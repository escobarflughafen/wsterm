"""Read cached market data. Yahoo prices are split-adjusted; price_on() can undo that."""
import functools, os

import pandas as pd

from settings import MARKET_DIR

DATA = str(MARKET_DIR)


@functools.lru_cache(maxsize=None)
def history(ticker):
    df = pd.read_csv(os.path.join(DATA, 'prices', f'{ticker}.csv'), parse_dates=['Date'])
    return df.set_index('Date').sort_index()


@functools.lru_cache(maxsize=None)
def ticker_map():
    df = pd.read_csv(os.path.join(DATA, 'tickers.csv'), keep_default_na=False)
    return {(r.ws_symbol, r.currency): r.yahoo or None for r in df.itertuples()}


@functools.lru_cache(maxsize=None)
def fx_usdcad():
    df = pd.read_csv(os.path.join(DATA, 'fx_usdcad.csv'), parse_dates=['Date'])
    return df.set_index('Date')['USDCAD'].sort_index()


def split_factor_after(ticker, date):
    """Product of splits after `date`; multiply an adjusted price by this to get the as-traded price."""
    df = history(ticker)
    s = df.loc[df.index > pd.Timestamp(date), 'Stock Splits']
    return float(s[s > 0].prod()) if (s > 0).any() else 1.0


def price_on(ticker, date, field='Close', as_traded=True):
    """Last close on or before `date` (handles weekends/holidays)."""
    df = history(ticker)
    row = df.loc[:pd.Timestamp(date)].iloc[-1]
    return float(row[field]) * (split_factor_after(ticker, date) if as_traded else 1.0)


def latest(ticker):
    df = history(ticker)
    return df.index[-1].date(), float(df['Close'].iloc[-1])


def usdcad_on(date):
    return float(fx_usdcad().loc[:pd.Timestamp(date)].iloc[-1])
