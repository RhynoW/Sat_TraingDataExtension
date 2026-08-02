#!/usr/bin/env python3
"""
fusion_scorer.py — 連續融合評分器（Layer 2 統計層 → 單一機動機率分數）
=====================================================================
把離散的多個統計偵測器（CUSUM／BOCPD／SSA／3σ-MAD）＋ NRLMSIS 阻力殘差，
以**衛星分組交叉驗證的邏輯斯回歸**融合為單一連續機動機率分數 s∈[0,1]。

動機（對應契約表 8 情境②）：
  - 離散事件旗標無法畫 ROC → 無法計算 ROC-AUC／AP／FPR／macro-F1；連續分數可以。
  - 單一偵測器 recall 有限；融合（含 3σ-MAD，單獨 recall 最佳）可拉高 large 事件 recall。

方法：
  逐衛星以 statistical_detectors.run_all(sma) 取 cusum/bocpd/ssa/mad 四通道逐點分數，
  併入 NRLMSIS 阻力殘差 |drag_resid_da|（data/drag/drag_resid_*.csv）為第五通道；
  標籤 = 該 epoch 是否落在 medium/large MEME 轉移 ±24h 內。
  GroupKFold(5, 依 norad) 取 OOF 分數 → 誠實計算 ROC-AUC／AP；閾值取 macro-F1 最大化，
  報 FPR／macro-F1／TPR，並以 episode 級（48h 合併、max 嚴重度）算分層 recall + latency。

輸出：models_fusion/fusion_scorer.pkl、data/benchmark/fusion_metrics_{date}.csv
用法：python fusion_scorer.py [--max-sats N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score

from statistical_detectors import run_all
from compare_tle_vs_ephemeris import load_registry
from satdet import (TOL_NS, config, episodes_by_sat, episode_masks,
                    fpr_floor_threshold, input_file, load_drag_map,
                    quiet_blocks, record, to_ns)
from satdet.common import SEV_RANK as _RANK

CH = ["cusum", "bocpd", "ssa", "mad3sig", "drag"]
LABEL_TOL_NS = int(3 * 3.6e12)   # 訓練緊標籤：epoch≈實際機動轉移（避免 ±24h 膨脹退化成 base-rate）


def build_units(db: str, sats, drag_by: dict, truth: pd.DataFrame):
    """單位級（unit）融合資料集：正=機動 episode、負=無機動安靜窗。
    每 unit 特徵＝其涵蓋 epoch 上各通道的最大值。標籤在 unit 級對齊乾淨（避開
    MEME 8h 網格 vs TLE epoch 的點級錯位）。回傳 DataFrame(norad,label,sev,f_*,lat_h)。"""
    con = duckdb.connect(db, read_only=True)
    eps_by = episodes_by_sat(truth)

    rows = []
    for name, nid in sats:
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive "
                         "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
                         [int(nid)]).fetchdf()
        if len(df) < 8:
            continue
        ep = to_ns(df["epoch_utc"]); sma = df["sma_km"].to_numpy(float)
        r = run_all(sma)
        drg = drag_by.get(int(nid), {})
        C = np.nan_to_num(np.column_stack([
            np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
            np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]),
            np.array([drg.get(e, 0.0) for e in ep]) / 0.10]))
        def _feat(sub):  # sub: C[mask] → 每通道 max/mean/p90（不含長度，避免長度洩漏）
            d = {}
            for j, c in enumerate(CH):
                col = sub[:, j]
                d[f"{c}_max"] = float(col.max()); d[f"{c}_mean"] = float(col.mean())
                d[f"{c}_p90"] = float(np.percentile(col, 90))
            return d

        masks, assigned = episode_masks(ep, eps_by.get(int(nid), []), TOL_NS)
        for mask, rk, lat in masks:
            rows.append({"norad_id": int(nid), "label": 1, "sev": int(rk),
                         **_feat(C[mask]), "lat_h": lat})
        # 負 unit：把安靜 epoch 切成與正 unit 等寬（~48h）的窗，避免長度不對稱洩漏
        for w in quiet_blocks(ep, np.where(~assigned)[0], 2 * TOL_NS):
            rows.append({"norad_id": int(nid), "label": 0, "sev": 0,
                         **_feat(C[w]), "lat_h": np.nan})
    con.close()
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--max-sats", type=int, default=None)
    args = ap.parse_args()

    truth_path = input_file("data/meme_truth/transitions_full_*.csv",
                            step="meme_truth", key="transitions_full")
    truth = pd.read_csv(truth_path)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")

    reg = load_registry("data/url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())[: args.max_sats] if args.max_sats else list(n2n.items())

    print(f"建 unit 級融合資料集：{len(sats)} 顆 × 5 通道 {CH} …")
    drag_by = load_drag_map()
    U = build_units(args.db, sats, drag_by, truth)
    feats = [f"{c}_{s}" for c in CH for s in ("max", "mean", "p90")]
    X = U[feats].to_numpy(); y = U["label"].to_numpy()
    groups = U["norad_id"].to_numpy()
    print(f"  units {len(U)}（正/機動 episode {int(y.sum())}、負/安靜窗 {int((y==0).sum())}），"
          f"衛星 {U['norad_id'].nunique()}")

    # ── 衛星分組 CV → OOF 分數（unit 級標籤乾淨、誠實）─────────────────────────
    def _mk():
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                               max_depth=4, l2_regularization=1.0,
                                               class_weight="balanced", random_state=42)
    oof = np.zeros(len(y))
    for tr_i, te_i in GroupKFold(n_splits=5).split(X, y, groups):
        oof[te_i] = _mk().fit(X[tr_i], y[tr_i]).predict_proba(X[te_i])[:, 1]
    U["oof"] = oof

    auc = roc_auc_score(y, oof); ap = average_precision_score(y, oof)
    # 操作點：在 FPR≤0.05 預算下取最高 recall（floor 保證嚴格 ≤0.05）
    best_thr = fpr_floor_threshold(oof[y == 0], 0.05)
    pred = oof >= best_thr
    fp = int(((pred == 1) & (y == 0)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    best_mf1 = f1_score(y, pred, average="macro")

    print(f"\n=== 融合分數 OOF 指標（unit 級：機動 episode vs 安靜窗）===")
    print(f"  ROC-AUC={auc:.4f}  AP={ap:.4f}  macro-F1={best_mf1:.4f}  FPR={fpr:.4f}  "
          f"(操作點 thr={best_thr:.3f}, FPR預算 0.05)")

    # 分層 recall + latency（正 unit 依 sev）
    inv = {v: k for k, v in _RANK.items()}; tgt = {"large": 0.90, "medium": 0.80, "small": 0.65}
    rows_out = [{"metric": "ROC-AUC", "value": round(auc, 4), "target": ">=0.90"},
                {"metric": "Average Precision", "value": round(ap, 4), "target": ">=0.85"},
                {"metric": "F1-macro", "value": round(best_mf1, 4), "target": ">=0.80"},
                {"metric": "FPR", "value": round(fpr, 4), "target": "<=0.05"}]
    print(f"\n=== 分層 recall（融合分數 unit 級，±24h）===")
    for sev in ("large", "medium", "small"):
        sub = U[(U["label"] == 1) & (U["sev"] == _RANK[sev])]
        rc = float((sub["oof"] >= best_thr).mean()) if len(sub) else 0.0
        lat = float(sub[sub["oof"] >= best_thr]["lat_h"].median()) if (sub["oof"] >= best_thr).any() else None
        vd = "✅" if rc >= tgt[sev] else "❌"
        ls = f"{lat:.1f}h" if lat is not None else "—"
        print(f"  {sev:6} recall={rc:.3f} (n={len(sub)}, target≥{tgt[sev]}) {vd}  latency中位={ls}")
        rows_out.append({"metric": f"TPR_{sev}", "value": round(rc, 4), "target": f">={tgt[sev]}"})

    # 全資料重訓 → 存模型
    clf = _mk().fit(X, y)
    try:
        import joblib
        Path("models_fusion").mkdir(exist_ok=True)
        joblib.dump({"clf": clf, "feats": feats, "channels": CH, "thr": float(best_thr)},
                    "models_fusion/fusion_scorer.pkl")
        print("\n  模型 → models_fusion/fusion_scorer.pkl")
    except Exception as ex:
        print("  存檔略過：", ex)

    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = Path("data/benchmark") / f"fusion_metrics_{date}.csv"
    pd.DataFrame(rows_out).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  指標 → {out}")
    record("fusion_scorer",
           inputs={"transitions_full": truth_path, "db": args.db},
           params={"channels": ",".join(CH), "fpr_budget": 0.05,
                   "max_sats": args.max_sats},
           outputs={"fusion_metrics": out, "model": "models_fusion/fusion_scorer.pkl"})


if __name__ == "__main__":
    main()
