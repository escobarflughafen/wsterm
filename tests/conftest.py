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
