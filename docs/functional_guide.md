> This guide covers the three building blocks of the app:
>
> 1. **EW5** – wave 5 reversal (described first).
> 2. **EW3** – wave 2 finished / wave 3 starting (its own section further down).
> 3. **Higher-timeframe alignment** – a tag on every EW5 and EW3 signal that says whether the
>    bigger timeframes agree with the trade (section "Trading with the higher timeframe").
>
> The data, timeframes, degrees, indicators and backtest ideas apply to both screeners.

## The three pieces at a glance

| | EW5 tab | EW3 tab |
|---|---|---|
| Looks for | The **end** of a five-wave move | The **start of wave 3** (waves 1 and 2 done) |
| Trades | Against the move that is ending | With the move that is starting |
| Side column | `reversal_side` | `trade_side` |
| Stop level | Wave-5 end | Wave-2 end |
| First / second target card | W4 end / FIB 0.5 | W1 end / W3 1.618 |
| Fails when | Wave 5 extends (`EXTENDED`) | Wave-2 end breaks (`FAILED`) |

On top of both sits the **higher-timeframe alignment**: each signal is marked ALIGNED, MIXED or
AGAINST from the trend of the timeframes above it (60m → 4hr → 1D → 1W). It is a filter and a
column in both tabs, not a third screener.

## What this app looks for

Elliott Wave theory says a trend unfolds in **five waves** (1-2-3-4-5) and is then corrected in
three (a-b-c). Wave 5 is the last push of the trend. This app finds stocks, indices and
commodities whose latest valid impulse is **at or just past wave 5**, and gives you the price
levels needed to judge a **reversal against that trend**.

| Impulse found | What it means | Reversal side shown |
|---|---|---|
| BULLISH (five waves up) | The up-move may be ending | **SHORT** |
| BEARISH (five waves down) | The down-move may be ending | **LONG** |

> This is a screening and study tool. It shows what the wave count says and what happened after
> similar signals in the past. It does not tell you what to trade, how much, or when. Position
> size, instrument choice and risk are your own decisions.

---

## Daily routine

1. **Data tab → Update data** after the market closes (or any time; today's unfinished bar is
   replaced on the next update). Only the last *N* days are downloaded. A ticker you added to
   `data/tickers.csv` gets its full history automatically.
   Weekly bars are rebuilt from the daily ones in the same step.
2. **Run / Backtest tab → pick EW5 → Live screen → Run**, then the same for **EW3**. This lists
   every ticker sitting at wave 5, and every ticker whose wave 2 has just finished.
3. **EW5 tab and EW3 tab.** Set the **HTF alignment** filter to ALIGNED (add MIXED if the list
   is too short), then filter the rest, click a row and read the chart.
4. Read the **Higher timeframes** line above the chart before anything else. AGAINST means the
   next timeframe up is moving the other way.
5. From time to time, run a **Walk-forward backtest** for each screener to see how these signals
   behaved on your own universe, and compare the alignment groups in the breakdown.

---

## Reading a signal

### Stage

- **WAVE5_IN_PROGRESS** – the wave-5 extreme is the most recent swing. Nothing has confirmed a
  turn yet; wave 5 can still extend. This is the early list.
- **WAVE5_COMPLETED** – a swing against wave 5 has been confirmed (wave *a* has started), the
  correction is not finished and the 0.854 retracement is not broken. This is the later, more
  confirmed list.

### Degree (ZigZag length)

The degree is the **size of swing** the engine counts. A ZigZag length of *N* means a high or
low only counts as a pivot when it stands out from the *N* bars before it. A bigger length
ignores small wiggles and counts only large waves.

| Length | Degree | What it counts | Signals | Typical target distance |
|---|---|---|---|---|
| 4 | **minor** | Small swings of a few bars | Many | Small |
| 8 | **intermediate** | Swing-sized moves of one to several weeks | Fewer | Medium |
| 16 | **major** | Large trend legs lasting months | Rare | Large; needs ~500 bars of history |

The same degree means a different amount of time on each timeframe, because one 1D bar is a
day, one 4hr bar is half a day and one 60m bar is an hour (seven per NSE session):

| | minor (4) | intermediate (8) | major (16) |
|---|---|---|---|
| **60m** | swings inside one to two days | swings of a few days | swings of one to two weeks |
| **4hr** | swings of a few days | swings of one to two weeks | swings of several weeks |
| **1D** | swings of one to two weeks | swings of several weeks | swings of months |

**60m** is the fastest view. Use it for timing an entry inside a 4hr or 1D signal you already
like, or for very short holds. It has the most signals and the most noise, and 60m history
only goes back about two years.

How to use the three together:

- **Major** tells you where the big trend is in its life. Use it as the background, not as a
  short-term trigger. A major wave 5 that is completing is the context in which smaller
  reversal signals deserve more attention.
- **Intermediate** is the working degree for swing-sized moves.
- **Minor** gives the earliest and most frequent signals, with the smallest objectives and the
  most noise. It is most useful when it agrees with the degree above it.
- **Agreement matters more than any single degree.** A SHORT on 4hr minor while 1D intermediate
  is also at wave 5 of a bullish impulse is one story told twice. A minor signal against a
  young higher-degree trend is usually just a pause.

#### Which degree fits an F&O holding period under two weeks

Two weeks is about **10 daily bars, 20 4hr bars or 70 60m bars**. The move you are waiting for (TRIGGER to
W4_END) has to fit inside that window, so the degree should be chosen by how long its
corrections normally take.

Measured on this app's own universe (walk-forward backtest, Nov 2025 to Sep 2026, 1,651
signals, stage WAVE5_IN_PROGRESS, 30-bar horizon). For triggered signals that reached W4_END:

| Timeframe · degree | Bars to reach W4_END (median / 75% within) | In calendar terms | Median distance entry → W4_END | Median distance entry → STOP |
|---|---|---|---|---|
| 4hr · minor | 2 / 6 bars | 1 to 3 trading days | 2.5% | 2.8% |
| 4hr · intermediate | 4.5 / 10 bars | 2 to 5 trading days | 3.4% | 2.8% |
| 4hr · major | 8 / 16 bars | 4 to 8 trading days | 5.5% | 2.8% |
| 1D · minor | 2 / 7 bars | 2 to 7 trading days | 3.4% | 3.8% |
| 1D · intermediate | 3 / 8 bars | 3 to 8 trading days | 5.3% | 3.6% |
| 1D · major | 3.5 / 8 bars | 4 to 8 trading days | 5.9% | 3.7% |

Reading it for a holding period under two weeks:

- **4hr intermediate and 1D minor are the natural fit.** Their corrections are sized for a
  one-to-two-week swing, most of the ones that worked finished within about a week, and the
  objective is at least as far away as the stop.
- **4hr minor** resolves fastest (often within three days) but the objective is small, about
  the same size as the stop. It suits very short holds and is the noisiest.
- **1D intermediate** offers a larger objective for a similar stop distance, and in this sample
  usually still finished inside eight trading days. It is the upper end of what fits.
- **Major** (either timeframe) is best treated as direction and context. Its full correction
  can take longer than a short-dated contract allows, and there are few signals.

On **60m**, the degree that matches a one-to-two-week swing is **major** (length 16); 60m minor
and intermediate are intraday to few-day moves. The table above was measured before 60m was
enabled, so run your own 60m backtest for comparable numbers.

A practical setup for this kind of holding period: run the screen with lengths **4 and 8**, keep
**16** switched on only to see the bigger picture, and set `horizon_bars` to **10 for 1D**,
**20 for 4hr** or **70 for 60m** when you backtest, so the statistics describe a two-week hold and not a six-week one.

These numbers come from one period and one universe. They describe what happened, not what
will happen; re-run the backtest on your own dates before relying on them.

### The levels

| Level | Meaning | How it is read |
|---|---|---|
| **W5_END / STOP** | The wave-5 extreme | If price goes beyond it, wave 5 has extended and the reversal idea is invalid. It is the natural invalidation level. |
| **TRIGGER** | Low (bullish impulse) or high (bearish impulse) of the wave-5 bar | A **close** beyond it is the first evidence that the turn has started. The backtest treats this close as the entry. |
| **W4_END** | End of wave 4 | The classic first objective of a post-wave-5 correction. |
| **FIB 0.500 / 0.618 / 0.764 / 0.854** | Retracement of the whole impulse (wave 0 → wave 5) | Deeper objectives. A break of 0.854 means the move is no longer a correction, and the signal is dropped. |
| **W5_TGT 0.618 / 1.000 / 1.618 × W1** | Where wave 5 would end if it equalled those multiples of wave 1 | Maturity check: a wave 5 that has not yet reached 0.618 × W1 is young and more likely to extend. |

Related columns:

- **w5_vs_w1** – actual length of wave 5 relative to wave 1. Use the `min_w5_vs_w1` input
  (e.g. 0.618) to skip immature fifth waves.
- **bars_since_w5** – how fresh the wave-5 extreme is. Use `max_bars_since_w5` to keep only recent ones.
- **live_count** – the provisional leg counter of the engine (`~(3)`, `~(A)` …), for orientation only.

### EMA 13 and EMA 55 on the chart (make-or-break)

The two moving averages are drawn on the chart only as a visual aid. They are not used by the
wave engine.

- **EMA 13** (yellow) follows price closely. While wave 5 is running, price normally stays on
  the trend side of it. The first close across EMA 13 often comes together with the TRIGGER.
- **EMA 55** (magenta) is the slower, larger-trend line. It is the **make-or-break level**: a
  correction that stops at EMA 55 is still just a pullback in the trend, while a decisive close
  through it says the larger trend is giving way.
- **EMA 13 crossing EMA 55** after a completed wave 5 is late but strong confirmation.

Compare EMA 55 with the W4_END and Fib levels: when they sit close together, that zone matters more.

### Chart timeframe switch

Above the signal chart, **Chart timeframe** (60m · 4hr · 1D) shows the same signal on another
timeframe. The chart opens on the signal's own timeframe, marked *(signal)*. Switch to a higher
one to see where the setup sits in the bigger move, for example a 60m wave-5 reversal against
the daily trend and its EMA 55.

On another timeframe:

- the **levels** (trigger, stop, wave ends, Fibonacci levels, targets) are the same prices;
- the **signal bar** is the bar that contains it (on a lower timeframe: the last bar before
  the signal bar closed);
- **wave points** and **entry / stop / target markers** move to the bar that contains them
  (on a lower timeframe: the bar with the nearest high / low);
- the shaded **evaluation window** covers the same span of time as on the signal's timeframe;
- the **indicator pane** shows that timeframe's own RSI and DTosc.

60m history is about two years, so a daily signal older than that has no 60m chart.
Add `"1W"` to `chart.timeframes` in `config.yaml` for a weekly button.

### Indicator columns in the table

`rsi`, `dtosck` / `dtoscd` (DT oscillator: stochastic of RSI, fast and slow lines),
`histogram` (RSI − 50), `13_ema`, `21_ema`, `55_ema`, `atr14`, `cci` are the values **on the
signal bar**. They are for your own filtering and are not part of the signal logic. Common
readings: RSI above 70 or below 30 at wave 5 (stretched), a DT oscillator cross in the
overbought/oversold zone (momentum turning), and ATR as a measure of how far price normally
moves in one bar.

---

## Thinking about it in F&O terms

The app works on the cash/spot price. If you study F&O trades from it, these are the links:

- **Risk per lot.** Distance from TRIGGER (or your entry) to STOP, multiplied by the contract's
  lot size, is the loss per lot if the idea fails. Lot sizes are not stored in the app; take
  them from the exchange.
- **Reward to risk.** Distance from entry to W4_END (first objective) divided by distance from
  entry to STOP. The dashboard's hit rates tell you how often W4_END and FIB 0.5 were actually
  reached in the backtest.
- **Timeframe and expiry.** `horizon_bars` is how long a signal is followed (30 bars = about six
  weeks on 1D, about three weeks on 4hr, about four trading days on 60m). A view that needs weeks to play out does not fit a
  contract expiring in days.
- **Futures vs options.** A futures position has linear profit and loss and can gap through the
  STOP level. A bought option limits the loss to the premium but loses value with time, so a
  correct direction that takes too long can still lose. Defined-risk spreads sit in between.
- **Indices first.** Check `^NSEI` and `^NSEBANK` and the sector index of the stock. A stock
  signal against a strong index trend has the market working against it.
- **Volatility.** `^INDIAVIX` and `atr14` show how wide normal moves are. A STOP closer than one
  ATR is easily hit by noise.
- **Events.** Results, policy days and expiry days can override any wave count.

---

## Reading the backtest

A backtest replays every bar between your start and end date using only the data known at that
bar (no look-ahead), then follows each signal for `horizon_bars`.

| Number | Meaning |
|---|---|
| **Trigger rate** | Share of signals where price closed beyond TRIGGER before wave 5 extended |
| **Extended** | Share where price went beyond W5_END first: wave 5 was not finished |
| **W4 target hit / FIB 0.5 hit** | Of the triggered signals, how many reached that level |
| **Stop rate** | Of the triggered signals, how many later went back beyond W5_END |
| **Avg MFE / MAE** | Average best and worst move (in %) after entry |

Status and result per signal:

- `NOT_TRIGGERED` – neither trigger nor extension inside the horizon.
- `EXTENDED` – wave 5 made a new extreme before the trigger.
- `TRIGGERED` – then `TARGET_HIT`, `TARGET_HIT_THEN_STOPPED`, `STOPPED` or `OPEN`.

Things to keep in mind:

- A high **Extended** share is normal for `WAVE5_IN_PROGRESS`: you are looking before
  confirmation. Compare it with a run that includes only `WAVE5_COMPLETED`.
- When the stop and a target fall in the same bar, the stop is counted first (conservative).
- Costs, slippage, lot sizes and option pricing are **not** modelled.
- A handful of signals is not a statistic. Look at the signal count before trusting a percentage.
- Past behaviour of a pattern does not guarantee its future behaviour.

---

## EW3: wave 2 finished, wave 3 starting

EW5 looks for the **end** of a trend. EW3 looks for the **start of the strongest part** of a new
one. In Elliott Wave terms, wave 1 is the first push, wave 2 pulls back against it without
breaking the start of wave 1, and wave 3 is usually the longest and fastest leg. "Wave 2
finished" and "wave 3 starting" are the same moment, so this is one screener.

| Waves 1-2 found | Side shown |
|---|---|
| BULLISH (up, then a pullback that holds) | **LONG** |
| BEARISH (down, then a bounce that fails) | **SHORT** |

EW3 trades **with** the new move, where EW5 trades against the old one. It uses the same
ZigZag swings as EW5, so degrees and timeframes mean the same thing in both tabs.

### What counts as a setup

- Wave 2 must retrace wave 1 by **38.2% to 78.6%** (adjustable on the Run tab) and must never
  pass the start of wave 1.
- Price must not have gone beyond the wave-2 end since that pivot formed.
- The setup ends by itself when the next swing in the trend direction is confirmed (wave 3 has
  printed) or when the wave-2 end is broken.

### Context: where the 0-1-2 sits

| Context | Meaning | Reading |
|---|---|---|
| **AFTER_WAVE5** | Wave 1 starts exactly where a completed wave 5 ended | The reversal that EW5 flagged, one step later: first leg done, pullback done |
| **AFTER_ABC** | Wave 1 starts where an a-b-c correction ended | The old trend resuming after its correction |
| **OTHER** | Any other three swings | No structure behind it; about ten times as many signals |

The first two are switched on by default. Add OTHER on the Run tab only if you want the wide net.

### Stage

- **WAVE2_COMPLETED** – the wave-2 pivot is confirmed but price has not closed beyond the
  wave-1 end. Early: better entry distance, less proof.
- **WAVE3_CONFIRMED** – price has closed beyond the wave-1 end. Later: wave 3 is visibly under
  way, but part of the move is gone and the stop is further away.

### The levels

| Level | Meaning | How it is read |
|---|---|---|
| **W0_START** | Start of wave 1 | Hard invalidation. If price passes it, this was not a wave 2. |
| **W1_END** | End of wave 1 | First objective, and the level whose break confirms wave 3. |
| **W2_END / STOP** | End of wave 2 | If price goes back beyond it, wave 2 was not finished. The backtest uses it as the stop. |
| **TRIGGER** | High (LONG) or low (SHORT) of the wave-2 bar | A **close** beyond it is the first evidence that wave 2 is over. The backtest enters on that close. |
| **W2_RET 0.382 / 0.500 / 0.618 / 0.786** | Retracement levels of wave 1 | Show how deep wave 2 went. Deeper pullbacks give a closer stop relative to the targets. |
| **W3_TGT 1.000 / 1.618 / 2.618 × W1** | Wave 3 projected from the wave-2 end | 1.618 is the classic wave-3 objective; 1.000 is the minimum normally expected. |

Columns worth using: **w2_retrace** (depth of wave 2; filter with the range slider),
**bars_since_w2** (freshness) and **context**.

### Reading the EW3 stats

| Number | Meaning |
|---|---|
| **Trigger rate** | Share of signals where price closed beyond TRIGGER before breaking the wave-2 end |
| **Failed** | Share where price went beyond the wave-2 end first: wave 2 was not finished |
| **W1 end hit / W3 1.618 hit** | Of the triggered signals, how many reached that level |
| **Stop rate** | Of the triggered signals, how many later went back beyond the wave-2 end |

A target that price has already passed when the trigger fires (common for WAVE3_CONFIRMED)
counts as hit at entry.

### Using EW5 and EW3 together

- An **EW5** signal says a move may be ending. If it triggers and pulls back without breaking
  the wave-5 end, the same stock can later appear in **EW3** with context AFTER_WAVE5. That is
  the second, more confirmed entry into the same reversal.
- **EW3 with AFTER_ABC** is a trend-continuation idea and has no EW5 counterpart.
- Both tabs carry the same **HTF alignment** column, so an EW5 reversal and the EW3 follow-up
  can be judged against the same bigger picture.
- On the 60m timeframe EW3 produces many signals. The degree and two-week guidance above
  applies in the same way: pick the degree whose swings match your holding period.

On this app's universe (six months to 11 Nov 2026, all three timeframes, default settings) EW3
gave 1,574 signals: 54% triggered, 45% failed first, and of the triggered ones 52% reached the
wave-1 end and 11% the 1.618 target, with 65% stopped at some point. EW5 over the same period
gave 3,100 signals: 59% triggered, 41% extended first, and of the triggered ones 53% reached
the wave-4 end and 35% FIB 0.5, with 55% stopped at some point. Treat these as a
description of one period, not a forecast.

---

## Stock lists and attributes

`data/tickers.csv` has, for every stock: `marketcapname` (Large / Mid / Small Cap),
`cnx_sector_name`, `fno_enabled`, `macro_info` (macro sector) and `sector_info` (sector index).

- **Data update** (sidebar) and **Run / Backtest** can use *All stocks* or *F&O stocks* only
  (`fno_enabled = true`); indices and commodities are always included. The dashboard caption
  shows which list a run used.
- **EW5 / EW3 tabs**: the **Filters** section (closed by default; its title lists the filters
  that are on) holds the Elliott Wave filters and the five stock-attribute filters together,
  all saved with *Save filters*. Below it, **Charts by stock attribute** (also closed) shows the
  signals by market cap, F&O and macro sector.
- **Drill-down**: a clicked bar keeps only those signals for everything below it. The
  attribute charts narrow the next attribute charts, the KPI cards, the breakdown charts and
  the table; each breakdown chart narrows the ones after it and the table. *Clear chart
  filter* starts again.

## Scheduled scans on this Mac (Alerts tab)

The **Alerts** tab runs scans by itself, like the phone app: usual times (default 12:30 and
15:45, Monday to Friday) for F&O stocks and a weekly full scan of every stock (default Friday
18:00). Each scan downloads the latest data, runs EW5 and EW3 over the last few days, saves the
results as `backtest_auto_…` files and notifies the stocks triggered or set up today
(Telegram optional, same message layout as the phone).

**Messages**: *Separate* (the default) sends one notification, and one Telegram message, for
stocks **triggered** today and another for **new setups**, each only when it has something new.
*One message for the day* puts both in one. To keep only one category, leave the other out of
**Notify about**.

**Message layout**: *Cards* (a short block per stock, the default), *Compact* (one line per
stock) or *Custom* (your own template). Stocks new since the last scan come first, then those
already sent today under *Earlier today*; each in the order 60m → 4hr → 1D, aligned first.

Press **Install schedule** to hand the times to macOS (two launch agents in
`~/Library/LaunchAgents/com.ewscanner.scan.*`); **Remove schedule** takes them out again. The
Mac must be on; a scan missed while it slept runs when it wakes. **Run … scan now** starts one
in the background. From a terminal: `python scheduled_scan.py --kind regular` (or `full`).

## Trading with the higher timeframe

The expensive mistake is a trade that looks right on a small chart while the bigger chart is
moving the other way: a LONG on 60m inside a 4hr and daily downtrend. To make that visible,
every signal is tagged with the trend of the timeframes above it.

| Signal timeframe | Parent | Grandparent |
|---|---|---|
| 60m | 4hr | 1D |
| 4hr | 1D | 1W |
| 1D | 1W | none |

Weekly (1W) bars are built from the stored daily bars, so nothing extra is downloaded.

**Trend of a higher-timeframe bar** (from the DT oscillator in the indicator pane):

- **BULLISH**: DTosc K above DTosc D.
- **BEARISH**: DTosc K below DTosc D.
- **NEUTRAL**: K equal to D (rare).

(Before November 2026 the trend came from EMA 13 / 55. Results saved with that rule are
re-tagged with the DTosc rule the first time they are opened.)

**Alignment of the signal:**

| Alignment | Meaning |
|---|---|
| **ALIGNED** | Every higher timeframe points the way of the trade (LONG with bullish, SHORT with bearish). |
| **MIXED** | The parent is neutral, or parent and grandparent disagree. |
| **AGAINST** | The parent points the other way. This is the lower-timeframe-bullish, higher-timeframe-bearish trap. |
| **UNKNOWN** | No higher timeframe, or not enough history for its DT oscillator yet. |

A signal only reads a higher-timeframe bar that had already **finished** when the signal bar
closed, so the backtest never sees the future.

### Where to find it

- **Signal table**: the `alignment` column sits next to the side (green, amber, red);
  `htf1_trend` (parent) and `htf2_trend` (grandparent) are at the end of the table.
- **HTF alignment filter** at the top of each dashboard. Pick ALIGNED and press *Save filters*
  to make it your default view.
- **Results by higher-timeframe alignment** chart and table under the breakdown charts: stop
  rate, target hit rates, MFE and MAE for each group. Click a bar to see its signals.
- **Run / Backtest**: *Keep only signals aligned with the higher timeframes* drops everything
  else before the file is saved. Leave it off if you want to compare the groups.

### How to use it as a plan

| Alignment | Suggested handling |
|---|---|
| ALIGNED | The setup to study first. All targets are reasonable to consider. |
| MIXED | Smaller objective (first target), or wait for the parent to pick a side. |
| AGAINST | Skip, or treat as a short counter-trend scalp at most. |

**In EW5 and in EW3 the tag is read the same way, but it means something different:**

- **EW5 (counter-trend).** Most EW5 signals are AGAINST, because a five-wave rise on 60m
  normally sits inside a rising 4hr chart. An ALIGNED EW5 signal is the special case where the
  small impulse was only a bounce inside a bigger opposite trend, so the reversal takes you
  back into that trend. An AGAINST EW5 signal is a top or bottom call against every timeframe.
- **EW3 (with-trend).** EW3 already trades in the direction of its own new move. ALIGNED means
  the higher timeframes are moving that way too, typical for context AFTER_ABC (an old trend
  resuming). AGAINST is common for context AFTER_WAVE5, where the reversal is still young and
  the higher timeframes have not turned yet.

### What the backtest says (11 May to 11 Nov 2026, all tickers, default settings)

| | Signals | Stop rate | Target 1 hit | Target 2 hit | Avg MAE |
|---|---|---|---|---|---|
| EW5 ALIGNED | 411 | 50.8% | 47.5% | 23.4% | 2.0% |
| EW5 MIXED | 998 | 55.3% | 53.0% | 31.9% | 1.5% |
| EW5 AGAINST | 1,691 | 55.5% | 54.2% | 38.8% | 1.7% |
| EW3 ALIGNED | 509 | 60.4% | 55.1% | 8.1% | 1.8% |
| EW3 MIXED | 467 | 68.6% | 53.1% | 14.7% | 1.4% |
| EW3 AGAINST | 598 | 67.3% | 49.4% | 10.5% | 1.7% |

Rates are out of triggered signals. Targets are W4 end and FIB 0.5 for EW5, W1 end and
W3 1.618 for EW3.

Read this honestly (DTosc rule):

- **EW3**: ALIGNED is the better group. It is stopped less often (60% against 67% when
  AGAINST) and reaches the wave-1 end more often (55% against 49%).
- **EW5**: ALIGNED is stopped a little less often (51% against 56%) but reaches the targets
  *less* often (FIB 0.5: 23% against 39%). EW5 is a reversal; when the bigger timeframe's
  oscillator already points the trade's way, part of the move has often happened.
- The stop is still hit about half the time or more in every group. The loss on a single
  trade is set by the stop distance and position size; the alignment tag is a reason to
  prefer one setup over another, not a replacement for a stop.
- Six months is one market phase. Rerun the backtest over other periods, and compare the
  groups with the breakdown chart, before relying on it.

---

## Good habits with this tool

- Click through the charts. The wave labels show exactly what the engine counted; if the count
  looks forced to you, skip the signal.
- Use the filters: timeframe, degree, side, HTF alignment, stage, and the range slider
  (`w5_vs_w1` in EW5, `w2_retrace` in EW3).
- Check the alignment before the wave count. A clean count against the higher timeframe is
  still a trade against the higher timeframe.
- Tickers flagged **short history** (fewer than 500 bars) give unreliable major-degree counts.
- After a split or bonus issue, run **Full re-download** so old prices are adjusted.
