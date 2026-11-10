"""
elliott_wave5_screener.py
=========================

Python port of the Elliott Wave logic from "SMC Ultimate [Roshan]" (Pine Script),
built to:

1. Screen stocks whose latest valid impulse (1-2-3-4-5) is at / completing wave 5,
   so a reversal can be played, and return the reversal levels as a list of strings.
2. Backtest the same logic without look-ahead (point-in-time / walk-forward).

Input DataFrame columns (case-insensitive):
    Ticker, time, time_frame, Open, High, Low, Close

Public API
----------
screen_wave5(df, as_of=None, ...)          -> signals DataFrame (one row per ticker/tf/degree)
backtest_wave5(df, start, end, ...)        -> signals + forward outcome per signal
evaluate_signals(signals, df, ...)         -> adds forward outcome columns to any signals frame
summarize_backtest(results)                -> hit-rate summary

Faithfulness to the Pine script
-------------------------------
The engine replays the Pine `draw()` function bar by bar (same ZigZag arrays, same
impulse rules, same A-B-C rules, same invalidation, same Fibonacci zone and break
check). Everything a bar sees is computed from that bar and earlier bars only, so the
state at bar t is exactly what TradingView would show if bar t were the last bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------
# Defaults (same as the Pine inputs)
# ----------------------------------------------------------------------------------
DEFAULT_LENGTHS: tuple[int, ...] = (4, 8, 16)          # ZigZag 1 / 2 / 3
DEGREE_NAMES = {4: "minor", 8: "intermediate", 16: "major"}
DEFAULT_FIBS: tuple[float, float, float, float] = (0.500, 0.618, 0.764, 0.854)

STAGE_IN_PROGRESS = "WAVE5_IN_PROGRESS"   # wave-5 extreme is the latest confirmed pivot
STAGE_COMPLETED = "WAVE5_COMPLETED"       # an opposite pivot after wave 5 is confirmed (wave A started)

# Order of the reversal_levels list (always the same, so it explodes into stable columns)
LEVEL_NAMES: tuple[str, ...] = (
    "W0_START", "W1_END", "W2_END", "W3_END", "W4_END", "W5_END",
    "TRIGGER", "STOP",
    "FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854",
    "W5_TGT_0.618xW1", "W5_TGT_1.000xW1", "W5_TGT_1.618xW1",
)

_REQUIRED = ["ticker", "time", "time_frame", "open", "high", "low", "close"]


# ----------------------------------------------------------------------------------
# Internal state objects (mirror the Pine UDTs)
# ----------------------------------------------------------------------------------
@dataclass
class _Wave:
    """Pine `Ewave`. pts = [(x, y)] for points 0..5 (0 = start, 5 = end of wave 5)."""
    dir: int = 0                       # 1 bullish impulse, -1 bearish impulse, 0 = empty seed
    pts: Optional[list] = None
    on: bool = False                   # False for the empty seed (Pine: na)
    a: Optional[tuple] = None          # (x, y) of (a)
    b: Optional[tuple] = None
    c: Optional[tuple] = None
    abc_on: bool = False               # False once the A-B-C is invalidated (dashed)
    box: Optional[list] = None         # [left, top, right, bottom] of the A-B-C box
    next: bool = False                 # "possible new start" circle printed
    created_bar: int = -1

    @property
    def empty(self) -> bool:
        return self.pts is None

    def is_same(self, x1, x2, x3, x4) -> bool:      # Pine isSame (l1..l4 .x1)
        if self.empty:
            return False
        p = self.pts
        return x1 == p[0][0] and x2 == p[1][0] and x3 == p[2][0] and x4 == p[3][0]

    def is_same2(self, x1, x2, x3) -> bool:         # Pine isSame2 (l3..l5 .x2)
        if self.empty:
            return False
        p = self.pts
        return x1 == p[3][0] and x2 == p[4][0] and x3 == p[5][0]


@dataclass
class _LiveWave:
    """Pine `LiveWave` - provisional leg counter (~(1) .. ~(5), ~(A) .. ~(C))."""
    phase: int = 1
    leg: int = 0
    pivot_n: int = 0
    text: Optional[str] = None

    def new_leg(self):
        self.pivot_n += 1
        if self.pivot_n > 1:
            self.leg += 1
            if self.phase == 1:
                self.text = f"~({self.leg})"
            else:
                self.text = "~(" + ("A" if self.leg == 1 else "B" if self.leg == 2 else "C") + ")"
            limit = 5 if self.phase == 1 else 3
            if self.leg == limit:
                self.phase *= -1
                self.leg = 0

    def reset(self):
        self.phase = 1
        self.leg = 0
        self.text = None


# ----------------------------------------------------------------------------------
# Pivot detection (ta.pivothigh / ta.pivotlow with rightbars = 1)
# ----------------------------------------------------------------------------------
def _pivots(src: np.ndarray, left: int, is_high: bool, tie: str) -> np.ndarray:
    """
    Value reported on bar i for a pivot at bar i-1 (confirmed 1 bar later, like Pine).
    tie = "strict"     : pivot must be strictly above (below) all left bars and the right bar
          "left_equal" : ties allowed on the left side, strict on the right
    """
    n = len(src)
    out = np.full(n, np.nan)
    for i in range(left + 1, n):
        c = src[i - 1]
        if np.isnan(c):
            continue
        lw = src[i - 1 - left:i - 1]
        r = src[i]
        if is_high:
            ok_left = np.all(c > lw) if tie == "strict" else np.all(c >= lw)
            ok = ok_left and c > r
        else:
            ok_left = np.all(c < lw) if tie == "strict" else np.all(c <= lw)
            ok = ok_left and c < r
        if ok:
            out[i] = c
    return out


# ----------------------------------------------------------------------------------
# Engine: one ticker, one timeframe, one ZigZag length (= one Pine draw() call)
# ----------------------------------------------------------------------------------
class ElliottWaveEngine:
    """
    Bar-by-bar replay of the Pine `draw()` function.

    Call `step(i)` for i = 0..n-1 in order. After step(i), `snapshot(i)` returns what
    the indicator shows when bar i is the last bar (no future data is used).
    """

    def __init__(self, high, low, close, length: int,
                 hi_source: str = "high", lo_source: str = "low",
                 fibs: Sequence[float] = DEFAULT_FIBS, open_=None, pivot_tie: str = "strict"):
        self.H = np.asarray(high, dtype=float)
        self.L = np.asarray(low, dtype=float)
        self.C = np.asarray(close, dtype=float)
        self.O = np.asarray(open_ if open_ is not None else close, dtype=float)
        self.length = int(length)
        self.fibs = tuple(fibs)
        self.f854 = self.fibs[3]

        # source [high - low]
        if hi_source == "high":
            self.hi = self.H
        elif hi_source == "close":
            self.hi = self.C
        else:                                   # 'max open/close'
            self.hi = np.maximum(self.O, self.C)
        if lo_source == "low":
            self.lo = self.L
        elif lo_source == "close":
            self.lo = self.C
        else:                                   # 'min open/close'
            self.lo = np.minimum(self.O, self.C)

        self.PH = _pivots(self.hi, self.length, True, pivot_tie)
        self.PL = _pivots(self.lo, self.length, False, pivot_tie)

        # ZZ arrays (Pine: 11 zeros on the first bar)
        self.zd = [0] * 11
        self.zx = [0] * 11
        self.zy = [0.0] * 11
        self.waves: list[_Wave] = [_Wave()]     # aEW with the empty seed
        self.live = _LiveWave()
        self.n = len(self.H)

    # Pine in_out()
    def _in_out(self, d, x2, y2):
        self.zd.insert(0, d); self.zx.insert(0, x2); self.zy.insert(0, y2)
        self.zd.pop(); self.zx.pop(); self.zy.pop()

    def _window(self, x2, y2):
        zx, zy = self.zx, self.zy
        return (zx[5], zy[5]), (zx[4], zy[4]), (zx[3], zy[3]), (zx[2], zy[2]), (zx[1], zy[1]), (x2, y2)

    # ------------------------------------------------------------------ one bar
    def step(self, i: int) -> None:
        x2 = i - 1
        ph = self.PH[i]
        pl = self.PL[i]
        f = self.f854

        # ================================ new Pivot High ================================
        if not np.isnan(ph):
            gEW = self.waves[0]
            d0, y1 = self.zd[0], self.zy[0]
            y2 = float(np.nan_to_num(self.hi[i - 1]))
            if d0 < 1:
                self._in_out(1, x2, y2)
                self.live.new_leg()
            elif d0 == 1 and ph > y1:
                self.zx[0], self.zy[0] = x2, y2

            (_1x, _1y), (_2x, _2y), (_3x, _3y), (_4x, _4y), (_5x, _5y), (_6x, _6y) = self._window(x2, y2)

            # ---- 12345 (bullish)
            W5, W3, W1 = _6y - _5y, _4y - _3y, _2y - _1y
            is_wave = (W3 != min(W1, W3, W5)) and _6y > _4y and _3y > _1y and _5y > _2y
            same = gEW.is_same(_1x, _2x, _3x, _4x)
            if is_wave:
                if same:
                    gEW.pts[5] = (_6x, _6y)
                else:
                    self.waves.insert(0, _Wave(dir=1, on=True, created_bar=i,
                                               pts=[(_1x, _1y), (_2x, _2y), (_3x, _3y),
                                                    (_4x, _4y), (_5x, _5y), (_6x, _6y)]))
            if not is_wave and same and gEW.on:
                gEW.on = False
                self.live.reset()

            # ---- ABC after a bearish impulse (corrective up)
            g = self.waves[0]
            if g.dir == -1:
                p0y, (p5x, p5y) = g.pts[0][1], g.pts[5]
                diff = abs(p5y - p0y)
                same2 = g.is_same2(_1x, _2x, _3x)
                valid = _3x == p5x and _6y < p5y + diff * f and _4y < p5y + diff * f and _5y > p5y
                has_a_after = g.a is not None and g.a[0] > _3x
                if valid:
                    width = _6x - _2x
                    if same2 and has_a_after:
                        g.c = (_6x, _6y)
                        g.box[0], g.box[1], g.box[2] = _6x, _6y, _6x + width
                    else:
                        g.a, g.b, g.c = (_4x, _4y), (_5x, _5y), (_6x, _6y)
                        g.box = [_6x, _6y, _6x + width, _4y]
                        g.abc_on = True
                elif same2 and has_a_after:
                    g.abc_on = False
            # ---- possible new (1) after bullish impulse + correction
            if g.dir == 1 and g.c is not None:
                if _5x == g.c[0] and _6y > g.pts[5][1] and not g.next:
                    g.next = True

        # ================================ new Pivot Low =================================
        if not np.isnan(pl):
            gEW = self.waves[0]
            d0, y1 = self.zd[0], self.zy[0]
            y2 = float(np.nan_to_num(self.lo[i - 1]))
            if d0 > -1:
                self._in_out(-1, x2, y2)
                self.live.new_leg()
            elif d0 == -1 and pl < y1:
                self.zx[0], self.zy[0] = x2, y2

            (_1x, _1y), (_2x, _2y), (_3x, _3y), (_4x, _4y), (_5x, _5y), (_6x, _6y) = self._window(x2, y2)

            # ---- 12345 (bearish)
            W5, W3, W1 = _5y - _6y, _3y - _4y, _1y - _2y
            is_wave = (W3 != min(W1, W3, W5)) and _4y > _6y and _1y > _3y and _2y > _5y
            same = gEW.is_same(_1x, _2x, _3x, _4x)
            if is_wave:
                if same:
                    gEW.pts[5] = (_6x, _6y)
                else:
                    self.waves.insert(0, _Wave(dir=-1, on=True, created_bar=i,
                                               pts=[(_1x, _1y), (_2x, _2y), (_3x, _3y),
                                                    (_4x, _4y), (_5x, _5y), (_6x, _6y)]))
            if not is_wave and same and gEW.on:
                gEW.on = False
                self.live.reset()

            # ---- ABC after a bullish impulse (corrective down)
            g = self.waves[0]
            if g.dir == 1:
                p0y, (p5x, p5y) = g.pts[0][1], g.pts[5]
                diff = abs(p5y - p0y)
                same2 = g.is_same2(_1x, _2x, _3x)
                valid = _3x == p5x and _6y > p5y - diff * f and _4y > p5y - diff * f and _5y < p5y
                has_a_after = g.a is not None and g.a[0] > _3x
                if valid:
                    width = _6x - _2x
                    if same2 and has_a_after:
                        g.c = (_6x, _6y)
                        g.box[0], g.box[1], g.box[2] = _6x, _6y, _6x + width
                    else:
                        g.a, g.b, g.c = (_4x, _4y), (_5x, _5y), (_6x, _6y)
                        g.box = [_6x, _6y, _6x + width, _4y]
                        g.abc_on = True
                elif same2 and has_a_after:
                    g.abc_on = False
            # ---- possible new (1) after bearish impulse + correction
            if g.dir == -1 and g.c is not None:
                if _5x == g.c[0] and _6y < g.pts[5][1] and not g.next:
                    g.next = True

        if len(self.waves) > 16:                 # Pine: pop when size > 15
            self.waves.pop()

    # ------------------------------------------------------------------ state at bar t
    def snapshot(self, t: int) -> Optional[dict]:
        """State of the latest impulse as the indicator shows it with bar t as last bar."""
        if len(self.waves) < 2:                  # Pine: aEW.size() > 1
            return None
        g = self.waves[0]
        if g.empty:
            return None
        p = g.pts
        bull = g.dir == 1
        abc_done = g.c is not None and g.c[0] > p[5][0]
        fib_valid = g.on and not abc_done
        diff = abs(p[5][1] - p[0][1])
        sgn = -1.0 if bull else 1.0
        fib_levels = [p[5][1] + sgn * diff * r for r in self.fibs]

        fib_broken = False
        if fib_valid:
            seg = slice(p[5][0], t + 1)
            lvl = fib_levels[3]
            fib_broken = bool(np.any(self.L[seg] < lvl)) if bull else bool(np.any(self.H[seg] > lvl))

        latest_is_w5 = self.zx[0] == p[5][0] and self.zd[0] == g.dir
        stage = STAGE_IN_PROGRESS if latest_is_w5 else STAGE_COMPLETED

        return dict(
            dir=g.dir, on=g.on, pts=[tuple(q) for q in p], fib_levels=fib_levels,
            fib_valid=fib_valid, fib_broken=fib_broken, abc_done=abc_done,
            abc_on=g.abc_on, next=g.next, stage=stage, created_bar=g.created_bar,
            live=self.live.text,
        )


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------
def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c: c.strip().lower() for c in df.columns}
    out = df.rename(columns=cols)
    missing = [c for c in _REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Expected {_REQUIRED} (case-insensitive).")
    out = out[_REQUIRED].copy()
    out["time"] = pd.to_datetime(out["time"])
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["high", "low", "close"])
    out = (out.sort_values(["ticker", "time_frame", "time"])
              .drop_duplicates(["ticker", "time_frame", "time"], keep="last")
              .reset_index(drop=True))
    return out


def _r(v: float, nd: int = 2) -> float:
    return float(round(v, nd))


def _build_row(snap: dict, g: pd.DataFrame, t: int, ticker, tf, length, nd: int) -> dict:
    p = snap["pts"]
    bull = snap["dir"] == 1
    (x0, y0), (x1, y1), (x2, y2), (x3, y3), (x4, y4), (x5, y5) = p
    w1, w3, w5 = abs(y1 - y0), abs(y3 - y2), abs(y5 - y4)
    sgn = 1.0 if bull else -1.0
    trigger = float(g["low"].iat[x5] if bull else g["high"].iat[x5])   # break of the W5 bar
    levels = {
        "W0_START": y0, "W1_END": y1, "W2_END": y2, "W3_END": y3, "W4_END": y4, "W5_END": y5,
        "TRIGGER": trigger, "STOP": y5,
        "FIB_0.500": snap["fib_levels"][0], "FIB_0.618": snap["fib_levels"][1],
        "FIB_0.764": snap["fib_levels"][2], "FIB_0.854": snap["fib_levels"][3],
        "W5_TGT_0.618xW1": y4 + sgn * 0.618 * w1,
        "W5_TGT_1.000xW1": y4 + sgn * 1.000 * w1,
        "W5_TGT_1.618xW1": y4 + sgn * 1.618 * w1,
    }
    times = g["time"]
    return {
        "Ticker": ticker,
        "time_frame": tf,
        "zigzag_length": length,
        "degree": DEGREE_NAMES.get(length, f"len{length}"),
        "signal_time": times.iat[t],
        "impulse": "BULLISH" if bull else "BEARISH",
        "reversal_side": "SHORT" if bull else "LONG",
        "stage": snap["stage"],
        "live_count": snap["live"],
        "close": _r(float(g["close"].iat[t]), nd),
        "w5_end_time": times.iat[x5],
        "w5_end_price": _r(y5, nd),
        "bars_since_w5": int(t - x5),
        "w5_vs_w1": _r(w5 / w1, 3) if w1 else np.nan,
        "w3_vs_w1": _r(w3 / w1, 3) if w1 else np.nan,
        "dist_from_w5_pct": _r((float(g["close"].iat[t]) / y5 - 1) * 100, 2),
        "fib_broken": snap["fib_broken"],
        "wave_key": f"{ticker}|{tf}|{length}|{x0}-{x1}-{x2}-{x3}",
        "reversal_levels": [f"{k}={_r(levels[k], nd)}" for k in LEVEL_NAMES],
        "_bar": t, "_w5_bar": x5,
    }


def _qualifies(snap: Optional[dict], stages: Iterable[str], max_bars_since_w5: Optional[int], t: int,
               min_w5_vs_w1: float) -> bool:
    if snap is None or not snap["fib_valid"] or snap["fib_broken"]:
        return False
    if snap["stage"] not in stages:
        return False
    p = snap["pts"]
    if max_bars_since_w5 is not None and t - p[5][0] > max_bars_since_w5:
        return False
    w1 = abs(p[1][1] - p[0][1])
    w5 = abs(p[5][1] - p[4][1])
    if w1 and w5 / w1 < min_w5_vs_w1:
        return False
    return True


# ----------------------------------------------------------------------------------
# Public: point-in-time screener
# ----------------------------------------------------------------------------------
def screen_wave5(
    df: pd.DataFrame,
    as_of=None,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    stages: Sequence[str] = (STAGE_IN_PROGRESS,),
    max_bars_since_w5: Optional[int] = None,
    min_w5_vs_w1: float = 0.0,
    hi_source: str = "high",
    lo_source: str = "low",
    fibs: Sequence[float] = DEFAULT_FIBS,
    pivot_tie: str = "strict",
    min_bars: int = 120,
    decimals: int = 2,
) -> pd.DataFrame:
    """
    Return tickers whose latest valid impulse is at / completing wave 5.

    as_of : None -> use the last bar of each ticker.
            timestamp -> only bars with time <= as_of are used (backtest a past date).
                         You can pass the full DataFrame; later rows are ignored.
    stages: (WAVE5_IN_PROGRESS,) = wave-5 extreme is the most recent swing (default)
            add WAVE5_COMPLETED to also get stocks where the first pivot against wave 5
            is already confirmed (reversal started, A-B-C not complete, 0.854 not broken).
    max_bars_since_w5 : optional freshness filter.
    min_w5_vs_w1      : optional maturity filter, e.g. 0.618 -> wave 5 at least 61.8% of wave 1.
    """
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
                                    fibs, g["open"], pivot_tie)
            for i in range(eng.n):
                eng.step(i)
            snap = eng.snapshot(t)
            if _qualifies(snap, stages, max_bars_since_w5, t, min_w5_vs_w1):
                rows.append(_build_row(snap, g, t, ticker, tf, length, decimals))

    return _finish(rows)


def _finish(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[
            "Ticker", "time_frame", "zigzag_length", "degree", "signal_time", "impulse",
            "reversal_side", "stage", "live_count", "close", "w5_end_time", "w5_end_price",
            "bars_since_w5", "w5_vs_w1", "w3_vs_w1", "dist_from_w5_pct", "fib_broken",
            "wave_key", "reversal_levels"])
    out = pd.DataFrame(rows).drop(columns=["_bar", "_w5_bar"])
    return out.sort_values(["time_frame", "Ticker", "zigzag_length"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------
# Public: forward evaluation of signals (did the reversal trigger and work?)
# ----------------------------------------------------------------------------------
def _levels_dict(levels: list[str]) -> dict:
    return {k: float(v) for k, v in (s.split("=", 1) for s in levels)}


def evaluate_signals(signals: pd.DataFrame, df: pd.DataFrame, horizon_bars: int = 30) -> pd.DataFrame:
    """
    For each signal, look at the bars AFTER signal_time (up to horizon_bars) and report:

    status  NOT_TRIGGERED  - neither trigger nor wave-5 extension inside the horizon
            EXTENDED       - price went beyond W5_END before the trigger (wave 5 extended)
            TRIGGERED      - Close broke TRIGGER (low/high of the wave-5 bar) first
    After a trigger (entry = trigger bar close, stop = W5_END):
            stopped / stop_time, hit_<target> / hit_<target>_time for
            W4_END, FIB_0.500, FIB_0.618, FIB_0.764, FIB_0.854,
            mfe_pct / mae_pct (best / worst move from entry), result.

    Same-bar conflicts are resolved conservatively (extension / stop counted first).
    The signal bar's own close can trigger (it is known at signal time).
    """
    data = _prepare(df)
    targets = ["W4_END", "FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854"]
    groups = {k: g.reset_index(drop=True) for k, g in data.groupby(["ticker", "time_frame"], sort=False)}

    out = []
    for _, s in signals.iterrows():
        rec = s.to_dict()
        g = groups.get((s["Ticker"], s["time_frame"]))
        res = {"status": "NO_DATA", "trigger_time": pd.NaT, "entry_price": np.nan,
               "stopped": False, "stop_time": pd.NaT, "mfe_pct": np.nan, "mae_pct": np.nan,
               "first_target_hit": None, "result": None}
        for tg in targets:
            res[f"hit_{tg}"] = False
            res[f"hit_{tg}_time"] = pd.NaT

        if g is not None:
            lv = _levels_dict(s["reversal_levels"])
            short = s["reversal_side"] == "SHORT"
            times = g["time"]
            t0 = int(times.searchsorted(pd.Timestamp(s["signal_time"]), side="left"))
            end = min(len(g) - 1, t0 + horizon_bars)
            H, L, C = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
            w5, trig = lv["W5_END"], lv["TRIGGER"]

            k_trig = None
            status = "NOT_TRIGGERED"
            for k in range(t0, end + 1):
                if k > t0 and ((H[k] > w5) if short else (L[k] < w5)):
                    status = "EXTENDED"
                    break
                if (C[k] < trig) if short else (C[k] > trig):
                    k_trig, status = k, "TRIGGERED"
                    break
            res["status"] = status

            if k_trig is not None:
                entry = C[k_trig]
                res["trigger_time"] = times.iat[k_trig]
                res["entry_price"] = round(float(entry), 2)
                mfe = mae = 0.0
                stop_k = None
                for k in range(k_trig + 1, end + 1):
                    stop_hit = (H[k] > w5) if short else (L[k] < w5)
                    if stop_hit:
                        stop_k = k
                        mae = max(mae, (w5 / entry - 1) * 100 if short else (1 - w5 / entry) * 100)
                        break
                    fav = (1 - L[k] / entry) * 100 if short else (H[k] / entry - 1) * 100
                    adv = (H[k] / entry - 1) * 100 if short else (1 - L[k] / entry) * 100
                    mfe, mae = max(mfe, fav), max(mae, adv)
                    for tg in targets:
                        if not res[f"hit_{tg}"] and ((L[k] <= lv[tg]) if short else (H[k] >= lv[tg])):
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
def backtest_wave5(
    df: pd.DataFrame,
    start=None,
    end=None,
    horizon_bars: int = 30,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    stages: Sequence[str] = (STAGE_IN_PROGRESS,),
    resignal_on_extension: bool = False,
    max_bars_since_w5: Optional[int] = None,
    min_w5_vs_w1: float = 0.0,
    hi_source: str = "high",
    lo_source: str = "low",
    fibs: Sequence[float] = DEFAULT_FIBS,
    pivot_tie: str = "strict",
    min_bars: int = 120,
    decimals: int = 2,
) -> pd.DataFrame:
    """
    Walk forward through every bar between start and end. On each bar the engine only
    knows data up to that bar (same as screen_wave5(df, as_of=that bar)). A signal is
    recorded the first bar an impulse qualifies; with resignal_on_extension=True a new
    signal is also recorded each time wave 5 makes a new confirmed extreme.
    Returns signals with forward outcome columns (see evaluate_signals).
    """
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
                                    fibs, g["open"], pivot_tie)
            seen = set()
            for i in range(eng.n):
                eng.step(i)
                if i < min_bars - 1 or not in_window[i]:
                    continue
                snap = eng.snapshot(i)
                if not _qualifies(snap, stages, max_bars_since_w5, i, min_w5_vs_w1):
                    continue
                p = snap["pts"]
                key = (p[0][0], p[1][0], p[2][0], p[3][0]) + ((p[5][0],) if resignal_on_extension else ())
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
    r["extended"] = r["status"].eq("EXTENDED")
    agg = r.groupby(["time_frame", "degree"]).agg(
        signals=("Ticker", "size"),
        triggered=("triggered", "sum"),
        extended=("extended", "sum"),
        hit_W4=("hit_W4_END", "sum"),
        hit_FIB_0500=("hit_FIB_0.500", "sum"),
        stopped=("stopped", "sum"),
        avg_mfe_pct=("mfe_pct", "mean"),
        avg_mae_pct=("mae_pct", "mean"),
    ).reset_index()
    agg["trigger_rate_%"] = (agg["triggered"] / agg["signals"] * 100).round(1)
    agg["w4_hit_rate_of_triggered_%"] = (agg["hit_W4"] / agg["triggered"].replace(0, np.nan) * 100).round(1)
    return agg
