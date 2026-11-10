"""
Incremental NSE data store.

Downloads Daily and 60m bars from yfinance, converts everything to timezone-naive
IST, builds 4hr bars from the 60m bars (stock_data.build_4h_from_hourly), merges into
one stock.csv and adds the indicators (stock_data.calculate_indicator_values):

    Ticker, time, time_frame, Open, High, Low, Close, Volume, <indicator columns>

Rows are unique on (Ticker, time_frame, time); the newest download wins. Indicators
are recomputed on the full merged history, so an incremental update never leaves an
EMA / RSI that was calculated on 30 days only.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

from stock_data import INDICATOR_COLS, build_4h_from_hourly, calculate_indicator_values

OHLC = ["Open", "High", "Low", "Close"]
BASE_SCHEMA = ["Ticker", "time", "time_frame", *OHLC, "Volume"]
SCHEMA = [*BASE_SCHEMA, *INDICATOR_COLS]
KEYS = ["Ticker", "time_frame", "time"]
TIME_FMT = "%Y-%m-%d %H:%M:%S"
YF_INTERVAL = {"1D": "1d", "4hr": "60m"}       # yfinance has no 4h: 60m is converted

log = logging.getLogger("ew_app.data")

# fetch(tickers, interval, period, start) -> {ticker: raw OHLCV frame}
FetchFn = Callable[[list[str], str, Optional[str], Optional[str]], dict[str, pd.DataFrame]]
ProgressFn = Callable[[int, int, str], None]


# ----------------------------------------------------------------------------------
# Tickers
# ----------------------------------------------------------------------------------
def clean_tickers(raw: Sequence[Any]) -> list[str]:
    """Strip blanks and duplicates. Symbols are NOT renamed: they must be yfinance symbols."""
    out: list[str] = []
    for item in raw:
        t = str(item).strip()
        if t and t.lower() != "nan" and t not in out:
            out.append(t)
    return out


def parse_ticker_text(text: str) -> list[str]:
    """Tickers pasted as text, separated by commas, spaces or new lines (used as written)."""
    return clean_tickers(re.split(r"[,\s;]+", text or ""))


def write_tickers(path: Path, tickers: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Ticker": list(tickers)}).to_csv(path, index=False)


# ----------------------------------------------------------------------------------
# Time handling and resampling
# ----------------------------------------------------------------------------------
def to_naive_ist(index: Any, tz: str) -> pd.DatetimeIndex:
    """Any datetime index -> timezone-naive wall-clock time in `tz` (naive input is kept)."""
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is not None:
        idx = idx.tz_convert(tz).tz_localize(None)
    return idx


def bars_4h(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    60m bars (naive IST index) -> 4hr bars via stock_data.build_4h_from_hourly:
    the first four 60m bars of a day form one bar, the remaining bars the second one.
    Each bar is labelled with the time of its first 60m bar (NSE: 09:15 and 13:15).
    """
    hourly = hourly.dropna(subset=OHLC)
    if hourly.empty:
        return hourly
    out = build_4h_from_hourly(hourly.rename_axis("Date").reset_index())
    return out.set_index("Date").rename_axis(None)


def empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in BASE_SCHEMA})
    df["Ticker"] = df["Ticker"].astype("object")
    df["time_frame"] = df["time_frame"].astype("object")
    df["time"] = pd.to_datetime(df["time"])
    return df


def to_schema(raw: Optional[pd.DataFrame], ticker: str, time_frame: str, cfg: dict) -> pd.DataFrame:
    """Raw yfinance-style OHLCV frame for one ticker -> rows in the stock.csv schema."""
    if raw is None or raw.empty:
        return empty_frame()
    df = raw.copy()
    df.columns = [str(c).strip().title() for c in df.columns]
    if any(c not in df.columns for c in OHLC):
        return empty_frame()
    df = df[[c for c in (*OHLC, "Volume") if c in df.columns]]
    df = df.apply(pd.to_numeric, errors="coerce").dropna(subset=OHLC)
    df.index = to_naive_ist(df.index, cfg["timezone"])

    if time_frame == "1D":
        df.index = df.index.normalize()
    elif time_frame == "4hr":
        df = bars_4h(df)
    else:
        raise ValueError(f"Unsupported time_frame: {time_frame}")

    df = df[~df.index.duplicated(keep="last")]
    df[OHLC] = df[OHLC].round(int(cfg["price_decimals"]))
    out = df.reset_index(names="time")
    out["Ticker"] = ticker
    out["time_frame"] = time_frame
    if "Volume" not in out.columns:
        out["Volume"] = np.nan
    return out[BASE_SCHEMA]


# ----------------------------------------------------------------------------------
# Merge / load / save
# ----------------------------------------------------------------------------------
def merge_stats(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Per time_frame: rows downloaded, added (new keys) and replaced (keys already stored)."""
    cols = ["time_frame", "downloaded", "added", "replaced"]
    new = new.drop_duplicates(KEYS, keep="last")
    if new.empty:
        return pd.DataFrame(columns=cols)
    seen = new[KEYS].merge(existing[KEYS].drop_duplicates(), on=KEYS, how="left", indicator=True)
    seen["replaced"] = seen["_merge"].eq("both")
    stats = (seen.groupby("time_frame")
                 .agg(downloaded=("replaced", "size"), replaced=("replaced", "sum"))
                 .reset_index())
    stats["added"] = stats["downloaded"] - stats["replaced"]
    return stats[cols]


def merge_bars(existing: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Append `new` to `existing`, keep the newest row per (Ticker, time_frame, time).

    Returns (merged, stats) where stats has one row per time_frame with the number of
    rows downloaded / added / replaced.
    """
    new = new.drop_duplicates(KEYS, keep="last")
    stats = merge_stats(existing, new)
    if new.empty:
        return _sorted(existing), stats

    frames = [f for f in (existing, new) if not f.empty]
    merged = pd.concat(frames, ignore_index=True).drop_duplicates(KEYS, keep="last")
    return _sorted(merged), stats


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(KEYS).reset_index(drop=True)[BASE_SCHEMA]


def add_indicators(df: pd.DataFrame, decimals: int = 4) -> pd.DataFrame:
    """
    Indicator columns for every (Ticker, time_frame) series, calculated on the whole
    stored history with stock_data.calculate_indicator_values.
    """
    if df.empty:
        return df.reindex(columns=SCHEMA)
    parts = []
    for _, g in df[BASE_SCHEMA].groupby(["Ticker", "time_frame"], sort=False):
        parts.append(calculate_indicator_values(g.rename(columns={"time": "Date"})))
    out = pd.concat(parts, ignore_index=True).rename(columns={"Date": "time"})
    out[INDICATOR_COLS] = out[INDICATOR_COLS].replace([np.inf, -np.inf], np.nan).round(decimals)
    return out.sort_values(KEYS).reset_index(drop=True)[SCHEMA]


def load_stock_csv(path: Path) -> pd.DataFrame:
    """stock.csv -> DataFrame with `time` parsed (empty frame if the file is missing)."""
    if not Path(path).exists():
        return empty_frame()
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], format=TIME_FMT)
    return df.reindex(columns=SCHEMA)


def save_stock_csv(df: pd.DataFrame, path: Path, backups_dir: Path, keep: int,
                   stamp: Optional[str] = None) -> None:
    """Back up the previous file (keep the last `keep`), write to a temp file, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, backups_dir / f"stock_{stamp}.csv")
        for old in sorted(backups_dir.glob("stock_*.csv"))[:-keep]:
            old.unlink()
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, date_format=TIME_FMT)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------------
def make_yf_fetch(auto_adjust: bool) -> FetchFn:
    """yfinance downloader: one yf.download call per batch of tickers."""

    def fetch(tickers: list[str], interval: str, period: Optional[str],
              start: Optional[str]) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        kwargs: dict[str, Any] = dict(interval=interval, group_by="ticker",
                                      auto_adjust=auto_adjust, progress=False, threads=True)
        if start is not None:
            kwargs["start"] = start
        else:
            kwargs["period"] = period
        raw = yf.download(tickers, **kwargs)
        out: dict[str, pd.DataFrame] = {}
        if raw is None or raw.empty:
            return out
        for t in tickers:
            if isinstance(raw.columns, pd.MultiIndex):
                if t in raw.columns.get_level_values(0):
                    sub = raw[t]
                elif t in raw.columns.get_level_values(1):
                    sub = raw.xs(t, axis=1, level=1)
                else:
                    continue
            else:
                sub = raw
            sub = sub.dropna(how="all")
            if not sub.empty:
                out[t] = sub
        return out

    return fetch


def _fetch_with_retries(fetch: FetchFn, tickers: list[str], interval: str, period: Optional[str],
                        start: Optional[str], retries: int, backoff: float,
                        say: Callable[[str], None]) -> dict[str, pd.DataFrame]:
    got: dict[str, pd.DataFrame] = {}
    missing = list(tickers)
    for attempt in range(1, retries + 1):
        try:
            got.update(fetch(missing, interval, period, start))
        except Exception as exc:  # network / yfinance errors: retry, never crash the update
            say(f"  attempt {attempt}/{retries} failed: {exc}")
        missing = [t for t in tickers if t not in got]
        if not missing:
            break
        if attempt < retries:
            say(f"  {len(missing)} ticker(s) without data, retrying ({attempt}/{retries})")
            _time.sleep(backoff * attempt)
    return got


@dataclass
class UpdateReport:
    stats: pd.DataFrame
    failed: dict[str, list[str]] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    rows_before: int = 0
    rows_after: int = 0
    saved: bool = False


def setup_logging(logs_dir: Path) -> None:
    """Send the data log to logs/data_update.log (idempotent)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    target = str(logs_dir / "data_update.log")
    if any(getattr(h, "baseFilename", None) == target for h in log.handlers):
        return
    handler = logging.FileHandler(target, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def update_data(cfg: dict, tickers: Sequence[str], timeframes: Sequence[str],
                incremental_days: int, full: bool = False,
                progress: Optional[ProgressFn] = None, fetch: Optional[FetchFn] = None,
                today: Optional[datetime] = None) -> UpdateReport:
    """
    Update stock.csv.

    Symbols are passed to yfinance exactly as given (no renaming).
    Per timeframe, a ticker gets the full history when it is new, when `full` is set,
    or when its newest stored bar is older than the incremental window (otherwise the
    update would leave a hole). Everything else gets the last `incremental_days`.
    With `full`, stored rows of every re-downloaded (ticker, timeframe) are discarded
    first, so split/bonus adjustments are picked up cleanly.
    """
    fetch = fetch or make_yf_fetch(bool(cfg["auto_adjust"]))
    today = today or datetime.now()
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(f"{datetime.now():%H:%M:%S} {msg}")
        log.info(msg)

    existing = load_stock_csv(cfg["stock_csv"])[BASE_SCHEMA]
    tickers = clean_tickers(tickers)
    inc_start = (today - timedelta(days=int(incremental_days))).strftime("%Y-%m-%d")
    last_bar = existing.groupby(["time_frame", "Ticker"])["time"].max() if not existing.empty else {}

    jobs: list[tuple[str, str, list[str]]] = []          # (time_frame, "full"/"incremental", batch)
    size = int(cfg["batch_size"])
    for tf in timeframes:
        need_full = [t for t in tickers
                     if full or (tf, t) not in last_bar or last_bar[(tf, t)] < pd.Timestamp(inc_start)]
        incremental = [t for t in tickers if t not in need_full]
        for kind, group in (("full", need_full), ("incremental", incremental)):
            jobs += [(tf, kind, group[i:i + size]) for i in range(0, len(group), size)]

    say(f"Update started: {len(tickers)} tickers, timeframes {list(timeframes)}, "
        f"{'FULL re-download' if full else f'incremental {incremental_days}d'}")

    new_frames: list[pd.DataFrame] = []
    failed: dict[str, list[str]] = {tf: [] for tf in timeframes}
    refreshed: list[tuple[str, str]] = []
    for n, (tf, kind, batch) in enumerate(jobs, start=1):
        if progress:
            progress(n - 1, len(jobs), f"{tf} · {kind} · {batch[0]} … ({len(batch)} tickers)")
        period, start = (cfg["full_history"][tf], None) if kind == "full" else (None, inc_start)
        if tf == "4hr":
            # 60m data only exists for ~730 days. A start date works for every ticker; a
            # `period` fails for stocks listed more recently than that.
            floor = (today - timedelta(days=int(cfg["intraday_max_days"]))).strftime("%Y-%m-%d")
            period, start = None, max(start or floor, floor)
        say(f"{tf} {kind}: {len(batch)} tickers ({period or 'from ' + str(start)})")
        got = _fetch_with_retries(fetch, batch, YF_INTERVAL[tf], period, start,
                                  int(cfg["retries"]), float(cfg["backoff_seconds"]), say)
        for t in batch:
            frame = to_schema(got.get(t), t, tf, cfg)
            if frame.empty:
                failed[tf].append(t)
            else:
                new_frames.append(frame)
                if kind == "full":
                    refreshed.append((t, tf))
    if progress:
        progress(len(jobs), len(jobs), "Merging and saving")

    new = pd.concat(new_frames, ignore_index=True) if new_frames else empty_frame()
    base = existing
    if full and refreshed and not existing.empty:
        drop = pd.MultiIndex.from_tuples(refreshed)
        base = existing[~pd.MultiIndex.from_frame(existing[["Ticker", "time_frame"]]).isin(drop)]
    merged, _ = merge_bars(base, new)
    stats = merge_stats(existing, new)

    saved = not new.empty
    if saved:
        say(f"Calculating indicators for {merged.groupby(['Ticker', 'time_frame']).ngroups} series")
        merged = add_indicators(merged, int(cfg["indicator_decimals"]))
        save_stock_csv(merged, cfg["stock_csv"], cfg["backups_dir"], int(cfg["backups_keep"]))
    for tf, bad in failed.items():
        if bad:
            say(f"{tf}: no data for {len(bad)} ticker(s): {', '.join(bad)}")
    say(f"Update finished: {len(existing)} -> {len(merged)} rows" + ("" if saved else " (nothing saved)"))
    return UpdateReport(stats=stats, failed={k: v for k, v in failed.items() if v}, log=lines,
                        rows_before=len(existing), rows_after=len(merged), saved=saved)


# ----------------------------------------------------------------------------------
# Summaries for the Data tab
# ----------------------------------------------------------------------------------
def timeframe_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Rows, tickers, first and last bar per timeframe."""
    if df.empty:
        return pd.DataFrame(columns=["time_frame", "rows", "tickers", "first_bar", "last_bar"])
    return (df.groupby("time_frame")
              .agg(rows=("time", "size"), tickers=("Ticker", "nunique"),
                   first_bar=("time", "min"), last_bar=("time", "max"))
              .reset_index())


def bars_per_ticker(df: pd.DataFrame, short_threshold: int) -> pd.DataFrame:
    """Bars per ticker and timeframe, with a `short_history` flag."""
    if df.empty:
        return pd.DataFrame(columns=["Ticker", "short_history"])
    counts = df.pivot_table(index="Ticker", columns="time_frame", values="time",
                            aggfunc="size", fill_value=0)
    counts.columns = [f"bars_{c}" for c in counts.columns]
    counts["short_history"] = (counts < short_threshold).any(axis=1)
    return counts.reset_index()
