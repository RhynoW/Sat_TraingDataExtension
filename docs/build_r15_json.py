# -*- coding: utf-8 -*-
"""build_r15_json.py — 產生 TASA 15 星之 r15.json（maneuver_report_builder.build_report_data 輸出）。

供 build_tasa15_ppt.py（圖 19 時間軸）與 gen_fig_tasa15_detect_vs_alt.py（圖 21 偵測能力）使用。
以交付當時之資料重建時，先以 LOCAL_DB_PATH 指向只含 2026-11-15 13:50 UTC 前下載之 TLE 之資料庫
（見 docs/compare_app_vs_delivery.py 與期末報告 10.6 節）：
  set LOCAL_DB_PATH=<deliv_state.duckdb>
  python docs/build_r15_json.py data/benchmark/tasa15_r7_delivery/r15.json 2026-11-14
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
import pandas as pd  # noqa: E402

import maneuver_report_builder as rb  # noqa: E402
from compare_app_vs_delivery import DELIV  # noqa: E402

DROP = {"tle_df", "l2_raw", "fusion_df", "drag_df", "tr_df"}


def clean(o):
    if isinstance(o, pd.DataFrame):
        return None
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            return o.item()
        except Exception:
            pass
    if isinstance(o, (pd.Timestamp, date)):
        return str(o)
    if isinstance(o, float) and o != o:
        return None
    return o


def main():
    out, end = Path(sys.argv[1]), date.fromisoformat(sys.argv[2])
    R = {}
    for nid, spec in DELIV.items():
        r = rb.build_report_data(nid, date.fromisoformat(spec[0]), end, with_ai=False, with_external=True)
        R[str(nid)] = clean({k: v for k, v in r.items() if k not in DROP})
        print(nid, r.get("name"), len(r.get("events") or []), len(r.get("low_conf") or []), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(R, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    print("→", out, "；分析流程", rb._pipeline_version(), "；資料", rb.DB_PATH)


if __name__ == "__main__":
    main()
