"""FORMOSAT-7 精密軌道（leoOrb）衰減率 vs NRLMSIS 預期：隨太陽活動起伏之時間相關（不含 FORMOSAT7-3／L78）。

1. 逐日 leoOrb（2024-01 迄今）→ 60 秒網格之瞬時半長軸（detect.build_series）
   → 以一個軌道週期滑動平均消去 J2 短週期項 → 每 UTC 日取中位數（當日涵蓋 ≥ 18 小時）。
2. 7 日窗衰減率：窗內每日平均半長軸之線性斜率（m/日，正值＝下降）。
   排除機動：有效日之間日變化率 > +20 m/日（推進抬升）或 < −150 m/日、線性擬合殘差 > 40 m，或窗內有效日 < 5。
3. NRLMSIS 2.1（atmospheric_drag.density，實測 F10.7、Ap）：依當日平均高度，於緯度 −24°～24°（FS7 傾角 24°）、
   經度 0°／180°、每 3 小時取樣平均，得軌道平均密度 ρ；預期衰減形狀 s = ρ·√(μa)，
   逐星以全期中位數校準單一彈道係數 B（與 TLE 分析同法），預期衰減率 = B·s。
4. 對照：同五顆衛星之 TLE（space_db）同法計算之 7 日窗衰減率。
輸出：docs/fig_fs7_precise_nrlmsis.png、data/benchmark/fs7_precise_decay_windows.csv、fs7_precise_nrlmsis_corr.csv
--pub：只讀上述兩個 CSV 與 nrlmsis_decay_expect.csv（不重算、不連 DB），輸出 docs/figures_pub/fig_fs7_precise_nrlmsis/ 中英 × 白底／黑底四版本
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
LEO = ROOT / "data/formosat7_leoorb"
BM = ROOT / "data/benchmark"
CACHE = BM / "fs7_daily_sma_cache"
SATS = {"L76": ("FORMOSAT7-1", 44349), "L77": ("FORMOSAT7-2", 44351), "L79": ("FORMOSAT7-4", 44350),
        "L80": ("FORMOSAT7-5", 44358), "L81": ("FORMOSAT7-6", 44353)}
MU_KM, RE = 398600.4418, 6378.137


def day_mean(tar):
    out = CACHE / (Path(tar).name.replace(".tar.gz", ".csv"))
    if out.exists():
        return
    from formosat7_leoorb.archive import load_leoorb_tar
    from formosat7_leoorb.detect import build_series
    rows = []
    try:
        ser = build_series(load_leoorb_tar(tar))
    except Exception as e:                     # 壞檔略過
        print("skip", tar, e)
        ser = {}
    for sat, s in ser.items():
        if sat not in SATS:
            continue
        a = s.a_km
        per = int(round(2 * np.pi * np.sqrt(a.median() ** 3 / MU_KM) / 60))
        sm = a.rolling(per, center=True, min_periods=int(per * 0.9)).mean().dropna()
        for d, g in sm.groupby(sm.index.floor("D")):
            if len(g) >= 18 * 60:
                rows.append({"date": d.date(), "sp3_sat": sat, "a_km": g.median(), "n_min": len(g)})
    pd.DataFrame(rows, columns=["date", "sp3_sat", "a_km", "n_min"]).to_csv(out, index=False)


def nrl_shape(dates, alt_km):
    from atmospheric_drag import density, load_space_weather
    sw = load_space_weather()
    LATS, LONS, HRS = np.arange(-24, 25, 8), np.array([0.0, 180.0]), np.arange(0, 24, 3)
    k = len(LATS) * len(LONS) * len(HRS)
    t = pd.DatetimeIndex([pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=int(h))
                          for d in dates for h in HRS for _ in LATS for _ in LONS])
    la = np.tile(np.repeat(LATS, len(LONS)), len(dates) * len(HRS)).astype(float)
    lo = np.tile(LONS, len(dates) * len(HRS) * len(LATS))
    alt = np.repeat(alt_km, k)
    rho = density(t, alt, sw, lat=la, lon=lo).reshape(len(dates), k).mean(1)
    a_m = (np.asarray(alt_km) + RE) * 1e3
    return rho * np.sqrt(3.986004418e14 * a_m) * 86400.0          # m/日 per unit B (m²/kg)


def windows_from_daily(D, col="a_km"):
    """D: index=date（日），欄 a_km。回傳 7 日窗斜率（m/日，正＝下降）。"""
    D = D.asfreq("D")
    rows = []
    for w0 in pd.date_range(D.index.min().floor("7D"), D.index.max(), freq="7D"):
        g = D.loc[w0:w0 + pd.Timedelta(days=6), col].dropna()
        if len(g) < 5:
            continue
        x = (g.index - g.index[0]).days.to_numpy(float)
        y = g.to_numpy() * 1000
        rate = np.diff(y) / np.diff(x)                      # 有效日之間的日變化率（跨缺日亦檢查）
        if (rate > 20).any() or (rate < -150).any():
            continue
        k, c0 = np.polyfit(x, y, 1)
        if np.abs(y - (k * x + c0)).max() > 40:             # 窗內非線性（機動、異常）
            continue
        rows.append({"w": w0, "decay": -k, "alt": g.mean() - RE})
    return pd.DataFrame(rows)


def tle_daily(nid):
    import duckdb
    c = duckdb.connect("space_db.duckdb", read_only=True)
    t = c.execute("select epoch_utc, sma_km from raw_tle_archive where norad_id=? and epoch_utc>='2024-01-01' order by 1",
                  [nid]).df()
    t["d"] = pd.to_datetime(t.epoch_utc).dt.floor("D")
    return t.groupby("d").sma_km.median().rename("a_km").to_frame()


def main():
    CACHE.mkdir(exist_ok=True)
    tars = sorted(str(p) for p in LEO.glob("leoOrb_*.tar.gz"))
    with ProcessPoolExecutor(max_workers=int(os.environ.get("NPROC", 8))) as ex:
        list(ex.map(day_mean, tars, chunksize=8))
    daily = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in CACHE.glob("*.csv") if f.stat().st_size > 30])
    daily = daily.groupby(["sp3_sat", "date"]).a_km.median().reset_index()

    from scipy.stats import pearsonr, spearmanr
    allw, corr = [], []
    for sat, (name, nid) in SATS.items():
        D = daily[daily.sp3_sat == sat].set_index("date")[["a_km"]].sort_index()
        W = windows_from_daily(D)
        if W.empty:
            continue
        W["shape"] = nrl_shape(W.w.dt.date + pd.Timedelta(days=3), W.alt.to_numpy())
        B = float(np.median(W.decay[W.decay > 0] / W["shape"][W.decay > 0]))
        W["nrl"] = B * W["shape"]
        T = windows_from_daily(tle_daily(nid))
        W = W.merge(T[["w", "decay"]].rename(columns={"decay": "tle"}), on="w", how="left")
        W["sat"], W["name"] = sat, name
        allw.append(W)
        both = W.dropna(subset=["tle"])
        corr.append({"sat": name, "norad": nid, "n_win": len(W), "B_m2_per_kg": B,
                     "r_precise_nrl": pearsonr(W.decay, W.nrl)[0], "rho_precise_nrl": spearmanr(W.decay, W.nrl)[0],
                     "r_tle_nrl": pearsonr(both.tle, both.nrl)[0], "r_tle_precise": pearsonr(both.tle, both.decay)[0],
                     "rms_precise_minus_nrl": float(np.sqrt(((W.decay - W.nrl) ** 2).mean())),
                     "rms_tle_minus_precise": float(np.sqrt(((both.tle - both.decay) ** 2).mean())),
                     "decay_med": W.decay.median()})
    A = pd.concat(allw, ignore_index=True)
    C = pd.DataFrame(corr)
    A.to_csv(BM / "fs7_precise_decay_windows.csv", index=False, encoding="utf-8-sig")
    C.round(4).to_csv(BM / "fs7_precise_nrlmsis_corr.csv", index=False, encoding="utf-8-sig")
    print(C.round(3).to_string(index=False))
    pool = A.dropna(subset=["tle"])
    print("合併 r 精密-NRLMSIS", round(pearsonr(A.decay, A.nrl)[0], 3), " TLE-NRLMSIS", round(pearsonr(pool.tle, pool.nrl)[0], 3),
          " TLE-精密", round(pearsonr(pool.tle, pool.decay)[0], 3))
    plot(A, C)


def plot(A, C):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig = draw(A, C)
    fig.savefig(ROOT / "docs/fig_fs7_precise_nrlmsis.png", bbox_inches="tight")
    print("fig saved")


def draw(A, C):
    """繪圖（不設字型、不存檔），回傳 Figure；預設輸出與 --pub 四版本共用。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from scipy.stats import pearsonr
    from fig_pub import t
    sw = pd.read_csv(BM / "nrlmsis_decay_expect.csv", parse_dates=["date"])
    fig = plt.figure(figsize=(14, 11), dpi=150)
    gs = fig.add_gridspec(3, 3, height_ratios=[0.8, 1.6, 1.5], hspace=0.32, wspace=0.28)
    ax0 = fig.add_subplot(gs[0, :])
    ax0.plot(sw.date, sw.f107, color="#9AA5B1", lw=0.7, label=t("F10.7 每日", "F10.7 daily"))
    ax0.plot(sw.date, sw.f107_81, color="#C2410C", lw=1.8, label=t("F10.7 81 日平均", "F10.7 81-day mean"))
    ax0.set_ylabel("F10.7 (sfu)")
    ax0.legend(loc="upper right", frameon=False, ncol=2, fontsize=9)
    ax0.set_title(t("FORMOSAT-7 精密軌道（leoOrb）衰減率 vs NRLMSIS 預期（2024-01 迄今，不含 FORMOSAT7-3）",
                    "FORMOSAT-7 precise-orbit (leoOrb) decay rate vs NRLMSIS expectation (2024-01 to date, excl. FORMOSAT7-3)"),
                  loc="left", fontsize=13)

    ax1 = fig.add_subplot(gs[1, :], sharex=ax0)
    g = A.groupby("w")
    S = pd.DataFrame({"p": g.decay.median(), "lo": g.decay.min(), "hi": g.decay.max(), "n": g.size(),
                      "nrl": g.nrl.median(), "tle": g.tle.median()})
    S = S[S.n >= 2]
    ax1.fill_between(S.index, S.lo, S.hi, color="#60A5FA", alpha=0.25, lw=0, label=t("精密軌道（各星範圍）", "Precise orbit (range across satellites)"))
    ax1.plot(S.index, S.p, color="#1D4ED8", lw=1.6, marker="o", ms=2.5, label=t("精密軌道（五星中位數）", "Precise orbit (median of 5 satellites)"))
    ax1.plot(S.index, S.nrl, color="#C2410C", lw=2.0, label=t("NRLMSIS 預期（逐星單一 B 校準）", "NRLMSIS expected (one B per satellite)"))
    ax1.plot(S.index, S.tle, color="#6B7280", lw=1.0, ls="--", label=t("TLE（五星中位數）", "TLE (median of 5 satellites)"))
    r_p = pearsonr(S.p, S.nrl)[0]
    ax1.text(0.01, 0.95, t(f"週中位數序列：精密 vs NRLMSIS r = {r_p:.2f}　逐星 r 中位 = {C.r_precise_nrl.median():.2f}",
                          f"Weekly-median series: precise vs NRLMSIS r = {r_p:.2f}\n"
                          f"Per-satellite median r = {C.r_precise_nrl.median():.2f}"),
             transform=ax1.transAxes, va="top", fontsize=11, fontweight="bold",
             bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=2))
    ax1.set_ylabel(t("半長軸衰減率（m/日）", "SMA decay rate (m/day)"))
    ax1.set_ylim(0, S[["hi", "nrl"]].max().max() * 1.25)
    ax1.legend(loc="upper right", frameon=False, fontsize=9, ncol=2)
    ax1.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.set_xlim(pd.Timestamp("2024-01-01"), pd.Timestamp("2026-11-16"))

    ax2 = fig.add_subplot(gs[2, 0])
    cols = dict(zip(C.sat, ["#1D4ED8", "#059669", "#D97706", "#7C3AED", "#DB2777"]))
    for name, gg in A.groupby("name"):
        ax2.scatter(gg.nrl, gg.decay, s=7, alpha=0.5, color=cols[name], label=name)
    m = max(A.nrl.max(), A.decay.max()) * 1.05
    ax2.plot([0, m], [0, m], color="#444", ls="--", lw=1)
    ax2.set(xlim=(0, m), ylim=(0, m), xlabel=t("NRLMSIS 預期（m/日）", "NRLMSIS expected (m/day)"),
            ylabel=t("精密軌道實測（m/日）", "Precise-orbit observed (m/day)"),
            title=t(f"(a) 精密 vs NRLMSIS　合併 r = {pearsonr(A.decay, A.nrl)[0]:.2f}",
                    f"(a) Precise vs NRLMSIS (pooled r = {pearsonr(A.decay, A.nrl)[0]:.2f})"))
    ax2.legend(fontsize=7.5, frameon=False, markerscale=1.8)
    pool = A.dropna(subset=["tle"])
    ax3 = fig.add_subplot(gs[2, 1])
    ax3.scatter(pool.decay, pool.tle, s=7, alpha=0.4, color="#6B7280")
    ax3.plot([0, m], [0, m], color="#444", ls="--", lw=1)
    ax3.set(xlim=(0, m), ylim=(0, m), xlabel=t("精密軌道實測（m/日）", "Precise-orbit observed (m/day)"),
            ylabel=t("TLE 實測（m/日）", "TLE observed (m/day)"),
            title=t(f"(b) TLE vs 精密　合併 r = {pearsonr(pool.decay, pool.tle)[0]:.2f}",
                    f"(b) TLE vs precise (pooled r = {pearsonr(pool.decay, pool.tle)[0]:.2f})"))
    ax4 = fig.add_subplot(gs[2, 2])
    x = np.arange(len(C))
    ax4.bar(x - 0.2, C.r_precise_nrl, 0.4, color="#1D4ED8", label=t("精密 vs NRLMSIS", "Precise vs NRLMSIS"))
    ax4.bar(x + 0.2, C.r_tle_nrl, 0.4, color="#9CA3AF", label="TLE vs NRLMSIS")
    ax4.set_xticks(x, [s.replace("FORMOSAT7-", "FM") for s in C.sat])
    ax4.set(ylim=(0, 1.18), ylabel=t("Pearson r（7 日窗）", "Pearson r (7-day windows)"),
            title=t("(c) 逐星時間相關", "(c) Per-satellite temporal correlation"))
    ax4.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax4.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
    for a in (ax0, ax1, ax2, ax3, ax4):
        a.grid(alpha=0.3)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.text(0.01, 0.005, t("精密軌道：瞬時半長軸以一個軌道週期滑動平均消去 J2 短週期項後取日中位數；7 日窗線性斜率。"
                            "排除含推進抬升（日變化率 > +20 m/日）或擬合殘差 > 40 m 之窗。NRLMSIS 彈道係數逐星全期單一常數，起伏來自模型密度。",
                            "Precise orbit: osculating SMA smoothed with a one-orbit moving average to remove J2 short-period "
                            "terms, then daily median; decay rate = linear slope over 7-day windows.\n"
                            "Windows with propulsive raising (daily change > +20 m/day) or fit residual > 40 m are excluded. "
                            "The NRLMSIS ballistic coefficient is one constant per satellite; variations come from the modeled density."),
             fontsize=8.5, color="#6B7280", va="top" if t("zh", "en") == "en" else "baseline")
    return fig


def pub():
    import fig_pub as fp
    A = pd.read_csv(BM / "fs7_precise_decay_windows.csv", parse_dates=["w"])
    C = pd.read_csv(BM / "fs7_precise_nrlmsis_corr.csv")
    fp.export_variants(lambda: draw(A, C), "fig_fs7_precise_nrlmsis")


if __name__ == "__main__":
    pub() if "--pub" in sys.argv else main()
