"""Wealthsimple stamps an order when it is placed. The ledger has to key off when it executed."""
import csv

import engine
import ledger


def row(effective_date, time, description, qty='1', price='100', net='-100'):
    return dict(effective_date=effective_date, effective_time=time, settlement_date='', account_id='A1',
                account_type='TFSA', activity_type='Trade', activity_sub_type='BUY' if float(qty) > 0 else 'SELL',
                description=description, direction='LONG', symbol='VOO', underlying_symbol='', name='Vanguard',
                currency='USD', quantity=qty, unit_price=price, commission='0', net_cash_amount=net)


def write(tmp_path, rows):
    path = tmp_path / 'activities.csv'
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return str(path)


def test_an_overnight_order_belongs_to_the_session_that_filled_it(tmp_path):
    path = write(tmp_path, [row('2026-01-05', '23:13:50', 'Bought 1.0000 shares (executed at 2026-01-06)')])
    a = ledger.load_activities(path)[0]
    assert a['effective_date'] == '2026-01-06'      # the day the shares actually moved
    assert a['booked_date'] == '2026-01-05'         # what the broker booked, kept for identity
    assert a['order_time'] == '23:13:50'
    assert a['effective_time'] == '00:00:00'        # a queued order has no fill time to claim


def test_a_same_session_order_keeps_its_time(tmp_path):
    path = write(tmp_path, [row('2026-01-06', '09:32:10', 'Bought 1.0000 shares (executed at 2026-01-06)')])
    a = ledger.load_activities(path)[0]
    assert (a['effective_date'], a['effective_time'], a['booked_date']) == ('2026-01-06', '09:32:10', '2026-01-06')


def test_a_queued_order_sorts_ahead_of_that_session_s_live_orders(tmp_path):
    """23:13 the night before is in the queue before 09:32 the next morning, not eight hours after it."""
    path = write(tmp_path, [
        row('2026-01-06', '09:32:10', 'Bought 1.0000 shares (executed at 2026-01-06)', net='-101'),
        row('2026-01-05', '23:13:50', 'Bought 1.0000 shares (executed at 2026-01-06)', net='-100'),
    ])
    assert [a['net_cash_amount'] for a in ledger.load_activities(path)] == ['-100', '-101']


def test_a_description_without_an_execution_date_is_left_alone(tmp_path):
    path = write(tmp_path, [row('2026-01-05', '10:00:00', 'Bought 1.0000 shares')])
    a = ledger.load_activities(path)[0]
    assert a['effective_date'] == '2026-01-05' and a['effective_time'] == '10:00:00'


def test_trade_ids_survive_the_correction(tmp_path):
    """Ids hash what the broker booked, so a saved simulation selection still matches after this fix."""
    raw = row('2026-01-05', '23:13:50', 'Bought 1.0000 shares (executed at 2026-01-06)')
    before = engine.trade_id(raw)
    after = engine.trade_id(ledger.load_activities(write(tmp_path, [dict(raw)]))[0])
    assert before == after
