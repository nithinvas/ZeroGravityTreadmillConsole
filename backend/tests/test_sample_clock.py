from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from treadmill.protocol.sample_clock import SampleClock

NOMINAL_US = 1_000_000 / 976.5625  # 1024 us


def feed(clock: SampleClock, arrivals: list[int]) -> list[int]:
    stamps: list[int] = []
    for arrival in arrivals:
        stamps.extend(clock.stamp(4, arrival))
    return stamps


def test_first_packet_is_spread_by_the_nominal_period() -> None:
    stamps = SampleClock(NOMINAL_US).stamp(4, 1_000_000)

    assert stamps == [996_928, 997_952, 998_976, 1_000_000]


def test_tracks_976_samples_per_second() -> None:
    clock = SampleClock(NOMINAL_US)
    arrivals = [round(i * 4 * NOMINAL_US) for i in range(300)]
    stamps = feed(clock, arrivals)

    assert abs(clock.observed_period_us - NOMINAL_US) < 1.0
    gaps = [b - a for a, b in zip(stamps[-40:], stamps[-39:], strict=False)]
    assert all(abs(g - NOMINAL_US) <= 2 for g in gaps)


def test_learns_a_rate_far_from_nominal() -> None:
    # The firmware's OSR 16384 with an 8.192 MHz clock would give 250 Sa/s, not 976.5625.
    clock = SampleClock(NOMINAL_US)
    feed(clock, [i * 16_000 for i in range(100)])

    assert abs(clock.observed_period_us - 4_000) < 20


def test_never_runs_backwards_under_bursty_delivery() -> None:
    clock = SampleClock(NOMINAL_US)
    arrivals = [0, 4_096, 8_192, 8_300, 8_350, 20_000, 24_096, 24_100, 60_000, 64_096]
    stamps = feed(clock, arrivals)

    assert all(b >= a for a, b in zip(stamps, stamps[1:], strict=False))


def test_snaps_to_arrival_after_a_stall() -> None:
    clock = SampleClock(NOMINAL_US)
    feed(clock, [round(i * 4 * NOMINAL_US) for i in range(50)])
    after = clock.stamp(4, 5_000_000_000)

    assert after[-1] == 5_000_000_000


def test_relearns_after_a_real_rate_change() -> None:
    clock = SampleClock(NOMINAL_US)
    arrivals = [round(i * 4 * NOMINAL_US) for i in range(50)]
    last = arrivals[-1]
    arrivals += [last + k * 40_000 for k in range(1, 40)]  # 10x slower from here
    feed(clock, arrivals)

    assert abs(clock.observed_period_us - 10_000) < 500


@settings(max_examples=200)
@given(st.lists(st.integers(0, 50_000), min_size=2, max_size=60))
def test_monotonic_for_any_arrival_gaps(gaps: list[int]) -> None:
    clock = SampleClock(NOMINAL_US)
    t = 0
    arrivals = []
    for gap in gaps:
        t += gap
        arrivals.append(t)
    stamps = feed(clock, arrivals)

    assert all(b >= a for a, b in zip(stamps, stamps[1:], strict=False))
