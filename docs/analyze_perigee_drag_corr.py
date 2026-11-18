"""近地點分檔 150 顆衛星（2024-01 迄今）：實測衰減與 NRLMSIS 預期、阻力殘差之相關分析。

輸入：data/benchmark/perigee_bin_selection.csv（docs/select_perigee_bins.py 產生）
方法：
  1. 逐星以 atmospheric_drag.drag_residual 計算逐轉換 Δa、NRLMSIS 預測 Δa（軌道平均密度、逐星中位數校準 B_eff）
     與殘差＝實測 − 預測。
  2. 彙整為 7 日窗：實測衰減率、預測衰減率、殘差率（m/日）、平均近地點高度。
     排除：窗內轉換涵蓋 < 4 日、任一轉換跨 > 3 日、任一轉換 |殘差| > 1 km（疑似機動或 TLE 異常）。
  3. 相關係數：
     A 逐星時間相關：實測衰減率 vs NRLMSIS 預期衰減率（Pearson r、Spearman ρ）
     B 跨高度：近地點高度 vs log10 衰減率（實測、預期）；log10 實測 vs log10 預期
     C 殘差：高度 vs 殘差 RMS／相對殘差（逐星，Spearman）；殘差 vs 預期衰減率（逐窗，各檔）
輸出：data/benchmark/perigee_drag_corr_*.csv、docs/fig_perigee_drag_corr.png
--pub：只讀上述快取 CSV（不重算、不連 DB），輸出 docs/figures_pub/fig_perigee_drag_corr{_TAG}/ 中英 × 白底／黑底四版本
  例：python docs/analyze_perigee_drag_corr.py --pub --tag=x30
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
OUT = ROOT / "data/benchmark"
T0 = "2024-01-01"
TAG = os.environ.get("TAG", "") or next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tag=")), "")  # 例：TAG=x30 或 --tag=x30 → 擴大版（選星檔、快取、輸出皆加後綴）
SUF = f"_{TAG}" if TAG else ""
CACHE = ROOT / f"data/benchmark/perigee_drag_cache{SUF}"
BACKFILL = ROOT / "data/benchmark/perigee_backfill"
MU = 398600.4418
_BF = None


def backfill_rows(nid):
    """Space-Track 補回之 TLE（docs/backfill_perigee_tle.py），轉成與 raw_tle_archive 同欄位。"""
    global _BF
    if _BF is None:
        import gzip
        recs = []
        for f in sorted(BACKFILL.glob("batch_*.tle.gz")):
            lines = [ln.rstrip() for ln in gzip.open(f, "rt", encoding="ascii") if ln.strip()]
            for l1, l2 in zip(lines[0::2], lines[1::2]):
                if not (l1.startswith("1 ") and l2.startswith("2 ")):
                    continue
                yy, doy = int(l1[18:20]), float(l1[20:32])
                ep = pd.Timestamp(year=2000 + yy if yy < 57 else 1900 + yy, month=1, day=1, tz="UTC") + pd.Timedelta(days=doy - 1)
                n = float(l2[52:63]) * 2 * np.pi / 86400
                recs.append((int(l1[2:7]), ep, (MU / n ** 2) ** (1 / 3), float("0." + l2[26:33].strip()), l1, l2))
        _BF = pd.DataFrame(recs, columns=["norad_id", "epoch", "sma_km", "eccentricity", "line1", "line2"])
    return _BF[_BF.norad_id == int(nid)].drop(columns="norad_id")


def one(nid):
    f = CACHE / f"{nid}.csv.gz"
    if f.exists():
        return nid, "cached"
    import duckdb
    from atmospheric_drag import drag_residual, load_space_weather
    sw = load_space_weather()
    c = duckdb.connect("space_db.duckdb", read_only=True)
    df = c.execute("select epoch_utc epoch, sma_km, eccentricity, line1, line2 from raw_tle_archive "
                   "where norad_id=? and epoch_utc>=? and sma_km is not null order by 1", [int(nid), T0]).df()
    c.close()
    df["epoch"] = pd.to_datetime(df.epoch, utc=True)
    if TAG:
        df = pd.concat([backfill_rows(nid), df], ignore_index=True)
        df["epoch"] = pd.to_datetime(df.epoch, utc=True)
    df = df.sort_values("epoch")
    df = df[df.epoch.diff().dt.total_seconds().fillna(1e9).abs() > 60]          # 重複曆元（≤ 60 s）去除
    if len(df) < 20:
        return nid, "few"
    r = drag_residual(df, sw)
    if r.empty:
        return nid, "empty"
    ep = pd.to_datetime(df.epoch, utc=True).sort_values()
    r["dt_d"] = ep.diff().dt.total_seconds().to_numpy()[1:] / 86400    # drag_residual 逐轉換，長度 = n − 1
    r["B_eff"] = r.attrs.get("B_eff")
    r.to_csv(f, index=False, compression="gzip")
    return nid, len(r)


def windows(nid, r):
    r = r.copy()
    r["epoch"] = pd.to_datetime(r.epoch, utc=True)
    r = r[r.epoch >= pd.Timestamp(T0, tz="UTC")]
    r["w"] = r.epoch.dt.floor("7D")
    g = r.groupby("w")
    W = pd.DataFrame({
        "days": g.dt_d.sum(), "maxdt": g.dt_d.max(), "maxres": g.drag_resid_da.apply(lambda s: s.abs().max()),
        "da": g.da_km.sum(), "pred": g.drag_pred_da.sum(), "res": g.drag_resid_da.sum(), "alt": g.alt_km.mean()})
    W = W[(W.days >= 4) & (W.maxdt <= 3) & (W.maxres <= 1.0)]
    W["obs_decay"] = -W.da * 1000 / W.days          # m/日，正值＝下降
    W["nrl_decay"] = -W.pred * 1000 / W.days
    W["res_rate"] = W.res * 1000 / W.days
    W["norad_id"] = nid
    return W.reset_index()


def main():
    sel = pd.read_csv(OUT / f"perigee_bin_selection{SUF}.csv")
    CACHE.mkdir(exist_ok=True)
    if TAG:
        backfill_rows(0)
    with ProcessPoolExecutor(max_workers=int(os.environ.get("NPROC", 8))) as ex:
        for nid, st in ex.map(one, sel.norad_id):
            print(nid, st, flush=True)

    from scipy.stats import pearsonr, spearmanr
    allw, per = [], []
    for _, s in sel.iterrows():
        f = CACHE / f"{s.norad_id}.csv.gz"
        if not f.exists():
            continue
        W = windows(s.norad_id, pd.read_csv(f))
        if len(W) < 10:
            continue
        W["bin"] = s.bin
        raw = pd.read_csv(f, usecols=["epoch", "da_km", "dt_d", "B_eff"])
        n_up = int(((raw.dt_d <= 3) & (raw.da_km > 0.3)).sum())      # 全期抬升次數（相鄰 TLE Δa > 0.3 km）
        W["passive"] = n_up == 0
        allw.append(W)
        ok = (W.nrl_decay > 0)
        pr = pearsonr(W.obs_decay[ok], W.nrl_decay[ok])[0] if ok.sum() > 5 else np.nan
        sp = spearmanr(W.obs_decay[ok], W.nrl_decay[ok])[0] if ok.sum() > 5 else np.nan
        per.append({"bin": s.bin, "norad_id": s.norad_id, "object_name": s.object_name, "n_win": len(W),
                    "alt_mean": W.alt.mean(), "obs_decay_med": W.obs_decay.median(), "nrl_decay_med": W.nrl_decay.median(),
                    "r_pearson": pr, "rho_spearman": sp,
                    "res_rms": np.sqrt((W.res_rate ** 2).mean()),
                    "res_rel": np.sqrt((W.res_rate ** 2).mean()) / max(W.nrl_decay.median(), 1e-6),
                    "B_eff": raw.B_eff.iloc[0], "n_up03_all": n_up, "passive_all": n_up == 0,
                    "first_tle": str(pd.to_datetime(raw.epoch.iloc[0], utc=True).date())})
    A = pd.concat(allw, ignore_index=True)
    P = pd.DataFrame(per)
    P.round(4).to_csv(OUT / f"perigee_drag_corr_persat{SUF}.csv", index=False, encoding="utf-8-sig")

    # 依當時高度（非選星時高度）分 50 km 檔之逐窗統計
    A["alt_bin"] = (A.alt / 50).round() * 50
    rows = []
    for b, g in A.groupby("bin"):
        pos = (g.obs_decay > 0) & (g.nrl_decay > 0)
        rows.append({"bin": b, "n_sat": g.norad_id.nunique(), "n_win": len(g),
                     "r_obs_nrl_pooled": pearsonr(g.obs_decay, g.nrl_decay)[0],
                     "rho_obs_nrl_pooled": spearmanr(g.obs_decay, g.nrl_decay)[0],
                     "r_log_pooled": pearsonr(np.log10(g.obs_decay[pos]), np.log10(g.nrl_decay[pos]))[0] if pos.sum() > 5 else np.nan,
                     "persat_r_median": P[P.bin == b].r_pearson.median(),
                     "n_passive": int(P[P.bin == b].passive_all.sum()),
                     "persat_r_median_passive": P[(P.bin == b) & P.passive_all].r_pearson.median(),
                     "persat_r_pos_share": (P[P.bin == b].r_pearson > 0).mean(),
                     "rho_res_vs_nrl": spearmanr(g.res_rate.abs(), g.nrl_decay)[0],
                     "obs_decay_med": g.obs_decay.median(), "nrl_decay_med": g.nrl_decay.median(),
                     "res_rms_med": P[P.bin == b].res_rms.median(), "res_rel_med": P[P.bin == b].res_rel.median()})
    B = pd.DataFrame(rows)
    B.round(4).to_csv(OUT / f"perigee_drag_corr_bins{SUF}.csv", index=False, encoding="utf-8-sig")

    pos = (A.obs_decay > 0) & (A.nrl_decay > 0)
    g = {
        "逐窗 n": len(A), "衛星數": A.norad_id.nunique(),
        "高度 vs log10 實測衰減 Spearman（逐星）": spearmanr(P.alt_mean, np.log10(P.obs_decay_med.clip(lower=1e-3)))[0],
        "高度 vs log10 NRLMSIS 衰減 Spearman（逐星）": spearmanr(P.alt_mean, np.log10(P.nrl_decay_med.clip(lower=1e-3)))[0],
        "log10 實測 vs log10 NRLMSIS Pearson（逐窗，正值者）": pearsonr(np.log10(A.obs_decay[pos]), np.log10(A.nrl_decay[pos]))[0],
        "逐星時間相關 r 中位（全部）": P.r_pearson.median(),
        "逐星時間相關 r > 0 比例": (P.r_pearson > 0).mean(),
        "高度 vs 殘差 RMS Spearman（逐星）": spearmanr(P.alt_mean, P.res_rms)[0],
        "高度 vs 相對殘差 Spearman（逐星）": spearmanr(P.alt_mean, P.res_rel)[0],
        "NRLMSIS 預期 vs |殘差| Spearman（逐窗）": spearmanr(A.nrl_decay, A.res_rate.abs())[0],
        "全期被動衛星數": int(P.passive_all.sum()),
        "全期被動：逐星時間相關 r 中位": P[P.passive_all].r_pearson.median(),
        "全期被動：r > 0.5 比例": (P[P.passive_all].r_pearson > 0.5).mean(),
        "有抬升紀錄：逐星時間相關 r 中位": P[~P.passive_all].r_pearson.median(),
        "TLE 自 2024-01 起之衛星數": int((P.first_tle < "2024-02-01").sum()),
        "2024 起涵蓋者：逐星 r 中位（全期被動）": P[P.passive_all & (P.first_tle < "2024-02-01")].r_pearson.median(),
    }
    pd.Series(g).to_csv(OUT / f"perigee_drag_corr_global{SUF}.csv", header=["value"], encoding="utf-8-sig")
    for k, v in g.items():
        print(f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}")
    print(B.round(3).to_string(index=False))
    A.to_csv(OUT / f"perigee_drag_corr_windows{SUF}.csv.gz", index=False, compression="gzip")
    plot(A, P, B)


def plot(A, P, B):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "dejavusans"
    fig = draw(A, P, B)
    fig.savefig(ROOT / f"docs/fig_perigee_drag_corr{SUF}.png")
    print("fig saved")


def draw(A, P, B):
    """繪圖（不設字型、不存檔），回傳 Figure；預設輸出與 --pub 四版本共用。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from fig_pub import t
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.6), dpi=150)
    cm = plt.get_cmap("viridis")
    bins = sorted(B.bin)
    col = {b: cm(i / (len(bins) - 1)) for i, b in enumerate(bins)}
    # (a) 實測 vs NRLMSIS（逐窗，log-log）
    pos = (A.obs_decay > 0) & (A.nrl_decay > 0)
    for b in bins:
        m = pos & (A.bin == b)
        ax[0].scatter(A.nrl_decay[m], A.obs_decay[m], s=3, alpha=0.25, color=col[b], rasterized=True)
    lim = [1e-2, 3e3]
    ax[0].plot(lim, lim, color="#444", lw=1, ls="--", label="1:1")
    ax[0].set(xscale="log", yscale="log", xlim=lim, ylim=lim, xlabel=t("NRLMSIS 預期衰減率（m/日，已逐星校準 B_eff）", "NRLMSIS expected decay rate (m/day, per-satellite B_eff)"),
              ylabel=t("TLE 實測衰減率（m/日）", "TLE-observed decay rate (m/day)"),
              title=t("(a) 7 日窗：實測 vs NRLMSIS 預期", "(a) 7-day windows: observed vs NRLMSIS expected"))
    ax[0].legend(loc="upper left", frameon=False)
    sm = plt.cm.ScalarMappable(cmap=cm, norm=plt.Normalize(min(bins), max(bins)))
    fig.colorbar(sm, ax=ax[0], fraction=0.046, pad=0.02).set_label(t("選星時近地點檔位（km）", "Perigee bin at selection (km)"))
    # (b) 各檔逐星時間相關 r
    data = [P[(P.bin == b) & P.passive_all].r_pearson.dropna() for b in bins]
    bp = ax[1].boxplot(data, positions=range(len(bins)), widths=0.6, patch_artist=True, showfliers=True)
    for patch, b in zip(bp["boxes"], bins):
        patch.set_facecolor(col[b]); patch.set_alpha(0.6)
    act = P[~P.passive_all]
    ax[1].scatter([bins.index(b) for b in act.bin], act.r_pearson, marker="x", color="#B91C1C", s=26, zorder=3,
                  label=t("期間內有抬升紀錄（不納入箱形）", "Orbit raising during period (not in boxes)"))
    ax[1].legend(loc="lower left", frameon=False, fontsize=9)
    ax[1].axhline(0, color="#999", lw=0.8)
    ax[1].set_xticks(range(len(bins)), [str(int(b)) for b in bins], rotation=45)
    ax[1].set(xlabel=t("選星時近地點檔位（km）", "Perigee bin at selection (km)"),
              ylabel=t("Pearson r（逐星，2024-01 迄今）", "Pearson r (per satellite, 2024-01 to date)"),
              title=t("(b) 逐星時間相關（箱形＝全期被動衛星）", "(b) Per-satellite temporal correlation\n(boxes = passive throughout)"), ylim=(-1, 1))
    # (c) 殘差 RMS 與相對殘差 vs 高度
    Pp, Pa = P[P.passive_all], P[~P.passive_all]
    ax[2].scatter(Pp.alt_mean, Pp.res_rms, s=14, color="#2563EB", label=t("殘差 RMS（m/日）", "Residual RMS (m/day)"))
    ax[2].scatter(Pp.alt_mean, Pp.res_rel, s=14, color="#EA580C", marker="^", label=t("相對殘差（RMS ÷ 預期衰減）", "Relative residual (RMS ÷ expected decay)"))
    ax[2].scatter(Pa.alt_mean, Pa.res_rms, s=14, facecolors="none", edgecolors="#2563EB", label=t("（空心＝有抬升紀錄）", "(open = orbit-raising record)"))
    ax[2].scatter(Pa.alt_mean, Pa.res_rel, s=14, facecolors="none", edgecolors="#EA580C", marker="^")
    ax[2].set(yscale="log", xlabel=t("平均近地點高度（km，2024-01 迄今）", "Mean perigee altitude (km, 2024-01 to date)"), ylabel="",
              title=t("(c) 阻力殘差與高度", "(c) Drag residual vs altitude"))
    ax[2].legend(frameon=False, fontsize=9)
    from matplotlib.ticker import FuncFormatter, LogLocator
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    for a_, axis in ((ax[0], "x"), (ax[0], "y"), (ax[2], "y")):
        getattr(a_, f"{axis}axis").set_major_locator(LogLocator(base=10))
        getattr(a_, f"{axis}axis").set_major_formatter(fmt)
    for a in ax:
        a.grid(alpha=0.3, which="both")
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.tight_layout()
    return fig


def pub():
    """--pub：讀既有快取 CSV（逐窗、逐星、分檔），輸出四版本。"""
    import fig_pub as fp
    A = pd.read_csv(OUT / f"perigee_drag_corr_windows{SUF}.csv.gz")
    P = pd.read_csv(OUT / f"perigee_drag_corr_persat{SUF}.csv")
    B = pd.read_csv(OUT / f"perigee_drag_corr_bins{SUF}.csv")
    fp.export_variants(lambda: draw(A, P, B), f"fig_perigee_drag_corr{SUF}")


if __name__ == "__main__":
    pub() if "--pub" in sys.argv else main()
