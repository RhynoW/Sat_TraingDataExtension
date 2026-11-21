"""產生碎片連鎖用的太陽活動與大氣密度表（內嵌進 exe，離線可用）。

輸出：
  config/f107_monthly.csv   每月 F10.7 的 81 天中心平均（sfu）：1957 年起的實測，之後接 CelesTrak 的日預報與月預報
  config/msis_density.csv   NRLMSISE-00 全球平均總質量密度（kg/m³），高度 × F10.7 網格

全球平均：緯度 −80°～80°（每 20°）、經度每 45°（等效地方時每 3 小時）、四季各一天（1、4、7、10 月 1 日 0 UT），
F10.7 與 81 天平均取同值、Ap 固定 15（中等地磁活動）。

用法（在 RUST_SatDashboard 目錄）：
  py -3.13 scripts/gen_solar_tables.py [--sw ../data/space_weather_full/SW-All.csv]
需要 numpy、pymsis。更新太陽活動資料後重跑本腳本，再重新建置 exe。
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import pymsis

ROOT = Path(__file__).resolve().parents[1]
ALTS = list(range(100, 1001, 20))                       # km
F107S = [60, 70, 80, 100, 125, 150, 175, 200, 250, 300]  # sfu


def monthly_f107(sw: Path) -> list[tuple[str, float, str]]:
    """回傳 [(YYYY-MM, F10.7 81 天中心平均, 資料類型)]；同月多筆取平均，類型取最後一筆（OBS／PRD／PRM）。"""
    acc: dict[str, list[float]] = defaultdict(list)
    kind: dict[str, str] = {}
    with sw.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v = row.get("F10.7_OBS_CENTER81") or ""
            if not v.strip():
                continue
            ym = row["DATE"][:7]
            acc[ym].append(float(v))
            kind[ym] = row.get("F10.7_DATA_TYPE", "").strip() or "OBS"
    return [(ym, sum(vs) / len(vs), kind[ym]) for ym, vs in sorted(acc.items())]


def density_table() -> np.ndarray:
    """回傳 shape (len(ALTS), len(F107S)) 的全球平均密度。"""
    dates = np.array(["2022-01-01T00:00", "2022-04-01T00:00", "2022-07-01T00:00", "2022-10-01T00:00"], dtype="datetime64[m]")
    lons = np.arange(0, 360, 45)
    lats = np.arange(-80, 81, 20)
    out = np.zeros((len(ALTS), len(F107S)))
    w = np.cos(np.radians(lats))                         # 緯度面積權重
    for j, f in enumerate(F107S):
        rho = pymsis.calculate(dates, lons, lats, ALTS, f107s=[f] * len(dates), f107as=[f] * len(dates),
                               aps=[[15] * 7] * len(dates), version=0)[..., 0]   # (date, lon, lat, alt)
        m = rho.mean(axis=(0, 1))                         # (lat, alt)
        out[:, j] = (m * w[:, None]).sum(axis=0) / w.sum()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sw", default=str(ROOT.parent / "data" / "space_weather_full" / "SW-All.csv"))
    a = ap.parse_args()

    rows = monthly_f107(Path(a.sw))
    p = ROOT / "config" / "f107_monthly.csv"
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 每月 F10.7 81 天中心平均（sfu）；type：OBS 實測、PRD 日預報、PRM 月預報。來源 CelesTrak SW-All.csv\n")
        f.write("month,f107,type\n")
        for ym, v, k in rows:
            f.write(f"{ym},{v:.1f},{k}\n")
    print(f"{p}: {len(rows)} 個月（{rows[0][0]}～{rows[-1][0]}，實測至 {max(r[0] for r in rows if r[2] == 'OBS')}）")

    tab = density_table()
    p = ROOT / "config" / "msis_density.csv"
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# NRLMSISE-00 全球平均總質量密度（kg/m³）；列為高度（km），欄為 F10.7（sfu，81 天平均同值），Ap = 15\n")
        f.write("alt_km," + ",".join(str(x) for x in F107S) + "\n")
        for i, h in enumerate(ALTS):
            f.write(f"{h}," + ",".join(f"{v:.4e}" for v in tab[i]) + "\n")
    print(f"{p}: {len(ALTS)} 個高度 × {len(F107S)} 個 F10.7")
    for h in (400, 500, 600, 800):
        i = ALTS.index(h)
        print(f"  {h} km：F10.7=70 {tab[i, 1]:.2e}，150 {tab[i, 5]:.2e}，250 {tab[i, 8]:.2e}（高低比 {tab[i, 8] / tab[i, 1]:.0f} 倍）")


if __name__ == "__main__":
    main()
