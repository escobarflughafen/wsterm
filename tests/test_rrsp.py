"""An account type the app has never seen (RRSP) must flow through import, ledger, rules and the built output."""
import json

import pytest

import store


def test_rrsp_imports_and_reconciles(fixture_bytes):
    s = store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('activities_rrsp.csv')])
    assert s['added'] == 7                                   # 4 TFSA rows + 3 RRSP rows
    assert 'RRSP' in s['after']['accounts']
    store.commit(s['id'])
    assert set(store.status()['activities']['accounts']) == {'TFSA', 'RRSP'}


def test_rrsp_positions_and_cash(fixture_bytes):
    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    from ledger import build_positions, load_activities
    pos = build_positions(load_activities())
    rrsp = pos[('RRSP', 'VOO', 'USD')]
    assert rrsp['q'] == 3 and round(rrsp['cost'], 2) == 1600.0   # 2 @ 505 + 1 @ 590
    assert rrsp['buys'] == 2 and rrsp['sells'] == 0


def test_registered_rules_cover_every_registered_account():
    from settings import CONFIG_PATH
    cfg = json.load(open(CONFIG_PATH))
    assert 'RRSP' in cfg['registered_accounts'] and 'TFSA' in cfg['registered_accounts']
    assert 'max_trades_per_month_registered' in cfg['rules']


def test_rrsp_flows_through_the_whole_build(fixture_bytes, synthetic_market):
    """End to end: an account type the code never names still gets value, rules and per-account series."""
    import json
    import build_app
    from settings import BUILD_DIR

    store.commit(store.preview([fixture_bytes('activities_rrsp.csv'), fixture_bytes('holdings_rrsp.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))

    assert [a['acct'] for a in d['accounts']] == ['RRSP']
    rrsp = d['accounts'][0]
    assert rrsp['value'] == 3248.0 and rrsp['contrib'] == 2800.0 and rrsp['gain'] == 448.0
    assert ('RRSP', 'VOO', 3.0) in [(h['acct'], h['sym'], h['qty']) for h in d['holdings']]
    assert 'RRSP' in d['series']['accounts'] and 'RRSP' in d['series']['account_contrib']
    registered = next(r for r in d['rules'] if 'REGISTERED ACCOUNTS' in r['name'])
    assert 'RRSP' in registered['detail']          # the rule checks it, not just the TFSA


def test_activity_only_build_derives_current_holdings(fixture_bytes, synthetic_market):
    import json
    import build_app
    from settings import BUILD_DIR

    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))

    assert d['holdings_source'] == 'activities'
    assert 'ESTIMATED FROM ACTIVITIES' in d['asof']
    voo = next(h for h in d['holdings'] if h['sym'] == 'VOO')
    cash = next(h for h in d['holdings'] if h['sym'] == 'USD CASH')
    assert (voo['acct'], voo['qty'], voo['px'], voo['mv']) == ('RRSP', 3.0, 640.0, 1920.0)
    assert cash['mv'] == 400.0
