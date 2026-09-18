import audit
import engine
import pytest


def act(date, sym, qty, price, net, time='10:00:00', acct='TFSA', cur='USD'):
    return dict(effective_date=date, effective_time=time, settlement_date='', account_id='TEST', account_type=acct,
                activity_type='Trade', activity_sub_type='BUY' if qty > 0 else 'SELL', description='', direction='LONG',
                symbol=sym, currency=cur, quantity=str(qty), unit_price=str(price), net_cash_amount=str(net))


def test_campaign_decisions_fixed_horizons_and_indices(synthetic_market):
    acts = [
        act('2026-01-02', 'VOO', 1, 700, -700),
        act('2026-01-20', 'VOO', 1, 500, -500),       # market remains below the $700 average: add to loser
        act('2026-02-10', 'VOO', -1, 600, 600),       # partial reduction
        act('2026-02-20', 'VOO', -1, 620, 620),       # flat: closes campaign
        act('2026-02-23', 'VOO', 1, 610, -610),       # starts campaign 2
    ]
    out = audit.build(acts, engine.Calendar('2026-01-02'))
    classes = [d['class'] for d in out['decisions']]
    assert classes == ['OPEN', 'ADD_TO_LOSER', 'REDUCE_LOSER', 'CLOSE_LOSER', 'OPEN']
    assert len({d['campaign'] for d in out['decisions']}) == 2
    assert out['decisions'][0]['er_20d'] > 0           # VOO rises faster than XEQT in the fixture
    first = out['decisions'][0]
    assert first['factor_20d'] == pytest.approx((1 + first['cad_20d']) / (1 + first['benchmark_20d']), abs=1e-6)
    assert out['decisions'][2]['er_20d'] < 0           # the same move makes selling relatively costly
    assert out['indices']['base'] == 1.0
    assert out['indices']['curves']['OPEN']['20d'][-1] > 1
    assert len(out['indices']['dates']) > len(out['decisions'])
    end_i = out['indices']['dates'].index(first['end_20d'])
    curve, counts = out['indices']['curves']['OPEN']['20d'], out['indices']['counts']['OPEN']['20d']
    assert curve[0] is None and counts[0] == 0          # no line before any score has matured
    assert curve[end_i] > 1 and counts[end_i] == 1      # evidence enters only when 20D has elapsed
    assert out['coverage']['daily_priced'] == len(out['decisions'])


def test_index_averages_overlapping_windows_instead_of_compounding(synthetic_market):
    """Two identical entries must not double the curve: overlapping windows are one move, not two."""
    pair = [act('2026-01-02', 'VOO', 1, 700, -700), act('2026-01-05', 'VOO', 1, 700, -700, acct='FHSA')]
    one = audit.build(pair[:1], engine.Calendar('2026-01-02'))
    two = audit.build(pair, engine.Calendar('2026-01-02'))
    factors = [d['factor_20d'] for d in two['decisions']]
    a = one['indices']['curves']['OPEN']['20d'][-1]
    b = two['indices']['curves']['OPEN']['20d'][-1]
    assert len(factors) == 2 and a > 1 and b > 1
    assert b == pytest.approx((factors[0] * factors[1]) ** 0.5, abs=1e-5)   # geometric mean
    assert b < factors[0] * factors[1] * 0.95                              # nothing like a product
    assert abs(b - a) < 0.01                    # a second similar decision does not double the claim


def test_bootstrap_band_contains_its_own_point_estimate(synthetic_market):
    """The band resamples campaigns but must estimate the decision-weighted mean the table prints."""
    acts = [act(d, 'VOO', 1, 700, -700) for d in ('2026-01-02', '2026-01-05', '2026-01-06')]
    acts += [act('2026-01-20', 'VOO', 1, 500, -500, acct='FHSA'), act('2026-02-10', 'VOO', -1, 600, 600, acct='FHSA')]
    for row in audit.build(acts, engine.Calendar('2026-01-02'))['summary']:
        assert row['lo_20d'] <= row['er_20d'] <= row['hi_20d'], row['cls']


def test_transfer_out_drains_the_book_that_holds_the_shares(synthetic_market):
    """US names bought under the CAD key transfer out against that key, never by inventing shares."""
    acts = [act('2026-01-02', 'VOO', 4, 500, -2000, cur='CAD'),
            dict(act('2026-01-20', 'VOO', -4, 500, -2000, cur='USD'), activity_type='InternalSecurityTransfer')]
    out = audit.build(acts, engine.Calendar('2026-01-02'))
    held = out['concentration']['ranked']
    assert [c['cur'] for c in held] == ['CAD']            # the USD row never becomes a position
    assert held[0]['open'] is False and held[0]['end'] == '2026-01-20'
    assert held[0]['transferred'] is True                 # book value moved out; this is not a sale


def test_options_are_separate_from_timing_but_remain_in_campaign_pnl(synthetic_market):
    acts = [
        act('2026-01-02', 'VOO', 1, 500, -500),
        act('2026-01-05', 'VOO   260320C00500000', 1, 20, -20),
    ]
    out = audit.build(acts, engine.Calendar('2026-01-02'))
    assert len(out['decisions']) == 1
    assert out['options']['campaigns'] == 1
    assert out['options']['timing_excluded'] is True
    assert any(c['option'] for c in out['concentration']['ranked'])


def test_concentration_replays_without_top_campaigns(synthetic_market):
    acts = [act('2026-01-02', 'VOO', 1, 500, -500), act('2026-02-02', 'VOO', -1, 580, 580),
            act('2026-02-03', 'VOO', 1, 580, -580)]
    out = audit.build(acts, engine.Calendar('2026-01-02'))
    c = out['concentration']
    assert len(c['ranked']) == 2
    assert [r['n'] for r in c['removals']] == [0, 1, 3, 5]      # row 0 is the actual portfolio
    assert c['removals'][0]['return_'] == c['actual_return']
    assert c['removals'][0]['trades_removed'] == 0
    assert c['removals'][1]['trades_removed'] == 2
    assert c['top_positive_share']['1'] is not None
    assert 'trade_ids' not in c['ranked'][0]


def test_reconciliation_explains_the_gap_to_portfolio_gain(synthetic_market):
    acts = [act('2026-01-02', 'VOO', 1, 500, -500),
            dict(act('2026-01-15', 'VOO', 0, 0, 3.5), activity_type='Dividend', quantity='0')]
    r = audit.build(acts, engine.Calendar('2026-01-02'))['reconciliation']
    assert r['income_total'] == pytest.approx(3.5 * 1.3, abs=0.6)   # the dividend is not campaign P&L
    assert r['portfolio_gain'] == pytest.approx(r['campaign_pnl'] + r['income_total'] + r['residual'], abs=0.01)
