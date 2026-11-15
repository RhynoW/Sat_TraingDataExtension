#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md_to_docx_tasa.py — 以期中報告之正式文件格式為範本，把期末報告 Markdown 轉為 Word。
執行單位一律為「社團法人中華民國國防科技學術研究學會」：轉換時移除範本中的學校名稱與院徽（strip_school）。

格式比照 D:/SSA/20260729期中報告/期中報告-星文整理-0723_修0723R.doc：
  封面（文件編號、Issue/Revision、日期）→ 簽核頁 → Revision/Change Record → 目錄／圖目錄／表目錄
  → 內文；第 2 節起頁首為計畫名＋文件編號＋日期＋「x of N」，頁尾頁碼。
  內文標楷體 12pt、固定行距 20pt、左右對齊、首行縮排兩字；說明框斜體左縮、固定行距 16pt；
  表格表頭 #0072B2 白字粗體、內文列 #D3DFEE、白色格線；表題在表上、圖題在圖下，皆置中。

Markdown 解析沿用 md_to_docx.py（同一套語法子集），本檔只覆寫版面與樣式。

用法：
  python docs/md_to_docx_tasa.py template <期中報告.docx> <輸出範本.docx>      # 由期中報告建立空白範本（一次即可）
  python docs/md_to_docx_tasa.py convert <in.md> <out.docx> <文件編號> <報告名稱> [修訂紀錄說明] [影響章節]
（convert 後請以 docs/export_docx_pdf.py 用 Word 更新目錄／頁碼並匯出 PDF）
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md_to_docx as m  # noqa: E402

DOCS = Path(__file__).resolve().parent
TEMPLATE = DOCS / "tasa_template" / "期末報告Word範本.docx"
BLACK = RGBColor(0, 0, 0)
EA_FONT = "標楷體"
LAT_FONT = "Times New Roman"
HEAD_FILL, BODY_FILL = "0072B2", "D3DFEE"
FIG_STYLE, TAB_STYLE = "圖標題", "表標題"
CAP_RE = re.compile(r"^\*\*\s*(表|圖)\s*[\dA-Za-z一二三四五六七八九十]+[\d\-－.]*[a-z]?[　 \s]")

# 每次轉換時填入
META: dict = {}


# ── 範本建立 ──────────────────────────────────────────────────────────────────
def _field_par(doc_body_par, instr: str):
    """在段落中插入一個 Word 欄位（TOC 等），內容待 Word 更新。"""
    p = doc_body_par
    for kind in ("begin", None, "separate", "end"):
        r = p._p.makeelement(qn("w:r"), {})
        if kind is None:
            it = r.makeelement(qn("w:instrText"), {qn("xml:space"): "preserve"})
            it.text = instr
            r.append(it)
        else:
            r.append(r.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): kind}))
            if kind == "separate":
                t = p._p.makeelement(qn("w:r"), {})
                tt = t.makeelement(qn("w:t"), {})
                tt.text = "（請於 Word 更新功能變數以產生清單）"
                t.append(tt)
                p._p.append(r)
                p._p.append(t)
                continue
        p._p.append(r)


def build_template(src: str, out: str) -> None:
    d = Document(src)
    body = d.element.body
    paras = d.paragraphs
    idx_toc = next(i for i, p in enumerate(paras) if p.text.strip() == "目錄")
    toc_title = paras[idx_toc]
    # 移除「目錄」標題之後的所有內容（保留最後的 sectPr）
    started = False
    for el in list(body):
        if el is toc_title._p:
            started = True
            continue
        if started and el.tag != qn("w:sectPr"):
            body.remove(el)
    # 目錄／圖目錄／表目錄
    def title_like(text):
        p = copy.deepcopy(toc_title._p)
        for t in p.iter(qn("w:t")):
            t.text = ""
        ts = list(p.iter(qn("w:t")))
        if ts:
            ts[0].text = text
        body.insert(len(body) - 1, p)
        return p

    def new_par():
        p = d.add_paragraph()   # add_paragraph 會放在 sectPr 之前
        return p

    _field_par(new_par(), r' TOC \o "1-3" \h \z \u ')
    new_par().add_run().add_break(WD_BREAK.PAGE)
    title_like("圖目錄")
    _field_par(new_par(), f' TOC \\h \\z \\t "{FIG_STYLE},1" ')
    new_par().add_run().add_break(WD_BREAK.PAGE)
    title_like("表目錄")
    _field_par(new_par(), f' TOC \\h \\z \\t "{TAB_STYLE},1" ')
    new_par().add_run().add_break(WD_BREAK.PAGE)
    # 圖題／表題樣式（以 Caption 為基礎；目錄欄位依樣式名收集）
    styles = d.styles
    from docx.enum.style import WD_STYLE_TYPE
    for name in (FIG_STYLE, TAB_STYLE):
        if name in [s.name for s in styles]:
            st = styles[name]
        else:
            st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles["Caption"]
        st.font.size = Pt(11)
        st.font.bold = True
        st.font.color.rgb = BLACK
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        st.paragraph_format.space_before = Pt(6)
        st.paragraph_format.space_after = Pt(4)
        st.paragraph_format.keep_with_next = name == TAB_STYLE
    d.save(out)
    print("template saved", out)


# ── 封面／頁首／變更紀錄 ─────────────────────────────────────────────────────
def _replace_in_par(p, old: str, new: str) -> bool:
    """段落層級取代（文字可能被拆成多個 run）；含功能變數之段落不處理。"""
    if "w:fldChar" in p._p.xml or old not in p.text:
        return False
    runs = p.runs
    full = "".join(r.text for r in runs)
    if old not in full:
        return False
    runs[0].text = full.replace(old, new)
    for r in runs[1:]:
        r.text = ""
    return True


def _all_pars(doc):
    for p in doc.paragraphs:
        yield p
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                yield from c.paragraphs
    for s in doc.sections:
        for hf in (s.header, s.first_page_header, s.footer, s.first_page_footer):
            yield from hf.paragraphs
            for t in hf.tables:
                for row in t.rows:
                    for c in row.cells:
                        yield from c.paragraphs


def fill_front_matter(doc) -> None:
    rep = [("MID-RPT-01", META["docno"]), ("Issue 00 Revision 00", "Issue 00 Revision 01"),
           ("2026/07/28", META["date"]), ("期中進度報告", META["title"]), ("期中報告", META["short"])]
    for p in _all_pars(doc):
        for old, new in rep:
            _replace_in_par(p, old, new)
    # 頁首之文件編號被拆成 MID|-|RPT|-|0|1：以儲存格為單位重組
    for s in doc.sections:
        for t in s.header.tables:
            for row in t.rows:
                for c in row.cells:
                    for p in c.paragraphs:
                        txt = p.text.replace(" ", "")
                        if txt.startswith("MID-RPT") or txt in ("2026/07/28", "0000"):
                            if "w:fldChar" not in p._p.xml and p.runs:
                                p.runs[0].text = (META["docno"] if txt.startswith("MID") else
                                                  "0001" if txt == "0000" else META["date"])
                                for r in p.runs[1:]:
                                    r.text = ""
    # 變更紀錄表：第一張表
    t = doc.tables[0]
    rows = [("0000", "2026/09/09", "New Issue（期末報告初版）", "All."),
            ("0001", META["date"], META.get("rev_note", "增修"), META.get("rev_pages", "—"))]
    first = t.rows[1]
    for c in first.cells:                 # 範本儲存格內有多個空段落撐高列高：只留第一段
        for extra in c.paragraphs[1:]:
            extra._p.getparent().remove(extra._p)
    for k, vals in enumerate(rows):
        row = first if k == 0 else None
        if row is None:
            new_tr = copy.deepcopy(first._tr)
            first._tr.addnext(new_tr)
            row = t.rows[k + 1]
        cols = [0, 1, 3, 4]
        for ci, v in zip(cols, vals):
            cell = row.cells[ci]
            ps = cell.paragraphs
            if ps and ps[0].runs:
                ps[0].runs[0].text = v
                for r in ps[0].runs[1:]:
                    r.text = ""
            else:
                ps[0].add_run(v)
        if k == 1:
            c2 = row.cells[2]
            for r in c2.paragraphs[0].runs:
                r.text = ""


ORG_NAME = "社團法人中華民國國防科技學術研究學會"
SCHOOL_TEXT = (("CHUNG CHENG INSTITUTE OF TECHNOLOGY, NDU", ""), ("國防大學理工學院", ORG_NAME))


def strip_school(doc) -> None:
    """範本沿用期中報告格式，其中簽核頁／變更紀錄頁印有學校中英文名、頁首有院徽圖：
    文字改為學會名稱（英文校名刪除），頁首、頁尾內的圖片一律移除。"""
    for p in _all_pars(doc):
        for old, new in SCHOOL_TEXT:
            _replace_in_par(p, old, new)
    for part in doc.part.package.iter_parts():      # 直接走既有頁首／頁尾 part，不經 section 存取（避免新增空白頁首）
        name = str(part.partname)
        if not re.match(r"/word/(header|footer)\d*\.xml$", name):
            continue
        el = part.element
        for tag in ("w:pict", "w:drawing"):
            for g in list(el.iter(qn(tag))):
                run = g.getparent()
                run.getparent().remove(run) if run.tag == qn("w:r") else run.remove(g)


# ── 樣式覆寫 ─────────────────────────────────────────────────────────────────
def style_run(run, lang, size=12, bold=False, italic=False, code=False, color=BLACK, sub=False, sup=False):
    run.bold, run.italic = bold, italic
    f = run.font
    f.size = Pt(size)
    f.color.rgb = BLACK if color in (m.INK, m.MUTE) else color
    f.subscript, f.superscript = sub, sup
    lat = m.CODE_FONT if code else LAT_FONT
    f.name = lat
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    rf.set(qn("w:eastAsia"), EA_FONT)   # 程式碼字串內之中文亦用標楷體（Consolas 無中文字形，會退回細明體）
    rf.set(qn("w:ascii"), lat)
    rf.set(qn("w:hAnsi"), lat)
    return run


def _exact(pf, pt):
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(pt)


def add_paragraph(doc, lang, space_after=0, space_before=0, indent=None):
    p = doc.add_paragraph(style="Normal")
    pf = p.paragraph_format
    pf.space_after, pf.space_before = Pt(space_after), Pt(space_before)
    _exact(pf, 20)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if indent is not None:
        pf.left_indent = indent
    else:
        pf.first_line_indent = Cm(0.85)      # 首行縮排兩字（12pt）
    return p


_orig_add_inline = m.add_inline


def add_inline(par, text, lang, size=12, bold0=False, color=BLACK):
    # 一般段落中的「**表 N　…**」「**圖 N　…**」→ 表題／圖題樣式
    if par._parent is not None and par.style.name == "Normal" and CAP_RE.match(text) \
            and par.paragraph_format.first_line_indent is not None:
        kind = CAP_RE.match(text).group(1)
        par.style = TAB_STYLE if kind == "表" else FIG_STYLE
        pf = par.paragraph_format
        pf.first_line_indent = None
        pf.line_spacing_rule = None
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        text = text.replace("**", "")
        return _orig_add_inline(par, text, lang, size=11, bold0=True, color=BLACK)
    return _orig_add_inline(par, text, lang, size=size, bold0=bold0, color=color)


_seen_h3 = {"v": False}


def add_heading(doc, lang, level, text):
    # md：# 標題、## 副標（封面已有）→ 略過；### → Heading 1；#### → Heading 2；##### 以下 → Heading 3
    if level <= 1 and not _seen_h3["v"]:
        return None
    _seen_h3["v"] = True
    hl = {2: 1, 3: 2}.get(level, 3) if level >= 2 else 1
    p = doc.add_paragraph(style=f"Heading {hl}")
    ppr = p._p.get_or_add_pPr()
    num = ppr.makeelement(qn("w:numPr"), {})            # 關閉範本 Heading 2 之自動編號
    ilvl = num.makeelement(qn("w:ilvl"), {qn("w:val"): "0"})
    nid = num.makeelement(qn("w:numId"), {qn("w:val"): "0"})
    num.append(ilvl); num.append(nid); ppr.append(num)
    pf = p.paragraph_format
    pf.first_line_indent = Cm(0)
    pf.left_indent = Cm(0)
    pf.space_before = Pt({1: 18, 2: 12, 3: 8}[hl])
    pf.space_after = Pt(6)
    pf.keep_with_next = True
    size = {1: 14, 2: 13, 3: 12}[hl]
    _orig_add_inline(p, text, lang, size=size, bold0=True, color=BLACK)
    for r in p.runs:
        r.bold = True
    return p


_orig_add_table = m.add_table


def _cell_borders_white(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.makeelement(qn("w:tcBorders"), {})
    for side in ("top", "left", "bottom", "right"):
        e = b.makeelement(qn(f"w:{side}"), {qn("w:val"): "single", qn("w:sz"): "8", qn("w:color"): "FFFFFF"})
        b.append(e)
    tcPr.insert(0, b) if len(tcPr) == 0 else tcPr.append(b)


def add_table(doc, rows, lang):
    t = _orig_add_table(doc, rows, lang)
    for ri, row in enumerate(t.rows):
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            for old in tcPr.findall(qn("w:shd")):
                tcPr.remove(old)
            shd = tcPr.makeelement(qn("w:shd"), {qn("w:val"): "clear", qn("w:color"): "auto",
                                                  qn("w:fill"): HEAD_FILL if ri == 0 else BODY_FILL})
            tcPr.append(shd)
            _cell_borders_white(cell)
            for p in cell.paragraphs:
                p.paragraph_format.first_line_indent = None
                p.paragraph_format.line_spacing_rule = None
                p.paragraph_format.line_spacing = 1.0
                for r in p.runs:
                    if ri == 0:
                        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        r.bold = True
    # 表格後留一點間距
    sp = doc.add_paragraph(style="Normal")
    sp.paragraph_format.space_after = Pt(4)
    _exact(sp.paragraph_format, 8)
    return t


def add_image(doc, src, caption, lang):
    path = m.DOCS / src
    if not path.exists() and (Path.cwd() / src).exists():
        path = Path.cwd() / src
    if not path.exists():
        print(f"    [警告] 找不到圖檔，略過: {src}")
        return
    p = doc.add_paragraph(style="Normal")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=m.IMG_W)
    if caption:
        c = doc.add_paragraph(style=FIG_STYLE)
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _orig_add_inline(c, caption, lang, size=11, bold0=True, color=BLACK)


def add_quote(doc, lines, lang):
    p = doc.add_paragraph(style="Normal")
    pf = p.paragraph_format
    pf.left_indent = Cm(0.42)
    pf.space_after = Pt(12)
    _exact(pf, 16)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for i, ln in enumerate(lines):
        if i:
            p.add_run().add_break()
        _orig_add_inline(p, ln, lang, size=11)
    for r in p.runs:
        r.italic = True


def add_hr(doc, lang):
    return None    # 範本不使用水平線；章節以標題區隔


def _template_document(*_a, **_k):
    return Document(str(META["template"]))


def convert(md_path, out_path, docno, title, rev_note="增修", rev_pages="—", template=TEMPLATE, date=None):
    import datetime
    date = date or datetime.date.today().strftime("%Y/%m/%d")     # 封面、頁首、變更紀錄之日期，預設為轉檔當日
    META.update(docno=docno, title=title, short="期末報告", date=date,
                rev_note=rev_note, rev_pages=rev_pages, template=template)
    _seen_h3["v"] = False
    m.BODY_PT = 12
    m.IMG_W = Cm(16.0)
    m.Document = _template_document
    m.style_run = style_run
    m.add_paragraph = add_paragraph
    m.add_inline = add_inline
    m.add_heading = add_heading
    m.add_table = add_table
    m.add_image = add_image
    m.add_quote = add_quote
    m.add_hr = add_hr
    # convert() 內會改 Normal 字型與頁面邊界——改用不會覆寫範本之版本
    stats = _convert_body(md_path, out_path)
    return stats


def _convert_body(md_path, out_path):
    """呼叫 md_to_docx.convert，但避免其覆寫範本之頁面與 Normal 樣式。"""
    src = Path(m.__file__).read_text(encoding="utf-8")
    start = src.index("def convert(")
    end = src.index("def main(")
    code = src[start:end]
    code = re.sub(r"    sec = doc\.sections\[0\].*?stats = dict", "    stats = dict", code, flags=re.S)
    ns = dict(vars(m))
    exec(code, ns)   # 以 md_to_docx 之命名空間（已覆寫上列函式）定義 convert
    doc_holder = {}
    orig_doc = ns["Document"]

    def _doc(*a, **k):
        d = orig_doc()
        doc_holder["d"] = d
        return d
    ns["Document"] = _doc
    stats = ns["convert"](md_path, out_path, "zh")
    d = Document(str(out_path))
    fill_front_matter(d)
    strip_school(d)
    _drop_empty_lists(d)
    unify_cjk_font(d)
    d.save(str(out_path))
    return stats


_CJK_OTHER = {"BiauKai", "新細明體", "PMingLiU", "細明體", "MingLiU", "微軟正黑體", "Microsoft JhengHei", "Yu Mincho",
              "MS Mincho", "MS Gothic", "Consolas"}


def unify_cjk_font(doc) -> None:
    """全冊中文字形統一為標楷體：內文、表格、頁首頁尾、樣式、文件預設與佈景主題字型。
    （Word 更新目錄時之 TOC 樣式取佈景主題之東亞字型＝新細明體，會造成標楷體與細明體夾雜。）"""
    def fix(root):
        for rf in root.iter(qn("w:rFonts")):
            for att in ("w:eastAsiaTheme",):
                if rf.get(qn(att)) is not None:
                    del rf.attrib[qn(att)]
                    rf.set(qn("w:eastAsia"), EA_FONT)
            if rf.get(qn("w:eastAsia")) in _CJK_OTHER:
                rf.set(qn("w:eastAsia"), EA_FONT)
            for att in ("w:ascii", "w:hAnsi"):          # Mac 字型名 BiauKai 在 Windows 不存在，會退回細明體
                if rf.get(qn(att)) in ("BiauKai", EA_FONT, "Calibri"):
                    rf.set(qn(att), LAT_FONT)
    fix(doc.element.body)
    fix(doc.styles.element)
    for sec in doc.sections:
        for hf in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            fix(hf._element)
    st = doc.styles.element
    dd = st.find(qn("w:docDefaults"))
    if dd is None:
        dd = st.makeelement(qn("w:docDefaults"), {}); st.insert(0, dd)
    rpd = dd.find(qn("w:rPrDefault"))
    if rpd is None:
        rpd = dd.makeelement(qn("w:rPrDefault"), {}); dd.insert(0, rpd)
    rpr = rpd.find(qn("w:rPr"))
    if rpr is None:
        rpr = rpd.makeelement(qn("w:rPr"), {}); rpd.append(rpr)
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {}); rpr.insert(0, rf)
    for att in list(rf.attrib):
        if att.endswith("Theme"):
            del rf.attrib[att]
    rf.set(qn("w:eastAsia"), EA_FONT); rf.set(qn("w:ascii"), LAT_FONT); rf.set(qn("w:hAnsi"), LAT_FONT)
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/theme"):
            part = rel.target_part
            part._blob = part.blob.replace("新細明體".encode("utf-8"), EA_FONT.encode("utf-8"))                                   .replace(b'typeface="PMingLiU"', f'typeface="{EA_FONT}"'.encode("utf-8"))                                   .replace(b'<a:latin typeface="Calibri Light"', f'<a:latin typeface="{LAT_FONT}"'.encode())                                   .replace(b'<a:latin typeface="Calibri"', f'<a:latin typeface="{LAT_FONT}"'.encode())                                   .replace(b'<a:latin typeface="Cambria"', f'<a:latin typeface="{LAT_FONT}"'.encode())


def _drop_empty_lists(doc) -> None:
    """本冊若無圖題／表題，移除對應之「圖目錄／表目錄」標題、TOC 欄位與分頁段落。"""
    used = {p.style.name for p in doc.paragraphs}
    pars = doc.paragraphs
    for name, title in ((FIG_STYLE, "圖目錄"), (TAB_STYLE, "表目錄")):
        if name in used:
            continue
        for i, p in enumerate(pars):
            if f'"{name},1"' in p._p.xml and "instrText" in p._p.xml:
                drop = [p]
                if i > 0 and pars[i - 1].text.strip() == title:
                    drop.append(pars[i - 1])
                if i + 1 < len(pars) and "w:br" in pars[i + 1]._p.xml and not pars[i + 1].text.strip():
                    drop.append(pars[i + 1])
                for q in drop:
                    q._p.getparent().remove(q._p)
                break
        pars = doc.paragraphs


if __name__ == "__main__":
    if sys.argv[1] == "template":
        build_template(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "convert":
        a = sys.argv[2:]
        convert(a[0], a[1], a[2], a[3], *(a[4:6]))
    else:
        print(__doc__)
