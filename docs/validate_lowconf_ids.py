#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_lowconf_ids.py — 以 IDS 營運方點火紀錄與認證安靜期，評估 R7 之 L1 候選事件與 L2 低置信複核項。

非 Starlink 精密定軌衛星（海洋測高等），營運方公開逐次點火與安靜期，可量測誤報：
  - 誤報：L1 候選事件或 L2 項落在營運方認證安靜期內（扣除兩端各 24 小時）；以每千安靜星日計。
  - 偵測：點火（同一 ids 視窗合併為一件）之 ±24 小時內有 L1 候選事件或 L2 項；依 TLE 可見性分層。
  阻力殘差與融合評分器之低置信複核項未納入（需整段 NRLMSIS 計算，另案評估）。

用法：python docs/validate_lowconf_ids.py [out.csv]
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
import maneuver_report_builder as rb  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/benchmark/lowconf_ids_validation.csv"
PAD = pd.Timedelta(hours=24)


def main():
    tru = pd.read_csv("ids_truth_set/ids_truth.csv")
    qui = pd.read_csv("ids_truth_set/ids_quiet.csv")
    for c in ("win_start_tai", "win_end_tai"):
        tru[c] = pd.to_datetime(tru[c], utc=True)
    for c in ("quiet_start_tai", "quiet_end_tai"):
        qui[c] = pd.to_datetime(qui[c], utc=True)
    f107 = rb.load_f107()
    rows = []
    for nid in sorted(qui["norad"].dropna().unique()):
        nid = int(nid)
        q = qui[qui["norad"] == nid]
        t = tru[tru["norad"] == nid]
        df = rb.load_tle(nid).sort_values("epoch", kind="stable").reset_index(drop=True)
        df = df[~((df["epoch"].shift(-1) - df["epoch"]).dt.total_seconds() < 1.0)].reset_index(drop=True)
        l1 = rb.compute_l1(df, f107)
        tr, comb = l1["tr"], np.asarray(l1["combined"], bool)
        l2 = rb.compute_l2(df)
        ev = rb.build_candidate_events(df, tr, comb, l2, None, None, None)
        cap = rb.detection_capability(tr, comb, ev)
        md = cap["min_detect_m"] / 1000 if cap else None
        items = rb._l2_only_items(df, l2, ev, min_net_km=md)
        # 安靜期（兩端各縮 24h，避免點火前後之 TLE 擬合影響）
        qs = [(a + PAD, b - PAD) for a, b in zip(q["quiet_start_tai"], q["quiet_end_tai"]) if b - a > 2 * PAD]
        qdays = sum((b - a).total_seconds() for a, b in qs) / 86400
        inq = lambda t0, t1: any(t0 <= b and a <= t1 for a, b in qs)
        fp_l1 = sum(inq(e["t_start"], e["t_end"]) for e in ev)
        fp_l2 = sum(inq(x["epoch"], x["epoch"]) for x in items)
        # 點火：同一視窗合併
        w = t.groupby(["win_start_tai", "win_end_tai"]).agg(da=("da_km", lambda s: float(np.abs(s).sum())),
                                                          vis=("tle_visible_50", "max")).reset_index()
        det_l1 = det_l2 = 0
        for _, r in w.iterrows():
            a, b = r["win_start_tai"] - PAD, r["win_end_tai"] + PAD
            h1 = any(e["t_start"] <= b and a <= e["t_end"] for e in ev)
            h2 = (not h1) and any(a <= x["epoch"] <= b for x in items)
            det_l1 += h1
            det_l2 += h2
        vis = w[w["vis"] == 1]
        det_l1v = det_l2v = 0
        for _, r in vis.iterrows():
            a, b = r["win_start_tai"] - PAD, r["win_end_tai"] + PAD
            h1 = any(e["t_start"] <= b and a <= e["t_end"] for e in ev)
            det_l1v += h1
            det_l2v += (not h1) and any(a <= x["epoch"] <= b for x in items)
        rows.append({"norad": nid, "name": q["name"].iloc[0], "quiet_days": qdays, "n_l1_ev": len(ev),
                     "n_l2": len(items), "fp_l1": fp_l1, "fp_l2": fp_l2, "burn_win": len(w), "burn_vis": len(vis),
                     "det_l1": det_l1, "det_l2": det_l2, "det_l1_vis": det_l1v, "det_l2_vis": det_l2v,
                     "min_detect_m": cap["min_detect_m"] if cap else np.nan})
        print(rows[-1], flush=True)
    R = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    R.to_csv(OUT, index=False, encoding="utf-8-sig")
    s = R.sum(numeric_only=True)
    qd = s["quiet_days"]
    print(f"\n{len(R)} 顆、安靜期 {qd:.0f} 星日；L1 候選事件落在安靜期 {s['fp_l1']:.0f} 件（每千安靜星日 {s['fp_l1']/qd*1000:.2f}）；"
          f"L2 項落在安靜期 {s['fp_l2']:.0f} 項（每千安靜星日 {s['fp_l2']/qd*1000:.2f}）；L2 項總數 {s['n_l2']:.0f}")
    print(f"點火視窗 {s['burn_win']:.0f}（TLE 可見 {s['burn_vis']:.0f}）：L1 偵測 {s['det_l1']:.0f}，L2 補列 {s['det_l2']:.0f}；"
          f"可見者 L1 {s['det_l1_vis']:.0f}/{s['burn_vis']:.0f}，L2 補列 {s['det_l2_vis']:.0f}")


if __name__ == "__main__":
    main()
