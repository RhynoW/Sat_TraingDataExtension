"""generate_maneuver_app_figures.py
產生 maneuver_app.py 進度章節所需的案例圖表（NORAD 44349 TLE 缺口守門案例）。
資料來源：即時從 space_db.duckdb 重新計算（呼叫 maneuver_app.py 的真實函式)。
執行：python docs/generate_maneuver_app_figures.py
"""
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family":        "Microsoft YaHei",
    "axes.unicode_minus": False,
    "figure.dpi":         150,
    "savefig.dpi":        200,
    "savefig.bbox":       "tight",
})

OUT = os.path.dirname(os.path.abspath(__file__))
R_EARTH = 6371.0
TLE_GAP_SUPPRESS_H = 48.0


def fig11_gap_suppression_case():
    import sys
    sys.path.insert(0, os.path.join(OUT, ".."))
    import maneuver_app as m

    df = m.load_data("44349", "2026-02-08", "2026-07-05")
    models = m.load_ml_models()
    feat_cols = models.get("lgbm_feat_cols") or []
    f107 = m.fetch_f107_data()
    f107["epoch"] = pd.to_datetime(f107["epoch"])
    f107_mean = float(f107.loc[
        (f107["epoch"] >= pd.Timestamp("2026-02-08")) & (f107["epoch"] <= pd.Timestamp("2026-07-05")),
        "f107"
    ].mean())

    roll = m.compute_lgbm_rolling_predictions(
        df, models["lgbm"], feat_cols, f107_mean=f107_mean, window_days=26, step_days=3
    )
    roll["gap_suppressed"] = roll["max_tle_gap_h"] > TLE_GAP_SUPPRESS_H
    roll["is_alert"] = (roll["p_maneuver"] >= 0.5) & ~roll["gap_suppressed"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [1.3, 1]})

    colors = [
        "#FF9800" if (gs and p >= 0.5) else ("#F44336" if a else "#26C6DA")
        for p, a, gs in zip(roll["p_maneuver"], roll["is_alert"], roll["gap_suppressed"])
    ]
    ax1.plot(roll["window_center"], roll["p_maneuver"], "-", color="#26C6DA", lw=1.5, zorder=1)
    ax1.scatter(roll["window_center"], roll["p_maneuver"], c=colors, s=45, zorder=2,
                edgecolor="white", linewidth=0.5)
    ax1.axhline(0.5, color="orange", ls="--", lw=1.2, label="判定閾值 50%")

    for _, r in roll[roll["gap_suppressed"] & (roll["p_maneuver"] >= 0.5)].iterrows():
        ax1.axvspan(r["window_center"] - pd.Timedelta(days=1.5),
                    r["window_center"] + pd.Timedelta(days=1.5),
                    color="#FF9800", alpha=0.12, zorder=0)

    ax1.set_ylabel("機動機率 p_maneuver", fontsize=11)
    ax1.set_ylim(-0.05, 1.05)
    ax1.set_title("(a) LightGBM 機動機率（橘色＝資料缺口 >48h，判定壓制為非機動）",
                   fontsize=11, fontweight="bold")
    ax1.legend(loc="center left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.plot(df["epoch"], df["sma_km"], color="#FFD54F", lw=1.3)
    ax2_r = ax2.twinx()
    ax2_r.plot(roll["window_center"], roll["max_tle_gap_h"], "o--", color="#8888ff",
               lw=1, ms=3, alpha=0.8)
    ax2_r.axhline(TLE_GAP_SUPPRESS_H, color="#8888ff", ls=":", lw=1)
    ax2_r.set_ylabel("視窗內最長 TLE 缺口（小時）", fontsize=10, color="#5555cc")
    ax2_r.tick_params(axis="y", labelcolor="#5555cc")

    ax2.set_ylabel("SMA（km）", fontsize=11)
    ax2.set_xlabel("日期", fontsize=10)
    ax2.set_title("(b) 半長軸走勢（平緩連續下降）與視窗內最長 TLE 缺口", fontsize=11, fontweight="bold")
    ax2.grid(True, alpha=0.3)

    fig.suptitle("圖十一：NORAD 44349 TLE 資料缺口守門案例（2026-02-08～2026-07-05）\n"
                  "半長軸持續平緩衰減，機率假警報由追蹤缺口（非真實機動）驅動，經守門後正確壓制",
                  fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig11_gap_suppression_case.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")
    print(f"  raw alerts (p>=0.5): {int((roll['p_maneuver']>=0.5).sum())}  "
          f"-> after suppression: {int(roll['is_alert'].sum())}")


if __name__ == "__main__":
    print("產生 maneuver_app.py 案例圖片中...")
    fig11_gap_suppression_case()
    print("完成。")
