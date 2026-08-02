"""satdet.config — 路徑單一來源（環境變數可覆寫）。

所有分析模組的 DB／資料目錄預設值集中於此；個別腳本不再各自硬編碼
"space_db.duckdb"。環境變數 SPACE_DB_PATH / SATDET_DATA_DIR 可覆寫。
"""
from __future__ import annotations

import os
from pathlib import Path

SPACE_DB = os.getenv("SPACE_DB_PATH", "space_db.duckdb")

DATA_DIR = Path(os.getenv("SATDET_DATA_DIR", "data"))
MANIFEST_DIR = DATA_DIR / "manifests"
BENCHMARK_DIR = DATA_DIR / "benchmark"
STAT_LAYER_DIR = DATA_DIR / "statistical_layer"
DRAG_DIR = DATA_DIR / "drag"
MEME_TRUTH_DIR = DATA_DIR / "meme_truth"
