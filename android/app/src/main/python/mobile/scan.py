"""
runner.run_engine one group of tickers at a time.

Every ticker is screened on its own (and its higher-timeframe trend only reads its own
bars), so running the universe group by group gives exactly the same rows as one run
over everything, while the working memory stays at the size of one group.
tests/test_mobile.py checks that.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

import pandas as pd

from core import runner

ORDER = ("signal_time", "Ticker", "time_frame", "zigzag_length")


def _join(parts: list[pd.DataFrame]) -> pd.DataFrame:
    filled = [x for x in parts if not x.empty]
    if not filled:
        return parts[0] if parts else pd.DataFrame()
    out = pd.concat(filled, ignore_index=True)
    order = [c for c in ORDER if c in out.columns]
    return out.sort_values(order, kind="stable").reset_index(drop=True)


def run_groups(frames: Iterable[pd.DataFrame], n_groups: int, p: runner.RunParams,
               indicator_cols: Sequence[str], htf_cfg: dict,
               progress: Optional[Callable[[int, int], None]] = None) -> pd.DataFrame:
    """run_engine on each frame (one group of tickers each) and join the results."""
    parts = []
    for n, df in enumerate(frames):
        if progress:
            progress(n, n_groups)
        parts.append(runner.run_engine(df, p, indicator_cols, htf_cfg))
    if progress:
        progress(n_groups, n_groups)
    return _join(parts)


def run_chunked(df: pd.DataFrame, p: runner.RunParams, indicator_cols: Sequence[str], htf_cfg: dict,
                chunk: int = 30) -> pd.DataFrame:
    """Same as run_engine(df, ...) but group by group (used by the equality test)."""
    tickers = sorted(df["Ticker"].unique())
    groups = [tickers[i:i + chunk] for i in range(0, len(tickers), chunk)] or [[]]
    return run_groups((df[df["Ticker"].isin(g)] for g in groups), len(groups), p, indicator_cols, htf_cfg)
