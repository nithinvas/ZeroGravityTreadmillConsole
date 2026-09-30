// Shapes of what the backend sends. Kept in one file so a renamed field is one edit;
// generating these from the backend's OpenAPI schema is planned (design, section 10).

export type LinkState = "waiting" | "streaming" | "disconnected" | "stopped";

export interface Channel {
  name: "TL" | "TR" | "BR" | "BL";
  last: number | null;
  mean: number | null;
  min: number | null;
  max: number | null;
  std: number | null;
  noise: number | null;
}

export interface StreamWarning {
  code: string;
  message: string;
}

export interface Counters {
  transfers: number;
  bytes: number;
  samples: number;
  short_transfers: number;
  out_of_range: number;
  timeouts: number;
  reconnects: number;
  queue_overflows: number;
}

export interface RecordingStatus {
  id: string;
  label: string;
  started_at: string;
  elapsed_s: number;
  transfers: number;
  segments: number;
}

export interface Snapshot {
  app: { version: string; source: string; nominal_rate_hz: number };
  link: {
    state: LinkState;
    detail: string;
    device: Record<string, string | number | null>;
    segment: number;
    since_s: number;
  };
  stream: {
    rate_hz: number | null;
    packets_per_s: number | null;
    session_rate_hz: number | null;
    elapsed_s: number;
    sample_period_us: number;
    last_data_age_s: number | null;
    max_queue_depth: number;
    counters: Counters;
  };
  channels: Channel[];
  warnings: StreamWarning[];
  recording: RecordingStatus | null;
  calibration: { status: CalibrationState; message: string; method: string | null; in_use: string };
  weight: Weight | null;
  capture_ready: boolean;
  simulator: "walking" | "static" | "empty" | null;
  treadmill: TreadmillState;
  height: HeightState;
  session: SessionLive | null;
}

export interface HeightState {
  /** False when the console was started with --height none. */
  available: boolean;
  backend: "usb" | "sim" | null;
  /** Until the deck has found its end stops, no absolute height means anything. */
  homed: boolean;
  moving: boolean;
  /** Homing ends at a switch, not after a known distance: no meaningful countdown. */
  homing: boolean;
  /** 0…1 through the current move. A timer, not a measurement. */
  progress: number;
  seconds_left: number;
  /** What the console asked for. The mechanism reports nothing back. */
  target_mm: number | null;
  min_mm: number;
  max_mm: number;
  step_mm: number;
  can_move: boolean;
  locked_by_session: boolean;
  last_error: string;
}

export interface TreadmillLimits {
  min_speed_kph: number;
  max_speed_kph: number;
  speed_step_kph: number;
  min_incline_percent: number;
  max_incline_percent: number;
  incline_step_percent: number;
}

export interface TreadmillState {
  /** False when the console was started with --treadmill none. */
  available: boolean;
  backend: "ble" | "sim" | null;
  state: "idle" | "connecting" | "ready" | "failed";
  detail: string;
  device_name: string;
  connected: boolean;
  has_control: boolean;
  running: boolean;
  can_start: boolean;
  can_stop: boolean;
  /** False while the belt is stopped: it has no speed until Start brings it up. */
  can_change_speed: boolean;
  safety_key_pulled: boolean;
  /** What the console asked for; the belt lags this while the motor ramps. */
  target_speed_kph: number | null;
  reported_speed_kph: number | null;
  target_incline_percent: number | null;
  reported_incline_percent: number | null;
  limits: TreadmillLimits;
  session_start_speed_kph: number;
  last_error: string;
}

export interface GaitLive {
  state: "idle" | "walking" | "running";
  cadence_spm: number | null;
  step_length_m: number | null;
  stride_length_m: number | null;
  confidence: "high" | "medium" | "low" | "unavailable" | null;
  prompt: string | null;
  steps_total: number;
  steps_accepted: number;
  front_kg: number;
  amplitude_kg: number;
}

export interface SessionDetails {
  patient_name: string;
  patient_id: string;
  issue: string;
  tester: string;
  speed_kph: number;
  activity: string;
  body_weight_kg: number | null;
  bws_percent: number | null;
  incline_percent: number | null;
  notes: string;
}

export interface Condition {
  id: number;
  start_s: number;
  /** null while the belt was stopped — the treadmill has no 0 km/h. */
  speed_kph: number | null;
  activity: string;
  bws_percent: number | null;
  incline_percent: number | null;
  note: string;
}

export interface StepRow {
  time_s: number;
  side: "L" | "R";
  step_time_s: number;
  step_length_m: number | null;
  stride_time_s: number | null;
  stride_length_m: number | null;
  speed_kph: number | null;
  confidence: string;
  accepted: boolean;
  transition: boolean;
  running: boolean;
  condition_id: number;
  reasons: string[];
}

export interface SessionLive {
  id: string;
  details: SessionDetails;
  elapsed_s: number;
  condition: Condition;
  conditions: number;
  gait: GaitLive;
  walking_s: number;
  distance_m: number;
  recent_steps: StepRow[];
}

export interface Spread {
  median: number | null;
  q1: number | null;
  q3: number | null;
}

export interface Block {
  condition: Condition;
  steps_total: number;
  steps_accepted: number;
  transitions: number;
  low_confidence: number;
  unavailable: number;
  running_steps: number;
  cadence_spm: Spread;
  step_length_m: Spread;
  stride_length_m: Spread;
}

export interface SessionSummary {
  blocks: Block[];
  steps_total: number;
  steps_accepted: number;
  walking_s: number;
  distance_m: number;
  main_condition_id: number | null;
}

export interface SessionRow {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  patient_name: string | null;
  patient_id: string | null;
  issue: string | null;
  tester: string | null;
  activity: string | null;
  duration_s: number | null;
  walking_s: number | null;
  distance_m: number | null;
  steps_accepted: number | null;
  conditions: number | null;
  speeds: string | null;
  main_cadence: number | null;
  main_step_length: number | null;
  main_stride_length: number | null;
}

export interface SessionReport {
  meta: {
    id: string;
    status: string;
    details: SessionDetails;
    started_at: string;
    finished_at: string | null;
    duration_s: number;
    closing_notes: string;
    conditions: Condition[];
    calibration: Profile;
    device: Record<string, string>;
    gait_engine: { version: string };
    app_version: string;
    /** The deck height this session ran at, when the mechanism reported one. */
    height_mm: number | null;
  };
  summary: SessionSummary | null;
  steps: StepRow[];
  trace: { time_s: number[]; tl_kg: number[]; tr_kg: number[]; br_kg: number[]; bl_kg: number[]; total_kg: number[] };
}

export type CalibrationState = "ok" | "missing" | "firmware_mismatch";

export interface Weight {
  live_kg: number;
  average_kg: number;
  std_kg: number;
  stable: boolean;
  cells_kg: [number, number, number, number];
  raw: [number, number, number, number];
  window_s: number;
}

export interface Profile {
  zeros: number[];
  counts_per_kg: number[];
  method: string;
  created_at: string;
  firmware_bcd: string | null;
  known_weight_kg: number | null;
  note: string;
}

export interface DefaultsInfo {
  present: boolean;
  path: string;
  zeros?: number[];
  counts_per_kg?: number[];
  firmware_bcd?: string | null;
  saved_at?: string;
  note?: string;
}

export interface CalibrationInfo {
  status: CalibrationState;
  message: string;
  in_use: "defaults" | "custom" | "none";
  active: Profile | null;
  defaults: DefaultsInfo;
  history: Profile[];
}

export interface Capture {
  means: number[];
  stds: number[];
  samples: number;
  covered_s: number;
  stable: boolean;
}

export interface Solved {
  counts_per_kg: number[];
  kind: "per_cell" | "shared";
  method: string;
}

export interface RecordingMeta {
  id: string;
  label: string;
  started_at: string;
  finished_at: string | null;
  duration_s: number | null;
  transfers: number;
}

export interface LogEntry {
  ts: string;
  level: "debug" | "info" | "warning" | "error";
  component: string;
  event: string;
  msg: string;
  [key: string]: unknown;
}
