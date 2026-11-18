"""練習 0：環境檢查（套件、資料檔、模型檔、HF 連線）

執行：python training/ex00_env_check.py
"""
import importlib
import time

import _common

print("① Python 套件")
for mod in ("numpy", "pandas", "scipy", "duckdb", "sklearn", "lightgbm", "matplotlib", "sgp4", "pymsis"):
    try:
        m = importlib.import_module(mod)
        print(f"   ✔ {mod:10s} {getattr(m, '__version__', '')}")
    except Exception as e:
        print(f"   ✘ {mod:10s} 無法匯入：{type(e).__name__}（pymsis 缺少時，阻力殘差通道不計入）")

print("\n② 必要檔案")
for f in ("f107_cache.csv", "space_weather_ap.csv", "space_hf.duckdb",
          "models_fusion/fusion_scorer.pkl", "assets/fonts/NotoSansTC-Regular.ttf"):
    p = _common.ROOT / f
    print(f"   {'✔' if p.exists() else '✘'} {f}")

print("\n③ HF 公開資料集連線（讀取 FORMOSAT-5，NORAD 42920）")
try:
    rb = _common.load_builder()
    t = time.time()
    df = rb.load_tle(42920, "2026-10-01")
    print(f"   ✔ 資料來源 {rb.DATA_BACKEND}，取得 {len(df)} 筆 TLE，{time.time()-t:.0f} 秒")
except Exception as e:
    print(f"   ✘ 連線失敗：{e}（練習 1、3、4、6 需網路；練習 2、5 可離線）")
