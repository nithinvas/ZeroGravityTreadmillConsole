"""Command line: `trendmill serve | probe | inspect | logs`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from trendmill import __version__
from trendmill.protocol.constants import (
    CHANNEL_NAMES,
    DEFAULT_NOMINAL_RATE_HZ,
    PACKET_SIZE,
    USB_DATA_ENDPOINT,
    USB_DATA_INTERFACE,
    USB_PRODUCT_ID,
    USB_VENDOR_ID,
)


def default_data_dir() -> Path:
    env = os.environ.get("TRENDMILL_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if platform.system() == "Linux" and os.access("/var/lib/trendmill", os.W_OK):
        return Path("/var/lib/trendmill")
    return Path.home() / "TrendMill"


def default_ui_dir() -> Path | None:
    env = os.environ.get("TRENDMILL_UI_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "frontend" / "dist", here.parent / "ui"):
        if (candidate / "index.html").exists():
            return candidate
    return None


# ---------------------------------------------------------------- serve


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from trendmill.api.app import create_app
    from trendmill.logs import setup_logging
    from trendmill.service import Console, ConsoleConfig

    data_dir = Path(args.data_dir).expanduser()
    setup_logging(data_dir / "logs", level=logging.getLevelName(args.log_level.upper()))
    source = make_source(args)
    console = Console(
        source,
        ConsoleConfig(data_dir=data_dir, nominal_rate_hz=args.nominal_rate),
        make_treadmill(args),
        make_height(args, source),
    )
    ui_dir = default_ui_dir()
    if ui_dir is None:
        print("note: no built UI found; run `npm run build` in frontend/ (API still works)",
              file=sys.stderr)
    app = create_app(console, ui_dir)
    print(f"TrendMill {__version__}: open http://{args.host}:{args.port}  (data: {data_dir})",
          file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


def make_source(args: argparse.Namespace) -> Any:
    if args.source == "usb":
        from trendmill.device.usb_source import UsbSource
        return UsbSource()
    if args.source in ("sim", "sim-bug"):
        from trendmill.device.simulator import SimulatedBoard
        return SimulatedBoard(rate_hz=args.nominal_rate, packing_bug=args.source == "sim-bug")
    if args.source == "replay":
        from trendmill.device.replay import ReplaySource
        if not args.replay:
            raise SystemExit("--replay PATH is required with --source replay")
        return ReplaySource(Path(args.replay).expanduser(), speed=args.speed, loop=args.loop)
    raise SystemExit(f"unknown source {args.source}")


def make_height(args: argparse.Namespace, source: Any) -> Any:
    """Belt-height control: over the board's USB link, simulated, or absent."""
    from trendmill.height.controller import HeightController

    if args.height == "none":
        return HeightController(None)
    if args.height == "sim":
        from trendmill.height.link import SimulatedHeightMechanism
        return HeightController(SimulatedHeightMechanism())
    from trendmill.height.link import UsbHeightLink
    return HeightController(UsbHeightLink(source))


def make_treadmill(args: argparse.Namespace) -> Any:
    """Builds the treadmill controller: the real radio, a simulated machine, or none."""
    from trendmill.treadmill.controller import TreadmillController

    if args.treadmill == "none":
        return TreadmillController(None)
    if args.treadmill == "sim":
        from trendmill.treadmill.link import SimulatedTreadmill
        return TreadmillController(SimulatedTreadmill())
    from trendmill.treadmill.ble_link import BleTreadmillLink
    return TreadmillController(BleTreadmillLink(address=args.treadmill_address))


# ---------------------------------------------------------------- probe


def cmd_probe(args: argparse.Namespace) -> int:
    """Checks the board directly, without the server: identity, endpoints, a few packets."""
    import usb.core
    import usb.util

    from trendmill.device.usb_source import describe, libusb_backend
    from trendmill.protocol.decoder import decode_packet

    backend = libusb_backend()
    if backend is None:
        print("FAIL  libusb could not be loaded")
        return 2
    print("USB devices:")
    board = None
    for dev in usb.core.find(find_all=True, backend=backend):
        info = describe(dev)
        mark = ""
        if dev.idVendor == USB_VENDOR_ID and dev.idProduct == USB_PRODUCT_ID:
            board = dev
            mark = "   <-- load-cell board"
        print(f"  {info['vid']}:{info['pid']}  {info.get('manufacturer') or ''} "
              f"{info.get('product') or ''}{mark}")
    if board is None:
        print(f"\nFAIL  board {USB_VENDOR_ID:04x}:{USB_PRODUCT_ID:04x} not found. "
              "Check the cable, and that the board is powered.")
        return 1

    info = describe(board)
    print(f"\nBoard: bcdDevice {info['bcd_device']}, serial {info.get('serial')}")
    try:
        cfg = board.get_active_configuration()
    except usb.core.USBError:
        board.set_configuration()
        cfg = board.get_active_configuration()
    for intf in cfg:
        print(f"  interface {intf.bInterfaceNumber}: class 0x{intf.bInterfaceClass:02x}")
        for ep in intf:
            kind = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}[ep.bmAttributes & 3]
            print(f"    endpoint 0x{ep.bEndpointAddress:02x} {kind}, max packet {ep.wMaxPacketSize}")

    try:
        if board.is_kernel_driver_active(USB_DATA_INTERFACE):
            board.detach_kernel_driver(USB_DATA_INTERFACE)
    except (NotImplementedError, usb.core.USBError):
        pass
    usb.util.claim_interface(board, USB_DATA_INTERFACE)
    transfers: list[tuple[int, bytes]] = []
    start = time.monotonic()
    try:
        while len(transfers) < args.count and time.monotonic() - start < args.seconds:
            try:
                data = bytes(board.read(USB_DATA_ENDPOINT, PACKET_SIZE, timeout=500))
                transfers.append((time.monotonic_ns(), data))
            except usb.core.USBTimeoutError:
                continue
    finally:
        usb.util.release_interface(board, USB_DATA_INTERFACE)
        usb.util.dispose_resources(board)

    if not transfers:
        print(f"\nFAIL  no data from endpoint 0x{USB_DATA_ENDPOINT:02x} in {args.seconds:g} s")
        return 1
    print(f"\nFirst transfers from endpoint 0x{USB_DATA_ENDPOINT:02x}:")
    for i, (_, data) in enumerate(transfers[:3], start=1):
        print(f"  rx[{i}] {len(data)} bytes: {data.hex(' ')}")
        if len(data) == PACKET_SIZE:
            for s, quad in enumerate(decode_packet(data), start=1):
                values = "  ".join(f"{n}={v:>9}" for n, v in zip(CHANNEL_NAMES, quad, strict=True))
                print(f"        sample {s}: {values}")
    return report_stream(transfers, args.nominal_rate)


def report_stream(transfers: list[tuple[int, bytes]], nominal_rate: float) -> int:
    """Prints the verdicts shared by `probe` and `inspect`. Returns an exit code."""
    from trendmill.protocol.decoder import decode_packet, in_adc_range

    sizes = [len(d) for _, d in transfers]
    good = [(t, d) for t, d in transfers if len(d) == PACKET_SIZE]
    quads = [q for _, d in good for q in decode_packet(d)]
    ok = True
    print(f"\n{len(transfers)} transfers, {len(quads)} samples")
    short = sum(1 for n in sizes if n != PACKET_SIZE)
    print(("PASS  " if short == 0 else "FAIL  ") + f"transfer size: {short} not 64 bytes")
    ok &= short == 0
    if len(good) >= 2:
        span_s = (good[-1][0] - good[0][0]) / 1e9
        rate = (len(good) - 1) * 4 / span_s if span_s > 0 else float("nan")
        deviation = abs(rate - nominal_rate) / nominal_rate
        verdict = "PASS  " if deviation <= 0.02 else "WARN  "
        print(f"{verdict}rate: {rate:.2f} samples/s per channel "
              f"({rate / 4:.2f} transfers/s); configured nominal {nominal_rate:g}")
    bad = sum(1 for q in quads for v in q if not in_adc_range(v))
    print(("PASS  " if bad == 0 else "FAIL  ") + f"ADC range: {bad} values outside 24 bits")
    ok &= bad == 0
    if len(quads) >= 8:
        means = [statistics.fmean(q[c] for q in quads) for c in range(4)]
        noise = statistics.median(
            statistics.fmean(abs(b[c] - a[c]) for a, b in zip(quads, quads[1:], strict=False))
            for c in range(4)
        )
        spread = max(means) - min(means)
        identical = spread <= 5 * noise + 2
        print(("FAIL  " if identical else "PASS  ") + "channels distinct: " + ", ".join(
            f"{n} mean {m:,.0f}" for n, m in zip(CHANNEL_NAMES, means, strict=True)))
        if identical:
            print("      All four channels carry the same signal: the firmware is sending one "
                  "channel only.\n      Check main.c: payload_index must advance by 4, not 1.")
        ok &= not identical
    return 0 if ok else 1


# ---------------------------------------------------------------- inspect


def cmd_inspect(args: argparse.Namespace) -> int:
    from trendmill.device.replay import segment_files
    from trendmill.storage.raw_format import header_of, iter_records, sha256_of

    path = Path(args.path).expanduser()
    files = segment_files(path)
    if not files:
        print(f"no recording at {path}")
        return 2
    code = 0
    for file in files:
        header = header_of(file)
        print(f"{file.name}: board {header.vid:04x}:{header.pid:04x} bcd {header.bcd_device:04x}, "
              f"nominal {header.nominal_rate_hz:g} Hz")
        sidecar = file.with_suffix(file.suffix + ".sha256")
        if sidecar.exists():
            expected = sidecar.read_text(encoding="utf-8").split()[0]
            print(("PASS  " if expected == sha256_of(file) else "FAIL  ") + "checksum")
        code |= report_stream(list(iter_records(file)), header.nominal_rate_hz)
    return code


# ---------------------------------------------------------------- logs

LEVEL_ORDER = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def cmd_logs(args: argparse.Namespace) -> int:
    path = Path(args.data_dir).expanduser() / "logs" / "trendmill.jsonl"
    minimum = LEVEL_ORDER[args.level]
    colour = sys.stdout.isatty()
    colours = {"debug": "\033[37m", "info": "\033[36m", "warning": "\033[33m", "error": "\033[31m"}

    def show(line: str) -> None:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return
        if LEVEL_ORDER.get(e.get("level", "info"), 20) < minimum:
            return
        if args.component and e.get("component") != args.component:
            return
        extras = " ".join(f"{k}={v}" for k, v in e.items()
                          if k not in {"ts", "level", "component", "event", "msg"})
        level = e.get("level", "").upper()
        if colour:
            level = f"{colours.get(e.get('level', ''), '')}{level:<7}\033[0m"
        print(f"{e.get('ts', '')[11:23]} {level:<7} {e.get('component', ''):<8} "
              f"{e.get('event', ''):<28} {e.get('msg', '')}" + (f"  [{extras}]" if extras else ""),
              flush=True)

    if not path.exists():
        print(f"no log file yet at {path}; start `trendmill serve` first")
        return 1
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines[-args.lines:]:
            show(line)
        if not args.follow:
            return 0
        while True:
            line = f.readline()
            if line:
                show(line)
                continue
            time.sleep(0.2)
            if path.stat().st_size < f.tell():  # rotated
                f.close()
                return cmd_logs(args)


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendmill", description="TrendMill gait console")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the console (API + UI)")
    serve.add_argument("--source", choices=["usb", "sim", "sim-bug", "replay"], default="usb")
    serve.add_argument("--replay", help="recording directory or .tmraw file (with --source replay)")
    serve.add_argument("--speed", type=float, default=1.0, help="replay speed; 0 = as fast as possible")
    serve.add_argument("--loop", action="store_true", help="replay repeatedly")
    serve.add_argument("--nominal-rate", type=float, default=DEFAULT_NOMINAL_RATE_HZ,
                       help="expected samples/s per channel (default %(default)s)")
    serve.add_argument("--data-dir", default=str(default_data_dir()))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--height", choices=["usb", "sim", "none"], default="usb",
                       help="belt-height control: over the board's USB link, simulated, or none")
    serve.add_argument("--treadmill", choices=["ble", "sim", "none"], default="ble",
                       help="treadmill control: real Bluetooth, a simulated machine, or none")
    serve.add_argument("--treadmill-address",
                       help="connect to this Bluetooth address instead of the first treadmill found")
    serve.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    serve.set_defaults(func=cmd_serve)

    probe = sub.add_parser("probe", help="check the board directly and print verdicts")
    probe.add_argument("--count", type=int, default=500, help="transfers to read")
    probe.add_argument("--seconds", type=float, default=5.0, help="give up after this long")
    probe.add_argument("--nominal-rate", type=float, default=DEFAULT_NOMINAL_RATE_HZ)
    probe.set_defaults(func=cmd_probe)

    inspect = sub.add_parser("inspect", help="check a recording")
    inspect.add_argument("path")
    inspect.set_defaults(func=cmd_inspect)

    logs = sub.add_parser("logs", help="show or follow the log")
    logs.add_argument("--follow", "-f", action="store_true")
    logs.add_argument("--level", choices=list(LEVEL_ORDER), default="info")
    logs.add_argument("--component")
    logs.add_argument("--lines", "-n", type=int, default=50)
    logs.add_argument("--data-dir", default=str(default_data_dir()))
    logs.set_defaults(func=cmd_logs)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
