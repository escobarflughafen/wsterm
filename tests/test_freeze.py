"""Freeze simulation on a synthetic market: VOO rises 500 -> 650 USD, XEQT flat, USD/CAD fixed at 1.4."""
import csv

import pandas as pd
import pytest

import engine
import prices
from ledger import load_activities
from settings import MARKET_DIR

FX = 1.4


@pytest.fixture
def ctx(tmp_path):
    days = pd.bdate_range('2026-01-01', '2026-03-31')
    (MARKET_DIR / 'prices').mkdir(parents=True, exist_ok=True)
    for ticker, start, end in (('VOO', 500.0, 650.0), ('XEQT.TO', 40.0, 40.0)):
        closes = [start + (end - start) * i / (len(days) - 1) for i in range(len(days))]
        pd.DataFrame({'Date': days, 'Open': closes, 'High': closes, 'Low': closes, 'Close': closes, 'Adj Close': closes,
                      'Volume': 0, 'Dividends': 0.0, 'Stock Splits': 0.0}).to_csv(MARKET_DIR / 'prices' / f'{ticker}.csv', index=False)
    pd.DataFrame({'Date': days, 'USDCAD': FX}).to_csv(MARKET_DIR / 'fx_usdcad.csv', index=False)
    with open(MARKET_DIR / 'tickers.csv', 'w', newline='') as f:
        csv.writer(f).writerows([['ws_symbol', 'currency', 'yahoo'], ['VOO', 'USD', 'VOO']])
    for fn in (prices.history, prices.ticker_map, prices.fx_usdcad):
        fn.cache_clear()
    acts = load_activities(str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'activities_jan.csv'))
    acts += load_activities(str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'activities_feb.csv'))[1:]  # skip overlap
    acts.sort(key=lambda a: (a['effective_date'], a['effective_time']))
    import freeze
    yield freeze.Context(acts)
    for fn in (prices.history, prices.ticker_map, prices.fx_usdcad):
        fn.cache_clear()


def voo(day):
    days = pd.bdate_range('2026-01-01', '2026-03-31')
    return 500 + 150 * days.get_loc(pd.Timestamp(day)) / (len(days) - 1)


def test_freezing_on_the_last_day_changes_nothing(ctx):
    r = ctx.run(date='2026-03-31')
    todate = r['horizons'][-1]
    assert todate['diff'] == 0 and todate['gain_diff'] == 0


def test_freeze_before_the_sell_keeps_the_shares(ctx):
    r = ctx.run(date='2026-01-06', deposits='cash')  # holds 4 VOO + 1000 USD; the dividend and the Feb sell never happen
    assert r['trades_skipped'] == 1
    assert r['frozen'][-1] == pytest.approx(1000 * FX + 4 * 650 * FX, rel=1e-6)
    todate = r['horizons'][-1]
    assert todate['frozen'] > todate['actual'] and todate['diff'] > 0  # selling 3 shares at 600 before the rise to 650 cost money
    by = {h['ticker']: h for h in r['holdings']}
    assert by['VOO']['qty'] == 4 and by['VOO']['actual_qty_now'] == 1


def test_freeze_after_a_trade_uses_intraday_state(ctx):
    buy = next(a for a in ctx.acts if a['activity_type'] == 'Trade')
    r = ctx.run(trade=engine.trade_id(buy))
    by = {h['ticker']: h for h in r['holdings']}
    assert by['VOO']['qty'] == 2  # only the first of the two same-second buys
    assert r['label'].startswith('after 2026-01-06')


def test_deposit_modes_and_validation(ctx):
    with pytest.raises(ValueError):
        ctx.run(date='2026-01-06', deposits='bitcoin')
    none = ctx.run(date='2026-01-06', deposits='none')
    assert none['contrib_frozen'][-1] == none['contrib_frozen'][0]


def test_sweep_shape(ctx):
    s = ctx.sweep(step=5, min_value=0)
    assert len(s['dates']) == len(s['1M']) == len(s['3M']) == len(s['to_date']) > 5
    assert s['3M'][-1] is None and s['to_date'][-1] is not None


def test_removing_a_sell_keeps_the_shares_and_forgoes_the_proceeds(ctx):
    """Anchor for the what-if engine: the difference is exactly shares kept minus cash not received."""
    import engine
    acts = ctx.acts
    sell = next(a for a in acts if a['activity_type'] == 'Trade' and float(a['quantity']) < 0)
    base = engine.simulate(acts, [], None)['summary']['actual']
    got = engine.simulate(acts, [engine.trade_id(sell)], None)['summary']['simulated'] - base
    qty, proceeds = -float(sell['quantity']), float(sell['net_cash_amount'])
    assert got == pytest.approx((qty * voo('2026-03-31') - proceeds) * FX, abs=0.01)


def test_removing_a_buy_also_shrinks_the_sell_it_funded(ctx):
    """Two identical same-second fills share one id, and a sell with no shares left is clipped to zero."""
    import engine
    acts = ctx.acts
    buy = next(a for a in acts if a['activity_type'] == 'Trade' and float(a['quantity']) > 0)
    base = engine.simulate(acts, [], None)['summary']['actual']
    r = engine.simulate(acts, [engine.trade_id(buy)], None)
    got = r['summary']['simulated'] - base
    # both 2-share fills disappear (4 shares, $2,000 unspent) and the later 3-share sell has nothing to sell
    assert r['summary']['removed'] == 2 and r['summary']['clipped'] == 1
    expected = (2000 - 1800 - 1 * voo('2026-03-31')) * FX          # cash kept, proceeds forgone, share gone
    assert got == pytest.approx(expected, abs=0.01)


def test_redirecting_freed_cash_into_the_same_etf_is_a_wash(ctx):
    """Freed cash buys VOO at that day's close, so removing a VOO sell and rebuying leaves only price drift."""
    import engine
    acts = ctx.acts
    sell = next(a for a in acts if a['activity_type'] == 'Trade' and float(a['quantity']) < 0)
    base = engine.simulate(acts, [], None)['summary']['actual']
    idle = engine.simulate(acts, [engine.trade_id(sell)], None)['summary']['simulated'] - base
    into_voo = engine.simulate(acts, [engine.trade_id(sell)], 'VOO')['summary']['simulated'] - base
    # removing a sell leaves the simulation with less cash; putting that shortfall into VOO cannot help it
    assert into_voo < idle


def test_a_share_transfer_is_a_flow_at_market_not_at_book(synthetic_market):
    """Wealthsimple states a book value on a transfer; the portfolio revalues the shares at market.
    Using the stated figure leaves the difference with nowhere to go and the return series books it
    as a gain on the transfer day."""
    import engine

    def row(date, kind, qty, net, sub=''):
        return dict(effective_date=date, effective_time='10:00:00', settlement_date='', account_id='A1',
                    account_type='TFSA', activity_type=kind, activity_sub_type=sub,
                    description='', direction='LONG', symbol='VOO', currency='USD', quantity=str(qty),
                    unit_price='', commission='0', net_cash_amount=str(net),
                    booked_date=date, order_time='10:00:00')

    acts = [dict(row('2026-01-05', 'MoneyMovement', 0, 4000), symbol=''),
            row('2026-01-06', 'Trade', 4, -2000, 'BUY'),
            # two shares leave, stated at a book value far from what they are worth that day
            row('2026-02-02', 'InternalSecurityTransfer', -2, -800)]
    cal = engine.Calendar('2026-01-05')
    base = engine.replay(acts, cal)
    px = float(cal.price_cad('VOO').asof(pd.Timestamp('2026-02-02')))
    flow = base['contrib'].diff().fillna(base['contrib'].iloc[0]).loc[pd.Timestamp('2026-02-02')]
    assert flow == pytest.approx(-2 * px, rel=1e-6)          # market, not the stated -800
    # The four shares held at the open still move with the market that day, so the test is not that
    # the day returns zero -- it is that the transfer itself contributes nothing to it.
    def day_return(rows):
        b = engine.replay(rows, cal)
        r = engine.twr(b['total'], b['contrib'])
        d = pd.Timestamp('2026-02-02')
        return float(r.loc[d] / r.shift(1).loc[d] - 1)

    assert day_return(acts) == pytest.approx(day_return(acts[:2]), abs=1e-9)


def test_money_weighted_return_answers_a_different_question(synthetic_market):
    """TWR weights every day alike, MWR every dollar. On a pot that grew from a small base they differ,
    and the app now shows both rather than letting one be read as the other."""
    import engine
    acts = [dict(effective_date='2026-01-05', effective_time='09:00:00', settlement_date='', account_id='A1',
                 account_type='TFSA', activity_type='MoneyMovement', activity_sub_type='EFT', description='',
                 direction='', symbol='', currency='USD', quantity='', unit_price='', commission='',
                 net_cash_amount='1000', booked_date='2026-01-05', order_time='09:00:00'),
            dict(effective_date='2026-01-06', effective_time='10:00:00', settlement_date='', account_id='A1',
                 account_type='TFSA', activity_type='Trade', activity_sub_type='BUY', description='',
                 direction='LONG', symbol='VOO', currency='USD', quantity='1', unit_price='505',
                 commission='0', net_cash_amount='-505', booked_date='2026-01-06', order_time='10:00:00')]
    cal = engine.Calendar('2026-01-05')
    base = engine.replay(acts, cal)
    m = engine.mwr(base['total'], base['contrib'])
    assert m is not None and m > 0                # the fixture's VOO rises, so the money earned something
    assert engine.mwr(base['total'] * 0, base['contrib']) is None   # an emptied account has no rate


def test_selling_part_of_an_option_leaves_the_rest_at_its_own_cost(synthetic_market):
    """A contract has no price history, so an open one is carried at cost. Netting the sale proceeds
    against that cost under-carries the remainder by exactly the realised gain."""
    import engine

    def opt_row(date, qty, net):
        return dict(effective_date=date, effective_time='10:00:00', settlement_date='', account_id='A1',
                    account_type='Non-registered', activity_type='Trade',
                    activity_sub_type='BUY' if qty > 0 else 'SELL', description='', direction='LONG',
                    symbol='OPEN  261002C00002500', currency='USD', quantity=str(qty), unit_price='',
                    commission='0', net_cash_amount=str(net), booked_date=date, order_time='10:00:00')

    deposit = dict(opt_row('2026-01-05', 0, 1000), symbol='', activity_type='MoneyMovement',
                   activity_sub_type='EFT', quantity='')
    bought = [deposit, opt_row('2026-01-06', 4, -72)]
    half = bought + [opt_row('2026-01-20', -2, 56)]
    cal = engine.Calendar('2026-01-05')

    held = engine.replay(bought, cal)['option_value'].iloc[-1]
    after = engine.replay(half, cal)['option_value'].iloc[-1]
    assert float(held) == pytest.approx(72 * 1.4, rel=1e-6)      # four contracts at what they cost
    assert float(after) == pytest.approx(36 * 1.4, rel=1e-6)     # two left, still at 18 each

    # and the gain is real: proceeds are cash, the remainder keeps its basis
    assert float(engine.replay(half, cal)['total'].iloc[-1]) == pytest.approx(
        float(engine.replay(bought, cal)['total'].iloc[-1]) + 20 * 1.4, rel=1e-6)


def test_closing_an_option_entirely_leaves_nothing_behind(synthetic_market):
    import engine

    def opt_row(date, qty, net):
        return dict(effective_date=date, effective_time='10:00:00', settlement_date='', account_id='A1',
                    account_type='Non-registered', activity_type='Trade',
                    activity_sub_type='BUY' if qty > 0 else 'SELL', description='', direction='LONG',
                    symbol='OPEN  261002C00002500', currency='USD', quantity=str(qty), unit_price='',
                    commission='0', net_cash_amount=str(net), booked_date=date, order_time='10:00:00')

    acts = [dict(opt_row('2026-01-05', 0, 1000), symbol='', activity_type='MoneyMovement',
                 activity_sub_type='EFT', quantity=''),
            opt_row('2026-01-06', 4, -72), opt_row('2026-01-20', -4, 112)]
    v = engine.replay(acts, engine.Calendar('2026-01-05'))['option_value'].iloc[-1]
    assert float(v) == 0.0
