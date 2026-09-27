"""End to end: the simulated board through the running app, over HTTP and WebSocket."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from trendmill.api.app import create_app
from trendmill.device.simulator import SimulatedBoard
from trendmill.logs import setup_logging
from trendmill.service import Console, ConsoleConfig

RATE = 976.5625


def client(tmp_path: Path, packing_bug: bool = False) -> TestClient:
    setup_logging(tmp_path / "logs", console=False)
    console = Console(SimulatedBoard(rate_hz=RATE, packing_bug=packing_bug),
                      ConsoleConfig(data_dir=tmp_path, nominal_rate_hz=RATE))
    return TestClient(create_app(console))


def wait_for(c: TestClient, predicate, timeout: float = 5.0) -> dict:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    status: dict = {}
    while time.monotonic() < deadline:
        status = c.get("/api/status").json()
        if predicate(status):
            return status
        time.sleep(0.1)
    raise AssertionError(f"condition not met; last status: {status}")


def test_streams_and_reports_rate_and_channels(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        status = wait_for(c, lambda s: s["stream"]["counters"]["samples"] > 2000)

    assert status["link"]["state"] == "streaming"
    assert abs(status["stream"]["rate_hz"] - RATE) / RATE < 0.05
    assert [ch["name"] for ch in status["channels"]] == ["TL", "TR", "BR", "BL"]
    means = [ch["mean"] for ch in status["channels"]]
    assert len({round(m, -3) for m in means}) == 4  # four distinct cells
    assert not [w for w in status["warnings"] if w["code"] == "channels_identical"]


def test_flags_the_firmware_packing_bug(tmp_path: Path) -> None:
    with client(tmp_path, packing_bug=True) as c:
        status = wait_for(c, lambda s: any(w["code"] == "channels_identical" for w in s["warnings"]))

    assert status["link"]["state"] == "streaming"


def test_recording_start_stop_and_list(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        wait_for(c, lambda s: s["stream"]["counters"]["transfers"] > 10)
        assert c.post("/api/recordings/start", json={"label": "press TL"}).status_code == 200
        assert c.post("/api/recordings/start", json={}).status_code == 409
        wait_for(c, lambda s: (s["recording"] or {}).get("transfers", 0) > 100)
        meta = c.post("/api/recordings/stop").json()
        assert c.post("/api/recordings/stop").status_code == 409
        listed = c.get("/api/recordings").json()

    assert meta["label"] == "press TL" and meta["transfers"] > 100
    assert listed[0]["id"] == meta["id"]
    assert (tmp_path / "recordings" / meta["id"] / "segment-0001.tmraw").exists()


def test_live_websocket_pushes_snapshots(tmp_path: Path) -> None:
    with client(tmp_path) as c, c.websocket_connect("/ws/live") as ws:
        first = ws.receive_json()
        second = ws.receive_json()

    assert {"app", "link", "stream", "channels", "warnings", "recording"} <= first.keys()
    assert second["stream"]["counters"]["transfers"] >= first["stream"]["counters"]["transfers"]


def test_logs_are_available_live_and_levels_change(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        wait_for(c, lambda s: s["link"]["state"] == "streaming")
        assert any(e["event"] == "usb.connected" for e in c.get("/api/logs").json())
        with c.websocket_connect("/ws/logs") as ws:
            assert "event" in ws.receive_json()
        assert c.post("/api/logging", json={"component": "gait", "level": "debug"}).status_code == 200
        assert c.get("/api/logging").json()["gait"] == "debug"
        assert c.post("/api/logging", json={"component": "x", "level": "debug"}).status_code == 400

    assert (tmp_path / "logs" / "trendmill.jsonl").read_text().count("usb.connected") >= 1
