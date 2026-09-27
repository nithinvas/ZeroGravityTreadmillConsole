"""Belt-height control.

The mechanism lifts a deck a patient stands on, and reports nothing back about
where it is. Most of what is checked here is therefore refusal: the cases where
the console must decline to move rather than guess.
"""

from __future__ import annotations

import time

import pytest

from treadmill.height import protocol
from treadmill.height.controller import HeightController, HeightError
from treadmill.height.link import SimulatedHeightMechanism


async def homed() -> tuple[HeightController, SimulatedHeightMechanism]:
    mechanism = SimulatedHeightMechanism()
    controller = HeightController(mechanism)
    await controller.home()
    controller._moving_until = 0.0  # the test does not wait out the homing crawl
    return controller, mechanism


def opcodes(m: SimulatedHeightMechanism) -> list[protocol.Opcode]:
    return [c.opcode for c in m.commands]


# ---- the wire ----------------------------------------------------------------


def test_a_frame_says_what_it_is() -> None:
    assert protocol.move_to(300) == bytes([0x48, 0x54, 0x01, 0x00, 0x2C, 0x01, 0x00, 0x00])
    assert len(protocol.home()) == protocol.FRAME_SIZE


def test_a_frame_round_trips() -> None:
    command = protocol.parse(protocol.move_to(455, seq=7))
    assert command is not None
    assert command.opcode is protocol.Opcode.MOVE_TO
    assert command.param == 455
    assert command.seq == 7


@pytest.mark.parametrize("junk", [b"", b"XX\x01\x00\x00\x00\x00\x00", b"HT\x99\x00\x00\x00\x00\x00"])
def test_anything_that_is_not_a_command_is_rejected(junk: bytes) -> None:
    # This frame drives a motor: a stray byte run must never decode as a move.
    assert protocol.parse(junk) is None


def test_heights_snap_to_the_travel_and_the_ten_millimetre_grid() -> None:
    assert protocol.clamp(7) == protocol.MIN_HEIGHT_MM
    assert protocol.clamp(10_000) == protocol.MAX_HEIGHT_MM
    assert protocol.clamp(247) == 250
    assert protocol.clamp(244) == 240


def test_travel_time_matches_the_firmware_profile() -> None:
    # Short moves are triangular and never reach MAX_SPEED; long ones cruise at
    # 2000 pulses/s = 20 mm/s, so the full travel is the best part of a minute.
    assert protocol.move_seconds(0) == 0.0
    assert 2.0 < protocol.move_seconds(10) < 5.0
    assert 40.0 < protocol.move_seconds(730) < 60.0
    assert protocol.move_seconds(-100) == protocol.move_seconds(100)  # direction is not distance


# ---- refusals ----------------------------------------------------------------


async def test_a_console_without_the_mechanism_says_so() -> None:
    controller = HeightController(None)
    assert controller.available is False
    assert controller.snapshot()["can_move"] is False
    with pytest.raises(HeightError, match="without belt-height control"):
        await controller.home()


async def test_nothing_moves_before_homing() -> None:
    """An absolute height is meaningless without a datum — it would travel blind."""
    controller = HeightController(SimulatedHeightMechanism())
    with pytest.raises(HeightError, match="has not been homed"):
        await controller.move_to(300)
    with pytest.raises(HeightError, match="has not been homed"):
        await controller.nudge(1)


async def test_nothing_moves_while_a_session_records() -> None:
    controller, _ = await homed()
    controller.session_active = True
    with pytest.raises(HeightError, match="session is recording"):
        await controller.move_to(300)
    with pytest.raises(HeightError, match="session is recording"):
        await controller.home()
    assert controller.snapshot()["locked_by_session"] is True


async def test_a_second_move_is_refused_while_the_deck_is_still_travelling() -> None:
    controller, _ = await homed()
    await controller.move_to(400)
    assert controller.moving
    with pytest.raises(HeightError, match="still moving"):
        await controller.move_to(500)


# ---- moving ------------------------------------------------------------------


async def test_homing_establishes_the_datum_at_the_bottom_of_the_travel() -> None:
    controller, mechanism = await homed()
    assert controller.homed
    assert controller.target_mm == protocol.MIN_HEIGHT_MM
    assert opcodes(mechanism) == [protocol.Opcode.HOME]


async def test_a_press_moves_ten_millimetres() -> None:
    controller, mechanism = await homed()
    await controller.nudge(1)
    assert controller.target_mm == protocol.MIN_HEIGHT_MM + protocol.STEP_MM
    assert mechanism.commands[-1].param == 30


async def test_presses_do_not_walk_past_either_end() -> None:
    controller, _ = await homed()
    await controller.nudge(-5)
    assert controller.target_mm == protocol.MIN_HEIGHT_MM
    controller._moving_until = 0.0
    await controller.move_to(protocol.MAX_HEIGHT_MM)
    assert controller.target_mm == protocol.MAX_HEIGHT_MM
    controller._moving_until = 0.0
    await controller.nudge(3)
    assert controller.target_mm == protocol.MAX_HEIGHT_MM


async def test_a_typed_height_is_snapped_and_sent() -> None:
    controller, mechanism = await homed()
    await controller.move_to(333)
    assert controller.target_mm == 330
    assert mechanism.commands[-1].param == 330


async def test_asking_for_the_height_it_is_already_at_sends_nothing() -> None:
    controller, mechanism = await homed()
    before = len(mechanism.commands)
    await controller.move_to(protocol.MIN_HEIGHT_MM)
    assert len(mechanism.commands) == before
    assert not controller.moving


async def test_a_move_reports_progress_while_it_runs() -> None:
    controller, _ = await homed()
    await controller.move_to(300)
    first = controller.snapshot()
    assert first["moving"] is True
    assert first["seconds_left"] > 0
    assert 0.0 <= first["progress"] < 1.0
    time.sleep(0.2)
    assert controller.snapshot()["progress"] > first["progress"]


async def test_each_command_carries_a_new_sequence_number() -> None:
    """So the board can drop a frame it has already acted on."""
    controller, mechanism = await homed()
    await controller.move_to(300)
    controller._moving_until = 0.0
    await controller.move_to(400)
    seqs = [c.seq for c in mechanism.commands]
    assert len(set(seqs)) == len(seqs)


# ---- stopping ----------------------------------------------------------------


async def test_stopping_mid_move_forgets_where_the_deck_is() -> None:
    """The mechanism reports nothing, so a half-finished move loses the datum."""
    controller, mechanism = await homed()
    await controller.move_to(600)
    await controller.stop()

    assert opcodes(mechanism)[-1] is protocol.Opcode.STOP
    assert controller.homed is False
    assert controller.target_mm is None
    assert "no longer known" in controller.last_error
    with pytest.raises(HeightError, match="has not been homed"):
        await controller.move_to(300)


async def test_stop_works_even_while_a_session_is_recording() -> None:
    # Everything else is refused during a session; stopping a moving deck is not.
    controller, mechanism = await homed()
    await controller.move_to(600)
    controller.session_active = True
    await controller.stop()
    assert opcodes(mechanism)[-1] is protocol.Opcode.STOP


async def test_a_board_that_is_not_there_is_reported_not_swallowed() -> None:
    class Absent:
        name = "usb"

        async def send(self, payload: bytes) -> None:
            raise ConnectionError("no such device")

    controller = HeightController(Absent())
    with pytest.raises(HeightError, match="did not reach the board"):
        await controller.home()
    assert controller.homed is False
