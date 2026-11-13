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
- **Light / dark**: the button under the title switches the whole app, charts included; the
  choice is remembered.
- **Breakdown charts**: tap a bar to narrow the table to its signals; tap more bars to add
  them; *Clear chart filter* resets. These charts do not zoom, so they cannot get stuck in a
  zoomed view; the signal chart below is the one to zoom.
- **Signal table**: swipe sideways for more columns; tap a row to show its chart and details
  below the table (scroll down). **Open chart overlay** shows the same chart full screen.
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

### Alerts (scheduled scans and notifications)

The **Alerts** tab runs the scanner by itself and tells you what happened today, with the app
closed and the screen off.

At each time you set (default **12:30 and 15:45, Monday to Friday**):

1. the latest data is downloaded (the same incremental update as the Data tab);
2. EW5 and EW3 run over the last few days (default 10) with the normal settings and
   higher-timeframe alignment;
3. one notification lists every stock of the day:
   - **Triggered**: the close crossed the TRIGGER level today;
   - **New setup**: the setup appeared today.

The second scan of the day only notifies stocks that are new since the first; the
notification always lists the whole day, triggers first. Tap it to open the Alerts tab; tap
a row there to open that stock in its EW5 / EW3 tab, scrolled to its chart. The scans' results are also in the EW5 / EW3 tabs as
`backtest_auto_…` files (the newest four of each are kept).

Settings: days, times (add or remove), whether to download first, EW5 / EW3, timeframes,
what to be notified about, *only ALIGNED* signals, and how many days back a setup may still
trigger today. **Run now** starts a scan at once; **Test notification** shows what an alert
looks like.

**Telegram (optional, off by default).** Switch *Telegram* to **On** to also get the day's
list in a Telegram chat, with trigger and stop for each stock:

1. In Telegram open **@BotFather**, send `/newbot` and follow the steps: it gives you a
   **bot token**.
2. Open your new bot and send it any message.
3. In the Alerts tab paste the token, press **Find my chat ID** and tap your chat, then
   **Send test to Telegram**, then **Save**.

The token is kept in the app's private storage and is never shown again (leave the field
empty to keep it). For a group, add the bot to the group, write a message there and pick the
group's chat ID. The phone notification is sent either way.

**Message layout** (under Telegram) sets what the message says: a header line and one line
per stock, written with placeholders such as `{icon} {ticker} {side}`, `{trigger}`, `{stop}`,
`{target1}`, `{risk_pct}`, `{alignment}` or `{tradingview}` (a chart link). Tap a placeholder
to insert it, **Preview** to see the message with today's stocks (or two examples), and
**Default layout** to start again. `<b>`, `<i>`, `<code>` and links work as in Telegram.

**Scans while the phone is locked.** Scans are set as alarm-clock alarms (you will see the
alarm icon in the status bar), which phones keep even in deep sleep. The tab checks the
phone settings that can still stop them and offers an **Allow** button for each:
notifications, exact alarms, battery optimisation, background data (Data Saver), and on
Xiaomi, Oppo, Vivo, Huawei and similar phones the maker's **auto-start** switch. On those
phones also set the app's battery use to *No restrictions* (Samsung: take it out of
*Sleeping apps*), and don't swipe the app away from recent apps. **Test in 2 min** sets a
one-off scan: lock the phone and the notification should arrive a few minutes later. The
**Scheduler log** shows when alarms were set and when they fired. Scans are set again after
a restart or an app update.

A daily (1D) signal found at 12:30 is based on the day's unfinished bar; it can still change
by the close. The 15:45 scan sees the finished day.

### What is different from the desktop

| | Desktop | Phone |
|---|---|---|
| Signal chart | Plotly | TradingView Lightweight Charts (pinch zoom, pan, axis scaling); same content; RSI + histogram and DTosc K / D in two panes |
| Price download | yfinance | Yahoo's chart API directly (same data; yfinance cannot run on Android) |
| Indicators | TA-Lib | `core/ta_lite.py`: the same formulas in numpy, checked against TA-Lib on all stored series |
| stock.csv | one file | 16 part files of the same format, so the phone never holds every ticker in memory |
| pandas / numpy | 3.x / 2.x | 2.1.3 / 1.26.2 (the versions built for Android); results checked identical |

Signals, levels, outcomes, alignment and every stat are identical to the desktop on the same
data and the same run settings: a backtest of 11 May to 11 Nov 2026 gives 3,100 EW5 and 1,574
EW3 signals on both, signal for signal. Compare runs with the same dates: the Run / Backtest
tab's default window is the last 365 days, and each dashboard shows the dates of the file it
displays under the file name. The only known difference is DTosc K / D on a perfectly flat price stretch, where both
versions divide zero by zero.

### Storage and battery

- About 250 MB of storage for all tickers, plus results files.
- Memory stays around 0.6 GB during a run (one group of about 15 tickers at a time).
- A long job keeps the phone awake through a notification. It ends by itself when the job
  is finished.
