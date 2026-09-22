import datetime as dt

import market_data as m

NY = m.NY


def at(y, mo, d, hh, mm):
    return dt.datetime(y, mo, d, hh, mm, tzinfo=NY)


def test_active_ticker_waits_for_next_close():
    checked = at(2026, 9, 16, 17, 0).isoformat()  # Wed after close
    st = dict(checked=checked, last='2026-09-16')
    assert not m.needs_fetch('VOO', st, at(2026, 9, 17, 12, 0), active=True, force=False)  # Thu midday
    assert m.needs_fetch('VOO', st, at(2026, 9, 17, 17, 0), active=True, force=False)  # Thu after close


def test_weekend_has_no_new_session():
    st = dict(checked=at(2026, 9, 18, 17, 0).isoformat(), last='2026-09-18')  # Fri after close
    assert not m.needs_fetch('VOO', st, at(2026, 9, 20, 12, 0), active=True, force=False)


def test_closed_positions_refresh_weekly_or_on_their_weekday():
    ticker = 'ZZZ'
    stagger = sum(map(ord, ticker)) % 5
    base = at(2026, 9, 14, 17, 0)  # Monday
    st = dict(checked=base.isoformat(), last='2026-09-14')
    days = [d for d in range(1, 5) if m.needs_fetch(ticker, st, base + dt.timedelta(days=d), active=False, force=False)]
    assert days == ([stagger] if stagger > 0 else [])
    assert m.needs_fetch(ticker, st, base + dt.timedelta(days=8), active=False, force=False)


def test_force_always_fetches():
    st = dict(checked=dt.datetime.now(dt.timezone.utc).isoformat(), last='2026-09-16')
    assert m.needs_fetch('VOO', st, dt.datetime.now(dt.timezone.utc), active=True, force=True)


def test_ticker_map_handles_symbols_that_already_carry_an_exchange():
    # Wealthsimple writes some TSX symbols qualified (RY.TO) and some bare (XEQT); both must map cleanly.
    assert m.yahoo_ticker('RY.TO', 'CAD', 'RY.TO - Royal Bank of Canada: Bought', 'Non-registered') == 'RY.TO'
    assert m.yahoo_ticker('GOOG', 'CAD', 'GOOG - Alphabet CDR (CAD Hedged)', 'TFSA') == 'GOOG.NE'
    assert m.yahoo_ticker('NVDA', 'USD', 'NVDA - NVIDIA Corp', 'TFSA') == 'NVDA'
    assert m.yahoo_ticker('BTC', 'CAD', 'Purchase of BTC', 'Crypto') == 'BTC-CAD'
    acts = [dict(activity_type='Trade', symbol='RY.TO', currency='CAD', description='RY.TO - Royal Bank of Canada', account_type='Non-registered'),
            dict(activity_type='Trade', symbol='XEQT', currency='CAD', description='XEQT - iShares Core Equity ETF Portfolio', account_type='TFSA')]
    assert m.build_ticker_map(acts) == {('RY.TO', 'CAD'): 'RY.TO', ('XEQT', 'CAD'): 'XEQT.TO'}


def test_activity_only_universe_marks_reconstructed_positions_held(fixture_bytes):
    import store
    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    _acts, tmap, held, tickers, active = m.load_universe()
    assert tmap[('VOO', 'USD')] == 'VOO'
    assert 'VOO' in held and 'VOO' in tickers and 'VOO' in active


def test_price_rows_without_a_close_are_dropped(tmp_path):
    """Yahoo publishes today's row before the session has a close; a NaN close must never reach the build."""
    import pandas as pd
    rows = pd.DataFrame({'Date': pd.to_datetime(['2026-09-16', '2026-09-17']), 'Open': [1.0, 2.0], 'High': [1.0, 2.0],
                         'Low': [1.0, 2.0], 'Close': [1.0, float('nan')], 'Adj Close': [1.0, float('nan')],
                         'Volume': [1, 0], 'Dividends': [0.0, 0.0], 'Stock Splits': [0.0, 0.0]})
    kept = rows[rows['Close'].notna()]
    assert len(kept) == 1 and kept['Date'].iloc[-1].date().isoformat() == '2026-09-16'


def test_hourly_never_refetches_inside_the_bar():
    st = dict(hourly_checked=at(2026, 9, 17, 11, 0).isoformat())
    assert not m.hourly_due('VOO', st, at(2026, 9, 17, 11, 30), force=False)   # same 60-minute bar
    assert m.hourly_due('VOO', st, at(2026, 9, 17, 12, 30), force=False)       # next one, session open


def test_hourly_stops_once_the_session_has_settled():
    st = dict(hourly_checked=at(2026, 9, 17, 17, 0).isoformat())               # Thu, after the close
    assert not m.hourly_due('VOO', st, at(2026, 9, 17, 22, 0), force=False)
    assert not m.hourly_due('VOO', st, at(2026, 9, 18, 8, 0), force=False)     # Fri pre-market
    assert m.hourly_due('VOO', st, at(2026, 9, 18, 10, 0), force=False)        # Fri, printing again
    assert m.hourly_due('BTC-CAD', st, at(2026, 9, 17, 22, 0), force=False)    # crypto never closes


def test_hourly_universe_keeps_recently_traded_names():
    tmap = {('NVDA', 'USD'): 'NVDA', ('OLD', 'USD'): 'OLD'}
    recent = dt.date.today() - dt.timedelta(days=3)
    stale = dt.date.today() - dt.timedelta(days=m.HOURLY_TRADED_DAYS + 5)
    acts = [dict(activity_type='Trade', symbol='NVDA', currency='USD', effective_date=recent.isoformat()),
            dict(activity_type='Trade', symbol='OLD', currency='USD', effective_date=stale.isoformat())]
    assert m.hourly_tickers(acts, tmap, {'VOO'}) == {'VOO', 'NVDA'}


def _bars(dates, close):
    import pandas as pd
    return pd.DataFrame({'Date': pd.to_datetime(dates), 'Open': close, 'High': close,
                         'Low': close, 'Close': close, 'Adj Close': close, 'Volume': 100})


def test_a_clean_overlap_appends_only_the_new_tail(tmp_path):
    """The five-day rewind corrects nothing most days; rewriting five hundred rows to add one is waste."""
    import pandas as pd
    path = str(tmp_path / 'VOO.csv')
    old = _bars(['2026-01-05', '2026-01-06', '2026-01-07'], [100.0, 101.0, 102.0])
    old.to_csv(path, index=False, float_format='%.6f')
    before = open(path).read()

    new = _bars(['2026-01-06', '2026-01-07', '2026-01-08'], [101.0, 102.0, 103.0])
    assert m.write_bars(path, old, new) == 'append'

    after = pd.read_csv(path, parse_dates=['Date'])
    assert len(after) == 4                                  # no duplicated overlap
    assert list(after['Close']) == [100.0, 101.0, 102.0, 103.0]
    assert open(path).read().startswith(before)             # the old bytes were never rewritten


def test_a_restated_overlap_rewrites_the_file(tmp_path):
    """A split back-adjusts history. That has to reach a file already on disk."""
    import pandas as pd
    path = str(tmp_path / 'VOO.csv')
    old = _bars(['2026-01-05', '2026-01-06', '2026-01-07'], [100.0, 101.0, 102.0])
    old.to_csv(path, index=False, float_format='%.6f')

    halved = _bars(['2026-01-06', '2026-01-07', '2026-01-08'], [50.5, 51.0, 51.5])
    assert m.write_bars(path, old, halved) == 'rewrite'
    after = pd.read_csv(path, parse_dates=['Date'])
    assert list(after['Close']) == [100.0, 50.5, 51.0, 51.5]   # the correction landed


def test_nothing_new_writes_nothing(tmp_path):
    path = str(tmp_path / 'VOO.csv')
    old = _bars(['2026-01-05', '2026-01-06'], [100.0, 101.0])
    old.to_csv(path, index=False, float_format='%.6f')
    before = open(path).read()
    assert m.write_bars(path, old, _bars(['2026-01-05', '2026-01-06'], [100.0, 101.0])) == 'unchanged'
    assert open(path).read() == before


def test_appended_rows_render_like_the_file_they_join(tmp_path):
    """Volume arrives as an int and an older file holds it as a float. A file with two spellings of
    one column is the kind of thing the next comparison trips over."""
    import pandas as pd
    path = str(tmp_path / 'VOO.csv')
    old = _bars(['2026-01-05', '2026-01-06'], [100.0, 101.0])
    old['Volume'] = old['Volume'].astype(float)
    old.to_csv(path, index=False, float_format='%.6f')

    new = _bars(['2026-01-06', '2026-01-07'], [101.0, 102.0])
    new['Volume'] = new['Volume'].astype('int64')            # as the API delivers it
    reread = pd.read_csv(path, parse_dates=['Date'])
    assert m.write_bars(path, reread, new) == 'append'

    lines = open(path).read().strip().splitlines()
    vols = [l.split(',')[6] for l in lines[1:]]
    assert len(set(v.count('.') for v in vols)) == 1          # one spelling throughout


def test_a_batch_splits_into_one_frame_per_ticker(monkeypatch):
    """One request carries many tickers; a name the response omits must be skipped, not written empty."""
    import pandas as pd
    idx = pd.to_datetime(['2026-01-05', '2026-01-06'])
    frame = pd.concat({'VOO': pd.DataFrame({'Close': [1.0, 2.0]}, index=idx),
                       'QQQ': pd.DataFrame({'Close': [3.0, 4.0]}, index=idx)}, axis=1)
    monkeypatch.setattr(m.yf, 'download', lambda *a, **k: frame)
    budget = m.Budget()
    out = m._batch(['VOO', 'QQQ', 'NOPE'], '2026-01-01', budget, 'prices')
    assert set(out) == {'VOO', 'QQQ'}                         # NOPE is absent, not empty
    assert budget.requests == 1                               # three tickers, one call
