#!/usr/bin/env python3
"""
fs7_review4_analysis.py — 最終審查必辦之技術補算（v6）
======================================================
1. (c, SNR50) 二維聯合 likelihood 等值圖（β 逐點 profile）→ 補充材料圖
2. blocked cluster CV：fold＝衛星×連續時間區塊（防 50% 重疊窗跨 fold 洩漏），
   回報 OOF logloss/Brier（SNR_eff vs Δa/σ），並與原 cluster CV 對照
3. held-out 完整指標：raw 與 recalibrated（於校準期 OOF 擬合 Platt 再校準、
   套用於測試期）之 logloss/Brier；校準斜率/截距＋叢集自助 CI
4. 逐阻力域 c 之 profile 95% CI

輸出：data/benchmark/fs7_review4_analysis.json（摘要值；若重跑結果與既有檔不同，不覆寫，
        改寫入 fs7_review4_analysis_rerun.json 並列出差異）
      data/benchmark/fs7_review4_joint_grid.csv          (c, SNR50) 聯合似然網格（β 逐點 profile）：
                                                         原 26×26 網格（json 峰值之來源，grid=coarse）
                                                         ＋繪圖用 61×61 細網格（grid=fine）
      data/benchmark/fs7_review4_heldout_predictions.csv 時間切分測試期逐試驗之 raw 與 Platt 再校準預測機率
                                                         （Fig. S2 reliability diagram 之來源）
  圖改由 docs/gen_fig_fs7_model_supplement.py 讀上述 CSV 繪製
  （Fig. S1 之 fig_fs7_joint_likelihood、Fig. S2 之 fig_fs7_reliability）。
  註：json 內 held_out_metrics.*.calib_intercept（−0.27）之換算少乘 ln 10；正確值
      （−0.63，與 fs7_final_supplement.json 一致）由繪圖程式以逐試驗預測重算並標示。
輸入：data/benchmark/fs7_injection_trials.csv、space_db.duckdb（read_only；取窗起點曆元）
用法：python fs7_review4_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from fs7_injection_sweep import WIN, load_series
from fs7_injection_sweep_v2 import _logit_fit

SPLIT = "2025-07-01"
CS = np.logspace(-1.3, 1.0, 47)


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def ll_beta_profile(x, y, s50):
    """固定 SNR50、僅對 β 最大化之對數概似（黃金分割粗搜即可）。"""
    lo, hi = 0.5, 20.0
    for _ in range(40):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        def ll(b):
            p = np.clip(1 / (1 + np.exp(-b * (x - np.log10(s50)))), 1e-12, 1 - 1e-12)
            return float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        if ll(m1) < ll(m2):
            lo = m1
        else:
            hi = m2
    b = (lo + hi) / 2
    p = np.clip(1 / (1 + np.exp(-b * (x - np.log10(s50)))), 1e-12, 1 - 1e-12)
    return float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit_at(tr, c):
    x = np.log10(snr_of(tr, c).values)
    y = tr["hit"].values.astype(float)
    return _logit_fit(x, y)


def metrics(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    order = np.argsort(p)
    ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else np.nan
    return ll, brier, auc


def main():
    rng = np.random.default_rng(42)
    tr = pd.read_csv("data/benchmark/fs7_injection_trials.csv")
    series = load_series("space_db.duckdb")
    t0_map = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0_map[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0_map[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    y_all = tr["hit"].values.astype(float)
    n = len(tr)
    result = {}

    # ── 1. (c, SNR50) 聯合 likelihood 等值面 ────────────────────────────────
    print("1. 聯合 likelihood 等值面（β profile）…")
    c_grid = np.logspace(-0.9, 0.4, 26)
    s_grid = np.logspace(-0.2, 1.0, 26)
    LL = np.full((len(s_grid), len(c_grid)), -np.inf)
    for j, c in enumerate(c_grid):
        x = np.log10(snr_of(tr, c).values)
        for i, s50 in enumerate(s_grid):
            LL[i, j] = ll_beta_profile(x, y_all, s50) * n
    LL_rel = LL - LL.max()
    result["joint_likelihood"] = {"ll_max_at": {
        "c": round(float(c_grid[np.unravel_index(LL.argmax(), LL.shape)[1]]), 2),
        "snr50": round(float(s_grid[np.unravel_index(LL.argmax(), LL.shape)[0]]), 2)}}
    print(f"   峰值 (c, SNR50) = ({result['joint_likelihood']['ll_max_at']['c']}, "
          f"{result['joint_likelihood']['ll_max_at']['snr50']})")
    # 繪圖用細網格（不影響上方 json 峰值；與原網格同一 β-profile 似然）
    c_fine = np.logspace(np.log10(0.15), np.log10(1.2), 61)
    s_fine = np.logspace(np.log10(1.5), np.log10(8.0), 61)
    LLf = np.full((len(s_fine), len(c_fine)), -np.inf)
    for j, c in enumerate(c_fine):
        x = np.log10(snr_of(tr, c).values)
        for i, s50 in enumerate(s_fine):
            LLf[i, j] = ll_beta_profile(x, y_all, s50) * n
    rows_g = []
    for tag, cg, sg, L in (("coarse", c_grid, s_grid, LL), ("fine", c_fine, s_fine, LLf)):
        for i, s50 in enumerate(sg):
            for j, c in enumerate(cg):
                rows_g.append({"grid": tag, "c": c, "snr50": s50, "ll_total": L[i, j],
                               "rel_ll": L[i, j] - L.max()})
    pd.DataFrame(rows_g).to_csv("data/benchmark/fs7_review4_joint_grid.csv", index=False,
                                float_format="%.8g")

    # ── 4. 逐阻力域 c 之 profile CI ─────────────────────────────────────────
    band_c = {}
    for b in ("low", "mid", "high"):
        sub = tr[tr["drag_band"] == b]
        lls = np.array([fit_at(sub, c)[2] for c in CS]) * len(sub)
        ih = int(np.argmax(lls))
        okk = np.where(lls >= lls[ih] - 1.92)[0]
        band_c[b] = {"c_hat": round(float(CS[ih]), 2),
                     "profile_ci95": [round(float(CS[okk.min()]), 2),
                                      round(float(CS[okk.max()]), 2)]}
    result["per_band_c"] = band_c
    print("4. 逐阻力域 c：", band_c)

    # ── 2. blocked cluster CV（衛星×連續時間區塊）───────────────────────────
    print("\n2. blocked CV（衛星×連續區塊，無相鄰窗跨 fold）…")
    tr["block"] = tr["norad"].astype(str) + "_" + (tr["win_start"] // (WIN * 5)).astype(str)
    blocks = tr["block"].unique()
    fold_of = {b: i % 5 for i, b in enumerate(rng.permutation(blocks))}
    fold_id = tr["block"].map(fold_of).values
    oof = {"eff": np.zeros(n), "amp": np.zeros(n)}
    xa_all = np.log10((tr["da_km"] / tr["sigma_km"]).clip(1e-2, 1e4).values)
    for f in range(5):
        m = fold_id != f
        lls = [fit_at(tr[m], c)[2] for c in CS[::2]]
        c_f = float(CS[::2][int(np.argmax(lls))])
        for tag, xfull in (("eff", np.log10(snr_of(tr, c_f).values)), ("amp", xa_all)):
            s50, beta, _ = _logit_fit(xfull[m], y_all[m])
            oof[tag][~m] = 1 / (1 + np.exp(-beta * (xfull[~m] - np.log10(s50))))
    cv = {}
    for tag in ("eff", "amp"):
        ll, brier, auc = metrics(oof[tag], y_all)
        cv[tag] = {"oof_logloss": round(ll, 4), "oof_brier": round(brier, 4),
                   "oof_auc": round(auc, 4)}
    result["blocked_cv5"] = {"fold_unit": "satellite × contiguous 5-window block "
                             "(adjacent overlapping windows never straddle folds)", **cv}
    print(f"   OOF logloss: eff={cv['eff']['oof_logloss']} vs amp={cv['amp']['oof_logloss']}"
          f"   Brier: {cv['eff']['oof_brier']} vs {cv['amp']['oof_brier']}")

    # ── 3. held-out 完整指標 + 再校準 ───────────────────────────────────────
    print("\n3. held-out raw vs recalibrated…")
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT]
    y_cal, y_tst = cal["hit"].values.astype(float), tst["hit"].values.astype(float)
    lls = [fit_at(cal, c)[2] for c in CS]
    c_cal = float(CS[int(np.argmax(lls))])
    s50, beta, _ = _logit_fit(np.log10(snr_of(cal, c_cal).values), y_cal)
    # 校準期內 5-fold OOF 預測 → 擬合 Platt 再校準（a+b·logit）
    calb = cal.reset_index(drop=True)
    kf = rng.permutation(len(calb)) % 5
    oof_cal = np.zeros(len(calb))
    xc = np.log10(snr_of(calb, c_cal).values)
    for f in range(5):
        m = kf != f
        s5f, bf, _ = _logit_fit(xc[m], y_cal[m])
        oof_cal[~m] = 1 / (1 + np.exp(-bf * (xc[~m] - np.log10(s5f))))
    lgt = np.log(np.clip(oof_cal, 1e-9, 1 - 1e-9) / (1 - np.clip(oof_cal, 1e-9, 1 - 1e-9)))
    s50p, bp, _ = _logit_fit(lgt / np.log(10), y_cal)     # Platt: y ~ logit(p)
    a_pl, b_pl = -bp * np.log10(s50p), bp / np.log(10)

    x_t = np.log10(snr_of(tst, c_cal).values)
    p_raw = np.clip(1 / (1 + np.exp(-beta * (x_t - np.log10(s50)))), 1e-9, 1 - 1e-9)
    lgt_t = np.log(p_raw / (1 - p_raw))
    p_rec = 1 / (1 + np.exp(-(a_pl + b_pl * lgt_t)))
    rows = {}
    for tag, p in (("raw", p_raw), ("recalibrated", p_rec)):
        ll, brier, auc = metrics(p, y_tst)
        lgt2 = np.log(np.clip(p, 1e-9, 1 - 1e-9) / (1 - np.clip(p, 1e-9, 1 - 1e-9)))
        s50s, slope, _ = _logit_fit(lgt2 / np.log(10), y_tst)
        intercept = -slope * np.log10(s50s) / np.log(10)
        rows[tag] = {"logloss": round(ll, 4), "brier": round(brier, 4),
                     "auc": round(auc, 4), "calib_slope": round(slope / np.log(10), 2),
                     "calib_intercept": round(float(intercept), 2)}
        print(f"   {tag:<13} logloss={ll:.4f} Brier={brier:.4f} AUC={auc:.4f} "
              f"slope={slope/np.log(10):.2f}")
    result["held_out_metrics"] = {"c_cal_fixed_for_test": c_cal, **rows,
                                  "note": "recalibration (Platt) fitted on calibration-period "
                                          "OOF predictions only; applied unchanged to test"}

    tst_out = tst[["norad", "win_start", "decim", "da_km", "hit", "win_t0"]].copy()
    tst_out["p_raw"] = p_raw
    tst_out["p_recal"] = p_rec
    tst_out.to_csv("data/benchmark/fs7_review4_heldout_predictions.csv", index=False,
                   float_format="%.10g")
    print(f"   Platt 參數：a={a_pl:.4f}  b={b_pl:.4f}（p_recal = sigmoid(a + b·logit p_raw)）")

    write_json_guarded(result, Path("data/benchmark") / "fs7_review4_analysis.json")
    print("\n網格：data/benchmark/fs7_review4_joint_grid.csv, fs7_review4_heldout_predictions.csv")
    print("圖：python docs/gen_fig_fs7_model_supplement.py")


def _diff(a, b, path=""):
    """列出兩個 json 物件之差異（路徑: 舊 → 新）。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            out += _diff(a.get(k, "<缺>"), b.get(k, "<缺>"), f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for k, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{k}]")
    elif a != b:
        out.append(f"{path}: {a!r} → {b!r}")
    return out


def write_json_guarded(result: dict, path: Path) -> None:
    """既有摘要 json 不覆寫：重跑結果相同則不動檔；不同則另存 <stem>_rerun.json 並列差異。"""
    new = json.loads(json.dumps(result, ensure_ascii=False, default=str))
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        d = _diff(old, new)
        if not d:
            print(f"\n摘要值與既有 {path.name} 一致（檔案未改動）")
            return
        alt = path.with_name(path.stem + "_rerun.json")
        alt.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"\n[差異] 重跑摘要與既有 {path.name} 不同，已另存 {alt.name}（原檔未動）：")
        for x in d:
            print("   ", x)
        return
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"\n輸出：{path}")


if __name__ == "__main__":
    main()
