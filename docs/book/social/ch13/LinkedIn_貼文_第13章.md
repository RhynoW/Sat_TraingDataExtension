# 第 13 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第13章_從單星監測到星系級分析_單章.pdf，13 頁：封面、扉頁、版權頁、第 13 章 9 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 13 章　從單星監測到星系級分析」／"Chapter 13: From Single-Satellite Monitoring to Constellation-Level Analysis"。檔案 21.5 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（圖 13-1、13-2 為本專案案例集 Case 6 匯出圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=13
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=13

內容依據：全部取自第 13 章 v1.3 正文（已依 TASA 結案報告更新：三項星系級分析的適用星系、軌道面分群方式、結案報告 Starlink 快照 7 個異常面、千帆 2026 年 7 月入軌事件、R7 流程中星系級分析的角色）與本章外部事件來源，未新增事實。

---

## 中文貼文內容

2014 年 8 月 22 日，聯盟號從法屬圭亞那升空，載著伽利略導航系統的第五、第六顆衛星。兩顆衛星都分離了，但追蹤資料顯示，它們不在該去的地方：目標是傾角 55 度、半長軸 29,900 公里的圓軌道，實際到達的是傾角 49.8 度、半長軸 26,200 公里的橢圓軌道。

整個軌道面歪了 5 度。事後調查指出，Fregat 上面級裡一個支架讓推進劑管線太靠近冷氦管線，管線被凍住，姿態控制推力器失效。

如果手上只有公開 TLE，看著星座裡兩個傾角明顯不合群的點，要怎麼判斷這是刻意的機動，還是一場沒有人想要的意外？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 13 章　從單星監測到星系級分析

1️⃣ 星系級分析不是把單星結果加總
它問的是：整個星系裡，有沒有需要用群體行為來解釋的訊號？本書分三種基準分開檢驗：軌道面一致性（同面衛星的傾角變化是否異常分散）、批量機動（是否異常多顆衛星同一天一起動）、隊形相位（同面衛星間距是否跑掉）。依結案報告，三項都已建置，用於 Starlink、OneWeb、千帆、遙感、高分、吉林。

2️⃣ 沒有觸發，也是結果
Case 6 以 2026-10-13 至 11-12 的 Starlink 公開 TLE（11,234 顆、828,374 筆）即時計算：單日機動最多 494 顆，門檻 K 約 600，批量事件日 0 天。案例的判讀是，Starlink 的電推機動是持續、分散的個別站位保持，不是全星系同步動作。這個負面結果照實保留，不改寫成成功；但未觸發也不等於沒有異常。

3️⃣ 抓到的異常，成因要另外核對
同一資料窗，228 個軌道面中有 3 個傾角變化異常分散，227 個軌道面中有 290 顆相位離群。結案報告另一個快照標記 7 個異常面，核對後皆對應新批次部署後的調整期。這可作為佐證，但兩個資料窗不同，數字不可互換，也不能代替本資料窗的核對。

4️⃣ 群體行為，常常是正常交接
Iridium 換代時逐槽替換，同一軌道面內成對出現「新星就位、舊星離開」，只看相位離群，很容易把正常交接當成隊形跑掉。SpaceX 2024 年讓約 100 顆早期 Starlink 陸續離軌，分散在數月內，未必會在單日衝過門檻。千帆背景高，2026 年 7 月入軌期間單日 82、91 顆仍低於門檻 113，未觸發；同樣規模放在基線接近零的星系就會觸發。

群體指標越過門檻，代表的是一整批衛星偏離常態；它不等於協同機動已確認，更不等於敵意或違規。

🔗 線上免費閱讀第 13 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=13

#太空態勢感知 #SpaceSituationalAwareness #SSA #巨型星系 #MegaConstellation #Starlink #負面結果 #太空安全 #台灣太空

---

## English post

On August 22, 2014, a Soyuz lifted off from French Guiana carrying the fifth and sixth satellites of Europe's Galileo navigation system. Both separated, but tracking showed they were not where they should be: the target was a circular orbit at 55° inclination and a semi-major axis of 29,900 km; what they reached was an elliptical orbit at 49.8° and 26,200 km.

The whole orbital plane was off by 5°. The inquiry found that a bracket in the Fregat upper stage put a propellant line too close to a cold helium line; the line froze and the attitude-control thrusters failed.

With only public TLEs, looking at two points in a constellation whose inclinations clearly don't fit, how would you tell a deliberate maneuver from an accident nobody wanted?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 13: From Single-Satellite Monitoring to Constellation-Level Analysis

1️⃣ Constellation-level analysis is not a sum of single-satellite results
It asks whether anything in the whole constellation needs group behavior to explain it. The book tests three baselines separately: orbital-plane consistency (are inclination changes within a plane abnormally spread?), batch maneuvers (did an abnormally large number of satellites move on the same day?), and formation phase (has spacing within a plane drifted?). Per the final report, all three are built and applied to Starlink, OneWeb, Qianfan, Yaogan, Gaofen, and Jilin.

2️⃣ Not triggering is also a result
Case 6 computed live on public Starlink TLEs for 2026-10-13 to 11-12 (11,234 satellites, 828,374 TLEs): the busiest day had 494 satellites maneuvering, the threshold K was about 600, and there were 0 batch event days. The case reads this as Starlink's electric-propulsion maneuvers being continuous, distributed station-keeping by individual satellites, not constellation-wide synchronized action. The negative result is kept as it is, not rewritten as a success; but not triggering does not mean nothing is anomalous.

3️⃣ Anomalies found still need their causes checked
In the same window, 3 of 228 orbital planes showed abnormally spread inclination changes, and 290 satellites across 227 planes were phase outliers. Another snapshot in the final report flagged 7 anomalous planes, all of which, on checking, matched adjustment periods after new-batch deployments. That is supporting evidence, but the two windows differ, the figures are not interchangeable, and it cannot substitute for checking this window.

4️⃣ Group behavior is often a normal handover
When Iridium replaced its fleet slot by slot, each plane showed paired "new satellite in, old satellite out" moves; looking only at phase outliers, a normal handover is easy to mistake for a formation drifting. When SpaceX deorbited about 100 early Starlinks in 2024, spread over months, that need not cross a single-day threshold. Qianfan's background is high: during its July 2026 orbit-raising, 82 and 91 satellites a day still stayed below its threshold of 113 and nothing triggered; the same numbers in a constellation with a near-zero baseline would have.

A group indicator crossing its threshold means a whole batch of satellites departed from normal. It is not a confirmed coordinated maneuver, let alone evidence of hostility or a violation.

🔗 Read Chapter 13 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=13

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #MegaConstellation #Starlink #NegativeResults #SpaceSecurity #Taiwan
