#!/usr/bin/env python3
"""fs7_l3_fusion_apply.py — 把本專案「LOSO L3 融合」模型（訓練於全 23 星，
`tasa14_l3_fusion.py --ext23 --q23`）套用到福衛七號 6 星，與精密星曆推估
真值（`fs7_curve_method_vs_precise_truth.py` 之 85 個「疑似真事件」）比較。

**方法（忠實沿用既有 L3 融合之候選生成/特徵/訓練邏輯，非重新設計）**：
1. 候選生成：`detect_iter2(k=3)` ∪ `detect_pred(k=6,deg=1)` ∪ L2 四通道
   （CUSUM/BOCPD/SSA/MAD3σ）事件之聯集，1 天內合併。
2. 特徵：與 23 星訓練時完全相同之 10 個基礎特徵（z_ls/z_pe/z_step/
   s_cusum/s_bocpd/s_ssa/s_mad/cadence_d/det_it2/det_pr）＋ Q23 之 4 個特徵
   （local_gap_d/cad_ratio/in_w1/in_w2）。
3. 訓練：用**全部 23 星**（福衛七號本就不在此 23 星內，天然無需再排除，
   等同於把福衛七號視為「真正從未見過的全新衛星」做泛化測試——比 LOSO
   對既有 23 星的驗證更嚴格）訓練一個 HistGradientBoostingClassifier。
4. 門檻 θ：依福衛七號自身 cadence（更新頻率）落入 dense/sparse 類別，
   在**全 23 星**（依同類別）上做網格搜尋選出最大化平均 F1 之 θ——福衛
   七號自己的真值全程未參與訓練或選門檻，是乾淨的樣本外測試。

**誠實聲明**：Q23 之 `local_gap_d`/`cad_ratio` 特徵原設計依賴
`tasa14_14class_peer_yearly_20260804.csv`（14 星機隊逐年 cadence 中位數）
做相對化；福衛七號之 epoch（2024-2026）多數超出該表涵蓋範圍，此處以最近
可得年份之數值代用（`fleet_gap()` 之既有 argmin 邏輯自動處理），可能引入
額外雜訊，如實記錄。

用法：python fs7_l3_fusion_apply.py
輸出：data/benchmark/fs7_l3_fusion_apply_20260914.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# 側載 tasa14_l3_fusion.py，強制以 --ext23 --q23 模式初始化（沿用 app 既有手法，
# 見 maneuver_app_2026September.py::_import_tasa14_l3_fusion_ext23_q23）
saved_argv = sys.argv
sys.argv = [saved_argv[0], "--ext23", "--q23"]
try:
    import tasa14_l3_fusion as l3f
finally:
    sys.argv = saved_argv

import tasa14_l2_compare as l2
from tasa14_compare import load_a, detect_iter2
from tasa14_pdf_baseline import detect_pred
from formosat7_leoorb.satmap import SP3_TO_NORAD, SP3_TO_NAME
from fs7_curve_method_vs_precise_truth import load_truth_events

CAND_MERGE_D = l3f.CAND_MERGE_D
CADENCE_SPLIT_D = l3f.CADENCE_SPLIT_D
THETA_GRID = l3f.THETA_GRID
FEATS = l3f.FEATS + l3f.Q23_FEATS


def build_fs7_candidates(nid: int, nm: str, tol_d: float) -> pd.DataFrame:
    """比照 l3f.build_features() 之候選生成/特徵計算，套用於單一福衛七號衛星。
    無真值標籤時 label 留 NaN（僅供最終評估用，不參與訓練/選門檻）。"""
    t, a = load_a(nid)
    if t is None or len(a) < 60:
        return pd.DataFrame()
    tsec = t.astype("int64").to_numpy() / 1e9
    gaps = np.diff(tsec) / 86400.0
    cad = float(np.median(gaps[gaps > 0])) if (gaps > 0).any() else np.nan
    z_ls = l3f.signal_ls(t, a)
    z_pe = l3f.signal_pe(t, a)
    z_st = l3f.signal_step(t, a)
    sc, evs = l3f.l2_scores(t, a)
    cands = list(detect_iter2(t, a, 3)) + list(detect_pred(t, a, 6, 1, 1))
    for c in l2.CHANS:
        cands += list(l2.merge_epochs(evs[c]))
    cands = l2.merge_epochs(cands, CAND_MERGE_D)
    cands = pd.to_datetime(list(cands))
    if len(cands) == 0:
        return pd.DataFrame()
    csec = cands.astype("int64").to_numpy() / 1e9
    it2 = pd.to_datetime(detect_iter2(t, a, 8)).astype("int64").to_numpy() / 1e9
    prd = pd.to_datetime(detect_pred(t, a, 12, 1, 1)).astype("int64").to_numpy() / 1e9
    near = lambda arr, cs: bool(len(arr)) and bool(np.min(np.abs(arr - cs)) <= 0.75 * 86400)
    rows = []
    for ce, cs in zip(cands, csec):
        m = np.abs(tsec - cs) <= 1.0 * 86400
        if not m.any():
            continue
        def mx(arr):
            v = arr[m]; v = v[np.isfinite(v)]
            return float(v.max()) if len(v) else 0.0
        rows.append(dict(norad=nid, name=nm, epoch=ce,
                          z_ls=mx(z_ls), z_pe=mx(z_pe), z_step=mx(z_st),
                          s_cusum=mx(sc["cusum"]), s_bocpd=mx(sc["bocpd"]),
                          s_ssa=mx(sc["ssa"]), s_mad=mx(sc["mad3sig"]),
                          cadence_d=cad, det_it2=int(near(it2, cs)), det_pr=int(near(prd, cs))))
    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df
    # Q23 特徵：local_gap_d / cad_ratio（fleet_gap 之 argmin 對超出年份範圍自動就近取代用）
    py = pd.read_csv(l3f.PEER_YEARLY_CSV)
    fleet = py.groupby("year")["cadence_d"].median()
    fyears = fleet.index.to_numpy()
    def fleet_gap(year):
        return float(fleet.loc[fyears[np.argmin(np.abs(fyears - year))]])
    csec2 = df["epoch"].astype("int64").to_numpy() / 1e9
    lg = np.empty(len(df))
    for i, cs in enumerate(csec2):
        mm = np.abs(tsec - cs) <= 15 * 86400
        gg = np.diff(tsec[mm]) / 86400.0
        gg = gg[gg > 0]
        lg[i] = float(np.median(gg)) if len(gg) >= 3 else cad
    df["local_gap_d"] = lg
    yrs = df["epoch"].dt.year.to_numpy()
    df["cad_ratio"] = lg / np.array([fleet_gap(y) for y in yrs])
    df["in_w1"] = ((df["epoch"] >= l3f.W1[0]) & (df["epoch"] <= l3f.W1[1])).astype(int)
    df["in_w2"] = ((df["epoch"] >= l3f.W2[0]) & (df["epoch"] <= l3f.W2[1])).astype(int)
    # 標籤：與精密星曆真值 ±tol_d 天比對
    tol = pd.Timedelta(days=tol_d)
    events = load_truth_events()
    ev = events.get(nid)
    df["label"] = 0
    if ev is not None and len(ev):
        for _, e in ev.iterrows():
            m = (df["epoch"] >= e["ws"] - tol) & (df["epoch"] <= e["we"] + tol)
            df.loc[m, "label"] = 1
    return df


def evaluate_fs7(nid: int, dets: pd.DatetimeIndex, tol_d: float) -> dict:
    """比照 l3f.star_f1，但真值改用福衛七號精密星曆推估真值。"""
    events = load_truth_events()
    if nid not in events:
        return dict(n_ev=0, precision=0.0, recall=0.0, f1=0.0)
    ev = events[nid]
    t, a = load_a(nid)
    lo, hi = t.min(), t.max()
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    return l2.metrics(dets, ev, lo, hi)


def main():
    print("載入全 23 星（Q23）訓練特徵表……", flush=True)
    train_df = l3f.build_features(False)
    train_df = l3f.augment_q23(train_df)
    print(f"訓練樣本：{len(train_df)} 個候選，{train_df['norad'].nunique()} 顆衛星，"
          f"正例率 {train_df['label'].mean():.3f}", flush=True)

    clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08, random_state=42)
    clf.fit(train_df[FEATS], train_df["label"])
    print("已在全 23 星上訓練單一模型（福衛七號未參與訓練）。", flush=True)

    cad_map = train_df.groupby("norad")["cadence_d"].first().to_dict()
    cls_map = {n: ("dense" if cad_map[n] < CADENCE_SPLIT_D else "sparse") for n in cad_map}
    train_sats = list(cad_map.keys())
    train_proba = {n: clf.predict_proba(train_df[train_df.norad == n][FEATS])[:, 1] for n in train_sats}

    rows = []
    for sp3_id, nid in SP3_TO_NORAD.items():
        nm = SP3_TO_NAME[sp3_id]
        fs7_df = build_fs7_candidates(nid, nm, tol_d=l3f.tc.TOL_D)
        if len(fs7_df) == 0:
            print(f"[{nm}] 無候選，跳過", flush=True)
            continue
        cls = "dense" if fs7_df["cadence_d"].iloc[0] < CADENCE_SPLIT_D else "sparse"
        tr_sats_cls = [n for n in train_sats if cls_map[n] == cls]
        if len(tr_sats_cls) < 2:
            tr_sats_cls = train_sats
        best_th, best_f1 = 0.5, -1
        for th in THETA_GRID:
            f1s = []
            for n in tr_sats_cls:
                dets = l3f.dets_from_accept(train_df[train_df.norad == n], train_proba[n], th)
                f1s.append(l3f.star_f1(n, dets, l3f.EVENTS_LOADER())["f1"])
            m = float(np.mean(f1s))
            if m > best_f1:
                best_f1, best_th = m, th

        proba = clf.predict_proba(fs7_df[FEATS])[:, 1]
        dets = l3f.dets_from_accept(fs7_df, proba, best_th)
        met = evaluate_fs7(nid, dets, tol_d=l3f.tc.TOL_D)
        rows.append(dict(norad=nid, name=nm, cls=cls, theta=best_th, method="l3_fusion",
                          n_ev=met.get("n_ev", np.nan),
                          precision=met["precision"], recall=met["recall"], f1=met["f1"]))
        print(f"[{nm}] cls={cls} θ={best_th:.2f} P={met['precision']:.3f} "
              f"R={met['recall']:.3f} F1={met['f1']:.3f}", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/fs7_l3_fusion_apply_20260914.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列）")
    if len(df):
        print(f"平均 F1={df['f1'].mean():.3f} P={df['precision'].mean():.3f} R={df['recall'].mean():.3f}")


if __name__ == "__main__":
    main()
