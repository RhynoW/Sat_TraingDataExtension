"""把 leoOrb 真值與 TLE/SGP4 傳播結果比對，產出 RIC 殘差。

方法（與來源文件第 6.1 節一致）::

    對每個真值 epoch，取 **epoch 之前最近的一筆 TLE**（模擬實際作業使用方式），
    SGP4 傳播到該 epoch，轉到與真值同一框架，於 RIC 分解位置差。

框架處理
--------
SGP4 輸出 TEME，leoOrb 是 ITRF。本模組把 TLE 側 TEME -> ITRS（astropy，帶 EOP），
在 ITRF 分量下相減。RIC 基底以真值的位置與**慣性**速度建立
（SP3 給的是地固速度，需補 omega_E x r，見 archive.add_inertial_velocity）。

astropy 版本需求
----------------
需要 astropy >= 8.0。astropy 7.1.1 與 numpy 2.5.0 不相容，
且失敗時第一個斷點拋的是 AttributeError 而非 ImportError。
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np
import pandas as pd

try:
    import astropy.units as u
    from astropy.coordinates import ITRS, TEME, CartesianRepresentation
    from astropy.time import Time
    from astropy.utils import iers
except (ImportError, AttributeError) as _e:
    raise ImportError(
        """astropy 載入失敗：%s: %s
若 astropy 已安裝，通常是版本與 numpy 不相容，而非缺套件。
已知 astropy 7.1.1 + numpy 2.5.0 不相容，請執行：pip install -U astropy （>= 8.0）"""
        % (type(_e).__name__, _e)
    ) from _e

from sgp4.api import Satrec, jday

from .archive import OMEGA_EARTH_RAD_S

log = logging.getLogger(__name__)

FORMOSAT7_NORADS = (44349, 44351, 44343, 44350, 44358, 44353)


def load_tles(db_path: str,
              norad_ids: Sequence[int] = FORMOSAT7_NORADS,
              start: Optional[str] = None,
              end: Optional[str] = None) -> pd.DataFrame:
    """從 raw_tle_archive 取 TLE。回傳 norad_id, epoch_utc, line1, line2。"""
    import duckdb

    where = ["norad_id IN (%s)" % ",".join(str(int(n)) for n in norad_ids)]
    params: list = []
    if start:
        where.append("epoch_utc >= ?")
        params.append(start)
    if end:
        where.append("epoch_utc <= ?")
        params.append(end)
    sql = ("SELECT norad_id, epoch_utc, line1, line2 FROM raw_tle_archive "
           "WHERE " + " AND ".join(where) + " ORDER BY norad_id, epoch_utc")
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute(sql, params).df()
    finally:
        con.close()
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    return df


def _sgp4_batch(line1: np.ndarray, line2: np.ndarray,
                epochs: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """逐點 SGP4 傳播。回傳 (r_teme_km, v_teme_km_s, err_code)。"""
    n = len(epochs)
    r = np.full((n, 3), np.nan)
    v = np.full((n, 3), np.nan)
    err = np.zeros(n, dtype=int)
    cache: dict[tuple[str, str], Satrec] = {}
    for i, (l1, l2, t) in enumerate(zip(line1, line2, epochs)):
        key = (l1, l2)
        sat = cache.get(key)
        if sat is None:
            sat = cache[key] = Satrec.twoline2rv(l1, l2)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute,
                      t.second + t.microsecond / 1e6)
        e, rr, vv = sat.sgp4(jd, fr)
        err[i] = e
        if e == 0:
            r[i] = rr
            v[i] = vv
    return r, v, err


def teme_to_itrs_batch(r_teme_km: np.ndarray, epochs: pd.Series) -> np.ndarray:
    """向量化 TEME -> ITRS 位置轉換（帶 EOP）。"""
    t = Time(pd.DatetimeIndex(epochs).to_pydatetime(), scale="utc")
    rep = CartesianRepresentation(r_teme_km[:, 0] * u.km,
                                  r_teme_km[:, 1] * u.km,
                                  r_teme_km[:, 2] * u.km)
    itrs = TEME(rep, obstime=t).transform_to(ITRS(obstime=t))
    return itrs.cartesian.xyz.to(u.km).value.T


def compare(truth: pd.DataFrame,
            tles: pd.DataFrame,
            auto_download_eop: bool = False) -> pd.DataFrame:
    """真值 vs TLE 的 RIC 殘差。

    truth : merge.merge_arcs()/resample() 的輸出（需 norad_id, epoch, 位置與地固速度）
    tles  : load_tles() 的輸出

    回傳每個真值點一列：sp3_sat, norad_id, epoch, tle_epoch, age_h,
                       radial_km, in_track_km, cross_track_km, d3_km, sgp4_err
    """
    iers.conf.auto_download = auto_download_eop

    truth = truth.sort_values("epoch").reset_index(drop=True)
    tles = tles.sort_values("epoch_utc").reset_index(drop=True)
    # merge_asof 的 join 鍵型別必須逐位一致：duckdb 給 int32 / datetime64[us]，
    # 而真值側是 int64 / datetime64[ns]，不對齊會直接 MergeError。
    truth = truth.assign(
        norad_id=truth["norad_id"].astype("int64"),
        epoch=pd.to_datetime(truth["epoch"], utc=True).astype("datetime64[ns, UTC]"))
    tles = tles.assign(
        norad_id=tles["norad_id"].astype("int64"),
        epoch_utc=pd.to_datetime(tles["epoch_utc"], utc=True).astype("datetime64[ns, UTC]"))

    # 對每個真值 epoch 取「之前最近」的一筆 TLE
    merged = pd.merge_asof(
        truth, tles,
        left_on="epoch", right_on="epoch_utc",
        by="norad_id", direction="backward", allow_exact_matches=True,
    )
    n_before = len(merged)
    merged = merged[merged["line1"].notna()].reset_index(drop=True)
    if len(merged) < n_before:
        log.warning("有 %d 個真值點在其 TLE 之前，已剔除", n_before - len(merged))
    if merged.empty:
        raise ValueError("沒有任何真值點配到 TLE")

    r_teme, _, err = _sgp4_batch(merged["line1"].to_numpy(),
                                 merged["line2"].to_numpy(),
                                 merged["epoch"])
    ok = err == 0
    if not ok.all():
        log.warning("SGP4 失敗 %d 點，已剔除", int((~ok).sum()))
    merged = merged[ok].reset_index(drop=True)
    r_teme = r_teme[ok]

    r_tle = teme_to_itrs_batch(r_teme, merged["epoch"])

    r_true = merged[["x_km", "y_km", "z_km"]].to_numpy(float)
    v_ecef = merged[["vx_km_s", "vy_km_s", "vz_km_s"]].to_numpy(float)
    # RIC 基底要用慣性速度；SP3 給的是地固速度
    v_true = v_ecef + np.cross(np.array([0.0, 0.0, OMEGA_EARTH_RAD_S]), r_true)

    d = r_tle - r_true
    r_hat = r_true / np.linalg.norm(r_true, axis=1, keepdims=True)
    h = np.cross(r_true, v_true)
    c_hat = h / np.linalg.norm(h, axis=1, keepdims=True)
    i_hat = np.cross(c_hat, r_hat)

    out = pd.DataFrame({
        "sp3_sat": merged["sp3_sat"].to_numpy(),
        "norad_id": merged["norad_id"].to_numpy(),
        "epoch": merged["epoch"].to_numpy(),
        "tle_epoch": merged["epoch_utc"].to_numpy(),
        "radial_km": (d * r_hat).sum(1),
        "in_track_km": (d * i_hat).sum(1),
        "cross_track_km": (d * c_hat).sum(1),
    })
    out["age_h"] = (pd.to_datetime(out["epoch"], utc=True)
                    - pd.to_datetime(out["tle_epoch"], utc=True)
                    ).dt.total_seconds() / 3600.0
    out["d3_km"] = np.linalg.norm(d, axis=1)
    return out


_RMS = lambda x: float(np.sqrt(np.mean(np.square(x))))
_P95 = lambda x: float(np.percentile(np.abs(x), 95))


def summary_by_satellite(res: pd.DataFrame) -> pd.DataFrame:
    """逐星彙總（對應來源文件第 6.2 節表格）。單位 km。"""
    rows = []
    for sat, g in res.groupby("sp3_sat"):
        rows.append({
            "sp3_sat": sat, "n": len(g),
            "R_rms": _RMS(g.radial_km), "R_p95": _P95(g.radial_km),
            "I_rms": _RMS(g.in_track_km), "I_p95": _P95(g.in_track_km),
            "C_rms": _RMS(g.cross_track_km), "C_p95": _P95(g.cross_track_km),
            "d3_rms": _RMS(g.d3_km),
        })
    rows.append({
        "sp3_sat": "ALL", "n": len(res),
        "R_rms": _RMS(res.radial_km), "R_p95": _P95(res.radial_km),
        "I_rms": _RMS(res.in_track_km), "I_p95": _P95(res.in_track_km),
        "C_rms": _RMS(res.cross_track_km), "C_p95": _P95(res.cross_track_km),
        "d3_rms": _RMS(res.d3_km),
    })
    return pd.DataFrame(rows).set_index("sp3_sat").round(3)


#: 來源文件第 6.3 節的齡期分箱（小時上界）
AGE_BINS = (3.0, 6.0, 12.0, 24.0, 48.0)


def summary_by_day(res: pd.DataFrame, max_age_h: float | None = None) -> pd.DataFrame:
    """逐日彙總（單位 km）。用來檢視地磁擾動等時間相關效應。

    max_age_h : 給定時只取齡期 <= 該值的點。**做風暴比較時務必給**，
                否則齡期分布的日間差異會混進結果，被誤讀成風暴效應。
    """
    d = res if max_age_h is None else res[res["age_h"] <= max_age_h]
    day = pd.to_datetime(d["epoch"], utc=True).dt.strftime("%Y-%m-%d")
    rows = []
    for k, g in d.groupby(day):
        rows.append({
            "day": k, "n": len(g), "med_age_h": float(g.age_h.median()),
            "R_rms": _RMS(g.radial_km),
            "I_rms": _RMS(g.in_track_km),
            "C_rms": _RMS(g.cross_track_km),
            "d3_rms": _RMS(g.d3_km),
        })
    return pd.DataFrame(rows).set_index("day").round(3)


def summary_by_age(res: pd.DataFrame) -> pd.DataFrame:
    """依 TLE 齡期分箱彙總（對應來源文件第 6.3 節表格）。單位 km。"""
    labels = ["0-3", "3-6", "6-12", "12-24", "24-48"]
    b = pd.cut(res["age_h"], bins=(0.0,) + AGE_BINS, labels=labels,
               include_lowest=True, right=True)
    rows = []
    for lab, g in res.groupby(b, observed=True):
        rows.append({
            "age_h": str(lab), "n": len(g),
            "R_rms": _RMS(g.radial_km),
            "I_rms": _RMS(g.in_track_km),
            "C_rms": _RMS(g.cross_track_km),
            "d3_rms": _RMS(g.d3_km),
            "d3_p95": float(np.percentile(g.d3_km, 95)),
        })
    return pd.DataFrame(rows).set_index("age_h").round(3)
