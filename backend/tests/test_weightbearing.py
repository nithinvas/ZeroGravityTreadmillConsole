"""Weight bearing: what each leg carries, against what the surgeon allowed.

The tests that matter here are the refusals. Getting a number out of a clean
walker is easy; the clinically dangerous failure is confidently reporting
"18 kg on the operated leg" for a patient who is actually shuffling with both
feet down and putting 45 kg through it.
"""

from __future__ import annotations

import math

import pytest

from treadmill.gait.weightbearing import (
    MIN_SEPARATION,
    Quality,
    WeightBearingTracker,
)

RATE = 200.0


def walk(tracker: WeightBearingTracker, *, steps=20, bw=70.0, step_s=0.55,
         peak=1.15, trough=0.45, left_scale=1.0, t0=0.0):
    """Feed a walker whose load falls to `trough` x BW between steps.

    `trough` is the knob the whole feature turns on: 0.45 is ordinary walking,
    0.95 is a shuffle with both feet permanently down, 0.0 is running.
    """
    t = t0
    for i in range(steps):
        side = "L" if i % 2 == 0 else "R"
        scale = left_scale if side == "L" else 1.0
        tracker.on_step(t, side)
        n = int(step_s * RATE)
        for k in range(n):
            u = k / n
            # Rises from the trough to the peak and back: one stance.
            v = trough + (peak - trough) * math.sin(math.pi * u) ** 0.7
            tracker.on_sample(t, v * bw * scale)
            t += 1 / RATE
    tracker.finish(t)
    return t


def test_a_clean_walker_gives_a_number_for_each_leg():
    wb = WeightBearingTracker(body_weight_kg=70.0, limit_kg=100.0)
    walk(wb)
    s = wb.state()
    assert s.quality is Quality.GOOD, s.reason
    assert s.left_kg == pytest.approx(80.5, rel=0.1)
    assert s.right_kg == pytest.approx(80.5, rel=0.1)
    assert s.steps_over == 0


def test_a_favoured_leg_shows_as_a_favoured_leg():
    wb = WeightBearingTracker(body_weight_kg=70.0)
    walk(wb, left_scale=0.5)
    s = wb.state()
    assert s.left_kg is not None and s.right_kg is not None
    assert s.left_kg / s.right_kg == pytest.approx(0.5, rel=0.12)


def test_steps_over_the_limit_are_counted():
    wb = WeightBearingTracker(body_weight_kg=70.0, limit_kg=20.0)
    walk(wb, steps=20)
    s = wb.state()
    # Every step of ordinary walking blows a 20 kg limit -- which is the
    # finding this feature exists to surface, not an error.
    assert s.steps_over == s.steps
    assert s.steps >= 18


def test_a_shuffler_gets_one_number_for_both_legs_not_two():
    """The corner case that matters: both feet down, no leg isolated.

    Measured at 1 km/h across three subjects, the load falls only 5-13% between
    steps. Splitting that into two legs would be invention.
    """
    wb = WeightBearingTracker(body_weight_kg=70.0)
    walk(wb, trough=0.95, peak=1.05)
    s = wb.state()
    assert s.quality is Quality.COMBINED
    assert s.left_kg is None and s.right_kg is None
    assert s.combined_kg is not None          # the honest number is still given
    assert s.separation < MIN_SEPARATION
    assert "cannot be told apart" in s.reason


def test_running_is_the_easy_case():
    """Both feet leave the deck, so every stance is unambiguously one leg."""
    wb = WeightBearingTracker(body_weight_kg=70.0)
    walk(wb, trough=0.0, peak=2.3, step_s=0.33)
    s = wb.state()
    assert s.quality is Quality.GOOD
    assert s.separation > 0.85          # vs ~0.6 for ordinary walking
    assert s.left_kg == pytest.approx(2.3 * 70.0, rel=0.1)


def test_nothing_is_reported_until_there_are_enough_steps():
    wb = WeightBearingTracker(body_weight_kg=70.0)
    walk(wb, steps=3)
    s = wb.state()
    assert s.quality is Quality.UNAVAILABLE
    assert s.left_kg is None and s.combined_kg is None


def test_one_leg_never_landing_is_refused():
    """A patient hopping, or dragging a leg that never takes a stance."""
    wb = WeightBearingTracker(body_weight_kg=70.0)
    t = 0.0
    for _ in range(14):
        wb.on_step(t, "L")                     # always the same foot
        for k in range(int(0.55 * RATE)):
            wb.on_sample(t, 70.0 * (0.45 + 0.7 * math.sin(math.pi * k / 110) ** 0.7))
            t += 1 / RATE
    wb.finish(t)
    s = wb.state()
    assert s.quality is Quality.COMBINED
    assert "one leg" in s.reason.lower()


def test_a_pause_does_not_become_a_giant_step():
    wb = WeightBearingTracker(body_weight_kg=70.0)
    walk(wb, steps=12)
    wb.on_step(100.0, "L")                     # a long gap, then one more
    for k in range(50):
        wb.on_sample(100.0 + k / RATE, 70.0)
    closed = wb.on_step(104.0, "R")            # 4 s later: not a stride
    assert closed is None
    assert all(s.t < 50 for s in wb.steps)


def test_a_toe_brush_is_not_a_stance():
    wb = WeightBearingTracker(body_weight_kg=70.0)
    wb.on_step(0.0, "L")
    for k in range(40):
        wb.on_sample(k / RATE, 3.0)            # 3 kg: a foot resting, not weight
    assert wb.on_step(0.5, "R") is None
    assert wb.steps == []


def test_percentages_need_a_body_weight_and_say_so_when_absent():
    wb = WeightBearingTracker(body_weight_kg=None)
    walk(wb, bw=70.0)
    d = wb.state().as_dict()
    assert d["combined_kg"] is not None        # kilograms always work
    assert d["left_pct_bw"] is None            # percentages need a reference
    assert d["body_weight_kg"] is None


def test_no_limit_set_means_nothing_is_over_it():
    wb = WeightBearingTracker(body_weight_kg=70.0, limit_kg=None)
    walk(wb)
    assert wb.state().steps_over == 0


def test_an_empty_session_does_not_crash():
    wb = WeightBearingTracker(body_weight_kg=70.0)
    wb.finish(0.0)
    s = wb.state()
    assert s.quality is Quality.UNAVAILABLE
    assert wb.summary()["session"]["steps"] == 0
