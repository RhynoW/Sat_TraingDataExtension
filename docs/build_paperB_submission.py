#!/usr/bin/env python3
"""build_paperB_submission.py — 論文 B（FS7 偵測器層級敏感度）投稿套件一鍵重建（Markdown → DOCX → PDF）

流程：
  1. 以 docs/md_to_docx.py 將正文、補充材料、投稿信、兩輪回覆信轉為 DOCX。
  2. 投稿信後處理：署名區段後距 0、上下邊界 2.0 cm（避免署名溢到第二頁）。
  3. 以 Word COM（pywin32）匯出 PDF，回報頁數。
  4. 檢核：摘要字數（ASR ≤ 250）、Highlights 字元數（Elsevier ≤ 85）、殘留占位文字。

用法：python docs/build_paperB_submission.py
輸出：output/paper_B_submission/<stem>.{docx,pdf}
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from docx import Document
from docx.shared import Cm

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "output" / "paper_B_submission"
ITEMS = {
    "paper_fs7_sensitivity_model_EN": "manuscript",
    "paper_fs7_supplement_EN": "supplement",
    "paper_fs7_cover_letter_EN": "letter",
    "paper_fs7_response_to_reviewers_R1": "response",
    "paper_fs7_response_to_reviewers_R2": "response",
}
LETTER_MARGIN_CM = 2.0
ABSTRACT_MAX_WORDS = 250
HIGHLIGHT_MAX_CHARS = 85


def to_docx(stem: str) -> Path:
    out = OUT / f"{stem}.docx"
    subprocess.run([sys.executable, str(DOCS / "md_to_docx.py"), str(DOCS / f"{stem}.md"), str(out), "en"],
                   check=True, cwd=DOCS)
    return out


def tidy_letter(path: Path) -> None:
    d = Document(path)
    paras = [p for p in d.paragraphs if p.text.strip()]
    i = next(k for k, p in enumerate(paras) if p.text.strip().startswith("Sincerely"))
    for p in paras[i:-1]:
        p.paragraph_format.space_after = 0
    for s in d.sections:
        s.top_margin = s.bottom_margin = Cm(LETTER_MARGIN_CM)
    d.save(path)


def to_pdf(paths: list[Path]) -> dict[str, int]:
    import win32com.client
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    pages = {}
    try:
        for p in paths:
            doc = word.Documents.Open(str(p), False, True)
            pages[p.stem] = doc.ComputeStatistics(2)
            doc.ExportAsFixedFormat(str(p.with_suffix(".pdf")), 17)
            doc.Close(False)
    finally:
        word.Quit()
    return pages


def checks() -> list[str]:
    msgs = []
    t = (DOCS / "paper_fs7_sensitivity_model_EN.md").read_text(encoding="utf-8")
    n = len(t.split("## Abstract")[1].split("**Keywords:**")[0].split())
    msgs.append(f"摘要 {n} 字（上限 {ABSTRACT_MAX_WORDS}）{'' if n <= ABSTRACT_MAX_WORDS else '  ← 超過'}")
    hl = [l[2:] for l in t.split("## Highlights")[1].split("---")[0].strip().splitlines() if l.startswith("- ")]
    for k, l in enumerate(hl, 1):
        msgs.append(f"Highlight {k}：{len(l)} 字元（上限 {HIGHLIGHT_MAX_CHARS}）{'' if len(l) <= HIGHLIGHT_MAX_CHARS else '  ← 超過'}")
    msgs.append(f"正文字數（含表格、參考文獻）：{len(t.split()):,}")
    for stem in ITEMS:
        s = (DOCS / f"{stem}.md").read_text(encoding="utf-8")
        ph = sorted(set(re.findall(r"\[[^\]\n]{0,80}?(?:to be|To be|Author|Name|Affiliation|Date|E-mail|DOI|e-mail|statement|tool name|address|roles)[^\]\n]{0,80}\]", s)))
        msgs.append(f"{stem}：占位文字 {len(ph)} 種" + ("" if not ph else "：" + "；".join(ph)))
    return msgs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for stem, kind in ITEMS.items():
        p = to_docx(stem)
        if kind == "letter":
            tidy_letter(p)
        paths.append(p)
    for stem, n in to_pdf(paths).items():
        print(f"  {stem}.pdf：{n} 頁" + ("  ← 附函超過 1 頁" if "cover_letter" in stem and n > 1 else ""))
    for m in checks():
        print("  " + m)


if __name__ == "__main__":
    main()
