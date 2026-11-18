#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md_to_docx.py — 將本專案之 Markdown 論文轉為 Word (.docx)。

本機無 pandoc／LibreOffice，故以 python-docx 自行轉換。支援論文實際用到的
Markdown 子集：標題、段落（粗體／斜體／行內碼／連結）、表格（含對齊）、圖片
（alt 轉圖說）、區塊公式、行內公式、引用區塊、清單、水平線。

公式處理：
  · 區塊公式 $$...$$ → 以 matplotlib mathtext 渲染為 PNG 置中插入，\\tag{n}
    抽出為右側式號。
  · 行內公式 $...$ → 優先以「多個 run + 斜體 + 上下標」原生排版；僅在含
    \\frac／\\sqrt／\\tfrac 等無法以 run 表達者才退回小圖片。

用法：
    python docs/md_to_docx.py                 # 轉換中英兩篇論文
    python docs/md_to_docx.py <in.md> <out.docx> [zh|en]
"""
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

DOCS = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="md2docx_"))

BODY_PT = 10.5
CODE_FONT = "Consolas"
INK = RGBColor(0x22, 0x22, 0x2A)
MUTE = RGBColor(0x60, 0x60, 0x6A)
IMG_W = Cm(15.6)          # A4 21cm - 左右邊距各 2.7cm

# LaTeX 命令 -> Unicode（行內公式原生排版用）
UNI = {
    r"\sigma": "σ", r"\mu": "μ", r"\Delta": "Δ", r"\delta": "δ", r"\Phi": "Φ",
    r"\phi": "φ", r"\alpha": "α", r"\beta": "β", r"\rho": "ρ", r"\theta": "θ",
    r"\lambda": "λ", r"\omega": "ω", r"\pi": "π", r"\tau": "τ", r"\epsilon": "ε",
    r"\approx": " ≈ ", r"\le": " ≤ ", r"\leq": " ≤ ", r"\ge": " ≥ ",
    r"\geq": " ≥ ", r"\ne": " ≠ ", r"\neq": " ≠ ", r"\times": "×",
    r"\cdot": "·", r"\pm": "±", r"\to": "→", r"\infty": "∞", r"\max": "max",
    r"\min": "min", r"\log": "log", r"\exp": "exp", r"\ln": "ln",
    r"\,": " ", r"\;": " ", r"\ ": " ", r"\!": "", r"\%": "%",
}
NEEDS_IMAGE = ("\\frac", "\\sqrt", "\\tfrac", "\\dfrac", "\\sum", "\\int", "\\big")


# --------------------------------------------------------------------------
# 公式渲染
# --------------------------------------------------------------------------
def tex_to_mathtext(tex):
    """論文 LaTeX -> matplotlib mathtext 子集；回傳 (公式, 式號)。"""
    tag = None
    m = re.search(r"\\tag\{([^}]*)\}", tex)
    if m:
        tag = m.group(1)
        tex = tex[:m.start()] + tex[m.end():]
    tex = tex.strip()
    tex = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", tex)
    # \mathrm d（無大括號）-> \mathrm{d}；mathtext 不接受省略大括號之寫法
    tex = re.sub(r"\\(mathrm|mathbf|mathit)\s+([A-Za-z])", r"\\\1{\2}", tex)
    tex = re.sub(r"\\t?frac", r"\\frac", tex)
    tex = re.sub(r"\\bigg?[lr]?", "", tex)          # mathtext 無 \big 系列
    for a, b in ((r"\le ", r"\leq "), (r"\ge ", r"\geq "),
                 (r"\le}", r"\leq}"), (r"\ne ", r"\neq ")):
        tex = tex.replace(a, b)
    tex = tex.replace("\\,", r"\ ").replace("\\;", r"\ ").replace("\\!", "")
    tex = re.sub(r"\\[lr]vert\b", "|", tex)          # mathtext 無 \lvert／\rvert
    tex = re.sub(r"\\sqrt\s*([0-9A-Za-z])", r"\\sqrt{\1}", tex)   # \sqrt2 → \sqrt{2}
    return tex, tag


_eq_n = [0]


def render_equation(tex, fontsize=17):
    """把 LaTeX 渲染為 PNG，回傳 (路徑, 式號, 寬高比) 或 None。"""
    mt, tag = tex_to_mathtext(tex)
    _eq_n[0] += 1
    out = TMP / f"eq_{_eq_n[0]:03d}.png"
    try:
        fig = plt.figure(figsize=(0.1, 0.1))
        fig.text(0, 0, f"${mt}$", fontsize=fontsize, color="#22222a")
        fig.savefig(out, dpi=220, bbox_inches="tight", pad_inches=0.05,
                    facecolor="white")
        plt.close(fig)
    except Exception as e:
        print(f"    [警告] 公式渲染失敗，改以原文呈現: {e.__class__.__name__}: {mt[:60]}")
        return None
    from PIL import Image
    with Image.open(out) as im:
        w, h = im.size
    return out, tag, w / h


# --------------------------------------------------------------------------
# 字型
# --------------------------------------------------------------------------
def style_run(run, lang, size=BODY_PT, bold=False, italic=False, code=False,
              color=INK, sub=False, sup=False):
    run.bold = bold
    run.italic = italic
    f = run.font
    f.size = Pt(size)
    f.color.rgb = color
    f.subscript = sub
    f.superscript = sup
    f.name = CODE_FONT if code else "Times New Roman"
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    ea = CODE_FONT if code else ("Microsoft JhengHei" if lang == "zh" else "Times New Roman")
    rf.set(qn("w:eastAsia"), ea)
    rf.set(qn("w:ascii"), CODE_FONT if code else "Times New Roman")
    rf.set(qn("w:hAnsi"), CODE_FONT if code else "Times New Roman")
    return run


# --------------------------------------------------------------------------
# 行內公式 -> runs
# --------------------------------------------------------------------------
def inline_math_runs(par, tex, lang, size=BODY_PT, color=INK):
    """把行內公式排成 run；無法原生表達者回傳 False（呼叫端改用圖片）。"""
    if any(k in tex for k in NEEDS_IMAGE):
        return False
    s = tex
    for k in sorted(UNI, key=len, reverse=True):
        s = s.replace(k, UNI[k])
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^}]*)\}", r"\1", s)
    if "\\" in s:                      # 仍有未知命令
        return False
    # 依 _{..} ^{..} _x ^x 切段
    tokens, i = [], 0
    while i < len(s):
        c = s[i]
        if c in "_^" and i + 1 < len(s):
            kind = "sub" if c == "_" else "sup"
            if s[i + 1] == "{":
                j = s.index("}", i + 2)
                tokens.append((kind, s[i + 2:j]))
                i = j + 1
            else:
                tokens.append((kind, s[i + 1]))
                i += 2
        else:
            if tokens and tokens[-1][0] == "txt":
                tokens[-1] = ("txt", tokens[-1][1] + c)
            else:
                tokens.append(("txt", c))
            i += 1
    for kind, txt in tokens:
        if not txt:
            continue
        ital = bool(re.fullmatch(r"[A-Za-z]+", txt)) and txt not in ("max", "min", "log", "ln", "exp")
        style_run(par.add_run(txt), lang, size=size, italic=ital, color=color,
                  sub=(kind == "sub"), sup=(kind == "sup"))
    return True


# --------------------------------------------------------------------------
# 行內語法 -> runs
# --------------------------------------------------------------------------
# 單星斜體只要求「星號內側非空白」（如 |Δ*a*| 中的 *a*，其左側是文字而非空白，
# 舊的 (?<![\w*]) 寫法會漏判）。**粗體** 由前一個分支先行匹配，故不衝突。
TOKEN_RE = re.compile(
    r"(\*\*\*.+?\*\*\*|\*\*.+?\*\*|\*(?!\s)[^*\n]+?(?<!\s)\*|`[^`]+`|"
    r"\[[^\]]*\]\([^)]*\)|\$[^$\n]+?\$)", re.S)


MD_ESC = re.compile(r"\\([\\`*_{}\[\]()#+.!|>~-])")


def unesc(s):
    """還原 Markdown 跳脫序列（如 B\\* -> B*）。"""
    return MD_ESC.sub(r"\1", s)


def add_inline(par, text, lang, size=BODY_PT, bold0=False, color=INK):
    """把一段含 Markdown 行內語法之文字加入段落。"""
    for part in TOKEN_RE.split(text):
        if not part:
            continue
        if part.startswith("***") and part.endswith("***"):
            style_run(par.add_run(unesc(part[3:-3])), lang, size, bold=True, italic=True, color=color)
        elif part.startswith("**") and part.endswith("**"):
            style_run(par.add_run(unesc(part[2:-2])), lang, size, bold=True, color=color)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            style_run(par.add_run(unesc(part[1:-1])), lang, size, bold=bold0, italic=True, color=color)
        elif part.startswith("`") and part.endswith("`"):
            style_run(par.add_run(part[1:-1]), lang, size - 0.5, bold=bold0, code=True, color=color)
        elif part.startswith("[") and "](" in part:
            m = re.match(r"\[([^\]]*)\]\(([^)]*)\)", part)
            style_run(par.add_run(unesc(m.group(1))), lang, size, bold=bold0, color=color)
        elif part.startswith("$") and part.endswith("$") and len(part) > 2:
            if not inline_math_runs(par, part[1:-1], lang, size, color):
                r = render_equation(part[1:-1], fontsize=13)
                if r:
                    path, _tag, ratio = r
                    h = Pt(size * 1.45)
                    par.add_run().add_picture(str(path), height=h)
                else:
                    style_run(par.add_run(part[1:-1]), lang, size, italic=True, color=color)
        else:
            style_run(par.add_run(unesc(part)), lang, size, bold=bold0, color=color)


# --------------------------------------------------------------------------
# 區塊處理
# --------------------------------------------------------------------------
def add_paragraph(doc, lang, space_after=6, space_before=0, indent=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing = 1.18
    if indent is not None:
        pf.left_indent = indent
    return p


def add_heading(doc, lang, level, text):
    p = doc.add_heading(level=level)
    p.paragraph_format.space_before = Pt(14 if level <= 2 else 10)
    p.paragraph_format.space_after = Pt(6)
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    size = {0: 17, 1: 14.5, 2: 12.5, 3: 11.5}.get(level, 11)
    add_inline(p, text, lang, size=size, bold0=True, color=INK)
    for r in p.runs:
        r.bold = True
        r.font.color.rgb = INK
        rf = r._element.get_or_add_rPr().find(qn("w:rFonts"))
        if rf is not None and lang == "zh":
            rf.set(qn("w:eastAsia"), "Microsoft JhengHei")
    if level == 0:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p


def add_table(doc, rows, lang):
    """rows: list of list[str]；第 1 列為表頭，第 2 列為對齊定義。"""
    header, align_row, body = rows[0], rows[1], rows[2:]
    aligns = []
    for a in align_row:
        a = a.strip()
        if a.startswith(":") and a.endswith(":"):
            aligns.append(WD_ALIGN_PARAGRAPH.CENTER)
        elif a.endswith(":"):
            aligns.append(WD_ALIGN_PARAGRAPH.RIGHT)
        else:
            aligns.append(WD_ALIGN_PARAGRAPH.LEFT)
    ncol = len(header)
    aligns += [WD_ALIGN_PARAGRAPH.LEFT] * (ncol - len(aligns))

    t = doc.add_table(rows=1 + len(body), cols=ncol)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 依內容實際字寬估算欄寬（中日韓字元計 2 個字元當量），避免 autofit 把
    # 名稱或數值擠到斷行；空間不足時自動縮小表格字型而非壓爛欄位。
    def vis_len(s):
        s = re.sub(r"[*`]|\[([^\]]*)\]\([^)]*\)", r"\1", s)
        return sum(2 if ord(c) > 0x2E80 else 1 for c in s)

    demand = []
    for j in range(ncol):
        cells = [vis_len(r[j].strip()) for r in body if j < len(r)]
        head = vis_len(header[j].strip()) * 1.18      # 表頭為粗體，略寬
        demand.append(min(max([head] + cells or [1]), 40))

    CELL_PAD = 0.30                      # 左右內距合計 (cm)
    fsize = 9.5
    while fsize > 7.4:
        per = fsize * 0.0177             # Times New Roman 每字元當量寬 (cm)
        need = [d * per + CELL_PAD for d in demand]
        if sum(need) <= IMG_W.cm:
            break
        fsize -= 0.5
    per = fsize * 0.0177
    need = [d * per + CELL_PAD for d in demand]
    scale = IMG_W.cm / sum(need)
    widths = [Cm(w * scale) for w in need]

    t.autofit = False
    # 縮小儲存格內距，把寬度讓給內容
    mar = t._tbl.tblPr.makeelement(qn("w:tblCellMar"), {})
    for side, val in (("left", "72"), ("right", "72")):   # 72 dxa = 0.127 cm
        e = mar.makeelement(qn(f"w:{side}"), {})
        e.set(qn("w:w"), val)
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    t._tbl.tblPr.append(mar)
    tblPr = t._tbl.tblPr
    layout = tblPr.makeelement(qn("w:tblLayout"), {})
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    for j, w in enumerate(widths):
        for row in t.rows:
            row.cells[j].width = w
    for j, cell_txt in enumerate(header):
        cell = t.cell(0, j)
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        add_inline(p, cell_txt.strip(), lang, size=fsize, bold0=True)
        for r in p.runs:
            r.bold = True
        shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "EDEDF2")
        cell._tc.get_or_add_tcPr().append(shd)
    for i, row in enumerate(body, start=1):
        for j in range(ncol):
            cell = t.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = aligns[j]
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, row[j].strip() if j < len(row) else "", lang, size=fsize)
    return t


def add_image(doc, src, caption, lang):
    path = DOCS / src
    if not path.exists() and (Path.cwd() / src).exists():
        path = Path.cwd() / src          # 子資料夾內之 md：圖檔相對於執行目錄
    if not path.exists():
        print(f"    [警告] 找不到圖檔，略過: {src}")
        return
    p = add_paragraph(doc, lang, space_after=2, space_before=8)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=IMG_W)
    if caption:
        c = add_paragraph(doc, lang, space_after=10)
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(c, caption, lang, size=9, color=MUTE)


def add_block_equation(doc, tex, lang):
    r = render_equation(tex)
    p = add_paragraph(doc, lang, space_after=8, space_before=8)
    if not r:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(p, tex, lang, size=BODY_PT)
        return
    path, tag, ratio = r
    height = Cm(0.62) if ratio > 6 else Cm(0.95)
    if tag:
        # \u5b78\u8853\u6163\u4f8b\uff1a\u516c\u5f0f\u7f6e\u4e2d\u3001\u5f0f\u865f\u9760\u53f3 \u2014\u2014 \u4ee5\u7f6e\u4e2d\uff0f\u9760\u53f3\u5169\u500b\u5b9a\u4f4d\u9ede\u9054\u6210
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        ts = p.paragraph_format.tab_stops
        ts.add_tab_stop(Cm(IMG_W.cm / 2), WD_TAB_ALIGNMENT.CENTER)
        ts.add_tab_stop(IMG_W, WD_TAB_ALIGNMENT.RIGHT)
        p.add_run("\t").add_picture(str(path), height=height)
        style_run(p.add_run(f"\t({tag})"), lang, size=BODY_PT, color=INK)
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(path), height=height)


def add_quote(doc, lines, lang):
    p = add_paragraph(doc, lang, space_after=8, space_before=6, indent=Cm(0.6))
    p.paragraph_format.right_indent = Cm(0.4)
    for i, ln in enumerate(lines):
        if i:
            p.add_run().add_break()
        add_inline(p, ln, lang, size=9.5, color=MUTE)
    pbdr = p._p.get_or_add_pPr().makeelement(qn("w:pBdr"), {})
    left = pbdr.makeelement(qn("w:left"), {})
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "12")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), "B8B8C4")
    pbdr.append(left)
    p._p.get_or_add_pPr().append(pbdr)


def add_hr(doc, lang):
    p = add_paragraph(doc, lang, space_after=8, space_before=8)
    pbdr = p._p.get_or_add_pPr().makeelement(qn("w:pBdr"), {})
    bot = pbdr.makeelement(qn("w:bottom"), {})
    bot.set(qn("w:val"), "single")
    bot.set(qn("w:sz"), "6")
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), "C9C9D1")
    pbdr.append(bot)
    p._p.get_or_add_pPr().append(pbdr)


# --------------------------------------------------------------------------
# 主轉換
# --------------------------------------------------------------------------
def add_code_block(doc, code_lines, lang):
    """程式碼區塊（``` 圍欄）：等寬字型、淺灰底、保留行首空白，整段一個段落以換行分隔。"""
    from docx.oxml import OxmlElement
    par = doc.add_paragraph()
    pf = par.paragraph_format
    pf.left_indent = Cm(0.4)
    pf.space_before = Pt(3)
    pf.space_after = Pt(6)
    pf.line_spacing = 1.0
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F2F2")
    par._p.get_or_add_pPr().append(shd)
    for k, line in enumerate(code_lines):
        run = par.add_run(line.replace("	", "    "))
        style_run(run, lang, 8.5, code=True)
        if k < len(code_lines) - 1:
            run.add_break()
    return par


def convert(md_path, out_path, lang):
    md_path, out_path = Path(md_path), Path(out_path)
    text = md_path.read_text(encoding="utf-8")
    lines = text.replace("\r\n", "\n").split("\n")

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(BODY_PT)
    normal.element.rPr.rFonts.set(
        qn("w:eastAsia"), "Microsoft JhengHei" if lang == "zh" else "Times New Roman")

    stats = dict(heading=0, para=0, table=0, image=0, equation=0, quote=0, list=0)
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if not s:
            i += 1
            continue

        # 程式碼區塊（``` 圍欄，可縮排於清單內）
        if s.startswith("```"):
            ind = len(ln) - len(ln.lstrip())
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                raw = lines[i]
                buf.append(raw[ind:] if raw[:ind].strip() == "" else raw)
                i += 1
            add_code_block(doc, buf, lang)
            stats["para"] += 1
            i += 1
            continue

        # 區塊公式（可跨行）
        if s.startswith("$$"):
            buf = s
            while buf.count("$$") < 2 and i + 1 < n:
                i += 1
                buf += "\n" + lines[i].strip()
            tex = buf.strip()[2:-2] if buf.strip().endswith("$$") else buf.strip()[2:]
            add_block_equation(doc, tex, lang)
            stats["equation"] += 1
            i += 1
            continue

        # 圖片（獨立成行）
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            add_image(doc, m.group(2), m.group(1), lang)
            stats["image"] += 1
            i += 1
            continue

        # 標題
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            add_heading(doc, lang, min(len(m.group(1)) - 1, 4), m.group(2).strip())
            stats["heading"] += 1
            i += 1
            continue

        # 水平線
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            add_hr(doc, lang)
            i += 1
            continue

        # 表格
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                # 只在未跳脫的 | 切欄；儲存格內的 \| 還原為 |（如 |Δa|、mean|Δp|）
                row = lines[i].strip()
                row = row[1:] if row.startswith("|") else row
                row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
                cells = [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]
                rows.append(cells)
                i += 1
            if len(rows) >= 2:
                add_table(doc, rows, lang)
                stats["table"] += 1
            continue

        # 引用區塊
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            add_quote(doc, [b for b in buf if b.strip()], lang)
            stats["quote"] += 1
            continue

        # 清單
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
        if m:
            depth = len(m.group(1)) // 2
            ordered = m.group(2)[0].isdigit()
            p = add_paragraph(doc, lang, space_after=3,
                              indent=Cm(0.75 + 0.6 * depth))
            p.paragraph_format.first_line_indent = Cm(-0.55)
            bullet = f"{m.group(2)} " if ordered else "\u2022  "
            style_run(p.add_run(bullet), lang, size=BODY_PT)
            add_inline(p, m.group(3), lang)
            stats["list"] += 1
            i += 1
            continue

        # 一般段落
        p = add_paragraph(doc, lang)
        add_inline(p, s, lang)
        stats["para"] += 1
        i += 1

    doc.save(out_path)
    kb = out_path.stat().st_size // 1024
    print(f"  已輸出 {out_path.name}  ({kb} KB)")
    print("   ", "  ".join(f"{k}={v}" for k, v in stats.items()))
    return stats


def main():
    if len(sys.argv) >= 3:
        convert(sys.argv[1], sys.argv[2],
                sys.argv[3] if len(sys.argv) > 3 else "zh")
        return
    for md, lang in (("paper_tle_sma_noise_floor.md", "zh"),
                     ("paper_tle_sma_noise_floor_EN.md", "en")):
        src = DOCS / md
        print(f"[{lang}] {md}")
        convert(src, src.with_suffix(".docx"), lang)


if __name__ == "__main__":
    main()
