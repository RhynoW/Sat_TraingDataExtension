#!/usr/bin/env python3
"""
run_1000sat_compare.py — 隨機 1000 顆酬載衛星的機動偵測「三方法比較」。

三方法（皆對同一顆衛星、同一近期觀測窗）：
  A. 統計層  statistical_detectors.run_all(sma)  → CUSUM / BOCPD / SSA / 3σ-MAD 事件數
  B. Model 1 監督式 LightGBM（models_plan_b）    → p_maneuver（54 天窗聚合特徵）
  C. Model 2 + NRLMSIS  atmospheric_drag.drag_residual → 大氣阻力殘差旗標

抽樣：raw_tle_archive 中 PAYLOAD（排除 DEB/R/B/ROCKET/DEBRIS），
      n_tle>=30 且跨度>=30d，seed=42 抽 1000 顆。

用法：
  PYTHONUTF8=1 python docs/run_1000sat_compare.py --limit 40      # pilot
  PYTHONUTF8=1 python docs/run_1000sat_compare.py --limit 1000    # full
"""
from __future__ import annotations
import argparse, json, sys, time, warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import duckdb
import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import statistical_detectors as sd
from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay
from build_training_dataset import extract_features_plan_b

R_E = 6378.137
DB = "space_db.duckdb"
LOOKBACK_DAYS = 90        # 統計層 + drag 的共同觀測窗（每顆取其資料最後 N 天）
M1_WINDOW_DAYS = 54       # Model 1（Plan B）原生聚合窗
DRAG_RESID_THR = 0.5      # |drag_resid_da| > 0.5 km 視為阻力殘差旗標（同 atmospheric_drag 自測）
MODEL_PKL = "Orbital_Maneuver_V2/models_plan_b/lgbm_maneuver_v1.pkl"
FEAT_JSON = "Orbital_Maneuver_V2/models_plan_b/feature_names.json"
THR_JSON = "Orbital_Maneuver_V2/models_plan_b/threshold.json"


def build_sample(con, n=1000, seed=42) -> pd.DataFrame:
    q = """
    WITH agg AS (
      SELECT r.norad_id, COUNT(*) n_tle, MIN(epoch_utc) t0, MAX(epoch_utc) t1,
             MAX(object_name) obj
      FROM raw_tle_archive r GROUP BY r.norad_id
    ),
    named AS (
      SELECT a.norad_id, a.n_tle, a.t0, a.t1,
             COALESCE(a.obj, m.name_en) nm
      FROM agg a LEFT JOIN sat_n2yo_metadata m USING(norad_id)
      WHERE a.n_tle>=30 AND date_diff('day',a.t0,a.t1)>=30
        AND COALESCE(a.obj, m.name_en) IS NOT NULL
    )
    SELECT norad_id, n_tle, t0, t1, nm FROM named
    WHERE UPPER(nm) NOT LIKE '%DEB%' AND UPPER(nm) NOT LIKE '%R/B%'
      AND UPPER(nm) NOT LIKE '%ROCKET%' AND UPPER(nm) NOT LIKE '%DEBRIS%'
    ORDER BY norad_id
    """
    pool = con.execute(q).fetchdf()
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
    samp = pool.iloc[np.sort(idx)].reset_index(drop=True)
    return samp


def load_f107_map():
    f = pd.read_csv("f107_cache.csv")
    f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
    return f.groupby("epoch")["f107"].median().to_dict()


def daily_downsample(df):
    """每日保留最後一筆 TLE。"""
    d = df.copy()
    d["day"] = d["epoch"].dt.strftime("%Y-%m-%d")
    d = d.drop_duplicates("day", keep="last").drop(columns="day").reset_index(drop=True)
    return d


def regime(alt_km):
    if alt_km < 2000:
        return "LEO"
    if alt_km < 35000:
        return "MEO"
    return "GEO"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="docs/compare_1000sat_results.csv")
    args = ap.parse_args()

    model = joblib.load(MODEL_PKL)
    feat_cols = json.load(open(FEAT_JSON, encoding="utf-8"))
    thr = json.load(open(THR_JSON, encoding="utf-8"))["threshold"]
    sw = load_space_weather()
    f107_map = load_f107_map()

    con = duckdb.connect(DB, read_only=True)
    samp = build_sample(con, n=args.limit, seed=args.seed)
    print(f"酬載池抽樣：{len(samp)} 顆（seed={args.seed}，目標 {args.limit}）", flush=True)

    rows = []
    t_start = time.time()
    for k, r in samp.iterrows():
        nid = int(r["norad_id"])
        rec = {"norad_id": nid, "object_name": r["nm"], "n_tle_total": int(r["n_tle"])}
        try:
            df = con.execute(
                "SELECT epoch_utc AS epoch, sma_km, eccentricity, inclination_deg, "
                "raan_deg, bstar FROM raw_tle_archive WHERE norad_id=? "
                "AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchdf()
            df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
            df = df.drop_duplicates("epoch").reset_index(drop=True)
            tmax = df["epoch"].max()

            # ── 共同觀測窗（最近 LOOKBACK_DAYS 天，日採樣）────────────────────
            win = df[df["epoch"] >= tmax - pd.Timedelta(days=LOOKBACK_DAYS)].copy()
            wd = daily_downsample(win)
            sma = wd["sma_km"].to_numpy(float)
            med_alt = float(np.median(sma)) - R_E
            rec["regime"] = regime(med_alt)
            rec["alt_km"] = round(med_alt, 1)
            rec["n_win"] = len(wd)

            # ── A. 統計層 ─────────────────────────────────────────────────────
            if len(sma) >= 8:
                res = sd.run_all(sma)
                cu = len(res["cusum"]["events"]); bo = len(res["bocpd"]["events"])
                ss = len(res["ssa"]["events"]);   md = len(res["mad3sig"]["events"])
                rec.update(stat_cusum_n=cu, stat_bocpd_n=bo, stat_ssa_n=ss, stat_mad_n=md)
                rec["stat_named_n"] = cu + bo + ss
                rec["stat_flag"] = int((cu + bo + ss) > 0)
            else:
                rec.update(stat_cusum_n=np.nan, stat_bocpd_n=np.nan, stat_ssa_n=np.nan,
                           stat_mad_n=np.nan, stat_named_n=np.nan, stat_flag=np.nan)

            # ── B. Model 1（Plan B LightGBM）──────────────────────────────────
            m1win = df[df["epoch"] >= tmax - pd.Timedelta(days=M1_WINDOW_DAYS)].copy()
            m1win = m1win.rename(columns={"epoch": "date_tag"})
            m1win["date_tag"] = m1win["date_tag"].dt.tz_localize(None)
            days = pd.date_range(m1win["date_tag"].min(), m1win["date_tag"].max(), freq="D")
            fvals = [f107_map.get(d.strftime("%Y-%m-%d"), np.nan) for d in days]
            fvals = [v for v in fvals if not np.isnan(v)]
            f107_mean = float(np.mean(fvals)) if fvals else np.nan
            feats = extract_features_plan_b(m1win, f107_mean=f107_mean)
            if feats is not None:
                X = pd.DataFrame([feats]).reindex(columns=feat_cols)
                p = float(model.predict_proba(X)[:, 1][0])
                rec["m1_p"] = round(p, 5)
                rec["m1_flag"] = int(p >= thr)
            else:
                rec["m1_p"] = np.nan; rec["m1_flag"] = np.nan

            # ── C. Model 2 + NRLMSIS（drag 殘差）──────────────────────────────
            dr = drag_residual(wd.rename(columns={"sma_km": "sma_km"}), sw)
            if not dr.empty:
                reentry = is_reentry_decay(wd)
                absr = dr["drag_resid_da"].abs()
                n_hit = int((absr > DRAG_RESID_THR).sum())
                rec["m2_resid_max"] = round(float(absr.max()), 4)
                rec["m2_n"] = n_hit
                rec["m2_reentry"] = int(reentry)
                rec["m2_flag"] = int((not reentry) and n_hit > 0)
            else:
                rec.update(m2_resid_max=np.nan, m2_n=np.nan, m2_reentry=np.nan, m2_flag=np.nan)

        except Exception as ex:
            rec["error"] = str(ex)[:120]
        rows.append(rec)
        if (k + 1) % 20 == 0:
            el = time.time() - t_start
            print(f"  ...{k+1}/{len(samp)}  ({el:.1f}s, {el/(k+1):.2f}s/sat)", flush=True)
    con.close()

    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")
    el = time.time() - t_start
    print(f"\n完成 {len(out)} 顆，用時 {el:.1f}s（{el/len(out):.2f}s/sat）→ {args.out}")

    # 簡摘要
    def rate(c):
        v = out[c].dropna()
        return f"{int(v.sum())}/{len(v)} ({100*v.mean():.1f}%)" if len(v) else "NA"
    print("方法旗標率：")
    print("  統計層 stat_flag :", rate("stat_flag"))
    print("  Model 1 m1_flag  :", rate("m1_flag"))
    print("  Model 2 m2_flag  :", rate("m2_flag"))


if __name__ == "__main__":
    main()
