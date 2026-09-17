"""Portfolio terminal web server.

Dev:   .venv/bin/uvicorn --app-dir pipeline server:app --reload   (set ALLOW_NO_AUTH=1 for local use without a password)
Prod:  see Dockerfile / docker-compose.yml. Run exactly one worker: jobs and the scheduler live in-process.
"""
import base64, contextlib, hashlib, hmac, json, logging, re, secrets, threading, time
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import engine, freeze, jobs, market_data, store
from ledger import load_activities
from settings import (ALLOW_NO_AUTH, APP_PASSWORD, APP_USER, BUILD_DIR, FETCH_TIMES, GUEST_COOKIE_SECURE, GUEST_MODE,
                      GUEST_SESSION_HOURS, GUEST_TOKEN, MARKET_DIR, MAX_UPLOAD_MB, PUBLIC_MARKET_DIR, STATIC_DIR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('portfolio')
TICKER = re.compile(r'^[A-Za-z0-9.\-^=]{1,24}$')
CSRF_HEADER = 'x-requested-with'
PUBLIC = {'/healthz'}
GUEST_COOKIE = 'pt_guest_session'

if GUEST_MODE and not GUEST_TOKEN:
    raise SystemExit('Refusing to start guest mode without GUEST_TOKEN.')
if GUEST_MODE and len(GUEST_TOKEN) < 32:
    raise SystemExit('GUEST_TOKEN must be at least 32 characters.')
if not GUEST_MODE and not APP_PASSWORD and not ALLOW_NO_AUTH:
    raise SystemExit('Refusing to start without APP_PASSWORD. Set one, enable guest mode, or ALLOW_NO_AUTH=1 locally.')


@contextlib.asynccontextmanager
async def lifespan(_app):
    stop = threading.Event()
    threading.Thread(target=jobs.scheduler, args=(stop,), daemon=True, name='scheduler').start()
    if not (BUILD_DIR / 'data.json').exists() and store.has_data():
        jobs.start('rebuild', trigger='startup')
    yield
    stop.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _guest_session():
    return hmac.new(GUEST_TOKEN.encode(), b'portfolio-terminal-guest-session-v1', hashlib.sha256).hexdigest()


def _security_headers(response, path):
    response.headers.update({
        'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    })
    if path.startswith('/api') or path.endswith('.json') or path.endswith('.csv'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.middleware('http')
async def guard(request: Request, call_next):
    path = request.url.path
    if path not in PUBLIC and GUEST_MODE:
        supplied = request.query_params.get('token', '')
        if supplied and secrets.compare_digest(supplied, GUEST_TOKEN) and request.method in ('GET', 'HEAD'):
            clean_query = urlencode([(k, v) for k, v in request.query_params.multi_items() if k != 'token'])
            response = RedirectResponse(path + (f'?{clean_query}' if clean_query else ''), status_code=303)
            response.set_cookie(GUEST_COOKIE, _guest_session(), max_age=GUEST_SESSION_HOURS * 3600, httponly=True,
                                secure=GUEST_COOKIE_SECURE, samesite='strict', path='/')
            response.headers['Cache-Control'] = 'no-store'
            return _security_headers(response, path)
        session = request.cookies.get(GUEST_COOKIE, '')
        if not session or not secrets.compare_digest(session, _guest_session()):
            return _security_headers(PlainTextResponse('Guest token required', 401), path)
    elif path not in PUBLIC and APP_PASSWORD:
        ok = False
        auth = request.headers.get('authorization', '')
        if auth.startswith('Basic '):
            try:
                user, _, pw = base64.b64decode(auth[6:]).decode().partition(':')
                ok = secrets.compare_digest(user, APP_USER) & secrets.compare_digest(pw, APP_PASSWORD)
            except Exception:
                ok = False
        if not ok:
            response = PlainTextResponse('Authentication required', 401, headers={'WWW-Authenticate': 'Basic realm="portfolio"'})
            return _security_headers(response, path)
    # Browsers attach Basic credentials to cross-site form posts; a custom header can only come from our own JS.
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get(CSRF_HEADER) != 'portfolio':
        return _security_headers(PlainTextResponse('Missing X-Requested-With header', 403), path)
    started = time.perf_counter()
    response = await call_next(request)
    _security_headers(response, path)
    if path.startswith('/api') and request.method != 'GET':
        log.info('%s %s %s %.0fms', request.method, path, response.status_code, (time.perf_counter() - started) * 1000)
    return response


# ------------------------------------------------------------------ health & static
@app.get('/healthz')
def healthz():
    data = BUILD_DIR / 'data.json'
    return dict(ok=True, guest=GUEST_MODE, data=data.exists(), data_age_s=int(time.time() - data.stat().st_mtime) if data.exists() else None,
                job_running=jobs.snapshot()['job']['running'])


@app.get('/')
def index():
    return FileResponse(STATIC_DIR / 'index.html', headers={'Cache-Control': 'no-cache'})


app.mount('/static', StaticFiles(directory=STATIC_DIR / 'static'), name='static')


@app.get('/data.json')
def data_json():
    path = BUILD_DIR / 'data.json'
    if not path.exists():
        return JSONResponse(dict(empty=True, exports=store.status()), status_code=404)
    return FileResponse(path, media_type='application/json')


@app.get('/prices/{ticker}.csv')
def price_csv(ticker: str):
    path = PUBLIC_MARKET_DIR / 'prices' / f'{ticker}.csv'
    if not TICKER.match(ticker) or not path.is_file():
        raise HTTPException(404, 'unknown ticker')
    return FileResponse(path, media_type='text/csv')


@app.get('/fx_usdcad.csv')
def fx_csv():
    path = PUBLIC_MARKET_DIR / 'fx_usdcad.csv'
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type='text/csv')


# ------------------------------------------------------------------ jobs
def _history(n=15):
    path = MARKET_DIR / 'fetch_log.jsonl'
    if not path.exists():
        return []
    return [json.loads(l) for l in reversed(path.read_text().strip().splitlines()[-n:])]


@app.get('/api/status')
def status():
    try:
        plan = market_data.plan() if store.has_data() else dict(tickers=[], requests=0, price_due=0, calendar_due=0,
                                                                  fx_due=False, est_seconds=0)
    except Exception as e:
        plan = dict(error=str(e), tickers=[], requests=0, price_due=0, calendar_due=0, fx_due=False, est_seconds=0)
    return dict(**jobs.snapshot(), guest=GUEST_MODE, ephemeral_user_data=GUEST_MODE, plan=plan, history=_history(), exports=store.status(),
                schedule=dict(times=FETCH_TIMES),
                limits=dict(request_gap_s=market_data.REQUEST_GAP, rate_limit_pause_s=market_data.RATE_LIMIT_PAUSE,
                            cooldown_s=jobs.FETCH_COOLDOWN_S, closed_refresh_days=market_data.CLOSED_REFRESH_DAYS,
                            calendar_ttl_h=market_data.CALENDAR_TTL_H))


def _start(kind, force=False):
    try:
        jobs.start(kind, force=force)
    except jobs.Cooldown as e:
        return JSONResponse(dict(ok=False, log=str(e), retry_after=e.wait), 429, headers={'Retry-After': str(e.wait)})
    except jobs.Busy as e:
        return JSONResponse(dict(ok=False, log=str(e)), 409)
    return JSONResponse(dict(ok=True, started=kind), 202)


@app.post('/api/fetch')
def fetch(force: bool = False):
    if not store.has_data():
        return JSONResponse(dict(ok=False, log='Import your exports first'), 409)
    return _start('fetch', force)


@app.post('/api/rebuild')
def rebuild():
    return _start('rebuild')


# ------------------------------------------------------------------ import
@app.post('/api/import/preview')
async def import_preview(files: list[UploadFile] = File(...)):
    if not files or len(files) > 10:
        raise HTTPException(400, 'Upload 1 to 10 CSV files')
    limit = int(MAX_UPLOAD_MB * 1024 * 1024)
    total_limit = limit * 2  # bound how much one request can hold in memory
    payload, total = [], 0
    for f in files:
        raw = await f.read(limit + 1)
        if len(raw) > limit:
            raise HTTPException(413, f'{f.filename} is larger than {MAX_UPLOAD_MB:g} MB')
        total += len(raw)
        if total > total_limit:
            raise HTTPException(413, f'Upload exceeds {2 * MAX_UPLOAD_MB:g} MB in total')
        payload.append((f.filename, raw))
    return store.preview(payload)


class Commit(BaseModel):
    id: str = Field(pattern=r'^[0-9a-f]{16}$')
    force_holdings: bool = False
    fetch: bool = True


@app.post('/api/import/commit')
def import_commit(body: Commit):
    if jobs.snapshot()['job']['running']:
        return JSONResponse(dict(ok=False, log='A job is running; try again when it finishes'), 409)
    try:
        result = store.commit(body.id, body.force_holdings)
    except store.ImportError_ as e:
        return JSONResponse(dict(ok=False, log=str(e)), 400)
    log.info('import committed: +%s rows, holdings_updated=%s', result['added'], result['holdings_updated'])
    kind = 'import-fetch' if body.fetch and result['new_symbols'] else 'rebuild'
    try:
        jobs.start(kind, trigger='import')
        result['job'] = kind
    except jobs.Busy:
        result['job'] = None
    return dict(ok=True, **result)


# ------------------------------------------------------------------ simulate
class Simulate(BaseModel):
    exclude: list[str] = Field(default_factory=list, max_length=5000)
    redirect: str | None = None


@app.post('/api/simulate')
def simulate(body: Simulate):
    if not store.has_data():
        raise HTTPException(409, 'No data')
    redirect = body.redirect if body.redirect in (*engine.CFG['benchmarks'], engine.CASH_ETF) else None
    ids = [i for i in body.exclude if re.fullmatch(r'[0-9a-f]{12}', i)]
    return dict(ok=True, **engine.simulate(load_activities(), ids, redirect))


# ------------------------------------------------------------------ freeze (stop-trading hindsight)
_freeze_lock = threading.Lock()
_freeze_cache = dict(key=None, ctx=None, sweep=None)


def _freeze_ctx():
    """Rebuilt only when exports or the computed data change (a new import, fetch or rebuild)."""
    data = BUILD_DIR / 'data.json'
    key = (store.ACTIVITIES.stat().st_mtime if store.ACTIVITIES.exists() else 0, data.stat().st_mtime if data.exists() else 0)
    with _freeze_lock:
        if _freeze_cache['key'] != key:
            _freeze_cache.update(key=key, ctx=freeze.Context(load_activities()), sweep=None)
        return _freeze_cache


class Freeze(BaseModel):
    trade: str | None = Field(default=None, pattern=r'^[0-9a-f]{12}$')
    date: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    deposits: str = 'cash'


@app.post('/api/freeze')
def freeze_run(body: Freeze):
    if not store.has_data():
        raise HTTPException(409, 'No data')
    if not body.trade and not body.date:
        raise HTTPException(422, 'Give a trade id or a date')
    try:
        return dict(ok=True, **_freeze_ctx()['ctx'].run(trade=body.trade, date=body.date, deposits=body.deposits))
    except ValueError as e:
        return JSONResponse(dict(ok=False, log=str(e)), 400)


@app.get('/api/freeze/sweep')
def freeze_sweep():
    if not store.has_data():
        raise HTTPException(409, 'No data')
    cache = _freeze_ctx()
    with _freeze_lock:
        if cache['sweep'] is None:
            cache['sweep'] = cache['ctx'].sweep()
        return dict(ok=True, **cache['sweep'])
