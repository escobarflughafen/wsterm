"""Daily-first portfolio decision audit.

Transactions are ledger events.  The analytical units exposed here are decisions
inside campaigns (flat -> invested -> flat).  All timing scores are descriptive,
fixed-horizon close-to-close excess returns; they never use the eventual exit.
"""
import collections
import json
import math
import os
import random

import pandas as pd

import engine
from prices import history

HORIZONS = (1, 5, 20, 60)
ENTRY_CLASSES = ('OPEN', 'ADD_TO_LOSER', 'ADD_TO_WINNER')
EXIT_CLASSES = ('REDUCE_LOSER', 'REDUCE_WINNER', 'CLOSE_LOSER', 'CLOSE_WINNER')
HYPOTHESES_PATH = os.path.join(os.path.dirname(__file__), 'audit_hypotheses.json')


def _r(value, places=4):
    return None if value is None or pd.isna(value) else round(float(value), places)


def _series(ticker, cal, cad=True, days=None):
    """Adjusted close on the audit calendar, without inventing pre/post-coverage prices."""
    days = cal.days if days is None else pd.DatetimeIndex(days)
    df = history(ticker).dropna(subset=['Adj Close'])
    if df.empty:
        return pd.Series(dtype=float), None
    raw = df['Adj Close'].astype(float)
    out = raw.reindex(raw.index.union(days)).sort_index().ffill().reindex(days)
    out.loc[out.index < raw.index[0]] = float('nan')
    out.loc[out.index > raw.index[-1]] = float('nan')
    if cad and not engine.quoted_in_cad(ticker):
        out = out * cal.fx.reindex(days).ffill().bfill()
    return out, raw.index[-1]


def _mark_series(ticker, cal, days=None):
    """Split-corrected as-traded close, comparable with the ledger's historical cost/share."""
    days = cal.days if days is None else pd.DatetimeIndex(days)
    raw = engine.as_traded_close(ticker).dropna().astype(float)
    out = raw.reindex(raw.index.union(days)).sort_index().ffill().reindex(days)
    if not raw.empty:
        out.loc[out.index < raw.index[0]] = float('nan')
        out.loc[out.index > raw.index[-1]] = float('nan')
    return out


def _forward_point(series, day, horizon):
    i = series.index.searchsorted(pd.Timestamp(day))
    j = i + horizon
    if i >= len(series) or j >= len(series):
        return None, None
    a, b = series.iloc[i], series.iloc[j]
    if pd.isna(a) or pd.isna(b) or not a:
        return None, None
    return float(b / a - 1), series.index[j].strftime('%Y-%m-%d')


def _quote_in_currency(value, ticker, currency, fx):
    """Convert a Yahoo quote into the broker ledger currency used for cost/share."""
    quoted_cad = engine.quoted_in_cad(ticker)
    if currency == 'CAD' and not quoted_cad:
        return value * fx
    if currency == 'USD' and quoted_cad:
        return value / fx
    return value


def _campaign_bootstrap(rows, horizon, samples=1000):
    """10-90% sensitivity range, resampling whole campaigns rather than fills.

    The resampled statistic has to be the one the table prints, so each draw pools every decision in
    the drawn campaigns and averages those.  Averaging campaign means instead would estimate a
    different quantity and let the point estimate fall outside its own band.
    """
    key = f'er_{horizon}d'
    grouped = collections.defaultdict(list)
    for row in rows:
        if row.get(key) is not None:
            grouped[row['campaign']].append(row[key])
    clusters = [v for v in grouped.values() if v]
    if not clusters:
        return dict(lo=None, hi=None, campaigns=0)
    rng = random.Random(20260917 + horizon)
    draws = []
    for _ in range(samples):
        pooled = [v for _ in clusters for v in rng.choice(clusters)]
        draws.append(sum(pooled) / len(pooled))
    draws.sort()
    return dict(lo=_r(draws[int(samples * .1)]), hi=_r(draws[int(samples * .9)]), campaigns=len(clusters))


def _summaries(decisions):
    out = []
    for cls in ('ALL',) + ENTRY_CLASSES + EXIT_CLASSES:
        rows = decisions if cls == 'ALL' else [d for d in decisions if d['class'] == cls]
        if not rows:
            continue
        item = dict(cls=cls, decisions=len(rows), campaigns=len({r['campaign'] for r in rows}))
        for h in HORIZONS:
            vals = [r[f'er_{h}d'] for r in rows if r[f'er_{h}d'] is not None]
            item[f'n_{h}d'] = len(vals)
            item[f'er_{h}d'] = _r(sum(vals) / len(vals)) if vals else None
            item[f'median_{h}d'] = _r(pd.Series(vals).median()) if vals else None
            item[f'win_{h}d'] = _r(sum(v > 0 for v in vals) / len(vals), 3) if vals else None
            boot = _campaign_bootstrap(rows, h)
            item[f'lo_{h}d'], item[f'hi_{h}d'] = boot['lo'], boot['hi']
        out.append(item)
    return out


def _indices(decisions, days):
    """Daily no-look-ahead evidence curves: a score enters only when its forward horizon matured.

    The curve is the running *average* relative factor, not a compounded one.  A 60-day window
    overlaps roughly sixty neighbours, so multiplying every matured score would count the same market
    move dozens of times: it explodes at long horizons and bleeds away to volatility drag at short
    ones.  Averaging in log space keeps the number what the reader thinks it is -- what the typical
    decision of this class did against the benchmark, with `counts` saying how much evidence backs it.
    """
    if not decisions:
        return dict(dates=[], curves={}, counts={}, base=1.0)
    first = min(d['date'] for d in decisions)
    dates = [d.strftime('%Y-%m-%d') for d in days if d >= pd.Timestamp(first)]
    curves, counts = {}, {}
    for cls in ('ALL',) + ENTRY_CLASSES + EXIT_CLASSES:
        rows = decisions if cls == 'ALL' else [d for d in decisions if d['class'] == cls]
        if not rows:
            continue
        curves[cls], counts[cls] = {}, {}
        for horizon in HORIZONS:
            by_date = collections.defaultdict(list)
            for d in rows:
                if d[f'factor_{horizon}d'] and d[f'end_{horizon}d']:
                    by_date[d[f'end_{horizon}d']].append(math.log(d[f'factor_{horizon}d']))
            total, n, values, seen = 0.0, 0, [], []
            for date in dates:
                for logged in by_date.get(date, ()):
                    total += logged
                    n += 1
                values.append(_r(math.exp(total / n), 5) if n else None)
                seen.append(n)
            curves[cls][f'{horizon}d'] = values
            counts[cls][f'{horizon}d'] = seen
    return dict(dates=dates, curves=curves, counts=counts, base=1.0)


def _campaigns_and_decisions(acts, cal, benchmark, days):
    states = collections.defaultdict(lambda: dict(q=0.0, cost=0.0, number=0, campaign=None))
    campaigns, decisions = [], []
    bench_cad, _ = _series(benchmark, cal, days=days)
    cache = {}

    def market(ticker):
        """(total-return series in CAD, as-traded close for comparing against ledger cost)."""
        if ticker not in cache:
            cache[ticker] = (_series(ticker, cal, True, days)[0], _mark_series(ticker, cal, days))
        return cache[ticker]

    ordered = sorted(enumerate(acts), key=lambda x: (x[1]['effective_date'], x[1]['effective_time'], x[0]))
    for _, a in ordered:
        if a['activity_type'] not in ('Trade', 'InternalSecurityTransfer') or not a['symbol']:
            continue
        key = (a['account_type'], a['symbol'], a['currency'])
        s = states[key]
        qty, net = float(a['quantity'] or 0), float(a['net_cash_amount'] or 0)
        if not qty:
            continue
        if s['q'] <= 1e-9 and qty > 0:
            s['number'] += 1
            cid = f"{a['account_type']}|{a['symbol'].strip()}|{a['currency']}|{s['number']}"
            s['campaign'] = dict(id=cid, acct=a['account_type'], sym=a['symbol'].strip(), cur=a['currency'],
                                 start=a['effective_date'], end=None, open=True, option=engine.is_option(a['symbol']),
                                 decisions=0, avg_down=False, realized_cad=0.0, trade_ids=[],
                                 transferred=a['activity_type'] == 'InternalSecurityTransfer')
            campaigns.append(s['campaign'])

        campaign = s['campaign']
        if campaign and a['activity_type'] == 'Trade':
            campaign['trade_ids'].append(engine.trade_id(a))
        avg_before = s['cost'] / s['q'] if s['q'] > 1e-9 else None
        ticker = None if engine.is_option(a['symbol']) else cal.tmap.get((a['symbol'], a['currency']))
        mark = None
        if ticker:
            try:
                marks = market(ticker)[1]
                # With no intraday bar, the last completed close is the only non-look-ahead mark.
                i = marks.index.searchsorted(pd.Timestamp(a['effective_date']), side='left') - 1
                if i >= 0 and not pd.isna(marks.iloc[i]):
                    # cal.fx is indexed on business days and `marks` on the benchmark's trading days,
                    # so the rate has to be looked up by label; the positions drift apart every holiday.
                    fx = float(cal.fx.asof(marks.index[i]))
                    mark = _quote_in_currency(float(marks.iloc[i]), ticker, a['currency'], fx)
            except FileNotFoundError:
                ticker = None
        status = None if avg_before is None or mark is None else ('WINNER' if mark >= avg_before else 'LOSER')

        if a['activity_type'] == 'Trade' and ticker and campaign:
            if qty > 0:
                cls = 'OPEN' if s['q'] <= 1e-9 else f'ADD_TO_{status or "UNKNOWN"}'
            else:
                closes = -qty >= s['q'] - 1e-9
                cls = f'CLOSE_{status or "UNKNOWN"}' if closes else f'REDUCE_{status or "UNKNOWN"}'
            if cls in ENTRY_CLASSES + EXIT_CLASSES:
                row = dict(id=engine.trade_id(a), date=a['effective_date'], acct=a['account_type'], sym=a['symbol'].strip(),
                           ticker=ticker, cur=a['currency'], campaign=campaign['id'], cls=('ENTRY' if qty > 0 else 'EXIT'),
                           **{'class': cls}, state=status, quantity=abs(qty), notional_cad=_r(cal.to_cad(abs(net), a['currency'], a['effective_date']), 2),
                           price_quality='DAILY')
                cad = market(ticker)[0]
                for horizon in HORIZONS:
                    ticker_ret, end_date = _forward_point(cad, a['effective_date'], horizon)
                    benchmark_ret, _ = _forward_point(bench_cad, a['effective_date'], horizon)
                    er = None if ticker_ret is None or benchmark_ret is None else (ticker_ret - benchmark_ret) * (1 if qty > 0 else -1)
                    factor = None
                    if ticker_ret is not None and benchmark_ret is not None and 1 + ticker_ret > 0 and 1 + benchmark_ret > 0:
                        relative = (1 + ticker_ret) / (1 + benchmark_ret)
                        factor = relative if qty > 0 else 1 / relative
                    row[f'cad_{horizon}d'] = _r(ticker_ret)
                    row[f'benchmark_{horizon}d'] = _r(benchmark_ret)
                    row[f'er_{horizon}d'] = _r(er)
                    row[f'factor_{horizon}d'] = _r(factor, 6)
                    row[f'end_{horizon}d'] = end_date if er is not None else None
                    row[f'impact_{horizon}d'] = _r(er * row['notional_cad'], 2) if er is not None else None
                if all(row[f'er_{h}d'] is None for h in HORIZONS):
                    row['price_quality'] = 'MISSING'
                decisions.append(row)
                campaign['decisions'] += 1
                campaign['avg_down'] |= cls == 'ADD_TO_LOSER'

        if qty > 0:
            s['q'] += qty
            s['cost'] += (-net if a['activity_type'] == 'Trade' else abs(net))
            continue

        # A transfer out may drain a sibling book: early US stocks were held under the CAD key, so
        # taking the shares only off this key would leave a position the portfolio does not hold.
        drained = key
        if a['activity_type'] == 'InternalSecurityTransfer' and s['q'] < -qty - 1e-9:
            siblings = [k for k, v in states.items() if k[:2] == key[:2] and k != key and v['q'] >= -qty - 1e-9]
            drained = siblings[0] if siblings else key
        t = states[drained]
        sold = min(-qty, max(t['q'], 0.0))
        avg = t['cost'] / t['q'] if t['q'] > 1e-9 else 0.0
        if a['activity_type'] == 'Trade' and campaign:
            campaign['realized_cad'] += cal.to_cad(net - avg * sold, a['currency'], a['effective_date'])
        if t['campaign'] and a['activity_type'] == 'InternalSecurityTransfer':
            t['campaign']['transferred'] = True   # its P&L stops at a stated book value, not a sale
        t['cost'] -= avg * sold
        t['q'] += qty
        if t['q'] <= 1e-9:
            t['q'] = t['cost'] = 0.0
            if t['campaign']:
                t['campaign'].update(end=a['effective_date'], open=False)
            t['campaign'] = None

    # Mark open campaign value. Contract history is deliberately not invented: open options stay at cost.
    for key, s in states.items():
        c = s['campaign']
        if not c:
            continue
        if c['option']:
            unreal = 0.0
        else:
            ticker = cal.tmap.get((key[1], key[2]))
            try:
                close = float(history(ticker)['Close'].dropna().iloc[-1]) if ticker else None
            except (FileNotFoundError, IndexError):
                close = None
            if close is not None:
                close = _quote_in_currency(close, ticker, key[2], cal.fx_now)
            unreal = cal.to_cad(s['q'] * close - s['cost'], key[2]) if close is not None else 0.0
        c['unrealized_cad'] = _r(unreal, 2)
    for c in campaigns:
        c.setdefault('unrealized_cad', 0.0)
        c['realized_cad'] = _r(c['realized_cad'], 2)
        c['pnl_cad'] = _r(c['realized_cad'] + c['unrealized_cad'], 2)
    return campaigns, decisions


def _concentration(campaigns, acts, cal, benchmark):
    ranked = sorted(campaigns, key=lambda c: c['pnl_cad'], reverse=True)
    positive = sum(max(0, c['pnl_cad']) for c in ranked)
    shares = {str(n): _r(sum(max(0, c['pnl_cad']) for c in ranked[:n]) / positive, 3) if positive else None for n in (1, 3, 5)}
    base = engine.replay(acts, cal)
    actual_twr = float(engine.twr(base['total'], base['contrib']).iloc[-1] - 1)
    bench_twr = float(engine.benchmark_value(benchmark, base['contrib'], cal)[1].iloc[-1] - 1)
    removals = [dict(n=0, campaigns=0, return_=_r(actual_twr), excess=_r(actual_twr - bench_twr),
                     end_value=_r(float(base['total'].iloc[-1]), 2), trades_removed=0, clipped=0)]
    for n in (1, 3, 5):
        picked = ranked[:n]
        ids = {tid for c in picked for tid in c['trade_ids']}
        stripped, removed, clipped = engine.apply_exclusions(acts, ids, cal.tmap)
        replay = engine.replay(stripped, cal)
        # A complete removal can leave no accounts, and replay's empty sum is the scalar 0.
        total = replay['total'] if isinstance(replay['total'], pd.Series) else pd.Series(0.0, index=cal.days)
        contrib = replay['contrib'] if isinstance(replay['contrib'], pd.Series) else pd.Series(0.0, index=cal.days)
        ret = float(engine.twr(total, contrib).iloc[-1] - 1)
        removals.append(dict(n=n, campaigns=len(picked), return_=_r(ret), excess=_r(ret - bench_twr),
                             end_value=_r(total.iloc[-1], 2), trades_removed=removed, clipped=len(clipped)))
    public = [{k: v for k, v in c.items() if k != 'trade_ids'} for c in ranked]  # ids are replay input, not display
    return dict(ranked=public, positive_pnl=_r(positive, 2), top_positive_share=shares,
                actual_return=_r(actual_twr), benchmark_return=_r(bench_twr), actual_excess=_r(actual_twr - bench_twr), removals=removals)


def _averaging_down(decisions, campaigns):
    rows = [d for d in decisions if d['class'] == 'ADD_TO_LOSER']
    by_ticker = []
    for sym, group in sorted(collections.defaultdict(list, {s: [r for r in rows if r['sym'] == s] for s in {r['sym'] for r in rows}}).items()):
        by_ticker.append(dict(sym=sym, decisions=len(group), campaigns=len({r['campaign'] for r in group}),
                              impact_20d=_r(sum(r['impact_20d'] or 0 for r in group), 2),
                              impact_60d=_r(sum(r['impact_60d'] or 0 for r in group), 2),
                              er_20d=_r(pd.Series([r['er_20d'] for r in group if r['er_20d'] is not None]).mean()),
                              er_60d=_r(pd.Series([r['er_60d'] for r in group if r['er_60d'] is not None]).mean())))
    by_ticker.sort(key=lambda r: r['impact_60d'], reverse=True)
    with_add = [c['pnl_cad'] for c in campaigns if c['avg_down']]
    without = [c['pnl_cad'] for c in campaigns if not c['avg_down']]
    return dict(by_ticker=by_ticker, decisions=len(rows), campaigns=len({r['campaign'] for r in rows}),
                impact_20d=_r(sum(r['impact_20d'] or 0 for r in rows), 2), impact_60d=_r(sum(r['impact_60d'] or 0 for r in rows), 2),
                campaign_pnl_with=_r(pd.Series(with_add).median(), 2) if with_add else None,
                campaign_pnl_without=_r(pd.Series(without).median(), 2) if without else None)


def _reconciliation(campaigns, acts, cal, gain=None):
    """Campaign P&L covers trades only.  Publish the rest of the gain so two screens cannot disagree
    silently: dividends, fees and FX conversions never belong to a campaign, and whatever is still
    unexplained after those is shown as a residual rather than quietly absorbed.  `gain` is the figure
    PERF publishes; reconciling against anything else would just move the argument somewhere else."""
    if gain is None:
        replay = engine.replay(acts, cal)
        gain = float(replay['total'].iloc[-1] - replay['contrib'].iloc[-1])
    income = collections.Counter()
    for a in acts:
        net = float(a['net_cash_amount'] or 0)
        if net and a['activity_type'] not in ('Trade', 'MoneyMovement', 'InternalSecurityTransfer'):
            income[a['activity_type']] += cal.to_cad(net, a['currency'], a['effective_date'])
    campaign_pnl = sum(c['pnl_cad'] for c in campaigns)
    other = sum(income.values())
    return dict(campaign_pnl=_r(campaign_pnl, 2), portfolio_gain=_r(gain, 2), income_total=_r(other, 2),
                residual=_r(gain - campaign_pnl - other, 2),
                income=[dict(kind=k, cad=_r(v, 2)) for k, v in income.most_common()])


def _public(decisions):
    """The scrubber reads these; everything else was intermediate work and stays out of the payload."""
    keep = ('date', 'sym', 'campaign', 'cls', 'class', 'notional_cad')
    horizon_keys = [f'{name}_{h}d' for h in HORIZONS for name in ('cad', 'benchmark', 'er', 'factor', 'end')]
    return [{k: d[k] for k in keep + tuple(horizon_keys)} for d in decisions]


def build(acts, cal=None, benchmark=None, gain=None):
    """Return JSON-safe V1 audit results using only cached daily market data."""
    benchmark = benchmark or engine.CFG['benchmarks'][0]
    cal = cal or engine.Calendar(acts[0]['effective_date'])
    benchmark_rows = history(benchmark).dropna(subset=['Adj Close'])
    days = benchmark_rows.index[(benchmark_rows.index >= cal.days[0]) & (benchmark_rows.index <= cal.days[-1])]
    campaigns, decisions = _campaigns_and_decisions(acts, cal, benchmark, days)
    priced = sum(d['price_quality'] != 'MISSING' for d in decisions)
    options = [c for c in campaigns if c['option']]
    return dict(
        version=2, benchmark=benchmark, clock='DAILY', horizons=list(HORIZONS),
        methodology='Daily close-to-close CAD excess return; pre-trade state uses the previous completed close; exits use benchmark minus security. Each matured score is one relative-wealth factor: security/benchmark for buys, benchmark/security for sells. The curve averages those factors in log space rather than compounding them, because overlapping windows are the same market move counted many times. It describes the typical decision of a class, not a return anyone earned.',
        hypotheses=json.load(open(HYPOTHESES_PATH)),
        coverage=dict(decisions=len(decisions), daily_priced=priced, daily_pct=_r(priced / len(decisions), 3) if decisions else None,
                      missing=len(decisions) - priced, hourly_priced=0, options_excluded=len(options),
                      transferred_campaigns=sum(c['transferred'] for c in campaigns)),
        decisions=_public(decisions), summary=_summaries(decisions), indices=_indices(decisions, days),
        concentration=_concentration(campaigns, acts, cal, benchmark),
        averaging_down=_averaging_down(decisions, campaigns),
        reconciliation=_reconciliation(campaigns, acts, cal, gain),
        options=dict(campaigns=len(options), pnl_cad=_r(sum(c['pnl_cad'] for c in options), 2), timing_excluded=True),
    )
