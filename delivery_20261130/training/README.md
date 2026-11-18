# 教育訓練練習程式

配合《教育訓練教材：技術教學》（FIN-RPT-04，`教育訓練_技術教學教材_20261118`）使用。所有練習皆在**程式包根目錄**執行。

| 檔案 | 單元 | 內容 | 網路 |
|---|---|---|---|
| `ex00_env_check.py` | 0 | 套件、必要檔案、線上資料集連線檢查 | 需要（第 ③ 項） |
| `ex01_tle_noise.py` | 1 | SJ-26 高度歷程、發射初期 TLE、TLE 雜訊估計 | 需要 |
| `ex02_threshold.py` | 2 | L1 有效門檻（P2×P5×P6）、人工序列比較舊版與 R7 | 不需要 |
| `ex03_r7_events.py` | 3、5 | R7 候選事件、證據等級、偵測下限、低置信複核項 | 需要 |
| `ex04_aux_channels.py` | 4 | NRLMSIS 阻力殘差、L2 四種方法之觸發 | 需要（另需 pymsis） |
| `ex05_eval_stats.py` | 6 | 每千星日、Poisson 精確信賴區間、隨機命中基準 | 不需要 |
| `ex06_pdf_report.py` | 7 | 以程式批次產出 F1／F2 PDF 報表 | 需要 |

```
python training/ex00_env_check.py
python training/ex02_threshold.py
python training/ex03_r7_events.py 62190 2025-03-01 2025-06-30
python training/ex06_pdf_report.py 60548 41634
```

- 線上資料來源為程式包內附之 `space_hf.duckdb`（連到 HuggingFace 公開資料集）；可改以環境變數 `LOCAL_DB_PATH` 指向本機資料庫。
- 輸出檔寫入 `training/output/`。
- 各練習之預期輸出見教材；練習 1、3、4、6 之 TLE 持續更新，數字可能略有不同。
- 開發環境實測（2026-11-18，Python 3.13、Windows 11）：ex00–ex06 皆可執行。
