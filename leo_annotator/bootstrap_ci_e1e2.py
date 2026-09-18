"""bootstrap_ci_e1e2.py — E1/E2 消融結果之衛星層級 bootstrap 95% CI（回應審查意見）。

論文一自陳限制：「E1／E2 消融統計未含信賴區間與顯著性檢定」。本腳本對
E1（Full P1-P4，30 天，14,019 顆）與 E2（Full P1-P6，54 天，14,023 顆）
之 Precision/Recall/F1，以**衛星（norad_id）為重抽樣單位**做分層 bootstrap
（B=2000，與 GT 正/負例各自重抽樣以維持母體正負例比例、降低小樣本下的
抽樣變異），計算 2.5/97.5 百分位 CI。

預測正例定義與 ablation_study.py 之「Full (+P1~P4+spike)」配置一致：
    predicted_positive = maneuver_detected | (multi_window_detected & ~maneuver_detected) | monotone_with_spike
GT 正例定義與 ablation_study.py 一致：propulsion_class ∈ GT_POSITIVE_CLASSES。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ANN_CSV = HERE / "output" / "annotations_leo_full.csv"
GT_POSITIVE_CLASSES = {"Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"}

B = 2000
SEED = 42


def load_and_label(val_csv: Path, include_p4_spike: bool = True) -> pd.DataFrame:
    """include_p4_spike=True  → 對應表 3「完整 P1–P4（含多窗口）」列（E1 headline）
       include_p4_spike=False → 對應 7.1 節「未含 P4 多窗口折算」之基礎偵測（E2 headline）
    """
    val = pd.read_csv(val_csv, dtype={"norad_id": str})
    val = val[val["tle_status"] == "ok"].copy()

    ann = pd.read_csv(ANN_CSV, dtype={"norad_id": str})
    ann_prop = ann[["norad_id", "propulsion_class"]].drop_duplicates("norad_id")
    val = val.drop(columns=["propulsion_class"], errors="ignore").merge(ann_prop, on="norad_id", how="left")

    for col in ["maneuver_detected", "multi_window_detected", "monotone_with_spike"]:
        if col not in val.columns:
            val[col] = False
        val[col] = val[col].fillna(False).astype(bool)

    val["gt_positive"] = val["propulsion_class"].isin(GT_POSITIVE_CLASSES)
    if include_p4_spike:
        p4_only = val["multi_window_detected"] & ~val["maneuver_detected"]
        val["pred_positive"] = val["maneuver_detected"] | p4_only | val["monotone_with_spike"]
    else:
        val["pred_positive"] = val["maneuver_detected"]
    return val[["norad_id", "gt_positive", "pred_positive"]].reset_index(drop=True)


def prf(gt: np.ndarray, pred: np.ndarray) -> dict:
    tp = int((gt & pred).sum())
    fp = int((~gt & pred).sum())
    fn = int((gt & ~pred).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def bootstrap_ci(df: pd.DataFrame, label: str) -> dict:
    gt_all = df["gt_positive"].to_numpy(bool)
    pred_all = df["pred_positive"].to_numpy(bool)
    point = prf(gt_all, pred_all)

    pos_ids = df.loc[df["gt_positive"], "norad_id"].to_numpy()
    neg_ids = df.loc[~df["gt_positive"], "norad_id"].to_numpy()
    id_to_idx = {}
    for i, nid in enumerate(df["norad_id"].to_numpy()):
        id_to_idx.setdefault(nid, []).append(i)

    rng = np.random.default_rng(SEED)
    boot = {"precision": [], "recall": [], "f1": []}
    for _ in range(B):
        pick_pos = rng.choice(pos_ids, size=len(pos_ids), replace=True)
        pick_neg = rng.choice(neg_ids, size=len(neg_ids), replace=True)
        idx = np.concatenate([id_to_idx[n] for n in np.concatenate([pick_pos, pick_neg])])
        m = prf(gt_all[idx], pred_all[idx])
        for k in boot:
            boot[k].append(m[k])

    ci = {}
    for k in boot:
        lo, hi = np.percentile(boot[k], [2.5, 97.5])
        ci[k] = (lo, hi)

    print(f"\n=== {label}（n={len(df)} 顆，GT正例={int(gt_all.sum())}，B={B} 衛星層級分層 bootstrap） ===")
    print(f"  Precision = {point['precision']*100:.1f}%  95% CI [{ci['precision'][0]*100:.1f}%, {ci['precision'][1]*100:.1f}%]")
    print(f"  Recall    = {point['recall']*100:.1f}%  95% CI [{ci['recall'][0]*100:.1f}%, {ci['recall'][1]*100:.1f}%]")
    print(f"  F1        = {point['f1']*100:.1f}%  95% CI [{ci['f1'][0]*100:.1f}%, {ci['f1'][1]*100:.1f}%]")
    print(f"  TP={point['tp']} FP={point['fp']} FN={point['fn']}")

    return {"label": label, "n": len(df), "n_gt_pos": int(gt_all.sum()),
            "precision": point["precision"], "precision_ci_lo": ci["precision"][0], "precision_ci_hi": ci["precision"][1],
            "recall": point["recall"], "recall_ci_lo": ci["recall"][0], "recall_ci_hi": ci["recall"][1],
            "f1": point["f1"], "f1_ci_lo": ci["f1"][0], "f1_ci_hi": ci["f1"][1]}


def main():
    e1_csv = HERE / "output" / "validation_full_e1_fullp1p4.csv"
    e2_csv = HERE / "output" / "validation_full.csv"

    rows = []
    if e1_csv.exists():
        df_e1 = load_and_label(e1_csv, include_p4_spike=True)
        rows.append(bootstrap_ci(df_e1, "E1 (表3「完整P1-P4含多窗口」, 30天, 14,019顆)"))
    else:
        print(f"[跳過] {e1_csv} 不存在，請先重跑 validate_annotations.py 產生 E1 資料")

    if e2_csv.exists():
        df_e2 = load_and_label(e2_csv, include_p4_spike=False)
        rows.append(bootstrap_ci(df_e2, "E2 (7.1節headline「未含P4折算」, 54天, 14,023顆)"))

    if rows:
        pd.DataFrame(rows).to_csv(HERE / "output" / "e1e2_bootstrap_ci.csv", index=False)
        print(f"\nsaved -> {HERE / 'output' / 'e1e2_bootstrap_ci.csv'}")


if __name__ == "__main__":
    main()
