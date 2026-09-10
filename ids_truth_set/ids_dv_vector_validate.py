#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ids_dv_vector_validate.py — 交叉弧段 ΔV 向量驗證（收尾 §18.2-3(c)）。

目的：IDS 對 SWOT／CryoSat-2 等**脈衝式化學推進**測高衛星，提供逐次點火的
      三分量 ΔV（R/T/N，dv_radial/along/cross）真值。本腳本由**公開 TLE** 量測
      每次點火前後的根數步階 Δa、Δi，以近圓 Gauss 變分反解 R/T/N ΔV，與 IDS
      三分量真值比對，實測「交叉弧段機動估計」之準確度與**適用邊界**。

反解（近圓）：
  n = √(μ/a³)（rad/s），v = √(μ/a)（km/s）
  沿軌（切向）：Δa = 2·Δv_t / n            → dv_along = n·Δa / 2
  越軌（法向）：Δi = Δv_c / v （節點處）    → dv_cross = v·Δi(rad)
  （徑向 Δv_r 由 Δe 反解，量級小且 TLE 對 e 靈敏度低，此處以量級估計、不作主驗證。）

適用邊界：脈衝假設（單一階躍）對化學推進成立；電推連續推力（如 Starlink）
  之 ΔV 攤在數十圈、無單一階躍，單步反解會系統性低估——見報告 burn-arc 章。

用法：python ids_dv_vector_validate.py
輸出：ids_dv_vector_validate.csv（逐事件）＋ docs/fig_ids_dv_vector.png
"""
from __future__ import annotations
import sys, math, datetime as dt
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "space_db.duckdb"
TRUTH = Path(__file__).parent / "ids_truth.csv"
FIG = ROOT / "docs" / "fig_ids_dv_vector.png"
OUT = Path(__file__).parent / "ids_dv_vector_validate.csv"

MU = 398600.4418               # km^3/s^2
TAI_UTC = 37.0
BR_IN_D, BR_OUT_D = 0.3, 3.0
MIN_SIDE = 3
TARGETS = [(54754, "SWOT"), (36508, "CryoSat-2")]


def load_tle(nid):
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT epoch_utc, sma_km, inclination_deg FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL AND inclination_deg IS NOT NULL "
        "ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    t = np.array([r[0].timestamp() if hasattr(r[0], "timestamp")
                  else dt.datetime.fromisoformat(str(r[0])).timestamp() for r in rows])
    a = np.array([float(r[1]) for r in rows])
    inc = np.array([float(r[2]) for r in rows])
    return t, a, inc


def _ep(tai_str):
    return dt.datetime.fromisoformat(tai_str).timestamp() - TAI_UTC


def step(t, y, s_ep, e_ep):
    pre = (t >= s_ep - BR_OUT_D * 86400) & (t <= s_ep - BR_IN_D * 86400)
    post = (t >= e_ep + BR_IN_D * 86400) & (t <= e_ep + BR_OUT_D * 86400)
    if pre.sum() < MIN_SIDE or post.sum() < MIN_SIDE:
        return None, None
    return float(np.median(y[post]) - np.median(y[pre])), float(np.median(y[pre | post]))


def main():
    df = pd.read_csv(TRUTH)
    recs = []
    for nid, name in TARGETS:
        t, a, inc = load_tle(nid)
        s = df[df["norad"] == nid].copy()
        # 逐窗聚合真值：多 burn 加總為窗淨 ΔV／Δa／Δi
        agg = s.groupby(["win_start_tai", "win_end_tai"], as_index=False).agg(
            dv_along=("dv_along", "sum"), dv_cross=("dv_cross", "sum"),
            dv_mag=("dv_mag", "sum"), da_km=("da_km", "sum"), di_deg=("di_deg", "sum"),
            n_burns=("burn_idx", "size"))
        # 所有機動窗區間（供鄰近汙染判定）
        wins = [(_ep(a0), _ep(b0)) for a0, b0 in zip(agg["win_start_tai"], agg["win_end_tai"])]
        for _, r in agg.iterrows():
            s_ep, e_ep = _ep(r["win_start_tai"]), _ep(r["win_end_tai"])
            da_obs, a_med = step(t, a, s_ep, e_ep)
            di_obs, _ = step(t, inc, s_ep, e_ep)
            if da_obs is None or di_obs is None:
                continue
            # bracket 乾淨判定：bracket 區間 [lo,hi] 內無「其他」機動窗
            lo, hi = s_ep - BR_OUT_D * 86400, e_ep + BR_OUT_D * 86400
            neigh = 0
            for (ws, we) in wins:
                if abs(ws - s_ep) < 60 and abs(we - e_ep) < 60:
                    continue                              # 自己
                if not (we < lo or ws > hi):              # 與 bracket 重疊
                    neigh += 1
            clean = int(neigh == 0)
            n = math.sqrt(MU / a_med ** 3)          # rad/s
            v = math.sqrt(MU / a_med)               # km/s
            dv_along_rec = n * da_obs / 2 * 1000.0            # m/s（帶號）
            dv_cross_rec = v * math.radians(di_obs) * 1000.0  # m/s（帶號）
            recs.append(dict(
                sat=name, win_start_tai=r["win_start_tai"], n_burns=int(r["n_burns"]),
                clean=clean, da_obs_m=da_obs * 1000, di_obs_mdeg=di_obs * 1000,
                dv_along_truth=r["dv_along"], dv_along_rec=dv_along_rec,
                dv_cross_truth=r["dv_cross"], dv_cross_rec=dv_cross_rec,
                dv_mag_truth=r["dv_mag"]))
    D = pd.DataFrame(recs)
    D.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"逐事件 {len(D)} 筆 → {OUT}")

    def report(data, col_t, col_r, label):
        m = data[[col_t, col_r]].dropna()
        m = m[m[col_t].abs() > 1e-6]                 # 只評有真值分量者
        if len(m) < 3:
            print(f"  {label}: 樣本不足"); return None
        err = (m[col_r] - m[col_t]).abs()
        r = float(np.corrcoef(m[col_t], m[col_r])[0, 1])
        print(f"  {label}: n={len(m)}  相關 r={r:.3f}  "
              f"中位|誤差|={err.median()*1000:.1f} mm/s  "
              f"中位真值={m[col_t].abs().median()*1000:.1f} mm/s")
        return r

    Dc = D[D["clean"] == 1]
    print(f"\n== 全體 {len(D)} 事件（SWOT + CryoSat-2，脈衝化學推進）==")
    report(D, "dv_along_truth", "dv_along_rec", "沿軌 Δv_t")
    report(D, "dv_cross_truth", "dv_cross_rec", "越軌 Δv_c")
    print(f"== 乾淨 bracket 子集 {len(Dc)} 事件（排除鄰近機動汙染）==")
    report(Dc, "dv_along_truth", "dv_along_rec", "沿軌 Δv_t")
    for name in ("SWOT", "CryoSat-2"):
        for tag, dd in (("全體", D), ("乾淨", Dc)):
            mm = dd[(dd["sat"] == name) & (dd["dv_along_truth"].abs() > 1e-6)]
            if len(mm) >= 3:
                r = float(np.corrcoef(mm["dv_along_truth"], mm["dv_along_rec"])[0, 1])
                print(f"  [{name}/{tag}] 沿軌 n={len(mm)} r={r:.3f}")

    # ── 圖 ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Yu Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.2))
        colors = {"SWOT": "#1a6fc4", "CryoSat-2": "#e08a2c"}

        for name in ("SWOT", "CryoSat-2"):
            sub = Dc[(Dc["sat"] == name) & (Dc["dv_along_truth"].abs() > 1e-6)]
            ax1.scatter(sub["dv_along_truth"] * 1000, sub["dv_along_rec"] * 1000,
                        s=26, alpha=0.75, color=colors[name], label=f"{name}（n={len(sub)}）")
        lim = 120
        ax1.plot([-lim, lim], [-lim, lim], color="#888", lw=1.0, ls=":", label="y = x")
        ax1.set_xlim(-lim, lim); ax1.set_ylim(-lim, lim)
        ax1.set_xlabel("IDS 真值 沿軌 Δv_t (mm/s)")
        ax1.set_ylabel("TLE 反解 沿軌 Δv_t (mm/s)")
        ax1.set_title("(A) 沿軌 ΔV 反解 vs IDS 真值（乾淨 bracket）")
        ax1.grid(True, alpha=0.3); ax1.legend(loc="upper left", fontsize=9)

        both = D[D["dv_cross_truth"].abs() > 1e-6]
        for name in ("SWOT", "CryoSat-2"):
            sub = both[both["sat"] == name]
            ax2.scatter(sub["dv_cross_truth"] * 1000, sub["dv_cross_rec"] * 1000,
                        s=26, alpha=0.75, color=colors[name], label=name)
        lim2 = 200
        ax2.plot([-lim2, lim2], [-lim2, lim2], color="#888", lw=1.0, ls=":", label="y = x")
        ax2.set_xlim(-lim2, lim2); ax2.set_ylim(-lim2, lim2)
        ax2.set_xlabel("IDS 真值 越軌 Δv_c (mm/s)")
        ax2.set_ylabel("TLE 反解 越軌 Δv_c (mm/s)")
        ax2.set_title("(B) 越軌 ΔV 反解 vs 真值（Δi 微小、較噪）")
        ax2.grid(True, alpha=0.3); ax2.legend(loc="upper left", fontsize=9)

        fig.suptitle("交叉弧段 ΔV 向量驗證：TLE 反解 R/T/N vs IDS 三分量真值（脈衝化學推進）",
                     fontsize=12.5)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(FIG, dpi=140)
        print(f"圖 → {FIG}")
    except Exception as e:
        print(f"（繪圖略：{e}）")


if __name__ == "__main__":
    main()
