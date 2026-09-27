"""A software load-cell board, for development and tests without hardware.

It produces real 64-byte transfers at the configured rate, so everything from the
decoder upwards runs exactly as with the board. It can also reproduce the
firmware's `payload_index += 1` packing bug, to demonstrate that the backend
detects it.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time

from treadmill.device.base import LinkState, StateChange, StateSink, Transfer, TransferSink
from treadmill.logs import get_logger, log_event
from treadmill.protocol.constants import DEFAULT_NOMINAL_RATE_HZ, SAMPLES_PER_PACKET
from treadmill.protocol.decoder import Quad, encode_packet

log = get_logger("usb")

# Zero offsets and per-cell sensitivities from the four-corner calibration made on
# the bench board (firmware 0100, 14.68 kg reference), so the simulator reads
# correctly with the saved default coefficients.
ZERO_OFFSETS = (-553_477, 405_763, -549_397, -63_667)
CELL_COUNTS_PER_KG = (-22_442.38, -21_816.8, -22_406.59, -21_849.17)


class SimulatedBoard:
    def __init__(
        self,
        rate_hz: float = DEFAULT_NOMINAL_RATE_HZ,
        packing_bug: bool = False,
        walker_kg: float = 60.0,
        cadence_spm: float = 105.0,
        noise_counts: float = 150.0,
        seed: int = 1,
    ) -> None:
        self.name = "simulator (packing bug)" if packing_bug else "simulator"
        self._rate = rate_hz
        self._bug = packing_bug
        self._walker_kg = walker_kg
        self._stride_hz = cadence_spm / 120.0
        self._noise = noise_counts
        self._rng = random.Random(seed)
        #: "walking", "static" (a weight at x, y) or "empty". Changed live from the API.
        self.mode = "walking"
        self.static_kg = 20.0
        self.static_x = 0.5  # 0 = left edge, 1 = right edge
        self.static_y = 0.5  # 0 = top edge, 1 = bottom edge

    def set_load(self, mode: str, kg: float = 0.0, x: float = 0.5, y: float = 0.5) -> None:
        if mode not in ("walking", "static", "empty"):
            raise ValueError(f"unknown simulator mode {mode!r}")
        self.mode = mode
        self.static_kg = max(0.0, kg)
        self.static_x = min(1.0, max(0.0, x))
        self.static_y = min(1.0, max(0.0, y))

    def sample(self, index: int) -> Quad:
        """The four channels at sample `index`: the current load plus noise."""
        if self.mode != "walking":
            kg = self.static_kg if self.mode == "static" else 0.0
            x, y = self.static_x, self.static_y
            # A rigid plate on four supports: each corner's share falls off linearly with distance.
            static_shares = ((1 - x) * (1 - y), x * (1 - y), x * y, (1 - x) * y)
            return tuple(  # type: ignore[return-value]
                int(zero + c * kg * share + self._rng.gauss(0.0, self._noise))
                for zero, c, share in zip(ZERO_OFFSETS, CELL_COUNTS_PER_KG, static_shares, strict=True)
            )
        t = index / self._rate
        phase = 2 * math.pi * self._stride_hz * t
        left = 0.5 + 0.35 * math.sin(phase)  # lateral weight shift, once per stride
        front = 0.5 + 0.2 * math.cos(2 * phase)  # fore-aft, once per step
        load = self._walker_kg * (1.0 + 0.1 * math.sin(2 * phase))
        shares = (left * front, (1 - left) * front, (1 - left) * (1 - front), left * (1 - front))
        return tuple(  # type: ignore[return-value]
            int(zero + c * load * share + self._rng.gauss(0.0, self._noise))
            for zero, c, share in zip(ZERO_OFFSETS, CELL_COUNTS_PER_KG, shares, strict=True)
        )

    def packet(self, first_index: int) -> bytes:
        if not self._bug:
            return encode_packet([self.sample(first_index + k) for k in range(SAMPLES_PER_PACKET)])
        # The firmware bug: 16 successive readings, keeping only channel 0 of each.
        channel0 = [self.sample(first_index + k)[0] for k in range(16)]
        return encode_packet([tuple(channel0[i:i + 4]) for i in range(0, 16, 4)])  # type: ignore[misc]

    def run(self, sink: TransferSink, on_state: StateSink, stop: threading.Event) -> None:
        samples_per_transfer = 16 if self._bug else SAMPLES_PER_PACKET
        period_ns = 1e9 * samples_per_transfer / self._rate
        device = {"vid": "sim", "pid": "sim", "product": self.name, "bcd_device": "0000"}
        log_event(log, logging.INFO, "usb.connected", f"Connected to {self.name}", segment=1)
        on_state(StateChange(LinkState.STREAMING, "Streaming", device=device, segment=1))
        start = time.monotonic_ns()
        sent = 0
        while not stop.is_set():
            data = self.packet(sent * samples_per_transfer)
            sink(Transfer(arrival_ns=time.monotonic_ns(), data=data, segment=1))
            sent += 1
            # Paced against a deadline so the long-run rate is exact despite sleep granularity.
            wait_ns = start + sent * period_ns - time.monotonic_ns()
            if wait_ns > 0:
                stop.wait(wait_ns / 1e9)
        on_state(StateChange(LinkState.STOPPED, "Simulator stopped"))
