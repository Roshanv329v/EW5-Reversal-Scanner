from __future__ import annotations

import elliott_wave5_screener as ew
from core import charts, runner
from tests.conftest import make_engine_df


def test_overlay_matches_signal_levels_and_chart_builds():
    df = make_engine_df()
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16),
                         stages=(ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED), horizon_bars=30)
    res = runner.run_engine(df, p)
    assert len(res) > 0
    for _, row in res.iterrows():
        price = df[(df["Ticker"] == row["Ticker"]) & (df["time_frame"] == row["time_frame"])]
        overlay = charts.wave_overlay(price, row["signal_time"], row["zigzag_length"])
        # the re-run engine reproduces the wave the signal was built from
        assert [round(y, 2) for _, y in overlay["pts"]] == [
            row[n] for n in ("W0_START", "W1_END", "W2_END", "W3_END", "W4_END", "W5_END")]
        assert overlay["pts"][5][0] == row["w5_end_time"]
        assert all(t <= row["signal_time"] for t, _ in overlay["pts"])

    fig = charts.signal_chart(price, row, overlay, horizon_bars=30, bars_before=150,
                              groups=list(charts.LEVEL_GROUPS), height=600)
    assert fig.data[0].type == "candlestick" and fig.layout.xaxis.type == "category"
    assert charts.outcome_breakdown(res).data and charts.mfe_mae_distribution(res).data
    assert charts.side_breakdown(res).data
