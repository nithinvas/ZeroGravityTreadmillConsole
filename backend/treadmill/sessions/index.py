"""A searchable index of saved sessions.

The session folders are the record; this SQLite file only makes them fast to
search. It can be deleted at any time and is rebuilt from the folders.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

COLUMNS = (
    "id",
    "folder",
    "started_at",
    "finished_at",
    "status",
    "patient_name",
    "patient_id",
    "issue",
    "tester",
    "activity",
    "notes",
    "duration_s",
    "walking_s",
    "distance_m",
    "steps_accepted",
    "conditions",
    "speeds",
    "main_cadence",
    "main_step_length",
    "main_stride_length",
)

NUMERIC = {
    "duration_s",
    "walking_s",
    "distance_m",
    "steps_accepted",
    "conditions",
    "main_cadence",
    "main_step_length",
    "main_stride_length",
}


def _schema() -> str:
    cols = ",\n    ".join(f"{c} {'REAL' if c in NUMERIC else 'TEXT'}" for c in COLUMNS)
    return f"CREATE TABLE IF NOT EXISTS sessions (\n    {cols},\n    PRIMARY KEY (id)\n)"


class SessionIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(_schema())

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def upsert(self, row: dict[str, Any]) -> None:
        values = [row.get(c) for c in COLUMNS]
        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._connect() as db:
            db.execute(
                f"INSERT OR REPLACE INTO sessions ({', '.join(COLUMNS)}) VALUES ({placeholders})", values
            )

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def search(
        self,
        q: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        args: list[Any] = []
        if q.strip():
            for word in q.lower().split():
                like = f"%{word}%"
                where.append(
                    "("
                    + " OR ".join(
                        f"LOWER(COALESCE({c}, '')) LIKE ?"
                        for c in ("patient_name", "patient_id", "tester", "issue", "notes", "id", "activity")
                    )
                    + ")"
                )
                args.extend([like] * 7)
        if date_from:
            where.append("started_at >= ?")
            args.append(date_from)
        if date_to:
            where.append("started_at < ?")
            args.append(date_to + "T99")  # inclusive of the whole day
        sql = "SELECT * FROM sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def rebuild(self, sessions_root: Path) -> int:
        """Re-reads every session folder. Returns how many were indexed."""
        count = 0
        for meta_path in sessions_root.glob("*/session.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                summary_path = meta_path.parent / "summary.json"
                summary = (
                    json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
                )
            except (OSError, ValueError):
                continue
            self.upsert(index_row(meta, summary, meta_path.parent.name))
            count += 1
        return count


def index_row(meta: dict[str, Any], summary: dict[str, Any], folder: str) -> dict[str, Any]:
    details = meta.get("details", {})
    blocks = summary.get("blocks", [])
    main = next((b for b in blocks if b["condition"]["id"] == summary.get("main_condition_id")), None)
    speeds = sorted({b["condition"].get("speed_kph") for b in blocks if b["condition"].get("speed_kph")})
    return {
        "id": meta["id"],
        "folder": folder,
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("finished_at"),
        "status": meta.get("status"),
        "patient_name": details.get("patient_name"),
        "patient_id": details.get("patient_id"),
        "issue": details.get("issue"),
        "tester": details.get("tester"),
        "activity": details.get("activity"),
        "notes": " ".join(filter(None, [details.get("notes"), meta.get("closing_notes")])),
        "duration_s": meta.get("duration_s"),
        "walking_s": summary.get("walking_s"),
        "distance_m": summary.get("distance_m"),
        "steps_accepted": summary.get("steps_accepted"),
        "conditions": len(blocks),
        "speeds": ", ".join(f"{s:g}" for s in speeds),
        "main_cadence": main["cadence_spm"]["median"] if main else None,
        "main_step_length": main["step_length_m"]["median"] if main else None,
        "main_stride_length": main["stride_length_m"]["median"] if main else None,
    }
