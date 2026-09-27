#!/usr/bin/env bash
# Puts the console on the touch screen and keeps it there.
#
# Cage is a Wayland compositor that runs exactly one application full screen,
# with no desktop, no window chrome and nothing to escape to — which is the whole
# reason it is here rather than a full desktop session with a browser on top.
set -euo pipefail

: "${TREADMILL_HOST:=127.0.0.1}"
: "${TREADMILL_PORT:=8080}"
URL="http://${TREADMILL_HOST}:${TREADMILL_PORT}"

CHROMIUM="$(command -v chromium || command -v chromium-browser || true)"
[ -n "$CHROMIUM" ] || { echo "no chromium found" >&2; exit 1; }

# Wait for the backend rather than showing the patient a connection error.
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "$URL/api/status"; then break; fi
    sleep 1
done

# --kiosk           full screen, no chrome, no way out
# --incognito       nothing about a patient survives a restart
# --noerrdialogs …  never interrupt a session with a browser dialog
# --touch-events    the panel is a touch screen, not a mouse
exec cage -d -- "$CHROMIUM" \
    --kiosk \
    --incognito \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI,Translate \
    --no-first-run \
    --fast \
    --fast-start \
    --touch-events=enabled \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    "$URL"
