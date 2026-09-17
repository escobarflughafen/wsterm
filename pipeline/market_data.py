"""Fetch and cache market data for everything in the Wealthsimple exports.

Writes public fetch data to PUBLIC_MARKET_DIR and guest/user-derived metadata to MARKET_DIR:
  prices/<ticker>.csv   daily OHLC, Close, Adj Close, Volume (appended incrementally)
  fx_usdcad.csv         Bank of Canada daily USD/CAD
  tickers.csv           WS symbol -> Yahoo ticker map (private MARKET_DIR)
  events.csv            upcoming earnings / ex-dividend dates for current holdings
  fetch_state.json      per-ticker last check, so unchanged data is never re-requested
  fetch_log.jsonl       one line per run: requests, skips, errors, rate limiting (private MARKET_DIR)

Budget rules (Yahoo publishes no limits, so stay far below anything that trips 429s):
  - a ticker is requested only when a newer session close should exist than the last check
  - held tickers and benchmarks refresh every session; closed positions only feed hindsight, so they refresh
    weekly on a staggered weekday (~1/5 of them per day) instead of all at once
  - closed positions that stopped trading (delisted) are re-checked at most weekly
  - calendars are requested once per day, and never for tickers that have none (ETFs)
  - requests are spaced by REQUEST_GAP seconds; a 429 pauses once, a second 429 aborts the run

Run: pipeline/.venv/bin/python pipeline/market_data.py [--force]
"""
import csv, datetime as dt, json, logging, os, sys, time, urllib.request
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

import store
from ledger import build_positions, load_activities, load_holdings
from settings import MARKET_DIR, PUBLIC_MARKET_DIR


logging.getLogger('yfinance').setLevel(logging.CRITICAL)  # expected 404s for ETF calendars
yf.config.debug.hide_exceptions = False  # surface 429s instead of returning empty frames
(PUBLIC_MARKET_DIR / 'yf-cache').mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(PUBLIC_MARKET_DIR / 'yf-cache'))  # container root filesystem is read-only

DATA = str(MARKET_DIR)
PUBLIC_DATA = str(PUBLIC_MARKET_DIR)
PRICES = os.path.join(PUBLIC_DATA, 'prices')
STATE = os.path.join(PUBLIC_DATA, 'fetch_state.json')
LOG = os.path.join(DATA, 'fetch_log.jsonl')
PROGRESS = os.path.join(DATA, 'fetch_progress.json')
BENCHMARKS = ['XEQT.TO', 'VFV.TO', 'VOO', 'QQQ']
TSX_SUFFIX = '.TO'
CDR_SUFFIX = '.NE'  # CDRs trade on Cboe Canada
EXCHANGE_SUFFIXES = ('.TO', '.V', '.NE', '.CN')  # some exports already carry one (e.g. RY.TO)
CRYPTO = {'BTC', 'ETH', 'DOGE', 'SHIB', 'SOL', 'XRP', 'ADA', 'LTC'}
REQUEST_GAP = 0.35          # seconds between network calls
RATE_LIMIT_PAUSE = 20       # seconds to wait after the first 429
STALE_DAYS = 10             # no new rows for this long => treat as delisted
STALE_RECHECK_DAYS = 7
CLOSED_REFRESH_DAYS = 7
CALENDAR_TTL_H = 20
NO_CALENDAR_TTL_D = 30
NY = ZoneInfo('America/New_York')


class RateLimited(Exception):
    pass


# ---------------------------------------------------------------- ticker map
def yahoo_ticker(symbol, currency, description, account):
    """Map a WS symbol to a Yahoo ticker, or None when Yahoo has no usable history."""
    if account == 'Crypto' or symbol in CRYPTO:
        return f'{symbol}-CAD'
    if len(symbol) > 10:  # OCC option symbol; Yahoo drops expired contracts
        return None
    if currency == 'USD':
        return symbol.replace('.', '-')
    if symbol.upper().endswith(EXCHANGE_SUFFIXES):
        return symbol.upper()  # already qualified by the export
    if 'CDR' in description:
        return symbol + CDR_SUFFIX
    return None  # CAD, non-CDR: decided below


def build_ticker_map(acts):
    usd_symbols = {a['symbol'] for a in acts if a['currency'] == 'USD'}
    out = {}
    for a in acts:
        if a['activity_type'] not in ('Trade', 'InternalSecurityTransfer', 'Dividend') or not a['symbol']:
            continue
        key = (a['symbol'], a['currency'])
        if key in out:
            continue
        t = yahoo_ticker(a['symbol'], a['currency'], a['description'], a['account_type'])
        if t is None and a['currency'] == 'CAD' and len(a['symbol']) <= 10:
            # Early US stocks were booked in CAD; Telus (T) collides with AT&T (T, USD) so check the name
            us_listed = a['symbol'] in usd_symbols and 'Telus' not in a['description']
            t = a['symbol'] if us_listed else a['symbol'] + TSX_SUFFIX
        out[key] = t
    return out


# ---------------------------------------------------------------- scheduling
def last_session_close(ticker, now):
    """Most recent moment a new daily bar could have appeared for this ticker."""
    if ticker.endswith('-CAD'):  # crypto: daily bar rolls at 00:00 UTC
        return now.astimezone(dt.timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0)
    ny = now.astimezone(NY)
    day = ny.date()
    close = dt.datetime.combine(day, dt.time(16, 30), NY)  # TSX and US close 16:00 ET, bars settle a bit later
    if ny < close:
        day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(16, 30), NY)  # holidays: one wasted check, then state skips it


def needs_fetch(ticker, st, now, active, force):
    if force or not st.get('checked'):
        return True
    checked = dt.datetime.fromisoformat(st['checked'])
    if checked >= last_session_close(ticker, now):
        return False
    if active:
        return True
    last_row = dt.date.fromisoformat(st['last']) if st.get('last') else None
    if last_row and (now.date() - last_row).days > STALE_DAYS:
        return (now - checked).days >= STALE_RECHECK_DAYS  # likely delisted
    stagger_day = sum(map(ord, ticker)) % 5  # spread closed positions across weekdays
    return (now - checked).days >= CLOSED_REFRESH_DAYS or (now.astimezone(NY).weekday() == stagger_day and checked.date() < now.date())


# ---------------------------------------------------------------- network
class Budget:
    def __init__(self):
        self.requests = 0
        self.errors = []
        self.rate_limited = 0
        self._last = 0.0
        self.planned = None

    def call(self, label, fn, missing_ok=False):
        for attempt in (1, 2):
            wait = REQUEST_GAP - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                with open(PROGRESS, 'w') as f:
                    json.dump(dict(requests=self.requests, label=label, planned=self.planned), f)
            except OSError:
                pass
            try:
                return fn()
            except Exception as e:
                text = f'{type(e).__name__}: {e}'
                if 'RateLimit' in type(e).__name__ or '429' in text or 'Too Many Requests' in text:
                    self.rate_limited += 1
                    if attempt == 1:
                        time.sleep(RATE_LIMIT_PAUSE)
                        continue
                    raise RateLimited(label)
                if not (missing_ok and ('404' in text or 'Not Found' in text)):  # ETFs have no calendar: expected
                    self.errors.append(f'{label}: {text}'.replace('\n', ' ')[:160])
                return None


def fetch_prices(tickers, active, start, state, budget, force):
    os.makedirs(PRICES, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    skipped, updated = 0, 0
    for t in sorted(tickers):
        st = state.setdefault(t, {})
        path = os.path.join(PRICES, f'{t}.csv')
        if os.path.exists(path) and not needs_fetch(t, st, now, t in active, force):
            skipped += 1
            continue
        old = pd.read_csv(path, parse_dates=['Date']) if os.path.exists(path) and not force else None
        begin = (old['Date'].max() - pd.Timedelta(days=5)).date() if old is not None and len(old) else start
        df = budget.call(t, lambda: yf.Ticker(t).history(start=begin, auto_adjust=False, actions=True))
        st['checked'] = now.isoformat(timespec='seconds')
        if df is None or df.empty:
            continue
        df = df.reset_index()
        df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None).dt.normalize()
        if old is not None:
            df = pd.concat([old[old['Date'] < df['Date'].min()], df])
        df.to_csv(path, index=False, float_format='%.6f')
        st['last'] = df['Date'].max().date().isoformat()
        updated += 1
    return dict(price_skipped=skipped, price_updated=updated)


def fetch_fx(start, state, budget):
    path = os.path.join(PUBLIC_DATA, 'fx_usdcad.csv')
    st = state.setdefault('FXUSDCAD', {})
    now = dt.datetime.now(dt.timezone.utc)
    if os.path.exists(path) and st.get('checked') and dt.datetime.fromisoformat(st['checked']) >= last_session_close('VOO', now):
        return 'skipped'

    def get():
        url = f'https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?start_date={start}'
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)['observations']
    obs = budget.call('BoC FXUSDCAD', get)
    if not obs:
        return 'failed'
    with open(path, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['Date', 'USDCAD'])
        for o in obs:
            if o.get('FXUSDCAD', {}).get('v'):
                w.writerow([o['d'], o['FXUSDCAD']['v']])
    st['checked'] = now.isoformat(timespec='seconds')
    st['last'] = obs[-1]['d']
    return 'updated'


def projected_dividend(ticker, today):
    """ETFs have no Yahoo calendar: project the next ex-dividend date from the payment rhythm."""
    path = os.path.join(PRICES, f'{ticker}.csv')
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, parse_dates=['Date'])
    ex = df.loc[df['Dividends'] > 0, 'Date'].dt.date.tolist()
    if len(ex) < 3:
        return []
    gap = pd.Series(ex).diff().dropna().median()
    nxt = ex[-1] + gap
    while nxt < today - dt.timedelta(days=7):
        nxt += gap
    return [(nxt.isoformat(), ticker, 'ex-dividend (projected)')]


def fetch_events(tickers, state, budget, force):
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    rows, skipped = [], 0
    for t in sorted(tickers):
        st = state.setdefault(t, {})
        cached = st.get('calendar')
        age_h = (now - dt.datetime.fromisoformat(st['calendar_checked'])).total_seconds() / 3600 if st.get('calendar_checked') else 1e9
        ttl_h = NO_CALENDAR_TTL_D * 24 if cached == [] else CALENDAR_TTL_H
        if not force and cached is not None and age_h < ttl_h:
            skipped += 1
            cal_rows = cached
        else:
            cal = budget.call(f'{t} calendar', lambda: yf.Ticker(t).calendar, missing_ok=True) or {}
            cal_rows = []
            for label, field in (('earnings', 'Earnings Date'), ('ex-dividend', 'Ex-Dividend Date'), ('dividend pay', 'Dividend Date')):
                v = cal.get(field)
                for d in (v if isinstance(v, list) else [v]):
                    if isinstance(d, dt.datetime):
                        d = d.date()
                    if isinstance(d, dt.date):
                        cal_rows.append((d.isoformat(), label))
            st['calendar'], st['calendar_checked'] = cal_rows, now.isoformat(timespec='seconds')
        if not cal_rows:
            rows += projected_dividend(t, today)
        rows += [(d, t, label) for d, label in cal_rows if dt.date.fromisoformat(d) >= today - dt.timedelta(days=7)]
    rows = sorted(set(map(tuple, rows)))
    with open(os.path.join(DATA, 'events.csv'), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['date', 'ticker', 'event'])
        w.writerows(rows)
    return rows, skipped


def load_universe():
    acts = load_activities()
    tmap = build_ticker_map(acts)
    if store.HOLDINGS.exists():
        holdings = load_holdings()
        held = {tmap.get((k[1], k[2])) for k in holdings} - {None}
    else:
        # A full activity export is enough to estimate today's open positions.
        held = {tmap.get((sym, cur)) for (_acct, sym, cur), p in build_positions(acts).items()
                if p['q'] > 1e-9} - {None}
    tickers = {t for t in tmap.values() if t} | set(BENCHMARKS)
    return acts, tmap, held, tickers, held | set(BENCHMARKS)


def plan(force=False):
    """What a fetch right now would request, without touching the network."""
    _, _, held, tickers, active = load_universe()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for t in sorted(tickers):
        st = state.get(t, {})
        due = not os.path.exists(os.path.join(PRICES, f'{t}.csv')) or needs_fetch(t, st, now, t in active, force)
        tier = 'held' if t in held else 'benchmark' if t in active else 'closed'
        rows.append(dict(ticker=t, tier=tier, last=st.get('last'), checked=st.get('checked'), due=due))
    fx = state.get('FXUSDCAD', {})
    fx_due = not fx.get('checked') or dt.datetime.fromisoformat(fx['checked']) < last_session_close('VOO', now)
    cal_due = 0
    for t in held:
        if t.endswith('-CAD'):
            continue
        st = state.get(t, {})
        if st.get('calendar') is None or not st.get('calendar_checked'):
            cal_due += 1
            continue
        age_h = (now - dt.datetime.fromisoformat(st['calendar_checked'])).total_seconds() / 3600
        cal_due += age_h >= (NO_CALENDAR_TTL_D * 24 if st['calendar'] == [] else CALENDAR_TTL_H)
    due = sum(r['due'] for r in rows) + fx_due + cal_due
    return dict(tickers=rows, price_due=sum(r['due'] for r in rows), fx_due=bool(fx_due), calendar_due=cal_due,
                requests=due, est_seconds=round(due * (REQUEST_GAP + 0.1), 1))


def main():
    force = '--force' in sys.argv
    started = time.monotonic()
    acts, tmap, held, tickers, active = load_universe()
    start = (dt.date.fromisoformat(acts[0]['effective_date']) - dt.timedelta(days=30)).isoformat()
    os.makedirs(DATA, exist_ok=True)
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}

    with open(os.path.join(DATA, 'tickers.csv'), 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['ws_symbol', 'currency', 'yahoo'])
        for (sym, cur), t in sorted(tmap.items()):
            w.writerow([sym, cur, t or ''])

    budget = Budget()
    budget.planned = plan(force)['requests']
    result = dict(started=dt.datetime.now().isoformat(timespec='seconds'), force=force, tickers=len(tickers))
    aborted = None
    try:
        result.update(fetch_prices(tickers, active, start, state, budget, force))
        result['fx'] = fetch_fx(start, state, budget)
        events, ev_skipped = fetch_events({t for t in held if not t.endswith('-CAD')}, state, budget, force)
        result.update(events=len(events), calendar_skipped=ev_skipped)
    except RateLimited as e:
        aborted = f'rate limited at {e}; stopped early, cached data kept'
    finally:
        json.dump(state, open(STATE, 'w'), indent=1, sort_keys=True)
        result.update(seconds=round(time.monotonic() - started, 1), requests=budget.requests,
                      rate_limited=budget.rate_limited, errors=budget.errors[:20], aborted=aborted)
        with open(LOG, 'a') as f:
            f.write(json.dumps(result) + '\n')
        if os.path.exists(PROGRESS):
            os.remove(PROGRESS)

    print(f"{result['requests']} requests in {result['seconds']}s · prices updated {result.get('price_updated', 0)}, "
          f"skipped {result.get('price_skipped', 0)} · calendars skipped {result.get('calendar_skipped', 0)} · fx {result.get('fx')}")
    for e in budget.errors:
        print('  error', e)
    if aborted:
        print('  ' + aborted)
        sys.exit(2)


if __name__ == '__main__':
    main()
