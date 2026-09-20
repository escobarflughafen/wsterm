"""Compute everything the terminal app shows and write app/data.json.

Run: pipeline/.venv/bin/python pipeline/build_app.py
"""
import collections, csv, datetime as dt, json, math, os

import pandas as pd

import audit
import options as opt
import store
from ledger import load_activities, holding_rows, build_positions
from settings import BUILD_DIR
from prices import PRIVATE_DATA, history, ticker_map
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
    for cat in ('core', 'cash', 'satellite', 'speculative'):
        if symbol in CFG['categories'].get(cat, ()):
            return cat
    return 'stocks'


def r2(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def main():
    if not store.has_data():
        print('no activities imported yet: upload an activities CSV first')
        raise SystemExit(3)
    acts = load_activities()
    hold_rows = holding_rows() if store.has_holdings() else []
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
    # The activity ledger is the source: it is what an import updates, complete or incremental, so
    # everything on every screen moves the moment trades land. Wealthsimple's snapshot is kept purely
    # as an independent check (see the reconciliation below) -- never as the source, because a holdings
    # report that is a day older than your trades would otherwise silently freeze NAV and positions.
    names = {}
    for h in hold_rows:                              # the report has the nicest display names; take those
        names[(h['Symbol'], h['Market Price Currency'])] = h['Name']
    for a in acts:
        if a['symbol']:
            names.setdefault((a['symbol'], a['currency']), a.get('name') or
                             (a['description'].split(' - ', 1)[1].split(':')[0].strip()
                              if ' - ' in a['description'] else a['symbol']))
    rows, acct_val = [], collections.defaultdict(float)
    pos = build_positions(acts)
    for (acct, sym, cur), p in pos.items():
        q = float(p['q'])
        if q <= 1e-9:
            continue
        t = None if is_option(sym) else tmap.get((sym, cur))
        px = day = None
        if t:
            closes = history(t)['Close'].dropna()
            if len(closes):
                px = float(closes.iloc[-1])
            if len(closes) > 1:
                day = float(closes.iloc[-1] / closes.iloc[-2] - 1)
        if px is None:
            px = float(p['cost']) / q if q else 0.0
        mv = q * px
        mv_cad = to_cad(mv, cur)
        book = float(p['cost'])
        acct_val[acct] += mv_cad
        rows.append(dict(acct=acct, sym=sym, name=names.get((sym, cur), sym), cat=category(sym, acct), cur=cur,
                         qty=q, avg=r2(book / q), px=r2(px), mv=r2(mv), mv_cad=r2(mv_cad),
                         upl=r2(mv - book), upl_pct=round(mv / book - 1, 4) if book else None,
                         day_pct=None if day is None else round(float(day), 4)))
    for (acct, cur), amount in base['cash'].items():
        if abs(amount) <= 0.005:
            continue
        mv_cad = to_cad(amount, cur)
        acct_val[acct] += mv_cad
        rows.append(dict(acct=acct, sym=f'{cur} CASH', name='Cash', cat='cash', cur=cur, qty=None, avg=None,
                         px=None, mv=r2(amount), mv_cad=r2(mv_cad), upl=0, upl_pct=None, day_pct=None))
    total_now = sum(acct_val.values())
    for row in rows:
        row['weight'] = round(row['mv_cad'] / total_now, 4) if total_now else 0

    # ---------- snapshot reconciliation ----------
    # The holdings report is Wealthsimple's own count on a given date. It no longer drives anything, so
    # its job is to disagree loudly when the ledger and the broker do not match, and to say plainly when
    # it is simply older than the trades rather than wrong. Quantities are compared per account and
    # symbol (summed across booking currencies); cash is compared per currency.
    reconcile = None
    if hold_rows:
        snapshot, report_cad = collections.defaultdict(float), 0.0
        for h in hold_rows:
            acct, cur = h['Account Type'], h['Market Value Currency']
            report_cad += to_cad(float(h['Market Value']), cur)
            if h['Security Type'] == 'CURRENCY':
                snapshot[(acct, f"{h['Symbol']} CASH")] += float(h['Market Value'])
            else:
                snapshot[(acct, h['Symbol'])] += float(h['Quantity'])
        ours = collections.defaultdict(float)
        for r in rows:
            ours[(r['acct'], r['sym'])] += r['mv'] if r['qty'] is None else r['qty']
        differences = []
        for key in sorted(set(snapshot) | set(ours), key=str):
            mine, theirs = ours.get(key, 0.0), snapshot.get(key, 0.0)
            if abs(mine - theirs) > 0.01:
                differences.append(dict(acct=key[0], sym=key[1], ledger=r2(mine), report=r2(theirs), diff=r2(mine - theirs)))
        asof = store.holdings_asof() or ''
        reconcile = dict(asof=asof.replace('T', ' '), newest_activity=acts[-1]['effective_date'],
                         stale=asof[:10] < acts[-1]['effective_date'],
                         report_value=r2(report_cad), ledger_value=r2(total_now), differences=differences)

    # ---------- realized P&L ----------
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
            closes = df['Close'].dropna()  # today's row can exist before the session has a close
            now = float(closes.iloc[-1]) * factor if len(closes) else None  # today's price in trade-date share units
            if now is not None:
                if cur == 'CAD' and not t.endswith(CAD_SUFFIXES):
                    now *= fx_now
                edge = (now - price) * q  # buy: gain since; sell: negative if it kept rising
                if q < 0:
                    edge = (price - now) * -q
        queued = a['booked_date'] != a['effective_date']
        trades.append(dict(id=engine.trade_id(a), cat=category(sym, acct), date=a['effective_date'],
                           # when the order was placed, and whether it sat overnight before executing --
                           # an intraday chart can only claim an hour for orders placed inside the session
                           time=(a['order_time'] or '')[:5] or None, queued=queued,
                           booked=a['booked_date'] if queued else None,
                           acct=acct, sym=sym, cur=cur, side='BUY' if q > 0 else 'SELL',
                           qty=abs(q), px=round(price, 4), amt=r2(float(a['net_cash_amount'])),
                           now=r2(now), edge=r2(edge),
                           edge_cad=None if edge is None else r2(to_cad(edge, cur)),
                           avgdown=bool(q > 0 and avg_before and price < avg_before * 0.98
                                        and category(sym, acct) in ('stocks', 'speculative'))))

    # ---------- open option contracts ----------
    # Yahoo has no history for a contract, so it is carried at cost; everything else comes from the underlying.
    today = dt.date.fromisoformat(series['dates'][-1])
    open_options = []
    for (acct, sym, cur), p in pos.items():
        if not is_option(sym) or p['q'] <= 1e-9:
            continue
        spec = opt.parse(sym)
        under = tmap.get((spec['root'], cur)) if spec else None
        spot = None
        if under:
            try:
                closes = history(under)['Close'].dropna()
                spot = float(closes.iloc[-1]) if len(closes) else None
            except FileNotFoundError:
                spot = None
        o = opt.position(sym, float(p['q']), float(p['cost']), spot=spot, today=today)
        if not o:
            continue
        o.update(acct=acct, cur=cur, underlying=under, cost_cad=r2(to_cad(float(p['cost']), cur)),
                 payoff=opt.payoff(o))
        if spot:
            o['intrinsic_pl_cad'] = r2(to_cad(o['intrinsic_pl'], cur))
        open_options.append(o)
    open_options.sort(key=lambda o: o['expiry'])

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

    # Each rule carries a stable id so it can be renamed in config without the code knowing the wording.
    # A rule you wrote in your own words is one you argue with; a generated label is one you scroll past.
    MINE = CFG.get('rule_text') or {}

    def rule(rid, name, ok, detail, items=()):
        # rule_text takes either one string (same wording in every language) or {"en": ..., "zh": ...}.
        # Your own words should not be machine-translated, but you should be able to write both.
        mine = MINE.get(rid)
        names = dict(mine) if isinstance(mine, dict) else ({} if mine is None else dict(en=mine, zh=mine))
        rules.append(dict(id=rid, name=names.get('en') or name, names=names, spec=name,
                          ok=ok, detail=detail, items=list(items)))

    big = [f"{x['acct']} {x['sym']} {x['weight']:.1%}" for x in rows
           if x['cat'] == 'stocks' and x['weight'] > R['max_single_stock_pct']]
    rule('single_stock', f"SINGLE STOCK ≤ {R['max_single_stock_pct']:.0%} OF TOTAL", not big, 'All positions within limit' if not big else f'{len(big)} over limit', big)
    spec_pct = alloc['speculative'] / invested if invested else 0
    rule('speculative', f"SPECULATIVE ≤ {R['max_speculative_pct_of_invested']:.0%} OF INVESTED", spec_pct <= R['max_speculative_pct_of_invested'],
         f'Now {spec_pct:.1%}', [f"{x['acct']} {x['sym']} ${x['mv_cad']:,.0f}" for x in rows if x['cat'] == 'speculative'])
    # A satellite is a deliberate structural bet -- currently KWEB, the only non-US, non-Canada holding
    # against a 71% US book. It gets its own cap so the speculative rule stops flagging it, and the cap is
    # set at the trim the user decided on rather than at today's size.
    sat_cap = R.get('max_satellite_pct_of_invested')
    if sat_cap:
        sat_pct = alloc.get('satellite', 0.0) / invested if invested else 0
        held = [x for x in rows if x['cat'] == 'satellite']
        items = [f"{x['acct']} {x['sym']} ${x['mv_cad']:,.0f} ({x['mv_cad']/invested:.1%} of invested)" for x in held]
        for sym, frac in (CFG.get('satellite_exit') or {}).items():
            for x in held:
                if x['sym'] == sym and x['qty']:
                    items.append(f"{sym} exit target: sell {x['qty']*frac:g} of {x['qty']:g} shares (~${x['mv_cad']*frac:,.0f})")
        rule('satellite', f"SATELLITE ≤ {sat_cap:.0%} OF INVESTED", sat_pct <= sat_cap, f'Now {sat_pct:.1%}', items)

    off_cap = R.get('max_offense_cad_nonregistered')
    if off_cap:
        off = [x for x in rows if x['acct'] == 'Non-registered' and x['cat'] == 'speculative']
        spent = sum(x['mv_cad'] for x in off)
        rule('offence', f"NON-REGISTERED OFFENCE ≤ ${off_cap:,.0f}", spent <= off_cap,
             f'${spent:,.0f} of ${off_cap:,.0f} · ${off_cap-spent:,.0f} left',
             [f"{x['sym']} ${x['mv_cad']:,.0f}" for x in off])

    # Registered accounts (TFSA, FHSA, RRSP...): a loss there is permanent and cannot be claimed, so the same
    # guardrails apply to every one of them, not just the TFSA.
    registered = set(CFG.get('registered_accounts', ['TFSA']))
    present = [a for a in sorted({r['acct'] for r in rows}) if a in registered]
    lev_reg = [f"{x['acct']} {x['sym']} ${x['mv_cad']:,.0f}" for x in rows if x['acct'] in registered and x['cat'] == 'speculative']
    rule('leveraged_registered', 'NO LEVERAGED/THEMATIC ETFS IN REGISTERED ACCOUNTS', not lev_reg,
         ('Clean' if not lev_reg else f'{len(lev_reg)} held') + (f" · checking {', '.join(present)}" if present else ''), lev_reg)
    dd = [f"{x['acct']} {x['sym']} {x['upl_pct']:+.1%}" for x in rows
          if x['upl_pct'] is not None and x['upl_pct'] <= R['review_drawdown_pct'] and x['cat'] != 'cash']
    rule('review_drawdown', f"REVIEW POSITIONS ≤ {R['review_drawdown_pct']:.0%}", not dd, 'None below threshold' if not dd else f'{len(dd)} need a decision', dd)
    cutoff = (today - dt.timedelta(days=R['averaging_down_lookback_days'])).isoformat()
    ad = [f"{t['date']} {t['acct']} {t['sym']} {t['qty']:g} @ {t['px']:g}" for t in trades if t['avgdown'] and t['date'] >= cutoff]
    rule('averaging_down', f"NO AVERAGING DOWN (LAST {R['averaging_down_lookback_days']}D)", not ad, f'{len(ad)} buys below average cost', ad[-15:])
    if CFG['rules'].get('require_monthly_core_buy'):
        recent = contributions['months'][-6:]
        missed = [m for m, v in zip(contributions['months'], contributions['core'])][-6:]
        missed = [m for m, v in zip(recent, contributions['core'][-6:]) if abs(v) <= 1]
        floor = R.get('min_monthly_core_cad', 0)
        small = [f'{m}: ${v:,.0f}' for m, v in zip(recent, contributions['core'][-6:]) if 1 < v < floor]
        rule('monthly_core', 'CORE ETF PURCHASE EVERY MONTH', not missed, f"last 6 months: {6 - len(missed)}/6 with a purchase", missed)
        if floor:
            this_month = contributions['core'][-1] if contributions['core'] else 0
            # net, not gross: rotating one core fund into another is not a deployment
            rule('monthly_core_size', f"MONTHLY CORE BUY ≥ ${floor:,.0f} NET", this_month >= floor,
                 f"{contributions['months'][-1] if contributions['months'] else '—'}: ${this_month:,.0f} of ${floor:,.0f}",
                 small)

    month = today.strftime('%Y-%m')
    cap = R.get('max_trades_per_month_registered', R.get('max_tfsa_trades_per_month', 20))
    per_acct = collections.defaultdict(collections.Counter)
    for t in trades:
        if t['acct'] in registered:
            per_acct[t['acct']][t['date'][:7]] += 1
    over = [f'{a} {month}: {c[month]} trades' for a, c in sorted(per_acct.items()) if c[month] > cap]
    recent = [f'{a} {m}: {n}' for a, c in sorted(per_acct.items()) for m, n in sorted(c.items())[-3:]]
    rule('registered_trades', f'REGISTERED TRADES ≤ {cap}/MONTH', not over,
         f"{month}: " + (', '.join(f'{a} {c[month]}' for a, c in sorted(per_acct.items())) or 'no registered trades'),
         over + recent[-9:])

    # ---------- per-ticker series, for comparing several at once ----------
    # Two measures, never on one axis: value is what the position is worth, gain is value minus every
    # dollar put into it. A closed position keeps its realised gain and flat-lines, which is the point.
    spend = collections.defaultdict(list)
    for a in acts:
        t = a['activity_type']
        if t not in ('Trade', 'InternalSecurityTransfer') or not a['symbol'] or is_option(a['symbol']):
            continue
        key = engine.position_key(a, tmap)[1]
        cad = to_cad(float(a['net_cash_amount'] or 0), a['currency'], a['effective_date'])
        # A trade's net is cash moving the other way, so money in is -net. A transfer carries its own
        # stated book value with the shares, and the ledger adds it as given; without this the capital
        # stays behind when the shares leave and the position looks like a loss for the whole gap.
        spend[key].append((pd.Timestamp(a['effective_date']), cad if t == 'InternalSecurityTransfer' else -cad))
    compare = {}
    for key, q in base['qty'].items():
        if key not in spend:
            continue
        val = q * cal.price_cad(key)
        inv = cal.cumulative(spend[key])
        gain = val - inv
        if abs(float(val.iloc[-1])) < 1 and abs(float(gain.iloc[-1])) < 1:
            continue                      # never really held: nothing to compare
        # Peak capital deployed: the denominator that means something for a closed position too.
        compare[key] = dict(value=[r2(v) for v in val], gain=[r2(v) for v in gain],
                            peak_cost=r2(max(float(inv.max()), 0.0)),
                            held=bool(abs(float(q.iloc[-1])) > 1e-9))

    # ---------- scheduled deployment ----------
    # USD cash is spent in USD and CAD in CAD: no conversion, so no 1.5% FX drag on either side.
    # The ladder buys the steadier fund by default and the more volatile one only after a drop.
    dca = None
    P_CAD = (CFG.get('dca') or {}).get('cad_ticker', 'core ETF')
    if CFG.get('dca'):
        P = CFG['dca']

        def last_close(sym):
            t = tmap.get((sym, 'USD')) or tmap.get((sym, 'CAD')) or sym
            try:
                return float(history(t)['Close'].dropna().iloc[-1]), t
            except (FileNotFoundError, IndexError):
                return None, t

        alt_px, alt_t = last_close(P['usd_dip_ticker'])
        try:
            c = history(alt_t)['Close'].dropna()
            dip5 = float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) > 5 else None
        except (FileNotFoundError, IndexError):
            dip5 = None
        on_dip = dip5 is not None and dip5 <= P['usd_dip_pct']
        target = P['usd_dip_ticker'] if on_dip else P['usd_ladder'][0]
        unit, _ = last_close(target)
        usd_cash = sum(x['mv'] for x in rows if x['sym'] == 'USD CASH' and x['cur'] == 'USD')
        cad_px, _ = last_close(P['cad_ticker'])
        cad_cash = sum(x['mv_cad'] for x in rows if x['cat'] == 'cash' and x['sym'] != 'USD CASH')
        dca = dict(
            usd_cash=r2(usd_cash), target=target, on_dip=on_dip,
            dip_5d=None if dip5 is None else round(dip5, 4), dip_threshold=P['usd_dip_pct'],
            unit_usd=r2(unit), shares_now=int(usd_cash // unit) if unit else None,
            default_ticker=P['usd_ladder'][0], dip_ticker=P['usd_dip_ticker'],
            cad_ticker=P['cad_ticker'], monthly_cad=P['monthly_cad'], cad_unit=r2(cad_px),
            cad_shares=int(P['monthly_cad'] // cad_px) if cad_px else None,
            cad_available=r2(cad_cash),
            cad_months=int(cad_cash // P['monthly_cad']) if P['monthly_cad'] else None,
        )

    # ---------- this month's to-do ----------
    # The rules above say whether a standing commitment holds. These say what is still unticked *this
    # month* -- a list you can finish, not a dashboard you can look at.
    todos = []

    def todo(tid, text, done, detail='', amount=None):
        todos.append(dict(id=tid, text=text, done=bool(done), detail=detail, amount=amount))

    month_label = contributions['months'][-1] if contributions['months'] else today.strftime('%Y-%m')
    net_core = contributions['core'][-1] if contributions['core'] else 0.0
    floor = R.get('min_monthly_core_cad', 0)
    if floor:
        short = floor - net_core
        todo('core_buy', f"Buy {P_CAD} this month", net_core >= floor,
             f"{month_label}: ${net_core:,.0f} of ${floor:,.0f} net"
             + ('' if net_core >= floor else f" · ${short:,.0f} to go"),
             None if net_core >= floor else r2(short))
    if dca and dca['usd_cash'] and dca['shares_now']:
        todo('usd_ladder', f"Deploy USD into {dca['target']}", False,
             f"${dca['usd_cash']:,.0f} left · {dca['shares_now']} shares @ ${dca['unit_usd']:,.2f}"
             + (' · on a dip' if dca['on_dip'] else f" · no dip ({dca['dip_5d']:+.2%} 5D)"),
             r2(dca['unit_usd']))
    for sym, frac in (CFG.get('satellite_exit') or {}).items():
        for x in rows:
            if x['sym'] == sym and x['qty']:
                cap = R.get('max_satellite_pct_of_invested', 1)
                todo('trim_' + sym.lower(), f"Trim {sym} by {frac:.0%}",
                     x['mv_cad'] / invested <= cap if invested else False,
                     f"sell {x['qty']*frac:g} of {x['qty']:g} shares (~${x['mv_cad']*frac:,.0f}) · "
                     f"now {x['mv_cad']/invested:.1%} of invested, cap {cap:.0%}", r2(x['mv_cad'] * frac))
    for o in open_options:
        if not o['expired']:
            todo('option_' + o['symbol'].split()[0].lower(), f"Decide on the {o['root']} {o['right'].lower()}", False,
                 f"expires {o['expiry']} · {o['days_to_expiry']}d · "
                 + ('' if o['intrinsic_pl'] is None else f"{o['intrinsic_pl']:+,.0f} {o.get('cur','USD')} if it expired today"))
    cap_tr = R.get('max_trades_per_month_registered', R.get('max_tfsa_trades_per_month', 20))
    used = max((c[month] for c in per_acct.values()), default=0)
    todo('trade_budget', f"Stay under {cap_tr} registered trades", used <= cap_tr,
         f"{month_label}: {used} used, {max(0, cap_tr-used)} left")
    if reconcile and reconcile['stale']:
        todo('holdings_report', 'Import a fresh holdings report', False,
             f"last one {reconcile['asof']} · your trades run to {reconcile['newest_activity']}"
             f" · {len(reconcile['differences'])} lines differ")

    # ---------- income ----------
    income = collections.defaultdict(lambda: collections.defaultdict(float))
    for a in acts:
        if a['activity_type'] in ('Dividend', 'Interest', 'Tax', 'Fee', 'BonusPayment'):
            income[a['effective_date'][:7]][a['activity_type']] += to_cad(float(a['net_cash_amount']), a['currency'], a['effective_date'])

    events = []
    ev_path = os.path.join(PRIVATE_DATA, 'events.csv')
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
        asof=acts[-1]['effective_date'],          # the ledger is the source, so this is how fresh it is
        holdings_source='activities',
        reconcile=reconcile,
        built=dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        price_date=series['dates'][-1], fx=fx_now,
        summary=dict(total=r2(total_now), contrib=r2(contrib_now), gain=r2(total_now - contrib_now),
                     unreal=r2(sum(to_cad(x['upl'] or 0, x['cur']) for x in rows)),
                     realized=r2(sum(p['realized_cad'] for p in positions)),
                     day=r2(sum(x['mv_cad'] * x['day_pct'] / (1 + x['day_pct']) for x in rows if x['day_pct'] is not None)),
                     twr=round(float(twr.iloc[-1] - 1), 4),
                     bench={b: dict(value=r2(bench[b]['value'].iloc[-1]), twr=round(float(bench[b]['twr'].iloc[-1] - 1), 4)) for b in bench}),
        accounts=[dict(acct=a, value=r2(acct_val[a]), contrib=r2(flows[a].iloc[-1]), gain=r2(acct_val[a] - flows[a].iloc[-1]),
                       weight=round(acct_val[a] / total_now, 4) if total_now else 0) for a in accounts],
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
        compare=compare,
        dca=dca,
        todos=todos,
        options=open_options,
        audit=audit.build(acts, cal, gain=total_now - contrib_now),
        events=events,
    )
    os.makedirs(APP, exist_ok=True)
    # The 900-odd audit decision rows are two thirds of the payload and only one screen reads them,
    # so they ship as their own file that AUD fetches on first open.
    decisions = data['audit'].pop('decisions')
    with open(os.path.join(APP, 'audit_decisions.json'), 'w') as f:
        json.dump(decisions, f, separators=(',', ':'), allow_nan=False)
    # Same reasoning for the per-ticker series: 97 tickers of daily value and gain, read by one screen.
    with open(os.path.join(APP, 'compare.json'), 'w') as f:
        json.dump(data.pop('compare'), f, separators=(',', ':'), allow_nan=False)
    with open(os.path.join(APP, 'data.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'), allow_nan=False)  # NaN is not JSON: fail here, not in the browser
    s = data['summary']
    print(f"total ${s['total']:,.0f}  contrib ${s['contrib']:,.0f}  gain ${s['gain']:,.0f}  twr {s['twr']:+.1%}  "
          + '  '.join(f"{b} ${v['value']:,.0f}" for b, v in s['bench'].items()))


if __name__ == '__main__':
    main()
