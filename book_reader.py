"""線上閱讀：《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》

內容由 docs/book/web/_export_web.py 匯出到 data/book/（book.json、chapters/NN.md、img/）。
網址深連結：?mode=book&ch=05（章號兩位數；附錄為 A1、A2；不帶 ch 為封面與目錄）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

BOOK_DIR = Path("data") / "book"
ASIDE_TAG = "背景脈絡｜外部事件，非本專案分析案例"


@st.cache_data(show_spinner=False)
def _meta() -> dict:
    return json.loads((BOOK_DIR / "book.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def _chapter(cid: str) -> str:
    return (BOOK_DIR / "chapters" / f"{cid}.md").read_text(encoding="utf-8")


_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")


def _md(s: str) -> str:
    """粗體改為 <strong>：CommonMark 規則下，「？**」後接上標或中文字時 ** 不會閉合，中文書稿常見。"""
    return _BOLD.sub(r"<strong>\1</strong>", s)


def _blocks(md: str):
    """把章節 Markdown 切成 (kind, payload)：text／image／aside。"""
    lines = md.split("\n")
    buf: list[str] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^!\[([^\]]*)\]\((img/[^)]+)\)\s*$", l)
        if m:
            if buf:
                yield "text", "\n".join(buf)
                buf = []
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            cap = []
            while j < len(lines) and lines[j].strip():
                cap.append(lines[j].rstrip())
                j += 1
            yield "image", (m.group(2), cap)
            i = j
            continue
        if l.startswith("**插敘："):
            if buf:
                yield "text", "\n".join(buf)
                buf = []
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            k = j
            while k < len(lines) and lines[k].strip():
                k += 1
            yield "aside", (l.strip("* "), "\n".join(lines[j:k]))
            i = k
            continue
        buf.append(l)
        i += 1
    if buf:
        yield "text", "\n".join(buf)


def _render_chapter(cid: str):
    md = _chapter(cid)
    title, body = md.split("\n", 1) if "\n" in md else (md, "")
    st.title(title.lstrip("# ").strip())
    for kind, payload in _blocks(body):
        if kind == "text":
            if payload.strip():
                st.markdown(_md(payload), unsafe_allow_html=True)
        elif kind == "aside":
            head, para = payload
            with st.container(border=True):
                st.markdown(f"<strong>{head}</strong>　<span style='font-size:0.8em;color:#8A96A6'>{ASIDE_TAG}</span>", unsafe_allow_html=True)
                st.markdown(_md(para), unsafe_allow_html=True)
        elif kind == "image":
            src, cap = payload
            p = BOOK_DIR / src
            if p.exists():
                try:
                    from PIL import Image
                    w, h = Image.open(p).size
                except Exception:
                    w, h = 4, 3
                if h > w:  # 直式照片不撐滿版面
                    c1, _ = st.columns([2, 3])
                    c1.image(str(p))
                else:
                    st.image(str(p), width="stretch")
            if cap:
                st.caption(_md("  \n".join(c.rstrip() for c in cap)), unsafe_allow_html=True)


def _goto(cid: str | None):
    st.session_state["book_ch"] = cid or "cover"


def _render_cover(meta: dict):
    st.title(meta["title"])
    st.subheader(meta["subtitle"])
    cov = BOOK_DIR / "img" / "cover.jpg"
    if cov.exists():
        st.image(str(cov), width="stretch", caption=meta.get("cover_credit", ""))
    st.markdown(f"**作者**：{meta['author']}　｜　**版本**：{meta['version']}　｜　**日期**：{meta['date']}　｜　{meta['copyright']}　｜　**授權**：{meta['license']}")
    st.markdown("---")
    st.markdown("### 目錄")
    for c in meta["chapters"]:
        st.button(c["title"], key=f"toc_{c['id']}", on_click=_goto, args=(c["id"],), width="stretch")


def render_book():
    meta = _meta()
    ids = ["cover"] + [c["id"] for c in meta["chapters"]]
    names = {"cover": "封面與目錄", **{c["id"]: c["title"] for c in meta["chapters"]}}
    qp = st.query_params.get("ch")
    if "book_ch" not in st.session_state:
        st.session_state["book_ch"] = qp if qp in ids else ("0" + qp if qp and ("0" + qp) in ids else "cover")
    with st.sidebar:
        st.markdown(f"**{meta['title']}**  \n{meta['subtitle']}")
        st.selectbox("章節", options=ids, key="book_ch", format_func=lambda k: names.get(k, k))
        st.caption(f"{meta['author']}｜{meta['version']}｜{meta['date']} {meta['copyright']}")
    cid = st.session_state["book_ch"]
    # 不回寫 st.query_params：在 huggingface.co 外層頁中，iframe 改網址會被外層同步回來，
    # 形成不斷重新載入與自動換章（看起來像左右抖動）。深連結只在首次載入時讀取 ?ch=。
    if cid == "cover":
        _render_cover(meta)
        return
    _render_chapter(cid)
    st.markdown("---")
    k = ids.index(cid)
    c1, c2, c3 = st.columns(3)
    if k > 1:
        c1.button("← " + names[ids[k - 1]], key="prev", on_click=_goto, args=(ids[k - 1],), width="stretch")
    c2.button("封面與目錄", key="home", on_click=_goto, args=(None,), width="stretch")
    if k + 1 < len(ids):
        c3.button(names[ids[k + 1]] + " →", key="next", on_click=_goto, args=(ids[k + 1],), width="stretch")
    st.caption(f"線上版取自送審版書稿 {meta['version']}（{meta['date']}）。{meta['copyright']}，授權{meta['license']}。")
