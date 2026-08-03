#!/usr/bin/env python3
"""tasa14_dataquality.py — 14 星「資料品質」逐星量化,並與偵測 F1 關聯。

量化四個資料品質維度(皆為客觀、與偵測方法無關):
  σ_m       : TLE 半長軸雜訊底(去趨勢步階 MAD,公尺)——越小越乾淨
  cadence_d : TLE 更新中位間隔(天)——越小越密
  vis_frac  : 機動之「物理可見比例」= |Δa| ≥ 2σ(SNR≥2)之事件占比——越高越可偵
  med_da_m  : 機動 |Δa| 中位量級(公尺)——訊號強度
再與迭代法逐星 F1 求 Spearman 相關,檢驗「F1 差異是否由資料品質解釋」。
用法：python tasa14_dataquality.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import load_a, detrend_step, robust_sigma, SATS
RE = 6378.137


def main():
    truth = pd.read_csv("ids_truth_set/ids_truth.csv")
    truth = truth.dropna(subset=["norad"]); truth["norad"] = truth["norad"].astype(int)
    truth["da_m"] = pd.to_numeric(truth["da_km"], errors="coerce") * 1000.0

    f1 = pd.read_csv("data/benchmark/tasa14_compare_iter_20260801.csv").set_index("norad")["f1"]

    rows = []
    for nid, nm in SATS:
        t, a = load_a(nid)
        if t is None or len(a) < 30:
            continue
        sig_m = robust_sigma(detrend_step(a)) * 1000.0                    # 雜訊底(m)
        gaps = np.diff(t.astype("int64").to_numpy() / 1e9) / 86400.0
        cad = float(np.median(gaps))                                       # 更新中位間隔(天)
        alt = float(np.median(a)) - RE
        da = truth.loc[truth["norad"] == nid, "da_m"].abs().dropna()
        da = da[da > 0]
        med_da = float(da.median()) if len(da) else np.nan
        vis = float((da >= 2 * sig_m).mean()) if len(da) else np.nan       # SNR≥2 可見比例
        rows.append(dict(norad=nid, name=nm, alt_km=alt, sigma_m=sig_m,
                         cadence_d=cad, med_da_m=med_da, vis_frac=vis,
                         f1=float(f1.get(nid, np.nan))))
    df = pd.DataFrame(rows).sort_values("f1", ascending=False)

    print("=" * 92)
    print("14 星資料品質逐星量化(客觀、與偵測方法無關) vs 偵測 F1")
    print("=" * 92)
    print(f"{'衛星':14}{'高度km':>7}{'σ_m雜訊底':>10}{'更新間隔d':>10}"
          f"{'|Δa|中位m':>10}{'可見比例%':>10}{'F1':>7}")
    for _, r in df.iterrows():
        vf = f"{r.vis_frac*100:.0f}" if pd.notna(r.vis_frac) else "—(窗)"
        md = f"{r.med_da_m:.0f}" if pd.notna(r.med_da_m) else "—"
        print(f"{r['name']:14}{r.alt_km:>7.0f}{r.sigma_m:>10.2f}{r.cadence_d:>10.2f}"
              f"{md:>10}{vf:>10}{r.f1:>7.2f}")
    print("=" * 92)

    # Spearman 相關(F1 vs 各品質維度)
    def spearman(x, y):
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 4: return np.nan
        rx = pd.Series(x[m]).rank(); ry = pd.Series(y[m]).rank()
        return float(np.corrcoef(rx, ry)[0, 1])
    f = df["f1"].to_numpy()
    print("Spearman 相關(F1 ↔ 資料品質維度):")
    print(f"  F1 ↔ 可見比例(SNR≥2)   : {spearman(f, df['vis_frac'].to_numpy()):+.2f}  (應為強正)")
    print(f"  F1 ↔ σ 雜訊底           : {spearman(f, df['sigma_m'].to_numpy()):+.2f}  (應為負:越吵越差)")
    print(f"  F1 ↔ 更新間隔           : {spearman(f, df['cadence_d'].to_numpy()):+.2f}  (應為負:越疏越差)")
    print(f"  F1 ↔ |Δa| 中位量級      : {spearman(f, df['med_da_m'].to_numpy()):+.2f}  (應為正:訊號越強越好)")

    out = Path("data/benchmark/tasa14_dataquality_20260801.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
