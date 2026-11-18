"""練習 6：以程式產出 F1 摘要版與 F2 技術完整版 PDF 報表（需網路）

學習目標
1. 了解 App「產出 PDF 報告」背後之呼叫：build_report_data() → render_pdf()。
2. 能以批次方式為多顆衛星產製報表（App 介面為逐顆查詢）。

執行：python training/ex06_pdf_report.py [NORAD ...]
預設：ICEYE-X33（60548），2026-03-01 至今日；輸出於 training/output/
"""
import sys
from datetime import date

import _common

rb = _common.load_builder()
norads = [int(x) for x in sys.argv[1:]] or [60548]
d0, d1 = date(2026, 3, 1), date.today()

for norad in norads:
    r = rb.build_report_data(norad, d0, d1, with_ai=False, with_external=False)
    print(f"{r['name']}（{norad}）：候選事件 {len(r['events'])} 件，等級 {r['counts']['grades']}")
    for fmt in ("F1", "F2"):
        pdf = rb.render_pdf(r, fmt=fmt)
        out = _common.OUT / f"report_{norad}_{fmt}.pdf"
        out.write_bytes(pdf)
        print(f"   {fmt} → {out.relative_to(_common.ROOT)}（{len(pdf)/1024:.0f} KB）")
