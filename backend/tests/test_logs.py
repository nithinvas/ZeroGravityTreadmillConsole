from __future__ import annotations

import json
import logging

import pytest

from treadmill.logs import (
    JsonFormatter,
    WarningAggregator,
    get_logger,
    log_event,
    set_component_level,
    setup_logging,
)


def make_record(logger: logging.Logger, **fields: object) -> logging.LogRecord:
    return logger.makeRecord(logger.name, logging.WARNING, __file__, 1, "37 short transfers",
                             None, None, extra={"event": "usb.short_transfer", "fields": fields})


def test_json_lines_carry_component_event_and_fields() -> None:
    line = JsonFormatter().format(make_record(get_logger("usb"), count_10s=37, segment=2))
    entry = json.loads(line)

    assert entry["component"] == "usb"
    assert entry["event"] == "usb.short_transfer"
    assert entry["level"] == "warning"
    assert entry["count_10s"] == 37 and entry["segment"] == 2


def test_repeating_warning_collapses_to_one_line_per_interval(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("decoder")
    logger.propagate = True
    aggregator = WarningAggregator(logger, interval_s=10)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        for _ in range(1000):
            aggregator.note("decoder.short_transfer", "Discarded a 3-byte transfer", length=3)
        aggregator.flush(now=1e12)
    logger.propagate = False

    events = [r for r in caplog.records if getattr(r, "event", "") == "decoder.short_transfer"]
    assert len(events) == 2  # the first occurrence at once, then one summary
    assert events[1].fields["count"] == 999  # type: ignore[attr-defined]


def test_runtime_level_change_and_restart_default(tmp_path: object) -> None:
    setup_logging(None, console=False)
    set_component_level("gait", "debug")
    assert get_logger("gait").level == logging.DEBUG

    setup_logging(None, console=False)  # what a restart does
    assert get_logger("gait").level == logging.INFO


def test_rejects_unknown_component_or_level() -> None:
    with pytest.raises(ValueError):
        set_component_level("nope", "debug")
    with pytest.raises(ValueError):
        set_component_level("usb", "loud")


def test_log_event_helper_sets_event() -> None:
    record_holder: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            record_holder.append(record)

    logger = get_logger("api")
    logger.setLevel(logging.INFO)
    handler = Grab()
    logger.addHandler(handler)
    try:
        log_event(logger, logging.INFO, "api.test", "hello", x=1)
    finally:
        logger.removeHandler(handler)
    assert record_holder[0].event == "api.test"  # type: ignore[attr-defined]
