from __future__ import annotations

import random

from tests.conftest import buggy_firmware_packet, packet
from treadmill.device.base import Transfer
from treadmill.device.simulator import SimulatedBoard
from treadmill.processor import StreamProcessor
from treadmill.protocol.health import RateMeter, StreamHealth

RATE = 976.5625
PERIOD_NS = round(4 * 1e9 / RATE)


def run(transfers: list[bytes], period_ns: int = PERIOD_NS, rate: float = RATE) -> StreamHealth:
    health = StreamHealth(rate)
    processor = StreamProcessor(health, rate)
    for i, data in enumerate(transfers):
        processor.process(Transfer(arrival_ns=i * period_ns, data=data, segment=1))
    return health


def test_rate_meter_measures_samples_per_second() -> None:
    meter = RateMeter()
    for i in range(500):
        meter.add(i * 4096, 4)

    assert meter.rate_hz is not None and abs(meter.rate_hz - RATE) < 1
    assert meter.session_rate_hz is not None and abs(meter.session_rate_hz - RATE) < 1


def test_rate_meter_needs_two_transfers() -> None:
    meter = RateMeter()
    meter.add(0, 4)

    assert meter.rate_hz is None


def test_real_channels_are_not_flagged_as_identical() -> None:
    board = SimulatedBoard(rate_hz=RATE)
    health = run([board.packet(i * 4) for i in range(300)])

    assert "channels_identical" not in {w.code for w in health.warnings(streaming=True)}


def test_the_packing_bug_is_detected() -> None:
    rng = random.Random(3)
    transfers = []
    for _ in range(120):
        readings = [(-536_000 + rng.randint(-150, 150), 101_000, 694_000, -19_000) for _ in range(16)]
        transfers.append(buggy_firmware_packet(readings))
    health = run(transfers, period_ns=PERIOD_NS * 4)

    assert "channels_identical" in {w.code for w in health.warnings(streaming=True)}


def test_simulated_packing_bug_is_detected() -> None:
    board = SimulatedBoard(rate_hz=RATE, packing_bug=True)
    health = run([board.packet(i * 16) for i in range(100)], period_ns=PERIOD_NS * 4)

    assert "channels_identical" in {w.code for w in health.warnings(streaming=True)}


def test_rate_mismatch_is_reported_after_five_seconds() -> None:
    # Transfers arriving at 250 Sa/s while 976.5625 is configured.
    transfers = [packet((1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 3, 4))] * 400
    health = run(transfers, period_ns=16_000_000)

    codes = {w.code for w in health.warnings(streaming=True)}
    assert "rate_mismatch" in codes


def test_no_rate_verdict_in_the_first_seconds() -> None:
    transfers = [packet((1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 3, 4))] * 50
    health = run(transfers, period_ns=16_000_000)  # 0.8 s

    assert "rate_mismatch" not in {w.code for w in health.warnings(streaming=True)}
