"""
Stock attributes and stock lists ("universes") from data/tickers.csv.

tickers.csv:  Ticker, marketcapname, cnx_sector_name, fno_enabled, macro_info, sector_info

    universe "all"  every stock in the file             (+ indices and commodities from stock_data.py)
    universe "fno"  stocks with fno_enabled = true      (+ indices and commodities)

Signals get the attribute columns joined by Ticker for the dashboard filters and charts.
Indices and commodities are not in the file; their attributes read "Index" / "Commodity".
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

import stock_data

ATTR_COLS = ("marketcapname", "cnx_sector_name", "fno_enabled", "macro_info", "sector_info")
ATTR_LABELS = {"marketcapname": "Market cap", "cnx_sector_name": "CNX sector", "fno_enabled": "F&O",
               "macro_info": "Macro sector", "sector_info": "Sector index"}
CHART_COLS = ("marketcapname", "fno_enabled", "macro_info")       # the attribute charts on the dashboards
UNIVERSES = {"all": "All stocks", "fno": "F&O stocks"}
MISSING = "-"


def load_attributes(path: Path) -> pd.DataFrame:
    """Ticker-indexed attribute table (text values; blanks become '-'). Empty if the file has no attributes."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(ATTR_COLS))
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)     # utf-8-sig: the file starts with a BOM
    df.columns = [c.strip() for c in df.columns]
    key = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
    df = df.rename(columns={key: "Ticker"})
    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    df = df[df["Ticker"].ne("") & df["Ticker"].ne("nan")].drop_duplicates("Ticker").set_index("Ticker")
    out = pd.DataFrame(index=df.index)
    for col in ATTR_COLS:
        values = df[col] if col in df.columns else pd.Series(MISSING, index=df.index)
        values = values.fillna(MISSING).astype(str).str.strip().replace({"": MISSING, "nan": MISSING})
        if col == "fno_enabled":
            values = values.str.lower().map({"true": "Yes", "false": "No", "1": "Yes", "0": "No"}).fillna(values)
        out[col] = values
    return out


def has_attributes(attrs: pd.DataFrame) -> bool:
    return not attrs.empty and any((attrs[c] != MISSING).any() for c in ATTR_COLS if c in attrs.columns)


def kind_of(ticker: str) -> str:
    if ticker in stock_data.indian_index:
        return "Index"
    if ticker in stock_data.commodity:
        return "Commodity"
    return MISSING


def attach(res: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    """Add the attribute columns to signal rows (by Ticker). Existing columns are replaced."""
    out = res.drop(columns=[c for c in ATTR_COLS if c in res.columns])
    if out.empty:
        for col in ATTR_COLS:
            out[col] = pd.Series(dtype="object")
        return out
    joined = out[["Ticker"]].join(attrs, on="Ticker")
    for col in ATTR_COLS:
        values = joined[col] if col in joined.columns else pd.Series(index=out.index, dtype="object")
        out[col] = values.where(values.notna(), out["Ticker"].map(kind_of)).fillna(MISSING).astype(str)
    return out


def stocks(path: Path, universe: str = "all") -> list[str]:
    """Stock tickers of a universe, in file order (indices / commodities are added by build_final_list)."""
    attrs = load_attributes(path)
    if attrs.empty:
        return [t for t in stock_data.read_stock_tickers(path)] if Path(path).exists() else []
    if universe == "fno":
        return list(attrs.index[attrs["fno_enabled"].eq("Yes")])
    return list(attrs.index)


def counts(path: Path) -> dict[str, int]:
    attrs = load_attributes(path)
    return {"all": len(attrs), "fno": int(attrs["fno_enabled"].eq("Yes").sum()) if not attrs.empty else 0}


def final_list(path: Path, universe: str = "all") -> list[str]:
    """stocks of the universe + indices + commodities (stock_data.build_final_list)."""
    return stock_data.build_final_list(stocks(path, universe))


def write_stocks(path: Path, tickers: Sequence[str]) -> None:
    """Save a stock list; tickers already in the file keep their attributes, new ones get '-'."""
    path = Path(path)
    old = pd.read_csv(path, encoding="utf-8-sig", dtype=str) if path.exists() else pd.DataFrame(columns=["Ticker"])
    old.columns = [c.strip() for c in old.columns]
    key = next((c for c in old.columns if c.lower() in ("ticker", "symbol")), old.columns[0] if len(old.columns) else "Ticker")
    old = old.rename(columns={key: "Ticker"}).drop_duplicates("Ticker").set_index("Ticker")
    cols = [c for c in old.columns] or []
    out = pd.DataFrame(index=pd.Index(list(dict.fromkeys(tickers)), name="Ticker")).join(old[cols])
    if cols:
        out[cols] = out[cols].fillna(MISSING)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.reset_index().to_csv(path, index=False)


def mask(res: pd.DataFrame, picks: dict[str, Sequence[str]]) -> pd.Series:
    """Rows whose attributes are in the picked values (an empty pick = no filter)."""
    m = pd.Series(True, index=res.index)
    for col, values in picks.items():
        if values and col in res.columns:
            m &= res[col].astype(str).isin([str(v) for v in values])
    return m
