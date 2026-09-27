"""Test sessions: the equivalent of the mobile app's Firmware Tester mode.

A session records everything needed to review it later:

    <data>/sessions/20260919-183015-3f2a9c1e/
        session.json      who, what, when, conditions, the calibration used, versions
        steps.csv         every detected step with its confidence and reasons
        trace.csv         the four cells and total load in kg, 10 times a second
        summary.json      per-condition medians and ranges
        raw/segment-*.tmraw   every USB transfer, untouched, for replay

Files are written as the session runs, so a crash leaves a recoverable session
marked "interrupted" rather than nothing.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from treadmill import __version__
from treadmill.calibration.profile import CalibrationProfile
from treadmill.device.base import Transfer
from treadmill.gait.engine import GaitEngine, Step
from treadmill.gait.speed import SpeedTimeline
from treadmill.logs import get_logger, log_event
from treadmill.processor import Sample
from treadmill.protocol.constants import USB_PRODUCT_ID, USB_VENDOR_ID
from treadmill.sessions.index import SessionIndex, index_row
from treadmill.sessions.summary import summarize
from treadmill.storage.raw_format import VERSION, RawHeader, RawWriter

log = get_logger("session")

US_PER_S = 1_000_000
TRACE_INTERVAL_US = 100_000  # 10 points per second in trace.csv
STEP_FIELDS = (
    "time_s",
    "side",
    "step_time_s",
    "step_length_m",
    "stride_time_s",
    "stride_length_m",
    "speed_kph",
    "confidence",
    "accepted",
    "transition",
    "running",
    "condition_id",
    "amplitude_kg",
    "reasons",
)
ACTIVITIES = ("walk", "jog", "run")


@dataclass(frozen=True)
class SessionDetails:
    patient_name: str
    patient_id: str = ""
    issue: str = ""
    tester: str = ""
    speed_kph: float = 0.0
    activity: str = "walk"
    body_weight_kg: float | None = None
    bws_percent: float | None = None
    incline_percent: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.patient_name.strip() and not self.patient_id.strip():
            raise ValueError("Enter the patient's name or ID.")
        if not 0 <= self.speed_kph <= 25:
            raise ValueError("Belt speed must be between 0 and 25 km/h.")
        if self.activity not in ACTIVITIES:
            raise ValueError(f"Activity must be one of {', '.join(ACTIVITIES)}.")


class ActiveSession:
    def __init__(
        self,
        directory: Path,
        details: SessionDetails,
        profile: CalibrationProfile,
        device: dict[str, Any],
        nominal_rate_hz: float,
        start_us: int,
    ) -> None:
        self.id = directory.name
        self.directory = directory
        self.details = details
        self.profile = profile
        self.device = dict(device)
        self.nominal_rate_hz = nominal_rate_hz
        self.start_us = start_us
        self.started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        self.started_monotonic = time.monotonic()
        self.speed = SpeedTimeline()
        self.engine = GaitEngine(nominal_rate_hz, self.speed)
        self.conditions: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        #: How the treadmill was reached, if at all, recorded with the session.
        self.treadmill: dict[str, Any] | None = None
        #: The deck height this session ran at, in mm, when it is known.
        self.height_mm: int | None = None
        self.last_us = start_us
        (directory / "raw").mkdir(parents=True)
        self._raw: RawWriter | None = None
        self._raw_segment: int | None = None
        self._raw_files: list[dict[str, Any]] = []
        self._steps_file: TextIO = open(directory / "steps.csv", "w", newline="", encoding="utf-8")  # noqa: SIM115
        self._steps_csv = csv.writer(self._steps_file)
        self._steps_csv.writerow(STEP_FIELDS)
        self._trace_file: TextIO = open(directory / "trace.csv", "w", newline="", encoding="utf-8")  # noqa: SIM115
        self._trace_csv = csv.writer(self._trace_file)
        self._trace_csv.writerow(("time_s", "tl_kg", "tr_kg", "br_kg", "bl_kg", "total_kg"))
        self._trace_block = [0.0] * 4
        self._trace_n = 0
        self._trace_next = start_us + TRACE_INTERVAL_US
        self._last_flush = time.monotonic()
        self.add_condition(
            details.speed_kph, details.activity, details.bws_percent, "start", details.incline_percent
        )

    # ---- conditions --------------------------------------------------------

    def add_condition(
        self,
        speed_kph: float | None,
        activity: str,
        bws_percent: float | None,
        note: str,
        incline_percent: float | None = None,
    ) -> dict[str, Any]:
        condition_id = len(self.conditions) + 1
        condition: dict[str, Any] = {
            "id": condition_id,
            "start_s": round((self.last_us - self.start_us) / US_PER_S, 3),
            "speed_kph": speed_kph,
            "activity": activity,
            "bws_percent": bws_percent,
            "incline_percent": incline_percent,
            "note": note,
        }
        self.conditions.append(condition)
        # None means the deck was not moving. Lengths are then reported as
        # unavailable for that stretch rather than computed from a stale speed.
        self.speed.set(self.last_us, speed_kph)
        self.engine.set_condition(condition_id)
        self._write_meta("recording")
        return condition

    # ---- data --------------------------------------------------------------

    def on_transfer(self, transfer: Transfer) -> None:
        if self._raw_segment != transfer.segment or self._raw is None:
            self._close_raw()
            path = self.directory / "raw" / f"segment-{len(self._raw_files) + 1:04d}.tmraw"
            self._raw = RawWriter(
                path,
                RawHeader(
                    VERSION,
                    _hex(self.device.get("vid"), USB_VENDOR_ID),
                    _hex(self.device.get("pid"), USB_PRODUCT_ID),
                    _hex(self.device.get("bcd_device"), 0),
                    self.nominal_rate_hz,
                    time.time_ns(),
                ),
            )
            self._raw_segment = transfer.segment
            self._raw_files.append({"file": f"raw/{path.name}", "source_segment": transfer.segment})
        self._raw.write(transfer.arrival_ns, transfer.data)

    def on_samples(self, samples: list[Sample]) -> list[Step]:
        new_steps: list[Step] = []
        for sample in samples:
            if sample.t_us < self.start_us:
                continue
            self.last_us = sample.t_us
            cells = self.profile.cell_kg(sample.values)
            new_steps += self.engine.feed(sample.t_us, cells[0], cells[1])
            for i in range(4):
                self._trace_block[i] += cells[i]
            self._trace_n += 1
            if sample.t_us >= self._trace_next:
                avg = [v / self._trace_n for v in self._trace_block]
                self._trace_csv.writerow(
                    [round((sample.t_us - self.start_us) / US_PER_S, 2)]
                    + [round(v, 2) for v in avg]
                    + [round(sum(avg), 2)]
                )
                self._trace_block = [0.0] * 4
                self._trace_n = 0
                self._trace_next = sample.t_us + TRACE_INTERVAL_US
        for step in new_steps:
            row = step.as_dict()
            row["time_s"] = round((step.t_us - self.start_us) / US_PER_S, 3)
            self.steps.append(row)
            self._steps_csv.writerow([";".join(row[f]) if f == "reasons" else row[f] for f in STEP_FIELDS])
        if time.monotonic() - self._last_flush >= 1.0:
            self._steps_file.flush()
            self._trace_file.flush()
            self._last_flush = time.monotonic()
        return new_steps

    # ---- live and finish ---------------------------------------------------

    def live(self) -> dict[str, Any]:
        accepted = [s for s in self.steps if s["accepted"]]
        return {
            "id": self.id,
            "details": asdict(self.details),
            "elapsed_s": round(time.monotonic() - self.started_monotonic, 1),
            "condition": self.conditions[-1],
            "conditions": len(self.conditions),
            "gait": self.engine.live(),
            "walking_s": round(sum(s["step_time_s"] for s in accepted), 1),
            "distance_m": round(sum(s["step_length_m"] for s in self.steps if s["step_length_m"]), 1),
            "recent_steps": self.steps[-12:],
        }

    def finish(self, status: str, closing_notes: str = "") -> dict[str, Any]:
        self._close_raw()
        self._steps_file.close()
        self._trace_file.close()
        summary = summarize(self.steps, self.conditions)
        (self.directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return self._write_meta(status, closing_notes)

    def _close_raw(self) -> None:
        if self._raw is not None:
            digest = self._raw.close()
            self._raw_files[-1].update(records=self._raw.records, sha256=digest)
            self._raw = None

    def _write_meta(self, status: str, closing_notes: str = "") -> dict[str, Any]:
        meta = {
            "id": self.id,
            "status": status,
            "details": asdict(self.details),
            "started_at": self.started_at,
            "finished_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            if status != "recording"
            else None,
            "duration_s": round(time.monotonic() - self.started_monotonic, 1),
            "closing_notes": closing_notes,
            "conditions": self.conditions,
            "calibration": self.profile.to_dict(),
            "device": self.device,
            "treadmill": self.treadmill,
            "height_mm": self.height_mm,
            "nominal_rate_hz": self.nominal_rate_hz,
            "gait_engine": asdict(self.engine.config),
            "app_version": __version__,
            "raw_files": self._raw_files,
        }
        (self.directory / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta


class SessionManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = SessionIndex(root / "index.sqlite")
        self.active: ActiveSession | None = None
        self._recover_interrupted()
        if self.index.count() == 0:
            self.index.rebuild(root)

    def start(
        self,
        details: SessionDetails,
        profile: CalibrationProfile | None,
        device: dict[str, Any],
        nominal_rate_hz: float,
        now_us: int,
    ) -> ActiveSession:
        if self.active is not None:
            raise RuntimeError("A session is already running.")
        if profile is None:
            raise LookupError(
                "Select coefficients on the Calibration tab first: every load and "
                "gait value is computed from them."
            )
        name = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.active = ActiveSession(self.root / name, details, profile, device, nominal_rate_hz, now_us)
        log_event(
            log,
            logging.INFO,
            "session.started",
            f"Session started: {name}",
            session=name,
            speed_kph=details.speed_kph,
            activity=details.activity,
        )
        return self.active

    def new_condition(
        self,
        speed_kph: float | None,
        activity: str,
        bws_percent: float | None,
        note: str,
        incline_percent: float | None = None,
    ) -> dict[str, Any]:
        if self.active is None:
            raise RuntimeError("No session is running.")
        if activity not in ACTIVITIES:
            raise ValueError(f"Activity must be one of {', '.join(ACTIVITIES)}.")
        condition = self.active.add_condition(speed_kph, activity, bws_percent, note, incline_percent)
        log_event(
            log,
            logging.INFO,
            "session.condition",
            f"Condition {condition['id']}: {speed_kph} km/h, {activity}",
            session=self.active.id,
            **{k: v for k, v in condition.items() if k != "id"},
        )
        return condition

    def stop(self, closing_notes: str = "") -> dict[str, Any]:
        session = self.active
        if session is None:
            raise RuntimeError("No session is running.")
        self.active = None
        meta = session.finish("completed", closing_notes)
        summary = json.loads((session.directory / "summary.json").read_text(encoding="utf-8"))
        self.index.upsert(index_row(meta, summary, session.directory.name))
        log_event(
            log,
            logging.INFO,
            "session.finished",
            f"Session finished: {session.id}",
            session=session.id,
            steps_accepted=summary["steps_accepted"],
        )
        return {"meta": meta, "summary": summary}

    def shutdown(self) -> None:
        """The server is stopping mid-session: save what there is, clearly marked."""
        if self.active is not None:
            session, self.active = self.active, None
            meta = session.finish("interrupted", "The server stopped during the session.")
            summary = json.loads((session.directory / "summary.json").read_text(encoding="utf-8"))
            self.index.upsert(index_row(meta, summary, session.directory.name))

    def report(self, session_id: str, max_trace_points: int = 3000) -> dict[str, Any] | None:
        directory = self._folder(session_id)
        if directory is None:
            return None
        meta = json.loads((directory / "session.json").read_text(encoding="utf-8"))
        summary_path = directory / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
        steps = _read_steps(directory / "steps.csv")
        trace = _read_trace(directory / "trace.csv", max_trace_points)
        return {"meta": meta, "summary": summary, "steps": steps, "trace": trace}

    def file_path(self, session_id: str, name: str) -> Path | None:
        directory = self._folder(session_id)
        if directory is None or name not in ("steps.csv", "trace.csv", "session.json", "summary.json"):
            return None
        path = directory / name
        return path if path.exists() else None

    def _folder(self, session_id: str) -> Path | None:
        # Only a plain folder name inside the sessions root: never a path from the request.
        if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
            return None
        directory = self.root / session_id
        return directory if (directory / "session.json").exists() else None

    def _recover_interrupted(self) -> None:
        """A session left "recording" by a crash or power cut is summarised from its files."""
        for meta_path in self.root.glob("*/session.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("status") != "recording":
                continue
            steps = _read_steps(meta_path.parent / "steps.csv")
            summary = summarize(steps, meta.get("conditions", []))
            (meta_path.parent / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            meta["status"] = "interrupted"
            meta["closing_notes"] = "Recovered after the server stopped unexpectedly."
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self.index.upsert(index_row(meta, summary, meta_path.parent.name))
            log_event(
                log,
                logging.WARNING,
                "session.recovered",
                f"Recovered interrupted session {meta.get('id')}",
                session=meta.get("id"),
            )


def _read_steps(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out.append(
                    {
                        "time_s": float(row["time_s"]),
                        "side": row["side"],
                        "step_time_s": float(row["step_time_s"]),
                        "step_length_m": _float(row["step_length_m"]),
                        "stride_time_s": _float(row["stride_time_s"]),
                        "stride_length_m": _float(row["stride_length_m"]),
                        "speed_kph": _float(row["speed_kph"]),
                        "confidence": row["confidence"],
                        "accepted": row["accepted"] == "True",
                        "transition": row["transition"] == "True",
                        "running": row["running"] == "True",
                        "condition_id": int(row["condition_id"]),
                        "amplitude_kg": _float(row["amplitude_kg"]),
                        "reasons": [r for r in row["reasons"].split(";") if r],
                    }
                )
            except (KeyError, ValueError):
                continue  # a half-written final line after a power cut
    return out


def _read_trace(path: Path, max_points: int) -> dict[str, list[float]]:
    columns: dict[str, list[float]] = {
        "time_s": [],
        "tl_kg": [],
        "tr_kg": [],
        "br_kg": [],
        "bl_kg": [],
        "total_kg": [],
    }
    if not path.exists():
        return columns
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if len(r) == 6 and all(r.values())]
    step = max(1, len(rows) // max_points)
    for row in rows[::step]:
        for key in columns:
            columns[key].append(float(row[key]))
    return columns


def _float(value: str) -> float | None:
    return float(value) if value not in ("", "None") else None


def _hex(value: Any, default: int) -> int:
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return default
