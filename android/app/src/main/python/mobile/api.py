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
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew
import stock_data
from core import alert_events, charts, data_store as ds, eligibility, htf, overview, prefs, runner, strategies, universe
from core.config import ROOT, load_config
from core.strategies import Strategy
from mobile import alerts, jobs, lwchart, resources, scan, workers
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
                   dashboard_filters_file_ew3=data / "dashboard_filters_ew3.json",
                   stock_charts_filters_file=data / "stock_charts_filters.json", backups_keep=1)
        self.cfg = cfg
        for d in (data, cfg["results_dir"], cfg["logs_dir"]):
            d.mkdir(parents=True, exist_ok=True)
        seed = resources.read("seed/tickers.csv")
        path = cfg["tickers_file"]
        if seed and (not path.exists() or (not universe.has_attributes(universe.load_attributes(path))
                                           and b"fno_enabled" in seed[:300])):
            # first start, or a list from before the attribute columns: use the bundled one (old kept)
            if path.exists():
                shutil.copy(path, path.with_name("tickers_before_attributes.csv"))
            path.write_bytes(seed)
        ds.setup_logging(cfg["logs_dir"])
        self.store = Store(cfg)
        self.last_report: Optional[dict] = None
        self.last_run: Optional[str] = None


APP: Optional[App] = None


def warm_up() -> None:
    """Right after start, in the background: part summaries and the newest results of each tab."""
    try:
        a = _app()
        a.store.timeframe_summary()
        for key in strategies.STRATEGIES:
            files = runner.list_results(a.cfg["results_dir"], key)
            if files:
                load_results(files[0])
        if any(runner.needs_retag(*runner.load_results(f)) for f in runner.list_results(a.cfg["results_dir"])):
            jobs.start("retag", "Updating trend tags", lambda job: retag_old_results(job))
    except Exception:                      # only a head start; the real calls do the same work
        pass


def retag_old_results(job: Optional[jobs.Job] = None) -> int:
    """
    Results saved before the DTosc trend rule get their higher-timeframe columns worked out
    again. One pass over the data parts serves every old file. Returns the files updated.
    """
    a = _app()
    todo = []
    for f in runner.list_results(a.cfg["results_dir"]):
        res, meta = runner.load_results(f)
        if runner.needs_retag(res, meta):
            todo.append((f, res, meta, strategies.get(runner.strategy_of(f)).side_col))
    if not todo:
        return 0
    done: list[list[pd.DataFrame]] = [[] for _ in todo]
    paths = a.store.part_paths()
    for n, frame in enumerate(a.store.frames()):
        if job:
            job.progress(n / max(len(paths), 1), f"part {n + 1}/{len(paths)} · {len(todo)} file(s)")
        tickers = set(frame["Ticker"].unique())
        for i, (_, res, _, side) in enumerate(todo):
            part = res[res["Ticker"].isin(tickers)]
            if not part.empty:
                done[i].append(htf.retag(part, frame, side, a.cfg["htf"]))
    for (f, res, meta, side), parts in zip(todo, done):
        new = pd.concat(parts) if parts else res.iloc[0:0]
        rest = res.drop(index=new.index)                           # tickers with no stored bars any more
        if not rest.empty:
            rest = htf.retag(rest, ds.empty_frame().reindex(columns=ds.SCHEMA), side, a.cfg["htf"])
        runner.rewrite_results(f, pd.concat([new, rest]).sort_index(), meta)
    _results.cache_clear()
    return len(todo)


def init(root: str) -> None:
    global APP
    APP = App(Path(root))
    alerts.load_settings(APP)                 # writes the default schedule for the Android scheduler


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
    """Saved-filter columns: the strategy's filters and the stock attributes (tickers.csv)."""
    return [col for col, _ in S.filter_cols] + list(universe.ATTR_COLS)


@lru_cache(maxsize=2)
def _attributes(path: str, mtime: float) -> pd.DataFrame:
    return universe.load_attributes(Path(path))


def attributes() -> pd.DataFrame:
    path = _app().cfg["tickers_file"]
    return _attributes(str(path), path.stat().st_mtime) if path.exists() else universe.load_attributes(path)


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
                      f"stages {', '.join(params.get('stages', []))}{extra} · "
                      f"{universe.UNIVERSES.get(params.get('universe', 'all'), 'All stocks')}"]
    if res.empty:
        out["info"] = "This run produced no signals."
        return out

    # ---- filters (same rules as _filters in app.py); stock attributes joined from tickers.csv
    res = universe.attach(res, attributes())
    res = eligibility.assess(res, S, a.cfg["fno_5day"])          # F&O 5-day grade (config: fno_5day)
    picks: dict[str, list] = req.get("filters") or {}
    options = {}
    attr_cols = [(c, universe.ATTR_LABELS[c]) for c in universe.ATTR_COLS]
    for col, _ in [*S.filter_cols, *attr_cols]:
        if col in universe.ATTR_COLS:                 # as written in tickers.csv (indices / commodities: none)
            present = universe.options(res[col]) if col in res.columns else []
        else:
            present = sorted(map(str, res[col].dropna().unique())) if col in res.columns else []
        options[col] = present + [v for v in picks.get(col, []) if v not in present]
    out["options"] = options
    out["attr_cols"] = [[c, lbl] for c, lbl in attr_cols]
    out["fno5_help"] = eligibility.summary(a.cfg["fno_5day"])
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

    # ---- drill-down 1: charts by stock attribute. Each chart shows what the charts before it
    # left; the result feeds the stat cards, the breakdown charts and the table.
    bars = req.get("bars") or {}
    notes: list[str] = []
    picked: dict[str, list] = {}
    for col, value in bars.get("attr") or []:
        picked.setdefault(col, []).append(value)
    attr_figs = {}
    for col in universe.CHART_COLS:
        attr_figs[col] = fig_json(charts.attribute_breakdown(filtered, col, universe.ATTR_LABELS[col], S.side_col))
        if picked.get(col):
            filtered = filtered[universe.mask(filtered, {col: picked[col]})]
            notes.append(f"{universe.ATTR_LABELS[col]} {', '.join(picked[col])}")
    out["attr_figures"] = attr_figs
    out["counts"]["filtered"] = len(filtered)
    if filtered.empty:
        out.update(notes=notes, figures={}, warning="No signals behind this chart selection.")
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

    # ---- drill-down 2: breakdown charts, each on what the one before it left; the table follows
    figures: dict[str, Any] = {}
    drill = filtered
    if evaluated:
        figures["outcome"] = fig_json(charts.outcome_breakdown(drill))
        if bars.get("outcome"):
            drill = drill[runner.bar_mask(drill, "status", bars["outcome"])]
            notes += [f"{tf} {degree} {value}" for tf, degree, value in bars["outcome"]]
        if not drill.empty:
            figures["mfemae"] = fig_json(charts.mfe_mae_distribution(drill))
        if bars.get("mfemae"):
            drill = drill[runner.range_mask(drill, bars["mfemae"])]
            notes += [f"{'MFE' if col == 'mfe_pct' else 'MAE'} {float(low):.1f}% to {float(high):.1f}%"
                      for col, low, high in bars["mfemae"]]
        if "alignment" in drill.columns and not drill.empty:
            stats = S.alignment_stats(drill)
            (t1_label, _), (t2_label, _) = S.target_cards
            figures["align"] = fig_json(charts.alignment_breakdown(
                stats, label(t1_label).split(" ", 1)[-1], label(t2_label).split(" ", 1)[-1]))
            out["align_table"] = table(stats.rename(columns={
                "alignment": "Alignment", "signals": "Signals", "trigger_rate": "Trigger %", "fail_pct": "Failed %",
                "t1_hit_rate": "Target 1 %", "t2_hit_rate": "Target 2 %", "stop_rate": "Stop %",
                "avg_mfe": "Avg MFE %", "avg_mae": "Avg MAE %"}), decimals=1)
            if bars.get("align"):
                names = [b[0] for b in bars["align"]]
                drill = drill[drill["alignment"].isin(names)]
                notes += [f"HTF {n}" for n in names]
        out["summary_table"] = table(S.summarize(drill if not drill.empty else filtered))
    else:
        figures["sides"] = fig_json(charts.side_breakdown(drill, by=S.side_col))
        if bars.get("sides"):
            drill = drill[runner.bar_mask(drill, S.side_col, bars["sides"])]
            notes += [f"{tf} {degree} {value}" for tf, degree, value in bars["sides"]]
    out["figures"] = figures
    out["notes"] = notes
    view = view[view.index.isin(drill.index)]
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
        "tradingview": alert_events.tradingview_url(row["Ticker"], row["time_frame"]),
    }
    facts = [("Signal", pd.Timestamp(row["signal_time"]).strftime("%d %b %Y %H:%M")),
             ("Close", f"{row['close']:,.2f}"),
             *((lbl, f"{row[level]:,.2f}") for lbl, level in S.fact_levels)]
    if pd.notna(row.get("status")):
        facts.append(("Outcome", row["status"] if pd.isna(row.get("result")) else f"{row['status']} · {row['result']}"))
    if out["htf"]:
        facts.append(("Higher timeframes", out["htf"]))
    graded = eligibility.assess(universe.attach(res.loc[[int(req["id"])]], attributes()), S, a.cfg["fno_5day"]).iloc[0]
    out["fno5"] = graded["fno5"]
    hold = ""
    if graded["fno5"] in eligibility.GRADES:
        end = eligibility.exit_by(row.get("trigger_time"), int(a.cfg["fno_5day"].get("max_days", 5))) \
            if pd.notna(row.get("trigger_time")) else None
        hold = (f" · exit by the close of {end:%a %d %b}" if end is not None
                else f" · hold at most {a.cfg['fno_5day'].get('max_days', 5)} trading days after the trigger")
    out["fno5_note"] = (f"{eligibility.LABEL.get(graded['fno5'], graded['fno5'])} — {graded['fno5_reason']} · stop "
                        f"{graded['fno5_stop_pct']:.1f}% · target {graded['fno5_rr']:.1f}× risk{hold}")
    out["facts"] = facts

    bars = a.store.ticker_bars(row["Ticker"])
    price = bars[bars["time_frame"] == row["time_frame"]]
    have = set(bars["time_frame"].unique())
    options = [tf for tf in chart_cfg["timeframes"] if tf in have] or [row["time_frame"]]
    if row["time_frame"] not in options:
        options.append(row["time_frame"])
    view_tf = req.get("tf") if req.get("tf") in options else row["time_frame"]
    out.update(timeframes=options, signal_tf=row["time_frame"], view_tf=view_tf)
    if price.empty:
        out["warning"] = f"No {row['time_frame']} bars for {row['Ticker']} in the stored data - cannot draw the chart."
    else:
        if S.overlay_from_row is not None:
            overlay = S.overlay_from_row(row)
        else:
            overlay = _overlay(row["Ticker"], row["time_frame"], str(row["signal_time"]), int(row["zigzag_length"]),
                               params.get("pivot_tie", engine["pivot_tie"]), params.get("hi_source", engine["hi_source"]),
                               params.get("lo_source", engine["lo_source"]), a.store.mtime())
        small = compact or bool(req.get("narrow"))
        horizon, title, had_waves, shown = (int(params.get("horizon_bars", engine["horizon_bars"])),
                                            S.chart_title(row), overlay is not None, row)
        if view_tf != row["time_frame"]:          # same signal on another timeframe (desktop: same helper)
            view = bars[bars["time_frame"] == view_tf]
            shown, overlay, horizon = charts.on_timeframe(row, overlay, price, view, view_tf, horizon, S.targets)
            price, title = view, f"{title} · chart {view_tf}"
            out["tf_note"] = (f"{row['time_frame']} signal shown on {view_tf} bars: levels unchanged; the signal bar, "
                              f"wave points and entry / stop / target markers are on the {view_tf} bars that contain them.")
        fig = charts.signal_chart(
            price, shown, overlay, horizon_bars=horizon,
            bars_before=int(chart_cfg["bars_before"]), groups=groups,
            height=int(chart_cfg["overlay_height" if small else "height"]), emas=emas,
            panes=chart_cfg["indicator_panes"] if req.get("ind", True) else (),
            pane_height=int(chart_cfg["overlay_pane_height" if small else "pane_height"]),
            level_groups=S.level_groups, level_labels=S.level_labels, targets=S.targets,
            side_col=S.side_col, wave_name=S.wave_name, title=title)
        # Same figure as the desktop, drawn on the phone with TradingView Lightweight Charts
        out["tv"] = lwchart.convert(fig, price, view_tf)
        out["tv"].update(height=int(chart_cfg["overlay_height" if small else "height"]),
                         pane_height=int(chart_cfg["overlay_pane_height" if small else "pane_height"]))
        if overlay is None:
            out["note"] = (f"Part of the wave count is outside the stored {view_tf} history, so only price and "
                           "levels are shown." if had_waves else
                           "The engine has no wave count at this bar, so only price and levels are shown.")

    level_names = list(S.level_names)
    fields = row.drop(labels=[c for c in [*level_names, S.levels_col] if c in row.index])
    out["fields"] = [[str(k), str(v)] for k, v in fields.items()]
    out["levels"] = [[n, _cell(row.get(n))] for n in level_names]
    out["live_count"] = row["live_count"] if pd.notna(row.get("live_count")) else "–"
    return clean(out)


# ----------------------------------------------------------------------------------
# Charts tab (render_stock_charts in app.py): stocks to trade with the trend
# ----------------------------------------------------------------------------------
@lru_cache(maxsize=2)
def _trend(mtime: float, frames: tuple) -> pd.DataFrame:
    return overview.trends(_app().store.snapshot(), frames)


def _sc_files(req: dict) -> list[tuple[Strategy, pd.DataFrame, str, dict, list[str], list[str]]]:
    """(Strategy, results, name, meta, all names, picked names) of every picked results file."""
    a = _app()
    out = []
    wanted = req.get("files") or {}
    for S in strategies.STRATEGIES.values():
        files = runner.list_results(a.cfg["results_dir"], S.key)
        names = [f.name for f in files]
        picked = [n for n in wanted.get(S.key, []) if n in names] if S.key in wanted else \
            [f.name for f in overview.default_files(files)]
        if not picked:
            out.append((S, None, "", {}, names, []))
        for name in picked:
            res, meta = load_results(a.cfg["results_dir"] / name)
            res = eligibility.assess(universe.attach(res, attributes()), S, a.cfg["fno_5day"])
            out.append((S, res, name, meta, names, picked))
    return out


def _sc_data(req: dict):
    a = _app()
    sc = a.cfg["stock_charts"]
    files = _sc_files(req)
    sig = overview.signals([(S, res, name) for S, res, name, *_ in files if res is not None])
    trend = _trend(a.store.mtime(), tuple(sc["trend_frames"]))
    return a, sc, files, sig, trend


def charts_list(req: dict) -> dict:
    a, sc, files, sig, trend = _sc_data(req)
    path = a.cfg["stock_charts_filters_file"]
    f = {**overview.DEFAULT_FILTERS, **(req.get("filters") or overview.load_filters(path))}
    rows = overview.stock_list(trend, sig, attributes(), f)
    shown = overview.table(rows, int(sc["list_rows"]))
    attrs = attributes()
    return clean({
        "filters": f, "saved": path.exists(), "active": overview.active_filters(f),
        "trend_frames": sc["trend_frames"], "trend_choices": list(overview.TREND_CHOICES.items()),
        "options": {
            "strategies": [[S.key, S.name] for S in strategies.STRATEGIES.values()],
            "timeframes": list(overview.TIMEFRAMES), "alignment": list(charts.ALIGN_ORDER),
            "status": sorted(sig["status"].dropna().astype(str).unique()) if not sig.empty else [],
            "attributes": [[col, universe.ATTR_LABELS.get(col, col),
                            universe.options(attrs[col]) if not attrs.empty and col in attrs else []]
                           for col in universe.ATTR_COLS]},
        "files": {S.key: {"name": S.name, "all": names, "picked": picked}
                  for S, _, _, _, names, picked in files},
        "counts": {"listed": len(rows), "up": int(trend["trend_side"].eq("LONG").sum()) if not trend.empty else 0,
                   "down": int(trend["trend_side"].eq("SHORT").sum()) if not trend.empty else 0,
                   "with_trend": int(rows["with_trend"].sum()) if not rows.empty else 0},
        "table": table(shown), "tickers": list(shown["Ticker"]),
        "all_tickers": a.store.tickers(),
    })


def charts_save(req: dict) -> dict:
    overview.save_filters(_app().cfg["stock_charts_filters_file"], req.get("filters") or {})
    return {"ok": True, "note": "Saved. The Charts tab will open with these filters."}


def charts_chart(req: dict) -> dict:
    a, sc, files, sig, trend = _sc_data(req)
    ticker = str(req["ticker"])
    bars = a.store.ticker_bars(ticker)
    have = [tf for tf in sc["timeframes"] if tf in set(bars["time_frame"])]
    if not have:
        return {"ticker": ticker, "warning": f"No bars for {ticker} in the stored data."}
    tf = req.get("tf") if req.get("tf") in have else (sc["default_timeframe"] if sc["default_timeframe"] in have
                                                     else have[0])
    price = bars[bars["time_frame"] == tf].sort_values("time")
    mine = overview.ticker_signals(sig, ticker)
    labels = [overview.signal_label(r) for _, r in mine.iterrows()]
    pick = int(req.get("pick") or 0)
    pick = pick if 0 < pick <= len(labels) else 0
    highlight, engine, chart_cfg = None, a.cfg["engine"], a.cfg["chart"]
    if pick:
        r = mine.iloc[pick - 1]
        S = strategies.get(r["strategy"])
        res, meta = next((res, meta) for SS, res, name, meta, *_ in files if SS.key == S.key and name == r["file"])
        row, params = res.loc[int(r["id"])], meta.get("params", {})
        src = bars[bars["time_frame"] == row["time_frame"]]
        overlay = (S.overlay_from_row(row) if S.overlay_from_row is not None else
                   _overlay(row["Ticker"], row["time_frame"], str(row["signal_time"]), int(row["zigzag_length"]),
                            params.get("pivot_tie", engine["pivot_tie"]), params.get("hi_source", engine["hi_source"]),
                            params.get("lo_source", engine["lo_source"]), a.store.mtime()))
        horizon = int(params.get("horizon_bars", engine["horizon_bars"]))
        if tf != row["time_frame"]:
            row, overlay, horizon = charts.on_timeframe(row, overlay, src, price, tf, horizon, S.targets)
        highlight = {"row": row, "overlay": overlay, "S": S, "groups": list(S.level_groups), "horizon": horizon}
    small = bool(req.get("narrow"))
    height = int(chart_cfg["overlay_height" if small else "height"])
    pane_height = int(chart_cfg["overlay_pane_height" if small else "pane_height"])
    fig = charts.stock_chart(
        price, tf, mine, bars=int(sc["phone_bars"].get(tf, 500)), height=height,
        emas=[("EMA 13", chart_cfg["ema_fast"]), ("EMA 55", chart_cfg["ema_slow"])] if req.get("ema", True) else [],
        panes=chart_cfg["indicator_panes"] if req.get("ind", True) else (), pane_height=pane_height,
        highlight=highlight, title=f"{ticker} · {tf}" + (f" · {labels[pick - 1]}" if pick else ""))
    spec = lwchart.convert(fig, price, tf)
    spec.update(height=height, pane_height=pane_height,
                initial_bars=None if pick else int(sc["bars"].get(tf, 250)))   # opens on the recent bars
    t = trend.loc[ticker] if ticker in trend.index else None
    view = mine[["strategy", "time_frame", "degree", "side", "signal_time", "status", "result", "alignment",
                 "TRIGGER", "STOP", "risk_pct", "entry_price"]].copy() if not mine.empty else pd.DataFrame()
    if not view.empty:
        view["strategy"] = view["strategy"].str.upper()
        view["signal_time"] = view["signal_time"].dt.strftime("%d %b %Y %H:%M")
        view = view.rename(columns={"risk_pct": "Stop %", "time_frame": "TF", "signal_time": "Signal"})
    return clean({
        "ticker": ticker, "tf": tf, "timeframes": have, "tv": spec, "labels": labels, "pick": pick,
        "tradingview": alert_events.tradingview_url(ticker, tf),
        "trend_side": "" if t is None else t["trend_side"], "trend": "" if t is None else overview.trend_text(t),
        "signals": table(view) if not view.empty else None,
    })


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
    n = universe.counts(_app().cfg["tickers_file"])
    return {"text": "\n".join(stocks), "count": len(stocks), "indices": len(stock_data.indian_index),
            "commodities": len(stock_data.commodity),
            "universes": [[k, f"{v} ({n.get(k, 0):,} stocks)"] for k, v in universe.UNIVERSES.items()]}


def save_tickers(text: str) -> dict:
    stocks = ds.parse_ticker_text(text)
    universe.write_stocks(_app().cfg["tickers_file"], stocks)          # keeps each stock's attributes
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
    scope = req.get("universe") if req.get("universe") in universe.UNIVERSES else "all"
    stocks = ds.parse_ticker_text(pasted) if pasted.strip() else universe.stocks(a.cfg["tickers_file"], scope)
    tfs = [tf for tf in (req.get("timeframes") or a.cfg["timeframes"]) if tf in a.cfg["timeframes"]]
    if not stocks:
        raise ValueError("No stock tickers to download.")
    if not tfs:
        raise ValueError("Pick at least one timeframe.")
    if pasted.strip() and req.get("save_pasted"):
        universe.write_stocks(a.cfg["tickers_file"], stocks)
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
        "universes": get_tickers()["universes"],
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
        aligned_only=bool(req.get("aligned_only")),
        universe=req.get("universe") if req.get("universe") in universe.UNIVERSES else "all")
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
        job.say(f"{S.name} · {runner.MODES[p.mode]} · {', '.join(p.timeframes)} · {n} parts")
        keep = set(universe.final_list(a.cfg["tickers_file"], p.universe))
        res = workers.run_parts(a.store.part_paths(), [(S.key, p)], keep, a.cfg["signal_indicators"], a.cfg["htf"],
                                int(a.cfg.get("phone", {}).get("engine_workers", 4)), a.root / "work",
                                progress=lambda i, total: job.progress(
                                    i / max(total, 1), f"Elliott Wave engine · part {min(i + 1, total)}/{total}"),
                                log=job.say)[S.key]
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
# Alerts tab
# ----------------------------------------------------------------------------------
def alerts_overview() -> dict:
    return clean(alerts.overview(_app()))


def alerts_save(values: dict) -> dict:
    return clean(alerts.save_settings(_app(), values))


def alerts_telegram_test(values: dict) -> dict:
    return alerts.telegram_test(_app(), values)


def alerts_telegram_preview(values: dict) -> dict:
    return alerts.telegram_preview(_app(), values)


def alerts_telegram_chat(values: dict) -> dict:
    return alerts.telegram_find_chat(_app(), values)


def alerts_test() -> dict:
    return alerts.test_notification(_app())


def alerts_run(kind: str = "regular") -> dict:
    out = alerts.run(_app(), source="manual", kind="full" if kind == "full" else "regular")
    if "busy" in out:
        raise RuntimeError(out["busy"])
    return out


# ----------------------------------------------------------------------------------
# User Guide
# ----------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def guide() -> dict:
    import markdown
    out = {}
    for key, name in (("pictures", "elliott_wave_pictures.md"), ("functional", "functional_guide.md"),
                      ("technical", "technical_guide.md"), ("phone", "phone_guide.md")):
        raw = resources.read(f"docs/{name}")                    # copied in by the Android build
        if raw is None and (ROOT / "docs" / name).exists():     # desktop test run
            raw = (ROOT / "docs" / name).read_bytes()
        if raw is not None:
            out[key] = markdown.markdown(raw.decode("utf-8"), extensions=["tables", "fenced_code"])
    return out
