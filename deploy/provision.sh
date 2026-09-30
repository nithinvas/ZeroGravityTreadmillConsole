#!/usr/bin/env bash
# Turns a clean Debian 13 or Ubuntu 24.04 install into a TreadMill appliance.
#
#   sudo ./deploy/provision.sh
#
# Idempotent: running it again upgrades the installed release and leaves
# everything else alone. Recorded sessions, calibration and the settings file are
# never touched, so a re-run is safe on a unit that is already in clinical use.
#
# What it does, in order: packages, users, the USB rule that makes the board
# readable, Bluetooth access, the release under /opt/treadmill, the two services,
# and the kiosk. It prints a verification list at the end.
set -euo pipefail

# ---------------------------------------------------------------- settings

APP_ROOT=/opt/treadmill
DATA_DIR=/var/lib/treadmill
CONFIG=/etc/treadmill/treadmill.env
SERVICE_USER=treadmill
KIOSK_USER=kiosk
PORT=8080

RELEASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WITH_KIOSK=1
WITH_SERVICES=1
WITH_TAILSCALE=0
TAILSCALE_KEY=""
PYTHON_VERSION=3.12

usage() {
    cat <<'EOF'
Usage: sudo ./deploy/provision.sh [options]

  --no-kiosk       Install the backend only, without the touch-screen kiosk.
                   Use this on a headless unit, or to service one over SSH.
  --no-services    Install everything but do not touch systemd. Used by the
                   container test, where there is no init to talk to.
  --with-tailscale Install Tailscale and a connectivity watchdog, so the machine
                   can be reached and recovered from anywhere. FOR DEVELOPMENT
                   UNITS ONLY -- a clinic install must not pass this: it is a
                   permanent inbound path to a machine holding patient records,
                   and the watchdog will reboot the machine to restore it.
  --tailscale-key K  Authenticate unattended with this auth key. Without it,
                   `tailscale up` prints a URL to open in a browser.
  --port N         Port the console listens on (default 8080, localhost only).
  --release-dir D  Install from D instead of the directory this script is in.
  -h, --help       This text.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-kiosk) WITH_KIOSK=0 ;;
        --with-tailscale) WITH_TAILSCALE=1 ;;
        --tailscale-key) TAILSCALE_KEY="$2"; WITH_TAILSCALE=1; shift ;;
        --no-services) WITH_SERVICES=0 ;;
        --port) PORT="$2"; shift ;;
        --release-dir) RELEASE_DIR="$(cd "$2" && pwd)"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[ "$(id -u)" = 0 ] || { echo "Run this with sudo." >&2; exit 1; }
[ -f "$RELEASE_DIR/backend/pyproject.toml" ] || {
    echo "No backend/ in $RELEASE_DIR — is this the release directory?" >&2; exit 1; }

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }

RELEASE_VERSION="$(cat "$RELEASE_DIR/VERSION" 2>/dev/null || sed -n 's/^__version__ = "\(.*\)"/\1/p' \
    "$RELEASE_DIR/backend/treadmill/__init__.py")"
TARGET="$APP_ROOT/releases/$RELEASE_VERSION"

# Read in a subshell: /etc/os-release defines VERSION, ID and more, and sourcing
# it here would quietly overwrite this script's own variables.
OS_ID="$(. /etc/os-release && printf '%s' "${ID:-unknown}")"
OS_NAME="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-this machine}")"

step "TreadMill $RELEASE_VERSION onto $OS_NAME"

# True when apt has a version it can actually install, not merely a name it knows.
installable() { apt-get install -s -qq "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- packages

step "Installing packages"
export DEBIAN_FRONTEND=noninteractive
PACKAGES=(ca-certificates curl rsync libusb-1.0-0 bluez dbus udev)
if [ "$WITH_KIOSK" = 1 ]; then
    PACKAGES+=(cage seatd fonts-dejavu-core)
    # Chromium is a snap on Ubuntu and a deb on Debian. The deb is what the kiosk
    # wants: a snap cannot see a Wayland socket owned by another confined app
    # without extra interfaces, and the appliance has no reason to carry snapd.
    if installable chromium; then
        PACKAGES+=(chromium)
    elif installable chromium-browser; then
        PACKAGES+=(chromium-browser)
    else
        echo "WARNING: no Chromium package available; the kiosk will not start." >&2
        echo "         See docs/deployment.md, section 'Ubuntu'." >&2
    fi
fi
apt-get update -qq
apt-get install -y -qq "${PACKAGES[@]}"
note "installed: ${PACKAGES[*]}"

# Wireless firmware. Which package is needed depends on the card, and that varies
# between units of the same model — the first appliance shipped with a Realtek
# radio (0bda:b85b) where the specification said Intel. Rather than guess, install
# whichever of the candidates this machine can actually get. On Debian these live
# in non-free-firmware, which a minimal install may not have enabled.
#
# Never fatal: a console with no radio still records over USB. But the treadmill
# will be unreachable, so a missing one is worth saying out loud.
FIRMWARE_FOUND=0
for fw in firmware-realtek firmware-iwlwifi firmware-atheros; do
    if installable "$fw"; then
        apt-get install -y -qq "$fw" && { note "installed: $fw"; FIRMWARE_FOUND=1; }
    fi
done
if [ "$FIRMWARE_FOUND" = 0 ]; then
    note "no wireless firmware package was available. If Bluetooth does not work,"
    note "add 'non-free-firmware' to your apt sources and re-run this script."
fi

# uv owns the Python: the distributions ship different versions (3.13 on Debian
# 13, 3.12 on Ubuntu 24.04) and the appliance must run exactly what was tested.
if ! command -v uv >/dev/null 2>&1; then
    step "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh
fi
note "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# Where uv puts the interpreter it downloads. This must NOT be the default
# (~/.local/share/uv, i.e. /root/... when run under sudo): the virtualenv records
# an absolute path to its base interpreter, and the service runs as an
# unprivileged user who cannot read anything under /root. The service then dies
# at startup with "No module named 'encodings'", which says nothing about the
# real cause.
export UV_PYTHON_INSTALL_DIR="$APP_ROOT/python"
install -d -m 0755 "$APP_ROOT" "$APP_ROOT/python"

# ------------------------------------------------- migrate from the old name

# The project was called "TrendMill" until the spelling was fixed. A machine
# provisioned before that has its data, config, service and user under the old
# name. Move them rather than starting empty: /var/lib/trendmill holds the
# calibration and every recorded session, and losing those means recalibrating
# a treadmill with a known weight and telling a clinic their records are gone.
OLD_APP=/opt/trendmill
OLD_DATA=/var/lib/trendmill
OLD_CONFIG=/etc/trendmill/trendmill.env

if [ -d "$OLD_DATA" ] || [ -d "$OLD_APP" ] || [ -f "$OLD_CONFIG" ]; then
    step "Migrating from the old 'trendmill' name"

    # Stop the old services first: moving a data directory out from under a
    # running console would leave half-written session files.
    for unit in trendmill-core trendmill-kiosk; do
        if systemctl list-unit-files "$unit.service" >/dev/null 2>&1 &&
           [ -f "/etc/systemd/system/$unit.service" ]; then
            systemctl disable --now "$unit.service" >/dev/null 2>&1 || true
            rm -f "/etc/systemd/system/$unit.service"
            note "removed $unit.service"
        fi
    done
    systemctl daemon-reload 2>/dev/null || true

    if [ -d "$OLD_DATA" ] && [ ! -d "$DATA_DIR" ]; then
        mv "$OLD_DATA" "$DATA_DIR"
        note "moved $OLD_DATA -> $DATA_DIR (sessions and calibration)"
    elif [ -d "$OLD_DATA" ]; then
        # Both exist: merge without overwriting anything already in the new one.
        cp -rn "$OLD_DATA/." "$DATA_DIR/" 2>/dev/null || true
        note "merged $OLD_DATA into $DATA_DIR; the old copy is left in place"
    fi

    if [ -f "$OLD_CONFIG" ] && [ ! -f "$CONFIG" ]; then
        install -d -m 0755 /etc/treadmill
        # The settings keep their values; only their names change.
        sed 's/^TRENDMILL_/TREADMILL_/; s#/opt/trendmill#/opt/treadmill#g; s#/var/lib/trendmill#/var/lib/treadmill#g' \
            "$OLD_CONFIG" > "$CONFIG"
        chmod 0640 "$CONFIG"
        note "carried $OLD_CONFIG over to $CONFIG"
    fi

    rm -f /etc/udev/rules.d/99-trendmill.rules /etc/dbus-1/system.d/trendmill-bluetooth.conf
    rm -rf "$OLD_APP"
    # The old service user owned the data; the new one is created below and the
    # ownership is reset after.
    userdel trendmill 2>/dev/null || true
    groupdel trendmill 2>/dev/null || true
    note "old name removed"
fi

# ---------------------------------------------------------------- users

step "Creating users and directories"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
# Board access comes from this group, granted by the udev rule below.
getent group treadmill >/dev/null || groupadd treadmill
usermod -aG treadmill "$SERVICE_USER"
# BlueZ is reached over D-Bus; membership plus the policy file below is what lets
# the console drive the treadmill without running as root.
getent group bluetooth >/dev/null && usermod -aG bluetooth "$SERVICE_USER"

install -d -o "$SERVICE_USER" -g treadmill -m 0750 "$DATA_DIR" \
    "$DATA_DIR/sessions" "$DATA_DIR/recordings" "$DATA_DIR/calibration" "$DATA_DIR/logs"
# Migrated files still carry the old user's numeric id.
chown -R "$SERVICE_USER":treadmill "$DATA_DIR"
install -d -m 0755 "$APP_ROOT" "$APP_ROOT/releases" /etc/treadmill

# ---------------------------------------------------------------- device rules

step "Installing device rules"
install -m 0644 "$RELEASE_DIR/deploy/udev/99-treadmill.rules" /etc/udev/rules.d/99-treadmill.rules
install -m 0644 "$RELEASE_DIR/deploy/dbus/treadmill-bluetooth.conf" \
    /etc/dbus-1/system.d/treadmill-bluetooth.conf
if command -v udevadm >/dev/null 2>&1 && [ -d /run/udev ]; then
    udevadm control --reload-rules && udevadm trigger --subsystem-match=usb
    note "udev rules reloaded"
else
    note "udev not running here; rules will apply at next boot"
fi

# ---------------------------------------------------------------- the release

step "Installing the release to $TARGET"
rm -rf "$TARGET"
install -d -m 0755 "$TARGET"
rsync -a --exclude='__pycache__' --exclude='.venv' --exclude='.pytest_cache' \
      --exclude='.mypy_cache' --exclude='.ruff_cache' \
      "$RELEASE_DIR/backend" "$RELEASE_DIR/deploy" "$TARGET/"
install -d -m 0755 "$TARGET/frontend"
if [ -d "$RELEASE_DIR/frontend/dist" ]; then
    rsync -a "$RELEASE_DIR/frontend/dist/" "$TARGET/frontend/dist/"
else
    echo "WARNING: no built UI in the release. The API will run; the screen will not." >&2
fi

step "Creating the Python environment"
# --frozen: install exactly the locked versions, never resolve on the appliance.
(cd "$TARGET/backend" && uv sync --frozen --no-dev --python "$PYTHON_VERSION")
chown -R root:treadmill "$TARGET"
# Readable and executable by the service user, never writable by it: the console
# must not be able to modify its own code.
chmod -R a+rX "$TARGET" "$APP_ROOT/python"
ln -sfn "$TARGET" "$APP_ROOT/current"
note "$APP_ROOT/current -> $TARGET"

# ---------------------------------------------------------------- settings

if [ ! -f "$CONFIG" ]; then
    step "Writing $CONFIG"
    install -m 0640 -o root -g treadmill "$RELEASE_DIR/deploy/treadmill.env.example" "$CONFIG"
    sed -i "s/^TREADMILL_PORT=.*/TREADMILL_PORT=$PORT/" "$CONFIG"
else
    note "keeping the existing $CONFIG"
    # A release may add a setting the installed config has never heard of. The
    # unit expands it to an empty string, the console gets an option with no
    # value, and the service dies on start -- so fill in anything missing
    # rather than leaving an upgrade broken.
    added=0
    while IFS= read -r key; do
        if ! grep -q "^${key}=" "$CONFIG"; then
            line="$(grep -m1 "^${key}=" "$RELEASE_DIR/deploy/treadmill.env.example")"
            if [ "$added" = 0 ]; then
                printf '\n# Added by provision.sh for TreadMill %s\n' "$RELEASE_VERSION" >> "$CONFIG"
                added=1
            fi
            printf '%s\n' "$line" >> "$CONFIG"
            note "added missing setting: $line"
        fi
    done < <(grep -oE '^[A-Z_]+=' "$RELEASE_DIR/deploy/treadmill.env.example" | tr -d '=')
fi

# ---------------------------------------------------------------- services

if [ "$WITH_SERVICES" = 0 ]; then
    step "Skipping systemd (--no-services)"
    note "start it by hand with:"
    note "  $TARGET/backend/.venv/bin/treadmill serve --data-dir $DATA_DIR --port $PORT"
    exit 0
fi

step "Installing services"
install -m 0644 "$RELEASE_DIR/deploy/systemd/treadmill-core.service" \
    /etc/systemd/system/treadmill-core.service
systemctl daemon-reload
systemctl enable treadmill-core.service
# restart, not "enable --now": --now starts a stopped service but leaves a
# running one alone, so an upgrade would install the new release and quietly
# carry on serving the old one.
systemctl restart treadmill-core.service

if [ "$WITH_KIOSK" = 1 ]; then
    if ! id -u "$KIOSK_USER" >/dev/null 2>&1; then
        useradd --create-home --shell /usr/sbin/nologin "$KIOSK_USER"
    fi
    # seatd hands the compositor the display and input devices without root.
    usermod -aG video,input,render,seat "$KIOSK_USER" 2>/dev/null || \
        usermod -aG video,input "$KIOSK_USER"
    systemctl enable --now seatd.service 2>/dev/null || true
    install -m 0755 "$RELEASE_DIR/deploy/kiosk/start-kiosk.sh" "$APP_ROOT/start-kiosk.sh"
    install -m 0644 "$RELEASE_DIR/deploy/systemd/treadmill-kiosk.service" \
        /etc/systemd/system/treadmill-kiosk.service
    # Nothing else should own the screen.
    systemctl set-default graphical.target >/dev/null 2>&1 || true
    systemctl disable --now gdm3 lightdm sddm >/dev/null 2>&1 || true
    systemctl daemon-reload
    systemctl enable treadmill-kiosk.service
    # Same again, and it also reloads Chromium onto the new UI.
    systemctl restart treadmill-kiosk.service
fi

# ---------------------------------------------------- remote access (dev only)

if [ "$WITH_TAILSCALE" = 1 ]; then
    step "Installing remote access (development units only)"

    if ! command -v tailscale >/dev/null 2>&1; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    systemctl enable --now tailscaled

    if tailscale status >/dev/null 2>&1; then
        note "already on a tailnet: $(tailscale status --peers=false 2>/dev/null | head -1)"
    elif [ -n "$TAILSCALE_KEY" ]; then
        tailscale up --authkey "$TAILSCALE_KEY" --hostname "$(hostname)" --ssh
        note "authenticated with the supplied key"
    else
        note "run 'tailscale up --ssh' and open the URL it prints to finish."
    fi

    # The Realtek card's power saving is what made this machine unreachable for
    # seconds at a time; on a unit nobody can walk up to, that is not a
    # trade-off worth having.
    cat > /etc/systemd/system/treadmill-wifi-power.service <<'UNIT'
[Unit]
Description=Disable Wi-Fi power saving (keeps a remote machine reachable)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for i in $(ls /sys/class/net | grep "^wl"); do iw dev "$i" set power_save off || true; done'

[Install]
WantedBy=multi-user.target
UNIT
    apt-get install -y -qq iw >/dev/null 2>&1 || true
    systemctl enable --now treadmill-wifi-power.service >/dev/null 2>&1 || true

    install -m 0755 "$RELEASE_DIR/deploy/netwatch.sh" "$APP_ROOT/netwatch.sh"
    install -m 0644 "$RELEASE_DIR/deploy/systemd/treadmill-netwatch.service" \
        /etc/systemd/system/treadmill-netwatch.service
    install -m 0644 "$RELEASE_DIR/deploy/systemd/treadmill-netwatch.timer" \
        /etc/systemd/system/treadmill-netwatch.timer
    systemctl daemon-reload
    systemctl enable --now treadmill-netwatch.timer
    note "watchdog: bounces the network after 20 min offline, reboots after 40"
fi

# ---------------------------------------------------------------- report

step "Done"
systemctl --no-pager --lines=0 status treadmill-core.service || true
cat <<EOF

Check it:

  systemctl status treadmill-core          the console itself
  curl -s localhost:$PORT/api/status | head -c 200
  $TARGET/backend/.venv/bin/treadmill probe     the load-cell board, directly
  journalctl -u treadmill-core -f          live logs

Settings live in $CONFIG (edit, then: systemctl restart treadmill-core).
Sessions, calibration and logs live in $DATA_DIR.

If the board is plugged in, 'treadmill probe' should find 413d:2107 and read
packets. If it finds the device but cannot open it, the udev rule has not been
applied yet — reboot once.
EOF
