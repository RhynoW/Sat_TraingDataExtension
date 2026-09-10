#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etalon_lunisolar_model.py — 對 Etalon（MEO ~19,120 km）TLE 半長軸之慢變背離建模。

背景（月報 §3.6 之延伸）：被動球 Etalon 之 σ_resid（6–7 m）遠大於 σ_diff（~1 m），
  背離顯示其去趨勢殘差含**未建模之週期性攝動**（研判為日月長週期），非純 TLE 雜訊。
  本腳本以頻譜諧波建模驗證此假說：若移除主週期正弦後殘差由 6–7 m 收斂至 σ_diff 量級，
  即證該背離為**確定性週期訊號**（可建模），而非隨機雜訊。

方法：
  1. 全序列去線性趨勢。
  2. 於週期網格 P∈[2,63] 天，以最小二乘擬合 [1,t,sin(2πt/P),cos(2πt/P)]，取殘差最小之 P1。
  3. 對殘差重複求 P2（諧波逐次剝離）。
  4. 比較 σ：原始 → 去P1 → 去P1P2，對照 σ_diff（短期雜訊底）。
  5. 主週期與已知日月週期比對（朔望月 29.53、恆星月 27.32、半月 13.66、太陽半年 182.6…）。

用法：python etalon_lunisolar_model.py
輸出：docs/fig_etalon_lunisolar.png（序列+擬合、週期圖、殘差收斂）
"""
from __future__ import annotations
import sys, datetime as dt
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import duckdb

ROOT = Path(__file__).resolve().parent
DB = ROOT / "space_db.duckdb"
FIG = ROOT / "docs" / "fig_etalon_lunisolar.png"
TARGETS = [(19751, "Etalon-1"), (20026, "Etalon-2")]
RE = 6378.137

# 已知日月週期（天）供比對
KNOWN = {"恆星月": 27.322, "朔望月": 29.531, "半恆星月": 13.661,
         "回歸月": 27.322, "太陽半年": 182.62}


def load(nid):
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT epoch_utc, sma_km FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    t = np.array([r[0].timestamp() for r in rows]) / 86400.0
    a = np.array([float(r[1]) for r in rows])
    t -= t[0]
    return t, a


def fit_at_period(t, y, P):
    """在固定週期 P 擬合 [1,t,sin,cos]，回 (殘差RMS, 預測, 振幅)。"""
    w = 2 * np.pi / P
    A = np.column_stack([np.ones_like(t), t, np.sin(w * t), np.cos(w * t)])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ coef
    amp = np.hypot(coef[2], coef[3])
    return float(np.sqrt(np.mean((y - pred) ** 2))), pred, amp


def best_period(t, y, pmin=2.0, pmax=63.0, n=1200):
    Ps = np.linspace(pmin, pmax, n)
    rms = np.array([fit_at_period(t, y, P)[0] for P in Ps])
    i = int(np.argmin(rms))
    return Ps[i], rms, Ps


def robust_sigma_diff(a):
    return 1.4826 * np.median(np.abs(np.diff(a))) / np.sqrt(2.0)


def nearest_known(P):
    lab, dd = min(KNOWN.items(), key=lambda kv: abs(kv[1] - P))
    return lab, dd, abs(dd - P)


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Yu Gothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(len(TARGETS), 3, figsize=(15, 4.4 * len(TARGETS)))
    if len(TARGETS) == 1:
        axes = axes[None, :]

    for row, (nid, name) in enumerate(TARGETS):
        t, a = load(nid)
        a_m = (a - np.median(a)) * 1000.0                     # 相對中位、公尺
        sig0 = 1.4826 * np.median(np.abs(a_m - np.median(a_m)))  # 原始 MAD σ（m）
        # 去線性趨勢
        c = np.polyfit(t, a_m, 1)
        y = a_m - np.polyval(c, t)
        sig_detrend = 1.4826 * np.median(np.abs(y - np.median(y)))
        sdiff = robust_sigma_diff(a_m)

        # 主週期 P1（y 已去線性；擬合 [1,t,sin,cos] 後取殘差）
        P1, rms1, Ps = best_period(t, y)
        _, pred1, amp1 = fit_at_period(t, y, P1)
        res1 = y - pred1
        sig1 = 1.4826 * np.median(np.abs(res1 - np.median(res1)))

        # 次週期 P2（於殘差）
        P2, rms2, _ = best_period(t, res1)
        _, pred2, amp2 = fit_at_period(t, res1, P2)
        res2 = res1 - pred2
        sig2 = 1.4826 * np.median(np.abs(res2 - np.median(res2)))

        lab1, kd1, d1 = nearest_known(P1)
        lab2, kd2, d2 = nearest_known(P2)
        print(f"\n== {name}（{len(t)}點/{t[-1]:.0f}天，高度 {np.median(a)-RE:.0f} km）==")
        print(f"  原始 σ(MAD)        = {sig0:.2f} m")
        print(f"  去線性後 σ         = {sig_detrend:.2f} m")
        print(f"  主週期 P1={P1:.2f} 天（振幅 {amp1:.2f} m）→ 近 {lab1} {kd1:.2f} 天（差 {d1:.2f}）")
        print(f"  去 P1 後 σ         = {sig1:.2f} m")
        print(f"  次週期 P2={P2:.2f} 天（振幅 {amp2:.2f} m）→ 近 {lab2} {kd2:.2f} 天（差 {d2:.2f}）")
        print(f"  去 P1+P2 後 σ      = {sig2:.2f} m")
        print(f"  σ_diff（短期底）   = {sdiff:.2f} m")
        print(f"  → 週期建模解釋比例 = {(1 - sig2/sig_detrend)*100:.0f}%（σ 由 {sig_detrend:.2f}→{sig2:.2f} m）")

        # 圖 A：序列 + 擬合
        ax = axes[row, 0]
        ax.scatter(t, a_m, s=8, color="#888", alpha=0.6, label="TLE sma（去中位）")
        tt = np.linspace(t.min(), t.max(), 600)
        w1 = 2 * np.pi / P1
        A1 = np.column_stack([np.ones_like(t), t, np.sin(w1 * t), np.cos(w1 * t)])
        cc, *_ = np.linalg.lstsq(A1, a_m, rcond=None)
        A1t = np.column_stack([np.ones_like(tt), tt, np.sin(w1 * tt), np.cos(w1 * tt)])
        ax.plot(tt, A1t @ cc, color="#d9534f", lw=1.6, label=f"線性+P1={P1:.1f}d 擬合")
        ax.set_title(f"{name}  (A) sma 序列 + 主週期擬合")
        ax.set_xlabel("天"); ax.set_ylabel("sma−中位 (m)")
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)

        # 圖 B：週期圖（殘差 RMS vs 週期）
        ax = axes[row, 1]
        ax.plot(Ps, rms1, color="#1a6fc4", lw=1.2)
        ax.axvline(P1, color="#d9534f", ls="--", lw=1.2, label=f"P1={P1:.1f}d≈{lab1}")
        for lab, kd in KNOWN.items():
            if Ps.min() <= kd <= Ps.max():
                ax.axvline(kd, color="#5cb85c", ls=":", lw=0.9, alpha=0.7)
        ax.set_title(f"{name}  (B) 週期掃描（殘差極小=主週期）")
        ax.set_xlabel("試探週期 (天)"); ax.set_ylabel("擬合殘差 RMS (m)")
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)

        # 圖 C：殘差收斂
        ax = axes[row, 2]
        stages = ["去線性", "去P1", "去P1+P2", "σ_diff"]
        vals = [sig_detrend, sig1, sig2, sdiff]
        colors = ["#888", "#e08a2c", "#1a6fc4", "#5cb85c"]
        ax.bar(stages, vals, color=colors)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
        ax.set_title(f"{name}  (C) σ 收斂：週期建模→逼近短期底")
        ax.set_ylabel("σ (m)"); ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Etalon（MEO）TLE 半長軸慢變背離之日月週期建模：移除週期→殘差收斂至短期雜訊底",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(FIG, dpi=140)
    print(f"\n圖 → {FIG}")


if __name__ == "__main__":
    main()
