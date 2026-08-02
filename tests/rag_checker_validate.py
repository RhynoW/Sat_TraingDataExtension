#!/usr/bin/env python3
"""rag_checker_validate.py — rag_answer_check 精確度回歸驗證
==========================================================
用歷次測試留下的「真實 RAG 答案文本」當標註集，比較檢查器改動前後的旗標變化。

標註集：
  * 歷史真誤判（must-flag / TP）：65545、53451、44343 —— RAG 確實對負 Δa 判「軌道抬升」。
  * 其餘負 Δa 答案：以人工複核基準，正確否定抬升者不應被旗標（FP）。

用法：python tests/rag_checker_validate.py
離線純文字比對，不需 SSA-RAG 服務。
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_answer_check import claims_raising_in_conclusion, sign_conflict  # noqa: E402

# 歷史真誤判（記憶：每次擴充否定詞表須回抓驗證 3/3）
MUST_FLAG = {65545, 53451, 44343}

HIST_GLOBS = [
    "prc_maneuver/output/prc_rag_test_10events*.csv",
    "docs/rag_test_july_10sat_*.csv",
    "docs/rag_test_100sat_all.csv",
]


def load_corpus() -> pd.DataFrame:
    rows = []
    for g in HIST_GLOBS:
        for f in sorted(glob.glob(g)):
            try:
                d = pd.read_csv(f)
            except Exception:
                continue
            nid = "norad_id" if "norad_id" in d.columns else (
                "norad" if "norad" in d.columns else None)
            da = "da_km" if "da_km" in d.columns else (
                "net_da_km" if "net_da_km" in d.columns else None)
            if nid is None or da is None or "answer" not in d.columns:
                continue
            for _, r in d.iterrows():
                ans = str(r["answer"])
                if not ans or ans.startswith("ERR:"):
                    continue
                rows.append({"src": Path(f).name, "norad": int(r[nid]),
                             "da_km": float(r[da]), "answer": ans})
    return pd.DataFrame(rows)


def main():
    df = load_corpus()
    neg = df[df["da_km"] < 0].copy()
    print(f"語料：{len(df)} 筆答案（來源 {df['src'].nunique()} 檔），其中負 Δa {len(neg)} 筆\n")

    neg["flag"] = [sign_conflict(a, d) for a, d in zip(neg["answer"], neg["da_km"])]
    flagged = neg[neg["flag"]]

    print(f"目前檢查器旗標：{len(flagged)} / {len(neg)} 負向樣本")
    hit = {int(n) for n in flagged["norad"]} & MUST_FLAG
    print(f"歷史真誤判回抓（must-flag {sorted(MUST_FLAG)}）：{len(hit)}/{len(MUST_FLAG)} "
          f"→ {'PASS' if hit == MUST_FLAG else 'FAIL 缺 ' + str(sorted(MUST_FLAG - hit))}")

    print("\n--- 被旗標的樣本（need adjudication）---")
    for _, r in flagged.iterrows():
        tag = "TP(歷史真誤判)" if r["norad"] in MUST_FLAG else "?"
        print(f"[{tag}] {r['src']} NORAD {r['norad']} Δa={r['da_km']:+.3f}")
        print(f"    {r['answer'][:180]}...")

    ok = hit == MUST_FLAG
    print("\n" + "=" * 60)
    print(f"結果：must-flag {'PASS' if ok else 'FAIL'}；旗標總數 {len(flagged)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
