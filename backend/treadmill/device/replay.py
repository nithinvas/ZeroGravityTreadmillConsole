"""Replays a recording through the live pipeline, as if the board were attached."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from treadmill.device.base import LinkState, StateChange, StateSink, Transfer, TransferSink
from treadmill.logs import get_logger, log_event
from treadmill.storage.raw_format import header_of, iter_records

log = get_logger("usb")


def segment_files(path: Path) -> list[Path]:
    """A recording directory's segment files in order, or a single file."""
    if path.is_dir():
        return sorted(path.glob("segment-*.tmraw"))
    return [path]


class ReplaySource:
    def __init__(self, path: Path, speed: float = 1.0, loop: bool = False) -> None:
        """`speed` 1.0 is real time; 0 replays as fast as the pipeline accepts."""
        self.name = f"replay:{path.name}"
        self._path = path
        self._speed = speed
        self._loop = loop

    def run(self, sink: TransferSink, on_state: StateSink, stop: threading.Event) -> None:
        files = [f for f in segment_files(self._path) if f.is_file()]
        if not files:
            log_event(log, logging.ERROR, "usb.replay_missing", f"No recording found at {self._path}")
            on_state(StateChange(LinkState.STOPPED, f"No recording found at {self._path}"))
            return
        while not stop.is_set():
            for number, file in enumerate(files, start=1):
                try:
                    header = header_of(file)
                except (OSError, ValueError) as error:
                    log_event(log, logging.ERROR, "usb.replay_unreadable", f"Cannot replay {file}: {error}")
                    continue
                device = {"vid": f"{header.vid:04x}", "pid": f"{header.pid:04x}",
                          "bcd_device": f"{header.bcd_device:04x}", "product": f"replay of {file.name}"}
                log_event(log, logging.INFO, "usb.connected", f"Replaying {file}", segment=number)
                on_state(StateChange(LinkState.STREAMING, "Replaying", device=device, segment=number))
                self._play(file, number, sink, stop)
                if stop.is_set():
                    break
            if not self._loop:
                break
        on_state(StateChange(LinkState.STOPPED, "Replay finished"))

    def _play(self, file: Path, segment: int, sink: TransferSink, stop: threading.Event) -> None:
        wall_start = time.monotonic_ns()
        first: int | None = None
        for arrival_ns, data in iter_records(file):
            if stop.is_set():
                return
            if first is None:
                first = arrival_ns
            if self._speed > 0:
                due = wall_start + (arrival_ns - first) / self._speed
                wait = due - time.monotonic_ns()
                if wait > 0:
                    stop.wait(wait / 1e9)
            # The recorded arrival time is kept: timing reproduces exactly.
            sink(Transfer(arrival_ns=arrival_ns, data=data, segment=segment))
