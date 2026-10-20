"""Noticing a load cell that has stopped responding.

A corner failed on the real machine between September and October. Nobody
noticed for weeks: the deck kept reporting a number, sessions kept recording,
and every weight was understated by about a quarter. These tests exist so that
cannot happen quietly again.
"""

from __future__ import annotations

import math

from treadmill.gait.cellhealth import CellHealthMonitor, CellState

RATE = 200.0


def feed(mon: CellHealthMonitor, *, seconds=25.0, bw=70.0, dead: int | None = None,
         light: int | None = None, walking=True, sway=True):
    """A walker on four corners, optionally with one corner dead or lightly loaded."""
    n = int(seconds * RATE)
    for i in range(n):
        t = i / RATE
        swing = math.sin(2 * math.pi * 1.1 * t) if sway else 0.0
        step = max(0.0, math.sin(math.pi * ((t * 2.2) % 1.0))) if walking else 1.0
        base = bw / 4 * step
        cells = [
            base * (1 + 0.6 * swing),
            base * (1 - 0.6 * swing),
            base * (1 - 0.5 * swing),
            base * (1 + 0.5 * swing),
        ]
        if dead is not None:
            # What a failed cell actually reads: its own electrical noise.
            cells[dead] = 0.4 * math.sin(97.0 * t)
        if light is not None:
            cells[light] *= 0.55
        mon.on_sample(t, cells)


def test_a_failed_corner_is_named():
    mon = CellHealthMonitor()
    feed(mon, dead=3)
    r = mon.report()
    assert r.cells[3].state is CellState.DEAD
    assert r.fault is not None
    assert "bottom left" in r.fault.lower()
    assert "under-reported" in r.fault
    assert all(c.state is CellState.OK for c in r.cells[:3])


def test_a_healthy_deck_says_nothing():
    mon = CellHealthMonitor()
    feed(mon)
    r = mon.report()
    assert r.fault is None
    assert all(c.state is CellState.OK for c in r.cells)


def test_a_lightly_loaded_corner_is_not_called_dead():
    """A patient standing off-centre genuinely unloads a corner. That is not a fault."""
    mon = CellHealthMonitor()
    feed(mon, light=0)
    r = mon.report()
    assert r.fault is None
    assert r.cells[0].state is not CellState.DEAD


def test_standing_perfectly_still_is_not_judged():
    """No corner moves, so there is nothing to compare. Silence, not a fault.

    Standing and swaying is a different case: the corners do move, and the
    monitor is entitled to judge them.
    """
    mon = CellHealthMonitor()
    feed(mon, walking=False, sway=False)
    r = mon.report()
    assert r.fault is None
    assert all(c.state is CellState.UNKNOWN for c in r.cells)


def test_an_empty_deck_is_not_judged():
    mon = CellHealthMonitor()
    feed(mon, bw=0.5)
    assert mon.report().fault is None


def test_nothing_is_claimed_before_there_is_enough_to_look_at():
    mon = CellHealthMonitor()
    feed(mon, seconds=2.0)
    r = mon.report()
    assert r.fault is None
    assert all(c.state is CellState.UNKNOWN for c in r.cells)


def test_two_failed_corners_are_both_named():
    mon = CellHealthMonitor()
    feed(mon, dead=3)
    # Overwrite a second corner the same way.
    n = int(25.0 * RATE)
    mon2 = CellHealthMonitor()
    for i in range(n):
        t = i / RATE
        step = max(0.0, math.sin(math.pi * ((t * 2.2) % 1.0)))
        mon2.on_sample(t, [70 / 4 * step, 70 / 4 * step,
                           0.4 * math.sin(97 * t), 0.3 * math.sin(83 * t)])
    r = mon2.report()
    assert r.fault is not None and "2 load cells" in r.fault
    assert "bottom right" in r.fault and "bottom left" in r.fault


def test_memory_is_bounded_whatever_the_board_rate():
    """At 1 kHz a session is a million samples; the monitor keeps 40 buckets."""
    mon = CellHealthMonitor()
    for i in range(200_000):
        mon.on_sample(i / 1000.0, [5.0, 5.0, 5.0, 5.0])
    assert len(mon._buckets) <= 40


def test_standing_and_swaying_is_judged_and_found_healthy():
    """Enough movement to compare, so a verdict -- and no fault on a good deck."""
    mon = CellHealthMonitor()
    feed(mon, walking=False, sway=True)
    r = mon.report()
    assert r.fault is None
    assert any(c.state is CellState.OK for c in r.cells)
