"""The belt-speed timeline, and distance as its integral.

Step and stride length are the belt distance travelled between two foot contacts,
so a speed change mid-step is integrated rather than approximated by one value.
Phase 1 speed is what the therapist enters; Bluetooth treadmill speed (M3b) will
feed the same timeline.
"""

from __future__ import annotations

import bisect

US_PER_S = 1_000_000


class SpeedTimeline:
    def __init__(self) -> None:
        self._times: list[int] = []
        self._kph: list[float | None] = []

    def set(self, t_us: int, kph: float | None) -> None:
        """Speed from `t_us` onwards. Times must not go backwards."""
        if self._times and t_us < self._times[-1]:
            raise ValueError("speed changes must be in time order")
        if self._times and t_us == self._times[-1]:
            self._kph[-1] = kph
            return
        self._times.append(t_us)
        self._kph.append(kph)

    def at(self, t_us: int) -> float | None:
        i = bisect.bisect_right(self._times, t_us) - 1
        return self._kph[i] if i >= 0 else None

    def integrate_m(self, t0_us: int, t1_us: int) -> float | None:
        """Metres of belt between two times, or None if the speed was unknown for any of it."""
        if t1_us < t0_us:
            return None
        start = bisect.bisect_right(self._times, t0_us) - 1
        if start < 0:
            return None
        metres = 0.0
        t = t0_us
        i = start
        while t < t1_us:
            kph = self._kph[i]
            if kph is None:
                return None
            end = self._times[i + 1] if i + 1 < len(self._times) else t1_us
            end = min(end, t1_us)
            metres += kph / 3.6 * (end - t) / US_PER_S
            t = end
            i += 1
        return metres

    def changed_between(self, t0_us: int, t1_us: int, tolerance_kph: float = 0.18) -> bool:
        """True when the speed changed by more than `tolerance_kph` (0.05 m/s) inside the interval."""
        values = [self.at(t0_us)] + [
            k for t, k in zip(self._times, self._kph, strict=True) if t0_us < t <= t1_us
        ]
        known = [v for v in values if v is not None]
        return len(known) != len(values) or (max(known) - min(known) > tolerance_kph if known else False)
