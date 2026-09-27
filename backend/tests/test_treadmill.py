"""The controller, driven against the simulated machine.

Every test here is a behaviour that cost time on the real treadmill or in the
mobile app: control that has to be requested first, a stop parameter the spec
sheet got wrong, a target that must not be stepped from the readback, and a belt
someone stops at the console while a session is running.
"""

from __future__ import annotations

import asyncio

import pytest

from trendmill.treadmill import ftms
from trendmill.treadmill.controller import (
    ConnectionState,
    TreadmillController,
    TreadmillError,
    TreadmillEvent,
)
from trendmill.treadmill.link import SimulatedTreadmill, TreadmillUnavailable


async def connected() -> tuple[TreadmillController, SimulatedTreadmill]:
    machine = SimulatedTreadmill(broadcast_s=0)  # frames are injected by hand here
    controller = TreadmillController(machine)
    await controller.connect()
    return controller, machine


def opcodes(machine: SimulatedTreadmill) -> list[int]:
    return [frame[0] for frame in machine.written]


async def test_connecting_reads_the_limits_and_takes_control() -> None:
    controller, machine = await connected()
    assert controller.state is ConnectionState.READY
    assert controller.has_control
    assert controller.can_control
    # Control first, before anything else is attempted.
    assert opcodes(machine)[0] == ftms.OP_REQUEST_CONTROL
    assert controller.limits.min_speed_kph == pytest.approx(1.0)
    assert controller.limits.max_speed_kph == pytest.approx(12.0)
    assert controller.limits.speed_step_kph == pytest.approx(0.1)


async def test_a_console_without_a_link_says_so_instead_of_failing_obscurely() -> None:
    controller = TreadmillController(None)
    assert not controller.available
    with pytest.raises(TreadmillError, match="without treadmill control"):
        await controller.connect()
    assert controller.snapshot()["can_start"] is False


async def test_a_missing_treadmill_is_a_message_not_an_exception() -> None:
    class Absent:
        name = "ble"
        connected = False

        async def connect(self, on_notify: object) -> str:
            raise TreadmillUnavailable("No treadmill found. Check it is switched on.")

        async def write(self, payload: bytes) -> None: ...
        async def read(self, characteristic: str) -> bytes | None: ...
        async def disconnect(self) -> None: ...

    controller = TreadmillController(Absent())
    snapshot = await controller.connect()
    assert snapshot["state"] == "failed"
    assert "switched on" in snapshot["detail"]
    # And the console must not pretend it can drive the belt.
    assert snapshot["can_start"] is False
    assert snapshot["can_stop"] is False


async def test_commands_are_refused_before_connecting() -> None:
    controller = TreadmillController(SimulatedTreadmill(broadcast_s=0))
    with pytest.raises(TreadmillError, match="not connected"):
        await controller.start_belt()


async def test_starting_and_stopping_tracks_the_belt() -> None:
    controller, machine = await connected()
    assert not controller.running
    await controller.start_belt()
    assert controller.running
    assert controller.snapshot()["can_start"] is False
    assert controller.snapshot()["can_stop"] is True
    await controller.stop_belt()
    assert not controller.running
    assert machine.written[-1] == bytes([0x08, 0x01])  # the parameter that works


async def test_a_session_always_opens_at_one_kph() -> None:
    controller, machine = await connected()
    await controller.start_belt()
    await controller.set_speed(9.0)  # the last patient finished fast
    await controller.end_session()

    speed = await controller.begin_session()
    assert speed == pytest.approx(ftms.SESSION_START_SPEED_KPH)
    assert controller.target_speed_kph == pytest.approx(1.0)
    assert controller.running
    # Start first, then the speed: the machine discards a target given while idle.
    assert opcodes(machine)[-2:] == [ftms.OP_START_OR_RESUME, ftms.OP_SET_TARGET_SPEED]
    assert machine.written[-1] == ftms.set_speed(1.0)


async def test_ending_a_session_stops_the_belt_and_forgets_the_speed() -> None:
    controller, machine = await connected()
    await controller.begin_session()
    await controller.adjust_speed(20)
    await controller.end_session()
    assert not controller.running
    assert controller.target_speed_kph is None
    assert machine.written[-1] == ftms.stop()


async def test_starting_again_comes_up_at_one_kph_not_the_old_speed() -> None:
    """The belt is stopped exactly when someone is stepping on or off it."""
    controller, machine = await connected()
    await controller.begin_session()
    await controller.set_speed(6.0)
    await controller.stop_belt()

    await controller.start_belt()
    assert controller.target_speed_kph == pytest.approx(1.0)
    assert machine._target_kph == pytest.approx(1.0)
    assert machine.written[-1] == ftms.set_speed(1.0)


async def test_a_stopped_belt_has_no_speed_at_all() -> None:
    """Not a speed of zero: the machine's range starts at 1 km/h."""
    controller, _ = await connected()
    await controller.begin_session()
    await controller.set_speed(5.0)
    await controller.stop_belt()

    assert controller.target_speed_kph is None
    assert controller.snapshot()["can_change_speed"] is False
    with pytest.raises(TreadmillError, match="comes up at 1.0 km/h"):
        await controller.set_speed(5.0)


async def test_ending_a_session_is_safe_when_the_belt_is_already_stopped() -> None:
    controller, machine = await connected()
    before = len(machine.written)
    await controller.end_session()
    assert len(machine.written) == before  # nothing sent: there was nothing to stop


async def test_steps_move_the_target_not_the_readback() -> None:
    """The app's speed-stuck bug: two quick presses while the motor is still ramping."""
    controller, machine = await connected()
    await controller.begin_session()
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(1.0))
    await controller.adjust_speed(1)
    assert controller.target_speed_kph == pytest.approx(1.1)
    # The belt is still at 1.0 — stepping from the readback would send 1.1 again.
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(1.0))
    await controller.adjust_speed(1)
    assert controller.target_speed_kph == pytest.approx(1.2)
    assert machine.written[-1] == ftms.set_speed(1.2)


async def test_the_target_echo_never_walks_the_target_back_down() -> None:
    controller, _ = await connected()
    await controller.start_belt()
    await controller.set_speed(5.0)
    # The machine echoes Target-Changed with the instantaneous value while ramping.
    controller._on_notify(ftms.FITNESS_MACHINE_STATUS, bytes([0x05]) + (120).to_bytes(2, "little"))
    assert controller.target_speed_kph == pytest.approx(5.0)


async def test_speed_is_clamped_to_the_machines_range() -> None:
    controller, _ = await connected()
    await controller.start_belt()
    await controller.set_speed(30.0)
    assert controller.target_speed_kph == pytest.approx(12.0)
    await controller.set_speed(0.2)
    assert controller.target_speed_kph == pytest.approx(1.0)


async def test_inclination_steps_within_its_own_range() -> None:
    controller, _ = await connected()
    await controller.adjust_incline(2)
    assert controller.target_incline_percent == pytest.approx(2.0)
    await controller.adjust_incline(-10)
    assert controller.target_incline_percent == pytest.approx(0.0)
    await controller.adjust_incline(100)
    assert controller.target_incline_percent == pytest.approx(15.0)


async def test_control_lost_mid_session_is_re_requested_once_and_the_command_repeated() -> None:
    controller, machine = await connected()
    await controller.start_belt()
    machine._controlled = False  # the machine dropped control on its own
    await controller.set_speed(3.0)
    assert controller.target_speed_kph == pytest.approx(3.0)
    assert opcodes(machine).count(ftms.OP_REQUEST_CONTROL) == 2


async def test_a_refused_command_is_reported_rather_than_looking_like_success() -> None:
    controller, machine = await connected()
    await controller.start_belt()

    async def refuse(payload: bytes) -> None:
        machine.written.append(payload)
        controller._on_notify(
            ftms.CONTROL_POINT, bytes([ftms.OP_RESPONSE_CODE, payload[0], 0x03])
        )

    machine.write = refuse  # type: ignore[method-assign]
    with pytest.raises(TreadmillError, match="outside the range"):
        await controller.set_speed(4.0)


async def test_someone_stopping_the_belt_at_the_console_is_noticed() -> None:
    controller, machine = await connected()
    await controller.start_belt()
    seen: list[TreadmillEvent] = []
    controller.on_event = seen.append
    machine.press_stop_on_the_console()
    assert not controller.running
    assert [e.kind for e in seen] == ["belt"]
    assert seen[0].running is False


async def test_the_safety_key_is_surfaced_and_only_cleared_by_a_fresh_start() -> None:
    controller, machine = await connected()
    await controller.start_belt()
    machine.pull_safety_key()
    assert controller.safety_key_pulled
    assert not controller.running
    assert "safety key" in controller.last_error.lower()
    await controller.start_belt()
    assert not controller.safety_key_pulled


async def test_a_belt_reporting_zero_for_long_enough_counts_as_stopped() -> None:
    controller, _ = await connected()
    await controller.start_belt()
    controller._started_at -= 10  # past the start grace period
    for _ in range(3):
        controller._on_notify(ftms.TREADMILL_DATA, _data_frame(0.0))
    assert not controller.running


async def test_one_zero_frame_during_a_ramp_does_not_stop_the_belt() -> None:
    controller, _ = await connected()
    await controller.start_belt()
    controller._started_at -= 10
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(0.0))
    assert controller.running


async def test_a_moving_belt_is_running_even_if_the_console_did_not_start_it() -> None:
    controller, _ = await connected()
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(2.4))
    assert controller.running
    assert controller.reported_speed_kph == pytest.approx(2.4)


async def test_a_command_with_no_reply_gives_up_instead_of_hanging(monkeypatch) -> None:
    controller, machine = await connected()
    monkeypatch.setattr("trendmill.treadmill.controller.RESPONSE_TIMEOUT_S", 0.05)

    async def silent(payload: bytes) -> None:
        machine.written.append(payload)

    machine.write = silent  # type: ignore[method-assign]
    await asyncio.wait_for(controller.start_belt(), timeout=2.0)
    assert "did not reply" in controller.last_error


async def test_a_dropped_link_mid_command_is_reported_as_a_failed_link() -> None:
    controller, machine = await connected()

    async def gone(payload: bytes) -> None:
        raise ConnectionError("device disconnected")

    machine.write = gone  # type: ignore[method-assign]
    with pytest.raises(TreadmillError, match="did not accept"):
        await controller.start_belt()
    assert controller.state is ConnectionState.FAILED
    assert not controller.can_control


async def test_the_simulated_belt_ramps_rather_than_jumping() -> None:
    controller, machine = await connected()
    await controller.begin_session()
    await controller.set_speed(6.0)
    machine.tick(1.0)
    assert 0 < machine.belt_kph < 6.0
    for _ in range(10):
        machine.tick(1.0)
    assert machine.belt_kph == pytest.approx(6.0)


async def test_the_log_keeps_the_frames_in_both_directions() -> None:
    controller, _ = await connected()
    await controller.start_belt()
    lines = controller.recent_log()
    assert any(line["direction"] == "out" and "Start belt" in line["text"] for line in lines)
    assert any(line["direction"] == "in" and "Accepted" in line["text"] for line in lines)
    assert all(line["hex"] is None or line["hex"] == line["hex"].upper() for line in lines)


def _data_frame(kph: float) -> bytes:
    """Flags 0x0000: instantaneous speed only, with bit 0 clear."""
    return (0x0000).to_bytes(2, "little") + round(kph * 100).to_bytes(2, "little")


async def test_a_belt_coasting_down_after_stop_does_not_look_like_a_restart() -> None:
    """Found in the browser: Stop, then the ramp-down frames flipped it back to running.

    A treadmill takes several seconds to halt, so the frames right after a stop still
    carry a moving belt. Reading those as "someone started it" put the belt back into
    running and wrote a phantom condition at the old speed into the live session.
    """
    controller, _ = await connected()
    await controller.begin_session()
    await controller.set_speed(4.0)
    await controller.stop_belt()

    for kph in (2.8, 1.4, 0.4):  # coasting down
        controller._on_notify(ftms.TREADMILL_DATA, _data_frame(kph))
        assert not controller.running

    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(0.0))
    assert not controller.running
    # And once it has genuinely halted, a belt started at the machine is seen again.
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(2.0))
    assert controller.running


async def test_a_stop_at_the_console_also_survives_the_coast_down() -> None:
    controller, machine = await connected()
    await controller.start_belt()
    machine.press_stop_on_the_console()
    controller._on_notify(ftms.TREADMILL_DATA, _data_frame(1.9))
    assert not controller.running
