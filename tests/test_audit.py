import audit
import engine


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
    assert out['decisions'][2]['er_20d'] < 0           # the same move makes selling relatively costly
    assert out['indices']['base'] == 100
    assert out['indices']['curves']['OPEN']['20d'][-1] > 100
    assert out['coverage']['daily_priced'] == len(out['decisions'])


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
    assert [r['n'] for r in c['removals']] == [1, 3, 5]
    assert c['removals'][0]['trades_removed'] == 2
    assert c['top_positive_share']['1'] is not None
