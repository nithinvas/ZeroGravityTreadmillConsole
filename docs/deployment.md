# Deploying on the mini PC

How to turn the mini PC into a TrendMill appliance: power on, and within a minute
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
cd ~/projects/trendmill-console && ./deploy/build-release.sh
```

That builds the UI, runs the full test suite, and writes
`dist/trendmill-<version>+<stamp>.tar.gz` with a SHA-256 beside it. Copy both to
a USB stick.

The appliance never builds the UI itself — no Node, no npm, no network for the
part most likely to differ between machines.

## 3. Provision (on the mini PC)

```bash
tar -xzf trendmill-<version>+<stamp>.tar.gz
sudo ./trendmill-<version>+<stamp>/deploy/provision.sh
```

Ten to fifteen minutes on a first run, mostly package downloads. It installs
packages, creates the `trendmill` and `kiosk` users, installs the USB and
Bluetooth rules, unpacks the release to `/opt/trendmill/releases/<version>`,
builds its Python environment with `uv`, and starts both services.

Useful flags:

| Flag | For |
| --- | --- |
| `--no-kiosk` | A headless unit, or servicing one over SSH |
| `--port 9000` | A different port (localhost only either way) |
| `--no-services` | Install without touching systemd (used by the container test) |

## 4. Check it

```bash
systemctl status trendmill-core              # running, no restarts
curl -s localhost:8080/api/status | head -c 300
journalctl -u trendmill-core -f              # live
```

**The board.** With it plugged in:

```bash
sudo /opt/trendmill/current/backend/.venv/bin/trendmill probe
```

It should find `413d:2107`, claim interface 1, and read packets at about 977
samples/s per channel.

**`Resource busy` (Errno 16) is expected while the console is running** — the
service already holds the interface, and only one process may. Stop it first
(`systemctl stop trendmill-core`), probe, then start it again. To check a
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
systemctl status trendmill-kiosk
journalctl -u trendmill-kiosk -n 50
```

**End to end.** Choose coefficients on the Calibration tab (or **Use default
coefficients** if the file is present), then run a short session: the belt should
start at 1.0 km/h by itself, `+` should raise it, and the report should show a
block per speed.

---

## Settings

One file, `/etc/trendmill/trendmill.env`, which upgrades never overwrite:

```bash
sudo nano /etc/trendmill/trendmill.env
sudo systemctl restart trendmill-core
```

The two worth knowing:

- `TRENDMILL_SOURCE=sim` runs the appliance against a simulated board, so the
  screen, the kiosk and the treadmill can be commissioned before the hardware is
  on the bench.
- `TRENDMILL_EXTRA_ARGS=--treadmill-address AA:BB:CC:DD:EE:FF` pins one
  treadmill. **Do this in any clinic with more than one machine in range** — the
  console otherwise connects to the first treadmill that answers, which may be
  the one in the next room. Find the address with `bluetoothctl scan on`.

## Where things live

| Path | What |
| --- | --- |
| `/opt/trendmill/current` | Symlink to the running release |
| `/opt/trendmill/releases/<version>` | Each installed release, kept for rollback |
| `/var/lib/trendmill/sessions/` | One folder per session: raw samples, steps, trace, summary |
| `/var/lib/trendmill/calibration/` | `defaults.json` and the profile in use |
| `/var/lib/trendmill/logs/` | JSON logs; also in the journal |
| `/etc/trendmill/trendmill.env` | Settings |

## Upgrading and rolling back

Upgrade: copy the new tarball across and run `provision.sh` again. It installs
beside the old release and repoints `current`. **Do it between patients** — the
service restarts, and an in-flight session would be saved as *interrupted*.

Roll back to the previous release:

```bash
ls /opt/trendmill/releases
sudo ln -sfn /opt/trendmill/releases/<previous> /opt/trendmill/current
sudo systemctl restart trendmill-core
```

Sessions and calibration are outside the release, so they survive both.

## Backing up

The session folders are the record; the SQLite index is rebuilt from them.

```bash
sudo tar -czf /media/usb/trendmill-$(date +%F).tar.gz -C /var/lib trendmill
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Screen blank, backend fine | `journalctl -u trendmill-kiosk -n 50`. Usually Chromium missing (Ubuntu: see below) or the compositor cannot get the seat — check `systemctl status seatd` |
| "Waiting for board" | `trendmill probe`. Device absent → cable or hub; present but cannot open → udev rule not applied, reboot once |
| Channels all show the same value | The firmware's packet-packing bug, not the host. The console raises `channels_identical` itself |
| Transfers drop after a while | USB autosuspend. The udev rule disables it for this device; confirm with `cat /sys/bus/usb/devices/*/power/control` |
| Treadmill never found | Radio off (`rfkill list`), the treadmill paired to a phone, or missing Intel firmware — `dmesg \| grep -i bluetooth` |
| Treadmill found, refuses commands | It did not grant control. Nothing else may hold it; the console shows this rather than failing silently |
| A phantom keyboard types into the screen | The board's HID interface. The udev rule sets `LIBINPUT_IGNORE_DEVICE`; check the rule installed |
| Service restarting in a loop | `journalctl -u trendmill-core -n 100`. Most often the data directory's ownership after a manual copy: `chown -R trendmill:trendmill /var/lib/trendmill` |

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
