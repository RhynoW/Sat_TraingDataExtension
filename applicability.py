#!/usr/bin/env python3
"""applicability.py — 融合評分器之「適用範圍」判定（案例研究簡報 p.115 步驟 4 之初版實作）

問題：融合評分器（models_fusion/fusion_scorer.pkl）以 283 顆 Starlink 之 MEME 真值訓練；遇到訓練範圍以外的
情境（如 Starlink V3：30.5° 傾角、350 km 以下、剛入軌、持續升軌），它仍會輸出一個機率——通常偏低——
看起來像「沒有機動」，卻不會說「我不適用」。本模組在輸出機率之前先判定適用與否：

  applicable        落在訓練範圍內 → 照常輸出機率
  out_of_domain     落在訓練範圍外 → 機率改為 NaN，並列出原因（傾角／高度／入軌天數）
  regime            狀態層判定為升軌或降軌（orbit_regime）→ 改由區段輸出，融合評分器只用在維持期

適用範圍由訓練族群實測（build_domain()，存於 models_fusion/fusion_domain.json）：
  傾角族群   訓練星之傾角分群，各族群 [min − INC_TOL_DEG, max + INC_TOL_DEG]
  高度範圍   訓練期平均高度之 0.5／99.5 百分位，外擴 ALT_MARGIN_KM
  入軌天數   訓練星於真值起點時之最小入軌天數（訓練中有入軌僅約 5 天者，故此門檻效力有限）

用法：
  python applicability.py              # 由訓練族群重建 fusion_domain.json
  from applicability import assess, fusion_with_applicability
"""
from __future__ import annotations

import glob
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DOMAIN_JSON = ROOT / "models_fusion" / "fusion_domain.json"
R_E = 6378.137
INC_TOL_DEG = 0.5
ALT_MARGIN_KM = 10.0
INC_CLUSTER_GAP_DEG = 2.0


def build_domain(db: str | None = None) -> dict:
    """由融合評分器之訓練族群（MEME 真值涵蓋之 Starlink）實測適用範圍。"""
    import duckdb
    truth = pd.read_csv(sorted(glob.glob(str(ROOT / "data" / "meme_truth" / "transitions_full_*.csv")))[-1],
                        usecols=["norad_id", "t_from", "i_deg", "alt_km"])
    inc = np.sort(truth.groupby("norad_id").i_deg.median().to_numpy())
    fams, cur = [], [inc[0]]
    for x in inc[1:]:
        if x - cur[-1] > INC_CLUSTER_GAP_DEG:
            fams.append(cur); cur = []
        cur.append(x)
    fams.append(cur)
    con = duckdb.connect(db or str(ROOT / "space_db.duckdb"), read_only=True)
    ids = ",".join(str(int(n)) for n in truth.norad_id.unique())
    first = con.sql(f"SELECT norad_id, min(epoch_utc) AS t_first FROM raw_tle_archive "
                    f"WHERE norad_id IN ({ids}) GROUP BY 1").df().set_index("norad_id")
    con.close()
    start = pd.to_datetime(truth.groupby("norad_id").t_from.min(), utc=True)
    age = (start - pd.to_datetime(first.t_first, utc=True).reindex(start.index)).dt.total_seconds() / 86400
    dom = {
        "source": "MEME 真值涵蓋之 Starlink（data/meme_truth/transitions_full_*），fusion_scorer 之訓練族群",
        "built_on": date.today().isoformat(),
        "n_sats": int(truth.norad_id.nunique()),
        "inc_families_deg": [[round(min(f) - INC_TOL_DEG, 2), round(max(f) + INC_TOL_DEG, 2), len(f)] for f in fams],
        "alt_range_km": [round(float(truth.alt_km.quantile(0.005)) - ALT_MARGIN_KM, 1),
                         round(float(truth.alt_km.quantile(0.995)) + ALT_MARGIN_KM, 1)],
        "min_age_days": round(float(np.floor(age.min())), 1),
    }
    return dom


def load_domain() -> dict:
    with open(DOMAIN_JSON, encoding="utf-8") as f:
        return json.load(f)


def assess(tle: pd.DataFrame, t_first=None, domain: dict | None = None, use_regime: bool = True) -> pd.DataFrame:
    """逐筆判定適用與否。tle 需含 epoch、sma_km、inclination_deg；t_first＝該星首筆 TLE 時刻（缺則取 tle 最早）。

    回傳 DataFrame(epoch, status, reasons)；reasons 為中文原因字串（以「；」分隔），適用時為空字串。
    """
    dom = domain or load_domain()
    d = tle[["epoch", "sma_km", "inclination_deg"]].copy()
    d["epoch"] = pd.to_datetime(d["epoch"], utc=True)
    t0 = pd.Timestamp(t_first) if t_first is not None else d.epoch.min()
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0
    alt = d.sma_km.to_numpy(float) - R_E
    inc = d.inclination_deg.to_numpy(float)
    age = (d.epoch - t0).dt.total_seconds().to_numpy() / 86400
    fams = dom["inc_families_deg"]
    lo, hi = dom["alt_range_km"]
    in_fam = np.zeros(len(d), bool)
    for f_lo, f_hi, _ in fams:
        in_fam |= (inc >= f_lo) & (inc <= f_hi)
    fam_txt = "／".join(f"{(a + b) / 2:.0f}°" for a, b, _ in fams)
    reasons = [[] for _ in range(len(d))]
    for i in range(len(d)):
        if not in_fam[i]:
            reasons[i].append(f"傾角 {inc[i]:.1f}° 不屬於訓練族群（{fam_txt}）")
        if alt[i] < lo or alt[i] > hi:
            reasons[i].append(f"高度 {alt[i]:.0f} km 超出訓練範圍 {lo:.0f}–{hi:.0f} km")
        if age[i] < dom["min_age_days"]:
            reasons[i].append(f"入軌 {age[i]:.1f} 天，少於訓練最小值 {dom['min_age_days']:.0f} 天")
    status = np.where([bool(r) for r in reasons], "out_of_domain", "applicable").astype(object)
    if use_regime:
        import orbit_regime as R
        reg = R.classify_regime(tle).set_index("day").regime
        day = d.epoch.dt.floor("D")
        rg = day.map(reg).fillna("unknown").to_numpy()
        for i in range(len(d)):
            if rg[i] in ("raising", "lowering"):
                tag = "升軌" if rg[i] == "raising" else "降軌"
                reasons[i].append(f"狀態層判定為{tag}期，改由區段輸出")
                if status[i] == "applicable":
                    status[i] = "regime"
    return pd.DataFrame({"epoch": d.epoch, "status": status, "reasons": ["；".join(r) for r in reasons]})


def fusion_with_applicability(norad: int, d0, d1) -> pd.DataFrame | None:
    """融合評分器＋適用範圍：回傳 df[epoch, fusion_raw, fusion, status, reasons]，不適用時 fusion 為 NaN。"""
    import maneuver_report_builder as rb
    fus = rb.compute_fusion_detection(norad, d0, d1)
    if fus is None:
        return None
    full = rb.load_tle(norad)
    a = assess(full, t_first=full.epoch.min())
    out = fus.rename(columns={"fusion": "fusion_raw"}).merge(a, on="epoch", how="left")
    out["status"] = out["status"].fillna("applicable")
    out["reasons"] = out["reasons"].fillna("")
    out["fusion"] = np.where(out.status == "applicable", out.fusion_raw, np.nan)
    out.attrs["thr"] = fus.attrs.get("thr")
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dom = build_domain()
    DOMAIN_JSON.parent.mkdir(exist_ok=True)
    with open(DOMAIN_JSON, "w", encoding="utf-8") as f:
        json.dump(dom, f, ensure_ascii=False, indent=2)
    print(json.dumps(dom, ensure_ascii=False, indent=2))
    print("→", DOMAIN_JSON)
