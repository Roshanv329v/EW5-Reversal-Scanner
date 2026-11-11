from __future__ import annotations

import pandas as pd
import pytest

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew5
from tests.conftest import make_engine_df

ALL = dict(stages=ew3.STAGES, contexts=ew3.CONTEXTS)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return make_engine_df(tickers=("AAA.NS", "BBB.NS", "CCC.NS"), n=500)


@pytest.fixture(scope="module")
def results(df) -> pd.DataFrame:
    return ew3.backtest_wave3(df, **ALL)


def _levels(row) -> dict:
    return {k: float(v) for k, v in (s.split("=") for s in row["wave_levels"])}


def test_backtest_finds_signals_with_all_levels(results):
    assert len(results) > 20, "fixture should produce plenty of 0-1-2 setups"
    for _, row in results.iterrows():
        assert [s.split("=")[0] for s in row["wave_levels"]] == list(ew3.LEVEL_NAMES)
    assert set(results["stage"]) <= set(ew3.STAGES) and set(results["context"]) <= set(ew3.CONTEXTS)


def test_wave2_rule_holds_for_every_signal(results):
    for _, row in results.iterrows():
        lv = _levels(row)
        d = 1 if row["trade_side"] == "LONG" else -1
        w1 = (lv["W1_END"] - lv["W0_START"]) * d
        assert w1 > 0
        retrace = (lv["W1_END"] - lv["W2_END"]) * d / w1
        assert 0.38 <= retrace <= 0.79                                # rounding of stored levels
        assert (lv["W2_END"] - lv["W0_START"]) * d > 0                # wave 2 never passes wave 0
        assert lv["STOP"] == lv["W2_END"]
        assert (lv["W3_TGT_1.618xW1"] - lv["W3_TGT_1.000xW1"]) * d > 0
        assert row["w0_time"] < row["w1_end_time"] < row["w2_end_time"] < row["signal_time"]


def test_no_look_ahead_as_of_equals_truncated_data(df):
    checked = 0
    for day in ("2023-09-15", "2024-01-31", "2024-05-20", "2024-09-10"):
        d = pd.Timestamp(day)
        a = ew3.screen_wave3(df, as_of=d, **ALL)
        b = ew3.screen_wave3(df[df["time"] <= d], **ALL)
        pd.testing.assert_frame_equal(a, b)
        checked += len(a)
    assert checked > 0


def test_backtest_signals_match_point_in_time_screen(df, results):
    for _, row in results.head(8).iterrows():
        snap = ew3.screen_wave3(df, as_of=row["signal_time"], **ALL)
        match = snap[(snap["Ticker"] == row["Ticker"]) & (snap["zigzag_length"] == row["zigzag_length"])]
        assert len(match) == 1 and match["wave_levels"].iloc[0] == row["wave_levels"]


def test_outcomes_are_consistent(df, results):
    assert set(results["status"]) <= {"TRIGGERED", "FAILED", "NOT_TRIGGERED"}
    trig = results[results["status"] == "TRIGGERED"]
    assert len(trig) > 0 and trig["entry_price"].notna().all()
    assert results.loc[results["status"] != "TRIGGERED", "trigger_time"].isna().all()
    for _, row in trig.iterrows():
        lv = _levels(row)
        long = row["trade_side"] == "LONG"
        assert row["trigger_time"] >= row["signal_time"]
        assert (row["entry_price"] >= lv["TRIGGER"]) if long else (row["entry_price"] <= lv["TRIGGER"])
        if row["stopped"]:
            assert row["stop_time"] > row["trigger_time"]
        if row["hit_W3_TGT_1.618xW1"]:
            assert row["hit_W3_TGT_1.000xW1"] and row["hit_W1_END"]     # nearer targets come first
    summary = ew3.summarize_backtest(results)
    assert summary["signals"].sum() == len(results)


def test_filters_narrow_the_result(df, results):
    only_early = ew3.backtest_wave3(df, stages=(ew3.STAGE_W2_COMPLETED,), contexts=ew3.CONTEXTS)
    assert set(only_early["stage"]) == {ew3.STAGE_W2_COMPLETED}
    structured = ew3.backtest_wave3(df, stages=ew3.STAGES)             # default contexts
    assert set(structured["context"]) <= set(ew3.DEFAULT_CONTEXTS) and len(structured) < len(results)
    tight = ew3.backtest_wave3(df, min_retrace=0.5, max_retrace=0.618, **ALL)
    assert len(tight) < len(results) and tight["w2_retrace"].between(0.5, 0.618).all()
    with pytest.raises(ValueError):
        ew3.screen_wave3(df, max_retrace=1.0)


def test_wave5_screener_is_untouched_by_wave3(df):
    before = ew5.backtest_wave5(df, stages=(ew5.STAGE_IN_PROGRESS, ew5.STAGE_COMPLETED))
    ew3.backtest_wave3(df, **ALL)
    after = ew5.backtest_wave5(df, stages=(ew5.STAGE_IN_PROGRESS, ew5.STAGE_COMPLETED))
    pd.testing.assert_frame_equal(before, after)
