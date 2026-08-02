"""generate_paper1_extended_figures.py
產生論文一「擴充驗證」章節（P5/P6、54 天全量評估）所需的圖表。
所有數字直接讀取 leo_annotator/output/ 的真實計算結果，非示意數據。
執行：python docs/generate_paper1_extended_figures.py
"""
import os
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
LEO_OUT = os.path.join(OUT, "..", "leo_annotator", "output")


# ─────────────────────────────────────────────────────────────────────────────
# 圖七：Recall@N 信心排名曲線
# ─────────────────────────────────────────────────────────────────────────────
def fig7_recall_at_n():
    df = pd.read_csv(os.path.join(LEO_OUT, "recall_at_n.csv"))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(df["N"], df["Recall@N"] * 100, "o-", color="#2266cc", lw=2, ms=7)
    ax1.set_xscale("log")
    ax1.set_xlabel("N（依信心分數 max_da_km 降冪取前 N 筆）", fontsize=10)
    ax1.set_ylabel("Recall@N（%）", fontsize=10)
    ax1.set_title("(a) Recall@N 曲線", fontsize=11, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    for _, r in df.iterrows():
        ax1.annotate(f"{r['Recall@N']*100:.1f}%", (r["N"], r["Recall@N"] * 100),
                     textcoords="offset points", xytext=(0, 8), fontsize=8, ha="center")

    ax2.plot(df["N"], df["Precision@N"] * 100, "s-", color="#cc6622", lw=2, ms=7)
    ax2.set_xscale("log")
    ax2.set_ylim(80, 102)
    ax2.set_xlabel("N", fontsize=10)
    ax2.set_ylabel("Precision@N（%）", fontsize=10)
    ax2.set_title("(b) Precision@N 曲線", fontsize=11, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    for _, r in df.iterrows():
        ax2.annotate(f"{r['Precision@N']*100:.1f}%", (r["N"], r["Precision@N"] * 100),
                     textcoords="offset points", xytext=(0, 8), fontsize=8, ha="center")

    fig.suptitle("圖七：Recall@N / Precision@N 信心排名評估\n"
                  "（P1–P6，54 天全量，14,090 顆 LEO 衛星）",
                  fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig7_recall_at_n.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖八：跨星系分層 Recall / FAR
# ─────────────────────────────────────────────────────────────────────────────
def fig8_constellation():
    # 直接取自 recall_at_n_report.txt 的「各星系分層 Recall / FAR」表
    rows = [
        ("Starlink",   9805, 9805, 2650,  0, 27.0, 0.0),
        ("Kuiper",      210,  210,   61,  0, 29.0, 0.0),
        ("PRC_Recon",   186,    9,    6, 13, 66.7, 7.0),
        ("ISS_Complex",   7,    0,    0,  6, np.nan, 85.7),
        ("Other",      3713,  159,   27,143, 17.0, 3.9),
    ]
    cols = ["星系", "N", "GT+", "TP", "FP", "Recall", "FAR"]
    df = pd.DataFrame(rows, columns=cols)

    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(df))
    w = 0.35

    recall_vals = df["Recall"].fillna(0)
    b1 = ax1.bar(x - w/2, recall_vals, w, label="Recall（%）", color="#2266cc", alpha=0.85)
    b2 = ax1.bar(x + w/2, df["FAR"], w, label="FAR（%）", color="#cc3333", alpha=0.85)

    for bar, r, v in zip(b1, df["Recall"], df["Recall"]):
        label = "N/A" if pd.isna(v) else f"{v:.1f}%"
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, label,
                 ha="center", fontsize=8.5, color="#2266cc")
    for bar, v in zip(b2, df["FAR"]):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f"{v:.1f}%",
                 ha="center", fontsize=8.5, color="#cc3333")

    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{n}\n(N={v})" for n, v in zip(df["星系"], df["N"])], fontsize=9)
    ax1.set_ylabel("百分比（%）", fontsize=11)
    ax1.set_ylim(0, 100)
    ax1.legend(fontsize=10)
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.set_title("圖八：跨星系分層 Recall / FAR\n"
                   "（ISS_Complex 無推進標注正例，FAR 高反映「未標注」而非真誤報）",
                   fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig8_constellation.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖九：跨時間段穩定性測試
# ─────────────────────────────────────────────────────────────────────────────
def fig9_temporal_stability():
    fig, ax = plt.subplots(figsize=(8, 5.5))

    labels = ["一致\n（Both_miss + Both_detect）", "A_only\n（僅前期偵測）", "B_only\n（僅後期偵測）"]
    values = [269, 17, 14]
    colors = ["#22aa44", "#ee8822", "#cc3333"]

    bars = ax.bar(labels, values, color=colors, alpha=0.85, width=0.55)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 3, f"{v}\n({v/300*100:.1f}%)",
                 ha="center", fontsize=10, fontweight="bold")

    ax.set_ylabel("衛星數（共 300 顆抽樣）", fontsize=11)
    ax.set_ylim(0, 300)
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_title(
        "圖九：跨時間段偵測穩定性測試\n"
        "Period A（05-01～06-01）vs Period B（06-01～06-23）｜整體一致率 89.7%\n"
        "F10.7：A=127.9 sfu、B=127.3 sfu（兩期均為太陽平靜期，非活躍期對照）",
        fontsize=11, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig9_temporal_stability.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖十：獨立 Hold-out 事件驗證（MEME V 形事件）
# ─────────────────────────────────────────────────────────────────────────────
def fig10_holdout():
    df = pd.read_csv(os.path.join(LEO_OUT, "holdout_detection.csv"))
    ok = df[df["status"] == "ok"].copy()
    detected = ok[ok["detected"] == True]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # (a) lead time 直方圖
    ax1.hist(detected["lead_h"].dropna(), bins=20, color="#2266cc", alpha=0.8, edgecolor="white")
    ax1.axvline(0, color="black", lw=1, ls="--")
    ax1.axvline(detected["lead_h"].mean(), color="#cc3333", lw=1.5,
                label=f"平均 {detected['lead_h'].mean():.1f}h")
    ax1.set_xlabel("偵測前置時間 Lead Time（小時，正值＝提前偵測）", fontsize=10)
    ax1.set_ylabel("事件數", fontsize=10)
    ax1.set_title(f"(a) 命中事件之偵測前置時間分布（n={len(detected)}）", fontsize=10.5, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # (b) 依 peak_pos_err 分層 recall
    bins = [(100, 500), (500, 2000), (2000, 99999)]
    bin_labels = ["100–500 km", "500–2000 km", "2000+ km"]
    recalls, ns = [], []
    for lo, hi in bins:
        sub = ok[(ok["peak_pos_err_km"] >= lo) & (ok["peak_pos_err_km"] < hi)]
        ns.append(len(sub))
        recalls.append(100 * sub["detected"].mean() if len(sub) else 0)

    bars = ax2.bar(bin_labels, recalls, color=["#ffaa00", "#22aa44", "#2266cc"], alpha=0.85)
    for b, r, n in zip(bars, recalls, ns):
        ax2.text(b.get_x() + b.get_width()/2, b.get_height() + 1.5, f"{r:.1f}%\n(N={n})",
                 ha="center", fontsize=9)
    ax2.set_ylabel("事件級 Recall（%）", fontsize=10)
    ax2.set_ylim(0, 100)
    ax2.set_title("(b) 依 MEME peak_pos_err 分層 Recall", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="y", alpha=0.3)

    fig.suptitle("圖十：獨立 Hold-out 事件驗證（MEME V 形事件，2026-06-01～06-23，99 個有效事件）",
                 fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig10_holdout.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


if __name__ == "__main__":
    print("產生論文一擴充驗證圖片中...")
    fig7_recall_at_n()
    fig8_constellation()
    fig9_temporal_stability()
    fig10_holdout()
    print("全部完成。")
