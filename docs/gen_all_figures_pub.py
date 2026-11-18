#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_all_figures_pub.py — 一次重產所有可重繪之報告／論文圖的四版本（中英 × 白底／黑底，600 dpi PNG＋PDF）。

輸出：docs/figures_pub/<stem>/<stem>_<lang>_<theme>.{png,pdf}；對照表見 docs/figures_pub/README.md。
各指令皆只讀快取 CSV（不連 space_db.duckdb、不重算），也不會覆寫 docs/fig_*.png 原檔。
用法：python docs/gen_all_figures_pub.py            （全部）
      python docs/gen_all_figures_pub.py sigma ids   （只跑名稱含任一關鍵字者）
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JOBS = [
    ["docs/gen_fig_system_flow.py", "--pub"],
    ["docs/gen_fig_sigma_vs_altitude.py", "--pub"],
    ["docs/gen_fig_nrlmsis_decay_expect.py", "--pub"],
    ["docs/analyze_perigee_drag_corr.py", "--pub", "--tag=x30"],
    ["docs/gen_fig_nrlmsis_solar_tracking.py", "--pub", "--tag=x30"],
    ["docs/gen_fig_fs7_precise_nrlmsis.py", "--pub"],
    ["verify_shenlong_2026_rpo.py", "--pub"],
    ["docs/study_drag_resid_threshold.py", "--pub"],
    ["docs/gen_fig_report_r_series.py"],          # 期末報告圖 4、5、11–17（需 space_db.duckdb，唯讀）
    ["ids_truth_set/ids_detection_curve.py", "--pub"],
    ["ids_truth_set/ids_dv_vector_validate.py", "--pub"],
    ["fs7_injection_sweep.py", "--pub"],
    ["fs7_injection_sweep_v3.py", "--pub"],
    ["fs7_noise_floor_map_v2.py", "--pub"],
]


def main():
    keys = [a for a in sys.argv[1:] if not a.startswith("-")]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("TAG", None)                       # 由各指令之 --tag= 決定，避免外部 TAG 干擾
    failed = []
    for job in JOBS:
        if keys and not any(k in job[0] for k in keys):
            continue
        print(f"== {' '.join(job)}", flush=True)
        r = subprocess.run([sys.executable, *job], cwd=ROOT, env=env)
        if r.returncode:
            failed.append(job[0])
    print("完成" if not failed else f"失敗：{failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
