"""Plotly figures for the dashboard: signal candlestick with wave overlay, and breakdowns."""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import elliott_wave5_screener as ew

# Dark-surface palette (validated categorical order: blue, orange, aqua)
C = dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
         axis="#383835", blue="#3987e5", orange="#d95926", aqua="#199e70", yellow="#c98500",
         magenta="#d55181", violet="#9085e9", red="#e66767", critical="#d03b3b")

STATUS_ORDER = ("TRIGGERED", "EXTENDED", "NOT_TRIGGERED", "NO_DATA")
STATUS_COLOR = {"TRIGGERED": C["blue"], "EXTENDED": C["orange"], "NOT_TRIGGERED": C["aqua"],
                "NO_DATA": C["muted"]}
SIDE_COLOR = {"SHORT": C["blue"], "LONG": C["orange"]}

# Level groups that can be switched on/off: name -> [(level, colour, dash)]
LEVEL_GROUPS: dict[str, list[tuple[str, str, str]]] = {
    "Trigger / Stop": [("TRIGGER", C["orange"], "solid"), ("STOP", C["critical"], "solid")],
    "W4": [("W4_END", C["yellow"], "dash")],
    "Fib zone": [(n, C["ink2"], "dot") for n in ("FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854")],
    "W5 targets": [(n, C["muted"], "dashdot")
                   for n in ("W5_TGT_0.618xW1", "W5_TGT_1.000xW1", "W5_TGT_1.618xW1")],
}
_LEVEL_LABEL = {"STOP": "STOP / W5_END"}
EMA_GROUP = "EMA 13 / 55"
EMA_COLOURS = ("#fab219", C["magenta"])              # fast, slow
# One indicator pane under the price chart, 0-100 scale: series name -> stock.csv columns
PANE_SERIES: dict[str, tuple[str, ...]] = {
    "rsi": ("rsi",), "dtosc": ("dtosck", "dtoscd"), "histogram": ("histogram",)}
PANE_BANDS = (30, 70)                                # dashed guide lines; the middle is 50
HIST_LIMIT = 20                                      # histogram bars are drawn only beyond +/- this
GOOD, BAD = "#2fbf71", C["red"]                      # histogram below -20 / above +20
_LABEL_GAP_PX = 12                      # minimum vertical distance between level labels


def _base_layout(fig: go.Figure, height: int, title: str = "") -> go.Figure:
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=C["surface"], plot_bgcolor=C["surface"],
        font=dict(color=C["ink2"], size=12), height=height,
        title=dict(text=title, font=dict(color=C["ink"], size=15), x=0.01, xanchor="left"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(color=C["ink2"])),
        margin=dict(l=50, r=30, t=60, b=40), hoverlabel=dict(bgcolor="#0d0d0d"),
    )
    fig.update_xaxes(gridcolor=C["grid"], linecolor=C["axis"], zeroline=False)
    fig.update_yaxes(gridcolor=C["grid"], linecolor=C["axis"], zeroline=False)
    return fig


# ----------------------------------------------------------------------------------
# Wave overlay (re-run the engine up to the signal bar)
# ----------------------------------------------------------------------------------
def wave_overlay(price: pd.DataFrame, signal_time: Any, length: int, pivot_tie: str = "strict",
                 hi_source: str = "high", lo_source: str = "low") -> Optional[dict]:
    """
    Wave points as timestamps for one ticker/timeframe, as the engine sees them at
    `signal_time`. Returns {"dir", "pts": [(time, price)] * 6, "abc": [(label, time, price)]}.
    """
    g = (price[price["time"] <= pd.Timestamp(signal_time)]
         .dropna(subset=["High", "Low", "Close"]).sort_values("time").reset_index(drop=True))
    if g.empty:
        return None
    eng = ew.ElliottWaveEngine(g["High"], g["Low"], g["Close"], int(length), hi_source=hi_source,
                               lo_source=lo_source, open_=g["Open"], pivot_tie=pivot_tie)
    for i in range(eng.n):
        eng.step(i)
    snap = eng.snapshot(eng.n - 1)
    if snap is None:
        return None
    times = g["time"]
    wave = eng.waves[0]
    abc = [(label, times.iat[pt[0]], float(pt[1]))
           for label, pt in zip("abc", (wave.a, wave.b, wave.c)) if pt is not None]
    return {"dir": snap["dir"], "pts": [(times.iat[x], float(y)) for x, y in snap["pts"]], "abc": abc}


# ----------------------------------------------------------------------------------
# Signal chart
# ----------------------------------------------------------------------------------
def signal_chart(price: pd.DataFrame, row: pd.Series, overlay: Optional[dict], horizon_bars: int,
                 bars_before: int, groups: Sequence[str], height: int,
                 emas: Sequence[tuple[str, str]] = (), panes: Sequence[str] = (),
                 pane_height: int = 170) -> go.Figure:
    """
    Candlestick for one signal. The x-axis is a category axis (one slot per bar), so
    nights, weekends and holidays leave no gaps. `panes` (keys of PANE_SERIES) are drawn
    together in ONE indicator pane below the price (0-100 scale, `pane_height` px high).
    """
    p = price.sort_values("time").reset_index(drop=True)
    t_sig = pd.Timestamp(row["signal_time"])
    i_sig = max(int(p["time"].searchsorted(t_sig, side="right")) - 1, 0)
    i0 = max(0, i_sig - bars_before)
    if overlay:
        i_w0 = int(p["time"].searchsorted(overlay["pts"][0][0], side="left"))
        i0 = max(0, min(i0, i_w0 - 5))
    i1 = min(len(p) - 1, i_sig + horizon_bars)
    win = p.iloc[i0:i1 + 1]

    fmt = "%d %b %Y" if row["time_frame"] == "1D" else "%d %b %Y %H:%M"
    labels = win["time"].dt.strftime(fmt).tolist()
    visible = set(win["time"])

    def lab(t: Any) -> str:
        return pd.Timestamp(t).strftime(fmt)

    panes = [name for name in panes
             if all(c in win.columns for c in PANE_SERIES[name])
             and win[list(PANE_SERIES[name])].notna().any().any()]
    has_pane = bool(panes)
    total_height = height + (pane_height if has_pane else 0)
    fig = make_subplots(rows=2 if has_pane else 1, cols=1, shared_xaxes=True, vertical_spacing=0.022,
                        row_heights=[height, pane_height] if has_pane else [height])
    fig.add_trace(go.Candlestick(
        x=labels, open=win["Open"], high=win["High"], low=win["Low"], close=win["Close"],
        name="Price", increasing_line_color=C["aqua"], decreasing_line_color=C["red"],
        increasing_fillcolor=C["aqua"], decreasing_fillcolor=C["red"], line_width=1))

    # ---- moving averages: (label, stock.csv column), fast one first
    for (label, column), colour in zip(emas, EMA_COLOURS):
        if column in win.columns and win[column].notna().any():
            fig.add_trace(go.Scatter(x=labels, y=win[column], mode="lines", name=label,
                                     line=dict(color=colour, width=1.5),
                                     hovertemplate=f"{label}: %{{y:,.2f}}<extra></extra>"))

    # ---- wave count
    if overlay:
        bull = overlay["dir"] == 1
        pts = [(t, y, k) for k, (t, y) in enumerate(overlay["pts"]) if t in visible]
        fig.add_trace(go.Scatter(
            x=[lab(t) for t, _, _ in pts], y=[y for _, y, _ in pts], mode="lines+markers+text",
            name="Impulse 1-5", line=dict(color=C["blue"], width=2), marker=dict(size=8),
            text=["0" if k == 0 else f"({k})" for _, _, k in pts],
            textposition=["top center" if (k % 2 == 1) == bull else "bottom center" for _, _, k in pts],
            textfont=dict(color=C["ink"], size=13)))
        abc = [(lbl, t, y) for lbl, t, y in overlay["abc"] if t in visible]
        if abc:
            t5, y5 = overlay["pts"][5]
            xs, ys = [lab(t5)] + [lab(t) for _, t, _ in abc], [y5] + [y for _, _, y in abc]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines+markers+text", name="Correction a-b-c",
                line=dict(color=C["violet"], width=2, dash="dash"), marker=dict(size=8),
                text=[""] + [f"({lbl})" for lbl, _, _ in abc],
                textposition=[""] + ["bottom center" if (k % 2 == 0) == bull else "top center"
                                     for k in range(len(abc))],
                textfont=dict(color=C["ink"], size=13)))

    # ---- horizontal levels (labels are added after the y-range is known)
    y_values = [win["Low"].min(), win["High"].max()]
    level_labels: list[tuple[float, str]] = []
    for group in groups:
        for name, colour, dash in LEVEL_GROUPS[group]:
            value = row.get(name)
            if pd.isna(value):
                continue
            y_values.append(float(value))
            level_labels.append((float(value), f"{_LEVEL_LABEL.get(name, name)}  {value:,.2f}"))
            fig.add_hline(y=float(value), line=dict(color=colour, width=1.2, dash=dash), row=1, col=1)

    # ---- signal bar and evaluation window (category axis: positions are bar numbers)
    k_sig = i_sig - i0
    if i1 > i_sig:
        fig.add_shape(type="rect", xref="x", yref="paper", x0=k_sig, x1=len(labels) - 0.5,
                      y0=0, y1=1, fillcolor=C["blue"], opacity=0.07, line_width=0, layer="below")
    fig.add_shape(type="line", xref="x", yref="paper", x0=k_sig, x1=k_sig, y0=0, y1=1,
                  line=dict(color=C["ink2"], width=1, dash="dot"))
    fig.add_annotation(x=k_sig, xref="x", y=1, yref="paper", yanchor="bottom", showarrow=False,
                       text="signal", font=dict(size=11, color=C["ink2"]))

    # ---- outcome markers
    short = row.get("reversal_side") == "SHORT"
    events: list[tuple[Any, Any, str, str, str]] = [
        (row.get("trigger_time"), row.get("entry_price"), "Trigger (entry)",
         "triangle-down" if short else "triangle-up", C["orange"]),
        (row.get("stop_time"), row.get("STOP"), "Stopped", "x", C["critical"]),
    ]
    events += [(row.get(f"hit_{tg}_time"), row.get(tg), f"Hit {tg}", "star", C["yellow"])
               for tg in ("W4_END", "FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854")]
    for when, level, name, symbol, colour in events:
        if when is None or pd.isna(when) or pd.isna(level) or pd.Timestamp(when) not in visible:
            continue
        fig.add_trace(go.Scatter(
            x=[lab(when)], y=[float(level)], mode="markers", name=name,
            marker=dict(symbol=symbol, size=13, color=colour, line=dict(color=C["surface"], width=2)),
            hovertemplate=f"{name}<br>%{{x}}<br>%{{y:,.2f}}<extra></extra>"))

    # ---- indicator pane: everything on one 0-100 layer
    if has_pane:
        sig_row = win.iloc[k_sig]
        readings: list[str] = []
        if "histogram" in panes:
            # histogram = RSI - 50, so it is drawn from the 50 line; only the extreme bars are shown
            values = win["histogram"]
            extreme = values.abs() > HIST_LIMIT
            fig.add_trace(go.Bar(
                x=[x for x, keep in zip(labels, extreme) if keep], y=values[extreme], base=50,
                name="Histogram", marker_color=[GOOD if v < 0 else BAD for v in values[extreme]],
                marker_line_width=0, opacity=0.75, showlegend=False, customdata=values[extreme],
                hovertemplate="Histogram: %{customdata:.1f}<extra></extra>"), row=2, col=1)
        lines = []
        if "rsi" in panes:
            lines.append(("rsi", "RSI 14", C["violet"]))
        if "dtosc" in panes:
            lines += [("dtosck", "DTosc K", C["blue"]), ("dtoscd", "DTosc D", C["orange"])]
        for column, label, colour in lines:
            fig.add_trace(go.Scatter(x=labels, y=win[column], mode="lines", name=label,
                                     line=dict(color=colour, width=1.6),
                                     hovertemplate=f"{label}: %{{y:.1f}}<extra></extra>"), row=2, col=1)
            if pd.notna(sig_row[column]):
                readings.append(f"{label} {sig_row[column]:.1f}")
        if "histogram" in panes and pd.notna(sig_row["histogram"]):
            readings.append(f"Histogram {sig_row['histogram']:.1f}")
        fig.add_hrect(y0=PANE_BANDS[0], y1=PANE_BANDS[1], fillcolor=C["violet"], opacity=0.06,
                      line_width=0, layer="below", row=2, col=1)
        for level in PANE_BANDS:
            fig.add_hline(y=level, line=dict(color=C["muted"], width=1, dash="dash"), row=2, col=1)
        fig.add_hline(y=50, line=dict(color=C["axis"], width=1, dash="dot"), row=2, col=1)
        fig.update_yaxes(range=[0, 100], tickmode="array", tickvals=[PANE_BANDS[0], 50, PANE_BANDS[1]],
                         fixedrange=True, showgrid=False, row=2, col=1)
        fig.add_annotation(xref="paper", x=0.004, xanchor="left", yref="y2 domain", y=0.98,
                           yanchor="top", showarrow=False, text="  ·  ".join(readings),
                           font=dict(size=11, color=C["ink2"]), bgcolor="rgba(26,26,25,0.75)")

    title = (f"{row['Ticker']} · {row['time_frame']} · {row.get('degree', '')} · "
             f"{row.get('impulse', '')} impulse → {row.get('reversal_side', '')} reversal")
    _base_layout(fig, total_height, title)
    lo, hi = min(y_values), max(y_values)
    pad = (hi - lo) * 0.04 or 1.0
    lo, hi = lo - pad, hi + pad
    margin_top, margin_bottom = 95, 50      # room for the title above the legend row
    fig.update_layout(margin=dict(r=175, t=margin_top, b=margin_bottom), hovermode="x unified",
                      hoversubplots="axis", xaxis_rangeslider_visible=False, bargap=0.15)
    step = max(1, len(labels) // 8)
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=labels,
                     tickmode="array", tickvals=labels[::step],
                     ticktext=win["time"].dt.strftime("%d %b %Y").tolist()[::step],   # short: no overlap
                     tickangle=0, showgrid=False)
    fig.update_yaxes(range=[lo, hi], side="left", tickformat=",.2f", row=1, col=1)
    fig.update_layout(legend=dict(xanchor="left", x=0))               # keeps clear of the "signal" label

    # level labels on the right edge, nudged apart so close levels stay readable
    domain = fig.layout.yaxis.domain                                  # share of the plot area used by price
    px_per_unit = (total_height - margin_top - margin_bottom) * (domain[1] - domain[0]) / (hi - lo)
    placed = -1e9
    for value, text in sorted(level_labels):
        pixel = (value - lo) * px_per_unit
        placed = max(pixel, placed + _LABEL_GAP_PX)
        fig.add_annotation(xref="paper", x=1, xanchor="left", yref="y", y=value, yshift=placed - pixel,
                           text=text, showarrow=False, xshift=4,
                           font=dict(size=10, color=C["ink2"]))
    return fig


# ----------------------------------------------------------------------------------
# Breakdown charts (every bar carries `customdata` so a click can filter the table)
# ----------------------------------------------------------------------------------
def _stacked_counts(res: pd.DataFrame, by: str, order: Sequence[str], colours: dict[str, str],
                    height: int, title: str) -> go.Figure:
    """Stacked bars per time_frame × degree. customdata of a bar = [time_frame, degree, value of `by`]."""
    table = res.groupby(["time_frame", "degree", by]).size().unstack(by, fill_value=0)
    x = [f"{tf}<br>{degree}" for tf, degree in table.index]
    fig = go.Figure()
    for key in [k for k in order if k in table.columns] + [k for k in table.columns if k not in order]:
        fig.add_trace(go.Bar(
            x=x, y=table[key], name=key, marker_color=colours.get(key, C["muted"]),
            marker_line=dict(color=C["surface"], width=2),
            customdata=[[tf, degree, key] for tf, degree in table.index],
            hovertemplate=f"{key}: %{{y}}<extra>%{{customdata[0]}} · %{{customdata[1]}}</extra>"))
    _base_layout(fig, height, title)
    fig.update_layout(barmode="stack", bargap=0.45, clickmode="event+select")
    fig.update_xaxes(showgrid=False, tickangle=0)
    fig.update_yaxes(title_text="signals")
    return fig


def outcome_breakdown(res: pd.DataFrame, height: int = 360) -> go.Figure:
    """Stacked bar: outcome status by time_frame × degree."""
    return _stacked_counts(res, "status", STATUS_ORDER, STATUS_COLOR, height,
                           "Outcome by timeframe × degree")


def side_breakdown(res: pd.DataFrame, height: int = 360) -> go.Figure:
    """Stacked bar for live screens: signals by time_frame × degree, split by reversal side."""
    return _stacked_counts(res, "reversal_side", ("SHORT", "LONG"), SIDE_COLOR, height,
                           "Signals by timeframe × degree")


def mfe_mae_distribution(res: pd.DataFrame, height: int = 360, bins: int = 20) -> go.Figure:
    """
    Two histograms on a shared y-axis: best (MFE) and worst (MAE) move after entry.
    Bars are pre-binned; customdata of a bar = [column, bin low, bin high].
    """
    trig = res[res["status"].eq("TRIGGERED")]
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=("MFE % (best move)", "MAE % (worst move)"))
    for col, (name, column, colour) in enumerate(
            (("MFE %", "mfe_pct", C["blue"]), ("MAE %", "mae_pct", C["orange"])), start=1):
        values = trig[column].dropna().to_numpy()
        if len(values) == 0:
            continue
        counts, edges = np.histogram(values, bins=bins)
        keep = counts > 0
        lows, highs = edges[:-1][keep], edges[1:][keep]
        fig.add_trace(go.Bar(
            x=(lows + highs) / 2, y=counts[keep], width=(highs - lows) * 0.92, name=name,
            marker_color=colour, marker_line=dict(color=C["surface"], width=1),
            customdata=[[column, float(a), float(b)] for a, b in zip(lows, highs)],
            hovertemplate="%{customdata[1]:.1f}% to %{customdata[2]:.1f}%: %{y} signals<extra></extra>"),
            row=1, col=col)
    _base_layout(fig, height, "MFE / MAE of triggered signals")
    fig.update_layout(showlegend=False, clickmode="event+select")
    fig.update_yaxes(title_text="signals", col=1)
    return fig


def picked_bars(fig: go.Figure, points: Sequence[dict]) -> list[list]:
    """customdata of the bars named in a Streamlit plotly selection (looked up in the figure)."""
    out = []
    for point in points:
        try:
            out.append(list(fig.data[int(point["curve_number"])].customdata[int(point["point_index"])]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out
