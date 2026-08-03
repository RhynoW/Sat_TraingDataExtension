# 模組化互動式太空情勢感知儀表板:瞬時鄰近篩選、TCA 精化與在地覆蓋預報

## A Modular Interactive Space Situational Awareness Dashboard: Instantaneous Proximity Screening with TCA Refinement and Regional Coverage Forecasting

**作者**：（作者姓名）　｜　**單位**：（作者所屬單位）
**系統**：SatDashboard（scenario-advanced01，自主新創研發）

---

### Abstract

Space situational awareness (SSA) increasingly requires interactive tools that let analysts screen the entire tracked catalog for proximity events, forecast regional coverage, and inspect orbital geometry in near real time. This paper presents SatDashboard, a modular, web-based SSA platform that ingests Two-Line Elements (TLE) and couples four capabilities on one interface: (1) vectorized SGP4 propagation of the entire catalog at a common epoch via the batched SatrecArray interface; (2) all-pairs **instantaneous proximity screening** using a k-d tree (`query_pairs`), followed by a lightweight **time-of-closest-approach (TCA) refinement** that propagates each candidate pair over one orbital period to recover its true TCA, miss distance, and relative speed; (3) regional coverage and overpass forecasting for a ground site (Taipei, ±30-day timeline); and (4) an optional Space-Track integration with graceful degradation, user-defined overlays, and hot-reloadable configuration. On a single workstation (Intel Raptor Lake, 24 cores; timings are medians of five runs), efficiency—which is independent of TLE data age—scales near-linearly: a full 31,481-satellite snapshot completes in ~0.35 s on first call and ~52 ms in steady state (cached SatrecArray). Behavior results use **fresh TLE (median age 1.2 days)**; we show that data currency is decisive—on the same Starlink constellation (~10.8k objects), 18-day-old TLE yields 31 candidate pairs at 10 km versus only 8 with fresh TLE (~4×, and ~14× at 5 km), the excess being propagation-error artifacts. On fresh data, TCA refinement resolves the 8 snapshot candidates into 5 fast transits (4 genuinely closing), 2 co-orbital, and 1 mid-speed pair; the conjunction-meaningful fast-transit miss distances (median 5.5 km) are reported separately from co-orbital formation spacing. We limit the isotropic first-order Pc proxy (inspired by Chan, 2008) to fast-transit pairs, and position CelesTrak SOCRATES as the intended correctness benchmark with an explicit screening-window caveat. An event-driven roadmap is outlined.

**Keywords**: space situational awareness; proximity screening; time of closest approach; SGP4; k-d tree; collision probability; data currency; interactive visualization

---

## 一、緒論

太空情勢感知（SSA）的日常作業，除了「偵測與判讀」之外，還需要一套能讓分析人員**互動探索**的工具：在近即時的時間尺度上，對整個編目篩選出**鄰近事件熱點**、預報地面站的覆蓋與過頂時段、並以三維幾何檢視軌道狀態。商用平台（如 STK）功能完整但授權昂貴、不易客製與內部部署；純前端的三維檢視器（多以 CesiumJS 實作）擅長展示，卻通常不含全目錄的鄰近篩選與碰撞機率計算。

需特別界定的是：**「瞬時鄰近」不等於「碰撞接近事件（conjunction）」**。低軌相對速度動輒 7–14 km/s，兩物體停留在 10 km 內僅約 1–2 秒；單一時刻的距離篩選會納入（a）恰好同時經過附近的無關物體、（b）同次發射的共軌 payload／debris 群、（c）編隊飛行衛星。本文因此明確採「瞬時鄰近篩選（instantaneous proximity screening）」一詞，並以一個**輕量 TCA 精化**步驟把快照候選收斂為真正逼近中的配對。此外，本文亦以受控對照量化**資料時效（data currency）**對篩選之影響——這在互動式工具之討論中常被忽略。

本文提出 **SatDashboard**——一套模組化、以 Web 為介面的自主 SSA 平台，將四項能力整合於單一介面：(1) **向量化 SGP4**；(2) **k-d tree 瞬時鄰近篩選 + TCA 精化**；(3) **在地覆蓋與過頂預報**（台北，±30 天時間軸）；(4) **Space-Track 選配整合**與使用者自訂資料、設定熱重載。本文貢獻有四：

1. 一套**可全目錄近即時運行**的鄰近篩選管線，全 31,481 顆單快照首次約 0.35 秒、穩態約 52 毫秒（效能與資料齡無關、近線性擴展）；
2. **輕量 TCA 精化**把快照鄰近收斂為真接近，並分類別（共軌／中速／快速）報告——避免把瞬時鄰近計數誤讀為 conjunction 計數；
3. 以**受控對照量化資料時效**：同一 Starlink 星系，過期 TLE（18 天）較新鮮 TLE（1.2 天）多出約 4×（@10km）之候選，多為傳播誤差假影；
4. 誠實界定近似 Pc 之適用範圍（僅快速穿越類）、並以 SOCRATES 為正確性驗證路徑（含視窗不匹配之方法學說明）。

## 二、相關研究與系統定位

**軌道傳播。** SGP4/SDP4（Hoots & Roehrich, 1980；Vallado et al., 2006）為業界標準；本系統採其開源實作並優先使用批次化 `SatrecArray` 介面以攤平 Python 逐顆呼叫之額外負擔（Montenbruck & Gill, 2000 為軌道方法之通論參考）。TLE 之精度隨物體高度、資料齡與太陽活動變化，低軌傳播逾日誤差快速累積（Kelso, 2007）——此即本文第五節量化資料時效之動機。

**接近事件篩選。** 作業級全對接近篩選之標準做法為**多階時間視窗濾波**：Hoots, Crawford & Roehrich（1984）以遠地點／近地點、軌道幾何路徑與時間三重濾波，於龐大編目中排除不可能接近之配對；Alfano（2012）之環面路徑濾波以幾何走廊縮小候選集。此類方法本質上**沿時間視窗**求最接近點。本系統之 k-d tree `query_pairs`（Bentley, 1975）則為**單一時刻**之空間鄰近查詢——兩者分工互補：快照法以近 $O(N\log N)$ 快速圈出瞬時鄰近熱點供互動展示，再對少量候選以 TCA 精化沿時間軸求極值。全目錄對全目錄之公開接近報告（如 CelesTrak **SOCRATES**、NASA **CARA**、開源 **KeepTrack.space**）提供作業級參考，本文將 SOCRATES 定位為**正確性交叉比對基準**（第五、八節）。

**碰撞機率。** 嚴謹 Pc 需最接近點之相對協方差投影至遭遇平面（Foster & Estes, 1992；Alfano, 2005；Chan, 2008，等效面積 Rician 級數）。**低相對速度接近**則違反 2D 遭遇平面法之核心假設（高相對速度、線性相對運動、單次穿越），須改用 3D 非線性方法（Coppola, 2012）。本系統於篩選階段採一個**受 Chan (2008) 啟發之各向同性首階近似**作快速排序，並**僅施於快速穿越類**（見 4.4）。

系統定位：**互動式初篩、熱點偵測與態勢展示平台**——近即時、可客製、可內部部署，補商用平台與純展示型檢視器之間的空缺；其輸出為**候選排序**，作業級碰撞評估仍回歸含真實協方差之 CDM 流程。

## 三、系統架構

系統由 3,880 行單體 Flask 腳本重構為分層 Python 套件（表 1），各層職責單一、物理運算層不依賴 Flask，便於單元測試與重用。應用以 `create_app()` 工廠模式組裝，前後端分離（Jinja2 模板 + 靜態資源），並以 Docker 封裝、可於容器平台部署。

**表 1　模組化分層架構與職責**

| 層 | 模組 | 職責 |
|---|---|---|
| config | settings／stations／classification_rules | 環境變數、路徑、常數之唯一來源；SSN 站點（29 站，公開地面站資訊彙整、可替換）與國別／星座分類規則外部化 |
| ingestion | db／metadata／index／spacetrack | DuckDB 存取、衛星索引（現行＋歷史時間軸）、統計、Space-Track 選配整合與降級 |
| physics | coords／propagate／coverage／conjunction | 純數學：座標轉換、向量化 SGP4、覆蓋／過頂、k-d tree 鄰近＋TCA 精化＋近似 Pc（無 Flask 依賴） |
| services | passes_service | 過頂預報背景執行服務 |
| api | 多個 Flask Blueprint | 31 個 REST 端點（頁面／位置／過頂／接近／圖層／管理） |
| web | templates／static | globe.html（3D）、taipei.html（2D）＋ JS/CSS |

## 四、核心方法

### 4.1 向量化 SGP4 傳播

給定全目錄 $N$ 顆衛星之 TLE 與目標時刻 $t$，系統以 `SatrecArray`（sgp4 套件，Vallado et al., 2006 之開源實作）一次批次傳播取得慣性系位置 $\mathbf{r}_i(t)$；當批次介面不可用時自動退回逐顆傳播。批次化將 $N$ 次 Python 層呼叫攤平為單次向量運算；`SatrecArray` 於首次由 TLE 解析建構，之後可**跨快照重用**（穩態延遲因此遠低於首次）。傳播後以 ECI→地理座標批次轉換，並依高度合理範圍（$-500$ 至 $80{,}000$ km）濾除異常解。

### 4.2 瞬時鄰近篩選

以有效衛星之慣性系座標建 k-d tree，呼叫 `query_pairs(d)` 枚舉所有**於當下時刻**相互距離小於閾值 $d$（預設 10 km）之配對，複雜度為建樹 $O(N\log N)$ 加輸出敏感之枚舉，遠優於暴力 $O(N^2)$。此步驟產出**瞬時鄰近候選**——其中多數並非逼近中之 conjunction，須經 4.3 之 TCA 精化辨別。

### 4.3 TCA 精化

對每一瞬時鄰近候選對，沿當下時刻 $\pm 1$ 軌道週期（取兩物體週期之**較長者**，約 ±55 分）以粗掃（5 s 步長）加細掃（極小值附近 0.25 s）求相對距離之極小值，得**真正的最接近時刻（TCA）與最小距離（miss distance）**，並以 TCA 前後有限差分估計**相對速度**。候選對僅數個至數十個，計算量極小（約 10 ms/對）。相對速度提供分類：

- **快速穿越**（相對速度 $>1$ km/s）：具真實相對運動，為 conjunction 之候選；其中精化後 miss distance 明顯小於快照距離者為**真接近中**。
- **中速**（$0.1$–$1$ km/s）：介於其間，多為異軌交會之邊界情形，個別檢視。
- **低相對速度／共軌**（$<0.1$ km/s）：距離近乎恆定，多為同批發射／編隊之**持續同行**；惟須注意——低相對速度接近其實是碰撞評估中著名之困難案例（停留時間長、累積機率未必低），其風險評估需另用 3D 非線性方法（Coppola, 2012），**非本文 2D 代理之適用範圍**（見 4.4）。

此步驟使「conjunction」一詞站得住腳，並直接回應快照法之核心限制（第五節量化）。

### 4.4 近似碰撞機率（僅快速穿越類）

對**快速穿越類**候選對，以精化之 miss distance $m$ 代入受 Chan (2008) 啟發之各向同性首階近似：

$$\sigma^2 = \sigma_r^2 + \sigma_t^2, \qquad P_{c,\text{base}} = 1 - \exp\!\left(-\frac{r_A^2}{2\sigma^2}\right) \tag{1}$$

$$P_c = P_{c,\text{base}} \cdot \exp\!\left(-\frac{m^2}{2\sigma^2}\right) \tag{2}$$

其中 $r_A$ 為合成硬體半徑（等效 0.005 km）。**適用界定**：(i) 式 (1)(2) 取 Chan 級數首項並假設圓對稱協方差，非其各向異性等效面積解；(ii) $\sigma_r=0.1$、$\sigma_t=0.5$ km 為**代表性量級假設，非個別物體之真實協方差**（TLE 誤差隨高度、資料齡與太陽活動變化）；(iii) 式 (1)(2) 之高相對速度、線性穿越假設**僅對快速穿越類成立**，故**共軌／低相對速度類不輸出 Pc（標為 N/A）**，其風險須另用 3D 非線性方法。此式僅作快速排序代理，作業級評估須改用含真實協方差之 CDM。

### 4.5 在地覆蓋、資料層與可擴充性

**在地覆蓋與過頂預報。** 以地面站（台北，25.033°N／121.565°E）為中心，將傳播所得衛星位置轉為相對仰角／方位，套用最小仰角遮罩（5°）；覆蓋半徑（2,000 km 斜距）為每一時刻**可見性閘門**（僅斜距內、且高於仰角遮罩者計入當下覆蓋集合），不將任何物體排除於編目與傳播之外。因幾何之故，覆蓋集合以低軌物體為主；提供 **±30 天時間軸**回放。**適用性說明**：覆蓋集合內之低軌物體，其過頂時刻之預報誤差隨天數增長（大氣阻力不確定性累積），遠期時間軸宜作趨勢參考。

**資料層與整合。** 資料以 **DuckDB** 為後端，索引具 TTL 快取（統計 600 s、鄰近 120 s；可選 Redis 後端）。**Space-Track** 為選配整合，缺憑證時自動降級為僅用本地資料。系統支援四類**使用者自訂資料**（TLE、衛星目錄、NORAD 監測清單、GeoJSON 圖層），放檔即生效（或以 `POST /api/admin/reload_cats` **熱重載**）。系統並記錄每筆 TLE 之 epoch，可依**資料齡**過濾或降權（第五節）。**合規說明**：若對外提供介面轉發 Space-Track 資料，須遵循其使用者協議之再散布條款；本系統以內部部署為預設，並以使用者自備憑證存取來源資料。

## 五、效能與行為實測

於單一工作站（Intel Raptor Lake，24 實體／32 邏輯核心、64 GB RAM；Python 3.13、sgp4 2.25、SciPy 1.16、NumPy 2.5）量測；時間量測均取 5 次之中位數。

**效能與擴展（與資料齡無關）。** TLE 解析、傳播與空間查詢之延遲僅取決於物體數與幾何，與 TLE 資料齡無關，故以全目錄（31,734 顆、經高度濾除後 31,481 顆有效）量測（表 2、圖 1 左）：首次含 TLE 解析約 302 ms、傳播 16 ms、建樹 12 ms、`query_pairs`（10 km）24 ms，**首次合計約 0.35 s**；`SatrecArray` 快取後**穩態每快照約 52 ms**。傳播延遲隨衛星數**近線性**（5k/10k/20k/31k：2.9/4.8/10.3/14.7 ms），佐證 $O(N)$ 傳播與 $O(N\log N)$ 建樹之分析。

![圖 1　單快照全目錄延遲分解（左）與向量化傳播之近線性擴展（右），實測 31,481 顆有效衛星。](fig_ssa_perf.png)

**表 2　效能實測（全目錄 31,481 顆，5 次量測之中位數）**

| 項目 | 量測值 |
|---|---|
| TLE 解析（twoline2rv，僅首次，可快取） | 302 ms |
| 向量化傳播（SatrecArray.sgp4） | 16 ms |
| k-d tree 建樹 | 12 ms |
| `query_pairs`（10 km） | 24 ms |
| 首次合計 / 穩態（快取後） | 約 0.35 s / 約 52 ms |
| 傳播擴展（5k/10k/20k/31k） | 2.9 / 4.8 / 10.3 / 14.7 ms |

**資料時效之決定性影響（受控對照）。** 行為結果（配對、分類、miss）**必須用新鮮 TLE**：低軌 TLE 傳播 18 天，位置誤差可達數十公里，足以憑空製造或抹除近接。為量化此效應，於**同一 Starlink 星系（~10.8k）、同一方法**下比較兩種資料齡（圖 2 左）：過期 TLE（中位齡 18.2 天）於 10 km 得 **31** 個候選、於 5 km 得 14 個；新鮮 TLE（中位齡 1.2 天，取自 CelesTrak）於 10 km 僅 **8** 個、於 5 km 僅 1 個。**過期資料膨脹候選約 4×（@10km）至 14×（@5km），多為傳播誤差假影。** 故下述行為實測一律採新鮮資料。

**新鮮資料之行為實測（TCA 精化）。** 以新鮮 Starlink 目錄（10,767 顆、TLE 中位齡 1.23 天）為例（圖 2 右）：10 km 快照得 **8 個候選**，TCA 精化（約 10 ms/對）分類為 **5 個快速穿越（其中 4 個真接近中）、2 個共軌、1 個中速**。分類別報告 miss（避免混類扭曲，回應審查）：**快速穿越類**（具 conjunction 意義）之 miss distance 中位 **5.5 km**、最小 2.3 km；**共軌類**之「miss」實為隊形間距（3–6 km），另述。可見即便於新鮮資料，快照計數（8）仍高於真接近（4），TCA 精化為必要之收斂；而過期資料（31）更會把此高估放大數倍。

（說明：本次行為實測採新鮮 **Starlink** 目錄，因 CelesTrak 對完整 active 目錄之重複請求採 2 小時更新之禮貌性限流；效能與擴展則以全目錄量測，因其與資料齡及星系組成無關。）

![圖 2　資料時效受控對照（左，同 Starlink 星系、僅資料齡不同）；新鮮資料之 TCA 精化分類（右，8 候選 → 4 真接近）。](fig_ssa_tca.png)

**正確性驗證（規劃）與方法學界定。** 本文已完成**效能**、**資料時效**與**行為分類**之實測；**正確性**之外部交叉比對列為即將步驟，並須注意**視窗不匹配**：CelesTrak SOCRATES 報告未來 7 天之 TCA，本系統之 TCA 精化僅掃當下 ±1 軌道週期（±55 分）——兩者篩選範圍本質不同（快照當下 vs 未來 7 天）。正確之比對須（a）將本系統之篩選延伸為時間視窗式（即路線圖之事件驅動化），或（b）僅就 TCA 落於可比視窗內之 SOCRATES 事件與本系統候選作交集比對；否則召回率會被誤讀。此比對將於下一步以新鮮資料（與 SOCRATES 同源時效）進行。

## 六、系統功能與介面

前端提供 **3D 地球儀**（CesiumJS，globe.html）與 **2D 台北覆蓋**（taipei.html，含時間軸）兩視圖。主要互動功能包括：**NORAD 監測**（多顆同時追蹤、地球即時標示＋軌道弧、每 15 秒更新、可勾選或手動加入，上限 50 顆）、鄰近／接近面板（閾值可調、逐對顯示 miss distance、TCA 與 Pc）、CDM 與衰減（decay）查詢 API、以及自訂向量圖層開關。所有路由、參數與回應格式與原單體版一致，確保重構之行為等價。

## 七、工程實踐

系統之工程品質為本文重點之一：(1) **模組化**——由 3,880 行單體重構為 27 個模組、物理層與 Flask 解耦；(2) **可測試性**——128 項 pytest（純函式單元測試＋應用冒煙測試），涵蓋座標轉換、傳播、鄰近／TCA、覆蓋與各 API 端點；(3) **可部署性**——Docker 封裝、容器平台就緒；(4) **可維運性**——設定（分類規則、SSN 站點、過頂類別）全外部化並支援熱重載，前端 JS/CSS 改動不需重啟；(5) **可擴充性**——四類使用者自訂資料放檔即生效。此等實踐使系統從「研究原型」邁向「可維運之內部服務」。

## 八、討論與限制

**近似 Pc 與適用類別。** 式 (1)(2) 為各向同性首階近似、僅施於快速穿越類，未使用每對真實相對協方差，不取代作業級 CDM；共軌／低相對速度類不輸出 Pc，其風險須另用 3D 非線性方法（Coppola, 2012）。**TCA 為兩體幾何。** 4.3 之精化沿一軌道週期求極值，已將快照鄰近收斂為真接近，但採兩體 SGP4 外推，未含機動與攝動不確定性之協方差傳播。**資料時效。** 第五節已量化過期 TLE 之候選膨脹；行為結果須以新鮮資料產生，部署應每日更新並以資料齡旗標降權。**正確性外部驗證待補。** SOCRATES 交叉比對已定位為即將步驟，並須處理視窗不匹配（第五節）。上述限制清楚界定本系統與作業級碰撞評估之分工，不減損其作為**近即時初篩、熱點偵測與態勢展示平台**之價值。

## 九、結論與展望

本文提出並實測 SatDashboard——一套模組化、可全目錄近即時運行的互動式 SSA 平台。效能上（與資料齡無關），全 31,481 顆單快照首次約 0.35 秒、穩態約 52 毫秒，傳播近線性擴展。行為上採**新鮮 TLE**（中位齡 1.2 天）：TCA 精化把 10 km 之 8 個瞬時鄰近收斂為 5 個快速穿越、其中 4 個真接近，並分類別報告 miss；且以受控對照證明**資料時效之決定性**（同星系過期資料膨脹候選約 4×）。系統整合在地覆蓋預報、Space-Track、使用者自訂資料與設定熱重載，工程上由單體重構為含 128 項測試之分層架構。後續：以 SOCRATES 完成正確性交叉比對（處理視窗不匹配）；把篩選延伸為時間視窗式；獨立 ingestion 排程與 Redis Streams；WebSocket 事件推送與告警規則引擎；以及實測感測器接入、track fusion 與 STK 匯出。

## 誌謝

本系統為作者自主新創研發之獨立成果，與任何機構均無隸屬或委辦關係。

## 參考文獻

[1] F. R. Hoots and R. L. Roehrich, "Spacetrack Report No. 3: Models for Propagation of NORAD Element Sets," Aerospace Defense Command, 1980.
[2] D. A. Vallado, P. Crawford, R. Hujsak, and T. S. Kelso, "Revisiting Spacetrack Report #3," AIAA 2006-6753, 2006.
[3] F. R. Hoots, L. L. Crawford, and R. L. Roehrich, "An Analytic Method to Determine Future Close Approaches Between Satellites," *Celestial Mechanics*, 33(2), 1984.
[4] S. Alfano, "Toroidal Path Filter for Orbital Conjunction Screening," *Celestial Mechanics and Dynamical Astronomy*, 113, 2012.
[5] J. L. Bentley, "Multidimensional Binary Search Trees Used for Associative Searching," *Communications of the ACM*, 18(9), 1975.
[6] F. K. Chan, *Spacecraft Collision Probability*, The Aerospace Press, 2008.
[7] V. T. Coppola, "Including Velocity Uncertainty in the Probability of Collision Between Space Objects," AAS 12-247, 2012.
[8] J. L. Foster and H. S. Estes, "A Parametric Analysis of Orbital Debris Collision Probability and Maneuver Rate for Space Vehicles," NASA/JSC-25898, 1992.
[9] S. Alfano, "A Numerical Implementation of Spherical Object Collision Probability," *J. Astronautical Sciences*, 53(1), 2005.
[10] T. S. Kelso, "Validation of SGP4 and IS-GPS-200D Against GPS Precision Ephemerides," AAS 07-127, 2007.
[11] T. S. Kelso and Analytical Graphics, Inc., "SOCRATES: Satellite Orbital Conjunction Reports Assessing Threatening Encounters in Space," CelesTrak.
[12] O. Montenbruck and E. Gill, *Satellite Orbits: Models, Methods and Applications*, Springer, 2000.
[13] P. Virtanen et al., "SciPy 1.0: Fundamental Algorithms for Scientific Computing in Python," *Nature Methods*, 17, 2020.
[14] CesiumJS, "An Open-Source JavaScript Library for World-Class 3D Globes and Maps," Cesium GS, Inc.
