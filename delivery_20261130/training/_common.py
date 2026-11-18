"""教育訓練練習共用設定：切換到交付包根目錄、加入匯入路徑、關閉冗長日誌與進度列。

所有練習請在交付包根目錄執行，例如：python training/ex02_threshold.py
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)

OUT = ROOT / "training" / "output"
OUT.mkdir(exist_ok=True)


def quiet_duckdb():
    """關閉 DuckDB 遠端讀取之進度列（HF 遠端資料來源時會大量輸出）。"""
    import duckdb
    if getattr(duckdb.connect, "_quiet", False):
        return
    _orig = duckdb.connect

    def _connect(*a, **k):
        con = _orig(*a, **k)
        try:
            con.execute("SET enable_progress_bar=false")
        except Exception:
            pass
        return con
    _connect._quiet = True
    duckdb.connect = _connect


def load_builder():
    """匯入 R7 報表模組。未設資料來源時，使用本包內附之 space_hf.duckdb（連到 HF 公開資料集，需網路）。"""
    quiet_duckdb()
    import maneuver_report_builder as rb
    return rb
