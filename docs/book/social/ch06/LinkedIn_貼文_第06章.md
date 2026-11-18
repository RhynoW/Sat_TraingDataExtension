# 第 6 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第06章_追蹤缺口資料品質與假警報_單章.pdf，12 頁）可用「文件」上傳，文件標題填「第 6 章　追蹤缺口、資料品質與假警報」／"Chapter 6: Tracking Gaps, Data Quality, and False Alarms"。檔案 21.2 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=06
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=06

內容依據：全部取自第 6 章修訂版正文（Case 8 與本章外部事件來源），未新增事實。資料庫數字是 2026-11-17 的單次查詢快照，貼文已註明。

---

## 中文貼文內容

2018 年 12 月，一枚獵鷹九號一次送上 64 顆衛星，其中近 50 顆是外形相近的立方衛星。到了 2019 年 4 月下旬，營運方表示仍有 19 顆待識別，另有 4 顆下落不明。

軌道已經在目錄裡，名字卻還沒對上。若一組 TLE 掛錯了編號，下游的偵測再準，也會把 A 的動作算到 B 頭上。

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 6 章　追蹤缺口、資料品質與假警報

這一章的核心原則是：先確認資料能支持什麼判斷，再決定演算法應輸出什麼結論。

1️⃣ 「沒有資料」有四種原因
觀測更新不足、發布延遲、匯入中斷、歷史未回補。畫面停止更新的樣子一樣，處置卻不同：入口中斷要修管線，觀測不足要標示時效限制。福衛七號一號星曾出現約 134 到 163 小時的 TLE 缺口，缺口後的第一筆跳變，被我們的初版規則誤判為機動。

2️⃣ 資料庫的建置歷史，會改變你看見的衛星歷史
本章 Case 8 起於一個問題：介面上的資料怎麼好像只從三月開始？查下去，是 2026 年三到四月的目錄擴編：29,494 個物件在這段期間首次被收錄，約占快照總量的 85%。首次出現在本地資料庫，不等於首次被觀測，更不等於發射日期；擴編前後的統計母體也不能直接比較。

3️⃣ 資料品質和事件分數分開管理
資料可不可靠，和行為是否異常，是兩個問題。低品質資料不必刪除，但不該因為數值跳得大，就得到很高的判斷信心。

口徑問題也不只出現在 TLE。SpaceX 向 FCC 申報的 Starlink 機動次數，從 13,612 次升到 25,299 次，2024 年那一期接近 5 萬次；研究者 Hugh Lewis 指出，這次翻倍主要來自 SpaceX 調低了門檻。跨期比較前，先確認口徑一致。

即使資料品質已經確認，軌道曲線的跳動也只代表偏離常態，不等於機動已確認，更不等於敵意。

🔗 線上免費閱讀第 6 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=06

#太空態勢感知 #SpaceSituationalAwareness #SSA #資料品質 #DataQuality #TLE #太空目錄 #福衛七號 #太空安全 #台灣太空

---

## English post

In December 2018, a single Falcon 9 launched 64 satellites, nearly 50 of them similar-looking CubeSats. By late April 2019, the mission operator said 19 were still unidentified and 4 were missing.

The orbits were in the catalog; the names were not yet matched. Attach a TLE to the wrong catalog number, and however good your downstream detection is, it will credit A's maneuver to B.

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 6: Tracking Gaps, Data Quality, and False Alarms

The chapter's core principle: first establish what the data can support, then decide what the algorithm should conclude.

1️⃣ "No data" has four causes
Insufficient observation updates, publication delay, ingest failure, and history never backfilled. They look the same on screen but need different fixes: a broken ingest needs pipeline repair; sparse observations need a freshness warning. FORMOSAT-7/COSMIC-2 FM1 once had a TLE gap of about 134 to 163 hours, and our first-version rule flagged the jump in the first post-gap TLE as a maneuver.

2️⃣ How your database was built changes the satellite history you see
Case 8 began with a question: why does the data seem to start only in March? The answer was a catalog expansion: 29,494 objects were first ingested in March–April 2026, about 85% of the snapshot. First appearance in a local database is not first observation, let alone launch date, and populations before and after the expansion cannot be compared directly.

3️⃣ Keep data quality and event scores separate
Whether the data is reliable and whether the behavior is unusual are two different questions. Low-quality data need not be deleted, but a big jump in it should not earn high confidence.

Definitions matter beyond TLEs. Starlink maneuvers reported by SpaceX to the FCC rose from 13,612 to 25,299 per period, and the 2024 period approached 50,000; researcher Hugh Lewis noted that the doubling came mainly from SpaceX lowering its threshold. Check that definitions match before comparing periods.

Even with data quality confirmed, a jump in an orbital curve only marks a departure from normal. It is not a confirmed maneuver, let alone evidence of hostile intent.

🔗 Read Chapter 6 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=06

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #DataQuality #TLE #SpaceCatalog #FORMOSAT7 #SpaceSecurity #Taiwan
