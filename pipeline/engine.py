"""Portfolio replay engine: daily value history from activities, plus what-if simulation."""
import collections, hashlib, json, os

import pandas as pd

from ledger import build_positions
from settings import CONFIG_PATH
from prices import history, ticker_map, fx_usdcad

CFG = json.load(open(CONFIG_PATH))
CAD_SUFFIXES = ('.TO', '.NE', '-CAD')
CASH_ETF = CFG.get('cash_etf', 'CCAD.TO')


def is_option(symbol):
    return len(symbol) > 10


def trade_id(a):
    raw = '|'.join(a[k] for k in ('effective_date', 'effective_time', 'account_id', 'symbol', 'quantity', 'net_cash_amount'))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def position_key(a, tmap):
    sym = a['symbol']
    return (a['account_type'], sym if is_option(sym) else tmap.get((sym, a['currency'])) or sym)


def as_traded_close(ticker):
    """Close in as-traded units: undo split adjustment for dates before each split."""
    df = history(ticker)
    splits = df['Stock Splits'].where(df['Stock Splits'] > 0, 1.0)
    after = splits[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    return df['Close'] * after


class Calendar:
    def __init__(self, first_date):
        tmap = ticker_map()
        last = max(history(t).index[-1] for t in {'VOO', 'XEQT.TO'})
        self.days = pd.bdate_range(first_date, last)
        fx = fx_usdcad()
        self.fx = fx.reindex(fx.index.union(self.days)).ffill().bfill().reindex(self.days)
        self.fx_now = float(self.fx.iloc[-1])
        self.tmap = tmap
        self._px = {}

    def to_cad(self, amount, currency, d=None):
        if currency != 'USD':
            return amount
        return amount * (float(self.fx.asof(pd.Timestamp(d))) if d else self.fx_now)

    def cumulative(self, events):
        s = pd.Series(0.0, index=self.days)
        for d, v in events:
            i = self.days.searchsorted(d)
            if i < len(self.days):
                s.iloc[i] += v
        return s.cumsum()

    def price_cad(self, ticker):
        if ticker not in self._px:
            px = as_traded_close(ticker)
            px = px.reindex(px.index.union(self.days)).ffill().reindex(self.days).fillna(0.0)
            self._px[ticker] = px if ticker.endswith(CAD_SUFFIXES) else px * self.fx
        return self._px[ticker]

    def adj_cad(self, ticker):
        df = history(ticker)
        adj = df['Adj Close'].reindex(df.index.union(self.days)).ffill().reindex(self.days).bfill()
        return adj if ticker.endswith(CAD_SUFFIXES) else adj * self.fx


def replay(acts, cal):
    """Daily CAD value per account, net deposits, and ending quantities."""
    qty_events = collections.defaultdict(list)
    option_cost = collections.defaultdict(list)
    cash_events = collections.defaultdict(list)
    flow_events = collections.defaultdict(list)
    for a in acts:
        d, t, cur = pd.Timestamp(a['effective_date']), a['activity_type'], a['currency']
        net = float(a['net_cash_amount'] or 0)
        if t in ('Trade', 'InternalSecurityTransfer'):
            key = position_key(a, cal.tmap)
            qty_events[key].append((d, float(a['quantity'])))
            if is_option(a['symbol']):
                option_cost[key].append((d, cal.to_cad(-net, cur, d)))
        if t == 'InternalSecurityTransfer':
            flow_events[a['account_type']].append((d, cal.to_cad(net, cur, d)))  # shares enter/leave tracked accounts
        elif net:
            cash_events[(a['account_type'], cur)].append((d, net))
        if t == 'MoneyMovement':
            flow_events[a['account_type']].append((d, cal.to_cad(net, cur, d)))

    accounts = sorted({a['account_type'] for a in acts})
    value = {acct: pd.Series(0.0, index=cal.days) for acct in accounts}
    ending, qty, option_value = {}, {}, pd.Series(0.0, index=cal.days)
    for (acct, key), ev in qty_events.items():
        q = cal.cumulative(ev).round(8)
        if is_option(key):  # no price history for expired contracts: carry open options at cost (CAD at trade date)
            v = cal.cumulative(option_cost[(acct, key)]).where(q > 0, 0.0)
            option_value += v
        else:
            v = q * cal.price_cad(key)
            qty[key] = qty[key] + q if key in qty else q
        value[acct] += v
        if abs(q.iloc[-1]) > 1e-9:
            ending[(acct, key)] = dict(qty=float(q.iloc[-1]), value=float(v.iloc[-1]))
    cash_now, cash_by_cur = {}, {}
    for (acct, cur), ev in cash_events.items():
        c = cal.cumulative(ev)
        cash_by_cur[cur] = cash_by_cur[cur] + c if cur in cash_by_cur else c
        value[acct] += c * (cal.fx if cur == 'USD' else 1.0)
        cash_now[(acct, cur)] = float(c.iloc[-1])
    flows = {acct: cal.cumulative(flow_events[acct]) for acct in accounts}
    total = sum(value.values())
    contrib = sum(flows.values())
    return dict(value=value, total=total, contrib=contrib, flows=flows, ending=ending, cash=cash_now, accounts=accounts,
                qty=qty, cash_by_cur=cash_by_cur, option_value=option_value)


def invested_sleeve(acts, cal, base):
    """Everything except cash and cash ETFs: the money you actually put at risk.

    Flows are the trades themselves (a buy moves money in, a sell moves it out) and dividends, which leave the sleeve
    as cash. Comparing this against a benchmark fed by the same flows answers "did my picks beat XEQT?" without the
    portfolio's cash position deciding the answer.
    """
    cash_symbols = set(CFG['categories'].get('cash', []))
    cash_tickers = {t for (sym, cur), t in cal.tmap.items() if t and sym in cash_symbols}
    value = pd.Series(0.0, index=cal.days)
    for ticker, q in base['qty'].items():
        if ticker not in cash_tickers:
            value += q * cal.price_cad(ticker)
    value += base['option_value']

    flows = []
    for a in acts:
        t, cur, sym = a['activity_type'], a['currency'], a['symbol']
        net = float(a['net_cash_amount'] or 0)
        d = pd.Timestamp(a['effective_date'])
        if t == 'Trade' and sym not in cash_symbols:
            flows.append((d, cal.to_cad(-net, cur, d)))              # buy: money in, sell: money out
        elif t == 'InternalSecurityTransfer' and sym not in cash_symbols:
            flows.append((d, cal.to_cad(net, cur, d)))               # shares entering/leaving the tracked accounts
        elif t == 'Dividend' and sym and sym not in cash_symbols:
            flows.append((d, cal.to_cad(-net, cur, d)))              # paid out to cash, so it leaves the sleeve
    capital = cal.cumulative(flows)
    return dict(value=value, capital=capital, twr=twr(value, capital))


def twr(total, contrib):
    daily_flow = contrib.diff().fillna(contrib.iloc[0])
    prev = total.shift(1)
    r = ((total - daily_flow) / prev - 1).where(prev > 50, 0.0).fillna(0.0)
    return (1 + r).cumprod()


def benchmark_value(ticker, contrib, cal):
    """Value if every net deposit had bought `ticker` the same day (dividends reinvested)."""
    adj = cal.adj_cad(ticker)
    daily_flow = contrib.diff().fillna(contrib.iloc[0])
    return (daily_flow / adj).cumsum() * adj, adj / adj.iloc[0]


# ---------------------------------------------------------------- what-if
def apply_exclusions(acts, exclude, tmap):
    """Drop excluded trades; shrink later sells/transfers-out that no longer have shares to cover them."""
    exclude = set(exclude)
    out, held, clipped, removed = [], collections.defaultdict(float), [], 0
    for a in acts:
        t = a['activity_type']
        if t == 'Trade' and trade_id(a) in exclude:
            removed += 1
            continue
        if t not in ('Trade', 'InternalSecurityTransfer'):
            out.append(a)
            continue
        key = position_key(a, tmap)
        q = float(a['quantity'])
        if q < 0 and held[key] < -q - 1e-9:
            avail = max(held[key], 0.0)
            if avail <= 1e-9:
                clipped.append((a['effective_date'], a['account_type'], a['symbol'], -q, 0.0))
                continue
            scale = avail / -q
            a = dict(a, quantity=str(-avail), net_cash_amount=str(float(a['net_cash_amount'] or 0) * scale))
            clipped.append((a['effective_date'], a['account_type'], a['symbol'], -q, avail))
            q = -avail
        held[key] += q
        out.append(a)
    return out, removed, clipped


def redirect_cash(actual, sim, ticker, cal, acts_actual, acts_sim):
    """Invest the cash the simulation frees into `ticker`, buying on the day that cash appears.

    The delta is tracked per currency: USD cash is converted at the rate of the day it appears when buying the
    ETF, and at today's rate when it is subtracted from the simulated total — which is how the replay values
    idle cash. Mixing the two rates would leak an FX gain into the comparison.
    """
    def cash_by_currency(acts):
        events = collections.defaultdict(list)
        for a in acts:
            net = float(a['net_cash_amount'] or 0)
            if net and a['activity_type'] != 'InternalSecurityTransfer':
                events[a['currency']].append((pd.Timestamp(a['effective_date']), net))
        return {cur: cal.cumulative(ev) for cur, ev in events.items()}

    before, after = cash_by_currency(acts_actual), cash_by_currency(acts_sim)
    zero = pd.Series(0.0, index=cal.days)
    deltas = {cur: after.get(cur, zero) - before.get(cur, zero) for cur in set(before) | set(after)}

    at_date = sum((d * cal.fx if cur == 'USD' else d) for cur, d in deltas.items())      # CAD when it appeared
    today = sum((d * cal.fx_now if cur == 'USD' else d) for cur, d in deltas.items())    # CAD valued now
    adj = cal.adj_cad(ticker)
    units = (at_date.diff().fillna(at_date.iloc[0]) / adj).cumsum()
    return units * adj, today  # ETF position value, and the idle cash it replaces


def simulate(acts, exclude, redirect=None):
    """redirect: ticker the freed cash buys instead of sitting idle (a benchmark, or the cash ETF)."""
    tmap = ticker_map()
    cal = Calendar(acts[0]['effective_date'])
    base = replay(acts, cal)
    acts_sim, removed, clipped = apply_exclusions(acts, exclude, tmap)
    sim = replay(acts_sim, cal)
    total_sim = sim['total'].copy()
    etf = None
    if redirect:
        etf, delta = redirect_cash(base, sim, redirect, cal, acts, acts_sim)
        total_sim = total_sim + etf - delta

    def realized_cad(a_list):
        return sum(cal.to_cad(p['realized'], cur) for (_, _, cur), p in build_positions(a_list).items())

    diffs = []
    for key in set(base['ending']) | set(sim['ending']):
        b, s_ = base['ending'].get(key, dict(qty=0, value=0)), sim['ending'].get(key, dict(qty=0, value=0))
        if abs(b['qty'] - s_['qty']) > 1e-6 and abs(b['value'] - s_['value']) >= 0.5:
            diffs.append(dict(acct=key[0], sym=key[1], qty=round(b['qty'], 6), sim_qty=round(s_['qty'], 6),
                              value=round(b['value'], 2), sim_value=round(s_['value'], 2)))
    for key in set(base['cash']) | set(sim['cash']):
        b, s_ = base['cash'].get(key, 0), sim['cash'].get(key, 0)
        if abs(b - s_) > 0.01:
            diffs.append(dict(acct=key[0], sym=f'{key[1]} CASH', qty=round(b, 2), sim_qty=round(s_, 2),
                              value=round(cal.to_cad(b, key[1]), 2), sim_value=round(cal.to_cad(s_, key[1]), 2)))
    if redirect:
        diffs.append(dict(acct='(redirect)', sym=redirect, qty=None, sim_qty=None, value=0.0, sim_value=round(float(etf.iloc[-1]), 2)))
    contrib = base['contrib']
    r = lambda x: round(float(x), 2)
    return dict(
        dates=[d.strftime('%Y-%m-%d') for d in cal.days],
        actual=[r(v) for v in base['total']], simulated=[r(v) for v in total_sim], contrib=[r(v) for v in contrib],
        summary=dict(actual=r(base['total'].iloc[-1]), simulated=r(total_sim.iloc[-1]), contrib=r(contrib.iloc[-1]),
                     realized_actual=r(realized_cad(acts)), realized_sim=r(realized_cad(acts_sim)),
                     removed=removed, clipped=len(clipped)),
        clipped=[dict(date=c[0], acct=c[1], sym=c[2], qty=c[3], kept=c[4]) for c in clipped],
        diffs=sorted(diffs, key=lambda x: -abs(x['sim_value'] - x['value'])),
    )
