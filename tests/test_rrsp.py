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
    assert d['asof'] == '2026-02-09'            # how fresh the ledger is, the only source there is
    assert d['reconcile'] is None               # nothing to check against
    voo = next(h for h in d['holdings'] if h['sym'] == 'VOO')
    cash = next(h for h in d['holdings'] if h['sym'] == 'USD CASH')
    assert (voo['acct'], voo['qty'], voo['px'], voo['mv']) == ('RRSP', 3.0, 640.0, 1920.0)
    assert cash['mv'] == 400.0


def test_a_stale_holdings_report_cannot_freeze_nav(fixture_bytes, synthetic_market):
    """The ledger is the source. A holdings report taken before the newest trade must not override it,
    and every line it disagrees on has to be named rather than silently winning."""
    import json
    import build_app
    from settings import BUILD_DIR

    # The report is as of 2026-01-31: it predates the 2026-02-09 purchase of a third VOO share.
    store.commit(store.preview([fixture_bytes('activities_rrsp.csv'), fixture_bytes('holdings_rrsp_stale.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))

    voo = next(h for h in d['holdings'] if h['sym'] == 'VOO')
    cash = next(h for h in d['holdings'] if h['sym'] == 'USD CASH')
    assert voo['qty'] == 3.0 and cash['mv'] == 400.0          # the ledger, not the report's 2 and 990
    assert d['summary']['total'] == 3248.0                    # (3 x 640 + 400) USD at 1.4

    r = d['reconcile']
    assert r['stale'] is True and r['asof'].startswith('2026-01-31') and r['newest_activity'] == '2026-02-09'
    assert r['ledger_value'] == 3248.0 and r['report_value'] == 3178.0
    assert {(x['sym'], x['diff']) for x in r['differences']} == {('VOO', 1.0), ('USD CASH', -590.0)}


def test_a_current_holdings_report_reports_no_differences(fixture_bytes, synthetic_market):
    import json
    import build_app
    from settings import BUILD_DIR

    store.commit(store.preview([fixture_bytes('activities_rrsp.csv'), fixture_bytes('holdings_rrsp.csv')])['id'])
    build_app.main()
    r = json.load(open(BUILD_DIR / 'data.json'))['reconcile']
    assert r['stale'] is False and r['differences'] == []
    assert r['ledger_value'] == r['report_value']


def test_satellite_bucket_and_deployment_rules(fixture_bytes, synthetic_market, monkeypatch):
    """A structural non-US holding gets its own cap so the speculative rule stops flagging it."""
    import json
    import build_app
    from settings import BUILD_DIR, CONFIG_PATH

    cfg = json.load(open(CONFIG_PATH))
    cfg['categories']['satellite'] = ['VOO']          # stand-in: the fixture only trades VOO
    cfg['categories']['core'] = [s for s in cfg['categories']['core'] if s != 'VOO']
    cfg['targets']['satellite'] = 0.03
    cfg['rules']['max_satellite_pct_of_invested'] = 0.04
    cfg['rules']['max_offense_cad_nonregistered'] = 5000
    cfg['dca'] = dict(usd_ladder=['VOO'], usd_dip_ticker='VOO', usd_dip_pct=-0.02,
                      cad_ticker='VOO', monthly_cad=1000)
    cfg['satellite_exit'] = {'VOO': 0.5}
    monkeypatch.setattr(build_app, 'CFG', cfg)
    monkeypatch.setattr(build_app.engine, 'CFG', cfg)

    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))

    voo = next(h for h in d['holdings'] if h['sym'] == 'VOO')
    assert voo['cat'] == 'satellite'                  # reclassified out of the default bucket
    assert 'satellite' in d['alloc']['now']

    names = {r['name']: r for r in d['rules']}
    sat = next(r for n, r in names.items() if n.startswith('SATELLITE'))
    assert sat['ok'] is False                         # 100% of invested, well past the 4% cap
    assert any('exit target' in i for i in sat['items'])
    off = next(r for n, r in names.items() if n.startswith('NON-REGISTERED OFFENCE'))
    assert off['ok'] is True                          # nothing speculative in the non-registered book

    p = d['dca']
    assert p['target'] == 'VOO' and p['unit_usd'] == 640.0
    assert p['shares_now'] == int(p['usd_cash'] // 640.0)
