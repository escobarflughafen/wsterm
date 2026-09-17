import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_public_market_cache_is_separate_from_private_guest_metadata(tmp_path):
    private = tmp_path / 'private'
    public = tmp_path / 'public'
    env = dict(os.environ, DATA_DIR=str(tmp_path / 'data'), MARKET_DIR=str(private), PUBLIC_MARKET_DIR=str(public),
               ALLOW_NO_AUTH='1', APP_PASSWORD='')
    code = """
import sys
sys.path.insert(0, 'pipeline')
import market_data, prices, settings
assert settings.MARKET_DIR.name == 'private'
assert settings.PUBLIC_MARKET_DIR.name == 'public'
assert market_data.DATA.endswith('/private')
assert market_data.PUBLIC_DATA.endswith('/public')
assert market_data.PRICES.endswith('/public/prices')
assert market_data.STATE.endswith('/public/fetch_state.json')
assert prices.DATA.endswith('/public')
assert prices.PRIVATE_DATA.endswith('/private')
"""
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, check=True)
