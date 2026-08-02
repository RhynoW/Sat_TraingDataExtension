#!/usr/bin/env python3
"""
reentry_predict.py — 由 TLE 近地點高度衰減外推「再入大氣層」日期範圍。

方法：對高橢圓/衰減軌道，再入由**近地點高度**下降主導（sma 幾乎不變）。
取最終俯衝段（近地點 < cut_km）的近地點時序，以「近期線性率」與「加速(二次)」
兩模型外推至再入門檻（近地點 80/100/120 km），給出日期範圍。

用法：
  python reentry_predict.py 26410 26464
"""
from __future__ import annotations

import sys

import duckdb
import numpy as np
import pandas as pd

RE = 6378.137
DB = "space_db.duckdb"


def _load(nid: int) -> pd.DataFrame:
    con = duckdb.connect(DB, read_only=True)
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km, eccentricity FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
    con.close()
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    return df.drop_duplicates("epoch").reset_index(drop=True)


def predict_reentry(df: pd.DataFrame, cut_km: float = 2000.0,
                    recent_days: float = 45.0) -> dict:
    """回傳再入預測：近地點衰減外推至 80/100/120 km 的日期（線性 & 加速模型）。"""
    d = df.sort_values("epoch").reset_index(drop=True)
    a = d["sma_km"].to_numpy(float)
    e = d["eccentricity"].to_numpy(float)
    rp = a * (1.0 - e) - RE                                    # 近地點高度
    t = d["epoch"]
    t0 = t.iloc[0]
    tdays = (t - t0).dt.total_seconds().to_numpy() / 86400.0

    # 最終俯衝段：近地點 < cut_km
    mask = rp < cut_km
    if mask.sum() < 6:
        mask = rp < np.percentile(rp, 40)
    tw, rpw = tdays[mask], rp[mask]
    # 近期窗（最後 recent_days）
    rec = tw >= (tw[-1] - recent_days)
    if rec.sum() < 4:
        rec = np.ones_like(tw, bool)
    tr, rr = tw[rec], rpw[rec]

    lin = np.polyfit(tr, rr, 1)                               # 線性
    quad = np.polyfit(tr, rr, 2)                              # 加速
    t_last = tw[-1]
    rp_now = rpw[-1]

    def _cross(poly, target):
        r = np.roots(np.r_[poly[:-1], poly[-1] - target])
        fut = [x.real for x in r if abs(x.imag) < 1e-6 and x.real > t_last]
        return min(fut) if fut else None

    def _date(td):
        return (t0 + pd.Timedelta(days=float(td))) if td is not None else None

    out = {"norad_epoch": t.iloc[-1], "rp_now": rp_now,
           "rate_km_day": float(lin[0]), "n_recent": int(rec.sum())}
    for thr in (120, 100, 80):
        out[f"lin_{thr}"] = _date(_cross(lin, thr))
        out[f"quad_{thr}"] = _date(_cross(quad, thr))
    # 綜合範圍：加速模型(早) ~ 線性模型(晚)，門檻 100km 為中心
    cand = [out[f"quad_100"], out[f"lin_100"], out[f"quad_120"], out[f"lin_80"]]
    cand = [c for c in cand if c is not None]
    if cand:
        out["reentry_early"] = min(cand)
        out["reentry_late"] = max(cand)
        out["reentry_central"] = out["quad_100"] or out["lin_100"]
    return out


def main():
    ids = [int(x) for x in sys.argv[1:]] or [26410, 26464]
    for nid in ids:
        df = _load(nid)
        if len(df) < 10:
            print(f"NORAD {nid}: 資料不足"); continue
        r = predict_reentry(df)
        print("=" * 60)
        print(f"NORAD {nid} 再入預測（最新 TLE epoch {pd.Timestamp(r['norad_epoch']).date()}）")
        print(f"  目前近地點高度: {r['rp_now']:.0f} km   近期衰減率: {r['rate_km_day']:.2f} km/day")
        print(f"  近地點達 120/100/80 km 之日期：")
        for thr in (120, 100, 80):
            l = r.get(f"lin_{thr}"); q = r.get(f"quad_{thr}")
            ls = pd.Timestamp(l).date() if l is not None else "—"
            qs = pd.Timestamp(q).date() if q is not None else "—"
            print(f"     {thr} km：線性 {ls}   加速 {qs}")
        if r.get("reentry_central") is not None:
            print(f"  ▶ 預測再入日期範圍：{pd.Timestamp(r['reentry_early']).date()} "
                  f"～ {pd.Timestamp(r['reentry_late']).date()}"
                  f"（中心 {pd.Timestamp(r['reentry_central']).date()}）")


if __name__ == "__main__":
    main()
