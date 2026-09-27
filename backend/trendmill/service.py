"""The running console: reader thread, processing loop, recorder and health log.

The USB read blocks, so the source runs on its own OS thread and hands transfers
to the asyncio loop through a bounded queue. A full queue is counted and shown,
never silently absorbed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from trendmill import __version__
from trendmill.calibration.profile import CalibrationProfile, Method
from trendmill.calibration.store import CalibrationStore
from trendmill.calibration.weighing import Capture, Weighing
from trendmill.chart import ChartFeed
from trendmill.device.base import LinkState, PacketSource, StateChange, Transfer
from trendmill.height.controller import HeightController
from trendmill.logs import get_logger, log_event
from trendmill.processor import StreamProcessor
from trendmill.protocol.constants import CHANNEL_NAMES, SAMPLES_PER_PACKET
from trendmill.protocol.health import StreamHealth, finite_or_none
from trendmill.sessions.manager import ActiveSession, SessionDetails, SessionManager
from trendmill.storage.recorder import Recorder
from trendmill.treadmill.controller import TreadmillController, TreadmillError, TreadmillEvent

log = get_logger("stream")

QUEUE_SIZE = 8192
HEALTH_LOG_INTERVAL_S = 10.0
NO_DATA_AFTER_S = 1.5


@dataclass
class ConsoleConfig:
    data_dir: Path
    nominal_rate_hz: float


class Console:
    def __init__(
        self,
        source: PacketSource,
        config: ConsoleConfig,
        treadmill: TreadmillController | None = None,
        height: HeightController | None = None,
    ) -> None:
        self.source = source
        self.config = config
        # No link means no belt control: the console still streams, records and
        # measures, and every treadmill control reports itself as unavailable.
        self.treadmill = treadmill if treadmill is not None else TreadmillController(None)
        self.treadmill.on_event = self._on_treadmill_event
        # Belt height: refuses to move while a session records, so the deck can
        # never rise under a patient who is already walking on it.
        self.height = height if height is not None else HeightController(None)
        self.health = StreamHealth(config.nominal_rate_hz)
        self.processor = StreamProcessor(self.health, config.nominal_rate_hz)
        self.recorder = Recorder(config.data_dir / "recordings")
        self.calibration_store = CalibrationStore(config.data_dir / "calibration")
        self.profile: CalibrationProfile | None = self.calibration_store.load()
        self.weighing = Weighing()
        self._weighing_segment: int | None = None
        self.chart = ChartFeed()
        self.sessions = SessionManager(config.data_dir / "sessions")
        self.link_state = LinkState.WAITING
        self.link_detail = "Starting"
        self.device: dict[str, Any] = {}
        self.segment = 0
        self._link_since = time.monotonic()
        self._last_data = 0.0
        self._queue: asyncio.Queue[Transfer] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._closing_session = False
        self._process = psutil.Process()
        self._process.cpu_percent(None)

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._tasks = [
            asyncio.create_task(self._consume(), name="consume"),
            asyncio.create_task(self._health_log(), name="health-log"),
        ]
        self._thread = threading.Thread(target=self._run_source, name="usb-reader", daemon=True)
        self._thread.start()
        defaults = self.calibration_store.load_defaults()
        if defaults is None:
            log_event(get_logger("calibration"), logging.WARNING, "calibration.defaults_not_present",
                      f"Default coefficients not present ({self.calibration_store.defaults_path})")
        else:
            log_event(get_logger("calibration"), logging.INFO, "calibration.defaults_loaded",
                      f"Default coefficients loaded from {self.calibration_store.defaults_path}",
                      counts_per_kg=list(defaults.counts_per_kg))
        if self.profile is not None:
            log_event(get_logger("calibration"), logging.INFO, "calibration.in_use",
                      f"Calibration in use: {self.profile.method}", method=self.profile.method,
                      counts_per_kg=list(self.profile.counts_per_kg))
        log_event(log, logging.INFO, "stream.started",
                  f"TrendMill {__version__} started with source '{self.source.name}'",
                  version=__version__, source=self.source.name,
                  nominal_rate_hz=self.config.nominal_rate_hz, data_dir=str(self.config.data_dir))

    async def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 3.0)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.recorder.active is not None:
            self.recorder.stop()
        if self.sessions.active is not None:
            # The server is going down mid-session: the belt must not be left running.
            self._closing_session = True
            await self.treadmill.end_session()
        self.height.session_active = False
        self.sessions.shutdown()
        await self.treadmill.disconnect()
        log_event(log, logging.INFO, "stream.stopped", "TrendMill stopped")

    # ---- reader thread -> loop -------------------------------------------

    def _run_source(self) -> None:
        try:
            self.source.run(self._sink, self._on_state_threadsafe, self._stop)
        except Exception as error:  # a source must never take the reader thread down silently
            log.exception("Packet source failed", extra={"event": "stream.source_failed", "fields": {}})
            self._on_state_threadsafe(StateChange(LinkState.STOPPED, f"Source failed: {error}"))

    def _sink(self, transfer: Transfer) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._enqueue, transfer)

    def _enqueue(self, transfer: Transfer) -> None:
        assert self._queue is not None
        try:
            self._queue.put_nowait(transfer)
        except asyncio.QueueFull:
            self.health.counters.queue_overflows += 1
        depth = self._queue.qsize()
        if depth > self.health.max_queue_depth:
            self.health.max_queue_depth = depth

    def _on_state_threadsafe(self, change: StateChange) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._on_state, change)

    def _on_state(self, change: StateChange) -> None:
        if self.link_state == LinkState.STREAMING and change.state == LinkState.DISCONNECTED:
            self.health.counters.reconnects += 1
        self.link_state = change.state
        self.link_detail = change.detail
        self._link_since = time.monotonic()
        if change.device:
            self.device = change.device
        if change.segment:
            self.segment = change.segment

    # ---- processing ------------------------------------------------------

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            transfer = await self._queue.get()
            # Raw first: a processing bug must never cost the recording.
            try:
                self.recorder.write(transfer)
            except OSError as error:
                log_event(get_logger("storage"), logging.ERROR, "storage.write_failed",
                          f"Could not write the recording: {error}")
                self.recorder.active = None
            session = self.sessions.active
            if session is not None:
                session.on_transfer(transfer)
            samples = self.processor.process(transfer)
            if transfer.segment != self._weighing_segment:
                self._weighing_segment = transfer.segment
                self.weighing.reset()
                self.chart.reset()
            for sample in samples:
                self.weighing.add(sample.t_us, sample.values)
                self.chart.add(sample, self.profile)
            if session is not None and samples:
                session.on_samples(samples)
            self._last_data = time.monotonic()

    async def _health_log(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_LOG_INTERVAL_S)
            self.processor.flush_warnings()
            c = self.health.counters
            rate = self.health.rate.rate_hz
            fields = {
                "state": str(self.link_state),
                "rate_hz": round(rate, 2) if rate is not None else None,
                "transfers": c.transfers, "short": c.short_transfers,
                "out_of_range": c.out_of_range, "timeouts": self._timeouts(),
                "reconnects": c.reconnects, "queue_max": self.health.max_queue_depth,
                "cpu_pct": round(self._process.cpu_percent(None), 1),
                "rss_mb": round(self._process.memory_info().rss / 1e6, 1),
            }
            log_event(log, logging.INFO, "stream.health", "health", **fields)
            for warning in self.health.warnings(self.link_state == LinkState.STREAMING):
                if warning.code in {"channels_identical", "rate_mismatch"}:
                    log_event(log, logging.WARNING, f"stream.{warning.code}", warning.message)

    def _timeouts(self) -> int:
        return int(getattr(self.source, "timeouts", 0))

    # ---- recording -------------------------------------------------------

    def start_recording(self, label: str) -> dict[str, Any]:
        rec = self.recorder.start(label, self.config.nominal_rate_hz, self.device)
        return {"id": rec.id, "label": rec.label}

    def stop_recording(self) -> dict[str, Any]:
        return self.recorder.stop()

    # ---- sessions --------------------------------------------------------

    def now_us(self) -> int:
        """The sample clock's latest time: sessions and conditions are timed on it."""
        latest = self.processor.latest
        return latest.t_us if latest is not None else 0

    async def start_session(self, details: SessionDetails) -> ActiveSession:
        """Opens the session, then brings the belt up to the starting speed.

        The belt is started *after* the session exists, so the first metres of
        walking are already being recorded when the motor engages. If the
        treadmill refuses, the session is left running rather than thrown away:
        the load cells are the measurement, and an operator can drive the belt
        from its own console while the recording continues.
        """
        # Filters are designed for the rate actually arriving, not the nominal one: the
        # firmware's real rate is still unconfirmed (976.5625 vs 250 samples/s).
        observed = self.health.rate.rate_hz
        rate = observed if observed and observed > 50 else self.config.nominal_rate_hz
        session = self.sessions.start(details, self.profile, self.device, rate, self.now_us())
        session.treadmill = self.treadmill.snapshot()
        session.height_mm = self.height.target_mm
        self.height.session_active = True
        if self.treadmill.can_control:
            try:
                await self.treadmill.begin_session()
            except (TreadmillError, ConnectionError, OSError) as error:
                log_event(get_logger("ble"), logging.WARNING, "ble.session_start_failed",
                          f"The session started, but the belt did not: {error}")
        return session

    async def stop_session(self, notes: str = "") -> dict[str, Any]:
        """Stops the belt first, then closes the session.

        In that order deliberately: stopping the belt is the safety-relevant half
        and must not wait on files being written. The belt stopping is not
        recorded as a condition here, though — a session always ends with the belt
        stopped, so a final 0 km/h block with no steps in it would appear in every
        report and say nothing.
        """
        self._closing_session = True
        try:
            await self.treadmill.end_session()
        finally:
            self._closing_session = False
            self.height.session_active = False
        return self.sessions.stop(notes)

    # ---- treadmill --------------------------------------------------------

    def _on_treadmill_event(self, event: TreadmillEvent) -> None:
        """Keeps the gait maths and the belt in step.

        Every speed the operator selects becomes a new condition, which is what
        step and stride length integrate. A stopped belt becomes a condition with
        no speed at all — the treadmill has no such thing as 0 km/h — so lengths
        read "unavailable" for that stretch instead of being computed from a speed
        the deck no longer has.
        """
        session = self.sessions.active
        if session is None or event.kind == "connection" or self._closing_session:
            return
        current = session.conditions[-1]
        speed = current["speed_kph"]
        incline = current.get("incline_percent")
        if event.kind == "belt":
            speed = self.treadmill.target_speed_kph if event.running else None
        elif event.kind == "speed" and event.speed_kph is not None:
            if not self.treadmill.running:
                return  # a target set while the belt is stopped changes nothing under the patient
            speed = event.speed_kph
        elif event.kind == "incline" and event.incline_percent is not None:
            incline = event.incline_percent
        if speed == current["speed_kph"] and incline == current.get("incline_percent"):
            return
        self.sessions.new_condition(
            speed, current["activity"], current["bws_percent"], event.detail, incline
        )

    # ---- calibration and weight ------------------------------------------

    def capture(self) -> Capture | None:
        """The last 2 s averaged per cell, or None before 1 s of data is in."""
        return self.weighing.capture()

    def save_profile(self, profile: CalibrationProfile) -> None:
        self.calibration_store.save(profile)
        self.profile = profile

    def use_defaults(self) -> CalibrationProfile:
        """Selects the defaults file for every calculation. Raises if there is no file."""
        defaults = self.calibration_store.load_defaults()
        if defaults is None:
            raise LookupError("Default values are not present. Set them first.")
        self.save_profile(defaults)
        return defaults

    def save_defaults(self, profile: CalibrationProfile, note: str = "") -> CalibrationProfile:
        saved = self.calibration_store.save_defaults(profile, note)
        if self.profile is not None and self.profile.method == Method.DEFAULTS:
            self.profile = saved  # the defaults are in use, so the new ones take effect now
        return saved

    def clear_profile(self) -> None:
        self.calibration_store.clear()
        self.profile = None

    def firmware_bcd(self) -> str | None:
        value = self.device.get("bcd_device")
        return str(value) if value is not None else None

    def calibration_status(self) -> dict[str, Any]:
        profile = self.profile
        defaults = self.calibration_store.defaults_info()
        if profile is None:
            in_use = "none"
        else:
            in_use = "defaults" if profile.method == Method.DEFAULTS else "custom"
        base = {"in_use": in_use, "defaults": defaults}
        if profile is None:
            message = "No coefficients selected. Weight and loads cannot be shown until you choose some."
            if not defaults["present"]:
                message += " Default values are not present."
            return base | {"status": "missing", "message": message, "active": None}
        board = self.firmware_bcd()
        if profile.firmware_bcd and board and profile.firmware_bcd != board:
            return base | {
                "status": "firmware_mismatch",
                "message": f"These coefficients were made on firmware {profile.firmware_bcd}, but the "
                           f"board reports {board}. A firmware change can rescale the ADC: recalibrate.",
                "active": profile.to_dict(),
            }
        return base | {"status": "ok", "message": "", "active": profile.to_dict()}

    # ---- snapshot for the API and UI ---------------------------------------

    def snapshot(self) -> dict[str, Any]:
        streaming = self.link_state == LinkState.STREAMING
        counters = self.health.counters.as_dict()
        counters["timeouts"] = self._timeouts()
        rate = finite_or_none(self.health.rate.rate_hz)
        age = time.monotonic() - self._last_data if self._last_data else None
        warnings = [w.__dict__ for w in self.health.warnings(streaming)]
        if streaming and (age is None or age > NO_DATA_AFTER_S) and \
                time.monotonic() - self._link_since > NO_DATA_AFTER_S:
            warnings.insert(0, {"code": "no_data",
                                "message": "Connected, but no data is arriving from the board."})
        stats = {s.name: s for s in self.health.channel_stats()}
        channels = []
        for name in CHANNEL_NAMES:
            s = stats.get(name)
            channels.append({
                "name": name,
                "last": s.last if s else None,
                "mean": round(s.mean, 1) if s else None,
                "min": s.minimum if s else None,
                "max": s.maximum if s else None,
                "std": round(s.std, 1) if s else None,
                "noise": round(s.step_noise, 1) if s else None,
            })
        return {
            "app": {"version": __version__, "source": self.source.name,
                    "nominal_rate_hz": self.config.nominal_rate_hz},
            "link": {"state": str(self.link_state), "detail": self.link_detail,
                     "device": self.device, "segment": self.segment,
                     "since_s": round(time.monotonic() - self._link_since, 1)},
            "stream": {
                "rate_hz": round(rate, 2) if rate is not None else None,
                "packets_per_s": round(rate / SAMPLES_PER_PACKET, 2) if rate is not None else None,
                "session_rate_hz": _round(self.health.rate.session_rate_hz, 3),
                "elapsed_s": round(self.health.rate.elapsed_s, 1),
                "sample_period_us": round(self.processor.clock.observed_period_us, 2),
                "last_data_age_s": round(age, 2) if age is not None else None,
                "max_queue_depth": self.health.max_queue_depth,
                "counters": counters,
            },
            "channels": channels,
            "warnings": warnings,
            "recording": self.recorder.status(),
            "calibration": {k: v for k, v in self.calibration_status().items()
                            if k not in ("active", "defaults")}
            | {"method": self.profile.method if self.profile else None},
            "weight": self.weighing.weight(self.profile) if self.profile is not None else None,
            "capture_ready": self.weighing.ready,
            "simulator": getattr(self.source, "mode", None),
            "treadmill": self.treadmill.snapshot(),
            "height": self.height.snapshot(),
            "session": self.sessions.active.live() if self.sessions.active is not None else None,
        }


def _round(value: float | None, digits: int) -> float | None:
    value = finite_or_none(value)
    return round(value, digits) if value is not None else None
