"""Live averaging for captures and for the weight display.

Mirrors the mobile app's `StabilityWindow` and weight screen: a 2 s rolling
window; a capture is allowed once it covers 1 s, even if the readings are still
moving (flagged, not refused); the weight is "stable" when its standard deviation
over the window is at most 0.5 kg.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass

from treadmill.calibration.profile import CalibrationProfile
from treadmill.protocol.constants import CHANNEL_NAMES

WINDOW_US = 2_000_000
MIN_CAPTURE_US = 1_000_000
MIN_CAPTURE_SAMPLES = 8
#: A cell's raw standard deviation above this marks a capture as fluctuating.
#: About 0.27 kg at 1,856 counts/kg. TODO(hardware): tune against real noise.
CAPTURE_MAX_STD_COUNTS = 500.0
STABLE_WEIGHT_MAX_STD_KG = 0.5


@dataclass(frozen=True)
class Capture:
    means: tuple[float, float, float, float]
    stds: tuple[float, float, float, float]
    samples: int
    covered_s: float
    stable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "means": [round(m, 1) for m in self.means],
            "stds": [round(s, 1) for s in self.stds],
            "cells": list(CHANNEL_NAMES),
            "samples": self.samples,
            "covered_s": round(self.covered_s, 2),
            "stable": self.stable,
        }


class Weighing:
    """Fed every sample; answers capture requests and the live weight."""

    def __init__(self) -> None:
        self._samples: deque[tuple[int, tuple[int, int, int, int]]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def add(self, t_us: int, values: tuple[int, int, int, int]) -> None:
        self._samples.append((t_us, values))
        cutoff = t_us - WINDOW_US
        while self._samples and self._samples[0][0] <= cutoff:
            self._samples.popleft()

    @property
    def covered_us(self) -> int:
        if len(self._samples) < 2:
            return 0
        return self._samples[-1][0] - self._samples[0][0]

    @property
    def ready(self) -> bool:
        return len(self._samples) >= MIN_CAPTURE_SAMPLES and self.covered_us >= MIN_CAPTURE_US

    def capture(self) -> Capture | None:
        """The window's per-cell means, or None until it covers 1 s."""
        if not self.ready:
            return None
        columns = list(zip(*(v for _, v in self._samples), strict=True))
        means = tuple(statistics.fmean(col) for col in columns)
        stds = tuple(statistics.pstdev(col) for col in columns)
        return Capture(
            means=means,  # type: ignore[arg-type]
            stds=stds,
            samples=len(self._samples),
            covered_s=self.covered_us / 1e6,
            stable=all(s <= CAPTURE_MAX_STD_COUNTS for s in stds),
        )

    def weight(self, profile: CalibrationProfile) -> dict[str, object] | None:
        if not self._samples:
            return None
        latest = self._samples[-1][1]
        cells = profile.cell_kg(latest)
        totals = [profile.total_kg(v) for _, v in self._samples]
        average = statistics.fmean(totals)
        spread = statistics.pstdev(totals) if len(totals) > 1 else 0.0
        return {
            # Clamped at zero for display: noise on an empty deck dips slightly
            # negative, and a weight reading should never show that as real.
            "live_kg": round(max(0.0, sum(cells)), 2),
            "average_kg": round(max(0.0, average), 2),
            "std_kg": round(spread, 3),
            "stable": self.ready and spread <= STABLE_WEIGHT_MAX_STD_KG,
            "cells_kg": [round(c, 2) for c in cells],
            "raw": list(latest),
            "window_s": round(self.covered_us / 1e6, 2),
        }
