"""Sessions: recording, per-condition summaries, saved files, search and recovery."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from treadmill.api.app import create_app
from treadmill.calibration.profile import CalibrationProfile, Method
from treadmill.device.simulator import CELL_COUNTS_PER_KG, ZERO_OFFSETS, SimulatedBoard
from treadmill.logs import setup_logging
from treadmill.processor import Sample
from treadmill.service import Console, ConsoleConfig
from treadmill.sessions.manager import SessionDetails, SessionManager

RATE = 976.5625
US = 1_000_000
PROFILE = CalibrationProfile(
    tuple(float(z) for z in ZERO_OFFSETS),  # type: ignore[arg-type]
    CELL_COUNTS_PER_KG,
    Method.FOUR_POSITION,
    firmware_bcd="0000",
)


def details(**overrides: object) -> SessionDetails:
    base: dict[str, object] = {
        "patient_name": "Asha Rao",
        "patient_id": "P-014",
        "issue": "left knee",
        "tester": "Nithin",
        "speed_kph": 3.0,
        "activity": "walk",
    }
    return SessionDetails(**(base | overrides))  # type: ignore[arg-type]


def walk(manager: SessionManager, board: SimulatedBoard, start_s: float, seconds: float) -> None:
    session = manager.active
    assert session is not None
    first = int(start_s * RATE)
    for i in range(first, first + int(seconds * RATE)):
        session.on_samples([Sample(round(i * US / RATE), board.sample(i), 1)])


def test_a_session_records_conditions_steps_and_summaries(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=105.0)
    manager.start(details(), PROFILE, {"bcd_device": "0000"}, RATE, now_us=0)
    walk(manager, board, 0, 25)
    live = manager.active.live()  # type: ignore[union-attr]
    assert live["gait"]["cadence_spm"] == pytest.approx(105, rel=0.02)

    manager.new_condition(4.5, "walk", None, "faster")
    walk(manager, board, 25, 25)
    result = manager.stop("went well")

    blocks = result["summary"]["blocks"]
    assert [b["condition"]["speed_kph"] for b in blocks] == [3.0, 4.5]
    assert blocks[0]["cadence_spm"]["median"] == pytest.approx(105, rel=0.02)
    assert blocks[0]["step_length_m"]["median"] == pytest.approx(3.0 / 3.6 * 60 / 105, rel=0.03)
    assert blocks[1]["step_length_m"]["median"] == pytest.approx(4.5 / 3.6 * 60 / 105, rel=0.03)
    assert blocks[1]["stride_length_m"]["median"] == pytest.approx(2 * 4.5 / 3.6 * 60 / 105, rel=0.03)
    assert blocks[1]["transitions"] >= 1
    assert result["meta"]["status"] == "completed"
    assert result["meta"]["calibration"]["counts_per_kg"] == list(CELL_COUNTS_PER_KG)


def test_every_session_file_is_written(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    board = SimulatedBoard(rate_hz=RATE)
    session = manager.start(details(), PROFILE, {}, RATE, now_us=0)
    walk(manager, board, 0, 15)
    manager.stop()
    folder = tmp_path / session.id

    for name in ("session.json", "steps.csv", "trace.csv", "summary.json"):
        assert (folder / name).exists(), name
    with open(folder / "trace.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == pytest.approx(150, abs=3)  # 10 per second
    total = float(rows[-1]["total_kg"])
    assert 50 < total < 75  # the simulated 60 kg walker, rising and falling with each step
    meta = json.loads((folder / "session.json").read_text())
    assert meta["details"]["patient_name"] == "Asha Rao"
    assert meta["gait_engine"]["version"] == "gait-engine 1.0.0"


def test_search_finds_sessions_by_any_detail(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    board = SimulatedBoard(rate_hz=RATE)
    for name, pid in (("Asha Rao", "P-014"), ("Ravi Kumar", "P-020")):
        manager.start(details(patient_name=name, patient_id=pid), PROFILE, {}, RATE, now_us=0)
        walk(manager, board, 0, 8)
        manager.stop()

    assert [r["patient_name"] for r in manager.index.search("asha")] == ["Asha Rao"]
    assert [r["patient_id"] for r in manager.index.search("P-020")] == ["P-020"]
    assert len(manager.index.search("nithin")) == 2  # the tester
    assert len(manager.index.search("")) == 2
    today = time.strftime("%Y-%m-%d", time.gmtime())
    assert len(manager.index.search("", date_from=today, date_to=today)) == 2
    assert manager.index.search("", date_from="2000-01-01", date_to="2000-01-02") == []


def test_the_index_is_rebuilt_from_the_folders(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    manager.start(details(), PROFILE, {}, RATE, now_us=0)
    walk(manager, SimulatedBoard(rate_hz=RATE), 0, 5)
    manager.stop()
    (tmp_path / "index.sqlite").unlink()

    assert len(SessionManager(tmp_path).index.search("")) == 1


def test_a_crashed_session_is_recovered_as_interrupted(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.start(details(), PROFILE, {}, RATE, now_us=0)
    walk(manager, SimulatedBoard(rate_hz=RATE), 0, 12)
    session._steps_file.flush()  # what the one-second flush would have done before the crash
    # No stop(): the process died here.

    recovered = SessionManager(tmp_path)
    rows = recovered.index.search("")
    assert rows[0]["status"] == "interrupted"
    report = recovered.report(session.id)
    assert report is not None and report["summary"]["steps_accepted"] > 5


def test_a_session_needs_coefficients(tmp_path: Path) -> None:
    with pytest.raises(LookupError):
        SessionManager(tmp_path).start(details(), None, {}, RATE, now_us=0)


@pytest.mark.parametrize(
    "bad", [{"patient_name": "", "patient_id": ""}, {"speed_kph": -1.0}, {"activity": "dance"}]
)
def test_session_details_are_validated(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        details(**bad)


def test_report_files_cannot_escape_the_sessions_folder(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)

    assert manager.report("../secrets") is None
    assert manager.file_path("..", "session.json") is None


# ---- API ---------------------------------------------------------------------


def test_session_api_end_to_end(tmp_path: Path) -> None:
    setup_logging(None, console=False)
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=110.0)
    console = Console(board, ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    with TestClient(create_app(console)) as c:
        # This console has no treadmill, so a plain start is refused with an
        # explanation rather than quietly running with dead speed buttons.
        without_belt = {"patient_name": "Asha Rao", "tester": "Nithin", "speed_kph": 3.0}
        refusal = c.post("/api/sessions", json=without_belt)
        assert refusal.status_code == 409
        assert "without belt control" in refusal.json()["detail"]

        start = without_belt | {"without_treadmill": True}
        assert c.post("/api/sessions", json=start).status_code == 409  # no coefficients yet
        c.post(
            "/api/calibration", json={"zeros": list(ZERO_OFFSETS), "counts_per_kg": list(CELL_COUNTS_PER_KG)}
        )
        time.sleep(1.0)
        assert c.post("/api/sessions", json=start).status_code == 200
        assert c.post("/api/sessions", json=start).status_code == 409  # one at a time

        deadline = time.monotonic() + 15
        cadence = None
        while time.monotonic() < deadline and cadence is None:
            time.sleep(0.5)
            cadence = c.get("/api/status").json()["session"]["gait"]["cadence_spm"]
        assert cadence == pytest.approx(110, rel=0.03)

        assert c.post("/api/sessions/current/condition", json={"speed_kph": 4.0}).status_code == 200
        with c.websocket_connect("/ws/chart") as ws:
            message = ws.receive_json()
        assert message["units"] == "kg" and len(message["points"][0]) == 7
        result = c.post("/api/sessions/current/stop", json={"notes": "fine"}).json()
        session_id = result["meta"]["id"]

        found = c.get("/api/sessions", params={"q": "asha"}).json()
        report = c.get(f"/api/sessions/{session_id}").json()
        steps_csv = c.get(f"/api/sessions/{session_id}/files/steps.csv")
        missing = c.get("/api/sessions/nope")

    assert found[0]["id"] == session_id and found[0]["main_cadence"] == pytest.approx(110, rel=0.03)
    assert len(report["summary"]["blocks"]) == 2 and report["steps"] and report["trace"]["total_kg"]
    assert steps_csv.status_code == 200 and steps_csv.text.startswith("time_s,side")
    assert missing.status_code == 404
