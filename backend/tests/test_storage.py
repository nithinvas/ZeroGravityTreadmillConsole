from __future__ import annotations

import json
import threading
from pathlib import Path

from tests.conftest import numbered
from treadmill.device.base import StateChange, Transfer
from treadmill.device.replay import ReplaySource
from treadmill.storage.raw_format import RawHeader, RawWriter, iter_records, sha256_of
from treadmill.storage.recorder import Recorder

HEADER = RawHeader(1, 0x413D, 0x2107, 0x0100, 976.5625, 0)


def test_raw_file_round_trips_bit_exact(tmp_path: Path) -> None:
    path = tmp_path / "a.tmraw"
    writer = RawWriter(path, HEADER)
    records = [(i * 4_096_000, numbered(i)) for i in range(100)] + [(999, b"\x01\x02\x03")]
    for arrival, data in records:
        writer.write(arrival, data)
    digest = writer.close()

    assert list(iter_records(path)) == records
    assert digest == sha256_of(path)
    assert (tmp_path / "a.tmraw.sha256").read_text().startswith(digest)


def test_truncated_final_record_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "a.tmraw"
    writer = RawWriter(path, HEADER)
    for i in range(10):
        writer.write(i, numbered(i))
    writer.close()
    with open(path, "r+b") as f:  # a power cut mid-record
        f.truncate(path.stat().st_size - 20)

    assert len(list(iter_records(path))) == 9


def test_checksum_detects_a_changed_byte(tmp_path: Path) -> None:
    path = tmp_path / "a.tmraw"
    writer = RawWriter(path, HEADER)
    writer.write(0, numbered())
    digest = writer.close()
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))

    assert sha256_of(path) != digest


def test_recorder_splits_segments_and_writes_meta(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.start("bench test", 976.5625, {"vid": "413d", "pid": "2107", "bcd_device": "0100"})
    for i in range(5):
        recorder.write(Transfer(i, numbered(i), segment=1))
    for i in range(3):
        recorder.write(Transfer(100 + i, numbered(i), segment=2))
    meta = recorder.stop()

    directory = next(tmp_path.iterdir())
    assert [s["records"] for s in meta["segments"]] == [5, 3]
    assert json.loads((directory / "meta.json").read_text())["transfers"] == 8
    assert recorder.list()[0]["label"] == "bench test"


def test_replay_reproduces_the_recording(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.start("", 976.5625, {})
    sent = [Transfer(i * 4_096_000, numbered(i), 1) for i in range(20)]
    for t in sent:
        recorder.write(t)
    recorder.stop()

    received: list[Transfer] = []
    states: list[StateChange] = []
    ReplaySource(next(tmp_path.iterdir()), speed=0).run(received.append, states.append,
                                                         threading.Event())

    assert [(t.arrival_ns, t.data) for t in received] == [(t.arrival_ns, t.data) for t in sent]
    assert states[-1].state == "stopped"
