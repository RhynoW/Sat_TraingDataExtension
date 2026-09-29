#!/usr/bin/env python3
"""s2_msis_compare.py — 在 STORM-AI 真值衛星的軌道／時刻上計算本專案各 NRLMSIS 口徑的密度。

軌道來源：
  GRACE-1/2（27391/27392）、GRACE-FO1（43476）：本專案 DuckDB raw_tle_archive（唯讀）之 TLE，
    SGP4 傳播得真實軌跡；專案口徑高度直接用 DB 的 sma_km/eccentricity（與 drag_residual 相同）。
  SWARM-A/B/C：STORM-AI initial states（實測為 ITRF 地固系根數）→ 轉慣性系 → 平均 a（Kozai
    一階短週期修正）→ J2 長期項外推（樣本間隔 ≤3 天）。
  CHAMP：DB 無 TLE、初始狀態框架不一致 → 不納入（見 README 限制）。

每個有真值的整點 t 計算：
  P0  單點 lat=lon=0、日均 Ap、高度 a(1−e)−RE（專案原版）
  P0b 單點 lat=lon=0、3h ap(7)                   （只換 Ap 解析度）
  P1  單點 星下點、3h ap(7)                       （專案現行 2026-09-09 版）
  P2  軌道平均 18 點、WGS84 大地高、3h ap(7)、F10.7 取前一日（MSIS 標準用法）
  P2d 軌道平均 18 點、日均 Ap                     （分離「Ap 解析度」與「軌道平均」兩效應）
輸出 out/msis_hourly.parquet
"""
from __future__ import annotations

import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_common import (DATA, DB, J2, MU, OUT, RE, OMEGA_E, eci_to_geodetic, gmst_rad,  # noqa: E402
                       use_swall)

NRING = 18
TLE_SATS = {"GRACE-1": 27391, "GRACE-2": 27392, "GRACE-FO1": 43476}
SWARM = ["SWARM-A", "SWARM-B", "SWARM-C"]


# ───────────────────────── 真值 → 整點 ─────────────────────────
def truth_hourly() -> pd.DataFrame:
    D = pd.read_parquet(DATA / "density_all.parquet")
    D["th"] = D["t"].dt.round("h")
    H = D.groupby(["sat", "th"], as_index=False)["rho_true"].mean().rename(columns={"th": "t"})
    return H


# ───────────────────────── TLE 衛星幾何 ─────────────────────────
def geom_tle(sat: str, nid: int, hours: pd.DatetimeIndex) -> pd.DataFrame:
    import duckdb
    from sgp4.api import Satrec, jday
    con = duckdb.connect(DB, read_only=True)
    T = con.execute("SELECT epoch_utc, line1, line2, sma_km, eccentricity FROM raw_tle_archive "
                    "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchdf()
    con.close()
    T["epoch_utc"] = pd.to_datetime(T["epoch_utc"])
    T = T.drop_duplicates("epoch_utc").reset_index(drop=True)
    ep = T["epoch_utc"].to_numpy()
    h = hours.to_numpy()
    idx = np.searchsorted(ep, h, side="right") - 1
    ok = idx >= 0
    gap = np.where(ok, (h - ep[np.clip(idx, 0, None)]) / np.timedelta64(1, "h"), np.inf)
    ok &= gap < 72                                   # 最近 TLE 需在 3 天內
    h, idx = h[ok], idx[ok]
    n = len(h)
    lat_r = np.zeros((n, NRING)); lon_r = np.zeros((n, NRING)); alt_r = np.zeros((n, NRING))
    lat0 = np.zeros(n); lon0 = np.zeros(n); alt0g = np.zeros(n)
    good = np.ones(n, bool)
    a = T["sma_km"].to_numpy()[idx]; e = T["eccentricity"].to_numpy()[idx]
    P = 2 * np.pi * np.sqrt(a ** 3 / MU)             # s
    for j in np.unique(idx):
        rows = np.where(idx == j)[0]
        s = Satrec.twoline2rv(T.at[j, "line1"], T.at[j, "line2"])
        # ring 時刻：t + (k−8.5)/18·P（以 t 為中心的一整圈）＋ t 本身
        off = ((np.arange(NRING) - (NRING - 1) / 2) / NRING)[None, :] * P[rows, None]
        tt = h[rows, None] + (off * 1e9).astype("timedelta64[ns]")
        tt = np.concatenate([tt, h[rows, None]], axis=1)          # 最後一欄 = t
        ti = pd.DatetimeIndex(tt.ravel())
        jd = ti.to_julian_date().to_numpy()
        jd_i = np.floor(jd - 0.5) + 0.5
        err, r, _ = s.sgp4_array(jd_i, jd - jd_i)
        r = np.asarray(r)
        la, lo, al = eci_to_geodetic(r[:, 0], r[:, 1], r[:, 2], gmst_rad(ti))
        la, lo, al = la.reshape(tt.shape), lo.reshape(tt.shape), al.reshape(tt.shape)
        lat_r[rows], lon_r[rows], alt_r[rows] = la[:, :NRING], lo[:, :NRING], al[:, :NRING]
        lat0[rows], lon0[rows], alt0g[rows] = la[:, -1], lo[:, -1], al[:, -1]
        good[rows] = (np.asarray(err).reshape(tt.shape) == 0).all(axis=1)
    alt_proj = a * (1 - e) - RE                      # 與 atmospheric_drag.drag_residual 相同
    G = pd.DataFrame({"sat": sat, "t": h, "alt_proj": alt_proj, "a_km": a, "lat0": lat0,
                      "lon0": lon0, "alt0_geod": alt0g, "tle_gap_h": gap[ok]})
    G["ring_lat"] = list(lat_r); G["ring_lon"] = list(lon_r); G["ring_alt"] = list(alt_r)
    return G[good].reset_index(drop=True)


# ───────────────────────── Swarm 幾何（ITRF 根數）─────────────────────────
def _kep2rv(a, e, i, W, w, nu):
    p = a * (1 - e * e)
    r = p / (1 + e * np.cos(nu))
    u = w + nu
    cW, sW, ci, si = np.cos(W), np.sin(W), np.cos(i), np.sin(i)
    R = np.stack([r * (cW * np.cos(u) - sW * np.sin(u) * ci),
                  r * (sW * np.cos(u) + cW * np.sin(u) * ci),
                  r * np.sin(u) * si], -1)
    vr = np.sqrt(MU / p) * e * np.sin(nu)
    vt = np.sqrt(MU / p) * (1 + e * np.cos(nu))
    ur = R / r[:, None]
    h = np.stack([sW * si, -cW * si, ci], -1)        # 角動量單位向量
    ut = np.cross(h, ur)
    V = vr[:, None] * ur + vt[:, None] * ut
    return R, V


def _rv2kep(R, V):
    r = np.linalg.norm(R, axis=1); v2 = (V ** 2).sum(1)
    H = np.cross(R, V); hn = np.linalg.norm(H, axis=1)
    i = np.arccos(H[:, 2] / hn)
    W = np.arctan2(H[:, 0], -H[:, 1])
    a = 1 / (2 / r - v2 / MU)
    # 緯度引數 u
    nvec = np.stack([np.cos(W), np.sin(W), np.zeros_like(W)], -1)
    cu = (R * nvec).sum(1) / r
    su = R[:, 2] / (r * np.sin(i))
    u = np.arctan2(su, cu)
    return a, i, W, u


def geom_swarm(sat: str, init: pd.DataFrame, hours: pd.DatetimeIndex) -> pd.DataFrame:
    I = init.sort_values("t0").drop_duplicates("t0").reset_index(drop=True)
    t0 = pd.DatetimeIndex(I["t0"])
    # ITRF 根數 → ITRF 位置/速度 → 慣性
    R, V = _kep2rv(I["a"].to_numpy(), I["e"].to_numpy(), np.radians(I["i"].to_numpy()),
                   np.radians(I["raan"].to_numpy()), np.radians(I["argp"].to_numpy()),
                   np.radians(I["nu"].to_numpy()))
    g = gmst_rad(t0)
    V_in = V + np.cross(np.array([0, 0, OMEGA_E])[None, :], R)   # v_eci = v_ecef + ω×r（在地固座標）
    c, s = np.cos(g), np.sin(g)
    Rot = lambda X: np.stack([c * X[:, 0] - s * X[:, 1], s * X[:, 0] + c * X[:, 1], X[:, 2]], -1)
    a_o, inc, W, u = _rv2kep(Rot(R), Rot(V_in))
    # Kozai 一階：a_osc − a_mean ≈ 1.5·J2·RE²/a·sin²i·cos2u（e≈0）
    a_m = a_o - 1.5 * J2 * RE ** 2 / a_o * np.sin(inc) ** 2 * np.cos(2 * u)
    I = I.assign(a_mean=a_m, inc_in=inc, W_in=W, u0=u)
    h = hours.to_numpy()
    idx = np.searchsorted(t0.to_numpy(), h, side="right") - 1
    ok = idx >= 0
    dt = np.where(ok, (h - t0.to_numpy()[np.clip(idx, 0, None)]) / np.timedelta64(1, "s"), np.inf)
    ok &= dt < 3.6 * 86400
    h, idx, dt = h[ok], idx[ok], dt[ok]
    a = a_m[idx]; i_ = inc[idx]
    # a 在相鄰樣本間線性內插（衰減）；無下一筆則用本筆
    nxt = np.clip(idx + 1, 0, len(I) - 1)
    dtn = (t0.to_numpy()[nxt] - t0.to_numpy()[idx]) / np.timedelta64(1, "s")
    w = np.where((nxt > idx) & (dtn < 4 * 86400) & (dtn > 0), np.clip(dt / np.where(dtn > 0, dtn, 1), 0, 1), 0)
    a = a * (1 - w) + a_m[nxt] * w
    n = np.sqrt(MU / a ** 3)
    p = a
    dW = -1.5 * n * J2 * (RE / p) ** 2 * np.cos(i_)
    du = n * (1 + 0.75 * J2 * (RE / p) ** 2 * (3 * np.cos(i_) ** 2 - 1)) \
        + 0.75 * n * J2 * (RE / p) ** 2 * (5 * np.cos(i_) ** 2 - 1)   # 平均緯度引數率（含 J2）
    Wt = W[idx] + dW * dt
    ut = u[idx] + du * dt
    P = 2 * np.pi / n
    k = (np.arange(NRING) - (NRING - 1) / 2) / NRING
    uu = np.concatenate([ut[:, None] + 2 * np.pi * k[None, :], ut[:, None]], axis=1)
    tt = h[:, None] + ((k[None, :] * P[:, None]) * 1e9).astype("timedelta64[ns]")
    tt = np.concatenate([tt, h[:, None]], axis=1)
    cW, sW, ci, si = np.cos(Wt)[:, None], np.sin(Wt)[:, None], np.cos(i_)[:, None], np.sin(i_)[:, None]
    x = a[:, None] * (cW * np.cos(uu) - sW * np.sin(uu) * ci)
    y = a[:, None] * (sW * np.cos(uu) + cW * np.sin(uu) * ci)
    z = a[:, None] * np.sin(uu) * si
    gm = gmst_rad(pd.DatetimeIndex(tt.ravel())).reshape(tt.shape)
    la, lo, al = eci_to_geodetic(x, y, z, gm)
    G = pd.DataFrame({"sat": sat, "t": h, "alt_proj": a - RE, "a_km": a, "lat0": la[:, -1],
                      "lon0": lo[:, -1], "alt0_geod": al[:, -1], "tle_gap_h": dt / 3600})
    G["ring_lat"] = list(la[:, :NRING]); G["ring_lon"] = list(lo[:, :NRING]); G["ring_alt"] = list(al[:, :NRING])
    return G


def load_init() -> pd.DataFrame:
    I = pd.read_parquet(DATA / "initial_states_raw.parquet")
    I = I.rename(columns={"File ID": "file_id", "Timestamp": "t0", "Semi-major Axis (km)": "a",
                          "Eccentricity": "e", "Inclination (deg)": "i", "RAAN (deg)": "raan",
                          "Argument of Perigee (deg)": "argp", "True Anomaly (deg)": "nu",
                          "Latitude (deg)": "lat", "Longitude (deg)": "lon", "Altitude (km)": "alt"})
    I["t0"] = pd.to_datetime(I["t0"], format="mixed")
    I["file_id"] = pd.to_numeric(I["file_id"], errors="coerce")
    I.loc[I["alt"] > 5000, "alt"] /= 1000.0              # 部分檔高度單位為 m
    I.loc[I["a"] > 1e5, "a"] /= 1000.0
    D = pd.read_parquet(DATA / "density_all.parquet")[["sat", "file_id"]].drop_duplicates()
    return I.merge(D, on="file_id", how="inner").drop_duplicates(["sat", "t0"])


def add_geom_features(G: pd.DataFrame) -> pd.DataFrame:
    """由 ring 陣列算星下點地方時 lst0、升段旗標 asc0、升交點地方時 ltan。"""
    # 幾何特徵：星下點地方時、升/降段、升交點地方時（LTAN，由 ring 過赤道北向點求）
    hr = pd.DatetimeIndex(G["t"]).hour.to_numpy() + pd.DatetimeIndex(G["t"]).minute.to_numpy() / 60
    G["lst0"] = (hr + G["lon0"].to_numpy() / 15.0) % 24
    ltan, asc = np.full(len(G), np.nan), np.zeros(len(G), bool)
    k = (np.arange(NRING) - (NRING - 1) / 2) / NRING
    for j, (la0_, lo0_) in enumerate(zip(G["ring_lat"].to_numpy(), G["ring_lon"].to_numpy())):
        Pj = 2 * np.pi * np.sqrt(G["a_km"].iat[j] ** 3 / MU) / 3600.0
        # 環狀首尾相接：首點一整圈後的地固經度需扣掉地球自轉 360°·P/恆星日
        la_, lo_ = np.append(la0_, la0_[0]), np.append(lo0_, lo0_[0] - 360.0 * Pj / 23.9345)
        up = np.where((la_[:-1] < 0) & (la_[1:] >= 0))[0]
        if len(up):
            q = up[0]; w_ = -la_[q] / (la_[q + 1] - la_[q])
            dl = ((lo_[q + 1] - lo_[q] + 180) % 360) - 180
            lon_n = lo_[q] + w_ * dl
            # ring 點時間 = t + k·P；地方時需用該點當刻 UTC
            ltan[j] = (hr[j] + (k[q] + w_ / NRING) * Pj + lon_n / 15.0) % 24
        mid = NRING // 2
        asc[j] = la0_[mid] > la0_[mid - 1]
    G["ltan"], G["asc0"] = ltan, asc
    return G


# ───────────────────────── MSIS 平行計算 ─────────────────────────
STORM_OPT = None


def _storm_opt():
    import pymsis
    return pymsis.msis.create_options(geomagnetic_activity=-1)   # 開關 9 = −1：啟用 3h ap(7) 陣列


def _worker(args):
    """口徑：
    P0   專案原版（lat=lon=0、ap 全填日均）＝AD.density 關掉 3h
    P1   專案現行寫法原樣（星下點 + 傳入 3h ap(7)，但 pymsis 預設開關 9=1 → ap[1:] 被忽略）
    P0s  lat=lon=0 + 3h ap(7) 且開關 9=−1（隔離「3h ap 真正生效」的效果）
    P1s  星下點 + 3h ap(7) 且開關 9=−1（2026-09-09 改良的原本意圖）
    P2   軌道平均 18 點、3h ap(7)、開關 9=−1、F10.7 前一日（MSIS 標準用法）
    P2d  軌道平均 18 點、開關 9=1（實質只用日均 Ap）"""
    kind, t, alt, lat, lon = args
    AD, sw = use_swall()
    import pymsis
    if kind == "P0":
        AD._ap3h_cache = pd.Series(dtype=float)
        return AD.density(t, alt, sw, lat=0.0, lon=0.0)
    if kind == "P1":
        return AD.density(t, alt, sw, lat=lat, lon=lon)
    ti = pd.DatetimeIndex(t)
    f, fa, apd = AD._sw_arrays(ti, sw)
    ap7 = AD._ap7_array(ti, apd)
    dates = ti.tz_convert(None).to_numpy() if ti.tz is not None else ti.to_numpy()
    if kind in ("P0s", "P1s"):
        la = np.zeros(len(alt)) if kind == "P0s" else lat
        lo = np.zeros(len(alt)) if kind == "P0s" else lon
        r = pymsis.calculate(dates, lo, la, alt, f, fa, ap7, options=_storm_opt())
        return np.asarray(r)[..., 0].ravel()
    # P2 / P2d
    keys_prev = (ti - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    f_prev = np.array([sw.get(k, (np.nan,) * 3)[0] for k in keys_prev], float)
    f_prev = np.where(np.isfinite(f_prev), f_prev, f)
    opt = _storm_opt() if kind == "P2" else None
    r = pymsis.calculate(dates, lon, lat, alt, f_prev, fa, ap7, options=opt)
    return np.asarray(r)[..., 0].ravel()


def run_parallel(kind, t, alt, lat, lon, nproc=30, chunk=20000):
    parts = [(kind, t[s:s + chunk], alt[s:s + chunk], lat[s:s + chunk], lon[s:s + chunk])
             for s in range(0, len(t), chunk)]
    with Pool(nproc) as pool:
        res = pool.map(_worker, parts)
    return np.concatenate(res)


def main():
    t_start = time.time()
    H = truth_hourly()
    print("真值整點：", H.groupby("sat")["t"].agg(["min", "max", "count"]).to_string())
    geoms = []
    for sat, nid in TLE_SATS.items():
        hrs = pd.DatetimeIndex(H.loc[H["sat"] == sat, "t"])
        if len(hrs):
            G = geom_tle(sat, nid, hrs)
            print(f"  {sat}: 幾何 {len(G)}/{len(hrs)} 點（TLE）", flush=True)
            geoms.append(G)
    init = load_init()
    for sat in SWARM:
        hrs = pd.DatetimeIndex(H.loc[H["sat"] == sat, "t"])
        ii = init[init["sat"] == sat]
        if len(hrs) and len(ii):
            G = geom_swarm(sat, ii, hrs)
            print(f"  {sat}: 幾何 {len(G)}/{len(hrs)} 點（ITRF 根數 {len(ii)} 筆）", flush=True)
            geoms.append(G)
    G = pd.concat(geoms, ignore_index=True)
    G = G.merge(H, on=["sat", "t"], how="left")
    print(f"幾何完成 {len(G):,} 整點，{time.time()-t_start:.0f}s", flush=True)

    t = pd.DatetimeIndex(G["t"]).tz_localize("UTC")
    for kind in ["P0", "P1", "P0s", "P1s"]:
        G[f"rho_{kind}"] = run_parallel(kind, t, G["alt_proj"].to_numpy(),
                                        G["lat0"].to_numpy(), G["lon0"].to_numpy())
        print(f"  {kind} 完成 {time.time()-t_start:.0f}s", flush=True)
    tr = np.repeat(G["t"].to_numpy(), NRING)
    la = np.concatenate(G["ring_lat"].to_numpy()); lo = np.concatenate(G["ring_lon"].to_numpy())
    al = np.concatenate(G["ring_alt"].to_numpy())
    for kind in ["P2", "P2d"]:
        r = run_parallel(kind, pd.DatetimeIndex(tr), al, la, lo)
        G[f"rho_{kind}"] = r.reshape(-1, NRING).mean(axis=1)
        print(f"  {kind} 完成 {time.time()-t_start:.0f}s", flush=True)
    G["ring_alt_mean"] = [float(np.mean(x)) for x in G["ring_alt"]]
    G = add_geom_features(G)
    G = G.drop(columns=["ring_lat", "ring_lon", "ring_alt"])
    G.to_parquet(OUT / "msis_hourly.parquet", index=False)
    print(f"→ {OUT/'msis_hourly.parquet'}  {len(G):,} 列，{time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
