#!/usr/bin/env python3
"""eval_orbit_regime.py — 驗證 orbit_regime（狀態判別＋區段輸出）

三項驗證，真值皆獨立於 TLE 之外或為已逐筆核對之案例：
  A. Starlink V3 26 顆 × MEME 時窗：每份 MEME 只取前 24 小時（升軌期預報超過 24h 會失準），
     以一圈移動平均之平均高度斜率為真值（> +1 km／天＝raising、< −1＝lowering、其餘 maintain），
     與 TLE 推得之當日狀態比對 → 混淆矩陣。
  B. STARLINK-37471（68802）已知升軌：案例研究簡報第三節逐筆核對為 06-14（爬升前）～06-18（完成），
     淨變化 +46.7 km（MEME 真值 +50.3 km），檢查區段起訖與 Δa。
  C. 一般運行中之 Starlink（url_registry 284 顆，NORAD < 100000）近 30 天：統計被判為 raising／lowering
     之星日比例與區段數，作為「運行期誤判」之上限（其中可能含真實的軌道調整，故為上限而非誤報率）。
另輸出 V3 26 顆之升軌區段表，供簡報使用。

輸出：data/benchmark/orbit_regime_{meme_windows,v3_segments,starlink_recent,summary}_<日期>.csv
用法：python eval_orbit_regime.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import orbit_regime as R
from compare_v3_meme_tle import orbit_avg_alt
from starlink_ephemeris.parser import parse_ephemeris_file

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
TAG = date.today().strftime("%Y%m%d")
OUT = {k: ROOT / "data" / "benchmark" / f"orbit_regime_{k}_{TAG}.csv"
       for k in ("meme_windows", "v3_segments", "starlink_recent", "summary")}
V3 = range(100855, 100881)
RECENT_D = 30


def tle_of(con, nid, since=None):
    q = "SELECT epoch_utc AS epoch, object_name, sma_km FROM raw_tle_archive WHERE norad_id=?"
    args = [int(nid)]
    if since is not None:
        q += " AND epoch_utc >= ?"
        args.append(since)
    d = con.execute(q + " ORDER BY epoch_utc", args).fetchdf()
    d["epoch"] = pd.to_datetime(d.epoch, utc=True)
    return d


def label(rate):
    return "raising" if rate > R.RATE_KM_D else ("lowering" if rate < -R.RATE_KM_D else "maintain")


def part_a(con):
    rows, segs = [], []
    for nid in V3:
        tle = tle_of(con, nid)
        name = str(tle.object_name.iloc[0]).replace("0 ", "", 1).strip()
        reg = R.classify_regime(tle).set_index("day")
        sg = R.segments(tle)
        sg.insert(0, "norad", nid); sg.insert(1, "name", name)
        segs.append(sg)
        for f in sorted((ROOT / "data" / "raw" / name).glob("*.txt")):
            _, m = parse_ephemeris_file(f, sat_id=name)
            m["t"] = pd.to_datetime(m["t"], utc=True)
            m["alt"] = orbit_avg_alt(m)
            m = m[m.t <= m.t.min() + pd.Timedelta(hours=24)].dropna(subset=["alt"])
            x = (m.t - m.t.min()).dt.total_seconds().to_numpy() / 86400
            rate = float(np.polyfit(x, m.alt.to_numpy(), 1)[0])
            mid = (m.t.min() + pd.Timedelta(hours=12)).floor("D")
            covered = tle.epoch.max() >= m.t.min() + pd.Timedelta(hours=12)
            pred = reg.regime.get(mid, "unknown") if covered else "no_tle"
            rows.append(dict(norad=nid, name=name, file=f.stem, meme_rate_km_d=round(rate, 3),
                             truth=label(rate), pred=pred))
    return pd.DataFrame(rows), pd.concat(segs, ignore_index=True)


def part_b(con):
    t = tle_of(con, 68802)
    t = t[(t.epoch >= "2026-06-05") & (t.epoch <= "2026-06-30")]
    return R.segments(t)


def part_c(con):
    reg = pd.read_csv(ROOT / "data" / "url_registry.csv", usecols=["norad_id"]).drop_duplicates()
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=RECENT_D)).strftime("%Y-%m-%d")
    rows = []
    for nid in reg.norad_id[reg.norad_id < 100000]:
        t = tle_of(con, nid, since)
        if len(t) < 10:
            continue
        r = R.classify_regime(t)
        r = r[r.regime != "unknown"]
        rows.append(dict(norad=int(nid), n_days=len(r), raising_days=int((r.regime == "raising").sum()),
                         lowering_days=int((r.regime == "lowering").sum()),
                         raising_segs=len(R.segments(t, "raising")), lowering_segs=len(R.segments(t, "lowering"))))
    return pd.DataFrame(rows)


def main():
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    a, v3seg = part_a(con)
    b = part_b(con)
    c = part_c(con)
    con.close()
    a.to_csv(OUT["meme_windows"], index=False, encoding="utf-8-sig")
    v3seg.to_csv(OUT["v3_segments"], index=False, encoding="utf-8-sig")
    c.to_csv(OUT["starlink_recent"], index=False, encoding="utf-8-sig")

    ev = a[a.pred.isin(["raising", "maintain", "lowering"])]
    print("A. V3 × MEME 時窗（前 24 小時）：", len(a), "窗；有 TLE 涵蓋者", len(ev))
    print(pd.crosstab(ev.truth, ev.pred, rownames=["MEME 真值"], colnames=["TLE 狀態"]).to_string())
    acc = float((ev.truth == ev.pred).mean()) if len(ev) else np.nan
    print(f"   一致率 {acc:.3f}")
    print("\nB. STARLINK-37471 已知升軌：")
    print(b.to_string(index=False))
    sd = c.n_days.sum()
    print(f"\nC. 一般 Starlink {len(c)} 顆近 {RECENT_D} 天：raising 星日 {c.raising_days.sum()}／{sd}"
          f"（{c.raising_days.sum() / sd:.3%}），lowering 星日 {c.lowering_days.sum()}（{c.lowering_days.sum() / sd:.3%}）；"
          f"有 raising 區段之衛星 {int((c.raising_segs > 0).sum())} 顆、lowering {int((c.lowering_segs > 0).sum())} 顆")
    print(f"\nV3 升軌區段：{len(v3seg)} 段，每顆 {v3seg.groupby('norad').size().min()}–{v3seg.groupby('norad').size().max()} 段")

    b0 = b.iloc[0] if len(b) else None
    pd.DataFrame([dict(
        meme_windows=len(a), meme_windows_eval=len(ev), meme_agreement=acc,
        meme_raising_truth=int((ev.truth == "raising").sum()),
        meme_raising_hit=int(((ev.truth == "raising") & (ev.pred == "raising")).sum()),
        meme_flat_truth=int((ev.truth != "raising").sum()),
        meme_flat_false_raise=int(((ev.truth != "raising") & (ev.pred == "raising")).sum()),
        s37471_start=None if b0 is None else str(b0.start), s37471_end=None if b0 is None else str(b0.end),
        s37471_delta_km=None if b0 is None else float(b0.delta_km),
        recent_sats=len(c), recent_sat_days=int(sd),
        recent_raising_days=int(c.raising_days.sum()), recent_lowering_days=int(c.lowering_days.sum()),
        recent_sats_raising=int((c.raising_segs > 0).sum()), recent_sats_lowering=int((c.lowering_segs > 0).sum()),
        v3_segments=len(v3seg))]).to_csv(OUT["summary"], index=False, encoding="utf-8-sig")
    print("→", OUT["summary"])


if __name__ == "__main__":
    main()
