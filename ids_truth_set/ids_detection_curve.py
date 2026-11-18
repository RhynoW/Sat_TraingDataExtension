#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ids_detection_curve.py — 用 Jason-3 的 IDS 認證點火，實測「偵測機率 vs Δa」曲線。

目的（收尾 §18.2-3(b)）：報告表 11 的「偵測機率 vs Δa」原為**合成注入**
（synthetic_injection_test.py：50% 偵測落在 ~3–5×σ）。Jason-3 位於 1336 km、
幾無大氣阻力，其 IDS operator 點火日誌提供 **da/σ 0.4→101.5** 的連續 Δa 頻譜，
可把該曲線**由合成升級為實資料驗證**，完成表 11 的另一半。

方法（實資料、trend-immune）：
  對每一次點火窗 [win_start, win_end]（TAI→UTC 減 37 s），量測 TLE 之
  sma 觀測步階：post-bracket 中位 − pre-bracket 中位（bracket 各 ±[0.3,3] 天、
  避開窗內暫態）。以校準所得雜訊底 σ（ids_sigma_calibration.csv 之 Jason-3
  σ_resid）定 3σ 偵測門檻：|Δa_obs| ≥ 3σ 即「偵測」。
  再依**真值** |da|/σ 分箱，計每箱實測偵測率 → 偵測機率曲線。

用法：python ids_detection_curve.py [--plot-only] [--en]
      python ids_detection_curve.py --pub   （讀既有逐事件 CSV，不連 DB；輸出 docs/figures_pub/fig_ids_detection_curve/ 中英×白底／黑底四版本）
輸出：ids_detection_curve_jason3.csv（逐事件）＋ docs/fig_ids_detection_curve.png（曲線）
"""
from __future__ import annotations
import sys, math, csv, datetime as dt
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))
import fig_pub as fp  # noqa: E402
DB = ROOT / "space_db.duckdb"
TRUTH = Path(__file__).parent / "ids_truth.csv"
CALIB = Path(__file__).parent / "ids_sigma_calibration.csv"
EN = "--en" in sys.argv
FIG = ROOT / "docs" / ("fig_ids_detection_curve_EN.png" if EN else "fig_ids_detection_curve.png")
OUT = Path(__file__).parent / "ids_detection_curve_jason3.csv"

NORAD_J3 = 41240
TAI_UTC = 37.0                 # s
PUB = fp.wants_pub()
PLOT_ONLY = "--plot-only" in sys.argv or PUB
K_SIGMA = 3.0                  # 偵測門檻（3σ）
BR_IN_D, BR_OUT_D = 0.3, 3.0   # bracket 內/外緣（天）
MIN_SIDE = 3                   # 每側最少 TLE 點


def T(zh, en):
    return en if (EN or fp.is_en()) else zh


def load_tle(nid):
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT epoch_utc, sma_km FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    t = np.array([r[0].timestamp() if hasattr(r[0], "timestamp")
                  else dt.datetime.fromisoformat(str(r[0])).timestamp() for r in rows])
    a = np.array([float(r[1]) for r in rows])
    return t, a


def _to_epoch(tai_str):
    return dt.datetime.fromisoformat(tai_str).timestamp() - TAI_UTC


def observed_step(t, a, s_ep, e_ep):
    """量測窗兩側 sma 中位差；點數不足回 None。"""
    pre = (t >= s_ep - BR_OUT_D * 86400) & (t <= s_ep - BR_IN_D * 86400)
    post = (t >= e_ep + BR_IN_D * 86400) & (t <= e_ep + BR_OUT_D * 86400)
    if pre.sum() < MIN_SIDE or post.sum() < MIN_SIDE:
        return None
    return float(np.median(a[post]) - np.median(a[pre]))


def main():
    df = pd.read_csv(TRUTH)
    j = df[df["norad"] == NORAD_J3].copy()
    # 每次「機動窗」只算一次（多 burn 同窗去重）
    j = j.drop_duplicates(subset=["win_start_tai", "win_end_tai"]).reset_index(drop=True)

    calib = pd.read_csv(CALIB)
    row = calib[calib["norad"] == NORAD_J3]
    sigma = float(row["sigma_resid_km"].iloc[0]) if len(row) else 0.05
    print(f"Jason-3 校準雜訊底 σ = {sigma*1000:.1f} m；偵測門檻 = {K_SIGMA:.0f}σ = {K_SIGMA*sigma*1000:.1f} m")

    if PLOT_ONLY:
        D = pd.read_csv(OUT)
        print(f"--plot-only：讀取既有逐事件 {len(D)} 筆（不重算）")
    else:
        t, a = load_tle(NORAD_J3)
        _d0 = dt.datetime.fromtimestamp(t[0], dt.timezone.utc).date()
        _d1 = dt.datetime.fromtimestamp(t[-1], dt.timezone.utc).date()
        print(f"TLE 點 {len(t)}（{_d0}~{_d1}）")

        recs = []
        for _, r in j.iterrows():
            s_ep, e_ep = _to_epoch(r["win_start_tai"]), _to_epoch(r["win_end_tai"])
            step = observed_step(t, a, s_ep, e_ep)
            if step is None:
                continue
            da_true = abs(float(r["da_km"]))
            recs.append(dict(
                win_start_tai=r["win_start_tai"], da_true_km=da_true,
                da_over_sigma=da_true / sigma, da_obs_km=step,
                detected=int(abs(step) >= K_SIGMA * sigma), severity=r["severity"]))
        D = pd.DataFrame(recs)
        D["da_true_m"] = D["da_true_km"] * 1000.0
        D["da_obs_m"] = D["da_obs_km"].abs() * 1000.0
        D.to_csv(OUT, index=False, encoding="utf-8-sig")
        print(f"逐事件 {len(D)} 筆 → {OUT}")

    thr_cal_m = K_SIGMA * sigma * 1000.0        # 真實校準底 3σ（m）
    thr_t11_m = K_SIGMA * 0.05 * 1000.0         # 表 11 假設 3σ（m）= 150 m

    # 分箱（依物理 Δa，公尺）
    edges = [0, 1, 3, 10, 30, 100, 300, 1000, 6000]
    D["bin"] = pd.cut(D["da_true_m"], edges, right=False)
    grp = D.groupby("bin", observed=True).agg(
        n=("detected", "size"), p_det=("detected", "mean"),
        da_mid=("da_true_m", "median")).reset_index()
    print("\nΔa 箱(m)        n   偵測率")
    for _, g in grp.iterrows():
        print(f"  {str(g['bin']):14} {g['n']:3d}   {g['p_det']:.2f}")

    r_corr = float(np.corrcoef(D["da_true_m"], D["da_obs_m"])[0, 1])
    pdet_all = D["detected"].mean()
    print(f"\n整體實測偵測率 {pdet_all:.3f}（{int(D['detected'].sum())}/{len(D)}）；"
          f"obs vs true 相關 r={r_corr:.3f}")
    print(f"真實校準底 3σ = {thr_cal_m:.1f} m；表 11 假設 3σ = {thr_t11_m:.0f} m（真實底優於假設 ~{0.05/sigma:.0f}×）")

    # ── 圖（雙面板）──
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def draw():
        return plot_curve(D, grp, thr_cal_m, thr_t11_m, pdet_all, r_corr)

    if PUB:
        fp.export_variants(draw, "fig_ids_detection_curve")
        return
    try:
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Yu Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig = draw()
        fig.savefig(FIG, dpi=140)
        print(f"圖 → {FIG}")
    except Exception as e:
        print(f"（繪圖略：{e}）")


def plot_curve(D, grp, thr_cal_m, thr_t11_m, pdet_all, r_corr):
    """雙面板圖；不設定字型（由呼叫端／fig_pub 決定），回傳 Figure。"""
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.2))

    # A：偵測機率 vs 真值 Δa(m)
    gg = grp.dropna(subset=["da_mid"])
    ax1.scatter(gg["da_mid"], gg["p_det"], s=40 + gg["n"] * 7,
                color="#1a6fc4", zorder=3, label=T("實測偵測率（分箱，點大小隨 n 增大）", "Measured detection rate (binned; larger marker = more events)"))
    ax1.plot(gg["da_mid"], gg["p_det"], color="#1a6fc4", lw=1.2, alpha=0.5, zorder=2)
    in_gap = D[(D["da_true_m"] >= thr_cal_m) & (D["da_true_m"] < thr_t11_m)]
    n_gap, n_gap_det = len(in_gap), int(in_gap["detected"].sum())
    ax1.axvspan(thr_cal_m, thr_t11_m, color="#f0ad4e", alpha=0.16, zorder=1, lw=0)
    ax1.axvline(thr_cal_m, color="#5cb85c", lw=1.6, ls="--", zorder=2,
                label=T(f"校準底 3σ = {thr_cal_m:.1f} m（實測）", f"Calibrated noise floor 3σ = {thr_cal_m:.1f} m (measured)"))
    ax1.axvline(thr_t11_m, color="#d9534f", lw=1.6, ls="--", zorder=2,
                label=T(f"表 11 假設 3σ = {thr_t11_m:.0f} m", f"Reference-table assumption 3σ = {thr_t11_m:.0f} m"))
    ax1.annotate("", xy=(thr_t11_m, 0.5), xytext=(thr_cal_m, 0.5),
                 arrowprops=dict(arrowstyle="<->", color="#8a6d3b", lw=1.3))
    ax1.text(math.sqrt(thr_cal_m * thr_t11_m), 0.55,
             T(f"假設門檻高於實測 {thr_t11_m / thr_cal_m:.0f}×\n"
               f"此區 {n_gap} 次點火中 {n_gap_det} 次已被偵得\n"
               f"（其真值 Δa 皆低於假設門檻）",
               f"Assumed threshold is {thr_t11_m / thr_cal_m:.0f}x the measured one\n"
               f"{n_gap_det} of {n_gap} burns in this band were detected\n"
               f"(all have truth Δa below the assumed threshold)"),
             ha="center", va="bottom", fontsize=9, color="#8a6d3b")
    ax1.set_xscale("log"); ax1.set_ylim(-0.03, 1.06)
    ax1.set_xlabel(T("真值 Δa (m)", "Truth Δa (m)"))
    ax1.set_ylabel(T("偵測機率", "Detection probability"))
    ax1.set_title(T(f"(A) Jason-3 實測偵測機率 vs Δa　整體 {pdet_all:.2f}", f"(A) Jason-3 detection probability vs Δa (overall {pdet_all:.2f})"))
    ax1.grid(True, alpha=0.3, which="both"); ax1.legend(loc="lower right", fontsize=8.5)

    # B：觀測 vs 真值 Δa（回收驗證）
    det = D["detected"] == 1
    ax2.scatter(D.loc[det, "da_true_m"], D.loc[det, "da_obs_m"],
                s=22, color="#1a6fc4", alpha=0.8, label=T("已偵測", "Detected"))
    ax2.scatter(D.loc[~det, "da_true_m"], D.loc[~det, "da_obs_m"],
                s=40, color="#d9534f", marker="x", label=T("未偵測", "Missed"))
    lims = [0.3, 2e4]
    ax2.plot(lims, lims, color="#888", lw=1.0, ls=":", label="y = x")
    ax2.axhline(thr_cal_m, color="#5cb85c", lw=1.0, ls="--", alpha=0.7)
    ax2.set_xscale("log"); ax2.set_yscale("log")
    ax2.set_xlim(*lims); ax2.set_ylim(*lims)
    ax2.set_xlabel(T("真值 Δa (m)", "Truth Δa (m)")); ax2.set_ylabel(T("TLE 觀測 |Δa| (m)", "TLE-observed |Δa| (m)"))
    ax2.set_title(T(f"(B) 觀測 vs 真值 Δa 回收　r = {r_corr:.2f}", f"(B) Observed vs truth Δa recovery (r = {r_corr:.2f})"))
    ax2.grid(True, alpha=0.3, which="both"); ax2.legend(loc="upper left", fontsize=8.5)

    fig.suptitle(T("Jason-3 IDS 認證點火：偵測能力實資料驗證（表 11 由合成注入升級為實測）", "Jason-3 IDS-certified maneuvers: real-data validation of detection capability"),
                 fontsize=12.5)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


if __name__ == "__main__":
    main()
