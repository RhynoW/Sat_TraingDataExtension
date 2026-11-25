# -*- coding: utf-8 -*-
"""gen_tasa_tender_case_figs.py — TASA 2026-11-25 提問第 8 題：三類衛星之 R7 偵測案例圖（半長軸高度 vs 候選事件）

三類衛星（每類 2–3 例）：
  一般衛星（化學推進，有營運方點火真值）：Jason-3、SWOT（IDS／CDDIS 點火紀錄，ids_truth_set/ids_truth.csv）
  Starlink：STARLINK-37471（MEME 精密星曆真值，data/meme_truth/transitions_full_20260918.csv）、STARLINK-4314（無真值）
  非 Starlink 電力推進：Amazon Kuiper、OneWeb（公開資料顯示使用霍爾推進器；無公開機動真值）
  註：raw_tle_archive 對多數物件只保留 2026-04 以後之 TLE，電推案例因此選在此期間內入軌爬升之 Kuiper 衛星
R7：maneuver_report_builder.build_report_data()（與 App 頁面主結果、PDF 報表同一函式）。

每張圖：上為 TLE 平均半長軸換算之高度（a − 6378.137 km）；下方三條時間帶依序為真值、R7 候選事件（依證據等級著色）、
低置信複核項（實心 = 立即複核 P1，空心 = 排程複核 P2）。
輸出：docs/tasa_reply_20261125/fig_case_*.png 與 cases_summary.json
用法：python docs/gen_tasa_tender_case_figs.py [案例代號 …]
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
sys.stdout.reconfigure(encoding="utf-8")
import maneuver_report_builder as rb  # noqa: E402

OUT = ROOT / "docs" / "tasa_reply_20261125"
OUT.mkdir(parents=True, exist_ok=True)
RE = 6378.137
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, GRAY = "#2a78d6", "#8a8984"
GRADE_COL = {"E3": "#b0127f", "E2": "#eb6834", "E1": "#eda100", "D": "#8a8984"}

NAMES = {41240: "Jason-3", 54754: "SWOT", 68802: "STARLINK-37471", 53056: "STARLINK-4314", 61595: "ONEWEB-0687", 67142: "KUIPER-00188"}
CASES = [
    # 代號, 類別, NORAD, 起, 訖, 真值, 說明
    ("G1", "一般衛星", 41240, date(2025, 1, 1), date(2025, 12, 31), "ids", "2025 年分段降軌，營運方紀錄 33 次點火（累計約 −26 km）"),
    ("G2", "一般衛星", 54754, date(2023, 1, 11), date(2023, 9, 30), "ids", "發射後由校驗軌道升至科學軌道（累計約 +31 km）"),
    ("G3", "一般衛星", 54754, date(2025, 1, 1), date(2026, 8, 20), "ids", "科學軌道之維持點火：單次淨變化 12–45 m；另有 4 組 ±0.15–0.36 km、方向相反之成對點火"),
    ("S1", "Starlink", 68802, date(2026, 5, 1), date(2026, 8, 31), "meme", "2026-06-21 大型升軌（8.1 節案例）"),
    ("S2", "Starlink", 53056, date(2026, 3, 31), date(2026, 11, 14), None, "26 天累計 −83.8 km 之連續降軌（TASA 指定 15 顆之一）"),
    ("E1", "非 Starlink 電推", 67142, date(2026, 4, 1), date(2026, 11, 14), None, "Amazon Kuiper：入軌後以霍爾推進器由約 450 km 逐步爬升至約 630 km 運作高度"),
    ("E2", "非 Starlink 電推", 61595, date(2026, 4, 1), date(2026, 11, 14), None, "OneWeb：約 1,200 km 運作高度，以霍爾推進器維持軌道"),
]


def truth_ids(norad, d0, d1):
    t = pd.read_csv(ROOT / "ids_truth_set/ids_truth.csv")
    t = t[t.norad == norad].copy()
    t["t"] = pd.to_datetime(t.epoch_utc, utc=True)
    t = t[(t.t.dt.date >= d0) & (t.t.dt.date <= d1)]
    return pd.DataFrame({"t": t.t, "da": t.da_km, "vis": t.tle_visible_50.fillna(0) > 0})


def truth_meme(norad, d0, d1):
    t = pd.read_csv(ROOT / "data/meme_truth/transitions_full_20260918.csv", usecols=["norad_id", "t_from", "t_to", "da_km", "label_meme"])
    t = t[(t.norad_id == norad) & (t.label_meme == 1)].copy()
    t["t"] = pd.to_datetime(t.t_from, utc=True) + (pd.to_datetime(t.t_to, utc=True) - pd.to_datetime(t.t_from, utc=True)) / 2
    t = t[(t.t.dt.date >= d0) & (t.t.dt.date <= d1)].sort_values("t")
    # MEME 逐筆轉換幾乎全標為機動（電推連續推力），依全專案定義以 48 小時間隔合併為機動段
    segs, cur = [], None
    for x in t.itertuples():
        if cur and x.t - cur[1] <= pd.Timedelta(hours=48):
            cur[1] = x.t; cur[2] += 1
        else:
            if cur: segs.append(cur)
            cur = [x.t, x.t, 1]
    if cur: segs.append(cur)
    return pd.DataFrame({"t": [a for a, _, _ in segs], "t_end": [b for _, b, _ in segs], "n": [n for _, _, n in segs],
                         "da": np.nan, "vis": True})


def style(ax):
    ax.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#c9c8c3")
    ax.tick_params(colors=INK2, labelsize=8)


def run_case(code, cat, norad, d0, d1, truth, desc):
    r = rb.build_report_data(norad, d0, d1, lang="zh", with_ai=False, with_external=False)
    df = r["tle_df"]
    tt = pd.to_datetime(df["epoch"], utc=True)
    alt = df["sma_km"] - RE if "sma_km" in df else df["a_km"] - RE
    ev, lc = r["events"] or [], r["low_conf"] or []
    tr = {"ids": truth_ids, "meme": truth_meme}[truth](norad, d0, d1) if truth else None
    name = NAMES.get(norad) or r.get("name") or str(norad)

    fig = plt.figure(figsize=(9.6, 5.0), dpi=200)
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1.1], hspace=0.08)
    ax = fig.add_subplot(gs[0]); bx = fig.add_subplot(gs[1], sharex=ax)
    ax.plot(tt, alt, color=BLUE, lw=1.2, marker=".", ms=2.2, label="TLE 平均半長軸高度")
    for e in ev:
        c = GRADE_COL.get(e["grade"], GRAY)
        ax.axvspan(e["t_start"], max(e["t_end"], e["t_start"] + pd.Timedelta(hours=12)), color=c, alpha=0.18, lw=0)
    ax.set_ylabel("高度（km）", color=INK2, fontsize=8.5); style(ax)
    ax.ticklabel_format(axis="y", useOffset=False, style="plain")
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.xaxis.get_offset_text().set_visible(False)
    n_g = {g: sum(1 for e in ev if e["grade"] == g) for g in ("E3", "E2", "E1", "D")}
    ax.set_title(f"{cat}｜{name}（NORAD {norad}）　{d0} 至 {d1}\n{desc}", fontsize=9.5, color=INK, loc="left")
    # 下方三條時間帶
    lanes = {"真值": 2, "R7 候選事件": 1, "低置信複核項": 0}
    if tr is not None and len(tr) and truth == "meme":
        for x in tr.itertuples():
            bx.barh(2, max(x.t_end - x.t, pd.Timedelta(hours=12)), left=x.t, height=0.35, color=INK)
        bx.barh(-9, 0, color=INK, label=f"真值機動段（MEME，{len(tr)} 段）")
    elif tr is not None and len(tr):
        v = tr[tr.vis]; h = tr[~tr.vis]
        lab_v = "真值（TLE 可見）" if truth == "ids" else "真值（|Δa| ≥ 0.1 km）"
        bx.scatter(v.t, [2] * len(v), marker="v", s=22, color=INK, label=lab_v, zorder=3)
        if len(h):
            bx.scatter(h.t, [2] * len(h), marker="v", s=14, facecolors="none", edgecolors=GRAY, lw=0.8,
                       label="真值（低於 TLE 偵測下限）" if truth == "ids" else "真值（|Δa| < 0.1 km）", zorder=2)
    else:
        bx.text(tt.iloc[0], 2, "  無公開機動真值", va="center", fontsize=7.5, color=INK2)
    for e in ev:
        c = GRADE_COL.get(e["grade"], GRAY)
        bx.barh(1, (max(e["t_end"], e["t_start"] + pd.Timedelta(hours=18)) - e["t_start"]), left=e["t_start"], height=0.5, color=c)
    handles = [Patch(color=c, label=f"{g}（{n_g[g]} 件）") for g, c in GRADE_COL.items() if n_g[g]]
    p1 = [x["epoch"] for x in lc if x.get("priority") == "P1"]
    p2 = [x["epoch"] for x in lc if x.get("priority") != "P1"]
    if p1: bx.scatter(p1, [0] * len(p1), marker="o", s=12, color="#3f6fb5", label=f"立即複核（{len(p1)}）")
    if p2: bx.scatter(p2, [0] * len(p2), marker="o", s=12, facecolors="none", edgecolors="#3f6fb5", lw=0.8, label=f"排程複核（{len(p2)}）")
    bx.set_yticks(list(lanes.values())); bx.set_yticklabels(list(lanes.keys()), fontsize=8)
    bx.set_ylim(-0.6, 2.6); style(bx)
    bx.set_xlim(pd.Timestamp(d0, tz="UTC"), pd.Timestamp(d1, tz="UTC") + pd.Timedelta(days=1))
    bx.xaxis.set_major_formatter(mdates.ConciseDateFormatter(bx.xaxis.get_major_locator()))
    h0, _ = bx.get_legend_handles_labels()
    bx.legend(handles=h0 + handles, frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=4)
    fig.savefig(OUT / f"fig_case_{code}.png", facecolor="#ffffff", bbox_inches="tight"); plt.close(fig)

    # 真值對照（±24 小時內有候選事件或低置信複核項）
    summ = {"code": code, "cat": cat, "norad": norad, "name": name, "d0": str(d0), "d1": str(d1), "desc": desc,
            "n_tle": int(len(df)), "alt_range_km": [float(alt.min()), float(alt.max())], "net_alt_change_km": float(alt.iloc[-1] - alt.iloc[0]),
            "events": n_g, "events_total": len(ev), "low_conf_P1": len(p1), "low_conf_P2": len(p2),
            "detect_cap": r.get("detect_cap"), "largest_event_net_da_km": max((abs(e["net_da"]) for e in ev), default=None),
            "smallest_event_net_da_km": min((abs(e["net_da"]) for e in ev), default=None)}
    if tr is not None and len(tr):
        pad = pd.Timedelta(hours=24)
        def hit(t, items):
            return any(a - pad <= t <= b + pad for a, b in items)
        evw = [(e["t_start"], e["t_end"]) for e in ev]
        lcw = [(x["epoch"], x["epoch"]) for x in lc]
        if truth == "meme":
            def hit(t, items, te=None):   # 機動段與事件窗重疊即算
                te = te if te is not None else t
                return any(a - pad <= te and t <= b + pad for a, b in items)
            summ["truth"] = {"type": "meme_segments", "n": int(len(tr)),
                             "seg_hit_event": int(sum(hit(x.t, evw, x.t_end) for x in tr.itertuples())),
                             "seg_hit_event_or_lc": int(sum(hit(x.t, evw + lcw, x.t_end) for x in tr.itertuples())),
                             "seg_days": [round((x.t_end - x.t).total_seconds() / 86400, 1) for x in tr.itertuples()]}
            summ["events_near_truth"] = int(sum(any(x.t - pad <= b and a <= x.t_end + pad for x in tr.itertuples()) for a, b in evw))
            print(code, name, n_g, summ["truth"], flush=True)
            return summ
        v = tr[tr.vis]
        summ["truth"] = {"type": truth, "n": int(len(tr)), "n_visible": int(len(v)),
                         "visible_hit_event": int(sum(hit(t, evw) for t in v.t)),
                         "visible_hit_event_or_lc": int(sum(hit(t, evw + lcw) for t in v.t)),
                         "hidden_hit_event": int(sum(hit(t, evw) for t in tr[~tr.vis].t)),
                         "da_abs_range_km": [float(tr.da.abs().min()), float(tr.da.abs().max())]}
        summ["events_near_truth"] = int(sum(any(a - pad <= t <= b + pad for t in tr.t) for a, b in evw))
    print(code, name, n_g, summ.get("truth"), flush=True)
    return summ


def main():
    pick = set(sys.argv[1:])
    path = OUT / "cases_summary.json"
    allr = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for c in CASES:
        if pick and c[0] not in pick:
            continue
        allr[c[0]] = run_case(*c)
        path.write_text(json.dumps(allr, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    path.write_text(json.dumps(allr, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
