# 每日資料自動更新（GitHub Actions）

把兩個 HF Space 的資料庫更新從「本機手動跑 .bat」改成雲端每日自動執行。

## 一次性準備（只需做一次）

1. **設定 GitHub Secrets**（repo → Settings → Secrets and variables → Actions → New repository secret）：
   - `SPACE_TRACK_IDENTITY` — Space-Track 帳號（同本機 `.env` 裡的值）
   - `SPACE_TRACK_PASSWORD` — Space-Track 密碼
   - `HF_TOKEN` — Hugging Face token（需對 `RhynoWu/starlink-maneuver-db`、
     `RhynoWu/satdashboard-db` 兩個 Dataset 與對應 Space 有寫入權限；
     在 huggingface.co → Settings → Access Tokens 建立，選 **Write** 權限）

2. **執行一次遷移腳本**（本機執行，需要本機已 `hf auth login`）：
   ```
   python ci/migrate_raw_tle_archive_to_yearly.py --dry-run   # 先看切檔結果
   python ci/migrate_raw_tle_archive_to_yearly.py             # 確認無誤後正式上傳
   ```
   這一步把 HF Dataset 現有的單一大檔 `raw_tle_archive/data.parquet` 拆成
   `raw_tle_archive/year=YYYY/data.parquet`，之後每日流程只需碰「今年」那一份小檔。
   舊檔不會被刪除，可留著當備援。

3. 確認 `.github/workflows/daily_data_update.yml` 已隨這次改動一起 push 到 GitHub
   （排程只有 push 到預設分支後才會生效）。

## 之後的日常運作

- 每天 UTC 00:00（台灣 08:00）自動執行：抓當日新 TLE → 更新 HF Dataset 年度 parquet →
  重建 `space_db_slim.duckdb` → 發布到 SatDashboard Dataset → 重啟兩個 Space。
- 可在 GitHub repo 的 Actions 分頁手動觸發（workflow_dispatch）驗證是否成功，
  不用等到隔天排程。
- 本機的 `update_slim_publish_hf.bat` 與 `download_TLE_unified.py` 仍然保留、可繼續手動使用
  （例如需要立即更新、或需要 recent-days 以外的自訂範圍時），兩者互不衝突——
  CI 與本機都是往同一個 HF Dataset 寫入 year=YYYY 檔案，誰跑都可以更新到最新。

## 已知限制

- CI 的 slim DB 建置涵蓋「近 14 天全衛星」+「RPO 展示白名單 + StoryMap 故事 JSON 明列
  衛星（含 QZSS）+ 使用者自訂目錄」的全歷史，與本機 `update_slim_publish_hf.bat` 的
  涵蓋範圍等價，但**沒有**複製 `merge_storymap_tle.py` 裡「六大展示群組（GPS/北斗/
  Starlink/OneWeb/大陸ISR/大陸通訊）近 30 天活躍成員」這層額外邏輯——這層在 CI 版其實
  不需要，因為 CI 本來就把「近 14 天全衛星」整批帶入 slim DB，已經涵蓋所有近期活躍衛星。
- `sat_n2yo_metadata`／`training_samples`／`conjunction_events` 等小型業務表，CI 只會
  原樣沿用 Dataset 上次的版本，不會重新計算——這些本來就是低頻更新的參考資料，
  如需要更新請照舊在本機重新產生後手動 `export_to_hf_parquet.py` 上傳一次。
