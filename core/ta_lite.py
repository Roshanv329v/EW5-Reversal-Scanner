"""
Pure numpy / pandas versions of the five TA-Lib functions used by
stock_data.calculate_indicator_values: RSI, SMA, EMA, ATR, CCI.

Used only where the TA-Lib C library cannot be installed (the Android build).
Each function follows TA-Lib's own algorithm, so the output matches TA-Lib:

- leading NaNs in the input are skipped and the output starts after them
- the same warm-up length (first value at the same bar as TA-Lib)
- EMA is seeded with the simple average of the first `timeperiod` values
- RSI and ATR use Wilder smoothing seeded with a simple average
- an interior NaN in SMA input stays in the running sum, as in TA-Lib

tests/test_ta_lite.py checks every function against TA-Lib on the same data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _values(x) -> np.ndarray:
    return np.asarray(x, dtype="float64")


def _wrap(out: np.ndarray, like) -> pd.Series | np.ndarray:
    return pd.Series(out, index=like.index) if isinstance(like, pd.Series) else out


def _first_valid(*arrays: np.ndarray) -> int:
    """First index where every input is a number (TA-Lib skips the NaNs before it)."""
    ok = np.ones(len(arrays[0]), dtype=bool)
    for a in arrays:
        ok &= ~np.isnan(a)
    hits = np.flatnonzero(ok)
    return int(hits[0]) if len(hits) else len(arrays[0])


def _seeded_recursive(values: np.ndarray, seed_at: int, seed: float, alpha: float) -> np.ndarray:
    """y[seed_at] = seed, then y[i] = y[i-1] + alpha * (x[i] - y[i-1])."""
    out = np.full(len(values), np.nan)
    if seed_at >= len(values):
        return out
    tail = values[seed_at:].copy()
    tail[0] = seed
    out[seed_at:] = pd.Series(tail).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return out


def SMA(real, timeperiod: int = 30):
    x = _values(real)
    n, out = int(timeperiod), np.full(len(x), np.nan)
    start = _first_valid(x)
    if len(x) - start >= n:
        csum = np.cumsum(x[start:])                       # a NaN stays in the running sum
        sums = csum[n - 1:] - np.concatenate(([0.0], csum[:-n]))
        out[start + n - 1:] = sums / n
    return _wrap(out, real)


def EMA(real, timeperiod: int = 30):
    x = _values(real)
    n = int(timeperiod)
    start = _first_valid(x)
    if len(x) - start < n:
        return _wrap(np.full(len(x), np.nan), real)
    seed = x[start:start + n].mean()
    return _wrap(_seeded_recursive(x, start + n - 1, seed, 2.0 / (n + 1)), real)


def RSI(real, timeperiod: int = 14):
    """
    Wilder RSI as in TA-Lib. Values agree with TA-Lib to about 1e-14; the last bits can
    differ because TA-Lib's compiled loop rounds differently. That only shows where
    stock_data's DTosc divides by (max - min) of RSI on a perfectly flat stretch, which
    is 0 / 0 noise in TA-Lib too.
    """
    x = _values(real)
    n, out = int(timeperiod), np.full(len(x), np.nan)
    start = _first_valid(x)
    if len(x) - start <= n:
        return _wrap(out, real)
    diff = np.diff(x[start:])
    gain, loss = np.where(diff > 0, diff, 0.0), np.where(diff < 0, -diff, 0.0)
    g = _seeded_recursive(gain, n - 1, gain[:n].mean(), 1.0 / n)
    l = _seeded_recursive(loss, n - 1, loss[:n].mean(), 1.0 / n)
    total = g + l
    with np.errstate(invalid="ignore", divide="ignore"):
        rsi = np.where(np.abs(total) < 1e-8, 50.0, 100.0 * g / total)   # flat price: TA-Lib gives 50
    rsi[: n - 1] = np.nan
    out[start + 1:] = rsi
    return _wrap(out, real)


def ATR(high, low, close, timeperiod: int = 14):
    h, l, c = _values(high), _values(low), _values(close)
    n, out = int(timeperiod), np.full(len(c), np.nan)
    start = _first_valid(h, l, c)
    if len(c) - start <= n:
        return _wrap(out, close)
    h, l, c = h[start:], l[start:], c[start:]
    prev = c[:-1]
    tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - prev), np.abs(l[1:] - prev)])
    atr = _seeded_recursive(tr, n - 1, tr[:n].mean(), 1.0 / n)
    out[start + 1:] = atr
    return _wrap(out, close)


def CCI(high, low, close, timeperiod: int = 14):
    h, l, c = _values(high), _values(low), _values(close)
    n, out = int(timeperiod), np.full(len(c), np.nan)
    start = _first_valid(h, l, c)
    if len(c) - start < n:
        return _wrap(out, close)
    tp = (h[start:] + l[start:] + c[start:]) / 3.0
    windows = np.lib.stride_tricks.sliding_window_view(tp, n)
    mean = windows.mean(axis=1)
    dev = np.abs(windows - mean[:, None]).mean(axis=1)
    flat = dev <= 1e-12 * np.maximum(1.0, np.abs(mean))          # rounding noise on a flat window
    with np.errstate(invalid="ignore", divide="ignore"):
        cci = np.where(flat, 0.0, (tp[n - 1:] - mean) / (0.015 * dev))
    out[start + n - 1:] = cci
    return _wrap(out, close)
