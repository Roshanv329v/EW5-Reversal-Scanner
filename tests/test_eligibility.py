"""F&O 5-day grades (core/eligibility.py), missed scans and the Mac notification."""

from datetime import datetime

import pandas as pd

from core import alert_events as ev, alert_settings as aset, eligibility as el, strategies
from core.config import load_config

CFG = load_config()["fno_5day"]


def _rows(**cols) -> pd.DataFrame:
    base = {"Ticker": "A.NS", "degree": "major", "alignment": "MIXED", "fno_enabled": "true", "close": 100.0,
            "55_ema": 101.0, "TRIGGER": 100.0, "STOP": 101.5, "entry_price": float("nan"), "W4_END": 96.0,
            "W1_END": 104.0}
    n = max((len(v) for v in cols.values() if isinstance(v, list)), default=1)
    return pd.DataFrame({k: (cols.get(k, v) if isinstance(cols.get(k, v), list) else [cols.get(k, v)] * n)
                         for k, v in {**base, **cols}.items()})


def test_ew5_grades_follow_the_config_rules():
    r = el.assess(_rows(degree=["major", "major", "major", "intermediate", "major"],
                        STOP=[101.5, 102.5, 101.5, 101.5, 101.5],
                        alignment=["MIXED", "MIXED", "AGAINST", "ALIGNED", "MIXED"],
                        fno_enabled=["true", "true", "true", "true", "false"]), strategies.EW5, CFG)
    assert r["fno5"].tolist() == ["A", "B", "B", "–", "–"]
    assert r["fno5_reason"].iloc[3].startswith("degree intermediate") and r["fno5_reason"].iloc[4] == "not an F&O stock"
    assert r["fno5_stop_pct"].iloc[0] == 1.5 and r["fno5_rr"].iloc[0] == 2.67


def test_ew3_needs_a_big_enough_target_and_price_near_the_55_ema():
    r = el.assess(_rows(TRIGGER=100.0, STOP=[98.0, 98.0, 98.0, 98.0], W1_END=[104.5, 103.0, 104.5, 104.5],
                        close=[100.0, 100.0, 100.0, 100.0], **{"55_ema": [99.0, 99.0, 90.0, 99.0]},
                        alignment=["ALIGNED", "ALIGNED", "ALIGNED", "AGAINST"]), strategies.EW3, CFG)
    assert r["fno5"].tolist() == ["A", "–", "–", "–"]
    assert r["fno5_reason"].iloc[1].startswith("target 1.5× risk") and "55 EMA" in r["fno5_reason"].iloc[2]
    assert r["fno5_reason"].iloc[3] == "against the higher timeframes"


def test_a_triggered_trade_is_held_at_most_five_trading_days():
    assert el.exit_by(pd.Timestamp("2026-11-18 13:15")) == pd.Timestamp("2026-11-24")    # Wed -> next Tue
    assert el.exit_by(pd.Timestamp("2026-11-21")) == pd.Timestamp("2026-11-27")          # a Saturday rolls to Mon


def test_alert_events_carry_the_grade_and_can_keep_only_eligible_ones():
    S = strategies.EW5
    day = pd.Timestamp("2026-11-18")
    res = _rows(Ticker=["A.NS", "B.NS"], degree=["major", "minor"], time_frame="60m", zigzag_length=4,
                signal_time=day + pd.Timedelta(hours=9), status="TRIGGERED", trigger_time=day + pd.Timedelta(hours=11),
                entry_price=100.0, reversal_side="SHORT", **{"FIB_0.500": 94.0})
    attrs = pd.DataFrame({"fno_enabled": ["true", "true"]}, index=["A.NS", "B.NS"])
    rows = ev.event_rows(res, S, day.date(), ["TRIGGERED"], False, "f.csv", grade_cfg=CFG, attrs=attrs)
    assert {r["ticker"]: r["fno5"] for r in rows} == {"A.NS": "A", "B.NS": "–"}
    assert rows[0]["exit_by"] == "Tue 24 Nov"
    only = ev.event_rows(res, S, day.date(), ["TRIGGERED"], False, "f.csv", grade_cfg=CFG, attrs=attrs, fno5_only=True)
    assert [r["ticker"] for r in only] == ["A.NS"]
    text = ev.render("TRIGGERED", "t", ev.messages(rows, rows, True)[0][2], aset.DEFAULTS)[0]
    assert "⭐A" in text and "F&amp;O 5-day A: exit by the close of Tue 24 Nov" in text
    assert text.index("A</b>") < text.index("B</b>")                     # graded first within the timeframe


def test_a_scan_due_today_that_did_not_run_is_reported():
    s = {**aset.DEFAULTS, "enabled": True, "days": [1, 2, 3, 4, 5], "times": ["12:30", "15:45"], "full_enabled": False}
    now = datetime(2026, 11, 18, 16, 0)                                   # a Wednesday
    assert aset.missed(s, "2026-11-18T12:31:00", now) == {"at": "15:45", "kind": "regular"}
    assert aset.missed(s, "2026-11-18T15:45:30", now) is None
    assert aset.missed(s, None, datetime(2026, 11, 18, 9, 0)) is None    # nothing due yet
    assert aset.missed({**s, "enabled": False}, None, now) is None


def test_mac_notification_passes_emoji_as_arguments(monkeypatch):
    import subprocess
    import scheduled_scan as sc
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(sc.subprocess, "run", fake)
    assert sc.notify_mac('⚡ 2 triggered "today"', "🔴 RELIANCE")
    assert seen["cmd"][-2:] == ['⚡ 2 triggered "today"', "🔴 RELIANCE"]
    assert not any("⚡" in part for part in seen["cmd"][:-2])            # never inside the script text


def test_fno_stocks_both_ways_cash_stocks_long_only_and_full_scan_timeframes():
    s = aset.clean_settings({**aset.DEFAULTS, "timeframes": ["60m"], "full_timeframes": ["1D", "1W"]})
    assert aset.timeframes_for(s, "regular") == ["60m"] and aset.timeframes_for(s, "full") == ["1D", "1W"]
    assert aset.side_rules(s) == {"fno": ["LONG", "SHORT"], "cash": ["LONG"]}           # the defaults
    assert aset.with_defaults({"timeframes": ["4hr"]})["full_timeframes"] == ["4hr"]   # saved before 2.8
    assert aset.with_defaults({"sides": ["SHORT"]})["sides_fno"] == ["SHORT"]           # saved by 2.8
    import pytest
    with pytest.raises(ValueError, match="bullish, bearish"):
        aset.clean_settings({**aset.DEFAULTS, "sides_fno": [], "sides_cash": []})
    S = strategies.EW5
    day = pd.Timestamp("2026-11-18")
    res = _rows(Ticker=["F1.NS", "F2.NS", "C1.NS", "C2.NS", "^NSEI"], time_frame="60m", zigzag_length=4,
                signal_time=day + pd.Timedelta(hours=9), status="TRIGGERED", trigger_time=day + pd.Timedelta(hours=11),
                entry_price=100.0, reversal_side=["LONG", "SHORT", "LONG", "SHORT", "SHORT"], **{"FIB_0.500": 94.0})
    attrs = pd.DataFrame({"fno_enabled": ["true", "true", "false", "false"]}, index=["F1.NS", "F2.NS", "C1.NS", "C2.NS"])
    rows = ev.event_rows(res, S, day.date(), ["TRIGGERED"], False, "f.csv", attrs=attrs, sides=aset.side_rules(s))
    assert sorted(r["ticker"] for r in rows) == ["C1.NS", "F1.NS", "F2.NS", "^NSEI"]  # cash SHORT C2 left out


def test_chart_palette_recolours_levels_once():
    from core import charts
    before = dict(charts.C)
    try:
        charts.use_palette("night")
        charts.use_palette("night")                                       # every Streamlit rerun calls it
        assert charts.C["surface"] == charts.NIGHT["surface"] and charts.THEME["template"] == "plotly_dark"
        fib = dict((n, c) for n, c, _ in charts.LEVEL_GROUPS["Fib zone"])
        assert fib["FIB_0.500"] == charts.NIGHT["ink2"]
    finally:
        charts.use_palette("dark")
    assert charts.C == before
