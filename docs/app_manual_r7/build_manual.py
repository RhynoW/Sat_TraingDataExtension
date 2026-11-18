"""App 操作手冊（期末 R7 版）：Markdown → TASA 格式 DOCX → Word 更新目錄並匯出 PDF。

用法：python docs/app_manual_r7/build_manual.py
需 Windows＋Microsoft Word（pywin32）。截圖由 capture_manual.py 產生於 shots/。
"""
import subprocess
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[2]
MD = ROOT / "docs/App操作手冊_機動偵測儀表板_期末R7版_20261118.md"
OUT = ROOT / "output/final_word/App操作手冊_FIN-RPT-03_20261118.docx"
PY = sys.executable

subprocess.run([PY, str(ROOT / "docs/md_to_docx_tasa.py"), "convert", str(MD), str(OUT), "FIN-RPT-03",
                "App 操作手冊：機動偵測儀表板（R7）",
                "期末 R7 版：P3 停用、ΔΩ 移除、證據等級與低置信複核項更新、新增專書線上版", "All."], check=True)
# 變更紀錄表第一列：轉檔工具固定寫「期末報告初版」，改為本手冊之初版（2026-09-09）
d = Document(str(OUT))
for row in d.tables[0].rows:
    for c in row.cells:
        for p in c.paragraphs:
            for r in p.runs:
                if "期末報告初版" in r.text:
                    r.text = r.text.replace("期末報告初版", "App 操作手冊初版")
d.save(str(OUT))
subprocess.run([PY, str(ROOT / "docs/export_docx_pdf.py"), str(OUT)], check=True)
