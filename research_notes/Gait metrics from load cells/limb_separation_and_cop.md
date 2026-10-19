# Separating left/right limb forces from a single combined force platform, and CoP-based gait analysis

Scope note for the report-writer: throughout, I flag whether a method needs only the **vertical** force (available on a four-corner-load-cell deck) or also needs **shear (Fx/Fy)** and/or **free moment Mz** (not available on a vertical-only deck). This distinction is the single most consequential filter on the literature for this device.

## Q1. What published algorithms exist for separating left and right vGRF from a single force platform during double support?

### Takeaway
There is a well-established lineage of five algorithm families — CoP-oscillation (Davis & Cavanagh 1993), smooth/spline transition functions (Villeger 2014; Raison patent), CoP-distance-based event detection plus revised Davis–Cavanagh reconstruction (Meurisse 2016), machine-learning regression (Bastien 2019), and physics-informed deep learning (Yu 2025). The vertical-only sub-problem is the best solved of the lot; the shear and mediolateral components are much harder and all require force components a vertical-only deck cannot measure.

### Cited Findings

**The underlying indeterminacy**
- During double support a single platform records a summation of bilateral force profiles, so the per-limb split is mathematically indeterminate without extra assumptions — [Davis & Cavanagh, J Biomech 1993 (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/002192909390020F); [NASA NTRS record](https://ntrs.nasa.gov/citations/20050000491)
- Framed as equations: a single platform gives only **two** equations (vertical force equilibrium, and moment equilibrium about an antero-posterior axis) against **four** unknowns (left and right vertical forces, left and right mediolateral CoP positions) — [US9579044B2 (Raison et al.), Google Patents](https://patents.google.com/patent/US9579044B2/en)
- The full 3D version is worse: the task has **ten unknowns but only five measured values** — [Yu et al., Gait & Posture 2025 (PubMed 40618708)](https://pubmed.ncbi.nlm.nih.gov/40618708/)
- "Only the resultant force of both limbs may be recorded on a single-belt instrumented treadmill or when both feet touch the same force platform" — [Bastien, Gosseye & Penta, Gait & Posture 2019 (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751)

**Family 1 — CoP-oscillation method (Davis & Cavanagh 1993)**
- Decomposes superimposed force data into individual left and right profiles by examining the **side-to-side (mediolateral) oscillations of the measured global centre of pressure** — [Davis & Cavanagh 1993](https://www.sciencedirect.com/science/article/abs/pii/002192909390020F)
- Critique in the Raison patent: the start and end of single/double stance must be set by **visual inspection** of the CoP plot (called "unreliable"); mediolateral CoP often lacks a clear inflection point so a threshold is hard to define; the method **fixes the mediolateral CoP of the take-off foot to threshold constants**, producing an absolute CoP error of about **3 cm**; and it was tested on **only one adult subject** — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)
- Requires only vertical force and the vertical-force-derived CoP. **Available on a four-load-cell vertical-only deck.**

**Family 2 — smooth / spline transition functions**
- Earlier work assumed the **trailing foot's force changes smoothly toward zero** during double stance — [search synthesis over Davis & Cavanagh / NTRS lineage](https://ntrs.nasa.gov/citations/20050000491)
- Villeger, Costes, Watier & Moretto (Medical Engineering & Physics 36(11):1530–1535, Nov 2014) propose an **adaptive transition function** whose shape coefficient is fitted to the single-support data, then used to split the double-support signal into right and left force *and moment* contributions — [IOPscience/ScienceDirect record](https://www.sciencedirect.com/science/article/abs/pii/S1350453314002082)
- Raison patent: during double stance the vertical GRF under the foot **leaving** the platform is approximated with a **cubic spline**, and the landing foot is assigned the remainder, so the sum always equals the measured global GRF — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)
- The vertical-only version needs only Fz. Villeger's moment decomposition needs Mx/My/Mz and shear — **not available on a vertical-only deck.**

**Family 3 — CoP-displacement event detection (ΔCoP) + revised Davis–Cavanagh**
- Raison patent computes a **squared Euclidean norm of CoP displacement between samples, ΔCoP²**, and thresholds it to separate single from double stance; GRF peaks are used to locate double stances; a predictive check over a short window of *s* samples flags an upcoming peak. Thresholds are set from the **white-noise magnitude (~0.01 m in their trials) × a security factor of 3** — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)
- Meurisse, Dierick, Schepens & Bastien (Gait & Posture 2016) detect **front-foot contact and back-foot off** from the **distance covered by the centre of pressure**, then reconstruct each limb's vertical force during double contact with a **revised version of the Davis & Cavanagh approach**; the authors state it may be used on a single force plate **or an instrumented treadmill** — [ScienceDirect record](https://www.sciencedirect.com/science/article/abs/pii/S0966636215009133)
- Another reconstruction method uses a **zero-derivative (inflection point) criterion** to detect contralateral foot contact and subtracts the contralateral force from the combined force-time curve — [search synthesis, Davis & Cavanagh lineage](https://www.sciencedirect.com/science/article/abs/pii/002192909390020F)
- **Vertical-only. Available on a four-load-cell deck**, which makes Meurisse 2016 the single most directly applicable paper for this device.

**Family 4 — machine learning regression (shear)**
- Bastien, Gosseye & Penta (Gait & Posture 73:221–227, 2019; PMID 31374439; DOI 10.1016/j.gaitpost.2019.07.190) built a **predictive linear model of the fore-aft GRF under the back foot at every 5% of the double contact phase**, from two predictors: the **total fore-aft force** and the **back foot's vertical force**. Trained on **374 healthy adults and 434 patient records** — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751); [UCLouvain repository PDF](https://dial.uclouvain.be/pr/boreal/object/boreal:222604/datastream/PDF_01/view)
- Their decomposition runs in a **cascade: vertical first, then fore-aft, then lateral**, with the lateral force derived from **balancing transverse moments about the centre of pressure** — [Bastien 2019](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751)
- **Requires total fore-aft force as an input predictor → unavailable on a vertical-only deck.** The lateral stage additionally requires Mz.

**Family 5 — physics-informed deep learning**
- Yu et al. (Gait & Posture, 2025) built a **physics-informed residual recurrent network (PI-ResRNN)** that decomposes forces *and* per-foot CoP during double contact, trained on **6,765 trials from 315 participants** including healthy adults and patients with **six types of neuromusculoskeletal disorder** — [PubMed 40618708](https://pubmed.ncbi.nlm.nih.gov/40618708/); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636225002619)
- Motivation stated: avoid making participants **target** separate plates, which causes multiple trial attempts "especially in patients with neuromusculoskeletal disorders" — [PubMed 40618708](https://pubmed.ncbi.nlm.nih.gov/40618708/)
- Uses all five measured channels (3 forces + 2 moments) as inputs → **the full model is unavailable on a vertical-only deck**, though a vertical-only ablation is conceptually possible.

**Family 6 — standing/bipedal stance (not gait, but adjacent)**
- A 2025 analytical method combined with neural networks for **bipedal stance exercises** reports CoP position error **< 8%** and vertical force error **2%** per foot from a single forceplate — [Determining the GRF Value and Location for Each Foot During Bipedal Stance Exercises from a Single Forceplate, PMC12349061](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12349061/)

**Methods using known belt speed**
- The mechanical fact that enables this: during single stance on a treadmill the CoP **drifts backward at approximately the belt speed**, then moves rapidly forward during double stance — [search synthesis of treadmill CoP literature](https://www.researchgate.net/publication/7722202_Determining_the_centre_of_pressure_during_walking_and_running_using_an_instrumented_treadmill)
- A paper on real-time double-stance modelling for treadmills exists: "Modeling of vertical ground reaction forces during double stance phase of the gait cycle for real-time treadmill measurements" — [ResearchGate record](https://www.researchgate.net/publication/308854874_Modeling_of_vertical_ground_reaction_forces_during_double_stance_phase_of_the_gait_cycle_for_real-time_treadmill_measurements)

### Inferences
- For a vertical-only four-load-cell deck, the realistic algorithm choice is **Meurisse 2016 (CoP-distance event detection + revised Davis–Cavanagh vertical reconstruction)**, optionally with Raison's **ΔCoP² thresholding** substituted for the event-detection stage to remove the manual visual-inspection step that the patent criticises in the original Davis–Cavanagh method.
- Everything Bastien 2019 and Villeger 2014 add beyond the vertical component is structurally out of reach: Bastien's fore-aft model takes total Fy as a *predictor*, and the lateral stage closes on a transverse-moment balance. A vertical-only deck therefore caps the product at **per-limb vertical force + per-limb CoP**, not per-limb 3D GRF.
- The known belt speed is a strong *prior* for the deck's own CoP-based event detection: because single-stance CoP should regress at ≈ belt speed, departures from that rate are exactly the signature of double support. This is the same information Meurisse's "distance covered by the CoP" criterion exploits, but with an absolute expected value rather than a tuned threshold — plausibly more robust across walking speeds. I found no paper that implements it that way explicitly, so treat this as an engineering inference, not a cited result.

### Gaps
- I could not retrieve full texts for Davis & Cavanagh 1993, Villeger 2014, Meurisse 2016 or Bastien 2019 (PubMed returned cookie walls, Europe PMC and ScienceDirect returned HTTP 403). All numeric values below come from abstracts, search-engine extracts of abstracts, or the Raison patent's own characterisation of prior art. The exact functional forms of the transition functions and the revised Davis–Cavanagh reconstruction are therefore not in these notes and would need library access.
- Raison et al. (2005), "ground reaction forces and centres of pressure of both feet on a single platform", cited by Arsalis, was not retrieved separately.
- I found no published method that uses belt speed as an explicit constraint in the decomposition itself.

## Q2. What accuracy do these methods report against dual-plate/dual-belt gold standards?

### Takeaway
Vertical-force decomposition is accurate to roughly 2–4% relative error with R² ≈ 0.99 against individual force plates, and the best figures hold up in large clinical samples. Shear and mediolateral components degrade sharply — lateral force errors of 12–18% are typical — and this is precisely the part a vertical-only deck cannot do anyway.

### Cited Findings

**Meurisse 2016 (vertical only; the most relevant benchmark)**
- **811 force measurements during double contact**, from walking trials of **27 healthy subjects and 88 patients** — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636215009133)
- **Median relative error 1.8% (healthy), 2.5% (clinical)**; correlation with real forces **R² = 0.998 (healthy), R² = 0.991 (clinical)**, validated against individual force plates — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636215009133)
- A companion study on the same subject pool reported a **mean absolute difference of 1.76%** across 27 subjects, i.e. reconstructed GRFs equal measured forces **within 2%** — [Determination of vertical ground reaction forces under each foot during walking (ResearchGate)](https://www.researchgate.net/publication/264388878_Determination_of_vertical_ground_reaction_forces_under_each_foot_during_walking)

**Villeger 2014 (forces and moments, double support only)**
- Relative RMSE: **~3.8% vertical force, ~6% anterior force, ~18% lateral force** — [search extract of abstract](https://www.sciencedirect.com/science/article/abs/pii/S1350453314002082)
- Relative RMSE for moments: **~4.3% frontal, ~3% sagittal, ~12.3% transverse** — [same](https://www.sciencedirect.com/science/article/abs/pii/S1350453314002082)
- **Maximum force errors < 1 N/kg** in double support; **mean CoP error 0.0135 m (13.5 mm)** in double support — [same](https://www.sciencedirect.com/science/article/abs/pii/S1350453314002082)
- Authors' own highlight: the errors are **lower than intra-individual variability** — [same](https://www.sciencedirect.com/science/article/abs/pii/S1350453314002082)
- A later paper attributes the large lateral-force and transverse-moment errors to the **interdependence of these components**, and notes that most such algorithms **disregard the necessary equilibrium of moments about a vertical axis** — [Bastien 2019](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751)

**Raison patent (vertical, children)**
- **Mean relative error 5.0%** between computed and measured vertical forces, over **36 double stances** from children (age 9.3 ± 2.9 y, weight 35.1 ± 11.1 kg) during untargeted gait on seven force plates; **no trials rejected** — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)

**Bastien 2019 (shear, ML)**
- Lateral force error **~5.7% in healthy gait and ~12.0% in patients** under the back foot, and roughly **half that under the front foot** — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751)

**Yu 2025 (physics-informed DL, full 3D + CoP)**
- Mean **rRMSE below 0.34% (vertical), 0.38% (anteroposterior), 0.56% (mediolateral)** GRF, and mean **CoP RMSE below 3.0 mm** — [PubMed 40618708](https://pubmed.ncbi.nlm.nih.gov/40618708/)
- The model also reproduced **statistically significant between-group differences** that were present in the ground truth — [same](https://pubmed.ncbi.nlm.nih.gov/40618708/)

### Inferences
- The accuracy hierarchy is consistent across independent groups: **vertical ≪ anteroposterior < mediolateral/transverse** in error. A vertical-only deck is therefore operating in the *best* part of the error landscape, not the worst — the components it cannot measure are the ones the algorithms handle badly in any case. This is a genuinely favourable framing for a four-load-cell design.
- Yu 2025's sub-1% figures are a large step beyond the 2–5% of analytical methods, but they are **rRMSE** (normalised RMSE, which deflates with large signal ranges) from a single group, on a model consuming all five channels. They are not directly comparable to Meurisse's median relative error, and I found no independent replication. Treat the ~2% analytical figure as the defensible design assumption.
- Villeger's 13.5 mm mean CoP error during double support is a useful order-of-magnitude expectation for per-foot CoP after decomposition, and is comparable to the ~8.5–17 mm AP CoP RMSE of load-cell/ML systems (Q7) — i.e. per-foot CoP from a decomposed signal is a roughly centimetre-accurate quantity, not a millimetre-accurate one.

### Gaps
- No study I found validates a decomposition algorithm against a **dual-belt instrumented treadmill** as the gold standard. All validations above use **two or more separate overground force plates** with targeted or untargeted stepping. Whether treadmill-specific effects (belt compliance, motor torque ripple, frame vibration) degrade the figures is untested in these sources.
- No reported accuracy figures as a function of **walking speed**, which is the variable that matters most for the slow-gait failure mode.
- Bastien 2019's vertical-stage accuracy is not separately reported in the material I could access (it builds on Meurisse).

## Q3. What are the documented failure modes?

### Takeaway
The literature documents failure modes clearly in principle — every method depends on a detectable single-support interval and on CoP displacement having a resolvable structure — but direct quantitative evidence for shuffling gait, handrail use and running is thin to absent. The strongest documented evidence is for gait variability (children, patients) and for the mediolateral CoP lacking a usable inflection point.

### Cited Findings

**Variable gait and absent CoP inflection**
- Mediolateral CoP **often lacks a clear inflection point**, so a threshold is hard to define; **children's gait is more variable**, which makes the CoP oscillations harder to interpret; the original CoP-oscillation method was tested on one adult subject and therefore "cannot be implemented systematically or applied to all gait patterns" — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)
- The CoP-oscillation method's fixing of take-off-foot mediolateral CoP to constants yields **~3 cm absolute CoP error** — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)

**Pathological gait degrades, but does not break, vertical decomposition**
- Median relative error rises from **1.8% (healthy) to 2.5% (clinical)** over 88 patients — [Meurisse 2016](https://www.sciencedirect.com/science/article/abs/pii/S0966636215009133)
- Lateral force error rises from **~5.7% (healthy) to ~12.0% (patients)** — [Bastien 2019](https://www.sciencedirect.com/science/article/abs/pii/S0966636218319751)
- Yu 2025 explicitly trained and tested on patients with **six types of neuromusculoskeletal disorder** and recovered the between-group statistical differences, i.e. the decomposition did not wash out pathology — [PubMed 40618708](https://pubmed.ncbi.nlm.nih.gov/40618708/)
- Targeting separate force plates "can cause multiple trial attempts, especially in patients with neuromusculoskeletal disorders" — the clinical pressure that motivates single-platform decomposition in the first place — [PubMed 40618708](https://pubmed.ncbi.nlm.nih.gov/40618708/)

**Slow gait is the population of interest, and asymmetry is the norm there**
- Slow gait speed and interlimb asymmetry are "prevalent in a variety of disorders" — [The Integrated Virtual Environment Rehabilitation Treadmill System, PMC4545254](https://pmc.ncbi.nlm.nih.gov/articles/PMC4545254)
- A major shortcoming of current split-belt protocols is that they **do not reduce temporal asymmetries tied to weight-bearing and propulsion forces** — [Weight-bearing symmetry changes after asymmetric surface stiffness walking (bioRxiv preprint)](https://www.biorxiv.org/content/10.1101/2025.05.16.654517.full.pdf)

**Patients who never fully unload one limb**
- GRFs during double limb stance have been studied specifically in **unilateral transfemoral amputation**, a population where double-support loading is markedly asymmetric — [Ground reaction forces during double limb stances while walking in individuals with unilateral transfemoral amputation, PMC9885323](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9885323/)

**Thresholding fragility**
- Raison's ΔCoP² thresholds are derived from the measurement noise floor (**~0.01 m of CoP white noise × safety factor 3**) — so the method's usable sensitivity is bounded by CoP noise, which itself scales as 1/Fz — [US9579044B2](https://patents.google.com/patent/US9579044B2/en)

### Inferences
- The mechanism of failure is common to all CoP-based methods and follows directly from the cited noise-floor construction: **CoP noise is inversely proportional to total vertical force**, and the CoP *signal* used for event detection is proportional to the inter-foot separation times the load fraction on the incoming foot. Very slow walking, shuffling gait with short steps, and partial body-weight support therefore all attack the same quantity — they shrink the CoP excursion between successive samples while leaving (or increasing) the noise, pushing ΔCoP² below the 3σ threshold. Expect event detection to fail before force reconstruction does.
- **A patient who never fully unloads one limb breaks the method structurally, not statistically.** Every algorithm in Families 1–4 calibrates on the single-support interval — Villeger fits the transition-function shape coefficient to single-support data, Meurisse/Davis–Cavanagh reconstructs the trailing-foot curve from an assumption anchored at full unloading, and Raison's spline is fitted to a force that goes to zero. With no true single support (continuous double support, shuffling, or a flat-footed drag), there is no interval in which the measured force is attributable to one limb, so the system never becomes determinate. This is an inference from the cited method descriptions, not a measured result in any source I found.
- **Handrail use is an unmodelled external force.** Every method rests on vertical force equilibrium, i.e. the measured ΣFz equals the body's inertial + gravitational load. A handrail supplies an unmeasured vertical and horizontal force, so ΣFz no longer closes and the "remainder assigned to the landing foot" step in Raison's spline method absorbs the entire handrail load as a force error on one limb. I found **no published study** quantifying this; it is a first-principles consequence.
- **Running with a flight phase is the easy case for vertical separation and the hard case for CoP.** With no double support there is nothing to decompose — each contact is attributable to one limb outright. The risk shifts to event detection (CoP is undefined during flight, when ΣFz → 0, so CoP goes numerically unstable and must be gated by a force threshold) and to bandwidth (impact peaks need high sampling; see Q7).

### Gaps
- **No source I found reports decomposition error as a function of walking speed, or any study of shuffling gait, festinating gait, or very slow (< 0.4 m/s) walking.** This is the most important unanswered question for the device and I would flag it as a genuine hole in the literature, not just in my search.
- **No source quantifies the effect of handrail use** on single-platform force decomposition or on CoP-based event detection. Searches on single-belt decomposition error in pathological gait returned no study addressing it directly.
- No source addresses patients using body-weight support or assistive devices (walkers, canes) on an instrumented deck.
- Running: no paper I found applies these decomposition algorithms to running, which is consistent with the fact that the problem largely disappears — but it also means there is no validated event-detection scheme for the walk/run transition.

## Q4. How is centre of pressure computed from four corner load cells?

### Takeaway
For a four-corner vertical-only deck the CoP is a difference-over-sum of the corner readings scaled by half the platform dimensions; there is no need for moment channels. The general six-component formula requires Mx, My and the plate's vertical offset dz, and is not usable without them.

### Cited Findings

**Four-corner difference-over-sum form** (origin at plate centre, corner readings F1–F4, plate length *l*, width *w*, ΣF the sum of the four readings):
- `X_cop = ((F1 + F2) − (F3 + F4)) · (l/2) / ΣF`
- `Y_cop = ((F2 + F3) − (F1 + F4)) · (w/2) / ΣF`
- The moment about the Y axis is derived from the corner readings and equals X_cop × total vertical force. Corner-to-axis assignment depends on cell numbering and must be checked against the physical layout — [Design and Validation of a Low-Cost Portable Device to Quantify Postural Stability (2017), PMC5375905](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5375905/)

**Equivalent weighted-centroid form** (cell positions X_i, Y_i; readings W_i), used for centre-of-gravity scales:
- `X_cg = Σ(W_i · X_i) / ΣW_i`, `Y_cg = Σ(W_i · Y_i) / ΣW_i` — same structure, using cell coordinates directly rather than the difference-over-sum form — [Loadstar Sensors, Center of Gravity Scale](https://www.loadstarsensors.com/solutions/center-of-gravity-scale.html)

**General six-component form** (for comparison; requires moment outputs):
- `CoP_X = (−M_Y + F_X · dz) / F_Z`, `CoP_Y = (−M_X + F_Y · dz) / F_Z`, where dz is the plate's vertical offset between the measurement origin and the contact surface. CoP is by definition the point of application of the resultant vertical force. "If the platform reports moments directly, use this form. For a four-cell plate with no moment output, use the corner-difference formula above." — [search synthesis of force-platform references, incl. Wikipedia: Force platform](https://en.wikipedia.org/wiki/Force_platform)
- Load-cell-only platforms measure only vertical force and **cannot estimate shear or horizontal components**; the same holds for pressure-measuring plates — [search synthesis, same sources](https://en.wikipedia.org/wiki/Force_platform)

**Reference-design note**
- Commercial laboratory plates themselves use four cells: Kistler platforms use **four piezoelectric load cells** to compute GRF and CoP location — [DeBerardinis et al., J Rehabil Assist Technol Eng 2020, PMC7338728](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)

### Inferences
- The two forms are algebraically identical for a rectangular four-cell layout with cells at the corners; the weighted-centroid form generalises to non-rectangular or more-than-four-cell layouts and is the safer implementation.
- Because CoP is divided by ΣF, **CoP is undefined and numerically explosive as ΣF → 0**. Any implementation must gate CoP output on a vertical-force threshold (and the Raison noise analysis — ~0.01 m CoP white noise — is effectively a statement about this ratio at walking loads).
- The dz term in the general formula is the standard correction for the plate's measurement plane sitting below the contact surface. On a four-corner deck with Fx/Fy unmeasured, the dz correction is both unavailable and unnecessary — but this also means the deck's CoP is **the vertical-force CoP only**, which is the correct quantity for Davis–Cavanagh-style decomposition. The `F_X · dz` term in the general formula is exactly the shear-induced CoP offset that a vertical-only deck silently omits; it is small during mid-stance walking but grows at push-off and heel-strike.
- Four cells recover three quantities (Fz, Mx, My) and hence a 2D CoP — the four readings are one redundant measurement, which is what allows a least-squares calibration but means **no additional information is available to help the limb-separation problem beyond Fz and CoP**.

### Gaps
- I did not find a paper giving the **error-propagation formula** for CoP uncertainty from individual load-cell uncertainty on a four-corner deck (the expected form, σ_CoP ∝ (l/2)·σ_F/ΣF, is an inference).
- No source addressed **crosstalk, hysteresis or corner-sensitivity calibration procedures** specific to four-corner load-cell decks, despite the search including force-plate design and calibration terms.

## Q5. What clinically useful metrics come from CoP alone?

### Takeaway
A vertical-only deck can produce a complete CoP metric set — path length, velocity, AP/ML excursion, sway, the butterfly/gait-line diagram with its intersection-point measures, and CoP symmetry — and these are exactly the parameters commercial systems like Zebris already report clinically. Normative definitions are vendor-specific and should be checked against current documentation.

### Cited Findings

**Path length and width (validated against force plates)**
- CoP path length during overground walking, 65 healthy adults, Kistler force plates: **13.45 ± 1.72 cm**; CoP path width **1.31 ± 0.24 cm**. Pressure insoles over the same subjects gave 14.28 ± 1.97 cm and 0.74 ± 0.29 cm respectively — [DeBerardinis et al. 2020, PMC7338728](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)
- Insole-vs-plate normalised difference: **ΔL = 4.12 ± 6.72% (r = 0.74)** for length, **ΔW = −7.04 ± 4.48% (r = 0.11)** for width. Length agreement was strong, width agreement weak, attributed to the small number of sensors across the insole width — [same](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)

**CoP velocity as a clinical marker**
- Mean CoP velocity during stance was **strongly correlated with walking speed** — [Velocity of centre of pressure as a predictor of walking speed, PMC3323521](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3323521)

**Butterfly diagram / gait line (the Zebris-style Lissajous construction)**
- The butterfly diagram traces the CoP across a walking trial and "captures many gait characteristics in a single frame"; used in stroke and neurological rehabilitation — [RESNA 2017, Butterfly Parameters Affected by AFOs in Stroke](https://www.resna.org/sites/default/files/conference/2017/emerging_technology/Thitithunwarat%20.html)
- Parameters appearing on Zebris reports and in Zebris-based studies:
  - **Gait line length (mm)** — a sample Zebris gait report lists values near **220–225 mm** — [Zebris gait report sample PDF](https://is.muni.cz/el/fsps/podzim2020/np4333/um/Zebris_protokol.pdf)
  - **Single limb support line length (mm)** — also on Zebris reports; measured alongside gait line length in an ACL-reconstruction study — [ACLR butterfly/CoP figure](https://www.researchgate.net/figure/Butterfly-diagram-of-COP-and-gait-line-in-patients-with-ACL-reconstruction-Note-a_fig5_388530109)
  - **Anterior/posterior position (mm)** of the CoP intersection point — [Belgian Malinois CoP study](https://www.researchgate.net/publication/342551126_Center_of_Pressures_COP_Analysis_Using_Gait_Analysis_Systems_in_Belgian_Malinois_Dogs_A_Pilot_Study)
  - **Lateral symmetry (mm)** — [same](https://www.researchgate.net/publication/342551126_Center_of_Pressures_COP_Analysis_Using_Gait_Analysis_Systems_in_Belgian_Malinois_Dogs_A_Pilot_Study); also a listed outcome in a stroke RCT — [ClinicalTrials.gov NCT05187559](https://clinicaltrials.gov/study/NCT05187559)
  - **Max gait line velocity (cm/s)** and **time change heel to forefoot (%/s)** — [Zebris gait report sample](https://is.muni.cz/el/fsps/podzim2020/np4333/um/Zebris_protokol.pdf); [NCT05187559](https://clinicaltrials.gov/study/NCT05187559)
- **Intersection-point variability** analysed by **kernel density estimation**, plus a **CoP symmetry index**, in post-stroke gait — [Characterizing intersection variability of butterfly diagram in post-stroke gait using KDE](https://www.researchgate.net/publication/337992444_Characterizing_intersection_variability_of_butterfly_diagram_in_post-stroke_gait_using_Kernel_Density_Estimation)
- The butterfly diagram has been proposed as "a gait marker for neurological and cerebellar impairment in people with multiple sclerosis" — [ResearchGate record](https://www.researchgate.net/publication/281394941_The_butterfly_diagram_A_gait_marker_for_neurological_and_cerebellar_impairment_in_people_with_multiple_sclerosis)
- CoP parameters during gait and stance have been related to **falls history in lower-limb osteoarthritis** — [PMC12287451](https://pmc.ncbi.nlm.nih.gov/articles/PMC12287451/)

**Static sway / postural stability from four load cells**
- The same four-corner formula is the basis of low-cost postural-stability devices, validated against laboratory plates — [PMC5375905](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5375905/); [Validating and Calibrating the Nintendo Wii Balance Board, PMC4239899](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4239899/)

### Inferences
- The butterfly diagram is **the natural primary output of a single combined deck** and requires no limb separation at all: it is literally the global CoP trajectory plotted in the plate frame, and its diagnostic content (intersection-point scatter, lateral symmetry, loop asymmetry between left and right wings) comes from the fact that the combined signal alternates between limbs. A product built on one deck with four load cells is architecturally *better* suited to butterfly analysis than a split-belt system, where the two plates must be registered into a common frame first.
- The DeBerardinis width result (r = 0.11 for path width) is an important caution transferred to this device: **mediolateral CoP measures are far less reliable than anteroposterior ones** when spatial resolution across the narrow direction is limited. For a four-cell deck the ML resolution is set by cell spacing across the belt width, which is the coarsest axis — so ML excursion and lateral-symmetry metrics should be expected to be the noisiest outputs, matching the independently observed ML weakness in Villeger's 18% lateral force error and the ML CoP r = 0.22 in Q7.
- On a treadmill the butterfly is not a static figure: successive steps land at nearly the same plate location, so the diagram superimposes steps rather than marching forward as it does on an overground walkway. This makes intersection-point *variability* (the KDE measure) directly available without the step-to-step registration an overground mat needs — an inference, but a straightforward consequence of treadmill geometry.

### Gaps
- The Zebris gait report PDF would not render through WebFetch (the fetch returned empty page content), so I could not extract the **complete parameter list with units and both-feet sample values**. The parameter names and the ~220–225 mm gait-line length above come from the search engine's extract of that document, not from my own reading of it. **Someone should open that PDF directly.**
- **No normative reference values** for butterfly parameters in healthy adults were found — only the single sample report. Exact Zebris parameter definitions should be checked against current FDM documentation.
- Several butterfly-parameter sources are ResearchGate records and conference abstracts rather than peer-reviewed full texts; the dog study and the RESNA pilot are weak evidence for parameter *definitions* and should not be cited for normative values.

## Q6. Heel-to-toe CoP progression under a single planted foot during treadmill walking

### Takeaway
Under a single planted foot the CoP travels roughly a foot length in the anteroposterior direction (about 83% of foot length overground) and about 27% of foot width mediolaterally; on a treadmill the plate-frame CoP additionally regresses backward at approximately belt speed during single stance and jumps forward during double stance. I found no source giving treadmill single-stance excursion directly in mm or mm/s.

### Cited Findings
- Overground plantigrade walking: **CoP excursion was 83% of foot length (AP) and 27% of foot width (ML)** — [Center of Pressure Trajectory during Gait: A Comparison of Four Foot Positions, PMC4029865](https://pmc.ncbi.nlm.nih.gov/articles/PMC4029865/); [ScienceDirect record](https://www.sciencedirect.com/science/article/abs/pii/S0966636214006171)
- CoP "travels approximately a foot length during stance" — [same](https://pmc.ncbi.nlm.nih.gov/articles/PMC4029865/)
- On a treadmill, **in single stance the CoP moves backward with a velocity about equal to the treadmill speed**, then moves quickly forward during double stance — [Determining the centre of pressure during walking and running using an instrumented treadmill (ResearchGate record)](https://www.researchgate.net/publication/7722202_Determining_the_centre_of_pressure_during_walking_and_running_using_an_instrumented_treadmill)
- Treadmill belt velocity in one instrumented-treadmill study **deviated at most 5% from the intended velocity** — relevant if belt speed is used to predict CoP velocity — [same](https://www.researchgate.net/publication/7722202_Determining_the_centre_of_pressure_during_walking_and_running_using_an_instrumented_treadmill)
- Mean CoP velocity during stance is strongly correlated with walking speed — [PMC3323521](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3323521)
- A pressure-mat CoP-excursion method sampled at **240 Hz** (overground) — a reference point for excursion-method sampling rates — [A Novel Method for Gait Analysis on Center of Pressure Excursion Based on a Pressure-Sensitive Mat, PMC7663129](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7663129/)

### Inferences
- Two superimposed effects must be separated in the plate frame. **Foot-frame** AP excursion is ≈ 0.83 × foot length (so ≈ 215 mm for a 260 mm foot) heel-to-toe, forward. **Plate-frame** excursion during single stance adds a backward translation of the whole foot at belt speed: at 1.2 m/s with a ~0.4 s single-support duration, that is ≈ 480 mm of backward drift — more than twice the foot-frame excursion, and in the opposite direction. **The net plate-frame CoP motion during treadmill single stance is therefore dominated by belt-speed regression, not by heel-to-toe roll-over.** Recovering the clinically interesting heel-to-toe progression requires subtracting belt displacement, i.e. working in the foot frame.
- This also explains why the belt-speed prior is so useful for event detection: single stance has a near-constant, predictable plate-frame CoP velocity (≈ −v_belt), while double stance has a large, fast forward excursion as load transfers to the leading foot, which lands ahead of the trailing one. The contrast between these two regimes is large (hundreds of mm/s versus a sign-reversed transient), which is more robust than thresholding mediolateral inflection points.
- Both inferences above are arithmetic consequences of the cited facts, not values reported in any source.

### Gaps
- **No source gives treadmill single-stance CoP excursion in mm, or CoP velocity in mm/s, at a stated walking speed.** The arithmetic above is mine. Searching for this specifically returned only the qualitative "velocity about equal to the treadmill speed" statement.
- No source reports whether the 83%-of-foot-length figure holds on a treadmill as it does overground.
- No normative heel-to-toe CoP velocity profile (the "time change heel to forefoot, %/s" that Zebris reports) with reference values was found.

## Q7. Commercial single-belt instrumented treadmills reporting per-limb data

### Takeaway
Arsalis Gaitway 3D is the clearest case: a four-strain-gauge single-belt treadmill advertising on-the-fly left/right 3D force decomposition, citing exactly the Davis–Cavanagh / Meurisse / Bastien lineage above, but publishing no numerical accuracy claim of its own. Zebris FDM-T is a different technology (capacitive pressure matrix, not load cells) and gets per-limb data spatially rather than by decomposition; its published validation is mixed and model-specific.

### Cited Findings

**Arsalis Gaitway 3D (single belt, four strain gauges)**
- Described as "the first instrumented single belt treadmill that measures ground reaction forces in three directions"; advertises **left and right force decomposition** and biomechanical parameters for **normal and pathological gait** — [Arsalis Gaitway 3D product page](https://www.arsalis.com/products/instrumented-treadmill/)
- Specs on that page: **4 strain gauge sensors**; measures vertical, fore-aft and lateral GRF (moments not mentioned); optional pressure metrics, centre of pressure, 3D centre-of-mass displacement, mechanical work; **sampling rate up to 10 kHz**; "Left / Right foot 3D force decomposition" listed as a parameter, performed "on the fly"; no platform dimensions stated — [same](https://www.arsalis.com/products/instrumented-treadmill/)
- Accuracy claims are **qualitative only** ("excellent measuring accuracy", "extremely wide measuring range") with **no numerical values** — [same](https://www.arsalis.com/products/instrumented-treadmill/)
- The page lists nine references without saying which validate this device; the most relevant are **Dierick et al. 2004** (a force measuring treadmill in clinical gait analysis), **Raison et al. 2005** (GRFs and CoPs of both feet on a single platform), **Bastien et al. 2019** (decomposing shear forces during double contact), and **Davis & Cavanagh 1993** — [same](https://www.arsalis.com/products/instrumented-treadmill/)
- Dierick et al. 2004, "A force measuring treadmill in clinical gait analysis", exists as a separate publication — [ScienceDirect record](https://www.sciencedirect.com/science/article/abs/pii/S0966636203001942)

**Zebris FDM-T (pressure matrix, not load cells)**
- Zebris describes the FDM-T as a **pressure sensor matrix with individually calibrated capacitive sensors beneath the belt**, and presents **no validation data** on that page — [Zebris: Gait analysis on the FDM-T treadmill](https://www.zebris.de/en/medical/dynamic-gait-analysis-on-the-treadmill)
- **Running (FDM-THQ), test-retest over two days:** ICC for Fmax was acceptable (ICC ≥ 0.7); contact time and flight time reliability were predominantly good (ICC ≥ 0.8) to excellent (ICC ≥ 0.9). On validity, the Zebris **significantly underestimated Fmax versus Pedar-X**, and the underestimation bias **increased with running speed** — [Reliability and validity of the Zebris FDM-THQ instrumented treadmill during running trials, PubMed 29785869](https://pubmed.ncbi.nlm.nih.gov/29785869/)
- **Walking (FDM-THM-S):** highly reliable peak forefoot and heel forces between trials and days, but only moderate reliability of peak vGRF during running; the authors note further research is needed to establish accuracy and validity for comparing cohorts or establishing intervention effects — [Reliability of spatiotemporal and kinetic gait parameters determined by a new instrumented treadmill system, PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/)
- Clinical use continues regardless: a force-sensing treadmill gait analysis system detected gait abnormalities in haemophilia patients without arthropathy — [Mawarikado et al., Haemophilia 2024](https://onlinelibrary.wiley.com/doi/10.1111/hae.14987)
- **Caveat from the search:** FDM-T, FDM-THQ and FDM-THM-S are distinct configurations and results should not be transferred between them.

**Other hardware context**
- Kistler laboratory plates themselves use four piezoelectric load cells — [PMC7338728](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)

### Inferences
- **Zebris is not a comparator for a four-load-cell deck.** A capacitive pressure matrix gets per-limb data by *spatial segmentation* — it sees two separate pressure blobs during double support and attributes each to a foot — so it never faces the decomposition problem at all. The price is that a pressure matrix **cannot measure shear** and its vGRF accuracy is the weak point (underestimated Fmax, worsening with speed). A four-load-cell deck has the opposite profile: good total vertical force, no spatial segmentation, decomposition required.
- **Gaitway 3D is the direct architectural comparator** and it validates the product concept: four strain-gauge sensors under a single belt, with left/right decomposition done in software from the published algorithms. That it cites Davis & Cavanagh, Raison and Bastien is strong evidence that commercial per-limb decomposition is implemented exactly as Q1 describes. But Gaitway measures **three force directions**, so it can run Bastien's fore-aft and lateral stages; a vertical-only deck cannot, and should not claim per-limb 3D forces.
- The absence of any numerical accuracy claim on the Gaitway page, despite the device being commercially mature, suggests the industry standard of evidence for per-limb decomposition claims is "cites the method papers" rather than "publishes device-level validation". That is both an opportunity (device-level validation would be differentiating) and a caution (no competitor benchmark exists to match).

### Gaps
- **I found no independent peer-reviewed validation of Gaitway 3D's left/right decomposition.** The product page's reference list does not identify which references validate the device.
- I found no evidence that **h/p/cosmos** (named in the assignment) itself performs per-limb force decomposition; h/p/cosmos treadmills are commonly the mechanical base under a Zebris FDM sensor matrix, so per-limb data in those systems comes from Zebris's pressure matrix. I did not retrieve an h/p/cosmos source to confirm this, so it should be checked.
- **Bertec split-belt** was not reached in my searches; as a dual-plate system it is a gold-standard comparator rather than a decomposition system, so it is less relevant, but I have no sourced specification for it.
- No source gives platform dimensions for Gaitway 3D.

## Q8. Sampling rate, platform geometry, and the accuracy limits of four-load-cell versus six-component designs

### Takeaway
There is no accepted sampling-rate standard for CoP; practice ranges from 50–60 Hz for postural validation up to 1000 Hz for sprint work, with 120–240 Hz typical for gait, and filtering choice matters as much as rate. The structural limit of a four-load-cell design is that it recovers only Fz and the two CoP coordinates — no shear, no free moment — which rules out the shear-decomposition and moment-balance methods outright.

### Cited Findings

**Sampling rates in practice**
- Sprint running CoP: **1000 Hz**, "as common with many previous studies into sprint running" — [Calculating centre of pressure from multiple force plates for kinetic analysis of sprint running (ResearchGate record)](https://www.researchgate.net/publication/313393614_Calculating_centre_of_pressure_from_multiple_force_plates_for_kinetic_analysis_of_sprint_running)
- Force plates in the insole-comparison gait study: **1000 Hz, downsampled to 60 Hz** for comparison with 60 Hz insoles — [PMC7338728](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)
- Force plates as ground truth for the load-cell deep-learning study: **120 Hz**; the load-cell shoe itself sampled at **30 Hz** — [Kim et al., Sensors 2025, PMC12157732](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12157732/)
- Pressure-mat CoP excursion: **240 Hz** — [PMC7663129](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7663129)
- A portable clinical plate records internally at **200 Hz** but its validation was run at **50 Hz** — recording rate and validation rate are not the same thing — [The validity of a portable clinical force plate in assessment of static postural control](https://link.springer.com/article/10.1186/2045-709X-20-15)
- Arsalis Gaitway 3D advertises **up to 10 kHz** — [Arsalis](https://www.arsalis.com/products/instrumented-treadmill/)
- **No single accepted sampling-frequency standard for CoP accuracy emerged from the search.**

**Filtering**
- In the sprint study, optimal cut-off frequencies were determined by the **autocorrelation method of Challis (1999)**, with **CoP cut-offs averaging 83 Hz** — [ResearchGate record](https://www.researchgate.net/publication/313393614_Calculating_centre_of_pressure_from_multiple_force_plates_for_kinetic_analysis_of_sprint_running)
- Low **and inconsistent** sample rate (time jitter) was itself identified as a validity concern for the Wii Balance Board, separate from the nominal rate — [PMC4239899](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4239899/)
- Errors in active peak force increased as sampling frequency decreased (pressure insoles, running) — relevant to peak force rather than CoP — [Effect of pressure insole sampling frequency on peak force accuracy during running (bioRxiv)](https://www.biorxiv.org/content/10.1101/2022.05.18.492523.full.pdf)

**Achievable accuracy of low-cost four-cell designs**
- A Wii Balance Board validation placing known masses on a laboratory plate reported **total force uncertainty within 9.1 N and CoP location within 4.1 mm** — [Bartlett et al. 2014, Accuracy of force and center of pressure measures of the Wii Balance Board](https://scholarblogs.emory.edu/neuromechanicslab/files/2024/06/Bartlett-et-al-2014.pdf)
- A separate validation drove CoP displacement with a **controlled inverted pendulum**, giving the reference signal known dynamics — [PMC4239899](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4239899/)
- Vendor claim (treat with caution): a 2024 study reporting **mean bias under 2.5 N for GRF and 0.1 mm for CoP** against laboratory plates — [VALD, Buyer's Guide to Force Plates](https://valdhealth.com/news/buyers-guide-to-force-plates)

**Geometry and resolution effects**
- The four-corner formula scales the difference-over-sum by **l/2 and w/2**, so CoP sensitivity to a given corner-force error scales directly with platform dimension — [PMC5377905 / PMC5375905](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5375905/)
- Insole ML CoP width agreement with force plates was poor (**r = 0.11**), attributed to the small number of sensors across the insole's width, especially in smaller sizes — [PMC7338728](https://pmc.ncbi.nlm.nih.gov/articles/PMC7338728)
- Load-cell CoP accuracy in the three-cell shoe study: **AP CoP r = 0.76–0.99, RMSE ≈ 8.5 mm (turning) to 17.3 mm (running)**; **ML CoP r = 0.22 (uphill) to 0.86 (straight), RMSE 5.64 mm (straight) to 10.52 mm (uphill)**. Authors' stated limitation: "the current sensor configuration was not sufficient to capture variability in the ML direction" — [Kim et al., Sensors 2025, PMC12157732](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12157732/)
- In the same study, vertical GRF correlation ranged **0.91 (downhill) to 0.99 (straight)**; AP GRF **0.89–0.99**; ML GRF was weakest at **0.67–0.91**. Only healthy young adults were tested and the authors state the approach is "not yet suitable" for populations with more variable gait, such as stroke patients — [same](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12157732/)

**Four-load-cell versus six-component: the structural limit**
- Load-cell-only platforms measure only vertical force and **cannot estimate shear or horizontal components** — [force-platform references](https://en.wikipedia.org/wiki/Force_platform)
- The general CoP equation requires **Mx, My and the plate offset dz**; the four-cell corner-difference form is the substitute when no moment output exists — [same](https://en.wikipedia.org/wiki/Force_platform)

### Inferences
- **Which methods a vertical-only four-cell deck forfeits, explicitly:**
  - Bastien 2019 fore-aft decomposition — needs **total Fy** as a model predictor. Forfeited.
  - Bastien 2019 lateral stage — needs **transverse moment Mz** balance. Forfeited.
  - Villeger 2014 moment decomposition (frontal/sagittal/transverse) — needs **Mx/My/Mz**. Forfeited.
  - Yu 2025 PI-ResRNN as published — consumes all **five** channels. Forfeited as published.
  - The `F_X · dz` CoP correction — needs **Fx**. Forfeited (small but systematic error at heel-strike and push-off).
  - Davis & Cavanagh 1993, Raison ΔCoP² event detection, Meurisse 2016 vertical reconstruction, butterfly/gait-line analysis, all CoP excursion/velocity/sway metrics — **all available.**
- On sampling rate, the cited practice supports a tiered answer: **≥100–120 Hz is adequate for walking CoP and for the decomposition event detection** (matching the force-plate ground truth used in the 2025 load-cell study and the 83 Hz CoP filter cut-off found in sprinting), **200–250 Hz for comfortable headroom on gait-line velocity and heel-to-forefoot timing**, and **≥1000 Hz only if impact peaks during running are a target metric**. The 83 Hz empirical CoP cut-off implies a Nyquist requirement above ~170 Hz to avoid aliasing the CoP signal itself. This synthesis is mine; no single source states it.
- **Sample-clock jitter is called out as a distinct validity threat** in the Wii literature and is the more actionable engineering requirement than raw rate: a deterministic, low-jitter clock across all four channels matters more than the nominal frequency, because CoP is a *ratio* of simultaneously-sampled channels and any inter-channel skew appears directly as CoP noise. Simultaneous (not multiplexed) ADC sampling of the four cells is the design implication.
- **The realistic CoP accuracy target for a well-built four-cell deck is single-digit millimetres** — 4.1 mm for a consumer-grade four-cell board with known static masses, versus the ~10 mm CoP white noise implicit in Raison's threshold derivation on laboratory plates during dynamic gait. Dynamic gait CoP noise is roughly an order of magnitude worse than static-mass CoP accuracy, so static calibration figures should not be quoted as dynamic performance.
- **Geometry: the large deck dimension is a direct noise multiplier.** Because CoP error scales as (l/2)·σ_F/ΣF, a long treadmill deck amplifies load-cell noise into AP CoP error more than a short laboratory plate does — and the ML axis, being short, is quieter in absolute terms but is also where the *signal* is smallest. The repeated independent finding that ML measures are the weakest (insole r = 0.11, load-cell shoe r = 0.22, Villeger 18% lateral force error) means ML-dependent features — lateral symmetry, ML excursion, and any mediolateral-inflection event detector — are the ones to treat with most scepticism on this hardware.

### Gaps
- **No source gives a minimum sampling rate requirement for CoP measurement.** The search explicitly returned no accepted standard; the tiered recommendation above is synthesised from observed practice.
- **No source gives platform-geometry guidance** (deck length/width, cell placement) for CoP accuracy on an instrumented treadmill. The error-propagation reasoning is mine.
- **No head-to-head study of a four-load-cell vertical-only deck versus a six-component force plate** was found. The comparison above is assembled from the structural limits of each and from separate validations of each class.
- No source addressed load-cell crosstalk, creep, hysteresis or temperature drift specifications for gait-grade platforms.
- The VALD figure (2.5 N, 0.1 mm) is a vendor buyer's guide citing a study it does not fully identify; it should not be used without tracing the primary source.
