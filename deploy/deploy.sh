#!/usr/bin/env bash
# Build, ship and install a release on a clinic machine, in one command.
#
#   ./deploy/deploy.sh zerogravity
#   ./deploy/deploy.sh zerogravity --yes        # no confirmation prompt
#
# Builds (which runs the full test suite and refuses to package a failing
# release), copies, provisions, and then checks the machine actually came back
# up on the new version — because "provisioning finished" and "the new code is
# running" turned out not to be the same thing.
#
# It refuses to upgrade a machine that is mid-session. A restart would save that
# session as "interrupted" and lose the patient's remaining walk.
set -euo pipefail

HOST="${1:-}"
[ -n "$HOST" ] || { echo "usage: $0 <host> [--yes] [--user root]" >&2; exit 2; }
shift

ASSUME_YES=0
USER_AT=root
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --user) USER_AT="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -o ConnectTimeout=15 -o BatchMode=yes -o ServerAliveInterval=15 "${USER_AT}@${HOST}")

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# ---- 1. is it safe to touch this machine right now? ------------------------

step "Checking $HOST"
"${SSH[@]}" true || { echo "Cannot reach $HOST over SSH." >&2; exit 1; }

BEFORE="$("${SSH[@]}" 'readlink /opt/trendmill/current 2>/dev/null || echo none')"
echo "    running now: $(basename "$BEFORE")"

if "${SSH[@]}" 'curl -s --max-time 5 localhost:8080/api/sessions/current' 2>/dev/null \
        | grep -q '"id"'; then
    echo
    echo "REFUSING: a session is recording on $HOST." >&2
    echo "Restarting the console would save it as 'interrupted' and lose the rest" >&2
    echo "of the patient's walk. Upgrade between patients." >&2
    exit 1
fi
echo "    no session recording"

# ---- 2. build ---------------------------------------------------------------

step "Building (runs the full test suite)"
"$ROOT/deploy/build-release.sh" >/tmp/trendmill-build.log 2>&1 || {
    echo "Build or tests failed. Last lines:" >&2
    tail -25 /tmp/trendmill-build.log >&2
    exit 1
}
TARBALL="$(ls -t "$ROOT"/dist/trendmill-*.tar.gz | head -1)"
NAME="$(basename "$TARBALL" .tar.gz)"
echo "    $NAME  ($(du -h "$TARBALL" | cut -f1))"

if [ "$ASSUME_YES" = 0 ]; then
    echo
    read -r -p "Install $NAME on $HOST? [y/N] " reply
    case "$reply" in [yY]*) ;; *) echo "Nothing was changed."; exit 0 ;; esac
fi

# ---- 3. ship and install ----------------------------------------------------

step "Copying to $HOST"
scp -q -o BatchMode=yes -o ConnectTimeout=25 "$TARBALL" "${USER_AT}@${HOST}:/tmp/"
"${SSH[@]}" "cd /tmp && tar -xzf '$NAME.tar.gz'"

step "Provisioning"
"${SSH[@]}" "/tmp/$NAME/deploy/provision.sh" 2>&1 \
    | grep -vE '^ \+|Ignoring unknown extended header' | sed 's/^/    /'

# ---- 4. did it actually take? ----------------------------------------------

step "Verifying"
sleep 5
AFTER="$("${SSH[@]}" 'readlink /opt/trendmill/current')"
[ "$AFTER" != "$BEFORE" ] || {
    echo "The release did not change: still $(basename "$AFTER")" >&2; exit 1; }
echo "    release   $(basename "$AFTER")"

# The running process must be the new one. An install that leaves the old
# process serving is the failure this whole step exists to catch.
RUNNING="$("${SSH[@]}" 'systemctl show -p ExecMainPID --value trendmill-core \
    | xargs -I{} readlink -f /proc/{}/exe 2>/dev/null || true')"
"${SSH[@]}" "systemctl is-active --quiet trendmill-core" \
    || { echo "trendmill-core is not running. journalctl -u trendmill-core -n 50" >&2; exit 1; }
echo "    service   active"

for i in $(seq 1 20); do
    if "${SSH[@]}" 'curl -sf --max-time 5 -o /dev/null localhost:8080/api/status'; then
        break
    fi
    [ "$i" = 20 ] && { echo "The console is not answering on 8080." >&2; exit 1; }
    sleep 2
done

"${SSH[@]}" 'curl -s localhost:8080/api/status' | python3 -c '
import json, sys
s = json.load(sys.stdin)
print(f"    version   {s[\"app\"][\"version\"]}")
print(f"    board     {s[\"link\"][\"state\"]} ({s[\"link\"][\"detail\"] or \"ok\"})")
for w in s.get("warnings", []):
    print(f"    WARNING   {w[\"message\"]}")
'
_ = "$RUNNING"

step "Done"
echo "$HOST is running $(basename "$AFTER")."
echo "Watch it settle with:  ssh ${USER_AT}@${HOST} 'journalctl -u trendmill-core -f'"
