#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_report_r_series.py — 期末報告圖 4、5、11–17 之出版用四版本（中英 × 白底／黑底，600 dpi＋PDF）。

這 9 張報告原圖（docs/fig_r*.png）找不到原產生程式，本程式依原圖內容重寫繪圖，資料來源如下：

  圖 4  fig_r5_p2_parabola        maneuver_strategies_july.DEFAULT_P2／DEFAULT_P5／P5_MULT_MAX（常數，無資料）
  圖 5  fig_r1_nrlmsis_density    pymsis（NRLMSIS 2.1），日期 2024-06-21 12:00 UTC、經緯度 0°
  圖 11 fig_r3_joint_element      raw_tle_archive：STARLINK-37471（68802），2026-04-27 至 2026-07-14
  圖 12 fig_r9_planupload         data/raw/STARLINK-37471、STARLINK-5846 之 MEME 發布檔（burn_arc_profiler.plan_upload_scan）
  圖 13 fig_r2_starlink_planes    raw_tle_archive：Starlink，epoch 2026-06-14 至 07-14、下載時間 ≤ 2026-07-15
                                  （constellation_anomaly.analyze；此視窗重現 10,802 顆／215 面／7 個異常面）
  圖 14 fig_r8_fs_family          raw_tle_archive：福衛三號 6 顆、福衛五號、福衛七號 R（獵風者）、福衛八號 A
  圖 15 fig_r7_fs7_fleet          raw_tle_archive：福衛七號 6 顆
  圖 16 fig_r4_shenlong_release   raw_tle_archive：58573、59884，SGP4 傳播（每 1 分鐘，各用 epoch 最接近該時點之 TLE；
                                  最近距離 0.18 km @ 05-28 05:53，報告寫約 0.2 km @ 05:43Z）
  圖 17 fig_r6_shenlong_height    同上，逐筆 TLE 平均高度

TLE 圖（11、13–17）只用下載時間 ≤ 2026-07-15 之資料，epoch 截至 2026-07-15，以對應報告原圖之資料快照。
資料庫以 read_only 開啟。不覆寫報告原圖 docs/fig_*.png。
用法：python docs/gen_fig_report_r_series.py [關鍵字 …]   （例：p2 nrlmsis shenlong；不給則全部）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))
sys.path.insert(0, str(ROOT))
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

DB = ROOT / "space_db.duckdb"
RE = 6378.137
DL_CUTOFF = "2026-07-15"
C1, C2, C3, C4, C5, C6 = "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"
CG = "#888888"


def _con():
    import duckdb
    return duckdb.connect(str(DB), read_only=True)


def tle(norads, d0, d1, cols="epoch_utc, sma_km, line1, line2", cutoff=DL_CUTOFF) -> pd.DataFrame:
    """逐顆取 TLE（同 epoch 重複下載只留一筆）。"""
    ids = ",".join(str(int(n)) for n in norads)
    q = (f"SELECT norad_id, {cols} FROM raw_tle_archive WHERE norad_id IN ({ids}) "
         f"AND epoch_utc BETWEEN '{d0}' AND '{d1}' AND downloaded_at_utc <= '{cutoff}' "
         "QUALIFY ROW_NUMBER() OVER (PARTITION BY norad_id, epoch_utc ORDER BY downloaded_at_utc DESC) = 1 "
         "ORDER BY norad_id, epoch_utc")
    with _con() as c:
        df = c.execute(q).fetchdf()
    df["epoch"] = pd.to_datetime(df["epoch_utc"])
    df["alt"] = df["sma_km"] - RE
    return df


def _date_axis(ax, fmt="%Y-%m-%d"):
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))


# ── 圖 4：P2／P5 門檻 ────────────────────────────────────────────────────────
def draw_p2():
    import maneuver_strategies_july as ms
    p2, p5 = ms.DEFAULT_P2, ms.DEFAULT_P5
    x = np.linspace(250, 1200, 800)
    m200 = float(np.clip(p5(200.0), 1.0, ms.P5_MULT_MAX))
    fig, ax = plt.subplots(figsize=(7.8, 4.6))
    ax.plot(x, p2(x), color=C1, lw=2.4, label=t("P2 門檻（一般條件）", "P2 threshold (normal conditions)"))
    ax.plot(x, p2(x) * m200, "--", color=C4, lw=1.6,
            label=t(f"P5 調整後（太陽極大期 F10.7＝200 sfu，×{m200:g}）",
                    f"After P5 adjustment (solar maximum, F10.7 = 200 sfu, ×{m200:g})"))
    ax.axhline(p2.floor, color=C1, lw=0.8, ls=":")
    ax.plot([p2.ref_x], [p2.ref_y], "o", color=C1, ms=7, zorder=5)
    ax.annotate(t(f"參考點（{p2.ref_x:.0f} km，{p2.ref_y:.1f} km）", f"Reference point ({p2.ref_x:.0f} km, {p2.ref_y:.1f} km)"),
                (p2.ref_x, p2.ref_y), xytext=(14, 6), textcoords="offset points", fontsize=9)
    ax.text(760, p2.floor + 0.05, t(f"底值 {p2.floor:g} km（{p2.vertex:.0f} km 以上）",
                                    f"Floor {p2.floor:g} km (above {p2.vertex:.0f} km)"), color=C1, fontsize=9)
    ax.set_xlim(200, 1250); ax.set_ylim(0, 3.6)
    ax.set_xlabel(t("軌道高度 (km)", "Orbital altitude (km)"))
    ax.set_ylabel(t("Δa 偵測門檻 (km)", "Δa detection threshold (km)"))
    ax.set_title(t("P2 高度自適應門檻與 P5 太陽活動調整", "P2 altitude-adaptive threshold and P5 solar-activity adjustment"))
    ax.grid(alpha=0.3); ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    return fig


# ── 圖 5：NRLMSIS 密度 ──────────────────────────────────────────────────────
def draw_nrlmsis():
    import pymsis
    h = np.arange(200, 901, 10.0)
    when = np.datetime64("2024-06-21T12:00")
    cases = [(70, 5, C1, "-", t("太陽極小（F10.7＝70，Ap＝5）", "Solar minimum (F10.7 = 70, Ap = 5)")),
             (150, 15, C2, "-", t("中等活動（F10.7＝150，Ap＝15）", "Moderate activity (F10.7 = 150, Ap = 15)")),
             (220, 15, C4, "-", t("太陽極大（F10.7＝220，Ap＝15）", "Solar maximum (F10.7 = 220, Ap = 15)")),
             (150, 200, C5, "--", t("磁暴（F10.7＝150，Ap＝200）", "Geomagnetic storm (F10.7 = 150, Ap = 200)"))]
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.axvspan(300, 600, color="#cccccc", alpha=0.2, lw=0)
    ax.text(450, 2e-10, t("Starlink 主營運帶", "Starlink main operating band"), ha="center", color=CG, fontsize=9)
    for f107, ap, c, ls, lab in cases:
        out = pymsis.calculate(np.array([when]), 0.0, 0.0, h, f107s=[f107], f107as=[f107], aps=[[ap] * 7])
        rho = np.squeeze(out)[:, pymsis.Variable.MASS_DENSITY]
        if fp.lang() == "zh" and fp.theme() == "light":
            print(f"    F10.7={f107} Ap={ap}: ρ(400 km)={rho[h == 400][0]:.2e}")
        ax.semilogy(h, rho, ls, color=c, lw=2, label=lab)
    ax.set_xlabel(t("高度 (km)", "Altitude (km)"))
    ax.set_ylabel(t("大氣密度 (kg/m³，對數尺度)", "Atmospheric density (kg/m³, log scale)"))
    ax.set_title(t("NRLMSIS 大氣密度隨高度與太空天氣條件之變化", "NRLMSIS atmospheric density vs. altitude and space weather"))
    ax.grid(alpha=0.3); ax.legend(fontsize=9)
    fig.tight_layout()
    return fig


# ── 圖 11：STARLINK-37471 平均高度與逐筆 Δa ─────────────────────────────────
def draw_joint(df):
    ev = pd.Timestamp("2026-06-21 09:38")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8.2, 5.4), sharex=True)
    a1.plot(df.epoch, df.alt, "-o", color=C1, ms=2.5, lw=1)
    a1.set_ylabel(t("平均高度 a − RE (km)", "Mean altitude a − RE (km)"))
    da = df.sma_km.diff()
    a2.bar(df.epoch, da, width=0.18, color=C2)
    a2.set_ylabel(t("逐筆增量 Δa (km)", "Per-TLE increment Δa (km)"))
    a2.set_xlabel(t("日期 (UTC)", "Date (UTC)"))
    for a in (a1, a2):
        a.axvline(ev, color=C4, ls="--", lw=1); a.grid(alpha=0.3)
    a1.text(ev + pd.Timedelta(hours=36), df.alt.max() - 28,
            t("MEME 真值轉移\n2026-06-21 09:38Z（Δa 約 +50 km）", "MEME truth transfer\n2026-06-21 09:38Z (Δa ≈ +50 km)"),
            color=C4, fontsize=8.5)
    _date_axis(a2)
    a1.set_title(t("STARLINK-37471（NORAD 68802）平均高度與逐筆 Δa：2026-06-21 升軌",
                   "STARLINK-37471 (NORAD 68802) mean altitude and per-TLE Δa: 2026-06-21 orbit raise"))
    fig.tight_layout()
    return fig


# ── 圖 12：相鄰 MEME 發布檔位置差 ────────────────────────────────────────────
def plan_series():
    import burn_arc_profiler as B
    out = {}
    for sat, first, n in (("STARLINK-37471", "2026-06-21T09-38-42Z.txt", 16),
                          ("STARLINK-5846", "2026-07-04T11-20-42Z.txt", 11)):
        files = sorted((ROOT / B.RAW_DIR / sat).glob("*.txt"))
        i = [f.name for f in files].index(first)
        out[sat] = B.plan_upload_scan(files[i:i + n + 1], sat).head(n)
    return out, B.NORMAL_BAND_M


def draw_plan(series, band):
    s1, s2 = series["STARLINK-37471"], series["STARLINK-5846"]
    fig, ax = plt.subplots(figsize=(9.2, 4.0))
    ax.plot(range(len(s1)), s1.first10min_diff_m, "-o", color=C4, ms=5,
            label=t("STARLINK-37471（06-21 執行 +50 km 升軌）", "STARLINK-37471 (+50 km orbit raise on 06-21)"))
    ax.plot(range(len(s2)), s2.first10min_diff_m, "-o", color=C1, ms=5,
            label=t("STARLINK-5846（同週僅站位維持）", "STARLINK-5846 (station-keeping only that week)"))
    ax.axhline(band, color="black", ls="--", lw=1)
    ax.text(1, band + 25, t(f"正常帶上限 {band:.0f} m", f"Normal-band upper limit {band:.0f} m"), fontsize=9)
    v0 = float(s1.first10min_diff_m.iloc[0])
    ax.annotate(t(f"機動計畫上傳\n{v0:,.0f} m", f"Maneuver plan upload\n{v0:,.0f} m"), (0, v0), xytext=(18, -40),
                textcoords="offset points", color=C4, fontsize=9, arrowprops=dict(arrowstyle="->", color=C4))
    ax.set_xlabel(t("相鄰 MEME 發布檔序（約每 8 小時一檔）", "Consecutive MEME release index (about one file every 8 h)"))
    ax.set_ylabel(t("重疊首 10 分鐘位置差中位數 (m)", "Median position difference, first 10 overlapping min (m)"))
    ax.set_title(t("相鄰 MEME 發布檔位置差：機動計畫上傳之偵測", "Position difference between consecutive MEME releases: detecting maneuver plan uploads"))
    ax.grid(alpha=0.3); ax.legend(fontsize=9)
    fig.tight_layout()
    return fig


# ── 圖 13：Starlink 軌道面一致性 ────────────────────────────────────────────
def planes_result():
    import constellation_anomaly as ca
    with _con() as c:
        df = c.execute(
            "SELECT norad_id, object_name, epoch_utc, sma_km, inclination_deg, raan_deg, argp_deg, mean_anomaly_deg "
            "FROM raw_tle_archive WHERE UPPER(object_name) LIKE '%STARLINK-%' AND sma_km IS NOT NULL "
            "AND epoch_utc BETWEEN '2026-06-14' AND '2026-07-14' AND downloaded_at_utc <= ? "
            "ORDER BY norad_id, epoch_utc", [DL_CUTOFF]).fetchdf()
    df["epoch"] = pd.to_datetime(df["epoch_utc"], utc=True)
    r = ca.analyze(df)
    p = r["planes"]
    thr = float(p.di_std_deg.median() + 3 * p.di_std_deg.std(ddof=0))
    return {"n_sat": int(df.norad_id.nunique()), "planes": p, "thr": thr, "n_batch": int(r["batch"].flag_batch.sum())}


def draw_planes(R):
    p = R["planes"].sort_values("di_std_deg", ascending=False).reset_index(drop=True)
    nflag = int(p.flag_plane_incoherent.sum())
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ax.bar(p.index, p.di_std_deg, width=1.0, color=np.where(p.flag_plane_incoherent, C4, C1))
    ax.axhline(R["thr"], color=C4, ls="--", lw=1,
               label=t(f"判定線（中位數＋3σ）：{nflag} 個面超標", f"Threshold (median + 3σ): {nflag} planes exceed"))
    ax.set_xlabel(t(f"Starlink 軌道面（共 {len(p)} 面，依 Δi 標準差由大至小排列）",
                    f"Starlink orbital planes ({len(p)} in total, sorted by Δi standard deviation)"))
    ax.set_ylabel(t("面內傾角變化標準差 σ_Δi (°)", "In-plane inclination-change std σ_Δi (°)"))
    ax.set_title(t("Starlink 軌道面一致性：紅色為傾角異常面", "Starlink orbital-plane coherence: red marks planes with anomalous inclination"))
    ax.grid(axis="y", alpha=0.3); ax.legend(fontsize=9)
    fig.tight_layout()
    return fig


# ── 圖 14：福衛家族 ──────────────────────────────────────────────────────────
FS3 = {29047: "FS3A", 29048: "FS3B", 29049: "FS3C", 29050: "FS3D", 29051: "FS3E", 29052: "FS3F"}
def _fs3_colors():
    """FS3A–F（FS3D 除外）以藍色深淺區分。黑底版經 fp.to_dark 做亮度反轉，故黑底先取較深色，反轉後才夠亮。"""
    import colorsys
    ls = np.linspace(0.28, 0.72, 5) if fp.theme() == "light" else np.linspace(0.45, 0.20, 5)
    cols = ["#%02x%02x%02x" % tuple(int(255 * v) for v in colorsys.hls_to_rgb(0.58, l, 0.75)) for l in ls]
    out, k = {}, 0
    for n in FS3:
        if n == 29050:
            out[n] = C4
        else:
            out[n] = cols[k]; k += 1
    return out


def draw_fs_family(df):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    col = _fs3_colors()
    for n, lab in FS3.items():
        g = df[df.norad_id == n]
        a1.plot(g.epoch, g.alt, color=col[n], lw=1.2, label=lab)
    a1.legend(ncol=2, fontsize=8.5, loc="center right")
    a1.set_title(t("福衛三號 6 顆（除役，自然衰減）", "FORMOSAT-3, 6 satellites (decommissioned, natural decay)"))
    a1.set_ylabel(t("平均高度 (km)", "Mean altitude (km)"))
    for n, c, lab in ((42920, C3, t("FS-5（SSO 723 km）", "FS-5 (SSO 723 km)")),
                      (58017, C5, t("TRITON（SSO 595 km）", "TRITON (SSO 595 km)")),
                      (66666, C2, t("FS-8A（SSO 564 km）", "FS-8A (SSO 564 km)"))):
        g = df[df.norad_id == n]
        a2.plot(g.epoch, g.alt, color=c, lw=1.4, label=lab)
    a2.legend(fontsize=8.5, loc="lower left")
    a2.set_title("FORMOSAT-5 / TRITON / FORMOSAT-8A")
    for a in (a1, a2):
        a.set_xlabel(t("日期", "Date")); a.grid(alpha=0.3)
        _date_axis(a, "%Y-%m"); a.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    return fig


# ── 圖 15：福衛七號 ──────────────────────────────────────────────────────────
FS7 = [(44349, "FS7-1", C1), (44351, "FS7-2", C2), (44343, "FS7-3", C3), (44350, "FS7-4", C4),
       (44358, "FS7-5", C5), (44353, "FS7-6", C6)]


def draw_fs7(df):
    fig, ax = plt.subplots(figsize=(9.4, 4.6))
    for n, lab, c in FS7:
        g = df[df.norad_id == n]
        if n == 44343:
            ax.plot(g.epoch, g.alt, color=c, lw=2.4, label=t(f"{lab}（停止維持）", f"{lab} (maintenance stopped)"), zorder=5)
        else:
            ax.plot(g.epoch, g.alt, color=c, lw=1, label=lab)
    last3 = df[df.norad_id == 44343].alt.iloc[-1]
    ax.text(pd.Timestamp("2025-06-25"), 566, t("2025-07／08 五顆分段升軌 550→575 km", "Jul–Aug 2025: five satellites raised in stages, 550→575 km"), fontsize=9)
    ax.text(pd.Timestamp("2025-10-20"), 582, t("2026-01 五顆同步推升至 580 km", "Jan 2026: five satellites raised together to 580 km"), fontsize=9)
    ax.text(pd.Timestamp("2025-10-15"), 553,
            t(f"2025-05 後 FS7-3 停止軌道維持，\n自然衰減至 {last3:.0f} km", f"FS7-3 stopped orbit maintenance after May 2025\nand decayed naturally to {last3:.0f} km"),
            color=C3, fontsize=9)
    ax.set_ylim(529, 587)
    ax.set_xlabel(t("日期", "Date")); ax.set_ylabel(t("平均高度 a − RE (km)", "Mean altitude a − RE (km)"))
    ax.set_title(t("福衛七號 6 顆高度時序（2024-01 至 2026-07）：同步維持與 FS7-3 自然衰減",
                   "FORMOSAT-7/COSMIC-2 altitude, Jan 2024 – Jul 2026: synchronized maintenance and FS7-3 natural decay"))
    _date_axis(ax, "%Y-%m"); ax.grid(alpha=0.3); ax.legend(ncol=3, fontsize=8.5, loc="lower left")
    fig.tight_layout()
    return fig


# ── 圖 16、17：神龍太空梭與物體 G ─────────────────────────────────────────────
REL = pd.Timestamp("2024-05-24")


def shenlong_rel(df, step_min=1):
    from sgp4.api import Satrec, jday
    sats = {n: [(r.epoch, Satrec.twoline2rv(r.line1, r.line2)) for r in g.itertuples()] for n, g in df.groupby("norad_id")}
    t0 = max(sats[58573][0][0], sats[59884][0][0]).ceil("10min")
    t1 = pd.Timestamp("2024-06-10")
    ts = pd.date_range(t0, t1, freq=f"{step_min}min")
    rows = []
    for tt in ts:
        jd, fr = jday(tt.year, tt.month, tt.day, tt.hour, tt.minute, tt.second)
        rv = {}
        for n, lst in sats.items():
            s = min(lst, key=lambda p: abs((p[0] - tt).total_seconds()))[1]   # epoch 最接近 t 之 TLE
            e, r, v = s.sgp4(jd, fr)
            rv[n] = (np.array(r), np.array(v)) if e == 0 else None
        if rv[58573] is None or rv[59884] is None:
            continue
        rc, vc = rv[58573]; d = rv[59884][0] - rc
        R = rc / np.linalg.norm(rc); N = np.cross(rc, vc); N /= np.linalg.norm(N); T = np.cross(N, R)
        rows.append((tt, np.linalg.norm(d), d @ T, d @ R, d @ N))
    return pd.DataFrame(rows, columns=["t", "dist", "T", "R", "N"])


def draw_shenlong_rel(rel):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8.6, 5.8), sharex=True)
    a1.semilogy(rel.t, rel.dist, color=C1, lw=1.2)
    a1.set_ylabel(t("相對距離 (km，對數)", "Relative distance (km, log)"))
    a2.plot(rel.t, rel["T"], color=C2, lw=1.1, label=t("沿軌 T", "Along-track T"))
    a2.plot(rel.t, rel["R"], color=C3, lw=1.1, label=t("徑向 R", "Radial R"))
    a2.plot(rel.t, rel["N"], color="#7f7f7f", lw=1.1, label=t("法向 N", "Cross-track N"))
    a2.set_ylabel(t("LVLH 相對位置 (km)", "LVLH relative position (km)")); a2.legend(fontsize=9)
    a2.set_xlabel(t("日期 (UTC)", "Date (UTC)"))
    for a in (a1, a2):
        a.axvline(REL, color=C4, ls="--", lw=1); a.grid(alpha=0.3)
    a1.text(REL + pd.Timedelta(hours=10), 700, t("2024-05-24 釋放（約 605 km）", "Released 2024-05-24 (about 605 km)"), color=C4, fontsize=9)
    a2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    _date_axis(a2, "%m-%d")
    a1.set_title(t("CSSHQ-1（NORAD 58573）→ 物體 G（NORAD 59884）釋放事件重建（SGP4 傳播）",
                   "CSSHQ-1 (NORAD 58573) → Object G (NORAD 59884) release reconstruction (SGP4 propagation)"))
    fig.tight_layout()
    return fig


def shenlong_dh(df):
    a = df[(df.epoch >= "2024-05-30") & (df.epoch <= "2024-05-31")].groupby("norad_id").alt.mean()
    return float(a.max()), float(a.min())


def draw_shenlong_height(df):
    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    for n, c, lab in ((58573, "#c9a400", "58573 PRC TEST SPACECRAFT 3 (CSSHQ-1)"), (59884, "#1a9fd6", "59884 OBJECT G")):
        g = df[(df.norad_id == n) & (df.epoch >= "2024-04-29") & (df.epoch <= "2024-06-02")]
        ax.plot(g.epoch, g.alt, "o", color=c, ms=4.5, label=lab)
    ax.axvline(REL, color=C4, ls="--", lw=1)
    hi, lo = shenlong_dh(df)
    xa = pd.Timestamp("2024-05-30 12:00")
    ax.annotate("", (xa, lo), (xa, hi), arrowprops=dict(arrowstyle="<->", color="black"))
    ax.text(xa + pd.Timedelta(hours=8), (hi + lo) / 2, t(f"Δh 約 {hi - lo:.2f} km", f"Δh ≈ {hi - lo:.2f} km"), fontsize=10)
    ax.set_ylabel(t("平均高度 a − RE (km)", "Mean altitude a − RE (km)"))
    ax.set_xlabel(t("日期 (UTC)", "Date (UTC)"))
    ax.set_title(t("CSSHQ-1 與物體 G 平均高度（TLE）", "Mean altitude of CSSHQ-1 and Object G (TLE)"))
    _date_axis(ax, "%m-%d"); ax.grid(alpha=0.3); ax.legend(fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig


# ── 主程式 ───────────────────────────────────────────────────────────────────
def main(keys):
    want = lambda k: not keys or any(x in k for x in keys)  # noqa: E731
    E = fp.export_variants
    if want("p2_parabola"):
        E(draw_p2, "fig_r5_p2_parabola")
    if want("nrlmsis_density"):
        E(draw_nrlmsis, "fig_r1_nrlmsis_density")
    if want("joint_element"):
        d = tle([68802], "2026-04-27", "2026-07-15")
        print(f"  68802：{len(d)} 筆，06-21 前後高度 {d[d.epoch < '2026-06-21'].alt.iloc[-1]:.1f}→{d[d.epoch > '2026-06-22'].alt.iloc[0]:.1f} km")
        E(lambda: draw_joint(d), "fig_r3_joint_element")
    if want("planupload"):
        s, band = plan_series()
        print(f"  37471 首值 {s['STARLINK-37471'].first10min_diff_m.iloc[0]} m；5846 最大 {s['STARLINK-5846'].first10min_diff_m.max()} m")
        E(lambda: draw_plan(s, band), "fig_r9_planupload")
    if want("starlink_planes"):
        R = planes_result()
        print(f"  Starlink {R['n_sat']} 顆／{len(R['planes'])} 面／異常面 {int(R['planes'].flag_plane_incoherent.sum())}／批量日 {R['n_batch']}")
        E(lambda: draw_planes(R), "fig_r2_starlink_planes")
    if want("fs_family"):
        d = tle(list(FS3) + [42920, 58017, 66666], "2024-01-01", "2026-07-15")
        E(lambda: draw_fs_family(d), "fig_r8_fs_family")
    if want("fs7_fleet"):
        d = tle([n for n, _, _ in FS7], "2024-01-01", "2026-07-15")
        print(f"  FS7-3 末筆 {d[d.norad_id == 44343].alt.iloc[-1]:.1f} km")
        E(lambda: draw_fs7(d), "fig_r7_fs7_fleet")
    if want("shenlong_release") or want("shenlong_height"):
        d = tle([58573, 59884], "2024-04-20", "2024-06-15", cutoff="2026-12-31")
        if want("shenlong_release"):
            rel = shenlong_rel(d)
            i = rel.dist.idxmin()
            print(f"  最近距離 {rel.dist[i]:.2f} km @ {rel.t[i]}；06-06 前最大 {rel[rel.t < '2024-06-07'].dist.max():.0f} km")
            E(lambda: draw_shenlong_rel(rel), "fig_r4_shenlong_release")
        if want("shenlong_height"):
            hi, lo = shenlong_dh(d)
            print(f"  Δh {hi - lo:.2f} km")
            E(lambda: draw_shenlong_height(d), "fig_r6_shenlong_height")


if __name__ == "__main__":
    main([a.lower() for a in sys.argv[1:]])
