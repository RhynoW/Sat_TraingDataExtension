"""第 11 章單章 PDF：自全書排版版 v1.3 取頁，不重新排版；頁界依章首標記判定（見 ../_book_pages.py）。

用法（repo 根目錄）：python docs/book/social/ch11/_build_ch11_pdf.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(11, "第 11 章　物理作為第三方證人：NRLMSIS 與阻力殘差", OUT / "第11章_物理作為第三方證人NRLMSIS與阻力殘差_單章.pdf")
