#!/usr/bin/env python3
"""tasa14_l3_fusion.py — ② pred 通道併入 + L3 訓練式融合(LOSO) + ⑤ 類別操作點。

設計:
  候選產生(高召回):detect_iter2(k=3) ∪ detect_pred(k=6,deg1) ∪ L2 四通道事件,
  1 天內合併為單一候選。
  特徵(全部 σ 正規化/域不變):z_ls(位準位移 SNR)、z_pe(預測誤差 SNR)、
  z_step(單步 SNR)、cusum/bocpd/ssa/mad 逐點分數(±1 天內最大)、局部 cadence。
  標籤:候選落於真值機動窗 ±1.5 天 → 1。
  訓練:HistGradientBoosting,**留一衛星交叉(LOSO)**——被評星永不參與訓練;
  決策門檻 θ 於訓練星上選(⑤:cadence 兩類——中位更新間隔 <0.45 天/≥0.45 天
  ——各自選 θ;類別規則事前定義,θ 僅用訓練星,無測試洩漏)。
  評估:接受之候選 → 1 天合併 → 與其他方法完全相同之貪婪一對一配對。
用法:python tasa14_l3_fusion.py [--rebuild](重建特徵快取)
輸出:data/benchmark/tasa14_l3_fusion_20260804.csv(逐星)
     data/benchmark/tasa14_fusion_features_20260804.csv(特徵快取)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from sklearn.ensemble import HistGradientBoostingClassifier
from scipy import stats

import tasa14_compare as tc
from tasa14_compare import (load_a, load_events, SATS, detect_iter2, adaptive_lw,
                            _shift_signal_w, detrend_step, robust_sigma)
from tasa14_pdf_baseline import detect_pred, _pred_error, _adaptive_w
import tasa14_l2_compare as l2
import statistical_detectors as sd

FEAT_CSV = Path("data/benchmark/tasa14_fusion_features_20260804.csv")
OUT_CSV = Path("data/benchmark/tasa14_l3_fusion_20260804.csv")

# --ext19:擴充至 19 星(SPOT-2/3/4/5+Sentinel-6B;window-only 真值)
# --ext23:再擴充至 23 星(+GRACE-A/B、GRACE-FO-C/D;SOE MANV 真值)
EXT23 = "--ext23" in sys.argv
EXT19 = "--ext19" in sys.argv or EXT23
BASE_FEAT = Path("data/benchmark/tasa14_fusion_features_20260804.csv")
if EXT23:
    from tasa23_ext_arena import ALL_SATS23, load_events_ext2
    SATS_LIST = ALL_SATS23
    EVENTS_LOADER = load_events_ext2
    FEAT_CSV = Path("data/benchmark/tasa23_fusion_features_20260804.csv")
    STACK_CSV = Path("data/benchmark/tasa23_l3_stack_20260804.csv")
    BASE_FEAT = Path("data/benchmark/tasa19_fusion_features_20260804.csv")
elif EXT19:
    from tasa19_ext_arena import EXT_SATS, load_events_ext
    SATS_LIST = list(SATS) + list(EXT_SATS)
    EVENTS_LOADER = load_events_ext
    FEAT_CSV = Path("data/benchmark/tasa19_fusion_features_20260804.csv")
    STACK_CSV = Path("data/benchmark/tasa19_l3_stack_20260804.csv")
else:
    SATS_LIST = list(SATS)
    EVENTS_LOADER = load_events
    STACK_CSV = Path("data/benchmark/tasa14_l3_stack_20260804.csv")
CAND_MERGE_D = 1.0
CADENCE_SPLIT_D = 0.45          # ⑤ 類別規則(事前定義):中位更新間隔
THETA_GRID = np.arange(0.10, 0.91, 0.05)
FEATS = ["z_ls", "z_pe", "z_step", "s_cusum", "s_bocpd", "s_ssa", "s_mad", "cadence_d",
         "det_it2", "det_pr"]   # 後兩者=強偵測器同意旗標(iter2 k=8 / pred k=12)

# --q23:Q2/Q3 特徵擴充(handoff_ilrs_orbit_class_findings_20260804.md;
# FP 時間窗歸因閘門後定案:W2 劣化窗旗標有靶(FP 1.45×,p=0.035)、
# W1 為召回側問題亦納入、W3 無群聚故不納入;另加局部 cadence 與
# 「局部 cadence ÷ 同期全池中位」相對化特徵)。架構/θ 網格全數凍結。
Q23 = "--q23" in sys.argv
Q23_FEATS = ["local_gap_d", "cad_ratio", "in_w1", "in_w2"]
PEER_YEARLY_CSV = Path("data/benchmark/tasa14_14class_peer_yearly_20260804.csv")
W1 = (pd.Timestamp("2009-01-01", tz="UTC"), pd.Timestamp("2010-12-31", tz="UTC"))
W2 = (pd.Timestamp("2013-10-01", tz="UTC"), pd.Timestamp("2014-12-31", tz="UTC"))


def augment_q23(df):
    """為特徵表加 Q2/Q3 欄位:local_gap_d(候選 ±15 天實際 TLE 中位間隔)、
    cad_ratio(local_gap ÷ 同年全候選池中位 cadence,吸收全域追蹤基建趨勢)、
    in_w1/in_w2(已知非機動混淆時間窗旗標)。"""
    py = pd.read_csv(PEER_YEARLY_CSV)
    fleet = py.groupby("year")["cadence_d"].median()
    fyears = fleet.index.to_numpy()

    def fleet_gap(year):
        return float(fleet.loc[fyears[np.argmin(np.abs(fyears - year))]])

    out = []
    for nid, g in df.groupby("norad", sort=False):
        t, _ = load_a(nid)
        tsec = t.astype("int64").to_numpy() / 1e9
        g = g.copy()
        csec = g["epoch"].astype("int64").to_numpy() / 1e9
        med_cad = float(g["cadence_d"].iloc[0])
        lg = np.empty(len(g))
        for i, cs in enumerate(csec):
            m = np.abs(tsec - cs) <= 15 * 86400
            gaps = np.diff(tsec[m]) / 86400.0
            gaps = gaps[gaps > 0]
            lg[i] = float(np.median(gaps)) if len(gaps) >= 3 else med_cad
        g["local_gap_d"] = lg
        yrs = g["epoch"].dt.year.to_numpy()
        g["cad_ratio"] = lg / np.array([fleet_gap(y) for y in yrs])
        g["in_w1"] = ((g["epoch"] >= W1[0]) & (g["epoch"] <= W1[1])).astype(int)
        g["in_w2"] = ((g["epoch"] >= W2[0]) & (g["epoch"] <= W2[1])).astype(int)
        out.append(g)
    return pd.concat(out, ignore_index=True)


# ── 逐點訊號 ──

def signal_ls(t, a):
    """位準位移 SNR 序列(單輪遮罩後重估,與 detect_iter2 同構)。"""
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    w = adaptive_lw(tsec)
    mask = np.zeros(n, bool)
    sig = _shift_signal_w(a, tsec, mask, w)
    for _ in range(2):
        s = sig[np.isfinite(sig) & ~mask]
        sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
        if not np.isfinite(sdv) or sdv == 0:
            break
        newmask = np.zeros(n, bool)
        for j in np.where(np.abs(sig) > 8 * sdv)[0]:
            newmask[max(0, j - w):min(n, j + w)] = True
        if newmask.sum() == mask.sum():
            break
        mask = newmask
        sig = _shift_signal_w(a, tsec, mask, w)
    s = sig[np.isfinite(sig) & ~mask]
    sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else 1e-9
    return np.abs(sig) / max(sdv, 1e-9)


def signal_pe(t, a):
    """前向預測誤差 SNR 序列(deg1,自適應 w;單輪剔除後重估)。"""
    tsec = t.astype("int64").to_numpy() / 1e9
    w = _adaptive_w(tsec)
    bad = np.zeros(len(a), bool)
    e = _pred_error(tsec, a, w, 1, bad)
    s = e[np.isfinite(e)]
    sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
    if np.isfinite(sdv) and sdv > 0:
        bad = np.isfinite(e) & (np.abs(e) > 8 * sdv)
        e = _pred_error(tsec, a, w, 1, bad)
        s = e[np.isfinite(e) & ~bad]
        sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else sdv
    return np.abs(e) / max(sdv, 1e-9)


def signal_step(t, a):
    s = detrend_step(a)                        # 對齊 a[1:]
    sdv = robust_sigma(s)
    z = np.full(len(a), np.nan)
    z[1:] = np.abs(s) / max(sdv, 1e-9)
    return z


def l2_scores(t, a):
    """滑動窗跑 L2,收逐點分數(重疊窗取最大)與各通道事件 epoch。"""
    n = len(a)
    sc = {c: np.full(n, np.nan) for c in l2.CHANS}
    evs = {c: [] for c in l2.CHANS}
    start = 0
    while start < n:
        seg = slice(start, min(n, start + l2.WIN))
        aw = a[seg]; tw = t[seg]
        if len(aw) >= 24:
            res = sd.run_all(aw)
            for c in l2.CHANS:
                s = np.asarray(res[c]["scores"], float)
                if len(s) == len(aw):
                    idx = np.arange(seg.start, seg.start + len(aw))
                    cur = sc[c][idx]
                    sc[c][idx] = np.where(np.isnan(cur), s, np.maximum(cur, s))
                for k in res[c]["events"]:
                    if l2.EDGE <= k < len(aw) - l2.EDGE:
                        evs[c].append(tw[k])
        if start + l2.WIN >= n:
            break
        start += l2.STEP
    return sc, evs


def build_features(rebuild=False):
    if FEAT_CSV.exists() and not rebuild:
        d = pd.read_csv(FEAT_CSV)
        d["epoch"] = pd.to_datetime(d["epoch"], utc=True, format="mixed")
        return d
    # 增量:沿用前一級快取(14→19→23),只補缺星
    done = pd.DataFrame()
    if EXT19 and BASE_FEAT.exists():
        done = pd.read_csv(BASE_FEAT)
        done["epoch"] = pd.to_datetime(done["epoch"], utc=True, format="mixed")
    events = EVENTS_LOADER()
    tol = pd.Timedelta(days=float(tc.TOL_D))
    rows = []
    have = set(done["norad"]) if len(done) else set()
    for nid, nm in [s for s in SATS_LIST if s[0] not in have]:
        t, a = load_a(nid)
        if t is None or len(a) < 60 or nid not in events:
            continue
        ev = events[nid]
        lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
        evw = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
        if len(evw) == 0:
            continue
        tsec = t.astype("int64").to_numpy() / 1e9
        gaps = np.diff(tsec) / 86400.0
        cad = float(np.median(gaps[gaps > 0]))
        z_ls = signal_ls(t, a)
        z_pe = signal_pe(t, a)
        z_st = signal_step(t, a)
        sc, evs = l2_scores(t, a)
        # 候選:寬鬆聯集
        cands = list(detect_iter2(t, a, 3)) + list(detect_pred(t, a, 6, 1, 1))
        for c in l2.CHANS:
            cands += list(l2.merge_epochs(evs[c]))
        cands = l2.merge_epochs(cands, CAND_MERGE_D)
        cands = pd.to_datetime([c for c in cands if lo <= c <= hi])
        csec = cands.astype("int64").to_numpy() / 1e9
        # 強偵測器同意旗標
        it2 = pd.to_datetime(detect_iter2(t, a, 8)).astype("int64").to_numpy() / 1e9
        prd = pd.to_datetime(detect_pred(t, a, 12, 1, 1)).astype("int64").to_numpy() / 1e9
        near = lambda arr, cs: bool(len(arr)) and bool(np.min(np.abs(arr - cs)) <= 0.75 * 86400)
        for ce, cs in zip(cands, csec):
            m = np.abs(tsec - cs) <= 1.0 * 86400
            if not m.any():
                continue
            def mx(arr):
                v = arr[m]
                v = v[np.isfinite(v)]
                return float(v.max()) if len(v) else 0.0
            lab = int(any((e["ws"] - tol <= ce <= e["we"] + tol) for _, e in evw.iterrows()))
            rows.append(dict(norad=nid, name=nm, epoch=ce, label=lab,
                             z_ls=mx(z_ls), z_pe=mx(z_pe), z_step=mx(z_st),
                             s_cusum=mx(sc["cusum"]), s_bocpd=mx(sc["bocpd"]),
                             s_ssa=mx(sc["ssa"]), s_mad=mx(sc["mad3sig"]),
                             cadence_d=cad,
                             det_it2=int(near(it2, cs)), det_pr=int(near(prd, cs))))
        print(f"  {nm:14s} 候選 {len(cands):4d} 正例率 {np.mean([r['label'] for r in rows if r['norad']==nid]):.2f}", flush=True)
    df = pd.DataFrame(rows)
    if len(done):
        df = pd.concat([done, df], ignore_index=True)
    df.to_csv(FEAT_CSV, index=False, encoding="utf-8-sig")
    return df


# ── LOSO 訓練與評估 ──

def dets_from_accept(sub, proba, theta):
    acc = sub.loc[proba >= theta, "epoch"]
    return l2.merge_epochs(list(acc), CAND_MERGE_D)


def star_f1(nid, dets, events):
    t, a = load_a(nid)
    ev = events[nid]
    lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    return l2.metrics(dets, ev, lo, hi)


def main():
    rebuild = "--rebuild" in sys.argv
    print("建立/載入特徵…")
    df = build_features(rebuild)
    events = load_events()
    print(f"特徵表:{len(df)} 候選、正例率 {df.label.mean():.2f}")
    sats = [n for n, _ in SATS if n in set(df.norad)]
    cad_map = df.groupby("norad")["cadence_d"].first().to_dict()
    cls_map = {n: ("dense" if cad_map[n] < CADENCE_SPLIT_D else "sparse") for n in sats}

    per_star = []
    for held in sats:
        tr = df[df.norad != held]
        te = df[df.norad == held]
        clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08,
                                             random_state=42)
        clf.fit(tr[FEATS], tr["label"])
        # ⑤ θ 於訓練星上按 cadence 類別選(被評星之類別規則事前定義)
        cls = cls_map[held]
        tr_sats = [n for n in sats if n != held and cls_map[n] == cls]
        if len(tr_sats) < 2:
            tr_sats = [n for n in sats if n != held]
        best_th, best_f1 = 0.5, -1
        tr_proba = {n: clf.predict_proba(df[df.norad == n][FEATS])[:, 1] for n in tr_sats}
        for th in THETA_GRID:
            f1s = []
            for n in tr_sats:
                dets = dets_from_accept(df[df.norad == n], tr_proba[n], th)
                f1s.append(star_f1(n, dets, events)["f1"])
            m = float(np.mean(f1s))
            if m > best_f1:
                best_f1, best_th = m, th
        proba = clf.predict_proba(te[FEATS])[:, 1]
        dets = dets_from_accept(te, proba, best_th)
        met = star_f1(held, dets, events)
        per_star.append(dict(norad=held, name=te["name"].iloc[0], cls=cls,
                             theta=best_th, **met))
        print(f"  {te['name'].iloc[0]:14s} [{cls:6s} θ={best_th:.2f}] "
              f"P={met['precision']:.2f} R={met['recall']:.2f} F1={met['f1']:.3f}", flush=True)

    out = pd.DataFrame(per_star).sort_values("f1", ascending=False)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\nL3 融合(LOSO)平均 F1={out.f1.mean():.3f} "
          f"(P={out.precision.mean():.2f} R={out.recall.mean():.2f}) 最高={out.f1.max():.3f}")
    print(f"→ {OUT_CSV}")

    # ── 最終檢定:vs 曲線法 oracle ──
    LAUNCH = {22076: 1992, 26997: 2001, 27386: 2002, 33105: 2008, 36508: 2010,
              37781: 2011, 39086: 2013, 41240: 2016, 41335: 2016, 43437: 2018,
              46469: 2020, 46984: 2020, 48621: 2021, 54754: 2022}
    orac = pd.read_csv("data/benchmark/tasa14_pdf_oracle_20260803.csv").set_index("norad")["f1"]
    mine = out.set_index("norad")["f1"]
    common = sorted(set(mine.index) & set(orac.index))
    for lab, ids in [("全 14 星", common),
                     ("發射年 ≥ 2010", [n for n in common if LAUNCH[n] >= 2010])]:
        a_, b_ = mine.loc[ids], orac.loc[ids]
        w, p = stats.wilcoxon(a_, b_)
        print(f"  {lab:12s} n={len(ids)}  L3={a_.mean():.3f} vs oracle={b_.mean():.3f} "
              f"中位差={float((a_-b_).median()):+.3f}  勝/負={int((a_>b_).sum())}/{int((a_<b_).sum())}"
              f"  Wilcoxon(雙尾) p={p:.4f}")


def stacked_dets(n, proba, sub, th_add, th_veto, base):
    """疊加式偵測：iter2(k=8) 基底(base[n]) ∪ 高信心補入(θ_add) − 低信心否決(θ_veto)。
    自 main_stack() 內部閉包提出為模組層級函式，供外部（如 App 即時重算）直接呼叫。"""
    b = base[n]
    bsec = b.astype("int64").to_numpy() / 1e9
    csec = sub["epoch"].astype("int64").to_numpy() / 1e9
    keep_b = np.ones(len(b), bool)
    if th_veto > 0 and len(b):
        for i, bs in enumerate(bsec):
            m = np.abs(csec - bs) <= 1.0 * 86400
            if m.any() and proba[m].max() <= th_veto:
                keep_b[i] = False
    adds = []
    for cs, ce, pr in zip(csec, sub["epoch"], proba):
        if pr >= th_add and (not len(bsec) or np.min(np.abs(bsec - cs)) > 1.0 * 86400):
            adds.append(ce)
    return l2.merge_epochs(list(b[keep_b]) + adds, CAND_MERGE_D)


def run_stack(write_output=True):
    """疊加式 L3(LOSO)主體邏輯，回傳逐星結果 DataFrame。
    write_output=True(CLI 預設)時另寫出 CSV 並印出 vs oracle/全域之 Wilcoxon 檢定，
    行為與舊版 main_stack() 完全相同;write_output=False 供外部即時呼叫，
    不覆寫任何凍結 CSV、不印出過程。"""
    df = build_features(False)
    feats = FEATS
    stack_csv = STACK_CSV
    if Q23:
        if write_output:
            print("加入 Q2/Q3 特徵(local_gap_d/cad_ratio/in_w1/in_w2)…")
        df = augment_q23(df)
        feats = FEATS + Q23_FEATS
        stack_csv = stack_csv.with_name(stack_csv.name.replace("_l3_stack_", "_l3_stack_q23_"))
    events = EVENTS_LOADER()
    sats = [n for n, _ in SATS_LIST if n in set(df.norad)]
    cad_map = df.groupby("norad")["cadence_d"].first().to_dict()
    cls_map = {n: ("dense" if cad_map[n] < CADENCE_SPLIT_D else "sparse") for n in sats}
    if write_output:
        print("預計算各星 iter2(k=8) 基底偵測…")
    base = {}
    for n in sats:
        t, a = load_a(n)
        base[n] = pd.to_datetime(detect_iter2(t, a, 8))
    TH_ADD = [0.55, 0.65, 0.75, 0.85, 1.1]     # 1.1=不補入
    TH_VETO = [0.0, 0.10, 0.20]                # 0=不否決

    per_star = []
    for held in sats:
        tr = df[df.norad != held]; te = df[df.norad == held]
        clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08, random_state=42)
        clf.fit(tr[feats], tr["label"])
        cls = cls_map[held]
        tr_sats = [n for n in sats if n != held and cls_map[n] == cls]
        if len(tr_sats) < 2:
            tr_sats = [n for n in sats if n != held]
        tr_proba = {n: clf.predict_proba(df[df.norad == n][feats])[:, 1] for n in tr_sats}
        best = (1.1, 0.0, -1)
        for ta_ in TH_ADD:
            for tv in TH_VETO:
                f1s = [star_f1(n, stacked_dets(n, tr_proba[n], df[df.norad == n], ta_, tv, base),
                               events)["f1"] for n in tr_sats]
                m = float(np.mean(f1s))
                if m > best[2]:
                    best = (ta_, tv, m)
        ta_, tv, _ = best
        proba = clf.predict_proba(te[feats])[:, 1]
        met = star_f1(held, stacked_dets(held, proba, te, ta_, tv, base), events)
        per_star.append(dict(norad=held, name=te["name"].iloc[0], cls=cls,
                             th_add=ta_, th_veto=tv, **met))
        if write_output:
            print(f"  {te['name'].iloc[0]:14s} [{cls:6s} add≥{ta_:.2f} veto≤{tv:.2f}] "
                  f"P={met['precision']:.2f} R={met['recall']:.2f} F1={met['f1']:.3f}", flush=True)
    out = pd.DataFrame(per_star).sort_values("f1", ascending=False)
    if not write_output:
        return out

    out.to_csv(stack_csv, index=False, encoding="utf-8-sig")
    print(f"\nL3 疊加式(LOSO,n={len(out)})平均 F1={out.f1.mean():.3f} "
          f"(P={out.precision.mean():.2f} R={out.recall.mean():.2f}) 最高={out.f1.max():.3f}")
    print(f"→ {stack_csv}")
    LAUNCH = {22076: 1992, 26997: 2001, 27386: 2002, 33105: 2008, 36508: 2010,
              37781: 2011, 39086: 2013, 41240: 2016, 41335: 2016, 43437: 2018,
              46469: 2020, 46984: 2020, 48621: 2021, 54754: 2022,
              20436: 1990, 22823: 1993, 25260: 1998, 27421: 2002, 66514: 2025,
              27391: 2002, 27392: 2002, 43476: 2018, 43477: 2018}
    orac = pd.read_csv("data/benchmark/tasa14_pdf_oracle_20260803.csv").set_index("norad")["f1"]
    glob = pd.read_csv("data/benchmark/tasa14_pdf_baseline_20260803.csv").set_index("norad")["f1"]
    if EXT19:
        ext_csvs = ["data/benchmark/tasa19_ext_20260804.csv"]
        if EXT23:
            ext_csvs.append("data/benchmark/tasa23_ext_20260804.csv")
        for fn in ext_csvs:
            ext = pd.read_csv(fn).pivot_table(index="norad", columns="method", values="f1")
            orac = pd.concat([orac, ext["pdf_oracle"]])
            glob = pd.concat([glob, ext["pdf_global"]])
    mine = out.set_index("norad")["f1"]
    common = sorted(set(mine.index) & set(orac.index))
    for lab, ids in [(f"全 {len(common)} 星", common),
                     ("發射年 ≥ 2010", [n for n in common if LAUNCH[n] >= 2010])]:
        for opp_lab, opp in [("oracle", orac), ("全域(同待遇)", glob)]:
            a_, b_ = mine.loc[ids], opp.loc[ids]
            w, p = stats.wilcoxon(a_, b_)
            print(f"  {lab:12s} vs {opp_lab:10s} n={len(ids)}  L3={a_.mean():.3f} vs {b_.mean():.3f} "
                  f"勝/負={int((a_>b_).sum())}/{int((a_<b_).sum())}  Wilcoxon(雙尾) p={p:.4f}")
    return out


def main_stack():
    """疊加式 L3:iter2(k=8) 偵測為基底;分類器僅作高信心補入(θ_add)與
    低信心否決(θ_veto)。θ 於訓練星(同 cadence 類)上選,LOSO 無測試洩漏。"""
    run_stack(write_output=True)


if __name__ == "__main__":
    if "--stack" in sys.argv:
        main_stack()
    else:
        main()
