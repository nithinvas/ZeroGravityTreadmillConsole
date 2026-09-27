"""A small live-chart feed: the four cells and total, averaged into 25 points per second.

Block averaging rather than picking every Nth sample: skipping samples without a
filter aliases, drawing wiggles that are not in the signal.
"""

from __future__ import annotations

from collections import deque

from treadmill.calibration.profile import CalibrationProfile
from treadmill.processor import Sample

INTERVAL_US = 40_000
KEEP_S = 30


class ChartFeed:
    def __init__(self) -> None:
        self._points: deque[list[float]] = deque(maxlen=KEEP_S * 1_000_000 // INTERVAL_US)
        self._seq = 0
        self._sum = [0.0] * 4
        self._n = 0
        self._block_end: int | None = None
        self.units = "kg"

    def reset(self) -> None:
        self._points.clear()
        self._sum = [0.0] * 4
        self._n = 0
        self._block_end = None

    def add(self, sample: Sample, profile: CalibrationProfile | None) -> None:
        if profile is not None:
            values = profile.cell_kg(sample.values)
            self.units = "kg"
        else:
            values = [float(v) for v in sample.values]
            self.units = "counts"
        if self._block_end is None:
            self._block_end = sample.t_us + INTERVAL_US
        for i in range(4):
            self._sum[i] += values[i]
        self._n += 1
        if sample.t_us >= self._block_end:
            avg = [v / self._n for v in self._sum]
            self._seq += 1
            self._points.append(
                [self._seq, round(sample.t_us / 1e6, 3)] + [round(v, 2) for v in avg] + [round(sum(avg), 2)]
            )
            self._sum = [0.0] * 4
            self._n = 0
            self._block_end = sample.t_us + INTERVAL_US

    def since(self, seq: int) -> list[list[float]]:
        return [p for p in self._points if p[0] > seq]
