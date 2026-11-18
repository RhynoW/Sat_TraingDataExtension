# An Empirical Sensitivity Model for Maneuver Detection from Public Two-Line Elements: Calibration Against Precise Orbit Determination Truth

**Authors:** [Author 1]ᵃ*, [Author 2]ᵃ, [Author 3]ᵇ

ᵃ [Affiliation, address, country]
ᵇ [Affiliation, address, country]

\* Corresponding author. E-mail: [address]

## Highlights

- Public TLE maneuver detection is calibrated against FORMOSAT-7 precise orbits.
- Recall rises from 0.11 for 1–50 m steps to 0.82 for 1–3 km steps.
- 90% detection amplitude grows from 50 m to 500 m with cadence and drag.
- A drag-aware effective SNR improves held-out log loss from 0.141 to 0.124.
- Storm-time drag produces persistent, arc-consistent non-thrust signatures.

---

## Abstract

Public Two-Line Elements (TLEs) are widely used for maneuver screening, but their detection sensitivity depends on residual variability, update cadence, and atmospheric drag. We use publicly distributed FORMOSAT-7/COSMIC-2 precise-orbit products as an independent reference and evaluate a TLE-based detector against 131 verified maneuver events, of which 96 have sufficient TLE coverage for recall analysis. Recall increases from 0.11 in the 1–50 m bin to 0.82 in the 1–3 km bin at the evaluated operating point. A separate May 2024 storm interval produces 21 drag-driven non-thrust signatures, illustrating a distinct false-alarm mode. Controlled injections into real TLE series show that the amplitude required for 90% empirical recall increases from 50 to 500 m across cadence and drag regimes. An empirical detectability relation based on an effective residual scale and a drag-related inter-TLE ambiguity term improves held-out predictive performance relative to an amplitude-only model (log loss 0.124 versus 0.141; AUC 0.977 versus 0.967), with all held-out results using parameters estimated on the calibration period and then fixed. The relation's coefficients are jointly calibrated and parameterization-dependent; the model characterizes detector-level sensitivity under TLE-equivalent perturbations rather than complete end-to-end sensitivity. Under the evaluated FS7 data and detector configuration, routine station-keeping of approximately 18 m was not reliably resolved.

**Keywords:** maneuver detection; two-line elements; precise orbit determination; FORMOSAT-7; detectability; space situational awareness

---

## 1. Introduction

Space situational awareness (SSA) for non-cooperative targets relies almost entirely on the public Two-Line Element (TLE) catalog. TLEs are free, global, and frequently updated, but they are fitted products rather than measurements: their accuracy depends on radar tracking density, SGP4 model error, and update cadence [1, 2], and they carry no covariance [3, 4]. A large literature detects maneuvers from TLE time series [5–7], but a basic question has lacked a direct answer: *how small a maneuver can public TLEs actually reveal, and under what conditions?*

Most published evaluations report detected-event counts or comparisons against operator announcement lists. The former cannot separate true signals from processing artifacts; the latter is limited by the incompleteness and coarse time-tagging of public announcements. Answering the question head-on requires an independent, more accurate orbit truth for the same satellites over the same period. Moreover, quoting sensitivity as a single number conflates three physically distinct contributions — the TLE residual scale, the update interval, and the drag environment — which vary by orders of magnitude across the LEO population.

This paper uses a public data set with rare properties: the FORMOSAT-7/COSMIC-2 (FS7) [8] precise orbit determination product (leoOrb), published by the Taiwan Analysis Center for COSMIC (TACC) [9] in SP3 format at 60 s cadence and covering more than 2,500 days since 2019. FS7 is a six-satellite constellation at approximately 550 km altitude and 24° inclination with chemical propulsion, whose orbit-raising campaigns provide abundant, independently verifiable maneuvers over a wide amplitude range.

The contributions are threefold:

1. We establish an event-level baseline for TLE-based maneuver detection using precise-orbit truth for FS7 targets, including characterization of drag-driven non-thrust signatures during disturbed space-weather conditions.
2. We quantify detector-level sensitivity under controlled TLE-equivalent injections across cadence, residual scale, and drag regimes, while explicitly treating the results as an upper bound on end-to-end performance.
3. We develop and evaluate an empirical detectability relation based on an effective signal-to-noise ratio (SNR_eff), estimate its drag-ambiguity coefficient, and assess its predictive performance using temporally held-out data and blocked cross-validation.

The analysis is intentionally limited to detector-level sensitivity under TLE-equivalent perturbations for the FS7 configuration: no universal physical law, no invariance across detector families, and no complete prediction of end-to-end sensitivity is claimed; the drag coefficient is an empirical scale factor, not a universal physical constant. Cross-constellation transfer of the calibrated relation is reserved for future work.

## 2. Data and Truth Definition

### 2.1 Truth source: TACC leoOrb precise orbits

The leoOrb product distributes SP3-c files at 60 s sampling for the six FS7 satellites (SP3 codes L76–L81, NORAD 44349, 44351, 44343, 44350, 44358, 44353). Each file is a short arc of 126–129 epochs (≈2.1 h); each satellite has 42–59 arcs per day with four- to six-fold overlap between independent solutions. Overlap residuals give a direct estimate of truth quality; based on the inter-solution spread of semi-major axis we adopt **26 m (4σ)** as the smallest *validated SP3-derived event amplitude* — a property of the current pipeline and decision rules, not a physical detection limit.

Two implementation pitfalls fail silently and are documented for reproducibility. (i) Per the SP3-c standard [10], as adopted by the leoOrb distribution [9], positions and velocities are given in an Earth-fixed (ITRF) frame with velocity records in dm/s; computing orbital energy then requires the unit conversion and restoration of the inertial term v_ECI = v_ECEF + ω_E × r (ω_E = 7.292115×10⁻⁵ rad/s). The interpretation is verified numerically: with the correction, |v_ECI| ≈ sqrt(μ/r) holds to the expected precision, while omitting it biases semi-major axis by tens of kilometres without any error being raised. (ii) The 2024 and 2026 releases use different arc-alignment conventions; without resampling to a uniform grid, a "one orbital period" rolling window maps to the wrong number of samples.

### 2.2 TLE data and unit conventions

TLE histories for the six satellites cover January 2024 to August 2026 (≈1,900 records each). The median update interval is 8–12 h over the full history and **21.6 h during the 2025 orbit-raising campaign**; whenever an interval enters a formula we state which period it refers to. All core computations are carried out in SI units; figures and tables report Δa in metres, ȧ in m/day, and Δt in days, with conversions stated where they appear.

### 2.3 A natural negative control

FS7-3 (NORAD 44343) performed its final orbit-raising in May 2025 and has not maintained its orbit since; through the end of the data set (August 2026, ≈15 months, no gaps relevant to the analysis) it decays monotonically. It is a same-constellation, same-processing, free-decay control — a sample class that is otherwise very hard to certify, since one can rarely prove a satellite did *not* maneuver.

### 2.4 Space-weather context

Dst, Kp and F10.7 indices are used to identify geomagnetically disturbed intervals, in particular the May 2024 storm interval analyzed in Section 5.1. Quantitative attribution of residual structure to individual indices is future work; no claim of completed space-weather attribution is made.

### 2.5 Campaign data status

Five orbit-raising campaigns are covered (Table 1). SP3 data have been acquired for all five; SP3-side event building is complete for all five (verified events: 29, 41, 8, 46, 7 respectively). The final campaign (January 2026) is reserved as a test segment that took no part in any calibration.

**Table 1 — Campaign data status.**

| Campaign | SP3 | TLE | Used for injections | Verified events | Role |
|---|---|---|---|--:|---|
| 2024 storm interval (20 d) | yes | yes | no (disturbed) | 87 → 21, all spurious (excluded from the 131) | false-positive case study |
| 2024-07 | yes | yes | quiet segments | 158 → 29 | test |
| 2024-11/12 | yes | yes | quiet segments | 247 → 41 | calibration |
| 2025-05 | yes | yes | quiet segments | 125 → 8 | calibration |
| 2025-07/08 (62 d) | yes | yes | excluded (campaign) | 332 → 46 | main truth set |
| 2026-01 | yes | yes | quiet segments | 94 → 7 | **held-out test** |

### 2.6 Event data lineage

The event populations are summarized in Table 2 and Fig. 1: the 131 verified events (46 from the 2025-07/08 campaign and 85 from the four other campaigns, disjoint) reduce to 96 TLE-comparable events with sufficient TLE coverage before and after the event window, grouped into five amplitude bins (n = 37 / 16 / 18 / 8 / 17); 35 are excluded for insufficient TLE coverage.

**Table 2 — Data and event lineage.**

| population | count | role |
|---|--:|---|
| verified maneuver events | 131 | complete event library (46 + 85, disjoint; storm case study excluded) |
| events from four further campaigns | 85 | 29 + 41 + 8 + 7 (2024-07, 2024-11/12, 2025-05, 2026-01) |
| TLE-comparable events | 96 | recall evaluation (Section 5.3) |
| excluded events | 35 | insufficient TLE coverage; limitations analysis |
| storm candidates | 21 | separate false-positive case study (not maneuvers, not in the 131) |

The 21 storm-interval candidates of Section 5.1 (from 87 raw candidates in the
2024 storm sample) are spurious drag-driven signatures, **not maneuvers, and
are not part of the 131**; they enter this paper only as the false-positive
case study.

Recall estimates in Section 5 therefore apply to the 96 events with adequate TLE coverage and **may not be unbiased estimates for the full set of 131 verified events**. Exclusion is not random: the exclusion rate ranges from 0.00 to 0.54 across campaigns and from 0.18 to 0.35 across amplitude bins; a comparison of amplitude, campaign, and satellite distributions between included and excluded events is given in Section S2 and Fig. S4, and the possibility of selection bias is carried explicitly into the limitations.

### 2.7 Event definition

An SP3-side candidate is a contiguous super-threshold segment of the smoothed-and-differenced semi-major-axis series (Section 3.1). Event time is defined by the segment start, peak, and end epochs. Candidates are screened by **consistency checks**: a candidate is verified when it passes (a) persistence of the mean-level step, (b) agreement among overlapping independent arcs, and (c) a common-mode check that rejects signatures appearing on three or more satellites within ±3 h; (d) the inclination channel is recorded as corroboration for out-of-plane burns and does not enter the verdict. The checks share the same SP3 source and are consistency criteria, not independent pieces of evidence. Over all 1,043 candidates, persistence rejects 52% and the common-mode check 39%; the arc-agreement check rejects none, because 41% of candidates are covered by a single arc and the overlapping arcs of the remainder agree to within 50 m. The common-mode check also rejects coordinated burns: 192 candidates with steps ≥ 1 km, rejected solely by it during orbit-raising campaigns, are not among the verified events. Definitions, rejection counts and failure modes are given in Tables S6–S7. Verified SP3 events are not merged; 40 of 125 consecutive same-satellite pairs are separated by less than 1 h and are evaluated as separate events, sharing a TLE-side decision when they fall within one update interval (Table S8). On the injection side, any number of flags within the tolerance counts as one hit. For injections, the hit tolerance of ±2 samples corresponds to different absolute times at different cadences (±0.7–1.0 d at 1×, up to ±4 d at 4×); a fixed ±1.0 d tolerance is evaluated alongside as a robustness check (Section 4.5).

## 3. Detector and Sensitivity Model

### 3.1 SP3-side detector

The instantaneous semi-major axis is not smooth: Earth oblateness (J2) drives a twice-per-revolution oscillation whose peak-to-peak amplitude for FS7 is **3,480 m** — 7.9 times larger than the largest routine signal of interest. Any detector differencing at the 60 s scale detects J2, not maneuvers. The **differencing gain** — the transfer-function magnitude of lag-L differencing alone, with L and P expressed in the same units (samples) — for the k-th harmonic of period P is

G_diff(k) = 2 |sin(π L k / P)|,

for the backward difference x_n − x_{n−L}, with both the lag L and the period P expressed in samples; it vanishes only when L is an integer multiple of P. The rolling-mean smoothing stage has its own (Dirichlet-kernel) response H_mean(k), which likewise nulls harmonics exactly when the window length is an integer multiple of P; the total response is H_total(k) = H_mean(k)·G_diff(k), and the integer-period rule below applies to each stage separately. Three implementation rules follow: (i) the smoothing window and the differencing lag must both be integer multiples of the orbital period, computed per series from the actual semi-major axis rather than hard-coded; (ii) under the integer-period condition the arithmetic mean cancels harmonics exactly while the median only approximately; (iii) non-integer lags alias residual harmonics into spurious but apparently significant structure. A decomposition on a Starlink series (actual period 96.06 min) quantifies the ranking: an unsmoothed series has 16.975 km peak-to-peak residual; a median filter with a hard-coded 97 min window leaves 1.040 km; a median with the integer 96 min window leaves 0.141 km; the integer-window mean leaves **0.063 km**. The detector therefore uses: uniform 60 s resampling → one integer-period rolling mean → one integer-period difference → threshold at 4× the robust σ (MAD-based). The FS7 orbital period at a ≈ 6,928 km is P ≈ 95.5 min (≈ 96 samples at 60 s); one integer-period smoothing window plus one integer-period differencing lag therefore requires a series of at least 2P ≈ 191 min. Because a single leoOrb arc (126 min) is shorter than this, arcs must be merged into continuous series before analysis (the per-satellite window lengths, computed from each series' actual median semi-major axis, are listed in the released configuration).

### 3.2 TLE-side detectors

For injection experiments the TLE-side detector is a robust threshold detector (MAD-σ on per-step differences) combined with a cumulative-sum (CUSUM) change-point detector. For real-event comparison, the detector fits a local linear trend to TLE semi-major axes in a 3-day window before the event (absorbing the local drag rate), and tests the residual of the first post-event TLE against a threshold with the sign required to match the SP3-derived step.

### 3.3 The sensitivity model

The proposed relation is

SNR_eff(c) = |Δa_maneuver| / sqrt( σ_TLE² + ( c · |ȧ_drag| · Δt )² ),

P(detect) = 1 / ( 1 + exp[ −β ( log₁₀ SNR_eff − log₁₀ SNR₅₀ ) ] ),

with SNR₉₀ = SNR₅₀ · 10^(ln 9 / β); β is defined on the log₁₀ axis and the derivation is given in the appendix. Variables are defined as follows. Δa_maneuver is the semi-major-axis step a maneuver is expected to produce (truth-side or injected); it is distinct from the observed inter-TLE difference Δa_obs,k = a_{k+1} − a_k that the detector actually sees. σ_TLE is an **effective TLE residual scale**: the MAD-based robust standard deviation of detrended single-step differences in quiet windows (MAD × 1.4826 / √2, a robust differencing estimator in the sense of [4], derived for the same TLE histories in a companion study [11]; the /√2 assumes independent identically distributed errors — a lag-1 autocorrelation check accompanies it (Table S21) — and the quantity is deliberately not called the "TLE element standard deviation", since it mixes tracking error, SGP4 averaging, fit-span and processing effects). ȧ_drag is the robust linear drag rate of the window, and Δt the median update interval.

**Status of the coefficients.** The drag-ambiguity scale and the logistic detection scale are *jointly calibrated under the specified model parameterization; their strong parameter correlation limits separate physical interpretation of either coefficient.* Each estimated quantity is defined by its data, method, and use:

| quantity | estimation data | method | use |
|---|---|---|---|
| ĉ = 0.32 | full data | maximum likelihood over a log-spaced grid (c > 0) | descriptive refit |
| CI [0.28, 0.40] for c | full data | profile likelihood: 2[ℓ(ĉ) − ℓₚ(c)] ≤ χ²₁,₀.₉₅ = 3.8416, i.e. ℓ(ĉ) − ℓₚ(c) ≤ 1.9208, where ℓₚ(c) profiles out SNR₅₀ and β | parameter uncertainty of the descriptive refit (not a bootstrap percentile CI; 0.28 is not this interval's bound by construction) |
| c = 0.28 | calibration split | maximum likelihood | fixed for all held-out evaluation |
| corr(log c, log SNR₅₀) = −0.98 | full data | Pearson correlation of (log ĉ, log SNR̂₅₀) across B = 200 cluster-bootstrap replicates (c > 0 by construction); a B = 500 convergence check gives an indistinguishable value (−0.979 versus −0.978; Table S10) — the smaller B is used only for this diagnostic because each replicate requires a full grid refit of c | joint-identification diagnostic |

The correlation of −0.98 is interpreted as strong coefficient covariation — a scale trade-off — not as robust separate identification; jointly determined *predictive* quantities remain stable despite it (e.g., SNR₉₀ carries a narrow CI because it is recomputed within each resample, and the Δa₉₀ predictions of Section 4.4 shift by at most 5% between parameterizations). *Within the specified detector-level logistic model and its profile-likelihood construction, the fixed value c = 1 lies outside the 95% confidence set*; because c is not a physical constant, this is a statement about the model fit, not a rejection of a physical drag fraction. Per-drag-regime estimates are consistent (low 0.28 [0.20, 0.40]; mid 0.32 [0.25, 0.50]; high 0.32 [0.25, 0.50]). Fig. S1 shows the profile likelihood of c and the joint (c, SNR₅₀) likelihood surface with β profiled and the 95% region marked. What *is* identifiable is the structural claim: a model containing the drag term outperforms the amplitude-only model on held-out data (Section 6). Physically, c is *an empirical scale factor for the detector-level drag-related ambiguity and should not be interpreted as a universal physical fraction of orbital decay*. In the logistic link, SNR₅₀ is the scale at which detection probability is 50% and β is the slope with respect to log₁₀SNR (natural-log optimizer outputs are converted accordingly); the logistic P does not model the small-amplitude background-coincidence plateau, which is treated separately (Section 4.5).

### 3.4 Injection design and its position in a validation ladder

Injections are performed at the **TLE post-processing level**: steps (and, in a sensitivity variant, ramps) are added to real TLE semi-major-axis series, preserving real cadence, real noise, and real drag. Fig. 2 shows one injection case. This validates the detector's response to TLE-equivalent perturbations but does not simulate the full chain maneuver → tracking observations → orbit determination/SGP4 fitting → published TLE. All injection results are therefore reported as a **detector-level upper bound under TLE-equivalent perturbations**. The validation ladder has three rungs — post-processing injection (this paper), orbit-state-level injection (modifying mean motion and re-propagating), and observation/OD-level injection (end-to-end) — with the latter two reserved for future work.

The grid: 11 step amplitudes from 20 m to 2 km × cadence decimation {1×, 2×, 4×} × drag terciles of |ȧ|, over 478 quiet windows (40 TLE points each, sliding stride 20, windows containing any single step > 0.3 km or gap > 5 d excluded), totalling 15,774 trials. Per-window (σ_TLE, ȧ, Δt) are measured, not assumed.

### 3.5 Statistical methods

Trials within a window share the same satellite, epoch background, and residual structure and are not independent; nothing is treated as a binomial sample of 15,774. Inference uses cluster bootstrap with the **satellite × window** cluster (478 clusters; 73–94 windows per satellite; median 33 trials per cluster), B = 2,000 resamples, percentile intervals, fixed seed, re-estimating (SNR₅₀, β) and recomputing SNR₉₀ *within* each resample; the CI for c is a profile-likelihood interval. Because adjacent windows overlap by 50%, two robustness checks are reported: a non-overlapping-window subset (241 windows: SNR₅₀ = 3.81, β = 5.43, consistent with the main fit) and a satellite-level bootstrap (six clusters, acknowledged as coarse: SNR₅₀ 95% CI [3.51, 4.07]). Cross-validation uses **blocked folds** — satellite × contiguous time blocks, so that adjacent overlapping windows never straddle folds — reported alongside a plain cluster CV to demonstrate the absence of dependence leakage. Calibration performance and generalization performance are kept distinct throughout; model comparisons use identical data splits, event sets, and operating points, and the differing degrees of freedom of the compared models are stated.

## 4. Controlled Injection Results (Detector Level)

### 4.1 Recall surfaces

The **observed empirical 90% recall floor** — the smallest grid amplitude at which measured injection recall reaches 0.90 (no interpolation); an operating-point quantity, not a physical limit, distinct from the *model-implied 90% probability amplitude* of Section 4.4 — degrades systematically with both cadence and drag regime (Fig. 3):

| cadence \ drag tercile | low | mid | high |
|---|--:|--:|--:|
| 1× (median Δt ≈ 0.3–0.5 d) | 50 m | 100 m | 200 m |
| 2× (≈ 0.9–1.0 d) | 50 m | 100 m | 300 m |
| 4× (≈ 1.7–2.0 d) | 100 m | 200 m | **500 m** |

The measured window σ_TLE is only 1–21 m in every condition; thresholds far exceed it, indicating that the residual scale alone is not the controlling factor.

### 4.2 Cadence ablation

Because the decimation experiment holds the data fixed and lengthens only the sampling interval, it is a controlled ablation: *under the controlled decimation experiment, reduced temporal sampling is associated with a marked degradation in detector sensitivity* (90% floor 50 m → 500 m). Decimation simultaneously changes the available sample count, the CUSUM accumulation behavior, and the σ-estimation background; these confounds are carried to the limitations rather than argued away.

### 4.3 Parameterization protocol and model comparison

**Inference protocol (single main flow).** (i) All model parameters — c, SNR₅₀, β — are estimated on the **calibration split** (windows before 2025-07-01): **c = 0.28, SNR₅₀ = 3.87, β = 5.04 (hence SNR₉₀ = 10.57)**. (ii) They are then **fixed, with no re-estimation**, for every held-out evaluation (temporal test split; real events). (iii) A **full-data refit** (ĉ = 0.32, profile-likelihood 95% CI [0.28, 0.40]; SNR₅₀ = 3.77 [3.58, 3.96]; β = 5.25 [4.96, 5.59]; SNR₉₀ = 9.87 [9.51, 10.20], computed within each of B = 2,000 cluster-bootstrap resamples) is reported **as a descriptive refit only** — it is the paper's best single summary of the relation but is never used to claim held-out performance. Wherever a number derives from the descriptive refit it is labeled as such.

**Table 3 — Temporal hold-out performance** (both models estimated entirely on the calibration split — drag-aware: c = 0.28, SNR₅₀ = 3.87, β = 5.04; amplitude-only: SNR₅₀ = 8.74, β = 4.38 — then fixed and evaluated on the same test split; the main-protocol drag-aware number is **0.1237**):

| Model | held-out log loss | held-out Brier | held-out AUC | calib. slope [95% CI] | calib. intercept [95% CI] |
|---|--:|--:|--:|--:|--:|
| drag-aware (SNR_eff) | 0.1237 | 0.0393 | 0.9773 | 1.22 [1.12, 1.35] | −0.63 [−0.89, −0.39] |
| amplitude-only (Δa/σ) | 0.1413 | 0.0446 | 0.9671 | 1.15 [1.06, 1.26] | −0.26 [−0.52, −0.02] |

(All metrics, including Brier and the calibration slope/intercept with cluster-bootstrap CIs, are computed on the identical temporal test split for both models.)

Sensitivity variants — c fixed at 1 (drag term at the full decay rate: held-out log loss 0.1241) and c fixed at the full-data value 0.32 (0.1236) — are tabulated in Table S12; the latter uses full-data information to choose c and is therefore excluded from the main hold-out table by protocol, even though its result is numerically indistinguishable. All drag-aware variants make near-identical held-out predictions: the apparent movement of SNR₅₀ between parameterizations is a rescaling of the denominator, demonstrated explicitly by evaluating SNR_eff(c) and the corresponding predicted probabilities on common events (Tables S13–S14). The identifiable content is structural (Fig. 4): removing the drag term degrades held-out log loss from 0.124 to 0.141 (the amplitude-only model's per-sample log-likelihood deficit on the full data is 0.021 [0.017, 0.025]). The binned detection-rate curve is approximately monotone in SNR_eff (monotone within a 0.05 tolerance; isotonic-regression R² = 0.9999) over the tested amplitude range — a conditional statement for this data set, injection range, detector, and operating point.

### 4.4 Threshold back-calculation in common units

The **model-implied 90% probability amplitude** is Δa₉₀ = SNR₉₀ · sqrt(σ_TLE² + (c·|ȧ|·Δt)²), evaluated here with the full-data descriptive-refit coefficients (SNR₉₀ = 9.87, c = 0.32; the calibration-only variant, SNR₉₀ = 10.57 with c = 0.28, shifts each prediction by at most 4% relative to the values below; Table S15) at each condition's median (σ, |ȧ|, Δt) after SI conversion — condition-representative values, not per-trial averages. The observed column is the empirical 90% recall floor of Section 4.1 (smallest grid amplitude, same hit tolerance); the two quantities are related but not identical, which is why 515 m (model-implied), 519 m (worked example) and 500 m (observed grid floor) legitimately differ:

| condition | σ_TLE | \|ȧ\| (m/d) | Δt (d) | model-implied Δa₉₀ | observed 90% floor |
|---|--:|--:|--:|--:|--:|
| 1×·low | 1.1 m | 18.5 | 0.33 | 22 m | 50 m |
| 1×·mid | 2.6 m | 46.9 | 0.40 | 64 m | 100 m |
| 1×·high | 5.5 m | 76.8 | 0.53 | 138 m | 200 m |
| 2×·low | 2.2 m | 18.5 | 0.87 | 55 m | 50 m |
| 2×·mid | 5.4 m | 46.4 | 0.99 | 153 m | 100 m |
| 2×·high | 10.7 m | 74.6 | 0.99 | 254 m | 300 m |
| 4×·low | 3.6 m | 18.5 | 1.72 | 106 m | 100 m |
| 4×·mid | 8.7 m | 46.4 | 1.80 | 274 m | 200 m |
| 4×·high | 20.8 m | 76.2 | 1.98 | **515 m** | **500 m** |

Coarse-cadence predictions agree with observed floors; dense-cadence floors are under-predicted by roughly a factor of two. (A layer-specific caveat: the 22 m model-implied value at 1×·low lies below the 26 m smallest validated SP3-derived event amplitude, i.e., below the scale at which the truth pipeline itself has validated events; predictions in that corner are extrapolations of the logistic fit, not truth-validated.) This **prediction residual** coincides with the change of residual serial correlation across cadence (lag-1 autocorrelation of detrended differences: 0.24 → 0.46 → 0.49 for 1×/2×/4×), *consistent with a correlated drag-related component* — a diagnostic observation, not a causal proof; a worked numerical example with every value and unit is given in the appendix.

### 4.5 Metrics suite

Operating points by condition are shown in Fig. 5. Recall under the ±2-sample tolerance and under a fixed ±1.0 d tolerance nearly coincide at 1× and 2×; at 4× the time-based tolerance is lower at small amplitudes because ±2 samples there spans ±4 d. Precision in the detectable range (Δa ≥ 200 m) is 0.56–0.92 across conditions (TP = injections with at least one flag within tolerance; FP = flags before the injection); the flag-level and event-level definitions are compared in Table S20. The false-alarm rate in matched control windows is 1.4 flags per satellite per 30 days pooled over all control windows (flag level; stratified by cadence, drag, and satellite, with an event-level rate, in Tables S16–S17). For Δa ≥ 50 m the injected step is flagged at the first post-event TLE — defined for injections as the first TLE epoch at or after the injected step epoch, and for real events as the first TLE epoch after the truth-interval end t_end — in the majority of trials; detection delay is measured from the same reference epoch, and delay distributions (median, IQR, first-TLE fraction) are reported per cadence in Tables S18–S19. Event fragmentation (more than one attributable flag per injection) occurs in 12–22% of trials, depending on cadence. The low-amplitude detection plateau is **not** pure background: its rate (0.35 pooled for Δa ≤ 50 m) exceeds the coincidence rate of matched pseudo-injections in non-injected control windows (0.16) by +0.19 (cluster-bootstrap 95% CI [0.16, 0.22]); the plateau is a mixture of genuine detections in ultra-quiet windows (σ_TLE of 1–3 m) and coincidental hits. A ramp-injection variant shows the 90% floor unchanged for ramp widths up to 1 d and inflated only 1.5× at 2 d, excluding simple fit-smearing as a dominant effect.

### 4.6 Probability quality on held-out data

Held-out log loss, Brier score, AUC and calibration slope/intercept for both models on the temporal test split are given in Table 3 (calibration before 2025-07-01, test after; c fixed at the calibration-period estimate).

Raw and recalibrated probabilities are reported separately: *the raw probabilities showed mild miscalibration — held-out calibration slope 1.22, cluster-bootstrap 95% CI [1.12, 1.35] (statistically distinguishable from unity), intercept −0.63 [−0.89, −0.39] — although Platt recalibration, fitted on calibration-period out-of-fold predictions and applied unchanged to the test period, produced little change in held-out loss* (0.1238 / 0.0393). Reliability diagrams for both are shown in Fig. S2, with confidence intervals for the slope and intercept of all variants in Table S22. Because discrimination and calibration are distinct, AUC is never quoted alone as evidence of probability quality.

## 5. Real-Event Results (Held-Out Real-Event Validation within FS7)

The real events are FS7 events; this section is a *held-out real-event validation within FS7* — the events took no part in injection calibration — not an external validation on an independent constellation.

### 5.1 Drag-driven non-thrust signatures under storm conditions

In a 20-day 2024 sample containing the May 2024 geomagnetic storm [12], 87 candidates yielded 21 that passed the consistency screening (persistence, arc agreement, and common mode). *The 21 candidates are classified as drag-driven non-thrust signatures because they occur during the storm interval, are uniformly negative-going, and have no corresponding maneuver in the available campaign records; an unannounced maneuver cannot be ruled out absolutely.* The six satellites' mean semi-major-axis rate moved from −49 m/day (pre-storm) to −182 m/day (storm main phase); the 21 spurious events are all negative-going (−47 to −16 m) and all fall within the storm interval. Persistence and cross-arc agreement cannot distinguish "the satellite maneuvered" from "the atmosphere pulled it down": thermospheric density, and with it drag, rises sharply during geomagnetic storms [12, 13], and drag *does* produce persistent, arc-consistent steps. Under the calibrated relation the storm raises the drag-ambiguity term so that steps of this size lie below the model's detection scale, consistent with their character as drag-driven non-thrust signatures rather than detectable events; any candidate must therefore be screened against space-weather indices. *This result demonstrates that persistence and cross-arc consistency alone cannot distinguish a thrust event from a drag-driven decay signature under the evaluated conditions*; its identification is part of the event-level baseline (contribution 1).

### 5.2 Maneuver structure: a staircase, not a ramp

Decomposing the 2025 campaign trajectory of L77 (FORMOSAT7-2, NORAD 44351) at 6 h resolution shows the 25.67 km total raise to be a staircase of **eleven discrete burns of 1.2–2.8 km** (2.81, 1.45, 1.16, 2.56, 2.57, 2.81, 2.56, 2.68, 2.60, 2.51, 2.80 km). The campaign-average rate of ≈400 m/day is therefore an average over discrete burns, not a continuous low-thrust profile. TLE-side total raises for the five active satellites (24.6–25.8 km) agree with the SP3-side 25.67 km, an independent cross-check.

### 5.3 Recall by amplitude bin

**Table 4 — Real-event recall.** *Recall is computed over the 96 TLE-comparable events, not over all 131 verified events, and should be interpreted as conditional on adequate TLE coverage; it is not an unbiased estimate for the full 131-event library* (included/excluded distributions: Fig. S4). Both thresholds; Wilson 95% CIs; model prediction is the mean predicted probability under the full-data descriptive-refit coefficients (c = 0.32, SNR₅₀ = 3.77, β = 5.25), none of which were estimated on real events:

| amplitude bin | n | recall @ 45 m | recall @ unified 3σ | 95% CI (unified) | mean predicted event-level probability* | note |
|---|--:|--:|--:|---|--:|---|
| 1–50 m | 37 | 0.11 | 0.19 | [0.09, 0.34] | 0.29 | mixed with background at small amplitudes |
| 50–100 m | 16 | 0.31 | 0.50 | [0.28, 0.72] | 0.59 | |
| 100–300 m | 18 | 0.50 | 0.61 | [0.39, 0.80] | 0.67 | |
| 300 m–1 km | 8 | 0.62 | 0.62 | [0.31, 0.86] | 0.68 | small sample; partially characterized |
| 1–3 km | 17 | 0.82 | 0.82 | [0.59, 0.94] | 0.65 | prediction residual −0.17 |

\* Mean of per-event model-implied probabilities (descriptive refit); a descriptive comparison column, not an independent recall estimate. Under the calibration-period coefficients (c = 0.28, SNR₅₀ = 3.87, β = 5.04) the bin means are 0.31, 0.61, 0.68, 0.71 and 0.67.

Recall rises monotonically with amplitude (Fig. 6), and the 1–3 km value agrees with an independent campaign-only analysis of the 2025 raise (0.82). Note the granularity caveat: P̄ is the mean of per-event predicted probabilities while recall is a binomial event count; the comparison assumes exchangeability within a bin, and per-event probabilities are provided in the released event table for finer analysis. The intermediate 300 m–1 km bin contains eight events and is only partially characterized. Under the descriptive refit, predicted and observed recall agree within 0.11 in four of five bins (within 0.12 under the calibration-period coefficients); the 1–3 km residual of −0.17 *may reflect differences between event-level association and step-level detectability, long inter-TLE intervals, event aggregation, or selection effects* — a residual decomposition has not been performed and no single cause is asserted.

### 5.4 Threshold trade-off: confusion matrices

**Threshold performance on separate real-event and pseudo-event samples** (not a standard single-population confusion matrix): TP/FN are computed on the 96 comparable real events; FP/TN on quiet-period **pseudo-events** — up to 200 random TLE epochs drawn per satellite from the full 2024–2026 history, each at least 2 days from any verified event, evaluated with the identical pre/post trend estimator, window lengths, and thresholds (n = 1,131 evaluable after coverage screening). FPR = FP/(FP + TN) is per evaluated pseudo-event, pooled across satellites; per-satellite and per-period stratification, the cadence-distribution match between pseudo-events and real events, the treatment of the storm interval, and separately computed CIs for the two samples are given in Tables S24–S27:

| threshold | TP | FN | FP | TN | recall [Wilson 95% CI] | FPR [Wilson 95% CI] |
|---|--:|--:|--:|--:|--:|--:|
| 45 m | 37 | 59 | 64 | 1,067 | 0.39 [0.29, 0.49] | 0.057 [0.045, 0.072] |
| unified 3σ (3.9–6.2 m) | 45 | 51 | 617 | 514 | 0.47 [0.37, 0.57] | 0.546 [0.52, 0.57] |

Stratification (Tables S24–S26): per-satellite evaluable pseudo-events are balanced (187–196 each); the satellite-weighted FPR differs from the pooled value by at most 0.001 (0.052/0.552 versus 0.052/0.553 in an independent redraw of n = 1,142; 0.057/0.546 in the tabulated draw); excluding the May 2024 storm interval changes the FPR by ≤ 0.006. Pooled FPR is therefore not driven by any single satellite or by the storm period. It does vary by half-year (0.000–0.141 at 45 m, highest in 2024-H2; Table S26), so the pooled value averages over periods with different drag and tracking conditions.

Lowering the threshold to the local TLE residual scale (per-satellite 3σ of 3.9–6.2 m from the unified estimator) raises small-amplitude recall but drives the false-positive rate from 5.7% to 54.6% — operationally unacceptable. The interpretation is conditional: *for the evaluated campaign and detector configuration, the 45 m threshold happens to be close to the estimated effective inter-TLE ambiguity scale, resulting in a substantially lower false-alarm rate than a threshold based only on σ_TLE.* A worked σ_eff example accompanies the claim (quiet: σ_TLE ≈ 2 m, |ȧ| ≈ 49 m/d, Δt ≈ 0.9 d, c = 0.32 → σ_eff ≈ 14 m; storm: |ȧ| ≈ 182 m/d → σ_eff ≈ 52 m), and *the threshold comparison is consistent with a substantial drag-related contribution to the inter-TLE ambiguity under the evaluated conditions* — it does not by itself prove that all false alarms are drag-driven.

### 5.5 Why detector-level injection sensitivity does not fully match real-event sensitivity

Six factors separate the two: (1) post-processing injections are an upper bound; (2) the consistency screening of verified events rejects some genuine maneuvers, notably coordinated burns removed by the common-mode check; (3) TLE-side association and merging rules differ from the per-sample hit criterion; (4) SP3-side truth definition imposes its own losses; (5) multiple burns can pile up within one update interval; (6) TLE fitting and averaging smooth the signal. The ramp experiment (Section 4.5) excludes simple smearing (≤1 d) as the dominant cause; the remaining gap is attributed to a combination of (2), (3) and (5), with the orbit-state-level injection experiment identified as the direct test.

## 6. Generalization Evaluation

### 6.1 Temporal hold-out

Calibrating on windows before 2025-07-01 (8,778 trials; within-period ĉ = 0.28, then fixed) and testing after (6,996 trials): held-out log loss 0.124 (SNR_eff) versus 0.141 (amplitude-only); AUC 0.977 versus 0.967; Brier 0.039. The advantage of the drag-aware relation survives on data from a later epoch than any used in calibration. The test period contains no windows in the high-drag tercile, so the held-out comparison covers the low- and mid-drag regimes only.

### 6.2 Blocked cross-validation

With five folds formed from satellite × contiguous five-window time blocks — adjacent overlapping windows never straddle folds, and c is re-estimated within each training fold — out-of-fold log loss is 0.184 versus 0.205 and Brier 0.056 versus 0.063 (SNR_eff versus amplitude-only), essentially identical to a plain cluster CV (0.183 / 0.204), demonstrating that window-overlap dependence leakage does not drive the comparison.

### 6.3 Future work

Leave-one-satellite, leave-one-drag-regime, and leave-one-campaign hold-outs; a complete domain-transfer protocol for the Starlink-trained detector family; extension of the calibrated relation to the ILRS altimetry benchmark and other constellations; orbit-state-level and observation-level injections; quantitative space-weather attribution; and a residual decomposition for the dense-cadence and large-amplitude prediction residuals.

## 7. Discussion and Limitations

**Operational implications.** The reliable detection threshold of TLE-based maneuver detection is not a constant but a function of (σ_TLE, Δt, ȧ_drag). The inference "no maneuver was seen in TLEs, therefore none occurred" is defensible only when the hypothesized maneuver's SNR_eff lies well above the calibrated detection scale, for a detector of the same family under comparable data conditions. Under the evaluated FS7 data, cadence, and detector configuration, the approximately 18-m station-keeping signature was below every evaluated operating threshold and was not reliably resolved. *The same mechanism may affect other low-altitude objects, but its magnitude depends on altitude, ballistic coefficient, tracking coverage, cadence, and detector design*; the extrapolation has not been validated beyond FS7. Conversely, kilometre-scale raises are captured with ≈82% recall, so public TLEs remain a meaningful screen for orbit-relocation-class activity. As supplementary context (Fig. S3), a domain map of the study satellites in altitude–inclination space with fitted noise-floor contours σ_th(h) = sqrt(σ₀² + (A·e^{−(h−400)/H})²) (σ₀ = 0.045 m, A = 24.5 m, H = 77 km, log-space R² = 0.89; derived in the companion study [11]) illustrates the altitude dominance of the nominal residual scale; it is contextual, not part of the calibrated model's claims, and the GRACE pair's departure from the contours (consistent with their low area-to-mass ratio) marks a limit of the single-parameter description.

**Limitations.** (i) Injections are post-processing-level; all injection results are upper bounds under TLE-equivalent perturbations, and end-to-end sensitivity is unvalidated. (ii) The decimation ablation carries confounds (sample count, CUSUM accumulation, σ background). (iii) The coefficient pair (c, SNR₅₀) is jointly calibrated and parameterization-dependent; neither is separately interpretable, and the c = 1 variant is retained only as a sensitivity reference. (iv) Dense-cadence 90% floors are under-predicted by ≈2×, coinciding with cadence-dependent residual autocorrelation; an AR(1)/colored-residual extension is future work. (v) Recall estimates apply to the 96 TLE-comparable events; the non-random exclusion of 35 events (by-campaign exclusion rates 0.00–0.54) is a potential selection bias. (vi) The /√2 in the σ_TLE estimator assumes independent errors; the assumption is checked but not guaranteed. (vii) c has not been recalibrated on any other constellation. (viii) The SP3-side checks share one truth source and are consistency criteria, not independent evidence; in practice the persistence and common-mode checks carry the rejection, the arc-agreement check rejected no candidate, and the common-mode check removes coordinated burns, so the 131-event library under-represents maneuvers performed by three or more satellites within ±3 h. (ix) The probability outputs are raw model probabilities with a held-out calibration slope of 1.22; recalibrated variants are reported separately.

## 8. Conclusion

Under the evaluated FS7 data, TLE update patterns, and MAD/CUSUM detector, a jointly calibrated empirical detectability relation based on effective residual and drag-related inter-TLE ambiguity improves the alignment of detector-level sensitivity curves across cadence and drag regimes. The relation retains predictive value on temporally held-out injections and held-out real events within FS7, but its coefficients are parameterization-dependent and should not be interpreted as universal physical constants or as complete end-to-end TLE maneuver-detection limits.


## Declaration of competing interest

The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper. [To be confirmed by all authors.]

## Funding

[To be completed: funding source and grant number, or "This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors."]

## CRediT authorship contribution statement

[Author 1]: Conceptualization, Methodology, Software, Formal analysis, Writing – original draft. [Author 2]: [roles]. [Author 3]: [roles]. [To be completed.]

## Declaration of generative AI and AI-assisted technologies in the writing process

During the preparation of this work the authors used [tool name] to assist with code development, consistency checking of reported numbers, and language editing. After using this tool, the authors reviewed and edited the content as needed and take full responsibility for the content of the published article. [To be confirmed or revised by the authors.]

## Acknowledgements

The authors thank the Taiwan Analysis Center for COSMIC (TACC) for public distribution of the FORMOSAT-7/COSMIC-2 leoOrb precise orbit products, and the 18th Space Defense Squadron for TLE data distributed through Space-Track.org.

---


## Figure captions

![](fig_fs7_method_flow.png)

**Fig. 1.** Data and method flow: SP3 precise-orbit truth, TLE series and space-weather indices; SP3-side detection with the consistency screening (persistence, arc agreement, common mode; inclination as corroboration); TLE-side detectors; event lineage 131 → 96 → five amplitude bins, with the 21 storm candidates as a separate false-positive case study; injection grid and model evaluation.

![](fig_fs7_injection_case.png)

**Fig. 2.** A single injection case (FORMOSAT7-4, NORAD 44350; window 2024-03-04 to 2024-03-23; 1× cadence, mid-drag tercile; Δa = 100 m injected at the window midpoint; σ_TLE = 2.8 m, |ȧ| = 48.7 m/day, Δt = 0.40 d): raw and injected semi-major-axis series, detrended single-step differences with the MAD threshold, CUSUM statistic, and the ±2-sample hit tolerance. The MAD detector flags the step; the CUSUM statistic stays below its threshold. The MAD scale of the detector's step differences (21 m; threshold ±63 m) is larger than σ_TLE (2.8 m) because σ_TLE is computed after removing the drag trend in time, whereas the detector differences successive TLEs directly; the drag change between updates, |ȧ|·Δt ≈ 19.5 m here, is of the same order and is the inter-TLE ambiguity represented by the drag term of SNR_eff.

![](figures_pub/fig_fs7_injection_recall/fig_fs7_injection_recall_en_light.png)

**Fig. 3.** Injection recall versus Δa by cadence and drag regime, with cluster-bootstrap 95% CIs; the observed empirical 90% recall floors range from 50 to 500 m (Section 4.1).

![](figures_pub/fig_fs7_injection_collapse/fig_fs7_injection_collapse_en_light.png)

**Fig. 4.** Collapse test: detection-rate curves separate when plotted against Δa/σ_TLE and align when plotted against SNR_eff (Section 4.3).

![](figures_pub/fig_fs7_injection_metrics/fig_fs7_injection_metrics_en_light.png)

**Fig. 5.** False-alarm rate and recall operating points by cadence and drag condition (Section 4.5).

![](fig_fs7_real_event_recall.png)

**Fig. 6.** Real-event comparison versus amplitude: observed recall at the 45 m and unified 3σ thresholds (Wilson 95% CIs), mean model-implied probability, the injection-based prediction, and the amplitudes of the 21 storm-interval drag-driven candidates (Sections 5.1 and 5.3).

Supplementary figures (in the Supplementary Material):

- **Fig. S1.** Profile likelihood of c with the reference values ĉ = 0.32, c = 0.28 and c = 1, and the joint (c, SNR₅₀) likelihood surface with β profiled; the ridge visualizes the −0.98 parameter correlation (Section 3.3).
- **Fig. S2.** Reliability diagrams on the temporal hold-out, raw versus Platt-recalibrated (Section 4.6).
- **Fig. S3.** Altitude–inclination domain map of the study satellites (56 with a valid noise estimate) colored by nominal TLE noise floor, with fitted contours σ_th(h); contextual only (Section 7).
- **Fig. S4.** Amplitude, campaign and satellite distributions of included (96) versus excluded (35) events (Section 2.6).

## Appendix A — Derivations and worked example

**SNR₉₀.** From P = [1 + exp(−β(log₁₀SNR − log₁₀SNR₅₀))]⁻¹, setting P = 0.9 gives log₁₀SNR₉₀ = log₁₀SNR₅₀ + ln 9 / (β ln 10), i.e. SNR₉₀ = SNR₅₀·10^{ln9/β}; β is estimated on the log₁₀ axis.

**Worked example (4×·high condition; full-data descriptive-refit coefficients).** σ_TLE = 20.8 m; |ȧ| = 76.2 m/day; Δt = 1.98 d; c = 0.32. Drag term: 0.32 × 76.2 × 1.98 = 48.3 m. σ_eff = sqrt(20.8² + 48.3²) = 52.6 m. Model-implied Δa₉₀ = 9.87 × 52.6 m = 519 m (the 515 m in the table in Section 4.4 uses the unrounded condition medians), versus the observed empirical 90% recall floor of 500 m (smallest grid amplitude); the three numbers are different quantities and agree to within grid resolution.

## Data and code availability

leoOrb SP3 products are publicly distributed by TACC (file versions, download dates, and checksums recorded in the release). TLE histories were obtained from Space-Track; per the Space-Track user agreement, raw TLE data are not redistributed — the release instead includes the NORAD identifiers and epoch lists (metadata, which the agreement permits) and retrieval scripts that reconstruct the data set under the user's own Space-Track credentials. The code release includes all analysis scripts (injection sweeps, joint calibration, blocked cross-validation, event building, unified recall comparison), the derived event tables (including per-event predicted probabilities; no reconstructable raw TLE content), and a README specifying (1) the environment (Python and key package versions), (2) data-retrieval instructions, (3) the exact command reproducing each table and figure, (4) expected output checksums, and (5) the fixed random seeds and configuration files.

## References

1. F. R. Hoots, R. L. Roehrich, *Models for Propagation of NORAD Element Sets*, Spacetrack Report No. 3, 1980.
2. D. A. Vallado, P. Crawford, R. Hujsak, T. S. Kelso, "Revisiting Spacetrack Report #3," AIAA/AAS Astrodynamics Specialist Conference, Keystone, CO, 2006, AIAA 2006-6753.
3. T. Flohrer, H. Krag, H. Klinkrad, "Assessment and categorization of TLE orbit errors for the US SSN catalogue," Advanced Maui Optical and Space Surveillance Technologies (AMOS) Conference, 2008.
4. J. Geul, E. Mooij, R. Noomen, "TLE uncertainty estimation using robust weighted differencing," *Advances in Space Research*, 59(10), 2577–2593, 2017.
5. T. Kelecy, M. Jah, "Detection and orbit determination of a satellite executing low thrust maneuvers," *Acta Astronautica*, 66(5–6), 798–809, 2010.
6. R. P. Patera, "Space event detection method," *Journal of Spacecraft and Rockets*, 45(3), 554–559, 2008.
7. S. Lemmens, H. Krag, "Two-line-elements-based maneuver detection methods for satellites in low Earth orbit," *Journal of Guidance, Control, and Dynamics*, 37(3), 860–868, 2014.
8. W. S. Schreiner et al., "COSMIC-2 radio occultation constellation: First results," *Geophysical Research Letters*, 47, e2019GL086841, 2020.
9. Taiwan Analysis Center for COSMIC (TACC), *FORMOSAT-7/COSMIC-2 near-real-time data products (leoOrb precise orbit files)*, https://tacc.cwa.gov.tw, accessed August 2026.
10. S. Hilla, *The Extended Standard Product 3 Orbit Format (SP3-c)*, National Geodetic Survey / International GNSS Service, 2010.
11. [Authors], "Empirical characterization of TLE-derived semi-major-axis noise from DORIS-certified quiescent arcs and its application to FORMOSAT maneuver analysis," manuscript in preparation, 2026.
12. W. E. Parker, R. Linares, "Satellite drag analysis during the May 2024 Gannon geomagnetic storm," *Journal of Spacecraft and Rockets*, 61(5), 2024. doi:10.2514/1.A36164.
13. J. M. Picone, A. E. Hedin, D. P. Drob, A. C. Aikin, "NRLMSISE-00 empirical model of the atmosphere: Statistical comparisons and scientific issues," *Journal of Geophysical Research: Space Physics*, 107(A12), 2002.
