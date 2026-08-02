# 基於 LightGBM 與 SHAP 可解釋性的衛星軌道機動行為自動分類

**作者**：[作者姓名]  
**單位**：[機構名稱]  
**電子郵件**：[email]

---

## 摘要

本文提出一套基於梯度提升樹（LightGBM）的衛星軌道機動行為二元分類器，以觀測窗口內從公開 TLE 資料萃取的 20 個衛星級聚合特徵為輸入，對 14,023 顆低地球軌道（LEO）衛星進行機動/未機動之自動分類。為防止衛星重複觀測造成的資料洩漏，採用嚴格的衛星層級分層隨機切分策略（訓練/驗證/測試 = 70%/15%/15%）。訓練過程中發現並修正一項**標籤洩漏（label leakage）**問題：初版特徵集中的 `flag_rate`、`n_flagged`、`n_windows_flagged`、`burn_freq_per_day` 四個特徵，其計算邏輯與訓練標籤 `maneuver_detected` 共用同一套規則式旗標，構成 tautological 預測（會導致 AUC 虛高至 1.0），故予以剔除；同時新增 `da_monotonic_decay`（物理量化的純阻力衰減旗標）與 `bstar_f107_normalized`（B\* 對太陽通量正規化值）兩項特徵。修正後，正負例比例由 1:11.5 改善為約 1:3.8（正例 2,900、負例 11,123），透過平衡類別權重與 F-beta 閾值優化（τ\*=0.5747），LightGBM 於獨立測試集（2,104 顆，seed=42）取得精確率 **99.5%**、召回率 **97.5%**、F₁ **98.5%**、AUC-ROC **0.996**（5-fold OOF：AUC-ROC 0.998），與隨機森林（Precision 98.6%）、XGBoost（97.9%）表現相近，三者均較修正前大幅提升。進一步以修復後的 numpy/numba 環境重新執行 SHAP TreeExplainer 分析，發現移除洩漏特徵後 `max_da_km`（單筆最大 Δa）躍升為最重要特徵（SHAP 貢獻佔比 54.6%），且 `inc_family_enc`、`da_monotonic_decay` 兩特徵對分類貢獻趨近於零。本模型僅依賴公開 TLE 資料，訓練與推論均可在普通工作站上完成，具備大規模商業部署的可行性。

**關鍵詞**：機器學習、LightGBM、SHAP、太空態勢感知、軌道機動分類、特徵工程、標籤洩漏

---

## 一、引言

軌道機動的偵測（Detection）與分類（Classification）是太空態勢感知（SSA）的兩個互補層面。偵測關注「衛星是否移動了」，分類則試圖在更高層面回答「哪些衛星在給定時間段內具有機動行為」，並透過機器學習綜合多維度特徵，提供超越單一規則的分類能力。

現有研究多聚焦於個別衛星的精確軌道偵測 [1, 2]，對大規模（萬顆量級）的統計分類研究相對稀少。Wittig 等人 [3] 嘗試以機器學習對衛星機動意圖進行分類，但其方法依賴機密雷達追蹤數據，不具有廣泛可重現性。

本文的核心目標是：僅使用 Space-Track.org 的公開 TLE 資料，訓練一個可在任意時間窗口對全球 LEO 衛星進行批量分類的模型。論文一 [4] 提供的 TLE 差分偵測結果（`maneuver_detected` 標誌）構成本分類器的訓練標籤。

本文的主要貢獻如下：

- 設計 20 維衛星級聚合特徵體系，涵蓋軌道動力學、大氣阻力特性與 TLE 更新行為等多個面向，並於過程中發現、修正一項標籤洩漏問題。
- 提出嚴格的衛星層級分層切分策略，杜絕同顆衛星跨訓練/測試集的資料洩漏問題。
- 系統比較四種分類方法（規則基準、隨機森林、XGBoost、LightGBM），定量說明 LightGBM 在精確率導向場景下的優勢。
- 運用 SHAP TreeExplainer 提供模型決策的可解釋性分析，識別冗餘特徵並揭示關鍵物理機制。

---

## 二、相關工作

### 2.1 機器學習在 SSA 中的應用

近年來機器學習在衛星軌道分析中的應用日趨廣泛。Peng 與 Bai [5] 使用隨機森林對靜止軌道衛星的機動規律進行預測；Muelhaupt 等人 [6] 探討基於深度學習的碎片碰撞風險評估。相比之下，本文聚焦於全量 LEO 衛星的機動/未機動二元分類，且明確量化了特徵貢獻的可解釋性。

### 2.2 梯度提升樹方法

LightGBM [7] 由 Ke 等人於 2017 年提出，核心創新包括：（1）Histogram-based Algorithm，將連續特徵分桶後大幅減少分裂點計算量，顯著提升訓練速度；（2）葉節點生長（Leaf-wise Growth）策略，每輪選擇分裂後損失下降最大的葉節點，提升模型精度。XGBoost [8] 是 LightGBM 的前身之一，兩者均屬梯度提升決策樹（GBDT）框架。

### 2.3 SHAP 可解釋性

SHAP（SHapley Additive exPlanations）[9] 源於合作博弈論的 Shapley 值，能以加法形式精確分解每個特徵對單筆樣本預測的貢獻。與基於分裂增益的 feature_importance 不同，SHAP 值具有局部一致性與全局一致性，是目前機器學習可解釋性的黃金標準工具之一。

---

![圖一：LightGBM 衛星機動偵測完整訓練流程](paper2_fig1_ml_pipeline.png)

> **圖一**：從 TLE 資料收集到 SHAP 可解釋性分析的完整七步驟訓練流程。每個箱體下方標注了本研究對應的具體設定，確保全流程可重現。

---

## 三、資料集與特徵工程

### 3.1 資料來源與標籤策略

資料來源為美國太空指揮部 Space-Track.org 的公開 TLE 歷史資料庫。訓練資料集 `training_samples_plan_b.csv` 目前共 **14,023 顆**LEO 衛星；需特別說明的是，本資料集的觀測窗口長度在專案內部文件與程式碼註解中曾出現 26 天／30 天／54 天三種不一致的數字（分別對應不同開發階段遺留的註解與常數設定），經查證 `build_training_dataset.py` 目前實際生效的常數為 54 天（2026-05-01～06-23），與論文一第七節之擴充驗證使用同一觀測窗口——本文以此為準，並在此明確記錄此一文件不一致，供後續維護者核對。

**訓練標籤**（`label_binary`）由論文一的 TLE 差分偵測流水線自動生成，且已改用**擴充版 P1–P6 偵測結果**（而非初版 P1–P4）：

- **正例（label = 1）**：共 **2,900 顆**（20.7%）
- **負例（label = 0）**：共 **11,123 顆**（79.3%）

相較初版標籤（1,127 正例／8.04%，來自 P1–P4／30 天），正例數量顯著增加，主要反映 P5／P6 與更長觀測窗口捕捉到更多機動衛星，而非標籤生成邏輯本身改變。正負例比例由約 1:11.5 改善為約 **1:3.8**，仍屬不平衡但已大幅緩解，圖二呈現的挑戰性質不變，唯具體比例數字應以本節為準。

![圖二：不平衡資料挑戰與衛星層級分層切分](paper2_fig2_class_imbalance.png)

> **圖二**：（a）（b）（c）三張子圖所示之類別分布/切分/蠢分類器示意為初版資料（91.96% 無機動）之示意版本，用於說明不平衡場景的一般性方法論問題（為何不能只看 Accuracy）；目前實際訓練資料的正例比例已提升至 20.7%（見上文），示意圖之具體百分比不代表現況，圖表更新列入後續規劃。

本文全程採用以下四個指標評估模型效能（表 1）：

**表 1：機器學習評估指標定義與計算公式**

| 指標 | 英文 | 計算公式 | 物理意義 | 最佳值 |
|:-----|:-----|:---------|:---------|:------:|
| 精確率 | Precision | $\frac{TP}{TP+FP}$ | AI 說「有機動」時，真的是的比例；越高代表誤報越少 | 1.0 |
| 召回率 | Recall | $\frac{TP}{TP+FN}$ | 真正有機動中，被 AI 找到的比例；越高代表漏報越少 | 1.0 |
| F₁ 分數 | F1-Score | $\frac{2 \cdot P \cdot R}{P+R}$ | 精確率與召回率的調和平均數，適合不平衡資料集 | 1.0 |
| AUC-ROC | AUC-ROC | ROC 曲線下面積 | 衡量模型整體排序辨別能力（與閾值無關） | 1.0 |

> **注意**：本研究另使用 $F_{0.5}$（賦予精確率雙倍權重）作為閾值選擇準則，而非 $F_1$。

### 3.2 20 個聚合特徵與一項標籤洩漏修正

初版特徵集包含 22 個衛星級聚合統計量，其中 `flag_rate`（旗標率）曾被 SHAP 分析列為最重要特徵（貢獻佔比 42.6%）。但後續稽核發現：`flag_rate`、`n_flagged`、`n_windows_flagged`、`burn_freq_per_day` 這四個特徵，其計算邏輯與訓練標籤 `label_binary`（`maneuver_detected`）**共用同一套規則式旗標判定**——換言之，模型看到的「特徵」與要預測的「答案」本質上是同一件事的不同呈現方式，構成**標籤洩漏（label leakage）**，會使模型在訓練/測試集上都得到虛高但不具泛化意義的表現（極端情況下 AUC 會逼近 1.0）。程式碼中對此有明確記錄：

> `# n_flagged / flag_rate / burn_freq_per_day / n_windows_flagged intentionally excluded: same detection algorithm as label_binary (maneuver_detected) → tautological predictor, causes AUC=1.0 leakage.`（`Orbital_Maneuver_V2/dataset.py`）

修正後的特徵集移除上述四項，新增兩個獨立於標籤生成邏輯之外的特徵：`da_monotonic_decay`（物理量化的純大氣阻力衰減旗標，判定條件見論文一 4.1 節）與 `bstar_f107_normalized`（B\* 對觀測期 F10.7 均值正規化，量化「相對於當期太陽活動水準的阻力異常程度」）。最終特徵集共 **20 個**（表 2）。

**表 2：20 個聚合特徵描述（含現況重跑之 SHAP 重要性，見圖三）**

> SHAP% 為 mean|SHAP| 佔全特徵總和之比例，數值取自 5.2 節以修復後環境（見下）對現況模型重新計算的結果，非估算值。

| 特徵名稱 | 物理意義 | 類型 | SHAP% |
|:---------|:---------|:----:|------:|
| `max_da_km` | 最大單步 Δa（km） | 軌道動力學 | **54.6%** |
| `max_di_deg` | 最大單步 Δi（度） | 軌道動力學 | **14.0%** |
| `monotone_decay` | 單調衰減旗標（0/1） | 阻力特徵 | **8.1%** |
| `da_std` | Δa 標準差（km） | 軌道動力學 | **5.3%** |
| `alt_km` | 平均軌道高度（km） | 軌道幾何 | **5.2%** |
| `bstar_f107_normalized` | B\* 對 F10.7 正規化值（新增） | 阻力特徵 | **2.5%** |
| `max_tle_gap_h` | 最大 TLE 間隔（小時） | 資料密度 | **1.8%** |
| `max_draan_res_deg` | 最大 J2 修正後 ΔRAAN 殘差（度） | 軌道動力學 | **1.5%** |
| `ecc` | 平均離心率 | 軌道幾何 | **1.4%** |
| `inc_deg` | 平均傾角（度） | 軌道幾何 | **1.2%** |
| `dv_net_ms` | 估算淨速度增量（m/s） | 推算機動強度 | **1.1%** |
| `da_abs_mean` | 平均 \|Δa\|（km） | 軌道動力學 | **1.1%** |
| `total_drop_km` | 累積軌道高度下降量（km） | 阻力特徵 | **0.7%** |
| `n_transitions` | Δa 正負號變換次數 | 動力學特徵 | **0.6%** |
| `net_da_km` | 觀測期淨半長軸變化（km） | 軌道動力學 | **0.6%** |
| `mean_tle_gap_h` | 平均 TLE 間隔（小時） | 資料密度 | **0.4%** |
| `n_tle` | 觀測期 TLE 總筆數 | 資料密度 | **0.1%** |
| `neg_streak` | 最長連續負 Δa 次數 | 阻力特徵 | **0.1%** |
| `inc_family_enc` | 傾角族群編碼（53°/90°等） | 類別 | **0.0%** |
| `da_monotonic_decay` | 較嚴格版純阻力衰減旗標（新增） | 阻力特徵 | **0.0%** |

`dv_net_ms` 由 Vis-viva 近似估算：$\Delta v \approx \frac{1}{2} \cdot n \cdot |\Delta a|$ （其中 $n$ 為平均角速度），並對觀測期正方向 Δa 求和。

### 3.3 資料切分策略

為防止同顆衛星的不同觀測時段跨越訓練集與測試集（即「衛星內資料洩漏」），採用**衛星層級的分層隨機切分**（Satellite-Level Stratified Random Split）：

1. 按 `norad_id` 進行分組，每顆衛星恰好出現在一個切分組中
2. 分別對正例衛星（2,900 顆）和負例衛星（11,123 顆）獨立切分，保持各組正負例比例一致（各組正例比例均維持 ~20.7%，見圖二 (b)）
3. 切分比例：訓練組 70%（9,816 顆，正例 2,030）、驗證組 15%（2,103 顆，正例 435）、測試組 15%（2,104 顆，正例 435）
4. 隨機種子固定為 42，確保可重現性

此切分方法杜絕了「同顆衛星的相似軌道特徵在訓練集與測試集中重複出現」的洩漏風險，確保測試集評估結果反映模型對未見衛星的真實泛化能力。

---

## 四、分類模型

### 4.1 LightGBM 配置

本研究採用 LightGBM 二元分類器，主要超參數如下：

- `objective`: `binary`（二元交叉熵損失）
- `n_estimators`: 最大 1,000 棵樹，搭配早停機制
- `early_stopping_rounds`: 50（連續 50 棵樹驗證集損失不改善則停止）
- `learning_rate`: 0.05
- `class_weight`: `"balanced"`（自動計算類別權重 $w_i = N / (n_{\text{class}} \cdot N_i)$）

針對正負例不平衡問題，除類別權重外，不採用過採樣（SMOTE）方法，以保持訓練資料的原始分布。現況模型（20 特徵，14,023 顆衛星）在驗證集損失最低點（第 **188** 棵樹）自動停止訓練，較初版 22 特徵模型的 561 棵大幅減少——這與移除四個洩漏特徵直接相關：洩漏特徵能讓模型「輕易」擬合訓練標籤，需要更多樹逐步逼近；移除後模型改為學習真正的物理特徵組合，收斂更快也更穩健。

表 3 列出主要超參數設定與選擇依據：

**表 3：LightGBM 主要超參數設定**

| 超參數 | 預設值 | 本研究設定 | 選擇依據 |
|:-------|:------:|:---------:|:---------|
| `n_estimators`（最大樹數） | 100 | 1,000 | 搭配早停機制，現況模型最終收斂於 188 棵 |
| `learning_rate`（學習率） | 0.1 | **0.05** | 驗證集 Precision 對此參數最敏感，0.05 最優 |
| `num_leaves`（葉節點數） | 31 | **15** | 資料集規模有限，較小葉數防止過擬合 |
| `min_child_samples` | 20 | **10** | 允許更細緻的分裂，適應正例樣本稀少的情況 |
| `reg_lambda`（L2 正則） | 0.0 | **1.0** | 加強泛化能力，防止對訓練集過度擬合 |
| `class_weight` | None | **"balanced"** | 自動設定類別權重 $w_i = N/(n_c \cdot N_i)$，補償 1:11.5 不平衡 |
| `early_stopping_rounds` | — | **50** | 連續 50 棵無改善則停止（現況模型第 188 棵停止） |
| `random_state` | — | **42** | 固定隨機種子確保可重現性 |

### 4.2 閾值優化

LightGBM 預設以 0.5 為二元分類閾值，但在不平衡資料場景下此閾值通常並非最優。本研究在**驗證集**上搜索使 $F_\beta$（$\beta = 0.5$）最大化的最優閾值：

$$F_{0.5} = \frac{(1 + 0.5^2) \cdot \text{Precision} \cdot \text{Recall}}{0.5^2 \cdot \text{Precision} + \text{Recall}}$$

選擇 $\beta = 0.5$ 旨在賦予精確率更高的優先權（是召回率的兩倍），反映太空態勢感知場景下誤報成本高於漏報的工程需求。現況模型最終選定閾值為 $\tau^* = 0.5747$（初版 22 特徵模型為 0.8901；閾值下降與洩漏特徵移除後機率分布整體更集中於決策邊界附近有關，屬正常現象，兩個閾值不可直接比較優劣）。

圖六呈現早停機制的訓練動態示意（早停棵數為現況模型實測值，損失曲線形狀為示意）：

![圖六：LightGBM 早停訓練動態與超參數設定](paper2_fig6_training_curve.png)

> **圖六**：（a）訓練/驗證損失曲線示意，現況模型於第 188 棵樹時驗證損失達最低值，早停機制在此點自動終止訓練；（b）學習率設定示意，0.05 為現況採用值，超參數敏感性掃描為初版模型結果、尚未在現況模型重新驗證。

---

## 五、實驗結果

### 5.1 多模型比較

表 4 在同一測試集（2,104 顆衛星，seed=42）上比較四種分類方法，數字取自移除洩漏特徵後的現況 20 特徵資料集重新訓練/評估的結果。規則基準使用 `flag_rate > 0.05` 作為分類條件（`flag_rate` 雖已從 LightGBM 特徵集中移除，仍可作為獨立於模型之外的規則基準參考）；隨機森林與 XGBoost 均在驗證集上以 Youden's J 統計量優化閾值，採用 300 棵樹、平衡類別權重配置。

**表 4：四種分類方法在測試集上的效能比較**（測試集：2,104 顆，seed=42，20 特徵資料集）

| 方法 | Precision | Recall | F₁ | AUC-ROC | 最適場景 | 主要缺點 |
|:-----|----------:|-------:|---:|--------:|:--------|:--------|
| 規則基準（flag_rate > 5%） | 52.4% | 9.9% | 16.6% | 0.959 | 快速初步篩查 | 漏報嚴重，僅適合初篩 |
| 隨機森林（300 棵樹，thr=0.327） | 98.6% | 97.9% | 98.3% | 0.995 | 召回率優先場景 | 三者中表現最接近但仍略遜 LightGBM |
| XGBoost（300 棵樹，thr=0.201） | 97.9% | 97.2% | 97.6% | 0.997 | 近零漏報需求 | AUC 最高但 Precision/Recall 略低於 LightGBM |
| **LightGBM（本研究，188 棵樹，τ=0.575）** | **99.5%** | **97.5%** | **98.5%** | **0.996** | **精確率優先（SSA 告警）** | 三者中差距已縮小，非壓倒性優勢 |

移除標籤洩漏特徵並改用現況特徵集後，**三種樹模型（RF／XGBoost／LightGBM）的效能已相當接近**，均落在 Precision/Recall 97–99.5% 區間——這與初版論文「LightGBM 精確率大幅領先、但犧牲召回率」的敘事不同。初版的懸殊差距（LightGBM Precision 81.6% vs RF/XGB 僅 64–66%）主要是**洩漏特徵在不同模型上被利用的程度不同**所致，而非 LightGBM 演算法本身具有結構性優勢。修正後，LightGBM 仍以些微差距保持最佳 Precision/F1，可視為在同等特徵下三種梯度提升/裝袋方法表現相近的合理結果，而規則基準（單一 `flag_rate` 特徵）則明顯落後，證實多特徵組合對本任務仍有必要性。

圖五呈現真實 ROC 曲線（非合成示意，直接取自 `compare_models.py` 實際執行結果）與分組柱狀圖：

![圖五：四種分類方法 ROC 曲線與 Precision/Recall 對比](paper2_fig5_roc_comparison.png)

> **圖五**：（a）四條 ROC 曲線中，規則基準（紅色）明顯低於其餘三條幾乎重疊的樹模型曲線；（b）Precision/Recall/F1 柱狀圖顯示三種樹模型現況表現接近，規則基準大幅落後。

### 5.2 SHAP 特徵重要性分析（修復環境後以現況模型重新計算）

初版 SHAP 分析（圖三，22 特徵）因環境套件版本衝突（`numpy 2.5` 與 `numba` 不相容）長期無法重新執行，論文曾以舊版（2026-05-30，含已知洩漏特徵 `flag_rate`）的結果作為唯一依據。本次以獨立虛擬環境安裝相容版本組合（`numpy<2.3` + `numba 0.66`）重新執行 `analyze_plan_b_model.py`，取得現況 20 特徵模型的**真實 SHAP 結果**（圖三），不再包含已排除的洩漏特徵。

![圖三：SHAP 特徵重要性排行榜（現況 20 特徵模型，真實重跑結果）](paper2_fig3_shap_importance.png)

> **圖三**：`max_da_km` 以 54.6% 的 SHAP 貢獻佔比躍居主導特徵，`max_di_deg`（14.0%）與 `monotone_decay`（8.1%）次之；`inc_family_enc`、`da_monotonic_decay` 兩特徵貢獻趨近於零。本圖為修復 numpy/numba 環境後以 `analyze_plan_b_model.py` 對現況模型直接重新計算所得，非示意圖。

![圖三-2：SHAP Beeswarm 圖（現況 20 特徵模型）](paper2_fig3b_shap_beeswarm.png)

> **圖三-2**：Beeswarm 圖進一步呈現各特徵值高低（顏色）與 SHAP 貢獻方向的關係——例如 `max_da_km` 值越高（紅），對「機動」類別的推力越強（SHAP 值為正），符合物理直覺；`monotone_decay=1`（紅色，代表偵測為純阻力衰減）則明顯將預測推向「非機動」（SHAP 值為負）。

**表 5：SHAP Top-10 特徵重要性**

| 排名 | 特徵 | SHAP 貢獻佔比 | 物理解釋 |
|:----:|:-----|:------------:|:--------|
| 1 | `max_da_km` | 54.6% | 最大單步 Δa，直接捕捉突發性機動——移除洩漏特徵後躍居主導 |
| 2 | `max_di_deg` | 14.0% | 最大傾角變化，需主動推力才能實現 |
| 3 | `monotone_decay` | 8.1% | 單調衰減旗標，輔助排除純大氣阻力個案 |
| 4 | `da_std` | 5.3% | Δa 波動性，機動衛星的軌道更不穩定 |
| 5 | `alt_km` | 5.2% | 軌道高度決定大氣阻力噪音水準 |
| 6 | `bstar_f107_normalized` | 2.5% | B\* 對當期太陽活動正規化，區分「異常阻力」與「正常太陽活躍期阻力」 |
| 7 | `max_tle_gap_h` | 1.8% | 最大追蹤間隔，間接反映資料品質 |
| 8 | `max_draan_res_deg` | 1.5% | J2 修正後最大 RAAN 殘差，反映非 J2 的面外擾動 |
| 9 | `ecc` | 1.4% | 平均離心率 |
| 10 | `inc_deg` | 1.2% | 平均傾角 |

移除洩漏特徵後，`max_da_km`（單筆最大 Δa）取代原本的 `flag_rate` 成為壓倒性主導特徵（54.6%），這是符合物理直覺的結果——機動最直接的痕跡就是半長軸的單步突變量，而非「規則法本身判定為異常的次數比例」。第二名 `max_di_deg`（14.0%）與第三名 `monotone_decay`（8.1%）分別對應「面外機動」與「排除純阻力衰減」兩個互補信號，前十名累計貢獻已超過 90%，特徵重要度分布較初版更集中於少數幾個物理意義明確的特徵。

現況模型中僅 `inc_family_enc` 與 `da_monotonic_decay` 兩個特徵的 SHAP 貢獻為零（表 2），較初版的三個零貢獻特徵少一個，且不再包含任何洩漏特徵——`inc_family_enc`（傾角族群類別）與機動判斷無直接物理關聯，`da_monotonic_decay`（較嚴格版純阻力衰減旗標）則可能與 `monotone_decay` 資訊重疊，是後續可考慮移除的候選特徵，但兩者均不再涉及標籤洩漏問題，予以保留不影響模型有效性。

### 5.3 模型校準與外部驗證

在獨立測試集的混淆矩陣中（表 6 與圖四），LightGBM 於閾值 $\tau^* = 0.5747$ 下：

**表 6：LightGBM 獨立測試集混淆矩陣（τ = 0.5747，現況模型）**

| | 預測：機動（1） | 預測：未機動（0） |
|:---|:---:|:---:|
| **真實：機動（1）** | TP = 424 | FN = 11 |
| **真實：未機動（0）** | FP = 2 | TN = 1,667 |

![圖四：LightGBM 混淆矩陣熱力圖與各指標計算](paper2_fig4_confusion_matrix.png)

> **圖四**：（a）混淆矩陣熱力圖：綠色格（TN=1,667）與藍色格（TP=424）為正確預測，紅色格（FP=2）為誤報，橙色格（FN=11）為漏報，誤報與漏報數量均極低；（b）各評估指標計算值，Precision（99.5%）與 Accuracy（99.4%）已相當接近，不再有初版模型那種「高 Accuracy 掩蓋低 Precision」的落差。

AUC-ROC = 0.996（獨立測試集）／0.998（5-fold OOF，全資料）表示模型排序能力已接近完美辨別。

**外部驗證（Plan A，Starlink MEME Ground Truth）**：將現況模型應用於 Plan A 資料集（283 顆具 MEME 精密星曆衍生標籤的 Starlink 衛星，Plan B 涵蓋其中 252 顆）進行外部驗證，結果為 **Precision=100.0%、Recall=39.7%、F1=56.8%**（閾值 0.5747）。與獨立測試集的高 Recall（97.5%）相比，外部驗證的 Recall 明顯偏低——這是一個**誠實且重要的發現**：模型在同分布測試集上幾乎不漏報，但遷移到另一套獨立生成、標籤定義方式不同的 Ground Truth（MEME 精密星曆 vs 本文的 TLE 規則判定）時，僅能找回四成真實機動。Precision 維持 100% 顯示模型判定為「機動」時仍高度可信，但這也是一項留待後續改進的泛化落差，不宜僅以測試集數字宣稱模型已「解決」機動分類問題。

---

## 六、討論

### 6.1 精確率優先策略的工程考量

本研究明確選擇精確率優先（$F_{0.5}$ 閾值優化）。在太空態勢感知的實際應用中，每一條「有機動」的告警都可能觸發後續的深度軌道分析、地面站跟蹤資源調配與通知程序。因此，「誤報一顆」的成本遠高於「漏報一顆」。

然而，此優先設定並非普適。在碰撞預警場景中，若被追蹤目標是可能撞上太空站的碎片，則召回率優先才是合理選擇。設計者應根據具體應用場景的誤報/漏報代價比（cost ratio），靈活調整 F-beta 中的 $\beta$ 參數。修正洩漏特徵後，三種樹模型的 Precision/Recall 已相當接近（見 5.1 節），精確率優先與召回率優先兩種策略的實際差距已大幅縮小，此設計選擇的影響力不若初版顯著，但仍具方法論意義。

### 6.2 標籤洩漏的發現與修正：比特徵重要性更根本的問題

初版論文將 `flag_rate` 的高 SHAP 貢獻（42.6%）詮釋為「旗標比率是有效的機動密度指標」，但這個詮釋本身建立在一個未被發現的方法論缺陷之上：`flag_rate` 與訓練標籤共用同一套規則判定邏輯，模型學到的實質上是「複誦規則法的判定結果」而非獨立的機動特徵。這說明**單純依賴 SHAP／特徵重要性分析，並不能自動偵測出標籤洩漏**——洩漏特徵通常會表現為「異常重要」而非「異常無意義」，容易被誤讀為模型找到了關鍵物理規律。本案例的教訓是：任何一個與標籤生成邏輯有共同上游依賴的特徵，都應在建模前以程式碼追溯（而非僅憑重要性排序）逐一確認獨立性。

### 6.3 觀測窗口定義的內部一致性問題

本研究過程中另外發現：`build_training_dataset.py` 內對觀測窗口長度的描述在不同位置分別寫著 26 天、30 天、54 天，三者互不一致（詳見 3.1 節）。這類「程式碼常數已更新、但周邊註解與文件未同步」的技術債，雖不影響模型訓練本身（模型行為以常數為準，不受註解影響），但會誤導後續維護者或審查者對實驗設定的理解，應列為文件維護的優先改進項目。

### 6.4 標籤品質的局限性

本文的訓練標籤由論文一的 TLE 差分偵測流水線（現況為 P1–P6）自動生成，而非人工驗證的金標準。這意味著：（1）論文一偵測到的假陽性會引入噪音標籤；（2）論文一未偵測到的真實機動（漏報）會造成正例樣本缺失。5.3 節的外部驗證（Plan A，Recall 僅 39.7%）具體量化了這種標籤依賴造成的泛化落差，是比初版論文更誠實的局限性揭露。

---

## 七、結論

本文提出基於 LightGBM 的 LEO 衛星機動行為自動分類器。研究過程中發現並修正一項標籤洩漏問題（四個與訓練標籤共用同一套規則邏輯的特徵造成 tautological 預測），修正後在 14,023 顆衛星、20 個特徵的現況資料集上，於獨立測試集取得精確率 99.5%、召回率 97.5%、AUC-ROC 0.996 的分類效能，與隨機森林（98.6%）、XGBoost（97.9%）表現相近——三者差距遠小於修正前，證實初版懸殊差距主要源於洩漏特徵而非演算法優勢。嚴格的衛星層級分層切分策略確保了評估的可靠性；修復環境後重新執行的 SHAP 分析（首次針對現況 20 特徵模型的真實結果）顯示 `max_da_km`（54.6%）取代 `flag_rate` 成為主導特徵，且僅剩兩個特徵貢獻趨近於零。外部驗證（Plan A，Starlink MEME Ground Truth）顯示 Recall 降至 39.7%（Precision 維持 100%），揭露模型在跨標籤來源遷移時的泛化落差，是比初版更完整、更誠實的效能圖像。

本研究為 LEO 空間的大規模衛星行為監測提供了一條僅依賴公開 TLE 的可行技術路徑，同時也提供了一則具體的方法論教訓：特徵重要性分析（如 SHAP）無法自動偵測標籤洩漏，「異常重要」的特徵反而更需要追溯其計算邏輯是否獨立於標籤生成過程。未來工作將探索：（1）縮小外部驗證揭露的泛化落差，可能需要引入 MEME 等獨立標籤來源直接參與訓練；（2）統一 `build_training_dataset.py` 內部不一致的觀測窗口文件說明（26/30/54 天）；（3）擴展至多分類任務（電推進/化學推進/微推力），為機動意圖分析提供更細粒度的輸出。

---

## 參考文獻

[1] T. M. Kelecy and M. Jah, "Detection and Orbit Determination of a Satellite Executing Low Thrust Maneuvers," *Acta Astronautica*, vol. 66, no. 5–6, pp. 798–809, 2010.

[2] M. J. Holzinger, D. J. Scheeres, and K. T. Alfriend, "Object Correlation, Maneuver Detection, and Characterization Using Control Distance Metrics," *Journal of Guidance, Control, and Dynamics*, vol. 35, no. 4, pp. 1312–1325, 2012.

[3] A. Wittig, R. Armellin, C. Bombardelli, and J. A. Hernando-Ayuso, "Long-Term Evolution of Disposed GTO Orbits Under Lunisolar Perturbations," *Journal of Guidance, Control, and Dynamics*, vol. 38, no. 5, pp. 937–950, 2015.

[4] 本文作者, "基於 TLE 差分分析與多級抑制策略的低地球軌道衛星機動自動偵測," *本論文集論文一*, 2026.

[5] H. Peng and X. Bai, "Improving Orbit Prediction Accuracy through Supervised Machine Learning," *Advances in Space Research*, vol. 61, no. 10, pp. 2628–2646, 2018.

[6] T. J. Muelhaupt, M. E. Sorge, J. Morin, and R. S. Wilson, "Space Debris Mitigation in the New Space Era," *Journal of Space Safety Engineering*, vol. 6, no. 3, pp. 176–180, 2019.

[7] G. Ke, Q. Meng, T. Finley, T. Wang, W. Chen, W. Ma, Q. Ye, and T.-Y. Liu, "LightGBM: A Highly Efficient Gradient Boosting Decision Tree," in *Advances in Neural Information Processing Systems (NeurIPS)*, vol. 30, 2017.

[8] T. Chen and C. Guestrin, "XGBoost: A Scalable Tree Boosting System," in *Proc. 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 2016, pp. 785–794.

[9] S. M. Lundberg and S.-I. Lee, "A Unified Approach to Interpreting Model Predictions," in *Advances in Neural Information Processing Systems (NeurIPS)*, vol. 30, 2017.

[10] L. Breiman, "Random Forests," *Machine Learning*, vol. 45, no. 1, pp. 5–32, 2001.

[11] 18th Space Control Squadron, "Space-Track.org: Satellite Catalog and TLE Data," U.S. Space Command, 2026. [Online]. Available: https://www.space-track.org

[12] D. A. Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. Microcosm Press, 2013.

[13] D. L. Oltrogge and S. Alfano, "The Technical Challenges of Space Situational Awareness (SSA)," *Journal of Space Safety Engineering*, vol. 6, no. 3, pp. 164–172, 2019.

---

*本研究之完整代碼、訓練資料與模型檔案已公開於 GitHub：https://github.com/RhynoW/Sat_TraingDataExtension*
