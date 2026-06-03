# maneuver_app.py 功能說明文件

## 總覽

`maneuver_app.py` 是一套以 **Streamlit** 建立的衛星機動偵測與軌道分析系統，支援
**LEO / MEO / GEO** 三類衛星，整合 TLE 歷史資料庫、F10.7 太陽輻射指數、多種精密星曆來源，並以互動式 Plotly 圖表呈現。

- **主資料庫**：`space_db.duckdb`（DuckDB，兩張主表）
- **精密星曆**：Starlink MEME、Galileo MGEX SP3、IDS DORIS SP3
- **前端框架**：Streamlit + Plotly
- **數值運算**：NumPy、SciPy（Lomb-Scargle、curve_fit）
- **軌道傳播**：sgp4（`Satrec.sgp4init` 直接由軌道元素初始化）

---

## 運行模式

應用程式在側邊欄（Sidebar）提供兩種模式切換：

| 模式 | 說明 | 入口函式 |
|---|---|---|
| **LEO / MEO 分析** | 多顆衛星批次分析，9 個分頁 | 主流程（`run_btn` 觸發） |
| **GEO 機動分析** | 單顆 GEO 衛星的經度漂移與 NS 機動 | `render_geo_page()` |

GEO 模式渲染後立即呼叫 `st.stop()`，不執行 LEO 程式碼。

---

## 資料庫結構

### `tle_table`（LEO/MEO 主表）
| 欄位 | 型別 | 說明 |
|---|---|---|
| `norad_id` | INTEGER | NORAD 衛星編號 |
| `epoch_jd` | DOUBLE | 元素曆元（儒略日） |
| `date_tag` | TIMESTAMP | 日期標籤（每日一筆） |
| `sma_km` | DOUBLE | 半長軸（km） |
| `eccentricity` | DOUBLE | 離心率 |
| `inclination_deg` | DOUBLE | 傾角（度） |
| `raan_deg` | DOUBLE | 升交點赤經（度） |
| `argp_deg` | DOUBLE | 近地點幅角（度） |
| `mean_anomaly_deg` | DOUBLE | 平均近點角（度） |
| `mean_motion` | DOUBLE | 平均運動（rev/day） |
| `energy` / `rmin_km` / `rmax_km` | DOUBLE | 軌道能量、近地點、遠地點 |

### `raw_tle_archive`（GEO / IDS 用，含 TLE 原始字串）
`tle_table` 所有欄位 + `object_name`、`line1`、`line2`、`epoch_utc`、`downloaded_at_utc`

---

## 全域常數

```python
SPACE_DB_PATH = "./space_db.duckdb"    # 可由環境變數 SPACE_DB_PATH 覆蓋
TABLE_NAME    = "tle_table"
MU            = 398600.4415            # km^3/s^2
R_EARTH       = 6371.0                 # km
F107_CACHE_FILE = "./f107_cache.csv"
COMPARISON_DIR         = "./data/comparison"         # MEME 殘差 CSV 目錄
GALILEO_COMPARISON_DIR = "./data/galileo_comparison" # Galileo SP3 殘差 CSV 目錄
GEO_MANEUVER_CSV       = "./data/geo_maneuvers/maneuver_candidates.csv"
```

Spiral 圖固定參數：`spiral_a = 0.5`、`spiral_b = 0.02`、`spiral_cmap = "hsv"`

---

## 函式索引

### F10.7 太陽輻射

#### `fetch_f107_data() → pd.DataFrame`
- 來源：`https://spaceweather.gc.ca/solar_flux_data/daily_flux_values/fluxtable.txt`
- 快取至 `f107_cache.csv`；若當日資料已存在則直接讀取。
- 欄位：`epoch`（datetime64）、`f107`（float，調整後日均太陽通量）。
- 下載失敗時回退至快取。

---

### 資料載入

#### `load_data(norad_id, start_date, end_date) → pd.DataFrame`
- 從 `tle_table` 查詢指定 NORAD ID 在日期範圍內的軌道元素。
- 返回依 `epoch` 排序、去重後的 DataFrame（每日一筆，保留最晚 `epoch_jd`）。

#### `load_geo_raw_series(norad_id, start_date, end_date) → pd.DataFrame`
- 從 `raw_tle_archive` 讀取 GEO 衛星 TLE 序列。
- 計算輔助欄位：`lambda_deg`（地理經度）、`drift_deg_day`（漂移率 °/day）。
- 每小時去重（1-hour bucket dedup）。

#### `load_geo_events(norad_id, start_date, end_date) → pd.DataFrame`
- 讀取 `data/geo_maneuvers/maneuver_candidates.csv` 中預計算的機動事件。
- 過濾指定 NORAD ID 與日期範圍。

#### `load_meme_residuals(norad_id, start_date, end_date) → pd.DataFrame`
- 從 `data/comparison/residuals_*.csv`（按檔名降序，取最新）載入 MEME 殘差。
- 以 DuckDB in-memory 做 NORAD ID 篩選，效率高於全量 Pandas 讀取。
- 欄位：`norad_id`、`sat_name`、`t`（UTC Timestamp）、`dr_r_km`、`dr_t_km`、`dr_n_km`、`pos_err_km`、`vel_err_kms`、`tle_epoch`、`tle_age_days`。

#### `load_galileo_sp3_residuals(sat_id, start_date, end_date) → pd.DataFrame`
- 同 MEME，但從 `data/galileo_comparison/residuals_*.csv` 讀取。
- `sat_id` 可為 NORAD int 或 PRN 字串（如 `"E11"`）；PRN 透過 `_GALILEO_PRN_NORAD` 字典轉換。
- 支援 Galileo 30 顆衛星（E02 ~ E36）。

#### `load_ids_precomputed(sat_name) → pd.DataFrame`
- 讀取 `./output_data/residuals/{sat_name}/residuals.csv`（由 `tle_ids_maneuver_pipeline` 產生）。

---

### 資料處理

#### `compute_delta_table(df_in) → pd.DataFrame`
- 輸入：`load_data()` 結果。
- 計算每日差分：`delta_sma_km`、`delta_inclination_deg`、`delta_raan_deg`、`delta_argp_deg`、`delta_mean_anomaly_deg`。
- 角度差分使用 `angle_diff_deg()`（wrap 到 ±180°）。

#### `calculate_ric_deltas(df) → pd.DataFrame`
- 計算 In-Track 與 Cross-Track 的估算 ΔV（m/s）：
  - **In-Track**：`dv_intrack = (v_mag / 2) × (ΔSMA / SMA) × 1000`
  - **Cross-Track**：`dv_crosstrack = v_mag × √(Δi² + (sin(i) × ΔΩ)²) × 1000`
  - `v_mag = √(μ / SMA)`（圓軌道近似）
- 對 `sma_km` 先做 3 點中心移動平均平滑。

#### `prepare_spiral_polar_data(df_raw) → tuple`
- 計算 Spiral Polar 圖所需的角度時序與半徑：
  - `theta_time`：基於觀測天數的時間角（0 → 2π）
  - `r_spiral = spiral_a + spiral_b × days_since_start`
  - `t_norm`：歸一化時間（用於顏色映射）

#### `ensure_datetime64ns(df, col) → pd.DataFrame`
- 確保指定欄位為 `datetime64[ns]` 型別（避免 merge_asof 型別衝突）。

---

### 機動偵測

#### `detect_maneuvers_refined_adaptive(df) → (df_out, event_df, mult)`
這是 LEO/MEO 主機動偵測演算法。

**流程：**
1. 排序去重、重採樣到日頻率（`resample("D").ffill()`）。
2. 計算 `sma_rate`（SMA 變化率 km/h）和 `sma_delta`（絕對差分 km）。
3. **依平均高度自適應調整參數**：

| 高度範圍 | mult | window | rate_mult | rate_floor |
|---|---|---|---|---|
| 300–500 km | 7.0 | 3 | 8.0 | 0.10 km/h |
| 500–600 km | 4.0 | 7 | 6.0 | 0.02 km/h |
| 600–700 km | 3.5 | 7 | 6.0 | 0.02 km/h |
| 700–1200 km | 3.0 | 10 | 4.0 | 0.005 km/h |
| ≥ 12000 km（MEO） | 2.5 | 21 | 3.0 | 0.0001 km/h |
| 其他 | 4.0 | 7 | 6.0 | 0.01 km/h |

4. 以滾動中位數計算殘差 z-score。
5. **雙重閾值**：`sma_delta ≥ delta_thr` 且 `|sma_rate| ≥ rate_thr`。
6. 連續候選點群集化，取峰值作為機動事件，記錄 `sma_direction`（raise/lower）。

#### `detect_ric_events(df, column, threshold_mult=5.0, alt_km=None) → pd.Series`
- 對 `dv_intrack` 或 `dv_crosstrack` 做 MAD z-score 異常偵測。
- 同時要求絕對值超過 `min_dv`：

| 高度 | min_dv |
|---|---|
| ≥ 12,000 km（MEO） | 0.005 m/s |
| < 500 km | 0.5 m/s |
| ≥ 700 km | 0.01 m/s |
| 其他 | 0.05 m/s |

#### `detect_maneuvers_rtn(resid_df, z_thr=None) → pd.DataFrame`
用於 MEME 殘差或 Galileo SP3 殘差的機動偵測。

**演算法：**
1. 計算 `dr_t_km` 和 `dr_n_km` 的逐步差分絕對值（km），除以時間間隔得到 km/h。
2. 對變化率做 MAD z-score。
3. `z_thr` 依 TLE 年齡自動選取：≤3天→4.0、≤7天→5.0、≤14天→6.0、>14天→7.0。
4. 連續觸發點（間距 ≤ 3 步）群集化，取 z-score 峰值。
5. 同小時的順軌道 / 交叉軌道事件合併為一筆。
- 返回欄位：`epoch`、`type`（in-plane / out-of-plane）、`step_km`、`step_rate_km_h`、`z_score`、`tle_age_days`。

#### `detect_ids_maneuvers(resid_df, ...) → pd.DataFrame`
用於 IDS SP3 殘差的機動偵測。

**參數（含預設值）：**
- `radial_thr = 0.3 km`、`in_track_thr = 1.0 km`、`cross_track_thr = 0.3 km`
- `zscore_thr = 3.0`、`window = 12`（滾動 z-score 視窗）、`min_sep_hrs = 6`

**演算法：**
1. 滾動視窗 z-score（均值 + 標準差）。
2. 絕對值閾值 OR z-score 閾值，任一觸發即標記。
3. 最小間距 `min_sep_hrs` 小時的群集化，記錄 `peak_dr_km`、`peak_abs_in_track_km` 等。

---

### GEO 輔助計算

#### `_geo_gmst(jd) → np.ndarray`
計算格林威治平恆星時（GMST）：`(280.46061837 + 360.98564736629 × T) % 360`，T 為 J2000.0 以來的儒略日。

#### `_geo_mean_lon(raan, argp, ma, jd) → np.ndarray`
計算 GEO 衛星地理平均經度：`λ = (Ω + ω + M − GMST) mod 360`，映射到 ±180°。

---

### 軌道傳播（IDS 使用）

#### `propagate_from_db_elements(con, norad_id, epochs) → pd.DataFrame`
- 從 DuckDB `raw_tle_archive`（或 fallback 至 `tle_table`）取得軌道元素。
- 對每個目標曆元，選取最近的先前元素，以 `Satrec.sgp4init()` 初始化（不需 TLE 字串）：
  - `no_kozai = √(μ / a³) × 60`（rad/min）
  - `tle_epoch_days = (epoch − 1949-12-31) / 86400`
- 返回 ECI 位置速度（TEME 座標）。

#### `compute_ids_ric_residuals(tle_states, ids_states) → pd.DataFrame`
- 以 `merge_asof`（tolerance 120s）配對 TLE 傳播結果與 IDS SP3 狀態向量。
- 計算 RIC 殘差（`_ids_eci_to_ric()` 建立旋轉矩陣）。
- 返回：`epoch`、`dr_km`、`radial_km`、`in_track_km`、`cross_track_km`、`tle_epoch_used`、`sgp4_error`。

**注意**：app 內的 `parse_ids_sp3_file()` 不做 TAI→UTC 時間校正，與 pipeline 版本（`download_ids.py`）有差異。pipeline 版本已套用 37 秒 TAI−UTC 修正。

---

### 繪圖函式

| 函式 | 說明 |
|---|---|
| `plot_dual_axis_sma_f107(df_final)` | 雙 Y 軸：SMA + F10.7 + 機動標記 |
| `plot_3d_orbit_scene(sma, inc, raan, id)` | 單圈靜態 3D 軌道（彩色地球 + 黃色軌道線） |
| `plot_3d_orbit_scene_multi(df_raw, id)` | 多時序 3D 軌道演變（RdBu 色漸層，舊→新） |

---

## UI 結構（LEO / MEO 模式）

### 側邊欄輸入
- NORAD ID（逗號分隔，支援多顆）
- 日期範圍（`date_input`）
- 移動平均視窗（MA slider, 1–14）
- 顯示原始取樣點（checkbox）
- 執行分析按鈕

### 主頁面 9 分頁

| 分頁 | 圖示 | 主要內容 |
|---|---|---|
| 1. 趨勢分析 | 📊 | SMA 折線 + F10.7 + 機動標記；指標：數據點、機動次數、最大 Δa |
| 2. RIC 速度變化 | 🚀 | `dv_intrack`（柱狀）+ `dv_crosstrack`（折線）；MAD 異常標記 |
| 3. 3D 軌道 | 🌍 | 多時序軌道演變，顏色由舊（紅）到新（藍） |
| 4. Δ 計算 | Δ | SMA + 四個角度元素每日差分；可下載 CSV |
| 5. Spiral Polar | 𖦹 | 四個角度在極座標中的螺旋時序分佈 |
| 6. 長軸旋轉週期 | ⬯ | Lomb-Scargle 頻譜 + 線性+正弦模型擬合；輸出週期、振幅、斜率 |
| 7. MEME 殘差 | 🛰️ | RTN 三面板殘差圖；偵測機動；TLE vs MEME 方法對比表 |
| 8. Galileo SP3 | 🪐 | RTN 三面板（~29,600 km MEO）；三方法偵測對比表 |
| 9. IDS 驗證 | 🌍 | DORIS SP3 Ground Truth；RIC 殘差三面板；機動候選表；IDS 衛星一覽 |

---

## UI 結構（GEO 模式）

`render_geo_page()` 渲染三個子分頁：

| 子分頁 | 內容 |
|---|---|
| 📡 經度 & 漂移率 | 雙面板：λ(°) + drift(°/day)；EW 確認/未確認標記；TLE 空白區間陰影 |
| ↕ 傾角 (NS) | 傾角時序 + NS 機動標記（星形符號）；確認 NS 事件表格 |
| 📋 事件表 | 所有類型事件彙整；可下載 CSV |

機動類型對應表：

| 類型 | 偵測條件 |
|---|---|
| `EW` | 漂移率符號翻轉，`|Δdrift| > 0.02 °/day` |
| `NS` | 傾角步進 `Δi < −0.003°`，附 RAAN 殘差確認 |
| `REPOSITIONING` | 中值漂移 > 0.05 °/day 且最大偏離 > 2° |
| `DISPOSAL` | SMA 持續超過 42,300 km |
| `TLE_GAP` | 相鄰 TLE 間距 > 4 天 |

---

## IDS（DORIS）支援衛星一覽

| NORAD ID | 衛星名稱 | IDS 代碼 | 狀態 | 資料起始 | 資料截止 |
|---|---|---|---|---|---|
| 22076 | topex-poseidon | top | 🔴 已退役 | 1992-09-25 | 2006-01-18 |
| 26997 | jason-1 | ja1 | 🔴 已退役 | 2001-12-07 | 2013-07-01 |
| 27386 | envisat | en1 | 🔴 已退役 | 2002-03-01 | 2012-04-08 |
| 33105 | jason-2 | ja2 | 🔴 已退役 | 2008-06-20 | 2019-10-01 |
| 36508 | cryosat-2 | cs2 | 🟢 運作中 | 2010-04-08 | — |
| 37781 | hy-2a | h2a | 🔴 已退役 | 2011-08-16 | 2023-01-10 |
| 39086 | saral | srl | 🟢 運作中 | 2013-02-25 | — |
| 41240 | jason-3 | ja3 | 🟢 運作中 | 2016-01-17 | — |
| 41335 | sentinel-3a | s3a | 🟢 運作中 | 2016-02-16 | — |
| 43437 | sentinel-3b | s3b | 🟢 運作中 | 2018-04-25 | — |
| 44750 | hy-2c | h2c | 🟢 運作中 | 2020-09-21 | — |
| 46984 | sentinel-6a | s6a | 🟢 運作中 | 2020-11-21 | — |
| 48621 | hy-2d | h2d | 🟢 運作中 | 2021-05-19 | — |
| 54754 | swot | swo | 🟢 運作中 | 2022-12-16 | — |

---

## Galileo PRN → NORAD 對照

| PRN | NORAD | PRN | NORAD | PRN | NORAD |
|---|---|---|---|---|---|
| E02 | 41549 | E11 | 37846 | E26 | 40544 |
| E03 | 41860 | E12 | 37847 | E27 | 43057 |
| E04 | 41861 | E13 | 43567 | E28 | 67160 |
| E05 | 41862 | E14 | 40129 | E29 | 59598 |
| E06 | 59600 | E15 | 43564 | E30 | 40890 |
| E07 | 41859 | E16 | 61182 | E31 | 43058 |
| E08 | 41175 | E18 | 40128 | E32 | 67162 |
| E09 | 41174 | E19 | 38857 | E33 | 43565 |
| E10 | 49810 | E21 | 43055 | E34 | 49809 |
| — | — | E23 | 61183 | E36 | 43566 |
| — | — | E25 | 43056 | — | — |

---

## 資料流程

```
DuckDB (space_db.duckdb)
  └─ tle_table / raw_tle_archive
       ├─ load_data() ──────────────────────────────────────────┐
       │    └─ detect_maneuvers_refined_adaptive()              │
       │         └─ [SMA 差分 + 高度自適應 MAD z-score]         │
       ├─ calculate_ric_deltas() ── dv_intrack / dv_crosstrack  │
       └─ load_geo_raw_series() ── λ, drift_deg_day             │
                                                                 ▼
外部精密星曆                                              Plotly 互動圖表
  ├─ MEME CSV ── load_meme_residuals()                    ├─ 9 分頁（LEO/MEO）
  │    └─ detect_maneuvers_rtn() [MAD z-score on step]   └─ 3 子分頁（GEO）
  ├─ Galileo SP3 CSV ── load_galileo_sp3_residuals()
  │    └─ detect_maneuvers_rtn()
  └─ IDS DORIS SP3 ── parse_ids_sp3_file()
       └─ propagate_from_db_elements() [SGP4 sgp4init]
            └─ compute_ids_ric_residuals() [RIC frame]
                 └─ detect_ids_maneuvers()

F10.7 (NRC Canada) ── fetch_f107_data() ── 快取 CSV
  └─ merge_asof → df_final（與 TLE 時序對齊）
```

---

## 關鍵已知限制

1. **App 內 SP3 TAI 時間**：`parse_ids_sp3_file()` 未做 TAI→UTC 37 秒修正（pipeline 版本已修正）。
2. **座標系**：`propagate_from_db_elements()` 輸出 TEME（SGP4），IDS SP3 使用 ITRF。App 內 RIC 殘差計算未做 TEME→ITRF 轉換（pipeline 版本的 `compare_residuals.py` 已修正）。
3. **GEO SMA 偵測**：GEO 模式使用 `load_geo_raw_series()` 讀取 `raw_tle_archive`，需有 `line1`/`line2` 欄位；若 DB 僅有 `tle_table`（無 TLE 字串），GEO 時序圖會顯示空白。
4. **MEME 機動計數**：`load_meme_residuals()` 在三方法對比表中會被再次呼叫一次（重複 I/O）。
5. **Streamlit `query_params` 相容性**：已做 `st.query_params` vs `st.experimental_get_query_params()` 相容包裝。
