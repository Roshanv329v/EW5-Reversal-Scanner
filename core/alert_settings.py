"""
Scheduled-scan settings shared by the phone (mobile/alerts.py, Android Scheduler) and the
desktop (scheduled_scan.py, Alerts tab): defaults, validation and the upcoming scan times.
Both keep them in data/alert_settings.json with the same keys.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from core import strategies, universe
from core.alert_events import TEMPLATE_DEFAULTS  # noqa: F401  (the Telegram layout defaults)


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "days": [1, 2, 3, 4, 5],                 # 1 = Monday ... 7 = Sunday
    "times": ["12:30", "15:45"],             # phone's local time (IST)
    "universe": "fno",                       # stocks for these scans: "fno" (F&O, ~210) or "all" (~1,300)
    "full_enabled": True,                    # plus a weekly scan of every stock in tickers.csv
    "full_days": [5],                        # Friday
    "full_times": ["18:00"],                 # after the close: the week's final bars
    "update_data": True,
    "strategies": ["ew5", "ew3"],
    "timeframes": ["1D", "4hr", "60m"],
    "events": ["TRIGGERED", "NEW"],
    "aligned_only": False,                   # notify only signals ALIGNED with the higher timeframes
    "lookback_days": 10,                     # setups from this many days back can still trigger today
    "telegram": False,                       # also send the day's list to a Telegram bot (off by default)
    "telegram_token": "",                    # from @BotFather; kept in the app's private storage only
    "telegram_chat_id": "",
    "telegram_header": "<b>{title}</b>",
    "telegram_line": "{icon} {strategy} <b>{ticker}</b> {tf} {degree} {side} · {time} · {alignment} · trigger {trigger} · stop {stop}",
    "telegram_group": True,                  # "Triggered today" / "New setups today" sections
}


def _times(values: Any) -> list[str]:
    out = []
    for t in values or []:
        try:
            hh, mm = str(t).split(":")[:2]
            if 0 <= int(hh) < 24 and 0 <= int(mm) < 60:
                out.append(f"{int(hh):02d}:{int(mm):02d}")
        except ValueError:
            continue
    return sorted(set(out))


def clean_settings(values: dict, old: Optional[dict] = None) -> dict:
    """Validate what the Alerts tab sends. An empty token keeps the saved one (the page never sees it)."""
    out = dict(DEFAULTS)
    out["enabled"] = bool(values.get("enabled"))
    out["days"] = sorted({int(d) for d in values.get("days", []) if 1 <= int(d) <= 7})
    out["times"] = _times(values.get("times", []))
    out["universe"] = values.get("universe") if values.get("universe") in universe.UNIVERSES else "fno"
    out["full_enabled"] = bool(values.get("full_enabled", True))
    out["full_days"] = sorted({int(d) for d in values.get("full_days", [5]) if 1 <= int(d) <= 7})
    out["full_times"] = _times(values.get("full_times", ["18:00"]))
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
    out["telegram_header"] = str(values.get("telegram_header") or DEFAULTS["telegram_header"])[:500]
    out["telegram_line"] = str(values.get("telegram_line") or DEFAULTS["telegram_line"])[:800]
    out["telegram_group"] = bool(values.get("telegram_group", True))
    problems = []
    if out["telegram"] and not (out["telegram_token"] and out["telegram_chat_id"]):
        problems.append("Telegram needs a bot token and a chat ID.")
    if out["enabled"]:
        if not out["days"]:
            problems.append("Pick at least one day.")
        if not out["times"] and not (out["full_enabled"] and out["full_times"]):
            problems.append("Add at least one time.")
        if out["full_enabled"] and not (out["full_days"] and out["full_times"]):
            problems.append("The weekly full scan needs a day and a time.")
        if not out["strategies"]:
            problems.append("Pick EW5, EW3 or both.")
        if not out["timeframes"]:
            problems.append("Pick at least one timeframe.")
        if not out["events"]:
            problems.append("Pick what to be notified about.")
    if problems:
        raise ValueError(" ".join(problems))
    return out


def slots(settings: dict, now: Optional[datetime] = None, days: int = 15) -> list[tuple[datetime, str]]:
    """
    Upcoming scans as (time, kind): kind "full" = every stock (weekly), "regular" = the usual
    universe. A full scan at the same minute as a regular one replaces it. Same rule as
    app.ewscanner.Scheduler.
    """
    if not settings.get("enabled"):
        return []
    now = now or datetime.now()
    found: dict[datetime, str] = {}
    for offset in range(days):
        day = (now + timedelta(days=offset)).date()
        for kind, day_key, time_key in (("regular", "days", "times"), ("full", "full_days", "full_times")):
            if kind == "full" and not settings.get("full_enabled"):
                continue
            if day.isoweekday() not in settings.get(day_key, []):
                continue
            for t in settings.get(time_key, []):
                hh, mm = map(int, t.split(":"))
                at = datetime(day.year, day.month, day.day, hh, mm)
                if at > now and found.get(at) != "full":
                    found[at] = kind
    return sorted(found.items())


def next_runs(settings: dict, now: Optional[datetime] = None, count: int = 3) -> list[str]:
    """The next scheduled times, labelled (F&O / all stocks)."""
    names = {"regular": universe.UNIVERSES[settings.get("universe", "fno")], "full": "All stocks"}
    return [f"{at:%a %d %b %H:%M} ({names[kind]})" for at, kind in slots(settings, now)[:count]]


def public(settings: dict) -> dict:
    """Settings for the page: the bot token is never sent back, only whether one is saved."""
    out = {k: v for k, v in settings.items() if k != "telegram_token"}
    out["telegram_token_set"] = bool(settings.get("telegram_token"))
    return out
