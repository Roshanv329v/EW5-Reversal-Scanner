"""
The phone app (android/app/src/main/python/mobile) must give the desktop's answers.

Synthetic data only lives here (tests/conftest.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

import elliott_wave5_screener as ew
from core import data_store as ds, htf, runner, strategies
from core.config import ROOT, load_config
from tests.conftest import FakeFetch, make_engine_df

sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))
pytest.importorskip("mobile")
from mobile import api, jobs, scan                          # noqa: E402
from mobile.store import N_PARTS, Store, part_of            # noqa: E402

CFG = load_config()
STAGES = (ew.STAGE_IN_PROGRESS, ew.STAGE_COMPLETED)
TICKERS = [f"T{i:02d}.NS" for i in range(12)]
TODAY = pd.Timestamp("2026-03-13 18:00").to_pydatetime()


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return ds.add_indicators(ds.with_weekly(make_engine_df(tickers=TICKERS[:6], n=420), CFG))


def test_group_by_group_scan_equals_one_scan(df):
    for strategy, stages in (("ew5", STAGES), ("ew3", ("WAVE2_COMPLETED",))):
        p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8), stages=stages,
                             horizon_bars=30, strategy=strategy)
        whole = runner.run_engine(df, p, CFG["signal_indicators"], CFG["htf"])
        groups = scan.run_chunked(df, p, CFG["signal_indicators"], CFG["htf"], chunk=2)
        key = ["Ticker", "time_frame", "zigzag_length", "signal_time"]
        assert len(whole) > 0
        def norm(x: pd.DataFrame) -> pd.DataFrame:    # pandas 3 writes a missing text as None or NaN after concat
            x = x.sort_values(key).reset_index(drop=True).astype(object)
            return x.where(x.notna(), None)
        pd.testing.assert_frame_equal(norm(whole), norm(groups))


def test_parts_hold_exactly_what_one_stock_csv_holds(cfg, tmp_path):
    """update_data per part (phone) == update_data on one file (desktop)."""
    fetch = FakeFetch(days=40)
    one = ds.update_data(cfg, TICKERS, ["1D", "4hr", "60m"], 30, fetch=fetch, today=TODAY)
    store = Store(dict(cfg, stock_csv=tmp_path / "phone" / "stock.csv"))
    parts = store.update(TICKERS, ["1D", "4hr", "60m"], 30, False, FakeFetch(days=40))
    assert one.rows_after == parts.rows_after and not parts.failed
    assert len(store.part_paths()) == len({part_of(t) for t in TICKERS}) <= N_PARTS
    desktop = ds.load_stock_csv(cfg["stock_csv"]).sort_values(ds.KEYS).reset_index(drop=True)
    phone = pd.concat(store.frames()).sort_values(ds.KEYS).reset_index(drop=True)
    pd.testing.assert_frame_equal(desktop, phone)
    pd.testing.assert_frame_equal(store.timeframe_summary(), ds.timeframe_summary(desktop))
    a = store.bars_per_ticker(10, skip=("1W",)).sort_values("Ticker").reset_index(drop=True)
    b = ds.bars_per_ticker(desktop, 10, skip=("1W",)).sort_values("Ticker").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False, check_names=False)


def test_import_splits_a_desktop_stock_csv(cfg, tmp_path, df):
    path = tmp_path / "stock.csv"
    ds.save_stock_csv(df, path, tmp_path / "b", 1)
    store = Store(dict(cfg, stock_csv=tmp_path / "phone" / "stock.csv"))
    assert store.import_csv(path) == len(df)
    back = pd.concat(store.frames()).sort_values(ds.KEYS).reset_index(drop=True)
    pd.testing.assert_frame_equal(back, ds.load_stock_csv(path).sort_values(ds.KEYS).reset_index(drop=True))


def test_api_dashboard_and_chart_match_the_desktop_numbers(tmp_path, df):
    root = tmp_path / "phone"
    api.init(str(root))
    a = api._app()
    src = tmp_path / "stock.csv"
    ds.save_stock_csv(df, src, tmp_path / "b", 1)
    a.store.import_csv(src)
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES, horizon_bars=30)
    res = runner.run_engine(df, p, CFG["signal_indicators"], CFG["htf"])
    runner.save_results(res, p, a.cfg["results_dir"])

    out = api.dashboard({"key": "ew5"})
    k = strategies.EW5.kpis(res)
    assert out["counts"]["total"] == len(res) == out["signals"]
    assert {c["name"]: c["value"] for c in out["cards"]}["stopped"] == f"{k['stop_rate']:.1f}%"
    assert set(out["figures"]) == {"outcome", "mfemae", "align"}
    assert out["table"]["columns"][:5] == ["Ticker", "time_frame", "degree", "reversal_side", "alignment"]

    narrowed = api.dashboard({"key": "ew5", "filters": {"alignment": [htf.AGAINST]}, "stat": "triggered"})
    expected = res[res["alignment"].eq(htf.AGAINST)]
    assert narrowed["counts"]["filtered"] == len(expected)
    assert narrowed["counts"]["view"] == int(expected["status"].eq("TRIGGERED").sum())

    chart = api.chart({"key": "ew5", "file": out["file"], "id": out["table"]["ids"][0],
                       "groups": out["level_groups"], "narrow": True})
    tv = chart["tv"]                                     # TradingView chart: everything from the desktop figure
    assert chart["levels"] and chart["facts"][0][0] == "Signal"
    assert tv["candles"] and tv["signal_time"] in {c["time"] for c in tv["candles"]}
    assert [c["time"] for c in tv["candles"]] == sorted({c["time"] for c in tv["candles"]})
    assert {line["name"] for line in tv["lines"]} >= {"EMA 13", "EMA 55", "RSI 14", "DTosc K", "DTosc D"}
    panes = {line["name"]: line["pane"] for line in tv["lines"]}
    assert panes["EMA 13"] == 0 and panes["RSI 14"] == tv["hist_pane"] == 1           # RSI + histogram
    assert panes["DTosc K"] == panes["DTosc D"] == 2 and tv["panes"] == 2             # DTosc K / D below
    assert tv["waves"] and [x["text"] for x in tv["waves"][0]["labels"]][:2] == ["0", "(1)"]
    assert "TRIG" in {lv["title"] for lv in tv["levels"]} and {b["price"] for b in tv["bands"]} == {30.0, 50.0, 70.0}

    assert chart["view_tf"] == chart["signal_tf"] == "1D" and "1W" not in chart["timeframes"]
    weekly_cfg = dict(a.cfg["chart"], timeframes=["1D", "1W"])
    a.cfg["chart"] = weekly_cfg                                    # the fixture only has 1D and 1W bars
    on_week = api.chart({"key": "ew5", "file": out["file"], "id": out["table"]["ids"][0],
                         "groups": out["level_groups"], "tf": "1W"})
    assert on_week["view_tf"] == "1W" and on_week["tf_note"] and not on_week["tv"]["intraday"]
    assert {lv["price"] for lv in on_week["tv"]["levels"]} == {lv["price"] for lv in tv["levels"]}

    saved = api.save_prefs("ew5", {**api.get_prefs("ew5")["default"], "alignment": ["ALIGNED"]})
    assert saved["ok"] and api.get_prefs("ew5")["prefs"]["alignment"] == ["ALIGNED"]


def test_one_job_at_a_time():
    import threading
    gate = threading.Event()
    jobs.start("run", "first", lambda job: gate.wait(5))
    with pytest.raises(RuntimeError):
        jobs.start("run", "second", lambda job: None)
    gate.set()


def test_yahoo_live_row_is_folded_into_its_bar():
    """Yahoo's separate live row (current time, zero volume) must not become a bar."""
    from mobile.fetch import merge_live_row
    idx = pd.DatetimeIndex(["2026-11-12 04:45", "2026-11-12 05:45", "2026-11-12 06:45", "2026-11-12 07:20:36"], tz="UTC")
    frame = pd.DataFrame({"Open": [10, 11, 12, 12.5], "High": [11, 12, 13, 13.6], "Low": [9, 10, 11, 12.4],
                          "Close": [11, 12, 12.5, 12.6], "Volume": [100, 100, 100, 0]}, index=idx)
    out = merge_live_row(frame, pd.Timedelta("60m"))
    assert list(out.index) == list(idx[:3])
    assert out.iloc[-1].to_dict() == {"Open": 12, "High": 13.6, "Low": 11, "Close": 12.6, "Volume": 100}
    assert merge_live_row(frame.iloc[:3], pd.Timedelta("60m")).equals(frame.iloc[:3])      # nothing to merge


def test_update_removes_live_rows_stored_by_older_versions(cfg, tmp_path):
    store = Store(dict(cfg, stock_csv=tmp_path / "phone" / "stock.csv"))
    store.update(TICKERS[:3], ["1D", "4hr", "60m"], 30, False, FakeFetch(days=40))
    part = store.part_paths()[0]
    df = ds.load_stock_csv(part)
    hour = df[df["time_frame"] == "60m"].iloc[-1].copy()
    hour["time"] = hour["time"] + pd.Timedelta(minutes=35, seconds=36)               # e.g. 13:50:36
    ds.save_stock_csv(pd.concat([df, hour.to_frame().T], ignore_index=True), part, tmp_path / "b", 1)
    assert store.drop_live_rows(int(part.stem[-2:])) == 1
    assert (ds.load_stock_csv(part)["time"].dt.second == 0).all()
