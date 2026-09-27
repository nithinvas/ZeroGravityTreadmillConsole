"""Recordings: one directory per recording, one raw file per connection segment.

    <data>/recordings/20260919-181502-3f2a9c1e/
        meta.json
        segment-0001.tmraw
        segment-0001.tmraw.sha256
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from treadmill import __version__
from treadmill.device.base import Transfer
from treadmill.logs import get_logger, log_event
from treadmill.protocol.constants import USB_PRODUCT_ID, USB_VENDOR_ID
from treadmill.storage.raw_format import VERSION, RawHeader, RawWriter

log = get_logger("storage")


@dataclass
class ActiveRecording:
    id: str
    label: str
    directory: Path
    started_at: str
    started_monotonic: float
    nominal_rate_hz: float
    device: dict[str, Any]
    writer: RawWriter | None = None
    segment: int | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    transfers: int = 0


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.active: ActiveRecording | None = None

    def start(self, label: str, nominal_rate_hz: float, device: dict[str, Any]) -> ActiveRecording:
        if self.active is not None:
            raise RuntimeError("a recording is already running")
        rec_id = uuid.uuid4().hex[:8]
        name = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{rec_id}"
        directory = self.root / name
        directory.mkdir(parents=True)
        self.active = ActiveRecording(
            id=name, label=label.strip()[:80], directory=directory, started_at=_now_iso(),
            started_monotonic=time.monotonic(), nominal_rate_hz=nominal_rate_hz, device=dict(device),
        )
        self._write_meta(self.active, finished=False)
        log_event(log, logging.INFO, "storage.recording_started", f"Recording started: {name}",
                  recording=name)
        return self.active

    def write(self, transfer: Transfer) -> None:
        rec = self.active
        if rec is None:
            return
        if rec.segment != transfer.segment or rec.writer is None:
            self._close_segment(rec)
            number = len(rec.segments) + 1
            path = rec.directory / f"segment-{number:04d}.tmraw"
            header = RawHeader(
                version=VERSION,
                vid=_hex_or(rec.device.get("vid"), USB_VENDOR_ID),
                pid=_hex_or(rec.device.get("pid"), USB_PRODUCT_ID),
                bcd_device=_hex_or(rec.device.get("bcd_device"), 0),
                nominal_rate_hz=rec.nominal_rate_hz,
                created_unix_ns=time.time_ns(),
            )
            rec.writer = RawWriter(path, header)
            rec.segment = transfer.segment
            rec.segments.append({"file": path.name, "source_segment": transfer.segment})
        rec.writer.write(transfer.arrival_ns, transfer.data)
        rec.transfers += 1

    def stop(self) -> dict[str, Any]:
        rec = self.active
        if rec is None:
            raise RuntimeError("no recording is running")
        self._close_segment(rec)
        meta = self._write_meta(rec, finished=True)
        self.active = None
        log_event(log, logging.INFO, "storage.recording_stopped",
                  f"Recording stopped: {rec.id} ({rec.transfers} transfers)",
                  recording=rec.id, transfers=rec.transfers)
        return meta

    def status(self) -> dict[str, Any] | None:
        rec = self.active
        if rec is None:
            return None
        return {"id": rec.id, "label": rec.label, "started_at": rec.started_at,
                "elapsed_s": round(time.monotonic() - rec.started_monotonic, 1),
                "transfers": rec.transfers, "segments": len(rec.segments)}

    def list(self) -> list[dict[str, Any]]:
        out = []
        for meta_path in sorted(self.root.glob("*/meta.json"), reverse=True):
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def _close_segment(self, rec: ActiveRecording) -> None:
        if rec.writer is None:
            return
        digest = rec.writer.close()
        rec.segments[-1].update(records=rec.writer.records, bytes=rec.writer.bytes, sha256=digest)
        rec.writer = None

    def _write_meta(self, rec: ActiveRecording, finished: bool) -> dict[str, Any]:
        meta = {
            "id": rec.id,
            "label": rec.label,
            "started_at": rec.started_at,
            "finished_at": _now_iso() if finished else None,
            "duration_s": round(time.monotonic() - rec.started_monotonic, 1) if finished else None,
            "transfers": rec.transfers,
            "nominal_rate_hz": rec.nominal_rate_hz,
            "device": rec.device,
            "segments": rec.segments,
            "app_version": __version__,
        }
        (rec.directory / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta


def _hex_or(value: Any, default: int) -> int:
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return default
