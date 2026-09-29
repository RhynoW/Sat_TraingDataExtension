#!/usr/bin/env python3
"""sa_common.py — STORM-AI 研究共用：太空天氣、MSIS 口徑、幾何工具。

口徑命名（全研究一致）：
  P0  本專案「原版」口徑（2026-09-09 前）：單點、lat=lon=0、ap(7) 全填日均 Ap、
      高度 = a(1−e) − 6378.137（TLE 平均根數，赤道半徑）。
  P1  本專案「現行」口徑（atmospheric_drag.py 2026-09-09 版）：單點、3 小時 ap(7)、
      星下點實際 lat/lon（TLE epoch 當刻），高度同 P0。
  P2  參考「軌道平均 MSIS」：沿整圈軌道 18 點取 MSIS 平均，WGS84 大地高度、3 小時 ap(7)。
  ※ 三者皆呼叫 pymsis.calculate 預設版本（NRLMSIS 2.1；專案文件寫 -00，實際為 2.1）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
PROJ = HERE.parents[1]                       # F:\GitHub\Sat_TraingDataExtension
SWALL = DATA / "SW-All.csv"
DB = r"F:\GitHub\Sat_TraingDataExtension\space_db.duckdb"
RE, MU, J2 = 6378.137, 398_600.4418, 1.08263e-3
F_WGS = 1 / 298.257223563
OMEGA_E = 7.2921150e-5


def use_swall():
    """讓 atmospheric_drag（本專案原始碼，唯讀 import）改用 SW-All.csv（1957–今），
    專案本身的 space_weather_ap.csv 只從 2021 起。兩檔同為 Celestrak 格式、數值相同。"""
    if str(PROJ) not in sys.path:
        sys.path.insert(0, str(PROJ))
    import atmospheric_drag as AD
    AD._sw_cache = None
    AD._ap3h_cache = None
    sw = AD.load_space_weather(str(SWALL))
    AD._ap3h_series(str(SWALL))
    return AD, sw


# ───────────────────────── 太空天氣 ─────────────────────────
def load_sw_daily() -> pd.DataFrame:
    sw = pd.read_csv(SWALL)
    sw["DATE"] = pd.to_datetime(sw["DATE"])
    for c in ["AP_AVG", "F10.7_OBS", "F10.7_OBS_CENTER81", "F10.7_OBS_LAST81", "KP_SUM"] + \
             [f"AP{i}" for i in range(1, 9)] + [f"KP{i}" for i in range(1, 9)]:
        sw[c] = pd.to_numeric(sw[c], errors="coerce")
    return sw.set_index("DATE")


def ap3h_series() -> pd.Series:
    sw = load_sw_daily()
    vals = sw[[f"AP{i}" for i in range(1, 9)]].to_numpy()
    idx = (sw.index.to_numpy()[:, None] + (np.arange(8) * 3).astype("timedelta64[h]")[None, :]).ravel()
    return pd.Series(vals.ravel(), index=pd.DatetimeIndex(idx)).sort_index()


def load_omni2_hourly(years=range(2000, 2026)) -> pd.DataFrame:
    """NASA SPDF OMNI2 低解析（1 小時）年檔。只取研究用欄位並把填值設 NaN。"""
    cols = {0: "year", 1: "doy", 2: "hour", 16: "bz_gsm", 24: "vsw", 35: "ey", 38: "kp10",
            40: "dst", 41: "ae", 49: "ap_omni", 50: "f107_omni"}
    fills = {"bz_gsm": 999.9, "vsw": 9999., "ey": 999.99, "dst": 99999, "ae": 9999,
             "kp10": 99, "ap_omni": 999, "f107_omni": 999.9}
    frames = []
    for y in years:
        p = DATA / "omni2" / f"omni2_{y}.dat"
        if not p.exists() or p.stat().st_size < 1000:
            continue
        d = pd.read_csv(p, sep=r"\s+", header=None, usecols=list(cols))
        d = d.rename(columns=cols)
        frames.append(d)
    o = pd.concat(frames, ignore_index=True)
    for c, fv in fills.items():
        o.loc[o[c] >= fv * 0.999, c] = np.nan
    o["t"] = pd.to_datetime(o["year"].astype(str), format="%Y") + \
        pd.to_timedelta(o["doy"] - 1, unit="D") + pd.to_timedelta(o["hour"], unit="h")
    return o.set_index("t")[[c for c in fills]].sort_index()


def sw_features(t: pd.DatetimeIndex, with_omni: bool = False) -> pd.DataFrame:
    """在時刻 t（UTC naive）組出密度修正模型之太空天氣特徵（只用 ≤ t 的資料 = 因果/可部署）。"""
    t = pd.DatetimeIndex(t)
    sw = load_sw_daily()
    ap3 = ap3h_series()
    ap3 = ap3.reindex(pd.date_range(ap3.index.min(), ap3.index.max(), freq="3h")).ffill()
    bin_t = t.floor("3h")
    F = pd.DataFrame(index=np.arange(len(t)))
    pos = ap3.index.get_indexer(bin_t)
    a = ap3.to_numpy()
    for lag in range(0, 9):                       # 0–24 h 逐 3h
        F[f"ap3_l{lag*3}"] = a[np.clip(pos - lag, 0, None)]
    for lo, hi in [(9, 16), (16, 24)]:            # 24–48h、48–72h 平均
        F[f"ap3_m{lo*3}_{hi*3}"] = np.array([np.nanmean(a[max(p - hi, 0):max(p - lo, 1)]) for p in pos])
    F["ap3_max24"] = np.array([np.nanmax(a[max(p - 8, 0):p + 1]) for p in pos])
    F["ap3_sum24"] = np.array([np.nansum(a[max(p - 8, 0):p + 1]) for p in pos])
    day = t.normalize()
    F["f107"] = sw["F10.7_OBS"].reindex(day).to_numpy()
    F["f107_prev"] = sw["F10.7_OBS"].reindex(day - pd.Timedelta(days=1)).to_numpy()
    F["f81c"] = sw["F10.7_OBS_CENTER81"].reindex(day).to_numpy()
    F["ap_day"] = sw["AP_AVG"].reindex(day).to_numpy()
    F["ap_day_prev"] = sw["AP_AVG"].reindex(day - pd.Timedelta(days=1)).to_numpy()
    doy = t.dayofyear.to_numpy()
    F["doy_s"], F["doy_c"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    F["hour_utc"] = t.hour.to_numpy() + t.minute.to_numpy() / 60
    if with_omni:
        o = load_omni2_hourly().reindex(pd.date_range("2000-01-01", "2025-12-31 23:00", freq="h"))
        ft = t.floor("h")
        oi = o.index.get_indexer(ft)
        D = o["dst"].interpolate(limit=6).to_numpy()
        AE = o["ae"].interpolate(limit=6).to_numpy()
        BZ = o["bz_gsm"].to_numpy()
        V = o["vsw"].interpolate(limit=6).to_numpy()
        for lag in [0, 3, 6, 12, 24]:
            F[f"dst_l{lag}"] = D[np.clip(oi - lag, 0, None)]
        F["dst_min24"] = np.array([np.nanmin(D[max(p - 24, 0):p + 1]) if p >= 0 else np.nan for p in oi])
        F["ae_mean6"] = np.array([np.nanmean(AE[max(p - 6, 0):p + 1]) if p >= 0 else np.nan for p in oi])
        F["ae_mean24"] = np.array([np.nanmean(AE[max(p - 24, 0):p + 1]) if p >= 0 else np.nan for p in oi])
        F["bz_min6"] = np.array([np.nanmin(BZ[max(p - 6, 0):p + 1]) if p >= 0 and np.isfinite(BZ[max(p - 6, 0):p + 1]).any() else np.nan for p in oi])
        F["vsw_l0"] = V[np.clip(oi, 0, None)]
    return F


def storm_class(ap3_now: np.ndarray, ap_day: np.ndarray) -> np.ndarray:
    """以「當日 Ap」與「當下 3h ap」分級（NOAA G 級近似：Kp5≈ap48、Kp7≈ap111、Kp8≈ap207）。"""
    m = np.maximum(ap3_now, ap_day)
    return np.select([m < 15, m < 48, m < 111, m < 207], ["quiet", "active", "G1-G2", "G3"], "G4-G5")


# ───────────────────────── 幾何 ─────────────────────────
def gmst_rad(t: pd.DatetimeIndex) -> np.ndarray:
    jd = pd.DatetimeIndex(t).to_julian_date().to_numpy()
    T = (jd - 2451545.0) / 36525.0
    g = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T ** 2
    return np.deg2rad(g % 360.0)


def eci_to_geodetic(x, y, z, gmst):
    """慣性 (km) → 地固 → WGS84 大地緯度／經度（度）與大地高度（km）。
    gmst 需與 x 同形（或可廣播）。高度用 Bowring 一次迭代，誤差 < 10 m。"""
    c, s = np.cos(gmst), np.sin(gmst)
    xe = c * x + s * y
    ye = -s * x + c * y
    lon = np.degrees(np.arctan2(ye, xe))
    p = np.hypot(xe, ye)
    a, f = RE, F_WGS
    b = a * (1 - f)
    e2 = f * (2 - f)
    ep2 = (a * a - b * b) / (b * b)
    th = np.arctan2(z * a, p * b)
    lat = np.arctan2(z + ep2 * b * np.sin(th) ** 3, p - e2 * a * np.cos(th) ** 3)
    N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    alt = p / np.cos(lat) - N
    return np.degrees(lat), lon, alt


def msis(dates, lon, lat, alt, f107, f81, ap7, version=2.1):
    import pymsis
    r = pymsis.calculate(np.asarray(dates, dtype="datetime64[ns]"), lon, lat, alt,
                         f107, f81, ap7, version=version)
    return np.asarray(r)[..., 0].ravel()
