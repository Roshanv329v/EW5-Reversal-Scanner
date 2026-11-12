"""
The logic of app.py (Streamlit) as JSON endpoints for the phone's page.

Every number, filter, stat card, chart and table comes from the same core modules the
desktop uses (runner, strategies, charts, prefs, data_store, htf); this file only turns
their results into JSON. Function names follow the desktop tabs:

    dashboard(), chart()                      EW5 and EW3 tabs
    data_summary(), data_preview(), start_*   Data tab
    run_options(), run_check(), start_run()   Run / Backtest tab
    guide()                                   User Guide tab
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew
import stock_data
from core import charts, data_store as ds, htf, prefs, runner, strategies
from core.config import ROOT, load_config
from core.strategies import Strategy
from mobile import jobs, resources, scan
from mobile.fetch import yahoo_fetch
from mobile.store import N_PARTS, Store

ICONS = {"monitoring": "📊", "rocket_launch": "🚀", "flag": "🚩", "target": "🎯", "trending_up": "📈",
         "trending_down": "📉", "bolt": "⚡", "shield": "🛡️", "north_east": "↗️", "south_east": "↘️",
         "radar": "📡"}
PREVIEW_ROWS = 2000            # Data tab preview (desktop: 5,000)
RUN_ROWS = 300                 # rows of a fresh run shown in the Run tab


# ----------------------------------------------------------------------------------
# Set-up: config with every path inside the app's storage
# ----------------------------------------------------------------------------------
class App:
    def __init__(self, root: Path):
        self.root = Path(root)
        cfg = load_config()
        data = self.root / "data"
        cfg.update(tickers_file=data / "tickers.csv", stock_csv=data / "stock.csv",
                   backups_dir=data / "backups", results_dir=self.root / "results", logs_dir=self.root / "logs",
                   dashboard_filters_file=data / "dashboard_filters.json",
                   dashboard_filters_file_ew3=data / "dashboard_filters_ew3.json", backups_keep=1)
        self.cfg = cfg
        for d in (data, cfg["results_dir"], cfg["logs_dir"]):
            d.mkdir(parents=True, exist_ok=True)
        seed = resources.read("seed/tickers.csv")
        if not cfg["tickers_file"].exists() and seed:
            cfg["tickers_file"].write_bytes(seed)
        ds.setup_logging(cfg["logs_dir"])
        self.store = Store(cfg)
        self.last_report: Optional[dict] = None
        self.last_run: Optional[str] = None


APP: Optional[App] = None


def init(root: str) -> None:
    global APP
    APP = App(Path(root))


def _app() -> App:
    assert APP is not None, "mobile.api.init() was not called"
    return APP


# ----------------------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------------------
def clean(value: Any) -> Any:
    """Anything pandas / numpy -> plain JSON values (NaN -> None, times -> text)."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return None if pd.isna(value) else str(pd.Timestamp(value))
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) or math.isinf(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NaT or (not isinstance(value, (str, bytes)) and pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return value


def label(text: str) -> str:
    """':material/flag: W4 target hit' -> '🚩 W4 target hit'."""
    return re.sub(r":material/([a-z_]+):", lambda m: ICONS.get(m.group(1), ""), text).strip()


def fig_json(fig) -> dict:
    return json.loads(fig.to_json())


def table(df: pd.DataFrame, max_rows: Optional[int] = None, decimals: int = 2) -> dict:
    """Columns + rows as display text (2 decimals, times without seconds), like the desktop tables."""
    view = df if max_rows is None else df.head(max_rows)
    cols = [str(c) for c in view.columns]
    rows = [[_cell(v, decimals) for v in r] for r in view.itertuples(index=False, name=None)]
    return {"columns": cols, "rows": rows, "total": len(df)}


def _cell(v: Any, decimals: int = 2) -> Any:
    if v is None or (not isinstance(v, (str, list, dict)) and pd.api.types.is_scalar(v) and pd.isna(v)):
        return ""
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        t = pd.Timestamp(v)
        return t.strftime("%Y-%m-%d") if (t.hour, t.minute, t.second) == (0, 0, 0) else t.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return f"{float(v):.{decimals}f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(map(str, v))
    return str(v)


@lru_cache(maxsize=6)
def _results(path: str, mtime: float) -> tuple[pd.DataFrame, dict]:
    return runner.load_results(Path(path))


def load_results(path: Path) -> tuple[pd.DataFrame, dict]:
    return _results(str(path), path.stat().st_mtime)


# ----------------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------------
def state() -> dict:
    a = _app()
    last = a.store.last_time()
    return clean({
        "tickers": len(a.store.tickers()) if not a.store.empty() else 0,
        "data_to": last.strftime("%d %b %Y") if last is not None else None,
        "saved_runs": len(runner.list_results(a.cfg["results_dir"])),
        "job": jobs.current(),
        "strategies": [{"key": S.key, "name": S.name, "tab": label(S.tab)} for S in strategies.STRATEGIES.values()],
    })


# ----------------------------------------------------------------------------------
# Saved filters (same files and format as the desktop)
# ----------------------------------------------------------------------------------
def _filter_columns(S: Strategy) -> list[str]:
    return [col for col, _ in S.filter_cols]


def _prefs_path(S: Strategy) -> Path:
    return _app().cfg[S.prefs_file_key]


def get_prefs(key: str) -> dict:
    S = strategies.get(key)
    path = _prefs_path(S)
    return {"prefs": prefs.load_prefs(path, _filter_columns(S)), "saved": path.exists(),
            "default": prefs.default_prefs(_filter_columns(S))}


def save_prefs(key: str, values: dict) -> dict:
    S = strategies.get(key)
    prefs.save_prefs(_prefs_path(S), values, _filter_columns(S))
    return {"ok": True, "note": "Saved. This dashboard will open like this from now on."}


# ----------------------------------------------------------------------------------
# Dashboard (render_dashboard in app.py)
# ----------------------------------------------------------------------------------
def _fmt(value: float, suffix: str = "%") -> str:
    return "–" if value is None or pd.isna(value) else f"{value:.1f}{suffix}"


def dashboard(req: dict) -> dict:
    a = _app()
    S = strategies.get(req.get("key"))
    out: dict[str, Any] = {"key": S.key, "name": S.name, "blurb": S.blurb,
                           "filter_cols": [[c, lbl] for c, lbl in S.filter_cols], "ratio_col": S.ratio_col,
                           "level_groups": list(S.level_groups), "side_col": S.side_col}
    files = runner.list_results(a.cfg["results_dir"], S.key)
    names = [f.name for f in files]
    out["files"] = names
    if not files:
        out["info"] = (f"No {S.key.upper()} results yet. In the Run / Backtest tab choose "
                       f"{S.name} and run a screen or backtest.")
        return out
    chosen = req.get("file") if req.get("file") in names else names[0]
    out["file"] = chosen
    res, meta = load_results(a.cfg["results_dir"] / chosen)
    params = meta.get("params", {})
    mode_name = runner.MODES.get(params.get("mode", ""), "Run")
    period = (params.get("as_of") or
              (f"{params.get('start')} → {params.get('end')}" if params.get("start") else "latest bar"))
    extra = (f" · retrace {params.get('min_retrace')}–{params.get('max_retrace')}"
             f" · contexts {', '.join(params.get('contexts', []))}" if S.key == "ew3" else "")
    out["caption"] = [f"{mode_name} · {period} · lengths {params.get('lengths', '?')} · "
                      f"horizon {params.get('horizon_bars', '?')} bars · pivot_tie {params.get('pivot_tie', '?')}",
                      f"stages {', '.join(params.get('stages', []))}{extra}"]
    if res.empty:
        out["info"] = "This run produced no signals."
        return out

    # ---- filters (same rules as _filters in app.py)
    picks: dict[str, list] = req.get("filters") or {}
    options = {}
    for col, _ in S.filter_cols:
        present = sorted(map(str, res[col].dropna().unique())) if col in res.columns else []
        options[col] = present + [v for v in picks.get(col, []) if v not in present]
    out["options"] = options
    out["disabled"] = [col for col, _ in S.filter_cols if col not in res.columns]

    view = res
    for col, chosen_values in picks.items():
        if chosen_values and col in view.columns:
            view = view[view[col].astype(str).isin([str(v) for v in chosen_values])]
    search = (req.get("search") or "").strip()
    if search:
        view = view[view["Ticker"].str.contains(search, case=False, regex=False)]
    ratio = res[S.ratio_col].dropna() if S.ratio_col in res.columns else pd.Series(dtype=float)
    lo, hi = (float(ratio.min()), float(ratio.max())) if len(ratio) else (0.0, 1.0)
    pref = req.get("ratio") or [None, None]
    if hi > lo:
        out["ratio"] = {"lo": lo, "hi": hi, "value": list(prefs.ratio_range(pref, lo, hi))}
        low, high = pref
        if low is not None:
            view = view[view[S.ratio_col] >= float(low)]
        if high is not None:
            view = view[view[S.ratio_col] <= float(high)]
    filtered = view
    out["counts"] = {"total": len(res), "filtered": len(filtered)}
    if filtered.empty:
        out["warning"] = "No signals match the filters."
        return clean(out)

    # ---- stat cards
    evaluated = runner.has_outcomes(res)
    out["evaluated"] = evaluated
    if evaluated:
        k, masks = S.kpis(filtered), S.stat_masks(filtered)
        active = req.get("stat") if req.get("stat") in masks else None
        (t1_label, _), (t2_label, _) = S.target_cards
        out["stat"] = active
        out["signals"] = k["signals"]
        out["cards"] = [
            {"name": n, "label": label(lbl), "value": val, "tip": tip, "count": int(masks[n].sum())}
            for lbl, val, n, tip in (
                (":material/bolt: Trigger rate", _fmt(k["trigger_rate"]), "triggered",
                 "Signals whose close broke the TRIGGER level"),
                (S.fail_card[0], _fmt(k["fail_pct"]), "failed", S.fail_card[1]),
                (t1_label, _fmt(k["t1_hit_rate"]), "t1", "Of triggered signals"),
                (t2_label, _fmt(k["t2_hit_rate"]), "t2", "Of triggered signals"),
                (":material/shield: Stop rate", _fmt(k["stop_rate"]), "stopped", "Of triggered signals"),
                (":material/north_east: Avg MFE", _fmt(k["avg_mfe"]), "mfe",
                 "Average best move after entry. The button keeps triggered signals at or above it."),
                (":material/south_east: Avg MAE", _fmt(k["avg_mae"]), "mae",
                 "Average worst move after entry. The button keeps triggered signals at or below it."))]
        view = filtered[masks[active]] if active else filtered
    else:
        fields = [("By timeframe", "time_frame"), ("By degree", "degree"), ("By side", S.side_col)]
        if "alignment" in filtered.columns:
            fields.append(("By HTF alignment", "alignment"))
        live_picks = req.get("live") or {}
        out["signals"] = len(filtered)
        out["live_cards"] = []
        view = filtered
        for lbl, field in fields:
            counts = filtered[field].value_counts()
            pick = live_picks.get(field) if live_picks.get(field) in counts.index else None
            out["live_cards"].append({"label": lbl, "field": field, "pick": pick,
                                      "counts": [[str(v), int(n)] for v, n in counts.items()]})
            if pick is not None:
                view = view[view[field] == pick]

    # ---- breakdown charts (a tapped bar narrows the table)
    bars = req.get("bars") or {}
    notes: list[str] = []
    mask = pd.Series(True, index=filtered.index)
    figures: dict[str, Any] = {}
    if evaluated:
        figures["outcome"] = fig_json(charts.outcome_breakdown(filtered))
        figures["mfemae"] = fig_json(charts.mfe_mae_distribution(filtered))
        if bars.get("outcome"):
            mask &= runner.bar_mask(filtered, "status", bars["outcome"])
            notes += [f"{tf} {degree} {value}" for tf, degree, value in bars["outcome"]]
        if bars.get("mfemae"):
            mask &= runner.range_mask(filtered, bars["mfemae"])
            notes += [f"{'MFE' if col == 'mfe_pct' else 'MAE'} {float(low):.1f}% to {float(high):.1f}%"
                      for col, low, high in bars["mfemae"]]
        if "alignment" in filtered.columns:
            stats = S.alignment_stats(filtered)
            (t1_label, _), (t2_label, _) = S.target_cards
            figures["align"] = fig_json(charts.alignment_breakdown(
                stats, label(t1_label).split(" ", 1)[-1], label(t2_label).split(" ", 1)[-1]))
            out["align_table"] = table(stats.rename(columns={
                "alignment": "Alignment", "signals": "Signals", "trigger_rate": "Trigger %", "fail_pct": "Failed %",
                "t1_hit_rate": "Target 1 %", "t2_hit_rate": "Target 2 %", "stop_rate": "Stop %",
                "avg_mfe": "Avg MFE %", "avg_mae": "Avg MAE %"}), decimals=1)
            if bars.get("align"):
                names = [b[0] for b in bars["align"]]
                mask &= filtered["alignment"].isin(names)
                notes += [f"HTF {n}" for n in names]
        out["summary_table"] = table(S.summarize(filtered))
    else:
        figures["sides"] = fig_json(charts.side_breakdown(filtered, by=S.side_col))
        if bars.get("sides"):
            mask &= runner.bar_mask(filtered, S.side_col, bars["sides"])
            notes += [f"{tf} {degree} {value}" for tf, degree, value in bars["sides"]]
    out["figures"] = figures
    out["notes"] = notes
    if notes:
        view = view[mask.loc[view.index]]
    view = view.sort_values("signal_time", ascending=False, kind="stable")       # newest first

    # ---- signal table
    cols = [c for c in (*S.table_cols, *a.cfg["signal_indicators"]) if c in view.columns]
    t = table(view[cols])
    t["ids"] = [int(i) for i in view.index]
    out["table"] = t
    out["counts"]["view"] = len(view)
    out["narrowed"] = len(view) < len(filtered)
    return clean(out)


# ----------------------------------------------------------------------------------
# Signal chart (_signal_chart / _open_chart_overlay in app.py)
# ----------------------------------------------------------------------------------
@lru_cache(maxsize=64)
def _overlay(ticker: str, time_frame: str, signal_time: str, length: int, pivot_tie: str, hi: str, lo: str,
             mtime: float) -> Optional[dict]:
    price = _app().store.ticker_bars(ticker, time_frame)
    return charts.wave_overlay(price, signal_time, length, pivot_tie, hi, lo)


def _htf_note(row: pd.Series) -> str:
    if pd.isna(row.get("alignment")):
        return ""
    parents = _app().cfg["htf"]["ladder"].get(row["time_frame"], [])
    trends = [f"{tf} {row[col]}" for tf, col in zip(parents, htf.TREND_COLS) if pd.notna(row.get(col))]
    return " · ".join([str(row["alignment"]), *trends])


_SHORT = [(r"^STOP / W\d_END", "STOP"), (r"^W0_START.*", "W0"), (r"^TRIGGER", "TRIG"),
          (r"^W(\d)_END", r"W\1"), (r"^FIB_0(\.\d+)", r"F\1"), (r"^W\d_TGT_(\d\.\d+)xW1", r"T\1"),
          (r"^W2_RET_0(\.\d+)", r"R\1")]


def _narrow(fig) -> None:
    """
    Phone portrait (~360 px): the same chart, laid out for the width. Legend drawn by the
    page under the chart, title on two lines, short level labels (TRIG, STOP, W4, F.500, T1.618, R.382)
    so the right margin is small and the candles keep the room.
    """
    title = fig.layout.title.text or ""
    parts = title.split(" · ")
    if len(parts) > 3:
        title = " · ".join(parts[:3]) + "<br>" + " · ".join(parts[3:])
    fig.update_layout(title=dict(text=title, font_size=12), font_size=10, showlegend=False,
                      margin=dict(l=46, r=84, t=78, b=40))       # the page draws the legend under the chart
    for name in [k for k in fig.layout.to_plotly_json() if k.startswith("xaxis")]:
        axis = fig.layout[name]
        if axis.tickvals:                                   # every third date, so they do not overlap
            fig.layout[name].update(tickvals=list(axis.tickvals)[::3], ticktext=list(axis.ticktext)[::3], tickfont_size=9)
    for ann in fig.layout.annotations:
        if ann.yref and str(ann.yref).endswith("domain"):   # the indicator readings line
            ann.update(font_size=8)
        if ann.xref == "paper" and ann.x == 1 and ann.text:
            name, _, value = ann.text.partition("  ")
            for pattern, repl in _SHORT:
                name = re.sub(pattern, repl, name)
            try:
                number = float(value.replace(",", ""))
                value = f"{number:,.0f}" if abs(number) >= 1000 else f"{number:,.2f}"
            except ValueError:
                pass
            ann.update(text=f"{name} {value}", font_size=8, xshift=2)


def chart(req: dict) -> dict:
    a = _app()
    S = strategies.get(req.get("key"))
    path = a.cfg["results_dir"] / str(req["file"])
    res, meta = load_results(path)
    params = meta.get("params", {})
    row = res.loc[int(req["id"])]
    engine, chart_cfg = a.cfg["engine"], a.cfg["chart"]
    compact = bool(req.get("compact"))
    groups = [g for g in S.level_groups if g in (req.get("groups") or [])]
    emas = ([("EMA 13", chart_cfg["ema_fast"]), ("EMA 55", chart_cfg["ema_slow"])] if req.get("ema", True) else [])
    out: dict[str, Any] = {
        "heading": [row["Ticker"], row["time_frame"], row["degree"], row[S.side_col]],
        "dialog_title": f"{S.key.upper()} · {row['Ticker']} · {row['time_frame']} · {row['degree']} · {row[S.side_col]}",
        "htf": _htf_note(row), "alignment": row.get("alignment"),
    }
    facts = [("Signal", pd.Timestamp(row["signal_time"]).strftime("%d %b %Y %H:%M")),
             ("Close", f"{row['close']:,.2f}"),
             *((lbl, f"{row[level]:,.2f}") for lbl, level in S.fact_levels)]
    if pd.notna(row.get("status")):
        facts.append(("Outcome", row["status"] if pd.isna(row.get("result")) else f"{row['status']} · {row['result']}"))
    if out["htf"]:
        facts.append(("Higher timeframes", out["htf"]))
    out["facts"] = facts

    price = a.store.ticker_bars(row["Ticker"], row["time_frame"])
    if price.empty:
        out["warning"] = f"No {row['time_frame']} bars for {row['Ticker']} in the stored data - cannot draw the chart."
    else:
        if S.overlay_from_row is not None:
            overlay = S.overlay_from_row(row)
        else:
            overlay = _overlay(row["Ticker"], row["time_frame"], str(row["signal_time"]), int(row["zigzag_length"]),
                               params.get("pivot_tie", engine["pivot_tie"]), params.get("hi_source", engine["hi_source"]),
                               params.get("lo_source", engine["lo_source"]), a.store.mtime())
        narrow = bool(req.get("narrow"))
        fig = charts.signal_chart(
            price, row, overlay, horizon_bars=int(params.get("horizon_bars", engine["horizon_bars"])),
            bars_before=int(chart_cfg["bars_before"]), groups=groups,
            height=int(chart_cfg["overlay_height" if (compact or narrow) else "height"]), emas=emas,
            panes=chart_cfg["indicator_panes"] if req.get("ind", True) else (),
            pane_height=int(chart_cfg["overlay_pane_height" if (compact or narrow) else "pane_height"]),
            level_groups=S.level_groups, level_labels=S.level_labels, targets=S.targets,
            side_col=S.side_col, wave_name=S.wave_name, title=S.chart_title(row))
        if narrow:
            _narrow(fig)
        out["figure"] = fig_json(fig)
        if overlay is None:
            out["note"] = "The engine has no wave count at this bar, so only price and levels are shown."

    level_names = list(S.level_names)
    fields = row.drop(labels=[c for c in [*level_names, S.levels_col] if c in row.index])
    out["fields"] = [[str(k), str(v)] for k, v in fields.items()]
    out["levels"] = [[n, _cell(row.get(n))] for n in level_names]
    out["live_count"] = row["live_count"] if pd.notna(row.get("live_count")) else "–"
    return clean(out)


# ----------------------------------------------------------------------------------
# Data tab
# ----------------------------------------------------------------------------------
def _stock_tickers(pasted: str = "") -> list[str]:
    if pasted.strip():
        return ds.parse_ticker_text(pasted)
    path = _app().cfg["tickers_file"]
    return ds.clean_tickers(stock_data.read_stock_tickers(path)) if path.exists() else []


def get_tickers() -> dict:
    stocks = _stock_tickers()
    return {"text": "\n".join(stocks), "count": len(stocks), "indices": len(stock_data.indian_index),
            "commodities": len(stock_data.commodity)}


def save_tickers(text: str) -> dict:
    stocks = ds.parse_ticker_text(text)
    ds.write_tickers(_app().cfg["tickers_file"], stocks)
    return {"ok": True, "count": len(stocks)}


def data_summary() -> dict:
    a = _app()
    out: dict[str, Any] = {"timeframes": a.cfg["timeframes"], "incremental_days": int(a.cfg["incremental_days"]),
                           "short_history_bars": int(a.cfg["short_history_bars"]), "report": a.last_report,
                           "parts": len(a.store.part_paths()), "size_mb": a.store.size_mb(),
                           "import_ready": (a.root / "data" / "import_stock.csv").exists(),
                           **{k: v for k, v in get_tickers().items() if k != "text"}}
    if a.store.empty():
        out["empty"] = True
        return clean(out)
    summary = a.store.timeframe_summary()
    stored = set(a.store.tickers())
    listed = stock_data.build_final_list(_stock_tickers())
    out["new_tickers"] = [t for t in listed if t not in stored]
    out["has_weekly"] = a.cfg["htf"]["weekly"]["name"] in set(summary["time_frame"])
    out["weekly"] = a.cfg["htf"]["weekly"]["name"]
    out["coverage"] = table(summary)
    per = a.store.bars_per_ticker(int(a.cfg["short_history_bars"]), skip=(a.cfg["htf"]["weekly"]["name"],))
    out["n_short"] = int(per["short_history"].sum())
    out["per_ticker"] = table(per.sort_values("short_history", ascending=False))
    out["stored_tickers"] = sorted(stored)
    out["stored_timeframes"] = sorted(summary["time_frame"])
    return clean(out)


def data_preview(req: dict) -> dict:
    view, total = _app().store.preview(req.get("tickers") or [], req.get("timeframes") or [],
                                       bool(req.get("newest", True)), PREVIEW_ROWS)
    t = table(view, decimals=4)
    t["total"] = total
    return clean(t)


def _report_json(report: ds.UpdateReport) -> dict:
    stats = report.stats
    return clean({"rows_before": report.rows_before, "rows_after": report.rows_after,
                  "added": int(stats["added"].sum()) if not stats.empty else 0,
                  "replaced": int(stats["replaced"].sum()) if not stats.empty else 0,
                  "stats": table(stats) if not stats.empty else None, "failed": report.failed,
                  "saved": report.saved, "log": report.log})


def start_update(req: dict) -> dict:
    a = _app()
    pasted = req.get("pasted") or ""
    stocks = _stock_tickers(pasted)
    tfs = [tf for tf in (req.get("timeframes") or a.cfg["timeframes"]) if tf in a.cfg["timeframes"]]
    if not stocks:
        raise ValueError("No stock tickers to download.")
    if not tfs:
        raise ValueError("Pick at least one timeframe.")
    if pasted.strip() and req.get("save_pasted"):
        ds.write_tickers(a.cfg["tickers_file"], stocks)
    tickers = stock_data.build_final_list(stocks)
    full = bool(req.get("full"))
    days = int(req.get("days") or a.cfg["incremental_days"])

    def work(job: jobs.Job) -> dict:
        job.say(f"{len(tickers)} tickers · {', '.join(tfs)} · "
                f"{'FULL re-download' if full else f'incremental {days}d (new tickers: full history)'}")
        report = a.store.update(tickers, tfs, days, full, yahoo_fetch, progress=job.progress)
        a.last_report = _report_json(report)
        return a.last_report

    return jobs.start("update", "Full re-download" if full else "Data update", work)


def start_weekly() -> dict:
    a = _app()

    def work(job: jobs.Job) -> dict:
        rows = 0
        paths = a.store.part_paths()
        for n, path in enumerate(paths):
            job.progress(n / len(paths), f"part {n + 1}/{len(paths)}")
            rows += ds.rebuild_weekly(dict(a.cfg, stock_csv=path, backups_dir=path.parent / "backups" / path.stem))
        return {"weekly_rows": rows}

    return jobs.start("weekly", "Build weekly bars", work)


def start_import() -> dict:
    a = _app()
    src = a.root / "data" / "import_stock.csv"
    if not src.exists():
        raise ValueError("No stock.csv to import. Pick one with the Import button first.")

    def work(job: jobs.Job) -> dict:
        rows = a.store.import_csv(src, progress=job.progress)
        src.unlink(missing_ok=True)
        if a.cfg["htf"]["weekly"]["name"] not in set(a.store.timeframe_summary()["time_frame"]):
            job.say("No weekly bars in the imported file: building them")
            for path in a.store.part_paths():
                ds.rebuild_weekly(dict(a.cfg, stock_csv=path, backups_dir=path.parent / "backups" / path.stem))
        return {"rows": rows, "parts": len(a.store.part_paths())}

    return jobs.start("import", "Import stock.csv", work)


# ----------------------------------------------------------------------------------
# Run / Backtest tab
# ----------------------------------------------------------------------------------
def _first_last() -> tuple[Optional[str], Optional[str]]:
    a = _app()
    s = a.store.timeframe_summary()
    if s.empty:
        return None, None
    return str(pd.Timestamp(s["first_bar"].min()).date()), str(pd.Timestamp(s["last_bar"].max()).date())


def run_options() -> dict:
    a = _app()
    engine, ew3_cfg = a.cfg["engine"], a.cfg["ew3"]
    first, last = _first_last()
    available = sorted(a.store.timeframe_summary()["time_frame"]) if not a.store.empty() else []
    last_ts = pd.Timestamp(last) if last else None
    return clean({
        "empty": a.store.empty(), "first_day": first, "last_day": last,
        "default_asof": str(max(pd.Timestamp(first), last_ts - pd.Timedelta(days=60)).date()) if last else None,
        "default_start": str(max(pd.Timestamp(first), last_ts - pd.Timedelta(days=365)).date()) if last else None,
        "modes": [[k, v] for k, v in runner.MODES.items()],
        "strategies": [{"key": S.key, "name": S.name, "blurb": S.blurb, "stages": list(S.stages),
                        "default_stages": ew3_cfg["stages"] if S.key == "ew3" else engine["stages"]}
                       for S in strategies.STRATEGIES.values()],
        "timeframes": available,
        "default_timeframes": [tf for tf in available if tf in a.cfg["timeframes"]] or available,
        "weekly": a.cfg["htf"]["weekly"]["name"],
        "lengths": [[n, f"{n} ({ew.DEGREE_NAMES.get(n, '')})"] for n in ew.DEFAULT_LENGTHS],
        "default_lengths": engine["lengths"], "horizon_bars": int(engine["horizon_bars"]),
        "pivot_ties": ["strict", "left_equal"], "pivot_tie": engine["pivot_tie"],
        "hi_sources": list(runner.HI_SOURCES), "lo_sources": list(runner.LO_SOURCES),
        "hi_source": engine["hi_source"], "lo_source": engine["lo_source"],
        "min_w5_vs_w1": float(engine["min_w5_vs_w1"]), "min_bars": int(a.cfg["min_bars"]),
        "contexts": list(ew3.CONTEXTS), "default_contexts": ew3_cfg["contexts"],
        "min_retrace": float(ew3_cfg["min_retrace"]), "max_retrace": float(ew3_cfg["max_retrace"]),
        "last_run": a.last_run,
    })


def _params(req: dict) -> tuple[runner.RunParams, list[str]]:
    a = _app()
    mode, key = req.get("mode", "live"), req.get("strategy", "ew5")
    problems = []
    if not req.get("timeframes"):
        problems.append("Pick at least one timeframe.")
    if not req.get("lengths"):
        problems.append("Pick at least one ZigZag length.")
    if not req.get("stages"):
        problems.append("Pick at least one stage.")
    if key == "ew3" and not req.get("contexts"):
        problems.append("Pick at least one context.")
    if mode == "backtest" and req.get("start") and req.get("end") and req["start"] > req["end"]:
        problems.append("Start date is after the end date.")
    max_since = req.get("max_since")
    p = runner.RunParams(
        mode=mode, timeframes=tuple(req.get("timeframes") or ()), lengths=tuple(sorted(int(x) for x in req.get("lengths") or ())),
        stages=tuple(req.get("stages") or ()), horizon_bars=int(req.get("horizon_bars") or a.cfg["engine"]["horizon_bars"]),
        max_bars_since_w5=None if max_since in (None, "") else int(max_since),
        min_w5_vs_w1=float(req.get("min_w5_vs_w1") or 0.0),
        resignal_on_extension=bool(req.get("resignal") and mode == "backtest"),
        pivot_tie=req.get("pivot_tie", "strict"), hi_source=req.get("hi_source", "high"),
        lo_source=req.get("lo_source", "low"), min_bars=int(a.cfg["min_bars"]),
        as_of=req.get("as_of") if mode == "asof" else None,
        start=req.get("start") if mode == "backtest" else None, end=req.get("end") if mode == "backtest" else None,
        strategy=key, contexts=tuple(req.get("contexts") or ew3.DEFAULT_CONTEXTS),
        min_retrace=float(req.get("min_retrace", ew3.DEFAULT_MIN_RETRACE)),
        max_retrace=float(req.get("max_retrace", ew3.DEFAULT_MAX_RETRACE)),
        aligned_only=bool(req.get("aligned_only")))
    return p, problems


def run_check(req: dict) -> dict:
    """Validation messages and the short-history warning shown above the Run button."""
    a = _app()
    p, problems = _params(req)
    out: dict[str, Any] = {"problems": problems}
    if problems or a.store.empty():
        return out
    if p.mode == "asof":
        cutoff, when = runner.end_of_day(p.as_of), f"on {p.as_of}"
    elif p.mode == "backtest":
        cutoff, when = pd.Timestamp(p.start) - pd.Timedelta(seconds=1), f"before {p.start}"
    else:
        cutoff, when = a.store.last_time(), "in the stored data"
    short = pd.concat([runner.check_min_bars(df, cutoff, p.min_bars, p.timeframes) for df in a.store.frames()],
                      ignore_index=True)
    if not short.empty:
        note = "The backtest only signals once a series has enough bars." if p.mode == "backtest" \
            else "These are skipped by the engine."
        out["short_warning"] = (f"{len(short)} ticker/timeframe pair(s) have fewer than {p.min_bars} bars "
                                f"{when}. {note}")
        out["short"] = table(short.sort_values(["time_frame", "Ticker"]))
    return clean(out)


def start_run(req: dict) -> dict:
    a = _app()
    p, problems = _params(req)
    if problems:
        raise ValueError(" ".join(problems))
    if a.store.empty():
        raise ValueError("Download data first (Data tab).")
    S = strategies.get(p.strategy)

    def work(job: jobs.Job) -> dict:
        n = len(a.store.part_paths())
        job.say(f"{S.name} · {runner.MODES[p.mode]} · {', '.join(p.timeframes)} · {n} parts of ~{240 // N_PARTS} tickers")
        res = scan.run_groups(a.store.frames(), n, p, a.cfg["signal_indicators"], a.cfg["htf"],
                              progress=lambda i, total: job.progress(i / max(total, 1),
                                                                     f"Elliott Wave engine · part {min(i + 1, total)}/{total}"))
        saved = runner.save_results(res, p, a.cfg["results_dir"], a.store.dir)
        a.last_run = saved.name
        job.say(f"{len(res)} signal(s) saved to results/{saved.name}")
        return {"file": saved.name, "strategy": S.key, "rows": len(res)}

    return jobs.start("run", f"Run {S.key.upper()}", work)


def last_run() -> dict:
    a = _app()
    if not a.last_run or not (a.cfg["results_dir"] / a.last_run).exists():
        return {}
    path = a.cfg["results_dir"] / a.last_run
    res, _ = load_results(path)
    S = strategies.get(runner.strategy_of(path))
    summary = runner.summarize(res, S.key)
    shown = res.drop(columns=[c for c in (S.levels_col,) if c in res.columns])
    return clean({"file": path.name, "strategy": S.key, "rows": len(res),
                  "summary": table(summary) if not summary.empty else None, "signals": table(shown, RUN_ROWS)})


def result_path(name: str) -> Optional[Path]:
    a = _app()
    path = (a.cfg["results_dir"] / Path(name).name)
    return path if path.exists() and path.suffix == ".csv" else None


# ----------------------------------------------------------------------------------
# User Guide
# ----------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def guide() -> dict:
    import markdown
    out = {}
    for key, name in (("functional", "functional_guide.md"), ("technical", "technical_guide.md"),
                      ("phone", "phone_guide.md")):
        raw = resources.read(f"docs/{name}")                    # copied in by the Android build
        if raw is None and (ROOT / "docs" / name).exists():     # desktop test run
            raw = (ROOT / "docs" / name).read_bytes()
        if raw is not None:
            out[key] = markdown.markdown(raw.decode("utf-8"), extensions=["tables", "fenced_code"])
    return out
