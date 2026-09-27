"""How a height command gets to the mechanism, and a stand-in for testing.

Same split as everywhere else in this console: the controller talks to an
interface, and what sits behind it is the real board, a simulation, or nothing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from treadmill.height import protocol


class HeightUnavailable(Exception):
    """There is no board to send to — unplugged, or not streaming yet."""


class HeightLink(Protocol):
    name: str

    async def send(self, payload: bytes) -> None:
        """Delivers one command frame. Raises `HeightUnavailable` if it cannot."""
        ...


class UsbHeightLink:
    """Sends on the load-cell board's bulk OUT endpoint.

    The board is owned by the reader thread, which is why this goes through the
    source's own `send` rather than touching the USB handle: one lock, one owner,
    and a command can never interleave with a bulk read.
    """

    name = "usb"

    def __init__(self, source: Any) -> None:
        self._source = source

    async def send(self, payload: bytes) -> None:
        send = getattr(self._source, "send", None)
        if send is None:
            raise HeightUnavailable("This packet source cannot send commands to the board.")
        # The write blocks on libusb, so it goes to a thread rather than stalling
        # the event loop that is also draining the sample queue.
        await asyncio.to_thread(send, payload)


class SimulatedHeightMechanism:
    """A deck that moves at the speed the real one does.

    Useful beyond tests: it lets the whole height workflow — homing, the 10 mm
    buttons, typing a height, the progress while it travels — be exercised on a
    console with no mechanism attached.
    """

    name = "sim"

    def __init__(self) -> None:
        self.commands: list[protocol.Command] = []
        self.height_mm: float = 0.0
        self.homed = False
        self._arrive_at = 0.0
        self._from_mm = 0.0
        self._to_mm = 0.0

    async def send(self, payload: bytes) -> None:
        command = protocol.parse(payload)
        if command is None:
            raise ConnectionError("malformed height frame")
        self.commands.append(command)
        now = time.monotonic()
        if command.opcode is protocol.Opcode.HOME:
            self._start(now, self.height_mm, protocol.MIN_HEIGHT_MM, protocol.HOME_TIMEOUT_S)
            self.homed = True
        elif command.opcode is protocol.Opcode.MOVE_TO:
            self._start(now, self.height_mm, float(command.param),
                        protocol.move_seconds(command.param - self.height_mm))
        elif command.opcode is protocol.Opcode.STOP:
            self.height_mm = self.position()
            self._arrive_at = now

    def _start(self, now: float, start: float, end: float, seconds: float) -> None:
        self._from_mm, self._to_mm = start, end
        self._started = now
        self._arrive_at = now + seconds

    def position(self) -> float:
        """Where the deck is now, interpolated along the move."""
        now = time.monotonic()
        if now >= self._arrive_at:
            self.height_mm = self._to_mm
            return self.height_mm
        span = self._arrive_at - getattr(self, "_started", now)
        if span <= 0:
            return self._to_mm
        fraction = (now - self._started) / span
        return self._from_mm + (self._to_mm - self._from_mm) * fraction
