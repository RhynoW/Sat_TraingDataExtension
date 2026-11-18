# Supplementary Material for "An Empirical Sensitivity Model for Maneuver Detection from Public Two-Line Elements: Calibration Against Precise Orbit Determination Truth"

**Target journal:** Advances in Space Research

This supplement provides the tables, definitions and figures referred to in the main text. Section numbers in parentheses (e.g., "main §2.7") point to the main text. Every table states its source file. Files named `fs7_*.json` / `fs7_*.csv` are in `data/benchmark/`; scripts are at the repository root unless a path is given. Quantities that are not stored in the released JSON/CSV products are computed by `docs/fs7_supplement_tables.py`, which reads only the released derived tables and, where trial-level or epoch-level information is required, the TLE history opened read-only and restricted to epochs before 2026-08-25 (this restriction reproduces the 478 quiet windows and the 15,774 injection trials of `fs7_injection_trials.csv` exactly, and the per-condition TP/FP counts of `fs7_injection_metrics.csv` exactly). Its output is `data/benchmark/fs7_supplement_tables.json`.

---

## Contents

- Section S1 — Data products and reproduction map (Table S1)
- Section S2 — Included versus excluded real events (Tables S2–S5; Fig. S4)
- Section S3 — SP3-side consistency checks and event accounting (Tables S6–S8)
- Section S4 — Identification of the drag-ambiguity coefficient (Tables S9–S11; Fig. S1)
- Section S5 — Parameterization sensitivity variants (Tables S12–S14)
- Section S6 — Δa₉₀ under the calibration-only coefficients (Table S15)
- Section S7 — Injection metrics suite: false alarms, delay, precision (Tables S16–S21)
- Section S8 — Probability calibration on the temporal hold-out (Tables S22–S23; Fig. S2)
- Section S9 — Pseudo-event false-positive sample (Tables S24–S27)
- Section S10 — Altitude–inclination domain map (Fig. S3)

---

## Section S1. Data products and reproduction map

**Table S1 — Supplementary items, source files and producing scripts.**

| item | source file | producing script |
|---|---|---|
| included/excluded event comparison (S2) | `fs7_tle_recall_unified_20260825.csv`; `fs7_review3_analysis.json` (`selection_bias`) | `fs7_tle_recall_unified.py`; `fs7_review3_analysis.py`; `docs/fs7_supplement_tables.py` |
| SP3 candidate verdicts (S3) | `fs7_events_2024.csv`, `fs7_events_2025raise.csv`, `fs7_events_campaigns_20260825.csv` | `formosat7_leoorb/detect.py`; `fs7_campaign_truth_build.py` |
| profile likelihood, joint surface, per-band c (S4) | `fs7_law_fit_v4.json`, `fs7_review3_analysis.json`, `fs7_review4_analysis.json`, `fs7_review4b_analysis.json`, `fs7_injection_trials.csv` | `fs7_injection_sweep_v4.py`; `fs7_review3_analysis.py`; `fs7_review4_analysis.py`; `fs7_review4b_analysis.py`; `docs/fs7_supplement_tables.py` |
| parameterization variants (S5) | `fs7_review3_analysis.json` (`parameterization_table`); `fs7_injection_trials.csv` | `fs7_review3_analysis.py`; `docs/fs7_supplement_tables.py` |
| Δa₉₀ two parameterizations (S6) | `fs7_final_supplement.json`; `fs7_review3_analysis.json` (`da90_backcalc`) | `fs7_final_supplement.py`; `fs7_review3_analysis.py` |
| metrics suite (S7) | `fs7_injection_metrics.csv`, `fs7_law_fit_v3.json`, `fs7_law_fit.json` | `fs7_injection_sweep_v3.py`; `fs7_injection_sweep_v2.py`; `docs/fs7_supplement_tables.py` |
| calibration (S8) | `fs7_final_supplement.json`, `fs7_review4_analysis.json`, `fs7_review4b_analysis.json`, `fs7_review3_analysis.json` (`calibration`) | `fs7_final_supplement.py`; `fs7_review4_analysis.py`; `fs7_review4b_analysis.py`; `docs/fs7_supplement_tables.py` |
| pseudo-event sample (S9) | `fs7_review3_analysis.json` (`confusion`), `fs7_review4b_analysis.json` (`pseudo_event_stratified`, `wilson_ci`) | `fs7_review3_analysis.py`; `fs7_review4b_analysis.py`; `docs/fs7_supplement_tables.py` |
| domain map (S10) | `tle_noise_floor_map.csv` | `fs7_noise_floor_map.py`; `fs7_noise_floor_map_v2.py` |

All random draws use `numpy.random.default_rng(42)`. Cluster-bootstrap intervals are percentile intervals with the satellite × window cluster (478 clusters on the full data; 212 clusters on the temporal test split).

---

## Section S2. Included versus excluded real events (main §2.6)

Of the 131 verified maneuver events, 96 have sufficient TLE coverage for the real-event comparison and 35 are excluded. An event is *included* when the TLE history contains at least three TLEs in the pre-event window [t_start − 3 d, t_start − 2 h] and at least one TLE in the post-event window [t_end + 2 h, t_end + 3 d] (`tle_step` in `fs7_tle_recall_unified.py`). Exclusion is therefore a property of TLE availability around the event, not of the event's amplitude.

**Table S2 — Inclusion by amplitude bin** (|SP3 step|). Source: `fs7_tle_recall_unified_20260825.csv` (column `computable`); exclusion rates agree with `fs7_review3_analysis.json` (`selection_bias.exclusion_rate_by_bin`).

| amplitude bin | verified | included | excluded | exclusion rate |
|---|--:|--:|--:|--:|
| 1–50 m | 52 | 37 | 15 | 0.29 |
| 50–100 m | 21 | 16 | 5 | 0.24 |
| 100–300 m | 22 | 18 | 4 | 0.18 |
| 300 m–1 km | 10 | 8 | 2 | 0.20 |
| 1–3 km | 26 | 17 | 9 | 0.35 |
| **total** | **131** | **96** | **35** | **0.27** |

**Table S3 — Inclusion by campaign.** Source: as Table S2 (`selection_bias.exclusion_rate_by_campaign`).

| campaign | role | verified | included | excluded | exclusion rate |
|---|---|--:|--:|--:|--:|
| 2024-07 | test | 29 | 22 | 7 | 0.24 |
| 2024-11/12 | calibration | 41 | 19 | 22 | 0.54 |
| 2025-05 | calibration | 8 | 8 | 0 | 0.00 |
| 2025-07/08 | main truth set | 46 | 43 | 3 | 0.07 |
| 2026-01 | held-out test | 7 | 4 | 3 | 0.43 |

**Table S4 — Inclusion by satellite.** Source: `fs7_tle_recall_unified_20260825.csv`; computed by `docs/fs7_supplement_tables.py` (`S2_selection.sp3_sat`).

| satellite (SP3 / NORAD) | verified | included | excluded | exclusion rate |
|---|--:|--:|--:|--:|
| L76 / 44349 | 23 | 17 | 6 | 0.26 |
| L77 / 44351 | 20 | 13 | 7 | 0.35 |
| L78 / 44343 | 6 | 4 | 2 | 0.33 |
| L79 / 44350 | 17 | 11 | 6 | 0.35 |
| L80 / 44358 | 39 | 38 | 1 | 0.03 |
| L81 / 44353 | 26 | 13 | 13 | 0.50 |

**Table S5 — Distribution summaries and independence tests.** Source: `docs/fs7_supplement_tables.py` (`S2_selection`).

| comparison | included (n = 96) | excluded (n = 35) | test |
|---|---|---|---|
| |Δa| quartiles (Q1 / median / Q3) | 39 / 87 / 353 m | 40 / 69 / 1,042 m | Mann–Whitney U, two-sided p = 0.84 |
| amplitude bin × inclusion | Table S2 | | χ² = 2.09, dof = 4, p = 0.72 |
| campaign × inclusion | Table S3 | | χ² = 28.7, dof = 4, p < 0.001 |
| satellite × inclusion | Table S4 | | χ² = 20.3, dof = 5, p = 0.001 |

Exclusion is strongly associated with campaign and satellite (where TLE availability differs) and not detectably associated with amplitude bin or with the amplitude distribution. The excluded set has a heavier upper tail (Q3 = 1,042 m versus 353 m), and the 1–3 km bin of main Table 4 is the bin most exposed to selection effects (exclusion rate 0.35). The χ² tests are descriptive: several cells have expected counts below 5.

![](fig_fs7_event_selection.png)

**Fig. S4** Distributions of amplitude (log scale, the five amplitude bins of main Table 4), campaign and satellite for the 96 included versus the 35 excluded verified events. Included and excluded amplitude distributions are similar (Mann–Whitney p = 0.84; χ² over bins p = 0.72), whereas exclusion rates differ markedly by campaign (0.00–0.54) and by satellite (0.03–0.50). Data: `fs7_tle_recall_unified_20260825.csv`.

---

## Section S3. SP3-side consistency checks and event accounting (main §2.7)

### S3.1 Candidate generation

For each satellite, instantaneous semi-major axis is computed from SP3 positions and inertial velocities (v_ECI = v_ECEF + ω_E × r), averaged across overlapping arcs at each epoch, and resampled to a uniform 60 s grid. The series is smoothed with a centred rolling mean of one orbital period and differenced at a lag of one orbital period, both computed per series from the median semi-major axis. A candidate is a contiguous run of samples with |difference| > max(4 × 1.4826 × MAD, 2 m) (`formosat7_leoorb/detect.py`, `detect_events`). Its start, end and peak epochs are t_start, t_end and the epoch of maximum |difference|.

### S3.2 The four consistency checks

**Table S6 — Definitions, thresholds and failure modes of the four checks.** Source: `formosat7_leoorb/detect.py` (`detect_events`, `add_common_mode`, `verify`; constants `STEP_WIN_H = 6`, `STEP_GAP_H = 1`, `PERSIST_MIN = 0.5`, `SPREAD_MAX_M = 50`, `CONCURRENT_MAX = 3`).

| check | quantity | rejection rule | what it rejects | failure modes |
|---|---|---|---|---|
| (a) persistence of the mean-level step | step = mean smoothed a over [t_end + 1 h, t_end + 7 h] minus mean over [t_start − 7 h, t_start − 1 h] (each window > 10 samples); persist ratio = |step| / |peak difference| | reject if persist ratio < 0.5 or undefined | transient excursions that return to the prior level (residual harmonics, processing glitches, short arcs) | drag-driven decay produces a persistent step and passes (main §5.1); two burns closer than ≈ 7 h contaminate each other's windows; a candidate within 7 h of a data gap is rejected because its ratio is undefined |
| (b) agreement among overlapping arcs | median over the candidate interval of the per-epoch spread (max − min) of a across overlapping independent arcs | reject if spread > 50 m | candidates seen in one arc solution and not in the overlapping ones | vacuous when only one arc covers the interval (spread = 0); the arcs share the same processing chain, so common processing artefacts agree across arcs |
| (c) common mode across satellites | number of distinct satellites with a candidate peak within ±3 h of this candidate's peak (itself included) | reject if ≥ 3 satellites | constellation-wide signatures (space weather, product or processing changes) | rejects genuinely coordinated maneuvers performed by three or more satellites within ±3 h, which is common during orbit-raising campaigns; does not reject a storm signature that reaches fewer than three satellites within ±3 h |
| (d) inclination channel | Δi = mean inclination over the post window minus mean over the pre window (windows of check a) | none (corroboration only) | — | in-plane raises leave Δi ≈ 0, so absence of a Δi signal carries no information for the dominant event type |

A candidate is *verified* when it passes (a), (b) and (c); (d) is recorded for every candidate as corroboration for out-of-plane burns and does not enter the verdict. The checks share one SP3 source and are consistency criteria, not independent evidence.

**Table S7 — Rejection power of each check, by candidate set.** "fails" counts candidates failing the check (marginal); "sole" counts candidates for which it is the only failing check. "single-arc" counts candidates whose interval is covered by one arc (check b vacuous). "common-only ≥ 1 km" counts candidates rejected solely by check (c) with |step| ≥ 1 km. Source: the three event CSVs (columns `verdict`, `reason`, `n_arcs_med`, `step_m`); computed by `docs/fs7_supplement_tables.py` (`S3_sp3_checks`).

| set | candidates | verified | (a) fails / sole | (b) fails / sole | (c) fails / sole | ≥ 2 fail | single-arc | common-only ≥ 1 km |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 storm interval | 87 | 21 | 16 / 6 | 0 / 0 | 60 / 50 | 10 | 49 | 0 |
| 2024-07 | 158 | 29 | 48 / 37 | 0 / 0 | 92 / 81 | 11 | 112 | 45 |
| 2024-11/12 | 247 | 41 | 108 / 96 | 0 / 0 | 110 / 98 | 12 | 69 | 50 |
| 2025-05 | 125 | 8 | 76 / 76 | 0 / 0 | 41 / 41 | 0 | 40 | 36 |
| 2025-07/08 | 332 | 46 | 231 / 210 | 0 / 0 | 76 / 55 | 21 | 132 | 41 |
| 2026-01 | 94 | 7 | 64 / 57 | 0 / 0 | 30 / 23 | 7 | 27 | 20 |
| **all six sets** | **1,043** | **152** | **543 / 482** | **0 / 0** | **409 / 348** | **61** | **429** | **192** |

Over all 1,043 candidates, persistence (a) rejects 52% (46% as the only failing check) and the common-mode check (c) rejects 39% (33% alone); the arc-agreement check (b) rejects no candidate in any set — 41% of candidates are single-arc, and in the remainder the overlapping arcs agree to within 50 m. The 192 candidates with |step| ≥ 1 km rejected solely by (c) fall in the orbit-raising campaigns, where several satellites burn within ±3 h of one another; they illustrate the failure mode of check (c) listed in Table S6 and are not part of the 131 verified events. The inclination channel (d) shows |Δi| with median 0.001° and 95th percentile 0.003° among verified events, consistent with predominantly in-plane burns. The verified totals (21 storm signatures; 29, 41, 8, 46, 7 maneuvers) reproduce main Table 1a.

### S3.3 Event accounting definitions

- **Merging of flags within one window.** Injection side: an injection is a hit when at least one detector flag falls within ±2 samples of the injected step; any number of flags within the tolerance counts as one hit. Real-event side: the TLE detector makes one decision per verified event, from the median residual of the first one or two TLEs in the post-event window against a linear trend fitted to the pre-event window; flags therefore cannot be counted more than once per event.
- **One maneuver detected repeatedly is counted once.** Injection side: TP is counted per injection (hit or not), never per flag. For the event-level metrics of Section S7, flags whose indices differ by ≤ 2 samples are merged into one detection event, and at most one event per injection is counted as a TP.
- **Detection delay.** The reference epoch is the first TLE epoch at or after the injected step epoch (injections) or the first TLE epoch after the truth-interval end t_end (real events). Injection delay is the time from the reference epoch to the first flag at or after the injected step; delay = 0 means the step is flagged at the first post-event TLE. For real events the detector uses the first TLE at or after t_end + 2 h; its time after t_end is summarised in Table S8.
- **Closely spaced maneuvers.** SP3 candidates are contiguous super-threshold runs; two runs separated by at least one sub-threshold sample are distinct candidates and, if both pass the checks, distinct verified events. Each verified event is evaluated against TLEs independently. When two verified events on the same satellite fall within one TLE update interval, they share the same post-event TLE and therefore the same TLE-side decision (pile-up, factor 5 of main §5.5). No merging of verified events is applied. Table S8 gives the frequency of such pairs.

**Table S8 — Separation of consecutive verified events and real-event delay to the first post-event TLE.** Source: `fs7_tle_recall_unified_20260825.csv`, event CSVs (`t_end`) and the TLE epoch history (< 2026-08-25); computed by `docs/fs7_supplement_tables.py` (`S9_pseudo.closely_spaced`, `S9_pseudo.real_event_first_post_tle_delay`).

| quantity | value |
|---|---|
| consecutive same-satellite pairs among the 131 verified events | 125 |
| pairs separated by < 1 h / < 6 h / < 1 d / < 3 d | 40 / 52 / 67 / 86 |
| delay from t_end to the first TLE used (≥ t_end + 2 h), 96 included events: median [IQR] | 0.54 d [0.34, 0.85] |
| by campaign: 2024-07 / 2024-11/12 / 2025-05 / 2025-07/08 / 2026-01 (median) | 0.75 / 0.41 / 0.45 / 0.53 / 0.35 d |

---

## Section S4. Identification of the drag-ambiguity coefficient (main §3.3)

**Table S9 — Profile likelihood of c** (full data, 15,774 trials; SNR₅₀ and β profiled at each c on the grid `logspace(−1.3, 1.0, 47)`). Relative log-likelihood ℓₚ(c) − ℓ(ĉ); the 95% set is ℓ(ĉ) − ℓₚ(c) ≤ 1.9208. Source: `fs7_injection_trials.csv`, computed by `docs/fs7_supplement_tables.py` (`S4_profile`); ĉ, CI and log-likelihoods agree with `fs7_law_fit_v4.json` (`c_drag`) and `fs7_review3_analysis.json`.

| c (grid) | relative log-likelihood | SNR₅₀ | β (log₁₀ axis) | inside 95% set |
|--:|--:|--:|--:|:-:|
| 0.100 | −96.90 | 7.31 | 5.04 | no |
| 0.200 | −12.24 | 5.25 | 5.23 | no |
| 0.251 | −2.55 | 4.49 | 5.25 | no |
| 0.282 | −0.56 | 4.12 | 5.25 | yes |
| 0.316 (ĉ) | 0.00 | 3.77 | 5.25 | yes |
| 0.398 | −1.76 | 3.11 | 5.25 | yes |
| 0.501 | −5.40 | 2.54 | 5.24 | no |
| 0.708 | −11.17 | 1.84 | 5.22 | no |
| 1.000 | −15.60 | 1.32 | 5.21 | no |
| 1.995 | −20.19 | 0.67 | 5.20 | no |

ĉ = 0.32, profile 95% CI [0.28, 0.40]; mean per-trial log-likelihood −0.1833 at ĉ and −0.1843 at c = 1 (`fs7_law_fit_v4.json`), so c = 1 lies outside the 95% set. β is essentially constant (5.20–5.25) for c ≥ 0.2 while SNR₅₀ moves inversely with c — the scale trade-off quantified in Table S10.

**Table S10 — Joint-identification diagnostic and its convergence.** Pearson correlation of (log ĉ, log SNR̂₅₀) across full-data cluster-bootstrap replicates, c re-estimated on a 24-point log grid within each replicate. Source: `fs7_review4b_analysis.json` (`corr_convergence`); main-text value from `fs7_review3_analysis.json`.

| replicates | corr(log c, log SNR₅₀) |
|--:|--:|
| B = 200 | −0.978 |
| B = 500 | −0.979 |
| main text (B = 200, rounded) | −0.98 |

**Table S11 — Per-drag-regime estimates of c** (profile 95% CI). Source: `fs7_review4_analysis.json` (`per_band_c`).

| drag tercile | ĉ | profile 95% CI |
|---|--:|---|
| low | 0.28 | [0.20, 0.40] |
| mid | 0.32 | [0.25, 0.50] |
| high | 0.32 | [0.25, 0.50] |

**Joint surface.** With β profiled at each grid node on a 26 × 26 log grid (c ∈ [0.126, 2.51], SNR₅₀ ∈ [0.63, 10]), the maximum lies at the grid node (c, SNR₅₀) = (0.33, 3.70) (`fs7_review4_analysis.json`, `joint_likelihood.ll_max_at`), adjacent to the profile estimate (0.32, 3.77). The 95% region (relative log-likelihood ≥ −1.92) occupies three grid nodes spanning c 0.29–0.37 and SNR₅₀ 3.31–4.13 (`docs/fs7_supplement_tables.py`, `S4_profile.joint_95_region_grid_extent`); its orientation along a descending ridge is the geometric counterpart of the −0.98 correlation.

![](fig_fs7_profile_likelihood.png)

![](fig_fs7_joint_likelihood.png)

**Fig. S1** Identification of the drag-ambiguity coefficient on the full data (15,774 injection trials). (a) Profile likelihood of c_drag (SNR₅₀ and β profiled); dashed line, the 95% threshold ℓ(ĉ) − 1.92; vertical markers at ĉ = 0.32, the calibration-split estimate c = 0.28 and c = 1. The 95% profile set is [0.28, 0.40]. (b) Joint relative log-likelihood of (c, SNR₅₀) with β profiled at each node; red contour, 95% region; the descending ridge visualizes the corr(log c, log SNR₅₀) = −0.98 scale trade-off of Table S10. Data: `fs7_injection_trials.csv`; scripts: `fs7_review3_analysis.py`, `fs7_review4_analysis.py`.

---

## Section S5. Parameterization sensitivity variants (main §4.3)

Each variant is fitted on the calibration split (windows starting before 2025-07-01; 8,778 trials) with c held at the stated value, and evaluated unchanged on the temporal test split (6,996 trials).

**Table S12 — Sensitivity variants on the temporal hold-out.** Source: `fs7_review3_analysis.json` (`parameterization_table`: SNR₅₀, β, SNR₉₀, held-out log loss); Brier and AUC from `docs/fs7_supplement_tables.py` (`S5_variants`), which reproduces the JSON SNR₅₀, β, SNR₉₀ and log loss exactly.

| variant | c | SNR₅₀ | β | SNR₉₀ | held-out log loss | held-out Brier | held-out AUC | role |
|---|--:|--:|--:|--:|--:|--:|--:|---|
| main protocol (c estimated on calibration split) | 0.28 | 3.87 | 5.04 | 10.57 | 0.1237 | 0.0393 | 0.9773 | main hold-out result |
| c fixed at 1 (historical parameterization) | 1 | 1.23 | 5.00 | 3.39 | 0.1241 | 0.0394 | 0.9775 | sensitivity reference |
| c fixed at the full-data value | 0.32 | 3.50 | 5.04 | 9.55 | 0.1236 | 0.0392 | 0.9774 | excluded from main table (uses full-data information) |
| amplitude-only (Δa/σ) | — | 8.74 | 4.38 | 27.72 | 0.1413 | 0.0446 | 0.9671 | structural comparison |

The c = 0.32 variant's SNR₅₀ (3.50) differs from the full-data descriptive refit (3.77) because it is fitted on the calibration split only.

**Table S13 — SNR_eff(c) and predicted probability on common events.** All three drag-aware variants are evaluated on the same 6,996 test-split trials. "SNR ratio" is the median per-trial ratio SNR_eff(c_a)/SNR_eff(c_b); "SNR₅₀ ratio" is the ratio of the fitted scales. Source: `docs/fs7_supplement_tables.py` (`S5_variants.pairs`).

| comparison | median SNR ratio | SNR₅₀ ratio | mean |Δp| | 99th pct |Δp| | max |Δp| | Pearson r (p_a, p_b) |
|---|--:|--:|--:|--:|--:|--:|
| c = 1 vs c = 0.28 | 0.320 | 0.318 | 0.0072 | 0.098 | 0.232 | 0.995 |
| c = 0.32 vs c = 0.28 | 0.906 | 0.904 | 0.0014 | 0.017 | 0.034 | 0.9998 |
| c = 1 vs c = 0.32 | 0.353 | 0.351 | 0.0058 | 0.079 | 0.200 | 0.997 |

Changing c rescales SNR_eff by almost exactly the factor by which the fitted SNR₅₀ moves, so the argument log₁₀(SNR_eff/SNR₅₀) of the logistic link — and therefore the predicted probability — is nearly unchanged.

**Table S14 — Common-event comparison by condition** (test split; median SNR_eff and mean predicted probability for each variant, observed hit rate). The test split contains no windows in the high-drag tercile (terciles defined on the full data). Source: `docs/fs7_supplement_tables.py` (`S5_variants.by_condition`).

| condition | n | observed rate | median SNR_eff: c = 1 / 0.32 / 0.28 | mean P: c = 1 / 0.32 / 0.28 |
|---|--:|--:|---|---|
| 1×·low | 1,507 | 0.964 | 55.1 / 146.4 / 159.9 | 0.985 / 0.984 / 0.984 |
| 1×·mid | 825 | 0.897 | 25.6 / 69.1 / 76.2 | 0.956 / 0.953 / 0.952 |
| 2×·low | 1,507 | 0.939 | 22.9 / 61.7 / 67.4 | 0.946 / 0.944 / 0.944 |
| 2×·mid | 825 | 0.869 | 10.6 / 30.2 / 33.1 | 0.881 / 0.879 / 0.878 |
| 4×·low | 1,507 | 0.883 | 11.4 / 32.6 / 36.1 | 0.886 / 0.885 / 0.885 |
| 4×·mid | 825 | 0.782 | 5.4 / 15.5 / 17.2 | 0.792 / 0.793 / 0.793 |

---

## Section S6. Δa₉₀ under the calibration-only coefficients (main §4.4)

Δa₉₀ = SNR₉₀ · sqrt(σ_TLE² + (c·|ȧ|·Δt)²) at each condition's median (σ, |ȧ|, Δt) from `fs7_injection_sweep.csv`.

**Table S15 — Model-implied Δa₉₀ under the descriptive and the calibration-only coefficients.** "Main text" is the column of main §4.4 (full-data refit coefficients at unrounded values; `fs7_review3_analysis.json`, `da90_backcalc`). "Descriptive" and "calibration-only" are evaluated with the rounded coefficient pairs (SNR₉₀ = 9.87, c = 0.32) and (SNR₉₀ = 10.57, c = 0.28); "rel. diff." is (calibration-only − descriptive)/descriptive. Source: `fs7_final_supplement.json` (`da90_two_parameterizations`).

| condition | σ_TLE (m) | \|ȧ\| (m/d) | Δt (d) | main text | descriptive (9.87, 0.32) | calibration-only (10.57, 0.28) | rel. diff. | observed 90% floor |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1×·low | 1.1 | 18.5 | 0.33 | 22 m | 22 m | 22 m | −2.9% | 50 m |
| 1×·mid | 2.6 | 46.9 | 0.40 | 64 m | 64 m | 62 m | −4.0% | 100 m |
| 1×·high | 5.5 | 76.8 | 0.53 | 138 m | 139 m | 134 m | −4.1% | 200 m |
| 2×·low | 2.2 | 18.5 | 0.87 | 55 m | 55 m | 53 m | −4.1% | 50 m |
| 2×·mid | 5.4 | 46.4 | 0.99 | 153 m | 155 m | 148 m | −4.6% | 100 m |
| 2×·high | 10.7 | 74.6 | 0.99 | 254 m | 256 m | 246 m | −3.9% | 300 m |
| 4×·low | 3.6 | 18.5 | 1.72 | 106 m | 107 m | 102 m | −4.7% | 100 m |
| 4×·mid | 8.7 | 46.4 | 1.80 | 274 m | 277 m | 264 m | −4.9% | 200 m |
| 4×·high | 20.8 | 76.2 | 1.98 | 515 m | 520 m | 499 m | −4.1% | 500 m |

The largest relative difference between parameterizations is 4.9% (`max_rel_diff_pct`); relative to the main-text column the calibration-only values are 0–4% lower. The condition medians σ, |ȧ|, Δt are those of `fs7_review3_analysis.json`.

---

## Section S7. Injection metrics suite: false alarms, delay, precision (main §4.5)

All quantities in this section come from the trial-level replica of `fs7_injection_sweep_v3.py` in `docs/fs7_supplement_tables.py` (`S7_metrics`), which reproduces the per-condition TP and FP counts of `fs7_injection_metrics.csv` for all 99 (amplitude × cadence × drag) cells. Control windows are the same windows without injection (478 windows × 3 cadences = 1,434 control series).

### S7.1 False-alarm rate

*Flag level*: number of detector flags in a non-injected control window divided by the window span, × 30 d (flags per satellite per 30 days). *Event level*: flags ≤ 2 samples apart are merged into one detection event, and the rate is events per satellite per 30 days (per satellite-month).

**Table S16 — False-alarm rate in control windows, stratified by cadence, drag tercile and satellite.** Source: `docs/fs7_supplement_tables.py` (`S7_metrics.far_*`); the cadence × drag medians agree with `far_per30d_med` of `fs7_injection_metrics.csv`.

| stratum | windows | flag level: median [IQR] | flag level: mean | event level: median | event level: mean | windows with no flag |
|---|--:|---|--:|--:|--:|--:|
| **pooled** | 1,434 | 1.40 [0.00, 2.90] | 1.83 | 1.37 | 1.45 | 0.45 |
| 1× | 478 | 1.46 [0.00, 3.25] | 2.37 | 1.40 | 1.84 | 0.41 |
| 2× | 478 | 1.57 [0.00, 3.11] | 1.92 | 1.53 | 1.54 | 0.37 |
| 4× | 478 | 0.00 [0.00, 1.98] | 1.19 | 0.00 | 0.98 | 0.55 |
| low drag | 478 | 1.45 [0.00, 2.91] | 1.94 | 1.40 | 1.61 | 0.45 |
| mid drag | 479 | 1.59 [0.00, 3.11] | 1.98 | 1.53 | 1.52 | 0.41 |
| high drag | 477 | 1.25 [0.00, 2.56] | 1.57 | 1.23 | 1.23 | 0.48 |
| L76 (44349) | 234 | 1.44 [0.00, 3.15] | 1.80 | 1.40 | 1.45 | 0.43 |
| L77 (44351) | 282 | 1.65 [0.00, 2.90] | 2.04 | 1.61 | 1.64 | 0.43 |
| L78 (44343) | 246 | 1.37 [0.00, 2.88] | 1.73 | 1.34 | 1.36 | 0.44 |
| L79 (44350) | 231 | 1.08 [0.00, 2.95] | 1.64 | 1.08 | 1.27 | 0.50 |
| L80 (44358) | 222 | 1.56 [0.00, 2.89] | 2.10 | 1.45 | 1.64 | 0.40 |
| L81 (44353) | 219 | 1.32 [0.00, 2.56] | 1.62 | 1.30 | 1.31 | 0.48 |

**Table S17 — False-alarm rate by cadence × drag condition** (median flags / event per satellite per 30 days). Source: as Table S16 (`far_by_cadence_drag`).

| cadence \ drag | low: flag / event | mid: flag / event | high: flag / event |
|---|---|---|---|
| 1× | 1.82 / 1.70 | 1.53 / 1.45 | 0.59 / 0.59 |
| 2× | 1.46 / 1.41 | 1.71 / 1.62 | 1.51 / 1.49 |
| 4× | 0.00 / 0.00 | 1.39 / 1.35 | 0.00 / 0.00 |

The pooled window-level median is 1.40 flags per satellite per 30 days; the median of the nine condition medians is 1.46. Merging adjacent flags changes the median little (1.37 events per satellite-month) but lowers the mean (1.83 → 1.45), because multi-flag bursts occur in a minority of windows. No satellite departs markedly from the pooled distribution (medians 1.08–1.65).

### S7.2 Detection delay

**Table S18 — Detection delay per cadence, Δa ≥ 50 m** (10 amplitudes × all windows per cadence). Delay is measured from the first TLE at or after the injected step to the first flag at or after it. "First-TLE fraction" is the fraction of trials flagged exactly at the first post-step TLE. Source: `docs/fs7_supplement_tables.py` (`S7_metrics.delay_da_ge_50m`).

| cadence | trials | with a post-step flag | delay median [IQR] (d) | 90th pct (d) | first-TLE fraction (all trials) | first-TLE fraction (flagged trials) |
|---|--:|--:|---|--:|--:|--:|
| 1× | 4,780 | 0.953 | 0.00 [0.00, 0.00] | 0.00 | 0.933 | 0.979 |
| 2× | 4,780 | 0.938 | 0.00 [0.00, 0.00] | 0.00 | 0.908 | 0.968 |
| 4× | 4,780 | 0.810 | 0.00 [0.00, 0.00] | 0.00 | 0.792 | 0.977 |

**Table S19 — First-TLE fraction by cadence and amplitude.** Source: as Table S18 (`delay_by_cadence_amp`).

| Δa | 20 m | 50 m | 100 m | 150 m | 200 m | 300 m | 500 m | ≥ 750 m |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1× | 0.17 | 0.53 | 0.84 | 0.97 | 1.00 | 1.00 | 1.00 | 1.00 |
| 2× | 0.13 | 0.44 | 0.77 | 0.90 | 0.97 | 1.00 | 1.00 | 1.00 |
| 4× | 0.05 | 0.20 | 0.47 | 0.63 | 0.75 | 0.89 | 0.98 | 1.00 |

Among trials with a post-step flag, the first such flag falls at the first post-step TLE in 96.8–97.9% of cases at every cadence; the cadence dependence of Table S18 enters through the fraction of trials with any post-step flag. At 20 m the median delay of flagged trials is 2.1 d (1×), 4.0 d (2×) and 5.3 d (4×): these late flags are dominated by background flags rather than by the injected step (main §4.5, plateau analysis).

### S7.3 Precision: two definitions

- **Flag-level precision (main-text definition).** TP = number of injections with at least one flag within ±2 samples (one per hit injection); FP = number of individual flags earlier than the injected step by more than 2 samples. Precision = TP / (TP + FP). This is the `precision` column of `fs7_injection_metrics.csv`.
- **Flag-level precision, all flags.** TP = number of individual flags within ±2 samples; FP as above.
- **Event-level precision.** Flags ≤ 2 samples apart are merged into events; TP = injections having an event that contains a flag within ±2 samples (at most one per injection); FP = events lying entirely more than 2 samples before the injected step.

**Table S20 — Precision under the three definitions, detectable range (Δa ≥ 200 m).** Source: `docs/fs7_supplement_tables.py` (`S7_metrics.precision_*`).

| stratum | trials | flag level (main text) | flag level (all flags) | event level |
|---|--:|--:|--:|--:|
| 1×·low | 1,113 | 0.573 | 0.607 | 0.625 |
| 1×·mid | 1,127 | 0.619 | 0.642 | 0.693 |
| 1×·high | 1,106 | 0.715 | 0.735 | 0.794 |
| 2×·low | 1,113 | 0.742 | 0.766 | 0.781 |
| 2×·mid | 1,106 | 0.679 | 0.706 | 0.733 |
| 2×·high | 1,127 | 0.695 | 0.725 | 0.749 |
| 4×·low | 1,120 | 0.905 | 0.913 | 0.911 |
| 4×·mid | 1,120 | 0.830 | 0.843 | 0.863 |
| 4×·high | 1,106 | 0.828 | 0.841 | 0.856 |
| 1× pooled | 3,346 | 0.630 | 0.656 | 0.697 |
| 2× pooled | 3,346 | 0.705 | 0.731 | 0.754 |
| 4× pooled | 3,346 | 0.854 | 0.866 | 0.877 |
| all | 10,038 | 0.716 | 0.739 | 0.767 |

The range 0.60–0.64 quoted in main §4.5 is the flag-level precision of the 1×·mid condition for Δa = 100 m–2 km (`fs7_injection_metrics.csv`, 0.596–0.639). Across all conditions with Δa ≥ 200 m the flag-level precision spans 0.56–0.92; precision rises with coarser cadence, consistent with fewer background flags in the shorter decimated series. Event-level precision exceeds the main-text flag-level precision by up to 0.08.

**Fragmentation.** The fraction of injections with more than one attributable flag (flags within [step − 2, step + 5] samples), weighted by trial count from `fs7_injection_metrics.csv` (`frag_rate`), is 0.146 / 0.195 / 0.122 at 1× / 2× / 4× over all amplitudes and 0.160 / 0.218 / 0.141 for Δa ≥ 200 m. The 13–17% of main §4.5 is the range for the 1×·mid condition at Δa = 100 m–2 km (0.130–0.168).

### S7.4 Residual serial correlation

**Table S21 — Lag-1 autocorrelation of detrended single-step TLE differences** (median over 478 windows). Source: `fs7_law_fit.json` (`autocorr`).

| cadence | median lag-1 autocorrelation |
|---|--:|
| 1× | 0.238 |
| 2× | 0.463 |
| 4× | 0.490 |

The lag-1 autocorrelation is positive at all cadences, so the /√2 factor, which assumes independent errors, does not hold exactly; σ_TLE is therefore treated as an effective residual scale (main §3.3, limitation vi).

---

## Section S8. Probability calibration on the temporal hold-out (main §4.6)

Calibration slope b and intercept a are the coefficients of the logistic recalibration y ~ sigmoid(a + b·logit p) fitted on the test split (6,996 trials; 212 satellite × window clusters); b = 1 and a = 0 indicate perfect calibration in the large. CIs are cluster-bootstrap percentile intervals, B = 2,000.

**Table S22 — Calibration slope and intercept with 95% CIs.** Sources: raw drag-aware model, `fs7_final_supplement.json` (`calibration_slope`); amplitude-only model, `fs7_review4b_analysis.json` (`amp_calibration`); Platt-recalibrated drag-aware model, `docs/fs7_supplement_tables.py` (`S8_calibration.recalibrated`); log loss / Brier / AUC from `fs7_law_fit_v4.json` and `fs7_review4_analysis.json`.

| model | log loss | Brier | AUC | slope [95% CI] | intercept [95% CI] |
|---|--:|--:|--:|---|---|
| drag-aware, raw (c = 0.28, SNR₅₀ = 3.87, β = 5.04) | 0.1237 | 0.0393 | 0.9773 | 1.22 [1.12, 1.35] | −0.63 [−0.89, −0.39] |
| drag-aware, Platt-recalibrated | 0.1238 | 0.0393 | 0.9773 | 1.22 [1.12, 1.35] | −0.62 [−0.88, −0.37] |
| amplitude-only, raw (SNR₅₀ = 8.74, β = 4.38) | 0.1413 | 0.0446 | 0.9671 | 1.15 [1.06, 1.26] | −0.26 [−0.52, −0.02] |

The Platt map, fitted on calibration-period out-of-fold predictions, is a ≈ 0.00, b ≈ 1.00 (b = 0.998): the calibration-period predictions are already calibrated in-sample, so recalibration leaves the test-period probabilities, the slope and the loss essentially unchanged. The slope CI of the raw model excludes 1 (`slope_ci_contains_1 = false`). The recalibrated row is computed with the unrounded calibration estimate c = 0.2818; evaluated the same way, the raw model gives intercept −0.62 [−0.87, −0.38], identical in slope.

**Table S23 — Reliability-diagram data (deciles of predicted probability, test split).** Raw bins: `fs7_review3_analysis.json` (`calibration.bins`), reproduced by `docs/fs7_supplement_tables.py`; recalibrated bins: `docs/fs7_supplement_tables.py` (`S8_calibration.recalibrated.bins`).

| decile | n | raw: mean predicted | raw: observed rate | recalibrated: mean predicted | recalibrated: observed rate |
|--:|--:|--:|--:|--:|--:|
| 1 | 700 | 0.375 | 0.253 | 0.376 | 0.253 |
| 2 | 700 | 0.840 | 0.784 | 0.840 | 0.784 |
| 3 | 699 | 0.957 | 0.971 | 0.957 | 0.971 |
| 4 | 700 | 0.986 | 0.999 | 0.986 | 0.999 |
| 5 | 699 | 0.995 | 1.000 | 0.995 | 1.000 |
| 6 | 700 | 0.998 | 1.000 | 0.998 | 1.000 |
| 7 | 699 | 0.999 | 1.000 | 0.999 | 1.000 |
| 8 | 700 | 1.000 | 1.000 | 1.000 | 1.000 |
| 9 | 699 | 1.000 | 1.000 | 1.000 | 1.000 |
| 10 | 700 | 1.000 | 1.000 | 1.000 | 1.000 |

The slope > 1 reflects over-prediction in the lowest two deciles (0.375 predicted versus 0.253 observed; 0.840 versus 0.784) and slight under-prediction in deciles 3–4: the raw probabilities are too moderate, i.e., the true detection curve is steeper than the fitted one. Deciles 5–10 (60% of test trials) have mean predicted probability ≥ 0.995, so the decile layout concentrates resolution at high probabilities.

![](fig_fs7_reliability.png)

**Fig. S2** Reliability diagrams on the temporal hold-out (test split, 6,996 trials; predicted-probability deciles), raw versus Platt-recalibrated SNR_eff model with c = 0.28 fixed from the calibration split. Dashed line, perfect calibration. Raw: slope 1.22 [1.12, 1.35], intercept −0.63 [−0.89, −0.39]; recalibrated: slope 1.22 [1.12, 1.35], intercept −0.62 [−0.88, −0.37]. The two curves coincide because the Platt map fitted on calibration-period out-of-fold predictions is close to the identity (b = 0.998). Data: Table S23.

---

## Section S9. Pseudo-event false-positive sample (main §5.4)

### S9.1 Protocol and draws

Pseudo-events are random TLE epochs, up to 200 per satellite, drawn without replacement from the full 2024–2026 history (excluding the first and last 3 d), rejected if within 2 d of the t_start of any of the 131 verified events, and evaluated with the identical pre/post trend estimator, windows and thresholds as the real events (`tle_step`). A pseudo-event is *evaluable* when the estimator's coverage conditions hold (≥ 3 TLEs pre, ≥ 1 TLE post). FP = evaluable pseudo-event with |residual| above the threshold (no sign condition, since a pseudo-event has no SP3 step sign); FPR = FP / (FP + TN), pooled across satellites. Three draws under this protocol are reported:

- **Draw A** (n = 1,131 evaluable): the tabulated draw of main §5.4 (`fs7_review3_analysis.json`, `confusion`).
- **Draw B** (n = 1,142): per-satellite stratification and storm sensitivity (`fs7_review4b_analysis.json`, `pseudo_event_stratified`).
- **Draw C** (n = 1,145): per-period stratification and cadence match, TLE history restricted to epochs before 2026-08-25 (`docs/fs7_supplement_tables.py`, `S9_pseudo`).

**Storm interval.** The 21 storm-interval signatures are not verified events, so the 2-day exclusion rule does not remove pseudo-events from the May 2024 storm interval (2024-05-08 to 2024-05-20); pseudo-events falling there are retained in the pooled FPR and removed in the storm-excluded sensitivity rows. Likewise, SP3 candidates rejected by the consistency checks (Table S7) are not excluded from the sampling frame.

### S9.2 Separately computed CIs for the two samples

**Table S24 — Real-event recall and pseudo-event FPR with Wilson 95% CIs, computed separately for each sample.** Source: `fs7_review3_analysis.json` (`confusion`); `fs7_review4b_analysis.json` (`wilson_ci`).

| threshold | real events (n = 96): TP / FN | recall [Wilson 95% CI] | pseudo-events (draw A, n = 1,131): FP / TN | FPR [Wilson 95% CI] | precision vs pseudo-events |
|---|---|---|---|---|--:|
| 45 m | 37 / 59 | 0.385 [0.294, 0.485] | 64 / 1,067 | 0.057 [0.045, 0.072] | 0.366 |
| unified 3σ (3.9–6.2 m) | 45 / 51 | 0.469 [0.372, 0.568] | 617 / 514 | 0.546 [0.516, 0.574] | 0.068 |

"Precision vs pseudo-events" combines counts from two differently sized samples and is shown only for completeness; it is not a population precision.

### S9.3 Per-satellite stratification and storm sensitivity

**Table S25 — Per-satellite evaluable pseudo-events and FPR (draw B).** Source: `fs7_review4b_analysis.json` (`pseudo_event_stratified`).

| satellite | evaluable | FPR @ 45 m | FPR @ unified 3σ |
|---|--:|--:|--:|
| L76 | 191 | 0.052 | 0.476 |
| L77 | 191 | 0.058 | 0.571 |
| L78 | 196 | 0.041 | 0.607 |
| L79 | 187 | 0.048 | 0.583 |
| L80 | 187 | 0.048 | 0.561 |
| L81 | 190 | 0.063 | 0.516 |
| **pooled** (n = 1,142) | | **0.052** | **0.553** |
| satellite-weighted (mean of six) | | 0.052 | 0.552 |
| storm interval excluded (n = 1,124) | | 0.048 | 0.547 |

The satellite-weighted and pooled FPR agree to three decimals at 45 m and differ by 0.001 at the unified 3σ threshold; excluding the 18 storm-interval pseudo-events changes the FPR by −0.004 (45 m) and −0.006 (3σ). Draw C gives the same picture: pooled 0.052 / 0.548, satellite-weighted 0.052 / 0.547, storm-excluded (n = 1,127) 0.049 / 0.543, per-satellite FPR @ 45 m 0.040–0.062 (`S9_pseudo`).

### S9.4 Per-period stratification

**Table S26 — FPR by half-year (draw C).** Source: `docs/fs7_supplement_tables.py` (`S9_pseudo.per_period`). 2026-H2 covers 2026-07-01 to 2026-08-24.

| period | evaluable | FPR @ 45 m [Wilson 95% CI] | FPR @ unified 3σ [Wilson 95% CI] |
|---|--:|---|---|
| 2024-H1 | 209 | 0.067 [0.040, 0.109] | 0.703 [0.638, 0.761] |
| 2024-H2 | 177 | 0.141 [0.098, 0.200] | 0.774 [0.707, 0.829] |
| 2025-H1 | 199 | 0.030 [0.014, 0.064] | 0.653 [0.585, 0.716] |
| 2025-H2 | 232 | 0.056 [0.033, 0.093] | 0.487 [0.423, 0.551] |
| 2026-H1 | 246 | 0.004 [0.001, 0.023] | 0.341 [0.285, 0.403] |
| 2026-H2 | 82 | 0.000 [0.000, 0.045] | 0.207 [0.134, 0.307] |
| **pooled** | 1,145 | 0.052 [0.040, 0.066] | 0.548 [0.520, 0.577] |

Unlike the satellite stratification, the period stratification is heterogeneous: the 45 m FPR ranges from 0.000 to 0.141 and the 3σ FPR falls from 0.65–0.77 in 2024–2025-H1 to 0.21–0.34 in 2026. The highest 45 m FPR (2024-H2) coincides with the 2024-11/12 orbit-raising campaign, whose 50 large candidates rejected only by the common-mode check (Table S7) remain in the pseudo-event sampling frame. The pooled FPR is therefore an average over periods with different background rates, and is not driven by the storm interval (Table S25).

### S9.5 Cadence-distribution match

**Table S27 — Distribution of the TLE interval spanning the evaluation point** (gap between the last pre-window TLE and the first post-window TLE used by the estimator). Pseudo-events: draw C; real events: the 96 included events (`gap_day` in `fs7_tle_recall_unified_20260825.csv`). Source: `docs/fs7_supplement_tables.py` (`S9_pseudo.cadence_match`).

| quantile | pseudo-events (n = 1,145), d | real events (n = 96), d |
|--:|--:|--:|
| 10% | 0.66 | 0.66 |
| 25% | 0.93 | 0.79 |
| 50% | 1.00 | 1.03 |
| 75% | 1.39 | 1.32 |
| 90% | 1.85 | 2.00 |

Two-sample Kolmogorov–Smirnov: D = 0.134, p = 0.076. The spanning interval of a real event additionally contains the event duration (t_start to t_end), which a pseudo-event (t_start = t_end) does not.

---

## Section S10. Altitude–inclination domain map (main §7)

![](figures_pub/fig_tle_noise_floor_map_contour/fig_tle_noise_floor_map_contour_en_light.png)

**Fig. S3** Altitude–inclination domain map of the study satellites (FORMOSAT-7 calibration set, 6; altimetry benchmark, 14; SPOT/GRACE/Sentinel-6B hold-out, 9; Starlink sample of the detector's training domain, 27 with a valid estimate), colored by the nominal TLE residual scale σ_TLE (m). Contours show the fitted noise floor σ_th(h) = sqrt(σ₀² + (A·e^{−(h−400)/H})²) with σ₀ = 0.045 m, A = 24.5 m, H = 77 km (fit in log space, soft-L1 loss, measurement floor 0.02 m; log-space R² = 0.89; no inclination dependence). The figure is contextual and is not part of the calibrated model's claims. The two GRACE pairs (NORAD 27391/27392 at ≈ 470 km and 43476/43477 at ≈ 496 km; σ_TLE 0.5–2.4 m) lie well below the contour value at their altitude, consistent with their low area-to-mass ratio, and mark a limit of the altitude-only description. Data: `tle_noise_floor_map.csv` (59 listed objects, 56 with a valid σ_TLE estimate); scripts: `fs7_noise_floor_map.py`, `fs7_noise_floor_map_v2.py`.
