#!/usr/bin/env python3
"""eval_applicability.py — 驗證 applicability（融合評分器適用範圍判定）

  A. Starlink V3 26 顆（訓練範圍外）：應全數判為 out_of_domain，且原因須列出
  B. 一般 Starlink（url_registry，NORAD < 100000，即訓練族群）近 30 天：
     被判為 out_of_domain 之比例應很低；逐一列出原因類別（傾角／高度／入軌）以利檢查
  兩者皆另報 regime（狀態層判定為升軌／降軌）比例。

輸出：data/benchmark/applicability_{v3,starlink_recent,summary}_<日期>.csv
用法：python eval_applicability.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from applicability import assess, load_domain

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
TAG = date.today().strftime("%Y%m%d")
OUT = {k: ROOT / "data" / "benchmark" / f"applicability_{k}_{TAG}.csv" for k in ("v3", "starlink_recent", "summary")}
RECENT_D = 30


def run(con, ids, since=None):
    dom = load_domain()
    rows = []
    for nid in ids:
        full = con.execute("SELECT epoch_utc AS epoch, sma_km, inclination_deg FROM raw_tle_archive "
                           "WHERE norad_id=? ORDER BY epoch_utc", [int(nid)]).fetchdf()
        if len(full) < 10:
            continue
        full["epoch"] = pd.to_datetime(full.epoch, utc=True)
        a = assess(full, t_first=full.epoch.min(), domain=dom)
        if since is not None:
            a = a[a.epoch >= since]
        if a.empty:
            continue
        r = a.reasons
        rows.append(dict(norad=int(nid), n=len(a),
                         applicable=int((a.status == "applicable").sum()),
                         out_of_domain=int((a.status == "out_of_domain").sum()),
                         regime=int((a.status == "regime").sum()),
                         why_inc=int(r.str.contains("傾角").sum()), why_alt=int(r.str.contains("高度").sum()),
                         why_age=int(r.str.contains("入軌").sum())))
    return pd.DataFrame(rows)


def main():
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    v3 = run(con, range(100855, 100881))
    reg = pd.read_csv(ROOT / "data" / "url_registry.csv", usecols=["norad_id"]).drop_duplicates()
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=RECENT_D)
    sl = run(con, reg.norad_id[reg.norad_id < 100000], since)
    con.close()
    v3.to_csv(OUT["v3"], index=False, encoding="utf-8-sig")
    sl.to_csv(OUT["starlink_recent"], index=False, encoding="utf-8-sig")

    def frac(df, col):
        return df[col].sum() / df.n.sum()
    ood_sats = sl[sl.out_of_domain > 0]
    summ = dict(v3_sats=len(v3), v3_tle=int(v3.n.sum()), v3_ood_frac=frac(v3, "out_of_domain"),
                v3_why_inc_frac=v3.why_inc.sum() / v3.n.sum(),
                sl_sats=len(sl), sl_tle=int(sl.n.sum()), sl_applicable_frac=frac(sl, "applicable"),
                sl_ood_frac=frac(sl, "out_of_domain"), sl_regime_frac=frac(sl, "regime"),
                sl_ood_sats=len(ood_sats), sl_ood_why_inc=int(sl.why_inc.sum()), sl_ood_why_alt=int(sl.why_alt.sum()),
                sl_ood_why_age=int(sl.why_age.sum()))
    pd.DataFrame([summ]).to_csv(OUT["summary"], index=False, encoding="utf-8-sig")
    print(f"A. V3 {len(v3)} 顆、{v3.n.sum()} 筆：不適用 {summ['v3_ood_frac']:.1%}（原因含傾角 {summ['v3_why_inc_frac']:.1%}）")
    print(f"B. 一般 Starlink {len(sl)} 顆近 {RECENT_D} 天、{sl.n.sum()} 筆：適用 {summ['sl_applicable_frac']:.1%}、"
          f"不適用 {summ['sl_ood_frac']:.2%}（{len(ood_sats)} 顆；原因次數：傾角 {summ['sl_ood_why_inc']}、"
          f"高度 {summ['sl_ood_why_alt']}、入軌 {summ['sl_ood_why_age']}）、狀態層 {summ['sl_regime_frac']:.2%}")
    print("→", OUT["summary"])


if __name__ == "__main__":
    main()
