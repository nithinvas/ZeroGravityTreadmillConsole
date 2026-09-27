"""The FTMS wire format, checked against the frames the real treadmill sends."""

from __future__ import annotations

import pytest

from treadmill.belt import ftms


def test_uuids_expand_to_the_full_128_bit_form() -> None:
    assert ftms.FITNESS_MACHINE_SERVICE == "00001826-0000-1000-8000-00805f9b34fb"
    assert ftms.CONTROL_POINT == "00002ad9-0000-1000-8000-00805f9b34fb"


def test_stop_uses_the_parameter_that_actually_stops_the_belt() -> None:
    # The spec sheet says 08 02; the machine accepts it and keeps running.
    assert ftms.stop() == bytes([0x08, 0x01])
    assert ftms.pause() == bytes([0x08, 0x02])


def test_speed_is_hundredths_of_a_kilometre_little_endian() -> None:
    assert ftms.set_speed(1.0) == bytes([0x02, 0x64, 0x00])
    assert ftms.set_speed(12.0) == bytes([0x02, 0xB0, 0x04])
    # 4.7 km/h is 470 = 0x01D6, and must not round to 469 through float error.
    assert ftms.set_speed(4.7) == bytes([0x02, 0xD6, 0x01])


def test_speed_is_clamped_to_the_wire_width() -> None:
    assert ftms.set_speed(-5) == bytes([0x02, 0x00, 0x00])
    assert ftms.set_speed(10_000) == bytes([0x02, 0xFF, 0xFF])


def test_inclination_is_signed_tenths_of_a_percent() -> None:
    assert ftms.set_inclination(15.0) == bytes([0x03, 0x96, 0x00])
    assert ftms.set_inclination(-2.5) == bytes([0x03, 0xE7, 0xFF])


def test_a_response_carries_the_original_opcode_and_the_verdict() -> None:
    response = ftms.parse_response(bytes([0x80, 0x07, 0x01]))
    assert response is not None
    assert response.ok
    assert response.opcode == ftms.OP_START_OR_RESUME
    assert "Start belt" in response.text


def test_control_not_permitted_is_reported_not_swallowed() -> None:
    response = ftms.parse_response(bytes([0x80, 0x02, 0x05]))
    assert response is not None
    assert not response.ok
    assert response.result is ftms.Result.NOT_PERMITTED


@pytest.mark.parametrize("frame", [b"", b"\x80\x07", b"\x00\x07\x01"])
def test_a_frame_that_is_not_a_response_is_rejected(frame: bytes) -> None:
    assert ftms.parse_response(frame) is None


def test_speed_is_present_when_bit_zero_is_clear() -> None:
    # flags 0x0000, speed 3.50 km/h. Reading bit 0 the obvious way loses the field.
    parsed = ftms.parse_treadmill_data(bytes([0x00, 0x00, 0x5E, 0x01]))
    assert parsed is not None
    assert parsed.speed_kph == pytest.approx(3.5)


def test_more_data_set_means_no_instantaneous_speed() -> None:
    parsed = ftms.parse_treadmill_data(bytes([0x01, 0x00, 0x5E, 0x01]))
    assert parsed is not None
    assert parsed.speed_kph is None


def test_inclination_follows_speed_and_is_signed() -> None:
    # flags 0x0008: speed present (bit 0 clear) plus the inclination/ramp pair.
    frame = bytes([0x08, 0x00]) + (250).to_bytes(2, "little") + (-15).to_bytes(
        2, "little", signed=True
    ) + (20).to_bytes(2, "little", signed=True)
    parsed = ftms.parse_treadmill_data(frame)
    assert parsed is not None
    assert parsed.speed_kph == pytest.approx(2.5)
    assert parsed.inclination_percent == pytest.approx(-1.5)
    assert parsed.ramp_angle_degrees == pytest.approx(2.0)


def test_elapsed_time_lands_correctly_past_the_optional_fields() -> None:
    # Speed, distance, energy triple and elapsed time: the layout that shifts by
    # two bytes if any field's width is wrong.
    flags = (1 << 2) | (1 << 7) | (1 << 10)
    frame = (
        flags.to_bytes(2, "little")
        + (500).to_bytes(2, "little")  # 5.00 km/h
        + (1234).to_bytes(3, "little")  # metres
        + (42).to_bytes(2, "little")  # total energy
        + b"\xff\xff"  # energy per hour: not available
        + b"\xff"  # energy per minute: not available
        + (95).to_bytes(2, "little")  # elapsed seconds
    )
    parsed = ftms.parse_treadmill_data(frame)
    assert parsed is not None
    assert parsed.speed_kph == pytest.approx(5.0)
    assert parsed.total_distance_m == 1234
    assert parsed.total_energy_kcal == 42
    assert parsed.elapsed_time_s == 95


def test_a_truncated_frame_gives_up_rather_than_inventing_values() -> None:
    assert ftms.parse_treadmill_data(b"\x00\x00\x5e") is None


def test_machine_status_reports_the_safety_key_as_stopping() -> None:
    status = ftms.parse_machine_status(bytes([0x03]))
    assert status is not None
    assert status.event is ftms.Event.STOPPED_BY_SAFETY_KEY
    assert status.stopped


def test_machine_status_carries_a_changed_target() -> None:
    status = ftms.parse_machine_status(bytes([0x05]) + (450).to_bytes(2, "little"))
    assert status is not None
    assert status.value == pytest.approx(4.5)
    assert not status.stopped


def test_ranges_decode_with_their_own_scales() -> None:
    speed = (100).to_bytes(2, "little") + (1200).to_bytes(2, "little") + (10).to_bytes(2, "little")
    assert ftms.parse_range(speed, 0.01, signed=False) == pytest.approx((1.0, 12.0, 0.1))
    incline = (
        (-100).to_bytes(2, "little", signed=True)
        + (150).to_bytes(2, "little", signed=True)
        + (5).to_bytes(2, "little")
    )
    assert ftms.parse_range(incline, 0.1, signed=True) == pytest.approx((-10.0, 15.0, 0.5))


def test_a_reported_step_of_zero_keeps_the_spec_sheet_step() -> None:
    # A machine claiming a step of 0 would make every increment a no-op.
    limits = ftms.SPEC_SHEET_LIMITS.with_speed_range(1.0, 12.0, 0.0)
    assert limits.speed_step_kph == ftms.SPEC_SHEET_LIMITS.speed_step_kph


def test_stepping_never_leaves_the_machines_range() -> None:
    assert ftms.next_target(11.95, 1, 0.1, 1.0, 12.0) == pytest.approx(12.0)
    assert ftms.next_target(1.0, -1, 0.1, 1.0, 12.0) == pytest.approx(1.0)


def test_repeated_steps_do_not_drift_off_the_grid() -> None:
    value = 1.0
    for _ in range(20):
        value = ftms.next_target(value, 1, 0.1, 1.0, 12.0)
    assert value == pytest.approx(3.0)
    # And the wire value is exactly 300, not 299 through accumulated float error.
    assert ftms.set_speed(value)[1:] == (300).to_bytes(2, "little")
