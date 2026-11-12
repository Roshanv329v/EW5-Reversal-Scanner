"""
stock.csv on the phone, split into part files of about 15 tickers each.

Same columns and format as the desktop's data/stock.csv; a ticker always lives in the
same part (by a hash of its symbol). Every ticker's bars, indicators and signals depend
only on that ticker, so the unchanged desktop functions are simply called once per part:

    core.data_store.update_data(cfg with stock_csv = part file, tickers of that part)
    core.runner.run_engine(bars of that part)

and the phone never holds more than one part in memory (the desktop needs 1.5-1.8 GB
for the whole universe at once).
"""

from __future__ import annotations

import zlib
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

import pandas as pd

from core import data_store as ds

N_PARTS = 16
ProgressFn = Callable[[float, str], None]


def part_of(ticker: str) -> int:
    return zlib.crc32(ticker.encode("utf-8")) % N_PARTS


class Store:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.dir = Path(cfg["stock_csv"]).parent / "stock_parts"

    # ---------------------------------------------------------------- files
    def part_path(self, i: int) -> Path:
        return self.dir / f"stock_{i:02d}.csv"

    def part_paths(self) -> list[Path]:
        return [p for p in (self.part_path(i) for i in range(N_PARTS)) if p.exists()]

    def mtime(self) -> float:
        """Changes whenever any part is rewritten (used as a cache key)."""
        return sum(p.stat().st_mtime for p in self.part_paths())

    def empty(self) -> bool:
        return not self.part_paths()

    def size_mb(self) -> float:
        return round(sum(p.stat().st_size for p in self.part_paths()) / 1e6, 1)

    def frames(self, timeframes: Optional[Sequence[str]] = None) -> Iterator[pd.DataFrame]:
        """Each part as a stock.csv frame (optionally only some timeframes)."""
        for path in self.part_paths():
            df = _load(str(path), path.stat().st_mtime)
            yield df[df["time_frame"].isin(timeframes)] if timeframes else df

    def ticker_bars(self, ticker: str, time_frame: Optional[str] = None) -> pd.DataFrame:
        path = self.part_path(part_of(ticker))
        if not path.exists():
            return ds.empty_frame()
        df = _load(str(path), path.stat().st_mtime)
        df = df[df["Ticker"] == ticker]
        return df[df["time_frame"] == time_frame] if time_frame else df

    # ---------------------------------------------------------------- update
    def update(self, tickers: Sequence[str], timeframes: Sequence[str], incremental_days: int,
               full: bool, fetch, progress: Optional[ProgressFn] = None) -> ds.UpdateReport:
        """core.data_store.update_data once per part; the reports are added up."""
        groups: dict[int, list[str]] = {}
        for t in ds.clean_tickers(tickers):
            groups.setdefault(part_of(t), []).append(t)
        self.dir.mkdir(parents=True, exist_ok=True)
        reports: list[ds.UpdateReport] = []
        items = sorted(groups.items())
        for n, (i, group) in enumerate(items):
            cfg = dict(self.cfg, stock_csv=self.part_path(i), backups_dir=self.dir / "backups" / f"{i:02d}")
            self.drop_live_rows(i)

            def step(done: int, total: int, msg: str, n: int = n) -> None:
                if progress:
                    progress((n + done / max(total, 1)) / len(items), f"part {n + 1}/{len(items)} · {msg}")

            reports.append(ds.update_data(cfg, group, timeframes, incremental_days, full=full,
                                          progress=step, fetch=fetch))
            _load.cache_clear()
        return _combine(reports)

    def drop_live_rows(self, i: int) -> int:
        """
        Remove intraday rows left by Yahoo's separate "live" row (app 1.0-1.3 stored it as a
        bar stamped with the download time, e.g. 12:46:47). Real bars never carry seconds.
        The update that follows downloads those days again and rebuilds the 4hr bars.
        """
        path = self.part_path(i)
        if not path.exists():
            return 0
        df = ds.load_stock_csv(path)
        bad = df["time_frame"].isin(["60m", "4hr"]) & (df["time"].dt.second != 0)
        if not bad.any():
            return 0
        ds.save_stock_csv(ds.add_indicators(df.loc[~bad, ds.BASE_SCHEMA], int(self.cfg["indicator_decimals"])),
                          path, self.dir / "backups" / f"{i:02d}", 1)
        _load.cache_clear()
        return int(bad.sum())

    # ---------------------------------------------------------------- import / summaries
    def import_csv(self, path: Path, progress: Optional[ProgressFn] = None) -> int:
        """Split a desktop stock.csv into parts (read in pieces, so it never sits in memory whole)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = {i: self.dir / f"import_{i:02d}.csv" for i in range(N_PARTS)}
        for p in tmp.values():
            p.unlink(missing_ok=True)
        rows = 0
        for chunk in pd.read_csv(path, chunksize=200_000):
            rows += len(chunk)
            for i, part in chunk.groupby(chunk["Ticker"].map(part_of)):
                part.to_csv(tmp[int(i)], mode="a", header=not tmp[int(i)].exists(), index=False)
            if progress:
                progress(0.5 * min(rows / 1.3e6, 1.0), f"read {rows:,} rows")
        for n, (i, p) in enumerate(tmp.items()):
            if p.exists():
                df = ds.load_stock_csv(p).sort_values(ds.KEYS).reset_index(drop=True)
                ds.save_stock_csv(df, self.part_path(i), self.dir / "backups" / f"{i:02d}", 1)
                p.unlink()
            if progress:
                progress(0.5 + 0.5 * (n + 1) / N_PARTS, f"wrote part {n + 1}/{N_PARTS}")
        _load.cache_clear()
        return rows

    # ---- summaries: each part is read once per change, then only its small summary is kept
    def _infos(self) -> list[dict]:
        return [_info(str(p), p.stat().st_mtime) for p in self.part_paths()]

    def timeframe_summary(self) -> pd.DataFrame:
        parts = [i["summary"] for i in self._infos() if not i["summary"].empty]
        if not parts:
            return ds.timeframe_summary(ds.empty_frame())
        return (pd.concat(parts).groupby("time_frame")
                  .agg(rows=("rows", "sum"), tickers=("tickers", "sum"),
                       first_bar=("first_bar", "min"), last_bar=("last_bar", "max"))
                  .reset_index())

    def bars_per_ticker(self, short_threshold: int, skip: Sequence[str] = ()) -> pd.DataFrame:
        counts = [i["counts"] for i in self._infos() if not i["counts"].empty]
        if not counts:
            return ds.bars_per_ticker(ds.empty_frame(), short_threshold, skip)
        out = pd.concat(counts).fillna(0).astype(int)                     # Ticker x time_frame
        flagged = [c for c in out.columns if c not in skip]
        out["short_history"] = (out[flagged] < short_threshold).any(axis=1)
        out.columns = [f"bars_{c}" if c != "short_history" else c for c in out.columns]
        out = out.reset_index()
        bar_cols = sorted(c for c in out.columns if c.startswith("bars_"))
        return out[["Ticker", *bar_cols, "short_history"]]

    def tickers(self) -> list[str]:
        return sorted({t for i in self._infos() for t in i["tickers"]})

    def last_time(self) -> Optional[pd.Timestamp]:
        times = [i["last"] for i in self._infos() if i["last"] is not None]
        return max(times) if times else None

    def preview(self, tickers: Sequence[str], timeframes: Sequence[str], newest_first: bool,
                limit: int) -> tuple[pd.DataFrame, int]:
        """
        Rows for the Data tab preview. Picked tickers: only their parts are read. No ticker
        picked, newest first: from the newest rows kept per part, so nothing is re-read.
        """
        if tickers:
            frames = [self.ticker_bars(t) for t in tickers]
        elif newest_first:
            infos = self._infos()
            frames = [i["newest"] for i in infos]
            total = sum(int(i["summary"].loc[i["summary"]["time_frame"].isin(timeframes) if timeframes
                                             else slice(None), "rows"].sum()) for i in infos)
            frames = [f[f["time_frame"].isin(timeframes)] if timeframes else f for f in frames]
            frames = [f for f in frames if not f.empty]
            if not frames:
                return ds.empty_frame(), 0
            view = pd.concat(frames).sort_values("time", ascending=False, kind="stable").head(limit)
            return view, total
        else:
            frames = list(self.frames())
        frames = [f[f["time_frame"].isin(timeframes)] if timeframes else f for f in frames]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return ds.empty_frame(), 0
        total = sum(len(f) for f in frames)
        heads = [f.sort_values("time", ascending=not newest_first).head(limit) for f in frames]
        view = pd.concat(heads).sort_values("time", ascending=not newest_first, kind="stable").head(limit)
        return view, total


PREVIEW_KEEP = 2000            # newest rows kept per part and timeframe for the Data tab preview


@lru_cache(maxsize=64)
def _info(path: str, mtime: float) -> dict:
    df = _load(path, mtime)
    newest = (df.sort_values("time", ascending=False, kind="stable").groupby("time_frame", sort=False)
                .head(PREVIEW_KEEP)) if not df.empty else df
    return {
        "summary": ds.timeframe_summary(df),
        "counts": (df.pivot_table(index="Ticker", columns="time_frame", values="time", aggfunc="size", fill_value=0)
                   if not df.empty else pd.DataFrame()),
        "tickers": set(df["Ticker"].unique()),
        "last": df["time"].max() if not df.empty else None,
        "newest": newest,
    }


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> pd.DataFrame:
    return ds.load_stock_csv(Path(path))


def _combine(reports: list[ds.UpdateReport]) -> ds.UpdateReport:
    stats = [r.stats for r in reports if not r.stats.empty]
    merged = (pd.concat(stats).groupby("time_frame")[["downloaded", "added", "replaced"]].sum().reset_index()
              if stats else pd.DataFrame(columns=["time_frame", "downloaded", "added", "replaced"]))
    failed: dict[str, list[str]] = {}
    for r in reports:
        for tf, bad in r.failed.items():
            failed.setdefault(tf, []).extend(bad)
    return ds.UpdateReport(stats=merged, failed=failed, log=[line for r in reports for line in r.log],
                           rows_before=sum(r.rows_before for r in reports),
                           rows_after=sum(r.rows_after for r in reports),
                           saved=any(r.saved for r in reports))
