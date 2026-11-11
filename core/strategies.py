"""
What differs between the two screeners, in one place.

    EW5 - wave 5 reversal        (elliott_wave5_screener.py)
    EW3 - wave 2 finished / wave 3 starting   (elliott_wave3_screener.py)

The runner, the charts and the dashboard read everything strategy-specific from a
`Strategy`: column names, levels, targets, stat cards, chart groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import pandas as pd

import elliott_wave3_screener as ew3
import elliott_wave5_screener as ew5
from core import charts
from core.charts import C


@dataclass(frozen=True)
class Strategy:
    key: str                                   # "ew5" / "ew3"
    name: str                                  # short name shown in pickers
    tab: str                                   # tab label (with icon)
    blurb: str                                 # one line under the dashboard heading
    file_prefix: str                           # results file prefix ("" keeps the EW5 names)
    side_col: str                              # column holding LONG / SHORT
    levels_col: str                            # list column with "NAME=value" strings
    level_names: tuple[str, ...]
    targets: tuple[str, ...]                   # levels that have hit_<name> outcome columns
    stages: tuple[str, ...]
    fail_status: str                           # status when the idea died before the trigger
    fail_card: tuple[str, str]                 # (label, tooltip)
    target_cards: tuple[tuple[str, str], ...]  # two (label, level) pairs shown as hit-rate cards
    level_groups: dict[str, list[tuple[str, str, str]]]
    level_labels: dict[str, str]
    wave_name: str                             # legend name of the wave line
    ratio_col: str                             # column behind the range slider
    filter_cols: tuple[tuple[str, str], ...]   # (column, label) of the dashboard filters
    table_cols: tuple[str, ...]
    fact_levels: tuple[tuple[str, str], ...]   # (label, level) in the overlay caption
    prefs_file_key: str                        # config key of the saved-filters file
    summarize: Callable[[pd.DataFrame], pd.DataFrame] = field(repr=False, default=lambda r: r)
    chart_title: Callable[[pd.Series], str] = field(repr=False, default=lambda row: "")
    overlay_from_row: Optional[Callable[[pd.Series], Optional[dict]]] = field(repr=False, default=None)

    # ---------------------------------------------------------------- stats
    def stat_masks(self, res: pd.DataFrame) -> dict[str, pd.Series]:
        """Rows behind each stat card (hit / stop / MFE / MAE cards are subsets of triggered)."""
        trig = res["status"].eq("TRIGGERED")
        avg_mfe, avg_mae = res.loc[trig, "mfe_pct"].mean(), res.loc[trig, "mae_pct"].mean()
        (_, level1), (_, level2) = self.target_cards
        return {
            "triggered": trig,
            "failed": res["status"].eq(self.fail_status),
            "t1": trig & res[f"hit_{level1}"].astype(bool),
            "t2": trig & res[f"hit_{level2}"].astype(bool),
            "stopped": trig & res["stopped"].astype(bool),
            "mfe": trig & (res["mfe_pct"] >= avg_mfe),
            "mae": trig & (res["mae_pct"] <= avg_mae),
        }

    def kpis(self, res: pd.DataFrame) -> dict[str, float]:
        """Headline numbers. Hit and stop rates are out of triggered signals."""
        masks = self.stat_masks(res)
        n, n_trig = len(res), int(masks["triggered"].sum())
        trig = res[masks["triggered"]]

        def pct(count: float, total: float) -> float:
            return float(count) / float(total) * 100 if total else float("nan")

        return {
            "signals": n,
            "trigger_rate": pct(n_trig, n),
            "fail_pct": pct(masks["failed"].sum(), n),
            "t1_hit_rate": pct(masks["t1"].sum(), n_trig),
            "t2_hit_rate": pct(masks["t2"].sum(), n_trig),
            "stop_rate": pct(masks["stopped"].sum(), n_trig),
            "avg_mfe": float(trig["mfe_pct"].mean()) if n_trig else float("nan"),
            "avg_mae": float(trig["mae_pct"].mean()) if n_trig else float("nan"),
        }


# ----------------------------------------------------------------------------------
# EW5 - wave 5 reversal
# ----------------------------------------------------------------------------------
EW5 = Strategy(
    key="ew5", name="EW5 · Wave 5 reversal", tab=":material/monitoring: EW5",
    blurb="Wave 5 reversal: the latest impulse is at or just past wave 5; trade against it.",
    file_prefix="", side_col="reversal_side", levels_col="reversal_levels",
    level_names=ew5.LEVEL_NAMES,
    targets=("W4_END", "FIB_0.500", "FIB_0.618", "FIB_0.764", "FIB_0.854"),
    stages=(ew5.STAGE_IN_PROGRESS, ew5.STAGE_COMPLETED),
    fail_status="EXTENDED",
    fail_card=(":material/trending_up: Extended", "Wave 5 made a new extreme before the trigger"),
    target_cards=((":material/flag: W4 target hit", "W4_END"), (":material/target: FIB 0.5 hit", "FIB_0.500")),
    level_groups=charts.LEVEL_GROUPS, level_labels={"STOP": "STOP / W5_END"},
    wave_name="Impulse 1-5", ratio_col="w5_vs_w1",
    filter_cols=(("time_frame", "Timeframe"), ("degree", "Degree"), ("reversal_side", "Side"),
                 ("stage", "Stage"), ("status", "Status"), ("result", "Result")),
    table_cols=("Ticker", "time_frame", "degree", "reversal_side", "stage", "signal_time", "close",
                "w5_end_price", "bars_since_w5", "w5_vs_w1", "status", "result", "entry_price",
                "mfe_pct", "mae_pct", "first_target_hit", "TRIGGER", "STOP", "W4_END"),
    fact_levels=(("Trigger", "TRIGGER"), ("Stop", "STOP"), ("W4 end", "W4_END")),
    prefs_file_key="dashboard_filters_file",
    summarize=ew5.summarize_backtest,
    chart_title=lambda row: (f"{row['Ticker']} · {row['time_frame']} · {row.get('degree', '')} · "
                             f"{row.get('impulse', '')} impulse → {row.get('reversal_side', '')} reversal"),
)


# ----------------------------------------------------------------------------------
# EW3 - wave 2 finished / wave 3 starting
# ----------------------------------------------------------------------------------
def _ew3_overlay(row: pd.Series) -> Optional[dict]:
    """Wave points 0-1-2 straight from the signal row (no engine re-run needed)."""
    points = [(row.get("w0_time"), row.get("W0_START")), (row.get("w1_end_time"), row.get("W1_END")),
              (row.get("w2_end_time"), row.get("W2_END"))]
    if any(pd.isna(t) or pd.isna(y) for t, y in points):
        return None
    return {"dir": 1 if row.get("trade_side") == "LONG" else -1,
            "pts": [(pd.Timestamp(t), float(y)) for t, y in points], "abc": []}


EW3 = Strategy(
    key="ew3", name="EW3 · Wave 3 start", tab=":material/rocket_launch: EW3",
    blurb="Wave 3 start: waves 1 and 2 are in place and wave 2 has finished; trade with the new trend.",
    file_prefix="ew3_", side_col="trade_side", levels_col="wave_levels",
    level_names=ew3.LEVEL_NAMES, targets=ew3.TARGETS, stages=ew3.STAGES,
    fail_status="FAILED",
    fail_card=(":material/trending_down: Failed", "Price went beyond the wave-2 end before the trigger"),
    target_cards=((":material/flag: W1 end hit", "W1_END"), (":material/target: W3 1.618 hit", "W3_TGT_1.618xW1")),
    level_groups={
        "Trigger / Stop": [("TRIGGER", C["orange"], "solid"), ("STOP", C["critical"], "solid")],
        "Wave 0 / 1": [("W0_START", C["muted"], "dash"), ("W1_END", C["yellow"], "dash")],
        "W2 retracement": [(n, C["ink2"], "dot") for n in
                           ("W2_RET_0.382", "W2_RET_0.500", "W2_RET_0.618", "W2_RET_0.786")],
        "W3 targets": [(n, C["muted"], "dashdot") for n in
                       ("W3_TGT_1.000xW1", "W3_TGT_1.618xW1", "W3_TGT_2.618xW1")],
    },
    level_labels={"STOP": "STOP / W2_END", "W0_START": "W0_START (invalid beyond)"},
    wave_name="Waves 0-1-2", ratio_col="w2_retrace",
    filter_cols=(("time_frame", "Timeframe"), ("degree", "Degree"), ("trade_side", "Side"),
                 ("stage", "Stage"), ("context", "Context"), ("status", "Status"), ("result", "Result")),
    table_cols=("Ticker", "time_frame", "degree", "trade_side", "stage", "context", "signal_time", "close",
                "w2_end_price", "bars_since_w2", "w2_retrace", "status", "result", "entry_price",
                "mfe_pct", "mae_pct", "first_target_hit", "TRIGGER", "STOP", "W1_END", "W3_TGT_1.618xW1"),
    fact_levels=(("Trigger", "TRIGGER"), ("Stop", "STOP"), ("W1 end", "W1_END"),
                 ("W3 1.618", "W3_TGT_1.618xW1")),
    prefs_file_key="dashboard_filters_file_ew3",
    summarize=ew3.summarize_backtest,
    chart_title=lambda row: (f"{row['Ticker']} · {row['time_frame']} · {row.get('degree', '')} · "
                             f"{row.get('impulse', '')} waves 1-2 → {row.get('trade_side', '')} wave 3"
                             f" · {row.get('context', '')}"),
    overlay_from_row=_ew3_overlay,
)

STRATEGIES: dict[str, Strategy] = {"ew5": EW5, "ew3": EW3}


def get(key: Any) -> Strategy:
    return STRATEGIES.get(str(key or "ew5"), EW5)
