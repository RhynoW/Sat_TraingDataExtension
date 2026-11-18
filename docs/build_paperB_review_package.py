#!/usr/bin/env python3
"""
build_paperB_review_package.py — Paper B 匿名審稿資料包（R2）
============================================================
產出 dist/paperB_review_package_R2.zip，內容：
  · 全部分析腳本與圖腳本（保留相對路徑）
  · 衍生表（JSON/CSV；不含可重建之原始 TLE 內容）
  · TLE 曆元清單（NORAD × epoch；Space-Track 使用者協議允許之 metadata）
  · fs7_injection_trials_with_t0.csv（試驗表 + 窗起點曆元，供不連 DB 之最小重現）
  · README_REVIEW.md（最小重現流程、表格→檔案對照、授權限制）、MANIFEST_SHA256.txt
匿名檢查：所有文字檔掃描作者/路徑/電子郵件樣式，命中即中止。
用法：python docs/build_paperB_review_package.py
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist/paperB_review_package_R2"
CUTOFF = "2026-08-25"
NORADS = [44343, 44349, 44350, 44351, 44353, 44358]

SCRIPTS = [
    "fs7_injection_sweep.py", "fs7_injection_sweep_v2.py", "fs7_injection_sweep_v3.py", "fs7_injection_sweep_v4.py",
    "fs7_review3_analysis.py", "fs7_review4_analysis.py", "fs7_review4b_analysis.py", "fs7_review5_analysis.py",
    "fs7_review6_analysis.py", "fs7_review7_analysis.py", "fs7_final_supplement.py", "fs7_campaign_truth_build.py", "fs7_tle_recall_unified.py",
    "fs7_noise_floor_map.py", "fs7_noise_floor_map_v2.py", "fs7_make_checksums.py", "fs7_repro_minimal.py",
    "statistical_detectors.py",
    "formosat7_leoorb/__init__.py", "formosat7_leoorb/archive.py", "formosat7_leoorb/cli.py",
    "formosat7_leoorb/compare.py", "formosat7_leoorb/detect.py", "formosat7_leoorb/download.py",
    "formosat7_leoorb/merge.py", "formosat7_leoorb/satmap.py",
    "docs/fs7_supplement_tables.py", "docs/gen_fs7_supplement_r1.py", "docs/gen_fs7_supplement_r2.py", "docs/gen_fs7_supplement_r3.py",
    "docs/gen_fig_fs7_event_selection.py", "docs/gen_fig_fs7_injection_case.py", "docs/gen_fig_fs7_method_flow.py",
    "docs/gen_fig_fs7_model_supplement.py", "docs/gen_fig_fs7_real_event_recall.py",
    "docs/fig_pub.py", "docs/fs7_fig_style.py", "docs/fs7_env_freeze.txt", "docs/paper_fs7_repro_README.md",
    "docs/paper_fs7_supplement_EN.md",   # Supplementary Material (incl. Tables S1b, S44, S45–S48)
]
DATA_GLOBS = ["data/benchmark/fs7_*.csv", "data/benchmark/fs7_*.json", "data/benchmark/fs7_checksums_sha256.txt",
              "data/benchmark/tle_noise_floor_map.csv", "data/space_weather/gfz_kp_3h_2024-04_05.csv"]
DATA_EXCLUDE = {"fs7_review3_analysis_rerun.json",
                # 其他論文／研討會版之產物，非 Paper B 依賴
                "fs7_l3_ood_2025.csv", "fs7_precise_decay_windows.csv", "fs7_precise_nrlmsis_corr.csv",
                "fs7_tle_detection_2025.csv"}
FORBIDDEN = [r"[A-Za-z]:[\\/]+Users[\\/]", r"[\w.+-]+@[\w-]+\.(com|org|edu|tw|net)", r"rhynowu"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def derived_files():
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    ep = []
    starts = {}
    for nid in NORADS:
        df = con.execute("SELECT epoch_utc FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
                         "AND epoch_utc < ? ORDER BY epoch_utc", [nid, CUTOFF]).df().drop_duplicates("epoch_utc")
        df = df.reset_index(drop=True)
        starts[nid] = df["epoch_utc"].values
        ep.append(pd.DataFrame({"norad": nid, "epoch_utc": df["epoch_utc"]}))
    con.close()
    pd.concat(ep).to_csv(ROOT / "data/benchmark/fs7_tle_epoch_list.csv", index=False)
    tr = pd.read_csv(ROOT / "data/benchmark/fs7_injection_trials.csv")
    tr["win_t0"] = [pd.Timestamp(starts[n][int(w)]) for n, w in zip(tr.norad, tr.win_start)]
    tr.to_csv(ROOT / "data/benchmark/fs7_injection_trials_with_t0.csv", index=False)


README = """# Review package — FS7 detector-level TLE maneuver-detection sensitivity (R2)

This package accompanies the anonymized manuscript. It contains every analysis script, all derived tables, and
the metadata needed to rebuild the TLE data set. Raw TLEs are **not** included, as required by the Space-Track
user agreement.

## 1. Minimal reproduction (no Space-Track account, no database; ~5 s)

    pip install numpy pandas
    python fs7_repro_minimal.py

The script reproduces and checks the following against the manuscript values, and exits with code 0 if all checks pass:

- **Table 3:** held-out log loss and AUC of the drag-aware and amplitude-only models.
- **Table 4a:** interpolated 90% injection-recall amplitudes, all nine conditions.
- **Table 4:** real-event recall by amplitude bin at both thresholds.
- **Table 5:** rule-U and rule-S operating point at 45 m.

The supplementary Markdown sections can also be regenerated without a database:

    python docs/gen_fs7_supplement_r1.py     # Sections S11–S16
    python docs/gen_fs7_supplement_r2.py     # Section S17
    python docs/gen_fs7_supplement_r3.py     # Section S19

Figures can be regenerated from the cached CSVs with `--pub` (see `docs/paper_fs7_repro_README.md`).

## 2. Full reproduction (requires your own Space-Track credentials)

1. Rebuild the TLE archive for the epochs in `data/benchmark/fs7_tle_epoch_list.csv` (NORAD × epoch, before 2026-08-25).
2. Run the commands listed in `docs/paper_fs7_repro_README.md`, Section 3.

The following results need the TLE archive and cannot be reproduced from this package alone:

- the injection sweep (`fs7_injection_trials.csv` is provided as its output);
- the real-event residuals (`fs7_tle_recall_unified_20260825.csv` is provided);
- the pseudo-event draw;
- the R2 detector-parameter replay.

SP3 products are public (TACC) and can be downloaded with `python -m formosat7_leoorb.cli download`.

## 3. Where each main-text item comes from

See Table S1b of the Supplementary Material. In brief:

| item | file (key) |
|---|---|
| Table 2b, Table 6, Table 6a | `fs7_review5_analysis.json` (`selection_bias`, `miss_decomposition`); `fs7_review6_analysis.json` (`M1`, `M3`) |
| Table 3; §4.3 drag proxies (Table S43a) | `fs7_law_fit_v4.json`; `fs7_review5_analysis.json` (`heldout_auc`); `fs7_review6_analysis.json` (`M8`) |
| Table 4a | `fs7_review5_analysis.json` (`da90_interpolated`); `fs7_review5_recall_grid.csv` |
| Table 4 | `fs7_tle_recall_unified_20260825.csv` |
| Table 5 | `fs7_review5_analysis.json` (`symmetric_rules`); `fs7_review5_threshold_sweep.csv` |
| Section S17 | `fs7_review6_analysis.json`; `fs7_review6_detector_sensitivity.csv` |
| Section S19 (window covariates, overlap arcs, rule-S sign components) | `fs7_review7_analysis.json` |
| Table S44 (transfer conditions) and all supplementary tables | `docs/paper_fs7_supplement_EN.md` |

## 4. Integrity

`MANIFEST_SHA256.txt` lists the SHA-256 of every file in this package. Figures are excluded from checksumming
because matplotlib output depends on the backend; the CSV/JSON files underlying them are included.

## 5. Licences and restrictions

- **TLE data:** Space-Track user agreement; only epoch metadata is distributed.
- **SP3:** public TACC distribution.
- **Kp/F10.7:** GFZ Potsdam, CC BY 4.0 (Matzka et al., 2021).
"""


def main():
    derived_files()
    if OUT.exists():
        shutil.rmtree(OUT)
    files = [ROOT / f for f in SCRIPTS]
    for g in DATA_GLOBS:
        files += [p for p in sorted(ROOT.glob(g)) if p.name not in DATA_EXCLUDE]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        sys.exit(f"缺檔：{missing}")
    pat = re.compile("|".join(FORBIDDEN), re.I)
    for f in files:
        if f.suffix in (".py", ".md", ".txt", ".json", ".csv"):
            hit = pat.search(f.read_text(encoding="utf-8", errors="ignore"))
            if hit:
                sys.exit(f"匿名檢查失敗：{f.relative_to(ROOT)} 含 {hit.group(0)!r}")
        dst = OUT / f.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    (OUT / "README_REVIEW.md").write_text(README, encoding="utf-8", newline="\n")
    man = [f"{sha(p)}  {p.relative_to(OUT).as_posix()}" for p in sorted(OUT.rglob("*")) if p.is_file()]
    (OUT / "MANIFEST_SHA256.txt").write_text("\n".join(man) + "\n", encoding="utf-8", newline="\n")
    z = ROOT / "dist/paperB_review_package_R2.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(OUT.parent).as_posix())
    print(f"輸出：{z}（{len(man)} 檔，{z.stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
