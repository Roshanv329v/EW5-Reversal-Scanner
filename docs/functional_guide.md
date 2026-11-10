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
2. **Run / Backtest tab → Live screen → Run.** This lists every ticker sitting at wave 5 right now.
3. **Dashboard tab.** Filter the table, click a row, read the chart.
4. From time to time, run a **Walk-forward backtest** to see how these signals behaved on your
   own universe.

---

## Reading a signal

### Stage

- **WAVE5_IN_PROGRESS** – the wave-5 extreme is the most recent swing. Nothing has confirmed a
  turn yet; wave 5 can still extend. This is the early list.
- **WAVE5_COMPLETED** – a swing against wave 5 has been confirmed (wave *a* has started), the
  correction is not finished and the 0.854 retracement is not broken. This is the later, more
  confirmed list.

### Degree (ZigZag length)

| Length | Degree | Typical use |
|---|---|---|
| 4 | minor | Short swings, frequent signals, more noise |
| 8 | intermediate | Swing-sized moves |
| 16 | major | Large trend turns, few signals; needs ~500 bars of history |

A signal that appears on **both 1D and 4hr**, or on two degrees at once, has more structure
behind it than a lone minor-degree signal.

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
  weeks on 1D, about three weeks on 4hr). A view that needs weeks to play out does not fit a
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

## Good habits with this tool

- Click through the charts. The wave labels show exactly what the engine counted; if the count
  looks forced to you, skip the signal.
- Use the filters: timeframe, degree, side, stage, `w5_vs_w1` range.
- Tickers flagged **short history** (fewer than 500 bars) give unreliable major-degree counts.
- After a split or bonus issue, run **Full re-download** so old prices are adjusted.
