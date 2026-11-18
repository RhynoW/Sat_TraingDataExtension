# Supplementary Material

for "Empirical Characterization of TLE-Derived Semi-Major-Axis Noise from DORIS-Certified Quiescent Arcs and Its Application to FORMOSAT Maneuver Analysis"

All values are reproduced by `docs/paperA_numbers.py` (output `data/benchmark/paperA_numbers.json`).

## Section S1. Sensitivity of the noise estimates to processing choices (main Section 3.2)

The estimation of Section 2 is repeated with one processing choice changed at a time from the baseline (thinning 3 h, trimming 0.75 d, polynomial degree rule unchanged), using the current version of the IDS arc list. The full 3 × 3 × 3 grid gives a median σ_diff of 0.218–0.285 m and a median σ_res of 0.56–0.89 m; twelve of thirteen satellites have σ_diff < 1 m in every configuration.

**Table S1 — One-at-a-time sensitivity of the thirteen-satellite noise estimates.**

| configuration | median σ_res (m) | median σ_diff (m) | max σ_diff (m) | satellites with σ_diff < 1 m | Spearman ρ (altitude, σ_diff) |
|---|--:|--:|--:|--:|--:|
| baseline (thinning 3 h, trimming 0.75 d, degree rule 0) | 0.754 | 0.241 | 1.24 | 12/13 | -0.64 |
| thinning 1.5 h | 0.739 | 0.218 | 1.21 | 12/13 | -0.49 |
| thinning 6 h | 0.739 | 0.285 | 1.37 | 12/13 | -0.61 |
| trimming 0.5 d | 0.766 | 0.241 | 1.24 | 12/13 | -0.64 |
| trimming 1.0 d | 0.732 | 0.241 | 1.24 | 12/13 | -0.57 |
| degree rule −1 | 0.861 | 0.241 | 1.24 | 12/13 | -0.64 |
| degree rule +1 | 0.602 | 0.241 | 1.24 | 12/13 | -0.64 |

## Section S2. Starlink-altitude noise estimates (main Section 3.3)

No certified quiescent arcs exist for Starlink. Table S2 lists the estimates available at Starlink altitude; they measure different quantities and are not interchangeable.

**Table S2 — Starlink-altitude estimates.**

| estimate | definition | value |
|---|---|---|
| TLE vs SpaceX ephemeris, all | |TLE-propagated SMA − ephemeris SMA|, 283 satellites, 35,460 daily samples, 2026-05-01 to 2026-09-20 | median 57.0 m; IQR 23.6–110.8 m; P90 191.6 m |
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

The self-consistency estimates change between data snapshots because the TLE archive used for Starlink is a rolling window; the quiescent-arc results of the main text are computed on fixed arcs. The filtered medians are an order-of-magnitude guide only: the ephemeris SMA is osculating, its J2 short-period amplitude at a = 6850 km is 6.43 km, and the median day-to-day truth SMA change (6486 m/day for the 152 satellites) is dominated by aliased short-period terms rather than thrust. Weekly median prediction error versus F10.7: Spearman ρ = 0.564 (p = 0.0078, 21 weeks); point-wise ρ = 0.063 (F10.7 at epoch) and -0.037 (change of F10.7 over the propagation).

## Section S3. FORMOSAT-7 statistics (main Section 5.3)

Period 2025-11-17 to 2026-11-18; adjacent |Δa| after removal of duplicate epochs.

**Table S3 — FORMOSAT-7 adjacent |Δa| statistics.**

| satellite | NORAD | median altitude (km) | median (m) | P90 (m) | P99 (m) | max (m) | steps > 50 m |
|---|---|--:|--:|--:|--:|--:|--:|
| FORMOSAT-7-1 (A) | 44349 | 577.2 | 4.78 | 16.67 | 46.12 | 6695.2 | 7 |
| FORMOSAT-7-2 (B) | 44351 | 577.2 | 4.84 | 16.84 | 38.23 | 9338.9 | 6 |
| FORMOSAT-7-3 (C) | 44343 | 537.6 | 8.59 | 30.03 | 52.61 | 126.5 | 12 |
| FORMOSAT-7-4 (D) | 44350 | 577.2 | 4.62 | 16.74 | 35.52 | 9354.7 | 4 |
| FORMOSAT-7-5 (E) | 44358 | 577.3 | 4.97 | 17.26 | 37.53 | 4217.5 | 6 |
| FORMOSAT-7-6 (F) | 44353 | 577.2 | 4.75 | 16.64 | 34.7 | 6561.9 | 6 |

**Table S4 — FORMOSAT-7 steps exceeding 50 m.**

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

Positive steps of kilometres on 19–27 January 2026 are the orbit raise of five satellites; negative steps of −50 to −127 m occurring on the same dates on all six satellites, including the non-maintained FORMOSAT-7-3, are treated as common-mode signatures (main Section 5.3).
