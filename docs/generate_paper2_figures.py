"""generate_paper2_figures.py
產生論文二（LightGBM 分類器）所需的全部 6 張圖，儲存於 docs/ 資料夾。
執行：python docs/generate_paper2_figures.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.gridspec import GridSpec

plt.rcParams.update({
    "font.family":        "Microsoft YaHei",
    "axes.unicode_minus": False,
    "figure.dpi":         150,
    "savefig.dpi":        200,
    "savefig.bbox":       "tight",
})

OUT = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# 圖一：機器學習訓練流程圖
# ─────────────────────────────────────────────────────────────────────────────
def fig1_ml_pipeline():
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5)
    ax.axis("off")

    stages = [
        ("TLE\n資料收集", "14,019 顆衛星\n30 天 TLE", "#cce4ff", "#3366aa"),
        ("特徵\n工程",     "22 個聚合特徵\n成績單", "#dce8d0", "#4a7c3f"),
        ("資料\n切分",     "70/15/15%\n衛星層級分層", "#fff0cc", "#a07800"),
        ("模型\n訓練",     "LightGBM\n最多 1,000 棵樹", "#f5d0d0", "#883333"),
        ("驗證\n調參",     "早停 patience=50\n→第 561 棵停止", "#ead8f5", "#663399"),
        ("測試\n評估",     "Precision 81.6%\nAUC-ROC 0.990", "#d0f0e0", "#2a7a4a"),
        ("SHAP\n解釋",     "flag_rate 42.6%\n冗餘特徵 3 個", "#ffe8d0", "#aa4400"),
    ]

    xs = np.linspace(1.0, 13.0, len(stages))
    w, h = 1.5, 2.2

    for i, (title, subtitle, fc, ec) in enumerate(stages):
        cx = xs[i]
        rect = FancyBboxPatch((cx - w/2, 1.4), w, h,
                              boxstyle="round,pad=0.12",
                              fc=fc, ec=ec, lw=2.0, zorder=3)
        ax.add_patch(rect)
        ax.text(cx, 2.5 + h/2 - 0.25, title,
                ha="center", va="center", fontsize=10.5,
                fontweight="bold", color=ec, zorder=4)
        ax.text(cx, 1.8, subtitle,
                ha="center", va="center", fontsize=8.5,
                color="#444444", zorder=4)

        # 箭頭
        if i < len(stages) - 1:
            x_next = xs[i+1] - w/2 - 0.05
            ax.annotate("",
                        xy=(x_next, 2.5),
                        xytext=(cx + w/2 + 0.05, 2.5),
                        arrowprops=dict(arrowstyle="-|>",
                                       color="#888888", lw=1.5),
                        zorder=5)

    ax.text(7.0, 0.8,
            "每一步均可重現：完整代碼與訓練資料已公開於 GitHub",
            ha="center", va="center", fontsize=9.5, color="#555555",
            style="italic")

    ax.set_title("圖一：LightGBM 衛星機動偵測的完整訓練流程",
                 fontsize=13, fontweight="bold", pad=6)

    out = os.path.join(OUT, "paper2_fig1_ml_pipeline.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖二：不平衡資料分布圖
# ─────────────────────────────────────────────────────────────────────────────
def fig2_class_imbalance():
    fig, axes = plt.subplots(1, 3, figsize=(13, 5))

    # ─ 左：圓餅圖（現況：20 特徵版本，2026-06-23 重新標記）──────
    sizes  = [11123, 2900]
    labels = ["無機動（0）\n11,123 顆（79.3%）",
              "有機動（1）\n2,900 顆（20.7%）"]
    colors = ["#aaccff", "#ff7777"]
    wedges, texts = axes[0].pie(
        sizes, labels=labels, colors=colors,
        startangle=90, wedgeprops=dict(edgecolor="white", linewidth=2))
    for t in texts:
        t.set_fontsize(9.5)
    axes[0].set_title("(a) 訓練資料類別分布\n（14,023 顆衛星，P1–P6 標籤）",
                      fontsize=11, fontweight="bold")

    # ─ 中：訓練/驗證/測試各組正負例（random_split seed=42 實測）──
    splits = ["訓練組\n9,816 顆", "驗證組\n2,103 顆", "測試組\n2,104 顆"]
    neg_n  = [7786, 1668, 1669]
    pos_n  = [2030,  435,  435]

    x = np.arange(3)
    axes[1].bar(x, neg_n, label="無機動（0）", color="#aaccff", alpha=0.85)
    axes[1].bar(x, pos_n, bottom=neg_n, label="有機動（1）",
                color="#ff7777", alpha=0.85)
    for i, (n, p) in enumerate(zip(neg_n, pos_n)):
        axes[1].text(i, n + p + 30,
                     f"{p/(n+p)*100:.1f}%", ha="center", fontsize=9, color="#cc2222")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(splits, fontsize=9.5)
    axes[1].set_ylabel("衛星顆數", fontsize=10)
    axes[1].legend(fontsize=9, loc="upper right")
    axes[1].set_title("(b) 分層切分後各組正負例比例\n（三組均維持 ~20.7%，分層生效）",
                      fontsize=11, fontweight="bold")
    axes[1].grid(True, axis="y", alpha=0.3)

    # ─ 右：蠢分類器 vs LightGBM 對比（現況數字）──────────────
    metrics = ["Precision", "Recall", "F1", "Accuracy"]
    dumb_acc = 11123 / 14023
    dumb    = [0,     0,     0,    dumb_acc]   # always predicts 0
    lgbm    = [0.995, 0.975, 0.985, None]

    x2 = np.arange(len(metrics))
    w2 = 0.3
    axes[2].bar(x2[:3] - w2/2, dumb[:3],  w2,
                label=f"全猜「無機動」（準確率 {dumb_acc:.0%}）",
                color="#dddddd", alpha=0.8)
    axes[2].bar(x2[3]  - w2/2, dumb[3],   w2, color="#dddddd", alpha=0.8)
    axes[2].bar(x2[:3] + w2/2, lgbm[:3],  w2, label="LightGBM（本研究，現況）",
                color="#4488cc", alpha=0.85)
    axes[2].axhline(1.0, color="#999999", ls="--", lw=1, alpha=0.5)

    axes[2].set_xticks(x2)
    axes[2].set_xticklabels(metrics, fontsize=9.5)
    axes[2].set_ylim(0, 1.15)
    axes[2].set_ylabel("指標值", fontsize=10)
    axes[2].legend(fontsize=8.5, loc="upper right")
    axes[2].set_title("(c) 為什麼高準確率不代表好模型",
                      fontsize=11, fontweight="bold")
    axes[2].grid(True, axis="y", alpha=0.3)
    axes[2].text(3, dumb[3]+0.03, f"{dumb[3]:.1%}", ha="center",
                 fontsize=8.5, color="#555555")
    for i, v in enumerate(lgbm[:3]):
        axes[2].text(i+w2/2, v+0.03, f"{v:.1%}", ha="center",
                     fontsize=8.5, color="#2255aa")

    fig.suptitle("圖二：不平衡資料挑戰與衛星層級分層切分",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(OUT, "paper2_fig2_class_imbalance.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖三：SHAP 特徵重要性水平條形圖
# ─────────────────────────────────────────────────────────────────────────────
def fig3_shap_importance():
    # 30 天模型的 SHAP mean|SHAP| 百分比（top-10 為已驗證數值，其餘為估算）
    features = [
        "flag_rate",        "max_di_deg",      "mean_tle_gap_h",
        "max_draan_res_deg","alt_km",           "da_std",
        "net_da_km",        "neg_streak",       "total_drop_km",
        "max_da_km",        "n_flagged",        "da_abs_mean",
        "n_transitions",    "dv_net_ms",        "n_windows_flagged",
        "monotone_decay",   "ecc",              "inc_deg",
        "max_tle_gap_h",    "inc_family_enc",   "n_tle",
        "burn_freq_per_day",
    ]
    shap_pct = [
        42.6,  6.8,  6.4,
         6.2,  5.8,  5.1,
         4.3,  3.9,  3.2,
         2.8,  2.5,  1.5,
         1.5,  1.3,  1.2,
         1.0,  1.0,  0.9,
         0.7,  0.0,  0.0,
         0.0,
    ]

    # 特徵群組顏色
    group_colors = {
        "機動頻率":   ["flag_rate","n_flagged","burn_freq_per_day","n_windows_flagged"],
        "軌道動力學": ["max_di_deg","max_draan_res_deg","da_std","net_da_km","max_da_km","da_abs_mean","dv_net_ms","n_transitions","neg_streak","total_drop_km"],
        "軌道幾何":   ["alt_km","ecc","inc_deg","inc_family_enc"],
        "TLE 資料密度":["mean_tle_gap_h","max_tle_gap_h","n_tle"],
        "阻力特徵":   ["monotone_decay"],
    }
    palette = {
        "機動頻率":    "#cc3333",
        "軌道動力學":  "#2266cc",
        "軌道幾何":    "#228833",
        "TLE 資料密度":"#aa6600",
        "阻力特徵":    "#8833aa",
    }
    feat2grp = {}
    for grp, fts in group_colors.items():
        for f in fts:
            feat2grp[f] = grp

    colors = [palette[feat2grp.get(f, "TLE 資料密度")] for f in features]

    # 由高到低排序
    order = np.argsort(shap_pct)[::-1]
    features_s = [features[i] for i in order]
    shap_s     = [shap_pct[i] for i in order]
    colors_s   = [colors[i]   for i in order]

    fig, ax = plt.subplots(figsize=(10, 9))
    y = np.arange(len(features_s))
    bars = ax.barh(y, shap_s, color=colors_s, alpha=0.85, height=0.65)

    # 數值標籤
    for i, (bar, v) in enumerate(zip(bars, shap_s)):
        if v > 0:
            ax.text(v + 0.3, bar.get_y() + bar.get_height()/2,
                    f"{v:.1f}%", va="center", fontsize=8.5,
                    color=colors_s[i])
        else:
            ax.text(0.3, bar.get_y() + bar.get_height()/2,
                    "0.0%（零貢獻）", va="center", fontsize=8,
                    color="#aaaaaa", style="italic")

    ax.set_yticks(y)
    ax.set_yticklabels(features_s, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("SHAP 貢獻佔比（mean |SHAP| / 全特徵總和，%）", fontsize=10)
    ax.set_xlim(0, 50)
    ax.axvline(x=0, color="black", lw=0.5)
    ax.grid(True, axis="x", alpha=0.3)

    # 圖例
    legend_patches = [mpatches.Patch(color=palette[g], label=g, alpha=0.85)
                      for g in palette]
    ax.legend(handles=legend_patches, fontsize=9, loc="lower right",
              title="特徵類別", title_fontsize=9)

    # 標注前三
    for i in range(3):
        ax.text(shap_s[i]/2, i,
                f"#{i+1}", ha="center", va="center",
                fontsize=9, color="white", fontweight="bold")

    ax.set_title(
        "圖三：SHAP 特徵重要性排行榜（30 天模型，22 個特徵）\n"
        "flag_rate 以 42.6% 主導，三個特徵零貢獻可移除",
        fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "paper2_fig3_shap_importance.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖四：混淆矩陣熱力圖
# ─────────────────────────────────────────────────────────────────────────────
def fig4_confusion_matrix():
    # 現況 20 特徵模型，thr=0.5747，獨立測試集（2,104 顆，seed=42）
    cm = np.array([[1667, 2],
                   [  11, 424]])

    labels_row = ["實際：無機動（0）", "實際：有機動（1）"]
    labels_col = ["預測：無機動（0）", "預測：有機動（1）"]

    cell_labels = [["TN\n1,667", "FP\n2（誤報）"],
                   ["FN\n11（漏報）", "TP\n424"]]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # ─ 左：熱力圖 ──────────────────────────────────────────────
    # 對數正規化顯示（避免 TN 完全主導色彩）
    from matplotlib.colors import LogNorm
    im = axes[0].imshow(cm, cmap="Blues",
                        norm=LogNorm(vmin=1, vmax=cm.max()))
    axes[0].set_xticks([0, 1])
    axes[0].set_yticks([0, 1])
    axes[0].set_xticklabels(labels_col, fontsize=10)
    axes[0].set_yticklabels(labels_row, fontsize=10)
    axes[0].set_xlabel("預測結果", fontsize=11)
    axes[0].set_ylabel("實際標籤", fontsize=11)

    cell_colors = [["white", "#ff9999"], ["#ffcc88", "#66bb66"]]
    for i in range(2):
        for j in range(2):
            axes[0].add_patch(plt.Rectangle(
                (j-0.5, i-0.5), 1, 1,
                fill=True, fc=cell_colors[i][j], alpha=0.4, zorder=0))
            axes[0].text(j, i, cell_labels[i][j],
                         ha="center", va="center",
                         fontsize=12, fontweight="bold",
                         color="#222222")

    plt.colorbar(im, ax=axes[0], label="衛星顆數（對數刻度）")
    axes[0].set_title(f"(a) 混淆矩陣\n閾值 τ = 0.5747（F0.5 最優，現況模型）",
                      fontsize=11, fontweight="bold")

    # ─ 右：各指標計算結果 ──────────────────────────────────────
    tp, fp, fn, tn = 424, 2, 11, 1667
    prec   = tp / (tp+fp)
    recall = tp / (tp+fn)
    f1     = 2*prec*recall/(prec+recall)
    acc    = (tp+tn)/(tp+fp+fn+tn)
    auc    = 0.9962

    metrics = ["Precision\n（精確率）", "Recall\n（召回率）",
               "F1 Score", "Accuracy\n（整體準確率）", "AUC-ROC"]
    vals    = [prec, recall, f1, acc, auc]
    formulas = [
        f"TP/(TP+FP) = {tp}/({tp}+{fp})",
        f"TP/(TP+FN) = {tp}/({tp}+{fn})",
        f"2×P×R/(P+R)",
        f"(TP+TN)/N = {tp+tn}/{tp+fp+fn+tn}",
        "ROC 曲線下面積",
    ]
    colors5 = ["#2266cc","#228833","#aa4400","#888888","#aa00aa"]

    x3 = np.arange(len(metrics))
    bars = axes[1].bar(x3, vals, color=colors5, alpha=0.80, width=0.55)
    axes[1].axhline(1.0, color="#999999", ls="--", lw=1, alpha=0.5)
    for bar, v, fml in zip(bars, vals, formulas):
        axes[1].text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + 0.01,
                     f"{v:.3f}", ha="center", va="bottom",
                     fontsize=10.5, fontweight="bold")
        axes[1].text(bar.get_x() + bar.get_width()/2,
                     bar.get_height()/2,
                     fml, ha="center", va="center",
                     fontsize=7, color="white", rotation=0)

    axes[1].set_xticks(x3)
    axes[1].set_xticklabels(metrics, fontsize=9.5)
    axes[1].set_ylim(0, 1.15)
    axes[1].set_ylabel("指標值", fontsize=11)
    axes[1].set_title(
        "(b) 各指標計算值（獨立測試集，2,104 顆）",
        fontsize=11, fontweight="bold")
    axes[1].grid(True, axis="y", alpha=0.3)

    fig.suptitle(
        "圖四：LightGBM 混淆矩陣與評估指標（現況 20 特徵模型）",
        fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(OUT, "paper2_fig4_confusion_matrix.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖五：多模型 ROC 曲線比較
# ─────────────────────────────────────────────────────────────────────────────
def fig5_roc_comparison():
    """左圖直接載入 compare_models.py 實際執行產生的真實 ROC 曲線（非合成示意）；
    右圖為對應的 Precision/Recall/F1 長條圖，數字取自同一次執行的
    Orbital_Maneuver_V2/output/model_comparison.csv（現況 20 特徵模型）。"""
    real_roc_path = os.path.join(OUT, "..", "Orbital_Maneuver_V2", "output", "roc_comparison.png")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # ─ 左：直接嵌入真實 ROC 曲線圖（compare_models.py 產生）────────
    if os.path.exists(real_roc_path):
        img = plt.imread(real_roc_path)
        axes[0].imshow(img)
        axes[0].axis("off")
        axes[0].set_title("(a) 真實 ROC 曲線（compare_models.py 實測，非示意）",
                          fontsize=10.5, fontweight="bold")
    else:
        axes[0].text(0.5, 0.5, "roc_comparison.png 不存在\n請先執行 compare_models.py",
                     ha="center", va="center")
        axes[0].axis("off")

    # ─ 右：Precision-Recall-F1 對照（現況真實數字）──────────────
    metrics_all = {
        "規則基準\n(flag_rate>0.05)": (0.524, 0.099, 0.166),
        "隨機森林":                    (0.986, 0.979, 0.983),
        "XGBoost":                     (0.979, 0.972, 0.976),
        "LightGBM\n（本研究）":        (0.995, 0.975, 0.985),
    }
    names = list(metrics_all.keys())
    precs   = [v[0] for v in metrics_all.values()]
    recalls = [v[1] for v in metrics_all.values()]
    f1s     = [v[2] for v in metrics_all.values()]

    x4 = np.arange(len(names))
    w4 = 0.25
    colors4 = ["#888888","#228833","#aa6600","#cc2222"]
    axes[1].bar(x4 - w4, precs,   w4, label="精確率", alpha=0.82, color=colors4)
    axes[1].bar(x4,      recalls, w4, label="召回率", alpha=0.55, color=colors4)
    axes[1].bar(x4 + w4, f1s,    w4, label="F1",     alpha=0.40, color=colors4)
    axes[1].set_xticks(x4)
    axes[1].set_xticklabels(names, fontsize=8.5)
    axes[1].set_ylim(0, 1.2)
    axes[1].set_ylabel("指標值", fontsize=11)
    axes[1].legend(fontsize=9, loc="upper left")
    axes[1].set_title("(b) 精確率/召回率/F1 對比\n（三種樹模型現況表現相近，規則基準明顯落後）",
                      fontsize=10.5, fontweight="bold")
    axes[1].grid(True, axis="y", alpha=0.3)
    for x, v in zip(x4, precs):
        axes[1].text(x - w4, v + 0.02, f"{v:.1%}", ha="center", fontsize=7.5,
                     color="#222222", fontweight="bold")

    fig.suptitle("圖五：四種分類方法的 ROC 曲線與 Precision/Recall 對比（現況 20 特徵模型）",
                 fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(OUT, "paper2_fig5_roc_comparison.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖六：LightGBM 早停訓練曲線
# ─────────────────────────────────────────────────────────────────────────────
def fig6_training_curve():
    """早停訓練過程示意曲線（形狀為示意，早停棵數 188 為現況模型實測值，
    來自 joblib.load 後 booster_.best_iteration_）。"""
    rng = np.random.default_rng(42)
    n_trees = 400
    t = np.arange(1, n_trees + 1)

    # 示意訓練/驗證損失（指數衰減 + 輕微過擬合），曲線形狀非實際逐棵記錄
    train_loss = 0.55 * np.exp(-t / 60) + 0.05 + rng.normal(0, 0.003, n_trees)
    val_loss   = 0.58 * np.exp(-t / 65) + 0.08 + rng.normal(0, 0.005, n_trees)
    # 驗證損失在 ~188 棵後微幅上升（過擬合）
    val_loss[187:] += np.linspace(0, 0.02, n_trees - 187)

    best_iter = 188
    best_val  = val_loss[best_iter - 1]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # ─ 左：訓練/驗證損失曲線 ──────────────────────────────────
    axes[0].plot(t, train_loss, color="#2266cc", lw=1.5, alpha=0.8,
                 label="訓練損失（binary logloss）")
    axes[0].plot(t, val_loss,   color="#cc2222", lw=1.5,
                 label="驗證損失")
    axes[0].axvline(x=best_iter, color="#aa5500", lw=2.0, ls="--",
                    label=f"最佳迭代（第 {best_iter} 棵，實測值）")
    axes[0].axvspan(best_iter, n_trees, alpha=0.07, color="#ff8800")
    axes[0].annotate(
        f"早停：第 {best_iter} 棵後\n連續 50 棵無改善",
        xy=(best_iter, best_val),
        xytext=(best_iter + 60, best_val + 0.02),
        fontsize=9, color="#aa5500",
        arrowprops=dict(arrowstyle="->", color="#aa5500"))
    axes[0].set_xlabel("樹的棵數（Boosting 輪次）", fontsize=11)
    axes[0].set_ylabel("Binary Log-Loss（示意曲線形狀）", fontsize=11)
    axes[0].set_xlim(0, n_trees)
    axes[0].set_title("(a) 早停機制（Early Stopping）示意\n早停棵數 188 為現況模型實測值，曲線形狀為示意",
                      fontsize=10.5, fontweight="bold")
    axes[0].legend(fontsize=9)
    axes[0].grid(True, alpha=0.3)

    # ─ 右：超參數設定（現況不變，維持 0.05）────────────────────
    lr_vals   = [0.2,  0.1,  0.05, 0.02, 0.01]
    prec_vals = [0.97, 0.98, 0.995, 0.98, 0.96]  # 示意；現況精確峰值在 0.05

    axes[1].plot(lr_vals, prec_vals, "o-", color="#228833", lw=2.0, ms=8)
    axes[1].axvline(x=0.05, color="#cc2222", lw=1.8, ls="--", alpha=0.8)
    axes[1].text(0.055, prec_vals[2] - 0.01, "現況設定\nlearning_rate=0.05",
                 fontsize=9, color="#cc2222")
    axes[1].set_xlabel("學習率（learning_rate）", fontsize=11)
    axes[1].set_ylabel("測試集 Precision（示意）", fontsize=11)
    axes[1].set_xscale("log")
    axes[1].set_ylim(0.90, 1.02)
    axes[1].set_title("(b) 學習率超參數設定示意\n（其他參數固定，敏感性未在現況模型重新掃描）",
                      fontsize=10.5, fontweight="bold")
    axes[1].grid(True, alpha=0.3)

    fig.suptitle("圖六：LightGBM 早停訓練動態（現況：188 棵樹）與超參數設定",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(OUT, "paper2_fig6_training_curve.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("產生論文二圖片中...")
    fig1_ml_pipeline()
    fig2_class_imbalance()
    # 圖三（SHAP）改用真實運算結果，不再呼叫 fig3_shap_importance() 合成版本：
    # 見 Orbital_Maneuver_V2/analyze_plan_b_model.py 產生的
    # output/shap_summary_bar.png、output/shap_beeswarm.png（本腳本執行前需
    # 先在相容環境下跑過一次該腳本），再手動複製為
    # paper2_fig3_shap_importance.png / paper2_fig3b_shap_beeswarm.png。
    fig4_confusion_matrix()
    fig5_roc_comparison()
    fig6_training_curve()
    print("全部完成（圖三 SHAP 需另外由 analyze_plan_b_model.py 產生，見上方註解）。")
