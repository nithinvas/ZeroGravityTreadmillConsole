"""How this appliance opens, versions and copies its SQLite files.

SQLite is the right store for a machine that must work in a clinic with no
network: there is no server process to fail to start, one writer, kilobytes of
patient data, and a backup is a file copy -- which matters when support means
somebody plugging in a USB stick. What it does need is the three things a
default `sqlite3.connect` does not give you.

**Write-ahead logging.** The console is killed by a power cut, not by a clean
shutdown. WAL survives that better than the default rollback journal and lets a
reader work while a write is in flight.

**A schema version.** `CREATE TABLE IF NOT EXISTS` is fine until the day a
column is added: a machine in the field then has the old schema and the new
code, and IF NOT EXISTS will not notice. Every database here carries its version
in `PRAGMA user_version` and is brought forward one step at a time. Retrofitting
this onto machines that already hold patient records is painful, which is why it
is here before there are many.

**A copy.** Taking `cp` to a live SQLite file can capture a torn write. The
online backup API takes a consistent snapshot of a database that is being
written to, which is the only kind this appliance has.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from treadmill.logs import get_logger, log_event

log = get_logger(__name__)

#: How long to wait for another connection's write before giving up. The console
#: is single-writer, so this only covers a backup running against a live file.
BUSY_TIMEOUT_MS = 5_000


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a database with the settings this appliance needs."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    # WAL is a property of the file, not the connection: setting it once sticks.
    db.execute("PRAGMA journal_mode = WAL")
    # NORMAL is the documented safe pairing with WAL -- durable across a process
    # crash, and across a power cut at the cost of the last transaction or two.
    # FULL would fsync every commit, which on this hardware costs more than the
    # loss it prevents for records written once per session.
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def migrate(db: sqlite3.Connection, steps: Sequence[tuple[int, str]], label: str) -> int:
    """Bring a database up to the latest schema, one numbered step at a time.

    `steps` is ordered `(version, sql)`. Step 1 must be safe to run against a
    database that already has the tables, because the machines already in the
    field have the schema but no version stamped on it.
    """
    current = int(db.execute("PRAGMA user_version").fetchone()[0])
    applied = 0
    for version, sql in sorted(steps):
        if version <= current:
            continue
        db.executescript(sql)
        # Not a bound parameter: SQLite does not allow one here. The value is an
        # int from this module's own table, never from input.
        db.execute(f"PRAGMA user_version = {int(version)}")
        db.commit()
        applied += 1
        log_event(log, logging.INFO, "db.migrated",
                  f"{label}: schema {current} -> {version}", store=label, version=version)
        current = version
    return applied


def version(db: sqlite3.Connection) -> int:
    return int(db.execute("PRAGMA user_version").fetchone()[0])


def backup(source: Path, directory: Path, keep: int = 14) -> Path | None:
    """Snapshot a live database, and keep the most recent `keep` copies.

    Returns the file written, or None when the source does not exist yet.
    """
    if not Path(source).exists():
        return None
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{Path(source).stem}-{stamp}.sqlite"

    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(target)
        try:
            # The online backup API: consistent even while the console writes.
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    old = sorted(directory.glob(f"{Path(source).stem}-*.sqlite"))
    for stale in old[:-keep] if len(old) > keep else []:
        stale.unlink(missing_ok=True)
    log_event(log, logging.INFO, "db.backed_up", f"Copied {Path(source).name}",
              source=str(source), target=str(target), kept=min(len(old), keep))
    return target


def backup_all(data_dir: Path, keep: int = 14) -> list[Path]:
    """Snapshot every database this appliance keeps."""
    out = []
    for name in ("people.db", "sessions/index.sqlite"):
        made = backup(data_dir / name, data_dir / "backups", keep=keep)
        if made:
            out.append(made)
    return out


def free_space_mb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e6
