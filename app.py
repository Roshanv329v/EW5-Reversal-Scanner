"""Elliott Wave scanner - local Streamlit app: EW5 · EW3 · Data · Run / Backtest · User Guide."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew
import stock_data
from core import charts, data_store as ds, htf, prefs, runner, strategies, universe
from core.strategies import Strategy
from core.config import ROOT, load_config, resolve

st.set_page_config(page_title="Elliott Wave Scanner", page_icon="📈", layout="wide")

UP, DOWN, AMBER = "#2fbf71", "#e66767", "#e0a526"                       # green / red used for sides and readings
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
HTF = cfg["htf"]
WEEKLY = HTF["weekly"]["name"]
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
    params = runner.RunParams.from_json(params_json)
    data = _load_stock(path, mtime)
    if params.universe != "all":                     # e.g. F&O stocks only (+ indices and commodities)
        data = data[data["Ticker"].isin(set(universe.final_list(cfg["tickers_file"], params.universe)))]
    return runner.run_engine(data, params, cfg["signal_indicators"], HTF)


@st.cache_data(show_spinner=False)
def _attributes(path: str, mtime: float) -> pd.DataFrame:
    return universe.load_attributes(Path(path))


def attributes() -> pd.DataFrame:
    path = cfg["tickers_file"]
    return _attributes(str(path), path.stat().st_mtime) if path.exists() else universe.load_attributes(path)


def _universe_label(key: str) -> str:
    n = universe.counts(cfg["tickers_file"]).get(key, 0)
    return f"{universe.UNIVERSES[key]} ({n:,})"


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
    data_universe = st.radio("Stocks", list(universe.UNIVERSES), format_func=_universe_label, horizontal=True,
                             help="All stocks in the tickers file, or only those with fno_enabled = true. "
                                  "Ignored when tickers are pasted above.")
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

# Shown as EW5 · EW3 · Data · Run / Backtest · User Guide. The code below still runs
# Data -> Run -> dashboards so a fresh run can pre-select its file in its dashboard.
_data_now = stock_df()
_head = st.columns([3, 2], vertical_alignment="center")
_head[0].markdown("## :material/candlestick_chart: Elliott Wave Scanner")
_head[0].caption("EW5 wave-5 reversals and EW3 wave-3 starts: screener, backtest and signal charts "
                 "for stocks, indices and commodities")
if not _data_now.empty:
    _head[1].markdown(
        f":blue-badge[:material/database: {_data_now['Ticker'].nunique()} tickers] "
        f":green-badge[:material/schedule: Data to {_data_now['time'].max():%d %b %Y}] "
        f":violet-badge[:material/inventory_2: {len(runner.list_results(cfg['results_dir']))} saved runs]")

tab_ew5, tab_ew3, tab_data, tab_run, tab_alerts, tab_guide = st.tabs([
    strategies.EW5.tab, strategies.EW3.tab, ":material/database: Data",
    ":material/query_stats: Run / Backtest", ":material/notifications: Alerts", ":material/menu_book: User Guide"])


# ----------------------------------------------------------------------------------
# Tab 1 - Data
# ----------------------------------------------------------------------------------
def _stock_tickers(scope: Optional[str] = None) -> list[str]:
    if pasted.strip():
        return ds.parse_ticker_text(pasted)
    path = resolve(tickers_path)
    if not path.exists():
        st.error(f"Tickers file not found: {path}")
        return []
    return ds.clean_tickers(universe.stocks(path, scope or data_universe))


with tab_data:
    st.subheader(":material/database: Stock data")
    st.caption(f"`{_rel(cfg['stock_csv'])}` · Daily, 4hr and 60m bars from yfinance (4hr is built from the 60m bars), "
               "stored as timezone-naive IST, with indicators. "
               f"Weekly ({WEEKLY}) bars are built from the daily ones for the higher-timeframe trend.")

    if do_update or do_full:
        stocks = _stock_tickers()
        tickers = stock_data.build_final_list(stocks)
        if not stocks:
            st.error("No stock tickers to download.")
        elif not data_tfs:
            st.error("Pick at least one timeframe.")
        else:
            if pasted.strip() and save_pasted:
                universe.write_stocks(resolve(tickers_path), stocks)           # keeps the attribute columns
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
        listed = stock_data.build_final_list(_stock_tickers("all"))
        new_ones = [t for t in listed if t not in stored]
        if new_ones:
            st.info(f"{len(new_ones)} ticker(s) in your list are not in stock.csv yet and will get a "
                    f"full download on the next update: {', '.join(new_ones[:15])}"
                    + (" …" if len(new_ones) > 15 else ""))
        if WEEKLY not in set(data["time_frame"].unique()):
            st.warning(f"stock.csv has no weekly ({WEEKLY}) bars yet. Daily signals need them for the "
                       "higher-timeframe trend.")
            if st.button("Build weekly bars from the daily data", icon=":material/calendar_view_week:"):
                with st.spinner("Building weekly bars and indicators…"):
                    ds.rebuild_weekly(cfg)
                st.rerun()
    if not data.empty:
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Coverage per timeframe**")
            st.dataframe(ds.timeframe_summary(data), hide_index=True)
        with right:
            per_ticker = ds.bars_per_ticker(data, int(cfg["short_history_bars"]), skip=(WEEKLY,))
            n_short = int(per_ticker["short_history"].sum())
            st.markdown(f"**Bars per ticker** · {n_short} with short history "
                        f"(< {cfg['short_history_bars']} bars in a timeframe; {WEEKLY} not counted)")
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
# Tab - Run / Backtest (both strategies)
# ----------------------------------------------------------------------------------
with tab_run:
    st.subheader(":material/query_stats: Run a screener")
    data = stock_df()
    if data.empty:
        st.info("Download data first (Data tab).")
    else:
        top = st.columns([2, 3, 1], vertical_alignment="bottom")
        run_key = top[0].radio("Strategy", list(strategies.STRATEGIES), horizontal=True, key="run_strategy",
                               format_func=lambda k: strategies.STRATEGIES[k].name)
        S_run = strategies.get(run_key)
        mode = top[1].radio("Mode", list(runner.MODES), format_func=runner.MODES.get, horizontal=True)
        if top[2].button("Reload stock.csv", width="stretch"):
            _load_stock.clear()
            _run_engine.clear()
            st.rerun()
        st.caption(S_run.blurb)

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

        is_ew3 = S_run.key == "ew3"
        stage_default = cfg["ew3"]["stages"] if is_ew3 else ENGINE["stages"]
        a, b, c = st.columns(3)
        available_tfs = sorted(data["time_frame"].unique())
        run_universe = st.radio("Stocks", list(universe.UNIVERSES), format_func=_universe_label, horizontal=True,
                                key="run_universe", help="Scan every stock in the tickers file, or F&O stocks only "
                                                         "(indices and commodities are always included)")
        run_tfs = a.multiselect("Timeframes", available_tfs, key="run_tfs",
                                default=[tf for tf in available_tfs if tf in cfg["timeframes"]] or available_tfs,
                                help=f"{WEEKLY} is built from the daily bars. It is used for the higher-timeframe "
                                     "trend and can also be scanned.")
        lengths = b.multiselect("ZigZag lengths", list(ew.DEFAULT_LENGTHS), default=ENGINE["lengths"],
                                format_func=lambda n: f"{n} ({ew.DEGREE_NAMES.get(n, '')})")
        stages = c.multiselect("Stages", list(S_run.stages), default=stage_default, key=f"run_stages_{S_run.key}")

        a, b, c, d = st.columns(4)
        horizon = a.number_input("horizon_bars", min_value=1, max_value=500, value=int(ENGINE["horizon_bars"]),
                                 help="Bars after the signal used to evaluate the outcome")
        pivot_tie = d.selectbox("pivot_tie", ["strict", "left_equal"],
                                index=["strict", "left_equal"].index(ENGINE["pivot_tie"]))
        contexts: list[str] = list(ew3.DEFAULT_CONTEXTS)
        min_retrace, max_retrace, min_w5 = ew3.DEFAULT_MIN_RETRACE, ew3.DEFAULT_MAX_RETRACE, 0.0
        if is_ew3:
            max_since = b.number_input("max_bars_since_w2 (optional)", min_value=0, value=None, step=1,
                                       help="Only setups whose wave-2 pivot is at most this many bars old")
            contexts = c.multiselect(
                "Context", list(ew3.CONTEXTS), default=cfg["ew3"]["contexts"],
                help="AFTER_WAVE5: wave 1 starts where a completed wave 5 ended (reversal). "
                     "AFTER_ABC: wave 1 starts where an a-b-c correction ended (trend resumes). "
                     "OTHER: any other 0-1-2, roughly ten times more signals.")
        else:
            max_since = b.number_input("max_bars_since_w5 (optional)", min_value=0, value=None, step=1,
                                       help="Leave empty for no freshness filter")
            min_w5 = c.number_input("min_w5_vs_w1", min_value=0.0, value=float(ENGINE["min_w5_vs_w1"]), step=0.1,
                                    help="e.g. 0.618 = wave 5 at least 61.8% of wave 1")

        a, b, c, d = st.columns(4)
        hi_source = a.selectbox("High source", runner.HI_SOURCES, index=runner.HI_SOURCES.index(ENGINE["hi_source"]))
        lo_source = b.selectbox("Low source", runner.LO_SOURCES, index=runner.LO_SOURCES.index(ENGINE["lo_source"]))
        if is_ew3:
            retrace = c.slider("Wave 2 retracement of wave 1", min_value=0.10, max_value=0.99, step=0.001,
                               value=(float(cfg["ew3"]["min_retrace"]), float(cfg["ew3"]["max_retrace"])),
                               format="%.3f", help="Wave 2 must retrace wave 1 by an amount inside this range")
            min_retrace, max_retrace = float(retrace[0]), float(retrace[1])
            resignal = d.checkbox("resignal_on_new_w2", disabled=mode != "backtest",
                                  help="Backtest only: a new signal when the wave-2 pivot moves to a new extreme")
        else:
            resignal = c.checkbox("resignal_on_extension", disabled=mode != "backtest",
                                  help="Backtest only: a new signal each time wave 5 makes a new confirmed extreme")
            d.caption(f"min_bars = {cfg['min_bars']} (config.yaml)")

        aligned_only = st.checkbox(
            "Keep only signals aligned with the higher timeframes",
            help="Every signal is tagged ALIGNED / MIXED / AGAINST from the trend of the timeframes above it "
                 "(60m → 4hr, 1D · 4hr → 1D, 1W · 1D → 1W). Leave this off to keep all of them and filter "
                 "on the dashboard, where the results of each group can be compared.")

        problems = []
        if not run_tfs:
            problems.append("Pick at least one timeframe.")
        if not lengths:
            problems.append("Pick at least one ZigZag length.")
        if not stages:
            problems.append("Pick at least one stage.")
        if is_ew3 and not contexts:
            problems.append("Pick at least one context.")
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

            if st.button(f"Run {S_run.key.upper()}", type="primary", icon=":material/play_arrow:"):
                params = runner.RunParams(
                    mode=mode, timeframes=tuple(run_tfs), lengths=tuple(sorted(lengths)),
                    stages=tuple(stages), horizon_bars=int(horizon),
                    max_bars_since_w5=None if max_since is None else int(max_since),
                    min_w5_vs_w1=float(min_w5), resignal_on_extension=bool(resignal and mode == "backtest"),
                    pivot_tie=pivot_tie, hi_source=hi_source, lo_source=lo_source,
                    min_bars=int(cfg["min_bars"]),
                    as_of=str(as_of) if as_of else None, start=str(start) if start else None,
                    end=str(end) if end else None,
                    strategy=S_run.key, contexts=tuple(contexts),
                    min_retrace=min_retrace, max_retrace=max_retrace, aligned_only=bool(aligned_only),
                    universe=run_universe)
                with st.spinner("Running the Elliott Wave engine…"):
                    result = _run_engine(str(cfg["stock_csv"]), cfg["stock_csv"].stat().st_mtime,
                                         params.to_json())
                saved = runner.save_results(result, params, cfg["results_dir"], cfg["stock_csv"])
                st.session_state["last_run"] = str(saved)
                st.session_state[f"{S_run.key}_dash_file"] = saved.name      # its dashboard opens this run

        last_run = st.session_state.get("last_run")
        if last_run and Path(last_run).exists():
            path = Path(last_run)
            result, _meta = _load_results(str(path), path.stat().st_mtime)
            S_last = strategies.get(runner.strategy_of(path))
            st.divider()
            st.success(f"{len(result)} signal(s) · saved to `{_rel(path)}` (+ `.json` with the parameters). "
                       f"Open the **{S_last.key.upper()}** tab for the charts.")
            summary = runner.summarize(result, S_last.key)
            if not summary.empty:
                st.markdown("**Backtest summary** (`summarize_backtest`)")
                st.dataframe(summary, hide_index=True)
            st.markdown("**Signals**")
            st.dataframe(result, hide_index=True, height=380)
            st.download_button("Download results CSV", path.read_bytes(), file_name=path.name, mime="text/csv")


# ----------------------------------------------------------------------------------
# Dashboard (shared by the EW5 and EW3 tabs; every widget key carries the strategy key)
# ----------------------------------------------------------------------------------
def _k(S: Strategy, name: str) -> str:
    return f"{S.key}_{name}"


def _toggle_stat(state_key: str, name: str) -> None:
    st.session_state[state_key] = None if st.session_state.get(state_key) == name else name


def _kpi_cards(S: Strategy, view: pd.DataFrame, state_key: str) -> pd.DataFrame:
    """Stat cards for evaluated results. Each card's button filters the signal table below."""
    k = S.kpis(view)
    masks = S.stat_masks(view)
    if state_key not in st.session_state:               # first look at this file: use the saved stat
        st.session_state[state_key] = st.session_state.get(_k(S, "stat_default"))
    active = st.session_state.get(state_key)
    if active not in masks:
        active = st.session_state[state_key] = None
    st.session_state[_k(S, "stat_current")] = active
    (t1_label, _), (t2_label, _) = S.target_cards
    cards = [(":material/bolt: Trigger rate", _fmt(k["trigger_rate"]), "triggered",
              "Signals whose close broke the TRIGGER level"),
             (S.fail_card[0], _fmt(k["fail_pct"]), "failed", S.fail_card[1]),
             (t1_label, _fmt(k["t1_hit_rate"]), "t1", "Of triggered signals"),
             (t2_label, _fmt(k["t2_hit_rate"]), "t2", "Of triggered signals"),
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


def _live_cards(S: Strategy, view: pd.DataFrame, state_key: str) -> pd.DataFrame:
    """Stat cards for live screens: counts by timeframe / degree / side, each count clickable."""
    fields = [("By timeframe", "time_frame"), ("By degree", "degree"), ("By side", S.side_col)]
    if "alignment" in view.columns:
        fields.append(("By HTF alignment", "alignment"))
    cols = st.columns(len(fields) + 1)
    cols[0].metric(":material/radar: Signals", f"{len(view):,}", border=True)
    out = view
    for col, (label, field) in zip(cols[1:], fields):
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


# ---- saved filters ----------------------------------------------------------------
def _filter_columns(S: Strategy) -> list[str]:
    """Saved-filter columns: the strategy's filters and the stock attributes (tickers.csv)."""
    return [col for col, _ in S.filter_cols] + list(universe.ATTR_COLS)


def _chart_toggles(S: Strategy) -> list[str]:
    return [*S.level_groups, "ema", "ind"]


def _prefs_path(S: Strategy) -> Path:
    return cfg[S.prefs_file_key]


def _apply_prefs(S: Strategy, saved: dict[str, Any]) -> None:
    """Put a saved (or default) dashboard state into the widgets."""
    for col in _filter_columns(S):
        st.session_state[_k(S, f"f_{col}")] = list(saved[col])
    st.session_state[_k(S, "f_search")] = saved["search"]
    st.session_state[_k(S, "f_ratio_pref")] = list(saved["ratio"])
    st.session_state[_k(S, "stat_default")] = saved["stat"]
    for key in [k for k in st.session_state if str(k).startswith(_k(S, "stat_file_"))]:
        del st.session_state[key]                           # stat cards fall back to the default
    for name in _chart_toggles(S):
        for prefix in ("grp", "dlg"):
            st.session_state[_k(S, f"{prefix}_{name}")] = bool(saved["chart_groups"].get(name, True))


def _current_prefs(S: Strategy) -> dict[str, Any]:
    return {
        **{col: list(st.session_state.get(_k(S, f"f_{col}"), [])) for col in _filter_columns(S)},
        "search": st.session_state.get(_k(S, "f_search"), ""),
        "ratio": list(st.session_state.get(_k(S, "f_ratio_pref"), [None, None])),
        "stat": st.session_state.get(_k(S, "stat_current")),
        "chart_groups": {name: bool(st.session_state.get(_k(S, f"grp_{name}"), True))
                         for name in _chart_toggles(S)},
    }


def _save_filters(S: Strategy) -> None:
    saved = _current_prefs(S)
    prefs.save_prefs(_prefs_path(S), saved, _filter_columns(S))
    st.session_state[_k(S, "stat_default")] = saved["stat"]
    st.session_state[_k(S, "prefs_note")] = "Saved. This dashboard will open like this from now on."


def _restore_filters(S: Strategy) -> None:
    _apply_prefs(S, prefs.load_prefs(_prefs_path(S), _filter_columns(S)))
    st.session_state[_k(S, "prefs_note")] = "Saved filters restored."


def _clear_filters(S: Strategy) -> None:
    _apply_prefs(S, prefs.default_prefs(_filter_columns(S)))
    st.session_state[_k(S, "prefs_note")] = "Filters cleared (press Save filters to make this the default)."


def _filters(S: Strategy, res: pd.DataFrame) -> pd.DataFrame:
    def options(col: str) -> list:
        """Values in this file plus whatever is already selected, so a saved filter never breaks."""
        present = sorted(res[col].dropna().unique()) if col in res.columns else []
        selected = st.session_state.get(_k(S, f"f_{col}"), [])
        return present + [v for v in selected if v not in present]

    picks = {col: slot.multiselect(label, options(col), key=_k(S, f"f_{col}"), disabled=col not in res.columns)
             for slot, (col, label) in zip(st.columns(len(S.filter_cols)), S.filter_cols)}
    # stock attributes from tickers.csv: in a section that stays closed until opened
    attr_cols = [(c, universe.ATTR_LABELS[c]) for c in universe.ATTR_COLS]
    active = [lbl for c, lbl in attr_cols if st.session_state.get(_k(S, f"f_{c}"))]
    with st.expander(":material/sell: Stock attributes · market cap, F&O, sectors", expanded=False):
        st.caption("From tickers.csv. Indices and commodities show as Index / Commodity."
                   + (f" Filters on: {', '.join(active)}." if active else ""))
        picks.update({col: slot.multiselect(label, options(col), key=_k(S, f"f_{col}"))
                      for slot, (col, label) in zip(st.columns(len(attr_cols)), attr_cols)})

    row2 = st.columns([2, 2.2, 1.3, 1.1, 0.9], vertical_alignment="bottom")
    search = row2[0].text_input("Ticker search", key=_k(S, "f_search"), placeholder="e.g. BAJ")
    ratio = res[S.ratio_col].dropna()
    lo, hi = (float(ratio.min()), float(ratio.max())) if len(ratio) else (0.0, 1.0)
    pref_key = _k(S, "f_ratio_pref")
    if hi > lo:
        st.session_state[_k(S, "f_ratio")] = prefs.ratio_range(st.session_state.get(pref_key, [None, None]), lo, hi)
        rng = row2[1].slider(f"{S.ratio_col} range", min_value=lo, max_value=hi, key=_k(S, "f_ratio"))
        st.session_state[pref_key] = prefs.ratio_pref(rng, lo, hi)
    path = _prefs_path(S)
    row2[2].button("Save filters", type="primary", width="stretch", on_click=_save_filters, args=(S,),
                   icon=":material/save:", key=_k(S, "save_filters"),
                   help="Remember these filters, the selected stat and the chart toggles. "
                        "This dashboard opens with them every time.")
    row2[3].button("Restore", width="stretch", on_click=_restore_filters, args=(S,), icon=":material/restore:",
                   disabled=not path.exists(), key=_k(S, "restore_filters"))
    row2[4].button("Clear", width="stretch", on_click=_clear_filters, args=(S,),
                   icon=":material/filter_alt_off:", key=_k(S, "clear_filters"))
    note = st.session_state.pop(_k(S, "prefs_note"), None)
    if note:
        st.caption(note)
    elif path.exists() and _current_prefs(S) != prefs.load_prefs(path, _filter_columns(S)):
        st.caption("Filters differ from the saved ones.")

    view = res
    for col, chosen in picks.items():
        if chosen and col in view.columns:
            view = view[view[col].isin(chosen)]
    if search.strip():
        view = view[view["Ticker"].str.contains(search.strip(), case=False, regex=False)]
    low, high = st.session_state.get(pref_key, [None, None]) if hi > lo else (None, None)
    if low is not None:
        view = view[view[S.ratio_col] >= low]
    if high is not None:
        view = view[view[S.ratio_col] <= high]
    return view


# ---- signal chart -----------------------------------------------------------------
def _signal_chart(S: Strategy, row: pd.Series, params: dict[str, Any], prefix: str,
                  compact: bool = False) -> None:
    """
    Level / EMA / indicator toggles and the candlestick for one signal.
    `prefix` keeps widget keys apart; `compact` uses the smaller overlay sizes.
    """
    toggles = st.columns(len(S.level_groups) + 2)
    for name in _chart_toggles(S):
        st.session_state.setdefault(_k(S, f"{prefix}_{name}"), True)
    groups = [name for col, name in zip(toggles, S.level_groups)
              if col.toggle(name, key=_k(S, f"{prefix}_{name}"))]
    show_ema = toggles[len(S.level_groups)].toggle(charts.EMA_GROUP, key=_k(S, f"{prefix}_ema"))
    emas = ([("EMA 13", cfg["chart"]["ema_fast"]), ("EMA 55", cfg["chart"]["ema_slow"])]
            if show_ema else [])
    show_panes = toggles[len(S.level_groups) + 1].toggle(
        "Indicators", key=_k(S, f"{prefix}_ind"),
        help="RSI, DT oscillator (K, D) and histogram in one pane under the price")
    chart_cfg = cfg["chart"]

    stock = stock_df()
    bars = stock[stock["Ticker"] == row["Ticker"]]
    price = bars[bars["time_frame"] == row["time_frame"]]
    if price.empty:
        st.warning(f"No {row['time_frame']} bars for {row['Ticker']} in stock.csv - cannot draw the chart.")
        return
    # chart timeframe: the signal's own by default (a new signal starts there again)
    have = set(bars["time_frame"].unique())
    tf_options = [tf for tf in chart_cfg["timeframes"] if tf in have] or [row["time_frame"]]
    if row["time_frame"] not in tf_options:
        tf_options.append(row["time_frame"])
    tf_key = _k(S, f"{prefix}_ctf_{row['Ticker']}_{row['time_frame']}_{row['signal_time']}")
    view_tf = st.segmented_control(
        "Chart timeframe", tf_options, default=row["time_frame"], key=tf_key,
        format_func=lambda tf: f"{tf} (signal)" if tf == row["time_frame"] else tf,
        help="Show the same signal on another timeframe. Levels stay; the signal bar, wave points and "
             "entry / stop / target markers move to the bars that contain them.") or row["time_frame"]
    if S.overlay_from_row is not None:
        overlay = S.overlay_from_row(row)
    else:
        overlay = _overlay(str(cfg["stock_csv"]), cfg["stock_csv"].stat().st_mtime,
                           row["Ticker"], row["time_frame"], str(row["signal_time"]),
                           int(row["zigzag_length"]), params.get("pivot_tie", ENGINE["pivot_tie"]),
                           params.get("hi_source", ENGINE["hi_source"]),
                           params.get("lo_source", ENGINE["lo_source"]))
    horizon = int(params.get("horizon_bars", ENGINE["horizon_bars"]))
    title, signal_tf, had_waves = S.chart_title(row), row["time_frame"], overlay is not None
    if view_tf != row["time_frame"]:
        view = bars[bars["time_frame"] == view_tf]
        row, overlay, horizon = charts.on_timeframe(row, overlay, price, view, view_tf, horizon, S.targets)
        price, title = view, f"{title} · chart {view_tf}"
    fig = charts.signal_chart(
        price, row, overlay,
        horizon_bars=horizon,
        bars_before=int(chart_cfg["bars_before"]), groups=groups,
        height=int(chart_cfg["overlay_height" if compact else "height"]), emas=emas,
        panes=chart_cfg["indicator_panes"] if show_panes else (),
        pane_height=int(chart_cfg["overlay_pane_height" if compact else "pane_height"]),
        level_groups=S.level_groups, level_labels=S.level_labels, targets=S.targets,
        side_col=S.side_col, wave_name=S.wave_name, title=title)
    st.plotly_chart(fig, theme=None, config=PLOT_CONFIG, key=_k(S, f"{prefix}_fig"))
    if view_tf != signal_tf:
        st.caption(f"{signal_tf} signal shown on {view_tf} bars: levels unchanged; the signal bar, wave points and "
                   f"entry / stop / target markers are on the {view_tf} bars that contain them.")
    if overlay is None:
        st.caption(f"Part of the wave count is outside the stored {view_tf} history, so only price and levels "
                   "are shown." if had_waves else
                   "The engine has no wave count at this bar, so only price and levels are shown.")


def _htf_note(row: pd.Series) -> str:
    """e.g. 'ALIGNED · 4hr BULLISH · 1D BULLISH' (empty for results saved before this existed)."""
    if pd.isna(row.get("alignment")):
        return ""
    parents = HTF["ladder"].get(row["time_frame"], [])
    trends = [f"{tf} {row[col]}" for tf, col in zip(parents, htf.TREND_COLS) if pd.notna(row.get(col))]
    return " · ".join([str(row["alignment"]), *trends])


def _open_chart_overlay(S: Strategy, row: pd.Series, params: dict[str, Any]) -> None:
    """Pop-up with the same chart, so a clicked signal can be read without scrolling."""
    title = f"{S.key.upper()} · {row['Ticker']} · {row['time_frame']} · {row['degree']} · {row[S.side_col]}"

    def body() -> None:
        facts = [("Signal", pd.Timestamp(row["signal_time"]).strftime("%d %b %Y %H:%M")),
                 ("Close", f"{row['close']:,.2f}"),
                 *((label, f"{row[level]:,.2f}") for label, level in S.fact_levels)]
        if pd.notna(row.get("status")):
            outcome = row["status"] if pd.isna(row.get("result")) else f"{row['status']} · {row['result']}"
            facts.append(("Outcome", outcome))
        if _htf_note(row):
            facts.append(("Higher timeframes", _htf_note(row)))
        st.caption("  |  ".join(f"**{label}** {value}" for label, value in facts))
        _signal_chart(S, row, params, prefix="dlg", compact=True)

    st.dialog(title, width="large")(body)()


def _chart_pick(slot, fig, key: str) -> list[list]:
    """Draw a breakdown chart whose bars can be clicked; returns the clicked bars' data."""
    event = slot.plotly_chart(fig, theme=None, config=PLOT_CONFIG, key=key,
                              on_select="rerun", selection_mode="points")
    return charts.picked_bars(fig, event.selection.points)


def _bump(key: str) -> None:
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _style_signals(table: pd.DataFrame, side_col: str):
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

    def aligned(value: Any) -> str:
        colour = {htf.ALIGNED: UP, htf.MIXED: AMBER, htf.AGAINST: DOWN}.get(value)
        return f"color: {colour}; font-weight: 700" if colour else ""

    def trend(value: Any) -> str:
        colour = {htf.BULLISH: UP, htf.BEARISH: DOWN}.get(value)
        return f"color: {colour}" if colour else ""

    formats = {"signal_time": lambda t: "" if pd.isna(t) else f"{t:%Y-%m-%d %H:%M}"}
    styled = table.style.format({k: v for k, v in formats.items() if k in table.columns},
                                precision=2, na_rep="")
    if side_col in table.columns:
        styled = styled.map(side, subset=[side_col])
    if "histogram" in table.columns:
        styled = styled.map(histogram, subset=["histogram"])
    if "alignment" in table.columns:
        styled = styled.map(aligned, subset=["alignment"])
    trend_cols = [c for c in htf.TREND_COLS if c in table.columns]
    if trend_cols:
        styled = styled.map(trend, subset=trend_cols)
    return styled


def _on_table_click(table_key: str, flag_key: str) -> None:
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
        st.session_state[flag_key] = True


def render_dashboard(S: Strategy) -> None:
    """One dashboard: results picker, filters, stat cards, breakdown charts, table, chart, details."""
    if _k(S, "prefs_loaded") not in st.session_state:        # once per browser session
        _apply_prefs(S, prefs.load_prefs(_prefs_path(S), _filter_columns(S)))
        st.session_state[_k(S, "prefs_loaded")] = True

    files = runner.list_results(cfg["results_dir"], S.key)
    st.caption(f"**{S.name}** · {S.blurb}")
    if not files:
        st.info(f"No {S.key.upper()} results yet. In the **Run / Backtest** tab choose "
                f"**{S.name}** and run a screen or backtest.")
        return
    names = [f.name for f in files]
    file_key = _k(S, "dash_file")
    if st.session_state.get(file_key) not in names:
        st.session_state[file_key] = names[0]
    head = st.columns([2, 3])
    chosen = head[0].selectbox("Results file", names, key=file_key)
    path = cfg["results_dir"] / chosen
    res, meta = _load_results(str(path), path.stat().st_mtime)
    res = universe.attach(res, attributes())                      # market cap, F&O, sectors (tickers.csv)
    params = meta.get("params", {})
    mode_name = runner.MODES.get(params.get("mode", ""), "Run")
    period = (params.get("as_of") or
              (f"{params.get('start')} → {params.get('end')}" if params.get("start") else "latest bar"))
    extra = (f" · retrace {params.get('min_retrace')}–{params.get('max_retrace')}"
             f" · contexts {', '.join(params.get('contexts', []))}" if S.key == "ew3" else "")
    head[1].caption(f"**{mode_name}** · {period} · lengths {params.get('lengths', '?')} · "
                    f"horizon {params.get('horizon_bars', '?')} bars · pivot_tie {params.get('pivot_tie', '?')}"
                    f"\n\nstages {', '.join(params.get('stages', []))}{extra} · "
                    f"{universe.UNIVERSES.get(params.get('universe', 'all'), 'All stocks')}")

    if res.empty:
        st.info("This run produced no signals.")
        return

    with st.container(border=True):
        filtered = _filters(S, res)
    evaluated = runner.has_outcomes(res)
    stat_key = _k(S, f"stat_file_{chosen}")
    if filtered.empty:
        st.warning("No signals match the filters.")
        return
    nonce_key = _k(S, f"chartsel_{chosen}")
    suffix = f"{S.key}_{chosen}_{len(filtered)}_{st.session_state.get(nonce_key, 0)}"
    picked_notes: list[str] = []
    chart_mask = pd.Series(True, index=filtered.index)

    # ---- signals by stock attribute, right under the filters: click a bar to narrow the table
    attr_slots = st.columns(len(universe.CHART_COLS))
    for slot, col in zip(attr_slots, universe.CHART_COLS):
        picked = [(c, v) for c, v in _chart_pick(slot, charts.attribute_breakdown(
            filtered, col, universe.ATTR_LABELS[col], S.side_col, height=320), f"attr_{col}_{suffix}") if v != "other"]
        if picked:
            chart_mask &= universe.mask(filtered, {col: [v for _, v in picked]})
            picked_notes.append(f"{universe.ATTR_LABELS[col]} {', '.join(v for _, v in picked)}")

    view = _kpi_cards(S, filtered, stat_key) if evaluated else _live_cards(S, filtered, stat_key)

    # ---- breakdown charts: click a bar to narrow the table
    st.markdown("#### :material/bar_chart: Breakdown")
    st.caption("Click a bar to filter the signal table to the signals inside it. Shift-click adds more bars.")
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
        if "alignment" in filtered.columns:
            stats = S.alignment_stats(filtered)
            left, right = st.columns(2)
            (t1_label, _), (t2_label, _) = S.target_cards
            picked_align = _chart_pick(left, charts.alignment_breakdown(
                stats, t1_label.split(": ", 1)[-1], t2_label.split(": ", 1)[-1]), f"align_{suffix}")
            with right.container(border=True):
                st.markdown("**Does trading with the higher timeframe pay?**")
                st.caption("ALIGNED: every higher timeframe points the way of the trade · "
                           "AGAINST: the next timeframe up points the other way · MIXED: in between. "
                           "Rates are out of triggered signals.")
                st.dataframe(
                    stats.rename(columns={
                        "alignment": "Alignment", "signals": "Signals", "trigger_rate": "Trigger %",
                        "fail_pct": "Failed %", "t1_hit_rate": "Target 1 %", "t2_hit_rate": "Target 2 %",
                        "stop_rate": "Stop %", "avg_mfe": "Avg MFE %", "avg_mae": "Avg MAE %"}),
                    hide_index=True,
                    column_config={c: st.column_config.NumberColumn(format="%.1f") for c in (
                        "Trigger %", "Failed %", "Target 1 %", "Target 2 %", "Stop %", "Avg MFE %", "Avg MAE %")})
            if picked_align:
                names = [a for (a,) in picked_align]
                chart_mask &= filtered["alignment"].isin(names)
                picked_notes += [f"HTF {a}" for a in names]
        with st.expander("Summary table (by timeframe × degree)", icon=":material/table_chart:"):
            st.dataframe(S.summarize(filtered), hide_index=True)
    else:
        bars = _chart_pick(st, charts.side_breakdown(filtered, by=S.side_col), f"sides_{suffix}")
        if bars:
            chart_mask &= runner.bar_mask(filtered, S.side_col, bars)
            picked_notes += [f"{tf} {degree} {value}" for tf, degree, value in bars]
    if picked_notes:
        note = st.columns([5, 1], vertical_alignment="center")
        note[0].markdown(":material/filter_alt: **Chart filter:** " + " · ".join(picked_notes))
        note[1].button("Clear chart filter", width="stretch", icon=":material/close:",
                       on_click=_bump, args=(nonce_key,), key=_k(S, "clear_chart"))
        view = view[chart_mask.loc[view.index]]
    view = view.sort_values("signal_time", ascending=False, kind="stable").reset_index(drop=True)   # newest first

    st.markdown("#### :material/table_rows: Signals")
    narrowed = " · narrowed by the selected stat / chart bar" if len(view) < len(filtered) else ""
    st.caption(f"{len(view)} of {len(res)} signals{narrowed} · newest first")
    if view.empty:
        st.warning("No signals behind this selection.")
        return

    table_head = st.columns([4, 1])
    table_head[0].caption("Click any cell of a signal to open its chart in an overlay. The same chart stays below.")
    reopen = table_head[1].button("Open chart overlay", width="stretch", icon=":material/open_in_full:",
                                  key=_k(S, "reopen"), help="Opens the overlay again for the selected row")
    table_key = _k(S, f"signals_{chosen}_{len(view)}")
    flag_key = _k(S, "open_overlay")
    table_cols = [c for c in (*S.table_cols, *cfg["signal_indicators"]) if c in view.columns]
    st.dataframe(_style_signals(view[table_cols], S.side_col), hide_index=True, height=300,
                 on_select=lambda key=table_key, flag=flag_key: _on_table_click(key, flag),
                 selection_mode=["single-row", "single-cell"], key=table_key)
    picked = st.session_state.get(f"{table_key}_row", 0)
    row = view.iloc[picked if picked < len(view) else 0]
    if st.session_state.pop(flag_key, False) or reopen:
        _open_chart_overlay(S, row, params)

    side_colour = "red" if row[S.side_col] == "SHORT" else "green"
    st.markdown(f"#### :material/candlestick_chart: {row['Ticker']} · {row['time_frame']} · "
                f"{row['degree']} · :{side_colour}[{row[S.side_col]}]")
    if _htf_note(row):
        align_colour = {htf.ALIGNED: "green", htf.AGAINST: "red", htf.MIXED: "orange"}.get(row["alignment"], "gray")
        st.markdown(f":material/stacked_line_chart: **Higher timeframes:** :{align_colour}[{_htf_note(row)}]")
    _signal_chart(S, row, params, prefix="grp")

    st.markdown("#### :material/info: Signal details")
    d1, d2 = st.columns([3, 2])
    level_names = list(S.level_names)
    fields = row.drop(labels=[c for c in [*level_names, S.levels_col] if c in row.index])
    d1.dataframe(pd.DataFrame({"Field": fields.index, "Value": fields.astype(str).values}),
                 hide_index=True, height=420)
    d2.metric("Live count", row["live_count"] if pd.notna(row.get("live_count")) else "–")
    d2.dataframe(pd.DataFrame({"Level": level_names, "Price": [row.get(n) for n in level_names]}),
                 hide_index=True, height=330,
                 column_config={"Price": st.column_config.NumberColumn(format="%.2f")})


with tab_ew5:
    render_dashboard(strategies.EW5)
with tab_ew3:
    render_dashboard(strategies.EW3)


# ----------------------------------------------------------------------------------
# Tab - User Guide
# ----------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------
# Tab - Alerts: scheduled scans on this Mac (scheduled_scan.py + macOS launchd)
# ----------------------------------------------------------------------------------
def _alert_times(text: str) -> list[str]:
    return [t.strip() for t in text.replace(";", ",").split(",") if t.strip()]


with tab_alerts:
    import scheduled_scan as sc
    from core import alert_events as ev, alert_settings as aset

    st.subheader(":material/notifications: Alerts · scheduled scans on this Mac")
    st.caption("At the set times this Mac downloads the latest data, runs EW5 and EW3 and shows one notification "
               "(and a Telegram message if switched on) with the stocks triggered or set up today. The usual times "
               "scan the chosen stocks (default F&O); the weekly full scan covers every stock in tickers.csv. "
               "The phone app has the same Alerts, with its own settings.")
    a_settings = sc.load_settings(cfg)
    a_status = sc.status()
    loaded = any(v["loaded"] for v in a_status.values())
    with st.container(border=True):
        top = st.columns([3, 1.2, 1.2], vertical_alignment="center")
        top[0].markdown(f"**Schedule:** {':green[installed]' if loaded else ':orange[not installed]'}"
                        + (f" · next: {' · '.join(aset.next_runs(a_settings))}" if a_settings.get("enabled") else " · scans are off"))
        if top[1].button("Install schedule" if not loaded else "Update schedule", type="primary", width="stretch",
                         icon=":material/schedule:", key="alerts_install",
                         help="Adds two macOS launch agents (~/Library/LaunchAgents/com.ewscanner.scan.*) "
                              "that run scheduled_scan.py at the times below"):
            sc.install(cfg)
            st.rerun()
        if top[2].button("Remove schedule", width="stretch", icon=":material/schedule_send:", disabled=not loaded,
                         key="alerts_uninstall"):
            sc.uninstall()
            st.rerun()
        st.caption("The Mac must be on: a scan missed while it slept runs as soon as it wakes. "
                   "Notifications come from Script Editor / osascript; allow them in System Settings → Notifications.")
        run_cols = st.columns(2)
        for col, (kind, label) in zip(run_cols, (("regular", f"Run {universe.UNIVERSES[a_settings['universe']]} scan now"),
                                               ("full", "Run full scan now (all stocks)"))):
            if col.button(label, width="stretch", icon=":material/play_arrow:", key=f"alerts_run_{kind}"):
                cfg["logs_dir"].mkdir(parents=True, exist_ok=True)
                with open(cfg["logs_dir"] / "scheduled_scan.log", "a") as out:
                    subprocess.Popen([sys.executable, str(ROOT / "scheduled_scan.py"), "--kind", kind, "--source", "manual"],
                                     cwd=ROOT, stdout=out, stderr=out, start_new_session=True)
                st.toast("Scan started in the background. The notification comes when it finishes.")

    with st.form("alert_settings"):
        st.markdown("**Settings**")
        f1, f2, f3 = st.columns(3)
        v_enabled = f1.checkbox("Scheduled scans on", value=a_settings["enabled"])
        v_days = f2.multiselect("Days", list(range(1, 8)), default=a_settings["days"], format_func=lambda d: aset.DAYS[d - 1])
        v_times = f3.text_input("Times (24 h, comma separated)", ", ".join(a_settings["times"]))
        f1, f2, f3 = st.columns(3)
        v_universe = f1.radio("Stocks for these scans", list(universe.UNIVERSES), format_func=_universe_label,
                              index=list(universe.UNIVERSES).index(a_settings.get("universe", "fno")))
        v_full = f2.checkbox("Weekly full scan of every stock", value=a_settings.get("full_enabled", True))
        v_full_days = f2.multiselect("Full scan day", list(range(1, 8)), default=a_settings.get("full_days", [5]),
                                     format_func=lambda d: aset.DAYS[d - 1])
        v_full_times = f3.text_input("Full scan time", ", ".join(a_settings.get("full_times", ["18:00"])))
        v_update = f3.checkbox("Download the latest data first", value=a_settings["update_data"])
        f1, f2, f3 = st.columns(3)
        v_strats = f1.multiselect("Screeners", list(strategies.STRATEGIES), default=a_settings["strategies"],
                                  format_func=lambda k: strategies.STRATEGIES[k].name)
        v_tfs = f2.multiselect("Timeframes", ["1D", "4hr", "60m", "1W"], default=a_settings["timeframes"])
        v_events = f3.multiselect("Notify about", ["TRIGGERED", "NEW"], default=a_settings["events"],
                                  format_func=lambda e: "Triggered today" if e == "TRIGGERED" else "New setups today")
        f1, f2 = st.columns(2)
        v_aligned = f1.checkbox("Only signals ALIGNED with the higher timeframes", value=a_settings["aligned_only"])
        v_lookback = f2.number_input("Setups from the last N days can trigger today", 2, 60, int(a_settings["lookback_days"]))
        st.markdown("**Telegram** (optional)")
        t1, t2, t3 = st.columns([1, 2, 1.4])
        v_tg = t1.radio("Telegram", ["Off", "On"], index=1 if a_settings.get("telegram") else 0, horizontal=True)
        v_token = t2.text_input("Bot token", type="password",
                                placeholder="saved (type to replace)" if a_settings.get("telegram_token") else "123456789:AA…")
        v_chat = t3.text_input("Chat ID", a_settings.get("telegram_chat_id", ""))
        v_head = st.text_input("Message header", a_settings.get("telegram_header"))
        v_line = st.text_area("One line per stock", a_settings.get("telegram_line"), height=70,
                              help="Placeholders: " + ", ".join("{" + k + "}" for k in ev.LINE_FIELDS)
                                   + " · header: " + ", ".join("{" + k + "}" for k in ev.HEADER_FIELDS))
        v_group = st.checkbox('Group into "Triggered today" and "New setups today"', value=a_settings.get("telegram_group", True))
        if st.form_submit_button("Save settings", type="primary", icon=":material/save:"):
            try:
                sc.save_settings(cfg, {
                    "enabled": v_enabled, "days": v_days, "times": _alert_times(v_times), "universe": v_universe,
                    "full_enabled": v_full, "full_days": v_full_days, "full_times": _alert_times(v_full_times),
                    "update_data": v_update, "strategies": v_strats, "timeframes": v_tfs, "events": v_events,
                    "aligned_only": v_aligned, "lookback_days": v_lookback, "telegram": v_tg == "On",
                    "telegram_token": v_token, "telegram_chat_id": v_chat, "telegram_header": v_head,
                    "telegram_line": v_line, "telegram_group": v_group})
                st.success("Saved" + (" and the schedule updated." if loaded else ". Press Install schedule to run it on this Mac."))
            except ValueError as exc:
                st.error(str(exc))

    tg_cols = st.columns([1, 1, 3])
    if tg_cols[0].button("Preview Telegram message", icon=":material/visibility:", key="alerts_preview"):
        st.code(ev.telegram_text("EW alerts today (example)", ev.SAMPLE, a_settings)[0], language=None)
    if tg_cols[1].button("Send test to Telegram", icon=":material/send:", key="alerts_tg_test",
                         disabled=not (a_settings.get("telegram_token") and a_settings.get("telegram_chat_id"))):
        result = ev.send_telegram(a_settings, "EW Scanner · test alert", ev.SAMPLE)
        (st.success if result == "sent" else st.error)(f"Telegram: {result}")

    last = sc._read(sc._dir(cfg) / "alerts_last_run.json", None)
    if last:
        with st.container(border=True):
            st.markdown(f"**Last scan** · {last.get('started', '').replace('T', ' ')} · "
                        f"{universe.UNIVERSES.get(last.get('universe', 'fno'), '')} · {last.get('source')}")
            if last.get("skipped"):
                st.warning(f"Skipped: {last['skipped']}")
            else:
                st.caption(f"{last.get('seconds', '?')} s · today: {last.get('triggered', 0)} triggered, "
                           f"{last.get('new_setups', 0)} new setups · {last.get('new_events', 0)} not notified before"
                           + (f" · Telegram: {last['telegram']}" if last.get("telegram") else ""))
    hist = sc._read(sc._dir(cfg) / "alerts_history.json", [])
    if hist:
        hist_df = pd.DataFrame(hist[::-1])
        today_df = hist_df[hist_df["day"].eq(str(pd.Timestamp.now().date()))]
        show = ["at", "event", "strategy", "ticker", "tf", "degree", "side", "alignment", "trigger", "stop", "file"]
        st.markdown(f"**Today ({len(today_df)})** · open the stock in the EW5 / EW3 tab with its `backtest_auto_…` file")
        st.dataframe(today_df[[c for c in show if c in today_df.columns]], hide_index=True, height=260)
        with st.expander(f"Last 14 days ({len(hist_df)})"):
            st.dataframe(hist_df[[c for c in show if c in hist_df.columns]], hide_index=True, height=320)


with tab_guide:
    functional, technical = st.tabs(["How to use it (F&O)", "Technical documentation"])
    functional.markdown((ROOT / "docs" / "functional_guide.md").read_text(encoding="utf-8"))
    technical.markdown((ROOT / "docs" / "technical_guide.md").read_text(encoding="utf-8"))
