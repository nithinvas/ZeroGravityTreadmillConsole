"""The gait engine: synthetic walkers with exact answers, and the real 80 Hz recordings."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
import zipfile
from pathlib import Path

import pytest

from trendmill.device.simulator import CELL_COUNTS_PER_KG, ZERO_OFFSETS, SimulatedBoard
from trendmill.gait.engine import GaitEngine, Step
from trendmill.gait.filters import butterworth_delay_s, butterworth_lowpass
from trendmill.gait.speed import SpeedTimeline

RATE = 976.5625
US = 1_000_000


def kg(raw: tuple[int, int, int, int]) -> list[float]:
    return [(r - z) / c for r, z, c in zip(raw, ZERO_OFFSETS, CELL_COUNTS_PER_KG, strict=True)]


def walk(board: SimulatedBoard, seconds: float, speed: SpeedTimeline) -> tuple[GaitEngine, list[Step]]:
    engine = GaitEngine(RATE, speed)
    steps: list[Step] = []
    for i in range(int(seconds * RATE)):
        tl, tr, _, _ = kg(board.sample(i))
        steps += engine.feed(round(i * US / RATE), tl, tr)
    return engine, steps


def constant(kph: float | None) -> SpeedTimeline:
    timeline = SpeedTimeline()
    timeline.set(0, kph)
    return timeline


# ---- speed timeline --------------------------------------------------------


def test_distance_integrates_speed_changes() -> None:
    t = SpeedTimeline()
    t.set(0, 3.6)  # 1 m/s
    t.set(2 * US, 7.2)  # 2 m/s

    assert t.integrate_m(0, 2 * US) == pytest.approx(2.0)
    assert t.integrate_m(1 * US, 3 * US) == pytest.approx(3.0)
    assert t.changed_between(1 * US, 3 * US) and not t.changed_between(0, US)


def test_unknown_speed_gives_no_distance() -> None:
    t = SpeedTimeline()
    t.set(US, None)

    assert t.integrate_m(0, 2 * US) is None
    assert t.integrate_m(US, 2 * US) is None


# ---- filter ----------------------------------------------------------------


def test_lowpass_passes_dc_and_blocks_50_hz() -> None:
    f = butterworth_lowpass(RATE, 12.0)
    assert [f(5.0) for _ in range(2000)][-1] == pytest.approx(5.0)
    g = butterworth_lowpass(RATE, 12.0)
    out = [g(math.sin(2 * math.pi * 50 * i / RATE)) for i in range(4000)]
    assert max(abs(v) for v in out[2000:]) < 0.07


def test_group_delay_constant_matches_the_filter() -> None:
    # A slow ramp through the filter lags by the documented delay.
    f = butterworth_lowpass(RATE, 12.0)
    ramp = [i / RATE for i in range(4000)]
    out = [f(v) for v in ramp]
    lag_s = ramp[-1] - out[-1]
    assert lag_s == pytest.approx(butterworth_delay_s(12.0), rel=0.02)


# ---- synthetic walkers -------------------------------------------------------


@pytest.mark.parametrize(("cadence", "kph"), [(80.0, 1.5), (105.0, 3.0), (130.0, 5.0)])
def test_recovers_cadence_step_and_stride_length(cadence: float, kph: float) -> None:
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=cadence, noise_counts=300.0)
    engine, steps = walk(board, 30.0, constant(kph))
    live = engine.live()
    expected_step = kph / 3.6 * 60.0 / cadence

    assert live["cadence_spm"] == pytest.approx(cadence, rel=0.01)
    assert live["step_length_m"] == pytest.approx(expected_step, rel=0.02)
    assert live["stride_length_m"] == pytest.approx(2 * expected_step, rel=0.02)
    assert live["state"] == "walking"
    accepted = [s for s in steps if s.accepted]
    assert len(accepted) >= 0.9 * len(steps)
    assert all(a.side != b.side for a, b in zip(steps, steps[1:], strict=False))


def test_expected_number_of_steps_are_found() -> None:
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=105.0)
    _, steps = walk(board, 30.0, constant(3.0))
    # 105 steps/min for 30 s is 52.5 steps; the first few seconds settle the levels.
    assert 45 <= len(steps) <= 53


def test_empty_deck_and_standing_still_produce_no_steps() -> None:
    empty = SimulatedBoard(rate_hz=RATE)
    empty.set_load("empty")
    standing = SimulatedBoard(rate_hz=RATE)
    standing.set_load("static", kg=70.0, x=0.5, y=0.4)

    for board in (empty, standing):
        engine, steps = walk(board, 10.0, constant(3.0))
        assert steps == []
        assert engine.live()["cadence_spm"] is None


def test_without_belt_speed_nothing_is_counted_or_shown() -> None:
    board = SimulatedBoard(rate_hz=RATE)
    engine, steps = walk(board, 15.0, constant(None))

    assert steps == []
    assert engine.live()["prompt"] == "Belt speed not set"
    assert engine.live()["step_length_m"] is None


def test_speed_change_flags_transition_steps_and_lengths_follow() -> None:
    speed = SpeedTimeline()
    speed.set(0, 2.0)
    speed.set(20 * US, 4.0)
    board = SimulatedBoard(rate_hz=RATE, cadence_spm=100.0)
    engine, steps = walk(board, 40.0, speed)

    transitions = [s for s in steps if s.transition]
    assert 1 <= len(transitions) <= 2
    assert all(not s.accepted for s in transitions)
    late = [s for s in steps if s.t_us > 25 * US and s.accepted]
    assert statistics.median(s.step_length_m for s in late) == pytest.approx(4.0 / 3.6 * 0.6, rel=0.02)


# ---- real recordings ---------------------------------------------------------

DATA = Path.home() / "projects/TrendMillMonitor/docs/80Hz-DataCollection"


def _load(name: str) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, list[float]]]:
    with zipfile.ZipFile(DATA / f"{name}_80Hz.tmsession") as z:
        samples = list(csv.DictReader(io.TextIOWrapper(z.open("raw/samples.csv"))))
        conditions = list(csv.DictReader(io.TextIOWrapper(z.open("conditions.csv"))))
        calibration = json.loads(z.read("calibration.json"))
    return samples, conditions, calibration


def _spectral_cadence(times: list[float], values: list[float]) -> float:
    """Independent reference: the dominant lateral frequency. Detects no steps at all."""
    mean = statistics.fmean(values)
    x = [v - mean for v in values]
    best, best_power = 0.0, -1.0
    for k in range(300, 1701):  # stride frequency 0.300 to 1.700 Hz
        f = k / 1000
        re = sum(v * math.cos(2 * math.pi * f * t) for v, t in zip(x, times, strict=True))
        im = sum(v * math.sin(2 * math.pi * f * t) for v, t in zip(x, times, strict=True))
        if re * re + im * im > best_power:
            best, best_power = f, re * re + im * im
    return 120.0 * best


@pytest.mark.skipif(not DATA.exists(), reason="80 Hz recordings not available")
@pytest.mark.parametrize("name", ["Nithin", "Eshaq"])
def test_real_walking_cadence_matches_an_independent_estimate(name: str) -> None:
    samples, conditions, cal = _load(name)
    zeros, counts = cal["rawZero"], cal["coefficientCountsPerKg"]
    speed = SpeedTimeline()
    starts = {int(c["effective_from_packet_number"]): float(c["speed_kph"]) for c in conditions}
    engine = GaitEngine(80.0, speed)
    t0 = int(samples[0]["firmware_timestamp_ms"])
    by_speed: dict[float, list[tuple[float, float]]] = {}
    steps: list[Step] = []
    current = None
    for row in samples:
        n = int(row["packet_number"])
        t_us = (int(row["firmware_timestamp_ms"]) - t0) * 1000
        if n in starts:
            current = starts[n]
            speed.set(t_us, current)
        tl = (int(row["top_left_raw"]) - zeros[0]) / counts[0]
        tr = (int(row["top_right_raw"]) - zeros[1]) / counts[1]
        steps += engine.feed(t_us, tl, tr)
        if current is not None:
            by_speed.setdefault(current, []).append((t_us / US, tr - tl))

    checked = 0
    for kph in (2.0, 3.0, 4.0, 5.0):
        series = by_speed.get(kph)
        if not series or series[-1][0] - series[0][0] < 8:
            continue
        end = series[-1][0]
        window = [(t, v) for t, v in series if t >= end - 10]
        reference = _spectral_cadence([t for t, _ in window], [v for _, v in window])
        held = [s for s in steps if s.accepted and s.speed_kph == kph and s.t_us / US >= end - 10]
        measured = 60.0 / statistics.median(s.step_time_s for s in held)
        assert measured == pytest.approx(reference, rel=0.04), f"{name} at {kph} km/h"
        checked += 1
    assert checked >= 3
