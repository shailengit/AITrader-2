"""Cached per-ticker OHLCV access: one query per ticker, not per trade."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.price_panel import BARS_COLUMNS, PricePanel


def test_bars_has_expected_columns_and_dtypes():
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-03-01")
    assert list(df.columns) == BARS_COLUMNS
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])
    assert df["Date"].dt.tz is None          # naive dates, per package convention
    assert (df["Close"] > 0).all()
    assert df["Date"].is_monotonic_increasing


def test_repeated_bars_calls_hit_cache():
    p = PricePanel()
    p.bars("AAPL", "2020-01-01", "2021-01-01")
    n = p.query_count
    p.bars("AAPL", "2020-01-01", "2021-01-01")
    assert p.query_count == n


def test_missing_ticker_returns_empty_not_crash():
    p = PricePanel()
    df = p.bars("ZZZZNOTREAL", "2020-01-01", "2021-01-01")
    assert len(df) == 0
    assert list(df.columns) == BARS_COLUMNS


def test_next_open_returns_following_trading_day_open():
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-02-01")
    first, second = df.iloc[0], df.iloc[1]
    got = p.next_open("AAPL", first["Date"].strftime("%Y-%m-%d"))
    assert got == float(second["Open"])


def test_next_open_none_after_the_final_bar_in_history():
    """None only when no later bar exists at all -- not merely outside the slice."""
    p = PricePanel()
    df = p.bars("AAPL", "2000-01-01", "2030-01-01")
    last = df.iloc[-1]["Date"].strftime("%Y-%m-%d")
    assert p.next_open("AAPL", last) is None


def test_next_open_uses_full_history_not_the_requested_slice():
    """Deliberate: the adapter fills at the real next open, whatever window we sliced."""
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-02-01")
    last_in_slice = df.iloc[-1]["Date"].strftime("%Y-%m-%d")
    assert p.next_open("AAPL", last_in_slice) is not None


def test_dotted_ticker_uses_safe_table_name():
    """BRK.B -> table brk-b; must not raise."""
    p = PricePanel()
    out = p.bars("BRK.B", "2020-01-01", "2020-03-01")
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == BARS_COLUMNS
