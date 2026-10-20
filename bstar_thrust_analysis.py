#!/usr/bin/env python3
"""bstar_thrust_analysis.py — B* 是否吸收推力？對 L1 規則層有何影響？（StoryMap 案例三十之資料來源）

SGP4 沒有推力項，持續推進之衛星，其未建模之沿軌加速度只能被擬合進阻力參數 B*。
本程式以四部分檢驗此假說與其對偵測之影響：
  A. 族群統計：2026-08 起、高度 <1300 km 近圓軌道之全部物件，逐物件計算
     B* 跳動（相鄰 TLE |ΔB*|／|B*| 中位數）、負 B* 比例、|ndot| 中位數，依族群（Starlink／OneWeb／Kuiper／
     碎片與火箭殘骸／其他酬載）與高度帶彙總。
  B. MEME 真值檢驗（Starlink 284 顆）：每份抽樣 MEME 僅用前 24 小時（升軌期預報超過 24h 會失準），
     以一圈（91 分鐘）移動平均消除短週期項得軌道平均高度；
     B1 逐 TLE：epoch 前 12 小時之 MEME 平均高度變化率（km/天）＝推力真值，對照該 TLE 之 B*、ndot；
     B2 逐轉換：TLE 相鄰兩筆之 MEME 高度實際變化，對照 L1（apply_strategies）之偵測與 P1／P3 抑制。
  C. L1 於同高度帶（450–600 km）不推進物件（碎片、其他酬載）之旗標率，與 Starlink 對照。
  D. 範例時序：OneWeb／碎片（~1200 km）與 Starlink／碎片（~480 km）之 B* 時序，供頁面繪圖。

輸出：data/benchmark/bstar_thrust_{population,tle_truth,transitions,l1_control,examples}_<日期>.csv
用法：python bstar_thrust_analysis.py [--n-files 20] [--n-control 300]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from maneuver_strategies_july import apply_strategies, build_transitions, classify_orbit
from starlink_ephemeris.parser import parse_ephemeris_file

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "space_db.duckdb"
TAG = date.today().strftime("%Y%m%d")
OUT = {k: ROOT / "data" / "benchmark" / f"bstar_thrust_{k}_{TAG}.csv"
       for k in ("population", "tle_truth", "transitions", "l1_control", "examples")}
SINCE = "2026-08-01"
MU, R_E = 398600.4418, 6378.137
ORBIT_SAMPLES = 91
TRUTH_HOURS = 24
RATE_WINDOW_H = 12


def group_of(name: str) -> str:
    n = str(name).upper().replace("0 ", "", 1)
    if "STARLINK" in n:
        return "Starlink"
    if "ONEWEB" in n:
        return "OneWeb"
    if "KUIPER" in n:
        return "Kuiper"
    if " DEB" in n or n.endswith("DEB") or " R/B" in n:
        return "debris"
    if n.startswith("TBA"):
        return "new_unnamed"
    return "other_payload"


# ── A. 族群統計 ──────────────────────────────────────────────────────────────
def part_a(con) -> pd.DataFrame:
    q = f"""
    with t as (
      select norad_id n, object_name nm, epoch_utc ep, sma_km - {R_E} alt, bstar b,
             try_cast(trim(substr(line1, 34, 10)) as double) nd
      from raw_tle_archive
      where epoch_utc >= '{SINCE}' and sma_km < {R_E} + 1300 and eccentricity < 0.01
    ),
    d as (select distinct on (n, ep) * from t order by n, ep),
    w as (select *, b - lag(b) over (partition by n order by ep) db from d)
    select n norad_id, any_value(nm) object_name, median(alt) alt_km, count(*) n_tle,
      avg(case when b < 0 then 1 else 0 end) neg_bstar_frac,
      median(abs(b)) bstar_abs_med, median(abs(db)) dbstar_abs_med,
      median(abs(nd)) ndot_abs_med,
      avg(case when extract(minute from ep) = 0 and extract(second from ep) < 3 then 1 else 0 end) onhour_frac
    from w group by n having count(*) >= 20
    """
    s = con.sql(q).df()
    s["group"] = s.object_name.map(group_of)
    s["bstar_jump_rel"] = s.dbstar_abs_med / s.bstar_abs_med
    s["alt_band"] = pd.cut(s.alt_km, [0, 450, 600, 800, 1300],
                           labels=["<450", "450-600", "600-800", "800-1300"]).astype(str)
    return s


# ── B. MEME 真值 ─────────────────────────────────────────────────────────────
def meme_alt_avg(path: Path, name: str) -> pd.Series | None:
    try:
        _, m = parse_ephemeris_file(path, sat_id=name)
    except Exception:
        return None
    m["t"] = pd.to_datetime(m["t"], utc=True)
    m = m[m.t <= m.t.min() + pd.Timedelta(hours=TRUTH_HOURS + 1)]
    r = np.linalg.norm(m[["r_x", "r_y", "r_z"]].to_numpy(float), axis=1)
    v2 = (m[["v_x", "v_y", "v_z"]].to_numpy(float) ** 2).sum(axis=1)
    a = 1.0 / (2.0 / r - v2 / MU)
    alt = pd.Series(a - R_E, index=m.t.values).rolling(ORBIT_SAMPLES, center=True).mean().dropna()
    alt.index = pd.DatetimeIndex(alt.index).tz_localize("UTC") if alt.index.tz is None else alt.index
    return alt[alt.index <= m.t.min() + pd.Timedelta(hours=TRUTH_HOURS)]


def sat_tles(con, norad: int) -> pd.DataFrame:
    d = con.sql(f"select epoch_utc epoch, sma_km, inclination_deg, eccentricity, raan_deg, bstar, "
                f"try_cast(trim(substr(line1, 34, 10)) as double) ndot from raw_tle_archive "
                f"where norad_id = {norad} order by epoch_utc").df()
    d["epoch"] = pd.to_datetime(d.epoch, utc=True)
    return d.drop_duplicates("epoch").reset_index(drop=True)


def part_b(con, n_files: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    reg = pd.read_csv(ROOT / "data" / "url_registry.csv", usecols=["norad_id", "sat_name"]).drop_duplicates("norad_id")
    reg = reg[(reg.norad_id < 100000) & reg.sat_name.map(lambda s: (RAW / str(s)).is_dir())]
    tle_rows, tr_rows = [], []
    for k, (norad, name) in enumerate(zip(reg.norad_id, reg.sat_name), 1):
        tle = sat_tles(con, int(norad))
        if len(tle) < 10:
            continue
        tr = build_transitions(tle)
        oc = classify_orbit(float(tle.sma_km.median()), float(tle.eccentricity.median()),
                            float(tle.inclination_deg.median()))
        res = apply_strategies(tr, oc)
        ps = res["per_strategy"]
        tr["l1_flag"] = res["combined"]
        tr["p2"], tr["other"] = ps["P2"], ps["other(di/de/dΩ)"]
        tr["p1_sup"], tr["p3_sup"] = ps["P1_suppress"], ps["P3_suppress"]
        tr["detect_raw"] = ps["P2"] | ps["P5"] | ps["P6"] | ps["other(di/de/dΩ)"] | ps["P4"]
        tr["epoch"] = pd.to_datetime(tr.epoch, utc=True)
        tr["epoch_prev"] = tr.epoch - pd.to_timedelta(tr.dt_h, unit="h")
        files = sorted((RAW / name).glob("*.txt"))
        lo, hi = tle.epoch.min(), tle.epoch.max()
        files = [f for f in files if lo <= _file_time(f) <= hi]
        if not files:
            continue
        pick = [files[i] for i in np.unique(np.linspace(0, len(files) - 1, n_files).round().astype(int))]
        for f in pick:
            alt = meme_alt_avg(f, name)
            if alt is None or len(alt) < 200:
                continue
            t0, t1 = alt.index.min(), alt.index.max()
            tsec = (alt.index - t0).total_seconds().to_numpy()
            # B1：epoch 前 12 小時 MEME 平均高度變化率
            sel = tle[(tle.epoch >= t0 + pd.Timedelta(hours=RATE_WINDOW_H)) & (tle.epoch <= t1)]
            for _, r in sel.iterrows():
                w = (alt.index >= r.epoch - pd.Timedelta(hours=RATE_WINDOW_H)) & (alt.index <= r.epoch)
                if w.sum() < 60:
                    continue
                slope = np.polyfit(tsec[w] / 86400.0, alt.values[w], 1)[0]
                tle_rows.append(dict(norad=int(norad), name=name, epoch=r.epoch, alt_km=r.sma_km - R_E,
                                     bstar=r.bstar, ndot=r.ndot, meme_rate_km_d=slope, file=f.stem))
            # B2：轉換兩端皆落在 MEME 可靠段內
            st = tr[(tr.epoch_prev >= t0) & (tr.epoch <= t1)]
            for _, r in st.iterrows():
                a0 = float(np.interp((r.epoch_prev - t0).total_seconds(), tsec, alt.values))
                a1 = float(np.interp((r.epoch - t0).total_seconds(), tsec, alt.values))
                tr_rows.append(dict(norad=int(norad), name=name, epoch=r.epoch, dt_h=r.dt_h, alt_km=r.alt_km,
                                    bstar=r.bstar, da_tle_km=r.da_km, dalt_meme_km=a1 - a0,
                                    l1_flag=bool(r.l1_flag), detect_raw=bool(r.detect_raw),
                                    p2=bool(r.p2), other=bool(r.other),
                                    p1_sup=bool(r.p1_sup), p3_sup=bool(r.p3_sup), file=f.stem))
        if k % 20 == 0:
            print(f"  B. {k}/{len(reg)} 顆，TLE 樣本 {len(tle_rows):,}，轉換樣本 {len(tr_rows):,}")
    return (pd.DataFrame(tle_rows).drop_duplicates(["norad", "epoch"]),
            pd.DataFrame(tr_rows).drop_duplicates(["norad", "epoch"]))


# ── C. L1 於不推進物件 ───────────────────────────────────────────────────────
def part_c(con, pop: pd.DataFrame, n_control: int) -> pd.DataFrame:
    band = pop[(pop.alt_km >= 450) & (pop.alt_km < 600)]
    rows = []
    rng = np.random.default_rng(20261020)
    for grp in ("debris", "other_payload", "Starlink"):
        ids = band[band.group == grp].norad_id.to_numpy()
        ids = rng.choice(ids, size=min(n_control, len(ids)), replace=False)
        for norad in ids:
            tle = sat_tles(con, int(norad))
            tle = tle[tle.epoch >= pd.Timestamp(SINCE, tz="UTC")]
            if len(tle) < 10:
                continue
            tr = build_transitions(tle)
            oc = classify_orbit(float(tle.sma_km.median()), float(tle.eccentricity.median()),
                                float(tle.inclination_deg.median()))
            res = apply_strategies(tr, oc)
            ps = res["per_strategy"]
            rows.append(dict(norad=int(norad), group=grp, n_tr=len(tr), alt_km=float(tr.alt_km.median()),
                             n_flag=int(res["combined"].sum()), n_p2=int(ps["P2"].sum()),
                             n_other=int(ps["other(di/de/dΩ)"].sum()),
                             n_p1_sup=int(ps["P1_suppress"].sum()), n_p3_sup=int(ps["P3_suppress"].sum()),
                             neg_bstar_frac=float((tr.bstar < 0).mean())))
        print(f"  C. {grp}: {sum(r['group'] == grp for r in rows)} 個物件")
    return pd.DataFrame(rows)


# ── D. 範例時序 ──────────────────────────────────────────────────────────────
def part_d(con, pop: pd.DataFrame) -> pd.DataFrame:
    out = []
    picks = [("OneWeb", 1150, 1250), ("debris", 1150, 1250), ("Starlink", 470, 500), ("debris", 470, 500)]
    for grp, lo, hi in picks:
        c = pop[(pop.group == grp) & pop.alt_km.between(lo, hi)].sort_values("n_tle", ascending=False)
        if c.empty:
            continue
        r = c.iloc[0]
        d = con.sql(f"select epoch_utc epoch, bstar from raw_tle_archive where norad_id = {int(r.norad_id)} "
                    f"and epoch_utc >= '{SINCE}' order by epoch_utc").df().drop_duplicates("epoch")
        d["norad"], d["object_name"], d["group"], d["alt_km"] = int(r.norad_id), r.object_name, grp, r.alt_km
        out.append(d)
    return pd.concat(out, ignore_index=True)


def _file_time(f: Path) -> pd.Timestamp:
    return pd.Timestamp(f.stem[:10] + " " + f.stem[11:19].replace("-", ":"), tz="UTC")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-files", type=int, default=20)
    ap.add_argument("--n-control", type=int, default=300)
    ap.add_argument("--parts", default="abcd")
    args = ap.parse_args()
    con = duckdb.connect(str(DB), read_only=True)
    pop = part_a(con)
    pop.to_csv(OUT["population"], index=False, encoding="utf-8-sig")
    print(f"A. {len(pop):,} 個物件 → {OUT['population']}")
    if "d" in args.parts:
        part_d(con, pop).to_csv(OUT["examples"], index=False, encoding="utf-8-sig")
        print(f"D. → {OUT['examples']}")
    if "c" in args.parts:
        part_c(con, pop, args.n_control).to_csv(OUT["l1_control"], index=False, encoding="utf-8-sig")
        print(f"C. → {OUT['l1_control']}")
    if "b" in args.parts:
        tle_truth, trans = part_b(con, args.n_files)
        tle_truth.to_csv(OUT["tle_truth"], index=False, encoding="utf-8-sig")
        trans.to_csv(OUT["transitions"], index=False, encoding="utf-8-sig")
        print(f"B. TLE {len(tle_truth):,}／轉換 {len(trans):,} → {OUT['tle_truth']}、{OUT['transitions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
