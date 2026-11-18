# Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits

**Authors:** [Author 1]ᵃ*, [Author 2]ᵃ, [Author 3]ᵇ

ᵃ [Affiliation, address, country]
ᵇ [Affiliation, address, country]

\* Corresponding author. E-mail: [address]

## Highlights

- Public TLE maneuver detection is calibrated against FORMOSAT-7 precise orbits.
- Detector-level 90% recall under TLE-equivalent injections: ~40 m to ~480 m.
- A drag-aware effective SNR improves held-out log loss from 0.141 to 0.124.
- Most isolated sub-300 m real events show no TLE response within three days.
- Storm-consistent, drag-attributed signatures can mimic persistent maneuver steps.

---

## Abstract

Public Two-Line Elements (TLEs) are widely used for maneuver screening. We ask how large a TLE-equivalent perturbation a specified detector reveals, and under which residual, cadence and drag conditions. FORMOSAT-7/COSMIC-2 precise orbits yield 131 SP3-consistency-verified maneuver events, all individually verified (coordinated burns are excluded by design); 96 have adequate TLE coverage. Step injections into real TLE series give a detector-level 90% recall amplitude of about 40–480 m across cadence and drag regimes. These are upper bounds for the detector, not end-to-end limits of the TLE product. Adding a drag-related inter-TLE ambiguity term to the residual scale improves held-out prediction over an amplitude-only model (log loss 0.124 versus 0.141). At the densest cadence, however, the model under-predicts the 90% amplitude. Real-event recall at a pre-specified 45 m threshold rises from 0.11 (1–50 m) to 0.82 (1–3 km). Most isolated real events below 300 m show no TLE response within three days, consistent with a limitation upstream of the detector. A May 2024 storm interval yields 21 storm-consistent candidates, drag-attributed under the available evidence, which form a distinct false-alarm mode under the evaluated screening rules.

**Keywords:** maneuver detection; two-line elements; precise orbit determination; FORMOSAT-7; detectability; space situational awareness

---

## 1. Introduction

Space situational awareness (SSA) for non-cooperative targets relies almost entirely on the public Two-Line Element (TLE) catalog. TLEs are free, global, and frequently updated, but they are fitted products rather than measurements: their accuracy depends on radar tracking density, SGP4 model error, and update cadence [1, 2], and they carry no covariance [3, 4]. A large literature detects maneuvers from TLE time series [5–7], but a basic question has lacked a direct answer: *how small a maneuver can public TLEs actually reveal, and under what conditions?*

Most published evaluations report detected-event counts or comparisons against operator announcement lists. The former cannot separate true signals from processing artifacts; the latter is limited by the incompleteness and coarse time-tagging of public announcements. Answering the question head-on requires an independent, more accurate orbit truth for the same satellites over the same period. Moreover, quoting sensitivity as a single number conflates three physically distinct contributions — the TLE residual scale, the update interval, and the drag environment — which vary by orders of magnitude across the LEO population.

This paper uses a public data set with rare properties: the FORMOSAT-7/COSMIC-2 (FS7) [8] precise orbit determination product (leoOrb), published by the Taiwan Analysis Center for COSMIC (TACC) [9] in SP3 format at 60 s cadence and covering more than 2,500 days since 2019. FS7 is a six-satellite constellation at approximately 550 km altitude and 24° inclination with chemical propulsion, whose orbit-raising campaigns provide abundant, independently verifiable maneuvers over a wide amplitude range.

The contributions are threefold:

1. We establish an event-level baseline for TLE-based maneuver detection using precise-orbit truth for FS7 targets. The baseline covers individually verified, non-coordinated maneuvers, because coordinated multi-satellite burns are removed by the event-definition rules (Section 2.7). It also characterizes drag-attributed non-thrust signatures during disturbed space-weather conditions.
2. We quantify detector-level sensitivity under controlled TLE-equivalent injections across cadence, residual scale, and drag regimes, and treat the results explicitly as an upper bound on end-to-end performance.
3. We develop and evaluate an empirical detectability relation based on an effective signal-to-noise ratio (SNR_eff), and assess its predictive performance using temporally held-out data and blocked cross-validation.
4. We decompose the gap between detector-level and real-event sensitivity into coverage, threshold, sign, and TLE-response components.

The analysis is intentionally limited to detector-level sensitivity under TLE-equivalent perturbations for the FS7 configuration. We claim no universal physical law, no invariance across detector families, and no complete prediction of end-to-end sensitivity. Throughout, "sensitivity" refers to one of four distinct quantities, kept separate in the text: the empirical injection-recall amplitude (Section 4.1), the model-implied amplitude at a given detection probability (Section 4.4), real-event recall conditional on TLE coverage (Section 5.3), and end-to-end sensitivity from maneuver to published TLE, which this paper does not measure. Cross-constellation transfer of the calibrated relation is reserved for future work.

## 2. Data and Truth Definition

### 2.1 Truth source: TACC leoOrb precise orbits

The leoOrb product distributes SP3-c files at 60 s sampling for the six FS7 satellites (SP3 codes L76–L81, NORAD 44349, 44351, 44343, 44350, 44358, 44353). Each file is a short arc of 126–129 epochs (≈2.1 h); each satellite has 42–59 arcs per day with four- to six-fold overlap between independent solutions. Overlap residuals give a direct estimate of truth quality; based on the inter-solution spread of semi-major axis we adopt **26 m (4σ)** as the smallest *validated SP3-derived event amplitude* — a property of the current pipeline and decision rules, not a physical detection limit.

Two implementation pitfalls fail silently and are documented for reproducibility. (i) Per the SP3-c standard [10], as adopted by the leoOrb distribution [9], positions and velocities are given in an Earth-fixed (ITRF) frame with velocity records in dm/s; computing orbital energy then requires the unit conversion and restoration of the inertial term v_ECI = v_ECEF + ω_E × r (ω_E = 7.292115×10⁻⁵ rad/s). The interpretation is verified numerically: with the correction, |v_ECI| ≈ sqrt(μ/r) holds to the expected precision, while omitting it biases semi-major axis by tens of kilometres without any error being raised. (ii) The 2024 and 2026 releases use different arc-alignment conventions; without resampling to a uniform grid, a "one orbital period" rolling window maps to the wrong number of samples.

### 2.2 TLE data and unit conventions

TLE histories for the six satellites cover January 2024 to August 2026 (≈1,900 records each). The median update interval is 8–12 h over the full history and **21.6 h during the 2025 orbit-raising campaign**; whenever an interval enters a formula we state which period it refers to. All core computations are carried out in SI units; figures and tables report Δa in metres, ȧ in m/day, and Δt in days, with conversions stated where they appear.

### 2.3 A quiescent free-decay reference

FS7-3 (NORAD 44343) performed its final orbit-raising in May 2025 and shows no orbit maintenance in the available campaign records since then. Through the end of the data set (August 2026, ≈15 months, no gaps relevant to the analysis) it decays monotonically. It therefore serves as a same-constellation, same-processing *no-maneuver reference under the available campaign records*. It is not a certified negative control, because the absence of maneuvers cannot be proven independently.

### 2.4 Space-weather context

Geomagnetic activity is characterized by the definitive 3-hourly Kp index and the daily observed F10.7 flux distributed by GFZ Potsdam [14]. These indices identify geomagnetically disturbed intervals, in particular the May 2024 storm interval analyzed in Section 5.1. Quantitative attribution of residual structure to individual indices is future work; no claim of completed space-weather attribution is made.

### 2.5 Campaign data status

Five orbit-raising campaigns are covered (Table 1). SP3 data have been acquired for all five; SP3-side event building is complete for all five (verified events: 29, 41, 8, 46, 7 respectively). The final campaign (January 2026) is reserved as a test segment that took no part in any calibration.

**Table 1 — Campaign data status.**

| Campaign | SP3 | TLE | Used for injections | Verified events | Role |
|---|---|---|---|--:|---|
| 2024 storm interval (20 d) | yes | yes | no (disturbed) | 87 → 21, drag-attributed (excluded from the 131) | false-positive case study |
| 2024-07 | yes | yes | quiet segments | 158 → 29 | test |
| 2024-11/12 | yes | yes | quiet segments | 247 → 41 | calibration |
| 2025-05 | yes | yes | quiet segments | 125 → 8 | calibration |
| 2025-07/08 (62 d) | yes | yes | excluded (campaign) | 332 → 46 | main truth set |
| 2026-01 | yes | yes | quiet segments | 94 → 7 | **held-out test** |

### 2.6 Event data lineage

The event populations are summarized in Table 2 and Fig. 1: the 131 verified events (46 from the 2025-07/08 campaign and 85 from the four other campaigns, disjoint) reduce to 96 evaluable events with sufficient TLE coverage before and after the event window, grouped into five amplitude bins (n = 37 / 16 / 18 / 8 / 17); 35 are excluded for insufficient TLE coverage.

**Table 2 — Data and event lineage.**

| population | count | role |
|---|--:|---|
| SP3-consistency-verified maneuver events | 131 | complete event library (46 + 85, disjoint; individually verified, non-coordinated; storm case study excluded) |
| events from four further campaigns | 85 | 29 + 41 + 8 + 7 (2024-07, 2024-11/12, 2025-05, 2026-01) |
| evaluable events (TLE coverage rule) | 96 | recall evaluation (Sections 2.6, 5.3) |
| excluded events | 35 | insufficient TLE coverage; limitations analysis |
| storm candidates | 21 | separate false-positive case study (drag-attributed; not in the 131) |

The 21 storm-interval candidates of Section 5.1 (from 87 raw candidates in the
2024 storm sample) are drag-attributed non-thrust candidates, **not counted as
maneuvers and not part of the 131**; they enter this paper only as the
false-positive case study.

**Coverage rule and evaluable population.** An event is *evaluable* under a coverage rule fixed before the recall analysis: at least three TLEs in the pre-event window [t_start − 3 d, t_start − 2 h] and at least one TLE in the post-event window [t_end + 2 h, t_end + 3 d]. The rule is a property of TLE availability around the event and does not use the event amplitude. Of the 35 excluded events, 34 fail the pre-event condition (26 have two pre-event TLEs, seven have one, one has none) and one fails the post-event condition; none fails both. For excluded events, the median time from the last TLE to t_start is 17.0 h (IQR 11.2–37.8 h), compared with 7.3 h for included events, whereas the median time from t_end to the next TLE is similar (10.4 h versus 10.6 h). Exclusion is therefore driven by sparse TLE updates *before* the event.

**Selection-bias analysis.** Exclusion is not random. It is strongly associated with campaign (exclusion rate 0.00–0.54; χ² p < 0.001) and satellite (0.03–0.50; p = 0.001), but not detectably with amplitude (Mann–Whitney p = 0.84; χ² over bins p = 0.72) (Section S2, Fig. S4). Because the inclusion probability depends on campaign, Table 2b reports, alongside the recall over the 96 evaluable events, three alternative quantities. The first is an inverse-probability-weighted (IPW) recall with weights 1/P(included | campaign). The second and third are deterministic worst-case and best-case bounds for the full 131-event library, obtained by counting every excluded event as a miss or as a detection, respectively. A satellite × campaign IPW is not identifiable, because four cells contain no included event.

**Table 2b — Real-event recall at the 45 m threshold under alternative treatments of the 35 excluded events** (sign-constrained rule of Section 5.4; the unified-3σ column is given in Table S28).

| amplitude bin | verified | evaluable | recall, evaluable | IPW (campaign) | worst case (131) | best case (131) |
|---|--:|--:|--:|--:|--:|--:|
| 1–50 m | 52 | 37 | 0.11 | 0.11 | 0.08 | 0.37 |
| 50–100 m | 21 | 16 | 0.31 | 0.31 | 0.24 | 0.48 |
| 100–300 m | 22 | 18 | 0.50 | 0.47 | 0.41 | 0.59 |
| 300 m–1 km | 10 | 8 | 0.62 | 0.70 | 0.50 | 0.70 |
| 1–3 km | 26 | 17 | 0.82 | 0.86 | 0.54 | 0.88 |
| all | 131 | 96 | 0.39 | 0.37 | 0.28 | 0.55 |

*Notes to Table 2b.* The worst case assumes that every excluded event would have been missed, and the best case that every excluded event would have been detected. They are logical bounds under these missing-data scenarios, not statistical confidence intervals. IPW is identifiable only at the campaign level. It cannot correct a missingness mechanism that operates at the satellite or satellite × campaign level, because four satellite × campaign cells contain no evaluable event.

The campaign-weighted estimates differ from the evaluable-population recall by at most 0.08 in every bin, so the observed campaign dependence of exclusion does not materially shift the recall estimates. The deterministic bounds are wide, however, and recall for the full library is not identified without assumptions about the missing TLE responses. All recall values in Section 5 therefore refer to the evaluable population and are *conditional on adequate TLE coverage*.

### 2.7 Event definition

An SP3-side candidate is a contiguous super-threshold segment of the smoothed-and-differenced semi-major-axis series (Section 3.1). Event time is defined by the segment start, peak, and end epochs. Candidates are screened by **consistency checks**. A candidate becomes an *SP3-consistency-verified maneuver event* (abbreviated "verified event" below) when it passes (a) persistence of the mean-level step, (b) agreement among overlapping independent arcs, and (c) a common-mode check that rejects signatures appearing on three or more satellites within ±3 h. (d) The inclination channel is recorded as corroboration for out-of-plane burns and does not enter the verdict. "Verified" therefore means consistent with the SP3-derived orbital behavior. It does not mean confirmed by operator records or thruster telemetry, which are not available for this study. The checks share the same SP3 source and are consistency criteria, not independent pieces of evidence. Over all 1,043 candidates, persistence rejects 52% and the common-mode check 39%. The arc-agreement check rejects none, because 41% of candidates are covered by a single arc and the overlapping arcs of the remainder agree to within 50 m. Definitions, rejection counts and failure modes are given in Tables S6–S7.

**Inclination corroboration.** Taking 4× the robust (MAD-based) scale of the inclination change across all candidates (4σ = 0.0059°) as the corroboration level, 2 of the 131 verified events show an inclination signature. Among the rejected candidates, 6 show one: three rejected by persistence, two by the common-mode check, and one by both. Because the inclination channel does not enter the verdict, no event classification would change if it were included as corroboration. The two common-mode cases are discussed under the next heading.

**Coordinated maneuvers are excluded by design.** The common-mode check is intended to reject artifacts that appear simultaneously on several satellites, such as processing discontinuities or reference-frame jumps. It cannot distinguish them from physically real, coordinated burns. During orbit-raising campaigns, 192 candidates with steps ≥ 1 km are rejected solely by this check, and they are not among the verified events. No operator records or telemetry are available to validate these candidates as a separate coordinated-maneuver class. The 131-event library, and every recall and detectability estimate derived from it, therefore refers to **individually verified, non-coordinated events only**. The exclusion has a second, indirect consequence. Rejected coordinated burns still change the orbit, so they can contaminate the pre-event trend window of neighbouring verified events; Section 5.5 quantifies this effect.

**Event accounting.** Verified SP3 events are not merged. In 40 of 125 consecutive same-satellite pairs, the two events are separated by less than 1 h; they are evaluated as separate events and share a TLE-side decision when they fall within one update interval (Table S8). Four terms are used for injections. An *event-level hit* is an injection with at least one detector flag within the hit tolerance, and any number of such flags counts as one hit; recall is computed from event-level hits. A *flag-level hit* is an individual flag within the tolerance and is used for flag-level precision. *Fragmentation* occurs when an injection receives more than one attributable flag. A *duplicate detection* is any attributable flag after the first. The hit tolerance of ±2 samples corresponds to different absolute times at different cadences (±0.7–1.0 d at 1×, up to ±4 d at 4×), so a fixed ±1.0 d tolerance is evaluated alongside as a robustness check (Section 4.5).

## 3. Detector and Sensitivity Model

**Table N — Notation.**

| symbol | definition | unit in tables |
|---|---|---|
| a | semi-major axis (SP3: osculating, converted from ITRF states; TLE: SGP4 mean-motion derived) | km |
| Δa_maneuver | semi-major-axis step produced by a maneuver (truth-side or injected) | m |
| Δa_obs,k | observed inter-TLE difference a_{k+1} − a_k | m |
| ȧ, ȧ_drag | robust linear rate of a over the window (drag-dominated in quiet windows) | m/day |
| Δt | median TLE update interval of the window | day |
| σ_TLE | effective TLE residual scale: MAD-based robust scale of detrended single-step differences, /√2 (Appendix B) | m |
| σ_eff(c) | sqrt(σ_TLE² + (c·\|ȧ\|·Δt)²), effective inter-TLE ambiguity | m |
| c | empirical drag-ambiguity scale factor (jointly calibrated; not a physical constant) | — |
| c·\|ȧ\|·Δt | drag-related inter-TLE ambiguity term (the interpretable derived quantity) | m |
| SNR_eff(c) | \|Δa_maneuver\| / σ_eff(c) | — |
| SNR₅₀, SNR₉₀ | SNR_eff at which the logistic detection probability is 0.5, 0.9 | — |
| β | logistic slope with respect to log₁₀ SNR_eff | — |
| Δa₉₀ (model) | SNR₉₀ · σ_eff, model-implied 90% probability amplitude (Section 4.4) | m |
| Δa₉₀ (interp.) | amplitude at which interpolated injection recall equals 0.90 (Section 4.1) | m |
| grid floor | smallest tested grid amplitude with injection recall ≥ 0.90 (Section 4.1) | m |
| r₁ | lag-1 autocorrelation of detrended single-step differences in a window | — |

### 3.1 SP3-side detector

The instantaneous semi-major axis is not smooth: Earth oblateness (J2) drives a twice-per-revolution oscillation whose peak-to-peak amplitude for FS7 is **3,480 m** — 7.9 times larger than the largest routine signal of interest. Any detector differencing at the 60 s scale detects J2, not maneuvers. The **differencing gain** — the transfer-function magnitude of lag-L differencing alone, with L and P expressed in the same units (samples) — for the k-th harmonic of period P is

G_diff(k) = 2 |sin(π L k / P)|,

for the backward difference x_n − x_{n−L}, with both the lag L and the period P expressed in samples; it vanishes only when L is an integer multiple of P. The rolling-mean smoothing stage has its own (Dirichlet-kernel) response H_mean(k), which likewise nulls harmonics exactly when the window length is an integer multiple of P; the total response is H_total(k) = H_mean(k)·G_diff(k), and the integer-period rule below applies to each stage separately. Three implementation rules follow: (i) the smoothing window and the differencing lag must both be integer multiples of the orbital period, computed per series from the actual semi-major axis rather than hard-coded; (ii) under the integer-period condition the arithmetic mean cancels harmonics exactly while the median only approximately; (iii) non-integer lags alias residual harmonics into spurious but apparently significant structure. A decomposition on a Starlink series (actual period 96.06 min) quantifies the ranking: an unsmoothed series has 16.975 km peak-to-peak residual; a median filter with a hard-coded 97 min window leaves 1.040 km; a median with the integer 96 min window leaves 0.141 km; the integer-window mean leaves **0.063 km**. The detector therefore uses: uniform 60 s resampling → one integer-period rolling mean → one integer-period difference → threshold at 4× the robust σ (MAD-based). The FS7 orbital period at a ≈ 6,928 km is P ≈ 95.5 min (≈ 96 samples at 60 s); one integer-period smoothing window plus one integer-period differencing lag therefore requires a series of at least 2P ≈ 191 min. Because a single leoOrb arc (126 min) is shorter than this, arcs must be merged into continuous series before analysis (the per-satellite window lengths, computed from each series' actual median semi-major axis, are listed in the released configuration).

### 3.2 TLE-side detectors

Two TLE-side procedures are used, and they are deliberately kept distinct. **Detector D1** (MAD ∪ CUSUM) is used for all injection experiments and for the calibration of the sensitivity model. **Estimator E1** (pre-event trend and post-event residual) is used for the real-event comparison, because real events carry SP3-defined epochs that D1's window-level flags do not. The model of Section 3.3 is calibrated on D1 only. Its comparison with E1 outcomes in Section 5 is therefore descriptive and is not a validation of the probability model. Box 1 specifies both procedures, together with the association and hit rules.

**Box 1 — Detector and association specification** (code: `statistical_detectors.py`, `fs7_injection_sweep.py`, `fs7_tle_recall_unified.py`).

*Detector D1 (injections).*
1. Input: TLE semi-major-axis series of one window, 40 consecutive TLEs (decimated by 1×, 2× or 4×; at least 10 points after decimation), with no single step > 0.3 km and no gap > 5 d. Sampling is irregular: there is no resampling and no smoothing.
2. Increment series: d_k = a_k − a_{k−1} (lag 1, with d_0 = 0); the drag trend is not removed for D1.
3. Robust scale: m = median(d), s = 1.4826·median|d − m|, computed over the whole window; if s ≤ 10⁻¹² km, the standard deviation of d is used instead.
4. MAD rule: flag k if |d_k − m|/s > 3.
5. CUSUM on z_k = (d_k − m)/s, two-sided, initialized at S⁺ = S⁻ = 0: S⁺ ← max(0, S⁺ + z_k − κ) and S⁻ ← max(0, S⁻ − z_k − κ), with κ = 0.5. Flag k when S⁺ > h or S⁻ > h, with h = 5, and reset both to 0 after each alarm.
6. Flag set: the union of MAD and CUSUM flags.
7. Injection hit (event level): at least one flag within ±2 samples of the injected index (the robustness variant uses ±1.0 d). The injection index is drawn uniformly from the middle third of the window, and a step of Δa is added to all later samples.
8. Control false alarm: any flag in the same window without injection.

*Estimator E1 (real events and pseudo-events).*
1. Pre-event window [t_start − 3 d, t_start − 2 h]: at least 3 TLEs are required, and a least-squares linear trend is fitted to a(t).
2. Post-event window [t_end + 2 h, t_end + 3 d]: at least 1 TLE is required. The residual is the median of (a − trend) over the earliest one or two post-event TLEs, in metres.
3. Decision: |residual| > threshold, either 45 m or a per-satellite unified 3σ of 3.9–6.2 m. *Provenance of 45 m:* it was adopted in our earlier conference analysis as approximately three times a TLE semi-major-axis noise scale of about 15 m for FS7, so it is a noise-based rule. It was not chosen by optimizing any detection metric on events or pseudo-events. The data period and estimator behind the ≈ 15 m scale were not recorded, so we cannot show that its estimation data are disjoint from the present evaluation. That conference analysis also applied the 45 m threshold to the 46 events of the 2025-07/08 campaign, which are part of the present 131. We therefore report a check on the 85 events never used in that analysis, together with a full threshold sweep (Section 5.4). 45 m is a pre-specified threshold from prior analysis, not a recommended operating point. Section 5.4 reports two rules applied symmetrically to real events and pseudo-events: rule S requires the residual sign to match the SP3 step sign, or a hypothesized sign for pseudo-events, and rule U imposes no sign condition.
4. Association: each verified event is evaluated once at its own SP3 epochs; closely spaced events are not merged and can share a post-event TLE (Table S8). Detection delay is measured from t_end to the first post-event TLE.

*Fixed in advance.* The injection amplitude grid (11 values, 20 m–2 km), the decimation factors, the window and stride lengths, the D1 parameters (3σ, κ = 0.5, h = 5) and the 45 m threshold were all fixed before any injection or real-event result was examined; none was tuned on the data reported here.

### 3.3 The sensitivity model

The proposed relation is

SNR_eff(c) = |Δa_maneuver| / sqrt( σ_TLE² + ( c · |ȧ_drag| · Δt )² ),

P(detect) = 1 / ( 1 + exp[ −β ( log₁₀ SNR_eff − log₁₀ SNR₅₀ ) ] ),

with SNR₉₀ = SNR₅₀ · 10^(ln 9 / β); β is defined on the log₁₀ axis and the derivation is given in Appendix A.

**What the coefficients mean, and what they do not.** c, SNR₅₀ and β are *jointly calibrated* within this parameterization and are not separately identifiable: across cluster-bootstrap replicates, corr(log c, log SNR₅₀) = −0.98, so a larger c is compensated almost exactly by a smaller SNR₅₀. c is therefore neither a physical drag fraction, nor an atmospheric-density response coefficient, nor a universal property of TLE errors. The model's value lies in its *predictive structure*, namely that adding a drag-dependent ambiguity term improves held-out prediction (Section 6), and in jointly determined quantities such as SNR₉₀ and Δa₉₀. It does not lie in the individual numbers. For interpretation we therefore report the derived drag-ambiguity term c·|ȧ|·Δt, in metres. This term is an *empirical effective ambiguity* for the given data and detector. It does not separate the contributions of tracking error, SGP4 fitting, atmospheric-density model error, solar-activity lags, or the TLE update strategy, and the label "drag-related" is not a completed causal attribution. The form |ȧ|·Δt was specified in advance as the drag-induced change in a between consecutive updates. Alternative proxies are compared in Section 4.3. With c = 0.32, its median ranges from 2.0 m (1×, low drag) to 48 m (4×, high drag) across the nine injection conditions. It accounts for 76–90% of σ_eff² in every condition, compared with σ_TLE medians of 1.1–21 m (Table S29). Two alternative parameterizations were examined. Fitting c separately per cadence gives c = 0.32 [0.25, 0.50] at 2× and 0.28 [0.22, 0.35] at 4×, consistent with the pooled value; at 1× the drag term is not identified. With the grid extended to c = 100 and without the numerical floor on SNR (Section S17), the 1× likelihood rises monotonically toward the drag-only limit c → ∞, in which σ_TLE drops out. The 95% set is [0.56, ∞), and the limit exceeds the likelihood at c = 0.32 by 8.8 log-likelihood units. At the densest cadence, therefore, the data do not support a finite drag-ambiguity scale within this functional form. Using c′·Δt as a single free scale is algebraically identical to the present form at fixed Δt, so it does not remove the trade-off.

Variables are defined as follows. Δa_maneuver is the semi-major-axis step a maneuver is expected to produce (truth-side or injected); it is distinct from the observed inter-TLE difference Δa_obs,k = a_{k+1} − a_k that the detector actually sees. σ_TLE is an **effective TLE residual scale**: the MAD-based robust standard deviation of detrended single-step differences in quiet windows (MAD × 1.4826 / √2, a robust differencing estimator in the sense of [4]). Its complete definition, including detrending, quality-control rules and the autocorrelation diagnostic, is given in Appendix B, so that it can be evaluated without the companion study [11]. The /√2 assumes independent, identically distributed errors, and a lag-1 autocorrelation check accompanies it (Table S21). The quantity is deliberately not called the "TLE element standard deviation", because it mixes tracking error, SGP4 averaging, fit-span and processing effects. ȧ_drag is the robust linear drag rate of the window, and Δt the median update interval.

**Estimation details.** Each estimated quantity is defined by its data, method and use. Values of c are listed only for completeness and, as stated above, are not interpretable on their own:

| quantity | estimation data | method | use |
|---|---|---|---|
| ĉ = 0.32 | full data | maximum likelihood over a log-spaced grid (c > 0) | descriptive refit |
| CI [0.28, 0.40] for c | full data | profile likelihood: 2[ℓ(ĉ) − ℓₚ(c)] ≤ χ²₁,₀.₉₅ = 3.8416, i.e. ℓ(ĉ) − ℓₚ(c) ≤ 1.9208, where ℓₚ(c) profiles out SNR₅₀ and β | parameter uncertainty of the descriptive refit (not a bootstrap percentile CI; 0.28 is not this interval's bound by construction) |
| c = 0.28 | calibration split | maximum likelihood | fixed for all held-out evaluation |
| corr(log c, log SNR₅₀) = −0.98 | full data | Pearson correlation of (log ĉ, log SNR̂₅₀) across B = 200 cluster-bootstrap replicates (c > 0 by construction); a B = 500 convergence check gives an indistinguishable value (−0.979 versus −0.978; Table S10) — the smaller B is used only for this diagnostic because each replicate requires a full grid refit of c | joint-identification diagnostic |

The correlation of −0.98 is interpreted as strong coefficient covariation — a scale trade-off — not as robust separate identification; jointly determined *predictive* quantities remain stable despite it (e.g., SNR₉₀ carries a narrow CI because it is recomputed within each resample, and the Δa₉₀ predictions of Section 4.4 shift by at most 5% between parameterizations). *Within the specified detector-level logistic model and its profile-likelihood construction, the fixed value c = 1 lies outside the 95% confidence set*; because c is not a physical constant, this is a statement about the model fit, not a rejection of a physical drag fraction. Per-drag-regime estimates are consistent (low 0.28 [0.20, 0.40]; mid 0.32 [0.25, 0.50]; high 0.32 [0.25, 0.50]). Fig. S1 shows the profile likelihood of c and the joint (c, SNR₅₀) likelihood surface with β profiled and the 95% region marked. What *is* identifiable is the structural claim: a model containing the drag term outperforms the amplitude-only model on held-out data (Section 6). Physically, c is *an empirical scale factor for the detector-level drag-related ambiguity and should not be interpreted as a universal physical fraction of orbital decay*. In the logistic link, SNR₅₀ is the scale at which detection probability is 50% and β is the slope with respect to log₁₀SNR (natural-log optimizer outputs are converted accordingly); the logistic P does not model the small-amplitude background-coincidence plateau, which is treated separately (Section 4.5).

### 3.4 Injection design and its position in a validation ladder

Injections are performed at the **TLE post-processing level**: steps (and, in a sensitivity variant, ramps) are added to real TLE semi-major-axis series, preserving real cadence, real noise, and real drag. Fig. 2 shows one injection case. This validates the detector's response to TLE-equivalent perturbations but does not simulate the full chain maneuver → tracking observations → orbit determination/SGP4 fitting → published TLE. All injection results are therefore reported as a **detector-level upper bound under TLE-equivalent perturbations**. The validation ladder has three rungs — post-processing injection (this paper), orbit-state-level injection (modifying mean motion and re-propagating), and observation/OD-level injection (end-to-end) — with the latter two reserved for future work.

The grid, fixed before any result was examined and not refined afterwards: 11 step amplitudes from 20 m to 2 km × cadence decimation {1×, 2×, 4×} × drag terciles of |ȧ|, over 478 quiet windows (40 TLE points each, sliding stride 20, windows containing any single step > 0.3 km or gap > 5 d excluded), totalling 15,774 trials. Per-window (σ_TLE, ȧ, Δt) are measured, not assumed.

### 3.5 Statistical methods

Trials within a window share the same satellite, epoch background, and residual structure and are not independent; nothing is treated as a binomial sample of 15,774. Inference uses cluster bootstrap with the **satellite × window** cluster (478 clusters; 73–94 windows per satellite; median 33 trials per cluster), B = 2,000 resamples, percentile intervals, fixed seed, re-estimating (SNR₅₀, β) and recomputing SNR₉₀ *within* each resample; the CI for c is a profile-likelihood interval. Because adjacent windows overlap by 50%, two robustness checks are reported: a non-overlapping-window subset (241 windows: SNR₅₀ = 3.81, β = 5.43, consistent with the main fit) and a satellite-level bootstrap (six clusters, acknowledged as coarse: SNR₅₀ 95% CI [3.51, 4.07]). Cross-validation uses **blocked folds** — satellite × contiguous time blocks, so that adjacent overlapping windows never straddle folds — reported alongside a plain cluster CV to demonstrate the absence of dependence leakage. Calibration performance and generalization performance are kept distinct throughout. Model comparisons use identical data splits, event sets and operating points, and the differing degrees of freedom of the compared models are stated. **AUC** is used for two different evaluations, which are named differently and are not comparable. The *injection-trial AUC* evaluates the probability model. It is computed at the *trial* level on the temporal test split (6,996 trials). The positive class is an injection flagged within tolerance, ties are given averaged ranks (Mann–Whitney), and cluster-bootstrap CIs are taken over 212 satellite × window clusters. The *real-event/pseudo-event discrimination AUC* is used for the E1 threshold sweep (Section 5.4). Its positive class is the 96 evaluable real events and its negative class is the 1,145 pseudo-events; it is unpaired, and each sample is resampled separately. It is a supplementary diagnostic of E1 and is not quoted alongside the injection-trial AUC. **Error-rate terms** are used in three distinct senses. The *false-alarm rate* is the number of detector flags per satellite per 30 days in non-injected control windows (D1). The *false-positive rate* (FPR) is FP/(FP + TN) over pseudo-events (E1). The *false-discovery proportion* is 1 − precision, at flag or event level as stated.

## 4. Controlled Injection Results (Detector Level)

### 4.1 Recall surfaces

Two empirical quantities are distinguished. Both are operating-point quantities, not physical limits, and both differ from the *model-implied 90% probability amplitude* of Section 4.4. The **grid floor** is the smallest *tested* grid amplitude at which measured injection recall is at least 0.90. Because it depends on the grid spacing, it is reported only as a descriptive grid quantity. The **interpolated Δa₉₀** is the *estimated* amplitude at which recall equals 0.90. It is obtained by monotonizing the recall curve (pool-adjacent-violators) and interpolating linearly in log₁₀ Δa between the two bracketing grid amplitudes. Its 95% CI comes from a satellite × window cluster bootstrap (B = 2,000) that repeats the interpolation in every resample. Both degrade systematically with cadence and drag regime (Fig. 3; Table 4a). The recall at every grid amplitude, with cluster-bootstrap CIs, is tabulated in Table S30.

**Table 4a — Empirical 90% injection-recall amplitude by condition.**

| condition (median Δt) | grid floor | recall at floor | recall one grid step below | interpolated Δa₉₀ [95% CI] | resamples giving the same grid floor |
|---|--:|--:|--:|--:|--:|
| 1×·low (0.33 d) | 50 m | 0.99 | 0.58 | 41 m [39, 42] | 1.00 |
| 1×·mid (0.40 d) | 100 m | 0.96 | 0.50 | 91 m [87, 95] | 1.00 |
| 1×·high (0.53 d) | 200 m | 0.98 | 0.89 | 157 m [143, 173] | 0.74 |
| 2×·low (0.87 d) | 50 m | 0.94 | 0.38 | 47 m [45, 52] | 0.95 |
| 2×·mid (0.99 d) | 100 m | 0.91 | 0.44 | 98 m [93, 113] | 0.65 |
| 2×·high (0.99 d) | 300 m | 0.99 | 0.89 | 210 m [190, 239] | 0.65 |
| 4×·low (1.72 d) | 100 m | 0.91 | 0.56 | 99 m [91, 114] | 0.67 |
| 4×·mid (1.80 d) | 200 m | 0.90 | 0.71 | 200 m [187, 238] | 0.56 |
| 4×·high (1.98 d) | **500 m** | 0.92 | 0.67 | **476 m [440, 537]** | 0.87 |

The grid floor overstates the interpolated value by up to 1.4×. The overstatement is largest where the recall one step below the floor is already close to 0.9 (1×·high and 2×·high, 0.89). In five of nine conditions, the grid floor itself changes in at least 26% of bootstrap resamples, so the grid floors carry substantial resampling uncertainty that the grid presentation hides. The interpolated values span **41–476 m** across conditions. The measured window σ_TLE is only 1–21 m in every condition, so both quantities far exceed it, indicating that the residual scale alone is not the controlling factor.

### 4.2 Cadence ablation

Because the decimation experiment holds the data fixed and lengthens only the sampling interval, it is a controlled ablation: *under the controlled decimation experiment, reduced temporal sampling is associated with a marked degradation in detector sensitivity* (interpolated Δa₉₀ 41 m → 476 m; grid floor 50 m → 500 m). Decimation simultaneously changes the available sample count, the CUSUM accumulation behavior, and the σ-estimation background; these confounds are carried to the limitations rather than argued away.

### 4.3 Parameterization protocol and model comparison

**Inference protocol (single main flow).** (i) All model parameters — c, SNR₅₀, β — are estimated on the **calibration split** (windows before 2025-07-01): **c = 0.28, SNR₅₀ = 3.87, β = 5.04 (hence SNR₉₀ = 10.57)**. (ii) They are then **fixed, with no re-estimation**, for every held-out evaluation (temporal test split; real events). (iii) A **full-data refit** (ĉ = 0.32, profile-likelihood 95% CI [0.28, 0.40]; SNR₅₀ = 3.77 [3.58, 3.96]; β = 5.25 [4.96, 5.59]; SNR₉₀ = 9.87 [9.51, 10.20], computed within each of B = 2,000 cluster-bootstrap resamples) is reported **as a descriptive refit only** — it is the paper's best single summary of the relation but is never used to claim held-out performance. Wherever a number derives from the descriptive refit it is labeled as such.

**Table 3 — Temporal hold-out performance** (both models estimated entirely on the calibration split — drag-aware: c = 0.28, SNR₅₀ = 3.87, β = 5.04; amplitude-only: SNR₅₀ = 8.74, β = 4.38 — then fixed and evaluated on the same test split; the main-protocol drag-aware number is **0.1237**):

| Model | held-out log loss | held-out Brier | held-out AUC | calib. slope [95% CI] | calib. intercept [95% CI] |
|---|--:|--:|--:|--:|--:|
| drag-aware (SNR_eff) | 0.1237 | 0.0393 | 0.9773 | 1.22 [1.12, 1.35] | −0.63 [−0.89, −0.39] |
| amplitude-only (Δa/σ) | 0.1413 | 0.0446 | 0.9671 | 1.15 [1.06, 1.26] | −0.26 [−0.52, −0.02] |

All metrics, including Brier and the calibration slope and intercept with cluster-bootstrap CIs, are computed on the identical temporal test split for both models. The trial-level AUCs have cluster-bootstrap 95% CIs of [0.974, 0.981] (drag-aware) and [0.962, 0.972] (amplitude-only), and the paired AUC difference is 0.010 [0.007, 0.013].

Sensitivity variants — c fixed at 1 (drag term at the full decay rate: held-out log loss 0.1241) and c fixed at the full-data value 0.32 (0.1236) — are tabulated in Table S12; the latter uses full-data information to choose c and is therefore excluded from the main hold-out table by protocol, even though its result is numerically indistinguishable. All drag-aware variants make near-identical held-out predictions: the apparent movement of SNR₅₀ between parameterizations is a rescaling of the denominator, demonstrated explicitly by evaluating SNR_eff(c) and the corresponding predicted probabilities on common events (Tables S13–S14). The identifiable content is structural (Fig. 4): removing the drag term degrades held-out log loss from 0.124 to 0.141 (the amplitude-only model's per-sample log-likelihood deficit on the full data is 0.021 [0.017, 0.025]).

**Alternative drag proxies (post hoc).** We replaced c·|ȧ|·Δt with c·|ȧ|·Δt^p for p ∈ {0, 0.5, 2}, and also tested the drag-only limit, which drops σ_TLE. Each variant was fitted on the calibration split and evaluated on the test split (Table S43a, Section S17). Held-out log loss is 0.1238 for the pre-specified c·|ȧ|·Δt, 0.1159 for c·|ȧ|·√Δt, 0.1231 for c·|ȧ|, 0.1370 for c·|ȧ|·Δt², 0.1243 for the drag-only form, and 0.1413 for the amplitude-only model (AUC 0.977, 0.981, 0.976, 0.970, 0.977 and 0.967, respectively). Every drag-dependent variant beats the amplitude-only model, so the structural conclusion is unchanged. The √Δt form fits better on both splits (calibration mean log-likelihood −0.2250 versus −0.2317). It also removes the 1× under-prediction: across the nine conditions, the ratio of interpolated to model-implied Δa₉₀ narrows from 0.64–1.85 to 0.67–1.28. In exchange, it under-predicts 4×·high (372 m versus 476 m). Dropping σ_TLE altogether barely changes held-out performance. We retain the pre-specified linear form as the main model, by protocol. The √Δt result is reported as a post hoc finding: it is consistent with a diffusive, random-walk-like component of the inter-TLE ambiguity, but it requires confirmation on independent data.

The binned detection-rate curve is approximately monotone in SNR_eff (monotone within a 0.05 tolerance; isotonic-regression R² = 0.9999) over the tested amplitude range — a conditional statement for this data set, injection range, detector, and operating point.

### 4.4 Threshold back-calculation in common units

The **model-implied 90% probability amplitude** is Δa₉₀ = SNR₉₀ · sqrt(σ_TLE² + (c·|ȧ|·Δt)²), evaluated here with the full-data descriptive-refit coefficients (SNR₉₀ = 9.87, c = 0.32; the calibration-only variant, SNR₉₀ = 10.57 with c = 0.28, shifts each prediction by at most 4% relative to the values below; Table S15) at each condition's median (σ, |ȧ|, Δt) after SI conversion. These are condition-representative values, not per-trial averages. The empirical columns repeat Table 4a. Model-implied and empirical quantities are related but not identical, which is why 515 m (model-implied), 519 m (worked example), 476 m (interpolated) and 500 m (grid floor) legitimately differ:

| condition | σ_TLE | \|ȧ\| (m/d) | Δt (d) | c·\|ȧ\|·Δt | model-implied Δa₉₀ | interpolated Δa₉₀ [95% CI] | grid floor |
|---|--:|--:|--:|--:|--:|--:|--:|
| 1×·low | 1.1 m | 18.5 | 0.33 | 2.0 m | 22 m† | 41 m [39, 42] | 50 m |
| 1×·mid | 2.6 m | 46.9 | 0.40 | 6.0 m | 64 m | 91 m [87, 95] | 100 m |
| 1×·high | 5.5 m | 76.8 | 0.53 | 13.0 m | 138 m | 157 m [143, 173] | 200 m |
| 2×·low | 2.2 m | 18.5 | 0.87 | 5.1 m | 55 m | 47 m [45, 52] | 50 m |
| 2×·mid | 5.4 m | 46.4 | 0.99 | 14.7 m | 153 m | 98 m [93, 113] | 100 m |
| 2×·high | 10.7 m | 74.6 | 0.99 | 23.7 m | 254 m | 210 m [190, 239] | 300 m |
| 4×·low | 3.6 m | 18.5 | 1.72 | 10.2 m | 106 m | 99 m [91, 114] | 100 m |
| 4×·mid | 8.7 m | 46.4 | 1.80 | 26.7 m | 274 m | 200 m [187, 238] | 200 m |
| 4×·high | 20.8 m | 76.2 | 1.98 | 48.4 m | **515 m** | **476 m [440, 537]** | **500 m** |

† Extrapolated: below the 26 m smallest validated SP3-derived event amplitude, so not a validated detection capability.

Against the interpolated values, the model under-predicts every 1× condition, by factors of 1.1–1.9 (largest at low drag). It over-predicts all 2× conditions and 4×·mid by factors of 1.2–1.6 (2×·low 1.17, 2×·high 1.21, 4×·mid 1.37, 2×·mid 1.56). It agrees within 8% at 4×·low and 4×·high. The model-implied value of 22 m at 1×·low lies below the 26 m smallest validated SP3-derived event amplitude, that is, below the scale at which the truth pipeline itself has validated events. Predictions in that corner are extrapolations of the logistic fit and are not truth-validated.

**Is the dense-cadence residual explained by serial correlation?** The median lag-1 autocorrelation of detrended differences rises with decimation (0.24 → 0.46 → 0.49 for 1×/2×/4×), which earlier suggested a correlated drag-related component. A within-cadence test does not support this as the main explanation. Stratifying windows into r₁ terciles *within* each cadence leaves the 1× prediction residual (observed recall minus mean predicted probability) essentially unchanged: −0.040, −0.033 and −0.038 in the low, middle and high terciles (Table S31). Adding r₁ as a covariate improves held-out log loss only from 0.1238 to 0.1228. r₁ does matter at 4×, where the interpolated Δa₉₀ in the high-r₁ tercile (403 m [336, 467]) exceeds that in the low tercile (281 m [242, 341]). The more direct signature of the 1× residual is the per-cadence fit of c (Section 3.3): at 1× the likelihood keeps increasing toward the upper edge of the grid. This is consistent with the possibility that a single c scaled linearly with Δt understates the effective inter-TLE ambiguity at the densest cadence. The post hoc √Δt form (Section 4.3; Table S43a), which removes most of the 1× residual, points in the same direction. We report this as a structural limitation of the one-parameter drag term, not as a confirmed mechanism. **For dense TLE updates, the model-implied Δa₉₀ is optimistic. The empirical interpolated values of Table 4a, or their upper CI bounds where a conservative value is needed, should be used instead.** A worked numerical example with every value and unit is given in Appendix A.

### 4.5 Metrics suite

Operating points by condition are shown in Fig. 5. Recall under the ±2-sample tolerance and under a fixed ±1.0 d tolerance nearly coincide at 1× and 2×; at 4× the time-based tolerance is lower at small amplitudes because ±2 samples there spans ±4 d. Precision in the detectable range (Δa ≥ 200 m) is 0.56–0.92 across conditions. Here TP is an injection with at least one flag within tolerance, and FP is a flag in the same window *before* the injected index minus the tolerance. Flags after the injection that fall outside the tolerance are excluded, because they cannot be separated from post-step detector responses. This definition depends on the pre-injection window length and the background flag rate (the injection index lies in the middle third, so 13–25 TLEs precede it at 1×). The flag-level and event-level definitions, and the corresponding false-discovery proportions, are compared in Table S20. For operational use, the event-level false-alarm rate in control windows (Tables S16–S17) is the more transferable quantity. The false-alarm rate in matched control windows is 1.4 flags per satellite per 30 days pooled over all control windows (flag level; stratified by cadence, drag, and satellite, with an event-level rate, in Tables S16–S17). For Δa ≥ 50 m the injected step is flagged at the first post-event TLE — defined for injections as the first TLE epoch at or after the injected step epoch, and for real events as the first TLE epoch after the truth-interval end t_end — in the majority of trials; detection delay is measured from the same reference epoch, and delay distributions (median, IQR, first-TLE fraction) are reported per cadence in Tables S18–S19. Event fragmentation (more than one attributable flag per injection) occurs in 12–22% of trials, depending on cadence. The low-amplitude detection plateau is **not** pure background: its rate (0.35 pooled for Δa ≤ 50 m) exceeds the coincidence rate of matched pseudo-injections in non-injected control windows (0.16) by +0.19 (cluster-bootstrap 95% CI [0.16, 0.22]); the plateau is a mixture of genuine detections in ultra-quiet windows (σ_TLE of 1–3 m) and coincidental hits. **Sensitivity to D1 parameters.** We replayed all 15,774 injections with identical windows and injection indices; the baseline reproduces every published hit exactly. Changing the CUSUM parameters (h = 4 or 6; κ = 0.25 or 1.0) changes the interpolated Δa₉₀ by at most 6.7% in any condition, with Spearman rank correlation ≥ 0.98 against the baseline across conditions. The false-alarm rate moves in the expected direction (1.53–2.12 versus 1.75 flags per satellite per 30 days in this replay). Raising the MAD multiplier from 3 to 4 lowers the false-alarm rate to 1.07 and raises Δa₉₀ by up to 47%, while preserving the ordering of conditions (Spearman 0.97). The MAD rule therefore dominates D1's sensitivity, and the CUSUM settings are secondary (Section S17). A ramp-injection variant shows the 90% floor unchanged for ramp widths up to 1 d and inflated only 1.5× at 2 d, excluding simple fit-smearing as a dominant effect.

### 4.6 Probability quality on held-out data

Held-out log loss, Brier score, AUC and calibration slope/intercept for both models on the temporal test split are given in Table 3 (calibration before 2025-07-01, test after; c fixed at the calibration-period estimate).

Raw and recalibrated probabilities are reported separately: *the raw probabilities showed mild miscalibration — held-out calibration slope 1.22, cluster-bootstrap 95% CI [1.12, 1.35] (statistically distinguishable from unity), intercept −0.63 [−0.89, −0.39] — although Platt recalibration, fitted on calibration-period out-of-fold predictions and applied unchanged to the test period, produced little change in held-out loss* (0.1238 / 0.0393). Reliability diagrams for both are shown in Fig. S2, with confidence intervals for the slope and intercept of all variants in Table S22. Because discrimination and calibration are distinct, AUC is never quoted alone as evidence of probability quality.

## 5. Real-Event Results within FS7

The real events are FS7 events that took no part in injection calibration. This section is therefore a held-out real-event comparison *within FS7*, not an external validation on an independent constellation. > **Detector versus estimator.** The sensitivity model was calibrated on detector D1 (MAD ∪ CUSUM, injections). Real-event outcomes in this section come from a different procedure, estimator E1 (pre-event trend and post-event residual) (Box 1). **The D1-calibrated model therefore cannot validate E1 detection probabilities.** Model probabilities in Table 4 and Fig. 6 are D1-based descriptive quantities, not calibrated E1 probabilities.

As a sensitivity comparison, we fitted simple E1-based logistic models to the 96 evaluable events and evaluated them by leave-one-campaign-out (Section S17). A model on log₁₀ amplitude reaches log loss 0.58 and AUC 0.79; adding the pre-event-contamination indicator of Section 5.5 gives 0.52 and 0.87. The base-rate log loss is 0.67. The D1-based probabilities, applied without refitting, give log loss 2.06 and AUC 0.55 on the same events. This confirms that they should not be read as E1 detection probabilities. A properly calibrated E1 probability model would require more real events and is future work. Section 5.5 shows that the bin-level comparison is also confounded.

### 5.1 Storm-consistent, drag-attributed non-thrust candidates

In a 20-day 2024 sample (start epochs 2024-04-30 to 2024-05-18) containing the May 2024 geomagnetic storm [12], 87 candidates yielded 21 that passed the consistency screening (persistence, arc agreement, and common mode). We call these 21 *storm-consistent, drag-attributed non-thrust candidates*. The attribution is an inference from four lines of evidence, not a direct physical identification:

- **Sign:** all 21 are negative-going (−47 to −16 m), whereas thrust events in this constellation are predominantly orbit-raising.
- **Magnitude:** the six satellites' mean semi-major-axis rate moved from −49 m/day before the storm to −182 m/day in the storm main phase, which is sufficient to produce persistent tens-of-metre level shifts over an SP3 step window.
- **Timing:** 19 of the 21 follow the main-phase onset (first Kp ≥ 7 at 2024-05-10 15 UT; Kp peak 9.0 at 2024-05-11 00 UT [14]). Of these 19, 17 occur with Kp ≥ 5 within the preceding 24 h; the other two occur 4–5 days after onset, during recovery (Kp ≤ 3.3 in the preceding 24 h). The two pre-onset candidates (L76, 2024-05-02 18–20 UT) coincide with an earlier, minor storm (Kp 6.7 in the same 3-h slot). In total, 19 of the 21 candidates have Kp ≥ 5 within the preceding 24 h. Daily observed F10.7 was 194–223 sfu from 2024-05-10 to 2024-05-18. Per-candidate alignment is listed in Table S32.
- **Records:** no corresponding maneuver appears in the available campaign records.

No thruster telemetry or operator maneuver log is available, and no public FS7 maneuver record for this interval was available to this study, so the attribution holds *under the available evidence* only. Four alternatives cannot be excluded:

1. unannounced single-satellite maneuvers;
2. small corrections performed by several satellites in sequence during the storm, which could produce an apparently storm-related negative series without triggering the ±3 h common-mode rule;
3. changes in TLE or SP3 product processing during the disturbed interval;
4. correlated residual structure in the SP3-derived semi-major axis under rapidly changing drag.

The storm candidates therefore form a distinct false-alarm mode *under the evaluated screening rules*. They should not be equated with all drag-related false positives. Persistence and cross-arc agreement cannot distinguish "the satellite maneuvered" from "the atmosphere pulled it down": thermospheric density, and with it drag, rises sharply during geomagnetic storms [12, 13], and drag *does* produce persistent, arc-consistent steps. Under the calibrated relation the storm raises the drag-ambiguity term so that steps of this size lie below the model's detection scale, consistent with their attribution to drag rather than to detectable thrust events; any candidate must therefore be screened against space-weather indices. *This result demonstrates that persistence and cross-arc consistency alone cannot distinguish a thrust event from a drag-attributed decay signature under the evaluated conditions*; its identification is part of the event-level baseline (contribution 1).

### 5.2 Maneuver structure: a staircase, not a ramp

Decomposing the 2025 campaign trajectory of L77 (FORMOSAT7-2, NORAD 44351) at 6 h resolution shows the 25.67 km total raise to be a staircase of **eleven discrete burns of 1.2–2.8 km** (2.81, 1.45, 1.16, 2.56, 2.57, 2.81, 2.56, 2.68, 2.60, 2.51, 2.80 km). The campaign-average rate of ≈400 m/day is therefore an average over discrete burns, not a continuous low-thrust profile. TLE-side total raises for the five active satellites (24.6–25.8 km) agree with the SP3-side 25.67 km, an independent cross-check.

### 5.3 Recall by amplitude bin

**Table 4 — Real-event recall** (estimator E1, sign-constrained rule S). *Recall is computed over the 96 evaluable events, not over all 131 verified events, and is conditional on adequate TLE coverage; it is not an unbiased estimate for the full 131-event library.* IPW estimates and worst-case and best-case bounds are given in Table 2b. The table shows both thresholds, with Wilson 95% CIs. The probability column is the mean model-implied probability under the D1 calibration, using the full-data descriptive-refit coefficients (c = 0.32, SNR₅₀ = 3.77, β = 5.25), none of which were estimated on real events. It is not a calibrated E1 probability:

| amplitude bin | n | recall @ 45 m (pre-specified, prior analysis) | recall @ unified 3σ | 95% CI (unified) | D1-based descriptive probability (mean)* | note |
|---|--:|--:|--:|---|--:|---|
| 1–50 m | 37 | 0.11 | 0.19 | [0.09, 0.34] | 0.29 | mixed with background at small amplitudes |
| 50–100 m | 16 | 0.31 | 0.50 | [0.28, 0.72] | 0.59 | |
| 100–300 m | 18 | 0.50 | 0.61 | [0.39, 0.80] | 0.67 | |
| 300 m–1 km | 8 | 0.62 | 0.62 | [0.31, 0.86] | 0.68 | small sample; partially characterized |
| 1–3 km | 17 | 0.82 | 0.82 | [0.59, 0.94] | 0.65 | prediction residual −0.17 |

\* Mean of per-event model-implied probabilities (descriptive refit); a descriptive comparison column, not an independent recall estimate. Under the calibration-period coefficients (c = 0.28, SNR₅₀ = 3.87, β = 5.04) the bin means are 0.31, 0.61, 0.68, 0.71 and 0.67.

Recall rises monotonically with amplitude (Fig. 6), and the 1–3 km value agrees with an independent campaign-only analysis of the 2025 raise (0.82). The intermediate 300 m–1 km bin contains eight events and is only partially characterized. At bin level, predicted and observed recall agree within 0.11 in four of five bins (0.12 under the calibration-period coefficients). **Section 5.5 shows that this bin-level agreement should not be read as validation of the model.** It arises partly from two opposing biases that cancel within bins. Per-event predicted probabilities are provided in the released event table.

### 5.4 Threshold trade-off on real events and pseudo-events

**Samples.** TP/FN are computed on the 96 evaluable real events. FP/TN are computed on quiet-period **pseudo-events**: up to 200 random TLE epochs per satellite, drawn from the 2024–2026 history (epochs before 2026-08-25; seed 42), each at least 2 days from any verified event, and evaluated with estimator E1 using identical windows and thresholds (n = 1,145 evaluable). The two samples are separate, so the table below is not a single-population confusion matrix. FPR = FP/(FP + TN) is computed per evaluated pseudo-event and pooled across satellites.

**Symmetric decision rules.** In the original submission, real-event TPs required the post-event residual to match the sign of the SP3 step, whereas pseudo-event FPs were counted on |residual| alone. The two rules were therefore not matched. We now report two rules, each applied identically to both samples. *Rule S (sign-constrained)* counts a detection when |residual| exceeds the threshold *and* the residual has the sign of the hypothesized step: the SP3 step sign for real events, and for pseudo-events a sign drawn from the real-event sign mix (52.1% positive), applied in expectation. *Rule U (sign-free)* applies no sign condition to either sample. The 45 m threshold was carried over unchanged from the earlier conference analysis and was not selected using the data evaluated here.

**Table 5 — Threshold performance under symmetric rules** (Wilson 95% CIs; "sample precision" uses the sample ratio of 96 events to 1,145 pseudo-events and is prevalence-dependent, not an operational precision).

| threshold | rule | TP / FN | FP / TN | recall [95% CI] | FPR [95% CI] | sample precision |
|---|---|--:|--:|--:|--:|--:|
| 45 m | S | 37 / 59 | 29.8 / 1,115.2 | 0.39 [0.29, 0.48] | 0.026 [0.018, 0.037] | 0.55 |
| 45 m | U | 53 / 43 | 59 / 1,086 | 0.55 [0.45, 0.65] | 0.052 [0.040, 0.066] | 0.47 |
| unified 3σ (3.9–6.2 m) | S | 45 / 51 | 314 / 831 | 0.47 [0.37, 0.57] | 0.274 [0.249, 0.301] | 0.13 |
| unified 3σ (3.9–6.2 m) | U | 72 / 24 | 628 / 517 | 0.75 [0.66, 0.83] | 0.548 [0.520, 0.577] | 0.10 |

Under rule S, an FP count is an expectation over the hypothesized sign. The counts under a positive or a negative hypothesis are 37 and 22 at 45 m, and 313 and 315 at 3σ.

**Operating characteristic.** A sweep of 81 thresholds from 1 m to 2 km (Fig. S5; Table S33) gives real-event/pseudo-event discrimination AUCs of 0.73 [0.66, 0.80] under rule U and 0.59 [0.51, 0.67] under rule S. These are E1 diagnostics and are not comparable with the injection-trial AUC of Table 3. Rule S scores real events whose residual has the wrong sign as negative, which lowers its AUC. At 45 m, rule U and rule S have FPR 0.052 and 0.026, respectively. A post hoc Youden-optimal threshold of about 105 m leaves recall unchanged under both rules (0.55 for U, 0.39 for S) and roughly halves the FPR (0.027 for U, 0.014 for S). This value is reported for reference only and is not used anywhere in the paper. Holding the FPR at or below 0.01 requires 186 m under rule S (recall 0.35) and about 1.8 km under rule U (recall 0.27).

**Hypothesized sign under rule S.** Pseudo-event steps are nearly symmetric in sign (48.4% positive, median −0.3 m). Varying the hypothesized positive-sign probability p₊ from 0 to 1 changes the rule-S FPR from 0.019 to 0.032 at 45 m and from 0.273 to 0.275 at 3σ, and leaves the rule-S AUC unchanged at 0.588 (Section S17).

**Check on events never used in the earlier analysis.** Because the conference analysis applied the 45 m threshold to the 46 events of the 2025-07/08 campaign, we repeated the evaluation on the 85 events from the other four campaigns, of which 53 are evaluable. Recall at 45 m is 0.36 [0.24, 0.49] under rule S and 0.55 under rule U, compared with 0.42 [0.28, 0.57] and 0.56 on the 43 evaluable conference-campaign events. The discrimination AUC is 0.72 versus 0.73 (rule U). The pseudo-event FPR does not depend on the event subset (0.052 at 45 m, rule U). The main conclusions therefore do not depend on events that the threshold's earlier use could have influenced.

**Stratification.** Per-satellite evaluable pseudo-events are balanced (184–199 each). Per-satellite FPR at 45 m (rule U) ranges from 0.040 to 0.062. The satellite-weighted FPR equals the pooled value at 45 m and differs by 0.001 at 3σ (0.052/0.547 versus 0.052/0.548). Excluding the 18 pseudo-events inside the May 2024 storm interval changes the FPR by ≤ 0.005 (0.049/0.543). The FPR does vary by half-year, from 0.000 to 0.141 at 45 m and highest in 2024-H2 (Table S26), so the pooled value averages over periods with different drag and tracking conditions. Two earlier pseudo-event draws under the same protocol gave consistent pooled rule-U FPRs (0.057/0.546, n = 1,131; 0.052/0.553, n = 1,142; Section S9). The originally tabulated draw (n = 1,131) depended on the TLE archive state at the time and cannot be reproduced exactly from the current archive, so the reproducible draw is now used throughout.

**Interpretation.** Under both symmetric rules, lowering the threshold to the local TLE residual scale raises recall, but it also raises the FPR by roughly an order of magnitude: from 0.026 to 0.274 under rule S and from 0.052 to 0.548 under rule U. The conclusion that a σ_TLE-based threshold is operationally unacceptable is therefore not an artifact of the original rule asymmetry. The interpretation remains conditional: *for the evaluated campaign and detector configuration, the 45 m threshold happens to be close to the estimated effective inter-TLE ambiguity scale.* A worked example is given here. In quiet conditions (σ_TLE ≈ 2 m, |ȧ| ≈ 49 m/d, Δt ≈ 0.9 d, c = 0.32), σ_eff ≈ 14 m. In the storm (|ȧ| ≈ 182 m/d), σ_eff ≈ 52 m. *The threshold comparison is consistent with a substantial drag-related contribution to the inter-TLE ambiguity under the evaluated conditions*, but it does not by itself prove that all false alarms are drag-driven. The gap between rules S and U also shows that 16 real events at 45 m (27 at 3σ) exceed the threshold with the *wrong* sign; Section 5.5 traces most of the large-amplitude cases to contaminated pre-event trends.

### 5.5 Decomposing the gap between detector-level and real-event sensitivity

Six candidate factors could separate detector-level injection sensitivity from real-event sensitivity:

1. Post-processing injections are an upper bound.
2. The consistency screening of verified events rejects some genuine maneuvers.
3. TLE-side association rules differ from the per-sample hit criterion.
4. SP3-side truth definition imposes its own losses.
5. Multiple burns can pile up within one update interval.
6. TLE fitting and averaging smooth or delay the signal.

The original submission discussed these qualitatively. Four diagnostics now quantify them (Tables 6 and 6a; Tables S34–S35; Section S17). All of them are *descriptive* decompositions; none is a causal identification.

**Table 6a — Outcome classes of the 131 verified events at 45 m (rule S)**, with cluster-bootstrap 95% CIs over 23 satellite × campaign clusters (B = 2,000). The lower block applies the TLE-response classification of (c) to the 22 clean-window events of 50–300 m.

| class | definition | n | proportion [95% CI] |
|---|---|--:|--:|
| excluded, pre-event coverage | < 3 TLEs in [t_start − 3 d, t_start − 2 h] | 34 | 0.26 [0.10, 0.46] |
| excluded, post-event coverage | no TLE in [t_end + 2 h, t_end + 3 d] | 1 | 0.01 [0.00, 0.03] |
| detected | \|residual\| > 45 m, correct sign | 37 | 0.28 [0.16, 0.39] |
| below threshold | \|residual\| ≤ 45 m | 43 | 0.33 [0.22, 0.48] |
| wrong sign | \|residual\| > 45 m, opposite sign | 16 | 0.12 [0.06, 0.18] |
| *clean 50–300 m (n = 22):* no TLE response | \|ratio\| < 0.5 at every TLE within 3 d | 17 | 0.77 [0.50, 0.97] |
| *clean 50–300 m:* delayed response | first TLE not, a later TLE in [0.5, 2] | 3 | 0.14 [0.00, 0.41] |
| *clean 50–300 m:* immediate response | first post-event TLE in [0.5, 2] | 0 | 0.00 |
| *clean 50–300 m:* other | e.g. > 2 or opposite sign | 2 | 0.09 [0.00, 0.22] |

**(a) Outcome classes.** Each of the 131 verified events is assigned to one of five classes at 45 m under rule S: excluded for insufficient pre-event coverage (34) or post-event coverage (1); detected (37); below threshold (43); or above threshold with the wrong sign (16). Coverage exclusion is therefore the largest single loss after sub-threshold misses.

**(b) Pre-event trend contamination, including coordinated burns.** E1 extrapolates a linear trend fitted over the preceding 3 days. During campaigns, that window often contains earlier burns. We flag an evaluable event as *contaminated* when the pre-event window contains an SP3 candidate with |step| ≥ 500 m, *regardless of its verdict*, so that coordinated burns rejected by the common-mode check are included. In 39 of the 96 events, the fitted |ȧ| then reflects the campaign staircase, not drag (median 711 m/day versus 23.5 m/day in clean windows). Contamination biases the comparison in both directions.

- **Model probabilities are deflated.** The inflated |ȧ| enters σ_eff, so the mean predicted probability is 0.39 although observed recall is 0.72.
- **Small-amplitude "detections" are inflated.** For 1–300 m events in contaminated windows, the median ratio of TLE residual to SP3 step is 23–44, so the residual reflects neighbouring burns rather than the event itself. These events are detected at 0.57–0.86, which is an association artifact.

In clean windows the bias reverses: observed recall is 0.16 against a mean predicted probability of 0.59. The bin-level agreement in Table 4 is therefore partly a cancellation of these two biases. **The residual of −0.17 in the 1–3 km bin is fully accounted for:** all three misses in that bin are wrong-sign residuals, and each has km-scale burns in its pre-event window. In two of the three, those burns were rejected by the common-mode check. Of the 16 wrong-sign events overall, 11 are contaminated.

*Effect of the burns rejected by the common-mode check.* In 27 of the 96 evaluable events (28%), the pre-event window contains a ≥ 500 m candidate rejected by the common-mode check, that is, a likely coordinated burn excluded from the library. In 24 of these, only rejected burns are present; in 3, verified burns are present as well. These 27 events are spread across all amplitude bins (7, 3, 3, 4 and 10 from the smallest to the largest bin). Their E1 recall is 0.74 under rule S and 1.00 under rule U, and 7 of them have wrong-sign residuals. The median |residual| is 2,168 m in the rejected-only group, compared with 6.4 m in clean windows, and the median ratio of residual to SP3 step is 1.74. The first post-event TLE arrives after a median 16.7 h, compared with 8.2 h in clean windows. Windows contaminated by verified burns only (n = 12) behave similarly (recall 0.67, median ratio 5.3). Coordinated burns that the library excludes are therefore not inert. They enter E1's residuals for more than a quarter of the evaluable events, inflating small-amplitude detections and producing wrong-sign misses. Because these burns cannot be independently verified, we do not treat them as necessarily real. We note, however, that they appear in the independently produced TLE series as orbit changes of the expected size, which suggests that at least the large rejected candidates are real burns rather than SP3 processing artifacts.

**(c) TLE response in clean windows.** For each evaluable event, we computed the ratio (TLE residual)/(SP3 step) at every TLE within 3 days after t_end. The 3-day window is E1's own post-event window, so the response classification uses the same TLEs as E1. It does not depend on the 45 m threshold, and it is independent of the sign and coverage classes of (a). In clean windows, none of the 22 events of 50–300 m shows an immediate response, defined as a first post-event ratio between 0.5 and 2. Three show a delayed response, at a later TLE, and 17 show *no* response, meaning |ratio| < 0.5 throughout the 3 days. By contrast, 4 of the 5 clean events of ≥ 300 m respond immediately. The no-response share is 0.77 with a cluster-bootstrap 95% CI of [0.50, 0.97].

*Sensitivity of the classification.* Varying the ratio cut over {0.3, 0.5, 0.7} and the window over {3, 5, 7} d gives 10–17 no-response events out of 22. Zero events respond immediately in every variant, and 4 of the 5 clean events of ≥ 300 m respond immediately in every variant. With longer windows, some events are reclassified as "delayed" (at most 5) or "other", because later burns enter the window. Across the 3-day window, the largest |residual| at any TLE has a median of 10 m, and 16 of the 22 events never exceed 45 m.

*Covariates and alternative explanations.* Compared with the five responding events, the 17 no-response events have fewer post-event TLEs within 3 days (median 4 versus 7), smaller amplitudes (median 97 m versus 178 m), and more negative-going steps (65% versus 40%). Twelve of the 17 come from the 2025-07/08 campaign, whose median update interval was 21.6 h, and they are spread over five satellites. Several explanations remain open:

- the TLE generation chain smooths or delays small steps beyond the 3-day window (factors 1 and 6);
- SP3-side truth losses, meaning that some verified sub-300 m steps are not real orbit changes (factor 4), which the predominance of negative-going steps during orbit-raising makes plausible;
- sparse post-event TLE coverage during the campaign;
- amplitudes close to the effective inter-TLE ambiguity.

The finding is therefore *consistent with a limitation upstream of the detector*: for most isolated sub-300 m events, the published TLEs do not reflect the SP3 step within the evaluation window. The present data do not establish the cause.

**(d) Multiple burns and serial correlation.** Events that share a TLE update interval with another verified event (55 of 96) are detected at the same rate as isolated events (0.38 versus 0.39 at 45 m), so pile-up (factor 5) is not a dominant loss. Within-cadence serial correlation does not explain the dense-cadence injection residual (Section 4.4).

**Table 6 — Real-event outcomes by amplitude bin and pre-event trend status** (45 m, rule S; P̄ = mean model-implied probability, descriptive refit; ratio = median TLE residual / SP3 step).

| bin | pre-event window | n | recall | P̄ | median \|ȧ\| (m/d) | ratio |
|---|---|--:|--:|--:|--:|--:|
| 1–50 m | clean | 30 | 0.00 | 0.36 | 52 | −0.12 |
| 1–50 m | contaminated | 7 | 0.57 | 0.00 | 1,167 | 32 |
| 50–100 m | clean | 11 | 0.09 | 0.80 | 17 | 0.05 |
| 50–100 m | contaminated | 5 | 0.80 | 0.15 | 555 | 44 |
| 100–300 m | clean | 11 | 0.27 | 0.86 | 22 | 0.00 |
| 100–300 m | contaminated | 7 | 0.86 | 0.38 | 681 | 23 |
| 300 m–1 km | clean | 1 | 1.00 | 0.86 | 23 | 0.78 |
| 300 m–1 km | contaminated | 7 | 0.57 | 0.66 | 482 | 1.8 |
| 1–3 km | clean | 4 | 1.00 | 1.00 | 19 | 1.26 |
| 1–3 km | contaminated | 13 | 0.77 | 0.54 | 902 | 0.84 |

**Synthesis (descriptive).** Below about 300 m, the gap between injection and real-event sensitivity coincides with the absence of a TLE response for isolated events and with association artifacts for events inside campaigns. Above about 300 m, isolated events are detected and the remaining misses come from contaminated pre-event trends. This decomposition strengthens the upper-bound reading of the injection results. It also implies that real-event recall for small, isolated maneuvers is substantially lower than the bin-level Table 4 suggests: 0.00 for 1–50 m and 0.09 for 50–100 m, on small samples. The orbit-state-level injection experiment remains the direct test for separating TLE-generation effects from truth losses.

## 6. Generalization Evaluation

### 6.1 Temporal hold-out

Calibrating on windows before 2025-07-01 (8,778 trials; within-period ĉ = 0.28, then fixed) and testing after (6,996 trials): held-out log loss 0.124 (SNR_eff) versus 0.141 (amplitude-only); AUC 0.977 versus 0.967; Brier 0.039. The advantage of the drag-aware relation survives on data from a later epoch than any used in calibration. The test period contains no windows in the high-drag tercile, so the held-out comparison covers the low- and mid-drag regimes only.

### 6.2 Blocked cross-validation

With five folds formed from satellite × contiguous five-window time blocks — adjacent overlapping windows never straddle folds, and c is re-estimated within each training fold — out-of-fold log loss is 0.184 versus 0.205 and Brier 0.056 versus 0.063 (SNR_eff versus amplitude-only), essentially identical to a plain cluster CV (0.183 / 0.204), demonstrating that window-overlap dependence leakage does not drive the comparison.

### 6.3 Future work

The planned extensions are:

- leave-one-satellite, leave-one-drag-regime and leave-one-campaign hold-outs;
- a complete domain-transfer protocol for the Starlink-trained detector family;
- extension of the calibrated relation to the ILRS altimetry benchmark and other constellations;
- orbit-state-level and observation-level injections, which are the direct test of the upstream TLE-response loss identified in Section 5.5(c);
- a real-event estimator that is robust to pre-event trend contamination, for example by masking known SP3 candidates of any verdict from the trend window;
- a cadence-dependent drag-ambiguity term to address the 1× residual;
- a sensitivity sweep of the fixed detector and estimator parameters (MAD multiplier, CUSUM κ and h, trend-window length);
- validation of the coordinated-burn candidates as a separate class if operator records become available;
- quantitative space-weather attribution.

## 7. Discussion and Limitations

**Operational implications.** Under the evaluated detector, the reliable detection threshold of TLE-based maneuver detection is not a constant but a function of (σ_TLE, Δt, ȧ_drag). The inference "no maneuver was seen in TLEs, therefore none occurred" is defensible only when the hypothesized maneuver's SNR_eff lies well above the calibrated detection scale, for a detector of the same family under comparable data conditions. Even then it holds only at the detector level. Section 5.5(c) shows that small, isolated real maneuvers often leave no TLE response at all.

> **Box 2 — Operational reading, for FS7-like conditions and detector D1 only.** For a satellite with median TLE update interval Δt, robust residual scale σ_TLE, and drag rate |ȧ|, the semi-major-axis step needed for a detection probability p is approximately
>
> Δa_p ≈ SNR_p · sqrt(σ_TLE² + (c·|ȧ|·Δt)²),
>
> with SNR₅₀ ≈ 3.8, SNR₉₀ ≈ 9.9 and c ≈ 0.3 (descriptive refit). For example, with σ_TLE = 2 m, |ȧ| = 49 m/day and Δt = 0.9 d, σ_eff ≈ 14 m and Δa₉₀ ≈ 140 m. With σ_TLE = 21 m, |ȧ| = 76 m/day and Δt = 2 d, Δa₉₀ ≈ 520 m. The empirical injection values of Table 4a should be preferred where they apply. **The formula systematically under-predicts the 90% amplitude at 1× cadence (by 1.1–1.9×) and must not be used to set a conservative threshold for densely updated objects.** In particular, the 22 m model value at 1×·low is an extrapolation below the validated truth scale. For a conservative choice, use the upper CI bound of the interpolated empirical Δa₉₀ for the matching condition. The coefficients are detector- and population-specific and should be recalibrated for another detector or constellation. The result is a detector-level upper bound; for isolated sub-300 m maneuvers, real-event recall in FS7 was far lower (Table 6).

**Context for the ≈18 m station-keeping figure.** The ≈18 m value is a *nominal* along-track semi-major-axis change, Δa = 2aΔv/v ≈ 18.3 m, for an assumed routine ΔV of 0.01 m/s at a = 6,928 km. It is not an observed event and is not part of the 96 evaluable events. Two empirical observations support the statement that steps of this size are not reliably resolved under the evaluated configuration. First, injection recall at the smallest grid amplitude (20 m) is 0.13–0.58 across the nine conditions. Only the 1×·low-drag condition exceeds 0.4, and those hits are partly background coincidences (Section 4.5). Second, the 30 clean-window real events of 1–50 m have recall 0.00 at 45 m (0.10 at 3σ). The value also lies below the 26 m smallest validated SP3-derived event amplitude, so the truth pipeline itself does not resolve it.

**Population of applicability (external validity).** The results apply most plausibly to satellites resembling the evaluated conditions: ≈ 550 km altitude and 24° inclination; impulsive chemical burns from tens of metres to 2.8 km, individually performed; median TLE update intervals of 8–12 h (21.6 h in campaigns); σ_TLE of 1–21 m and |ȧ| of 18–77 m/day in quiet windows; and detector D1. Table S44 maps each condition to what a transfer would require, including the truth source, number of events and calibration protocol. They have not been transferred to any other constellation. Statements such as "kilometre-scale raises are captured with ≈ 82% recall" refer to evaluable, individually verified events under these conditions. Coordinated multi-satellite burns, low-thrust or continuous maneuvers, other altitudes and other tracking densities are outside the evaluated domain.

**Limitations.**

(i) Injections are post-processing-level. All injection results are upper bounds under TLE-equivalent perturbations, and end-to-end sensitivity is unvalidated.

(ii) The decimation ablation carries confounds: sample count, CUSUM accumulation, and the σ background.

(iii) c, SNR₅₀ and β are jointly calibrated and parameterization-dependent, and none of them is separately interpretable. The c = 1 variant is retained only as a sensitivity reference.

(iv) At 1× cadence, the model under-predicts the interpolated 90% amplitudes by 1.1–1.9×. When fitted at that cadence alone, the likelihood rises monotonically toward the drag-only limit (95% set [0.56, ∞)), so c is not identified. Within-cadence serial correlation does not explain the residual. A post hoc √Δt form removes most of it but under-predicts 4×·high and needs independent confirmation. The drag term c·|ȧ|·Δt is an empirical effective ambiguity: it does not separate tracking, SGP4-fitting, density-model and update-strategy contributions.

(v) Recall estimates apply to the 96 evaluable events. Exclusion of the other 35 events depends on campaign and satellite. Campaign-weighted estimates differ by ≤ 0.08, but the deterministic bounds for the full library are wide (Table 2b).

(vi) The /√2 in the σ_TLE estimator assumes independent errors; the assumption is checked but not guaranteed.

(vii) c has not been recalibrated on any other constellation (Table S44).

(viii) The SP3-side checks share one truth source and are consistency criteria, not independent evidence. Coordinated burns are excluded by design, and every result refers to individually verified events only. For sub-300 m events, SP3-side truth losses cannot be excluded as a cause of the missing TLE response (Section 5.5(c)).

(ix) The real-event estimator E1 differs from the calibration detector D1. Its linear pre-event trend is contaminated by earlier burns in 39 of 96 events, so the bin-level real-event comparison is descriptive and confounded (Section 5.5).

(x) The probability outputs are raw model probabilities with a held-out calibration slope of 1.22; recalibrated variants are reported separately.

## 8. Conclusion

Under the evaluated FS7 data, TLE update patterns and MAD/CUSUM detector, a jointly calibrated empirical detectability relation, based on the effective residual and a drag-related inter-TLE ambiguity, improves the alignment of detector-level sensitivity curves across cadence and drag regimes. It also improves prediction on temporally held-out injections. The interpolated detector-level 90% recall amplitude rises from about 40 m to about 480 m across the evaluated cadence and drag regimes. On real FS7 events, recall rises from 0.11 to 0.82 across amplitude bins, but a decomposition shows that the bin-level agreement with the model is partly fortuitous. Most isolated sub-300 m events leave no TLE response within three days, which is consistent with, but does not establish, a limitation upstream of the detector. Events inside campaigns are affected by pre-event trends contaminated by neighbouring burns, including coordinated burns excluded from the library. The relation's coefficients are parameterization-dependent and should not be interpreted as universal physical constants. Neither the injection floors nor the model-implied amplitudes should be interpreted as end-to-end maneuver-detection limits of the public TLE product. They are detector-level results under TLE-equivalent perturbations. The storm-interval candidates are drag-attributed only under the available evidence. Within the stated conditions (§7; Table S44), public TLEs remain a meaningful screen for kilometre-scale, individually performed orbit changes. They are not a reliable basis for asserting the absence of small maneuvers.


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

**Fig. 3.** Injection recall versus Δa by cadence and drag regime, with cluster-bootstrap 95% CIs. The interpolated 90% recall amplitudes range from 41 to 476 m and the grid floors from 50 to 500 m (Section 4.1, Table 4a).

![](figures_pub/fig_fs7_injection_collapse/fig_fs7_injection_collapse_en_light.png)

**Fig. 4.** Collapse test: detection-rate curves separate when plotted against Δa/σ_TLE and align when plotted against SNR_eff (Section 4.3).

![](figures_pub/fig_fs7_injection_metrics/fig_fs7_injection_metrics_en_light.png)

**Fig. 5.** False-alarm rate and recall operating points by cadence and drag condition (Section 4.5).

![](fig_fs7_real_event_recall.png)

**Fig. 6.** Real-event comparison versus amplitude: observed E1 recall at the pre-specified 45 m and unified 3σ thresholds (Wilson 95% CIs), and the mean D1-based descriptive model probability. The latter is calibrated on injections with detector D1 and is not a fitted or calibrated E1 probability, so the panel is not a goodness-of-fit test. The panel also shows the injection-based prediction, and the amplitudes of the 21 storm-interval drag-attributed candidates (Sections 5.1 and 5.3).

Supplementary figures (in the Supplementary Material):

- **Fig. S1.** Profile likelihood of c with the reference values ĉ = 0.32, c = 0.28 and c = 1, and the joint (c, SNR₅₀) likelihood surface with β profiled; the ridge visualizes the −0.98 parameter correlation (Section 3.3).
- **Fig. S2.** Reliability diagrams on the temporal hold-out, raw versus Platt-recalibrated (Section 4.6).
- **Fig. S3.** Altitude–inclination domain map of the study satellites (56 with a valid noise estimate) colored by nominal TLE noise floor, with fitted contours σ_th(h); contextual only (Section 7).
- **Fig. S4.** Amplitude, campaign and satellite distributions of included (96) versus excluded (35) events (Section 2.6).
- **Fig. S5.** Real-event versus pseudo-event ROC curves and threshold sweep under the symmetric rules S and U, with the 45 m operating point marked (Section 5.4).

## Appendix A — Derivations and worked example

**SNR₉₀.** From P = [1 + exp(−β(log₁₀SNR − log₁₀SNR₅₀))]⁻¹, setting P = 0.9 gives log₁₀SNR₉₀ = log₁₀SNR₅₀ + ln 9 / (β ln 10), i.e. SNR₉₀ = SNR₅₀·10^{ln9/β}; β is estimated on the log₁₀ axis.

**Worked example (4×·high condition; full-data descriptive-refit coefficients).** σ_TLE = 20.8 m; |ȧ| = 76.2 m/day; Δt = 1.98 d; c = 0.32. Drag term: 0.32 × 76.2 × 1.98 = 48.3 m. σ_eff = sqrt(20.8² + 48.3²) = 52.6 m. Model-implied Δa₉₀ = 9.87 × 52.6 m = 519 m (the 515 m in the table in Section 4.4 uses the unrounded condition medians), versus the interpolated empirical 90% amplitude of 476 m [440, 537] and the grid floor of 500 m (smallest grid amplitude). These are different quantities; the model-implied value lies within 10% of the interpolated value and inside the grid resolution.

## Appendix B — The effective TLE residual scale σ_TLE

The estimator is fully specified here so that it can be evaluated without the companion study [11].

1. **Input and quality control.** A window of 40 consecutive TLEs of one satellite, using the semi-major axis derived from the TLE mean motion, with duplicate epochs removed. A window is used only if, at full cadence, it contains no single inter-TLE step > 0.3 km (to exclude maneuvers) and no gap > 5 d. After decimation (1×, 2×, 4×), at least 10 points must remain, and windows with σ_TLE = 0 are discarded. Windows slide with a stride of 20 TLEs, so adjacent windows overlap by 50%.
2. **Detrending.** A least-squares line a(t) = a₀ + ȧ·t is fitted over the window. Its slope is the window drag rate ȧ, and the detrended series is r_k = a_k − ȧ·(t_k − t₀).
3. **Single-step differences.** d_k = r_k − r_{k−1}, for k = 1…n−1.
4. **Robust scale.** σ_TLE = 1.4826 · median_k |d_k − median(d)| / √2. The factor 1.4826 makes the MAD consistent with a Gaussian standard deviation. The factor 1/√2 converts the scale of a difference of two independent errors into the scale of a single error.
5. **Update interval.** Δt is the median of t_k − t_{k−1} within the window.
6. **Autocorrelation diagnostic.** r₁ is the lag-1 correlation of d_k − median(d) within the window. For independent errors, differencing implies r₁ = −0.5. The observed medians of +0.24, +0.46 and +0.49 at 1×, 2× and 4× (Table S21) are positive. They cannot arise from independent or AR(1) level errors, because for AR(1) errors with coefficient φ the lag-1 correlation of differences is −(1 − φ)/2, which lies between −0.5 and 0. Positive values indicate a slowly varying component that the linear detrending does not absorb, such as drag variability within the window. Under such structure, the i.i.d.-based /√2 conversion is not exact. σ_TLE is therefore an effective scale for the detector's inter-TLE differences, not an estimate of the TLE element error.

The same function (`window_stats` in `fs7_injection_sweep.py`) produces the per-window (σ_TLE, ȧ, Δt) used in every injection trial.

## Data and code availability

leoOrb SP3 products are publicly distributed by TACC (file versions, download dates, and checksums recorded in the release). TLE histories were obtained from Space-Track; per the Space-Track user agreement, raw TLE data are not redistributed — the release instead includes the NORAD identifiers and epoch lists (metadata, which the agreement permits) and retrieval scripts that reconstruct the data set under the user's own Space-Track credentials. The code release includes all analysis scripts (injection sweeps, joint calibration, blocked cross-validation, event building, unified recall comparison), the derived event tables (including per-event predicted probabilities; no reconstructable raw TLE content), and a README specifying (1) the environment (Python and key package versions), (2) data-retrieval instructions, (3) the exact command reproducing each table and figure, (4) expected output checksums, and (5) the fixed random seeds and configuration files. Analyses specific to this revision are produced by `fs7_review5_analysis.py`, which writes `fs7_review5_analysis.json` and three derived tables. Geomagnetic indices are taken from the GFZ Kp product [14], and the extract used is included. Analyses added in the second revision are produced by `fs7_review6_analysis.py`. An anonymized review package accompanies this submission. It contains all scripts, derived tables, the TLE epoch metadata, a SHA-256 manifest, and a minimal reproduction script (`fs7_repro_minimal.py`). This script runs in seconds without Space-Track credentials or a database, and it re-derives and checks the main values of Tables 3, 4a, 4 and 5. Results that need the raw TLE archive are identified in the package README. The code, derived tables, configuration files, seeds and checksums will be archived in a public repository at acceptance [repository DOI to be inserted]. **Computational cost.** All analyses run single-threaded, without parallelization, on a laptop-class machine (Windows 11, ARM64, Python 3.13; NumPy 2.4, pandas 3.1, SciPy 1.16; exact versions in `fs7_env_freeze.txt`). The 15,774-trial injection sweep is estimated at about 1 min, extrapolated from 3.6 ms per trial measured over 150 timed trials. Measured wall times are 16 s for the B = 200 joint-identification bootstrap together with the profile-likelihood grid (`fs7_review3_analysis.py`), and 5 s for the complete revision analysis (`fs7_review5_analysis.py`), which includes every B = 2,000 bootstrap of this revision. TLE retrieval and SP3 download are network-bound and dominate the end-to-end time.

## References

1. F. R. Hoots, R. L. Roehrich, *Models for Propagation of NORAD Element Sets*, Spacetrack Report No. 3, 1980.
2. D. A. Vallado, P. Crawford, R. Hujsak, T. S. Kelso, "Revisiting Spacetrack Report #3," AIAA/AAS Astrodynamics Specialist Conference, Keystone, CO, 2006, AIAA 2006-6753.
3. T. Flohrer, H. Krag, H. Klinkrad, "Assessment and categorization of TLE orbit errors for the US SSN catalogue," Advanced Maui Optical and Space Surveillance Technologies (AMOS) Conference, 2008.
4. J. Geul, E. Mooij, R. Noomen, "TLE uncertainty estimation using robust weighted differencing," *Advances in Space Research*, 59(10), 2577–2593, 2017. doi:10.1016/j.asr.2017.02.038.
5. T. Kelecy, M. Jah, "Detection and orbit determination of a satellite executing low thrust maneuvers," *Acta Astronautica*, 66(5–6), 798–809, 2010.
6. R. P. Patera, "Space event detection method," *Journal of Spacecraft and Rockets*, 45(3), 554–559, 2008.
7. S. Lemmens, H. Krag, "Two-line-elements-based maneuver detection methods for satellites in low Earth orbit," *Journal of Guidance, Control, and Dynamics*, 37(3), 860–868, 2014.
8. W. S. Schreiner et al., "COSMIC-2 radio occultation constellation: First results," *Geophysical Research Letters*, 47(4), e2019GL086841, 2020. doi:10.1029/2019GL086841.
9. Taiwan Analysis Center for COSMIC (TACC), *FORMOSAT-7/COSMIC-2 near-real-time data products (leoOrb precise orbit files)*, https://tacc.cwa.gov.tw, accessed August 2026.
10. S. Hilla, *The Extended Standard Product 3 Orbit Format (SP3-c)*, National Geodetic Survey / International GNSS Service, 2010.
11. [Authors], "Empirical characterization of TLE-derived semi-major-axis noise from DORIS-certified quiescent arcs and its application to FORMOSAT maneuver analysis," manuscript in preparation, 2026.
12. W. E. Parker, R. Linares, "Satellite drag analysis during the May 2024 Gannon geomagnetic storm," *Journal of Spacecraft and Rockets*, 61(5), 2024. doi:10.2514/1.A36164.
13. J. M. Picone, A. E. Hedin, D. P. Drob, A. C. Aikin, "NRLMSISE-00 empirical model of the atmosphere: Statistical comparisons and scientific issues," *Journal of Geophysical Research: Space Physics*, 107(A12), 1468, 2002. doi:10.1029/2002JA009430.
14. J. Matzka, C. Stolle, Y. Yamazaki, O. Bronkalla, A. Morschhauser, "The geomagnetic Kp index and derived indices of geomagnetic activity," *Space Weather*, 19(5), e2020SW002641, 2021. doi:10.1029/2020SW002641. Data: GFZ Potsdam, Kp_ap_Ap_SN_F107 file, https://kp.gfz.de, accessed November 2026.
