"""The Bluetooth SIG Fitness Machine Service, as this treadmill speaks it.

Pure encoding and decoding: no BLE stack, no I/O, no asyncio. Everything here can
be exercised from a unit test, which is the same split the mobile app uses and the
reason its protocol bugs were found on the JVM rather than on the machine.

The numbers and the two hardware quirks below come from the app, where they were
confirmed against the real treadmill:

* **Stop is `08 01`, not `08 02`.** The supplied spec sheet documents `08 02` as
  stop. The machine accepts it with a success reply and then keeps running. `08 01`
  (the standard's Stop parameter) is what actually halts the belt.
* **Treadmill Data bit 0 is inverted.** It is named "More Data", and instantaneous
  speed is present when the bit is *clear*. Reading it the obvious way shifts every
  later field by two bytes and yields plausible nonsense.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

# ---------------------------------------------------------------- identifiers

BASE_UUID = "0000{:04x}-0000-1000-8000-00805f9b34fb"


def uuid16(short: int) -> str:
    """Expands a 16-bit assigned number into the full 128-bit form bleak wants."""
    return BASE_UUID.format(short)


FITNESS_MACHINE_SERVICE = uuid16(0x1826)
FITNESS_MACHINE_FEATURE = uuid16(0x2ACC)
TREADMILL_DATA = uuid16(0x2ACD)
FITNESS_MACHINE_STATUS = uuid16(0x2ADA)
CONTROL_POINT = uuid16(0x2AD9)
SUPPORTED_SPEED_RANGE = uuid16(0x2AD4)
SUPPORTED_INCLINATION_RANGE = uuid16(0x2AD5)

#: Everything the console subscribes to on connect.
NOTIFY_CHARACTERISTICS = (TREADMILL_DATA, FITNESS_MACHINE_STATUS, CONTROL_POINT)

# ---------------------------------------------------------------- control point

OP_REQUEST_CONTROL = 0x00
OP_RESET = 0x01
OP_SET_TARGET_SPEED = 0x02
OP_SET_TARGET_INCLINATION = 0x03
OP_START_OR_RESUME = 0x07
OP_STOP_OR_PAUSE = 0x08
OP_RESPONSE_CODE = 0x80

PARAM_STOP = 0x01
PARAM_PAUSE = 0x02

OPCODE_NAMES = {
    OP_REQUEST_CONTROL: "Request control",
    OP_RESET: "Reset",
    OP_SET_TARGET_SPEED: "Set speed",
    OP_SET_TARGET_INCLINATION: "Set inclination",
    OP_START_OR_RESUME: "Start belt",
    OP_STOP_OR_PAUSE: "Stop belt",
}


def opcode_name(opcode: int) -> str:
    return OPCODE_NAMES.get(opcode, f"Opcode 0x{opcode:02X}")


def request_control() -> bytes:
    return bytes([OP_REQUEST_CONTROL])


def reset() -> bytes:
    return bytes([OP_RESET])


def start() -> bytes:
    """Belt on. FTMS models this as start/resume, not a mains switch."""
    return bytes([OP_START_OR_RESUME])


def stop() -> bytes:
    """Belt off, with the parameter confirmed to work on this machine."""
    return bytes([OP_STOP_OR_PAUSE, PARAM_STOP])


def pause() -> bytes:
    """The parameter the spec sheet wrongly documents as stop. Kept for the tester."""
    return bytes([OP_STOP_OR_PAUSE, PARAM_PAUSE])


def set_speed(kph: float) -> bytes:
    """Speed travels as uint16 in units of 0.01 km/h, little-endian."""
    raw = min(max(round(kph * 100), 0), 0xFFFF)
    return bytes([OP_SET_TARGET_SPEED]) + raw.to_bytes(2, "little")


def set_inclination(percent: float) -> bytes:
    """Inclination travels as sint16 in units of 0.1 %, little-endian."""
    raw = min(max(round(percent * 10), -32768), 32767)
    return bytes([OP_SET_TARGET_INCLINATION]) + raw.to_bytes(2, "little", signed=True)


class Result(StrEnum):
    SUCCESS = "Accepted"
    NOT_SUPPORTED = "This machine does not support that command"
    INVALID_PARAMETER = "Value outside the range the machine accepts"
    OPERATION_FAILED = "The machine refused the command"
    NOT_PERMITTED = "Control was not granted — request control first"
    UNKNOWN = "Unrecognised reply"


_RESULTS = {
    0x01: Result.SUCCESS,
    0x02: Result.NOT_SUPPORTED,
    0x03: Result.INVALID_PARAMETER,
    0x04: Result.OPERATION_FAILED,
    0x05: Result.NOT_PERMITTED,
}


@dataclass(frozen=True, slots=True)
class ControlResponse:
    opcode: int
    result: Result

    @property
    def ok(self) -> bool:
        return self.result is Result.SUCCESS

    @property
    def text(self) -> str:
        return f"{opcode_name(self.opcode)} → {self.result.value}"


def parse_response(data: bytes) -> ControlResponse | None:
    """Replies are always `0x80, <original opcode>, <result>`."""
    if len(data) < 3 or data[0] != OP_RESPONSE_CODE:
        return None
    return ControlResponse(data[1], _RESULTS.get(data[2], Result.UNKNOWN))


# ---------------------------------------------------------------- machine status


class Event(StrEnum):
    RESET = "Treadmill reset"
    STOPPED_BY_USER = "Stopped or paused at the console"
    #: The emergency clip. In a rehab setting this usually means a patient stumbled,
    #: and the console cannot clear it remotely.
    STOPPED_BY_SAFETY_KEY = "STOPPED — safety key removed"
    STARTED_BY_USER = "Started at the console"
    TARGET_SPEED_CHANGED = "Target speed changed"
    TARGET_INCLINE_CHANGED = "Target incline changed"
    OTHER = "Machine status update"


STOPPING_EVENTS = frozenset({Event.STOPPED_BY_USER, Event.STOPPED_BY_SAFETY_KEY, Event.RESET})


@dataclass(frozen=True, slots=True)
class MachineStatus:
    event: Event
    value: float | None
    opcode: int

    @property
    def stopped(self) -> bool:
        return self.event in STOPPING_EVENTS


_STATUS_OPCODES = {
    0x01: Event.RESET,
    0x02: Event.STOPPED_BY_USER,
    0x03: Event.STOPPED_BY_SAFETY_KEY,
    0x04: Event.STARTED_BY_USER,
    0x05: Event.TARGET_SPEED_CHANGED,
    0x06: Event.TARGET_INCLINE_CHANGED,
}


def parse_machine_status(data: bytes) -> MachineStatus | None:
    """One opcode byte, then parameters whose width depends on the event."""
    if not data:
        return None
    opcode = data[0]
    event = _STATUS_OPCODES.get(opcode, Event.OTHER)
    value: float | None = None
    if event is Event.TARGET_SPEED_CHANGED and len(data) >= 3:
        value = int.from_bytes(data[1:3], "little") * 0.01
    elif event is Event.TARGET_INCLINE_CHANGED and len(data) >= 3:
        value = int.from_bytes(data[1:3], "little", signed=True) * 0.1
    return MachineStatus(event, value, opcode)


# ---------------------------------------------------------------- treadmill data

#: FTMS "value not available": every bit set for the field's width.
NOT_AVAILABLE_U16 = 0xFFFF
NOT_AVAILABLE_U8 = 0xFF


@dataclass(frozen=True, slots=True)
class TreadmillData:
    speed_kph: float | None = None
    average_speed_kph: float | None = None
    total_distance_m: int | None = None
    inclination_percent: float | None = None
    ramp_angle_degrees: float | None = None
    total_energy_kcal: int | None = None
    heart_rate_bpm: int | None = None
    elapsed_time_s: int | None = None
    #: Kept for diagnostics when a field is unexpectedly absent.
    flags: int = 0


def parse_treadmill_data(data: bytes) -> TreadmillData | None:
    """Decodes the variable-length Treadmill Data broadcast (0x2ACD).

    The packet opens with a 16-bit flags word; each bit says whether one optional
    field follows, in a fixed order. Decoding is therefore walking the bit list
    and advancing a cursor by each present field's width.
    """
    if len(data) < 4:  # flags plus the mandatory speed field
        return None
    flags = int.from_bytes(data[0:2], "little")
    offset = 2

    def take(size: int) -> int | None:
        nonlocal offset
        if offset + size > len(data):
            return None
        start = offset
        offset += size
        return start

    def u(at: int | None, size: int, *, signed: bool = False) -> int | None:
        return None if at is None else int.from_bytes(data[at : at + size], "little", signed=signed)

    def bit(index: int) -> bool:
        return bool((flags >> index) & 1)

    def scaled(value: int | None, factor: float) -> float | None:
        return None if value is None else value * factor

    # Bit 0 set means "more data follows"; speed is present when it is CLEAR.
    speed = scaled(u(take(2), 2), 0.01) if not bit(0) else None
    average = scaled(u(take(2), 2), 0.01) if bit(1) else None
    distance = u(take(3), 3) if bit(2) else None

    inclination: float | None = None
    ramp: float | None = None
    if bit(3):  # inclination and ramp angle share one bit and always arrive as a pair
        inclination = scaled(u(take(2), 2, signed=True), 0.1)
        ramp = scaled(u(take(2), 2, signed=True), 0.1)
    if bit(4):
        take(2)
        take(2)  # elevation gain, positive and negative
    if bit(5):
        take(1)  # instantaneous pace
    if bit(6):
        take(1)  # average pace

    energy: int | None = None
    if bit(7):  # expended energy is a triple under one bit
        energy = _available(u(take(2), 2), NOT_AVAILABLE_U16)
        take(2)  # energy per hour
        take(1)  # energy per minute
    heart_rate = _available(u(take(1), 1), NOT_AVAILABLE_U8) if bit(8) else None
    if bit(9):
        take(1)  # metabolic equivalent
    elapsed = u(take(2), 2) if bit(10) else None

    return TreadmillData(
        speed_kph=speed,
        average_speed_kph=average,
        total_distance_m=distance,
        inclination_percent=inclination,
        ramp_angle_degrees=ramp,
        total_energy_kcal=energy,
        heart_rate_bpm=heart_rate,
        elapsed_time_s=elapsed,
        flags=flags,
    )


def _available(value: int | None, marker: int) -> int | None:
    return None if value is None or value == marker else value


def parse_range(data: bytes, scale: float, *, signed: bool) -> tuple[float, float, float] | None:
    """Supported Speed Range (0x2AD4) or Supported Inclination Range (0x2AD5).

    Both are three 16-bit values: minimum, maximum, increment. The increment is
    always unsigned even where the range itself is signed.
    """
    if len(data) < 6:
        return None
    def read(at: int) -> int:
        return int.from_bytes(data[at : at + 2], "little", signed=signed)

    increment = int.from_bytes(data[4:6], "little")  # always unsigned, even on a signed range
    return read(0) * scale, read(2) * scale, increment * scale


# ---------------------------------------------------------------- limits and steps


@dataclass(frozen=True, slots=True)
class Limits:
    """What the machine will accept. Read once at connect, with a spec-sheet fallback."""

    min_speed_kph: float = 1.0
    max_speed_kph: float = 12.0
    speed_step_kph: float = 0.1
    min_incline_percent: float = 0.0
    max_incline_percent: float = 15.0
    incline_step_percent: float = 1.0

    def with_speed_range(self, low: float, high: float, step: float) -> Limits:
        return replace(
            self,
            min_speed_kph=low,
            max_speed_kph=high,
            speed_step_kph=step if step > 0 else self.speed_step_kph,
        )

    def with_incline_range(self, low: float, high: float, step: float) -> Limits:
        return replace(
            self,
            min_incline_percent=low,
            max_incline_percent=high,
            incline_step_percent=step if step > 0 else self.incline_step_percent,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "min_speed_kph": round(self.min_speed_kph, 2),
            "max_speed_kph": round(self.max_speed_kph, 2),
            "speed_step_kph": round(self.speed_step_kph, 2),
            "min_incline_percent": round(self.min_incline_percent, 1),
            "max_incline_percent": round(self.max_incline_percent, 1),
            "incline_step_percent": round(self.incline_step_percent, 1),
        }


#: The spec sheet's range, used until the machine reports its own.
SPEC_SHEET_LIMITS = Limits()

#: Every session opens here, so a patient never steps onto a moving belt.
SESSION_START_SPEED_KPH = 1.0


def snap(value: float, step: float) -> float:
    """Rounds onto the machine's own increment grid.

    Repeated `+ 0.1` in binary floating point drifts (1.0999999999999999) and the
    machine quantises to 0.01 km/h on the wire, so without this a long run of
    presses can silently lose or gain a step at a rounding boundary.
    """
    if step <= 0:
        return value
    return round(round(value / step) * step, 4)


def next_target(current: float, steps: int, step: float, low: float, high: float) -> float:
    """The next absolute target, stepped from the last *requested* value.

    Never from the machine's reported speed: that reading lags the target by
    seconds while the motor ramps, so stepping from it means the value never
    advances. This is where the app's speed-stuck bug lived, and FTMS always
    carries an absolute target rather than a delta.
    """
    return min(max(snap(current + steps * step, step), low), high)
