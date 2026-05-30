#!/usr/bin/env python3
"""
p2p3_ablation.py
================
P2/P3 精確消融：分別以 --disable-p2 / --disable-p3 重跑 validate_annotations.py，
產生三份 CSV 後比較指標，精確量化 P2 和 P3 的獨立貢獻。

執行順序（3 次 DuckDB 查詢，各約 10 分鐘）：
  Config A : P1=ON  P2=OFF P3=OFF  → validation_full_p1only.csv
  Config B : P1=ON  P2=ON  P3=OFF  → validation_full_p1p2.csv
  Config C : P1=ON  P2=ON  P3=ON   → validation_full.csv (現有，不重跑)

用法：
  python leo_annotator/p2p3_ablation.py           # 僅比較（需先有 3 份 CSV）
  python leo_annotator/p2p3_ablation.py --run     # 重跑 Config A 和 B，再比較
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

_HERE   = Path(__file__).parent
OUT_DIR = _HERE / "output"

# 三份 CSV 路徑
CSV_A = OUT_DIR / "validation_full_p1only.csv"   # P1 only
CSV_B = OUT_DIR / "validation_full_p1p2.csv"     # P1+P2
CSV_C = OUT_DIR / "validation_full.csv"           # P1+P2+P3（現有）

GT_POSITIVE_CLASSES = {"Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"}
ANN_CSV = OUT_DIR / "annotations_leo_full.csv"


def _compute_metrics(val: pd.DataFrame, ann: pd.DataFrame, label: str) -> dict:
    """計算單一配置的 TP/FP/FN/TN/Precision/Recall/F1"""
    val = val[val["tle_status"] == "ok"].copy()
    ann_p = ann[["norad_id", "propulsion_class"]].drop_duplicates("norad_id")
    val = val.drop(columns=["propulsion_class"], errors="ignore")
    val = val.merge(ann_p, on="norad_id", how="left")
    gt_pos = val["propulsion_class"].isin(GT_POSITIVE_CLASSES)
    det    = val["maneuver_detected"].fillna(False).astype(bool)

    tp = int((gt_pos &  det).sum())
    fp = int((~gt_pos & det).sum())
    fn = int((gt_pos & ~det).sum())
    tn = int((~gt_pos & ~det).sum())
    prec = tp / (tp + fp) if tp + fp > 0 else 0.0
    rec  = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0
    return dict(配置=label, TP=tp, FP=fp, FN=fn, TN=tn,
                Precision=round(prec*100, 1), Recall=round(rec*100, 1), F1=round(f1*100, 1))


def run_configs() -> None:
    """重跑 Config A（P1 only）和 Config B（P1+P2）"""
    script = str(_HERE / "validate_annotations.py")
    for suffix, extra_flags in [
        ("_p1only", ["--disable-p2", "--disable-p3"]),
        ("_p1p2",   ["--disable-p3"]),
    ]:
        csv_path = OUT_DIR / f"validation_full{suffix}.csv"
        if csv_path.exists():
            print(f"[SKIP] {csv_path.name} 已存在，跳過重跑（刪除可強制重跑）")
            continue
        cmd = [sys.executable, script, f"--out-suffix={suffix}"] + extra_flags
        print(f"\n[RUN] {' '.join(cmd)}")
        print("  （預估 ~10 分鐘，請稍候…）")
        result = subprocess.run(cmd, cwd=str(_HERE.parent))
        if result.returncode != 0:
            print(f"[ERROR] 執行失敗，returncode={result.returncode}")
            sys.exit(1)
        print(f"[OK] {csv_path.name} 完成")


def compare() -> None:
    """讀取三份 CSV，輸出 P2/P3 精確消融表格"""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    missing = [p for p in [CSV_A, CSV_B, CSV_C] if not p.exists()]
    if missing:
        print("[ERROR] 缺少以下 CSV，請先執行 --run：")
        for p in missing:
            print(f"  {p}")
        sys.exit(1)

    ann = pd.read_csv(ANN_CSV, dtype=str, encoding="utf-8-sig")

    configs = [
        (CSV_A, "+P1 only (P2=OFF, P3=OFF)"),
        (CSV_B, "+P1+P2  (P3=OFF)"),
        (CSV_C, "+P1+P2+P3 (Full, 無P4)"),
    ]

    results = []
    for csv_path, label in configs:
        val = pd.read_csv(csv_path, dtype={"norad_id": str})
        results.append(_compute_metrics(val, ann, label))

    df = pd.DataFrame(results)

    print("\n" + "=" * 78)
    print("  P2/P3 精確消融實驗（Ablation Study — DuckDB 精確重跑版）")
    print("=" * 78)
    hdr = f"  {'配置':<30} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>6}  {'Precision':>10} {'Recall':>8} {'F1':>6}"
    print(hdr)
    print("  " + "─" * 76)
    for _, row in df.iterrows():
        print(
            f"  {row['配置']:<30} {int(row['TP']):>5} {int(row['FP']):>5}"
            f" {int(row['FN']):>5} {int(row['TN']):>6}"
            f"  {row['Precision']:>9.1f}%  {row['Recall']:>7.1f}%  {row['F1']:>5.1f}%"
        )
    print("=" * 78)

    rows = df.to_dict("records")
    print("\n各步驟增量（相對於前一步）：")
    print(f"  {'配置':<30} {'ΔPrecision':>11} {'ΔRecall':>9} {'ΔF1':>7}")
    print("  " + "─" * 60)
    sign = lambda x: f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%"
    for i in range(1, len(rows)):
        curr, prev = rows[i], rows[i - 1]
        print(
            f"  {curr['配置']:<30}"
            f" {sign(curr['Precision']-prev['Precision']):>11}"
            f" {sign(curr['Recall']-prev['Recall']):>9}"
            f" {sign(curr['F1']-prev['F1']):>7}"
        )

    # P2 和 P3 的物理解釋
    print("\n解釋：")
    if len(rows) >= 2:
        dp2 = rows[1]["Precision"] - rows[0]["Precision"]
        dr2 = rows[1]["Recall"]    - rows[0]["Recall"]
        print(f"  P2（自適應閾值）：Precision {sign(dp2)}，Recall {sign(dr2)}")
        print(f"    低軌（<400km）閾值放寬 → 減少噪聲 FP；高軌（>600km）閾值收緊 → 減少誤報")
    if len(rows) >= 3:
        dp3 = rows[2]["Precision"] - rows[1]["Precision"]
        dr3 = rows[2]["Recall"]    - rows[1]["Recall"]
        print(f"  P3（B* 輔助）：Precision {sign(dp3)}，Recall {sign(dr3)}")
        print(f"    高阻力衛星（bstar>0.0005, alt<450km）放寬 neg_streak → 補回部分高阻力機動 TP")

    out_csv = OUT_DIR / "ablation_p2p3_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[DONE] 結果儲存 → {out_csv}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true",
                        help="重跑 Config A（P1 only）和 Config B（P1+P2），再比較")
    args = parser.parse_args()
    if args.run:
        run_configs()
    compare()


if __name__ == "__main__":
    main()
