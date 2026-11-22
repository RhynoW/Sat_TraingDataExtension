"""第 14 章單章 PDF：自全書排版版 v1.3 取頁，不重新排版；頁界依章首標記判定（見 ../_book_pages.py）。

用法（repo 根目錄）：python docs/book/social/ch14/_build_ch14_pdf.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(14, "第 14 章　機動時刻偵測：不只知道「有」，還知道「何時」", OUT / "第14章_機動時刻偵測不只知道有還知道何時_單章.pdf")
