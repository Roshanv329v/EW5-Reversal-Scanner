from __future__ import annotations

import pandas as pd
import pytest

import elliott_wave5_screener as ew
from core import runner
from tests.conftest import make_engine_df

STAGES = (ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return make_engine_df()


def _params(mode: str, **kw) -> runner.RunParams:
    base = dict(mode=mode, timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES, horizon_bars=30)
    return runner.RunParams(**{**base, **kw})


def test_explode_levels_one_float_column_per_level(df):
    res = runner.run_engine(df, _params("backtest"))
    assert len(res) > 0, "fixture should produce signals"
    for name in ew.LEVEL_NAMES:
        assert name in res.columns and res[name].dtype == "float64"
    assert isinstance(res["reversal_levels"].iloc[0], list)           # original list is kept
    first = dict(s.split("=") for s in res["reversal_levels"].iloc[0])
    for name in ew.LEVEL_NAMES:
        assert res[name].iloc[0] == float(first[name])


def test_explode_levels_on_empty_result():
    empty = ew.screen_wave5(make_engine_df(n=50))                     # below min_bars -> no rows
    out = runner.explode_levels(empty)
    assert out.empty and all(name in out.columns for name in ew.LEVEL_NAMES)


def test_no_look_ahead_as_of_equals_truncated_data(df):
    checked = 0
    for day in ("2023-09-15", "2024-01-31", "2024-05-20"):
        d = pd.Timestamp(day)
        a = ew.screen_wave5(df, as_of=d, stages=STAGES)
        b = ew.screen_wave5(df[df["time"] <= d], stages=STAGES)
        pd.testing.assert_frame_equal(a, b)
        checked += len(a)
    assert checked > 0, "fixture should produce at least one as-of signal"


def test_backtest_signals_match_point_in_time_screen(df):
    """Every walk-forward signal is what the screener shows as of its own signal bar."""
    res = runner.run_engine(df, _params("backtest"))
    for _, row in res.head(5).iterrows():
        snap = ew.screen_wave5(df, as_of=row["signal_time"], stages=STAGES)
        match = snap[(snap["Ticker"] == row["Ticker"]) & (snap["zigzag_length"] == row["zigzag_length"])]
        assert len(match) == 1 and match["reversal_levels"].iloc[0] == row["reversal_levels"]


def test_asof_mode_includes_the_whole_day_and_evaluates(df):
    res = runner.run_engine(df, _params("asof", as_of="2024-01-31"))
    assert runner.has_outcomes(res) or res.empty
    assert (res["signal_time"] <= runner.end_of_day("2024-01-31")).all()
    assert runner.end_of_day("2024-01-31") == pd.Timestamp("2024-01-31 23:59:59")


def test_save_and_load_roundtrip(df, tmp_path):
    p = _params("backtest", start="2023-08-01", end="2024-03-01")
    res = runner.run_engine(df, p)
    path = runner.save_results(res, p, tmp_path, stamp="20260101_000000")
    assert path.name == "backtest_20260101_000000.csv" and path.with_suffix(".json").exists()

    back, meta = runner.load_results(path)
    assert runner.RunParams.from_json(runner.RunParams(**{**meta["params"]}).to_json()).mode == "backtest"
    assert back["reversal_levels"].tolist() == res["reversal_levels"].tolist()
    assert back["signal_time"].tolist() == res["signal_time"].tolist()
    assert runner.list_results(tmp_path) == [path]
    assert not runner.summarize(back).empty
    assert runner.kpis(back)["signals"] == len(res)


def test_check_min_bars_flags_short_history(df):
    short = runner.check_min_bars(df, "2023-03-01", 120, ["1D"])
    assert set(short["Ticker"]) == {"AAA.NS", "BBB.NS"} and (short["bars_before"] < 120).all()
    assert runner.check_min_bars(df, "2024-06-01", 120, ["1D"]).empty


def test_indicator_values_are_attached_at_the_signal_bar(df):
    data = df.assign(rsi=range(len(df)))
    res = runner.run_engine(data, _params("backtest"), indicator_cols=["rsi", "not_there"])
    assert len(res) > 0 and "not_there" not in res.columns
    for _, row in res.head(10).iterrows():
        bar = data[(data["Ticker"] == row["Ticker"]) & (data["time"] == row["signal_time"])]
        assert row["rsi"] == bar["rsi"].item()


def test_stat_masks_match_the_kpi_numbers(df):
    res = runner.run_engine(df, _params("backtest"))
    masks, k = runner.stat_masks(res), runner.kpis(res)
    n_trig = int(masks["triggered"].sum())
    assert n_trig > 0
    assert round(n_trig / len(res) * 100, 6) == round(k["trigger_rate"], 6)
    assert round(masks["w4"].sum() / n_trig * 100, 6) == round(k["w4_hit_rate"], 6)
    assert round(masks["stopped"].sum() / n_trig * 100, 6) == round(k["stop_rate"], 6)
    for name in ("w4", "fib50", "stopped", "mfe", "mae"):
        assert not (masks[name] & ~masks["triggered"]).any()        # subsets of triggered
    assert not (masks["triggered"] & masks["extended"]).any()
