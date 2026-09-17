"""Runtime configuration. Everything that differs between a laptop and a server comes from the environment.

  DATA_DIR        root for all mutable state (default ./var). Mount this as a volume in production.
  EXPORTS_DIR     Wealthsimple exports: merged masters, upload archive, inbox       (default $DATA_DIR/exports)
  MARKET_DIR      cached prices, FX, fetch state and logs                           (default $DATA_DIR/market)
  BUILD_DIR       computed data.json served to the browser                          (default $DATA_DIR/build)
  CONFIG_PATH     targets, buckets, rule thresholds                                 (default pipeline/config.json)
  APP_USER / APP_PASSWORD   HTTP Basic auth; required unless ALLOW_NO_AUTH=1
  FETCH_TIMES     comma-separated HH:MM (TZ below) for automatic weekday fetches; empty disables
  TZ_NAME         timezone for FETCH_TIMES (default America/Toronto)
  MAX_UPLOAD_MB   per-file import limit (default 20)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / 'app'


def _path(name, default):
    return Path(os.environ.get(name) or default).expanduser().resolve()


DATA_DIR = _path('DATA_DIR', ROOT / 'var')
EXPORTS_DIR = _path('EXPORTS_DIR', DATA_DIR / 'exports')
MARKET_DIR = _path('MARKET_DIR', DATA_DIR / 'market')
BUILD_DIR = _path('BUILD_DIR', DATA_DIR / 'build')
CONFIG_PATH = _path('CONFIG_PATH', ROOT / 'pipeline' / 'config.json')

APP_USER = os.environ.get('APP_USER', 'admin')
APP_PASSWORD = os.environ.get('APP_PASSWORD', '')
ALLOW_NO_AUTH = os.environ.get('ALLOW_NO_AUTH', '') == '1'
FETCH_TIMES = [t.strip() for t in os.environ.get('FETCH_TIMES', '').split(',') if t.strip()]
TZ_NAME = os.environ.get('TZ_NAME', 'America/Toronto')
MAX_UPLOAD_MB = float(os.environ.get('MAX_UPLOAD_MB', '20'))
FETCH_COOLDOWN_S = int(os.environ.get('FETCH_COOLDOWN_S', '60'))

for d in (EXPORTS_DIR, MARKET_DIR, BUILD_DIR):
    d.mkdir(parents=True, exist_ok=True)
