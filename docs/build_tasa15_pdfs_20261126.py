"""build_tasa15_pdfs_20261126.py — TASA 15 星逐星 F1、F2 PDF 報表，以 2026-11-26 補齊 TLE 後之資料重產（30 份）。

期間同 docs/build_r15_backfill_json.py：max(2024-01-01, 首筆 TLE) 至 min(2026-11-14, 末筆 TLE)。
不呼叫 SSA-RAG（與原交付版相同，無 AI 解說段落）；QR code 為線上儀表板重新產製之參數網址。
輸出：output/pdf_15sats_R7_20261126/<NORAD>_<名稱>_<起日>-<迄日>_<F1|F2>.pdf；原交付版 output/pdf_1030test_15sats_R7/ 保留。
用法：python docs/build_tasa15_pdfs_20261126.py
"""
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
sys.stdout.reconfigure(encoding="utf-8")
import maneuver_report_builder as rb  # noqa: E402
from compare_app_vs_delivery import DELIV  # noqa: E402

APP_URL = "https://rhynowu-maneuver-detection-i18n.hf.space"
OUT = ROOT / "output/pdf_15sats_R7_20261126"
SINCE, END = date(2024, 1, 1), date(2026, 11, 14)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for nid in DELIV:
        tle = rb.load_tle(nid)
        d0, d1 = max(SINCE, tle.epoch.min().date()), min(END, tle.epoch.max().date())
        r = rb.build_report_data(nid, d0, d1, with_ai=False, with_external=True)
        name = str(r.get("name") or nid).replace(" ", "_")
        for fmt in ("F1", "F2"):
            url = f"{APP_URL}/?mode=tool&norad={nid}&d0={d0}&d1={d1}&report={fmt}&lang=zh"
            pdf = rb.render_pdf(r, fmt=fmt, source_url=url, app_url=f"{APP_URL}/?mode=tool&norad={nid}&d0={d0}&d1={d1}&lang=zh")
            f = OUT / f"{nid}_{name}_{d0:%Y%m%d}-{d1:%Y%m%d}_{fmt}.pdf"
            f.write_bytes(pdf)
            print(f.name, len(pdf) // 1024, "KB", flush=True)


if __name__ == "__main__":
    main()
