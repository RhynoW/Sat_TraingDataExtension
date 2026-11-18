"""NRLMSIS 能否重現衰減率隨太陽活動的起伏：2024-01 迄今，全期被動且 TLE 完整涵蓋之衛星。

每顆衛星的實測衰減率與 NRLMSIS 預期衰減率（7 日窗）都除以「該星 NRLMSIS 預期之中位數」，
消去高度與面質比造成的量級差，只留時間起伏；再依選星檔位分四個高度帶，逐週取各星中位數。
NRLMSIS 預期已逐星校準 B_eff（全期單一常數），因此曲線的起伏完全來自模型密度，非擬合。

輸入：data/benchmark/perigee_drag_corr_windows.csv.gz、perigee_drag_corr_persat.csv、nrlmsis_decay_expect.csv
輸出：docs/fig_nrlmsis_solar_tracking.png、data/benchmark/nrlmsis_solar_tracking_bands.csv
--pub：同輸入（不重算），輸出 docs/figures_pub/fig_nrlmsis_solar_tracking{_TAG}/ 中英 × 白底／黑底四版本
  例：python docs/gen_fig_nrlmsis_solar_tracking.py --pub --tag=x30（或環境變數 TAG=x30）
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "data/benchmark"
import os  # noqa: E402
import sys  # noqa: E402
_TAG = os.environ.get("TAG") or next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tag=")), "")
SUF = f"_{_TAG}" if _TAG else ""
BANDS = [("350–550 km", 300, 575), ("600–700 km", 575, 725), ("750–850 km", 725, 875), ("900–1000 km", 875, 1025)]


def load():
    A = pd.read_csv(BM / f"perigee_drag_corr_windows{SUF}.csv.gz", parse_dates=["w"])
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    keep = P[P.passive_all & (P.first_tle < "2024-02-01")]
    A = A[A.norad_id.isin(keep.norad_id)].copy()
    norm = A.groupby("norad_id").nrl_decay.transform("median")
    A["obs_n"], A["nrl_n"] = A.obs_decay / norm, A.nrl_decay / norm
    sw = pd.read_csv(BM / "nrlmsis_decay_expect.csv", parse_dates=["date"])
    return A, keep, sw


def main():
    A, keep, sw = load()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    rows = []
    fig = draw(A, keep, sw, rows)
    fig.savefig(ROOT / f"docs/fig_nrlmsis_solar_tracking{SUF}.png", bbox_inches="tight")
    R = pd.DataFrame(rows)
    R.round(3).to_csv(BM / f"nrlmsis_solar_tracking_bands{SUF}.csv", index=False, encoding="utf-8-sig")
    print(R.round(3).to_string(index=False))


def draw(A, keep, sw, rows=None):
    """繪圖（不設字型、不存檔），回傳 Figure；rows 若給 list 則附加各高度帶統計。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FixedLocator, FuncFormatter
    from fig_pub import t
    if rows is None:
        rows = []
    fig, axs = plt.subplots(len(BANDS) + 1, 1, figsize=(13, 13), dpi=150, sharex=True,
                            gridspec_kw={"height_ratios": [1] + [1.45] * len(BANDS), "hspace": 0.12})
    ax0 = axs[0]
    ax0.plot(sw.date, sw.f107, color="#9AA5B1", lw=0.7, label=t("F10.7 每日", "F10.7 daily"))
    ax0.plot(sw.date, sw.f107_81, color="#C2410C", lw=1.8, label=t("F10.7 81 日平均", "F10.7 81-day mean"))
    ax0.set_ylabel("F10.7 (sfu)")
    ax0.legend(loc="upper right", frameon=False, ncol=2, fontsize=9)
    ax0.set_title(t("太陽活動起伏與衰減率：TLE 實測 vs NRLMSIS 預期（2024-01 迄今，全期被動、TLE 完整涵蓋之衛星）",
                    "Solar activity and decay rate: TLE-observed vs NRLMSIS-expected "
                    "(2024-01 to date; passive satellites with full TLE coverage)"),
                  fontsize=12.5, loc="left")
    for ax, (lab, lo, hi) in zip(axs[1:], BANDS):
        ids = keep[(keep.bin >= lo) & (keep.bin < hi)].norad_id
        g = A[A.norad_id.isin(ids)].groupby("w")
        S = pd.DataFrame({"obs": g.obs_n.median(), "q1": g.obs_n.quantile(0.25), "q3": g.obs_n.quantile(0.75),
                          "nrl": g.nrl_n.median(), "n": g.size()})
        S = S[S.n >= max(2, len(ids) // 2)]
        r = pearsonr(S.obs, S.nrl)[0]
        rl = pearsonr(np.log10(S.obs.clip(lower=1e-3)), np.log10(S.nrl))[0]
        rs = keep[keep.norad_id.isin(ids)].r_pearson.median()
        rows.append({"band": lab, "n_sat": len(ids), "n_week": len(S), "r_band_median_series": r,
                     "r_log": rl, "persat_r_median": rs})
        ax.fill_between(S.index, S.q1, S.q3, color="#60A5FA", alpha=0.25, lw=0, label=t("實測（各星四分位距）", "Observed (inter-satellite IQR)"))
        ax.plot(S.index, S.obs, color="#1D4ED8", lw=1.3, marker="o", ms=2.2, label=t("TLE 實測（各星中位數）", "TLE observed (median of satellites)"))
        ax.plot(S.index, S.nrl, color="#C2410C", lw=2.0, label=t("NRLMSIS 預期（各星中位數）", "NRLMSIS expected (median of satellites)"))
        ax.set_yscale("log")
        lo_y = max(min(S.q1.min(), S.nrl.min()) * 0.8, 0.05)
        ax.set_ylim(lo_y, max(S.q3.max(), S.nrl.max()) * 2.2)
        ax.yaxis.set_major_locator(FixedLocator([0.05, 0.1, 0.2, 0.5, 1, 2, 5]))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
        ax.set_ylabel(t("衰減率\n（÷ 該星預期中位數）", "Decay rate\n(÷ satellite's expected median)"))
        ax.text(0.01, 0.95, t(f"{lab}　{len(ids)} 顆　週中位數序列 r = {r:.2f}　逐星 r 中位 = {rs:.2f}",
                              f"{lab}   {len(ids)} satellites   weekly-median series r = {r:.2f}   "
                              f"per-satellite median r = {rs:.2f}"),
                transform=ax.transAxes, va="top", fontsize=11, fontweight="bold", color="#1F2937",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=2))
        ax.legend(loc="lower left", frameon=False, fontsize=8.5, ncol=3)
    for ax in axs:
        ax.grid(alpha=0.3, which="major")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axs[-1].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axs[-1].set_xlim(pd.Timestamp("2024-01-01"), pd.Timestamp("2026-11-16"))
    fig.text(0.01, 0.075, t("NRLMSIS 預期之彈道係數為逐星全期單一常數（中位數校準），曲線起伏來自模型大氣密度（F10.7、Ap），非逐段擬合。"
                            "低軌帶之長期上升另含衛星高度下降之效應，NRLMSIS 亦依實際高度計入。",
                            "The NRLMSIS ballistic coefficient is one constant per satellite over the full period "
                            "(median-calibrated); the variations come from the modeled density (F10.7, Ap), not piecewise fitting.\n"
                            "The long-term rise in the lowest band also reflects the satellites' decreasing altitude, "
                            "which NRLMSIS includes through the actual altitude."),
             fontsize=8.5, color="#6B7280", va="top" if t("zh", "en") == "en" else "baseline")
    return fig


def pub():
    import fig_pub as fp
    A, keep, sw = load()
    fp.export_variants(lambda: draw(A, keep, sw), f"fig_nrlmsis_solar_tracking{SUF}")


if __name__ == "__main__":
    pub() if "--pub" in sys.argv else main()
