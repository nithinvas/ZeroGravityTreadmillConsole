#!/usr/bin/env bash
# Pull everything needed to diagnose a clinic machine, in one command.
#
#   ./deploy/diagnose.sh zerogravity
#   ./deploy/diagnose.sh zerogravity --session 20260919-193116-37b5e3f8
#
# Collects the console's own view of itself, its logs, the journal, the machine's
# health, and the list of recent sessions. With --session it also pulls that
# session's raw USB capture, which is what lets the fault be reproduced at your
# desk instead of guessed at from a description.
#
# Everything lands in diagnostics/<host>-<timestamp>/ and a verdict is printed.
#
# WARNING: what this downloads contains patient names and recordings. The
# diagnostics/ directory is gitignored; treat the contents as clinical records.
set -euo pipefail

HOST="${1:-}"
[ -n "$HOST" ] || { echo "usage: $0 <host> [--session ID] [--user root]" >&2; exit 2; }
shift

SESSION=""
USER_AT=root
while [ $# -gt 0 ]; do
    case "$1" in
        --session) SESSION="$2"; shift ;;
        --user) USER_AT="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/diagnostics/${HOST}-$(date +%Y%m%d-%H%M%S)"
SSH=(ssh -o ConnectTimeout=15 -o BatchMode=yes "${USER_AT}@${HOST}")
REMOTE=/opt/trendmill/current/backend/.venv/bin/trendmill

mkdir -p "$OUT"
echo "Collecting from $HOST into ${OUT#"$ROOT"/}"

grab() {  # grab <file> <command...>
    local into="$1"; shift
    if "${SSH[@]}" "$@" > "$OUT/$into" 2>"$OUT/$into.err"; then
        [ -s "$OUT/$into.err" ] || rm -f "$OUT/$into.err"
        printf '  %-22s %s\n' "$into" "$(wc -c < "$OUT/$into" | tr -d ' ') bytes"
    else
        printf '  %-22s FAILED (see %s.err)\n' "$into" "$into"
    fi
}

# What the console believes about itself, right now. This alone answers most
# questions, which is why it is first.
grab status.json        'curl -s localhost:8080/api/status'
grab calibration.json   'curl -s localhost:8080/api/calibration'
grab treadmill.json     'curl -s localhost:8080/api/treadmill'
grab sessions.json      'curl -s "localhost:8080/api/sessions?limit=25"'

# The app's own structured log, and the journal for anything that went wrong
# before the app's logging existed.
grab trendmill.log      "$REMOTE logs -n 3000 --data-dir /var/lib/trendmill || true"
grab journal.log        'journalctl -u trendmill-core -n 2000 --no-pager'
grab journal-kiosk.log  'journalctl -u trendmill-kiosk -n 300 --no-pager'

# The machine itself: a fault that looks like software is sometimes a full disk,
# a dropped USB device or a radio that never came up.
grab system.txt 'echo "== uname =="; uname -a
echo "== uptime =="; uptime
echo "== release =="; readlink /opt/trendmill/current
echo "== services =="; systemctl is-active trendmill-core trendmill-kiosk bluetooth
echo "== disk =="; df -h /var/lib/trendmill /
echo "== memory =="; free -h
echo "== usb =="; lsusb
echo "== bluetooth =="; bluetoothctl show 2>/dev/null | head -5
echo "== usb autosuspend =="; cat /sys/bus/usb/devices/*/power/control 2>/dev/null | sort | uniq -c
echo "== config =="; cat /etc/trendmill/trendmill.env'

if [ -n "$SESSION" ]; then
    echo "  fetching session $SESSION (including the raw capture)"
    mkdir -p "$OUT/session"
    scp -q -o BatchMode=yes -r "${USER_AT}@${HOST}:/var/lib/trendmill/sessions/$SESSION/." \
        "$OUT/session/" || echo "  session FAILED: is the id right?"
fi

# ---- the verdict ----------------------------------------------------------

echo
python3 - "$OUT" <<'PY'
import json, pathlib, sys

out = pathlib.Path(sys.argv[1])

def load(name):
    try:
        return json.loads((out / name).read_text())
    except Exception:
        return None

print("Verdict")
print("-------")
s = load("status.json")
if not s:
    print("  The console did not answer. It is not running, or not on port 8080.")
    print("  Start with journal.log — a service that will not start is in there.")
else:
    link, stream = s["link"], s["stream"]
    print(f"  board        {link['state']}  ({link['detail'] or 'ok'})")
    rate = stream.get("rate_hz")
    print(f"  sample rate  {rate if rate is not None else '—'} Hz   "
          f"(expected about {s['app']['nominal_rate_hz']:.0f})")
    c = stream["counters"]
    bad = {k: v for k, v in c.items()
           if k in ("short_transfers", "out_of_range", "timeouts", "reconnects",
                    "queue_overflows") and v}
    print(f"  counters     {bad or 'all clean'}")
    print(f"  calibration  {s['calibration']['status']}")
    t = s.get("treadmill") or {}
    print(f"  treadmill    {t.get('state','—')}"
          f"{', running' if t.get('running') else ''}")
    h = s.get("height") or {}
    print(f"  height       {'homed' if h.get('homed') else 'not homed'}"
          f"{', moving' if h.get('moving') else ''}")
    for w in s.get("warnings", []):
        print(f"  WARNING      {w['message']}")

# Errors and warnings in the log, most frequent first: the shape of a fault is
# usually clearer from what repeats than from any single line.
log = out / "trendmill.log"
if log.exists():
    import re
    # An event name looks like "usb.timeout" -- lowercase words joined by dots.
    # Matching merely "has a dot in it" picks up the timestamp instead, which
    # makes every line unique and the whole summary useless.
    event_re = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
    counts: dict[str, int] = {}
    for line in log.read_text(errors="replace").splitlines():
        for level in ("ERROR", "WARNING"):
            if f" {level} " in line:
                event = next((w for w in line.split() if event_re.match(w)), "(no event)")
                counts[f"{level} {event}"] = counts.get(f"{level} {event}", 0) + 1
                break
    if counts:
        print("\n  Most frequent problems in the log:")
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
            print(f"    {n:>5}x  {name}")
    else:
        print("\n  No errors or warnings in the log.")

raw = list((out / "session").glob("raw/*.tmraw")) if (out / "session").exists() else []
if raw:
    print(f"\n  Reproduce it here:\n    ./run.sh --source replay --replay "
          f"{raw[0].relative_to(pathlib.Path.cwd()) if str(raw[0]).startswith(str(pathlib.Path.cwd())) else raw[0]}")
PY

echo
echo "Everything is in ${OUT#"$ROOT"/}"
echo "It contains patient names and recordings — handle it as clinical data."
