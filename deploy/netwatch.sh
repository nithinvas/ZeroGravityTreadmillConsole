#!/usr/bin/env bash
# Keep an unattended machine reachable.
#
# Run from a systemd timer every few minutes. It escalates only as far as it has
# to: check, then nudge the radio, then bounce the network, and only after a
# long, unbroken outage, reboot.
#
# This exists because a machine that loses Wi-Fi after a power cut is gone until
# somebody drives to it. The load-cell measurement does not depend on the
# network at all, so nothing here risks the clinical function -- it is purely
# about the engineer being able to get back in.
#
# Deliberately NOT part of a clinic install: a machine that reboots itself is
# the right trade for a development unit nobody can reach, and the wrong one for
# a unit somebody is standing in front of. provision.sh installs it only with
# --with-tailscale.
set -uo pipefail

STATE=/var/lib/treadmill/.netwatch-failures
# 4 consecutive failures at a 5 minute timer is 20 minutes of no internet before
# the network is bounced; 8 is 40 minutes before the last resort.
BOUNCE_AFTER=4
REBOOT_AFTER=8
# Never reboot a machine that has only just come up: if the network takes a
# while after boot, rebooting again makes a loop that never recovers.
MIN_UPTIME_S=900

log() { logger -t treadmill-netwatch "$*"; echo "$*"; }

online() {
    # Two different things, either of which means we are fine: the internet at
    # large, and the tailnet specifically. Checking only one would bounce a
    # perfectly good link whenever the other end had a bad day.
    curl -sf --max-time 8 -o /dev/null https://tailscale.com/ 2>/dev/null && return 0
    command -v tailscale >/dev/null 2>&1 &&
        tailscale status --json 2>/dev/null | grep -q '"Online": *true' && return 0
    ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 && return 0
    return 1
}

failures=$(cat "$STATE" 2>/dev/null || echo 0)
case "$failures" in ''|*[!0-9]*) failures=0 ;; esac

if online; then
    [ "$failures" -gt 0 ] && log "back online after $failures failed checks"
    echo 0 > "$STATE"
    exit 0
fi

failures=$((failures + 1))
echo "$failures" > "$STATE"
log "no connectivity (failure $failures)"

uptime_s=$(cut -d. -f1 /proc/uptime)

if [ "$failures" -ge "$REBOOT_AFTER" ] && [ "$uptime_s" -gt "$MIN_UPTIME_S" ]; then
    log "still offline after $failures checks — rebooting"
    echo 0 > "$STATE"
    systemctl reboot
    exit 0
fi

if [ "$failures" -ge "$BOUNCE_AFTER" ]; then
    log "bouncing the network"
    for iface in $(ls /sys/class/net | grep -E '^(wl|en)' || true); do
        ip link set "$iface" down 2>/dev/null || true
        sleep 2
        ip link set "$iface" up 2>/dev/null || true
    done
    systemctl restart wpa_supplicant 2>/dev/null || true
    systemctl restart networking 2>/dev/null || true
    # Ask for an address again: bringing the link up does not always renew one.
    for iface in $(ls /sys/class/net | grep -E '^wl' || true); do
        dhclient -r "$iface" 2>/dev/null || true
        dhclient "$iface" 2>/dev/null || true
    done
    systemctl restart tailscaled 2>/dev/null || true
fi
