# Deploying on the mini PC

How to turn the mini PC into a TreadMill appliance: power on, and within a minute
the touch screen shows the console with the board connected and the treadmill
reachable.

Everything below is in `deploy/`. The scripts are idempotent — running
`provision.sh` again upgrades the release and leaves sessions, calibration and
settings alone — so the same command installs the first unit and updates it a
year later.

---

## The unit

The delivered machine is a **GMKtec NucBox G3 Plus**, not the MSI Cubi the design
was written around. Nothing in the software cares, but three things about it
shape the steps below.

| | |
| --- | --- |
| **CPU** | Intel N150, 4 cores / 4 threads, 3.6 GHz turbo, 6 W TDP — a later Twin Lake part than the N100 the design assumed, and slightly faster. The workload is still a fraction of one core |
| **RAM** | One **SO-DIMM socket**, DDR4-3200, shipped with 8 or 16 GB depending on the order, upgradeable to 32 GB. Not soldered |
| **Storage** | M.2 2280 NVMe (PCIe 3.0), 256 GB / 512 GB / 1 TB by order. The only drive: OS and every session live on it |
| **Display** | **2 × HDMI 4K@60. No DisplayPort and no USB-C video** |
| **USB** | 4 × USB 3.2 Gen1 type-A — two front, two rear |
| **Bluetooth** | 5.2, on the Wi-Fi 6 card. FTMS treadmill control needs nothing newer |
| **Network** | One 2.5 GbE port. Not used in normal operation; handy for service |
| **Power** | DC 12 V 3 A barrel jack |

What that changes:

- **The touch monitor goes on HDMI**, plus its own USB cable for the touch panel.
  The design's worry about the monitor occupying the USB-C port does not apply
  here, so all four USB-A ports stay free.
- **Use Debian 13, not Ubuntu 24.04.** The N150 is a Twin Lake part; Debian 13
  ships kernel 6.12, which knows it. Ubuntu 24.04's 6.8 predates it, and the risk
  lands exactly where it hurts — the iGPU driving the kiosk. `provision.sh`
  supports both; this machine is a reason to pick Debian.
- **Check the RAM and disk you actually received.** Both are "subject to actual
  purchase" in GMKtec's own manual. After the first boot:
  `sudo dmidecode -t memory | grep -E "Size|Speed"` and `lsblk`.

## Before you start

| | |
| --- | --- |
| **OS** | Debian 13 (trixie), amd64 — see above |
| **Install type** | Minimal / server. No desktop environment: the kiosk *is* the desktop |
| **Network** | Needed **once**, during installation and provisioning. Not needed afterwards |
| **You also need** | A USB stick (2 GB+) for the installer, a USB keyboard, and the monitor on HDMI |
| **Board** | Plugged into a USB-A port **directly** — not through a hub |

## 1. Install Debian

On the Mac, fetch the installer and write it to a USB stick. The official image
now includes the non-free firmware the Intel Wi-Fi/Bluetooth card needs, so the
plain netinst is the right one:

```bash
curl -LO https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.7.0-amd64-netinst.iso
```

Find the stick, **check the identifier twice**, then write it:

```bash
diskutil list
```

```bash
diskutil unmountDisk /dev/diskN && sudo dd if=debian-13.7.0-amd64-netinst.iso of=/dev/rdiskN bs=4m status=progress
```

`diskN` is the USB stick from `diskutil list` — writing to the wrong one erases
that disk. Use `/dev/rdiskN` (raw) rather than `/dev/diskN`: it is far faster.

Boot the mini PC from it (tap `F7` or `Del` at the GMKtec splash for the boot
menu), then install:

- **Ethernet plugged in** for the install — simpler than configuring Wi-Fi in
  the installer.
- Partitioning: guided, whole disk, all files in one partition.
- At **software selection**, untick everything except **standard system
  utilities** and **SSH server**. No desktop: the kiosk is the desktop.
- Give yourself a normal user account; `provision.sh` creates the service and
  kiosk users itself.

### BIOS

Reboot, tap `Del`, and set:

- **Restore on AC Power Loss → Power On.** The clinic switches the wall socket;
  the appliance must come back by itself. On GMKtec's AMI BIOS this is usually
  under *Chipset → PCH-IO Configuration → State After G3* (choose **S0**).
- **ErP / Deep Sleep → Disabled**, and disable any suspend or hibernate.
- **Watchdog → Enabled**, if the board offers it.
- Secure Boot may stay on.

---

## 2. Build the release (on the Mac)

```bash
cd ~/projects/treadmill-console && ./deploy/build-release.sh
```

That builds the UI, runs the full test suite, and writes
`dist/treadmill-<version>+<stamp>.tar.gz` with a SHA-256 beside it. Copy both to
a USB stick.

The appliance never builds the UI itself — no Node, no npm, no network for the
part most likely to differ between machines.

## 3. Provision (on the mini PC)

```bash
tar -xzf treadmill-<version>+<stamp>.tar.gz
sudo ./treadmill-<version>+<stamp>/deploy/provision.sh
```

Ten to fifteen minutes on a first run, mostly package downloads. It installs
packages, creates the `treadmill` and `kiosk` users, installs the USB and
Bluetooth rules, unpacks the release to `/opt/treadmill/releases/<version>`,
builds its Python environment with `uv`, and starts both services.

Useful flags:

| Flag | For |
| --- | --- |
| `--no-kiosk` | A headless unit, or servicing one over SSH |
| `--port 9000` | A different port (localhost only either way) |
| `--no-services` | Install without touching systemd (used by the container test) |

## 4. Check it

```bash
systemctl status treadmill-core              # running, no restarts
curl -s localhost:8080/api/status | head -c 300
journalctl -u treadmill-core -f              # live
```

**The board.** With it plugged in:

```bash
sudo /opt/treadmill/current/backend/.venv/bin/treadmill probe
```

It should find `413d:2107`, claim interface 1, and read packets at about 977
samples/s per channel.

**`Resource busy` (Errno 16) is expected while the console is running** — the
service already holds the interface, and only one process may. Stop it first
(`systemctl stop treadmill-core`), probe, then start it again. To check a
*running* appliance instead, just ask the console what it sees:

```bash
curl -s localhost:8080/api/status
```

`"state": "streaming"` with a rate near 976 Hz is the board working. If `probe`
finds the device but cannot open it *while the service is stopped*, that is the
udev rule not yet applied — reboot once.

**The treadmill.** Switch it on, make sure no phone or tablet is paired with it,
then tap **Check connection** on the console. Or from the shell:

```bash
curl -s -XPOST localhost:8080/api/treadmill/connect | head -c 300
bluetoothctl scan on     # if nothing is found: is it advertising at all?
```

**The screen.** The kiosk should already be up. If it is not:

```bash
systemctl status treadmill-kiosk
journalctl -u treadmill-kiosk -n 50
```

**End to end.** Choose coefficients on the Calibration tab (or **Use default
coefficients** if the file is present), then run a short session: the belt should
start at 1.0 km/h by itself, `+` should raise it, and the report should show a
block per speed.

---

## Settings

One file, `/etc/treadmill/treadmill.env`, which upgrades never overwrite:

```bash
sudo nano /etc/treadmill/treadmill.env
sudo systemctl restart treadmill-core
```

The two worth knowing:

- `TREADMILL_SOURCE=sim` runs the appliance against a simulated board, so the
  screen, the kiosk and the treadmill can be commissioned before the hardware is
  on the bench.
- `TREADMILL_EXTRA_ARGS=--treadmill-address AA:BB:CC:DD:EE:FF` pins one
  treadmill. **Do this in any clinic with more than one machine in range** — the
  console otherwise connects to the first treadmill that answers, which may be
  the one in the next room. Find the address with `bluetoothctl scan on`.

## Where things live

| Path | What |
| --- | --- |
| `/opt/treadmill/current` | Symlink to the running release |
| `/opt/treadmill/releases/<version>` | Each installed release, kept for rollback |
| `/var/lib/treadmill/sessions/` | One folder per session: raw samples, steps, trace, summary |
| `/var/lib/treadmill/calibration/` | `defaults.json` and the profile in use |
| `/var/lib/treadmill/logs/` | JSON logs; also in the journal |
| `/etc/treadmill/treadmill.env` | Settings |

## Upgrading and rolling back

Upgrade: copy the new tarball across and run `provision.sh` again. It installs
beside the old release and repoints `current`. **Do it between patients** — the
service restarts, and an in-flight session would be saved as *interrupted*.

Roll back to the previous release:

```bash
ls /opt/treadmill/releases
sudo ln -sfn /opt/treadmill/releases/<previous> /opt/treadmill/current
sudo systemctl restart treadmill-core
```

Sessions and calibration are outside the release, so they survive both.

## Backing up

The session folders are the record; the SQLite index is rebuilt from them.

```bash
sudo tar -czf /media/usb/treadmill-$(date +%F).tar.gz -C /var/lib treadmill
```

## The support loop: diagnose, fix, deploy

Three commands, run from your machine, with nobody technical at the clinic.

### 1. Get everything off the machine

```bash
./deploy/diagnose.sh zerogravity
```

Pulls the console's own view of itself, its logs, the journal, the machine's
health and the recent session list into `diagnostics/<host>-<timestamp>/`, then
prints a verdict:

```
Verdict
-------
  board        streaming  (Streaming)
  sample rate  976.08 Hz   (expected about 977)
  counters     all clean
  calibration  missing
  treadmill    idle
  height       not homed

  Most frequent problems in the log:
        2x  WARNING usb.timeout
        1x  ERROR usb.disconnected
```

Grouping the log by event rather than reading it line by line is usually what
identifies the fault: one `usb.disconnected` is a glance, two hundred is a
cable.

When the clinic can name the session that went wrong, take its raw capture too:

```bash
./deploy/diagnose.sh zerogravity --session 20260919-193116-37b5e3f8
```

### 2. Reproduce it at your desk

The raw capture is every USB transfer, untouched. Replay it and the console runs
against the real signal at the real rate:

```bash
./run.sh --source replay --replay diagnostics/<...>/session/raw/segment-0001.tmraw
```

Now it is an ordinary bug on your own machine, with a debugger, and you can
write a failing test before you fix anything.

### 3. Fix it and ship it

```bash
./deploy/deploy.sh zerogravity
```

Builds (which runs the full suite and refuses to package a failing release),
copies, provisions, and then checks the machine actually came back on the new
version — not just that provisioning said it finished.

**It refuses to upgrade a machine that is mid-session**, because restarting the
console would save that session as "interrupted" and lose the rest of the
patient's walk. Upgrade between patients.

### What this needs

**Seeing the UI from your own machine.** The console binds to localhost on the
appliance, so reach it through the SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 root@<machine>
```

Leave that running and open `http://localhost:8080`. Write **`127.0.0.1`, not
`localhost`**: on the appliance `localhost` resolves to IPv6 `::1`, the console
binds IPv4 only, and the forward then fails for some connections with
`connect failed: dial tcp [::1]:8080` — intermittently, which is more confusing
than not working at all.

SSH to the machine from wherever you are. On the same network that is its IP; from
anywhere it means a mesh VPN such as Tailscale, installed with
`provision.sh --with-tailscale`. Everything above is plain SSH either way.

`diagnostics/` is gitignored: it holds patient names and recordings, and should
be handled like the records themselves.

## Debugging by hand

Work down this list. Each step narrows where the fault is, and most problems are
identified by the second one.

### 1. Is the console running?

```bash
systemctl status treadmill-core
```

`active (running)` with no recent restarts. If it is restarting in a loop, skip
to the journal in step 5 — the app's own log will not exist yet.

### 2. What does the console think is happening?

```bash
curl -s localhost:8080/api/status | python3 -m json.tool
```

One command that answers most questions:

| Field | What to look for |
| --- | --- |
| `link.state` | `streaming` is healthy; `waiting` means no board |
| `stream.rate_hz` | About 976. A lower number means dropped transfers |
| `stream.counters` | `short_transfers`, `timeouts`, `queue_overflows` should stay at 0 |
| `warnings` | The console's own diagnosis, in plain words |
| `calibration.status` | `missing` explains "why is the weight blank" |
| `treadmill`, `height` | Connected, in control, homed |

### 3. What happened just before?

```bash
treadmill logs -n 200
```

(On the appliance: `/opt/treadmill/current/backend/.venv/bin/treadmill logs`.)
Every line is a structured event — a name and fields, not prose — so a whole
class of problem can be pulled out directly:

```bash
treadmill logs -n 500 --level warning        # only things that went wrong
treadmill logs -n 500 --component usb        # just the board
treadmill logs -n 500 --component ble        # just the treadmill
```

Components: `usb`, `decoder`, `clock`, `stream`, `calibration`, `gait`, `ble`,
`height`, `session`, `storage`, `api`, `ui`.

There is a `stream.health` line every 10 seconds carrying rate, counters, CPU
and memory — the fastest way to see whether a fault built up gradually or
arrived all at once.

### 4. Watch it happen

```bash
treadmill logs -f --component height
```

Leave it running and reproduce the problem. **Raise the detail without
restarting anything** — a restart would lose the state you are trying to
diagnose:

```bash
curl -s -XPOST localhost:8080/api/logging -H 'content-type: application/json' \
     -d '{"component":"gait","level":"debug"}'
```

That is deliberately not persisted: a restart returns it to `info`, so nobody
leaves a clinic machine logging at debug forever.

### 5. When the service will not start

```bash
journalctl -u treadmill-core -n 100 --no-pager
```

The journal catches crashes *before* the app's logging is up — a bad config, a
missing file, a permissions problem. The app's own log cannot show you those.

### 6. Reproduce it away from the clinic

This is the one that saves a trip. **Every session records every USB transfer,
untouched**, in `raw/segment-*.tmraw`. Copy the session folder off the machine
and replay it on a laptop:

```bash
scp -r root@<machine>:/var/lib/treadmill/sessions/<id> .
treadmill inspect <id>/raw/segment-0001.tmraw
./run.sh --source replay --replay <id>/raw/segment-0001.tmraw
```

The console then runs against the real signal, at the real rate, with the real
calibration — so a gait or decoding fault can be chased with a debugger on your
own machine. That is how the cadence lock-up was found.

### 7. The board itself

```bash
systemctl stop treadmill-core
/opt/treadmill/current/backend/.venv/bin/treadmill probe
systemctl start treadmill-core
```

Stop the service first: only one process may hold the interface, so `probe`
against a running console reports `Resource busy`, which means nothing is wrong.

### What to send when asking for help

```bash
tar -czf /tmp/treadmill-debug.tar.gz \
    /var/lib/treadmill/logs \
    /etc/treadmill/treadmill.env \
    /var/lib/treadmill/sessions/<the session that went wrong>
```

Plus the output of step 2. The logs and session files contain patient names, so
treat that archive the way you would the records themselves.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Stuck in the kiosk, no way to a shell | **Ctrl+Alt+F2** for a text console. If that is blocked (a release before VT switching was enabled), reboot, press `e` at GRUB and append `systemd.unit=multi-user.target` to the `linux` line, then Ctrl+X |
| Screen blank, backend fine | `journalctl -u treadmill-kiosk -n 50`. Usually Chromium missing (Ubuntu: see below) or the compositor cannot get the seat — check `systemctl status seatd` |
| "Waiting for board" | `treadmill probe`. Device absent → cable or hub; present but cannot open → udev rule not applied, reboot once |
| Channels all show the same value | The firmware's packet-packing bug, not the host. The console raises `channels_identical` itself |
| Transfers drop after a while | USB autosuspend. The udev rule disables it for this device; confirm with `cat /sys/bus/usb/devices/*/power/control` |
| Treadmill never found | Radio off (`rfkill list`), the treadmill paired to a phone, or missing Intel firmware — `dmesg \| grep -i bluetooth` |
| Treadmill found, refuses commands | It did not grant control. Nothing else may hold it; the console shows this rather than failing silently |
| A phantom keyboard types into the screen | The board's HID interface. The udev rule sets `LIBINPUT_IGNORE_DEVICE`; check the rule installed |
| Service restarting in a loop | `journalctl -u treadmill-core -n 100`. Most often the data directory's ownership after a manual copy: `chown -R treadmill:treadmill /var/lib/treadmill` |

## Ubuntu

Ubuntu 24.04 works, with one wrinkle: **Chromium is a snap**, and a confined
snap does not reliably see a Wayland socket owned by another user's compositor.
`provision.sh` installs the `chromium` deb where one exists and falls back to
`chromium-browser`. If the kiosk will not start on Ubuntu, either install
Chromium from a deb source or use Debian 13, which is the reference image.

Debian also needs `firmware-iwlwifi` from `non-free-firmware` for the Bluetooth
radio; `provision.sh` installs it when the repository is enabled. If Bluetooth is
missing after provisioning, add `non-free-firmware` to
`/etc/apt/sources.list` and re-run.

---

## What is verified, and what is not

The install path — packages, users, rules, `uv sync`, the console starting and
serving the API and UI — is exercised on every change by a Debian 13 container
test:

```bash
./deploy/test-provision.sh      # needs Docker
```

What that cannot cover, and what therefore has to be checked on the unit itself:
the USB board under a real Linux USB stack, autosuspend behaviour, the Bluetooth
radio and a real treadmill, the touch panel, Cage and Chromium on the real GPU,
and boot-to-kiosk timing. The [design doc](design.md) §13 lists the acceptance
tests for those, including the 8-hour soak in the final mounting position — the
N100 is passively cooled and will sit near the treadmill motor.
