#!/usr/bin/env python3
"""
ml_model2_anomaly.py — 第二套 ML 模型：Regime-agnostic 物理殘差異常偵測器
=========================================================================
定位（與 Model 1 互補）：
  Model 1 (models_meme, 監督式 LGBM)：只在 Starlink LEO 訓練、依賴 alt/inc 族群先驗，
    對非 Starlink/衰減軌（FORMOSAT-3A、GEO、MEO）分布外誤報 → 需物理閘門。
  Model 2 (本檔, 無監督)：以「物理殘差」為輸入，通用任何軌道類別、無需 MEME 真值。

物理殘差通道（皆已扣除自然演化，殘差≈機動）：
  z_drag  = NRLMSIS 阻力殘差 Δa / 0.10 km        （扣大氣阻力，含 F10.7/Ap 變化）
  z_di    = Δinclination / 0.005 deg
  z_de    = Δecc / 2e-4
  z_draan = J2 修正後 ΔRAAN 殘差 / 0.03 deg
固定「物理地板」正規化（非自我 MAD）→ 安靜衛星雜訊不被放大、忙碌衛星保留敏感度。

Isolation Forest 學跨衛星「正常」殘差分布，離群 = 機動。純衰減衛星殘差皆 < 1 → 不誤報。

用法： python ml_model2_anomaly.py --max-sats 80
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from atmospheric_drag import drag_residual, load_space_weather
from compare_tle_vs_ephemeris import load_registry

RE, MU, J2 = 6378.137, 398_600.4418, 1.082_63e-3
_CH = ["z_drag", "z_di", "z_de", "z_draan"]
_FLOOR = {"z_drag": 0.10, "z_di": 0.005, "z_de": 2e-4, "z_draan": 0.03}


def _ang(a1, a2):
    d = (a2 - a1) % 360.0
    return np.where(d > 180.0, d - 360.0, d)


def _j2_raan(a, e, i_deg, dt_s):
    i = np.radians(i_deg)
    n = np.sqrt(MU / a ** 3)
    p = a * (1 - e ** 2)
    return np.degrees(-1.5 * n * J2 * (RE / p) ** 2 * np.cos(i)) * dt_s


def physical_residuals(df: pd.DataFrame, sw=None) -> pd.DataFrame:
    """逐轉換物理殘差通道（固定物理地板正規化）。
    df 欄位：epoch, sma_km, inclination_deg, eccentricity, raan_deg。"""
    d = df.sort_values("epoch").reset_index(drop=True)
    if len(d) < 5:
        return pd.DataFrame()
    _c = ["epoch", "sma_km"] + (["eccentricity"] if "eccentricity" in d.columns else [])
    dr = drag_residual(d[_c], sw)                        # NRLMSIS 阻力殘差（偏心軌道感知）
    if dr.empty:
        return pd.DataFrame()
    a = d["sma_km"].to_numpy(float)
    inc = d["inclination_deg"].to_numpy(float)
    e = d["eccentricity"].to_numpy(float)
    raan = d["raan_deg"].to_numpy(float)
    t_ns = pd.to_datetime(d["epoch"], utc=True).astype("int64").to_numpy()
    dt_s = np.diff(t_ns) / 1e9

    di = np.diff(inc)
    de = np.diff(e)
    draan = _ang(raan[:-1], raan[1:]) - _j2_raan(a[:-1], e[:-1], inc[:-1], dt_s)

    out = pd.DataFrame({"epoch": dr["epoch"].to_numpy()})
    out["z_drag"] = dr["drag_resid_da"].to_numpy() / _FLOOR["z_drag"]
    out["z_di"] = di / _FLOOR["z_di"]
    out["z_de"] = de / _FLOOR["z_de"]
    out["z_draan"] = draan / _FLOOR["z_draan"]
    return out


def _load(con, nid):
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg "
        "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
        [int(nid)]).fetchdf()
    if not df.empty:
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        df = df.drop_duplicates("epoch").reset_index(drop=True)
    return df


def _collapse(ns, gap):
    if len(ns) == 0:
        return []
    t = np.sort(ns); eps = []; s = p = t[0]
    for x in t[1:]:
        if x - p > gap:
            eps.append((int(s), int(p))); s = x
        p = x
    eps.append((int(s), int(p))); return eps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--max-sats", type=int, default=80)
    ap.add_argument("--contamination", type=float, default=0.04)
    ap.add_argument("--save", default="Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl")
    args = ap.parse_args()

    sw = load_space_weather()
    reg = load_registry(args.data_root / "url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    tg = sorted((args.data_root / "meme_truth").glob("transitions_full_*.csv"))
    truth = pd.read_csv(tg[-1]); truth = truth[truth["da_severity"].isin(["medium", "large"])]
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True)
    gap = int(48 * 3.6e12)
    ep_by = {s: _collapse(g["t_to"].astype("int64").to_numpy(), gap) for s, g in truth.groupby("sat_name")}

    con = duckdb.connect(args.db, read_only=True)
    sats = list(n2n.items())[: args.max_sats]
    per_sat, pool = {}, []
    for name, nid in sats:
        r = physical_residuals(_load(con, nid), sw)
        if not r.empty:
            per_sat[name] = r
            pool.append(r[_CH].to_numpy())
    X = np.clip(np.nan_to_num(np.vstack(pool)), -200, 200)
    iso = IsolationForest(n_estimators=200, contamination=args.contamination,
                          random_state=42, n_jobs=-1).fit(X)
    print(f"Model 2 訓練：{len(per_sat)} 顆、{len(X)} 轉換")

    tol = int(24 * 3.6e12)
    nt = nh = nd = ndh = 0
    for name, r in per_sat.items():
        Xs = np.clip(np.nan_to_num(r[_CH].to_numpy()), -200, 200)
        flag = iso.predict(Xs) == -1
        det = r["epoch"].astype("int64").to_numpy()[flag]
        eps = ep_by.get(name, [])
        nt += len(eps); nd += len(det)
        for (s, e) in eps:
            if np.any((det >= s - tol) & (det <= e + tol)):
                nh += 1
        for dt in det:
            if any((s - tol) <= dt <= (e + tol) for (s, e) in eps):
                ndh += 1
    print(f"\n=== Model 2 vs MEME episode（{len(per_sat)} 顆）===")
    print(f"  episodes={nt} 偵測={nd} Recall={nh/nt if nt else 0:.3f} Precision={ndh/nd if nd else 0:.3f}")

    print("\n=== OOD 檢查（純衰減，應 ~0）===")
    for nid, lbl in [(29052, "FORMOSAT-3A")]:
        r = physical_residuals(_load(con, nid), sw)
        Xf = np.clip(np.nan_to_num(r[_CH].to_numpy()), -200, 200)
        flag = iso.predict(Xf) == -1
        print(f"  {lbl}(29052): {len(r)} 轉換 異常={int(flag.sum())} ({100*flag.mean():.1f}%) "
              f"max|z_drag|={np.abs(r['z_drag']).max():.1f}")
    con.close()

    try:
        import joblib
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": iso, "channels": _CH, "floor": _FLOOR}, args.save)
        print(f"\n模型已存 → {args.save}")
    except Exception as e:
        print("存檔略過:", e)


if __name__ == "__main__":
    main()
