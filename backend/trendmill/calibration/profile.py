"""A calibration profile: each cell's zero and its sensitivity.

Uses the firmware team's convention, carried over from the mobile app::

    counts per kg  = (raw loaded - raw zero) / known weight
    cell load (kg) = (current raw - raw zero) / counts per kg

Counts per kg is negative on this deck, because the raw value falls under load.
The deck weight is the sum of the four cells: by static equilibrium the four
support reactions add up to the load, wherever it stands.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from trendmill.protocol.constants import CHANNEL_NAMES

Floats4 = tuple[float, float, float, float]

class Method:
    MANUAL = "manual"
    #: The values in the defaults file. A profile with this method is re-read from
    #: that file at every start, so editing the file changes what every calculation uses.
    DEFAULTS = "defaults"
    ONE_CAPTURE = "one_capture"
    FOUR_POSITION = "four_position"
    FOUR_POSITION_SHARED = "four_position_shared"


@dataclass(frozen=True)
class CalibrationProfile:
    zeros: Floats4
    counts_per_kg: Floats4
    method: str
    created_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )
    #: The board's bcdDevice when this was made. A different firmware may scale the ADC
    #: differently -- the September 32,400 vs 1,856 counts/kg problem.
    firmware_bcd: str | None = None
    known_weight_kg: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if len(self.zeros) != 4 or len(self.counts_per_kg) != 4:
            raise ValueError("a profile needs four zeros and four coefficients")
        if not all(math.isfinite(z) for z in self.zeros):
            raise ValueError("every zero must be a finite number")
        if not all(math.isfinite(c) and c != 0 for c in self.counts_per_kg):
            raise ValueError("every coefficient must be a finite, non-zero number")

    def cell_kg(self, raw: tuple[int, ...] | tuple[float, ...]) -> list[float]:
        return [(r - z) / c for r, z, c in zip(raw, self.zeros, self.counts_per_kg, strict=True)]

    def total_kg(self, raw: tuple[int, ...] | tuple[float, ...]) -> float:
        return sum(self.cell_kg(raw))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["zeros"] = list(self.zeros)
        d["counts_per_kg"] = list(self.counts_per_kg)
        d["cells"] = list(CHANNEL_NAMES)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CalibrationProfile:
        return cls(
            zeros=_four(d["zeros"]),
            counts_per_kg=_four(d["counts_per_kg"]),
            method=str(d.get("method", Method.MANUAL)),
            created_at=str(d.get("created_at") or dt.datetime.now(dt.UTC).isoformat(timespec="seconds")),
            firmware_bcd=d.get("firmware_bcd"),
            known_weight_kg=d.get("known_weight_kg"),
            note=str(d.get("note", "")),
        )


def _four(values: Any) -> Floats4:
    items = [float(v) for v in values]
    if len(items) != 4:
        raise ValueError("expected four values")
    return (items[0], items[1], items[2], items[3])
