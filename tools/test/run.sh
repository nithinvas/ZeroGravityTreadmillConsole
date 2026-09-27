#!/usr/bin/env bash
# Compiles the height firmware's logic for the desktop and runs it.
#
# The HAL is stubbed, step pulses are counted rather than driven, and the
# microsecond timer advances on read so the busy-waits return at once. What is
# left is the part that would otherwise only be testable by watching a deck
# move: framing, direction, distance, position tracking, and every reason a
# move should stop early.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d)/test_firmware"
cc -std=c11 -Wall -Wextra -I "$HERE" -o "$OUT" "$HERE/test_firmware.c" -lm
"$OUT"
