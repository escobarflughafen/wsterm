"""Compute everything the terminal app shows and write app/data.json.

Run: pipeline/.venv/bin/python pipeline/build_app.py
"""
import collections, csv, datetime as dt, json, math, os

import pandas as pd

import store
from ledger import load_activities, holding_rows, build_positions
from settings import BUILD_DIR
from prices import DATA, history, ticker_map
import engine

APP = str(BUILD_DIR)
CFG = engine.CFG
CAD_SUFFIXES = engine.CAD_SUFFIXES
is_option = engine.is_option


def category(symbol, account):
    if account == 'Crypto':
        return 'speculative'
    if is_option(symbol):
        return 'speculative'
    for cat in ('core', 'cash', 'speculative'):
        if symbol in CFG['categories'][cat]:
            return cat
    return 'stocks'


def r2(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def main():
    if not store.has_data():
        print('no exports imported yet: upload activities + holdings CSVs first')
        raise SystemExit(3)
    acts = load_activities()
    hold_rows = holding_rows()
    tmap = ticker_map()
    cal = engine.Calendar(acts[0]['effective_date'])
    fx_now, to_cad = cal.fx_now, cal.to_cad
    base = engine.replay(acts, cal)
    total, contrib, flows, value, accounts = base['total'], base['contrib'], base['flows'], base['value'], base['accounts']
    twr = engine.twr(total, contrib)
    bench = {}
    for b in CFG['benchmarks']:
        v, idx = engine.benchmark_value(b, contrib, cal)
        bench[b] = dict(value=v, twr=idx)
    days = cal.days

    sleeve = engine.invested_sleeve(acts, cal, base)
    sleeve_bench = {}
    for b in CFG['benchmarks']:
        adj = cal.adj_cad(b)
        flow = sleeve['capital'].diff().fillna(sleeve['capital'].iloc[0])
        sleeve_bench[b] = dict(value=(flow / adj).cumsum() * adj, twr=adj / adj.iloc[0])

    series = dict(
        dates=[d.strftime('%Y-%m-%d') for d in days],
        invested=dict(
            value=[r2(v) for v in sleeve['value']], capital=[r2(v) for v in sleeve['capital']],
            twr=[round(float(v), 5) for v in sleeve['twr']],
            bench={b: dict(value=[r2(v) for v in x['value']], twr=[round(float(v), 5) for v in x['twr']])
                   for b, x in sleeve_bench.items()}),
        total=[r2(v) for v in total], contrib=[r2(v) for v in contrib],
        twr=[round(float(v), 5) for v in twr],
        accounts={a: [r2(v) for v in value[a]] for a in accounts},
        account_contrib={a: [r2(v) for v in flows[a]] for a in accounts},
        bench={b: dict(value=[r2(v) for v in bench[b]['value']], twr=[round(float(v), 5) for v in bench[b]['twr']])
               for b in bench},
    )

    # ---------- current holdings ----------
    rows, acct_val = [], collections.defaultdict(float)
    for h in hold_rows:
        acct, sym, cur = h['Account Type'], h['Symbol'], h['Market Value Currency']
        mv_cad = to_cad(float(h['Market Value']), cur)
        acct_val[acct] += mv_cad
        if h['Security Type'] == 'CURRENCY':
            rows.append(dict(acct=acct, sym=f'{sym} CASH', name='Cash', cat='cash', cur=cur, qty=None, avg=None,
                             px=None, mv=r2(float(h['Market Value'])), mv_cad=r2(mv_cad), upl=0, upl_pct=None, day_pct=None))
            continue
        q, book, px = float(h['Quantity']), float(h['Book Value (Market)']), float(h['Market Price'])
        t = tmap.get((sym, h['Market Price Currency']))
        day = None
        if t:
            c = history(t)['Close']
            if len(c) > 1:
                day = c.iloc[-1] / c.iloc[-2] - 1
        rows.append(dict(acct=acct, sym=sym, name=h['Name'], cat=category(sym, acct), cur=cur, qty=q, avg=r2(book / q),
                         px=px, mv=r2(q * px), mv_cad=r2(mv_cad), upl=r2(q * px - book),
                         upl_pct=round((q * px / book - 1), 4) if book else None,
                         day_pct=None if day is None else round(float(day), 4)))
    total_now = sum(acct_val.values())
    for row in rows:
        row['weight'] = round(row['mv_cad'] / total_now, 4)

    # ---------- realized P&L ----------
    pos = build_positions(acts)
    positions = []
    for (acct, sym, cur), p in pos.items():
        if not p['buys'] and not p['sells']:
            continue
        positions.append(dict(acct=acct, sym=sym, cur=cur, cat=category(sym, acct), buys=p['buys'], sells=p['sells'],
                              realized=r2(p['realized']), realized_cad=r2(to_cad(p['realized'], cur)),
                              open=p['q'] > 1e-9, first=p['first'], last=p['last']))
    by_cat = collections.defaultdict(lambda: dict(realized_cad=0.0, sells=0, wins=0))
    by_year = collections.defaultdict(float)
    hold_buckets = {k: dict(n=0, sum_cad=0.0, wins=0) for k in ('≤7D', '8–30D', '31–90D', '>90D')}
    for (acct, sym, cur), p in pos.items():
        for d, gain, opened in p['events']:
            g = to_cad(gain, cur, d)
            c = by_cat[category(sym, acct)]
            c['realized_cad'] += g; c['sells'] += 1; c['wins'] += gain > 0
            by_year[d[:4]] += g
            if opened:
                n = (dt.date.fromisoformat(d) - dt.date.fromisoformat(opened)).days
                b = hold_buckets['≤7D' if n <= 7 else '8–30D' if n <= 30 else '31–90D' if n <= 90 else '>90D']
                b['n'] += 1; b['sum_cad'] += g; b['wins'] += gain > 0

    # ---------- trades with hindsight ----------
    trades = []
    avg_state = collections.defaultdict(lambda: [0.0, 0.0])  # key -> [qty, cost]
    for a in acts:
        if a['activity_type'] != 'Trade':
            continue
        sym, cur, acct = a['symbol'], a['currency'], a['account_type']
        q, price = float(a['quantity']), float(a['unit_price'] or 0)
        st = avg_state[(acct, sym, cur)]
        avg_before = st[1] / st[0] if st[0] > 1e-9 else None
        if q > 0:
            st[0] += q; st[1] += q * price
        elif st[0] > 1e-9:
            st[1] -= st[1] / st[0] * -q; st[0] += q
        t = None if is_option(sym) else tmap.get((sym, cur))
        now, edge = None, None
        if t:
            df = history(t)
            splits = df.loc[df.index > pd.Timestamp(a['effective_date']), 'Stock Splits']
            factor = float(splits[splits > 0].prod()) if (splits > 0).any() else 1.0
            now = float(df['Close'].iloc[-1]) * factor  # today's price in trade-date share units
            if cur == 'CAD' and not t.endswith(CAD_SUFFIXES):
                now *= fx_now
            edge = (now - price) * q  # buy: gain since; sell: negative if it kept rising
            if q < 0:
                edge = (price - now) * -q
        trades.append(dict(id=engine.trade_id(a), cat=category(sym, acct), date=a['effective_date'], acct=acct, sym=sym, cur=cur, side='BUY' if q > 0 else 'SELL',
                           qty=abs(q), px=round(price, 4), amt=r2(float(a['net_cash_amount'])),
                           now=None if now is None else round(now, 4), edge=r2(edge),
                           edge_cad=None if edge is None else r2(to_cad(edge, cur)),
                           avgdown=bool(q > 0 and avg_before and price < avg_before * 0.98
                                        and category(sym, acct) in ('stocks', 'speculative'))))

    # ---------- monthly contributions into the equity core ----------
    groups = CFG.get('equivalents', {})
    tracked = sorted({sym for syms in groups.values() for sym in syms} | set(CFG['categories']['core']))
    months = sorted({a['effective_date'][:7] for a in acts})
    contrib_cad = {sym: collections.defaultdict(float) for sym in tracked}
    contrib_sh = {sym: collections.defaultdict(float) for sym in tracked}
    totals = collections.defaultdict(lambda: dict(cad=0.0, shares=0.0, buys=0))
    for a in acts:
        sym = a['symbol']
        if a['activity_type'] != 'Trade' or sym not in contrib_cad:
            continue
        m, q = a['effective_date'][:7], float(a['quantity'])
        cad = to_cad(-float(a['net_cash_amount']), a['currency'], a['effective_date'])  # buys positive
        contrib_cad[sym][m] += cad
        contrib_sh[sym][m] += q
        t = totals[sym]
        t['cad'] += cad
        t['shares'] += q
        t['buys'] += q > 0

    def pace(values):
        """values: list aligned to `months`. Averages over calendar months, not just months with a purchase."""
        def avg(window):
            return round(sum(window) / len(window), 2) if window else None
        last3, prev3, last6, prev6 = values[-3:], values[-6:-3], values[-6:], values[-12:-6]
        active = [v for v in values if abs(v) > 1]
        return dict(total=round(sum(values), 2), last3=avg(last3), prev3=avg(prev3), last6=avg(last6), prev6=avg(prev6),
                    run_rate=round(sum(last6) / max(1, len(last6)) * 12, 2), months=len(values),
                    active_months=len(active), skipped_last6=sum(1 for v in last6 if abs(v) <= 1),
                    average=round(sum(values) / len(values), 2) if values else 0)

    group_series, group_pace = {}, {}
    for name, syms in groups.items():
        vals = [round(sum(contrib_cad[sym].get(m, 0.0) for sym in syms if sym in contrib_cad), 2) for m in months]
        group_series[name] = vals
        group_pace[name] = pace(vals)
    core_vals = [round(sum(contrib_cad[sym].get(m, 0.0) for sym in tracked), 2) for m in months]
    holdings_qty = collections.defaultdict(float)
    for row in rows:
        holdings_qty[row['sym']] += row['qty'] or 0
    contributions = dict(
        months=months, groups=group_series, group_pace=group_pace, core=core_vals, core_pace=pace(core_vals),
        tickers=[dict(sym=sym, group=next((g for g, syms in groups.items() if sym in syms), '—'),
                      cad=r2(totals[sym]['cad']), shares=round(totals[sym]['shares'], 4), buys=totals[sym]['buys'],
                      avg_cost=r2(totals[sym]['cad'] / totals[sym]['shares']) if totals[sym]['shares'] > 0 else None,
                      held=round(holdings_qty.get(sym, 0), 4),
                      monthly=[r2(contrib_cad[sym].get(m, 0.0)) for m in months])
                 for sym in tracked if abs(totals[sym]['cad']) > 1],
    )

    # ---------- allocation & rules ----------
    alloc = collections.defaultdict(float)
    for row in rows:
        alloc[row['cat']] += row['mv_cad']
    invested = sum(v for k, v in alloc.items() if k != 'cash')
    R = CFG['rules']
    today = dt.date.fromisoformat(series['dates'][-1])
    rules = []

    def rule(name, ok, detail, items=()):
        rules.append(dict(name=name, ok=ok, detail=detail, items=list(items)))

    big = [f"{x['acct']} {x['sym']} {x['weight']:.1%}" for x in rows
           if x['cat'] == 'stocks' and x['weight'] > R['max_single_stock_pct']]
    rule(f"SINGLE STOCK ≤ {R['max_single_stock_pct']:.0%} OF TOTAL", not big, 'All positions within limit' if not big else f'{len(big)} over limit', big)
    spec_pct = alloc['speculative'] / invested if invested else 0
    rule(f"SPECULATIVE ≤ {R['max_speculative_pct_of_invested']:.0%} OF INVESTED", spec_pct <= R['max_speculative_pct_of_invested'],
         f'Now {spec_pct:.1%}', [f"{x['acct']} {x['sym']} ${x['mv_cad']:,.0f}" for x in rows if x['cat'] == 'speculative'])
    # Registered accounts (TFSA, FHSA, RRSP...): a loss there is permanent and cannot be claimed, so the same
    # guardrails apply to every one of them, not just the TFSA.
    registered = set(CFG.get('registered_accounts', ['TFSA']))
    present = [a for a in sorted({r['acct'] for r in rows}) if a in registered]
    lev_reg = [f"{x['acct']} {x['sym']} ${x['mv_cad']:,.0f}" for x in rows if x['acct'] in registered and x['cat'] == 'speculative']
    rule('NO LEVERAGED/THEMATIC ETFS IN REGISTERED ACCOUNTS', not lev_reg,
         ('Clean' if not lev_reg else f'{len(lev_reg)} held') + (f" · checking {', '.join(present)}" if present else ''), lev_reg)
    dd = [f"{x['acct']} {x['sym']} {x['upl_pct']:+.1%}" for x in rows
          if x['upl_pct'] is not None and x['upl_pct'] <= R['review_drawdown_pct'] and x['cat'] != 'cash']
    rule(f"REVIEW POSITIONS ≤ {R['review_drawdown_pct']:.0%}", not dd, 'None below threshold' if not dd else f'{len(dd)} need a decision', dd)
    cutoff = (today - dt.timedelta(days=R['averaging_down_lookback_days'])).isoformat()
    ad = [f"{t['date']} {t['acct']} {t['sym']} {t['qty']:g} @ {t['px']:g}" for t in trades if t['avgdown'] and t['date'] >= cutoff]
    rule(f"NO AVERAGING DOWN (LAST {R['averaging_down_lookback_days']}D)", not ad, f'{len(ad)} buys below average cost', ad[-15:])
    if CFG['rules'].get('require_monthly_core_buy'):
        recent = contributions['months'][-6:]
        missed = [m for m, v in zip(contributions['months'], contributions['core'])][-6:]
        missed = [m for m, v in zip(recent, contributions['core'][-6:]) if abs(v) <= 1]
        rule('CORE ETF PURCHASE EVERY MONTH', not missed, f"last 6 months: {6 - len(missed)}/6 with a purchase", missed)

    month = today.strftime('%Y-%m')
    cap = R.get('max_trades_per_month_registered', R.get('max_tfsa_trades_per_month', 20))
    per_acct = collections.defaultdict(collections.Counter)
    for t in trades:
        if t['acct'] in registered:
            per_acct[t['acct']][t['date'][:7]] += 1
    over = [f'{a} {month}: {c[month]} trades' for a, c in sorted(per_acct.items()) if c[month] > cap]
    recent = [f'{a} {m}: {n}' for a, c in sorted(per_acct.items()) for m, n in sorted(c.items())[-3:]]
    rule(f'REGISTERED TRADES ≤ {cap}/MONTH', not over,
         f"{month}: " + (', '.join(f'{a} {c[month]}' for a, c in sorted(per_acct.items())) or 'no registered trades'),
         over + recent[-9:])

    # ---------- income ----------
    income = collections.defaultdict(lambda: collections.defaultdict(float))
    for a in acts:
        if a['activity_type'] in ('Dividend', 'Interest', 'Tax', 'Fee', 'BonusPayment'):
            income[a['effective_date'][:7]][a['activity_type']] += to_cad(float(a['net_cash_amount']), a['currency'], a['effective_date'])

    events = []
    ev_path = os.path.join(DATA, 'events.csv')
    if os.path.exists(ev_path):
        events = list(csv.DictReader(open(ev_path)))

    contrib_now = float(contrib.iloc[-1])
    names = {}
    for a in acts:
        if a['symbol'] and ' - ' in a['description']:
            names.setdefault((a['symbol'], a['currency']), a['description'].split(' - ', 1)[1].split(':')[0].strip())
    held_keys = {(x['sym'], x['cur']) for x in rows}
    tickers = [dict(sym=s_, cur=c_, yahoo=y_, name=names.get((s_, c_), s_), held=(s_, c_) in held_keys)
               for (s_, c_), y_ in sorted(tmap.items()) if y_]

    data = dict(
        tickers=tickers,
        asof=(store.holdings_asof() or '').replace('T', ' '),
        built=dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        price_date=series['dates'][-1], fx=fx_now,
        summary=dict(total=r2(total_now), contrib=r2(contrib_now), gain=r2(total_now - contrib_now),
                     unreal=r2(sum(to_cad(x['upl'] or 0, x['cur']) for x in rows)),
                     realized=r2(sum(p['realized_cad'] for p in positions)),
                     day=r2(sum(x['mv_cad'] * x['day_pct'] / (1 + x['day_pct']) for x in rows if x['day_pct'] is not None)),
                     twr=round(float(twr.iloc[-1] - 1), 4),
                     bench={b: dict(value=r2(bench[b]['value'].iloc[-1]), twr=round(float(bench[b]['twr'].iloc[-1] - 1), 4)) for b in bench}),
        accounts=[dict(acct=a, value=r2(acct_val[a]), contrib=r2(flows[a].iloc[-1]), gain=r2(acct_val[a] - flows[a].iloc[-1]),
                       weight=round(acct_val[a] / total_now, 4)) for a in accounts],
        holdings=sorted(rows, key=lambda x: -x['mv_cad']),
        series=series,
        positions=sorted(positions, key=lambda x: x['realized_cad']),
        by_cat=[dict(cat=k, realized_cad=r2(v['realized_cad']), sells=v['sells'], win=round(v['wins'] / v['sells'], 3)) for k, v in by_cat.items()],
        by_year=[dict(year=k, realized_cad=r2(v)) for k, v in sorted(by_year.items())],
        hold_buckets=[dict(bucket=k, n=v['n'], sum_cad=r2(v['sum_cad']), win=round(v['wins'] / v['n'], 3) if v['n'] else None)
                      for k, v in hold_buckets.items()],
        trades=trades[::-1],
        alloc=dict(now={k: r2(v) for k, v in alloc.items()}, invested=r2(invested), targets=CFG['targets']),
        rules=rules,
        income=[dict(month=m, **{k: r2(v) for k, v in d.items()}) for m, d in sorted(income.items())],
        contributions=contributions,
        events=events,
    )
    os.makedirs(APP, exist_ok=True)
    with open(os.path.join(APP, 'data.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    s = data['summary']
    print(f"total ${s['total']:,.0f}  contrib ${s['contrib']:,.0f}  gain ${s['gain']:,.0f}  twr {s['twr']:+.1%}  "
          + '  '.join(f"{b} ${v['value']:,.0f}" for b, v in s['bench'].items()))


if __name__ == '__main__':
    main()
