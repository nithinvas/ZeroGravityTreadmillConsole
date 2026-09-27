"""The real Bluetooth Low Energy link, over bleak.

bleak is the only place the host's radio stack appears: CoreBluetooth on the Mac,
BlueZ on the N100. Both are driven through the same calls, so the console behaves
the same on the bench and on the appliance.

bleak is imported lazily inside the methods. A console with no Bluetooth (a test
machine, a CI runner, a Pi without a radio) must still start and stream over USB,
so a missing or broken bleak is a treadmill that cannot connect — never a server
that will not boot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from trendmill.logs import get_logger, log_event
from trendmill.treadmill import ftms
from trendmill.treadmill.link import Notify, TreadmillUnavailable

if TYPE_CHECKING:
    from bleak import BleakClient

log = get_logger("ble")

SCAN_TIMEOUT_S = 12.0
CONNECT_TIMEOUT_S = 20.0


def _forward(characteristic: str, on_notify: Notify) -> Callable[[Any, bytearray], None]:
    """Binds one characteristic's UUID into the callback bleak hands the data to.

    bleak reports the sending characteristic object, not its UUID, and the object
    differs per backend — binding the UUID here keeps the controller platform-free.
    """

    def handler(_sender: Any, data: bytearray) -> None:
        on_notify(characteristic, bytes(data))

    return handler


class BleTreadmillLink:
    """Scans for the Fitness Machine Service and drives the first machine found.

    Filtering by service UUID rather than by name means any FTMS treadmill works,
    not one particular model.
    """

    name = "ble"

    def __init__(self, address: str | None = None, scan_timeout_s: float = SCAN_TIMEOUT_S) -> None:
        #: A fixed address pins the console to one machine in a room with several.
        self.address = address
        self.scan_timeout_s = scan_timeout_s
        self._client: BleakClient | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self, on_notify: Notify) -> str:
        try:
            from bleak import BleakClient, BleakScanner
            from bleak.exc import BleakError
        except ImportError as error:  # pragma: no cover - depends on the host
            raise TreadmillUnavailable(
                "The Bluetooth library is not installed on this machine, so the "
                "treadmill cannot be controlled. Recording over USB still works."
            ) from error

        device: Any
        if self.address:
            device = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout_s)
            missing = f"No treadmill answered at {self.address}."
        else:
            log_event(log, logging.INFO, "ble.scanning",
                      "Scanning for the Fitness Machine Service (0x1826)")
            device = await BleakScanner.find_device_by_filter(
                lambda _, adv: ftms.FITNESS_MACHINE_SERVICE in [u.lower() for u in adv.service_uuids],
                timeout=self.scan_timeout_s,
            )
            missing = (
                "No treadmill found. Check it is switched on, within range, and not "
                "already connected to a phone or tablet."
            )
        if device is None:
            raise TreadmillUnavailable(missing)

        label = getattr(device, "name", None) or getattr(device, "address", "Treadmill")
        log_event(log, logging.INFO, "ble.connecting", f"Connecting to {label}", device=str(label))
        client = BleakClient(device, timeout=CONNECT_TIMEOUT_S)
        try:
            await client.connect()
        except BleakError as error:
            raise ConnectionError(f"Could not connect to {label}: {error}") from error
        except OSError as error:  # pragma: no cover - radio off, permission denied
            raise TreadmillUnavailable(
                f"The Bluetooth radio refused the connection: {error}. Check Bluetooth "
                "is switched on and this application is allowed to use it."
            ) from error

        if client.services.get_service(ftms.FITNESS_MACHINE_SERVICE) is None:
            await client.disconnect()
            raise ConnectionError(f"{label} does not expose the Fitness Machine Service.")

        self._client = client
        for characteristic in ftms.NOTIFY_CHARACTERISTICS:
            try:
                # bleak writes the 0x2902 descriptor itself, and picks indication
                # over notification where the characteristic asks for it — which
                # the control point does, because a dropped command reply matters.
                await client.start_notify(characteristic, _forward(characteristic, on_notify))
            except (BleakError, ValueError) as error:
                log_event(log, logging.WARNING, "ble.subscribe_failed",
                          f"Could not subscribe to {characteristic}: {error}")
        return str(label)

    async def write(self, payload: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise ConnectionError("The treadmill is not connected.")
        # Write with response: the machine's reply is how a refused command becomes
        # visible instead of silently doing nothing.
        await client.write_gatt_char(ftms.CONTROL_POINT, payload, response=True)

    async def read(self, characteristic: str) -> bytes | None:
        client = self._client
        if client is None or not client.is_connected:
            return None
        try:
            return bytes(await client.read_gatt_char(characteristic))
        except Exception as error:  # a machine may simply not have the characteristic
            log_event(log, logging.DEBUG, "ble.read_failed",
                      f"Could not read {characteristic}: {error}")
            return None

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as error:  # pragma: no cover - the link is going away anyway
            log_event(log, logging.DEBUG, "ble.disconnect_failed", f"Disconnect failed: {error}")
