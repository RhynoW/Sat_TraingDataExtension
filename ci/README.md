# 每日資料更新腳本（手動執行）

> **2026-09-17 更新**：GitHub Actions 每日自動排程（`daily_data_update.yml`）已移除——
> Space-Track 帳密與 HF token 在 CI 環境下持續驗證失敗（`SPACE_TRACK_PASSWORD`／
> `HF_TOKEN` 401，連續多日排程失敗），且本機憑證已驗證可用，改為**手動執行下列腳本**
> 更新兩個 HF Dataset／Space，不再依賴雲端排程。

## 用法（本機執行，需要本機 `.env` 已有效的 Space-Track 帳密、且已 `hf auth login`）

```
python ci/ci_daily_tle_update.py --dataset-repo RhynoWu/starlink-maneuver-db
python ci/ci_build_and_publish_slim.py --dataset-repo RhynoWu/starlink-maneuver-db
```

- `ci_daily_tle_update.py`：抓最新 TLE、更新 `starlink-maneuver-db` 之年度 parquet，
  完成後重啟 `RhynoWu/maneuver-detection` 與 `RhynoWu/maneuver-detection-i18n` 兩個 Space。
- `ci_build_and_publish_slim.py`：由上一步抓好的資料重建 `space_db_slim.duckdb`，
  供後續 `scenario-advanced01/tools/publish_db_to_dataset.py` 原樣上傳＋重啟
  SatDashboard 的兩個 Space。

`migrate_raw_tle_archive_to_yearly.py` 為一次性遷移腳本（已執行過，`raw_tle_archive`
已切成 `year=YYYY/data.parquet`），除非重新出現單一大檔，否則不需要再跑。

## 與本機既有流程的關係

本機的 `update_slim_publish_hf.bat` 與 `download_TLE_unified.py` 仍是主要的手動更新
路徑（例如需要立即更新、或需要 recent-days 以外的自訂範圍時），與上述兩支 `ci/`
腳本互不衝突——皆是往同一個 HF Dataset 寫入 year=YYYY 檔案，誰跑都能更新到最新。

## 已知限制

- `ci_build_and_publish_slim.py` 建置之 slim DB 涵蓋「近 14 天全衛星」+「RPO 展示
  白名單 + StoryMap 故事 JSON 明列衛星（含 QZSS）+ 使用者自訂目錄」的全歷史，與本機
  `update_slim_publish_hf.bat` 之涵蓋範圍等價，但**沒有**複製 `merge_storymap_tle.py`
  裡「六大展示群組（GPS/北斗/Starlink/OneWeb/大陸ISR/大陸通訊）近 30 天活躍成員」這層
  額外邏輯——這層在此腳本其實不需要，因為已把「近 14 天全衛星」整批帶入 slim DB，
  已涵蓋所有近期活躍衛星。
- `sat_n2yo_metadata`／`training_samples`／`conjunction_events` 等小型業務表，
  `ci_build_and_publish_slim.py` 只會原樣沿用 Dataset 上次的版本，不會重新計算——
  這些本來就是低頻更新的參考資料，如需要更新請在本機重新產生後手動
  `export_to_hf_parquet.py` 上傳一次。
