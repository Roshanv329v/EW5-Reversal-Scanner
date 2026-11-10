"""Shared test fixtures. Synthetic data is only ever created here, under tests/."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from core.config import load_config

IST = "Asia/Kolkata"


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    """Real config.yaml values, with every file path pointed at a temp folder."""
    c = load_config()
    c.update(stock_csv=tmp_path / "stock.csv", backups_dir=tmp_path / "backups",
             results_dir=tmp_path / "results", logs_dir=tmp_path / "logs",
             tickers_file=tmp_path / "tickers.csv", backoff_seconds=0)
    return c


def _walk(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))


def ohlc_from_close(close: np.ndarray, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1)
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.006, len(close))) * close
    return pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) + spread,
                         "Low": np.minimum(open_, close) - spread, "Close": close,
                         "Volume": 1000.0})


def make_engine_df(tickers=("AAA.NS", "BBB.NS"), n: int = 400) -> pd.DataFrame:
    """Random-walk daily bars in the stock.csv schema, for engine/runner tests."""
    frames = []
    for k, t in enumerate(tickers):
        df = ohlc_from_close(_walk(n, seed=10 + k), seed=k)
        df.insert(0, "time", pd.bdate_range("2023-01-02", periods=n))
        df.insert(0, "Ticker", t)
        df.insert(2, "time_frame", "1D")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


class FakeFetch:
    """
    Stand-in for the yfinance downloader. Serves deterministic bars from a fixed
    "market history": daily bars tz-naive, 1h bars tz-aware UTC (like yfinance).
    """

    def __init__(self, days: int = 60, end: str = "2026-03-13", fail: tuple[str, ...] = ()):
        self.dates = pd.bdate_range(end=end, periods=days)
        self.fail = set(fail)
        self.calls: list[tuple] = []
        self.bump = 0.0                     # added to every price: simulates revised bars

    def _daily(self, ticker: str) -> pd.DataFrame:
        seed = sum(map(ord, ticker))
        df = ohlc_from_close(_walk(len(self.dates), seed), seed) + self.bump
        df.index = self.dates
        return df

    def _hourly(self, ticker: str) -> pd.DataFrame:
        seed = sum(map(ord, ticker)) + 7
        stamps = [d + pd.Timedelta(hours=9 + h, minutes=15) for d in self.dates for h in range(7)]
        df = ohlc_from_close(_walk(len(stamps), seed), seed) + self.bump
        df.index = pd.DatetimeIndex(stamps).tz_localize(IST).tz_convert("UTC")
        return df

    def __call__(self, tickers: list[str], interval: str, period: Optional[str],
                 start: Optional[str]) -> dict[str, pd.DataFrame]:
        self.calls.append((tuple(tickers), interval, period, start))
        out = {}
        for t in tickers:
            if t in self.fail:
                continue
            df = self._daily(t) if interval == "1d" else self._hourly(t)
            if start is not None:
                cut = pd.Timestamp(start)
                df = df[df.index >= (cut.tz_localize(IST) if df.index.tz is not None else cut)]
            out[t] = df
        return out
