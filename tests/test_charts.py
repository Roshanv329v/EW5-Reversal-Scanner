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


def test_clicked_bars_map_back_to_the_rows_they_count():
    df = make_engine_df()
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16),
                         stages=(ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED), horizon_bars=30)
    res = runner.run_engine(df, p)

    fig = charts.outcome_breakdown(res)
    for curve, trace in enumerate(fig.data):
        for i, height in enumerate(trace.y):
            bars = charts.picked_bars(fig, [{"curve_number": curve, "point_index": i}])
            assert int(runner.bar_mask(res, "status", bars).sum()) == height

    hist = charts.mfe_mae_distribution(res)
    total = 0
    for curve, trace in enumerate(hist.data[:1]):                      # MFE panel
        for i, height in enumerate(trace.y):
            bars = charts.picked_bars(hist, [{"curve_number": curve, "point_index": i}])
            total += height
            assert int(runner.range_mask(res, bars).sum()) >= height   # shared bin edges count twice
    assert total == int(res["status"].eq("TRIGGERED").sum())
    assert charts.picked_bars(fig, [{"curve_number": 99, "point_index": 0}]) == []


def test_indicator_panes_sit_under_the_price_with_fixed_scales():
    df = make_engine_df()
    n = len(df)
    df = df.assign(rsi=55.0, dtosck=80.0, dtoscd=60.0, histogram=[(-30.0, 0.0, 30.0)[i % 3] for i in range(n)])
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4,),
                         stages=(ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED), horizon_bars=30)
    row = runner.run_engine(df, p).iloc[0]
    price = df[df["Ticker"] == row["Ticker"]]
    kwargs = dict(horizon_bars=30, bars_before=150, groups=list(charts.LEVEL_GROUPS), height=600)

    plain = charts.signal_chart(price, row, None, **kwargs)
    fig = charts.signal_chart(price, row, None, panes=["rsi", "dtosc", "histogram"], pane_height=100, **kwargs)
    assert plain.layout.height == 600 and fig.layout.height == 900
    assert list(fig.layout.yaxis2.range) == [0, 100] and list(fig.layout.yaxis3.range) == [0, 100]
    assert list(fig.layout.yaxis4.range) == [-50, 50]
    names = {t.name: t for t in fig.data}
    assert {"RSI 14", "DTosc K", "DTosc D", "Histogram"} <= set(names)
    assert names["RSI 14"].yaxis == "y2" and names["DTosc K"].yaxis == "y3" and names["Histogram"].yaxis == "y4"
    assert set(names["Histogram"].marker.color) == {charts.GOOD, charts.BAD, charts.C["muted"]}
    # panes without data are left out
    assert charts.signal_chart(make_engine_df()[lambda d: d["Ticker"] == row["Ticker"]], row, None,
                               panes=["rsi"], **kwargs).layout.height == 600
