"""Load config.yaml and resolve its file paths against the project root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
_PATH_KEYS = ("tickers_file", "stock_csv", "backups_dir", "results_dir", "logs_dir",
              "dashboard_filters_file", "dashboard_filters_file_ew3", "stock_charts_filters_file")


def resolve(path: str | Path) -> Path:
    """Absolute path; relative paths are taken from the project root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else ROOT / p


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for key in _PATH_KEYS:
        cfg[key] = resolve(cfg[key])
    return cfg
