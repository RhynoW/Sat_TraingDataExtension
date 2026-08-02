# 以 MEME Ground Truth 調教機動偵測 ML 模型 — 設計文件

**版本**：草案 v0.1　**日期**：2026-07-14　**計畫案號**：TASA-S-1150268
**真值來源決策**：直接讀取 `data/raw/` MEME 精密星曆檔（不依賴中間 `residuals_*.csv`）

---

## 1. 結論（先講重點）

- **目標**：讓 Layer 3 的 ML 模型改由 **Starlink MEME 精密星曆的機動真值** 監督學習，從「模仿 TLE 規則」升級為「真的從 TLE 特徵辨識機動」。
- **核心手段**：用研究 3 已驗證的 `maneuver_burn_times`（相鄰 MEME 檔平均半長軸階躍）掃描全部 **285 顆** 衛星的 `data/raw/` 星曆，產生 **帶時刻的 burn 真值**，據此重新標註訓練視窗。
- **最大收益**：一旦標籤與 TLE 規則脫鉤，先前因**同義洩漏（tautological leakage）被迫丟棄的 4 個高資訊特徵**（`n_flagged / flag_rate / burn_freq_per_day / n_windows_flagged`）即可重新啟用。
- **本文件不改任何程式**；僅定義資料流、標籤協定、評估協定與後續實作清單，待核可後動工。

---

## 2. 現況診斷：為什麼要調教

### 2.1 部署模型其實在「模仿規則」而非「學機動」

現行訓練集 `data/maneuvers/training_dataset_final.parquet`（17,404 列 × 71 欄）的標籤來源：

| `label_source` | `plan` | 列數 | 佔比 | 真值性質 |
|---|---|---:|---:|---|
| `tle_annotation_v1` | B | 14,023 | **81 %** | TLE 規則偵測器（P1–P6）**自標** |
| `meme_ephemeris` | A | 3,381 | 19 % | MEME 精密星曆真值 |

部署中的 **models_plan_b/** 主要吃 Plan B（81 %）。其後果寫在程式註解裡（[dataset.py:59-62](../Orbital_Maneuver_V2/dataset.py#L59)）：

> `n_flagged / flag_rate / burn_freq_per_day / n_windows_flagged intentionally excluded: same detection algorithm as label_binary → tautological predictor, causes AUC=1.0 leakage.`

也就是：

1. **標籤 = 規則輸出** → 模型天花板 = 那條規則，學不到規則抓不到的機動，也糾正不了規則的誤判（`behavior` 欄含 `UnknownFP` 140 筆即為規則誤判）。
2. 為避免 AUC=1.0 洩漏，被迫**丟掉 4 個最有訊息量的特徵**，模型可用資訊被人為削弱。

### 2.2 MEME 真值已被研究量化，可直接拿來當監督訊號

| 研究產出 | 數值 | 對調教的用途 |
|---|---|---|
| 純外推誤差地板（study1/3） | P50 ≈ 2.5 km、機動 ×14（246 km → 3,473 km） | 校準「多大殘差才算機動」的門檻，降低把 TLE 老化誤判為機動 |
| `maneuver_burn_times`（study3） | 相鄰檔平均 a 階躍 ≥ 0.2 km 判機動 | **物理直接、帶 burn 時刻** 的真值產生器 |
| 平均半長軸法（`_MEAN_A_LINES=960`） | ~10 軌道平均，殘留振盪 < 0.1 km | 消去 J2 短週期振盪，使 0.2 km 門檻可靠 |

---

## 3. 真值來源設計（直接讀 `data/raw/`）

**決策**：不經 `residuals_*.csv`，直接對每顆衛星的原始 MEME 檔即時計算真值。理由：(a) 訊號來自平均半長軸階躍，**不受 TLE 品質污染**（pos_err V 型會混入 TLE 老化）；(b) 少一層中間檔依賴；(c) 直接給得出 burn 發生時刻，可對齊特徵視窗。

### 3.1 產生流程（重用既有函式，不重造輪子）

```
for 每顆衛星 sat in data/raw/*:
    files      = find_all_ephemeris_files(sat)              # compare_tle_vs_ephemeris
    file_tbl   = build_file_table(files, sat)               # study3：epoch, mean_a, 首筆近真值
    burns_ns   = maneuver_burn_times(file_tbl, thr=0.2km)   # study3：burn 近似時刻(int64 ns)
    # 每個 burn 展開為一個「機動時窗」 [burn - Δ, burn + Δ]
```

- `maneuver_burn_times` 已實作於 [study3_tle_frozen_and_gap.py:134](../study3_tle_frozen_and_gap.py#L134)。
- `build_file_table` / `file_epoch_mean_a_first` 只讀每檔前 ~960 行，**全 285 顆掃描成本可接受**（study3 已用同法跑過 50 顆）。

### 3.2 真值輸出格式（新中間檔）

`data/meme_truth/meme_burns_{date}.csv`

| 欄位 | 說明 |
|---|---|
| `norad_id`, `sat_name` | 衛星識別 |
| `burn_t` | burn 近似時刻（UTC，相鄰檔中點） |
| `d_mean_a_km` | 該階躍的平均半長軸變化量（帶正負號：raising/lowering） |
| `burn_window_start / _end` | `burn_t ± Δ`（Δ 見 §4.1） |
| `confidence` | `abs(d_mean_a_km)` 正規化後的信心（供加權訓練/門檻掃描） |

---

## 4. 標籤定義

### 4.1 從 burn 時窗到視窗標籤

MEME 給的是**時刻**，特徵是**視窗聚合**（Plan A 有 `center_epoch`；Plan B 為 26 天視窗但 `center_epoch` 全空）。對齊規則：

| 情境 | 標籤 |
|---|---|
| 特徵視窗 `[window_start, window_end]` 與任一 `burn_window` 有重疊 | `label_meme = 1`（機動） |
| 視窗內無任何 burn，且該衛星該期 MEME 覆蓋充分 | `label_meme = 0`（nominal） |
| MEME 覆蓋不足 / 落在 Mode A 持續發散段 | `label_meme = -1`（排除，不進訓練） |

- **Δ（burn 半寬）建議 12 h**：涵蓋 TLE 更新延遲；沿用 Plan A 的 `MEME_EVENT_WINDOW_H=24` 概念但收斂到單側 12 h。此為**可調超參數**，於 §7 門檻掃描一併定。
- **Plan B 視窗無 epoch 的處理**：Plan B 目前是「整段 26 天」聚合，無法精準對齊 burn。設計選項二擇一（待決，見 §9）：
  - **(A) 重建帶 epoch 的滑動視窗**（建議）：對 285 顆以固定步長（例如 1 天）重切滑動視窗，每窗有 `center_epoch`，可精準對齊 burn → 真值品質最高。
  - **(B) 沿用現有 26 天視窗**：僅用「該衛星該 26 天內是否有 burn」當弱標籤 → 改動小但真值較粗。

### 4.2 多級標籤（可選，供未來分類）

MEME 的 `d_mean_a_km` 正負與量值可直接產生：
- `maneuver_class`：`raising`（+）/`lowering`（−）/`phasing`（小幅來回）/`inclination`（配合 `d_inc`）。
- `severity`：依 `abs(d_mean_a_km)` 分 `small/medium/large`。
- 對應現有 Plan A 已有的 `label_maneuver_class` / `label_severity` 欄，**格式相容**，可直接擴充覆蓋率。

---

## 5. 資料流（端到端）

```
                data/raw/<STARLINK-*>/*.txt   (285 顆 MEME 精密星曆)
                            │
                            ▼  build_file_table + maneuver_burn_times (thr=0.2km)
                data/meme_truth/meme_burns_{date}.csv      ← 新真值中間檔（§3.2）
                            │
   space_db.duckdb ─────────┤  對齊：視窗 ∩ burn_window → label_meme (§4.1)
   (TLE 特徵 build_feature_matrix)
                            ▼
                data/maneuvers/training_dataset_meme_{date}.parquet
                   ├─ 特徵：TLE-only（重新納入 n_flagged 等 4 特徵，§6）
                   └─ 標籤：label_meme (0/1/-1)
                            │
                            ▼  train.py（--parquet 指向新檔）
                models_meme/lgbm_maneuver_meme.pkl  + threshold.json + feature_names.json
                            │
                            ▼  評估（§8）
                MEME-truth hold-out 指標 + 與 models_plan_b 對比
```

---

## 6. 特徵變更

**規則不變**：特徵只能來自 TLE（推論時 MEME 不可得）——沿用 [Orbital_Maneuver_V2/CLAUDE.md](../Orbital_Maneuver_V2/CLAUDE.md) 的鐵律。

**變更點**：因標籤來源改為 MEME（與 TLE 規則脫鉤），下列 4 特徵**不再是同義洩漏，予以重新啟用**：

| 特徵 | 現況 | 調教後 |
|---|---|---|
| `n_flagged` | 排除（洩漏） | **啟用** |
| `flag_rate` | 排除（洩漏） | **啟用** |
| `burn_freq_per_day` | 排除（洩漏） | **啟用** |
| `n_windows_flagged` | 排除（洩漏） | **啟用** |

> 驗證機制：訓練後查 SHAP，若這 4 特徵之一 SHAP 佔比異常壓倒性（近乎單特徵決定），代表 TLE 規則與 MEME 真值高度相關（合理），仍應保留但於報告揭露；若 AUC 又逼近 1.0，回頭檢查標籤是否無意間又等同規則。

其餘特徵沿用 `PLAN_B_FEATURE_COLS`（[dataset.py:45](../Orbital_Maneuver_V2/dataset.py#L45)）。

---

## 7. 門檻與超參數校準（用誤差地板）

| 超參數 | 現值 | 校準方式 |
|---|---|---|
| burn 判定門檻 `maneuver-thr` | 0.2 km（平均 a 階躍） | 以 study3 的 50 顆結果掃描 0.15–0.30 km，取 precision/recall 最佳點 |
| burn 半寬 Δ | 12 h（建議起點） | 掃描 6/12/18/24 h，看對齊後 label 穩定度 |
| pos_err 峰值門檻（若併用 V 型） | 寫死 50 km（[labeler.py:38](../Orbital_Maneuver_V2/labeler.py#L38)） | 改為資料驅動：取純外推誤差 P95 為門檻，降低 TLE 老化誤判 |
| 決策門檻 threshold | F-beta(0.5) 於 val（[train.py:386](../Orbital_Maneuver_V2/train.py#L386)） | 維持既有機制 |

---

## 8. 評估協定

### 8.1 切分（避免洩漏）

- **衛星層級切分**：同一顆衛星不可跨 train/val/test（沿用 `random_split` 的 groupby-norad 邏輯，[dataset.py:183](../Orbital_Maneuver_V2/dataset.py#L183)）。
- 若採 §4.1 選項 A（帶 epoch 滑動視窗），改用**時間切分**（train < val < test 依 epoch），更貼近上線情境。

### 8.2 對比基準（必做）

| 模型 | 標籤 | 特徵 | 角色 |
|---|---|---|---|
| **Baseline** | `label_binary`（TLE 自標） | 現行（缺 4 特徵） | 現行 models_plan_b |
| **MEME-tuned** | `label_meme`（MEME 真值） | 現行 + 4 特徵 | 本設計產物 |

指標：Precision / Recall / F1 / **PR-AUC**（不平衡資料以 PR-AUC 為主）/ AUC-ROC。

### 8.3 獨立真值 hold-out（關鍵誠信檢查）

- 保留一組**從未進訓練**的衛星，其 burn 由 MEME 獨立判定，作為最終 hold-out。
- 報告 **lead-time**：模型在 MEME 確認 burn 前多久能於 TLE 上示警（若採 epoch 視窗）。
- 對比 study3 已標的「機動 vs 純外推」12/50 顆案例，做逐案定性檢視。

---

## 9. 待決事項（需你拍板）

1. **視窗策略（§4.1）**：選 **(A) 重建帶 epoch 滑動視窗**（真值品質高、改動大）還是 **(B) 沿用 26 天視窗弱標籤**（改動小、真值粗）？—— 建議 (A)。
2. **是否併用 pos_err V 型**：`residuals_*.csv` 仍在（3 檔：06-09 / 06-23 / 07-07），可作雙訊號交叉確認，但覆蓋期較短。預設 **只用平均 a 階躍**（依你先前決策）；是否要加 V 型當第二確認？
3. **多級標籤（§4.2）**：本輪先只做二元 `label_meme`，或一併產出 `maneuver_class` / `severity`？

---

## 10. 實作清單（核可後執行，預估改動 5 檔）

| # | 檔案 | 動作 |
|---|---|---|
| 1 | `build_meme_labels.py`（新） | 掃 `data/raw/` → `maneuver_burn_times` → 輸出 `data/meme_truth/meme_burns_{date}.csv` |
| 2 | `build_training_dataset.py`（改） | 對齊 burn 時窗與特徵視窗 → 新增 `label_meme` 欄，輸出 `training_dataset_meme_{date}.parquet` |
| 3 | `Orbital_Maneuver_V2/dataset.py`（改） | `PLAN_B_FEATURE_COLS` 重新納入 4 特徵；新增 `label_meme` 為主標籤選項 |
| 4 | `Orbital_Maneuver_V2/train.py`（改） | 支援 `--label-col label_meme`、輸出至 `models_meme/` |
| 5 | `evaluate_meme_vs_baseline.py`（新） | 依 §8 產出對比表 + hold-out 指標 + 圖 |

---

## 附錄：本設計引用的既有資產

- `study3_tle_frozen_and_gap.py`：`maneuver_burn_times` / `build_file_table` / `file_epoch_mean_a_first`（真值產生器）
- `compare_tle_vs_ephemeris.py`：`find_all_ephemeris_files` / `_meme_first_state` / `propagate_tle` / `query_tles_in_range`
- `Orbital_Maneuver_V2/`：`data_loader.py`（TLE 特徵）、`labeler.py`（Plan A MEME 事件偵測）、`dataset.py`、`train.py`
- 現有資料：`data/raw/`（285 顆）、`data/maneuvers/training_dataset_final.parquet`（17,404 列）、`data/comparison/residuals_*.csv`（3 檔）、`data/study3/`（50 顆研究輸出）
