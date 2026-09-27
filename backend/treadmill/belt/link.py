"""The transport contract, and a simulated treadmill that satisfies it.

The controller above never imports bleak. It talks to a [TreadmillLink], which is
either the real BLE link or [SimulatedTreadmill] — the same split that lets the
load-cell pipeline run identically on USB, the simulator and a replay file, and
what makes the whole session flow testable on a Mac with no treadmill in the room.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Protocol

from treadmill.belt import ftms

Notify = Callable[[str, bytes], None]


class TreadmillLink(Protocol):
    """One connection to one fitness machine."""

    name: str

    async def connect(self, on_notify: Notify) -> str:
        """Finds the machine, subscribes, and returns its advertised name.

        Raises `TreadmillUnavailable` when there is nothing to connect to, and
        `ConnectionError` for anything else that went wrong.
        """
        ...

    async def write(self, payload: bytes) -> None:
        """Writes one frame to the control point."""
        ...

    async def read(self, characteristic: str) -> bytes | None:
        """Reads a characteristic, or returns None when the machine lacks it."""
        ...

    async def disconnect(self) -> None: ...

    @property
    def connected(self) -> bool: ...


class TreadmillUnavailable(Exception):
    """No machine to talk to: radio off, nothing advertising, or no BLE support."""


class SimulatedTreadmill:
    """A treadmill that lives in this process, for testing without the hardware.

    It answers every command the way the real machine does — including requiring
    control before it obeys anything — and broadcasts Treadmill Data once a
    second with a belt speed that ramps towards the target rather than jumping,
    because the ramp is what the +/- handling has to cope with.
    """

    name = "sim"

    RAMP_KPH_PER_S = 1.2

    def __init__(self, *, connect_delay_s: float = 0.0, broadcast_s: float = 1.0) -> None:
        self._notify: Notify | None = None
        self._connected = False
        self._task: asyncio.Task[None] | None = None
        self._connect_delay_s = connect_delay_s
        self._broadcast_s = broadcast_s
        self._controlled = False
        self._running = False
        self._target_kph = 0.0
        self._belt_kph = 0.0
        self._incline = 0.0
        self._last_tick = time.monotonic()
        #: Every frame written, so a test can assert on the wire, not on a mock.
        self.written: list[bytes] = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def belt_kph(self) -> float:
        return self._belt_kph

    async def connect(self, on_notify: Notify) -> str:
        if self._connect_delay_s:
            await asyncio.sleep(self._connect_delay_s)
        self._notify = on_notify
        self._connected = True
        self._last_tick = time.monotonic()
        if self._broadcast_s > 0:
            self._task = asyncio.create_task(self._broadcast(), name="sim-treadmill")
        return "Simulated treadmill"

    async def disconnect(self) -> None:
        self._connected = False
        self._controlled = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def read(self, characteristic: str) -> bytes | None:
        if characteristic == ftms.SUPPORTED_SPEED_RANGE:
            #: 1.00–12.00 km/h in 0.10 steps, as the spec sheet describes.
            return (100).to_bytes(2, "little") + (1200).to_bytes(2, "little") + (10).to_bytes(2, "little")
        if characteristic == ftms.SUPPORTED_INCLINATION_RANGE:
            return (
                (0).to_bytes(2, "little", signed=True)
                + (150).to_bytes(2, "little", signed=True)
                + (10).to_bytes(2, "little")
            )
        return None

    async def write(self, payload: bytes) -> None:
        if not self._connected:
            raise ConnectionError("not connected")
        self.written.append(bytes(payload))
        opcode = payload[0]
        result = 0x01
        if opcode == ftms.OP_REQUEST_CONTROL:
            self._controlled = True
        elif not self._controlled:
            result = 0x05  # control not permitted, exactly as the machine replies
        elif opcode == ftms.OP_START_OR_RESUME:
            self._running = True
        elif opcode == ftms.OP_STOP_OR_PAUSE:
            self._running = False
            self._target_kph = 0.0
        elif opcode == ftms.OP_SET_TARGET_SPEED:
            self._target_kph = int.from_bytes(payload[1:3], "little") * 0.01
            self._emit(ftms.FITNESS_MACHINE_STATUS, bytes([0x05]) + payload[1:3])
        elif opcode == ftms.OP_SET_TARGET_INCLINATION:
            self._incline = int.from_bytes(payload[1:3], "little", signed=True) * 0.1
            self._emit(ftms.FITNESS_MACHINE_STATUS, bytes([0x06]) + payload[1:3])
        elif opcode == ftms.OP_RESET:
            self._running = False
            self._controlled = False
            self._target_kph = 0.0
        self._emit(ftms.CONTROL_POINT, bytes([ftms.OP_RESPONSE_CODE, opcode, result]))

    def press_stop_on_the_console(self) -> None:
        """Someone reached over and stopped the belt: the case the console must notice."""
        self._running = False
        self._target_kph = 0.0
        self._emit(ftms.FITNESS_MACHINE_STATUS, bytes([0x02]))

    def pull_safety_key(self) -> None:
        self._running = False
        self._target_kph = 0.0
        self._belt_kph = 0.0
        self._emit(ftms.FITNESS_MACHINE_STATUS, bytes([0x03]))

    def tick(self, dt_s: float) -> None:
        """Advances the belt towards its target. Called by the broadcast loop."""
        goal = self._target_kph if self._running else 0.0
        change = self.RAMP_KPH_PER_S * dt_s
        if abs(goal - self._belt_kph) <= change:
            self._belt_kph = goal
        else:
            self._belt_kph += change if goal > self._belt_kph else -change

    def data_frame(self) -> bytes:
        """Speed and inclination present: flags 0x0008 with bit 0 clear."""
        return (
            (0x0008).to_bytes(2, "little")
            + round(self._belt_kph * 100).to_bytes(2, "little")
            + round(self._incline * 10).to_bytes(2, "little", signed=True)
            + round(self._incline * 10).to_bytes(2, "little", signed=True)
        )

    def _emit(self, characteristic: str, payload: bytes) -> None:
        if self._notify is not None and self._connected:
            self._notify(characteristic, payload)

    async def _broadcast(self) -> None:
        while True:
            await asyncio.sleep(self._broadcast_s)
            now = time.monotonic()
            self.tick(now - self._last_tick)
            self._last_tick = now
            self._emit(ftms.TREADMILL_DATA, self.data_frame())
