"""exp_bstar_candidate_source.py — 實驗：B* 偏離作為「候選來源」能補回多少被 Δa 候選漏掉的 MEME 機動？

承 exp_l3_bstar_feature.py（B* 當確認特徵：AUC 提升但召回率不變，因確認模型只能否決候選）。
本實驗改問：把 |B* 偏離| > k 個 MAD（基準＝前 30 天中位數／MAD）的時刻當成新候選，
MEME 機動（train_l3_starlink 之真值事件）的涵蓋率能提高多少、新增候選有多少比例是真機動。
輸出：data/benchmark/exp_bstar_candidate_source_<日期>.csv
用法：python exp_bstar_candidate_source.py
"""
import glob
from datetime import date
import duckdb
import numpy as np
import pandas as pd
import train_l3_starlink as T
from satdet import config

src = sorted(glob.glob("data/benchmark/starlink_candidate_features_*.csv"))[-1]
df = pd.read_csv(src)
df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="mixed")
events = T.sat_events(df)
con = duckdb.connect(config.SPACE_DB, read_only=True)
TOL = pd.Timedelta(days=1.5).value
DAY = pd.Timedelta(days=1).value
rows = []
for nid, g in df.groupby("norad"):
    ev = events.get(int(nid))
    if ev is None or len(ev) == 0:
        continue
    lo, hi = pd.to_datetime(g.t_first.iloc[0], utc=True, format="mixed"), pd.to_datetime(g.t_last.iloc[0], utc=True, format="mixed")
    tle = con.execute("SELECT epoch_utc, bstar FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc", [int(nid)]).fetchdf()
    tle["t"] = pd.to_datetime(tle.epoch_utc, utc=True)
    tle = tle.drop_duplicates("t").dropna(subset=["bstar"]).reset_index(drop=True)
    t = tle.t.dt.as_unit("ns").astype("int64").to_numpy()
    b = tle.bstar.to_numpy()
    z = np.full(len(b), np.nan)
    for i in range(len(b)):
        m = (t >= t[i] - 31 * DAY) & (t < t[i] - DAY)
        if m.sum() >= 5:
            med = np.median(b[m]); mad = max(1.4826 * np.median(np.abs(b[m] - med)), 1e-5)
            z[i] = (b[i] - med) / mad
    cand = g.epoch.dt.as_unit("ns").astype("int64").to_numpy()
    evt = ev.ws.dt.as_unit("ns").astype("int64").to_numpy()
    evt = evt[(evt >= lo.value) & (evt <= hi.value)]
    for k in (3, 5, 8):
        flag = t[np.abs(np.nan_to_num(z)) > k]
        for e in evt:
            covered = len(cand) and np.min(np.abs(cand - e)) <= TOL
            bhit = len(flag) and np.min(np.abs(flag - e)) <= TOL
            rows.append(dict(norad=int(nid), k=k, covered=bool(covered), bhit=bool(bhit)))
        # 額外候選數：B* 旗標合併成 1 天一個事件後，離任何 Δa 候選 >1.5 天者
        if len(flag):
            merged = [flag[0]]
            for f in flag[1:]:
                if f - merged[-1] > DAY:
                    merged.append(f)
            merged = np.array(merged)
            extra = [m for m in merged if not len(cand) or np.min(np.abs(cand - m)) > TOL]
            extra_true = [m for m in extra if len(evt) and np.min(np.abs(evt - m)) <= TOL]
        else:
            extra, extra_true = [], []
        rows.append(dict(norad=int(nid), k=k, n_extra=len(extra), n_extra_true=len(extra_true)))
con.close()
r = pd.DataFrame(rows)
ev_r = r.dropna(subset=["covered"])
ex_r = r.dropna(subset=["n_extra"])
summ = []
for k in (3, 5, 8):
    e = ev_r[ev_r.k == k]; x = ex_r[ex_r.k == k]
    unc = e[~e.covered.astype(bool)]
    print(f"k={k}: MEME 事件 {len(e)}，Δa 候選涵蓋 {e.covered.mean():.3f}；"
          f"未涵蓋者被 B* 旗標命中 {unc.bhit.mean():.3f}（{int(unc.bhit.sum())} 件）；"
          f"聯集涵蓋 {(e.covered.astype(bool) | e.bhit.astype(bool)).mean():.3f}；"
          f"額外候選 {int(x.n_extra.sum())}，其中對到真值 {int(x.n_extra_true.sum())}（{x.n_extra_true.sum() / max(x.n_extra.sum(), 1):.3f}）")
    summ.append(dict(k_mad=k, n_events=len(e), coverage_dA=e.covered.mean(),
                     coverage_union=(e.covered.astype(bool) | e.bhit.astype(bool)).mean(),
                     n_extra=int(x.n_extra.sum()), n_extra_true=int(x.n_extra_true.sum()),
                     extra_precision=x.n_extra_true.sum() / max(x.n_extra.sum(), 1)))
out = f"data/benchmark/exp_bstar_candidate_source_{date.today():%Y%m%d}.csv"
pd.DataFrame(summ).to_csv(out, index=False, encoding="utf-8-sig")
print("→", out)
