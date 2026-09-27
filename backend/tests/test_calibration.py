"""Calibration maths, storage and live weighing.

The solver tests are ported from the mobile app's DeckCalibrationSolverTest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from treadmill.calibration import solver
from treadmill.calibration.profile import CalibrationProfile, Method
from treadmill.calibration.store import CalibrationStore
from treadmill.calibration.weighing import Weighing

TRUE_COUNTS_PER_KG = [-1_800.0, -1_900.0, -2_000.0, -2_100.0]
# The September session (earlier firmware): zeros, and the 1,856 counts/kg measured then.
SEPTEMBER_ZEROS = (-536_660.0, 101_508.0, 694_467.0, -19_659.0)
SEPTEMBER_COUNTS_PER_KG = (-1_856.0, -1_856.0, -1_856.0, -1_856.0)
CORNER_DISTRIBUTIONS = [
    [0.55, 0.20, 0.05, 0.20],
    [0.20, 0.55, 0.20, 0.05],
    [0.05, 0.20, 0.55, 0.20],
    [0.20, 0.05, 0.20, 0.55],
]


def deltas(distribution: list[float], weight_kg: float) -> list[float]:
    return [share * weight_kg * c for share, c in zip(distribution, TRUE_COUNTS_PER_KG, strict=True)]


# ---- solver (ported) ------------------------------------------------------


def test_recovers_each_cells_coefficient_from_four_spread_positions() -> None:
    result = solver.solve([deltas(d, 20.0) for d in CORNER_DISTRIBUTIONS], 20.0)

    assert result is not None and result.kind == "per_cell"
    for got, want in zip(result.counts_per_kg, TRUE_COUNTS_PER_KG, strict=True):
        assert got == pytest.approx(want, abs=1.0)


def test_solved_calibration_reads_correctly_where_the_weight_was_never_placed() -> None:
    result = solver.solve([deltas(d, 20.0) for d in CORNER_DISTRIBUTIONS], 20.0)
    assert result is not None
    untested = deltas([0.31, 0.24, 0.17, 0.28], 73.0)

    measured = sum(d / c for d, c in zip(untested, result.counts_per_kg, strict=True))
    assert measured == pytest.approx(73.0, abs=0.05)


def test_crediting_each_corner_with_the_whole_weight_overstates_the_load() -> None:
    # The mobile app's original method, kept so the failure stays visible.
    per_corner = [20.0 / deltas(d, 20.0)[i] for i, d in enumerate(CORNER_DISTRIBUTIONS)]
    measured = sum(d * k for d, k in zip(deltas([0.31, 0.24, 0.17, 0.28], 20.0), per_corner, strict=True))

    assert measured > 30.0  # a 20 kg reference reads as nearly 40 kg


def test_falls_back_to_shared_rather_than_inventing_four_answers() -> None:
    identical = [deltas(CORNER_DISTRIBUTIONS[0], 20.0)] * 4

    assert solver.per_cell_kg_per_count(identical, 20.0) is None
    result = solver.solve(identical, 20.0)
    assert result is not None and result.kind == "shared"


def test_shared_coefficient_ignores_position_when_cells_match() -> None:
    for d in CORNER_DISTRIBUTIONS:
        row = [share * 58.0 * -1_856.0 for share in d]
        result = solver.solve([row], 58.0)
        assert result is not None
        assert result.counts_per_kg[0] == pytest.approx(-1_856.0, abs=0.01)


def test_matches_the_measured_58_kg_capture_from_the_treadmill() -> None:
    result = solver.solve([[-25_130.0, -25_857.0, -1_750.0, -54_887.0]], 58.0)

    assert result is not None
    assert result.counts_per_kg[0] == pytest.approx(-1_855.6, abs=0.5)


def test_rejects_captures_that_never_moved_the_deck() -> None:
    assert solver.solve([[1.0, 1.0, 1.0, 1.0]], 58.0) is None
    assert solver.per_cell_kg_per_count([[0.0] * 4] * 4, 58.0) is None


def test_rejects_a_non_positive_reference_weight() -> None:
    rows = [deltas(d, 20.0) for d in CORNER_DISTRIBUTIONS]
    assert solver.per_cell_kg_per_count(rows, 0.0) is None
    assert solver.shared_kg_per_count(rows, -5.0) is None


# ---- profile -------------------------------------------------------------


def test_profile_uses_the_firmware_convention() -> None:
    profile = CalibrationProfile((0, 0, 0, 0), (-1_856,) * 4, Method.MANUAL)  # type: ignore[arg-type]

    assert profile.cell_kg((-1_856, -3_712, 0, 1_856)) == [1.0, 2.0, 0.0, -1.0]
    assert profile.total_kg((-1_856, -3_712, 0, 1_856)) == 2.0


def test_the_september_screenshot_reads_58_kg_with_its_measured_coefficient() -> None:
    # Raw values with a 58 kg person on the deck, zeros from the same session.
    profile = CalibrationProfile(SEPTEMBER_ZEROS, SEPTEMBER_COUNTS_PER_KG, Method.MANUAL)

    assert profile.total_kg((-561_790, 75_651, 692_717, -74_546)) == pytest.approx(58.0, abs=0.1)


def test_the_old_coefficient_reproduces_the_bug() -> None:
    old = CalibrationProfile(SEPTEMBER_ZEROS, (-32_364.17, -32_425.82, -32_813.01, -32_210.63), Method.MANUAL)

    assert old.total_kg((-561_790, 75_651, 692_717, -74_546)) == pytest.approx(3.33, abs=0.02)


@pytest.mark.parametrize("coefficient", [0.0, float("nan"), float("inf")])
def test_profile_rejects_unusable_coefficients(coefficient: float) -> None:
    with pytest.raises(ValueError):
        CalibrationProfile((0, 0, 0, 0), (coefficient, 1, 1, 1), Method.MANUAL)  # type: ignore[arg-type]


# ---- store ---------------------------------------------------------------


def test_store_round_trips_and_keeps_history(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    assert store.load() is None
    store.save(
        CalibrationProfile(SEPTEMBER_ZEROS, SEPTEMBER_COUNTS_PER_KG, Method.MANUAL, firmware_bcd="0100")
    )
    store.save(CalibrationProfile((1, 2, 3, 4), (-1_800, -1_900, -2_000, -2_100), Method.FOUR_POSITION))  # type: ignore[arg-type]

    loaded = store.load()
    assert loaded is not None and loaded.method == Method.FOUR_POSITION
    assert len(store.history()) == 2
    store.clear()
    assert store.load() is None


def test_corrupt_stored_profile_is_ignored_not_fatal(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    (tmp_path / "active.json").write_text(json.dumps({"zeros": [1, 2]}))

    assert store.load() is None


# ---- weighing ------------------------------------------------------------


def feed(
    weighing: Weighing, values: tuple[int, int, int, int], seconds: float, rate: float = 976.5625
) -> None:
    n = int(seconds * rate)
    for i in range(n):
        weighing.add(int(i * 1e6 / rate), values)


def test_capture_needs_one_second() -> None:
    w = Weighing()
    feed(w, (1, 2, 3, 4), 0.5)
    assert w.capture() is None
    feed(w, (1, 2, 3, 4), 1.2)
    capture = w.capture()
    assert capture is not None and capture.means == (1.0, 2.0, 3.0, 4.0) and capture.stable


def test_weight_is_clamped_at_zero_and_marked_stable() -> None:
    w = Weighing()
    profile = CalibrationProfile((0, 0, 0, 0), (-1_856,) * 4, Method.MANUAL)  # type: ignore[arg-type]
    feed(w, (100, 100, 100, 100), 1.5)  # slightly "negative" load: noise around an empty deck
    weight = w.weight(profile)

    assert weight is not None
    assert weight["live_kg"] == 0.0 and weight["stable"] is True


# ---- default coefficients file -------------------------------------------

BENCH_ZEROS = (-553_476.8, 405_763.4, -549_396.9, -63_667.4)
BENCH_COUNTS = (-22_442.38, -21_816.8, -22_406.59, -21_849.17)


def test_defaults_file_absent_means_no_defaults(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)

    assert store.load_defaults() is None
    assert store.defaults_info() == {"present": False, "path": str(tmp_path / "defaults.json")}


def test_defaults_file_round_trips(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    store.save_defaults(CalibrationProfile(BENCH_ZEROS, BENCH_COUNTS, Method.MANUAL, firmware_bcd="0100"))

    loaded = store.load_defaults()
    assert loaded is not None and loaded.method == Method.DEFAULTS
    assert loaded.counts_per_kg == BENCH_COUNTS and loaded.zeros == BENCH_ZEROS
    assert json.loads((tmp_path / "defaults.json").read_text())["firmware_bcd"] == "0100"


def test_selected_defaults_are_re_read_from_the_file(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    store.save(store.save_defaults(CalibrationProfile(BENCH_ZEROS, BENCH_COUNTS, Method.MANUAL)))
    # Someone edits the defaults file; the next start must use the new values.
    data = json.loads((tmp_path / "defaults.json").read_text())
    data["counts_per_kg"] = [-20_000, -20_000, -20_000, -20_000]
    (tmp_path / "defaults.json").write_text(json.dumps(data))

    loaded = store.load()
    assert loaded is not None and loaded.counts_per_kg == (-20_000.0,) * 4


def test_selected_defaults_fall_back_to_the_saved_copy_if_the_file_vanishes(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    store.save(store.save_defaults(CalibrationProfile(BENCH_ZEROS, BENCH_COUNTS, Method.MANUAL)))
    (tmp_path / "defaults.json").unlink()

    loaded = store.load()
    assert loaded is not None and loaded.counts_per_kg == BENCH_COUNTS


def test_unreadable_defaults_file_is_reported_not_fatal(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    (tmp_path / "defaults.json").write_text("{not json")

    assert store.load_defaults() is None
