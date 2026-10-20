"""Noticing that a load cell has stopped responding.

A corner can fail silently. The deck keeps reporting a number, the console keeps
recording sessions, and every weight is understated by roughly a quarter --
which on a machine whose job is to tell a patient they are within a
weight-bearing limit is the most dangerous way for it to be wrong.

This happened here. One corner worked through three September recordings,
carried a normal share in each, and was reading nothing by 10 October. Nobody
noticed for weeks, and then only because somebody plotted the raw data by hand.

The signature is unmistakable once you look for the right thing. Not the cell's
*share* of the load -- a patient standing off-centre genuinely unloads a corner
-- but how far it **travels**. Every working corner moves with each step. Across
the 10 October session the three live cells travelled 42-43 kg between their 5th
and 95th percentiles; the dead one travelled 4.4 kg, which is its own electrical
noise. As a fraction of the median cell: 99%, 101%, 102% -- and 10%.

So: when the deck is being walked on, compare each cell's travel to the others.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

CELL_NAMES = ("Top left", "Top right", "Bottom right", "Bottom left")

#: Samples are summarised into buckets of this length, and this many are kept.
#: Twenty seconds is several gait cycles at any speed the machine runs at, and
#: bounds the memory regardless of the board's sample rate.
BUCKET_S = 0.5
BUCKETS = 40

#: A cell travelling less than this fraction of the median cell is not
#: responding. Measured: a dead corner reads 10%, live ones 99-102%. A quarter
#: sits clear of both, and clear of a corner that is merely lightly loaded.
DEAD_FRACTION = 0.25
SUSPECT_FRACTION = 0.50

#: Below this much travel on the median cell nobody is really walking, and the
#: comparison means nothing. A patient standing still moves no corner.
MIN_MEDIAN_TRAVEL_KG = 8.0


class CellState(str, Enum):
    OK = "ok"
    SUSPECT = "suspect"
    DEAD = "dead"
    UNKNOWN = "unknown"       # not enough movement on the deck to judge


@dataclass(frozen=True, slots=True)
class CellReport:
    name: str
    index: int
    state: CellState
    travel_kg: float
    share_of_median: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "index": self.index, "state": self.state.value,
                "travel_kg": round(self.travel_kg, 2),
                "share_of_median": round(self.share_of_median, 3)}


@dataclass(frozen=True, slots=True)
class DeckHealth:
    cells: list[CellReport]
    #: Set when a cell has stopped responding. The weights are wrong, and by
    #: roughly the share that corner used to carry.
    fault: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"cells": [c.as_dict() for c in self.cells], "fault": self.fault}


def _percentile(xs: Sequence[float], p: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


class CellHealthMonitor:
    """Fed every sample; says whether each corner is still responding."""

    def __init__(self) -> None:
        self._buckets: deque[list[tuple[float, float]]] = deque(maxlen=BUCKETS)
        self._open: list[tuple[float, float]] | None = None
        self._open_until = 0.0

    def on_sample(self, t: float, cells: Sequence[float]) -> None:
        if self._open is None or t >= self._open_until:
            if self._open is not None:
                self._buckets.append(self._open)
            self._open = [(v, v) for v in cells]
            self._open_until = t + BUCKET_S
            return
        self._open = [(min(lo, v), max(hi, v)) for (lo, hi), v in zip(self._open, cells)]

    def report(self) -> DeckHealth:
        buckets = list(self._buckets)
        if len(buckets) < BUCKETS // 4:
            return DeckHealth([CellReport(n, i, CellState.UNKNOWN, 0.0, 0.0)
                               for i, n in enumerate(CELL_NAMES)], None)

        travel = []
        for i in range(len(CELL_NAMES)):
            lows = [b[i][0] for b in buckets]
            highs = [b[i][1] for b in buckets]
            # Percentiles across buckets, so one stamp or knock does not set it.
            travel.append(max(0.0, _percentile(highs, 0.9) - _percentile(lows, 0.1)))

        ordered = sorted(travel)
        median = (ordered[1] + ordered[2]) / 2 if len(ordered) == 4 else 0.0
        if median < MIN_MEDIAN_TRAVEL_KG:
            return DeckHealth([CellReport(n, i, CellState.UNKNOWN, travel[i], 0.0)
                               for i, n in enumerate(CELL_NAMES)], None)

        cells, dead = [], []
        for i, name in enumerate(CELL_NAMES):
            share = travel[i] / median
            if share < DEAD_FRACTION:
                state = CellState.DEAD
                dead.append(name)
            elif share < SUSPECT_FRACTION:
                state = CellState.SUSPECT
            else:
                state = CellState.OK
            cells.append(CellReport(name, i, state, travel[i], share))

        fault = None
        if len(dead) == 1:
            fault = (f"The {dead[0].lower()} load cell is not responding. "
                     "Every weight is being under-reported. Check its cable at the board.")
        elif len(dead) > 1:
            fault = (f"{len(dead)} load cells are not responding "
                     f"({', '.join(d.lower() for d in dead)}). Check the board connections.")
        return DeckHealth(cells, fault)
