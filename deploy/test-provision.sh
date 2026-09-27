#!/usr/bin/env bash
# Runs provision.sh against a clean Debian 13 in Docker, and checks the console
# it installs actually serves.
#
# This is the part of the deployment that can be tested away from the hardware:
# packages, users, device rules, the Python environment, and the console coming
# up and answering. It deliberately cannot test the USB board, Bluetooth, the
# touch panel or the kiosk — see docs/deployment.md, "What is verified".
#
#   ./deploy/test-provision.sh            Debian 13 (the reference image)
#   ./deploy/test-provision.sh ubuntu:24.04
set -euo pipefail

IMAGE="${1:-debian:13}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker info >/dev/null 2>&1 || {
    echo "Docker is not running. Start Docker Desktop and try again." >&2; exit 1; }

[ -f "$ROOT/frontend/dist/index.html" ] || {
    echo "No built UI — run: (cd frontend && npm run build)" >&2; exit 1; }

echo "==> Provisioning $IMAGE"
docker run --rm -i \
    -v "$ROOT:/release:ro" \
    -e DEBIAN_FRONTEND=noninteractive \
    "$IMAGE" bash -s <<'SCRIPT'
set -euo pipefail

# The bind mount is read-only and provision.sh writes nothing to it, but it also
# rsyncs from it — so copy first, exactly as unpacking a tarball would.
apt-get update -qq && apt-get install -y -qq rsync >/dev/null
mkdir -p /tmp/release
rsync -a --exclude='node_modules' --exclude='.git' --exclude='.venv' \
      --exclude='dist/*.tar.gz' /release/ /tmp/release/

/tmp/release/deploy/provision.sh --no-kiosk --no-services

echo
echo "==> Checking what was installed"
fail() { echo "FAIL: $*" >&2; exit 1; }

id trendmill >/dev/null                        || fail "no trendmill user"
getent group trendmill >/dev/null              || fail "no trendmill group"
[ -f /etc/udev/rules.d/99-trendmill.rules ]    || fail "udev rule not installed"
[ -f /etc/dbus-1/system.d/trendmill-bluetooth.conf ] || fail "bluetooth policy not installed"
[ -f /etc/trendmill/trendmill.env ]            || fail "settings file not installed"
[ -L /opt/trendmill/current ]                  || fail "current symlink missing"
[ -d /var/lib/trendmill/sessions ]             || fail "data directory missing"
[ -x /opt/trendmill/current/backend/.venv/bin/trendmill ] || fail "console not installed"
[ -f /opt/trendmill/current/frontend/dist/index.html ]    || fail "UI not installed"

# The rules must name the board, not some other device.
grep -q '413d' /etc/udev/rules.d/99-trendmill.rules || fail "udev rule does not match the board"
grep -q 'LIBINPUT_IGNORE_DEVICE' /etc/udev/rules.d/99-trendmill.rules \
    || fail "the board's HID interface is not ignored"

BIN=/opt/trendmill/current/backend/.venv/bin/trendmill
"$BIN" --version >/dev/null                    || fail "the console will not run"
echo "    version: $("$BIN" --version)"
echo "    python:  $(/opt/trendmill/current/backend/.venv/bin/python --version)"

echo
echo "==> Starting the console as the trendmill user, exactly as the service does"
# shellcheck disable=SC1091
set -a; . /etc/trendmill/trendmill.env; set +a
install -d -o trendmill -g trendmill /var/lib/trendmill
setpriv --reuid=trendmill --regid=trendmill --clear-groups \
    "$BIN" serve --data-dir "$TRENDMILL_DATA_DIR" --host 127.0.0.1 --port 8080 \
    --source sim --treadmill sim --log-level info > /tmp/console.log 2>&1 &

for i in $(seq 1 45); do
    if curl -sf -o /dev/null http://127.0.0.1:8080/api/status; then break; fi
    [ "$i" = 45 ] && { echo "--- console log ---"; cat /tmp/console.log; fail "console never answered"; }
    sleep 1
done

STATUS="$(curl -s http://127.0.0.1:8080/api/status)"
echo "$STATUS" | grep -q '"state": *"streaming"' || { echo "$STATUS" | head -c 400; fail "not streaming"; }
echo "    /api/status: streaming"

# The UI is served, not just the API: a blank screen in the clinic is as bad as
# a dead backend, and it is the half that depends on paths being right.
curl -sf http://127.0.0.1:8080/ | grep -qi '<title>' || fail "the UI is not being served"
echo "    the UI is served"

# And the treadmill half works end to end inside the appliance.
curl -sf -XPOST http://127.0.0.1:8080/api/treadmill/connect >/dev/null || fail "treadmill connect failed"
curl -s http://127.0.0.1:8080/api/treadmill | grep -q '"connected": *true' || fail "treadmill not connected"
echo "    treadmill control works"

echo
echo "PASS"
SCRIPT
