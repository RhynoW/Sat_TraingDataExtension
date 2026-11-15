#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_lowconf_full.py — 以真值評估 R7 全部低置信複核項（阻力殘差、融合評分器、L2 統計變點）。

與 validate_l2_lowconf_meme.py／validate_lowconf_ids.py 不同，本程式以完整 R7 流程
（build_report_data，含 NRLMSIS 阻力殘差與融合評分器）產生候選事件與低置信複核項。

  meme：隨機抽樣 Starlink（固定種子），限 MEME 覆蓋期間；評估各來源複核項補回 L1 未涵蓋真值事件之件數。
        Starlink 機動頻繁，隨機命中基準極高，精確度不具鑑別力，只報補漏與負擔。
  ids ：IDS 精密定軌衛星，限 IDS_START 之後（太空天氣資料起日）；營運方認證安靜期（兩端各縮 24h）
        內之複核項計為誤報，以每千安靜星日表示；點火視窗 ±24h 內有複核項且 L1 未涵蓋者計為補列。

用法：python docs/validate_lowconf_full.py meme [n_sats] | ids
輸出：data/benchmark/lowconf_full_<mode>.csv、..._items.csv
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
os.environ.setdefault("SSA_RAG_TIMEOUT_S", "1")
import maneuver_report_builder as rb  # noqa: E402

PAD = pd.Timedelta(hours=24)
IDS_START = pd.Timestamp("2021-02-01", tz="UTC")
SEV = {"small": 1, "medium": 2, "large": 3}
SRC = lambda x: ("L2" if x["source"].startswith("L2") else "融合" if "融合" in x["source"] else "阻力")


def run(nid, d0, d1):
    r = rb.build_report_data(int(nid), d0.date(), d1.date())
    return r.get("events") or [], r.get("low_conf") or []


def meme(n_sats):
    tr_all = pd.read_csv(ROOT / "data/meme_truth/transitions_full_20260918.csv", parse_dates=["t_from", "t_to"])
    ids = sorted(tr_all["norad_id"].unique())
    rng = np.random.default_rng(20261115)
    pick = sorted(rng.choice(ids, size=min(n_sats, len(ids)), replace=False))
    rows, items_all = [], []
    for k, nid in enumerate(pick, 1):
        g = tr_all[tr_all["norad_id"] == nid]
        w0, w1 = g["t_from"].min(), g["t_to"].max()
        eps = []
        for _, x in g[g["label_meme"] == 1].sort_values("t_from").iterrows():
            if eps and x["t_from"] - eps[-1]["t1"] <= pd.Timedelta(hours=48):
                eps[-1]["t1"] = max(eps[-1]["t1"], x["t_to"]); eps[-1]["sev"] = max(eps[-1]["sev"], SEV.get(x["da_severity"], 0))
            else:
                eps.append({"t0": x["t_from"], "t1": x["t_to"], "sev": SEV.get(x["da_severity"], 0)})
        try:
            ev, lc = run(nid, w0, w1)
        except Exception as e:  # noqa: BLE001
            print("skip", nid, e, flush=True)
            continue
        days = (w1 - w0).total_seconds() / 86400
        row = {"norad": int(nid), "days": days, "n_ep": len(eps), "n_ev": len(ev), "n_lc": len(lc),
               "n_case": len({x.get("case") for x in lc})}
        for e in eps:
            e["l1"] = any(x["t_start"] - PAD <= e["t1"] and e["t0"] <= x["t_end"] + PAD for x in ev)
        row["ep_l1"] = sum(e["l1"] for e in eps)
        for s in ("阻力", "融合", "L2"):
            its = [x for x in lc if SRC(x) == s]
            row[f"n_{s}"] = len(its)
            row[f"rec_{s}"] = sum((not e["l1"]) and any(e["t0"] - PAD <= x["epoch"] <= e["t1"] + PAD for x in its) for e in eps)
        row["rec_any"] = sum((not e["l1"]) and any(e["t0"] - PAD <= x["epoch"] <= e["t1"] + PAD for x in lc) for e in eps)
        rows.append(row)
        for x in lc:
            items_all.append({"norad": int(nid), "epoch": x["epoch"], "source": SRC(x), "priority": x["priority"],
                              "case": x.get("case"), "tags": "|".join(x.get("tags") or []),
                              "near_truth": any(e["t0"] - PAD <= x["epoch"] <= e["t1"] + PAD for e in eps)})
        print(k, row, flush=True)
    return pd.DataFrame(rows), pd.DataFrame(items_all)


def ids():
    tru = pd.read_csv("ids_truth_set/ids_truth.csv")
    qui = pd.read_csv("ids_truth_set/ids_quiet.csv")
    for c in ("win_start_tai", "win_end_tai"):
        tru[c] = pd.to_datetime(tru[c], utc=True)
    for c in ("quiet_start_tai", "quiet_end_tai"):
        qui[c] = pd.to_datetime(qui[c], utc=True)
    qui = qui[qui["quiet_end_tai"] >= IDS_START]
    tru = tru[tru["win_end_tai"] >= IDS_START]
    rows, items_all = [], []
    for nid in sorted(qui["norad"].dropna().unique()):
        q, t = qui[qui["norad"] == nid], tru[tru["norad"] == nid]
        d0 = max(IDS_START, min(q["quiet_start_tai"].min(), t["win_start_tai"].min() if len(t) else q["quiet_start_tai"].min()))
        d1 = max(q["quiet_end_tai"].max(), t["win_end_tai"].max() if len(t) else q["quiet_end_tai"].max())
        try:
            ev, lc = run(nid, d0, d1)
        except Exception as e:  # noqa: BLE001
            print("skip", nid, e, flush=True)
            continue
        qs = [(max(a, IDS_START) + PAD, b - PAD) for a, b in zip(q["quiet_start_tai"], q["quiet_end_tai"])
              if b - max(a, IDS_START) > 2 * PAD]
        qdays = sum((b - a).total_seconds() for a, b in qs) / 86400
        inq = lambda ts: any(a <= ts <= b for a, b in qs)
        w = t.groupby(["win_start_tai", "win_end_tai"]).agg(vis=("tle_visible_50", "max")).reset_index()
        row = {"norad": int(nid), "name": q["name"].iloc[0], "d0": str(d0.date()), "d1": str(d1.date()),
               "quiet_days": qdays, "n_ev": len(ev), "n_lc": len(lc), "n_case": len({x.get("case") for x in lc}),
               "fp_l1": sum(any(a <= e["t_end"] and e["t_start"] <= b for a, b in qs) for e in ev),
               "burn_win": len(w), "burn_vis": int((w["vis"] == 1).sum())}
        l1hit = [any(e["t_start"] <= r["win_end_tai"] + PAD and r["win_start_tai"] - PAD <= e["t_end"] for e in ev)
                 for _, r in w.iterrows()]
        row["det_l1"] = sum(l1hit)
        row["det_l1_vis"] = sum(h for h, (_, r) in zip(l1hit, w.iterrows()) if r["vis"] == 1)
        for s in ("阻力", "融合", "L2"):
            its = [x for x in lc if SRC(x) == s]
            row[f"n_{s}"] = len(its)
            row[f"fp_{s}"] = sum(inq(x["epoch"]) for x in its)
            row[f"fpP1_{s}"] = sum(inq(x["epoch"]) and x["priority"] == "P1" for x in its)
            row[f"rec_{s}"] = sum((not h) and any(r["win_start_tai"] - PAD <= x["epoch"] <= r["win_end_tai"] + PAD for x in its)
                                  for h, (_, r) in zip(l1hit, w.iterrows()))
        rows.append(row)
        for x in lc:
            items_all.append({"norad": int(nid), "epoch": x["epoch"], "source": SRC(x), "priority": x["priority"],
                              "case": x.get("case"), "tags": "|".join(x.get("tags") or []), "in_quiet": inq(x["epoch"])})
        print(row, flush=True)
    return pd.DataFrame(rows), pd.DataFrame(items_all)


def main():
    mode = sys.argv[1]
    R, I = meme(int(sys.argv[2]) if len(sys.argv) > 2 else 40) if mode == "meme" else ids()
    out = ROOT / f"data/benchmark/lowconf_full_{mode}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    R.to_csv(out, index=False, encoding="utf-8-sig")
    I.to_csv(out.with_name(out.stem + "_items.csv"), index=False, encoding="utf-8-sig")
    s = R.sum(numeric_only=True)
    if mode == "meme":
        miss = s["n_ep"] - s["ep_l1"]
        print(f"\n{len(R)} 顆、{s['days']:.0f} 星日；真值事件 {s['n_ep']:.0f}，L1 涵蓋 {s['ep_l1']:.0f}，未涵蓋 {miss:.0f}")
        for k in ("阻力", "融合", "L2"):
            print(f"  {k}：{s['n_'+k]:.0f} 項（每千星日 {s['n_'+k]/s['days']*1000:.1f}），補回 {s['rec_'+k]:.0f}")
        print(f"  任一來源補回 {s['rec_any']:.0f}／{miss:.0f}；複核項 {s['n_lc']:.0f} 項、{s['n_case']:.0f} 案件")
        if len(I):
            print("  複核項落在真值事件 ±24h 內比例：", round(I['near_truth'].mean(), 3))
    else:
        qd = s["quiet_days"]
        print(f"\n{len(R)} 顆、安靜期 {qd:.0f} 星日；L1 事件落在安靜期 {s['fp_l1']:.0f}（每千 {s['fp_l1']/qd*1000:.2f}）")
        for k in ("阻力", "融合", "L2"):
            print(f"  {k}：{s['n_'+k]:.0f} 項；安靜期內 {s['fp_'+k]:.0f}（每千安靜星日 {s['fp_'+k]/qd*1000:.2f}，其中 P1 {s['fpP1_'+k]:.0f}）；補列 {s['rec_'+k]:.0f}")
        print(f"  點火視窗 {s['burn_win']:.0f}（可見 {s['burn_vis']:.0f}）；L1 偵測 {s['det_l1']:.0f}（可見 {s['det_l1_vis']:.0f}）")


if __name__ == "__main__":
    main()
