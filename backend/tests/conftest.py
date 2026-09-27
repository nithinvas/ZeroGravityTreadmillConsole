from __future__ import annotations

import struct

import pytest

# The tests keep their own encoder rather than importing the production one, so a
# bug cannot hide by being mirrored on both sides.
_PACK = struct.Struct("<16i")


def packet(*samples: tuple[int, int, int, int]) -> bytes:
    """A 64-byte transfer from four (ch0, ch1, ch2, ch3) samples, oldest first."""
    assert len(samples) == 4
    return _PACK.pack(*[v for s in samples for v in s])


def numbered(base: int = 0) -> bytes:
    """Every value distinct: sample s, channel c holds base + 10*(s+1) + (c+1)."""
    return packet(*[tuple(base + 10 * (s + 1) + (c + 1) for c in range(4)) for s in range(4)])  # type: ignore[misc]


def buggy_firmware_packet(readings: list[tuple[int, int, int, int]]) -> bytes:
    """What main.c actually sends: the `payload_index += 1` loop, ported line for line."""
    assert len(readings) == 16
    adc = [0] * 19  # three extra words: the firmware writes past the end of adc_samples[16]
    payload_index = 0
    for ch0, ch1, ch2, ch3 in readings:
        if payload_index <= 15:
            adc[payload_index] = ch0
            adc[payload_index + 1] = ch1
            adc[payload_index + 2] = ch2
            adc[payload_index + 3] = ch3
            payload_index += 1
        if payload_index > 15:
            break
    return _PACK.pack(*adc[:16])


@pytest.fixture
def distinct_readings() -> list[tuple[int, int, int, int]]:
    """Sixteen readings with each channel at its own, very different level."""
    return [(1000 + e, 2000 + e, 3000 + e, 4000 + e) for e in range(16)]
