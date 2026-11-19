"""第 6 章單章 PDF：自全書排版版 v1.3 取頁，不重新排版；頁界依章首標記判定（見 ../_book_pages.py）。

用法（repo 根目錄）：python docs/book/social/ch06/_build_ch06_pdf.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(6, "第 6 章　追蹤缺口、資料品質與假警報", OUT / "第06章_追蹤缺口資料品質與假警報_單章.pdf")
