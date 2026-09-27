"""The contract every packet source follows: real USB, simulator, or replay.

A source runs a blocking loop on its own thread and hands each USB transfer to a
sink the moment it arrives. It reports connection changes through `on_state`.
Everything above this layer is identical whichever source is in use, which is
what lets the Mac, the N100 and the tests exercise the same pipeline.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Transfer:
    """One USB transfer, exactly as it arrived."""

    arrival_ns: int
    data: bytes
    segment: int


class LinkState(StrEnum):
    WAITING = "waiting"  # looking for the device
    STREAMING = "streaming"
    DISCONNECTED = "disconnected"
    STOPPED = "stopped"


@dataclass(frozen=True)
class StateChange:
    state: LinkState
    detail: str = ""
    device: dict[str, Any] = field(default_factory=dict)
    segment: int = 0


TransferSink = Callable[[Transfer], None]
StateSink = Callable[[StateChange], None]


class PacketSource(Protocol):
    name: str

    def run(self, sink: TransferSink, on_state: StateSink, stop: threading.Event) -> None:
        """Blocks until `stop` is set. Must never raise: report failures via `on_state`."""
        ...
