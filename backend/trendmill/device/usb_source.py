"""Reads the load-cell board over USB, exactly as `graph.py` does.

Interface 1 is vendor-specific (class 0xFF), so no operating-system driver claims
it: on macOS and Linux alike the backend opens it from user space. Interface 0 is
a HID boot keyboard; it is never touched.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import usb.backend.libusb1
import usb.core
import usb.util

from trendmill.device.base import LinkState, StateChange, StateSink, Transfer, TransferSink
from trendmill.height.link import HeightUnavailable
from trendmill.logs import get_logger, log_event
from trendmill.protocol.constants import (
    PACKET_SIZE,
    USB_COMMAND_ENDPOINT,
    USB_DATA_ENDPOINT,
    USB_DATA_INTERFACE,
    USB_PRODUCT_ID,
    USB_VENDOR_ID,
)

log = get_logger("usb")

HEX_DUMP_TRANSFERS = 5


def libusb_backend() -> Any:
    """libusb from the `libusb-package` wheel if present, else the system library."""
    try:
        import libusb_package

        backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        if backend is not None:
            return backend
    except ImportError:
        pass
    return usb.backend.libusb1.get_backend()


def describe(dev: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "vid": f"{dev.idVendor:04x}",
        "pid": f"{dev.idProduct:04x}",
        "bcd_device": f"{dev.bcdDevice:04x}",
        "bus": getattr(dev, "bus", None),
        "address": getattr(dev, "address", None),
    }
    for key, index in (("manufacturer", dev.iManufacturer), ("product", dev.iProduct),
                       ("serial", dev.iSerialNumber)):
        try:
            info[key] = usb.util.get_string(dev, index) if index else None
        except (usb.core.USBError, ValueError, NotImplementedError):
            info[key] = None
    return info


class UsbSource:
    name = "usb"

    def __init__(
        self,
        vid: int = USB_VENDOR_ID,
        pid: int = USB_PRODUCT_ID,
        interface: int = USB_DATA_INTERFACE,
        endpoint: int = USB_DATA_ENDPOINT,
        command_endpoint: int = USB_COMMAND_ENDPOINT,
        read_timeout_ms: int = 200,
        max_consecutive_timeouts: int = 25,
        retry_s: float = 1.0,
    ) -> None:
        self._vid = vid
        self._pid = pid
        self._interface = interface
        self._endpoint = endpoint
        self._command_endpoint = command_endpoint
        self._timeout_ms = read_timeout_ms
        self._max_timeouts = max_consecutive_timeouts
        self._retry_s = retry_s
        self._segment = 0
        self.timeouts = 0
        #: The claimed device, published for `send`. Written by the reader thread
        #: and read by the event loop, so every touch takes the lock below.
        self._device: Any = None
        self._device_lock = threading.Lock()

    def send(self, payload: bytes) -> None:
        """Writes one command frame to the board's bulk OUT endpoint.

        Blocking, and called from a worker thread rather than the event loop.
        The lock keeps it from racing the reader's teardown on unplug — libusb
        will happily write to a handle that is being released, and the crash
        lands in the reader thread where it is hardest to explain.
        """
        with self._device_lock:
            dev = self._device
            if dev is None:
                raise HeightUnavailable(
                    "The board is not connected, so the command cannot be sent."
                )
            written = dev.write(self._command_endpoint, payload, timeout=self._timeout_ms)
        if written != len(payload):
            raise OSError(f"short command write: {written} of {len(payload)} bytes")

    def run(self, sink: TransferSink, on_state: StateSink, stop: threading.Event) -> None:
        backend = libusb_backend()
        if backend is None:
            log_event(log, logging.ERROR, "usb.no_backend", "libusb could not be loaded")
            on_state(StateChange(LinkState.STOPPED, "libusb could not be loaded"))
            return
        announced_waiting = False
        while not stop.is_set():
            dev = usb.core.find(idVendor=self._vid, idProduct=self._pid, backend=backend)
            if dev is None:
                if not announced_waiting:
                    log_event(log, logging.INFO, "usb.waiting",
                              f"Waiting for the board {self._vid:04x}:{self._pid:04x}")
                    on_state(StateChange(LinkState.WAITING, "Board not found; is it plugged in?"))
                    announced_waiting = True
                stop.wait(self._retry_s)
                continue
            announced_waiting = False
            try:
                self._stream(dev, sink, on_state, stop)
            except usb.core.USBError as error:
                log_event(log, logging.WARNING, "usb.disconnected", f"USB link lost: {error}",
                          errno=getattr(error, "errno", None))
                on_state(StateChange(LinkState.DISCONNECTED, str(error), segment=self._segment))
            except Exception as error:  # never let the reader thread die silently
                log.exception("Unexpected USB reader failure", extra={"event": "usb.reader_failed",
                                                                       "fields": {}})
                on_state(StateChange(LinkState.DISCONNECTED, repr(error), segment=self._segment))
            finally:
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
            stop.wait(self._retry_s)
        on_state(StateChange(LinkState.STOPPED, "Reader stopped"))

    def _stream(self, dev: Any, sink: TransferSink, on_state: StateSink, stop: threading.Event) -> None:
        try:
            dev.get_active_configuration()
        except usb.core.USBError:
            dev.set_configuration()
        try:
            if dev.is_kernel_driver_active(self._interface):
                dev.detach_kernel_driver(self._interface)
        except (NotImplementedError, usb.core.USBError):
            pass  # macOS has no detach and binds no driver to a vendor-class interface
        usb.util.claim_interface(dev, self._interface)
        with self._device_lock:
            self._device = dev

        self._segment += 1
        info = describe(dev)
        log_event(log, logging.INFO, "usb.connected",
                  f"Board connected: {info.get('manufacturer')} {info.get('product')}",
                  segment=self._segment, **info)
        on_state(StateChange(LinkState.STREAMING, "Streaming", device=info, segment=self._segment))

        consecutive_timeouts = 0
        dumped = 0
        try:
            while not stop.is_set():
                try:
                    raw = dev.read(self._endpoint, PACKET_SIZE, timeout=self._timeout_ms)
                except usb.core.USBTimeoutError:
                    consecutive_timeouts += 1
                    self.timeouts += 1
                    if consecutive_timeouts >= self._max_timeouts:
                        raise usb.core.USBError(
                            f"no data for {consecutive_timeouts * self._timeout_ms} ms"
                        ) from None
                    continue
                arrival = time.monotonic_ns()
                consecutive_timeouts = 0
                data = bytes(raw)
                if dumped < HEX_DUMP_TRANSFERS:
                    dumped += 1
                    log_event(log, logging.INFO, "usb.rx_hex", f"rx[{dumped}] {data.hex(' ')}",
                              length=len(data), segment=self._segment)
                sink(Transfer(arrival_ns=arrival, data=data, segment=self._segment))
        finally:
            try:
                with self._device_lock:
                    self._device = None
                usb.util.release_interface(dev, self._interface)
            except Exception:
                pass
