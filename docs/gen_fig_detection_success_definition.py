#!/usr/bin/env python3
"""gen_fig_detection_success_definition.py — 產生「本專案 vs TASA 檢測成功定義」對比圖，
版面比照 TASA《TASA方法於NASA機動資料庫偵測結果_20260911.pdf》p.5 風格
（左：混淆矩陣＋定義文字；右/下：真實衛星時序圖，標出命中/虛檢/漏檢範例）。
用法：python docs/gen_fig_detection_success_definition.py
輸出：docs/fig_detection_success_definition.png
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tasa14_compare import load_events, load_a, detect_iter, _shift_signal, TOL_D

for f in ["Microsoft JhengHei", "Noto Sans CJK TC", "SimHei"]:
    try:
        plt.rcParams["font.sans-serif"] = [f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

NID = 41240
NAME = "Jason-3"


def main():
    events = load_events()
    t, a = load_a(NID)
    tsec = t.astype("int64").to_numpy() / 1e9
    ev_all = events[NID]
    lo = max(t.min(), ev_all["ws"].min()); hi = min(t.max(), ev_all["we"].max())
    ev = ev_all[(ev_all["ws"] >= lo) & (ev_all["ws"] <= hi)].reset_index(drop=True)

    dets = detect_iter(t, a, 6)
    dets = pd.to_datetime([d for d in dets if lo <= d <= hi])

    tol = pd.Timedelta(days=float(TOL_D))
    used = np.zeros(len(dets), bool)
    tp_examples, fn_examples = [], []
    for _, e in ev.iterrows():
        w0, w1 = e["ws"] - tol, e["we"] + tol
        hit = [i for i, d in enumerate(dets) if w0 <= d <= w1 and not used[i]]
        if hit:
            used[hit[0]] = True
            tp_examples.append((e["ws"], e["we"], dets[hit[0]]))
        else:
            fn_examples.append((e["ws"], e["we"]))
    fp_examples = [dets[i] for i in range(len(dets)) if not used[i]]

    n_tp, n_fn, n_fp = len(tp_examples), len(fn_examples), len(fp_examples)
    n_ev = len(ev)
    prec = n_tp / (n_tp + n_fp) if (n_tp + n_fp) else 0.0
    rec = n_tp / (n_tp + n_fn) if (n_tp + n_fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    mask = np.zeros(len(a), bool)
    sig = _shift_signal(a, tsec, mask)
    sd = 1.4826 * np.nanmedian(np.abs(sig - np.nanmedian(sig)))

    # ── 選一段密集但仍可辨識的示範窗（涵蓋 TP/FN/FP 各至少一例）──
    win_lo = pd.Timestamp("2016-01-14", tz="UTC")
    win_hi = pd.Timestamp("2016-02-20", tz="UTC")

    def in_win(ts):
        return win_lo <= ts <= win_hi

    tp_win = [x for x in tp_examples if in_win(x[2])]
    fn_win = [x for x in fn_examples if in_win(x[0])]
    fp_win = [x for x in fp_examples if in_win(x)]

    fig = plt.figure(figsize=(13, 10))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 0.15, 1.6], width_ratios=[1.35, 1])

    # ── 上左：定義文字 ──
    ax_txt = fig.add_subplot(gs[0, 0]); ax_txt.axis("off")
    ax_txt.text(0, 1.0,
        "本專案「檢測成功」定義", fontsize=17, fontweight="bold", va="top")
    ax_txt.text(0, 0.80,
        "真實機動窗（Beginning→End of maneuver）\n"
        "外擴 ±1.5 天做為容差視窗；\n"
        "只要偵測時刻落在「真實窗 ± 1.5 天」內，\n"
        "就算命中（TP）；否則落單的偵測算虛檢（FP），\n"
        "沒被任何偵測命中的真實窗算漏檢（FN）。",
        fontsize=12.5, va="top", linespacing=1.7)
    ax_txt.text(0, 0.28,
        "與 TASA 定義之差異：TASA 只要求偵測「涵蓋到」\n"
        "真實機動時間範圍本身（原始窗常僅數分鐘至數小時）；\n"
        "本專案額外外擴 ±1.5 天，原因是 TLE 解析度通常僅\n"
        "每天 0.5–2 筆，若要求偵測落在原始窗內，以 TLE 的\n"
        "取樣頻率幾乎不可能達成。",
        fontsize=11, va="top", color="#333333", linespacing=1.6,
        style="italic")

    # ── 上右：混淆矩陣（比照 TASA p.5 版面）──
    ax_cm = fig.add_subplot(gs[0, 1]); ax_cm.axis("off")
    cell_w, cell_h = 0.22, 0.16
    x0, y0 = 0.30, 0.62
    labels = [
        ("", "", ""), ("", "P", "N"),
        ("P", "TP\n(命中)", "FP\n(虛檢)"),
        ("N", "FN\n(漏檢)", "TN"),
    ]
    ax_cm.text(x0 + cell_w * 1.5, y0 + cell_h * 1.8, "真實事件", ha="center", fontsize=12, fontweight="bold")
    ax_cm.text(x0 - cell_w * 1.3, y0 - cell_h * 0.3, "檢\n測\n事\n件", ha="center", va="center", fontsize=11, fontweight="bold")
    headers_x = ["P", "N"]
    for j, hx in enumerate(headers_x):
        ax_cm.add_patch(Rectangle((x0 + cell_w * (j + 1), y0 + cell_h), cell_w, cell_h,
                                   facecolor="#1f4e8c", edgecolor="white"))
        ax_cm.text(x0 + cell_w * (j + 1.5), y0 + cell_h * 1.5, hx, ha="center", va="center",
                   color="white", fontsize=12, fontweight="bold")
    rows = [("P", ["TP\n(命中)", "FP\n(虛檢)"], ["#5fa8d3", "#cfe8f3"]),
            ("N", ["FN\n(漏檢)", "TN"], ["#f7d9c4", "#e8eef1"])]
    for i, (rh, cells, colors) in enumerate(rows):
        ax_cm.add_patch(Rectangle((x0, y0 - cell_h * i), cell_w, cell_h,
                                   facecolor="#1f4e8c", edgecolor="white"))
        ax_cm.text(x0 + cell_w * 0.5, y0 - cell_h * i + cell_h * 0.5, rh, ha="center", va="center",
                   color="white", fontsize=12, fontweight="bold")
        for j, (c, col) in enumerate(zip(cells, colors)):
            ax_cm.add_patch(Rectangle((x0 + cell_w * (j + 1), y0 - cell_h * i), cell_w, cell_h,
                                       facecolor=col, edgecolor="white"))
            ax_cm.text(x0 + cell_w * (j + 1.5), y0 - cell_h * i + cell_h * 0.5, c,
                       ha="center", va="center", fontsize=10.5)
    ax_cm.set_xlim(0, 1.3); ax_cm.set_ylim(0, 1.0)
    ax_cm.text(0.02, 0.06,
        f"以 Jason-3（NORAD 41240）示範，2016-01 ~ 2026-09：\n"
        f"真實機動 {n_ev} 次｜命中 {n_tp}｜漏檢 {n_fn}｜虛檢 {n_fp}\n"
        f"Precision={prec:.2f}　Recall={rec:.2f}　F1={f1:.2f}",
        fontsize=10.5, va="bottom")

    # ── 下：時序圖（示範窗 2016-01-14 ~ 2016-02-20）──
    ax = fig.add_subplot(gs[2, :])
    mwin = (t >= win_lo) & (t <= win_hi)
    ax.plot(t[mwin], sig[mwin], color="#1f6fb2", lw=1.1, label="位準位移訊號 (km)")
    ax.axhline(6 * sd, color="gray", ls="--", lw=1, label=f"門檻 ±6σ (σ={sd:.2e})")
    ax.axhline(-6 * sd, color="gray", ls="--", lw=1)

    for j, (ws, we) in enumerate(ev[["ws", "we"]].itertuples(index=False)):
        if not (win_lo <= we and ws <= win_hi):
            continue
        ax.axvspan(ws - tol, we + tol, color="#ffd9a0", alpha=0.35, lw=0)
        ax.axvspan(ws, we, color="#e2841e", alpha=0.9, lw=0)

    for d in dets:
        if win_lo <= d <= win_hi:
            ax.axvline(d, color="#1f4e8c", lw=1.4, alpha=0.85)

    ymax = np.nanmax(np.abs(sig[mwin])) * 1.15 if mwin.any() else 1
    if tp_win:
        ws, we, d = tp_win[0]
        ax.annotate("命中\n(TP)", xy=(d, 6 * sd), xytext=(d, ymax * 0.75),
                    ha="center", fontsize=10, color="#1a7a3c", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#1a7a3c"))
    if fn_win:
        ws, we = fn_win[1] if len(fn_win) > 1 else fn_win[0]
        ax.annotate("漏檢\n(FN)", xy=(ws + (we - ws) / 2, 0), xytext=(ws, -ymax * 0.85),
                    ha="center", fontsize=10, color="#b32424", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#b32424"))
    if fp_win:
        d = fp_win[0]
        ax.annotate("虛檢\n(FP)", xy=(d, -6 * sd), xytext=(d, -ymax * 0.55),
                    ha="center", fontsize=10, color="#7a4fb3", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#7a4fb3"))

    ax.set_ylim(-ymax, ymax)
    ax.set_title(f"{NAME}（NORAD {NID}）位準位移訊號 · 示範窗 2016-01-14 ~ 2016-02-20\n"
                 "橘色實心＝真實機動窗；橘色淺色＝±1.5天容差；藍色直線＝本專案偵測時刻",
                 fontsize=11.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()
    ax.set_ylabel("位準位移 (km)")
    ax.legend(loc="upper right", fontsize=9)

    fig.suptitle("本專案 vs TASA：「檢測成功」定義比較說明圖", fontsize=15, fontweight="bold", y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = Path(__file__).resolve().parent / "fig_detection_success_definition.png"
    fig.savefig(out, dpi=160)
    print(f"輸出 → {out}")
    print(f"示範窗內：TP={len(tp_win)} FN={len(fn_win)} FP={len(fp_win)}")


if __name__ == "__main__":
    main()
