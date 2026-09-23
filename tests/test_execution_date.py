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


FX_BUY = 'QQQ - Invesco QQQ Trust: Bought 3.0000 shares at $883.18 per share (executed at 2026-04-14), FX Rate: 1.4000'


def test_a_us_buy_paid_in_cad_is_restated_in_usd(tmp_path):
    """The sell comes back in USD; the buy has to be in the same currency or the position never closes."""
    path = write(tmp_path, [dict(row('2026-04-14', '16:49:02', FX_BUY, qty='3', price='883.18', net='-2649.54'),
                                 currency='CAD')])
    a = ledger.load_activities(path)[0]
    assert a['currency'] == 'USD'
    assert abs(float(a['unit_price']) - 630.8428571) < 1e-6
    assert a['net_cash_amount'] == '-1892.53'
    assert (a['booked_currency'], a['booked_net_cash_amount']) == ('CAD', '-2649.54')
    assert ledger.cash_leg(a) == ('CAD', -2649.54)  # the CAD that actually left the account


def test_a_cdr_bought_in_cad_stays_in_cad(tmp_path):
    path = write(tmp_path, [dict(row('2026-05-08', '08:04:18', 'NVDA - Nvidia CDR (CAD Hedged): Bought 50.0000 shares '
                                     '(executed at 2026-05-08)', qty='50', price='48.58', net='-2429'), currency='CAD')])
    a = ledger.load_activities(path)[0]
    assert (a['currency'], a['net_cash_amount']) == ('CAD', '-2429')


def test_a_round_trip_across_currencies_leaves_no_position(tmp_path):
    path = write(tmp_path, [
        dict(row('2026-04-14', '16:49:02', FX_BUY, qty='3', price='883.18', net='-2649.54'), currency='CAD'),
        row('2026-05-13', '10:00:00', 'Sold 3.0000 shares (executed at 2026-05-13), FX Rate: 1.3699',
            qty='-3', price='713.52', net='2140.56'),
    ])
    pos = ledger.build_positions(ledger.load_activities(path))
    assert all(abs(p['q']) < 1e-9 for p in pos.values())
    assert list(pos) == [('TFSA', 'VOO', 'USD')]


def test_trade_ids_survive_the_currency_restatement(tmp_path):
    raw = dict(row('2026-04-14', '16:49:02', FX_BUY, qty='3', price='883.18', net='-2649.54'), currency='CAD')
    assert engine.trade_id(raw) == engine.trade_id(ledger.load_activities(write(tmp_path, [dict(raw)]))[0])


def test_a_us_sell_booked_in_usd_keeps_its_cash_in_usd(tmp_path):
    """The rate is printed on every US trade, including ones paid from USD cash, so it moves nothing by itself."""
    path = write(tmp_path, [row('2026-05-13', '10:00:00', 'Sold 3.0000 shares (executed at 2026-05-13), FX Rate: 1.4000',
                                qty='-3', price='700', net='2100')])
    a = ledger.load_activities(path)[0]
    assert (a['currency'], a['net_cash_amount']) == ('USD', '2100')
    assert ledger.cash_leg(a) == ('USD', 2100.0)


def test_an_expired_option_closes_and_realises_its_premium(tmp_path):
    sym = 'ASTS  260918C00060000'
    buy = dict(row('2026-09-18', '11:30:35', f'{sym}: Bought 2 contract (executed at 2026-09-18), FX Rate: 1.4000',
                   qty='2', price='3', net='-6'), symbol=sym)
    expiry = dict(row('2026-09-18', '13:15:00', f'{sym}: Expired 2 contract (executed at 2026-09-18)', qty='-2'),
                  symbol=sym, activity_type='OptionExpiry', activity_sub_type='-', currency='', unit_price='',
                  net_cash_amount='', commission='')
    acts = ledger.load_activities(write(tmp_path, [buy, expiry]))
    assert [ledger.cash_leg(a) for a in acts] == [('USD', -6.0), ('USD', 0.0)]
    p = ledger.build_positions(acts)[('TFSA', sym, 'USD')]
    assert abs(p['q']) < 1e-9 and p['realized'] == -6
