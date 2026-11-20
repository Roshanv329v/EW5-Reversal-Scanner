"""
F&O 5-day eligibility: which EW5 / EW3 signals are worth a short F&O trade of at most five
trading days, graded A (eligible) / B (possible) / "–" (not eligible), with the reason.

The trade the grades were measured on (config.yaml -> fno_5day):
    entry   the signal's entry (TRIGGER until it has triggered)
    stop    STOP
    target  the strategy's first target (EW5 W4_END, EW3 W1_END)
    exit    stop or target, whichever comes first; otherwise the close of the 5th trading day
            (the trigger day counts as day 1)

Rules come from simulating every triggered signal of the 11 May - 11 Nov 2026 backtests on
60m bars this way, and keeping only rules that gained in BOTH halves of that period. Shared
by the dashboards and the alerts on the desktop and the phone.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

COLUMNS = ("fno5", "fno5_reason", "fno5_rr", "fno5_stop_pct")
NOT = "–"                                       # not eligible
GRADES = ("A", "B")
LABEL = {"A": "A · eligible", "B": "B · possible", NOT: "not eligible"}


def _num(s: Any) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def measures(res: pd.DataFrame, S) -> pd.DataFrame:
    """stop % (entry → stop), reward : risk to the first target, price vs the 55 EMA (%)."""
    entry = _num(res["entry_price"]) if "entry_price" in res.columns else pd.Series(np.nan, index=res.index)
    entry = entry.where(entry.notna(), _num(res["TRIGGER"]))
    stop = _num(res["STOP"])
    (_, t1), _ = S.target_cards
    target = _num(res[t1]) if t1 in res.columns else pd.Series(np.nan, index=res.index)
    risk = (entry - stop).abs()
    out = pd.DataFrame(index=res.index)
    out["stop_pct"] = risk / entry.abs() * 100
    out["rr"] = (target - entry).abs() / risk.replace(0, np.nan)
    ema = _num(res["55_ema"]) if "55_ema" in res.columns else pd.Series(np.nan, index=res.index)
    out["ema_gap"] = ((_num(res["close"]) - ema) / ema * 100).abs()
    return out


def _passes(res: pd.DataFrame, m: pd.DataFrame, rule: dict) -> tuple[pd.Series, pd.Series]:
    """Rows that meet every condition of a grade's rule, and the first failed condition (text)."""
    ok = pd.Series(True, index=res.index)
    why = pd.Series("", index=res.index, dtype=object)

    def need(mask: pd.Series, text: Any) -> None:
        nonlocal ok
        mask = mask.fillna(False)
        fail = ok & ~mask
        why[fail] = text if isinstance(text, str) else text[fail]
        ok &= mask

    if rule.get("degree"):
        need(res["degree"].isin(rule["degree"]), "degree " + res["degree"].astype(str) + " (needs "
             + "/".join(rule["degree"]) + ")")
    if rule.get("not_alignment") and "alignment" in res.columns:
        need(~res["alignment"].isin(rule["not_alignment"]), "against the higher timeframes")
    if rule.get("max_stop_pct") is not None:
        need(m["stop_pct"] <= float(rule["max_stop_pct"]),
             "stop " + m["stop_pct"].round(1).astype(str) + "% > " + str(rule["max_stop_pct"]) + "%")
    if rule.get("min_rr") is not None:
        need(m["rr"] >= float(rule["min_rr"]),
             "target " + m["rr"].round(1).astype(str) + "× risk < " + str(rule["min_rr"]) + "×")
    if rule.get("max_ema55_gap_pct") is not None:
        need(m["ema_gap"] <= float(rule["max_ema55_gap_pct"]),
             "price " + m["ema_gap"].round(1).astype(str) + "% from the 55 EMA > "
             + str(rule["max_ema55_gap_pct"]) + "%")
    return ok, why


def assess(res: pd.DataFrame, S, cfg: dict) -> pd.DataFrame:
    """
    The four COLUMNS added to signal rows (stock attributes must be attached for the F&O check):
    fno5 "A" / "B" / "–", fno5_reason (what makes it A / B, or the first thing that fails),
    fno5_rr (first target in multiples of the risk) and fno5_stop_pct.
    """
    out = res.drop(columns=[c for c in COLUMNS if c in res.columns])
    if res.empty:
        for col in COLUMNS:
            out[col] = pd.Series(dtype=object)
        return out
    rules = (cfg or {}).get(S.key, {})
    m = measures(res, S)
    grade = pd.Series(NOT, index=res.index, dtype=object)
    reason = pd.Series("", index=res.index, dtype=object)
    for name in ("B", "A"):                                   # A overrides B
        rule = rules.get(name)
        if not rule:
            continue
        ok, why = _passes(res, m, rule)
        grade[ok] = name
        reason[ok] = rule.get("why", "")
        if name == "B" or "B" not in rules:                   # reason of the loosest grade for the rest
            reason[~ok & grade.eq(NOT)] = why[~ok & grade.eq(NOT)]
    if (cfg or {}).get("fno_only", True) and "fno_enabled" in res.columns:
        not_fno = ~res["fno_enabled"].astype(str).eq("true")
        grade[not_fno] = NOT
        reason[not_fno] = "not an F&O stock"
    out["fno5"] = grade
    out["fno5_reason"] = reason
    out["fno5_rr"] = m["rr"].round(2)
    out["fno5_stop_pct"] = m["stop_pct"].round(2)
    return out


def exit_by(start: Any, days: int = 5) -> Optional[pd.Timestamp]:
    """The last day of a trade entered on `start`, held at most `days` trading days (Mon-Fri)."""
    if start is None or pd.isna(start):
        return None
    day = np.datetime64(pd.Timestamp(start).date(), "D")
    first = np.busday_offset(day, 0, roll="forward")
    return pd.Timestamp(np.busday_offset(first, days - 1, roll="forward"))


def summary(cfg: dict) -> list[str]:
    """One line per strategy and grade (for the dashboards' and the alerts' help text)."""
    out = []
    for key in ("ew5", "ew3"):
        for name in ("A", "B"):
            rule = ((cfg or {}).get(key) or {}).get(name)
            if rule:
                out.append(f"{key.upper()} {name}: {rule.get('why', '')} · backtest {rule.get('backtest', '')}")
    return out
