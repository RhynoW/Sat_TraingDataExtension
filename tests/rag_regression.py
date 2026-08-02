#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SSA-RAG 回歸測試（CI 工具）。

對 5 筆已知問題案例（tests/rag_regression_cases.json，問題文字內嵌）重送原題，
檢查兩類已修復的 bug 是否復發：
  sign   —— 負 Δa 事件的結論句宣稱「軌道抬升」（Δa 符號推理短路）
  format —— 回答被後處理誤判為證據不足（insufficient=true 且 sources 清空）

用法：
    python tests/rag_regression.py                 # 跑全部案例，exit 0=通過 / 1=有回歸 / 2=服務不可用
    python tests/rag_regression.py --suite sign    # 只跑符號案例
    python tests/rag_regression.py --suite format  # 只跑格式案例
    python tests/rag_regression.py --notify        # 經 app_dialogue 信箱向 Server 通報逐筆進度
    python tests/rag_regression.py --interval 15   # 每筆間隔秒數（預設 2；連跑對 Server 負載小可用預設）

前置：SSA-RAG 服務需在 --base-url（預設 http://127.0.0.1:8000）運行。
歷史脈絡見 prc_maneuver/output/prc_rag_test_10events*.csv 與 *_regression_*.csv。
"""
import argparse
import json
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag_answer_check import sign_conflict          # noqa: E402
from ssa_rag_client import SSARAGClient             # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "rag_regression_cases.json"
CLIENT_ID = "maneuver_app_ci"


def load_cases(suite: str) -> list[dict]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if suite != "all":
        cases = [c for c in cases if suite in c["checks"]]
    return cases


def run(args) -> int:
    rag = SSARAGClient(base_url=args.base_url, timeout=args.timeout)
    if not rag.health():
        print(f"SKIP: SSA-RAG 服務不可用（{args.base_url}）")
        return 2

    notify = None
    if args.notify:
        try:
            from app_dialogue_client import DialogueClient
            notify = DialogueClient()
            notify.send(f"Client（CI）開始 RAG 回歸：suite={args.suite}，共 {len(load_cases(args.suite))} 筆。")
        except Exception as e:
            print(f"（信箱通報不可用，改為僅本地輸出：{e}）")

    cases = load_cases(args.suite)
    failures: list[str] = []

    for i, c in enumerate(cases, start=1):
        nid, name = c["norad_id"], c["sat_name"]
        print("=" * 64)
        print(f"[{i}/{len(cases)}] {name} (NORAD {nid}) checks={c['checks']} — {c['note']}")
        try:
            r = rag.ask(c["question"], topic="maneuver", client_id=CLIENT_ID)
        except Exception as e:
            msg = f"{nid} 查詢失敗：{type(e).__name__}: {e}"
            print(f"  FAIL  {msg}")
            failures.append(msg)
            continue

        case_fail = []
        if "sign" in c["checks"] and sign_conflict(r.answer, c["da_km"]):
            case_fail.append("sign：結論句仍宣稱軌道抬升（Δa<0）")
        if "format" in c["checks"] and r.insufficient and not r.sources:
            case_fail.append("format：被誤判為證據不足（insufficient=true, sources=0）")

        verdict = "FAIL  " + "；".join(case_fail) if case_fail else "PASS"
        print(f"  {verdict}（confidence={r.confidence}, sources={len(r.sources)}）")
        if args.verbose or case_fail:
            print("  --- answer ---")
            print("  " + r.answer.replace("\n", "\n  "))
        if case_fail:
            failures.append(f"{nid}（{name}）：" + "；".join(case_fail))
        if notify:
            notify.send(f"Client（CI）第 {i}/{len(cases)} 筆 NORAD {nid}：{'FAIL' if case_fail else 'PASS'}。")
        if i < len(cases) and args.interval > 0:
            time.sleep(args.interval)

    print("=" * 64)
    if failures:
        print(f"RESULT: FAIL（{len(failures)}/{len(cases)} 筆回歸）")
        for f in failures:
            print(f"  - {f}")
    else:
        print(f"RESULT: PASS（{len(cases)}/{len(cases)}）")
    if notify:
        notify.send(
            f"Client（CI）回歸結束：{'FAIL ' + str(len(failures)) + ' 筆' if failures else 'PASS 全數通過'}。#Over#"
        )
    return 1 if failures else 0


def main() -> None:
    p = argparse.ArgumentParser(description="SSA-RAG regression suite (CI)")
    p.add_argument("--suite", choices=["all", "sign", "format"], default="all")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--interval", type=float, default=2.0, help="每筆間隔秒數")
    p.add_argument("--notify", action="store_true", help="經 app_dialogue 信箱向 Server 通報")
    p.add_argument("--verbose", action="store_true", help="通過的案例也印出完整回答")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
