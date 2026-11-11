"""Saved dashboard state (filters, selected stat, chart toggles) in a small JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

# filter name (results column) -> empty selection means "no filter"
FILTER_COLUMNS = ("time_frame", "degree", "reversal_side", "stage", "status", "result")


def default_prefs(columns: Sequence[str] = FILTER_COLUMNS) -> dict[str, Any]:
    return {
        **{col: [] for col in columns},
        "search": "",
        "ratio": [None, None],         # range slider [low, high]; None = "no limit on that side"
        "stat": None,                  # active stat card, e.g. "triggered"
        "chart_groups": {},            # level group / "ema" -> shown?
    }


def load_prefs(path: Path, columns: Sequence[str] = FILTER_COLUMNS) -> dict[str, Any]:
    """Saved state merged over the defaults. A missing or unreadable file gives the defaults."""
    prefs = default_prefs(columns)
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return prefs
    if isinstance(saved, dict):
        if "ratio" not in saved and "w5_vs_w1" in saved:        # files written before EW3 existed
            saved["ratio"] = saved["w5_vs_w1"]
        prefs.update({k: v for k, v in saved.items() if k in prefs})
    return prefs


def save_prefs(path: Path, prefs: dict[str, Any], columns: Sequence[str] = FILTER_COLUMNS) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: prefs.get(k, v) for k, v in default_prefs(columns).items()}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")


def ratio_range(pref: Sequence[Optional[float]], lo: float, hi: float) -> tuple[float, float]:
    """Saved [low, high] (None = open side) -> a slider value that fits inside [lo, hi]."""
    low = lo if pref[0] is None else min(max(float(pref[0]), lo), hi)
    high = hi if pref[1] is None else min(max(float(pref[1]), lo), hi)
    return (low, high) if low <= high else (lo, hi)


def ratio_pref(value: Sequence[float], lo: float, hi: float) -> list[Optional[float]]:
    """Slider value -> [low, high], with None for a handle resting on the end of the scale."""
    eps = 1e-9
    return [None if value[0] <= lo + eps else float(value[0]),
            None if value[1] >= hi - eps else float(value[1])]
