"""線上閱讀：《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》

內容由 docs/book/web/_export_web.py 匯出到 data/book/（book.json、chapters/NN.md、img/；
英文、日文譯文在 data/book/en|ja/chapters/，為 AI 輔助翻譯，中文原稿為準）。
介面語言跟隨主程式的 app_lang（zh／ja／en）；某章沒有譯文時顯示中文原稿並加註。
網址深連結：?mode=book&ch=05（章號兩位數；附錄為 A1、A2；不帶 ch 為封面與目錄）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

BOOK_DIR = Path("data") / "book"
ASIDE_PREFIX = ("**插敘：", "**Sidebar: ", "**コラム：")
UI = {
    "cover": {"zh": "封面與目錄", "en": "Cover and contents", "ja": "表紙と目次"},
    "chapter": {"zh": "章節", "en": "Chapter", "ja": "章"},
    "toc": {"zh": "目錄", "en": "Contents", "ja": "目次"},
    "author": {"zh": "作者", "en": "Author", "ja": "著者"},
    "version": {"zh": "版本", "en": "Version", "ja": "版"},
    "date": {"zh": "日期", "en": "Date", "ja": "日付"},
    "license": {"zh": "授權", "en": "License", "ja": "利用許諾"},
    "license_v": {"zh": "請來信洽詢", "en": "please contact the author", "ja": "著者にお問い合わせください"},
    "aside": {"zh": "背景脈絡｜外部事件，非本專案分析案例", "en": "Background | external event, not a case analyzed by this project",
              "ja": "背景｜外部の出来事であり、本プロジェクトの分析事例ではない"},
    "footer": {"zh": "線上版取自送審版書稿 {v}（{d}）。", "en": "Online edition based on the review manuscript {v} ({d}).",
               "ja": "オンライン版は審査用原稿 {v}（{d}）に基づく。"},
    "fallback": {"zh": "", "en": "This chapter has not been translated yet; the Traditional Chinese original is shown.",
                 "ja": "この章はまだ翻訳されていないため、繁体字中国語の原文を表示している。"},
    "ai_note": {"zh": "", "en": "English edition: AI-assisted translation; the Traditional Chinese original prevails.",
                "ja": "日本語版：AI支援による翻訳。中国語の原文が優先する。"},
}


def _lang() -> str:
    lg = st.session_state.get("app_lang", "zh")
    return lg if lg in ("zh", "en", "ja") else "zh"


def _u(key: str, **kw) -> str:
    s = UI[key].get(_lang()) or UI[key]["zh"]
    return s.format(**kw) if kw else s


@st.cache_data(show_spinner=False)
def _meta() -> dict:
    return json.loads((BOOK_DIR / "book.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _chapter(cid: str, lang: str) -> tuple[str, bool]:
    """回傳 (Markdown, 是否為譯文)。"""
    if lang != "zh":
        p = BOOK_DIR / lang / "chapters" / f"{cid}.md"
        if p.exists():
            return _read(str(p)), True
    return _read(str(BOOK_DIR / "chapters" / f"{cid}.md")), False


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
        if l.startswith(ASIDE_PREFIX):
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
    lang = _lang()
    md, translated = _chapter(cid, lang)
    title, body = md.split("\n", 1) if "\n" in md else (md, "")
    st.title(title.lstrip("# ").strip())
    if lang != "zh" and not translated:
        st.info(_u("fallback"))
    for kind, payload in _blocks(body):
        if kind == "text":
            if payload.strip():
                st.markdown(_md(payload), unsafe_allow_html=True)
        elif kind == "aside":
            head, para = payload
            with st.container(border=True):
                st.markdown(f"<strong>{head}</strong>　<span style='font-size:0.8em;color:#8A96A6'>{_u('aside')}</span>", unsafe_allow_html=True)
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


def _texts(meta: dict) -> tuple[str, str, str, dict]:
    """依語言回傳 (書名, 副標, 封面說明, {章號: 章名})；缺譯文的章名退回中文。"""
    zh_names = {c["id"]: c["title"] for c in meta["chapters"]}
    lg = _lang()
    tr = meta.get("i18n", {}).get(lg) if lg != "zh" else None
    if not tr:
        return meta["title"], meta["subtitle"], meta.get("cover_credit", ""), zh_names
    return tr["title"], tr["subtitle"], tr.get("cover_credit", ""), {**zh_names, **tr.get("chapters", {})}


def _render_cover(meta: dict):
    title, sub, cred, names = _texts(meta)
    st.title(title)
    st.subheader(sub)
    cov = BOOK_DIR / "img" / "cover.jpg"
    if cov.exists():
        st.image(str(cov), width="stretch", caption=cred)
    st.markdown(f"**{_u('author')}**：{meta['author']}　｜　**{_u('version')}**：{meta['version']}　｜　**{_u('date')}**：{meta['date']}　｜　{meta['copyright']}　｜　**{_u('license')}**：{_u('license_v')}")
    if _u("ai_note"):
        st.caption(_u("ai_note"))
    st.markdown("---")
    st.markdown(f"### {_u('toc')}")
    for c in meta["chapters"]:
        st.button(names[c["id"]], key=f"toc_{c['id']}", on_click=_goto, args=(c["id"],), width="stretch")


def render_book():
    meta = _meta()
    title, sub, _, chap_names = _texts(meta)
    ids = ["cover"] + [c["id"] for c in meta["chapters"]]
    names = {"cover": _u("cover"), **chap_names}
    qp = st.query_params.get("ch")
    if "book_ch" not in st.session_state:
        st.session_state["book_ch"] = qp if qp in ids else ("0" + qp if qp and ("0" + qp) in ids else "cover")
    with st.sidebar:
        st.markdown(f"**{title}**  \n{sub}")
        st.selectbox(_u("chapter"), options=ids, key="book_ch", format_func=lambda k: names.get(k, k))
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
    c2.button(_u("cover"), key="home", on_click=_goto, args=(None,), width="stretch")
    if k + 1 < len(ids):
        c3.button(names[ids[k + 1]] + " →", key="next", on_click=_goto, args=(ids[k + 1],), width="stretch")
    st.caption(_u("footer", v=meta["version"], d=meta["date"]) + f"{meta['copyright']}")
