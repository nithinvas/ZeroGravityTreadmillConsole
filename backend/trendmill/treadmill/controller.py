"""Treadmill control: connection, belt state, speed and inclination.

One controller owns the link for the life of the process. It deliberately
outlives any one session — a session starting is a command sent over an existing
link, not a reason to reconnect — and it keeps two things strictly apart:

* **what the console asked for** (`target_speed_kph`), and
* **what the machine reports** (`reported_speed_kph`).

Stepping from the second is the bug the mobile app hit twice: the broadcast
carries instantaneous belt speed, which lags the target by seconds while the
motor ramps, so `+` pressed twice quickly sends the same number both times and
the speed sticks. Every adjustment here moves the *target* and sends it
absolutely, and the two figures are shown side by side rather than reconciled
silently.

The reported speed is also never fed to the gait maths. Step and stride length
integrate the speed the operator selected, which is a known constant between
contacts; a ramping readback would smear every length across the change.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from trendmill.logs import get_logger, log_event
from trendmill.treadmill import ftms
from trendmill.treadmill.link import TreadmillLink, TreadmillUnavailable

log = get_logger("ble")

#: How long to wait for the machine's reply to a command before giving up on it.
RESPONSE_TIMEOUT_S = 4.0
#: Consecutive zero-speed broadcasts before the belt counts as stopped, when no
#: explicit stop event arrived. One stray frame during a ramp must not flip it.
ZERO_FRAMES_FOR_STOPPED = 3
#: A start command keeps the belt "running" this long even at zero reported speed,
#: which is how long the motor may take to move at all.
START_GRACE_S = 6.0
MAX_LOG_ENTRIES = 200


class ConnectionState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    READY = "ready"
    FAILED = "failed"


class TreadmillError(RuntimeError):
    """A command could not be carried out. The message is meant for the operator."""


@dataclass(frozen=True, slots=True)
class TreadmillEvent:
    """Something changed that the rest of the console may need to react to."""

    kind: str  # "belt" | "speed" | "incline" | "connection"
    detail: str
    speed_kph: float | None = None
    incline_percent: float | None = None
    running: bool | None = None


EventSink = Callable[[TreadmillEvent], None]


@dataclass(slots=True)
class LogLine:
    at: float
    direction: str  # "out" | "in" | "info" | "error"
    text: str
    hex: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "direction": self.direction, "text": self.text, "hex": self.hex}


class TreadmillController:
    def __init__(self, link: TreadmillLink | None, *, on_event: EventSink | None = None) -> None:
        self.link = link
        self.on_event = on_event
        self.state = ConnectionState.IDLE
        self.detail = "Not connected"
        self.device_name = ""
        self.has_control = False
        self.limits = ftms.SPEC_SHEET_LIMITS
        self.target_speed_kph: float | None = None
        self.target_incline_percent: float | None = None
        self.reported_speed_kph: float | None = None
        self.reported_incline_percent: float | None = None
        self.running = False
        self.last_error = ""
        #: Set when the safety key is pulled, and only cleared by a fresh start.
        self.safety_key_pulled = False
        self.log: list[LogLine] = []
        self._pending: dict[int, asyncio.Future[ftms.ControlResponse]] = {}
        self._command_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._zero_frames = 0
        self._started_at = 0.0
        #: Set by a stop command until the belt actually reaches zero. A treadmill
        #: coasts down over several seconds, and those non-zero frames must not be
        #: read as "the belt is moving" — that flipped the belt back to running and
        #: wrote a phantom condition at the old speed into the session.
        self._expect_stopped = False
        self._started_monotonic = time.monotonic()

    # ---- state ------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether this console has a treadmill link at all (`--treadmill none` has not)."""
        return self.link is not None

    @property
    def ready(self) -> bool:
        return self.state is ConnectionState.READY and self.link is not None and self.link.connected

    @property
    def can_control(self) -> bool:
        """Connected *and* granted control: anything less and commands are refused."""
        return self.ready and self.has_control

    def snapshot(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "backend": self.link.name if self.link is not None else None,
            "state": str(self.state),
            "detail": self.detail,
            "device_name": self.device_name,
            "connected": self.ready,
            "has_control": self.has_control,
            "running": self.running,
            "can_start": self.can_control and not self.running,
            "can_stop": self.can_control and self.running,
            # There is no speed to change on a stopped belt: it restarts at 1 km/h.
            "can_change_speed": self.can_control and self.running,
            "safety_key_pulled": self.safety_key_pulled,
            "target_speed_kph": _round(self.target_speed_kph, 2),
            "reported_speed_kph": _round(self.reported_speed_kph, 2),
            "target_incline_percent": _round(self.target_incline_percent, 1),
            "reported_incline_percent": _round(self.reported_incline_percent, 1),
            "limits": self.limits.as_dict(),
            "session_start_speed_kph": ftms.SESSION_START_SPEED_KPH,
            "last_error": self.last_error,
        }

    def recent_log(self, limit: int = 60) -> list[dict[str, Any]]:
        return [line.as_dict() for line in self.log[-limit:]]

    # ---- connecting -------------------------------------------------------

    async def connect(self) -> dict[str, Any]:
        """Finds and prepares the treadmill. Safe to call when already connected."""
        if self.link is None:
            raise TreadmillError(
                "This console was started without treadmill control "
                "(--treadmill none). Restart it with a treadmill backend to use the belt."
            )
        if self.ready:
            self._note("info", "Already connected — reusing the existing link")
            return self.snapshot()
        if self._connect_lock.locked():
            raise TreadmillError("A connection attempt is already running.")

        async with self._connect_lock:
            await self._drop_link()
            self._set_state(ConnectionState.CONNECTING, "Searching for the treadmill")
            try:
                name = await self.link.connect(self._on_notify)
            except TreadmillUnavailable as error:
                return self._fail(str(error))
            except (TimeoutError, ConnectionError, OSError) as error:
                return self._fail(str(error) or error.__class__.__name__)
            self.device_name = name
            self._set_state(ConnectionState.READY, f"Connected to {name}")
            self._note("info", f"Connected to {name}")
            await self._read_limits()
            await self._request_control()
            return self.snapshot()

    async def disconnect(self) -> dict[str, Any]:
        await self._drop_link()
        self._set_state(ConnectionState.IDLE, "Not connected")
        self._note("info", "Disconnected")
        return self.snapshot()

    async def _drop_link(self) -> None:
        self.has_control = False
        self.running = False
        self.target_speed_kph = None
        self.target_incline_percent = None
        self.reported_speed_kph = None
        self.reported_incline_percent = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self.link is not None:
            with contextlib.suppress(Exception):
                await self.link.disconnect()

    async def _read_limits(self) -> None:
        assert self.link is not None
        speed = await self.link.read(ftms.SUPPORTED_SPEED_RANGE)
        if speed is not None:
            parsed = ftms.parse_range(speed, 0.01, signed=False)
            if parsed is not None:
                self.limits = self.limits.with_speed_range(*parsed)
        incline = await self.link.read(ftms.SUPPORTED_INCLINATION_RANGE)
        if incline is not None:
            parsed = ftms.parse_range(incline, 0.1, signed=True)
            if parsed is not None:
                self.limits = self.limits.with_incline_range(*parsed)
        self._note("info", "Machine limits: "
                           f"{self.limits.min_speed_kph:.1f}–{self.limits.max_speed_kph:.1f} km/h "
                           f"in {self.limits.speed_step_kph:.2f}, "
                           f"incline {self.limits.min_incline_percent:.0f}–"
                           f"{self.limits.max_incline_percent:.0f}%")

    async def _request_control(self) -> bool:
        """Control must be granted before anything else is obeyed, and is lost on every drop."""
        response = await self._write(ftms.request_control())
        self.has_control = response is not None and response.ok
        if not self.has_control:
            self.detail = "Connected, but the treadmill did not grant control"
            self.last_error = self.detail
        return self.has_control

    # ---- commands ---------------------------------------------------------

    async def start_belt(self) -> dict[str, Any]:
        """Starts the belt at the slowest speed the machine has.

        Always that speed, never the one before the last stop: the belt is stopped
        exactly when somebody is stepping on or off it, and it must not come back
        at 6 km/h under them. It also matches the machine itself, which drops its
        target on stop — a bare start would otherwise leave a stationary belt
        under a console still reading the old speed.
        """
        await self._require_control()
        await self._command(ftms.start(), "Start belt")
        self.safety_key_pulled = False
        self._started_at = time.monotonic()
        self._zero_frames = 0
        self._expect_stopped = False
        # Running is set before the speed is sent, and announced after, so the rest
        # of the console sees one event carrying the speed the belt came up at —
        # rather than a speedless "started" followed by a separate speed change.
        self.running = True
        await self._apply_speed(self.start_speed_kph)
        self._announce_belt(True, "Belt started")
        return self.snapshot()

    @property
    def start_speed_kph(self) -> float:
        """Where the belt always starts: 1 km/h, or the machine's minimum if higher."""
        return max(ftms.SESSION_START_SPEED_KPH, self.limits.min_speed_kph)

    async def stop_belt(self) -> dict[str, Any]:
        await self._require_control()
        await self._command(ftms.stop(), "Stop belt")
        self._expect_stopped = True
        self._set_running(False, "Belt stopped")
        return self.snapshot()

    async def set_speed(self, kph: float) -> dict[str, Any]:
        """Sets an absolute target speed, clamped onto the machine's own grid."""
        await self._require_control()
        if not self.running:
            raise TreadmillError(
                f"The belt is stopped. Press Start — it comes up at "
                f"{self.start_speed_kph:.1f} km/h — then set the speed from there."
            )
        bounded = await self._apply_speed(kph)
        self._emit(TreadmillEvent("speed", f"Speed set to {bounded:.1f} km/h", speed_kph=bounded))
        return self.snapshot()

    async def _apply_speed(self, kph: float) -> float:
        """Sends an absolute target and remembers it. Announcing is the caller's job."""
        bounded = min(
            max(ftms.snap(kph, self.limits.speed_step_kph), self.limits.min_speed_kph),
            self.limits.max_speed_kph,
        )
        await self._command(ftms.set_speed(bounded), f"Set speed {bounded:.2f} km/h")
        self.target_speed_kph = bounded
        return bounded

    async def adjust_speed(self, steps: int) -> dict[str, Any]:
        """Moves the target by whole increments. Positive is faster."""
        base = self.target_speed_kph
        if base is None:
            # Nothing asked for yet: start from the machine, or from its minimum.
            base = self.reported_speed_kph or self.limits.min_speed_kph
        return await self.set_speed(
            ftms.next_target(base, steps, self.limits.speed_step_kph,
                             self.limits.min_speed_kph, self.limits.max_speed_kph)
        )

    async def set_incline(self, percent: float) -> dict[str, Any]:
        await self._require_control()
        bounded = min(
            max(ftms.snap(percent, self.limits.incline_step_percent), self.limits.min_incline_percent),
            self.limits.max_incline_percent,
        )
        await self._command(ftms.set_inclination(bounded), f"Set incline {bounded:.1f}%")
        self.target_incline_percent = bounded
        self._emit(TreadmillEvent("incline", f"Incline set to {bounded:.0f}%",
                                  incline_percent=bounded))
        return self.snapshot()

    async def adjust_incline(self, steps: int) -> dict[str, Any]:
        base = self.target_incline_percent
        if base is None:
            base = self.reported_incline_percent or self.limits.min_incline_percent
        return await self.set_incline(
            ftms.next_target(base, steps, self.limits.incline_step_percent,
                             self.limits.min_incline_percent, self.limits.max_incline_percent)
        )

    async def begin_session(self) -> float:
        """Brings the belt up for a new session and returns the speed it was set to.

        Which is the same start every time — [start_belt] — never whatever the last
        session finished at.
        """
        await self._require_control()
        await self.start_belt()
        speed = self.start_speed_kph
        log_event(log, logging.INFO, "ble.session_start",
                  f"Treadmill started for a session at {speed:.1f} km/h", speed_kph=speed)
        return speed

    async def end_session(self) -> None:
        """Stops the belt if it is moving and forgets this session's targets.

        Without this the next patient inherits the last session's speed. Failures
        are logged and swallowed: a session must always be saveable, even when the
        treadmill has gone away mid-run — and if the link is gone the belt is
        beyond the console's reach anyway, which the operator can see.
        """
        try:
            if self.can_control and self.running:
                await self.stop_belt()
        except (TreadmillError, ConnectionError, OSError) as error:
            log_event(log, logging.WARNING, "ble.stop_failed",
                      f"Could not stop the belt at the end of the session: {error}")
            self._note("error", f"Could not stop the belt: {error}")
        self.target_speed_kph = None
        self.target_incline_percent = None

    # ---- the wire ---------------------------------------------------------

    async def _require_control(self) -> None:
        if self.link is None:
            raise TreadmillError("This console was started without treadmill control.")
        if not self.ready:
            raise TreadmillError(
                "The treadmill is not connected. Connect it before controlling the belt."
            )
        if not self.has_control and not await self._request_control():
            raise TreadmillError(
                "The treadmill did not grant control. Check nothing else is connected to it."
            )

    async def _command(self, payload: bytes, label: str) -> ftms.ControlResponse | None:
        response = await self._write(payload, label)
        if response is not None and response.result is ftms.Result.NOT_PERMITTED:
            # Control is dropped on every reconnect, and sometimes by the machine
            # itself. Ask once and repeat the command rather than failing the press.
            self._note("info", "Control was refused — requesting control and retrying")
            self.has_control = False
            if await self._request_control():
                response = await self._write(payload, label)
        if response is not None and not response.ok:
            self.last_error = f"{label}: {response.result.value}"
            raise TreadmillError(f"{label} — {response.result.value}")
        return response

    async def _write(self, payload: bytes, label: str | None = None) -> ftms.ControlResponse | None:
        assert self.link is not None
        opcode = payload[0]
        loop = asyncio.get_running_loop()
        async with self._command_lock:
            future: asyncio.Future[ftms.ControlResponse] = loop.create_future()
            self._pending[opcode] = future
            self._note("out", label or ftms.opcode_name(opcode), payload)
            try:
                await self.link.write(payload)
            except (ConnectionError, OSError) as error:
                self._pending.pop(opcode, None)
                self.last_error = str(error)
                self._note("error", f"Write failed: {error}")
                self._set_state(ConnectionState.FAILED, f"The treadmill link failed: {error}")
                raise TreadmillError(f"The treadmill did not accept the command: {error}") from error
            try:
                return await asyncio.wait_for(future, RESPONSE_TIMEOUT_S)
            except TimeoutError:
                # The write landed but no reply came. Reporting this rather than
                # assuming success is the difference between a visible problem and
                # a console that shows a speed the belt never adopted.
                self._note("error", f"No reply to {label or ftms.opcode_name(opcode)}")
                self.last_error = f"The treadmill did not reply to “{label or opcode}”."
                return None
            except asyncio.CancelledError:
                return None
            finally:
                self._pending.pop(opcode, None)

    def _on_notify(self, characteristic: str, data: bytes) -> None:
        """Every frame from the machine. Called on the event loop by the link."""
        if characteristic == ftms.CONTROL_POINT:
            self._on_response(data)
        elif characteristic == ftms.FITNESS_MACHINE_STATUS:
            self._on_status(data)
        elif characteristic == ftms.TREADMILL_DATA:
            self._on_data(data)

    def _on_response(self, data: bytes) -> None:
        response = ftms.parse_response(data)
        if response is None:
            return
        self._note("in" if response.ok else "error", response.text, data)
        future = self._pending.get(response.opcode)
        if future is not None and not future.done():
            future.set_result(response)

    def _on_status(self, data: bytes) -> None:
        status = ftms.parse_machine_status(data)
        if status is None:
            return
        text = status.event.value + (f" ({status.value:.2f})" if status.value is not None else "")
        self._note("error" if status.stopped else "in", text, data)
        if status.event is ftms.Event.STOPPED_BY_SAFETY_KEY:
            self.safety_key_pulled = True
            self.last_error = ftms.Event.STOPPED_BY_SAFETY_KEY.value
            log_event(log, logging.WARNING, "ble.safety_key",
                      "The treadmill's safety key was pulled — the belt has stopped")
        if status.stopped:
            self._expect_stopped = True
            self._set_running(False, text)
        elif status.event is ftms.Event.STARTED_BY_USER:
            self._started_at = time.monotonic()
            self._set_running(True, text)
        # A Target-Changed echo is deliberately NOT written back into the target.
        # The machine emits it after every command and keeps emitting it with the
        # instantaneous value while the motor ramps, so adopting it walks the
        # target back down to the belt speed and the next press recomputes the
        # same number. The console's target is authoritative; any divergence is
        # surfaced by showing both figures.

    def _on_data(self, data: bytes) -> None:
        parsed = ftms.parse_treadmill_data(data)
        if parsed is None:
            return
        if parsed.speed_kph is not None:
            self.reported_speed_kph = parsed.speed_kph
            if parsed.speed_kph > 0.15:
                self._zero_frames = 0
                # While a commanded stop is still taking effect, a non-zero reading is
                # the belt coasting down, not someone starting it.
                if not self.running and not self._expect_stopped:
                    self._set_running(True, "The belt is moving")
            else:
                self._expect_stopped = False
                self._zero_frames += 1
                stopped_long_enough = time.monotonic() - self._started_at > START_GRACE_S
                if self.running and self._zero_frames >= ZERO_FRAMES_FOR_STOPPED and stopped_long_enough:
                    self._set_running(False, "The belt has stopped")
        if parsed.inclination_percent is not None:
            self.reported_incline_percent = parsed.inclination_percent
        if not self.log or not any(line.text.startswith("Status frame") for line in self.log):
            # The first frame only: at ~1 Hz this would otherwise swamp the command
            # history, which is what the log is actually read for.
            self._note("in", f"Status frame, flags 0x{parsed.flags:04X}, {len(data)} bytes", data)

    # ---- bookkeeping ------------------------------------------------------

    def _set_running(self, running: bool, detail: str) -> None:
        if running == self.running:
            return
        self.running = running
        self._announce_belt(running, detail)

    def _announce_belt(self, running: bool, detail: str) -> None:
        if not running:
            # A stopped belt has no speed — not a speed of zero. The machine drops
            # its target too, and the next start comes up at 1 km/h regardless, so
            # keeping the old number here would only be something to disagree with.
            self.target_speed_kph = None
        log_event(log, logging.INFO, "ble.belt", detail, running=running,
                  speed_kph=self.target_speed_kph)
        self._emit(TreadmillEvent("belt", detail, running=running,
                                  speed_kph=self.target_speed_kph))

    def _set_state(self, state: ConnectionState, detail: str) -> None:
        self.state = state
        self.detail = detail
        if state is not ConnectionState.FAILED:
            self.last_error = ""
        self._emit(TreadmillEvent("connection", detail))

    def _fail(self, reason: str) -> dict[str, Any]:
        self._set_state(ConnectionState.FAILED, reason)
        self.last_error = reason
        self._note("error", reason)
        log_event(log, logging.WARNING, "ble.connect_failed", reason)
        return self.snapshot()

    def _emit(self, event: TreadmillEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _note(self, direction: str, text: str, payload: bytes | None = None) -> None:
        self.log.append(
            LogLine(
                at=time.monotonic() - self._started_monotonic,
                direction=direction,
                text=text,
                hex=payload.hex(" ").upper() if payload else None,
            )
        )
        del self.log[:-MAX_LOG_ENTRIES]


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
