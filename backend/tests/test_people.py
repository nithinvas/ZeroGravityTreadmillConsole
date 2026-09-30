"""Patients and staff.

Most of what matters here is refusal and privacy: a store that holds patient
records has to be careful about what it hands out and who it lets in.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from treadmill.people.store import (
    MAX_ATTEMPTS,
    ROLE_TECHNICIAN,
    ROLE_THERAPIST,
    PeopleError,
    PeopleStore,
)


@pytest.fixture
def store(tmp_path: Path) -> PeopleStore:
    return PeopleStore(tmp_path / "people.sqlite")


# ---- patients ----------------------------------------------------------------


def test_patients_get_a_readable_id(store: PeopleStore) -> None:
    # Short enough for a therapist to read out over a phone.
    first = store.add_patient(name="Asha Rao")
    second = store.add_patient(name="Ravi Kumar")
    assert first.id == "PT-0001"
    assert second.id == "PT-0002"


def test_a_patient_needs_a_name(store: PeopleStore) -> None:
    with pytest.raises(PeopleError, match="needs a name"):
        store.add_patient(name="   ")


def test_a_patient_is_found_by_name_or_id(store: PeopleStore) -> None:
    store.add_patient(name="Asha Rao", diagnosis="Neurological Rehab")
    store.add_patient(name="Ravi Kumar")

    assert [p.name for p in store.search_patients("asha")] == ["Asha Rao"]
    assert [p.name for p in store.search_patients("PT-0002")] == ["Ravi Kumar"]
    assert len(store.search_patients("")) == 2


def test_a_patient_survives_being_edited(store: PeopleStore) -> None:
    p = store.add_patient(name="Asha Rao", weight_kg=58.0)
    updated = store.update_patient(p.id, weight_kg=59.5, diagnosis="Hip Fracture Recovery")
    assert updated.weight_kg == 59.5
    assert updated.diagnosis == "Hip Fracture Recovery"
    assert updated.name == "Asha Rao"       # untouched fields stay
    assert updated.created_at == p.created_at


def test_two_patients_cannot_share_an_id(store: PeopleStore) -> None:
    store.add_patient(name="Asha Rao", id="PT-0001")
    with pytest.raises(PeopleError, match="already exists"):
        store.add_patient(name="Someone Else", id="PT-0001")


def test_the_home_screen_shows_the_most_recent_first(store: PeopleStore) -> None:
    store.add_patient(name="First")
    time.sleep(1.01)                          # created_at has second resolution
    store.add_patient(name="Second")
    assert [p.name for p in store.recent_patients()][0] == "Second"


# ---- staff and signing in ----------------------------------------------------


def test_the_lock_screen_never_sees_a_pin(store: PeopleStore) -> None:
    store.add_staff("Dr. Patel", "4417")
    listed = store.staff()[0].as_dict()
    assert set(listed) == {"id", "name", "role", "created_at"}
    assert "pin" not in str(listed).lower()


def test_a_correct_pin_signs_you_in(store: PeopleStore) -> None:
    added = store.add_staff("Dr. Patel", "4417")
    who = store.check_pin(added.id, "4417")
    assert who.name == "Dr. Patel"
    assert who.role == ROLE_THERAPIST


def test_a_wrong_pin_does_not(store: PeopleStore) -> None:
    added = store.add_staff("Dr. Patel", "4417")
    with pytest.raises(PeopleError, match="not right"):
        store.check_pin(added.id, "1234")


@pytest.mark.parametrize("bad,why", [
    ("12", "4 to 8"), ("123456789", "4 to 8"), ("abcd", "digits only"), ("1111", "too easy"),
])
def test_a_weak_pin_is_refused(store: PeopleStore, bad: str, why: str) -> None:
    with pytest.raises(PeopleError, match=why):
        store.add_staff("Dr. Patel", bad)


def test_guessing_gets_locked_out(store: PeopleStore) -> None:
    added = store.add_staff("Dr. Patel", "4417")
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(PeopleError):
            store.check_pin(added.id, "0000")
    # Even the right PIN waits: otherwise the lockout is no obstacle at all.
    with pytest.raises(PeopleError, match="Too many wrong PINs"):
        store.check_pin(added.id, "4417")
    assert store.locked_out_for(added.id) > 0


def test_changing_a_pin_clears_the_lockout(store: PeopleStore) -> None:
    added = store.add_staff("Dr. Patel", "4417")
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(PeopleError):
            store.check_pin(added.id, "0000")
    store.set_pin(added.id, "8891")
    assert store.check_pin(added.id, "8891").name == "Dr. Patel"


def test_the_last_technician_cannot_be_removed(store: PeopleStore) -> None:
    # Removing them leaves nobody able to calibrate the machine or add anyone
    # back: a clinic locked out of its own appliance.
    tech = store.add_staff("Tech", "9921", ROLE_TECHNICIAN)
    store.add_staff("Dr. Patel", "4417")
    with pytest.raises(PeopleError, match="only technician"):
        store.remove_staff(tech.id)

    second = store.add_staff("Tech Two", "7733", ROLE_TECHNICIAN)
    store.remove_staff(tech.id)
    assert [s.id for s in store.staff() if s.role == ROLE_TECHNICIAN] == [second.id]


def test_the_store_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "people.sqlite"
    first = PeopleStore(path)
    p = first.add_patient(name="Asha Rao", weight_kg=58.0)
    s = first.add_staff("Dr. Patel", "4417")

    reopened = PeopleStore(path)
    assert reopened.patient(p.id) is not None
    assert reopened.check_pin(s.id, "4417").name == "Dr. Patel"
    assert reopened.count() == (1, 1)


# ---- through the API ---------------------------------------------------------


def test_patients_and_sign_in_through_the_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from treadmill.api.app import create_app
    from treadmill.device.simulator import SimulatedBoard
    from treadmill.logs import setup_logging
    from treadmill.service import Console, ConsoleConfig

    setup_logging(None, console=False)
    console = Console(SimulatedBoard(rate_hz=500.0), ConsoleConfig(tmp_path, 500.0))
    with TestClient(create_app(console)) as c:
        # A clinic starts empty: the lock screen has nobody on it.
        assert c.get("/api/staff").json() == []

        staff = c.post("/api/staff", json={"name": "Dr. Patel", "pin": "4417"}).json()
        assert "pin" not in staff and "pin_hash" not in staff

        assert c.post("/api/sign-in", json={"staff_id": staff["id"], "pin": "0000"}).status_code == 401
        signed = c.post("/api/sign-in", json={"staff_id": staff["id"], "pin": "4417"})
        assert signed.status_code == 200
        assert signed.json()["name"] == "Dr. Patel"

        made = c.post("/api/patients", json={
            "name": "Asha Rao", "age": 45, "height_cm": 158, "weight_kg": 58,
            "diagnosis": "Neurological Rehab", "therapist_id": staff["id"],
        }).json()
        assert made["id"] == "PT-0001"

        assert [p["name"] for p in c.get("/api/patients", params={"q": "asha"}).json()] == ["Asha Rao"]
        assert c.get("/api/patients/recent").json()[0]["id"] == "PT-0001"

        full = c.get(f"/api/patients/{made['id']}").json()
        assert full["name"] == "Asha Rao"
        assert full["sessions"] == []          # nothing recorded for them yet

        edited = c.patch(f"/api/patients/{made['id']}", json={"weight_kg": 59.5})
        assert edited.json()["weight_kg"] == 59.5
        assert edited.json()["name"] == "Asha Rao"

        assert c.get("/api/patients/PT-9999").status_code == 404
        assert c.post("/api/staff", json={"name": "X", "pin": "1111"}).status_code == 400


def test_staff_can_be_onboarded_and_removed_through_the_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from treadmill.api.app import create_app
    from treadmill.device.simulator import SimulatedBoard
    from treadmill.logs import setup_logging
    from treadmill.service import Console, ConsoleConfig

    setup_logging(None, console=False)
    console = Console(SimulatedBoard(rate_hz=500.0), ConsoleConfig(tmp_path, 500.0))
    with TestClient(create_app(console)) as c:
        tech = c.post("/api/staff", json={"name": "Tech", "pin": "9921",
                                          "role": "technician"}).json()
        new = c.post("/api/staff", json={"name": "Dr. Mehta", "pin": "3355"}).json()
        assert {s["name"] for s in c.get("/api/staff").json()} == {"Tech", "Dr. Mehta"}

        # A forgotten PIN is reset, not recovered: nothing stores the old one.
        assert c.post(f"/api/staff/{new['id']}/pin", json={"pin": "8080"}).status_code == 200
        assert c.post("/api/sign-in", json={"staff_id": new["id"], "pin": "3355"}).status_code == 401
        assert c.post("/api/sign-in", json={"staff_id": new["id"], "pin": "8080"}).status_code == 200
        assert c.post(f"/api/staff/{new['id']}/pin", json={"pin": "1111"}).status_code == 400

        assert c.delete(f"/api/staff/{new['id']}").status_code == 200
        # The last technician stays: removing them locks the clinic out of its
        # own machine, with no way back that does not involve a database editor.
        refused = c.delete(f"/api/staff/{tech['id']}")
        assert refused.status_code == 409
        assert "only technician" in refused.json()["detail"]


def test_role_can_be_changed_without_losing_the_person(tmp_path):
    store = PeopleStore(tmp_path / "p.db")
    boss = store.add_staff("Dr. Patel", "4417", "technician")
    junior = store.add_staff("Dr. Rao", "5528")
    promoted = store.set_role(junior.id, "technician")
    assert promoted.id == junior.id
    assert promoted.role == "technician"
    assert store.staff_member(junior.id).role == "technician"
    # And back down again, now that somebody else holds the role.
    assert store.set_role(boss.id, "therapist").role == "therapist"


def test_the_last_technician_cannot_demote_themselves(tmp_path):
    store = PeopleStore(tmp_path / "p.db")
    only = store.add_staff("Dr. Patel", "4417", "technician")
    store.add_staff("Dr. Rao", "5528")
    with pytest.raises(PeopleError):
        store.set_role(only.id, "therapist")
    assert store.staff_member(only.id).role == "technician"


def test_role_must_be_a_known_one(tmp_path):
    store = PeopleStore(tmp_path / "p.db")
    who = store.add_staff("Dr. Patel", "4417", "technician")
    with pytest.raises(PeopleError):
        store.set_role(who.id, "admin")


def test_role_change_through_the_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from treadmill.api.app import create_app
    from treadmill.device.simulator import SimulatedBoard
    from treadmill.logs import setup_logging
    from treadmill.service import Console, ConsoleConfig

    setup_logging(None, console=False)
    console = Console(SimulatedBoard(rate_hz=500.0), ConsoleConfig(tmp_path, 500.0))
    with TestClient(create_app(console)) as c:
        boss = c.post("/api/staff", json={
            "name": "Dr. Patel", "pin": "4417", "role": "technician"}).json()
        junior = c.post("/api/staff", json={"name": "Dr. Rao", "pin": "5528"}).json()

        promoted = c.post(f"/api/staff/{junior['id']}/role", json={"role": "technician"})
        assert promoted.status_code == 200
        assert promoted.json() == junior | {"role": "technician"}

        # Now that there are two, stepping the first one down is allowed.
        assert c.post(f"/api/staff/{boss['id']}/role", json={"role": "therapist"}).status_code == 200
        # But the survivor is stuck with it.
        stuck = c.post(f"/api/staff/{junior['id']}/role", json={"role": "therapist"})
        assert stuck.status_code == 409

        assert c.post(f"/api/staff/{junior['id']}/role", json={"role": "admin"}).status_code == 409
        assert c.post("/api/staff/nobody/role", json={"role": "therapist"}).status_code == 409
