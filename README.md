# Elliott Wave 5 Reversal – local app

A local Streamlit app (http://localhost:8501) with four tabs:

1. **Dashboard** – KPIs, breakdowns, a filterable signal table and a candlestick chart per signal with the wave count, reversal levels and EMA 13 / 55.
2. **Data** – download / incrementally update Daily and 4hr bars from yfinance into `data/stock.csv`, with indicators.
3. **Run / Backtest** – run the Elliott Wave 5 screener (`elliott_wave5_screener.py`, unchanged) live, as of a past date, or walk-forward.
4. **User Guide** – how to use it for F&O study, and the technical documentation (also in `docs/`).

Everything stays in local files. No database, no Docker.

## Setup and start

```bash
./run.sh
```

`run.sh` creates `.venv` if it is missing, installs `requirements.txt`, and starts the app on
http://localhost:8501. Needs Python 3.11+.

## Tickers

`final_list = stock_tickers + indian_index + commodity`

- Stock tickers: `data/tickers.csv`, one column named `Ticker`.
- Indices and commodities: the `indian_index` and `commodity` lists at the top of `stock_data.py`.
- Symbols go to yfinance exactly as written, nothing is renamed. Use yfinance formats:
  `RELIANCE.NS`, `^NSEI`, `GC=F`, `BTC-USD`.

Add a stock by adding a row to `data/tickers.csv`. On the next **Update data** only that new
ticker gets a full download; everything else gets the incremental window.

## First full download

Open the app, press **Update data** in the sidebar. A ticker that is not in `stock.csv` yet gets
the full history (`full_history` in `config.yaml`: 3 years Daily, 729 days of 60m → 4hr).

From the terminal, the same thing:

```bash
.venv/bin/python stock_data.py
```

## Daily update

Press **Update data** again (or run `stock_data.py`). Only the last `incremental_days`
(default 30) are downloaded; they replace the stored rows for the same
`(Ticker, time_frame, time)`, so there are never duplicates and today's unfinished bar is
corrected by the next update. The previous `stock.csv` is copied to `data/backups/` (last 5 kept).

Use **Full re-download** after a split or bonus issue: old prices change, and only a full
download picks that up.

Notes on the data:

- Times are stored as timezone-naive IST. Daily bars are at `00:00:00`.
- 4hr bars are built from 60m bars by `build_4h_from_hourly` in `stock_data.py`: the first four
  60m bars of a day, then the rest. For NSE that is `09:15` and `13:15`, like TradingView.
- Indicators (`calculate_indicator_values` in `stock_data.py`, needs TA-Lib) are recalculated on
  the full history after every update and stored in `stock.csv`. They are shown in tables only;
  the chart draws EMA 13 and EMA 55.
- Prices are split-adjusted but not dividend-adjusted (`auto_adjust: false`), like TradingView's default.
- A ticker whose newest stored bar is older than the incremental window gets its full history
  again, so a long pause never leaves a hole.
- Tickers with fewer than 500 bars in a timeframe are flagged as short history.

## Running a backtest

**Run / Backtest** tab:

- **Live screen** – signals on the latest bar.
- **Point-in-time** – pick an as-of date, e.g. `2026-10-01`. The screener only sees bars up to the
  end of that day; the bars after it are used to evaluate what happened (`horizon_bars`).
- **Walk-forward backtest** – pick a start and end date; every bar in between is screened with
  only the data known at that bar.

Set the timeframes, ZigZag lengths, stages and filters, then press **Run**. The result opens in
the **Dashboard** tab.

## Where results are saved

`results/<mode>_<YYYYmmdd_HHMMSS>.csv` (mode = `live`, `asof` or `backtest`) plus a `.json` with
the same name holding the parameters used. The CSV has one numeric column per reversal level
(`W0_START` … `W5_TGT_1.618xW1`) and the original `reversal_levels` list.

## Configuration

All tunable values are in `config.yaml` (paths, download settings, 4H session times, engine
defaults, chart size). Restart the app after editing it.

## Tests

```bash
.venv/bin/python -m pytest
```

## Files

```
app.py                     Streamlit app, 4 tabs
config.yaml                all parameters
elliott_wave5_screener.py  Elliott Wave engine (unchanged)
stock_data.py              ticker lists, 60m → 4hr, indicators, command-line data update
docs/                      user guide shown in the app
core/config.py             loads config.yaml
core/data_store.py         download, IST conversion, merge/dedupe, indicators, safe write
core/runner.py             runs the engine, explodes levels, saves/loads results
core/charts.py             Plotly charts
data/                      tickers.csv, stock.csv, backups/
results/                   one CSV + JSON per run
logs/                      data_update.log
tests/                     pytest tests (synthetic fixtures live only here)
```
