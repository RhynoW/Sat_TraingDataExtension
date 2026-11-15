#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_kuiper_supgp_tle.py — Amazon Kuiper／OneWeb（依 SupGP 檔名判斷）：CelesTrak SupGP（營運方星曆擬合）與 Space-Track TLE 之 7 天推算比較。

以每顆衛星 SupGP 之曆元 t0 為基準，兩項比較（皆以 SGP4 推算，差值投影到 SupGP 狀態之 RIC 座標：
R 徑向、I 沿軌、C 法向）：
  A 往後推 7 天：SupGP 與 t0 前最新一筆 TLE 自 t0 起每小時推算至 t0＋7 天，量兩者之位置差。
    兩者皆非真值，此項量的是「兩份資料之一致性」隨推算時間之變化。
  B 回推比較：t0 前 0–7 天發布之每筆 TLE 推算至 t0，與 SupGP 在 t0 之狀態比較，依 TLE 年齡分箱。
    以 SupGP（擬合殘差中位約 0.24 km）作為參考，量 TLE 隨預報天數之誤差。

用法：python docs/compare_kuiper_supgp_tle.py [supgp.json.gz]
輸出：data/benchmark/kuiper_supgp_vs_tle_{forward,backward}.csv、docs/fig_kuiper_supgp_vs_tle.png
"""
import gzip
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sgp4 import omm
from sgp4.api import Satrec, jday

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/operator_ephemeris/supgp/kuiper/kuiper_20261115.json.gz"
OUT = ROOT / "data/benchmark"
KEY = SRC.name.split("_")[0]                       # kuiper／oneweb（由 SupGP 檔名判斷）
LABEL = {"kuiper": "Amazon Kuiper", "oneweb": "OneWeb"}.get(KEY, KEY)


def jd_of(ts: pd.Timestamp):
    ts = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC")
    return jday(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second + ts.microsecond / 1e6)


def prop(sat, times):
    jd = np.empty(len(times)); fr = np.empty(len(times))
    for k, t in enumerate(times):
        jd[k], fr[k] = jd_of(t)
    e, r, v = sat.sgp4_array(jd, fr)
    r = np.where(e[:, None] == 0, r, np.nan); v = np.where(e[:, None] == 0, v, np.nan)
    return r, v


def ric(r_ref, v_ref, dr):
    R = r_ref / np.linalg.norm(r_ref, axis=1, keepdims=True)
    C = np.cross(r_ref, v_ref); C /= np.linalg.norm(C, axis=1, keepdims=True)
    I = np.cross(C, R)
    return (dr * R).sum(1), (dr * I).sum(1), (dr * C).sum(1)


def main():
    recs = json.load(gzip.open(SRC, "rt", encoding="utf-8"))
    ids = sorted({int(x["NORAD_CAT_ID"]) for x in recs})
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    tle = con.execute(f"SELECT norad_id, tle_epoch, line1, line2 FROM tle_raw WHERE norad_id IN ({','.join(map(str, ids))}) "
                      "AND tle_epoch >= TIMESTAMP '2026-10-25'").df()
    con.close()
    tle["tle_epoch"] = pd.to_datetime(tle["tle_epoch"], utc=True)
    fwd, bwd = [], []
    for rec in recs:
        nid = int(rec["NORAD_CAT_ID"])
        sup = Satrec()
        omm.initialize(sup, {k: str(v) for k, v in rec.items()})
        t0 = pd.Timestamp(rec["EPOCH"], tz="UTC")
        g = tle[(tle["norad_id"] == nid) & (tle["tle_epoch"] <= t0)].sort_values("tle_epoch")
        if g.empty:
            continue
        # A 往後推 7 天
        last = g.iloc[-1]
        ts = [t0 + pd.Timedelta(hours=h) for h in range(0, 7 * 24 + 1)]
        rs, vs = prop(sup, ts)
        rt, _ = prop(Satrec.twoline2rv(last["line1"], last["line2"]), ts)
        r_, i_, c_ = ric(rs, vs, rt - rs)
        for h, a, b, c in zip(range(len(ts)), r_, i_, c_):
            fwd.append({"norad": nid, "h": h, "dR": a, "dI": b, "dC": c,
                        "tle_age_h": (t0 - last["tle_epoch"]).total_seconds() / 3600, "rms": float(rec.get("RMS") or np.nan)})
        # B 回推比較
        rs0, vs0 = prop(sup, [t0])
        for _, row in g[g["tle_epoch"] >= t0 - pd.Timedelta(days=7)].iterrows():
            rt0, _ = prop(Satrec.twoline2rv(row["line1"], row["line2"]), [t0])
            a, b, c = ric(rs0, vs0, rt0 - rs0)
            bwd.append({"norad": nid, "age_d": (t0 - row["tle_epoch"]).total_seconds() / 86400,
                        "dR": a[0], "dI": b[0], "dC": c[0]})
    F, Bk = pd.DataFrame(fwd), pd.DataFrame(bwd)
    for D in (F, Bk):
        D["d3"] = np.sqrt(D["dR"] ** 2 + D["dI"] ** 2 + D["dC"] ** 2)
    F.to_csv(OUT / f"{KEY}_supgp_vs_tle_forward.csv", index=False)
    Bk.to_csv(OUT / f"{KEY}_supgp_vs_tle_backward.csv", index=False)

    q = lambda s, p: float(np.nanpercentile(s, p))
    print(f"衛星 {F['norad'].nunique()} 顆；t0 時最新 TLE 年齡中位 {F.drop_duplicates('norad')['tle_age_h'].median():.1f} 小時")
    print("\nA 往後推算（SupGP vs 最新 TLE，km）")
    print("  推算天數 | 3D 中位 | 3D P90 | |R| 中位 | |I| 中位 | |C| 中位")
    for d in range(0, 8):
        s = F[F["h"] == d * 24]
        print(f"  {d} 天 | {s['d3'].median():.2f} | {q(s['d3'],90):.2f} | {s['dR'].abs().median():.2f} | {s['dI'].abs().median():.2f} | {s['dC'].abs().median():.2f}")
    print("\nB 回推比較（TLE 推算至 SupGP 曆元，km）")
    Bk["age_bin"] = pd.cut(Bk["age_d"], [0, 1, 2, 3, 4, 5, 6, 7], right=True, include_lowest=True)
    t = Bk.groupby("age_bin", observed=True).agg(n=("d3", "size"), d3_med=("d3", "median"),
                                                 d3_p90=("d3", lambda s: q(s, 90)),
                                                 R=("dR", lambda s: s.abs().median()), I=("dI", lambda s: s.abs().median()),
                                                 C=("dC", lambda s: s.abs().median()))
    print(t.round(2).to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "dejavusans"     # 對數軸 10^-1 之負號
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), dpi=160)
    hs = np.arange(0, 7 * 24 + 1)
    g = F.groupby("h")
    days = hs / 24
    ax[0].fill_between(days, g["d3"].quantile(0.1), g["d3"].quantile(0.9), color="#3F7BE0", alpha=0.18, lw=0, label="3D 10–90 百分位")
    ax[0].plot(days, g["d3"].median(), color="#002B8A", lw=2, label="3D 中位")
    ax[0].plot(days, g["dI"].apply(lambda s: s.abs().median()), color="#C2410C", lw=1.6, ls="--", label="|沿軌| 中位")
    ax[0].plot(days, g["dR"].apply(lambda s: s.abs().median()), color="#2F7D4A", lw=1.6, ls=":", label="|徑向| 中位")
    ax[0].set_yscale("log"); ax[0].set_xlabel("自 SupGP 曆元起推算天數"); ax[0].set_ylabel("位置差 (km)")
    ax[0].set_title("A　SupGP 與最新 TLE 往後推算之差異（一致性）", fontsize=11)
    ax[0].grid(alpha=0.3, which="both"); ax[0].legend(fontsize=8.5)
    ages = Bk["age_d"]; ax[1].scatter(ages, Bk["d3"], s=3, color="#9AA5B1", alpha=0.35, label="各筆 TLE")
    mid = t.index.map(lambda iv: iv.mid)
    ax[1].plot(mid, t["d3_med"], "o-", color="#002B8A", lw=2, label="3D 中位")
    ax[1].plot(mid, t["d3_p90"], "s--", color="#3F7BE0", lw=1.4, label="3D P90")
    ax[1].set_yscale("log"); ax[1].set_xlabel("TLE 年齡（天，推算至 SupGP 曆元）"); ax[1].set_ylabel("相對 SupGP 之位置差 (km)")
    ax[1].set_title("B　TLE 推算誤差（以 SupGP 為參考）", fontsize=11)
    ax[1].grid(alpha=0.3, which="both"); ax[1].legend(fontsize=8.5)
    from matplotlib.ticker import FuncFormatter
    for a_ in ax:   # 對數軸改用一般數字標示（避免中文字型缺 U+2212 負號）
        a_.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    fig.suptitle(f"{LABEL} {F['norad'].nunique()} 顆：CelesTrak SupGP vs Space-Track TLE（SGP4，SupGP 檔 {SRC.name.split('_')[-1][:8]}）", fontsize=12.5)
    fig.tight_layout()
    fig.savefig(ROOT / f"docs/fig_{KEY}_supgp_vs_tle.png", facecolor="white")
    print(f"\nfig → docs/fig_{KEY}_supgp_vs_tle.png")


if __name__ == "__main__":
    main()
