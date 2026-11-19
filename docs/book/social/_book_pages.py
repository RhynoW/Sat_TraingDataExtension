"""單章 PDF 共用：自全書排版版取頁，頁界依章首標記判定，不寫死頁碼。

全書排版版每章首頁有「C H A P T E R 0 N」標記（結語為 E P I L O G U E）；章末為章首跨頁所補的空白頁時不取。
"""
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3]
BOOK_PDF = ROOT / "docs/book/v1.0_送審版/全書_排版版_v1.3.pdf"


def _mark(n: int) -> str:
    return "E P I L O G U E" if n == 21 else "C H A P T E R " + " ".join(f"{n:02d}")


def chapter_range(src: pymupdf.Document, n: int) -> tuple[int, int]:
    """第 n 章在全書中的頁界（0 起算，含頭尾）。"""
    start = next(i for i in range(src.page_count) if _mark(n) in src[i].get_text())
    nxt = next((i for i in range(start + 1, src.page_count) if _mark(n + 1) in src[i].get_text()), src.page_count - 1)
    end = nxt - 1
    while not src[end].get_text().strip() and not src[end].get_images():
        end -= 1
    return start, end


def build_single(n: int, title: str, out: Path) -> pymupdf.Document:
    """封面、扉頁、版權頁＋第 n 章＋封底，存成單章 PDF。"""
    src = pymupdf.open(BOOK_PDF)
    a, b = chapter_range(src, n)
    pdf = pymupdf.open()
    for x, y in [(0, 2), (a, b), (src.page_count - 1, src.page_count - 1)]:
        pdf.insert_pdf(src, from_page=x, to_page=y)
    pdf.set_metadata({"title": f"從衛星軌道論國家安全｜{title}（單章試閱）",
                      "author": "Sat_Dashboard", "subject": "太空態勢感知"})
    pdf.set_toc([[1, "封面", 1], [1, "扉頁", 2], [1, "版權頁", 3], [1, title, 4], [1, "封底", pdf.page_count]])
    pdf.save(out, garbage=3, deflate=True)
    print(f"{out.name}：{pdf.page_count} 頁（第 {n} 章 {b - a + 1} 頁，全書第 {a + 1}–{b + 1} 頁，"
          f"{BOOK_PDF.name}），{out.stat().st_size / 1e6:.1f} MB")
    return pdf
