# Per-foot load from one deck

**Status:** built. `backend/treadmill/gait/decompose.py`, live on the session screen
("Left / right load") and in the report.

## What it does

A dual force plate measures each foot separately. We have one deck with four load
cells, and both feet land on it. This splits the one signal into two curves, so a
therapist can see what each leg is actually carrying.

## Why it is possible at all

Four cells give three numbers — total force and a centre of pressure — against
four unknowns (two forces, two positions). Underdetermined, in general.

It is only underdetermined **some** of the time. For most of a gait cycle one foot
is in the air, and an airborne foot carries exactly nothing: no algebra, just a
fact. That is why the curves reach true zero rather than bottoming out at a fitted
residual, and it is the whole reason this reads like a dual plate.

Real work is confined to the hand-over windows where both feet are down, and there
the pressure point sits between two feet whose positions were measured a fraction
of a second earlier.

## Three decisions worth knowing

**Phase comes from the lateral axis, not fore-aft.** The obvious signature is the
pressure point sliding backward at belt speed under a planted foot. It is excellent
from 3-7 km/h and fails at both ends: slow, the heel-to-toe roll under the foot
(~0.24 m/s forward, measured) cancels the belt and the slide disappears; fast, the
flight phase drives force toward zero and `CoP = moment / force` becomes
meaningless. Measured across three subjects, lateral separation between the feet is
**13-17 cm at every speed from 1 to 12 km/h** and needs no belt-speed input.

Before this change, 9 km/h reported **92% asymmetry** on a symmetric subject — a
confident fiction shaped exactly like a catastrophic limp. After, the same trace
reads 6.8%.

**Both axes are used for the split, weighted by conditioning.** Fore-aft separation
between feet is a step length; lateral is a step width, several times smaller, so
the same CoP error costs much more there. Weighting by the square of the separation
is the least-squares answer under the constraint that the feet sum to the measured
total. Their disagreement becomes the confidence figure, free.

**Nothing is assumed about the patient.** Cluster centres are found where the feet
actually land, so standing off-centre or loading one side harder is read, not
corrected away. Body weight is the mean total force over the window — Newton's third
law, not a typed-in number — so it is right for any body weight and right again when
body-weight support is carrying half of it.

## Invariants

- `left + right + residual == total`, exactly, on every sample and every input.
  Residual is non-zero only during a flight phase, where the deck still reads belt
  vibration that belongs to neither foot.
- An unresolved sample emits `null`, never `0`. The chart breaks the line. A gap
  reads as missing data, which is honest; a line through it reads as a measurement,
  and here a wrong line looks exactly like a limp.

## Live and the report cannot disagree

`decompose_trace()` does **not** batch the whole session. It replays the stored
trace through the same sliding window the live screen used, so the curve in the
record is the curve the therapist watched — identical, not merely similar. A test
asserts sample-for-sample equality.

The decomposition runs at the full sample rate during the session and the *result*
is written to `feet.csv` at 25 Hz. Storing the output rather than the raw cells
keeps a session to a few hundred kB instead of several MB, and removes any chance
of the report recomputing something different.

There is a fixed **0.5 s lag**: a hand-over cannot be resolved until the next foot
has landed and been measured. Single stance could be emitted instantly, but then
part of the curve would always arrive late, so all of it is delayed equally.

## Performance

5,600 samples/s in pure Python — about 9% of one core at the board's 976 Hz. The
window is re-solved 20 times a second rather than per sample; re-solving per sample
is ~50x more work and was enough to stall the acquisition loop when first written.

## Validated range

Three subjects (53-71 kg), 1-12 km/h, plus a synthetic walker with known ground
truth.

| Speed | Quality | Notes |
| ----- | ------- | ----- |
| 2-7 km/h | **good** | double support 15-26% (physiological ~20%), gaps under 5% |
| 1-2 km/h | fair | the feet are still separable but hand-overs get ragged |
| 8-12 km/h | fair | running; flight phase detected (17-36%), no double support, 13-22% gaps |

Outside what it can resolve it returns `Quality.UNUSABLE` with a reason in words a
therapist can act on, and the screen says so instead of drawing a curve.

## What it still cannot do

A gait with no structure. If a patient shuffles without ever fully unloading a limb,
or leans on the handrail, there is no single stance to anchor from and the central
assertion — *that foot is in the air* — is false.

**That is the population this machine is for**, so the limitation matters. Two
footswitches under the heels, on spare STM32 GPIO, would convert the inference into
a measurement: left only, right only, both, neither. It would also fix the ragged
low-speed hand-overs, since the lateral signature would no longer be the only cue.
That is the next thing worth building here.
