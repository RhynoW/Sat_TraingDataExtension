# LEO Satellite Orbital Maneuver Detection Pipeline

A two-paper research pipeline for detecting and classifying orbital maneuvers in Low Earth Orbit (LEO) satellites using publicly available TLE (Two-Line Element) data.

---

## Papers

### Paper 1 — TLE Differential Maneuver Detection Algorithm

Detects orbital maneuvers from consecutive TLE pairs using Keplerian element differences (Δa, Δi, Δe, ΔRAAN) with four algorithmic improvements:

| Improvement | Description | Effect |
|-------------|-------------|--------|
| **P1** — Monotonic decay suppression + spike rescue | Suppresses atmospheric drag false positives; preserves active deorbit satellites | FP: 68 → 41 (−40%) |
| **P2** — Adaptive Δa threshold | Altitude-dependent threshold (<400 km: 2.0 km; >600 km: 0.5 km) | FP: 41 → 27 (−34%) |
| **P3** — B\* auxiliary condition | Relaxes monotone threshold for high-drag satellites (bstar_mean > 5×10⁻⁴) | FP: 27 → 25 (−7%) |
| **P4** — 4×7-day multi-window | Supplementary rolling-window detection for missed maneuvers | TP: +26 new detections |

**Final metrics** (14,019 LEO satellites, 30-day window, 2026-05-01 to 2026-05-30):

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

Trains a LightGBM binary classifier on 22 satellite-level aggregate features extracted from 30-day TLE observation windows. Uses satellite-level stratified random split (70/15/15%) to prevent data leakage.

**Dataset (Plan B):** 14,019 satellites × 22 features, class ratio ≈ 1:11.5 (1,127 positive / 12,892 negative), **30-day observation window** (2026-05-01 to 2026-05-30)

**Results:**

| Model | Precision | Recall | F1 | AUC-ROC |
|-------|-----------|--------|----|---------|
| Naive threshold (flag_rate > 5%) | 64.7% | 32.5% | 43.3% | 0.974 |
| Random Forest (300 trees) | 66.4% | 99.4% | 79.6% | 0.988 |
| XGBoost (300 trees) | 64.3% | 98.2% | 77.8% | 0.990 |
| **LightGBM (ours, 561 trees)** | **81.6%** | **68.0%** | **74.2%** | **0.990** |

LightGBM achieves the highest precision (+15–17 pp over RF/XGBoost), making it best suited for precision-critical space situational awareness applications where false-alarm cost is high.

**SHAP Top-5 features** (mean |SHAP value|, 30-day model):

| Rank | Feature | Contribution | Physical Meaning |
|------|---------|-------------|------------------|
| 1 | `flag_rate` | 42.6% | Flagging rate — dominant signal in 30-day window |
| 2 | `max_di_deg` | 6.8% | Max inclination change (requires active thrust) |
| 3 | `mean_tle_gap_h` | 6.4% | TLE update frequency (active satellites updated more often) |
| 4 | `max_draan_res_deg` | 6.2% | Max J2-corrected RAAN anomaly |
| 5 | `alt_km` | 5.8% | Orbital altitude (affects drag/noise floor) |

Three features (`inc_family_enc`, `n_tle`, `burn_freq_per_day`) contribute 0% and can be removed in future versions.

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
│   ├── compare_models.py           # Multi-model comparison (RF / XGBoost / LightGBM)
│   ├── analyze_plan_b_model.py     # SHAP + feature importance + external validation
│   ├── predict.py                  # Inference (--plan-b flag)
│   ├── verify_paper2.py            # Independent metric verification
│   ├── models_plan_b/              # Saved model artifacts
│   │   ├── lgbm_maneuver_v1.pkl    # 30-day model, 561 trees
│   │   ├── feature_names.json      # 22 features
│   │   └── threshold.json          # Optimal threshold: 0.8901 (F-beta=0.5)
│   └── output/
│       ├── shap_summary_bar.png    # SHAP bar chart
│       ├── shap_beeswarm.png       # SHAP beeswarm plot
│       ├── roc_comparison.png      # Multi-model ROC curves
│       └── model_comparison.csv    # Comparison table
│
├── docs/                           # Papers, STEM materials & figures
│   │
│   ├── paper1_tle_maneuver_detection_zh.md   # 論文一（中文）
│   ├── paper2_lightgbm_classifier_zh.md      # 論文二（中文）
│   │
│   ├── stem_paper1_tle_detection.md          # STEM 教材：論文一（高中生版）
│   ├── stem_paper2_lightgbm.md               # STEM 教材：論文二（高中生版）
│   │
│   ├── generate_paper1_figures.py  # 產生論文一全部 6 張圖的腳本
│   ├── generate_paper2_figures.py  # 產生論文二全部 6 張圖的腳本
│   │
│   ├── fig1_orbital_geometry.png   # 軌道根數幾何示意圖
│   ├── fig2_timeseries.png         # 半長軸時序三種典型模式
│   ├── fig3_flowchart.png          # P1–P4 偵測流程圖
│   ├── fig4_p2_threshold.png       # P2 高度自適應閾值示意
│   ├── fig5_ablation.png           # 消融實驗柱狀圖
│   ├── fig6_fp_waterfall.png       # 假陽性縮減瀑布圖
│   ├── paper2_fig1_ml_pipeline.png     # ML 訓練流程圖
│   ├── paper2_fig2_class_imbalance.png # 不平衡資料分布圖
│   ├── paper2_fig3_shap_importance.png # SHAP 特徵重要性條形圖
│   ├── paper2_fig4_confusion_matrix.png# 混淆矩陣熱力圖
│   ├── paper2_fig5_roc_comparison.png  # ROC 曲線與 P/R 對比
│   └── paper2_fig6_training_curve.png  # 早停訓練曲線
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

## Reproducing Paper 1 Results

### P1–P4 ablation (requires space_db.duckdb)
```bash
# Full detection pipeline (30-day window: 2026-05-01 to 2026-05-30)
python leo_annotator/validate_annotations.py

# Static ablation from existing CSV
python leo_annotator/ablation_study.py

# P2/P3 precise ablation (runs 2 additional DuckDB queries, ~20 min)
python leo_annotator/p2p3_ablation.py --run

# Regenerate all Paper 1 figures
python docs/generate_paper1_figures.py
```

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
# Converges at 561 trees (early stopping, patience=50)
# Saves model to models_plan_b/
```

### Step 3 — Reproduce all metrics
```bash
# Feature importance + SHAP + external validation (Plan A)
python analyze_plan_b_model.py

# Multi-model comparison (RF / XGBoost / LightGBM)
python compare_models.py

# Independent metric verification (all checks should PASS)
python verify_paper2.py

# Regenerate all Paper 2 figures
python ../docs/generate_paper2_figures.py
```

### Step 4 — Inference on new satellites
```bash
python predict.py --plan-b --norad 67788
```

---

## STEM Education Materials

High-school-level explainers for both papers, suitable for STEM classroom use:

| File | Content | Target Audience |
|------|---------|-----------------|
| [`docs/stem_paper1_tle_detection.md`](docs/stem_paper1_tle_detection.md) | TLE format, P1–P4 logic with analogies, full ablation table, 5 discussion questions | High school (grades 10–12) |
| [`docs/stem_paper2_lightgbm.md`](docs/stem_paper2_lightgbm.md) | Machine learning concepts, SHAP explainability, model comparison, 5 think-aloud questions | High school (grades 10–12) |

---

## Academic Papers (Chinese)

Full conference-paper-format manuscripts targeting AIAA/IAC 2026:

| File | Title | Key Contribution |
|------|-------|-----------------|
| [`docs/paper1_tle_maneuver_detection_zh.md`](docs/paper1_tle_maneuver_detection_zh.md) | 基於TLE差分分析與多級抑制策略的LEO衛星機動自動偵測 | P1–P4 multi-level suppression framework; FP reduced 68→29 (−57%) |
| [`docs/paper2_lightgbm_classifier_zh.md`](docs/paper2_lightgbm_classifier_zh.md) | 基於LightGBM與SHAP可解釋性的衛星機動行為自動分類 | 22-feature classifier; Precision 81.6%, AUC-ROC 0.990 |

Both papers include 6 figures and 3–6 tables each, generated by scripts in `docs/`.

---

## Data Notes

- **GT labels** (`propulsion_class`): manually annotated from public satellite catalogs (UCS, Discos). Classes: `Electric_EP`, `Chemical`, `Micro/ColdGas`, `Hybrid/Other`, `passive`.
- **Training labels** (`label_binary`): derived from TLE-detected maneuvers via `validate_annotations.py` (P1–P4), not from GT propulsion class.
- **Observation window**: 2026-05-01 to 2026-05-30 (30 days).
- **Note on 30-day vs 26-day model**: The 30-day window model shows slightly lower precision (81.6% vs 85.6%) compared to the 26-day version, because 4 extra quiet days dilute the maneuver signal in aggregate features. The P1–P4 detection results (ablation table) are unchanged between the two windows.
- `space_db.duckdb` is excluded from this repository (private TLE archive, ~10 GB).

---

## Citation

> [Paper title and venue TBD — submitted to AIAA/IAC 2026]
