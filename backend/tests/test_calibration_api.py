"""Calibration and weighing end to end, driving the simulator like a technician would."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trendmill.api.app import create_app
from trendmill.device.simulator import CELL_COUNTS_PER_KG, SimulatedBoard
from trendmill.logs import setup_logging
from trendmill.service import Console, ConsoleConfig

RATE = 976.5625
# One shared coefficient: the mean of the simulated cells' sensitivities.
SIM_SHARED = sum(CELL_COUNTS_PER_KG) / 4
SIM_DEFAULT_COUNTS = [SIM_SHARED] * 4
CORNERS = {"TL": (0.1, 0.1), "TR": (0.9, 0.1), "BR": (0.9, 0.9), "BL": (0.1, 0.9)}


@pytest.fixture
def api(tmp_path: Path) -> Any:
    setup_logging(None, console=False)
    board = SimulatedBoard(rate_hz=RATE, noise_counts=40.0)
    board.set_load("empty")
    console = Console(board, ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(console)) as client:
        yield client


def settle_and_capture(
    c: TestClient, mode: str, kg: float = 0.0, x: float = 0.5, y: float = 0.5
) -> list[float]:
    assert c.post("/api/simulator/load", json={"mode": mode, "kg": kg, "x": x, "y": y}).status_code == 200
    time.sleep(2.2)  # let the 2 s window fill with the new load only
    response = c.post("/api/calibration/capture")
    assert response.status_code == 200, response.text
    return response.json()["means"]


def test_no_calibration_means_no_weight(api: TestClient) -> None:
    time.sleep(0.5)
    status = api.get("/api/status").json()
    calibration = api.get("/api/calibration").json()

    assert status["calibration"]["status"] == "missing"
    assert status["weight"] is None
    assert calibration["defaults"]["present"] is False
    assert "Default values are not present" in calibration["message"]
    assert api.post("/api/calibration/use-defaults").status_code == 409


def test_set_then_use_defaults_weighs_correctly(api: TestClient) -> None:
    zeros = settle_and_capture(api, "empty")
    written = api.post(
        "/api/calibration/defaults", json={"zeros": zeros, "counts_per_kg": SIM_DEFAULT_COUNTS}
    )
    assert written.json()["defaults"]["present"] is True
    assert written.json()["in_use"] == "none"  # writing defaults does not select them

    selected = api.post("/api/calibration/use-defaults").json()
    assert selected["in_use"] == "defaults" and selected["status"] == "ok"

    settle_and_capture(api, "static", kg=58.0)
    weight = api.get("/api/status").json()["weight"]
    # One shared coefficient for every cell; the simulated cells differ by up to 1.4%.
    assert weight["average_kg"] == pytest.approx(58.0, rel=0.03)
    assert weight["stable"] is True


def test_changing_defaults_while_in_use_takes_effect_at_once(api: TestClient) -> None:
    api.post("/api/calibration/defaults", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [-1856] * 4})
    api.post("/api/calibration/use-defaults")
    api.post("/api/calibration/defaults", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [-2000] * 4})

    assert api.get("/api/calibration").json()["active"]["counts_per_kg"] == [-2000.0] * 4


def test_other_coefficients_replace_the_defaults_everywhere(api: TestClient) -> None:
    api.post("/api/calibration/defaults", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [-1856] * 4})
    api.post("/api/calibration/use-defaults")
    custom = api.post("/api/calibration", json={"zeros": [1, 2, 3, 4], "counts_per_kg": [-1900] * 4}).json()

    assert custom["in_use"] == "custom"
    assert custom["active"]["counts_per_kg"] == [-1900.0] * 4


def test_the_defaults_method_cannot_be_forged(api: TestClient) -> None:
    response = api.post(
        "/api/calibration", json={"zeros": [0] * 4, "counts_per_kg": [-1] * 4, "method": "defaults"}
    )

    assert response.status_code == 400


def test_one_capture_calibration_from_a_known_weight(api: TestClient) -> None:
    zeros = settle_and_capture(api, "empty")
    loaded = settle_and_capture(api, "static", kg=20.0, x=0.3, y=0.7)
    solved = api.post(
        "/api/calibration/solve", json={"known_weight_kg": 20.0, "zeros": zeros, "loaded": [loaded]}
    ).json()

    assert solved["method"] == "one_capture" and solved["kind"] == "shared"
    assert solved["counts_per_kg"][0] == pytest.approx(SIM_SHARED, rel=0.03)


def test_four_position_calibration_recovers_each_cell(api: TestClient) -> None:
    zeros = settle_and_capture(api, "empty")
    rows = [settle_and_capture(api, "static", kg=20.0, x=x, y=y) for x, y in CORNERS.values()]
    solved = api.post(
        "/api/calibration/solve", json={"known_weight_kg": 20.0, "zeros": zeros, "loaded": rows}
    ).json()

    assert solved["method"] == "four_position"
    for got, want in zip(solved["counts_per_kg"], CELL_COUNTS_PER_KG, strict=True):
        assert got == pytest.approx(want, rel=0.02)

    api.post(
        "/api/calibration",
        json={
            "zeros": zeros,
            "counts_per_kg": solved["counts_per_kg"],
            "method": solved["method"],
            "known_weight_kg": 20.0,
        },
    )
    settle_and_capture(api, "static", kg=73.0, x=0.65, y=0.35)  # a spot never calibrated
    assert api.get("/api/status").json()["weight"]["average_kg"] == pytest.approx(73.0, rel=0.01)


def test_solve_refuses_captures_that_never_moved(api: TestClient) -> None:
    zeros = [-536_660.0, 101_508.0, 694_467.0, -19_659.0]
    response = api.post(
        "/api/calibration/solve", json={"known_weight_kg": 20.0, "zeros": zeros, "loaded": [zeros]}
    )

    assert response.status_code == 422


def test_saving_rejects_a_zero_coefficient(api: TestClient) -> None:
    response = api.post("/api/calibration", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [0, 1, 1, 1]})

    assert response.status_code == 400


def test_selected_defaults_are_read_from_the_file_at_every_start(tmp_path: Path) -> None:
    setup_logging(None, console=False)
    first = Console(SimulatedBoard(rate_hz=RATE), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(first)) as c:
        c.post("/api/calibration/defaults", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [-1856] * 4})
        c.post("/api/calibration/use-defaults")
    defaults_file = tmp_path / "calibration" / "defaults.json"
    data = json.loads(defaults_file.read_text())
    data["counts_per_kg"] = [-22_000] * 4
    defaults_file.write_text(json.dumps(data))

    second = Console(SimulatedBoard(rate_hz=RATE), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    assert second.profile is not None and second.profile.counts_per_kg == (-22_000.0,) * 4


def test_calibration_survives_a_restart(tmp_path: Path) -> None:
    setup_logging(None, console=False)
    first = Console(SimulatedBoard(rate_hz=RATE), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(first)) as c:
        c.post("/api/calibration", json={"zeros": [1, 2, 3, 4], "counts_per_kg": [-1856] * 4})

    second = Console(SimulatedBoard(rate_hz=RATE), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    assert second.profile is not None and second.profile.zeros == (1.0, 2.0, 3.0, 4.0)


def test_firmware_change_invalidates_the_calibration(tmp_path: Path) -> None:
    setup_logging(None, console=False)
    console = Console(SimulatedBoard(rate_hz=RATE), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(console)) as c:
        time.sleep(0.3)
        c.post("/api/calibration", json={"zeros": [0, 0, 0, 0], "counts_per_kg": [-1856] * 4})
        assert c.get("/api/calibration").json()["status"] == "ok"

        console.device = console.device | {"bcd_device": "0200"}  # the board was reflashed
        status = c.get("/api/calibration").json()

    assert status["status"] == "firmware_mismatch"
    assert "0000" in status["message"] and "0200" in status["message"]


def test_simulator_controls_are_refused_for_real_hardware(tmp_path: Path) -> None:
    from trendmill.device.replay import ReplaySource

    setup_logging(None, console=False)
    console = Console(ReplaySource(tmp_path / "none"), ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(console)) as c:
        assert c.post("/api/simulator/load", json={"mode": "empty"}).status_code == 409
