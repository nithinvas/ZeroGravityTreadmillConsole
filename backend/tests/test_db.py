"""Opening, versioning and copying the appliance's SQLite files.

The failures these guard against are the quiet ones: a machine in the field
running new code against an old schema, and a backup that turns out to have
captured a half-written file.
"""

from __future__ import annotations

import sqlite3

import pytest

from treadmill import db


def test_a_new_database_gets_the_settings_this_appliance_needs(tmp_path):
    con = db.connect(tmp_path / "x.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS


def test_migrations_run_once_and_stamp_the_version(tmp_path):
    con = db.connect(tmp_path / "x.db")
    steps = [(1, "CREATE TABLE a (x INT);"), (2, "CREATE TABLE b (y INT);")]
    assert db.migrate(con, steps, "test") == 2
    assert db.version(con) == 2
    # Running again is a no-op, not an error.
    assert db.migrate(con, steps, "test") == 0


def test_a_later_step_is_applied_to_an_older_database(tmp_path):
    """The case that breaks CREATE TABLE IF NOT EXISTS: a new column."""
    path = tmp_path / "x.db"
    con = db.connect(path)
    db.migrate(con, [(1, "CREATE TABLE a (x INT);")], "test")
    con.execute("INSERT INTO a (x) VALUES (7)")
    con.commit()
    con.close()

    con = db.connect(path)
    db.migrate(con, [(1, "CREATE TABLE a (x INT);"),
                     (2, "ALTER TABLE a ADD COLUMN note TEXT;")], "test")
    assert db.version(con) == 2
    row = con.execute("SELECT x, note FROM a").fetchone()
    assert row["x"] == 7 and row["note"] is None     # existing data survives


def test_an_unversioned_database_from_the_field_is_adopted_not_broken(tmp_path):
    """Machines already shipped have the tables but no version stamp."""
    path = tmp_path / "x.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE a (x INT)")
    raw.execute("INSERT INTO a (x) VALUES (1)")
    raw.commit()
    raw.close()

    con = db.connect(path)
    assert db.version(con) == 0
    db.migrate(con, [(1, "CREATE TABLE IF NOT EXISTS a (x INT);")], "test")
    assert db.version(con) == 1
    assert con.execute("SELECT COUNT(*) FROM a").fetchone()[0] == 1


def test_a_backup_is_a_usable_copy(tmp_path):
    src = tmp_path / "people.db"
    con = db.connect(src)
    db.migrate(con, [(1, "CREATE TABLE patients (id TEXT, name TEXT);")], "test")
    con.execute("INSERT INTO patients VALUES ('PT-0001', 'Asha Rao')")
    con.commit()

    made = db.backup(src, tmp_path / "backups")
    assert made is not None and made.exists()

    copy = sqlite3.connect(made)
    copy.row_factory = sqlite3.Row
    assert copy.execute("SELECT name FROM patients").fetchone()["name"] == "Asha Rao"
    assert int(copy.execute("PRAGMA user_version").fetchone()[0]) == 1


def test_a_backup_is_taken_while_the_database_is_open_for_writing(tmp_path):
    """The only kind of database this appliance has."""
    src = tmp_path / "people.db"
    con = db.connect(src)
    db.migrate(con, [(1, "CREATE TABLE t (x INT);")], "test")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    made = db.backup(src, tmp_path / "backups")      # con still open
    assert made is not None
    assert sqlite3.connect(made).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_old_copies_are_rotated_away(tmp_path):
    src = tmp_path / "people.db"
    con = db.connect(src)
    db.migrate(con, [(1, "CREATE TABLE t (x INT);")], "test")
    for _ in range(6):
        db.backup(src, tmp_path / "backups", keep=3)
    assert len(list((tmp_path / "backups").glob("*.sqlite"))) <= 3


def test_backing_up_a_database_that_does_not_exist_yet_is_not_an_error(tmp_path):
    assert db.backup(tmp_path / "nothing.db", tmp_path / "backups") is None
    assert db.backup_all(tmp_path) == []
