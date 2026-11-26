# -*- coding: utf-8 -*-
"""gen_tasa_reply_20261126_sk_figs.py — TASA 2026-11-26 追問：平緩維持機動（日常軌道維持）之 R7 偵測案例

四例，期間同來信圖（2026-05-18 至 2026-08-16）：
  ICEYE-X33（來信圖例）、STARLINK-31557（MEME 真值）、KUIPER-00188（非 Starlink 電推，運作高度）、ONEWEB-0687（非 Starlink 電推）
R7：maneuver_report_builder.build_report_data()（與 App 主結果、PDF 報表同一函式）。
註：本地 DB 之 sat_n2yo_metadata 名稱欄為 name_en，satellite_name() 查 name 欄而回傳 None；離線執行（with_external=False）時
    Starlink 會被當成非 Starlink。本程式以已知名稱代入，使 Starlink 之 ML／融合通道照 App 線上行為啟用。
輸出：docs/tasa_reply_20261126/fig_sk_cases.png、sk_cases.json
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
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
sys.stdout.reconfigure(encoding="utf-8")
import maneuver_report_builder as rb  # noqa: E402
from maneuver_strategies_july import DEFAULT_P2  # noqa: E402

OUT = ROOT / "docs" / "tasa_reply_20261126"
OUT.mkdir(parents=True, exist_ok=True)
RE = 6378.137
D0, D1 = date(2026, 5, 18), date(2026, 8, 16)
STEP_KM = 0.08     # 標示用：相鄰 TLE 正向抬升 > 80 m
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"

# 代號, 名稱, 說明, 是否標示正向跳升, 維持期起日（之前為入軌／降軌之大幅變化，另行標註）
CASES = [
    (60548, "ICEYE-X33", "來信圖例（推進方式未查證）", True, None),
    (59357, "STARLINK-31557", "Starlink 電推，運作高度", False, None),
    (67142, "KUIPER-00188", "非 Starlink 電推，運作高度", True, date(2026, 5, 28)),
    (61595, "ONEWEB-0687", "非 Starlink 電推，運作高度", False, None),
]


def meme_frac(norad):
    t = pd.read_csv(ROOT / "data/meme_truth/transitions_full_20260918.csv", usecols=["norad_id", "t_from", "t_to", "label_meme"])
    t = t[t.norad_id == norad].copy()
    t["t0"] = pd.to_datetime(t.t_from, utc=True); t["t1"] = pd.to_datetime(t.t_to, utc=True)
    t = t[(t.t0.dt.date >= D0) & (t.t0.dt.date <= D1)]
    return t, (float(t.label_meme.mean()) if len(t) else None)


def run(norad, name):
    rb.satellite_name = lambda _n, nm=name: nm
    r = rb.build_report_data(norad, D0, D1, lang="zh", with_ai=False, with_external=False)
    df = r["tle_df"]
    tt = pd.to_datetime(df["epoch"], utc=True)
    alt = (df["sma_km"] if "sma_km" in df else df["a_km"]) - RE
    d = alt.diff()
    up = d > STEP_KM
    alt_avg = float(alt.median())
    dc = r.get("detect_cap") or {}
    s = {"norad": norad, "name": name, "alt_km": round(alt_avg, 1), "n_tle": int(len(df)),
         "alt_range_km": round(float(alt.max() - alt.min()), 3),
         "l1_thr_km": round(float(DEFAULT_P2(alt_avg)), 2),
         "sigma_m": round(dc.get("sigma_med_m", np.nan), 1), "sigma5_m": round(5 * dc.get("sigma_med_m", np.nan)), "sigma20_m": round(dc.get("min_detect_m", np.nan)),
         # detect_cap["min_detect_m"] 為 SNR_HIGH（20）× σ，即 20σ 高顯著下限，不是 5σ
         "max_step_km": round(float(d.abs().max()), 3),
         "n_up_steps_gt80m": int(up.sum()), "up_steps": [(str(a.date()), round(float(b), 3)) for a, b in zip(tt[up], d[up])],
         "n_events": len(r["events"] or []), "grades": r["counts"]["grades"],
         "n_low_conf": len(r["low_conf"] or []), "low_conf": [(str(pd.Timestamp(x["epoch"]).date()), x["source"], x["value"]) for x in r["low_conf"] or []],
         "fusion_suppressed_non_starlink": (r.get("low_conf_suppressed") or {}).get("fusion_non_starlink", 0),
         "l2_counts": {k: v.get("n_events") for k, v in (r.get("l2") or {}).items() if isinstance(v, dict)},
         "fusion_max": round(float(r["fusion_df"]["fusion"].max()), 3) if r.get("fusion_df") is not None and len(r["fusion_df"]) else None}
    return r, tt, alt, up, d, s


def main():
    fig, axes = plt.subplots(4, 1, figsize=(9.6, 11.2), dpi=200, sharex=True)
    summary = []
    for ax, (norad, name, note, mark_up, sk0) in zip(axes, CASES):
        r, tt, alt, up, d, s = run(norad, name)
        ax.plot(tt, alt, color=BLUE, lw=1.0, marker=".", ms=2.4)
        if sk0 is not None:
            m = (tt.dt.date >= sk0).to_numpy()
            up = up & m
            s.update(sk_start=str(sk0), sk_alt_range_km=round(float(alt[m].max() - alt[m].min()), 3),
                     sk_max_step_km=round(float(d[m].abs().max()), 3), sk_n_events=sum(1 for e in r["events"] or [] if e["t_start"].date() >= sk0),
                     sk_up_steps=[(str(a.date()), round(float(b), 3)) for a, b in zip(tt[up], d[up])])
            pad = 0.15 * (alt[m].max() - alt[m].min())
            ax.set_ylim(alt[m].min() - pad, alt[m].max() + 2.2 * pad)
            ax.annotate(f"5/20–5/27 由 640 km 降至 629.5 km（超出圖幅）\nR7 候選事件 {s['n_events'] - s['sk_n_events']} 件（E2）",
                        xy=(pd.Timestamp("2026-06-17", tz="UTC"), alt[m].max() + 1.5 * pad), fontsize=7.5, color="#b0127f", va="center")
        if mark_up and up.any():
            ax.scatter(tt[up], alt[up], marker="^", s=26, color=ORANGE, zorder=3, label=f"相鄰 TLE 正向跳升 > 80 m（{int(up.sum())} 次）")
        for e in r["events"] or []:
            ax.axvspan(e["t_start"], e["t_end"], color="#b0127f", alpha=0.18, lw=0)
        for i, x in enumerate(r["low_conf"] or []):
            ax.axvline(pd.Timestamp(x["epoch"]), color="#3f6fb5", lw=0.9, ls=":", label="低置信複核項（融合評分器）" if i == 0 else None)
        if name.startswith("STARLINK"):
            t, fr = meme_frac(norad)
            s["meme_maneuver_frac"] = round(fr, 3) if fr is not None else None
            lo = alt.min() - 0.05 * (alt.max() - alt.min() + 0.05)
            for x in t[t.label_meme == 1].itertuples():
                ax.plot([x.t0, x.t1], [lo, lo], color=INK, lw=3, solid_capstyle="butt")
            ax.plot([], [], color=INK, lw=3, label=f"MEME 真值機動時段（占 {fr:.0%}）")
        ax.ticklabel_format(axis="y", useOffset=False, style="plain")
        ax.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
        for sp in ("top", "right"): ax.spines[sp].set_visible(False)
        ax.tick_params(colors=INK2, labelsize=8)
        ax.set_ylabel("高度（km）", fontsize=8.5, color=INK2)
        if sk0 is not None:
            s_max = f"維持期最大單步 {s['sk_max_step_km']*1000:.0f} m"
        else:
            s_max = f"期間最大單步 {s['max_step_km']*1000:.0f} m"
        lc = f"、低置信複核項 {s['n_low_conf']} 項" if s["n_low_conf"] else "、低置信複核項 0"
        ax.set_title(f"{name}（NORAD {norad}）｜{note}｜約 {s['alt_km']:.0f} km\n"
                     f"R7 候選事件 {s['n_events']} 件{lc}｜L1 高度門檻約 {s['l1_thr_km']:.2f} km｜"
                     f"σ {s['sigma_m']:.1f} m（5σ {s['sigma5_m']:.0f} m、20σ {s['sigma20_m']:.0f} m）｜{s_max}",
                     fontsize=9, color=INK, loc="left")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="best", fontsize=7.5, frameon=True, framealpha=0.9, edgecolor="none")
        summary.append(s)
        print(json.dumps(s, ensure_ascii=False))
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[-1].xaxis.get_major_locator()))
    axes[-1].set_xlim(pd.Timestamp(D0, tz="UTC"), pd.Timestamp(D1, tz="UTC") + pd.Timedelta(days=1))
    fig.suptitle("平緩維持機動之 R7 偵測結果（TLE 平均半長軸高度，2026-05-18 至 08-16）", fontsize=11, color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(OUT / "fig_sk_cases.png"); plt.close(fig)
    (OUT / "sk_cases.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def sigma_band():
    """ICEYE-X33 之 TLE 雜訊與同高度層（540–590 km）物件比較；σ 定義同 detection_capability（未標記轉換逐月穩健標準差之中位數）。
    未標記以 L1 高度門檻近似（不含 P5／P6 倍率與 P1 抑制）；ICEYE-X33 以此法重算為 8.13 m，與 R7 值相同。"""
    import duckdb
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    df = con.execute("""SELECT norad_id, object_name, epoch_utc, sma_km FROM raw_tle_archive
        WHERE epoch_utc >= ? AND epoch_utc < ? AND sma_km BETWEEN ? AND ? AND eccentricity < 0.005""",
        [str(D0), str(D1 + pd.Timedelta(days=1)), RE + 530, RE + 600]).fetchdf()
    con.close()
    df = df.sort_values(["norad_id", "epoch_utc"]); df["epoch_utc"] = pd.to_datetime(df.epoch_utc)
    df = df[df.groupby("norad_id").epoch_utc.diff().dt.total_seconds().fillna(9e9) >= 1]
    rows = []
    for n, g in df.groupby("norad_id"):
        alt = g.sma_km.median() - RE
        if len(g) < 40 or not 540 <= alt <= 590:
            continue
        da = g.sma_km.diff().to_numpy()[1:]; m = g.epoch_utc.iloc[1:].dt.strftime("%Y-%m").to_numpy()
        ok = np.abs(da) <= float(DEFAULT_P2(alt))
        sig = [x for mm in np.unique(m[ok]) if np.isfinite(x := rb._robust_sigma(da[ok][m[ok] == mm]))]
        if sig:
            nm = str(g.object_name.iloc[-1]).replace("0 ", "", 1).strip()
            rows.append(dict(norad=int(n), name=nm, alt=float(alt), n_tle=len(g), sigma_m=float(np.median(sig)) * 1000))
    r = pd.DataFrame(rows)
    u = r.name.str.upper()
    r["cls"] = np.where(u.str.startswith("STARLINK"), "Starlink",
                        np.where(u.str.contains(" DEB|R/B", regex=True), "碎片／火箭體", "其他酬載"))
    r.to_csv(OUT / "sigma_band_540_590km.csv", index=False, encoding="utf-8-sig")
    ice = float(r.loc[r.norad == 60548, "sigma_m"].iloc[0])
    stat = {"ICEYE-X33_sigma_m": round(ice, 2), "band": "540–590 km", "period": f"{D0}–{D1}"}
    for c, g in [("全部", r)] + list(r.groupby("cls")) + [("ICEYE 系列", r[u.str.startswith("ICEYE")])]:
        stat[c] = {"n": int(len(g)), "p25": round(g.sigma_m.quantile(.25), 1), "p50": round(g.sigma_m.median(), 1),
                   "p75": round(g.sigma_m.quantile(.75), 1), "iceye_x33_pct": round(float((g.sigma_m < ice).mean() * 100))}
    (OUT / "sigma_band.json").write_text(json.dumps(stat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stat, ensure_ascii=False))
    fig, ax = plt.subplots(figsize=(9.6, 4.2), dpi=200)
    bins = np.logspace(np.log10(0.8), np.log10(400), 46)
    cols = {"Starlink": "#2a78d6", "其他酬載": "#eb6834", "碎片／火箭體": "#8a8984"}
    for c in ("Starlink", "其他酬載", "碎片／火箭體"):
        g = r[r.cls == c]
        ax.hist(g.sigma_m, bins=bins, histtype="step", lw=1.6, color=cols[c], label=f"{c}（{len(g)}；中位 {g.sigma_m.median():.1f} m）")
    ic = r[u.str.startswith("ICEYE")]
    ax.scatter(ic.sigma_m, np.full(len(ic), -6), marker="|", s=60, color=INK, label=f"ICEYE 系列（{len(ic)}；中位 {ic.sigma_m.median():.1f} m）", clip_on=False)
    ax.axvline(ice, color="#b0127f", lw=1.8)
    ax.text(ice * 1.06, ax.get_ylim()[1] * 0.92, f"ICEYE-X33\nσ = {ice:.1f} m", color="#b0127f", fontsize=8.5, va="top")
    thr = float(DEFAULT_P2(564.1)) * 1000
    ax.axvline(thr / 20, color=INK2, lw=1, ls="--")
    ax.text(thr / 20 * 1.06, ax.get_ylim()[1] * 0.55, f"σ = {thr/20:.0f} m\n（564 km 之 L1 門檻 {thr:.0f} m\n＝ 20σ）", fontsize=7.5, color=INK2, va="top")
    ax.set_xscale("log"); ax.set_xlim(0.8, 400); ax.set_ylim(bottom=-10)
    ax.set_xticks([1, 2, 5, 10, 20, 50, 100, 200]); ax.set_xticklabels(["1", "2", "5", "10", "20", "50", "100", "200"])
    ax.set_xlabel("TLE 逐筆雜訊 σ（m，對數刻度）", fontsize=8.5, color=INK2); ax.set_ylabel("物件數", fontsize=8.5, color=INK2)
    ax.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.legend(fontsize=7.5, frameon=False, loc="upper right")
    ax.set_title(f"同高度層（540–590 km）物件之 TLE 雜訊（{D0} 至 {D1}，共 {len(r)} 個）", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); fig.savefig(OUT / "fig_sigma_band.png"); plt.close(fig)


if __name__ == "__main__":
    main()
    sigma_band()
