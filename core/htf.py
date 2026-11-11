"""
Higher-timeframe trend for every signal, so trades can be kept in the direction of the
bigger picture.

Each signal timeframe has a parent and (where there is one) a grandparent timeframe -
`htf.ladder` in config.yaml, e.g. 60m -> 4hr -> 1D. A bar's trend comes from the EMAs
already stored in stock.csv:

    BULLISH  close > slow EMA and fast EMA > slow EMA
    BEARISH  close < slow EMA and fast EMA < slow EMA
    NEUTRAL  anything else            UNKNOWN  no bar / EMA not available yet

No look-ahead: a signal reads the higher-timeframe bar BEFORE the one its own bar falls
in. That bar is always finished when the signal bar closes.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

BULLISH, BEARISH, NEUTRAL, UNKNOWN = "BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"
ALIGNED, MIXED, AGAINST = "ALIGNED", "MIXED", "AGAINST"
ALIGNMENTS = (ALIGNED, MIXED, AGAINST, UNKNOWN)
TREND_COLS = ("htf1_trend", "htf2_trend")          # parent, grandparent
COLUMNS = ("alignment", *TREND_COLS)


def bar_trend(close: pd.Series, fast: pd.Series, slow: pd.Series) -> pd.Series:
    """Trend of each bar from its close and two EMAs."""
    out = pd.Series(NEUTRAL, index=close.index, dtype="object")
    out[(close > slow) & (fast > slow)] = BULLISH
    out[(close < slow) & (fast < slow)] = BEARISH
    out[close.isna() | fast.isna() | slow.isna()] = UNKNOWN
    return out


def completed_trend(df: pd.DataFrame, time_frame: str, fast_col: str, slow_col: str) -> pd.DataFrame:
    """
    Ticker, time, trend for one timeframe, where `trend` is the trend of the PREVIOUS bar:
    whoever looks up the bar that is forming at some moment gets the last finished one.
    """
    bars = df.loc[df["time_frame"] == time_frame, ["Ticker", "time", "Close", fast_col, slow_col]]
    bars = bars.sort_values(["Ticker", "time"])
    trend = bar_trend(bars["Close"], bars[fast_col], bars[slow_col])
    return pd.DataFrame({"Ticker": bars["Ticker"], "time": bars["time"],
                         "trend": trend.groupby(bars["Ticker"]).shift(1)})


def _lookup(signals: pd.DataFrame, table: pd.DataFrame) -> np.ndarray:
    """Trend of the last finished higher-timeframe bar for each signal (signal order kept)."""
    left = pd.DataFrame({"Ticker": signals["Ticker"].to_numpy(),
                         "at": signals["signal_time"].to_numpy().astype("datetime64[ns]"),
                         "_row": np.arange(len(signals))}).sort_values("at")
    right = table.assign(time=table["time"].to_numpy().astype("datetime64[ns]")).sort_values("time")
    hit = pd.merge_asof(left, right, left_on="at", right_on="time", by="Ticker")
    return hit.sort_values("_row")["trend"].fillna(UNKNOWN).to_numpy(dtype="object")


def alignment(side: Any, trends: Sequence[Any]) -> str:
    """
    ALIGNED  every known higher timeframe points the way of the trade
    AGAINST  the parent timeframe points the other way
    MIXED    anything in between (a neutral parent, or parent and grandparent disagree)
    UNKNOWN  no parent timeframe, or no trend for it yet
    """
    want = BULLISH if side == "LONG" else BEARISH if side == "SHORT" else None
    trends = [t for t in trends if isinstance(t, str) and t]
    if want is None or not trends or trends[0] == UNKNOWN:
        return UNKNOWN
    if trends[0] not in (want, NEUTRAL):
        return AGAINST
    return ALIGNED if all(t == want for t in trends if t != UNKNOWN) else MIXED


def attach_alignment(res: pd.DataFrame, df: pd.DataFrame, side_col: str, htf_cfg: dict) -> pd.DataFrame:
    """Add htf1_trend (parent), htf2_trend (grandparent) and alignment to signal rows."""
    out = res.copy()
    for col in TREND_COLS:
        out[col] = pd.Series([None] * len(out), index=out.index, dtype="object")
    if out.empty:
        out["alignment"] = pd.Series(dtype="object")
        return out
    tables: dict[str, pd.DataFrame] = {}
    for tf, idx in out.groupby("time_frame").groups.items():
        for col, parent in zip(TREND_COLS, htf_cfg["ladder"].get(tf, [])):
            if parent not in tables:
                tables[parent] = completed_trend(df, parent, htf_cfg["ema_fast"], htf_cfg["ema_slow"])
            out.loc[idx, col] = _lookup(out.loc[idx], tables[parent])
    out["alignment"] = [alignment(side, trends)
                        for side, *trends in zip(out[side_col], *(out[c] for c in TREND_COLS))]
    return out
