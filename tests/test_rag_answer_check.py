#!/usr/bin/env python3
"""test_rag_answer_check.py — rag_answer_check v4 結構化判定的單元回歸
====================================================================
重點在「泛化」：v3 以前靠否定片語表，每遇新變體就漏接（不屬於／並未／不支援
三次實測才補齊）。v4 改以句構判定（否定助詞為封閉集合＋子句作用域＋後綴反轉），
故下列「從未出現在任何詞表」的說法也應正確處理。

用法：python tests/test_rag_answer_check.py   （exit 0=PASS）
離線純文字，不需 SSA-RAG 服務。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_answer_check import (phrasing_warning, sign_conflict,  # noqa: E402
                              verdict_types)

NEG = -5.0      # 負 Δa
POS = +5.0

# (文字, 預期 sign_conflict, 說明)
CASES = [
    # ── 真肯定：必須抓到（歷史真誤判的句型）──────────────────────────
    ("因此，這最可能是軌道抬升", True, "直述肯定"),
    ("綜合以上，判定為軌道抬升機動", True, "判定為＋型別"),
    ("這最可能是 **軌道抬升** 的結果", True, "markdown 強調（44343 型）"),
    ("因此，最有可能的情況是軌道維持或軌道抬升", True, "選言主張含抬升（28738 型）"),

    # ── 否定片語變體：v3 詞表沒有的說法，v4 應靠助詞結構擋下 ──────────
    ("因此本次機動不屬於軌道抬升或離軌", False, "不屬於（47800 實測）"),
    ("此結果表明衛星並未進行顯著的軌道抬升", False, "並未（65424 實測）"),
    ("因此，這種模式不支援軌道抬升、避碰或離軌", False, "不支援（26464 實測）"),
    ("因此，本次機動絕非軌道抬升", False, "絕非（新變體）"),
    ("綜合判斷，這無法歸類為軌道抬升", False, "無法歸類為（新變體）"),
    ("結論：此模式尚未構成軌道抬升", False, "尚未構成（新變體）"),
    ("因此可以否決軌道抬升的可能", False, "否決（新變體）"),

    # ── 後綴反轉：否定出現在型別詞之後 ────────────────────────────────
    ("這最可能是軌道抬升（OrbitRaising）的反向操作，即軌道降低", False,
     "後綴反向＋英文註記括號（52908 實測）"),
    ("這最可能是軌道維持或軌道抬升之外的一種機動", False, "後綴之外（65261 實測）"),
    ("判定為軌道抬升以外的機動型別", False, "後綴以外"),
    ("這最可能是軌道抬升的逆操作", False, "後綴逆操作"),

    # ── 長距否定：助詞在子句前段，固定字數回看搆不到 ──────────────────
    ("資料中沒有其他指標表明這是軌道維持、軌道抬升或平面變換", False,
     "沒有…表明（63523 實測，子句作用域）"),

    # ── 先並列後定案：同句內最後一次提及才是立場 ──────────────────────
    ("這最可能是軌道維持或軌道抬升，因此更有可能是軌道維持而非軌道抬升", False,
     "先並列後否定（53452 實測）"),

    # ── 純敘述提及：非判定，不應觸發 ──────────────────────────────────
    ("軌道抬升通常會使半長軸增加", False, "衛教式敘述，無判定動詞"),
]

# phrasing_warning：判定另有其詞，但結論句仍以括號註記提及抬升
PHRASING_CASES = [
    ("這種模式最可能對應軌道維持（軌道抬升）", True, "括號註記（49503 實測）"),
    ("最可能對應軌道維持（軌道維持／軌道抬升）", True, "括號列舉（31306 實測）"),
    ("因此，這最可能是軌道抬升", False, "本身即判定抬升 → 屬 sign_conflict 非 warning"),
]


def main() -> int:
    fails = []
    print("=== sign_conflict（Δa < 0）===")
    for text, expect, note in CASES:
        got = sign_conflict(text, NEG)
        ok = got == expect
        fails.append((note, text)) if not ok else None
        print(f"  [{'PASS' if ok else 'FAIL'}] 預期={str(expect):5} 實得={str(got):5} · {note}")

    print("\n=== 正 Δa 不應觸發 ===")
    for text, _, note in CASES[:4]:
        got = sign_conflict(text, POS)
        ok = got is False
        fails.append((f"正Δa:{note}", text)) if not ok else None
        print(f"  [{'PASS' if ok else 'FAIL'}] 實得={got} · {note}")

    print("\n=== phrasing_warning（措辭矛盾，非方向錯誤）===")
    for text, expect, note in PHRASING_CASES:
        got = phrasing_warning(text, NEG)
        ok = got == expect
        fails.append((f"warning:{note}", text)) if not ok else None
        print(f"  [{'PASS' if ok else 'FAIL'}] 預期={str(expect):5} 實得={str(got):5} · {note}")

    print("\n" + "=" * 62)
    if fails:
        print(f"FAIL：{len(fails)} 項")
        for note, text in fails:
            print(f"  - {note}：{text}")
        return 1
    total = len(CASES) + 4 + len(PHRASING_CASES)
    print(f"PASS：全部 {total} 項")
    return 0


if __name__ == "__main__":
    sys.exit(main())
