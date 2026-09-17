"""Test environment: isolated DATA_DIR and auth, set before any app module is imported."""
import os, shutil, sys, tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix='portfolio-test-'))
os.environ.update(DATA_DIR=str(TMP), APP_USER='tester', APP_PASSWORD='secret', FETCH_TIMES='', ALLOW_NO_AUTH='')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def fixture_bytes():
    return lambda name: (name, (FIXTURES / name).read_bytes())


@pytest.fixture(autouse=True)
def clean_exports():
    import store
    yield
    for p in (store.ACTIVITIES, store.HOLDINGS):
        p.unlink(missing_ok=True)
    for d in (store.UPLOADS, store.STAGING, store.INBOX):
        shutil.rmtree(d, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture
def synthetic_market():
    """A tiny price world (VOO 500→640 USD, XEQT flat-ish, USD/CAD 1.4) so builds and simulations can run."""
    import csv as _csv, json as _json, shutil
    import pandas as pd
    import prices
    from settings import MARKET_DIR, DATA_DIR
    days = pd.bdate_range('2026-01-01', '2026-03-31')
    (MARKET_DIR / 'prices').mkdir(parents=True, exist_ok=True)
    for ticker, start, end in (('VOO', 500.0, 640.0), ('XEQT.TO', 40.0, 44.0)):
        closes = [start + (end - start) * i / (len(days) - 1) for i in range(len(days))]
        pd.DataFrame({'Date': days, 'Open': closes, 'High': closes, 'Low': closes, 'Close': closes,
                      'Adj Close': closes, 'Volume': 0, 'Dividends': 0.0, 'Stock Splits': 0.0}
                     ).to_csv(MARKET_DIR / 'prices' / f'{ticker}.csv', index=False)
    pd.DataFrame({'Date': days, 'USDCAD': 1.4}).to_csv(MARKET_DIR / 'fx_usdcad.csv', index=False)
    with open(MARKET_DIR / 'tickers.csv', 'w', newline='') as f:
        _csv.writer(f).writerows([['ws_symbol', 'currency', 'yahoo'], ['VOO', 'USD', 'VOO']])
    shutil.copy(Path(__file__).parents[1] / 'pipeline' / 'config.example.json', DATA_DIR / 'config.json')
    for fn in (prices.history, prices.ticker_map, prices.fx_usdcad):
        fn.cache_clear()
    yield
    for fn in (prices.history, prices.ticker_map, prices.fx_usdcad):
        fn.cache_clear()
