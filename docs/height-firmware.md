# Belt height: the firmware

The console's side is built and tested. So is the height controller's
(`tools/main.c`) — rewritten to take commands, with its logic verified on a
desktop:

```bash
./tools/test/run.sh        # 13 checks: framing, direction, limits, aborts
```

The original is preserved beside it as `tools/main.c.orig`.

**What still has to be done before a real deck moves:**

1. **The load-cell board's relay** (section 1) — nothing forwards USB to UART yet.
   This is the remaining blocker.
2. **Verify `DIR_UP`** in `tools/main.c`. It is inferred from the old
   `move_to_home()`, not measured. With the deck near the bottom, send a small
   `MOVE_TO` and check it rises before trusting anything larger.
3. **Enable USART2's global interrupt in CubeMX** (NVIC tab) and regenerate, so
   `USART2_IRQHandler()` exists. Without it nothing is ever received.

---

## 1. The path a command takes

There are **two microcontrollers**, and the one that lifts the deck has no USB:

```
console ──USB bulk OUT 0x02──▶ load-cell board ──UART──▶ height controller
 (N150)      (existing cable)     (WCH, 413d:2107)   115200 8N1   (STM32)
```

The second hop exists now. **The first does not** — that is the blocker.

### On the load-cell board

Interface 1 already declares bulk OUT endpoint **0x02**; nothing reads it. It
needs to:

1. Read from endpoint 0x02.
2. Forward the bytes, unchanged, out of a UART wired to the height controller's
   USART2 (already configured: 115200, 8N1, no flow control).

Nothing else. No parsing, no buffering beyond a frame — a dumb relay is easier to
get right and keeps the protocol in one place. **The load-cell stream on 0x82
must not be disturbed**: it is a 64-byte packet every 4 ms, and a relay that
blocks the main loop will show up immediately as dropped transfers in the
console's health line.

### On the height controller

Done. `MX_USART2_UART_Init` used to run with nothing ever reading the UART;
there is now an interrupt-driven receive path that assembles 8-byte frames,
resynchronises on the magic, ignores retransmits, and hands moves to the main
loop — while acting on `STOP` immediately, in interrupt context, because a move
already running is exactly what it has to reach.

## 2. The frame

Eight bytes, little-endian. `backend/trendmill/height/protocol.py` is the
reference implementation, and its tests are worth reading as a spec.

| offset | size | field |
| --- | --- | --- |
| 0 | 2 | magic, `'H' 'T'` (0x48 0x54) |
| 2 | 1 | opcode |
| 3 | 1 | sequence, wraps at 256 |
| 4 | 4 | parameter, int32 — millimetres, or 0 |

| opcode | name | parameter | meaning |
| --- | --- | --- | --- |
| 0x01 | `MOVE_TO` | height in mm | Drive to an absolute height, measured from the home switch |
| 0x02 | `HOME` | 0 | Seek the limit switches; that position becomes zero |
| 0x03 | `STOP` | 0 | Abandon the current move, decelerate, stop |

Resynchronise on the magic if the stream is ever joined mid-frame. USB CRCs every
packet and the UART hop is short, so there is no checksum; add one if the link
proves noisy in practice.

Ignore a frame whose sequence equals the previous one — that is a retransmit, and
acting on it twice would move the deck twice.

## 3. What was wrong, and what was changed

These were the problems in the original. All are fixed in `tools/main.c`; each
has a test in `tools/test/test_firmware.c` that fails against the old
behaviour.

### 3.1 `move_motor` never set direction — it could only drive one way

`move_to_home()` sets both DIR pins low (toward home) and nothing sets them
again. `move_motor` pulses `STEP_PULSE_*` without touching `STEP_DIR_*`, so after
a homing run it drives *further into* the end stops.

The fix is a direction decision from the current position:

```c
static int32_t current_height_mm = -1;   /* -1 = unknown, must home first */

int32_t delta_mm = (int32_t)target_height - current_height_mm;
GPIO_PinState dir = (delta_mm > 0) ? GPIO_PIN_SET : GPIO_PIN_RESET;
HAL_GPIO_WritePin(STEP_DIR_1_GPIO_Port, STEP_DIR_1_Pin, dir);
HAL_GPIO_WritePin(STEP_DIR_2_GPIO_Port, STEP_DIR_2_Pin, dir);
```

(Confirm which level is "up" on the hardware — the constant above is a guess.)

### 3.2 `move_motor` was relative, but written as if it were absolute

```c
total_pulses  = target_height * PULSES_PER_MM;
travel_pulses = total_pulses - OFFSET;
```

That travels `target_height` millimetres *from wherever the deck happens to be*.
It is only an absolute move if the deck is at home and homing has just run — and
homing is commented out at both call sites (lines 397 and 461).

So today `move_motor(60)` means "move 58 mm in the current direction", not "go to
60 mm". The console assumes absolute, which is the safer contract: **the distance
must come from the difference against a tracked position.**

```c
travel_pulses = (uint32_t)abs(delta_mm) * PULSES_PER_MM;
```

and after a completed move, `current_height_mm = target_height;`.

### 3.3 Nothing tracked position, and nothing reported it

There is no `current_height` anywhere. After power-on the deck's position is
unknown, and it stays unknown — which is why the console refuses every height
command until `HOME` has run.

Keep `current_height_mm` in the firmware, set it to `MIN_HEIGHT` when homing
completes, and update it after each move.

### 3.4 A move could not be interrupted — including by the limit switches

`accelerate_motor`, `cruise_motor` and `decelerate_motor` are `while` loops full
of busy-waits. A full-travel move is roughly **47 seconds** during which the MCU
does nothing else: no UART, so `STOP` cannot arrive; and although the limit
switch interrupts still fire, `HAL_GPIO_EXTI_Falling_Callback` only sets
`home_reached_*`, which nothing in the move loops reads.

**The deck will keep driving into a hard stop.** This is the most serious item
here. The loops need a check each pulse:

```c
if (abort_requested || limit_hit_in_travel_direction()) {
    decelerate_motor(...);   /* or stop outright at a limit */
    current_height_mm = -1;  /* position is now unknown */
    return;
}
```

with `abort_requested` set from the UART receive interrupt on `STOP`.

### 3.5 No travel limits in firmware

20–750 mm is enforced only by the console. The firmware should clamp too — the
host is one cable away from being unplugged mid-command, and a corrupted
parameter should not reach the motors. `MAX_HOME_STEPS` (74 800 pulses = 748 mm)
suggests the travel is already known to the firmware author.

### 3.6 Smaller things

- **`stepper_delay_us` takes `uint16_t` but callers pass `uint32_t`.** Fine at
  present speeds (max 2500 µs), but a slower `START_SPEED` would silently wrap.
- **`move_to_home` has no failure path.** If it exits on `MAX_HOME_STEPS` without
  both switches, it returns as though it succeeded. It should report that.
- **`OFFSET` (2 mm) is subtracted from every move**, not just the first one after
  homing. If it exists to back off the switch, it belongs in the homing routine.
- **TIM6 prescaler 15 assumes a 16 MHz clock** for 1 µs ticks. It is HSI with no
  PLL, so that holds — worth a comment, as a clock change would alter every speed
  in the profile.

## 4. How it behaves now

* **Nothing moves at power-on.** The position is unknown until `HOME` runs, and
  a height command before that is refused rather than measured from a datum
  that does not exist.
* **`HOME`** crawls down to the switches, calls that zero, then lifts to 20 mm
  so that "homed" means a height the console can name. A run that never finds
  both switches leaves the position unknown instead of reporting success.
* **`MOVE_TO`** is absolute: the distance is the difference against the tracked
  position, the direction pins are set from its sign, and the target is clamped
  to 20–750 mm in the firmware as well as the console.
* **`STOP`** is handled in the receive interrupt and polled on every pulse, so
  it reaches a move already in progress. The speed is ramped down rather than
  cut, because dropping 2000 pulses/s to nothing loses steps — and a lost step
  is a tracked position that no longer matches the deck.
* **A limit switch closing during a descent** stops the move and resets the
  datum to zero. It is the last thing between the motors and a mechanical stop.
* **Position survives an interrupted move**, because it is updated per pulse.
  The console still asks for a re-home after a stop, because *it* cannot know
  how far the deck got — which section 5 would fix.

## 5. What the console cannot do until the firmware reports back

Right now every height the console shows is **what it asked for**, and "moving"
is a timer that mirrors the firmware's motion profile
(`protocol.move_seconds`). The UI says so plainly rather than implying a
measurement.

The firmware now *sends* that status: an 8-byte frame, opcode `0x81`, byte 3 the
state (0 unknown, 1 idle, 2 moving, 3 homing) and the parameter the height in mm
(−1 when unknown), emitted whenever the state changes. It goes out of USART2, so
a USB-serial adapter on the bench shows it today.

What is missing is the path back: the relay is one-way, and the load-cell
board's bulk IN endpoint already carries the 64-byte sample stream, which must
not be disturbed. A second IN endpoint, or a distinguishable frame on the
existing one, would let the console show the real position, know when a move
genuinely finished, detect a stall, and drop its re-home-after-stop rule. Worth
doing before clinical use; not needed to start testing.

## 6. Testing the firmware before the relay exists

The relay is the blocker, but it is not in the way of testing this board. Wire a
USB-serial adapter to USART2 — TX to RX, RX to TX, ground to ground, 115200 8N1
— and drive it directly:

```bash
uv run --with pyserial ./tools/height-command.py --port /dev/tty.usbserial-0001 home
uv run --with pyserial ./tools/height-command.py --port /dev/tty.usbserial-0001 move 300
uv run --with pyserial ./tools/height-command.py --port /dev/tty.usbserial-0001 stop
```

It also prints the status frames coming back, so you can watch the board's own
view of where the deck is. `--dry-run` shows the bytes without an adapter, and
`bytes` prints the whole protocol:

```
HOME                   48 54 02 01 00 00 00 00
STOP                   48 54 03 01 00 00 00 00
MOVE_TO 300 mm         48 54 01 01 2C 01 00 00
```

**Do the first move with the deck near the bottom and nothing on it**, to
confirm `DIR_UP` before trusting a large one.

## 7. Testing the console without the hardware

The whole workflow — homing, the ±10 mm buttons, typing a height, the progress
while it travels, the refusals — runs against a simulated mechanism:

```bash
./run.sh --source sim --treadmill sim --height sim
```

The simulator implements this protocol exactly (`SimulatedHeightMechanism`), so
if the firmware matches the table in section 2, it will behave the same way.
