"""Elliott Wave 5 Reversal - local Streamlit app (Data · Run / Backtest · Dashboard)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

import elliott_wave5_screener as ew
import stock_data
from core import charts, data_store as ds, prefs, runner
from core.config import ROOT, load_config, resolve

st.set_page_config(page_title="Elliott Wave 5 Reversal", page_icon="📈", layout="wide")

UP, DOWN = "#2fbf71", "#e66767"                       # green / red used for sides and readings
st.markdown("""
<style>
.block-container {padding-top: 2.2rem;}
/* centred, pill-like tabs */
.stTabs [role="tablist"] {justify-content: center; gap: 0.5rem;}
.stTabs [role="tab"] {padding: 0.65rem 1.4rem; border-radius: 12px 12px 0 0;}
.stTabs [role="tab"] p {font-size: 1.02rem; font-weight: 600;}
.stTabs [role="tab"][aria-selected="true"] {background: rgba(57,135,229,0.14);}
/* cards */
[data-testid="stMetric"] {border-radius: 14px;}
[data-testid="stMetricValue"] {font-weight: 700; letter-spacing: -0.01em;}
[data-testid="stMetricLabel"] p {font-weight: 600; opacity: 0.85;}
</style>
""", unsafe_allow_html=True)
cfg = load_config()
ds.setup_logging(cfg["logs_dir"])
ENGINE = cfg["engine"]
PLOT_CONFIG = {"displaylogo": False, "scrollZoom": False}   # wheel scrolls the page, not the chart


# ----------------------------------------------------------------------------------
# Cached loaders (keyed on file modified time, so a new file invalidates them)
# ----------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_stock(path: str, mtime: float) -> pd.DataFrame:
    return ds.load_stock_csv(Path(path))


def stock_df() -> pd.DataFrame:
    path = cfg["stock_csv"]
    return _load_stock(str(path), path.stat().st_mtime) if path.exists() else ds.empty_frame()


@st.cache_data(show_spinner=False)
def _run_engine(path: str, mtime: float, params_json: str) -> pd.DataFrame:
    return runner.run_engine(_load_stock(path, mtime), runner.RunParams.from_json(params_json),
                             cfg["signal_indicators"])


@st.cache_data(show_spinner=False)
def _load_results(path: str, mtime: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    return runner.load_results(Path(path))


@st.cache_data(show_spinner=False)
def _overlay(path: str, mtime: float, ticker: str, time_frame: str, signal_time: str, length: int,
             pivot_tie: str, hi_source: str, lo_source: str) -> Optional[dict]:
    data = _load_stock(path, mtime)
    price = data[(data["Ticker"] == ticker) & (data["time_frame"] == time_frame)]
    return charts.wave_overlay(price, signal_time, length, pivot_tie, hi_source, lo_source)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _fmt(value: float, suffix: str = "%") -> str:
    return "–" if pd.isna(value) else f"{value:.1f}{suffix}"


# ----------------------------------------------------------------------------------
# Sidebar: data update inputs
# ----------------------------------------------------------------------------------
with st.sidebar:
    st.header(":material/cloud_download: Data update")
    tickers_path = st.text_input("Stock tickers file", _rel(cfg["tickers_file"]),
                                 help="CSV with a `Ticker` column in yfinance format, e.g. RELIANCE.NS")
    pasted = st.text_area("…or paste stock tickers", placeholder="RELIANCE.NS, TCS.NS, INFY.NS",
                          help="Used exactly as written (yfinance symbols). "
                               "When filled, this list replaces the file for this update.")
    save_pasted = st.checkbox("Save pasted list to the tickers file", disabled=not pasted.strip())
    st.caption(f"Final list = stock tickers + {len(stock_data.indian_index)} indices + "
               f"{len(stock_data.commodity)} commodities (lists in `stock_data.py`)")
    data_tfs = st.multiselect("Timeframes", cfg["timeframes"], default=cfg["timeframes"])
    inc_days = st.number_input("Incremental days", min_value=1, max_value=700,
                               value=int(cfg["incremental_days"]),
                               help="How much recent data each update re-downloads")
    do_update = st.button("Update data", type="primary", width="stretch", icon=":material/sync:",
                          help="New tickers get their full history; all others only the last "
                               "N days, merged into stock.csv")
    st.divider()
    confirm_full = st.checkbox("Yes, replace all stored history")
    do_full = st.button("Full re-download", disabled=not confirm_full, width="stretch",
                        icon=":material/history:",
                        help="Use after a split / bonus, or to rebuild stock.csv")

# Shown as Dashboard · Data · Run / Backtest · User Guide. The code below still runs
# Data -> Run -> Dashboard so a fresh run can pre-select its file in the dashboard.
_data_now = stock_df()
_head = st.columns([3, 2], vertical_alignment="center")
_head[0].markdown("## :material/candlestick_chart: Elliott Wave 5 Reversal")
_head[0].caption("Wave-5 exhaustion screener, backtest and signal charts for stocks, indices and commodities")
if not _data_now.empty:
    _head[1].markdown(
        f":blue-badge[:material/database: {_data_now['Ticker'].nunique()} tickers] "
        f":green-badge[:material/schedule: Data to {_data_now['time'].max():%d %b %Y}] "
        f":violet-badge[:material/inventory_2: {len(runner.list_results(cfg['results_dir']))} saved runs]")

tab_dash, tab_data, tab_run, tab_guide = st.tabs([
    ":material/monitoring: Dashboard", ":material/database: Data",
    ":material/query_stats: Run / Backtest", ":material/menu_book: User Guide"])


# ----------------------------------------------------------------------------------
# Tab 1 - Data
# ----------------------------------------------------------------------------------
def _stock_tickers() -> list[str]:
    if pasted.strip():
        return ds.parse_ticker_text(pasted)
    path = resolve(tickers_path)
    if not path.exists():
        st.error(f"Tickers file not found: {path}")
        return []
    return ds.clean_tickers(stock_data.read_stock_tickers(path))


with tab_data:
    st.subheader(":material/database: Stock data")
    st.caption(f"`{_rel(cfg['stock_csv'])}` · Daily and 4hr bars (built from 60m) from yfinance, "
               "stored as timezone-naive IST, with indicators")

    if do_update or do_full:
        stocks = _stock_tickers()
        tickers = stock_data.build_final_list(stocks)
        if not stocks:
            st.error("No stock tickers to download.")
        elif not data_tfs:
            st.error("Pick at least one timeframe.")
        else:
            if pasted.strip() and save_pasted:
                ds.write_tickers(resolve(tickers_path), stocks)
            bar = st.progress(0.0, text="Starting download…")
            report = ds.update_data(
                cfg, tickers, data_tfs, int(inc_days), full=do_full,
                progress=lambda done, total, msg: bar.progress(done / max(total, 1), text=msg))
            bar.empty()
            st.session_state["update_report"] = report

    report: Optional[ds.UpdateReport] = st.session_state.get("update_report")
    if report is not None:
        with st.container(border=True):
            st.markdown("**Last update**")
            cols = st.columns(4)
            cols[0].metric("Rows before", f"{report.rows_before:,}")
            cols[1].metric("Rows after", f"{report.rows_after:,}")
            cols[2].metric("Rows added", f"{int(report.stats['added'].sum()) if not report.stats.empty else 0:,}")
            cols[3].metric("Rows replaced", f"{int(report.stats['replaced'].sum()) if not report.stats.empty else 0:,}")
            if not report.stats.empty:
                st.dataframe(report.stats, hide_index=True, width="content")
            if report.failed:
                for tf, bad in report.failed.items():
                    st.warning(f"**{tf}** – no data for {len(bad)} ticker(s): {', '.join(bad)}")
            elif report.saved:
                st.success("All tickers downloaded.")
            if not report.saved:
                st.error("Nothing was downloaded, stock.csv is unchanged.")
            with st.expander("Download log"):
                st.code("\n".join(report.log), language=None)

    data = stock_df()
    if data.empty:
        st.info("No data yet. Press **Update data** in the sidebar - the first run downloads the full history.")
    else:
        stored = set(data["Ticker"].unique())
        listed = stock_data.build_final_list(_stock_tickers())
        new_ones = [t for t in listed if t not in stored]
        if new_ones:
            st.info(f"{len(new_ones)} ticker(s) in your list are not in stock.csv yet and will get a "
                    f"full download on the next update: {', '.join(new_ones[:15])}"
                    + (" …" if len(new_ones) > 15 else ""))
    if not data.empty:
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Coverage per timeframe**")
            st.dataframe(ds.timeframe_summary(data), hide_index=True)
        with right:
            per_ticker = ds.bars_per_ticker(data, int(cfg["short_history_bars"]))
            n_short = int(per_ticker["short_history"].sum())
            st.markdown(f"**Bars per ticker** · {n_short} with short history "
                        f"(< {cfg['short_history_bars']} bars in a timeframe)")
            st.dataframe(per_ticker.sort_values("short_history", ascending=False), hide_index=True,
                         height=250)

        st.markdown("**Preview**")
        f1, f2, f3 = st.columns([2, 1, 1])
        pick_tickers = f1.multiselect("Ticker", sorted(data["Ticker"].unique()), key="prev_tickers")
        pick_tfs = f2.multiselect("Timeframe", sorted(data["time_frame"].unique()), key="prev_tfs")
        newest_first = f3.toggle("Newest first", value=True)
        view = data
        if pick_tickers:
            view = view[view["Ticker"].isin(pick_tickers)]
        if pick_tfs:
            view = view[view["time_frame"].isin(pick_tfs)]
        view = view.sort_values("time", ascending=not newest_first)
        st.caption(f"{len(view):,} rows" + (" (showing the first 5,000)" if len(view) > 5000 else ""))
        st.dataframe(view.head(5000), hide_index=True, height=350)


# ----------------------------------------------------------------------------------
# Tab 2 - Run / Backtest
# ----------------------------------------------------------------------------------
with tab_run:
    st.subheader(":material/query_stats: Run the Wave 5 screener")
    data = stock_df()
    if data.empty:
        st.info("Download data first (Data tab).")
    else:
        top = st.columns([3, 1])
        mode = top[0].radio("Mode", list(runner.MODES), format_func=runner.MODES.get, horizontal=True)
        if top[1].button("Reload stock.csv", width="stretch"):
            _load_stock.clear()
            _run_engine.clear()
            st.rerun()

        first_day, last_day = data["time"].min().date(), data["time"].max().date()
        as_of = start = end = None
        if mode == "asof":
            as_of = st.date_input("As-of date (signals as they stood after this day's close)",
                                  value=max(first_day, last_day - pd.Timedelta(days=60)),
                                  min_value=first_day, max_value=last_day)
        elif mode == "backtest":
            d1, d2 = st.columns(2)
            start = d1.date_input("Start date", value=max(first_day, last_day - pd.Timedelta(days=365)),
                                  min_value=first_day, max_value=last_day)
            end = d2.date_input("End date", value=last_day, min_value=first_day, max_value=last_day)

        a, b, c = st.columns(3)
        available_tfs = sorted(data["time_frame"].unique())
        run_tfs = a.multiselect("Timeframes", available_tfs, default=available_tfs, key="run_tfs")
        lengths = b.multiselect("ZigZag lengths", list(ew.DEFAULT_LENGTHS), default=ENGINE["lengths"],
                                format_func=lambda n: f"{n} ({ew.DEGREE_NAMES.get(n, '')})")
        stages = c.multiselect("Stages", [ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED], default=ENGINE["stages"])

        a, b, c, d = st.columns(4)
        horizon = a.number_input("horizon_bars", min_value=1, max_value=500, value=int(ENGINE["horizon_bars"]),
                                 help="Bars after the signal used to evaluate the outcome")
        max_since = b.number_input("max_bars_since_w5 (optional)", min_value=0, value=None, step=1,
                                   help="Leave empty for no freshness filter")
        min_w5 = c.number_input("min_w5_vs_w1", min_value=0.0, value=float(ENGINE["min_w5_vs_w1"]), step=0.1,
                                help="e.g. 0.618 = wave 5 at least 61.8% of wave 1")
        pivot_tie = d.selectbox("pivot_tie", ["strict", "left_equal"],
                                index=["strict", "left_equal"].index(ENGINE["pivot_tie"]))

        a, b, c, d = st.columns(4)
        hi_source = a.selectbox("High source", runner.HI_SOURCES, index=runner.HI_SOURCES.index(ENGINE["hi_source"]))
        lo_source = b.selectbox("Low source", runner.LO_SOURCES, index=runner.LO_SOURCES.index(ENGINE["lo_source"]))
        resignal = c.checkbox("resignal_on_extension", disabled=mode != "backtest",
                              help="Backtest only: a new signal each time wave 5 makes a new confirmed extreme")
        d.caption(f"min_bars = {cfg['min_bars']} (config.yaml)")

        problems = []
        if not run_tfs:
            problems.append("Pick at least one timeframe.")
        if not lengths:
            problems.append("Pick at least one ZigZag length.")
        if not stages:
            problems.append("Pick at least one stage.")
        if mode == "backtest" and start > end:
            problems.append("Start date is after the end date.")
        for msg in problems:
            st.error(msg)

        if not problems:
            if mode == "asof":
                cutoff, when = runner.end_of_day(as_of), f"on {as_of}"
            elif mode == "backtest":
                cutoff, when = pd.Timestamp(start) - pd.Timedelta(seconds=1), f"before {start}"
            else:
                cutoff, when = data["time"].max(), "in stock.csv"
            short = runner.check_min_bars(data, cutoff, int(cfg["min_bars"]), run_tfs)
            if not short.empty:
                note = ("The backtest only signals once a series has enough bars."
                        if mode == "backtest" else "These are skipped by the engine.")
                st.warning(f"{len(short)} ticker/timeframe pair(s) have fewer than {cfg['min_bars']} bars "
                           f"{when}. {note}")
                with st.expander("Show them"):
                    st.dataframe(short, hide_index=True, width="content")

            if st.button("Run", type="primary", icon=":material/play_arrow:"):
                params = runner.RunParams(
                    mode=mode, timeframes=tuple(run_tfs), lengths=tuple(sorted(lengths)),
                    stages=tuple(stages), horizon_bars=int(horizon),
                    max_bars_since_w5=None if max_since is None else int(max_since),
                    min_w5_vs_w1=float(min_w5), resignal_on_extension=bool(resignal and mode == "backtest"),
                    pivot_tie=pivot_tie, hi_source=hi_source, lo_source=lo_source,
                    min_bars=int(cfg["min_bars"]),
                    as_of=str(as_of) if as_of else None, start=str(start) if start else None,
                    end=str(end) if end else None)
                with st.spinner("Running the Elliott Wave engine…"):
                    result = _run_engine(str(cfg["stock_csv"]), cfg["stock_csv"].stat().st_mtime,
                                         params.to_json())
                saved = runner.save_results(result, params, cfg["results_dir"], cfg["stock_csv"])
                st.session_state["last_run"] = str(saved)
                st.session_state["dash_file"] = saved.name          # dashboard opens this run

        last_run = st.session_state.get("last_run")
        if last_run and Path(last_run).exists():
            path = Path(last_run)
            result, _meta = _load_results(str(path), path.stat().st_mtime)
            st.divider()
            st.success(f"{len(result)} signal(s) · saved to `{_rel(path)}` (+ `.json` with the parameters). "
                       "Open the **Dashboard** tab for the charts.")
            summary = runner.summarize(result)
            if not summary.empty:
                st.markdown("**Backtest summary** (`summarize_backtest`)")
                st.dataframe(summary, hide_index=True)
            st.markdown("**Signals**")
            st.dataframe(result, hide_index=True, height=380)
            st.download_button("Download results CSV", path.read_bytes(), file_name=path.name, mime="text/csv")


# ----------------------------------------------------------------------------------
# Tab 3 - Dashboard
# ----------------------------------------------------------------------------------
def _toggle_stat(state_key: str, name: str) -> None:
    st.session_state[state_key] = None if st.session_state.get(state_key) == name else name


def _kpi_cards(view: pd.DataFrame, state_key: str) -> pd.DataFrame:
    """Stat cards for evaluated results. Each card's button filters the signal table below."""
    k = runner.kpis(view)
    masks = runner.stat_masks(view)
    if state_key not in st.session_state:               # first look at this file: use the saved stat
        st.session_state[state_key] = st.session_state.get("stat_default")
    active = st.session_state.get(state_key)
    if active not in masks:
        active = st.session_state[state_key] = None
    st.session_state["stat_current"] = active
    cards = [(":material/bolt: Trigger rate", _fmt(k["trigger_rate"]), "triggered",
              "Signals whose close broke the TRIGGER level"),
             (":material/trending_up: Extended", _fmt(k["extended_pct"]), "extended",
              "Wave 5 made a new extreme before the trigger"),
             (":material/flag: W4 target hit", _fmt(k["w4_hit_rate"]), "w4", "Of triggered signals"),
             (":material/target: FIB 0.5 hit", _fmt(k["fib50_hit_rate"]), "fib50", "Of triggered signals"),
             (":material/shield: Stop rate", _fmt(k["stop_rate"]), "stopped", "Of triggered signals"),
             (":material/north_east: Avg MFE", _fmt(k["avg_mfe"]), "mfe",
              "Average best move after entry. The button keeps triggered signals at or above it."),
             (":material/south_east: Avg MAE", _fmt(k["avg_mae"]), "mae",
              "Average worst move after entry. The button keeps triggered signals at or below it.")]

    def card(col, label: str, value: str, name: Optional[str], tip: Optional[str]) -> None:
        with col.container(border=True):
            st.metric(label, value, help=tip)
            if name is None:
                st.button("Show all", key=f"{state_key}_all", width="stretch", disabled=active is None,
                          icon=":material/select_all:",
                          on_click=_toggle_stat, args=(state_key, active))
            else:
                on = active == name
                st.button(f"✓ Showing {int(masks[name].sum()):,}" if on else f"Show {int(masks[name].sum()):,}",
                          key=f"{state_key}_{name}", width="stretch", type="primary" if on else "secondary",
                          icon=":material/filter_alt:",
                          on_click=_toggle_stat, args=(state_key, name),
                          help="Click again to clear" if on else "Filter the signal table to these signals")

    row1, row2 = st.columns(4), st.columns(4)
    card(row1[0], ":material/radar: Signals", f"{k['signals']:,}", None, None)
    for col, (label, value, name, tip) in zip([*row1[1:], *row2], cards):
        card(col, label, value, name, tip)
    return view[masks[active]] if active else view


def _live_cards(view: pd.DataFrame, state_key: str) -> pd.DataFrame:
    """Stat cards for live screens: counts by timeframe / degree / side, each count clickable."""
    cols = st.columns(4)
    cols[0].metric(":material/radar: Signals", f"{len(view):,}", border=True)
    out = view
    for col, (label, field) in zip(cols[1:], (("By timeframe", "time_frame"), ("By degree", "degree"),
                                              ("By side", "reversal_side"))):
        counts = view[field].value_counts()
        key = f"{state_key}_{field}"
        if st.session_state.get(key) not in counts.index:
            st.session_state.pop(key, None)
        with col.container(border=True):
            pick = st.pills(label, list(counts.index), key=key, selection_mode="single",
                            format_func=lambda v, c=counts: f"{v} · {c[v]}",
                            help="Click a count to filter the signal table; click again to clear")
        if pick is not None:
            out = out[out[field] == pick]
    return out


_FILTER_KEYS = {"time_frame": "f_tf", "degree": "f_degree", "reversal_side": "f_side",
                "stage": "f_stage", "status": "f_status", "result": "f_result"}
_FILTER_LABELS = {"time_frame": "Timeframe", "degree": "Degree", "reversal_side": "Side",
                  "stage": "Stage", "status": "Status", "result": "Result"}
_CHART_TOGGLES = [*charts.LEVEL_GROUPS, "ema", "ind"]


def _apply_prefs(saved: dict[str, Any]) -> None:
    """Put a saved (or default) dashboard state into the widgets."""
    for col, key in _FILTER_KEYS.items():
        st.session_state[key] = list(saved[col])
    st.session_state["f_search"] = saved["search"]
    st.session_state["f_ratio_pref"] = list(saved["w5_vs_w1"])
    st.session_state["stat_default"] = saved["stat"]
    for key in [k for k in st.session_state if str(k).startswith("stat_") and k != "stat_default"]:
        del st.session_state[key]                           # stat cards fall back to the default
    for name in _CHART_TOGGLES:
        for prefix in ("grp", "dlg"):
            st.session_state[f"{prefix}_{name}"] = bool(saved["chart_groups"].get(name, True))


def _current_prefs() -> dict[str, Any]:
    return {
        **{col: list(st.session_state.get(key, [])) for col, key in _FILTER_KEYS.items()},
        "search": st.session_state.get("f_search", ""),
        "w5_vs_w1": list(st.session_state.get("f_ratio_pref", [None, None])),
        "stat": st.session_state.get("stat_current"),
        "chart_groups": {name: bool(st.session_state.get(f"grp_{name}", True)) for name in _CHART_TOGGLES},
    }


def _save_filters() -> None:
    saved = _current_prefs()
    prefs.save_prefs(cfg["dashboard_filters_file"], saved)
    st.session_state["stat_default"] = saved["stat"]
    st.session_state["prefs_note"] = "Saved. The dashboard will open like this from now on."


def _restore_filters() -> None:
    _apply_prefs(prefs.load_prefs(cfg["dashboard_filters_file"]))
    st.session_state["prefs_note"] = "Saved filters restored."


def _clear_filters() -> None:
    _apply_prefs(prefs.default_prefs())
    st.session_state["prefs_note"] = "Filters cleared (press Save filters to make this the default)."


if "prefs_loaded" not in st.session_state:                  # once per browser session
    _apply_prefs(prefs.load_prefs(cfg["dashboard_filters_file"]))
    st.session_state["prefs_loaded"] = True


def _filters(res: pd.DataFrame) -> pd.DataFrame:
    def options(col: str) -> list:
        """Values in this file plus whatever is already selected, so a saved filter never breaks."""
        present = sorted(res[col].dropna().unique()) if col in res.columns else []
        selected = st.session_state.get(_FILTER_KEYS[col], [])
        return present + [v for v in selected if v not in present]

    picks = {col: slot.multiselect(_FILTER_LABELS[col], options(col), key=_FILTER_KEYS[col],
                                   disabled=col not in res.columns)
             for slot, col in zip(st.columns(6), _FILTER_KEYS)}

    row2 = st.columns([2, 2.2, 1.3, 1.1, 0.9], vertical_alignment="bottom")
    search = row2[0].text_input("Ticker search", key="f_search", placeholder="e.g. BAJ")
    ratio = res["w5_vs_w1"].dropna()
    lo, hi = (float(ratio.min()), float(ratio.max())) if len(ratio) else (0.0, 1.0)
    if hi > lo:
        st.session_state["f_ratio"] = prefs.ratio_range(st.session_state.get("f_ratio_pref", [None, None]), lo, hi)
        rng = row2[1].slider("w5_vs_w1 range", min_value=lo, max_value=hi, key="f_ratio")
        st.session_state["f_ratio_pref"] = prefs.ratio_pref(rng, lo, hi)
    else:
        rng = (lo, hi)
    row2[2].button("Save filters", type="primary", width="stretch", on_click=_save_filters,
                   icon=":material/save:",
                   help="Remember these filters, the selected stat and the chart toggles. "
                        "The dashboard opens with them every time.")
    row2[3].button("Restore", width="stretch", on_click=_restore_filters, icon=":material/restore:",
                   disabled=not cfg["dashboard_filters_file"].exists())
    row2[4].button("Clear", width="stretch", on_click=_clear_filters, icon=":material/filter_alt_off:")
    note = st.session_state.pop("prefs_note", None)
    if note:
        st.caption(note)
    elif cfg["dashboard_filters_file"].exists() and _current_prefs() != prefs.load_prefs(cfg["dashboard_filters_file"]):
        st.caption("Filters differ from the saved ones.")

    view = res
    for col, chosen in picks.items():
        if chosen and col in view.columns:
            view = view[view[col].isin(chosen)]
    if search.strip():
        view = view[view["Ticker"].str.contains(search.strip(), case=False, regex=False)]
    low, high = st.session_state.get("f_ratio_pref", [None, None]) if hi > lo else (None, None)
    if low is not None:
        view = view[view["w5_vs_w1"] >= low]
    if high is not None:
        view = view[view["w5_vs_w1"] <= high]
    return view


_TABLE_COLS = ["Ticker", "time_frame", "degree", "reversal_side", "stage", "signal_time", "close",
               "w5_end_price", "bars_since_w5", "w5_vs_w1", "status", "result", "entry_price",
               "mfe_pct", "mae_pct", "first_target_hit", "TRIGGER", "STOP", "W4_END",
               *cfg["signal_indicators"]]

def _signal_chart(row: pd.Series, params: dict[str, Any], prefix: str, compact: bool = False) -> None:
    """
    Level / EMA / indicator toggles and the candlestick for one signal.
    `prefix` keeps widget keys apart; `compact` uses the smaller overlay sizes.
    """
    toggles = st.columns(len(charts.LEVEL_GROUPS) + 2)
    for name in _CHART_TOGGLES:
        st.session_state.setdefault(f"{prefix}_{name}", True)
    groups = [name for col, name in zip(toggles, charts.LEVEL_GROUPS)
              if col.toggle(name, key=f"{prefix}_{name}")]
    show_ema = toggles[len(charts.LEVEL_GROUPS)].toggle(charts.EMA_GROUP, key=f"{prefix}_ema")
    emas = ([("EMA 13", cfg["chart"]["ema_fast"]), ("EMA 55", cfg["chart"]["ema_slow"])]
            if show_ema else [])
    show_panes = toggles[len(charts.LEVEL_GROUPS) + 1].toggle(
        "Indicators", key=f"{prefix}_ind", help="RSI, DT oscillator (K, D) and histogram in one pane under the price")
    chart_cfg = cfg["chart"]

    stock = stock_df()
    price = stock[(stock["Ticker"] == row["Ticker"]) & (stock["time_frame"] == row["time_frame"])]
    if price.empty:
        st.warning(f"No {row['time_frame']} bars for {row['Ticker']} in stock.csv - cannot draw the chart.")
        return
    overlay = _overlay(str(cfg["stock_csv"]), cfg["stock_csv"].stat().st_mtime,
                       row["Ticker"], row["time_frame"], str(row["signal_time"]),
                       int(row["zigzag_length"]), params.get("pivot_tie", ENGINE["pivot_tie"]),
                       params.get("hi_source", ENGINE["hi_source"]),
                       params.get("lo_source", ENGINE["lo_source"]))
    fig = charts.signal_chart(
        price, row, overlay,
        horizon_bars=int(params.get("horizon_bars", ENGINE["horizon_bars"])),
        bars_before=int(chart_cfg["bars_before"]), groups=groups,
        height=int(chart_cfg["overlay_height" if compact else "height"]), emas=emas,
        panes=chart_cfg["indicator_panes"] if show_panes else (),
        pane_height=int(chart_cfg["overlay_pane_height" if compact else "pane_height"]))
    st.plotly_chart(fig, theme=None, config=PLOT_CONFIG, key=f"{prefix}_fig")
    if overlay is None:
        st.caption("The engine has no wave count at this bar, so only price and levels are shown.")


def _open_chart_overlay(row: pd.Series, params: dict[str, Any]) -> None:
    """Pop-up with the same chart, so a clicked signal can be read without scrolling."""
    title = f"{row['Ticker']} · {row['time_frame']} · {row['degree']} · {row['reversal_side']}"

    def body() -> None:
        facts = [("Signal", pd.Timestamp(row["signal_time"]).strftime("%d %b %Y %H:%M")),
                 ("Close", f"{row['close']:,.2f}"), ("Trigger", f"{row['TRIGGER']:,.2f}"),
                 ("Stop", f"{row['STOP']:,.2f}"), ("W4 end", f"{row['W4_END']:,.2f}")]
        if pd.notna(row.get("status")):
            outcome = row["status"] if pd.isna(row.get("result")) else f"{row['status']} · {row['result']}"
            facts.append(("Outcome", outcome))
        st.caption("  |  ".join(f"**{label}** {value}" for label, value in facts))
        _signal_chart(row, params, prefix="dlg", compact=True)

    st.dialog(title, width="large")(body)()


def _chart_pick(slot, fig, key: str) -> list[list]:
    """Draw a breakdown chart whose bars can be clicked; returns the clicked bars' data."""
    event = slot.plotly_chart(fig, theme=None, config=PLOT_CONFIG, key=key,
                              on_select="rerun", selection_mode="points")
    return charts.picked_bars(fig, event.selection.points)


def _bump(key: str) -> None:
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _style_signals(table: pd.DataFrame):
    """Colours: SHORT red / LONG green; histogram below -20 green, above +20 red."""
    def side(value: Any) -> str:
        colour = DOWN if value == "SHORT" else UP if value == "LONG" else None
        return f"color: {colour}; font-weight: 700" if colour else ""

    def histogram(value: Any) -> str:
        if pd.isna(value):
            return ""
        if value < -20:
            return f"color: {UP}; background-color: rgba(47,191,113,0.14); font-weight: 600"
        if value > 20:
            return f"color: {DOWN}; background-color: rgba(230,103,103,0.14); font-weight: 600"
        return ""

    formats = {"signal_time": lambda t: "" if pd.isna(t) else f"{t:%Y-%m-%d %H:%M}"}
    styled = table.style.format({k: v for k, v in formats.items() if k in table.columns},
                                precision=2, na_rep="")
    if "reversal_side" in table.columns:
        styled = styled.map(side, subset=["reversal_side"])
    if "histogram" in table.columns:
        styled = styled.map(histogram, subset=["histogram"])
    return styled


def _on_table_click(table_key: str) -> None:
    """
    Remember which row was clicked last - through its checkbox or through any cell -
    and ask for the chart overlay.
    """
    selection = st.session_state[table_key]["selection"]
    rows = list(selection.get("rows", []))
    cells = [cell[0] for cell in selection.get("cells", [])]
    previous = st.session_state.get(f"{table_key}_seen", ([], []))
    st.session_state[f"{table_key}_seen"] = (rows, cells)
    changed = cells if cells != previous[1] else rows
    if changed:
        st.session_state[f"{table_key}_row"] = int(changed[0])
        st.session_state["open_overlay"] = True


with tab_dash:
    files = runner.list_results(cfg["results_dir"])
    if not files:
        st.info("No results yet. Download data in the **Data** tab, then run a screen or backtest "
                "in the **Run / Backtest** tab.")
    else:
        names = [f.name for f in files]
        if st.session_state.get("dash_file") not in names:
            st.session_state["dash_file"] = names[0]
        head = st.columns([2, 3])
        chosen = head[0].selectbox("Results file", names, key="dash_file")
        path = cfg["results_dir"] / chosen
        res, meta = _load_results(str(path), path.stat().st_mtime)
        params = meta.get("params", {})
        mode_name = runner.MODES.get(params.get("mode", ""), "Run")
        period = (params.get("as_of") or
                  (f"{params.get('start')} → {params.get('end')}" if params.get("start") else "latest bar"))
        head[1].caption(f"**{mode_name}** · {period} · lengths {params.get('lengths', '?')} · "
                        f"horizon {params.get('horizon_bars', '?')} bars · pivot_tie {params.get('pivot_tie', '?')}"
                        f"\n\nstages {', '.join(params.get('stages', []))}")

        if res.empty:
            st.info("This run produced no signals.")
        else:
            with st.container(border=True):
                filtered = _filters(res)
            evaluated = runner.has_outcomes(res)
            stat_key = f"stat_{chosen}"
            if filtered.empty:
                st.warning("No signals match the filters.")
                view = filtered
            else:
                view = _kpi_cards(filtered, stat_key) if evaluated else _live_cards(filtered, stat_key)

                # ---- breakdown charts: click a bar to narrow the table
                nonce_key = f"chartsel_{chosen}"
                suffix = f"{chosen}_{len(filtered)}_{st.session_state.get(nonce_key, 0)}"
                st.markdown("#### :material/bar_chart: Breakdown")
                st.caption("Click a bar to filter the signal table to the signals inside it. "
                           "Shift-click adds more bars.")
                picked_notes: list[str] = []
                chart_mask = pd.Series(True, index=filtered.index)
                if evaluated:
                    left, right = st.columns(2)
                    bars = _chart_pick(left, charts.outcome_breakdown(filtered), f"outcome_{suffix}")
                    ranges = _chart_pick(right, charts.mfe_mae_distribution(filtered), f"mfemae_{suffix}")
                    if bars:
                        chart_mask &= runner.bar_mask(filtered, "status", bars)
                        picked_notes += [f"{tf} {degree} {value}" for tf, degree, value in bars]
                    if ranges:
                        chart_mask &= runner.range_mask(filtered, ranges)
                        picked_notes += [f"{'MFE' if col == 'mfe_pct' else 'MAE'} {low:.1f}% to {high:.1f}%"
                                         for col, low, high in ranges]
                    with st.expander("Summary table (by timeframe × degree)", icon=":material/table_chart:"):
                        st.dataframe(runner.summarize(filtered), hide_index=True)
                else:
                    bars = _chart_pick(st, charts.side_breakdown(filtered), f"sides_{suffix}")
                    if bars:
                        chart_mask &= runner.bar_mask(filtered, "reversal_side", bars)
                        picked_notes += [f"{tf} {degree} {value}" for tf, degree, value in bars]
                if picked_notes:
                    note = st.columns([5, 1], vertical_alignment="center")
                    note[0].markdown(":material/filter_alt: **Chart filter:** " + " · ".join(picked_notes))
                    note[1].button("Clear chart filter", width="stretch", icon=":material/close:",
                                   on_click=_bump, args=(nonce_key,))
                    view = view[chart_mask.loc[view.index]]
            if "signal_time" in view.columns:
                view = view.sort_values("signal_time", ascending=False, kind="stable")   # newest first
            view = view.reset_index(drop=True)

            if not filtered.empty:
                st.markdown("#### :material/table_rows: Signals")
                narrowed = " · narrowed by the selected stat / chart bar" if len(view) < len(filtered) else ""
                st.caption(f"{len(view)} of {len(res)} signals{narrowed} · newest first")
            if view.empty:
                if not filtered.empty:
                    st.warning("No signals behind this selection.")
            else:
                table_head = st.columns([4, 1])
                table_head[0].caption("Click any cell of a signal to open its chart in an overlay. The same chart stays below.")
                reopen = table_head[1].button("Open chart overlay", width="stretch",
                                              icon=":material/open_in_full:",
                                              help="Opens the overlay again for the selected row")
                table_key = f"signals_{chosen}_{len(view)}"
                st.dataframe(_style_signals(view[[c for c in _TABLE_COLS if c in view.columns]]), hide_index=True,
                             height=300, on_select=lambda key=table_key: _on_table_click(key),
                             selection_mode=["single-row", "single-cell"], key=table_key)
                picked = st.session_state.get(f"{table_key}_row", 0)
                row = view.iloc[picked if picked < len(view) else 0]
                if st.session_state.pop("open_overlay", False) or reopen:
                    _open_chart_overlay(row, params)

                side_colour = "red" if row["reversal_side"] == "SHORT" else "green"
                st.markdown(f"#### :material/candlestick_chart: {row['Ticker']} · {row['time_frame']} · "
                            f"{row['degree']} · :{side_colour}[{row['reversal_side']}]")
                _signal_chart(row, params, prefix="grp")

                st.markdown("#### :material/info: Signal details")
                d1, d2 = st.columns([3, 2])
                level_names = list(ew.LEVEL_NAMES)
                fields = row.drop(labels=[c for c in [*level_names, "reversal_levels"] if c in row.index])
                d1.dataframe(pd.DataFrame({"Field": fields.index, "Value": fields.astype(str).values}),
                             hide_index=True, height=420)
                d2.metric("Live count", row["live_count"] if pd.notna(row.get("live_count")) else "–")
                d2.dataframe(pd.DataFrame({"Level": level_names,
                                           "Price": [row.get(n) for n in level_names]}),
                             hide_index=True, height=330,
                             column_config={"Price": st.column_config.NumberColumn(format="%.2f")})


# ----------------------------------------------------------------------------------
# Tab 4 - User Guide
# ----------------------------------------------------------------------------------
with tab_guide:
    functional, technical = st.tabs(["How to use it (F&O)", "Technical documentation"])
    functional.markdown((ROOT / "docs" / "functional_guide.md").read_text(encoding="utf-8"))
    technical.markdown((ROOT / "docs" / "technical_guide.md").read_text(encoding="utf-8"))
