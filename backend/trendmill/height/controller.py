"""Belt-height control: where the deck is, where it is going, and when to refuse.

The mechanism reports nothing back — no position, no "arrived", no fault. Every
number the console shows is therefore what it *asked for*, and "moving" is a
timer computed from the firmware's own motion profile. That is a real limitation
and the UI says so rather than implying a measurement.

Two rules are enforced here rather than in the browser, because they are about a
motor lifting a deck:

* **Nothing moves until the mechanism has been homed.** Without a datum, an
  absolute height command means nothing — the deck would travel a distance from
  wherever it happens to be, which may be into an end stop.
* **Nothing moves while a session is recording.** Height is set before the
  patient steps on, and the gait maths assumes a deck that does not move
  underneath it mid-recording.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from trendmill.height import protocol
from trendmill.height.link import HeightLink, HeightUnavailable
from trendmill.logs import get_logger, log_event

log = get_logger("height")


class HeightError(RuntimeError):
    """A command was refused. The message is meant for the operator."""


class HeightController:
    def __init__(self, link: HeightLink | None) -> None:
        self.link = link
        self.homed = False
        #: What the console last asked for. Not a measurement.
        self.target_mm: int | None = None
        self.last_error = ""
        self._seq = 0
        self._moving_until = 0.0
        self._move_from: int | None = None
        #: Homing ends when the switch is found, not after a known distance, so it
        #: gets a worst-case timeout rather than a duration — and the UI must not
        #: present that as a countdown.
        self._homing = False
        self._move_started = 0.0
        self._lock = asyncio.Lock()
        #: Set by the console while a session records, to refuse movement.
        self.session_active = False

    # ---- state ------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.link is not None

    @property
    def moving(self) -> bool:
        return time.monotonic() < self._moving_until

    @property
    def progress(self) -> float:
        """0…1 through the current move, from the timer. Never a measurement."""
        if not self.moving or self._moving_until <= self._move_started:
            return 1.0
        elapsed = time.monotonic() - self._move_started
        return min(1.0, max(0.0, elapsed / (self._moving_until - self._move_started)))

    def snapshot(self) -> dict[str, Any]:
        moving = self.moving
        return {
            "available": self.available,
            "backend": self.link.name if self.link is not None else None,
            "homed": self.homed,
            "moving": moving,
            "homing": moving and self._homing,
            "progress": round(self.progress, 3) if moving else 1.0,
            "seconds_left": round(max(0.0, self._moving_until - time.monotonic()), 1) if moving else 0.0,
            "target_mm": self.target_mm,
            "min_mm": protocol.MIN_HEIGHT_MM,
            "max_mm": protocol.MAX_HEIGHT_MM,
            "step_mm": protocol.STEP_MM,
            "can_move": self.available and self.homed and not moving and not self.session_active,
            "locked_by_session": self.session_active,
            "last_error": self.last_error,
        }

    # ---- commands ---------------------------------------------------------

    async def home(self) -> dict[str, Any]:
        """Finds the end stops and calls that zero. Required after every power-on."""
        self._require_link()
        if self.session_active:
            raise HeightError("A session is recording. End it before moving the deck.")
        async with self._lock:
            await self._send(protocol.home(self._next_seq()), "home")
            self._begin_move(protocol.HOME_TIMEOUT_S, None)
            self._homing = True
            # Homing ends at the switch, which is the bottom of the travel.
            self.homed = True
            self.target_mm = protocol.MIN_HEIGHT_MM
        log_event(log, logging.INFO, "height.homing", "Homing the belt height")
        return self.snapshot()

    async def move_to(self, height_mm: float) -> dict[str, Any]:
        """Drives to an absolute height, clamped to the travel and the 10 mm grid."""
        self._require_link()
        self._require_ready()
        target = protocol.clamp(height_mm)
        async with self._lock:
            start = self.target_mm if self.target_mm is not None else protocol.MIN_HEIGHT_MM
            if target == start:
                return self.snapshot()
            await self._send(protocol.move_to(target, self._next_seq()), f"move to {target} mm")
            self._begin_move(protocol.move_seconds(target - start), start)
            self._homing = False
            self.target_mm = target
        log_event(log, logging.INFO, "height.move", f"Belt height set to {target} mm",
                  height_mm=target, from_mm=start)
        return self.snapshot()

    async def nudge(self, steps: int) -> dict[str, Any]:
        """One press of + or −, in 10 mm steps."""
        base = self.target_mm if self.target_mm is not None else protocol.MIN_HEIGHT_MM
        return await self.move_to(base + steps * protocol.STEP_MM)

    async def stop(self) -> dict[str, Any]:
        """Abandons the move. Always allowed — including during a session."""
        self._require_link()
        async with self._lock:
            await self._send(protocol.stop(self._next_seq()), "stop")
            self._moving_until = 0.0
            was_homing, self._homing = self._homing, False
            # Where it actually halted is unknown, so the datum is gone with it.
            # A stopped homing run is the same problem: it never reached the switch.
            if self._move_from is not None or was_homing:
                self.homed = False
                self.target_mm = None
                self.last_error = (
                    "The move was stopped part way, so the deck's position is no longer known. "
                    "Home it again before setting a height."
                )
        log_event(log, logging.WARNING, "height.stopped", "Belt height move stopped by the operator")
        return self.snapshot()

    # ---- internals --------------------------------------------------------

    def _require_link(self) -> None:
        if self.link is None:
            raise HeightError(
                "This console was started without belt-height control. Restart it with "
                "a height backend to use it."
            )

    def _require_ready(self) -> None:
        if self.session_active:
            raise HeightError("A session is recording. End it before moving the deck.")
        if not self.homed:
            raise HeightError("The deck has not been homed yet. Press Home first.")
        if self.moving:
            raise HeightError("The deck is still moving. Wait for it to stop.")

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _begin_move(self, seconds: float, from_mm: int | None) -> None:
        self._move_started = time.monotonic()
        self._moving_until = self._move_started + seconds
        self._move_from = from_mm

    async def _send(self, payload: bytes, what: str) -> None:
        assert self.link is not None
        try:
            await self.link.send(payload)
            self.last_error = ""
        except HeightUnavailable as error:
            self.last_error = str(error)
            raise HeightError(str(error)) from error
        except (ConnectionError, OSError) as error:
            self.last_error = f"Could not {what}: {error}"
            log_event(log, logging.ERROR, "height.send_failed", self.last_error)
            raise HeightError(
                f"The height command did not reach the board: {error}. Check the USB cable."
            ) from error
