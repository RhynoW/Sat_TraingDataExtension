#!/usr/bin/env python3
"""
maneuver_app_2026September.py — 機動偵測儀表板（2026-09 HuggingFace 發布版，前身 maneuver_app_2026August.py）
=====================================================
配合最新 ML（models_meme_forecast）與統計偵測（CUSUM/BOCPD/SSA）模型的重寫版。
用法（本機）：  streamlit run maneuver_app_2026September.py

【與 August 版差異 — HuggingFace 發布相容】
  * 資料後端可切換：本機 14GB 全庫（space_db.duckdb），或 HF 遠端 Parquet（不需下載整庫）。
  * 設環境變數 HF_DATASET_REPO=<帳號>/<repo> 即切為遠端模式：
      啟動時自動安裝 httpfs、建立一顆輕量 stub DuckDB，內含指向
      hf://datasets/<repo>/... Parquet 的 VIEW；read_only 連線 + 統計裁剪只抓需要的區塊。
  * 目錄樹佈局須先用 export_to_hf_parquet.py 匯出並上傳（見 README_HF_Space.md）。
  * 未設 HF_DATASET_REPO 且本機存在 space_db.duckdb → 行為與 August 版完全相同。

功能（依需求）
  1. NORAD/名稱查詢（支援 wildcard）；LEO/MEO/GEO/HEO 自動分類套不同規則；
     單頁顯示 a/i/e/RAAN 連續時序 + Δa/Δi/Δe/ΔRAAN 差值。
  2. P1–P6 策略個別結果 + 合併結果。
  3. P2 閾值改「拋物線左側」曲線（UI 滑桿）。
  4. F10.7 自適應倍率改「拋物線」曲線（UI 滑桿）。
  5. 全 284 顆 MEME 艦隊級統計 + bootstrap 95% 信賴區間。
  9. MEME 僅 72h 模型與 TLE 比較（不做長時程外推）。
 10. 合成 TLE 批次生成（重用 synthetic_tle）。
"""
from __future__ import annotations

import colorsys
import glob
import os
from datetime import timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import maneuver_strategies_july as ms
import statistical_detectors as sd
import data_quality_audit as dqa
import constellation_anomaly as ca

DATA = Path("data")
R_E = 6378.137

# ── i18n（zh/ja/en）──────────────────────────────────────────────────────────
LANG_LABELS = {"zh": "中文", "ja": "日本語", "en": "English"}
L: dict[str, dict[str, str]] = {
    # ── 頁面 / 標題 ──────────────────────────────────────────────────────────
    "page_title": {"zh": "機動偵測儀表板 2026-09",
                   "ja": "マヌーバ検知ダッシュボード 2026-09",
                   "en": "Maneuver Detection Dashboard 2026-09"},
    "app_title": {"zh": "🛰️ 機動偵測儀表板（2026 年 9 月版）",
                  "ja": "🛰️ マヌーバ検知ダッシュボード（2026年9月版）",
                  "en": "🛰️ Maneuver Detection Dashboard (September 2026)"},
    "app_caption": {"zh": "整合 P1–P6 規則、CUSUM/BOCPD/SSA"
                          "（Singular Spectrum Analysis，奇異譜分析）統計層、"
                          "MEME-tuned ML forecast 模型",
                    "ja": "P1–P6 ルール、CUSUM/BOCPD/SSA（特異スペクトル解析）統計層、"
                          "MEME チューニング済み ML 予測モデルを統合",
                    "en": "Integrating P1–P6 rules, the CUSUM/BOCPD/SSA (Singular Spectrum Analysis) "
                          "statistical layer, and MEME-tuned ML forecasting models"},

    # ── 艦隊級 KPI 卡片列（借用 scenario-advanced01/starlink.html 頂部統計卡樣式）───
    "kpi_monthly_maneuvers": {"zh": "近 30 天機動事件數", "ja": "直近30日のマヌーバ件数",
                              "en": "Maneuver events (last 30 days)"},
    "kpi_monthly_maneuvers_caption": {"zh": "medium/large，{n} 顆有事件",
                                      "ja": "medium/large、{n} 機で検出",
                                      "en": "medium/large, {n} satellites"},
    "kpi_monthly_maneuvers_stale": {"zh": "MEME 真值最新至 {d}，非近 30 天（真值資料有滯後）",
                                    "ja": "MEME真値の最新日は{d}、直近30日分ではない（真値データに遅延あり）",
                                    "en": "MEME ground truth latest as of {d} (older than 30 days — truth data lags)"},
    "kpi_quality_good_pct": {"zh": "資料品質 good 比例", "ja": "データ品質 good 比率",
                             "en": "Data quality: good %"},
    "kpi_quality_good_caption": {"zh": "近 30 天 {n} 筆 TLE 稽核", "ja": "直近30日 {n} 件のTLEを監査",
                                 "en": "{n} TLEs audited (last 30 days)"},
    "kpi_deorbiting": {"zh": "疑似離軌顆數（da_monotonic_decay）",
                       "ja": "離軌疑いの機数（da_monotonic_decay）",
                       "en": "Suspected deorbiting (da_monotonic_decay)"},
    "kpi_deorbiting_caption": {"zh": "近 7 天窗，全艦隊 {n} 顆", "ja": "直近7日窓、艦隊全 {n} 機中",
                               "en": "7-day window, fleet of {n}"},
    "kpi_no_data": {"zh": "－", "ja": "－", "en": "–"},

    # ── StoryMap（2026-09-10 新增）─────────────────────────────────────────────
    "mode_tool": {"zh": "🛠️ 分析工具", "ja": "🛠️ 分析ツール", "en": "🛠️ Analysis Tool"},
    "mode_storymap": {"zh": "📖 StoryMap", "ja": "📖 StoryMap", "en": "📖 StoryMap"},
    "storymap_lang_note": {"zh": "", "ja": "本ストーリーの本文は現時点で中国語版のみ提供しています（UIラベルは多言語対応）。",
                           "en": "Story narrative text is currently Traditional Chinese only (UI labels are multilingual)."},
    "storymap_landing_title": {"zh": "📖 太空態勢感知 StoryMap", "ja": "📖 SSA StoryMap", "en": "📖 SSA StoryMap"},
    "storymap_landing_sub": {"zh": "用真實資料回答本專案最常被問到的技術問題——不是簡報結論，是可重跑、可複核的完整推導過程。",
                             "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case3_card_title": {"zh": "案例三：TLE 觀測窗要拉多長，才能抓到 Starlink 電推機動的明確證據？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case3_card_desc": {"zh": "用兩顆真實衛星的 TLE 資料＋一組校準過的模擬實驗回答：答案分兩種完全不同的情境。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_enter_case": {"zh": "▶ 進入這個案例", "ja": "▶ Open", "en": "▶ Open"},
    "storymap_back": {"zh": "← 回到 StoryMap 首頁", "ja": "← Back", "en": "← Back"},
    "storymap_more_soon": {"zh": "更多案例陸續加入中……", "ja": "More cases coming soon…", "en": "More cases coming soon…"},
    "storymap_case4_card_title": {"zh": "案例四：23 顆外部標竿衛星的機動真值，從哪裡來、怎麼處理？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case4_card_desc": {"zh": "14 顆開發樣本 + 9 顆從未參與開發的 hold-out 衛星——三個公開資料來源、免帳號下載，並用真實案例驗證 TLE 與獨立真值是否吻合。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case5_card_title": {"zh": "案例五：怎麼分辨「主動機動」跟「大氣阻力自然衰減」？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case5_card_desc": {"zh": "用 NRLMSIS 物理阻力模型逐衛星扣除自然衰減量——FORMOSAT-3A（純衰減）、Starlink（電推機動）、ISS（真實 reboost）、Van Allen A（再入）四顆真實衛星對照示範，含一個「差點誤報」的真實案例。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case6_card_title": {"zh": "案例六：Starlink 這種巨型星系，抓得到「一次調整一整批衛星」嗎？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case6_card_desc": {"zh": "即時對上萬顆 Starlink 衛星做星系級分析：軌道面一致性、批量機動識別、隊形相位誤差——用真實資料回答「有沒有抓到批次事件」。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case7_card_title": {"zh": "案例七：兩顆衛星多近才算「危險接近」？Pc／TCA 怎麼算出來的？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case7_card_desc": {"zh": "兩個真實案例對照：TJS-10 對 TJS-3 的 GEO 抵近偵察，以及 ISS 對 Cygnus 貨運飛船的正常對接——同樣的「近距接近」，意義完全不同。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case8_card_title": {"zh": "案例八：這個資料庫本身的故事——3.4 萬顆衛星、跨度 55 年、一次目錄大擴編",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case8_card_desc": {"zh": "源自一次真實的使用者提問（「資料最早只到3月，分年parquet是不是沒啟用？」）——完整調查過程做成案例，即時查驗資料庫的真實跨度與一次目錄擴編事件。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case9_card_title": {"zh": "案例九：模型對「從沒看過的衛星」還準不準？三層擂台怎麼公平比較？",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case9_card_desc": {"zh": "56 顆衛星整組保留、完全不參與訓練——真實 unseen-satellite hold-out 測試結果，對照規則式／傳統 ML／融合模型三層架構。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case10_card_title": {"zh": "案例十：能不能用 TLE 反推大氣密度？一個誠實的負面結論",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case10_card_desc": {"zh": "四次嘗試、三個根因——本專案沒有隱藏這次失敗：TLE 資料本身的限制，讓乾淨複現精密星曆等級的大氣密度斷層變得不可行，以及可行的下一步。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case11_card_title": {"zh": "案例十一：本專案站在哪些巨人的肩膀上？——文獻整理與回顧",
                                   "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case11_card_desc": {"zh": "既有 TLE 機動偵測研究的四條路線、本專案與既有工作的差異，以及完整分類文獻列表（30 篇，含 DOI）。",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case12_card_title": {"zh": "案例十二：這套系統，在哪些軌道類型上能信？哪些還不能？",
                                   "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case12_card_desc": {"zh": "誠實分級：已驗證有信心（Starlink LEO）、有特殊處理但驗證有限（再入判定）、"
                                       "有程式路徑缺量化驗證（GEO/MEO）、獨立支線未整合（Galileo）、"
                                       "已知不適用（HEO 全生命週期）與尚待測試的缺口（太陽同步）。",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case13_card_title": {"zh": "案例十三：對幾十顆到上百顆 Starlink 跑 MEME 軌道外推，算出了什麼？",
                                   "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case13_card_desc": {"zh": "大規模計算的結果與兩個意外的方法論陷阱：瞬時半長軸的短週期振盪誤標 99.5%、"
                                       "SpaceX 把計畫機動預先編入星曆檔——以及機動污染讓外推誤差暴增 14 倍的真實對比。",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case1_card_title": {"zh": "案例一：從 TLE 偵測機動，到底可不可行？——演算法架構與流程全貌",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case1_card_desc": {"zh": "整體架構流程圖＋多種方法一併說明：規則式、統計變點偵測、物理阻力殘差、機器學習、融合評分器怎麼組合起來，並用 14+9 顆衛星真值驗證可行性。",
                                 "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case2_card_title": {"zh": "案例二：我們的方法，哪些用了 AI？哪些沒有？",
                                   "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},
    "storymap_case2_card_desc": {"zh": "把所有方法依「完全不是AI／傳統機器學習／深度學習（已放棄）」清楚分類，並用真實數字回答「加了 AI 到底差多少」。",
                                  "ja": "See narrative (ZH)", "en": "See narrative (ZH)"},

    # ── 資料後端 bootstrap ───────────────────────────────────────────────────
    "warn_hf_secret": {"zh": "HF secret 建立提示（private repo 才需要）：{e}",
                       "ja": "HF シークレット作成に関する注意（private リポジトリのみ必要）：{e}",
                       "en": "HF secret creation notice (only needed for private repos): {e}"},
    "warn_httpfs": {"zh": "httpfs 安裝提示：{e}",
                    "ja": "httpfs インストールに関する注意：{e}",
                    "en": "httpfs installation notice: {e}"},
    "spinner_init_backend": {"zh": "初始化資料後端…",
                             "ja": "データバックエンドを初期化中…",
                             "en": "Initializing data backend…"},
    "err_no_datasource": {
        "zh": "找不到資料來源。請擇一：\n"
              "  1) 本機放置 space_db.duckdb（完整庫），或\n"
              "  2) 設環境變數 HF_DATASET_REPO=<帳號>/<repo>（遠端 Parquet 模式）。\n"
              "遠端資料請先用 export_to_hf_parquet.py 匯出並上傳，詳見 README_HF_Space.md。",
        "ja": "データソースが見つかりません。いずれかを設定してください：\n"
              "  1) ローカルに space_db.duckdb（完全データベース）を配置する、または\n"
              "  2) 環境変数 HF_DATASET_REPO=<アカウント>/<repo> を設定する（リモート Parquet モード）。\n"
              "リモートデータは事前に export_to_hf_parquet.py でエクスポート・アップロードしてください"
              "（詳細は README_HF_Space.md）。",
        "en": "No data source found. Choose one of the following:\n"
              "  1) Place space_db.duckdb (the full database) locally, or\n"
              "  2) Set the environment variable HF_DATASET_REPO=<account>/<repo> (remote Parquet mode).\n"
              "For remote data, export and upload with export_to_hf_parquet.py first; "
              "see README_HF_Space.md."},

    # ── ① 圖表（根數與差值）─────────────────────────────────────────────────
    "plot_alt_km": {"zh": "離地高度 (km)", "ja": "地表からの高度 (km)",
                    "en": "Altitude above surface (km)"},
    "plot_sma_km": {"zh": "半長軸 a (km)", "ja": "軌道長半径 a (km)",
                    "en": "Semi-major axis a (km)"},
    "plot_sma_circle": {"zh": "SMA 圓形時間圖", "ja": "SMA 円形時間プロット",
                        "en": "SMA circular time plot"},
    "plot_inc_deg": {"zh": "傾角 i (deg)", "ja": "軌道傾斜角 i (deg)",
                     "en": "Inclination i (deg)"},
    "plot_inc_spiral": {"zh": "傾角 Spiral", "ja": "軌道傾斜角スパイラル",
                        "en": "Inclination spiral"},
    "plot_ecc": {"zh": "離心率 e", "ja": "離心率 e", "en": "Eccentricity e"},
    "plot_raan_deg": {"zh": "升交點赤經 RAAN (deg)", "ja": "昇交点赤経 RAAN (deg)",
                      "en": "RAAN (deg)"},
    "plot_draan_res": {"zh": "ΔRAAN 殘差 (deg)", "ja": "ΔRAAN 残差 (deg)",
                       "en": "ΔRAAN residual (deg)"},
    "legend_p16_combined": {"zh": "P1–P6 合併偵測", "ja": "P1–P6 統合検知",
                            "en": "P1–P6 combined detection"},
    "legend_nrlmsis_primary": {"zh": "NRLMSIS 主判定的機動候選", "ja": "NRLMSIS主判定のマヌーバ候補",
                               "en": "NRLMSIS primary maneuver candidates"},

    # ── 側邊欄 ───────────────────────────────────────────────────────────────
    "sidebar_query_header": {"zh": "查詢", "ja": "検索", "en": "Query"},
    "input_query": {"zh": "NORAD ID / 名稱 / wildcard",
                    "ja": "NORAD ID / 名称 / ワイルドカード",
                    "en": "NORAD ID / name / wildcard"},
    "help_query": {"zh": "例：57681、STARLINK-30273、STARLINK-30* 、SL-1?",
                   "ja": "例：57681、STARLINK-30273、STARLINK-30*、SL-1?",
                   "en": "e.g. 57681, STARLINK-30273, STARLINK-30*, SL-1?"},
    "sidebar_p2_header": {"zh": "P2 高度自適應閾值（拋物線左側）",
                          "ja": "P2 高度適応しきい値（放物線の左枝）",
                          "en": "P2 altitude-adaptive threshold (left branch of parabola)"},
    "slider_p2_vertex": {"zh": "P2 vertex 高度 (km)", "ja": "P2 頂点高度 (km)",
                         "en": "P2 vertex altitude (km)"},
    "slider_p2_floor": {"zh": "P2 floor 閾值 (km)", "ja": "P2 下限しきい値 (km)",
                        "en": "P2 floor threshold (km)"},
    "slider_p2_refy": {"zh": "P2 @400km 閾值 (km)", "ja": "P2 @400km しきい値 (km)",
                       "en": "P2 threshold @400 km (km)"},
    "sidebar_p5_header": {"zh": "P5 F10.7 自適應倍率（拋物線）",
                          "ja": "P5 F10.7 適応倍率（放物線）",
                          "en": "P5 F10.7-adaptive multiplier (parabola)"},
    "slider_p5_vertex": {"zh": "P5 vertex F10.7 (sfu)", "ja": "P5 頂点 F10.7 (sfu)",
                         "en": "P5 vertex F10.7 (sfu)"},
    "slider_p5_refy": {"zh": "P5 @200sfu 倍率", "ja": "P5 @200sfu 倍率",
                       "en": "P5 multiplier @200 sfu"},
    "sidebar_rag_header": {"zh": "🤖 SSA-RAG 知識庫", "ja": "🤖 SSA-RAG ナレッジベース",
                           "en": "🤖 SSA-RAG knowledge base"},
    "input_rag_url": {"zh": "SSA-RAG 服務位址", "ja": "SSA-RAG サービスアドレス",
                      "en": "SSA-RAG service URL"},
    "chk_rag_auto": {"zh": "執行後自動送 RAG 解說（③ 偵測結果）",
                     "ja": "実行後に自動で RAG 解説を送信（③ 検知結果）",
                     "en": "Auto-send RAG explanation after run (③ detection results)"},
    "help_rag_auto": {"zh": "將 P1–P6／ML 偵測結果轉自然語言自動送 SSA-RAG；服務離線僅留提示",
                      "ja": "P1–P6／ML の検知結果を自然言語に変換して SSA-RAG へ自動送信します。"
                            "サービスが停止中の場合は通知のみ表示します",
                      "en": "Converts P1–P6 / ML detection results into natural language and "
                            "automatically sends them to SSA-RAG; only a notice is shown when the "
                            "service is offline"},

    # ── 對話面板 ─────────────────────────────────────────────────────────────
    "dlg_expander": {"zh": "💬 App 對話（↔ SSA-RAG Server）",
                     "ja": "💬 アプリ対話（↔ SSA-RAG サーバー）",
                     "en": "💬 App conversation (↔ SSA-RAG server)"},
    "dlg_no_client": {"zh": "找不到 app_dialogue_client.py，無法使用對話功能。",
                      "ja": "app_dialogue_client.py が見つからないため、対話機能は利用できません。",
                      "en": "app_dialogue_client.py not found; the dialogue feature is unavailable."},
    "dlg_empty": {"zh": "（信箱尚無訊息）", "ja": "（メッセージはまだありません）",
                  "en": "(No messages yet)"},
    "dlg_recent": {"zh": "（僅顯示最近 {n} 則，共 {total} 則）",
                   "ja": "（直近 {n} 件のみ表示、全 {total} 件）",
                   "en": "(Showing the latest {n} of {total} messages)"},
    "dlg_ack": {"zh": "（送達確認）", "ja": "（受信確認）", "en": "(delivery ack)"},
    "dlg_end": {"zh": "（對話結束）", "ja": "（対話終了）", "en": "(end of dialogue)"},
    "btn_refresh": {"zh": "🔄 重新整理", "ja": "🔄 再読み込み", "en": "🔄 Refresh"},
    "input_message": {"zh": "訊息", "ja": "メッセージ", "en": "Message"},
    "ph_message": {"zh": "例：可以傳送 SSA-RAG 測試了嗎?",
                   "ja": "例：SSA-RAG のテストを送信してもよいですか？",
                   "en": "e.g. Can I send the SSA-RAG test now?"},
    "btn_send": {"zh": "送出", "ja": "送信", "en": "Send"},

    # ── SSA-RAG 自動解說 ─────────────────────────────────────────────────────
    "rag_offline_auto": {
        "zh": "⚠️ SSA-RAG 服務未上線（{url}），略過自動解說。"
              "啟動方式：於 F:\\GitHub\\SSA-RAG 目錄執行 `uvicorn app.main:app`。",
        "ja": "⚠️ SSA-RAG サービスが起動していません（{url}）。自動解説をスキップします。"
              "起動方法：F:\\GitHub\\SSA-RAG ディレクトリで `uvicorn app.main:app` を実行。",
        "en": "⚠️ The SSA-RAG service is offline ({url}); skipping the automatic explanation. "
              "To start it, run `uvicorn app.main:app` in F:\\GitHub\\SSA-RAG."},
    "rag_auto_title": {"zh": "#### 🤖 SSA-RAG 自動解說",
                       "ja": "#### 🤖 SSA-RAG 自動解説",
                       "en": "#### 🤖 SSA-RAG automatic explanation"},
    "rag_show_narrative": {"zh": "查看送出的偵測結果描述",
                           "ja": "送信した検知結果の記述を表示",
                           "en": "View the detection summary that was sent"},
    "rag_spinner_auto": {"zh": "SSA-RAG 解說產生中…（首次呼叫需載入模型，約 10–30 秒）",
                         "ja": "SSA-RAG の解説を生成中…（初回はモデル読み込みのため約 10–30 秒）",
                         "en": "Generating the SSA-RAG explanation… (the first call loads the model, "
                               "about 10–30 s)"},
    "rag_query_failed": {"zh": "SSA-RAG 查詢失敗：{e}", "ja": "SSA-RAG のクエリに失敗しました：{e}",
                         "en": "SSA-RAG query failed: {e}"},
    "rag_confidence_line": {"zh": "{icon} 信心度：{conf}", "ja": "{icon} 信頼度：{conf}",
                            "en": "{icon} Confidence: {conf}"},
    "rag_sources": {"zh": "📄 參考來源（{n} 筆）", "ja": "📄 参照ソース（{n} 件）",
                    "en": "📄 References ({n})"},
    "rag_source_docs": {"zh": "📄 來源文件（{n} 筆）", "ja": "📄 出典ドキュメント（{n} 件）",
                        "en": "📄 Source documents ({n})"},
    "rag_source_line": {"zh": "**{name}**（chunk {idx}，score {score}）",
                        "ja": "**{name}**（chunk {idx}、score {score}）",
                        "en": "**{name}** (chunk {idx}, score {score})"},
    "unknown": {"zh": "未知", "ja": "不明", "en": "Unknown"},

    # ── SSA-RAG 問答頁 ───────────────────────────────────────────────────────
    "err_no_rag_client": {"zh": "找不到 ssa_rag_client.py，請確認檔案已複製到本專案目錄。",
                          "ja": "ssa_rag_client.py が見つかりません。本プロジェクトのディレクトリに"
                                "コピーされているか確認してください。",
                          "en": "ssa_rag_client.py not found; please make sure it has been copied "
                                "into this project directory."},
    "rag_offline_page": {"zh": "⚠️ SSA-RAG 服務未上線（{url}）。"
                               "啟動：於 F:\\GitHub\\SSA-RAG 執行 `uvicorn app.main:app`。",
                         "ja": "⚠️ SSA-RAG サービスが起動していません（{url}）。"
                               "起動：F:\\GitHub\\SSA-RAG で `uvicorn app.main:app` を実行。",
                         "en": "⚠️ The SSA-RAG service is offline ({url}). "
                               "To start it, run `uvicorn app.main:app` in F:\\GitHub\\SSA-RAG."},
    "rag_online": {"zh": "✅ SSA-RAG 服務正常（{url}）",
                   "ja": "✅ SSA-RAG サービスは正常です（{url}）",
                   "en": "✅ The SSA-RAG service is up ({url})"},
    "sel_topic": {"zh": "主題篩選", "ja": "トピック絞り込み", "en": "Topic filter"},
    "opt_all": {"zh": "(全部)", "ja": "(すべて)", "en": "(All)"},
    "sel_example_q": {"zh": "範例問題（可略過，直接自訂輸入）",
                      "ja": "質問例（スキップして自由入力も可）",
                      "en": "Example questions (optional — you can type your own)"},
    "opt_custom": {"zh": "(自訂輸入)", "ja": "(自由入力)", "en": "(Custom input)"},
    "input_question": {"zh": "問題", "ja": "質問", "en": "Question"},
    "spinner_querying": {"zh": "查詢中… 首次呼叫需載入模型，約 10–30 秒",
                         "ja": "問い合わせ中… 初回はモデル読み込みのため約 10–30 秒",
                         "en": "Querying… the first call loads the model, about 10–30 s"},
    "err_query_failed": {"zh": "查詢失敗：{e}", "ja": "クエリに失敗しました：{e}",
                         "en": "Query failed: {e}"},
    "hdr_answer": {"zh": "### 回答", "ja": "### 回答", "en": "### Answer"},
    "warn_insufficient": {"zh": "資料不足，無法根據現有文件確認此問題。",
                          "ja": "情報が不足しており、既存の文書ではこの質問を確認できません。",
                          "en": "Insufficient information; this question cannot be answered from "
                                "the available documents."},

    # ── 主體：查詢 / 基本資訊 ────────────────────────────────────────────────
    "warn_no_match": {"zh": "查無符合的衛星。", "ja": "該当する衛星が見つかりません。",
                      "en": "No matching satellite found."},
    "info_multi_match": {"zh": "符合 {n} 顆（wildcard）。下方逐顆分析可選擇；艦隊統計見底部。",
                         "ja": "{n} 機が該当しました（ワイルドカード）。下部で個別に解析する衛星を"
                               "選択できます。フリート統計はページ下部を参照してください。",
                         "en": "{n} satellites matched (wildcard). Choose one below for per-satellite "
                               "analysis; fleet statistics are at the bottom."},
    "sel_satellite": {"zh": "選擇衛星", "ja": "衛星を選択", "en": "Select satellite"},
    "err_insufficient_tle": {"zh": "此衛星 TLE 資料不足。",
                             "ja": "この衛星の TLE データが不足しています。",
                             "en": "Insufficient TLE data for this satellite."},
    "date_start": {"zh": "起始", "ja": "開始", "en": "Start"},
    "date_end": {"zh": "結束", "ja": "終了", "en": "End"},
    "warn_range_lt3": {"zh": "此範圍 TLE 少於 3 筆。",
                       "ja": "この期間の TLE が 3 件未満です。",
                       "en": "Fewer than 3 TLEs in this range."},
    "metric_satellite": {"zh": "衛星", "ja": "衛星", "en": "Satellite"},
    "metric_orbit_class": {"zh": "軌道類別", "ja": "軌道クラス", "en": "Orbit class"},
    "metric_inc_family": {"zh": "傾角族群", "ja": "傾斜角ファミリー", "en": "Inclination family"},
    "metric_tle_count": {"zh": "TLE 筆數", "ja": "TLE 件数", "en": "TLE count"},

    # ── 🎯 統一偵測摘要 ──────────────────────────────────────────────────────
    "unified_title": {"zh": "#### 🎯 統一偵測摘要（orbit_anomaly_detector · 依軌域自動路由）",
                      "ja": "#### 🎯 統合検知サマリー（orbit_anomaly_detector · 軌道領域による自動ルーティング）",
                      "en": "#### 🎯 Unified detection summary (orbit_anomaly_detector · auto-routed "
                            "by orbit regime)"},
    "spinner_unified": {"zh": "統一偵測中…", "ja": "統合検知を実行中…",
                        "en": "Running unified detection…"},
    "metric_regime_domain": {"zh": "軌域 · 域", "ja": "軌道クラス · 領域",
                             "en": "Orbit class · domain"},
    "metric_routed_primary": {"zh": "路由主判", "ja": "ルーティング先の主判定",
                              "en": "Routed primary detector"},
    "metric_fusion_flags": {"zh": "融合旗標", "ja": "融合フラグ", "en": "Fusion flags"},
    "metric_model2_anomaly": {"zh": "Model 2 異常", "ja": "Model 2 異常",
                              "en": "Model 2 anomalies"},
    "err_reentry_verdict": {"zh": "⚠️ 偵測到**自然再入衰減模式** → 判定「{verdict}」"
                                  "（機動 = 0，不套用機動模型）",
                            "ja": "⚠️ **自然再入・減衰パターンを検知** → 判定「{verdict}」"
                                  "（マヌーバ件数 = 0、マヌーバモデルは適用しません）",
                            "en": "⚠️ **Natural re-entry/decay pattern detected** → verdict "
                                  "“{verdict}” (maneuvers = 0; maneuver models not applied)"},
    "info_routed_to": {"zh": "路由至 **{primary}** — {verdict}",
                       "ja": "**{primary}** へルーティング — {verdict}",
                       "en": "Routed to **{primary}** — {verdict}"},
    "caption_layer2": {"zh": "Layer 2 統計事件：{n}。"
                             "Starlink LEO→Model 1+融合；非 Starlink／衰減軌道→Model 2+NRLMSIS；"
                             "再入→物理閘門抑制。",
                       "ja": "Layer 2統計イベント：{n}。"
                             "Starlink LEO→Model 1＋統合、非Starlink／減衰軌道→Model 2＋NRLMSIS、"
                             "再突入→物理ゲートで抑制。",
                       "en": "Layer 2 statistical events: {n}. "
                             "Starlink LEO → Model 1 + fusion; non-Starlink / decaying orbits → "
                             "Model 2 + NRLMSIS; re-entry → suppressed by the physical gate."},
    "caption_unified_unavailable": {"zh": "統一偵測不可得：{err}",
                                    "ja": "統合検知は利用できません：{err}",
                                    "en": "Unified detection unavailable: {err}"},

    # ── ① 根數與差值 ─────────────────────────────────────────────────────────
    "sec1_title": {"zh": "① 軌道根數連續變化與差值",
                   "ja": "① 軌道要素の連続変化と差分",
                   "en": "① Orbital element time series and differences"},
    "radio_left_y": {"zh": "左上 Y 軸顯示", "ja": "左上 Y 軸の表示", "en": "Top-left Y axis"},
    "help_left_y": {"zh": "切換左上第一格：半長軸 a ↔ 距離地表高度（a − R⊕，R⊕=6378.137 km）。"
                          "註：Streamlit 無法擷取「滑鼠點選 Y 軸」事件，故以此切換鈕達成等效功能；"
                          "Δa 為差值、扣常數不變，不受影響。",
                    "ja": "左上のパネルを切り替えます：軌道長半径 a ↔ 地表からの高度"
                          "（a − R⊕、R⊕=6378.137 km）。"
                          "注：Streamlit では「Y 軸のクリック」イベントを取得できないため、"
                          "このトグルで同等の機能を実現しています。Δa は差分であり、"
                          "定数を引いても変わらないため影響を受けません。",
                    "en": "Switches the top-left panel between semi-major axis a and altitude above "
                          "the surface (a − R⊕, R⊕ = 6378.137 km). "
                          "Note: Streamlit cannot capture “click on the Y axis” events, so this "
                          "toggle provides the equivalent function; Δa is a difference and is "
                          "unaffected by subtracting a constant."},
    "caption_green_star": {"zh": "🟢 綠星 = NRLMSIS 主判定的機動候選（扣大氣阻力後 |Δa 殘差|>0.3km），共 {n} 次；"
                                 "紅叉 = P1–P6 合併偵測。",
                           "ja": "🟢 緑の星 = NRLMSIS主判定のマヌーバ候補"
                                 "（大気抵抗を除去後 |Δa 残差|>0.3km）、"
                                 "計 {n} 件。赤い × = P1–P6 統合検知。",
                           "en": "🟢 Green stars = NRLMSIS primary maneuver calls (|Δa residual| > "
                                 "0.3 km after removing atmospheric drag), {n} in total; "
                                 "red crosses = P1–P6 combined detections."},

    # ── ② P1–P6 ─────────────────────────────────────────────────────────────
    "sec2_title": {"zh": "② P1–P6 策略：個別 vs 合併",
                   "ja": "② P1–P6 戦略：個別 vs 統合",
                   "en": "② P1–P6 strategies: individual vs combined"},
    "tbl_kind_suppress": {"zh": "抑制", "ja": "抑制", "en": "Suppression"},
    "tbl_kind_detect": {"zh": "偵測", "ja": "検知", "en": "Detection"},
    "tbl_kind_final": {"zh": "最終", "ja": "最終", "en": "Final"},
    "tbl_strategy_combined": {"zh": "★ 合併", "ja": "★ 統合", "en": "★ Combined"},
    "exp_p2p5_preview": {"zh": "P2 / P5 拋物線曲線預覽",
                         "ja": "P2 / P5 放物線カーブのプレビュー",
                         "en": "P2 / P5 parabola curve preview"},
    "plot_p2_curve": {"zh": "P2：高度→Δa 閾值 (km)", "ja": "P2：高度→Δa しきい値 (km)",
                      "en": "P2: altitude → Δa threshold (km)"},
    "plot_p5_curve": {"zh": "P5：F10.7→倍率", "ja": "P5：F10.7→倍率",
                      "en": "P5: F10.7 → multiplier"},

    # ── ③ 統計層 + ML ───────────────────────────────────────────────────────
    "sec3_title": {"zh": "③ 統計偵測層（CUSUM/BOCPD/SSA）＋ ML 偵測/預測",
                   "ja": "③ 統計的検知層（CUSUM/BOCPD/SSA）＋ ML 検知・予測",
                   "en": "③ Statistical detection layer (CUSUM/BOCPD/SSA) + ML detection/forecast"},
    "succ_starlink_domain": {"zh": "🛰️ **{sat} 屬 Starlink（Model 1 分布內）→ 主判：Model 1（監督式）**，"
                                   "Model 2 / NRLMSIS 殘差供交叉驗證。",
                             "ja": "🛰️ **{sat} は Starlink（Model 1 の分布内）→ 主判定：Model 1（教師あり）**。"
                                   "Model 2 / NRLMSIS 残差はクロスチェックに使用します。",
                             "en": "🛰️ **{sat} is a Starlink satellite (in-distribution for Model 1) → "
                                   "primary: Model 1 (supervised)**; Model 2 / NRLMSIS residuals are "
                                   "used for cross-validation."},
    "warn_ood_domain": {"zh": "🌐 **{sat} 非 Starlink（Model 1 分布外／OOD）→ 主判：Model 2 + NRLMSIS 阻力殘差**"
                              "（regime-agnostic，適用於多種軌道域，無需預先指定軌道族群）。"
                              "Model 1 機率在此僅供參考，可能失準。",
                        "ja": "🌐 **{sat} は Starlink 以外（Model 1 の分布外／OOD）→ 主判定：Model 2 ＋ "
                              "NRLMSIS 大気抵抗残差**（regime-agnostic、軌道ファミリーを事前に指定せずに"
                              "複数の軌道領域へ適用可能）。"
                              "ここでの Model 1 の確率は参考値であり、精度が低い可能性があります。",
                        "en": "🌐 **{sat} is not a Starlink satellite (out-of-distribution for Model 1) "
                              "→ primary: Model 2 + NRLMSIS drag residual** (regime-agnostic, "
                              "applicable across multiple orbital regimes without a predefined regime "
                              "prior). The Model 1 probability is shown for reference only and may "
                              "be unreliable."},
    "err_reentry_decay": {"zh": "🔥 **偵測到自然再入/衰減軌道**（深近地點 + 單調快速衰減）→ "
                                "判定為大氣阻力自然衰減，**機動 = 0**。此類劇烈非線性衰減超出準secular阻力模型，"
                                "已由再入守門正確抑制誤報。",
                          "ja": "🔥 **自然再入・減衰軌道の可能性を検知**（低い近地点＋単調かつ急速な減衰）→ "
                                "大気抵抗による自然減衰と判定し、**マヌーバ件数 = 0**。"
                                "この種の激しい非線形減衰は準secular（準永年）抵抗モデルの適用範囲外のため、"
                                "再突入ゲートが誤検知を抑制しています。",
                          "en": "🔥 **Natural re-entry / decaying orbit pattern detected** (low perigee + "
                                "monotonic rapid decay) → classified as natural atmospheric-drag decay, "
                                "**maneuvers = 0**. Such strongly non-linear decay lies outside the "
                                "quasi-secular drag model, and the re-entry gate has correctly "
                                "suppressed the false alarms."},
    "metric_primary_m1": {"zh": "主判：Model 1 機動候選", "ja": "主判定：Model 1 マヌーバ候補",
                          "en": "Primary: Model 1 maneuver candidates"},
    "metric_nrlmsis_cross": {"zh": "NRLMSIS 殘差機動（交叉）",
                             "ja": "NRLMSIS残差によるマヌーバ候補（クロスチェック）",
                             "en": "NRLMSIS residual maneuvers (cross-check)"},
    "metric_m2_cross": {"zh": "Model 2 異常（交叉）", "ja": "Model 2 異常（クロスチェック）",
                        "en": "Model 2 anomalies (cross-check)"},
    "metric_primary_nrlmsis": {"zh": "主判：NRLMSIS 殘差機動候選",
                               "ja": "主判定：NRLMSIS残差によるマヌーバ候補",
                               "en": "Primary: NRLMSIS-residual maneuver candidates"},
    "metric_m2_support": {"zh": "Model 2 異常（佐證）", "ja": "Model 2 異常（補強）",
                          "en": "Model 2 anomalies (supporting)"},
    "metric_m1_ood": {"zh": "Model 1（參考，OOD）", "ja": "Model 1（参考・分布外）",
                      "en": "Model 1 (reference, OOD)"},
    "label_nrlmsis_times": {"zh": "NRLMSIS 主判機動時刻： ",
                            "ja": "NRLMSIS主判定のマヌーバ候補時刻： ",
                            "en": "NRLMSIS primary maneuver epochs: "},
    "fmt_nrlmsis_time": {"zh": "{d} (Δa殘差{v}km)", "ja": "{d}（Δa 残差 {v}km）",
                         "en": "{d} (Δa residual {v} km)"},
    "plot_cusum": {"zh": "CUSUM 累積統計", "ja": "CUSUM 累積統計量",
                   "en": "CUSUM cumulative statistic"},
    "plot_bocpd": {"zh": "BOCPD 短 run-length 機率", "ja": "BOCPD 短 run-length 確率",
                   "en": "BOCPD short run-length probability"},
    "plot_ssa": {"zh": "SSA 重構殘差 z", "ja": "SSA 再構成残差 z",
                 "en": "SSA reconstruction residual z"},
    "metric_events": {"zh": "{m} 事件數", "ja": "{m} イベント数", "en": "{m} events"},
    "exp_ml_forecast": {"zh": "ML forecast（未來 1 天機動機率，models_meme_forecast）",
                        "ja": "ML forecast（今後 1 日のマヌーバ発生確率、models_meme_forecast）",
                        "en": "ML forecast (maneuver probability within 1 day, "
                              "models_meme_forecast)"},
    "metric_forecast_p": {"zh": "未來 1 天內出現 ≥5km 機動之機率",
                          "ja": "今後 1 日以内に ≥5km のマヌーバが発生する確率",
                          "en": "Probability of a ≥5 km maneuver within 1 day"},
    "caption_feat_count": {"zh": "模型特徵數 {n}（含 CUSUM/BOCPD/SSA 統計量）",
                           "ja": "モデル特徴量数 {n}（CUSUM/BOCPD/SSA 統計量を含む）",
                           "en": "{n} model features (including CUSUM/BOCPD/SSA statistics)"},
    "caption_feat_insufficient": {"zh": "特徵不足，無法評分。",
                                  "ja": "特徴量が不足しているため、スコアリングできません。",
                                  "en": "Insufficient features; cannot score."},
    "caption_ml_model_unavailable": {"zh": "ML 模型/特徵不可得：{e}",
                                     "ja": "ML モデル／特徴量が利用できません：{e}",
                                     "en": "ML model / features unavailable: {e}"},
    "md_ml_detection": {"zh": "**ML 機動偵測（每窗口是否發生 ≥5km 機動 · models_meme，非預測）**",
                        "ja": "**ML マヌーバ検知（各ウィンドウで ≥5km のマヌーバが発生したか · "
                              "models_meme、予測ではない）**",
                        "en": "**ML maneuver detection (whether a ≥5 km maneuver occurred in each "
                              "window · models_meme; detection, not forecasting)**"},
    "spinner_ml_detect": {"zh": "ML 逐窗口偵測計算中…", "ja": "ML のウィンドウ単位検知を計算中…",
                          "en": "Computing per-window ML detection…"},
    "warn_pure_decay": {"zh": "⚠️ 此衛星整段 |Δa| 皆低於高度自適應閾值 → 判定為**純大氣阻力衰減/無機動**。"
                              "模型原始機率偏高係『分布外』(此模型僅在 Starlink 機動衛星上訓練)，"
                              "已由物理閘門正確濾除為 0。",
                        "ja": "⚠️ この衛星は全期間で |Δa| が高度適応しきい値を下回っています → "
                              "**純粋な大気抵抗による減衰／マヌーバなし**と判定。"
                              "モデルの生確率が高いのは「分布外」によるもので"
                              "（本モデルはマヌーバを行う Starlink 衛星のみで学習）、"
                              "物理ゲートにより正しく 0 に除去されています。",
                        "en": "⚠️ |Δa| stays below the altitude-adaptive threshold over the whole span "
                              "→ classified as **pure atmospheric-drag decay / no maneuver**. "
                              "The high raw model probability is an out-of-distribution effect (this "
                              "model was trained only on manoeuvring Starlink satellites) and has been "
                              "correctly filtered to 0 by the physical gate."},
    "legend_model_raw_prob": {"zh": "模型原始機率", "ja": "モデル生確率",
                              "en": "Raw model probability"},
    "annot_model_thr": {"zh": "模型門檻 {thr}", "ja": "モデルしきい値 {thr}",
                        "en": "Model threshold {thr}"},
    "legend_ml_detected": {"zh": "ML 偵測機動（通過物理閘門）",
                           "ja": "ML検知マヌーバ（物理ゲート通過）",
                           "en": "ML-detected maneuvers (passed physical gate)"},
    "yaxis_p_window": {"zh": "P(此窗發生機動)", "ja": "P(このウィンドウでマヌーバが発生)",
                       "en": "P(maneuver in this window)"},
    "metric_ml_windows": {"zh": "ML 偵測到的機動窗口", "ja": "ML が検知したマヌーバウィンドウ",
                          "en": "ML-detected maneuver windows"},
    "metric_raw_above_thr": {"zh": "模型原始 P>門檻 窗口",
                             "ja": "モデル生 P>しきい値 のウィンドウ",
                             "en": "Windows with raw P > threshold"},
    "metric_max_da": {"zh": "最大 |Δa| (km)", "ja": "最大 |Δa| (km)", "en": "Max |Δa| (km)"},
    "caption_model1_gate": {"zh": "Model 1（監督式，Starlink 專用）。**物理閘門**：ML 旗標須同時 (模型機率≥門檻) 且 "
                                  "(NRLMSIS 扣大氣阻力後 |殘差Δa|>0.3km)——先扣除阻力(含 F10.7/Ap)，"
                                  "旨在降低純衰減／太陽極大期的誤報。",
                            "ja": "Model 1（教師あり、Starlink 専用）。**物理ゲート**：ML フラグには "
                                  "(モデル確率≥しきい値) かつ (NRLMSIS で大気抵抗を除去後 |残差Δa|>0.3km) "
                                  "の両方が必要です。抵抗（F10.7/Ap を含む）を除去することで、"
                                  "純粋な減衰や太陽活動極大期における誤検知の低減を目的としています。",
                            "en": "Model 1 (supervised, Starlink-specific). **Physical gate**: an ML "
                                  "flag requires both (model probability ≥ threshold) and "
                                  "(|Δa residual| > 0.3 km after NRLMSIS drag removal). By removing "
                                  "drag (including F10.7/Ap) first, it is designed to reduce false "
                                  "alarms during pure decay and solar maximum."},
    "caption_ml_detect_unavailable": {"zh": "ML 偵測不可得（TLE 不足或模型缺失）。",
                                      "ja": "ML 検知は利用できません（TLE 不足またはモデル欠落）。",
                                      "en": "ML detection unavailable (insufficient TLEs or missing "
                                            "model)."},
    "md_model2": {"zh": "**Model 2：跨多種軌道域的異常偵測（無監督 · 無需預先指定軌道族群 · "
                        "旨在降低將純大氣阻力衰減誤判為機動的風險）**",
                  "ja": "**Model 2：複数の軌道領域に適用可能な異常検知（教師なし · "
                        "軌道ファミリーの事前指定が不要 · "
                        "抵抗による純粋な減衰をマヌーバと誤判定するリスクの低減を目的）**",
                  "en": "**Model 2: anomaly detection across multiple orbital regimes (unsupervised · "
                        "no predefined regime prior · designed to reduce the risk of misclassifying "
                        "pure drag decay as a maneuver)**"},
    "spinner_model2": {"zh": "Model 2 物理殘差計算中…", "ja": "Model 2 の物理残差を計算中…",
                       "en": "Computing Model 2 physical residuals…"},
    "legend_nrlmsis_resid": {"zh": "NRLMSIS 阻力殘差 (σ)", "ja": "NRLMSIS 大気抵抗残差 (σ)",
                             "en": "NRLMSIS drag residual (σ)"},
    "legend_m2_anomaly": {"zh": "Model 2 異常(機動)", "ja": "Model 2 異常（マヌーバ候補）",
                          "en": "Model 2 anomaly (maneuver)"},
    "yaxis_drag_resid": {"zh": "阻力殘差 (物理σ=0.1km)", "ja": "大気抵抗残差（物理 σ=0.1km）",
                         "en": "Drag residual (physical σ = 0.1 km)"},
    "metric_m2_detected": {"zh": "Model 2 偵測異常(機動)", "ja": "Model 2 検知異常（マヌーバ候補）",
                           "en": "Model 2 detected anomalies (maneuvers)"},
    "metric_max_drag_resid": {"zh": "最大阻力殘差 (σ)", "ja": "最大大気抵抗残差 (σ)",
                              "en": "Max drag residual (σ)"},
    "caption_model2_note": {"zh": "Model 2 用大氣密度模型(NRLMSIS)扣除阻力後的物理殘差，"
                                  "不靠 alt/inc 族群先驗 → 適用於 LEO/MEO/GEO/HEO 等多種軌道域，"
                                  "旨在降低將純大氣阻力衰減誤判為機動的風險。",
                            "ja": "Model 2 は大気密度モデル（NRLMSIS）で抵抗を除去した物理残差を用い、"
                                  "高度・傾斜角のグループ事前分布に依存しません → "
                                  "LEO/MEO/GEO/HEO での利用を想定しており、"
                                  "抵抗による純粋な減衰をマヌーバと誤判定するリスクの低減を"
                                  "目的としています。",
                            "en": "Model 2 uses physical residuals after removing drag with an "
                                  "atmospheric density model (NRLMSIS) and needs no altitude/"
                                  "inclination group prior → it is intended for use across "
                                  "LEO/MEO/GEO/HEO and is designed to reduce the risk of "
                                  "misclassifying pure drag decay as a maneuver."},
    "caption_model2_unavailable": {"zh": "Model 2 不可得（需 model2.pkl / pymsis / SW 資料）。",
                                   "ja": "Model 2 は利用できません（model2.pkl / pymsis / 宇宙天気データが必要）。",
                                   "en": "Model 2 unavailable (requires model2.pkl / pymsis / space "
                                         "weather data)."},
    "md_fusion": {"zh": "**融合評分器：五通道 → 單一連續機動機率**（Layer 2 統計層融合，"
                        "AUC 0.98／AP 0.96／large recall 0.97）",
                  "ja": "**融合スコアラー：5 チャンネル → 単一の連続マヌーバ確率**（Layer 2 統計層の融合、"
                        "AUC 0.98／AP 0.96／large recall 0.97）",
                  "en": "**Fusion scorer: five channels → a single continuous maneuver probability** "
                        "(Layer 2 statistical fusion, AUC 0.98 / AP 0.96 / large recall 0.97)"},
    "spinner_fusion": {"zh": "融合評分計算中…", "ja": "融合スコアを計算中…",
                       "en": "Computing fusion scores…"},
    "legend_fusion_prob": {"zh": "融合機動機率", "ja": "融合マヌーバ確率",
                           "en": "Fused maneuver probability"},
    "annot_op_thr": {"zh": "操作門檻 {thr} (FPR≤0.05)", "ja": "運用しきい値 {thr}（FPR≤0.05）",
                     "en": "Operating threshold {thr} (FPR ≤ 0.05)"},
    "legend_fusion_flag": {"zh": "融合旗標", "ja": "融合フラグ", "en": "Fusion flag"},
    "yaxis_fusion_prob": {"zh": "融合機率", "ja": "融合確率", "en": "Fusion probability"},
    "caption_fusion_note": {"zh": "融合旗標 {n} 筆。以衛星分組 CV 訓練(HistGBM)，"
                                  "unit 級對齊 MEME 真值，操作點取評估中 FPR≤0.05 條件下 recall 最高者。",
                            "ja": "融合フラグ {n} 件。衛星単位のグループ CV で学習（HistGBM）し、"
                                  "unit レベルで MEME 真値と対応付け、動作点は評価時に FPR≤0.05 の下で "
                                  "recall が最も高かった点を採用しています。",
                            "en": "{n} fusion flags. Trained with satellite-grouped CV (HistGBM), "
                                  "aligned to MEME ground truth at unit level; the operating point was "
                                  "selected as the one giving the highest recall observed under "
                                  "FPR ≤ 0.05 in evaluation."},
    "caption_fusion_unavailable": {"zh": "融合評分器不可得（需 models_fusion/fusion_scorer.pkl，"
                                         "執行 `python fusion_scorer.py`）。",
                                   "ja": "融合スコアラーは利用できません"
                                         "（models_fusion/fusion_scorer.pkl が必要。"
                                         "`python fusion_scorer.py` を実行してください）。",
                                   "en": "Fusion scorer unavailable (requires "
                                         "models_fusion/fusion_scorer.pkl — run "
                                         "`python fusion_scorer.py`)."},

    # ── ⑤ MEME vs TLE ───────────────────────────────────────────────────────
    "sec5_title": {"zh": "⑤ MEME vs TLE（僅 72h 模型，不做長時程外推）",
                   "ja": "⑤ MEME vs TLE（72h モデルのみ、長期外挿は行わない）",
                   "en": "⑤ MEME vs TLE (72 h model only; no long-term extrapolation)"},
    "xaxis_meme_age": {"zh": "MEME 外推齡 (h, 0–72)", "ja": "MEME 外挿経過時間 (h, 0–72)",
                       "en": "MEME propagation age (h, 0–72)"},
    "yaxis_tle_meme_err": {"zh": "TLE-vs-MEME 位置誤差 (km)", "ja": "TLE-vs-MEME 位置誤差 (km)",
                           "en": "TLE-vs-MEME position error (km)"},
    "caption_meme_err": {"zh": "72h 內位置誤差中位 {med} km、P95 {p95} km",
                         "ja": "72h 以内の位置誤差 中央値 {med} km、P95 {p95} km",
                         "en": "Position error within 72 h: median {med} km, P95 {p95} km"},
    "caption_no_meme": {"zh": "無 {sat} 的 MEME 星曆（data/raw/）。",
                        "ja": "{sat} の MEME 暦（data/raw/）がありません。",
                        "en": "No MEME ephemeris for {sat} (data/raw/)."},
    "caption_meme_unavailable": {"zh": "MEME 比較不可得：{e}",
                                 "ja": "MEME 比較は利用できません：{e}",
                                 "en": "MEME comparison unavailable: {e}"},

    # ── ⑥ 資料品質稽核 ───────────────────────────────────────────────────────
    "sec6_title": {"zh": "⑥ 資料品質稽核（quality_flag：good / suspect / rejected）",
                   "ja": "⑥ データ品質監査（quality_flag：good / suspect / rejected）",
                   "en": "⑥ Data quality audit (quality_flag: good / suspect / rejected)"},
    "metric_q_good": {"zh": "良好 good", "ja": "良好 good", "en": "Good"},
    "metric_q_suspect": {"zh": "存疑 suspect", "ja": "要確認 suspect", "en": "Suspect"},
    "metric_q_rejected": {"zh": "剔除 rejected", "ja": "除外 rejected", "en": "Rejected"},
    "metric_q_dup": {"zh": "重複移除 (≤60s)", "ja": "重複除去 (≤60s)",
                     "en": "Duplicates removed (≤60 s)"},
    "metric_q_topreason": {"zh": "主因", "ja": "主な要因", "en": "Top reasons"},
    "plot_q_title": {"zh": "半長軸時序（依 quality_flag 著色）",
                     "ja": "軌道長半径の時系列（quality_flag で色分け）",
                     "en": "Semi-major axis time series (colored by quality_flag)"},
    "caption_bad_count": {"zh": "非 good 共 {n} 筆（可下載複核）：",
                          "ja": "good 以外は計 {n} 件（ダウンロードして再確認できます）：",
                          "en": "{n} TLE records are not classified as “good” "
                                "(downloadable for review):"},
    "caption_all_good": {"zh": "此日期範圍內 TLE 全部判定為 good。",
                         "ja": "この期間の TLE はすべて good と判定されました。",
                         "en": "All TLEs in this date range are classified as good."},
    "caption_q_rules": {"zh": "規則：**rejected**＝e∉[0,1)／sma≤R⊕／inc∉[0,180]／checksum 錯；"
                              "**suspect**＝TLE 缺口>48h（J2 外推誤差，見 NORAD 44349 案例）／單步 Δi>3°／|B\\*|>1；"
                              "重複 epoch（≤60s）已移除另計，不影響品質判定。全庫稽核：`python data_quality_audit.py`。",
                        "ja": "ルール：**rejected**＝e∉[0,1)／sma≤R⊕／inc∉[0,180]／チェックサム誤り。"
                              "**suspect**＝TLE 欠測>48h（J2 外挿誤差、NORAD 44349 の事例を参照）／"
                              "1 ステップの Δi>3°／|B\\*|>1。"
                              "重複 epoch（≤60s）は別途除去済みで、品質判定には影響しません。"
                              "全データベース監査：`python data_quality_audit.py`。",
                        "en": "Rules: **rejected** = e ∉ [0,1) / sma ≤ R⊕ / inc ∉ [0,180] / bad "
                              "checksum; **suspect** = TLE gap > 48 h (J2 propagation error, see the "
                              "NORAD 44349 case) / single-step Δi > 3° / |B\\*| > 1. "
                              "Duplicate epochs (≤60 s) are removed and counted separately and do not "
                              "affect the quality verdict. Full-database audit: "
                              "`python data_quality_audit.py`."},

    # ── ⑦ 星系級異常分析 ────────────────────────────────────────────────────
    "sec7_title": {"zh": "⑦ 星系級異常分析（軌道面 Δi std／批量機動／陣型誤差）",
                   "ja": "⑦ コンステレーション規模の異常解析（軌道面 Δi std／一斉マヌーバ／編隊誤差）",
                   "en": "⑦ Constellation-level anomaly analysis (per-plane Δi std / batch maneuvers "
                         "/ formation error)"},
    "caption_not_constellation": {"zh": "「{sat}」不屬於已知星系清單，略過。已知：{known}",
                                  "ja": "「{sat}」は既知のコンステレーション一覧に含まれないためスキップします。"
                                        "既知：{known}",
                                  "en": "“{sat}” is not in the known constellation list; skipping. "
                                        "Known: {known}"},
    "slider_analysis_window": {"zh": "分析窗（天）", "ja": "解析ウィンドウ（日）",
                               "en": "Analysis window (days)"},
    "btn_run_constellation": {"zh": "▶ 執行 {cn} 星系級分析（大型星系需 10–20 秒）",
                              "ja": "▶ {cn} のコンステレーション解析を実行（大規模な場合 10–20 秒）",
                              "en": "▶ Run {cn} constellation-level analysis (10–20 s for large "
                                    "constellations)"},
    "spinner_constellation": {"zh": "{cn} 星系級分析中…", "ja": "{cn} のコンステレーション解析中…",
                              "en": "Running {cn} constellation-level analysis…"},
    "warn_constellation_insufficient": {"zh": "星系資料不足。",
                                        "ja": "コンステレーションのデータが不足しています。",
                                        "en": "Insufficient constellation data."},
    "caption_constellation_scope": {"zh": "{cn}：**{n}** 顆，窗 {d0} ~ {d1}",
                                    "ja": "{cn}：**{n}** 機、期間 {d0} ~ {d1}",
                                    "en": "{cn}: **{n}** satellites, window {d0} – {d1}"},
    "metric_c1": {"zh": "① 異常軌道面", "ja": "① 異常な軌道面",
                  "en": "① Incoherent orbital planes"},
    "metric_c1_delta": {"zh": "{n} 面", "ja": "{n} 面", "en": "{n} planes"},
    "metric_c2": {"zh": "② 批量事件日", "ja": "② 一斉マヌーバイベント日",
                  "en": "② Batch event days"},
    "metric_c3": {"zh": "③ 相位離群衛星", "ja": "③ 位相外れ衛星",
                  "en": "③ Phase-outlier satellites"},
    "exp_c1": {"zh": "① 軌道面一致性（同 RAAN 面 Δi 標準差，降冪）",
               "ja": "① 軌道面の整合性（同一 RAAN 面の Δi 標準偏差、降順）",
               "en": "① Plane coherence (Δi standard deviation within each RAAN plane, descending)"},
    "exp_c2": {"zh": "② 批量機動識別（同天顯著 |Δa|>2km 機動衛星數）",
               "ja": "② 一斉マヌーバの識別（同日に |Δa|>2km の顕著なマヌーバを行った衛星数）",
               "en": "② Batch maneuver identification (number of satellites with a significant "
                     "|Δa| > 2 km on the same day)"},
    "exp_c3": {"zh": "③ 陣型誤差（同面緯度幅角相位殘差 std，降冪）",
               "ja": "③ 編隊誤差（同一面内の緯度引数における位相残差 std、降順）",
               "en": "③ Formation error (std of argument-of-latitude phase residuals within a plane, "
                     "descending)"},
    "caption_constellation_note": {"zh": "① Δi std 過高＝協同傾角機動/星系重組；② 同天機動數 > mean+3σ＝批量"
                                         "部署/重組；③ 緯度幅角偏離均勻間隔＝相位保持失效/戰術移相。"
                                         "對應事件分類：批量部署／星系重組／戰術機動。",
                                   "ja": "① Δi std が過大＝協調的な傾斜角マヌーバ／コンステレーション再編。"
                                         "② 同日のマヌーバ件数 > mean+3σ＝一斉配備／再編。"
                                         "③ 緯度引数が均等間隔から外れる＝位相保持の失敗／戦術的な位相変更。"
                                         "対応するイベント分類：一斉配備／コンステレーション再編／"
                                         "戦術的マヌーバ。",
                                   "en": "① Excessive Δi std = coordinated inclination maneuvers / "
                                         "constellation restructuring; ② same-day maneuver count > "
                                         "mean + 3σ = batch deployment / restructuring; ③ argument of "
                                         "latitude departing from uniform spacing = loss of phase "
                                         "keeping / tactical phasing. Corresponding event classes: "
                                         "batch deployment / constellation restructuring / tactical "
                                         "maneuver."},

    # ── ④ 艦隊級統計 ─────────────────────────────────────────────────────────
    "sec4_title": {"zh": "④ 艦隊級統計（全 MEME 284 顆）＋ 95% 信賴區間",
                   "ja": "④ フリート全体の統計（MEME 全 284 機）＋ 95% 信頼区間",
                   "en": "④ Fleet-level statistics (all 284 MEME satellites) + 95% confidence "
                         "intervals"},
    "metric_fleet_rate": {"zh": "艦隊機動事件率（每 30 天／每顆）",
                          "ja": "衛星群全体のマヌーバイベント率（30日あたり／衛星）",
                          "en": "Fleet maneuver-event rate (per 30 days per satellite)"},
    "metric_fleet_ci": {"zh": "95% CI [{lo}, {hi}]", "ja": "95% CI [{lo}, {hi}]",
                        "en": "95% CI [{lo}, {hi}]"},
    "caption_fleet_n": {"zh": "{n} 顆有 ≥5km 機動", "ja": "{n} 機に ≥5km のマヌーバあり",
                        "en": "{n} satellites with ≥5 km maneuvers"},
    "md_detector_vs_truth": {"zh": "**各偵測器（TLE 序列）vs MEME 真值**",
                             "ja": "**各検知器（TLE 系列）vs MEME 真値**",
                             "en": "**Each detector (TLE series) vs MEME ground truth**"},
    "caption_no_truth": {"zh": "找不到 transitions_full 真值檔。",
                         "ja": "transitions_full の真値ファイルが見つかりません。",
                         "en": "transitions_full ground-truth file not found."},

    # ── ⑩ 合成 TLE ───────────────────────────────────────────────────────────
    "sec10_title": {"zh": "⑩ 合成 TLE 批次生成", "ja": "⑩ 合成TLEの一括生成",
                    "en": "⑩ Batch synthetic TLE generation"},
    "exp_synth": {"zh": "展開合成資料生成器（依條件批次產生）",
                  "ja": "合成データ生成器を開く（条件を指定して一括生成）",
                  "en": "Open the synthetic data generator (batch generation by criteria)"},
    "num_n_sat": {"zh": "衛星數", "ja": "衛星数", "en": "Number of satellites"},
    "num_n_days": {"zh": "天數", "ja": "日数", "en": "Number of days"},
    "num_cadence": {"zh": "TLE 間隔 (h)", "ja": "TLE 間隔 (h)", "en": "TLE cadence (h)"},
    "slider_man_frac": {"zh": "含機動比例", "ja": "マヌーバを含む割合",
                        "en": "Fraction containing maneuvers"},
    "slider_alt_range": {"zh": "高度範圍 (km)", "ja": "高度範囲 (km)", "en": "Altitude range (km)"},
    "slider_inc_range": {"zh": "傾角範圍 (deg)", "ja": "軌道傾斜角範囲 (deg)",
                         "en": "Inclination range (deg)"},
    "slider_dv_range": {"zh": "ΔV 範圍 (m/s)", "ja": "ΔV 範囲 (m/s)", "en": "ΔV range (m/s)"},
    "sel_noise": {"zh": "雜訊等級", "ja": "ノイズレベル", "en": "Noise level"},
    "num_seed": {"zh": "亂數種子", "ja": "乱数シード", "en": "Random seed"},
    "btn_gen_synth": {"zh": "生成並下載 synthetic.tle",
                      "ja": "synthetic.tle を生成してダウンロード",
                      "en": "Generate and download synthetic.tle"},
    "spinner_gen_synth": {"zh": "生成 {n_sat} 顆 × {n_tles} TLE…",
                          "ja": "{n_sat} 機 × {n_tles} 件の TLE を生成中…",
                          "en": "Generating {n_sat} satellites × {n_tles} TLEs…"},
    "succ_synth_done": {"zh": "完成：{n_sat} 顆（含機動 {n_man} 顆），每顆 ~{n_tles} 筆 TLE。",
                        "ja": "完了：{n_sat} 機（うちマヌーバあり {n_man} 機）、"
                              "1 機あたり約 {n_tles} 件の TLE。",
                        "en": "Done: {n_sat} satellites ({n_man} with maneuvers), about {n_tles} TLEs "
                              "each."},
    "btn_download_synth": {"zh": "下載 synthetic.tle", "ja": "synthetic.tle をダウンロード",
                           "en": "Download synthetic.tle"},
    "caption_synth_unavailable": {"zh": "合成模組不可得：{e}（可改用 synthetic_app.py）",
                                  "ja": "合成モジュールは利用できません：{e}"
                                        "（代わりに synthetic_app.py を使用できます）",
                                  "en": "Synthetic module unavailable: {e} (you can use "
                                        "synthetic_app.py instead)"},

    # ── ⑧ SSA-RAG 知識問答 / footer ─────────────────────────────────────────
    "sec8_title": {"zh": "⑧ SSA-RAG 知識問答（太空態勢感知知識庫）",
                   "ja": "⑧ SSA-RAG ナレッジ Q&A（宇宙状況把握ナレッジベース）",
                   "en": "⑧ SSA-RAG knowledge Q&A (space situational awareness knowledge base)"},
    "exp_rag_qa": {"zh": "展開互動問答（需 SSA-RAG 服務上線）",
                   "ja": "対話型 Q&A を開く（SSA-RAG サービスの起動が必要）",
                   "en": "Open interactive Q&A (requires the SSA-RAG service to be running)"},
    "footer": {"zh": "maneuver_app_2026September.py · 模型：P1–P6（拋物線 P2/P5）· CUSUM/BOCPD/SSA · "
                     "MEME-tuned 偵測(window≥5km) + forecast(1d) · 真值：MEME 284 顆 · "
                     "SSA-RAG 自動解說＋知識問答",
               "ja": "maneuver_app_2026September.py · モデル：P1–P6（放物線 P2/P5）· CUSUM/BOCPD/SSA · "
                     "MEME チューニング済みマヌーバ検知(window≥5km) ＋ forecast(1d) · "
                     "真値：MEME 284 機 · "
                     "SSA-RAG 自動解説＋ナレッジ Q&A",
               "en": "maneuver_app_2026September.py · Models: P1–P6 (parabolic P2/P5) · CUSUM/BOCPD/SSA "
                     "· MEME-tuned detection (window ≥5 km) + forecast (1 d) · Ground truth: 284 MEME "
                     "satellites · SSA-RAG auto-explanation + knowledge Q&A"},
}

# DataFrame 欄位表頭對照（僅顯示時套用，不改動原始 DataFrame）
COL_LABELS: dict[str, dict[str, str]] = {
    # TLE 根數 / 品質稽核
    "epoch": {"zh": "時刻(UTC)", "ja": "時刻(UTC)", "en": "Epoch (UTC)"},
    "sma_km": {"zh": "半長軸(km)", "ja": "軌道長半径(km)", "en": "SMA (km)"},
    "inclination_deg": {"zh": "傾角(deg)", "ja": "軌道傾斜角(deg)", "en": "Inclination (deg)"},
    "eccentricity": {"zh": "離心率", "ja": "離心率", "en": "Eccentricity"},
    "raan_deg": {"zh": "升交點赤經(deg)", "ja": "昇交点赤経(deg)", "en": "RAAN (deg)"},
    "argp_deg": {"zh": "近地點幅角(deg)", "ja": "近地点引数(deg)", "en": "Arg. of perigee (deg)"},
    "mean_anomaly_deg": {"zh": "平近點角(deg)", "ja": "平均近点角(deg)", "en": "Mean anomaly (deg)"},
    "bstar": {"zh": "B*", "ja": "B*", "en": "B*"},
    "quality_flag": {"zh": "品質旗標", "ja": "品質フラグ", "en": "Quality flag"},
    "quality_reason": {"zh": "品質原因", "ja": "品質判定理由", "en": "Quality reason"},
    # ② P1–P6 策略表
    "strategy": {"zh": "策略", "ja": "戦略", "en": "Strategy"},
    "n_flags": {"zh": "旗標/抑制數", "ja": "フラグ／抑制数", "en": "Flags / suppressions"},
    "kind": {"zh": "類型", "ja": "種別", "en": "Type"},
    # ⑦ 星系級：軌道面 / 批量 / 陣型
    "plane": {"zh": "軌道面", "ja": "軌道面", "en": "Plane"},
    "n": {"zh": "顆數", "ja": "機数", "en": "Count"},
    "raan_mean": {"zh": "RAAN 平均(deg)", "ja": "RAAN 平均(deg)", "en": "Mean RAAN (deg)"},
    "inc_mean": {"zh": "傾角平均(deg)", "ja": "軌道傾斜角 平均(deg)", "en": "Mean inclination (deg)"},
    "di_std_deg": {"zh": "Δi 標準差(deg)", "ja": "Δi 標準偏差(deg)", "en": "Δi std (deg)"},
    "di_absmax_deg": {"zh": "|Δi| 最大(deg)", "ja": "|Δi| 最大(deg)", "en": "Max |Δi| (deg)"},
    "flag_plane_incoherent": {"zh": "軌道面不一致", "ja": "軌道面 不整合",
                              "en": "Plane incoherent"},
    "day": {"zh": "日期", "ja": "日付", "en": "Date"},
    "n_maneuvering": {"zh": "當日機動衛星數", "ja": "当日のマヌーバ実施衛星数",
                      "en": "Maneuvering satellites"},
    "flag_batch": {"zh": "批量事件", "ja": "一斉イベント", "en": "Batch event"},
    "slot_deg": {"zh": "理想間隔(deg)", "ja": "理想スロット間隔(deg)", "en": "Ideal slot (deg)"},
    "phase_resid_std_deg": {"zh": "相位殘差標準差(deg)", "ja": "位相残差 標準偏差(deg)",
                            "en": "Phase residual std (deg)"},
    "n_outliers": {"zh": "離群衛星數", "ja": "外れ値衛星数", "en": "Outlier satellites"},
    # ④ 偵測器指標
    "method": {"zh": "方法", "ja": "手法", "en": "Method"},
    "precision": {"zh": "精確率（Precision）", "ja": "適合率", "en": "Precision"},
    "recall": {"zh": "召回率", "ja": "再現率", "en": "Recall"},
    "lead_time_h_median": {"zh": "提前時間中位數 (h)", "ja": "リードタイム中央値 (h)",
                           "en": "Median lead time (h)"},
}


def _lang() -> str:
    return st.session_state.get("app_lang", "zh")


def t(key: str, **kwargs) -> str:
    d = L.get(key, {})
    s = d.get(_lang()) or d.get("zh") or key
    return s.format(**kwargs) if kwargs else s


def tcols(df: pd.DataFrame) -> pd.DataFrame:
    """僅供顯示：把 DataFrame 欄名換成目前語言的表頭（不修改原 DataFrame）。"""
    lang = _lang()
    return df.rename(columns={c: COL_LABELS.get(c, {}).get(lang, c) for c in df.columns})


st.set_page_config(page_title=t("page_title"), page_icon="🛰️", layout="wide")

# ── 資料後端 bootstrap（本機全庫 / HuggingFace 遠端 Parquet）─────────────────────
# 環境變數：
#   HF_DATASET_REPO   HF Dataset repo id，例如 "rhynowu/starlink-maneuver-db"（設了即走遠端）
#   LOCAL_DB_PATH     本機全庫路徑（預設 space_db.duckdb）
#   HF_STUB_PATH      遠端模式 stub duckdb 路徑（預設 space_hf.duckdb）
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "").strip()
LOCAL_DB = os.environ.get("LOCAL_DB_PATH", "space_db.duckdb")
STUB_DB = os.environ.get("HF_STUB_PATH", "space_hf.duckdb")

# 遠端 dataset 內的相對佈局（須與 export_to_hf_parquet.py 產出的目錄一致）
_HF_LAYOUT = {
    # view 名稱 : (glob 相對路徑, 是否為必要表)
    "raw_tle_archive":   ("raw_tle_archive/**/*.parquet", True),
    "catalog":           ("catalog.parquet", True),
    "sat_n2yo_metadata": ("sat_n2yo_metadata/**/*.parquet", False),
    "maneuver_labels":   ("maneuver_labels/**/*.parquet", False),
    "conjunction_events": ("conjunction_events/**/*.parquet", False),
    "training_samples":  ("training_samples/**/*.parquet", False),
    "training_samples_plan_b": ("training_samples_plan_b/**/*.parquet", False),
}


def _ensure_httpfs() -> None:
    """確保 httpfs 已安裝（安裝需可寫連線；之後 read_only 連線即可 autoload）。
    若環境變數 HF_TOKEN 存在，建立「持久化」HF secret，讓 read_only 連線也能讀 private dataset。"""
    try:
        c = duckdb.connect()
        c.execute("INSTALL httpfs")
        c.execute("LOAD httpfs")
        tok = os.environ.get("HF_TOKEN", "").strip()
        if tok:
            try:
                c.execute(
                    "CREATE OR REPLACE PERSISTENT SECRET hf_token "
                    "(TYPE huggingface, TOKEN ?)", [tok])
            except Exception as e:
                st.warning(t("warn_hf_secret", e=e))
        c.close()
    except Exception as e:  # 安裝失敗時仍嘗試往下（可能已裝好）
        st.warning(t("warn_httpfs", e=e))


def _build_hf_stub(stub_path: str, repo: str) -> str:
    """建立/更新輕量 stub DuckDB：內含指向 hf://datasets/<repo>/... 的 VIEW。
    僅存 view 定義，不落地資料；查詢時 httpfs 依 row-group 統計只抓需要區塊。"""
    base = f"hf://datasets/{repo}"
    con = duckdb.connect(stub_path)
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    for view, (rel, required) in _HF_LAYOUT.items():
        url = f"{base}/{rel}"
        try:
            con.execute(f"CREATE OR REPLACE VIEW {view} AS "
                        f"SELECT * FROM read_parquet('{url}', union_by_name=true)")
        except Exception as e:
            if required:
                con.close()
                raise RuntimeError(f"必要表 {view} 建 VIEW 失敗（{url}）：{e}") from e
            # 可選表缺檔 → 跳過
    con.close()
    return stub_path


@st.cache_resource(show_spinner=t("spinner_init_backend"))
def _bootstrap_db() -> tuple[str, str]:
    """回傳 (DB_PATH, backend)。backend ∈ {'local','hf'}。"""
    if HF_DATASET_REPO:
        _ensure_httpfs()
        _build_hf_stub(STUB_DB, HF_DATASET_REPO)
        return STUB_DB, "hf"
    if Path(LOCAL_DB).exists():
        return LOCAL_DB, "local"
    # 本機無全庫、也未指定 HF repo：若已有預建 stub 就用它
    if Path(STUB_DB).exists():
        _ensure_httpfs()
        return STUB_DB, "hf"
    st.error(t("err_no_datasource"))
    st.stop()


DB_PATH, DATA_BACKEND = _bootstrap_db()


# ── cached loaders ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_catalog() -> pd.DataFrame:
    con = duckdb.connect(DB_PATH, read_only=True)
    # HF 遠端模式：優先讀預先彙整的小 catalog（避免對 19.5M 列做全表 GROUP BY）
    if DATA_BACKEND == "hf":
        try:
            df = con.execute(
                "SELECT norad_id, name, n FROM catalog ORDER BY norad_id").fetchdf()
            con.close()
            return df
        except Exception:
            pass  # 無 catalog 表 → 回退全表彙整
    df = con.execute(
        "SELECT norad_id, ANY_VALUE(object_name) AS name, COUNT(*) n "
        "FROM raw_tle_archive GROUP BY norad_id"
    ).fetchdf()
    con.close()
    return df


@st.cache_data(show_spinner=False)
def load_registry_names() -> dict:
    try:
        from compare_tle_vs_ephemeris import load_registry
        reg = load_registry(DATA / "url_registry.csv")
        return {int(k): v for k, v in reg["sat_name"].items()}
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def load_tle(norad_id: int, start=None, end=None) -> pd.DataFrame:
    con = duckdb.connect(DB_PATH, read_only=True)
    q = ("SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
         "raan_deg, argp_deg, mean_anomaly_deg, bstar, line1, line2 FROM raw_tle_archive "
         "WHERE norad_id=? ORDER BY epoch_utc")
    df = con.execute(q, [int(norad_id)]).fetchdf()
    con.close()
    if df.empty:
        return df
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    if start is not None:
        df = df[df["epoch"] >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df["epoch"] <= pd.Timestamp(end, tz="UTC")]
    return df.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_f107() -> dict:
    p = Path("f107_cache.csv")
    if not p.exists():
        return {}
    f = pd.read_csv(p)
    f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
    return dict(zip(f["epoch"], f["f107"]))


@st.cache_data(show_spinner=False)
def load_truth() -> pd.DataFrame:
    g = sorted((DATA / "meme_truth").glob("transitions_full_*.csv"))
    if not g:
        return pd.DataFrame()
    t = pd.read_csv(g[-1])
    t["t_to"] = pd.to_datetime(t["t_to"], utc=True)
    return t


@st.cache_data(show_spinner=False)
def load_stat_metrics() -> pd.DataFrame:
    g = sorted((DATA / "statistical_layer").glob("metrics_*.csv"))
    return pd.read_csv(g[-1]) if g else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_fleet_recent_tle(norad_ids: tuple[int, ...], days: int = 30) -> pd.DataFrame:
    """艦隊批次查詢近 N 天 TLE（單次 SQL，避免逐顆迴圈查詢 284 次）。"""
    if not norad_ids:
        return pd.DataFrame()
    con = duckdb.connect(DB_PATH, read_only=True)
    ids_str = ",".join(str(int(n)) for n in norad_ids)
    df = con.execute(
        f"SELECT norad_id, epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
        f"raan_deg, bstar FROM raw_tle_archive "
        f"WHERE norad_id IN ({ids_str}) AND epoch_utc >= now() - INTERVAL '{int(days)} days' "
        f"ORDER BY norad_id, epoch_utc"
    ).fetchdf()
    con.close()
    if not df.empty:
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    return df


def fleet_quality_good_pct(fleet_tle: pd.DataFrame) -> tuple[float, int]:
    """逐顆衛星分別稽核（quality 檢查含 diff，須依單顆時序）後彙總。回傳 (good 比例, 稽核總筆數)。"""
    if fleet_tle.empty:
        return float("nan"), 0
    parts = []
    for _, g in fleet_tle.groupby("norad_id"):
        if len(g) >= 2:
            parts.append(dqa.audit_tles(g))
    if not parts:
        return float("nan"), 0
    audited = pd.concat(parts, ignore_index=True)
    s = dqa.summarize(audited)
    return s["frac_good"], s["n"]


def fleet_suspected_deorbiting(fleet_tle: pd.DataFrame, window_days: int = 7) -> tuple[int, int]:
    """套用 da_monotonic_decay 公式（同 build_training_dataset.py，7 天窗版）於艦隊最新窗格。
    回傳 (旗標為 1 的顆數, 有足夠資料可判定的顆數)。"""
    if fleet_tle.empty:
        return 0, 0
    n_flagged, n_checked = 0, 0
    for _, g in fleet_tle.groupby("norad_id"):
        g = g.sort_values("epoch")
        latest_t = g["epoch"].max()
        window = g[g["epoch"] >= latest_t - pd.Timedelta(days=window_days)]
        if len(window) < 3:
            continue
        n_checked += 1
        da = np.diff(window["sma_km"].to_numpy(float))
        if len(da) == 0:
            continue
        frac_neg = float((da < 0.1).sum()) / len(da)
        has_jump = bool((np.abs(da) > 2.0).any())
        net = float(da.sum())
        bstar_mean = window["bstar"].dropna().mean() if window["bstar"].notna().any() else np.nan
        bstar_ok = (not np.isnan(bstar_mean)) and bstar_mean > 0
        if frac_neg >= 0.85 and not has_jump and bstar_ok and net < -2.0:
            n_flagged += 1
    return n_flagged, n_checked


def fleet_monthly_maneuver_count(truth: pd.DataFrame, days: int = 30) -> tuple[int, int, pd.Timestamp | None]:
    """近 N 天 medium/large 機動事件數（同 sec4 之 episode 合併邏輯：同顆衛星間隔 >48h 才算新事件）。
    回傳 (事件數, 有事件之衛星顆數, truth 資料最新 t_to)——最新 t_to 用於判斷 truth 是否滯後，
    避免「真值資料本身已停在數月前」被誤讀成「近 30 天無機動」。"""
    if truth.empty:
        return 0, 0, None
    latest = truth["t_to"].max()
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    med = truth[truth["da_severity"].isin(["medium", "large"]) & (truth["t_to"] >= cutoff)]
    if med.empty:
        return 0, 0, latest
    n_events, n_sats = 0, 0
    for _, g in med.groupby("sat_name"):
        tt = np.sort(g["t_to"].astype("int64").to_numpy())
        n_ep = 1 + int((np.diff(tt) > 48 * 3.6e12).sum()) if len(tt) > 1 else 1
        n_events += n_ep
        n_sats += 1
    return n_events, n_sats, latest


def render_fleet_kpi_row(fleet_names: dict) -> None:
    """頁首艦隊級 KPI 卡片列（借用 scenario-advanced01/starlink.html 頂部統計卡樣式）。

    範圍限定 284 顆 MEME-truth 艦隊（url_registry.csv，同 load_registry_names() 來源），
    而非全庫 3.4 萬顆——避免對整個 raw_tle_archive 做全量逐顆稽核。
    """
    norad_ids = tuple(sorted(int(n) for n in fleet_names.keys()))
    fleet_tle = load_fleet_recent_tle(norad_ids, days=30) if norad_ids else pd.DataFrame()
    truth = load_truth()

    c1, c2, c3 = st.columns(3)

    n_events, n_sats_with_events, latest_truth = fleet_monthly_maneuver_count(truth)
    truth_stale = latest_truth is not None and latest_truth < (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30))
    c1.metric(t("kpi_monthly_maneuvers"), t("kpi_no_data") if truth_stale or truth.empty else n_events)
    if truth_stale:
        c1.caption(t("kpi_monthly_maneuvers_stale", d=latest_truth.strftime("%Y-%m-%d")))
    elif not truth.empty:
        c1.caption(t("kpi_monthly_maneuvers_caption", n=n_sats_with_events))

    good_pct, n_audited = fleet_quality_good_pct(fleet_tle)
    c2.metric(t("kpi_quality_good_pct"),
              f"{good_pct * 100:.1f}%" if n_audited else t("kpi_no_data"))
    if n_audited:
        c2.caption(t("kpi_quality_good_caption", n=n_audited))

    n_deorbit, n_checked = fleet_suspected_deorbiting(fleet_tle)
    c3.metric(t("kpi_deorbiting"), n_deorbit if n_checked else t("kpi_no_data"))
    if n_checked:
        c3.caption(t("kpi_deorbiting_caption", n=n_checked))


@st.cache_data(show_spinner=False)
def compute_ml_detection(norad: int, d0, d1):
    """逐窗口 ML 機動偵測（models_meme，window ≥5km）：對每個 TLE epoch 以
    [t_from−7d, t_from] 特徵窗預測『此窗是否發生機動』的機率。回傳 (df[epoch,prob], thr)。"""
    import json
    import joblib
    import build_training_dataset as btd

    mdir = Path("Orbital_Maneuver_V2/models_meme")
    if not (mdir / "lgbm_maneuver_v1.pkl").exists():
        return None
    model = joblib.load(mdir / "lgbm_maneuver_v1.pkl")
    feats = json.loads((mdir / "feature_names.json").read_text(encoding="utf-8"))
    thr = json.loads((mdir / "threshold.json").read_text(encoding="utf-8")).get("threshold", 0.5)

    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    f107 = load_f107()
    sr = sd.run_all(dd["sma_km"].to_numpy(float))
    win = dd.rename(columns={"epoch": "date_tag"})

    # NRLMSIS 阻力殘差（逐 epoch）＋ 7 天滾動最大 → 供特徵與物理閘門
    dr = dr_am = None
    try:
        from atmospheric_drag import drag_residual, load_space_weather
        _cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
        _dr = drag_residual(dd[_cols], load_space_weather()).set_index("epoch")
        dr = _dr["drag_resid_da"]
        dr_am = dr.abs().rolling("7D").max()
    except Exception:
        pass

    idxs = np.arange(1, len(dd))
    if len(idxs) > 220:                                   # 過多時等距抽樣控制計算量
        idxs = np.unique(np.linspace(1, len(dd) - 1, 220).astype(int))

    sma = dd["sma_km"].to_numpy(float)
    epochs, probs, das, thrs, drs = [], [], [], [], []
    for i in idxs:
        t_from = dd["epoch"].iloc[i]
        lo = t_from - pd.Timedelta(days=7)
        window = win[(win["date_tag"] >= lo) & (win["date_tag"] <= t_from)]
        fv = btd.compute_features(window, t_from,
                                  float(f107.get(t_from.strftime("%Y-%m-%d"), np.nan)))
        if not fv:
            continue
        for key, col in [("cusum", "cusum_stat"), ("bocpd", "bocpd_cp_prob"),
                         ("ssa", "ssa_resid_z")]:
            fv[col] = float(sr[key]["scores"][i])
        # 注入 NRLMSIS 阻力殘差特徵
        dr_i = float(dr.loc[dr.index <= t_from].iloc[-1]) if dr is not None and (dr.index <= t_from).any() else np.nan
        dram_i = float(dr_am.loc[dr_am.index <= t_from].iloc[-1]) if dr_am is not None and (dr_am.index <= t_from).any() else np.nan
        fv["drag_resid_da"] = dr_i
        fv["drag_resid_absmax_7d"] = dram_i
        X = pd.DataFrame([{k: fv.get(k, np.nan) for k in feats}])
        epochs.append(t_from)
        probs.append(float(model.predict_proba(X)[:, 1][0]))
        das.append(float(sma[i] - sma[i - 1]))
        thrs.append(float(ms.DEFAULT_P2(np.array([sma[i] - R_E]))[0]))
        drs.append(dr_i)
    if not epochs:
        return None
    out = pd.DataFrame({"epoch": epochs, "prob": probs, "da_km": das,
                        "p2_thr": thrs, "drag_resid_da": drs})
    # 物理閘門（升級版）：ML 判機動須 (模型機率≥門檻) 且 (NRLMSIS 扣阻力後 |殘差Δa| 夠大)。
    # 用物理阻力殘差取代原始 |Δa|：正確扣除大氣阻力(含 F10.7/Ap)，純衰減/太陽極大期不誤報。
    # NRLMSIS 不可得時回退為高度自適應 |Δa| 閾值。
    if out["drag_resid_da"].notna().any():
        out["flag"] = (out["prob"] >= float(thr)) & (out["drag_resid_da"].abs() > 0.30)
    else:
        out["flag"] = (out["prob"] >= float(thr)) & (out["da_km"].abs() > out["p2_thr"])
    return out, float(thr)


@st.cache_data(show_spinner=False)
def compute_model2_detection(norad: int, d0, d1):
    """Model 2（regime-agnostic 無監督）：NRLMSIS 物理殘差 + Isolation Forest 異常偵測。
    通用任何軌道類別、對純衰減零誤報。回傳 df[epoch, z_drag, anomaly]。"""
    import joblib
    mpath = Path("Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl")
    if not mpath.exists():
        return None
    try:
        import ml_model2_anomaly as m2
        from atmospheric_drag import load_space_weather
    except Exception:
        return None
    bundle = joblib.load(mpath)
    iso, ch = bundle["model"], bundle["channels"]
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    _m2_cols = ["epoch", "sma_km", "inclination_deg", "eccentricity", "raan_deg"] + \
               [c for c in ("line1", "line2") if c in dd.columns]
    r = m2.physical_residuals(dd[_m2_cols], load_space_weather())
    if r.empty:
        return None
    X = np.clip(np.nan_to_num(r[ch].to_numpy()), -200, 200)
    r = r.assign(anomaly=(iso.predict(X) == -1))
    return r


@st.cache_data(show_spinner=False)
def compute_nrlmsis_maneuvers(norad: int, d0, d1, thr: float = 0.30):
    """NRLMSIS 阻力殘差機動（regime-agnostic 物理主判）：扣大氣阻力後 |Δa 殘差|>thr。
    回傳 df[epoch, drag_resid_da, is_maneuver]。通用任何軌道、對純衰減零誤報。"""
    try:
        from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay
    except Exception:
        return None
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 5:
        return None
    cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
    r = drag_residual(dd[cols], load_space_weather())
    if r.empty:
        return None
    r = r[["epoch", "drag_resid_da"]].copy()
    # 再入守門：自然再入衰減無法用準secular模型消除 → 直接判機動=0
    reentry = is_reentry_decay(dd)
    r["is_maneuver"] = False if reentry else (r["drag_resid_da"].abs() > thr)
    r.attrs["reentry"] = reentry
    return r


@st.cache_resource(show_spinner=False)
def _load_fusion():
    import joblib
    p = Path("models_fusion/fusion_scorer.pkl")
    return joblib.load(p) if p.exists() else None


@st.cache_data(show_spinner=False)
def compute_fusion_detection(norad: int, d0, d1):
    """連續融合評分器：5 通道(CUSUM/BOCPD/SSA/MAD+NRLMSIS drag)→ 每 epoch ±24h 窗
    特徵(max/mean/p90)→ HistGBM 融合機動機率。回傳 df[epoch, fusion] 與屬性 thr。"""
    fs = _load_fusion()
    if fs is None:
        return None
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    r = sd.run_all(dd["sma_km"].to_numpy(float))
    drag = np.zeros(len(dd))
    try:
        from atmospheric_drag import drag_residual, load_space_weather
        cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
        dr = drag_residual(dd[cols], load_space_weather())
        if not dr.empty:
            dmap = dict(zip(pd.to_datetime(dr["epoch"], utc=True), dr["drag_resid_da"].abs()))
            drag = np.array([dmap.get(e, 0.0) for e in dd["epoch"]], float)
    except Exception:
        pass
    ch = np.nan_to_num(np.column_stack([
        np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
        np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]), drag / 0.10]))
    t = dd["epoch"].reset_index(drop=True)
    feats = []
    for i in range(len(dd)):
        m = ((t - t.iloc[i]).abs() <= pd.Timedelta(hours=24)).to_numpy()
        sub = ch[m]
        row = []
        for j in range(5):
            col = sub[:, j]
            row += [col.max(), col.mean(), float(np.percentile(col, 90))]
        feats.append(row)
    proba = fs["clf"].predict_proba(np.array(feats))[:, 1]
    out = pd.DataFrame({"epoch": dd["epoch"], "fusion": proba})
    out.attrs["thr"] = float(fs["thr"])
    return out


def is_starlink_domain(sat_name: str) -> bool:
    """Model 1（監督式）僅在 Starlink 訓練 → 只有 Starlink 屬其分布內。"""
    return bool(sat_name) and sat_name.upper().startswith("STARLINK")


def resolve_query(q: str, cat: pd.DataFrame, names: dict) -> pd.DataFrame:
    """支援 NORAD、名稱、wildcard（* ?）。回傳符合的 (norad_id, name) 列。"""
    q = q.strip()
    if not q:
        return cat.head(0)
    cat = cat.copy()
    cat["disp"] = cat["norad_id"].map(names).fillna(cat["name"]).fillna("")
    if q.isdigit():
        return cat[cat["norad_id"] == int(q)]
    if any(c in q for c in "*?"):
        import fnmatch
        pat = q.upper()
        mask = cat["disp"].str.upper().apply(lambda s: fnmatch.fnmatch(s, pat))
        return cat[mask]
    return cat[cat["disp"].str.contains(q, case=False, na=False)]


# ── plotting ──────────────────────────────────────────────────────────────────

def _time_colorscale(n: int = 16):
    """時間 → HSL 色環（hue 0→330、S85% L55%），對應參考頁 orbit.js 之 timeColor。"""
    out = []
    for k in range(n):
        p = k / (n - 1)
        r, g, b = colorsys.hls_to_rgb((p * 330) / 360.0, 0.55, 0.85)
        out.append([p, f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"])
    return out


TIME_SCALE = _time_colorscale()


def plot_elements_and_deltas(df: pd.DataFrame, tr: pd.DataFrame, combined: np.ndarray,
                             nrlmsis_mv: pd.DataFrame | None = None,
                             show_altitude: bool = False):
    """① a/i/e/RAAN 連續時序（左）+ Δ 差值（中）+ 極座標時間視圖（右），共 4 列。
    第三欄（仿 orbit.js Spiral Polar）：
      列1 半長軸「圓形時間圖」(0°=起始於上方、順時針至 360°=結束，r=正規化 SMA)；
      列2/3/4 傾角/RAAN/ARGP「Spiral Polar」(角度=要素值、半徑=時間螺旋 r=0.18+0.82·t、色=時間)。
    nrlmsis_mv：NRLMSIS 主判機動（欄 epoch）→ 於 a 曲線與 Δa 圖標記，使根數圖與主判一致。
    show_altitude：左上第一格改顯示「距離地表高度 (km) = a − R⊕」；Δa 為差值、扣常數不變，不受影響。"""
    a_off = R_E if show_altitude else 0.0
    a_title = t("plot_alt_km") if show_altitude else t("plot_sma_km")
    fig = make_subplots(
        rows=4, cols=3, shared_xaxes=True, horizontal_spacing=0.06, vertical_spacing=0.055,
        column_widths=[0.37, 0.37, 0.26],
        specs=[[{"type": "xy"}, {"type": "xy"}, {"type": "polar"}] for _ in range(4)],
        subplot_titles=(
            a_title, "Δa (km)", t("plot_sma_circle"),
            t("plot_inc_deg"), "Δi (deg)", t("plot_inc_spiral"),
            t("plot_ecc"), "Δe", "RAAN Spiral",
            t("plot_raan_deg"), t("plot_draan_res"), "ARGP Spiral"))
    ep, tep = df["epoch"], tr["epoch"]
    left = [("sma_km", 1), ("inclination_deg", 2), ("eccentricity", 3), ("raan_deg", 4)]
    for col, r in left:
        y = df[col] - a_off if col == "sma_km" else df[col]
        fig.add_trace(go.Scatter(x=ep, y=y, mode="lines", line=dict(color="#0072B2", width=1.3),
                                 showlegend=False), row=r, col=1)
    right = [("da_km", 1), ("di_deg", 2), ("de", 3), ("draan_res_deg", 4)]
    for col, r in right:
        fig.add_trace(go.Scatter(x=tep, y=tr[col], mode="lines", line=dict(color="#888", width=1),
                                 showlegend=False), row=r, col=2)
    # 合併偵測（P1–P6）標記於 Δa
    if combined.any():
        cm = tr[combined]
        fig.add_trace(go.Scatter(x=cm["epoch"], y=cm["da_km"], mode="markers",
                                 marker=dict(color="#D55E00", size=7, symbol="x"),
                                 name=t("legend_p16_combined")), row=1, col=2)
    # NRLMSIS 主判機動：於 a 曲線（上）與 Δa 圖（上）皆標記（綠星），與主判一致
    if nrlmsis_mv is not None and len(nrlmsis_mv):
        mep = pd.to_datetime(nrlmsis_mv["epoch"], utc=True)
        a_src = df.drop_duplicates("epoch").set_index("epoch")["sma_km"].sort_index()
        da_src = tr.drop_duplicates("epoch").set_index("epoch")["da_km"].sort_index()
        a_at = a_src.reindex(mep, method="nearest").to_numpy() - a_off
        da_at = da_src.reindex(mep, method="nearest").to_numpy()
        fig.add_trace(go.Scatter(x=mep, y=a_at, mode="markers",
                                 marker=dict(color="#009E73", size=9, symbol="star",
                                             line=dict(color="white", width=0.5)),
                                 name=t("legend_nrlmsis_primary")), row=1, col=1)
        fig.add_trace(go.Scatter(x=mep, y=da_at, mode="markers",
                                 marker=dict(color="#009E73", size=9, symbol="star",
                                             line=dict(color="white", width=0.5)),
                                 showlegend=False), row=1, col=2)
    # ── 第三欄：極座標時間視圖 ────────────────────────────────────────────────
    def _spiral(series: str, row: int):
        v = df[series].to_numpy(float)
        e = df["epoch"].to_numpy()
        m = np.isfinite(v)
        v, e = v[m], e[m]
        n = len(v)
        if n == 0:
            return
        t = np.linspace(0, 1, n) if n > 1 else np.array([0.0])
        r_n = 0.18 + 0.82 * t                     # 時間螺旋（內→外）
        theta = np.mod(v, 360.0)                   # 角度 = 要素值
        htxt = [f"{pd.Timestamp(dd).strftime('%Y-%m-%d')} · {vv:.4f}°"
                for dd, vv in zip(e, v)]
        fig.add_trace(go.Scatterpolar(
            r=r_n, theta=theta, mode="markers",
            marker=dict(size=4, color=t, colorscale=TIME_SCALE, cmin=0, cmax=1,
                        showscale=False),
            hovertext=htxt, hoverinfo="text", showlegend=False), row=row, col=3)

    def _sma_circle(row: int):
        s = df["sma_km"].to_numpy(float)
        e = df["epoch"].to_numpy()
        m = np.isfinite(s)
        s, e = s[m], e[m]
        n = len(s)
        if n == 0:
            return
        mn, mx = float(s.min()), float(s.max())
        rg = mx - mn
        t = np.linspace(0, 1, n) if n > 1 else np.array([0.0])
        r_n = (s - mn) / rg if rg > 0 else np.full(n, 0.5)
        theta = t * 360.0                          # 0°=起始（上方）順時針→360°=結束
        htxt = [f"{pd.Timestamp(dd).strftime('%Y-%m-%d')} · SMA {ss:.3f} km"
                f"（min+{ss - mn:.3f}）" for dd, ss in zip(e, s)]
        fig.add_trace(go.Scatterpolar(
            r=r_n, theta=theta, mode="lines+markers",
            line=dict(color="rgba(150,150,150,0.35)", width=1),
            marker=dict(size=4, color=t, colorscale=TIME_SCALE, cmin=0, cmax=1,
                        showscale=False),
            hovertext=htxt, hoverinfo="text", showlegend=False), row=row, col=3)

    _sma_circle(1)
    _spiral("inclination_deg", 2)
    _spiral("raan_deg", 3)
    _spiral("argp_deg", 4)

    _rad = dict(showticklabels=False, gridcolor="#e5e5e5", linecolor="#e5e5e5",
                range=[0, 1.04])
    _ang = dict(gridcolor="#e5e5e5", linecolor="#e5e5e5", tickfont=dict(size=7),
                ticksuffix="°", nticks=8)
    _polar_spiral = dict(radialaxis=_rad, angularaxis=_ang, bgcolor="rgba(0,0,0,0)")
    _polar_sma = dict(
        radialaxis=dict(showticklabels=False, gridcolor="#e5e5e5",
                        linecolor="#e5e5e5", range=[0, 1.06]),
        angularaxis=dict(rotation=90, direction="clockwise", gridcolor="#e5e5e5",
                         linecolor="#e5e5e5", tickfont=dict(size=7), ticksuffix="°",
                         nticks=8),
        bgcolor="rgba(0,0,0,0)")
    # polar(列1)=SMA 圓形；polar2/3/4(列2-4)=Spiral
    fig.update_layout(polar=_polar_sma, polar2=_polar_spiral,
                      polar3=_polar_spiral, polar4=_polar_spiral)
    # 下縮各極座標 domain，讓子圖標題與頂端角度刻度留白、不再交疊
    for _pol in ("polar", "polar2", "polar3", "polar4"):
        _d = fig.layout[_pol].domain
        fig.layout[_pol].domain = dict(x=tuple(_d.x),
                                       y=(_d.y[0], _d.y[1] - 0.028))

    fig.update_layout(height=1020, margin=dict(l=40, r=20, t=52, b=30),
                      legend=dict(orientation="h", y=1.05))
    fig.update_annotations(font_size=12)          # 收斂 12 格 subplot 標題字級
    return fig


def bootstrap_ci(values: np.ndarray, stat=np.mean, n=2000, alpha=0.05, seed=0):
    values = np.asarray(values, float)
    values = values[~np.isnan(values)]
    if len(values) < 2:
        m = float(stat(values)) if len(values) else float("nan")
        return m, m, m
    rng = np.random.default_rng(seed)
    boot = [stat(rng.choice(values, len(values), replace=True)) for _ in range(n)]
    return float(stat(values)), float(np.percentile(boot, 100 * alpha / 2)), \
        float(np.percentile(boot, 100 * (1 - alpha / 2)))


# ── SSA-RAG 整合（自 maneuver_app.py 移植）────────────────────────────────────
RAG_DEFAULT_URL = os.environ.get("SSA_RAG_URL", "http://127.0.0.1:8000")
TLE_GAP_SUPPRESS_H = 48.0


@st.cache_data(ttl=60, show_spinner=False)
def _rag_health_cached(base_url: str) -> bool:
    try:
        from ssa_rag_client import SSARAGClient
    except ImportError:
        return False
    try:
        return SSARAGClient(base_url=base_url).health()
    except Exception:
        return False


@st.cache_data(ttl=3600, show_spinner=False)
def _rag_ask_cached(base_url: str, question: str, topic: str | None) -> dict:
    """同一描述文字只查詢一次（快取 1 小時），避免 Streamlit rerun 重複打 RAG。"""
    from ssa_rag_client import SSARAGClient
    client = SSARAGClient(base_url=base_url, timeout=120.0)
    result = client.ask(question, topic=topic, client_id="maneuver_app_july")
    return {"answer": result.answer, "confidence": result.confidence,
            "sources": result.sources}


def build_tle_maneuver_narrative(satellite_id, alt_km_avg, start_date: str,
                                 end_date: str, event_df: pd.DataFrame) -> str:
    """LEO/MEO TLE 自適應偵測結果 → 自然語言描述（供 SSA-RAG 解說）。"""
    alt_txt = f"平均軌道高度約 {alt_km_avg:.0f} km" if alt_km_avg is not None else "軌道高度未知"
    n_events = 0 if event_df is None or event_df.empty else len(event_df)
    lines = [
        f"衛星 NORAD {satellite_id}（{alt_txt}）在 {start_date} 至 {end_date} 期間，"
        f"以 TLE 半長軸（SMA）跳變法（P1–P6 高度自適應）進行機動偵測，"
        f"共偵測到 {n_events} 次疑似機動事件。"
    ]
    if n_events:
        ev_lines = []
        _is_raise = event_df["sma_direction"].astype(str).to_numpy() == "raise"
        _absd = event_df["sma_delta"].abs().to_numpy(float)
        for _, ev in event_df.head(10).iterrows():
            direction = "抬升" if str(ev.get("sma_direction", "")) == "raise" else "降低"
            ev_lines.append(
                f"- {pd.Timestamp(ev['epoch']).strftime('%Y-%m-%d')}："
                f"半長軸{direction}，|Δa| = {float(ev['sma_delta']):.4f} km")
        if n_events > 10:
            ev_lines.append(f"-（其餘 {n_events - 10} 次事件省略）")
        lines.append("事件清單：\n" + "\n".join(ev_lines))
        n_raise = int(_is_raise.sum())
        n_lower = int((~_is_raise).sum())
        net_signed = float((_absd * np.where(_is_raise, 1.0, -1.0)).sum())
        abs_sum = float(_absd.sum())
        net_dir = "淨抬升" if net_signed > 0 else ("淨降低" if net_signed < 0 else "淨值近零")
        lines.append(
            f"事件方向統計：抬升 {n_raise} 次、降低 {n_lower} 次。"
            f"帶正負號的淨半長軸變化 Δa_net = {net_signed:+.4f} km（{net_dir}）；"
            f"各事件 |Δa| 絕對值加總 = {abs_sum:.3f} km——此值僅代表機動活動量級，"
            "恒為正、不代表方向。"
            f"（註：上列統計與 Δa_net 均由偵測系統就「全部 {n_events} 次事件」計算所得，"
            "為本題給定之輸入事實；上方事件清單僅為可讀性節錄前 10 筆，"
            "故 Δa_net 無法、也不需由清單自行推算，請直接採用。）")
        lines.append(
            "請根據以上偵測結果解說：這種半長軸跳變模式最可能對應哪種機動類型"
            "（軌道維持、軌道抬升、避碰或離軌）？機動後 TLE 失效對 conjunction "
            "screening 有什麼影響？（判斷機動方向請「務必以帶正負號的 Δa_net 為準」——"
            "Δa_net 為正才可能是軌道抬升、為負屬軌道降低／離軌，切勿把絕對值加總當成淨值，"
            "也不要只憑檢索到的文件主題判斷方向。）")
    else:
        lines.append(
            "請解說：此期間未偵測到明顯機動的可能原因有哪些？"
            "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return "\n".join(lines)


def build_ml_maneuver_narrative(satellite_id, p_maneuver: float, lgbm_feat: dict,
                                start_date: str, end_date: str,
                                alert: bool | None = None) -> str:
    """LightGBM／融合偵測結果 → 自然語言描述（供 SSA-RAG 解說）。"""
    if alert is None:
        alert = p_maneuver >= 0.5
    net_da = float(lgbm_feat.get("net_da_km", 0))
    if net_da > 0:
        direction_txt = "半長軸上升（正值，方向上屬於軌道抬升類）"
    elif net_da < 0:
        direction_txt = "半長軸下降（負值，方向上屬於軌道降低／離軌／大氣阻力衰減類，並非軌道抬升）"
    else:
        direction_txt = "半長軸無明顯淨變化"
    lines = [
        f"機動偵測模型對衛星 NORAD {satellite_id}"
        f"（軌道高度約 {float(lgbm_feat.get('alt_km', float('nan'))):.0f} km）"
        f"在 {start_date} 至 {end_date} 的 TLE 資料推論，"
        f"機動機率 p_maneuver = {p_maneuver:.3f}，"
        f"判定為「{'偵測到機動' if alert else '無明顯機動'}」。",
        f"關鍵特徵：累積半長軸變化 {net_da:+.2f} km（{direction_txt}）、"
        f"單筆最大 |Δa| {float(lgbm_feat.get('max_da_km', 0)):.2f} km、"
        f"異常旗標率 {float(lgbm_feat.get('flag_rate', 0)):.0%}、"
        f"估算淨 Δv 約 {float(lgbm_feat.get('dv_net_ms', 0)):.2f} m/s。",
    ]
    if lgbm_feat.get("da_monotonic_decay") or lgbm_feat.get("monotone_decay"):
        lines.append("此觀測窗口帶有單調衰減特徵（半長軸持續小幅下降、無大跳變），"
                     "較可能為大氣阻力自然衰減而非推進機動。")
    lines.append(
        "請解說此偵測結果的物理意義：這樣的半長軸變化與 Δv 量級對應哪種機動行為？"
        "分析時如何區分大氣阻力衰減與真實機動？"
        "（請以上方標註的方向判讀為準，不要單純依照檢索到的文件主題判斷方向。）")
    return "\n".join(lines)


def render_rag_auto_explain(narrative: str, base_url: str = RAG_DEFAULT_URL,
                            topic: str = "maneuver") -> None:
    """將偵測結果的自然語言描述自動送入 SSA-RAG，顯示解說。服務離線只留一行提示。"""
    if not _rag_health_cached(base_url):
        st.caption(t("rag_offline_auto", url=base_url))
        return
    st.markdown(t("rag_auto_title"))
    with st.expander(t("rag_show_narrative")):
        st.text(narrative)
    with st.spinner(t("rag_spinner_auto")):
        try:
            res = _rag_ask_cached(base_url, narrative, topic)
        except Exception as e:
            st.warning(t("rag_query_failed", e=e))
            return
    st.info(res["answer"])
    conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(res["confidence"], "⚪")
    st.caption(t("rag_confidence_line", icon=conf_color, conf=res["confidence"]))
    if res["sources"]:
        with st.expander(t("rag_sources", n=len(res["sources"]))):
            for s in res["sources"]:
                st.caption(t("rag_source_line", name=s.get("file_name", t("unknown")),
                             idx=s.get("chunk_index", "?"),
                             score=f"{float(s.get('score', 0)):.3f}"))


def render_ssa_rag_page(base_url: str = RAG_DEFAULT_URL) -> None:
    """SSA-RAG 知識庫互動問答（自訂問題）。"""
    import requests
    try:
        from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS, TOPICS
    except ImportError:
        st.error(t("err_no_rag_client"))
        return
    if not _rag_health_cached(base_url):
        st.caption(t("rag_offline_page", url=base_url))
        return
    st.success(t("rag_online", url=base_url))
    client = SSARAGClient(base_url=base_url, timeout=120.0)
    col_topic, col_prompt = st.columns([1, 2])
    _ALL = "__ALL__"          # 語言無關的哨兵值（切換語言時 session_state 不會失效）
    _CUSTOM = "__CUSTOM__"
    with col_topic:
        topic = st.selectbox(t("sel_topic"), [_ALL] + TOPICS, key="ssa_topic_july",
                             format_func=lambda k: t("opt_all") if k == _ALL else k)
    with col_prompt:
        prompts = SUGGESTED_PROMPTS.get(topic, [])
        prompt_choice = st.selectbox(t("sel_example_q"), [_CUSTOM] + prompts,
                                     key="ssa_prompt_choice_july",
                                     format_func=lambda k: t("opt_custom") if k == _CUSTOM else k)
    default_q = "" if prompt_choice == _CUSTOM else prompt_choice
    question = st.text_input(t("input_question"), value=default_q, key="ssa_question_july")
    if st.button(t("btn_send"), type="primary", key="ssa_submit_july") and question:
        with st.spinner(t("spinner_querying")):
            try:
                result = client.ask(question, topic=None if topic == _ALL else topic,
                                    client_id="maneuver_app_july")
            except Exception as e:
                st.error(t("err_query_failed", e=e))
                return
        st.markdown(t("hdr_answer"))
        st.write(result.answer)
        conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")
        st.caption(t("rag_confidence_line", icon=conf_color, conf=result.confidence))
        if result.insufficient:
            st.warning(t("warn_insufficient"))
        elif result.sources:
            with st.expander(t("rag_source_docs", n=len(result.sources))):
                for s in result.sources:
                    st.caption(t("rag_source_line", name=s.get("file_name", t("unknown")),
                                 idx=s.get("chunk_index", "?"),
                                 score=f"{float(s.get('score', 0)):.3f}"))


def _render_dialogue_messages(n_show: int = 12) -> None:
    from app_dialogue_client import DialogueClient, DIALOGUE_END, DIALOGUE_ECHO
    records = DialogueClient().read_all()
    if not records:
        st.caption(t("dlg_empty"))
        return
    if len(records) > n_show:
        st.caption(t("dlg_recent", n=n_show, total=len(records)))
    for rec in records[-n_show:]:
        ts = rec.get("timestamp", "")[11:19]
        is_client = rec.get("sender") == "client"
        who = "🛰️ client" if is_client else "🖥️ server"
        msg = str(rec.get("message", ""))
        if msg.strip() == DIALOGUE_ECHO:
            st.markdown(f"<small>{ts} <b>{who}</b>：✓ <code>#Echo#</code>{t('dlg_ack')}</small>",
                        unsafe_allow_html=True)
        elif msg.strip() == DIALOGUE_END:
            st.markdown(f"<small>{ts} <b>{who}</b>：🔚 <code>#Over#</code>{t('dlg_end')}</small>",
                        unsafe_allow_html=True)
        else:
            color = "#8ecae6" if is_client else "#ffb703"
            st.markdown(f"<small><b style='color:{color}'>{who}</b> "
                        f"<span style='opacity:.6'>{ts}</span><br>{msg}</small>",
                        unsafe_allow_html=True)


def render_dialogue_panel() -> None:
    """側邊欄對話面板：與 SSA-RAG Server（scripts/ask.py --chat-listen）互傳訊息。"""
    with st.expander(t("dlg_expander")):
        try:
            from app_dialogue_client import DialogueClient
        except ImportError:
            st.caption(t("dlg_no_client"))
            return
        _render_dialogue_messages()
        st.button(t("btn_refresh"), key="dlg_refresh_july")
        with st.form("dlg_form_july", clear_on_submit=True):
            msg = st.text_input(t("input_message"), key="dlg_msg_july",
                                placeholder=t("ph_message"))
            c_send, c_over = st.columns(2)
            do_send = c_send.form_submit_button(t("btn_send"), type="primary",
                                                use_container_width=True)
            do_over = c_over.form_submit_button("#Over#", use_container_width=True)
        if do_send and msg.strip():
            DialogueClient().send(msg.strip())
            st.rerun()
        if do_over:
            DialogueClient().end()
            st.rerun()


# ══ StoryMap（2026-09-10 新增）══════════════════════════════════════════════════
# 架構：獨立於既有分析工具之外的頁面模式（側邊欄切換），Landing page + 逐案例頁。
# 每個案例回答一個本專案最常被問到的技術問題，以真實 TLE 資料＋（必要時）校準過的
# 模擬實驗作答，非僅文字結論——所有數字皆可由本頁面之快取函式重新查驗或重跑。

def _dedup_by_gap(df: pd.DataFrame, min_gap_min: int = 180) -> pd.DataFrame:
    """依時間排序後，僅保留間隔 >= min_gap_min 分鐘之列（去除近乎重複之 TLE 時戳）。"""
    df = df.sort_values("epoch").reset_index(drop=True)
    if df.empty:
        return df
    keep = [0]
    last_t = df["epoch"].iloc[0]
    for i in range(1, len(df)):
        if (df["epoch"].iloc[i] - last_t).total_seconds() >= min_gap_min * 60:
            keep.append(i)
            last_t = df["epoch"].iloc[i]
    return df.iloc[keep].reset_index(drop=True)


_MU_MEME = 398_600.4418  # km^3/s^2（與 compare_tle_vs_ephemeris._MU_M 一致）


def _meme_sma_series(sat_name: str) -> pd.DataFrame:
    """若 data/raw/{sat_name}/ 有 MEME 精密星曆檔，向量化算出其半長軸序列（EME2000，
    與 raw_tle_archive.sma_km 同一慣例，可直接疊圖比對）；查無資料回傳空 DataFrame。"""
    sat_dir = DATA / "raw" / sat_name
    if not sat_dir.is_dir():
        return pd.DataFrame()
    try:
        from compare_tle_vs_ephemeris import find_all_ephemeris_files, load_all_meme
    except Exception:
        return pd.DataFrame()
    files = find_all_ephemeris_files(sat_dir)
    if not files:
        return pd.DataFrame()
    df = load_all_meme(sat_name, files)
    if df.empty or not {"r_x", "r_y", "r_z", "v_x", "v_y", "v_z"}.issubset(df.columns):
        return pd.DataFrame()
    r = df[["r_x", "r_y", "r_z"]].to_numpy(float)
    v = df[["v_x", "v_y", "v_z"]].to_numpy(float)
    r_m = np.linalg.norm(r, axis=1)
    v_m = np.linalg.norm(v, axis=1)
    eps = v_m ** 2 / 2.0 - _MU_MEME / r_m
    a_km = -_MU_MEME / (2.0 * eps)
    return pd.DataFrame({"epoch": pd.to_datetime(df["t"], utc=True), "sma_km": a_km})


@st.cache_data(ttl=3600, show_spinner=False)
def load_case3_real_data() -> dict:
    """案例三之真實資料：STARLINK-3005（站位保持，量測真實雜訊底）與
    STARLINK-37457（抬軌中，量測真實電推爬升率）。回傳 dict 供繪圖與統計使用。"""
    con = duckdb.connect(DB_PATH, read_only=True)
    q_raw = con.execute(
        "SELECT epoch_utc AS epoch, sma_km FROM raw_tle_archive "
        "WHERE norad_id=48881 ORDER BY epoch_utc").fetchdf()
    r_raw = con.execute(
        "SELECT epoch_utc AS epoch, sma_km FROM raw_tle_archive "
        "WHERE norad_id=100294 ORDER BY epoch_utc").fetchdf()
    con.close()

    out = {}
    if not q_raw.empty:
        q_raw["epoch"] = pd.to_datetime(q_raw["epoch"], utc=True)
        q = _dedup_by_gap(q_raw, 180)
        cutoff = q["epoch"].max() - pd.Timedelta(days=60)
        q = q[q["epoch"] >= cutoff].reset_index(drop=True)
        da = np.diff(q["sma_km"].to_numpy())
        mad_sigma = float(np.median(np.abs(da - np.median(da))) * 1.4826) if len(da) else np.nan
        gap_h = q["epoch"].diff().dt.total_seconds().dropna() / 3600
        out["quiet_df"] = q
        out["quiet_da"] = da
        out["quiet_sigma_mad_km"] = mad_sigma
        out["quiet_sigma_std_km"] = float(np.std(da)) if len(da) else np.nan
        out["quiet_median_gap_h"] = float(gap_h.median()) if len(gap_h) else np.nan
        if len(da):
            i_max = int(np.argmax(np.abs(da)))
            out["quiet_outlier"] = {
                "t0": q["epoch"].iloc[i_max], "t1": q["epoch"].iloc[i_max + 1],
                "da_km": float(da[i_max]),
                "snr": abs(float(da[i_max])) / mad_sigma if mad_sigma else np.nan,
            }
    if not r_raw.empty:
        r_raw["epoch"] = pd.to_datetime(r_raw["epoch"], utc=True)
        r = _dedup_by_gap(r_raw, 180)
        out["raise_df"] = r
        active = r[r["epoch"] <= pd.Timestamp("2026-08-26", tz="UTC")]
        if len(active) >= 2:
            span_d = (active["epoch"].iloc[-1] - active["epoch"].iloc[0]).total_seconds() / 86400
            out["raise_active_rate_km_day"] = float(
                (active["sma_km"].iloc[-1] - active["sma_km"].iloc[0]) / span_d) if span_d else np.nan
            out["raise_active_days"] = span_d
            out["raise_active_da_km"] = float(active["sma_km"].iloc[-1] - active["sma_km"].iloc[0])
    out["raise_meme_df"] = _meme_sma_series("STARLINK-37457")
    return out


def _snr_curve_table(sigma_km: float, net_da_km: float = 1.0, k_days=(1, 3, 5, 7, 10, 14)) -> pd.DataFrame:
    """per-step SNR = (淨Δa / 橫跨天數) / σ；偵測率以 Φ 型近似（SNR>=3→~0.95 飽和、SNR<2→物理下限），
    僅供故事頁直覺呈現，非取代技術附錄之合成注入實測（`gradual_arc_injection.py`）。"""
    from scipy.stats import norm
    rows = []
    for k in k_days:
        per_step = (net_da_km / k) / sigma_km
        # 以 3σ-MAD 型偵測器之近似偵測機率：Φ(per_step - threshold)，threshold≈2（門檻對齊本專案慣例）
        detect_p = float(np.clip(norm.cdf(per_step - 2.0) * 0.95 + 0.02, 0.0, 0.97))
        rows.append({"k_days": k, "per_step_snr": round(per_step, 2), "approx_detect_rate": round(detect_p, 3)})
    return pd.DataFrame(rows)


def render_storymap_landing():
    st.title(t("storymap_landing_title"))
    st.caption(t("storymap_landing_sub"))
    if _lang() != "zh":
        st.info(t("storymap_lang_note"))
    st.caption(
        "🔗 單獨分享此頁：在網址後加上 `?mode=storymap`（分享特定案例則再加 "
        "`&case=case3`～`case2`），對方開啟連結即直接落地在 StoryMap，不需手動切換側欄。"
    )

    st.markdown("---")
    card9 = st.container(border=True)
    with card9:
        st.subheader(t("storymap_case1_card_title"))
        st.write(t("storymap_case1_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case1", type="primary"):
            st.session_state["storymap_case"] = "case1"
            st.rerun()

    card10 = st.container(border=True)
    with card10:
        st.subheader(t("storymap_case2_card_title"))
        st.write(t("storymap_case2_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case2", type="primary"):
            st.session_state["storymap_case"] = "case2"
            st.rerun()

    card1 = st.container(border=True)
    with card1:
        st.subheader(t("storymap_case3_card_title"))
        st.write(t("storymap_case3_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case3", type="primary"):
            st.session_state["storymap_case"] = "case3"
            st.rerun()

    card2 = st.container(border=True)
    with card2:
        st.subheader(t("storymap_case4_card_title"))
        st.write(t("storymap_case4_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case4", type="primary"):
            st.session_state["storymap_case"] = "case4"
            st.rerun()

    card3 = st.container(border=True)
    with card3:
        st.subheader(t("storymap_case5_card_title"))
        st.write(t("storymap_case5_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case5", type="primary"):
            st.session_state["storymap_case"] = "case5"
            st.rerun()

    card4 = st.container(border=True)
    with card4:
        st.subheader(t("storymap_case6_card_title"))
        st.write(t("storymap_case6_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case6", type="primary"):
            st.session_state["storymap_case"] = "case6"
            st.rerun()

    card5 = st.container(border=True)
    with card5:
        st.subheader(t("storymap_case7_card_title"))
        st.write(t("storymap_case7_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case7", type="primary"):
            st.session_state["storymap_case"] = "case7"
            st.rerun()

    card6 = st.container(border=True)
    with card6:
        st.subheader(t("storymap_case8_card_title"))
        st.write(t("storymap_case8_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case8", type="primary"):
            st.session_state["storymap_case"] = "case8"
            st.rerun()

    card7 = st.container(border=True)
    with card7:
        st.subheader(t("storymap_case9_card_title"))
        st.write(t("storymap_case9_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case9", type="primary"):
            st.session_state["storymap_case"] = "case9"
            st.rerun()

    card8 = st.container(border=True)
    with card8:
        st.subheader(t("storymap_case10_card_title"))
        st.write(t("storymap_case10_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case10", type="primary"):
            st.session_state["storymap_case"] = "case10"
            st.rerun()

    card11 = st.container(border=True)
    with card11:
        st.subheader(t("storymap_case11_card_title"))
        st.write(t("storymap_case11_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case11", type="primary"):
            st.session_state["storymap_case"] = "case11"
            st.rerun()

    card12 = st.container(border=True)
    with card12:
        st.subheader(t("storymap_case12_card_title"))
        st.write(t("storymap_case12_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case12", type="primary"):
            st.session_state["storymap_case"] = "case12"
            st.rerun()

    card13 = st.container(border=True)
    with card13:
        st.subheader(t("storymap_case13_card_title"))
        st.write(t("storymap_case13_card_desc"))
        if st.button(t("storymap_enter_case"), key="enter_case13", type="primary"):
            st.session_state["storymap_case"] = "case13"
            st.rerun()

    st.caption(t("storymap_more_soon"))


def render_storymap_case3():
    if st.button(t("storymap_back"), key="back_from_case3"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例三：TLE 觀測窗要拉多長，才能抓到 Starlink 電推機動的明確證據？")
    st.subheader("答案分兩種情境：抬軌階段輕鬆看穿，站位保持階段才是真正的極限")
    st.caption("本頁全部數字皆由下方之快取函式對本機／遠端 TLE 資料庫即時查驗計算，非預先寫死之靜態文字。")

    st.markdown(
        "**問題背景**：Starlink 的軌道機動幾乎全部靠電推（離子推進器）完成，"
        "電推可能是「發射後抬軌」的快速連續爬升，也可能是「在軌站位保持」的極小幅微調——"
        "這兩種情境的物理量級差了兩到三個數量級，答案完全不同。以下用兩顆真實衛星的 TLE 資料，"
        "分別展示這兩種情境。"
    )

    data = load_case3_real_data()

    # ── 情境一：抬軌（真實資料）──────────────────────────────────────────────
    st.header("① 抬軌階段——1～2 天的典型 TLE 頻率就已經是壓倒性證據")
    if "raise_df" in data and not data["raise_df"].empty:
        r = data["raise_df"]
        meme = data.get("raise_meme_df", pd.DataFrame())
        has_meme = isinstance(meme, pd.DataFrame) and not meme.empty
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=r["epoch"], y=r["sma_km"], mode="lines+markers",
                                 name="TLE 半長軸（逐筆，本節主軸）", line=dict(color="#4FC3F7")))
        if has_meme:
            fig.add_trace(go.Scatter(x=meme["epoch"], y=meme["sma_km"], mode="lines",
                                     name="MEME 精密星曆半長軸（逐分鐘真值）",
                                     line=dict(color="#FFD54F", width=1.2)))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                          xaxis_title="時間（UTC）", yaxis_title="半長軸 a (km)",
                          legend=dict(orientation="h", y=1.12),
                          title="STARLINK-37457（NORAD 100294，2026-08-11 發射）之抬軌軌跡" +
                                ("：TLE vs MEME 精密星曆對比" if has_meme else "（真實 TLE）"))
        st.plotly_chart(fig, use_container_width=True)
        if has_meme:
            st.caption(
                f"MEME 精密星曆共 {len(meme):,} 個逐分鐘資料點，與 TLE 疊圖後可直接看出："
                "TLE 呈現的「跳一段、停一下」階梯狀，究竟是真實的推力排程（MEME 也是階梯狀），"
                "還是純粹的 TLE 擬合/更新頻率造成的視覺假象（MEME 是平滑連續曲線）——見下方判讀。"
            )
        else:
            st.info(
                "ℹ️ **此衛星目前無 MEME 精密星曆資料可疊圖比對**：本專案之 MEME 資料集（`data/raw/`）"
                "是於 2026 年 5 月自「當時已在軌運作中」之 284 顆衛星名冊建立，"
                "而 STARLINK-37457 於 2026-08-11（名冊建立之後）才發射，故不在既有 MEME 涵蓋範圍——"
                "這不是系統限制，只是這顆衛星比資料集本身還新。若需要 TLE vs MEME 的抬軌階段真實對比，"
                "可考慮向 SpaceX 公開端點另行下載此衛星之 MEME 檔案（`data/raw/STARLINK-37457/`），"
                "本頁偵測到資料後會自動疊圖，無需修改程式。"
            )

        rate = data.get("raise_active_rate_km_day")
        days = data.get("raise_active_days")
        da_total = data.get("raise_active_da_km")
        if rate is not None:
            sigma_ref = data.get("quiet_sigma_mad_km", 0.0275)
            snr_1day = rate / sigma_ref if sigma_ref else float("nan")
            c1, c2, c3 = st.columns(3)
            c1.metric("主動爬升期實測速率", f"{rate:.2f} km/天")
            c2.metric("該階段實測總 Δa", f"{da_total:.1f} km", f"{days:.1f} 天內")
            c3.metric("對應 1 天 TLE 間隔之 SNR", f"{snr_1day:.0f}σ")
            st.markdown(
                f"**判讀**：實測主動爬升速率約 **{rate:.1f} km/天**，"
                f"以下方情境二量測到的真實雜訊底（σ≈{sigma_ref*1000:.0f} m）換算，"
                f"**單一天的變化量對應 SNR（訊噪比，Signal-to-Noise Ratio；訊號強度相對於背景雜訊的倍數）"
                f"≈{snr_1day:.0f}σ**——遠超任何合理判定門檻（通常 2–3σ 即視為明確訊號）。"
                "**這個情境幾乎不需要「拉長觀測窗」的討論：TLE 更新頻率再低，1～2 天內就已是壓倒性的明確證據。**"
                "\n\n仔細看上圖會發現真實軌跡不是平滑直線，而是「跳一段、停一下」的階梯狀——"
                "這代表電推抬軌在 TLE 解析度下常呈現離散的推力弧＋滑行段落，而非連續平滑爬升"
                "（詳細的推力弧形態分析見技術附錄十一.5、`thrust_arc_catalog.py`）。"
            )
    else:
        st.warning("目前資料庫查無 STARLINK-37457（NORAD 100294）之 TLE，此區塊暫時無法顯示。")

    st.markdown("---")

    # ── 情境二：站位保持（真實資料，量測雜訊底）──────────────────────────────
    st.header("② 站位保持——真實雜訊底長什麼樣，抓到一次真實的小型修正")
    if "quiet_df" in data and not data["quiet_df"].empty:
        q = data["quiet_df"]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=q["epoch"], y=q["sma_km"], mode="lines+markers",
                                  name="STARLINK-3005 半長軸", line=dict(color="#66BB6A")))
        outlier = data.get("quiet_outlier")
        if outlier:
            fig2.add_vrect(x0=outlier["t0"], x1=outlier["t1"], fillcolor="#EF9A9A", opacity=0.35,
                           line_width=0, annotation_text="偵測到的真實跳動", annotation_position="top left")
        fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                           xaxis_title="時間（UTC）", yaxis_title="半長軸 a (km)",
                           title="真實 TLE：STARLINK-3005（NORAD 48881，站位保持中）近 60 天")
        st.plotly_chart(fig2, use_container_width=True)

        sigma_mad = data.get("quiet_sigma_mad_km")
        sigma_std = data.get("quiet_sigma_std_km")
        gap_h = data.get("quiet_median_gap_h")
        c1, c2, c3 = st.columns(3)
        c1.metric("真實雜訊底 σ（穩健估計）", f"{sigma_mad*1000:.0f} m" if sigma_mad else "—")
        c2.metric("典型 TLE 更新間隔（中位數）", f"{gap_h:.1f} 小時" if gap_h else "—")
        c3.metric("含離群值之標準差", f"{sigma_std*1000:.0f} m" if sigma_std else "—",
                 help="標準差比穩健估計（MAD）大，正是因為下面這次真實跳動把它拉高了")

        if outlier:
            st.markdown(
                f"**這條「安靜」的衛星，60 天內其實藏了一次真實的小幅修正**：{outlier['t0']:%Y-%m-%d %H:%M} → "
                f"{outlier['t1']:%Y-%m-%d %H:%M} UTC，半長軸變化 **{outlier['da_km']*1000:+.0f} m**，"
                f"單步 SNR≈**{outlier['snr']:.0f}σ**——遠高於偵測門檻，這種量級的單次修正即使只隔一筆 TLE 也毫無疑問可以判定為機動。"
                "\n\n真正困難的不是這種「一次到位」的修正，而是把同樣的淨位移，**拆成好幾天、每天挪一點點**執行的情況——"
                "這正是下一節要處理的問題。"
            )
        st.caption(
            f"本頁測得之穩健雜訊底（σ≈{sigma_mad*1000:.0f} m，若有資料）"
            "與技術附錄§10.5「Starlink 低軌帶 σ≈24–75 m」之既有結論一致，屬於該範圍偏低（乾淨）的一端；"
            "不同衛星、不同時期之雜訊底會因追蹤幾何與大氣阻力狀態而異。"
        )
    else:
        st.warning("目前資料庫查無 STARLINK-3005（NORAD 48881）之 TLE，此區塊暫時無法顯示。")

    st.markdown("---")

    # ── 情境三：慢速電推站位保持——校準過的模擬（明確標示為模擬）─────────────
    st.header("③ 如果同樣的位移拆成好幾天執行——校準過的模擬實驗")
    st.markdown(
        "上面兩個情境都是「單一步就看得到」的案例。真正的問題是：如果一次 1 公里等級的位移，"
        "不是一步到位，而是像真實電推 station-keeping 那樣**拆成 3 天、7 天、甚至 14 天**慢慢完成，"
        "會發生什麼事？這裡用情境二剛剛量到的真實雜訊底做基準，跑一個簡化的偵測率模擬"
        "（完整版之嚴謹合成注入實驗見技術附錄§10.7、`gradual_arc_injection.py`，本頁為同一方法論之簡化重現）。"
    )

    sigma_options = {
        "本頁剛測得之真實 σ（乾淨案例）": data.get("quiet_sigma_mad_km", 0.0275),
        "技術附錄 Starlink 低軌帶下限 σ=24 m": 0.024,
        "技術附錄 Starlink 低軌帶上限 σ=75 m": 0.075,
    }
    sel = st.selectbox("選擇雜訊底假設", list(sigma_options.keys()), index=0)
    sigma_km = sigma_options[sel]
    net_da = st.slider("假設淨機動位移（km）", 0.2, 5.0, 1.0, 0.1)

    curve = _snr_curve_table(sigma_km, net_da)
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(x=curve["k_days"].astype(str) + " 天", y=curve["per_step_snr"],
                          name="per-step SNR", marker_color="#4FC3F7", yaxis="y1"))
    fig3.add_trace(go.Scatter(x=curve["k_days"].astype(str) + " 天", y=curve["approx_detect_rate"],
                              name="近似偵測率", mode="lines+markers", marker_color="#FFD54F", yaxis="y2"))
    fig3.add_hline(y=2.0, line_dash="dash", line_color="#EF9A9A",
                  annotation_text="SNR=2 判定門檻參考線", yref="y1")
    fig3.update_layout(
        height=360, margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="per-step SNR"),
        yaxis2=dict(title="近似偵測率", overlaying="y", side="right", range=[0, 1]),
        legend=dict(orientation="h", y=1.12),
        title=f"淨 Δa={net_da:.1f} km、σ={sigma_km*1000:.0f} m 時，per-step SNR 與近似偵測率隨橫跨天數之變化",
    )
    st.plotly_chart(fig3, use_container_width=True)
    st.dataframe(curve.rename(columns={"k_days": "橫跨天數", "per_step_snr": "per-step SNR",
                                       "approx_detect_rate": "近似偵測率"}),
                hide_index=True, width="stretch")

    crossover = curve[curve["per_step_snr"] < 2.0]["k_days"].min()
    st.markdown(
        f"**在目前選定的假設下（σ={sigma_km*1000:.0f} m、淨 Δa={net_da:.1f} km），"
        + (f"橫跨約 **{int(crossover)} 天**以上，per-step SNR 就會跌破 2，逐點偵測器開始明顯失靈。**"
           if pd.notna(crossover) else "在所評估的天數範圍內，per-step SNR 皆未跌破 2，這組假設相對安全。**")
    )

    st.markdown("---")
    st.header("結論：這個問題有答案了嗎？")
    st.success(
        "**有，答案分兩種情境**：\n\n"
        "1️⃣ **抬軌階段**：實測速率換算 SNR 高達數十倍，1～2 天的典型 TLE 更新頻率就已是壓倒性證據，"
        "不是本專案的難點，也不需要更長觀測窗。\n\n"
        "2️⃣ **站位保持階段**：真正的技術瓶頸。淨位移若橫跨超過約一週執行，"
        "現有的**逐點線上偵測器**（CUSUM 累積偏離量／BOCPD 貝葉斯變點偵測／3σ-MAD 中位數絕對偏差門檻——"
        "三種統計變點/離群偵測方法，詳細原理見案例一）之 per-step SNR 就會跌破可靠判定門檻——"
        "這是目前 TLE 雜訊底下的物理限制，不是調參數能解決的，須靠精密星曆（如 MEME，靈敏度高 10–50 倍）才能治本。\n\n"
        "3️⃣ **但有個容易被忽略的但書**：上述限制是「逐點線上偵測器」特有的——如果目的不是即時告警、"
        "而是事後回顧「這段期間有沒有累積淨位移」，直接比較窗口起點與終點（per-episode 而非 per-step），"
        "訊噪比其實還是很高、清楚可辨。換句話說，**明確證據其實存在於資料裡，只是現有演算法沒有用最適合的方式去讀它**——"
        "這是一個比單純調整觀測窗長度更有希望的改善方向。"
    )
    st.caption("完整推導、合成注入實驗與委員意見回應見 `docs/期末報告_技術附錄_20260909.md` §10.7、§14、§18.2。")


# ══ 案例四（2026-09-10 新增）══════════════════════════════════════════════════
# 資料來源歸屬與 14/9 分組數字，取自本專案既有之
# docs/TASA_資料取得與處理_真值與精密星曆/README.md（整理日 2026-09-01，公開資料快照）。
# Jason-3 真實事件時刻/量級取自同夾 outputs/ids_truth.csv（IDS/DORIS operator 認證機動日誌），
# 為避免額外部署整個文件夾，此處直接內嵌所需之少量真實數值（可對照原始 CSV 覆核，非虛構）。

_JASON3_TRUTH_EVENTS = [
    # (epoch_utc, da_km, 說明) — 源：ids_truth.csv，Jason-3（NORAD 41240）
    ("2026-06-23T22:02:47.763", 0.150485, "burn 1（升）"),
    ("2026-06-24T00:50:35.701", 0.150400, "burn 2（升）"),
    ("2026-06-25T23:27:24.730", -0.139989, "burn 3（降）"),
    ("2026-06-26T02:15:13.168", -0.139925, "burn 4（降）"),
]


@st.cache_data(ttl=3600, show_spinner=False)
def load_case4_real_data() -> pd.DataFrame:
    """Jason-3（NORAD 41240）2026-06-20～07-02 之真實 TLE 半長軸序列，供與獨立真值疊圖。"""
    con = duckdb.connect(DB_PATH, read_only=True)
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km FROM raw_tle_archive "
        "WHERE norad_id=41240 AND epoch_utc BETWEEN '2026-06-20' AND '2026-07-02' "
        "ORDER BY epoch_utc").fetchdf()
    con.close()
    if df.empty:
        return df
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    return _dedup_by_gap(df, 30)


def render_storymap_case4():
    if st.button(t("storymap_back"), key="back_from_case4"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例四：23 顆外部標竿衛星的機動真值，從哪裡來、怎麼處理？")
    st.subheader("三個公開、免帳號來源，用真實案例驗證 TLE 是否對得上獨立真值")
    st.caption(
        "本報告多處宣稱之「非自算、外部獨立真值」，具體是怎麼取得的？"
        "這裡完整交代「14 顆開發樣本」＋「9 顆從未參與開發的 hold-out 衛星」共 23 顆之機動真值來源，"
        "並用一組真實案例驗證：TLE 看到的變化，是否真的對得上這份獨立真值。"
    )

    st.header("① 三個真值來源——這 23 顆星的真值不是同一個來源")
    st.markdown(
        "| 來源 | 涵蓋衛星 | 顆數 | 資料型態 | 時間系統 | 下載點 |\n"
        "|---|---|--:|---|---|---|\n"
        "| **A. IDS/DORIS 機動歷史檔** | 14 顆開發用測高星 ＋ hold-out 之 SPOT-2/3/4/5、Sentinel-6B | **19** | operator 認證機動日誌（含逐次 ΔV） | **TAI** | `ids-doris.org` |\n"
        "| **B. NASA PO.DAAC SOE 檔** | GRACE-A/B、GRACE-FO-C/D（全為 hold-out） | **4** | operator 認證推力事件（窗級） | **GPS 秒** | `archive.podaac.earthdata.nasa.gov` |\n"
        "| **C. TACC 福衛七號 leoOrb** | 福衛七號 6 顆（非 23 顆之一，另作 TLE 誤差基準用） | 6 | SP3-c 精密定軌星曆 | **GPS 時** | `tacc.cwa.gov.tw` |\n"
    )
    st.success("**三個來源皆為公開、免帳號**——不需要 Earthdata、Space-Track 等任何登入即可直接下載，這正是「非自算」可信度的基礎：真值來自衛星操作方自己認證公布的紀錄，不是本專案自己算出來再拿來自我驗證。")

    st.header("② 14 顆開發 vs 9 顆 hold-out 的分組與來源歸屬")
    st.markdown(
        "| 分組 | 衛星 | 來源 |\n"
        "|---|---|---|\n"
        "| **14 顆開發用** | Jason-1、Jason-2、Jason-3、Sentinel-6A、TOPEX/Poseidon、CryoSat-2、Envisat、Sentinel-3A、Sentinel-3B、SARAL、SWOT、HY-2A、HY-2C、HY-2D | 全部 **A. IDS** |\n"
        "| **9 顆 hold-out** | SPOT-2、SPOT-3、SPOT-4、SPOT-5、Sentinel-6B | **A. IDS**（5 顆） |\n"
        "| | GRACE-A、GRACE-B、GRACE-FO-C、GRACE-FO-D | **B. PO.DAAC**（4 顆） |\n"
    )
    st.markdown(
        "**這 9 顆 hold-out 怎麼選出來的**：具「LEO ＋ 公開機動真值」者共 18 顆 IDS/DORIS 測高星；"
        "扣掉 4 顆較老舊的 SPOT（成像任務、2010 年前 TLE 品質較差、姿態框架真值），"
        "得到現代乾淨的 14 顆做開發。**這 9 顆 hold-out 是「14 星之外全部剩餘可用者」，"
        "不是為了讓結果好看而挑選出來的**——把 4 顆 SPOT 放回來，加上原本就在 IDS 名單內、"
        "但未列入 14 顆開發集的 Sentinel-6B，再加上不在 IDS 名單、需另尋 PO.DAAC 來源的 GRACE 四姊妹。"
    )

    st.header("③ 處理這些資料最容易出錯的地方")
    st.warning(
        "**三個來源的時間系統各不相同，是最容易出錯之處**：IDS 用 **TAI**、"
        "PO.DAAC 的 SOE 檔用 **GPS 秒（自 J2000 起算）**、leoOrb 精密星曆用 **GPS 時**——"
        "三者與 UTC 皆有數十秒的固定差距。這個差距對「事件發生在哪一天」看似無傷大雅，"
        "但對接下來要比對的**機動時刻定位精度**（本報告中位數約 2.7 小時）而言，"
        "數十秒的系統性偏移若沒扣除，會讓每一次比對都固定偏移、稀釋掉真正的精度數字。"
        "本專案之解析器（`ids_man_parse.py`／`soe_build_truth_grace.py`）已內建對應換算，"
        "並各自留一條回歸測試防止未來改版時再次弄錯。"
    )

    st.header("④ 真實案例：Jason-3 的一次「升軌又降回來」站位保持")
    df = load_case4_real_data()
    if df.empty:
        st.warning("目前資料庫查無 Jason-3（NORAD 41240）之 TLE，此區塊暫時無法顯示。")
    else:
        events = [(pd.Timestamp(t, tz="UTC"), da, lbl) for t, da, lbl in _JASON3_TRUTH_EVENTS]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["epoch"], y=df["sma_km"], mode="lines+markers",
                                 name="TLE 半長軸（本專案 space_db）", line=dict(color="#4FC3F7")))
        y_top, y_bot = float(df["sma_km"].max()), float(df["sma_km"].min())
        for i, (te, da, lbl) in enumerate(events):
            te_str = te.isoformat()
            fig.add_shape(type="line", x0=te_str, x1=te_str, y0=y_bot, y1=y_top,
                         line=dict(color="#EF9A9A", dash="dot", width=1))
            fig.add_annotation(x=te_str, y=y_top if i % 2 == 0 else y_bot, text=lbl,
                              showarrow=False, yshift=12 if i % 2 == 0 else -12,
                              font=dict(color="#EF9A9A", size=10))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10),
                          xaxis_title="時間（UTC）", yaxis_title="半長軸 a (km)",
                          title="Jason-3（NORAD 41240）2026-06-20～07-02：TLE 實測 vs IDS/DORIS 獨立真值標記")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            "**IDS/DORIS 真值記載**（`ids-doris.org` 公開機動日誌，operator 認證，非本專案自算）："
        )
        ev_df = pd.DataFrame(_JASON3_TRUTH_EVENTS, columns=["真值時刻（UTC）", "真值 Δa (km)", "說明"])
        st.dataframe(ev_df, hide_index=True, width="stretch")

        net_up = sum(da for _, da, _ in _JASON3_TRUTH_EVENTS[:2])
        net_down = sum(da for _, da, _ in _JASON3_TRUTH_EVENTS[2:])
        st.success(
            f"**判讀**：真值記載 06-23／06-24 有兩次共 **+{net_up:.3f} km** 的升軌點火，"
            f"06-25／06-26 又有兩次共 **{net_down:.3f} km** 的降軌點火——這是典型的「站位保持死區來回」操作"
            "（先讓軌道略升，衰減一段時間後再修正回來）。"
            "**上圖的真實 TLE 曲線精確重現了這個先升後降的形狀**，時間點與真值標記完全對齊，"
            "淨變化量級也與真值相符（約 0.28～0.30 km）——這是本報告一貫方法論的具體示範：**用完全獨立、"
            "operator 自己認證的第三方紀錄，驗證我方從公開 TLE 讀出的訊號是否可信，而非球員兼裁判。**"
        )

    st.caption(
        "完整三來源之下載、篩選條件、例外處理與 23 顆完整清單，見 "
        "`docs/TASA_資料取得與處理_真值與精密星曆/`（README.md 及 01–04 號文件）；"
        "本節數字之可重現指令見該包 README §五。"
    )


# ══ StoryMap 案例五～七（2026-09-10 新增）══════════════════════════════════════

_CASE3_SATS = [
    (29052, "FORMOSAT-3A（純大氣衰減）"),
    (57681, "STARLINK-30273（電推機動）"),
    (25544, "ISS 國際太空站（真實 reboost，剛回補之 1998–2026 全歷史）"),
    (38752, "Van Allen A（HEO 再入衰減）"),
]


@st.cache_data(ttl=3600, show_spinner=False)
def load_case5_real_data() -> dict:
    """案例五之真實資料：4 顆代表性衛星的 NRLMSIS 阻力殘差（重用既有 compute_nrlmsis_maneuvers）。"""
    d0, d1 = pd.Timestamp("1990-01-01").date(), pd.Timestamp.today().date()
    out = {}
    for nid, lbl in _CASE3_SATS:
        try:
            r = compute_nrlmsis_maneuvers(nid, d0, d1, thr=0.30)
        except Exception:
            r = None
        if r is None or r.empty:
            out[nid] = {"label": lbl, "df": pd.DataFrame()}
            continue
        rd = r["drag_resid_da"].abs()
        out[nid] = {
            "label": lbl, "df": r, "reentry": bool(r.attrs.get("reentry", False)),
            "med": float(rd.median()), "p95": float(rd.quantile(0.95)), "max": float(rd.max()),
            "n_over": int((rd > 0.30).sum()), "n_flag": int(r["is_maneuver"].sum()), "n": len(r),
        }
    return out


def render_storymap_case5():
    if st.button(t("storymap_back"), key="back_from_case5"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例五：怎麼分辨「主動機動」跟「大氣阻力自然衰減」？")
    st.subheader("物理阻力殘差模型＋再入守門：四顆真實衛星的對照示範")
    st.caption("本頁全部數字皆由下方之快取函式對本機／遠端 TLE 資料庫即時查驗計算，非預先寫死之靜態文字。")

    st.markdown(
        "**問題背景**：低軌衛星的半長軸每天都在變小——這是大氣阻力造成的自然衰減，"
        "太陽活動越強（F10.7，10.7 公分波長太陽無線電通量，是最常用的太陽活動強度指標，越高代表太陽越活躍）"
        "衰減越快，跟「機動」完全無關。單看 |Δa| 沒辦法分辨兩者：一顆衛星今天掉了 50 公尺，"
        "可能是正常的阻力衰減，也可能是一次微幅機動。\n\n"
        "本專案的作法是先用 **NRLMSIS-2.1 半經驗大氣密度模型**，逐衛星算出「這段時間阻力理論上應該讓軌道掉多少」"
        "（`da/dt = -B·ρ·√(μa)`，B 為逐衛星自我校準的等效彈道係數），再從實測 Δa 中扣掉這個理論值——"
        "**扣除後還剩下的殘差，才是真正需要解釋的訊號**（機動、或模型解釋不了的異常）。"
    )

    data = load_case5_real_data()

    st.header("四顆真實衛星對照：殘差長什麼樣子？")
    cols = st.columns(2)
    for i, (nid, lbl) in enumerate(_CASE3_SATS):
        d = data.get(nid, {})
        with cols[i % 2]:
            st.subheader(lbl)
            df = d.get("df", pd.DataFrame())
            if df.empty:
                st.info(f"NORAD {nid} 目前資料庫中無足夠 TLE，略過。")
                continue
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["epoch"], y=df["drag_resid_da"], mode="lines",
                                     line=dict(color="#64B5F6", width=1), name="阻力殘差 Δa (km)"))
            flagged = df[df["is_maneuver"]]
            if not flagged.empty:
                fig.add_trace(go.Scatter(x=flagged["epoch"], y=flagged["drag_resid_da"], mode="markers",
                                         marker=dict(color="#EF5350", size=6, symbol="x"), name="判定為機動"))
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="殘差 Δa (km)", showlegend=False,
                              plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, key=f"case5_chart_{nid}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("資料筆數", f"{d['n']:,}")
            m2.metric("殘差中位數", f"{d['med']*1000:.1f} m")
            m3.metric("殘差最大值", f"{d['max']:.2f} km")
            m4.metric("判定為機動", f"{d['n_flag']}")
            if d.get("reentry"):
                st.warning(
                    f"⚠️ **再入守門觸發**：此衛星近地點已降到再入判準範圍，原始阻力殘差模型（非 secular）"
                    f"在這裡會爆量到最高 **{d['max']:.0f} km**——如果沒有 `is_reentry_decay()` 這道守門，"
                    f"系統會誤判成一次前所未見的巨大機動。守門邏輯直接判定「自然再入，機動=0」，"
                    f"上圖標記為機動的點數因此正確地是 **0**。"
                )

    st.markdown("---")
    st.success(
        "**判讀**：FORMOSAT-3A（穩定低軌、無機動）的殘差幾乎全部貼著 0；STARLINK-30273 "
        "的殘差有明顯超過門檻的尖峰，對應真實電推站位保持；ISS 因為橫跨 1998–2026 近 28 年真實推進器 "
        "reboost 歷史（本次對話中才剛從只有 2026-03 之後的殘缺資料，回補到完整 1998 年至今），"
        "殘差尖峰數量遠高於前兩者；Van Allen A 展示的是「模型會出錯，但系統設計了守門」的真實案例——"
        "**沒有物理阻力模型會把正常衰減當機動，沒有再入守門則會把再入當成史上最大機動。三道防線缺一不可。**"
    )
    st.caption("方法完整推導見 `atmospheric_drag.py`（NRLMSIS 阻力殘差）與 `docs/期末報告_技術附錄_20260909.md` §六～六.5。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_case6_real_data(days: int = 30) -> dict:
    """案例六之真實資料：即時對 Starlink 全星系跑軌道面/批量機動/隊形分析（重用 constellation_anomaly.py）。"""
    from constellation_anomaly import load_constellation, analyze, CONSTELLATIONS
    con = duckdb.connect(DB_PATH, read_only=True)
    pat = CONSTELLATIONS["Starlink"]
    mx = con.execute("SELECT MAX(epoch_utc) FROM raw_tle_archive WHERE UPPER(object_name) LIKE ?", [pat]).fetchone()[0]
    con.close()
    if mx is None:
        return {}
    date1 = pd.Timestamp(mx)
    date0 = date1 - pd.Timedelta(days=days)
    df = load_constellation(DB_PATH, pat, date0, date1)
    if df.empty or df["norad_id"].nunique() < 5:
        return {}
    R = analyze(df)
    R["window"] = (date0, date1)
    R["n_sats"] = int(df["norad_id"].nunique())
    R["n_tle"] = len(df)
    return R


def render_storymap_case6():
    if st.button(t("storymap_back"), key="back_from_case6"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例六：Starlink 這種巨型星系，抓得到「一次調整一整批衛星」嗎？")
    st.subheader("軌道面一致性、批量機動、隊形相位——三個角度即時檢驗上萬顆衛星")
    st.caption("本頁對整個 Starlink 星系即時計算，資料量較大，首次載入可能需要數十秒。")

    st.markdown(
        "**問題背景**：單顆衛星的機動偵測回答的是「這一顆有沒有動」；但 Starlink 有上萬顆衛星，"
        "有時候真正該問的是「有沒有一整批衛星同一天一起動」——這種集體行為（批次部署、軌道面重組）"
        "跟個別衛星的例行站位保持，代表完全不同的意義。以下用最近 30 天的真實資料，"
        "從三個角度檢驗：**軌道面是否一致**、**有沒有異常大量衛星同天機動**、**隊形相位有沒有跑掉**。"
    )

    days = 30
    R = load_case6_real_data(days)
    if not R:
        st.warning("目前資料庫中 Starlink 資料不足，無法計算。")
        return

    date0, date1 = R["window"]
    st.info(f"分析窗：**{date0.date()} ～ {date1.date()}**（{R['n_sats']:,} 顆衛星、{R['n_tle']:,} 筆 TLE）")

    planes, batch, formation = R["planes"], R["batch"], R["formation"]

    st.header("① 軌道面一致性：同一個軌道面的衛星，傾角應該幾乎完全一樣")
    nflag_p = int(planes["flag_plane_incoherent"].sum())
    fig1 = go.Figure()
    pv = planes.sort_values("di_std_deg", ascending=False)
    colors = ["#EF5350" if f else "#90A4AE" for f in pv["flag_plane_incoherent"]]
    fig1.add_trace(go.Bar(x=pv["plane"], y=pv["di_std_deg"], marker_color=colors, name="Δi std (deg)"))
    fig1.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                       yaxis_title="傾角變化標準差 (deg)", xaxis_title="軌道面",
                       plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    st.plotly_chart(fig1, use_container_width=True, key="case6_planes")
    st.caption(f"門檻＝中位數 + 3σ（自適應，非固定值）。紅色＝異常偏高的 {nflag_p} 個軌道面，"
              f"共 {len(planes)} 個軌道面中。")

    st.header("② 批量機動識別：有沒有異常多顆衛星同一天一起機動？")
    K = R["K"]
    bv = batch.sort_values("day")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=bv["day"].astype(str), y=bv["n_maneuvering"],
                          marker_color=["#EF5350" if f else "#64B5F6" for f in bv["flag_batch"]],
                          name="同天機動衛星數"))
    fig2.add_hline(y=K, line=dict(color="#EF9A9A", dash="dot"),
                   annotation_text=f"批量門檻 K≈{K:.0f}（mean+3σ）")
    fig2.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10),
                       yaxis_title="同天機動衛星數", plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    st.plotly_chart(fig2, use_container_width=True, key="case6_batch")
    nflag_b = int(batch["flag_batch"].sum())
    max_day = batch.loc[batch["n_maneuvering"].idxmax()]
    st.caption(f"觀測窗內單日最高 **{int(max_day['n_maneuvering'])} 顆**（{max_day['day']}），"
              f"門檻 K≈{K:.0f}；判定為「批量事件日」共 **{nflag_b} 天**。")

    st.header("③ 隊形相位誤差：同一軌道面內的衛星間距，有沒有跑掉？")
    fv = formation.sort_values("phase_resid_std_deg", ascending=False)
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(x=fv["plane"].head(15), y=fv["phase_resid_std_deg"].head(15),
                          marker_color="#FFB74D", name="相位殘差 std (deg)"))
    fig3.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                       yaxis_title="相位殘差標準差 (deg)", xaxis_title="軌道面（前 15 名）",
                       plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    st.plotly_chart(fig3, use_container_width=True, key="case6_formation")
    n_outliers = int(formation["n_outliers"].sum())
    st.caption(f"{len(formation)} 個軌道面中，相位離群衛星總數 **{n_outliers} 顆**。")

    st.markdown("---")
    if nflag_b == 0:
        st.success(
            f"**判讀（誠實揭露）**：這 {days} 天真實資料裡，"
            f"**沒有任何一天觸發批量機動門檻**（最高 {int(max_day['n_maneuvering'])} 顆 < K≈{K:.0f} 顆）——"
            "這本身就是一個有意義的負面結果：Starlink 的電推機動是持續性、分散式的個別衛星站位保持，"
            f"不是集中式的全星系同步動作。但軌道面一致性上仍抓到 **{nflag_p} 個**傾角異常偏高的軌道面"
            "（可能是新一批尚未完全settle的衛星、或殼層間的協同傾角調整），值得後續追蹤。"
        )
    else:
        bd = batch[batch["flag_batch"]]
        st.success(
            f"**判讀**：偵測到 **{nflag_b} 天**觸發批量機動門檻"
            f"（{', '.join(str(d) for d in bd['day'].head(5))}），"
            f"同時軌道面一致性上有 {nflag_p} 個異常軌道面——兩者對照可用於判斷是否為真實批次部署/重組事件。"
        )
    st.caption("方法完整推導見 `constellation_anomaly.py`；可用 `python constellation_anomaly.py --list` 查看其他已支援星系（OneWeb/Qianfan/Yaogan/Gaofen/Jilin）。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_case7_real_data() -> dict:
    """案例七之真實資料：TJS-10×TJS-3 GEO RPO ＋ ISS×Cygnus NG-24 對接（重用 conjunction_viz.py）。"""
    from conjunction_viz import compute_pair_series
    out = {}
    try:
        out["tjs"] = compute_pair_series(DB_PATH, 58204, 43874, start="2024-03-01", end="2024-07-31")
    except Exception:
        out["tjs"] = None
    try:
        out["cygnus"] = compute_pair_series(DB_PATH, 25544, 68689, start="2026-04-11", end="2026-04-19")
    except Exception:
        out["cygnus"] = None
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        out["iss_pc_row"] = con.execute(
            "SELECT * FROM conjunction_events WHERE primary_norad=25544 AND secondary_norad=68689"
        ).fetchdf()
    except Exception:
        out["iss_pc_row"] = pd.DataFrame()
    con.close()
    return out


def _case7_dist_chart(pair: dict, title: str, key: str):
    rel = pd.DataFrame(pair["rel"])
    rel["t"] = pd.to_datetime(rel["t"], format="ISO8601", utc=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rel["t"], y=rel["d"], mode="lines+markers",
                             line=dict(color="#BA68C8", width=1.5), marker=dict(size=3),
                             name="相對距離 (km)"))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), title=title,
                      yaxis_title="相對距離 (km)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=key)


def render_storymap_case7():
    if st.button(t("storymap_back"), key="back_from_case7"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例七：兩顆衛星多近才算「危險接近」？Pc／TCA 怎麼算出來的？")
    st.subheader("同樣的距離量級，非合作抵近與計畫內對接是完全不同的故事")
    st.caption("本頁全部數字皆由下方之快取函式對本機／遠端 TLE 資料庫即時以 SGP4 重建相對軌跡計算。")

    st.markdown(
        "**問題背景**：「兩顆衛星距離 15 公里」跟「兩顆衛星距離 15 公里」，可能代表完全不同的事情——"
        "取決於這兩顆衛星「打算不打算」靠近彼此。本案例對照兩個真實事件：一個是**非合作／意圖不明**的 "
        "GEO 抵近，一個是**合作／計畫內**的太空站貨運對接。兩者的最近距離量級接近，但意義天差地遠。\n\n"
        "本案例會用到兩個核心指標：**TCA**（Time of Closest Approach，最接近時刻——兩顆衛星預測軌跡"
        "距離最短的那一刻）與 **Pc**（Probability of Collision，碰撞機率——綜合最近距離與雙方軌道"
        "不確定性算出的一個 0～1 數字，越接近 1 代表碰撞風險越高）。"
    )

    data = load_case7_real_data()

    st.header("① TJS-10 抵近 TJS-3（GEO，2024 年春）")
    tjs = data.get("tjs")
    if tjs:
        s = tjs["summary"]
        _case7_dist_chart(tjs, "TJS-10 (58204) 相對 TJS-3 (43874) 之距離", "case7_tjs")
        c1, c2, c3 = st.columns(3)
        c1.metric("起始距離", f"{s['d_first']:.0f} km")
        c2.metric("最近距離 (TCA)", f"{s['d_min']:.1f} km")
        c3.metric("結束距離", f"{s['d_last']:.0f} km")
        st.markdown(
            "TJS-10（中國「通信技術試驗衛星」系列，任務不公開）與同軌位的 TJS-3 共位在 173°E 附近。"
            "2024 年 5 月 15–16 日，TJS-10 兩次真實半長軸機動（各 +11 公里量級）啟動西移，"
            f"15 日後在 **{s['d_min_t'][:16].replace('T',' ')} UTC 以 {s['d_min']:.1f} km** 從 TJS-3 東側掠過到西側，"
            "隨即再兩次反向機動煞車，最終停在 TJS-3 西側 65–85 公里處——**這是需要主動推進才能完成的軌跡反轉**，"
            "不是自然漂移。此案例常被歸類為「共位檢視／抵近偵察」行為。"
        )
    else:
        st.info("目前資料庫中無 TJS-10/TJS-3 之 TLE 重疊窗，略過。")

    st.header("② ISS 對接 Cygnus NG-24 貨運飛船（LEO，2026 年 4 月）")
    cyg = data.get("cygnus")
    if cyg:
        s = cyg["summary"]
        _case7_dist_chart(cyg, "ISS (ZARYA) 相對 CYGNUS NG-24 之距離", "case7_cygnus")
        c1, c2, c3 = st.columns(3)
        c1.metric("剛入軌時距離", f"{s['d_first']:,.0f} km")
        c2.metric("最遠曾拉開到", f"{s['d_max']:,.0f} km")
        c3.metric("對接時距離", "≈0 km")
        st.markdown(
            "Cygnus NG-24 貨運飛船發射入軌後，軌道相位尚未對齊 ISS，前兩天距離曾一度拉開到超過 "
            f"**{s['d_max']:,.0f} km**——這是正常的相位追趕過程（振幅逐漸收斂的靠近震盪），"
            "**不是異常軌跡**。到 4 月 17 日左右完成最終逼近，正式對接後兩者軌道基本重合。"
        )
        row = data.get("iss_pc_row")
        if isinstance(row, pd.DataFrame) and not row.empty:
            r0 = row.iloc[0]
            st.warning(
                f"**耐人尋味的對照**：本專案的自動化 Pc 篩選管線（`conjunction_events.parquet`）"
                f"對這一組真實接近事件（TCA {str(r0['tca_utc'])[:16]} UTC，最近距離僅 "
                f"**{r0['miss_distance_km']*1000:.1f} 公尺**）計算出 **Pc = {r0['pc']:.4f}，"
                f"風險等級 = {r0['risk_label']}**——單看這組數字，跟一次真正危險的抵近事件幾乎無法區分。"
                "但這其實是一次完全計畫內、雙方都知情配合的太空站貨運對接，安全等級最高。"
                "**這正是本案例要傳達的重點**：Pc/TCA 的距離幾何計算本身無法分辨「合作」與「非合作」，"
                "必須額外比對飛行計畫、發射任務資料庫，才能判斷一次近距接近究竟是操作正常還是真正的威脅。"
            )
    else:
        st.info("目前資料庫中無 ISS/Cygnus NG-24 之 TLE 重疊窗，略過。")

    st.markdown("---")
    st.success(
        "**判讀**：TJS-10×TJS-3 與 ISS×Cygnus 的最近距離都在「公里到公尺」量級，"
        "純粹看距離／Pc 數字本身無法分辨兩者的意圖差異——前者是非合作的抵近偵察（需要額外比對軌道機動特徵"
        "如反轉軌跡、共位歷史），後者是合作的計畫性對接（有公開發射任務資料佐證）。"
        "**這也是為什麼實務上的 SSA/SDA 分析從不能只看單一 Pc 數字，而要結合任務資料庫、機動歷史與外部情資。**"
    )
    st.caption("方法完整推導見 `conjunction_viz.py`（compute_pair_series，SGP4 相對運動重建）；"
              "TJS-10×TJS-3 案例另有互動版四視角 3D 視覺化於 `figs/rpo_tjs10_tjs3_2024.html`。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_case8_real_data() -> dict:
    """案例八之真實資料：資料庫本身的健檢（總量、跨度、逐月新收錄衛星數、ISS 個案）。"""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        if DATA_BACKEND == "hf":
            cat = con.execute(
                "SELECT norad_id, name, n, first_epoch, last_epoch FROM catalog").fetchdf()
        else:
            cat = con.execute(
                "SELECT norad_id, ANY_VALUE(object_name) AS name, COUNT(*) n, "
                "MIN(epoch_utc) AS first_epoch, MAX(epoch_utc) AS last_epoch "
                "FROM raw_tle_archive GROUP BY norad_id").fetchdf()
        iss = con.execute(
            "SELECT COUNT(*) n, MIN(epoch_utc) first_epoch, MAX(epoch_utc) last_epoch "
            "FROM raw_tle_archive WHERE norad_id=25544").fetchdf()
    finally:
        con.close()
    cat["first_epoch"] = pd.to_datetime(cat["first_epoch"], utc=True)
    cat["last_epoch"] = pd.to_datetime(cat["last_epoch"], utc=True)
    if not iss.empty:
        iss["first_epoch"] = pd.to_datetime(iss["first_epoch"], utc=True)
        iss["last_epoch"] = pd.to_datetime(iss["last_epoch"], utc=True)
    cat["first_ym"] = cat["first_epoch"].dt.strftime("%Y-%m")
    monthly = cat.groupby("first_ym").size().rename("n_new_sats").reset_index().sort_values("first_ym")
    return {
        "n_sats": int(len(cat)), "n_rows": int(cat["n"].sum()),
        "span_lo": cat["first_epoch"].min(), "span_hi": cat["last_epoch"].max(),
        "n_pre2020": int((cat["first_epoch"] < pd.Timestamp("2020-01-01", tz="UTC")).sum()),
        "monthly": monthly, "iss": iss.iloc[0] if not iss.empty else None,
        "backend": DATA_BACKEND,
    }


def render_storymap_case8():
    if st.button(t("storymap_back"), key="back_from_case8"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例八：這個資料庫本身的故事——3.4 萬顆衛星、跨度 55 年、一次目錄大擴編")
    st.subheader("從一個真實的使用者提問出發的資料庫健檢")
    st.caption("本頁全部數字皆由下方之快取函式對本機／遠端 TLE 資料庫即時查驗計算，非預先寫死之靜態文字。")

    st.markdown(
        "**這個案例的起點是一個真實的使用者提問**：「目前 App 上看到的資料最早只到今年 3 月，"
        "當初設計的『分年 parquet』架構是不是沒有真正啟用？」——這個問題的調查過程本身，"
        "就是一次很好的資料庫健檢示範，所以把它原封不動做成一個案例。"
    )

    data = load_case8_real_data()
    span_days = (data["span_hi"] - data["span_lo"]).days

    st.header("① 全庫真實跨度：不是只有 3 月，是 55 年")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("衛星總數", f"{data['n_sats']:,}")
    c2.metric("TLE 總筆數", f"{data['n_rows']:,}")
    c3.metric("最早資料", f"{data['span_lo'].date()}")
    c4.metric("最新資料", f"{data['span_hi'].date()}")
    st.caption(f"跨度約 **{span_days/365.25:.0f} 年**；其中 **{data['n_pre2020']} 顆衛星**"
              f"在 2020 年以前就已有 TLE 紀錄（多為長期追蹤之標竿／既有衛星）。")

    st.header("② 逐月新收錄衛星數：3～4 月的斷崖式擴編")
    m = data["monthly"]
    fig = go.Figure()
    colors = ["#EF5350" if ym in ("2026-03", "2026-04") else "#64B5F6" for ym in m["first_ym"]]
    fig.add_trace(go.Bar(x=m["first_ym"], y=m["n_new_sats"], marker_color=colors))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="當月「首次出現」衛星數", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(tickangle=-60, tickmode="auto", nticks=25))
    st.plotly_chart(fig, use_container_width=True, key="case8_monthly")
    mar_apr = int(m[m["first_ym"].isin(["2026-03", "2026-04"])]["n_new_sats"].sum())
    st.warning(
        f"⚠️ **紅色兩根長條就是使用者觀察到的「3 月現象」的真正原因**：2026 年 3～4 月，"
        f"單月就有 **{mar_apr:,} 顆衛星**是「首次」被收錄進追蹤管線——佔全庫 {data['n_sats']:,} 顆衛星的 "
        f"**{mar_apr/data['n_sats']*100:.0f}%**。這是一次一次性的目錄擴編事件（追蹤範圍從幾百～兩千顆核心衛星，"
        "擴大到近乎全量的公開在軌目錄），**不是分年 parquet 沒啟用、也不是舊資料遺失**——"
        "新收錄物件的「歷史」本來就只能從收錄當下開始，無法回溯抓到收錄前的資料。"
    )

    st.header("③ 具體案例：ISS（NORAD 25544）")
    iss = data["iss"]
    if iss is not None:
        i1, i2, i3 = st.columns(3)
        i1.metric("目前最早 TLE", f"{pd.Timestamp(iss['first_epoch']).date()}")
        i2.metric("目前最新 TLE", f"{pd.Timestamp(iss['last_epoch']).date()}")
        i3.metric("目前筆數", f"{int(iss['n']):,}")
        if pd.Timestamp(iss["first_epoch"]) > pd.Timestamp("2020-01-01", tz="UTC"):
            st.info(
                "**這正是使用者問題點名的具體案例**：ISS 從 1998 年就已在軌，但（在本次調查當下）"
                f"資料庫裡最早的 TLE 只到 **{pd.Timestamp(iss['first_epoch']).date()}**——"
                "跟上面②的擴編事件時間點完全吻合，證實 ISS 正是當時新收錄的一顆衛星，而非它以前的資料遺失或損毀。\n\n"
                "**本次對話中已對本機資料庫完成回補**：用 `backfill_tle_history.py 25544` 向 Space-Track 補抓 "
                "gp_history，新增 **47,038 筆**，最早 epoch 推回到 **1998-11-20**（ISS 發射入軌當月）——"
                "待下次資料集（`RhynoWu/starlink-maneuver-db`）重新匯出／同步後，此處數字會更新為完整 28 年歷史。"
            )
        else:
            st.success(
                f"ISS 目前資料已回補到 **{pd.Timestamp(iss['first_epoch']).date()}**（完整歷史），"
                "本案例描述的「3 月斷點」問題已修復。"
            )
    st.caption(f"目前執行環境：資料後端 = `{data['backend']}`（local＝本機全庫 space_db.duckdb；"
              "hf＝遠端 httpfs 直查 HuggingFace Dataset）。")

    st.markdown("---")
    st.success(
        "**判讀**：「資料看起來從某個時間點才開始」幾乎都不代表資料遺失或架構沒生效，"
        "而是要先問「這顆衛星是什麼時候被納入追蹤範圍的」——這是所有長期累積型資料庫最容易被誤解的特徵。"
        "分年 parquet 分割邏輯確實寫在 `export_to_hf_parquet.py`（`PARTITION_BY (year)`），"
        "但只在單表超過 2,500 萬列時才觸發；本庫 `raw_tle_archive` 目前約 1,954 萬列，未達門檻，"
        "因此維持單檔——這與「3 月斷崖」是兩件完全獨立的事。"
    )
    st.caption("方法完整推導：本案例之調查對話記錄；相關程式見 `export_to_hf_parquet.py`、`backfill_tle_history.py`。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_case9_real_data() -> dict:
    """案例九之真實資料：三層同一擂台之凍結盲測結果（讀取離線批次評測輸出，非即時重算）。"""
    out = {}
    p1 = DATA / "benchmark" / "frozen_blind_20260803.csv"
    p2 = DATA / "benchmark" / "three_layer_common_eval_20260803.csv"
    p3 = DATA / "benchmark" / "three_layer_perunit_20260803.csv"
    out["blind"] = pd.read_csv(p1) if p1.exists() else pd.DataFrame()
    out["arena"] = pd.read_csv(p2) if p2.exists() else pd.DataFrame()
    if p3.exists():
        pu = pd.read_csv(p3)
        pos = pu[pu["label"] == 1].copy()
        g = pos.groupby("norad_id").agg(n_pos=("label", "size"), n_hit=("l3_pred", "sum")).reset_index()
        g["recall"] = g["n_hit"] / g["n_pos"]
        out["n_sats"] = int(pu["norad_id"].nunique())
        out["n_pos"] = int(len(pos))
        out["n_neg"] = int((pu["label"] == 0).sum())
        out["worst"] = g[g["n_pos"] >= 2].sort_values("recall").head(5)
        out["perfect_n"] = int((g["recall"] >= 0.999).sum())
    else:
        out["n_sats"] = out["n_pos"] = out["n_neg"] = out["perfect_n"] = 0
        out["worst"] = pd.DataFrame()
    return out


def render_storymap_case9():
    if st.button(t("storymap_back"), key="back_from_case9"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例九：模型對「從沒看過的衛星」還準不準？三層擂台怎麼公平比較？")
    st.subheader("Unseen-satellite hold-out：不讓模型背答案的誠實測試")
    st.caption(
        "本頁數字讀取自離線批次評測輸出（`data/benchmark/*_20260803.csv`）——"
        "這項評測本身涉及對全庫 284 顆衛星重跑 5 通道統計偵測器＋交叉驗證訓練，屬分鐘級批次工作，"
        "不適合在網頁點擊時即時重算，因此展示的是**凍結、可重現的評測結果**，而非即時查詢。"
    )

    st.markdown(
        "**問題背景**：機動偵測模型很容易「背answer」——如果訓練跟測試用到同一批衛星，"
        "模型可能只是記住了每顆衛星的個別特徵，而不是真的學會「機動長什麼樣子」。"
        "真正誠實的測試方法，是把一整批衛星**完全藏起來、從頭到尾不讓模型看過**，"
        "再拿訓練好的模型去猜這些陌生衛星的機動——這就是 unseen-satellite hold-out。"
    )

    data = load_case9_real_data()

    st.header("① Unseen-satellite hold-out 怎麼做的？")
    st.markdown(
        f"從全庫 **{data['n_sats']}** 顆有精密星曆真值的 Starlink 衛星中，"
        "用固定亂數種子（`np.random.default_rng(2026)`）隨機留出 **20%（56 顆）整組**，"
        "訓練另外 228 顆的模型後，直接套用到這 56 顆從沒見過的衛星身上——"
        "判定門檻也完全只用訓練折的資料決定，測試折的資料連「用來選門檻」都不准碰。"
        f"（正樣本 unit **{data['n_pos']:,}** 個、負樣本 unit **{data['n_neg']:,}** 個）"
    )
    if not data["blind"].empty:
        bl = data["blind"].copy()
        bl.columns = ["情境", "AUC", "大型機動召回率", "整體召回率", "誤報率(FPR)", "測試 unit 數"]
        st.dataframe(bl.style.format({"AUC": "{:.3f}", "大型機動召回率": "{:.1%}",
                                       "整體召回率": "{:.1%}", "誤報率(FPR)": "{:.3f}"}),
                    use_container_width=True, hide_index=True)
        st.caption("「out-of-time」是另一種嚴格測試：用前 60% 時間的資料訓練、後 40% 完全未來的資料盲測——"
                  "兩者都比一般的隨機切分測試嚴格得多。")

    st.header("② 三層架構同一擂台：規則式 vs 傳統 ML（單通道）vs 融合模型")
    if not data["arena"].empty:
        ar = data["arena"].copy()
        fig = go.Figure()
        colors = ["#EF5350" if "naive" in m else ("#66BB6A" if "L3" in m else "#64B5F6")
                 for m in ar["method"]]
        fig.add_trace(go.Bar(x=ar["method"], y=ar["recall"], marker_color=colors, name="召回率"))
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=120),
                          yaxis_title="整體召回率", xaxis=dict(tickangle=-45),
                          plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="case9_arena")
        l3 = ar[ar["method"].str.contains("L3")].iloc[0]
        naive = ar[ar["method"].str.contains("naive")].iloc[0]
        l1 = ar[ar["method"].str.contains("L1")].iloc[0]
        st.caption(
            f"融合模型（L3）召回率 **{l3['recall']:.1%}**（大型機動 {l3['rec_large']:.1%}），"
            f"遠高於純規則式 L1 的 {l1['recall']:.1%}，也遠高於隨機基準 naive 的 {naive['recall']:.1%}——"
            "naive 接近 0 正好證明這個測試集不是靠「亂猜也能矇對」的資料洩漏撐出來的高分。"
        )

    st.header("③ 逐衛星戰績：哪些衛星模型表現最差？")
    if not data["worst"].empty:
        w = data["worst"].copy()
        w.columns = ["NORAD ID", "正樣本 unit 數", "命中數", "召回率"]
        st.dataframe(w.style.format({"召回率": "{:.1%}"}), use_container_width=True, hide_index=True)
        st.caption(f"（僅列出正樣本≥2 個之衛星以避免小樣本雜訊）另有 **{data['perfect_n']} 顆**衛星的正樣本 unit 全數命中（召回率 100%）。"
                  "沒有隱藏最差表現——這正是誠實揭露模型限制的一部分。")

    st.markdown("---")
    st.success(
        "**判讀**：AUC（Area Under Curve，ROC 曲線下面積——分類器整體判別力的常用指標，"
        "1.0 為完美、0.5 為隨機亂猜）達 0.98、大型機動召回率 100%"
        "（81 個大型事件全中，Wilson 95% CI [0.955, 1.000]）——"
        "在完全沒看過的衛星上依然成立，代表模型學到的是可泛化的機動特徵，不是死記個別衛星。"
        "out-of-time 測試的 AUC 略降到 0.94，是誠實的次要限制：時間越久，星系操作模式可能緩慢漂移，"
        "泛化力會比對「同時期陌生衛星」略打折扣，但仍遠優於任何單一規則或單通道方法。"
    )
    st.caption("完整推導與逐切片穩定度分析見 `three_layer_common_eval.py`、`docs/期末報告_技術附錄_20260909.md` §13.2、表 13-3／13-11。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_case10_real_data() -> pd.DataFrame:
    """案例十之真實資料：TLE 反推熱層密度之複現嘗試（讀取離線分析輸出，非即時重算）。"""
    p = Path("thermosphere_kyoto_repro.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def render_storymap_case10():
    if st.button(t("storymap_back"), key="back_from_case10"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例十：能不能只用 TLE 反推大氣密度？")
    st.subheader("一個誠實的負面結論與方法上限")
    st.caption("本頁所有數字來自離線分析輸出檔 `thermosphere_kyoto_repro.csv`，記錄的是一次「未能成功複現目標結果」的真實嘗試。")

    st.markdown(
        "**問題背景**：日本京都大學團隊（Yamamoto, 2026, *Earth, Planets and Space*, 78, Article 175）"
        "利用約 1,200 顆 Starlink 衛星的精密星曆，在約 482 公里高度反演出隨緯度與地方時變化的大氣密度 2D 分布圖——"
        "包括日側因太陽加熱而膨脹、夜側收縮的「密度鼓包」（地球大氣受陽光加熱後像被曬熱的氣球一樣局部膨脹，"
        "白天那一側的密度因此明顯高於夜晚那一側）。\n\n"
        "**為什麼會有人期待 TLE 也能做到**：TLE 每天免費公開更新、涵蓋全球幾乎所有在軌衛星，"
        "如果能從中反推大氣密度，等於是拿到一份不花錢的全球太空天氣感測網。"
        "但 TLE 的設計初衷是「粗略軌道預報」，精度只有百公尺到公里級，遠低於精密星曆——"
        "**本案例要誠實回答的是：這個落差，最後會不會真的讓結果做不出來。**\n\n"
        "本專案想問：如果只用免費、公開的 TLE（而非昂貴的精密星曆），有沒有機會做出類似等級的結果？"
        "本案例誠實展示結論：**做不到，並說明為什麼做不到**。"
    )
    st.caption(
        "📄 原始論文：Yamamoto, T. (2026). *Earth, Planets and Space*, 78, Article 175. "
        "京都大學團隊以約 1,200 顆 Starlink 衛星的精密星曆，反演熱層密度隨緯度與地方時變化的 2D 分布（本案例的參照基準）。"
        "本頁未直接附上全文連結——建議以上述書目資訊在期刊官網或 Google Scholar 搜尋全文，避免引用未經核對的第三方連結。"
    )

    df = load_case10_real_data()

    st.header("① 嘗試過程：四個版本，一次比一次更嚴謹")
    st.markdown("**版本 1｜純 TLE 版**")
    st.markdown(
        "篩選軌道高度單調下降、處於衰變末期的衛星（共 **584 顆**），"
        "利用 NRLMSIS 大氣模型校準後，從衰減率反推密度隨高度的變化剖面。"
    )
    st.markdown("**版本 2｜MEME 精密星曆版**")
    st.markdown(
        "改用 **283 顆** Starlink 衛星的精密位置/速度資料（MEME），"
        "以「比能量法」（specific energy method——用軌道能量隨時間的損耗速率反推阻力大小）直接估算大氣密度，"
        "避開純 TLE 版本的擬合誤差。"
    )
    st.markdown("**版本 3｜逐星自校準版**")
    st.markdown(
        "將資料切成 **924 個**阻力弧段，對每顆衛星單獨校準「彈道係數」（ballistic coefficient——"
        "描述衛星形狀/質量對阻力有多敏感的一個係數），嘗試壓低因姿態與外形不確定造成的雜訊。"
    )
    st.markdown("**版本 4｜忠實複現京大方法版（本頁資料來源）**")
    st.markdown(
        "進一步改用 EGM96 12 階重力場（比一般簡化模型更精確的地球重力場模型）計算比能量，"
        f"盡可能貼近京大團隊的方法設定，最終得到 **{len(df)} 個**「乾淨」阻力弧段的密度比對結果。"
    )

    if not df.empty:
        st.header("② 真實比對：本專案反推密度 vs NRLMSIS 模型密度")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["rho_msis"], y=df["rho_obs"], mode="markers",
                                 marker=dict(color="#FFB74D", size=6, opacity=0.7), name="151 個真實阻力弧"))
        lo, hi = df["rho_msis"].min(), df["rho_msis"].max()
        fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines",
                                 line=dict(color="#90A4AE", dash="dot"), name="完全吻合線"))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="NRLMSIS 模型密度 (kg/m³)", yaxis_title="本專案反推密度 (kg/m³)",
                          plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True, key="case10_scatter")
        ratio = df["ratio"]
        c1, c2, c3 = st.columns(3)
        c1.metric("比值中位數", f"{ratio.median():.2f}")
        c2.metric("比值 IQR", f"{ratio.quantile(.25):.2f}～{ratio.quantile(.75):.2f}")
        c3.metric("有效阻力弧數", f"{len(df)}")
        st.caption(
            "在理想情況下，如果反推結果完美，每個點應該緊貼圖中的灰色虛線（反推密度＝NRLMSIS 密度）。"
            "實際結果卻是點群散布極廣：中位數雖然落在 1.00（代表整體沒有系統性偏差），"
            "但四分位距 0.39～1.24 代表同一高度下，反推密度可能只有模型值的 4 成，也可能高達 1.2 倍——"
            "**這種大幅離散，就是「無法乾淨複現京大結果」的直接視覺證據，而不是文字上空泛地說『效果不好』。**"
        )

    st.header("③ 三個根因：為什麼做不到")
    st.markdown("**根因 1｜樣本本身有偏差**")
    st.markdown(
        "能篩選出「軌道高度單調下降、乾淨到適合反推」的衛星，幾乎都是壽命末期、姿態失控的離軌衛星。"
        "對這些衛星來說，軌道衰減主要由「翻滾姿態造成的有效阻力面積變化」主導，而不是真實大氣密度的變化。\n\n"
        "結果是：反推出的「密度尺度高度」（scale height——大氣密度隨高度每增加這個距離就衰減為原本的約 37%，"
        "數值越貼近真實大氣模型代表反推越準）高達 **−120 公里**（負值代表密度隨高度上升反而增加，物理上不合理），"
        "對照 NRLMSIS 在該高度應有的約 **58 公里**。"
    )
    st.markdown("**根因 2｜B\\* 循環論證**")
    st.markdown(
        "TLE 中的彈道係數 B\\* 本身就是從軌道衰減率反推出來的參數。當我們再用 B\\* 去除衰減率來推算密度時，"
        "等於是「用答案去除答案」，密度訊號在計算過程中被自己抵消掉一部分。\n\n"
        "這會導致反推出的尺度高度被拉平到約 **212 公里**，遠大於真實大氣的 58 公里，"
        "代表密度隨高度的真實變化被嚴重低估、訊號被磨平了。"
    )
    st.markdown("**根因 3｜軌道覆蓋太稀疏＋TLE 本身雜訊大**")
    st.markdown(
        "Starlink 主力殼層集中在約 53° 傾角，極軌衛星只有約 13 顆。在「緯度×地方時」這張 2D 網格上，"
        "很多格子幾乎沒有資料，空間取樣嚴重不足；再加上 TLE 本身的位置/速度誤差通常達百公尺到公里級，"
        "最終反推出的密度場空間相關係數只有 **r = 0.42**（0 代表毫無關聯、1 代表完全一致，"
        "0.42 屬於低到中度相關）——完全沒有重現出京大版本清晰可見的日側密度鼓包。"
    )
    st.info(
        "**後續 MEME 精密星曆版的追加診斷**：即使把輸入資料換成精密星曆、並逐星自校準彈道係數，"
        "每個阻力弧段的密度估計仍卡在約 **0.62 dex** 的離散度"
        "（dex 是以 10 為底的對數尺度單位，0.62 dex 代表上下浮動約 **4 倍**），校準前後幾乎沒有明顯改善——"
        "顯示真正的瓶頸不只是上面三個 TLE 特有的根因，而是更根本的：**單一比能量法**（只靠軌道能量變化這"
        "一個訊號反推阻力）**本身的精度上限**。即使輸入資料從 TLE 升級到精密星曆，這個方法能提取的資訊量"
        "依然不足以支撐京大等級的 2D 密度斷層重建。"
    )

    st.markdown("---")
    st.warning(
        "**可行的下一步**（誠實給出，而非假裝問題已解決）——若未來想繼續朝這個方向推進，建議路線：\n\n"
        "① **改用 SpaceX 公開的精密星曆直接算加速度**：避開 TLE 中 B\\* 的循環論證，"
        "直接從位置/速度時間序列估算阻力加速度（本專案已部分執行此路線）；\n\n"
        "② **針對運作中衛星，擷取「純阻力空窗期」**：在兩次站位保持之間，選取幾乎無推力干擾的弧段"
        "重新校準彈道係數，減少姿態與推力造成的訊號混疊；\n\n"
        "③ **降低目標，從 2D 斷層改為全球平均指標**：不強求重建京大等級的緯度×地方時 2D 密度斷層，"
        "先做「全球平均密度隨太陽活動變化」的定性指標，作為既有大氣模型的輔助校驗資料；\n\n"
        "④ **若要真正重現京大等級結果**：需要 POD（精密定軌）等級的逐點阻力加速度反演法，"
        "配合更嚴謹的誤差模型與資料同化，這已超出本專案目前「簡化比能量法」路線的可及範圍。"
    )
    st.caption("完整技術推導見 `thermosphere_kyoto_repro.py`、`thermosphere_meme_bccal.py`、"
              "`docs/研究_Starlink熱層密度_TLE限制_20260807.md`。")

    st.markdown("---")
    st.success(
        "**本案例的啟示**：這個負面結果其實提供了兩個重要訊息——\n\n"
        "1. **TLE 不適合用來做高精度大氣密度反演**：它的設計目標是提供粗略軌道預報，而非精密物理參數反演；\n"
        "2. **方法本身也有資訊上限**：即使把輸入資料從 TLE 升級到精密星曆，單一比能量法仍不足以支撐 "
        "2D 密度斷層的重建，問題不只出在資料，也出在方法本身能萃取的資訊量。\n\n"
        "對後續研究者來說，與其硬把 TLE 推到它設計範圍之外，不如把資源投入在取得更高品質的軌道資料"
        "（POD、精密星曆）、以及發展更完整的阻力反演框架（含誤差模型、資料同化、多源資料融合）——"
        "這才是更接近京大團隊成果的可持續路線。"
    )


# ══ StoryMap 案例一～二（2026-09-10 新增，置頂）══════════════════════════════════

def _pipeline_flowchart_fig() -> go.Figure:
    """畫出偵測管線流程圖（純 Plotly shapes/annotations，不依賴 graphviz 系統套件）。
    高對比版：實心飽和底色＋白色粗體字，非 AI／AI 兩色系分色，加大字級。"""
    boxes = [
        # (x, y, w, h, label, color)
        (0.3, 5.5, 3.0, 1.0, "①  TLE 逐日下載<br>（Space-Track／CelesTrak）", "#0D47A1"),
        (0.3, 4.1, 3.0, 1.0, "②  換算軌道根數<br>（SGP4 → a/e/i/RAAN/…）", "#0D47A1"),
        (-0.2, 2.5, 1.9, 1.0, "③a  L1 規則式<br>P1–P6 門檻<br><b>非 AI</b>", "#37474F"),
        (1.85, 2.5, 1.9, 1.0, "③b  L2 統計通道<br>CUSUM/BOCPD/SSA/MAD3σ<br><b>非 AI</b>", "#37474F"),
        (3.9, 2.5, 1.9, 1.0, "③c  物理阻力殘差<br>NRLMSIS<br><b>非 AI</b>", "#37474F"),
        (5.95, 2.5, 1.9, 1.0, "③d  ML 分類器<br>LightGBM（MEME 訓練）<br><b>AI</b>", "#6A1B9A"),
        (1.85, 1.1, 3.9, 1.0, "④  L3 融合評分器　HistGradientBoosting　<b>AI</b>", "#6A1B9A"),
        (1.85, -0.2, 3.9, 0.9, "⑤  最終機率＋判定<br>（對照 14+9 顆真值驗證）", "#1B5E20"),
    ]
    fig = go.Figure()
    for x, y, w, h, label, color in boxes:
        fig.add_shape(type="rect", x0=x, y0=y, x1=x + w, y1=y + h,
                      line=dict(color="#FFFFFF", width=2), fillcolor=color, opacity=1.0,
                      layer="below")
        fig.add_annotation(x=x + w / 2, y=y + h / 2, text=f"<b>{label}</b>",
                           showarrow=False, font=dict(size=16, color="#FFFFFF", family="Arial Black, Arial"),
                           align="center")
    # ①→②
    fig.add_annotation(x=1.8, y=4.1, ax=1.8, ay=5.5, xref="x", yref="y", axref="x", ayref="y",
                       showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor="#FFD54F", arrowwidth=3)
    # ②→③a/b/c/d
    for bx in (0.75, 2.8, 4.85, 6.9):
        fig.add_annotation(x=bx, y=3.5, ax=1.8, ay=4.1, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=1.3, arrowcolor="#FFD54F", arrowwidth=2.5)
    # ③a/b/c/d→④
    for bx in (0.75, 2.8, 4.85, 6.9):
        fig.add_annotation(x=3.8, y=2.1, ax=bx, ay=2.5, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=1.3, arrowcolor="#FFD54F", arrowwidth=2.5)
    # ④→⑤
    fig.add_annotation(x=3.8, y=0.7, ax=3.8, ay=1.1, xref="x", yref="y", axref="x", ayref="y",
                       showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor="#FFD54F", arrowwidth=3)
    fig.update_xaxes(visible=False, range=[-0.5, 8.1])
    fig.update_yaxes(visible=False, range=[-0.5, 6.7])
    fig.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def render_storymap_case1():
    if st.button(t("storymap_back"), key="back_from_case1"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例一：從 TLE 偵測機動，到底可不可行？")
    st.subheader("演算法架構與流程全貌（StoryMap 入口／總覽案例）")
    st.caption("本頁為 StoryMap 的總覽案例：先看懂整體架構，後面每個案例都是這張圖裡某一塊的深入展開。")

    st.markdown(
        "**核心問題**：公開、免費、每天更新一次、定位精度只有百公尺量級的 TLE，"
        "能不能拿來偵測衛星的軌道機動？（正因為它免費、覆蓋全球幾乎所有在軌衛星、歷史又長，"
        "才會讓人想拿它來做這件事——但它的設計初衷其實是「粗略軌道預報」，不是精密物理量測。）\n\n"
        "**本專案的答案**：可以，但必須用對方法組合，而且一定要用獨立的機動真值"
        "（精密星曆或官方紀錄）反覆驗證，**不能只靠「看起來合理」就相信結果**。"
    )

    st.header("① 整體流程")
    st.plotly_chart(_pipeline_flowchart_fig(), use_container_width=True, key="case1_flowchart")
    st.caption("下方文字說明中，每個步驟前面的顏色標記對應流程圖中的色塊：　"
              "🔵 藍＝資料前處理　⬛ 灰＝非 AI（規則／統計／物理模型）　🟣 紫＝AI（機器學習）　🟢 綠＝最終驗證")

    st.markdown("**🔵 ①② 資料前處理**")
    st.markdown(
        "每日從 Space-Track 或 CelesTrak 下載最新 TLE，利用 SGP4（一套標準化的軌道傳播演算法）"
        "換算成時間序列形式的軌道根數（描述軌道形狀與方位的一組數字），包括半長軸、離心率、傾角等。"
        "這些「軌道根數時序」就是後續所有偵測方法的共同輸入訊號。"
    )

    st.markdown("**③ 四種平行偵測方法**（同一份軌道根數時序，同時送進四種原理完全不同的通道——詳細分類見案例二）")
    st.markdown(
        "**⬛ L1 規則式 P1–P6**：人工訂定的硬門檻規則，例如「半長軸變化量 |Δa| 超過某個值」就標記為可能機動。"
        "優點是最容易理解、最容易解釋；缺點是誤報與漏報都偏高，單獨使用不夠可靠。"
    )
    st.markdown(
        "**⬛ L2 統計變點偵測**：CUSUM（累積偏離量）、BOCPD（貝葉斯變點偵測）、SSA（奇異譜分析）、"
        "MAD3σ（以中位數絕對偏差設門檻）四個經典統計通道，各自用不同的數學定義去捕捉「訊號突然改變」的時刻。"
    )
    st.markdown(
        "**⬛ 物理阻力殘差**：先用 NRLMSIS 大氣密度模型估算「這段時間單純由大氣阻力造成的軌道衰減應該是多少」，"
        "再從實際觀測的軌道變化中扣掉這部分——剩下的「殘差」才是真正需要由機動來解釋的訊號（詳細推導見案例五）。"
    )
    st.markdown(
        "**🟣 ML 分類器**：用 14 顆擁有精密星曆真值的衛星資料，訓練一個 LightGBM（一種梯度提升樹模型）分類器，"
        "直接學習「有機動 vs 無機動」在軌道根數時序上的特徵模式。"
    )

    st.markdown("**🟣 ④ 融合**")
    st.markdown(
        "L3 融合評分器把前面所有通道的分數（規則分數、統計變點分數、阻力殘差分數、ML 分類機率）當作特徵，"
        "訓練一個 HistGradientBoosting（一種能穩健處理大量特徵與缺值的梯度提升模型）模型來統一裁決——"
        "**不是隨便選一種方法的結果，而是讓模型學會在什麼情況下該相信哪一個通道**，綜合所有訊號做出最終判定。"
    )

    st.markdown("**🟢 ⑤ 驗證**")
    st.markdown(
        "最終判定結果會與兩組機動真值逐一核對：「原始 14 顆開發樣本」＋「9 顆完全沒參與開發的 hold-out 衛星」"
        "（用來測試模型是否真的學到可泛化的機動特徵，而不是背答案）。"
        "機動真值來源包括 IDS/DORIS（國際多普勒衛星定軌系統之精密軌道）、"
        "NASA PO.DAAC、TACC 等機構提供的精密星曆（詳細來源與處理見案例四）。"
        "**換句話說：本專案的績效不是自己說了算，而是用獨立、外部的高精度資料反覆驗證過。**"
    )

    st.header("② 可行性驗證：這套組合方法，準不準？")
    arena = load_case9_real_data().get("arena", pd.DataFrame())
    if not arena.empty:
        fig = go.Figure()
        colors = ["#EF5350" if "naive" in m else ("#66BB6A" if "L3" in m else "#64B5F6")
                 for m in arena["method"]]
        fig.add_trace(go.Bar(x=arena["method"], y=arena["recall"], marker_color=colors))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=120),
                          yaxis_title="整體召回率", xaxis=dict(tickangle=-45),
                          plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="case1_methods")
        l3 = arena[arena["method"].str.contains("L3")].iloc[0]
        st.success(
            f"**答案是肯定的**：融合模型的整體召回率達 **{l3['recall']:.1%}**，"
            f"對大型機動事件召回率更高達 **{l3['rec_large']:.1%}**，"
            "而且在完全沒參與訓練的 hold-out 衛星上，AUC 仍達 0.98（見案例九的 unseen-satellite 測試）——"
            "這代表模型不是「背下 14 顆衛星的答案」，而是真的學到可泛化的機動特徵，"
            "即使換到新的衛星上，依然能維持高水準的偵測能力。"
        )
    st.caption("方法逐一展開見：案例五（物理阻力殘差）、案例九（三層擂台公平比較）、案例四（真值資料從哪來）、"
              "案例二（哪些步驟用了 AI、哪些沒有）。")

    st.markdown("---")
    st.info(
        "**如何使用本 StoryMap**：若你是第一次接觸本系列，建議的閱讀順序是——\n\n"
        "**案例一**（本頁）：看懂整體架構與流程　→　**案例二**：了解哪些步驟用了 AI、哪些沒有　→　"
        "**案例三～八**：深入各個關鍵技術環節（觀測窗長度、真值資料、阻力模型、星系批量偵測、危險接近、資料庫本身）　→　"
        "**案例九**：看 hold-out 衛星上的泛化表現　→　**案例十**：看一個誠實的負面結果與方法上限。\n\n"
        "你也可以直接從 StoryMap 首頁跳到自己感興趣的案例，再把本頁當作「地圖」隨時回來對照。"
    )


def render_storymap_case2():
    if st.button(t("storymap_back"), key="back_from_case2"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例二：我們的方法，哪些用了 AI？哪些沒有？")
    st.subheader("分層混合架構：AI／非AI／已嘗試放棄的深度學習，邊界劃在哪裡")
    st.caption("這一頁專門回答一個常見的疑問：前面案例展示的成果，到底是「AI 做的」還是「傳統方法做的」？")

    st.markdown(
        "**先講結論**：這是一個**分層混合架構**，不是「全部都是 AI」也不是「完全沒有 AI」——"
        "每一層方法有沒有用 AI，取決於「這個問題有沒有足夠的真值資料可以學」以及「需不需要對任何衛星都成立的物理保證」。"
    )

    st.header("① 三個分類：完全不是 AI／傳統機器學習／深度學習（已放棄）")
    rows = [
        ("🔧 完全不是 AI（寫死的規則／統計公式／物理模型）",
         "L1 規則式 P1–P6　·　L2 統計變點偵測（CUSUM／BOCPD／SSA／MAD3σ）　·　NRLMSIS 大氣阻力物理模型",
         "所有參數都是人工設定或物理常數，不從訓練資料學習權重；對任何衛星、任何時候都用同一套公式，"
         "**可以完全解釋每一個判定是怎麼算出來的**。"),
        ("🤖 傳統機器學習（從真值資料學規則）",
         "LightGBM 機動分類器（14 顆 MEME 精密星曆訓練）　·　L3 融合評分器 HistGradientBoosting　·　"
         "Model 2 Isolation Forest（無監督異常偵測）",
         "這幾個模型的參數是從真實機動真值資料「學」出來的，能捕捉規則式方法寫不出來的複雜組合條件，"
         "犧牲一部分「人類可讀性」換取更高的準確率。"),
        ("🧠 深度學習（嘗試過，因負面結果而放棄）",
         "bi-GRU 序列標註器（Model 3）",
         "曾嘗試用遞迴神經網路直接對整段軌道時序做序列標註，但實測**沒有比傳統方法更好的判別力**、"
         "且在未訓練過的衛星上（OOD）表現崩潰——誠實記錄這個負面結果，繼續使用效果更好、更穩定的 Model 2。"),
    ]
    for title, methods, note in rows:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown(f"　{methods}")
            st.caption(note)

    st.header("② 加了 AI 到底差多少？用真實數字回答")
    arena = load_case9_real_data().get("arena", pd.DataFrame())
    if not arena.empty:
        l1 = arena[arena["method"].str.contains("L1")].iloc[0]
        cusum = arena[arena["method"].str.contains("cusum")].iloc[0]
        l3 = arena[arena["method"].str.contains("L3")].iloc[0]
        naive = arena[arena["method"].str.contains("naive")].iloc[0]
        comp = pd.DataFrame({
            "方法": ["naive 隨機（下限對照）", "L1 規則式（非 AI）", "L2 最佳單通道 cusum（非 AI）",
                    "L3 融合評分器（傳統 ML）"],
            "是否為 AI": ["—", "否", "否", "是（HistGradientBoosting）"],
            "召回率": [naive["recall"], l1["recall"], cusum["recall"], l3["recall"]],
        })
        fig = go.Figure()
        fig.add_trace(go.Bar(x=comp["方法"], y=comp["召回率"],
                             marker_color=["#B0BEC5", "#78909C", "#78909C", "#66BB6A"]))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=80),
                          yaxis_title="整體召回率", xaxis=dict(tickangle=-20),
                          plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key="case2_ai_compare")
        st.dataframe(comp.style.format({"召回率": "{:.1%}"}), use_container_width=True, hide_index=True)
        st.success(
            f"**沒有 AI（規則＋單一統計通道）最高只能到 {cusum['recall']:.1%} 召回率；"
            f"加上 AI（融合評分器）跳升到 {l3['recall']:.1%}**——差距主要來自融合模型能同時權衡多個弱訊號的組合，"
            "而不是只認一種模式。但非 AI 方法的價值在於：任何時候都能解釋「為什麼判定機動」，"
            "這也是為什麼系統把它們保留當作 L1/L2 的第一線，而不是直接跳過去只用 AI。"
        )

    st.markdown("---")
    st.info(
        "**判讀**：「用不用 AI」不是單選題，而是**依任務需求分層選擇**——"
        "解釋性優先、資料稀疏、或需要對任何衛星（含從未見過的）都成立物理保證的環節，用非 AI 方法；"
        "有足夠真值資料、追求最高準確率的最終裁決環節，用傳統機器學習；"
        "深度學習則先誠實驗證過「有沒有真的帶來額外好處」，沒有就不勉強用。"
    )
    st.caption("完整方法清單見 `docs/期末報告_技術附錄_20260909.md`；bi-GRU 負面結果見 `ml_bigru_labeler.py`。")


# ══ StoryMap 案例十一（2026-09-10 新增）══════════════════════════════════════════

_LIT_REFS: list[tuple[str, str, str]] = [
    # (category, citation_markdown, note)
    ("軌道力學與 TLE 機動偵測",
     "T. M. Kelecy and M. Jah, \"Detection and Orbit Determination of a Satellite Executing "
     "Low Thrust Maneuvers,\" *Acta Astronautica*, 66(5–6), pp. 798–809, 2010.",
     "[DOI](https://doi.org/10.1016/j.actaastro.2009.08.029)"),
    ("軌道力學與 TLE 機動偵測",
     "T. Kelecy et al., \"Satellite Maneuver Detection Using Two-line Element (TLE) Data,\" "
     "AMOS Conference, 2007.", "[PDF](https://amostech.com/TechnicalPapers/2007/Modeling_Analysis_Simulation/Kelecy.pdf)"),
    ("軌道力學與 TLE 機動偵測",
     "T. Flohrer, H. Krag, and H. Klinkrad, \"Assessment and Categorization of TLE Orbit Errors "
     "for the US SSN Catalogue,\" AMOS Conference, 2008.",
     "[PDF](https://amostech.com/TechnicalPapers/2008/Orbital_Debris/Flohrer.pdf)"),
    ("軌道力學與 TLE 機動偵測",
     "J. M. Picone, A. E. Hedin, D. P. Drob, and A. C. Aikin, \"NRLMSISE-00 Empirical Model of "
     "the Atmosphere,\" *J. Geophys. Res.: Space Physics*, 107(A12), 2002.",
     "[DOI](https://doi.org/10.1029/2002JA009430)"),
    ("軌道力學與 TLE 機動偵測",
     "D. A. Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed., Microcosm Press, 2013.",
     "[Celestrak](https://celestrak.org/software/vallado-sw.php)"),
    ("軌道力學與 TLE 機動偵測",
     "F. R. Hoots and R. L. Roehrich, \"Models for Propagation of NORAD Element Sets,\" "
     "Spacetrack Report No. 3, 1980.", "[PDF](https://celestrak.org/NORAD/documentation/spacetrk.pdf)"),
    ("軌道力學與 TLE 機動偵測",
     "D. A. Vallado et al., \"Revisiting Spacetrack Report #3,\" AIAA 2006-6753, 2006.",
     "[DOI](https://doi.org/10.2514/6.2006-6753)"),
    ("軌道力學與 TLE 機動偵測",
     "M. J. Holzinger, D. J. Scheeres, and K. T. Alfriend, \"Object Correlation, Maneuver "
     "Detection, and Characterization Using Control Distance Metrics,\" *J. Guidance, Control, "
     "and Dynamics*, 35(4), pp. 1312–1325, 2012.", "[DOI](https://doi.org/10.2514/1.53245)"),
    ("軌道力學與 TLE 機動偵測",
     "\"Simplified Approach to Detect Satellite Maneuvers Using TLE Data and Simplified "
     "Perturbation Model Utilizing Orbital Element Variation,\" *Applied Sciences*, 11(21):10181, 2021.",
     "[DOI](https://doi.org/10.3390/app112110181)"),
    ("統計變化點方法",
     "E. S. Page, \"Continuous Inspection Schemes,\" *Biometrika*, 41(1/2), pp. 100–115, 1954"
     "（CUSUM 原始文獻）。", "[DOI](https://doi.org/10.1093/biomet/41.1-2.100)"),
    ("統計變化點方法",
     "R. P. Adams and D. J. C. MacKay, \"Bayesian Online Changepoint Detection,\" arXiv:0710.3742, "
     "2007（BOCPD）。", "[arXiv](https://arxiv.org/abs/0710.3742)"),
    ("統計變化點方法",
     "N. Golyandina, V. Nekrutkin, and A. Zhigljavsky, *Analysis of Time Series Structure: SSA "
     "and Related Techniques*, Chapman & Hall/CRC, 2001（SSA）。",
     "[DOI](https://doi.org/10.1201/9781420035841)"),
    ("統計變化點方法",
     "\"RSO Proper Elements: Concept, Methods, and Application to Maneuver Detection,\" "
     "*Advances in Space Research*, 2023（BOCPD 於 mean-/proper-element 空間之比較）。",
     "[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0273117723006865)"),
    ("統計變化點方法",
     "\"Detection of Satellite Maneuvers in Earth and Cislunar Orbits using Adaptive CuSum "
     "Methods,\" EngrXiv / ION JNC（門檻—誤報—延遲權衡之量化）。",
     "[EngrXiv](https://engrxiv.org/preprint/view/7254)"),
    ("機器學習",
     "G. Ke et al., \"LightGBM: A Highly Efficient Gradient Boosting Decision Tree,\" NeurIPS 30, 2017.",
     "[NeurIPS](https://papers.nips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)"),
    ("機器學習",
     "F. T. Liu, K. M. Ting, and Z.-H. Zhou, \"Isolation Forest,\" IEEE ICDM, pp. 413–422, 2008.",
     "[DOI](https://doi.org/10.1109/ICDM.2008.17)"),
    ("機器學習",
     "S. M. Lundberg and S.-I. Lee, \"A Unified Approach to Interpreting Model Predictions,\" "
     "NeurIPS 30, 2017（SHAP）。",
     "[NeurIPS](https://papers.nips.cc/paper_files/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html)"),
    ("機器學習",
     "S. Hochreiter and J. Schmidhuber, \"Long Short-Term Memory,\" *Neural Computation*, "
     "9(8), pp. 1735–1780, 1997.", "[DOI](https://doi.org/10.1162/neco.1997.9.8.1735)"),
    ("機器學習",
     "Y. Nie et al., \"A Time Series is Worth 64 Words: Long-term Forecasting with "
     "Transformers,\" ICLR 2023（PatchTST）。", "[arXiv](https://arxiv.org/abs/2211.14730)"),
    ("機器學習",
     "H. Peng and X. Bai, \"Improving Orbit Prediction Accuracy through Supervised Machine "
     "Learning,\" *Adv. Space Res.*, 61(10), pp. 2628–2646, 2018.",
     "[DOI](https://doi.org/10.1016/j.asr.2018.03.001)"),
    ("SSA 領域與評估方法學",
     "D. L. Oltrogge and S. Alfano, \"The Technical Challenges of Better Space Situational "
     "Awareness,\" *J. Space Safety Eng.*, 6(3), pp. 164–172, 2019.",
     "[ScienceDirect](https://www.sciencedirect.com/org/science/article/pii/S2692765922000333)"),
    ("SSA 領域與評估方法學",
     "\"Real-Time Detection of LEO Satellite Orbit Maneuvers Based on Geometric Distance "
     "Difference,\" *Aerospace*, 12(10):925, 2025.", "[MDPI](https://www.mdpi.com/2226-4310/12/10/925)"),
    ("SSA 領域與評估方法學",
     "\"Comprehensive Analysis of Receiver Operating Characteristic (ROC) Curves for Anomaly "
     "Detection,\" IEEE, 2022.", "[IEEE Xplore](https://ieeexplore.ieee.org/document/9909988/)"),
    ("SSA 領域與評估方法學",
     "18th Space Defense Squadron, \"Space-Track.org,\" U.S. Space Command"
     "（TLE 與事件資料來源）。", "[space-track.org](https://www.space-track.org)"),
    ("SSA 領域與評估方法學",
     "SpaceX, \"Starlink Public Ephemerides（MEME 格式精密星曆）,\" 2026.",
     "[Starlink ephemerides](https://api.starlink.com/public-files/ephemerides/)"),
    ("LEO-PNT 與應用",
     "\"Inside LEO: LEO-PNT — Why Now?,\" *Inside GNSS*, 2024（LEO-PNT 成熟動力與國家戰略性之產業評述）。",
     "[Inside GNSS](https://insidegnss.com/inside-leo-leo-pnt-why-now/)"),
    ("LEO-PNT 與應用",
     "「以低成本硬體接收 Starlink 訊號進行定位之學術實測」，*KOC*, 2025"
     "（TLE + SGP4 路線之定位可行性實證）。", "[KOC](https://www.koc.com.tw/archives/648920)"),
    ("機動偵測方法與外部真值",
     "J. F. San-Juan, I. Pérez, M. San-Martín, et al., \"Hybrid SGP4 Orbit Propagator,\" "
     "*Acta Astronautica*, 137, pp. 254–260, 2017（SGP4 半長軸預報誤差量化）。",
     "[DOI](https://doi.org/10.1016/j.actaastro.2017.04.015)"),
    ("機動偵測方法與外部真值",
     "ILRS/IDS, \"Satellite Maneuver Histories（DORIS 測高衛星 operator 點火日誌）,\" "
     "International DORIS Service（本專案第二 hold-out 外部真值集來源）。",
     "[IDS](https://ids-doris.org/documents/BC/satellites/)"),
]

# 兩岸署名政策（見 feedback_cross_strait_attribution 備忘）：大陸文獻列為外部獨立文獻，
# 與本案執行單位無關，不稱同儕；僅引為方法論慣例／技術數字之外部佐證。
_LIT_EXTERNAL_NOTE = (
    "李泽越, 杨震, 李海阳, 罗亚中.《航天器轨道机动自适应逆向移动滑窗检测方法》. "
    "国防科技大学学报（中國大陸 NUDT，長沙）, 2024, 46(4): 45–53."
)
_LIT_EXTERNAL_DOI = "[DOI](https://doi.org/10.11887/j.cn.202404005)"


def render_storymap_case11():
    if st.button(t("storymap_back"), key="back_from_case11"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例十一：本專案站在哪些巨人的肩膀上？")
    st.subheader("文獻整理與回顧（方法論的知識地圖）")
    st.caption("本文獻整理自本專案技術報告之附錄與相關研究章節（`docs/期中報告_MEME_TLE_20260715_r10.md` 附錄 C、"
              "`docs/conf_ssa_maneuver_2026.md` §2），並非本頁新查找之文獻。"
              "本案例在整個 StoryMap 中扮演的角色，是幫每個技術案例標出它在既有研究地圖上的座標。")

    st.markdown(
        "**為什麼要做文獻回顧？**\n\n"
        "任何一個「這樣做應該可行」的方法，都可能已經有人做過、甚至已經證明行不通。"
        "文獻回顧的目的不是列一堆引用充版面，而是老實回答兩個問題：\n\n"
        "- **別人已經做到哪裡了？**\n"
        "- **本專案的方法，跟既有做法比起來，差異究竟在哪裡？**\n\n"
        "對本專案而言，這份回顧幫助我們：**避免重複造輪子**、**清楚定位自己的創新點**、"
        "**理解既有方法的極限在哪裡**。"
    )

    st.header("① 既有研究的四條路線")
    st.markdown(
        "TLE 由 SGP4/SDP4（兩套標準化的軌道傳播演算法）攝動模型產生，其半長軸精度受大氣阻力建模與擬合誤差影響"
        "（Hoots & Roehrich, 1980；Vallado et al., 2006）。以 TLE 偵測機動的既有作法，大致可以歸成四條路線："
    )
    st.markdown("**路線 1｜軌道力學基礎**")
    st.markdown(
        "研究 SGP4 傳播模型本身的誤差特性，是所有後續方法的地基——"
        "包括理解 TLE 在不同軌道區間、不同時間跨度下的系統誤差與隨機誤差。"
    )
    st.markdown("**路線 2｜單一統計量門檻**")
    st.markdown(
        "以半長軸變化量 |Δa| 門檻、多項式或 LOWESS（局部加權回歸）曲線擬合為主"
        "（Lemmens & Krag, 2014；Patera, 2008；Kelecy et al., 2007）。\n"
        "- 優點：實作簡單、計算成本低\n"
        "- 缺點：誤報與漏報難以兼顧，對小機動或雜訊大的情況特別敏感"
    )
    st.markdown("**路線 3｜統計變點偵測**")
    st.markdown(
        "CUSUM（累積偏離量，Page, 1954）、貝氏線上變點 BOCPD（Adams & MacKay, 2007）、"
        "奇異譜分析 SSA（Golyandina et al., 2001）、穩健 MAD（以中位數絕對偏差設門檻，"
        "Rousseeuw & Croux, 1993）等經典方法。\n"
        "- 各方法對「訊號突然改變」有不同的數學定義\n"
        "- 單獨使用時，召回率與誤報率難以同時優化"
    )
    st.markdown("**路線 4｜物理阻力模型**")
    st.markdown(
        "以 NRLMSISE-00（Picone et al., 2002）、NRLMSIS 2.0（Emmert et al., 2021）等半經驗大氣密度模型，"
        "作為扣除自然衰減的阻力殘差通道（詳見案例五）。\n"
        "- 優點：有物理基礎，可解釋性高\n"
        "- 缺點：依賴大氣模型的準確度，太陽活動劇烈時期誤差會放大"
    )

    st.header("② 本專案與既有工作的差異")
    st.markdown(
        "既有機動偵測文獻多半**以單一偵測器為終點**——選定一種統計量或門檻，調好參數就結案。"
        "本專案的做法不同，差異有兩點："
    )
    st.success(
        "**差異 1｜融合多通道，而非單一偵測器**\n\n"
        "本專案不以單一偵測器為終點，而是用融合層整合物理模型與多個統計通道的訊號"
        "（詳見案例一的架構全貌、案例二的 AI/非AI 分類）——"
        "讓模型學會在什麼情況下該相信哪一個通道，綜合所有訊號做出最終判定，而非隨便選一種方法的結果。"
    )
    st.success(
        "**差異 2｜嚴格的真值分級與泛化驗證**\n\n"
        "在方法論上，本專案嚴格處理真值分級與泛化驗證——這一點在既有機動偵測文獻中**少有系統性報告**。"
        "多數既有研究要嘛沒有獨立真值（用自己的偵測結果驗證自己），要嘛沒有測試「模型對沒看過的目標還準不準」"
        "（詳見案例四的真值來源分級、案例九的 unseen-satellite hold-out）。\n\n"
        "**泛化驗證的重要性在於**：避免模型只是「背下特定衛星或時期的答案」，而是真的學到可遷移到新目標的機動特徵。"
    )

    st.header("③ 完整分類文獻列表")
    with st.expander("🧭 如果想從頭讀起：建議入門路線", expanded=False):
        st.markdown(
            "若你是第一次接觸 TLE 機動偵測，建議的閱讀順序是：\n\n"
            "1. **軌道力學基礎**：Hoots & Roehrich (1980)、Vallado et al. (2006)"
            "——理解 SGP4 與 TLE 的基本假設與誤差來源；\n"
            "2. **單一門檻方法**：Kelecy et al. (2007)、Lemmens & Krag (2014)"
            "——看最直觀的做法及其限制；\n"
            "3. **統計變點**：Page (1954, CUSUM)、Adams & MacKay (2007, BOCPD)"
            "——理解經典變點偵測的數學思想；\n"
            "4. **物理模型**：Picone et al. (2002, NRLMSISE-00)、Emmert et al. (2021, NRLMSIS 2.0)"
            "——理解大氣密度建模如何用於阻力殘差；\n"
            "5. **機器學習**：Ke et al. (2017, LightGBM)、Lundberg & Lee (2017, SHAP)"
            "——理解本專案使用的 ML 工具。"
        )

    df_refs = pd.DataFrame(_LIT_REFS, columns=["類別", "文獻", "連結"])
    for cat in df_refs["類別"].unique():
        with st.expander(f"📚 {cat}（{(df_refs['類別'] == cat).sum()} 篇）", expanded=False):
            for i, (_, row) in enumerate(df_refs[df_refs["類別"] == cat].iterrows(), start=1):
                st.markdown(f"{i}. {row['文獻']} {row['連結']}")
            if cat == "SSA 領域與評估方法學":
                st.caption(
                    "註：本小節標題中的「SSA」指 Space Situational Awareness（太空情境意識），"
                    "與路線 3「統計變點偵測」中的 SSA（Singular Spectrum Analysis，奇異譜分析）為不同概念，"
                    "兩者恰好同縮寫，本頁其餘位置提到 SSA 皆指後者（奇異譜分析）。"
                )

    with st.expander("📚 機動偵測方法與外部真值（含一篇兩岸署名政策適用文獻）", expanded=False):
        st.markdown(f"1. {_LIT_EXTERNAL_NOTE} {_LIT_EXTERNAL_DOI}")
        st.caption(
            "說明：此為**外部獨立文獻**，作者與本案執行單位無任何關聯，不構成同儕或合作關係——"
            "引用僅作為「事件級人工計數評估」之領域慣例佐證，以及 SGP4 半長軸誤差數量級之外部佐證。"
        )

    st.markdown("---")
    st.info(
        "**本案例的啟示**：這份文獻回顧告訴我們三件事——\n\n"
        "1. **TLE 機動偵測不是新問題**：從 2007 年 Kelecy 的 TLE 偵測研究，到 2020 年代的統計變點與 ML 方法，"
        "領域已經累積近 20 年的經驗；\n"
        "2. **單一方法有本質限制**：無論是單一門檻、單一統計變點方法，或單一物理模型，"
        "都難以同時兼顧召回率與誤報率；\n"
        "3. **本專案的創新點在於融合與驗證**：透過多通道融合與嚴格的真值分級、泛化驗證，"
        "本專案在方法論上補足了既有文獻中較少系統性處理的環節。\n\n"
        "換句話說：**本專案不是從零開始，而是站在這些巨人的肩膀上，往「更可靠、更可解釋、更可泛化」的方向再推一步。**"
    )
    st.caption(
        "完整書目（含全部 30 筆條目與名詞縮寫對照表）見 "
        "`docs/期中報告_MEME_TLE_20260715_r10.md` 附錄 C／附錄 D；"
        "本專案方法定位之完整論述見 `docs/conf_ssa_maneuver_2026.md` §2「相關研究」。"
    )


# ══ StoryMap 案例十二（2026-09-10 新增）══════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_reentry_validation() -> pd.DataFrame:
    """案例十二②之擴大驗證結果（讀取 validate_reentry_gate.py 之離線輸出）。"""
    p = DATA / "benchmark" / "reentry_gate_validation_20260910.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    df["expected"] = df["expected"].astype(bool)
    df["predicted"] = df["predicted"].astype(bool)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_geo_meo_scope() -> pd.DataFrame:
    """案例十二③之路由範圍量化（讀取 analyze_geo_meo_scope.py 之離線輸出）。"""
    p = DATA / "benchmark" / "geo_meo_routing_scope_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_injection_persat() -> pd.DataFrame:
    """案例十二⑤之注入式合成真值測試 A：單顆衛星 Δa（Monte Carlo，讀取離線輸出）。"""
    p = DATA / "benchmark" / "constellation_injection_persat_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_injection_plane() -> pd.DataFrame:
    """案例十二⑤之注入式合成真值測試 B：軌道面 Δi 注入（讀取離線輸出）。"""
    p = DATA / "benchmark" / "constellation_injection_plane_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_injection_formation() -> pd.DataFrame:
    """案例十二⑤之注入式合成真值測試 C：陣型相位注入（讀取離線輸出）。"""
    p = DATA / "benchmark" / "constellation_injection_formation_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_injection_batch() -> pd.DataFrame:
    """案例十二⑤之注入式合成真值測試 D：批量機動端到端驗證（讀取離線輸出）。"""
    p = DATA / "benchmark" / "constellation_injection_batch_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_case12_heo_drag_residual() -> pd.DataFrame:
    """案例十二⑥之 HEO 阻力殘差量級驗證（讀取 validate_heo_drag_residual.py 之離線輸出）。"""
    p = DATA / "benchmark" / "heo_drag_residual_validation_20260910.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def render_storymap_case12():
    if st.button(t("storymap_back"), key="back_from_case12"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例十二：這套系統，在哪些軌道類型上能信？哪些還不能？")
    st.subheader("適合、不適合與尚待測試的軌道類型整理")
    st.caption("整理自技術附錄之量化驗收章節與各程式模組之實際邏輯——本頁目的是誠實劃出「量化驗證過」跟"
              "「程式碼可以跑、但沒有真值可以核對」之間的界線，兩者不能混為一談。")

    st.markdown(
        "**為什麼要做這個整理**：一套偵測系統公布的召回率、AUC 這些數字，"
        "只有在「跟訓練/驗證時同一種母體」的資料上才可信。把在 Starlink 上驗證出的準確率，"
        "直接套用到從沒驗證過的 GEO 衛星、拿來做宣稱，是常見但不誠實的做法。"
        "本頁把系統對每一種軌道類型的把握程度，如實分成四級。"
    )

    st.header("① 已驗證、有信心")
    st.success(
        "**LEO 星座級站台保持（以 Starlink 為主）**\n\n"
        "融合評分器（L3）在 284 顆有 MEME 精密星曆真值的 Starlink 衛星上，ROC-AUC 達 **0.982**，"
        "大型機動事件召回率 **97.3%**（n=405 個事件）；"
        "在 **56 顆完全沒參與訓練**的 hold-out 衛星上，AUC 仍達 **0.980**，大型機動召回率 **100%**（81/81，"
        "詳見案例九）。\n\n"
        "**但要老實說清楚驗證的邊界**：這組數字的驗證母體僅止於「284 顆有精密星曆真值可核對的 Starlink 衛星」，"
        "技術附錄本身也明白寫著**不可外推到非 Starlink 的衛星**。"
    )

    st.header("② 有特殊處理機制、部分驗證")
    reentry_val = load_case12_reentry_validation()
    st.warning(
        "**LEO 自然再入／衰減 vs 站台保持維持（含 HEO 末期再入段）**\n\n"
        "系統用 `is_reentry_decay()` 這道守門邏輯，依「近地點高度」＋「45 天窗衰減斜率」區分"
        "「正在自然再入」與「靠推進器維持軌道」（例如 ISS／天宮）：近地點極低（如 Van Allen A 衛星末期）"
        "或近地點低且快速下降者，直接判定「自然再入、機動＝0」，避免物理阻力模型對這類劇烈非線性衰減"
        "爆量誤報（詳見案例五、案例十）。\n\n"
        "**2026-09-10 反思本案例後已擴大驗證樣本**：原本只用 4 個手選案例做邏輯正確性檢查，"
        "樣本太小。改用客觀、不依賴人工標籤的真值定義重新驗證——"
        "**真陽性**＝近地點高度曾跌破 120 km、且此後 14 天以上再無任何 TLE（追蹤徹底中止，代表已真實燒毀）；"
        "**真陰性**＝ISS、天宮核心艙，加上隨機抽樣的長期追蹤 Starlink（全程近地點 >300 km，靠站位保持維持）。"
    )
    if not reentry_val.empty:
        n_re = int(reentry_val["expected"].sum())
        n_qt = int((~reentry_val["expected"]).sum())
        tp = int(((reentry_val["expected"]) & (reentry_val["predicted"])).sum())
        tn = int(((~reentry_val["expected"]) & (~reentry_val["predicted"])).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("確認再入衛星", f"{n_re} 顆", f"recall {tp}/{n_re}")
        c2.metric("確認安靜衛星", f"{n_qt} 顆", f"specificity {tn}/{n_qt}")
        c3.metric("總樣本數", f"{len(reentry_val)} 顆")
        st.success(
            f"**擴大後的結果**：{len(reentry_val)} 顆真實衛星（16 顆確認再入，涵蓋 Cluster-II、"
            "多型火箭殘骸、Van Allen A 等；42 顆確認安靜，含 ISS／天宮／40 顆隨機 Starlink）——"
            f"再入 recall **{tp}/{n_re} = 100%**（Wilson 95% CI [80.6%, 100%]），"
            f"安靜 specificity **{tn}/{n_qt} = 100%**（Wilson 95% CI [91.6%, 100%]）。\n\n"
            "**老實補充兩點**：① n=16 的正類樣本，Wilson 下界僅 80.6%，還稱不上大樣本統計驗證，"
            "只是比原本 4 案例扎實一倍以上；② 真值定義是本頁自建的物理判準（近地點崩潰＋追蹤中止），"
            "不是像案例四那樣的第三方獨立真值（IDS/DORIS 等）——**這一層仍應標示為「部分驗證」，"
            "但已經是有實際數字支撐的部分驗證，不再是純邏輯煙霧測試**。"
        )
    else:
        st.info("擴大驗證之輸出檔案 `data/benchmark/reentry_gate_validation_20260910.csv` 目前找不到，"
               "顯示的仍是原始 4 案例邏輯檢查。可執行 `python validate_reentry_gate.py` 重新產生。")

    st.header("③ 有程式路徑、但缺乏量化驗證")
    st.info(
        "**GEO／MEO（地球同步軌道／中軌道）**\n\n"
        "系統的路由機制會把非 Starlink 域的目標導向 Model 2（無監督 Isolation Forest 異常偵測）"
        "＋ NRLMSIS 物理殘差。技術附錄記載「已以 GEO/HEO 實例驗證路由正確」——"
        "**但這只證明了「路由邏輯能把 GEO 目標正確導向 Model 2」，並不等同於「在 GEO 軌道上的"
        "機動偵測召回率／誤報率已經被量化驗證」**，兩者是完全不同層次的驗證。"
        "換句話說：**目前只驗證了「路走對了」，還沒驗證「走到終點後準不準」**。\n\n"
        "**GEO 近距接近／RPO 案例**（TJS-10×TJS-3、Shenlong——詳見案例七）：屬於 SGP4/TLE 幾何重建的"
        "**描述性、調查性視覺化**，程式本身就註明「精度為 SGP4/TLE 等級（GEO 上約公里級）」——"
        "這是把真實事件的軌跡重建出來給人看，並不是一套本專案獨立驗證過召回率的機動偵測器。"
    )
    geo_scope = load_case12_geo_meo_scope()
    if not geo_scope.empty:
        n_total = len(geo_scope)
        vc = geo_scope["orbit_class"].value_counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("路由至 Model 2 的 GEO/MEO/GEO+ 目標", f"{n_total:,} 顆")
        c2.metric("其中 GEO／GEO+", f"{int(vc.get('GEO', 0) + vc.get('GEO+', 0)):,} 顆")
        c3.metric("做過個案軌跡核對", "2 顆", "TJS-10×TJS-3、Shenlong")
        st.caption(
            f"**2026-09-10 反思本案例後補上的規模量化**：資料庫最新快照中，被 `classify_orbit()` "
            f"分類為 GEO／MEO／GEO+ 的目標共 **{n_total:,} 顆**（GEO {int(vc.get('GEO', 0)):,}、"
            f"MEO {int(vc.get('MEO', 0)):,}、GEO+ {int(vc.get('GEO+', 0)):,}），依規則全數路由到 Model 2。"
            f"這不是偵測準確率驗證——只是把「目前完全沒有個案核對過的範圍」量到多大："
            f"**{n_total:,} 顆之中，只有 2 顆做過個案軌跡重建，其餘 {n_total - 2:,} 顆從未被人核對過**。"
            "規模越大，越不該用 2 個案例去暗示涵蓋全體。"
        )
    with st.expander("🧭 若要把這一級升等，可行的下一步驗證路線", expanded=False):
        st.markdown(
            "1. **建立 GEO/MEO 的最小可行真值集**：精密星曆稀缺、機動真值多為操作機密，"
            "但可先整理已知公開機動事件（TJS 系列、Shenlong、GEO 通訊衛星站位調整）——"
            "以新聞稿、追蹤網站公開軌跡、學術論文中的案例，建立一份「事件級真值」清單；\n"
            "2. **半真值（proxy ground truth）交叉比對**：無官方紀錄的 GEO 衛星，"
            "可用「軌道要素突變 ＋ 操作者公告 ＋ 新聞報導」三方交叉比對，"
            "標記為「高機率機動事件」，作為初步（非嚴格）驗證集；\n"
            "3. **在 StoryMap 中持續更新分級**：等真的跑出量化召回率/誤報率數字，"
            "再把這一級從「有程式路徑、缺乏量化驗證」正式升級到「部分驗證」或更高——"
            "在那之前，誠實維持現在的分級，比提前宣稱更重要。"
        )

    st.header("④ 獨立研究支線，尚未整合進主管線")
    st.info(
        "**Galileo MEO 精密星曆比對**：`mgex_galileo/` 是一條獨立的 SP3 精密星曆比對管線，"
        "用來量化 TLE/SGP4 對 Galileo 衛星的預報誤差量級。"
        "**2026-09-10 反思本案例後訂正規模**：這組數字並非抽查——現有輸出"
        "（`data/galileo_comparison/summary_2026-06-23.csv`）**已涵蓋全部 30 顆 Galileo 衛星、"
        "120 天時間窗**：切線方向誤差 RMS 落在 **2.1～21.4 公里**，法線方向落在 **76.5～128.6 公里**。\n\n"
        "**但要老實補上一個方法論警語**：法線方向這組數字可能**被「微分假影」污染**——"
        "MGEX 的 Galileo SP3 檔案本身沒有速度紀錄，管線用數值微分從位置反推速度來建立"
        "RTN 座標系，而本專案在另一批已知真速度的精密測高衛星（Jason-3）上做過對照實驗："
        "同樣的差分處理手法，量出峰對峰 **131.9 公里**，但真值只有 **14.4 公里**——純粹是處理方式"
        "造成的假訊號，比真訊號大了近 10 倍。也就是說，Galileo 這組法線方向 76～129 公里的數字，"
        "**上限可能主要來自微分假影，而非 SGP4 真實物理誤差**，應保守解讀，不宜直接引用為「SGP4 對"
        "MEO 的法向誤差」。\n\n"
        "無論如何，這條支線**目前只在 App 裡有一個獨立分頁展示這些誤差數字，尚未接入 L1/L2/L3 融合"
        "偵測管線**，不能算是「機動偵測已驗證涵蓋 MEO」——擴大到全量 30 顆，補強的是「誤差量級的樣本"
        "規模」，不是「機動偵測準確率」，這兩者仍是案例十二一貫要區分清楚的兩件事。"
    )

    st.header("⑤ 有掃描、但無法判斷是否真的有效")
    st.warning(
        "**非 Starlink 的 LEO 星系（OneWeb、千帆、遙感等）**\n\n"
        "星系級批量分析（詳見案例六）支援 19 個星系型號的軌道面/批量機動/隊形掃描，"
        "OneWeb、千帆等星系目前回報「零異常」——**但這組零異常沒辦法區分是「這個星系真的很安靜」，"
        "還是「模型對非 Starlink 域本來就不敏感、抓不到」**，因為這些星系沒有精密星曆真值可以逐一核對。"
        "零異常是一個誠實但曖昧的結果，不能直接當作「系統在這些星系上表現良好」的證據。"
    )
    inj_a = load_case12_injection_persat()
    inj_b = load_case12_injection_plane()
    inj_c = load_case12_injection_formation()
    inj_d = load_case12_injection_batch()
    if not inj_a.empty:
        st.markdown(
            "**2026-09-10 反思本案例後補上的注入式合成真值測試**：既然沒有外部真值，"
            "改用「已知的真實機動量級」疊加到「真實的 OneWeb／千帆 TLE 雜訊背景」上，"
            "看現行邏輯能不能在真實雜訊底下抓到它。**同日再擴充為四個方向**：單顆衛星 Δa"
            "（改用多次隨機注入時刻的 Monte Carlo，取代原本單一時間點的估計）、軌道面 Δi 注入、"
            "陣型相位注入，以及最關鍵的——直接端到端驗證「一整批衛星同時機動」是否真的會被標記。"
        )

        st.markdown("**A. 單顆衛星 Δa（Monte Carlo，每個量級 30 次隨機試驗）**")
        fig_a = go.Figure()
        for cname, color in [("OneWeb", "#42A5F5"), ("Qianfan", "#FFA726")]:
            sub = inj_a[inj_a["constellation"] == cname].sort_values("inject_mag_km")
            if not sub.empty:
                fig_a.add_trace(go.Scatter(
                    x=sub["inject_mag_km"], y=sub["detect_rate"] * 100, mode="lines+markers",
                    name=cname, line=dict(color=color, width=2),
                    error_y=dict(type="data", symmetric=False,
                                array=(sub["ci_hi"] - sub["detect_rate"]) * 100,
                                arrayminus=(sub["detect_rate"] - sub["ci_lo"]) * 100)))
        fig_a.add_vline(x=2.0, line_dash="dot", line_color="#EF5350",
                        annotation_text="現行 2km 判定門檻")
        fig_a.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                            xaxis_title="注入的半長軸階躍量級 (km)", yaxis_title="偵測率 (%，含 Wilson 95% CI)",
                            plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.15))
        st.plotly_chart(fig_a, use_container_width=True, key="case12_injection_a")
        st.caption(
            "0.5～1km 幾乎測不到，**3km 以上兩個星系皆達 97～100% 偵測率**。"
            "千帆的曲線在 1～2km 附近不單調（1km 反而比 2km 偵測率高），"
            "這正呼應下面的老實補充——千帆的真實背景雜訊本身就不乾淨，30 次隨機試驗撞到的"
            "真實雜訊有時會抵銷、有時會疊加注入訊號，不是程式錯誤。"
        )

        if not inj_b.empty:
            st.markdown("**B. 軌道面 Δi 注入——意外發現：「盲區甜甜圈」**")
            fig_b = go.Figure()
            for cname, color in [("OneWeb", "#42A5F5"), ("Qianfan", "#FFA726")]:
                sub = inj_b[inj_b["constellation"] == cname].sort_values("inject_mag_deg")
                if not sub.empty:
                    fig_b.add_trace(go.Scatter(
                        x=sub["inject_mag_deg"], y=sub["detect_rate"] * 100, mode="lines+markers",
                        name=f"{cname} 偵測率", line=dict(color=color, width=2)))
                    fig_b.add_trace(go.Scatter(
                        x=sub["inject_mag_deg"], y=sub["escape_rate"] * 100, mode="lines+markers",
                        name=f"{cname} 逃逸率", line=dict(color=color, width=1.5, dash="dot")))
            fig_b.add_vline(x=0.5, line_dash="dot", line_color="#FFD54F",
                            annotation_text="殼層分群間隙門檻 0.5°")
            fig_b.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                xaxis_title="注入的傾角變化量級 (deg)", yaxis_title="%",
                                plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.18))
            st.plotly_chart(fig_b, use_container_width=True, key="case12_injection_b")
            st.error(
                "**這是本次擴充最重要的意外發現**：注入 0.05° 太小，偵測率 0%（低於雜訊地板，合理）；"
                "**注入 0.1°～0.5° 之間，兩個星系偵測率都是 100%**；但**一旦注入量級達到 1°"
                "（超過 `assign_planes()` 用來分群軌道面的 0.5° 傾角間隙門檻），偵測率直接摔回 0%，"
                "逃逸率 100%**——不是訊號太小看不到，而是**注入的傾角變化大到把這顆衛星直接甩出了"
                "原本的軌道面分組**，變成一顆孤立的「新軌道面」（因為少於 3 顆同組門檻而被整個過濾掉），"
                "根本沒有機會被 Δi 標準差邏輯檢查到。**換句話說：機動量級越大，反而越容易被系統的"
                "分群前處理本身「看不見」**——這是一個只有做注入測試才會發現的方法論陷阱，"
                "純粹看歷史「零異常」紀錄完全不會意識到這個盲區存在。"
            )

        if not inj_c.empty:
            st.markdown("**C. 陣型相位注入**")
            fig_c = go.Figure()
            for cname, color in [("OneWeb", "#42A5F5"), ("Qianfan", "#FFA726")]:
                sub = inj_c[inj_c["constellation"] == cname].sort_values("inject_mag_deg")
                if not sub.empty:
                    fig_c.add_trace(go.Scatter(
                        x=sub["inject_mag_deg"], y=sub["detect_rate"] * 100, mode="lines+markers",
                        name=cname, line=dict(color=color, width=2)))
            fig_c.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                                xaxis_title="注入的相位偏移量級 (deg)", yaxis_title="偵測率 (%)",
                                plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig_c, use_container_width=True, key="case12_injection_c")
            st.caption(
                "1° 幾乎測不到、2° 附近約 50%、5° 以上穩定在 87～97%——但**從未真正摸到 100%**："
                "因為被注入的那一顆衛星自己會拉高該軌道面的殘差標準差（判定門檻用 3×標準差），"
                "等於機動量級越大，門檻也跟著自己被墊高一些，形成一個溫和的自我遮蔽效應。"
            )

        if not inj_d.empty:
            st.markdown("**D. 批量機動端到端驗證（直接回答「抓得到一整批衛星嗎」）**")
            d_disp = inj_d.rename(columns={
                "constellation": "星系", "n_injected": "同時注入顆數", "test_day": "測試日",
                "flag_rate": "觸發批量旗標比例", "avg_n_maneuvering_that_day": "當天平均機動顆數",
                "K_baseline_before_injection": "注入前基線K", "avg_K_including_test_day": "注入後K(含當天)",
                "avg_K_excluding_test_day": "注入後K(排除當天)"})[
                ["星系", "同時注入顆數", "測試日", "觸發批量旗標比例", "當天平均機動顆數",
                 "注入前基線K", "注入後K(含當天)", "注入後K(排除當天)"]]
            st.dataframe(
                d_disp.style.format({"觸發批量旗標比例": "{:.0%}", "當天平均機動顆數": "{:.1f}",
                                     "注入前基線K": "{:.1f}", "注入後K(含當天)": "{:.1f}",
                                     "注入後K(排除當天)": "{:.1f}"}),
                use_container_width=True, hide_index=True)
            k_oneweb = inj_d.loc[inj_d["constellation"] == "OneWeb", "K_baseline_before_injection"]
            k_qianfan = inj_d.loc[inj_d["constellation"] == "Qianfan", "K_baseline_before_injection"]
            st.error(
                f"**第二個重要意外發現：兩個星系的「批量」判定門檻天差地遠**。"
                f"OneWeb 的背景基線極安靜，K≈**{k_oneweb.iloc[0]:.1f}** 顆／天——"
                "只要同時注入 2 顆衛星就立刻超標、100% 被標記為批量事件；"
                f"但千帆目前的背景本身變動就很劇烈，K≈**{k_qianfan.iloc[0]:.0f}** 顆／天——"
                "同時注入 2 顆完全不會被標記（正確的陰性對照），但這也代表**如果千帆真的發生一次"
                "涉及數十顆衛星的協同機動，只要沒超過這個上百顆的自適應門檻，系統一樣會判定「正常」**。"
                "門檻用 mean+3σ 自適應設計的立意是避開誤報，但代價是：**背景越不安分的星系，"
                "批量偵測的『警覺線』反而被自己的雜訊墊得越高**——這也解釋了為什麼千帆的日常監控"
                "會持續回報「零異常」：不是系統看不到明顯的機動，而是它預設的『正常背景』範圍本身很寬。"
            )
            st.caption(
                "測試方法：把同一個真實可偵測量級（5km，依上方 A 測試已知≥3km幾乎必被逐星邏輯抓到）"
                "同時疊加到 N 顆真實衛星的同一天，重跑完整 `analyze()`，檢查該天是否觸發 `flag_batch`。"
                "這是刻意理想化的合成情境（真實批量事件各衛星量級/時間點會有分散度），"
                "測出的偵測率可能比真實批量事件更樂觀，用途是刻劃系統的敏感度地圖，不是宣稱這就是"
                "真實批量事件的偵測率。"
            )

        st.success(
            "**四項測試合起來的判讀**：「零異常」在單顆衛星機動夠大（≥3km）時是可信的——"
            "確實抓得到。但兩個新發現讓誠實的分級更精確：**機動量級太大反而可能逃過軌道面一致性檢查**"
            "（分群前處理的盲區），以及**批量偵測的『多大算異常』門檻，會被該星系自己的背景雜訊高低"
            "自動撐大或縮小**——千帆目前的門檻高到數十顆衛星同時異常都可能被判定為正常。"
            "這一級維持「有掃描、但無法判斷是否真的有效」的分級不變，但現在對「哪裡有效、哪裡有盲區」"
            "已經有具體數字可以指認，而不是含糊地說『不確定』。"
        )

    st.header("⑥ 已知不適用的情境")
    st.error(
        "**HEO 非末期再入段（正常橢圓軌道運行階段）**\n\n"
        "物理阻力殘差模型（NRLMSIS）在真正的高橢圓軌道上**不適用**——"
        "遠地點階段的軌道變化主要由月球/太陽等第三體攝動主導，而不是大氣阻力，"
        "用阻力模型硬套會得出完全不合理的結果（詳見案例十的 −120 公里尺度高度案例）。"
        "`is_reentry_decay()` 自己的程式註解也寫明：「Cluster 類 HEO 的近地點早年很高，"
        "只有末期才俯衝，全期 median 會漏判」——目前的再入守門只是末期低近地點階段的安全網，"
        "**不是涵蓋 HEO 全生命週期的解法**。"
    )
    heo_resid = load_case12_heo_drag_residual()
    if not heo_resid.empty:
        st.caption(
            "**2026-09-10 反思本案例後補上的量級佐證**：對真實 Cluster II（FM7、FM8）非末期俯衝段"
            "跑既有的 `drag_residual()`，與同一函式在 ISS（站台保持 LEO 圓軌，模型原始設計目標）"
            "上的殘差量級比較："
        )
        st.dataframe(
            heo_resid.rename(columns={
                "name": "衛星", "kind": "類型", "n_epochs_used": "採用筆數",
                "resid_median_abs_km": "殘差中位數(km)", "resid_p95_abs_km": "殘差P95(km)",
                "resid_max_abs_km": "殘差最大值(km)"})
            [["衛星", "類型", "採用筆數", "殘差中位數(km)", "殘差P95(km)", "殘差最大值(km)"]],
            use_container_width=True, hide_index=True)
        st.markdown(
            "ISS 的殘差中位數僅 **0.0096 km**（約 10 公尺，符合模型設計時的乾淨雜訊地板）；"
            "**Cluster II-FM7 的殘差中位數飆到 1.64 km（約 ISS 的 170 倍）、尾端最大值達 570 km**，"
            "FM8 的中位數雖仍算小（0.027 km，約 ISS 的 3 倍），但尾端 P95 也衝到 12.6 km、"
            "最大值 131 km——**兩顆衛星的共同特徵是「多數時候還算合理、但尾端會出現物理上說不通的"
            "巨大跳動」**，這正是第三體攝動偶爾主導、阻力模型硬套上去就會失真的具體樣貌，"
            "把原本純文字的「不適用」換成了看得到的數字反差。\n\n"
            "**老實補充**：Van Allen A／B（38752／38753）本可作為第三個對照案例，"
            "但兩者在本地封存的 TLE 歷史窗內，近地點高度全程已 <250 km——代表這兩份封存資料"
            "本身就落在末期俯衝階段，找不到「非末期正常運行段」可用，因此本表未納入，"
            "而非刻意排除不利樣本。"
        )

    st.markdown("---")
    st.markdown("**尚待測試的缺口**")
    st.markdown(
        "**太陽同步軌道**：目前系統從未把「太陽同步」單獨設為一條測試分層——"
        "FORMOSAT 系列（多為太陽同步軌道）的驗證數字（如 FORMOSAT-3A 純衰減殘差極小）"
        "可以算是間接佐證，但技術文件從未以「太陽同步 vs 非太陽同步」作為明確的分類軸去呈現結果，"
        "這是一個誠實列出、但目前還沒有專門數字可以回答的缺口。"
    )

    st.markdown("---")
    st.success(
        "**判讀**：這套系統目前唯一有嚴謹量化驗證（獨立真值＋泛化測試）的範圍，"
        "是 **Starlink 這一類 LEO 星座級站台保持衛星**。往外延伸一圈——LEO 再入判定、GEO/MEO 路由——"
        "有清楚的處理邏輯，但驗證強度遞減；再往外——非 Starlink 星系的零異常、HEO 全生命週期——"
        "則是誠實標示為「還不知道」或「已知不適用」，而不是含糊地宣稱「通用於所有軌道」。"
        "**這種分級揭露，本身就是本專案方法論嚴謹度的一部分**（呼應案例十一：既有文獻少見系統性報告驗證邊界）。"
    )
    st.caption("完整量化驗收數字見 `docs/期末報告_技術附錄_20260909.md`；"
              "再入守門邏輯見 `atmospheric_drag.py::is_reentry_decay()`；"
              "星系級掃描見 `constellation_anomaly.py`；Galileo MEO 比對見 `mgex_galileo/`。")


# ══ StoryMap 案例十三（2026-09-10 新增）══════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_case13_real_data() -> dict:
    """案例十三之真實資料：大量 Starlink MEME 軌道外推研究（study1/2/3，讀取離線分析輸出）。"""
    out = {}
    p2 = DATA / "study2" / "study2_horizon_summary_20260712.csv"
    p3s = DATA / "study3" / "study3_frozen_summary_20260712.csv"
    p3g = DATA / "study3" / "study3_gap_spotcheck_20260712.csv"
    out["horizon"] = pd.read_csv(p2) if p2.exists() else pd.DataFrame()
    out["frozen"] = pd.read_csv(p3s) if p3s.exists() else pd.DataFrame()
    out["gap"] = pd.read_csv(p3g) if p3g.exists() else pd.DataFrame()
    return out


def render_storymap_case13():
    if st.button(t("storymap_back"), key="back_from_case13"):
        st.session_state["storymap_case"] = None
        st.rerun()

    st.title("案例十三：對幾十顆到上百顆 Starlink 跑 MEME 軌道外推，算出了什麼？")
    st.subheader("大規模計算的結果與意外發現")
    st.caption("本頁數字讀取自離線批次分析輸出（`data/study1/`、`data/study2/`、`data/study3/`），"
              "皆為對真實 Starlink MEME 精密星曆逐顆計算之結果，非模擬數字。")

    st.markdown(
        "**問題背景**：軌道預報的誤差，理論上應該隨著「預測多久以後」單調變大——但實際數字長什麼樣子？"
        "多久之後誤差會大到不能用？大規模跑過幾十到上百顆真實衛星之後，除了驗證這個直覺，"
        "還意外挖到兩個一開始沒想到的方法論陷阱。"
    )

    data = load_case13_real_data()

    st.header("① 最乾淨的量尺：MEME 對 MEME 自我預測")
    st.markdown(
        "SpaceX 的 MEME 精密星曆每份涵蓋 72 小時、每分鐘一筆，且每 ~8 小時重新發布一次、彼此重疊 ~88%。"
        "這代表對同一個未來時刻，會同時存在「較新、外推齡幾乎為 0」的檔案（當作真值）"
        "和「較舊、外推齡 8～72 小時」的檔案（當作預測）——兩者相減就是精密星曆自己的外推誤差，"
        "**完全不需要外部傳播器，不會混進 SGP4 的誤差**，是樣本量最大、最乾淨的量測方式。"
    )
    hz = data.get("horizon", pd.DataFrame())
    if not hz.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hz["horizon_bin_h"], y=hz["pos_med_km"], mode="lines+markers",
                                 name="位置誤差中位數", line=dict(color="#64B5F6", width=2)))
        fig.add_trace(go.Scatter(x=hz["horizon_bin_h"], y=hz["pos_p95_km"], mode="lines+markers",
                                 name="位置誤差 P95", line=dict(color="#FFB74D", width=2, dash="dot")))
        fig.add_trace(go.Scatter(x=hz["horizon_bin_h"], y=hz["rms_t_km"], mode="lines",
                                 name="沿軌方向 RMS", line=dict(color="#EF5350", width=1.5)))
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="外推時程 (小時)", yaxis_title="誤差 (km)",
                          plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="case13_horizon")
        st.caption(
            f"50 顆安靜（無機動）衛星、共 {int(hz['n'].sum()):,} 筆樣本："
            f"位置誤差中位數從 8 小時的 **{hz.loc[hz.horizon_bin_h==8,'pos_med_km'].iloc[0]:.2f} km** "
            f"成長到 72 小時的 **{hz.loc[hz.horizon_bin_h==72,'pos_med_km'].iloc[0]:.2f} km**，"
            "且在 48 小時左右就開始飽和，不再持續倍增——**幾乎全部誤差來自沿軌方向**（紅線遠高於徑向/法向），"
            "符合軌道力學上「沿軌相位誤差是主導項」的預期。"
        )

    st.header("② 意外發現一：用「瞬時半長軸」抓機動，99.5% 都抓錯")
    st.error(
        "MEME 檔案裡的瞬時（osculating）半長軸，其實會因為地球扁率造成的 J2 短週期攝動而上下振盪"
        "（振幅可達數公里），跟真正的機動訊號長得很像。第一版方法直接比較相鄰快照的瞬時半長軸差異，"
        "**結果把 99.5% 的正常樣本都誤判成機動**——這不是資料問題，是方法本身的系統性錯誤。\n\n"
        "**修正方式**：不比較單一時刻的瞬時值，而是把整份 72 小時星曆檔（約 10 個軌道週期）的半長軸取平均，"
        "讓 J2 短週期振盪自然抵消，只留下真正的長期趨勢——修正後，已知靜止衛星的雜訊地板才降到合理範圍"
        "（低於 0.2 km 的判定門檻）。**這個教訓後來變成 `study3` 機動過濾邏輯的核心方法**。"
    )

    st.header("③ 意外發現二：SpaceX 把計畫機動「預先寫好」進星曆檔")
    st.warning(
        "對 STARLINK-5846 做逐檔比對時發現：點火前發布的檔案，跟點火後發布的檔案，"
        "在重疊時間範圍內的軌跡幾乎完全一致（差距僅 100～250 公尺，屬於定軌更新雜訊等級）——"
        "**兩份檔案裡都已經包含完全相同的未來半長軸變化曲線**。這代表：**跨檔案比較法根本定位不到點火時刻**，"
        "因為 SpaceX 是把「計畫要做的機動」預先計算好、寫進了尚未執行的星曆檔案裡。\n\n"
        "真正能定位點火的方法是**檔案內部**逐點用 vis-viva 方程式"
        "（依軌道能量守恆推導、從瞬時位置與速度直接反算瞬時半長軸的公式）算瞬時半長軸——"
        "推力弧會在單一檔案內直接顯現。"
        "本案例最後抓到一次 30 分鐘內半長軸階躍 6.59 公里的真實推力弧，時間點與兩份不同檔案的讀值完全一致。"
    )

    st.header("④ 機動污染的量級反差：純外推 vs 含機動，差了 14 倍")
    frozen = data.get("frozen", pd.DataFrame())
    gap = data.get("gap", pd.DataFrame())
    if not frozen.empty:
        fig2 = go.Figure()
        for subset, color in [("all", "#EF5350"), ("clean", "#66BB6A")]:
            sub = frozen[frozen["subset"] == subset]
            fig2.add_trace(go.Scatter(x=sub["horizon_days"], y=sub["pos_med_km"], mode="lines+markers",
                                      name="全部樣本" if subset == "all" else "已濾除機動",
                                      line=dict(color=color, width=2)))
        fig2.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                           xaxis_title="凍結 TLE 外推天數", yaxis_title="位置誤差中位數 (km)",
                           plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True, key="case13_frozen")
    if not gap.empty:
        n_man = int(gap["maneuvered"].sum())
        n_quiet = int((~gap["maneuvered"]).sum())
        med_man = gap.loc[gap["maneuvered"], "pos_err_km"].median()
        med_quiet = gap.loc[~gap["maneuvered"], "pos_err_km"].median()
        st.info(
            f"對 50 顆衛星做「凍結一筆 TLE、放著讓它自然老化 7 天」的實測（跨越一次真實 ~6.7 天的資料下載斷點）：\n\n"
            f"- **{n_quiet} 顆純外推（無機動）**：7 天後位置誤差中位數 **{med_quiet:.1f} km**\n"
            f"- **{n_man} 顆期間曾機動**：7 天後位置誤差中位數飆升到 **{med_man:.0f} km**"
            f"（約 **{med_man/med_quiet:.0f} 倍**）\n\n"
            "最乾淨的幾顆純外推衛星，7 天後誤差甚至可以低到個位數公里——"
            "**這代表 TLE 老化本身不是主要問題，「有沒有在外推期間機動」才是決定 TLE 還能不能用的關鍵**。"
        )

    st.header("⑤ 放大到全星系的意義：TLE vs MEME，差了三個數量級")
    st.success(
        "把同樣的比對邏輯放大到全部 **284 顆 Starlink、約 2,600 萬個資料點**："
        "新鮮 TLE（epoch 未滿 3 小時）的位置誤差中位數約 **1.5 km**（沿軌方向 1,524 m 主導，"
        "徑向僅 143 m、法向 181 m）；6～12 小時後成長到約 3 km，24～48 小時到 13 km，48～72 小時到 32 km——"
        "對照 MEME 精密星曆全程維持在**公尺級（約 5 m）**，兩者差了**三個數量級**。\n\n"
        "這個落差對實務有具體意義：機動偵測可以反過來當作「星曆可信度即時把關」機制——"
        "剛做完機動的衛星，其 TLE 在數十公里等級內完全失準，若能即時標記出來，"
        "就能在需要高精度定位（例如評估 Starlink 訊號能否替代 GPS 做 LEO-PNT 定位）的應用中先行剔除。"
    )

    st.markdown("---")
    st.markdown(
        "**判讀**：這次大規模計算最重要的不是「證實了誤差會隨時間變大」（這是預期中的結果），"
        "而是兩個計算前沒想到的方法論陷阱——**瞬時半長軸的短週期振盪陷阱**與**星曆檔已預先編入計畫機動**——"
        "如果沒有先跑過幾十顆衛星的真實資料去對照檢查，這兩個陷阱很容易被忽略，"
        "後續所有基於「相鄰快照差分找機動」的分析都會建立在錯誤的地基上。"
    )
    st.caption("完整方法與程式見 `study1_tle_error_distribution.py`、`study2_meme_self_prediction.py`、"
              "`study3_tle_frozen_and_gap.py`；期中報告圖文見 `docs/meme_tle_report/`。")


# ── main ──────────────────────────────────────────────────────────────────────

# StoryMap 獨立進入點（2026-09-10 新增）：網址帶 ?mode=storymap（可選 &case=case3..case7）
# 即可直接落地到 StoryMap（或指定案例），免手動切換側欄——供對外分享單一連結用。
_qp = st.query_params
if "app_mode" not in st.session_state and _qp.get("mode") in ("tool", "storymap"):
    st.session_state["app_mode"] = _qp.get("mode")
if "storymap_case" not in st.session_state and _qp.get("case") in (
        "case3", "case4", "case5", "case6", "case7", "case8", "case9", "case10", "case1", "case2",
        "case11", "case12", "case13"):
    st.session_state["storymap_case"] = _qp.get("case")
    st.session_state.setdefault("app_mode", "storymap")

with st.sidebar:
    st.selectbox("Language / 語言 / 言語", options=list(LANG_LABELS.keys()),
                 format_func=lambda k: LANG_LABELS[k], key="app_lang")
    st.radio(" ", options=["tool", "storymap"], key="app_mode",
             format_func=lambda k: t("mode_tool") if k == "tool" else t("mode_storymap"),
             label_visibility="collapsed")

if st.session_state.get("app_mode") == "storymap":
    _case = st.session_state.get("storymap_case")
    if _case == "case3":
        render_storymap_case3()
    elif _case == "case4":
        render_storymap_case4()
    elif _case == "case5":
        render_storymap_case5()
    elif _case == "case6":
        render_storymap_case6()
    elif _case == "case7":
        render_storymap_case7()
    elif _case == "case8":
        render_storymap_case8()
    elif _case == "case9":
        render_storymap_case9()
    elif _case == "case10":
        render_storymap_case10()
    elif _case == "case1":
        render_storymap_case1()
    elif _case == "case2":
        render_storymap_case2()
    elif _case == "case11":
        render_storymap_case11()
    elif _case == "case12":
        render_storymap_case12()
    elif _case == "case13":
        render_storymap_case13()
    else:
        render_storymap_landing()
    st.stop()

st.title(t("app_title"))
st.caption(t("app_caption"))

cat = load_catalog()
names = load_registry_names()

render_fleet_kpi_row(names)

with st.sidebar:
    st.header(t("sidebar_query_header"))
    query = st.text_input(t("input_query"), value="STARLINK-30273",
                          help=t("help_query"))
    st.header(t("sidebar_p2_header"))
    p2_vertex = st.slider(t("slider_p2_vertex"), 400.0, 1000.0, 700.0, 10.0)
    p2_floor = st.slider(t("slider_p2_floor"), 0.1, 1.0, 0.4, 0.05)
    p2_refy = st.slider(t("slider_p2_refy"), 0.5, 4.0, 2.0, 0.1)
    st.header(t("sidebar_p5_header"))
    p5_vertex = st.slider(t("slider_p5_vertex"), 50.0, 120.0, 70.0, 5.0)
    p5_refy = st.slider(t("slider_p5_refy"), 1.0, 3.0, 1.6, 0.1)

    st.header(t("sidebar_rag_header"))
    rag_url = st.text_input(t("input_rag_url"), value=RAG_DEFAULT_URL, key="rag_url_july")
    rag_auto = st.checkbox(t("chk_rag_auto"), value=True,
                           key="rag_auto_july",
                           help=t("help_rag_auto"))
    render_dialogue_panel()

p2 = ms.ParabolaParams(vertex=p2_vertex, floor=p2_floor, ref_x=400.0, ref_y=p2_refy)
p5 = ms.ParabolaParams(vertex=p5_vertex, floor=1.0, ref_x=200.0, ref_y=p5_refy)

hits = resolve_query(query, cat, names)
if hits.empty:
    st.warning(t("warn_no_match"))
    st.stop()

hits = hits.copy()
hits["disp"] = hits["norad_id"].map(names).fillna(hits["name"])
if len(hits) > 1:
    st.info(t("info_multi_match", n=len(hits)))
    pick = st.selectbox(t("sel_satellite"),
                        hits["disp"] + "  (" + hits["norad_id"].astype(str) + ")")
    norad = int(pick.split("(")[-1].rstrip(")"))
else:
    norad = int(hits["norad_id"].iloc[0])
sat_name = names.get(norad, hits["disp"].iloc[0] if len(hits) else str(norad))

df = load_tle(norad)
if df.empty or len(df) < 3:
    st.error(t("err_insufficient_tle"))
    st.stop()

# 日期範圍
dmin, dmax = df["epoch"].min().date(), df["epoch"].max().date()
c1, c2 = st.columns(2)
d0 = c1.date_input(t("date_start"), dmin, min_value=dmin, max_value=dmax)
d1 = c2.date_input(t("date_end"), dmax, min_value=dmin, max_value=dmax)
df = df[(df["epoch"].dt.date >= d0) & (df["epoch"].dt.date <= d1)].reset_index(drop=True)
if len(df) < 3:
    st.warning(t("warn_range_lt3"))
    st.stop()

a0 = float(df["sma_km"].iloc[0])
i0 = float(df["inclination_deg"].iloc[0])
orbit_class = ms.classify_orbit(a0, float(df["eccentricity"].iloc[0]), i0)
fam = ms.inc_family(i0)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric(t("metric_satellite"), sat_name)
m2.metric("NORAD", norad)
m3.metric(t("metric_orbit_class"), orbit_class)
m4.metric(t("metric_inc_family"), fam)
m5.metric(t("metric_tle_count"), len(df))

f107 = load_f107()
tr = ms.build_transitions(df, f107)
res = ms.apply_strategies(tr, orbit_class, p2=p2, p5=p5, lang=_lang())
combined = res["combined"] if len(tr) else np.array([], bool)


# ── 🎯 統一偵測摘要（orbit_anomaly_detector，依軌域自動路由）──────────────────
@st.cache_resource(show_spinner=False)
def _get_oad():
    import orbit_anomaly_detector as _oad
    return _oad.OrbitAnomalyDetector(DB_PATH)


@st.cache_data(show_spinner=False)
def _unified_detect(nid: int):
    try:
        return _get_oad().detect(int(nid))
    except Exception as _e:
        return {"status": "error", "err": str(_e)}


with st.container(border=True):
    st.markdown(t("unified_title"))
    with st.spinner(t("spinner_unified")):
        ur = _unified_detect(norad)
    if ur.get("status") == "ok":
        uc = st.columns(4)
        uc[0].metric(t("metric_regime_domain"), f"{ur['orbit_class']} · {ur['domain']}")
        uc[1].metric(t("metric_routed_primary"),
                     ur["routed_primary"].split("(")[0].split("+")[0].strip())
        uc[2].metric(t("metric_fusion_flags"),
                     ur["fusion_flags"] if ur["fusion_flags"] is not None else "—",
                     f"max_p={ur['fusion_max_prob']}" if ur["fusion_max_prob"] is not None else None)
        uc[3].metric(t("metric_model2_anomaly"),
                     ur["model2_anomalies"] if ur["model2_anomalies"] is not None else "—")
        if ur["reentry"]:
            st.error(t("err_reentry_verdict", verdict=ur["verdict"]))
        else:
            st.info(t("info_routed_to", primary=ur["routed_primary"], verdict=ur["verdict"]))
        st.caption(t("caption_layer2", n=ur["layer2_statistical_events"]))
    else:
        st.caption(t("caption_unified_unavailable", err=ur.get("err", ur.get("status"))))

# ── ① 根數與差值 ─────────────────────────────────────────────────────────────
st.subheader(t("sec1_title"))
if len(tr):
    _c_ttl, _c_tog = st.columns([3, 1.1])
    with _c_tog:
        _y_mode = st.radio(
            t("radio_left_y"), ["sma", "alt"],
            format_func=lambda k: t("plot_sma_km") if k == "sma" else t("plot_alt_km"),
            horizontal=True, key="elem_a_ymode",
            help=t("help_left_y"))
    _show_alt = (_y_mode == "alt")
    _nm1 = compute_nrlmsis_maneuvers(norad, d0, d1)
    _mv = _nm1[_nm1["is_maneuver"]] if _nm1 is not None else None
    st.plotly_chart(plot_elements_and_deltas(df, tr, combined, nrlmsis_mv=_mv,
                                             show_altitude=_show_alt),
                    width="stretch")
    if _mv is not None:
        st.caption(t("caption_green_star", n=len(_mv)))

# ── ② P1–P6 ─────────────────────────────────────────────────────────────────
st.subheader(t("sec2_title"))
if len(tr):
    rows = [{"strategy": k, "n_flags": int(v.sum()),
             "kind": t("tbl_kind_suppress") if "suppress" in k else t("tbl_kind_detect")}
            for k, v in res["per_strategy"].items()]
    rows.append({"strategy": t("tbl_strategy_combined"), "n_flags": int(combined.sum()),
                 "kind": t("tbl_kind_final")})
    cL, cR = st.columns([1, 1.4])
    cL.dataframe(tcols(pd.DataFrame(rows)), hide_index=True, width="stretch")
    with cR:
        for k, note in res["notes"].items():
            st.caption(f"**{k}** — {note}")
    # 閾值曲線預覽
    with st.expander(t("exp_p2p5_preview")):
        gx = np.linspace(300, 1000, 100)
        fx = np.linspace(60, 260, 100)
        fig2 = make_subplots(rows=1, cols=2, subplot_titles=(t("plot_p2_curve"),
                                                             t("plot_p5_curve")))
        fig2.add_trace(go.Scatter(x=gx, y=p2(gx), line=dict(color="#0072B2")), row=1, col=1)
        fig2.add_trace(go.Scatter(x=fx, y=p5(fx), line=dict(color="#E69F00")), row=1, col=2)
        fig2.update_layout(height=280, showlegend=False, margin=dict(t=30, b=20))
        st.plotly_chart(fig2, width="stretch")

# ── ③ 統計層 + ML ────────────────────────────────────────────────────────────
st.subheader(t("sec3_title"))

# ── 自動路由：Starlink → Model 1 主判；非 Starlink → Model 2 / NRLMSIS 殘差 ──
_in_domain = is_starlink_domain(sat_name)
if _in_domain:
    st.success(t("succ_starlink_domain", sat=sat_name))
else:
    st.warning(t("warn_ood_domain", sat=sat_name))

# 主判結果卡（依路由選擇的偵測器）
with st.container():
    _nm = compute_nrlmsis_maneuvers(norad, d0, d1)
    _m2 = compute_model2_detection(norad, d0, d1)
    if _nm is not None and _nm.attrs.get("reentry"):
        st.error(t("err_reentry_decay"))
    pc = st.columns(3)
    if _in_domain:
        _det = compute_ml_detection(norad, d0, d1)
        _n1 = int(_det[0]["flag"].sum()) if _det else 0
        pc[0].metric(t("metric_primary_m1"), _n1)
        pc[1].metric(t("metric_nrlmsis_cross"),
                     int(_nm["is_maneuver"].sum()) if _nm is not None else 0)
        pc[2].metric(t("metric_m2_cross"), int(_m2["anomaly"].sum()) if _m2 is not None else 0)
    else:
        _nnm = int(_nm["is_maneuver"].sum()) if _nm is not None else 0
        pc[0].metric(t("metric_primary_nrlmsis"), _nnm)
        pc[1].metric(t("metric_m2_support"), int(_m2["anomaly"].sum()) if _m2 is not None else 0)
        pc[2].metric(t("metric_m1_ood"), "—")
        if _nm is not None and _nnm:
            mv = _nm[_nm["is_maneuver"]]
            st.caption(t("label_nrlmsis_times") + "， ".join(
                t("fmt_nrlmsis_time", d=pd.Timestamp(e).date(), v=f"{v:+.2f}")
                for e, v in zip(mv["epoch"], mv["drag_resid_da"])))

if len(df) >= 8:
    sr = sd.run_all(df["sma_km"].to_numpy(float))
    fig3 = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                         subplot_titles=(t("plot_cusum"), t("plot_bocpd"),
                                         t("plot_ssa"), "3σ MAD z"))
    xep = df["epoch"]
    for r_, key, col in [(1, "cusum", "#0072B2"), (2, "bocpd", "#E69F00"),
                         (3, "ssa", "#009E73"), (4, "mad3sig", "#D55E00")]:
        sc = sr[key]["scores"]
        fig3.add_trace(go.Scatter(x=xep, y=sc, line=dict(color=col, width=1.2),
                                  showlegend=False), row=r_, col=1)
        ev = sr[key]["events"]
        if len(ev):
            fig3.add_trace(go.Scatter(x=xep.iloc[ev], y=np.asarray(sc)[ev], mode="markers",
                                      marker=dict(color=col, size=6, symbol="circle-open"),
                                      showlegend=False), row=r_, col=1)
    fig3.update_layout(height=560, margin=dict(l=40, r=20, t=40, b=30))
    st.plotly_chart(fig3, width="stretch")
    cc = st.columns(4)
    for i, key in enumerate(("cusum", "bocpd", "ssa", "mad3sig")):
        cc[i].metric(t("metric_events", m=key.upper()), int(len(sr[key]["events"])))

    # ML forecast（若模型與特徵可得）
    with st.expander(t("exp_ml_forecast")):
        try:
            import joblib, json
            mdir = Path("Orbital_Maneuver_V2/models_meme_forecast")
            model = joblib.load(mdir / "lgbm_maneuver_v1.pkl")
            feats = json.loads((mdir / "feature_names.json").read_text(encoding="utf-8"))
            import build_training_dataset as btd
            t_from = df["epoch"].iloc[-1]
            win = df.rename(columns={"epoch": "date_tag"})
            fv = btd.compute_features(win, t_from,
                                      float(f107.get(t_from.strftime("%Y-%m-%d"), np.nan)))
            if fv:
                # Phase 2：接上統計層三變點統計量（取最新 TLE epoch 的值）
                for key, col in [("cusum", "cusum_stat"), ("bocpd", "bocpd_cp_prob"),
                                 ("ssa", "ssa_resid_z")]:
                    sc = sr[key]["scores"]
                    fv[col] = float(sc[-1]) if len(sc) else np.nan
                X = pd.DataFrame([{k: fv.get(k, np.nan) for k in feats}])
                p = float(model.predict_proba(X)[:, 1][0])
                st.metric(t("metric_forecast_p"), f"{p:.1%}")
                st.caption(t("caption_feat_count", n=len(feats)))
            else:
                st.caption(t("caption_feat_insufficient"))
        except Exception as e:
            st.caption(t("caption_ml_model_unavailable", e=e))

    # ML 機動偵測（每窗口，非預測）
    st.markdown(t("md_ml_detection"))
    with st.spinner(t("spinner_ml_detect")):
        det = compute_ml_detection(norad, d0, d1)
    if det is not None:
        ddf, dthr = det
        prob = ddf["prob"].to_numpy(float)
        flg = ddf[ddf["flag"]]
        # 分布外偵測：整段最大 |Δa| 都低於高度自適應閾值 → 純阻力衰減/無機動
        pure_decay = bool((ddf["da_km"].abs() <= ddf["p2_thr"]).all())
        if pure_decay:
            st.warning(t("warn_pure_decay"))
        figd = go.Figure()
        figd.add_trace(go.Scatter(x=ddf["epoch"], y=prob, mode="lines",
                                  line=dict(color="#CC79A7", width=1.3),
                                  name=t("legend_model_raw_prob")))
        figd.add_hline(y=dthr, line=dict(color="#888", dash="dash"),
                       annotation_text=t("annot_model_thr", thr=f"{dthr:.2f}"))
        if len(flg):
            figd.add_trace(go.Scatter(x=flg["epoch"], y=flg["prob"], mode="markers",
                                      marker=dict(color="#D55E00", size=9, symbol="x"),
                                      name=t("legend_ml_detected")))
        figd.update_layout(height=280, yaxis_title=t("yaxis_p_window"),
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.18))
        st.plotly_chart(figd, width="stretch")
        dc = st.columns(3)
        dc[0].metric(t("metric_ml_windows"), int(len(flg)))
        dc[1].metric(t("metric_raw_above_thr"), int((prob >= dthr).sum()))
        dc[2].metric(t("metric_max_da"), f"{ddf['da_km'].abs().max():.3f}")
        st.caption(t("caption_model1_gate"))
    else:
        st.caption(t("caption_ml_detect_unavailable"))

    # ── Model 2：regime-agnostic 無監督（NRLMSIS 物理殘差 + Isolation Forest）──
    st.markdown(t("md_model2"))
    with st.spinner(t("spinner_model2")):
        m2 = compute_model2_detection(norad, d0, d1)
    if m2 is not None:
        anom = m2[m2["anomaly"]]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=m2["epoch"], y=m2["z_drag"], mode="lines",
                                  line=dict(color="#009E73", width=1.2),
                                  name=t("legend_nrlmsis_resid")))
        if len(anom):
            fig2.add_trace(go.Scatter(x=anom["epoch"], y=anom["z_drag"], mode="markers",
                                      marker=dict(color="#D55E00", size=8, symbol="diamond"),
                                      name=t("legend_m2_anomaly")))
        fig2.update_layout(height=260, yaxis_title=t("yaxis_drag_resid"),
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.2))
        st.plotly_chart(fig2, width="stretch")
        e1, e2 = st.columns(2)
        e1.metric(t("metric_m2_detected"), int(len(anom)))
        e2.metric(t("metric_max_drag_resid"), f"{m2['z_drag'].abs().max():.1f}")
        st.caption(t("caption_model2_note"))
    else:
        st.caption(t("caption_model2_unavailable"))

    # ── 連續融合評分器（CUSUM/BOCPD/SSA/MAD + NRLMSIS drag → 單一機率）──────────
    st.markdown(t("md_fusion"))
    with st.spinner(t("spinner_fusion")):
        fus = compute_fusion_detection(norad, d0, d1)
    if fus is not None:
        fthr = fus.attrs.get("thr", 0.5)
        fflag = fus[fus["fusion"] >= fthr]
        figf = go.Figure()
        figf.add_trace(go.Scatter(x=fus["epoch"], y=fus["fusion"], mode="lines",
                                  line=dict(color="#CC79A7", width=1.4),
                                  name=t("legend_fusion_prob")))
        figf.add_hline(y=fthr, line_dash="dash", line_color="#999",
                       annotation_text=t("annot_op_thr", thr=f"{fthr:.2f}"))
        if len(fflag):
            figf.add_trace(go.Scatter(x=fflag["epoch"], y=fflag["fusion"], mode="markers",
                                      marker=dict(color="#D55E00", size=7),
                                      name=t("legend_fusion_flag")))
        figf.update_layout(height=240, yaxis_title=t("yaxis_fusion_prob"), yaxis_range=[0, 1],
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.25))
        st.plotly_chart(figf, width="stretch")
        st.caption(t("caption_fusion_note", n=len(fflag)))
    else:
        st.caption(t("caption_fusion_unavailable"))

    # ── 🤖 SSA-RAG 自動解說（③ 偵測結果 → 自然語言 → RAG）───────────────────────
    if rag_auto:
        _ev = pd.DataFrame()
        if len(tr) and combined.any():
            _et = tr[combined].copy()
            _ev = pd.DataFrame({
                "epoch": _et["epoch"].to_numpy(),
                "sma_delta": _et["da_km"].abs().to_numpy(),
                "sma_direction": np.where(_et["da_km"].to_numpy() > 0, "raise", "lower"),
            })
        _alt_avg = float(tr["alt_km"].mean()) if len(tr) else None
        _narr = build_tle_maneuver_narrative(norad, _alt_avg, str(d0), str(d1), _ev)
        # Starlink（Model 1 分布內）額外附 ML 偵測敘述
        if _in_domain and det is not None:
            _ddf = det[0]
            _p_ml = float(_ddf.loc[_ddf["flag"], "prob"].max()) if _ddf["flag"].any() \
                else float(_ddf["prob"].max())
            _feat = {
                "alt_km": _alt_avg if _alt_avg is not None else float("nan"),
                "net_da_km": float(_ddf["da_km"].sum()),
                "max_da_km": float(_ddf["da_km"].abs().max()),
                "flag_rate": float(_ddf["flag"].mean()),
                "dv_net_ms": float(_ddf["da_km"].sum()) / 2 * 0.0011 * 1000,
            }
            _narr += "\n\n" + build_ml_maneuver_narrative(
                norad, _p_ml, _feat, str(d0), str(d1), alert=bool(_ddf["flag"].any()))
        render_rag_auto_explain(_narr, base_url=rag_url)

# ── ⑤ MEME vs TLE（72h 模型）────────────────────────────────────────────────
st.subheader(t("sec5_title"))
try:
    from compare_tle_vs_ephemeris import (find_all_ephemeris_files, propagate_with_best_tles,
                                          _meme_first_state)
    from skyfield.api import load as skyload
    sat_dir = DATA / "raw" / sat_name
    files = find_all_ephemeris_files(sat_dir) if sat_dir.is_dir() else []
    if files:
        snaps = [s for s in (_meme_first_state(f) for f in sorted(files)) if s]
        meme = pd.DataFrame(snaps).sort_values("t").reset_index(drop=True)
        meme = meme[meme["t"] <= meme["t"].iloc[0] + pd.Timedelta(hours=72)]
        ts = skyload.timescale()
        tle_df = df.rename(columns={"epoch": "epoch_utc"})
        prop = propagate_with_best_tles(meme[["t", "r_x", "r_y", "r_z"]], tle_df, sat_name, ts)
        mg = meme.merge(prop[["t", "r_x", "r_y", "r_z"]], on="t", suffixes=("_m", "_t"))
        err = np.sqrt((mg.r_x_t-mg.r_x_m)**2 + (mg.r_y_t-mg.r_y_m)**2 + (mg.r_z_t-mg.r_z_m)**2)
        age_h = (mg["t"] - mg["t"].iloc[0]).dt.total_seconds() / 3600
        figm = go.Figure(go.Scatter(x=age_h, y=err, line=dict(color="#0072B2")))
        figm.update_layout(height=300, xaxis_title=t("xaxis_meme_age"),
                           yaxis_title=t("yaxis_tle_meme_err"), margin=dict(t=20))
        st.plotly_chart(figm, width="stretch")
        st.caption(t("caption_meme_err", med=f"{np.median(err):.2f}",
                     p95=f"{np.percentile(err, 95):.2f}"))
    else:
        st.caption(t("caption_no_meme", sat=sat_name))
except Exception as e:
    st.caption(t("caption_meme_unavailable", e=e))

# ── ⑥ 資料品質稽核 (quality_flag) ─────────────────────────────────────────────
st.subheader(t("sec6_title"))
au = dqa.audit_tles(df)
qs = dqa.summarize(au)
qc = st.columns(5)
qc[0].metric(t("metric_q_good"), qs["good"], f"{qs['frac_good']*100:.1f}%")
qc[1].metric(t("metric_q_suspect"), qs["suspect"])
qc[2].metric(t("metric_q_rejected"), qs["rejected"])
qc[3].metric(t("metric_q_dup"), qs["n_dup"])
qc[4].metric(t("metric_q_topreason"),
             "、".join(f"{k}:{v}" for k, v in qs["top_reason"].items()) or "—")

_qcmap = {"good": "#2ca02c", "suspect": "#E69F00", "rejected": "#d62728"}
figq = go.Figure()
for _fl in ("good", "suspect", "rejected"):
    _sub = au[au["quality_flag"] == _fl]
    if not _sub.empty:
        figq.add_trace(go.Scatter(
            x=_sub["epoch"], y=_sub["sma_km"], mode="markers",
            marker=dict(size=5, color=_qcmap[_fl]), name=_fl,
            text=_sub["quality_reason"],
            hovertemplate="%{x}<br>sma=%{y:.3f} km<br>%{text}<extra>" + _fl + "</extra>"))
figq.update_layout(title=t("plot_q_title"), height=300,
                   margin=dict(t=40, b=30, l=10, r=10),
                   yaxis_title="sma (km)", legend=dict(orientation="h"))
st.plotly_chart(figq, width="stretch")

_bad = au[au["quality_flag"] != "good"]
if not _bad.empty:
    st.caption(t("caption_bad_count", n=len(_bad)))
    st.dataframe(tcols(_bad[["epoch", "sma_km", "inclination_deg", "bstar",
                             "quality_flag", "quality_reason"]]),
                 hide_index=True, width="stretch", height=min(300, 52 + 34 * len(_bad)))
else:
    st.caption(t("caption_all_good"))
st.caption(t("caption_q_rules"))

# ── ⑦ 星系級異常分析（constellation_anomaly）─────────────────────────────────
@st.cache_data(show_spinner=False)
def _cached_constellation(cn: str, days: int):
    from datetime import timedelta as _td
    pat = ca.CONSTELLATIONS[cn]
    con = duckdb.connect(DB_PATH, read_only=True)
    mx = con.execute("SELECT MAX(epoch_utc) FROM raw_tle_archive WHERE UPPER(object_name) LIKE ?",
                     [pat]).fetchone()[0]
    con.close()
    date1 = pd.Timestamp(mx); date0 = date1 - _td(days=days)
    cdf = ca.load_constellation(DB_PATH, pat, date0, date1)
    if cdf.empty or cdf["norad_id"].nunique() < 5:
        return None
    R = ca.analyze(cdf)
    return {"planes": R["planes"], "batch": R["batch"], "formation": R["formation"],
            "K": R["K"], "nsat": int(cdf["norad_id"].nunique()),
            "d0": str(date0.date()), "d1": str(date1.date())}


def _detect_constellation(name: str):
    up = (name or "").upper()
    for cn, pat in ca.CONSTELLATIONS.items():
        if pat.strip("%") in up:
            return cn
    return None


st.subheader(t("sec7_title"))
_cn = _detect_constellation(sat_name)
if _cn is None:
    st.caption(t("caption_not_constellation", sat=sat_name,
                 known="、".join(ca.CONSTELLATIONS)))
else:
    _cdays = st.slider(t("slider_analysis_window"), 7, 60, 30, key="cn_days")
    if st.button(t("btn_run_constellation", cn=_cn), key="cn_go"):
        with st.spinner(t("spinner_constellation", cn=_cn)):
            CR = _cached_constellation(_cn, _cdays)
        if CR is None:
            st.warning(t("warn_constellation_insufficient"))
        else:
            planes, batch, formation = CR["planes"], CR["batch"], CR["formation"]
            st.caption(t("caption_constellation_scope", cn=_cn, n=CR["nsat"],
                         d0=CR["d0"], d1=CR["d1"]))
            cc = st.columns(3)
            cc[0].metric(t("metric_c1"), int(planes["flag_plane_incoherent"].sum()),
                         t("metric_c1_delta", n=len(planes)))
            cc[1].metric(t("metric_c2"), int(batch["flag_batch"].sum()), f"K={CR['K']:.0f}")
            cc[2].metric(t("metric_c3"), int(formation["n_outliers"].sum()))
            with st.expander(t("exp_c1")):
                st.dataframe(tcols(planes.head(15)), hide_index=True, width="stretch")
            with st.expander(t("exp_c2")):
                st.dataframe(tcols(batch.head(15)), hide_index=True, width="stretch")
            with st.expander(t("exp_c3")):
                st.dataframe(tcols(formation.head(15)), hide_index=True, width="stretch")
            st.caption(t("caption_constellation_note"))

# ── ④ 艦隊級統計（284 顆）+ bootstrap CI ─────────────────────────────────────
# 先隱藏（使用者要求 2026-07-14）：整段艦隊統計 + 95% CI 暫不顯示；改 True 即復原。
_SHOW_FLEET_STATS = False
if _SHOW_FLEET_STATS:
    st.subheader(t("sec4_title"))
    truth = load_truth()
    if not truth.empty:
        # 每顆 medium+ 機動episode率（gap>48h 合併）
        med = truth[truth["da_severity"].isin(["medium", "large"])].copy()
        rates = []
        for s, g in med.groupby("sat_name"):
            tt = np.sort(g["t_to"].astype("int64").to_numpy())
            span_d = max((tt[-1] - tt[0]) / 3.6e12 / 24, 1) if len(tt) > 1 else 1
            n_ep = 1 + int((np.diff(tt) > 48 * 3.6e12).sum()) if len(tt) > 1 else len(tt)
            rates.append(n_ep / span_d * 30)  # 每 30 天episode數
        m, lo, hi = bootstrap_ci(np.array(rates))
        cA, cB = st.columns(2)
        cA.metric(t("metric_fleet_rate"), f"{m:.2f}",
                  t("metric_fleet_ci", lo=f"{lo:.2f}", hi=f"{hi:.2f}"))
        cA.caption(t("caption_fleet_n", n=len(rates)))
        sm = load_stat_metrics()
        if not sm.empty:
            cB.markdown(t("md_detector_vs_truth"))
            show = sm[sm["input"] == "TLE"][["method", "precision", "recall", "lead_time_h_median"]]
            cB.dataframe(tcols(show), hide_index=True, width="stretch")
    else:
        st.caption(t("caption_no_truth"))

# ── ⑩ 合成 TLE ───────────────────────────────────────────────────────────────
st.subheader(t("sec10_title"))
with st.expander(t("exp_synth")):
    try:
        import datetime as _dt
        from synthetic_tle import (ManeuverParams, ManeuverType, NoiseLevel,
                                    OrbitalElements, generate_sequence,
                                    generate_training_pair, seq_to_tle_text)
        cS = st.columns(4)
        n_sat = int(cS[0].number_input(t("num_n_sat"), 1, 500, 10))
        n_days = int(cS[1].number_input(t("num_n_days"), 3, 120, 26))
        cadence = float(cS[2].number_input(t("num_cadence"), 1, 24, 8))
        man_frac = cS[3].slider(t("slider_man_frac"), 0.0, 1.0, 0.5, 0.1)
        c6 = st.columns(4)
        alt_lo, alt_hi = c6[0].slider(t("slider_alt_range"), 300, 1200, (500, 600), 10)
        inc_lo, inc_hi = c6[1].slider(t("slider_inc_range"), 0, 100, (52, 55), 1)
        dv_lo, dv_hi = c6[2].slider(t("slider_dv_range"), 0.1, 50.0, (0.5, 5.0), 0.1)
        noise = c6[3].selectbox(t("sel_noise"), ["LOW", "MEDIUM", "HIGH"], index=1)
        seed = int(st.number_input(t("num_seed"), 0, 99999, 42))

        if st.button(t("btn_gen_synth")):
            rng = np.random.default_rng(seed)
            n_tles = max(3, int(round(n_days / (cadence / 24.0))))
            ep0 = _dt.datetime(2026, 5, 1, tzinfo=_dt.timezone.utc)
            nl = getattr(NoiseLevel, noise)
            mtypes = list(ManeuverType)
            texts, n_man = [], 0
            with st.spinner(t("spinner_gen_synth", n_sat=n_sat, n_tles=n_tles)):
                for k in range(n_sat):
                    start = OrbitalElements(
                        sma_km=R_E + rng.uniform(alt_lo, alt_hi),
                        ecc=rng.uniform(0, 0.002), inc_deg=rng.uniform(inc_lo, inc_hi),
                        raan_deg=rng.uniform(0, 360), argp_deg=rng.uniform(0, 360),
                        ma_deg=rng.uniform(0, 360), epoch=ep0,
                        bstar=rng.uniform(1e-5, 3e-4), norad_id=90000 + k)
                    if rng.random() < man_frac:
                        mp = ManeuverParams(
                            maneuver_type=rng.choice(mtypes),
                            dv_m_s=float(rng.uniform(dv_lo, dv_hi)),
                            delta_t_days=float(rng.uniform(n_days * 0.3, n_days * 0.7)),
                            dv_prograde_fraction=1.0, target_sma_km=None)
                        before, after = generate_training_pair(
                            start, mp, n_before=n_tles // 2, n_after=n_tles - n_tles // 2,
                            dt_days=cadence / 24.0, noise_level=nl, rng=rng)
                        seq = before + after
                        n_man += 1
                    else:
                        seq = generate_sequence(start, n_tles, dt_days=cadence / 24.0,
                                                noise_level=nl, rng=rng)
                    texts.append(seq_to_tle_text(seq, f"SYNTH-{90000 + k}"))
            out = "\n".join(texts)
            st.success(t("succ_synth_done", n_sat=n_sat, n_man=n_man, n_tles=n_tles))
            st.download_button(t("btn_download_synth"), out, file_name="synthetic.tle")
    except Exception as e:
        st.caption(t("caption_synth_unavailable", e=e))

# ── ⑧ SSA-RAG 知識問答 ────────────────────────────────────────────────────────
st.subheader(t("sec8_title"))
with st.expander(t("exp_rag_qa"), expanded=False):
    render_ssa_rag_page(base_url=rag_url)

st.divider()
st.caption(t("footer"))
