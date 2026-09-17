# Portfolio Terminal

A self-hosted, Bloomberg-style terminal for a Wealthsimple portfolio: performance vs. benchmarks, realized P&L,
trade hindsight, allocation rules, what-if simulation (remove trades, or freeze all trading after a trade/day with
short- vs long-term comparisons and a hindsight map), and CSV import. English and Simplified Chinese UI
(`LANG <GO>`, the 中文/EN button, or `?lang=zh`) plus an optional persistent Vim navigation mode (`VIM <GO>` or the
top-right toggle; `h/j/k/l` moves between panel controls, Enter activates, and `:q` exits). Single container, no database, all state in one
data directory.

```
Browser ──HTTPS──► reverse proxy (Caddy/Traefik/nginx) ──► portfolio (FastAPI, 1 worker) ──► /data volume
                                                              │  ├─ exports/  activities.csv, holdings.csv, uploads/, inbox/
                                                              │  ├─ market/   prices/*.csv, fx, fetch state + log
                                                              │  └─ build/    data.json (what the UI renders)
                                                              └─► Yahoo Finance + Bank of Canada (incremental, rate-limited)
```

## Getting started

**Prerequisites:** Docker with the Compose plugin (everything runs in a container), or Python 3.11+ if you prefer a
local virtualenv. Nothing else: no database, no build step, no Node.

```sh
git clone git@github.com:escobarflughafen/wsterm.git
cd portfolio-terminal
git checkout dev                 # day-to-day work happens on dev; main is what production runs
cp .env.example .env             # set APP_PASSWORD, or ALLOW_NO_AUTH=1 for a local-only run
make dev-up                      # build + start with live reload → http://127.0.0.1:8787
make logs
```

`make dev-up` mounts `pipeline/` and `app/` into the container, so saving a file reloads the server; a browser refresh
picks up UI changes. `make down` stops it.

**Without Docker:**

```sh
make setup                       # .venv with runtime + dev dependencies (PYTHON=python3.12 to pick an interpreter)
make test
make dev                         # uvicorn --reload on 127.0.0.1:8787, data in ./var
```

### Giving it data

The app starts empty and says so. Three ways to fill it:

| Source | How |
|---|---|
| Your own exports | Open the app → **IMP** screen → drop `activities-export-*.csv` and `holdings-report-*.csv` → preview → commit. Prices for new symbols are fetched automatically. The same screen carries an illustrated four-step guide to exporting and uploading the activities CSV from Wealthsimple (`app/static/img/`). |
| A copy of another instance | `rsync -a <other>/data/ ./data/` (or `~/Maintenances/portfolio-terminal-deploy.sh seed-dev` on the host) |
| Nothing real | `tests/fixtures/*.csv` are small synthetic exports; import them the same way. |

Data lives in `DATA_PATH` (`./data` for Docker, `./var` for the local venv) and is never committed.

### Tests

```sh
make test          # .venv
make test-docker   # same suite inside the image; no local Python needed
```

24 tests cover the import merge rules, the average-cost ledger, fetch scheduling, the freeze simulation and the HTTP
layer (auth, CSRF, upload limits, path traversal). They use synthetic fixtures only — never real exports.

### Where things are

```
pipeline/settings.py     env-driven paths and secrets            app/index.html        page shell
pipeline/store.py        CSV import: validate, merge, archive    app/static/app.js     all screens and charts
pipeline/ledger.py       average-cost positions and realized P&L app/static/app.css    terminal theme
pipeline/market_data.py  incremental Yahoo/BoC fetch             app/static/i18n.js    EN/中文 strings
pipeline/prices.py       cached price/FX readers (split-aware)   tests/                pytest + fixtures
pipeline/engine.py       daily replay, benchmarks, remove-trades deploy/               host deploy script
pipeline/freeze.py       stop-trading simulation                 Dockerfile            app + test stages
pipeline/build_app.py    computes data.json (what the UI reads)  docker-compose*.yml   prod + dev overlay
pipeline/jobs.py         background jobs, cooldown, scheduler    Makefile              every task
pipeline/server.py       FastAPI: auth, CSRF, headers, API
```

The UI never computes portfolio figures: `build_app.py` writes `data.json` and the browser renders it. Add a metric in
Python, surface it in `app.js`, and add its strings to `i18n.js`.

### Change workflow

```sh
git checkout dev && ...edit... && make test && git commit && git push origin dev
ssh <host> '~/Maintenances/portfolio-terminal-deploy.sh deploy dev'    # verify on :8788
ssh <host> '~/Maintenances/portfolio-terminal-deploy.sh promote'       # main ← dev, then prod on :8787
```

Config that is data, not code — target mix, bucket membership, rule thresholds, benchmark and equivalent tickers —
lives in `$DATA_DIR/config.json` (seeded from `pipeline/config.example.json`, never committed).

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
scp activities-export-*.csv holdings-report-*.csv <host>:/tmp/
ssh <host> 'cd portfolio-terminal && make import FILES="/tmp/activities-export-*.csv /tmp/holdings-report-*.csv"'
```

### Single-host deployment

Prod (`/srv/portfolio-terminal`, :8787, branch `main`) and dev (`~/Workspaces/portfolio-terminal`, :8788, branch `dev`)
are managed by `deploy/portfolio-terminal-deploy.sh`, installed on the host as `~/Maintenances/portfolio-terminal-deploy.sh`
(`init`, `deploy` with verification and automatic rollback, `backup`, `seed-dev`, `promote`, `survey`, `self-update`).
Paths, ports and the repo URL are overridable (`PT_PROD_ROOT`, `PT_DEV_ROOT`, `PT_REPO`, `PT_HOST_URL`); keep the
host-specific runbook outside this repo.

### TLS / reverse proxy

The app speaks plain HTTP and expects a proxy in front. Caddy example (automatic certificates, LAN or Tailscale name):

```caddy
portfolio.example.lan {
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

Portfolio targets, bucket membership and rule thresholds live in `$DATA_DIR/config.json`, seeded from
`pipeline/config.example.json` on first init. It stays out of git so a public repo carries no personal strategy.

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

## Notes for contributors

- **One worker only.** Background jobs and the scheduler live in the process; a second worker would duplicate fetches.
- **Branches.** `dev` is where work lands, `main` is what production runs; `promote` fast-forwards main to dev's commit.
- **Never commit data.** `.gitignore` blocks `data/`, `var/`, `.env` and every CSV except `tests/fixtures/`.
- **CI** (`.github/workflows/ci.yml`) runs the tests, builds the image and smoke-tests that auth is enforced.
- **Adding a screen:** add it to `SCREENS` in `app.js`, write its render function, add strings to `i18n.js`.
