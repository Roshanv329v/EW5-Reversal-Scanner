## The phone app

The Android app runs the same scanner as the desktop, entirely on the phone. No computer
or server is involved; only the price download needs internet. The tabs match the desktop:
**EW5**, **EW3**, **Data**, **Run / Backtest** and **User Guide**.

### First start

1. **Data tab → Update data.** The first run downloads the full history of every ticker:
   3 years of daily bars and about 2 years of 60m bars (the 4hr and weekly bars are built
   from those). For all tickers this takes a while; a notification shows progress and the
   download carries on with the screen off or the app in the background.
2. **Run / Backtest tab.** Pick EW5 or EW3, a mode, and press **Run**. A full walk-forward
   backtest of every ticker on three timeframes takes several minutes on a phone.
3. **EW5 / EW3 tabs.** The run you just made opens there.

Have the desktop's `data/stock.csv` already? Copy it to the phone (cable, Google Drive …) and
use **Data → Import stock.csv** instead of downloading. The import takes about a minute.

### Daily routine

Same as the desktop:

1. **Data → Update data** after the close (only the last 30 days are downloaded).
2. **Run / Backtest → Live screen → Run**, for EW5 and for EW3.
3. Open the EW5 and EW3 tabs, set the **HTF alignment** filter, tap a signal for its chart.

### Using the screens

- **Filters** open a list to tick. **Save filters** remembers them, the selected stat card and
  the chart toggles, exactly as on the desktop.
- **Stat cards**: tap *Show N* to narrow the signal table; tap again to clear.
- **Breakdown charts**: tap a bar to narrow the table to its signals; tap more bars to add
  them; *Clear chart filter* resets.
- **Signal table**: swipe sideways for more columns; tap a row for the chart overlay. The
  same chart and the signal details stay below the table.
- **Signal chart** works like TradingView (it is drawn with TradingView's Lightweight Charts):
  - **pinch** (or the mouse wheel) to zoom, **drag** sideways to move through time;
  - **drag the price axis** up or down to stretch or squeeze prices; **double-tap an axis** to
    reset that axis;
  - buttons under the chart: **－ / ＋** zoom, **⟲ Reset** shows everything again with automatic
    price scaling, **◎ Signal** jumps to the signal bar;
  - the line above the chart shows date, open / high / low / close, EMAs and the indicator
    values of the bar under your finger (the signal bar otherwise);
  - level labels sit on the price axis: `TRIG` trigger, `STOP`, `W4` wave-4 end,
    `F.500` … `F.854` Fibonacci levels, `T0.618` … `T2.618` wave-5 (EW5) or wave-3 (EW3)
    targets, `R.382` … `R.786` wave-2 retracements, `W0` / `W1` wave starts and ends;
  - the legend under the chart hides or shows a series when tapped;
  - **Chart timeframe** buttons (60m · 4hr · 1D) above the chart show the same signal on
    another timeframe; the signal's own one is marked *signal* and is where every newly opened
    signal starts. The overlay and the chart under the table switch separately.
  - under the price: **RSI with the histogram** bars (beyond ±20) in one pane and **DTosc K / D**
    in the next, each on 0-100 with the 30 / 50 / 70 lines (the desktop shows all four in one pane).
  The content is the desktop chart's: same candles, EMAs, wave count, levels, markers and
  indicator values.
- **Back button** closes an open overlay or list first.
- **Share results CSV** (Run tab) sends a results file to any app.

### What is different from the desktop

| | Desktop | Phone |
|---|---|---|
| Signal chart | Plotly | TradingView Lightweight Charts (pinch zoom, pan, axis scaling); same content; RSI + histogram and DTosc K / D in two panes |
| Price download | yfinance | Yahoo's chart API directly (same data; yfinance cannot run on Android) |
| Indicators | TA-Lib | `core/ta_lite.py`: the same formulas in numpy, checked against TA-Lib on all stored series |
| stock.csv | one file | 16 part files of the same format, so the phone never holds every ticker in memory |
| pandas / numpy | 3.x / 2.x | 2.1.3 / 1.26.2 (the versions built for Android); results checked identical |

Signals, levels, outcomes, alignment and every stat are identical to the desktop on the same
data. The only known difference is DTosc K / D on a perfectly flat price stretch, where both
versions divide zero by zero.

### Storage and battery

- About 250 MB of storage for all tickers, plus results files.
- Memory stays around 0.6 GB during a run (one group of about 15 tickers at a time).
- A long job keeps the phone awake through a notification. It ends by itself when the job
  is finished.
