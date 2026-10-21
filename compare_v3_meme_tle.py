#!/usr/bin/env python3
"""compare_v3_meme_tle.py — Starlink V3（Flight 14，NORAD 100855–100880）MEME 精密星曆 vs TLE。

每份 MEME（72 小時、1 分鐘）分開比對，不合併，以便看出每次預報各自之 TLE 落差：
  1. 位置殘差：每個 MEME 時刻取「該時刻之前最新一筆 TLE」以 SGP4 推算（沿用
     compare_tle_vs_ephemeris.propagate_with_best_tles／compute_residuals），算 3D 與 RTN 殘差。
  2. 高度軌跡：MEME 以 vis-viva 算瞬時半長軸，取一圈（約 91 分鐘）移動平均消除短週期項，
     與 TLE 平均半長軸對照；MEME 預報段可看出 SpaceX 已排定之升軌。

輸出：data/benchmark/v3_meme_vs_tle_summary_<日期>.csv（每星每檔一列）、
      data/benchmark/v3_meme_vs_tle_samples_<日期>.parquet（5 分鐘取樣明細）
用法：python compare_v3_meme_tle.py [--extra-tle 檔案.3le]
  --extra-tle：額外 TLE 檔（3LE），與資料庫合併，供每日排程尚未入庫之最新 TLE 使用。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sgp4.api import Satrec
from skyfield.api import load

from compare_tle_vs_ephemeris import compute_residuals, propagate_with_best_tles
from starlink_ephemeris.parser import parse_ephemeris_file

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
logging.basicConfig(level=logging.ERROR)

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "space_db.duckdb"
TAG = date.today().strftime("%Y%m%d")
OUT_SUM = ROOT / "data" / "benchmark" / f"v3_meme_vs_tle_summary_{TAG}.csv"
OUT_SMP = ROOT / "data" / "benchmark" / f"v3_meme_vs_tle_samples_{TAG}.parquet"
MU, R_E = 398600.4418, 6378.137
ORBIT_SAMPLES = 91          # 1 分鐘取樣下約一圈
SUBSAMPLE = 5               # 位置殘差每 5 分鐘取一點


def v3_roster(con) -> dict[str, int]:
    df = con.sql("select norad_id, any_value(object_name) nm from raw_tle_archive "
                 "where norad_id between 100855 and 100880 group by 1").df()
    return {nm.replace("0 ", "", 1).strip(): int(n) for n, nm in zip(df.norad_id, df.nm)}


def read_extra_tle(path: Path) -> pd.DataFrame:
    lines = [l.rstrip() for l in path.read_text(encoding="ascii").splitlines()]
    rows = []
    for l1, l2 in zip(lines, lines[1:]):
        if l1.startswith("1 ") and l2.startswith("2 "):
            sat = Satrec.twoline2rv(l1, l2)
            ep = pd.Timestamp(sat.jdsatepoch + sat.jdsatepochF - 2440587.5, unit="D", tz="UTC")
            rows.append(dict(norad_id=sat.satnum, line1=l1, line2=l2, epoch_utc=ep))
    return pd.DataFrame(rows, columns=["norad_id", "line1", "line2", "epoch_utc"])


def tles_for(con, norad: int, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    df = con.sql(f"select norad_id, line1, line2, epoch_utc from raw_tle_archive "
                 f"where norad_id={norad} order by epoch_utc").df()
    df["epoch_utc"] = pd.to_datetime(df.epoch_utc, utc=True)
    if extra is not None:
        df = pd.concat([df, extra[extra.norad_id == norad]], ignore_index=True)
    df = df.drop_duplicates(subset=["line1", "line2"]).sort_values("epoch_utc").reset_index(drop=True)
    df["epoch_utc"] = df.epoch_utc.dt.tz_localize(None).astype("datetime64[ns]")
    return df


def orbit_avg_alt(m: pd.DataFrame) -> np.ndarray:
    r = np.linalg.norm(m[["r_x", "r_y", "r_z"]].to_numpy(float), axis=1)
    v2 = (m[["v_x", "v_y", "v_z"]].to_numpy(float) ** 2).sum(axis=1)
    a = 1.0 / (2.0 / r - v2 / MU)
    return pd.Series(a).rolling(ORBIT_SAMPLES, center=True, min_periods=ORBIT_SAMPLES // 2).mean().to_numpy() - R_E


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra-tle", type=Path)
    args = ap.parse_args()
    extra = read_extra_tle(args.extra_tle) if args.extra_tle else None
    con = duckdb.connect(str(DB), read_only=True)
    ts = load.timescale()
    roster = v3_roster(con)
    sums, samples = [], []
    for name, norad in sorted(roster.items(), key=lambda kv: kv[1]):
        files = sorted((RAW / name).glob("*.txt"))
        tle = tles_for(con, norad, extra)
        for f in files:
            meta, m = parse_ephemeris_file(f, sat_id=name)
            m["t"] = pd.to_datetime(m["t"], utc=True)
            m["alt_avg"] = orbit_avg_alt(m)
            ms = m.iloc[::SUBSAMPLE].reset_index(drop=True)
            prop = propagate_with_best_tles(ms, tle, name, ts)
            res = compute_residuals(ms, prop) if not prop.empty else pd.DataFrame()
            t_ep = tle.epoch_utc.dt.tz_localize("UTC")
            idx = np.searchsorted(t_ep.values, ms.t.values, side="right") - 1
            ms["tle_age_h"] = np.where(idx >= 0, (ms.t.values - t_ep.values[np.clip(idx, 0, None)])
                                       / np.timedelta64(1, "h"), np.nan)
            if not res.empty:
                res = res.merge(ms[["t", "tle_age_h"]], on="t")
                res["norad"], res["name"], res["file"] = norad, name, f.stem
                samples.append(res[["norad", "name", "file", "t", "pos_err_km", "dr_r_km", "dr_t_km",
                                    "dr_n_km", "alt_avg", "tle_age_h"]])
            alt = m.alt_avg.dropna()
            covered = res[res.t <= t_ep.max() + pd.Timedelta(hours=8)] if not res.empty else res
            sums.append(dict(
                norad=norad, name=name, file=f.stem, meme_start=m.t.min(), meme_stop=m.t.max(),
                alt_start=alt.iloc[0], alt_end=alt.iloc[-1], alt_change_72h=alt.iloc[-1] - alt.iloc[0],
                n_cmp=len(covered),
                pos_med_km=covered.pos_err_km.median() if len(covered) else np.nan,
                pos_p95_km=covered.pos_err_km.quantile(0.95) if len(covered) else np.nan,
                along_med_km=covered.dr_t_km.abs().median() if len(covered) else np.nan,
                radial_med_km=covered.dr_r_km.abs().median() if len(covered) else np.nan,
                cross_med_km=covered.dr_n_km.abs().median() if len(covered) else np.nan,
                last_tle_epoch=t_ep.max(),
            ))
        print(f"  {name} ({norad}): {len(files)} 份 MEME")
    s = pd.DataFrame(sums)
    s.to_csv(OUT_SUM, index=False, encoding="utf-8-sig")
    if samples:
        pd.concat(samples, ignore_index=True).to_parquet(OUT_SMP, index=False)
    print(f"輸出 → {OUT_SUM}\n輸出 → {OUT_SMP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
