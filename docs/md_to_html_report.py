#!/usr/bin/env python3
"""期末報告 Markdown → 單一 HTML（圖片內嵌、目錄、KaTeX 公式；不改動來源 Markdown）。

用法：python docs/md_to_html_report.py docs/期末報告_20261115.md output/final_word/期末報告_FIN-RPT-01_20261115.html
字形與 PDF 一致：中文標楷體、西文 Times New Roman；公式以 KaTeX（CDN）排版，離線時顯示 LaTeX 原文。
"""
import base64
import html
import mimetypes
import re
import sys
from pathlib import Path

import markdown

src, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
text = src.read_text(encoding="utf-8")

# 公式先保護，避免 markdown 吃掉反斜線與底線
math = []


def keep(m):
    math.append(m.group(0))
    return f"@@MATH{len(math) - 1}@@"


text = re.sub(r"\$\$.*?\$\$", keep, text, flags=re.S)
text = re.sub(r"B\*(?!\*)", r"B\\*", text)

# 章節錨點與目錄（### 為章、#### 為節）
toc, n = [], 0


def anchor(m):
    global n
    n += 1
    level, title = len(m.group(1)), m.group(2).strip()
    toc.append((level, title, f"s{n}"))
    return f"{m.group(1)} {title} {{#s{n}}}"


text = re.sub(r"^(#{3,4}) (.+)$", anchor, text, flags=re.M)
body = markdown.markdown(text, extensions=["tables", "attr_list", "sane_lists", "fenced_code"])
for i, m in enumerate(math):
    body = body.replace(f"@@MATH{i}@@", html.escape(m, quote=False))


# 圖片內嵌（base64），圖說改為 figure／figcaption
def embed(m):
    alt, path = html.unescape(m.group(1)), m.group(2)
    f = (src.parent / path).resolve()
    if not f.exists():
        print("缺圖：", path)
        return m.group(0)
    mime = mimetypes.guess_type(f.name)[0] or "image/png"
    data = base64.b64encode(f.read_bytes()).decode()
    return (f'<figure><img src="data:{mime};base64,{data}" alt="{html.escape(alt)}" loading="lazy">'
            f"<figcaption>{html.escape(alt)}</figcaption></figure>")


body = re.sub(r'<p><img alt="([^"]*)" src="([^"]+)"\s*/?></p>', embed, body)
body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")

title = re.search(r"^# (.+)$", src.read_text(encoding="utf-8"), re.M).group(1)
toc_html = "\n".join(f'<li class="l{lv}"><a href="#{a}">{html.escape(t)}</a></li>' for lv, t, a in toc)

page = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}　期末報告</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{delimiters:[{{left:'$$',right:'$$',display:true}}],throwOnError:false}})"></script>
<style>
:root {{ --ink:#1f2937; --muted:#6b7280; --navy:#1e3a8a; --line:#d1d5db; --bg:#ffffff; --head:#eef2ff; }}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:"Times New Roman","DFKai-SB","BiauKai","標楷體",serif; font-size:17px; line-height:1.85; }}
.wrap {{ display:grid; grid-template-columns:280px minmax(0,1fr); max-width:1280px; margin:0 auto; }}
nav {{ position:sticky; top:0; height:100vh; overflow:auto; padding:24px 16px; border-right:1px solid var(--line); font-size:14px; }}
nav ul {{ list-style:none; padding:0; margin:0; }}
nav li.l4 {{ padding-left:1.2em; font-size:13px; }}
nav a {{ color:var(--ink); text-decoration:none; display:block; padding:2px 0; }}
nav a:hover {{ color:var(--navy); }}
main {{ padding:32px 48px 80px; min-width:0; }}
h1 {{ color:var(--navy); font-size:30px; margin:0 0 4px; }}
h2 {{ color:var(--navy); font-size:22px; margin:0 0 16px; }}
h3 {{ color:var(--navy); font-size:23px; border-bottom:2px solid var(--navy); padding-bottom:4px; margin-top:48px; }}
h4 {{ color:var(--navy); font-size:19px; margin-top:32px; }}
p {{ text-align:justify; }}
figure {{ margin:20px 0; text-align:center; }}
figure img {{ max-width:100%; height:auto; border:1px solid var(--line); }}
figcaption {{ font-size:14px; color:var(--muted); margin-top:6px; text-align:left; }}
.tw {{ overflow-x:auto; margin:12px 0 20px; }}
table {{ border-collapse:collapse; width:100%; font-size:15px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; vertical-align:top; }}
th {{ background:var(--head); }}
code {{ font-family:Consolas,monospace; font-size:0.9em; background:#f3f4f6; padding:0 3px; }}
blockquote {{ border-left:4px solid var(--navy); margin:16px 0; padding:4px 16px; background:#f8fafc; }}
hr {{ border:none; border-top:1px solid var(--line); margin:32px 0; }}
.katex-display {{ overflow-x:auto; overflow-y:hidden; }}
@media (max-width: 900px) {{
  .wrap {{ display:block; }}
  nav {{ position:static; height:auto; border-right:none; border-bottom:1px solid var(--line); }}
  main {{ padding:16px; }}
}}
@media print {{ nav {{ display:none; }} .wrap {{ display:block; }} }}
</style></head>
<body><div class="wrap">
<nav><strong>目錄</strong><ul>
{toc_html}
</ul></nav>
<main>
{body}
</main></div></body></html>
"""
out.write_text(page, encoding="utf-8")
print("HTML：", out, f"{out.stat().st_size / 1e6:.1f} MB", "章節", len(toc), "公式", len(math))
