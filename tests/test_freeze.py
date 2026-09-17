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
