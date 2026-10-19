# Spatiotemporal gait metrics derivable from vertical ground reaction force (vGRF) on an instrumented treadmill, and their clinical validation

Scope note: this file covers treadmill walking specifically, and flags throughout where a method needs anteroposterior (AP) or mediolateral (ML) *shear* force (which a vertical-load-cell deck cannot provide) versus where it needs only vertical force (which a 4-load-cell deck can provide, including centre-of-pressure).

---

## Q1. Which spatiotemporal parameters can be derived from vGRF alone?

### Takeaway
Everything temporal — initial contact (IC), terminal contact (TO), step time, stride time, cadence, stance, swing, single support, double support, gait cycle duration — follows directly from a per-limb IC/TO event sequence, which force data gives directly by thresholding. Spatial parameters (step/stride length) are not measured but *reconstructed* as `time × belt speed`, which is only valid if the walker does not drift fore/aft on the belt. The hard constraint is not vertical-vs-shear force, it is **limb attribution**: a single summed vGRF trace from one undivided deck cannot by itself say which foot is loaded, so step/stance/swing/single-support per side requires either two independently instrumented belts or a centre-of-pressure (CoP) / decomposition step.

### Cited Findings
- Force platforms are "particularly well-suited for gait event detection because FC and FO can be determined directly from thresholds in force recordings" — [Roerdink et al. 2008, J Biomech 41(12), via search summary](https://www.sciencedirect.com/science/article/abs/pii/S0021929008003199)
- Roerdink et al. ran **online gait event detection from a single large force platform embedded in a treadmill** (12 healthy participants), using CoP profiles, with offline kinematics as gold standard; they report "strong agreement for spatial and temporal gait parameters compared to kinematic data" — [Roerdink et al. 2008 (VU Amsterdam record)](https://research.vu.nl/en/publications/online-gait-event-detection-using-a-large-force-platform-embedded/); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0021929008003199)
- **Step/stride length by belt-speed integration**: "One commonly applied method to calculate spatial gait parameters during treadmill gait is based on the timing of gait events combined with belt speed. Stride length is equal to stride time multiplied by belt speed; step length is equal to step time multiplied by belt speed." The same source cautions results "are only precise if the subject doesn't drift on the belt," so length measures "should be corrected for global displacement" — [Using Positional Heel-marker Data to More Accurately Calculate Stride Length for Treadmill Walking (arXiv:1710.09030)](https://arxiv.org/abs/1710.09030)
- Worked numeric example of the same formula in a treadmill patent: 7 km/h belt speed, 0.22 s between touchdowns → 0.22 × (700000/3600) = 42.77 cm — [US 11,452,917](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11452917)
- Alternative geometric definition used as the reference in that paper: `Stride Length = RSL + LSL`, each step length being the horizontal heel-to-heel distance at heel strike — [arXiv:1710.09030](https://arxiv.org/abs/1710.09030)
- **Limb attribution needs two belts or decomposition.** A split-belt validation paper states that putting force sensing under one moving belt "requires signal decomposition to differentiate the ground reaction forces of the left and right foot while stepping", and that splitting the signal "may lead to loss of detail in data, which may be essential in gait analysis" — [Characterization and validation of a split belt treadmill (PMC5323434)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5323434/)
- A commercial statement of the same constraint: an instrumented treadmill "must have two belts in order to record forces from the right and left feet independently"; a front/back tandem arrangement "transforms front/back forces into left/right limb forces in real-time" — [AMTI Tandem Instrumented Treadmill](https://www.amti.biz/product/tandem-instrumented-treadmill/)
- Even with two belts, conventional force-threshold detection fails for cross-steps "because both feet are in contact with only one belt" — [Cross-step detection using centre-of-pressure based algorithm, J NeuroEng Rehabil 2024 (PMC11403786)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11403786/)
- The CoP signal used by that algorithm came from **four force transducers under a single belt**, sampled at 200 Hz; CoP is defined there as "the point where the vertical ground reaction force is applied" — [PMC11403786](https://pmc.ncbi.nlm.nih.gov/articles/PMC11403786/)

### Inferences
- Because CoP is the point of application of the *vertical* force, the AP and ML **CoP coordinates are computable from the vertical loads at four known load-cell positions alone** — no shear transducers required. So the Roerdink-style CoP ("butterfly") family of methods, and the 2024 cross-step algorithm, are available to a vertical-only load-cell deck. What is *not* available to such a deck is true AP/ML shear force (propulsion/braking forces, friction-based events), nor free moment.
- On an undivided deck, total vGRF does not return to zero between steps during walking (double support keeps the sum loaded), so the textbook "force crosses 20 N" rule cannot be applied to the summed trace. The threshold rule is only directly applicable per-belt (split-belt) or per-limb after decomposition; otherwise CoP-transition logic is the practical route. This is an inference from the single-belt decomposition requirement above, not a directly quoted finding.
- Single support is not an independent measurement: single support of one limb = contralateral swing, and `stride = 2× double support + 2× single support`. So a vGRF event sequence over-determines these, which is why reliability tables report identical SEM for swing and single support (see Q5/Q7, Reed et al.).

### Gaps
- I found no study that reports the *error* in treadmill step length computed purely as `step time × belt speed` against a marker-based heel-to-heel measure. The arXiv heel-marker paper argues the correction is needed but I could not extract its numeric comparison (the PDF returned as binary and no text extractor was available locally).
- No source found that quantifies accuracy of left/right decomposition from a single summed vGRF trace in humans; a 2011 review notes "there are no studies to date that have compared the lower extremity kinematics between split-belt and single-belt treadmill walking" — [Kinematic comparison of split-belt and single-belt treadmill walking](https://www.sciencedirect.com/science/article/abs/pii/S0966636211003985)

---

## Q2. Event-detection algorithms and force thresholds from vGRF; timing error vs gold standard

### Takeaway
The standard algorithm is a fixed force threshold: IC = first sample where vGRF rises above the threshold, TO = first sample where it falls below. Published thresholds cluster at **5–20 N**, with 20 N the most common and 10 N or lower specifically recommended for toe-off; percent-body-weight thresholds (e.g. 50% BW) are substantially worse. With a clean per-limb force signal, threshold detection is accurate to roughly **≤10 ms median** against a footswitch reference; CoP-based detection on a single platform is good for foot contact but detects foot-off about **31 ms late**.

### Cited Findings
- Standard method: "determine when the force has risen above (IC) and fallen below (TO) a specific force threshold (ex. 20 N)" — [Evaluation of Different Pressure-Based Foot Contact Event Detection Algorithms (PMC10007471)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10007471/)
- Predefined vGRF thresholds "typically ranging from 5 to 20 N" are described as the gold standard for heel-strike/toe-off — [Detecting Heel Strike and Toe Off Events Using Kinematic Methods and LSTM Models (arXiv:2503.00794)](https://arxiv.org/html/2503.00794v1)
- **Tirosh & Sparrow 2003** (J Appl Biomech 19(2):178–184) compared five vertical force thresholds against a 3D optoelectronic system: "during normal and fast walking, any threshold from 0 to 50 N predicted heel-contact time", whereas for toe-off "thresholds of 10 N or lower" are recommended. Reported average timing differences: **10.0 ms (heel contact) and 16.5 ms (toe-off) for normal walking; 7.4 ms and 13.5 ms for fast walking** — [Journal of Applied Biomechanics 19(2) abstract](https://journals.humankinetics.com/view/journals/jab/19/2/article-p178.xml); [ResearchGate record](https://www.researchgate.net/publication/292004898_Identifying_Heel_Contact_and_Toe-Off_Using_Forceplate_Thresholds_With_a_Range_of_Digital-Filter_Cutoff_Frequencies)
- **Rouhani et al. 2015** (Gait & Posture 41(3):863–866), split force-plate treadmill, 11 subjects walking >20 min, footswitch reference. Compared a 20 N threshold (HS_20N), a 50% body-weight threshold (HS_50%), and a linear-approximation reconstruction of the contaminated force profile. On **uncontaminated** plate data, median maximum error ≈ **9 ms** for both 20 N and linear approximation (maxima 23 ms and 37 ms); the 50% BW threshold was much worse at **median 52 ms (max 74 ms)**. On **contaminated** data (foot partly landing on the contralateral plate), the 20 N threshold degraded to **median 23 ms error** and produced large stride-interval errors in some subjects, while the other two methods were not affected the same way — [PubMed 25800003](https://pubmed.ncbi.nlm.nih.gov/25800003/); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636215000697)
- **CoP-based detection on one platform**: "Good correspondence was achieved between online FC detections using center-of-pressure profiles and those derived offline from kinematic data, whereas FO was detected **31 ms too late**" — [Roerdink et al. 2008](https://www.sciencedirect.com/science/article/abs/pii/S0021929008003199)
- **CoP relay/threshold algorithm, 2024** (single-belt treadmill, 4 transducers, 200 Hz): adaptive per-axis thresholds at a ratio of 0.2 between tracked upper/lower CoP limits; AP clamp 0.04 m, ML minimum 0.05 m. Both AP and ML CoP crossings in the same phase → a normal event (LHS/RTO/RHS/LTO); AP crossed twice with no ML crossing → cross-step. Simulated real-time accuracy vs an offline AP-peak reference: native gait **HS absolute mean error 78 ms (SD 32), TO 126 ms (SD 47), 100% success**; cross-steps **HS 64 ms (SD 28), TO 111 ms (SD 47), 94% (SD 11%) success** (2120/2253 cross-steps recognised). Errors were positive (late) and TO errors consistently larger than HS — [PMC11403786](https://pmc.ncbi.nlm.nih.gov/articles/PMC11403786/)
- Other thresholds in current use: **5% of body weight** as contact threshold in one study — [PMC10007471](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10007471/); **15 N** with force plates at 1000 Hz — [On the accuracy of methods identifying gait events (bioRxiv 2025)](https://www.biorxiv.org/content/10.1101/2025.03.09.642234v1.full); **50 N** for step detection (plus a 25 N Nexus step-detection threshold and a 20 N force-plate analog threshold) in a 246-subject treadmill normative dataset — [Senden et al., Normative 3D gait data (PMC10912446)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10912446/)
- Threshold value changes timing by about one frame in running: "a threshold of 20 N resulted in foot-strike being detected one frame later and toe-off one frame earlier than when using a threshold of 10 N" in a large share of cases — [Identifying gait events without a force plate during running](https://www.sciencedirect.com/science/article/abs/pii/S0966636210001670)
- Acceptability benchmarks quoted in the literature: "no higher than ±20 ms" as a commonly cited acceptability level, and "within 50 ms" as acceptable for real-time gait event detection in wearable systems — [arXiv:2503.00794](https://arxiv.org/html/2503.00794v1)

### Inferences
- The threshold asymmetry (any value 0–50 N works for IC; ≤10 N needed for TO) follows from loading rate: vGRF rises steeply at heel contact so the crossing time is insensitive to threshold, but unloads gradually at push-off so a high threshold truncates late stance. Practical consequence for a load-cell deck: use a low threshold (10 N) and accept that noise floor, rather than a %BW threshold, which Rouhani showed costs ~40 ms.
- A deck that only has CoP (no per-belt separation) should expect foot-off to be systematically **late** (31 ms in Roerdink; 111–126 ms in the 2024 real-time algorithm) and may want a fixed offset correction; foot contact is the trustworthy event.

### Gaps
- I could not access the Tirosh & Sparrow full text (HTTP 403), so I cannot confirm whether the 10.0/16.5 ms figures are the *threshold-vs-kinematic* difference or the *acceleration-algorithm-vs-force* difference, nor the exact filter cutoff at which they were obtained. Treat them as "order 10–20 ms" rather than exact threshold error.
- No study found that reports IC/TO timing error as a function of load-cell noise floor or deck natural frequency.

---

## Q3. Filtering before event detection; effect of filter choice on event timing

### Takeaway
There is no single standard cutoff for vGRF before event detection. Published treadmill/force-plate studies use low-pass filters anywhere from 8 Hz to 100 Hz, with ~30 Hz a common choice for GRF in gait studies and 6 Hz for markers. The documented risks are (a) low cutoffs (≤25 Hz) erase the impact transient that event detection keys on, and (b) causal (single-pass) Butterworth filters introduce a frequency-dependent delay, which is why zero-lag dual-pass filtering is used when event timing is the output. I found no paper that directly quantifies IC/TO timing shift in ms as a function of GRF cutoff.

### Cited Findings
- Primary example of actual practice in a treadmill gait study: markers low-pass filtered at **6 Hz**, GRF at **30 Hz**; GRF sampled at 2000 Hz, markers at 100 Hz — [Lewek & Randall 2011, J Neurol Phys Ther (PMC3042506)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3042506/)
- Low cutoffs destroy the impact peak: 10, 15 and 25 Hz filters "eliminated impact peaks during drop landings", whereas conventional 50 and 100 Hz cutoffs retained higher impact peaks; the authors note cutoffs must be robust "0–100 milliseconds after ground contact" — [FFT-determined low-pass filter cut-offs ... vertical ground reaction force](https://www.researchgate.net/publication/401141218_FFT-determined_low-pass_filter_cut-offs_increase_vertical_ground_reaction_force_attenuation_and_decrease_waveform_similarity_compared_with_conventional_cut-offs_during_countermovement_and_drop_jumps)
- The trade-off stated explicitly for gait event detection: the cutoff "must be low enough to attenuate signal noise, including high-frequency oscillations such as impact spikes during initial contact, but also higher than the primary frequency of human gait" — [Assessing Smart Algorithms for Gait Phases Detection in Lower Limb Prosthesis (arXiv:2310.09735)](https://arxiv.org/pdf/2310.09735)
- Causal Butterworth filters delay the signal in a frequency-dependent way: "a causal low-pass filter with a fixed order and cut-off frequency will delay sinusoids of different frequencies by different amounts"; a closed-form solution exists and can be used "to adjust the order and/or cut-off frequency in order to achieve a desired delay" — [A general solution for the time delay introduced by a low-pass Butterworth digital filter, J Biomech](https://www.sciencedirect.com/science/article/abs/pii/S0021929006000480)
- Example of a low cutoff applied to both marker and force data in gait analysis: "4th-order low-pass filter with a standard 8 Hz cutoff frequency commonly used in gait analysis" — [search-surfaced practice, see arXiv:2310.09735 context](https://arxiv.org/pdf/2310.09735)
- Heel-strike transients are themselves a recognised force-plate noise source requiring dedicated handling before filtering — [On improving gait analysis data: heel induced force plate noise removal and cut-off frequency selection for Butterworth filter](https://www.researchgate.net/publication/323648822_On_improving_gait_analysis_data_heel_induced_force_plate_noise_removal_and_cut-off_frequency_selection_for_Butterworth_filter)
- Tirosh & Sparrow's title explicitly pairs force thresholds with "a range of digital-filter cutoff frequencies", and the study tested four cutoff frequencies — [JAB 19(2):178–184](https://journals.humankinetics.com/view/journals/jab/19/2/article-p178.xml)

### Inferences
- For an offline/post-hoc pipeline, zero-lag (forward–backward) filtering removes the delay problem entirely and is the right default. For a *real-time* console reading a load-cell deck, the filter delay is unavoidable and should be budgeted explicitly — the 2024 CoP paper attributes part of its 78–126 ms error to the fact that "real-time filtering adds timing error" ([PMC11403786](https://pmc.ncbi.nlm.nih.gov/articles/PMC11403786/)).
- Because IC timing is driven by a steep rise, a cutoff that attenuates the impact transient biases IC *late*; a cutoff that leaves it in risks spurious early crossings from the heel-strike spike. The cited sources support both halves of this trade-off but none quantifies the net ms bias.

### Gaps
- **No source found that reports IC/TO timing shift in milliseconds as a function of vGRF low-pass cutoff.** This is a genuine hole in the literature as surfaced by these searches; the closest is the generic Butterworth delay solution, which must be applied analytically rather than cited as a measured gait result.
- I could not confirm the widely repeated "zero-lag second-order 60 Hz for vGRF" convention to a primary source and have therefore not asserted it.

---

## Q4. Accuracy of instrumented-treadmill spatiotemporal measures vs motion capture and pressure walkways

### Takeaway
Temporal agreement between an instrumented treadmill and a pressure walkway is tight (95% limits of agreement typically <±2% of gait cycle duration) but spatial agreement is not (up to ±5 cm), and all parameters differ systematically — the authors of the key head-to-head study concluded treadmill values are **not** interchangeable with walkway values. Against kinematic gold standard, a single-platform treadmill shows good foot-contact agreement and a ~31 ms late foot-off. Pressure-matrix treadmills (Zebris) additionally show force drift over longer bouts, which matters for any force-threshold event detector.

### Cited Findings
- **Head-to-head, matched speed: Wearing, Reed & Urry, Gait & Posture 38(3), DOI 10.1016/j.gaitpost.2012.12.017.** 39 healthy adults, GAITRite walkway vs Zebris instrumented treadmill at matched speed. Temporospatial parameters "highly correlated (**r, 0.79–0.95**)". "The 95% limits of agreement for temporal parameters were typically less than **±2% of gait cycle duration**. However, 95% limits of agreement for spatial measures were as much as **±5 cm**." "All temporospatial parameters measured via the instrumented walkway were significantly different from those obtained from the instrumented treadmill (P < .01)." Conclusion: treadmill-derived parameters "are not representative of those obtained from an instrumented walkway" — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0966636212004729); [QUT ePrints record](https://eprints.qut.edu.au/219873/)
- **Vs kinematic gold standard (treadmill force platform):** foot contact agreed with kinematics; foot-off detected **31 ms too late**; "strong agreement for spatial and temporal gait parameters" — [Roerdink et al. 2008](https://www.sciencedirect.com/science/article/abs/pii/S0021929008003199)
- **Treadmill as reference for an optical timing gate (running):** OptoGait mounted on an instrumented treadmill showed "excellent agreement" for step rate and step length and "good agreement" for contact time — [Agreement Between the OptoGait and Instrumented Treadmill System (PMC7739620)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7739620/)
- **Treadmill as reference for a portable IMU system:** RehaGait showed "good to excellent validity" for stride length, cadence and stride time against an instrumented treadmill in healthy younger adults; walking speed computed from the pressure data "underestimated tachometer speed at all speeds and slopes" — [Validity and reliability of a portable gait analysis system (J NeuroEng Rehabil 2016)](https://link.springer.com/article/10.1186/s12984-016-0115-z); [PMC4719749](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4719749/)
- **Zebris FDM-THQ vs Pedar-X insoles (running, 20 men):** ICC "acceptable (ICC ≥ 0.7)" for peak vertical force; contact time and flight time reliability "predominantly good (ICC ≥ 0.8) to excellent (ICC ≥ 0.9)". The Zebris "significantly underestimated Fmax when compared with the Pedar-X", with underestimation growing at higher speeds — [PubMed 29785869](https://pubmed.ncbi.nlm.nih.gov/29785869/)
- **Force drift over a 10-minute walking bout on a pressure-pad treadmill:** "an evident decline in the measured VGRF and impulse over time for both trials"; the Zebris system "consistently yielded the lower VGRF values during the second trials"; authors conclude the treadmill "is unreliable in measuring VGRF during walking, and a 10 min break is not enough for the embedded sensors to recover their sensitivity" — [A Pressure-Pad-Embedded Treadmill Yields Time-Dependent Errors in Estimating Ground Reaction Force during Walking (PMC8401449)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8401449/)
- Conflicting reliability reports for Zebris force measures: Nüesch et al. "reported highly reliable peak forefoot and heel forces measured between-trials and days", while Van Alsenoy et al. "reported only moderate reliability of peak VGRF" for running at increasing speeds — [as summarised in PubMed 29785869 context](https://pubmed.ncbi.nlm.nih.gov/29785869/)
- At matched speeds, treadmill walking produces systematically shorter steps: "all our participants had smaller average step and stride lengths on the treadmill compared to overground" — [Use Treadmills with Caution (PMC13302541)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13302541/)

### Inferences
- The split in the Wearing/Reed/Urry result (temporal tight, spatial loose) is exactly what the belt-speed-integration model predicts: timing is measured directly, length is inferred, and any fore/aft drift or speed-setting error maps straight into a length error of several centimetres. A console computing step length from belt speed should quote a ±5 cm-class uncertainty, not a ±1 cm one.
- The Zebris force-drift finding is a capacitive-pressure-matrix problem, not inherent to load cells; strain-gauge load-cell decks would not be expected to share it, but no source was found that tests load-cell deck drift over long bouts.

### Gaps
- Could not retrieve the WalkerView instrumented treadmill validity paper's numbers (fetch redirect loop) — [PMC8309770](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8309770/) is the record if needed.
- No study found that compares a **load-cell (strain-gauge) instrumented treadmill** head-to-head against optical motion capture for spatiotemporal parameters with reported ICC/LoA. The available head-to-head data is treadmill-vs-walkway (Zebris pressure matrix) and treadmill-CoP-vs-kinematics (Roerdink).
- Explicit ICC values for the treadmill-vs-walkway comparison were not available in the abstract (only Pearson r 0.79–0.95).

---

## Q5. Normative values for healthy adults, and speed dependence

### Takeaway
On an instrumented treadmill at self-selected speed, healthy adults sit at roughly **110–116 steps/min cadence, ~1.04–1.10 s stride time, ~0.52–0.55 s step time, 62–63% stance, 37–38% swing, 37–38% single support, 24–26% double support, 60–64 cm step length**. Overground older-adult norms are similar for stance/swing but show higher double support (~28%). Across increasing speed, cadence rises and double support falls; stance% falls and swing% rises.

### Cited Findings — instrumented treadmill, healthy adults (the most directly applicable source)
**Reed, Urry & Wearing 2013, BMC Musculoskelet Disord 14:249** — Zebris FDM-THM-S capacitance pressure platform in a treadmill, 7,168 sensors (~0.85 cm each), 150 × 50 cm belt, 0% grade, **sampled at 120 Hz**; 33 healthy adults, 3 sessions — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/); [Springer](https://link.springer.com/article/10.1186/1471-2474-14-249)

| Parameter | Session 1 | Session 2 | Session 3 |
|---|---|---|---|
| Cadence (steps/min) | 110.3 (9.8) | 111.3 (9.6) | 115.7 (8.8) |
| Stride time (ms) | 1097 (102) | 1087 (92) | 1043 (79) |
| Step time L / R (ms) | 548 (51) / 549 (51) | 544 (48) / 542 (45) | 522 (41) / 521 (38) |
| Stance phase (% GC) | 63 (2) | 63 (2) | 62 (1–2) |
| Swing phase (% GC) | 37 (2) | 37 (2) | 38 (1–2) |
| Single support (% GC) | 37 (2) | 37 (2) | 38 (1–2) |
| Double support (% GC) | 26 (3) | 25 (3) | 24 (3) |
| Step length L / R (cm) | 59.6 (7.4) / 59.6 (6.8) | 60.7 (8.2) / 60.4 (7.4) | 64.3 (7.5) / 64.1 (7.3) |

Session 3 differed significantly from sessions 1–2 for most parameters (P < .01), i.e. subjects walked faster by the third visit — a familiarisation effect worth noting. — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/)

### Cited Findings — overground norms for comparison
**Hollman et al. 2011, Gait & Posture — normative spatiotemporal gait parameters in older adults.** GAITRite electronic walkway (5.6 × 0.9 m, **80 Hz**), n = 294 community-dwelling adults aged 70+ (108 men, 186 women), self-selected speed — [PMC3104090](https://pmc.ncbi.nlm.nih.gov/articles/PMC3104090/)
- Pooled: gait speed **110 ± 19 cm/s** (95% CI 107.8–112.2); cadence **109 ± 13 steps/min**; stride length **122 ± 19 cm**; stance **63.9% GC** (95% CI 63.6–64.2); swing **36.1% GC** (95% CI 35.8–36.4); double support **27.9% GC** (95% CI 27.3–28.5); single support **36.2% GC** (95% CI 35.8–36.6); step width SD 3.2 cm (95% CI 2.9–3.5).
- Sex differences: men vs women — speed ~115 vs ~108 cm/s (difference 7 cm/s, 95% CI 2.7–11.5); cadence ~103 vs ~112 steps/min (difference 8.3); step length ~66 vs ~57 cm (difference 9.0 cm); stride length ~133 vs ~115 cm (difference 17.5 cm); step time 0.58 ± 0.05 vs 0.54 ± 0.06 s; double support time 0.32 vs 0.30 s (p = 0.05); step width 10.0 vs 7.9 cm.
- Normalising gait speed to height eliminated the sex difference (p = 0.219); normalising stride length and cadence to height did not.
- Age effect: speed, step length and stride length similar at 70–79 and lower at 80+; double support time higher at 85+.
- By age group (men | women), stance % GC: 63.2±2.1 | 63.3±3.1 (70–74), 64.0±2.5 | 63.9±3.0 (75–79), 63.8±2.7 | 64.5±2.6 (80–84), 64.9±2.7 | 64.5±2.5 (85+). Double support % GC: 26.3±3.0 | 27.1±4.0, 26.5±2.3 | 28.4±6.4, 27.4±4.7 | 29.0±4.6, 30.3±3.5 | 28.7±4.8.

### Cited Findings — treadmill vs overground, and speed dependence
- Healthy adults at matched normalised speed (0.27 overground vs 0.28 treadmill): treadmill had **shorter stance time (0.65 vs 0.68 s)** and **shorter swing time (0.43 vs 0.45 s)**; double-limb support time (~0.22 s) did not differ significantly — [Riley et al., Biomechanics of overground vs. treadmill walking, J Appl Physiol](https://journals.physiology.org/doi/full/10.1152/japplphysiol.01380.2006)
- Double support fell and cadence rose across slow / self-selected / fast conditions: **~31% / 28% / 27%** double support with cadence **~102 / 115 / 123 steps/min**. *Caveat: this table is from an industry white paper, not peer-reviewed; treat as illustrative* — [Measuring Walking Quality Through iPhone Mobility Metrics (Apple, 2022)](https://www.apple.com/healthcare/docs/site/Measuring_Walking_Quality_Through_iPhone_Mobility_Metrics.pdf)
- Double support "ranges from 18% in young adults to ≥26% in healthy older adults"; typical walking "ranges between 20 and 40 percent, with lower values indicating better balance" — [Plantiga reference page (commercial source)](https://plantiga.com/walk/double-support)
- With ageing, "the swing/single support time remained unchanged ... whereas the stance time increased owing to the increased double support time"; mean velocity ~91 cm/s (SD ~18) in 184 older Korean adults — [Gait Parameters in Healthy Older Adults in Korea, J Mov Disord](https://www.e-jmd.org/journal/view.php?number=542)
- Unimpaired stance:swing is about **60:40**, versus closer to **50:50** in stroke patients — [Symmetry function, Gait & Posture](https://www.sciencedirect.com/science/article/pii/S0966636221002721)

### Cited Findings — open normative datasets with treadmill speed sweeps
- **Senden et al. 2024** — normative 3D gait data, **246 healthy adults (122 M / 124 F), aged 18–91**, on an instrumented treadmill in VR at three speeds: comfortable, 30% slower, 30% faster (comfortable set by a ramp protocol from 0.5 m/s). Age groups 18–29, 30–39, 40–49, 50–59, 60–69, ≥70. **Force plates 1000 Hz, cameras 100 Hz**; step detection used a **50 N** threshold on heel kinematics plus force-plate data (Nexus step-detection threshold 25 N; force-plate analog threshold 20 N). Raw and processed data on OSF (osf.io/t72cw) — [PMC10912446](https://pmc.ncbi.nlm.nih.gov/articles/PMC10912446/)
- **Fukuchi, Fukuchi & Duarte 2018, PeerJ 6:e4640** — 42 healthy volunteers (24 young, 18 older) walking overground and on an instrumented treadmill at **40, 55, 70, 85, 100, 115, 130, 145% of self-selected speed** (expressed as dimensionless Froude number); c3d and ASCII, Figshare DOI 10.6084/m9.figshare.5722711 — [PeerJ](https://peerj.com/articles/4640/); [WBDS dataset page](https://bmclab.pesquisa.ufabc.edu.br/datasets/wbds/)

### Inferences
- The two best-sourced normative sets agree on stance/swing to within ~1% GC (62–63% treadmill vs 63.9% overground older adults) but differ by ~2–4% GC on double support (24–26% treadmill young adults vs 27.9% overground older adults). Part of that is age, part is the treadmill-vs-overground difference Riley et al. documented. A console should not apply overground norms to treadmill data without stating this.
- The Reed et al. session-3 shift (cadence +5 steps/min, step length +4 cm, double support −2% GC relative to session 1) is the size of a real clinical effect, so **treadmill familiarisation must be controlled before any longitudinal comparison**.

### Gaps
- The Senden normative tables are published as PNG image files (Files 08, 14, 20) and are not in the article text, so I could not extract the per-age-group, per-speed cadence/stance/swing/double-support numbers. The numeric tables are retrievable from OSF (osf.io/t72cw) if the report needs them.
- No normative table found for **treadmill** cadence/stance/swing/double support stratified by *walking speed* in a peer-reviewed source. The only speed-stratified double-support figures I found are from a non-peer-reviewed industry document.
- No regression equations (e.g. double support % as a function of dimensionless speed) were found in any source.

---

## Q6. Symmetry indices from spatiotemporal data: formulas and thresholds

### Takeaway
Five formulas are in circulation — ratio index, gait asymmetry (log transform), symmetry index, symmetry angle and the newer normalized symmetry index — all scaled so 0 = perfect symmetry. There is **no accepted standard** and **no validated clinical cut-off**; the most commonly quoted practical threshold is that healthy controls rarely exceed ±5%, with >5–10% taken as asymmetric.

### Cited Findings — formulas
All from the Normalized Symmetry Index paper, which lays out all five side by side. `X_S` = surgical/affected limb, `X_NS` = non-surgical/unaffected limb — [A novel method for measuring asymmetry in kinematic and kinetic variables: The Normalized Symmetry Index (PMC6960348)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6960348/)

1. **Ratio Index (symmetry ratio)**: `RI = (1 − X_S / X_NS) × 100`. 0% = perfect symmetry; unbounded. Limitation: "overly sensitive to small values in the denominator"; not universally recommended.
2. **Gait Asymmetry (log transform)**: `GA = ln(X_NS / X_S) × 100`. 0% = perfect symmetry; unbounded; >100% indicates full asymmetry. Limitation: undefined unless the ratio is positive, so unusable for variables that change sign.
3. **Symmetry Index**: `SI = (X_NS − X_S) / [0.5 × (|X_S| + |X_NS|)] × 100`. 0% = perfect symmetry. |SI| = 100% when one limb is 3× the other. The paper is internally inconsistent on bounds (Results say unbounded; Discussion says bounded −200% to +200%) and does not resolve it; the 200% maximum occurs discontinuously when the two values have opposite signs.
4. **Symmetry Angle**: `SA = (45° − arctan(X_S / X_NS)) / 90° × 100`. 0% = perfect symmetry; >100% = full asymmetry. Rationale: arctan(1) = 45°, so equal limbs give the 45° reference. Limitation: designed for angular data, "does not perform well with other variable types".
5. **Normalized Symmetry Index** (proposed): `NSI_t = (X_NS,t − X_S,t) / [max_t max(0, X_NS,t, X_S,t) − min_t min(0, X_NS,t, X_S,t)] × 100`, averaged across trials. Bounded at ±100%. Requires ≥3 trials; saturates at ±100% over a wide input range if used on a single trial.

Alternative/equivalent statements:
- SI in left/right form: `(X_R − X_L) / [0.5 × (X_R + X_L)] × 100`; 0 = full symmetry; described as "the method most commonly used and cited in publications on gait symmetry" — [Comparison of four methods of calculating the symmetry of spatial-temporal parameters of gait](https://www.researchgate.net/publication/261441374_Comparison_of_four_methods_of_calculating_the_symmetry_of_spatial-temporal_parameters_of_gait)
- Simple ratio form `RI = X_R / X_L`, used for amputee peak velocity, prosthetic alignment, temporal asymmetry in runners and knee OA — [same source](https://www.researchgate.net/publication/261441374_Comparison_of_four_methods_of_calculating_the_symmetry_of_spatial-temporal_parameters_of_gait)
- Vagenas & Hoshizaki variant: `Ia = ((L − R) / max(L,R)) × 100` — [same source](https://www.researchgate.net/publication/261441374_Comparison_of_four_methods_of_calculating_the_symmetry_of_spatial-temporal_parameters_of_gait)
- The symmetry angle was introduced as "a novel, robust method of quantifying asymmetry" and is "a dimensionless measure of asymmetry that is not prone to artificial inflation" — [Zifchock et al., Gait & Posture](https://www.sciencedirect.com/science/article/abs/pii/S0966636207002111)
- **Patterson et al.** compared symmetry ratio, symmetry index, log transformation of the symmetry ratio, and symmetry angle in stroke and recommended standardising on one; their ratio convention puts "the greatest value as numerator and indicat[es] the direction of the asymmetry with a sign", with a ratio of 1 = perfect symmetry; negative values indicate asymmetry toward the non-paretic limb. Their spatial step symmetry was defined as nonparetic step length / paretic step length — [Patterson et al., Evaluation of gait symmetry after stroke, Gait & Posture](https://www.sciencedirect.com/science/article/abs/pii/S0966636209006493); [Patterson et al. 2010, Neurorehabil Neural Repair 24(9):783–790](https://journals.sagepub.com/doi/pdf/10.1177/1545968310372091)
- A post-stroke comparison "supports the recommendations of the symmetry ratio as the equation for standardization" — [Gait Symmetry Assessment with a Low Back 3D Accelerometer in Post-Stroke Patients (PMC6209891)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6209891/)

### Cited Findings — thresholds
- "Values of SF less than 5% indicate good symmetry and values above 5–10% threshold indicate asymmetry"; healthy controls "rarely reach the ±5% symmetry threshold discriminating pathological from normal patterns" — [Symmetry function, Gait & Posture](https://www.sciencedirect.com/science/article/pii/S0966636221002721)
- SI interpretation: "A value of 0 indicates full symmetry, while SI ≥ 100% indicates asymmetry" — [Comparison of four methods](https://www.researchgate.net/publication/261441374_Comparison_of_four_methods_of_calculating_the_symmetry_of_spatial-temporal_parameters_of_gait)
- Phase-proportion reference rather than a symmetry cut-off: unimpaired stance:swing ≈ **60:40**, stroke closer to **50:50** — [Symmetry function](https://www.sciencedirect.com/science/article/pii/S0966636221002721)
- **No consensus exists**: "there is no accepted standard for assessing symmetry making it difficult to compare across studies and establish criteria to guide clinical decision making" — [Patterson et al., Gait & Posture](https://www.sciencedirect.com/science/article/abs/pii/S0966636209006493); and "optimal symmetry ratios are unknown, [and] typical symmetry ratios are also not established" — [as reported in search results from the same literature](https://www.sciencedirect.com/science/article/abs/pii/S0966636209006493)
- The NSI paper "gives no clinical cutoffs for any index" and reports that all five indices agree closely for low-magnitude asymmetry but diverge as asymmetry increases — [PMC6960348](https://pmc.ncbi.nlm.nih.gov/articles/PMC6960348/)
- One device patent proposes a swing-time ratio threshold above 1.9–2.0 to flag impairment; this is a patent claim, not a clinical validation — [US 9,974,478](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9974478)

### Inferences
- For a load-cell console, the symmetry index and symmetry ratio are the defensible choices: both are computable from any pair of per-limb temporal values, and the symmetry ratio is what the post-stroke standardisation literature recommends. The symmetry angle buys little for strictly positive quantities like step time, since arctan of a near-1 ratio is nearly linear — its advantage (immunity to artificial inflation) only matters for variables that approach zero or change sign.
- The practical operating point is the MDC, not a literature cut-off: the Lewek & Randall step-symmetry-ratio MDC of 0.068 between sessions (Q7) is ~6.8% on a ratio scale, which lands almost exactly on the 5–10% "asymmetric" band. So a measured asymmetry below ~7% on a treadmill is not reliably distinguishable from measurement noise session-to-session.

### Gaps
- I could not retrieve the amputee reference-value paper (Springer/BMC returned auth redirects) — [Reference values for gait temporal and loading symmetry of lower-limb amputees, J NeuroEng Rehabil 2018, DOI 10.1186/s12984-018-0403-x](https://jneuroengrehab.biomedcentral.com/articles/10.1186/s12984-018-0403-x). It is the single best candidate source for population-specific temporal symmetry reference intervals and is worth a second attempt.
- Patterson et al.'s own numeric symmetry values for stroke vs control groups were not retrievable (SAGE returned 403), so I cannot state the measured group means or the exact log-transform coefficient they used.
- No ROC-derived, population-validated symmetry cut-off (sensitivity/specificity) was found for any index.

---

## Q7. Minimal detectable change (MDC) and smallest worthwhile change

### Takeaway
On an instrumented treadmill in healthy adults, MDC95 is approximately **±9–11 steps/min for cadence, ±91–128 ms for stride time, ±45–67 ms for step time, ±2% GC for stance/swing/single support, ±3–4% GC for double support, and ±7–9 cm for step length** — i.e. temporal measures are reliable to a few percent while spatial measures are reliable only to 4–6%. In chronic stroke on a split-belt instrumented treadmill, between-session MDC is ~5.5–6.8 cm for step length and 3.2–4.2% GC for stance/double support, with ICCs 0.90–0.99.

### Cited Findings — healthy adults, instrumented treadmill
**Reed, Urry & Wearing 2013**, Zebris FDM-THM-S at 120 Hz, 33 healthy adults. The authors state that RC95% is mathematically identical to MDC95%. Values below are SEM (SEM%), ±RC95% — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/)

| Parameter | Within-day (S2–S3) | Between-day (S1–S2) | Between-day (S1–S3) |
|---|---|---|---|
| Cadence (steps/min) | 3.3 (3%), ±9.0 | 3.4 (3%), ±9.5 | 4.1 (4%), ±11.2 |
| Stride time (ms) | 33 (3%), ±91 | 37 (3%), ±103 | 46 (4%), ±128 |
| Step time, L (ms) | 17 (3%), ±47 | 19 (3%), ±52 | 24 (4%), ±67 |
| Step time, R (ms) | 16 (3%), ±45 | 19 (3%), ±51 | 22 (4%), ±62 |
| Stance phase (% GC) | 1 (2%), ±2 | 1 (2%), ±2 | 1 (2%), ±2 |
| Swing phase (% GC) | 1 (3%), ±2 | 1 (3%), ±2 | 1 (3%), ±2 |
| Single support (% GC) | 1 (3%), ±2 | 1 (3%), ±2 | 1 (3%), ±2 |
| Double support (% GC) | 1 (4%), ±3 | 1 (4%), ±4 | 1 (4%), ±4 |
| Step length, L (cm) | 2.7 (4%), ±7.4 | 3.0 (5%), ±8.4 | 3.4 (6%), ±9.4 |
| Step length, R (cm) | 2.6 (4%), ±7.1 | 3.0 (5%), ±8.4 | 3.3 (6%), ±9.1 |

- For most variables SEM was under 10% of the mean, and temporal parameters were the most consistent. ICCs were **not** reported in this paper. — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/)
- Summarised as percentages: "The minimum change that can be detected with 95% confidence by the instrumented treadmill ranged between **3% and 17% for temporal parameters, 4% and 20% for kinetic parameters, and 14% and 33% for spatial parameters between days**"; the authors add that "further research is needed to establish the accuracy and validity of the system for comparing different cohorts or establishing potential intervention effects" — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/)

### Cited Findings — chronic stroke, split-belt instrumented treadmill
**Lewek & Randall 2011** — split-belt instrumented treadmill with two 6-DoF force platforms; handrail held, harness worn, no body-weight support; markers 100 Hz, GRF 2000 Hz, filtered at 6 Hz and 30 Hz respectively; two 20–40 s trials at self-selected speed, first 9 usable consecutive strides analysed; **vGRF used to identify gait events** (threshold not specified) — [PMC3042506](https://pmc.ncbi.nlm.nih.gov/articles/PMC3042506/)

| Variable | Between-session ICC (95% CI) | Between-session MDC | Within-session ICC (95% CI) | Within-session MDC |
|---|---|---|---|---|
| Paretic step length (cm) | 0.970 (0.924–0.988) | 6.75 | 0.996 (0.992–0.998) | 2.62 |
| Nonparetic step length (cm) | 0.986 (0.963–0.995) | 5.46 | 0.998 (0.996–0.999) | 2.11 |
| Step symmetry (ratio) | 0.956 (0.883–0.983) | 0.068 | 0.991 (0.984–0.996) | 0.032 |
| Paretic swing / nonparetic single support (% GC) | 0.939 (0.845–0.977) | 3.6% | 0.983 (0.968–0.992) | 2.0% |
| Paretic stance (% GC) | 0.939 (0.845–0.977) | 3.6% | 0.983 (0.968–0.992) | 2.0% |
| Paretic double support (% GC) | 0.895 (0.726–0.960) | 4.2% | 0.979 (0.962–0.991) | 2.0% |
| Paretic single support / nonparetic swing (% GC) | 0.963 (0.905–0.986) | 3.2% | 0.995 (0.991–0.998) | 1.2% |
| Nonparetic stance (% GC) | 0.963 (0.906–0.986) | 3.2% | 0.995 (0.991–0.998) | 1.2% |

- MDC was computed via `SEM = SD × √(1 − ICC)`; the paper gives the formula but not the SEM values or per-variable SDs. No step-time/stride-time MDC appears in its tables. — [PMC3042506](https://pmc.ncbi.nlm.nih.gov/articles/PMC3042506/)

### Cited Findings — other populations
- Pooled across pathological populations (stroke, multiple sclerosis, spinal cord injury, chronic low back pain, cerebral palsy), step length MDC ranges roughly **4 to 17 cm** — [as reported in the stroke MDC literature](https://www.researchgate.net/publication/332122569_Minimal_detectable_change_of_kinematic_and_spatiotemporal_parameters_in_patients_with_chronic_stroke_across_three_sessions_of_gait_analysis)
- In chronic stroke across three gait-analysis sessions, "step length exceeded the associated MDC in both the paretic and non-paretic limbs", and some limits of agreement were large — [Minimal detectable change of kinematic and spatiotemporal parameters in patients with chronic stroke](https://www.researchgate.net/publication/332122569_Minimal_detectable_change_of_kinematic_and_spatiotemporal_parameters_in_patients_with_chronic_stroke_across_three_sessions_of_gait_analysis)
- A Kinect v2 stroke study found MDC "excellent for step time and stride measures, moderate for speed and step length, and poor for step asymmetry, swing, and double support time" — [Gait analysis with the Kinect v2, J NeuroEng Rehabil 2019](https://link.springer.com/article/10.1186/s12984-019-0568-y)
- MDC for incomplete spinal cord injury spatial and temporal gait measures has been published separately — [Minimal Detectable Change for Spatial and Temporal Measurements of Gait After Incomplete Spinal Cord Injury](https://www.researchgate.net/publication/235786686_Minimal_Detectable_Change_for_Spatial_and_Temporal_Measurements_of_Gait_After_Incomplete_Spinal_Cord_Injury)
- MDC for gait speed in chronic stroke depends on baseline speed — [Minimal Detectable Change for Gait Speed Depends on Baseline Speed in Individuals With Chronic Stroke](https://www.researchgate.net/publication/332120908_Minimal_Detectable_Change_for_Gait_Speed_Depends_on_Baseline_Speed_in_Individuals_With_Chronic_Stroke)

### Inferences
- The ordering is consistent across both reliability studies and the validity literature: **percent-of-cycle phase measures are the most reliable (±2–4% GC), temporal durations next (3–4% of value), spatial lengths worst (4–6% of value, 5–9 cm absolute)**. This mirrors the Wearing/Reed/Urry validity split and reinforces that belt-speed-derived length is the weak link in a vGRF-only pipeline.
- Within-session MDC is roughly 2–2.5× tighter than between-session MDC (e.g. stroke paretic step length 2.62 vs 6.75 cm). A console that compares a patient to themselves inside one session can resolve much smaller changes than one comparing across visits — worth distinguishing in any change-flagging logic.
- A stance-phase change must exceed ~2% GC (healthy, treadmill) or ~3.6% GC (stroke, between-session) before it can be called real. Double support needs ~3–4% GC. Those numbers are of the same magnitude as the entire healthy-vs-pathological difference for some parameters, which is the central measurement-sensitivity problem for this class of device.

### Gaps
- **No cadence MDC was found for a stroke or other rehabilitation population.** A value of 8.58 steps/min was surfaced attributed to Geiger et al. 2019, but the context was unclear in the search result and I did not verify it against the original paper — do not use it without checking.
- No "smallest worthwhile change" / minimal clinically important difference (MCID) values were found for cadence, stance %, swing % or double support % in any population. The literature surfaced here reports MDC (a measurement-error construct) only; MCID (a patient-relevance construct) appears to be established for gait *speed* but not for these parameters.
- No MDC study found for a vertical-load-cell (non-pressure-matrix, non-split-belt) treadmill specifically.

---

## Cross-cutting: sampling-rate requirements

### Takeaway
No source sets a required minimum rate for force-based gait event detection; the sampling interval sets the error floor, and published instrumented-treadmill studies span 120 Hz to 2000 Hz. At 100 Hz, one sample is 10 ms, which is already the size of the best reported threshold-detection error.

### Cited Findings
- Rates actually used: **120 Hz** (Zebris FDM-THM-S, spatiotemporal reliability) — [PMC3766030](https://pmc.ncbi.nlm.nih.gov/articles/PMC3766030/); **200 Hz** (CoP from four transducers, real-time cross-step detection) — [PMC11403786](https://pmc.ncbi.nlm.nih.gov/articles/PMC11403786/); **1000 Hz** force plates with 100 Hz cameras (246-subject normative dataset) — [PMC10912446](https://pmc.ncbi.nlm.nih.gov/articles/PMC10912446/); **2000 Hz** GRF with 100 Hz markers (stroke MDC study) — [PMC3042506](https://pmc.ncbi.nlm.nih.gov/articles/PMC3042506/); **80 Hz** (GAITRite walkway, normative older adults) — [PMC3104090](https://pmc.ncbi.nlm.nih.gov/articles/PMC3104090/)
- Sampling interval sets the error floor: at ~143 Hz, "one sample difference between the events based on the measured and predicted vertical GRF waveforms equaled ~7 ms due to the relatively low sampling frequency" — [Predicting vertical ground reaction forces from 3D accelerometry (PMC9644164)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9644164/)
- An inertial study at 240 Hz reported "14.05 ± 13.91 ms, which for a sampling frequency of 240 Hz corresponds to 3.36 ± 3.33 samples" — [Estimation of Ground Reaction Forces and Moments During Gait Using Only Inertial Motion Capture (PMC5298648)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5298648/)
- Reference-grade detection is typically done at 1000 Hz with a 15 N threshold — [bioRxiv 2025, sacrum IMU accuracy study](https://www.biorxiv.org/content/10.1101/2025.03.09.642234v1.full)
- One kinematic method "determined 94% of the treadmill events from healthy subjects within one frame (0.0167 s) of the GRF events" — i.e. a 60 Hz frame — [as reported in search results for Zeni-type methods](https://www.researchgate.net/publication/6117642_Two_simple_methods_for_determining_gait_events_during_treadmill_and_overground_walking_using_kinematic_data)

### Inferences
- To keep quantisation error well under the ±20 ms acceptability benchmark cited in Q2, ≥200 Hz per load cell is a sensible floor (5 ms interval), and 1000 Hz matches the reference-grade literature. 120 Hz (8.3 ms interval) is demonstrably sufficient for *spatiotemporal* parameters — Reed et al. achieved ±2% GC MDC at that rate — but is marginal if the goal is per-event timing comparable to published force-plate standards.

### Gaps
- No study found that systematically down-samples force data and reports the resulting IC/TO timing error, so the "minimum adequate rate" is an inference from sample-interval arithmetic, not a measured result.
