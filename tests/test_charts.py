from __future__ import annotations

import pandas as pd

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


def test_indicators_share_one_pane_and_histogram_shows_only_extremes():
    df = make_engine_df()
    n = len(df)
    df = df.assign(rsi=55.0, dtosck=80.0, dtoscd=60.0,
                   histogram=[(-30.0, 0.0, 30.0, 10.0)[i % 4] for i in range(n)])
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4,),
                         stages=(ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED), horizon_bars=30)
    row = runner.run_engine(df, p).iloc[0]
    price = df[df["Ticker"] == row["Ticker"]]
    kwargs = dict(horizon_bars=30, bars_before=150, groups=list(charts.LEVEL_GROUPS), height=600)

    plain = charts.signal_chart(price, row, None, **kwargs)
    fig = charts.signal_chart(price, row, None, panes=["rsi", "dtosc", "histogram"], pane_height=100, **kwargs)
    assert plain.layout.height == 600 and fig.layout.height == 700            # one extra pane only
    assert list(fig.layout.yaxis2.range) == [0, 100] and "yaxis3" not in fig.layout
    names = {t.name: t for t in fig.data}
    for name in ("RSI 14", "DTosc K", "DTosc D", "Histogram"):
        assert names[name].yaxis == "y2"                                      # all on the same layer
    hist = names["Histogram"]
    assert set(hist.y) == {-30.0, 30.0} and hist.base == 50                   # nothing inside +/-20
    assert all((c == charts.GOOD) == (v < 0) for c, v in zip(hist.marker.color, hist.y))
    assert set(hist.marker.color) == {charts.GOOD, charts.BAD}
    # no indicator data -> no pane
    assert charts.signal_chart(make_engine_df()[lambda d: d["Ticker"] == row["Ticker"]], row, None,
                               panes=["rsi"], **kwargs).layout.height == 600


def test_alignment_breakdown_bars_carry_their_alignment():
    stats = pd.DataFrame({"alignment": ["AGAINST", "ALIGNED"], "signals": [30, 10], "stop_rate": [60.0, 40.0],
                          "t1_hit_rate": [45.0, 55.0], "t2_hit_rate": [20.0, 35.0]})
    fig = charts.alignment_breakdown(stats, "T1", "T2")
    assert [t.name for t in fig.data] == ["Stop rate", "T1", "T2"]
    assert charts.picked_bars(fig, [{"curve_number": 1, "point_index": 0}]) == [["ALIGNED"]]   # ALIGNED first
    assert list(fig.data[0].y) == [40.0, 60.0]


def _hourly_and_daily(days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic 7-bar NSE sessions (09:15 ... 15:15) and the daily bars built from them."""
    import numpy as np
    dates = pd.bdate_range("2024-03-01", periods=days)
    times = [d + pd.Timedelta(hours=9 + h, minutes=15) for d in dates for h in range(7)]
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, len(times)))
    hourly = pd.DataFrame({"time": times, "Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close})
    daily = (hourly.assign(time=hourly["time"].dt.normalize()).groupby("time")
             .agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
             .reset_index())
    return hourly, daily


def test_on_timeframe_moves_times_and_keeps_prices():
    hourly, daily = _hourly_and_daily()
    day = daily.iloc[10]
    hi_bar = hourly[hourly["time"].dt.normalize() == day["time"]].sort_values("High").iloc[-1]
    row = pd.Series({"time_frame": "1D", "signal_time": day["time"], "trigger_time": day["time"],
                     "entry_price": day["Close"], "stop_time": pd.NaT, "STOP": 1.0, "W4_END": 99.0,
                     "hit_W4_END_time": pd.NaT})
    overlay = {"dir": 1, "pts": [(daily["time"].iloc[2], 1.0), (day["time"], float(day["High"]))], "abc": []}

    same = charts.on_timeframe(row, overlay, daily, daily, "1D", 30)
    assert same[0] is row and same[1] is overlay and same[2] == 30

    r, o, horizon = charts.on_timeframe(row, overlay, daily, hourly, "60m", 5, ("W4_END",))
    assert r["time_frame"] == "60m" and r["W4_END"] == 99.0                      # levels untouched
    assert r["signal_time"] == day["time"] + pd.Timedelta(hours=15, minutes=15)   # known at the day's close
    assert o["pts"][1] == (hi_bar["time"], float(day["High"]))                   # pivot on the bar with that high
    assert horizon == 5 * 7                                                      # same span: 5 days of hours

    friday_close = hourly[hourly["time"].dt.day_of_week == 4].iloc[-1]             # 15:15, next bar is Monday
    row_fri = row.copy()
    row_fri["time_frame"], row_fri["signal_time"] = "60m", friday_close["time"]
    r, _, _ = charts.on_timeframe(row_fri, None, hourly, daily, "1D", 7)
    assert r["signal_time"] == friday_close["time"].normalize()                  # Friday's bar, not Monday's

    hour = hourly.iloc[7 * 10 + 3]                                               # 12:15 bar of the same day
    row60 = row.copy()
    row60["time_frame"], row60["signal_time"] = "60m", hour["time"]
    r, _, horizon = charts.on_timeframe(row60, None, hourly, daily, "1D", 7)
    assert r["signal_time"] == day["time"] and horizon == 1                      # the daily bar that contains it
