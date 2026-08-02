"""satdet.manifest — run manifest：產出物的顯式接力，取代 glob 猜最新。

producer 每次跑完呼叫 record(step, ...) 寫 data/manifests/<step>.json
（輸入檔、參數、輸出檔、UTC 時間）。下游用 input_file() 解析：優先讀
manifest 指到且存在的檔案，否則 fallback 到 latest_file(pattern)——
上游尚未改用 manifest 時行為與舊慣例完全相同。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .common import latest_file
from .config import MANIFEST_DIR


def record(step: str, *, inputs: dict | None = None, params: dict | None = None,
           outputs: dict | None = None) -> Path:
    """寫（覆蓋）該 step 的 manifest；回傳 manifest 路徑。"""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "step": step,
        "written_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {k: str(v) for k, v in (inputs or {}).items()},
        "params": {k: (v if isinstance(v, (int, float, bool, str, type(None))) else str(v))
                   for k, v in (params or {}).items()},
        "outputs": {k: str(v) for k, v in (outputs or {}).items()},
    }
    path = MANIFEST_DIR / f"{step}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(step: str) -> dict | None:
    path = MANIFEST_DIR / f"{step}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def input_file(pattern: str, step: str | None = None, key: str | None = None) -> str:
    """解析上游輸入檔：manifest 優先（step 的輸出 key，檔案須存在），glob fallback。"""
    if step and key:
        doc = load(step)
        if doc:
            p = doc.get("outputs", {}).get(key)
            if p and Path(p).exists():
                return p
    return latest_file(pattern)
