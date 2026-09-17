import store


def test_detects_file_types(fixture_bytes):
    assert store.detect(fixture_bytes('activities_jan.csv')[1].decode()) == 'activities'
    assert store.detect(fixture_bytes('holdings_feb.csv')[1].decode()) == 'holdings'
    assert store.detect('a,b,c\n1,2,3\n') is None


def test_rejects_unknown_and_malformed_files():
    bad_rows = ','.join(store.ACTIVITY_COLUMNS) + '\n' + 'not-a-date,,,,TFSA,Trade,BUY,,,,,,USD,abc,1,0,1\n'
    s = store.preview([('random.csv', b'x,y\n1,2\n'), ('broken.csv', bad_rows.encode())])
    assert not s['committable']
    assert 'header does not match' in s['files'][0]['errors'][0]
    assert 'effective_date' in s['files'][1]['errors'][0] and 'quantity' in s['files'][1]['errors'][0]


def test_import_keeps_identical_rows_and_skips_overlap(fixture_bytes):
    s = store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('holdings_jan.csv')])
    assert s['added'] == 4  # the two identical buys are both real trades
    assert s['reconciliation_total'] == 0
    r = store.commit(s['id'])
    assert r['added'] == 4 and r['holdings_updated']
    assert len(r['archived']) == 2 and all((store.UPLOADS / a).exists() for a in r['archived'])

    s2 = store.preview([fixture_bytes('activities_feb.csv'), fixture_bytes('holdings_feb.csv')])
    assert (s2['added'], s2['duplicates']) == (1, 1)  # the Jan 20 dividend overlaps
    store.commit(s2['id'])
    assert store.status()['activities']['rows'] == 5
    assert store.holdings_asof() == '2026-02-12T18:00'

    again = store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('activities_feb.csv')])
    assert again['added'] == 0 and again['duplicates'] == 6


def test_older_holdings_are_not_applied_unless_forced(fixture_bytes):
    store.commit(store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('holdings_feb.csv')])['id'])
    older = store.preview([fixture_bytes('holdings_jan.csv')])
    assert any('Older than current holdings' in w for w in older['files'][0]['warnings'])
    assert not store.commit(older['id'])['holdings_updated']
    older = store.preview([fixture_bytes('holdings_jan.csv')])
    assert store.commit(older['id'], force_holdings=True)['holdings_updated']
    assert store.holdings_asof() == '2026-01-31T18:00'


def test_reconciliation_flags_mismatched_exports(fixture_bytes):
    s = store.preview([fixture_bytes('activities_jan.csv'), fixture_bytes('holdings_feb.csv')])
    assert s['reconciliation_total'] == 1 and 'activities give 4' in s['reconciliation'][0]


def test_inbox_imports_good_files_and_quarantines_bad(fixture_bytes):
    store.INBOX.mkdir(parents=True, exist_ok=True)
    (store.INBOX / 'activities_jan.csv').write_bytes(fixture_bytes('activities_jan.csv')[1])
    (store.INBOX / 'junk.csv').write_bytes(b'x,y\n1,2\n')
    result = store.process_inbox()
    assert result['added'] == 4
    assert not list(store.INBOX.glob('*.csv'))
    assert (store.INBOX / 'rejected' / 'junk.csv').exists()


def test_commit_rejects_bad_ids():
    import pytest
    with pytest.raises(store.ImportError_):
        store.commit('../../etc')
