"""Per-condition summaries of a session's steps.

Following FR-09, a session spanning several speeds is never reduced to one blended
average: each condition block gets its own median and interquartile range, from
accepted steps only. Transition steps (the speed changed mid-step) are counted but
excluded.
"""

from __future__ import annotations

import statistics
from typing import Any


def _spread(values: list[float], digits: int) -> dict[str, float | None]:
    if not values:
        return {"median": None, "q1": None, "q3": None}
    if len(values) < 4:
        m = round(statistics.median(values), digits)
        return {"median": m, "q1": None, "q3": None}
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {"median": round(median, digits), "q1": round(q1, digits), "q3": round(q3, digits)}


def summarize_block(steps: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [s for s in steps if s["accepted"]]
    return {
        "steps_total": len(steps),
        "steps_accepted": len(accepted),
        "transitions": sum(1 for s in steps if s["transition"]),
        "low_confidence": sum(1 for s in steps if s["confidence"] == "low"),
        "unavailable": sum(1 for s in steps if s["confidence"] == "unavailable"),
        "running_steps": sum(1 for s in accepted if s["running"]),
        # From strides (two steps), so a limp's unequal left and right steps cancel out.
        "cadence_spm": _spread(
            [120.0 / s["stride_time_s"] for s in accepted if s["stride_time_s"]]
            or [60.0 / s["step_time_s"] for s in accepted if s["step_time_s"]],
            1,
        ),
        "step_length_m": _spread([s["step_length_m"] for s in accepted if s["step_length_m"] is not None], 3),
        "stride_length_m": _spread(
            [s["stride_length_m"] for s in accepted if s["stride_length_m"] is not None], 3
        ),
        "step_time_s": _spread([s["step_time_s"] for s in accepted], 3),
    }


def summarize(steps: list[dict[str, Any]], conditions: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = []
    for condition in conditions:
        mine = [s for s in steps if s["condition_id"] == condition["id"]]
        blocks.append({"condition": condition, **summarize_block(mine)})
    walking_s = sum(s["step_time_s"] for s in steps if s["accepted"])
    distance_m = sum(s["step_length_m"] for s in steps if s["step_length_m"] is not None)
    main = max(blocks, key=lambda b: b["steps_accepted"], default=None)
    return {
        "blocks": blocks,
        "steps_total": len(steps),
        "steps_accepted": sum(1 for s in steps if s["accepted"]),
        "walking_s": round(walking_s, 1),
        "distance_m": round(distance_m, 1),
        # The block with the most accepted steps: what the session list shows.
        "main_condition_id": main["condition"]["id"] if main and main["steps_accepted"] else None,
    }
