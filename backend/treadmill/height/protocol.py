"""Commands sent to the belt-height controller.

The height mechanism is a second microcontroller — an STM32 driving two steppers
through a trapezoidal motion profile — and it is *not* the board that streams the
load cells. It has no USB of its own in the firmware as written, only USART2.

So commands reach it the way the treadmill's do not: down the same USB cable the
load cells use, on the bulk OUT endpoint of the load-cell board, which then
relays the bytes to the STM32's UART. Both firmwares need work for that; see
`docs/height-firmware.md` for exactly what.

The frame is deliberately tiny and self-describing. USB already CRCs every
packet, so the magic exists to let the relay resynchronise if it ever starts
mid-stream, not to detect corruption.

    offset  size  field
    0       2     magic, 'H' 'T'
    2       1     opcode
    3       1     sequence, wrapping — lets the board ignore a repeat
    4       4     parameter, int32 little-endian (millimetres, or 0)
                                                            = 8 bytes
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"HT"
FRAME_SIZE = 8

#: The mechanism's travel, from the specification. The firmware itself enforces
#: nothing, so the host must: `move_motor` happily drives past either end.
MIN_HEIGHT_MM = 20
MAX_HEIGHT_MM = 750
#: One press of + or −.
STEP_MM = 10


class Opcode(IntEnum):
    #: Drive to an absolute height in millimetres, measured from the home switch.
    MOVE_TO = 0x01
    #: Seek the limit switches and make that position zero. Required after power
    #: on: until it happens, nothing knows where the belt actually is.
    HOME = 0x02
    #: Abandon the current move and decelerate to a stop.
    STOP = 0x03


def frame(opcode: Opcode, param: int = 0, seq: int = 0) -> bytes:
    """Builds one command frame."""
    return MAGIC + bytes([int(opcode), seq & 0xFF]) + int(param).to_bytes(4, "little", signed=True)


def move_to(height_mm: int, seq: int = 0) -> bytes:
    return frame(Opcode.MOVE_TO, height_mm, seq)


def home(seq: int = 0) -> bytes:
    return frame(Opcode.HOME, 0, seq)


def stop(seq: int = 0) -> bytes:
    return frame(Opcode.STOP, 0, seq)


@dataclass(frozen=True, slots=True)
class Command:
    opcode: Opcode
    param: int
    seq: int


def parse(data: bytes) -> Command | None:
    """Decodes a frame. Used by the simulator and the tests — and by whoever
    writes the board's side, as the reference for what to expect."""
    if len(data) < FRAME_SIZE or data[0:2] != MAGIC:
        return None
    try:
        opcode = Opcode(data[2])
    except ValueError:
        return None
    return Command(opcode, int.from_bytes(data[4:8], "little", signed=True), data[3])


def clamp(height_mm: float) -> int:
    """Onto the travel, and onto the 10 mm grid the operator works in."""
    stepped = round(height_mm / STEP_MM) * STEP_MM
    return int(min(max(stepped, MIN_HEIGHT_MM), MAX_HEIGHT_MM))


# ---------------------------------------------------------------- timing

# The firmware's motion profile, mirrored here so the console can say how long a
# move will take. There is no position feedback from the mechanism — nothing
# reports back — so "moving" is a timer, and it has to match the firmware's own
# arithmetic or the console will claim the belt has arrived before it has.
PULSES_PER_MM = 100
START_SPEED = 200.0  # pulses/s
MAX_SPEED = 2000.0
STOP_SPEED = 200.0
ACCELERATION = 400.0  # pulses/s²
DECELERATION = 400.0


def _ramp_pulses(fast: float, slow: float, rate: float) -> float:
    return (fast * fast - slow * slow) / (2.0 * rate)


def move_seconds(distance_mm: float) -> float:
    """How long the mechanism takes to travel `distance_mm`, plus a margin.

    Mirrors `move_motor`: a trapezoid when there is room to reach MAX_SPEED, and
    a triangle when there is not.
    """
    pulses = abs(distance_mm) * PULSES_PER_MM
    if pulses <= 0:
        return 0.0
    accel = _ramp_pulses(MAX_SPEED, START_SPEED, ACCELERATION)
    decel = _ramp_pulses(MAX_SPEED, STOP_SPEED, DECELERATION)
    if pulses >= accel + decel:
        t = (MAX_SPEED - START_SPEED) / ACCELERATION
        t += (MAX_SPEED - STOP_SPEED) / DECELERATION
        t += (pulses - accel - decel) / MAX_SPEED
    else:
        # Solving N = (Vp²-Vs²)/2a + (Vp²-Vf²)/2d for the peak speed reached.
        peak_sq = (2.0 * pulses + START_SPEED**2 / ACCELERATION + STOP_SPEED**2 / DECELERATION) / (
            1.0 / ACCELERATION + 1.0 / DECELERATION
        )
        peak = min(peak_sq**0.5, MAX_SPEED)
        t = (peak - START_SPEED) / ACCELERATION + (peak - STOP_SPEED) / DECELERATION
    return t * 1.15 + 0.3  # the firmware busy-waits, so it runs a little slow


#: Homing has no distance to work from: it crawls until it finds the switches.
HOME_TIMEOUT_S = MAX_HEIGHT_MM * PULSES_PER_MM / 500.0
