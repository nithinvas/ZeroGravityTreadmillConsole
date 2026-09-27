// Shared test fixtures, so a new field on a shared shape is one edit rather than
// one per test file.

import type { HeightState, TreadmillState } from "./types";

/** Homed and idle: the normal state before a session. */
export const HEIGHT_READY: HeightState = {
  available: true, backend: "sim", homed: true, moving: false, homing: false, progress: 1,
  seconds_left: 0,
  target_mm: 300, min_mm: 20, max_mm: 750, step_mm: 10,
  can_move: true, locked_by_session: false, last_error: "",
};

/** Fresh from power-on: position unknown until it finds its end stops. */
export const HEIGHT_NOT_HOMED: HeightState = {
  ...HEIGHT_READY, homed: false, target_mm: null, can_move: false,
};

/** A treadmill that is present but not connected: the console's starting state. */
export const NO_TREADMILL: TreadmillState = {
  available: true,
  backend: "ble",
  state: "idle",
  detail: "Not connected",
  device_name: "",
  connected: false,
  has_control: false,
  running: false,
  can_start: false,
  can_stop: false,
  can_change_speed: false,
  safety_key_pulled: false,
  target_speed_kph: null,
  reported_speed_kph: null,
  target_incline_percent: null,
  reported_incline_percent: null,
  limits: {
    min_speed_kph: 1, max_speed_kph: 12, speed_step_kph: 0.1,
    min_incline_percent: 0, max_incline_percent: 15, incline_step_percent: 1,
  },
  session_start_speed_kph: 1,
  last_error: "",
};

/** Connected, in control, belt running at the speed given. */
export function drivingAt(kph: number, incline = 0): TreadmillState {
  return {
    ...NO_TREADMILL,
    state: "ready",
    detail: "Connected to Treadmill",
    device_name: "Treadmill",
    connected: true,
    has_control: true,
    running: true,
    can_start: false,
    can_stop: true,
    can_change_speed: true,
    target_speed_kph: kph,
    reported_speed_kph: kph,
    target_incline_percent: incline,
    reported_incline_percent: incline,
  };
}
