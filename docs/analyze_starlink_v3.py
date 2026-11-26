# -*- coding: utf-8 -*-
"""analyze_starlink_v3.py — Starlink V3 入軌後軌道行為與 R7 偵測結果（期末報告獨立章節用）

流程（逐星）：
  1. 由 TLE 日中位高度切分軌道階段：入軌 → 暫駐高度（~316 km）→ 運作高度（~345 km）。
     抵達日＝日中位高度首次 ≥ 門檻之日；暫駐天數＝首次 ≥ 314 km 至首次 ≥ 344 km 之日數。
  2. 以 R7 單星報表流程（maneuver_report_builder.build_report_data）產生候選事件、證據等級、低置信複核項。
  3. 比對每段爬升是否被 L1 候選事件或低置信複核項涵蓋。
輸出：data/benchmark/starlink_v3_<tag>/{sats.csv, events.csv, lowconf.csv, fleet.json}
      docs/fig_starlink_v3_profile.png（報告用）；--pub 另輸出 docs/figures_pub/fig_starlink_v3_profile/ 四版本
用法：python docs/analyze_starlink_v3.py [--norads 100855-100880,...] [--tag batch1] [--end 2026-11-18] [--pub]
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
os.environ.setdefault("SSA_RAG_TIMEOUT_S", "1")
import maneuver_report_builder as rb  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RE = 6378.137
STAGE_KM, OPER_KM = 314.0, 344.0
PAD = pd.Timedelta(hours=24)
GRADE_COL = {"E3": "#B0127F", "E2": "#EF6C00", "E1": "#1565C0", "D": "#8A8984"}   # E3 紫紅、D 灰（2026-11-25 依使用者要求，與 E2 區隔）


def parse_norads(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def load(con, nid, end=None):
    """end：分析截止日（含當日）。2026-11-26 補：原未截斷，資料續增後 raan_now、運作期星日數等會用到截止日以後之 TLE。"""
    q = "SELECT epoch_utc AS epoch, object_name, sma_km, inclination_deg AS inc, raan_deg AS raan FROM raw_tle_archive WHERE norad_id=?"
    args = [nid]
    if end is not None:
        q += " AND epoch_utc < ?"
        args.append((pd.Timestamp(end) + pd.Timedelta(days=1)).to_pydatetime())
    df = con.execute(q + " ORDER BY epoch_utc", args).fetchdf()
    df["epoch"] = pd.to_datetime(df.epoch, utc=True)
    df = df.drop_duplicates("epoch").reset_index(drop=True)
    df["alt"] = df.sma_km - RE
    return df


def phases(df):
    d = df.set_index("epoch").alt.resample("1D").median().dropna()
    t0 = d.index[0]
    hit = lambda thr: (d[d >= thr].index[0] if (d >= thr).any() else None)  # noqa: E731
    t_stage, t_oper = hit(STAGE_KM), hit(OPER_KM)
    after = d[d.index >= t_oper] if t_oper is not None else d.iloc[0:0]
    return dict(t_first=t0, alt_first=float(d.iloc[0]), t_stage=t_stage, t_oper=t_oper,
                days_to_stage=(t_stage - t0).days if t_stage is not None else None,
                dwell_stage_d=(t_oper - t_stage).days if (t_stage is not None and t_oper is not None) else None,
                days_to_oper=(t_oper - t0).days if t_oper is not None else None,
                alt_now=float(df.alt.iloc[-1]),
                oper_std_m=float(after.std() * 1000) if len(after) > 3 else None,
                oper_range_km=float(after.max() - after.min()) if len(after) > 3 else None), d


def covered(t0, t1, ev, lc):
    l1 = [e for e in ev if e["t_start"] - PAD <= t1 and t0 <= e["t_end"] + PAD]
    l2 = [x for x in lc if t0 - PAD <= x["epoch"] <= t1 + PAD]
    return l1, l2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--norads", default="100855-100880")
    ap.add_argument("--tag", default="batch1")
    ap.add_argument("--end", default=str(date.today()))
    ap.add_argument("--pub", action="store_true")
    ap.add_argument("--plot-only", action="store_true")
    a = ap.parse_args()
    out = ROOT / "data" / "benchmark" / f"starlink_v3_{a.tag}"
    out.mkdir(parents=True, exist_ok=True)
    norads = parse_norads(a.norads)
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    end = date.fromisoformat(a.end)
    series = {}
    if not a.plot_only:
        S, E, L = [], [], []
        for k, nid in enumerate(norads, 1):
            df = load(con, nid, end)
            if df.empty:
                print("無 TLE", nid)
                continue
            ph, d = phases(df)
            series[nid] = d
            r = rb.build_report_data(nid, df.epoch.min().date(), end, with_ai=False, with_external=False)
            ev, lc = r.get("events") or [], r.get("low_conf") or []
            name = str(df.object_name.iloc[0]).replace("0 ", "", 1).strip()
            row = dict(norad=nid, name=name, n_tle=len(df), inc=float(df.inc.median()), raan_now=float(df.raan.iloc[-1]),
                       **{k2: (str(v.date()) if isinstance(v, pd.Timestamp) else v) for k2, v in ph.items()},
                       n_ev=len(ev), **{f"n_{g}": sum(e["grade"].startswith(g) for e in ev) for g in ("E3", "E2", "E1", "D")},
                       n_lc=len(lc), n_lc_drag=sum(x["source"] == "阻力殘差" for x in lc),
                       n_lc_l2=sum(x["source"].startswith("L2") for x in lc),
                       n_lc_fus=sum("融合" in x["source"] for x in lc),
                       sigma_m=float(ev[0]["sigma_km"] * 1000) if ev else None)
            # 運作高度之阻力補償：抵達運作高度 2 天後，實測 Δa 與 NRLMSIS 模型 Δa 之日均率
            dd = r.get("drag_df")
            if dd is not None and len(dd) and ph["t_oper"] is not None:
                dd = dd[dd.epoch >= ph["t_oper"] + pd.Timedelta(days=2)]
                span = (dd.epoch.max() - dd.epoch.min()).total_seconds() / 86400 if len(dd) > 3 else 0
                if span > 5:
                    row["oper_obs_rate_m_d"] = float(dd.da_km.sum() / span * 1000)
                    row["oper_model_rate_m_d"] = float((dd.da_km - dd.drag_resid_da).sum() / span * 1000)
                    row["oper_span_d"] = span
                    row["oper_lc_drag"] = sum(x["source"] == "阻力殘差" and x["epoch"] >= ph["t_oper"] for x in lc)
            # 各爬升段之涵蓋
            segs = []
            if ph["t_stage"] is not None:
                segs.append(("insert_to_stage", ph["t_first"], ph["t_stage"]))
            if ph["t_stage"] is not None and ph["t_oper"] is not None:
                t_leave = d[(d.index < ph["t_oper"]) & (d < STAGE_KM + 6)].index.max()
                segs.append(("stage_to_oper", t_leave, ph["t_oper"]))
            for sname, t0, t1 in segs:
                l1, l2 = covered(t0, t1 + pd.Timedelta(days=1), ev, lc)
                row[f"{sname}_dalt_km"] = float(d[t1] - d[t0])
                row[f"{sname}_l1"] = len(l1)
                row[f"{sname}_l1_netda_km"] = float(sum(e["net_da"] for e in l1))
                row[f"{sname}_l1_grades"] = "|".join(e["grade"] for e in l1)
                row[f"{sname}_lc"] = len(l2)
            S.append(row)
            for e in ev:
                E.append(dict(norad=nid, name=name, t_start=e["t_start"], t_end=e["t_end"], net_da=e["net_da"],
                              grade=e["grade"], ev_type=e["ev_type"], snr=e["snr"], e3_basis=e.get("e3_basis"),
                              ml_capped=e.get("ml_capped"), segment=e.get("segment"), checks=e.get("checks")))
            for x in lc:
                L.append(dict(norad=nid, name=name, epoch=x["epoch"], source=x["source"], value=x["value"],
                              peak=x["peak"], priority=x["priority"], tags="|".join(x.get("tags") or [])))
            print(k, nid, name, {kk: row[kk] for kk in ("days_to_stage", "dwell_stage_d", "days_to_oper", "n_ev", "n_lc")},
                  flush=True)
        pd.DataFrame(S).to_csv(out / "sats.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(E).to_csv(out / "events.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(L).to_csv(out / "lowconf.csv", index=False, encoding="utf-8-sig")
        Sd = pd.DataFrame(S)
        for col in ("oper_obs_rate_m_d", "oper_model_rate_m_d", "oper_lc_drag", "oper_span_d", "oper_std_m", "days_to_oper", "dwell_stage_d"):
            if col not in Sd:
                Sd[col] = np.nan   # 新批次尚未抵達運作高度時無此欄
        fleet = dict(n=len(Sd), end=a.end, raan_now_min=float(Sd.raan_now.min()), raan_now_max=float(Sd.raan_now.max()),
                     raan_now_median=float(Sd.raan_now.median()), inc_median=float(Sd.inc.median()),
                     alt_first_range=[float(Sd.alt_first.min()), float(Sd.alt_first.max())],
                     days_to_oper_median=float(Sd.days_to_oper.median()),
                     days_to_oper_range=[float(Sd.days_to_oper.min()), float(Sd.days_to_oper.max())],
                     dwell_stage_median=float(Sd.dwell_stage_d.median()),
                     dwell_stage_range=[float(Sd.dwell_stage_d.min()), float(Sd.dwell_stage_d.max())],
                     oper_std_m_median=float(Sd.oper_std_m.median()),
                     oper_obs_rate_m_d_median=float(Sd.oper_obs_rate_m_d.median()),
                     oper_model_rate_m_d_median=float(Sd.oper_model_rate_m_d.median()),
                     oper_model_rate_m_d_range=[float(Sd.oper_model_rate_m_d.min()), float(Sd.oper_model_rate_m_d.max())],
                     oper_lc_drag=int(Sd.oper_lc_drag.sum()), oper_sat_days=float(Sd.oper_span_d.sum()),
                     n_ev=int(Sd.n_ev.sum()), grades={g: int(Sd[f"n_{g}"].sum()) for g in ("E3", "E2", "E1", "D")},
                     n_lc=int(Sd.n_lc.sum()), n_lc_drag=int(Sd.n_lc_drag.sum()), n_lc_l2=int(Sd.n_lc_l2.sum()),
                     n_lc_fus=int(Sd.n_lc_fus.sum()))
        (out / "fleet.json").write_text(json.dumps(fleet, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(fleet, ensure_ascii=False, indent=2))
    else:
        for nid in norads:
            df = load(con, nid, end)
            if not df.empty:
                series[nid] = phases(df)[1]
    plot(series, out, a.pub, a.tag)


TXT = {
    "zh": dict(title="Starlink V3 {batch}（{n} 顆）入軌後高度與 R7 偵測結果",
               a="(a) 日中位高度", b="(b) 各星候選事件（實心，依證據等級著色）與低置信複核項（空心）",
               ylab="平均高度（km）", lag="暫駐較久之 2 顆", others="其餘 {k} 顆",
               stage="暫駐高度約 316 km", oper="運作高度約 345 km", lc="低置信複核項", ylab2="衛星（依抵達運作高度之日排序；未抵達者依編號）"),
    "en": dict(title="Starlink V3 {batch} ({n} satellites): post-insertion altitude and R7 detections",
               a="(a) Daily median altitude", b="(b) Candidate events (filled, by evidence grade) and low-confidence review items (hollow)",
               ylab="Mean altitude (km)", lag="2 satellites with longer staging", others="Other {k}",
               stage="Staging altitude ≈316 km", oper="Operational altitude ≈345 km", lc="Low-confidence item",
               ylab2="Satellite (by arrival at operational altitude; others by NORAD)"),
}
THEME = {"light": dict(bg="white", fg="black", grid="#D0D0D0", grey="#9E9E9E"),
         "dark": dict(bg="black", fg="white", grid="#444444", grey="#8A8A8A")}


BATCH = {"batch1": ("第一批", "batch 1"), "batch2": ("第二批", "batch 2")}


def draw(series, out, lang="zh", theme="light", tag="batch1"):
    t, th = dict(TXT[lang]), THEME[theme]
    font = ["Microsoft JhengHei", "Microsoft YaHei", "sans-serif"] if lang == "zh" else ["Arial", "DejaVu Sans"]
    S = pd.read_csv(out / "sats.csv")
    E = pd.read_csv(out / "events.csv", parse_dates=["t_start", "t_end"])
    L = pd.read_csv(out / "lowconf.csv", parse_dates=["epoch"])
    lag = set(S.loc[S.dwell_stage_d >= 14, "norad"])
    bz, be = BATCH.get(tag, (tag, tag))
    t["title"] = t["title"].format(batch=bz if lang == "zh" else be, n=len(S))
    t["others"] = t["others"].format(k=len(series) - len(lag))
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "figure.facecolor": th["bg"],
                         "axes.facecolor": th["bg"], "savefig.facecolor": th["bg"], "text.color": th["fg"],
                         "axes.labelcolor": th["fg"], "xtick.color": th["fg"], "ytick.color": th["fg"],
                         "axes.edgecolor": th["fg"], "legend.facecolor": th["bg"], "legend.edgecolor": th["grid"],
                         "legend.labelcolor": th["fg"]})
    if True:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.6), sharex=True, gridspec_kw=dict(height_ratios=[1, 1.25]))
        first = True
        for nid, d in series.items():
            if nid in lag:
                continue
            ax1.plot(d.index, d.values, color=th["grey"], lw=0.9, alpha=0.8, label=t["others"] if first else None)
            first = False
        lc_cols = ["#00ACC1", "#FDD835"]
        for c, nid in zip(lc_cols, sorted(lag)):
            d = series[nid]
            nm = S.loc[S.norad == nid, "name"].iloc[0]
            ax1.plot(d.index, d.values, color=c, lw=2.0, label=f"{nm}（{nid}）" if lang == "zh" else f"{nm} ({nid})")
        for y, lab in ((316, t["stage"]), (345.5, t["oper"])):
            ax1.axhline(y, color=th["fg"], ls=":", lw=0.8)
            ax1.text(list(series.values())[0].index[0], y + 1.2, lab, fontsize=9, color=th["fg"])
        ax1.set_ylabel(t["ylab"])
        ax1.set_title(t["a"], loc="left", fontsize=11)
        ax1.grid(color=th["grid"], lw=0.5)
        ax1.legend(loc="lower right", fontsize=8.5)
        order = S.sort_values(["t_oper", "norad"])["norad"].tolist()
        ypos = {n: i for i, n in enumerate(order)}
        for _, e in E.iterrows():
            g = str(e.grade)[:2] if str(e.grade).startswith("E") else "D"
            ax2.plot([e.t_start, e.t_end], [ypos[e.norad]] * 2, color=GRADE_COL[g], lw=5, solid_capstyle="round")
            ax2.scatter(e.t_start, ypos[e.norad], s=26, color=GRADE_COL[g], zorder=3)
        ax2.scatter(L.epoch, [ypos[n] for n in L.norad], s=22, facecolors="none", edgecolors=th["fg"], lw=0.8, zorder=2)
        ax2.set_yticks(range(len(order)))
        ax2.set_yticklabels([str(n) for n in order], fontsize=7)
        ax2.set_ylabel(t["ylab2"], fontsize=9)
        ax2.set_title(t["b"], loc="left", fontsize=11)
        ax2.grid(color=th["grid"], lw=0.5, axis="x")
        hs = [plt.Line2D([], [], color=GRADE_COL[g], lw=5, label=g) for g in ("E3", "E2", "E1", "D")]
        hs.append(plt.Line2D([], [], marker="o", ls="", mfc="none", mec=th["fg"], label=t["lc"]))
        ax2.legend(handles=hs, loc="upper center", bbox_to_anchor=(0.5, -0.06), fontsize=8.5, ncol=5, frameon=False)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        fig.suptitle(t["title"], fontsize=13.5, fontweight="bold")
        fig.tight_layout()
    return fig


def plot(series, out, pub, tag="batch1"):
    # 第一批之檔名為期末報告圖 20 所用，其他批次另存，不覆蓋
    stem0 = "fig_starlink_v3_profile" if tag == "batch1" else f"fig_starlink_v3_profile_{tag}"
    fig = draw(series, out, tag=tag)
    fig.savefig(DOCS / f"{stem0}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    if pub:
        pdir = DOCS / "figures_pub" / stem0
        pdir.mkdir(parents=True, exist_ok=True)
        for lang in ("zh", "en"):
            for theme in ("light", "dark"):
                fig = draw(series, out, lang, theme, tag)
                stem = pdir / f"{stem0}_{lang}_{theme}"
                fig.savefig(stem.with_suffix(".png"), dpi=600, bbox_inches="tight")
                fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
                plt.close(fig)
    print("圖已輸出")


if __name__ == "__main__":
    main()
