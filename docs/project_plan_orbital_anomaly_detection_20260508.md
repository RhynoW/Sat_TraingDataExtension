# 軌道異常及太空事件智慧化偵測系統
## 五個月工作計畫書

**計畫起始日期**：2026-05-07  
**計畫結束日期**：2026-10-07  
**版本**：v1.1（更新日期：2026-05-08）  
**異動摘要**：反映 2026-05-07–08 期間完成的 `compare_tle_vs_ephemeris.py` 重構、`maneuver_app.py` 雙管線整合與六項高度自適應改進，更新現有基礎資產清單、Layer 1 完成狀態、W1/W3 任務勾選狀態。

---

## 一、計畫概述

### 1.1 目標

開發一套可實際部署的「衛星軌道異常及太空事件智慧化偵測演算法」，具備以下能力：

| 偵測層級 | 目標幅度 | 對應事件 |
|----------|----------|----------|
| 微型機動 | 10–100 m（Δa ≈ 0.01–0.1 km） | 碰撞規避細調、站保推力 |
| 小型機動 | 0.1–5 km | 相位調整、Hohmann 第一段 |
| 大型機動 | ≥ 5 km | 軌道爬升、受控離軌 |
| 星系級異常 | 多星協同偏差 | 批量部署、星系重組、戰術機動 |

### 1.2 現有基礎（截至 2026-05-08）

| 資產 | 狀態 |
|------|------|
| MEME ephemeris 下載 pipeline | ✅ 已自動化，日批次下載 284 顆 Starlink |
| TLE 歷史資料庫（DuckDB） | ✅ 4590 萬筆，39,009 顆衛星 |
| `compare_tle_vs_ephemeris.py` | ✅ 已重構（7 項修正）：高度自適應 TLE 選擇、零範數防護、合併率警告、TLE 年齡診斷 |
| `data/comparison/residuals_*.csv` | ✅ 284 顆衛星，1.22M 行 RTN 殘差資料集（TLE vs MEME 精密星曆） |
| `maneuver_app.py` — TLE-SMA 管線 | ✅ 高度自適應偵測：5 個高度帶 mult/window/rate_mult/rate_floor，rate_floor 防塌陷，sma_direction 記錄 |
| `maneuver_app.py` — MEME RTN 管線 | ✅ `detect_maneuvers_rtn`：MAD z-score + TLE 年齡自適應 z_thr（4.0/5.0/6.0/7.0）|
| `maneuver_app.py` — RIC ΔV 偵測 | ✅ `detect_ric_events`：高度自適應 min_dv（0.5/0.05/0.01 m/s）|
| Streamlit 雙管線儀表板（7 頁籤） | ✅ 趨勢分析、RIC、3D 軌道、Δ 計算、Spiral Polar、長軸週期、MEME 殘差 |
| MEO/GEO 高度警告 | ✅ 軌道高度 > 1200 km 自動提示偵測限制 |
| 地面實況標記集 | ✅ 3381 筆 transition labels（May 2–6，3 天） |
| 軌道相位偵測模型 | ✅ XGBoost 4-class，CV Acc = 96.1% |
| 活動強度偵測模型 | ✅ XGBoost binary，CV AUC = 100.0% |
| 驗證案例 | ✅ NORAD 62425：z = 20.4 順軌向機動，Δdr_t = 0.718 km（2026-05-03 21:37 UTC） |
| 文件 | ✅ `compare_tle_vs_ephemeris.md`、`maneuver_app.md` |

### 1.3 關鍵技術挑戰

1. **時間解析度差距**：TLE 每日 1–3 筆（~8h 積分），MEME 每 8h 一筆（瞬時快照）。MEME RTN 管線（`detect_maneuvers_rtn`）已部分解決此問題，提供 ~10 分鐘解析度偵測
2. **微型機動偵測**：TLE 位置誤差約 100–300 m，直接從 TLE 偵測 10 m 量級機動需要特殊統計方法（CUSUM、SSA）；MEME 直接偵測路徑可偵測至 |ΔV| > 0.05 m/s
3. **標記資料稀少**：目前僅 3 天 MEME 資料；需要累積 + 合成資料擴充
4. **低誤報率要求**：Starlink 衛星「隨時都在機動」，需區分「正常操作」vs「異常事件」；已透過高度自適應 rate_floor 改善

---

## 二、資料策略

### 2.1 原始資料來源

#### 主要資料（已建立）

| 來源 | 資料類型 | 精度 | 更新頻率 |
|------|----------|------|----------|
| Space-Track TLE | 兩行軌道要素 | 位置誤差 ~300 m | 每日多次 |
| Starlink MEME ephemeris | 精密狀態向量 + 協方差 | 位置誤差 <10 m | 每 8 小時 |

#### 補充資料（計畫期間建立）

| 來源 | 資料類型 | 用途 |
|------|----------|------|
| Space-Track `maneuver` API | 部分衛星機動記錄（ISS 等） | 多星驗證集 |
| NASA GCAT / CelesTrak | 歷史 TLE 封存 | 長期趨勢分析 |
| 合成軌道資料生成器 | 含真實雜訊的模擬狀態向量 | 低誤報率測試 |

### 2.2 合成資料生成器設計（Month 1 交付）

解決標記資料不足的核心策略。

**生成流程**：

```
真實 TLE 軌道 (baseline)
    │
    ├─ 注入機動事件（Hohmann impulse, ΔV ∈ [0.001, 50] m/s）
    │       時機：隨機 or 依 Starlink 操作模式
    │
    ├─ 加入 TLE 擬合雜訊（Gaussian σ = 50–300 m）
    │       根據不同高度殼層的真實 TLE 殘差校準
    │       ← 殼層雜訊參數已可從 residuals_*.csv 自動估算
    │
    ├─ 加入 J2 攝動（精確計算）
    │       RAAN 日漂移 = −1.5 × n × J2 × (R_E/p)² × cos(i)
    │
    └─ 輸出：帶標記的 TLE 序列
             label: {maneuver_epoch, dv_ms, direction (RTN), maneuver_class}
```

**雜訊模型校準**（基於真實 TLE vs MEME 殘差，`residuals_*.csv` 已可提供）：

| 殼層 | σ_sma（km） | σ_inc（deg） | σ_raan_res（deg） |
|------|-------------|--------------|-------------------|
| 53°/460-510 km | 0.045 | 0.0012 | 0.022 |
| SSO/320-370 km | 0.120 | 0.0025 | 0.031 |
| 70°/540-580 km | 0.043 | 0.0010 | 0.019 |

### 2.3 資料清洗流程

```
原始 TLE
 ├─ 去重（相同 epoch 多筆 → 取最新）         ← 已實作於 load_data()
 ├─ 異常值過濾（Δa > 3σ 且無相鄰確認 → 標記為 TLE fitting artifact）
 ├─ J2 RAAN 校正（已實作，殘差 std = 22 milli-deg）
 ├─ 軌道要素穩定性評估（rolling std 7d < noise threshold）
 └─ 輸出：品質標記 TLE 序列（quality_flag: good / suspect / rejected）
```

---

## 三、演算法架構

### 3.1 三層偵測架構

```
Layer 1 — 閾值基準層（✅ 已完成並強化）
  輸入：MEME RTN 殘差（residuals_*.csv）
        TLE-SMA 時序（DuckDB）
  方法（雙管線）：
    ├─ TLE-SMA 差分：高度自適應 mult/window/rate_mult/rate_floor
    │     5 個高度帶（300-500/500-600/600-700/700-1200/其他）
    │     rate_thr = max(r_med + rate_mult × r_mad, rate_floor)
    ├─ MEME RTN MAD z-score：TLE 年齡自適應 z_thr（4.0–7.0）
    │     step rate [km/h]、聚類相鄰尖峰、同小時去重
    └─ RIC ΔV 偵測：高度自適應 min_dv（0.5/0.05/0.01 m/s）
  精度：TLE 管線 ~km；MEME 管線 sub-km
  介面：`maneuver_app.py`（Streamlit 7 頁籤儀表板）

Layer 2 — 統計偵測層（Month 2–3）
  輸入：TLE 時序（7–30 天窗口）
  方法：CUSUM、BOCPD、Lomb-Scargle SSA
  精度：100 m ~ 1 km（TLE 雜訊限制）
  用途：TLE-only 偵測，覆蓋非 MEME 衛星

Layer 3 — AI 偵測層（Month 3–5）
  輸入：TLE 特徵 + MEME Ground Truth
  方法：XGBoost + LSTM Autoencoder + Transformer
  精度：目標 < 100 m（MEME 輸入）；< 500 m（TLE 輸入）
  用途：高靈敏度偵測，包含微型機動
```

### 3.2 特徵工程階段規劃

#### Phase A 特徵（✅ 已實作）

| 特徵 | 描述 | 窗口 |
|------|------|------|
| `da_Nd_km` | 半長軸變化 | 1/3/7 天 |
| `di_Nd_deg` | 傾角變化 | 1/3/7 天 |
| `draan_res_Nd_deg` | J2 校正 RAAN 殘差 | 1/3/7 天 |
| `sma_slope_km_day` | 30 天線性趨勢 | 30 天 |
| `sma_std_30d_km` | 軌道高度標準差 | 30 天 |
| `dv_intrack_ms` | 估算切向 ΔV（高度自適應 min_dv） | 1 天 |
| `dr_t_step_km` | MEME 順軌向殘差逐步突變 | 10 分鐘 |
| `dr_n_step_km` | MEME 法向殘差逐步突變 | 10 分鐘 |
| `rtn_z_score` | TLE 年齡自適應 MAD z-score | 10 分鐘 |
| `sma_direction` | 機動方向（raise/lower） | 1 天 |

#### Phase B 特徵（Month 2–3）

| 特徵 | 描述 | 技術 |
|------|------|------|
| `cusum_sma` | 累積和異常分數 | CUSUM 統計量 |
| `bocpd_prob` | 變化點後驗概率 | Bayesian Online CPD |
| `ssa_residual_km` | SSA 去趨勢殘差 | Singular Spectrum Analysis |
| `raan_ssa_anomaly` | RAAN 異常振幅 | SSA on J2-corrected RAAN |
| `drag_corrected_da` | 大氣阻力校正後 Δa | NRLMSISE-00 × F10.7 |

#### Phase C 特徵（Month 4–5）

| 特徵 | 描述 | 技術 |
|------|------|------|
| `lstm_recon_error` | 序列重建誤差 | LSTM Autoencoder |
| `transformer_anomaly_score` | Attention 異常分數 | Patch-based Transformer |
| `constellation_delta_raan` | 星系 RAAN 偏差 | 多星統計 |
| `plane_formation_error` | 軌道面陣型誤差 | 星系結構分析 |

### 3.3 AI 模型架構

#### 監督式學習（Month 2–3）

```
輸入：TLE 時序特徵（窗口 = 14/30/60 天）
     + MEME Ground Truth（累積標記）

XGBoost（快速 baseline）
  任務 A：Binary — 是否發生推力（8h 窗口）
  任務 B：4-class — da_severity（none/small/medium/large）
  任務 C：5-class — maneuver_class（raising/lowering/phasing/mixed/stable）
           ← sma_direction（raise/lower）欄位已納入特徵

隨機森林（可解釋性基準）
  用於特徵重要度排序與閾值校準
```

#### 非監督式學習（Month 3–4）

```
LSTM Autoencoder（軌道行為建模）
  架構：Encoder(LSTM×2) → Bottleneck → Decoder(LSTM×2)
  輸入：[sma, i, Ω, e, u] × 60 天時序
  訓練：穩定衛星（MEME stable 期間），最小化重建誤差
  推論：重建誤差突增 → 異常事件

Isolation Forest（補充偵測）
  輸入：Phase B 特徵向量
  用途：無標記衛星的初篩，降低 LSTM 誤報

變化點偵測（BOCPD）
  實作：Bayesian Online Changepoint Detection（Adams & MacKay 2007）
  目標：精準定位推力發生時刻（8h 分辨率）
```

#### 深度學習（Month 4–5）

```
Patch Transformer Anomaly Detector
  架構：
    時序切片（patch_size = 7 天）
    → Positional Encoding
    → Multi-Head Self-Attention（8 heads）
    → Feed-Forward Network
    → 重建誤差 + 異常分數

  輸入：標準化 TLE 特徵 × 90 天
  訓練策略：
    - 預訓練：無標記 TLE 序列（自監督 MAE）
    - 微調：MEME Ground Truth 標記（監督式）
  目標：偵測 TLE 層級 100 m 量級機動
```

---

## 四、五個月執行期程

### 總覽甘特圖

```
月份       1         2         3         4         5
週次    1234    5678    9012    3456    7890
                                              
資料蒐集 ████████████████████████████████████████
合成資料 ████████████
資料清洗 ████████████████████
                                              
MEME 累積 ████████████████████████████████████████
閾值偵測  ██▓▓            （✅ Layer 1 雙管線已完成）
統計偵測      ████████████████
監督式 ML         ████████████████
非監督式              ████████████████
深度學習                  ████████████████████
                                              
Benchmark ████                       ████████████
驗證評估              ████                ████████
文件報告  ▓▓                              ████████
```

---

### 第一個月（2026-05-07 ~ 2026-06-06）：基礎建設期

**主題**：資料管線完備化、基準演算法驗證、合成資料生成器

#### W1（5/07–5/14）：資料品質稽核

- [x] 稽核 TLE 資料庫雜訊特性
  - `compare_tle_vs_ephemeris.py`（7 項修正）計算真實 TLE vs MEME 殘差，輸出 `data/comparison/residuals_*.csv`（284 顆，1.22M 行）
  - 高度自適應 TLE 選擇邏輯：Python-side 選取最接近星曆起始時刻的 TLE，偏好 epoch ≤ ephem_start
  - 零範數防護（`_rtn_basis`）、合併率警告（< 90% 記錄 WARNING）、TLE 年齡負值警告
- [x] 擴充 MEME 下載覆蓋範圍
  - 每日批次正確執行（排程代理人已啟動）
  - 建立 MEME 完整性監控儀表板（`maneuver_app.py` MEME 殘差頁籤）
- [ ] 建立 Benchmark 資料集 v0（3381 筆標記正式封裝為 `data/benchmark/benchmark_v0.csv`）

#### W2（5/15–5/21）：合成資料生成器

- [ ] 實作 `generate_synthetic_tle.py`
  - 基於真實 TLE 軌道插入 Hohmann 推力
  - 雜訊模型依 `residuals_*.csv` 殼層統計自動校準（σ_sma/σ_inc/σ_raan）
  - 支援批量生成（目標：每個 maneuver_class 各 500+ 樣本）
- [ ] 驗證合成資料統計特性與真實資料一致性（KS 檢定）

#### W3（5/22–5/28）：基準演算法完備化

- [x] 強化 `maneuver_app.py` TLE-SMA 偵測器
  - 高度自適應超參數：5 個高度帶（300-500/500-600/600-700/700-1200/其他），mult/window/rate_mult/rate_floor 各別設定
  - `rate_thr = max(r_med + rate_mult × r_mad, rate_floor)` 防止靜軌期門檻塌陷
  - 機動方向記錄（`sma_direction`：raise/lower）
  - 方向偵測 bug 修正（原僅偵測軌道抬升，現已同時偵測降軌）
- [x] 實作並驗證 MEME RTN 管線
  - `detect_maneuvers_rtn`：TLE 年齡自適應 z_thr（≤3d→4.0/≤7d→5.0/≤14d→6.0/>14d→7.0）
  - `load_meme_residuals`：DuckDB 記憶體過濾 100 MB+ CSV，僅讀取目標衛星行
  - 驗證：NORAD 62425，z = 20.4，順軌向機動 Δdr_t = 0.718 km（2026-05-03 21:37 UTC）
- [x] 高度自適應 RIC ΔV 門檻（`detect_ric_events`，min_dv 0.5/0.05/0.01 m/s）
- [x] MEO/GEO 高度警告（> 1200 km 自動提示）
- [ ] 建立 ISS 驗證集
  - 從 Space-Track 下載 ISS TLE（NORAD 25544）歷史資料
  - 對照 NASA 公開的機動執行記錄（ISS Reboost log）
- [ ] 加入 3-sigma 異常過濾（去除 TLE fitting artifacts，加入 `quality_flag`）

#### W4（5/29–6/06）：月底整合

- [ ] 整合當月 MEME 資料（~4週 × 3筆/天 × 284顆 ≈ 24,000 筆快照）
- [ ] 重新執行 `compare_tle_vs_ephemeris.py`，更新 `residuals_*.csv`，目標 > 10,000 transitions
- [ ] 交付 **Benchmark v1**

**月底交付物**：
- `generate_synthetic_tle.py`（合成資料生成器）
- `data/benchmark/benchmark_v1.csv`（真實 + 合成，各 1000+ 樣本）
- `data/noise_profile/`（TLE 雜訊特性報告，從 residuals_*.csv 自動生成）
- 技術備忘錄：TLE 雜訊模型與合成資料驗證報告

---

### 第二個月（2026-06-07 ~ 2026-07-06）：統計偵測層開發期

**主題**：TLE-only 統計偵測、1 個月 MEME Ground Truth 監督式學習

#### W5–W6（6/07–6/21）：統計變化點偵測

- [ ] 實作 `detect_maneuvers_statistical.py`
  - **CUSUM**（Cumulative Sum）：偵測 sma rate 的結構性變化
    ```python
    # CUSUM 統計量
    S_t = max(0, S_{t-1} + (x_t - μ_0 - k))  # k = 允許偏移量
    # 觸發條件：S_t > h（偵測閾值）
    # 高度帶 rate_floor 可作為 μ_0 的下界參考
    ```
  - **BOCPD**（Bayesian Online Changepoint Detection）：
    計算每個 epoch 為變化點的後驗概率
  - **SSA**（Singular Spectrum Analysis）：
    分解 sma 時序為趨勢 + 週期 + 殘差；機動事件出現在殘差峰值

- [ ] 大氣阻力校正
  - 整合 F10.7 指數（已有 cache，`f107_cache.csv`）
  - 實作簡化 NRLMSISE-00 阻力模型（基於 BCterm）
  - 修正後的 `da_drag_corrected` 特徵降低高活動期誤報

#### W7–W8（6/22–7/06）：1 個月 MEME 監督式學習

- [ ] 重建 `build_training_dataset.py`（Phase B 特徵版本）
  - 加入 CUSUM / BOCPD / SSA 特徵
  - 加入 Phase A RTN 特徵（`dr_t_step_km`、`rtn_z_score`、`sma_direction`）
  - 延長 TLE 窗口至 30 天
  - 目標樣本數：~30,000 transitions（1個月 × 284衛星 × 3筆/天）
- [ ] 重新訓練 XGBoost（任務 A：Binary，任務 B：severity，任務 C：maneuver_class 含 raise/lower）
  - 預期 Binary AUC > 0.80（1個月資料）
  - 導入 SHAP 可解釋性分析

**月底交付物**：
- `detect_maneuvers_statistical.py`（CUSUM + BOCPD + SSA）
- 更新 `build_training_dataset.py`（Phase B 特徵，30-day 窗口）
- 更新 XGBoost 模型（v2.0）
- 技術報告：統計偵測 vs 閾值法效能比較（ROC / PR 曲線）

---

### 第三個月（2026-07-07 ~ 2026-08-06）：Burn-Epoch 偵測開發期

**主題**：精準定位推力時刻（8h 分辨率）、LSTM Autoencoder 訓練

#### W9–W10（7/07–7/21）：Burn-Epoch 偵測器

目標：從 TLE 序列推斷機動發生的 8 小時窗口（與 MEME 直接對齊）

- [ ] 實作 `detect_burn_epoch.py`
  - **方法**：滑動窗口 BOCPD，窗口大小 = 1 天（~TLE 更新頻率）
  - **標記對齊**：MEME t_from → 最近 TLE epoch（merge_asof，max 4h 容差）
  - **輸入特徵**：30 天 TLE context + Phase B 統計特徵 + RTN z_score
  - **輸出**：每個 TLE epoch 的機動概率分數（0–1）

- [ ] 累積 MEME 標記集（~2個月，目標 >60,000 transitions）
  - 用於 burn-epoch 偵測器監督式訓練
  - 依 da_severity 分層採樣確保類別均衡

#### W11–W12（7/22–8/06）：LSTM Autoencoder

- [ ] 實作 `model_lstm_autoencoder.py`
  ```
  架構：
    Encoder: LSTM(128) → LSTM(64) → Dense(32) [bottleneck]
    Decoder: Dense(32) → LSTM(64) → LSTM(128) → 重建序列
  
  輸入：[sma_norm, i_norm, Ω_res_norm, e_norm, dr_t_norm] × 60 時步
         ← dr_t（RTN 順軌向殘差）納入多模態輸入
  訓練資料：MEME 標記為「stable」的衛星片段（無推力期間）
  損失函數：MSE 重建損失
  
  推論：重建誤差 z-score > 3σ → 異常
  ```

- [ ] 驗證：合成注入測試
  - 在已知穩定軌道上注入 0.01 / 0.1 / 1.0 km 機動
  - 測量 LSTM AE 偵測率 vs 假警報率（ROC）

**月底交付物**：
- `detect_burn_epoch.py`（8h 分辨率機動時刻偵測器）
- `model_lstm_autoencoder.py`（非監督式異常偵測）
- Benchmark v2（加入 burn-epoch 標記，~60,000 樣本）
- 技術報告：LSTM AE vs BOCPD vs CUSUM vs RTN MAD z-score 比較

---

### 第四個月（2026-08-07 ~ 2026-09-06）：星系級分析 & 微型機動

**主題**：多衛星協同分析、Transformer 模型、微型機動（100 m 量級）

#### W13–W14（8/07–8/21）：星系級異常偵測

- [ ] 實作 `detect_constellation_anomaly.py`
  - **軌道面一致性**：同一 RAAN 面的衛星 Δi 標準差 → 異常面 ID
  - **批量機動識別**：同天機動衛星 > K 顆 → 星系事件（利用 `sma_direction` 欄位分類）
  - **陣型誤差**：衛星間相對相位 θ_ij 偏離預期值 → 主動重組
  - 輸出：每日星系事件報告（`constellation_events_{date}.csv`）

- [ ] Starlink 星系動態視覺化
  - 3D RAAN-alt 空間的衛星分布動態圖
  - 機動事件叢集標記（顏色 = maneuver_class + sma_direction）

#### W15–W16（8/22–9/06）：Patch Transformer + 微型機動

- [ ] 實作 `model_transformer_anomaly.py`
  ```
  架構（簡化 Anomaly Transformer）：
    Patch Embedding（patch = 7 天 TLE 序列）
    → Positional Encoding
    → 4 × Transformer Block（8 heads, d_model=64）
    → 重建頭（預測下一個 patch）
    → 異常分數 = 重建誤差 × Attention weight 分歧度
  
  預訓練：無標記 TLE（自監督 Masked Prediction）
  微調：MEME 標記集（3 個月累積，> 90,000 transitions）
  ```

- [ ] 微型機動偵測研究（100 m 量級）
  - 基於 MEME 高精度狀態向量直接偵測（不依賴 TLE）
  - 方法：連續 MEME 快照間能量差 ΔE = v·Δv ≈ 機動加速度指標
  - 目標偵測閾值：|ΔV| > 0.05 m/s（MEME 精度允許範圍，RTN 管線驗證下限）
  - 參考基準：NORAD 62425 已驗證 z = 20.4 @ step = 0.718 km

**月底交付物**：
- `detect_constellation_anomaly.py`（星系級事件偵測）
- `model_transformer_anomaly.py`（Patch Transformer）
- 星系事件月報（範本）
- 技術備忘錄：微型機動偵測下限分析（MEME RTN 管線 vs TLE 精度邊界）

---

### 第五個月（2026-09-07 ~ 2026-10-07）：系統整合、驗證與文件

**主題**：Benchmark 最終版、全面效能評估、API/介面完備化

#### W17–W18（9/07–9/21）：Test Benchmark v3（最終版）

**驗證資料集組成**：

| 資料集 | 樣本數 | 來源 | 用途 |
|--------|--------|------|------|
| Starlink MEME GT | ~120,000 transitions | 本計畫 pipeline（5個月） | 主要訓練與評估 |
| ISS reboost log | ~200 事件 | NASA + TLE | 多星種驗證 |
| 合成資料集 | 50,000 樣本 | `generate_synthetic_tle.py` | 稀有事件測試 |
| Starlink 公開 SA 事件 | ~50 事件 | 媒體報導確認 | 極端事件基準 |

- [ ] 執行 Benchmark v3 完整評估：所有演算法（Layer 1–3）
- [ ] 繪製完整 ROC / PR 曲線（依機動幅度分層，TLE 管線 vs MEME RTN 管線 vs ML）
- [ ] 計算 Benchmark 可重現性（固定隨機種子，輸出 hash 一致性）

#### W19–W20（9/22–10/07）：系統整合與最終文件

- [ ] 整合三層偵測架構為統一介面 `orbit_anomaly_detector.py`
  ```python
  detector = OrbitAnomalyDetector(config="default")
  results  = detector.detect(
      norad_ids   = [25544, 48274, ...],
      start_date  = "2026-09-01",
      end_date    = "2026-10-01",
      source      = "tle"  # or "meme" or "both"
  )
  # returns: AnomalyReport with events, severity, confidence, sma_direction
  ```
- [ ] Streamlit 儀表板整合（擴充 `maneuver_app.py`）
  - 新增 AI 偵測分數層（疊加於現有 TLE-SMA 與 MEME RTN 雙管線）
  - 加入星系事件地圖
  - 串接 MEME 即時資料流

- [ ] 撰寫技術報告（最終版）

---

## 五、效能評估指標

### 5.1 偵測效能

| 指標 | 定義 | 目標值 |
|------|------|--------|
| **TPR（Recall）** | 偵測到的真實機動 / 所有真實機動 | ≥ 0.90（large）<br>≥ 0.80（medium）<br>≥ 0.65（small） |
| **FPR（False Alarm Rate）** | 誤報 / 所有非機動窗口 | ≤ 0.05 |
| **ROC-AUC** | 整體區分能力 | ≥ 0.90 |
| **Average Precision** | PR 曲線下面積（考慮類別不平衡） | ≥ 0.85 |
| **F1-score（macro）** | 各類別平均 F1 | ≥ 0.80 |
| **Latency** | 從推力發生到偵測的時間延遲 | ≤ 24h（TLE 輸入）<br>≤ 8h（MEME 輸入） |

### 5.2 分層評估（按機動幅度）

| 幅度 | ΔV 範圍 | TLE 可偵測性 | MEME RTN 可偵測性 | 目標 TPR |
|------|---------|-------------|------------------|---------|
| 微型 | < 0.1 m/s（Δa < 0.1 km） | ❌ 雜訊以下 | ✅ z_thr 自適應後勉強可見 | > 0.50 |
| 小型 | 0.1–2 m/s（Δa 0.1–5 km） | ⚠ 需統計方法 | ✅ 清晰可見 | > 0.70 |
| 中型 | 2–15 m/s（Δa 5–15 km） | ✅ 可偵測 | ✅ 清晰可見 | > 0.90 |
| 大型 | > 15 m/s（Δa > 15 km） | ✅ 明顯 | ✅ 極清晰（驗證：z = 20.4） | > 0.98 |

### 5.3 比較基準

| 方法 | 說明 |
|------|------|
| **Baseline-Threshold（TLE-SMA）** | `maneuver_app.py` 高度自適應 TLE-SMA 差分管線（Layer 1） |
| **Baseline-RTN** | `maneuver_app.py` MEME RTN MAD z-score 管線（Layer 1，TLE 年齡自適應） |
| **Baseline-CUSUM** | 統計變化點偵測（無 AI，Month 2） |
| **Literature: Maneuver DB** | Kelecy & Hall 2006 閾值法 |
| **本計畫 ML v1** | XGBoost（Month 2） |
| **本計畫 ML v2** | LSTM AE + XGBoost ensemble（Month 3） |
| **本計畫 ML v3** | Transformer + multi-source fusion（Month 5） |

### 5.4 可重現性驗證

```
每個 Benchmark 執行：
  1. 固定隨機種子（seed=42）
  2. 輸出模型 hash（SHA-256）
  3. 輸出預測結果 hash
  4. 記錄環境快照（Python 版本、套件版本）
  
通過標準：相同輸入 → 相同輸出（hash 完全一致）
```

---

## 六、微型機動偵測的技術邊界

### 6.1 各資料源的偵測下限

| 資料源 | 位置精度 | 理論 Δa 偵測下限 | 實際限制 |
|--------|----------|-----------------|---------|
| TLE（一般） | ~300 m | 0.6 km | TLE 更新不均勻 |
| TLE（最新分類 GP） | ~100 m | 0.2 km | 需多 epoch 統計 |
| MEME ephemeris（RTN 管線） | <10 m | 0.02 km（20 m） | TLE 年齡影響背景殘差，z_thr 自適應已部分補償 |
| 精密測距（GRACE-FO 等） | ~1 cm | 0.00002 km（2 cm） | 非公開資料 |

### 6.2 10 m 量級機動的可行路徑

直接從 TLE 偵測 10 m 量級機動目前不可行（TLE 雜訊高出 10–30 倍）。  
可行替代路徑：

1. **MEME RTN 直接偵測**（已實作）：MEME 精度 < 10 m，`detect_maneuvers_rtn` 可偵測 |ΔV| > 0.05 m/s；TLE 年齡自適應 z_thr 避免老舊 TLE 造成假陽性
2. **累積統計**：對同一衛星做 100+ 天的系統性偏差累積，可偵測慢速遷移（10 m/天 量級）
3. **相對測量**：同平面衛星的相對位置偏差（RAAN 面內比較），雜訊可降低到 10 m 量級

**建議**：第四個月交付微型機動偵測技術可行性分析報告，依結果決定是否納入正式評估指標。

---

## 七、里程碑總覽

| 里程碑 | 日期 | 交付物 | 狀態 |
|--------|------|--------|------|
| **Layer 1 完成** | 2026-05-08 | 雙管線 Streamlit 儀表板、高度自適應閾值、RTN z_thr 自適應 | ✅ 完成 |
| **M1** Data Foundation | 2026-06-06 | 合成資料生成器、Benchmark v1、雜訊特性報告 | 進行中 |
| **M2** Statistical Layer | 2026-07-06 | CUSUM+BOCPD+SSA 偵測器、ML v2（1個月GT） | 計畫中 |
| **M3** Burn-Epoch Detection | 2026-08-06 | 8h 精度機動時刻偵測、LSTM AE、Benchmark v2 | 計畫中 |
| **M4** Constellation + DL | 2026-09-06 | 星系級異常偵測、Patch Transformer、微型機動分析 | 計畫中 |
| **M5** Integration & Validation | 2026-10-07 | 統一介面、Benchmark v3、最終技術報告 | 計畫中 |

---

## 八、工具與技術棧

| 類別 | 工具 |
|------|------|
| 語言 | Python 3.11+ |
| 軌道力學 | `numpy`、`scipy`（J2/J4 攝動）、`astropy`（座標轉換）、`skyfield`（SGP4 傳播） |
| 資料庫 | DuckDB（TLE + MEME 殘差 CSV 記憶體過濾） |
| ML 框架 | XGBoost、scikit-learn、PyTorch（LSTM / Transformer） |
| 統計方法 | `ruptures`（BOCPD/PELT）、`scipy.signal`（SSA/Lomb-Scargle） |
| 可視化 | Plotly、Matplotlib、Streamlit（7 頁籤雙管線儀表板） |
| 評估 | scikit-learn metrics、`shap`（可解釋性） |
| 版本控制 | Git（GitHub: RhynoW/Sat_TraingDataExtension） |
| 排程 | Claude Code Remote Agent（每日 MEME 下載） |

---

## 九、風險與因應措施

| 風險 | 可能性 | 影響 | 因應措施 |
|------|--------|------|----------|
| Starlink MEME API 停止服務 | 低 | 高 | 合成資料補充；`residuals_*.csv` 已存 284 顆歷史資料；切換 ISS + 其他衛星 |
| 3 個月標記資料仍不足 | 中 | 中 | 強化合成資料生成（`residuals_*.csv` 提供殼層雜訊校準基準）；Transfer Learning |
| TLE 精度限制微型機動 | 高 | 中 | MEME RTN 管線已實作（偵測下限 0.02 km）；調整 TLE 管線目標下限至 200 m |
| 高度自適應閾值過於保守（MEO/GEO） | 中 | 低 | UI 已加入 > 1200 km 警告；Layer 2/3 可作為補充 |
| 計算資源不足（Transformer） | 中 | 低 | 使用輕量化架構；雲端訓練 |
| ISS 機動記錄不完整 | 中 | 低 | 補充 GPS 衛星、Sentinel 等有公開機動記錄的衛星 |
