from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.conftest import buggy_firmware_packet, numbered, packet
from treadmill.protocol.decoder import decode_packet, encode_packet, in_adc_range


def test_decodes_four_samples_of_four_channels_in_order() -> None:
    samples = decode_packet(numbered())

    assert samples == [(11, 12, 13, 14), (21, 22, 23, 24), (31, 32, 33, 34), (41, 42, 43, 44)]


def test_reads_little_endian() -> None:
    data = packet((0x04030201, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0))

    assert data[:4] == bytes([1, 2, 3, 4])
    assert decode_packet(data)[0][0] == 0x04030201


def test_values_are_signed() -> None:
    data = packet((-1, -184, -(2**31), 2**31 - 1), (0,) * 4, (0,) * 4, (0,) * 4)  # type: ignore[arg-type]

    assert decode_packet(data)[0] == (-1, -184, -(2**31), 2**31 - 1)


@pytest.mark.parametrize("length", [0, 3, 63, 65, 128])
def test_rejects_anything_but_64_bytes(length: int) -> None:
    with pytest.raises(ValueError):
        decode_packet(bytes(length))


def test_adc_range_is_24_bit_signed() -> None:
    assert in_adc_range(-(2**23)) and in_adc_range(2**23 - 1)
    assert not in_adc_range(2**23) and not in_adc_range(-(2**23) - 1)


def test_fixed_firmware_packing_keeps_channels_apart(distinct_readings: list[tuple[int, ...]]) -> None:
    fixed = packet(*distinct_readings[:4])  # type: ignore[arg-type]

    assert decode_packet(fixed)[0] == (1000, 2000, 3000, 4000)


def test_buggy_firmware_packing_sends_only_channel_0(distinct_readings: list[tuple[int, ...]]) -> None:
    # Documents what the current main.c produces: sixteen successive channel-0 readings.
    samples = decode_packet(buggy_firmware_packet(distinct_readings))  # type: ignore[arg-type]

    assert [v for s in samples for v in s] == list(range(1000, 1016))


@given(st.lists(st.tuples(*[st.integers(-(2**31), 2**31 - 1)] * 4), min_size=4, max_size=4))
def test_encode_then_decode_round_trips(samples: list[tuple[int, int, int, int]]) -> None:
    assert decode_packet(encode_packet(samples)) == samples
