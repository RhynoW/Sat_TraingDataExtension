"""build_r15_backfill_json.py — TASA 15 星 R7 結果，以 2026-11-26 補齊 TLE 後之資料、期間 2024-01-01 起重產。

期間：max(2024-01-01, 該星首筆 TLE) 至 min(2026-11-14, 該星末筆 TLE)；資料截止日同原交付（2026-11-14）。
原交付結果（data/benchmark/tasa15_r7_delivery/r15.json）保留不動。
用法：python docs/build_r15_backfill_json.py data/benchmark/tasa15_r7_backfill_20261126/r15.json 2026-11-14
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
os.environ.setdefault("SSA_RAG_TIMEOUT_S", "1")
import maneuver_report_builder as rb  # noqa: E402
from build_r15_json import DROP, clean  # noqa: E402
from compare_app_vs_delivery import DELIV  # noqa: E402

SINCE = date(2024, 1, 1)


def main():
    out, end = Path(sys.argv[1]), date.fromisoformat(sys.argv[2])
    R = {}
    for nid in DELIV:
        tle = rb.load_tle(nid)
        d0, d1 = max(SINCE, tle.epoch.min().date()), min(end, tle.epoch.max().date())
        r = rb.build_report_data(nid, d0, d1, with_ai=False, with_external=True)
        R[str(nid)] = clean({k: v for k, v in r.items() if k not in DROP})
        print(nid, r.get("name"), d0, d1, len(r.get("events") or []), r["counts"]["grades"], len(r.get("low_conf") or []), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(R, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    print("→", out, "；分析流程", rb._pipeline_version(), "；資料", rb.DB_PATH)


if __name__ == "__main__":
    main()
