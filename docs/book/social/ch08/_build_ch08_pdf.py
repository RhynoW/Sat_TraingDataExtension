"""第 8 章單章 PDF：自全書排版版 v1.3 取頁，不重新排版；頁界依章首標記判定（見 ../_book_pages.py）。

用法（repo 根目錄）：python docs/book/social/ch08/_build_ch08_pdf.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(8, "第 8 章　規則層：讓每一個警報都有理由", OUT / "第08章_規則層讓每一個警報都有理由_單章.pdf")
