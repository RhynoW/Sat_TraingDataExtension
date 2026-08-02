#!/usr/bin/env python3
"""
model1_meme_episode_tpr.py — Model 1（Plan B）於外部 MEME 集之事件級 TPR
=======================================================================
補齊情境①#2「待對齊」：以**同一個 Plan B production Model 1**（自標籤訓練、逐衛星整段
聚合特徵）、在**外部 MEME 真值集**上，計算**事件級（episode）TPR**，修正原逐點/衛星級
0.397 之粒度，對齊 #2 之欄位定義（Model 1 · 外部 MEME · TPR）。

Model 1 每顆星輸出一個機動機率（20 維整段聚合特徵）→ 過門檻得每星旗標。
  · 衛星級 TPR：有 MEME 機動之衛星中，被旗標之比例（健全性檢查，應 ≈ 0.397）。
  · 事件級 TPR：所有 MEME 機動 episode 中，其母衛星被旗標之比例（本項要補的數字）。
並分「全區間」與「out-of-time（Plan B 訓練截止 2026-06-23 之後）」雙報，確保外部性乾淨。

用法：python model1_meme_episode_tpr.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import joblib
import numpy as np
import pandas as pd

from satdet import episodes_by_sat, to_ns
from satdet.common import RANK_SEV, SEV_RANK

MDIR = Path("Orbital_Maneuver_V2/models_plan_b")
OOT_CUTOFF = pd.Timestamp("2026-06-23", tz="UTC")     # Plan B 訓練窗結尾
PARQUET = "data/maneuvers/training_dataset_final.parquet"


def main():
    feats = json.load(open(MDIR / "feature_names.json", encoding="utf-8"))
    thr = json.load(open(MDIR / "threshold.json", encoding="utf-8"))["threshold"]
    model = joblib.load(MDIR / "lgbm_maneuver_v1.pkl")

    # ── 1. 評分 Plan B Model 1（每星一分數）──
    df = pd.read_parquet(PARQUET)
    b = df[df["plan"] == "B"].copy() if "plan" in df else df.copy()
    X = b[feats].to_numpy()
    b["p"] = model.predict_proba(X)[:, 1]
    b["flag"] = (b["p"] >= thr).astype(int)
    flag_by_norad = dict(zip(b["norad_id"].astype(int), b["flag"]))
    name_to_norad = dict(zip(b["sat_name"], b["norad_id"].astype(int)))
    print(f"Model 1（Plan B）評分：{len(b)} 顆，門檻 {thr:.4f}，旗標 {int(b['flag'].sum())} 顆"
          f"（{b['flag'].mean()*100:.1f}%）\n")

    # ── 2. 外部 MEME 真值：episodes ──
    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601", errors="coerce")
    if "norad_id" not in truth.columns or truth["norad_id"].isna().all():
        truth["norad_id"] = truth["sat_name"].map(name_to_norad)
    truth = truth.dropna(subset=["norad_id"]); truth["norad_id"] = truth["norad_id"].astype(int)

    eps_by = episodes_by_sat(truth)   # {norad: [(times_ns, rank), ...]}，僅 SEV_RANK 內

    # ── 3. 事件級 / 衛星級 TPR（全區間 & out-of-time）──
    def eval_split(cutoff_ns=None, oot=False):
        # 事件層：逐 episode 計；衛星層：有 episode 之 sat 計
        ep_tot = {s: 0 for s in SEV_RANK}; ep_hit = {s: 0 for s in SEV_RANK}
        sat_pos, sat_hit = set(), set()
        for norad, eps in eps_by.items():
            fl = flag_by_norad.get(int(norad), 0)
            for times_ns, rk in eps:
                if oot and cutoff_ns is not None and times_ns.max() < cutoff_ns:
                    continue                    # 只留 cutoff 之後之 episode
                sev = RANK_SEV[rk]
                ep_tot[sev] += 1
                if fl:
                    ep_hit[sev] += 1
                sat_pos.add(int(norad))
                if fl:
                    sat_hit.add(int(norad))
        return ep_tot, ep_hit, sat_pos, sat_hit

    cutoff_ns = int(OOT_CUTOFF.value)
    results = {}
    for tag, oot in [("全區間", False), ("out-of-time(>06-23)", True)]:
        ep_tot, ep_hit, sat_pos, sat_hit = eval_split(cutoff_ns, oot)
        # 事件級 TPR（large / medium / large+medium / 全部）
        def tpr(keys):
            t = sum(ep_tot[k] for k in keys); h = sum(ep_hit[k] for k in keys)
            return (h / t if t else float("nan")), t
        results[tag] = {
            "large": tpr(["large"]), "medium": tpr(["medium"]),
            "lm": tpr(["large", "medium"]), "all": tpr(list(SEV_RANK)),
            "sat": (len(sat_hit) / len(sat_pos) if sat_pos else float("nan"), len(sat_pos)),
        }

    # ── 4. 輸出 ──
    print("=" * 78)
    print(f"{'口徑':<22}{'large':>13}{'medium':>13}{'large+med':>13}{'衛星級':>13}")
    print("-" * 78)
    for tag in ("全區間", "out-of-time(>06-23)"):
        r = results[tag]
        def cell(k):
            v, n = r[k]; return f"{v:.3f} (n={n})"
        print(f"{tag:<22}{cell('large'):>13}{cell('medium'):>13}{cell('lm'):>13}{cell('sat'):>13}")
    print("=" * 78)
    r = results["全區間"]
    print(f"健全性檢查：衛星級 TPR {r['sat'][0]:.3f}（原報告 0.397，應相近）")
    print(f"★ 對齊 #2 之數字：Model 1 · 外部 MEME · 事件級 large TPR = "
          f"{r['large'][0]:.3f}（全區間）／{results['out-of-time(>06-23)']['large'][0]:.3f}（out-of-time）")
    print("\n粒度說明：逐點 0.397 要求旗標落在 MEME 8h 真值格；事件級改以『該次機動事件是否被"
          "母衛星旗標』計，修正粒度錯位。Model 1 為逐星整段聚合模型，事件級即"
          "『機動事件之母衛星被旗標比例』。")

    out = Path("data/benchmark/model1_meme_episode_tpr_20260724.csv")
    rows = []
    for tag in results:
        for k in ("large", "medium", "lm", "all", "sat"):
            v, n = results[tag][k]
            rows.append({"split": tag, "metric": k, "tpr": round(v, 4), "n": n})
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
