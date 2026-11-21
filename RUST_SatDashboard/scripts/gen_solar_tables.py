"""產生碎片連鎖用的太陽活動與大氣密度表（內嵌進 exe，離線可用）。

輸出：
  config/f107_monthly.csv   每月 F10.7 的 81 天中心平均（sfu）與等效 Ap：1957 年起的實測，之後接 CelesTrak 的日預報與月預報
  config/msis_density.csv   NRLMSISE-00 全球平均總質量密度（kg/m³），高度 × Ap × F10.7 網格

全球平均：緯度 −80°～80°（每 20°，cos 緯度面積加權）、經度每 45°（等效地方時每 3 小時）、四季各一天（1、4、7、10 月 1 日 0 UT），
F10.7 與 81 天平均取同值（近似：模擬以每月 81 天平均驅動，不區分當日值）。

等效 Ap（v0.1.19）：密度對 Ap 是凸函數，月平均 Ap 會低估磁暴月份的平均密度。因此每月取「在 460 km、當月 F10.7 下，
使密度等於當月每日密度平均」的 Ap 值。只有實測（OBS）與日預報（PRD）有每日 Ap；月預報（PRM）沒有 Ap，
取 1957 年以來實測等效 Ap 的中位數（情境假設）。

用法（在 RUST_SatDashboard 目錄）：
  py -3.13 scripts/gen_solar_tables.py [--sw ../data/space_weather_full/SW-All.csv]
  py -3.13 scripts/gen_solar_tables.py --track     # 沿軌跡取樣 vs 全球平均的密度比（敏感度測試，不寫檔）
需要 numpy、pymsis。更新太陽活動資料後重跑本腳本，再重新建置 exe。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path

import numpy as np
import pymsis

ROOT = Path(__file__).resolve().parents[1]
ALTS = list(range(100, 1001, 20))                       # km
F107S = [60, 70, 80, 100, 125, 150, 175, 200, 250, 300]  # sfu
APS = [0, 4, 7, 15, 30, 50, 80, 130, 200, 300, 400]     # 日 Ap
H_EFF = 460                                             # 等效 Ap 的參考高度（km，表格格點）
DATES = np.array(["2022-01-01T00:00", "2022-04-01T00:00", "2022-07-01T00:00", "2022-10-01T00:00"], dtype="datetime64[m]")


def daily(sw: Path) -> list[dict]:
    with sw.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("F10.7_OBS_CENTER81") or "").strip()]


def msis(f: float, ap: float, lats, lons, alts) -> np.ndarray:
    """(date, lon, lat, alt) 的總質量密度。"""
    n = len(DATES)
    return pymsis.calculate(DATES, lons, lats, alts, f107s=[f] * n, f107as=[f] * n, aps=[[ap] * 7] * n, version=0)[..., 0]


def density_table() -> np.ndarray:
    """回傳 shape (len(ALTS), len(APS), len(F107S)) 的全球平均密度。"""
    lons = np.arange(0, 360, 45)
    lats = np.arange(-80, 81, 20)
    w = np.cos(np.radians(lats))
    out = np.zeros((len(ALTS), len(APS), len(F107S)))
    for k, ap in enumerate(APS):
        for j, f in enumerate(F107S):
            m = msis(f, ap, lats, lons, ALTS).mean(axis=(0, 1))   # (lat, alt)
            out[:, k, j] = (m * w[:, None]).sum(axis=0) / w.sum()
    return out


def ln_rho_at(tab: np.ndarray, ia: int, f: np.ndarray, ap: np.ndarray) -> np.ndarray:
    """表格在高度索引 ia 的 ln ρ：F10.7 方向對 ln F、Ap 方向線性內插（與 Rust 端一致）。"""
    lf = np.log(np.clip(f, F107S[0], F107S[-1]))
    lfs = np.log(F107S)
    apc = np.clip(ap, APS[0], APS[-1])
    lr = np.log(tab[ia])                                     # (ap, f)
    by_ap = np.array([np.interp(lf, lfs, lr[k]) for k in range(len(APS))])   # (ap, n)
    return np.array([np.interp(apc[i], APS, by_ap[:, i]) for i in range(len(f))])


def ap_effective(lnr_target: float, f: float, tab: np.ndarray, ia: int) -> float:
    """在 F10.7 = f 下，使 ln ρ 等於目標值的 Ap（二分法）。"""
    lo, hi = APS[0], APS[-1]
    for _ in range(40):
        m = (lo + hi) / 2
        if ln_rho_at(tab, ia, np.array([f]), np.array([m]))[0] < lnr_target:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def monthly(rows: list[dict], tab: np.ndarray) -> list[tuple[str, float, str, float | None]]:
    """回傳 [(YYYY-MM, F10.7 81 天中心平均, 資料類型, 等效 Ap 或 None)]。"""
    ia = ALTS.index(H_EFF)
    acc: dict[str, list[tuple[float, float | None]]] = defaultdict(list)
    kind: dict[str, str] = {}
    for r in rows:
        ym = r["DATE"][:7]
        a = (r.get("AP_AVG") or "").strip()
        acc[ym].append((float(r["F10.7_OBS_CENTER81"]), float(a) if a else None))
        kind[ym] = (r.get("F10.7_DATA_TYPE") or "").strip() or "OBS"
    out = []
    for ym in sorted(acc):
        fs = [x[0] for x in acc[ym]]
        f = sum(fs) / len(fs)
        aps = np.array([x[1] for x in acc[ym] if x[1] is not None])
        ape = None
        if len(aps) >= 0.8 * len(fs):   # 每日 Ap 齊全才算
            lnr = ln_rho_at(tab, ia, np.full(len(aps), f), aps)
            ape = ap_effective(float(np.log(np.exp(lnr).mean())), f, tab, ia)
        out.append((ym, f, kind[ym], ape))
    return out


def track_sensitivity() -> None:
    """沿軌跡取樣（圓軌道在各緯度的停留時間加權）vs 全球平均（cos 緯度面積加權）的密度比。"""
    lats = np.arange(-89, 90, 2.0)
    lons = np.arange(0, 360, 30)
    alts = [400, 500, 600, 800]
    print("沿軌跡／全球平均 密度比（Ap 15；四季、各地方時平均）")
    print("傾角    F10.7 " + "".join(f"{h:>8} km" for h in alts))
    for f in (70, 150, 250):
        rho = msis(f, 15, lats, lons, alts).mean(axis=(0, 1))   # (lat, alt)
        wg = np.cos(np.radians(lats))
        g = (rho * wg[:, None]).sum(axis=0) / wg.sum()
        for inc in (28.5, 51.6, 82.6, 98.0):
            si = np.sin(np.radians(min(inc, 180 - inc)))
            sl = np.sin(np.radians(lats))
            # 圓軌道在緯度 φ 的停留時間密度 ∝ cos φ / sqrt(sin²i − sin²φ)
            wt = np.where(np.abs(sl) < si, np.cos(np.radians(lats)) / np.sqrt(np.maximum(si ** 2 - sl ** 2, 1e-4)), 0.0)
            tr = (rho * wt[:, None]).sum(axis=0) / wt.sum()
            print(f"{inc:5.1f}° {f:6d}  " + "".join(f"{x:11.3f}" for x in tr / g))
    # 太陽同步軌道：地方時固定（0 UT 時地方時 = 經度／15），取升、降交點兩個地方時的平均（近似：高緯度的地方時變化不計）
    print("\n太陽同步（98°）固定地方時／全球平均")
    for f in (70, 150, 250):
        full = msis(f, 15, lats, lons, alts).mean(axis=0)          # (lon, lat, alt)
        wg = np.cos(np.radians(lats))
        g = (full.mean(axis=0) * wg[:, None]).sum(axis=0) / wg.sum()
        si, sl = np.sin(np.radians(82.0)), np.sin(np.radians(lats))
        wt = np.where(np.abs(sl) < si, np.cos(np.radians(lats)) / np.sqrt(np.maximum(si ** 2 - sl ** 2, 1e-4)), 0.0)
        for lt in (6, 10, 12):
            k1, k2 = list(lons).index(lt * 15), list(lons).index((lt + 12) % 24 * 15)
            band = (full[k1] + full[k2]) / 2
            tr = (band * wt[:, None]).sum(axis=0) / wt.sum()
            print(f"{lt:02d}/{(lt + 12) % 24:02d} 時 {f:4d}  " + "".join(f"{x:11.3f}" for x in tr / g))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sw", default=str(ROOT.parent / "data" / "space_weather_full" / "SW-All.csv"))
    ap.add_argument("--track", action="store_true")
    a = ap.parse_args()
    if a.track:
        track_sensitivity()
        return

    tab = density_table()
    p = ROOT / "config" / "msis_density.csv"
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# NRLMSISE-00 全球平均總質量密度（kg/m³）；列為高度（km）× 日 Ap，欄為 F10.7（sfu，81 天平均同值）\n")
        f.write("alt_km,ap," + ",".join(str(x) for x in F107S) + "\n")
        for i, h in enumerate(ALTS):
            for k, apv in enumerate(APS):
                f.write(f"{h},{apv}," + ",".join(f"{v:.4e}" for v in tab[i, k]) + "\n")
    print(f"{p}: {len(ALTS)} 個高度 × {len(APS)} 個 Ap × {len(F107S)} 個 F10.7")
    k15 = APS.index(15)
    for h in (400, 500, 600, 800):
        i = ALTS.index(h)
        print(f"  {h} km（Ap 15）：F10.7=70 {tab[i, k15, 1]:.2e}，250 {tab[i, k15, 8]:.2e}；F10.7=150 時 Ap 4→50 為 {tab[i, APS.index(50), 5] / tab[i, APS.index(4), 5]:.2f} 倍")

    rows = monthly(daily(Path(a.sw)), tab)
    obs_ap = [r[3] for r in rows if r[2] == "OBS" and r[3] is not None]
    ap_default = float(np.median(obs_ap))
    p = ROOT / "config" / "f107_monthly.csv"
    sha = hashlib.sha256(Path(a.sw).read_bytes()).hexdigest()
    obs_until = max(r[0] for r in rows if r[2] == "OBS")
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 每月 F10.7 81 天中心平均（sfu）與等效 Ap（460 km 密度等效，見 gen_solar_tables.py）；type：OBS 實測、PRD 日預報、PRM 月預報。"
                "來源 CelesTrak SW-All.csv（https://celestrak.org/SpaceData/SW-All.csv）\n")
        f.write(f"# 來源檔 sha256 {sha}，實測至 {obs_until}；無每日 Ap 的月份取實測等效 Ap 中位數 {ap_default:.1f}\n")
        f.write("month,f107,type,ap\n")
        for ym, v, k, ape in rows:
            f.write(f"{ym},{v:.1f},{k},{(ape if ape is not None else ap_default):.1f}\n")
    mean_ap = np.mean(obs_ap)
    big = sorted(((r[3], r[0]) for r in rows if r[3] is not None), reverse=True)[:3]
    print(f"{p}: {len(rows)} 個月（{rows[0][0]}～{rows[-1][0]}，實測至 {obs_until}）；實測等效 Ap 中位數 {ap_default:.1f}、平均 {mean_ap:.1f}；"
          f"最高 {', '.join(f'{m} {v:.0f}' for v, m in big)}")


if __name__ == "__main__":
    main()
