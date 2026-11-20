"""
Scheduled scans and phone notifications.

At the times in the Alerts tab (default 12:30 and 15:45, Monday to Friday) Android wakes
the app (app.ewscanner.Scheduler / AlarmReceiver / JobService) and calls run(). One run:

    1. Data update (the same incremental download as the Data tab)
    2. EW5 and EW3: a walk-forward backtest over the last `lookback_days`, so each setup
       carries its outcome (was the TRIGGER level crossed, and when) - the same engine,
       settings and higher-timeframe alignment as a Run / Backtest run
    3. Today's events:
         TRIGGERED  the close crossed the TRIGGER level today (trigger_time is today)
         NEW        a setup appeared today (signal_time is today)
    4. One notification listing every event of the day; it is posted again only when a
       run finds events that were not notified yet

The results are saved like any run (results/backtest_auto_*.csv, ew3_backtest_auto_*.csv),
so they can be opened in the EW5 / EW3 tabs; only the newest few are kept.
"""

from __future__ import annotations

import html
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core import htf, runner, strategies, universe
from mobile import jobs, scan, workers
from core.alert_settings import DAYS, DEFAULTS, _times, clean_settings, missed, next_runs, public, side_rules, slots, timeframes_for, with_defaults  # noqa: F401
from core.alert_events import (ALIGN_ORDER, TF_ORDER, HEADER_FIELDS, LINE_FIELDS, SAMPLE, TELEGRAM_LIMIT, TELEGRAM_URL,  # noqa: F401
                               _Fields, _event_rows, _line, _num, _telegram, line_fields, messages, notification_lines, preview_texts, send_telegram, send_test,
                               telegram_text)
from mobile.fetch import yahoo_fetch

KEEP_AUTO_FILES = 4                          # per strategy
HISTORY_DAYS = 14


# ----------------------------------------------------------------------------------
# Files: settings (also read by the Android scheduler), sent log, history, last run
# ----------------------------------------------------------------------------------
# Android notification per category: separate ones stay side by side in the shade
NOTIFY_IDS = {"ALL": 2, "TRIGGERED": 3, "NEW": 4}


def _dir(app) -> Path:
    return app.root / "data"


def settings_path(app) -> Path:
    return _dir(app) / "alert_settings.json"


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


def load_settings(app) -> dict:
    saved = _read(settings_path(app), {})
    out = with_defaults(saved)
    if not settings_path(app).exists():
        _write(settings_path(app), out)                       # the scheduler reads this file
    return out


def _java(cls: str, method: str, *args: Any) -> bool:
    """Call into the Android app; False on a desktop (tests, browser preview)."""
    try:
        from java import jclass                       # Chaquopy, inside the app only
        getattr(jclass(f"app.ewscanner.{cls}"), method)(*args)
        return True
    except Exception:
        return False


def save_settings(app, values: dict) -> dict:
    settings = clean_settings(values, load_settings(app))
    _write(settings_path(app), settings)
    scheduled = _java("Scheduler", "reschedule")
    return {"ok": True, "settings": public(settings), "next": next_runs(settings), "scheduled": scheduled}


def telegram_preview(app, values: dict) -> dict:
    """The message as it would look now: today's alerts, or two examples when there are none yet."""
    s = {**load_settings(app), **{k: v for k, v in values.items()
                                  if k.startswith("telegram_") or k == "split_messages"}}
    history = _read(_dir(app) / "alerts_history.json", [])
    today = [h for h in history if h.get("day") == str(date.today())]
    events = sorted(today, key=lambda h: (h["event"] != "TRIGGERED", h["at"]))[:12] or SAMPLE
    texts = [t for _, msgs in preview_texts(events, s) for t in msgs]
    return {"messages": texts, "example": not today,
            "header_fields": HEADER_FIELDS, "line_fields": LINE_FIELDS}


def telegram_test(app, values: dict) -> dict:
    """Send a test message with the token / chat ID on the page (or the saved ones)."""
    saved = load_settings(app)
    s = {"telegram_token": str(values.get("telegram_token") or "").strip() or saved.get("telegram_token", ""),
         "telegram_chat_id": str(values.get("telegram_chat_id") or "").strip() or saved.get("telegram_chat_id", "")}
    s.update({k: v for k, v in {**saved, **values}.items()
              if k in ("telegram_header", "telegram_line", "telegram_group", "split_messages")})
    result = send_test(s)
    if result != "sent":
        raise ValueError(f"Telegram: {result}")
    return {"ok": True, "note": "Test message sent to Telegram."}


def telegram_find_chat(app, values: dict) -> dict:
    """Chat IDs that recently wrote to the bot (send it any message first)."""
    token = str(values.get("telegram_token") or "").strip() or load_settings(app).get("telegram_token", "")
    if not token:
        raise ValueError("Enter the bot token first.")
    r = _telegram(token, "getUpdates", {"limit": 50})
    if not r.get("ok"):
        raise ValueError(f"Telegram: {r.get('description', 'unknown error')}")
    chats = {}
    for u in r.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            chats[str(chat["id"])] = chat.get("title") or " ".join(
                x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or ""
    if not chats:
        raise ValueError("No chats yet: open your bot in Telegram, send it any message, then try again.")
    return {"chats": [[cid, name] for cid, name in chats.items()]}


def _prune_auto_files(results_dir: Path) -> None:
    for prefix in ("backtest_auto_", "ew3_backtest_auto_"):
        files = sorted(results_dir.glob(f"{prefix}*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[KEEP_AUTO_FILES:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)


def run(app, source: str = "schedule", today: Optional[date] = None, notify: bool = True,
        kind: str = "regular") -> dict:
    """
    Start the scan as the one background job. Returns the job, or {'busy': ...}.
    kind "full": the weekly scan of every stock; "regular": the Alerts tab's universe.
    """
    settings = load_settings(app)
    today = today or date.today()
    scope = "all" if kind == "full" else settings.get("universe", "fno")

    def work(job: jobs.Job) -> dict:
        t0 = time.time()
        summary: dict[str, Any] = {"source": source, "started": datetime.now().isoformat(timespec="seconds"),
                                   "date": str(today), "runs": {}, "events": 0, "new_events": 0}
        steps = (1 if settings["update_data"] else 0) + len(settings["strategies"])
        done = 0
        if settings["update_data"] and source == "schedule":
            waited = wait_for_network(job)                    # a phone just woken from sleep may be offline
            summary["network_wait_s"] = waited
        tickers = universe.final_list(app.cfg["tickers_file"], scope)
        summary["universe"] = scope
        if settings["update_data"]:
            from mobile import api
            job.say(f"Data update: {len(tickers)} tickers, {universe.UNIVERSES[scope]} "
                    f"(last {app.cfg['incremental_days']} days; new tickers: full history)")
            report = app.store.update(tickers, app.cfg["timeframes"], int(app.cfg["incremental_days"]), False,
                                      yahoo_fetch, progress=lambda f, m: job.progress(f / steps, f"Data · {m}"))
            app.last_report = api._report_json(report)
            summary["update"] = {"rows_after": report.rows_after, "failed": sum(len(v) for v in report.failed.values())}
            done += 1
        if app.store.empty():
            raise ValueError("No data yet. Download data first (Data tab).")

        engine, ew3_cfg = app.cfg["engine"], app.cfg["ew3"]
        start = today - timedelta(days=int(settings["lookback_days"]))
        events: list[dict] = []
        runs = []
        for key in settings["strategies"]:
            p = runner.RunParams(
                mode="backtest", timeframes=tuple(timeframes_for(settings, kind)), lengths=tuple(engine["lengths"]),
                stages=tuple(ew3_cfg["stages"] if key == "ew3" else engine["stages"]),
                horizon_bars=int(engine["horizon_bars"]), min_bars=int(app.cfg["min_bars"]),
                pivot_tie=engine["pivot_tie"], hi_source=engine["hi_source"], lo_source=engine["lo_source"],
                min_w5_vs_w1=float(engine["min_w5_vs_w1"]), start=str(start), end=str(today), strategy=key,
                contexts=tuple(ew3_cfg["contexts"]), min_retrace=float(ew3_cfg["min_retrace"]),
                max_retrace=float(ew3_cfg["max_retrace"]), universe=scope)
            runs.append((key, p))
        # EW5 and EW3 in one pass over the parts (each part is read once), on several cores
        names = " + ".join(strategies.get(k).name for k, _ in runs)
        job.say(f"{names}: {universe.UNIVERSES[scope]}, setups since {start}")
        n_steps_left = steps - done
        by_key = workers.run_parts(
            app.store.part_paths(), runs, set(tickers), app.cfg["signal_indicators"], app.cfg["htf"],
            int(app.cfg.get("phone", {}).get("engine_workers", 4)), app.root / "work",
            progress=lambda i, total, d=done: job.progress(
                (d + n_steps_left * i / max(total, 1)) / steps, f"{names} · part {min(i + 1, total)}/{total}"),
            log=job.say)
        for key, p in runs:
            S = strategies.get(key)
            res = by_key[key]
            saved = runner.save_results(res, p, app.cfg["results_dir"], app.store.dir,
                                        stamp="auto_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            found = _event_rows(res, S, today, settings["events"], settings["aligned_only"], saved.name,
                                grade_cfg=app.cfg["fno_5day"], attrs=universe.load_attributes(app.cfg["tickers_file"]),
                                fno5_only=settings.get("fno5_only", False), sides=side_rules(settings))
            summary["runs"][key] = {"file": saved.name, "setups": len(res), "today": len(found)}
            events += found
            done += 1
        _prune_auto_files(app.cfg["results_dir"])

        # ---- notify what was not notified yet; the notification lists the whole day
        sent_path, hist_path = _dir(app) / "alerts_sent.json", _dir(app) / "alerts_history.json"
        sent = _read(sent_path, {})
        history = _read(hist_path, [])
        fresh = [e for e in events if e["key"] not in sent]
        stamp = datetime.now().isoformat(timespec="seconds")
        for e in fresh:
            sent[e["key"]] = str(today)
            history.append({**e, "day": str(today), "notified": stamp})
        cutoff = str(today - timedelta(days=HISTORY_DAYS))
        sent = {k: d for k, d in sent.items() if d >= cutoff}
        history = [h for h in history if h.get("day", h["notified"][:10]) >= cutoff][-1000:]
        _write(sent_path, sent)
        _write(hist_path, history)
        todays = [h for h in history if h.get("day") == str(today)]
        n_trig = sum(h["event"] == "TRIGGERED" for h in todays)
        summary.update(events=len(todays), triggered=n_trig, new_setups=len(todays) - n_trig,
                       new_events=len(fresh), seconds=round(time.time() - t0, 1))
        if notify:
            # one notification (and Telegram message) per category, or one for the whole day
            for category, title, rows in messages(todays, fresh, settings.get("split_messages", True)):
                shown = _java("Notifier", "show", title, json.dumps(notification_lines(rows)),
                              NOTIFY_IDS[category])
                summary["notified"] = summary.get("notified", True) and shown
                if settings.get("telegram"):
                    result = send_telegram(settings, title, rows, category)
                    summary["telegram"] = result if summary.get("telegram", "sent") == "sent" else summary["telegram"]
        _write(_dir(app) / "alerts_last_run.json", summary)
        return summary

    try:
        title = ("Weekly full scan" if kind == "full" else "Scheduled scan") if source == "schedule" else "Alert scan"
        return jobs.start("alerts", title, work)
    except RuntimeError as exc:                         # another job is running: try at the next time
        _write(_dir(app) / "alerts_last_run.json", {"source": source, "started": datetime.now().isoformat(timespec="seconds"),
                                                     "date": str(today), "skipped": str(exc)})
        if jobs.current() is None or not jobs.current()["running"]:
            jobs._notify(False, "")
        return {"busy": str(exc)}


def wait_for_network(job: Optional[jobs.Job] = None, limit: float = 120.0) -> float:
    """Wait (up to `limit` seconds) until Yahoo can be reached; returns the seconds waited."""
    import socket
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            socket.create_connection(("query2.finance.yahoo.com", 443), timeout=8).close()
            return round(time.time() - t0, 1)
        except OSError:
            if job:
                job.say("Waiting for the network…")
            time.sleep(5)
    return round(time.time() - t0, 1)


def alarm_log(app, lines: int = 12) -> list[str]:
    """What the Android scheduler did (files/data/alarm_log.txt, newest first)."""
    try:
        return (_dir(app) / "alarm_log.txt").read_text(encoding="utf-8").strip().splitlines()[::-1][:lines]
    except OSError:
        return []


def overview(app) -> dict:
    """Everything the Alerts tab shows."""
    settings = load_settings(app)
    history = _read(_dir(app) / "alerts_history.json", [])
    today = str(date.today())
    n = universe.counts(app.cfg["tickers_file"])
    return {"settings": public(settings), "next": next_runs(settings), "days": list(DAYS),
            "universes": [[k, f"{v} ({n.get(k, 0):,} stocks)"] for k, v in universe.UNIVERSES.items()],
            "last_run": _read(_dir(app) / "alerts_last_run.json", None),
            "missed": missed(settings, (_read(_dir(app) / "alerts_last_run.json", None) or {}).get("started")),
            "today": sorted([h for h in history if h.get("day", h["notified"][:10]) == today],   # triggers first,
                            key=lambda h: (h["event"] != "TRIGGERED", TF_ORDER.get(h.get("tf"), 9),  # then 60m → 1D
                                           ALIGN_ORDER.get(h.get("alignment"), 3), h.get("at", ""))),
            "history": history[::-1][:300], "timeframes": ["60m", "4hr", "1D", "1W"], "alarm_log": alarm_log(app),
            "strategies": [[S.key, S.name] for S in strategies.STRATEGIES.values()]}


def test_notification(app) -> dict:
    split = load_settings(app).get("split_messages", True)
    ok = True
    for category, title, rows in messages(SAMPLE, SAMPLE, split):
        ok = _java("Notifier", "show", "Test · " + title, json.dumps(notification_lines(rows)),
                   NOTIFY_IDS[category]) and ok
    return {"ok": ok, "note": "Sent." if ok else "Notifications are sent by the phone app only."}
