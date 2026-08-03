# 智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究
## 期中進度報告（合併版）

**計畫案號**：TASA-S-1150268
**主辦單位**：行政法人國家太空中心（TASA）
**執行單位**：社團法人中華民國國防科技學術研究學會
**執行期限**：2026-04-24 ～ 2026-11-30（7 個月）
**契約期中截止**：2026-07-31
**本文件簡報日期**：2026-07-20｜**資料基準日**：2026-07-06

---

## 〇、文件說明與版本關係

本報告整合以下四份既有文件的內容，形成單一、內部一致的期中進度陳述：

1. `docs/CCITOrbitalManeuver_Midterm_Prelease_Report_20260624.doc`——2026-06-24 之全計畫層級期中預擬版報告，提供 Layer 1–3 之正式驗證指標（Recall/FAR/ROC-AUC 等）與 55–60% 完成度估計。
2. `docs/paper1_tle_maneuver_detection_zh.md`——Layer 1（TLE 差分機動偵測）技術論文，本次已更新至 P1–P6、54 天全量驗證。
3. `docs/paper2_lightgbm_classifier_zh.md`——Layer 3（LightGBM 機動分類器）技術論文，本次已更新至 20 特徵現況模型，並記錄一項標籤洩漏 bug 的發現與修正過程。
4. `docs/interim_progress_report_20260720.md`——`maneuver_app.py`（Streamlit 儀表板）之進度補充說明。

**本次合併新增的查證與修正工作**（非單純檔案拼接）：

- 派出獨立查證作業，逐行比對論文一所述 P1–P4 與 `leo_annotator/validate_annotations.py` 現況程式碼，確認 P5、P6 之實際觸發條件與預設啟用狀態，並發現「P1–P4」與「P1–P6」兩組指標在文件與程式輸出中互相混用的風險，已於論文一第七節統一釐清。
- 派出獨立查證作業，逐行比對論文二所述特徵集與 `Orbital_Maneuver_V2/` 現況程式碼，發現**訓練資料集與模型檔案皆為未提交的工作區修改**（相對於上次提交 `23c2d9e`），且效能指標與初版論文差距達 15–30 個百分點，非誤差範圍內差異。
- 修復本機 numpy/numba 版本衝突（於獨立虛擬環境安裝相容版本，未變更全域環境），重新執行 SHAP 可解釋性分析，取得現況 20 特徵模型的**真實**特徵重要度（初版圖表描述的是已被排除的洩漏特徵）。
- 新增 4 張以真實輸出資料繪製的圖表（Recall@N、跨星系分層、跨時間段穩定性、Hold-out 事件驗證）與 1 張 `maneuver_app.py` 誤報抑制案例圖，取代／補充原本的示意圖表。

**已與使用者確認的撰寫原則**：對契約內部排程落後之項目如實揭露，不淡化措辭；對照表附具體檔案路徑／函式名稱為證據；`maneuver_app.py` 除錯案例（NORAD 44349 TLE 缺口）納入正式報告，作為降低誤報率的具體實證。

---

## 一、計畫基本資訊

| 欄位 | 內容 |
|---|---|
| 計畫案號 | TASA-S-1150268 |
| 計畫名稱 | 智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究 |
| 主辦單位 | 行政法人國家太空中心（TASA） |
| 執行單位 | 社團法人中華民國國防科技學術研究學會 |
| 執行期限 | 2026-04-24 ～ 2026-11-30（7 個月） |
| 計畫金額 | 新台幣 120 萬元整（期中/期末各 50%） |
| 契約期中截止 | 2026-07-31 |
| 契約三層架構 | Layer 1 閾值基準層／Layer 2 統計偵測層／Layer 3 AI 偵測層 |

---

## 二、總體進度儀表板

下表彙整契約規劃書所定義之技術元件，於**全專案範圍**（含 `leo_annotator/`、`Orbital_Maneuver_V2/`、`maneuver_app.py` 三大程式群）之現況，取代先前分散於各文件的個別對照表。

| 契約項目 | 狀態 | 現況摘要 | 詳見章節 |
|---|:---:|---|---|
| Layer 1：閾值基準層（TLE 差分 + J2 校正） | ✅ 完成，已擴充至 P1–P6 | 14,090 顆衛星、54 天全量評估；Overall Recall 26.9%／FAR 5.4%／Precision@1000 98.2% | Part A |
| Layer 1：GEO 專屬管線 | ✅ 完成 | `maneuver_app.py` `render_geo_page()`，EW/NS/重定位/廢棄/TLE 空白五類事件 | Part C |
| Layer 2：統計偵測層（CUSUM／BOCPD／SSA） | ❌ 未實作 | 契約明列方法皆無程式碼；現有 Lomb-Scargle 用途不同（長軸旋轉週期估算，非變化點偵測） | Part A §A.7、Part D |
| Layer 2 替代方案（現有） | ⚠️ 部分，未整合進儀表板 | `anomaly_detector.py`（3σ MAD，27,131 顆）、`ep_slope_detector.py`（EP 聯集 Recall+30.9%） | Part A §A.7.5 |
| Layer 3：XGBoost（機動偵測用） | ✅ 完成 | 283 顆 Starlink，4 類軌道相位 CV Acc 96.1%；與 Layer 3 LightGBM 比較基準用 XGBoost 為**不同的獨立訓練模型**，兩者不可混淆 | Part B、附錄 C |
| Layer 3：LightGBM（機動分類器） | ✅ 完成，發現並修正標籤洩漏 | 20 特徵現況模型：獨立測試集 Precision 99.5%／Recall 97.5%／AUC-ROC 0.996；外部驗證（Plan A）Recall 降至 39.7%，泛化落差已誠實揭露 | Part B |
| Layer 3：LSTM Autoencoder／Transformer | ❌ 未開始 | 依契約排程屬第三～五個月，尚未逾期 | Part D |
| 合成資料生成器 | ✅ 完成，符合規格 | `synthetic_tle/` 套件，ΔV∈[0.001,50] m/s、Hohmann、J2 攝動精確計算 | 附錄 C |
| 效能評估指標基礎設施 | ✅ 完成 | `Orbital_Maneuver_V2/evaluate.py`、`compare_models.py`、`leo_annotator/compute_recall_at_n.py` 等 | Part A、Part B |
| 星系級異常分析（Δi 標準差／批量機動／陣型誤差） | ⚠️ 部分 | `constellation_planes.py` 有 RAAN 分面與艦隊級 SMA/RAAN 統計，契約指定三項具體指標未實作；依排程屬第四個月，尚未逾期 | Part D |
| 資料清洗 quality_flag（good/suspect/rejected） | ❌ 未實作 | 現以 P1 單調衰減抑制等規則局部替代 | Part D |
| `maneuver_app.py` Streamlit 視覺化儀表板 | ✅ 完成度遠超 6/24 版描述 | 10+ 分析頁籤、三種偵測管線、SSA-RAG 問答整合；6/24 報告誤列為「主要尚待事項」，應更新 | Part C |
| DuckDB 結構化資料庫 | ✅ 完成 | `space_db.duckdb`，27,131～39,009 顆衛星紀錄（依查詢範圍） | 附錄 C |

---

# Part A：Layer 1 — TLE 差分機動偵測（論文一全文整合）

> 以下 A.1–A.8 對應 `docs/paper1_tle_maneuver_detection_zh.md` 全文，已於本次查證中更新至 P1–P6 與 54 天擴充驗證。完整版另存獨立檔案（含 `.docx`）供技術審查使用；本報告收錄全文以維持單一文件的完整性。

## A.0 摘要

準確偵測低地球軌道（LEO）衛星的軌道機動行為，是太空態勢感知（SSA）與碰撞預警的關鍵技術需求。現有方法多依賴完整星曆資料或機密追蹤數據，難以大規模應用於公開衛星目錄。本文提出一套基於公開雙行軌道根數（TLE）的差分偵測框架，透過連續 TLE 對之軌道根數差值（Δa、Δi、Δe、ΔRAAN）識別異常機動信號。針對 TLE 資料中大氣阻力干擾、不同高度噪音水準差異及衛星個體阻力特性不一致等問題，依序設計六項改進策略（P1–P6）：（P1）單調衰減抑制與激增點救援、（P2）軌道高度自適應閾值、（P3）B\* 輔助條件、（P4）多窗口補充掃描、（P5）F10.7 太陽通量自適應閾值倍率、（P6）星座感知專屬閾值。於 2026 年 5 月 1–30 日之觀測窗口，對 14,019 顆 LEO 衛星進行 P1–P4 消融實驗：完整 P1–P4 架構相較基準版本，假陽性數量由 68 顆降至 29 顆，精確率由 94.8% 提升至 97.5%，並透過 P4 多窗口補充找回 26 顆基準方法遺漏之真實機動衛星。進一步將觀測窗口延伸至 54 天（2026-05-01～06-23）、衛星規模擴大至 14,090 顆並加入 P5–P6，於此擴充設定下取得 Overall Recall = 26.9%、FAR = 5.4%、Precision@1000 = 98.2%；並透過獨立 Hold-out 事件驗證（99 個 MEME 觀測到的真實軌道偏移事件）取得事件級 Recall = 57.6%、平均偵測前置時間 24.4 小時，以及跨時間段穩定性測試（89.7% 一致率）驗證方法穩健性。本方法僅使用公開 TLE 資料，具備高可擴展性，可即時部署於大規模衛星監測任務。

## A.1 引言

截至 2026 年，地球低軌道已部署超過 10,000 顆活躍人造衛星，並有數萬件碎片共存其中。在此擁擠的軌道環境下，衛星主動機動（Orbital Maneuver）的頻率持續上升——包括規避碰撞、進行星座位置保持、刻意轉換任務軌道等行為——每年在 LEO 空間估計發生數千次。對機動行為的及時偵測是太空態勢感知（Space Situational Awareness, SSA）的核心需求，直接關係到軌道分配規劃、碰撞預警精度以及太空行動透明度。

然而，衛星機動的精確偵測面臨以下核心挑戰：

1. **訊號與噪音混疊**：大氣阻力造成的半長軸自然衰減與低推力機動造成的軌道改變，在 TLE 時間序列中具有高度相似的特徵。
2. **資料稀疏與不均勻**：各衛星的 TLE 更新頻率從每天一次到每天十餘次不等，造成觀測窗口長度不一致。
3. **衛星個體差異**：不同截面積與質量比的衛星對大氣阻力的響應差異懸殊，單一固定閾值策略難以適用全部衛星。

已有研究嘗試利用 TLE 資料偵測衛星機動，例如 Kelecy 等人 [1] 提出基於半長軸突變的基礎偵測框架，以及 Flohrer 等人 [2] 研究的統計閾值方法。然而，上述工作大多針對特定衛星族群，缺乏在萬顆量級衛星上的系統性評估，且對大氣阻力的去偽處理不夠精細。

本文提出的方法在現有差分偵測框架基礎上，設計六項針對特定誤報來源的抑制策略（P1–P6），並在萬顆量級 LEO 衛星的全量數據上進行嚴格的逐步消融實驗與多角度獨立驗證，以量化每項改進的實際貢獻。本文的主要貢獻如下：

- 提出系統性的多級誤報抑制框架（P1–P6），適用於任意規模的公開 TLE 資料。
- 識別並處理「單調衰減激增點」（monotone_with_spike）的特殊案例，避免活躍離軌衛星的機動被誤抑制。
- 設計四窗口補充偵測機制（P4），在不大幅增加誤報的前提下提升長窗口內的機動召回率。
- 透過 Recall@N、跨星系分層、跨時間段穩定性與獨立 MEME Hold-out 事件驗證，從四個獨立角度確認方法的工程可用性。
- 公開完整代碼與實驗結果，支援可重現研究。

## A.2 相關工作

### A.2.1 基於 TLE 的機動偵測

TLE 是美國太空指揮部（USSPACECOM）持續發布的公開衛星軌道資料，包含以 SGP4 模型為基礎的軌道根數。Kelecy 等人 [1] 最早系統地研究了相鄰 TLE 對的半長軸差值作為機動偵測指標的可行性。後續工作由 Holzinger 等人 [3] 擴展至多參數綜合判斷，加入傾角與離心率變化量以減少誤報。

### A.2.2 大氣阻力建模

在 LEO 高度段，大氣阻力是造成軌道衰減的主要非引力攝動力。Picone 等人 [4] 的 NRLMSISE-00 模型提供了高精度的大氣密度估算，但其實時應用受限於計算資源與輸入資料可獲得性。本文採用更輕量的方法：利用 TLE 自身的 B\* 係數作為衛星-環境交互阻力的代理指標，不依賴外部大氣模型。

### A.2.3 J2 攝動修正

地球的扁率（J2 項）會造成軌道昇交點赤經（RAAN）的系統性漂移，速率為 [5]：

$$\dot{\Omega}_{J_2} = -\frac{3}{2} n J_2 \left(\frac{R_E}{p}\right)^2 \cos i$$

其中 $n$ 為平均運動（rad/s），$J_2 = 1.08263 \times 10^{-3}$，$R_E$ 為地球赤道半徑，$p = a(1-e^2)$ 為半通徑，$i$ 為傾角。若不修正此項，RAAN 的自然漂移量可達每天 3°–7°，遠超機動引起的改變，會造成大量假陽性。本文在計算 ΔRAAN 時，預先扣除此 J2 預期漂移量。

> **圖 A-1**：衛星軌道根數幾何關係——包含半長軸 $a$、傾角 $i$、升交點赤經 RAAN（$\Omega$）、近地點幅角 $\omega$ 與衛星位置，均為本文差分計算的輸入量。

![圖 A-1：軌道根數幾何示意圖](fig1_orbital_geometry.png)

## A.3 TLE 差分偵測基礎框架

### A.3.1 軌道根數差分計算

**表 A-1：TLE 主要欄位說明**

| 欄位 | 符號 | 類型 | 物理意義 | 在偵測中的角色 |
|:-----|:----:|:----:|:---------|:-------------|
| 半長軸 | $a$ | 軌道根數 | 軌道整體大小；高度 ≈ $a - R_E$ | 主要偵測信號：突變 Δa 指示機動 |
| 傾角 | $i$ | 軌道根數 | 軌道面與赤道面夾角 | 輔助確認：\|Δi\| > 0.01° 為機動特徵 |
| 離心率 | $e$ | 軌道根數 | 軌道橢圓扁率 | 輔助確認 |
| 升交點赤經 | $\Omega$ | 軌道根數 | 軌道面在慣性空間的方向 | J2 修正後殘差 \|ΔRAAN_res\| > 0.5° |
| 近地點幅角 | $\omega$ | 軌道根數 | 橢圓長軸在軌道面內的方向 | 本研究暫不直接使用 |
| 平近點角 | $M$ | 軌道根數 | 衛星在軌道上的當前位置 | 本研究暫不直接使用 |
| B\* 係數 | $B^*$ | 輔助參數 | 衛星氣動特性；受大氣阻力程度 | P3 條件輸入：高 B\* 放寬閾值 |
| 曆元 | — | 輔助參數 | TLE 生成時刻（年+天數） | 計算 Δt、判斷 TLE 更新頻率 |

定義各根數差值為：

$$\Delta a_k = a_{k+1} - a_k, \quad \Delta i_k = i_{k+1} - i_k, \quad \Delta e_k = e_{k+1} - e_k$$

$$\Delta \Omega_k^{\text{res}} = \left(\Omega_{k+1} - \Omega_k\right) - \dot{\Omega}_{J_2} \cdot \Delta t_k$$

其中 $\Delta t_k = t_{k+1} - t_k$ 為相鄰 TLE 的時間間隔（單位：天）。

### A.3.2 基礎機動旗標判斷

若滿足以下任一條件，則將該 TLE 對標記為「可疑機動」：$|\Delta a_k| > \theta_a$（基礎版本 $\theta_a = 1.0$ km）、$|\Delta i_k| > 0.01°$、$|\Delta \Omega_k^{\text{res}}| > 0.5°$。衛星在觀測窗口內任意一對 TLE 被旗標，即判定為「偵測到機動」（`maneuver_detected = True`）。

### A.3.3 基礎版本的局限性

基礎版本在 14,019 顆衛星的測試集上產生 68 顆假陽性（FP），精確率為 94.8%。分析假陽性案例發現：其中約 60% 來自低軌（< 500 km）衛星的大氣阻力造成的連續軌道衰減，另有約 20% 來自高阻力係數（B\* 值高）衛星在磁暴期間的異常波動。

> **圖 A-2**：（a）大氣阻力造成的單調下降模式（P1 識別為大氣衰減）；（b）軌道機動造成的突然跳升（Day 18 Δa ≈ +5.5 km）；（c）P4 多窗口案例：整體 30 天窗口未觸發，但第二個 7 天子窗口明顯偵測到機動。

![圖 A-2：半長軸時序變化三種典型模式](fig2_timeseries.png)

## A.4 多級改進策略

### A.4.1 P1：單調衰減抑制策略

**問題動機**：大氣阻力造成的軌道衰減具有典型的「單調、連續、累積」特徵。**P1 抑制條件**：連續負 Δa 次數 `neg_streak`≥5 **且** 累積下降量 `total_drop`>5 km **且** 淨 Δa `net_da`<−3 km，同時滿足則抑制機動判定。**激增點救援**：若 `monotone_decay=True` 且正方向 Δa 激增次數 `pos_da_spikes`≥2，取消抑制，避免受控離軌衛星的機動信號被誤刪。**效果**：假陽性由 68 降至 41（−40%）。

### A.4.2 P2：軌道高度自適應閾值

$$\theta_a(\text{alt}) = \begin{cases} 2.0 \text{ km} & \text{alt} < 400 \\ 1.0 \text{ km} & 400 \leq \text{alt} \leq 600 \\ 0.5 \text{ km} & \text{alt} > 600 \end{cases}$$

**效果**：假陽性由 41 降至 27（−34%）。

> **圖 A-3**：（a）高度分層閾值隨高度的分段函數；（b）三個典型高度的 Δa 雜訊散點與對應閾值線。

![圖 A-3：P2 高度自適應閾值示意圖](fig4_p2_threshold.png)

### A.4.3 P3：B\* 輔助條件

若 30 天平均 B\*（`bstar_mean`）> 5×10⁻⁴ **且** 半長軸 < R_E+450 km，則將 P1 的 `neg_streak` 門檻由 5 降至 3。**效果**：假陽性由 27 降至 25（−7%）。

### A.4.4 P4：多窗口補充偵測

對主偵測未觸發之衛星，將觀測窗口切為 4 個不重疊 7 天子窗口逐一重掃，任一子窗口觸發即標記 `multi_window_detected=True`。**效果**：新增 26 顆真實機動衛星，假陽性由 25 回升至 29（+4）。

> **圖 A-4**：偵測流程全覽。左側主路徑為 P1–P3 串行改進；右側分支為 P4 多窗口補充偵測。

![圖 A-4：TLE 差分機動偵測流程（含 P1–P4 改進策略）](fig3_flowchart.png)

### A.4.5 P5：F10.7 太陽通量自適應閾值倍率

僅套用於 alt<600 km，在基礎閾值上疊乘倍率：F10.7>200/150/100 sfu → ×2.0/1.5/1.2。**預設為關閉狀態**（需 `--enable-p5` 旗標），A.7 節之擴充驗證即在啟用 P5/P6 之設定下執行。

### A.4.6 P6：星座感知專屬閾值

以衛星名稱前綴比對，優先於 P2 高度分層閾值：`KUIPER-`→0.3 km；`ISS (`/`PROGRESS`/`SOYUZ MS`/`CREW DRAGON`→5.0 km。

**表 A-2：P1–P6 各改進策略觸發條件彙整**

| 策略 | 觸發條件 | 作用 | FP 變化 |
|:-----|:---------|:-----|:-------:|
| P1 抑制 | neg_streak≥5 且 total_drop>5km 且 net_da<−3km | 排除大氣阻力連續衰減誤報 | 68→41（−40%） |
| P1 救援 | monotone_decay=True 且 pos_da_spikes≥2 | 保留活躍受控離軌衛星 | 避免 4 顆 TP 被誤抑制 |
| P2 | 依高度分 3 層閾值 | 依高度調整閾值 | 41→27（−34%） |
| P3 | bstar_mean>5×10⁻⁴ 且 sma<R_E+450km | 高阻力衛星放寬門檻 | 27→25（−7%） |
| P4 | 主偵測未觸發→4×7 天子窗口重掃 | 補充單週微弱機動 | 25→29（+4，TP+26） |
| P5 | alt<600km；F10.7>100/150/200 sfu | 疊乘閾值 ×1.2/1.5/2.0（預設關閉） | 見 A.7 |
| P6 | 衛星名稱前綴命中 | 星座專屬閾值 | 見 A.7 |

## A.5 實驗設置

**資料集**：Space-Track.org 公開歷史 TLE，觀測窗口 2026-05-01～30（30 天），14,019 顆 LEO 有效衛星（`tle_status=ok`）。**基準真相標籤**：以衛星推進能力類別為代理 Ground Truth——有推進能力（Electric_EP/Chemical/Micro-ColdGas/Hybrid-Other）約 10,200 顆為正例，被動衛星約 3,800 顆為負例。**評估指標**：Precision、Recall、F1（定義見附錄）。

## A.6 結果與分析

**表 A-3：P1–P4 改進策略消融實驗結果**（30 天，14,019 顆）

| 配置 | TP | FP | Precision | Recall | F₁ |
|:-----|---:|---:|----------:|-------:|---:|
| 基準版 | 1,245 | 68 | 94.8% | 12.2% | 21.7% |
| +P1 | 1,148 | 41 | 96.6% | 11.3% | 20.2% |
| +P1+P2 | 1,111 | 27 | 97.6% | 10.9% | 19.6% |
| +P1+P2+P3 | 1,102 | 25 | 97.8% | 10.8% | 19.5% |
| **完整 P1–P4** | **1,128** | **29** | **97.5%** | **11.1%** | **19.9%** |

> **圖 A-5**：（a）各配置精確率/召回率/F1 對比；（b）假陽性數量逐步縮減。

![圖 A-5：P1–P4 消融實驗結果柱狀圖](fig5_ablation.png)

> **圖 A-6**：（a）FP 從 68 到 29 的逐步縮減，P1 貢獻最大（−27 顆）；（b）誤報來源拆解。

![圖 A-6：假陽性縮減路徑與誤報來源分析](fig6_fp_waterfall.png)

**P1 貢獻最大**（−40% FP），被抑制的 97 顆案例集中在 300–500 km 高度、無 Δi/ΔΩ_res 顯著變化，符合純大氣阻力衰減特徵。**P2** 使 FP 再降 34%，主要作用於 350–420 km 高度段。**P3** 效果有限（−7%），與本地 B\* 資料不完整有關。**P4** 為主動取捨：FP+4 換取 TP+26。**召回率詮釋**：11.1% 反映的是「30 天內實際發生可偵測機動的衛星比例」，而非演算法漏報率——多數有引擎衛星在任一個月內並不機動，屬正常運行狀態。

## A.7 擴充驗證：P1–P6 於 54 天全量資料之效能評估

> **方法論提醒**：本節數字與 A.6 節之 P1–P4（30 天）消融實驗**不可直接比較**——觀測窗口長度（30 天 vs 54 天）、衛星規模（14,019 vs 14,090 顆）與策略組合（P1–P4 vs P1–P6）均不同。

### A.7.1 Recall@N：偵測信心排名評估

> **圖 A-7**：（a）Recall@N 隨 N 增加上升，N=1000 時已覆蓋 9.6% 真實機動衛星；（b）Precision@N 在 N≤1000 維持 95–98%。

![圖 A-7：Recall@N / Precision@N 信心排名評估](fig7_recall_at_n.png)

總體指標（54 天全量）：GT 正例 10,186 顆，TP=2,744、FP=156、FN=7,442，**Overall Recall=26.9%、FAR=5.4%**，**Precision@1000=98.2%**。

### A.7.2 跨星系分層效能

> **圖 A-8**：Starlink／Kuiper 的 Recall 27.0%／29.0%、FAR 均 0%；PRC_Recon Recall 66.7% 但 FAR 7.0%；ISS_Complex 因缺乏推進標注，FAR=85.7% 為標籤策略限制，非真實誤報。

![圖 A-8：跨星系分層 Recall / FAR](fig8_constellation.png)

### A.7.3 跨時間段穩定性測試

> **圖 A-9**：Period A（05-01～06-01）vs Period B（06-01～06-23），整體一致率 89.7%（269/300）。兩期 F10.7 均值相近（127.9/127.3 sfu），驗證的是平靜期內穩定性，未涵蓋活躍期對照。

![圖 A-9：跨時間段偵測穩定性測試](fig9_temporal_stability.png)

### A.7.4 獨立 Hold-out 事件驗證（MEME Ground Truth）

以 MEME 精密星曆觀測到的真實 V 形軌道偏移事件（99 個有效事件，2026-06-01～06-23）為獨立標籤，檢驗 P1+P2+P3+P5（不含 P6）能否在事件前後 48 小時內觸發。

> **圖 A-10**：事件級 Recall=57.6%、Precision=53.3%；平均前置時間 24.4 小時；500–2000km 量級事件 Recall 達 85.2% 但同時 FAR 事件比例亦達 81.5%。

![圖 A-10：獨立 Hold-out 事件驗證](fig10_holdout.png)

### A.7.5 EP 連續推力補充偵測器

電推進衛星單次 Δa 常僅 0.05–0.5 km，低於規則法門檻。`ep_slope_detector.py` 改用同高度層同儕比較法：規則偵測器 Recall=27.1%，EP 偵測器單獨 Recall=39.2%，**聯集 Recall 提升至 58.0%**（+30.9pp），顯示兩法互補；代價是無推進衛星 FAR 上升至 10.1%。

### A.7.6 CDM 弱監督嘗試（負向結果誠實揭露）

以 104 筆觀測窗內 CDM（碰撞警報）事件檢驗「TCA 後 7 天 Δa≥2km」作為 CAM 確認條件，結果**無任何一筆滿足**，CDM-confirmed Recall 無法計算（N/A）。誠實記錄此負向結果，留待調整閾值或改用連續型指標。

### A.7.7 方法論差異說明

A.6 節（30 天，P1–P4，Recall=11.1%）與本節（54 天，P1–P6，Recall=26.9%）差距懸殊，主因是觀測窗口延長、衛星規模擴大，而非 P5/P6 本身貢獻。`validate_annotations.py` 的最終指標（Precision=94.5%、Recall=27.7%，含 P4 折算）與 `compute_recall_at_n.py` 的基礎指標（Recall=26.9%，P4 折算前）亦不完全相同，本文採用後者並於圖表註明來源。

## A.8 Layer 1 結論

本文提出基於 TLE 差分分析的多級機動偵測框架，設計六項改進策略（P1–P6）。P1–P4 全量消融實驗將假陽性從 68 降至 29（−57%），精確率從 94.8%提升至 97.5%。擴充至 54 天、14,090 顆衛星並加入 P5–P6 後，取得 Overall Recall=26.9%、FAR=5.4%、Precision@1000=98.2%，並透過獨立 MEME Hold-out 驗證（事件級 Recall=57.6%）與跨時間段穩定性測試（89.7%）進一步確認可靠性。CDM 弱監督雖未產生可用證據，但作為誠實揭露的負向結果，指出後續改進方向。未來工作：（1）調整 CDM 確認閾值；（2）將偵測結果作為 Layer 3 訓練標籤，實現端到端流水線；（3）擴展至 MEO/GEO 機動偵測。

---

# Part B：Layer 3 — LightGBM 機動分類器（論文二全文整合）

> 以下 B.0–B.7 對應 `docs/paper2_lightgbm_classifier_zh.md` 全文，記錄一項標籤洩漏 bug 的發現、修正過程與修正前後的完整效能對比。

## B.0 摘要

本文提出一套基於梯度提升樹（LightGBM）的衛星軌道機動行為二元分類器，以觀測窗口內從公開 TLE 資料萃取的 20 個衛星級聚合特徵為輸入，對 14,023 顆低地球軌道（LEO）衛星進行機動/未機動之自動分類。為防止衛星重複觀測造成的資料洩漏，採用嚴格的衛星層級分層隨機切分策略（訓練/驗證/測試 = 70%/15%/15%）。訓練過程中發現並修正一項**標籤洩漏（label leakage）**問題：初版特徵集中的 `flag_rate`、`n_flagged`、`n_windows_flagged`、`burn_freq_per_day` 四個特徵，其計算邏輯與訓練標籤 `maneuver_detected` 共用同一套規則式旗標，構成 tautological 預測，故予以剔除；同時新增 `da_monotonic_decay` 與 `bstar_f107_normalized` 兩項特徵。修正後，正負例比例由 1:11.5 改善為約 1:3.8，透過平衡類別權重與 F-beta 閾值優化（τ\*=0.5747），LightGBM 於獨立測試集取得精確率 **99.5%**、召回率 **97.5%**、AUC-ROC **0.996**，與隨機森林、XGBoost 表現相近，三者均較修正前大幅提升。修復環境後重新執行的 SHAP 分析顯示 `max_da_km` 躍升為最重要特徵（54.6%）。

## B.1 引言

軌道機動的偵測與分類是 SSA 的兩個互補層面：偵測關注「衛星是否移動」，分類回答「哪些衛星在給定時段有機動行為」。本文核心目標是僅用公開 TLE 資料，訓練可批量分類全球 LEO 衛星的模型；Part A 提供的 TLE 差分偵測結果構成本分類器的訓練標籤。主要貢獻：（1）設計 20 維特徵體系，並發現、修正一項標籤洩漏問題；（2）衛星層級分層切分杜絕資料洩漏；（3）系統比較四種分類方法；（4）SHAP 可解釋性分析識別冗餘特徵與關鍵物理機制。

## B.2 相關工作

機器學習在衛星軌道分析的應用日趨廣泛：Peng 與 Bai [5] 用隨機森林預測 GEO 衛星機動規律；LightGBM [7]（Ke et al. 2017）以 Histogram-based 演算法與 Leaf-wise 生長策略著稱；SHAP [9] 源於 Shapley 值，具局部與全局一致性，是可解釋性的黃金標準工具。

> **圖 B-1**：從 TLE 資料收集到 SHAP 可解釋性分析的完整七步驟訓練流程。

![圖 B-1：LightGBM 衛星機動偵測完整訓練流程](paper2_fig1_ml_pipeline.png)

## B.3 資料集與特徵工程

### B.3.1 資料來源與標籤策略、觀測窗口不一致問題

訓練資料集 `training_samples_plan_b.csv` 目前共 **14,023 顆**衛星。**查證發現**：觀測窗口長度在專案內部文件與程式碼註解中出現 26 天／30 天／54 天三種不一致數字，經查證 `build_training_dataset.py` 現行常數為 **54 天**（2026-05-01～06-23），與 Part A 之擴充驗證同一窗口，本文以此為準並記錄此文件不一致，供後續維護者核對。

訓練標籤已改用擴充版 **P1–P6** 偵測結果：正例 2,900 顆（20.7%）、負例 11,123 顆（79.3%），較初版標籤（1,127 正例／8.04%）比例大幅改善（約 1:3.8），主要反映 P5/P6 與更長觀測窗口捕捉到更多機動衛星。

> **圖 B-2**：不平衡資料挑戰示意；目前實際正例比例已提升至 20.7%。

![圖 B-2：不平衡資料挑戰與衛星層級分層切分](paper2_fig2_class_imbalance.png)

### B.3.2 20 個聚合特徵與一項標籤洩漏修正

**核心發現**：初版 22 特徵中，`flag_rate`、`n_flagged`、`n_windows_flagged`、`burn_freq_per_day` 與訓練標籤共用同一套規則判定邏輯，構成標籤洩漏（tautological predictor，可致 AUC 虛高至 1.0）。程式碼中的明確記錄：

> `# n_flagged / flag_rate / burn_freq_per_day / n_windows_flagged intentionally excluded: same detection algorithm as label_binary (maneuver_detected) → tautological predictor, causes AUC=1.0 leakage.`（`Orbital_Maneuver_V2/dataset.py`）

修正後移除上述四項，新增 `da_monotonic_decay`（純阻力衰減旗標）與 `bstar_f107_normalized`（B\* 對 F10.7 正規化），最終 **20 個特徵**（詳見表 B-1，含現況真實 SHAP 重要度）。

**表 B-1：20 個聚合特徵與 SHAP 重要性（現況真實重跑結果）**

| 特徵名稱 | 物理意義 | SHAP% |
|:---------|:---------|------:|
| `max_da_km` | 最大單步 Δa（km） | **54.6%** |
| `max_di_deg` | 最大單步 Δi（度） | **14.0%** |
| `monotone_decay` | 單調衰減旗標 | **8.1%** |
| `da_std` | Δa 標準差 | **5.3%** |
| `alt_km` | 平均軌道高度 | **5.2%** |
| `bstar_f107_normalized`（新增） | B\* 對 F10.7 正規化值 | **2.5%** |
| `max_tle_gap_h` | 最大 TLE 間隔 | **1.8%** |
| `max_draan_res_deg` | 最大 J2 校正 RAAN 殘差 | **1.5%** |
| `ecc` / `inc_deg` / `dv_net_ms` / `da_abs_mean` | 軌道幾何與動力學 | 1.1–1.4% |
| `total_drop_km` / `n_transitions` / `net_da_km` / `mean_tle_gap_h` | 阻力/動力學/密度特徵 | 0.4–0.7% |
| `n_tle` / `neg_streak` | 資料密度/阻力特徵 | 0.1% |
| `inc_family_enc` / `da_monotonic_decay`（新增） | 類別/阻力特徵 | **0.0%** |

### B.3.3 資料切分策略

按 `norad_id` 分組、正負例獨立分層切分：訓練組 70%（9,816 顆，正例 2,030）、驗證組 15%（2,103 顆，正例 435）、測試組 15%（2,104 顆，正例 435），隨機種子固定 42。

## B.4 分類模型

**LightGBM 配置**：`n_estimators`=1000（早停）、`learning_rate`=0.05、`num_leaves`=15、`min_child_samples`=10、`reg_lambda`=1.0、`class_weight`="balanced"、`early_stopping_rounds`=50、`random_state`=42。現況模型於第 **188** 棵樹收斂（初版 22 特徵模型為 561 棵）——移除洩漏特徵後模型改學習真正物理特徵組合，收斂更快也更穩健。

**閾值優化**：驗證集上搜索 $F_{0.5}$ 最大化閾值，現況模型 $\tau^*=0.5747$（初版為 0.8901；下降與洩漏特徵移除後機率分布變化有關，兩閾值不可直接比較優劣）。

> **圖 B-3**：（a）早停訓練動態示意，現況模型於第 188 棵樹收斂；（b）學習率設定示意（0.05，敏感性掃描為初版結果，尚未於現況模型重新驗證）。

![圖 B-3：LightGBM 早停訓練動態與超參數設定](paper2_fig6_training_curve.png)

## B.5 實驗結果

### B.5.1 多模型比較

**表 B-2：四種分類方法效能比較**（測試集 2,104 顆，seed=42，20 特徵資料集）

| 方法 | Precision | Recall | F₁ | AUC-ROC |
|:-----|----------:|-------:|---:|--------:|
| 規則基準（flag_rate>5%） | 52.4% | 9.9% | 16.6% | 0.959 |
| 隨機森林（thr=0.327） | 98.6% | 97.9% | 98.3% | 0.995 |
| XGBoost（thr=0.201） | 97.9% | 97.2% | 97.6% | 0.997 |
| **LightGBM（本研究，τ=0.575）** | **99.5%** | **97.5%** | **98.5%** | **0.996** |

**關鍵發現**：移除洩漏特徵後，**三種樹模型效能已相當接近**（Precision/Recall 97–99.5%），與初版「LightGBM 大幅領先」的敘事不同——初版懸殊差距（81.6% vs 64–66%）主因是洩漏特徵在不同模型上被利用程度不同，非 LightGBM 演算法結構性優勢。

> **圖 B-4**：（a）真實 ROC 曲線（直接取自 `compare_models.py` 實際執行結果，非合成示意）；（b）Precision/Recall/F1 對比，三種樹模型接近，規則基準明顯落後。

![圖 B-4：四種分類方法 ROC 曲線與 Precision/Recall 對比](paper2_fig5_roc_comparison.png)

### B.5.2 SHAP 特徵重要性分析（修復環境後重新計算）

初版 SHAP 分析因 `numpy 2.5` 與 `numba` 版本衝突長期無法重新執行。本次於獨立虛擬環境安裝相容版本（`numpy<2.3`+`numba 0.66`），重新執行 `analyze_plan_b_model.py`，取得**現況 20 特徵模型的真實 SHAP 結果**。

![圖 B-5：SHAP 特徵重要性排行榜（現況模型，真實結果）](paper2_fig3_shap_importance.png)

![圖 B-5-2：SHAP Beeswarm 圖（現況模型）](paper2_fig3b_shap_beeswarm.png)

`max_da_km` 取代 `flag_rate` 成為主導特徵（54.6%），符合物理直覺——機動最直接的痕跡是半長軸單步突變量。現況僅 `inc_family_enc`、`da_monotonic_decay` 兩特徵貢獻趨近於零，且**不再包含任何洩漏特徵**。

### B.5.3 模型校準與外部驗證

**表 B-3：獨立測試集混淆矩陣（τ=0.5747，現況模型）**

| | 預測：機動 | 預測：未機動 |
|:---|:---:|:---:|
| **真實：機動** | TP=424 | FN=11 |
| **真實：未機動** | FP=2 | TN=1,667 |

![圖 B-6：混淆矩陣熱力圖與各指標計算](paper2_fig4_confusion_matrix.png)

AUC-ROC=0.996（獨立測試集）／0.998（5-fold OOF）。**外部驗證**（Plan A，283 顆 Starlink MEME Ground Truth 衛星，Plan B 涵蓋 252 顆）：**Precision=100.0%、Recall=39.7%、F1=56.8%**——與測試集高 Recall（97.5%）相比明顯偏低，這是**誠實且重要的發現**：模型遷移到獨立生成的 MEME Ground Truth 時僅能找回四成真實機動，是留待改進的泛化落差，不宜僅憑測試集數字宣稱已「解決」機動分類問題。

## B.6 討論

**精確率優先的工程考量**：修正洩漏特徵後，三種樹模型 Precision/Recall 已相當接近，精確率優先設計的邊際影響力不若初版顯著，但仍具方法論意義。**標籤洩漏的發現比特徵重要性更根本**：初版將 `flag_rate` 的高 SHAP 貢獻詮釋為「有效機動密度指標」，但這建立在未被發現的方法論缺陷上——說明**單純依賴 SHAP 無法自動偵測標籤洩漏**，「異常重要」的特徵反而更需追溯計算邏輯是否獨立於標籤生成過程。**觀測窗口文件不一致**（26/30/54 天）雖不影響模型訓練本身，但會誤導後續維護者，應列為文件維護優先項目。**標籤品質局限性**：訓練標籤由 Part A 之 P1–P6 規則流水線自動生成而非人工金標準，B.5.3 節外部驗證具體量化了此標籤依賴造成的泛化落差。

## B.7 Layer 3 結論

本文提出基於 LightGBM 的 LEO 衛星機動分類器，並在研究過程中發現、修正一項標籤洩漏問題。修正後於獨立測試集取得 Precision 99.5%、Recall 97.5%、AUC-ROC 0.996，與 RF/XGBoost 表現相近，證實初版懸殊差距主因是洩漏特徵而非演算法優勢。修復環境後的真實 SHAP 分析顯示 `max_da_km` 取代 `flag_rate` 成為主導特徵。外部驗證揭露的泛化落差（Recall 39.7%）是比初版更誠實的效能圖像。方法論教訓：特徵重要性分析無法自動偵測標籤洩漏。未來工作：（1）引入 MEME 等獨立標籤來源縮小泛化落差；（2）統一觀測窗口文件說明；（3）擴展至多分類任務（電推進/化學推進/微推力）。

---

# Part C：`maneuver_app.py` — Streamlit 儀表板進度

> 本部分內容取自 `docs/interim_progress_report_20260720.md`，並新增一項今日完成、以真實資料驗證的案例（C.4）。**重要更新**：6/24 版全計畫報告將「Streamlit 視覺化儀表板」列在「主要尚待事項」，但截至本報告撰寫時，`maneuver_app.py` 已是涵蓋 10+ 分析頁籤、三種偵測管線、SSA-RAG 問答整合的完整儀表板，此項目實際進度顯著領先 6/24 報告的描述，建議正式期中報告更新此條目狀態。

## C.1 契約需求 vs. `maneuver_app.py` 現況對照

| 項目 | 狀態 | 證據 |
|---|:---:|---|
| Layer 1 閾值基準層（TLE-SMA 差分） | ✅ | `detect_maneuvers_refined_adaptive()`：5 個高度帶自適應 mult/window/rate_mult/rate_floor |
| Layer 1（GEO 專屬） | ✅ | `render_geo_page()`：EW/NS/重定位/廢棄/TLE 空白五類事件 |
| 軌道分類（LEO/MEO/GEO/GEO+/HEO） | ✅ | `classify_orbit()`：四層分類，含信心分數與判斷理由 |
| Layer 3 XGBoost / LightGBM 整合 | ✅ | `load_ml_models()`、`compute_lgbm_plan_b_features()`，含本次新增之 `da_monotonic_decay`、`max_tle_gap_h` 守門邏輯 |
| SSA-RAG 知識庫問答整合 | ✅ | `render_rag_auto_explain()`，各分析頁自動將偵測結果轉自然語言送查 |
| DuckDB 查詢 | ✅ | `load_data()` 查詢 `space_db.duckdb`/`tle_table` |
| Layer 2 統計偵測層 | ❌ | 契約要求之 CUSUM/BOCPD/SSA 均未實作；現有 Lomb-Scargle 用於長軸旋轉週期估算，用途不同 |

## C.2 近期關鍵改進

以下改進直接呼應契約「專案背景」痛點第 3 點（偵測靈敏度與誤報率難以兼顧），並已逐一以真實 NORAD 資料驗證：

1. **LEO/MEO／GEO 軌域自動判斷路由**：偵測到 GEO/GEO+ 軌域時自動切換渲染 GEO 視圖，不再需要使用者手動判斷分析模式（驗證：NORAD 36032 正確切換、NORAD 66666 正確維持 LEO/MEO 視圖）。
2. **ML 模型偵測頁軌域守門警告**：偵測到 GEO/GEO+ 衛星時顯示「此模型僅在 LEO 衛星（193–985 km）訓練，結果僅供參考」，避免模型套用於訓練分布外資料（根因：訓練集全部落在 193–985 km；驗證：NORAD 49336，a≈42,164 km，正確觸發警告）。
3. **半長軸／高度並列顯示格式標準化**：所有 LEO/MEO 頁面圖表與表格統一為「SMA(高度)」格式（例如 `6,942.2km(高度571.2km)`）。
4. **LightGBM 機動判定新增 TLE 資料缺口守門**（詳見 C.4 案例）。

## C.3 已知落差與風險

| 項目 | 現況 | 風險/建議 |
|---|---|---|
| Layer 2 未整合進儀表板 | `anomaly_detector.py`、`ep_slope_detector.py` 已有初步方法但使用者無法在介面上查看 | 優先評估接入 Streamlit，而非從零開發 CUSUM/BOCPD/SSA |
| 星系級異常分析 | RAAN 分面統計存在，三項契約指定指標未實作 | 依排程屬第四個月，尚未逾期 |
| 資料清洗 quality_flag | 未實作 | 現以 P1 規則局部替代 |

## C.4 案例研究：NORAD 44349 TLE 資料缺口守門

**問題發現**：NORAD 44349 半長軸在觀測期間平緩、連續下降（典型大氣阻力衰減），但 ML 模型仍兩度判定高機率「機動」（p_maneuver≈0.99）。

**根因分析**：比對觸發前後窗口的完整特徵向量，關鍵差異並非半長軸跳變，而是 `max_tle_gap_h`（視窗內最長 TLE 追蹤間隔）從正常的 24 小時暴增至 134–163 小時；長間隔導致 RAAN 殘差的 J2 長期進動率線性外推誤差被放大，使單筆轉移的 `max_draan_res_deg` 假性超過判定閾值。

**修正方式**：新增 `TLE_GAP_SUPPRESS_H=48.0` 小時門檻，視窗內最長 TLE 缺口超過門檻時，不論原始機率多高，直接壓制判定為非機動；同時套用於單次推論與滾動趨勢圖，並以橘色標記區隔「原本會誤報但已被壓制」的視窗。

**驗證結果**：如下圖所示，兩段橘色區間精確對應 TLE 缺口暴增區間，同期半長軸持續平緩下降，確認為誤報而非真實機動；擴大到完整資料期間測試，298 個滾動視窗中 50 個因資料缺口被正確壓制、20 個維持為真實高機率警示。

![圖 C-1：NORAD 44349 TLE 資料缺口守門案例](fig11_gap_suppression_case.png)

> **圖 C-1**：(a) 機動機率時序，橘色標記/區塊為資料缺口守門壓制的視窗；(b) 半長軸走勢（持續平緩下降）與視窗內最長 TLE 缺口（右軸），兩者高度相關，確認假警報由追蹤缺口而非真實機動驅動。

此案例已寫入 `maneuver_app.md`（軟體功能說明文件），作為未來維護者理解此守門邏輯的具體參考範例。

---

# Part D：全計畫層級之已知落差、風險與交付規劃

> 本部分彙整 `docs/CCITOrbitalManeuver_Midterm_Prelease_Report_20260624.doc` 中，未被 Part A/B/C 涵蓋之全計畫層級資訊。

## D.1 契約交付物現況

| 交付物 | 截止日期 | 現況 |
|---|---|---|
| 期中進度報告電子檔 | 2026-07-31 | 本文件 |
| 期末進度報告電子檔 | 2026-11-30 | 待撰寫 |
| 完整原始程式碼（訓練/測試資料集、AI 模型、訓練參數） | 2026-11-30 | 15+ 腳本已完成，需整合打包 |
| 技術說明文件（演算法流程、測試基準、驗證結果、參考資料） | 2026-11-30 | Part A/B 兩篇技術論文已具雛形，待擴充 |
| 教育訓練文件 | 2026-11-30 | 待撰寫 |

## D.2 風險與因應措施（沿用內部工作計畫書，2026-05-08 版）

| 風險 | 可能性 | 影響 | 因應措施 |
|---|:---:|:---:|---|
| Starlink MEME API 停止服務 | 低 | 高 | 合成資料補充；`residuals_*.csv` 已存 284 顆歷史資料 |
| 標記資料仍不足 | 中 | 中 | 強化合成資料生成；Transfer Learning |
| TLE 精度限制微型機動偵測 | 高 | 中 | MEME RTN 管線已實作（偵測下限 0.02km）；調整 TLE 管線目標下限至 200m |
| 高度自適應閾值於 MEO/GEO 過於保守 | 中 | 低 | `maneuver_app.py` 已加入 GEO 軌域自動路由（見 Part C） |
| 計算資源不足（Transformer） | 中 | 低 | 使用輕量化架構；雲端訓練 |

## D.3 整體完成度評估

6/24 版報告估計整體完成度約 55–60%，距期末（2026-11-30）尚有約 5 個月。本次查證確認 Part A（Layer 1）與 Part B（Layer 3 傳統 ML）之完成度與可靠度均高於或至少不低於 6/24 版的描述，且 `maneuver_app.py`（原列為「主要尚待事項」）實際已大幅完成。**建議正式期中報告（7/31 前）以本文件之 Part A/B/C 內容更新完成度估計**，但具體百分比調整建議由計畫主持人依 Layer 2/深度學習等尚未開始項目的相對權重綜合裁定，本報告不逕行給出新數字，僅提供更新後的事實基礎。

---

## 結論

本期中進度報告整合了 Layer 1（TLE 差分機動偵測，含 P1–P6 與 54 天全量擴充驗證）、Layer 3（LightGBM 機動分類器，含一項標籤洩漏 bug 的發現與修正）與 `maneuver_app.py`（Streamlit 儀表板，含 TLE 資料缺口守門案例）三個技術面向的最新進度，並與既有的全計畫層級期中預擬版報告（2026-06-24）進行交叉核對，修正其中一項認知落差（Streamlit 儀表板實際進度顯著領先原描述）。Layer 2（統計偵測層：CUSUM/BOCPD/SSA）維持未實作狀態，如實揭露、不予淡化，是本階段最主要的落差項目，建議列為下一階段最優先工作。所有量化指標均附具體檔案路徑或函式名稱作為證據，圖表以真實計算/執行結果為主，示意圖表均已明確標註。

---

## 附錄 A：Layer 1 參考文獻

[1] T. M. Kelecy and M. Jah, "Detection and Orbit Determination of a Satellite Executing Low Thrust Maneuvers," *Acta Astronautica*, vol. 66, no. 5–6, pp. 798–809, 2010.
[2] T. Flohrer, H. Krag, and H. Klinkrad, "Assessment and Categorization of TLE Orbit Errors for the US SSN Catalogue," AMOS Conference, 2008.
[3] M. J. Holzinger, D. J. Scheeres, and K. T. Alfriend, "Object Correlation, Maneuver Detection, and Characterization Using Control Distance Metrics," *JGCD*, vol. 35, no. 4, pp. 1312–1325, 2012.
[4] J. M. Picone et al., "NRLMSISE-00 Empirical Model of the Atmosphere," *JGR: Space Physics*, vol. 107, no. A12, 2002.
[5] D. A. Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. Microcosm Press, 2013.
[6] F. R. Hoots and R. L. Roehrich, "Models for Propagation of NORAD Element Sets," Spacetrack Report No. 3, 1980.
[7] D. A. Vallado et al., "Revisiting Spacetrack Report #3," AIAA 2006-6753, 2006.
[8] 18th Space Control Squadron, "Space-Track.org," U.S. Space Command, 2026.
[9] D. L. Oltrogge and S. Alfano, "The Technical Challenges of SSA," *J. Space Safety Eng.*, vol. 6, no. 3, pp. 164–172, 2019.
[10] H. G. Lewis, "Understanding Long-Term Orbital Debris Evolution," *Phil. Trans. R. Soc. A*, vol. 371, 2013.

## 附錄 B：Layer 3 參考文獻

[11] A. Wittig et al., "Long-Term Evolution of Disposed GTO Orbits Under Lunisolar Perturbations," *JGCD*, vol. 38, no. 5, pp. 937–950, 2015.
[12] H. Peng and X. Bai, "Improving Orbit Prediction Accuracy through Supervised Machine Learning," *Adv. Space Res.*, vol. 61, no. 10, pp. 2628–2646, 2018.
[13] T. J. Muelhaupt et al., "Space Debris Mitigation in the New Space Era," *J. Space Safety Eng.*, vol. 6, no. 3, pp. 176–180, 2019.
[14] G. Ke et al., "LightGBM: A Highly Efficient Gradient Boosting Decision Tree," NeurIPS 30, 2017.
[15] T. Chen and C. Guestrin, "XGBoost: A Scalable Tree Boosting System," KDD 2016, pp. 785–794.
[16] S. M. Lundberg and S.-I. Lee, "A Unified Approach to Interpreting Model Predictions," NeurIPS 30, 2017.
[17] L. Breiman, "Random Forests," *Machine Learning*, vol. 45, no. 1, pp. 5–32, 2001.

## 附錄 C：關鍵程式檔案清單

| 模組 / 檔案 | 說明 |
|---|---|
| `leo_annotator/validate_annotations.py` | Layer 1 規則偵測器（P1–P6） |
| `leo_annotator/compute_recall_at_n.py` | Recall@N 信心排名評估、CDM 弱監督查核 |
| `leo_annotator/temporal_stability_test.py` | 跨時間段穩定性測試 |
| `leo_annotator/build_holdout_testset.py` | 獨立 MEME Hold-out 事件驗證集建構 |
| `leo_annotator/analyze_far_vs_scale.py` | FAR vs 機動規模、B\* 分層 FAR 分析 |
| `leo_annotator/ep_slope_detector.py` | EP 連續推力補充偵測器 |
| `leo_annotator/anomaly_detector.py` | 統計異常偵測（3σ MAD，含非合作目標） |
| `Orbital_Maneuver_V2/train.py` | LightGBM Plan B 訓練腳本 |
| `Orbital_Maneuver_V2/dataset.py` | 特徵欄位定義（含洩漏特徵排除註記） |
| `Orbital_Maneuver_V2/compare_models.py` | 多模型（規則/RF/XGB/LightGBM）比較 |
| `Orbital_Maneuver_V2/analyze_plan_b_model.py` | 特徵重要度、外部驗證、SHAP 分析 |
| `Orbital_Maneuver_V2/models_plan_b/` | 現況模型檔、閾值、特徵清單 |
| `synthetic_tle/` | 軌道機動虛擬資料集生成器 |
| `maneuver_app.py` | Streamlit 視覺化儀表板 |
| `space_db.duckdb` | DuckDB 結構化資料庫 |

---

*本報告之完整代碼與數據已公開於 GitHub：https://github.com/RhynoW/Sat_TraingDataExtension*
