"""Build a per-position ledger from Wealthsimple exports (average-cost method).

Usage: python3 pipeline/ledger.py [activities.csv] [holdings.csv]
Defaults to the merged exports in the store (EXPORTS_DIR).
"""
import csv, collections, sys

import store


def load_activities(path=None):
    rows = list(csv.DictReader(open(path))) if path else store.load_activity_rows()
    return sorted(rows, key=lambda x: (x['effective_date'], x['effective_time']))


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
