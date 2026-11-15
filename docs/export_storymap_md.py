#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_storymap_md.py — 把機動偵測 App 的「太空態勢感知 StoryMap」（?mode=storymap，32 個案例＋首頁）匯出為 Markdown。

做法：以「記錄用的假 streamlit」取代 streamlit，執行 maneuver_app_2026November.py 的定義段（頁面主流程之前），
再逐一呼叫 render_storymap_landing／render_storymap_case1…32；所有 st.* 輸出依序轉為 Markdown：
  title／header／subheader → # ／## ／###；markdown／write → 原文；caption → 引用；info／success／warning／error → 帶圖示的引用；
  dataframe／table → Markdown 表格；metric → 條列；plotly／pyplot／image → PNG（kaleido／matplotlib），失敗時以圖表標題佔位；
  按鈕一律視為未按、輸入元件取預設值（即使用者第一次開啟頁面時看到的內容）。

用法：python docs/export_storymap_md.py [輸出目錄=docs/storymap_md] [--lang zh|ja|en] [--no-img] [--only case3,case7]
輸出：<目錄>/00_首頁.md、caseNN_*.md、README.md（索引）、StoryMap_全32案例.md（合併版）、img/*.png
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "maneuver_app_2026November.py"
STOP_MARK = "_qp = st.query_params"


# ── 記錄器 ────────────────────────────────────────────────────────────────────
class Rec:
    def __init__(self):
        self.out: list[str] = []
        self.imgdir: Path | None = None
        self.prefix = "x"
        self.n_img = 0
        self.no_img = False
        self.warn: list[str] = []

    def add(self, s: str):
        s = (s or "").rstrip()
        if s:
            self.out.append(s)


R = Rec()


def _txt(x) -> str:
    return "" if x is None else str(x)


def _quote(s: str, icon: str = "") -> str:
    lines = _txt(s).strip().split("\n")
    import unicodedata
    first = lines[0].lstrip("*_ ")[:1]
    if icon and not (first and unicodedata.category(first).startswith("S")):   # 原文已以圖示開頭者不重複加
        lines[0] = f"{icon} {lines[0]}"
    return "\n".join("> " + ln if ln.strip() else ">" for ln in lines)


def _df_md(df, max_rows: int = 80) -> str:
    import pandas as pd
    if hasattr(df, "data") and hasattr(df, "to_html") and not isinstance(df, pd.DataFrame):
        df = df.data                                    # pandas Styler
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception:
            return _txt(df)
    note = ""
    if len(df) > max_rows:
        note = f"\n\n*（共 {len(df)} 列，僅列前 {max_rows} 列）*"
        df = df.head(max_rows)
    if not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()

    def cell(v):
        if isinstance(v, float):
            s = f"{v:.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
        else:
            s = _txt(v)
        return s.replace("|", "\\|").replace("\n", " ")
    head = "| " + " | ".join(cell(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body]) + note


def _save_png(data: bytes, title: str) -> str:
    R.n_img += 1
    name = f"{R.prefix}_{R.n_img:02d}.png"
    (R.imgdir / name).write_bytes(data)
    return f"![{title or '圖'}](img/{name})"


def _fig_title(fig) -> str:
    try:
        t = fig.layout.title.text
        return re.sub(r"<[^>]+>", " ", t).strip() if t else ""
    except Exception:
        return ""


# ── 假 streamlit ──────────────────────────────────────────────────────────────
class Dummy:
    """任意屬性／呼叫皆回傳自身；可當 context manager。"""
    def __getattr__(self, k):
        return Dummy()

    def __call__(self, *a, **k):
        return Dummy()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False


class StopRender(Exception):
    pass


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


class Box:
    """columns／container／expander／tabs／sidebar 等容器：方法與 st 相同、可 with。"""
    def __init__(self, label: str | None = None, level: str = "####"):
        if label:
            R.add(f"{level} {label}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, k):
        return getattr(FakeST, k)


def _value(kw, default=None):
    return kw.get("value", default)


class FakeSTModule(types.ModuleType):
    def __getattr__(self, k):                          # 未實作者：不輸出
        if k.startswith("__"):
            raise AttributeError(k)
        return Dummy()


FakeST = FakeSTModule("streamlit")
FakeST.session_state = SessionState()
FakeST.query_params = {}
FakeST.secrets = {}
FakeST.sidebar = Box()
FakeST.column_config = Dummy()


def _md(body="", *a, **k):
    R.add(_txt(body))


def _write(*args, **k):
    import pandas as pd
    for x in args:
        if isinstance(x, pd.DataFrame) or (hasattr(x, "data") and hasattr(x, "to_html")):
            R.add(_df_md(x))
        elif hasattr(x, "to_plotly_json"):
            _plotly(x)
        else:
            R.add(_txt(x))


_NOFIG = object()


def _plotly(fig, *a, **k):
    if fig is None:                                    # 畫圖輔助函式已失敗並寫入佔位
        return
    title = _fig_title(fig)
    if not R.no_img:
        try:
            png = fig.to_image(format="png", width=1100, height=fig.layout.height or 520, scale=1)
            R.add(_save_png(png, title or "互動圖表"))
            return
        except Exception as e:
            R.warn.append(f"plotly 轉圖失敗：{type(e).__name__}")
    R.add(f"📊 *互動圖表{('：' + title) if title else ''}（請至線上版檢視）*")


def _pyplot(fig=_NOFIG, *a, **k):
    import matplotlib.pyplot as plt
    if fig is None:                                    # 畫圖輔助函式已失敗並寫入佔位
        return
    fig = plt.gcf() if fig is _NOFIG else fig
    if R.no_img:
        R.add("📊 *圖表（請至線上版檢視）*")
        return
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    R.add(_save_png(buf.getvalue(), "圖"))


def _bar_chart(data=None, *a, x=None, y=None, **k):
    """st.bar_chart：以 matplotlib 重畫（資料即呼叫參數）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    if R.no_img or data is None:
        R.add("📊 *長條圖（請至線上版檢視）*")
        return
    try:
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        df = pd.DataFrame(data)
        if x is not None and x in df.columns:
            df = df.set_index(x)
        if y is not None:
            df = df[[y] if isinstance(y, str) else list(y)]
        fig, ax = plt.subplots(figsize=(9, 3.8), dpi=110)
        df.plot.bar(ax=ax, legend=df.shape[1] > 1, color="#2E6FD8" if df.shape[1] == 1 else None)
        ax.grid(axis="y", color="#E3E8EF"); ax.set_axisbelow(True)
        plt.xticks(rotation=45, ha="right", fontsize=8)
        _pyplot(fig)
        plt.close(fig)
    except Exception as e:
        R.warn.append(f"bar_chart：{type(e).__name__}")
        R.add("📊 *長條圖（請至線上版檢視）*")


def _image(img, caption=None, *a, **k):
    if isinstance(img, (str, Path)) and Path(img).exists() and not R.no_img:
        R.add(_save_png(Path(img).read_bytes(), _txt(caption)))
    elif isinstance(img, (bytes, bytearray)) and not R.no_img:
        R.add(_save_png(bytes(img), _txt(caption)))
    else:
        R.add(f"🖼️ *圖片：{_txt(caption) or img}*")
    if caption:
        R.add(f"*{caption}*")


def _metric(label, value=None, delta=None, *a, **k):
    R.add(f"- **{label}**：{_txt(value)}" + (f"（{delta}）" if delta not in (None, "") else ""))


def _columns(spec, *a, **k):
    n = spec if isinstance(spec, int) else len(spec)
    return [Box() for _ in range(n)]


def _tabs(labels, *a, **k):
    return [_TabBox(lb) for lb in labels]


class _TabBox(Box):
    def __init__(self, label):
        self._label = label

    def __enter__(self):
        R.add(f"#### 〔分頁〕{self._label}")
        return self


def _expander(label, *a, **k):
    return Box(f"▸ {label}", "####")


def _cache(*da, **dk):
    def deco(f):
        f.clear = lambda *a, **k: None
        return f
    if da and callable(da[0]) and not dk:
        return deco(da[0])
    return deco


def _select(label, options=(), index=0, *a, **k):
    options = list(options)
    return options[index] if options and index is not None and index < len(options) else None


def _multiselect(label, options=(), default=None, *a, **k):
    return list(default or [])


def _slider(label, min_value=None, max_value=None, value=None, *a, **k):
    return value if value is not None else min_value


def _number_input(label, min_value=None, max_value=None, value=None, *a, **k):
    return value if value is not None else (min_value if min_value is not None else 0)


def _stop(*a, **k):
    raise StopRender()


for name, fn in {
    "title": lambda s, *a, **k: R.add(f"# {s}"),
    "header": lambda s, *a, **k: R.add(f"## {s}"),
    "subheader": lambda s, *a, **k: R.add(f"### {s}"),
    "markdown": _md, "write": _write, "text": lambda s, *a, **k: R.add(_txt(s)),
    "latex": lambda s, *a, **k: R.add(f"$$\n{s}\n$$"),
    "code": lambda s, language=None, *a, **k: R.add(f"```{language or ''}\n{s}\n```"),
    "caption": lambda s, *a, **k: R.add(_quote(s)),
    "info": lambda s, *a, **k: R.add(_quote(s, "ℹ️")),
    "success": lambda s, *a, **k: R.add(_quote(s, "✅")),
    "warning": lambda s, *a, **k: R.add(_quote(s, "⚠️")),
    "error": lambda s, *a, **k: R.add(_quote(s, "❌")),
    "dataframe": lambda df, *a, **k: R.add(_df_md(df)), "table": lambda df, *a, **k: R.add(_df_md(df)),
    "data_editor": lambda df, *a, **k: (R.add(_df_md(df)), df)[1],
    "json": lambda obj, *a, **k: R.add(f"```json\n{obj}\n```"),
    "metric": _metric, "plotly_chart": _plotly, "pyplot": _pyplot, "image": _image,
    "bar_chart": _bar_chart,
    "line_chart": lambda *a, **k: R.add("📊 *折線圖（請至線上版檢視）*"),
    "altair_chart": lambda *a, **k: R.add("📊 *圖表（請至線上版檢視）*"),
    "columns": _columns, "tabs": _tabs, "expander": _expander,
    "container": lambda *a, **k: Box(), "spinner": lambda *a, **k: Box(), "empty": lambda *a, **k: Box(),
    "status": lambda *a, **k: Box(), "form": lambda *a, **k: Box(), "popover": lambda *a, **k: Box(),
    "button": lambda *a, **k: False, "download_button": lambda *a, **k: False, "link_button": lambda *a, **k: False,
    "form_submit_button": lambda *a, **k: False, "checkbox": lambda *a, **k: _value(k, False),
    "toggle": lambda *a, **k: _value(k, False), "radio": _select, "selectbox": _select,
    "multiselect": _multiselect, "slider": _slider, "select_slider": lambda label, options=(), value=None, *a, **k: value,
    "number_input": _number_input, "text_input": lambda *a, **k: _value(k, ""),
    "text_area": lambda *a, **k: _value(k, ""), "date_input": lambda *a, **k: _value(k),
    "file_uploader": lambda *a, **k: None, "progress": lambda *a, **k: Dummy(),
    "cache_data": _cache, "cache_resource": _cache, "fragment": _cache,
    "rerun": lambda *a, **k: None, "stop": _stop, "set_page_config": lambda *a, **k: None,
    "toast": lambda *a, **k: None, "divider": lambda *a, **k: R.add("---"),
}.items():
    setattr(FakeST, name, fn)


# ── 主流程 ────────────────────────────────────────────────────────────────────
def load_app(lang: str) -> dict:
    sys.modules["streamlit"] = FakeST
    FakeST.session_state["app_lang"] = lang
    src = APP.read_text(encoding="utf-8")
    cut = src.index(STOP_MARK)
    ns: dict = {"__name__": "storymap_export", "__file__": str(APP)}
    sys.path.insert(0, str(ROOT))
    code = compile(src[:cut], str(APP), "exec")
    exec(code, ns)
    # 畫圖輔助函式失敗（多為離線資料缺漏）時只讓該圖改佔位，不中斷整個案例
    pat = re.compile(r"^(render_case\d+_\w*figure|_\w*chart|_\w*fig)$")
    for k, f in list(ns.items()):
        code_obj = getattr(f, "__code__", None)
        if pat.match(k) and code_obj is not None and code_obj.co_filename == str(APP):
            ns[k] = _guard(f, k)
    return ns


def _guard(f, name):
    def g(*a, **k):
        try:
            return f(*a, **k)
        except Exception as e:
            R.warn.append(f"{name}：{type(e).__name__}")
            R.add(f"📊 *圖表未能於離線匯出時產生（{name}：{type(e).__name__}: {e}），請至線上版檢視*")
            return None
    return g


def slug(s: str) -> str:
    s = re.sub(r"^[#\s📖]+", "", s)
    s = re.sub(r"[\\/:*?\"<>|？：，。、「」（）()\s]+", "_", s).strip("_")
    return s[:40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", nargs="?", default=str(ROOT / "docs" / "storymap_md"))
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--no-img", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.outdir)
    (out / "img").mkdir(parents=True, exist_ok=True)
    R.imgdir, R.no_img = out / "img", a.no_img
    import os
    os.chdir(ROOT)
    ns = load_app(a.lang)

    cases = ["landing"] + [f"case{i}" for i in range(1, 33)]
    if a.only:
        cases = [c for c in cases if c in a.only.split(",")]
    index, merged = [], []
    for c in cases:
        fn = ns.get(f"render_storymap_{c}")
        R.out, R.prefix, R.n_img, R.warn = [], c, 0, []
        FakeST.session_state.clear()
        FakeST.session_state.update(app_lang=a.lang, app_mode="storymap", storymap_case=c)
        t0, err = time.time(), None
        try:
            fn()
        except StopRender:
            pass
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc(limit=3)
            R.add(f"> ❌ **匯出中斷**：此案例在離線匯出時發生錯誤（{err}），以下內容未能產出；請至線上版檢視完整內容。")
        body = "\n\n".join(R.out)
        title = next((ln.lstrip("# ").strip() for ln in R.out if ln.startswith("#")), c)
        no = 0 if c == "landing" else int(c[4:])
        fname = "00_首頁.md" if c == "landing" else f"case{no:02d}_{slug(title)}.md"
        url = "https://rhynowu-maneuver-detection-i18n.hf.space/?mode=storymap" + ("" if c == "landing" else f"&case={c}")
        head = f"<!-- 由 docs/export_storymap_md.py 自 maneuver_app_2026November.py 匯出；線上版：{url} -->\n\n"
        (out / fname).write_text(head + body + f"\n\n---\n線上互動版：<{url}>\n", encoding="utf-8")
        merged.append(f"<a id=\"{c}\"></a>\n\n" + re.sub(r"(?m)^(#{1,5}) ", r"#\1 ", body) if c != "landing" else body)
        status = "⚠️ 部分內容未能匯出" if err else ("圖表以佔位顯示" if R.warn else "完整")
        index.append((no, title, fname, status, round(time.time() - t0, 1), err, len(set(R.warn))))
        print(f"[{'FAIL' if err else 'OK'}] {c:7s} {time.time() - t0:5.1f}s  img={R.n_img}  {title[:50]}", flush=True)

    lines = ["# 太空態勢感知 StoryMap — 32 個案例（Markdown 匯出）", "",
             "來源：機動偵測儀表板 `?mode=storymap`（<https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n>），"
             "以 `docs/export_storymap_md.py` 由 App 程式碼離線執行匯出；互動元件（按鈕、滑桿）取預設狀態。", "",
             "| # | 案例 | 檔案 | 匯出狀態 |", "|---|---|---|---|"]
    for no, title, fname, status, sec, err, nw in index:
        lines.append(f"| {no or '—'} | {title} | [{fname}]({fname}) | {status} |")
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    toc = "\n".join(f"- [{t}](#{'case' + str(n) if n else 'landing'})" for n, t, *_ in index if n)
    (out / "StoryMap_全32案例.md").write_text(
        "# 太空態勢感知 StoryMap — 全 32 案例\n\n## 目錄\n\n" + toc + "\n\n---\n\n" + "\n\n---\n\n".join(merged) + "\n",
        encoding="utf-8")
    print("輸出", out)


if __name__ == "__main__":
    main()
