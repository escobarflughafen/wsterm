# Portfolio Terminal

A self-hosted, Bloomberg-style terminal for a Wealthsimple portfolio: performance vs. benchmarks, realized P&L,
trade hindsight, allocation rules, what-if simulation (remove trades, or freeze all trading after a trade/day with
short- vs long-term comparisons and a hindsight map), and CSV import. English and Simplified Chinese UI
(`LANG <GO>`, the 中文/EN button, or `?lang=zh`). Single container, no database, all state in one
data directory.

```
Browser ──HTTPS──► reverse proxy (Caddy/Traefik/nginx) ──► portfolio (FastAPI, 1 worker) ──► /data volume
                                                              │  ├─ exports/  activities.csv, holdings.csv, uploads/, inbox/
                                                              │  ├─ market/   prices/*.csv, fx, fetch state + log
                                                              │  └─ build/    data.json (what the UI renders)
                                                              └─► Yahoo Finance + Bank of Canada (incremental, rate-limited)
```

## Quick start (local)

```sh
make setup                 # .venv with runtime + test deps (Python 3.11)
make test
make dev                   # http://127.0.0.1:8787, no auth, data in ./var
```

Open the app, go to **IMP**, drop your `activities-export-*.csv` and `holdings-report-*.csv`, review the preview,
commit. Prices for new symbols are fetched automatically.

## Deploy (home lab)

Requirements: Docker Engine with the Compose plugin, ~300 MB disk, outbound HTTPS.

```sh
git clone <repo> portfolio-terminal && cd portfolio-terminal
cp .env.example .env && $EDITOR .env      # set APP_PASSWORD (openssl rand -base64 24)
make up                                   # build + start, published on 127.0.0.1:8787
make logs
```

Then import data through the UI, or from your laptop:

```sh
scp activities-export-*.csv holdings-report-*.csv server:/tmp/
ssh server 'cd portfolio-terminal && make import FILES="/tmp/activities-export-2026-09-16.csv /tmp/holdings-report-2026-09-16.csv"'
```

### Host deployment (10.10.20.3)

Prod (`/srv/portfolio-terminal`, :8787, branch `main`) and dev (`~/Workspaces/portfolio-terminal`, :8788, branch `dev`)
are managed by `deploy/portfolio-terminal-deploy.sh`, installed on the host as `~/Maintenances/portfolio-terminal-deploy.sh`
(`init`, `deploy` with verification and automatic rollback, `backup`, `seed-dev`, `promote`, `survey`, `self-update`).
The full runbook lives on the host at `~/Deployments/portfolio-terminal-20260917.md`.

### TLS / reverse proxy

The app speaks plain HTTP and expects a proxy in front. Caddy example (automatic certificates, LAN or Tailscale name):

```caddy
portfolio.home.arpa {
    tls internal
    reverse_proxy 127.0.0.1:8787
}
```

Keep `BIND_ADDR=127.0.0.1` when the proxy runs on the same host. If the proxy is on another machine, set `BIND_ADDR` to
the LAN interface and `FORWARDED_ALLOW_IPS` to the proxy's IP. Don't expose it to the internet without a VPN
(Tailscale/WireGuard) or an SSO proxy in front; Basic auth is a second lock, not the only one.

### Operations

| Task | Command |
|---|---|
| Status / health | `docker compose ps` (healthcheck hits `/healthz`), UI **DATA** screen |
| Logs | `make logs` (JSON-file driver, rotated 3×10 MB) |
| Backup | `make backup` → `backups/portfolio-<stamp>.tgz` (the whole `/data` volume) |
| Restore | `make restore FILE=backups/portfolio-<stamp>.tgz` |
| Update | `git pull && make up` (data volume is untouched) |
| Manual fetch / rebuild | `make fetch`, `make rebuild`, or the buttons in the UI |
| Shell | `make shell` |

Back up before upgrades. Everything the app knows is in the volume; `exports/uploads/` keeps every original CSV, so
`activities.csv` can always be rebuilt from uploads.

## Configuration

All via environment (`.env`):

| Variable | Default | Purpose |
|---|---|---|
| `APP_USER` / `APP_PASSWORD` | `admin` / — | HTTP Basic auth. The server refuses to start without a password unless `ALLOW_NO_AUTH=1`. |
| `FETCH_TIMES` | `17:20` | Weekday auto-fetch times (HH:MM, comma-separated) in `TZ_NAME`. Empty disables. |
| `TZ_NAME` | `America/Toronto` | Scheduler timezone. |
| `BIND_ADDR` / `PORT` | `127.0.0.1` / `8787` | Where Compose publishes the port. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies trusted for `X-Forwarded-*`. |
| `MAX_UPLOAD_MB` | `20` | Per-file import limit. |
| `FETCH_COOLDOWN_S` | `60` | Minimum gap between manual fetches. |
| `DATA_DIR` | `/data` (container), `./var` (local) | Root of all state; `EXPORTS_DIR`, `MARKET_DIR`, `BUILD_DIR` override parts. |

Portfolio targets, bucket membership and rule thresholds live in `pipeline/config.json`.

## Importing data

- **UI (IMP screen):** upload 1–10 CSVs → preview (validation, new vs. duplicate rows, holdings date, reconciliation of
  activity quantities against holdings) → commit. Nothing changes until commit.
- **Inbox:** copy CSVs to `/data/exports/inbox/`; they're imported within 5 minutes or on REBUILD. Invalid files move to
  `inbox/rejected/`.
- **CLI:** `python pipeline/store.py <file.csv> ...`

Rules: file type is detected from the header, not the name. Activity exports may overlap or cover partial ranges; rows
are merged multiset-aware (identical same-second fills are kept, overlaps are not double counted). A holdings report
only replaces the current one if its "As of" date is newer, unless forced.

## Market data budget

Free sources, no API keys. Yahoo publishes no rate limit, so fetching is conservative: only tickers with a newer close
than their last check are requested; held tickers and benchmarks refresh every session, closed positions weekly on a
staggered weekday; ETF calendars are cached for 30 days; requests are sequential and spaced 0.35 s; a 429 pauses once
and a second 429 stops the run with cached data intact. Typical trading day: ~30–40 requests. See the **DATA** screen.

## Security model

- Basic auth on every route except `/healthz`; constant-time comparison.
- CSRF: state-changing requests must carry `X-Requested-With: portfolio` (cross-site forms can't set it).
- Strict CSP (`script-src 'self'`), `X-Frame-Options: DENY`, `no-referrer`, `nosniff`.
- Container: non-root UID 10001, read-only root filesystem, `no-new-privileges`, all capabilities dropped, 1 GB memory cap.
- Uploads: size-limited, header-validated, filenames sanitized, stored under generated names; ticker routes regex-checked.
- `.gitignore` and `.dockerignore` exclude `var/`, `.env`, backups and every CSV except synthetic test fixtures.

## Development

```
pipeline/
  settings.py     env-driven paths and secrets
  store.py        import: validate, stage, merge, archive, inbox
  ledger.py       average-cost positions and realized P&L
  market_data.py  incremental Yahoo/BoC fetch with request budget
  prices.py       cached price/FX readers (split-aware)
  engine.py       daily portfolio replay, benchmarks, remove-trades simulation
  freeze.py       stop-trading simulation: horizons, holdings at freeze, weekly hindsight sweep
  build_app.py    computes data.json
  jobs.py         single-flight background jobs, cooldown, weekday scheduler
  server.py       FastAPI app: auth, CSRF, headers, API, static files
app/              index.html + static/app.{js,css}, static/i18n.js (EN/中文 strings and patterns; no build step)
tests/            pytest with synthetic fixtures (never real exports)
```

Run exactly one worker: jobs and the scheduler are in-process. CI (`.github/workflows/ci.yml`) runs the tests, builds
the image and smoke-tests auth.
