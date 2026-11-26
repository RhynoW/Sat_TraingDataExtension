# -*- coding: utf-8 -*-
"""gen_fig_sma_vs_events.py — 半長軸（SMA）變化與 R7 候選事件之關係圖

兩例對照（同期 2026-05-18 至 08-16）：
  ICEYE-X33（TASA 指定 15 顆之一，約 564 km）：平緩維持，單步超過 5σ、20σ 但未達 L1 門檻 → 0 件
  KUIPER-00188（非 Starlink 電推，約 630 km）：5/20–5/27 降軌之單步超過 L1 門檻 → 2 件；其後維持期 0 件
上排：TLE 平均半長軸高度與 R7 候選事件（依證據等級著色）
下排：相鄰 TLE 之 |Δa|（對數刻度），標示 5σ、20σ 與 L1 有效門檻（P2 高度門檻 × P5 太陽活動 × P6 族群倍率）；
      L1 標記點分三種來源：①|Δa| 超過有效門檻、②Δi／Δe 超過門檻、③P4 相鄰補標（①②之後 2 筆，不論大小）；
      扣除 P1 抑制後合併為候選事件。③可位於門檻甚至 5σ 線以下，但不會單獨產生事件
R7：maneuver_report_builder.build_report_data()；L1 有效門檻由 maneuver_strategies_july.apply_strategies() 取得（同一函式）。
輸出：docs/tasa_reply_20261126/fig_sma_vs_events.png、sma_vs_events.json
--tasa15：TASA 指定 15 顆衛星（期間同交付 r15.json），輸出 fig_sma_vs_events_tasa15_p1–p4.png、sma_vs_events_tasa15.json
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
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
sys.stdout.reconfigure(encoding="utf-8")
import maneuver_report_builder as rb  # noqa: E402
import maneuver_strategies_july as ms  # noqa: E402

OUT = ROOT / "docs" / "tasa_reply_20261126"
OUT.mkdir(parents=True, exist_ok=True)
RE = 6378.137
D0, D1 = date(2026, 5, 18), date(2026, 8, 16)
CASES = [(60548, "ICEYE-X33", "平緩維持：單步超過 5σ、20σ，未達 L1 門檻"),
         (67142, "KUIPER-00188", "降軌之單步超過 L1 門檻；其後維持期未達")]
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, GRAY, RED = "#2a78d6", "#a9a8a3", "#d6312b"
GRADE_COL = {"E3": "#b0127f", "E2": "#eb6834", "E1": "#eda100", "D": "#8a8984"}


def style(ax):
    ax.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"): ax.spines[sp].set_color("#c9c8c3")
    ax.tick_params(colors=INK2, labelsize=8)


PINK = "#f0a19c"


def flag_sources(tr, res, flag):
    """L1 最終標記之三種來源：①Δa 超過有效門檻、②只有 Δi／Δe 超過門檻、③ P4 相鄰補標（觸發點之後 2 筆）。"""
    thr = np.asarray(res["thr_da"], float)
    main = flag & (np.abs(tr["da_km"].to_numpy(float)) > thr)
    oth = flag & ~main & ((np.abs(tr["di_deg"].to_numpy(float)) > ms.THR_DI) | (np.abs(tr["de"].to_numpy(float)) > ms.THR_DE))
    p4 = flag & ~main & ~oth
    return main, oth, p4


def scatter_flags(bx, te, ad, da_m, main, oth, p4, s_main, s_p4):
    for m, mk in ((da_m >= 0, "^"), (da_m < 0, "v")):
        bx.scatter(te[p4 & m], np.maximum(ad[p4 & m], 0.3), marker=mk, s=s_p4, color=PINK, edgecolors="white", lw=0.3, zorder=3)
        bx.scatter(te[oth & m], np.maximum(ad[oth & m], 0.3), marker=mk, s=s_main, facecolors="white", edgecolors=RED, lw=1.0, zorder=4)
        bx.scatter(te[main & m], ad[main & m], marker=mk, s=s_main, color=RED, edgecolors="white", lw=0.4, zorder=5)


def flag_handles(ms_main, ms_p4):
    return [Line2D([], [], marker="^", ls="", color=RED, ms=ms_main, label="紅色實心：Δa 超過 L1 有效門檻"),
            Line2D([], [], marker="^", ls="", mfc="white", mec=RED, mew=1.0, ms=ms_main, label="紅色空心：Δi／Δe 超過門檻"),
            Line2D([], [], marker="^", ls="", color=PINK, ms=ms_p4, label="淡紅色：P4 延伸（觸發點之後 2 筆，不論大小）")]


def run(norad):
    r = rb.build_report_data(norad, D0, D1, lang="zh", with_ai=False, with_external=False)
    tr = r["tr_df"]
    res = ms.apply_strategies(tr, r["orbit_class"], lang="zh")
    flag = np.asarray(res["combined"], bool)
    sup = np.asarray(res["per_strategy"].get("P1_suppress", np.zeros(len(tr), bool)), bool) | \
          np.asarray(res["per_strategy"].get("P3_suppress", np.zeros(len(tr), bool)), bool)
    assert int(flag.sum()) == r["l1"]["n_flagged"], "L1 標記數與報表不一致"
    return r, tr, flag, sup, np.asarray(res["thr_da"], float)


def main():
    fig, axes = plt.subplots(2, 2, figsize=(13.0, 6.4), dpi=200, sharex="col",
                             gridspec_kw={"height_ratios": [1, 1.35], "hspace": 0.12, "wspace": 0.16})
    summary = []
    for col, (norad, name, sub) in enumerate(CASES):
        r, tr, flag, sup, thr = run(norad)
        df = r["tle_df"]; tt = pd.to_datetime(df["epoch"], utc=True)
        alt = (df["sma_km"] if "sma_km" in df else df["a_km"]) - RE
        te = pd.to_datetime(tr["epoch"], utc=True)
        da_m = tr["da_km"].to_numpy(float) * 1000
        ad = np.abs(da_m)
        sig = r["detect_cap"]["sigma_med_m"]
        s5, s20 = 5 * sig, r["detect_cap"]["min_detect_m"]
        ev = r["events"] or []
        ax, bx = axes[0, col], axes[1, col]
        # 上排：高度與事件
        ax.plot(tt, alt, color=BLUE, lw=1.0, marker=".", ms=2.2)
        for e in ev:
            for a in (ax, bx):
                a.axvspan(e["t_start"], max(e["t_end"], e["t_start"] + pd.Timedelta(hours=12)),
                          color=GRADE_COL.get(e["grade"], GRAY), alpha=0.16, lw=0)
        ax.ticklabel_format(axis="y", useOffset=False, style="plain")
        ax.set_ylabel("半長軸高度（km）", fontsize=8.5, color=INK2); style(ax)
        ax.set_title(f"{name}（NORAD {norad}，約 {r['alt_km_avg']:.0f} km）\n{sub}", fontsize=10, color=INK, loc="left")
        # 下排：|Δa| 與三條門檻
        other = ~flag & ~sup
        res = ms.apply_strategies(tr, r["orbit_class"], lang="zh")
        fm, fo, fp = flag_sources(tr, res, flag)
        for m, mk, lab in ((da_m >= 0, "^", "上升"), (da_m < 0, "v", "下降")):
            bx.scatter(te[other & m], np.maximum(ad[other & m], 0.3), marker=mk, s=11, color=BLUE, lw=0, alpha=0.8)
            bx.scatter(te[sup & m], np.maximum(ad[sup & m], 0.3), marker=mk, s=11, color=GRAY, lw=0)
        scatter_flags(bx, te, ad, da_m, fm, fo, fp, 34, 20)
        bx.step(te, thr * 1000, where="post", color=INK, lw=1.4)
        bx.axhline(s20, color=INK2, lw=1.0, ls="--")
        bx.axhline(s5, color=INK2, lw=1.0, ls=":")
        x_txt = te.iloc[-1]
        bx.text(x_txt, float(np.median(thr)) * 1000 * 1.12, f"L1 有效門檻（中位）{np.median(thr)*1000:.0f} m", ha="right", va="bottom", fontsize=7.8, color=INK)
        bx.text(x_txt, s20 * 1.1, f"20σ {s20:.0f} m", ha="right", va="bottom", fontsize=7.8, color=INK2)
        bx.text(x_txt, s5 * 1.1, f"5σ {s5:.0f} m", ha="right", va="bottom", fontsize=7.8, color=INK2)
        bx.set_yscale("log"); bx.set_ylim(0.3, max(ad.max(), thr.max() * 1000) * 9)
        bx.set_ylabel("相鄰 TLE 之 |Δa|（m，對數）", fontsize=8.5, color=INK2); style(bx)
        bx.xaxis.set_major_formatter(mdates.ConciseDateFormatter(bx.xaxis.get_major_locator()))
        bx.set_xlim(pd.Timestamp(D0, tz="UTC"), pd.Timestamp(D1, tz="UTC") + pd.Timedelta(days=1))
        n_g = {g: sum(1 for e in ev if e["grade"] == g) for g in GRADE_COL}
        evtxt = "、".join(f"{g} {k}" for g, k in n_g.items() if k) or "0"
        s = {"norad": norad, "name": name, "n_transitions": int(len(tr)), "sigma_m": round(sig, 1),
             "sigma5_m": round(s5), "sigma20_m": round(s20), "l1_thr_median_m": round(float(np.median(thr)) * 1000),
             "n_gt_5sigma": int((ad > s5).sum()), "n_gt_20sigma": int((ad > s20).sum()),
             "n_l1_flagged": int(flag.sum()), "n_flag_thr": int(fm.sum()), "n_flag_di_de": int(fo.sum()), "n_flag_p4": int(fp.sum()),
             "n_suppressed": int(sup.sum()), "n_events": len(ev), "grades": n_g}
        summary.append(s)
        box = (f"轉換 {s['n_transitions']} 筆｜超過 5σ {s['n_gt_5sigma']}｜超過 20σ {s['n_gt_20sigma']}\n"
               f"L1 標記 {s['n_l1_flagged']} 筆（實心 {s['n_flag_thr']}、空心 {s['n_flag_di_de']}、延伸 {s['n_flag_p4']}）→ 候選事件 {len(ev)} 件" + (f"（{evtxt}）" if ev else ""))
        bx.text(0.985, 0.97, box, transform=bx.transAxes, va="top", ha="right", fontsize=7.8, color=INK,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#c9c8c3", lw=0.8))
        print(json.dumps(s, ensure_ascii=False))
    handles = flag_handles(6, 5) + [
               Line2D([], [], marker="^", ls="", color=BLUE, ms=5, label="未標記（▲上升／▼下降）"),
               Line2D([], [], marker="v", ls="", color=GRAY, ms=5, label="P1 判為阻力衰減而抑制"),
               Line2D([], [], color=INK, lw=1.4, label="L1 有效門檻（高度×太陽活動×族群）"),
               Line2D([], [], color=INK2, lw=1.0, ls="--", label="20σ 高顯著下限"),
               Line2D([], [], color=INK2, lw=1.0, ls=":", label="5σ 候選下限"),
               Patch(color=GRADE_COL["E2"], alpha=0.35, label="候選事件期間（E2）")]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=7.8, frameon=False, bbox_to_anchor=(0.5, -0.005))
    fig.text(0.012, 0.945, "三種紅點皆為 L1 標記，合併為候選事件；淡紅色（P4 延伸）本身不需超過門檻，故可位於黑線甚至 5σ 線以下，且不會單獨產生事件。",
             fontsize=8.5, color=INK2, ha="left")
    fig.suptitle("半長軸變化與候選事件之關係：單步 |Δa| 須超過 L1 門檻（或多筆同向累積成連續機動段）才產生候選事件；5σ、20σ 只用於顯著性分級",
                 fontsize=10.5, color=INK, x=0.012, ha="left", y=0.995)
    fig.subplots_adjust(left=0.055, right=0.99, top=0.86, bottom=0.17)
    fig.savefig(OUT / "fig_sma_vs_events.png"); plt.close(fig)
    (OUT / "sma_vs_events.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


# ── TASA 指定 15 顆衛星（期間同交付：data/benchmark/tasa15_r7_delivery/r15.json）────────────────
TASA15_ORDER = [64199, 62190, 58651, 53056, 59711, 69018, 60548, 41634, 68831, 61871, 43081, 43797, 56193, 60507, 65316]


def _cell(fig, sub, norad, rdel, since=None):
    d0, d1 = date.fromisoformat(rdel["start_date"]), date.fromisoformat(rdel["end_date"])
    if since is not None:
        d0 = since
    r = rb.build_report_data(norad, d0, d1, lang="zh", with_ai=False, with_external=False)
    tr = r["tr_df"]
    res = ms.apply_strategies(tr, r["orbit_class"], lang="zh")
    flag = np.asarray(res["combined"], bool)
    sup = np.asarray(res["per_strategy"].get("P1_suppress", np.zeros(len(tr), bool)), bool) | \
          np.asarray(res["per_strategy"].get("P3_suppress", np.zeros(len(tr), bool)), bool)
    thr = np.asarray(res["thr_da"], float)
    df = r["tle_df"]; tt = pd.to_datetime(df["epoch"], utc=True)
    alt = (df["sma_km"] if "sma_km" in df else df["a_km"]) - RE
    te = pd.to_datetime(tr["epoch"], utc=True)
    da_m = tr["da_km"].to_numpy(float) * 1000; ad = np.abs(da_m)
    sig = r["detect_cap"]["sigma_med_m"]; s5, s20 = 5 * sig, r["detect_cap"]["min_detect_m"]
    ev = r["events"] or []
    gs = sub.subgridspec(2, 1, height_ratios=[1, 1.25], hspace=0.06)
    ax = fig.add_subplot(gs[0]); bx = fig.add_subplot(gs[1], sharex=ax)
    span = pd.Timestamp(d1, tz="UTC") - pd.Timestamp(d0, tz="UTC")
    for e in ev:
        for a in (ax, bx):
            a.axvspan(e["t_start"], max(e["t_end"], e["t_start"] + span * 0.006), color=GRADE_COL.get(e["grade"], GRAY), alpha=0.28, lw=0)
    ax.plot(tt, alt, color=BLUE, lw=0.8)
    ax.ticklabel_format(axis="y", useOffset=False, style="plain")
    other = ~flag & ~sup
    fm, fo, fp = flag_sources(tr, res, flag)
    for m, mk in ((da_m >= 0, "^"), (da_m < 0, "v")):
        bx.scatter(te[sup & m], np.maximum(ad[sup & m], 0.3), marker=mk, s=4, color=GRAY, lw=0, rasterized=True)
        bx.scatter(te[other & m], np.maximum(ad[other & m], 0.3), marker=mk, s=5, color=BLUE, lw=0, alpha=0.85, rasterized=True)
    scatter_flags(bx, te, ad, da_m, fm, fo, fp, 18, 11)
    bx.step(te, thr * 1000, where="post", color=INK, lw=1.0)
    bx.axhline(s20, color=INK2, lw=0.8, ls="--"); bx.axhline(s5, color=INK2, lw=0.8, ls=":")
    bx.set_yscale("log"); bx.set_ylim(0.3, max(ad.max(), thr.max() * 1000) * 4)
    for a in (ax, bx):
        style(a); a.tick_params(labelsize=6.5)
    plt.setp(ax.get_xticklabels(), visible=False)
    bx.xaxis.set_major_formatter(mdates.ConciseDateFormatter(bx.xaxis.get_major_locator()))
    bx.set_xlim(pd.Timestamp(d0, tz="UTC"), pd.Timestamp(d1, tz="UTC") + pd.Timedelta(days=1))
    ax.xaxis.get_offset_text().set_visible(False)
    d_first = r["tle_df"]["epoch"].min()
    n_g = {g: sum(1 for e in ev if e["grade"] == g) for g in GRADE_COL}
    evtxt = "、".join(f"{g} {k}" for g, k in n_g.items() if k)
    name = rdel["name"].replace(" 4001", "")
    d0_txt = f"首筆 {pd.Timestamp(d_first).date()}" if since is not None and pd.Timestamp(d_first).date() > d0 else f"{d0}"
    stat = (f"L1 門檻 {np.median(thr)*1000:.0f}／20σ {s20:.0f}／5σ {s5:.0f} m｜超過 5σ {int((ad > s5).sum())}、20σ {int((ad > s20).sum())} 筆\n"
            f"L1 標記 {int(flag.sum())}（實心{int(fm.sum())}／空心{int(fo.sum())}／延伸{int(fp.sum())}）→ 事件 {len(ev)} 件" + (f"（{evtxt}）" if ev else ""))
    ax.set_title(f"{name}（{norad}，{r['alt_km_avg']:.0f} km）　{d0_txt}～{d1}\n{stat}", fontsize=7.6, color=INK, loc="left", pad=2)
    s = {"norad": norad, "name": name, "d0": str(d0), "d1": str(d1), "n_transitions": int(len(tr)), "sigma_m": round(sig, 1),
         "sigma5_m": round(s5), "sigma20_m": round(s20), "l1_thr_median_m": round(float(np.median(thr)) * 1000),
         "n_gt_5sigma": int((ad > s5).sum()), "n_gt_20sigma": int((ad > s20).sum()), "n_l1_flagged": int(flag.sum()),
         "n_flag_thr": int(fm.sum()), "n_flag_di_de": int(fo.sum()), "n_flag_p4": int(fp.sum()),
         "n_flag_below_thr": int((flag & (ad < thr * 1000)).sum()), "n_flag_below_5sigma": int((flag & (ad < s5)).sum()),
         "n_events": len(ev), "grades": n_g, "grades_delivery": rdel["counts"]["grades"],
         "match_delivery": n_g == {g: rdel["counts"]["grades"].get(g, 0) for g in GRADE_COL}}
    print(json.dumps(s, ensure_ascii=False))
    return s


def tasa15(since=None, check_only=False):
    R = {int(k): v for k, v in json.loads((ROOT / "data/benchmark/tasa15_r7_delivery/r15.json").read_text(encoding="utf-8")).items()}
    pages = [TASA15_ORDER[i:i + 4] for i in range(0, 15, 4)]
    summary = []
    handles = flag_handles(5, 4) + [
               Line2D([], [], marker="^", ls="", color=BLUE, ms=4, label="未標記（▲上升／▼下降）"),
               Line2D([], [], marker="v", ls="", color=GRAY, ms=4, label="P1 判為阻力衰減而抑制"),
               Line2D([], [], color=INK, lw=1.0, label="L1 有效門檻"),
               Line2D([], [], color=INK2, lw=0.8, ls="--", label="20σ"), Line2D([], [], color=INK2, lw=0.8, ls=":", label="5σ")] + \
              [Patch(color=c, alpha=0.4, label=f"候選事件 {g}") for g, c in GRADE_COL.items()]
    for k, page in enumerate(pages, 1):
        fig = plt.figure(figsize=(13.0, 6.6), dpi=200)
        gs = fig.add_gridspec(2, 2, hspace=0.52, wspace=0.12, left=0.045, right=0.99, top=0.86, bottom=0.11)
        for i, n in enumerate(page):
            summary.append(_cell(fig, gs[i // 2, i % 2], n, R[n], since))
        fig.suptitle(f"TASA 指定 15 顆衛星：半長軸變化與候選事件，2024-01-01 起（{k}／{len(pages)}）　上：半長軸高度（km）；下：相鄰 TLE 之 |Δa|（m，對數）",
                     fontsize=10, color=INK, x=0.012, ha="left", y=0.985)
        fig.legend(handles=handles, loc="lower center", ncol=7, fontsize=7, frameon=False, bbox_to_anchor=(0.5, 0.0))
        if check_only:
            plt.close(fig); continue
        fig.savefig(OUT / f"fig_sma_vs_events_tasa15_p{k}.png"); plt.close(fig)
    if check_only:
        print("交付期間一致", sum(s["match_delivery"] for s in summary), "／", len(summary)); return
    (OUT / "sma_vs_events_tasa15.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = {k: sum(x[k] for x in summary) for k in ("n_l1_flagged", "n_flag_thr", "n_flag_di_de", "n_flag_p4", "n_flag_below_thr", "n_flag_below_5sigma")}
    print("L1 標記來源合計", tot)
    print("一致", sum(s["match_delivery"] for s in summary), "／", len(summary))


if __name__ == "__main__":
    if "--tasa15-check" in sys.argv:
        tasa15(check_only=True)
    elif "--tasa15" in sys.argv:
        tasa15(since=date(2024, 1, 1))
    else:
        main()
