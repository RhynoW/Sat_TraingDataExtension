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

需求：pymsis、space_weather_ap.csv（Celestrak SW，含 F10.7_OBS / F10.7_OBS_CENTER81 / AP_AVG）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RE, MU = 6378.137, 398_600.4418
_SW_PATH = "space_weather_ap.csv"
_sw_cache: dict | None = None


def load_space_weather(path: str = _SW_PATH) -> dict:
    """回傳 {date_str: (f107_obs, f107_81avg, ap_avg)}（快取）。"""
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


def density(epochs, alt_km, sw=None, lat=0.0, lon=0.0) -> np.ndarray:
    """向量化 NRLMSIS 總質量密度 (kg/m³)；lat/lon 固定（常數偏差由 B_eff 校準吸收）。"""
    import pymsis
    sw = sw or load_space_weather()
    epochs = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True))
    dates = np.array([e.to_pydatetime().replace(tzinfo=None) for e in epochs])
    alt = np.asarray(alt_km, float)
    f, fa, a = _sw_arrays(epochs, sw)
    ap = np.tile(a[:, None], (1, 7))
    r = pymsis.calculate(dates, np.full(len(alt), lon), np.full(len(alt), lat),
                         alt, f, fa, ap)
    return np.asarray(r)[..., 0].ravel()


def drag_residual(df: pd.DataFrame, sw=None) -> pd.DataFrame:
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
    t_ns = t.astype("int64").to_numpy()
    dt_s = np.diff(t_ns) / 1e9
    da = np.diff(a)

    # ── 偏心軌道阻力模型（King-Hele）─────────────────────────────────────────
    # 阻力主要作用於近地點 → 於「近地點高度」取密度（非平均高度）；
    # 幾何因子 geom = exp(-z)[I₀(z)+2e·I₁(z)]，z=a·e/H（H≈大氣尺度高）。
    # e→0（近圓）時 geom→1，自動退化為原 LEO 圓軌公式。
    a0, e0 = a[:-1], e[:-1]
    alt_p = np.clip(a0 * (1.0 - e0) - RE, 80.0, 1000.0)   # 近地點高度（NRLMSIS 有效域）
    rho_p = density(t.iloc[:-1], alt_p, sw)               # 近地點密度
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
        df = con.execute("SELECT epoch_utc AS epoch, sma_km, eccentricity FROM raw_tle_archive "
                         "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
                         [int(nid)]).fetchdf()
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        r = drag_residual(df, sw)
        rd = r["drag_resid_da"].abs()
        print(f"{lbl} (n={len(r)}): B_eff={r.attrs['B_eff']:.3e}  "
              f"|resid| med={rd.median():.4f} P95={rd.quantile(0.95):.4f} max={rd.max():.4f} km  "
              f"|resid|>0.5km: {(rd>0.5).sum()}")
    con.close()
