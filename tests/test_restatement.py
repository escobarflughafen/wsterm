"""Wealthsimple restates rows between exports; the newest export must win for the window it covers."""
import store

H = ','.join(store.ACTIVITY_COLUMNS) + '\n'
OPTION_V1 = ('2026-09-17,12:29:57,2026-09-18,ACC1,Non-registered,Trade,BUY,'
             'OPEN  261002C00002500: Bought 4 contract (executed at 2026-09-17),LONG,OPEN  261002C00002500,OPEN,'
             'Opendoor Technologies Inc,USD,4,0.18,0,-72\n')
OPTION_V2 = ('2026-09-17,12:29:57,2026-09-18,ACC1,Non-registered,Trade,BUY,'
             '"OPEN  261002C00002500: Bought 4 contract (executed at 2026-09-17), FX Rate: 1.3985",LONG,'
             'OPEN  261002C00002500,OPEN,Opendoor Technologies Inc,USD,4,18,0,-72\n')
EARLIER = ('2026-09-16,10:00:00,2026-09-17,ACC1,Non-registered,Trade,BUY,RY.TO - Royal Bank: Bought 4,LONG,RY.TO,'
           'RY.TO,Royal Bank of Canada,CAD,4,285.08,0,-1140.32\n')
TWO_FILLS = ('2026-09-18,09:30:00,2026-09-19,ACC1,Non-registered,Trade,BUY,X: Bought 1,LONG,X,X,X Corp,USD,1,10,0,-10\n') * 2


def rows_for(symbol):
    return [r for r in store.load_activity_rows() if r['symbol'].startswith(symbol)]


def test_restated_row_replaces_instead_of_duplicating():
    store.commit(store.preview([('v1.csv', (H + EARLIER + OPTION_V1).encode())])['id'])
    s = store.preview([('v2.csv', (H + EARLIER + OPTION_V2).encode())])
    assert s['added'] == 0 and s['restated'] == 1 and s['removed'] == 0
    store.commit(s['id'])
    open_rows = rows_for('OPEN')
    assert len(open_rows) == 1                                   # one fill, not two
    assert open_rows[0]['unit_price'] == '18'                    # the newer convention won
    assert 'FX Rate' in open_rows[0]['description']
    assert sum(float(r['quantity']) for r in open_rows) == 4


def test_two_genuine_fills_in_one_file_both_survive():
    store.commit(store.preview([('fills.csv', (H + TWO_FILLS).encode())])['id'])
    assert len(rows_for('X')) == 2
    again = store.preview([('fills.csv', (H + TWO_FILLS).encode())])
    assert again['added'] == 0
    store.commit(again['id'])
    assert len(rows_for('X')) == 2


def test_partial_export_leaves_older_history_alone():
    store.commit(store.preview([('full.csv', (H + EARLIER + OPTION_V1).encode())])['id'])
    partial = store.preview([('partial.csv', (H + OPTION_V2).encode())])   # only 2026-09-17
    assert partial['kept_outside'] == 1                                    # the RY.TO row is outside the window
    store.commit(partial['id'])
    assert len(rows_for('RY.TO')) == 1 and len(rows_for('OPEN')) == 1


def test_cancelled_trade_disappears_when_the_window_is_re_exported():
    """Coverage is inferred from the rows themselves, so the re-export must still span the cancelled day."""
    store.commit(store.preview([('v1.csv', (H + EARLIER + OPTION_V1).encode())])['id'])
    s = store.preview([('v2.csv', (H + EARLIER + TWO_FILLS).encode())])    # spans 09-16..09-18, no OPEN trade
    assert s['removed'] == 1
    store.commit(s['id'])
    assert rows_for('OPEN') == []
    assert len(rows_for('RY.TO')) == 1


def test_export_that_stops_short_cannot_delete_later_rows():
    store.commit(store.preview([('v1.csv', (H + EARLIER + OPTION_V1).encode())])['id'])
    s = store.preview([('older.csv', (H + EARLIER).encode())])             # window ends 09-16
    assert s['removed'] == 0 and s['kept_outside'] == 1
    store.commit(s['id'])
    assert len(rows_for('OPEN')) == 1
