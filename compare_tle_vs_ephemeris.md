# compare_tle_vs_ephemeris.py — 程式說明

## 概述

將 TLE（Two-Line Element）傳播的狀態向量與 SpaceX Starlink MEME 精密星曆逐點比較，計算位置與速度殘差，並輸出統計摘要及視覺化圖表。

本程式有**兩個獨立模式**，可同時啟用：

| 模式 | 旗標 | 預設狀態 | 功能 |
|------|------|:--------:|------|
| **殘差比較** | *(無)* | ✅ 啟用 | TLE 傳播 vs MEME 星曆的逐點位置/速度殘差；輸出 RTN 圖表與統計摘要 |
| **機動偵測評估** | `--maneuver-detection` | ❌ 停用 | 從 MEME 快照序列提取軌道機動地面真相，並評估 TLE 差分偵測器的 TPR/FPR/ROC-AUC/F1 |

**v2（2026-05-09）起的重要改變**：每顆衛星現在預設處理**全部**星曆檔案（而非只取最新一個）。每個檔案涵蓋 72 小時、1 分鐘間隔共 4,321 個狀態向量；相鄰檔案以 ~8 h 為間隔，彼此重疊約 88%。19 個檔案去重後提供 13,533 個唯一時間戳、跨越 9 天，是單檔的 3 倍資料量。每個時間戳均獨立選取最近的先行 TLE 傳播，消除長期外推累積誤差。

適用情境：

- 評估 SGP4 傳播模型對 Starlink 衛星的預測準確度
- 偵測星曆異常或機動事件（透過 RTN 殘差突增）
- 以 MEME 為地面真相，評估純 TLE 差分偵測的召回率與誤報率
- 建立訓練資料集，標記正常／異常飛行段

---

## 前置條件

### 必要套件

| 套件 | 用途 |
|------|------|
| `duckdb` | 讀取 TLE 資料庫 |
| `numpy` | 向量運算、RTN 分解、searchsorted |
| `pandas` | 資料操作、CSV 輸出 |
| `skyfield` | SGP4 傳播（`EarthSatellite`） |
| `starlink_ephemeris.parser` | 解析 MEME 星曆文字檔 |
| `matplotlib` | 圖表輸出（選用，缺少時自動略過） |

安裝：

```bash
pip install duckdb numpy pandas skyfield matplotlib
```

### 必要資料

| 資料 | 路徑（預設） | 說明 |
|------|-------------|------|
| MEME 星曆 | `data/raw/{sat_name}/*.txt` | SpaceX OEM 格式；每個檔案 72 h、1 min 間隔（4,321 行），以**發布** UTC 時間戳命名（格式：`YYYY-MM-DDTHH-MM-SSZ`），與檔案內的資料時間範圍不同 |
| TLE 資料庫 | `space_db.duckdb` | DuckDB，含 `raw_tle_archive` 資料表 |
| 衛星名稱對照 | `data/url_registry.csv` | `norad_id` ↔ `sat_name` 對照表 |

#### `raw_tle_archive` 資料表欄位（最低需求）

| 欄位 | 說明 |
|------|------|
| `norad_id` | NORAD 目錄編號（整數） |
| `line1` | TLE 第一行 |
| `line2` | TLE 第二行 |
| `epoch_utc` | TLE 曆元（UTC，TIMESTAMP 或 ISO 字串） |
| `object_name` | Space-Track 官方名稱（`STARLINK-XXXX`，可為 NULL） |

#### MEME 星曆目錄結構實例（STARLINK-30201）

```
data/raw/STARLINK-30201/
  2026-05-02T10-36-42Z.txt   # 涵蓋 2026-05-02 ~ 2026-05-05（72 h）
  2026-05-02T18-44-42Z.txt   # 涵蓋 2026-05-02 ~ 2026-05-05（與前檔重疊 88%）
  2026-05-03T03-00-42Z.txt
  …（共 19 個檔案）
  2026-05-08T20-08-42Z.txt   # 最新檔，涵蓋至 2026-05-11
```

去重後：13,533 個唯一時間戳，跨度 2026-05-02 ~ 2026-05-11（9 天）

---

## 使用方法

```bash
# 預設：殘差比較（全部檔案 + 每時間戳選取最佳 TLE）
python compare_tle_vs_ephemeris.py

# 同時執行殘差比較 + 機動偵測評估
python compare_tle_vs_ephemeris.py --maneuver-detection

# 只執行機動偵測（略過殘差 CSV，速度較快）
python compare_tle_vs_ephemeris.py --maneuver-detection --no-residuals

# 機動偵測：只計算大型機動（|Δa| ≥ 5 km）的召回率
python compare_tle_vs_ephemeris.py --maneuver-detection --maneuver-min-da 5

# 指定資料根目錄與資料庫
python compare_tle_vs_ephemeris.py --data-root data --db space_db.duckdb

# 只處理前 10 顆衛星（測試用）
python compare_tle_vs_ephemeris.py --max-sats 10

# 不產生殘差 CSV（速度較快）
python compare_tle_vs_ephemeris.py --no-residuals

# 不產生圖表
python compare_tle_vs_ephemeris.py --no-plot

# 為誤差最大的前 10 顆衛星產生 RTN 圖
python compare_tle_vs_ephemeris.py --rtn-top 10

# 略過 RTN 圖
python compare_tle_vs_ephemeris.py --rtn-top 0

# 舊版行為：只處理最新一個星曆檔、每顆衛星配一個 TLE
python compare_tle_vs_ephemeris.py --latest-only
```

### 命令列參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--data-root` | `data/` | 資料根目錄 |
| `--db` | `space_db.duckdb` | DuckDB 資料庫路徑 |
| `--registry` | `{data-root}/url_registry.csv` | 衛星名稱對照 CSV |
| `--out-dir` | `{data-root}/comparison/` | 輸出目錄 |
| `--max-sats` | 不限 | 限制處理衛星數（測試用） |
| `--no-residuals` | 預設**輸出** CSV | 加上此旗標則略過殘差 CSV 輸出（加速執行） |
| `--no-plot` | 預設**產生**圖表 | 加上此旗標則略過所有圖表輸出 |
| `--rtn-top N` | `5` | 為誤差最大的 N 顆衛星產生 RTN 圖；`0` 略過 |
| `--latest-only` | 停用 | 只用最新一個星曆檔（legacy 模式），每顆衛星配一個 TLE |
| **`--maneuver-detection`** | 停用 | 啟用機動偵測模組：MEME 快照差分 + TLE 差分，以 MEME 為地面真相，計算 TPR/FPR/ROC-AUC/AP/F1 |
| **`--maneuver-min-da KM`** | `0.0` | MEME 正例最小 \|Δa\| 閾值（km）。`0`=任何 flagged indicator；`1`=小型以上；`5`=中型以上；`10`=大型機動 |

---

## 執行流程

```
1. 讀取 url_registry.csv，建立 norad_id ↔ sat_name 對照
        ↓
2. 掃描 data/raw/{sat_name}/ 收集所有 .txt 檔案
   （--latest-only：只取最新一個）
        ↓
3. Pre-scan：解析每顆衛星的第一個與最後一個星曆檔
   → 取得觀測窗口 (ephem_start, ephem_end)
        ↓
4. 批次查詢 DuckDB raw_tle_archive
   • 預設：query_tles_in_range → 取得窗口內所有 TLE（含 2 天前緩衝；近重複去重）
   • --latest-only：query_best_tle → 每顆衛星單一最佳 TLE
        ↓
5. 逐顆衛星處理（process_satellite）：
   a. load_all_meme：concat 所有星曆檔，去重保留最新預測
   b. propagate_with_best_tles：np.searchsorted 向量化找最近先行 TLE；
      按 TLE index 分組後，覆蓋同一段的時間戳批次傳播（每 TLE 只呼叫一次
      propagate_tle，避免逐點建立 SGP4 物件的效能損耗）
   c. compute_residuals：inner join，計算 ECI 殘差 + RTN 分解
   d. 彙整統計摘要（n_files, ephem_span_days, n_tles_used）
        ↓
6. 輸出殘差 CSV（summary, residuals）
        ↓
7. 輸出殘差圖表（fleet overview, time-series, ECDF, RTN）

    ↓（若 --maneuver-detection）

8. 逐顆衛星執行雙軌機動偵測：
   a. detect_meme_maneuvers：從各星曆檔首個狀態向量差分 Keplerian 根數，
      J2 RAAN 修正後計算複合評分；score > 1.0 → flagged（MEME 地面真相）
   b. detect_tle_maneuvers：從連續 TLE 直接解析 Kozai mean elements，
      同樣閾值邏輯；僅保留 MEME 窗口內的事件
        ↓
9. build_classification_dataset：兩事件列表對齊至 8 h 固定網格
   y_true = MEME flagged；y_score = 對應 bin 內最大 TLE 評分
        ↓
10. compute_detection_metrics（艦隊級與每顆衛星）：
    TPR / FPR @ score≥1.0、ROC-AUC、Average Precision、F1-macro、Youden 最優閾值
        ↓
11. 輸出機動偵測 CSV（meme_maneuvers, tle_maneuvers, classification, sat_metrics）
12. 輸出 ROC + PR 曲線圖（--no-plot 略過）
```

---

## 核心函數說明

### 殘差比較模組

---

#### `load_registry(registry_csv)`

讀取 `url_registry.csv`，回傳以 `norad_id` 為索引的 DataFrame（含 `sat_name` 欄）。

---

#### `find_latest_ephemeris(sat_dir)`

回傳衛星目錄下檔名最大的 `.txt` 檔（= 最新發布的預測）。`--latest-only` 模式使用。目錄不存在或無 `.txt` 檔時回傳 `None`。

---

#### `find_all_ephemeris_files(sat_dir)`

回傳衛星目錄下所有 `.txt` 檔，依檔名（= 發布時間戳）升序排列（舊 → 新）。預設模式使用。

---

#### `load_all_meme(sat_name, ephem_files)`

**功能**：解析並合併多個 MEME 星曆檔，去重後回傳完整時序。

**處理邏輯**：
1. 依 `ephem_files` 列表順序（舊 → 新）逐一解析
2. 所有檔案 concat 後，對重複時間戳以 `drop_duplicates(keep="last")` 保留最新預測
3. 回傳以 `t`（UTC datetime）排序的 DataFrame

**資料特性**（以 STARLINK-30201 為例）：

| 指標 | 數值 |
|------|------|
| 每個檔案涵蓋範圍 | 72 小時 |
| 時間解析度 | 1 分鐘 |
| 每個檔案行數 | 4,321 |
| 相鄰檔案重疊率 | ~88% |
| 19 個檔案去重後 | 13,533 個唯一時間戳 |
| 總跨度 | 9 天 |

---

#### `query_best_tle(con, norad_id_to_ephem_start)`

**用途**：`--latest-only` 模式的單一 TLE 選取（legacy）。

**邏輯**：批次取出所有相關 NORAD ID 的 TLE，Python 端選取最佳：
- 優先：`epoch_utc ≤ ephem_start` 中最近的（觀測前 TLE）
- Fallback：最早的觀測後 TLE（執行期間記錄 WARNING）

---

#### `query_tles_in_range(con, norad_id_to_window, pre_window_days=2.0)`

**用途**：預設模式的多 TLE 批次查詢。

**邏輯**：
1. 批次取出所有衛星在窗口內（含 2 天前緩衝）的全部 TLE
2. 對 epoch 差 < 1 秒的近重複 TLE 進行去重
3. 若窗口內無 TLE，Fallback 至該衛星的全部 TLE 存檔
4. 回傳 `dict[norad_id → DataFrame]`，每顆衛星的 DataFrame 依 `epoch_utc` 升序排列

> **注意**：`space_track_name`（如 `STARLINK-1008`）是 Space-Track 的官方序號，與 MEME 內部名稱（如 `STARLINK-32283`）不同。跨資料源比對請一律使用 `norad_id`。

---

#### `propagate_tle(line1, line2, sat_name, times_utc, ts)`

使用 Skyfield `EarthSatellite.at()` 在指定時間戳陣列傳播單一 TLE，回傳 ECI（GCRS）位置/速度 DataFrame。

---

#### `propagate_with_best_tles(meme_df, tle_df, sat_name, ts)`

對每個 MEME 時間戳獨立選取最佳 TLE 進行 SGP4 傳播：
1. `np.searchsorted` 向量化找最近先行 TLE
2. 按 TLE index 分組批次傳播（每組呼叫一次 `propagate_tle`）
3. 消除單一 TLE 長期外推誤差；9 天窗口中每日使用最近 TLE

---

#### `_rtn_basis(rx, ry, rz, vx, vy, vz)`

從 ECI 位置/速度陣列計算 RTN 單位向量（R：徑向外；N：角動量方向 r×v；T：順軌道 N×R）。位置或角動量為零時拋出 `ValueError`。

---

#### `compute_residuals(meme, tle)`

在時間戳 `t` 上 inner join，計算 TLE − MEME 差值（ECI 殘差 + RTN 分解）。

| 欄位 | 說明 |
|------|------|
| `dr_x/y/z` | ECI 位置殘差 (km) |
| `dv_x/y/z` | ECI 速度殘差 (km/s) |
| `pos_err_km` | 3D 位置誤差範數 |
| `vel_err_kms` | 3D 速度誤差範數 |
| `dr_r_km` | 徑向殘差 |
| `dr_t_km` | 順軌道殘差（機動偵測最敏感分量） |
| `dr_n_km` | 交叉軌道殘差 |

---

#### `process_satellite(norad_id, sat_name, ephem_files, sat_tle_df, ts, save_residuals)`

整合單顆衛星的完整殘差比較流程，回傳 `(summary_dict, residuals_df | None)`。

**可能的 `status` 值**：

| status | 原因 |
|--------|------|
| `ok` | 成功完成比較 |
| `empty_ephemeris` | 所有檔案解析成功但無有效資料點 |
| `no_tle` | 資料庫無此衛星的 TLE |
| `no_propagation` | 所有 TLE 段傳播均失敗 |
| `sgp4_error: …` | 傳播過程中拋出例外 |
| `no_match` | 時間戳無任何交集 |

---

### 機動偵測模組（`--maneuver-detection`）

---

#### `_meme_first_state(path)`

只讀取單一 MEME 星曆檔的**第一個**有效狀態向量（遇第一筆即停止），取得該時刻的 ECI 位置/速度。速度快，用於機動偵測的快照採集；完整星曆由 `load_all_meme` 負責。

---

#### `_eci_to_elements(rx, ry, rz, vx, vy, vz)`

將 ECI 狀態向量轉換為 Keplerian 軌道根數：
- 半長軸 `a`（km）：由 Vis-viva 方程計算
- 離心率 `e`
- 傾角 `i`（度）
- 升交點赤經 `raan`（度）

---

#### `_j2_raan_drift(a, e, i_deg, dt_s)`

解析計算 J2 地球扁率引起的 RAAN 世俗漂移（度）：

$$\frac{d\Omega}{dt} = -\frac{3}{2}\, n\, J_2 \left(\frac{R_e}{p}\right)^2 \cos i$$

其中：
- $n$：平均角速度（rad/s）
- $J_2 = 1.08263 \times 10^{-3}$：地球 J2 係數
- $R_e$：地球赤道半徑（km）
- $p = a(1 - e^2)$：**半通徑**（km）
- $i$：軌道傾角（度）

機動偵測中，所有 ΔRAAN 測量均扣除此預期漂移，保留非引力殘差。

---

#### `_maneuver_score(da, di, de, draan_res)`

計算綜合機動評分（連續值，≥ 1.0 視為觸發）：

```
score = |da| / da_thr  +  |di| / di_thr  +  |de| / de_thr  +  |draan_res| / raan_thr
```

各分量獨立觸發即足以使 `score > 1.0`。各閾值為程式碼中的模組常數：

| 分量 | 閾值變數 | 預設值 | 捕捉的機動類型 |
|------|----------|-------:|--------------|
| Δa | `da_thr` | **0.5 km** | 切向機動（最常見） |
| Δi | `di_thr` | **0.01°** | 面外機動（需主動推力） |
| Δe | `de_thr` | **0.0001** | 非圓化機動 |
| ΔRAAN_res | `raan_thr` | **0.02°** | J2 無法解釋的面外擾動 |

> **注意**：以上閾值是針對 Starlink（500–600 km LEO）校準的預設值。GEO 或 MEO 衛星的自然攝動量級不同，需重新調整。

---

#### `detect_meme_maneuvers(sat_name, ephem_files)`

**MEME 機動偵測器（地面真相）**。

**策略**：SpaceX 每次點火後都會重新生成 MEME 星曆，所以每個檔案的第一個狀態向量是一個軌道「快照」（~8 h 間隔）。連續兩個快照之間的軌道根數跳變，就是機動事件。

**流程**：
1. 對每個星曆檔呼叫 `_meme_first_state`，提取一個快照
2. `_eci_to_elements` 轉換為軌道根數
3. 相鄰快照差分：Δa、Δi、Δe、ΔRAAN_res（J2 修正後）
4. 計算複合評分；`score > 1.0` 標記為 `flagged = True`

**輸出欄位**：`sat_name, t_from, t_to, dt_h, da_km, di_deg, de, draan_res_deg, score, flagged, source='meme'`

---

#### `_parse_tle_at_epoch(line1, line2)`

從 TLE line1/line2 **直接解析** Kozai mean elements（不執行 SGP4 傳播）：
- 從 line2 讀取 `i`, `RAAN`, `e`
- 從 line2 的 mean motion（rev/day）經 Kepler 第三定律推算半長軸 `a`
- 從 line1 解析曆元

所得元素為 Kozai/Brouwer mean elements（與 MEME osculating elements 略有差異），但機動前後的跳變在兩種表示法下均清晰可見。

---

#### `detect_tle_maneuvers(sat_name, tle_df, t_start, t_end)`

**TLE 機動偵測器（被評估方）**。

對 TLE 窗口內的連續 TLE 對逐一計算 Keplerian 根數差分，使用與 `detect_meme_maneuvers` 相同的閾值邏輯。

- 僅保留 `t_from ∈ [t_start, t_end]` 的事件，確保與 MEME 時間對齊
- 向前取 2 天緩衝，確保第一個 MEME 窗口有先行 TLE 鄰居

**輸出欄位**：同 `detect_meme_maneuvers`，`source='tle'`

---

#### `build_classification_dataset(meme_ev, tle_ev, t_start, t_end, window_h=8.0, min_da=0.0)`

將兩個偵測器的事件列表對齊至 **8 h 固定網格**，建立二元分類資料集。

| 欄位 | 說明 |
|------|------|
| `t_bin` | 8 h 分箱起始時間 |
| `y_true` | 1 = 該箱內有 MEME 確認機動（地面真相） |
| `y_score` | 該箱內 TLE 複合評分的最大值（0.0 = 無 TLE 事件） |
| `n_meme_trans` | 該箱內 MEME 過渡事件數 |
| `n_tle_trans` | 該箱內 TLE 過渡事件數 |

`min_da > 0` 時，僅 MEME 事件中 \|Δa\| ≥ min_da 者才計為正例，用於過濾微型機動。

8 h 網格與 MEME 檔案間隔一致，確保每個 MEME 事件最多對應一個分箱。

---

#### `compute_detection_metrics(y_true, y_score)`

計算所有偵測評估指標（不依賴 sklearn，以梯形積分法手動計算 ROC/PR 曲線）：

| 指標 | 說明 |
|------|------|
| `tpr_at_thr1` | TPR（召回率）@ score≥1.0（自然操作點） |
| `fpr_at_thr1` | FPR（誤報率）@ score≥1.0 |
| `roc_auc` | ROC 曲線下面積 |
| `avg_precision` | PR 曲線下面積（Average Precision） |
| `f1_positive` | 正例 F1 @ Youden 最優閾值 |
| `f1_macro` | 宏平均 F1 @ Youden 最優閾值 |
| `optimal_threshold` | Youden's J 最優評分閾值 |
| `prevalence` | 正例率（正例箱 / 總箱數） |

---

#### `run_maneuver_detection(sat_entries, tle_pool, ...)`

機動偵測模組的主協調函式：
1. 對每顆衛星依序執行 MEME 偵測器 → TLE 偵測器 → 分類網格
2. 跨衛星彙整 `(y_true, y_score)` 計算艦隊級指標
3. 對有正例的衛星計算逐顆 ROC-AUC
4. 輸出所有 CSV 與報表；`--no-plot` 略過 ROC/PR 圖

---

## 輸出檔案

### 殘差比較輸出

#### `data/comparison/summary_{date}.csv`

每顆衛星一列的統計摘要。

| 欄位 | 說明 |
|------|------|
| `norad_id` | NORAD 目錄編號 |
| `sat_name` | SpaceX MEME API 內部名稱 |
| `space_track_name` | Space-Track 官方名稱（可為空） |
| `status` | 處理結果 |
| `n_files` | 處理的星曆檔案數 |
| `n_points` | 比較的狀態向量數 |
| `ephem_span_days` | 星曆覆蓋總天數（= 所有檔案去重後最晚時間戳 − 最早時間戳，非 nominal 涵蓋範圍加總） |
| `n_tles_used` | 傳播中實際被分配到至少一個時間戳的不重複 TLE 數量（epoch 差 < 1s 的近重複 TLE 已去重計為一筆） |
| `tle_epoch` | 代表性 TLE 曆元（最近先行 TLE；ISO 8601） |
| `tle_age_days` | 代表性 TLE 曆元到星曆起始的天數 |
| `ephem_start/end` | 星曆起始/結束時間 |
| `pos_err_mean/std/max_km` | 位置誤差統計 |
| `vel_err_mean/std/max_kms` | 速度誤差統計 |

#### `data/comparison/residuals_{date}.csv`

每個狀態向量一列的逐點殘差（`--no-residuals` 時略過）。

| 欄位 | 說明 |
|------|------|
| `norad_id, sat_name, t` | 識別欄位 |
| `r_x/y/z_m`, `r_x/y/z_t` | MEME / TLE 位置（km） |
| `v_x/y/z_m`, `v_x/y/z_t` | MEME / TLE 速度（km/s） |
| `dr_x/y/z`, `dv_x/y/z` | ECI 殘差 |
| `pos_err_km`, `vel_err_kms` | 3D 誤差範數 |
| `dr_r/t/n_km` | RTN 分解（`dr_t_km` 機動最敏感） |
| `tle_epoch` | 此時間戳實際使用的 TLE 曆元（逐行，非固定值） |
| `tle_age_days` | 此時間戳的 TLE 年齡（逐行計算） |

### 機動偵測輸出（`--maneuver-detection`）

#### `data/comparison/meme_maneuvers_{date}.csv`

所有衛星的 MEME 機動過渡事件（地面真相）。

| 欄位 | 說明 |
|------|------|
| `sat_name` | SpaceX 衛星名稱 |
| `t_from, t_to` | 過渡時間窗口（連續快照的時間對） |
| `dt_h` | 過渡間隔（小時，通常 ~8 h） |
| `da_km` | 半長軸變化量（km） |
| `di_deg` | 傾角變化量（度） |
| `de` | 離心率變化量 |
| `draan_res_deg` | J2 修正後 RAAN 殘差（度） |
| `score` | 複合評分（> 1.0 = flagged） |
| `flagged` | True/False |
| `source` | `'meme'` |

#### `data/comparison/tle_maneuvers_{date}.csv`

TLE 差分偵測器的所有機動事件，欄位與 `meme_maneuvers_*.csv` 相同，`source='tle'`。

#### `data/comparison/maneuver_classification_{date}.csv`

每顆衛星、每個 8 h 分箱的分類資料集。

| 欄位 | 說明 |
|------|------|
| `norad_id, sat_name` | 衛星識別 |
| `t_bin` | 分箱起始時間（8 h 間隔） |
| `y_true` | 1 = MEME 確認機動（地面真相） |
| `y_score` | TLE 複合評分（0 = 未偵測到） |
| `n_meme_trans` | 該箱內 MEME 過渡數 |
| `n_tle_trans` | 該箱內 TLE 過渡數 |

#### `data/comparison/maneuver_sat_metrics_{date}.csv`

每顆有機動事件的衛星的逐顆評估指標（欄位對應 `compute_detection_metrics` 的輸出）。

### 圖表輸出

所有圖表存於 `data/comparison/plots/`。

| 檔案 | 內容 |
|------|------|
| `fleet_overview_{date}.png` | 2×2 艦隊概覽（TLE 年齡 vs 誤差散點圖、誤差直方圖、最差 20 顆橫條圖） |
| `timeseries_{date}.png` | 3 面板時序圖（艦隊百分位帶、最差 5 顆、最佳 5 顆） |
| `ecdf_{date}.png` | 位置誤差與速度誤差的 CDF |
| `rtn_{sat_name}_{date}.png` | 單顆衛星的 4 面板 RTN + RSS 時序圖 |
| `maneuver_roc_pr_{date}.png` | **（`--maneuver-detection`）** 艦隊級 ROC 曲線 + PR 曲線，標注 AUC/AP/F1 等指標 |

> RTN 圖可事後從已儲存的 `residuals_*.csv` 重新繪製，使用 `plot_starlink_rtn.py`。

---

## 座標系統

| 資料來源 | 座標系 |
|----------|--------|
| MEME 星曆 | EME2000（J2000 ECI） |
| Skyfield SGP4 | GCRS（地心天球座標系） |

兩者在公里精度分析下可視為等同（差異 < 1 m），無需額外轉換。

---

## 機動偵測設計說明

### 為什麼 MEME 可作為地面真相

SpaceX 在每次軌道機動後都會重新生成並上傳新的 MEME 星曆，因此：

1. 相鄰兩個星曆檔案的發布間隔（~8 h）反映的是軌道狀態的重新評估時刻
2. 若第 N 個檔案與第 N+1 個檔案的首個快照之間出現超過閾值的 Δa 或 Δi，強烈暗示期間執行了機動
3. 這種「重新生成即機動」的邏輯讓 MEME 成為比公開 TLE 精度高一至兩個數量級的地面真相

### 8 h 分類網格的設計考量

- MEME 檔案的平均發布間隔約 8 h，因此每個 MEME 過渡事件最多對應一個 8 h 分箱
- TLE 更新頻率（~2–8 次/天）與 8 h 網格相近，同一分箱內多筆 TLE 事件取最大評分
- 以「分箱」而非「事件」作為評估單位，可公平比較稀疏的 MEME 事件與密集的 TLE 事件

### `--maneuver-min-da` 的用途

| 設定值 | 包含的機動類型 | 適用場景 |
|--------|--------------|----------|
| `0.0`（預設） | 任何 flagged indicator（包括小 Δi、Δe） | 最高召回率，包含微型機動 |
| `1.0` | \|Δa\| ≥ 1 km（小型以上機動） | 過濾 TLE 雜訊造成的假陽性 |
| `5.0` | \|Δa\| ≥ 5 km（中型機動） | 站保機動、碰撞規避等 |
| `10.0` | \|Δa\| ≥ 10 km（大型機動） | 僅評估軌道轉移、相位調整 |

---

## 名詞對照

| 英文 | 中文 | 說明 |
|------|------|------|
| TLE | 雙行軌道根數 | Space-Track 發布的標準軌道資料格式 |
| OEM | 軌道星曆訊息 | Orbit Ephemeris Message，CCSDS 502.0-B 標準格式；MEME 採用此格式封裝狀態向量 |
| MEME | SpaceX 精密星曆 | Mission Ephemeris，SpaceX 提供的高精度 OEM 星曆（EME2000 座標） |
| SGP4 | 簡化廣義擾動模型 4 | TLE 標準傳播演算法 |
| RTN | 徑向-順軌道-交叉軌道 | 衛星本體座標系 |
| ECI | 地心慣性座標系 | Earth-Centered Inertial |
| NORAD ID | NORAD 目錄編號 | 美國太空監視網路唯一衛星識別號 |
| Kozai mean elements | Kozai 平均根數 | 從 TLE 直接解析的元素，適合比較前後跳變 |
| 複合評分（score） | 機動評分 | 各指標超出閾值程度的加總，≥1.0 觸發旗標 |
| 8 h 分箱（bin） | 8 小時網格單元 | MEME/TLE 事件的對齊單位；與 MEME 發布間隔一致 |
| y_true | 地面真相標籤 | 1 = MEME 確認機動，0 = 無機動 |
| y_score | TLE 偵測評分 | 對應分箱內 TLE 複合評分的最大值 |
| ROC-AUC | ROC 曲線下面積 | TLE 偵測器整體辨別能力（不依賴閾值） |
| Average Precision | PR 曲線下面積 | 精確率-召回率的加權平均 |
| Youden's J | 約登指數 | TPR − FPR 最大點對應的最優閾值 |

---

## 注意事項

1. **多檔案 double parse**：Pre-scan 只解析每顆衛星的首尾兩個檔案取得窗口；`process_satellite` 再解析全部。效能可接受。

2. **重疊時間戳去重策略**：`load_all_meme` 保留最新預測（較晚發布的檔案），因為較新預測整合了更多追蹤觀測。需分析預測衰減時用 `--latest-only`。

3. **per-row TLE 記錄**：殘差 CSV 的 `tle_epoch` 和 `tle_age_days` 是逐行對應的實際使用 TLE，可直接分析 TLE 年齡與殘差的相關性。

4. **near-duplicate TLE 去重**：`query_tles_in_range` 對 `epoch_utc.round("s")` 去重，避免 epoch 差 < 1s 的近重複 TLE 造成不必要的分組分裂。

5. **時間戳精度**：MEME 與 TLE 傳播時間戳精度不同時（nanosecond vs microsecond），inner join 可能丟失資料行。若 match rate < 90% 會記錄 WARNING。出現此問題時，可在 `compute_residuals` 內 merge 前對兩個 DataFrame 的時間戳欄位執行 `.dt.round("us")` 統一精度後再 join。

6. **matplotlib 選用**：未安裝時所有圖表輸出自動略過，CSV 不受影響。

7. **RTN 分解基準**：RTN 單位向量以 MEME 星曆的位置/速度為參考，殘差為 TLE − MEME。`dr_t_km` 是切向機動最敏感分量，`dr_n_km` 反映面外機動。

8. **MEO/GEO 衛星**：預設超參數針對 Starlink（500–600 km LEO）設計，超過 1200 km 的衛星殘差特性不同（無大氣拖曳，SRP 主導），需另行校準。

9. **機動偵測與殘差比較的差異**：殘差比較需要 SGP4 傳播（計算密集）；`--maneuver-detection` 的 MEME 偵測路徑**不依賴 SGP4**（只讀取快照並差分根數），TLE 差分偵測路徑同樣不需 SGP4（直接解析 TLE mean elements，無需傳播），兩者計算成本都極低。搭配 `--no-residuals` 可只跑機動偵測，大幅縮短執行時間。

10. **艦隊級 vs 逐顆衛星 AUC**：艦隊級 AUC 以分箱數為權重（覆蓋長的衛星影響力更大）；`maneuver_sat_metrics_*.csv` 提供逐顆衛星的 AUC，更適合評估個別衛星的偵測效能。
