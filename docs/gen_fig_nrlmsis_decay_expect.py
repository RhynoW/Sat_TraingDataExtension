#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_nrlmsis_decay_expect.py — NRLMSIS 2.1 預期之自然軌道衰減率（2024-01 迄今，300–1000 km）。

每日以 NRLMSIS 2.1（實測 F10.7、81 日均 F10.7、3 小時 Ap，同系統 atmospheric_drag.density）計算大氣密度，
於緯度 −45°～45°（每 15°）、經度 0°／180°、每 3 小時取樣平均，近似圓軌道之軌道平均密度；
再以近圓軌道阻力公式換算半長軸衰減率：

    da/dt = −ρ · (Cd·A/m) · √(μ a)，Cd·A/m 取 0.022 m²/kg（Cd 2.2、面積質量比 0.01 m²/kg）

衰減率與 Cd·A/m 成正比：面積質量比加倍，衰減率加倍。實際系統之彈道係數逐星自我校準，此圖為代表值。

用法：python docs/gen_fig_nrlmsis_decay_expect.py [迄日 YYYY-MM-DD]
輸出：docs/fig_nrlmsis_decay_expect.png、data/benchmark/nrlmsis_decay_expect.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import os  # noqa: E402
os.chdir(ROOT)
from atmospheric_drag import density, load_space_weather  # noqa: E402

D0 = pd.Timestamp("2024-01-01", tz="UTC")
D1 = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-11-14", tz="UTC")
ALTS = list(range(300, 1001, 100))
BC = 0.022                      # Cd·A/m (m²/kg)
MU, RE = 3.986004418e14, 6378.137e3
LATS = np.arange(-45, 46, 15)
LONS = np.array([0.0, 180.0])
HOURS = np.arange(0, 24, 3)


def main():
    sw = load_space_weather()
    days = pd.date_range(D0, D1, freq="D")
    t = np.array([d + pd.Timedelta(hours=int(h)) for d in days for h in HOURS for _ in LATS for _ in LONS])
    la = np.tile(np.repeat(LATS, len(LONS)), len(days) * len(HOURS)).astype(float)
    lo = np.tile(LONS, len(days) * len(HOURS) * len(LATS))
    day_idx = np.repeat(np.arange(len(days)), len(HOURS) * len(LATS) * len(LONS))
    out = {"date": days.date}
    for h in ALTS:
        rho = density(pd.DatetimeIndex(t), np.full(len(t), float(h)), sw, lat=la, lon=lo)
        rho_d = np.bincount(day_idx, weights=rho) / np.bincount(day_idx)
        a = RE + h * 1e3
        out[f"{h}km_m_per_day"] = rho_d * BC * np.sqrt(MU * a) * 86400.0
        print(h, "km 中位", f"{np.median(out[f'{h}km_m_per_day']):.3g}", "m/日", flush=True)
    D = pd.DataFrame(out)
    f107 = np.array([sw.get(str(d), (np.nan, np.nan, np.nan))[0] for d in days.date], float)
    f81 = np.array([sw.get(str(d), (np.nan, np.nan, np.nan))[1] for d in days.date], float)
    D["f107"], D["f107_81"] = f107, f81
    D.to_csv(ROOT / "data/benchmark/nrlmsis_decay_expect.csv", index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax0, ax) = plt.subplots(2, 1, figsize=(12, 8.2), dpi=160, sharex=True,
                                  gridspec_kw={"height_ratios": [1, 3.6], "hspace": 0.08})
    x = pd.to_datetime(D["date"])
    ax0.plot(x, D["f107"], color="#9AA5B1", lw=0.8, label="F10.7 每日實測")
    ax0.plot(x, D["f107_81"], color="#C2410C", lw=1.8, label="F10.7 81 日平均")
    ax0.set_ylabel("F10.7 (sfu)")
    ax0.grid(alpha=0.3); ax0.legend(loc="upper right", fontsize=9, frameon=False, ncol=2)
    for s in ("top", "right"):
        ax0.spines[s].set_visible(False)

    cmap = plt.get_cmap("Blues")
    cols = [cmap(v) for v in np.linspace(0.95, 0.38, len(ALTS))]   # 低軌深、高軌淺
    for h, c in zip(ALTS, cols):
        y = D[f"{h}km_m_per_day"]
        ax.plot(x, y, color=c, lw=1.0, alpha=0.45)
        ys = y.rolling(7, center=True, min_periods=1).mean()
        ax.plot(x, ys, color=c, lw=2.0)
        last = ys.iloc[-1]
        ax.annotate(f"{h} km　{last:.3g} m/日" if last < 1000 else f"{h} km　{last / 1000:.2f} km/日",
                    xy=(x.iloc[-1], last), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=9.5, color="#262626")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_ylabel("預期半長軸衰減率（m／日，對數尺度）")
    ax.grid(alpha=0.3, which="major"); ax.grid(alpha=0.12, which="minor")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlim(x.iloc[0], x.iloc[-1] + pd.Timedelta(days=150))
    storm = pd.Timestamp("2024-05-11")
    for a_ in (ax0, ax):
        a_.axvline(storm, color="#7F1D1D", lw=0.9, ls=(0, (4, 3)))
    ax.text(storm + pd.Timedelta(days=6), 0.13, "2024-05-11 Gannon 磁暴", fontsize=9, color="#7F1D1D",
            va="bottom")
    ax.text(0.0, -0.1, "細線：每日值；粗線：7 日平均。假設圓軌道、Cd·A/m＝0.022 m²/kg（Cd 2.2、面積質量比 0.01 m²/kg），"
            "衰減率與 Cd·A/m 成正比。密度為緯度 ±45°、每 3 小時取樣之平均。",
            transform=ax.transAxes, fontsize=9, color="#595959")
    fig.suptitle(f"NRLMSIS 2.1 預期之自然軌道衰減率（{D0:%Y-%m-%d} 至 {D1:%Y-%m-%d}，300–1000 km）", fontsize=13.5, y=0.955)
    fig.subplots_adjust(left=0.08, right=0.86, top=0.91, bottom=0.1)
    fig.savefig(ROOT / "docs/fig_nrlmsis_decay_expect.png", facecolor="white")
    print("fig → docs/fig_nrlmsis_decay_expect.png")
    print(D[[c for c in D.columns if c.endswith("m_per_day")]].describe().loc[["min", "50%", "max"]].round(3).T.to_string())


if __name__ == "__main__":
    main()
