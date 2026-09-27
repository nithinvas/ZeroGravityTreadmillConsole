"""The treadmill and a recording session, through the API.

The point of these is the join between the two: the speed the operator selects on
the belt has to be the speed step and stride length are computed from. Two
sources of truth for that number is exactly the failure the mobile app had, where
the therapist set a speed on the treadmill and typed a different one into the app.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from trendmill.api.app import create_app
from trendmill.device.simulator import CELL_COUNTS_PER_KG, ZERO_OFFSETS, SimulatedBoard
from trendmill.logs import setup_logging
from trendmill.service import Console, ConsoleConfig
from trendmill.treadmill.controller import TreadmillController
from trendmill.treadmill.link import SimulatedTreadmill

RATE = 500.0


def console_with_treadmill(tmp_path: Path) -> tuple[Console, SimulatedTreadmill]:
    setup_logging(None, console=False)
    machine = SimulatedTreadmill(broadcast_s=0.2)
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=110.0)
    console = Console(
        board,
        ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE),
        TreadmillController(machine),
    )
    return console, machine


def calibrate(client: TestClient) -> None:
    client.post(
        "/api/calibration",
        json={"zeros": list(ZERO_OFFSETS), "counts_per_kg": list(CELL_COUNTS_PER_KG)},
    )


def conditions(report: dict[str, Any]) -> list[dict[str, Any]]:
    return report["meta"]["conditions"]


def test_a_session_starts_the_belt_at_one_kph_and_records_that_speed(tmp_path: Path) -> None:
    console, machine = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        assert c.post("/api/treadmill/connect").json()["connected"] is True

        live = c.post("/api/sessions", json={"patient_name": "Asha Rao"}).json()
        assert live["condition"]["speed_kph"] == 1.0

        treadmill = c.get("/api/treadmill").json()
        assert treadmill["running"] is True
        assert treadmill["target_speed_kph"] == 1.0
        assert treadmill["can_start"] is False and treadmill["can_stop"] is True

        result = c.post("/api/sessions/current/stop", json={}).json()

    # The belt is stopped by ending the session, never left running for the next patient.
    assert machine.written[-1] == bytes([0x08, 0x01])
    assert conditions(result)[0]["speed_kph"] == 1.0
    assert result["meta"]["treadmill"]["backend"] == "sim"


def test_a_typed_speed_cannot_diverge_from_the_belt(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        c.post("/api/treadmill/connect")
        # The form still carries a speed; with the belt under control it is ignored,
        # because the treadmill is the one that knows how fast the deck is moving.
        live = c.post("/api/sessions", json={"patient_name": "Asha Rao", "speed_kph": 7.5}).json()
        assert live["condition"]["speed_kph"] == 1.0
        assert c.get("/api/treadmill").json()["target_speed_kph"] == 1.0
        c.post("/api/sessions/current/stop", json={})


def test_every_speed_press_becomes_a_condition_the_gait_maths_uses(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        c.post("/api/treadmill/connect")
        c.post("/api/sessions", json={"patient_name": "Asha Rao"})

        for _ in range(5):
            c.post("/api/treadmill/speed", json={"steps": 1})
        assert c.get("/api/treadmill").json()["target_speed_kph"] == 1.5

        c.post("/api/treadmill/speed", json={"kph": 3.0})
        c.post("/api/treadmill/incline", json={"steps": 2})
        result = c.post("/api/sessions/current/stop", json={}).json()

    speeds = [round(x["speed_kph"], 2) for x in conditions(result)]
    assert speeds == [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 3.0, 3.0]
    assert all(x["speed_kph"] >= 1.0 for x in conditions(result))  # never a 0 km/h block
    assert conditions(result)[-1]["incline_percent"] == 2.0
    # Each one is timed, so the report can attribute every step to the speed it happened at.
    assert all(x["start_s"] >= 0 for x in conditions(result))


def test_stopping_the_belt_mid_session_leaves_the_speed_unknown_not_stale(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        c.post("/api/treadmill/connect")
        c.post("/api/sessions", json={"patient_name": "Asha Rao"})
        c.post("/api/treadmill/speed", json={"kph": 4.0})
        c.post("/api/treadmill/stop")

        status = c.get("/api/status").json()
        assert status["treadmill"]["running"] is False
        # A stopped belt has no speed. Not zero — the machine's range starts at 1.
        assert status["treadmill"]["target_speed_kph"] is None
        assert status["session"]["condition"]["speed_kph"] is None
        assert status["treadmill"]["can_change_speed"] is False

        # And starting again comes back at 1 km/h, not the 4 it was doing before.
        c.post("/api/treadmill/start")
        assert c.get("/api/status").json()["session"]["condition"]["speed_kph"] == 1.0
        result = c.post("/api/sessions/current/stop", json={}).json()

    speeds = [x["speed_kph"] for x in conditions(result)]
    assert speeds == [1.0, 4.0, None, 1.0]


def test_the_belt_stopped_at_its_own_console_is_recorded_too(tmp_path: Path) -> None:
    console, machine = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        c.post("/api/treadmill/connect")
        c.post("/api/sessions", json={"patient_name": "Asha Rao"})
        machine.pull_safety_key()
        time.sleep(0.1)

        status = c.get("/api/status").json()
        assert status["treadmill"]["safety_key_pulled"] is True
        assert status["session"]["condition"]["speed_kph"] is None
        result = c.post("/api/sessions/current/stop", json={}).json()

    assert "safety key" in conditions(result)[-1]["note"].lower()


def test_belt_commands_are_refused_clearly_when_nothing_is_connected(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        for path, body in (
            ("/api/treadmill/start", None),
            ("/api/treadmill/stop", None),
            ("/api/treadmill/speed", {"steps": 1}),
            ("/api/treadmill/incline", {"steps": 1}),
        ):
            response = c.post(path, json=body)
            assert response.status_code == 409
            assert "not connected" in response.json()["detail"]


def test_a_speed_request_needs_a_speed_or_a_step(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        c.post("/api/treadmill/connect")
        c.post("/api/treadmill/start")
        assert c.post("/api/treadmill/speed", json={}).status_code == 400
        assert c.post("/api/treadmill/incline", json={}).status_code == 400


def test_the_speed_buttons_are_refused_while_the_belt_is_stopped(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        c.post("/api/treadmill/connect")
        response = c.post("/api/treadmill/speed", json={"steps": 1})
        assert response.status_code == 409
        assert "comes up at 1.0 km/h" in response.json()["detail"]


def test_the_treadmill_panel_sees_the_frames_in_both_directions(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        c.post("/api/treadmill/connect")
        c.post("/api/treadmill/start")
        log = c.get("/api/treadmill").json()["log"]
    assert any(line["direction"] == "out" for line in log)
    assert any(line["direction"] == "in" for line in log)


def test_disconnecting_leaves_the_console_usable(tmp_path: Path) -> None:
    console, _ = console_with_treadmill(tmp_path)
    with TestClient(create_app(console)) as c:
        calibrate(c)
        c.post("/api/treadmill/connect")
        snapshot = c.post("/api/treadmill/disconnect").json()
        assert snapshot["connected"] is False and snapshot["state"] == "idle"
        # Recording still works over USB with the treadmill gone.
        time.sleep(0.5)
        started = c.post("/api/sessions", json={"patient_name": "Asha Rao", "speed_kph": 2.0,
                                                "without_treadmill": True})
        assert started.status_code == 200
        assert started.json()["condition"]["speed_kph"] == 2.0
        c.post("/api/sessions/current/stop", json={})


def test_the_deck_cannot_be_raised_while_a_session_records(tmp_path: Path) -> None:
    """The one interaction between height and sessions that could hurt someone."""
    from trendmill.height.controller import HeightController
    from trendmill.height.link import SimulatedHeightMechanism

    console, _ = console_with_treadmill(tmp_path)
    console.height = HeightController(SimulatedHeightMechanism())
    with TestClient(create_app(console)) as c:
        calibrate(c)
        assert c.post("/api/height/home").status_code == 200
        console.height._moving_until = 0.0
        assert c.post("/api/height/move", json={"mm": 300}).status_code == 200
        console.height._moving_until = 0.0

        c.post("/api/treadmill/connect")
        c.post("/api/sessions", json={"patient_name": "Asha Rao"})

        locked = c.post("/api/height/move", json={"steps": 1})
        assert locked.status_code == 409
        assert "session is recording" in locked.json()["detail"]
        assert c.get("/api/status").json()["height"]["locked_by_session"] is True
        # Stopping a moving deck stays available even so.
        assert c.post("/api/height/stop").status_code == 200

        result = c.post("/api/sessions/current/stop", json={}).json()

    # The height it ran at is part of the record.
    assert result["meta"]["height_mm"] == 300
    assert console.height.snapshot()["locked_by_session"] is False


def test_a_height_request_needs_a_height_or_a_step(tmp_path: Path) -> None:
    from trendmill.height.controller import HeightController
    from trendmill.height.link import SimulatedHeightMechanism

    console, _ = console_with_treadmill(tmp_path)
    console.height = HeightController(SimulatedHeightMechanism())
    with TestClient(create_app(console)) as c:
        assert c.post("/api/height/move", json={}).status_code == 400
