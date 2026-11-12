"""
The desktop signal chart (core/charts.signal_chart, a Plotly figure) converted for
TradingView Lightweight Charts, which the phone uses for pinch-zoom, pan and price-axis
scaling like TradingView.

Nothing is recomputed here: every candle, line, wave point, level, marker and indicator
value is read from the same figure the desktop draws, so both charts show the same thing.

    price pane   candles, EMA 13 / 55, wave 0-5 (+ a-b-c), level lines, entry / stop / target
                 markers, the signal bar and the shaded evaluation window
    lower pane   RSI, DTosc K / D on 0-100 (bands 30 / 50 / 70), histogram bars beyond +/-20
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

# Plotly dash name -> Lightweight Charts LineStyle (0 solid, 1 dotted, 2 dashed, 3 large dashed)
DASH = {"solid": 0, None: 0, "dot": 1, "dash": 2, "dashdot": 3, "longdash": 3}
SHAPE = {"triangle-up": "arrowUp", "triangle-down": "arrowDown", "x": "square", "star": "circle"}
SHORT = [(r"^STOP / W\d_END", "STOP"), (r"^W0_START.*", "W0"), (r"^TRIGGER", "TRIG"),
         (r"^W(\d)_END", r"W\1"), (r"^FIB_0(\.\d+)", r"F\1"), (r"^W\d_TGT_(\d\.\d+)xW1", r"T\1"),
         (r"^W2_RET_0(\.\d+)", r"R\1")]


def short_level(name: str) -> str:
    """'W5_TGT_1.618xW1' -> 'T1.618', 'FIB_0.500' -> 'F.500', 'TRIGGER' -> 'TRIG' ..."""
    for pattern, repl in SHORT:
        name = re.sub(pattern, repl, name)
    return name


def _epoch(t: Any) -> int:
    """IST wall-clock time as seconds 'in UTC', so the chart's axis shows IST as stored."""
    return int(pd.Timestamp(t).tz_localize("UTC").timestamp())


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else round(f, 4)


def convert(fig, price: pd.DataFrame, time_frame: str) -> dict:
    """Plotly signal chart -> Lightweight Charts spec (plain JSON)."""
    from core.charts import DAY_FRAMES
    fmt = "%d %b %Y" if time_frame in DAY_FRAMES else "%d %b %Y %H:%M"     # same labels as signal_chart
    when = {t.strftime(fmt): _epoch(t) for t in pd.to_datetime(price["time"])}

    def times(xs) -> list[Optional[int]]:
        return [when.get(str(x)) for x in xs]

    out: dict[str, Any] = {"title": fig.layout.title.text or "", "intraday": time_frame not in DAY_FRAMES,
                           "candles": [], "lines": [], "waves": [], "markers": [], "levels": [],
                           "bands": [], "hist": [], "pane": False}
    candle_times: list[int] = []
    for tr in fig.data:
        yaxis = getattr(tr, "yaxis", None) or "y"
        pane = 1 if yaxis == "y2" else 0
        if tr.type == "candlestick":
            candle_times = times(tr.x)
            out["candles"] = [{"time": t, "open": _num(o), "high": _num(h), "low": _num(lo), "close": _num(c)}
                              for t, o, h, lo, c in zip(candle_times, tr.open, tr.high, tr.low, tr.close) if t]
            out["up"], out["down"] = tr.increasing.line.color, tr.decreasing.line.color
        elif tr.type == "bar" and pane == 1:                      # histogram, drawn from the 50 line
            out["hist"] = [{"time": t, "value": _num(v), "color": c}
                           for t, v, c in zip(times(tr.x), tr.y, tr.marker.color) if t and _num(v) is not None]
            out["pane"] = True
        elif tr.type == "scatter":
            mode = tr.mode or ""
            pts = [{"time": t, "value": _num(v)} for t, v in zip(times(tr.x), tr.y) if t and _num(v) is not None]
            if mode == "lines":                                   # EMAs and the indicator lines
                out["lines"].append({"name": tr.name, "color": tr.line.color, "width": tr.line.width or 1.5,
                                     "pane": pane, "data": pts})
                out["pane"] = out["pane"] or pane == 1
            elif "lines" in mode:                                 # wave count 0-5 / a-b-c
                labels = list(tr.text or [])
                where = tr.textposition if isinstance(tr.textposition, (list, tuple)) else [tr.textposition] * len(pts)
                out["waves"].append({
                    "name": tr.name, "color": tr.line.color, "style": DASH.get(tr.line.dash, 0), "data": pts,
                    "labels": [{"time": p["time"], "price": p["value"], "text": str(text),
                                "position": "atPriceTop" if str(pos).startswith("top") else "atPriceBottom"}
                               for p, text, pos in zip(pts, labels, where) if str(text)]})
            else:                                                 # entry / stop / target hits
                symbol = tr.marker.symbol
                name = str(tr.name)
                text = ("Entry" if name.startswith("Trigger") else "Stop" if name.startswith("Stop")
                        else "Hit " + short_level(name[4:]) if name.startswith("Hit ") else name)
                for p in pts:
                    out["markers"].append({"time": p["time"], "price": p["value"], "name": name, "text": text,
                                           "shape": SHAPE.get(symbol, "circle"), "color": tr.marker.color})

    # ---- horizontal lines (levels on the price pane, 30 / 50 / 70 on the indicator pane)
    labels = {round(float(a.y), 6): a.text for a in fig.layout.annotations
              if a.xref == "paper" and a.x == 1 and a.yref == "y" and a.text}
    for s in fig.layout.shapes:
        if s.type != "line" or s.y0 is None or s.y0 != s.y1 or not str(s.xref).endswith("domain"):
            continue
        if s.yref == "y":
            name, _, value = labels.get(round(float(s.y0), 6), "").partition("  ")
            out["levels"].append({"price": float(s.y0), "color": s.line.color, "style": DASH.get(s.line.dash, 0),
                                  "title": short_level(name), "full": name})
        elif s.yref == "y2":
            out["bands"].append({"price": float(s.y0), "style": DASH.get(s.line.dash, 0)})

    # ---- signal bar and the evaluation window after it (category x = bar number)
    for s in fig.layout.shapes:
        if s.xref == "x" and candle_times:
            k = int(round(float(s.x0)))
            if 0 <= k < len(candle_times):
                out["signal_time"] = candle_times[k]
    readings = [a.text for a in fig.layout.annotations if str(a.yref).endswith("domain") and a.text]
    out["readings"] = readings[0] if readings else ""
    out["markers"].sort(key=lambda m: m["time"])
    return out
