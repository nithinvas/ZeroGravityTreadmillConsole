"""HTTP and WebSocket API, plus the built UI.

Listens on 127.0.0.1 by default: the only client is the kiosk on the same machine.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from treadmill import __version__
from treadmill.belt.controller import TreadmillError
from treadmill.belt.ftms import SESSION_START_SPEED_KPH
from treadmill.calibration import solver
from treadmill.calibration.profile import CalibrationProfile, Method
from treadmill.height.controller import HeightError
from treadmill.logs import COMPONENTS, LIVE_BUFFER, get_logger, log_event, set_component_level
from treadmill.service import Console
from treadmill.sessions.manager import ACTIVITIES, SessionDetails

log = get_logger("api")

LIVE_INTERVAL_S = 0.2
LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


class RecordingStart(BaseModel):
    label: str = Field(default="", max_length=80)


class LoggingChange(BaseModel):
    component: str
    level: str


class ManualCalibration(BaseModel):
    zeros: list[float] = Field(min_length=4, max_length=4)
    counts_per_kg: list[float] = Field(min_length=4, max_length=4)
    method: str = Method.MANUAL
    known_weight_kg: float | None = None
    note: str = Field(default="", max_length=200)


class SolveRequest(BaseModel):
    known_weight_kg: float = Field(gt=0)
    zeros: list[float] = Field(min_length=4, max_length=4)
    #: One row of four loaded means per capture position: one row, or four for the corners.
    loaded: list[list[float]] = Field(min_length=1, max_length=4)


class SimulatorLoad(BaseModel):
    mode: str
    kg: float = Field(default=0.0, ge=0, le=300)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)


ALLOWED_METHODS = {Method.MANUAL, Method.DEFAULTS, Method.ONE_CAPTURE, Method.FOUR_POSITION,
                   Method.FOUR_POSITION_SHARED}


class SessionStart(BaseModel):
    patient_name: str = Field(default="", max_length=120)
    patient_id: str = Field(default="", max_length=60)
    issue: str = Field(default="", max_length=500)
    tester: str = Field(default="", max_length=120)
    #: Ignored when the treadmill is connected: the belt always opens at its minimum.
    speed_kph: float = Field(default=SESSION_START_SPEED_KPH, ge=0, le=25)
    activity: str = "walk"
    body_weight_kg: float | None = Field(default=None, gt=0, le=300)
    bws_percent: float | None = Field(default=None, ge=0, le=100)
    notes: str = Field(default="", max_length=2000)
    #: Starting without belt control is allowed, but only when asked for explicitly,
    #: so nobody discovers mid-session that the + and − buttons do nothing.
    without_treadmill: bool = False


class ConditionChange(BaseModel):
    speed_kph: float = Field(ge=0, le=25)
    activity: str = "walk"
    bws_percent: float | None = Field(default=None, ge=0, le=100)
    note: str = Field(default="", max_length=200)


class SpeedRequest(BaseModel):
    """Either an absolute target, or a number of increments to move by."""

    kph: float | None = Field(default=None, ge=0, le=25)
    steps: int | None = Field(default=None, ge=-100, le=100)


class InclineRequest(BaseModel):
    percent: float | None = Field(default=None, ge=-30, le=30)
    steps: int | None = Field(default=None, ge=-100, le=100)


class HeightRequest(BaseModel):
    """Either an absolute height in millimetres, or a number of 10 mm steps."""

    mm: float | None = Field(default=None, ge=0, le=1000)
    steps: int | None = Field(default=None, ge=-100, le=100)


class SessionStop(BaseModel):
    notes: str = Field(default="", max_length=2000)


class ClientLog(BaseModel):
    level: str = "error"
    event: str = "ui.error"
    message: str = Field(max_length=2000)


def create_app(console: Console, ui_dir: Path | None = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await console.start()
        try:
            yield
        finally:
            await console.stop()

    app = FastAPI(title="TreadMill console", version=__version__, lifespan=lifespan)

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return console.snapshot()

    @app.get("/api/recordings")
    async def recordings() -> list[dict[str, Any]]:
        return console.recorder.list()

    @app.post("/api/recordings/start")
    async def start_recording(body: RecordingStart) -> dict[str, Any]:
        try:
            return console.start_recording(body.label)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/recordings/stop")
    async def stop_recording() -> dict[str, Any]:
        try:
            return console.stop_recording()
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/calibration")
    async def calibration() -> dict[str, Any]:
        return console.calibration_status() | {"history": console.calibration_store.history(10)}

    @app.post("/api/calibration/use-defaults")
    async def use_defaults() -> dict[str, Any]:
        try:
            console.use_defaults()
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return console.calibration_status()

    @app.post("/api/calibration/defaults")
    async def set_defaults(body: ManualCalibration) -> dict[str, Any]:
        """Writes the default coefficients file. Does not change what is in use."""
        profile = _profile_from(body, Method.DEFAULTS, console.firmware_bcd())
        console.save_defaults(profile, body.note)
        return console.calibration_status()

    @app.post("/api/calibration/capture")
    async def capture() -> dict[str, Any]:
        result = console.capture()
        if result is None:
            raise HTTPException(status_code=409,
                                detail="Not enough readings yet: hold still for at least one second.")
        return result.as_dict()

    @app.post("/api/calibration/solve")
    def solve(body: SolveRequest) -> dict[str, Any]:
        if any(len(row) != 4 for row in body.loaded):
            raise HTTPException(status_code=400, detail="Each capture needs four cell values.")
        if len(body.loaded) not in (1, 4):
            raise HTTPException(status_code=400, detail="Send one capture, or one per corner.")
        deltas = [[v - z for v, z in zip(row, body.zeros, strict=True)] for row in body.loaded]
        result = solver.solve(deltas, body.known_weight_kg)
        if result is None:
            raise HTTPException(
                status_code=422,
                detail="These captures do not determine a calibration: the deck barely moved. "
                       "Check the weight is on the deck, and at a different corner each time.",
            )
        if len(body.loaded) == 1:
            method = Method.ONE_CAPTURE
        else:
            method = Method.FOUR_POSITION if result.kind == "per_cell" else Method.FOUR_POSITION_SHARED
        return {"counts_per_kg": [round(c, 2) for c in result.counts_per_kg], "kind": result.kind,
                "method": method}

    @app.post("/api/calibration")
    async def save_calibration(body: ManualCalibration) -> dict[str, Any]:
        """Selects these coefficients for every calculation."""
        if body.method not in ALLOWED_METHODS or body.method == Method.DEFAULTS:
            # "defaults" is only ever the defaults file: use /use-defaults for that.
            raise HTTPException(status_code=400, detail=f"Unknown method {body.method!r}.")
        console.save_profile(_profile_from(body, body.method, console.firmware_bcd()))
        return console.calibration_status()

    @app.delete("/api/calibration")
    async def clear_calibration() -> dict[str, Any]:
        console.clear_profile()
        return console.calibration_status()

    @app.post("/api/simulator/load")
    async def simulator_load(body: SimulatorLoad) -> dict[str, Any]:
        set_load = getattr(console.source, "set_load", None)
        if set_load is None:
            raise HTTPException(status_code=409, detail="Only available with the simulator source.")
        try:
            set_load(body.mode, body.kg, body.x, body.y)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return body.model_dump()

    # ---- treadmill -------------------------------------------------------

    @app.get("/api/treadmill")
    async def treadmill() -> dict[str, Any]:
        return console.treadmill.snapshot() | {"log": console.treadmill.recent_log()}

    @app.post("/api/treadmill/connect")
    async def treadmill_connect() -> dict[str, Any]:
        try:
            return await console.treadmill.connect()
        except TreadmillError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/treadmill/disconnect")
    async def treadmill_disconnect() -> dict[str, Any]:
        return await console.treadmill.disconnect()

    @app.post("/api/treadmill/start")
    async def treadmill_start() -> dict[str, Any]:
        return await _belt(console.treadmill.start_belt())

    @app.post("/api/treadmill/stop")
    async def treadmill_stop() -> dict[str, Any]:
        return await _belt(console.treadmill.stop_belt())

    @app.post("/api/treadmill/speed")
    async def treadmill_speed(body: SpeedRequest) -> dict[str, Any]:
        if body.steps is not None:
            return await _belt(console.treadmill.adjust_speed(body.steps))
        if body.kph is None:
            raise HTTPException(status_code=400, detail="Send either a speed or a number of steps.")
        return await _belt(console.treadmill.set_speed(body.kph))

    @app.post("/api/treadmill/incline")
    async def treadmill_incline(body: InclineRequest) -> dict[str, Any]:
        if body.steps is not None:
            return await _belt(console.treadmill.adjust_incline(body.steps))
        if body.percent is None:
            raise HTTPException(status_code=400, detail="Send either an incline or a number of steps.")
        return await _belt(console.treadmill.set_incline(body.percent))

    # ---- belt height -----------------------------------------------------

    @app.get("/api/height")
    async def height() -> dict[str, Any]:
        return console.height.snapshot()

    @app.post("/api/height/home")
    async def height_home() -> dict[str, Any]:
        return await _height(console.height.home())

    @app.post("/api/height/move")
    async def height_move(body: HeightRequest) -> dict[str, Any]:
        if body.steps is not None:
            return await _height(console.height.nudge(body.steps))
        if body.mm is None:
            raise HTTPException(status_code=400, detail="Send either a height or a number of steps.")
        return await _height(console.height.move_to(body.mm))

    @app.post("/api/height/stop")
    async def height_stop() -> dict[str, Any]:
        return await _height(console.height.stop())

    # ---- sessions --------------------------------------------------------

    @app.post("/api/sessions")
    async def start_session(body: SessionStart) -> dict[str, Any]:
        controlled = console.treadmill.can_control
        if not controlled and not body.without_treadmill:
            raise HTTPException(
                status_code=409,
                detail=console.treadmill.detail
                + ". Connect it on the treadmill panel, or start the session without belt control "
                  "and drive the treadmill from its own console.",
            )
        fields = body.model_dump(exclude={"without_treadmill"})
        if controlled:
            # The belt is about to be started at its minimum, so that is the speed
            # the gait maths must use. Anything typed into the form would be a
            # second, divergent source of truth for the same number.
            fields["speed_kph"] = max(SESSION_START_SPEED_KPH,
                                      console.treadmill.limits.min_speed_kph)
            fields["incline_percent"] = console.treadmill.target_incline_percent
        try:
            details = SessionDetails(**fields)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        try:
            session = await console.start_session(details)
        except (RuntimeError, LookupError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return session.live()

    @app.get("/api/sessions/current")
    async def current_session() -> dict[str, Any] | None:
        return console.sessions.active.live() if console.sessions.active else None

    @app.post("/api/sessions/current/condition")
    async def change_condition(body: ConditionChange) -> dict[str, Any]:
        try:
            return console.sessions.new_condition(body.speed_kph, body.activity, body.bws_percent, body.note)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/sessions/current/stop")
    async def stop_session(body: SessionStop) -> dict[str, Any]:
        try:
            return await console.stop_session(body.notes)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/sessions")
    def search_sessions(
        q: str = "",
        date_from: str | None = Query(default=None, alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        date_to: str | None = Query(default=None, alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        return console.sessions.index.search(q, date_from, date_to, limit, offset)

    @app.get("/api/sessions/options")
    def session_options() -> dict[str, Any]:
        return {"activities": list(ACTIVITIES)}

    @app.get("/api/sessions/{session_id}")
    def session_report(session_id: str) -> dict[str, Any]:
        report = console.sessions.report(session_id)
        if report is None:
            raise HTTPException(status_code=404, detail="No such session.")
        return report

    @app.get("/api/sessions/{session_id}/files/{name}")
    def session_file(session_id: str, name: str) -> Response:
        path = console.sessions.file_path(session_id, name)
        if path is None:
            raise HTTPException(status_code=404, detail="No such file.")
        media = "text/csv" if name.endswith(".csv") else "application/json"
        return FileResponse(path, media_type=media, filename=f"{session_id}-{name}")

    @app.websocket("/ws/chart")
    async def live_chart(ws: WebSocket) -> None:
        await ws.accept()
        last = 0
        try:
            while True:
                points = console.chart.since(last)
                if points:
                    last = int(points[-1][0])
                await ws.send_json({"units": console.chart.units, "points": points})
                await asyncio.sleep(LIVE_INTERVAL_S)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/api/logs")
    def logs(
        limit: int = Query(500, ge=1, le=5000),
        level: str = "debug",
        component: str | None = None,
    ) -> list[dict[str, Any]]:
        return _filter(LIVE_BUFFER.recent(5000), level, component)[-limit:]

    @app.post("/api/logging")
    def change_logging(body: LoggingChange) -> dict[str, str]:
        try:
            set_component_level(body.component, body.level)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        log_event(log, logging.INFO, "api.log_level_changed",
                  f"Log level for {body.component} set to {body.level}",
                  component_changed=body.component, level=body.level)
        return {"component": body.component, "level": body.level}

    @app.get("/api/logging")
    def logging_levels() -> dict[str, str]:
        return {c: logging.getLevelName(get_logger(c).getEffectiveLevel()).lower() for c in COMPONENTS}

    @app.post("/api/client-log")
    def client_log(body: ClientLog) -> JSONResponse:
        level = LEVELS.get(body.level.lower(), logging.ERROR)
        log_event(get_logger("ui"), level, body.event if body.event.startswith("ui.") else "ui.error",
                  body.message)
        return JSONResponse({"ok": True})

    @app.websocket("/ws/live")
    async def live(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                await ws.send_json(console.snapshot())
                await asyncio.sleep(LIVE_INTERVAL_S)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.websocket("/ws/logs")
    async def live_logs(ws: WebSocket) -> None:
        await ws.accept()
        queue = LIVE_BUFFER.subscribe()
        try:
            for entry in LIVE_BUFFER.recent(200):
                await ws.send_json(entry)
            while True:
                await ws.send_json(await queue.get())
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            LIVE_BUFFER.unsubscribe(queue)

    if ui_dir is not None and (ui_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=ui_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def ui(path: str) -> FileResponse:
            candidate = (ui_dir / path).resolve()
            if path and candidate.is_file() and ui_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(ui_dir / "index.html")

    return app


async def _belt(command: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    """Runs one treadmill command, turning a refusal into a message the operator can act on."""
    try:
        return await command
    except TreadmillError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ConnectionError, OSError) as error:
        raise HTTPException(status_code=502, detail=f"The treadmill link failed: {error}") from error


async def _height(command: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    """One height command, with a refusal the operator can act on."""
    try:
        return await command
    except HeightError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ConnectionError, OSError) as error:
        raise HTTPException(status_code=502, detail=f"The height link failed: {error}") from error


def _profile_from(body: ManualCalibration, method: str, firmware_bcd: str | None) -> CalibrationProfile:
    try:
        return CalibrationProfile(
            zeros=(body.zeros[0], body.zeros[1], body.zeros[2], body.zeros[3]),
            counts_per_kg=(body.counts_per_kg[0], body.counts_per_kg[1],
                           body.counts_per_kg[2], body.counts_per_kg[3]),
            method=method,
            firmware_bcd=firmware_bcd,
            known_weight_kg=body.known_weight_kg,
            note=body.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _filter(entries: list[dict[str, Any]], level: str, component: str | None) -> list[dict[str, Any]]:
    minimum = LEVELS.get(level.lower(), 10)
    return [
        e for e in entries
        if LEVELS.get(str(e.get("level")), 10) >= minimum
        and (component is None or e.get("component") == component)
    ]
