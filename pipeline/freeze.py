"""Freeze simulation: what if you had stopped trading after a given transaction or day?

Frozen portfolio = everything held at the freeze point, left untouched:
  - securities keep their share count and earn total return (price + dividends reinvested, via Adj Close),
    so a split or distribution after the freeze is handled without extra bookkeeping
  - cash (CAD and USD) stays cash; USD cash still moves with the exchange rate
  - open options are closed at cost on the freeze day (expired contracts have no price history)
  - no trades, FX conversions or share transfers after the freeze; subscription fees still apply
Money deposited after the freeze is handled per `deposits`:
  'cash'    sits idle          'CCAD.TO'  buys the cash ETF you actually park money in (earns its yield)
  'XEQT.TO' / 'VOO'  bought the same day      'none'  ignored (compare returns only)

Returns are time-weighted, so deposits never inflate them; value gains subtract deposits.
"""
import collections, datetime as dt

import numpy as np
import pandas as pd

import engine
from engine import Calendar, is_option, position_key, replay, twr, trade_id

HORIZONS = [('1W', 7), ('1M', 30), ('3M', 91), ('6M', 182), ('1Y', 365)]
DEPOSIT_MODES = ('cash', 'none', engine.CASH_ETF, *engine.CFG['benchmarks'])


class Context:
    """Everything that doesn't depend on the freeze point, computed once per data build."""

    def __init__(self, acts):
        self.acts = acts
        self.cal = cal = Calendar(acts[0]['effective_date'])
        self.days = cal.days
        self.base = replay(acts, cal)
        self.actual = self.base['total']
        self.contrib = self.base['contrib']
        self.twr = twr(self.actual, self.contrib)
        mm = [(pd.Timestamp(a['effective_date']), cal.to_cad(float(a['net_cash_amount'] or 0), a['currency'], a['effective_date']))
              for a in acts if a['activity_type'] == 'MoneyMovement']
        self.deposits = cal.cumulative(mm)
        fees = [(pd.Timestamp(a['effective_date']), cal.to_cad(float(a['net_cash_amount'] or 0), a['currency'], a['effective_date']))
                for a in acts if a['activity_type'] == 'Fee']
        self.fees = cal.cumulative(fees)
        tickers = sorted(self.base['qty'])  # summed across accounts
        self.tickers = tickers
        self.px = pd.DataFrame({t: cal.price_cad(t) for t in tickers})
        adj = pd.DataFrame({t: cal.adj_cad(t) for t in tickers})
        self.adj = adj.where(adj > 0)
        self.bench = {b: cal.adj_cad(b) for b in engine.CFG['benchmarks']}
        self.invest_into = dict(self.bench)
        if engine.CASH_ETF not in self.invest_into:
            try:  # optional: only offered when that ETF has price history
                self.invest_into[engine.CASH_ETF] = cal.adj_cad(engine.CASH_ETF)
            except FileNotFoundError:
                pass

    # ------------------------------------------------------------ freeze point
    def snapshot(self, trade=None, date=None):
        """Holdings right after `trade` (id) or at the end of `date`. Returns (day index, label, positions, cash, options)."""
        acts = self.acts
        if trade:
            idx = next((i for i, a in enumerate(acts) if a['activity_type'] == 'Trade' and trade_id(a) == trade), None)
            if idx is None:
                raise ValueError('Unknown trade id')
            cutoff = acts[: idx + 1]
            a = acts[idx]
            label = f"after {a['effective_date']} {a['effective_time'][:5]} {a['account_type']} " \
                    f"{'BUY' if float(a['quantity']) > 0 else 'SELL'} {a['symbol'].strip()}"
            day = a['effective_date']
        else:
            day = date
            cutoff = [a for a in acts if a['effective_date'] <= day]
            label = f'end of {day}'
        fi = int(self.days.searchsorted(pd.Timestamp(day)))
        if fi >= len(self.days):
            raise ValueError('Freeze point is after the last price date')
        qty, cash, options = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float)
        for a in cutoff:
            t, net, cur = a['activity_type'], float(a['net_cash_amount'] or 0), a['currency']
            if t in ('Trade', 'InternalSecurityTransfer'):
                key = position_key(a, self.cal.tmap)
                if is_option(a['symbol']):
                    options[key] += float(a['quantity'])
                    options[(key, 'cost')] += -net
                else:
                    qty[key[1]] += float(a['quantity'])
            if t != 'InternalSecurityTransfer' and net:
                cash[cur] += net
        open_option_cost = sum(v for k, v in options.items() if isinstance(k[-1], str) and k[-1] == 'cost'
                               and options[k[0]] > 1e-9)
        cash['USD'] += open_option_cost  # options are USD; closed at cost
        positions = {t: q for t, q in qty.items() if abs(q) > 1e-9 and t in self.px}
        kept = sum(a['activity_type'] == 'Trade' for a in cutoff)
        return fi, label, positions, dict(cash), open_option_cost, kept

    def frozen_series(self, fi, positions, cash, deposits='cash'):
        cal, days = self.cal, self.days
        after = np.arange(len(days)) >= fi
        value = pd.Series(0.0, index=days)
        for t, q in positions.items():
            p0, a0 = self.px[t].iloc[fi], self.adj[t].iloc[fi]
            path = q * p0 * self.adj[t] / a0 if pd.notna(a0) and a0 > 0 else q * self.px[t]
            value += path.fillna(q * self.px[t])
        value += cash.get('CAD', 0.0) + cash.get('USD', 0.0) * cal.fx
        value += self.fees - self.fees.iloc[fi]  # subscription keeps billing
        post = self.deposits - self.deposits.iloc[fi]
        if deposits == 'cash':
            value += post
            contrib_after = self.contrib.iloc[fi] + post
        elif deposits in self.invest_into:
            px = self.invest_into[deposits]
            units = (post.diff().fillna(0.0).where(after, 0.0) / px).cumsum()
            value += units * px
            contrib_after = self.contrib.iloc[fi] + post
        else:
            contrib_after = pd.Series(self.contrib.iloc[fi], index=days)
        frozen = self.actual.where(~after, value)
        contrib = self.contrib.where(~after, contrib_after)
        return frozen, contrib

    # ------------------------------------------------------------ single freeze
    def run(self, trade=None, date=None, deposits='cash'):
        if deposits not in DEPOSIT_MODES:
            raise ValueError(f'deposits must be one of {DEPOSIT_MODES}')
        fi, label, positions, cash, option_cost, kept = self.snapshot(trade, date)
        frozen, contrib_f = self.frozen_series(fi, positions, cash, deposits)
        twr_f = twr(frozen, contrib_f)
        days, last = self.days, len(self.days) - 1
        # the freeze day's closing value is the common starting line for both paths
        start_value = float(frozen.iloc[fi])

        def window(end):
            ra = float(self.twr.iloc[end] / self.twr.iloc[fi] - 1)
            rf = float(twr_f.iloc[end] / twr_f.iloc[fi] - 1)
            ga = float((self.actual.iloc[end] - self.actual.iloc[fi]) - (self.contrib.iloc[end] - self.contrib.iloc[fi]))
            gf = float((frozen.iloc[end] - frozen.iloc[fi]) - (contrib_f.iloc[end] - contrib_f.iloc[fi]))
            return dict(end=days[end].strftime('%Y-%m-%d'), actual=round(ra, 5), frozen=round(rf, 5), diff=round(rf - ra, 5),
                        gain_actual=round(ga, 2), gain_frozen=round(gf, 2), gain_diff=round(gf - ga, 2))

        horizons = []
        for name, n in HORIZONS:
            target = days[fi] + pd.Timedelta(days=n)
            if target > days[last]:
                horizons.append(dict(name=name, end=None))
                continue
            horizons.append(dict(name=name, **window(int(days.searchsorted(target)))))
        horizons.append(dict(name='TO DATE', **window(last)))

        rows = []
        for t, q in sorted(positions.items(), key=lambda kv: -kv[1] * self.px[kv[0]].iloc[fi]):
            v0 = float(q * self.px[t].iloc[fi])
            a0, a1 = self.adj[t].iloc[fi], self.adj[t].iloc[last]
            v1 = float(v0 * a1 / a0) if pd.notna(a0) and pd.notna(a1) and a0 > 0 else float(q * self.px[t].iloc[last])
            now_qty = float(self.base['qty'][t].iloc[last]) if t in self.base['qty'] else 0.0
            if abs(v0) < 0.5 and abs(v1) < 0.5:
                continue  # dust (e.g. crypto remainders)
            rows.append(dict(ticker=t, qty=round(q, 6), value_then=round(v0, 2), value_now=round(v1, 2),
                             ret=round(v1 / v0 - 1, 5) if v0 else None, actual_qty_now=round(now_qty, 6)))
        cash_rows = [dict(ticker=f'{c} CASH', qty=round(v, 2), value_then=round(self.cal.to_cad(v, c, days[fi]), 2),
                          value_now=round(self.cal.to_cad(v, c), 2)) for c, v in cash.items() if abs(v) > 0.005]
        after_trades = sum(a['activity_type'] == 'Trade' for a in self.acts) - kept
        r = lambda s: [round(float(v), 2) for v in s]
        return dict(
            label=label, freeze_date=days[fi].strftime('%Y-%m-%d'), deposits=deposits, start_value=round(start_value, 2),
            trades_skipped=after_trades, options_closed_at_cost=round(option_cost, 2),
            dates=[d.strftime('%Y-%m-%d') for d in days[fi:]],
            actual=r(self.actual.iloc[fi:]), frozen=r(frozen.iloc[fi:]),
            contrib_actual=r(self.contrib.iloc[fi:]), contrib_frozen=r(contrib_f.iloc[fi:]),
            twr_actual=[round(float(v), 6) for v in (self.twr.iloc[fi:] / self.twr.iloc[fi])],
            twr_frozen=[round(float(v), 6) for v in (twr_f.iloc[fi:] / twr_f.iloc[fi])],
            bench={b: [round(float(v), 6) for v in (s.iloc[fi:] / s.iloc[fi])] for b, s in self.bench.items()},
            horizons=horizons, holdings=rows + cash_rows,
        )

    # ------------------------------------------------------------ sweep
    def sweep(self, step=5, horizons=(('1M', 30), ('3M', 91)), min_value=5000):
        """Freeze at every `step`-th trading day (end of day, deposits ignored): frozen minus actual return.
        Positive = doing nothing from that day would have beaten what you actually did."""
        days, last = self.days, len(self.days) - 1
        px, adj = self.px.to_numpy(), self.adj.to_numpy()
        cols = {t: i for i, t in enumerate(self.px.columns)}
        qty = np.zeros_like(px)
        for t, s in self.base['qty'].items():
            if t in cols:
                qty[:, cols[t]] += s.to_numpy()
        cad = self.base['cash_by_cur'].get('CAD', pd.Series(0.0, index=days)).to_numpy()
        usd = self.base['cash_by_cur'].get('USD', pd.Series(0.0, index=days)).to_numpy()
        opt_usd = self.base['option_value'].to_numpy() / self.cal.fx.to_numpy()  # carried as USD at cost
        fx = self.cal.fx.to_numpy()
        tw = self.twr.to_numpy()
        start = int(np.argmax(self.actual.to_numpy() >= min_value))  # tiny early balances swing too much to compare
        out = dict(dates=[], **{name: [] for name, _ in horizons}, to_date=[], trades_after=[])
        trade_days = np.array(sorted(pd.Timestamp(a['effective_date']) for a in self.acts if a['activity_type'] == 'Trade'),
                              dtype='datetime64[ns]')

        def frozen_value(f, end):
            w = qty[f] * px[f]
            ratio = np.where(np.isfinite(adj[f]) & (adj[f] > 0) & np.isfinite(adj[end]), adj[end] / np.where(adj[f] > 0, adj[f], 1), px[end] / np.where(px[f] > 0, px[f], 1))
            held = qty[f] != 0
            return float(np.nansum(np.where(held, w * ratio, 0.0))) + cad[f] + (usd[f] + opt_usd[f]) * fx[end]

        for f in range(start, last, step):
            v0 = frozen_value(f, f)
            if v0 <= 0:
                continue
            out['dates'].append(days[f].strftime('%Y-%m-%d'))
            for name, n in horizons:
                target = days[f] + pd.Timedelta(days=n)
                if target > days[last]:
                    out[name].append(None)
                    continue
                e = int(days.searchsorted(target))
                out[name].append(round((frozen_value(f, e) / v0 - 1) - (tw[e] / tw[f] - 1), 5))
            out['to_date'].append(round((frozen_value(f, last) / v0 - 1) - (tw[last] / tw[f] - 1), 5))
            out['trades_after'].append(int((trade_days > np.datetime64(days[f])).sum()))
        return out
