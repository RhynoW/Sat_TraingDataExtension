# maneuver_STEM_app.py  —  STEM Bilingual Learning Edition
# Derived from maneuver_app.py; all analysis logic preserved.
from datetime import datetime
import os

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import streamlit as st
from pathlib import Path
from plotly.subplots import make_subplots
from scipy.optimize import curve_fit
from scipy.signal import lombscargle

# ============================================================
# Version & Identity
# ============================================================

APP_VERSION    = "STEM-Bilingual-1.0"
APP_NAME_ZH    = "衛星機動分析教學平台"
APP_NAME_EN    = "Satellite Maneuver Analytics Learning Platform"
APP_TAGLINE_ZH = "以雙語方式學習軌道、機動與太空資料分析"
APP_TAGLINE_EN = "Learn orbital motion, maneuvers, and space data analysis in two languages"

# ============================================================
# Constants
# ============================================================

SPACE_DB_PATH          = os.getenv("SPACE_DB_PATH", r"./space_db.duckdb")
DB_PATH                = SPACE_DB_PATH
TABLE_NAME             = "tle_table"
MU                     = 398600.4415   # km³/s²
R_EARTH                = 6371.0        # km
F107_CACHE_FILE        = "./f107_cache.csv"
COMPARISON_DIR         = os.getenv("COMPARISON_DIR",         "./data/comparison")
GALILEO_COMPARISON_DIR = os.getenv("GALILEO_COMPARISON_DIR", "./data/galileo_comparison")
GEO_MANEUVER_CSV       = Path("./data/geo_maneuvers/maneuver_candidates.csv")

spiral_a    = 0.5
spiral_b    = 0.02
spiral_cmap = "hsv"
angle_cols  = ["inclination_deg", "raan_deg", "argp_deg", "mean_anomaly_deg"]

# ============================================================
# Bilingual UI Dictionary  I18N
# ============================================================

I18N = {
    "zh": {
        # App identity
        "title":   APP_NAME_ZH,
        "tagline": APP_TAGLINE_ZH,
        "version_label": "版本",
        # Sidebar
        "sidebar_language":  "語言 / Language",
        "sidebar_mode":      "分析模式",
        "sidebar_learn_mode":"教學模式",
        "mode_leo_meo":      "LEO / MEO 分析",
        "mode_geo":          "GEO 機動分析",
        "learn_concept":     "概念說明",
        "learn_data":        "資料視覺化",
        "learn_advanced":    "進階模型",
        "sidebar_norad":     "NORAD ID（多筆用逗號隔開）",
        "sidebar_start":     "開始日期",
        "sidebar_end":       "結束日期",
        "sidebar_plot":      "繪圖設定",
        "sidebar_ma":        "移動平均視窗 (MA)",
        "sidebar_raw":       "顯示原始取樣點",
        "sidebar_run":       "執行分析",
        "sidebar_geo_norad": "NORAD ID（GEO 衛星）",
        # Tabs
        "tab_analysis":  "📊 趨勢分析",
        "tab_ric":       "🚀 RIC 速度變化",
        "tab_3d":        "🌍 3D 軌道",
        "tab_delta":     "Δ 計算",
        "tab_spiral":    "𖦹 Spiral Polar",
        "tab_longaxis":  "⬯ 長軸旋轉週期",
        "tab_meme":      "🛰️ MEME 殘差",
        "tab_galileo":   "🪐 Galileo SP3",
        # Metrics
        "metric_points":        "數據點",
        "metric_maneuvers":     "機動次數",
        "metric_max_da":        "最大 Δa",
        "metric_resid_pts":     "殘差點數",
        "metric_meme_detected": "MEME 偵測機動",
        "metric_max_pos_err":   "最大 pos_err (km)",
        "metric_tle_age":       "TLE 年齡 (天)",
        "metric_sp3_detected":  "SP3 偵測機動",
        "metric_median_age":    "TLE 中位年齡 (天)",
        # GEO metrics
        "geo_ew_confirmed": "EW 確認",
        "geo_ns_confirmed": "NS 確認",
        "geo_reposition":   "重定位",
        "geo_disposal":     "廢棄",
        "geo_tle_gap":      "TLE 空白",
        # Section headings (used by concept_card key → "section_" + key)
        "section_tle":              "兩行元素（TLE）",
        "section_leo":              "LEO 機動偵測原理",
        "section_meo":              "MEO 機動偵測原理",
        "section_geo":              "GEO 機動偵測原理",
        "section_ric":              "RIC 座標系",
        "section_spiral":           "Spiral / Polar 週期視覺化",
        "section_longaxis":         "長軸旋轉週期（Lomb-Scargle）",
        "section_f107":             "Solar F10.7 指數",
        "section_event":            "機動事件判定流程",
        "section_meme":             "MEME 殘差分析",
        "section_galileo_sp3":      "Galileo SP3 精密星曆殘差",
        # Event labels
        "label_candidate":  "疑似事件",
        "label_confirmed":  "已確認事件",
        "label_maneuver":   "機動事件",
        "label_raise":      "抬升軌道",
        "label_lower":      "降低軌道",
        "label_inplane":    "面內機動",
        "label_outplane":   "面外機動",
        "label_intrack":    "沿軌方向（I）",
        "label_crosstrack": "跨軌方向（C）",
        "label_radial":     "徑向（R）",
        "label_ew_confirmed":   "EW 確認",
        "label_ew_unconfirmed": "EW 未確認",
        "label_ns_confirmed":   "NS 確認",
        "label_ns_unconfirmed": "NS 未確認",
        "label_raw_samples": "原始取樣",
        "label_fit_curve":   "擬合曲線",
        # Comparison table columns
        "comp_method":         "方法",
        "comp_count":          "偵測機動數",
        "comp_accuracy":       "資料精度",
        "comp_time_res":       "時間解析度",
        "comp_orbit_zone":     "軌道高度",
        "comp_tle_diff":       "TLE-SMA 差分",
        "comp_meme_rtn":       "MEME RTN 突變",
        "comp_galileo_sp3":    "Galileo SP3 RTN",
        "comp_tle_acc":        "~km（TLE 衍生）",
        "comp_meme_acc":       "sub-km（SpaceX MEME）",
        "comp_sp3_acc":        "sub-cm（IGS MGEX SP3）",
        "comp_leo_zone":       "LEO/MEO 通用",
        "comp_starlink_zone":  "LEO Starlink",
        "comp_galileo_zone":   "MEO Galileo",
        # Messages
        "msg_no_data":      "找不到 NORAD ID {sid} 的資料，跳過分析。",
        "msg_meo_warning":  "NORAD {sid}：軌道高度 {alt:.0f} km 屬 MEO/GEO，大氣阻力可忽略，機動偵測靈敏度較低，建議人工確認。",
        "msg_run_prompt":   "請於左側面板設定參數並點擊「執行分析」開始。",
        "msg_no_meme":      "此衛星在選定期間無 MEME 殘差資料。\n\n請先執行：\n```\npython compare_tle_vs_ephemeris.py\n```",
        "msg_no_galileo":   "此衛星在選定期間無 Galileo SP3 殘差資料。\n\n請先執行：\n```\npython galileo_pipeline.py\n```",
        "msg_no_event":     "在選定期間未偵測到 RTN 突變事件（z > 5）。",
        "msg_no_geo_data":  "NORAD {norad} 無資料。請確認 data/geo_maneuvers/maneuver_candidates.csv 已存在，且 space_db.duckdb 的 raw_tle_archive 包含此衛星 TLE。",
        "msg_enter_norad":  "請輸入至少一個 NORAD ID，例如 66666",
        "msg_galileo_wrong_orbit": "注意：NORAD {sid} 軌道高度約 {alt:.0f} km，非 MEO 高度，此頁面僅適用於 Galileo 衛星。",
        # Sub-titles with placeholders
        "sub_satellite_report":    "衛星分析報告: NORAD {sid}",
        "sub_geo_analysis":        "GEO 機動分析: {name}  (NORAD {norad})",
        "sub_geo_period":          "分析期間: {s} – {e}  |  資料來源: space_db → raw_tle_archive + maneuver_candidates.csv",
        "sub_detected_meme":       "偵測到的 MEME 機動事件",
        "sub_detected_galileo":    "偵測到的 Galileo SP3 機動事件",
        "sub_compare_tle_meme":    "TLE 偵測 vs MEME 偵測對比",
        "sub_compare_tri":         "三方法偵測對比",
        "sub_delta":               "Δ 計算（SMA 與軌道角度） — NORAD {sid}",
        "sub_spiral":              "Spiral Polar 軌道角度分佈 — NORAD {sid}",
        "sub_longaxis":            "長軸旋轉週期分析 — NORAD {sid}",
        # Delta tab
        "delta_preview":    "前 10 筆 Δ 資料預覽：",
        "delta_download":   "📥 下載 Δ 資料 (CSV)",
        "delta_time_chart": "Δ 時序圖",
        # Fit params
        "fit_params_title":      "擬合參數的物理意義：",
        "fit_psi_def":           "從 TLE 取出：長軸方向角 ψ(t) = 升交點赤經 Ω(t) + 近地點幅角 ω(t)",
        "fit_a":                 "a：線性斜率（deg / 恆星日），表示長軸平均旋轉速率。",
        "fit_b":                 "b：截距（deg），擬合時的初始偏移。",
        "fit_A":                 "A：正弦項係數（deg），主頻週期的正弦分量。",
        "fit_B":                 "B：餘弦項係數（deg），主頻週期的餘弦分量。",
        "fit_period_amplitude":  "週期項總振幅 ≈ {amp:.3f} deg",
        "fit_samples":           "樣本數: {n}，覆蓋時間: {d:.2f} 恆星日",
        "fit_failed":            "長軸模型擬合失敗",
        # downloads / misc
        "download_event_csv": "📥 下載事件 CSV",
        "ns_detail":          "NS 事件詳情",
        "orbit_evolution_title": "軌道演變示意",
        # event table extra columns
        "col_reason": "判定說明（中文）",
        "col_reason_en": "Reason (EN)",
        "col_direction": "方向",
        # chart axis / title
        "chart_sma_f107_title": "半長軸衰減 vs 太陽活動（F10.7）",
        "axis_sma":    "半長軸 (km)",
        "axis_f107":   "F10.7 太陽通量",
        "axis_dv":     "速度增量 ΔV (m/s)",
        "axis_lon":    "子衛星經度 λ (°)",
        "axis_drift":  "經度漂移率 dλ/dt (°/day)",
        "axis_inc":    "傾角 Inclination (°)",
        "trace_maneuver": "機動偵測點",
        "trace_intrack":  "沿軌 ΔV (m/s)",
        "trace_crosstrack": "跨軌 ΔV (m/s)",
        "trace_raw":   "原始取樣",
        "trace_fit":   "擬合",
        "no_longaxis_cols": "此資料集缺少 epoch_jd / raan_deg / argp_deg，無法做長軸分析。",
        "longaxis_fit_cols": "樣本數: {n}, 覆蓋時間: {d:.2f} 恆星日",
        "longaxis_wrapped_yaxis": "ψ (deg, 折疊)",
        "longaxis_unwrapped_yaxis": "ψ (deg, 展開)",
        "longaxis_ls_xaxis": "週期（恆星年）",
        "longaxis_ls_yaxis": "Lomb-Scargle 功率",
        "f107_download_failed": "F10.7 下載失敗",
        "db_read_failed": "資料庫讀取失敗",
        "meme_caption": "資料來源：`compare_tle_vs_ephemeris.py` 產生的 `data/comparison/residuals_*.csv`。機動偵測依據 RTN 殘差的逐步突變（MAD z-score），精度比 TLE-SMA 差分高 1–2 個量級。",
        "galileo_caption": "資料來源：`compare_galileo_sp3_vs_tle.py` 產生的 `data/galileo_comparison/residuals_*.csv`。精密 SP3 精度 sub-cm；RTN 殘差反映 TLE-SGP4 誤差；突變即為機動信號。適用於 MEO 高度 Galileo 星座（~29,600 km）。",
        "rtn_subplot_t":   "Along-Track dr_t (km)  ← 沿軌誤差（機動主指標）",
        "rtn_subplot_n":   "Cross-Track dr_n (km)  ← 跨軌誤差（面外機動）",
        "rtn_subplot_pos": "3D 位置誤差 RSS (km)",
        "geo_tab_lon":   "📡 經度 & 漂移率",
        "geo_tab_inc":   "↕ 傾角 (NS)",
        "geo_tab_table": "📋 事件表",
        "geo_no_series": "無 TLE 時間序列（raw_tle_archive 中未找到此衛星）。",
        "geo_no_series_inc": "無 TLE 時間序列。",
        "geo_ew_summary": "共 {n} 次確認 EW 機動  |  最大 |Δdrift| = {v:.4f} °/day",
        "geo_no_events":  "此衛星在選定期間無偵測到機動事件。",
        "geo_ew_help":    "漂移率符號翻轉 |Δdrift| > 0.02 °/day",
        "geo_ns_help":    "傾角步進 Δi < −0.003°，附加 RAAN 殘差確認",
        "geo_reposition_help": "中值漂移 > 0.05 °/day 且最大偏離 > 2°",
        "geo_disposal_help":   "SMA 持續超過 42,300 km",
        "geo_gap_help":        "相鄰 TLE 間距 > 4 天",
        "geo_lon_sub1":  "Sub-Satellite Longitude λ (°)",
        "geo_lon_sub2":  "Longitude Drift Rate dλ/dt (°/day)",
        "glossary_label": "📖 術語字典",
        "concept_label":  "概念說明",
    },
    "en": {
        # App identity
        "title":   APP_NAME_EN,
        "tagline": APP_TAGLINE_EN,
        "version_label": "Version",
        # Sidebar
        "sidebar_language":   "Language / 語言",
        "sidebar_mode":       "Analysis Mode",
        "sidebar_learn_mode": "Learning Mode",
        "mode_leo_meo":       "LEO / MEO Analysis",
        "mode_geo":           "GEO Maneuver Analysis",
        "learn_concept":      "Concept",
        "learn_data":         "Data Visualization",
        "learn_advanced":     "Advanced Model",
        "sidebar_norad":      "NORAD ID (comma-separated)",
        "sidebar_start":      "Start Date",
        "sidebar_end":        "End Date",
        "sidebar_plot":       "Plot Settings",
        "sidebar_ma":         "Moving Average Window (MA)",
        "sidebar_raw":        "Show Raw Samples",
        "sidebar_run":        "Run Analysis",
        "sidebar_geo_norad":  "NORAD ID (GEO Satellite)",
        # Tabs
        "tab_analysis":  "📊 Trend Analysis",
        "tab_ric":       "🚀 RIC Velocity",
        "tab_3d":        "🌍 3D Orbit",
        "tab_delta":     "Δ Computation",
        "tab_spiral":    "𖦹 Spiral Polar",
        "tab_longaxis":  "⬯ Apsidal Precession",
        "tab_meme":      "🛰️ MEME Residuals",
        "tab_galileo":   "🪐 Galileo SP3",
        # Metrics
        "metric_points":        "Data Points",
        "metric_maneuvers":     "Maneuvers",
        "metric_max_da":        "Max Δa",
        "metric_resid_pts":     "Residual Points",
        "metric_meme_detected": "MEME Detected",
        "metric_max_pos_err":   "Max pos_err (km)",
        "metric_tle_age":       "TLE Age (days)",
        "metric_sp3_detected":  "SP3 Detected",
        "metric_median_age":    "Median TLE Age (days)",
        # GEO metrics
        "geo_ew_confirmed": "EW Confirmed",
        "geo_ns_confirmed": "NS Confirmed",
        "geo_reposition":   "Repositioning",
        "geo_disposal":     "Disposal",
        "geo_tle_gap":      "TLE Gap",
        # Section headings
        "section_tle":         "Two-Line Elements (TLE)",
        "section_leo":         "LEO Maneuver Detection",
        "section_meo":         "MEO Maneuver Detection",
        "section_geo":         "GEO Maneuver Detection",
        "section_ric":         "RIC Coordinate Frame",
        "section_spiral":      "Spiral / Polar Periodicity",
        "section_longaxis":    "Apsidal Precession (Lomb-Scargle)",
        "section_f107":        "Solar F10.7 Index",
        "section_event":       "Event Detection Logic",
        "section_meme":        "MEME Residuals Analysis",
        "section_galileo_sp3": "Galileo SP3 Precision Ephemeris",
        # Event labels
        "label_candidate":  "Candidate Event",
        "label_confirmed":  "Confirmed Event",
        "label_maneuver":   "Maneuver Event",
        "label_raise":      "Orbit Raise",
        "label_lower":      "Orbit Lower",
        "label_inplane":    "In-Plane Maneuver",
        "label_outplane":   "Out-of-Plane Maneuver",
        "label_intrack":    "In-Track (I)",
        "label_crosstrack": "Cross-Track (C)",
        "label_radial":     "Radial (R)",
        "label_ew_confirmed":   "EW Confirmed",
        "label_ew_unconfirmed": "EW Candidate",
        "label_ns_confirmed":   "NS Confirmed",
        "label_ns_unconfirmed": "NS Candidate",
        "label_raw_samples": "Raw Samples",
        "label_fit_curve":   "Fit Curve",
        # Comparison table columns
        "comp_method":        "Method",
        "comp_count":         "Detected Maneuvers",
        "comp_accuracy":      "Data Accuracy",
        "comp_time_res":      "Time Resolution",
        "comp_orbit_zone":    "Orbit Zone",
        "comp_tle_diff":      "TLE-SMA Differencing",
        "comp_meme_rtn":      "MEME RTN Step",
        "comp_galileo_sp3":   "Galileo SP3 RTN",
        "comp_tle_acc":       "~km (TLE-derived)",
        "comp_meme_acc":      "sub-km (SpaceX MEME)",
        "comp_sp3_acc":       "sub-cm (IGS MGEX SP3)",
        "comp_leo_zone":      "LEO/MEO general",
        "comp_starlink_zone": "LEO Starlink",
        "comp_galileo_zone":  "MEO Galileo",
        # Messages
        "msg_no_data":      "No data found for NORAD {sid}, skipping.",
        "msg_meo_warning":  "NORAD {sid}: altitude {alt:.0f} km is MEO/GEO — drag negligible, lower detection sensitivity. Manual review recommended.",
        "msg_run_prompt":   "Set parameters in the sidebar and click 'Run Analysis'.",
        "msg_no_meme":      "No MEME residual data for this satellite in the selected period.\n\nRun first:\n```\npython compare_tle_vs_ephemeris.py\n```",
        "msg_no_galileo":   "No Galileo SP3 residual data for this satellite.\n\nRun first:\n```\npython galileo_pipeline.py\n```",
        "msg_no_event":     "No RTN step events detected (z > 5) in the selected period.",
        "msg_no_geo_data":  "NORAD {norad}: no data. Ensure data/geo_maneuvers/maneuver_candidates.csv exists and raw_tle_archive contains this satellite.",
        "msg_enter_norad":  "Please enter at least one NORAD ID, e.g. 66666",
        "msg_galileo_wrong_orbit": "Note: NORAD {sid} altitude ~{alt:.0f} km is not MEO — Galileo SP3 tab applies only to Galileo satellites.",
        # Sub-titles
        "sub_satellite_report":  "Satellite Analysis Report: NORAD {sid}",
        "sub_geo_analysis":      "GEO Maneuver Analysis: {name}  (NORAD {norad})",
        "sub_geo_period":        "Period: {s} – {e}  |  Source: space_db → raw_tle_archive + maneuver_candidates.csv",
        "sub_detected_meme":     "Detected MEME Maneuver Events",
        "sub_detected_galileo":  "Detected Galileo SP3 Maneuver Events",
        "sub_compare_tle_meme":  "TLE vs MEME Detection Comparison",
        "sub_compare_tri":       "Three-Method Detection Comparison",
        "sub_delta":             "Δ Computation (SMA & Angular Elements) — NORAD {sid}",
        "sub_spiral":            "Spiral Polar Angular Distribution — NORAD {sid}",
        "sub_longaxis":          "Apsidal Precession Period Analysis — NORAD {sid}",
        # Delta tab
        "delta_preview":    "First 10 rows preview:",
        "delta_download":   "📥 Download Δ data (CSV)",
        "delta_time_chart": "Δ Time Series",
        # Fit params
        "fit_params_title":     "Physical meaning of fit parameters:",
        "fit_psi_def":          "From TLE: ψ(t) = RAAN Ω(t) + Argument of Perigee ω(t)",
        "fit_a":                "a: linear slope (deg/sidereal day) — mean apsidal precession rate.",
        "fit_b":                "b: intercept (deg) — initial offset.",
        "fit_A":                "A: sine coefficient (deg) — sine component at dominant period.",
        "fit_B":                "B: cosine coefficient (deg) — cosine component at dominant period.",
        "fit_period_amplitude": "Total periodic amplitude ≈ {amp:.3f} deg",
        "fit_samples":          "Samples: {n}, span: {d:.2f} sidereal days",
        "fit_failed":           "Apsidal fit failed",
        # downloads / misc
        "download_event_csv": "📥 Download Event CSV",
        "ns_detail":          "NS Event Details",
        "orbit_evolution_title": "Orbital Evolution",
        # event table extra columns
        "col_reason":    "Reason (ZH)",
        "col_reason_en": "Reason (EN)",
        "col_direction": "Direction",
        # chart axis / title
        "chart_sma_f107_title": "SMA Decay vs Solar Activity (F10.7)",
        "axis_sma":    "Semi-Major Axis (km)",
        "axis_f107":   "F10.7 Solar Flux",
        "axis_dv":     "Delta-V (m/s)",
        "axis_lon":    "Sub-Satellite Longitude λ (°)",
        "axis_drift":  "Longitude Drift Rate dλ/dt (°/day)",
        "axis_inc":    "Inclination (°)",
        "trace_maneuver": "Detected Maneuver",
        "trace_intrack":  "In-Track ΔV (m/s)",
        "trace_crosstrack": "Cross-Track ΔV (m/s)",
        "trace_raw":   "Raw Samples",
        "trace_fit":   "Fit",
        "no_longaxis_cols": "Dataset missing epoch_jd / raan_deg / argp_deg — apsidal analysis unavailable.",
        "longaxis_fit_cols": "Samples: {n}, span: {d:.2f} sidereal days",
        "longaxis_wrapped_yaxis":   "ψ (deg, wrapped)",
        "longaxis_unwrapped_yaxis": "ψ (deg, unwrapped)",
        "longaxis_ls_xaxis": "Period (sidereal years)",
        "longaxis_ls_yaxis": "Lomb-Scargle Power",
        "f107_download_failed": "F10.7 download failed",
        "db_read_failed": "Database read failed",
        "meme_caption": "Source: `compare_tle_vs_ephemeris.py` → `data/comparison/residuals_*.csv`. Maneuver detection uses MAD z-score on RTN residual steps — 1–2 orders of magnitude more sensitive than TLE-SMA differencing.",
        "galileo_caption": "Source: `compare_galileo_sp3_vs_tle.py` → `data/galileo_comparison/residuals_*.csv`. SP3 accuracy sub-cm; RTN residuals reflect TLE-SGP4 error; step jumps are maneuver signatures. Applies to MEO Galileo constellation (~29,600 km).",
        "rtn_subplot_t":   "Along-Track dr_t (km)  ← in-plane maneuver indicator",
        "rtn_subplot_n":   "Cross-Track dr_n (km)  ← out-of-plane maneuver indicator",
        "rtn_subplot_pos": "3D Position Error RSS (km)",
        "geo_tab_lon":   "📡 Longitude & Drift",
        "geo_tab_inc":   "↕ Inclination (NS)",
        "geo_tab_table": "📋 Event Table",
        "geo_no_series":     "No TLE time series (satellite not in raw_tle_archive).",
        "geo_no_series_inc": "No TLE time series.",
        "geo_ew_summary": "{n} confirmed EW maneuvers  |  max |Δdrift| = {v:.4f} °/day",
        "geo_no_events":  "No maneuver events detected for this satellite in the selected period.",
        "geo_ew_help":    "Drift-rate sign reversal |Δdrift| > 0.02 °/day",
        "geo_ns_help":    "Inclination step Δi < −0.003°, confirmed by RAAN residual",
        "geo_reposition_help": "Median drift > 0.05 °/day and max deviation > 2°",
        "geo_disposal_help":   "SMA continuously above 42,300 km",
        "geo_gap_help":        "Adjacent TLE gap > 4 days",
        "geo_lon_sub1":  "Sub-Satellite Longitude λ (°)",
        "geo_lon_sub2":  "Longitude Drift Rate dλ/dt (°/day)",
        "glossary_label": "📖 Glossary",
        "concept_label":  "Concept",
    },
}

# ============================================================
# Teaching Explanation Dictionary  EXPLAIN
# ============================================================

EXPLAIN = {
    "zh": {
        "tle": (
            "**TLE / 兩行元素**：TLE 用兩行 ASCII 文字描述衛星在某一「曆元」時刻的**平均**軌道狀態，"
            "搭配 SGP4/SDP4 模型可向前或向後推算衛星位置。\n\n"
            "TLE 不是精密定軌結果，精度約 1–10 km，適合快速追蹤與短中期預報。\n\n"
            "| 欄位 | 說明 |\n|---|---|\n"
            "| 曆元 Epoch | 軌道元素的參考時刻 |\n"
            "| 傾角 Inclination | 軌道面與赤道面夾角 |\n"
            "| RAAN | 升交點赤經，定義軌道面方向 |\n"
            "| 偏心率 Eccentricity | 軌道橢圓形狀（0=圓形）|\n"
            "| 近地點幅角 | 橢圓長軸方向 |\n"
            "| 平近點角 | 衛星在軌道上的相位 |\n"
            "| 平均運動 Mean Motion | 每天繞地圈數 |\n\n"
            "**Two-Line Elements (TLE)**: A two-line ASCII format describing a satellite's *mean* "
            "orbital state at a given epoch. Used with SGP4/SDP4 propagators for position prediction "
            "(accuracy ~1–10 km). Not a precision orbit determination product."
        ),
        "leo": (
            "**LEO 機動偵測**（低地球軌道，高度 < ~1,200 km）\n\n"
            "LEO 衛星持續受大氣阻力影響，半長軸（SMA）呈現連續緩慢衰減。"
            "機動事件會在短時間內造成 SMA 跳變、斜率翻轉或殘差激增，與背景衰減明顯不同。\n\n"
            "偵測方法：\n"
            "1. 計算每日 SMA 差分與變化率\n"
            "2. 以 MAD z-score 找出統計異常點（候選點）\n"
            "3. 相鄰候選點合併為事件簇，取峰值為代表時刻\n\n"
            "**LEO Maneuver Detection** (altitude < ~1,200 km): "
            "Continuous atmospheric drag causes slow SMA decay. "
            "A maneuver appears as a sudden SMA jump, slope reversal, or residual spike — "
            "distinguishable from the smooth background decay by MAD-based statistical outlier detection."
        ),
        "meo": (
            "**MEO 機動偵測**（中地球軌道，如 Galileo ~29,600 km）\n\n"
            "MEO 幾乎無大氣阻力，軌道自然演化極平滑。"
            "機動訊號主要來自 RIC 殘差的**階躍變化**（尤其是沿軌 I 分量），"
            "需精密星曆（SP3）與較長觀測窗口才能可靠偵測。\n\n"
            "偵測重點：\n"
            "- along-track（沿軌）步階群聚 → 面內推進\n"
            "- cross-track（跨軌）步階 → 傾角修正\n"
            "- 殘差斜率突然改變 → 推進前後軌道能量不同\n\n"
            "**MEO Maneuver Detection** (~29,600 km for Galileo): "
            "Negligible drag means natural SMA evolution is very smooth. "
            "Maneuvers appear as *step changes* in RIC residuals (especially in-track I), "
            "requiring SP3 precision ephemerides and a longer detection window."
        ),
        "geo": (
            "**GEO 機動偵測**（地球同步軌道，~35,786 km）\n\n"
            "GEO 衛星需持續進行站位控制：\n"
            "- **東西向（EW）**：修正經度漂移，防止衛星偏離指定經度槽\n"
            "- **南北向（NS）**：修正傾角增長，防止軌道面偏離赤道\n\n"
            "機動通常呈週期性分段修正（每 1–14 天一次），而非單一孤立跳點。\n\n"
            "偵測信號：\n"
            "- EW：漂移率符號翻轉（Δdrift > 閾值）\n"
            "- NS：傾角階躍（Δi < −0.003°）+ RAAN 殘差確認\n"
            "- 重定位：中值漂移率持續增大\n\n"
            "**GEO Maneuver Detection** (~35,786 km): "
            "Regular **East-West (EW)** and **North-South (NS)** station-keeping. "
            "EW corrects longitude drift; NS controls inclination growth. "
            "Events appear as periodic segmented corrections, not isolated spikes."
        ),
        "ric": (
            "**RIC 座標系**（Radial-Intrack-Crosstrack）\n\n"
            "RIC 把衛星的相對位置偏差分解成三個物理直觀的方向：\n\n"
            "| 分量 | 方向 | 物理意義 |\n|---|---|---|\n"
            "| **R（徑向）** | 指向/遠離地心 | 軌道大小與能量變化 |\n"
            "| **I（沿軌/切向）** | 沿速度方向 | 相位偏移，最敏感的機動指標 |\n"
            "| **C（跨軌/法向）** | 垂直軌道面 | 傾角與軌道面調整 |\n\n"
            "機動偵測時，I 分量的步階變化通常最先出現且最顯著，"
            "C 分量的步階則反映面外推進（傾角修正）。\n\n"
            "**RIC Frame** (Radial-Intrack-Crosstrack): "
            "Decomposes relative orbital changes into three physically intuitive directions. "
            "The **I (in-track)** component is most sensitive to maneuver-induced phasing; "
            "the **C (cross-track)** component reflects inclination and plane changes."
        ),
        "spiral": (
            "**Spiral / Polar 週期視覺化**\n\n"
            "將時間軸正規化映射為角度，在極座標系下呈現四個角元素"
            "（傾角、RAAN、近地點幅角、平近點角）的長期演化。\n\n"
            "閱讀方法：\n"
            "- 顏色由早（暖色）→ 晚（冷色）\n"
            "- 螺旋半徑隨時間增加，可辨識時間進程\n"
            "- 若分佈呈均勻圓形 → 週期穩定；若出現缺口或叢集 → 可能有機動或攝動\n\n"
            "**Spiral / Polar Visualization**: "
            "Maps time to angle in polar coordinates to reveal periodicity and long-term trends "
            "in angular orbital elements. "
            "Stable cycles suggest undisturbed evolution; jumps or clustering indicate maneuvers or perturbations."
        ),
        "f107": (
            "**Solar F10.7 指數**\n\n"
            "F10.7 是 10.7 cm 波長太陽電波通量，是太陽活動強度最常用的代理量。\n\n"
            "物理鏈路：\n"
            "F10.7 升高 → 太陽極紫外線增強 → 熱層加熱 → 大氣密度增加 → LEO 阻力增大 → SMA 衰減加速\n\n"
            "**觀察重點**：若 SMA 加速衰減但無機動標記，可能是阻力增強而非推進燃燒。\n"
            "使用本圖可同時觀察 SMA 趨勢與太陽活動背景，協助區分自然衰減與人為機動。\n\n"
            "**Solar F10.7 Index**: Solar radio flux at 10.7 cm — standard proxy for solar activity. "
            "Higher F10.7 → denser thermosphere → greater drag on LEO satellites → faster SMA decay. "
            "Accelerated decay without maneuver markers may indicate drag enhancement, not a burn."
        ),
        "event": (
            "**機動事件判定流程**\n\n"
            "| 步驟 | 方法 | 說明 |\n|---|---|---|\n"
            "| 1. 差分 | 每日 SMA 差分 | 計算變化量與變化率 |\n"
            "| 2. 統計異常 | MAD z-score | 找出超過閾值的候選點 |\n"
            "| 3. 聚類 | 相鄰合併 | 把連續候選點視為同一機動 |\n"
            "| 4. 峰值 | 取最大 z-score | 選代表時刻 |\n\n"
            "閾值 `mult` 會根據軌道高度自動調整（LEO 低軌用較高閾值，MEO 用較低閾值）。\n\n"
            "**重要提示**：代表時刻是資料判定點，不一定等於實際推進開始的物理瞬間。\n\n"
            "**Event Detection Logic**: "
            "1) Daily SMA differencing → 2) MAD z-score outlier flagging → "
            "3) Adjacent candidate merging into clusters → 4) Peak epoch selection. "
            "*The detected epoch is a statistical representative, not the exact thruster-firing instant.*"
        ),
        "meme": (
            "**MEME 殘差分析**\n\n"
            "MEME（Mission Engineering & Maneuver Ephemeris）是 SpaceX 發布的精密星曆，精度達 sub-km。"
            "與 TLE-SGP4 推算位置相減即得 RTN 殘差時間序列。\n\n"
            "機動信號：\n"
            "- **along-track（沿軌）突變** → 面內機動（相位調整，速度方向推進）\n"
            "- **cross-track（跨軌）突變** → 面外機動（傾角修正）\n"
            "- 殘差整體斜率改變 → 軌道能量變化\n\n"
            "偵測精度比 TLE-SMA 差分高 1–2 個量級（sub-km vs ~km）。\n\n"
            "**MEME Residual Analysis**: "
            "SpaceX MEME ephemeris (sub-km accuracy) minus TLE-SGP4 yields RTN residuals. "
            "Along-track step jumps indicate in-plane maneuvers; "
            "cross-track steps indicate out-of-plane maneuvers. "
            "Sensitivity is 1–2 orders of magnitude better than TLE-SMA differencing."
        ),
        "galileo_sp3": (
            "**Galileo SP3 殘差分析**\n\n"
            "IGS MGEX 發布的 SP3 精密星曆精度達 sub-cm（公分以下）。"
            "與 TLE-SGP4 比對可得 MEO 高度（~29,600 km）的 RTN 殘差時間序列。\n\n"
            "由於 MEO 無大氣阻力，殘差序列自然演化極平滑；任何步階突變即為機動信號。\n\n"
            "偵測方法與 MEME 相同（MAD z-score on RTN step rate），"
            "但因 MEO 動態更平滑，z-score 閾值可更低（預設 z > 4），靈敏度更高。\n\n"
            "**Galileo SP3 Residual Analysis**: "
            "IGS MGEX SP3 ephemerides (sub-cm accuracy) vs TLE-SGP4 at MEO altitude. "
            "Smooth natural dynamics mean any step in RTN residuals is a maneuver signature. "
            "Detection uses the same MAD z-score method as MEME but with a lower threshold."
        ),
        "longaxis": (
            "**長軸旋轉週期（Lomb-Scargle）**\n\n"
            "ψ(t) = RAAN Ω(t) + 近地點幅角 ω(t)，代表軌道橢圓長軸在慣性空間的方向角。\n\n"
            "在地球非球形攝動（J2）等力的作用下，ψ 緩慢進動，形成長達數年的週期。"
            "Lomb-Scargle 週期圖能從不均勻採樣的 TLE 時間序列中精確估計進動週期，"
            "並以線性+正弦模型擬合趨勢與週期振幅。\n\n"
            "**Apsidal Precession (Lomb-Scargle)**: "
            "ψ(t) = RAAN + Argument of Perigee tracks the orbital ellipse's major-axis direction "
            "in inertial space. Under J2 perturbations, ψ precesses slowly over years. "
            "The Lomb-Scargle periodogram recovers the precession period from "
            "the unevenly-sampled TLE series."
        ),
    },
}

# Mirror zh explanations to en (EXPLAIN only has zh; bilingual text is embedded in each entry)
EXPLAIN["en"] = EXPLAIN["zh"]

# ============================================================
# Terminology Glossary  TERMS
# ============================================================

TERMS = {
    "zh": {
        "leo": "低地球軌道（LEO，< 2,000 km）",
        "meo": "中地球軌道（MEO，2,000–35,786 km）",
        "geo": "地球同步軌道（GEO，~35,786 km）",
        "tle": "兩行元素（TLE）",
        "ric": "徑向-沿軌-跨軌座標系（RIC）",
        "f107": "太陽 F10.7 電波通量指數",
        "maneuver": "機動事件（推進器點火）",
        "candidate": "疑似候選點（超過統計閾值）",
        "confirmed": "已確認事件（通過額外規則）",
        "sma": "半長軸（Semi-Major Axis, SMA）",
        "inclination": "傾角（Inclination）",
        "raan": "升交點赤經（RAAN）",
        "argp": "近地點幅角（Argument of Perigee）",
        "mean_anomaly": "平近點角（Mean Anomaly）",
        "eccentricity": "偏心率（Eccentricity）",
        "epoch": "曆元（Epoch）",
        "sgp4": "SGP4 軌道推算模型",
        "mad": "中位數絕對偏差（MAD）",
        "zscore": "z 分數（統計異常強度）",
        "ew": "東西向站位控制（East-West S/K）",
        "ns": "南北向站位控制（North-South S/K）",
        "drift": "經度漂移率（°/day）",
        "sp3": "SP3 精密星曆格式（IGS 標準）",
        "rtn": "RTN 殘差（Radial-Tangential-Normal）",
        "lombscargle": "Lomb-Scargle 週期圖（不均勻採樣頻譜）",
        "cluster": "事件簇（Cluster，相鄰候選點群組）",
        "delta_v": "速度增量 ΔV（推進效果量化）",
        "sgp4_drag": "B* 阻力係數（TLE 中的大氣阻力代理量）",
    },
    "en": {
        "leo": "Low Earth Orbit (LEO, < 2,000 km)",
        "meo": "Medium Earth Orbit (MEO, 2,000–35,786 km)",
        "geo": "Geosynchronous Earth Orbit (GEO, ~35,786 km)",
        "tle": "Two-Line Element (TLE)",
        "ric": "Radial-Intrack-Crosstrack Frame (RIC)",
        "f107": "Solar F10.7 Radio Flux Index",
        "maneuver": "Maneuver Event (thruster firing)",
        "candidate": "Candidate Point (above statistical threshold)",
        "confirmed": "Confirmed Event (passes additional criteria)",
        "sma": "Semi-Major Axis (SMA)",
        "inclination": "Inclination",
        "raan": "Right Ascension of Ascending Node (RAAN)",
        "argp": "Argument of Perigee",
        "mean_anomaly": "Mean Anomaly",
        "eccentricity": "Eccentricity",
        "epoch": "Epoch",
        "sgp4": "SGP4 Orbit Propagator",
        "mad": "Median Absolute Deviation (MAD)",
        "zscore": "Z-Score (statistical anomaly metric)",
        "ew": "East-West Station-Keeping (EW S/K)",
        "ns": "North-South Station-Keeping (NS S/K)",
        "drift": "Longitude Drift Rate (°/day)",
        "sp3": "SP3 Precision Ephemeris Format (IGS standard)",
        "rtn": "RTN Residuals (Radial-Tangential-Normal)",
        "lombscargle": "Lomb-Scargle Periodogram (unevenly-sampled spectrum)",
        "cluster": "Event Cluster (adjacent candidate group)",
        "delta_v": "Delta-V ΔV (maneuver magnitude proxy)",
        "sgp4_drag": "B* Drag Coefficient (atmospheric drag proxy in TLE)",
    },
}

# ============================================================
# Translation Helpers
# ============================================================

def T(key: str, lang: str = "zh") -> str:
    """Return UI string for key in given language; fall back to key itself."""
    return I18N.get(lang, I18N["zh"]).get(key, I18N["zh"].get(key, key))


def E(key: str, lang: str = "zh") -> str:
    """Return teaching explanation for key (both zh and en are embedded in zh entry)."""
    return EXPLAIN["zh"].get(key, key)


def term(key: str, lang: str = "zh") -> str:
    return TERMS.get(lang, TERMS["zh"]).get(key, key)


# ============================================================
# Teaching UI Helpers
# ============================================================

def concept_card(key: str, lang: str, icon: str = "📚") -> None:
    """Render an expandable concept explanation box."""
    label = f"{icon} {T('section_' + key, lang)} — {T('concept_label', lang)}"
    with st.expander(label, expanded=False):
        st.markdown(E(key, lang))


def terms_glossary_card(lang: str) -> None:
    """Render a collapsible glossary table."""
    with st.expander(T("glossary_label", lang), expanded=False):
        rows = [(term(k, "zh"), term(k, "en")) for k in TERMS["zh"]]
        st.dataframe(
            pd.DataFrame(rows, columns=["中文 Chinese", "English"]),
            use_container_width=True,
            hide_index=True,
        )


def event_reason_text(lang: str, event_type: str, metric: str,
                      zscore: float, step: float, window: int) -> str:
    if lang == "zh":
        return (
            f"事件類型：{event_type}。"
            f"判定依據：{metric} 的 z-score = {zscore:.1f}，步階變化 = {step:.3f}。"
            f"使用窗口：約 {window} 個曆元。"
            "教學解釋：此點序列出現明顯統計異常，可能對應機動或姿態控制動作。"
        )
    return (
        f"Event type: {event_type}. "
        f"Criterion: z-score of {metric} = {zscore:.1f}, step = {step:.3f}. "
        f"Window: ~{window} epochs. "
        "Teaching note: clear statistical anomaly — likely a maneuver or attitude-control action."
    )


def _add_reason_cols(df: pd.DataFrame, event_type_col: str,
                     zscore_col: str, step_col: str, window: int) -> pd.DataFrame:
    """Append bilingual reason columns to an event DataFrame."""
    df = df.copy()
    if df.empty:
        df["reason_zh"] = pd.Series(dtype=str)
        df["reason_en"] = pd.Series(dtype=str)
        return df
    df["reason_zh"] = df.apply(
        lambda r: event_reason_text(
            "zh", r.get(event_type_col, ""),
            step_col, float(r.get(zscore_col, 0)),
            float(r.get(step_col, 0)), window,
        ), axis=1,
    )
    df["reason_en"] = df.apply(
        lambda r: event_reason_text(
            "en", r.get(event_type_col, ""),
            step_col, float(r.get(zscore_col, 0)),
            float(r.get(step_col, 0)), window,
        ), axis=1,
    )
    return df


def _show_concept_if(mode: str, key: str, lang: str, icon: str = "📚") -> None:
    if mode in ("learn_concept", "learn_data", "learn_advanced"):
        concept_card(key, lang, icon)

# ============================================================
# F10.7 Solar Flux
# ============================================================

def fetch_f107_data():
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(F107_CACHE_FILE):
        df_cache = pd.read_csv(F107_CACHE_FILE)
        if not df_cache.empty and "epoch" in df_cache.columns:
            df_cache["epoch"] = pd.to_datetime(df_cache["epoch"])
            if df_cache["epoch"].max().strftime("%Y-%m-%d") == today_str:
                return df_cache
    url = "https://spaceweather.gc.ca/solar_flux_data/daily_flux_values/fluxtable.txt"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = response.text.split("\n")
        data = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 7 and parts[0].isdigit() and len(parts[0]) == 8:
                date_val = pd.to_datetime(parts[0], format="%Y%m%d")
                data.append({"epoch": date_val.strftime("%Y-%m-%d"), "f107": float(parts[5])})
        new_df = pd.DataFrame(data)
        if not new_df.empty:
            new_df["epoch"] = pd.to_datetime(new_df["epoch"], errors="coerce").astype("datetime64[ns]")
            new_df.to_csv(F107_CACHE_FILE, index=False)
        return new_df
    except Exception as e:
        lang = st.session_state.get("lang", "zh")
        st.error(f"{T('f107_download_failed', lang)}: {e}")
        if os.path.exists(F107_CACHE_FILE):
            df_cache = pd.read_csv(F107_CACHE_FILE)
            if not df_cache.empty and "epoch" in df_cache.columns:
                df_cache["epoch"] = pd.to_datetime(df_cache["epoch"], errors="coerce").astype("datetime64[ns]")
            return df_cache
        return pd.DataFrame()


# ============================================================
# Shared Data Processing
# ============================================================

def prepare_spiral_polar_data(df_raw: pd.DataFrame):
    df = df_raw.copy()
    df["date"] = pd.to_datetime(df["date_tag"])
    df = df.sort_values("date").reset_index(drop=True)
    days_since_start = (df["date"] - df["date"].min()).dt.days.values
    if len(days_since_start) == 0:
        return df, np.array([]), np.array([]), np.array([]), np.array([])
    theta_time = (2 * np.pi * days_since_start / days_since_start.max()
                  if days_since_start.max() > 0 else np.zeros_like(days_since_start))
    r_spiral = spiral_a + spiral_b * days_since_start
    if days_since_start.max() > days_since_start.min():
        t_norm = ((days_since_start - days_since_start.min())
                  / (days_since_start.max() - days_since_start.min()))
    else:
        t_norm = np.zeros_like(days_since_start, dtype=float)
    return df, days_since_start, theta_time, r_spiral, t_norm


def angle_diff_deg(a_curr: pd.Series, a_prev: pd.Series) -> pd.Series:
    return (a_curr - a_prev + 180.0) % 360.0 - 180.0


def compute_delta_table(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df["date"] = pd.to_datetime(df["date_tag"])
    df = (df.sort_values(["date", "epoch_jd"])
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True))
    for col in angle_cols:
        df[f"delta_{col}"] = angle_diff_deg(df[col], df[col].shift(1))
    df["delta_sma_km"] = df["sma_km"] - df["sma_km"].shift(1)
    out_cols = (["date", "norad_id", "sma_km", "delta_sma_km"]
                + angle_cols + [f"delta_{c}" for c in angle_cols])
    return df[out_cols]


def calculate_ric_deltas(df):
    df = df.copy()
    if df.empty:
        df["dv_intrack"] = []
        df["dv_crosstrack"] = []
        return df
    sma_smooth = df["sma_km"].rolling(window=3, center=True).mean().fillna(df["sma_km"])
    v_mag = np.sqrt(MU / sma_smooth)
    df["dv_intrack"] = ((v_mag / 2.0) * (sma_smooth.diff() / sma_smooth)) * 1000.0
    di  = np.radians(df["inclination_deg"].diff())
    dO  = np.radians(df["raan_deg"].diff())
    inc = np.radians(df["inclination_deg"])
    df["dv_crosstrack"] = (v_mag * np.sqrt(di**2 + (np.sin(inc) * dO)**2)) * 1000.0
    df[["dv_intrack", "dv_crosstrack"]] = df[["dv_intrack", "dv_crosstrack"]].fillna(0)
    return df


# ============================================================
# Maneuver Detection
# ============================================================

def detect_ric_events(df, column, threshold_mult=5.0, alt_km=None):
    series = df[column].abs()
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0:
        mad = 1e-6
    z_score = (series - median) / mad
    if alt_km is not None and alt_km >= 12_000:
        min_dv = 0.005
    elif alt_km is not None and alt_km < 500:
        min_dv = 0.5
    elif alt_km is not None and alt_km >= 700:
        min_dv = 0.01
    else:
        min_dv = 0.05
    return (z_score > threshold_mult) & (series > min_dv)


def detect_maneuvers_refined_adaptive(df):
    df_out = df.copy()
    if df_out.empty:
        return df_out, pd.DataFrame(columns=["idx", "epoch", "sma_delta"]), 4.0
    df_out.columns = df_out.columns.str.strip()
    df_out["epoch"] = pd.to_datetime(df_out["epoch"])
    df_out = (df_out.sort_values(["epoch", "epoch_jd"])
                    .drop_duplicates(subset=["epoch"], keep="last")
                    .reset_index(drop=True))
    df_out = (df_out.set_index("epoch").resample("D").ffill()
                    .reset_index().sort_values("epoch").reset_index(drop=True))
    if len(df_out) < 2:
        for col in ["sma_rate", "sma_delta", "residual", "z_score"]:
            df_out[col] = 0.0
        df_out["is_candidate"] = False
        df_out["is_maneuver"]  = False
        return df_out, pd.DataFrame(columns=["idx", "epoch", "sma_delta"]), 4.0
    dt_hours = df_out["epoch"].diff().dt.total_seconds().bfill() / 3600
    dt_hours = dt_hours.replace(0, 24)
    df_out["sma_rate"]  = df_out["sma_km"].diff() / dt_hours
    df_out["sma_delta"] = df_out["sma_km"].diff().abs()
    alt_avg = df_out["sma_km"].mean() - R_EARTH
    if 300 <= alt_avg < 500:
        mult = 7.0;  window = 3;  rate_mult = 8.0; rate_floor = 0.10
    elif 500 <= alt_avg < 600:
        mult = 4.0;  window = 7;  rate_mult = 6.0; rate_floor = 0.02
    elif 600 <= alt_avg < 700:
        mult = 3.5;  window = 7;  rate_mult = 6.0; rate_floor = 0.02
    elif 700 <= alt_avg < 1200:
        mult = 3.0;  window = 10; rate_mult = 4.0; rate_floor = 0.005
    elif alt_avg >= 12_000:
        mult = 2.5;  window = 21; rate_mult = 3.0; rate_floor = 0.0001
    else:
        mult = 4.0;  window = 7;  rate_mult = 6.0; rate_floor = 0.01
    ref_rate = df_out["sma_rate"].rolling(window, center=True, min_periods=3).median()
    df_out["residual"] = (df_out["sma_rate"] - ref_rate).abs()
    mad_rate = df_out["residual"].rolling(window, center=True, min_periods=3).median()
    mad_rate = mad_rate.fillna(max(mad_rate.median(), 1e-9))
    df_out["z_score"] = df_out["residual"] / mad_rate
    delta = df_out["sma_delta"].dropna()
    d_med = delta.median() if not delta.empty else 0.0
    d_mad = max((delta - d_med).abs().median() if not delta.empty else 0.0, max(d_med * 0.1, 1e-9))
    delta_thr = d_med + mult * d_mad
    rate_abs = df_out["sma_rate"].abs().dropna()
    r_med = rate_abs.median() if not rate_abs.empty else 0.0
    r_mad = max((rate_abs - r_med).abs().median() if not rate_abs.empty else 0.0, max(r_med * 0.1, 1e-9))
    rate_thr = max(r_med + rate_mult * r_mad, rate_floor)
    df_out["is_candidate"] = (df_out["sma_delta"] >= delta_thr) & (df_out["sma_rate"].abs() >= rate_thr)
    clusters, buf = [], []
    for idx_i, flag in enumerate(df_out["is_candidate"]):
        if flag:
            buf.append(idx_i)
        else:
            if buf:
                clusters.append(buf); buf = []
    if buf:
        clusters.append(buf)
    df_out["is_maneuver"] = False
    events = []
    for c in clusters:
        peak = df_out.loc[c, "sma_delta"].idxmax()
        if peak in df_out.index:
            df_out.loc[peak, "is_maneuver"] = True
            events.append({
                "idx": peak,
                "epoch": df_out.loc[peak, "epoch"],
                "sma_delta": df_out.loc[peak, "sma_delta"],
                "sma_direction": "raise" if df_out.loc[peak, "sma_rate"] > 0 else "lower",
            })
    return df_out, pd.DataFrame(events), mult


# ============================================================
# Data Loading
# ============================================================

def load_data(norad_id, start_date, end_date):
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        query = f"""
        SELECT epoch_jd, date_tag, norad_id, sma_km, eccentricity,
               inclination_deg, raan_deg, argp_deg, mean_anomaly_deg
        FROM {TABLE_NAME}
        WHERE norad_id = ?
          AND DATE(date_tag) BETWEEN DATE(?) AND DATE(?)
        ORDER BY date_tag
        """
        df = conn.execute(query, [int(norad_id), start_date, end_date]).df()
        conn.close()
        if not df.empty:
            df["epoch"] = pd.to_datetime(df["date_tag"], errors="coerce").astype("datetime64[ns]")
            df = (df.sort_values(["epoch", "epoch_jd"])
                    .drop_duplicates(subset=["epoch"], keep="last")
                    .reset_index(drop=True))
        return df
    except Exception as e:
        lang = st.session_state.get("lang", "zh")
        st.error(f"{T('db_read_failed', lang)}: {e}")
    return pd.DataFrame()


def ensure_datetime64ns(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df[col] = pd.to_datetime(df[col], errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        df[col] = df[col].astype("datetime64[ns]")
    return df


# ============================================================
# 3D Orbit Plot
# ============================================================

def plot_3d_orbit_scene_multi(df_raw, target_id):
    R_earth = 6371.0
    fig = go.Figure()
    u, v_sph = np.linspace(0, 2 * np.pi, 50), np.linspace(0, np.pi, 50)
    fig.add_trace(go.Surface(
        x=R_earth * np.outer(np.cos(u), np.sin(v_sph)),
        y=R_earth * np.outer(np.sin(u), np.sin(v_sph)),
        z=R_earth * np.outer(np.ones(np.size(u)), np.cos(v_sph)),
        colorscale="Blues", showscale=False, opacity=0.5, hoverinfo="skip",
    ))
    n_steps = len(df_raw)
    if n_steps == 0:
        return fig
    colors = px.colors.sample_colorscale(
        "RdBu", [i / (n_steps - 1) if n_steps > 1 else 0 for i in range(n_steps)]
    )
    t_ang = np.linspace(0, 2 * np.pi, 100)
    step = max(1, n_steps // 50)
    latest_xyz = None
    for ii in range(0, n_steps, step):
        row  = df_raw.iloc[ii]
        sma  = row["sma_km"]
        inc  = np.radians(row["inclination_deg"])
        raan = np.radians(row["raan_deg"])
        xp = sma * np.cos(t_ang);  yp = sma * np.sin(t_ang)
        xo = np.cos(raan) * xp - np.sin(raan) * np.cos(inc) * yp
        yo = np.sin(raan) * xp + np.cos(raan) * np.cos(inc) * yp
        zo = np.sin(inc) * yp
        latest_xyz = (xo[0], yo[0], zo[0])
        is_last  = (ii >= n_steps - step)
        is_first = (ii == 0)
        fig.add_trace(go.Scatter3d(
            x=xo, y=yo, z=zo, mode="lines",
            line=dict(color=colors[ii], width=4 if (is_last or is_first) else 2),
            opacity=1.0 if (is_last or is_first) else 0.3,
            name=str(row["date_tag"]),
            showlegend=bool(is_last or is_first),
        ))
    if latest_xyz is not None:
        fig.add_trace(go.Scatter3d(
            x=[latest_xyz[0]], y=[latest_xyz[1]], z=[latest_xyz[2]],
            mode="markers", marker=dict(size=8, color="blue", symbol="diamond"),
            name="Latest Position",
        ))
    lang = st.session_state.get("lang", "zh")
    fig.update_layout(
        scene=dict(aspectmode="data", bgcolor="rgb(5,5,15)"),
        margin=dict(l=0, r=0, b=0, t=30), height=700,
        title=(f"{T('orbit_evolution_title', lang)}: "
               "<span style='color:red'>Early</span> → <span style='color:blue'>Recent</span>"),
    )
    return fig


# ============================================================
# MEME / Galileo Residuals
# ============================================================

_RESID_COLS = [
    "norad_id", "sat_name", "t",
    "dr_r_km", "dr_t_km", "dr_n_km",
    "pos_err_km", "vel_err_kms",
    "tle_epoch", "tle_age_days",
]


def load_meme_residuals(norad_id, start_date: str, end_date: str) -> pd.DataFrame:
    comp_dir = Path(COMPARISON_DIR)
    if not comp_dir.exists():
        return pd.DataFrame()
    csvs = sorted(comp_dir.glob("residuals_*.csv"), reverse=True)
    if not csvs:
        return pd.DataFrame()
    nid     = int(norad_id)
    t_start = pd.Timestamp(start_date, tz="UTC")
    t_end   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    for csv_path in csvs:
        try:
            con = duckdb.connect(":memory:")
            df = con.execute(f"""
                SELECT * FROM read_csv_auto('{csv_path.as_posix()}', ignore_errors=true)
                WHERE CAST(norad_id AS INTEGER) = {nid}
            """).fetchdf()
            con.close()
            if df.empty:
                continue
            df = df[[c for c in _RESID_COLS if c in df.columns]]
            df["t"] = pd.to_datetime(df["t"], utc=True)
            df = df[(df["t"] >= t_start) & (df["t"] < t_end)]
            if not df.empty:
                return df.sort_values("t").reset_index(drop=True)
        except Exception:
            continue
    return pd.DataFrame()


_GALILEO_PRN_NORAD = {
    "E02": 41549, "E03": 41860, "E04": 41861, "E05": 41862,
    "E06": 59600, "E07": 41859, "E08": 41175, "E09": 41174,
    "E10": 49810, "E11": 37846, "E12": 37847, "E13": 43567,
    "E14": 40129, "E15": 43564, "E16": 61182, "E18": 40128,
    "E19": 38857, "E21": 43055, "E23": 61183, "E25": 43056,
    "E26": 40544, "E27": 43057, "E28": 67160, "E29": 59598,
    "E30": 40890, "E31": 43058, "E32": 67162, "E33": 43565,
    "E34": 49809, "E36": 43566,
}


def load_galileo_sp3_residuals(sat_id, start_date: str, end_date: str) -> pd.DataFrame:
    gal_dir = Path(GALILEO_COMPARISON_DIR)
    if not gal_dir.exists():
        return pd.DataFrame()
    csvs = sorted(gal_dir.glob("residuals_*.csv"), reverse=True)
    if not csvs:
        return pd.DataFrame()
    if isinstance(sat_id, str) and sat_id.upper().startswith("E"):
        nid = _GALILEO_PRN_NORAD.get(sat_id.upper())
        if nid is None:
            return pd.DataFrame()
    else:
        try:
            nid = int(sat_id)
        except (ValueError, TypeError):
            return pd.DataFrame()
    t_start = pd.Timestamp(start_date, tz="UTC")
    t_end   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    for csv_path in csvs:
        try:
            con = duckdb.connect(":memory:")
            df = con.execute(f"""
                SELECT * FROM read_csv_auto('{csv_path.as_posix()}', ignore_errors=true)
                WHERE CAST(norad_id AS INTEGER) = {nid}
            """).fetchdf()
            con.close()
            if df.empty:
                continue
            df = df[[c for c in _RESID_COLS if c in df.columns]]
            df["t"] = pd.to_datetime(df["t"], utc=True)
            df = df[(df["t"] >= t_start) & (df["t"] < t_end)]
            if not df.empty:
                return df.sort_values("t").reset_index(drop=True)
        except Exception:
            continue
    return pd.DataFrame()


def detect_maneuvers_rtn(resid_df: pd.DataFrame, z_thr=None) -> pd.DataFrame:
    required = {"t", "dr_t_km", "dr_n_km", "dr_r_km", "pos_err_km"}
    if resid_df.empty or not required.issubset(resid_df.columns):
        return pd.DataFrame()
    df = resid_df.sort_values("t").copy()
    df["t"] = pd.to_datetime(df["t"], utc=True)
    if z_thr is None:
        age   = float(df["tle_age_days"].median()) if "tle_age_days" in df.columns else 7.0
        z_thr = 4.0 if age <= 3 else (5.0 if age <= 7 else (6.0 if age <= 14 else 7.0))
    dt_h = df["t"].diff().dt.total_seconds().fillna(600.0) / 3600.0
    dt_h = dt_h.clip(lower=1e-4)
    events = []
    for col, mtype in [("dr_t_km", "in-plane"), ("dr_n_km", "out-of-plane")]:
        step = df[col].diff().abs()
        rate = step / dt_h
        med  = rate.median()
        mad  = (rate - med).abs().median()
        if mad < 1e-9:
            mad = rate.std() if rate.std() > 1e-9 else 1e-9
        z       = (rate - med) / mad
        flagged = df.index[z > z_thr].tolist()
        if not flagged:
            continue
        clusters, buf = [], [flagged[0]]
        for ix in flagged[1:]:
            if ix - buf[-1] <= 3:
                buf.append(ix)
            else:
                clusters.append(buf); buf = [ix]
        clusters.append(buf)
        for cluster in clusters:
            peak_ix = z.loc[cluster].idxmax()
            row = df.loc[peak_ix]
            events.append({
                "epoch":          row["t"],
                "type":           mtype,
                "dr_t_km":        row["dr_t_km"],
                "dr_n_km":        row["dr_n_km"],
                "dr_r_km":        row["dr_r_km"],
                "pos_err_km":     row["pos_err_km"],
                "step_km":        round(float(step.loc[peak_ix]), 3),
                "step_rate_km_h": round(float(rate.loc[peak_ix]), 3),
                "z_score":        round(float(z.loc[peak_ix]), 1),
                "tle_age_days":   round(float(row.get("tle_age_days", np.nan)), 2),
            })
    if not events:
        return pd.DataFrame()
    result = pd.DataFrame(events).sort_values("epoch").reset_index(drop=True)
    result["_epoch_h"] = result["epoch"].dt.floor("h")
    result = (result.sort_values("z_score", ascending=False)
                    .drop_duplicates("_epoch_h")
                    .sort_values("epoch")
                    .drop(columns="_epoch_h")
                    .reset_index(drop=True))
    return result


# ============================================================
# GEO Support
# ============================================================

def _geo_gmst(jd: np.ndarray) -> np.ndarray:
    return (280.460_618_37 + 360.985_647_366_29 * (jd - 2_451_545.0)) % 360.0


def _geo_mean_lon(raan, argp, ma, jd) -> np.ndarray:
    raw = (raan + argp + ma - _geo_gmst(jd)) % 360.0
    return np.where(raw > 180.0, raw - 360.0, raw)


def load_geo_raw_series(norad_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        df = con.execute("""
            SELECT epoch_jd, epoch_utc, raan_deg, argp_deg, mean_anomaly_deg,
                   inclination_deg, eccentricity, sma_km
            FROM raw_tle_archive
            WHERE norad_id = ?
              AND epoch_utc >= ? AND epoch_utc <= ?
            ORDER BY epoch_jd
        """, [norad_id, start_date, end_date]).df()
        con.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["_b"] = (df["epoch_jd"] / 0.04).astype(int)
    df = df.drop_duplicates(subset=["_b"]).drop(columns=["_b"]).reset_index(drop=True)
    df["lambda_deg"] = _geo_mean_lon(
        df["raan_deg"].values, df["argp_deg"].values,
        df["mean_anomaly_deg"].values, df["epoch_jd"].values,
    )
    dt = df["epoch_jd"].diff()
    dl = (df["lambda_deg"].diff() + 180.0) % 360.0 - 180.0
    df["drift_deg_day"] = np.where(dt >= 0.05, dl / dt, np.nan)
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True, errors="coerce")
    return df


def load_geo_events(norad_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    if not GEO_MANEUVER_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GEO_MANEUVER_CSV)
    df = df[df["norad_id"] == norad_id].copy()
    if df.empty:
        return df
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True, errors="coerce")
    t0 = pd.Timestamp(start_date, tz="UTC")
    t1 = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    return df[(df["epoch_utc"] >= t0) & (df["epoch_utc"] <= t1)].reset_index(drop=True)


# ============================================================
# GEO Page Renderer (Bilingual)
# ============================================================

def render_geo_page(norad_id: int, start_date: str, end_date: str, lang: str, learn_mode: str) -> None:
    events = load_geo_events(norad_id, start_date, end_date)
    series = load_geo_raw_series(norad_id, start_date, end_date)

    obj_name = (events["object_name"].iloc[0]
                if not events.empty and "object_name" in events.columns
                else f"NORAD-{norad_id}")

    st.subheader(T("sub_geo_analysis", lang).format(name=obj_name, norad=norad_id))
    st.caption(T("sub_geo_period", lang).format(s=start_date, e=end_date))

    _show_concept_if(learn_mode, "geo", lang, "🌐")

    if events.empty and series.empty:
        st.warning(T("msg_no_geo_data", lang).format(norad=norad_id))
        return

    def _cnt(t, conf=None):
        if events.empty:
            return 0
        mask = events["type"] == t
        if conf is not None:
            mask = mask & (events["confirmed"] == conf)
        return int(mask.sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(T("geo_ew_confirmed", lang), _cnt("EW", True),      help=T("geo_ew_help", lang))
    c2.metric(T("geo_ns_confirmed", lang), _cnt("NS", True),      help=T("geo_ns_help", lang))
    c3.metric(T("geo_reposition",   lang), _cnt("REPOSITIONING"), help=T("geo_reposition_help", lang))
    c4.metric(T("geo_disposal",     lang), _cnt("DISPOSAL"),      help=T("geo_disposal_help", lang))
    c5.metric(T("geo_tle_gap",      lang), _cnt("TLE_GAP"),       help=T("geo_gap_help", lang))

    tab_lon, tab_inc, tab_table = st.tabs([
        T("geo_tab_lon", lang),
        T("geo_tab_inc", lang),
        T("geo_tab_table", lang),
    ])

    with tab_lon:
        if series.empty:
            st.info(T("geo_no_series", lang))
        else:
            ew_ev  = events[events["type"] == "EW"]      if not events.empty else pd.DataFrame()
            gap_ev = events[events["type"] == "TLE_GAP"] if not events.empty else pd.DataFrame()

            fig_lon = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                subplot_titles=[T("geo_lon_sub1", lang), T("geo_lon_sub2", lang)],
                vertical_spacing=0.10,
            )
            fig_lon.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["lambda_deg"],
                name=T("axis_lon", lang), line=dict(color="deepskyblue", width=1.5),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>λ = %{y:.3f}°<extra></extra>",
            ), row=1, col=1)
            fig_lon.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["drift_deg_day"],
                name=T("axis_drift", lang), line=dict(color="lightgreen", width=1.2),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>drift = %{y:.4f} °/day<extra></extra>",
            ), row=2, col=1)
            fig_lon.add_hline(y=0.0, row=2, col=1, line_dash="dash", line_color="gray", opacity=0.5)

            if not gap_ev.empty:
                for _, g in gap_ev.iterrows():
                    t_end_g   = g["epoch_utc"]
                    gap_days  = float(g["gap_days"]) if pd.notna(g.get("gap_days")) else 4.0
                    t_start_g = t_end_g - pd.Timedelta(days=gap_days)
                    fig_lon.add_vrect(x0=t_start_g, x1=t_end_g,
                                      fillcolor="yellow", opacity=0.12, line_width=0,
                                      annotation_text="TLE Gap", annotation_position="top left")

            if not ew_ev.empty:
                valid_ser = series[series["lambda_deg"].notna() & series["epoch_utc"].notna()]
                ser_t_ns  = valid_ser["epoch_utc"].astype(np.int64).values if len(valid_ser) > 1 else np.array([0])
                ser_l     = valid_ser["lambda_deg"].values                  if len(valid_ser) > 1 else np.array([0.0])
                conf_ew = ew_ev[ew_ev["confirmed"] == True]
                uncf_ew = ew_ev[ew_ev["confirmed"] == False]
                for subset, color, sym, label_key in [
                    (conf_ew,  "red",    "triangle-up",      "label_ew_confirmed"),
                    (uncf_ew,  "orange", "triangle-up-open", "label_ew_unconfirmed"),
                ]:
                    if subset.empty:
                        continue
                    ev_t_ns = subset["epoch_utc"].astype(np.int64).values
                    ev_l    = np.interp(ev_t_ns, ser_t_ns, ser_l)
                    ev_d    = subset["drift_after"].values if "drift_after" in subset.columns else np.full(len(subset), np.nan)
                    hover = [
                        f"<b>EW {'✓' if r['confirmed'] else '?'}</b><br>"
                        f"{str(r['epoch_utc'])[:19]} UTC<br>"
                        f"drift: {r.get('drift_before', np.nan):.4f} → {r.get('drift_after', np.nan):.4f} °/day<br>"
                        f"Δdrift: {r.get('delta_drift', np.nan):.4f} °/day"
                        for _, r in subset.iterrows()
                    ]
                    for panel_row, ydata in [(1, ev_l), (2, ev_d)]:
                        fig_lon.add_trace(go.Scatter(
                            x=subset["epoch_utc"], y=ydata, mode="markers",
                            name=T(label_key, lang),
                            marker=dict(color=color, size=13, symbol=sym,
                                        line=dict(width=1.5, color="white")),
                            hovertext=hover, hoverinfo="text",
                            showlegend=(panel_row == 1),
                        ), row=panel_row, col=1)

            fig_lon.update_layout(template="plotly_dark", height=620,
                                  legend=dict(orientation="h", y=-0.08),
                                  margin=dict(l=60, r=30, t=60, b=60))
            st.plotly_chart(fig_lon, use_container_width=True, key=f"geo_lon_{norad_id}")

            if not ew_ev.empty:
                conf_summary = ew_ev[ew_ev["confirmed"] == True]
                if not conf_summary.empty:
                    st.caption(T("geo_ew_summary", lang).format(
                        n=len(conf_summary),
                        v=conf_summary["delta_drift"].abs().max(),
                    ))

    with tab_inc:
        if series.empty:
            st.info(T("geo_no_series_inc", lang))
        else:
            ns_ev = events[events["type"] == "NS"] if not events.empty else pd.DataFrame()
            fig_inc = go.Figure()
            fig_inc.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["inclination_deg"],
                name=T("axis_inc", lang), line=dict(color="violet", width=1.5),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>i = %{y:.4f}°<extra></extra>",
            ))
            if not ns_ev.empty:
                valid_ser = series[series["inclination_deg"].notna() & series["epoch_utc"].notna()]
                ser_t_ns  = valid_ser["epoch_utc"].astype(np.int64).values if len(valid_ser) > 1 else np.array([0])
                ser_i     = valid_ser["inclination_deg"].values             if len(valid_ser) > 1 else np.array([0.0])
                conf_ns = ns_ev[ns_ev["confirmed"] == True]
                uncf_ns = ns_ev[ns_ev["confirmed"] == False]
                for subset, color, sym, label_key in [
                    (conf_ns,  "magenta", "star",      "label_ns_confirmed"),
                    (uncf_ns,  "pink",    "star-open", "label_ns_unconfirmed"),
                ]:
                    if subset.empty:
                        continue
                    ev_t_ns = subset["epoch_utc"].astype(np.int64).values
                    ev_i    = np.interp(ev_t_ns, ser_t_ns, ser_i)
                    hover = [
                        f"<b>NS {'✓' if r['confirmed'] else '?'}</b><br>"
                        f"{str(r['epoch_utc'])[:19]} UTC<br>"
                        f"i: {r.get('i_before', np.nan):.4f}° → {r.get('i_after', np.nan):.4f}°<br>"
                        f"Δi = {r.get('delta_i_deg', np.nan):.4f}°<br>"
                        f"ΔRAAN_res = {r.get('delta_raan_residual_deg', np.nan):.3f}°"
                        for _, r in subset.iterrows()
                    ]
                    fig_inc.add_trace(go.Scatter(
                        x=subset["epoch_utc"], y=ev_i, mode="markers",
                        name=T(label_key, lang),
                        marker=dict(color=color, size=15, symbol=sym,
                                    line=dict(width=1.5, color="white")),
                        hovertext=hover, hoverinfo="text",
                    ))
            fig_inc.update_layout(template="plotly_dark", height=420,
                                  yaxis_title=T("axis_inc", lang),
                                  legend=dict(orientation="h"),
                                  margin=dict(l=60, r=30, t=50, b=40))
            st.plotly_chart(fig_inc, use_container_width=True, key=f"geo_inc_{norad_id}")
            if not ns_ev.empty:
                st.markdown(f"**{T('ns_detail', lang)}**")
                ns_cols = [c for c in ["epoch_utc", "confirmed", "i_before", "i_after",
                                       "delta_i_deg", "delta_raan_residual_deg"] if c in ns_ev.columns]
                fmt_ns = {k: "{:.4f}" for k in ["i_before", "i_after", "delta_i_deg", "delta_raan_residual_deg"]}
                st.dataframe(ns_ev[ns_cols].style.format(fmt_ns), use_container_width=True)

    with tab_table:
        if events.empty:
            st.info(T("geo_no_events", lang))
        else:
            if learn_mode == "learn_advanced":
                _show_concept_if(learn_mode, "event", lang, "🔬")
            _ICONS = {"EW": "🔴", "NS": "🟣", "REPOSITIONING": "🟡", "DISPOSAL": "⚫", "TLE_GAP": "🟤"}
            disp = events.copy()
            disp.insert(0, "", disp["type"].map(lambda t_: _ICONS.get(t_, "⚪")))
            fmt_tbl = {k: "{:.4f}" for k in ["drift_before", "drift_after", "delta_drift",
                                               "i_before", "i_after", "delta_i_deg"]}
            fmt_tbl["sma_km"] = "{:.2f}"
            tbl_cols = [c for c in ["", "epoch_utc", "type", "confirmed",
                                    "drift_before", "drift_after", "delta_drift",
                                    "i_before", "i_after", "delta_i_deg",
                                    "sma_km", "gap_days"] if c in disp.columns]
            st.dataframe(disp[tbl_cols].style.format(fmt_tbl),
                         use_container_width=True, key=f"geo_tbl_{norad_id}")
            st.download_button(
                T("download_event_csv", lang),
                data=events.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"geo_events_{norad_id}_{start_date}_{end_date}.csv",
                mime="text/csv",
            )


# ============================================================
# RTN Chart Helper (shared by MEME + Galileo)
# ============================================================

def _render_rtn_chart(resid_df, rtn_events, satellite_id, panel_idx, lang, chart_key_prefix):
    fig_rtn = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        subplot_titles=[
            T("rtn_subplot_t",   lang),
            T("rtn_subplot_n",   lang),
            T("rtn_subplot_pos", lang),
        ],
        vertical_spacing=0.08,
    )
    fig_rtn.add_trace(go.Scatter(x=resid_df["t"], y=resid_df["dr_t_km"],
                                  name="dr_t", line=dict(color="deepskyblue", width=1.2)), row=1, col=1)
    fig_rtn.add_trace(go.Scatter(x=resid_df["t"], y=resid_df["dr_n_km"],
                                  name="dr_n", line=dict(color="mediumseagreen", width=1.2)), row=2, col=1)
    fig_rtn.add_trace(go.Scatter(x=resid_df["t"], y=resid_df["pos_err_km"],
                                  name="pos_err", line=dict(color="gold", width=1.2)), row=3, col=1)

    if not rtn_events.empty:
        inplane  = rtn_events[rtn_events["type"] == "in-plane"]
        outplane = rtn_events[rtn_events["type"] == "out-of-plane"]
        for evs, panel_row, val_col, color, label_key in [
            (inplane,  1, "dr_t_km", "red",     "label_inplane"),
            (outplane, 2, "dr_n_km", "magenta", "label_outplane"),
        ]:
            if not evs.empty:
                fig_rtn.add_trace(go.Scatter(
                    x=evs["epoch"], y=evs[val_col], mode="markers",
                    marker=dict(color=color, size=13, symbol="star",
                                line=dict(width=1, color="white")),
                    name=T(label_key, lang),
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        f"{val_col}: %{{y:.3f}} km<br>"
                        "step: %{customdata[0]:.4f} km<br>"
                        "z: %{customdata[1]:.1f}"
                    ),
                    customdata=evs[["step_km", "z_score"]].values,
                ), row=panel_row, col=1)

    fig_rtn.update_layout(template="plotly_dark", height=680,
                          legend=dict(orientation="h", y=-0.05),
                          margin=dict(l=60, r=30, t=60, b=50))
    st.plotly_chart(fig_rtn, use_container_width=True,
                    key=f"{chart_key_prefix}_{satellite_id}_{panel_idx}")


def _render_event_table_rtn(rtn_events, lang, learn_mode, table_key):
    if rtn_events.empty:
        st.success(T("msg_no_event", lang))
        return
    evs = _add_reason_cols(rtn_events, "type", "z_score", "step_km", window=3)
    fmt = {
        "dr_t_km": "{:.3f}", "dr_n_km": "{:.3f}", "dr_r_km": "{:.3f}",
        "pos_err_km": "{:.3f}", "step_km": "{:.4f}",
        "step_rate_km_h": "{:.4f}", "z_score": "{:.1f}", "tle_age_days": "{:.2f}",
    }
    base_cols = [c for c in ["epoch", "type", "dr_t_km", "dr_n_km", "dr_r_km",
                               "pos_err_km", "step_km", "step_rate_km_h",
                               "z_score", "tle_age_days"] if c in evs.columns]
    if learn_mode == "learn_advanced":
        reason_col = "reason_zh" if lang == "zh" else "reason_en"
        base_cols += [reason_col]
    st.dataframe(evs[base_cols].style.format(fmt), use_container_width=True, key=table_key)


# ============================================================
# Streamlit App Entry Point
# ============================================================

st.set_page_config(
    page_title=APP_NAME_EN,
    page_icon="🛰️",
    layout="wide",
)

# ── Session state defaults ────────────────────────────────────
if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"
if "learn_mode" not in st.session_state:
    st.session_state["learn_mode"] = "learn_data"

# ── Query params ──────────────────────────────────────────────
try:
    params = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
    def _get_param(name, default):
        val = params.get(name, default)
        return (val[0] if isinstance(val, list) and val else val) if isinstance(val, list) else val
    default_norad = _get_param("norad", "49336, 42738, 42917, 42965, 62876")
    default_start = _get_param("start", "2024-01-01")
    default_end   = _get_param("end",   "2026-03-30")
except Exception:
    default_norad = "49336, 42738, 42917, 42965, 62876"
    default_start = "2024-01-01"
    default_end   = "2026-03-30"

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    lang_choice = st.radio(
        "🌐 Language / 語言",
        options=["zh", "en"],
        format_func=lambda x: "中文" if x == "zh" else "English",
        horizontal=True,
        key="lang",
    )
    lang = st.session_state["lang"]

    st.divider()
    learn_mode = st.radio(
        T("sidebar_learn_mode", lang),
        options=["learn_concept", "learn_data", "learn_advanced"],
        format_func=lambda k: T(k, lang),
        horizontal=False,
        key="learn_mode",
    )

    st.divider()
    page = st.radio(
        T("sidebar_mode", lang),
        [T("mode_leo_meo", lang), T("mode_geo", lang)],
        horizontal=True,
    )

    st.divider()
    if page == T("mode_leo_meo", lang):
        raw_input  = st.text_input(T("sidebar_norad", lang), value=default_norad)
        target_ids = [x.strip() for x in raw_input.split(",") if x.strip()]
        col_d1, col_d2 = st.columns(2)
        start_d = col_d1.date_input(T("sidebar_start", lang), datetime.fromisoformat(default_start))
        end_d   = col_d2.date_input(T("sidebar_end",   lang), datetime.fromisoformat(default_end))
        st.divider()
        st.subheader(T("sidebar_plot", lang))
        ma_val       = st.slider(T("sidebar_ma", lang), 1, 14, 1)
        show_sampled = st.checkbox(T("sidebar_raw", lang), value=True)
        run_btn      = st.button(T("sidebar_run", lang), type="primary")
        geo_norad_id = 36032
        geo_start_d  = datetime.fromisoformat("2026-03-01").date()
        geo_end_d    = datetime.fromisoformat("2026-05-02").date()
    else:
        geo_norad_id = int(st.number_input(
            T("sidebar_geo_norad", lang),
            value=36032, min_value=1, step=1,
            help="預設 36032：Apr 3-4 EW 機動 + Apr 21 NS 修正（驗證範例）",
        ))
        col_g1, col_g2 = st.columns(2)
        geo_start_d = col_g1.date_input(T("sidebar_start", lang), datetime.fromisoformat("2026-03-01"))
        geo_end_d   = col_g2.date_input(T("sidebar_end",   lang), datetime.fromisoformat("2026-05-02"))
        raw_input = ""; target_ids = []; run_btn = False
        start_d = end_d = datetime.fromisoformat("2026-01-01").date()
        ma_val = 1; show_sampled = False

    st.divider()
    st.caption(f"{T('version_label', lang)}: {APP_VERSION}")

# ── Page Title ────────────────────────────────────────────────
st.title(f"🛰️ {T('title', lang)}")
st.markdown(f"*{T('tagline', lang)}*")

# ── Always-visible concept: TLE (shown in concept & data modes) ──
if learn_mode in ("learn_concept", "learn_data"):
    concept_card("tle", lang, "📡")

# ── Glossary always available ─────────────────────────────────
terms_glossary_card(lang)

# ── GEO page ─────────────────────────────────────────────────
if page == T("mode_geo", lang):
    render_geo_page(
        geo_norad_id,
        geo_start_d.strftime("%Y-%m-%d"),
        geo_end_d.strftime("%Y-%m-%d"),
        lang, learn_mode,
    )
    st.stop()

# ── LEO / MEO page ────────────────────────────────────────────
shared_layout = dict(
    margin=dict(l=80, r=80, t=80, b=40),
    hovermode="x unified",
    template="plotly_dark",
    xaxis=dict(showgrid=True, gridcolor="gray", range=[start_d, end_d]),
)

if not run_btn:
    st.info(T("msg_run_prompt", lang))
    st.stop()

if not target_ids:
    st.error(T("msg_enter_norad", lang))
    st.stop()

f107_data = fetch_f107_data()

for i, satellite_id in enumerate(target_ids):
    with st.container():
        st.subheader(f"📡 {T('sub_satellite_report', lang).format(sid=satellite_id)}")

        df_raw = load_data(satellite_id, start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d"))
        if df_raw.empty:
            st.warning(f"⚠️ {T('msg_no_data', lang).format(sid=satellite_id)}")
            st.divider()
            continue

        df_processed, event_df, used_mult = detect_maneuvers_refined_adaptive(df_raw)
        alt_km_avg = float(df_processed["sma_km"].mean() - R_EARTH) if not df_processed.empty else None

        # Orbit-type concept card
        if alt_km_avg is not None:
            if alt_km_avg >= 12_000:
                _show_concept_if(learn_mode, "meo", lang, "🔭")
                if learn_mode != "learn_concept":
                    st.warning(f"⚠️ {T('msg_meo_warning', lang).format(sid=satellite_id, alt=alt_km_avg)}")
            else:
                _show_concept_if(learn_mode, "leo", lang, "🛰️")

        # Merge F10.7
        if not f107_data.empty:
            left_df  = ensure_datetime64ns(df_processed, "epoch").sort_values("epoch").reset_index(drop=True)
            right_df = ensure_datetime64ns(f107_data,    "epoch").sort_values("epoch").reset_index(drop=True)
            df_final = pd.merge_asof(left_df, right_df, on="epoch", direction="nearest")
        else:
            df_final = df_processed.copy()

        df_final = calculate_ric_deltas(df_final)
        df_final["sma_visual"] = df_final["sma_km"].rolling(window=ma_val, min_periods=1, center=True).mean()

        # ── Tabs ──────────────────────────────────────────────
        tab_analysis, tab_ric, tab_3d, tab_delta, tab_spiral, tab_longaxis, tab_meme, tab_galileo = st.tabs([
            T("tab_analysis", lang), T("tab_ric",       lang), T("tab_3d",       lang),
            T("tab_delta",    lang), T("tab_spiral",    lang), T("tab_longaxis", lang),
            T("tab_meme",     lang), T("tab_galileo",   lang),
        ])

        # ── Tab: Trend Analysis ───────────────────────────────
        with tab_analysis:
            _show_concept_if(learn_mode, "f107", lang, "☀️")

            m1, m2, m3 = st.columns(3)
            m1.metric(T("metric_points",    lang), len(df_final))
            m2.metric(T("metric_maneuvers", lang), int(df_final["is_maneuver"].sum()))
            m3.metric(T("metric_max_da",    lang),
                      f"{event_df['sma_delta'].max():.4f} km" if not event_df.empty else "N/A")

            fig_2d = go.Figure()
            fig_2d.add_trace(go.Scatter(
                x=df_final["epoch"], y=df_final["sma_visual"],
                name=T("axis_sma", lang), line=dict(color="#00CCFF"),
            ))
            if "f107" in df_final.columns:
                fig_2d.add_trace(go.Scatter(
                    x=df_final["epoch"], y=df_final["f107"],
                    name=T("axis_f107", lang), yaxis="y2",
                    line=dict(dash="dot", color="orange"), opacity=0.4,
                ))
            manv_pts = df_final[df_final["is_maneuver"]]
            fig_2d.add_trace(go.Scatter(
                x=manv_pts["epoch"], y=manv_pts["sma_km"], mode="markers",
                marker=dict(color="red", size=10, symbol="star"),
                name=T("trace_maneuver", lang),
            ))
            if show_sampled:
                fig_2d.add_trace(go.Scatter(
                    x=df_raw["epoch"], y=df_raw["sma_km"], mode="markers",
                    marker=dict(color="white", size=4, opacity=0.4),
                    name=T("trace_raw", lang),
                ))
            fig_2d.update_layout(
                **shared_layout, height=450,
                title=T("chart_sma_f107_title", lang),
                yaxis=dict(title=T("axis_sma", lang)),
                yaxis2=dict(overlaying="y", side="right", title=T("axis_f107", lang)),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig_2d, use_container_width=True, key=f"fig_2d_{satellite_id}_{i}")

            # Event table in advanced mode
            if learn_mode == "learn_advanced" and not event_df.empty:
                _show_concept_if(learn_mode, "event", lang, "🔬")
                ev_display = event_df.copy()
                ev_display["direction"] = ev_display["sma_direction"].map(
                    lambda d: T("label_raise", lang) if d == "raise" else T("label_lower", lang)
                )
                ev_display["reason_zh"] = ev_display.apply(
                    lambda r: event_reason_text(
                        "zh", T("label_maneuver", "zh"),
                        "sma_delta", float(df_processed.loc[r["idx"], "z_score"]) if r["idx"] in df_processed.index else 0,
                        float(r["sma_delta"]), int(used_mult * 3),
                    ), axis=1,
                )
                ev_display["reason_en"] = ev_display.apply(
                    lambda r: event_reason_text(
                        "en", T("label_maneuver", "en"),
                        "sma_delta", float(df_processed.loc[r["idx"], "z_score"]) if r["idx"] in df_processed.index else 0,
                        float(r["sma_delta"]), int(used_mult * 3),
                    ), axis=1,
                )
                show_cols = ["epoch", "sma_delta", "direction"]
                show_cols += ["reason_zh"] if lang == "zh" else ["reason_en"]
                st.dataframe(ev_display[show_cols].style.format({"sma_delta": "{:.4f}"}),
                             use_container_width=True, key=f"evt_tbl_{satellite_id}_{i}")

        # ── Tab: RIC ──────────────────────────────────────────
        with tab_ric:
            _show_concept_if(learn_mode, "ric", lang, "📐")

            df_final["is_dv_v_event"] = detect_ric_events(df_final, "dv_intrack",   6.0, alt_km_avg)
            df_final["is_dv_w_event"] = detect_ric_events(df_final, "dv_crosstrack", 6.0, alt_km_avg)

            fig_ric = go.Figure()
            fig_ric.add_trace(go.Bar(
                x=df_final["epoch"], y=df_final["dv_intrack"],
                name=T("label_intrack", lang), marker_color="lime", opacity=0.7,
            ))
            fig_ric.add_trace(go.Scatter(
                x=df_final["epoch"], y=df_final["dv_crosstrack"],
                name=T("label_crosstrack", lang), line=dict(color="magenta", width=1.5),
            ))
            v_events = df_final[df_final["is_dv_v_event"]]
            if not v_events.empty:
                fig_ric.add_trace(go.Scatter(
                    x=v_events["epoch"], y=v_events["dv_intrack"], mode="markers",
                    name=f"{T('label_intrack', lang)} {T('label_maneuver', lang)}",
                    marker=dict(color="lime", size=12, symbol="triangle-up",
                                line=dict(width=1, color="white")),
                    text=[f"Time: {t}<br>dv_I: {v:.4f} m/s"
                          for t, v in zip(v_events["epoch"], v_events["dv_intrack"])],
                    hoverinfo="text",
                ))
            w_events = df_final[df_final["is_dv_w_event"]]
            if not w_events.empty:
                fig_ric.add_trace(go.Scatter(
                    x=w_events["epoch"], y=w_events["dv_crosstrack"], mode="markers",
                    name=f"{T('label_crosstrack', lang)} {T('label_maneuver', lang)}",
                    marker=dict(color="magenta", size=10, symbol="circle",
                                line=dict(width=1, color="white")),
                    text=[f"Time: {t}<br>dv_C: {w:.4f} m/s"
                          for t, w in zip(w_events["epoch"], w_events["dv_crosstrack"])],
                    hoverinfo="text",
                ))
            fig_ric.update_layout(
                **shared_layout,
                title=f"NORAD {satellite_id} — {T('section_ric', lang)}",
                yaxis=dict(title=T("axis_dv", lang), zeroline=True, zerolinecolor="white"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                bargap=0.5, height=480,
            )
            st.plotly_chart(fig_ric, use_container_width=True, key=f"fig_ric_{satellite_id}_{i}")

        # ── Tab: 3D Orbit ─────────────────────────────────────
        with tab_3d:
            fig_3d = plot_3d_orbit_scene_multi(df_raw, satellite_id)
            st.plotly_chart(fig_3d, use_container_width=True, key=f"fig_3d_{satellite_id}_{i}")

        # ── Tab: Δ Computation ────────────────────────────────
        with tab_delta:
            st.subheader(T("sub_delta", lang).format(sid=satellite_id))
            df_delta = compute_delta_table(df_raw)
            st.write(T("delta_preview", lang))
            st.dataframe(
                df_delta.head(10).style.format({
                    "sma_km": "{:.3f}", "delta_sma_km": "{:.5f}",
                    "inclination_deg": "{:.4f}", "raan_deg": "{:.4f}",
                    "argp_deg": "{:.4f}", "mean_anomaly_deg": "{:.4f}",
                    "delta_inclination_deg": "{:.5f}", "delta_raan_deg": "{:.5f}",
                    "delta_argp_deg": "{:.5f}", "delta_mean_anomaly_deg": "{:.5f}",
                }),
                use_container_width=True,
            )
            csv_name  = f"norad_{satellite_id}_deltas_{start_d}_{end_d}.csv"
            csv_bytes = df_delta.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(T("delta_download", lang), data=csv_bytes,
                               file_name=csv_name, mime="text/csv",
                               key=f"delta_csv_{satellite_id}_{i}")

            st.markdown(f"### {T('delta_time_chart', lang)}")
            for col_name, color_hex, height_ in [("sma_km", "#00CCFF", 300), ("delta_sma_km", "#FFA500", 300)]:
                fig_d = go.Figure(go.Scatter(
                    x=df_delta["date"], y=df_delta[col_name],
                    mode="lines+markers", name=col_name,
                    line=dict(color=color_hex), marker=dict(size=4),
                ))
                if "delta" in col_name:
                    fig_d.add_hline(y=0.0, line_dash="dash", line_color="gray", opacity=0.5)
                fig_d.update_layout(template="plotly_dark", height=height_,
                                    yaxis_title=col_name,
                                    margin=dict(l=60, r=30, t=40, b=40))
                st.plotly_chart(fig_d, use_container_width=True,
                                key=f"delta_{col_name}_{satellite_id}_{i}")

            for col_name in angle_cols:
                delta_col = f"delta_{col_name}"
                fig_ang = go.Figure(go.Scatter(
                    x=df_delta["date"], y=df_delta[delta_col],
                    mode="lines+markers", name=f"Δ {col_name}",
                    line=dict(color="#ADFF2F"), marker=dict(size=4),
                ))
                fig_ang.add_hline(y=0.0, line_dash="dash", line_color="gray", opacity=0.5)
                fig_ang.update_layout(template="plotly_dark", height=250,
                                      yaxis_title=f"Δ {col_name} (deg)",
                                      margin=dict(l=60, r=30, t=40, b=40))
                st.plotly_chart(fig_ang, use_container_width=True,
                                key=f"delta_{col_name}_{satellite_id}_{i}")

        # ── Tab: Spiral Polar ─────────────────────────────────
        with tab_spiral:
            st.subheader(T("sub_spiral", lang).format(sid=satellite_id))
            _show_concept_if(learn_mode, "spiral", lang, "🌀")

            df_spiral, days_arr, theta_time, r_spiral, t_norm = prepare_spiral_polar_data(df_raw)
            fig_spiral = make_subplots(
                rows=2, cols=2,
                specs=[[{"type": "polar"}, {"type": "polar"}],
                       [{"type": "polar"}, {"type": "polar"}]],
                subplot_titles=angle_cols,
            )
            for idx_c, col_c in enumerate(angle_cols):
                rr = idx_c // 2 + 1;  cc = idx_c % 2 + 1
                theta_angle = np.deg2rad(df_spiral[col_c].values % 360.0)
                fig_spiral.add_trace(go.Scatterpolar(
                    theta=np.rad2deg(theta_angle), r=r_spiral, mode="markers",
                    marker=dict(size=6, color=t_norm, colorscale=spiral_cmap,
                                showscale=True,
                                colorbar=dict(title="Norm time", ticks="outside")),
                    name=col_c,
                ), row=rr, col=cc)
                fig_spiral.update_polars(
                    radialaxis=dict(showticklabels=False, showgrid=True),
                    angularaxis=dict(direction="counterclockwise"),
                    row=rr, col=cc,
                )
            fig_spiral.update_layout(
                template="plotly_dark", showlegend=False, height=700,
                margin=dict(l=40, r=40, t=90, b=40),
                title_text=f"NORAD {satellite_id} Angular Elements (Spiral Polar)<br>{start_d} to {end_d}",
            )
            st.plotly_chart(fig_spiral, use_container_width=True, key=f"spiral_{satellite_id}_{i}")

        # ── Tab: Apsidal Precession ────────────────────────────
        with tab_longaxis:
            st.subheader(T("sub_longaxis", lang).format(sid=satellite_id))
            _show_concept_if(learn_mode, "longaxis", lang, "🌐")

            if not {"epoch_jd", "raan_deg", "argp_deg"}.issubset(df_raw.columns):
                st.warning(T("no_longaxis_cols", lang))
            else:
                sec_sidereal_day  = 86164.0905
                sidereal_days_yr  = 366.24
                sec_sidereal_yr   = sidereal_days_yr * sec_sidereal_day

                t_jd  = df_raw["epoch_jd"].to_numpy()
                t_sec = (t_jd - t_jd[0]) * sec_sidereal_day
                t_days = t_sec / sec_sidereal_day

                psi_wrapped   = (df_raw["raan_deg"] + df_raw["argp_deg"]).to_numpy()
                psi_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(psi_wrapped)))

                t_sec_c  = t_sec  - t_sec.mean()
                t_days_c = t_days - t_days.mean()

                st.write(T("fit_samples", lang).format(n=len(df_raw),
                          d=(t_sec.max() - t_sec.min()) / sec_sidereal_day))

                omega = np.linspace(2 * np.pi / (5.0 * sec_sidereal_yr),
                                    2 * np.pi / (0.5 * sec_sidereal_yr), 5000)
                y     = psi_unwrapped - psi_unwrapped.mean()
                pgram = lombscargle(t_sec_c, y, omega, precenter=False, normalize=True)
                omega_peak    = omega[np.argmax(pgram)]
                period_sec    = 2.0 * np.pi / omega_peak
                period_yrs    = period_sec / sec_sidereal_yr
                omega_peak_d  = omega_peak * sec_sidereal_day

                def model_longaxis(t_d, a, b, A, B):
                    return a * t_d + b + A * np.sin(omega_peak_d * t_d) + B * np.cos(omega_peak_d * t_d)

                psi_c = psi_unwrapped - psi_unwrapped.mean()
                psi_fit = None
                try:
                    params_fit, _ = curve_fit(model_longaxis, t_days_c, psi_c, p0=[0.0, 0.0, 1.0, 1.0])
                    a_f, b_f, A_f, B_f = params_fit
                    amp_f  = np.sqrt(A_f**2 + B_f**2)
                    psi_fit = model_longaxis(t_days_c, *params_fit) + psi_unwrapped.mean()

                    if learn_mode in ("learn_data", "learn_advanced"):
                        st.write(T("fit_params_title", lang))
                        st.write(T("fit_psi_def", lang))
                        st.write(T("fit_a", lang))
                        st.write(T("fit_b", lang))
                        st.write(T("fit_A", lang))
                        st.write(T("fit_B", lang))
                        st.write(T("fit_period_amplitude", lang).format(amp=amp_f))
                    if learn_mode == "learn_advanced":
                        for name_, val_ in [("a", a_f), ("b", b_f), ("A", A_f), ("B", B_f)]:
                            st.write(f"{name_} = {val_:.6e}")
                except Exception as e:
                    st.error(f"{T('fit_failed', lang)}: {e}")

                fig_wrap = go.Figure(go.Scatter(
                    x=df_raw["date_tag"], y=psi_wrapped,
                    mode="lines+markers", name="ψ wrapped", marker=dict(size=3),
                ))
                fig_wrap.update_layout(template="plotly_dark", height=300,
                                       yaxis_title=T("longaxis_wrapped_yaxis", lang),
                                       margin=dict(l=60, r=30, t=40, b=40))
                st.plotly_chart(fig_wrap, use_container_width=True,
                                key=f"longaxis_w_{satellite_id}_{i}")

                fig_unwrap = go.Figure(go.Scatter(
                    x=df_raw["date_tag"], y=psi_unwrapped,
                    mode="lines+markers", name="ψ unwrapped", marker=dict(size=3),
                ))
                if psi_fit is not None:
                    fig_unwrap.add_trace(go.Scatter(
                        x=df_raw["date_tag"], y=psi_fit, mode="lines",
                        name=f"{T('trace_fit', lang)} T≈{period_yrs:.3f} yr",
                        line=dict(color="red", width=2),
                    ))
                fig_unwrap.update_layout(template="plotly_dark", height=320,
                                         yaxis_title=T("longaxis_unwrapped_yaxis", lang),
                                         margin=dict(l=60, r=30, t=40, b=40))
                st.plotly_chart(fig_unwrap, use_container_width=True,
                                key=f"longaxis_u_{satellite_id}_{i}")

                periods_yrs = (2.0 * np.pi / omega) / sec_sidereal_yr
                fig_ls = go.Figure(go.Scatter(x=periods_yrs, y=pgram, mode="lines", name="LS Power"))
                fig_ls.add_vline(x=period_yrs, line_dash="dash", line_color="red",
                                  annotation_text=f"Peak ≈ {period_yrs:.3f} yr",
                                  annotation_position="top right")
                fig_ls.update_layout(template="plotly_dark", height=320,
                                     xaxis_title=T("longaxis_ls_xaxis", lang),
                                     yaxis_title=T("longaxis_ls_yaxis", lang),
                                     margin=dict(l=60, r=30, t=40, b=40))
                st.plotly_chart(fig_ls, use_container_width=True,
                                key=f"longaxis_ls_{satellite_id}_{i}")

        # ── Tab: MEME Residuals ───────────────────────────────
        with tab_meme:
            st.subheader(f"{T('section_meme', lang)} (NORAD {satellite_id})")
            st.caption(T("meme_caption", lang))
            _show_concept_if(learn_mode, "meme", lang, "🔬")

            resid_df = load_meme_residuals(satellite_id,
                                           start_d.strftime("%Y-%m-%d"),
                                           end_d.strftime("%Y-%m-%d"))
            if resid_df.empty:
                st.info(T("msg_no_meme", lang))
            else:
                rtn_events = detect_maneuvers_rtn(resid_df)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric(T("metric_resid_pts",     lang), f"{len(resid_df):,}")
                c2.metric(T("metric_meme_detected", lang), len(rtn_events))
                c3.metric(T("metric_max_pos_err",   lang), f"{resid_df['pos_err_km'].max():.2f}")
                tle_age_val = resid_df["tle_age_days"].iloc[0] if "tle_age_days" in resid_df.columns else None
                c4.metric(T("metric_tle_age", lang), f"{tle_age_val:.1f}" if tle_age_val is not None else "N/A")

                _render_rtn_chart(resid_df, rtn_events, satellite_id, i, lang, "meme_rtn")

                if not rtn_events.empty:
                    st.subheader(T("sub_detected_meme", lang))
                    _render_event_table_rtn(rtn_events, lang, learn_mode, f"meme_events_{satellite_id}_{i}")
                else:
                    st.success(T("msg_no_event", lang))

                if learn_mode in ("learn_data", "learn_advanced"):
                    st.subheader(T("sub_compare_tle_meme", lang))
                    tle_cnt  = int(df_final["is_maneuver"].sum())
                    meme_cnt = len(rtn_events)
                    td = resid_df["t"].diff().dt.total_seconds().median()
                    comp_df = pd.DataFrame({
                        T("comp_method",   lang): [T("comp_tle_diff",  lang), T("comp_meme_rtn", lang)],
                        T("comp_count",    lang): [tle_cnt,  meme_cnt],
                        T("comp_accuracy", lang): [T("comp_tle_acc",  lang), T("comp_meme_acc", lang)],
                        T("comp_time_res", lang): [
                            "daily (resampled)",
                            f"~{td/60:.0f} min" if td and not np.isnan(td) else "N/A",
                        ],
                    })
                    st.table(comp_df)

        # ── Tab: Galileo SP3 ──────────────────────────────────
        with tab_galileo:
            st.subheader(f"Galileo SP3 (NORAD {satellite_id})")
            st.caption(T("galileo_caption", lang))
            _show_concept_if(learn_mode, "galileo_sp3", lang, "🪐")

            if alt_km_avg is not None and alt_km_avg < 10_000:
                st.warning(T("msg_galileo_wrong_orbit", lang).format(sid=satellite_id, alt=alt_km_avg))

            gal_resid_df = load_galileo_sp3_residuals(satellite_id,
                                                       start_d.strftime("%Y-%m-%d"),
                                                       end_d.strftime("%Y-%m-%d"))
            if gal_resid_df.empty:
                st.info(T("msg_no_galileo", lang))
            else:
                gal_events = detect_maneuvers_rtn(gal_resid_df)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric(T("metric_resid_pts",    lang), f"{len(gal_resid_df):,}")
                c2.metric(T("metric_sp3_detected", lang), len(gal_events))
                c3.metric(T("metric_max_pos_err",  lang), f"{gal_resid_df['pos_err_km'].max():.2f}")
                med_age = gal_resid_df["tle_age_days"].median() if "tle_age_days" in gal_resid_df.columns else None
                c4.metric(T("metric_median_age", lang),
                          f"{med_age:.1f}" if med_age is not None else "N/A")

                _render_rtn_chart(gal_resid_df, gal_events, satellite_id, i, lang, "gal_rtn")

                if not gal_events.empty:
                    st.subheader(T("sub_detected_galileo", lang))
                    _render_event_table_rtn(gal_events, lang, learn_mode, f"gal_events_{satellite_id}_{i}")
                else:
                    st.success(T("msg_no_event", lang))

                if learn_mode in ("learn_data", "learn_advanced"):
                    st.subheader(T("sub_compare_tri", lang))
                    tle_cnt  = int(df_final["is_maneuver"].sum())
                    meme_cnt_local = len(
                        load_meme_residuals(satellite_id,
                                            start_d.strftime("%Y-%m-%d"),
                                            end_d.strftime("%Y-%m-%d"))
                    )
                    tri_df = pd.DataFrame({
                        T("comp_method",     lang): [T("comp_tle_diff",    lang),
                                                     T("comp_meme_rtn",    lang),
                                                     T("comp_galileo_sp3", lang)],
                        T("comp_count",      lang): [tle_cnt, meme_cnt_local, len(gal_events)],
                        T("comp_accuracy",   lang): [T("comp_tle_acc",     lang),
                                                     T("comp_meme_acc",    lang),
                                                     T("comp_sp3_acc",     lang)],
                        T("comp_orbit_zone", lang): [T("comp_leo_zone",       lang),
                                                     T("comp_starlink_zone",  lang),
                                                     T("comp_galileo_zone",   lang)],
                    })
                    st.table(tri_df)

    st.divider()
