"""第 3 章單章 PDF：直接從全書排版版取頁，不重新排版。

用法：python docs/book/social/ch03/_build_ch03_pdf.py
全書頁碼（1 起算）：1 封面、2 扉頁（四個 QR 碼）、3 版權頁、31–42 第 3 章、最後一頁封底。
"""
import sys
from pathlib import Path

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
src = pymupdf.open(ROOT / "docs/book/v1.0_送審版/全書_排版版_v1.2.pdf")
assert src.page_count == 250, "全書頁數已變，請重新確認頁界"
assert "C H A P T E R 0 3" in src[30].get_text(), "第 3 章起始頁已變"
assert "C H A P T E R 0 4" in src[42].get_text(), "第 4 章起始頁已變"
pdf = pymupdf.open()
for a, b in [(0, 2), (30, 41), (src.page_count - 1, src.page_count - 1)]:
    pdf.insert_pdf(src, from_page=a, to_page=b)
pdf.set_metadata({"title": "從衛星軌道論國家安全｜第 3 章　低軌巨型星座的世界（單章試閱）",
                  "author": "Sat_Dashboard", "subject": "太空態勢感知"})
pdf.set_toc([[1, "封面", 1], [1, "扉頁", 2], [1, "版權頁", 3],
             [1, "第 3 章　低軌巨型星座的世界", 4], [1, "封底", pdf.page_count]])
out = OUT / "第03章_低軌巨型星座的世界_單章.pdf"
pdf.save(out, garbage=3, deflate=True)
print(f"{out.name}：{pdf.page_count} 頁，{out.stat().st_size/1e6:.1f} MB")
