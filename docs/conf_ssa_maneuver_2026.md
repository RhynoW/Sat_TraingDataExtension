# 低軌巨型星系軌道機動偵測之三層架構:方法與驗證

## A Three-Layer Architecture for Orbital Maneuver Detection of LEO Mega-Constellations: Methodology and Validation

**作者**：（作者姓名）　｜　**單位**：社團法人中華民國國防科技學術研究學會
**計畫**：TASA-S-1150268（行政法人國家太空中心委辦）

---

### Abstract

The rapid expansion of low-Earth-orbit (LEO) mega-constellations has made autonomous, data-driven maneuver detection a core capability for space situational awareness (SSA). This paper presents a three-layer detection architecture that operates on publicly available Two-Line Elements (TLE) and SpaceX Mean-of-Ephemeris (MEME) precision ephemerides. Layer 1 performs interpretable rule-based screening (P1–P6); Layer 2 applies four complementary statistical change-point detectors (CUSUM, BOCPD, SSA, 3σ-MAD) under a per-satellite σ-normalized signal-to-noise (SNR) formulation; Layer 3 fuses the physical and statistical channels through a gradient-boosting scorer trained with leakage-free GroupKFold out-of-fold (OOF) prediction. A physics-based router (NRLMSIS drag residual and re-entry gating) handles out-of-domain targets. Crucially, maneuver truth is derived entirely from MEME while all detection features come solely from TLE—two independent measurement systems—so performance reflects TLE-detectability of MEME-confirmed maneuvers rather than circular self-detection. On a common arena of 284 Starlink satellites over a 67-day full-constellation window (2026-05-02 to 07-08; 19,066 satellite-days; 597 positive / 6,636 negative episode units, 8.3% positive rate), the fused Layer 3 attains a unit-level ROC-AUC of 0.985 and, under this imbalance, an average precision (PR-AUC) of 0.952—indicating discrimination is not an AUC artifact—with large-maneuver recall of 0.970 at FPR ≤ 0.05, substantially exceeding the best single statistical channel (CUSUM, AUC 0.901) and all simple baselines. Generalization is verified under three protocols: four-axis GroupKFold OOF stability, a temporal out-of-time split (AUC 0.94), and an intra-constellation unseen-satellite hold-out of 56 never-trained satellites (AUC 0.980, AP 0.947, large recall 81/81, Wilson 95% lower bound 0.955). Quantitative claims are scoped to the Starlink domain; cross-domain transfer is bounded by an external ILRS/IDS benchmark and a physics router (out-of-domain window FPR 0.032). A real 67-day full-constellation deployment yields an operationally tractable load of 13.3 alerts/day and ~1.1 analyst-hours/day. We further quantify the physical detection limit: sub-2σ small maneuvers are unrecoverable from radar-tracked TLE, motivating a precision-ephemeris path.

**Keywords**: space situational awareness; orbital maneuver detection; two-line elements; statistical change-point detection; gradient boosting; generalization; LEO mega-constellation

---

## 一、緒論

低軌（LEO）巨型通訊星系近年以每週多批的速度部署，在軌衛星數已達數萬量級，軌道擁擠與碰撞風險同步升高。在此背景下，能否**自主、以資料驅動地偵測衛星軌道機動**（station-keeping、批量部署、規避、任務調整等），成為太空情勢感知（SSA）的核心能力之一。由於營運方之機動計畫多不完整公開，偵測必須建立在**公開可得的軌道資料**（TLE、公開精密星曆）與**可驗證的真值**之上。

自主機動偵測面臨三項根本挑戰：(1) **真值稀缺且異質**——不同來源的可信度差異極大；(2) **訊雜比受限**——雷達追蹤之 TLE 半長軸雜訊可達數十公尺，小型機動之訊號被雜訊淹沒；(3) **泛化風險**——監督式模型易「只認得訓練過的衛星或時段」。本文提出之三層偵測架構針對上述挑戰，於方法設計與實驗驗證兩面同時處理。

本文貢獻如下：

1. 提出**三層互補架構**（規則→統計變點→梯度提升融合）並輔以**物理路由**處理域外目標，兼顧可解釋性與偵測力；
2. 建立**真值可信度分級**協定，所有效能宣稱僅採嚴格真值（MEME／ILRS-IDS）；
3. 以**三種嚴格泛化協定**（GroupKFold OOF、時間外推、未見衛星 hold-out）驗證融合層之外推能力（星系內未見衛星 hold-out 達 AUC 0.980、AP 0.947），並誠實界定跨異質域範圍（外部 ILRS 標竿＋物理路由）；
4. 以**真實全星系 67 天部署**量化營運負荷，證明系統可落地；
5. 量化**SNR 物理偵測下限**，誠實界定純 TLE 對小型機動之能力邊界。

## 二、相關研究

TLE 由 SGP4/SDP4 攝動模型產生，其半長軸精度受大氣阻力建模與擬合誤差影響（Hoots & Roehrich, 1980；Vallado et al., 2006）。以 TLE 偵測機動的既有作法多以單一統計量（如 |Δa| 門檻、多項式／LOWESS 曲線擬合）為主（Lemmens & Krag, 2014；Patera, 2008；Kelecy et al., 2007）。變點偵測方面，CUSUM（Page, 1954）、貝氏線上變點（BOCPD；Adams & MacKay, 2007）、奇異譜分析（SSA；Golyandina et al., 2001）與穩健 MAD（Rousseeuw & Croux, 1993）各有所長但單獨使用時召回／誤報難以兼顧。大氣密度以 NRLMSISE-00（Picone et al., 2002）與 NRLMSIS 2.0（Emmert et al., 2021）建模，可作為阻力殘差通道。

本文與既有工作的差異在於：不以單一偵測器為終點，而是以**融合層**整合物理與多統計通道，並在**方法論上嚴格處理真值分級與泛化驗證**——後者在既有機動偵測文獻中少有系統性報告。

## 三、資料與真值

**資料來源。** 情境一（單衛星）以 Space-Track TLE 為特徵來源，存入 DuckDB `raw_tle_archive`；情境二（星系級）以 SpaceX 公開 MEME 精密星曆（公尺級）為真值與交叉驗證來源。外部第二真值集取自國際雷射測距服務（ILRS）／國際 DORIS 服務（IDS）公開之營運方點火日誌（含 ΔV 三分量與秒級時刻）。

**真值可信度分級。** 為避免以品質不一之標籤混入效能宣稱，本文採三級真值（表 1）；**所有 AUC／召回／FPR 之達標宣稱一律建立於嚴格真值之上**，代理真值僅用於描述廣掃覆蓋規模。

**表 1　真值可信度分級**

| 真值類別 | 來源 | 可信度 | 角色 |
|---|---|---|---|
| 嚴格真值 | MEME 精密星曆、ILRS／IDS 點火日誌 | 高 | 所有效能宣稱之唯一依據 |
| 代理真值 | 推進能力（有無推進器） | 低（分母高估） | 僅描述覆蓋規模 |
| 合成真值 | 已知 Δa 注入真實序列 | 受控 | 量化偵測下限 |

**真值定義與獨立性（關鍵，杜絕循環質疑）。** MEME 與 TLE 為**兩套獨立量測系統**：MEME 係 SpaceX 以其營運定軌產出之公尺級精密星曆，TLE 則由地面雷達追蹤擬合而得。機動真值之產生**完全在 MEME 上進行**——對 MEME 半長軸序列偵測持續性軌域改變（以 48 小時合併為 episode 事件），與 TLE 無關；而所有偵測特徵**僅取自 TLE**。負例（安靜窗）亦由 MEME 之「無機動」期間界定、並與正例**等寬**（約 48 小時），非由任何 TLE 偵測器輸出定義，故無「窗界定洩漏」，亦避免以易分辨之寬窄不一負例灌高 AUC。兩系統雖皆經半長軸反映同一物理機動（此正為可偵測性之前提），但**標註來源（MEME）與特徵來源（TLE）為不同儀器**，故高績效反映的是「MEME 確認之機動可由獨立之 TLE 偵得」，而非同源自我偵測之循環。

**評估資料集。** 本文主實驗以全 **284 顆 Starlink** 於 **67 天全星系密集覆蓋窗**（2026-05-02～07-08、19,066 星日）為範圍，構成 **597 個正 unit／6,636 個負 unit**（正例率 8.3%）。此「unit（事件單元）級」對齊乃關鍵：MEME 為 8 小時網格、TLE 為不規則 epoch，**點級對齊會使 AUC 塌至約 0.55**，unit 級方能得到乾淨評估。

## 四、方法

系統採三層串接（圖 1）：L1 廣掃候選（高召回、可解釋），L2 於候選附近以統計量確認變點，L3 融合多通道輸出可排序機率並於固定誤報預算下產生最終告警；物理路由對域外／再入目標接管。

![圖 1　三層偵測架構與物理路由之資料流。](fig3_flowchart.png)

### 4.1 Layer 1：規則廣掃（P1–P6）

依軌道六根數將目標分類（LEO／MEO／GEO、傾角殼層），對相鄰 TLE 之元素轉移套用六條物理規則 P1–P6（半長軸階躍、傾角變化、離心率跳變等），產生逐 epoch 之合併旗標。L1 追求高召回與完全可稽核，靈敏度受人工設計上限限制。

### 4.2 Layer 2：統計變點與 σ 正規化 SNR

L2 對半長軸序列 $a(t)$ 去趨勢後，計算四通道逐點分數：CUSUM、BOCPD、SSA、3σ-MAD。核心設計為**每衛星自身雜訊 σ 之正規化**，即以訊雜比而非絕對量判定機動：

$$\mathrm{SNR}(t) = \frac{|\Delta a(t)|}{\sigma_a}, \qquad \sigma_a = 1.4826 \cdot \mathrm{median}\!\left(\left| \Delta a - \mathrm{median}(\Delta a)\right|\right) \tag{1}$$

其中 $\sigma_a$ 為半長軸一階差之穩健 MAD 尺度。CUSUM 之遞迴累積量為

$$S_t = \max\!\left(0,\; S_{t-1} + (x_t - \mu) - k\right) \tag{2}$$

$x_t$ 為標準化觀測、$k$ 為鬆弛參數。σ 正規化使同一門檻可跨不同追蹤品質之衛星一致套用（見第六節雜訊底分析）。

### 4.3 Layer 3：梯度提升融合

L3 將五通道（cusum／bocpd／ssa／mad3sig／NRLMSIS drag）於每個 unit 內聚合為 15 維特徵（各通道之 max／mean／p90），以 HistGradientBoosting 分類器融合：

$$p = f_{\mathrm{HGB}}(\mathbf{x}), \qquad \text{alert if } p \geq \tau,\; \tau = \tau(\mathrm{FPR} \leq 0.05) \tag{3}$$

為杜絕洩漏，訓練採 **GroupKFold（同一衛星不跨 train／test）之 OOF 預測**；操作門檻 $\tau$ 以「誤報率下限（FPR floor）」法在負樣本上求取，保證嚴格控制誤報預算。特徵刻意去除 unit 長度以避免長度洩漏，負窗與正 unit 等寬以避免 AUC 虛高。

### 4.4 物理路由

對非 Starlink 域或再入目標，L3 之量化召回不成立。路由層以 NRLMSIS 阻力殘差 $z_{\mathrm{drag}}$ 與再入守門判定：域外目標改走非監督之 Model 2（IsolationForest＋物理殘差），不作量化召回宣稱，僅提供一致性與 FPR 驗證。

## 五、實驗設計

**評估單元與指標。** 以 unit 級為主評估單元。主指標為 **ROC-AUC**（整體判別力）與 **FPR ≤ 0.05 操作點下之召回率**（可接受誤報預算內之偵測力）。因正例率僅 8.3%（類別不平衡），**併報平均精確率 AP（PR-AUC）**，以檢核 AUC 於不平衡下之潛在樂觀偏差（Saito & Rehmsmeier, 2015）。並依機動量級分層報告 large／medium／small 召回；嚴重度定義：small 1–5 km、medium 5–10 km、large ≥ 10 km（半長軸變化量）。

**泛化協定。** 為區辨「真判別力」與「過擬合」，採三種漸次嚴格之協定：(a) **GroupKFold(5) OOF**——同一衛星不跨折，沿族群／高度／時間／品質四軸切片檢驗穩定度；(b) **out-of-time**——依 unit 時間中位數，前 60% 訓練、後 40% 從未見時段盲測；(c) **unseen-satellite hold-out**——隨機保留 56 顆衛星整組、完全不參與訓練，門檻由訓練集設定後套用（可部署情境）。

**對照組。** 設三類簡單基線（純 |Δa| 絕對門檻、僅阻力模型、單特徵 σ 正規化 |Δa|）與隨機對照，並以模型消融（HistGB／LightGBM／Logistic）分離「框架貢獻」與「演算法貢獻」。

## 六、結果與分析

### 6.1 同一擂台三層比較

於相同測試集、相同真值、相同評估單元下比較三層與基線（表 2）。融合層 L3 之 AUC 0.985 明顯高於最佳單一統計通道（CUSUM 0.901）與所有基線；隨機對照近 0.05，證明擂台具鑑別力。

**表 2　同一擂台之逐層與基線比較（284 星／67 天／FPR≤0.05）**

| 方法 | ROC-AUC | 精確率 | large 召回 | 總召回 |
|---|--:|--:|--:|--:|
| L1 規則 P1–P6 | — | 0.296 | 0.333 | 0.251 |
| L2 cusum（最佳單通道） | 0.901 | 0.472 | 0.469 | 0.496 |
| L2 mad3sig | 0.859 | 0.302 | 0.333 | 0.240 |
| L2 ssa | 0.819 | 0.261 | 0.279 | 0.196 |
| L2 bocpd | 0.725 | 0.065 | 0.047 | 0.039 |
| 基線 純 \|Δa\| 門檻 | 0.870 | 0.323 | 0.353 | 0.265 |
| 基線 σ 正規化 \|Δa\| | 0.878 | 0.337 | 0.365 | 0.281 |
| **L3 融合（本系統）** | **0.985** | **0.631** | **0.970** | **0.946** |
| naive 隨機（對照） | — | 0.084 | 0.053 | 0.051 |

**不平衡穩健性。** 於 8.3% 正例率下，L3 之 **AP（PR-AUC）達 0.952**，與 ROC-AUC 0.985 相當——顯示判別力並非 AUC 於不平衡下之樂觀假象，PR 空間中亦成立。

**三層增量分析。** L3 相對「L1∪L2」淨補漏 202 個真機動（補漏 205、反向損失 3），並淨除誤 333 個假警報（除誤 592、引入 259），證融合層對前兩層具實質增量而非重複其輸出。

### 6.2 消融分析

**表 3　模型消融（固定 episode-native 資料＋15 特徵＋GroupKFold）**

| 分類器 | ROC-AUC | large 召回@FPR≤.05 | 總召回 |
|---|--:|--:|--:|
| HistGB（本系統） | 0.985 | 0.970 | 0.946 |
| LightGBM | 0.985 | 0.970 | 0.948 |
| Logistic（線性基線） | 0.975 | 0.953 | 0.933 |

LightGBM ≈ HistGB，顯示 0.97 之增益來自「episode-native 資料＋聚合特徵框架」而非特定演算法；即便線性分類器亦達 0.975，進一步佐證框架之主導性。

![圖 2　三層方法之 ROC 比較。](fig8_roc_comparison.png)

### 6.3 泛化驗證

三種協定結果如表 4（併報 AP）。四軸 OOF 切片之 AUC 全距僅 0.044（0.945–0.989），無單一切片撐盤全域；時間外推守住 FPR 預算；未見衛星 hold-out（56 顆整組留出）達 AUC 0.980、AP 0.947、large 召回 1.000。

**表 4　泛化協定結果**

| 協定 | ROC-AUC | AP | large 召回 | FPR | 測試 unit |
|---|--:|--:|--:|--:|--:|
| GroupKFold OOF（全域） | 0.985 | 0.952 | 0.970 | 0.050 | 7,233 |
| out-of-time（後 40% 盲測） | 0.94 | n/a¹ | 0.800 | 0.044 | 2,893 |
| **unseen-satellite hold-out（星系內）** | **0.980** | **0.947** | **1.000（81/81）** | 0.070 | 1,457 |

¹ out-of-time 採獨立訓練之盲測模型（前 60% 訓、後 40% 測），非全域 OOF 分數，故不併列同尺度 AP；其 large 召回受後段尾部 large 事件樣本數少影響，惟仍守住 FPR≤0.05（跨重跑 large 召回／recall／測試數完全一致，AUC 僅 ±0.005 多執行緒抖動）。

**hold-out 效力範圍之誠實界定。** 上述未見衛星 hold-out 為**星系內（intra-constellation）泛化**：Starlink 各星之衛星匯流排、軌域殼層與維持節律高度同質，故此測驗證的是「模型未記憶特定衛星」，**而非跨異質域轉移**。其 large 召回 1.000 係 **81/81**（56 顆 hold-out 星內之 81 個 large 事件全數偵得，Wilson 95% 下界 0.955），為可信之高值而非小樣本僥倖，惟推論僅及 Starlink 域。

**跨域證據與範圍界定。** L3 之量化召回宣稱**僅限 Starlink LEO 域**。真正之跨異質域證據來自外部 **ILRS／IDS 標竿（14 顆非 Starlink 精密測高衛星）**：於該獨立真值上，σ 正規化取向之現代 6 星平均 F1 0.64、優於曲線擬合基準法 0.52（BOCPD 為最強單一偵測器）；惟該比較採曲線擬合協定、非本文之 L3 融合，僅佐證**取向可轉移**。域外目標於部署中由物理路由接管，其非 Starlink 域之**逐窗誤報率**經 ILRS 認證安靜期實測為 **0.032**（14 星／1,138 安靜窗），支持路由之域外守門有效。

### 6.4 全星系部署營運

以全 284 顆於 67 天真實窗（19,066 星日）之逐 unit 預測直接統計營運負荷（表 5，非線性投影）。系統把 L1 廣掃候選逐級收斂為每日 13.3 則 L3 告警，人工每日約 1.1 人時即可值守全星座；高信心（p ≥ 0.9）自動升級佔 57%，使值勤員優先審少量關鍵告警。

**表 5　284 星 × 67 天全量部署之值勤負荷（真實窗實測）**

| 項目 | 值 |
|---|---|
| L3 最終告警 | 894 則（TP 564、FP 330）；每日 13.3 則 |
| 精確率 | 0.631 |
| 誤警率 FAR | 17.4 / 1,000 星日（＝0.0174／星日） |
| 人工覆核工時 | 74.5 人時／67 天 ＝ 每日 1.1 人時 |
| 高信心自動升級 | 57%（515／896） |
| 平均告警延遲 | 中位 0.1–0.5 h（遠優於 24 h） |

### 6.5 雜訊底與 SNR 偵測下限

以 13 顆 DORIS 精密測高衛星於營運方認證安靜期實測 TLE 半長軸雜訊，σ_diff 中位僅 **0.2 m**，較 Starlink 級雷達追蹤之常見假設 50 m 小約兩個數量級（圖 3）。此驗證 σ 正規化之必要：同一絕對機動在不同追蹤品質衛星上之可偵測性差異極大。**須界定域別**：0.2 m 係 DORIS 精密域之雜訊底，用以（i）示範 σ 正規化之必要、（ii）說明精密星曆可將小型機動之偵測天花板大幅提高；**Starlink 偵測域本身之雜訊底為數十公尺量級**，故 Starlink 之 small 機動下限由其自身 σ 決定、而非 0.2 m——此正是本文主張擴展精密星曆輸入之依據（第八節）。進一步以漸進弧注入分析（圖 4）區辨**逐步 SNR** 與**事件級 SNR**：當機動量分攤於多日、逐步 SNR < 2 時，訊號沒入雜訊底，純 TLE 不可偵測——此為**物理下限**而非模型缺陷，說明 small 機動召回受限之根因，並指向精密星曆（σ≈0.3 m）為根治路徑。

![圖 3　TLE 半長軸雜訊底隨高度之關係（13 顆 DORIS 測高衛星，認證安靜期實測）。](fig_sigma_vs_altitude.png)

![圖 4　漸進弧注入之逐步 SNR 與偵測率關係。](fig_gradual_arc.png)

## 七、討論

**能力邊界。** 系統之量化成績為 episode（事件融合）級；epoch（單筆 TLE）級之 large TPR 僅 0.383、AUC 0.572，受 8 小時 MEME 網格與 SGP4 擬合限制。本系統定位為**大尺度軌道行為改變之候選事件排序器**，而非單筆 TLE 高精度推力分類器。small 機動（SNR < 2）屬物理偵測下限，應標為「下限以下」而非宣稱召回。

**負面結果。** 我們亦評估深度序列模型：LSTM-AutoEncoder（AUC 0.70）、PatchTST（0.67）與 bi-GRU（無有效判別力）**全面輸給**工程特徵之梯度提升融合（0.98）。原因在於機動為稀疏點事件，變化點統計量之 max／mean／p90 聚合特徵，在有限資料上優於原始序列深度學習。此結果對同類 SSA 任務之模型選型具參考價值。**公平性界定**：深度模型採合理但非窮盡之超參數調校，此結論係針對「稀疏事件＋有限標註」之資料規模，而非深度學習之絕對否定——若正例規模顯著擴增（如以生成器擴增或多星系匯集），結論或異。

**資料漂移與維運。** out-of-time 驗證顯示時間分布有輕微漂移（新發射批次、季節性大氣密度變化）；建議部署後每季以新期資料重跑 GroupKFold 更新融合器，並以分數漂移儀表板監控。

## 八、結論

本文提出並驗證一套適用於 LEO 巨型星系之三層軌道機動偵測架構。於 284 星／67 天全星系嚴格真值擂台上（真值純取自獨立之 MEME、特徵純取自 TLE），融合層達 ROC-AUC 0.985、AP 0.952、large 召回 0.970；星系內未見衛星 hold-out（AUC 0.980、large 81/81）證明其非記憶式泛化，跨異質域範圍則由外部 ILRS 標竿與物理路由（域外 FPR 0.032）誠實界定；真實 67 天部署顯示每日約 1.1 人時之可負荷營運；並量化了純 TLE 對小型機動之 SNR 物理下限。後續將以 MEME 原生標籤重訓單衛星模型、擴展精密星曆輸入以突破小型機動偵測下限，並以外部標竿完成跨域正確性驗證。

## 誌謝

本研究由行政法人國家太空中心（TASA）委辦計畫 TASA-S-1150268 支持。

## 參考文獻

[1] F. R. Hoots and R. L. Roehrich, "Spacetrack Report No. 3: Models for Propagation of NORAD Element Sets," Aerospace Defense Command, 1980.
[2] D. A. Vallado, P. Crawford, R. Hujsak, and T. S. Kelso, "Revisiting Spacetrack Report #3," AIAA 2006-6753, 2006.
[3] T. S. Kelso, "Validation of SGP4 and IS-GPS-200D Against GPS Precision Ephemerides," AAS 07-127, 2007.
[4] O. Montenbruck and E. Gill, *Satellite Orbits: Models, Methods and Applications*, Springer, 2000.
[5] S. Lemmens and H. Krag, "Two-Line-Elements-Based Maneuver Detection Methods for Satellites in Low Earth Orbit," *J. Guidance, Control, and Dynamics*, 37(3), 2014.
[6] R. J. Patera, "Space Event Detection Method," *J. Spacecraft and Rockets*, 45(3), 2008.
[7] T. Kelecy et al., "Satellite Maneuver Detection Using Two-Line Element (TLE) Data," AMOS Conf., 2007.
[8] E. S. Page, "Continuous Inspection Schemes," *Biometrika*, 41(1/2), 1954.
[9] R. P. Adams and D. J. C. MacKay, "Bayesian Online Changepoint Detection," arXiv:0710.3742, 2007.
[10] N. Golyandina, V. Nekrutkin, and A. Zhigljavsky, *Analysis of Time Series Structure: SSA and Related Techniques*, Chapman & Hall, 2001.
[11] P. J. Rousseeuw and C. Croux, "Alternatives to the Median Absolute Deviation," *J. American Statistical Association*, 88(424), 1993.
[12] J. M. Picone, A. E. Hedin, D. P. Drob, and A. C. Aikin, "NRLMSISE-00 Empirical Model of the Atmosphere," *J. Geophysical Research*, 107(A12), 2002.
[13] J. T. Emmert et al., "NRLMSIS 2.0: A Whole-Atmosphere Empirical Model of Temperature and Neutral Species Densities," *Earth and Space Science*, 8(3), 2021.
[14] P. Willis et al., "The International DORIS Service (IDS)," *Advances in Space Research*, 45(12), 2010.
[15] T. Chen and C. Guestrin, "XGBoost: A Scalable Tree Boosting System," KDD, 2016.
[16] G. Ke et al., "LightGBM: A Highly Efficient Gradient Boosting Decision Tree," NeurIPS, 2017.
[17] 行政法人國家太空中心（TASA），「智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究——期中報告（r10）」，TASA-S-1150268, 2026.
[18] T. Saito and M. Rehmsmeier, "The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets," *PLoS ONE*, 10(3), 2015.
[19] E. B. Wilson, "Probable Inference, the Law of Succession, and Statistical Inference," *J. American Statistical Association*, 22(158), 1927.
[20] 本計畫外部標竿驗證章節（採 NASA/ILRS 公開真值），TASA-S-1150268, 2026.
