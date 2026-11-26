"""gen_fig_tasa15_timeline_backfill.py — 期末報告圖 19（15 顆衛星候選事件時間軸），以 2026-11-26 補齊 TLE 後之結果重產。

資料：data/benchmark/tasa15_r7_backfill_20261126/r15.json（docs/build_r15_backfill_json.py 產生）
分組依補齊後之結果調整（原交付簡報 build_tasa15_ppt.py 之 TYPES 不變，該簡報不重建）：
  A 軌道轉移型加入 TANAGER-1、PELICAN-4 300B（入軌後降至運作高度）；ICEYE-X33 補齊後無事件，移至 D；
  D 改稱「無 E1 以上事件」（HJS-9A、SKYSAT C12 只有 D 級）。
輸出：docs/fig_tasa15_timeline_r7.png
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))
import build_tasa15_ppt as b  # noqa: E402

b.TYPES = [
    ("A", "軌道轉移型", [64199, 62190, 58651, 60507, 65316]),
    ("B", "星系營運型", [53056, 59711]),
    ("C", "小幅調整型", [69018]),
    ("D", "無 E1 以上事件", [60548, 68831, 61871, 43081, 43797, 56193, 41634]),
]
b.build_timeline(b.load(str(ROOT / "data/benchmark/tasa15_r7_backfill_20261126/r15.json")))
print("→", b.FIG)
