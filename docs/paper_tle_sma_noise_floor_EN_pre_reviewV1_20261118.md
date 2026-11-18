# Empirical Characterization of TLE-Derived Semi-Major-Axis Noise from DORIS-Certified Quiescent Arcs and Its Application to FORMOSAT Maneuver Analysis

**Authors:** [Author 1]ᵃ*, [Author 2]ᵃ, [Author 3]ᵇ

ᵃ [Affiliation, address, country]
ᵇ [Affiliation, address, country]

\* Corresponding author. E-mail: [address]

## Highlights

- TLE semi-major-axis noise is measured in operator-certified maneuver-free arcs.
- Thirteen DORIS altimetry satellites (719–1338 km) give a median noise of 0.24 m.
- Noise rises steeply at lower altitude with a drag-like scale height of 77 km.
- A 0.9 m threshold detects 67 of 68 certified Jason-3 maneuvers.
- Along-track Δv is recoverable from TLEs on clean arcs; cross-track Δv is not.

## Abstract

Two-Line Element (TLE) sets are widely used to detect maneuvers of satellites in low Earth orbit, usually by thresholding the change in the TLE-derived semi-major axis (SMA). The noise level that sets such thresholds is rarely measured on intervals known to be free of maneuvers. We measure it on operator-certified quiescent arcs of thirteen International DORIS Service (IDS) altimetry satellites at 719–1338 km, each contributing 22–200 arcs, using a detrended-residual and an adjacent-difference robust estimator. The adjacent-difference noise has a median of 0.24 m (range 0.07–1.24 m), two orders of magnitude below fixed thresholds of tens of metres used in operational screening; the result is stable under changes of thinning interval, arc trimming and detrending order. Across a wider sample including lower orbits, the noise follows σ(h) = [σ₀² + (A e^{−(h−400)/H})²]^{1/2} with H = 77 km, within the range of thermospheric density scale heights computed with NRLMSIS 2.0. A 3σ threshold of 0.9 m detects 67 of 68 IDS-certified Jason-3 maneuver windows. Against IDS three-component Δv truth for SWOT and CryoSat-2, the along-track Δv recovered from TLEs correlates with truth at r = 0.942 on clean arcs, whereas the cross-track component shows no correlation. Applied to the FORMOSAT series, the framework separates a 1 m noise floor on non-propulsive FORMOSAT-3, four maneuvers of 51–798 m (0.03–0.42 m/s) on FORMOSAT-5, and a January 2026 FORMOSAT-7 orbit raise from constellation-wide negative steps that are not maneuvers. The results support altitude-dependent, σ-normalized detection thresholds.

**Keywords:** two-line elements; semi-major-axis noise; maneuver detection; DORIS; precise orbit determination; space situational awareness

---

## 1. Introduction

Space situational awareness for satellites without cooperative data relies on the public Two-Line Element (TLE) catalog. TLEs are mean elements fitted for the SGP4 propagator [1, 2]; their errors vary with orbit regime, tracking coverage and fit span and are not distributed with the elements [3–5]. A common maneuver-detection approach thresholds the change |Δa| in the TLE-derived semi-major axis (SMA) between consecutive element sets [6–8]. Whether a step can be attributed to propulsion rather than to fitting or modelling error depends on the noise level of the TLE-derived SMA.

We define the noise floor σ as the residual scatter of the TLE-derived SMA during an interval certified to be free of maneuvers. Two limitations affect current practice. First, the noise level is often assumed rather than measured: operational rule-based screening commonly uses fixed thresholds of tens of metres for orbits above 700 km — for example, σ = 50 m in the baseline of the screening system that motivated this study [9] — and such values have rarely been checked against maneuver-free observations above about 800 km. Second, the altitude dependence of TLE noise is usually not represented. Atmospheric density, and with it the unmodelled drag absorbed into the fitted elements, changes by orders of magnitude across low Earth orbit, so a single absolute threshold is expected to be conservative at high altitude and insensitive to small maneuvers at low altitude.

Measuring σ directly requires satellites with independently certified maneuver-free intervals. The altimetry missions supported by the International DORIS Service (IDS) [10] meet this requirement: their operators publish maneuver histories and thrust logs [11], and their precise orbits are maintained to centimetre level [12, 13]. We call the intervals between logged maneuvers *certified quiescent arcs*. Because the maneuver-free labels are produced independently of the TLE series, the noise estimate does not depend on a detector's own classification of the data.

The contributions are threefold:

1. We measure the TLE-derived SMA noise floor of thirteen IDS altimetry satellites at 719–1338 km on certified quiescent arcs with two robust estimators, test its sensitivity to processing choices, and characterize its altitude dependence (Sections 2–3).
2. We validate the detection threshold derived from the calibrated noise floor on 68 IDS-certified Jason-3 maneuver windows (Section 3.4).
3. We apply the framework to the FORMOSAT series and use IDS three-component Δv truth to delimit which maneuver components can be recovered from TLEs (Section 5).

The detection sensitivity of a TLE-based detector as a function of update cadence and drag, calibrated against FORMOSAT-7 precise orbits, is addressed in a companion study [14]; the present paper supplies the noise-floor input to such models and does not evaluate detector performance.

## 2. Data and Methods

### 2.1 Certified quiescent arcs and TLE data

Quiescent arcs are the intervals between consecutive maneuvers in the IDS maneuver histories and operator thrust logs [11], given in TAI and converted to UTC by subtracting TAI − UTC = 37 s. To exclude pre- and post-maneuver transients, each arc is trimmed inward by 0.75 d at both ends; an arc is retained if it contains at least 12 usable TLEs spanning at least 3 d. TLE histories were obtained from Space-Track (gp_history). Duplicate and near-duplicate epochs, which would artificially reduce robust scatter estimates, are removed by thinning each series to a minimum spacing of 3 h. The SMA is computed from the mean motion with μ = 398,600.4418 km³ s⁻².

### 2.2 Trend-robust noise estimators

Within a quiescent arc the SMA still contains a slow drag-driven trend, which is removed in two independent ways. The primary estimator fits a polynomial within each arc (degree 1 for spans < 10 d, degree 2 for < 40 d, degree 3 otherwise) and takes the robust standard deviation of the residuals,

$$\sigma_{\text{res}} = 1.4826 \cdot \mathrm{median}\big(|a_i - \hat a_i|\big). \tag{1}$$

The cross-check estimator removes the trend by adjacent differencing,

$$\sigma_{\text{diff}} = \frac{1.4826 \cdot \mathrm{median}\big(|\,a_{i+1}-a_i\,|\big)}{\sqrt{2}}, \tag{2}$$

where the factor √2 accounts for the variance of a difference of two independent errors. The constant 1.4826 converts the median absolute deviation (MAD) to a Gaussian-equivalent standard deviation [15]: for e ~ N(0, σ²), half of the probability mass lies within ±MAD,

$$P(|e| \le \mathrm{MAD}) = 2\Phi\left(\frac{\mathrm{MAD}}{\sigma}\right) - 1 = \frac{1}{2}, \tag{3}$$

so that MAD/σ = Φ⁻¹(3/4) = 0.67449 and

$$\sigma = \frac{\mathrm{MAD}}{\Phi^{-1}(3/4)} = 1.4826\,\mathrm{MAD}. \tag{4}$$

The two estimators respond differently to residual structure: σ_res retains slow residual curvature that the polynomial does not absorb, whereas σ_diff is insensitive to slow trends but assumes uncorrelated errors between adjacent element sets. Per-satellite estimates are medians over all qualifying arcs.

### 2.3 Sensitivity analysis

The thinning interval, the trimming window and the polynomial degree are processing choices. We repeat the full estimation on a 3 × 3 × 3 grid — thinning 1.5, 3 and 6 h; trimming 0.5, 0.75 and 1.0 d; polynomial degree rule shifted by −1, 0 and +1 (minimum degree 1) — and report the resulting range of the per-satellite and median estimates.

### 2.4 Lower-altitude reference data

No certified quiescent arcs exist for the Starlink constellation, whose satellites perform near-continuous station-keeping. As a lower-altitude reference we use a different quantity: the difference between the TLE-propagated SMA and the SMA of SpaceX's publicly distributed precise ephemerides [16] for 283 Starlink satellites (1 May to 20 September 2026, daily sampling, 35,460 comparisons). This is a TLE prediction error against an independent truth, not a quiescent-arc noise floor, and is reported only as an order-of-magnitude comparison.

## 3. Results

### 3.1 Noise floor of the IDS altimetry satellites

Table 1 lists the measured noise for the thirteen satellites. The adjacent-difference estimate σ_diff has a median of 0.24 m and ranges from 0.07 m (Sentinel-6A) to 1.24 m (HY-2A); twelve of the thirteen satellites are below 0.5 m. The detrended-residual estimate σ_res has a median of 0.72 m and ranges from 0.23 to 2.08 m. σ_res exceeds σ_diff for most satellites, as expected from residual curvature that a low-order polynomial does not remove over multi-week arcs; the two estimators agree to within a factor of two for four satellites and within a factor of seven for all.

**Table 1 — TLE-derived SMA noise of the IDS altimetry satellites on certified quiescent arcs** (ordered by σ_res).

| Satellite | NORAD | Altitude (km) | Quiescent arcs | TLE points | σ_res (m) | σ_diff (m) |
|---|---|--:|--:|--:|--:|--:|
| Sentinel-3A | 41335 | 803 | 137 | 11,821 | 0.23 | 0.16 |
| Jason-3 | 41240 | 1338 | 58 | 7,876 | 0.29 | 0.09 |
| SWOT | 54754 | 893 | 47 | 2,642 | 0.30 | 0.29 |
| Sentinel-3B | 43437 | 803 | 113 | 5,313 | 0.35 | 0.31 |
| Jason-2 | 33105 | 1311 | 54 | 5,688 | 0.39 | 0.14 |
| Sentinel-6A | 46984 | 1338 | 22 | 3,786 | 0.44 | 0.07 |
| HY-2D | 48621 | 952 | 44 | 5,323 | 0.72 | 0.24 |
| Jason-1 | 26997 | 1325 | 67 | 4,451 | 0.75 | 0.24 |
| HY-2C | 46469 | 952 | 46 | 6,249 | 0.76 | 0.23 |
| CryoSat-2 | 36508 | 719 | 200 | 9,851 | 0.97 | 0.34 |
| SARAL | 39086 | 785 | 47 | 8,994 | 1.47 | 0.24 |
| Envisat | 27386 | 766 | 140 | 9,431 | 1.47 | 0.45 |
| HY-2A | 37781 | 968 | 56 | 8,449 | 2.08 | 1.24 |
| **Median** | | | | | **0.72** | **0.24** |

![](figures_pub/fig_sigma_vs_altitude_paperA/fig_sigma_vs_altitude_paperA_en_light.png)

**Fig. 1.** TLE-derived SMA noise σ_diff versus altitude. Blue circles: IDS altimetry satellites on certified quiescent arcs (Table 1). Orange triangle: FORMOSAT-3 (non-propulsive; Section 5.1). Purple band: Starlink, TLE-propagated SMA versus SpaceX precise ephemerides (median and interquartile range, 351–578 km; a prediction error, not a quiescent-arc noise floor; Section 3.3). Grey dashed line: a fixed 50 m threshold.

The noise floor of 0.07–1.24 m lies two orders of magnitude below fixed thresholds of tens of metres (Fig. 1). For the altimetry satellites, a fixed σ = 50 m corresponds to a threshold 40–700 times larger than the measured noise.

**Altitude dependence.** Within 719–1338 km the noise decreases with altitude (Spearman ρ = −0.62 between altitude and σ_diff), with HY-2A and Envisat the main outliers. To extend the altitude range, per-satellite nominal noise levels for 56 satellites spanning 340–1340 km — the altimetry satellites, the six FORMOSAT-7 satellites, hold-out altimetry and gravity missions, and a Starlink sample, estimated with a sliding-window self-consistency estimator (40-TLE windows, steps > 0.3 km excluded, linear detrending) — were fitted with

$$\sigma_{th}(h) = \sqrt{\sigma_0^2 + \left(A\,e^{-(h-400)/H}\right)^2}, \tag{5}$$

giving σ₀ = 0.045 m, A = 24.5 m and H = 77 km (log-space R² = 0.89). Extrapolated to 800 km, Eq. (5) gives 0.15 m, the same order as the quiescent-arc median. The fitted H lies within the neutral-density scale heights computed with NRLMSIS 2.0 [17, 18] for 350–550 km: 51–54 km at F10.7 = 70 sfu, 67–70 km at 150 sfu, and 78–81 km at 220 sfu (solar flux index [19]). An exponential with this scale height is the signature expected if unmodelled drag dominates the TLE noise at low altitude; maneuver activity has no reason to follow it.

### 3.2 Sensitivity to processing choices

The sensitivity grid is evaluated with the current version of the IDS arc list, whose baseline configuration reproduces Table 1 to within 0.07 m for every satellite. Over the 27 processing configurations of Section 2.3, the median σ_diff of the thirteen satellites ranges from 0.22 to 0.29 m. The thinning interval is the main factor: 1.5 h thinning lowers σ_diff by about 10% and 6 h raises it by about 18%, consistent with residual near-duplicate solutions at short spacing. The median σ_res ranges from 0.56 to 0.89 m and depends mainly on the polynomial degree (individual satellites change by −40% to +64%), confirming that σ_res carries residual trend while σ_diff does not. In every configuration twelve of the thirteen satellites have σ_diff < 1 m (HY-2A: 1.2–1.4 m), and the altitude–σ_diff correlation stays negative (Spearman ρ between −0.64 and −0.47). The sub-metre noise floor and its decrease with altitude are therefore robust to these choices (Supplementary Table S1).

### 3.3 Lower-altitude comparison: Starlink

For 283 Starlink satellites at 351–578 km (1st–99th percentile of sample altitudes), the TLE-propagated SMA differs from the SpaceX precise ephemerides by a median of 57.0 m (interquartile range 23.6–110.8 m; 90th percentile 191.6 m). The median increases with propagation age, from 47.7 m at 0–6 h to 60.8, 67.9, 101.2 and 117.4 m at 6–12, 12–24, 24–48 and 48–72 h. This comparison includes station-keeping thrust between the TLE epoch and the comparison time: restricting it to 152 satellites with net SMA change below 10 km and to samples whose truth SMA rate is below 2,000, 1,000 or 500 m d⁻¹ lowers the median to 33.2, 35.0 and 36.7 m, but retains only 2.85% of the samples at the loosest limit. Starlink satellites therefore have no quiescent arcs comparable to those of the altimetry satellites, and their TLE noise cannot be measured with the method of Section 2. Self-consistency estimates obtained from the TLEs alone range from 3 to 30 m and depend on the estimator, the window length and the date of the data snapshot (Supplementary Section S2). The weekly median prediction error correlates with F10.7 (Spearman ρ = 0.56, p = 0.008, 21 weeks), but the point-wise correlation is only 0.06, so the data do not establish solar activity as the dominant driver. Whatever the estimator, the Starlink-altitude values exceed the quiescent-arc noise floor at 719–1338 km by one to two orders of magnitude, consistent with Eq. (5).

### 3.4 Validation on certified Jason-3 maneuvers

Jason-3 (1338 km) is nearly drag-free, and its operator thrust log provides 68 maneuver windows. For each window we compared the TLE-derived SMA step across the window with the IDS truth SMA change, taken as the net change of all burns in the window. With σ_res = 0.29 m (Table 1) and a threshold of 3σ = 0.88 m, 67 of the 68 windows are detected (98.5%). The single miss has a truth step of 5.0 m and an observed step of 0.37 m. One window whose logged burns carry no SMA change is detected through its out-of-plane signature and is excluded from the amplitude comparison; for the other 67 windows the truth steps range from 2.5 m to 9.5 km, and the observed and truth steps correlate at r = 0.84 (Fig. 2). Using σ_diff = 0.09 m instead would lower the threshold to 0.27 m and detect all 68 windows. The threshold implied by a fixed σ = 50 m (3σ = 150 m) is 171 times larger than the calibrated one; 53 of the 54 windows with truth steps between the two thresholds are detected.

![](figures_pub/fig_ids_detection_curve/fig_ids_detection_curve_en_light.png)

**Fig. 2.** Validation on 68 IDS-certified Jason-3 maneuver windows. (A) Detection rate versus truth Δa in amplitude bins (marker size proportional to the number of windows), with the calibrated 3σ threshold (0.9 m) and the 3σ threshold of a fixed σ = 50 m assumption (150 m). (B) TLE-observed versus IDS-truth Δa (net change per window, log–log); the red cross marks the single missed window.

## 4. Implications for Threshold Design

For a detector that thresholds |Δa|, maneuvers with amplitudes comparable to σ (signal-to-noise ratio below about 2) cannot be separated from noise using TLEs alone. By Section 3 and Eq. (5), this limit is most restrictive at low altitude, whereas at 700–1340 km sub-metre steps are resolvable. Detection thresholds are therefore better expressed as k·σ(h) than as one absolute value, and |Δa|/σ(h) provides a feature that is comparable across altitudes. How such a threshold behaves under realistic update cadence and drag variability — which add an inter-TLE ambiguity to σ — is quantified in the companion study [14]; a rule-based screening system built on these principles is documented in [9].

## 5. Application to the FORMOSAT Series

Table 2 summarizes the FORMOSAT satellites analysed. FORMOSAT-3 and FORMOSAT-5 lie at 670–790 km, at or just below the lower edge of the calibrated range; FORMOSAT-7 lies at 539–571 km (2024–2026 medians), below it.

**Table 2 — FORMOSAT satellites analysed** (median altitude, 2024–2026).

| Satellite | NORAD | Altitude (km) | Propulsion | Role |
|---|---|--:|---|---|
| FORMOSAT-3 A–F | 29047–29052 | 787–788 (3D: 675) | none | non-propulsive control |
| FORMOSAT-5 | 42920 | 723 | yes | maneuver observation |
| FORMOSAT-7-1 to 7-6 | 44349, 44351, 44343, 44350, 44358, 44353 | 539–571 | yes | maintenance and orbit raising |

### 5.1 FORMOSAT-3: non-propulsive control

The six FORMOSAT-3 (COSMIC) satellites have no propulsion and decay naturally. Over 18 October to 17 November 2026, with the estimators of Section 2.2 applied to the whole 30-day window, the five satellites at 786–787 km give σ_diff = 0.90–1.27 m (σ_res = 0.58–1.46 m), and FORMOSAT-3D, now at 670 km, gives σ_diff = 3.07 m. The values are higher than those of the altimetry satellites at similar altitude (SARAL, 785 km: 0.24 m), consistent with the poorer TLE fits of small decaying satellites, and the larger noise of FORMOSAT-3D at 670 km follows the altitude dependence of Eq. (5). We adopt σ ≈ 1 m as the regional noise floor near 790 km.

### 5.2 FORMOSAT-5: maneuver detection and Δv

FORMOSAT-5 (723 km, Sun-synchronous) shows, from 17 November 2025 to 17 November 2026, adjacent |Δa| with median 0.28 m, 90th percentile 0.89 m and 99th percentile 2.20 m, and four steps exceeding 50 m (Table 3). Relative to the ~1 m regional noise floor, the largest step corresponds to a signal-to-noise ratio of about 800. For a small tangential impulse on a near-circular orbit, the vis-viva relation gives Δv ≈ (v/2a)Δa with v = (μ/a)^{1/2}; for FORMOSAT-5 (a = 7100.9 km, v = 7.492 km s⁻¹),

$$\Delta v \approx \frac{7.492}{2 \times 7100.9} \times 0.798 \approx 0.42\ \text{m s}^{-1} \tag{6}$$

for the largest step. The four maneuvers correspond to 0.03–0.42 m s⁻¹, consistent with routine orbit maintenance of a Sun-synchronous satellite.

**Table 3 — FORMOSAT-5 steps exceeding 50 m** (17 Nov 2025 – 17 Nov 2026).

| Date (UTC) | Δa (m) | Δv (m s⁻¹) |
|---|--:|--:|
| 2025-12-16 | +797.7 | 0.42 |
| 2026-03-23 | +411.2 | 0.22 |
| 2026-04-14 | −519.0 | 0.27 |
| 2026-07-21 | +51.4 | 0.03 |

### 5.3 FORMOSAT-7: orbit raising and constellation-wide steps

The six FORMOSAT-7 satellites (537–577 km over the analysis year) show, from 17 November 2025 to 17 November 2026, median adjacent |Δa| of 4.6–8.6 m (σ_diff-equivalent 4.8–9.0 m) and 99th percentiles of 35–53 m — five to nine times the FORMOSAT-3 noise, as expected from Eq. (5) at their lower altitude. Between 19 and 27 January 2026, five satellites raised their orbits by a cumulative 9.2–9.4 km in steps of 2.5–9.4 km; FORMOSAT-7-3, which has not maintained its orbit since May 2025, did not take part. In addition, all six satellites show negative steps of −50 to −127 m on the same dates (around 1 January, 31 March, 17 April and 5–6 June 2026). Because these steps occur simultaneously on all satellites — including the non-maintained FORMOSAT-7-3 — and are uniformly negative, they are interpreted as drag- or fitting-related signatures rather than maneuvers. They exceed a 50 m threshold and would be flagged by an amplitude test alone; a common-mode check across the constellation is required to reject them, as also found against precise-orbit truth in [14]. Per-satellite statistics and the list of steps are given in Supplementary Tables S3–S4.

### 5.4 Recoverability of the Δv vector (SWOT and CryoSat-2)

Section 5.2 assumes a purely tangential impulse. IDS provides per-burn three-component Δv (radial, along-track, cross-track) for the impulsively maneuvering SWOT and CryoSat-2, which allows the TLE-recovered components to be tested. Using near-circular Gauss variational relations [20], the along-track component is recovered as Δv_t = nΔa/2 (n: mean motion) and the cross-track component as Δv_c = vΔi at the node; the radial component is not evaluated because of the weak sensitivity of TLE eccentricity.

For the along-track component, all 262 events give r = 0.548 (median absolute error 3.2 mm s⁻¹; median truth 16.0 mm s⁻¹). On the 207 events whose TLE brackets are not contaminated by neighbouring maneuvers, r = 0.942 (median absolute error 2.4 mm s⁻¹). The accuracy differs between satellites: r = 0.975 for CryoSat-2 (166 clean events) and r = 0.512 for SWOT (41 clean events). For the cross-track component, the 246 events give r = 0.002 with a median absolute error of 39.1 mm s⁻¹ against a median truth of 0.2 mm s⁻¹: the inclination changes involved (10⁻⁴–10⁻³ deg) lie below the precision of the TLE inclination, and the recovered values are dominated by noise (Fig. 3).

![](figures_pub/fig_ids_dv_vector/fig_ids_dv_vector_en_light.png)

**Fig. 3.** Cross-arc Δv recovery from TLEs versus IDS three-component truth. (A) Along-track, clean brackets (CryoSat-2 r = 0.975, SWOT r = 0.512). (B) Cross-track (r ≈ 0).

TLE-recovered Δv is thus reliable for the along-track component on clean arcs, which is the setting of the FORMOSAT-5 estimate in Section 5.2, whose steps are much larger than the 16 mm s⁻¹ median of this validation set. The cross-track component cannot be recovered at current TLE precision. All events evaluated here are impulsive chemical burns; continuous low-thrust maneuvers spread over many revolutions produce no single step and are outside the scope of this test.

## 6. Discussion

**Altitude-dependent, σ-normalized thresholds.** The TLE-derived SMA noise is 0.07–1.24 m at 719–1338 km (median 0.24 m) and follows a drag-like exponential toward lower altitude, where Starlink-altitude reference values are one to two orders of magnitude larger. A single absolute |Δa| threshold is therefore conservative at high altitude and too permissive of noise at low altitude; thresholds of the form k·σ(h) apply equally to rule-based detectors and to classifiers that use σ-normalized features.

**Fixed high-altitude thresholds.** A fixed σ = 50 m above 700 km overestimates the measured noise by a factor of 40–700 and, as the Jason-3 test shows, would leave most certified maneuvers below the detection threshold.

**Independent labels.** The noise floor is estimated on intervals certified maneuver-free by the operators, independently of the TLE series, which avoids the circularity of estimating noise on intervals labelled quiet by a detector.

**Recoverable maneuver components.** On clean arcs the along-track Δv is recoverable (r = 0.942; 0.975 for CryoSat-2), whereas the cross-track Δv is not (r = 0.002). Inferences of thrust direction or full three-dimensional Δv from TLEs require separate treatment of the two components.

**Constellation-wide signatures.** The simultaneous negative steps of all six FORMOSAT-7 satellites show that steps well above the noise floor are not necessarily maneuvers at low altitude; amplitude thresholds must be combined with checks for common-mode behaviour.

**Limitations.** (i) The quiescent-arc calibration covers 719–1338 km; below 700 km the altitude dependence rests on a self-consistency estimator and on a different quantity for Starlink, so statements for low altitude are comparative. (ii) σ_diff assumes uncorrelated errors between adjacent element sets; σ_res and σ_diff differ by up to a factor of seven, and the choice of estimator matters for thresholds near the noise floor. (iii) HY-2A (1.24 m) and Envisat (0.45 m) are higher than the other altimetry satellites at similar altitude, and FORMOSAT-3 (~1 m) is higher still; satellite-specific factors such as area-to-mass ratio and tracking coverage are not modelled. (iv) The Δv validation covers two impulsively maneuvering satellites, and the along-track accuracy differs markedly between them; validation per satellite is advisable before generalization. (v) The analysis uses a rolling TLE archive; self-consistency estimates at Starlink altitude change between data snapshots (Supplementary Section S2), whereas the quiescent-arc results are computed on fixed arcs.

## 7. Conclusion

On operator-certified quiescent arcs of thirteen IDS altimetry satellites, the TLE-derived SMA noise at 719–1338 km has a median of 0.24 m (0.07–1.24 m), robust to processing choices and two orders of magnitude below fixed thresholds of tens of metres. Toward lower altitude the noise grows with a scale height of 77 km, within the range of thermospheric density scale heights. A 0.9 m threshold derived from the calibrated noise detects 67 of 68 certified Jason-3 maneuver windows. TLE-recovered along-track Δv agrees with IDS truth on clean arcs (r = 0.942), whereas cross-track Δv is not recoverable. Applied to FORMOSAT, the framework establishes a ~1 m noise floor near 790 km, recovers four FORMOSAT-5 maneuvers of 0.03–0.42 m s⁻¹, and identifies a FORMOSAT-7 orbit raise while showing that constellation-wide negative steps at 540–580 km require common-mode screening. These results support altitude-dependent, σ-normalized maneuver-detection thresholds.

## Declaration of competing interest

The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper. [To be confirmed by all authors.]

## Funding

[To be completed: funding source and grant number, or "This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors."]

## CRediT authorship contribution statement

[Author 1]: Conceptualization, Methodology, Software, Formal analysis, Writing – original draft. [Author 2]: [roles]. [Author 3]: [roles]. [To be completed.]

## Declaration of generative AI and AI-assisted technologies in the writing process

During the preparation of this work the authors used [tool name] to assist with code development, verification of reported numbers against the analysis outputs, and language editing. After using this tool, the authors reviewed and edited the content as needed and take full responsibility for the content of the published article. [To be confirmed or revised by the authors.]

## Acknowledgements

The authors thank the International DORIS Service and the mission operators for the publication of maneuver histories and thrust logs, the 18th Space Defense Squadron for TLE data distributed through Space-Track.org, and SpaceX for the public distribution of Starlink ephemerides.

## Data and code availability

IDS maneuver histories are public [11]. TLE histories were obtained from Space-Track; per the Space-Track user agreement, raw TLEs are not redistributed — the release includes NORAD identifiers, quiescent-arc boundaries and retrieval scripts that reconstruct the data set under the user's own credentials. All numbers in this paper are reproduced by `paperA_numbers.py`, with the noise calibration (`ids_sigma_calibrate.py`), detection validation (`ids_detection_curve.py`) and Δv validation (`ids_dv_vector_validate.py`) scripts and their output tables.

## References

1. F. R. Hoots, R. L. Roehrich, *Models for Propagation of NORAD Element Sets*, Spacetrack Report No. 3, Aerospace Defense Command, U.S. Air Force, 1980.
2. D. A. Vallado, P. Crawford, R. Hujsak, T. S. Kelso, "Revisiting Spacetrack Report #3," AIAA/AAS Astrodynamics Specialist Conference, Keystone, CO, 2006, AIAA 2006-6753.
3. T. Flohrer, H. Krag, H. Klinkrad, "Assessment and categorization of TLE orbit errors for the US SSN catalogue," Advanced Maui Optical and Space Surveillance Technologies (AMOS) Conference, 2008.
4. T. S. Kelso, "Validation of SGP4 and IS-GPS-200D against GPS precision ephemerides," AAS/AIAA Space Flight Mechanics Conference, 2007, AAS 07-127.
5. D. A. Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed., Microcosm Press, 2013.
6. S. Lemmens, H. Krag, "Two-line-elements-based maneuver detection methods for satellites in low Earth orbit," *Journal of Guidance, Control, and Dynamics*, 37(3), 860–868, 2014.
7. R. P. Patera, "Space event detection method," *Journal of Spacecraft and Rockets*, 45(3), 554–559, 2008.
8. T. Kelecy, D. Hall, K. Hamada, D. Stocker, "Satellite maneuver detection using two-line element (TLE) data," Advanced Maui Optical and Space Surveillance Technologies (AMOS) Conference, 2007.
9. [Authors], *Intelligent detection of orbital anomalies and space events for LEO communication satellites: final report*, Taiwan Space Agency contract TASA-S-1150268, 2026.
10. P. Willis et al., "The International DORIS Service (IDS): toward maturity," *Advances in Space Research*, 45(12), 1408–1420, 2010.
11. International DORIS Service, *Satellite maneuver histories*, https://ids-doris.org, accessed 2026.
12. L. Cerri et al., "Precision orbit determination standards for the Jason series of altimeter missions," *Marine Geodesy*, 33(S1), 379–418, 2010.
13. A. Couhert et al., "Towards the 1 mm/y stability of the radial orbit error at regional scales," *Advances in Space Research*, 55(1), 2–23, 2015.
14. [Authors], "An empirical sensitivity model for maneuver detection from public two-line elements: calibration against precise orbit determination truth," submitted to *Advances in Space Research*, 2026.
15. P. J. Rousseeuw, C. Croux, "Alternatives to the median absolute deviation," *Journal of the American Statistical Association*, 88(424), 1273–1283, 1993.
16. SpaceX, *Starlink public ephemeris data*, distributed through Space-Track.org, accessed 2026.
17. J. T. Emmert et al., "NRLMSIS 2.0: a whole-atmosphere empirical model of temperature and neutral species densities," *Earth and Space Science*, 8, e2020EA001321, 2021.
18. J. M. Picone, A. E. Hedin, D. P. Drob, A. C. Aikin, "NRLMSISE-00 empirical model of the atmosphere: statistical comparisons and scientific issues," *Journal of Geophysical Research: Space Physics*, 107(A12), 1468, 2002.
19. K. F. Tapping, "The 10.7 cm solar radio flux (F10.7)," *Space Weather*, 11(7), 394–406, 2013.
20. O. Montenbruck, E. Gill, *Satellite Orbits: Models, Methods and Applications*, Springer, 2000.
