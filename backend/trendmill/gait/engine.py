"""Cadence, step length and stride length from the top-left and top-right cells.

See docs/design.md, section 6. In short:

* F = TL + TR is the front load; D = TR - TL, minus its slow drift, is the lateral
  balance of that load.
* Each step moves load to the new foot's side, so D swings through zero: a swing
  past +h marks a right contact, past -h a left contact, with hysteresis
  h = 0.35 x A, where A is half the 5th-95th percentile range of D over 4 s. The
  contact time is the zero crossing just before the swing.
* Step length is the belt distance between opposite-foot contacts; stride length
  the distance between same-foot contacts. Both integrate the speed timeline, so
  they stay right when the speed changes mid-step.
* Cadence is 120 / median stride time, so unequal left and right steps cancel.
* Every step is checked (alternation, timing, signal strength, known speed) and
  graded high / medium / low / unavailable. Only high and medium count; nothing is
  shown until three have been accepted.

Everything is in kilograms from the calibration in use, so every threshold means
the same thing on every deck.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from trendmill.gait.filters import butterworth_delay_s, butterworth_lowpass
from trendmill.gait.speed import SpeedTimeline

US_PER_S = 1_000_000
HIGH, MEDIUM, LOW, UNAVAILABLE = "high", "medium", "low", "unavailable"
_RANK = {HIGH: 3, MEDIUM: 2, LOW: 1, UNAVAILABLE: 0}


@dataclass(frozen=True)
class GaitConfig:
    version: str = "gait-engine 1.0.0"
    #: Signals are low-passed, then processed at about this rate.
    target_rate_hz: float = 250.0
    lowpass_hz: float = 12.0
    lateral_baseline_s: float = 3.0
    amplitude_window_s: float = 4.0
    amplitude_update_s: float = 0.25
    hysteresis: float = 0.35
    #: Someone is on the front of the deck, and swinging side to side.
    min_front_kg: float = 5.0
    min_amplitude_kg: float = 1.0
    min_belt_kph: float = 0.36  # 0.1 m/s
    min_step_s: float = 0.20
    max_step_s: float = 2.0
    refractory_fraction: float = 0.4
    median_tolerance: float = 0.4
    #: Lateral swing relative to this condition's own baseline.
    weak_fraction: float = 0.4
    medium_fraction: float = 0.6
    rolling_steps: int = 8
    rolling_strides: int = 4
    min_steps_to_show: int = 3
    show_for_s: float = 3.0
    #: Flight phase: front load under this fraction of its recent peak, for this long.
    flight_fraction: float = 0.10
    flight_min_s: float = 0.04
    running_after_steps: int = 4


@dataclass(frozen=True)
class Step:
    t_us: int
    side: str  # "L" or "R": the foot that just landed
    step_time_s: float
    step_length_m: float | None
    stride_time_s: float | None
    stride_length_m: float | None
    speed_kph: float | None
    confidence: str
    reasons: tuple[str, ...]
    transition: bool
    running: bool
    condition_id: int
    amplitude_kg: float

    @property
    def accepted(self) -> bool:
        return self.confidence in (HIGH, MEDIUM) and not self.transition

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        d["accepted"] = self.accepted
        return d


@dataclass
class _Contact:
    t_us: int
    side: str


@dataclass
class GaitCounters:
    contacts: int = 0
    steps: int = 0
    accepted: int = 0
    by_confidence: dict[str, int] = field(
        default_factory=lambda: {HIGH: 0, MEDIUM: 0, LOW: 0, UNAVAILABLE: 0}
    )


class GaitEngine:
    def __init__(self, sample_rate_hz: float, speed: SpeedTimeline, config: GaitConfig | None = None) -> None:
        self.config = cfg = config or GaitConfig()
        self.speed = speed
        self._decimate = max(1, int(sample_rate_hz // cfg.target_rate_hz))
        self._lp_tl = butterworth_lowpass(sample_rate_hz, cfg.lowpass_hz)
        self._lp_tr = butterworth_lowpass(sample_rate_hz, cfg.lowpass_hz)
        self._delay_us = round(butterworth_delay_s(cfg.lowpass_hz) * US_PER_S)
        self._n = 0
        self._baseline: deque[tuple[int, float]] = deque()
        self._baseline_sum = 0.0
        self._d_window: deque[tuple[int, float]] = deque()
        self._f_window: deque[tuple[int, float]] = deque()
        self.amplitude = 0.0
        self.front_kg = 0.0
        self._front_peak = 0.0
        self._last_amp_update: int | None = None
        self._prev_d: float | None = None
        self._prev_t: int | None = None
        self._last_zero_t: int | None = None
        self._side: str | None = None
        self._contacts: deque[_Contact] = deque(maxlen=3)
        self._low_front_us = 0
        self._flight_streak = 0
        self.running = False
        #: Every plausible step, accepted or not: the reference for "is this step's timing odd?".
        #: Using accepted steps only would lock the engine out after a real cadence change --
        #: every new step would look odd, and odd steps would never update the reference.
        self._recent_step_times: deque[float] = deque(maxlen=cfg.rolling_steps)
        self._step_times: deque[float] = deque(maxlen=cfg.rolling_steps)
        self._step_lengths: deque[float] = deque(maxlen=cfg.rolling_steps)
        self._stride_lengths: deque[float] = deque(maxlen=cfg.rolling_strides)
        self._stride_times: deque[float] = deque(maxlen=cfg.rolling_strides)
        self._amp_baseline: list[float] = []
        self._first_t: int | None = None
        self._last_accepted_t: int | None = None
        self._last_t = 0
        self._last_confidence: str | None = None
        self.condition_id = 1
        self.counters = GaitCounters()

    # ---- input -------------------------------------------------------------

    def set_condition(self, condition_id: int) -> None:
        """A new condition block: cadence, lengths and signal baseline restart."""
        self.condition_id = condition_id
        self._restart_history()

    def _restart_history(self) -> None:
        # A new speed legitimately changes cadence and length: never judge or display
        # the new steps against the old ones.
        self._recent_step_times.clear()
        self._step_times.clear()
        self._step_lengths.clear()
        self._stride_lengths.clear()
        self._stride_times.clear()
        self._amp_baseline.clear()

    def feed(self, t_us: int, tl_kg: float, tr_kg: float) -> list[Step]:
        tl = self._lp_tl(tl_kg)
        tr = self._lp_tr(tr_kg)
        self._n += 1
        if self._n % self._decimate:
            return []
        cfg = self.config
        t = t_us - self._delay_us
        if self._first_t is None:
            self._first_t = t
        front = tl + tr
        lateral = tr - tl

        # Remove slow lateral drift, so standing off-centre does not bias the side decision.
        self._baseline.append((t, lateral))
        self._baseline_sum += lateral
        cutoff = t - int(cfg.lateral_baseline_s * US_PER_S)
        while self._baseline and self._baseline[0][0] < cutoff:
            self._baseline_sum -= self._baseline.popleft()[1]
        d = lateral - self._baseline_sum / len(self._baseline)

        window_cutoff = t - int(cfg.amplitude_window_s * US_PER_S)
        self._d_window.append((t, d))
        self._f_window.append((t, front))
        while self._d_window and self._d_window[0][0] < window_cutoff:
            self._d_window.popleft()
        while self._f_window and self._f_window[0][0] < window_cutoff:
            self._f_window.popleft()
        if self._last_amp_update is None or t - self._last_amp_update >= cfg.amplitude_update_s * US_PER_S:
            self._update_levels(t)

        if self._prev_t is not None:
            if self._front_peak > 0 and front < cfg.flight_fraction * self._front_peak:
                self._low_front_us += t - self._prev_t
            if self._prev_d is not None and (self._prev_d < 0) != (d < 0) and d != self._prev_d:
                # Interpolated zero crossing: the moment load passed from one side to the other.
                fraction = -self._prev_d / (d - self._prev_d)
                self._last_zero_t = self._prev_t + round(fraction * (t - self._prev_t))
        self._prev_d, self._prev_t, self._last_t = d, t, t

        h = cfg.hysteresis * self.amplitude
        # Warm-up: until the drift baseline and amplitude windows are full, zero crossings
        # are biased and would make left and right step times unequal.
        if self.amplitude <= 0 or t - self._first_t < cfg.amplitude_window_s * US_PER_S:
            return []
        if d > h and self._side != "R":
            return self._contact("R", t)
        if d < -h and self._side != "L":
            return self._contact("L", t)
        return []

    def _update_levels(self, t: int) -> None:
        self._last_amp_update = t
        values = sorted(v for _, v in self._d_window)
        if len(values) >= 10:
            self.amplitude = (_percentile(values, 0.95) - _percentile(values, 0.05)) / 2
        recent = [v for ts, v in self._f_window if ts >= t - 2 * US_PER_S]
        self.front_kg = statistics.fmean(recent) if recent else 0.0
        fronts = sorted(v for _, v in self._f_window)
        self._front_peak = _percentile(fronts, 0.95) if fronts else 0.0

    # ---- contacts and steps --------------------------------------------------

    def occupied(self, t: int) -> bool:
        speed = self.speed.at(t)
        return (
            self.front_kg >= self.config.min_front_kg
            and self.amplitude >= self.config.min_amplitude_kg
            and speed is not None
            and speed >= self.config.min_belt_kph
        )

    def _contact(self, side: str, t_detect: int) -> list[Step]:
        cfg = self.config
        self._side = side
        previous = self._contacts[-1] if self._contacts else None
        t_c = t_detect
        if self._last_zero_t is not None and (previous is None or self._last_zero_t > previous.t_us):
            t_c = self._last_zero_t
        if not self.occupied(t_detect):
            self._contacts.clear()
            self._low_front_us = 0
            return []
        self.counters.contacts += 1

        flight = self._low_front_us >= cfg.flight_min_s * US_PER_S
        self._low_front_us = 0
        self._flight_streak = self._flight_streak + 1 if flight else 0
        if self._flight_streak >= cfg.running_after_steps:
            self.running = True
        elif not flight:
            self.running = False

        if previous is None:
            self._contacts.append(_Contact(t_c, side))
            return []
        step_time = (t_c - previous.t_us) / US_PER_S
        refractory = max(cfg.min_step_s, cfg.refractory_fraction * _median(self._recent_step_times, 0.0))
        if step_time < refractory:
            return []  # a flicker around the threshold, not a new foot
        if step_time > cfg.max_step_s:
            self._contacts.clear()  # a pause: start a new chain rather than invent a long step
            self._contacts.append(_Contact(t_c, side))
            return []
        self._contacts.append(_Contact(t_c, side))

        reasons: list[str] = []
        confidence = HIGH
        speed = self.speed.at(t_c)
        step_length = self.speed.integrate_m(previous.t_us, t_c)
        stride_time: float | None = None
        stride_length: float | None = None
        if len(self._contacts) == 3 and self._contacts[0].side == side:
            first = self._contacts[0]
            stride_time = (t_c - first.t_us) / US_PER_S
            stride_length = self.speed.integrate_m(first.t_us, t_c)
        if step_length is None or speed is None or speed < cfg.min_belt_kph:
            confidence = UNAVAILABLE
            reasons.append("belt speed not set")
        transition = self.speed.changed_between(previous.t_us, t_c)
        if transition:
            reasons.append("speed changed during this step")
            self._restart_history()
        elif len(self._recent_step_times) >= 3:
            median = _median(self._recent_step_times, step_time)
            if abs(step_time - median) > cfg.median_tolerance * median:
                confidence = _worst(confidence, LOW)
                reasons.append("step time far from the recent median")
        if not transition:
            self._recent_step_times.append(step_time)
        baseline = _median(self._amp_baseline, self.amplitude) if len(self._amp_baseline) >= 3 else None
        if baseline:
            ratio = self.amplitude / baseline
            if ratio < cfg.weak_fraction:
                confidence = _worst(confidence, LOW)
                reasons.append("weak signal: patient may be at the back of the deck")
            elif ratio < cfg.medium_fraction:
                confidence = _worst(confidence, MEDIUM)
                reasons.append("reduced signal")
        if self.running:
            confidence = _worst(confidence, MEDIUM)
            reasons.append("running: not yet validated")

        step = Step(
            t_us=t_c,
            side=side,
            step_time_s=round(step_time, 4),
            step_length_m=round(step_length, 4) if step_length is not None else None,
            stride_time_s=round(stride_time, 4) if stride_time is not None else None,
            stride_length_m=round(stride_length, 4) if stride_length is not None else None,
            speed_kph=speed,
            confidence=confidence,
            reasons=tuple(reasons),
            transition=transition,
            running=self.running,
            condition_id=self.condition_id,
            amplitude_kg=round(self.amplitude, 3),
        )
        self.counters.steps += 1
        self.counters.by_confidence[confidence] += 1
        self._last_confidence = confidence
        if step.accepted:
            self.counters.accepted += 1
            self._step_times.append(step_time)
            if step_length is not None:
                self._step_lengths.append(step_length)
            if stride_length is not None:
                self._stride_lengths.append(stride_length)
            if stride_time is not None:
                self._stride_times.append(stride_time)
            self._amp_baseline.append(self.amplitude)
            self._last_accepted_t = t_c
        return [step]

    # ---- live metrics ----------------------------------------------------------

    def live(self) -> dict[str, Any]:
        cfg = self.config
        recent = (
            self._last_accepted_t is not None
            and self._last_t - self._last_accepted_t <= cfg.show_for_s * US_PER_S
        )
        show = recent and len(self._step_times) >= cfg.min_steps_to_show
        # Cadence from stride time (two steps): unequal left and right steps -- a limp, or
        # a biased baseline -- cancel out, where a median of single steps would pick one side.
        if not show:
            cadence = None
        elif self._stride_times:
            cadence = 120.0 / statistics.median(self._stride_times)
        else:
            cadence = 60.0 / statistics.median(self._step_times)
        step_length = statistics.median(self._step_lengths) if show and self._step_lengths else None
        stride_length = statistics.median(self._stride_lengths) if show and self._stride_lengths else None
        return {
            "state": ("running" if self.running else "walking") if show else "idle",
            "cadence_spm": round(cadence, 1) if cadence else None,
            "step_length_m": round(step_length, 3) if step_length else None,
            "stride_length_m": round(stride_length, 3) if stride_length else None,
            "confidence": self._last_confidence if show else None,
            "prompt": self._prompt(show),
            "steps_total": self.counters.steps,
            "steps_accepted": self.counters.accepted,
            "front_kg": round(self.front_kg, 2),
            "amplitude_kg": round(self.amplitude, 2),
        }

    def _prompt(self, showing: bool) -> str | None:
        cfg = self.config
        speed = self.speed.at(self._last_t)
        if speed is None or speed < cfg.min_belt_kph:
            return "Belt speed not set"
        if self.front_kg < cfg.min_front_kg:
            return "No one walking"
        if self.amplitude < cfg.min_amplitude_kg:
            return "No stepping detected"
        if len(self._amp_baseline) >= 3 and self.amplitude < cfg.weak_fraction * statistics.median(
            self._amp_baseline
        ):
            return "Step forward on the deck"
        if self.running:
            return "Running: metrics not yet validated"
        return None if showing else "Detecting steps…"


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _median(values: Any, default: float) -> float:
    items = list(values)
    return statistics.median(items) if items else default


def _worst(a: str, b: str) -> str:
    return a if _RANK[a] <= _RANK[b] else b
