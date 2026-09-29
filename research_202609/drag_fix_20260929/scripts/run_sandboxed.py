"""只寫暫存區的下游執行器：模型 joblib.dump、hardcoded CSV、manifest 全導向 OUT_DIR；正式檔不動。
環境變數：DRAG_CSV、STORM_AP(0/1)、OUT_DIR。用法：python run_sandboxed.py <script.py> [args...]"""
import os, runpy, sys
from pathlib import Path
ROOT = r"F:\GitHub\Sat_TraingDataExtension"; sys.path.insert(0, ROOT); os.chdir(ROOT)
OUT = Path(os.environ["OUT_DIR"]); OUT.mkdir(parents=True, exist_ok=True)
import atmospheric_drag as AD
AD.STORM_AP_MODE = os.environ.get("STORM_AP", "1") == "1"
import functools, satdet, satdet.units as U, satdet.manifest as MF
if os.environ.get("DRAG_CSV"):
    f = functools.partial(U.load_drag_map, pattern=os.environ["DRAG_CSV"]); U.load_drag_map = f; satdet.load_drag_map = f
noop = lambda *a, **k: None
satdet.record = noop; MF.record = noop
def redirect(p):
    p = Path(p); rp = (Path(ROOT) / p) if not p.is_absolute() else p
    try: rel = rp.resolve().relative_to(Path(ROOT).resolve())
    except ValueError: return str(p)            # 已在 repo 外（暫存區）
    return str(OUT / str(rel).replace(os.sep, "__"))
import joblib, pandas as pd
_jd = joblib.dump; joblib.dump = lambda obj, path, *a, **k: _jd(obj, redirect(path), *a, **k)
_csv = pd.DataFrame.to_csv
def to_csv(self, path=None, *a, **k):
    return _csv(self, redirect(path) if path is not None and not hasattr(path, "write") else path, *a, **k)
pd.DataFrame.to_csv = to_csv
print(f"[sandbox] STORM_AP={AD.STORM_AP_MODE} DRAG_CSV={os.environ.get('DRAG_CSV')} OUT={OUT}", flush=True)
script = sys.argv[1]; sys.argv = sys.argv[1:]
runpy.run_path(os.path.join(ROOT, script), run_name="__main__")
