#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_shenlong_2026_rpo.py — 以公開 TLE 獨立查證 LeoLabs 2026 神龍 RPO 報告。

物件（已由國際標識碼確認）：
  太空梭 PRC Test Spacecraft 4 = NORAD 67689（2026-024A）
  Object H                     = NORAD 69673（2026-024H，2026-06-22 部署）
  Object G                     = NORAD 59884（2023-195G，第3次任務釋放）

以各物件 epoch 最接近之 TLE 於共同時間格 SGP4 傳播，計每日最小相對距離
H–G 與 H–太空梭，對照 LeoLabs 時序（部署→接近G→返回→回收→背離）。

輸出：verify_shenlong_2026_rpo.csv、docs/fig_shenlong_2026_rpo.png
--pub：只讀 verify_shenlong_2026_rpo.csv（不連 DB），輸出 docs/figures_pub/fig_shenlong_2026_rpo/ 中英 × 白底／黑底四版本
"""
from __future__ import annotations
import sys, datetime as dt
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import numpy as np

ROOT = Path(__file__).resolve().parent
DB = ROOT / "space_db.duckdb"
FIG = ROOT / "docs" / "fig_shenlong_2026_rpo.png"
OUT = ROOT / "verify_shenlong_2026_rpo.csv"
SP_ID, H_ID, G_ID = 67689, 69673, 59884


def load(nid):
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT epoch_utc,line1,line2 FROM raw_tle_archive "
        "WHERE norad_id=? AND epoch_utc>=TIMESTAMP '2026-06-18' AND line1 IS NOT NULL "
        "ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    out = []
    for ep, l1, l2 in rows:
        try:
            from sgp4.api import Satrec
            out.append((ep, Satrec.twoline2rv(l1, l2)))
        except Exception:
            pass
    return out


def pos(tles, t):
    from sgp4.api import jday
    best = min(tles, key=lambda x: abs((x[0] - t).total_seconds()))
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond * 1e-6)
    e, r, v = best[1].sgp4(jd, fr)
    return np.array(r) if e == 0 else None


def main():
    SP, H, G = load(SP_ID), load(H_ID), load(G_ID)
    print(f"TLE 數：太空梭 {len(SP)}、ObjH {len(H)}、ObjG {len(G)}")

    t0, t1 = dt.datetime(2026, 6, 22), dt.datetime(2026, 8, 7)
    days, dHG, dHS = [], [], []
    d = t0
    while d < t1:
        hg, hs = [], []
        for hh in range(0, 24, 1):
            t = d + dt.timedelta(hours=hh)
            ph, pg, ps = pos(H, t), pos(G, t), pos(SP, t)
            if ph is not None and pg is not None:
                hg.append(np.linalg.norm(ph - pg))
            if ph is not None and ps is not None:
                hs.append(np.linalg.norm(ph - ps))
        days.append(d)
        dHG.append(min(hg) if hg else np.nan)
        dHS.append(min(hs) if hs else np.nan)
        d += dt.timedelta(days=1)

    # CSV
    import csv
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "H_G_min_km", "H_SP_min_km"])
        for dd, a, b in zip(days, dHG, dHS):
            w.writerow([dd.date(), round(a, 2), round(b, 2)])
    print(f"每日最小距離 → {OUT}")

    # 里程碑
    def onday(target):
        i = min(range(len(days)), key=lambda k: abs((days[k].date() - target).days))
        return days[i], dHG[i], dHS[i]
    for lbl, dd in [("06-22 部署", dt.date(2026, 6, 22)),
                    ("07-04 H近G", dt.date(2026, 7, 4)),
                    ("07-08 返回", dt.date(2026, 7, 8)),
                    ("07-13 回收", dt.date(2026, 7, 13))]:
        _, a, b = onday(dd)
        print(f"  {lbl}: H-G={a:.1f} km, H-太空梭={b:.1f} km")

    # 圖
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Yu Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig = draw(days, dHG, dHS)
        fig.savefig(FIG, dpi=140)
        print(f"圖 → {FIG}")
    except Exception as e:
        print(f"（繪圖略：{e}）")


def draw(days, dHG, dHS):
    """繪圖（不設字型、不存檔），回傳 Figure；預設輸出與 --pub 四版本共用。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    if str(ROOT / "docs") not in sys.path:
        sys.path.insert(0, str(ROOT / "docs"))
    import fig_pub as fp
    from fig_pub import t
    fig, ax = plt.subplots(figsize=(11, 5.6))
    xs = [mdates.date2num(x) for x in days]
    ax.plot(xs, np.clip(dHG, 0.05, None), "-o", ms=3, color="#e08a2c",
            label=t("H – Object G 最小距離", "H – Object G minimum range"))
    ax.plot(xs, np.clip(dHS, 0.05, None), "-o", ms=3, color="#1a6fc4",
            label=t("H – 太空梭(67689) 最小距離", "H – spaceplane (67689) minimum range"))
    ax.set_yscale("log")
    ax.axhline(50, color="#5cb85c", ls=":", lw=1, alpha=0.7, label=t("50 km（鄰近參考）", "50 km (proximity reference)"))
    # 里程碑標註
    ann = [(dt.date(2026, 6, 22), t("6/22 部署\n(H≈太空梭)", "6/22 deployment\n(H ≈ spaceplane)")),
           (dt.date(2026, 7, 4), t("7/4 H最近G\n≈9 km", "7/4 H closest\nto G, ≈ 9 km")),
           (dt.date(2026, 7, 8), t("7/8 離G返回", "7/8 H leaves G")),
           (dt.date(2026, 7, 13), t("7/12–14 回收\n(H≈太空梭)", "7/12–14 recovery\n(H ≈ spaceplane)"))]
    for dd, txt in ann:
        x = mdates.date2num(dt.datetime(dd.year, dd.month, dd.day))
        ax.axvline(x, color="#aaa", ls="--", lw=0.8, alpha=0.6)
        ax.text(x, 1600, txt, fontsize=8, ha="center", va="top", color="#444",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.5) if fp.in_pub() else None)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    ax.set_ylabel(t("相對距離 (km, log)", "Relative range (km, log scale)"))
    ax.set_xlabel(t("2026 年日期", "Date (2026)"))
    ax.set_title(t("神龍第4次任務 RPO 公開 TLE 查證：Object H(69673) 對 Object G(59884) 與太空梭(67689)",
                   "Shenlong mission 4 RPO check from public TLEs: Object H (69673) vs Object G (59884) "
                   "and the spaceplane (67689)"))
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(loc="center right", fontsize=9)
    fig.tight_layout()
    return fig


def pub():
    """--pub：讀既有 verify_shenlong_2026_rpo.csv（不連 DB、不重算 SGP4），輸出四版本。"""
    import csv
    sys.path.insert(0, str(ROOT / "docs"))
    import fig_pub as fp
    days, dHG, dHS = [], [], []
    with open(OUT, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            days.append(dt.datetime.fromisoformat(r["date"]))
            dHG.append(float(r["H_G_min_km"]) if r["H_G_min_km"] not in ("", "nan") else np.nan)
            dHS.append(float(r["H_SP_min_km"]) if r["H_SP_min_km"] not in ("", "nan") else np.nan)
    fp.export_variants(lambda: draw(days, dHG, dHS), "fig_shenlong_2026_rpo")

if __name__ == "__main__":
    pub() if "--pub" in sys.argv else main()
