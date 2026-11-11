"""
Runs a screener / backtest and stores the results: one CSV per run plus a JSON with
the parameters used. Two strategies share this runner:

    ew5 - wave 5 reversal            (elliott_wave5_screener.py, unchanged)
    ew3 - wave 2 finished / wave 3   (elliott_wave3_screener.py)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew
from core import htf

MODES = {"live": "Live screen", "asof": "Point-in-time (as-of date)", "backtest": "Walk-forward backtest"}
HI_SOURCES = ("high", "close", "max open/close")
LO_SOURCES = ("low", "close", "min open/close")
TARGETS = ("W4_END", "FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854")
LEVEL_COLS = {"ew5": "reversal_levels", "ew3": "wave_levels"}        # list column per strategy
LEVEL_NAMES = {"ew5": ew.LEVEL_NAMES, "ew3": ew3.LEVEL_NAMES}
SIDE_COLS = {"ew5": "reversal_side", "ew3": "trade_side"}
FILE_PREFIX = {"ew5": "", "ew3": "ew3_"}                              # EW5 keeps its file names


@dataclass(frozen=True)
class RunParams:
    mode: str                                   # live | asof | backtest
    timeframes: tuple[str, ...]
    lengths: tuple[int, ...]
    stages: tuple[str, ...]
    horizon_bars: int
    max_bars_since_w5: Optional[int] = None
    min_w5_vs_w1: float = 0.0
    resignal_on_extension: bool = False
    pivot_tie: str = "strict"
    hi_source: str = "high"
    lo_source: str = "low"
    min_bars: int = 120
    as_of: Optional[str] = None                 # YYYY-MM-DD (asof mode)
    start: Optional[str] = None                 # YYYY-MM-DD (backtest mode)
    end: Optional[str] = None
    # --- strategy. For ew3, `max_bars_since_w5` means bars since the wave-2 pivot and
    #     `resignal_on_extension` means "signal again when the wave-2 pivot moves".
    strategy: str = "ew5"
    contexts: tuple[str, ...] = ew3.DEFAULT_CONTEXTS                  # ew3 only
    min_retrace: float = ew3.DEFAULT_MIN_RETRACE                      # ew3 only
    max_retrace: float = ew3.DEFAULT_MAX_RETRACE                      # ew3 only
    aligned_only: bool = False                  # keep only signals ALIGNED with the higher timeframes

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RunParams":
        d = json.loads(text)
        for key in ("timeframes", "lengths", "stages", "contexts"):
            if key in d:
                d[key] = tuple(d[key])
        return cls(**d)


def end_of_day(date: Any) -> pd.Timestamp:
    """
    Last second of a calendar day. An as-of / end DATE means "after that day's close":
    the daily bar (stamped 00:00) and both 4H bars (09:15, 13:15) of that day are all
    included, so the two timeframes see the same amount of information.
    """
    return pd.Timestamp(date).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)


# ----------------------------------------------------------------------------------
# Engine calls
# ----------------------------------------------------------------------------------
def run_engine(df: pd.DataFrame, p: RunParams, indicator_cols: Sequence[str] = (),
               htf_cfg: Optional[dict] = None) -> pd.DataFrame:
    """
    Run one of the three modes on stock data and return the result with level columns.
    `indicator_cols` from stock.csv are copied in at the signal bar (display only - the
    engine itself never sees them). With `htf_cfg` (config.yaml `htf`), every signal also
    gets the trend of its higher timeframes and an `alignment` column (core/htf.py).
    """
    res = _run_screener(df[df["time_frame"].isin(p.timeframes)], p, indicator_cols)
    if htf_cfg is None:
        return res
    res = htf.attach_alignment(res, df, SIDE_COLS[p.strategy], htf_cfg)
    if p.aligned_only:
        res = res[res["alignment"].eq(htf.ALIGNED)].reset_index(drop=True)
    return res


def _run_screener(data: pd.DataFrame, p: RunParams, indicator_cols: Sequence[str]) -> pd.DataFrame:
    if p.strategy == "ew3":
        return attach_indicators(explode_levels(_run_ew3(data, p), ew3.LEVEL_NAMES, LEVEL_COLS["ew3"]),
                                 data, indicator_cols)
    common = dict(lengths=p.lengths, stages=p.stages, max_bars_since_w5=p.max_bars_since_w5,
                  min_w5_vs_w1=p.min_w5_vs_w1, hi_source=p.hi_source, lo_source=p.lo_source,
                  pivot_tie=p.pivot_tie, min_bars=p.min_bars)
    if p.mode == "live":
        res = ew.screen_wave5(data, **common)
    elif p.mode == "asof":
        res = ew.screen_wave5(data, as_of=end_of_day(p.as_of), **common)
        if not res.empty:
            res = ew.evaluate_signals(res, data, p.horizon_bars)
    elif p.mode == "backtest":
        res = ew.backtest_wave5(data,
                                start=pd.Timestamp(p.start) if p.start else None,
                                end=end_of_day(p.end) if p.end else None,
                                horizon_bars=p.horizon_bars,
                                resignal_on_extension=p.resignal_on_extension, **common)
    else:
        raise ValueError(f"Unknown mode: {p.mode}")
    return attach_indicators(explode_levels(res), data, indicator_cols)


def _run_ew3(data: pd.DataFrame, p: RunParams) -> pd.DataFrame:
    common = dict(lengths=p.lengths, stages=p.stages, contexts=p.contexts, min_retrace=p.min_retrace,
                  max_retrace=p.max_retrace, max_bars_since_w2=p.max_bars_since_w5,
                  hi_source=p.hi_source, lo_source=p.lo_source, pivot_tie=p.pivot_tie, min_bars=p.min_bars)
    if p.mode == "live":
        return ew3.screen_wave3(data, **common)
    if p.mode == "asof":
        res = ew3.screen_wave3(data, as_of=end_of_day(p.as_of), **common)
        return ew3.evaluate_signals(res, data, p.horizon_bars) if not res.empty else res
    if p.mode == "backtest":
        return ew3.backtest_wave3(data, start=pd.Timestamp(p.start) if p.start else None,
                                  end=end_of_day(p.end) if p.end else None, horizon_bars=p.horizon_bars,
                                  resignal_on_new_w2=p.resignal_on_extension, **common)
    raise ValueError(f"Unknown mode: {p.mode}")


def attach_indicators(res: pd.DataFrame, df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Add the stock.csv indicator values of each signal's own bar (Ticker, time_frame, signal_time)."""
    cols = [c for c in columns if c in df.columns and c not in res.columns]
    if res.empty or not cols:
        return res
    keys = ["Ticker", "time_frame", "signal_time"]
    look = df[["Ticker", "time_frame", "time", *cols]].rename(columns={"time": "signal_time"})
    look = look.drop_duplicates(keys, keep="last")
    look["signal_time"] = look["signal_time"].astype(res["signal_time"].dtype)
    return res.merge(look, on=keys, how="left")


def explode_levels(res: pd.DataFrame, level_names: Sequence[str] = ew.LEVEL_NAMES,
                   col: str = "reversal_levels") -> pd.DataFrame:
    """Add one float column per level name; the list column (`col`) is kept."""
    out = res.copy()
    parsed = [dict(item.split("=", 1) for item in levels) for levels in out[col]]
    for name in level_names:
        out[name] = pd.Series([float(d[name]) if name in d else np.nan for d in parsed],
                              index=out.index, dtype="float64")
    return out


def has_outcomes(res: pd.DataFrame) -> bool:
    return "status" in res.columns


def summarize(res: pd.DataFrame, strategy: str = "ew5") -> pd.DataFrame:
    """summarize_backtest() for results that carry outcome columns, else an empty frame."""
    if res.empty or not has_outcomes(res):
        return pd.DataFrame()
    return (ew3 if strategy == "ew3" else ew).summarize_backtest(res)


def check_min_bars(df: pd.DataFrame, cutoff: Any, min_bars: int,
                   timeframes: Sequence[str]) -> pd.DataFrame:
    """Ticker/timeframe pairs with fewer than `min_bars` bars at or before `cutoff`."""
    data = df[df["time_frame"].isin(timeframes)]
    pairs = data[["Ticker", "time_frame"]].drop_duplicates()
    before = data[data["time"] <= pd.Timestamp(cutoff)]
    counts = before.groupby(["Ticker", "time_frame"]).size().rename("bars_before").reset_index()
    out = pairs.merge(counts, on=["Ticker", "time_frame"], how="left").fillna({"bars_before": 0})
    out["bars_before"] = out["bars_before"].astype(int)
    return out[out["bars_before"] < min_bars].sort_values(["time_frame", "Ticker"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------
# KPIs for the dashboard
# ----------------------------------------------------------------------------------
def _pct(num: float, den: float) -> float:
    return float(num) / float(den) * 100 if den else float("nan")


def kpis(res: pd.DataFrame) -> dict[str, float]:
    """Headline numbers for evaluated results. Hit / stop rates are out of triggered signals."""
    n = len(res)
    trig = res[res["status"].eq("TRIGGERED")]
    return {
        "signals": n,
        "trigger_rate": _pct(len(trig), n),
        "extended_pct": _pct(res["status"].eq("EXTENDED").sum(), n),
        "w4_hit_rate": _pct(trig["hit_W4_END"].sum(), len(trig)),
        "fib50_hit_rate": _pct(trig["hit_FIB_0.500"].sum(), len(trig)),
        "stop_rate": _pct(trig["stopped"].sum(), len(trig)),
        "avg_mfe": float(trig["mfe_pct"].mean()) if len(trig) else float("nan"),
        "avg_mae": float(trig["mae_pct"].mean()) if len(trig) else float("nan"),
    }


def stat_masks(res: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Row masks behind each dashboard stat card, so a card can filter the signal table:
    triggered / extended, and (of the triggered ones) W4 hit, FIB 0.5 hit, stopped,
    MFE at or above the average, MAE at or below the average.
    """
    trig = res["status"].eq("TRIGGERED")
    avg_mfe, avg_mae = res.loc[trig, "mfe_pct"].mean(), res.loc[trig, "mae_pct"].mean()
    return {
        "triggered": trig,
        "extended": res["status"].eq("EXTENDED"),
        "w4": trig & res["hit_W4_END"].astype(bool),
        "fib50": trig & res["hit_FIB_0.500"].astype(bool),
        "stopped": trig & res["stopped"].astype(bool),
        "mfe": trig & (res["mfe_pct"] >= avg_mfe),
        "mae": trig & (res["mae_pct"] <= avg_mae),
    }


def bar_mask(res: pd.DataFrame, by: str, bars: Sequence[Sequence[Any]]) -> pd.Series:
    """Rows behind clicked breakdown bars; each bar = [time_frame, degree, value of `by`]."""
    mask = pd.Series(False, index=res.index)
    for tf, degree, value in bars:
        mask |= res["time_frame"].eq(tf) & res["degree"].eq(degree) & res[by].eq(value)
    return mask


def range_mask(res: pd.DataFrame, bars: Sequence[Sequence[Any]]) -> pd.Series:
    """Triggered rows behind clicked MFE / MAE histogram bars; each bar = [column, low, high]."""
    mask = pd.Series(False, index=res.index)
    for column, low, high in bars:
        mask |= res[column].between(float(low), float(high))
    return mask & res["status"].eq("TRIGGERED")


# ----------------------------------------------------------------------------------
# Results files
# ----------------------------------------------------------------------------------
def save_results(res: pd.DataFrame, p: RunParams, results_dir: Path,
                 stock_csv: Optional[Path] = None, stamp: Optional[str] = None) -> Path:
    """Write results/[ew3_]<mode>_<YYYYmmdd_HHMMSS>.csv and a .json with the parameters."""
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = results_dir / f"{FILE_PREFIX.get(p.strategy, '')}{p.mode}_{stamp}.csv"
    out = res.copy()
    col = LEVEL_COLS.get(p.strategy, "reversal_levels")
    out[col] = [json.dumps(list(v)) for v in out[col]]
    out.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
    meta = {"created": stamp, "rows": len(res), "stock_csv": str(stock_csv) if stock_csv else None,
            "params": asdict(p)}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return path


def strategy_of(path: Path) -> str:
    """Which strategy a results file belongs to (from its name)."""
    for key, prefix in FILE_PREFIX.items():
        if prefix and path.name.startswith(prefix):
            return key
    return "ew5"


def list_results(results_dir: Path, strategy: Optional[str] = None) -> list[Path]:
    """Result CSVs, newest first; optionally only those of one strategy."""
    if not results_dir.exists():
        return []
    files = sorted(results_dir.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [f for f in files if strategy is None or strategy_of(f) == strategy]


def load_results(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read a results CSV back (times parsed, levels as a list) with its parameters."""
    res = pd.read_csv(path)
    for col in res.columns:
        if col.endswith("_time"):
            res[col] = pd.to_datetime(res[col])
    for col in LEVEL_COLS.values():
        if col in res.columns:
            res[col] = [json.loads(v) for v in res[col]]
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return res, meta
