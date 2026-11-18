#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_fs7_real_event_recall.py — 論文二 Fig. 6：真實事件比較 vs 振幅。

內容（橫軸為 SP3 真值事件振幅 |Δa|，對數）：
  - 觀測召回率：統一 3σ 門檻（3.9–6.2 m）與 45 m 門檻，96 件 TLE 可比對事件、5 個振幅箱，Wilson 95% CI；
  - 模型平均預測機率（逐事件預測機率之箱內平均＝Table 4 「mean predicted event-level probability」欄）；
  - 注入校準之預測曲線：P(Δa) = mean_i logistic(Δa / σ_eff,i)，σ_eff,i 取 96 件事件各自之有效殘差尺度
    （= amp_m / snr_eff_pred），陰影為 σ_eff 四分位距（P25–P75）兩條曲線之間；
  - 2024 年 5 月磁暴區間 21 件假候選之振幅（皆為負向，−47 至 −16 m；以 |Δa| 標於底部，非機動、不在 131 件內）。
係數與 CSV 之 p_pred 欄相同（fs7_tle_recall_unified.py 之 C_DRAG, SNR50, BETA），曲線與箱內平均因此一致。
程式會核對各箱 n、兩門檻召回、Wilson CI 與平均預測機率是否等於論文 Table 4（不一致即中止）。

輸入：data/benchmark/fs7_tle_recall_unified_20260825.csv（131 件；computable 為 96 件）
      data/benchmark/fs7_events_2024.csv（磁暴樣本 87 件候選；verdict = 疑似真事件 者 21 件）
      data/benchmark/fs7_law_fit_v4.json（核對描述性係數 SNR50 / β）
輸出：docs/fig_fs7_real_event_recall.png（600 dpi）＋ .pdf
用法：python docs/gen_fig_fs7_real_event_recall.py          （docs/ 英文白底）
      python docs/gen_fig_fs7_real_event_recall.py --pub    （docs/figures_pub/ 四版本）
"""
from __future__ import annotations

import json
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
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402
from fs7_tle_recall_unified import BETA, C_DRAG, SNR50, wilson  # noqa: E402

EDGES = [0, 50, 100, 300, 1000, 3000]
LAB_EN = ["1–50 m", "50–100 m", "100–300 m", "300 m–1 km", "1–3 km"]
# 論文 Table 4：n, recall@45m, recall@unified, CI lo, CI hi, mean predicted
TABLE4 = [(37, 0.11, 0.19, 0.09, 0.34, 0.29), (16, 0.31, 0.50, 0.28, 0.72, 0.59),
          (18, 0.50, 0.61, 0.39, 0.80, 0.67), (8, 0.62, 0.62, 0.31, 0.86, 0.68),
          (17, 0.82, 0.82, 0.59, 0.94, 0.65)]


def load():
    r = pd.read_csv(st.BM / "fs7_tle_recall_unified_20260825.csv")
    c = r[r["computable"]].copy()
    c["bin"] = pd.cut(c["amp_m"], EDGES, labels=False)
    rows = []
    for b, g in c.groupby("bin"):
        n = len(g)
        k_new, k_old = int(g["det_new"].sum()), int(g["det_old"].sum())
        rows.append({"bin": int(b), "n": n, "amp_med": g["amp_m"].median(),
                     "rec_new": k_new / n, "ci_new": wilson(k_new, n),
                     "rec_old": k_old / n, "ci_old": wilson(k_old, n),
                     "p_mean": g["p_pred"].mean()})
    bins = pd.DataFrame(rows)
    sig_eff = (c["amp_m"] / c["snr_eff_pred"]).values           # m
    e = pd.read_csv(st.BM / "fs7_events_2024.csv")
    storm = e.loc[e["verdict"] == "疑似真事件", "step_m"].values
    return r, c, bins, sig_eff, storm


def verify():
    r, c, bins, sig_eff, storm = load()
    msgs = []
    assert len(r) == 131 and len(c) == 96, (len(r), len(c))
    for (_, b), ref in zip(bins.iterrows(), TABLE4):
        got = (b["n"], round(b["rec_old"], 2), round(b["rec_new"], 2), round(b["ci_new"][0], 2),
               round(b["ci_new"][1], 2), round(b["p_mean"], 2))
        if tuple(got) != ref:
            msgs.append(f"bin {LAB_EN[int(b['bin'])]}: 計算 {got} ≠ Table 4 {ref}")
    if len(storm) != 21 or round(storm.min()) != -47 or round(storm.max()) != -16 or (storm > 0).any():
        msgs.append(f"磁暴候選：n={len(storm)} 範圍 {storm.min():.1f}–{storm.max():.1f} m（論文 21 件、−47 至 −16 m）")
    v4 = json.loads((st.BM / "fs7_law_fit_v4.json").read_text(encoding="utf-8"))
    if (round(v4["law_fit_v4"]["snr50"], 2), round(v4["law_fit_v4"]["beta"], 2), v4["c_drag"]["c_hat"]) != (SNR50, BETA, C_DRAG):
        msgs.append("fs7_tle_recall_unified 係數與 fs7_law_fit_v4.json 不同")
    if msgs:
        print("[不一致] 與論文 Table 4／§5.1 數字不符，中止：")
        for m in msgs:
            print("   ", m)
        sys.exit(1)
    print("核對：各箱 n、兩門檻召回、Wilson CI、平均預測機率與 Table 4 一致；磁暴 21 件 −47 至 −16 m 一致")


def p_model(da_m, sig_m):
    snr = np.maximum(da_m / sig_m, 1e-3)
    return 1 / (1 + np.exp(-BETA * (np.log10(snr) - np.log10(SNR50))))


def draw():
    import matplotlib.pyplot as plt
    _, c, bins, sig_eff, storm = load()
    fig, ax = plt.subplots(figsize=(st.SINGLE, 9.0 * st.CM))
    x = np.logspace(np.log10(8), np.log10(4000), 300)

    # 磁暴假候選（|Δa|）
    s_abs = np.abs(storm)
    ax.axvspan(s_abs.min(), s_abs.max(), color=st.RED, alpha=0.10, lw=0, zorder=0)
    ax.plot(s_abs, np.full_like(s_abs, 0.025), "|", ms=7, mew=0.7, color=st.RED, zorder=3,
            label=t(f"磁暴區間假候選（n = {len(storm)}，−{-storm.min():.0f} 至 −{-storm.max():.0f} m）",
                    f"Storm-interval spurious candidates (n = {len(storm)}, −{-storm.min():.0f} to −{-storm.max():.0f} m)"))

    # 振幅箱界線與 n
    for e_ in EDGES[1:-1]:
        ax.axvline(e_, color="#c8ccd2", lw=0.5, zorder=0)
    for _, b in bins.iterrows():
        lo, hi = EDGES[int(b["bin"])], EDGES[int(b["bin"]) + 1]
        xc = np.sqrt(max(lo, 10) * hi)
        ax.text(xc, 1.035, f"n = {int(b['n'])}", ha="center", va="bottom", fontsize=5.8, color=st.GRAY,
                transform=ax.get_xaxis_transform())

    # 注入校準之預測曲線
    pm = np.array([p_model(v, sig_eff).mean() for v in x])
    q25, q75 = np.percentile(sig_eff, [25, 75])
    ax.fill_between(x, p_model(x, q75), p_model(x, q25), color=st.BLUE, alpha=0.09, lw=0,
                    label=t(f"預測（σ_eff 四分位距 {q25:.0f}–{q75:.0f} m）",
                            f"Prediction, σ_eff IQR ({q25:.0f}–{q75:.0f} m)"))
    ax.plot(x, pm, "-", color=st.BLUE, lw=1.1,
            label=t("注入校準之預測召回（96 件平均）", "Injection-calibrated prediction (mean over 96 events)"))

    xm = bins["amp_med"].values
    ax.plot(xm, bins["p_mean"], "D", ms=3.6, color=st.BLUE, mfc="white", mew=0.9, zorder=5,
            label=t("模型平均預測機率（箱內）", "Mean predicted probability (per bin)"))
    for col, f, mk, mfc, lab in (
            ("new", 0.90, "o", st.INK, t("觀測召回：統一 3σ 門檻", "Observed recall, unified 3σ threshold")),
            ("old", 1.11, "s", "white", t("觀測召回：45 m 門檻", "Observed recall, 45 m threshold"))):
        y = bins[f"rec_{col}"].values
        lo = y - np.array([c_[0] for c_ in bins[f"ci_{col}"]])
        hi = np.array([c_[1] for c_ in bins[f"ci_{col}"]]) - y
        ax.errorbar(xm * f, y, yerr=[lo, hi], fmt=mk, ms=3.4, color=st.INK, mfc=mfc, mew=0.8,
                    elinewidth=0.6, capsize=1.6, capthick=0.6, zorder=6, label=lab)

    ax.set_xscale("log")
    if not fp.is_en():
        from matplotlib.ticker import FuncFormatter
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlim(8, 4000)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel(t("事件振幅 |Δa|（m，SP3 真值）", "Event amplitude |Δa| (m, SP3 truth)"))
    ax.set_ylabel(t("召回率／偵測機率", "Recall / detection probability"))
    ax.grid(alpha=0.3, which="major")
    h, l = ax.get_legend_handles_labels()
    order = [4, 5, 3, 2, 1, 0]
    ax.legend([h[i] for i in order], [l[i] for i in order], loc="upper left", fontsize=5.9,
              handlelength=1.6, labelspacing=0.35, bbox_to_anchor=(-0.02, -0.12))
    return fig


if __name__ == "__main__":
    verify()
    st.run({"fig_fs7_real_event_recall": draw})
