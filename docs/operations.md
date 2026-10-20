# Running this in the field

How a machine gets installed, kept working, and fixed when it is not. Written
for whoever at Rehax picks up the phone.

The short version: installation and updates are solved and tested. Diagnosis is
solved *if you can reach the machine*. **Reaching the machine, and the customer
reaching you, are not solved** — see "What is missing" at the end, because that
is the part that decides whether this can be supported at scale.

---

## 1. Installing on a new treadmill

One script, run once, on a machine with Debian 13 already installed.

```bash
sudo ./deploy/provision.sh
```

Ten to fifteen minutes, mostly downloads. It creates the `treadmill` and
`kiosk` users, installs the USB and Bluetooth rules, unpacks the release under
`/opt/treadmill/releases/<version>`, builds its Python environment, installs
both systemd units, and sets up the Cage + Chromium kiosk so the screen comes
up on boot with no desktop behind it.

Before that, three things in the BIOS and OS that are easy to miss:

- **Restore on AC power loss → Power On.** A clinic will switch the machine off
  at the wall. Without this it stays off.
- **Install with Ethernet plugged in**, and untick everything at software
  selection except *standard system utilities* and *SSH server*.
- **Debian 13, not Ubuntu 24.04**, on the N150: Debian 13 ships kernel 6.12,
  which knows the Twin Lake iGPU that drives the kiosk. Ubuntu 24.04's 6.8 does
  not.

After provisioning, on site:

1. Plug in the load-cell board. Check `treadmill probe` finds `413d:2107` and
   reads packets. If it finds the device but cannot open it, the udev rule has
   not applied yet — reboot once.
2. **Calibrate against a known weight.** This is not optional and not a
   formality: every weight the machine ever reports comes from these
   coefficients, and a single-capture calibration cannot tell you that one cell
   is dead. Put a known mass over each corner in turn and confirm all four
   respond.
3. Create the first technician from the lock screen.
4. If more than one treadmill is in Bluetooth range, pin yours in
   `/etc/treadmill/treadmill.env` with `--treadmill-address`, or the console
   will connect to whichever answers first — possibly the one in the next room.

The whole provisioning path is tested on a clean container by
`./deploy/test-provision.sh`, which also checks the console then serves the API,
the UI and treadmill control. Run it before shipping a release.

---

## 2. Updating a machine

```bash
./deploy/deploy.sh <address> --yes
```

Builds a release on your Mac, copies it over, unpacks it beside the current one,
repoints the `current` symlink and restarts the service. Roughly a minute.

**Sessions, patient records, calibration and the settings file are left alone.**
That is tested explicitly, including the case of a machine whose database
predates schema versioning.

Rolling back is repointing the symlink at the previous release and restarting —
the old release is still on disk.

Take a database copy first, which is also what a service engineer should do
before touching anything:

```bash
treadmill backup
```

---

## 3. When a customer reports a problem

### Step one: what does the screen say?

The top bar is silent when the machine is ready. If it shows something, it says
both the problem and what to do about it — "The load cells are not connected.
Check the USB cable to the board." Ask the caller to read it out.

That answers a large share of calls without anyone logging in.

### Step two: the diagnostic bundle

```bash
./deploy/diagnose.sh <address>
```

Collects, into one archive: the console's status, calibration and treadmill
state, the last 25 sessions' metadata, 3000 lines of application log, the
systemd journal for both services, and system information including disk space.

**No patient names leave the machine in the status and log files** — but the
session metadata does contain them, so treat the bundle as clinical data.

### Step three: reading it

Most failures fall into a short list.

| What you see | What it means |
|---|---|
| `link: waiting`, `Board not found` | The board is unplugged, or the udev rule has not applied. Reboot once; then check the cable. |
| `A load cell has stopped responding` | The console found it itself: that corner is not moving while the others are. The deck is running on three corners and every weight is understated. Check the named cell's cable at the board. |
| `rate_hz` well below nominal | Packets are being dropped. Check the serial link speed before anything else. |
| `short` or `timeouts` climbing | USB trouble: cable, hub, or autosuspend. |
| `calibration: missing` | No coefficients selected. Sessions cannot start. |
| Kiosk black, service active | Display or Cage problem, not the console. Check `treadmill-kiosk`. |
| Service restarting repeatedly | Read the journal. The unit gives up after five restarts in ten seconds by design, rather than thrashing. |

Live logs, when you have a shell:

```bash
journalctl -u treadmill-core -f
treadmill logs -f --level warning
```

### The deck self-check

The console watches the four load cells continuously and raises a fault when one
stops responding. It compares how far each corner **travels**, not how much it
carries -- a patient standing off-centre genuinely unloads a corner, but every
working corner still moves with each step. On the real failure here, the three
live cells travelled 42-43 kg between their 5th and 95th percentiles while the
dead one travelled 4.4 kg: 99%, 101%, 102% of the median, against 10%.

It only judges while somebody is walking, says nothing when the deck is still,
and names the corner when it fires.

---

## 4. Service visits

What a service engineer should do, in order:

1. **`treadmill backup`** before anything else.
2. **Check all four load cells**, one corner at a time with a known weight. This
   is the failure that hides: a dead corner looks like a working machine.
3. **Recalibrate against a known mass** if anything was changed.
4. **Carry the backups off** on a USB stick. The copies in
   `/var/lib/treadmill/backups/` are on the same disk as the originals; they
   survive a corrupted database, not a failed drive.
5. **Run a short session and read the report** before leaving, as proof the
   whole chain works — acquisition, gait, weight bearing, storage.

Everything that affects measurement lives behind the Service screen, reachable
only by a technician.

---

## 5. What is missing

Honest list. None of it is hard; all of it is needed before this is supportable
at more than a handful of sites.

**The customer has no way to contact Rehax.** There is no phone number, no email
and no reference on any screen. A clinic with a problem has to already know who
to call and what to call the machine. The cheapest fix in this document: a
support line and the machine's serial on the lock screen and the service screen.

**There is no remote access in production.** Tailscale is installed only with
`--with-tailscale`, and only for development — it is to be removed before
shipping. Once it is, the only way into a machine is physically or through
whatever network the clinic happens to have. Support is currently "drive there".

**The service login does not exist.** The design is settled — per-machine
secrets, short typed codes, expiry, each engineer identified — and roughly a
week's work, but today a technician PIN is all there is, and nothing
distinguishes a Rehax engineer from clinic staff.

**The machine cannot tell *you* anything is wrong.** It now notices a dead load
cell and says so on its own screen -- see the deck self-check -- but it is
offline by design and has no outbound reporting, so somebody at the clinic still
has to read the screen and pick up the phone. Nothing reaches Rehax by itself.

**There is no fleet view.** No list of machines, versions, last-seen times or
installation dates. You cannot answer "which sites are on the old release?"

**Updates are manual and per-machine.** No staged rollout, no automatic update,
no signed packages.

**The disk is not encrypted**, and now holds patient names, ages, diagnoses and
session history, plus database backups. Anyone who removes the drive reads all
of it.

**The API has no authentication.** Forty-eight endpoints, no authorisation
checks; the PIN gate is enforced in the browser only. It is bounded today by
binding to localhost, which stops being a boundary the moment anything else can
reach that port.

### If I were ordering that list

1. Support contact and serial number on screen — hours of work, removes the
   worst gap.
2. API authentication — the roles are decorative without it.
3. The service login.
5. Disk encryption.
6. Fleet view and remote access, together, since they are the same problem.
