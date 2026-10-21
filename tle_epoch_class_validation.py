#!/usr/bin/env python3
"""tle_epoch_class_validation.py — 以有 MEME 之 Starlink 驗證「TLE 依 epoch 時刻分兩類」之假說。

假說（源自 Starlink V3，compare_v3_meme_tle.py）：Space-Track 之 Starlink TLE 分為
  整點類：epoch 恰為整點（分=0、秒≤2），疑由營運方（SpaceX）星曆擬合；
  非整點類：其餘，疑為雷達自行定軌。
兩類於 epoch 附近同樣準，但非整點類之 ndot／B* 偏大，外推迅速失準。

兩層驗證：
  A. 全量統計：每星全部 TLE 之分類比例、整點 epoch 之時刻分布、逐月比例。
  B. 準度抽樣：每星均勻抽至多 N_FILES 份 MEME，僅取每份前 24 小時（升軌期 MEME 預報超過 24h 會失準），
     每 10 分鐘一點，分別以「該時刻之前最新之整點類 TLE」與「最新之非整點類 TLE」推算，比較相同 TLE 年齡下之誤差。
排除 V3（NORAD ≥ 100000），其已另案分析。

輸出：data/benchmark/tle_epoch_class_{tles,samples}_<日期>.parquet
用法：python tle_epoch_class_validation.py [--n-files 10]
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
TAG = date.today().strftime("%Y%m%d")
OUT_TLE = ROOT / "data" / "benchmark" / f"tle_epoch_class_tles_{TAG}.parquet"
OUT_SMP = ROOT / "data" / "benchmark" / f"tle_epoch_class_samples_{TAG}.parquet"
TRUTH_HOURS = 24
STEP_MIN = 10


def classify(ep: pd.Series) -> pd.Series:
    return (ep.dt.minute == 0) & (ep.dt.second <= 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-files", type=int, default=10)
    args = ap.parse_args()

    reg = pd.read_csv(ROOT / "data" / "url_registry.csv", usecols=["norad_id", "sat_name"])
    reg = reg.drop_duplicates("norad_id")
    reg = reg[(reg.norad_id < 100000) & reg.sat_name.map(lambda s: (RAW / str(s)).is_dir())]
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    ids = ",".join(str(int(n)) for n in reg.norad_id)
    tle = con.sql(f"select norad_id, line1, line2, epoch_utc from raw_tle_archive "
                  f"where norad_id in ({ids})").df()
    tle["epoch_utc"] = pd.to_datetime(tle.epoch_utc, utc=True)
    tle = tle.drop_duplicates(subset=["line1", "line2"]).sort_values(["norad_id", "epoch_utc"])
    tle["onhour"] = classify(tle.epoch_utc)
    tle["ndot"] = tle.line1.str[33:43].astype(float)
    tle["bstar"] = tle.line1.str[53:61].map(_bstar)
    tle[["norad_id", "epoch_utc", "onhour", "ndot", "bstar"]].to_parquet(OUT_TLE, index=False)
    print(f"A. TLE {len(tle):,} 筆／{tle.norad_id.nunique()} 顆 → {OUT_TLE}")

    ts = load.timescale()
    samples = []
    for k, (norad, name) in enumerate(zip(reg.norad_id, reg.sat_name), 1):
        t_sat = tle[tle.norad_id == norad]
        if t_sat.empty:
            continue
        lo, hi = t_sat.epoch_utc.min(), t_sat.epoch_utc.max()
        files = [f for f in sorted((RAW / name).glob("*.txt")) if lo <= _file_time(f) <= hi]
        if not files:
            continue
        pick = [files[i] for i in np.unique(np.linspace(0, len(files) - 1, args.n_files).round().astype(int))]
        for f in pick:
            try:
                _, m = parse_ephemeris_file(f, sat_id=name)
            except Exception:
                continue
            m["t"] = pd.to_datetime(m["t"], utc=True)
            m = m[m.t <= m.t.min() + pd.Timedelta(hours=TRUTH_HOURS)].iloc[::STEP_MIN].reset_index(drop=True)
            for cls in (True, False):
                tc = t_sat[t_sat.onhour == cls][["norad_id", "line1", "line2", "epoch_utc"]].copy()
                tc = tc[tc.epoch_utc <= m.t.max()]
                if tc.empty:
                    continue
                tc["epoch_utc"] = tc.epoch_utc.dt.tz_localize(None).astype("datetime64[ns]")
                tc = tc.reset_index(drop=True)
                idx = np.searchsorted(tc.epoch_utc.values, m.t.dt.tz_localize(None).values, side="right") - 1
                mm = m[idx >= 0].reset_index(drop=True)
                if mm.empty:
                    continue
                prop = propagate_with_best_tles(mm, tc, name, ts)
                res = compute_residuals(mm, prop)
                ep = tc.epoch_utc.values[idx[idx >= 0]]
                res["tle_age_h"] = (mm.t.dt.tz_localize(None).values - ep) / np.timedelta64(1, "h")
                res["onhour"], res["norad"], res["file"] = cls, norad, f.stem
                samples.append(res[["norad", "file", "t", "onhour", "tle_age_h",
                                    "pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km"]])
        if k % 20 == 0:
            print(f"  B. {k}/{len(reg)} 顆")
    out = pd.concat(samples, ignore_index=True)
    out.to_parquet(OUT_SMP, index=False)
    print(f"B. 樣本 {len(out):,} 點／{out.norad.nunique()} 顆 → {OUT_SMP}")
    return 0


def _bstar(s: str) -> float:
    s = s.strip()
    try:
        mant, exp = s[:-2], s[-2:]
        return float(f"{mant[0] if mant[0] in '+-' else ''}0.{mant.lstrip('+-')}e{exp}")
    except (ValueError, IndexError):
        return np.nan


def _file_time(f: Path) -> pd.Timestamp:
    return pd.Timestamp(f.stem.replace("T", " ")[:10] + " " + f.stem[11:19].replace("-", ":"), tz="UTC")


if __name__ == "__main__":
    raise SystemExit(main())
