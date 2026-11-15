#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_l2_lowconf_meme.py — 以 MEME 精密星曆真值評估 R7「L2 統計變點」低置信複核項。

做法（逐顆 Starlink，限 MEME 覆蓋期間）：
  1. 真值事件：transitions_full 中 label_meme==1 之轉換，相隔 ≤48 小時合併為一件，取最大嚴重度。
  2. 以 R7 同一程式產生 L1 候選事件與 L2 低置信複核項（只需 TLE；不需阻力、ML）。
  3. 真值事件若與 L1 候選事件（起訖 ±24h）重疊，記為「L1 已偵測」；否則若與 L2 項（±24h）重疊，記為「L2 補列」。
  4. L2 項若在任一真值事件 ±24h 內為「命中」，否則為「未對應真值」；並以每千星日計。
  5. 機率基準：隨機時點落在任一真值事件 ±24h 內之比例（Starlink 機動頻繁，命中率須與此比較）。

用法：python docs/validate_l2_lowconf_meme.py [truth.csv] [out.csv]
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

TRUTH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/meme_truth/transitions_full_20260918.csv"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/benchmark/l2_lowconf_meme_validation.csv"
PAD = pd.Timedelta(hours=24)
SEV = {"small": 1, "medium": 2, "large": 3}


def episodes(t: pd.DataFrame) -> list[dict]:
    t = t.sort_values("t_from")
    out, cur = [], None
    for _, r in t.iterrows():
        if cur and r["t_from"] - cur["t1"] <= pd.Timedelta(hours=48):
            cur["t1"] = max(cur["t1"], r["t_to"])
            cur["sev"] = max(cur["sev"], SEV.get(r["da_severity"], 0))
        else:
            cur = {"t0": r["t_from"], "t1": r["t_to"], "sev": SEV.get(r["da_severity"], 0)}
            out.append(cur)
    return out


def near(t, eps) -> bool:
    return any(e["t0"] - PAD <= t <= e["t1"] + PAD for e in eps)


def main():
    tr_all = pd.read_csv(TRUTH, parse_dates=["t_from", "t_to"])
    f107 = rb.load_f107()
    rows, items_all = [], []
    for k, (nid, g) in enumerate(tr_all.groupby("norad_id"), 1):
        w0, w1 = g["t_from"].min(), g["t_to"].max()
        eps = episodes(g[g["label_meme"] == 1])
        try:
            df = rb.load_tle(int(nid))
        except Exception:
            continue
        df = df[(df["epoch"] >= w0) & (df["epoch"] <= w1)].sort_values("epoch", kind="stable").reset_index(drop=True)
        df = df[~((df["epoch"].shift(-1) - df["epoch"]).dt.total_seconds() < 1.0)].reset_index(drop=True)
        if len(df) < 20:
            continue
        l1 = rb.compute_l1(df, f107)
        tr, comb = l1["tr"], np.asarray(l1["combined"], bool)
        l2 = rb.compute_l2(df)
        ev = rb.build_candidate_events(df, tr, comb, l2, None, None, None)
        cap = rb.detection_capability(tr, comb, ev)
        md = cap["min_detect_m"] / 1000 if cap else None
        items = rb._l2_only_items(df, l2, ev, min_net_km=md)
        days = (df["epoch"].iloc[-1] - df["epoch"].iloc[0]).total_seconds() / 86400
        # 機率基準：覆蓋期間內「任一真值事件 ±24h」所占時間比例（每小時取樣）
        grid = pd.date_range(df["epoch"].iloc[0], df["epoch"].iloc[-1], freq="1h")
        cover = np.zeros(len(grid), bool)
        for e in eps:
            cover |= (grid >= e["t0"] - PAD) & (grid <= e["t1"] + PAD)
        for e in eps:
            e["l1"] = any(x["t_start"] - PAD <= e["t1"] and e["t0"] <= x["t_end"] + PAD for x in ev)
            e["l2"] = (not e["l1"]) and any(e["t0"] - PAD <= x["epoch"] <= e["t1"] + PAD for x in items)
        hit = [near(x["epoch"], eps) for x in items]
        rows.append({"norad": int(nid), "days": days, "n_tle": len(df), "n_ep": len(eps),
                     "n_ep_s": sum(e["sev"] == 1 for e in eps), "n_ep_m": sum(e["sev"] == 2 for e in eps),
                     "n_ep_l": sum(e["sev"] == 3 for e in eps),
                     "ep_l1": sum(e["l1"] for e in eps), "ep_l2": sum(e["l2"] for e in eps),
                     "ep_l1_l": sum(e["l1"] for e in eps if e["sev"] == 3),
                     "ep_l2_l": sum(e["l2"] for e in eps if e["sev"] == 3),
                     "ep_l1_m": sum(e["l1"] for e in eps if e["sev"] == 2),
                     "ep_l2_m": sum(e["l2"] for e in eps if e["sev"] == 2),
                     "n_l1_ev": len(ev), "n_l2": len(items), "l2_hit": sum(hit),
                     "chance": float(cover.mean()) if len(cover) else np.nan})
        for x, h in zip(items, hit):
            items_all.append({"norad": int(nid), "epoch": x["epoch"], "value": x["value"], "source": x["source"], "hit": h})
        if k % 25 == 0:
            print(k, "sats", flush=True)
    R = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    R.to_csv(OUT, index=False, encoding="utf-8-sig")
    pd.DataFrame(items_all).to_csv(OUT.with_name(OUT.stem + "_items.csv"), index=False, encoding="utf-8-sig")
    s = R.sum(numeric_only=True)
    sd = s["days"]
    miss = s["n_ep"] - s["ep_l1"]
    print(f"衛星 {len(R)} 顆、{sd:.0f} 星日、真值事件 {s['n_ep']:.0f}（large {s['n_ep_l']:.0f}／medium {s['n_ep_m']:.0f}／small {s['n_ep_s']:.0f}）")
    print(f"L1 候選事件涵蓋真值事件 {s['ep_l1']:.0f}（{s['ep_l1']/s['n_ep']:.3f}）；L1 未涵蓋 {miss:.0f}")
    print(f"L2 補列 {s['ep_l2']:.0f}（占 L1 未涵蓋 {s['ep_l2']/max(miss,1):.3f}）；large L1 {s['ep_l1_l']:.0f}/{s['n_ep_l']:.0f}、L2 補列 {s['ep_l2_l']:.0f}；"
          f"medium L1 {s['ep_l1_m']:.0f}/{s['n_ep_m']:.0f}、L2 補列 {s['ep_l2_m']:.0f}")
    print(f"L2 項 {s['n_l2']:.0f}：命中 {s['l2_hit']:.0f}（{s['l2_hit']/max(s['n_l2'],1):.3f}）；未對應真值 {s['n_l2']-s['l2_hit']:.0f}，"
          f"每千星日 {(s['n_l2']-s['l2_hit'])/sd*1000:.2f} 項；每千星日 L2 項總數 {s['n_l2']/sd*1000:.2f}")
    print(f"機率基準（隨機時點落在真值事件 ±24h 內）：{np.average(R['chance'], weights=R['days']):.3f}")


if __name__ == "__main__":
    main()
