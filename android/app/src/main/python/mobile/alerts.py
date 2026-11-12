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

from core import htf, runner, strategies
from mobile import jobs, scan
from mobile.fetch import yahoo_fetch

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "days": [1, 2, 3, 4, 5],                 # 1 = Monday ... 7 = Sunday
    "times": ["12:30", "15:45"],             # phone's local time (IST)
    "update_data": True,
    "strategies": ["ew5", "ew3"],
    "timeframes": ["1D", "4hr", "60m"],
    "events": ["TRIGGERED", "NEW"],
    "aligned_only": False,                   # notify only signals ALIGNED with the higher timeframes
    "lookback_days": 10,                     # setups from this many days back can still trigger today
    "telegram": False,                       # also send the day's list to a Telegram bot (off by default)
    "telegram_token": "",                    # from @BotFather; kept in the app's private storage only
    "telegram_chat_id": "",
}
TELEGRAM_URL = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_LIMIT = 3800                        # Telegram allows 4096 characters per message
KEEP_AUTO_FILES = 4                          # per strategy
HISTORY_DAYS = 14


# ----------------------------------------------------------------------------------
# Files: settings (also read by the Android scheduler), sent log, history, last run
# ----------------------------------------------------------------------------------
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
    out = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    if not settings_path(app).exists():
        _write(settings_path(app), out)                       # the scheduler reads this file
    return out


def clean_settings(values: dict, old: Optional[dict] = None) -> dict:
    """Validate what the Alerts tab sends. An empty token keeps the saved one (the page never sees it)."""
    out = dict(DEFAULTS)
    out["enabled"] = bool(values.get("enabled"))
    out["days"] = sorted({int(d) for d in values.get("days", []) if 1 <= int(d) <= 7})
    times = []
    for t in values.get("times", []):
        try:
            hh, mm = str(t).split(":")[:2]
            if 0 <= int(hh) < 24 and 0 <= int(mm) < 60:
                times.append(f"{int(hh):02d}:{int(mm):02d}")
        except ValueError:
            continue
    out["times"] = sorted(set(times))
    out["update_data"] = bool(values.get("update_data", True))
    out["strategies"] = [s for s in values.get("strategies", []) if s in strategies.STRATEGIES]
    out["timeframes"] = [tf for tf in values.get("timeframes", []) if tf in ("1D", "4hr", "60m", "1W")]
    out["events"] = [e for e in values.get("events", []) if e in ("TRIGGERED", "NEW")]
    out["aligned_only"] = bool(values.get("aligned_only"))
    out["lookback_days"] = max(2, min(60, int(values.get("lookback_days") or DEFAULTS["lookback_days"])))
    out["telegram"] = bool(values.get("telegram"))
    token = str(values.get("telegram_token") or "").strip()
    out["telegram_token"] = token or (old or {}).get("telegram_token", "")
    out["telegram_chat_id"] = str(values.get("telegram_chat_id") or "").strip()
    problems = []
    if out["telegram"] and not (out["telegram_token"] and out["telegram_chat_id"]):
        problems.append("Telegram needs a bot token and a chat ID.")
    if out["enabled"]:
        if not out["days"]:
            problems.append("Pick at least one day.")
        if not out["times"]:
            problems.append("Add at least one time.")
        if not out["strategies"]:
            problems.append("Pick EW5, EW3 or both.")
        if not out["timeframes"]:
            problems.append("Pick at least one timeframe.")
        if not out["events"]:
            problems.append("Pick what to be notified about.")
    if problems:
        raise ValueError(" ".join(problems))
    return out


def next_runs(settings: dict, now: Optional[datetime] = None, count: int = 3) -> list[str]:
    """The next scheduled times (same rule as app.ewscanner.Scheduler)."""
    if not settings.get("enabled") or not settings.get("days") or not settings.get("times"):
        return []
    now = now or datetime.now()
    out = []
    for offset in range(0, 15):
        day = (now + timedelta(days=offset)).date()
        if day.isoweekday() not in settings["days"]:
            continue
        for t in settings["times"]:
            hh, mm = map(int, t.split(":"))
            at = datetime(day.year, day.month, day.day, hh, mm)
            if at > now:
                out.append(at.strftime("%a %d %b %H:%M"))
                if len(out) == count:
                    return out
    return out


def _java(cls: str, method: str, *args: Any) -> bool:
    """Call into the Android app; False on a desktop (tests, browser preview)."""
    try:
        from java import jclass                       # Chaquopy, inside the app only
        getattr(jclass(f"app.ewscanner.{cls}"), method)(*args)
        return True
    except Exception:
        return False


def public(settings: dict) -> dict:
    """Settings for the page: the bot token is never sent back, only whether one is saved."""
    out = {k: v for k, v in settings.items() if k != "telegram_token"}
    out["telegram_token_set"] = bool(settings.get("telegram_token"))
    return out


def save_settings(app, values: dict) -> dict:
    settings = clean_settings(values, load_settings(app))
    _write(settings_path(app), settings)
    scheduled = _java("Scheduler", "reschedule")
    return {"ok": True, "settings": public(settings), "next": next_runs(settings), "scheduled": scheduled}


# ----------------------------------------------------------------------------------
# Telegram (optional)
# ----------------------------------------------------------------------------------
def _telegram(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(TELEGRAM_URL.format(token=token, method=method),
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:          # Telegram explains the problem in the body
        try:
            return json.load(exc)
        except ValueError:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "description": f"no connection ({getattr(exc, 'reason', exc)})"}


def telegram_text(title: str, events: list[dict]) -> list[str]:
    """The day's list as Telegram messages (HTML), split under Telegram's size limit."""
    head = f"<b>{html.escape(title)}</b>"
    blocks = []
    for kind, label in (("TRIGGERED", "Triggered today"), ("NEW", "New setups today")):
        rows = [e for e in events if e["event"] == kind]
        if not rows:
            continue
        lines = [f"<b>{label} ({len(rows)})</b>"]
        for e in rows:
            align = f" · {e['alignment']}" if e.get("alignment") else ""
            lines.append(html.escape(f"• {e['strategy'].upper()} {e['ticker']} {e['tf']} {e['degree']} {e['side']} "
                                     f"{e['at'][11:]}{align} · trigger {e['trigger']:,.2f} · stop {e['stop']:,.2f}"))
        blocks.append("\n".join(lines))
    messages, current = [], head
    for line in "\n\n".join(blocks).split("\n"):
        if len(current) + len(line) + 1 > TELEGRAM_LIMIT:
            messages.append(current)
            current = head + " (continued)"
        current += "\n" + line
    messages.append(current)
    return messages


def send_telegram(settings: dict, title: str, events: list[dict]) -> str:
    if not (settings.get("telegram_token") and settings.get("telegram_chat_id")):
        return "not set up"
    for text in telegram_text(title, events):
        r = _telegram(settings["telegram_token"], "sendMessage",
                      {"chat_id": settings["telegram_chat_id"], "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True})
        if not r.get("ok"):
            return f"failed: {r.get('description', 'unknown error')}"
    return "sent"


def telegram_test(app, values: dict) -> dict:
    """Send a test message with the token / chat ID on the page (or the saved ones)."""
    saved = load_settings(app)
    s = {"telegram_token": str(values.get("telegram_token") or "").strip() or saved.get("telegram_token", ""),
         "telegram_chat_id": str(values.get("telegram_chat_id") or "").strip() or saved.get("telegram_chat_id", "")}
    sample = [{"event": "TRIGGERED", "strategy": "ew5", "ticker": "EXAMPLE.NS", "tf": "60m", "degree": "minor",
               "side": "SHORT", "at": "2026-01-01 13:15", "alignment": "ALIGNED", "trigger": 100.0, "stop": 102.5}]
    result = send_telegram(s, "EW Scanner · test alert", sample)
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


# ----------------------------------------------------------------------------------
# One scheduled run
# ----------------------------------------------------------------------------------
def _event_rows(res: pd.DataFrame, S, today: date, wanted: list[str], aligned_only: bool, file: str) -> list[dict]:
    if res.empty:
        return []
    side = S.side_col
    rows = []
    trig = res["status"].eq("TRIGGERED") & (pd.to_datetime(res["trigger_time"]).dt.date == today)
    new = pd.to_datetime(res["signal_time"]).dt.date == today
    for event, mask in (("TRIGGERED", trig), ("NEW", new)):
        if event not in wanted:
            continue
        part = res[mask]
        if aligned_only and "alignment" in part.columns:
            part = part[part["alignment"].eq(htf.ALIGNED)]
        for idx, r in part.iterrows():
            at = r["trigger_time"] if event == "TRIGGERED" else r["signal_time"]
            rows.append({
                "key": f"{S.key}|{r['Ticker']}|{r['time_frame']}|{r['zigzag_length']}|{r['signal_time']}|{event}",
                "event": event, "strategy": S.key, "ticker": r["Ticker"], "tf": r["time_frame"],
                "degree": r["degree"], "side": r[side], "alignment": r.get("alignment"),
                "at": str(pd.Timestamp(at))[:16], "signal_time": str(pd.Timestamp(r["signal_time"]))[:16],
                "trigger": round(float(r["TRIGGER"]), 2), "stop": round(float(r["STOP"]), 2),
                "close": round(float(r["close"]), 2), "file": file, "id": int(idx)})
    return rows


def _line(e: dict) -> str:
    what = "triggered" if e["event"] == "TRIGGERED" else "new setup"
    align = f" · {e['alignment']}" if e.get("alignment") else ""
    return f"{e['strategy'].upper()} {e['ticker']} {e['tf']} {e['side']} · {what} {e['at'][11:]}{align}"


def _prune_auto_files(results_dir: Path) -> None:
    for prefix in ("backtest_auto_", "ew3_backtest_auto_"):
        files = sorted(results_dir.glob(f"{prefix}*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[KEEP_AUTO_FILES:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)


def run(app, source: str = "schedule", today: Optional[date] = None, notify: bool = True) -> dict:
    """Start the scan as the one background job. Returns the job, or {'busy': ...}."""
    settings = load_settings(app)
    today = today or date.today()

    def work(job: jobs.Job) -> dict:
        t0 = time.time()
        summary: dict[str, Any] = {"source": source, "started": datetime.now().isoformat(timespec="seconds"),
                                   "date": str(today), "runs": {}, "events": 0, "new_events": 0}
        steps = (1 if settings["update_data"] else 0) + len(settings["strategies"])
        done = 0
        if settings["update_data"]:
            from mobile import api
            tickers = api.stock_data.build_final_list(api._stock_tickers())
            job.say(f"Data update: {len(tickers)} tickers (last {app.cfg['incremental_days']} days)")
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
        for key in settings["strategies"]:
            S = strategies.get(key)
            p = runner.RunParams(
                mode="backtest", timeframes=tuple(settings["timeframes"]), lengths=tuple(engine["lengths"]),
                stages=tuple(ew3_cfg["stages"] if key == "ew3" else engine["stages"]),
                horizon_bars=int(engine["horizon_bars"]), min_bars=int(app.cfg["min_bars"]),
                pivot_tie=engine["pivot_tie"], hi_source=engine["hi_source"], lo_source=engine["lo_source"],
                min_w5_vs_w1=float(engine["min_w5_vs_w1"]), start=str(start), end=str(today), strategy=key,
                contexts=tuple(ew3_cfg["contexts"]), min_retrace=float(ew3_cfg["min_retrace"]),
                max_retrace=float(ew3_cfg["max_retrace"]))
            n = len(app.store.part_paths())
            job.say(f"{S.name}: setups since {start}")
            res = scan.run_groups(app.store.frames(), n, p, app.cfg["signal_indicators"], app.cfg["htf"],
                                  progress=lambda i, total, d=done: job.progress(
                                      (d + i / max(total, 1)) / steps, f"{key.upper()} · part {min(i + 1, total)}/{total}"))
            saved = runner.save_results(res, p, app.cfg["results_dir"], app.store.dir,
                                        stamp="auto_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
            found = _event_rows(res, S, today, settings["events"], settings["aligned_only"], saved.name)
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
        if fresh and notify:
            parts = [f"{n_trig} triggered" if n_trig else "", f"{len(todays) - n_trig} new setups" if len(todays) > n_trig else ""]
            title = f"EW alerts today: {' · '.join(p for p in parts if p)} ({len(fresh)} since last scan)"
            todays = sorted(todays, key=lambda h: (h["event"] != "TRIGGERED", h["at"]))   # triggers first
            summary["notified"] = _java("Notifier", "show", title, json.dumps([_line(e) for e in todays]))
            if settings.get("telegram"):
                summary["telegram"] = send_telegram(settings, title, todays)
        _write(_dir(app) / "alerts_last_run.json", summary)
        return summary

    try:
        return jobs.start("alerts", "Scheduled scan" if source == "schedule" else "Alert scan", work)
    except RuntimeError as exc:                         # another job is running: try at the next time
        _write(_dir(app) / "alerts_last_run.json", {"source": source, "started": datetime.now().isoformat(timespec="seconds"),
                                                     "date": str(today), "skipped": str(exc)})
        if jobs.current() is None or not jobs.current()["running"]:
            jobs._notify(False, "")
        return {"busy": str(exc)}


def overview(app) -> dict:
    """Everything the Alerts tab shows."""
    settings = load_settings(app)
    history = _read(_dir(app) / "alerts_history.json", [])
    today = str(date.today())
    return {"settings": public(settings), "next": next_runs(settings), "days": list(DAYS),
            "last_run": _read(_dir(app) / "alerts_last_run.json", None),
            "today": [h for h in history if h.get("day", h["notified"][:10]) == today][::-1],
            "history": history[::-1][:300], "timeframes": app.cfg["timeframes"],
            "strategies": [[S.key, S.name] for S in strategies.STRATEGIES.values()]}


def test_notification() -> dict:
    ok = _java("Notifier", "show", "EW Scanner · test alert",
               json.dumps(["EW5 EXAMPLE.NS 60m SHORT · triggered 13:15 · ALIGNED",
                           "This is how a scheduled scan reports the day's stocks."]))
    return {"ok": ok, "note": "Sent." if ok else "Notifications are sent by the phone app only."}
