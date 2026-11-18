# -*- coding: utf-8 -*-
"""compare_app_vs_delivery.py — 檢查「以 App 逐顆輸入」能否重現 TASA 15 星 R7 交付結果。

App 之 PDF 與頁面皆呼叫 maneuver_report_builder.build_report_data(norad, d0, d1)；差異只來自
資料來源（線上 HF Dataset 或本機 space_db.duckdb）與日期區間（App 預設為該星全部 TLE 範圍）。
資料來源須在 import 前以環境變數決定，故每種情境各跑一次：
  本機：python docs/compare_app_vs_delivery.py local  2026-11-14
  線上：set HF_DATASET_REPO=RhynoWu/starlink-maneuver-db && python docs/compare_app_vs_delivery.py hf 2026-11-14
        （結束日給 latest 表示 App 預設：該星最新 TLE 日期）
輸出：data/benchmark/app_vs_delivery/<tag>_<end>.csv
"""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
os.environ.setdefault("SSA_RAG_TIMEOUT_S", "1")
import pandas as pd  # noqa: E402

import maneuver_report_builder as rb  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 交付結果（期末報告表 21／TASA 回覆 Q4；TLE 資料至 2026-11-14）
DELIV = {  # norad: (起日, 事件數, E3, E2, E1, D, 複核項, 案件)
    64199: ("2025-05-29", 4, 1, 3, 0, 0, 0, 0), 62190: ("2024-12-04", 8, 1, 4, 3, 0, 92, 85),
    58651: ("2024-01-01", 4, 1, 2, 1, 0, 8, 6), 53056: ("2026-03-31", 3, 2, 0, 0, 1, 18, 16),
    59711: ("2026-04-01", 0, 0, 0, 0, 0, 3, 3), 69018: ("2026-05-08", 2, 0, 2, 0, 0, 13, 10),
    60548: ("2026-03-31", 1, 0, 1, 0, 0, 1, 1), 41634: ("2024-01-01", 0, 0, 0, 0, 0, 2, 2),
    68831: ("2026-04-24", 1, 0, 0, 0, 1, 8, 7), 61871: ("2024-11-09", 0, 0, 0, 0, 0, 6, 5),
    43081: ("2024-01-01", 0, 0, 0, 0, 0, 6, 6), 43797: ("2026-03-31", 0, 0, 0, 0, 0, 0, 0),
    56193: ("2026-04-01", 0, 0, 0, 0, 0, 0, 0), 60507: ("2026-04-01", 0, 0, 0, 0, 0, 4, 4),
    65316: ("2026-03-31", 0, 0, 0, 0, 0, 5, 4),
}


def main():
    tag, end = sys.argv[1], sys.argv[2]
    rows = []
    for nid, (d0, n, e3, e2, e1, dd, nlc, ncase) in DELIV.items():
        tle = rb.load_tle(nid)
        d1 = tle.epoch.max().date() if end == "latest" else date.fromisoformat(end)
        d0x = tle.epoch.min().date() if end == "latest" else date.fromisoformat(d0)
        # with_external=True 與 App 相同：本機編目查不到名稱時以 N2YO 補名，名稱決定是否視為 Starlink
        # （影響融合評分器項是否列入低置信複核項）
        r = rb.build_report_data(nid, d0x, d1, with_ai=False, with_external=True)
        ev, lc = r.get("events") or [], r.get("low_conf") or []
        g = lambda k: sum(str(e["grade"]).startswith(k) for e in ev)  # noqa: E731
        got = (len(ev), g("E3"), g("E2"), g("E1"), g("D"), len(lc), len({x.get("case") for x in lc}))
        rows.append(dict(norad=nid, name=r.get("name"), d0=str(d0x), d1=str(d1), n_tle=r.get("n_tle"),
                         ev=got[0], E3=got[1], E2=got[2], E1=got[3], D=got[4], lc=got[5], case=got[6],
                         deliv=f"{n}({e3}/{e2}/{e1}/{dd}) lc{nlc}/{ncase}",
                         same_events=got[:5] == (n, e3, e2, e1, dd), same_lc=got[5:] == (nlc, ncase),
                         events=" ; ".join(f"{e['t_start']:%Y-%m-%d} {e['net_da']:+.2f}km {e['grade']}" for e in ev),
                         pipeline=rb._pipeline_version(), backend=rb.DATA_BACKEND))
        print(rows[-1]["norad"], rows[-1]["n_tle"], got, rows[-1]["deliv"], rows[-1]["same_events"], rows[-1]["same_lc"],
              flush=True)
    out = ROOT / "data" / "benchmark" / "app_vs_delivery"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / f"{tag}_{end}.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
