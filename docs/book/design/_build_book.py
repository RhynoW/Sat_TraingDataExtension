"""排版版全書 PDF：封面 A v2＋書名頁＋目錄＋21 章（章首跨頁＋內文）＋封底。

來源（只讀）：
  docs/book/v0.9_讀者版/全書_修訂版_v1.2.md   全書正文（_merge_v12.py 產出）
  docs/book/design/章首文案_全書.md            章名、核心問題、路線、主案例
  docs/book/design/_visuals.py                 章首主視覺
  docs/book/design/cover_A_v2.html、back_v2.html
排版只影響呈現：H1 與「學習目標」一節移到章首跨頁，不在內文重複；其餘 Markdown 原樣轉換。

用法（repo 根目錄）：python docs/book/design/_build_book.py
輸出：docs/book/v0.9_讀者版/全書_排版版_v1.2.pdf（另留 .html 內頁供檢查）
"""
import html
import re
import sys
from pathlib import Path

import fitz
import markdown
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
from _visuals2 import visual as _visual  # noqa: E402

# 章首右頁配圖改用照片（相對 BOOKDIR）：章號 → (圖檔, 署名)
PHOTO_VISUALS = {
    14: ("img/nasa/s64-03507_inv.jpg", "雙子星太空船對姿態控制推力的反應：俯仰、滾轉、偏航（1964）｜NASA，S64-03507；原圖白底黑線，本書反相處理"),
    15: ("img/nasa/s65-05399_inv.jpg", "雙子星太空船機動控制示意圖：垂直、側向、前進、後退（1965）｜NASA，S65-05399；原圖白底黑線，本書反相處理"),
    16: ("img/nasa/ARC-1977-A77-0851_art.jpg", "Voyager 土星任務構想圖：以重力彈弓飛越木星、土星，前往天王星（1977）｜NASA Ames Research Center，ARC-1977-A77-0851"),
    21: ("img/tasa/maraho_2026-08-22.jpg", "TASA 首支自主探空火箭「島脈 MARAHO」首次飛試任務團隊合影（2026-08-22，屏東旭海）｜照片：國家太空中心（TASA）"),
}


# 章首左頁下半部照片：章號 → (圖檔, 署名)
LEFT_PHOTOS = {
    21: ("img/tasa/launch_vehicle_model_2023-09-14.jpg", "TASA 三節式入軌火箭模型首度亮相（2023 台北國際航太暨國防工業展）｜照片：國家太空中心提供，取自自由時報 2023-09-14 報導"),
}


# 扉頁四個 QR 碼（與 rhynowu-stk-dashboard.static.hf.space/index.html 相同的四個入口）
QR_LINKS = [
    ("SatDashboard（SSA 系統）", "https://huggingface.co/spaces/RhynoWu/ATRDC-SatDashboard-i18n"),
    ("Maneuver Detection Dashboard（含本書線上版）", "https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n"),
    ("次軌道駕駛艙（互動遊戲）", "https://rhynowu-stk-dashboard.static.hf.space/spaceport_game/index.html"),
    ("STKER + SysML v2 案例集", "https://rhynowu-stk-dashboard.static.hf.space/stker_sysml_showcase/index.html"),
]


def _qr_svg(url: str) -> str:
    import qrcode
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    path = "".join(f"M{x} {y}h1v1h-1z" for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


QR_BLOCK = '<div class="qrs">' + "".join(
    f'<a class="qr" href="{u}">{_qr_svg(u)}<b>{html.escape(label)}</b><small>{html.escape(u.split("://", 1)[1])}</small></a>'
    for label, u in QR_LINKS) + "</div>"

# 全書最後一頁（附錄之後、封底之前）：全幅照片
LAST_PAGE = ('<section class="lastpage"><img src="img/nasa/KSC-20240605-PH-RKL01_0002.jpg" alt="">'
             '<div class="lcap">Rocket Lab Electron 火箭「PREFIRE and Ice」任務升空：2024-06-05 15:15（紐西蘭標準時間），紐西蘭馬希亞 1 號發射場；'
             'NASA PREFIRE 任務的第二次發射，把立方衛星送往近極地軌道｜照片：Rocket Lab（經 NASA 發布），KSC-20240605-PH-RKL01_0002</div></section>')


def left_photo(n):
    if n not in LEFT_PHOTOS:
        return ""
    src, credit = LEFT_PHOTOS[n]
    return f'<div class="lphoto"><img src="{src}" alt=""><div>{html.escape(credit)}</div></div>'


def visual(n):
    if n not in PHOTO_VISUALS:
        return _visual(n)
    src, credit = PHOTO_VISUALS[n]
    return (f'<svg class="visual" viewBox="0 0 210 150" preserveAspectRatio="xMidYMid slice">'
            f'<defs><linearGradient id="vp{n}g" x1="0" y1="0" x2="0" y2="1"><stop offset=".80" stop-color="#fff"/>'
            f'<stop offset="1" stop-color="#000"/></linearGradient><mask id="vp{n}"><rect width="210" height="150" fill="url(#vp{n}g)"/></mask></defs>'
            f'<g mask="url(#vp{n})"><image href="{src}" x="0" y="0" width="210" height="150" preserveAspectRatio="xMidYMid slice"/></g></svg>'
            f'<div class="vcredit">{html.escape(credit)}</div>')

BOOKDIR = D.parent / "v1.0_送審版"
SRC = BOOKDIR / "全書_送審版_v1.3.md"
OUT_HTML = BOOKDIR / "全書_排版版_v1.3.html"
OUT_PDF = BOOKDIR / "全書_排版版_v1.3.pdf"
VERSION, DATE, COPY = "v1.3", "2026.11.19", "©Sat_Dashboard"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
TMP = Path(ARGS[0]) if ARGS else BOOKDIR / "_build_tmp"
# --with-ext：另排「全書＋延伸模擬篇（S1–S3）」版本，輸出到 sim_chapters/pdf/，不覆蓋送審版檔案；
# 延伸篇放在結語之後、附錄之前。未加此選項時，行為與原本相同。
WITH_EXT = "--with-ext" in sys.argv
SIMDIR = D.parent / "sim_chapters"
if WITH_EXT:
    OUT_HTML = SIMDIR / "pdf" / "全書_排版版_v1.3_含延伸篇.html"
    OUT_PDF = SIMDIR / "pdf" / "全書_排版版_v1.3_含延伸篇.pdf"
    VERSION, DATE = "v1.3＋延伸模擬篇", "2026.11.23"
    if not ARGS:
        TMP = SIMDIR / "pdf" / "_build_tmp"
TMP.mkdir(parents=True, exist_ok=True)

TITLE = "從衛星軌道論國家安全"
SUB = "太空態勢感知的基礎——智慧化低軌通訊衛星軌道異常與太空事件偵測演算法研究"

# ---------- 章首文案 ----------
meta = {}
for line in (D / "章首文案_全書.md").read_text(encoding="utf-8").splitlines():
    m = re.match(r"^\| (\d\d) \| (.+?) \| (.+?) \| (.+?) \| (.+?) \| (.+?) \|$", line)
    if m:
        n = int(m.group(1))
        cases = [] if "無主案例" in m.group(5) else [c.strip() for c in m.group(5).split("／")]
        meta[n] = dict(title=m.group(2), q=m.group(3), route=[r.strip() for r in m.group(4).split("→")], cases=cases)
assert sorted(meta) == list(range(1, 22))

# ---------- 拆章 ----------
text = SRC.read_text(encoding="utf-8")
# 附錄（# 附錄…）不做章首跨頁，接在第 21 章之後
appendix_md = ""
if re.search(r"^# 附錄", text, re.M):
    k = re.search(r"^# 附錄", text, re.M).start()
    text, appendix_md = text[:k], text[k:]
parts = re.split(r"^(?=# 第 \d+ 章)", text, flags=re.M)
parts = [p for p in parts if p.strip()]
assert len(parts) == 21


def md2html(t):
    math = []

    def keep(m):
        math.append(m.group(0))
        return f"@@MATH{len(math) - 1}@@"
    t = re.sub(r"B\*(?!\*)", r"B\\*", t)
    # 證據方框：引用區塊內各欄位（> **欄名**）分段，避免被併成一段
    t = re.sub(r"^(> \*\*[^\n]*)\r?\n(?=> \*\*)", r"\1\n>\n", t, flags=re.M)
    t = re.sub(r"^(> \*\*[^\n]*)\r?\n(?=> \*\*)", r"\1\n>\n", t, flags=re.M)
    t = re.sub(r"\\\[.*?\\\]", keep, t, flags=re.S)
    t = re.sub(r"\\\(.*?\\\)", keep, t, flags=re.S)
    h = markdown.markdown(t, extensions=["tables", "sane_lists", "fenced_code"])
    # 獨立成段的行間公式改用 div，避免段落斷頁殘留
    h = re.sub(r"<p>(@@MATH\d+@@)</p>", r'<div class="math">\1</div>', h)
    h = linkify(h)
    for i, m in enumerate(math):
        h = h.replace(f"@@MATH{i}@@", html.escape(m, quote=False))
    return h, len(math)


URL_RE = re.compile(r"(?<![\"'=/])\bhttps?://[^\s<>\"'　-〿一-鿿＀-￯]+")
N_LINKS = [0]


def linkify(h):
    """裸網址改為可點擊連結；長網址只顯示網域，完整網址保留在連結目標（送審版 Markdown 保留全文）。"""
    def sub(m):
        u = m.group(0)
        tail = ""
        while u and u[-1] in ".,;:)":
            if u[-1] == ")" and u.count("(") >= u.count(")"):
                break
            tail = u[-1] + tail
            u = u[:-1]
        href = html.unescape(u)
        host = re.sub(r"^https?://(www\.)?", "", href).split("/")[0]
        rest = re.sub(r"^https?://(www\.)?", "", href)[len(host):].strip("/")
        shown = host if not rest else (re.sub(r"^https?://(www\.)?", "", href).rstrip("/") if len(href) <= 40 else host + "/…")
        N_LINKS[0] += 1
        return f'<a class="url" href="{html.escape(href, quote=True)}">{html.escape(shown)}</a>{tail}'
    out, pos = [], 0
    # 只處理標籤外的文字
    for m in re.finditer(r"<[^>]+>", h):
        out.append(URL_RE.sub(sub, h[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(URL_RE.sub(sub, h[pos:]))
    return "".join(out)


def br_title(t):
    for sep in ("：", "，"):
        if sep in t:
            a, b = t.split(sep, 1)
            return f"{html.escape(a)}{sep}<br>{html.escape(b)}"
    if "、" in t and len(t) > 10:
        a, b = t.split("、", 1)
        return f"{html.escape(a)}、<br>{html.escape(b)}"
    return html.escape(t)


chapters, n_math, stats = [], 0, []
for n, raw in enumerate(parts, 1):
    lines = raw.split("\n")
    h1 = lines[0]
    assert h1.startswith(f"# 第 {n} 章"), h1
    body = lines[1:]
    # 抽出「學習目標」一節（到下一個 ## 為止）
    i = next(k for k, l in enumerate(body) if l.strip() == "## 學習目標")
    j = next(k for k in range(i + 1, len(body)) if body[k].startswith("## "))
    goals = [re.sub(r"^(?:[-*]|\d+\.)\s+", "", l).strip() for l in body[i + 1:j] if re.match(r"^\s*(?:[-*]|\d+\.)\s+", l)]
    body = body[:i] + body[j:]
    h, k = md2html("\n".join(body))
    n_math += k
    # 插敘：標題段＋緊接的一段
    h, n_as = re.subn(r"<p><strong>(插敘[^<]*)</strong></p>\s*<p>",
                      r'<p class="aside-h"><span>\1</span><em>背景脈絡｜外部事件，非本專案分析案例</em></p>\n<p class="aside">', h)
    # 主案例證據方框
    h = re.sub(r"<blockquote>\s*<p><strong>證據等級", r'<blockquote class="evidence">\n<p><strong>證據等級', h)
    h = re.sub(r"(<blockquote class=\"evidence\">.*?</blockquote>)",
               lambda m: m.group(1).replace("<br />\n", "</p>\n<p>"), h, flags=re.S)
    h = re.sub(r"<p><strong>資料規格</strong>", r'<p class="spec"><strong>資料規格</strong>', h)
    h = re.sub(r"<p>((?:圖|照片) \d+-\d+　)", r'<p class="cap">\1', h)
    h = re.sub(r'<p><img ', r'<p class="fig"><img ', h)
    # 章末來源：自「本章外部事件來源」起縮小字級
    h = re.sub(r"(<h2>本章外部事件來源</h2>)", r'<div class="notes">\1', h, count=1)
    if '<div class="notes">' in h:
        h += "</div>"
    else:
        h = re.sub(r"(<h2>資料來源</h2>)", r'<div class="notes">\1', h, count=1) + "</div>"
    chapters.append(dict(n=n, goals=goals, html=h))
    stats.append((n, len(goals), n_as))


# ---------- 延伸模擬篇（--with-ext） ----------
EXT_META = {
    "S1": dict(file="S1_碎片連鎖一次解體會引發什麼_初稿.md", title="碎片連鎖：一次解體會引發什麼",
               q="一次解體之後，碎片多快消失？在消失之前，會不會撞出下一代碎片？",
               route=["解體模型", "傳播與大氣", "碰撞率", "Cosmos 1408 驗證", "緩解決策"],
               img="../sim_chapters/img/op_s1.jpg", credit="碎片連鎖模擬畫面：Cosmos 1408 情境，解體後約 46 天｜本專案 Rust 單機版，2026-11-22"),
    "S2": dict(file="S2_巨型星座的外部成本壅擠與光害_初稿.md", title="巨型星座的外部成本：壅擠與光害",
               q="星座變大之後，接近與光跡的成本落在誰身上？",
               route=["假想星座", "接近頻率", "收斂與敏感度", "第三方成本", "光跡與地影"],
               img="../sim_chapters/img/op_s2.jpg", credit="星座壅擠模擬畫面：10 萬 Starlink 情境｜本專案 Rust 單機版，2026-11-22"),
    "S3": dict(file="S3_兵棋推演海纜中斷下的太空通訊韌性_初稿.md", title="兵棋推演：海纜中斷下的太空通訊韌性",
               q="在寫清楚的假設下，哪些選擇比較好？假設改變時，結論會不會翻轉？",
               route=["想定依據", "對照組", "四個想定", "配對差值", "敏感度分析"],
               img="../sim_chapters/img/op_s3.jpg", credit="太空兵棋模擬畫面：想定 C 的一局｜本專案 Rust 單機版，2026-11-22"),
}
EXT_KEYS = list(EXT_META) if WITH_EXT else []
ext_chapters = []
for k in EXT_KEYS:
    lines = (SIMDIR / EXT_META[k]["file"]).read_text(encoding="utf-8").split("\n")
    assert lines[0].startswith(f"# 延伸篇 {k}"), lines[0]
    body = lines[1:]
    i = next(x for x, l in enumerate(body) if l.strip() == "## 學習目標")
    j = next(x for x in range(i + 1, len(body)) if body[x].startswith("## "))
    goals = [re.sub(r"^(?:[-*]|\d+\.)\s+", "", l).strip() for l in body[i + 1:j] if re.match(r"^\s*(?:[-*]|\d+\.)\s+", l)]
    h, kk = md2html("\n".join(body[:i] + body[j:]))
    n_math += kk
    h = h.replace('src="img/', 'src="../sim_chapters/img/')
    h = re.sub(r"<blockquote>\s*<p><strong>證據等級", r'<blockquote class="evidence">\n<p><strong>證據等級', h)
    h = re.sub(r"(<blockquote class=\"evidence\">.*?</blockquote>)",
               lambda m: m.group(1).replace("<br />\n", "</p>\n<p>"), h, flags=re.S)
    h = re.sub(r"<p>((?:圖|畫面) S\d-\d+　)", r'<p class="cap">\1', h)
    h = re.sub(r'<p><img ', r'<p class="fig"><img ', h)
    h = re.sub(r"(<h2>本章外部事件來源</h2>)", r'<div class="notes">\1', h, count=1)
    h = h + "</div>" if '<div class="notes">' in h else re.sub(r"(<h2>資料來源</h2>)", r'<div class="notes">\1', h, count=1) + "</div>"
    ext_chapters.append(dict(n=k, goals=goals, html=h))


def ext_opener(c):
    k, m = c["n"], EXT_META[c["n"]]
    chips = '<span class="arr">→</span>'.join(f'<span class="chip">{html.escape(r)}</span>' for r in m["route"])
    goals = "".join("<li>" + html.escape(g) + "</li>" for g in c["goals"])
    vis = (f'<svg class="visual" viewBox="0 0 210 150" preserveAspectRatio="xMidYMid slice">'
           f'<defs><linearGradient id="v{k}g" x1="0" y1="0" x2="0" y2="1"><stop offset=".80" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>'
           f'<mask id="v{k}"><rect width="210" height="150" fill="url(#v{k}g)"/></mask></defs>'
           f'<g mask="url(#v{k})"><image href="{m["img"]}" x="0" y="0" width="210" height="150" preserveAspectRatio="xMidYMid slice"/></g></svg>'
           f'<div class="vcredit">{html.escape(m["credit"])}</div>')
    return f"""
<div class="op op-l" id="op{k}">
  <div class="bignum ext">{k}</div>
  <svg class="bg" viewBox="0 0 210 297" preserveAspectRatio="none"><path d="M-10 270 C 60 240, 150 250, 230 214" fill="none" stroke="#35C6FF" stroke-opacity=".25" stroke-width=".35"/></svg>
  <div class="num">EXTENSION {k}</div>
  <h1 class="t long">{br_title(m['title'])}</h1>
  <div class="q"><div class="bar"></div><div class="k">核心問題</div><p>{html.escape(m['q'])}</p></div>
  <div class="run">延伸篇 {k}　{html.escape(m['title'])}</div>
</div>
<div class="op op-r">
  {vis}
  <div class="flow">
    <div><div class="k2">LEARNING GOALS　學習目標</div><ol class="goals">{goals}</ol></div>
    <div><div class="k2">ROUTE　本篇路線</div><div class="chips">{chips}</div></div>
  </div>
</div>"""


def ext_part(toc_pages):
    rows = "".join(f'<li><span class="tn">延伸篇 {k}</span><span class="tt">{html.escape(EXT_META[k]["title"])}</span>'
                   f'<span class="dots"></span><span class="tp">{toc_pages.get(k, "")}</span></li>' for k in EXT_KEYS)
    return f"""
<div class="op part" id="part">
  <svg class="bg" viewBox="0 0 210 297" preserveAspectRatio="none"><path d="M-10 270 C 60 240, 150 250, 230 214" fill="none" stroke="#35C6FF" stroke-opacity=".25" stroke-width=".35"/></svg>
  <div class="num">EXTENSION｜PART</div>
  <h1 class="t">延伸模擬篇</h1>
  <div class="pq">碎片連鎖、巨型星座的外部成本、兵棋推演：用三個可以操作的教學模型，把本書的證據鏈延伸到「推演」。</div>
  <div class="pnote">內容取自本專案 Rust 單機版的教學模型；除碎片衰減曲線已對照 CelesTrak 觀測外，數值一律為教學模型示意，不是預報，也不是政策或能力評估。證據等級另設「M｜教學模型（示意）」與「M＋｜教學模型，部分已對照觀測」。</div>
  <ol class="ptoc">{rows}</ol>
  <div class="run">延伸模擬篇｜2026-11-22 初稿</div>
</div>"""


EXT_CSS = """
.op.part .t{top:58mm}
.op.part .pq{position:absolute;left:20mm;right:24mm;top:84mm;font:600 14pt/1.8 "Noto Serif TC";color:var(--white)}
.op.part .pnote{position:absolute;left:20mm;right:24mm;top:128mm;font:400 9.4pt/1.85 "Noto Sans TC";color:var(--gray);border-left:2px solid var(--amber);padding-left:5mm}
.op.part .ptoc{position:absolute;left:20mm;right:24mm;top:188mm;list-style:none;margin:0;padding:0}
.op.part .ptoc li{display:flex;align-items:baseline;gap:3mm;padding:2.6mm 0;border-bottom:1px solid rgba(201,211,222,.2);font:500 11.5pt "Noto Sans TC";color:var(--white)}
.op.part .ptoc .tn{font:600 9pt "IBM Plex Mono","Noto Sans TC";color:var(--cyan);min-width:22mm;letter-spacing:.05em}
.op.part .ptoc .dots{flex:1}
.op.part .ptoc .tp{font:500 10pt "IBM Plex Mono";color:var(--gray)}
.op .bignum.ext{font-size:120pt}
.toc li.ext .tn{min-width:22mm}
""" if WITH_EXT else ""

appendix_html = md2html(appendix_md)[0] if appendix_md else ""
APPX_TITLES = [t.split("　", 1)[-1].strip() for t in re.findall(r"^# (附錄.+)$", appendix_md, re.M)]


def opener(c, page_left_label):
    n, m = c["n"], meta[c["n"]]
    num = "EPILOGUE" if n == 21 else f"CHAPTER {n:02d}"
    chips = []
    for r in m["route"]:
        cls = "chip case" if r.startswith("Case") else "chip"
        chips.append(f'<span class="{cls}">{html.escape(r)}</span>')
    chips = '<span class="arr">→</span>'.join(chips)
    cases = "".join(
        f'<div><b>CASE {int(re.match(r"Case (\d+)", cs).group(1)):02d}</b>{html.escape(cs.split("｜", 1)[1])}</div>'
        for cs in m["cases"])
    goals = "".join("<li>" + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(g)) + "</li>" for g in c["goals"])
    run = f"第 {n} 章　{m['title']}" if n != 21 else "結語"
    return f"""
<div class="op op-l" id="op{n}">
  <div class="bignum">{n:02d}</div>
  <svg class="bg" viewBox="0 0 210 297" preserveAspectRatio="none"><path d="M-10 270 C 60 240, 150 250, 230 214" fill="none" stroke="#35C6FF" stroke-opacity=".25" stroke-width=".35"/></svg>
  <div class="num">{num}</div>
  <h1 class="t{' long' if max(len(x) for x in re.split('<br>', br_title(m['title']))) > 14 else ''}">{br_title(m['title'])}</h1>
  <div class="q"><div class="bar"></div><div class="k">核心問題</div><p>{html.escape(m['q'])}</p></div>
  <div class="run">{html.escape(run)}</div>
  {left_photo(n)}
</div>
<div class="op op-r">
  {visual(n)}
  <div class="flow">
    <div><div class="k2">LEARNING GOALS　學習目標</div><ol class="goals">{goals}</ol></div>
    <div><div class="k2">ROUTE　本章路線</div><div class="chips">{chips}</div></div>
    {f'<div class="casebox">{cases}</div>' if cases else ''}
  </div>
</div>"""


def build(toc_pages, pads=frozenset()):
    toc = "".join(
        f'<li><span class="tn">{"結語" if c["n"] == 21 else f"第 {c["n"]} 章"}</span>'
        f'<span class="tt">{html.escape(meta[c["n"]]["title"]) if c["n"] != 21 else ""}</span>'
        f'<span class="dots"></span><span class="tp">{toc_pages.get(c["n"], "")}</span></li>'
        for c in chapters) + "".join(
        f'<li class="ext"><span class="tn">{"延伸模擬篇" if k == "part" else f"延伸篇 {k}"}</span>'
        f'<span class="tt">{"" if k == "part" else html.escape(EXT_META[k]["title"])}</span>'
        f'<span class="dots"></span><span class="tp">{toc_pages.get(k, "")}</span></li>'
        for k in (["part"] + EXT_KEYS if EXT_KEYS else [])) + "".join(f'<li><span class="tn">附錄</span><span class="tt">{html.escape(t)}</span><span class="dots"></span><span class="tp">{toc_pages.get(f"appx{k}", "")}</span></li>' for k, t in enumerate(APPX_TITLES))
    named = []
    for c in chapters:
        n = c["n"]
        run = "結語" if n == 21 else f"第 {n} 章　{meta[n]['title']}"
        named.append(f'@page c{n}:right {{ @top-right {{ content: "{run}"; }} }}')
    sections = "".join(
        ('<div class="pad"></div>' if c["n"] in pads else "") + opener(c, "") + f'<section class="chap" style="page:c{c["n"]}">{c["html"]}</section>' for c in chapters)
    for idx, c in enumerate(ext_chapters):
        k = c["n"]
        named.append(f'@page c{k}:right {{ @top-right {{ content: "延伸篇 {k}　{EXT_META[k]["title"]}"; }} }}')
        # S1 的補頁放在篇名頁之前，讓篇名頁落在右頁、S1 章首左頁落在偶數頁
        sections += ('<div class="pad"></div>' if k in pads else "") + (ext_part(toc_pages) if idx == 0 else "") + \
            ext_opener(c) + f'<section class="chap" style="page:c{k}">{c["html"]}</section>'
    if appendix_html:
        sections += f'<section class="chap appx" style="page:capp">{appendix_html}</section>'
        named.append('@page capp:right { @top-right { content: "附錄"; } }')
    sections += LAST_PAGE
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
{f'<base href="{BOOKDIR.as_uri()}/">' if WITH_EXT else ""}<title>{TITLE}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Noto+Serif+TC:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script>
window.MathJax = {{ tex: {{ inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]] }},
  svg: {{ fontCache: "local" }},
  startup: {{ pageReady: () => MathJax.startup.defaultPageReady().then(() => document.fonts.ready).then(() => {{ document.body.dataset.ready = "1"; }}) }} }};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"></script>
<style>
:root{{--navy:#0B1F3A;--ink:#08101C;--cyan:#35C6FF;--cyan2:#7FD8FF;--amber:#FFB020;--teal:#35D6A4;--violet:#9B8CFF;--white:#F5F7FA;--gray:#C9D3DE;--text:#1A2230;--muted:#5A6676}}
@page {{ size: A4; margin: 22mm 21mm 24mm 21mm;
  @bottom-center {{ content: counter(page); font: 500 8.5pt "IBM Plex Mono"; color: #7A8696; }} }}
@page :left {{ @top-left {{ content: "{TITLE}"; font: 500 7.5pt "Noto Sans TC"; color: #8A96A6; letter-spacing: .1em; }} }}
@page :right {{ @top-right {{ font: 500 7.5pt "Noto Sans TC"; color: #8A96A6; letter-spacing: .05em; }} }}
{chr(10).join(named)}
@page dark {{ margin: 0; @bottom-center {{ content: none; }} @top-left {{ content: none; }} @top-right {{ content: none; }} }}
@page front {{ @bottom-center {{ content: none; }} @top-left {{ content: none; }} @top-right {{ content: none; }} }}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{font-family:"Noto Serif TC",serif;font-size:10.5pt;line-height:1.85;color:var(--text);-webkit-print-color-adjust:exact;print-color-adjust:exact}}

/* 書名頁與目錄 */
.front{{page:front}}
.title-page{{height:250mm;display:flex;flex-direction:column;justify-content:center;break-after:page}}
.title-page .t{{font:900 30pt/1.3 "Noto Sans TC";color:var(--navy);letter-spacing:.03em}}
.title-page .rule{{width:24mm;height:2px;background:var(--cyan);margin:8mm 0}}
.title-page .s{{font:500 13pt/1.7 "Noto Sans TC";color:#2E4A6E}}
.title-page .a{{margin-top:30mm;font:400 11pt "Noto Sans TC";color:var(--muted)}}
.title-page .qrs{{margin-top:auto;display:grid;grid-template-columns:repeat(4,1fr);gap:4mm}}
.title-page .qr{{display:flex;flex-direction:column;align-items:center;text-align:center;border:.3mm solid #D5DCE4;border-radius:2mm;padding:2.5mm 1.5mm;text-decoration:none;color:var(--ink)}}
.title-page .qr svg{{width:26mm;height:26mm}}
.title-page .qr b{{font:700 7.6pt/1.3 "Noto Sans TC";margin-top:1.5mm;color:var(--navy)}}
.title-page .qr small{{font:400 5.4pt/1.3 "IBM Plex Mono",monospace;color:#5A6575;word-break:break-all;margin-top:1mm}}
.copyright{{break-after:page;height:250mm;display:flex;flex-direction:column;justify-content:flex-end;font:400 9pt/2 "Noto Sans TC";color:var(--muted)}}
.copyright b{{color:var(--text);font-weight:500;display:inline-block;min-width:22mm}}
.copyright .bt{{font:700 10.5pt "Noto Sans TC";color:var(--navy);margin-bottom:3mm}}
.toc h2{{font:900 22pt "Noto Sans TC";color:var(--navy);margin:0 0 10mm;border:0;padding:0}}
.toc h2::before{{display:none}}
.toc ol{{list-style:none;padding:0;margin:0}}
.toc li{{display:flex;align-items:baseline;gap:3mm;padding:2.1mm 0;border-bottom:1px solid #E3E8EF;font:500 11pt "Noto Sans TC"}}
.toc .tn{{font:600 9pt "IBM Plex Mono","Noto Sans TC";color:var(--cyan);min-width:16mm;letter-spacing:.05em}}
.toc .tt{{color:var(--text)}}
.toc .dots{{flex:1}}
.toc .tp{{font:500 9.5pt "IBM Plex Mono";color:var(--muted)}}

/* 章首跨頁 */
.op{{page:dark;width:210mm;height:297mm;position:relative;overflow:hidden;break-before:page;break-after:page;background:linear-gradient(170deg,var(--navy) 0%,var(--ink) 100%);color:var(--white);font-family:"Noto Sans TC",sans-serif}}
.pad{{page:front;break-before:page;height:5mm}}
.lastpage{{page:dark;width:210mm;height:297mm;position:relative;overflow:hidden;break-before:page;background:#000}}
.lastpage img{{width:100%;height:100%;object-fit:cover;display:block}}
.lastpage .lcap{{position:absolute;left:14mm;right:14mm;bottom:10mm;font:400 6.6pt/1.5 "Noto Sans TC";color:#D5DEE8;background:rgba(0,0,0,.45);padding:1mm 2.5mm}}
.op svg.bg{{position:absolute;inset:0;width:100%;height:100%}}
.op .num{{position:absolute;left:20mm;top:26mm;font:600 11pt "IBM Plex Mono";letter-spacing:.35em;color:var(--cyan)}}
.op .bignum{{position:absolute;right:-6mm;top:8mm;font:600 150pt/1 "IBM Plex Mono";color:rgba(53,198,255,.07)}}
.op h1.t{{position:absolute;left:20mm;right:20mm;top:40mm;margin:0;font:900 29pt/1.32 "Noto Sans TC";letter-spacing:.03em;color:var(--white)}}
.op h1.t.long{{font-size:24pt}}
.op ol.goals b{{color:var(--white);font-weight:600}}
.op .q{{position:absolute;left:20mm;right:28mm;top:122mm}}
.op .q .k{{font:600 9pt "IBM Plex Mono","Noto Sans TC";letter-spacing:.25em;color:var(--amber)}}
.op .q p{{margin:4mm 0 0;font:600 16.5pt/1.75 "Noto Serif TC";color:var(--white)}}
.op .q .bar{{position:absolute;left:-6mm;top:0;bottom:0;width:2px;background:var(--amber)}}
.op .run{{position:absolute;left:20mm;bottom:12mm;font:500 8pt "Noto Sans TC";color:rgba(201,211,222,.5);letter-spacing:.1em}}
.op svg.visual{{position:absolute;left:0;top:0;width:210mm;height:138mm}}
.op .lphoto{{position:absolute;left:20mm;width:150mm;top:170mm;z-index:2}}
.op .lphoto img{{width:150mm;display:block;border-radius:1.5mm;box-shadow:0 2mm 6mm rgba(0,0,0,.45)}}
.op .lphoto div{{margin-top:2mm;font:400 6.4pt/1.4 "Noto Sans TC";color:#AFC0D2}}
.op .vcredit{{position:absolute;right:10mm;top:126mm;max-width:186mm;font:400 6.4pt/1.4 "Noto Sans TC";color:#D5DEE8;background:rgba(6,12,22,.6);padding:.7mm 2.2mm;text-align:right;z-index:3}}
.op .flow{{position:absolute;left:18mm;right:18mm;top:136mm;bottom:14mm;display:flex;flex-direction:column;gap:6mm}}
.op .k2{{font:600 8.5pt "IBM Plex Mono","Noto Sans TC";letter-spacing:.2em;color:var(--cyan2);margin-bottom:2.6mm}}
.op ol.goals{{list-style:none;margin:0;padding:0;font:400 9.6pt/1.7 "Noto Serif TC";color:var(--gray);counter-reset:g}}
.op ol.goals li{{padding-left:7mm;text-indent:-7mm;margin:.6mm 0;counter-increment:g}}
.op ol.goals li::before{{content:counter(g, decimal-leading-zero);display:inline-block;width:7mm;text-indent:0;font:600 8.4pt "IBM Plex Mono";color:var(--cyan)}}
.op .chips{{display:flex;flex-wrap:wrap;gap:2mm 1.5mm;align-items:center;font:500 8.8pt "Noto Sans TC"}}
.op .chip{{padding:1.1mm 2.5mm;border:1px solid rgba(127,216,255,.5);border-radius:1mm;color:var(--white)}}
.op .chip.case{{border-color:var(--amber);color:var(--amber)}}
.op .arr{{color:var(--cyan);font-family:"IBM Plex Mono"}}
.op .casebox{{margin-top:auto;align-self:flex-end;width:118mm;padding:3.2mm 4mm;border-left:2px solid var(--amber);background:rgba(255,176,32,.06)}}
.op .casebox div{{font:400 8.8pt/1.6 "Noto Sans TC";color:var(--gray)}}
.op .casebox b{{font:600 8.6pt "IBM Plex Mono";color:var(--amber);margin-right:2.4mm}}

/* 內文 */
section.chap{{break-before:page}}
h2,h3,h4{{font-family:"Noto Sans TC",sans-serif;color:var(--navy);line-height:1.45;break-after:avoid}}
h2{{font-size:14.5pt;font-weight:700;margin:1.7em 0 .6em;padding-left:4mm;position:relative}}
h2::before{{content:"";position:absolute;left:0;top:.28em;bottom:.28em;width:1.4mm;background:var(--cyan)}}
section.chap > h2:first-child{{margin-top:0}}
h3{{font-size:11.8pt;font-weight:700;margin:1.3em 0 .4em}}
h4{{font-size:10.8pt;margin:1.1em 0 .3em}}
p{{margin:.5em 0;text-align:justify;orphans:2;widows:2}}
strong{{font-weight:700;color:#0E1A2B}}
a{{color:#1C5A99;text-decoration:none}}
ul,ol{{padding-left:1.6em;margin:.5em 0}}
li{{margin:.15em 0}}
blockquote{{margin:.9em 0;padding:.5em 1em;border-left:3px solid var(--cyan);background:#F1F7FC;color:#2B3A4E}}
table{{border-collapse:collapse;width:100%;margin:1em 0;font:400 8.8pt/1.55 "Noto Sans TC";break-inside:auto}}
th{{background:var(--navy);color:#fff;font-weight:500;text-align:left}}
th,td{{border:1px solid #CBD4DF;padding:1.4mm 2mm;vertical-align:top}}
tr:nth-child(even) td{{background:#F5F8FB}}
tr{{break-inside:avoid}}
code{{font-family:"IBM Plex Mono",Consolas,monospace;font-size:8.8pt;background:#EEF2F6;padding:0 1mm;border-radius:.6mm}}
pre{{background:#EEF2F6;padding:3mm;font-size:8.5pt;white-space:pre-wrap}}
hr{{border:none;border-top:1px solid #D5DCE4;margin:1.4em 0}}
mjx-container[display="true"]{{margin:.9em 0 !important;display:block;break-inside:avoid;page-break-inside:avoid}}
p:has(> mjx-container[display="true"]){{break-inside:avoid;margin:0}}
mjx-assistive-mml{{display:none !important}}
div.math{{break-inside:avoid;margin:.6em 0}}
blockquote.evidence{{border-left:3px solid var(--navy);background:#EEF3F9;padding:2.6mm 4.5mm;font:400 8.9pt/1.65 "Noto Sans TC";color:#24324A}}
blockquote.evidence p{{margin:.25em 0;text-align:left}}
blockquote.evidence p:first-child strong{{color:var(--navy);font-size:9.6pt}}
p.aside-h em{{font:400 7.6pt "Noto Sans TC";font-style:normal;color:#9A7A3A;margin-left:3mm}}
.appx h1{{font:900 20pt "Noto Sans TC";color:var(--navy);margin:0 0 6mm}}
.appx h1:not(:first-child){{break-before:page}}
p.fig{{text-align:center;margin:1.1em 0 .2em;break-inside:avoid;break-after:avoid}}
p.fig img{{max-width:100%;max-height:100mm}}
p.cap{{font:400 8.4pt/1.6 "Noto Sans TC";color:var(--muted);margin:.3em 4mm 1.3em;text-align:left;break-before:avoid}}
p.aside-h{{margin:1.4em 0 0;break-after:avoid}}
p.aside-h span{{display:inline-block;font:700 9pt "Noto Sans TC";color:#8A5A00;background:#FFF1D6;border-left:3px solid var(--amber);padding:.6mm 3mm}}
p.aside{{margin:0 0 1.3em;padding:2.4mm 4mm 2.6mm;border-left:3px solid var(--amber);background:#FFF9EE;font-size:9.8pt;line-height:1.8;color:#2C2A26}}
.notes{{margin-top:2em;padding-top:1em;border-top:1px solid #D5DCE4;font-size:8.4pt;line-height:1.65;color:#4A5565}}
.notes h2{{font-size:10.5pt;margin:1.2em 0 .5em}}
.notes li,.notes p{{word-break:normal;overflow-wrap:anywhere}}
.notes ul li{{padding-left:1.2em;text-indent:-1.2em;list-style:none}}
.notes ul{{padding-left:0}}
a.url{{color:#1B4F8A;text-decoration:none;font:500 .94em "IBM Plex Mono",monospace;white-space:nowrap}}
a.url::after{{content:"↗";font-size:.8em;margin-left:.15em}}
.appx a:not(.url){{color:#1B4F8A;text-decoration:none;border-bottom:.4pt solid #9FB3C8}}
p.spec{{font:400 8.9pt/1.7 "Noto Sans TC";color:#24324A;border-left:3px solid var(--teal,#35D6A4);background:#F1F8F5;padding:1.6mm 4.5mm;text-align:left}}
p.spec strong{{color:#0F5E46}}
{EXT_CSS}</style></head><body>
<div class="front">
  <div class="title-page"><div class="t">{TITLE}</div><div class="rule"></div><div class="s">太空態勢感知的基礎——<br>智慧化低軌通訊衛星軌道異常與太空事件偵測演算法研究</div><div class="a">Sat_Dashboard<br><span style="font-size:9pt">{VERSION}　{DATE}</span></div>{QR_BLOCK}</div>
  <div class="copyright"><div class="bt">{TITLE}</div><div>{SUB}</div><br>
    <div><b>作者</b>Sat_Dashboard</div><div><b>版本</b>{VERSION}</div><div><b>日期</b>{DATE}</div>
    <div><b>版權</b>{DATE} {COPY}</div><div><b>授權</b>請來信洽詢</div><br><div><b>封面照片</b>NASA（iss036e024096），Expedition 36 國際太空站組員 Karen Nyberg 攝，2013-07-22 16:44:23 UTC，台灣夜間；取自 NASA Image and Video Library（images.nasa.gov）</div><div><b>封底照片</b>NASA（iss073e0848542），國際太空站組員油井龜美攝，2025-09-17 15:55:52 UTC，台灣海峽夜景</div><div><b>內頁照片</b>NASA、NASA/JPL、NASA/GSFC、NASA Ames Research Center 及 SpaceX（經 NASA 發布），出處與攝影者見各照片說明</div><div><b>最後一頁照片</b>Rocket Lab（經 NASA 發布，KSC-20240605-PH-RKL01_0002），Electron「PREFIRE and Ice」升空，2024-06-05，紐西蘭馬希亞；取自 NASA Image and Video Library</div><div><b>第 14 章章首圖</b>NASA（S64-03507），Diagrams of Spacecraft Responses to Orbit Attitude Control Thrust，1964；取自 NASA Image and Video Library，本書反相並調色</div><div><b>第 15 章章首圖</b>NASA（S65-05399），Gemini Spacecraft – Maneuvering Control，1965；取自 NASA Image and Video Library，本書反相並調色</div><div><b>第 16 章章首圖</b>NASA Ames Research Center（ARC-1977-A77-0851），Voyager Saturn Mission Artwork，1977-07-06；取自 NASA Image and Video Library，裁去沖印白邊</div><div><b>結語章首左頁照片</b>國家太空中心（TASA）提供，三節式入軌火箭模型首度亮相（2023 台北國際航太暨國防工業展）；取自自由時報 2023-09-14 報導（記者吳柏軒）</div><div><b>結語章首照片</b>國家太空中心（TASA），「島脈 MARAHO」首次飛試任務團隊合影，2026-08-22，屏東旭海科研火箭發射場；取自 TASA 官網公告</div>{'<div><b>延伸模擬篇</b>配圖、模擬畫面與章首圖為本專案製作（Rust 單機版，2026-11-22）</div>' if WITH_EXT else ''}</div>
  <div class="toc"><h2>目錄</h2><ol>{toc}</ol></div>
</div>
{sections}
</body></html>"""


def render(pw, page_html, out_pdf, html_path):
    html_path.write_text(page_html, encoding="utf-8")
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page()
    pg.goto(html_path.as_uri(), wait_until="networkidle")
    pg.wait_for_selector("body[data-ready='1']", timeout=60000)
    pg.wait_for_timeout(500)
    katex = pg.locator("mjx-container").count()
    pg.pdf(path=str(out_pdf), prefer_css_page_size=True, print_background=True)
    b.close()
    return katex


def render_single(pw, src, out_pdf):
    b = pw.chromium.launch(channel="msedge")
    pg = b.new_page()
    pg.goto(src.as_uri(), wait_until="networkidle")
    pg.evaluate("document.fonts.ready")
    pg.add_style_tag(content="@page{size:A4;margin:0} body{padding:0!important;background:none!important;display:block!important}")
    pg.wait_for_timeout(400)
    pg.pdf(path=str(out_pdf), prefer_css_page_size=True, print_background=True)
    b.close()


def chapter_pages(pdf):
    doc = fitz.open(pdf)
    found = {}
    for i, p in enumerate(doc):
        t = p.get_text().replace(" ", "")
        for n in range(1, 22):
            key = "EPILOGUE" if n == 21 else f"CHAPTER{n:02d}"
            if n not in found and key in t:
                found[n] = i + 1
        for k in EXT_KEYS:
            if k not in found and f"EXTENSION{k}" in t:
                found[k] = i + 1
        for k, at in enumerate(APPX_TITLES):
            key = f"appx{k}"
            if key not in found and 21 in found and "附錄" in t and ("附錄" + at.replace(" ", "")) in t.replace("　", ""):
                found[key] = i + 1
    return found, doc.page_count


with sync_playwright() as pw:
    inner = TMP / "inner.pdf"
    # 第一輪：取得各章章首頁碼；第二輪：寫入目錄
    render(pw, build({}), inner, OUT_HTML)
    pages, total = chapter_pages(inner)
    # 章首左頁須落在偶數頁（跨頁）；Chromium 不支援 break-before:left，改為在需要處補一張空白頁
    pads, shift, target = set(), 0, {}
    for n in sorted(k for k in pages if isinstance(k, int)) + [k for k in EXT_KEYS if k in pages]:
        if (pages[n] + shift) % 2:
            pads.add(n)
            shift += 1
        target[n] = pages[n] + shift
    pads = frozenset(pads)
    if EXT_KEYS:
        target["part"] = target[EXT_KEYS[0]] - 1   # 篇名頁緊接在 S1 章首之前
    katex = render(pw, build(target, pads), inner, OUT_HTML)
    pages2, total2 = chapter_pages(inner)
    if any(isinstance(k, str) for k in pages2):
        target.update({k: v for k, v in pages2.items() if isinstance(k, str)})
        render(pw, build(target, pads), inner, OUT_HTML)
    cover_src = D / "cover_A_v3.html"
    if not (D / "img" / "cover_mid.jpg").exists():
        print("警告：缺封面中段照片 design/img/cover_mid.jpg，本次暫用 cover_A_v2（作者名已另行更正）")
        cover_src = D / "cover_A_v2.html"
    render_single(pw, cover_src, TMP / "cover.pdf")
    render_single(pw, D / "back_v3.html", TMP / "back.pdf")

out = fitz.open()
for f in ["cover.pdf", "inner.pdf", "back.pdf"]:
    d = fitz.open(TMP / f)
    if f != "inner.pdf":
        assert d.page_count == 1, (f, d.page_count)
    out.insert_pdf(d)
out.set_metadata({"title": f"{TITLE}：{SUB}", "author": "Sat_Dashboard", "subject": "太空態勢感知"})
toc = [[1, "封面", 1], [1, "目錄", 4]] + [[1, ("結語" if n == 21 else f"第 {n} 章　{meta[n]['title']}"), p + 1] for n, p in sorted((k, v) for k, v in pages2.items() if isinstance(k, int))] + ([[1, "延伸模擬篇", pages2[EXT_KEYS[0]]]] if EXT_KEYS else []) + [[1, f"延伸篇 {k}　{EXT_META[k]['title']}", pages2[k] + 1] for k in EXT_KEYS] + [[1, f"附錄　{t}", pages2[f"appx{k}"] + 1] for k, t in enumerate(APPX_TITLES) if f"appx{k}" in pages2] + [[1, "封底", out.page_count]]
out.set_toc(toc)
out.save(OUT_PDF, garbage=3, deflate=True)

print(f"章數 {len(chapters)}；公式保護 {n_math} 處；MathJax SVG 排出 {katex} 處")
print("學習目標條數／插敘樣式套用：", "；".join(f"{n}:{g}/{a}" for n, g, a in stats))
print(f"插敘套用合計 {sum(a for _, _, a in stats)}；超連結 {N_LINKS[0]} 個；資料規格行 {sum(c['html'].count('class=\"spec\"') for c in chapters)} 個")
print(f"章首頁碼（內頁）第一輪 {pages}")
print(f"補空白頁於第 {sorted(map(str, pads))} 章之前；第二輪 {pages2}；與預計一致 {all(pages2.get(k) == v for k, v in target.items() if k != 'part')}")
left_ok = all(p % 2 == 0 for k, p in pages2.items() if isinstance(k, int) or k in EXT_KEYS)
print(f"章首左頁皆在偶數頁（跨頁成立）：{left_ok}")
print(f"內頁 {total2} 頁；含封面封底共 {out.page_count} 頁")
print(f"PDF：{OUT_PDF}（{OUT_PDF.stat().st_size:,} 位元組）")

# 延伸篇單篇 PDF：封面、扉頁、版權頁＋該篇＋封底（同 social/_book_pages.py 的單章作法）
if EXT_KEYS:
    full = fitz.open(OUT_PDF)
    starts = [pages2[k] for k in EXT_KEYS] + [min(v for k, v in pages2.items() if str(k).startswith("appx"))]
    for k, a, nxt in zip(EXT_KEYS, starts, starts[1:]):
        b = nxt - 1                    # 內頁頁碼 = 合併檔索引（封面在索引 0）
        while b > a and not full[b].get_text().strip() and not full[b].get_images():
            b -= 1
        one = fitz.open()
        one.insert_pdf(full, from_page=0, to_page=2)
        one.insert_pdf(full, from_page=a, to_page=b)
        one.insert_pdf(full, from_page=full.page_count - 1, to_page=full.page_count - 1)
        title = f"延伸篇 {k}　{EXT_META[k]['title']}"
        one.set_toc([[1, "封面", 1], [1, "扉頁", 2], [1, "版權頁", 3], [1, title, 4], [1, "封底", one.page_count]])
        one.set_metadata({"title": f"{TITLE}｜{title}（單篇試閱）", "author": "Sat_Dashboard", "subject": "太空態勢感知"})
        name = OUT_PDF.parent / f"延伸篇{k}_{re.sub(r'[：，、]', '', EXT_META[k]['title'])}_單篇.pdf"
        one.save(name, garbage=3, deflate=True)
        print(f"{name.name}：{one.page_count} 頁（該篇 {b - a + 1} 頁，全書第 {a}–{b} 頁），{name.stat().st_size / 1e6:.1f} MB")
