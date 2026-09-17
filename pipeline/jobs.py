"""Background jobs (fetch, rebuild, import) with a single-flight lock, cooldown and a weekday scheduler."""
import datetime as dt, json, logging, os, subprocess, sys, threading, time
from zoneinfo import ZoneInfo

import prices, store
from settings import FETCH_COOLDOWN_S, FETCH_TIMES, MARKET_DIR, TZ_NAME

log = logging.getLogger('portfolio.jobs')
HERE = os.path.dirname(os.path.abspath(__file__))

_lock = threading.Lock()
job = dict(kind=None, started=None, finished=None, ok=None, log='', trigger=None)
_last_fetch_done = [0.0]


class Busy(Exception):
    pass


class Cooldown(Exception):
    def __init__(self, wait):
        super().__init__(f'Cooling down: try again in {wait}s')
        self.wait = wait


def _run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(HERE, script), *args], cwd=HERE, capture_output=True, text=True,
                       timeout=1800)
    out = (p.stdout + p.stderr).strip()
    log.info('%s %s exit=%s %s', script, ' '.join(args), p.returncode, out.splitlines()[-1] if out else '')
    return p.returncode, out[-4000:]


def _worker(kind, force, trigger):
    lines, ok = [], True
    try:
        if kind in ('rebuild', 'scheduled-fetch', 'fetch'):
            inbox = store.process_inbox()
            if inbox:
                lines.append(f"inbox: +{inbox['added']} activity rows, holdings updated={inbox['holdings_updated']}")
        if kind in ('fetch', 'scheduled-fetch', 'import-fetch'):
            code, out = _run('market_data.py', *(['--force'] if force else []))
            lines.append(out)
            ok = code in (0, 2)  # 2 = stopped early on rate limit; cached data is still valid
        if ok:
            code, out = _run('build_app.py')
            lines.append(out)
            ok = code == 0 or (code == 3 and not store.has_data())
        for f in (prices.history, prices.ticker_map, prices.fx_usdcad):
            f.cache_clear()
    except Exception as e:  # never leave the lock held
        log.exception('job %s failed', kind)
        lines.append(f'{type(e).__name__}: {e}')
        ok = False
    finally:
        job.update(ok=ok, log='\n'.join(l for l in lines if l).strip(), finished=time.time())
        if 'fetch' in kind:
            _last_fetch_done[0] = job['finished']
        _lock.release()


def start(kind, force=False, trigger='user'):
    if kind in ('fetch',) and time.time() - _last_fetch_done[0] < FETCH_COOLDOWN_S:
        raise Cooldown(int(FETCH_COOLDOWN_S - (time.time() - _last_fetch_done[0])))
    if not _lock.acquire(blocking=False):
        raise Busy(f"A {job['kind']} job is already running")
    job.update(kind=kind, started=time.time(), finished=None, ok=None, log='', trigger=trigger)
    threading.Thread(target=_worker, args=(kind, force, trigger), daemon=True, name=f'job-{kind}').start()


def snapshot():
    running = job['started'] is not None and job['finished'] is None
    progress = None
    path = MARKET_DIR / 'fetch_progress.json'
    if running and 'fetch' in (job['kind'] or '') and path.exists():
        try:
            progress = json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return dict(job=dict(job, running=running, elapsed=round(time.time() - job['started'], 1) if job['started'] else None),
                progress=progress, cooldown=max(0, int(FETCH_COOLDOWN_S - (time.time() - _last_fetch_done[0]))))


def scheduler(stop: threading.Event):
    """Weekday fetches at FETCH_TIMES; inbox checks every 5 minutes."""
    tz = ZoneInfo(TZ_NAME)
    done, last_inbox = set(), 0.0
    log.info('scheduler: fetch at %s %s on weekdays', FETCH_TIMES or 'never', TZ_NAME)
    while not stop.wait(30):
        now = dt.datetime.now(tz)
        try:
            for t in FETCH_TIMES:
                key = (now.date(), t)
                hh, mm = map(int, t.split(':'))
                if now.weekday() < 5 and key not in done and (now.hour, now.minute) >= (hh, mm) \
                        and (now.hour * 60 + now.minute) - (hh * 60 + mm) < 90:
                    done.add(key)
                    start('scheduled-fetch', trigger='schedule')
            if time.time() - last_inbox >= 300:
                last_inbox = time.time()
                if store.INBOX.exists() and any(store.INBOX.glob('*.csv')):
                    start('rebuild', trigger='inbox')
        except (Busy, Cooldown) as e:
            log.info('scheduler skipped: %s', e)
        except Exception:
            log.exception('scheduler tick failed')
