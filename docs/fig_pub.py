#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fig_pub.py — 論文／報告圖之「高解析 × 中英 × 白底／黑底」四版本共用模組。

用法（產生程式端）：
    import fig_pub as fp
    def draw():                       # 不存檔，回傳 Figure；文字一律以 fp.t("中文", "English") 提供
        fig, ax = plt.subplots(...)
        ax.set_title(fp.t("標題", "Title"))
        return fig
    if fp.wants_pub():                # 指令列帶 --pub
        fp.export_variants(draw, "fig_xxx")
    else:                             # 原本預設輸出不變
        draw().savefig(...)

輸出：docs/figures_pub/<stem>/<stem>_<lang>_<theme>.png（600 dpi）與同名 .pdf（向量）。
  lang ∈ {zh, en}；theme ∈ {light（白底黑字）, dark（黑底白字）}

黑底版作法：繪圖函式照常以白底配色繪製，完成後由 `to_dark()` 走訪所有圖元，
將每個顏色在 HLS 空間做「亮度反轉、色相與飽和度不變」（L → 1 − L）：
白底→黑底、黑字→白字、淺色填色→深色填色、深色線→淺色線；中等亮度之資料色
（藍、橘、紅、綠）色相保持可辨識。色圖（colormap）亦逐點同樣轉換，色條與資料一致。
"""
from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import Collection  # noqa: E402
from matplotlib.colors import ListedColormap, to_rgba  # noqa: E402
from matplotlib.image import AxesImage  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.text import Text  # noqa: E402

DOCS = Path(__file__).resolve().parent
PUB_DIR = DOCS / "figures_pub"

FONTS = {
    "zh": ["Microsoft JhengHei", "DejaVu Sans", "Noto Sans TC"],
    "en": ["Arial", "DejaVu Sans", "Microsoft JhengHei"],   # 末項僅補 ① 等符號；英文版殘留中文由 check() 另行攔截
}
THEMES = {
    "light": {"bg": "#ffffff", "fg": "#000000"},
    "dark": {"bg": "#000000", "fg": "#ffffff"},
}

_LANG = "zh"          # 預設中文：未呼叫 export_variants 時，t() 一律回傳中文 → 原預設輸出不變
_CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


# ── 語言 ─────────────────────────────────────────────────────────────────────
def t(zh: str, en: str) -> str:
    """依目前語言回傳字串。"""
    return en if _LANG == "en" else zh


def lang() -> str:
    return _LANG


_IN_PUB = False


def in_pub() -> bool:
    """export_variants 執行中為 True：可供繪圖函式只在出版版本加的微調（不影響原預設輸出）。"""
    return _IN_PUB


def set_lang(l: str) -> None:
    global _LANG
    assert l in ("zh", "en")
    _LANG = l


def is_en() -> bool:
    return _LANG == "en"


def wants_pub(argv=None) -> bool:
    return "--pub" in (sys.argv if argv is None else argv)


def rc_for(l: str) -> dict:
    """該語言之字型 rcParams（中文：微軟正黑體；英文：Arial），缺字依序 fallback 至 DejaVu Sans。"""
    return {
        "font.family": FONTS[l],     # 以清單指定，matplotlib 才會逐字 fallback（"sans-serif" 泛稱不會）
        "font.sans-serif": FONTS[l],
        "axes.unicode_minus": False,
        "mathtext.fontset": "dejavusans",
        "pdf.fonttype": 42,          # PDF 內嵌 TrueType（可編輯、可檢索）
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    }


# ── 黑底轉換 ─────────────────────────────────────────────────────────────────
def invert_color(c):
    """HLS 亮度反轉；alpha 保留。"""
    r, g, b, a = to_rgba(c)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    # 半透明色（alpha < 0.75，多為區間底色、陰影帶）在黑底上本已偏暗：取 max(L, 1−L) 保持可見
    l2 = max(l, 1.0 - l) if 0 < a < 0.75 else 1.0 - l
    r, g, b = colorsys.hls_to_rgb(h, l2, s)
    return (r, g, b, a)


def _inv_array(arr):
    import numpy as np
    arr = np.asarray(arr, float)
    if arr.size == 0:
        return arr
    return np.array([invert_color(tuple(x)) for x in arr.reshape(-1, 4)])


def invert_cmap(cmap):
    import numpy as np
    cols = cmap(np.linspace(0, 1, 256))
    new = ListedColormap([invert_color(tuple(c)) for c in cols], name=f"{cmap.name}_inv")
    try:
        new.set_bad(invert_color(cmap.get_bad()))
        new.set_under(invert_color(cmap.get_under()))
        new.set_over(invert_color(cmap.get_over()))
    except Exception:
        pass
    return new


def _is_none(c) -> bool:
    return isinstance(c, str) and c.lower() == "none"


def _recolor_patch(p: Patch) -> None:
    # 原為透明（"none"）者不動：否則 set_*color 會套用 patch 的 alpha，使透明邊框／底色現形
    fc, ec = p.get_facecolor(), p.get_edgecolor()
    if fc[3] > 0:
        p.set_facecolor(invert_color(fc))
    if ec[3] > 0:
        p.set_edgecolor(invert_color(ec))


def to_dark(fig) -> list[str]:
    """將以白底配色繪成之 Figure 原地轉為黑底白字版；回傳無法轉換之警告。"""
    warns: list[str] = []
    seen: set[int] = set()

    def visit(art):
        if id(art) in seen:
            return
        seen.add(id(art))
        if isinstance(art, Text):
            art.set_color(invert_color(art.get_color()))
            bp = art.get_bbox_patch()
            if bp is not None and id(bp) not in seen:
                seen.add(id(bp))
                _recolor_patch(bp)
            ap = getattr(art, "arrow_patch", None)
            if ap is not None and id(ap) not in seen:
                seen.add(id(ap))
                _recolor_patch(ap)
        elif isinstance(art, Line2D):
            # 先讀出標記色再改線色：標記色為 "auto" 時會跟隨線色，先改線色會造成二次反轉
            pairs = [(set_, getattr(art, get)()) for get, set_ in (
                ("get_markerfacecolor", "set_markerfacecolor"),
                ("get_markeredgecolor", "set_markeredgecolor"),
                ("get_markerfacecoloralt", "set_markerfacecoloralt"))]
            art.set_color(invert_color(art.get_color()))
            for set_, c in pairs:
                if not _is_none(c):
                    getattr(art, set_)(invert_color(c))
        elif isinstance(art, Patch):
            _recolor_patch(art)
        elif isinstance(art, Collection):
            mapped = art.get_array() is not None
            if mapped:
                art.set_cmap(invert_cmap(art.get_cmap()))
            else:
                fc = art.get_facecolor()
                if len(fc) and fc[:, 3].max() > 0:          # 全透明（facecolors="none"）者不動
                    art.set_facecolor(_inv_array(fc))
            orig_ec = getattr(art, "_original_edgecolor", None)
            if not (isinstance(orig_ec, str) and orig_ec == "face"):
                ec = art.get_edgecolor()
                if len(ec) and ec[:, 3].max() > 0 and not (mapped and getattr(art, "_edge_is_mapped", False)):
                    art.set_edgecolor(_inv_array(ec))
        elif isinstance(art, AxesImage):
            if art.get_array() is not None and getattr(art.get_array(), "ndim", 2) == 2:
                art.set_cmap(invert_cmap(art.get_cmap()))
            else:
                warns.append("RGB 影像無法轉為黑底版（保留原色）")

    for art in fig.findobj(include_self=True):
        visit(art)
    return warns


# ── 檢查 ─────────────────────────────────────────────────────────────────────
def _lum(c) -> float:
    r, g, b, _ = to_rgba(c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def check(fig, l: str, theme: str) -> list[str]:
    """英文版殘留中文字、黑底版殘留暗色文字之檢查。"""
    out = []
    for txt in fig.findobj(Text):
        s = txt.get_text()
        if not s.strip() or not txt.get_visible():
            continue
        if l == "en" and _CJK.search(s):
            out.append(f"英文版含中文：{s[:40]!r}")
        if theme == "dark" and _lum(txt.get_color()) < 0.30:
            out.append(f"黑底版暗色文字：{s[:40]!r} color={txt.get_color()}")
    return out


# ── 中文字型缺 U+2212 之對數刻度修正 ─────────────────────────────────────────
def fix_log_minus(fig) -> None:
    """微軟正黑體缺數學負號（U+2212），對數軸 10⁻¹ 等刻度在中文版會成缺字方塊（mathtext 不做字型 fallback）。
    將 Log 類刻度格式改為一般數字（0.1、1、10）：原本會標示的刻度才標示，標示位置不變。"""
    from matplotlib.ticker import Formatter, LogFormatter

    class _Plain(Formatter):
        def __init__(self, inner):
            self.inner = inner

        def set_axis(self, axis):
            super().set_axis(axis)
            self.inner.set_axis(axis)

        def set_locs(self, locs):
            super().set_locs(locs)
            self.inner.set_locs(locs)

        def __call__(self, x, pos=None):
            return f"{x:g}" if self.inner(x, pos) else ""

    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            for get, set_ in ((axis.get_major_formatter, axis.set_major_formatter),
                              (axis.get_minor_formatter, axis.set_minor_formatter)):
                f = get()
                if isinstance(f, LogFormatter):
                    set_(_Plain(f))


# ── 匯出 ─────────────────────────────────────────────────────────────────────
def export_variants(draw_fn: Callable[[], "plt.Figure"], stem: str, *, out_root: Path | None = None,
                    langs=("zh", "en"), themes=("light", "dark"), dpi: int = 600,
                    formats=("png", "pdf"), bbox_inches="tight", pad_inches=0.08,
                    extra_rc: dict | None = None) -> list[Path]:
    """對 lang × theme 呼叫 draw_fn()（每次重繪），輸出 <out_root>/<stem>/<stem>_<lang>_<theme>.<fmt>。"""
    out_dir = (out_root or PUB_DIR) / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    global _IN_PUB
    prev = _LANG
    _IN_PUB = True
    try:
        for l in langs:
            set_lang(l)
            for th in themes:
                rc = rc_for(l)
                if extra_rc:
                    rc.update(extra_rc)
                with plt.rc_context(rc):
                    fig = draw_fn()
                    if l == "zh":
                        fix_log_minus(fig)
                    warns = to_dark(fig) if th == "dark" else []
                    warns += check(fig, l, th)
                    bg = THEMES[th]["bg"]
                    for fmt in formats:
                        p = out_dir / f"{stem}_{l}_{th}.{fmt}"
                        kw = dict(facecolor=bg, edgecolor="none", bbox_inches=bbox_inches,
                                  pad_inches=pad_inches)
                        if fmt == "png":
                            kw["dpi"] = dpi
                        fig.savefig(p, **kw)
                        written.append(p)
                    plt.close(fig)
                for w in dict.fromkeys(warns):
                    print(f"  [WARN {stem} {l}/{th}] {w}")
                print(f"  {stem}_{l}_{th}  ok")
    finally:
        set_lang(prev)
        _IN_PUB = False
    return written
