"""Two per-foot force curves from one four-cell deck.

A dual force plate measures each foot separately. We have one deck, both feet on
it, and four load cells -- which give total force and a centre of pressure, three
numbers against four unknowns (two forces, two positions). Underdetermined, in
general.

It is only underdetermined some of the time. For most of a gait cycle one foot is
in the air, and an airborne foot carries exactly nothing; there is no algebra to
do, only a fact to assert. That is why the curves reach true zero rather than
bottoming out at some fitted residual. The work is confined to the hand-over
windows where both feet are down, and there the pressure point sits between two
feet whose positions we measured a fraction of a second earlier.

Three design choices are worth knowing about:

**Phase comes from the lateral axis, not the fore-aft one.** The obvious
signature is the pressure point sliding backward at belt speed while a foot is
planted. It works beautifully between 3 and 7 km/h and fails at both ends: slow,
the heel-to-toe roll under the foot (~0.24 m/s forward) cancels the belt and the
slide disappears; fast, the flight phase drives force to zero and the pressure
point becomes numerically meaningless. Sideways separation between the feet
carries the same information, is 13-17 cm at every speed we have data for, and
needs no belt speed input at all.

**Both axes are used for the split, weighted by how well each is conditioned.**
Fore-aft separation between the feet is a step length; lateral is a step width,
several times smaller, so the same centre-of-pressure error costs much more
there. Weighting by the square of the separation is the least-squares answer
under the constraint that the two feet must sum to the measured total. Their
disagreement is reported as confidence, free of charge.

**Nothing is assumed about the patient.** Cluster centres are found where the
feet actually land, so standing off-centre or loading one side harder is read,
not corrected for. Body weight is the mean total force over whole gait cycles,
which is Newton's third law rather than a number somebody typed in -- so it is
right for any body weight, and right again when body-weight support is taking
half of it.

What this cannot do is work on a gait that has no structure. If a patient
shuffles without ever fully unloading a limb, or leans on the handrail, there is
no single stance to anchor from and the central assertion is false. The engine
detects that and declines rather than producing a confident fiction -- see
`Phase.UNAVAILABLE` and `Decomposition.quality`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

# Deck geometry, metres. Measured on the unit.
DECK_LENGTH_M = 0.78
DECK_WIDTH_M = 0.46

#: Below this fraction of body weight nobody is standing on the deck: the
#: patient is airborne between running strides, or has stepped off.
FLIGHT_FRACTION = 0.10

#: Hysteresis on the lateral position, as a fraction of the gap between the two
#: feet. A sample enters single stance inside ENTER of a foot's centre and only
#: leaves once it passes EXIT, so noise around the threshold cannot chatter.
#: Tuned against three subjects over 1-12 km/h so that double support lands near
#: the ~20% of the cycle that walking actually has: looser values let single
#: stance eat the hand-over and report 8%, which would quietly understate how
#: long a patient spends on two feet -- itself a clinical sign.
ENTER = 0.08
EXIT = 0.25

#: The feet must be at least this far apart across the deck to be told apart.
MIN_SEPARATION_M = 0.035

#: Shortest run of samples that can be a real phase rather than a glitch.
MIN_PHASE_SAMPLES = 2

#: Default smoothing, in samples, applied to the cell signals before anything
#: else. At 80-100 Hz five samples is ~60 ms: it cuts sample noise roughly four
#: fold while costing under 2% of peak. Never applied to the output curves --
#: that would drag the zeros up and lose the one thing that makes these read
#: like a dual plate.
DEFAULT_SMOOTHING = 5


class Phase(str, Enum):
    LEFT = "left"            # left foot alone
    RIGHT = "right"          # right foot alone
    DOUBLE = "double"        # both down, load handing over
    FLIGHT = "flight"        # neither down, running
    UNAVAILABLE = "unavailable"   # cannot be resolved; draw a gap


class Quality(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    UNUSABLE = "unusable"


@dataclass(frozen=True, slots=True)
class FootSample:
    """One instant, resolved.

    `left + right + residual == total` holds exactly, always. Residual is the
    load on the deck that belongs to neither foot -- belt vibration during a
    flight phase -- and is zero whenever anybody is standing on it.
    """
    t: float
    total_kg: float
    left_kg: float
    right_kg: float
    residual_kg: float
    phase: Phase
    confidence: float        # 0..1, how well the two axes agreed

    def as_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 4),
            "total": round(self.total_kg, 2),
            # None, not 0, where nothing could be resolved: the chart must draw
            # a gap there rather than a line through territory we never saw.
            "left": None if self.phase is Phase.UNAVAILABLE else round(self.left_kg, 2),
            "right": None if self.phase is Phase.UNAVAILABLE else round(self.right_kg, 2),
            "phase": self.phase.value,
            "confidence": round(self.confidence, 3),
        }


@dataclass(frozen=True, slots=True)
class Decomposition:
    samples: list[FootSample]
    body_weight_kg: float
    quality: Quality
    reason: str = ""
    #: Fraction of samples that could not be resolved at all.
    gap_fraction: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "body_weight_kg": round(self.body_weight_kg, 2),
            "quality": self.quality.value,
            "reason": self.reason,
            "gap_fraction": round(self.gap_fraction, 4),
            "samples": [s.as_dict() for s in self.samples],
        }


# ---- signal conditioning ------------------------------------------------------


def moving_average(xs: Sequence[float], n: int) -> list[float]:
    """Centred moving average, edges held rather than tapered to zero."""
    if n <= 1 or len(xs) < 2:
        return list(xs)
    n = min(n, len(xs))
    half = n // 2
    padded = [xs[0]] * half + list(xs) + [xs[-1]] * half
    out, run = [], sum(padded[:n])
    out.append(run / n)
    for i in range(n, len(padded)):
        run += padded[i] - padded[i - n]
        out.append(run / n)
    return out[: len(xs)]


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _percentile(xs: Sequence[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = (len(s) - 1) * p / 100
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] if lo == hi else s[lo] * (hi - i) + s[hi] * (i - lo)


def _two_centres(values: Sequence[float]) -> tuple[float, float] | None:
    """The two places the feet land, found rather than assumed.

    One-dimensional k-means from robust starting points. A patient standing
    off-centre gives two off-centre clusters, which is the truth; a patient with
    both feet in the same place gives one, which is reported as a failure
    instead of being split down the middle.
    """
    if len(values) < 8:
        return None
    lo, hi = _percentile(values, 12), _percentile(values, 88)
    if hi - lo < MIN_SEPARATION_M:
        return None
    for _ in range(25):
        mid = (lo + hi) / 2
        left = [v for v in values if v < mid]
        right = [v for v in values if v >= mid]
        if not left or not right:
            return None
        new_lo, new_hi = sum(left) / len(left), sum(right) / len(right)
        if abs(new_lo - lo) < 1e-5 and abs(new_hi - hi) < 1e-5:
            lo, hi = new_lo, new_hi
            break
        lo, hi = new_lo, new_hi
    return (lo, hi) if hi - lo >= MIN_SEPARATION_M else None


# ---- the decomposition --------------------------------------------------------


@dataclass
class _Track:
    """Where one foot is, while it is on the deck."""
    phase: Phase
    start: int
    end: int
    x: float            # lateral position, m
    y0: float           # fore-aft position at t0, m
    slope: float        # how fast that position travels, m/s
    t0: float

    def y_at(self, t: float) -> float:
        return self.y0 + self.slope * (t - self.t0)


def decompose(
    t: Sequence[float],
    cells: Sequence[Sequence[float]],
    *,
    smoothing: int = DEFAULT_SMOOTHING,
) -> Decomposition:
    """Split a deck trace into per-foot curves.

    `cells` is one row per sample: top-left, top-right, bottom-right, bottom-left,
    in kilograms. `t` is seconds.
    """
    n = len(t)
    if n < 16:
        return Decomposition([], 0.0, Quality.UNUSABLE, "not enough samples")

    tl = moving_average([c[0] for c in cells], smoothing)
    tr = moving_average([c[1] for c in cells], smoothing)
    br = moving_average([c[2] for c in cells], smoothing)
    bl = moving_average([c[3] for c in cells], smoothing)
    total = [a + b + c + d for a, b, c, d in zip(tl, tr, br, bl)]

    # Body weight is the mean total force over the window. Over whole gait
    # cycles that is exactly the supported weight -- Newton, not a typed-in
    # number -- so it is right for any patient and right again under body-weight
    # support, which is the only reading that matters here.
    body_weight = sum(total) / n
    if body_weight <= 1.0:
        return Decomposition([], 0.0, Quality.UNUSABLE, "no load on the deck")

    floor = FLIGHT_FRACTION * body_weight
    loaded = [f > floor for f in total]

    copx: list[float | None] = []
    copy_: list[float | None] = []
    for i in range(n):
        if not loaded[i]:
            copx.append(None)
            copy_.append(None)
            continue
        f = total[i]
        copx.append((DECK_WIDTH_M / 2) * ((tr[i] + br[i]) - (tl[i] + bl[i])) / f)
        copy_.append((DECK_LENGTH_M / 2) * ((tl[i] + tr[i]) - (bl[i] + br[i])) / f)

    seen = [v for v in copx if v is not None]
    centres = _two_centres(seen)
    if centres is None:
        return Decomposition(
            [FootSample(t[i], total[i], 0.0, 0.0, total[i], Phase.UNAVAILABLE, 0.0)
             for i in range(n)],
            body_weight, Quality.UNUSABLE,
            "the two feet cannot be told apart across the deck", 1.0,
        )
    left_x, right_x = centres
    span = right_x - left_x

    labels = _label(copx, loaded, left_x, span, n)
    runs = _runs(labels)
    tracks = _tracks(runs, t, copx, copy_)
    return _resolve(t, total, copx, copy_, runs, tracks, body_weight)


def _label(copx, loaded, left_x, span, n) -> list[Phase]:
    """Classify each sample, with hysteresis so the edges cannot chatter."""
    out: list[Phase] = []
    state = Phase.DOUBLE
    for i in range(n):
        if not loaded[i]:
            state = Phase.FLIGHT
            out.append(state)
            continue
        u = (copx[i] - left_x) / span       # 0 at the left foot, 1 at the right
        if state is Phase.LEFT:
            state = Phase.LEFT if u < EXIT else Phase.DOUBLE
        elif state is Phase.RIGHT:
            state = Phase.RIGHT if u > 1 - EXIT else Phase.DOUBLE
        else:
            if u < ENTER:
                state = Phase.LEFT
            elif u > 1 - ENTER:
                state = Phase.RIGHT
            else:
                state = Phase.DOUBLE
        out.append(state)
    return out


def _runs(labels: list[Phase]) -> list[tuple[int, int, Phase]]:
    runs, i = [], 0
    while i < len(labels):
        j = i
        while j < len(labels) and labels[j] is labels[i]:
            j += 1
        runs.append((i, j, labels[i]))
        i = j
    # Absorb runs too short to be real, so a single noisy sample cannot invent
    # a phase change.
    merged: list[tuple[int, int, Phase]] = []
    for a, b, p in runs:
        if b - a < MIN_PHASE_SAMPLES and merged:
            pa, pb, pp = merged[-1]
            merged[-1] = (pa, b, pp)
        else:
            merged.append((a, b, p))
    return merged


def _tracks(runs, t, copx, copy_) -> dict[int, _Track]:
    """Measure where each foot sits, for every stance it has on the deck."""
    out: dict[int, _Track] = {}
    for idx, (a, b, phase) in enumerate(runs):
        if phase not in (Phase.LEFT, Phase.RIGHT):
            continue
        xs = [copx[i] for i in range(a, b) if copx[i] is not None]
        ys = [(t[i], copy_[i]) for i in range(a, b) if copy_[i] is not None]
        if not xs or len(ys) < 2:
            continue
        # The pressure point travels during stance: the belt drags the foot
        # backward while the foot's own load rolls heel to toe forward. Fit
        # whatever it actually did rather than assuming belt speed.
        slope = _fit_slope([p[0] for p in ys], [p[1] for p in ys])
        out[idx] = _Track(phase, a, b, _median(xs), ys[0][1], slope, ys[0][0])
    return out


def _fit_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den < 1e-12 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _resolve(t, total, copx, copy_, runs, tracks, body_weight) -> Decomposition:
    n = len(t)
    out: list[FootSample] = [None] * n   # type: ignore[list-item]

    for idx, (a, b, phase) in enumerate(runs):
        if phase is Phase.FLIGHT:
            # Nobody is on the deck. Neither foot carries anything, and what the
            # cells still read is belt vibration -- reported as residual rather
            # than smeared across two feet that are both in the air.
            for i in range(a, b):
                out[i] = FootSample(t[i], total[i], 0.0, 0.0, total[i], Phase.FLIGHT, 1.0)
        elif phase in (Phase.LEFT, Phase.RIGHT):
            for i in range(a, b):
                left = total[i] if phase is Phase.LEFT else 0.0
                out[i] = FootSample(t[i], total[i], left, total[i] - left, 0.0, phase, 1.0)
        else:
            prev = tracks.get(idx - 1)
            nxt = tracks.get(idx + 1)
            usable = prev is not None and nxt is not None and prev.phase is not nxt.phase
            for i in range(a, b):
                if not usable or copx[i] is None:
                    out[i] = FootSample(t[i], total[i], 0.0, 0.0, total[i],
                                        Phase.UNAVAILABLE, 0.0)
                    continue
                out[i] = _split(t[i], total[i], copx[i], copy_[i], prev, nxt)

    gaps = sum(1 for s in out if s.phase is Phase.UNAVAILABLE) / n
    conf = sum(s.confidence for s in out) / n
    quality, reason = _grade(runs, gaps, conf, n)
    return Decomposition(out, body_weight, quality, reason, gaps)


def _split(ti, f, cx, cy, prev: _Track, nxt: _Track) -> FootSample:
    """Share one instant's load between two feet whose positions we measured.

    Two independent levers -- one across the deck, one along it -- each give the
    trailing foot's share. Combining them weighted by the square of the foot
    separation is the least-squares answer subject to the two feet summing to
    the measured total, which is the one thing here that was actually measured
    and so is enforced rather than fitted.
    """
    est: list[tuple[float, float]] = []    # (share of the leading foot, weight)

    gap_x = nxt.x - prev.x
    if abs(gap_x) > 1e-4:
        est.append(((cx - prev.x) / gap_x, gap_x * gap_x))
    if cy is not None:
        y_prev, y_next = prev.y_at(ti), nxt.y_at(ti)
        gap_y = y_next - y_prev
        if abs(gap_y) > 1e-4:
            est.append(((cy - y_prev) / gap_y, gap_y * gap_y))

    if not est:
        return FootSample(ti, f, 0.0, 0.0, f, Phase.UNAVAILABLE, 0.0)

    weight = sum(w for _, w in est)
    share = sum(s * w for s, w in est) / weight
    # How far apart the two axes were before they were averaged. They measure
    # the same physical quantity, so disagreement is the honest confidence.
    spread = max(s for s, _ in est) - min(s for s, _ in est) if len(est) > 1 else 0.0
    confidence = max(0.0, 1.0 - 2.0 * abs(spread))

    lead = min(max(share, 0.0), 1.0) * f
    trail = f - lead
    left, right = (trail, lead) if prev.phase is Phase.LEFT else (lead, trail)
    return FootSample(ti, f, left, right, 0.0, Phase.DOUBLE, confidence)


def _grade(runs, gaps, conf, n) -> tuple[Quality, str]:
    stances = [r for r in runs if r[2] in (Phase.LEFT, Phase.RIGHT)]
    if len(stances) < 2:
        return Quality.UNUSABLE, "no alternating single stance: the patient may be shuffling, or on the handrail"
    sides = [r[2] for r in stances]
    alternating = sum(1 for a, b in zip(sides, sides[1:]) if a is not b) / max(1, len(sides) - 1)
    if alternating < 0.7:
        return Quality.UNUSABLE, "steps are not alternating between the feet"
    if gaps > 0.25:
        return Quality.UNUSABLE, "too much of the trace could not be resolved"
    if gaps > 0.08 or conf < 0.6 or alternating < 0.95:
        return Quality.FAIR, "resolved, but the hand-over between feet is not clean"
    return Quality.GOOD, ""


# ---- live ---------------------------------------------------------------------


class StreamingDecomposer:
    """The same decomposition, fed a sample at a time.

    Live and the report must never disagree -- a therapist who watched a curve
    and then reads a different one in the record has no reason to trust either.
    So this does not reimplement anything: it keeps a window, runs the batch
    decomposition over it, and releases only the part far enough from the live
    edge to have stopped changing.

    That costs a fixed delay. Single stance could in principle be emitted
    instantly, but a hand-over cannot be resolved until the next foot has landed
    and been measured, so part of the curve would always arrive late. Delaying
    all of it by the same amount keeps the curve uniform, and on a gait trace
    half a second is not perceptible.
    """

    #: Nothing is released until the window holds at least this much, so the
    #: first curve a therapist sees was decided on as much context as every
    #: later one -- otherwise the opening second would be the one stretch where
    #: live and the report disagree.
    MIN_FILL_S = 2.0

    #: How often the window is actually re-solved. Re-solving on every sample
    #: would redo several thousand samples' work per sample -- at 500 Hz that is
    #: a million operations a second in Python, which is enough to stall the
    #: acquisition loop. Nothing is lost by batching: no sample is released for
    #: half a second anyway, so re-solving twenty times a second still settles
    #: every sample long before it is due out.
    RESOLVE_INTERVAL_S = 0.05

    def __init__(self, window_s: float = 4.0, settle_s: float = 0.5,
                 smoothing: int = DEFAULT_SMOOTHING) -> None:
        self.window_s = window_s
        self.settle_s = settle_s
        self.smoothing = smoothing
        self._next_resolve = -math.inf
        self._t: list[float] = []
        self._cells: list[Sequence[float]] = []
        self._released_to = -math.inf
        self.body_weight_kg = 0.0
        self.quality = Quality.UNUSABLE
        self.reason = "waiting for enough of a walk to work with"

    def push(self, t: float, cell_kg: Sequence[float]) -> list[FootSample]:
        """Add one sample; return any samples that have now settled."""
        self._t.append(t)
        self._cells.append(tuple(cell_kg))
        cut = t - self.window_s
        while len(self._t) > 2 and self._t[0] < cut:
            self._t.pop(0)
            self._cells.pop(0)
        if len(self._t) < 16 or self._t[-1] - self._t[0] < self.MIN_FILL_S:
            return []
        if t < self._next_resolve:
            return []
        self._next_resolve = t + self.RESOLVE_INTERVAL_S

        result = decompose(self._t, self._cells, smoothing=self.smoothing)
        self.body_weight_kg = result.body_weight_kg
        self.quality = result.quality
        self.reason = result.reason

        return self._release(result, t - self.settle_s)

    def flush(self) -> list[FootSample]:
        """Release the tail once the walk is over. Used when replaying a trace."""
        if len(self._t) < 16:
            return []
        result = decompose(self._t, self._cells, smoothing=self.smoothing)
        self.body_weight_kg = result.body_weight_kg
        self.quality = result.quality
        self.reason = result.reason
        return self._release(result, math.inf)

    def _release(self, result: Decomposition, horizon: float) -> list[FootSample]:
        fresh = [s for s in result.samples if self._released_to < s.t <= horizon]
        if fresh:
            self._released_to = fresh[-1].t
        return fresh


def decompose_trace(
    t: Sequence[float],
    cells: Sequence[Sequence[float]],
    *,
    smoothing: int = DEFAULT_SMOOTHING,
) -> Decomposition:
    """Decompose a stored session, exactly as the live screen did.

    The report does not re-run the whole trace in one go. It replays it through
    the same sliding window the live screen used, so the curve in the record is
    the curve the therapist watched -- identical, not merely similar. A report
    that quietly disagrees with what was on the screen is worse than no report.
    """
    live = StreamingDecomposer(smoothing=smoothing)
    out: list[FootSample] = []
    for ti, c in zip(t, cells):
        out.extend(live.push(ti, c))
    out.extend(live.flush())
    gaps = (sum(1 for s in out if s.phase is Phase.UNAVAILABLE) / len(out)) if out else 1.0
    return Decomposition(out, live.body_weight_kg, live.quality, live.reason, gaps)
