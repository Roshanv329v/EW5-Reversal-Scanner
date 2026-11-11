from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from core import data_store as ds
from tests.conftest import FakeFetch

TODAY = datetime(2026, 3, 13, 18, 0)
TICKERS = ["AAA.NS", "BBB.NS"]


def _bars(times, close, ticker="AAA.NS", tf="1D") -> pd.DataFrame:
    return pd.DataFrame({"Ticker": ticker, "time": pd.to_datetime(times), "time_frame": tf,
                         "Open": close, "High": close, "Low": close, "Close": close,
                         "Volume": 1.0})[ds.BASE_SCHEMA]


# ---------------------------------------------------------------- merge / dedupe
def test_merge_replaces_overlap_and_has_no_duplicates():
    old = _bars(["2026-01-01", "2026-01-02", "2026-01-05"], [10.0, 11.0, 12.0])
    new = _bars(["2026-01-05", "2026-01-06"], [99.0, 13.0])
    merged, stats = ds.merge_bars(old, new)

    assert not merged.duplicated(ds.KEYS).any()
    assert len(merged) == 4
    assert merged.loc[merged["time"] == "2026-01-05", "Close"].item() == 99.0   # newest wins
    row = stats.iloc[0]
    assert (row["downloaded"], row["added"], row["replaced"]) == (2, 1, 1)
    assert merged["time"].is_monotonic_increasing


def test_merge_keeps_timeframes_apart():
    daily = _bars(["2026-01-05"], [10.0], tf="1D")
    four_h = _bars(["2026-01-05"], [20.0], tf="4hr")
    merged, _ = ds.merge_bars(daily, four_h)
    assert len(merged) == 2


def test_update_twice_gives_identical_file(cfg):
    fetch = FakeFetch()
    first = ds.update_data(cfg, TICKERS, ["1D", "4hr"], 30, fetch=fetch, today=TODAY)
    before = cfg["stock_csv"].read_bytes()
    second = ds.update_data(cfg, TICKERS, ["1D", "4hr"], 30, fetch=fetch, today=TODAY)

    assert cfg["stock_csv"].read_bytes() == before
    assert first.rows_after == second.rows_after
    assert second.stats["added"].sum() == 0 and second.stats["replaced"].sum() > 0
    stored = ds.load_stock_csv(cfg["stock_csv"])
    assert not stored.duplicated(ds.KEYS).any()


def test_second_update_is_incremental_and_replaces_revised_bars(cfg):
    fetch = FakeFetch()
    ds.update_data(cfg, TICKERS, ["1D"], 30, fetch=fetch, today=TODAY)
    assert fetch.calls[-1][2] == cfg["full_history"]["1D"]          # first run: full history
    old = ds.load_stock_csv(cfg["stock_csv"])

    fetch.bump = 5.0                                                # the source revised its bars
    ds.update_data(cfg, TICKERS, ["1D"], 30, fetch=fetch, today=TODAY)
    _, _, period, start = fetch.calls[-1]
    assert period is None and start == "2026-02-11"                 # only the last 30 days

    new = ds.load_stock_csv(cfg["stock_csv"])
    assert len(new) == len(old)
    recent = new["time"] >= "2026-02-11"
    np.testing.assert_allclose(new.loc[recent, "Close"], old.loc[recent, "Close"] + 5.0)
    np.testing.assert_allclose(new.loc[~recent, "Close"], old.loc[~recent, "Close"])


def test_new_ticker_gets_full_history_and_failures_are_collected(cfg):
    fetch = FakeFetch(fail=("BAD.NS",))
    ds.update_data(cfg, ["AAA.NS"], ["1D"], 30, fetch=fetch, today=TODAY)
    report = ds.update_data(cfg, ["AAA.NS", "BBB.NS", "BAD.NS"], ["1D"], 30, fetch=fetch, today=TODAY)

    kinds = {call[0]: call[2] for call in fetch.calls[1:]}
    assert kinds[("AAA.NS",)] is None                               # incremental
    assert report.failed == {"1D": ["BAD.NS"]}
    stored = ds.load_stock_csv(cfg["stock_csv"])
    assert stored.groupby("Ticker").size().to_dict() == {"AAA.NS": 60, "BBB.NS": 60}


def test_backups_are_kept_and_pruned(cfg):
    df = _bars(["2026-01-01"], [10.0])
    for i in range(8):
        ds.save_stock_csv(df, cfg["stock_csv"], cfg["backups_dir"], keep=5, stamp=f"2026010{i}_000000")
    backups = sorted(p.name for p in cfg["backups_dir"].glob("stock_*.csv"))
    assert len(backups) == 5 and backups[-1] == "stock_20260107_000000.csv"
    assert not cfg["stock_csv"].with_name("stock.csv.tmp").exists()


# ---------------------------------------------------------------- timezone
def test_utc_and_ist_inputs_become_identical_naive_ist(cfg):
    ist = pd.date_range("2026-01-05 09:15", periods=7, freq="1h", tz="Asia/Kolkata")
    values = np.arange(7, dtype=float) + 100
    raw_ist = pd.DataFrame({c: values for c in ds.OHLC}, index=ist)
    raw_utc = raw_ist.copy()
    raw_utc.index = ist.tz_convert("UTC")

    idx_a, idx_b = ds.to_naive_ist(raw_ist.index, "Asia/Kolkata"), ds.to_naive_ist(raw_utc.index, "Asia/Kolkata")
    assert idx_a.tz is None and idx_a.equals(idx_b)
    assert idx_a[0].strftime(ds.TIME_FMT) == "2026-01-05 09:15:00"

    raw_ist, raw_utc = raw_ist.assign(Volume=1.0), raw_utc.assign(Volume=1.0)
    a = ds.to_schema(raw_ist, "AAA.NS", "4hr", cfg)
    b = ds.to_schema(raw_utc, "AAA.NS", "4hr", cfg)
    pd.testing.assert_frame_equal(a, b)
    merged, _ = ds.merge_bars(a, b)
    assert len(merged) == len(a)                                    # dedupe matches


def test_daily_bars_are_stored_at_midnight(cfg, tmp_path):
    aware = pd.DatetimeIndex(["2026-01-04 18:30", "2026-01-05 18:30"], tz="UTC")   # IST midnight
    raw = pd.DataFrame({c: [1.0, 2.0] for c in ds.OHLC}, index=aware)
    out = ds.to_schema(raw, "AAA.NS", "1D", cfg)
    ds.save_stock_csv(out, cfg["stock_csv"], cfg["backups_dir"], keep=5)
    text = cfg["stock_csv"].read_text().splitlines()
    assert text[1].startswith("AAA.NS,2026-01-05 00:00:00,1D")
    assert text[2].startswith("AAA.NS,2026-01-06 00:00:00,1D")


# ---------------------------------------------------------------- 60m -> 4hr
def _hourly(days, hours=7) -> pd.DataFrame:
    stamps = [pd.Timestamp(f"{day} 09:15") + pd.Timedelta(hours=h) for day in days for h in range(hours)]
    o = np.arange(len(stamps), dtype=float) + 100
    return pd.DataFrame({"Open": o, "High": o + 2, "Low": o - 3, "Close": o + 1, "Volume": 10.0},
                        index=pd.DatetimeIndex(stamps))


def test_4h_two_bars_per_day_with_correct_ohlc():
    out = ds.bars_4h(_hourly(("2026-01-05", "2026-01-06")))                  # 09:15 … 15:15

    assert [t.strftime("%Y-%m-%d %H:%M") for t in out.index] == [
        "2026-01-05 09:15", "2026-01-05 13:15", "2026-01-06 09:15", "2026-01-06 13:15"]
    first, second = out.iloc[0], out.iloc[1]
    # first bar = 60m bars 0..3 (09:15, 10:15, 11:15, 12:15)
    assert (first["Open"], first["High"], first["Low"], first["Close"]) == (100, 105, 97, 104)
    # second bar = 60m bars 4..6 (13:15, 14:15, 15:15)
    assert (second["Open"], second["High"], second["Low"], second["Close"]) == (104, 108, 101, 107)
    assert (first["Volume"], second["Volume"]) == (40, 30)


def test_4h_has_no_empty_bar_for_a_half_day():
    out = ds.bars_4h(_hourly(("2026-01-05",), hours=2))                      # morning only
    assert len(out) == 1 and out.index[0] == pd.Timestamp("2026-01-05 09:15")


# ---------------------------------------------------------------- indicators
def test_indicators_use_full_history_after_incremental_update(cfg):
    fetch = FakeFetch(days=120)
    ds.update_data(cfg, TICKERS, ["1D", "4hr"], 30, fetch=fetch, today=TODAY)
    ds.update_data(cfg, TICKERS, ["1D", "4hr"], 30, fetch=fetch, today=TODAY)   # incremental
    stored = ds.load_stock_csv(cfg["stock_csv"])
    assert list(stored.columns) == ds.SCHEMA

    one = stored[(stored["Ticker"] == "AAA.NS") & (stored["time_frame"] == "1D")].reset_index(drop=True)
    assert one["55_ema"].notna().sum() == len(one) - 54            # not just the last 30 days
    expected = one["Close"].ewm(span=13, adjust=False).mean().iloc[-1]
    assert abs(one["13_ema"].iloc[-1] - expected) / expected < 0.001
    assert one["rsi"].dropna().between(0, 100).all()


# ---------------------------------------------------------------- tickers
def test_tickers_are_not_renamed():
    assert ds.parse_ticker_text("ABB.NS, ^NSEI\n GC=F ABB.NS") == ["ABB.NS", "^NSEI", "GC=F"]


def test_final_list_is_stocks_plus_indices_plus_commodities():
    import stock_data
    final = stock_data.build_final_list(["ABB.NS", "^NSEI"])
    assert final[0] == "ABB.NS" and final.count("^NSEI") == 1
    assert set(stock_data.indian_index) <= set(final) and set(stock_data.commodity) <= set(final)


# ---------------------------------------------------------------- 60m timeframe
def test_60m_is_stored_and_shares_one_download_with_4hr(cfg):
    fetch = FakeFetch(days=20)
    report = ds.update_data(cfg, ["AAA.NS"], ["1D", "4hr", "60m"], 30, fetch=fetch, today=TODAY)
    assert [call[1] for call in fetch.calls] == ["1d", "60m"]            # one intraday download
    assert not report.failed

    stored = ds.load_stock_csv(cfg["stock_csv"])
    counts = stored.groupby("time_frame").size().to_dict()
    assert counts == {"1D": 20, "4hr": 40, "60m": 140}                   # 7 hourly bars per day
    hourly = stored[stored["time_frame"] == "60m"]
    assert sorted(hourly["time"].dt.strftime("%H:%M").unique()) == [
        "09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    # each 4hr bar is exactly the aggregate of its 60m bars
    day = hourly[hourly["time"].dt.date == hourly["time"].dt.date.iloc[0]]
    first_4h = stored[(stored["time_frame"] == "4hr")].iloc[0]
    assert first_4h["Open"] == day["Open"].iloc[0] and first_4h["High"] == day["High"].iloc[:4].max()
    assert first_4h["Close"] == day["Close"].iloc[3]
    assert stored.loc[stored["time_frame"] == "60m", "13_ema"].notna().any()   # indicators too


def test_adding_60m_later_downloads_full_intraday_history_once(cfg):
    fetch = FakeFetch(days=60)
    ds.update_data(cfg, ["AAA.NS"], ["1D", "4hr"], 30, fetch=fetch, today=TODAY)
    ds.update_data(cfg, ["AAA.NS"], ["1D", "4hr", "60m"], 30, fetch=fetch, today=TODAY)
    interval, start = fetch.calls[-1][1], fetch.calls[-1][3]
    assert interval == "60m" and start < "2026-02-11"                    # not just the last 30 days
    first = ds.load_stock_csv(cfg["stock_csv"])
    ds.update_data(cfg, ["AAA.NS"], ["1D", "4hr", "60m"], 30, fetch=fetch, today=TODAY)
    assert fetch.calls[-1][3] == "2026-02-11"                            # now incremental
    pd.testing.assert_frame_equal(first, ds.load_stock_csv(cfg["stock_csv"]))
    assert not first.duplicated(ds.KEYS).any()
