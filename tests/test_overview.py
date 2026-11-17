"""Charts tab (core/overview.py, charts.stock_chart) and the phone's endpoints for it."""

import pandas as pd
import pytest

from core import charts, htf, overview, runner, strategies
from core.config import load_config
from tests.conftest import make_engine_df
from core import data_store as ds
import elliott_wave5_screener as ew

CFG = load_config()
TICKERS = [f"T{i:02d}.NS" for i in range(6)]


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return ds.add_indicators(ds.with_weekly(make_engine_df(tickers=TICKERS, n=420), CFG))


@pytest.fixture(scope="module")
def results(df):
    out = []
    for S, stages in ((strategies.EW5, (ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED)),
                      (strategies.EW3, ("WAVE2_COMPLETED",))):
        p = runner.RunParams(mode="backtest", strategy=S.key, timeframes=("1D", "4hr", "60m"), lengths=(4, 8, 16),
                             stages=stages, horizon_bars=30)
        out.append((S, runner.run_engine(df, p, CFG["signal_indicators"], CFG["htf"]), f"{S.key}_test.csv"))
    return out


def test_trend_side_needs_every_trend_timeframe():
    snap = pd.DataFrame({"Ticker": ["A"] * 4 + ["B"] * 2, "time_frame": ["60m", "4hr", "1D", "1W", "1D", "1W"],
                         "time": pd.Timestamp("2026-01-02"), "Close": 10.0,
                         "dtosck": [10, 60, 70, 80, 70, 20], "dtoscd": [20, 50, 60, 70, 60, 30]})
    t = overview.trends(snap, ("1D", "1W"))
    assert t.loc["A", "trend_side"] == "LONG" and t.loc["B", "trend_side"] == ""      # B: 1D up, 1W down
    assert overview.trend_text(t.loc["A"]) == "60m ▼ · 4hr ▲ · 1D ▲ · 1W ▲"
    assert t.loc["B", "trend_60m"] == htf.UNKNOWN


def test_a_signal_sits_on_the_bar_that_holds_it():
    daily = pd.Series(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    assert overview.bar_of(daily, pd.Timestamp("2026-01-02 13:15"), "60m") == pd.Timestamp("2026-01-02")
    hourly = pd.Series(pd.to_datetime(["2026-01-02 09:15", "2026-01-02 14:15", "2026-01-02 15:15",
                                       "2026-01-05 09:15"]))
    assert overview.bar_of(hourly, pd.Timestamp("2026-01-02"), "1D") == pd.Timestamp("2026-01-02 15:15")
    assert overview.bar_of(hourly, pd.Timestamp("2026-01-02 14:15"), "60m") == pd.Timestamp("2026-01-02 14:15")


def test_stock_list_keeps_signals_on_the_trend_side_with_a_small_stop(df, results):
    sig = overview.signals(results)
    assert set(sig["strategy"]) == {"ew5", "ew3"} and sig["risk_pct"].notna().all()
    again = overview.signals(results + results)                     # the same file twice: counted once
    assert len(again) == len(sig)
    trend = overview.trends(overview.snapshot(df))
    now = sig["signal_time"].max()
    everything = overview.stock_list(trend, sig, None, {"has_signal": True, "with_trend": False, "days": 3650}, now)
    assert set(everything.index) == set(sig["Ticker"])
    with_trend = overview.stock_list(trend, sig, None, {"has_signal": True, "with_trend": True, "days": 3650}, now)
    assert (with_trend["sig_side"] == with_trend["trend_side"]).all() and with_trend["with_trend"].all()
    tight = overview.stock_list(trend, sig, None, {"has_signal": True, "with_trend": False, "days": 3650,
                                                   "max_risk": 1.0}, now)
    assert (tight["sig_risk_pct"] <= 1.0).all()
    up = overview.stock_list(trend, sig, None, {"has_signal": False, "with_trend": False, "trend": "up"}, now)
    assert set(up.index) == set(trend.index[trend["trend_side"].eq("LONG")])
    shown = overview.table(everything)
    assert list(shown.columns[:4]) == ["Ticker", "Trend", "Trend side", "Signal"]


def test_stock_chart_draws_every_signal_of_the_stock(df, results):
    sig = overview.signals(results)
    ticker = sig["Ticker"].value_counts().index[0]
    mine = overview.ticker_signals(sig, ticker)
    frames = [tf for tf in overview.TIMEFRAMES if tf in set(df.loc[df["Ticker"] == ticker, "time_frame"])]
    assert frames == ["1D", "1W"]                                   # the fixture has daily + weekly bars
    for tf in frames:
        price = df[(df["Ticker"] == ticker) & (df["time_frame"] == tf)]
        fig = charts.stock_chart(price, tf, mine, bars=len(price), height=500)
        marks = [d for d in fig.data if d.name and d.name.split()[0] in ("EW5", "EW3")]
        counts = sum(int(t.split("×")[1]) if "×" in t else 1 for d in marks for t in d.text)
        visible = sum(overview.bar_of(price["time"].sort_values().reset_index(drop=True), r["signal_time"],
                                      r["time_frame"]) is not None for _, r in mine.iterrows())
        assert counts == visible > 0                                  # every signal, on every timeframe
    assert not [s for s in fig.layout.shapes if s.xref == "x"]        # no "signal" line without a picked signal
