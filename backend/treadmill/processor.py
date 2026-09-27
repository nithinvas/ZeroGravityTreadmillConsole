"""Turns USB transfers into timestamped samples and keeps the health counters.

Synchronous and free of I/O, so the whole path from bytes to samples is tested
directly, and replay produces exactly what live streaming produced.
"""

from __future__ import annotations

from dataclasses import dataclass

from treadmill.device.base import Transfer
from treadmill.logs import WarningAggregator, get_logger
from treadmill.protocol.constants import PACKET_SIZE, SAMPLES_PER_PACKET
from treadmill.protocol.decoder import Quad, decode_packet, in_adc_range
from treadmill.protocol.health import StreamHealth
from treadmill.protocol.sample_clock import SampleClock

log = get_logger("decoder")


@dataclass(frozen=True, slots=True)
class Sample:
    t_us: int
    values: Quad
    segment: int


class StreamProcessor:
    def __init__(self, health: StreamHealth, nominal_rate_hz: float,
                 warnings: WarningAggregator | None = None) -> None:
        self.health = health
        self.clock = SampleClock(1_000_000.0 / nominal_rate_hz)
        self._warnings = warnings or WarningAggregator(log)
        self._segment: int | None = None
        self.latest: Sample | None = None

    def process(self, transfer: Transfer) -> list[Sample]:
        counters = self.health.counters
        counters.transfers += 1
        counters.bytes += len(transfer.data)

        if transfer.segment != self._segment:
            # A new connection: never carry timing or statistics across it.
            self._segment = transfer.segment
            self.clock.reset()
            self.health.reset_segment()

        if len(transfer.data) != PACKET_SIZE:
            counters.short_transfers += 1
            self._warnings.note("decoder.short_transfer",
                                f"Discarded a {len(transfer.data)}-byte transfer",
                                length=len(transfer.data), segment=transfer.segment)
            return []

        arrival_us = transfer.arrival_ns // 1000
        quads = decode_packet(transfer.data)
        stamps = self.clock.stamp(SAMPLES_PER_PACKET, arrival_us)
        self.health.rate.add(arrival_us, SAMPLES_PER_PACKET)

        samples: list[Sample] = []
        for t_us, quad in zip(stamps, quads, strict=True):
            if not all(in_adc_range(v) for v in quad):
                counters.out_of_range += 1
                self._warnings.note("decoder.out_of_range",
                                    "A value outside the 24-bit ADC range was discarded",
                                    values=list(quad), segment=transfer.segment)
                continue
            self.health.add_sample(t_us, quad)
            samples.append(Sample(t_us, quad, transfer.segment))
        counters.samples += len(samples)
        if samples:
            self.latest = samples[-1]
        return samples

    def flush_warnings(self) -> None:
        self._warnings.flush()

