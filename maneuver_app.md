# maneuver_app.py 功能說明文件

*最後更新：2026-07-05（新增 ML 模型偵測頁、軌道自動分類/路由、SSA-RAG 問答整合、SMA/高度並列顯示、TLE 缺口守門）*

## 總覽

`maneuver_app.py` 是一套以 **Streamlit** 建立的衛星機動偵測與軌道分析系統，支援
**LEO / MEO / GEO** 三類衛星，整合 TLE 歷史資料庫、F10.7 太陽輻射指數、多種精密星曆來源、
**XGBoost / LightGBM 機器學習機動偵測模型**與 **SSA-RAG 知識庫問答系統**，並以互動式 Plotly 圖表呈現。

- **主資料庫**：`space_db.duckdb`（DuckDB，兩張主表）
- **精密星曆**：Starlink MEME、Galileo MGEX SP3、IDS DORIS SP3
- **前端框架**：Streamlit + Plotly
- **數值運算**：NumPy、SciPy（Lomb-Scargle、curve_fit）
- **軌道傳播**：sgp4（`Satrec.sgp4init` 直接由軌道元素初始化）
- **機器學習**：XGBoost（軌道相位/活動強度分類）、LightGBM（Plan B 機動偵測，26 天聚合特徵）
- **RAG 問答**：`ssa_rag_client.py` 對接外部 SSA-RAG 服務（`F:\GitHub\SSA-RAG`），將偵測結果自動轉自然語言送查

---

## 運行模式

應用程式在側邊欄（Sidebar）提供三種模式切換：

| 模式 | 說明 | 入口函式 |
|---|---|---|
| **LEO / MEO 分析** | 多顆衛星批次分析，10 個分頁；**會自動偵測軌域並路由** | 主流程（`run_btn` 觸發） |
| **🤖 ML 模型偵測** | XGBoost + LightGBM 機動機率推論、滾動趨勢圖 | `render_ml_page()` |
| **💬 SSA 知識庫問答** | 直接對 SSA-RAG 服務提問（不經偵測結果） | `render_ssa_rag_page()` |

**GEO 機動分析已不是可手動選擇的模式**：使用者一律從「LEO / MEO 分析」輸入 NORAD ID，
程式先以 `classify_orbit()` 依中位數半長軸判斷軌域，若歸類為 `GEO` 或 `GEO+`，
自動改呼叫 `render_geo_page()` 渲染 GEO 專屬視圖（經度漂移、NS 機動等）並 `continue` 到下一顆衛星；
否則才會跑 LEO/MEO 的機動偵測與 10 個分頁。`render_ml_page()` 亦會做同樣的軌域判斷，
但只顯示警告（模型僅在 LEO 高度訓練），不會中斷推論。

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
TLE_GAP_SUPPRESS_H = 48.0              # LightGBM 判定：視窗內最長 TLE 缺口超過此值即壓制為非機動
F107_CACHE_FILE = "./f107_cache.csv"
COMPARISON_DIR         = "./data/comparison"         # MEME 殘差 CSV 目錄
GALILEO_COMPARISON_DIR = "./data/galileo_comparison" # Galileo SP3 殘差 CSV 目錄
GEO_MANEUVER_CSV       = "./data/geo_maneuvers/maneuver_candidates.csv"
RAG_DEFAULT_URL        = "http://127.0.0.1:8000"     # SSA-RAG 服務位址（由另一個 session 啟動）
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

#### `format_sma_with_alt(sma_km, decimals=0) → str`
- LEO/MEO 半長軸顯示慣例：SMA 與高度並列，例如 `6,771km(高度400km)`（高度 = SMA − 6371 km）。
- 用於軌道分類參數表、Δ 計算表等所有以文字/表格呈現半長軸數值的地方。

#### `sma_axis_ticks(y_min, y_max, n=6) → (tickvals, ticktext)`
- 回傳 Plotly Y 軸的自訂刻度，每個刻度文字為兩行：SMA 數值 + `(高度NNN)`。
- 套用於「趨勢分析」主圖、「Δ 計算」時序圖、ML 頁「趨勢分析」滾動推論圖的 SMA 座標軸。

---

### 軌道分類

#### `classify_orbit(a_km, e, i_deg, raan_deg=None, argp_deg=None, ...) → dict`
四層軌道分類器，輸入平均（TLE 導出）克卜勒六參數，輸出每一層的分類標籤、信心分數（0–1）與判斷理由：

1. **高度類別**（`altitude_class`）：`LEO` / `MEO` / `GEO` / `GEO+` / `HEO`
   - `GEO` 窗口：`41600 ≤ a_km ≤ 42650`；`e > 0.25` 一律歸 `HEO`；`a_km < 8000` 歸 `LEO`；
     介於 LEO–GEO 窗口之間歸 `MEO`；超過 GEO 窗口歸 `GEO+`（可能為墓地軌道）。
2. **偏心率形狀**（`eccentricity_class`）：`circular` / `elliptical` / `highly-elliptical`
3. **幾何約束**（`geometry_class`）：`equatorial` / `polar` / `sun-synchronous_candidate` /
   `inclined-geosynchronous` / `general-inclined`
4. **任務狀態**（`mission_state`）：`operational` / `transfer` / `graveyard` / `formation`

**用途**：(1) 「軌道分類」分頁顯示四張分類卡片；(2) LEO/MEO 主流程用其 `altitude_class`
判斷是否要自動路由到 GEO 頁；(3) `render_ml_page()` 用其判斷是否顯示「模型訓練域限制」警告。

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

### ML 模型推論（🤖 ML 模型偵測頁）

#### `load_ml_models() → dict`（`@st.cache_resource`）
- 載入 XGBoost（`models/orbital_phase_v1.ubj`、`models/activity_level_v1.ubj`、`models/model_meta_v1.json`）
  與 LightGBM Plan B（`Orbital_Maneuver_V2/models_plan_b/lgbm_maneuver_v1.pkl` + `feature_names.json`）。
- 任一模型檔不存在時該模型標記未載入，頁面會顯示對應警告而非報錯。

#### `compute_xgb_features(df) → dict | None`
- 由 30 天 TLE 統計量計算 XGBoost 輸入特徵（< 3 筆 TLE 時回傳 `None`）。
- XGBoost 有兩顆子模型：**軌道相位**（4 類：deployment/raising/operational/high-shell，
  CV Acc 96.1%）與**活動強度**（二元：主動提升中 vs 穩定維持，依 `sma_slope_km_day` 訓練）。

#### `compute_lgbm_plan_b_features(df, f107_mean=nan) → dict | None`
LightGBM Plan B 的 20 個 26 天聚合特徵計算函式，關鍵欄位：

| 特徵 | 說明 |
|---|---|
| `net_da_km` / `max_da_km` / `da_std` | 半長軸累積/單筆最大/標準差變化 |
| `max_di_deg` / `max_draan_res_deg` | 傾角、J2 校正 RAAN 殘差單筆最大變化 |
| `neg_streak` / `total_drop_km` / `monotone_decay` | 連續下降筆數/總降幅/單調衰減旗標（純大氣阻力判定） |
| `flag_rate` / `n_flagged` | 逐筆轉移超過 `_ada_thr()` 高度自適應閾值或 Δi/Δe/ΔRAAN 閾值的比例/筆數 |
| `da_monotonic_decay` | 較嚴格的「純阻力衰減」旗標（`frac_neg_da≥0.85` 且無單筆大跳變且淨變化<−2km） |
| `mean_tle_gap_h` / `max_tle_gap_h` | 視窗內 TLE 間隔平均/最大值（**新增的 TLE 缺口守門即依賴此欄位**） |
| `dv_net_ms` / `bstar_f107_normalized` | 估算淨 Δv、B\* 對 F10.7 正規化值 |

#### `compute_lgbm_rolling_predictions(df, model, feat_cols, f107_mean, window_days=26, step_days=3) → pd.DataFrame`
- 以固定長度視窗（預設 26 天，步進 3 天）滑過整段 TLE 資料，逐視窗呼叫上述特徵函式並推論 `p_maneuver`。
- 回傳欄位：`window_center`、`p_maneuver`、`net_da_km`、`flag_rate`、`da_monotonic_decay`、`n_tle`、`max_tle_gap_h`。

#### TLE 資料缺口守門（`TLE_GAP_SUPPRESS_H = 48.0` 小時）
**問題背景**：當視窗內出現長時間 TLE 追蹤缺口時，RAAN 殘差是用 J2 長期進動率乘以時間間隔、
從觀測到的 RAAN 變化中線性外推扣除而得；缺口越長，外推誤差越大，足以讓單筆轉移的
`max_draan_res_deg` 假性超過判定閾值，被 LightGBM 誤判為高機率機動（實際案例：
NORAD 44349，缺口 62–163 小時導致連續兩段 p_maneuver≈0.99 的假警報，而同期半長軸其實只是
平緩的大氣阻力衰減）。

**處理方式**：不論原始 `p_maneuver` 多高，只要該視窗 `max_tle_gap_h > TLE_GAP_SUPPRESS_H`，
一律將最終判定壓制為非機動。套用位置：
- 單次推論（「🔍 LightGBM 機動偵測」子分頁）：原本的紅／綠警示框，遇到「機率高但缺口過大」時
  改顯示橘色框「🟠 最長 TLE 缺口 Nh 超過 48h 門檻，判定壓制為非機動」，並在指標列顯示缺口小時數。
- 滾動趨勢圖（「📈 趨勢分析」子分頁）：`roll_df["gap_suppressed"]` / `roll_df["is_alert"]`
  兩個衍生欄位；「高機率窗口」統計改用 `is_alert`（已扣除被壓制的視窗）；圖上以橘色標記／
  橘色背景區塊標示「原本會誤報但已被壓制」的視窗，另有獨立指標「資料缺口壓制（>48h）」計數。
- SSA-RAG 自動解說（`build_ml_maneuver_narrative()`）：壓制發生時會在送出的描述文字中加一句
  說明，避免 RAG 把已被系統判定為誤報的視窗當成真實機動來解說。

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

### SSA-RAG 整合與對話信箱

`maneuver_app.py` 是 SSA-RAG（`F:\GitHub\SSA-RAG`，另一個 session 維護的獨立 FastAPI 服務）的
**Client 端**。服務由 Server 端 session 啟動（本 app 不會自行 `uvicorn`），本 app 只透過
`ssa_rag_client.py`（HTTP client）查詢。

#### `render_rag_auto_explain(narrative, base_url=RAG_DEFAULT_URL, topic="maneuver")`
- 先呼叫 `_rag_health_cached()`（`@st.cache_data(ttl=60)`）做健康檢查；服務未上線時只顯示一行
  提示文字並直接返回，不渲染整個解說區塊（因此如果服務剛啟動、快取還沒過期，畫面上可能
  只看到不起眼的一行警示，而非完整解說）。
- 服務上線則呼叫 `_rag_ask_cached()`（`@st.cache_data(ttl=3600)`，同一段描述文字一小時內只查一次）
  取得 `answer` / `confidence` / `sources`，並以 `st.info` + 信心度圖示 + 來源清單展開區呈現。

#### 各分析頁的自動解說觸發時機
| 頁面 | 觸發函式 | 是否可關閉 |
|---|---|---|
| LEO/MEO「📊 趨勢分析」 | `build_tle_maneuver_narrative()` | 否，一律自動（唯一顯示條件＝服務健康） |
| GEO「📡 經度 & 漂移率」 | `build_geo_maneuver_narrative()` | 是，側邊欄 `rag_auto` 勾選框 |
| ML「🔍 LightGBM 機動偵測」 | `build_ml_maneuver_narrative()` | 是，側邊欄 `rag_auto` 勾選框 |

三個 `build_*_narrative()` 函式都會把「方向判讀」（Δa 正負、機動 vs 大氣阻力等）由程式先算好寫進
文字描述，而不是讓 LLM 自己從數字猜方向——這是因為 LLM 容易被檢索到的文件主題牽著走，
即使 Δa 是負值也可能照樣答「軌道抬升」。

#### `render_dialogue_panel()` / `app_dialogue_client.DialogueClient`
- 側邊欄「💬 App 對話（↔ SSA-RAG Server）」展開區，走**共用 JSONL 信箱**
  （`F:\GitHub\SSA-RAG\logs\app_dialogue.jsonl`），純粹是兩個 App 之間的操作協調
  （例如「服務是否啟動」），不經過 RAG 問答流程本身。任一方送出 `#Over#` 結束對話；
  `#Echo#` 是對方收訊後的送達確認。

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
- NORAD ID（逗號分隔，支援多顆；若判定為 GEO/GEO+ 會自動路由到 GEO 視圖，見下方說明）
- 日期範圍（`date_input`）
- 移動平均視窗（MA slider, 1–14）
- 顯示原始取樣點（checkbox）
- 執行分析按鈕
- SSA-RAG 服務位址輸入框（自動解說一律開啟，僅離線時降級為一行提示）

### 軌域自動路由（新）

`run_btn` 迴圈中，每顆衛星先用 `load_data()` 取回 TLE 後，立刻以中位數 a/e/i 呼叫
`classify_orbit()`。若 `altitude_class` 為 `GEO` 或 `GEO+`：顯示
「🛰️ NORAD {id} 軌道要素（a≈… km）判定為 GEO 軌域，自動切換為 GEO 機動分析視圖。」，
接著呼叫 `render_geo_page()` 並 `continue`（不執行以下 10 分頁）。否則才進入
`detect_maneuvers_refined_adaptive()` 與 10 分頁渲染。

### 主頁面 10 分頁

| 分頁 | 圖示 | 主要內容 |
|---|---|---|
| 1. 軌道分類 | 🏷️ | `classify_orbit()` 四張分類卡片（高度/偏心率/幾何/任務狀態）+ 參數表（半長軸以 SMA(高度) 並列顯示）+ 原始 JSON |
| 2. 趨勢分析 | 📊 | SMA 折線（SMA(高度) 座標軸）+ F10.7 + 機動標記；指標：數據點、機動次數、最大 Δa；下方自動顯示 SSA-RAG 解說 |
| 3. RIC 速度變化 | 🚀 | `dv_intrack`（柱狀）+ `dv_crosstrack`（折線）；MAD 異常標記 |
| 4. 3D 軌道 | 🌍 | 多時序軌道演變，顏色由舊（紅）到新（藍） |
| 5. Δ 計算 | Δ | SMA（SMA(高度) 格式）+ 四個角度元素每日差分；可下載 CSV |
| 6. Spiral Polar | 𖦹 | 四個角度在極座標中的螺旋時序分佈 |
| 7. 長軸旋轉週期 | ⬯ | Lomb-Scargle 頻譜 + 線性+正弦模型擬合；輸出週期、振幅、斜率 |
| 8. MEME 殘差 | 🛰️ | RTN 三面板殘差圖；偵測機動；TLE vs MEME 方法對比表 |
| 9. Galileo SP3 | 🪐 | RTN 三面板（~29,600 km MEO）；三方法偵測對比表 |
| 10. IDS 驗證 | 🌍 | DORIS SP3 Ground Truth；RIC 殘差三面板；機動候選表；IDS 衛星一覽 |

---

## UI 結構（🤖 ML 模型偵測頁）

### 側邊欄輸入
- NORAD ID（逗號分隔）、日期範圍
- 滑動窗口（天，預設 26）、步進間隔（天，預設 3）、判定閾值（預設 0.50）— 僅「趨勢分析」子分頁使用
- SSA-RAG 自動解說勾選框（預設開啟）

### 軌域守門警告

同樣呼叫 `classify_orbit()`；若判定為 `GEO`/`GEO+`，顯示
「⚠️ NORAD {id} 軌道要素（a≈… km）判定為 GEO 軌域。此模型僅在 LEO 衛星（193–985 km）
訓練，結果僅供參考。」——**不中斷推論**，XGBoost/LightGBM 仍照常顯示結果，只是加註警告
（因為訓練集 `training_samples_plan_b.csv` 的高度全部落在 193–985 km，對 GEO 級輸入屬於
分布外推論）。

### 三個子分頁

| 子分頁 | 圖示 | 主要內容 |
|---|---|---|
| XGBoost 軌道相位 | 📊 | 軌道相位 4 類機率卡片＋長條圖；活動強度（主動提升 vs 穩定維持）；特徵重要度 |
| LightGBM 機動偵測 | 🔍 | 單次推論 `p_maneuver`；紅/綠/橘三色警示框（橘＝TLE 缺口守門壓制）；5 個指標（含「最長 TLE 缺口」）；SSA-RAG 解說 |
| 趨勢分析 | 📈 | `compute_lgbm_rolling_predictions()` 滾動推論雙面板圖（機率 + SMA(高度)）；灰色區塊＝純阻力衰減、橘色區塊＝資料缺口壓制；5 個彙總指標 |

---

## UI 結構（💬 SSA 知識庫問答頁）

`render_ssa_rag_page()`：獨立於機動偵測結果之外，讓使用者直接輸入問題查詢 SSA-RAG 知識庫，
並顯示服務健康檢查指令提示（`curl http://127.0.0.1:8000/health`）。

---

## UI 結構（GEO 模式，由軌域自動路由觸發）

`render_geo_page()` 渲染四個子分頁（含軌道分類）：

| 子分頁 | 內容 |
|---|---|
| 🏷️ 軌道分類 | `classify_orbit()` 四張分類卡片（同 LEO/MEO 頁邏輯，套用於 GEO 衛星） |
| 📡 經度 & 漂移率 | 雙面板：λ(°) + drift(°/day)；EW 確認/未確認標記；TLE 空白區間陰影；自動 SSA-RAG 解說 |
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
       └─ load_data() ── df_raw
            │
            ├─ classify_orbit() [中位數 a/e/i] ──→ altitude_class
            │        │
            │        ├─ GEO / GEO+ ──→ render_geo_page() ─┐
            │        │    └─ load_geo_raw_series()/load_geo_events()
            │        │         └─ λ, drift_deg_day / EW,NS,REPOSITIONING,DISPOSAL,TLE_GAP
            │        │                                     │
            │        └─ 其他（LEO/MEO） ──┐                │
            │                             ▼                ▼
            │              detect_maneuvers_refined_adaptive()   build_geo_maneuver_narrative()
            │                   └─ [SMA 差分 + 高度自適應 MAD z-score]      │
            │              calculate_ric_deltas() ── dv_intrack/crosstrack │
            │                             │                                │
            └──────────── build_tle_maneuver_narrative() ─────────────────┤
                                          │                                │
🤖 ML 模型偵測頁（獨立入口，同樣先 classify_orbit() 守門）                │
  compute_xgb_features() → XGBoost（相位/活動強度）                        │
  compute_lgbm_plan_b_features()/compute_lgbm_rolling_predictions()        │
       └─ [26d 聚合特徵 + max_tle_gap_h 缺口守門 (>48h 壓制)]              │
            └─ build_ml_maneuver_narrative()                              │
                                          │                                │
外部精密星曆                              ▼                                ▼
  ├─ MEME CSV ── load_meme_residuals()          render_rag_auto_explain()
  │    └─ detect_maneuvers_rtn() [MAD z-score]        └─ ssa_rag_client → SSA-RAG 服務（另一 repo）
  ├─ Galileo SP3 CSV ── load_galileo_sp3_residuals()
  │    └─ detect_maneuvers_rtn()
  └─ IDS DORIS SP3 ── parse_ids_sp3_file()
       └─ propagate_from_db_elements() [SGP4 sgp4init]
            └─ compute_ids_ric_residuals() [RIC frame]
                 └─ detect_ids_maneuvers()

F10.7 (NRC Canada) ── fetch_f107_data() ── 快取 CSV
  └─ merge_asof → df_final（與 TLE 時序對齊）
                                          │
                                          ▼
                                  Plotly 互動圖表（SMA 座標軸統一用 sma_axis_ticks() 標示高度）
                                  ├─ 10 分頁（LEO/MEO，含軌道分類）
                                  ├─ 4 子分頁（GEO，含軌道分類）
                                  └─ 3 子分頁（ML 模型偵測）
```

---

## 關鍵已知限制

1. **App 內 SP3 TAI 時間**：`parse_ids_sp3_file()` 未做 TAI→UTC 37 秒修正（pipeline 版本已修正）。
2. **座標系**：`propagate_from_db_elements()` 輸出 TEME（SGP4），IDS SP3 使用 ITRF。App 內 RIC 殘差計算未做 TEME→ITRF 轉換（pipeline 版本的 `compare_residuals.py` 已修正）。
3. **GEO SMA 偵測**：GEO 視圖使用 `load_geo_raw_series()` 讀取 `raw_tle_archive`，需有 `line1`/`line2` 欄位；若 DB 僅有 `tle_table`（無 TLE 字串），GEO 時序圖會顯示空白。
4. **MEME 機動計數**：`load_meme_residuals()` 在三方法對比表中會被再次呼叫一次（重複 I/O）。
5. **LightGBM 模型訓練域限制**：訓練集 `training_samples_plan_b.csv` 高度全部落在 193–985 km（純 LEO），
   對 MEO/GEO 衛星屬分布外推論；`render_ml_page()` 會顯示警告但不會阻擋推論，結果僅供參考。
6. **TLE 缺口守門門檻是啟發式值**：`TLE_GAP_SUPPRESS_H = 48.0` 小時是依實際案例（NORAD 44349）
   反推的經驗門檻，未經大規模統計驗證；未來若要嚴謹化，建議依高度/衛星類型分層校準。
7. **SSA-RAG 服務依賴**：`render_rag_auto_explain()` 需要外部 SSA-RAG 服務（`F:\GitHub\SSA-RAG`）
   由另一個 session 啟動；本 app 不會、也不應自行執行 `uvicorn`。健康檢查快取 60 秒，
   服務剛啟動的前 60 秒內畫面可能仍顯示「服務未上線」。
5. **Streamlit `query_params` 相容性**：已做 `st.query_params` vs `st.experimental_get_query_params()` 相容包裝。
