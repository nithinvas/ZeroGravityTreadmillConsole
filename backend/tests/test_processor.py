from __future__ import annotations

from tests.conftest import numbered, packet
from treadmill.device.base import Transfer
from treadmill.processor import StreamProcessor
from treadmill.protocol.health import StreamHealth

RATE = 976.5625


def make() -> StreamProcessor:
    return StreamProcessor(StreamHealth(RATE), RATE)


def test_emits_four_timestamped_samples_per_transfer() -> None:
    p = make()
    samples = p.process(Transfer(arrival_ns=1_000_000_000, data=numbered(), segment=1))

    assert [s.values[0] for s in samples] == [11, 21, 31, 41]
    assert samples[-1].t_us == 1_000_000
    assert all(b.t_us > a.t_us for a, b in zip(samples, samples[1:], strict=False))


def test_short_transfer_is_counted_and_dropped() -> None:
    p = make()
    samples = p.process(Transfer(arrival_ns=0, data=b"\x13\x37\x42", segment=1))

    assert samples == []
    assert p.health.counters.short_transfers == 1
    assert p.health.counters.transfers == 1


def test_out_of_range_sample_is_counted_and_dropped() -> None:
    p = make()
    data = packet((1, 2, 3, 4), (2**24, 0, 0, 0), (5, 6, 7, 8), (9, 10, 11, 12))
    samples = p.process(Transfer(arrival_ns=0, data=data, segment=1))

    assert len(samples) == 3
    assert p.health.counters.out_of_range == 1


def test_new_segment_restarts_the_clock() -> None:
    p = make()
    for i in range(20):
        p.process(Transfer(arrival_ns=i * 4_096_000, data=numbered(), segment=1))
    later = p.process(Transfer(arrival_ns=60_000_000_000, data=numbered(), segment=2))

    assert later[-1].t_us == 60_000_000
    assert p.health.rate.elapsed_s == 0
