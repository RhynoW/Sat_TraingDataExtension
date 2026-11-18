# Supplementary Material for "Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits"

**Revisions.** Section S17 (Tables S36–S43), Section S18 (Table S44, moved from the main text) and Table S1b are new in R2 (generated from `fs7_review6_analysis.json` by `docs/gen_fs7_supplement_r2.py`). Sections S11–S16 (Tables S28–S35, Fig. S5) are new in this revision and are generated from `fs7_review5_analysis.json` by `docs/gen_fs7_supplement_r1.py`; Section S9 is updated for the symmetric decision rules.

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
- Section S11 — Selection bias of the evaluable event population (Table S28) — *new in R1*
- Section S12 — Coefficient interpretation: per-cadence c and the drag-ambiguity term (Table S29) — *new in R1*
- Section S13 — Injection recall at every grid amplitude; autocorrelation stratification; held-out AUC CIs (Tables S30–S31) — *new in R1*
- Section S14 — Storm-interval candidates and geomagnetic activity; inclination corroboration (Table S32) — *new in R1*
- Section S15 — Symmetric decision rules and threshold sweep (Table S33; Fig. S5) — *new in R1*
- Section S16 — Decomposition of real-event outcomes (Tables S34–S35) — *new in R1*
- Section S17 — R2 robustness analyses: TLE-response sensitivity, contamination by source, independent-event check, sign sensitivity, E1 logistic, wide-grid c and the SNR-floor artifact, drag proxies, D1 parameter sensitivity (Tables S36–S43) — *new in R2*
- Section S18 — Conditions of applicability and requirements for transfer (Table S44) — *moved from the main text in R2*

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

**Table S1b — Final-version map (R2): each main-text table, figure and number, with the final file, key and script that produce it.** Earlier JSON files that are not listed here are superseded for main-text use and are kept only for traceability.

| main-text item | final source file (key) | script |
|---|---|---|
| Table 1, Table 2 (event counts) | `fs7_events_2025raise.csv`, `fs7_events_campaigns_20260825.csv`, `fs7_tle_recall_unified_20260825.csv` | `fs7_campaign_truth_build.py`; `fs7_tle_recall_unified.py` |
| §2.6 exclusion reasons and timing; Table 2b | `fs7_review5_analysis.json` (`selection_bias`) | `fs7_review5_analysis.py` |
| §3.3 coefficient table (ĉ, profile CI, corr −0.98) | `fs7_law_fit_v4.json` (`c_drag`); `fs7_review3_analysis.json` (`identifiability`) | `fs7_injection_sweep_v4.py`; `fs7_review3_analysis.py` |
| §3.3 per-cadence c; drag-ambiguity term | `fs7_review5_analysis.json` (`per_cadence_c`, `drag_term_by_condition`); `fs7_review6_analysis.json` (`M7`) | `fs7_review5_analysis.py`; `fs7_review6_analysis.py` |
| Table 3 (held-out metrics, calibration) | `fs7_law_fit_v4.json`; `fs7_review4_analysis.json`; `fs7_final_supplement.json` (`calibration_slope`); `fs7_review4b_analysis.json` (`amp_calibration`); `fs7_review5_analysis.json` (`heldout_auc`) | `fs7_injection_sweep_v4.py`; `fs7_review4_analysis.py`; `fs7_final_supplement.py`; `fs7_review5_analysis.py` |
| §4.3 alternative drag proxies (Tables S43a–b) | `fs7_review6_analysis.json` (`M8`, `M8_da90`) | `fs7_review6_analysis.py` |
| Table 4a; §4.4 interpolated column | `fs7_review5_analysis.json` (`da90_interpolated`); `fs7_review5_recall_grid.csv` | `fs7_review5_analysis.py` |
| §4.4 model-implied Δa₉₀ | `fs7_review3_analysis.json` (`da90_backcalc`) | `fs7_review3_analysis.py` |
| §4.4 r₁ stratification | `fs7_review5_analysis.json` (`autocorr_stratification`) | `fs7_review5_analysis.py` |
| §4.5 metrics suite | `fs7_injection_metrics.csv`; `fs7_law_fit_v3.json`; `fs7_supplement_tables.json` (`S7_metrics`) | `fs7_injection_sweep_v3.py`; `docs/fs7_supplement_tables.py` |
| §4.5 D1 parameter sensitivity | `fs7_review6_analysis.json` (`m9`); `fs7_review6_detector_sensitivity.csv` | `fs7_review6_analysis.py` |
| Table 4 (real-event recall) | `fs7_tle_recall_unified_20260825.csv` | `fs7_tle_recall_unified.py` |
| §5 E1 logistic comparison | `fs7_review6_analysis.json` (`M2`) | `fs7_review6_analysis.py` |
| §5.1 Kp alignment | `fs7_review5_analysis.json` (`storm_alignment`); `data/space_weather/gfz_kp_3h_2024-04_05.csv` | `fs7_review5_analysis.py` |
| Table 5; §5.4 sweep, stratification | `fs7_review5_analysis.json` (`symmetric_rules`, `threshold_sweep`); `fs7_supplement_tables.json` (`S9_pseudo`, Draw C) | `fs7_review5_analysis.py`; `docs/fs7_supplement_tables.py` |
| §5.4 sign sensitivity; independent 85-event check | `fs7_review6_analysis.json` (`M5`, `M4`) | `fs7_review6_analysis.py` |
| Table 6, Table 6a; §5.5 | `fs7_review5_analysis.json` (`miss_decomposition`); `fs7_review5_event_decomposition.csv`; `fs7_review6_analysis.json` (`M1`, `M3`) | `fs7_review5_analysis.py`; `fs7_review6_analysis.py` |
| §6.1–6.2 (temporal hold-out, blocked CV) | `fs7_law_fit_v4.json`; `fs7_review4_analysis.json` | `fs7_injection_sweep_v4.py`; `fs7_review4_analysis.py` |
| Figs. 1–6; Figs. S1–S5 | see the README of the reproduction package | `docs/gen_fig_fs7_*.py`; `fs7_injection_sweep*.py`; `fs7_review5_analysis.py` |

Superseded for main-text use: `fs7_review3_analysis.json` (`confusion`, the original Draw A), which is retained for comparison in Section S9.

**Error-rate terms** follow main §3.5. The *false-alarm rate* is the number of flags per satellite per 30 days in D1 control windows. The *false-positive rate* is FP/(FP + TN) over E1 pseudo-events. The *false-discovery proportion* is 1 − precision.

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

Pseudo-events are random TLE epochs, up to 200 per satellite, drawn without replacement from the full 2024–2026 history (excluding the first and last 3 d), rejected if within 2 d of the t_start of any of the 131 verified events, and evaluated with the identical pre/post trend estimator, windows and thresholds as the real events (`tle_step`). A pseudo-event is *evaluable* when the estimator's coverage conditions hold (≥ 3 TLEs pre, ≥ 1 TLE post). In the original submission, FP = evaluable pseudo-event with |residual| above the threshold (no sign condition), whereas real-event TPs required a sign match; this asymmetry is removed in R1, where both samples are evaluated under rule S (sign-constrained; pseudo-events carry a hypothesized sign drawn from the real-event sign mix, in expectation) and under rule U (sign-free) — Section S15. The FPR values in Tables S24–S26 are rule-U values. FPR = FP / (FP + TN), pooled across satellites. Three draws under this protocol are reported:

- **Draw A** (n = 1,131 evaluable): the draw tabulated in the original submission (`fs7_review3_analysis.json`, `confusion`). It depended on the TLE archive state at the time and cannot be reproduced exactly from the current archive (a rerun gives n = 1,141; `fs7_review3_analysis_rerun.json`); it is retained for comparison only.
- **Draw B** (n = 1,142): per-satellite stratification and storm sensitivity (`fs7_review4b_analysis.json`, `pseudo_event_stratified`).
- **Draw C** (n = 1,145): reproducible (TLE history restricted to epochs before 2026-08-25); used for main §5.4 Table 5 from R1 onward, for per-period stratification and cadence match (`docs/fs7_supplement_tables.py`, `S9_pseudo`), and for Section S15 (`fs7_review5_analysis.py`).

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

---

## Section S11. Selection bias of the evaluable event population (main §2.6, Table 2b)

Exclusion reasons (coverage rule of main §2.6): pre-event window with fewer than three TLEs only, 34; empty post-event window only, 1; both, 0. Distribution of the number of pre-event TLEs among excluded events: 0 TLE: 1, 1 TLE: 7, 2 TLE: 26, 7 TLE: 1.

Timing of TLE coverage. Excluded events: median time since the last TLE before t_start 17.0 h (IQR 11.2–37.8 h), median time from t_end to the next TLE 10.4 h (IQR 3.5–19.2 h). Included events: 7.3 h and 10.6 h.

**Table S28 — Real-event recall under alternative treatments of excluded events, both thresholds** (rule S). Source: `fs7_review5_analysis.json` (`selection_bias.recall_bounds_by_bin`).

| bin | verified | evaluable | 45 m: evaluable | 45 m: IPW | 45 m: worst | 45 m: best | 3σ: evaluable | 3σ: IPW | 3σ: worst | 3σ: best |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1–50 m | 52 | 37 | 0.11 | 0.11 | 0.08 | 0.37 | 0.19 | 0.17 | 0.13 | 0.42 |
| 50–100 m | 21 | 16 | 0.31 | 0.31 | 0.24 | 0.48 | 0.50 | 0.46 | 0.38 | 0.62 |
| 100–300 m | 22 | 18 | 0.50 | 0.47 | 0.41 | 0.59 | 0.61 | 0.57 | 0.50 | 0.68 |
| 300 m–1 km | 10 | 8 | 0.62 | 0.70 | 0.50 | 0.70 | 0.62 | 0.70 | 0.50 | 0.70 |
| 1–3 km | 26 | 17 | 0.82 | 0.86 | 0.54 | 0.88 | 0.82 | 0.86 | 0.54 | 0.88 |
| all | 131 | 96 | 0.39 | 0.37 | 0.28 | 0.55 | 0.47 | 0.44 | 0.34 | 0.61 |

IPW weight = 1 / P(included | campaign), inclusion probability estimated as the campaign inclusion fraction; satellite×campaign cells contain zero-inclusion cells (4) so a satellite×campaign IPW is not identifiable.

---

## Section S12. Coefficient interpretation: per-cadence c and the drag-ambiguity term (main §3.3)

**Table S29 — Per-cadence profile-likelihood estimate of c and the derived drag-ambiguity term by condition.** Source: `fs7_review5_analysis.json` (`per_cadence_c`, `drag_term_by_condition`). Grid `logspace(−1.3, 1.0, 47)`; 95% set ℓ(ĉ) − ℓₚ(c) ≤ 1.9208.

| cadence | ĉ | 95% profile set | set reaches grid edge |
|---|--:|---|---|
| 1× | 10.0 | [0.56, 10.0] | yes |
| 2× | 0.32 | [0.25, 0.5] | no |
| 4× | 0.28 | [0.22, 0.35] | no |

*Drag-ambiguity term by injection condition:*

| condition | σ_TLE (m) | c·\|ȧ\|·Δt, c = 0.32 (m) | c·\|ȧ\|·Δt, c = 0.28 (m) | σ_eff, c = 0.32 (m) | drag share of σ_eff² |
|---|--:|--:|--:|--:|--:|
| 1×·low | 1.1 | 2.0 | 1.7 | 2.3 | 0.76 |
| 1×·mid | 2.6 | 6.0 | 5.2 | 6.5 | 0.84 |
| 1×·high | 5.5 | 13.0 | 11.4 | 14.1 | 0.85 |
| 2×·low | 2.2 | 5.1 | 4.5 | 5.6 | 0.85 |
| 2×·mid | 5.4 | 14.7 | 12.9 | 15.7 | 0.88 |
| 2×·high | 10.7 | 23.7 | 20.7 | 26.0 | 0.83 |
| 4×·low | 3.6 | 10.2 | 8.9 | 10.8 | 0.89 |
| 4×·mid | 8.7 | 26.7 | 23.4 | 28.1 | 0.9 |
| 4×·high | 20.8 | 48.4 | 42.3 | 52.7 | 0.84 |

At 1× the profile likelihood increases monotonically to the upper grid edge, so c is not identified from 1× trials alone; the lower bound of the 95% set (0.56) exceeds the pooled estimate.

---

## Section S13. Injection recall at every grid amplitude and the interpolated Δa₉₀ (main §4.1, Table 4a)

**Table S30 — Injection recall by condition and grid amplitude**, with satellite × window cluster-bootstrap 95% CIs (B = 2,000). Source: `fs7_review5_recall_grid.csv`.

*(a) 20–200 m*

| condition | 20 m | 50 m | 100 m | 150 m | 200 m |
|---|--:|--:|--:|--:|--:|
| 1×·low | 0.58 [0.50, 0.66] | 0.99 [0.98, 1.00] | 0.99 [0.98, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 1×·mid | 0.14 [0.09, 0.19] | 0.50 [0.43, 0.58] | 0.96 [0.93, 0.99] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 1×·high | 0.13 [0.08, 0.18] | 0.15 [0.10, 0.20] | 0.64 [0.56, 0.71] | 0.89 [0.83, 0.93] | 0.98 [0.96, 1.00] |
| 2×·low | 0.38 [0.31, 0.46] | 0.94 [0.89, 0.97] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 2×·mid | 0.13 [0.08, 0.18] | 0.44 [0.36, 0.52] | 0.91 [0.87, 0.96] | 0.99 [0.97, 1.00] | 1.00 [1.00, 1.00] |
| 2×·high | 0.17 [0.12, 0.24] | 0.25 [0.19, 0.32] | 0.47 [0.39, 0.55] | 0.71 [0.65, 0.78] | 0.89 [0.84, 0.93] |
| 4×·low | 0.21 [0.16, 0.28] | 0.56 [0.48, 0.63] | 0.91 [0.86, 0.95] | 0.99 [0.98, 1.00] | 1.00 [1.00, 1.00] |
| 4×·mid | 0.17 [0.12, 0.24] | 0.16 [0.10, 0.22] | 0.44 [0.37, 0.53] | 0.71 [0.64, 0.79] | 0.90 [0.85, 0.94] |
| 4×·high | 0.13 [0.08, 0.18] | 0.15 [0.10, 0.21] | 0.15 [0.10, 0.21] | 0.25 [0.18, 0.32] | 0.43 [0.35, 0.51] |

*(b) 300–2,000 m*

| condition | 300 m | 500 m | 750 m | 1,000 m | 1,500 m | 2,000 m |
|---|--:|--:|--:|--:|--:|--:|
| 1×·low | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 1×·mid | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 1×·high | 0.99 [0.98, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 2×·low | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 2×·mid | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 2×·high | 0.99 [0.97, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 4×·low | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 4×·mid | 0.98 [0.96, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| 4×·high | 0.67 [0.59, 0.74] | 0.92 [0.88, 0.96] | 0.99 [0.98, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |

Interpolation: the recall curve is made monotone non-decreasing by pool-adjacent-violators, and the 0.90 crossing is interpolated linearly in log₁₀Δa between the bracketing grid amplitudes; the bootstrap repeats both steps in every resample. Source of Table 4a: `fs7_review5_analysis.json` (`da90_interpolated`).

**Table S31 — Within-cadence stratification by residual lag-1 autocorrelation r₁** (terciles of r₁ within each cadence; observed minus mean predicted recall under the descriptive-refit coefficients). Source: `fs7_review5_analysis.json` (`autocorr_stratification`).

| cadence | r₁ tercile | median r₁ | windows | interpolated Δa₉₀ [95% CI] | obs − pred (all Δa) | obs − pred (Δa ≤ 200 m) |
|---|---|--:|--:|--:|--:|--:|
| 1× | low | -0.04 | 160 | 121 m [98, 141] | -0.040 | -0.089 |
| 1× | mid | 0.24 | 159 | 106 m [94, 120] | -0.033 | -0.074 |
| 1× | high | 0.44 | 159 | 121 m [99, 140] | -0.038 | -0.087 |
| 2× | low | 0.08 | 160 | 150 m [130, 175] | +0.007 | +0.007 |
| 2× | mid | 0.47 | 159 | 136 m [105, 168] | +0.027 | +0.049 |
| 2× | high | 0.69 | 159 | 160 m [139, 176] | +0.030 | +0.050 |
| 4× | low | 0.09 | 160 | 281 m [242, 341] | +0.023 | +0.021 |
| 4× | mid | 0.49 | 159 | 285 m [231, 353] | +0.024 | +0.028 |
| 4× | high | 0.74 | 159 | 403 m [336, 467] | +0.011 | +0.012 |

Adding r₁ as a covariate to the calibration-split logistic model (c = 0.28 fixed) changes the held-out log loss from 0.1238 to 0.1228 (r₁ coefficient 0.245). Correlation of r₁ with log₁₀ SNR_eff: -0.181.

Held-out AUC (trial level, 212 clusters, B = 2,000): drag-aware 0.9773 [0.9736, 0.9806], amplitude-only 0.9671 [0.9621, 0.9717], difference 0.0102 [0.0072, 0.0131].

---

## Section S14. Storm-interval candidates and geomagnetic activity (main §5.1)

**Table S32 — The 21 storm-interval candidates aligned with the GFZ 3-hourly Kp index** [main ref. 14]. Main-phase onset (first Kp ≥ 7 in the sample): 2024-05-10 15:00 UT; Kp peak 9.0 at 2024-05-11 00:00 UT. 'Kp slot' is the 3-h interval containing t_start. Source: `fs7_review5_analysis.json` (`storm_alignment`), `data/space_weather/gfz_kp_3h_2024-04_05.csv`.

| satellite | t_start (UT) | step (m) | Kp slot | max Kp, preceding 24 h | F10.7 obs (sfu) | hours from main-phase onset |
|---|---|--:|--:|--:|--:|--:|
| L76 | 2024-05-02 18:12 | -21.7 | 6.7 | 6.7 | 142 | -188.8 |
| L76 | 2024-05-02 19:45 | -16.9 | 6.7 | 6.7 | 142 | -187.2 |
| L78 | 2024-05-11 18:41 | -47.3 | 7.7 | 9.0 | 214 | +27.7 |
| L80 | 2024-05-11 22:24 | -33.8 | 7.7 | 9.0 | 214 | +31.4 |
| L76 | 2024-05-12 02:15 | -27.0 | 6.3 | 9.0 | 222 | +35.2 |
| L76 | 2024-05-12 02:39 | -27.9 | 6.3 | 9.0 | 222 | +35.6 |
| L76 | 2024-05-12 05:00 | -16.5 | 7.0 | 9.0 | 222 | +38.0 |
| L77 | 2024-05-12 11:14 | -23.4 | 4.3 | 8.7 | 222 | +44.2 |
| L80 | 2024-05-12 11:33 | -23.4 | 4.3 | 8.7 | 222 | +44.5 |
| L77 | 2024-05-12 12:03 | -21.6 | 2.0 | 8.3 | 222 | +45.0 |
| L79 | 2024-05-13 17:35 | -29.9 | 2.7 | 6.3 | 215 | +74.6 |
| L79 | 2024-05-13 18:08 | -32.7 | 2.3 | 6.3 | 215 | +75.1 |
| L79 | 2024-05-14 10:45 | -26.1 | 2.3 | 3.3 | 220 | +91.8 |
| L77 | 2024-05-15 21:48 | -29.1 | 2.3 | 3.0 | 216 | +126.8 |
| L77 | 2024-05-16 12:21 | -40.0 | 4.3 | 6.0 | 207 | +141.3 |
| L78 | 2024-05-16 18:10 | -32.9 | 2.3 | 6.0 | 207 | +147.2 |
| L78 | 2024-05-16 19:45 | -30.0 | 2.3 | 6.0 | 207 | +148.8 |
| L78 | 2024-05-17 17:34 | -32.0 | 5.3 | 5.3 | 204 | +170.6 |
| L78 | 2024-05-17 23:25 | -42.9 | 5.3 | 6.0 | 204 | +176.4 |
| L78 | 2024-05-17 23:43 | -43.1 | 5.3 | 6.0 | 204 | +176.7 |
| L78 | 2024-05-18 11:18 | -38.2 | 3.0 | 6.0 | 194 | +188.3 |

The project's earlier daily index file carried a constant fill value for Kp in April–May 2024 and is not used.

**Inclination corroboration** (main §2.7). Robust scale of the inclination change across all candidates 0.00147°; corroboration level 4σ = 0.00589°. Verified events with an inclination signature: 2 of 131; rejected candidates: 6 of 891 (persistence 3, common mode 2, both 1).

---

## Section S15. Symmetric decision rules and threshold sweep (main §5.4)

Pseudo-event draw: Draw C (n = 1,145). Hypothesized sign for rule S: positive with probability 0.521 (the real-event sign mix), applied in expectation.

**Table S33 — Original asymmetric and symmetric rules.** Source: `fs7_review5_analysis.json` (`symmetric_rules`, `threshold_sweep`); full sweep in `fs7_review5_threshold_sweep.csv`.

| threshold | rule | TP | FP | recall | FPR |
|---|---|--:|--:|--:|--:|
| 45 m | original (TP sign-constrained, FP sign-free) | 37 | 59 | 0.385 | 0.052 |
| 45 m | S (both sign-constrained) | 37 | 29.8 | 0.385 | 0.026 |
| 45 m | U (both sign-free) | 53 | 59 | 0.552 | 0.052 |
| unified 3σ | original (TP sign-constrained, FP sign-free) | 45 | 628 | 0.469 | 0.548 |
| unified 3σ | S (both sign-constrained) | 45 | 314.0 | 0.469 | 0.274 |
| unified 3σ | U (both sign-free) | 72 | 628 | 0.750 | 0.548 |

ROC AUC (real events versus pseudo-events; events and per-satellite pseudo-events resampled separately, B = 2,000): rule U 0.727 [0.659, 0.795]; rule S 0.588 [0.509, 0.666]. Post hoc Youden threshold (reference only): 105 m (U: recall 0.552, FPR 0.027; S: recall 0.385, FPR 0.014). Smallest swept threshold with FPR ≤ 0.01: rule S 186 m (recall 0.354); rule U 1819 m (recall 0.271). Sample precision uses the sample ratio 96 events : 1,145 pseudo-events and is prevalence-dependent; it is not an operational precision.

![](fig_fs7_threshold_sweep.png)

**Fig. S5** ROC curves (left) and recall/FPR versus threshold (right) for the 96 evaluable real events and the 1,145 pseudo-events under rules S and U; dots and the dotted line mark the pre-specified 45 m threshold. Data: `fs7_review5_threshold_sweep.csv`; script: `fs7_review5_analysis.py`.

---

## Section S16. Decomposition of real-event outcomes (main §5.5, Table 6)

**Table S34 — Outcome classes of all 131 verified events by amplitude bin** (rule S). Classes: excluded (pre-event coverage), excluded (post-event coverage), detected, below threshold, sign mismatch (|residual| above threshold, opposite sign). Source: `fs7_review5_analysis.json` (`miss_decomposition`); per-event classes in `fs7_review5_event_decomposition.csv`.

| bin | 45 m: excl. pre / excl. post / detected / below / wrong sign | 3σ: excl. pre / excl. post / detected / below / wrong sign |
|---|---|---|
| 1–50 m | 14 / 1 / 4 / 25 / 8 | 14 / 1 / 7 / 13 / 17 |
| 50–100 m | 5 / 0 / 5 / 10 / 1 | 5 / 0 / 8 / 6 / 2 |
| 100–300 m | 4 / 0 / 9 / 8 / 1 | 4 / 0 / 11 / 5 / 2 |
| 300 m–1 km | 2 / 0 / 5 / 0 / 3 | 2 / 0 / 5 / 0 / 3 |
| 1–3 km | 9 / 0 / 14 / 0 / 3 | 9 / 0 / 14 / 0 / 3 |
| all | 34 / 1 / 37 / 43 / 16 | 34 / 1 / 45 / 24 / 27 |

Shared TLE interval (another verified event between the last pre-event and first post-event TLE): 45 m recall 0.382 (n = 55) versus 0.39 (n = 41) for isolated events; 3σ: 0.491 versus 0.439.

**Table S35 — TLE response class by amplitude bin and pre-event trend status** (evaluable events). ratio = (TLE a − pre-window linear trend)/SP3 step for each TLE in [t_end+2h, t_end+3d]; immediate: first ratio in [0.5, 2]; delayed: a later TLE in [0.5, 2]; none: all |ratio| < 0.5; other: remaining (e.g. > 2 or opposite sign, typically subsequent burns). Contaminated: an SP3 candidate of any verdict with |step| ≥ 500 m lies in the pre-event trend window.

| bin | clean: immediate / delayed / none / other | contaminated: immediate / delayed / none / other |
|---|---|---|
| 1–50 m | 0 / 5 / 9 / 16 | 0 / 0 / 0 / 7 |
| 50–100 m | 0 / 0 / 10 / 1 | 0 / 0 / 0 / 5 |
| 100–300 m | 0 / 3 / 7 / 1 | 0 / 0 / 0 / 7 |
| 300 m–1 km | 1 / 0 / 0 / 0 | 0 / 0 / 0 / 7 |
| 1–3 km | 3 / 1 / 0 / 0 | 8 / 1 / 0 / 4 |

**Misses in the 1–3 km bin (45 m).**

| satellite | campaign | t_start (UT) | SP3 step (m) | TLE residual (m) | gap (d) | verified events in pre-window | SP3 candidates ≥ 500 m in pre-window (any verdict) |
|---|---|---|--:|--:|--:|--:|--:|
| L80 | 2025-07/08 | 2025-07-21 08:39 | 1666 | -1031.6 | 2.86 | 0 | 1 |
| L80 | 2025-07/08 | 2025-08-20 08:16 | 2517 | -2274.0 | 1.93 | 6 | 2 |
| L79 | 2025-05 | 2025-05-14 04:13 | 2236 | -265.4 | 1.06 | 0 | 2 |

Of the 16 wrong-sign events at 45 m, 11 have a contaminated pre-event window.

---

## Section S17. R2 robustness analyses (main §3.3, §4.3–4.5, §5, §5.4–5.5)

Source for every table in this section: `fs7_review6_analysis.json`, produced by `fs7_review6_analysis.py`.

**Table S36 — Outcome classes and TLE-response classes with cluster-bootstrap CIs** (23 satellite × campaign clusters, B = 2,000; key `M1`).

| population | class | n | proportion [95% CI] |
|---|---|--:|--:|
| 131 verified, 45 m, rule S | excl_pre | 34 | 0.26 [0.10, 0.46] |
| 131 verified, 45 m, rule S | excl_post | 1 | 0.01 [0.00, 0.03] |
| 131 verified, 45 m, rule S | detected | 37 | 0.28 [0.16, 0.39] |
| 131 verified, 45 m, rule S | below_threshold | 43 | 0.33 [0.22, 0.48] |
| 131 verified, 45 m, rule S | sign_mismatch | 16 | 0.12 [0.06, 0.18] |
| clean 50–300 m (n = 22) | immediate | 0 | 0.00 [0.00, 0.00] |
| clean 50–300 m (n = 22) | delayed | 3 | 0.14 [0.00, 0.41] |
| clean 50–300 m (n = 22) | none | 17 | 0.77 [0.50, 0.97] |
| clean 50–300 m (n = 22) | other | 2 | 0.09 [0.00, 0.22] |

**Table S37 — Sensitivity of the TLE-response classification** (clean-window events; ratio cut c means a response requires a ratio in [c, 1/c], and 'none' requires |ratio| < c at every TLE in the window).

| ratio cut | window (d) | 50–300 m: none / delayed / immediate / other | ≥ 300 m: immediate / n |
|--:|--:|---|---|
| 0.3 | 3 | 16 / 4 / 0 / 2 | 4 / 5 |
| 0.3 | 5 | 12 / 5 / 0 / 5 | 4 / 5 |
| 0.3 | 7 | 10 / 5 / 0 / 7 | 4 / 5 |
| 0.5 | 3 | 17 / 3 / 0 / 2 | 4 / 5 |
| 0.5 | 5 | 14 / 5 / 0 / 3 | 4 / 5 |
| 0.5 | 7 | 10 / 5 / 0 / 7 | 4 / 5 |
| 0.7 | 3 | 17 / 2 / 0 / 3 | 4 / 5 |
| 0.7 | 5 | 15 / 4 / 0 / 3 | 4 / 5 |
| 0.7 | 7 | 11 / 4 / 0 / 7 | 4 / 5 |

Covariates of no-response (clean 50–300 m): not_none: n = 5, median |ȧ| 22.1 m/d, median post-event TLEs within 3 d 7, median gap 0.73 d, median amplitude 178.1 m, negative-going 40%; none: n = 17, median |ȧ| 16.9 m/d, median post-event TLEs within 3 d 4, median gap 1.0 d, median amplitude 97.3 m, negative-going 65%. By campaign (none / delayed / other): 2024-07: 1 / 0 / 0; 2024-11/12: 1 / 0 / 1; 2025-05: 1 / 0 / 0; 2025-07/08: 12 / 3 / 1; 2026-01: 2 / 0 / 0. By satellite (none): L76 6, L77 2, L79 2, L80 4, L81 3. Largest |residual| within 3 d: median 10.2 m; 16 of 22 never exceed 45 m.

**Table S38 — Pre-event trend contamination by source** (≥ 500 m SP3 candidates in [t_start − 3 d, t_start); 'rejected' means rejected by any check, in practice the common-mode check; key `M3`).

| pre-event window | n | recall 45 m (S) | recall 45 m (U) | wrong sign | median \|residual\| (m) | median ratio | median \|ȧ\| (m/d) | median delay to first post-event TLE (h) | median amplitude (m) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| both | 3 | 1.00 | 1.00 | 0 | 1,266.3 | 1.82 | 1,095.4 | 21.8 | 1213.6 |
| clean | 57 | 0.16 | 0.25 | 5 | 6.4 | -0.01 | 23.5 | 8.2 | 46.0 |
| rejected_only | 24 | 0.71 | 1.00 | 7 | 2,168.3 | 1.74 | 832.4 | 16.7 | 242.5 |
| verified_only | 12 | 0.67 | 1.00 | 4 | 2,376.9 | 5.29 | 681.3 | 15.8 | 407.1 |

Events with a common-mode-rejected ≥ 500 m burn in the pre-event window: 27 (recall 0.74, wrong sign 7; by bin 1–50 m 7, 50–100 m 3, 100–300 m 3, 300 m–1 km 4, 1–3 km 10).

**Table S39 — 45 m threshold on events never used in the earlier analysis** (key `M4`).

| event subset | evaluable n | recall S [Wilson 95% CI] | recall U | discrimination AUC U | discrimination AUC S |
|---|--:|--:|--:|--:|--:|
| 85 events from four campaigns not used earlier | 53 | 0.36 [0.24, 0.49] | 0.55 | 0.72 | 0.53 |
| 46 events of 2025-07/08 (used earlier) | 43 | 0.42 [0.28, 0.57] | 0.56 | 0.73 | 0.67 |
| all | 96 | 0.39 [0.29, 0.48] | 0.55 | 0.73 | 0.59 |

Recall by amplitude bin, independent subset (rule S): 1–50 m 0.13 (n = 30), 50–100 m 0.43 (n = 7), 100–300 m 0.40 (n = 5), 300 m–1 km 1.00 (n = 5), 1–3 km 0.83 (n = 6). Pseudo-event FPR at 45 m (rule U): 0.052. Post hoc Youden threshold on the independent subset (rule U, reference only): 225 m.

**Table S40 — Rule-S sensitivity to the hypothesized-sign probability p₊** (key `M5`). Pseudo-event steps: 48.4% positive, median -0.29 m.

| p₊ | FPR (S), 45 m | FPR (S), 3σ | discrimination AUC (S) |
|--:|--:|--:|--:|
| 0.0 | 0.019 | 0.275 | 0.588 |
| 0.5 | 0.026 | 0.274 | 0.588 |
| 0.521 | 0.026 | 0.274 | 0.588 |
| 1.0 | 0.032 | 0.273 | 0.588 |

**Table S41 — E1-based logistic models versus the D1-based descriptive probability** (96 evaluable events; outcome = E1 detection at 45 m, rule S; key `M2`). LOCO = leave-one-campaign-out (5 folds); D1 probability uses fixed descriptive-refit coefficients (no refit).

| model | log loss | Brier | AUC |
|---|--:|--:|--:|
| E1 logistic: log₁₀ amplitude (LOCO) | 0.581 | 0.193 | 0.786 |
| E1 logistic: + contamination indicator (LOCO) | 0.517 | 0.16 | 0.867 |
| D1-based descriptive probability (no refit) | 2.056 | 0.373 | 0.546 |
| base rate | 0.667 | 0.237 | — |

**Table S42 — Profile likelihood of c on an extended grid (c ≤ 100) with unclipped SNR** (key `M7`). The c → ∞ limit is the drag-only model Δa/(|ȧ|Δt), in which σ_TLE drops out.

| data | ĉ | 95% set | ℓ(ĉ) | ℓ(0.32) | ℓ(drag-only limit) | interior maximum |
|---|--:|---|--:|--:|--:|---|
| 1× | 100.0 | [0.56, inf] | -642.1 | -650.9 | -642.1 | no |
| 2× | 0.32 | [0.25, 0.5] | -849.0 | -849.0 | -856.9 | yes |
| 4× | 0.28 | [0.22, 0.35] | -1247.3 | -1247.6 | -1260.9 | yes |
| all cadences | 0.32 | [0.28, 0.4] | -2891.6 | -2891.6 | -2913.8 | yes |

*Numerical floor artifact.* The released analysis scripts bound SNR_eff to [10⁻², 10⁴] before taking logarithms. This has no effect for c ≤ 10 (at most 0.2% of trials reach the floor). On an extended grid, however, a growing share of trials is floored, which acts as a spurious low-SNR plateau and inflates the likelihood. Without the bound, the likelihood decreases monotonically toward the drag-only limit beyond the interior maximum:

| c | share of trials below 10⁻² | ℓ unclipped | ℓ with floor |
|--:|--:|--:|--:|
| 0.32 | 0.000 | -2891.6 | -2891.6 |
| 10 | 0.002 | -2913.8 | -2912.2 |
| 20 | 0.014 | -2913.8 | -2896.3 |
| 50 | 0.058 | -2913.8 | -2773.9 |
| 100 | 0.119 | -2913.8 | -2682.6 |

All published estimates use c ≤ 10 and are unaffected. The R2 analyses of alternative drag proxies use unclipped SNR.

**Table S43a — Alternative drag proxies** (calibration-split fit, test-split evaluation; key `M8`).

| ambiguity term | ĉ (calibration) | calibration mean log-likelihood | held-out log loss | held-out AUC |
|---|--:|--:|--:|--:|
| c·|ȧ|·Δt^0 | 0.154 | -0.2341 | 0.1231 | 0.9764 |
| c·|ȧ|·Δt^0.5 | 0.316 | -0.22504 | 0.1159 | 0.9807 |
| c·|ȧ|·Δt^1 | 0.274 | -0.23174 | 0.1238 | 0.9773 |
| c·|ȧ|·Δt^2 | 0.049 | -0.24694 | 0.137 | 0.9698 |
| drag-only Δa/(|ȧ|Δt) | — | — | 0.1243 | 0.9774 |
| none (Δa/σ) | — | — | 0.1413 | 0.9671 |

**Table S43b — Model-implied Δa₉₀ (full-data fit) under the linear and √Δt forms versus the interpolated empirical Δa₉₀** (key `M8_da90`).

| condition | linear Δt: model (m) | √Δt: model (m) | interpolated empirical (m) |
|---|--:|--:|--:|
| 1×·low | 22 | 34 | 40.7 |
| 1×·mid | 64 | 93 | 91.0 |
| 1×·high | 138 | 176 | 156.5 |
| 2×·low | 55 | 56 | 47.0 |
| 2×·mid | 153 | 148 | 98.4 |
| 2×·high | 254 | 244 | 209.9 |
| 4×·low | 106 | 80 | 98.8 |
| 4×·mid | 274 | 203 | 200.0 |
| 4×·high | 515 | 372 | 476.3 |

Ratio interpolated / model: linear [0.64, 1.85], √Δt [0.67, 1.28] (√Δt: ĉ = 0.355, SNR₉₀ = 8.56).

**Table S43c — D1 parameter sensitivity** (all 15,774 injections replayed with identical windows and injection indices; baseline agreement with the published hits 1.0000; per-condition values in `fs7_review6_detector_sensitivity.csv`; the false-alarm rate is the replay's flags per satellite per 30 days in control windows, averaged over conditions).

| setting | κ | h | MAD multiplier | interpolated Δa₉₀ range (m) | max relative change | Spearman vs baseline | false-alarm rate |
|---|--:|--:|--:|---|--:|--:|--:|
| baseline | 0.5 | 5 | 3 | 41–476 | 0.0% | 1.000 | 1.75 |
| h=4 | 0.5 | 4 | 3 | 40–476 | 2.4% | 1.000 | 1.91 |
| h=6 | 0.5 | 6 | 3 | 41–476 | 1.8% | 0.983 | 1.65 |
| kappa=0.25 | 0.25 | 5 | 3 | 40–474 | 6.7% | 0.983 | 2.12 |
| kappa=1.0 | 1.0 | 5 | 3 | 41–476 | 0.2% | 1.000 | 1.53 |
| MAD 4σ | 0.5 | 5 | 4 | 47–576 | 47.4% | 0.967 | 1.07 |

---

## Section S18. Conditions of applicability and requirements for transfer (main §7)

**Table S44 — Evaluated conditions and what a transfer would require** (main §7, "Population of applicability").

| factor | evaluated FS7 condition | required for a meaningful transfer |
|---|---|---|
| altitude / inclination | ≈ 550 km, 24° | similar drag regime, or recalibration of c·\|ȧ\|·Δt |
| propulsion / maneuver type | chemical, discrete burns of tens of metres to 2.8 km | impulsive maneuvers; low-thrust arcs are not covered |
| maneuver coordination | individually verified only; coordinated burns excluded | separate validation of coordinated events |
| TLE cadence | median 8–12 h over the full history, 21.6 h during the 2025 campaign; 0.3–2.0 d across the injection conditions | comparable Δt, or use of the cadence-dependent empirical floors |
| residual scale σ_TLE | 1–21 m in quiet windows | measured σ_TLE with the Appendix B estimator |
| drag rate \|ȧ\| | 18–77 m/day in quiet windows; up to 182 m/day in the storm | within or near the calibrated range |
| detector | D1 (MAD 3σ ∪ CUSUM κ = 0.5, h = 5) | the same detector family, or recalibration |
| truth source | independent precise orbits (60 s SP3) | an independent truth source (SP3/SLR/DORIS/GNSS-POD) with ≥ ~50 verified events spanning 20 m–2 km, plus quiet windows for injections and a temporal hold-out | As supplementary context (Fig. S3), a domain map of the study satellites in altitude–inclination space with fitted noise-floor contours σ_th(h) = sqrt(σ₀² + (A·e^{−(h−400)/H})²) (σ₀ = 0.045 m, A = 24.5 m, H = 77 km, log-space R² = 0.89; derived in the companion study [11]) illustrates the altitude dominance of the nominal residual scale; it is contextual, not part of the calibrated model's claims, and the GRACE pair's departure from the contours (consistent with their low area-to-mass ratio) marks a limit of the single-parameter description.
