"""
The Charts tab: pick stocks that can be traded WITH the trend, then look at any of them on
60m / 4hr / 1D / 1W candles with every EW5 and EW3 signal drawn on the chart.

Shared by the desktop (app.py) and the phone (mobile/api.py), so both list the same stocks
in the same order and draw the same chart.

    snapshot()      last bar of every ticker on every timeframe (close, DTosc K / D)
    trends()        trend per timeframe (DTosc K above D = BULLISH, as in core/htf.py) and the
                    trend side: LONG when every trend timeframe is bullish, SHORT when bearish
    signals()       EW5 and EW3 results in one table with the risk to the stop
    stock_list()    one row per stock after the filters: trend, newest matching signal, stop %
    chart()         candles of one stock on one timeframe with all its signals (core/charts)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

from core import htf, universe

TIMEFRAMES = ("60m", "4hr", "1D", "1W")
DURATION = {"60m": pd.Timedelta(hours=1), "4hr": pd.Timedelta(hours=4), "1D": pd.Timedelta(days=1),
            "1W": pd.Timedelta(days=7)}
ARROW = {htf.BULLISH: "▲", htf.BEARISH: "▼", htf.NEUTRAL: "■", htf.UNKNOWN: "·"}
TREND_CHOICES = {"any": "Any trend", "up": "Uptrend (LONG side)", "down": "Downtrend (SHORT side)"}

# filters of the stock list (both apps save these with "Save filters")
DEFAULT_FILTERS: dict[str, Any] = {
    "trend": "any",                 # any / up / down (the trend side of the trend timeframes)
    "with_trend": True,             # only signals on the trend side (LONG in an uptrend, SHORT in a downtrend)
    "has_signal": True,             # only stocks with a matching signal in the last `days` days
    "days": 10,
    "strategies": [],               # ew5 / ew3 (empty = both)
    "timeframes": [],               # signal timeframes (empty = all)
    "sides": [],                    # LONG / SHORT
    "alignment": [],                # ALIGNED / MIXED / AGAINST / UNKNOWN
    "status": [],                   # TRIGGERED / NOT_TRIGGERED / ... (live screens have none)
    "max_risk": 0.0,                # biggest trigger → stop distance in %, 0 = no limit
    "attributes": {},               # column -> picked values (market cap, sector, F&O ...)
    "search": "",
}


def load_filters(path: Path) -> dict:
    """Saved filters over the defaults (a missing or broken file gives the defaults)."""
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULT_FILTERS, **{k: v for k, v in (saved if isinstance(saved, dict) else {}).items()
                                  if k in DEFAULT_FILTERS}}


def save_filters(path: Path, filters: dict) -> dict:
    clean = {k: filters.get(k, v) for k, v in DEFAULT_FILTERS.items()}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(clean, indent=1), encoding="utf-8")
    return clean


def active_filters(f: dict) -> list[str]:
    """Short names of the filters that are on (for the collapsed filter box's title)."""
    out = []
    if f.get("trend") in ("up", "down"):
        out.append("uptrend" if f["trend"] == "up" else "downtrend")
    if f.get("with_trend"):
        out.append("with the trend")
    if f.get("has_signal"):
        out.append(f"signal ≤ {f.get('days')} days")
    if float(f.get("max_risk") or 0) > 0:
        out.append(f"stop ≤ {f['max_risk']}%")
    for key in ("strategies", "timeframes", "sides", "alignment", "status"):
        if f.get(key):
            out.append(", ".join(str(v).upper() if key == "strategies" else str(v) for v in f[key]))
    out += [", ".join(map(str, v)) for v in (f.get("attributes") or {}).values() if v]
    if f.get("search"):
        out.append(f"“{f['search']}”")
    return out


# ----------------------------------------------------------------------------------
# Trend of every stock
# ----------------------------------------------------------------------------------
def snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """The last bar of every (Ticker, time_frame): time, Close, dtosck, dtoscd."""
    cols = [c for c in ("Ticker", "time_frame", "time", "Close", "dtosck", "dtoscd") if c in df.columns]
    if df.empty:
        return pd.DataFrame(columns=cols)
    last = df.groupby(["Ticker", "time_frame"], sort=False)["time"].idxmax()
    return df.loc[last.values, cols].reset_index(drop=True)


def trends(snap: pd.DataFrame, trend_frames: Sequence[str] = ("1D", "1W")) -> pd.DataFrame:
    """
    One row per ticker: trend_<tf> for every timeframe, close (daily, else the newest),
    as_of (newest bar) and trend_side: LONG when all trend_frames are BULLISH, SHORT when
    all are BEARISH, "" otherwise. The newest bar may still be forming (the live bar).
    """
    if snap.empty:
        return pd.DataFrame(columns=["close", "as_of", "trend_side", *[f"trend_{tf}" for tf in TIMEFRAMES]])
    s = snap.copy()
    missing = pd.Series(float("nan"), index=s.index)
    s["trend"] = htf.bar_trend(pd.to_numeric(s.get("dtosck", missing), errors="coerce"),
                               pd.to_numeric(s.get("dtoscd", missing), errors="coerce")).values
    out = s.pivot_table(index="Ticker", columns="time_frame", values="trend", aggfunc="last")
    out = out.reindex(columns=list(TIMEFRAMES)).astype(object).fillna(htf.UNKNOWN)
    out.columns = [f"trend_{tf}" for tf in out.columns]
    order = {tf: i for i, tf in enumerate(TIMEFRAMES)}
    s["rank"] = s["time_frame"].map(lambda tf: 0 if tf == "1D" else 1 + order.get(tf, 9))
    close = s.sort_values("rank").drop_duplicates("Ticker").set_index("Ticker")["Close"]
    out["close"] = close.reindex(out.index)
    out["as_of"] = s.groupby("Ticker")["time"].max().reindex(out.index)
    frames = [f"trend_{tf}" for tf in trend_frames if f"trend_{tf}" in out.columns]
    up = out[frames].eq(htf.BULLISH).all(axis=1) if frames else pd.Series(False, index=out.index)
    down = out[frames].eq(htf.BEARISH).all(axis=1) if frames else pd.Series(False, index=out.index)
    out["trend_side"] = ""
    out.loc[up, "trend_side"] = "LONG"
    out.loc[down, "trend_side"] = "SHORT"
    return out


def trend_text(row: pd.Series) -> str:
    """'60m ▲ · 4hr ▲ · 1D ▼ · 1W ▼'"""
    return " · ".join(f"{tf} {ARROW.get(row.get(f'trend_{tf}'), '·')}" for tf in TIMEFRAMES)


# ----------------------------------------------------------------------------------
# Signals of both strategies
# ----------------------------------------------------------------------------------
def signals(results: Sequence[tuple[Any, pd.DataFrame, str]]) -> pd.DataFrame:
    """
    (Strategy, results, file name) -> one table: strategy, Ticker, time_frame, degree,
    signal_time, side, status, trigger_time, entry_price, stop_time, TRIGGER, STOP,
    target1 / target2 (the strategy's two target cards), alignment, risk_pct, file, id.
    """
    parts = []
    for S, res, file in results:
        if res is None or res.empty:
            continue
        (_, t1), (_, t2) = S.target_cards
        get = lambda col: res[col] if col in res.columns else pd.Series(pd.NA, index=res.index)   # noqa: E731
        part = pd.DataFrame({
            "strategy": S.key, "Ticker": res["Ticker"], "time_frame": res["time_frame"], "degree": get("degree"),
            "signal_time": pd.to_datetime(res["signal_time"]), "side": res[S.side_col], "stage": get("stage"),
            "status": get("status"), "result": get("result"), "trigger_time": pd.to_datetime(get("trigger_time")),
            "entry_price": get("entry_price"), "stop_time": pd.to_datetime(get("stop_time")),
            "TRIGGER": res["TRIGGER"], "STOP": res["STOP"], "target1": get(t1), "target2": get(t2),
            "target1_name": t1, "target2_name": t2, "alignment": get("alignment").fillna(htf.UNKNOWN),
            "close": get("close"), "file": file, "id": res.index})
        parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["strategy", "Ticker", "time_frame", "signal_time", "side", "risk_pct"])
    out = pd.concat(parts, ignore_index=True)
    # the same signal in a backtest and a live screen: keep the copy with an outcome
    out = (out.assign(_has=out["status"].notna()).sort_values("_has", ascending=False, kind="stable")
              .drop_duplicates(["strategy", "Ticker", "time_frame", "degree", "signal_time", "side"])
              .drop(columns="_has").sort_index().reset_index(drop=True))
    trigger, stop = pd.to_numeric(out["TRIGGER"], errors="coerce"), pd.to_numeric(out["STOP"], errors="coerce")
    out["risk_pct"] = ((trigger - stop).abs() / trigger.abs() * 100).round(2)
    return out


def default_files(files: Sequence[Path]) -> list[Path]:
    """Newest backtest (history with outcomes) and newest live screen (today's setups)."""
    picked = []
    for kind in ("backtest", "live"):
        match = next((f for f in files if kind in Path(f).name), None)
        if match is not None:
            picked.append(match)
    return picked or list(files[:1])


# ----------------------------------------------------------------------------------
# The stock list
# ----------------------------------------------------------------------------------
def _match_signals(sig: pd.DataFrame, trend: pd.DataFrame, f: dict, now: pd.Timestamp) -> pd.DataFrame:
    if sig.empty:
        return sig
    s = sig[sig["signal_time"] >= now - pd.Timedelta(days=int(f.get("days") or 10))]
    for key, col in (("strategies", "strategy"), ("timeframes", "time_frame"), ("sides", "side"),
                     ("alignment", "alignment"), ("status", "status")):
        if f.get(key):
            s = s[s[col].astype(str).isin([str(v) for v in f[key]])]
    if float(f.get("max_risk") or 0) > 0:
        s = s[s["risk_pct"] <= float(f["max_risk"])]
    if f.get("with_trend"):
        side = s["Ticker"].map(trend["trend_side"]) if not trend.empty else pd.Series("", index=s.index)
        s = s[s["side"].eq(side)]
    return s


def stock_list(trend: pd.DataFrame, sig: pd.DataFrame, attrs: pd.DataFrame, filters: Optional[dict] = None,
               now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """
    One row per stock that passes the filters, best first: stocks whose newest matching
    signal is on the trend side, then the newest signals, then the smallest stop.
    """
    f = {**DEFAULT_FILTERS, **(filters or {})}
    now = pd.Timestamp(now) if now is not None else (
        sig["signal_time"].max() if not sig.empty and pd.notna(sig["signal_time"].max()) else pd.Timestamp.now())
    tickers = list(trend.index) if not trend.empty else []
    tickers += [t for t in dict.fromkeys(sig["Ticker"]) if t not in set(tickers)] if not sig.empty else []
    base = pd.DataFrame(index=pd.Index(tickers, name="Ticker"))
    base = base.join(trend) if not trend.empty else base
    for tf in TIMEFRAMES:
        base[f"trend_{tf}"] = base.get(f"trend_{tf}", pd.Series(htf.UNKNOWN, index=base.index)).fillna(htf.UNKNOWN)
    base["trend_side"] = base.get("trend_side", pd.Series("", index=base.index)).fillna("")

    matched = _match_signals(sig, trend, f, now)
    newest = (matched.sort_values("signal_time", ascending=False).drop_duplicates("Ticker").set_index("Ticker")
              if not matched.empty else pd.DataFrame())
    counts = matched.groupby("Ticker").size() if not matched.empty else pd.Series(dtype=int)
    base["signals"] = counts.reindex(base.index).fillna(0).astype(int)
    cols = ["strategy", "time_frame", "degree", "side", "signal_time", "status", "alignment", "TRIGGER", "STOP",
            "risk_pct", "target1"]
    for col in cols:
        base[f"sig_{col}"] = newest[col].reindex(base.index) if not newest.empty and col in newest else pd.NA
    if f.get("has_signal"):
        base = base[base["signals"] > 0]
    if f.get("trend") == "up":
        base = base[base["trend_side"].eq("LONG")]
    elif f.get("trend") == "down":
        base = base[base["trend_side"].eq("SHORT")]
    base = universe.attach(base.reset_index(), attrs).set_index("Ticker") if attrs is not None else base
    picks = {k: v for k, v in (f.get("attributes") or {}).items() if v}
    if picks:
        base = base[universe.mask(base, picks)]
    if f.get("search"):
        base = base[base.index.str.contains(str(f["search"]).strip(), case=False, regex=False)]
    base["with_trend"] = base["sig_side"].astype("object").eq(base["trend_side"]) & base["trend_side"].ne("")
    base = base.sort_values(["with_trend", "sig_signal_time", "sig_risk_pct"], ascending=[False, False, True],
                            na_position="last")
    return base


def table(rows: pd.DataFrame, limit: Optional[int] = None) -> pd.DataFrame:
    """The stock list as shown (same columns on both apps)."""
    out = pd.DataFrame(index=rows.index)
    out["Trend"] = [trend_text(r) for _, r in rows.iterrows()]
    out["Trend side"] = rows["trend_side"].replace("", "–")
    out["Signal"] = [
        "" if pd.isna(r["sig_strategy"]) else
        f"{str(r['sig_strategy']).upper()} {r['sig_time_frame']} {r['sig_side']}"
        for _, r in rows.iterrows()]
    out["Signal time"] = pd.to_datetime(rows["sig_signal_time"]).dt.strftime("%d %b %H:%M")
    out["With trend"] = rows["with_trend"].map({True: "✅", False: ""})
    out["Alignment"] = rows["sig_alignment"]
    out["Status"] = rows["sig_status"]
    out["Trigger"] = pd.to_numeric(rows["sig_TRIGGER"], errors="coerce").round(2)
    out["Stop"] = pd.to_numeric(rows["sig_STOP"], errors="coerce").round(2)
    out["Stop %"] = pd.to_numeric(rows["sig_risk_pct"], errors="coerce").round(2)
    out["Signals"] = rows["signals"]
    out["Close"] = pd.to_numeric(rows.get("close"), errors="coerce").round(2)
    for col in ("marketcapname", "cnx_sector_name", "fno_enabled"):
        if col in rows.columns:
            out[universe.ATTR_LABELS.get(col, col)] = rows[col]
    out = out.reset_index()
    return out.head(limit) if limit else out


# ----------------------------------------------------------------------------------
# One stock's chart
# ----------------------------------------------------------------------------------
def bar_of(times: pd.Series, when: Any, source_tf: str) -> Optional[pd.Timestamp]:
    """
    The bar (of `times`, sorted) holding the END of a `source_tf` bar starting at `when`:
    a 60m signal at 13:15 is on that day's 1D bar; a 1D signal is on the day's last 60m bar.
    """
    if when is None or pd.isna(when) or times.empty:
        return None
    end = pd.Timestamp(when) + DURATION.get(source_tf, pd.Timedelta(0))
    k = int(times.searchsorted(end, side="left")) - 1
    return pd.Timestamp(times.iloc[k]) if 0 <= k < len(times) else None


def ticker_signals(sig: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Every signal of one stock, newest first."""
    if sig.empty:
        return sig
    return sig[sig["Ticker"].eq(ticker)].sort_values("signal_time", ascending=False)


def signal_label(r: pd.Series) -> str:
    """'EW5 60m SHORT · 16 Nov 13:15 · TRIGGERED · stop 1.1%'"""
    status = "" if pd.isna(r.get("status")) else f" · {r['status']}"
    risk = "" if pd.isna(r.get("risk_pct")) else f" · stop {r['risk_pct']:.1f}%"
    return (f"{str(r['strategy']).upper()} {r['time_frame']} {r['side']} · "
            f"{pd.Timestamp(r['signal_time']):%d %b %Y %H:%M}{status}{risk}")
