# 第 9 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第09章_統計層判斷多不尋常_單章.pdf，15 頁：封面、扉頁、版權頁、第 9 章 11 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 9 章　統計層：判斷「多不尋常」」／"Chapter 9: The Statistical Layer: Judging "How Unusual""。檔案 21.9 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（圖 9-1 為本專案案例集匯出圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=09
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=09

內容依據：全部取自第 9 章 v1.3 正文（已依 TASA 結案報告更新：L2 在 R7 中的角色、低置信複核項真值評估、三層比較數字）與本章外部事件來源，未新增事實。

---

## 中文貼文內容

2015 年春天，一顆俄羅斯衛星移進地球同步軌道上兩顆國際通訊衛星之間。它叫 Luch，也稱 Olymp-K。Intelsat General 當時的總裁說：「這不是正常行為，我們很擔心。」

依 CSIS 的整理，2017 年 7 月到 2020 年 12 月間，它至少停留過 16 個不同的軌道位置，先後成為約 30 顆衛星的最近鄰。

在地球同步軌道上，一顆衛星的位置幾乎可以濃縮成一個經度。停留、漂移、再停留，每一次都只是經度曲線上的一個轉折。在一條長達數年、轉折不斷的曲線上，哪一個轉折才算真正「不尋常」？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 9 章　統計層：判斷「多不尋常」

1️⃣ 先問「跟誰比」
同樣的變化，發生在長期穩定的衛星、剛部署的衛星，或持續補償阻力的衛星身上，意義可能完全不同。統計層至少要區分三種基準：自身歷史、同儕族群、物理預期。三者都不是真值。

2️⃣ 四條通道互補，但不是四倍證據
CUSUM 累積持續偏離，BOCPD 估計變點可能性，SSA 分離趨勢，穩健 MAD 提供離群尺度。單一方法容易受雜訊觸發，所以在正式報表的流程中，要 2 種以上方法在 48 小時內同時觸發，才算一類輔助證據，而且只影響證據等級。規則層沒標記、但統計層看到「每步都未達門檻、合計已超過」的變化，會另列為低置信複核項；這類項目誤報少，但只補回不到 3% 的規則層漏偵。

3️⃣ 分數不是機率
單一統計方法不足以撐起大型事件的召回：驗收口徑下，最佳單一方法 CUSUM 的大型事件召回為 0.437，融合評分器為 0.970；只取有真值涵蓋的期間時，分別是 0.292 與 0.643。0.9 的分數只表示值得優先覆核，不表示真實機率是 90%。

4️⃣ 方法學錯誤也值得保留
本章的相位殘差案例曾發現：磁暴週觸發率 75.0%，平靜週只有 6.4%。但換成強度更高的 2026-07-04 磁暴，觸發率只有 1.4%，與平靜週沒有差別。較合理的解讀是那一天有資料處理或編目層面的特殊事件，磁暴敏感性應視為存疑。

統計分數再高、經度或相位曲線轉折再明顯，也只表示偏離常態，不等於機動已確認，更不等於敵意或違規。

🔗 線上免費閱讀第 9 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=09

#太空態勢感知 #SpaceSituationalAwareness #SSA #異常偵測 #AnomalyDetection #變點偵測 #ChangePointDetection #地球同步軌道 #太空安全 #台灣太空

---

## English post

In spring 2015, a Russian satellite moved into the gap between two international communications satellites in geostationary orbit. It was called Luch, also known as Olymp-K. Intelsat General's president at the time called it abnormal behavior and said the company was concerned.

According to CSIS, between July 2017 and December 2020 it parked at no fewer than 16 different orbital positions, becoming the nearest neighbor of about 30 satellites.

In geostationary orbit, a satellite's position nearly collapses into a single longitude. Park, drift, park again: each move is just a bend in a longitude curve. On a curve that bends again and again over years, which bend is truly "unusual"?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 9: The Statistical Layer: Judging "How Unusual"

1️⃣ First ask: compared with what?
The same change means different things for a long-stable satellite, a newly deployed one, or one that constantly compensates for drag. The statistical layer needs at least three baselines: the satellite's own history, its peer group, and physical expectation. None of them is ground truth.

2️⃣ Four channels complement each other; they are not four times the evidence
CUSUM accumulates persistent deviation, BOCPD estimates change-point likelihood, SSA separates trend, and robust MAD gives an outlier scale. A single method fires on noise easily, so in the formal report pipeline two or more methods must fire within 48 hours to count as one auxiliary signal, and even then it only affects the evidence grade. Changes the rule layer missed, where no single step crossed the threshold but the total did, are listed separately as low-confidence review items; these raise few false alarms but recover less than 3% of what the rule layer misses.

3️⃣ A score is not a probability
No single statistical method carries large-event recall on its own: on the acceptance basis, the best single method, CUSUM, reaches 0.437 large-event recall versus 0.970 for the fusion scorer; restricted to periods covered by ground truth, the figures are 0.292 and 0.643. A score of 0.9 means "review this first," not a 90% chance that it happened.

4️⃣ Methodological mistakes are worth keeping
The chapter's phase-residual case once found a 75.0% trigger rate during a geomagnetic-storm week versus 6.4% in a quiet week. But a stronger storm on 2026-07-04 produced only 1.4%, no different from the quiet week. The more plausible reading is that something happened in data processing or cataloging that day; the storm sensitivity should be treated as doubtful.

However high a statistical score, and however sharp a bend in a longitude or phase curve, it only marks a departure from normal. It is not a confirmed maneuver, let alone evidence of hostility or a violation.

🔗 Read Chapter 9 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=09

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #AnomalyDetection #ChangePointDetection #GEO #SpaceSecurity #Taiwan
