#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs7_fig_style.py — 論文二（docs/paper_fs7_sensitivity_model_EN.md）新增圖之共用版面設定。

期刊（Advances in Space Research）規格：白底、Arial（缺字 fallback DejaVu Sans）、
單欄寬 8.5 cm／雙欄寬 17.5 cm，字級 6.5–7.5 pt，線寬 0.6–1.0 pt；
預設輸出 docs/<stem>.png（600 dpi）＋ docs/<stem>.pdf（向量，TrueType 內嵌）。
加 --pub 時改以 fig_pub.export_variants 輸出 docs/figures_pub/<stem>/ 之中英 × 白底／黑底四版本。

用法（產生程式端）：
    import fs7_fig_style as st
    st.run({"fig_fs7_xxx": draw_xxx})     # draw_xxx() 回傳 Figure；文字以 fp.t("中文", "English") 提供
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fig_pub as fp  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
BM = ROOT / "data" / "benchmark"

CM = 1 / 2.54
SINGLE = 8.5 * CM      # 單欄寬（in）
DOUBLE = 17.5 * CM     # 雙欄寬（in）

# 資料色（白底；黑底版由 fig_pub 亮度反轉）
BLUE, ORANGE, RED, GREEN, PURPLE, GRAY = "#1f5fa8", "#d9822b", "#b8322a", "#2e7d4a", "#6b4c9a", "#6b7280"
INK = "#111111"

JOURNAL_RC = {
    "font.size": 7.0,
    "axes.titlesize": 7.5,
    "axes.labelsize": 7.0,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.3,
    "legend.title_fontsize": 6.5,
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.0,
    "lines.markersize": 3.5,
    "patch.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.minor.width": 0.45,
    "ytick.minor.width": 0.45,
    "xtick.major.size": 2.8,
    "ytick.major.size": 2.8,
    "xtick.minor.size": 1.6,
    "ytick.minor.size": 1.6,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titlepad": 4.0,
    "axes.labelpad": 2.5,
    "legend.frameon": False,
    "legend.handlelength": 1.8,
    "legend.borderaxespad": 0.3,
    "grid.linewidth": 0.4,
    "grid.alpha": 0.35,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
}


def panel_label(ax, s, x=-0.02, y=1.0, **kw):
    """面板代號 (a)/(b)…：放在軸框左上外側。"""
    ax.text(x, y, s, transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5,
            fontweight="bold", color=INK, **kw)


def save_default(draw: Callable[[], "plt.Figure"], stem: str) -> None:
    """預設輸出：英文、白底，docs/<stem>.png（600 dpi）與 .pdf。"""
    prev = fp.lang()
    fp.set_lang("en")
    try:
        rc = fp.rc_for("en")
        rc.update(JOURNAL_RC)
        with plt.rc_context(rc):
            fig = draw()
            for w in fp.check(fig, "en", "light"):
                print(f"  [WARN {stem}] {w}")
            for ext, kw in (("png", {"dpi": 600}), ("pdf", {})):
                fig.savefig(DOCS / f"{stem}.{ext}", facecolor="white", edgecolor="none",
                            bbox_inches="tight", pad_inches=0.03, **kw)
            w_in, h_in = fig.get_size_inches()
            plt.close(fig)
        print(f"  docs/{stem}.png / .pdf  ok（版面 {w_in / CM:.1f} × {h_in / CM:.1f} cm）")
    finally:
        fp.set_lang(prev)


def export_pub(draw: Callable[[], "plt.Figure"], stem: str) -> None:
    fp.export_variants(draw, stem, extra_rc=JOURNAL_RC, pad_inches=0.03)


def run(figs: dict[str, Callable[[], "plt.Figure"]]) -> None:
    """依指令列：預設輸出 docs/ 英文白底；--pub 輸出 figures_pub 四版本。"""
    for stem, draw in figs.items():
        if fp.wants_pub():
            export_pub(draw, stem)
        else:
            save_default(draw, stem)
