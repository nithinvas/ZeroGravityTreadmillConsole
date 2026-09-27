"""The calibration in use, the default coefficients file, and every previous calibration.

    <data>/calibration/
        defaults.json      the default coefficients: read at every start, never hardcoded
        active.json        the calibration every calculation uses
        history/           every calibration ever saved

`active.json` either holds its own values, or -- method "defaults" -- says "use the
defaults file". In that case the values are re-read from `defaults.json` each time
the server starts, so changing the defaults file changes every calculation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

from trendmill.calibration.profile import CalibrationProfile, Method
from trendmill.logs import get_logger, log_event

log = get_logger("calibration")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # a crash never leaves half a file


class CalibrationStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "history").mkdir(exist_ok=True)
        self.active_path = self.directory / "active.json"
        self.defaults_path = self.directory / "defaults.json"

    # ---- default coefficients ----------------------------------------------

    def load_defaults(self) -> CalibrationProfile | None:
        """The defaults file as a profile, or None when absent or unreadable."""
        if not self.defaults_path.exists():
            return None
        try:
            data = json.loads(self.defaults_path.read_text(encoding="utf-8"))
            return CalibrationProfile.from_dict(data | {"method": Method.DEFAULTS})
        except (OSError, ValueError, KeyError, TypeError) as error:
            log_event(log, logging.ERROR, "calibration.defaults_unreadable",
                      f"Default coefficients file is unreadable and was ignored: {error}",
                      path=str(self.defaults_path))
            return None

    def save_defaults(self, profile: CalibrationProfile, note: str = "") -> CalibrationProfile:
        data: dict[str, Any] = {
            "zeros": list(profile.zeros),
            "counts_per_kg": list(profile.counts_per_kg),
            "firmware_bcd": profile.firmware_bcd,
            "saved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "note": note or profile.note,
        }
        _write_atomic(self.defaults_path, json.dumps(data, indent=2))
        log_event(log, logging.INFO, "calibration.defaults_saved",
                  f"Default coefficients written to {self.defaults_path}",
                  zeros=data["zeros"], counts_per_kg=data["counts_per_kg"])
        loaded = self.load_defaults()
        assert loaded is not None
        return loaded

    def defaults_info(self) -> dict[str, Any]:
        profile = self.load_defaults()
        if profile is None:
            return {"present": False, "path": str(self.defaults_path)}
        raw: dict[str, Any] = json.loads(self.defaults_path.read_text(encoding="utf-8"))
        return {"present": True, "path": str(self.defaults_path),
                "zeros": list(profile.zeros), "counts_per_kg": list(profile.counts_per_kg),
                "firmware_bcd": profile.firmware_bcd, "saved_at": raw.get("saved_at"),
                "note": profile.note}

    # ---- the calibration in use --------------------------------------------

    def load(self) -> CalibrationProfile | None:
        """The calibration to use. A "defaults" selection is resolved from the defaults file."""
        if not self.active_path.exists():
            return None
        try:
            stored = CalibrationProfile.from_dict(json.loads(self.active_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as error:
            log_event(log, logging.ERROR, "calibration.load_failed",
                      f"Stored calibration is unreadable and was ignored: {error}")
            return None
        if stored.method != Method.DEFAULTS:
            return stored
        defaults = self.load_defaults()
        if defaults is None:
            log_event(log, logging.WARNING, "calibration.defaults_missing",
                      "Default coefficients are selected but the defaults file is missing; "
                      "using the copy saved when they were selected", path=str(self.defaults_path))
            return stored
        return defaults

    def save(self, profile: CalibrationProfile) -> None:
        text = json.dumps(profile.to_dict(), indent=2)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (self.directory / "history" / f"{stamp}.json").write_text(text, encoding="utf-8")
        _write_atomic(self.active_path, text)
        log_event(log, logging.INFO, "calibration.saved",
                  f"Calibration in use: {profile.method}", method=profile.method,
                  zeros=list(profile.zeros), counts_per_kg=list(profile.counts_per_kg),
                  firmware_bcd=profile.firmware_bcd)

    def clear(self) -> None:
        if self.active_path.exists():
            self.active_path.unlink()
            log_event(log, logging.INFO, "calibration.cleared", "Calibration cleared")

    def history(self, limit: int = 20) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for path in sorted((self.directory / "history").glob("*.json"), reverse=True)[:limit]:
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out
