"""
Scheduled scans on this Mac (the desktop twin of the phone app's Alerts).

    python scheduled_scan.py --kind regular     data update + EW5 / EW3 for the usual stocks (F&O)
    python scheduled_scan.py --kind full        the same for every stock in tickers.csv
    python scheduled_scan.py --install          schedule both with macOS launchd (from the Alerts tab)
    python scheduled_scan.py --uninstall        remove the schedule
    python scheduled_scan.py --status

Settings are data/alert_settings.json (Alerts tab; same keys as the phone). One run:
download the latest data, run a short walk-forward backtest so each setup carries its
outcome, find today's TRIGGERED / NEW signals, save the results as backtest_auto_* files,
then send one macOS notification (and Telegram if switched on) for what was not sent yet.
launchd runs a scan that was missed while the Mac slept as soon as it wakes.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import plistlib
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core import alert_events as ev, alert_settings as aset, data_store as ds, runner, strategies, universe
from core.config import ROOT, load_config

LABELS = {"regular": "com.ewscanner.scan.regular", "full": "com.ewscanner.scan.full"}
AGENTS = Path.home() / "Library" / "LaunchAgents"
KEEP_AUTO_FILES = 4
HISTORY_DAYS = 14
log = logging.getLogger("ew_app.scheduled")


# ----------------------------------------------------------------------------------
# Files (data/alert_settings.json, alerts_sent.json, alerts_history.json, alerts_last_run.json)
# ----------------------------------------------------------------------------------
def _dir(cfg: dict) -> Path:
    return Path(cfg["tickers_file"]).parent


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_settings(cfg: dict) -> dict:
    saved = _read(_dir(cfg) / "alert_settings.json", {})
    return aset.with_defaults(saved)


def save_settings(cfg: dict, values: dict) -> dict:
    settings = aset.clean_settings(values, load_settings(cfg))
    _write(_dir(cfg) / "alert_settings.json", settings)
    if installed():                       # keep the Mac's schedule in step with the settings
        install(cfg)
    return settings


# ----------------------------------------------------------------------------------
# One scan
# ----------------------------------------------------------------------------------
def notify_mac(title: str, text: str) -> bool:
    # title and text go in as arguments, never into the script text: emoji and quotes stay safe
    script = ["-e", "on run argv", "-e",
              'display notification (item 2 of argv) with title (item 1 of argv) sound name "default"',
              "-e", "end run"]
    try:
        return subprocess.run(["osascript", *script, title, text], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _prune(results_dir: Path) -> None:
    for prefix in ("backtest_auto_", "ew3_backtest_auto_"):
        files = sorted(results_dir.glob(f"{prefix}*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[KEEP_AUTO_FILES:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)


def run(kind: str = "regular", source: str = "schedule", today: Optional[date] = None, notify: bool = True,
        cfg: Optional[dict] = None) -> dict:
    """One scan; returns the summary also written to data/alerts_last_run.json."""
    cfg = cfg or load_config()
    settings = load_settings(cfg)
    today = today or date.today()
    scope = "all" if kind == "full" else settings.get("universe", "fno")
    t0 = time.time()
    summary: dict[str, Any] = {"source": source, "kind": kind, "universe": scope, "date": str(today),
                               "started": datetime.now().isoformat(timespec="seconds"), "runs": {}}
    lock_path = _dir(cfg) / ".scan.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)          # one scan at a time
        except OSError:
            summary["skipped"] = "another scan is running"
            _write(_dir(cfg) / "alerts_last_run.json", summary)
            return summary
        tickers = universe.final_list(cfg["tickers_file"], scope)
        if settings["update_data"]:
            log.info("data update: %d tickers (%s)", len(tickers), scope)
            report = ds.update_data(cfg, tickers, cfg["timeframes"], int(cfg["incremental_days"]))
            summary["update"] = {"rows_after": report.rows_after,
                                 "failed": sum(len(v) for v in report.failed.values())}
        df = ds.load_stock_csv(cfg["stock_csv"])
        df = df[df["Ticker"].isin(set(tickers))]
        engine, ew3_cfg = cfg["engine"], cfg["ew3"]
        start = today - timedelta(days=int(settings["lookback_days"]))
        events: list[dict] = []
        for key in settings["strategies"]:
            S = strategies.get(key)
            p = runner.RunParams(
                mode="backtest", timeframes=tuple(aset.timeframes_for(settings, kind)), lengths=tuple(engine["lengths"]),
                stages=tuple(ew3_cfg["stages"] if key == "ew3" else engine["stages"]),
                horizon_bars=int(engine["horizon_bars"]), min_bars=int(cfg["min_bars"]),
                pivot_tie=engine["pivot_tie"], hi_source=engine["hi_source"], lo_source=engine["lo_source"],
                min_w5_vs_w1=float(engine["min_w5_vs_w1"]), start=str(start), end=str(today), strategy=key,
                contexts=tuple(ew3_cfg["contexts"]), min_retrace=float(ew3_cfg["min_retrace"]),
                max_retrace=float(ew3_cfg["max_retrace"]), universe=scope)
            res = runner.run_engine(df, p, cfg["signal_indicators"], cfg["htf"])
            saved = runner.save_results(res, p, cfg["results_dir"], cfg["stock_csv"],
                                        stamp="auto_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            found = ev.event_rows(res, S, today, settings["events"], settings["aligned_only"], saved.name,
                                  grade_cfg=cfg["fno_5day"], attrs=universe.load_attributes(cfg["tickers_file"]),
                                  fno5_only=settings.get("fno5_only", False), sides=aset.side_rules(settings))
            summary["runs"][key] = {"file": saved.name, "setups": len(res), "today": len(found)}
            events += found
        _prune(cfg["results_dir"])

        sent_path, hist_path = _dir(cfg) / "alerts_sent.json", _dir(cfg) / "alerts_history.json"
        sent, history = _read(sent_path, {}), _read(hist_path, [])
        fresh = [e for e in events if e["key"] not in sent]
        stamp = datetime.now().isoformat(timespec="seconds")
        for e in fresh:
            sent[e["key"]] = str(today)
            history.append({**e, "day": str(today), "notified": stamp})
        cutoff = str(today - timedelta(days=HISTORY_DAYS))
        _write(sent_path, {k: d for k, d in sent.items() if d >= cutoff})
        history = [h for h in history if h.get("day", "") >= cutoff][-2000:]
        _write(hist_path, history)
        todays = sorted([h for h in history if h.get("day") == str(today)],
                        key=lambda h: (h["event"] != "TRIGGERED", h["at"]))
        n_trig = sum(h["event"] == "TRIGGERED" for h in todays)
        summary.update(events=len(todays), triggered=n_trig, new_setups=len(todays) - n_trig,
                       new_events=len(fresh), seconds=round(time.time() - t0, 1))
        if notify:
            # one notification (and Telegram message) per category, or one for the whole day
            for category, title, rows in ev.messages(todays, fresh, settings.get("split_messages", True)):
                shown = notify_mac(title, "\n".join(ev.notification_lines(rows)[:4]))
                summary["notified"] = summary.get("notified", True) and shown
                if settings.get("telegram"):
                    result = ev.send_telegram(settings, title, rows, category)
                    summary["telegram"] = result if summary.get("telegram", "sent") == "sent" else summary["telegram"]
        _write(_dir(cfg) / "alerts_last_run.json", summary)
        return summary


# ----------------------------------------------------------------------------------
# launchd schedule
# ----------------------------------------------------------------------------------
def calendar(settings: dict) -> dict[str, list[dict]]:
    """StartCalendarInterval entries per kind. A regular slot at the same minute as a full one is dropped."""
    def entries(days: list[int], times: list[str]) -> list[dict]:
        return [{"Weekday": d % 7, "Hour": int(t[:2]), "Minute": int(t[3:5])} for d in days for t in times]
    if not settings.get("enabled"):
        return {"regular": [], "full": []}
    full = entries(settings.get("full_days", []), settings.get("full_times", [])) if settings.get("full_enabled") else []
    regular = [e for e in entries(settings.get("days", []), settings.get("times", [])) if e not in full]
    return {"regular": regular, "full": full}


def _plist(kind: str) -> Path:
    return AGENTS / f"{LABELS[kind]}.plist"


def installed() -> bool:
    return any(_plist(k).exists() for k in LABELS)


def _launchctl(*args: str) -> int:
    return subprocess.run(["launchctl", *args], capture_output=True).returncode


def install(cfg: Optional[dict] = None) -> dict:
    """Write the two launch agents from the settings and load them (replacing older ones)."""
    cfg = cfg or load_config()
    cal = calendar(load_settings(cfg))
    uninstall()
    AGENTS.mkdir(parents=True, exist_ok=True)
    logs = Path(cfg["logs_dir"])
    logs.mkdir(parents=True, exist_ok=True)
    done = {}
    for kind, entries in cal.items():
        if not entries:
            continue
        plist = {
            "Label": LABELS[kind],
            "ProgramArguments": [sys.executable, str(ROOT / "scheduled_scan.py"), "--kind", kind],
            "WorkingDirectory": str(ROOT),
            "StartCalendarInterval": entries,
            "StandardOutPath": str(logs / "scheduled_scan.log"),
            "StandardErrorPath": str(logs / "scheduled_scan.log"),
            "ProcessType": "Background",
        }
        with open(_plist(kind), "wb") as fh:
            plistlib.dump(plist, fh)
        done[kind] = _launchctl("bootstrap", f"gui/{os.getuid()}", str(_plist(kind))) == 0
    return {"installed": done, "entries": cal}


def uninstall() -> None:
    for kind in LABELS:
        if _plist(kind).exists():
            _launchctl("bootout", f"gui/{os.getuid()}", str(_plist(kind)))
            _plist(kind).unlink(missing_ok=True)


def status() -> dict:
    return {kind: {"installed": _plist(kind).exists(),
                   "loaded": _launchctl("print", f"gui/{os.getuid()}/{LABELS[kind]}") == 0} for kind in LABELS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--kind", choices=["regular", "full"], default="regular")
    parser.add_argument("--source", default="schedule")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.install:
        print(json.dumps(install(), indent=2))
    elif args.uninstall:
        uninstall()
        print("removed")
    elif args.status:
        print(json.dumps(status(), indent=2))
    else:
        cfg = load_config()
        ds.setup_logging(cfg["logs_dir"])
        print(json.dumps(run(args.kind, source=args.source, cfg=cfg), indent=2, default=str))


if __name__ == "__main__":
    main()
