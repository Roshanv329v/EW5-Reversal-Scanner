# -*- coding: utf-8 -*-
"""
stock_data.py - ticker lists, 60m -> 4hr conversion and indicators.

The three building blocks below are taken from "1 FnO Data.ipynb":

    final_list                    = stock_tickers + indian_index + commodity
    build_4h_from_hourly(df)      60m bars -> 4hr bars
    calculate_indicator_values(df) RSI / DTosc / EMA / ATR / CCI

core/data_store.py calls them, so the app and this script share the same logic.
Run it from the terminal to update data/stock.csv:

    python stock_data.py            # new tickers = full history, the rest = last N days
    python stock_data.py --full     # re-download the full history of everything
    python stock_data.py --days 10  # incremental window of 10 days
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import talib

# ----------------------------------------------------------------------------------
# Ticker lists. Symbols are used exactly as written (yfinance format) - no renaming.
# ----------------------------------------------------------------------------------
indian_index = ['^NSEI', '^NSEBANK', '^CNXAUTO', '^CNXPSE', '^CNXFMCG', '^CNXIT', '^CNXPHARMA',
                '^CNXPSUBANK', '^CNXENERGY', '^INDIAVIX', 'NIFTY_FIN_SERVICE.NS', '^BSESN']
commodity = ['NG=F', 'CL=F', 'GC=F', 'SI=F']


def read_stock_tickers(path: Path) -> list[str]:
    """Stock tickers from the CSV file (`Ticker` column, else `symbol`, else the first column)."""
    stock_df = pd.read_csv(path)
    lower = {c.lower(): c for c in stock_df.columns}
    col = lower.get("ticker") or lower.get("symbol") or stock_df.columns[0]
    return [t for t in stock_df[col].dropna().astype(str).str.strip() if t]


def build_final_list(stock_tickers: list[str]) -> list[str]:
    """final_list = stock_tickers + indian_index + commodity (duplicates removed, order kept)."""
    final_list = stock_tickers + indian_index + commodity
    return list(dict.fromkeys(final_list))


# ----------------------------------------------------------------------------------
# Indicator parameters (DTosc type)
# ----------------------------------------------------------------------------------
type_val = 2  # You can change this to 1, 2, or 3

a = 8 if type_val == 1 else 13 if type_val == 2 else 21 if type_val == 3 else 34
b = 5 if type_val == 1 else 8 if type_val == 2 else 13 if type_val == 3 else 21
c = 3 if type_val == 1 else 5 if type_val == 2 else 8 if type_val == 3 else 13
d = 3 if type_val == 1 else 5 if type_val == 2 else 8 if type_val == 3 else 13

INDICATOR_COLS = ['rsi', 'rsi_a', 'e', 'f', 'storsi', 'dtosck', 'dtoscd', 'maValue', 'normalizedRSI',
                  'histogram', '13_ema', '21_ema', '55_ema', 'atr14', 'cci']


def calculate_indicator_values(df_pd):

    # Adding indicators
    df_pd = df_pd.sort_values("Date")

    df_pd["rsi"] = talib.RSI(df_pd["Close"], timeperiod=14)
    df_pd["rsi_a"] = talib.RSI(df_pd["Close"], timeperiod=a)
    df_pd["e"] = df_pd["rsi_a"].rolling(window=b, min_periods=1).max()
    df_pd["f"] = df_pd["rsi_a"].rolling(window=b, min_periods=1).min()
    df_pd["storsi"] = 100 * ((df_pd["rsi_a"] - df_pd["f"]) / (df_pd["e"] - df_pd["f"]))
    df_pd["dtosck"] = talib.SMA(df_pd["storsi"], c)
    df_pd["dtoscd"] = talib.SMA(df_pd["dtosck"], d)
    # Histogram
    df_pd["maValue"] = talib.SMA(df_pd["Close"], 14)
    df_pd["normalizedRSI"] = df_pd["rsi"].clip(lower=0, upper=100)
    df_pd["histogram"] = df_pd["normalizedRSI"] - 50
    # Moving Averages
    df_pd["13_ema"] = talib.EMA(df_pd["Close"], 13)
    df_pd["21_ema"] = talib.EMA(df_pd["Close"], 21)
    df_pd["55_ema"] = talib.EMA(df_pd["Close"], 55)

    df_pd["atr14"] = talib.ATR(df_pd["High"], df_pd["Low"], df_pd["Close"], timeperiod=14)

    # Calculate the CCI using talib.CCI
    # The required inputs are High, Low, Close price arrays, and a timeperiod.
    # The timeperiod is typically 14 or 20, but can be adjusted.
    timeperiod = 14
    df_pd['cci'] = talib.CCI(df_pd['High'], df_pd['Low'], df_pd['Close'], timeperiod=timeperiod)

    return df_pd


def build_4h_from_hourly(df):
    """
    Converts hourly data (like 6 hourly bars/day) into 4h aggregates:
    - First 4 hours -> one 4h bar
    - Remaining 2 hours -> another shorter bar (2h)
    Works for entire 12-month data automatically.
    """
    # Ensure sorting
    df = df.sort_values("Date").reset_index(drop=True)

    # Extract date part (trading day)
    df["date_only"] = df["Date"].dt.date

    # Assign block number within each day (1 for first 4h, 2 for last 2h)
    df["hour_rank"] = df.groupby("date_only").cumcount() + 1
    df["hour_block"] = np.where(df["hour_rank"] <= 4, "4H_1", "4H_2")

    # Aggregate OHLCV for each day+block
    agg_funcs = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Adj Close": "last",
        "Volume": "sum"
    }
    # (only change vs the notebook: skip columns the download did not return)
    agg_funcs = {k: v for k, v in agg_funcs.items() if k in df.columns}

    df_4h = (
        df.groupby(["date_only", "hour_block"], as_index=False)
          .agg(agg_funcs)
    )

    # Rebuild a proper datetime index — use first timestamp of each block
    first_dt_per_block = (
        df.groupby(["date_only", "hour_block"])["Date"].first().reset_index(drop=True)
    )
    df_4h["Date"] = first_dt_per_block

    # Keep consistent column order
    out_cols = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    df_4h = df_4h[[col for col in out_cols if col in df_4h.columns]]

    return df_4h


# ----------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------
def main() -> None:
    from core.config import load_config
    from core.data_store import setup_logging, update_data

    cfg = load_config()
    parser = argparse.ArgumentParser(description="Update data/stock.csv from yfinance")
    parser.add_argument("--full", action="store_true", help="re-download the full history")
    parser.add_argument("--days", type=int, default=cfg["incremental_days"],
                        help="incremental window in days")
    args = parser.parse_args()

    setup_logging(cfg["logs_dir"])
    stock_tickers = read_stock_tickers(cfg["tickers_file"])
    final_list = build_final_list(stock_tickers)
    print(f"{len(final_list)} tickers = {len(stock_tickers)} stocks + "
          f"{len(indian_index)} indices + {len(commodity)} commodities")

    report = update_data(cfg, final_list, cfg["timeframes"], args.days, full=args.full,
                         progress=lambda done, total, msg: print(f"[{done}/{total}] {msg}"))
    print("\n".join(report.log[-12:]))
    print(report.stats.to_string(index=False))
    if report.failed:
        print("Failed:", report.failed)


if __name__ == "__main__":
    main()
