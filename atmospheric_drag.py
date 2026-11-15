#!/usr/bin/env python3
"""
atmospheric_drag.py — NRLMSIS-00/2.1 物理阻力殘差（取代不可靠的 tle_table.bstar）。

動機：偵測機動須先扣除大氣阻力造成的自然 Δa。bstar 覆蓋率僅 ~11%；改用半經驗
密度模型 NRLMSIS（pymsis），依 F10.7 與 Ap 逐時算密度，並逐衛星自我校準等效彈道
係數，得到乾淨的阻力殘差：

  近圓軌道阻力衰減率：  da/dt = -B · ρ · √(μ a)
  形狀項            ：  s_i  = ρ_i · √(μ a_i) · dt_i
  逐衛星校準        ：  B_eff = median( -Δa_i / s_i )     （中位數穩健，排除機動離群）
  阻力殘差          ：  drag_resid_da_i = Δa_i + B_eff · s_i
      純大氣衰減 → 殘差 ≈ 0；機動 → 殘差 = 機動 Δa（含太陽/地磁變化已由 ρ 涵蓋）。

需求：pymsis、space_weather_ap.csv（Celestrak SW，含 F10.7_OBS / F10.7_OBS_CENTER81 / AP_AVG /
AP1-AP8）。

[2026-09-09 改善] 原版 ap(7) 陣列全填每日 AP_AVG、lat/lon 固定 0，暴時精度受限（見
project_atmospheric_drag_model2 備忘）。改為：
  (a) 依 NRLMSISE-00 標準定義組出真正的 3 小時解析度 ap(7)（見 _ap7_array()）；
  (b) 若呼叫端提供 line1/line2，以 SGP4 解出當下（epoch 當刻）星下點 lat/lon 取代常數 0/0
      （見 _subsat_latlon()）；未提供時完全退回原行為（向下相容，不影響既有呼叫端）。

[2026-09-29 修正]（STORM-AI 驗證發現，research_202609/stormai/README.md）
  (c) pymsis 預設開關 9（geomagnetic_activity=1）只讀 ap[0]（日均 Ap），(a) 組出的 3 小時 ap(7)
      從未生效。改為有 3 小時 ap 時傳 geomagnetic_activity=-1（NRLMSIS 標準「暴時 ap 模式」）。
      STORM_AP_MODE=False 可還原舊行為（重現 2026-09-29 以前的結果用）。
  (d) 模型版本明示為 MSIS_VERSION=2.1（pymsis ≥0.8 的預設；舊文件寫 NRLMSIS-00 有誤）。
  (e) drag_residual 的 dt 改用 total_seconds()：原本 astype("int64")/1e9 假設奈秒，
      DuckDB 回傳微秒解析度時 dt 小 1000 倍 → attrs["B_eff"] 大 1000 倍（殘差因自我校準不受影響）。

[2026-09-29 沿軌道平均＋逐時積分]（STORM-AI 驗證 P2／V2，research_202609/stormai/README.md §5–§6）
  (f) 近圓軌道（中位 e < ORBIT_AVG_MAX_ECC）且有 TLE 原文時，密度改為：每整點以當時最新 TLE 經
      SGP4 取一整圈 ORBIT_RING_N 點的 WGS84 大地座標，NRLMSIS 平均得軌道平均密度 ρ̄(t)；
      阻力形狀項改為 ∫_{t_i}^{t_{i+1}} ρ̄ dt（原本只取 t_i 單點 × dt）。F10.7 用前一日（MSIS 慣例）。
      STORM-AI 在 2024-05 Gannon 磁暴：殘差 RMS 18.1→9.7 m、GRACE-FO 已達實測密度 oracle 水準。
      偏心軌道（HEO／再入末期）18 點抓不到近地點，維持近地點單點＋King-Hele；
      缺 TLE 原文或 DENSITY_METHOD="point" 時亦為原單點法。
"""
from __future__ import annotations


import numpy as np
import pandas as pd

RE, MU = 6378.137, 398_600.4418
_SW_PATH = "space_weather_ap.csv"
_sw_cache: dict | None = None
_ap3h_cache: pd.Series | None = None
MSIS_VERSION = 2.1       # pymsis 預設；0 = NRLMSISE-00
STORM_AP_MODE = True     # True：有 3 小時 ap(7) 時開 geomagnetic_activity=-1 讓其生效
DENSITY_METHOD = "orbit_avg"   # "orbit_avg"（沿軌道平均＋逐時積分）｜"point"（TLE 時刻單點，2026-09-29 前）
ORBIT_RING_N = 18              # 每整點沿一整圈取樣點數
ORBIT_AVG_MAX_ECC = 0.01       # 中位偏心率高於此值 → 用近地點單點＋King-Hele
ORBIT_AVG_MAX_GAP_D = 7.0      # 單一轉換跨越超過此天數 → 該轉換改用單點法（避免長空窗大量取樣）
WGS_F = 1.0 / 298.257223563


def load_space_weather(path: str = _SW_PATH) -> dict:
    """回傳 {date_str: (f107_obs, f107_81avg, ap_avg)}（快取；向下相容，未變動既有呼叫端）。"""
    global _sw_cache
    if _sw_cache is not None:
        return _sw_cache
    sw = pd.read_csv(path)
    sw["k"] = pd.to_datetime(sw["DATE"]).dt.strftime("%Y-%m-%d")
    f107 = pd.to_numeric(sw["F10.7_OBS"], errors="coerce")
    f81 = pd.to_numeric(sw.get("F10.7_OBS_CENTER81", sw["F10.7_OBS"]), errors="coerce")
    ap = pd.to_numeric(sw["AP_AVG"], errors="coerce")
    _sw_cache = {k: (f, a81, a) for k, f, a81, a in zip(sw["k"], f107, f81, ap)}
    return _sw_cache


def _sw_arrays(epochs, sw):
    keys = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True)).strftime("%Y-%m-%d")
    f = np.array([sw.get(k, (120., 120., 10.))[0] for k in keys], float)
    fa = np.array([sw.get(k, (120., 120., 10.))[1] for k in keys], float)
    a = np.array([sw.get(k, (120., 120., 10.))[2] for k in keys], float)
    # 缺值以合理預設補（避免 pymsis NaN）
    f = np.where(np.isnan(f), 120., f)
    fa = np.where(np.isnan(fa), f, fa)
    a = np.where(np.isnan(a), 10., a)
    return f, fa, a


def _ap3h_series(path: str = _SW_PATH) -> pd.Series:
    """把 space_weather_ap.csv 的 AP1-AP8（每日 8 個 3 小時值）攤平成單一時序（index=區間起始
    UTC 時刻）。找不到 AP1-AP8 欄位時回傳空 Series（呼叫端據此退回原行為）。"""
    global _ap3h_cache
    if _ap3h_cache is not None:
        return _ap3h_cache
    sw = pd.read_csv(path)
    ap_cols = [f"AP{i}" for i in range(1, 9)]
    if not all(c in sw.columns for c in ap_cols):
        _ap3h_cache = pd.Series(dtype=float)
        return _ap3h_cache
    d0 = pd.to_datetime(sw["DATE"]).to_numpy()
    vals = sw[ap_cols].apply(pd.to_numeric, errors="coerce").to_numpy()  # (n_days, 8)
    idx = (d0[:, None] + (np.arange(8) * 3).astype("timedelta64[h]")[None, :]).ravel()
    _ap3h_cache = pd.Series(vals.ravel(), index=pd.DatetimeIndex(idx)).sort_index()
    return _ap3h_cache


def _ap7_array(epochs, daily_ap: np.ndarray) -> np.ndarray | None:
    """依 NRLMSISE-00 標準定義組出 ap(7)：
      ap[0]=當日 AP_AVG；ap[1..4]=當下／前3／前6／前9 小時之 3hr ap；
      ap[5]=前 12–33 小時 8 筆 3hr ap 均值；ap[6]=前 36–57 小時 8 筆均值。
    找不到 AP1-8 資料（或落在資料範圍邊界）時回傳 None／以 NaN 標記，由呼叫端補 daily 值。"""
    s = _ap3h_series()
    if s.empty:
        return None
    vals = s.to_numpy()
    n_bins = len(vals)
    bin_start = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True)).tz_localize(None).floor("3h")
    pos = s.index.searchsorted(bin_start, side="right") - 1
    n = len(pos)
    out = np.full((n, 7), np.nan)
    out[:, 0] = daily_ap
    for slot, lag in enumerate([0, 1, 2, 3]):
        idx = pos - lag
        ok = (idx >= 0) & (idx < n_bins)
        col = np.full(n, np.nan)
        col[ok] = vals[idx[ok]]
        out[:, slot + 1] = col
    for i in range(n):
        p = pos[i]
        if p < 0:
            continue
        lo, hi = max(p - 11, 0), p - 4
        if hi >= lo:
            out[i, 5] = np.nanmean(vals[lo:hi + 1])
        lo2, hi2 = max(p - 19, 0), p - 12
        if hi2 >= lo2:
            out[i, 6] = np.nanmean(vals[lo2:hi2 + 1])
    nanmask = np.isnan(out)
    if nanmask.any():
        out[nanmask] = np.broadcast_to(daily_ap[:, None], out.shape)[nanmask]
    return out


def _subsat_latlon(epochs, line1, line2) -> tuple[np.ndarray, np.ndarray]:
    """由 TLE 逐筆解出當下（epoch 當刻）星下點 lat/lon（度，球形地球近似，僅供 NRLMSIS
    輸入用——密度對地心/大地緯度差異之敏感度遠低於高度）。傳播失敗者填 0.0（退回原行為）。"""
    from sgp4.api import Satrec, jday
    t = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True))
    n = len(t)
    lat = np.zeros(n)
    lon = np.zeros(n)
    for i in range(n):
        l1, l2 = line1[i], line2[i]
        if not isinstance(l1, str) or not isinstance(l2, str) or not l1 or not l2:
            continue
        try:
            sat = Satrec.twoline2rv(l1, l2)
            ti = t[i]
            jd, fr = jday(ti.year, ti.month, ti.day, ti.hour, ti.minute,
                          ti.second + ti.microsecond / 1e6)
            e, r, _ = sat.sgp4(jd, fr)
            if e:
                continue
            x, y, z = r
            T = ((jd - 2451545.0) + fr) / 36525.0
            gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr) + 0.000387933 * T ** 2
            gmst_rad = np.deg2rad(gmst % 360.0)
            x_ecef = np.cos(gmst_rad) * x + np.sin(gmst_rad) * y
            y_ecef = -np.sin(gmst_rad) * x + np.cos(gmst_rad) * y
            lon[i] = np.degrees(np.arctan2(y_ecef, x_ecef))
            lat[i] = np.degrees(np.arctan2(z, np.hypot(x_ecef, y_ecef)))
        except Exception:
            continue
    return lat, lon


def _storm_options():
    """NRLMSIS 開關 9 = -1：使用完整 ap(7) 歷史（否則只讀 ap[0] 日均 Ap）。"""
    from pymsis import msis
    return msis.create_options(geomagnetic_activity=-1)


def density(epochs, alt_km, sw=None, lat=0.0, lon=0.0, storm_ap: bool | None = None) -> np.ndarray:
    """向量化 NRLMSIS 總質量密度 (kg/m³)。

    lat/lon 可傳純量（原行為，常數）或與 alt_km 等長之陣列（星下點實際座標，見
    _subsat_latlon()）。ap(7) 優先用 3 小時解析度真值（見 _ap7_array()），AP1-8 欄位不存在
    時退回全填每日 AP_AVG 的原行為。storm_ap（預設 STORM_AP_MODE）控制 3 小時 ap 是否真正
    生效；AP1-8 不存在時一律用日均 Ap（開關 9=1）。
    """
    import pymsis
    sw = sw or load_space_weather()
    epochs = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True))
    dates = np.array([e.to_pydatetime().replace(tzinfo=None) for e in epochs])
    alt = np.asarray(alt_km, float)
    f, fa, a = _sw_arrays(epochs, sw)
    ap7 = _ap7_array(epochs, a)
    ap = ap7 if ap7 is not None else np.tile(a[:, None], (1, 7))
    lat_arr = np.asarray(lat, float) if np.ndim(lat) else np.full(len(alt), float(lat))
    lon_arr = np.asarray(lon, float) if np.ndim(lon) else np.full(len(alt), float(lon))
    use_storm = (STORM_AP_MODE if storm_ap is None else storm_ap) and ap7 is not None
    r = pymsis.calculate(dates, lon_arr, lat_arr, alt, f, fa, ap, version=MSIS_VERSION,
                         options=_storm_options() if use_storm else None)
    return np.asarray(r)[..., 0].ravel()


def _teme_to_geodetic(x, y, z, gmst):
    """TEME≈慣性 (km) → 地固 → WGS84 大地緯度／經度（度）與大地高度（km）（Bowring 一次迭代，誤差 < 10 m）。"""
    c, sn = np.cos(gmst), np.sin(gmst)
    xe, ye = c * x + sn * y, -sn * x + c * y
    lon = np.degrees(np.arctan2(ye, xe))
    p_ = np.hypot(xe, ye)
    a_, f_ = RE, WGS_F
    b_ = a_ * (1 - f_)
    e2 = f_ * (2 - f_)
    ep2 = (a_ * a_ - b_ * b_) / (b_ * b_)
    th = np.arctan2(z * a_, p_ * b_)
    lat = np.arctan2(z + ep2 * b_ * np.sin(th) ** 3, p_ - e2 * a_ * np.cos(th) ** 3)
    alt = p_ / np.cos(lat) - a_ / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    return np.degrees(lat), lon, alt


def orbit_avg_density_hourly(t_utc: pd.DatetimeIndex, line1, line2, a_km: np.ndarray,
                             hours: pd.DatetimeIndex, sw=None, ring_n: int = ORBIT_RING_N):
    """每個整點以 ≤ 該時刻之最新 TLE（無則最早一筆）沿一整圈取 ring_n 點，回傳軌道平均密度（kg/m³）。
    SGP4 失敗（再入後等）之整點回傳 NaN，由呼叫端退回單點法。"""
    import pymsis
    from sgp4.api import Satrec
    sw = sw or load_space_weather()
    ep = t_utc.tz_convert(None).to_numpy() if t_utc.tz is not None else t_utc.to_numpy()
    h = hours.tz_convert(None).to_numpy() if hours.tz is not None else hours.to_numpy()
    idx = np.clip(np.searchsorted(ep, h, side="right") - 1, 0, len(ep) - 1)
    period_s = 2 * np.pi * np.sqrt(a_km[idx] ** 3 / MU)
    frac = (np.arange(ring_n) - (ring_n - 1) / 2) / ring_n
    tt = h[:, None] + (frac[None, :] * period_s[:, None] * 1e9).astype("timedelta64[ns]")
    lat = np.full(tt.shape, np.nan); lon = np.full(tt.shape, np.nan); alt = np.full(tt.shape, np.nan)
    for j in np.unique(idx):
        rows = np.where(idx == j)[0]
        l1, l2 = line1[j], line2[j]
        if not isinstance(l1, str) or not isinstance(l2, str) or not l1 or not l2:
            continue
        sat = Satrec.twoline2rv(l1, l2)
        ti = pd.DatetimeIndex(tt[rows].ravel())
        jd = ti.to_julian_date().to_numpy()
        jd_i = np.floor(jd - 0.5) + 0.5
        err, r, _ = sat.sgp4_array(jd_i, jd - jd_i)
        r = np.asarray(r)
        T = (jd - 2451545.0) / 36525.0
        gm = np.deg2rad((280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T ** 2) % 360.0)
        la, lo, al = _teme_to_geodetic(r[:, 0], r[:, 1], r[:, 2], gm)
        bad = np.asarray(err) != 0
        la[bad] = lo[bad] = al[bad] = np.nan
        lat[rows], lon[rows], alt[rows] = la.reshape(-1, ring_n), lo.reshape(-1, ring_n), al.reshape(-1, ring_n)
    rho = np.full(len(h), np.nan)
    ok = np.isfinite(alt).all(axis=1) & (alt.min(axis=1) > 80.0)
    if not ok.any():
        return rho
    hs = pd.DatetimeIndex(h[ok]).tz_localize("UTC")
    _, fa, a_d = _sw_arrays(hs, sw)
    f_prev, _, _ = _sw_arrays(hs - pd.Timedelta(days=1), sw)       # MSIS 慣例：F10.7 用前一日
    ap7 = _ap7_array(hs, a_d)
    ap = ap7 if ap7 is not None else np.tile(a_d[:, None], (1, 7))
    rep_ = lambda v: np.repeat(v, ring_n, axis=0)                   # noqa: E731
    dates = np.repeat(h[ok], ring_n)
    r = pymsis.calculate(dates, lon[ok].ravel(), lat[ok].ravel(), np.clip(alt[ok].ravel(), 80.0, 1000.0),
                         rep_(f_prev), rep_(fa), rep_(ap), version=MSIS_VERSION,
                         options=_storm_options() if (STORM_AP_MODE and ap7 is not None) else None)
    rho[ok] = np.asarray(r)[..., 0].ravel().reshape(-1, ring_n).mean(axis=1)
    return rho


def _orbit_avg_rho_eff(t: pd.Series, line1, line2, a: np.ndarray, sw) -> np.ndarray:
    """各轉換 [t_i, t_{i+1}] 的時間平均軌道密度（逐時軌道平均密度之線性內插積分／dt）。
    轉換跨越 > ORBIT_AVG_MAX_GAP_D 天或該區間整點計算失敗者回傳 NaN。"""
    tu = pd.DatetimeIndex(t)
    ts = tu.as_unit("ns").asi8 / 1e9
    dt = np.diff(ts)
    short = dt <= ORBIT_AVG_MAX_GAP_D * 86400
    hrs = set()
    for i in np.where(short)[0]:
        h0 = int(np.floor(ts[i] / 3600)) - 1
        h1 = int(np.ceil(ts[i + 1] / 3600)) + 1
        hrs.update(range(h0, h1 + 1))
    out = np.full(len(dt), np.nan)
    if not hrs:
        return out
    hs = np.array(sorted(hrs), dtype=np.int64)
    hours = pd.to_datetime(hs * 3600, unit="s", utc=True)
    rho_h = orbit_avg_density_hourly(tu, line1, line2, a, hours, sw)
    th = hs * 3600.0
    good = np.isfinite(rho_h)
    if good.sum() < 2:
        return out
    th, rho_h = th[good], rho_h[good]
    C = np.concatenate([[0.0], np.cumsum(0.5 * (rho_h[1:] + rho_h[:-1]) * np.diff(th))])
    for i in np.where(short)[0]:
        # 區間需有整點覆蓋（首尾外插至多 1 小時）
        if ts[i] < th[0] - 3600 or ts[i + 1] > th[-1] + 3600:
            continue
        m = (th >= ts[i] - 3600) & (th <= ts[i + 1] + 3600)
        if m.sum() < 2 or np.diff(th[m]).max() > 3 * 3600:     # 區間內缺太多整點（SGP4 失敗）
            continue
        integ = np.interp(ts[i + 1], th, C) - np.interp(ts[i], th, C)
        out[i] = integ / dt[i] if dt[i] > 0 else np.nan
    return out


def drag_residual(df: pd.DataFrame, sw=None, method: str | None = None) -> pd.DataFrame:
    """對單顆衛星（欄位 epoch, sma_km）算逐轉換 drag_resid_da + 校準的 B_eff。

    回傳 DataFrame(epoch, da_km, drag_pred_da, drag_resid_da) 與屬性 .attrs['B_eff']。
    """
    from scipy.special import ive
    d = df.sort_values("epoch").reset_index(drop=True)
    if len(d) < 4:
        return pd.DataFrame()
    a = d["sma_km"].to_numpy(float)
    e = d["eccentricity"].to_numpy(float) if "eccentricity" in d.columns else np.zeros(len(a))
    t = pd.to_datetime(d["epoch"], utc=True)
    dt_s = t.diff().dt.total_seconds().to_numpy()[1:]    # 與 datetime 解析度（ns/us）無關
    da = np.diff(a)

    # ── 偏心軌道阻力模型（King-Hele）─────────────────────────────────────────
    # 阻力主要作用於近地點 → 於「近地點高度」取密度（非平均高度）；
    # 幾何因子 geom = exp(-z)[I₀(z)+2e·I₁(z)]，z=a·e/H（H≈大氣尺度高）。
    # e→0（近圓）時 geom→1，自動退化為原 LEO 圓軌公式。
    a0, e0 = a[:-1], e[:-1]
    alt_p = np.clip(a0 * (1.0 - e0) - RE, 80.0, 1000.0)   # 近地點高度（NRLMSIS 有效域）
    if {"line1", "line2"}.issubset(d.columns):
        lat_p, lon_p = _subsat_latlon(t.iloc[:-1], d["line1"].to_numpy()[:-1], d["line2"].to_numpy()[:-1])
    else:
        lat_p, lon_p = 0.0, 0.0                           # 無 TLE 行原始文本時退回原行為
    rho_p = density(t.iloc[:-1], alt_p, sw, lat=lat_p, lon=lon_p)  # 近地點密度（星下點實際座標）
    method = method or DENSITY_METHOD
    n_orbit = 0
    if (method == "orbit_avg" and {"line1", "line2"}.issubset(d.columns)
            and np.nanmedian(e) < ORBIT_AVG_MAX_ECC):
        rho_o = _orbit_avg_rho_eff(t, d["line1"].to_numpy(), d["line2"].to_numpy(), a, sw)
        use = np.isfinite(rho_o) & (rho_o > 0)
        rho_p = np.where(use, rho_o, rho_p)                # 失敗／長空窗之轉換退回單點
        n_orbit = int(use.sum())
    H = 50.0                                              # 大氣尺度高 (km)
    z = np.clip(a0 * e0 / H, 0.0, 1e6)
    geom = ive(0, z) + 2.0 * e0 * ive(1, z)              # 數值穩定（ive=exp(-z)·Iν）
    s = rho_p * np.sqrt(MU * a0) * dt_s * geom            # 阻力 da 形狀項（>0）

    # 校準 B_eff：中位數穩健，只用 s>0 且有限者
    ok = np.isfinite(s) & (s > 0) & np.isfinite(da)
    ratios = -da[ok] / s[ok]                         # 阻力使 a 下降 → -da/s > 0
    B_eff = float(np.median(ratios[ratios > 0])) if np.any(ratios > 0) else 0.0

    pred = -B_eff * s                                # 預測阻力 Δa（負）
    resid = da - pred                                # 殘差 = 實測 − 阻力預測
    out = pd.DataFrame({"epoch": t.to_numpy()[1:], "da_km": da,
                        "drag_pred_da": pred, "drag_resid_da": resid,
                        "rho": rho_p, "alt_km": alt_p})
    out.attrs["B_eff"] = B_eff
    out.attrs["density_method"] = "orbit_avg" if n_orbit else "point"
    out.attrs["n_orbit_avg"] = n_orbit
    return out


def is_reentry_decay(df: pd.DataFrame) -> bool:
    """再入/自然衰減守門：深近地點 + 單調快速衰減 + 無 reboost 正跳 → True。

    再入的劇烈非線性衰減無法用準secular阻力模型消除，殘差會爆量誤報；
    此守門辨識此狀態，讓上層直接判定「自然再入，機動=0」。
    可靠區分「再入(單調衰減)」與「reboost 太空站(週期性正跳)」。
    """
    d = df.sort_values("epoch").reset_index(drop=True)
    if len(d) < 5:
        return False
    a = d["sma_km"].to_numpy(float)
    e = d["eccentricity"].to_numpy(float) if "eccentricity" in d.columns else np.zeros(len(a))
    rp_alt = a * (1.0 - e) - RE                       # 近地點高度
    t_days = (pd.to_datetime(d["epoch"], utc=True) -
              pd.to_datetime(d["epoch"], utc=True).iloc[0]).dt.total_seconds().to_numpy() / 86400.0

    # 用「近期」窗（最後 45 天）判斷當前是否再入——Cluster 類 HEO 的近地點早年很高
    # （第三體攝動主導），只有末期才俯衝，全期 median 會漏判。
    rec = t_days >= (t_days[-1] - 45.0)
    if rec.sum() < 4:
        rec = np.ones(len(a), bool)
    rp_r, t_r = rp_alt[rec], t_days[rec]
    perigee_now = float(np.median(rp_r[-5:])) if rec.sum() >= 5 else float(rp_alt[-1])
    rate = float(np.polyfit(t_r, rp_r, 1)[0]) if rec.sum() >= 2 else 0.0  # km/day
    # 再入/即將再入（不用 reboost 計數——極端 HEO 的 sma 雜訊會假造正跳）：
    #   (a) 近地點極低 <150km（已觸底俯衝，如末期 Van Allen），或
    #   (b) 近地點低 <350km 且快速下降 rate<-2 km/day（如 Cluster）。
    # 站點(ISS 415 / 天宮 392)近地點 >350 且靠 reboost 維持(率≈0) → 不觸發。
    return bool(perigee_now < 150.0 or (perigee_now < 350.0 and rate < -2.0))


if __name__ == "__main__":
    # 快速自我測試：FORMOSAT-3A(純衰減,殘差≈0) vs 一顆機動 Starlink
    import duckdb
    from compare_tle_vs_ephemeris import load_registry
    sw = load_space_weather()
    con = duckdb.connect("space_db.duckdb", read_only=True)
    reg = load_registry("data/url_registry.csv"); n2n = {v: k for k, v in reg["sat_name"].items()}
    for nid, lbl in [(29052, "FORMOSAT-3A 純衰減"), (n2n.get("STARLINK-30273"), "STARLINK-30273 機動"),
                     (25544, "ISS reboost"), (38752, "Van Allen A HEO 再入(期望≈0)")]:
        df = con.execute("SELECT epoch_utc AS epoch, sma_km, eccentricity, line1, line2 "
                         "FROM raw_tle_archive "
                         "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
                         [int(nid)]).fetchdf()
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        r = drag_residual(df, sw)
        rd = r["drag_resid_da"].abs()
        print(f"{lbl} (n={len(r)}): B_eff={r.attrs['B_eff']:.3e}  "
              f"|resid| med={rd.median():.4f} P95={rd.quantile(0.95):.4f} max={rd.max():.4f} km  "
              f"|resid|>0.5km: {(rd>0.5).sum()}")
    con.close()
