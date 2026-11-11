## Architecture

Everything is local files. No database.

```
app.py                     Streamlit app: EW5 · EW3 · Data · Run / Backtest · User Guide
config.yaml                every tunable value
elliott_wave5_screener.py  Elliott Wave engine and EW5 screener (never modified by the app)
elliott_wave3_screener.py  EW3 screener: wave 2 finished / wave 3 starting, on the same engine
core/strategies.py         what differs between EW5 and EW3 (columns, levels, stats, chart groups)
stock_data.py              ticker lists, 60m → 4hr conversion, indicators, command-line update
core/config.py             loads config.yaml, resolves paths
core/data_store.py         download, IST conversion, merge/dedupe, indicators, safe write
core/runner.py             calls the engine, explodes levels, saves/loads results
core/charts.py             Plotly figures
docs/                      this guide
data/tickers.csv           stock tickers (one column: Ticker)
data/stock.csv             all bars, all timeframes, with indicators
data/backups/              previous stock.csv copies (last 5)
results/                   one CSV + JSON per run
logs/data_update.log       download log
tests/                     pytest
```

Data flow:

```
tickers.csv + indian_index + commodity ──► yfinance (1d, 60m)
        │
        ▼
IST conversion ─► 60m (kept) + 60m → 4hr ─► merge + dedupe ─► indicators ─► data/stock.csv
                                                                    │
                          screen_wave5 / backtest_wave5 ◄───────────┤
                                     │                              │
                                     ▼                              ▼
                          results/<mode>_<time>.csv ──────────► Dashboard
```

---

## Tickers

`final_list = stock_tickers + indian_index + commodity`

- `stock_tickers` come from `data/tickers.csv` (column `Ticker`).
- `indian_index` and `commodity` are Python lists at the top of `stock_data.py`.
- Symbols are sent to yfinance **exactly as written**. Nothing is renamed, so use yfinance
  formats: `RELIANCE.NS`, `^NSEI`, `GC=F`, `BTC-USD`.
- The `Ticker` column in `stock.csv` holds the same symbol.

---

## Data update logic

For every timeframe and ticker, `update_data()` decides:

| Situation | Download |
|---|---|
| Ticker not in `stock.csv` yet (first run, or newly added) | Full history |
| Ticker already stored | Last `incremental_days` (sidebar input, default 30) |
| Newest stored bar is older than the incremental window | Full history, so no hole is left |
| **Full re-download** button | Full history for everything; stored rows are replaced |

Full history is `full_history` in `config.yaml`: 3 years of daily bars, and 729 days of 60m bars
(the yfinance limit).

Steps of one update:

1. Download in batches of `batch_size` tickers per `yf.download` call. Tickers that return
   nothing are retried `retries` times with a growing pause; whatever still fails is listed
   and the update carries on.
2. Convert timestamps to **timezone-naive IST**. Daily bars are stamped `00:00:00`.
3. Build 4hr bars from 60m bars (see below).
4. Drop rows with missing OHLC, round OHLC to `price_decimals`.
5. Append to the stored data and drop duplicates on `(Ticker, time_frame, time)`, **keeping the
   newest row**. Sort by `Ticker, time_frame, time`.
6. Recompute the indicators on the full merged history of each series.
7. Copy the old `stock.csv` to `data/backups/`, write a temp file, rename it over `stock.csv`.

Running the same update twice produces the identical file.

### 60m and 4hr from one download

Three timeframes are stored: `1D`, `4hr` and `60m`. The 60m bars are saved as downloaded
(NSE: 09:15, 10:15 … 15:15, seven per session), and the same download is used to build the 4hr
bars, so adding 60m costs no extra requests. yfinance serves about 730 days of 60m data.

### 60m → 4hr (`build_4h_from_hourly`)

yfinance has no 4-hour interval, so the 60m bars are converted per day:

- the **first four** 60m bars of the day form the first bar,
- the **remaining** bars of the day form the second bar,
- Open = first, High = max, Low = min, Close = last, Volume = sum,
- each bar is labelled with the time of its first 60m bar.

For NSE symbols this gives `09:15` (09:15–13:15) and `13:15` (13:15–15:30), the same as a
TradingView 4h chart. Instruments that trade around the clock (crypto, commodity futures) also
get two bars per day by this rule: the first four hours, then the rest of the day.

### Indicators (`calculate_indicator_values`)

Calculated with TA-Lib for every ticker and timeframe:

| Column | Definition |
|---|---|
| `rsi` | RSI(14) of Close |
| `rsi_a`, `e`, `f`, `storsi` | RSI(a), its rolling max / min over b bars, and the stochastic of RSI |
| `dtosck`, `dtoscd` | SMA(c) of `storsi`, and SMA(d) of `dtosck` (DT oscillator) |
| `maValue` | SMA(14) of Close |
| `normalizedRSI`, `histogram` | RSI clipped to 0–100, and RSI − 50 |
| `13_ema`, `21_ema`, `55_ema` | EMAs of Close |
| `atr14` | ATR(14) |
| `cci` | CCI(14) |

`a, b, c, d` depend on `type_val` in `stock_data.py` (2 → 13, 8, 5, 5).
Indicators are stored in `stock.csv`, copied into result files at the signal bar
(`signal_indicators` in `config.yaml`) and shown in tables. The Elliott Wave engine does not
read them. On the chart, EMA 13 / 55 are drawn on price and RSI, DT oscillator and histogram in one pane below it.

### stock.csv schema

```
Ticker, time, time_frame, Open, High, Low, Close, Volume,
rsi, rsi_a, e, f, storsi, dtosck, dtoscd, maValue, normalizedRSI, histogram,
13_ema, 21_ema, 55_ema, atr14, cci
```

`time` is `YYYY-MM-DD HH:MM:SS` in IST. `time_frame` is `1D`, `4hr` or `60m`.
Prices are split-adjusted but not dividend-adjusted (`auto_adjust: false`).

---

## Engine (elliott_wave5_screener.py)

A bar-by-bar Python replay of the Pine Script logic. For one ticker, timeframe and ZigZag length:

1. **Pivots** – a high (low) is a pivot when it is above (below) the `length` bars to its left
   and the one bar to its right. It is confirmed one bar later. `pivot_tie` decides whether
   equal highs/lows on the left are allowed (`left_equal`) or not (`strict`).
2. **ZigZag** – alternating pivot highs and lows; a more extreme pivot in the same direction
   replaces the previous one.
3. **Impulse test** on the last six ZigZag points (0-1-2-3-4-5), for a bullish impulse:
   wave 3 is not the shortest of waves 1, 3, 5; point 5 is above point 3; point 2 is above
   point 0; point 4 is above point 1 (no overlap). Mirrored for bearish.
4. **Invalidation and a-b-c** – the count is switched off when the structure breaks; an a-b-c
   correction is tracked after wave 5, and the signal ends when it completes or when price
   breaks the 0.854 retracement.
5. **Snapshot** – state at a given bar using only that bar and earlier ones.

Public functions used by the app:

| Function | Used for |
|---|---|
| `screen_wave5(df, as_of=None, …)` | Live screen and point-in-time screen |
| `evaluate_signals(signals, df, horizon_bars)` | Forward outcome of signals |
| `backtest_wave5(df, start, end, horizon_bars, …)` | Walk-forward backtest |
| `summarize_backtest(results)` | Hit-rate table |
| `ElliottWaveEngine.step / snapshot` | Rebuilding the wave points for the chart |

A series needs at least `min_bars` (120) bars to be screened, and about 500 for reliable
major-degree counts.

---

## EW3 screener (elliott_wave3_screener.py)

EW3 adds no new wave engine. It drives the same `ElliottWaveEngine` bar by bar and reads the
three latest ZigZag points after each bar: 0 (start of wave 1), 1 (end of wave 1) and 2 (end of
wave 2, the latest confirmed pivot). `elliott_wave5_screener.py` is imported, not changed.

A setup exists on bar *t* when all of these hold:

1. The three points are real, alternating pivots and each wave spans at least one bar.
2. Wave 1 moved away from point 0, and wave 2 retraced it by `min_retrace` to `max_retrace`
   (`max_retrace` must be below 1, so point 0 is never passed).
3. No bar since the wave-2 pivot has gone beyond the wave-2 end.

Stage is `WAVE3_CONFIRMED` once a close beyond the wave-1 end has occurred since the pivot,
otherwise `WAVE2_COMPLETED`. Context comes from the engine's latest impulse: `AFTER_WAVE5` when
point 0 is that impulse's wave-5 end and the new move is against it, `AFTER_ABC` when point 0
is the end of its a-b-c correction and the new move is with it, else `OTHER`.

The wave-2 pivot is confirmed one bar after it forms, like every pivot in the engine, so
nothing uses future bars. `screen_wave3(df, as_of=d)` equals `screen_wave3(df[df.time <= d])`,
and every walk-forward signal equals the point-in-time screen on its own bar (both tested).

| Function | Purpose |
|---|---|
| `screen_wave3(df, as_of=None, …)` | Live and point-in-time screen |
| `backtest_wave3(df, start, end, horizon_bars, …)` | Walk-forward backtest |
| `evaluate_signals(signals, df, horizon_bars)` | Forward outcome |
| `summarize_backtest(results)` | Hit-rate table |

Levels (`wave_levels`, fixed order): `W0_START, W1_END, W2_END, TRIGGER, STOP,
W2_RET_0.382 … 0.786, W3_TGT_1.000xW1, 1.618xW1, 2.618xW1`. TRIGGER is the high (LONG) or low
(SHORT) of the wave-2 bar; STOP is the wave-2 end; targets are projected from the wave-2 end.

Outcome: `FAILED` if price goes beyond the wave-2 end before the trigger, `TRIGGERED` on a
close beyond TRIGGER, else `NOT_TRIGGERED`. After the trigger, `hit_<target>` is recorded for
`W1_END` and the three wave-3 targets, with the wave-2 end as stop. Same-bar conflicts count
the failure or stop first.

Result files are named `ew3_<mode>_<time>.csv`; EW5 files keep their names. Each tab lists only
its own files and saves its own filters (`dashboard_filters_file` and
`dashboard_filters_file_ew3`). EW3 defaults live under `ew3:` in `config.yaml`.

---

## Run modes (core/runner.py)

The Run tab has a strategy switch (EW5 / EW3). Both use the same three modes:

| Mode | EW5 call | EW3 call |
|---|---|---|
| Live screen | `screen_wave5(df)` | `screen_wave3(df)` |
| Point-in-time | `screen_wave5(df, as_of=…)` then `evaluate_signals` | `screen_wave3(df, as_of=…)` then `evaluate_signals` |
| Walk-forward | `backtest_wave5(df, start, end, horizon_bars, …)` | `backtest_wave3(df, start, end, horizon_bars, …)` |

An as-of or end **date** means the end of that day (`23:59:59`), so the daily bar and both 4hr
bars of that day are included for both timeframes.

After the engine returns:

- `reversal_levels` (list of `"NAME=value"`) is exploded into one float column per level; the
  list column is kept.
- Indicator values of the signal bar are merged in.
- The result is saved as `results/<mode>_<YYYYmmdd_HHMMSS>.csv` plus a `.json` holding the parameters.

Results are cached by `stock.csv` modified time plus parameters, so repeating a run is instant.

### Outcome columns (from `evaluate_signals`)

`status`, `trigger_time`, `entry_price` (close of the trigger bar), `stopped`, `stop_time`,
`hit_<target>` and `hit_<target>_time` for `W4_END` and the four Fib levels, `first_target_hit`,
`mfe_pct`, `mae_pct`, `result`, `bars_evaluated`.

---

## Signal chart (core/charts.py)

- Candles: about `chart.bars_before` bars before the signal plus `horizon_bars` after it.
- Wave points: the engine is re-run on data up to `signal_time` and `snapshot()` gives the bar
  index of points 0–5; a, b, c come from the engine's latest wave.
- The x-axis is a category axis (one slot per bar), so nights, weekends and holidays leave no gaps.
- Level groups, the evaluation window, and trigger / stop / target-hit markers are overlaid.
- EMA 13 and EMA 55 are read from `stock.csv`.
- One indicator pane sits under the price on a fixed 0–100 scale, like a TradingView oscillator pane: RSI 14, DT oscillator K and D as lines, with guide lines at 30, 50 and 70. The histogram (RSI − 50) is drawn from the 50 line and only where it is below −20 (green) or above +20 (red), the same colours as the table. One toggle switches the pane on or off; `chart.indicator_panes` and `chart.pane_height` in `config.yaml` control which series are drawn and how tall the pane is.

---

## Configuration (config.yaml)

| Key | Purpose |
|---|---|
| `tickers_file`, `stock_csv`, `backups_dir`, `results_dir`, `logs_dir` | File locations |
| `timeframes`, `incremental_days`, `full_history`, `intraday_max_days` | What and how much to download |
| `batch_size`, `retries`, `backoff_seconds` | Download behaviour |
| `auto_adjust`, `price_decimals`, `indicator_decimals` | Price handling |
| `short_history_bars`, `min_bars` | History thresholds |
| `engine.*` | Default lengths, horizon, pivot tie, stages, sources |
| `chart.*`, `signal_indicators` | Chart size, EMA columns, indicators copied into results |

Restart the app after changing `config.yaml`, `stock_data.py` or anything under `core/`.

---

## Commands

```
./run.sh                           start the app on http://localhost:8501
.venv/bin/python stock_data.py     update data from the terminal
.venv/bin/python stock_data.py --full
.venv/bin/python -m pytest         run the tests
```

## Known limits

- yfinance serves only about 730 days of 60m data, so 4hr history cannot go back further.
- Some Yahoo sector indices (several `NIFTY_*.NS`) return almost no daily history.
- Yahoo data can be late or revised; the incremental window re-downloads recent bars for that reason.
- The engine is pure Python: with 60m included, a live screen over all three timeframes takes about 15 seconds and long 60m backtests take longer.
- `stock.csv` is about 235 MB once 60m bars are stored, so `backups_keep` is set to 3.
