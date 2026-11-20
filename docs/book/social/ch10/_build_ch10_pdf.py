"""第 10 章單章 PDF：自全書排版版 v1.3 取頁，不重新排版；頁界依章首標記判定（見 ../_book_pages.py）。

用法（repo 根目錄）：python docs/book/social/ch10/_build_ch10_pdf.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(10, "第 10 章　融合評分器：五個證人，一個信心分數", OUT / "第10章_融合評分器五個證人一個信心分數_單章.pdf")
