#!/usr/bin/env python3
# 用法：python docs/export_pptx_pdf.py <deck.pptx> <out.pdf> <slide_png_dir>（需 Windows＋PowerPoint）
"""PowerPoint 匯出 PDF＋逐頁 PNG；若 PDF 遺失 PPTX 內的超連結（表格儲存格常見），依文字位置補回連結註記。"""
import sys, os, re, zipfile, win32com.client, pythoncom
import pymupdf as fitz
src, pdf, imgdir = map(os.path.abspath, sys.argv[1:4])
os.makedirs(imgdir, exist_ok=True)
pythoncom.CoInitialize()
app = win32com.client.DispatchEx("PowerPoint.Application")
pres = app.Presentations.Open(src, ReadOnly=True, Untitled=False, WithWindow=False)
pres.SaveAs(pdf, 32)  # ppSaveAsPDF（表格內超連結會遺失，下方補回）
for i in range(1, pres.Slides.Count + 1):
    pres.Slides(i).Export(os.path.join(imgdir, f"slide{i}.png"), "PNG", 1600, 900)
pres.Close(); app.Quit()

# 補連結：讀每頁 PPTX 的超連結（依出現順序）與其顯示文字，對應 PDF 同頁同文字之位置
z = zipfile.ZipFile(src)
doc = fitz.open(pdf); added = 0
for pno in range(doc.page_count):
    name = f"ppt/slides/slide{pno + 1}.xml"
    if name not in z.namelist():
        continue
    xml = z.read(name).decode("utf-8")
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*?Target="([^"]+)"',
                           z.read(f"ppt/slides/_rels/slide{pno + 1}.xml.rels").decode("utf-8")))
    links = re.findall(r'<a:r>(?:(?!</a:r>).)*?r:id="(rId\d+)"(?:(?!</a:r>).)*?<a:t>([^<]+)</a:t>', xml, re.S)
    page = doc[pno]
    have = {l.get("uri") for l in page.get_links()}
    pending = [(rels[rid].replace("&amp;", "&"), txt) for rid, txt in links
               if rels[rid].replace("&amp;", "&") not in have]
    mid = page.rect.width / 2
    for uri, txt in pending:
        # 錨點：網址中的 NORAD → 找到該 NORAD 所在之表格列，連結放在同列同側之顯示文字上
        m = re.search(r"norad=(\d+)", uri)
        key = re.sub(r"[^\w\s]+$", "", txt).strip()       # PDF 抽不出箭頭等符號 → 去尾符號再搜尋
        if not m:
            continue
        anchors = [h for h in page.search_for(m.group(1)) if h.y0 > 140]
        if not anchors:
            continue
        a = anchors[0]; cy = (a.y0 + a.y1) / 2
        cells = [h for h in page.search_for(key)
                 if abs((h.y0 + h.y1) / 2 - cy) < 9 and (h.x0 > mid) == (a.x0 > mid)]
        if not cells:
            continue
        r = fitz.Rect(cells[0])
        for h in cells[1:]:
            r |= h
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(r.x0, r.y0, r.x1 + 16, r.y1), "uri": uri})
        added += 1
doc.saveIncr() if added else None
print("exported", pdf, "| 補回連結", added)
