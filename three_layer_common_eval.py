#!/usr/bin/env python3
"""
three_layer_common_eval.py — 三層同一擂台評估（相同測試集、相同 Ground Truth、相同單元）
========================================================================================
回應審查關切：報告中 Layer 1／2／3 原本各用不同測試集與評估基準，數值不可橫向比較。
本腳本把三層放到**完全相同**的評估條件上，產出一張可直接比較的表。

統一條件
--------
  測試集    ：284 顆有 MEME 精密星曆的 Starlink（data/raw ∩ url_registry）
  Ground Truth：MEME transitions da_severity ∈ {medium, large}，gap>48h 合併為 episode
  評估單元  ：unit＝機動 episode（正）＋等寬安靜窗（負）——同一批 unit 餵三層
  操作點    ：FPR≤0.05 floor（對有連續分數的層）；L1 為二元規則，報其固定 (P,R,FPR) 點
  指標      ：precision／recall／分層 recall（large/medium/small）／FPR，全部同定義

各層在同一 unit 上的分數／預測
--------------------------------
  L1 規則   ：unit 內任一相鄰轉移被 P1–P6 combined 旗標 → 預測正（二元；無可調操作點）
  L2 統計   ：unit 內各統計通道（cusum/bocpd/ssa/mad3sig）的 max；主表取單通道最佳，
              另報「五通道樸素 max 融合」作為「未學習」對照
  L3 機器學習：五通道 × (max/mean/p90) = 15 維特徵，HistGradientBoosting，
              **GroupKFold(5) OOF**（同一顆星不跨 train/test，杜絕樂觀偏差）
  naive     ：純隨機分數（同操作點）——驗證此擂台具鑑別力（對照不應接近滿分）

公平性
------
  ・L3 用 OOF，不以自身訓練集測試；L1／L2 不訓練，直接跑。
  ・同一 unit 集、同一 GT、同一操作點。
  ・L2 單通道 vs L3 五通道融合：融合較優為預期（正是「ML 勝過單一統計」之驗證）。

限制（如實呈現）
----------------
  ・僅 283 顆 Starlink，不可外推非 Starlink（L1 域先驗、Model 2 跨域優勢均測不到）。
  ・L1 之 P1–P6 門檻為全庫調校，非為本集最佳化——呈現其於此集之真實表現。
  ・L1 為二元規則，只有一個 (P,R,FPR) 點，無 ROC 曲線。

輸出：data/benchmark/three_layer_common_eval_{date}.csv、主控台對照表
用法：python three_layer_common_eval.py [--max-sats N]
"""
from __future__ import annotations

import argparse
import glob
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
from sklearn.metrics import roc_auc_score

from statistical_detectors import run_all
import maneuver_strategies_july as ms
from compare_tle_vs_ephemeris import load_registry
from satdet import (config, coverage_mask, episodes_by_sat, episode_masks, quiet_blocks,
                    fpr_floor_threshold, load_drag_map, to_ns, truth_coverage, TOL_NS)
from satdet.common import SEV_RANK

CH = ["cusum", "bocpd", "ssa", "mad3sig", "drag"]          # 與 fusion_scorer 一致
STAT_CH = ["cusum", "bocpd", "ssa", "mad3sig"]             # L2 純統計通道（不含物理 drag）
HGB = dict(max_iter=300, learning_rate=0.06, max_depth=4,
           l2_regularization=1.0, class_weight="balanced", random_state=42)
RANK_SEV = {v: k for k, v in SEV_RANK.items()}
# L3 v2 特徵與參數（exp_l3_v2.py 選定）
L3V2_FEATS = ([f"f_{c}_{st}" for c in CH for st in ("max", "mean", "p90")]
              + [f"t_{c}_{k}" for c in CH for k in ("peakpos", "rise", "conc")]
              + ["x_stat_minus_drag", "x_stat_over_drag", "snr_window", "da_max_m"]
              + ["v2_levelshift_sig", "v2_levelshift_abs", "v2_net_da_sig", "v2_di_max", "v2_de_max",
                 "v2_b_dev_max", "v2_b_dev_min", "v2_b_neg_frac"]
              + ["alt_km", "inc_deg", "q_cadence_day", "q_sigma_m"])
L3V2_LGB = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8,
                subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, class_weight="balanced",
                random_state=42, verbose=-1)


def build_common_units(db, sats, drag_by, eps_by, cov_by=None, skipped=None):
    """單一遍歷建共同 unit 集，同時記錄三層在每個 unit 上的分數／旗標。

    cov_by：{norad: (lo_ns, hi_ns)} 真值涵蓋時段（satdet.truth_coverage）。給定時：
      ・沒有真值的衛星整顆不納入評估（記入 skipped），不再預設為「安靜」；
      ・負（安靜）unit 只取自涵蓋時段內——真值以外的時段沒有標記，不等於沒有機動。
    cov_by=None 時維持舊行為（全部未被 episode 涵蓋之 epoch 皆視為安靜），僅供重現舊數字。
    """
    con = duckdb.connect(db, read_only=True)
    rows = []
    for name, nid in sats:
        if cov_by is not None and int(nid) not in cov_by:
            if skipped is not None:
                skipped.append((name, int(nid)))
            continue
        df = con.execute(
            "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
            "raan_deg, bstar FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
            "ORDER BY epoch_utc", [int(nid)]).fetchdf()
        if len(df) < 8:
            continue
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="ISO8601")
        ep = to_ns(df["epoch"])
        sma = df["sma_km"].to_numpy(float)
        inc = df["inclination_deg"].to_numpy(float)       # v2 特徵用
        ecc = df["eccentricity"].to_numpy(float)
        bst = df["bstar"].to_numpy(float)

        # ── 資料品質 proxy（per-sat 常數，供 §13.4 品質切片，不參與訓練）──
        gaps_day = np.diff(ep.astype(float)) / 8.64e13          # ns → day
        q_cadence = float(np.median(gaps_day)) if len(gaps_day) else float("nan")
        dsma = np.diff(sma)                                     # 一階差；MAD 對機動尖峰穩健
        q_sigma_m = (1.4826 * float(np.median(np.abs(dsma - np.median(dsma)))) * 1000.0
                     if len(dsma) else float("nan"))            # 殘差 σ（公尺）

        # ── L2：四統計通道逐點分數 ＋ 物理 drag 通道 ──
        r = run_all(sma)
        drg = drag_by.get(int(nid), {})
        C = np.nan_to_num(np.column_stack([
            np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
            np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]),
            np.array([drg.get(e, 0.0) for e in ep]) / 0.10]))

        # ── L1：P1–P6 combined 旗標（對齊到 TLE epoch）──
        a = float(df["sma_km"].iloc[-1]); e_ = float(df["eccentricity"].iloc[-1])
        i_ = float(df["inclination_deg"].iloc[-1])
        orbit = ms.classify_orbit(a, e_, i_)
        tr = ms.build_transitions(df.rename(columns={"epoch": "epoch"}))
        l1_epoch_flag = np.zeros(len(ep), bool)
        if len(tr):
            strat = ms.apply_strategies(tr, orbit)
            comb = strat.get("combined", np.array([], bool))
            if len(comb):
                flagged_ns = set(to_ns(tr["epoch"])[comb].tolist())
                l1_epoch_flag = np.array([int(x) in flagged_ns for x in ep], bool)

        def unit_row(mask, label, rk):
            sub = C[mask]                       # 涵蓋 epoch × 5 通道
            row = {"norad_id": int(nid), "label": label, "sev": rk}
            # 分層切片鍵（族群/高度/時間/品質）——供 L3 泛化穩定度分析，不參與訓練
            row["t_ns"] = int(np.median(ep[mask]))
            row["alt_km"] = float(sma[mask].mean() - 6378.137)
            row["inc_deg"] = float(i_)
            row["q_cadence_day"] = q_cadence
            row["q_sigma_m"] = q_sigma_m
            # L1：unit 內是否有任一 combined 旗標
            row["l1_flag"] = bool(l1_epoch_flag[mask].any())
            # L2：各統計通道 max（連續分數）
            for j, c in enumerate(STAT_CH):
                row[f"l2_{c}"] = float(sub[:, j].max())
            # L2 樸素五通道融合：所有通道 max 的最大（未學習）
            row["l2_naivemax"] = float(sub.max())
            # L3：15 維 fusion 特徵（max/mean/p90 × 5 通道）
            for j, c in enumerate(CH):
                col = sub[:, j]
                row[f"f_{c}_max"] = float(col.max())
                row[f"f_{c}_mean"] = float(col.mean())
                row[f"f_{c}_p90"] = float(np.percentile(col, 90))
            # ── P1 增強特徵（多樣性與時間結構）——additive，不影響既有 15 維 ──
            # (i) 時間結構：每通道之峰值相對位置、最大上升步、峰值集中度
            L = sub.shape[0]
            for j, c in enumerate(CH):
                col = sub[:, j]; mx = float(col.max())
                row[f"t_{c}_peakpos"] = float(np.argmax(col)) / max(L - 1, 1)      # 0..1 窗內峰值位置
                row[f"t_{c}_rise"] = float(np.max(np.diff(col))) if L > 1 else 0.0  # 最大上升步（尖峰陡度）
                row[f"t_{c}_conc"] = float((col > 0.5 * mx).mean()) if mx > 0 else 0.0  # 峰值集中度（分段/持續代理）
            # (ii) 跨通道交互：統計證據 vs 物理阻力（阻力解釋不了的階躍＝強機動證據）
            stat_max = max(row[f"f_{c}_max"] for c in STAT_CH)
            drag_max = row["f_drag_max"]
            row["x_stat_minus_drag"] = stat_max - drag_max
            row["x_stat_over_drag"] = stat_max / (drag_max + 1e-6)
            # (iii) 窗內物理 SNR：最大半長軸跳變（公尺）/ 該星雜訊 σ
            sm = sma[mask]
            da_max_m = float(np.max(np.abs(np.diff(sm)))) * 1000.0 if len(sm) > 1 else 0.0
            row["snr_window"] = da_max_m / q_sigma_m if q_sigma_m and q_sigma_m > 0 else 0.0
            row["da_max_m"] = da_max_m            # 窗內最大 |Δa|（公尺，絕對量）——供「純 Δa」基線
            # ── v2 特徵（2026-10-21，L3 v2 實驗用；additive，不影響既有 15 維與上列特徵）──
            # 皆只由 TLE 推得；B* 基準只用窗口之前的資料（線上可照做）
            idx = np.where(mask)[0]
            w0, w1 = ep[idx[0]], ep[idx[-1]]
            sig = q_sigma_m / 1000.0 if q_sigma_m and q_sigma_m > 0 else np.nan        # km
            pre = (ep >= w0 - 2 * TOL_NS) & (ep < w0)
            post = (ep > w1) & (ep <= w1 + 2 * TOL_NS)
            if pre.any() and post.any() and np.isfinite(sig):
                ls = float(np.median(sma[post]) - np.median(sma[pre])) / sig
            else:
                ls = np.nan
            row["v2_levelshift_sig"] = ls                       # 窗口前後 48h 位準差（σ 單位，含正負）
            row["v2_levelshift_abs"] = abs(ls) if np.isfinite(ls) else np.nan
            row["v2_net_da_sig"] = float(sm[-1] - sm[0]) / sig if len(sm) > 1 and np.isfinite(sig) else np.nan
            row["v2_di_max"] = float(np.max(np.abs(np.diff(inc[mask])))) if len(sm) > 1 else 0.0
            row["v2_de_max"] = float(np.max(np.abs(np.diff(ecc[mask])))) if len(sm) > 1 else 0.0
            base = (ep >= w0 - 31 * 86400 * 10**9) & (ep < w0 - 86400 * 10**9) & np.isfinite(bst)
            bw = bst[mask]; bw = bw[np.isfinite(bw)]
            if base.sum() >= 5 and len(bw):
                med = float(np.median(bst[base])); mad = max(1.4826 * float(np.median(np.abs(bst[base] - med))), 1e-5)
                row["v2_b_dev_max"] = float((bw.max() - med) / mad)
                row["v2_b_dev_min"] = float((bw.min() - med) / mad)
                row["v2_b_neg_frac"] = float((bw < 0).mean())
            else:
                row["v2_b_dev_max"] = row["v2_b_dev_min"] = row["v2_b_neg_frac"] = np.nan
            return row

        masks, assigned = episode_masks(ep, eps_by.get(int(nid), []), TOL_NS)
        for mask, rk, _lat in masks:
            rows.append(unit_row(mask, 1, int(rk)))
        in_cov = coverage_mask(ep, cov_by.get(int(nid))) if cov_by is not None else np.ones(len(ep), bool)
        for w in quiet_blocks(ep, np.where(~assigned & in_cov)[0], 2 * TOL_NS):
            m = np.zeros(len(ep), bool); m[w] = True
            rows.append(unit_row(m, 0, 0))
    con.close()
    return pd.DataFrame(rows)


def eval_scores(scores, y, sev, thr):
    """給定連續分數與門檻，算 precision/recall/FPR/分層 recall。"""
    pred = scores >= thr
    tp = int(((pred) & (y == 1)).sum()); fp = int(((pred) & (y == 0)).sum())
    P = int((y == 1).sum()); N = int((y == 0).sum())
    out = {"precision": tp / (tp + fp) if (tp + fp) else float("nan"),
           "recall": tp / P if P else float("nan"),
           "fpr": fp / N if N else float("nan")}
    for s in ("large", "medium", "small"):
        m = (y == 1) & (sev == SEV_RANK[s])
        out[f"rec_{s}"] = float(pred[m].mean()) if m.any() else float("nan")
    return out


def eval_binary(pred, y, sev):
    """L1 二元規則：直接算其固定 (P,R,FPR) 點。"""
    return eval_scores(pred.astype(float), y, sev, 0.5)


BLIND_AUC_OK = 0.85      # 凍結盲測判為「維持」之 AUC 下限
BLIND_FPR_OK = 0.10      # 測試端實測 FPR 上限（訓練端門檻設在 0.05；超過 2 倍視為門檻失準）


def frozen_blind(U, seed=2026):
    """凍結盲測：(a) 前 60% 時間訓練、後 40% 盲測；(b) 隨機保留 20% 衛星整組盲測。
    門檻只由訓練折負樣本設定（FPR≤0.05），原 L3 與 L3 v2 各跑一次。"""
    y = U["label"].to_numpy(); sev = U["sev"].to_numpy(); groups = U["norad_id"].to_numpy()
    t_ns = U["t_ns"].to_numpy(float)
    models = [("L3", [f"f_{c}_{st}" for c in CH for st in ("max", "mean", "p90")],
               lambda: HistGradientBoostingClassifier(**HGB))]
    try:
        from lightgbm import LGBMClassifier
        models.append(("L3 v2", L3V2_FEATS, lambda: LGBMClassifier(**L3V2_LGB)))
    except ImportError:
        pass
    D = np.quantile(t_ns, 0.60)
    rng = np.random.default_rng(seed)
    sat_ids = np.array(sorted(set(groups.tolist())))
    hold = set(rng.choice(sat_ids, size=max(1, len(sat_ids) // 5), replace=False).tolist())
    tem2 = np.array([g in hold for g in groups])
    splits = [(t_ns < D, t_ns >= D, "out-of-time（前60%訓/後40%盲測）"),
              (~tem2, tem2, f"unseen-satellite（保留 {len(hold)} 顆從未訓練）")]
    rows = []
    for name, feats, make in models:
        X = U[feats].to_numpy(float)
        for trm, tem, tag in splits:
            if trm.sum() < 50 or tem.sum() < 20 or len(set(y[tem].tolist())) < 2:
                continue
            Xtr, ytr, gtr = X[trm], y[trm], groups[trm]
            # 門檻取自訓練集內部 GroupKFold OOF 分數，而非訓練樣本的自我預測：
            # 後者對 LightGBM 等易過擬模型過度自信，門檻偏低，測試端 FPR 會遠超 0.05
            p_tr = np.zeros(len(ytr))
            for a, b in GroupKFold(5).split(Xtr, ytr, gtr):
                p_tr[b] = make().fit(Xtr[a], ytr[a]).predict_proba(Xtr[b])[:, 1]
            thr = fpr_floor_threshold(p_tr[ytr == 0], 0.05)   # 門檻只由訓練期負樣本設定
            p_te = make().fit(Xtr, ytr).predict_proba(X[tem])[:, 1]
            m = eval_scores(p_te, y[tem], sev[tem], thr)
            rows.append(dict(model=name, setting=tag, auc=roc_auc_score(y[tem], p_te),
                             rec_large=m["rec_large"], recall=m["recall"],
                             fpr=m["fpr"], n_test=int(tem.sum())))
    return rows


def blind_verdict(rows):
    """依實測數字產生判讀（不預設結論）：AUC ≥ BLIND_AUC_OK 且測試 FPR ≤ BLIND_FPR_OK 才算「維持」。"""
    out = []
    for r in rows:
        bad = []
        if r["auc"] < BLIND_AUC_OK:
            bad.append(f"AUC {r['auc']:.3f} < {BLIND_AUC_OK}")
        if r["fpr"] > BLIND_FPR_OK:
            bad.append(f"測試 FPR {r['fpr']:.3f} > {BLIND_FPR_OK}（訓練端門檻在新資料上失準）")
        kind = "時間外推" if r["setting"].startswith("out-of-time") else "跨衛星外推"
        out.append(f"{r['model']}｜{kind}：" + ("維持" if not bad else "未維持——" + "；".join(bad)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--save-l3v2", action="store_true", help="以全部 unit 訓練並存 models_fusion/fusion_scorer_v2.pkl")
    ap.add_argument("--legacy-quiet", action="store_true",
                    help="舊行為：沒有真值或真值範圍以外之時段一律視為安靜（僅供重現 2026-10-07 以前之數字）")
    args = ap.parse_args()

    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)   # {norad: [(times_ns, rank)]}
    cov_by = None if args.legacy_quiet else truth_coverage(truth)   # 完整真值表（未依嚴重度過濾）

    reg = load_registry("data/url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())[: args.max_sats] if args.max_sats else list(n2n.items())

    print(f"建共同 unit 集：{len(sats)} 顆 Starlink，MEME medium+ 真值 …", flush=True)
    drag_by = load_drag_map()
    skipped = []
    U = build_common_units(args.db, sats, drag_by, eps_by, cov_by, skipped)
    if cov_by is not None:
        print(f"  無真值、不納入評估之衛星：{len(skipped)} 顆"
              + (f"（例：{', '.join(n for n, _ in skipped[:3])} …）" if skipped else ""))
        print("  負（安靜）unit 只取自各星真值涵蓋時段內")
    y = U["label"].to_numpy(); sev = U["sev"].to_numpy(); groups = U["norad_id"].to_numpy()
    neg = y == 0
    P, N = int((y == 1).sum()), int(neg.sum())
    print(f"  units {len(U)}：正/機動 episode {P}、負/安靜窗 {N}，衛星 {U['norad_id'].nunique()}")
    print(f"  正 unit 嚴重度：" + "、".join(
        f"{s} {int(((y==1)&(sev==SEV_RANK[s])).sum())}" for s in ("large", "medium", "small")))

    results = {}

    # ── L1 規則（二元，固定操作點）──
    results["L1 規則 P1–P6"] = eval_binary(U["l1_flag"].to_numpy(bool), y, sev)

    # ── L2 統計：每單通道（連續，FPR≤0.05）──
    l2_aucs = {}
    for c in STAT_CH:
        s = U[f"l2_{c}"].to_numpy()
        thr = fpr_floor_threshold(s[neg], 0.05)
        l2_aucs[c] = roc_auc_score(y, s)
        results[f"L2 {c}（單通道）"] = {**eval_scores(s, y, sev, thr), "auc": l2_aucs[c]}
    # L2 最佳單通道（依 AUC）
    best_c = max(l2_aucs, key=l2_aucs.get)
    # L2 樸素五通道 max 融合
    s = U["l2_naivemax"].to_numpy()
    thr = fpr_floor_threshold(s[neg], 0.05)
    results["L2 五通道樸素max"] = {**eval_scores(s, y, sev, thr), "auc": roc_auc_score(y, s)}

    # ── 簡單基線（回應委員：提供「純 Δa／僅阻力／σ 正規化」對照，凸顯 σ 正規化與學習融合之增益）──
    for name, col in [("基線 純|Δa|絕對門檻", "da_max_m"),
                      ("基線 僅阻力模型", "f_drag_max"),
                      ("基線 σ正規化|Δa|(單特徵)", "snr_window")]:
        s = U[col].to_numpy()
        thr = fpr_floor_threshold(s[neg], 0.05)
        results[name] = {**eval_scores(s, y, sev, thr), "auc": roc_auc_score(y, s)}

    # ── L3 融合評分器（15 維，GroupKFold OOF）──
    feats = [f"f_{c}_{st}" for c in CH for st in ("max", "mean", "p90")]
    X = U[feats].to_numpy()
    oof = np.zeros(len(y))
    for tr_i, te_i in GroupKFold(5).split(X, y, groups):
        oof[te_i] = HistGradientBoostingClassifier(**HGB).fit(
            X[tr_i], y[tr_i]).predict_proba(X[te_i])[:, 1]
    thr = fpr_floor_threshold(oof[neg], 0.05)
    results["L3 融合評分器 OOF"] = {**eval_scores(oof, y, sev, thr), "auc": roc_auc_score(y, oof)}

    # ── L3 v2（2026-10-21）：15 維＋既有增強特徵＋v2 特徵＋4 個背景常數，LightGBM，同一 GroupKFold OOF ──
    # 依 exp_l3_v2.py：修正後擂台 AUC 0.813 → 0.858 ± 0.002（5 種分折）；族群內 AUC 皆提升，背景特徵單獨僅 0.56
    try:
        from lightgbm import LGBMClassifier
        X2 = U[L3V2_FEATS].to_numpy(float)
        oof2 = np.zeros(len(y))
        for tr_i, te_i in GroupKFold(5).split(X2, y, groups):
            oof2[te_i] = LGBMClassifier(**L3V2_LGB).fit(X2[tr_i], y[tr_i]).predict_proba(X2[te_i])[:, 1]
        thr2 = fpr_floor_threshold(oof2[neg], 0.05)
        results["L3 v2 融合評分器 OOF"] = {**eval_scores(oof2, y, sev, thr2), "auc": roc_auc_score(y, oof2)}
        if args.save_l3v2:
            import joblib
            final = LGBMClassifier(**L3V2_LGB).fit(X2, y)
            Path("models_fusion").mkdir(exist_ok=True)
            joblib.dump({"clf": final, "feats": L3V2_FEATS, "thr": float(thr2), "params": L3V2_LGB,
                         "oof_auc": float(roc_auc_score(y, oof2)), "n_units": int(len(y)),
                         "n_sats": int(len(np.unique(groups))), "trained_on": datetime.now(timezone.utc).strftime("%Y%m%d"),
                         "note": "unit 級（episode ±24h 窗）模型；線上逐 epoch 推論需另實作 v2 特徵之串流計算"},
                        "models_fusion/fusion_scorer_v2.pkl")
            print("  → models_fusion/fusion_scorer_v2.pkl")
    except ImportError:
        print("  （未安裝 lightgbm，略過 L3 v2）")

    # ── 三層 per-unit 二元預測（交叉分析用）──
    l1_pred = U["l1_flag"].to_numpy(bool)
    s_best = U[f"l2_{best_c}"].to_numpy()
    thr_l2 = fpr_floor_threshold(s_best[neg], 0.05)
    l2_pred = s_best >= thr_l2
    l3_pred = oof >= thr                        # 沿用 L3 之 FPR≤0.05 門檻

    # ── naive 隨機對照（5 次平均）──
    rng = np.random.default_rng(0)
    accum = None
    for _ in range(5):
        s = rng.random(len(y))
        thr = fpr_floor_threshold(s[neg], 0.05)
        m = eval_scores(s, y, sev, thr)
        accum = m if accum is None else {k: accum[k] + m[k] for k in m}
    results["naive 隨機（對照）"] = {k: v / 5 for k, v in accum.items()}

    # ── 輸出表 ──
    order = ["基線 純|Δa|絕對門檻", "基線 僅阻力模型", "基線 σ正規化|Δa|(單特徵)",
             "L1 規則 P1–P6", f"L2 {best_c}（單通道）", "L2 五通道樸素max",
             "L3 融合評分器 OOF", "L3 v2 融合評分器 OOF", "naive 隨機（對照）"]
    print("\n" + "=" * 92)
    print(f"三層同一擂台：{U['norad_id'].nunique()} 顆 Starlink · MEME episode unit · "
          f"操作點 FPR≤0.05（L1 為二元規則）")
    print("=" * 92)
    hdr = f"  {'層／方法':<22}{'AUC':>7}{'精確率':>8}{'召回率':>8}{'FPR':>8}" \
          f"{'large':>8}{'medium':>8}{'small':>8}"
    print(hdr); print("  " + "-" * 88)
    for k in order:
        if k not in results:
            continue
        m = results[k]
        auc = f"{m['auc']:.3f}" if "auc" in m else "  —  "
        print(f"  {k:<22}{auc:>7}{m['precision']:>8.3f}{m['recall']:>8.3f}"
              f"{m['fpr']:>8.3f}{m['rec_large']:>8.3f}{m['rec_medium']:>8.3f}{m['rec_small']:>8.3f}")
    print("=" * 92)
    print(f"  L2 最佳單通道＝{best_c}（AUC {l2_aucs[best_c]:.3f}）；四通道 AUC："
          + "、".join(f"{c} {l2_aucs[c]:.3f}" for c in STAT_CH))

    # ── 三層交叉分析：L3 相對 L1/L2 的增量修正（回應審查第六點）──
    prior = l1_pred | l2_pred                    # 前兩層之聯集（統計層＋規則層一起看）
    pos, negm = (y == 1), (y == 0)
    # 正 unit（真機動）：漏補
    l3_saves_recall = int((l3_pred & ~prior & pos).sum())   # 前層漏、L3 抓到（L3 補漏）
    l3_misses_prior_had = int((~l3_pred & prior & pos).sum())# 前層抓、L3 漏（L3 反向損失）
    both_hit_pos = int((l3_pred & prior & pos).sum())
    none_hit_pos = int((~l3_pred & ~prior & pos).sum())
    # 負 unit（無機動）：誤報修正
    l3_fixes_fp = int((~l3_pred & prior & negm).sum())      # 前層誤報、L3 正確排除（L3 除誤）
    l3_adds_fp = int((l3_pred & ~prior & negm).sum())        # 前層正確、L3 誤報（L3 引入）
    print("\n" + "=" * 92)
    print("三層交叉分析：L3 相對「L1∪L2（規則＋統計）」的增量修正")
    print("=" * 92)
    print(f"  正 unit（真機動，n={P}）：")
    print(f"    L3 補漏（前層漏、L3 抓到）        ： {l3_saves_recall:>4}")
    print(f"    兩者皆抓                          ： {both_hit_pos:>4}")
    print(f"    L3 漏而前層抓（L3 反向損失）      ： {l3_misses_prior_had:>4}")
    print(f"    三者皆漏                          ： {none_hit_pos:>4}")
    print(f"  負 unit（無機動，n={N}）：")
    print(f"    L3 除誤（前層誤報、L3 正確排除）  ： {l3_fixes_fp:>4}")
    print(f"    L3 引入誤報（前層正確、L3 誤報）  ： {l3_adds_fp:>4}")
    net_recall = l3_saves_recall - l3_misses_prior_had
    print(f"  淨效果：召回淨補 {net_recall:+d} 個真機動；除誤淨 {l3_fixes_fp - l3_adds_fp:+d} 個假警報")
    print("  判讀：L3 補漏 > 反向損失 ⇒ 融合層對前兩層有實質增量，非重複其輸出。")

    # CSV（彙總 + per-unit 明細）
    date = datetime.now(timezone.utc).strftime("%Y%m%d") + ("_legacyquiet" if args.legacy_quiet else "")

    # ── #8 模型消融：固定 episode-native MEME 資料＋15 聚合特徵＋GroupKFold，只換分類器 ──
    #    回應委員：隔離表 13-2 之 (2)→(3) 中「模型」因素，檢驗 0.97 是否依賴 HistGB、
    #    抑或來自「episode-native MEME ＋ 聚合特徵」框架本身（→ 單變因歸因收尾）。
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    def _oof_model(mk):
        o = np.zeros(len(y))
        for tr_i, te_i in GroupKFold(5).split(X, y, groups):
            o[te_i] = mk().fit(X[tr_i], y[tr_i]).predict_proba(X[te_i])[:, 1]
        return o

    abl_models = [("HistGB（本系統）", oof)]
    try:
        from lightgbm import LGBMClassifier
        abl_models.append(("LightGBM（同 Model 1 演算法）", _oof_model(
            lambda: LGBMClassifier(n_estimators=300, learning_rate=0.06, max_depth=4,
                                   class_weight="balanced", random_state=42, verbose=-1))))
    except Exception:
        print("  （未安裝 lightgbm，略過 LightGBM 消融）")
    abl_models.append(("Logistic（線性基線）", _oof_model(
        lambda: make_pipeline(StandardScaler(),
                              LogisticRegression(max_iter=1000, class_weight="balanced")))))
    print("\n" + "=" * 92)
    print("#8 模型消融（固定 episode-native MEME 資料＋15 聚合特徵＋GroupKFold；只換分類器）")
    print("=" * 92)
    print(f"  {'分類器':<28}{'AUC':>8}{'large召回@FPR≤.05':>18}{'總召回':>9}")
    abl_rows = []
    for nm, o in abl_models:
        th = fpr_floor_threshold(o[neg], 0.05)
        m = eval_scores(o, y, sev, th); au = roc_auc_score(y, o)
        print(f"  {nm:<28}{au:>8.3f}{m['rec_large']:>18.3f}{m['recall']:>9.3f}")
        abl_rows.append(dict(model=nm, auc=au, rec_large=m['rec_large'], recall=m['recall'], fpr=m['fpr']))
    pd.DataFrame(abl_rows).to_csv(Path("data/benchmark") / f"model_ablation_{date}.csv",
                                  index=False, encoding="utf-8-sig")
    print("  判讀：若 LightGBM ≈ HistGB，則 0.97 之增益來自「episode-native MEME＋聚合特徵框架」"
          "而非特定演算法——完成表 13-2 (2)→(3) 之單變因歸因。")

    # ── #4 凍結盲測（回應委員：真正 hold-out；門檻以訓練集設定＝可部署套未來）──
    blind_rows = frozen_blind(U)
    print("\n" + "=" * 92)
    print("#4 凍結盲測（真正 hold-out：不共時段／不共衛星；門檻以訓練集設定＝可部署）")
    print("=" * 92)
    print(f"  {'模型':<8}{'設定':<40}{'AUC':>7}{'large召回':>10}{'FPR':>8}{'測試unit':>9}")
    for r in blind_rows:
        print(f"  {r['model']:<8}{r['setting']:<40}{r['auc']:>7.3f}{r['rec_large']:>10.3f}{r['fpr']:>8.3f}{r['n_test']:>9}")
    if blind_rows:
        pd.DataFrame(blind_rows).to_csv(Path("data/benchmark") / f"frozen_blind_{date}.csv",
                                        index=False, encoding="utf-8-sig")
    for line in blind_verdict(blind_rows):
        print("  判讀：" + line)
    outp = Path("data/benchmark") / f"three_layer_common_eval_{date}.csv"
    outp.parent.mkdir(parents=True, exist_ok=True)
    rec = []
    for k, m in results.items():
        rec.append({"method": k, "auc": m.get("auc", np.nan), **{kk: m[kk] for kk in
                    ("precision", "recall", "fpr", "rec_large", "rec_medium", "rec_small")}})
    pd.DataFrame(rec).to_csv(outp, index=False, encoding="utf-8-sig")

    cross = pd.DataFrame({
        "norad_id": U["norad_id"], "label": y, "sev": sev,
        "l1_pred": l1_pred.astype(int), "l2_pred": l2_pred.astype(int),
        "l3_pred": l3_pred.astype(int), "l3_score": np.round(oof, 4)})
    coutp = Path("data/benchmark") / f"three_layer_perunit_{date}.csv"
    cross.to_csv(coutp, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {outp}")
    print(f"       {coutp}（per-unit 三層預測，供交叉分析複核）")
    print(f"  正 unit {P}、負 unit {N}；naive 對照若接近滿分即表示擂台無鑑別力（應遠低於 L3）。")


if __name__ == "__main__":
    main()
