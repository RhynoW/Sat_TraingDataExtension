#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_fs7_event_selection.py — 論文二補充圖 Fig. S4：納入（96）vs 排除（35）事件之分布。

內容：131 件已驗證機動事件依「TLE 前後段覆蓋是否足夠」分為納入（computable，96 件）與排除（35 件），
  (a) 依 SP3 振幅箱（1–50 m、50–100 m、100–300 m、300 m–1 km、1–3 km）
  (b) 依 campaign（2024-07、2024-11/12、2025-05、2025-07/08、2026-01）
  (c) 依衛星（SP3 代碼 L76–L81 與 NORAD）
  之堆疊長條，長條上方標排除率；(a) 另附兩組振幅中位數與 Mann–Whitney U 檢定 p 值。
程式會核對：總數 131／96／35、各 campaign 驗證事件數（29、41、8、46、7，Table 1a）、
  振幅箱排除率範圍（論文 §2.6：0.18–0.35）、campaign 排除率範圍（補充材料 Table S2–S4：0.00–0.54，2025-05 為 0/8；
  論文正文 §2.6 寫 0.07–0.54，係漏計 2025-05），不一致者印出。

輸入：data/benchmark/fs7_tle_recall_unified_20260825.csv（131 件；欄 campaign、sp3_sat、amp_m、computable）
      data/benchmark/fs7_events_campaigns_20260825.csv、fs7_events_2025raise.csv（核對各 campaign 事件數）
輸出：docs/fig_fs7_event_selection.png（600 dpi）＋ .pdf
用法：python docs/gen_fig_fs7_event_selection.py          （docs/ 英文白底）
      python docs/gen_fig_fs7_event_selection.py --pub    （docs/figures_pub/ 四版本）
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DOCS))
import fs7_fig_style as st  # noqa: E402
from fig_pub import t  # noqa: E402

EDGES = [0, 50, 100, 300, 1000, 3000]
BIN_LAB = ["1–50 m", "50–100 m", "100–300 m", "300 m–1 km", "1–3 km"]
CAMPAIGNS = ["2024-07", "2024-11/12", "2025-05", "2025-07/08", "2026-01"]
SATS = {"L76": 44349, "L77": 44351, "L78": 44343, "L79": 44350, "L80": 44358, "L81": 44353}


def load():
    r = pd.read_csv(st.BM / "fs7_tle_recall_unified_20260825.csv")
    r["bin"] = pd.cut(r["amp_m"], EDGES, labels=False)
    return r


def table(r, col, keys):
    g = r.groupby(col)["computable"].agg(["size", "sum"]).reindex(keys)
    g = g.rename(columns={"size": "n", "sum": "inc"})
    g["exc"] = g["n"] - g["inc"]
    g["rate"] = g["exc"] / g["n"]
    return g


def verify():
    r = load()
    msgs = []
    if (len(r), int(r["computable"].sum()), int((~r["computable"]).sum())) != (131, 96, 35):
        msgs.append(f"總數 {len(r)}/{r['computable'].sum()}/{(~r['computable']).sum()} ≠ 131/96/35")
    cam = table(r, "campaign", CAMPAIGNS)
    e25 = pd.read_csv(st.BM / "fs7_events_2025raise.csv")
    enew = pd.read_csv(st.BM / "fs7_events_campaigns_20260825.csv")
    ver = enew[enew["verdict"] == "疑似真事件"].groupby("campaign").size().to_dict()
    ver["2025-07/08"] = int((e25["verdict"] == "疑似真事件").sum())
    exp = {"2024-07": 29, "2024-11/12": 41, "2025-05": 8, "2025-07/08": 46, "2026-01": 7}
    for k, v in exp.items():
        if int(cam.loc[k, "n"]) != v or ver.get(k) != v:
            msgs.append(f"campaign {k}: recall CSV {int(cam.loc[k, 'n'])}、事件表 {ver.get(k)}、Table 1a {v}")
    b = table(r, "bin", list(range(5)))
    rb = (round(b["rate"].min(), 2), round(b["rate"].max(), 2))
    rc = (round(cam["rate"].min(), 2), round(cam["rate"].max(), 2))
    print(f"核對：131／96／35 {'一致' if not msgs else ''}；各 campaign 事件數與 Table 1a "
          f"{'一致' if not any('campaign' in m for m in msgs) else '不一致'}")
    print(f"  振幅箱排除率範圍 {rb[0]:.2f}–{rb[1]:.2f}（論文 0.18–0.35）：{'一致' if rb == (0.18, 0.35) else '差異'}")
    print(f"  campaign 排除率範圍 {rc[0]:.2f}–{rc[1]:.2f}（補充材料 0.00–0.54；正文 §2.6 寫 0.07–0.54）：{'一致' if rc == (0.0, 0.54) else '差異'}")
    print("  campaign 排除率：" + "、".join(f"{k} {v:.2f}" for k, v in cam["rate"].items()))
    s = table(r, "sp3_sat", list(SATS))
    print("  衛星排除率：" + "、".join(f"{k} {v:.2f}" for k, v in s["rate"].items()))
    for m in msgs:
        print("  [不一致]", m)


def draw():
    import matplotlib.pyplot as plt
    from scipy.stats import mannwhitneyu
    r = load()
    fig, axes = plt.subplots(1, 3, figsize=(st.DOUBLE, 5.6 * st.CM),
                             gridspec_kw={"width_ratios": [5, 5, 6], "wspace": 0.28})
    specs = [("bin", list(range(5)), BIN_LAB, t("SP3 振幅箱", "SP3 amplitude bin")),
             ("campaign", CAMPAIGNS, CAMPAIGNS, t("Campaign", "Campaign")),
             ("sp3_sat", list(SATS), [f"{k}\n{v}" for k, v in SATS.items()],
              t("衛星（SP3 代碼／NORAD）", "Satellite (SP3 code / NORAD)"))]
    ymax = 55
    for i, (ax, (col, keys, labs, xl)) in enumerate(zip(axes, specs)):
        g = table(r, col, keys)
        x = np.arange(len(keys))
        ax.bar(x, g["inc"], width=0.68, color=st.BLUE, label=t("納入（n = 96）", "Included (n = 96)"))
        ax.bar(x, g["exc"], width=0.68, bottom=g["inc"], color="white", edgecolor=st.ORANGE, lw=0.8,
               hatch="////", label=t("排除（n = 35）", "Excluded (n = 35)"))
        for xi, (_, row) in zip(x, g.iterrows()):
            ax.text(xi, row["n"] + 1.0, f"{row['rate']:.2f}", ha="center", va="bottom", fontsize=6.0,
                    color=st.ORANGE)
        ax.set_xticks(x)
        ax.set_xticklabels(labs, fontsize=5.9, rotation=0 if col == "sp3_sat" else 30,
                           ha="center" if col == "sp3_sat" else "right")
        ax.set_xlabel(xl)
        ax.set_ylim(0, ymax)
        ax.grid(alpha=0.3, axis="y")
        st.panel_label(ax, f"({'abc'[i]})", x=-0.08, y=1.02)
    axes[0].set_ylabel(t("事件數", "Number of events"))
    inc, exc = r.loc[r["computable"], "amp_m"], r.loc[~r["computable"], "amp_m"]
    p = mannwhitneyu(inc, exc).pvalue
    axes[0].text(0.98, 0.88, t(f"振幅中位數：\n納入 {inc.median():.0f} m、排除 {exc.median():.0f} m\nMann–Whitney p = {p:.2f}",
                               f"Median |Δa|:\nincluded {inc.median():.0f} m, excluded {exc.median():.0f} m\nMann–Whitney p = {p:.2f}"),
                 transform=axes[0].transAxes, ha="right", va="top", fontsize=5.6, color=st.INK, linespacing=1.3)
    axes[2].legend(loc="upper left", fontsize=6.0)
    axes[1].text(0.03, 0.97, t("數字：排除率", "Labels: exclusion rate"), transform=axes[1].transAxes,
                 ha="left", va="top", fontsize=5.8, color=st.ORANGE)
    return fig


if __name__ == "__main__":
    verify()
    st.run({"fig_fs7_event_selection": draw})
