from ledger import build_positions


def act(date, kind, sym, qty, net, cur='USD', price='', acct='TFSA'):
    return dict(effective_date=date, effective_time='10:00:00', account_type=acct, activity_type=kind, symbol=sym,
                currency=cur, quantity=str(qty), unit_price=str(price), net_cash_amount=str(net))


def test_average_cost_realized_gain():
    pos = build_positions([
        act('2026-01-01', 'Trade', 'X', 2, -1000, price=500),
        act('2026-01-02', 'Trade', 'X', 2, -1200, price=600),
        act('2026-01-03', 'Trade', 'X', -2, 1400, price=700),
    ])
    p = pos[('TFSA', 'X', 'USD')]
    assert round(p['realized'], 2) == 300.0  # avg cost 550
    assert p['q'] == 2 and round(p['cost'], 2) == 1100.0


def test_transfer_out_drains_position_booked_in_other_currency():
    pos = build_positions([
        act('2025-01-01', 'Trade', 'NVDA', 9, -1600, cur='CAD', price=178),
        act('2025-03-14', 'InternalSecurityTransfer', 'NVDA', -9, -1095, cur='USD'),
    ])
    assert pos[('TFSA', 'NVDA', 'CAD')]['q'] == 0
    assert pos[('TFSA', 'NVDA', 'USD')]['q'] == 0
