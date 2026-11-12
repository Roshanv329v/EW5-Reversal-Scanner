"""The TA-Lib stand-in used on Android must give TA-Lib's numbers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import ta_lite
from tests.conftest import make_engine_df

talib = pytest.importorskip("talib")


def _series() -> list[pd.DataFrame]:
    walk = make_engine_df(tickers=("AAA.NS", "BBB.NS"), n=600)
    flat = walk[walk["Ticker"] == "AAA.NS"].copy()
    flat.iloc[:40, flat.columns.get_indexer(["Open", "High", "Low", "Close"])] = 100.0   # no movement
    gap = walk[walk["Ticker"] == "BBB.NS"].copy()
    gap.iloc[:25, gap.columns.get_indexer(["Close"])] = np.nan                           # leading NaNs
    return [g for _, g in walk.groupby("Ticker")] + [flat, gap]


@pytest.mark.parametrize("name, args", [
    ("RSI", ("Close", 14)), ("RSI", ("Close", 13)), ("SMA", ("Close", 14)), ("SMA", ("Close", 5)),
    ("EMA", ("Close", 13)), ("EMA", ("Close", 55)),
    ("ATR", ("High", "Low", "Close", 14)), ("CCI", ("High", "Low", "Close", 14)),
])
def test_matches_talib(name, args):
    for g in _series():
        cols, period = args[:-1], args[-1]
        if name == "ATR" or name == "CCI":
            g = g.dropna(subset=["Close"])
        want = getattr(talib, name)(*(g[c] for c in cols), period)
        got = getattr(ta_lite, name)(*(g[c] for c in cols), period)
        assert isinstance(got, pd.Series) and got.index.equals(g.index)
        np.testing.assert_allclose(got.to_numpy(), np.asarray(want), rtol=1e-9, atol=1e-9, equal_nan=True)


def test_sma_of_a_series_with_leading_nans_matches_talib():
    rsi = talib.RSI(make_engine_df(tickers=("AAA.NS",), n=300)["Close"], 13)
    np.testing.assert_allclose(ta_lite.SMA(rsi, 5), talib.SMA(rsi, 5), rtol=1e-9, equal_nan=True)
