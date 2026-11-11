"""
elliott_wave3_screener.py
=========================

Wave 2 finished / wave 3 starting, built on the SAME ZigZag as the wave-5 screener.

It drives `ElliottWaveEngine` from elliott_wave5_screener.py bar by bar (that file is
not modified) and reads the three latest ZigZag points:

    0 = start of wave 1      1 = end of wave 1      2 = end of wave 2 (latest pivot)

A setup exists on bar t when
    * wave 1 moved away from point 0 and wave 2 retraced it by
      min_retrace .. max_retrace (max_retrace < 1, so point 0 is never broken),
    * price has not gone beyond the wave-2 end since that pivot.
It ends by itself when the next opposite pivot is confirmed (wave 3 has printed) or
when the wave-2 extreme is broken. Everything a bar sees uses that bar and earlier
bars only (the wave-2 pivot is confirmed one bar after it forms, as in the engine).

Stage    WAVE2_COMPLETED  - wave-2 pivot confirmed, no close beyond the wave-1 end yet
         WAVE3_CONFIRMED  - a close beyond the wave-1 end since the wave-2 pivot
Context  AFTER_WAVE5      - point 0 is the end of the engine's latest impulse (wave 5):
                            the first leg and pullback of a reversal
         AFTER_ABC        - point 0 is the end of the a-b-c correction of that impulse:
                            a new impulse in the old trend direction
         OTHER            - any other 0-1-2

Public API (mirrors the wave-5 screener)
    screen_wave3(df, as_of=None, ...)      -> signals DataFrame
    backtest_wave3(df, start, end, ...)    -> signals + forward outcome
    evaluate_signals(signals, df, ...)     -> adds forward outcome columns
    summarize_backtest(results)            -> hit-rate summary
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from elliott_wave5_screener import DEFAULT_LENGTHS, DEGREE_NAMES, ElliottWaveEngine, _prepare

STAGE_W2_COMPLETED = "WAVE2_COMPLETED"
STAGE_W3_CONFIRMED = "WAVE3_CONFIRMED"
STAGES: tuple[str, ...] = (STAGE_W2_COMPLETED, STAGE_W3_CONFIRMED)

CONTEXT_AFTER_WAVE5 = "AFTER_WAVE5"
CONTEXT_AFTER_ABC = "AFTER_ABC"
CONTEXT_OTHER = "OTHER"
CONTEXTS: tuple[str, ...] = (CONTEXT_AFTER_WAVE5, CONTEXT_AFTER_ABC, CONTEXT_OTHER)
DEFAULT_CONTEXTS: tuple[str, ...] = (CONTEXT_AFTER_WAVE5, CONTEXT_AFTER_ABC)

DEFAULT_MIN_RETRACE = 0.382
DEFAULT_MAX_RETRACE = 0.786
RETRACE_LEVELS: tuple[float, ...] = (0.382, 0.500, 0.618, 0.786)
TARGET_MULTIPLES: tuple[float, ...] = (1.000, 1.618, 2.618)

# Order of the wave_levels list (always the same, so it explodes into stable columns)
LEVEL_NAMES: tuple[str, ...] = (
    "W0_START", "W1_END", "W2_END",
    "TRIGGER", "STOP",
    "W2_RET_0.382", "W2_RET_0.500", "W2_RET_0.618", "W2_RET_0.786",
    "W3_TGT_1.000xW1", "W3_TGT_1.618xW1", "W3_TGT_2.618xW1",
)
TARGETS: tuple[str, ...] = ("W1_END", "W3_TGT_1.000xW1", "W3_TGT_1.618xW1", "W3_TGT_2.618xW1")


def _r(v: float, nd: int = 2) -> float:
    return float(round(v, nd))


# ----------------------------------------------------------------------------------
# State at one bar
# ----------------------------------------------------------------------------------
def _snapshot(eng: ElliottWaveEngine, t: int, min_retrace: float, max_retrace: float) -> Optional[dict]:
    """The 0-1-2 setup as it stands with bar t as the last bar, or None."""
    zd, zx, zy = eng.zd, eng.zx, eng.zy
    if zd[0] == 0 or zd[1] != -zd[0] or zd[2] != zd[0]:      # need three real, alternating pivots
        return None
    d = -zd[0]                                               # +1: wave 3 up (latest pivot is a low)
    (x0, y0), (x1, y1), (x2, y2) = (zx[2], zy[2]), (zx[1], zy[1]), (zx[0], zy[0])
    w1 = (y1 - y0) * d
    if w1 <= 0 or not (x0 < x1 < x2):                        # each wave needs at least one bar
        return None
    retrace = (y1 - y2) * d / w1
    if not (min_retrace <= retrace <= max_retrace):
        return None

    after = slice(x2 + 1, t + 1)                             # bars since the wave-2 pivot
    if d == 1:
        if np.any(eng.L[after] < y2):                        # wave 2 made a lower low: not finished
            return None
        confirmed = bool(np.any(eng.C[after] > y1))
    else:
        if np.any(eng.H[after] > y2):
            return None
        confirmed = bool(np.any(eng.C[after] < y1))

    wave = eng.waves[0]
    context = CONTEXT_OTHER
    if not wave.empty:
        if wave.pts[5][0] == x0 and wave.dir == -d:
            context = CONTEXT_AFTER_WAVE5
        elif wave.c is not None and wave.c[0] == x0 and wave.dir == d:
            context = CONTEXT_AFTER_ABC

    return dict(dir=d, pts=[(x0, y0), (x1, y1), (x2, y2)], retrace=retrace,
                stage=STAGE_W3_CONFIRMED if confirmed else STAGE_W2_COMPLETED,
                context=context, live=eng.live.text)


def _qualifies(snap: Optional[dict], stages: Iterable[str], contexts: Iterable[str],
               max_bars_since_w2: Optional[int], t: int) -> bool:
    if snap is None or snap["stage"] not in stages or snap["context"] not in contexts:
        return False
    if max_bars_since_w2 is not None and t - snap["pts"][2][0] > max_bars_since_w2:
        return False
    return True


def _build_row(snap: dict, g: pd.DataFrame, t: int, ticker, tf, length, nd: int) -> dict:
    (x0, y0), (x1, y1), (x2, y2) = snap["pts"]
    d = snap["dir"]
    bull = d == 1
    w1 = abs(y1 - y0)
    trigger = float(g["high"].iat[x2] if bull else g["low"].iat[x2])   # break of the wave-2 bar
    levels = {"W0_START": y0, "W1_END": y1, "W2_END": y2, "TRIGGER": trigger, "STOP": y2}
    for ratio in RETRACE_LEVELS:
        levels[f"W2_RET_{ratio:.3f}"] = y1 - d * ratio * w1
    for multiple in TARGET_MULTIPLES:
        levels[f"W3_TGT_{multiple:.3f}xW1"] = y2 + d * multiple * w1
    times = g["time"]
    close = float(g["close"].iat[t])
    return {
        "Ticker": ticker,
        "time_frame": tf,
        "zigzag_length": length,
        "degree": DEGREE_NAMES.get(length, f"len{length}"),
        "signal_time": times.iat[t],
        "impulse": "BULLISH" if bull else "BEARISH",
        "trade_side": "LONG" if bull else "SHORT",
        "stage": snap["stage"],
        "context": snap["context"],
        "live_count": snap["live"],
        "close": _r(close, nd),
        "w0_time": times.iat[x0],
        "w1_end_time": times.iat[x1],
        "w2_end_time": times.iat[x2],
        "w2_end_price": _r(y2, nd),
        "bars_since_w2": int(t - x2),
        "w2_retrace": _r(snap["retrace"], 3),
        "w1_pct": _r(w1 / y0 * 100, 2) if y0 else np.nan,
        "dist_from_w2_pct": _r((close / y2 - 1) * 100, 2) if y2 else np.nan,
        "wave_key": f"{ticker}|{tf}|{length}|{x0}-{x1}",
        "wave_levels": [f"{k}={_r(levels[k], nd)}" for k in LEVEL_NAMES],
    }


_COLUMNS = ["Ticker", "time_frame", "zigzag_length", "degree", "signal_time", "impulse", "trade_side",
            "stage", "context", "live_count", "close", "w0_time", "w1_end_time", "w2_end_time",
            "w2_end_price", "bars_since_w2", "w2_retrace", "w1_pct", "dist_from_w2_pct", "wave_key",
            "wave_levels"]


def _finish(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_COLUMNS)
    out = pd.DataFrame(rows)
    return out.sort_values(["time_frame", "Ticker", "zigzag_length"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------
# Public: point-in-time screener
# ----------------------------------------------------------------------------------
def screen_wave3(
    df: pd.DataFrame,
    as_of=None,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    stages: Sequence[str] = (STAGE_W2_COMPLETED,),
    contexts: Sequence[str] = DEFAULT_CONTEXTS,
    min_retrace: float = DEFAULT_MIN_RETRACE,
    max_retrace: float = DEFAULT_MAX_RETRACE,
    max_bars_since_w2: Optional[int] = None,
    hi_source: str = "high",
    lo_source: str = "low",
    pivot_tie: str = "strict",
    min_bars: int = 120,
    decimals: int = 2,
) -> pd.DataFrame:
    """
    Tickers whose latest three swings form a finished wave 2 (wave 3 starting).

    as_of : None -> last bar of each ticker; timestamp -> only bars with time <= as_of.
    max_retrace must stay below 1.0: a wave 2 that passes the start of wave 1 is not a wave 2.
    """
    if not 0 < min_retrace <= max_retrace < 1:
        raise ValueError("Need 0 < min_retrace <= max_retrace < 1")
    data = _prepare(df)
    if as_of is not None:
        data = data[data["time"] <= pd.Timestamp(as_of)]

    rows = []
    for (ticker, tf), g in data.groupby(["ticker", "time_frame"], sort=False):
        g = g.reset_index(drop=True)
        if len(g) < min_bars:
            continue
        t = len(g) - 1
        for length in lengths:
            eng = ElliottWaveEngine(g["high"], g["low"], g["close"], length, hi_source, lo_source,
                                    open_=g["open"], pivot_tie=pivot_tie)
            for i in range(eng.n):
                eng.step(i)
            snap = _snapshot(eng, t, min_retrace, max_retrace)
            if _qualifies(snap, stages, contexts, max_bars_since_w2, t):
                rows.append(_build_row(snap, g, t, ticker, tf, length, decimals))
    return _finish(rows)


# ----------------------------------------------------------------------------------
# Public: forward evaluation
# ----------------------------------------------------------------------------------
def _levels_dict(levels: list[str]) -> dict:
    return {k: float(v) for k, v in (s.split("=", 1) for s in levels)}


def evaluate_signals(signals: pd.DataFrame, df: pd.DataFrame, horizon_bars: int = 30) -> pd.DataFrame:
    """
    For each signal, look at the bars AFTER signal_time (up to horizon_bars):

    status  NOT_TRIGGERED - neither trigger nor failure inside the horizon
            FAILED        - price went beyond W2_END before the trigger (wave 2 was not finished)
            TRIGGERED     - Close broke TRIGGER (high/low of the wave-2 bar) first
    After a trigger (entry = trigger bar close, stop = W2_END):
            stopped / stop_time, hit_<target> / hit_<target>_time for
            W1_END and wave 3 at 1.000 / 1.618 / 2.618 x wave 1,
            mfe_pct / mae_pct, result.

    Same-bar conflicts are resolved conservatively (failure / stop counted first).
    The signal bar's own close can trigger. A target the entry price is already
    beyond counts as hit on the trigger bar.
    """
    data = _prepare(df)
    groups = {k: g.reset_index(drop=True) for k, g in data.groupby(["ticker", "time_frame"], sort=False)}

    out = []
    for _, s in signals.iterrows():
        rec = s.to_dict()
        g = groups.get((s["Ticker"], s["time_frame"]))
        res = {"status": "NO_DATA", "trigger_time": pd.NaT, "entry_price": np.nan,
               "stopped": False, "stop_time": pd.NaT, "mfe_pct": np.nan, "mae_pct": np.nan,
               "first_target_hit": None, "result": None}
        for tg in TARGETS:
            res[f"hit_{tg}"] = False
            res[f"hit_{tg}_time"] = pd.NaT

        if g is not None:
            lv = _levels_dict(s["wave_levels"])
            long = s["trade_side"] == "LONG"
            times = g["time"]
            t0 = int(times.searchsorted(pd.Timestamp(s["signal_time"]), side="left"))
            end = min(len(g) - 1, t0 + horizon_bars)
            H, L, C = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
            w2, trig = lv["W2_END"], lv["TRIGGER"]

            k_trig = None
            status = "NOT_TRIGGERED"
            for k in range(t0, end + 1):
                if k > t0 and ((L[k] < w2) if long else (H[k] > w2)):
                    status = "FAILED"
                    break
                if (C[k] > trig) if long else (C[k] < trig):
                    k_trig, status = k, "TRIGGERED"
                    break
            res["status"] = status

            if k_trig is not None:
                entry = C[k_trig]
                res["trigger_time"] = times.iat[k_trig]
                res["entry_price"] = round(float(entry), 2)
                for tg in TARGETS:                              # already beyond at entry
                    if (entry >= lv[tg]) if long else (entry <= lv[tg]):
                        res[f"hit_{tg}"] = True
                        res[f"hit_{tg}_time"] = times.iat[k_trig]
                        if res["first_target_hit"] is None:
                            res["first_target_hit"] = tg
                mfe = mae = 0.0
                stop_k = None
                for k in range(k_trig + 1, end + 1):
                    if (L[k] < w2) if long else (H[k] > w2):
                        stop_k = k
                        mae = max(mae, (1 - w2 / entry) * 100 if long else (w2 / entry - 1) * 100)
                        break
                    fav = (H[k] / entry - 1) * 100 if long else (1 - L[k] / entry) * 100
                    adv = (1 - L[k] / entry) * 100 if long else (H[k] / entry - 1) * 100
                    mfe, mae = max(mfe, fav), max(mae, adv)
                    for tg in TARGETS:
                        if not res[f"hit_{tg}"] and ((H[k] >= lv[tg]) if long else (L[k] <= lv[tg])):
                            res[f"hit_{tg}"] = True
                            res[f"hit_{tg}_time"] = times.iat[k]
                            if res["first_target_hit"] is None:
                                res["first_target_hit"] = tg
                if stop_k is not None:
                    res["stopped"] = True
                    res["stop_time"] = times.iat[stop_k]
                res["mfe_pct"], res["mae_pct"] = round(mfe, 2), round(mae, 2)
                if res["first_target_hit"]:
                    res["result"] = "TARGET_HIT" + ("_THEN_STOPPED" if stop_k is not None else "")
                else:
                    res["result"] = "STOPPED" if stop_k is not None else "OPEN"
            res["bars_evaluated"] = end - t0
        rec.update(res)
        out.append(rec)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------
# Public: walk-forward backtest (one engine pass per series, no look-ahead)
# ----------------------------------------------------------------------------------
def backtest_wave3(
    df: pd.DataFrame,
    start=None,
    end=None,
    horizon_bars: int = 30,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    stages: Sequence[str] = (STAGE_W2_COMPLETED,),
    contexts: Sequence[str] = DEFAULT_CONTEXTS,
    min_retrace: float = DEFAULT_MIN_RETRACE,
    max_retrace: float = DEFAULT_MAX_RETRACE,
    resignal_on_new_w2: bool = False,
    max_bars_since_w2: Optional[int] = None,
    hi_source: str = "high",
    lo_source: str = "low",
    pivot_tie: str = "strict",
    min_bars: int = 120,
    decimals: int = 2,
) -> pd.DataFrame:
    """
    Walk forward through every bar between start and end; each bar only knows data up
    to itself (same as screen_wave3(df, as_of=that bar)). A signal is recorded the first
    bar a 0-1 pair qualifies; with resignal_on_new_w2=True a new signal is also recorded
    when the wave-2 pivot moves to a new confirmed extreme.
    """
    if not 0 < min_retrace <= max_retrace < 1:
        raise ValueError("Need 0 < min_retrace <= max_retrace < 1")
    data = _prepare(df)
    t_start = pd.Timestamp(start) if start is not None else None
    t_end = pd.Timestamp(end) if end is not None else None

    rows = []
    for (ticker, tf), g in data.groupby(["ticker", "time_frame"], sort=False):
        g = g.reset_index(drop=True)
        if len(g) < min_bars:
            continue
        in_window = np.ones(len(g), dtype=bool)
        if t_start is not None:
            in_window &= (g["time"] >= t_start).to_numpy()
        if t_end is not None:
            in_window &= (g["time"] <= t_end).to_numpy()
        for length in lengths:
            eng = ElliottWaveEngine(g["high"], g["low"], g["close"], length, hi_source, lo_source,
                                    open_=g["open"], pivot_tie=pivot_tie)
            seen = set()
            for i in range(eng.n):
                eng.step(i)
                if i < min_bars - 1 or not in_window[i]:
                    continue
                snap = _snapshot(eng, i, min_retrace, max_retrace)
                if not _qualifies(snap, stages, contexts, max_bars_since_w2, i):
                    continue
                p = snap["pts"]
                key = (p[0][0], p[1][0]) + ((p[2][0],) if resignal_on_new_w2 else ())
                if key in seen:
                    continue
                seen.add(key)
                rows.append(_build_row(snap, g, i, ticker, tf, length, decimals))

    signals = _finish(rows)
    if signals.empty:
        return signals
    return evaluate_signals(signals, df, horizon_bars)


def summarize_backtest(results: pd.DataFrame) -> pd.DataFrame:
    """Hit-rate summary by time_frame and degree."""
    if results.empty:
        return results
    r = results.copy()
    r["triggered"] = r["status"].eq("TRIGGERED")
    r["failed"] = r["status"].eq("FAILED")
    agg = r.groupby(["time_frame", "degree"]).agg(
        signals=("Ticker", "size"),
        triggered=("triggered", "sum"),
        failed=("failed", "sum"),
        hit_W1=("hit_W1_END", "sum"),
        hit_W3_1618=("hit_W3_TGT_1.618xW1", "sum"),
        stopped=("stopped", "sum"),
        avg_mfe_pct=("mfe_pct", "mean"),
        avg_mae_pct=("mae_pct", "mean"),
    ).reset_index()
    agg["trigger_rate_%"] = (agg["triggered"] / agg["signals"] * 100).round(1)
    agg["w1_hit_rate_of_triggered_%"] = (agg["hit_W1"] / agg["triggered"].replace(0, np.nan) * 100).round(1)
    return agg
