# 期末交付程式包（精簡版）

契約 TASA-S-1150268「智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究」期末交付之第 2 項「完整原始程式碼（含訓練與測試資料集、AI 模型、訓練參數）」。

Written for: 承辦審查人員與後續維護工程師（需能在本包內重現測試與主要訓練流程）。

> **2026-11-26 更新。** ① `maneuver_report_builder.satellite_name()` 修正：名稱欄改讀 `sat_n2yo_metadata.name_en`，並以 `raw_tle_archive` 最新 3LE 名稱補新編目衛星（原只查 `name` 欄而全數回傳 None，離線執行時 Starlink 被當成非 Starlink，ML／融合通道受限；線上 App 以 N2YO 名稱補上，不受影響）。② `maneuver_app_2026November.py` 同步 2026-11-19 之 StoryMap Case 1 更新（依期末報告 R7 流程）。③ 新增 TASA 指定 15 顆衛星之測試資料：`data/benchmark/tasa15_backfill/`（Space-Track gp_history 2024-01-01 至 2026-04-30 之 3LE，補齊本機缺漏）、`data/benchmark/tasa15_r7_delivery/r15.json`（原交付結果，2026-11-15）、`data/benchmark/tasa15_r7_backfill_20261126/r15.json`（補齊 TLE 後重產，期末報告 8.6 節）。偵測規則與模型未變動。
>
> **2026-11-18 更新為 R7 版。** 程式依報表版本 R7（2026-11-15）更新，與線上儀表板（HuggingFace Space `RhynoWu/maneuver-detection-i18n`）一致。R7 的主要變更：L1 改以 P2×P5×P6 有效門檻判定，P5 倍率上限 1.8；P3 停用；ΔΩ 標記移除；非 Starlink 衛星僅靠 ML 輔助達 E3 者改列 E2；低置信複核項合併為案件並新增 L2 統計變點補漏。訓練與測試資料集維持 2026-10-07 版未更動。

## 1. 內容

| 目錄／檔案 | 內容 |
|---|---|
| `maneuver_app_2026November.py` | 機動偵測儀表板（Streamlit 介面；分析工具、StoryMap 32 案、專書線上版三種模式） |
| `maneuver_report_builder.py`、`maneuver_strategies_july.py` | 單星報表（R7）與 L1 規則 P1–P6 |
| `book_reader.py`、`data/book/` | 專書線上版閱讀器與書稿（繁中／英／日） |
| `detection_timeline.py`、`sat_info_fetch.py` | 偵測時間軸、衛星基本資料查詢 |
| `assets/fonts/` | PDF 報表中文字型（NotoSansTC） |
| `Orbital_Maneuver_V2/` | LightGBM 分類器（train／predict／evaluate／labeler／dataset／data_loader） |
| `train_maneuver_model.py` | 30 天 TLE 特徵之運行階段與機動活動模型訓練 |
| `train_l3_altimetry.py`、`train_l3_starlink.py` | L3 候選確認式模型訓練（非 Starlink 族群／Starlink 族群） |
| `meme_label_training.py` | 以 MEME 真值標籤訓練（情境①泛化落差實驗） |
| `build_training_dataset.py` | 訓練樣本建立（MEME 真值 × TLE 軌道特徵） |
| `satdet/`、`synthetic_tle/`、`starlink_ephemeris/` | 共用套件（事件切段、FPR 下限、manifest、TLE 合成、星曆解析） |
| `atmospheric_drag.py`、`statistical_detectors.py`、`l3_candidate.py` 等 | 偵測演算法模組（大氣阻力、統計層、L3 候選） |
| `tasa14_*.py`、`tasa19_ext_arena.py`、`tasa23_ext_arena.py` | 測試基準（benchmark）與比較腳本 |
| `tests/` | 單元與回歸測試（pytest） |
| `models_plan_b/`、`models_fusion/`、`Orbital_Maneuver_V2/models/`、`Orbital_Maneuver_V2/models_meme*/` | 訓練完成之模型權重與門檻、特徵名稱（`l3_starlink.pkl` 為 2026-10-21 加入 B* 偏離特徵之重訓版） |
| `f107_cache.csv` | F10.7 太陽通量快取，P5 門檻倍率使用 |
| `data/benchmark/`、`data/meme_truth/`、`data/maneuvers/`、`data/tle_parquet/` 等 | 測試與訓練資料集（已篩選，見 MANIFEST.csv） |
| `data/benchmark/tasa15_*` | TASA 指定 15 顆衛星：補齊之歷史 TLE（3LE）、原交付與補齊後重產之 R7 結果（r15.json，`maneuver_report_builder.build_report_data()` 輸出） |
| `space_weather_ap.csv` | 太空天氣（Celestrak SW 格式），大氣阻力模組必需 |
| `requirements*.txt` | Python 相依套件 |
| `MANIFEST.csv` | 全部檔案清單、大小與 SHA-256 |

## 2. 環境

- Python 3.13（開發環境為 Windows 11；其他平台未驗證）
- `pip install -r requirements.txt`（另需 `pymsis` 供大氣模型，見 `atmospheric_drag.py` 開頭註解）
- 所有指令請在本包根目錄執行（資料路徑為相對路徑）

## 3. 驗證

```
python -m pytest -q tests/test_satdet.py tests/test_meme_to_tle.py tests/test_tle_catnr.py tests/test_atmospheric_drag.py tests/test_ephemeris_type.py tests/test_l3_candidate.py tests/test_p1p3_large_step.py tests/test_sixdigit_ingest.py
```

開發環境實測：8 個測試檔共 53 項，全部通過（2026-10-07；R7 更新後於 2026-11-18 重跑，結果相同）。

## 4. 執行

- 儀表板：`streamlit run maneuver_app_2026November.py`（未設遠端資料來源時讀本機 `space_db.duckdb`；本包未附該母庫，見第 5 節。亦可先設定環境變數 `HF_DATASET_REPO=RhynoWu/starlink-maneuver-db` 改讀公開之遠端 Parquet 資料集）
- L3 訓練：`python train_l3_altimetry.py`、`python train_l3_starlink.py`
- 機動活動模型：`python train_maneuver_model.py`
- LightGBM 分類器：`python Orbital_Maneuver_V2/train.py --help`

## 5. 已知限制（交付範圍之外）

1. **完整資料庫未附**：`space_db.duckdb` 母庫與 `data/raw/`（約 92 GB）未納入。Starlink 與 NASA/ILRS 的原始 TLE 可依報告附錄之來源重建；本包附的是訓練與測試直接使用的已整理資料。
2. **儀表板需資料庫**：`maneuver_app_2026November.py` 的完整功能需要 `space_db_slim.duckdb`（可由 HF Dataset `RhynoWu/satdashboard-db` 取得）。
3. **部分腳本需要母庫**：`train.py`、`build_training_dataset.py` 會讀 `space_db.duckdb`，本包內無法直接執行，需先補母庫。
4. **未逐一驗證執行**：本包僅對測試檔與編譯做了驗證；訓練腳本依相依分析收錄，尚未在本包內完整重跑。

## 6. 來源與授權

本程式為 SatDashboard 自主研發，開發工具皆為開源免費軟體（STK 除外，本包未使用）。
