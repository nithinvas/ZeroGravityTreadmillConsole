# TrendMill Console

Backend and touch UI for the zero-gravity treadmill: reads the ADS131M04 load-cell
board over USB, records every transfer, shows live diagnostics, and (from
milestone M2) computes cadence, step length and stride length. Built to run on
the N100 mini PC; runs the same way on a Mac. The design is in
[docs/design.md](docs/design.md).

**Status.** Done: USB streaming, decoding, per-sample timing, health checks, raw
recording, replay, live logs, the firmware test screen, calibration and weight
measurement. Next: the gait engine (M2) and treadmill control over Bluetooth (M3b).

## Quick start on a Mac

Needs [uv](https://docs.astral.sh/uv/) and Node 20+. libusb comes bundled with the
Python dependencies, so Homebrew is not needed.

```bash
./run.sh
```

That installs dependencies, builds the UI if needed, and starts the console
reading the real board. Open <http://127.0.0.1:8080>.

Without the board:

```bash
./run.sh --source sim
```

```bash
./run.sh --source sim-bug
```

Both can be combined with `--treadmill sim` to exercise a whole session,
belt and all, with no hardware attached:

```bash
./run.sh --source sim --treadmill sim
```

The second reproduces the firmware packing bug (`payload_index += 1`), so you
can see the warning it raises.

## Testing the firmware

1. **Check the board directly**, without the server:

   ```bash
   cd backend && uv run trendmill probe
   ```

   It lists USB devices, the board's interfaces and endpoints, hex-dumps the
   first transfers, and prints PASS/FAIL for transfer size, sample rate, ADC range
   and whether the four channels are distinct. A FAIL on "channels distinct"
   means the firmware is sending one channel four times.

2. **Run the console** (`./run.sh`) and open the page.
   - With the deck empty, tap **Zero all**.
   - Press each corner in turn. The tile in the same place on screen should
     respond most. If a different tile lights up, the channel-to-corner wiring
     differs from the assumed ch0–ch3 = TL, TR, BR, BL.
   - Read **Samples/s per channel** against the nominal 976.5625. The firmware
     sets OSR 16384, which gives 976.5625 only with a 32 MHz ADC clock and 250
     with the standard 8.192 MHz one; the observed number settles it. If it is
     250, restart with `./run.sh --nominal-rate 250`.

3. **Record** a labelled test from the Recording panel, then check it:

   ```bash
   cd backend && uv run trendmill inspect ~/TrendMill/recordings/<recording-id>
   ```

   ```bash
   ./run.sh --source replay --replay ~/TrendMill/recordings/<recording-id>
   ```

## Treadmill control (Bluetooth)

Speed and incline are driven over Bluetooth Low Energy, using the standard
Fitness Machine Service (FTMS) — the same protocol, opcodes and hardware quirks
the Android app uses, ported to Python over
[bleak](https://bleak.readthedocs.io/) (CoreBluetooth on the Mac, BlueZ on the
N100). The load cells stay on USB; the two links are independent and neither
blocks the other.

The first time the console scans, macOS asks for Bluetooth permission for the
terminal running it.

```bash
./run.sh                      # real treadmill over Bluetooth (default)
./run.sh --treadmill sim      # a simulated treadmill, for testing without one
./run.sh --treadmill none     # no belt control at all; speed is typed in
./run.sh --treadmill-address <UUID>   # pin one machine in a room with several
```

**How a session drives the belt**

1. *Check connection* on the treadmill panel scans for the Fitness Machine
   Service and requests control. Until the machine grants control it obeys
   nothing, so this is reported rather than assumed.
2. **Start session** starts the belt at **1.0 km/h**. So does the **Start**
   button, every time — never at whatever the belt was doing before the last
   stop, because the belt is stopped exactly when somebody is stepping on or off
   it.
3. **+ / −** move speed (1.0–12.0 km/h) and incline (0–15%) by the machine's own
   increment. Each change starts a new condition in the report, and **that speed
   is what cadence, step length and stride length are computed from** — there is
   no second number to disagree with the belt.
4. **Start** is greyed while the belt runs and **Stop** while it is stopped,
   following what the machine reports. A belt stopped at its own console, or by
   the safety key, is picked up here.
5. **Ending the session stops the belt** if it is still moving, and forgets the
   session's speed and incline.

A stopped belt has **no speed** — not a speed of zero, which the treadmill's
1–12 km/h range does not contain. The speed buttons are greyed while it is
stopped, the readout shows `—`, and any stretch of a session recorded with the
belt stopped is shown as "belt stopped" with its lengths marked unavailable
rather than computed from a speed the deck no longer had.

Speed is shown twice: the target the console asked for, and what the belt
reports. They differ for a few seconds while the motor ramps, and showing both
is deliberate — reconciling them silently is what made the app's `+` button
stick.

## The touch screen

The appliance has no keyboard, so the console brings up its own: tap any field
and an on-screen keyboard docks at the bottom — a numeric pad for numeric
fields, a full layout for text. It is on by default on a touch screen and off
on a desktop, and the **⌨** button in the top bar overrides either way
(remembered per browser).

## Belt height

The zero-gravity deck raises between **20 and 750 mm**, driven by a second
microcontroller (two steppers, `tools/main.c`). The console sets it **before a
session**, in 10 mm steps or by typing a height, and refuses to move it while one
is recording — the deck must never rise under a patient already walking.

```bash
./run.sh --height sim      # a simulated mechanism, for testing without one
./run.sh --height none     # no height control; the deck is set at the treadmill
```

Commands travel down the load-cell board's USB cable on bulk OUT `0x02`, which
the board relays to the height controller's UART. **Neither firmware does this
yet** — [docs/height-firmware.md](docs/height-firmware.md) specifies the frame
and lists the firmware bugs found reviewing the mechanism's code, including a
`move_motor` that cannot change direction and a move loop that ignores its own
limit switches.

The mechanism reports nothing back, so every height shown is what the console
asked for, and it must be homed after each power-on before any absolute height
means anything. The UI states both rather than implying a measurement.

## Weight and calibration

The **Calibration** tab offers three ways to calibrate. All use the firmware
convention: weight per cell = (raw − zero) ÷ counts per kg, which is negative on this
deck because the raw value falls under load.

| Method | Steps | Result |
| --- | --- | --- |
| Default tested values | Load defaults, capture the empty-deck tare, save | −1,856 counts/kg for every cell, measured in September on this firmware |
| Known weight, one capture | Capture the empty-deck tare; put a known weight anywhere on the deck; calculate; save | One shared coefficient from the change in the sum of all four cells |
| Four corners | Tare, then the same weight over each corner in turn | A coefficient per cell, solved from all four positions together; falls back to shared if the positions are too alike |

Every capture waits 2.3 s and averages the last 2 s, so it only uses readings
taken after the weight was placed. Captures that were still moving are flagged.

The **Weight** tab shows the live weight, a 2-second average, a stable indicator
(standard deviation at most 0.5 kg), and each cell's load and raw value.

Calibrations are kept in `<data>/calibration/` with a history of every previous
one, and survive restarts. Each records the board's firmware version: if the
board later reports a different one, the calibration is flagged, because a
firmware change can rescale the ADC (the September 32,400 vs 1,856 counts/kg problem).

With `--source sim`, a Simulator panel can empty the deck, place a weight at the
centre or a corner, or run a walker, so calibration can be rehearsed without the board.

## Logs

Every component logs structured JSON to `~/TrendMill/logs/trendmill.jsonl`
(`/var/lib/trendmill/logs` on the N100), and to the terminal. The page shows a
live log panel with level and component filters. From a terminal:

```bash
cd backend && uv run trendmill logs -f
```

```bash
cd backend && uv run trendmill logs -f --level warning --component usb
```

A health line every 10 s reports the rate, counters, CPU and memory. Log levels
can be changed while running (`POST /api/logging`), and reset on restart.

## Development

```bash
cd backend && uv run pytest
```

```bash
cd backend && uv run ruff check trendmill tests && uv run mypy trendmill
```

```bash
cd frontend && npm test && npm run build
```

For UI work with hot reload, run the backend (`./run.sh --source sim`) and, in a
second terminal, `cd frontend && npm run dev`, then open <http://127.0.0.1:5173>.

## Deploying on the N100

```bash
./deploy/build-release.sh            # on the Mac: builds, tests, makes a tarball
# copy dist/trendmill-*.tar.gz to the N100, then there:
sudo ./deploy/provision.sh           # packages, users, device rules, services, kiosk
```

`provision.sh` is idempotent: run it again to upgrade, and sessions, calibration
and `/etc/trendmill/trendmill.env` are left alone. The install path is tested on
a clean Debian 13 and Ubuntu 24.04 with `./deploy/test-provision.sh` (needs
Docker).

Full runbook, including BIOS settings, verification and troubleshooting:
**[docs/deployment.md](docs/deployment.md)**.

## Layout

| Path | What |
| --- | --- |
| `backend/trendmill/protocol/` | Packet decoder, sample clock, stream health and the firmware-bug check |
| `backend/trendmill/device/` | Packet sources: USB board, simulator, replay |
| `backend/trendmill/storage/` | Raw recording format (every transfer, untouched) and recorder |
| `backend/trendmill/calibration/` | Profiles and defaults, the four-position solver, storage, live weighing |
| `backend/trendmill/treadmill/` | FTMS protocol, the BLE link, a simulated treadmill, and belt control |
| `backend/trendmill/height/` | Belt-height command frames, the USB command link, a simulated mechanism |
| `tools/main.c` | Height-controller firmware (STM32). `tools/test/run.sh` tests its logic on a desktop |
| `tools/height-command.py` | Sends height commands over a serial adapter, bypassing the USB relay |
| `backend/trendmill/processor.py`, `service.py` | Transfers to samples; the running console |
| `backend/trendmill/api/` | REST, WebSocket live state and logs, UI hosting |
| `backend/trendmill/cli.py` | `trendmill serve`, `probe`, `inspect`, `logs` |
| `frontend/` | React + TypeScript touch UI |
| `deploy/` | Release builder, provisioning script, udev and systemd units, kiosk |
| `docs/design.md` | Phase 1 design |
| `docs/deployment.md` | Installing and servicing the appliance |
| `docs/height-firmware.md` | What the boards must implement for belt-height control |

## Data locations

| | macOS | N100 (Linux) |
| --- | --- | --- |
| Recordings | `~/TrendMill/recordings/` | `/var/lib/trendmill/recordings/` |
| Calibration | `~/TrendMill/calibration/` | `/var/lib/trendmill/calibration/` |
| Logs | `~/TrendMill/logs/` | `/var/lib/trendmill/logs/` and the journal |

Override with `TRENDMILL_DATA_DIR` or `--data-dir`.
