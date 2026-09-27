"""The raw recording format: every USB transfer, untouched, with its arrival time.

Storing the transfer bytes rather than decoded values means replay exercises the
real decoder, and a decoder bug found later can be fixed and re-run over every
past recording.

File layout (little-endian)::

    header, 32 bytes:  magic "TMRAW1\\0\\0" | version u16 | vid u16 | pid u16 |
                       bcd_device u16 | nominal_rate_hz f64 | created_unix_ns i64
    record, repeated:  arrival_ns u64 | length u16 | `length` transfer bytes

A normal record is 74 bytes. Files are flushed and fsync'd every second, so a
power cut loses at most the last second; a truncated final record is ignored on
read.
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

MAGIC = b"TMRAW1\x00\x00"
VERSION = 1
HEADER = struct.Struct("<8sHHHHdq")
RECORD = struct.Struct("<QH")
FSYNC_INTERVAL_S = 1.0


@dataclass(frozen=True)
class RawHeader:
    version: int
    vid: int
    pid: int
    bcd_device: int
    nominal_rate_hz: float
    created_unix_ns: int


class RawWriter:
    def __init__(self, path: Path, header: RawHeader) -> None:
        self.path = path
        self._file: BinaryIO = open(path, "wb")  # noqa: SIM115 - closed in close()
        self._file.write(HEADER.pack(MAGIC, header.version, header.vid, header.pid,
                                     header.bcd_device, header.nominal_rate_hz,
                                     header.created_unix_ns))
        self._last_sync = time.monotonic()
        self.records = 0
        self.bytes = HEADER.size

    def write(self, arrival_ns: int, data: bytes) -> None:
        self._file.write(RECORD.pack(arrival_ns, len(data)))
        self._file.write(data)
        self.records += 1
        self.bytes += RECORD.size + len(data)
        now = time.monotonic()
        if now - self._last_sync >= FSYNC_INTERVAL_S:
            self.sync()
            self._last_sync = now

    def sync(self) -> None:
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> str:
        """Closes the file and returns its SHA-256, also written beside it."""
        self.sync()
        self._file.close()
        digest = sha256_of(self.path)
        self.path.with_suffix(self.path.suffix + ".sha256").write_text(
            f"{digest}  {self.path.name}\n", encoding="utf-8"
        )
        return digest


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_header(f: BinaryIO) -> RawHeader:
    raw = f.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise ValueError("file too short for a TMRAW header")
    magic, version, vid, pid, bcd, rate, created = HEADER.unpack(raw)
    if magic != MAGIC:
        raise ValueError("not a TMRAW file")
    if version != VERSION:
        raise ValueError(f"unsupported TMRAW version {version}")
    return RawHeader(version, vid, pid, bcd, rate, created)


def iter_records(path: Path) -> Iterator[tuple[int, bytes]]:
    """Yields (arrival_ns, transfer bytes); stops quietly at a truncated final record."""
    with open(path, "rb") as f:
        read_header(f)
        while True:
            head = f.read(RECORD.size)
            if len(head) < RECORD.size:
                return
            arrival_ns, length = RECORD.unpack(head)
            data = f.read(length)
            if len(data) < length:
                return
            yield arrival_ns, data


def header_of(path: Path) -> RawHeader:
    with open(path, "rb") as f:
        return read_header(f)
