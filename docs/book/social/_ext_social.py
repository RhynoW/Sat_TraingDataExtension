"""延伸模擬篇 LinkedIn 素材的共用工具：卡片繪製（1080×1350，版型同 ch01／S1）與全文文章版轉換。

render_cards(out_dir, prefix, cards)：cards 為 5 張卡的 HTML 片段（用 card_* 函式產生），輸出 PNG 與輪播 PDF。
article(md_path, out_path, header)：把延伸篇 Markdown 轉成可貼進 LinkedIn「撰寫文章」的純文字（表格轉條列、註腳轉 [n]、圖片轉【插圖】）。
"""
import base64
import re
from pathlib import Path

import pymupdf
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
IMG = ROOT / "docs/book/sim_chapters/img"
BOOK = "從衛星軌道論國家安全"
FULL_TITLE = "《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》"


def b64(name):
    p = IMG / name
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1350px;overflow:hidden;background:#08101C;color:#F5F7FA;font-family:"Noto Sans TC",sans-serif}
.card{position:relative;width:1080px;height:1350px;padding:96px 88px;background:linear-gradient(170deg,#0B1F3A 0%,#08101C 100%)}
.top{display:flex;justify-content:space-between;font:600 24px "IBM Plex Mono","Noto Sans TC",monospace;letter-spacing:.18em;color:#35C6FF}
.foot{position:absolute;left:88px;right:88px;bottom:72px;display:flex;justify-content:space-between;font-size:22px;color:#8A96A6}
h1{font-size:72px;font-weight:900;line-height:1.25;margin-top:40px}
h2{font-size:56px;font-weight:900;line-height:1.3;margin:56px 0 44px}
.bar{width:96px;height:6px;background:#35C6FF;margin-top:40px}
.row{display:flex;gap:36px;padding:26px 0;border-top:1px solid #23344E}
.row b{flex:0 0 230px;font-size:30px;font-weight:700;color:#FFB020;padding-top:4px;line-height:1.45}
.row span{font-size:31px;line-height:1.5;color:#E3E9F0}
.f{margin-top:36px;padding:28px 34px;border-left:6px solid #35C6FF;background:#0F2747;font-size:30px;line-height:1.55;font-weight:500}
.note{margin-top:22px;font-size:22px;color:#8A96A6;line-height:1.5}
.photo{position:absolute;inset:0;background-position:center;background-size:cover}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,16,28,.94) 0%,rgba(8,16,28,.45) 48%,rgba(8,16,28,.94) 93%,#08101C 96%)}
.q{font-size:40px;line-height:1.6;font-weight:500;margin-top:60px}
.credit{position:absolute;left:88px;right:88px;bottom:130px;font-size:20px;color:#C9D3DE}
.fig{background:#fff;border-radius:12px;padding:16px}
.fig img{width:100%;display:block}
.big{display:flex;gap:40px;margin:6px 0}
.big div{flex:1;padding:34px 30px;border-radius:14px;background:#0F2747}
.big b{display:block;font:700 108px "IBM Plex Mono",monospace;line-height:1.1}
.big span{font-size:28px;color:#C9D3DE;line-height:1.45;display:block;margin-top:8px}
.x{text-align:center;font-size:42px;font-weight:700;color:#FFB020;margin:26px 0 0}
"""
HEAD = ('<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?'
        'family=Noto+Sans+TC:wght@400;500;700;900&family=IBM+Plex+Mono:wght@500;600;700&display=swap" rel="stylesheet">'
        '<style>{css}</style></head><body>{body}</body></html>')


def _top(ch, n):
    return f'<div class="top"><span>{ch}</span><span>{n} / 5</span></div>'


FOOT = f'<div class="foot"><span>{BOOK}</span><span>©Sat_Dashboard</span></div>'


def card_cover(ch, img, title, q, credit):
    return (f'<div class="card"><div class="photo" style="background-image:url({b64(img)})"></div><div class="shade"></div>'
            f'<div style="position:relative">{_top(ch, 1)}<h1>{title}</h1><div class="bar"></div><div class="q">{q}</div></div>'
            f'<div class="credit">{credit}</div>{FOOT}</div>')


def card_rows(ch, n, h, rows, f, note=""):
    r = "".join(f'<div class="row"><b>{a}</b><span>{b}</span></div>' for a, b in rows)
    return (f'<div class="card">{_top(ch, n)}<h2>{h}</h2>{r}<div class="f">{f}</div>'
            f'{f"<div class=note>{note}</div>" if note else ""}{FOOT}</div>')


def card_fig(ch, n, h, img, f, note=""):
    return (f'<div class="card">{_top(ch, n)}<h2 style="margin-bottom:32px">{h}</h2><div class="fig"><img src="{b64(img)}"></div>'
            f'{f"<div class=note>{note}</div>" if note else ""}<div class="f">{f}</div>{FOOT}</div>')


def card_big(ch, n, h, a, b, x, f, note=""):
    """a、b 為 (數字, 說明, 顏色)。"""
    box = lambda v: f'<div><b style="color:{v[2]}">{v[0]}</b><span>{v[1]}</span></div>'
    return (f'<div class="card">{_top(ch, n)}<h2>{h}</h2><div class="big">{box(a)}{box(b)}</div>'
            f'<div class="x">{x}</div><div class="f">{f}</div>{f"<div class=note>{note}</div>" if note else ""}{FOOT}</div>')


def render_cards(out_dir: Path, prefix: str, cards):
    d = out_dir / "cards_zh"
    d.mkdir(parents=True, exist_ok=True)
    pngs = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        pg = br.new_page(viewport={"width": 1080, "height": 1350})
        for i, body in enumerate(cards, 1):
            pg.set_content(HEAD.format(css=CSS, body=body), wait_until="networkidle")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(300)
            f = d / f"{prefix}_zh_{i}.png"
            pg.screenshot(path=str(f))
            pngs.append(f)
        br.close()
    car = pymupdf.open()
    for f in pngs:  # LinkedIn「文件」輪播：每張卡一頁
        car.insert_pdf(pymupdf.open("pdf", pymupdf.open(f).convert_to_pdf()))
    car.save(out_dir / f"{prefix}_carousel_zh.pdf", garbage=3, deflate=True)
    return pngs


# ---------- 全文文章版 ----------
SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
# 註腳上標：前一字不是數字、英文字母、右括號或下標（避免動到 10⁹、(1/20)² 這類數學上標）
FOOTNOTE = re.compile(r"(?<![0-9A-Za-z\)₀-₉])([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")


def _inline(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = FOOTNOTE.sub(lambda m: f"[{m.group(1).translate(SUP)}]", s)
    return s.replace("[ ]", "").replace("] [", "][")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def article(md_path: Path, out_path: Path, header: str):
    lines = md_path.read_text(encoding="utf-8").split("\n")
    title = re.sub(r"^#\s*延伸篇 S\d　", "", lines[0]).strip()
    out = [f"標題：{title}", "", f"副標：{FULL_TITLE}{lines[0][2:].split('　')[0]}", ""]
    i = 1
    while i < len(lines):
        l = lines[i]
        if l.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = _cells(l)
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                c = _cells(lines[i])
                parts = [f"{h}：{v}" for h, v in zip(head[1:], c[1:]) if v]
                out.append(_inline(f"• {c[0]}｜" + "；".join(parts)))
                i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\((img/[^)]+)\)", l)
        if m:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            out.append(_inline(f"【插圖】{m.group(2)}　{lines[j].strip()}"))
            i = j + 1
            continue
        if l.startswith("## ") or l.startswith("### "):
            out.append(("▍" if l.startswith("## ") else "") + _inline(l.lstrip("# ").strip()))
        elif l.startswith("> "):
            out.append(_inline(l[2:]))
        elif l.startswith("- [ ] "):
            out.append("☐ " + _inline(l[6:]))
        elif l.startswith("- "):
            out.append("• " + _inline(l[2:]))
        else:
            out.append(_inline(l))
        i += 1
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    out_path.write_text(header + "\n---\n\n" + text, encoding="utf-8")
    return len(text)
