"""
Alert events and Telegram messages, shared by the phone app (mobile/alerts.py) and the
desktop's scheduled scans (scheduled_scan.py):

    event_rows()      today's TRIGGERED / NEW signals of a backtest result
    telegram_text()   the day's list as Telegram messages, from the Alerts templates
    send_telegram()   send them with a bot token and chat ID
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Optional

import pandas as pd

from core import htf

TEMPLATE_DEFAULTS = {
    "telegram_header": "<b>{title}</b>",
    "telegram_line": "{icon} {strategy} <b>{ticker}</b> {tf} {degree} {side} · {time} · {alignment} · trigger {trigger} · stop {stop}",
    "telegram_group": True,
}


# placeholders for the Telegram message (Alerts tab shows this list)
HEADER_FIELDS = {"title": "the notification title", "date": "the trading day", "count": "stocks today",
                 "triggered": "triggered today", "new": "new setups today"}


LINE_FIELDS = {
    "icon": "🟢 LONG / 🔴 SHORT", "event": "Triggered / New setup", "strategy": "EW5 / EW3", "ticker": "RELIANCE.NS",
    "symbol": "RELIANCE (no .NS)", "tf": "60m / 4hr / 1D", "degree": "minor / intermediate / major", "side": "LONG / SHORT",
    "time": "when it triggered / appeared", "signal_time": "signal bar", "alignment": "ALIGNED / MIXED / AGAINST",
    "htf": "higher-timeframe trends", "stage": "wave stage", "context": "EW3 context", "close": "close at the signal",
    "trigger": "TRIGGER level", "stop": "STOP level", "entry": "entry price (triggered)", "target1": "first target",
    "target2": "second target", "target1_name": "e.g. W4_END", "target2_name": "e.g. FIB_0.500",
    "risk_pct": "trigger→stop distance in %", "tradingview": "TradingView link (NSE stocks)"}


TELEGRAM_URL = "https://api.telegram.org/bot{token}/{method}"


TELEGRAM_LIMIT = 3800                        # Telegram allows 4096 characters per message


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


class _Fields(dict):
    """format_map values: unknown {names} stay as written instead of failing."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _num(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{float(v):,.2f}"


def line_fields(e: dict) -> _Fields:
    """Values for one stock's line (HTML-escaped: the template may use <b>, <i>, <code>, <a>)."""
    t = str(e.get("ticker", ""))
    symbol = t[:-3] if t.endswith(".NS") else t
    trigger, stop = e.get("trigger"), e.get("stop")
    risk = abs(float(trigger) - float(stop)) / float(trigger) * 100 if trigger and stop else None
    raw = {
        "icon": "🟢" if e.get("side") == "LONG" else "🔴" if e.get("side") == "SHORT" else "•",
        "event": "Triggered" if e.get("event") == "TRIGGERED" else "New setup",
        "strategy": str(e.get("strategy", "")).upper(), "ticker": t, "symbol": symbol, "tf": e.get("tf", ""),
        "degree": e.get("degree", ""), "side": e.get("side", ""), "time": str(e.get("at", ""))[11:16] or e.get("at", ""),
        "signal_time": e.get("signal_time", ""), "alignment": e.get("alignment") or "", "htf": e.get("htf") or "",
        "stage": e.get("stage") or "", "context": e.get("context") or "", "close": _num(e.get("close")),
        "trigger": _num(trigger), "stop": _num(stop), "entry": _num(e.get("entry")),
        "target1": _num(e.get("target1")), "target2": _num(e.get("target2")),
        "target1_name": e.get("target1_name") or "", "target2_name": e.get("target2_name") or "",
        "risk_pct": f"{risk:.2f}%" if risk is not None else "",
        "tradingview": f"https://www.tradingview.com/chart/?symbol=NSE:{symbol}" if t.endswith(".NS") else "",
    }
    return _Fields({k: html.escape(str(v)) for k, v in raw.items()})


def telegram_text(title: str, events: list[dict], settings: Optional[dict] = None) -> list[str]:
    """The day's list as Telegram messages (HTML), from the Alerts tab's templates, split under the limit."""
    s = {**TEMPLATE_DEFAULTS, **(settings or {})}
    n_trig = sum(e.get("event") == "TRIGGERED" for e in events)
    head = s["telegram_header"].format_map(_Fields({
        "title": html.escape(title), "date": html.escape(str(events[0].get("at", ""))[:10]) if events else "",
        "count": str(len(events)), "triggered": str(n_trig), "new": str(len(events) - n_trig)}))
    groups = ((("TRIGGERED", "Triggered today"), ("NEW", "New setups today")) if s["telegram_group"]
              else ((None, None),))
    blocks = []
    for kind, label in groups:
        rows = [e for e in events if kind is None or e["event"] == kind]
        if not rows:
            continue
        lines = [f"<b>{label} ({len(rows)})</b>"] if label else []
        lines += [s["telegram_line"].format_map(line_fields(e)).replace(" ·  · ", " · ") for e in rows]
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
    for text in telegram_text(title, events, settings):
        payload = {"chat_id": settings["telegram_chat_id"], "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        r = _telegram(settings["telegram_token"], "sendMessage", payload)
        if not r.get("ok") and "parse" in str(r.get("description", "")).lower():
            # a template with unbalanced HTML: send it as plain text rather than not at all
            payload.pop("parse_mode")
            r = _telegram(settings["telegram_token"], "sendMessage", payload)
        if not r.get("ok"):
            return f"failed: {r.get('description', 'unknown error')}"
    return "sent"


SAMPLE = [{"event": "TRIGGERED", "strategy": "ew5", "ticker": "RELIANCE.NS", "tf": "60m", "degree": "minor",
           "side": "SHORT", "at": "2026-01-02 13:15", "signal_time": "2026-01-02 11:15", "alignment": "ALIGNED",
           "htf": "BEARISH · BEARISH", "stage": "WAVE5_IN_PROGRESS", "close": 1301.2, "trigger": 1298.5,
           "stop": 1312.0, "entry": 1297.0, "target1": 1270.4, "target2": 1255.0,
           "target1_name": "W4_END", "target2_name": "FIB_0.500"},
          {"event": "NEW", "strategy": "ew3", "ticker": "TCS.NS", "tf": "4hr", "degree": "intermediate",
           "side": "LONG", "at": "2026-01-02 09:15", "signal_time": "2026-01-02 09:15", "alignment": "MIXED",
           "htf": "NEUTRAL · BULLISH", "stage": "WAVE2_COMPLETED", "context": "AFTER_ABC", "close": 3410.0,
           "trigger": 3425.0, "stop": 3380.0, "entry": None, "target1": 3502.0, "target2": 3610.0,
           "target1_name": "W1_END", "target2_name": "W3_TGT_1.618xW1"}]


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
        (t1_name, t2_name) = [lvl for _, lvl in S.target_cards]
        for idx, r in part.iterrows():
            at = r["trigger_time"] if event == "TRIGGERED" else r["signal_time"]
            rows.append({
                "stage": r.get("stage"), "context": r.get("context"),
                "entry": None if pd.isna(r.get("entry_price")) else round(float(r["entry_price"]), 2),
                "target1": round(float(r[t1_name]), 2) if pd.notna(r.get(t1_name)) else None, "target1_name": t1_name,
                "target2": round(float(r[t2_name]), 2) if pd.notna(r.get(t2_name)) else None, "target2_name": t2_name,
                "htf": " · ".join(str(r[c]) for c in htf.TREND_COLS if c in r.index and pd.notna(r[c])),
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


# public names
event_rows = _event_rows
line = _line
