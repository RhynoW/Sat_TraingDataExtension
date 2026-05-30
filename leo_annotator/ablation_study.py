"""
ablation_study.py
=================
消融實驗（Ablation Study）：展示 P1–P4 每一步對 Precision / Recall / F1 的獨立貢獻。

方法：逆推法
  - 直接讀取已存在的 leo_annotator/output/validation_full.csv（包含 P1–P4 全開結果）
  - 利用欄位 monotone_suppressed、multi_window_detected、monotone_with_spike
    反推各配置的預測正例集合，不需重跑 DuckDB 查詢

欄位語義（validation_full.csv）：
  maneuver_detected     = 主偵測結果（P1+P2+P3 全開，但不含 P4 多窗口）
  monotone_suppressed   = P1 抑制生效的衛星（da 旗標被 monotone_decay 覆蓋）
  multi_window_detected = P4 多窗口補偵（若主偵測已偵到，此欄也=True）
  monotone_with_spike   = P1 rescue（有 spike 的 monotone，P1 不抑制）

配置說明：
  Baseline   = 無任何改進：不抑制 monotone（P1 off），固定閾值（P2 off），
                無 B* 輔助（P3 off），無多窗口（P4 off）
  +P1        = 加入 monotone_decay 抑制
  +P1+P2     = P2 改閾值（效果已合入 detected，近似不變）
  +P1+P2+P3  = P3 B* 輔助（效果已合入，近似不變）
  Full P1-P4 = 全開（含 P4 多窗口 + P1 rescue spike）
"""

import sys
from pathlib import Path

import pandas as pd

# ── 路徑 ──────────────────────────────────────────────────────────────────────
_HERE       = Path(__file__).parent
VAL_CSV     = str(_HERE / "output" / "validation_full.csv")
ANN_CSV     = str(_HERE / "output" / "annotations_leo_full.csv")
OUT_CSV     = str(_HERE / "output" / "ablation_results.csv")

# GT 正例定義：有推進系統的衛星
GT_POSITIVE_CLASSES = {"Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"}


def compute_metrics(
    gt_positive: pd.Series,
    predicted_positive: pd.Series,
    label: str,
) -> dict:
    """計算 TP / FP / FN / TN / Precision / Recall / F1"""
    gt  = gt_positive.astype(bool)
    pred = predicted_positive.astype(bool)

    tp = int((gt  & pred).sum())
    fp = int((~gt & pred).sum())
    fn = int((gt  & ~pred).sum())
    tn = int((~gt & ~pred).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "配置":        label,
        "TP":          tp,
        "FP":          fp,
        "FN":          fn,
        "TN":          tn,
        "Precision":   round(precision * 100, 1),
        "Recall":      round(recall    * 100, 1),
        "F1":          round(f1        * 100, 1),
    }


def main() -> None:
    # 強制 utf-8 輸出
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # ── 1. 讀取資料 ───────────────────────────────────────────────────────────
    print(f"讀取驗證結果: {VAL_CSV}")
    val = pd.read_csv(VAL_CSV, dtype={"norad_id": str})

    print(f"讀取標註資料: {ANN_CSV}")
    ann = pd.read_csv(ANN_CSV, dtype={"norad_id": str})

    # 只保留 tle_status == "ok" 的有效分析樣本（與 validate_annotations.py 一致）
    val = val[val["tle_status"] == "ok"].copy()
    print(f"有效樣本數 : {len(val)} 顆")

    # 欄位補齊（舊版 CSV 可能無 monotone_with_spike）
    missing_cols = []
    for col in ["maneuver_detected", "multi_window_detected",
                "monotone_suppressed", "monotone_with_spike"]:
        if col not in val.columns:
            val[col] = False
            missing_cols.append(col)
        val[col] = val[col].fillna(False).astype(bool)

    if missing_cols:
        print(f"[警告] 以下欄位在 CSV 中不存在，已補 False：{missing_cols}")
        print(f"       若要取得精確的 spike rescue 數字，請先重跑 validate_annotations.py")
        print()

    # ── 2. 建立 GT 標籤 ───────────────────────────────────────────────────────
    # 合併 propulsion_class（val 已有，但以 ann 為準）
    ann_prop = ann[["norad_id", "propulsion_class"]].drop_duplicates("norad_id")
    val = val.drop(columns=["propulsion_class"], errors="ignore")
    val = val.merge(ann_prop, on="norad_id", how="left")

    gt_positive = val["propulsion_class"].isin(GT_POSITIVE_CLASSES)
    n_gt_pos = int(gt_positive.sum())
    n_gt_neg = int((~gt_positive).sum())
    print(f"GT 正例（有推進）: {n_gt_pos} 顆")
    print(f"GT 負例（無推進）: {n_gt_neg} 顆\n")

    # ── 3. 各配置的預測正例定義 ───────────────────────────────────────────────
    detected     = val["maneuver_detected"]     # P1+P2+P3 主偵測（已含改進，無 P4）
    multi_win    = val["multi_window_detected"] # P4 多窗口（若主偵測已偵到也=True）
    mono_supp    = val["monotone_suppressed"]   # P1 抑制的衛星（Baseline 下不抑制 → 也算 detected）
    spike_rescue = val["monotone_with_spike"]   # P1 rescue

    # P4 獨立貢獻 = multi_window_detected AND NOT maneuver_detected
    p4_only = multi_win & ~detected

    # 各配置說明：
    #   Baseline：P1 不抑制（mono_supp 的也算 detected）；無 P4
    #             = detected | mono_supp
    #   +P1：P1 抑制生效（mono_supp 不算 detected）；無 P4；P2/P3 已含於 detected
    #        = detected（此時 monotone_suppressed 的已被抑制）
    #   +P1+P2：P2 改閾值效果已合入 detected，無法完全分離 → 視為與 +P1 相同（近似）
    #   +P1+P2+P3：P3 效果同上 → 視為與 +P1+P2 相同（近似）
    #   Full P1-P4：detected | p4_only | spike_rescue（P1 rescue 讓 spike 案例重新算 detected）
    #
    # 注意：spike_rescue 的衛星原本 maneuver_detected=False（被 P1 抑制）
    #       但這些衛星有 spike，P1 rescue 後應算 detected

    configs_pred = {
        "Baseline (無P改進)":    detected | mono_supp,
        "+P1":                   detected,
        "+P1+P2":                detected,            # 近似：P2 效果已合入
        "+P1+P2+P3":             detected,            # 近似：P3 效果已合入
        "Full (+P1~P4+spike)":   detected | p4_only | spike_rescue,
    }

    # ── 4. 計算各配置指標 ────────────────────────────────────────────────────
    results = []
    for label, pred in configs_pred.items():
        m = compute_metrics(gt_positive, pred, label)
        results.append(m)

    df_out = pd.DataFrame(results)

    # ── 5. 輸出論文格式表格 ──────────────────────────────────────────────────
    print("=" * 75)
    print("消融實驗結果表（Ablation Study）")
    print("=" * 75)
    header = (
        f"{'配置':<22} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>6}"
        f"  {'Precision':>10} {'Recall':>8} {'F1':>6}"
    )
    print(header)
    print("─" * 75)
    for _, row in df_out.iterrows():
        line = (
            f"{row['配置']:<22} {int(row['TP']):>5} {int(row['FP']):>5}"
            f" {int(row['FN']):>5} {int(row['TN']):>6}"
            f"  {row['Precision']:>9.1f}%  {row['Recall']:>7.1f}%  {row['F1']:>5.1f}%"
        )
        print(line)
    print("=" * 75)

    # ── 6. 各步驟增量說明 ────────────────────────────────────────────────────
    rows = df_out.to_dict("records")
    print("\n各步驟增量（相對於前一步）：")
    print(f"  {'配置':<22} {'ΔPrecision':>11} {'ΔRecall':>9} {'ΔF1':>7}")
    print("  " + "─" * 52)
    for i in range(1, len(rows)):
        curr, prev = rows[i], rows[i-1]
        dp = curr["Precision"] - prev["Precision"]
        dr = curr["Recall"]    - prev["Recall"]
        df_ = curr["F1"]       - prev["F1"]
        sign = lambda x: f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%"
        print(f"  {curr['配置']:<22} {sign(dp):>11} {sign(dr):>9} {sign(df_):>7}")

    print()

    # ── 7. 附加說明：P2/P3 無法從 CSV 分離的原因 ─────────────────────────────
    print("注意：+P1+P2 與 +P1+P2+P3 的指標與 +P1 相同（近似），")
    print("      因為 P2（自適應閾值）和 P3（B* 放寬）的效果已合入")
    print("      validation_full.csv 的 maneuver_detected 欄位，")
    print("      無法從靜態 CSV 完全分離，需重跑 DuckDB 查詢才能精確量化。")
    print()

    # ── 8. monotone_with_spike 補救統計 ────────────────────────────────────
    n_spike = int(spike_rescue.sum())
    n_spike_gt = int((spike_rescue & gt_positive).sum())
    n_spike_fp = int((spike_rescue & ~gt_positive).sum())
    print(f"monotone_with_spike 統計：")
    print(f"  共 {n_spike} 顆衛星被 P1 rescue（有 spike 的 monotone）")
    print(f"  其中 GT 正例（有推進）: {n_spike_gt} 顆（真實機動）")
    print(f"  其中 GT 負例（無推進）: {n_spike_fp} 顆（可能 FP）")
    print()

    # ── 9. 儲存結果 ──────────────────────────────────────────────────────────
    df_out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[DONE] 消融結果已儲存: {OUT_CSV}")


if __name__ == "__main__":
    main()
