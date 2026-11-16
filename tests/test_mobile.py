"""
The phone app (android/app/src/main/python/mobile) must give the desktop's answers.

Synthetic data only lives here (tests/conftest.py).
"""

from __future__ import annotations

import json

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


def test_alert_schedule_and_settings():
    from datetime import datetime
    from mobile import alerts
    s = {**alerts.DEFAULTS}
    assert alerts.next_runs(s, datetime(2026, 11, 13, 16, 0)) == [          # Friday after the last F&O scan
        "Fri 13 Nov 18:00 (All stocks)", "Mon 16 Nov 12:30 (F&O stocks)", "Mon 16 Nov 15:45 (F&O stocks)"]
    kinds = [kind for _, kind in alerts.slots({**s, "full_times": ["15:45"]}, datetime(2026, 11, 13, 9, 0))[:2]]
    assert kinds == ["regular", "full"]                     # same minute as a regular scan: the full one wins
    assert alerts.next_runs({**s, "full_enabled": False}, datetime(2026, 11, 13, 16, 0))[0] == "Mon 16 Nov 12:30 (F&O stocks)"
    assert alerts.next_runs({**s, "enabled": False}) == []
    clean = alerts.clean_settings({**s, "times": ["9:5", "15:45", "25:00", "15:45"], "days": [5, 1, 9]})
    assert clean["times"] == ["09:05", "15:45"] and clean["days"] == [1, 5]
    with pytest.raises(ValueError):
        alerts.clean_settings({**s, "times": [], "full_enabled": False})          # no scan at all
    assert alerts.clean_settings({**s, "times": []})["full_times"] == ["18:00"]     # only the weekly full scan


def test_alerts_find_todays_events_and_notify_each_once(tmp_path, df):
    import time as _time
    from mobile import alerts
    api.init(str(tmp_path / "phone"))
    a = api._app()
    src = tmp_path / "stock.csv"
    ds.save_stock_csv(df, src, tmp_path / "b", 1)
    a.store.import_csv(src)
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES, horizon_bars=30)
    res = runner.run_engine(df, p, CFG["signal_indicators"], CFG["htf"])
    day = pd.Timestamp(res.loc[res["status"].eq("TRIGGERED"), "trigger_time"].max()).date()   # a day with a trigger
    alerts.save_settings(a, {**alerts.DEFAULTS, "update_data": False, "strategies": ["ew5"], "timeframes": ["1D"]})
    pd.DataFrame({"Ticker": TICKERS[:6], "marketcapname": "Large Cap",               # the fixture's stocks are F&O
                  "fno_enabled": "true"}).to_csv(a.cfg["tickers_file"], index=False)

    def scan_once() -> dict:
        alerts.run(a, "manual", today=day, notify=False)
        while jobs.current()["running"]:
            _time.sleep(0.05)
        assert jobs.current()["error"] is None, jobs.current()["log"]
        return jobs.current()["result"]

    first = scan_once()
    expected_trig = int((res["status"].eq("TRIGGERED") & (pd.to_datetime(res["trigger_time"]).dt.date == day)).sum())
    expected_new = int((pd.to_datetime(res["signal_time"]).dt.date == day).sum())
    assert first["triggered"] == expected_trig > 0 and first["new_setups"] == expected_new
    assert first["new_events"] == expected_trig + expected_new
    assert scan_once()["new_events"] == 0                                 # second scan: nothing new to notify
    files = runner.list_results(a.cfg["results_dir"], "ew5")
    assert files and all("auto" in f.name for f in files)


def test_telegram_is_off_by_default_and_keeps_the_token_private(tmp_path, monkeypatch):
    from mobile import alerts
    assert alerts.DEFAULTS["telegram"] is False
    with pytest.raises(ValueError):
        alerts.clean_settings({**alerts.DEFAULTS, "telegram": True})                     # no token / chat
    api.init(str(tmp_path / "phone"))
    a = api._app()
    saved = alerts.save_settings(a, {**alerts.DEFAULTS, "telegram": True, "telegram_token": "123:SECRET",
                                     "telegram_chat_id": "42"})
    assert "telegram_token" not in saved["settings"] and saved["settings"]["telegram_token_set"]
    assert "SECRET" not in json.dumps(api.alerts_overview())
    again = alerts.save_settings(a, {**api.alerts_overview()["settings"], "telegram_token": ""})   # page sends no token
    assert again["settings"]["telegram_token_set"] and alerts.load_settings(a)["telegram_token"] == "123:SECRET"

    sent = []
    from core import alert_events
    fake = lambda token, method, payload: sent.append((token, method, payload)) or {"ok": True}      # noqa: E731
    monkeypatch.setattr(alert_events, "_telegram", fake)
    monkeypatch.setattr(alerts, "_telegram", fake)
    assert alerts.telegram_test(a, {})["ok"]
    assert len(sent) == 2                                             # separate messages by default
    token, method, payload = sent[0]
    assert (token, method, payload["chat_id"], payload["parse_mode"]) == ("123:SECRET", "sendMessage", "42", "HTML")
    assert "<b>SHORT  RELIANCE</b>" in payload["text"] and "<b>TRIGGERED</b>" in payload["text"]
    assert "TCS" not in payload["text"] and "<b>LONG  TCS</b>" in sent[1][2]["text"]
    sent.clear()
    assert alerts.telegram_test(a, {"split_messages": False})["ok"]
    assert len(sent) == 1 and "RELIANCE" in sent[0][2]["text"] and "TCS" in sent[0][2]["text"]

    monkeypatch.setattr(alert_events, "_telegram", lambda *a: {"ok": False, "description": "Unauthorized"})
    with pytest.raises(ValueError, match="Unauthorized"):
        alerts.telegram_test(a, {})


def test_triggered_and_new_setups_go_in_separate_messages():
    from core import alert_events as ev, alert_settings as aset
    assert aset.DEFAULTS["split_messages"] is True
    assert aset.clean_settings({**aset.DEFAULTS, "split_messages": False})["split_messages"] is False
    trig, new = ev.SAMPLE
    later = dict(new, ticker="INFY.NS", key="infy")
    day = [new, trig, later]
    out = ev.messages(day, [trig, new, later], split=True)
    assert [(k, [e["ticker"] for e in rows]) for k, _, rows in out] == [
        ("TRIGGERED", ["RELIANCE.NS"]), ("NEW", ["INFY.NS", "TCS.NS"])]
    assert out[0][1] == "⚡ 1 triggered today: RELIANCE"
    assert out[1][1] == "👀 2 new setups today: INFY, TCS"
    # a later scan with only a new setup: only the New setups message, listing the whole day
    again = ev.messages(day, [later], split=True)
    assert [(k, len(rows)) for k, _, rows in again] == [("NEW", 2)]
    one = ev.messages(day, [later], split=False)
    assert [(k, [e["ticker"] for e in rows]) for k, _, rows in one] == [("ALL", ["INFY.NS", "RELIANCE.NS", "TCS.NS"])]
    assert one[0][1] == "EW alerts: ⚡ 1 triggered · 👀 2 new setups"
    assert ev.messages(day, [], split=True) == []


def test_alert_messages_are_sorted_and_readable():
    from core import alert_events as ev, alert_settings as aset
    trig, new = ev.SAMPLE
    rows = [dict(trig, ticker="SBIN.NS", tf="1D", alignment="AGAINST", key="sbin", notified="2026-01-02T12:31:00"),
            dict(trig, ticker="INFY.NS", tf="4hr", alignment="MIXED", key="infy"),
            dict(trig, ticker="WIPRO.NS", tf="60m", alignment="AGAINST", key="wipro"),
            dict(trig, key="rel")]                                                   # RELIANCE 60m ALIGNED
    fresh = [r for r in rows if r["key"] != "sbin"]
    (kind, title, out), = ev.messages(rows, fresh, split=True)
    # new first; then 60m → 4hr → 1D; aligned before against
    assert [ev._symbol(e) for e in out] == ["RELIANCE", "WIPRO", "INFY", "SBIN"]
    assert title == "⚡ 4 triggered today: RELIANCE, WIPRO, INFY +1"
    lines = ev.notification_lines(out)
    assert lines[0] == "🆕 🔴 RELIANCE SHORT 60m EW5 · SL 1,312 ✅" and not lines[-1].startswith("🆕")
    text = ev.render(kind, title, out, aset.DEFAULTS)[0]
    assert text.index("New since 12:31") < text.index("RELIANCE") < text.index("WIPRO") < text.index("INFY")
    assert text.index("Earlier today") < text.index("SBIN")
    assert "Entry 1,297 · SL 1,312 (1.1%)" in text and "🎯 1,270.4 → 1,255" in text and "✅ aligned" in text
    compact = ev.render(kind, title, out, {**aset.DEFAULTS, "telegram_style": "compact"})[0]
    assert "🔴 <b>SHORT RELIANCE</b> · 60m EW5 · Entry 1,297 · SL 1,312 (1.1%) ✅" in compact
    (_, _, setups), = ev.messages([new], [new], split=True)
    assert "Buy above 3,425 (0.4% away) · SL 3,380" in ev.render("NEW", "t", setups, aset.DEFAULTS)[0]
    # all new: no 🆕 marks and no "Earlier today"
    (_, _, only_new), = ev.messages(fresh, fresh, split=True)
    assert not any(line.startswith("🆕") for line in ev.notification_lines(only_new))
    assert "Earlier today" not in ev.render("TRIGGERED", "t", only_new, aset.DEFAULTS)[0]
    # settings saved before the layouts: an edited template stays in use as Custom
    assert aset.with_defaults({})["telegram_style"] == "cards"
    assert aset.with_defaults({"telegram_line": "{ticker}"})["telegram_style"] == "custom"
    assert ev.price(1298.5) == "1,298.5" and ev.price(1312.0) == "1,312" and ev.price(45.2) == "45.20"


def test_every_alert_stock_gets_a_tradingview_link_at_its_timeframe():
    from core import alert_events as ev, alert_settings as aset
    layout = ev._tv().get("layout")
    base = f"https://www.tradingview.com/chart/{layout + '/' if layout else ''}"
    assert ev.tradingview_url("YESBANK.NS", "4hr") == base + "?symbol=NSE%3AYESBANK&interval=240"
    assert ev.tradingview_url("M&M.NS", "60m") == base + "?symbol=NSE%3AM_M&interval=60"
    assert ev.tradingview_url("BAJAJ-AUTO.NS", "1D") == base + "?symbol=NSE%3ABAJAJ_AUTO&interval=1D"
    assert ev.tradingview_url("^NSEI", "60m") == base + "?symbol=NSE%3ANIFTY&interval=60"
    trig = ev.SAMPLE[0]
    rows = [dict(trig, ticker=f"S{i}.NS", tf=tf, key=str(i), **({"notified": "2026-01-02T12:31:00"} if i % 2 else {}))
            for i, tf in enumerate(["60m", "4hr", "1D", "60m", "4hr", "1D"])]
    (kind, title, out), = ev.messages(rows, rows[::2], split=True)
    for style in ("cards", "compact"):
        text = "\n".join(ev.render(kind, title, out, {**aset.DEFAULTS, "telegram_style": style}))
        assert text.count("<a href=") == len(rows)                     # new and earlier stocks alike
        assert "📈 4hr chart</a>" in text and "interval=240" in text
    many = [dict(trig, ticker=f"T{i}.NS", key=str(i), notified="2026-01-02T12:31:00") for i in range(150)]
    parts = ev.render("TRIGGERED", "t", ev.messages(many + [dict(trig, key="x")], [dict(trig, key="x")], True)[0][2],
                      aset.DEFAULTS)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)       # long "Earlier today" lists are split too


def test_telegram_messages_are_split_under_the_limit():
    from mobile import alerts
    many = [{"event": "NEW", "strategy": "ew3", "ticker": f"T{i}.NS", "tf": "60m", "degree": "minor", "side": "LONG",
             "at": "2026-01-01 10:15", "alignment": "MIXED", "trigger": 1.0, "stop": 0.9} for i in range(200)]
    parts = alerts.telegram_text("EW alerts <today>", many)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)
    assert "&lt;today&gt;" in parts[0] and sum(p.count("🟢") for p in parts) == 200


def test_telegram_message_follows_the_template():
    from mobile import alerts
    custom = {"telegram_header": "{date}: {count} stocks ({triggered} triggered)",
              "telegram_line": "{icon} {symbol} {side} @ {trigger} SL {stop} T1 {target1} ({risk_pct}) {nope}",
              "telegram_group": False}
    text = alerts.telegram_text("ignored", alerts.SAMPLE, custom)[0]
    assert text.splitlines()[0] == "2026-01-02: 2 stocks (1 triggered)"
    assert "🔴 RELIANCE SHORT @ 1,298.50 SL 1,312.00 T1 1,270.40 (1.04%) {nope}" in text   # unknown names stay as written
    assert "Triggered today" not in text
    evil = dict(alerts.SAMPLE[0], ticker="<script>.NS")
    assert "&lt;script&gt;" in alerts.telegram_text("t", [evil])[0]                        # values are escaped


def test_universes_and_attributes(tmp_path):
    from core import universe
    path = tmp_path / "tickers.csv"
    path.write_text("﻿Ticker,marketcapname,cnx_sector_name,fno_enabled,macro_info,sector_info\n"
                    "AAA.NS,Large Cap,CNX500,true,Energy,NIFTY 500\nBBB.NS,Small Cap,,false,Services,-\n", encoding="utf-8")
    assert universe.stocks(path, "all") == ["AAA.NS", "BBB.NS"] and universe.stocks(path, "fno") == ["AAA.NS"]
    assert universe.final_list(path, "fno")[0] == "AAA.NS" and "^NSEI" in universe.final_list(path, "fno")
    res = pd.DataFrame({"Ticker": ["AAA.NS", "BBB.NS", "^NSEI", "ZZZ.NS"]})
    out = universe.attach(res, universe.load_attributes(path))
    assert out["fno_enabled"].tolist() == ["Yes", "No", "Index", "-"]
    assert out["cnx_sector_name"].tolist() == ["CNX500", "-", "Index", "-"]
    assert universe.mask(out, {"marketcapname": ["Small Cap"]}).tolist() == [False, True, False, False]
    universe.write_stocks(path, ["BBB.NS", "NEW.NS"])                          # an edited list keeps the attributes
    kept = universe.load_attributes(path)
    assert list(kept.index) == ["BBB.NS", "NEW.NS"] and kept.loc["BBB.NS", "macro_info"] == "Services"
    assert kept.loc["NEW.NS", "marketcapname"] == "-"


def test_store_moves_old_16_part_data_to_the_new_layout(cfg, tmp_path, df):
    import zlib
    from mobile import store as store_mod
    old_dir = tmp_path / "phone" / "stock_parts"
    old_dir.mkdir(parents=True)
    for i, part in df.groupby(df["Ticker"].map(lambda t: zlib.crc32(t.encode()) % 16)):  # how 1.0-1.7 stored it
        ds.save_stock_csv(part, old_dir / f"stock_{int(i):02d}.csv", tmp_path / "b", 1)
    st = store_mod.Store(dict(cfg, stock_csv=tmp_path / "phone" / "stock.csv"))       # migrates on start
    assert (old_dir / "layout.json").exists()
    moved = pd.concat(st.frames()).sort_values(ds.KEYS).reset_index(drop=True)
    assert len(moved) == len(df) and set(moved["Ticker"]) == set(df["Ticker"])
    assert all(store_mod.part_of(t) == int(p.stem[-2:]) for p in st.part_paths() for t in ds.load_stock_csv(p)["Ticker"].unique())


def test_charts_drill_down_into_cards_breakdown_and_table(tmp_path, df):
    api.init(str(tmp_path / "phone"))
    a = api._app()
    src = tmp_path / "stock.csv"
    ds.save_stock_csv(df, src, tmp_path / "b", 1)
    a.store.import_csv(src)
    pd.DataFrame({"Ticker": TICKERS[:6], "marketcapname": ["Large Cap", "Mid Cap"] * 3,
                  "fno_enabled": "true"}).to_csv(a.cfg["tickers_file"], index=False)
    p = runner.RunParams(mode="backtest", timeframes=("1D",), lengths=(4, 8, 16), stages=STAGES, horizon_bars=30)
    res = runner.run_engine(df, p, CFG["signal_indicators"], CFG["htf"])
    runner.save_results(res, p, a.cfg["results_dir"])
    large = res[res["Ticker"].isin(TICKERS[0:6:2])]

    out = api.dashboard({"key": "ew5", "bars": {"attr": [["marketcapname", "Large Cap"]]}})
    assert out["counts"]["filtered"] == out["signals"] == len(large)                       # cards follow the chart
    assert out["cards"][0]["count"] == int(large["status"].eq("TRIGGERED").sum())
    assert out["counts"]["view"] == len(large) and out["notes"] == ["Market cap Large Cap"]
    mc = out["attr_figures"]["marketcapname"]["data"]
    assert {"Large Cap", "Mid Cap"} <= {y for t in mc for y in t["y"]}                       # first chart: all values

    trig = api.dashboard({"key": "ew5", "bars": {"attr": [["marketcapname", "Large Cap"]],
                                                  "outcome": [["1D", d, "TRIGGERED"] for d in large["degree"].unique()]}})
    assert trig["counts"]["view"] == int(large["status"].eq("TRIGGERED").sum())             # breakdown drills the table
    assert trig["signals"] == len(large)                                                    # cards are above it
