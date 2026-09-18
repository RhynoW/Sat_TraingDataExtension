"""multiseed_robustness.py — round5 review 要求之多 seed（10 個）穩健性統計。

對 train.py（Plan B, 20 特徵, class_weight=balanced）以 10 個不同隨機種子
各跑一次完整訓練（衛星層級分層切分種子 + LightGBM random_state 皆隨 --seed
連動），蒐集 test 分割（採 F-beta=0.5 最適閾值）之 Precision/Recall/F1/
AUC-ROC/PR-AUC，計算平均值與 95% CI（常態近似，n=10）。

每個 seed 的完整模型輸出（含 model.pkl）存於獨立子目錄
output/multiseed/seed_<N>/，避免覆蓋正式生產模型
（models_plan_b/lgbm_maneuver_v1.pkl 維持種子 42、不受本實驗影響）。
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT_ROOT = HERE / "output" / "multiseed"
SEEDS = [42, 0, 1, 7, 13, 99, 123, 2024, 314, 2718]

METRIC_KEYS = ["precision", "recall", "f1", "auc_roc", "avg_precision"]


def run_one(seed: int) -> dict | None:
    out_dir = OUT_ROOT / f"seed_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(HERE / "train.py"), "--seed", str(seed),
           "--out-dir", str(out_dir)]
    print(f"[seed={seed}] running: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[seed={seed}] FAILED (exit {proc.returncode})\n{proc.stderr[-3000:]}", flush=True)
        return None
    metrics_path = out_dir / "metrics.json"
    if not metrics_path.exists():
        print(f"[seed={seed}] metrics.json not found", flush=True)
        return None
    with open(metrics_path, encoding="utf-8") as fh:
        m = json.load(fh)
    # test@opt 若存在則優先採用（F-beta=0.5 最適閾值），否則退回 test（threshold=0.5）
    test_opt = next((r for r in m["results"] if r["split"] == "test@opt"), None)
    test_default = next((r for r in m["results"] if r["split"] == "test"), None)
    row = test_opt or test_default
    if row is None:
        print(f"[seed={seed}] no test split in results", flush=True)
        return None
    row = dict(row)
    row["seed"] = seed
    row["best_iteration"] = m["best_iteration"]
    row["threshold_used"] = "opt" if test_opt is not None else "default_0.5"
    return row


def main():
    rows = []
    for seed in SEEDS:
        r = run_one(seed)
        if r is not None:
            rows.append(r)
            print(f"[seed={seed}] test Precision={r['precision']:.4f} Recall={r['recall']:.4f} "
                  f"F1={r['f1']:.4f} AUC={r.get('auc_roc', float('nan')):.4f} "
                  f"best_iter={r['best_iteration']}", flush=True)

    if len(rows) < 2:
        print("Too few successful runs — aborting summary.", flush=True)
        raise SystemExit(1)

    df = pd.DataFrame(rows)
    df.to_csv(HERE / "output" / "multiseed_raw_results.csv", index=False)

    summary = []
    for k in METRIC_KEYS:
        if k not in df.columns:
            continue
        vals = df[k].dropna().values.astype(float)
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        se = std / np.sqrt(len(vals)) if len(vals) > 0 else 0.0
        ci95 = 1.96 * se
        summary.append({"metric": k, "n_seeds": len(vals), "mean": mean, "std": std,
                         "ci95_lo": mean - ci95, "ci95_hi": mean + ci95})

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(HERE / "output" / "multiseed_summary.csv", index=False)

    print("\n=== 多 seed（n=%d）test 分割穩健性統計（採各 seed 之最適閾值） ===" % len(rows), flush=True)
    print(summary_df.to_string(index=False), flush=True)
    print(f"\nbest_iteration 範圍: {df['best_iteration'].min()}–{df['best_iteration'].max()}"
          f"（原始 seed=42 生產模型: {df[df['seed'] == 42]['best_iteration'].iloc[0] if 42 in df['seed'].values else 'N/A'}）",
          flush=True)
    print(f"\nsaved -> {HERE / 'output' / 'multiseed_raw_results.csv'}")
    print(f"saved -> {HERE / 'output' / 'multiseed_summary.csv'}")


if __name__ == "__main__":
    main()
