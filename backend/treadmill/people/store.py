"""Patients and staff: the records the console keeps between sessions.

Until now a session stored whatever name was typed into a box. That is enough to
label one recording and useless for everything else — you cannot look a patient
up, see whether they improved, or know who ran the session.

This is the store that fixes it. SQLite, on the appliance, because the machine is
offline by design and a clinic's records should not depend on somebody's network
being up.

**Everything here is patient-identifying data.** The file it writes is the reason
full-disk encryption stops being optional: anyone who walks off with the drive
can read it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Roles. A therapist runs sessions; a technician also holds calibration and
#: settings, because a mis-set coefficient makes every weight the machine ever
#: reports wrong, and that should not be one tap away from a clinical screen.
ROLE_THERAPIST = "therapist"
ROLE_TECHNICIAN = "technician"
ROLES = (ROLE_THERAPIST, ROLE_TECHNICIAN)

#: A PIN is for attribution and to stop casual misuse, not to withstand an
#: attacker with the disk in their hand. Short enough to tap between patients.
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8
#: Wrong attempts before a staff member is locked out, and for how long. Slows a
#: guesser to a crawl without locking a clinic out of its own machine for long.
MAX_ATTEMPTS = 5
LOCKOUT_S = 120


@dataclass(frozen=True, slots=True)
class Patient:
    id: str
    name: str
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    diagnosis: str = ""
    therapist_id: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    #: Filled in on the way out for the patient list; never stored.
    session_count: int = 0
    last_session_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Staff:
    id: str
    name: str
    role: str = ROLE_THERAPIST
    created_at: str = ""
    #: Never leaves the store.
    _pin_hash: bytes = field(default=b"", repr=False)
    _pin_salt: bytes = field(default=b"", repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "role": self.role,
                "created_at": self.created_at}


class PeopleError(ValueError):
    """Something the operator asked for cannot be done, with a reason to show."""


def _hash_pin(pin: str, salt: bytes) -> bytes:
    # scrypt is memory-hard and in the standard library, so this needs no
    # dependency the appliance would otherwise not carry.
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class PeopleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        #: Failed PIN attempts, in memory only: a restart is not a way in,
        #: because the lockout is short enough that waiting is easier anyway.
        self._attempts: dict[str, list[float]] = {}
        with self._connect() as db:
            db.executescript(SCHEMA)

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

    # ---- patients ---------------------------------------------------------

    def next_patient_id(self) -> str:
        """PT-0001 upwards. Short enough to read out over a phone."""
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM patients WHERE id LIKE 'PT-%' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return "PT-0001"
        try:
            return f"PT-{int(str(row['id']).split('-')[1]) + 1:04d}"
        except (IndexError, ValueError):
            return f"PT-{secrets.randbelow(9000) + 1000}"

    def add_patient(self, **fields: Any) -> Patient:
        name = str(fields.get("name", "")).strip()
        if not name:
            raise PeopleError("A patient needs a name.")
        patient_id = str(fields.get("id") or "").strip() or self.next_patient_id()
        now = _now()
        patient = Patient(
            id=patient_id,
            name=name,
            age=fields.get("age"),
            height_cm=fields.get("height_cm"),
            weight_kg=fields.get("weight_kg"),
            diagnosis=str(fields.get("diagnosis", "")),
            therapist_id=str(fields.get("therapist_id", "")),
            notes=str(fields.get("notes", "")),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as db:
            if db.execute("SELECT 1 FROM patients WHERE id = ?", (patient.id,)).fetchone():
                raise PeopleError(f"Patient {patient.id} already exists.")
            db.execute(
                "INSERT INTO patients (id, name, age, height_cm, weight_kg, diagnosis,"
                " therapist_id, notes, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (patient.id, patient.name, patient.age, patient.height_cm, patient.weight_kg,
                 patient.diagnosis, patient.therapist_id, patient.notes,
                 patient.created_at, patient.updated_at),
            )
        return patient

    def update_patient(self, patient_id: str, **fields: Any) -> Patient:
        existing = self.patient(patient_id)
        if existing is None:
            raise PeopleError(f"No patient {patient_id}.")
        allowed = ("name", "age", "height_cm", "weight_kg", "diagnosis", "therapist_id", "notes")
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not changes:
            return existing
        sets = ", ".join(f"{k} = ?" for k in changes)
        with self._connect() as db:
            db.execute(f"UPDATE patients SET {sets}, updated_at = ? WHERE id = ?",
                       (*changes.values(), _now(), patient_id))
        found = self.patient(patient_id)
        assert found is not None
        return found

    def patient(self, patient_id: str) -> Patient | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return _patient_from(row) if row else None

    def search_patients(self, query: str = "", limit: int = 50) -> list[Patient]:
        """By name or id. The therapist has a name in their head, not an id."""
        like = f"%{query.strip()}%"
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM patients WHERE (? = '' OR name LIKE ? COLLATE NOCASE"
                " OR id LIKE ? COLLATE NOCASE) ORDER BY updated_at DESC LIMIT ?",
                (query.strip(), like, like, limit),
            ).fetchall()
        return [_patient_from(r) for r in rows]

    def recent_patients(self, limit: int = 8) -> list[Patient]:
        """What the home screen shows: who was here lately, most recent first."""
        return self.search_patients("", limit)

    # ---- staff ------------------------------------------------------------

    def add_staff(self, name: str, pin: str, role: str = ROLE_THERAPIST) -> Staff:
        name = name.strip()
        if not name:
            raise PeopleError("A staff member needs a name.")
        if role not in ROLES:
            raise PeopleError(f"Role must be one of {', '.join(ROLES)}.")
        _check_pin(pin)
        staff_id = secrets.token_hex(8)
        salt = secrets.token_bytes(16)
        with self._connect() as db:
            db.execute(
                "INSERT INTO staff (id, name, role, pin_hash, pin_salt, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (staff_id, name, role, _hash_pin(pin, salt), salt, _now()),
            )
        return Staff(staff_id, name, role, _now())

    def set_pin(self, staff_id: str, pin: str) -> None:
        _check_pin(pin)
        salt = secrets.token_bytes(16)
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM staff WHERE id = ?", (staff_id,)).fetchone():
                raise PeopleError("No such staff member.")
            db.execute("UPDATE staff SET pin_hash = ?, pin_salt = ? WHERE id = ?",
                       (_hash_pin(pin, salt), salt, staff_id))
        self._attempts.pop(staff_id, None)

    def set_role(self, staff_id: str, role: str) -> Staff:
        """Promote a therapist, or step a technician back down.

        Somebody is hired, somebody is trained up, somebody moves on. Without
        this the only way to change a role is to delete the person and add them
        again under a new id, which quietly detaches them from every session
        they ever ran.
        """
        if role not in ROLES:
            raise PeopleError(f"Role must be one of {', '.join(ROLES)}.")
        with self._connect() as db:
            row = db.execute("SELECT id, name, role, created_at FROM staff WHERE id = ?",
                             (staff_id,)).fetchone()
            if row is None:
                raise PeopleError("No such staff member.")
            if row["role"] == ROLE_TECHNICIAN and role != ROLE_TECHNICIAN:
                others = db.execute(
                    "SELECT COUNT(*) AS n FROM staff WHERE role = ? AND id != ?",
                    (ROLE_TECHNICIAN, staff_id),
                ).fetchone()["n"]
                # Same trap as removing the last technician: nobody left who can
                # calibrate the machine or hand the role back.
                if others == 0:
                    raise PeopleError("This is the only technician. Promote somebody else first.")
            db.execute("UPDATE staff SET role = ? WHERE id = ?", (role, staff_id))
        return Staff(row["id"], row["name"], role, row["created_at"])

    def remove_staff(self, staff_id: str) -> None:
        with self._connect() as db:
            remaining = db.execute(
                "SELECT COUNT(*) AS n FROM staff WHERE role = ? AND id != ?",
                (ROLE_TECHNICIAN, staff_id),
            ).fetchone()["n"]
            row = db.execute("SELECT role FROM staff WHERE id = ?", (staff_id,)).fetchone()
            if row is None:
                raise PeopleError("No such staff member.")
            # Removing the last technician would leave nobody able to calibrate
            # the machine or add anyone back — a clinic locked out of its own
            # appliance, fixable only by editing the database by hand.
            if row["role"] == ROLE_TECHNICIAN and remaining == 0:
                raise PeopleError("This is the only technician. Add another one first.")
            db.execute("DELETE FROM staff WHERE id = ?", (staff_id,))

    def staff(self) -> list[Staff]:
        """Everyone, for the lock screen. Names only — no secrets leave here."""
        with self._connect() as db:
            rows = db.execute("SELECT id, name, role, created_at FROM staff ORDER BY name").fetchall()
        return [Staff(r["id"], r["name"], r["role"], r["created_at"]) for r in rows]

    def staff_member(self, staff_id: str) -> Staff | None:
        with self._connect() as db:
            row = db.execute("SELECT id, name, role, created_at FROM staff WHERE id = ?",
                             (staff_id,)).fetchone()
        return Staff(row["id"], row["name"], row["role"], row["created_at"]) if row else None

    # ---- signing in -------------------------------------------------------

    def locked_out_for(self, staff_id: str) -> float:
        """Seconds remaining on a lockout, or 0."""
        recent = [t for t in self._attempts.get(staff_id, []) if time.monotonic() - t < LOCKOUT_S]
        self._attempts[staff_id] = recent
        if len(recent) < MAX_ATTEMPTS:
            return 0.0
        return max(0.0, LOCKOUT_S - (time.monotonic() - recent[0]))

    def check_pin(self, staff_id: str, pin: str) -> Staff:
        """Returns the staff member, or raises with something worth showing."""
        wait = self.locked_out_for(staff_id)
        if wait > 0:
            raise PeopleError(f"Too many wrong PINs. Try again in {int(wait) + 1} seconds.")
        with self._connect() as db:
            row = db.execute("SELECT * FROM staff WHERE id = ?", (staff_id,)).fetchone()
        if row is None:
            raise PeopleError("No such staff member.")
        # compare_digest, not ==: a plain comparison returns faster on an early
        # mismatch, which leaks how much of the guess was right.
        if not hmac.compare_digest(_hash_pin(pin, row["pin_salt"]), row["pin_hash"]):
            self._attempts.setdefault(staff_id, []).append(time.monotonic())
            left = MAX_ATTEMPTS - len(self._attempts[staff_id])
            raise PeopleError(
                "That PIN is not right." + (f" {left} attempts left." if 0 < left <= 2 else "")
            )
        self._attempts.pop(staff_id, None)
        return Staff(row["id"], row["name"], row["role"], row["created_at"])

    def count(self) -> tuple[int, int]:
        with self._connect() as db:
            p = db.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]
            s = db.execute("SELECT COUNT(*) AS n FROM staff").fetchone()["n"]
        return int(p), int(s)


def _check_pin(pin: str) -> None:
    if not pin.isdigit():
        raise PeopleError("A PIN is digits only.")
    if not MIN_PIN_LENGTH <= len(pin) <= MAX_PIN_LENGTH:
        raise PeopleError(f"A PIN is {MIN_PIN_LENGTH} to {MAX_PIN_LENGTH} digits.")
    if len(set(pin)) == 1:
        raise PeopleError("That PIN is too easy to guess.")


def _patient_from(row: sqlite3.Row) -> Patient:
    return Patient(
        id=row["id"], name=row["name"], age=row["age"], height_cm=row["height_cm"],
        weight_kg=row["weight_kg"], diagnosis=row["diagnosis"],
        therapist_id=row["therapist_id"], notes=row["notes"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    age          INTEGER,
    height_cm    REAL,
    weight_kg    REAL,
    diagnosis    TEXT DEFAULT '',
    therapist_id TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    created_at   TEXT,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS patients_by_name ON patients (name);
CREATE INDEX IF NOT EXISTS patients_by_updated ON patients (updated_at DESC);

CREATE TABLE IF NOT EXISTS staff (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL,
    pin_hash   BLOB NOT NULL,
    pin_salt   BLOB NOT NULL,
    created_at TEXT
);
"""
