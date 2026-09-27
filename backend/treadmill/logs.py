"""Structured logging: JSON lines to a file, readable lines to the console, and a
live in-memory buffer the UI streams from.

Conventions (see docs/design.md, section 12):

* the logger name is ``treadmill.<component>``;
* every record carries a stable ``event`` identifier -- filters, tests and alerts
  key off it, never off the wording of the message;
* extra fields travel in ``fields`` and become top-level JSON keys;
* individual samples are never logged, and neither is anything identifying a patient.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import logging.handlers
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

COMPONENTS = (
    "usb", "decoder", "clock", "stream", "calibration", "gait", "ble", "session", "storage", "api", "ui",
)

def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"treadmill.{component}")


def log_event(
    logger: logging.Logger, level: int, event: str, msg: str, /, **fields: Any
) -> None:
    """Logs `msg` with a stable `event` id and structured `fields`."""
    logger.log(level, msg, extra={"event": event, "fields": fields})


def record_to_dict(record: logging.LogRecord) -> dict[str, Any]:
    component = record.name.removeprefix("treadmill.") if record.name.startswith("treadmill") else record.name
    out: dict[str, Any] = {
        "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(timespec="milliseconds"),
        "level": record.levelname.lower(),
        "component": component,
        "event": getattr(record, "event", f"{component}.message"),
        "msg": record.getMessage(),
    }
    fields = getattr(record, "fields", None)
    if isinstance(fields, dict):
        for key, value in fields.items():
            out.setdefault(key, value)
    if record.exc_info:
        out["traceback"] = logging.Formatter().formatException(record.exc_info)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_to_dict(record), default=str)


class ConsoleFormatter(logging.Formatter):
    """One readable line per record, for a developer's terminal."""

    COLOURS = {"DEBUG": "\033[37m", "INFO": "\033[36m", "WARNING": "\033[33m", "ERROR": "\033[31m"}

    def __init__(self, colour: bool) -> None:
        super().__init__()
        self._colour = colour

    def format(self, record: logging.LogRecord) -> str:
        d = record_to_dict(record)
        extras = " ".join(
            f"{k}={v}" for k, v in d.items()
            if k not in {"ts", "level", "component", "event", "msg", "traceback"}
        )
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}"
        level = record.levelname
        if self._colour:
            level = f"{self.COLOURS.get(level, '')}{level:<7}\033[0m"
        else:
            level = f"{level:<7}"
        line = f"{stamp} {level} {d['component']:<8} {d['event']:<28} {d['msg']}"
        if extras:
            line += f"  [{extras}]"
        if "traceback" in d:
            line += "\n" + d["traceback"]
        return line


class LiveBuffer(logging.Handler):
    """Keeps the last N records and pushes new ones to live subscribers (the UI)."""

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__(level=logging.DEBUG)
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = record_to_dict(record)
        except Exception:  # never let logging break the caller
            return
        with self._lock:
            self._records.append(entry)
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, entry)
            except RuntimeError:
                pass  # loop closed

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)[-limit:]

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = {s for s in self._subscribers if s[1] is not queue}


def _offer(queue: asyncio.Queue[dict[str, Any]], entry: dict[str, Any]) -> None:
    try:
        queue.put_nowait(entry)
    except asyncio.QueueFull:
        pass  # a slow viewer misses lines; the journal and file still have them


LIVE_BUFFER = LiveBuffer()


def setup_logging(log_dir: Path | None, level: int = logging.INFO, console: bool = True) -> None:
    """Configures the `treadmill` logger tree. Safe to call more than once."""
    root = logging.getLogger("treadmill")
    root.setLevel(logging.DEBUG)  # handlers and per-component levels decide
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)

    LIVE_BUFFER.setLevel(logging.DEBUG)
    root.addHandler(LIVE_BUFFER)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        # A terminal gets readable lines; systemd/journald gets one JSON object per line.
        tty = sys.stderr.isatty()
        stream.setFormatter(ConsoleFormatter(colour=True) if tty else JsonFormatter())
        stream.setLevel(logging.DEBUG)
        root.addHandler(stream)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "treadmill.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)

    for component in COMPONENTS:
        get_logger(component).setLevel(level)


def set_component_level(component: str, level_name: str) -> None:
    """Runtime verbosity change. Deliberately not persisted: a restart restores INFO."""
    if component not in COMPONENTS:
        raise ValueError(f"unknown component {component!r}")
    level = logging.getLevelName(level_name.upper())
    if not isinstance(level, int):
        raise ValueError(f"unknown level {level_name!r}")
    get_logger(component).setLevel(level)


class WarningAggregator:
    """Collapses a repeating warning into one line per interval.

    The first occurrence is logged at once so a live tail sees it immediately;
    repeats are counted and summarised every `interval_s`.
    """

    def __init__(self, logger: logging.Logger, interval_s: float = 10.0) -> None:
        self._logger = logger
        self._interval = interval_s
        self._counts: dict[str, int] = {}
        self._last_fields: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, str] = {}
        self._seen: set[str] = set()
        self._last_flush = time.monotonic()

    def note(self, event: str, msg: str, **fields: Any) -> None:
        if event not in self._seen:
            self._seen.add(event)
            log_event(self._logger, logging.WARNING, event, msg, **fields)
            return
        self._counts[event] = self._counts.get(event, 0) + 1
        self._last_fields[event] = fields
        self._messages[event] = msg

    def flush(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if now - self._last_flush < self._interval:
            return
        self._last_flush = now
        for event, count in self._counts.items():
            if count:
                log_event(
                    self._logger, logging.WARNING, event,
                    f"{count} more in the last {self._interval:g} s: {self._messages[event]}",
                    count=count, **self._last_fields.get(event, {}),
                )
        self._counts.clear()
