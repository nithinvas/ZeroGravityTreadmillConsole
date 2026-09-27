#!/usr/bin/env python3
"""Send belt-height commands straight to the STM32 over a serial adapter.

The console normally reaches the height controller through the load-cell
board's USB link, and that relay does not exist yet. This bypasses it: wire a
USB-serial adapter to USART2 (TX->RX, RX->TX, GND->GND, 115200 8N1) and drive
the firmware directly, so it can be tested and `DIR_UP` confirmed before any
work happens on the load-cell board.

    ./tools/height-command.py --port /dev/tty.usbserial-0001 home
    ./tools/height-command.py --port /dev/tty.usbserial-0001 move 300
    ./tools/height-command.py --port /dev/tty.usbserial-0001 stop
    ./tools/height-command.py --port /dev/tty.usbserial-0001 watch

`--dry-run` prints the bytes without needing an adapter, which is also the
easiest way to see exactly what the console puts on the wire.

Needs pyserial (`uv run --with pyserial ./tools/height-command.py ...`), except
for --dry-run, which needs nothing.
"""

from __future__ import annotations

import argparse
import sys
import time

MAGIC = b"HT"
OP_MOVE_TO, OP_HOME, OP_STOP, OP_STATUS = 0x01, 0x02, 0x03, 0x81
STATES = {0: "unknown (needs homing)", 1: "idle", 2: "moving", 3: "homing"}


def frame(opcode: int, param: int = 0, seq: int = 1) -> bytes:
    return MAGIC + bytes([opcode, seq & 0xFF]) + int(param).to_bytes(4, "little", signed=True)


def show(label: str, data: bytes) -> None:
    print(f"{label:<22} {data.hex(' ').upper()}")


def decode_status(data: bytes) -> str | None:
    if len(data) < 8 or data[0:2] != MAGIC or data[2] != OP_STATUS:
        return None
    mm = int.from_bytes(data[4:8], "little", signed=True)
    where = "position unknown" if mm < 0 else f"{mm} mm"
    return f"{STATES.get(data[3], data[3])}, {where}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["home", "move", "stop", "watch", "bytes"])
    parser.add_argument("height_mm", nargs="?", type=int, help="for 'move'")
    parser.add_argument("--port", help="serial device, e.g. /dev/tty.usbserial-0001")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seq", type=int, default=1, help="sequence byte; change it between repeats")
    parser.add_argument("--dry-run", action="store_true", help="print the bytes, send nothing")
    args = parser.parse_args()

    if args.command == "bytes":
        # The whole protocol, as it goes on the wire.
        show("HOME", frame(OP_HOME, 0, args.seq))
        show("STOP", frame(OP_STOP, 0, args.seq))
        for mm in (20, 100, 300, 455, 750):
            show(f"MOVE_TO {mm} mm", frame(OP_MOVE_TO, mm, args.seq))
        return 0

    if args.command == "move" and args.height_mm is None:
        parser.error("'move' needs a height in millimetres")

    payload = {
        "home": frame(OP_HOME, 0, args.seq),
        "stop": frame(OP_STOP, 0, args.seq),
        "move": frame(OP_MOVE_TO, args.height_mm or 0, args.seq),
        "watch": b"",
    }[args.command]

    if payload:
        show(f"{args.command} ->", payload)
    if args.dry_run:
        return 0
    if not args.port:
        parser.error("--port is required (or use --dry-run)")

    try:
        import serial
    except ImportError:
        print("pyserial is not installed. Try:\n"
              "  uv run --with pyserial ./tools/height-command.py ...", file=sys.stderr)
        return 2

    with serial.Serial(args.port, args.baud, timeout=0.5) as link:
        if payload:
            link.write(payload)
        # Read status frames back for a while: the firmware reports its state
        # whenever it changes, and a move takes tens of seconds.
        print("listening for status (ctrl-C to stop)...")
        buffer = bytearray()
        deadline = time.monotonic() + (600 if args.command == "watch" else 90)
        try:
            while time.monotonic() < deadline:
                buffer += link.read(64)
                while len(buffer) >= 8:
                    if buffer[0:2] != MAGIC:
                        del buffer[0]        # resynchronise, exactly as the board does
                        continue
                    text = decode_status(bytes(buffer[:8]))
                    if text:
                        print(f"  {time.strftime('%H:%M:%S')}  {text}")
                    del buffer[:8]
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
