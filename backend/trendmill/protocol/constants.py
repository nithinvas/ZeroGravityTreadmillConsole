"""Facts about the load-cell board's USB stream.

Sources: the firmware image's USB descriptors (VID/PID, interface 1, EP 0x82) and
the firmware source (`main.c` packs four ADS131M04 channels per nDRDY event, four
events per 64-byte transfer, as little-endian int32).
"""

USB_VENDOR_ID = 0x413D
USB_PRODUCT_ID = 0x2107
USB_DATA_INTERFACE = 1
USB_DATA_ENDPOINT = 0x82
#: Bulk OUT on the same interface. Nothing used it until belt-height control:
#: the board relays whatever arrives here to the height controller's UART.
USB_COMMAND_ENDPOINT = 0x02

PACKET_SIZE = 64
CHANNELS = 4
SAMPLES_PER_PACKET = 4
BYTES_PER_VALUE = 4

# ADS131M04 in 24-bit word mode, sign-extended to int32 by the firmware.
ADC_MIN = -(1 << 23)
ADC_MAX = (1 << 23) - 1

# Physical corner of each ADC channel. Carried over from the old firmware and not
# yet confirmed against the wiring: press one corner at a time to check.
CHANNEL_NAMES = ("TL", "TR", "BR", "BL")

# The rate the firmware team quoted. The firmware sets OSR 16384, which gives
# 976.5625 Sa/s only with a 32 MHz ADC clock; a standard 8.192 MHz clock gives
# 250 Sa/s. Treat this as a starting guess: every judgement uses the observed rate.
DEFAULT_NOMINAL_RATE_HZ = 976.5625
