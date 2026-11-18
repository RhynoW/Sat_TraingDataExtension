#!/usr/bin/env python3
"""產生論文可重現性套件之 SHA-256 清單（腳本＋衍生資料；圖檔不入列）。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FILES = [
    "fs7_injection_sweep.py", "fs7_injection_sweep_v2.py", "fs7_injection_sweep_v3.py",
    "fs7_injection_sweep_v4.py", "fs7_review3_analysis.py", "fs7_review4_analysis.py",
    "fs7_final_supplement.py", "fs7_campaign_truth_build.py", "fs7_tle_recall_unified.py",
    "fs7_noise_floor_map.py", "fs7_noise_floor_map_v2.py", "statistical_detectors.py",
    "data/benchmark/fs7_injection_trials.csv", "data/benchmark/fs7_injection_sweep.csv",
    "data/benchmark/fs7_injection_metrics.csv", "data/benchmark/fs7_injection_smear.csv",
    "data/benchmark/fs7_law_fit.json", "data/benchmark/fs7_law_fit_v3.json",
    "data/benchmark/fs7_law_fit_v4.json", "data/benchmark/fs7_review3_analysis.json",
    "data/benchmark/fs7_review4_analysis.json", "data/benchmark/fs7_final_supplement.json",
    "data/benchmark/fs7_review4b_analysis.json",
    "data/benchmark/fs7_events_campaigns_20260825.csv",
    "data/benchmark/fs7_tle_recall_unified_20260825.csv",
    "data/benchmark/tle_noise_floor_map.csv",
    # R1（審查回應）新增
    "fs7_review5_analysis.py", "docs/gen_fs7_supplement_r1.py",
    "data/benchmark/fs7_review5_analysis.json",
    "data/benchmark/fs7_review5_event_decomposition.csv",
    "data/benchmark/fs7_review5_threshold_sweep.csv",
    "data/benchmark/fs7_review5_recall_grid.csv",
    "data/space_weather/gfz_kp_3h_2024-04_05.csv",
    # R2 新增
    "fs7_review6_analysis.py", "fs7_repro_minimal.py", "docs/gen_fs7_supplement_r2.py",
    "docs/build_paperB_review_package.py",
    "data/benchmark/fs7_review6_analysis.json", "data/benchmark/fs7_review6_detector_sensitivity.csv",
    "data/benchmark/fs7_injection_trials_with_t0.csv", "data/benchmark/fs7_tle_epoch_list.csv",
    # 終審新增
    "fs7_review7_analysis.py", "docs/gen_fs7_supplement_r3.py", "data/benchmark/fs7_review7_analysis.json",
]

out = Path("data/benchmark/fs7_checksums_sha256.txt")
lines = []
for f in FILES:
    p = Path(f)
    if not p.exists():
        lines.append(f"MISSING  {f}")
        continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    lines.append(f"{h}  {f}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[:6]) + f"\n… 共 {len(lines)} 筆 → {out}")
