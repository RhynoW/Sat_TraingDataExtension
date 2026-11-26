"""
build_prc_db.py — PRC 衛星基本資料：依 prc_groups.json 分類，產生 CHM、Word/PDF 與 Rust 單機版預設群組
================================================================================================
分類表 prc_groups.json 是唯一來源（大類 → 系列 →〔感測器〕），三種輸出用同一套分組：
  1. PRC衛星基本資料_YYYYMMDD.chm   （HTML Help；需 HTML Help Workshop 的 hhc.exe）
  2. PRC衛星基本資料_YYYYMMDD.docx／.pdf（PDF 以 Word 轉檔，需安裝 Microsoft Word）
  3. RUST_SatDashboard/config/prc_default_groups.json（Rust 單機版首次啟動自動建立的預設群組）
     另輸出 PRC衛星基本資料_YYYYMMDD_群組.csv（norad_id,name,group,note；可用「衛星管理 → CSV 匯入」）

補資料：SATCAT 中仍在軌、國別 PRC 的酬載若沒有 sat_profiles/*.md，會依 SATCAT（Space-Track）與
GCAT（planet4589.org，CC-BY）自動產生基本資料檔（data_quality: satcat_only），不撰寫任務說明。
既有資料檔不會被修改。

感測器：split_sensor 的系列依資料檔「任務類型」欄推定（光學／雷達／電子偵察）；同系列出現兩種以上時
再分一層。此為推定（inferred），不是官方資料。

用法：
  python build_prc_db.py                 # 全部（補資料 → CHM → Word/PDF → Rust 預設群組）
  python build_prc_db.py --no-chm --no-pdf
  python build_prc_db.py --db ../scenario-advanced01/DB/space_db_slim.duckdb
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from html import escape as he
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROFILES = HERE / "sat_profiles"
TAXONOMY = HERE / "prc_groups.json"
CHM_DIR = HERE / "chm_build"
RUST_PRESET = ROOT / "RUST_SatDashboard" / "config" / "prc_default_groups.json"
DEFAULT_DB = ROOT / "scenario-advanced01" / "DB" / "space_db_slim.duckdb"
TITLE = "PRC衛星基本資料"
SENSOR_ZH = {"optical": "光學", "radar": "雷達", "sigint": "電子偵察", "": "未標示感測器"}
SENSOR_ORDER = ["optical", "radar", "sigint", ""]


# ── 分類 ─────────────────────────────────────────────────────────────────────
def name_token(name: str) -> str:
    return re.split(r"[\s_\-/(（]", name.upper().replace("'", ""))[0]


class Taxonomy:
    def __init__(self, path: Path):
        t = json.loads(path.read_text(encoding="utf-8"))
        self.version = t["version"]
        self.root = t["root"]
        self.fallback = tuple(t["fallback"])
        self.cats = t["categories"]
        self.prefix: dict[str, tuple[str, str]] = {}
        self.series_meta: dict[tuple[str, str], dict] = {}
        self.cat_meta: dict[str, dict] = {}
        for c in self.cats:
            self.cat_meta[c["name"]] = c
            for s in c["series"]:
                self.series_meta[(c["name"], s["name"])] = s
                for p in s["prefixes"]:
                    if p in self.prefix:
                        raise SystemExit(f"分類表重複前綴：{p}")
                    self.prefix[p] = (c["name"], s["name"])
        self.cat_meta.setdefault(self.fallback[0], {"name": self.fallback[0], "color": "#7F8C8D", "series": []})
        self.rocket = self.prefix["CZ"]
        self.foreign = self.prefix["IRIDIUM"]

    def classify(self, name: str) -> tuple[str, str]:
        return self.prefix.get(name_token(name), self.fallback)

    def order(self) -> list[tuple[str, list[str]]]:
        out = [(c["name"], [s["name"] for s in c["series"]]) for c in self.cats]
        out.append((self.fallback[0], [self.fallback[1]]))
        return out

    def in_rust(self, cat: str) -> bool:
        return self.cat_meta.get(cat, {}).get("rust", True)


def sensor_of(mission: str) -> str:
    m = mission.upper()
    if re.search(r"ELINT|SIGINT|電子偵察|電子情報|無線電頻率監測", m):
        return "sigint"
    if re.search(r"SAR|雷達", m):
        return "radar"
    if re.search(r"光學|光譜|成像|全色|多光譜|\bEO\b|視頻", m):
        return "optical"
    return ""


# ── 資料檔 ───────────────────────────────────────────────────────────────────
@dataclass
class Sat:
    norad: int
    stem: str
    name: str
    md: str
    cospar: str = ""
    launch: str = ""
    orbit: str = ""
    mission: str = ""
    status: str = ""
    in_catalog: bool = False
    onorbit: bool = False
    cat: str = ""
    series: str = ""
    sensor: str = ""
    leaf: str = ""          # 感測器子層名稱（空白＝無子層）
    quality: str = ""


def md_field(md: str, key: str) -> str:
    m = re.search(rf"^\|\s*{re.escape(key)}\s*\|\s*(.*?)\s*\|\s*$", md, re.M)
    return m.group(1).strip() if m else ""


def load_profiles() -> list[Sat]:
    sats = []
    for f in sorted(PROFILES.glob("*.md")):
        m = re.match(r"^(\d+)_(.+)$", f.stem)
        if not m:
            continue
        md = f.read_text(encoding="utf-8")
        h1 = re.search(r"^#\s+(.+?)\s*(?:\(NORAD.*)?$", md, re.M)
        name = h1.group(1).strip() if h1 else m.group(2).replace("_", " ")
        q = re.search(r"data_quality:\s*(\S+)", md)
        sats.append(Sat(int(m.group(1)), f.stem, name, md,
                        cospar=md_field(md, "COSPAR ID"), launch=md_field(md, "發射日期")[:10],
                        orbit=md_field(md, "軌道"), mission=md_field(md, "任務類型"),
                        quality=q.group(1) if q else ""))
    return sats


def safe_stem(norad: int, name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name.strip()).strip("_")
    return f"{norad}_{s or 'UNKNOWN'}"


def orbit_text(r: dict) -> str:
    if r.get("perigee") is None or r.get("apogee") is None:
        return ""
    s = f"近地點 {r['perigee']:.0f} km × 遠地點 {r['apogee']:.0f} km"
    if r.get("incl") is not None:
        s += f"，傾角 {r['incl']:.1f}°"
    if r.get("period") is not None:
        s += f"，週期 {r['period']:.1f} 分"
    return s


def new_profile_md(r: dict, g: dict | None, gl: dict | None, series: str, satcat_src: str) -> str:
    rows = [("COSPAR ID", r["intl"] or "—"), ("星座 / 系列", series),
            ("營運國別", "中國（SATCAT 國別代碼 PRC）"), ("任務類型", "未查證"),
            ("發射日期", r["launch"] or "—"), ("軌道", orbit_text(r) or "—")]
    out = [f"# {r['name']}  (NORAD {r['norad_id']})", "", "## 基本資訊", "| 欄位 | 值 |", "|------|-----|"]
    out += [f"| {k} | {v} |" for k, v in rows]
    if g:
        out += ["", "## GCAT 紀錄", "| 欄位 | 值 |", "|------|-----|",
                f"| GCAT 名稱 | {g.get('name') or '—'} |", f"| 酬載名稱（PLName） | {g.get('plname') or '—'} |",
                f"| GCAT 營運者代碼 | {g.get('owner') or '—'} |"]
        if gl:
            out += [f"| 發射任務 | {gl.get('mission') or '—'} |", f"| 運載火箭 | {gl.get('lv') or '—'} |"]
    out += ["", "## 資料說明",
            f"本筆由 SATCAT（{satcat_src}）與 GCAT 自動產生，只列編目資料，未撰寫任務背景；"
            "任務與營運者請以官方或可靠來源查證後補充。", "",
            "## 參考來源", f"- https://www.n2yo.com/satellite/?s={r['norad_id']}",
            "- GCAT：Jonathan McDowell, General Catalog of Artificial Space Objects（planet4589.org，CC-BY）",
            "- data_quality: satcat_only", ""]
    return "\n".join(out)


def load_catalog(db: Path):
    import duckdb
    c = duckdb.connect(str(db), read_only=True)
    cols = ["norad_id", "name", "intl", "object_type", "owner", "launch", "decay", "period", "incl", "apogee", "perigee"]
    satcat = {r[0]: dict(zip(cols, r)) for r in c.sql(f"select {','.join(cols)} from satcat").fetchall()}
    gsat = {r[0]: dict(zip(["norad_id", "launch_tag", "name", "plname", "owner"], r))
            for r in c.sql("select norad_id,launch_tag,name,plname,owner from gcat_sat").fetchall()}
    glaunch = {r[0]: dict(zip(["launch_tag", "lv", "mission"], r))
               for r in c.sql("select launch_tag,lv,mission from gcat_launch").fetchall()}
    meta = c.sql("select source,fetched_at from satcat_meta").fetchone()
    c.close()
    return satcat, gsat, glaunch, f"{meta[0]}，{meta[1][:10]} 抓取" if meta else "SATCAT"


def add_missing(tax: Taxonomy, satcat, gsat, glaunch, src: str, have: set[int]) -> int:
    n = 0
    for nid, r in sorted(satcat.items()):
        if r["owner"] != "PRC" or r["object_type"] != "PAYLOAD" or (r["decay"] or "") or nid in have:
            continue
        _, series = tax.classify(r["name"])
        g = gsat.get(nid)
        gl = glaunch.get(g["launch_tag"]) if g else None
        path = PROFILES / f"{safe_stem(nid, r['name'])}.md"
        if path.exists():
            continue
        path.write_text(new_profile_md(r, g, gl, series, src), encoding="utf-8")
        n += 1
    return n


def enrich(sats: list[Sat], tax: Taxonomy, satcat) -> None:
    for s in sats:
        r = satcat.get(s.norad)
        if r:
            s.in_catalog = True
            s.onorbit = not (r["decay"] or "")
            s.status = f"已再入 {r['decay']}" if r["decay"] else "在軌"
            s.cospar = r["intl"] or s.cospar
            s.launch = r["launch"] or s.launch
            s.orbit = orbit_text(r) or s.orbit
        else:
            s.status = "未在 SATCAT"
        s.cat, s.series = tax.classify(s.name)
        # SATCAT 物件類型與國別優先於名稱：火箭殘骸（含遠地點發動機 AKM）、非中國營運的酬載另列
        if r and r["object_type"] == "ROCKET BODY":
            s.cat, s.series = tax.rocket
        elif r and r["object_type"] == "PAYLOAD" and r["owner"] not in ("PRC", "TBD", ""):
            if tax.in_rust(s.cat):
                s.cat, s.series = tax.foreign
        elif r and r["owner"] == "PRC" and (s.cat, s.series) == tax.foreign:
            s.cat, s.series = tax.fallback  # 名稱像外國衛星，但 SATCAT 國別為 PRC
        if tax.series_meta.get((s.cat, s.series), {}).get("split_sensor"):
            s.sensor = sensor_of(s.mission)
    # 同一系列有兩種以上感測器才分子層
    by_series = defaultdict(list)
    for s in sats:
        if tax.series_meta.get((s.cat, s.series), {}).get("split_sensor"):
            by_series[(s.cat, s.series)].append(s)
    for members in by_series.values():
        if len({m.sensor for m in members}) > 1:
            for m in members:
                m.leaf = SENSOR_ZH[m.sensor]


def tree(sats: list[Sat], tax: Taxonomy):
    """回傳 [(cat, [(series, [(leaf, [Sat])])])]，依分類表順序，略過空的節點。"""
    idx = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for s in sats:
        idx[s.cat][s.series][s.leaf].append(s)
    out = []
    for cat, series_list in tax.order():
        if cat not in idx:
            continue
        ser = []
        for sname in series_list:
            leaves = idx[cat].get(sname)
            if not leaves:
                continue
            order = [""] + [SENSOR_ZH[k] for k in SENSOR_ORDER]
            ser.append((sname, [(lf, sorted(leaves[lf], key=lambda x: x.norad)) for lf in order if lf in leaves]))
        out.append((cat, ser))
    return out


def count(node) -> int:
    if isinstance(node, list):
        return sum(count(x) for x in node)
    if isinstance(node, Sat):
        return 1
    return count(node[1])


# ── CHM ──────────────────────────────────────────────────────────────────────
HHC_PATHS = [r"C:\Program Files (x86)\HTML Help Workshop\hhc.exe", r"C:\Program Files\HTML Help Workshop\hhc.exe"]


def sat_table_html(items: list[Sat], prefix: str = "") -> str:
    rows = "".join(
        f"<tr><td>{s.norad}</td><td><a href=\"{prefix}{s.stem}.html\">{he(s.name)}</a></td><td>{he(s.cospar)}</td>"
        f"<td>{he(s.launch)}</td><td>{he(s.orbit)}</td><td>{he(s.status)}</td></tr>" for s in items)
    return ("<table><thead><tr><th>NORAD</th><th>名稱</th><th>COSPAR</th><th>發射日期</th><th>軌道</th><th>狀態</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>")


def build_chm(t, sats: list[Sat], tax: Taxonomy, today: str, src: str, out: Path) -> bool:
    sys.path.insert(0, str(HERE))
    from gen_chm import CSS, html_page, md2html  # noqa: E402

    if CHM_DIR.exists():
        shutil.rmtree(CHM_DIR)
    (CHM_DIR / "_groups").mkdir(parents=True)
    (CHM_DIR / "style.css").write_text(CSS, encoding="utf-8")
    for s in sats:
        nav = (f'<p class="nav"><a href="home.html">首頁</a> › {he(s.cat)} › {he(s.series)}'
               + (f" › {he(s.leaf)}" if s.leaf else "") + "</p>\n")
        (CHM_DIR / f"{s.stem}.html").write_text(html_page(f"{s.name} ({s.norad})", nav + md2html(s.md)), encoding="utf-8")

    files, toc, rows = [], [], []
    gid = 0

    def page(title: str, body: str) -> str:
        nonlocal gid
        gid += 1
        rel = f"_groups/g{gid:03d}.html"
        (CHM_DIR / rel).write_text(html_page(title, '<p class="nav"><a href="../home.html">首頁</a></p>\n' + body,
                                             css_rel="../style.css"), encoding="utf-8")
        files.append(rel)
        return rel

    def node(name: str, href: str, depth: int) -> None:
        ind = "  " * depth
        toc.append(f'{ind}<LI><OBJECT type="text/sitemap"><param name="Name" value="{he(name)}">'
                   f'<param name="Local" value="{href}"></OBJECT>')

    for cat, ser in t:
        n_cat = count(ser)
        summary = "".join(f"<li>{he(sn)}（{count(lv)}）</li>" for sn, lv in ser)
        node(f"{cat}（{n_cat}）", page(cat, f"<h1>{he(cat)}</h1><p>共 {n_cat} 筆</p><ul>{summary}</ul>"), 1)
        toc.append("  <UL>")
        rows.append(f'<tr><td rowspan="{len(ser)}"><b>{he(cat)}</b></td>')
        for i, (sname, leaves) in enumerate(ser):
            n_ser = count(leaves)
            items = [s for _, lst in leaves for s in lst]
            body = f"<h1>{he(sname)}</h1><p>{he(cat)}｜共 {n_ser} 筆</p>"
            for lf, lst in leaves:
                if lf:
                    body += f"<h2>{he(lf)}（{len(lst)}）</h2>"
                body += sat_table_html(lst, "../")
            href = page(sname, body)
            node(f"{sname}（{n_ser}）", href, 2)
            rows.append(("" if i == 0 else "<tr>") + f'<td><a href="{href}">{he(sname)}</a></td><td>{n_ser}</td></tr>')
            toc.append("    <UL>")
            for lf, lst in leaves:
                depth = 3
                if lf:
                    node(f"{lf}（{len(lst)}）", href, 3)
                    toc.append("      <UL>")
                    depth = 4
                for s in lst:
                    node(f"{s.name} ({s.norad})", f"{s.stem}.html", depth)
                if lf:
                    toc.append("      </UL>")
            toc.append("    </UL>")
        toc.append("  </UL>")

    q = Counter(s.quality or "（未標示）" for s in sats)
    home = (f"<h1>{TITLE}</h1><p>產生日期：{today}｜共 {len(sats)} 筆（在軌 {sum(s.onorbit for s in sats)}）｜"
            f"分類表版本 {tax.version}</p>"
            "<p>分組與 Rust 單機版「衛星管理 → 群組分類」的預設群組相同（大類 → 系列 →〔感測器〕）。"
            "感測器子層依各筆「任務類型」欄推定，屬推定資料。</p>"
            f"<p>編目資料：{he(src)}；GCAT（planet4589.org，CC-BY）。資料品質："
            + "、".join(f"{he(k)} {v}" for k, v in q.most_common()) + "。</p>"
            "<table><thead><tr><th>大類</th><th>系列</th><th>筆數</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")
    (CHM_DIR / "home.html").write_text(html_page(TITLE, home), encoding="utf-8")

    hhc = ['<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">', "<HTML><HEAD></HEAD><BODY>",
           '<OBJECT type="text/site properties"><param name="ImageType" value="Folder"></OBJECT>', "<UL>",
           f'  <LI><OBJECT type="text/sitemap"><param name="Name" value="{TITLE}（首頁）"><param name="Local" value="home.html"></OBJECT>',
           *toc, "</UL>", "</BODY></HTML>"]
    hhk = ['<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">', "<HTML><HEAD></HEAD><BODY>", "<UL>"]
    for s in sorted(sats, key=lambda x: x.name):
        for key in (s.name, str(s.norad)):
            hhk.append(f'  <LI><OBJECT type="text/sitemap"><param name="Name" value="{he(key)}">'
                       f'<param name="Local" value="{s.stem}.html"></OBJECT>')
    hhk += ["</UL>", "</BODY></HTML>"]
    # hhc.exe 以系統 ANSI（cp950）讀 HHC／HHK
    (CHM_DIR / "toc.hhc").write_text("\n".join(hhc), encoding="cp950", errors="replace")
    (CHM_DIR / "index.hhk").write_text("\n".join(hhk), encoding="cp950", errors="replace")
    filelist = "\n".join(["style.css", "home.html"] + files + [f"{s.stem}.html" for s in sats])
    (CHM_DIR / "prc_satellites.hhp").write_text(
        "[OPTIONS]\nCompiled file=prc_satellites.chm\nContents file=toc.hhc\nDefault Window=main\n"
        "Default topic=home.html\nDisplay compile progress=No\nFull-text search=Yes\nIndex file=index.hhk\n"
        "Language=0x0404 Chinese (Traditional)\nTitle=PRC Satellite Database\n\n[WINDOWS]\n"
        'main="PRC Satellite Database","toc.hhc","index.hhk","home.html","home.html",,,,,0x63520,,0x2520,,,,,,,,0\n\n'
        f"[FILES]\n{filelist}\n", encoding="utf-8")
    hhc_exe = next((p for p in HHC_PATHS if Path(p).exists()), None)
    if not hhc_exe:
        print("  ⚠ 找不到 hhc.exe（HTML Help Workshop）：已產生 chm_build/，未編譯。安裝後執行："
              "python build_prc_db.py --chm-only")
        return False
    subprocess.run([hhc_exe, "prc_satellites.hhp"], cwd=CHM_DIR, capture_output=True)
    built = CHM_DIR / "prc_satellites.chm"
    if not built.exists():
        print("  ❌ CHM 編譯失敗")
        return False
    shutil.copyfile(built, out)
    print(f"  CHM：{out.name}（{out.stat().st_size / 1e6:.1f} MB）")
    return True


# ── Word／PDF ────────────────────────────────────────────────────────────────
def build_docx(t, sats: list[Sat], tax: Taxonomy, today: str, src: str, out: Path) -> None:
    sys.path.insert(0, str(HERE))
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor
    from generate_doc import _inline_runs, _set_cell_bg, add_info_table, parse_md

    blue = RGBColor(0x1F, 0x49, 0x7D)
    doc = Document()
    for sect in doc.sections:
        sect.top_margin = sect.bottom_margin = Cm(2.0)
        sect.left_margin = sect.right_margin = Cm(2.2)
    st = doc.styles["Normal"]
    st.font.name = "Microsoft JhengHei"
    st.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft JhengHei")
    st.font.size = Pt(9.5)

    def heading(text, level):
        h = doc.add_heading(text, level=level)
        for r in h.runs:
            r.font.color.rgb = blue
        return h

    def table(headers, rows, widths=None, size=8.5):
        tb = doc.add_table(rows=1, cols=len(headers))
        tb.style = "Table Grid"
        for i, h in enumerate(headers):
            c = tb.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(h)
            r.bold, r.font.size = True, Pt(size)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            _set_cell_bg(c, "1F497D")
        for row in rows:
            cells = tb.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(size)
        if widths:
            for i, w in enumerate(widths):
                for c in tb.columns[i].cells:
                    c.width = Cm(w)
        return tb

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"\n\n\n{TITLE}")
    r.font.size, r.bold, r.font.color.rgb = Pt(30), True, blue
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"共 {len(sats)} 筆（在軌 {sum(s.onorbit for s in sats)}）｜產生日期 {today}｜分類表版本 {tax.version}\n"
              f"編目資料：{src}；GCAT（planet4589.org，CC-BY）\n"
              "分組與 Rust 單機版「衛星管理 → 群組分類」的預設群組相同").font.size = Pt(11)
    doc.add_page_break()

    heading("分類索引", 1)
    doc.add_paragraph("大類 → 系列 →〔感測器〕。感測器子層依各筆「任務類型」欄推定，屬推定資料；"
                      "標示 satcat_only 的資料檔只有編目資料，未撰寫任務背景。")
    idx = []
    for cat, ser in t:
        for sname, leaves in ser:
            sub = "、".join(f"{lf} {len(l)}" for lf, l in leaves if lf)
            idx.append([cat, sname, count(leaves), sub])
    table(["大類", "系列", "筆數", "感測器子層"], idx, [3.2, 5.5, 1.6, 6.0], 9)
    doc.add_page_break()

    for cat, ser in t:
        print(f"  Word：{cat}（{count(ser)}）")
        heading(f"{cat}（{count(ser)}）", 1)
        for sname, leaves in ser:
            heading(f"{sname}（{count(leaves)}）", 2)
            for lf, lst in leaves:
                if lf:
                    heading(f"{lf}（{len(lst)}）", 3)
                table(["NORAD", "名稱", "COSPAR", "發射日期", "軌道", "狀態"],
                      [[s.norad, s.name, s.cospar, s.launch, s.orbit, s.status] for s in lst],
                      [1.5, 3.6, 2.1, 2.0, 5.2, 2.2], 7.5)
                for s in lst:
                    heading(f"{s.name}（NORAD {s.norad}）", 4)
                    for kind, *pl in parse_md(s.md):
                        if kind in ("blank", "h1"):
                            continue
                        if kind in ("h2", "h3"):
                            q = doc.add_paragraph()
                            rr = q.add_run(pl[0])
                            rr.bold, rr.font.color.rgb = True, blue
                        elif kind == "table":
                            add_info_table(doc, pl[0])
                        elif kind == "li":
                            _inline_runs(doc.add_paragraph(style="List Bullet"), pl[0])
                        elif kind == "para" and pl[0]:
                            _inline_runs(doc.add_paragraph(), pl[0])
        doc.add_page_break()
    doc.save(out)
    print(f"  Word：{out.name}（{out.stat().st_size / 1e6:.1f} MB）")


def docx_to_pdf(docx: Path, pdf: Path) -> None:
    from docx2pdf import convert
    convert(str(docx), str(pdf))
    print(f"  PDF：{pdf.name}（{pdf.stat().st_size / 1e6:.1f} MB）")


# ── Rust 預設群組 ─────────────────────────────────────────────────────────────
def build_rust_preset(t, tax: Taxonomy, today: str, out_csv: Path) -> None:
    groups = [{"path": [tax.root], "color": "#C0392B", "sensor": "",
               "note": f"預設群組（{TITLE}_{today.replace('-', '')}，分類表 {tax.version}）；只含在軌酬載", "members": []}]
    csv_rows = []
    for cat, ser in t:
        if not tax.in_rust(cat):
            continue
        groups.append({"path": [tax.root, cat], "color": tax.cat_meta.get(cat, {}).get("color", ""),
                       "sensor": "", "note": "", "members": []})
        for sname, leaves in ser:
            single = [lf for lf, _ in leaves] == [""]
            sens = {s.sensor for _, lst in leaves for s in lst}
            ser_sensor = next(iter(sens)) if single and len(sens) == 1 else ""
            note = "感測器依資料檔任務類型欄推定" if ser_sensor or not single else ""
            ser_members = sorted(s.norad for lf, lst in leaves if not lf for s in lst if s.onorbit)
            groups.append({"path": [tax.root, cat, sname], "color": "", "sensor": ser_sensor, "note": note,
                           "members": ser_members})
            for lf, lst in leaves:
                if not lf:
                    continue
                key = next(k for k, v in SENSOR_ZH.items() if v == lf)
                groups.append({"path": [tax.root, cat, sname, lf], "color": "", "sensor": key,
                               "note": "感測器依資料檔任務類型欄推定" if key else "",
                               "members": sorted(s.norad for s in lst if s.onorbit)})
            for lf, lst in leaves:
                for s in lst:
                    if s.onorbit:
                        csv_rows.append((s.norad, " / ".join([tax.root, cat, sname] + ([lf] if lf else []))))
    groups = [g for g in groups if g["members"] or any(h["path"][:len(g["path"])] == g["path"] and h["members"]
                                                        for h in groups)]
    data = {"version": tax.version, "built": today, "source": f"{TITLE}_{today.replace('-', '')}", "groups": groups}
    RUST_PRESET.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(g["members"]) for g in groups)
    print(f"  Rust 預設群組：{len(groups)} 個群組、{n} 個成員 → {RUST_PRESET.relative_to(ROOT)}")
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("norad_id,name,group,note\n")
        for nid, path in sorted(csv_rows):
            f.write(f"{nid},,{path},\n")
    print(f"  群組 CSV：{out_csv.name}（{len(csv_rows)} 列）")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--no-new", action="store_true", help="不補新衛星資料檔")
    ap.add_argument("--no-chm", action="store_true")
    ap.add_argument("--no-pdf", action="store_true", help="只產 docx，不轉 PDF")
    ap.add_argument("--no-doc", action="store_true", help="不產 Word／PDF")
    ap.add_argument("--chm-only", action="store_true")
    a = ap.parse_args()
    today = a.date
    stamp = today.replace("-", "")
    tax = Taxonomy(TAXONOMY)
    satcat, gsat, glaunch, src = load_catalog(a.db)
    if not a.no_new and not a.chm_only:
        have = {s.norad for s in load_profiles()}
        print(f"補資料：新增 {add_missing(tax, satcat, gsat, glaunch, src, have)} 筆 satcat_only 資料檔")
    sats = load_profiles()
    enrich(sats, tax, satcat)
    t = tree(sats, tax)
    print(f"共 {len(sats)} 筆；" + "、".join(f"{c} {count(s)}" for c, s in t))
    base = HERE / f"{TITLE}_{stamp}"
    if not a.no_chm:
        build_chm(t, sats, tax, today, src, base.with_suffix(".chm"))
    if a.chm_only:
        return 0
    if not a.no_doc:
        build_docx(t, sats, tax, today, src, base.with_suffix(".docx"))
        if not a.no_pdf:
            docx_to_pdf(base.with_suffix(".docx"), base.with_suffix(".pdf"))
    build_rust_preset(t, tax, today, HERE / f"{TITLE}_{stamp}_群組.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
