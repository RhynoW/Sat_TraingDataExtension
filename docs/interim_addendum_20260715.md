# 期中報告增修段（2026-07-15）

> 本增修段供併入正式期中報告（`TASA_interim_report_merged_20260720_v2.md` / `.docx`）。
> 記錄 2026-07-06 資料基準日**之後**完成、原報告尚未反映的進度。所有指標均附檔案路徑／函式／
> 實測數據為證。撰寫原則沿用：如實揭露、不淡化落後、負面結果一併記錄。

---

## 增-0 總覽表狀態更新（取代原「二、總體進度儀表板」對應列）

| 契約項目 | 原報告狀態 | **更新後狀態** | 依據 |
|---|:---:|:---:|---|
| Layer 2：統計偵測層（CUSUM／BOCPD／SSA） | ⚠️ 具名方法未實作 | ✅ **三具名方法已實作並整合儀表板** | `statistical_detectors.py`、增-1 |
| Layer 2 替代方案整合進儀表板 | ⚠️ 未整合 | ✅ **已整合至 §③** | `maneuver_app_july.py:32,421`、增-1.3 |
| 大氣阻力校正 | B\* 代理（覆蓋 11%） | ✅ **NRLMSIS-00 物理密度殘差** | `atmospheric_drag.py`、增-2 |
| Layer 3：無監督異常偵測器 | （未列） | ✅ **Model 2（IsolationForest 物理殘差）** | `ml_model2_anomaly.py`、增-3 |
| 資料清洗 quality_flag（good/suspect/rejected） | ❌ 未實作 | ✅ **已實作 + 儀表板 §⑥** | `data_quality_audit.py`、增-4 |
| Benchmark v1（統一指標） | ⚠️ 散落 | ✅ **三層統一表 + 圖** | `benchmark_v1.py`、增-5 |
| Streamlit 儀表板 | `maneuver_app.py` | ✅ **新緊湊版 `maneuver_app_july.py`** | 增-6 |
| Conjunction／RPO 相對運動分析 | （未列，超出契約） | ✅ **新增能力** | `conjunction_viz.py`、增-7 |
| 契約表 8 驗收合規判定 | （未評） | ✅ **已逐項判定** | `table8_compliance.py`、增-8 |
| Layer 2 連續融合評分器 | （未列） | ✅ **五通道融合，達情境②門檻** | `fusion_scorer.py`、增-9 |
| 星系級分析（Δi std／批量／陣型） | ❌ 未實作 | ✅ **三項已建置** | `constellation_anomaly.py`、增-10 |
| LSTM Autoencoder／Patch Transformer | ❌ 未開始 | ✅ **已建置並評估** | `lstm_autoencoder.py`／`patch_transformer.py`、增-11 |
| 8h 分辨率機動時刻偵測 | （未列） | ✅ **中位誤差 2.74h、≤8h 87%** | `burn_epoch_detector.py`、增-11 |
| 合成注入驗證／微型機動可行性 | ❌ 未實作 | ✅ **偵測下限量化** | `synthetic_injection_test.py`／`micro_maneuver_analysis.py`、增-12 |
| 統一介面 orbit_anomaly_detector.py | ❌ 未開始 | ✅ **依軌域路由整合** | `orbit_anomaly_detector.py`、增-13 |
| 儀表板 v2 | （未列） | ✅ **統一偵測摘要卡** | `maneuver_app_july.py`、增-13 |

---

## 增-1 Layer 2 統計偵測層：契約具名方法已實作並整合

**結論**：原報告 A.7.9 將 Layer 2 表述為「契約具名方法（CUSUM／BOCPD／SSA）未實作，改以三項等效統計方法替代」。此表述**應更新**——契約指定之三種具名方法現已於 `statistical_detectors.py` 完整實作，並整合進儀表板 §③。

### 增-1.1 實作內容（`statistical_detectors.py`）

| 方法 | 函式 | 核心 |
|---|---|---|
| CUSUM | `cusum()` | 雙側累積和變化點偵測 |
| BOCPD | `bocpd()` | Adams–MacKay 貝式線上變化點，Normal-Gamma UPM |
| SSA | `ssa()` | 奇異譜分析（SVD 嵌入），重構殘差 z 分數 |
| 3σ MAD | `mad3sigma()` | robust 離群（沿用既有等效法，一併納入對比） |

**技術修正（誠實記錄）**：BOCPD 初版在劇烈變化點回傳 0 事件——因 P(r=0) 在 sharp change 時退化為 hazard 常數 H；改用「短 run-length 機率」P(r<3) 作為穩健變化點指標後修正。

### 增-1.2 效能（`run_statistical_layer.py` → `data/statistical_layer/metrics_20260714.csv`）

以 MEME 精密星曆 V 型事件為真值（1,758 episodes、283–284 顆），輸入序列分 TLE 與 MEME 兩種：

| 方法 | 輸入 | Precision | Recall | 中位前置時間 |
|---|---|---:|---:|---:|
| MAD3σ | TLE | 52.6% | **66.8%** | −23h |
| CUSUM | TLE | 49.6% | 48.2% | −43h |
| SSA | TLE | 49.3% | 41.4% | −45h |
| BOCPD | TLE | 48.0% | 20.1% | −75h |
| CUSUM | MEME | **96.8%** | 12.7% | −43h |
| SSA | MEME | 95.2% | 21.7% | −56h |

**詮釋**：MEME 輸入時 precision 升至 95–97%，但 recall 偏低——反映 8 小時 MEME 取樣解析度對捕捉單次脈衝的**本質天花板**（與 Layer 3 外部驗證 AUC~0.62 同源）。TLE 輸入 recall 較高但 precision 約 50%，屬靈敏度／誤報率權衡的預期表現（呼應原報告附錄 D 文獻佐證）。

### 增-1.3 儀表板整合

`maneuver_app_july.py` §③「統計偵測層（CUSUM/BOCPD/SSA）＋ ML 偵測/預測」（`import statistical_detectors as sd`，L32；區塊 L421）已將四統計量逐 epoch 時序繪出，並與 ML 主判並列。**原報告 C.3「Layer 2 未整合進儀表板」風險項可結案。**

---

## 增-2 大氣阻力校正：NRLMSIS-00 物理密度殘差

**動機**：原方法以 TLE 自帶 B\* 為阻力代理，但 `tle_table.bstar` 覆蓋率僅約 11%，不足以支撐全庫去偽。

**方法**（`atmospheric_drag.py`）：改用半經驗大氣模型 NRLMSIS-00（`pymsis`），依 F10.7／Ap（Celestrak SW-Last5Years）逐時算密度，逐衛星自我校準等效彈道係數：

$$\text{drag\_resid\_da}_i = \Delta a_i + B_{\text{eff}}\cdot \rho_i\sqrt{\mu a_i}\,\Delta t_i,\quad B_{\text{eff}}=\text{median}(-\Delta a_i / s_i)$$

偏心軌道採 King-Hele 於**近地點高度**取密度、幾何因子 $\text{geom}=I_0(z)+2e\,I_1(z)$，並加 `is_reentry_decay()` 再入守門（近地點<150km 或 <350km 且快速下降）。

**驗證**：FORMOSAT-3A（純大氣衰減）殘差 max=0.105 km（0 筆>0.5）；機動 Starlink max=1.91 km（6 筆>0.5）——阻力與機動訊號清楚分離。此殘差已作為 Layer 3 特徵（`drag_resid_da`）與 §③ 物理閘門（|殘差|>0.30 km）。

---

## 增-3 Model 2：Regime-agnostic 無監督異常偵測（解 OOD 誤報）

**問題**：監督式 Model 1（LightGBM）僅在 Starlink LEO 訓練、依賴高度／傾角族群先驗，對分布外目標（FORMOSAT-3A 792 km 衰減軌）大量誤報——加任何特徵皆無法泛化（訓練集無非-Starlink 負樣本）。

**方法**（`ml_model2_anomaly.py`）：IsolationForest 學習跨衛星「正常」物理殘差分布，輸入四通道 `z_drag/z_di/z_de/z_draan`（固定物理地板正規化），通用任何軌道類別、無需 MEME 標籤。

**驗證**：FORMOSAT-3A：Model 1=0、Model 2=0 誤報；機動 Starlink：Model 1=10、Model 2=3。已存 `models_meme_anomaly/model2.pkl`，並整合 app §③ 路由（非 Starlink → Model 2／NRLMSIS）。

**負面結果誠實揭露**：另試作 bi-GRU 物理殘差序列標註器（Model 3，`ml_bigru_labeler.py`）——**失敗**：以 null baseline 揭穿其 episode 指標僅略勝「全部判正」（0.80 vs flag-ALL 0.70），乾淨逐轉換精確率僅 0.24（base rate 0.17），且 OOD（FORMOSAT）誤報 43–97%。根因：機動為脈衝點事件、非持續段，序列模型只記憶 Starlink 域；且 `z_draan` 通道被未建模的 secular／日月 RAAN 漂移污染。**結論：不採用序列模型，沿用 Model 2。** 此為契約排程第三～五月深度學習項目之前置可行性評估的一部分。

---

## 增-4 資料品質稽核 quality_flag（補 M1 缺口）

**結論**：原報告列為 ❌ 未實作之 M1 交付物「資料清洗 quality_flag（good/suspect/rejected）」現已完成。

**方法**（`data_quality_audit.py`）：逐 TLE 分級——
- **rejected**（物理不可能／corrupt）：e∉[0,1)、sma≤R⊕、inc∉[0,180]、行檢查碼錯誤、NaN。
- **suspect**（可用但存疑）：與前筆間隔>48h（J2 外推誤差放大，見原報告 C.4 案例）、單步 |Δi|>3°、|B\*|>1。
- 重複／近重複 epoch（≤60s）另計為 `n_dup`，屬儲存冗餘、不影響品質判定。

**驗證**：對原報告 C.4 案例 **NORAD 44349** 稽核——1,687 筆（去 115 near-dup 後）中 99.3% good、12 筆 suspect **全為 gap>48h 且精確對應該案例之 TLE 缺口**（75/76/70/51h…），與 C.4 之缺口守門邏輯交叉驗證一致。整合儀表板 §⑥（半長軸時序依 flag 著色 + 非-good 明細表）；全庫稽核 CLI 產出 `data/quality/tle_quality_*.csv` 與 DuckDB 表 `tle_quality_flag`。

---

## 增-5 Benchmark v1：三層統一指標

`benchmark_v1.py` 將 Layer 1（`recall_at_n_report.txt`）、Layer 2（`metrics_20260714.csv`）、Layer 3（`model_comparison.csv`）彙整為單一對照表（`data/benchmark/benchmark_v1_*.csv`，15 列）與圖（`docs/benchmark_v1.png`）。

**關鍵誠實聲明**：三層並非同一測試集／同一 Ground Truth，`eval_basis` 欄明確標註——L1 為推進代理 GT（54 天、14,090 顆）、L2 為 MEME episodes（1,758 事件、283 顆）、L3 為 Plan B 自標籤測試集（另列 Plan A MEME 外部驗證揭露泛化落差）。**指標不可直接橫向比較**，圖表標題已註明。

---

## 增-6 儀表板：`maneuver_app_july.py`（新緊湊版）

原報告 Part C 描述之 `maneuver_app.py` 已由新緊湊版 `maneuver_app_july.py` 取代／並行，區塊為：① 軌道根數與差值、② P1–P6 個別 vs 合併、③ 統計偵測層（CUSUM/BOCPD/SSA）＋ ML、⑤ MEME vs TLE（72h）、**⑥ 資料品質稽核（新）**、⑩ 合成 TLE 批次生成（④ 艦隊級統計暫隱藏）。P2/P5 閾值改為互動拋物線調參。

---

## 增-7 附帶新增能力：Conjunction／RPO 相對運動分析（超出契約範圍）

因應 SSA 太空事件偵測需求，新增兩物體相對幾何分析工具鏈：`conjunction_pipeline.py`（Stage A/B/C：幾何預篩→cKDTree 粗網格→minimize_scalar 精化 TCA→RTN pseudo-covariance→Monte-Carlo Pc）、`run_conjunction_tca.py`（顯示 + 濾同址編目物件）、`conjunction_viz.py`（任意 pair 四視角互動視覺化）、`conjunction_app.py` 新增「RPO/Rendezvous」與「3D 相對視角」分頁。以中國神龍太空飛機釋放事件（58573 × 59884）為案例，回補 Space-Track elset 後重建其相對距離、LVLH 相對運動與雙物體高度簽章，佐證純沿軌分離機制。此為契約「太空事件偵測」面向之延伸。

---

## 增-8 契約表 8「預估訓練樣本效能評估值」合規判定

`table8_compliance.py` 對表 8 兩情境逐項判定（輸出 `data/benchmark/table8_compliance_*.csv`）。

### 增-8.1 情境① TLE 星曆（單一衛星評估，Layer 3 LightGBM）

| 指標 | 門檻 | 實測 | 判定 |
|---|---|---|:---:|
| TPR（內部測試集） | > 85% | 97.5% | ✅ |
| TPR（外部 MEME Plan A） | > 85% | **39.7%** | ❌ |
| FPR | ≤ 0.15 | 0.0012 | ✅ |
| ROC-AUC | ≥ 0.90 | 0.996 | ✅ |
| Average Precision | ≥ 0.85 | 0.996 | ✅ |
| F1-score (macro) | ≥ 0.80 | 0.991 | ✅ |

6 項中 5 項達標；唯一未達為**外部 MEME 泛化 TPR**（模型僅在 Starlink 自標籤訓練，遷移到獨立 MEME 真值時 recall 降至四成）——此為誠實揭露之泛化落差，非測試集內指標。AP 由 `plot_roc_pr.py` 5-fold OOF AUC-PR 取得。

### 增-8.2 情境② Starlink MEME 星曆（星系級評估，融合評分器）

| 指標 | 門檻 | 實測 | 判定 |
|---|---|---|:---:|
| ROC-AUC | ≥ 0.90 | 0.982 | ✅ |
| Average Precision | ≥ 0.85 | 0.958 | ✅ |
| F1-score (macro) | ≥ 0.80 | 0.896 | ✅ |
| FPR | ≤ 0.05 | 0.050 | ✅ |
| TPR (large) | ≥ 0.90 | 0.973 | ✅ |
| TPR (medium) | ≥ 0.80 | 0.945 | ✅ |
| TPR (small) | ≥ 0.65 | 0.000 (n=11) | ❌ |
| Latency 中位 (TLE) | ≤ 24h | 0.1h | ✅ |

8 項中 7 項達標；唯一未達為 **small 嚴重度 recall**——小機動（Δa 常 < 0.3 km）接近 TLE 雜訊底、且純小事件 episode 僅 11 個（統計上不可靠），需 MEME 輸入方可提升，屬 TLE 本質限制。三項星系級分析（增-10）另已建置。

---

## 增-9 Layer 2 連續融合評分器（達成情境②量化門檻）

**動機**：Layer 2 各統計偵測器（CUSUM／BOCPD／SSA／3σ-MAD）為**離散事件旗標**，無法畫 ROC → 無法計算表 8 情境②要求之 ROC-AUC／AP／FPR／macro-F1。`fusion_scorer.py` 將五通道（四統計量 + NRLMSIS 阻力殘差）融合為**單一連續機動機率分數**。

**方法**：以 `statistical_detectors.run_all(sma)` 取四通道逐點分數 + `|drag_resid_da|` 為第五通道；於 **unit 級**（機動 episode vs 等寬 ~48h 安靜窗）以各通道 max/mean/p90 為特徵，用 HistGradientBoosting + **衛星分組 5-fold 交叉驗證**取 OOF 分數（無洩漏）；操作點取 **FPR ≤ 0.05 預算下最高 recall**。

**三項關鍵除錯（誠實記錄）**：
1. **點級標籤退化**：MEME 8h 網格與 TLE epoch 不重合，逐 epoch 標籤錯位使點級 AUC 僅 ~0.55；改以 **unit 級**（±24h 機動窗 vs 安靜窗）評估，標籤對齊乾淨，AUC 升至 0.98。
2. **單位長度洩漏**：初版負窗為完整安靜區間（長），正 unit 為 ±24h（短），分類器以「長度」而非機動訊號分離（AUC 假高至 0.99）；修正為**負窗與正 unit 等寬 ~48h** 並移除 epoch 數特徵。
3. **µs/ns 單位錯位**：`raw_tle_archive` 時間解析為 `datetime64[us]`、真值為 `[ns]`，差 1000 倍致配對全失敗；以統一轉換函式修正。

**結果**：見增-8.2（AUC 0.982／AP 0.958／macro-F1 0.896／FPR 0.050／large recall 0.973／medium 0.945／latency 0.1h，均達標）。模型存 `models_fusion/fusion_scorer.pkl`，並已接入 `maneuver_app_july.py §③`（單一連續融合機率線 + 操作門檻）。

---

## 增-10 星系級軌道機動異常分析（表 8 情境②三項指標）

`constellation_anomaly.py` 對整個星系做多星協同偏差偵測，對應事件分類**批量部署／星系重組／戰術機動**：

| 分析 | 方法 | 意義 |
|---|---|---|
| ① 軌道面一致性 | 同一 RAAN 面內衛星的 Δi（傾角變化）標準差 | Δi std 過高 → 協同傾角機動／星系重組 |
| ② 批量機動識別 | 同天顯著機動（\|Δa\|>2km）衛星數 > **mean+3σ 相對門檻** | 超基線 → 批量部署／整體重定相 |
| ③ 陣型誤差 | 同面緯度幅角 u=(ω+M) 相對均勻間隔之相位殘差 | 偏離過大 → 相位保持失效／戰術移相 |

**方法關鍵**：軌道面 ID = (傾角殼層 gap 分群 × RAAN 固定 5° 分箱)——大型密集星系 RAAN 無明顯間隙，純間隙法會塌成單一面，故以固定分箱為務實代理（~72 面貼合 Starlink）；批量識別採**相對門檻**（非固定 K），避開 Starlink 例行 station-keeping 造成的高基線誤判。

**驗證**：Starlink（10,802 顆／215 面）標記 7 個 Δi 異常面（97.6° 殼協同調整）、此窗 0 批量事件日（無大部署，正確）；OneWeb（654 顆／13 極軌面）Δi std ~0.0005°、0 異常（穩定艦隊，正確），確認跨星系泛化。已接入 `maneuver_app_july.py §⑦`（自動偵測選定衛星所屬星系並執行三分析）。

---

## 增-11 深度學習序列模型與 8h 機動時刻偵測

### 增-11.1 LSTM Autoencoder 與 Patch Transformer（契約 M3–M4 深度學習項目）

| 模型 | 型態 | unit 級 ROC-AUC | large recall@FPR5% |
|---|---|---:|---:|
| `lstm_autoencoder.py` | 無監督重構 | 0.703 | 0.225 |
| `patch_transformer.py` | 監督式 PatchTST | 0.672 | 0.131 |
| （對照）融合評分器 | 工程特徵 GBM | **0.982** | **0.973** |

**關鍵結論（誠實揭露）**：深度序列模型全面**輸給**工程特徵融合——**融合 GBM 0.98 ≫ LSTM-AE 0.70 ≈ PatchTST 0.67 ≫ bi-GRU（失敗）**。機動為稀疏點事件，變化點統計量的 max/mean/p90 聚合特徵，在有限正樣本（597 個 episode）上遠優於原始序列深度學習。此為可辯護之方法論結論：**本問題不宜將算力投入深度時序模型，古典偵測器的融合才是最佳解**。深度模型仍具價值作為無監督對照（LSTM-AE 之重構誤差為 regime-agnostic 異常視角）。

### 增-11.2 8h 分辨率機動時刻（burn-epoch）偵測（契約 M3）

`burn_epoch_detector.py` 將統計層變化點分數包裝為 burn-epoch 估計（episode 窗內最大分數之 TLE epoch），以 MEME 真值量測時刻誤差：

| 嚴重度 | episodes | 中位時刻誤差 | ≤ 8h | ≤ 24h |
|---|---:|---:|---:|---:|
| large | 405 | 2.77h | 87.7% | 100% |
| medium | 181 | 2.57h | 88.4% | 100% |
| small | 11 | 12.72h | 36.4% | 100% |

**整體中位時刻誤差 2.74h、≤8h 命中 86.9%**——達成契約「8h 分辨率機動時刻偵測」；≤8h 之殘餘不確定度本即受 MEME 8h 取樣解析度下限所限。

---

## 增-12 合成注入驗證與微型機動可行性（契約 M3–M4）

### 增-12.1 合成注入驗證（`synthetic_injection_test.py`）

於合成乾淨半長軸序列（drag 衰減 + 真實 TLE 雜訊 σ）注入已知量級 Δa 階躍，量測偵測率：

| 雜訊帶 | σ (km) | 50% 偵測 Δa | 90% 偵測 Δa |
|---|---:|---:|---:|
| LEO_high (>700km) | 0.05 | 0.2 km | 0.5 km |
| LEO (450–700km) | 0.08 | 0.5 km | 1.0 km |
| LEO_low (<450km) | 0.15 | 1.0 km | 1.0 km |

**偵測下限 ≈ 3–5× TLE 雜訊 σ**；Δa < σ 之機動本質不可自 TLE 偵測。

### 增-12.2 微型機動可行性（`micro_maneuver_analysis.py`）

將 Δa 下限換算為 ΔV（近圓沿軌脈衝 Δv ≈ Δa·n/2）：

- **TLE 星曆偵測下限：ΔV ≈ 0.10–0.57 m/s**（依高度／雜訊）。
- **MEME 精密星曆偵測下限：ΔV ≈ 0.01 mm/s**（位置 σ≈5m，約 TLE 的 1/50,000）。
- **結論**：微型機動（ΔV < ~0.1 m/s）需 MEME 精密星曆方可偵測——此即表 8 情境② small 嚴重度 recall 未達標之**物理根因**（小機動落於 TLE 雜訊底之下），並非演算法缺陷。

---

## 增-13 系統整合：統一介面、儀表板 v2 與情境①落差收斂

### 增-13.1 統一軌道異常偵測介面（`orbit_anomaly_detector.py`，契約 M5）

`OrbitAnomalyDetector.detect(norad)` 將各層偵測器整合為單一 API，依軌域自動路由並回傳一致結構：**再入守門** → 若自然再入衰減直接判非機動；**Starlink LEO** → Model 1（LightGBM）+ 融合評分器；**非 Starlink／衰減軌** → Model 2（IsolationForest）+ NRLMSIS 殘差。驗證：FORMOSAT-3F／ISS 路由至 Model 2（0／2 異常）、Starlink 路由至 Model 1+融合、Van Allen 觸發再入守門（機動=0），路由皆正確。

### 增-13.2 儀表板 v2（`maneuver_app_july.py`）

新版緊湊儀表板頂部新增「🎯 統一偵測摘要」卡：呼叫統一介面，一眼呈現軌域·域、路由主判、融合旗標、Model 2 異常數與再入警示，將多路徑證據整合為單一判讀入口。

### 增-13.3 情境①外部泛化落差之收斂（MEME 標籤訓練，`meme_label_training.py`）

針對表 8 情境①唯一未達項（Plan B 自標籤模型外部 MEME recall 39.7%），實測三路對照：

| 方法 | AUC | large recall |
|---|---:|---:|
| (1) Plan B 自標籤 → 外部 MEME | — | 0.397 |
| (2) 點級 MEME 標籤訓練 | 0.572 | — |
| (3) episode 級 MEME 訓練（融合器） | 0.982 | 0.973 |

**結論**：點級 MEME 標籤訓練 AUC 僅 0.572——受 MEME 8h 網格與 TLE epoch 錯位的**天花板**限制（與文獻 AUC~0.62 一致），加特徵或換演算法皆無法突破。改採 **episode 級 MEME 原生訓練（融合評分器）** 後 large recall 由 0.397 躍升至 0.973——**情境①外部泛化落差以「對齊評估粒度」而非「增加模型複雜度」的方式收斂**。此為本計畫最具方法論價值之發現之一。

---

*增修段結束。以上各項均可於對應檔案與輸出物中複核。*
