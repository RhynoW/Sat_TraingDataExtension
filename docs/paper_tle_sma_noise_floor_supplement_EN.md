# Supplementary Material

for "TLE-Derived Semi-Major-Axis Variability on Operator-Logged Maneuver-Free Arcs: Residual Dependence and Empirical Maneuver Thresholds, with Application to FORMOSAT"

Sections S1–S2 and S5–S8 are reproduced by `docs/paperA_reviewV1_analysis.py` (output `data/benchmark/paperA_reviewV1.json`); Sections S3–S4 by `docs/paperA_numbers.py` (output `data/benchmark/paperA_numbers.json`).

## Section S1. Sensitivity of the variability estimates to processing choices (main Section 3.2)

The estimation of Section 2.2 is repeated on the 3 × 3 × 3 grid of Section 2.3. Over all 27 configurations the median σ_res ranges from 0.56 to 0.89 m, the median s_Δ from 0.109 to 0.124 m and the median scale-ratio persistence index P from 0.87 to 0.97. P is a distribution-dependent diagnostic and is not interpreted as an autocorrelation estimate (main Section 2.2). Table S1 shows one-at-a-time changes from the baseline (full grid: `data/benchmark/paperA_rv1_sensitivity.csv`).

**Table S1 — One-at-a-time sensitivity of the thirteen-satellite medians.**

| configuration | median σ_res (m) | median s_Δ (m) | median P |
|---|--:|--:|--:|
| baseline (thinning 3 h, trimming 0.75 d, degree rule 0) | 0.753 | 0.118 | 0.926 |
| thinning 1.5 h | 0.740 | 0.110 | 0.937 |
| thinning 6 h | 0.739 | 0.123 | 0.913 |
| trimming 0.5 d | 0.768 | 0.118 | 0.932 |
| trimming 1.0 d | 0.735 | 0.117 | 0.921 |
| degree rule −1 | 0.857 | 0.117 | 0.956 |
| degree rule +1 | 0.602 | 0.117 | 0.891 |

## Section S2. Null distribution: drift-corrected variant and lag dependence (main Sections 3.1 and 3.3)

The drift-corrected statistic fits a straight line to the SMA in each bracket ([0.3, 3] d before and after the window) and differences the two fits at the window midpoint. It is evaluated on the same pseudo-event windows as Table 2 of the main text.

**Table S2 — Null distribution of the drift-corrected step statistic** (ordered by σ_res; FAP: false-alarm probability per window).

| satellite | median (m) | robust scale (m) | FAP at 3σ_res | p99 (m) | p99.7 (m) |
|---|--:|--:|--:|--:|--:|
| Sentinel-3A | +0.011 | 0.27 | 0.091 | 4.3 | 6.6 |
| Jason-3 | -0.003 | 0.17 | 0.035 | 2.7 | 4.4 |
| SWOT | +0.010 | 0.31 | 0.099 | 102.0 | 252.5 |
| Sentinel-3B | +0.006 | 0.25 | 0.081 | 4.1 | 14.1 |
| Jason-2 | +0.002 | 0.27 | 0.060 | 2.4 | 3.6 |
| Sentinel-6A | +0.001 | 0.16 | 0.001 | 0.6 | 1.0 |
| Jason-1 | -0.002 | 0.42 | 0.026 | 3.9 | 9.2 |
| HY-2D | +0.006 | 0.40 | 0.121 | 7.5 | 13.8 |
| HY-2C | +0.001 | 0.44 | 0.104 | 6.7 | 17.3 |
| CryoSat-2 | -0.003 | 0.19 | 0.022 | 4.6 | 8.0 |
| SARAL | +0.001 | 0.17 | 0.025 | 13.7 | 32.6 |
| Envisat | -0.008 | 1.47 | 0.109 | 16.3 | 30.6 |
| HY-2A | -0.026 | 3.60 | 0.295 | 58.6 | 127.0 |

For Jason-3 the drift-corrected statistic flags 54 of 68 logged windows with non-zero SMA change at its 99th percentile (2.68 m) and 54 of 68 at its 99.7th percentile (4.38 m), compared with 67 and 64 for the median-bracket statistic of Eq. (4).

Pairs are pooled over all within-arc residual pairs of each satellite; every bin contains all thirteen satellites (3–6 h: 894 arcs, 19,238 pairs; 6–12 h: 981 arcs, 58,660 pairs; 12–24 h: 993 arcs, 107,637 pairs; 24–48 h: 1,041 arcs, 225,086 pairs; 48–96 h: 1,044 arcs, 435,406 pairs; 96–192 h: 1,038 arcs, 759,013 pairs; per-satellite counts in `data/benchmark/paperA_rv2_lag_counts.csv`).

**Table S3 — Increment scale s(τ)/σ_res by separation τ between element sets** (ordered by σ_res; the value 1 corresponds to independent, identically distributed Gaussian residuals; independence alone does not fix this MAD-based ratio).

| satellite | 3–6 h | 6–12 h | 12–24 h | 24–48 h | 48–96 h | 96–192 h |
|---|--:|--:|--:|--:|--:|--:|
| Sentinel-3A | 0.25 | 0.34 | 0.48 | 0.69 | 0.86 | 1.05 |
| Jason-3 | 0.18 | 0.25 | 0.31 | 0.40 | 0.57 | 0.82 |
| SWOT | 0.18 | 0.33 | 0.44 | 0.62 | 0.86 | 1.15 |
| Sentinel-3B | 0.22 | 0.27 | 0.40 | 0.59 | 0.82 | 1.00 |
| Jason-2 | 0.15 | 0.22 | 0.28 | 0.40 | 0.61 | 0.84 |
| Sentinel-6A | 0.11 | 0.12 | 0.18 | 0.28 | 0.46 | 0.72 |
| Jason-1 | 0.11 | 0.17 | 0.28 | 0.39 | 0.67 | 0.95 |
| HY-2D | 0.16 | 0.20 | 0.30 | 0.44 | 0.67 | 1.01 |
| HY-2C | 0.15 | 0.20 | 0.29 | 0.44 | 0.72 | 1.08 |
| CryoSat-2 | 0.08 | 0.13 | 0.23 | 0.39 | 0.70 | 1.11 |
| SARAL | 0.04 | 0.05 | 0.08 | 0.13 | 0.23 | 0.39 |
| Envisat | 0.19 | 0.30 | 0.46 | 0.65 | 0.81 | 0.97 |
| HY-2A | 0.40 | 0.55 | 0.60 | 0.71 | 0.81 | 0.92 |
| **median** | **0.16** | **0.22** | **0.30** | **0.44** | **0.70** | **0.97** |

## Section S3. Starlink-altitude estimates (main Section 3.7)

No operator-logged maneuver-free arcs exist for Starlink. Table S4 lists the estimates available at Starlink altitude; they measure different quantities and are not interchangeable.

**Table S4 — Starlink-altitude estimates.**

| estimate | definition | value |
|---|---|---|
| TLE vs SpaceX ephemeris, all | absolute difference of osculating SMA, TLE-propagated (SGP4, GCRS) minus ephemeris (EME2000) at ephemeris epochs; 283 satellites, 35,460 daily samples, 2026-05-01 to 2026-09-20 | median 57.0 m; IQR 23.6–110.8 m; P90 191.6 m; n = 35,460 |
| TLE vs ephemeris, propagation age 0-6h | as above | median 47.7 m (n = 14,860) |
| TLE vs ephemeris, propagation age 6-12h | as above | median 60.8 m (n = 8,641) |
| TLE vs ephemeris, propagation age 12-24h | as above | median 67.9 m (n = 9,191) |
| TLE vs ephemeris, propagation age 24-48h | as above | median 101.2 m (n = 2,150) |
| TLE vs ephemeris, propagation age 48-72h | as above | median 117.4 m (n = 468) |
| TLE vs ephemeris, propagation age >72h | as above | median 71.7 m (n = 150) |
| filtered, truth SMA rate < 2000 m/day | 152 satellites with net SMA change < 10 km; sample kept when the truth SMA rate to both neighbours is below the limit | median 33.2 m; 2.85% of samples kept |
| filtered, truth SMA rate < 1000 m/day | 152 satellites with net SMA change < 10 km; sample kept when the truth SMA rate to both neighbours is below the limit | median 35.0 m; 0.95% of samples kept |
| filtered, truth SMA rate < 500 m/day | 152 satellites with net SMA change < 10 km; sample kept when the truth SMA rate to both neighbours is below the limit | median 36.7 m; 0.30% of samples kept |
| self-consistency, 30 satellites (snapshot 2026-09-18) | 40-TLE sliding windows, steps > 0.3 km excluded, linear detrending, median over windows | median 9.87 m (27 valid) |
| self-consistency, same satellites (snapshot 2026-11-17) | as above | median 14.14 m (27 valid) |
| STARLINK-3005, 60-day raw differences | MAD of all adjacent differences over 60 days, no exclusion | 30.33 m (35/141 differences > 0.3 km) |
| STARLINK-3005, sliding windows | as for the 30-satellite estimate | 3.86 m (8/17 clean windows) |

The filtered medians do not represent propulsion-free samples (see below). The J2 amplitude quoted below is the order-of-magnitude value J2·R_E²/a; the circular-orbit short-period amplitude of the osculating SMA, (3/2)J2(R_E²/a)sin²i, is about 6.2 km at 53° inclination. The self-consistency estimates change between data snapshots because the TLE archive used for Starlink is a rolling window; the maneuver-free-arc results of the main text are computed on one fixed snapshot. The filtered medians are an order-of-magnitude guide only: the ephemeris SMA is osculating, the order-of-magnitude value J2·R_E²/a at a = 6850 km is 6.43 km, and the median day-to-day truth SMA change (6486 m/day for the 152 satellites) is dominated by aliased short-period terms rather than thrust. Weekly median prediction error versus F10.7: Spearman ρ = 0.564 (p = 0.0078, 21 weeks); point-wise ρ = 0.063 (F10.7 at epoch) and -0.037 (change of F10.7 over the propagation).

## Section S4. FORMOSAT-7 statistics (main Section 5.3)

Period [2025-11-17T00:00Z, 2026-11-18T00:00Z), exclusive upper bound (latest epoch 2026-11-17 20:19 UTC); adjacent |Δa| after removal of duplicate epochs.

**Table S5 — FORMOSAT-7 adjacent |Δa| statistics.**

| satellite | NORAD | median altitude (km) | median (m) | P90 (m) | P99 (m) | max (m) | steps > 50 m |
|---|---|--:|--:|--:|--:|--:|--:|
| FORMOSAT-7-1 (A) | 44349 | 577.2 | 4.78 | 16.67 | 46.12 | 6695.2 | 7 |
| FORMOSAT-7-2 (B) | 44351 | 577.2 | 4.84 | 16.84 | 38.23 | 9338.9 | 6 |
| FORMOSAT-7-3 (C) | 44343 | 537.6 | 8.59 | 30.03 | 52.61 | 126.5 | 12 |
| FORMOSAT-7-4 (D) | 44350 | 577.2 | 4.62 | 16.74 | 35.52 | 9354.7 | 4 |
| FORMOSAT-7-5 (E) | 44358 | 577.3 | 4.97 | 17.26 | 37.53 | 4217.5 | 6 |
| FORMOSAT-7-6 (F) | 44353 | 577.2 | 4.75 | 16.64 | 34.7 | 6561.9 | 6 |

**Table S6 — FORMOSAT-7 steps exceeding 50 m.**

| satellite | epoch after step (UTC) | Δa (m) |
|---|---|--:|
| FORMOSAT-7-1 (A) | 2026-01-01 06:41:41 | -62.4 |
| FORMOSAT-7-1 (A) | 2026-01-20 02:55:28 | +2609.0 |
| FORMOSAT-7-1 (A) | 2026-01-24 23:45:49 | +6695.2 |
| FORMOSAT-7-1 (A) | 2026-02-13 16:04:04 | -58.3 |
| FORMOSAT-7-1 (A) | 2026-03-31 23:01:05 | -74.7 |
| FORMOSAT-7-1 (A) | 2026-04-18 05:34:00 | -61.2 |
| FORMOSAT-7-1 (A) | 2026-06-06 04:16:47 | -84.7 |
| FORMOSAT-7-2 (B) | 2026-01-01 15:45:03 | -64.7 |
| FORMOSAT-7-2 (B) | 2026-01-23 16:48:45 | +9338.9 |
| FORMOSAT-7-2 (B) | 2026-01-25 00:50:06 | -61.5 |
| FORMOSAT-7-2 (B) | 2026-04-01 00:05:19 | -73.2 |
| FORMOSAT-7-2 (B) | 2026-04-17 14:37:56 | -51.3 |
| FORMOSAT-7-2 (B) | 2026-06-06 11:45:21 | -59.4 |
| FORMOSAT-7-3 (C) | 2025-12-06 13:14:11 | -50.5 |
| FORMOSAT-7-3 (C) | 2025-12-30 01:01:08 | -52.1 |
| FORMOSAT-7-3 (C) | 2026-01-01 00:39:27 | -60.4 |
| FORMOSAT-7-3 (C) | 2026-01-21 12:52:44 | -68.7 |
| FORMOSAT-7-3 (C) | 2026-01-24 12:19:24 | -51.3 |
| FORMOSAT-7-3 (C) | 2026-01-28 06:49:00 | -53.2 |
| FORMOSAT-7-3 (C) | 2026-01-29 06:37:48 | -52.8 |
| FORMOSAT-7-3 (C) | 2026-03-31 21:51:40 | -126.5 |
| FORMOSAT-7-3 (C) | 2026-04-17 16:52:39 | -90.3 |
| FORMOSAT-7-3 (C) | 2026-04-21 22:25:12 | -62.5 |
| FORMOSAT-7-3 (C) | 2026-06-05 14:49:54 | -121.8 |
| FORMOSAT-7-3 (C) | 2026-10-12 03:08:50 | -56.6 |
| FORMOSAT-7-4 (D) | 2026-01-01 13:36:48 | -74.2 |
| FORMOSAT-7-4 (D) | 2026-01-23 05:03:39 | +9354.7 |
| FORMOSAT-7-4 (D) | 2026-03-31 18:44:59 | -61.0 |
| FORMOSAT-7-4 (D) | 2026-04-17 18:53:51 | -50.2 |
| FORMOSAT-7-5 (E) | 2026-01-01 02:26:08 | -59.7 |
| FORMOSAT-7-5 (E) | 2026-01-19 19:28:02 | +2585.7 |
| FORMOSAT-7-5 (E) | 2026-01-20 17:51:14 | +2509.6 |
| FORMOSAT-7-5 (E) | 2026-01-23 14:40:38 | +4217.5 |
| FORMOSAT-7-5 (E) | 2026-04-01 01:08:59 | -71.4 |
| FORMOSAT-7-5 (E) | 2026-04-17 20:29:38 | -64.3 |
| FORMOSAT-7-6 (F) | 2026-01-01 04:34:33 | -68.3 |
| FORMOSAT-7-6 (F) | 2026-01-20 00:48:24 | +2621.9 |
| FORMOSAT-7-6 (F) | 2026-01-27 20:05:29 | +6561.9 |
| FORMOSAT-7-6 (F) | 2026-04-01 04:53:37 | -68.8 |
| FORMOSAT-7-6 (F) | 2026-04-17 21:02:13 | -58.0 |
| FORMOSAT-7-6 (F) | 2026-06-06 08:33:04 | -91.1 |

Positive steps of kilometres on 19–27 January 2026 are the orbit raise of five satellites. The epoch listed is the first element set after the step, not a burn time. The negative steps of −50 to −127 m cluster in four periods; every one spans a gap in the TLE series common to the six satellites, and most of its amplitude is decay accumulated over the gap (Table S9; main Section 5.3).

## Section S5. Data lineage (main Sections 2.1 and 3.1)

Maneuver-free arcs are the intervals between consecutive entries of the IDS maneuver histories (TAI, converted to UTC with the epoch-dependent TAI − UTC). "Listed" counts all intervals in the arc list; "used" counts arcs that pass the trimming (0.75 d each end), minimum-point (12) and minimum-span (3 d) criteria. TLE snapshot: latest download 2026-11-18 00:29 UTC, latest epoch 2026-11-17 20:19 UTC, 166,226 element sets for the thirteen satellites. Arc list: `ids_truth_set/ids_quiet.csv`; per-window maneuver list: `ids_truth_set/ids_truth.csv`; per-pseudo-window and per-window outputs: `data/benchmark/paperA_rv1_pseudo_steps.csv`, `paperA_rv1_jason3_det.csv`, `paperA_rv1_dv_vector.csv`.

**Table S7 — Satellites, identifiers and arc periods** (ordered by σ_res).

| satellite | NORAD | IDS identifier | arc period (TAI dates) | arcs listed | arcs used | TLEs used |
|---|---|---|---|--:|--:|--:|
| Sentinel-3A | 41335 | SEN3A | 2016-02-26 – 2026-09-11 | 147 | 140 | 11,973 |
| Jason-3 | 41240 | JASO3 | 2016-01-22 – 2026-08-06 | 69 | 59 | 7,963 |
| SWOT | 54754 | SWOT1 | 2023-01-15 – 2026-08-20 | 63 | 50 | 2,853 |
| Sentinel-3B | 43437 | SEN3B | 2018-05-04 – 2026-08-26 | 135 | 115 | 5,411 |
| Jason-2 | 33105 | JASO2 | 2008-06-25 – 2019-09-29 | 71 | 54 | 5,688 |
| Sentinel-6A | 46984 | SEN6A | 2020-11-24 – 2026-08-27 | 26 | 23 | 3,975 |
| Jason-1 | 26997 | JASO1 | 2001-12-11 – 2013-06-13 | 90 | 67 | 4,451 |
| HY-2D | 48621 | HY-2D | 2021-06-18 – 2026-08-14 | 45 | 45 | 5,639 |
| HY-2C | 46469 | HY-2C | 2020-10-21 – 2026-08-04 | 47 | 47 | 6,518 |
| CryoSat-2 | 36508 | CRYO2 | 2010-04-15 – 2026-08-06 | 227 | 201 | 9,949 |
| SARAL | 39086 | SARAL | 2013-02-27 – 2026-07-02 | 62 | 47 | 8,994 |
| Envisat | 27386 | ENVI1 | 2002-04-19 – 2012-04-05 | 155 | 140 | 9,431 |
| HY-2A | 37781 | HY-2A | 2011-09-28 – 2020-06-09 | 56 | 56 | 8,449 |

## Section S6. Non-overlapping subsets and held-out transfer of the empirical thresholds (main Section 3.3)

Non-overlapping subset: within each arc, pseudo-windows are retained in time order only if the full bracket support of the retained window (2.5 h + 2 × 3 d = 6.1 d) does not overlap that of the previous retained window. Cross-validation: arcs are randomly assigned to five folds; the 99th percentile is estimated from the other four folds and its exceedance counted on the held-out fold, pooled over folds. Chronological split: arcs are ordered by start time and split by count (not elapsed time or window count); the earlier half calibrates the 99th percentile and the later half validates it. Intervals: 95% nested arc bootstrap (calibration arcs resampled and the threshold re-estimated; validation arcs resampled). A second random fold assignment (main Section 3.3) gives 1.0–1.3% for twelve satellites and 3.6% for SARAL; the fold partition affects the per-satellite rates.

**Table S8 — Non-overlapping false-alarm probabilities and held-out exceedance** (ordered by σ_res; rates in %). Non-overlap: windows of the non-overlapping subset and their false-alarm probabilities at 3σ_res and at the all-window q99 of Table 2. 5-fold: exceedances / held-out windows, pooled over folds (fold-level q99 and counts in `paperA_reviewV1.json`, key rv3.cvfold). Chronological: cut date (first epoch of the validation arcs), calibration/validation arc counts, exceedances / validation windows, and the nested arc-bootstrap interval, in which the threshold is re-estimated on resampled calibration arcs. Zero observed exceedances yield an interval degenerate at zero when no resampled arc contains an exceedance; such intervals are not interpreted as evidence of zero future false-alarm probability.

| satellite | non-overlap windows | FAP 3σ_res | FAP q99 | 5-fold | cut date | arcs | later exceedance | nested CI |
|---|--:|--:|--:|--:|---|--:|--:|--:|
| Sentinel-3A | 487 | 92.2 | 1.2 | 59/5465 (1.1) | 2023-05-20 | 65/66 | 195/1303 (15.0) | 5.3–39.1 |
| Jason-3 | 534 | 21.3 | 2.4 | 65/6421 (1.0) | 2022-12-17 | 29/29 | 53/2048 (2.6) | 0.0–35.6 |
| SWOT | 165 | 96.4 | 2.4 | 25/1661 (1.5) | 2024-08-27 | 26/26 | 0/1032 (0.0) | 0.0–2.3 |
| Sentinel-3B | 368 | 66.6 | 1.1 | 42/3960 (1.1) | 2023-10-02 | 55/56 | 220/1119 (19.7) | 11.9–41.3 |
| Jason-2 | 527 | 15.6 | 3.0 | 55/5279 (1.0) | 2014-07-14 | 27/27 | 0/2506 (0.0) | degenerate at 0 |
| Sentinel-6A | 301 | 4.0 | 0.3 | 40/3646 (1.1) | 2023-08-07 | 11/11 | 0/2008 (0.0) | degenerate at 0 |
| Jason-1 | 502 | 10.6 | 2.8 | 45/4183 (1.1) | 2007-08-26 | 34/34 | 15/1617 (0.9) | 0.1–2.2 |
| HY-2D | 258 | 37.6 | 3.5 | 41/3055 (1.3) | 2024-02-24 | 22/23 | 7/1468 (0.5) | 0.0–1.2 |
| HY-2C | 289 | 36.0 | 3.1 | 41/3433 (1.2) | 2024-01-02 | 23/24 | 6/1540 (0.4) | 0.0–1.2 |
| CryoSat-2 | 697 | 40.0 | 1.7 | 82/7138 (1.1) | 2020-03-02 | 99/100 | 459/2998 (15.3) | 7.2–25.2 |
| SARAL | 642 | 26.0 | 2.0 | 241/7598 (3.2) | 2015-04-14 | 23/23 | 2/7450 (0.0) | 0.0–0.1 |
| Envisat | 452 | 27.0 | 2.6 | 51/4960 (1.0) | 2007-10-28 | 64/65 | 3/2006 (0.1) | 0.0–0.6 |
| HY-2A | 436 | 8.0 | 2.3 | 73/5124 (1.4) | 2015-07-19 | 27/27 | 14/2849 (0.5) | 0.0–1.6 |

## Section S7. FORMOSAT-7 clustered negative differences and gaps in the retrieved TLE series (main Section 5.3)

For each satellite and cluster, the largest negative adjacent difference in the cluster period is listed with the epochs of the element sets before and after it; these epochs bracket, but are not, any physical event time. Rates are linear SMA rates (± standard error; number of element sets) over the 10 days before and after the gap. R = Δa_raw − ½(ȧ_pre + ȧ_post)Δt is a retrospective correction using data on both sides of the gap; R_pre = Δa_raw − ȧ_pre·Δt uses pre-gap data only. In the archive, element sets with epochs from 12 to 17 April 2026 exist for 973 objects, compared with 29,421 for 1–6 April 2026; the first post-gap FORMOSAT-7 element sets were downloaded on 2 May 2026. Output: `data/benchmark/paperA_rv3_fs7_gap.csv`.

**Table S9 — Event matrix of the clustered negative differences** (satellite: FORMOSAT-7 number).

| sat. | cluster | epoch before (UTC) | epoch after (UTC) | gap (d) | raw (m) | ȧ_pre (m/d) | ȧ_post (m/d) | R (m) | R_pre (m) |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| 7-1 | Jan | 2025-12-30 13:08 | 2026-01-01 06:41 | 1.73 | -62.4 | -25.2 ± 0.6 (24) | -28.6 ± 0.5 (28) | -15.9 | -18.7 |
| 7-1 | Mar/Apr | 2026-03-29 00:35 | 2026-03-31 23:01 | 2.93 | -74.7 | -17.6 ± 0.1 (29) | -20.4 ± 0.8 (24) | -18.9 | -23.0 |
| 7-1 | Apr | 2026-04-11 10:18 | 2026-04-18 05:34 | 6.80 | -61.2 | -19.0 ± 0.8 (25) | -14.3 ± 0.5 (25) | +51.9 | +67.7 |
| 7-1 | Jun | 2026-06-01 05:51 | 2026-06-06 04:16 | 4.93 | -84.7 | -16.1 ± 0.3 (23) | -13.5 ± 0.1 (26) | -11.5 | -5.1 |
| 7-2 | Jan | 2025-12-30 20:36 | 2026-01-01 15:45 | 1.80 | -64.7 | -26.3 ± 0.6 (30) | -25.4 ± 0.5 (25) | -18.2 | -17.3 |
| 7-2 | Mar/Apr | 2026-03-29 01:39 | 2026-04-01 00:05 | 2.93 | -73.2 | -19.2 ± 0.1 (32) | -20.2 ± 0.6 (28) | -15.4 | -16.9 |
| 7-2 | Apr | 2026-04-11 17:47 | 2026-04-17 14:37 | 5.87 | -51.3 | -18.5 ± 0.5 (30) | -12.1 ± 0.4 (24) | +38.4 | +57.0 |
| 7-2 | Jun | 2026-06-02 11:44 | 2026-06-06 11:45 | 4.00 | -59.4 | -19.2 ± 0.2 (25) | -11.9 ± 0.1 (17) | +2.7 | +17.3 |
| 7-3 | Jan | 2025-12-30 20:04 | 2026-01-01 00:39 | 1.19 | -60.4 | -41.1 ± 0.7 (27) | -35.5 ± 0.9 (22) | -14.7 | -11.4 |
| 7-3 | Mar/Apr | 2026-03-29 03:12 | 2026-03-31 21:51 | 2.78 | -126.5 | -33.6 ± 0.3 (25) | -37.7 ± 1.2 (21) | -27.5 | -33.2 |
| 7-3 | Apr | 2026-04-11 19:40 | 2026-04-17 16:52 | 5.88 | -90.3 | -35.3 ± 1.3 (21) | -22.7 ± 0.6 (20) | +80.2 | +117.4 |
| 7-3 | Jun | 2026-06-01 10:53 | 2026-06-05 14:49 | 4.16 | -121.8 | -31.8 ± 0.5 (22) | -21.6 ± 0.3 (23) | -10.7 | +10.4 |
| 7-4 | Jan | 2025-12-30 15:16 | 2026-01-01 13:36 | 1.93 | -74.2 | -25.4 ± 0.6 (29) | -25.8 ± 0.5 (23) | -24.8 | -25.2 |
| 7-4 | Mar/Apr | 2026-03-29 04:19 | 2026-03-31 18:44 | 2.60 | -61.0 | -18.6 ± 0.2 (27) | -22.6 ± 0.7 (27) | -7.4 | -12.5 |
| 7-4 | Apr | 2026-04-11 14:02 | 2026-04-17 18:53 | 6.20 | -50.2 | -20.0 ± 0.7 (27) | -12.5 ± 0.5 (23) | +50.4 | +73.7 |
| 7-4 | Jun | 2026-06-02 07:59 | 2026-06-04 20:48 | 2.53 | -39.8 | -16.9 ± 0.2 (19) | -12.9 ± 0.2 (12) | -2.1 | +3.0 |
| 7-5 | Jan | 2025-12-30 13:40 | 2026-01-01 02:26 | 1.53 | -59.7 | -28.0 ± 0.6 (27) | -26.3 ± 0.8 (24) | -18.2 | -16.8 |
| 7-5 | Mar/Apr | 2026-03-29 02:43 | 2026-04-01 01:08 | 2.93 | -71.4 | -16.8 ± 0.1 (21) | -21.9 ± 0.7 (24) | -14.6 | -22.1 |
| 7-5 | Apr | 2026-04-11 01:14 | 2026-04-17 20:29 | 6.80 | -64.3 | -21.0 ± 0.7 (24) | -14.0 ± 0.5 (23) | +54.9 | +78.7 |
| 7-5 | Jun | 2026-06-02 19:11 | 2026-06-05 04:48 | 2.40 | -40.5 | -19.3 ± 0.3 (25) | -14.4 ± 0.2 (22) | -0.0 | +6.0 |
| 7-6 | Jan | 2025-12-30 11:01 | 2026-01-01 04:34 | 1.73 | -68.3 | -26.9 ± 0.6 (29) | -29.0 ± 0.6 (35) | -19.9 | -21.8 |
| 7-6 | Mar/Apr | 2026-03-28 20:51 | 2026-04-01 04:53 | 3.33 | -68.8 | -18.3 ± 0.1 (25) | -20.6 ± 0.6 (24) | -4.0 | -7.9 |
| 7-6 | Apr | 2026-04-11 12:59 | 2026-04-17 21:02 | 6.34 | -58.0 | -18.6 ± 0.6 (23) | -13.6 ± 0.6 (16) | +44.0 | +59.7 |
| 7-6 | Jun | 2026-06-01 03:43 | 2026-06-06 08:33 | 5.20 | -91.1 | -16.4 ± 0.3 (27) | -14.4 ± 0.1 (18) | -11.1 | -6.0 |

## Section S8. Altitude-model data and model comparison (main Sections 2.7 and 3.6)

Self-consistency scale: robust spread within sliding 40-TLE windows after linear detrending, excluding steps larger than 0.3 km, median over windows. Altitude: a − 6378.137 km, consistent with Table 1 (the source table used 6371 km; values here are converted). The source table is rounded to 0.01 m; the 3 values below 0.02 m (0.00, 0.01 and 0.01 m) are set to 0.02 m. Floor sensitivity: σ₀ = 0.0454, 0.0379 and 0.0359 m and H = 77.33, 77.41 and 77.57 km for floors of 0.02, 0.01 and 0.005 m. Model comparison: log10 σ with independent Gaussian errors and common variance; parameters re-estimated by ordinary least squares (maximum likelihood); the variance is counted as a parameter (k = 2, 5 and 4 for the constant, per-group and altitude models). AIC: constant -0.8, per-group -117.9, altitude -118.4 (least-squares H = 79.0 km). Data: `data/benchmark/tle_noise_floor_map.csv` (59 listed objects; 3 Starlink satellites near 358 km without a valid estimate are omitted).

**Table S10 — The 56 satellites of the altitude model.**

| group | NORAD | altitude (km) | inclination (deg) | self-consistency scale (m) | TLEs |
|---|---|--:|--:|--:|--:|
| 14 altimetry (benchmark) | 36508 | 719 | 92.03 | 0.18 | 12,441 |
| 14 altimetry (benchmark) | 27386 | 766 | 98.38 | 0.21 | 27,929 |
| 14 altimetry (benchmark) | 39086 | 785 | 98.55 | 0.06 | 11,083 |
| 14 altimetry (benchmark) | 41335 | 803 | 98.62 | 0.06 | 16,148 |
| 14 altimetry (benchmark) | 43437 | 803 | 98.63 | 0.14 | 6,734 |
| 14 altimetry (benchmark) | 54754 | 893 | 77.61 | 0.09 | 4,242 |
| 14 altimetry (benchmark) | 46469 | 952 | 66.00 | 0.02 | 12,022 |
| 14 altimetry (benchmark) | 48621 | 952 | 66.00 | 0.02 | 10,946 |
| 14 altimetry (benchmark) | 37781 | 968 | 99.33 | 0.06 | 21,327 |
| 14 altimetry (benchmark) | 33105 | 1311 | 66.04 | 0.07 | 12,543 |
| 14 altimetry (benchmark) | 26997 | 1325 | 66.04 | 0.08 | 12,967 |
| 14 altimetry (benchmark) | 22076 | 1338 | 66.04 | 0.05 | 17,515 |
| 14 altimetry (benchmark) | 41240 | 1338 | 66.04 | 0.06 | 10,145 |
| 14 altimetry (benchmark) | 46984 | 1338 | 66.04 | 0.05 | 5,018 |
| 9 hold-out (SPOT/GRACE/S6B) | 27391 | 463 | 89.01 | 2.41 | 8,502 |
| 9 hold-out (SPOT/GRACE/S6B) | 27392 | 463 | 89.01 | 2.26 | 8,324 |
| 9 hold-out (SPOT/GRACE/S6B) | 43476 | 489 | 88.99 | 0.52 | 8,188 |
| 9 hold-out (SPOT/GRACE/S6B) | 43477 | 489 | 88.99 | 0.51 | 8,185 |
| 9 hold-out (SPOT/GRACE/S6B) | 20436 | 687 | 98.70 | 0.46 | 31,356 |
| 9 hold-out (SPOT/GRACE/S6B) | 27421 | 825 | 98.59 | 0.32 | 28,440 |
| 9 hold-out (SPOT/GRACE/S6B) | 25260 | 825 | 98.61 | 0.30 | 29,771 |
| 9 hold-out (SPOT/GRACE/S6B) | 22823 | 830 | 98.68 | 0.15 | 24,671 |
| 9 hold-out (SPOT/GRACE/S6B) | 66514 | 1338 | 66.04 | 0.02 | 1,275 |
| FORMOSAT-7 (calibration) | 44343 | 540 | 24.00 | 2.46 | 1,950 |
| FORMOSAT-7 (calibration) | 44351 | 544 | 24.00 | 2.21 | 2,285 |
| FORMOSAT-7 (calibration) | 44358 | 550 | 24.00 | 2.66 | 1,961 |
| FORMOSAT-7 (calibration) | 44350 | 550 | 24.00 | 2.63 | 1,984 |
| FORMOSAT-7 (calibration) | 44349 | 550 | 24.00 | 2.64 | 1,954 |
| FORMOSAT-7 (calibration) | 44353 | 550 | 24.00 | 2.25 | 1,963 |
| Starlink sample (train domain) | 65082 | 463 | 53.16 | 15.67 | 422 |
| Starlink sample (train domain) | 66625 | 463 | 53.16 | 12.95 | 431 |
| Starlink sample (train domain) | 64740 | 463 | 53.16 | 12.00 | 420 |
| Starlink sample (train domain) | 66010 | 463 | 53.16 | 14.74 | 422 |
| Starlink sample (train domain) | 62311 | 463 | 53.16 | 13.74 | 421 |
| Starlink sample (train domain) | 69141 | 466 | 97.28 | 9.87 | 333 |
| Starlink sample (train domain) | 67601 | 466 | 97.28 | 13.96 | 451 |
| Starlink sample (train domain) | 48483 | 471 | 53.16 | 15.65 | 394 |
| Starlink sample (train domain) | 60130 | 471 | 53.16 | 9.44 | 418 |
| Starlink sample (train domain) | 67877 | 473 | 53.16 | 18.68 | 429 |
| Starlink sample (train domain) | 64919 | 475 | 53.16 | 14.00 | 411 |
| Starlink sample (train domain) | 64281 | 475 | 53.16 | 15.64 | 420 |
| Starlink sample (train domain) | 66189 | 475 | 53.16 | 15.37 | 414 |
| Starlink sample (train domain) | 57848 | 475 | 53.16 | 9.70 | 431 |
| Starlink sample (train domain) | 66854 | 483 | 43.00 | 14.99 | 377 |
| Starlink sample (train domain) | 68010 | 483 | 43.00 | 15.00 | 371 |
| Starlink sample (train domain) | 58069 | 483 | 43.00 | 6.77 | 373 |
| Starlink sample (train domain) | 59089 | 483 | 43.00 | 9.35 | 369 |
| Starlink sample (train domain) | 50177 | 486 | 53.16 | 4.07 | 449 |
| Starlink sample (train domain) | 53740 | 489 | 53.16 | 7.63 | 564 |
| Starlink sample (train domain) | 53779 | 514 | 53.16 | 5.90 | 447 |
| Starlink sample (train domain) | 52090 | 539 | 53.16 | 6.41 | 471 |
| Starlink sample (train domain) | 54067 | 540 | 53.16 | 3.22 | 470 |
| Starlink sample (train domain) | 49751 | 540 | 53.16 | 4.72 | 497 |
| Starlink sample (train domain) | 52138 | 540 | 53.16 | 5.29 | 459 |
| Starlink sample (train domain) | 63873 | 572 | 70.00 | 3.91 | 527 |
| Starlink sample (train domain) | 67200 | 572 | 70.00 | 3.41 | 514 |
