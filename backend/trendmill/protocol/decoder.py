"""Decodes one 64-byte USB transfer into four samples of four channels.

Layout (sample-major, little-endian int32)::

    offset  0: ch0 ch1 ch2 ch3   sample 1 (oldest)
    offset 16: ch0 ch1 ch2 ch3   sample 2
    offset 32: ch0 ch1 ch2 ch3   sample 3
    offset 48: ch0 ch1 ch2 ch3   sample 4 (newest)

There is no header, timestamp or checksum; see `StreamProcessor` in `trendmill/processor.py`
for alignment and timing.
"""

from __future__ import annotations

import struct

from trendmill.protocol.constants import (
    ADC_MAX,
    ADC_MIN,
    CHANNELS,
    PACKET_SIZE,
    SAMPLES_PER_PACKET,
)

Quad = tuple[int, int, int, int]

_PACKET = struct.Struct(f"<{SAMPLES_PER_PACKET * CHANNELS}i")


def decode_packet(data: bytes) -> list[Quad]:
    """Returns the packet's four samples, oldest first, each as (ch0, ch1, ch2, ch3)."""
    if len(data) != PACKET_SIZE:
        raise ValueError(f"expected {PACKET_SIZE} bytes, got {len(data)}")
    values = _PACKET.unpack(data)
    return [
        (values[i], values[i + 1], values[i + 2], values[i + 3])
        for i in range(0, SAMPLES_PER_PACKET * CHANNELS, CHANNELS)
    ]


def encode_packet(samples: list[Quad]) -> bytes:
    """Inverse of `decode_packet`; used by the simulator."""
    if len(samples) != SAMPLES_PER_PACKET:
        raise ValueError(f"a packet carries {SAMPLES_PER_PACKET} samples")
    flat: list[int] = []
    for sample in samples:
        flat.extend(sample)
    return _PACKET.pack(*flat)


def in_adc_range(value: int) -> bool:
    """False for a value the 24-bit ADC cannot produce: a corrupt read."""
    return ADC_MIN <= value <= ADC_MAX
