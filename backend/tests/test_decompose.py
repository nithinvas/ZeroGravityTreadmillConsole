"""Splitting one deck into two feet.

The synthetic walker here is the only place we know the true answer: real decks
never tell us what each foot was carrying. So the tests that matter are the ones
that put a known gait in and check what comes back, plus the invariants that must
hold on any input at all -- including input that is nothing like walking.
"""

from __future__ import annotations

import math

import pytest

from treadmill.gait.decompose import (
    DECK_LENGTH_M,
    DECK_WIDTH_M,
    Phase,
    Quality,
    StreamingDecomposer,
    decompose,
    decompose_trace,
    moving_average,
)

RATE = 100.0


def cells_for(total: float, copx: float, copy_: float) -> list[float]:
    """The four cell readings a deck would produce for this load and position."""
    px = total * copx / (DECK_WIDTH_M / 2)
    py = total * copy_ / (DECK_LENGTH_M / 2)
    return [(total + py - px) / 4, (total + py + px) / 4,
            (total + px - py) / 4, (total - px - py) / 4]


def _profile(u: float) -> float:
    """Normalised vertical force through one stance -- the double hump."""
    return math.sin(math.pi * u) * (1.0 + 0.18 * math.cos(2 * math.pi * u))


def walker(seconds=8.0, bw=70.0, cadence=110.0, left_x=-0.09, right_x=0.06,
           left_scale=1.0, right_scale=1.0, double_support=0.20, belt=1.1):
    """A two-footed walker, as a deck would see it.

    Feet are deliberately not symmetric about the centre line, and can be loaded
    unequally, because real patients are neither.
    """
    step = 60.0 / cadence
    stance = step * (1 + double_support)
    t, cells, truth, raw = [], [], [], []
    n = int(seconds * RATE)
    for i in range(n):
        ti = i / RATE
        fl = fr = 0.0
        for k in range(-1, int(seconds / step) + 2):
            start = k * step
            u = (ti - start) / stance
            if 0.0 < u < 1.0:
                f = _profile(u) * bw
                if k % 2 == 0:
                    fl += f * left_scale
                else:
                    fr += f * right_scale
        raw.append((ti, fl, fr))

    # Normalise so the mean total force over the walk is body weight -- Newton's
    # third law, and the only thing that makes the recovered body weight mean
    # anything.
    mean = sum(l + r for _, l, r in raw) / len(raw)
    k = bw / mean if mean > 0 else 1.0
    for ti, fl, fr in raw:
        fl, fr = fl * k, fr * k
        total = fl + fr
        if total < 1e-6:
            t.append(ti); cells.append([0.0] * 4); truth.append((0.0, 0.0))
            continue
        # Each planted foot's pressure point rolls heel-to-toe while the belt
        # drags it back, so neither sits still.
        yl = ((ti % (2 * step)) - step) * -(belt - 0.25)
        yr = (((ti + step) % (2 * step)) - step) * -(belt - 0.25)
        copx = (fl * left_x + fr * right_x) / total
        copy_ = max(-0.35, min(0.35, (fl * yl + fr * yr) / total))
        t.append(ti); cells.append(cells_for(total, copx, copy_)); truth.append((fl, fr))
    return t, cells, truth


def test_a_known_walker_comes_back_out():
    t, cells, truth = walker()
    r = decompose(t, cells)
    assert r.quality is Quality.GOOD, r.reason
    assert r.body_weight_kg == pytest.approx(70.0, rel=0.1)

    resolved = [(s, tr) for s, tr in zip(r.samples, truth) if s.phase is not Phase.UNAVAILABLE]
    assert len(resolved) > 0.9 * len(truth)
    err = [abs(s.left_kg - tl) for s, (tl, _) in resolved]
    assert sum(err) / len(err) < 0.05 * 70.0        # mean error under 5% of body weight


def test_an_airborne_foot_carries_exactly_nothing():
    """The whole point: these curves reach zero, they do not bottom out."""
    t, cells, _ = walker()
    r = decompose(t, cells)
    lefts = [s.left_kg for s in r.samples if s.phase is Phase.RIGHT]
    assert lefts and all(v == 0.0 for v in lefts)


@pytest.mark.parametrize("bw", [32.0, 70.0, 140.0])
def test_any_body_weight(bw):
    t, cells, truth = walker(bw=bw)
    r = decompose(t, cells)
    assert r.quality is Quality.GOOD
    assert r.body_weight_kg == pytest.approx(bw, rel=0.1)
    peak = max(s.left_kg for s in r.samples)
    assert peak == pytest.approx(max(tl for tl, _ in truth), rel=0.15)


@pytest.mark.parametrize("scale", [1.0, 0.75, 0.45])
def test_asymmetry_is_measured_not_assumed(scale):
    """A patient favouring one leg must read as favouring one leg."""
    t, cells, _ = walker(right_scale=scale)
    r = decompose(t, cells)
    peak_l = max(s.left_kg for s in r.samples)
    peak_r = max(s.right_kg for s in r.samples)
    assert peak_r / peak_l == pytest.approx(scale, rel=0.2)


def test_feet_placed_well_off_centre():
    """Nothing assumes the patient stands in the middle of the deck."""
    t, cells, _ = walker(left_x=0.01, right_x=0.16)
    r = decompose(t, cells)
    assert r.quality is Quality.GOOD, r.reason


def test_the_two_feet_always_add_up_to_what_was_measured():
    """The one quantity actually measured is the total, so it is never fitted."""
    for kwargs in ({}, {"right_scale": 0.4}, {"cadence": 150}, {"double_support": 0.05}):
        t, cells, _ = walker(seconds=5.0, **kwargs)
        for s in decompose(t, cells).samples:
            assert s.left_kg + s.right_kg + s.residual_kg == pytest.approx(s.total_kg, abs=1e-9)


def test_standing_still_is_refused_rather_than_guessed():
    t = [i / RATE for i in range(400)]
    cells = [cells_for(70.0, 0.0, 0.0) for _ in t]
    r = decompose(t, cells)
    assert r.quality is Quality.UNUSABLE
    assert all(s.phase is Phase.UNAVAILABLE for s in r.samples)
    assert "cannot be told apart" in r.reason


def test_an_empty_deck_is_refused():
    t = [i / RATE for i in range(200)]
    r = decompose(t, [[0.0] * 4 for _ in t])
    assert r.quality is Quality.UNUSABLE


def test_a_gap_is_reported_as_a_gap_not_a_zero():
    """None, not 0 -- a chart must break the line, not draw it through."""
    t = [i / RATE for i in range(400)]
    cells = [cells_for(70.0, 0.0, 0.0) for _ in t]
    rows = decompose(t, cells).as_dict()["samples"]
    assert all(row["left"] is None and row["right"] is None for row in rows)


def test_live_and_the_report_agree():
    """A therapist who watched a curve must read the same curve afterwards."""
    t, cells, _ = walker(seconds=6.0)
    batch = decompose_trace(t, cells)

    live = StreamingDecomposer()
    streamed = [s for ti, c in zip(t, cells) for s in live.push(ti, c)]
    streamed += live.flush()
    assert len(streamed) > 0.8 * len(t)
    assert [s.t for s in streamed] == sorted(s.t for s in streamed)

    # The report replays the same window, so the two are identical rather than
    # close -- which is the only version of this promise worth making.
    for live_s, report_s in zip(streamed, batch.samples):
        assert live_s == report_s


def test_moving_average_keeps_its_length_and_its_edges():
    assert moving_average([1.0, 2.0, 3.0], 1) == [1.0, 2.0, 3.0]
    out = moving_average([0.0, 0.0, 9.0, 0.0, 0.0], 3)
    assert len(out) == 5
    assert out[2] == pytest.approx(3.0)
