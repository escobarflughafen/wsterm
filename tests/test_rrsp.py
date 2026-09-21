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


def test_single_stock_cap_counts_a_ticker_across_accounts(fixture_bytes, synthetic_market, monkeypatch):
    """One company in two accounts is one exposure: each slice can pass while the total breaks the cap."""
    import json
    import build_app
    from settings import BUILD_DIR, CONFIG_PATH

    cfg = json.load(open(CONFIG_PATH))
    cfg['categories']['core'] = [s for s in cfg['categories']['core'] if s != 'VOO']   # VOO stands in for a stock
    monkeypatch.setattr(build_app, 'CFG', cfg)
    monkeypatch.setattr(build_app.engine, 'CFG', cfg)

    store.commit(store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('activities_rrsp.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))
    slices = [h['weight'] for h in d['holdings'] if h['sym'] == 'VOO']
    assert len(slices) == 2

    cfg['rules']['max_single_stock_pct'] = (max(slices) + sum(slices)) / 2   # above either slice, below the sum
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))
    rule = next(r for r in d['rules'] if r['id'] == 'single_stock')
    assert rule['ok'] is False
    assert len(rule['items']) == 1 and rule['items'][0].startswith('VOO ')
    assert 'TFSA' in rule['items'][0] and 'RRSP' in rule['items'][0]


def test_rules_carry_my_own_wording_and_a_monthly_todo(fixture_bytes, synthetic_market, monkeypatch):
    """A rule renamed in config keeps its mechanical spec beside it, and the to-do list is actionable."""
    import json
    import build_app
    from settings import BUILD_DIR, CONFIG_PATH

    cfg = json.load(open(CONFIG_PATH))
    cfg['rule_text'] = {'single_stock': '单一个股别超过 4%'}
    cfg['rules']['min_monthly_core_cad'] = 1000
    cfg['dca'] = dict(usd_ladder=['VOO'], usd_dip_ticker='VOO', usd_dip_pct=-0.02,
                      cad_ticker='VOO', monthly_cad=1000)
    monkeypatch.setattr(build_app, 'CFG', cfg)
    monkeypatch.setattr(build_app.engine, 'CFG', cfg)

    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    build_app.main()
    d = json.load(open(BUILD_DIR / 'data.json'))

    mine = next(r for r in d['rules'] if r['id'] == 'single_stock')
    assert mine['name'] == '单一个股别超过 4%'          # my words on top
    assert mine['spec'].startswith('SINGLE STOCK')     # the threshold still shown underneath
    untouched = next(r for r in d['rules'] if r['id'] == 'averaging_down')
    assert untouched['name'] == untouched['spec']      # no override, no change

    todos = {t['id']: t for t in d['todos']}
    assert todos['core_buy']['done'] is False
    assert todos['core_buy']['amount'] > 0             # how much is still owed, not just that it failed
    assert 'of $1,000 net' in todos['core_buy']['detail']
    assert todos['trade_budget']['done'] is True


def test_compare_series_survive_a_transfer(fixture_bytes, synthetic_market):
    """Shares moving between accounts carry their book value with them; the capital must move too,
    or the position reads as a total loss for as long as it is away."""
    import json
    import build_app
    from settings import BUILD_DIR

    acts = [
        dict(effective_date='2026-01-05', effective_time='09:00:00', settlement_date='', account_id='A1',
             account_type='TFSA', activity_type='MoneyMovement', activity_sub_type='EFT', description='Deposit',
             direction='', symbol='', **{'underlying symbol': ''}, name='', currency='USD', quantity='',
             unit_price='', commission='', net_cash_amount='2000'),
        dict(effective_date='2026-01-07', effective_time='10:00:00', settlement_date='', account_id='A1',
             account_type='TFSA', activity_type='Trade', activity_sub_type='BUY',
             description='VOO - Vanguard: Bought 2.0000 shares', direction='LONG', symbol='VOO',
             **{'underlying symbol': 'VOO'}, name='Vanguard', currency='USD', quantity='2', unit_price='505',
             commission='0', net_cash_amount='-1010'),
        dict(effective_date='2026-02-02', effective_time='10:00:00', settlement_date='', account_id='A1',
             account_type='TFSA', activity_type='InternalSecurityTransfer', activity_sub_type='',
             description='VOO transferred out', direction='LONG', symbol='VOO', **{'underlying symbol': 'VOO'},
             name='Vanguard', currency='USD', quantity='-2', unit_price='', commission='',
             net_cash_amount='-1100'),
    ]
    import csv
    path = BUILD_DIR.parent / 'transfer_acts.csv'
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(acts[0])); w.writeheader(); w.writerows(acts)
    store.commit(store.preview([('activities.csv', path.read_bytes())])['id'])
    build_app.main()
    c = json.load(open(BUILD_DIR / 'compare.json'))['VOO']

    assert c['held'] is False and c['value'][-1] == 0
    assert min(c['gain']) > -200      # not the full -1,100 the shares were worth when they left
    assert c['peak_cost'] > 0
