import sys
from pathlib import Path

# 讓 pytest 能 import 上層的 leo_satellite_annotator 模組
sys.path.insert(0, str(Path(__file__).parent.parent))
