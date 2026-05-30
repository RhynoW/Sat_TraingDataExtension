# LEO Satellite Orbital Maneuver Detection Pipeline

A two-paper research pipeline for detecting and classifying orbital maneuvers in Low Earth Orbit (LEO) satellites using publicly available TLE (Two-Line Element) data.

---

## Papers

### Paper 1 — TLE Differential Maneuver Detection Algorithm

Detects orbital maneuvers from consecutive TLE pairs using Keplerian element differences (Δa, Δi, Δe, ΔRAAN) with four algorithmic improvements:

| Improvement | Description | Effect |
|-------------|-------------|--------|
| **P1** — Monotonic decay suppression | Suppresses false positives from atmospheric drag | FP: 68 → 41 (−40%) |
| **P2** — Adaptive Δa threshold | Altitude-dependent threshold (<400 km: 2.0 km; >600 km: 0.5 km) | FP: 41 → 27 (−34%) |
| **P3** — B\* auxiliary condition | Relaxes monotone threshold for high-drag satellites | FP: 27 → 25 (−7%) |
| **P4** — 4×7-day multi-window | Supplementary rolling-window detection for missed maneuvers | TP: +26 new detections |

**Final metrics** (14,019 LEO satellites, 26-day window, 2026-05-01 to 2026-05-27):

| Configuration | TP | FP | Precision | Recall | F1 |
|--------------|----|----|-----------|--------|-----|
| Baseline (no improvements) | 1,245 | 68 | 94.8% | 12.2% | 21.7% |
| +P1 | 1,148 | 41 | 96.6% | 11.3% | 20.2% |
| +P1+P2 | 1,111 | 27 | 97.6% | 10.9% | 19.6% |
| +P1+P2+P3 | 1,102 | 25 | 97.8% | 10.8% | 19.5% |
| **Full P1–P4** | **1,128** | **29** | **97.5%** | **11.1%** | **19.9%** |

**Key files:** `leo_annotator/validate_annotations.py`, `leo_annotator/ablation_study.py`, `leo_annotator/p2p3_ablation.py`

---

### Paper 2 — LightGBM Orbital Maneuver Behavior Classifier

Trains a LightGBM binary classifier on 22 satellite-level aggregate features extracted from 26-day TLE observation windows. Uses a satellite-level stratified random split to prevent data leakage.

**Dataset (Plan B):** 14,019 satellites × 22 features, class ratio ≈ 1:11.5 (1,127 positive), **30-day observation window** (2026-05-01 to 2026-05-30)

**Results:**

| Model | Precision | Recall | F1 | AUC-ROC |
|-------|-----------|--------|----|---------|
| Naive threshold (flag_rate > 0.05) | 64.7% | 32.5% | 43.3% | 0.974 |
| Random Forest | 66.4% | 99.4% | 79.6% | 0.988 |
| XGBoost | 64.3% | 98.2% | 77.8% | 0.990 |
| **LightGBM (ours)** | **81.6%** | **68.0%** | **74.2%** | **0.990** |

LightGBM achieves the highest precision (85.9%) and AUC-ROC (0.9934), making it best suited for precision-critical space situational awareness applications.

**SHAP Top-5 features** (mean |SHAP value|):

| Rank | Feature | Contribution | Physical Meaning |
|------|---------|-------------|------------------|
| 1 | `flag_rate` | 42.6% | Flagging rate — dominant signal in 30-day window |
| 2 | `max_di_deg` | 6.8% | Max inclination change (requires active thrust) |
| 3 | `mean_tle_gap_h` | 6.4% | TLE update frequency (active sats updated more often) |
| 4 | `max_draan_res_deg` | 6.2% | Max J2-corrected RAAN anomaly |
| 5 | `alt_km` | 5.8% | Orbital altitude (affects drag/noise floor) |

**Key files:** `Orbital_Maneuver_V2/`, `build_training_dataset.py`

---

## Repository Structure

```
.
├── leo_annotator/                  # Paper 1: TLE detection & ablation
│   ├── validate_annotations.py     # Main detection pipeline (P1–P4)
│   ├── ablation_study.py           # P1–P4 ablation from static CSV
│   ├── p2p3_ablation.py            # P2/P3 precise ablation (DuckDB re-run)
│   └── output/
│       ├── annotations_leo_full.csv    # GT propulsion class labels
│       └── ablation_results.csv        # Ablation study output
│
├── Orbital_Maneuver_V2/            # Paper 2: LightGBM classifier
│   ├── train.py                    # Training script
│   ├── dataset.py                  # Data loading & satellite-level split
│   ├── compare_models.py           # Multi-model comparison
│   ├── analyze_plan_b_model.py     # SHAP + feature importance + external validation
│   ├── predict.py                  # Inference (--plan-b flag)
│   ├── verify_paper2.py            # Independent metric verification
│   ├── models_plan_b/              # Saved model artifacts
│   │   ├── lgbm_maneuver_v1.pkl
│   │   ├── feature_names.json
│   │   └── threshold.json          # Optimal threshold: 0.9180
│   └── output/
│       ├── shap_summary_bar.png    # SHAP bar chart
│       ├── shap_beeswarm.png       # SHAP beeswarm plot
│       ├── roc_comparison.png      # Multi-model ROC curves
│       └── model_comparison.csv    # Comparison table
│
├── build_training_dataset.py       # Builds Plan B training dataset from TLE DB
├── download_TLE_unified.py         # TLE download pipeline (Space-Track API)
├── starlink_ephemeris/             # MEME ephemeris download & parsing
└── data/
    └── maneuvers/
        ├── training_samples_plan_b.csv      # Plan B: 14,019 rows × 33 cols
        └── training_dataset_final.parquet   # Combined Plan A+B (17,400 rows)
```

---

## Setup

```bash
pip install lightgbm scikit-learn pandas numpy duckdb joblib shap xgboost matplotlib skyfield
```

**Requires:** A local `space_db.duckdb` database populated via `download_TLE_unified.py` (Space-Track account needed). See `config_spacetrack.py` for credentials setup.

---

## Reproducing Paper 2 Results

### Step 1 — Build training dataset
```bash
python build_training_dataset.py --plan b
```

### Step 2 — Train LightGBM
```bash
cd Orbital_Maneuver_V2
python train.py
# Saves model to models_plan_b/
```

### Step 3 — Reproduce all metrics
```bash
# Feature importance + SHAP + external validation
python analyze_plan_b_model.py

# Multi-model comparison (RF / XGBoost / LightGBM)
python compare_models.py

# Independent metric verification
python verify_paper2.py
```

### Step 4 — Inference on new satellites
```bash
python predict.py --plan-b --norad 67788
```

---

## Reproducing Paper 1 Results

### P1–P4 ablation (requires space_db.duckdb)
```bash
# Full detection pipeline
python leo_annotator/validate_annotations.py

# Static ablation from existing CSV
python leo_annotator/ablation_study.py

# P2/P3 precise ablation (runs 2 additional DuckDB queries, ~20 min)
python leo_annotator/p2p3_ablation.py --run
```

---

## Data Notes

- **GT labels** (`propulsion_class`): manually annotated from public satellite catalogs. Classes: `Electric_EP`, `Chemical`, `Micro/ColdGas`, `Hybrid/Other`, `passive`.
- **Training labels** (`label_binary`): derived from TLE-detected maneuvers via `validate_annotations.py`, not from GT propulsion class.
- **Observation window**: 2026-05-01 to 2026-05-27 (26 days).
- `space_db.duckdb` is excluded from this repository (private TLE archive, ~10 GB).

---

## Citation

> [Paper title and venue TBD — submitted to AIAA/IAC 2026]
