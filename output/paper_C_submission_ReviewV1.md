# Paper C 投稿文件審查 — Review V1

- 輸出文件：paper_C_submission_ReviewV1.md
- 審查日期：2026-11-18
- 審查對象：paper_nrlmsis_drag_validation_cover_letter_EN.pdf（1 頁投稿附函）
- 目標期刊：Space Weather
- 審查範圍：依提供的附函文字，檢查論述一致性、主張強度、研究定位及投稿前待補事項。未取得論文全文、圖表、程式、資料與其他兩篇稿件，也未核對期刊最新規範、Space-Track 條款或資料庫內容。因此，本文件不是對研究結果的獨立驗證，也不代表已完成期刊格式合規審查。

## 一、總評與建議

建議：完成重大文字修訂與必要的證據核對後，再提交此附函。

附函已有清楚的應用問題、樣本規模、跨資料來源驗證及量化結果。最有辨識度的貢獻，是指出良好的時間相關性不代表模型沒有活動度相依偏差，且此偏差可能影響軌道機動篩選。

目前最重要的風險不是英文文法，而是讀者可能把「經每星彈道係數校準的軌道衰減模型」誤讀為「NRLMSIS 2.1 絕對密度精度已獲獨立驗證」，或把未經嚴格確認的被動衛星族群視為可靠的非機動真值。這兩個界線需要在附函與正文一致表達。

尚有投稿阻擋事項：日期與作者資訊未填、作者同意與利益衝突聲明未確認、資料 DOI 未提供，以及研究期間的確切截止日期未明。建議先修正這些問題，再進行最後潤稿。

## 二、優先修訂清單

| 優先級 | 問題 | 風險 | 建議處理 |
|---|---|---|---|
| P0：送出前必須處理 | `[To be confirmed.]` 與作者、日期等占位文字 | 無法確認投稿聲明已獲授權，且附函未完成 | 逐項取得作者確認；填入正式資訊，刪除占位文字 |
| P0 | 研究期間僅寫 January 2024 to November 2026 | 無法判定是否涵蓋完整 11 月；本次審查日為 11 月 18 日 | 改為真實資料截止日；若資料尚未完整，不得暗示涵蓋月底 |
| P0 | 425 顆與 265 顆的母體／子集關係不明 | 結果的分母與適用範圍不清 | 說明總樣本、被動候選樣本及各分析合格子集的關係 |
| P0 | DOI 尚未指定 | 資料可得性聲明仍未完成 | 取得可用的資料紀錄與適當識別碼，核對實際存取狀態後填寫 |
| P1：高度建議 | 每星一個彈道係數的估計與驗證界線未交代 | 校準與驗證混淆，可能高估泛化能力 | 明示係數是否由同一時段擬合，以及是否有時間外驗證 |
| P1 | 精密軌道結果稱為 confirmed independently | 容易把觀測來源獨立誤解為校準或物理模型完全獨立 | 改為 independent orbit data provide corroborating evidence，並在正文說明共享假設 |
| P1 | 17% 未定義 | 相對變化、百分點與絕對偏差可能混淆 | 明確定義比值、低／高通量組別與變化算法 |
| P1 | over-alarms、insensitive、primary limitation 語氣強 | 若缺乏真值與比較分析，主張超出證據 | 按證據改為 excess flags、reduced sensitivity、a limitation |
| P1 | companion manuscripts「do not overlap in data analysis」 | 絕對性聲明可能與共用資料、方法或圖表不一致 | 逐篇核對共同與不同部分，避免未查證的零重疊保證 |
| P2：編輯改善 | 標題較長，且主題稍偏操作門檻 | 空間天氣科學訊息可能被應用細節遮蔽 | 優先凸顯 solar-activity-dependent bias，再連接篩選用途 |

## 三、主要技術與論證問題

### 3.1 NRLMSIS 驗證與整體阻力建模驗證須分開

原文以「Validating NRLMSIS 2.1 Orbital-Decay Predictions」描述研究，但同時指出每顆衛星使用一個彈道係數。從附函無法判定係數是獨立給定、全期擬合，還是以訓練期估計。

若係數由同一批衰減資料擬合，模型的固定尺度差異可能被係數吸收。此時，結果仍能支持時間變化或活動度相依誤差的分析，但不能僅據此宣稱模型絕對密度準確，亦不能把樣本內擬合直接當作樣本外預測。

正文應交代：

1. 彈道係數的定義與單位，避免 CdA/m 與其倒數混用。
2. 係數估計資料、損失函數及訓練／測試切分。
3. 是否在測試期重新估計或調整係數。
4. 姿態、有效截面積與阻力係數變化如何處理。
5. 軌道平均、傳播與非阻力項的處理方式。

附函建議使用「using one fitted ballistic coefficient per satellite」；但只有實際為擬合時才能加 fitted。若確有獨立留出期，應以一句話明示，這比單純強調高相關係數更能建立可信度。

### 3.2 425 顆、265 顆與「passive」的定義

標題及第一項結果容易讓人以為全部 425 顆均已確認為被動衛星；第二項結果卻以 265 顆為分母，第三項又承認參考族群受到小幅軌道維持污染。

這不一定代表研究矛盾，但附函沒有提供足夠資訊消除疑慮。若被動性是依資料篩選推定，宜使用「nominally passive」或「candidate passive」而非暗示已知真值。

應在正文提供樣本流向表：初始樣本數、各排除條件、各高度層數量、係數擬合合格數、活動度分析合格數與最終 265 顆的形成原因。附函至少增加一個限定語，說明 265 顆是何種合格子集。

### 3.3 相關係數支持變化追蹤，不等於絕對準確度

median per-satellite correlation 0.92 與 precise-orbit r = 0.962 是不同統計摘要。前者為每星相關係數的中位數；後者是單星、合併樣本或其他聚合方式，目前不明。

請核對並說明：

- 相關係數類型，以及資料取樣與平滑時間尺度。
- FORMOSAT-7 涉及幾顆衛星、哪些期間與多少有效樣本。
- r = 0.962 的聚合方式，是否混合衛星或高度差異。
- 絕對偏差、相對誤差及不確定度是否另有報告。

附函宜將 reproduces 改為 tracks，並把「confirmed」改為「corroborated」。這樣既保留結果，也避免把高相關性誤包裝為完整準確度驗證。

### 3.4 約 17% 的方向與意義須明確

「predicted-to-observed decay ratio rises by about 17%」只表示比值從低通量到高通量上升，不自動等於高通量時高估 17%。例如，比值可能由低於 1 上升至接近 1，也可能由接近 1 上升至高於 1；兩者的物理與操作解讀不同。

應確認：

1. decay 是否採正的衰減量值，或採帶符號的軌道變化率。
2. 比值是在何種時間窗及聚合層級計算。
3. 17% 是相對增幅 `(R_high/R_low - 1) × 100%`，還是其他統計量。
4. solar flux 採何種指標，以及 low/high 的分組準則。
5. 89% 指方向一致的衛星比例，還是各自達統計顯著的比例。
6. 是否檢查高度、時間、地磁活動與樣本組成等共同變化因素。

若尚未排除混雜因素，建議保留 activity-dependent 或 associated with solar flux 的描述，避免宣稱已證明特定模型機制導致偏差。

### 3.5 FORMOSAT-7 的「獨立」應限定範圍

使用精密軌道能提供不同於 TLE 的觀測來源，但不自動代表參數估計、資料前處理與參考模型也完全獨立。

建議表述為「corroborated using FORMOSAT-7 precise-orbit data, independently of the TLE observations」。正文再說明精密軌道如何轉換為衰減量、其時間尺度，以及是否共用彈道係數估計程序。

### 3.6 門檻表現與機動真值不能混用

「over-alarms below 450 km」需要可靠的非機動標記，否則較高的觸發率也可能包含真實小機動或其他未建模效應。「insensitive above 600 km」則需要已知機動、控制注入或其他可檢驗的靈敏度證據。

若只有未標記族群的殘差與觸發比例，較穩妥的說法是「produces altitude-dependent flagging rates」。若有對應驗證，才保留 false-alarm、missed detection 或 sensitivity 的定量主張。

另外，須分開說明：

- 高度門檻是以近地點高度、平均高度還是其他高度定義。
- out-of-sample 是跨時間、跨衛星或同時跨兩者。
- 門檻是否僅以訓練資料決定。
- 是否使用具時序相關性的樣本，以及評估單位為逐點或逐事件。

這些應屬於證據核對項目，不宜只靠附函措辭補救。

### 3.7 「primary limitation」目前證據不足以核實

附函將小幅 station-keeping 污染稱為 primary limitation，但沒有說明如何識別、量化及與其他限制比較。

若只有間接跡象，建議寫為「potential contamination ... remains a limitation」。若有敏感度分析或獨立證據，則可改為「is identified as an important limitation」，並在正文提供相應結果。只有能支持其相對重要性時，才保留 primary。

## 四、研究定位與附函結構

從現有文字看，最有說服力的敘事順序是：

1. 應用缺口：用於機動篩選的密度驅動衰減預測，需要在實際活動度範圍下評估。
2. 核心結果：模型能追蹤主要時間變化，但預測／觀測比仍隨太陽活動改變。
3. 交叉資料佐證：FORMOSAT-7 精密軌道呈現一致方向，而不僅是 TLE 特性。
4. 操作意義：固定與高度調整門檻都有適用限制，不能直接假定跨高度、跨時段可遷移。

這個順序能把空間天氣變異與操作後果連起來。附函應避免以「模型很準」作為第一印象，再於後文突然轉成「模型有偏差」；兩者其實可以並存，但須明示一個談時間變化，另一個談尺度與條件性誤差。

可考慮的標題方向：

> Solar-Activity-Dependent Bias in NRLMSIS 2.1–Based Orbital-Decay Estimates: Evaluation With LEO Satellite TLEs and FORMOSAT-7 Precise Orbits

這是編輯建議，未核對目標期刊標題限制。若 425 顆的母體定義已釐清，可再把樣本數放回標題；否則先不要把「425 Passive」作為強主張。

## 五、投稿聲明與資料可得性

### 5.1 Companion manuscripts

主動揭露另外兩篇稿件是優點，但「different questions and do not overlap in data analysis」應有可核對依據，不能只依研究題目不同而推定。

建議建立內部對照表，逐篇記錄：研究問題、資料來源與時段、樣本、前處理程式、核心方法、圖表、結果及本稿的獨立貢獻。共用資料或工具應如實說明；是否構成不當重複須另行判斷，不能僅由這封附函定論。

若仍在審稿中，核對最新投稿狀態與完整題名。是否須提供相關稿件副本或投稿系統另有揭露欄位，應以期刊當時要求為準。

較安全的表述骨架：

> Two related manuscripts address TLE noise characterization and maneuver-detection sensitivity, respectively. The present manuscript focuses on activity-dependent behavior in NRLMSIS 2.1–based decay estimates and its implications for residual screening. [Add an accurate description of shared data, methods, and distinct analyses.]

方括號內容為待作者完成的內部提示，不可保留於正式投稿版。

### 5.2 資料 DOI 與可重現性

目前 `[Zenodo DOI to be assigned]` 尚不足以確認資料已正式可得。應填入與實際上傳版本一致的資料識別碼與存取資訊，並核對資料包內容。

建議資料包至少列明：衛星識別碼、精確起訖時間、TLE 篩選條件、外部輸入資料來源與版本、處理參數、衍生量定義、彈道係數估計方式，以及重現主要圖表所需的程式與設定（以實際可公開內容為限）。

附函所稱 raw TLEs cannot be redistributed under the Space-Track user agreement，本審查未查證。作者應核對適用條款、實際取得途徑及限制範圍；不能把未經核實的法律或授權判斷當作定論。其他資料來源，包括精密軌道與外部活動度輸入，也須分別交代存取與使用條件。

### 5.3 推薦審稿人

既然原文標為 optional，若不提供就刪除整段占位文字；若提供，填入真實姓名、機構、聯絡資訊與相關專長，並依期刊規範核對利益衝突。不要在未查證的情況下補入人名或電子郵件。

## 六、英文關鍵句修訂建議

以下為條件式修訂，不應在未核實證據前直接替換全文。

| 原文 | 建議 | 理由與使用條件 |
|---|---|---|
| the density model it relies on is seldom tested under the conditions of that use | the applicability of density-model-based decay estimates to this screening task requires evaluation across solar-activity conditions | 減少對既有文獻「很少研究」的未舉證概括 |
| Over January 2024 to November 2026 | From January 2024 through [actual cutoff date] | 明確資料截止日，不暗示涵蓋尚未完成的月份 |
| reproduces the solar-activity variation | tracks the temporal variation in observed orbital decay | 降低由相關性直接推論物理歸因或絕對準確度的風險 |
| confirmed independently of TLEs by precise orbits | corroborated using FORMOSAT-7 precise-orbit data independently of the TLE observations | 限定獨立性為觀測來源 |
| rises with solar flux by about 17% | is approximately 17% higher in the high-flux subset than in the low-flux subset | 僅在確為兩組相對比較時採用，仍須定義分組與算法 |
| consistently across 89% of 265 passive satellites | with the same direction of change in 89% of the 265 satellites meeting the analysis criteria | 明確指方向一致，不暗示全部達顯著；需補足子集條件 |
| over-alarms below 450 km and is insensitive above 600 km | produces altitude-dependent screening behavior | 未有可靠機動真值前較保守；若已有驗證，應保留並量化原主張 |
| is identified as a primary limitation | remains a limitation | 若污染僅為推測，另加 potential；若有強證據可適度提高語氣 |

## 七、投稿前核對表

### 文件完整性

- [ ] 填入日期、通訊作者、機構、地址與電子郵件。
- [ ] 取得全體作者對投稿、稿件版本與利益衝突聲明的實際確認。
- [ ] 移除全部未完成占位文字。
- [ ] 填入有效的資料識別碼，核對存取與版本狀態。
- [ ] 核對投稿系統中的文章類型名稱與必要聲明。

### 科學主張

- [ ] 釐清 425 顆與 265 顆之間的篩選流程。
- [ ] 被動性未獲獨立確認時，使用 nominally passive 等限定詞。
- [ ] 說明每星彈道係數如何估計及是否有資料洩漏風險。
- [ ] 定義 0.92 與 0.962 的統計單位及聚合方式。
- [ ] 定義 17% 的算法、正負號及低／高通量分組。
- [ ] 說明 89% 是方向一致還是統計顯著。
- [ ] 釐清 FORMOSAT-7 觀測、參數與分析程序的獨立程度。
- [ ] 以證據支持假警報、靈敏度與 primary limitation 等措辭。
- [ ] 明確記錄研究資料截止日。

### 研究倫理與可重現性

- [ ] 核對兩篇相關稿件的最新狀態及實際重疊內容。
- [ ] 確認附函、正文、摘要與資料包的數字及主張一致。
- [ ] 核對 Space-Track 與其他資料來源的適用條款。
- [ ] 確認資料包與方法描述足以重現主要結果，並清楚揭露不能公開的部分。

## 八、最終判定

此附函具備可用的研究敘事與量化亮點，但尚不建議原樣送出。優先完成「母體與子集定義」「校準與驗證界線」「17% 的統計意義」「篩選效能的真值依據」四項核對，再處理資料與投稿聲明。

本次不提供看似可直接提交的完整替代附函，因為多項關鍵措辭仍取決於尚未提供的研究證據。待上述項目釐清後，才適合產生無占位文字的 submission-ready 版本。

## 審查依據

使用者提供之單頁投稿附函 PDF：paper_nrlmsis_drag_validation_cover_letter_EN.pdf。所有樣本數、相關係數、比例、高度與稿件狀態，均為附函所述，未經本次審查獨立驗證。
