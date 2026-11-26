"""
generate_doc.py
===============
將 sat_profiles/*.md 彙整成一份具備索引的 Word (.docx) 文件。

文件結構
  封面         ── 標題、日期、衛星總數
  系列索引表   ── 仿 home.html 的群組統計（可點超連結跳至對應章節）
  各章          ── 每個群組 = Heading 1
                   群組衛星一覽表（NORAD / 名稱 / COSPAR / 發射日期 / 軌道）
                   每顆有 profile 的衛星 = Heading 2 + 基本資訊表 + 文字段落

使用方式
  python generate_doc.py [--profiles DIR] [--groups DIR] [--out PATH]
"""

import argparse
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.table import WD_TABLE_ALIGNMENT


# ── 路徑預設 ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROFILES_DIR = SCRIPT_DIR / "sat_profiles"
GROUPS_DIR   = SCRIPT_DIR / "chm_build" / "_groups"
HOME_HTML    = SCRIPT_DIR / "chm_build" / "home.html"
OUTPUT_PATH  = SCRIPT_DIR / f"PRC_Satellite_Database_{date.today():%Y%m%d}.docx"


# ── 顏色 ─────────────────────────────────────────────────────────────────────
HEADING1_COLOR = RGBColor(0x1F, 0x49, 0x7D)   # 深藍
HEADING2_COLOR = RGBColor(0x37, 0x63, 0x94)   # 中藍
TABLE_HEADER   = RGBColor(0x1F, 0x49, 0x7D)   # 深藍（表頭背景）


# ════════════════════════════════════════════════════════════════════════════
# HTML 解析
# ════════════════════════════════════════════════════════════════════════════

class _HomeParser(HTMLParser):
    """解析 home.html，取得有序群組清單 [(name_zh, html_file, count)]"""
    def __init__(self):
        super().__init__()
        self._in_tbody = False
        self._in_td    = False
        self._in_a     = False
        self._cur_href = ""
        self._buf      = ""
        self._td_idx   = 0
        self._row      = {}
        self.groups    = []   # [(label, href, count)]

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "tbody": self._in_tbody = True
        if not self._in_tbody: return
        if tag == "tr":
            self._row  = {}
            self._td_idx = 0
        if tag == "td":
            self._in_td = True
            self._buf   = ""
            self._td_idx += 1
        if tag == "a" and self._in_td:
            self._in_a    = True
            self._cur_href = d.get("href", "")

    def handle_endtag(self, tag):
        if tag == "tbody": self._in_tbody = False
        if tag == "a":     self._in_a = False
        if tag == "td":
            self._in_td = False
            text = self._buf.strip()
            if self._td_idx == 1:
                self._row["label"] = text
                self._row["href"]  = self._cur_href
            elif self._td_idx == 2:
                self._row["count"] = int(text) if text.isdigit() else 0
        if tag == "tr" and "label" in self._row:
            href = self._row.get("href","")
            # 只保留有 href（即系列統計表列）的列，排除使用說明表列
            if href:
                fname = Path(href).name
                self.groups.append((self._row["label"], fname, self._row.get("count",0)))
            self._row = {}

    def handle_data(self, data):
        if self._in_td:
            self._buf += data


class _GroupParser(HTMLParser):
    """解析 _groups/*.html，取得該群組的衛星列表 [{norad, name, cospar, launch, orbit}]"""
    def __init__(self):
        super().__init__()
        self._in_tbody = False
        self._in_td    = False
        self._buf      = ""
        self._td_idx   = 0
        self._row      = {}
        self.satellites = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody": self._in_tbody = True
        if not self._in_tbody: return
        if tag == "tr":
            self._row    = {}
            self._td_idx = 0
        if tag == "td":
            self._in_td  = True
            self._buf    = ""
            self._td_idx += 1

    def handle_endtag(self, tag):
        if tag == "tbody": self._in_tbody = False
        if tag == "td":
            self._in_td = False
            text = self._buf.strip()
            if   self._td_idx == 1: self._row["norad"]  = text
            elif self._td_idx == 2: self._row["name"]   = text
            elif self._td_idx == 3: self._row["cospar"] = text
            elif self._td_idx == 4: self._row["launch"] = text
            elif self._td_idx == 5: self._row["orbit"]  = text
        if tag == "tr" and "norad" in self._row:
            self.satellites.append(dict(self._row))
            self._row = {}

    def handle_data(self, data):
        if self._in_td:
            self._buf += data


def load_home_groups(html_path: Path):
    p = _HomeParser()
    p.feed(html_path.read_text(encoding="utf-8"))
    return p.groups   # [(label, fname, count)]


def load_group_sats(html_path: Path):
    if not html_path.exists():
        return []
    p = _GroupParser()
    p.feed(html_path.read_text(encoding="utf-8"))
    return p.satellites   # [{norad, name, cospar, launch, orbit}]


# ════════════════════════════════════════════════════════════════════════════
# Markdown 解析（輕量，僅支援本專案實際用到的語法）
# ════════════════════════════════════════════════════════════════════════════

def parse_md(text: str):
    """
    回傳 list of (kind, payload)：
      ('h1', str), ('h2', str), ('h3', str),
      ('table', [[cell...]]),
      ('para', str),   # 可能含 **bold** 與 `code`
      ('li', str),
      ('blank',)
    """
    blocks = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            blocks.append(("blank",))
            continue
        m_h = re.match(r"^(#{1,3})\s+(.*)", line)
        if m_h:
            level = len(m_h.group(1))
            blocks.append((f"h{level}", m_h.group(2).strip()))
            continue
        if re.match(r"^\|[-| :]+\|", line):      # 分隔列
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            blocks.append(("table_row", cells))
            continue
        if re.match(r"^[-*+]\s", line):
            blocks.append(("li", line[2:].strip()))
            continue
        blocks.append(("para", line))

    # 把相鄰 table_row 合並成 table
    merged = []
    i = 0
    while i < len(blocks):
        if blocks[i][0] == "table_row":
            rows = [blocks[i][1]]
            while i+1 < len(blocks) and blocks[i+1][0] == "table_row":
                i += 1
                rows.append(blocks[i][1])
            merged.append(("table", rows))
        else:
            merged.append(blocks[i])
        i += 1
    return merged


def _inline_runs(para_obj, text: str):
    """把含 **bold**、`code`、plain 的文字分段加到 paragraph。"""
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
    parts = pattern.split(text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = para_obj.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = para_obj.add_run(part[1:-1])
            run.font.name = "Courier New"
            run.font.size = Pt(9)
        else:
            para_obj.add_run(part)


# ════════════════════════════════════════════════════════════════════════════
# Word 輔助工具
# ════════════════════════════════════════════════════════════════════════════

def _set_cell_bg(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def add_heading1(doc: Document, text: str, bookmark: str | None = None):
    h = doc.add_heading(text, level=1)
    h.runs[0].font.color.rgb = HEADING1_COLOR
    if bookmark:
        _add_bookmark(h, bookmark)
    return h


def add_heading2(doc: Document, text: str):
    h = doc.add_heading(text, level=2)
    h.runs[0].font.color.rgb = HEADING2_COLOR
    return h


def _add_bookmark(para, name: str):
    tag   = para._p
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"),   str(abs(hash(name)) % 100000))
    start.set(qn("w:name"), name)
    end   = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"),   str(abs(hash(name)) % 100000))
    tag.insert(0, start)
    tag.append(end)


def add_info_table(doc: Document, rows: list[list[str]]):
    """將 markdown 表格（rows = [[cell...]]）加入文件。"""
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    tbl   = doc.add_table(rows=len(rows), cols=ncols)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    for ri, row in enumerate(rows):
        for ci, cell_text in enumerate(row):
            if ci >= ncols: break
            cell = tbl.cell(ri, ci)
            cell.text = ""
            p = cell.paragraphs[0]
            p.clear()
            _inline_runs(p, cell_text)
            p.runs and setattr(p.runs[0].font, "size", Pt(9))
            if ri == 0:
                _set_cell_bg(cell, "1F497D")
                for run in p.runs:
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.bold = True
    tbl.columns[0].width = Cm(3.5)


def add_group_summary_table(doc: Document, sats: list[dict]):
    """群組衛星一覽表（有標頭列）。"""
    headers = ["NORAD", "衛星名稱", "COSPAR ID", "發射日期", "軌道"]
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr_cells = tbl.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = ""
        p = hdr_cells[i].paragraphs[0]
        run = p.add_run(h)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.size = Pt(9)
        _set_cell_bg(hdr_cells[i], "1F497D")
    for sat in sats:
        row = tbl.add_row().cells
        vals = [sat.get("norad",""), sat.get("name",""),
                sat.get("cospar",""), sat.get("launch",""), sat.get("orbit","")]
        for i, v in enumerate(vals):
            row[i].text = ""
            p = row[i].paragraphs[0]
            p.add_run(v).font.size = Pt(8.5)
    tbl.columns[0].width = Cm(1.8)
    tbl.columns[2].width = Cm(2.5)


def add_profile_blocks(doc: Document, blocks: list):
    """把 parse_md 的輸出加進文件（跳過第一個 h1 標題，已由 heading2 處理）。"""
    skip_first_h1 = True
    prev_kind = None
    for kind, *payload in blocks:
        if kind == "blank":
            prev_kind = kind
            continue
        if kind == "h1":
            if skip_first_h1:
                skip_first_h1 = False
                continue
            add_heading2(doc, payload[0])
        elif kind == "h2":
            h = doc.add_heading(payload[0], level=3)
        elif kind == "h3":
            h = doc.add_heading(payload[0], level=4)
        elif kind == "table":
            rows = payload[0]
            add_info_table(doc, rows)
        elif kind == "para":
            text = payload[0]
            if not text:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after  = Pt(2)
            _inline_runs(p, text)
        elif kind == "li":
            p = doc.add_paragraph(style="List Bullet")
            _inline_runs(p, payload[0])
        prev_kind = kind


# ════════════════════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════════════════════

def build_norad_to_md(profiles_dir: Path) -> dict[str, Path]:
    """NORAD ID（字串）→ .md 路徑"""
    mapping = {}
    for f in profiles_dir.glob("*.md"):
        m = re.match(r"^(\d+)_", f.name)
        if m:
            mapping[m.group(1)] = f
    return mapping


def generate(profiles_dir: Path, groups_dir: Path, home_html: Path, out_path: Path):
    print("讀取群組結構 …")
    groups       = load_home_groups(home_html)
    norad_to_md  = build_norad_to_md(profiles_dir)
    total_sats   = sum(c for _, _, c in groups)
    total_profiles = len(norad_to_md)

    print(f"  群組：{len(groups)} 個 | 群組衛星總數：{total_sats} | 有 profile：{total_profiles}")

    doc = Document()

    # ── 頁邊距 ────────────────────────────────────────────────────────────────
    for sect in doc.sections:
        sect.top_margin    = Cm(2.0)
        sect.bottom_margin = Cm(2.0)
        sect.left_margin   = Cm(2.5)
        sect.right_margin  = Cm(2.5)

    # ── 封面 ──────────────────────────────────────────────────────────────────
    cover_title = doc.add_paragraph()
    cover_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cover_title.add_run("PRC 衛星資料庫")
    run.font.size  = Pt(28)
    run.font.bold  = True
    run.font.color.rgb = HEADING1_COLOR

    doc.add_paragraph()  # 空行

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(
        f"收錄 {total_sats} 顆中國衛星的軌道資料、任務背景與機動行為分析\n"
        f"資料來源：N2YO、COSPAR、PRC 機動偵測 CSV（maneuver score）\n"
        f"生成日期：{date.today():%Y-%m-%d}　｜　包含完整 Profile：{total_profiles} 顆"
    ).font.size = Pt(11)

    doc.add_page_break()

    # ── 系列索引表 ────────────────────────────────────────────────────────────
    idx_heading = doc.add_heading("系列索引", level=1)
    idx_heading.runs[0].font.color.rgb = HEADING1_COLOR

    idx_tbl = doc.add_table(rows=1, cols=2)
    idx_tbl.style = "Table Grid"
    idx_tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr = idx_tbl.rows[0].cells
    for i, h in enumerate(["衛星系列", "衛星數"]):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        run = p.add_run(h)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.size = Pt(10)
        _set_cell_bg(hdr[i], "1F497D")

    for label, fname, count in groups:
        row = idx_tbl.add_row().cells
        row[0].text = ""
        row[0].paragraphs[0].add_run(label).font.size = Pt(9.5)
        row[1].text = str(count)
        row[1].paragraphs[0].runs[0].font.size = Pt(9.5)

    idx_tbl.columns[0].width = Cm(12)
    idx_tbl.columns[1].width = Cm(2)

    doc.add_page_break()

    # ── 各群組章節 ────────────────────────────────────────────────────────────
    for group_label, group_fname, group_count in groups:
        print(f"  處理群組：{group_label} ({group_count} 顆) …")

        # Heading 1（加書籤供索引超連結使用）
        bm_name = re.sub(r"[^\w]", "_", group_fname.replace(".html",""))
        add_heading1(doc, group_label, bookmark=bm_name)

        # 讀取群組衛星清單
        group_html = groups_dir / group_fname
        sats = load_group_sats(group_html)
        if not sats:
            doc.add_paragraph(f"（共 {group_count} 顆，詳細資料請參閱 Space-Track）")
        else:
            # 群組一覽表
            add_group_summary_table(doc, sats)
            doc.add_paragraph()   # 表後空行

            # 有 profile 的衛星加詳細內容
            has_profiles = [s for s in sats if s["norad"] in norad_to_md]
            for sat in has_profiles:
                norad = sat["norad"]
                md_path = norad_to_md[norad]
                text = md_path.read_text(encoding="utf-8")
                blocks = parse_md(text)

                # Heading 2：衛星名稱（NORAD）
                title_line = next(
                    (p[0] for k, *p in blocks if k == "h1"), sat["name"]
                )
                add_heading2(doc, title_line)
                add_profile_blocks(doc, blocks)
                doc.add_paragraph()   # 衛星間空行

        doc.add_page_break()

    # ── 儲存 ──────────────────────────────────────────────────────────────────
    doc.save(out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n完成！輸出：{out_path}  ({size_mb:.1f} MB)")


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Generate PRC Satellite Database Word document")
    ap.add_argument("--profiles", default=str(PROFILES_DIR))
    ap.add_argument("--groups",   default=str(GROUPS_DIR))
    ap.add_argument("--home",     default=str(HOME_HTML))
    ap.add_argument("--out",      default=str(OUTPUT_PATH))
    args = ap.parse_args()

    generate(
        profiles_dir = Path(args.profiles),
        groups_dir   = Path(args.groups),
        home_html    = Path(args.home),
        out_path     = Path(args.out),
    )


if __name__ == "__main__":
    main()
