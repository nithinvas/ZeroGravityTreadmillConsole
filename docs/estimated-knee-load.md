# Estimated Knee Load

**Status:** spec, not yet built.
**One line:** how hard the patient's knee is being pushed, calculated from belt speed
and measured offload, shown against the limit their surgeon set.

## Why it exists

The surgeon's instruction is about the **joint** ("don't overload the graft"). Our
machine's dial is about **body weight** ("50% offload"). Nobody converts between them,
so the therapist is working blind.

The gap is concrete. At a fixed 50% offload:

| Belt speed | Knee load |
| ---------- | --------- |
| 2 km/h     | ~1.1 x BW |
| 6 km/h     | ~2.2 x BW |

Same dial setting, double the force in the joint. **Belt speed is a weight-bearing
control and is not currently treated as one.** This metric makes it visible.

It cuts both ways. Under-loading is as much a treatment failure as over-loading —
tissue needs stress to remodel — and a therapist aiming conservatively at an invisible
target lands low far more often than high.

## The number

Unit: multiples of body weight, e.g. `1.4 x BW`. One decimal, never more. Always
rendered with its absolute equivalent (`~98 kg`), because `1.4` means nothing to a
patient and `98 kg` means everything.

It is the **peak** force at heel strike, per step. Not an average over time. Any label
that drops the word "peak" will be misread.

## Source

Patil et al., *Anti-Gravity Treadmills Are Effective in Reducing Knee Forces*,
J Orthop Res 31:672-679 (2013). Four subjects with instrumented tibial implants —
force sensors inside the knee replacement, telemetered out — walked an LBPP treadmill
(same chamber-and-waist-seal design as ours) across a grid of speeds and offloads.

**We are not measuring this patient's knee.** We are applying a relationship measured
in four other knees. Everything below follows from that.

## Computation

Per step. We detect steps from the load cells already, so each step carries its own
belt speed and its own measured weight fraction.

```
w = peak vertical load this step / patient body weight     # from load cells
F = -0.3 + 0.186 * speed_kmh + 1.89 * w                    # x BW
```

Two notes on the inputs:

- **Use the measured `w`, not the commanded offload percentage.** The paper's authors
  set chamber pressure while the subject stood, then had to re-tune it once walking
  started. Our load cells read the real number continuously, which makes our estimate
  better than theirs and makes seal drift visible instead of hidden.
- The regression above is the paper's own, converted from mph. Prefer **bilinear
  interpolation over the measured 4x4 grid** where it applies; the linear fit tracks
  walking well but badly underestimates jogging (predicts 2.9 x BW at 4.5 mph where
  5.1 x BW was measured).

Measured grid, x BW:

| offload \ speed | 2.4 km/h | 4.0 km/h | 5.6 km/h | 7.2 km/h |
| --------------- | -------- | -------- | -------- | -------- |
| 0%  (full BW)   | 2.10     | 2.25     | 2.80     | 5.05     |
| 25%             | 1.53     | 1.82     | 2.36     | 3.74     |
| 50%             | 1.19     | 1.27     | 1.96     | 2.95     |
| 75%             | 0.82     | 0.89     | 1.37     | 1.89     |

## Validity envelope — enforce this in code

Our treadmill runs 1-12 km/h. The study covered 2.4-7.2 km/h. **Most of our range was
never measured.**

| Speed        | Behaviour                                                       |
| ------------ | --------------------------------------------------------------- |
| < 2.4 km/h   | Clamp to the 2.4 km/h row. Errs high, which is the safe direction |
| 2.4-7.2 km/h | Interpolate. This is the trustworthy band                        |
| > 7.2 km/h   | **No number.** Render "beyond measured range"                    |

Silently extrapolating to 12 km/h is the kind of thing that gets a device pulled. The
out-of-range state is a feature, not an error path.

Offload outside 0-75% is likewise outside the grid; clamp and mark.

## Where it surfaces

One estimator, three faces. Build in this order — the first two are higher value and
carry less risk than the live one.

1. **Wizard (before)** — updates as the therapist moves the speed and offload sliders,
   against the patient's limit. Prevents the problem rather than reporting it. This is
   also where the Froude / belt-outrunning-patient warning belongs.
2. **Report (after)** — peak, time-weighted typical, time above limit, cumulative
   (`BW-steps`), and load-vs-time with the limit line and speed as a faint second
   series. Plus the cross-session trend, which is the recovery story.
3. **Live tile (during)** — the therapist's hands are on a patient, so the **state**
   (green / over-limit + elapsed time over) is the signal and the number is secondary.
   Smooth with a rolling median over the **last 10 steps** — the paper itself averaged
   over at least 10 gait cycles before reporting anything, and an unsmoothed per-step
   value jitters enough to make people chase it.

## Rules

- **Name it "Estimated Knee Load."** The word *estimated* lives in the name, not in a
  footnote. Never ship a label reading just "Knee Load" — it reads as measured.
- **Do not brand it.** No index, no score, no coined name. A branded name makes a
  derived estimate sound like a proprietary measurement and hides its provenance.
- Session total is a separate quantity: **Cumulative Knee Load**, in `BW-steps`,
  report only.
- The provenance caveat is reachable from every surface: *estimated from a study of
  4 patients aged 67-83 with knee replacements; a guide, not a measurement.*
- **Decision support, never instruction.** The screen shows the number. It must never
  say "set speed to 4 km/h." The therapist's judgement and the surgeon's order stay in
  charge. This distinction matters for how the device is regulated.
- Knee-specific. Meaningless for a hip or ankle diagnosis.

## Known limits — say these out loud

N = 4. Ages 67-83. All had total knee replacements and no intact ACL — i.e. **not**
the ACL-reconstruction and cartilage-repair patients who would actually be prescribed
this machine. Trust the shape of the relationship; do not present the absolute values
as this patient's truth.

## Open

- Does the surgeon's limit live on the patient record or per session? (Leaning record,
  with a per-session override — it is an instruction that holds for weeks.)
- Hide the metric entirely for non-knee diagnoses, or show it greyed?
