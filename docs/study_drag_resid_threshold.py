"""阻力殘差門檻研討：被動衛星逐筆 TLE 之殘差分布、現行 0.3 km 門檻之誤報率，與依高度調整之門檻方案。

只做分析與建議，不改正式偵測程式。
輸入：analyze_perigee_drag_corr.py 之逐星快取（TAG=x30 → perigee_drag_cache_x30）與 persat 表（passive_all）。
對象：全期被動衛星（期間內無相鄰 TLE Δa > +0.3 km）之逐筆轉換，轉換間隔 ≤ 3 日。

方案：
  A 現行：|殘差| > 0.30 km
  B 等誤報率查表：各 50 km 高度檔取最小門檻，使被動衛星誤報率 ≤ 目標（預設每千星日 0.43 件，
    與 L1 候選事件於 IDS 安靜期之誤報率相同）；下限 0.03 km
  C 高度公式：log10(門檻) 對高度線性擬合 B 之結果（樣本 ≥ 3,000 筆轉換之檔），門檻 = 10^(a + b·h)，下限 0.03 km
評估：誤報率（每千星日之超門檻次數，48 小時內合併為一次）；注入測試之 90% 偵測下限（km）。
輸出：data/benchmark/drag_thr_*.csv、docs/fig_drag_resid_threshold.png
--pub：只讀 drag_thr_by_alt{_TAG}.csv 與 drag_thr_summary{_TAG}.csv（不重算），輸出 docs/figures_pub/fig_drag_resid_threshold/ 中英 × 白底／黑底四版本
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "data/benchmark"
TAG = os.environ.get("TAG", "x30")
SUF = f"_{TAG}" if TAG else ""
CACHE = BM / f"perigee_drag_cache{SUF}"
RNG = np.random.default_rng(20261116)


def load():
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    rows = []
    for nid in P[P.passive_all].norad_id:
        f = CACHE / f"{nid}.csv.gz"
        if not f.exists():
            continue
        r = pd.read_csv(f, usecols=["epoch", "da_km", "drag_pred_da", "drag_resid_da", "alt_km", "dt_d"])
        r = r[(r.dt_d > 0) & (r.dt_d <= 3)].copy()
        r["norad_id"] = nid
        rows.append(r)
    T = pd.concat(rows, ignore_index=True)
    T["epoch"] = pd.to_datetime(T.epoch, utc=True)
    T["hbin"] = (T.alt_km / 50).round() * 50
    T = T[T.hbin.between(300, 1000)]
    return T


def events_per_ksd(T, flag):
    """超門檻點依星、48 小時合併為事件；回傳每千星日事件數。"""
    n = 0
    for _, g in T[flag].groupby("norad_id"):
        t = g.epoch.sort_values().astype("int64").to_numpy() / 1e9
        n += 1 + int((np.diff(t) > 48 * 3600).sum()) if len(t) else 0
    return n / (T.dt_d.sum() / 1000)


def main():
    T = load()
    print("轉換", len(T), "衛星", T.norad_id.nunique(), "星日", round(T.dt_d.sum()))
    absr = T.drag_resid_da.abs()
    target = float(os.environ.get("FP_TARGET", 0.43))
    zA = absr > 0.30
    grid = np.round(np.concatenate([np.arange(0.03, 0.30, 0.01), np.arange(0.30, 3.01, 0.05)]), 3)
    thrB = {}
    for h, g in T.groupby("hbin"):
        a = g.drag_resid_da.abs()
        thrB[h] = next((t for t in grid if events_per_ksd(g, a > t) <= target), grid[-1])
    thrB = pd.Series(thrB)
    ns = T.groupby("hbin").size()
    fitm = ns[ns >= 3000].index
    b_, a_ = np.polyfit(fitm.to_numpy(float), np.log10(thrB[fitm].to_numpy(float)), 1)
    T["thrB"] = T.hbin.map(thrB)
    T["thrC"] = np.maximum(10 ** (a_ + b_ * T.alt_km), 0.03)
    k_star, f_rel = a_, b_

    rows = []
    for h, g in T.groupby("hbin"):
        a = g.drag_resid_da.abs()
        row = {"hbin": h, "n_sat": g.norad_id.nunique(), "n_trans": len(g), "sat_days": g.dt_d.sum(),
               "pred_med_km": g.drag_pred_da.abs().median(),
               "p99_km": a.quantile(0.99), "p999_km": a.quantile(0.999),
               "fp_A_per_ksd": events_per_ksd(g, a > 0.30), "exceed_A_pct": 100 * (a > 0.30).mean(),
               "thrB_km": thrB[h], "fp_B_per_ksd": events_per_ksd(g, a > g.thrB),
               "thrC_med_km": g.thrC.median(), "fp_C_per_ksd": events_per_ksd(g, a > g.thrC)}
        # 注入：於隨機轉換加上 ±s 之 Δa，偵測率達 90% 之最小 s
        idx = RNG.choice(len(g), size=min(len(g), 3000), replace=False)
        rr, tb, tc = g.drag_resid_da.to_numpy()[idx], g.thrB.to_numpy()[idx], g.thrC.to_numpy()[idx]
        sign = RNG.choice([-1, 1], size=len(idx))
        for lab, thr in (("A", np.full(len(idx), 0.30)), ("B", tb), ("C", tc)):
            det = None
            for sz in np.arange(0.02, 3.01, 0.01):
                if (np.abs(rr + sign * sz) > thr).mean() >= 0.9:
                    det = sz
                    break
            row[f"min90_{lab}_km"] = det
        rows.append(row)
    S = pd.DataFrame(rows)
    S.round(4).to_csv(BM / f"drag_thr_by_alt{SUF}.csv", index=False, encoding="utf-8-sig")
    summ = {"轉換數": len(T), "被動衛星": T.norad_id.nunique(), "星日": T.dt_d.sum(),
            "A 全體誤報（每千星日）": events_per_ksd(T, zA), "A 300–450 km 誤報": events_per_ksd(T[T.hbin <= 450], zA[T.hbin <= 450]),
            "A 600–1000 km 誤報": events_per_ksd(T[T.hbin >= 600], zA[T.hbin >= 600]), "誤報目標": target,
            "C 公式 a（log10 km）": a_, "C 公式 b（每 km）": b_,
            "C 門檻 @300/500/700/1000 km": "/".join(f"{max(10 ** (a_ + b_ * h), 0.03):.3f}" for h in (300, 500, 700, 1000)),
            "B 全體誤報": events_per_ksd(T, absr > T.thrB), "C 全體誤報": events_per_ksd(T, absr > T.thrC)}
    pd.Series(summ).to_csv(BM / f"drag_thr_summary{SUF}.csv", header=["value"], encoding="utf-8-sig")
    for k, v in summ.items():
        print(f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}")
    print(S.round(3).to_string(index=False))
    S.attrs["fit"] = (a_, b_)
    plot(T, S, k_star, f_rel)


def plot(T, S, k_star, f_rel):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig = draw(S, k_star, f_rel)
    fig.savefig(ROOT / "docs/fig_drag_resid_threshold.png", bbox_inches="tight")
    print("fig saved")


def draw(S, k_star, f_rel):
    """繪圖（不設字型、不存檔），回傳 Figure；預設輸出與 --pub 四版本共用。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    from fig_pub import t
    fmt = FuncFormatter(lambda v, _: f"{v:g}")
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.4), dpi=150)
    x = S.hbin
    ax[0].fill_between(x, 0.001, S.p99_km, color="#BFDBFE", label=t("被動衛星 |殘差| P99", "Passive satellites |residual| P99"))
    ax[0].plot(x, S.p999_km, color="#93C5FD", lw=1, label=t("|殘差| P99.9", "|residual| P99.9"))
    ax[0].plot(x, S.thrB_km, color="#1D4ED8", lw=2, marker="o", ms=4, label=t("B 等誤報率門檻", "B equal-false-alarm threshold"))
    hh = np.linspace(300, 1000, 50)
    ax[0].plot(hh, np.maximum(10 ** (k_star + f_rel * hh), 0.03), color="#059669", lw=2, label=t("C 高度公式", "C altitude formula"))
    ax[0].axhline(0.30, color="#B91C1C", lw=2, ls="--", label=t("現行 0.30 km", "Current 0.30 km"))
    ax[0].plot(x, S.pred_med_km, color="#6B7280", lw=1, ls=":", label=t("每筆預期阻力 Δa 中位", "Median expected drag Δa per transition"))
    ax[0].set(yscale="log", ylim=(0.005, 5), xlabel=t("近地點高度（km）", "Perigee altitude (km)"),
              ylabel=t("km（每筆相鄰 TLE）", "km (per adjacent-TLE pair)"),
              title=t("(a) 殘差分布與門檻", "(a) Drag-residual distribution and thresholds"))
    ax[0].yaxis.set_major_formatter(fmt)
    ax[0].legend(fontsize=8.5, frameon=False, loc="upper right")
    w = 14
    ax[1].bar(x - w, S.fp_A_per_ksd, 2 * w * 0.95, color="#B91C1C", label=t("A 現行 0.30 km", "A current 0.30 km"))
    ax[1].bar(x + w, S.fp_C_per_ksd, 2 * w * 0.95, color="#059669", label=t("C 高度公式", "C altitude formula"))
    ax[1].plot(x, S.fp_B_per_ksd, color="#1D4ED8", marker="o", lw=1.5, label=t("B 等誤報率查表", "B equal-false-alarm lookup"))
    ax[1].axhline(float(os.environ.get("FP_TARGET", 0.43)), color="#6B7280", ls=":", lw=1, label=t("目標（每千星日 0.43 件）", "Target (0.43 per 1,000 satellite-days)"))
    ax[1].set(xlabel=t("近地點高度（km）", "Perigee altitude (km)"),
              ylabel=t("誤報事件／千星日（被動衛星）", "False alarms per 1,000 satellite-days (passive)"),
              title=t("(b) 各高度誤報率", "(b) False-alarm rate by altitude"))
    ax[1].legend(fontsize=9, frameon=False)
    ax[2].plot(x, S.min90_A_km, color="#B91C1C", marker="o", lw=2, label=t("A 現行 0.30 km", "A current 0.30 km"))
    ax[2].plot(x, S.min90_B_km, color="#1D4ED8", marker="o", lw=1.5, label=t("B 等誤報率查表", "B equal-false-alarm lookup"))
    ax[2].plot(x, S.min90_C_km, color="#059669", marker="s", lw=2, label=t("C 高度公式", "C altitude formula"))
    ax[2].set(yscale="log", xlabel=t("近地點高度（km）", "Perigee altitude (km)"),
              ylabel=t("90% 偵測之最小 |Δa|（km）", "Minimum |Δa| for 90% detection (km)"),
              title=t("(c) 注入測試：可偵測下限", "(c) Injection test: detection floor"))
    ax[2].yaxis.set_major_formatter(fmt)
    ax[2].legend(fontsize=9, frameon=False)
    for a in ax:
        a.grid(alpha=0.3, which="both")
        for s_ in ("top", "right"):
            a.spines[s_].set_visible(False)
    fig.text(0.01, -0.02, t(f"對象：全期被動衛星逐筆相鄰 TLE（間隔不超過 3 日），殘差＝實測 Δa 減 NRLMSIS 預期 Δa。誤報：超門檻點依星 48 小時內合併為一次。"
                            f"方案 C：log10(門檻 km) = {k_star:.2f} {'−' if f_rel < 0 else '+'} {abs(f_rel) * 1000:.2f} × 高度(km)/1000，下限 0.03 km。",
                            f"Sample: adjacent-TLE pairs (≤ 3 days apart) of satellites passive throughout; residual = observed Δa "
                            f"− NRLMSIS-expected Δa. False alarms: exceedances merged per satellite within 48 h.\n"
                            f"Scheme C: log10(threshold, km) = {k_star:.2f} {'−' if f_rel < 0 else '+'} {abs(f_rel) * 1000:.2f} × altitude(km)/1000, floor 0.03 km."),
             fontsize=8.5, color="#6B7280")
    fig.tight_layout()
    return fig


def pub():
    """--pub：讀既有 drag_thr_by_alt／drag_thr_summary（不重算），輸出四版本。"""
    import fig_pub as fp
    S = pd.read_csv(BM / f"drag_thr_by_alt{SUF}.csv")
    summ = pd.read_csv(BM / f"drag_thr_summary{SUF}.csv", index_col=0)["value"]
    k_star, f_rel = float(summ["C 公式 a（log10 km）"]), float(summ["C 公式 b（每 km）"])
    fp.export_variants(lambda: draw(S, k_star, f_rel), "fig_drag_resid_threshold")


if __name__ == "__main__":
    pub() if "--pub" in sys.argv else main()
