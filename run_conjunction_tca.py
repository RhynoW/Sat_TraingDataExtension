#!/usr/bin/env python3
"""
run_conjunction_tca.py — 針對單一 target NORAD 顯示 conjunction Stage A/B/C 結果
==============================================================================
重用 conjunction_pipeline.py 的 Stage A/B/C 函式，對「使用者輸入的 NORAD」計算並
逐事件顯示：
  Stage A  幾何預篩（橢圓軌道 rmin/rmax + Δecc/Δi/ΔRAAN）→ 候選數
  Stage B  粗時間網格 + cKDTree 空間搜尋（SGP4）→ 粗命中數
  Stage C  minimize_scalar 精化 TCA + RTN 相對位置 + pseudo-covariance + Monte-Carlo Pc

與 conjunction_pipeline.run_pipeline 不同：本檔**不寫入** DB（app 的 conjunction_events
為 7 欄舊 schema），純顯示 + 可選 CSV；並額外印出 TCA 時的 RTN 分量與 covariance 假設，
讓「TCA 精化 + covariance + Pc」三步驟完全透明。

用法： python run_conjunction_tca.py --target-norad 25544
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from sgp4.api import Satrec

from conjunction_pipeline import (
    load_stageA_candidates_elliptic,
    load_stageA_candidates,
    to_satrec_map,
    stage_b_kdtree_scan,
    search_best_distance_around_time_minimize,
    eci_to_rtn_basis,
    pseudo_cov_tle_leo,
    compute_pc_simplified,
    risk_label_from_pc,
)


def target_name(db, nid):
    con = duckdb.connect(db, read_only=True)
    row = con.execute("SELECT object_name FROM raw_tle_archive WHERE norad_id=? "
                      "ORDER BY epoch_utc DESC LIMIT 1", [int(nid)]).fetchone()
    con.close()
    return row[0] if row else f"NORAD {nid}"


def target_satrec(db, nid):
    con = duckdb.connect(db, read_only=True)
    row = con.execute("SELECT line1,line2 FROM raw_tle_archive WHERE norad_id=? "
                      "ORDER BY epoch_utc DESC LIMIT 1", [int(nid)]).fetchone()
    con.close()
    if row is None:
        raise ValueError(f"raw_tle_archive 找不到 NORAD {nid}")
    return Satrec.twoline2rv(row[0], row[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--target-norad", type=int, default=25544)
    ap.add_argument("--snapshot-date", default=None)
    # Stage A（橢圓幾何）
    ap.add_argument("--radial-buffer-km", type=float, default=50.0)
    ap.add_argument("--max-delta-ecc", type=float, default=0.3)
    ap.add_argument("--max-delta-inc-deg", type=float, default=5.0)
    ap.add_argument("--max-delta-raan-deg", type=float, default=30.0)
    # Stage B
    ap.add_argument("--hours-before", type=float, default=12.0)
    ap.add_argument("--hours-after", type=float, default=12.0)
    ap.add_argument("--coarse-step-seconds", type=int, default=300)
    ap.add_argument("--coarse-miss-km", type=float, default=50.0)
    # Stage C
    ap.add_argument("--fine-window-minutes", type=float, default=10.0)
    ap.add_argument("--Rc-km", type=float, default=0.01)
    ap.add_argument("--n-mc", type=int, default=20000)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--keep-self", action="store_true",
                    help="保留 miss≈0 且 rel_speed≈0 的同址編目物件（docked/共軌重複；預設濾除）")
    ap.add_argument("--export-csv", default=None)
    args = ap.parse_args()

    nid = args.target_norad
    name = target_name(args.db, nid)
    print(f"{'='*72}")
    print(f"Conjunction 螢幕篩選 — target = {name}（NORAD {nid}）")
    print(f"{'='*72}")

    # ── Stage A ──────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    cand, epoch_center = load_stageA_candidates_elliptic(
        db_path=args.db, target_norad=nid, snapshot_date=args.snapshot_date,
        radial_buffer_km=args.radial_buffer_km, max_delta_ecc=args.max_delta_ecc,
        max_delta_inc_deg=args.max_delta_inc_deg, max_delta_raan_deg=args.max_delta_raan_deg)
    tA = time.perf_counter() - t0
    print(f"\n[Stage A] 幾何預篩（snapshot={epoch_center.date()}，"
          f"radial±{args.radial_buffer_km:.0f}km, |Δe|≤{args.max_delta_ecc}, "
          f"|Δi|≤{args.max_delta_inc_deg}°, |ΔΩ|≤{args.max_delta_raan_deg}°）")
    print(f"          候選物件 = {len(cand)} 顆　（{tA:.1f}s）")
    if cand.empty:
        print("Stage A 無候選，結束。"); return

    # ── Stage B ──────────────────────────────────────────────────────────────
    tgt = target_satrec(args.db, nid)
    sec_map = to_satrec_map(cand)
    t0 = time.perf_counter()
    hits = stage_b_kdtree_scan(
        target_sat=tgt, secondary_map=sec_map, center_time=epoch_center,
        hours_before=args.hours_before, hours_after=args.hours_after,
        step_seconds=args.coarse_step_seconds, miss_threshold_km=args.coarse_miss_km)
    tB = time.perf_counter() - t0
    print(f"\n[Stage B] 粗時間網格 ±({args.hours_before:.0f}/{args.hours_after:.0f})h "
          f"@ {args.coarse_step_seconds}s + cKDTree（門檻 {args.coarse_miss_km:.0f}km）")
    print(f"          粗命中 = {len(hits)} 顆　（{tB:.1f}s）")
    if hits.empty:
        print("Stage B 無粗命中，結束。"); return

    # ── Stage C ──────────────────────────────────────────────────────────────
    nm = pd.read_sql if False else None
    id2name = dict(zip(cand["norad_id"].astype(int), cand["object_name"].astype(str)))
    span = int(args.fine_window_minutes * 60)
    C1 = pseudo_cov_tle_leo(); C2 = pseudo_cov_tle_leo()
    rows = []
    t0 = time.perf_counter()
    for r in hits.itertuples(index=False):
        sec_id = int(r.secondary_norad)
        sec = sec_map.get(sec_id)
        if sec is None:
            continue
        tca, d, r1, v1, r2, v2 = search_best_distance_around_time_minimize(
            target_sat=tgt, secondary_sat=sec, center_time=r.t_utc, span_seconds=span)
        if tca is None:
            continue
        B = eci_to_rtn_basis(r1, v1)
        r_rtn = B @ (r2 - r1)
        pc = compute_pc_simplified(r_rtn, C1, C2, Rc_km=args.Rc_km, n_mc=args.n_mc)
        rows.append({
            "secondary_norad": sec_id,
            "secondary_name": id2name.get(sec_id, ""),
            "tca_utc": pd.Timestamp(tca).tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S"),
            "miss_km": round(d, 4),
            "R_km": round(float(r_rtn[0]), 3),
            "T_km": round(float(r_rtn[1]), 3),
            "N_km": round(float(r_rtn[2]), 3),
            "rel_speed_km_s": round(float(np.linalg.norm(v2 - v1)), 3),
            "pc": pc,
            "risk_label": risk_label_from_pc(pc),
        })
    tC = time.perf_counter() - t0
    if not rows:
        print("Stage C 無有效 TCA，結束。"); return
    out = pd.DataFrame(rows).sort_values(["miss_km"]).reset_index(drop=True)

    # 濾除同址編目物件（docked / 共軌重複 TLE）：miss≈0 且 rel_speed≈0 → 同一物體
    n_self = 0
    if not args.keep_self:
        self_mask = (out["miss_km"] < 0.05) & (out["rel_speed_km_s"] < 0.1)
        n_self = int(self_mask.sum())
        out = out[~self_mask].reset_index(drop=True)

    print(f"\n[Stage C] minimize_scalar 精化 TCA + RTN + pseudo-cov + Monte-Carlo Pc")
    print(f"          covariance: σR=1.0 σT=5.0 σN=3.0 km（DEFAULT/RTN）  "
          f"Rc={args.Rc_km*1000:.0f}m  n_mc={args.n_mc}  （{tC:.1f}s）")
    print(f"          有效事件 = {len(out)} 筆" +
          (f"（已濾除 {n_self} 個同址編目物件 docked/共軌）" if n_self else "") + "\n")
    if out.empty:
        print("濾除同址物件後無真實合相事件。"); return

    risk_rank = {"HIGH": 0, "ELEVATED": 1, "MEDIUM": 2, "LOW": 3}
    show = out.copy()
    show["pc"] = show["pc"].apply(lambda x: f"{x:.2e}")
    cols = ["secondary_norad", "secondary_name", "tca_utc", "miss_km",
            "R_km", "T_km", "N_km", "rel_speed_km_s", "pc", "risk_label"]
    print(show[cols].head(args.top).to_string(index=False))

    # 風險摘要
    print(f"\n[風險摘要] " + "　".join(
        f"{k}={int((out['risk_label']==k).sum())}"
        for k in ["HIGH", "ELEVATED", "MEDIUM", "LOW"]))
    top = out.iloc[0]
    print(f"[最接近] secondary {int(top['secondary_norad'])} {top['secondary_name']}  "
          f"miss={top['miss_km']:.3f} km  rel_speed={top['rel_speed_km_s']:.2f} km/s  "
          f"Pc={top['pc']:.2e} → {top['risk_label']}")

    if args.export_csv:
        out.to_csv(args.export_csv, index=False, encoding="utf-8-sig")
        print(f"\nCSV → {args.export_csv}")


if __name__ == "__main__":
    main()
