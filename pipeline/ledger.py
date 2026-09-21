"""Build a per-position ledger from Wealthsimple exports (average-cost method).

Usage: python3 pipeline/ledger.py [activities.csv] [holdings.csv]
Defaults to the merged exports in the store (EXPORTS_DIR).
"""
import csv, collections, re, sys

import store

EXECUTED_AT = re.compile(r'executed at (\d{4}-\d{2}-\d{2})')
FX_RATE = re.compile(r'FX Rate: ([\d.]+)')


def load_activities(path=None):
    """Activities keyed by the date each one actually executed.

    Wealthsimple's effective_date/effective_time record when the *order was placed*, not when it filled.
    Nearly two thirds of trade stamps fall outside 09:30-16:00, and an order queued after the close is
    booked that evening but executes the next session -- 386 rows in this history, every one of them off
    by exactly a day. The description carries the real date, so that is what every downstream
    calculation gets: cost basis, forward-return scoring, the daily series and the charts.

    The booked pair stays alongside under booked_date/order_time, because it is what identifies a row to
    the broker (and to trade_id) and it is worth showing.
    """
    rows = list(csv.DictReader(open(path))) if path else store.load_activity_rows()
    for r in rows:
        m = EXECUTED_AT.search(r.get('description') or '')
        booked, executed = r['effective_date'], (m.group(1) if m else r['effective_date'])
        r['booked_date'], r['order_time'] = booked, r['effective_time']
        r['effective_date'] = executed
        # An order queued before its session has no fill time at all; keep it ahead of that day's live
        # orders rather than pretending 23:13 happened after 09:32.
        r['effective_time'] = r['order_time'] if executed == booked else '00:00:00'
        r['booked_currency'], r['booked_net_cash_amount'] = r['currency'], r['net_cash_amount']
        r['cash_currency'], r['cash_amount'] = r['currency'], r['net_cash_amount']
        fx = FX_RATE.search(r.get('description') or '')
        if r['activity_type'] == 'Trade' and r['currency'] == 'CAD' and fx:
            to_usd(r, float(fx.group(1)))
    expire_options(rows)
    return sorted(rows, key=lambda x: (x['effective_date'], x['effective_time'], x['booked_date'], x['order_time']))


def to_usd(r, rate):
    """A US-listed trade paid from CAD: the shares are USD, the cash that paid for them was CAD.

    Wealthsimple books a buy funded by an automatic conversion in CAD ("FX Rate: 1.4033" in the description) but
    the later sell in USD. Positions are keyed by currency, so left as booked the CAD buys are never closed: a
    round trip leaves phantom shares behind and the USD sells realise P&L against no cost. The security side
    (currency, unit_price, net_cash_amount) is restated in USD at the broker's rate; the cash leg stays as booked,
    because the booked currency is the balance the money actually came from (every US trade carries an FX rate,
    including ones paid from USD cash, so the rate alone says nothing about where the money was).
    """
    r['currency'] = 'USD'
    r['unit_price'] = repr(float(r['unit_price']) / rate)
    r['net_cash_amount'] = repr(round(float(r['net_cash_amount'] or 0) / rate, 2))


def expire_options(rows):
    """An expired contract is a sale at zero: close it in the currency it was bought in, so the premium is realised."""
    currency = {(r['account_type'], r['symbol']): r['currency'] for r in rows if r['activity_type'] == 'Trade'}
    for r in rows:
        if r['activity_type'] == 'OptionExpiry':
            cur = currency.get((r['account_type'], r['symbol']), 'USD')
            r.update(activity_type='Trade', activity_sub_type='EXPIRY', currency=cur, unit_price='0',
                     net_cash_amount='0', cash_currency=cur, cash_amount='0', booked_activity_type='OptionExpiry')


def cash_leg(a):
    """(currency, amount) of the cash an activity actually moved; rows not from load_activities fall back to as booked."""
    return a.get('cash_currency') or a['currency'], float(a.get('cash_amount', a['net_cash_amount']) or 0)


def holding_rows(path=None):
    """Raw holdings rows (positions and cash), without the 'As of' footer."""
    return [h for h in csv.DictReader(open(path or store.HOLDINGS)) if h.get('Quantity')]


def load_holdings(path=None):
    return holdings_from_rows(holding_rows(path))


def holdings_from_rows(rows):
    out = {}
    for h in rows:
        if not h.get('Quantity') or h['Security Type'] == 'CURRENCY':
            continue  # skips footer line and cash rows (ticker USD is also a ProShares ETF)
        key = (h['Account Type'], h['Symbol'], h['Market Price Currency'])
        out[key] = dict(q=float(h['Quantity']), price=float(h['Market Price']),
                        book=float(h['Book Value (Market)']), name=h['Name'],
                        book_cad=float(h['Book Value (CAD)']))
    return out


def build_positions(acts):
    pos = collections.defaultdict(lambda: dict(q=0.0, cost=0.0, realized=0.0, buys=0, sells=0,
                                               first=None, last=None, missing_cost=0.0, trades=[],
                                               opened=None, events=[]))
    for a in acts:
        t = a['activity_type']
        if t not in ('Trade', 'InternalSecurityTransfer'):
            continue
        key = (a['account_type'], a['symbol'], a['currency'])
        p = pos[key]
        qty, net = float(a['quantity']), float(a['net_cash_amount'])
        d = a['effective_date']
        p['first'] = p['first'] or d
        p['last'] = d
        if t == 'InternalSecurityTransfer':
            # Moves shares between WS accounts at a stated value; no gain/loss realized.
            # Early US stocks were held in CAD, so a transfer out may drain the CAD-keyed position.
            if qty > 0:
                if p['q'] <= 1e-9: p['opened'] = d
                p['q'] += qty; p['cost'] += net
            else:
                for k in [key] + [k for k in pos if k[:2] == key[:2] and k != key]:
                    src = pos[k]
                    if src['q'] >= -qty - 1e-9:
                        avg = src['cost'] / src['q']
                        src['cost'] -= avg * -qty; src['q'] += qty
                        if abs(src['q']) < 1e-9: src['q'] = src['cost'] = 0.0
                        break
            continue
        price = float(a['unit_price'] or 0)
        p['trades'].append((d, qty, price, net))
        if qty > 0:
            if p['q'] <= 1e-9: p['opened'] = d
            p['buys'] += 1; p['q'] += qty; p['cost'] += -net
        else:
            p['sells'] += 1
            sold = -qty
            if p['q'] < sold - 1e-9:  # selling shares with no recorded purchase
                p['missing_cost'] += sold - max(p['q'], 0)
            avg = p['cost'] / p['q'] if p['q'] > 1e-12 else 0
            gain = net - avg * min(sold, max(p['q'], 0))
            p['realized'] += gain
            p['events'].append((d, gain, p['opened']))
            p['cost'] -= avg * min(sold, max(p['q'], 0)); p['q'] += qty
            if abs(p['q']) < 1e-9:
                p['q'] = 0.0; p['cost'] = 0.0
    return pos


def income(acts):
    agg = collections.defaultdict(float)
    for a in acts:
        t = a['activity_type']
        if t in ('Dividend', 'Interest', 'Tax', 'Fee', 'BonusPayment'):
            agg[(a['account_type'], t, a['currency'])] += float(a['net_cash_amount'])
        elif t == 'MoneyMovement':
            agg[(a['account_type'], 'NetDeposits', a['currency'])] += float(a['net_cash_amount'])
    return agg


if __name__ == '__main__':
    act_path = sys.argv[1] if len(sys.argv) > 1 else None
    hold_path = sys.argv[2] if len(sys.argv) > 2 else None
    acts, H = load_activities(act_path), load_holdings(hold_path)
    pos = build_positions(acts)
    print(f"{len(acts)} activities {acts[0]['effective_date']} → {acts[-1]['effective_date']}\n")
    print(f"{'acct':8}{'symbol':24}{'cur':4}{'b':>4}{'s':>4}{'realized':>10}{'unreal':>10}{'qty':>10}  check")
    for key in sorted(pos, key=lambda k: (k[0], -pos[k]['realized'])):
        p, h = pos[key], H.get(key)
        unreal = h['q'] * h['price'] - h['book'] if h else 0
        chk = ''
        if h and abs(h['q'] - p['q']) > 1e-6: chk = f"qty mismatch hold={h['q']:g}"
        elif h and abs(h['book'] - p['cost']) > 1: chk = f"book {p['cost']:.2f} vs WS {h['book']:.2f}"
        elif not h and abs(p['q']) > 1e-6: chk = 'not in holdings'
        if p['missing_cost']: chk += f" no-cost {p['missing_cost']:g}"
        print(f"{key[0][:8]:8}{key[1]:24}{key[2]:4}{p['buys']:4}{p['sells']:4}{p['realized']:10.2f}{unreal:10.2f}{p['q']:10g}  {chk}")
    print()
    for k, v in sorted(income(acts).items()):
        print(k, round(v, 2))
