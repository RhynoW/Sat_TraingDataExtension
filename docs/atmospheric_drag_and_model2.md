# 大氣密度模型（NRLMSIS）阻力殘差 ＋ 第二套 ML 模型

**日期**：2026-07-14　**動機**：FORMOSAT-3A（NORAD 29052，792km 純大氣阻力衰減）被 ML 大量誤報機動。

---

## 1. 結論

1. **根因確認**：監督式 Model 1 只在 Starlink LEO（~500km、活躍機動）訓練，重度依賴 alt/inc **族群先驗**；對非 Starlink/衰減軌**分布外(OOD)**時，不論加多少特徵都會誤報——這是**訓練資料涵蓋**問題（無非 Starlink 負樣本），非特徵問題。
2. **NRLMSIS 大氣阻力殘差**（取代覆蓋率僅 11% 的 bstar）是乾淨的物理機動訊號：扣掉密度模型預測的阻力後，FORMOSAT 殘差≈0、Starlink 真實機動被隔離。
3. **雙模型架構**（互補）：
   - **Model 1**：監督式 LGBM（Starlink 專用）＋ **NRLMSIS 阻力殘差物理閘門** → OOD 安全。
   - **Model 2**：無監督 Isolation Forest on 物理殘差（**regime-agnostic**）→ 通用任何軌道、純衰減零誤報。
4. **驗證**：FORMOSAT-3A → Model 1 = 0、Model 2 = 0；STARLINK-30273 → Model 1 = 10、Model 2 = 3。

---

## 2. 大氣密度模型評估與選擇

| 模型 | 精度 | Python 整合 | 輸入 | 決定 |
|---|---|---|---|---|
| **NRLMSIS-00/2.1**（pymsis） | 高，業界標準 | ★★★ 好裝、C 加速、向量化 | F10.7 + Ap | ✅ **採用** |
| JB2008 | 最高（暴時） | ★ 需 S10/M10/Y10/Dst，無乾淨 Python | +4 指數 | 過度 |
| DTM2020 | 高（歐洲） | ★★ pyatmos | F10.7 + Kp | 次選 |

**採用 NRLMSIS-00**：本專案需「相對阻力殘差」而非「絕對阻力預報」，NRLMSIS 夠用且整合最順。
資料鏈：`pymsis`（已裝）＋ Celestrak `SW-Last5Years.csv`（F10.7 + Ap，存 `space_weather_ap.csv`）。

---

## 3. 阻力殘差公式（atmospheric_drag.py）

近圓軌道阻力衰減率　da/dt = −B · ρ · √(μ·a)

| 步驟 | 式子 |
|---|---|
| 密度 | ρ = NRLMSIS(高度, F10.7, Ap)（沿時序，涵蓋太陽/地磁變化）|
| 形狀項 | s_i = ρ_i · √(μ·a_i) · dt_i |
| 逐衛星校準 | B_eff = median(−Δa_i / s_i)（中位數穩健，排除機動離群）|
| **阻力殘差** | **drag_resid_da_i = Δa_i + B_eff · s_i** |

純衰減 → 殘差≈0；機動 → 殘差=機動 Δa。**F10.7/Ap 造成的自然加速衰減由 ρ 涵蓋 → 不再誤報（等於物理版 P5）**。

驗證：FORMOSAT-3A |殘差|max=0.105km（>0.5km 者 0 筆）；STARLINK-30273 |殘差|max=1.91km（6 筆真實機動）。

---

## 4. Model 1 更新（監督式，Starlink 專用）

- 特徵 32 → **40**：加 `da_frac_neg_7d`、`da_monotonic_decay`、`bstar_mean`、**`drag_resid_da`**、**`drag_resid_absmax_7d`**。
- in-domain 指標幾乎不變（偵測 AUC 0.617、forecast AUC 0.661）——因 Starlink 內既有特徵已足。
- **關鍵**：加特徵**無法**修 OOD（模型仍靠 alt/inc 先驗，alt=792 外插 → 誤報）。故保留**物理閘門**：ML 旗標須同時 (機率≥門檻) 且 (**|drag_resid_da|>0.3km**)。

## 5. Model 2 設計（無監督，regime-agnostic）

`ml_model2_anomaly.py`：
- 物理殘差通道（固定物理地板正規化，非自我 MAD）：
  `z_drag=drag_resid/0.10km`、`z_di=Δi/0.005°`、`z_de=Δe/2e-4`、`z_draan=ΔΩ_J2殘差/0.03°`。
- Isolation Forest（跨衛星彙集）學「正常」分布，離群=機動。
- **不用 alt/inc 族群先驗** → 通用 LEO/MEO/GEO/HEO；純衰減殘差皆<1σ → 零誤報。
- 驗證：80 顆 vs MEME episode Recall 0.30 / Precision 0.44（無監督合理值）；FORMOSAT 異常=0。

**分工**：Starlink（有 MEME）用 Model 1（高精度專家）；其他軌道用 Model 2（通用、安全）。

---

## 6. 產出檔案

| 類型 | 檔案 |
|---|---|
| 大氣阻力 | `atmospheric_drag.py`、`run_drag_residual.py`、`add_drag_features.py`、`space_weather_ap.csv`、`data/drag/drag_resid_*.csv` |
| Model 2 | `ml_model2_anomaly.py`、`Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl` |
| Model 1 特徵 | `build_training_dataset.py`(compute_features)、`Orbital_Maneuver_V2/dataset.py`(PLAN_A_FEATURE_COLS 40) |
| app | `maneuver_app_july.py`（drag 注入 + drag 物理閘門 + Model 2 偵測線）|

## 7. 後續建議
- 把 F10.7/Ap 的 3 小時解析 Ap 陣列（AP1-8）帶入 NRLMSIS 以提升暴時精度（目前用日均 AP_AVG）。
- Model 1 若要真正 OOD 泛化，需加入非 Starlink 負樣本（drag-decay/GEO）重訓；在此之前物理閘門是正解。
