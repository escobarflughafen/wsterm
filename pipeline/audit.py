"""Daily-first portfolio decision audit.

Transactions are ledger events.  The analytical units exposed here are decisions
inside campaigns (flat -> invested -> flat).  All timing scores are descriptive,
fixed-horizon close-to-close excess returns; they never use the eventual exit.
"""
import collections
import json
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
    if cad and not ticker.endswith(engine.CAD_SUFFIXES):
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
    quoted_cad = ticker.endswith(engine.CAD_SUFFIXES)
    if currency == 'CAD' and not quoted_cad:
        return value * fx
    if currency == 'USD' and quoted_cad:
        return value / fx
    return value


def _campaign_bootstrap(rows, horizon, samples=1000):
    """10-90% sensitivity range, resampling independent campaigns rather than fills."""
    key = f'er_{horizon}d'
    grouped = collections.defaultdict(list)
    for row in rows:
        if row.get(key) is not None:
            grouped[row['campaign']].append(row[key])
    means = [sum(v) / len(v) for v in grouped.values() if v]
    if not means:
        return dict(lo=None, hi=None, campaigns=0)
    rng = random.Random(20260917 + horizon)
    draws = sorted(sum(rng.choice(means) for _ in means) / len(means) for _ in range(samples))
    return dict(lo=_r(draws[int(samples * .1)]), hi=_r(draws[int(samples * .9)]), campaigns=len(means))


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
    """Daily no-look-ahead indices: a score enters only when its forward horizon has matured."""
    if not decisions:
        return dict(dates=[], curves={}, base=100)
    first = min(d['date'] for d in decisions)
    dates = [d.strftime('%Y-%m-%d') for d in days if d >= pd.Timestamp(first)]
    curves = {}
    for cls in ('ALL',) + ENTRY_CLASSES + EXIT_CLASSES:
        rows = decisions if cls == 'ALL' else [d for d in decisions if d['class'] == cls]
        if not rows:
            continue
        curves[cls] = {}
        for horizon in HORIZONS:
            by_date = collections.defaultdict(list)
            for d in rows:
                if d[f'factor_{horizon}d'] is not None and d[f'end_{horizon}d']:
                    by_date[d[f'end_{horizon}d']].append(d[f'factor_{horizon}d'])
            level, values = 100.0, []
            for date in dates:
                for factor in by_date.get(date, ()):
                    level *= factor
                values.append(_r(level, 3))
            curves[cls][f'{horizon}d'] = values
    return dict(dates=dates, curves=curves, base=100)


def _campaigns_and_decisions(acts, cal, benchmark, days):
    states = collections.defaultdict(lambda: dict(q=0.0, cost=0.0, number=0, campaign=None))
    campaigns, decisions = [], []
    bench_cad, _ = _series(benchmark, cal, days=days)
    cache = {}

    def market(ticker):
        if ticker not in cache:
            cache[ticker] = (_series(ticker, cal, False, days)[0], _series(ticker, cal, True, days)[0], _mark_series(ticker, cal, days))
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
                                 decisions=0, avg_down=False, realized_cad=0.0, trade_ids=[])
            campaigns.append(s['campaign'])

        campaign = s['campaign']
        if campaign and a['activity_type'] == 'Trade':
            campaign['trade_ids'].append(engine.trade_id(a))
        avg_before = s['cost'] / s['q'] if s['q'] > 1e-9 else None
        ticker = None if engine.is_option(a['symbol']) else cal.tmap.get((a['symbol'], a['currency']))
        mark = None
        if ticker:
            try:
                local, cad, marks = market(ticker)
                # With no intraday bar, the last completed close is the only non-look-ahead mark.
                i = marks.index.searchsorted(pd.Timestamp(a['effective_date']), side='left') - 1
                if i >= 0 and not pd.isna(marks.iloc[i]):
                    mark = _quote_in_currency(float(marks.iloc[i]), ticker, a['currency'], float(cal.fx.iloc[i]))
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
                local, cad, _ = market(ticker)
                for horizon in HORIZONS:
                    ticker_ret, end_date = _forward_point(cad, a['effective_date'], horizon)
                    local_ret, _ = _forward_point(local, a['effective_date'], horizon)
                    benchmark_ret, _ = _forward_point(bench_cad, a['effective_date'], horizon)
                    er = None if ticker_ret is None or benchmark_ret is None else (ticker_ret - benchmark_ret) * (1 if qty > 0 else -1)
                    factor = None
                    if ticker_ret is not None and benchmark_ret is not None and 1 + ticker_ret > 0 and 1 + benchmark_ret > 0:
                        relative = (1 + ticker_ret) / (1 + benchmark_ret)
                        factor = relative if qty > 0 else 1 / relative
                    row[f'local_{horizon}d'] = _r(local_ret)
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
        else:
            sold = min(-qty, max(s['q'], 0.0))
            avg = s['cost'] / s['q'] if s['q'] > 1e-9 else 0.0
            if a['activity_type'] == 'Trade' and campaign:
                campaign['realized_cad'] += cal.to_cad(net - avg * sold, a['currency'], a['effective_date'])
            s['cost'] -= avg * sold
            s['q'] += qty
            if s['q'] <= 1e-9:
                s['q'] = s['cost'] = 0.0
                if campaign:
                    campaign.update(end=a['effective_date'], open=False)
                s['campaign'] = None

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
    removals = []
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
    return dict(ranked=ranked, positive_pnl=_r(positive, 2), top_positive_share=shares,
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


def build(acts, cal=None, benchmark=None):
    """Return JSON-safe V1 audit results using only cached daily market data."""
    benchmark = benchmark or engine.CFG['benchmarks'][0]
    cal = cal or engine.Calendar(acts[0]['effective_date'])
    benchmark_rows = history(benchmark).dropna(subset=['Adj Close'])
    days = benchmark_rows.index[(benchmark_rows.index >= cal.days[0]) & (benchmark_rows.index <= cal.days[-1])]
    campaigns, decisions = _campaigns_and_decisions(acts, cal, benchmark, days)
    priced = sum(d['price_quality'] != 'MISSING' for d in decisions)
    options = [c for c in campaigns if c['option']]
    return dict(
        version=1, benchmark=benchmark, clock='DAILY', horizons=list(HORIZONS),
        methodology='Daily close-to-close CAD excess return; pre-trade state uses the previous completed close; exits use benchmark minus security. When a horizon elapses, the accumulated series multiplies a positive relative-wealth factor: security/benchmark for buys, benchmark/security for sells. The indices are descriptive, not evidence of independent bets.',
        hypotheses=json.load(open(HYPOTHESES_PATH)),
        coverage=dict(decisions=len(decisions), daily_priced=priced, daily_pct=_r(priced / len(decisions), 3) if decisions else None,
                      missing=len(decisions) - priced, hourly_priced=0, options_excluded=len(options)),
        decisions=decisions, summary=_summaries(decisions), indices=_indices(decisions, days),
        concentration=_concentration(campaigns, acts, cal, benchmark),
        averaging_down=_averaging_down(decisions, campaigns),
        options=dict(campaigns=len(options), pnl_cad=_r(sum(c['pnl_cad'] for c in options), 2), timing_excluded=True),
    )
