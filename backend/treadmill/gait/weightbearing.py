"""How much weight each leg is taking, against what the surgeon allowed.

After lower-limb surgery a patient is told something like "no more than 20 kg
on that leg for six weeks". They cannot feel kilograms through a foot, and the
evidence is that they do not come close: in fifty knee-replacement patients,
compliance was 0% on the first post-operative day and 2% at discharge, with
84-92% exceeding the limit on *every step*. Shown the number live, overloading
fell to under 9% of steps.

That is what this measures, and it needs no force decomposition.

For roughly 80% of each step one foot is in the air, and an airborne foot
carries nothing -- so during that window the deck's total reading *is* the
standing leg's load, measured rather than estimated. The peak of a step falls
inside that window. So: ask the step detector whose foot is down, take the peak
of the total force until the other foot lands, and that is this leg's peak load
for this step.

The method needs a real single-support interval, and that is exactly what some
patients do not give. Measured across three subjects over 1-12 km/h, the force
between steps falls to 5-13% below the peak at 1 km/h -- both feet are down
essentially all the time and no leg can be isolated -- rising through 20-43% at
2-4 km/h to a clean 100% once the patient is running and the deck empties
between steps. Below `MIN_SEPARATION` this reports the combined load for both
legs and says why, rather than splitting a number it cannot split.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

#: How far the load must fall between steps, as a fraction of the step's peak,
#: before the two legs can be told apart. Below this the feet overlap
#: continuously. Measured: 1 km/h gives 5-13%, 2 km/h 20-30%, 4 km/h 34-41%,
#: 5 km/h and above 46%+, running 100%.
MIN_SEPARATION = 0.25

#: Enough steps to say anything at all, and how many to average over. Medians,
#: so one stumble does not move the reported figure.
MIN_STEPS = 6
WINDOW_STEPS = 20

#: A step's peak must clear this fraction of body weight to be a real stance
#: rather than a toe brushing the deck.
MIN_PEAK_FRACTION = 0.15

#: Steps longer than this are a pause, not a stride; the peak between them
#: belongs to no single stance.
MAX_STEP_S = 2.0


class Quality(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    COMBINED = "combined"      # one number for both legs; they cannot be separated
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StepLoad:
    """One step's peak load, and the leg that carried it."""
    t: float
    side: str                  # "L" or "R"
    peak_kg: float
    trough_kg: float           # lowest load before the next step landed
    over_limit: bool

    def as_dict(self) -> dict[str, Any]:
        return {"t": round(self.t, 3), "side": self.side,
                "peak_kg": round(self.peak_kg, 2), "over_limit": self.over_limit}


@dataclass(frozen=True, slots=True)
class WeightBearing:
    quality: Quality
    reason: str
    #: Median peak over the recent window, per leg. None when not separable.
    left_kg: float | None
    right_kg: float | None
    #: Always available: the peak load the deck saw, whichever leg took it.
    combined_kg: float | None
    body_weight_kg: float | None
    limit_kg: float | None
    #: Steps counted since the session began, and how many exceeded the limit.
    steps: int
    steps_over: int
    #: How cleanly the legs separate, 0-1. The reason this can fail.
    separation: float

    def as_dict(self) -> dict[str, Any]:
        def pct(v: float | None) -> float | None:
            if v is None or not self.body_weight_kg:
                return None
            return round(100 * v / self.body_weight_kg, 1)
        return {
            "quality": self.quality.value,
            "reason": self.reason,
            "left_kg": None if self.left_kg is None else round(self.left_kg, 1),
            "right_kg": None if self.right_kg is None else round(self.right_kg, 1),
            "combined_kg": None if self.combined_kg is None else round(self.combined_kg, 1),
            "left_pct_bw": pct(self.left_kg),
            "right_pct_bw": pct(self.right_kg),
            "combined_pct_bw": pct(self.combined_kg),
            "body_weight_kg": self.body_weight_kg,
            "limit_kg": self.limit_kg,
            "steps": self.steps,
            "steps_over": self.steps_over,
            "separation": round(self.separation, 3),
        }


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


class WeightBearingTracker:
    """Fed every sample and every detected step; reports the current picture.

    Body weight comes from the patient's record, never from the deck. A patient
    leaning on the handrails puts part of their weight through their arms, which
    is a real reduction in leg load and should be measured as such -- but it
    would make a deck-derived body weight too low, and then every percentage
    would be wrong in the flattering direction.
    """

    def __init__(self, body_weight_kg: float | None = None,
                 limit_kg: float | None = None) -> None:
        self.body_weight_kg = body_weight_kg
        self.limit_kg = limit_kg
        self.steps: list[StepLoad] = []
        self._recent: deque[StepLoad] = deque(maxlen=WINDOW_STEPS)
        self._open: tuple[float, str] | None = None     # (t, side) of the live stance
        self._peak = 0.0
        self._trough = float("inf")
        self._latest = 0.0

    # ---- feeding -----------------------------------------------------------

    def on_sample(self, t: float, total_kg: float) -> None:
        self._latest = total_kg
        if self._open is None:
            return
        if total_kg > self._peak:
            self._peak = total_kg
        # The trough only counts once the peak is behind us: the load rising
        # from the previous step's handover is not this step's unloading.
        if self._peak > 0 and total_kg < self._trough:
            self._trough = total_kg

    def on_step(self, t: float, side: str) -> StepLoad | None:
        """A foot has landed. Closes the previous stance and opens a new one."""
        closed = self._close(t)
        self._open = (t, side)
        self._peak = 0.0
        self._trough = float("inf")
        return closed

    def _close(self, t: float) -> StepLoad | None:
        if self._open is None:
            return None
        t0, side = self._open
        self._open = None
        if t - t0 > MAX_STEP_S:
            return None                       # a pause, not a stride
        floor = MIN_PEAK_FRACTION * (self.body_weight_kg or 1.0)
        if self._peak <= floor:
            return None                       # nobody really stood on it
        trough = 0.0 if self._trough == float("inf") else max(0.0, self._trough)
        step = StepLoad(
            t=t0, side=side, peak_kg=self._peak, trough_kg=trough,
            over_limit=self.limit_kg is not None and self._peak > self.limit_kg,
        )
        self.steps.append(step)
        self._recent.append(step)
        return step

    # ---- reporting ---------------------------------------------------------

    def state(self) -> WeightBearing:
        recent = list(self._recent)
        over = sum(1 for s in self.steps if s.over_limit)
        base = dict(body_weight_kg=self.body_weight_kg, limit_kg=self.limit_kg,
                    steps=len(self.steps), steps_over=over)

        if len(recent) < MIN_STEPS:
            return WeightBearing(
                Quality.UNAVAILABLE,
                "Waiting for a few steps.",
                None, None, None, separation=0.0, **base)

        peaks = [s.peak_kg for s in recent]
        combined = _median(peaks)
        # How far the load falls between steps, as a fraction of the peak. This
        # is the whole question: no fall means both feet are always down.
        separation = max(0.0, 1.0 - _median([s.trough_kg for s in recent]) / combined) if combined else 0.0

        if separation < MIN_SEPARATION:
            return WeightBearing(
                Quality.COMBINED,
                "Both feet are on the deck almost all the time, so the legs "
                "cannot be told apart. Showing the load through both.",
                None, None, combined, separation=separation, **base)

        left = [s.peak_kg for s in recent if s.side == "L"]
        right = [s.peak_kg for s in recent if s.side == "R"]
        if len(left) < 2 or len(right) < 2:
            return WeightBearing(
                Quality.COMBINED,
                "Only one leg is landing cleanly. Showing the load through both.",
                None, None, combined, separation=separation, **base)

        quality = Quality.GOOD if separation >= 0.40 else Quality.FAIR
        reason = "" if quality is Quality.GOOD else (
            "The feet overlap for much of each step, so the split between them "
            "is approximate.")
        return WeightBearing(quality, reason, _median(left), _median(right),
                             combined, separation=separation, **base)

    def finish(self, t: float) -> None:
        """Close the last stance when the session ends."""
        self._close(t)

    def summary(self) -> dict[str, Any]:
        """What goes in the session record."""
        s = self.state()
        out = s.as_dict()
        left = [x.peak_kg for x in self.steps if x.side == "L"]
        right = [x.peak_kg for x in self.steps if x.side == "R"]
        out["session"] = {
            "steps": len(self.steps),
            "steps_over": sum(1 for x in self.steps if x.over_limit),
            "left_median_kg": round(_median(left), 2) if left else None,
            "right_median_kg": round(_median(right), 2) if right else None,
            "left_max_kg": round(max(left), 2) if left else None,
            "right_max_kg": round(max(right), 2) if right else None,
            "combined_max_kg": round(max(x.peak_kg for x in self.steps), 2) if self.steps else None,
        }
        return out
