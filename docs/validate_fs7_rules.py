#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_fs7_rules.py — 以福衛七號 leoOrb 精密星曆為真值，驗證 L1／證據等級之規則修正建議。

A. 真值（truth）：2024-01-01～2026-11-14 每日 leoOrb，逐月合併弧段（前後各重疊 1 天），以
   formosat7_leoorb.detect 偵測並以四項一致性檢查驗證，保留「疑似真事件」；同時記錄各星每日是否
   有精密資料（評估只在有資料之日進行）。
B. TLE 比對（每顆 FS7，限有精密資料之日）：
   (1) L1 規則：基準（R7 採用規則 B）、移除 ΔΩ、移除 P3、兩者皆移除 → 真值召回、無對應真值之事件數。
   (2) 證據等級：以完整 R7 流程（build_report_data）產生事件，比較
       現行計票：drag／ml／fusion／l2（≥2 種方法）各算一類；
       建議計票：drag 一類；ml、fusion 僅在無 drag 時才算（兩者觸發條件或輸入皆含阻力殘差）；
                 l2 需 ≥3 種方法；E3 (a) 改為「drag＋另一獨立類」。
       之各等級事件中，對應真值（±24 h）之比例。

用法：python docs/validate_fs7_rules.py [truth|eval|all]
輸出：data/benchmark/fs7_leoorb_truth_2024_2026.csv、fs7_leoorb_coverage.csv、fs7_rule_eval_*.csv
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
os.environ.setdefault("SSA_RAG_TIMEOUT_S", "1")

from formosat7_leoorb import archive, detect  # noqa: E402
from formosat7_leoorb.download import DEFAULT_CACHE_DIR, day_tag  # noqa: E402
from formosat7_leoorb.satmap import SP3_TO_NORAD, SP3_TO_NAME  # noqa: E402

OUT = ROOT / "data/benchmark"
T_PATH = OUT / "fs7_leoorb_truth_2024_2026.csv"
C_PATH = OUT / "fs7_leoorb_coverage.csv"
D0, D1 = date(2024, 1, 1), date(2026, 11, 14)
PAD = pd.Timedelta(hours=24)


def month_starts(d0, d1):
    d = date(d0.year, d0.month, 1)
    while d <= d1:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def build_truth():
    evs, cov = [], []
    for m0 in month_starts(D0, D1):
        m1 = (date(m0.year + (m0.month == 12), m0.month % 12 + 1, 1) - timedelta(days=1))
        m1 = min(m1, D1)
        paths = []
        d = m0 - timedelta(days=1)
        while d <= m1 + timedelta(days=1):
            p = DEFAULT_CACHE_DIR / f"leoOrb_{day_tag(d)}.tar.gz"
            if p.exists():
                paths.append(p)
            d += timedelta(days=1)
        if not paths:
            continue
        frames = []
        for p in paths:
            try:
                frames.append(archive.load_leoorb_tar(p, keep_unmapped=False))
            except Exception as e:  # noqa: BLE001
                print("skip", p.name, e, flush=True)
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        dd = pd.to_datetime(df["epoch"], utc=True).dt.date
        for (sat, day), _ in df.groupby([df["sp3_sat"], dd]).size().items():
            if m0 <= day <= m1:
                cov.append({"sp3_sat": sat, "norad": SP3_TO_NORAD.get(sat), "day": day})
        series = detect.build_series(df)
        ev = detect.verify(detect.detect_events(series))
        if not ev.empty:
            pk = pd.to_datetime(ev["peak_t"], utc=True).dt.date
            ev = ev[(pk >= m0) & (pk <= m1)]
            evs.append(ev)
        print(f"{m0:%Y-%m}：每日包 {len(paths)}，候選 {len(ev)}，通過 {int((ev['verdict']=='疑似真事件').sum()) if len(ev) else 0}",
              flush=True)
        del df, frames, series
    E = pd.concat(evs, ignore_index=True) if evs else pd.DataFrame()
    E["norad"] = E["sp3_sat"].map(SP3_TO_NORAD)
    E.to_csv(T_PATH, index=False, encoding="utf-8-sig")
    pd.DataFrame(cov).drop_duplicates().to_csv(C_PATH, index=False, encoding="utf-8-sig")
    print("truth events", len(E), "verified", int((E["verdict"] == "疑似真事件").sum()))


# ── B. 評估 ──────────────────────────────────────────────────────────────────
def regrade(e, scheme, in_domain=False, l2set=None):
    """依計票方式重給等級（沿用 assess_events 之顯著性、型態、量級、空窗、回跳判定）。"""
    if e["grade"] == "D":
        return "D"
    ev = set(e["evidence"])
    if scheme == "current":
        return e["grade"]
    ind = set()
    if "drag" in ev:
        ind.add("drag")
    if "ml" in ev and "drag" not in ev:
        ind.add("ml")
    if "fusion" in ev and "drag" not in ev and in_domain:
        ind.add("fusion")
    l2set = l2set or set()
    if scheme == "proposed" and e.get("n_l2_channels", 0) >= 3:
        ind.add("l2")
    elif scheme == "ml_dedupe" and len(l2set) >= 2:
        ind.add("l2")
    elif scheme == "ml_dedupe_bocpd" and "bocpd" in l2set and len(l2set) >= 2:
        ind.add("l2")
    # scheme == "ml_dedupe_nol2"：L2 不計入通道
    sigf = e.get("significance")
    big = abs(e["net_da"]) >= 10.0
    seg = e.get("ev_type") == "連續機動段"
    if e.get("quality_note") or sigf == "低":
        g = "E1"
    elif sigf == "高" and (seg or big):
        g = "E3"
    elif sigf == "高" and "drag" in ind and len(ind) >= 2:
        g = "E3"
    elif len(ind) >= 2:
        g = "E2"
    else:
        g = "E1"
    if e.get("gap_drag"):
        g = "E1"
    elif (e.get("gap_d") or 0) >= 7 and g == "E3":
        g = "E2"
    return g


def evaluate():
    import maneuver_report_builder as rb
    import eval_l1_combination as ec
    import eval_rule_ablation as ea
    T = pd.read_csv(T_PATH, parse_dates=["t_start", "t_end", "peak_t"])
    T = T[T["verdict"] == "疑似真事件"].copy()
    C = pd.read_csv(C_PATH, parse_dates=["day"])
    rows_l1, rows_ev = [], []
    for sp3, nid in SP3_TO_NORAD.items():
        cov_days = set(pd.to_datetime(C.loc[C["norad"] == nid, "day"]).dt.date)
        if not cov_days:
            continue
        tr_ev = T[T["norad"] == nid]
        truth = [(pd.Timestamp(a), pd.Timestamp(b), abs(s)) for a, b, s in zip(tr_ev["t_start"], tr_ev["t_end"], tr_ev["step_m"])]
        d0, d1 = min(cov_days), max(cov_days)
        p = ec.prep(nid, pd.Timestamp(d0, tz="UTC"), pd.Timestamp(d1, tz="UTC") + pd.Timedelta(days=1))
        if p is None:
            continue
        df, tr, oc = p
        sigma_m = (rb.detection_capability(tr, ea.combine(tr, oc, set()), []) or {}).get("sigma_med_m", np.nan)
        incov = lambda t: pd.Timestamp(t).date() in cov_days
        near = lambda e: any(a - PAD <= e["t_end"] and e["t_start"] <= b + PAD for a, b, _ in truth)
        for name, drop in (("基準 B", set()), ("移除 ΔΩ", {"draan"}), ("移除 P3", {"P3"}), ("移除 ΔΩ＋P3", {"draan", "P3"})):
            ev = ec.events_for(df, tr, ea.combine(tr, oc, drop))
            ev = [e for e in ev if incov(e["t_start"]) and incov(e["t_end"])]
            for thr_lab, thr_m in (("全部", 0), ("≥5σ", 5 * sigma_m), ("≥20σ", 20 * sigma_m)):
                tt = [x for x in truth if x[2] >= thr_m]
                rows_l1.append({"norad": nid, "sat": SP3_TO_NAME[sp3], "rule": name, "truth_bin": thr_lab,
                                "n_truth": len(tt),
                                "recall": sum(any(e["t_start"] - PAD <= b and a <= e["t_end"] + PAD for e in ev) for a, b, _ in tt),
                                "n_ev": len(ev), "n_ev_unmatched": sum(not near(e) for e in ev),
                                "cov_days": len(cov_days), "sigma_m": sigma_m})
        r = rb.build_report_data(int(nid), d0, d1)
        l2t = ea.l2_times(r_df := rb.load_tle(int(nid)).pipe(lambda x: x[(x["epoch"].dt.date >= d0) & (x["epoch"].dt.date <= d1)]
                                                          .sort_values("epoch", kind="stable").reset_index(drop=True)))
        for e in r.get("events") or []:
            if not (incov(e["t_start"]) and incov(e["t_end"])):
                continue
            rows_ev.append({"norad": nid, "sat": SP3_TO_NAME[sp3], "t_start": e["t_start"], "net_da": e["net_da"],
                            "evidence": "+".join(e["evidence"]), "n_l2": e.get("n_l2_channels"),
                            "grade_current": regrade(e, "current"), "grade_proposed": regrade(e, "proposed"),
                            **{f"grade_{sc}": regrade(e, sc, l2set=ea.l2_votes([e], l2t)[0])
                               for sc in ("ml_dedupe", "ml_dedupe_bocpd", "ml_dedupe_nol2")},
                            "matched": near(e)})
        print("eval", SP3_TO_NAME[sp3], flush=True)
    L1 = pd.DataFrame(rows_l1); EV = pd.DataFrame(rows_ev)
    L1.to_csv(OUT / "fs7_rule_eval_l1.csv", index=False, encoding="utf-8-sig")
    EV.to_csv(OUT / "fs7_rule_eval_grades.csv", index=False, encoding="utf-8-sig")
    print("\n=== L1 規則（6 顆 FS7 合計，限有精密資料之日）===")
    g = L1.groupby(["rule", "truth_bin"])[["n_truth", "recall", "n_ev", "n_ev_unmatched"]].sum()
    print(g.to_string())
    print("\n=== 證據等級：各等級事件對應真值之比例 ===")
    for col in ("grade_current", "grade_proposed", "grade_ml_dedupe", "grade_ml_dedupe_bocpd", "grade_ml_dedupe_nol2"):
        t = EV.groupby(col)["matched"].agg(["count", "sum"])
        t["比例"] = (t["sum"] / t["count"]).round(3)
        print(col); print(t.to_string())


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("truth", "all"):
        build_truth()
    if which in ("eval", "all"):
        evaluate()
