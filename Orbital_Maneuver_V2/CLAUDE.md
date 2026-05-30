# CLAUDE.md

## Goal
Build a TLE-based Starlink orbital maneuver detector trained on MEME ephemeris ground truth.

## Principles
- Be concise.
- Prefer direct answers and minimal necessary context.
- Avoid filler, repetition, and unnecessary explanations.
- Ask clarifying questions only when needed to proceed safely.
- Use the smallest relevant set of files, commands, and edits.

## Project understanding
- Learn the codebase structure before making changes.
- Read only the files needed for the current task.
- Prefer references to source-of-truth files over copying large explanations.

## Work style
- Make the simplest correct change.
- Keep edits focused and local.
- If a task needs project-specific instructions, look for a more specific markdown file first.
- Use tests, linters, and formatters to verify changes instead of re-checking by hand.

## Communication
- Reply in short, clear sentences.
- Give the result first.
- Include only actionable details.
- 請用繁體中文回答。

---

## Project context

### Problem statement
Detect satellite maneuver state from TLE archive alone (no MEME at inference time).
MEME is used only to generate labels during training.

### Data sources
| Source | Path | Role |
|---|---|---|
| TLE archive | `../space_db.duckdb` → `raw_tle_archive` | Features (training + inference) |
| MEME residuals | `../data/comparison/residuals_*.csv` | Labels (training only) |
| MEME summaries | `../data/comparison/summary_*.csv` | Satellite-level QC |
| Stale TLE report | `../data/comparison/stale_tle_report_*.csv` | Satellite filter list |

### residuals_*.csv schema (key columns)
```
norad_id, sat_name, t, pos_err_km, vel_err_kms,
dr_r_km, dr_t_km, dr_n_km,          # RTN residuals
tle_epoch, tle_age_days,
valid_for_training                    # bool: age<=2d AND pos_err<=50km
```

### Label classes
| Label | Source pattern | Filter |
|---|---|---|
| `nominal` | Mode C — low oscillation | `valid_for_training=True`, no MEME event ±24h |
| `maneuvering` | Mode B — V-shape spike | MEME Δv > threshold, followed by TLE recovery |
| *(excluded)* | Mode A — persistent diverge | `pos_err_km > 500` monotone rising; drop |

### Feature engineering rule
**Features must come from TLE only** (must be available at inference time).
MEME data is used only for label assignment — never as an input feature.

Key feature groups:
1. Per-TLE orbital elements: `sma_km`, `eccentricity`, `inclination_deg`, `bstar`
2. Consecutive-TLE deltas: `d_sma_km`, `d_inc_deg`, `d_raan_res_deg`, `tle_gap_hours`
3. Rolling-window stats (7-day): `sma_slope`, `sma_std`, `max_gap_h`, `tle_count`

### Reference files (read, do not copy)
- `../compare_tle_vs_ephemeris.py` — `_eci_to_elements`, `_j2_raan_drift`, `_parse_tle_at_epoch`, `detect_meme_maneuvers`, `propagate_with_best_tles`
- `../download_TLE_unified.py` — DuckDB schema, `raw_tle_archive` query patterns
- `../maneuver_app.py` — UI reference only

### Module layout
```
Orbital_Maneuver_V2/
├── CLAUDE.md              ← this file
├── data_loader.py         ← TLE + residuals I/O, feature extraction
├── labeler.py             ← MEME-derived label assignment
├── dataset.py             ← train/val/test split, class balancing
├── model.py               ← LightGBM baseline + optional GRU
├── train.py               ← CLI: python train.py
├── predict.py             ← CLI: python predict.py --norad XXXXX
├── evaluate.py            ← metrics: F1, AUC, lead-time
└── tests/
    ├── test_data_loader.py
    ├── test_labeler.py
    └── test_dataset.py
```

### Time-based train/val/test split (no random split — data leakage risk)
```
train : 2026-05-02 → 2026-05-15
val   : 2026-05-15 → 2026-05-20
test  : 2026-05-20 → 2026-05-25
```

### Key constants
```python
DB_PATH        = "../space_db.duckdb"
RESIDUALS_GLOB = "../data/comparison/residuals_*.csv"
LABEL_NOMINAL      = 0
LABEL_MANEUVERING  = 1
# Mode A rows are dropped, not labeled
VALID_TRAINING_AGE_DAYS = 2.0
VALID_TRAINING_POS_KM   = 50.0
MEME_EVENT_WINDOW_H     = 24      # label maneuvering within ±24h of MEME event
MODE_A_POS_THRESHOLD_KM = 500     # exclude if pos_err > this AND monotone rising
```
