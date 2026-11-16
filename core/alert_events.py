"""
Alert events and Telegram messages, shared by the phone app (mobile/alerts.py) and the
desktop's scheduled scans (scheduled_scan.py):

    event_rows()      today's TRIGGERED / NEW signals of a backtest result
    messages()        what a scan sends: Triggered and New setups apart (or together), sorted
                      new first, then 60m → 4hr → 1D, aligned first
    render()          one message in the chosen layout: cards, compact, or the custom template
    telegram_text()   the custom-template layout
    send_telegram()   send them with a bot token and chat ID
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Optional

import pandas as pd

from core import htf

TEMPLATE_DEFAULTS = {
    "telegram_style": "cards",               # "cards" / "compact" / "custom" (the two templates below)
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
    "risk_pct": "trigger→stop distance in %", "tradingview": "TradingView chart link at the signal's timeframe"}


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


_TV: Optional[dict] = None


def _tv() -> dict:
    """config.yaml's tradingview section (layout, intervals, symbols), read once."""
    global _TV
    if _TV is None:
        try:
            from core.config import load_config
            _TV = load_config().get("tradingview") or {}
        except Exception:                                   # no config: plain chart links
            _TV = {}
    return _TV


def tradingview_url(ticker: str, tf: Optional[str] = None) -> str:
    """The TradingView chart of a ticker at a timeframe, in the saved layout:
    https://www.tradingview.com/chart/<layout>/?symbol=NSE%3AYESBANK&interval=240"""
    tv = _tv()
    t = str(ticker or "")
    symbol = (tv.get("symbols") or {}).get(t)
    if not symbol:
        if t.endswith(".NS"):
            symbol = "NSE:" + re.sub(r"[^A-Z0-9]", "_", t[:-3].upper())     # M&M -> M_M, BAJAJ-AUTO -> BAJAJ_AUTO
        elif t.endswith(".BO"):
            symbol = "BSE:" + re.sub(r"[^A-Z0-9]", "_", t[:-3].upper())
        else:
            return ""
    intervals = tv.get("intervals") or {"60m": "60", "4hr": "240", "1D": "1D", "1W": "1W"}
    query = {"symbol": symbol}
    if intervals.get(tf):
        query["interval"] = intervals[tf]
    layout = str(tv.get("layout") or "").strip("/")
    return f"https://www.tradingview.com/chart/{layout + '/' if layout else ''}?" + urllib.parse.urlencode(query)


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
        "tradingview": tradingview_url(t, e.get("tf")),
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


def send_telegram(settings: dict, title: str, events: list[dict], category: str = "ALL") -> str:
    if not (settings.get("telegram_token") and settings.get("telegram_chat_id")):
        return "not set up"
    for text in render(category, title, events, settings):
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



# ----------------------------------------------------------------------------------
# One message, or one per category
# ----------------------------------------------------------------------------------
CATEGORIES = (("TRIGGERED", "triggered"), ("NEW", "new setups"))
STYLES = ("cards", "compact", "custom")       # Telegram layout: blocks per stock, one line per stock, template
TF_ORDER = {"60m": 0, "4hr": 1, "1D": 2, "1W": 3}
ALIGN_ORDER = {htf.ALIGNED: 0, htf.MIXED: 1, htf.AGAINST: 2}
ALIGN_ICON = {htf.ALIGNED: "✅", htf.MIXED: "➖", htf.AGAINST: "⚠️"}
CONTEXT_TEXT = {"AFTER_ABC": "after ABC", "AFTER_WAVE5": "after wave 5"}


def _ident(e: dict) -> str:
    return e.get("key") or f"{e.get('strategy')}|{e.get('ticker')}|{e.get('tf')}|{e.get('at')}|{e.get('event')}"


def sort_key(e: dict) -> tuple:
    """New since the last scan first, then 60m → 4hr → 1D → 1W, aligned before mixed / against, then time."""
    return (not e.get("_new", True), TF_ORDER.get(e.get("tf"), 9), ALIGN_ORDER.get(e.get("alignment"), 3),
            str(e.get("at", "")), str(e.get("ticker", "")))


def _symbol(e: dict) -> str:
    t = str(e.get("ticker", ""))
    return t[:-3] if t.endswith(".NS") else t


def _names(rows: list[dict], most: int = 3) -> str:
    names = list(dict.fromkeys(_symbol(e) for e in rows))
    return ", ".join(names[:most]) + (f" +{len(names) - most}" if len(names) > most else "")


def title_for(category: str, rows: list[dict]) -> str:
    """Notification title: who, not just how many."""
    if category == "TRIGGERED":
        return f"⚡ {len(rows)} triggered today: {_names(rows)}"
    if category == "NEW":
        return f"👀 {len(rows)} new setup{'s' if len(rows) != 1 else ''} today: {_names(rows)}"
    n_trig = sum(e["event"] == "TRIGGERED" for e in rows)
    parts = [f"⚡ {n_trig} triggered" if n_trig else "", f"👀 {len(rows) - n_trig} new setups" if len(rows) > n_trig else ""]
    return "EW alerts: " + " · ".join(p for p in parts if p)


def messages(todays: list[dict], fresh: list[dict], split: bool) -> list[tuple[str, str, list[dict]]]:
    """
    What a scan sends, as (category, title, events): category "TRIGGERED" / "NEW" / "ALL".

    split=True: one message for Triggered and one for New setups, each listing the whole
    day of its category, sent only for a category with events not notified before.
    split=False: one message listing the whole day.
    Each event comes back as a copy with "_new" (not notified before), sorted by sort_key.
    """
    if not fresh:
        return []
    new_ids = {_ident(e) for e in fresh}
    rows = sorted(({**h, "_new": _ident(h) in new_ids} for h in todays), key=sort_key)
    if not split:
        return [("ALL", title_for("ALL", rows), rows)]
    out = []
    for kind, _label in CATEGORIES:
        day = [h for h in rows if h["event"] == kind]
        if any(h["_new"] for h in day):
            out.append((kind, title_for(kind, day), day))
    return out


# ---- readable layouts -------------------------------------------------------------
def price(v: Any) -> str:
    """1,298.5 · 1,312 · 45.20: no trailing zeros on larger prices."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    v = float(v)
    text = f"{v:,.2f}"
    return text if abs(v) < 100 else text.rstrip("0").rstrip(".")


def _pct(a: Any, b: Any) -> str:
    try:
        a, b = float(a), float(b)
        return f"{abs(a - b) / abs(b) * 100:.1f}%" if b else ""
    except (TypeError, ValueError):
        return ""


def _side(e: dict) -> str:
    return {"LONG": "🟢", "SHORT": "🔴"}.get(e.get("side"), "•")


def _align(e: dict, words: bool = True) -> str:
    a = e.get("alignment")
    icon = ALIGN_ICON.get(a, "")
    return f"{icon} {str(a).lower()}" if icon and words else icon


def _chart(e: dict) -> str:
    """📈 60m chart: opens TradingView at the signal's timeframe (every stock that TradingView has)."""
    url = tradingview_url(e.get("ticker"), e.get("tf"))
    return f'<a href="{html.escape(url)}">📈 {html.escape(str(e.get("tf") or ""))} chart</a>' if url else ""


def _levels(e: dict) -> str:
    """Triggered: entry and stop with the risk. New setup: where it triggers, how far, and the stop."""
    stop = price(e.get("stop"))
    if e.get("event") == "TRIGGERED":
        entry = e.get("entry") or e.get("trigger")
        return f"Entry {price(entry)} · SL {stop} ({_pct(entry, e.get('stop'))})"
    verb = "Buy above" if e.get("side") == "LONG" else "Sell below"
    away = _pct(e.get("trigger"), e.get("close"))
    return f"{verb} {price(e.get('trigger'))}" + (f" ({away} away)" if away else "") + f" · SL {stop}"


def card(e: dict) -> str:
    """One stock as a short block: who and which way, what, the levels, the targets."""
    esc = lambda v: html.escape(str(v or ""))                                          # noqa: E731
    what = [e.get("tf"), str(e.get("strategy", "")).upper(), e.get("degree"),
            CONTEXT_TEXT.get(e.get("context") or "", ""), f"at {str(e.get('at', ''))[11:16]}"]
    targets = [price(e.get(k)) for k in ("target1", "target2") if price(e.get(k))]
    last = " · ".join(x for x in ["🎯 " + " → ".join(targets) if targets else "", _chart(e)] if x)
    lines = [f"{_side(e)} <b>{esc(e.get('side'))}  {esc(_symbol(e))}</b>  {_align(e)}",
             esc(" · ".join(str(x) for x in what if x)), esc(_levels(e))]
    return "\n".join(lines + ([last] if last else []))


def compact(e: dict, mark_new: bool = False) -> str:
    """One stock on one line."""
    esc = lambda v: html.escape(str(v or ""))                                          # noqa: E731
    bits = [f"{e.get('tf')} {str(e.get('strategy', '')).upper()}", _levels(e)]
    return (("🆕 " if mark_new and e.get("_new") else "") + f"{_side(e)} <b>{esc(e.get('side'))} {esc(_symbol(e))}</b> · "
            + esc(" · ".join(bits)) + (f" {_align(e, words=False)}" if _align(e, words=False) else "")
            + (f" · {_chart(e)}" if _chart(e) else ""))


def _day(rows: list[dict]) -> str:
    try:
        return pd.Timestamp(str(rows[0].get("at", ""))[:10]).strftime("%a %d %b")
    except (ValueError, IndexError):
        return ""


def _section(rows: list[dict], style: str) -> list[str]:
    """New since the last scan in full; stocks already sent today, one line each."""
    new = [e for e in rows if e.get("_new", True)]
    old = [e for e in rows if not e.get("_new", True)]
    blocks: list[str] = []
    if old and new:
        since = max(str(e.get("notified", ""))[11:16] for e in old)
        blocks.append(f"🆕 <b>New since {since}</b>" if since else "🆕 <b>New</b>")
    if style == "cards":
        blocks += [card(e) for e in new]
    elif new:
        blocks.append("\n".join(compact(e) for e in new))
    if old:
        blocks.append("<b>Earlier today</b>\n" + "\n".join(compact(e) for e in old))
    return blocks


def _pack(head: str, blocks: list[str]) -> list[str]:
    """Blocks into messages under Telegram's limit, never cutting a block in two."""
    pieces = []
    for block in blocks:                        # a long list of one-line stocks may itself be too long
        if len(block) + len(head) + 20 <= TELEGRAM_LIMIT:
            pieces.append(block)
            continue
        chunk = ""
        for line in block.split("\n"):
            if chunk and len(chunk) + len(line) + len(head) + 20 > TELEGRAM_LIMIT:
                pieces.append(chunk)
                chunk = ""
            chunk = f"{chunk}\n{line}" if chunk else line
        pieces.append(chunk)
    out, current = [], head
    for block in pieces:
        if len(current) + len(block) + 2 > TELEGRAM_LIMIT and current != head:
            out.append(current)
            current = head + " (continued)"
        current += "\n\n" + block
    out.append(current)
    return out


def render(category: str, title: str, rows: list[dict], settings: Optional[dict] = None) -> list[str]:
    """The Telegram message(s) for one category ("TRIGGERED" / "NEW" / "ALL") in the chosen layout."""
    s = {**TEMPLATE_DEFAULTS, **(settings or {})}
    style = s.get("telegram_style", "cards")
    rows = sorted(rows, key=sort_key)
    if style == "custom":
        return telegram_text(title, rows, s)
    n_trig = sum(e.get("event") == "TRIGGERED" for e in rows)
    day = _day(rows)
    if category == "TRIGGERED":
        head = f"⚡ <b>TRIGGERED</b> · {day} · {len(rows)} stock{'s' if len(rows) != 1 else ''}"
        return _pack(head, _section(rows, style))
    if category == "NEW":
        head = f"👀 <b>NEW SETUPS</b> · {day} · {len(rows)} stock{'s' if len(rows) != 1 else ''}"
        return _pack(head, _section(rows, style))
    head = f"📋 <b>EW ALERTS</b> · {day} · {n_trig} triggered · {len(rows) - n_trig} new setups"
    blocks = []
    for kind, label in (("TRIGGERED", "⚡ <b>TRIGGERED</b>"), ("NEW", "👀 <b>NEW SETUPS</b>")):
        part = [e for e in rows if e.get("event") == kind]
        if part:
            blocks += [f"{label} ({len(part)})"] + _section(part, style)
    return _pack(head, blocks)


def preview_texts(events: list[dict], settings: dict, prefix: str = "") -> list[tuple[str, list[str]]]:
    """(title, Telegram messages) for each message a scan would send if all of events were new."""
    return [(prefix + title, render(kind, prefix + title, rows, settings))
            for kind, title, rows in messages(events, events, settings.get("split_messages", True))]


def send_test(settings: dict) -> str:
    """The two example stocks, sent as a scan would send them (one or two messages)."""
    for kind, title, rows in messages(SAMPLE, SAMPLE, settings.get("split_messages", True)):
        result = send_telegram(settings, "Test · " + title, rows, kind)
        if result != "sent":
            return result
    return "sent"


def notification_lines(rows: list[dict]) -> list[str]:
    """The notification's lines; 🆕 marks the new stocks only when earlier ones are listed too."""
    mixed = any(e.get("_new", True) for e in rows) and not all(e.get("_new", True) for e in rows)
    return [notification_line(e if mixed else {**e, "_new": False}) for e in rows]


def notification_line(e: dict) -> str:
    """One stock in the phone / Mac notification: 🆕 🔴 RELIANCE SHORT 60m EW5 · SL 1,312 ✅"""
    level = (f"SL {price(e.get('stop'))}" if e.get("event") == "TRIGGERED"
             else f"{'above' if e.get('side') == 'LONG' else 'below'} {price(e.get('trigger'))} · SL {price(e.get('stop'))}")
    return (("🆕 " if e.get("_new") else "") + f"{_side(e)} {_symbol(e)} {e.get('side', '')} {e.get('tf', '')} "
            f"{str(e.get('strategy', '')).upper()} · {level}" + (f" {_align(e, False)}" if _align(e, False) else ""))


# public names
event_rows = _event_rows
line = notification_line
