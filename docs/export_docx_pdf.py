#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_docx_pdf.py — 以 Word 開啟 md_to_docx_tasa.py 產出之 .docx，更新目錄／圖目錄／表目錄與頁碼等
功能變數後存回 .docx，並匯出 PDF。需 Windows＋Microsoft Word（pywin32）。

用法：python docs/export_docx_pdf.py <in.docx> [out.pdf]
"""
import os
import sys

import pythoncom
import win32com.client

src = os.path.abspath(sys.argv[1])
pdf = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".pdf"
pythoncom.CoInitialize()
w = win32com.client.DispatchEx("Word.Application")
w.Visible = False
w.DisplayAlerts = 0
try:
    d = w.Documents.Open(src, ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False,
                         Visible=False, OpenAndRepair=False, NoEncodingDialog=True)
    d.Fields.Update()
    for t in d.TablesOfContents:          # 目錄、圖目錄、表目錄皆為 TOC 欄位
        t.Update()
    for s in d.Sections:                  # 頁首頁尾之 PAGE／NUMPAGES
        for hf in list(s.Headers) + list(s.Footers):
            hf.Range.Fields.Update()
    d.Repaginate()
    d.Save()
    d.SaveAs2(pdf, FileFormat=17)         # wdFormatPDF
    print("pages", d.ComputeStatistics(2), "→", pdf)
    d.Close(False)
finally:
    w.Quit()
