from __future__ import annotations

import pandas as pd
import pytest

import elliott_wave5_screener as ew
from core import data_store as ds, htf, runner, strategies
from core.config import load_config
from tests.conftest import make_engine_df

CFG = load_config()
HTF = CFG["htf"]
STAGES = (ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    """Daily fixture bars plus the weekly bars and indicators the app would store."""
    return ds.add_indicators(ds.with_weekly(make_engine_df(n=500), CFG))


def test_weekly_bars_are_built_from_daily_bars():
    daily = make_engine_df(tickers=("AAA.NS",), n=30)                 # starts Monday 2023-01-02
    weekly = ds.weekly_bars(daily)
    assert len(weekly) == 6 and set(weekly["time_frame"]) == {"1W"}
    assert (weekly["time"].dt.day_of_week == 0).all()                   # stamped with the Monday
    first, week1 = weekly.iloc[0], daily.iloc[:5]
    assert first["Open"] == week1["Open"].iloc[0] and first["Close"] == week1["Close"].iloc[-1]
    assert first["High"] == week1["High"].max() and first["Low"] == week1["Low"].min()
    assert first["Volume"] == week1["Volume"].sum()


def test_with_weekly_replaces_old_weekly_rows():
    once = ds.with_weekly(make_engine_df(n=60), CFG)
    twice = ds.with_weekly(once, CFG)
    pd.testing.assert_frame_equal(once, twice)
    assert not once.duplicated(ds.KEYS).any() and set(once["time_frame"]) == {"1D", "1W"}


def test_bar_trend_rules():
    close = pd.Series([110.0, 90.0, 105.0, 95.0, 100.0])
    fast = pd.Series([105.0, 95.0, 95.0, 105.0, float("nan")])
    slow = pd.Series([100.0] * 5)
    assert list(htf.bar_trend(close, fast, slow)) == [
        htf.BULLISH, htf.BEARISH, htf.NEUTRAL, htf.NEUTRAL, htf.UNKNOWN]


@pytest.mark.parametrize("side, trends, expected", [
    ("LONG", ["BULLISH", "BULLISH"], "ALIGNED"),
    ("SHORT", ["BEARISH", "BEARISH"], "ALIGNED"),
    ("LONG", ["BULLISH"], "ALIGNED"),
    ("LONG", ["BULLISH", "UNKNOWN"], "ALIGNED"),
    ("LONG", ["BEARISH", "BULLISH"], "AGAINST"),          # the case that hurts: parent the other way
    ("SHORT", ["BULLISH", "BEARISH"], "AGAINST"),
    ("LONG", ["BULLISH", "BEARISH"], "MIXED"),
    ("LONG", ["NEUTRAL", "BULLISH"], "MIXED"),
    ("LONG", ["BULLISH", "NEUTRAL"], "MIXED"),
    ("LONG", ["UNKNOWN", "BULLISH"], "UNKNOWN"),
    ("LONG", [None, None], "UNKNOWN"),
])
def test_alignment_mapping(side, trends, expected):
    assert htf.alignment(side, trends) == expected


def test_signal_reads_the_last_finished_weekly_bar(df):
    """A daily signal on a Wednesday must use last week's bar, not the week still forming."""
    weekly = df[(df["time_frame"] == "1W") & (df["Ticker"] == "AAA.NS")].reset_index(drop=True)
    trend = htf.bar_trend(weekly["Close"], weekly["13_ema"], weekly["55_ema"])
    k = len(weekly) - 3
    for offset in (0, 2, 4):                                          # Monday, Wednesday, Friday
        signal = pd.DataFrame({"Ticker": ["AAA.NS"], "time_frame": ["1D"], "side": ["LONG"],
                               "signal_time": [weekly["time"].iloc[k] + pd.Timedelta(days=offset)]})
        out = htf.attach_alignment(signal, df, "side", HTF)
        assert out["htf1_trend"].iloc[0] == trend.iloc[k - 1]
        assert pd.isna(out["htf2_trend"].iloc[0])                     # 1D has no grandparent


def test_no_look_ahead_alignment_equals_truncated_data(df):
    params = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES,
                              horizon_bars=30)
    res = runner.run_engine(df, params, htf_cfg=HTF)
    assert len(res) > 0 and set(res["alignment"]) <= set(htf.ALIGNMENTS)
    assert res["alignment"].isin([htf.ALIGNED, htf.AGAINST]).any()
    daily = df[df["time_frame"] == "1D"]
    for _, row in res.iloc[:: max(1, len(res) // 12)].iterrows():
        past = daily[daily["time"] <= row["signal_time"]][ds.BASE_SCHEMA]
        known = ds.add_indicators(ds.with_weekly(past, CFG))          # what was knowable at that bar
        again = htf.attach_alignment(row.drop(list(htf.COLUMNS)).to_frame().T, known, "reversal_side", HTF)
        assert again["alignment"].iloc[0] == row["alignment"]
        assert again["htf1_trend"].iloc[0] == row["htf1_trend"]


def test_aligned_only_and_results_round_trip(df, tmp_path):
    base = dict(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES, horizon_bars=30)
    everything = runner.run_engine(df, runner.RunParams(**base), htf_cfg=HTF)
    only = runner.run_engine(df, runner.RunParams(**base, aligned_only=True), htf_cfg=HTF)
    assert len(only) == int(everything["alignment"].eq(htf.ALIGNED).sum()) and 0 < len(only) < len(everything)
    plain = runner.run_engine(df, runner.RunParams(**base))           # without htf: nothing is added
    assert "alignment" not in plain.columns and len(plain) == len(everything)

    path = runner.save_results(everything, runner.RunParams(**base), tmp_path)
    back, _ = runner.load_results(path)
    assert list(back["alignment"]) == list(everything["alignment"])
    stats = strategies.EW5.alignment_stats(back)
    assert stats["signals"].sum() == len(back) and set(stats["alignment"]) <= set(htf.ALIGNMENTS)
