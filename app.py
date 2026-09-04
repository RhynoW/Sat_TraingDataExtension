#!/usr/bin/env python3
"""
app.py — HuggingFace Space 進入點（Streamlit）。
=====================================================
薄殼:每次 Streamlit rerun 以 __main__ 重新執行 maneuver_app_2026September.py，
維持單一真相來源(避免 import 只跑一次、UI 不再更新的問題)。

Space 需設環境變數:
  HF_DATASET_REPO = <帳號>/<dataset-repo>   ← 設了即走遠端 Parquet 模式(不需 14GB 全庫)
  HF_TOKEN        = <token>                 ← 僅 private dataset 需要
詳見 README_HF_Space.md。
"""
from __future__ import annotations

import runpy
from pathlib import Path

APP = Path(__file__).with_name("maneuver_app_2026September.py")

if not APP.exists():
    import streamlit as st
    st.error(f"找不到主程式:{APP.name}。請確認已一併上傳至 Space。")
    st.stop()

runpy.run_path(str(APP), run_name="__main__")
