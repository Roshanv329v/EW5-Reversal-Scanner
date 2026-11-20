"""
Stock attributes and stock lists ("universes") from data/tickers.csv.

tickers.csv:  Ticker, marketcapname, cnx_sector_name, fno_enabled, macro_info, sector_info

    universe "all"  every stock in the file             (+ indices and commodities from stock_data.py)
    universe "fno"  stocks with fno_enabled = true      (+ indices and commodities)

Signals get the attribute columns joined by Ticker for the dashboard filters and charts.
Values are kept exactly as written in the file (fno_enabled: true / false); an empty cell reads
"(blank)". Indices and commodities are not in the file: their attributes are empty (""), so
they are never a filter option and drop out when an attribute filter is set.
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
BLANK = "(blank)"              # an empty cell in tickers.csv
NOT_LISTED = ""                # a ticker that is not in tickers.csv (indices, commodities)
MISSING = NOT_LISTED           # older name


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
        if col not in df.columns:
            out[col] = NOT_LISTED
            continue
        values = df[col].fillna("").astype(str).str.strip()
        if col == "fno_enabled":
            values = values.str.lower()                         # TRUE / True -> true, as the file means it
        out[col] = values.replace({"": BLANK})
    return out


def has_attributes(attrs: pd.DataFrame) -> bool:
    return not attrs.empty and any((~attrs[c].isin([NOT_LISTED, BLANK])).any() for c in ATTR_COLS if c in attrs.columns)


def kind_of(ticker: str) -> str:
    """Index / Commodity / Stock (for labels only; the attribute values stay as in tickers.csv)."""
    if ticker in stock_data.indian_index:
        return "Index"
    if ticker in stock_data.commodity:
        return "Commodity"
    return "Stock"


_OLD_VALUES = {"fno_enabled": {"Yes": "true", "No": "false"}, "cnx_sector_name": {"-": BLANK},
               "marketcapname": {"-": BLANK}, "macro_info": {"-": BLANK}}


def migrate_picks(column: str, values: Sequence) -> list[str]:
    """Filter values saved before the values were read as written (Yes / No, Index / Commodity, '-')."""
    if column not in ATTR_COLS:
        return list(values)
    out = []
    for v in values:
        v = _OLD_VALUES.get(column, {}).get(str(v), str(v))
        if v not in ("Index", "Commodity") and v not in out:
            out.append(v)
    return out


def options(values: Sequence) -> list[str]:
    """Filter choices: the values present, without the empty one of tickers not in tickers.csv."""
    return sorted({str(v) for v in values if pd.notna(v) and str(v) != NOT_LISTED})


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
        out[col] = values.fillna(NOT_LISTED).astype(str)
    return out


def stocks(path: Path, universe: str = "all") -> list[str]:
    """Stock tickers of a universe, in file order (indices / commodities are added by build_final_list)."""
    attrs = load_attributes(path)
    if attrs.empty:
        return [t for t in stock_data.read_stock_tickers(path)] if Path(path).exists() else []
    if universe == "fno":
        return list(attrs.index[attrs["fno_enabled"].eq("true")])
    return list(attrs.index)


def counts(path: Path) -> dict[str, int]:
    attrs = load_attributes(path)
    return {"all": len(attrs), "fno": int(attrs["fno_enabled"].eq("true").sum()) if not attrs.empty else 0}


def final_list(path: Path, universe: str = "all") -> list[str]:
    """stocks of the universe + indices + commodities (stock_data.build_final_list)."""
    return stock_data.build_final_list(stocks(path, universe))


def write_stocks(path: Path, tickers: Sequence[str]) -> None:
    """Save a stock list; tickers already in the file keep their attributes, new ones get empty cells."""
    path = Path(path)
    old = pd.read_csv(path, encoding="utf-8-sig", dtype=str) if path.exists() else pd.DataFrame(columns=["Ticker"])
    old.columns = [c.strip() for c in old.columns]
    key = next((c for c in old.columns if c.lower() in ("ticker", "symbol")), old.columns[0] if len(old.columns) else "Ticker")
    old = old.rename(columns={key: "Ticker"}).drop_duplicates("Ticker").set_index("Ticker")
    cols = [c for c in old.columns] or []
    out = pd.DataFrame(index=pd.Index(list(dict.fromkeys(tickers)), name="Ticker")).join(old[cols])
    if cols:
        out[cols] = out[cols].fillna("")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.reset_index().to_csv(path, index=False)


def mask(res: pd.DataFrame, picks: dict[str, Sequence[str]]) -> pd.Series:
    """Rows whose attributes are in the picked values (an empty pick = no filter)."""
    m = pd.Series(True, index=res.index)
    for col, values in picks.items():
        if values and col in res.columns:
            m &= res[col].astype(str).isin([str(v) for v in values])
    return m
