# 第 12 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第12章_再入守門知道什麼時候不該用模型_單章.pdf，17 頁：封面、扉頁、版權頁、第 12 章 13 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 12 章　再入守門：知道什麼時候不該用模型」／"Chapter 12: The Reentry Gate: Knowing When Not to Use the Model"。檔案 23.5 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（照片 12-1～12-3 為 NASA 公有領域圖片，圖 12-1 為本專案案例集匯出圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=12
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=12

內容依據：全部取自第 12 章 v1.3 正文（已依 TASA 結案報告更新：再入守門條件、結案報告 6 案例驗證、GEO／MEO 在 App 摘要與 R7 報表中的不同路徑、千帆 2026 年 7 月入軌事件）與本章外部事件來源，未新增事實。

---

## 中文貼文內容

2025 年 5 月 10 日 06:04 UTC，德國 TIRA 雷達又一次看見它：1972 年蘇聯金星探測任務 Kosmos 482 的一部分，約半噸重，在地球軌道上繞了 53 年。下一圈預定 07:32 飛過，雷達照預定方向搜尋，什麼也沒有。

它已經再入了，但確切的時間與地點，至今沒有被觀測證實。EU SST 說 06:04 ±20 分鐘，ESA 事前給 06:37 ±197 分鐘，Aerospace 公司 06:29 ±120 分鐘，美方事後通報 05:32 ±12 分鐘，俄方稱 06:24、落在印度洋。

五個機構，五個答案。只靠公開 TLE，系統又能守到哪裡？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 12 章　再入守門：知道什麼時候不該用模型

1️⃣ 守門、預測、確認，是三件事
再入守門不預測衛星何時墜落，它判斷的是：這個軌道與資料條件，還適合用模型判讀機動嗎？依結案報告，取最近 45 天資料，近地點低於 150 公里，或低於 350 公里且每天下降超過 2 公里，就判為自然再入，機動數輸出為 0。ERS-2 的再入預報窗口要到最後一天才縮到 ±0.55 小時；那是再入預測的工作，不是守門的工作。

2️⃣ 能信到哪裡，要分級寫清楚
Starlink LEO 已驗證；再入判定有特殊處理但驗證有限；GEO／MEO 只有程式路徑，3,422 顆中只有 2 顆做過個案軌跡核對；Galileo 是獨立支線，未整合；HEO 正常橢圓軌道階段已知不適用；太陽同步只有初步佐證。「有程式路徑」不等於「已驗證」。

3️⃣ 全對，也還是「驗證有限」
58 顆真實衛星中，16 顆確認再入全部判對，42 顆確認安靜也全部判對。但正類只有 16 顆，再入召回的 Wilson 95% 信賴區間下界只有 80.6%；真值又是本專案自建的物理判準，不是第三方獨立真值。所以這一級維持「驗證有限」，而且檢驗的是守門判定，不是再入時間。

4️⃣ 背景太吵，批量機動會被淹沒
批量判定的門檻隨背景自適應。OneWeb 背景約每天 1 顆，同時注入 2 顆就被標記；千帆背景約每天 126 顆，要 126 顆以上才觸發。結案報告也記錄，2026 年 7 月千帆入軌期間，單日顯著機動升到 82、91 顆，仍低於當時門檻 113，未觸發。兩組數字的日期與口徑不同，不宜合併比較，但方向一致：數十顆衛星同時機動，仍可能被判為正常。

守門放行之後，模型標出的仍只是「偏離常態」；守門觸發，也不等於再入已確認。兩者都不等於敵意或違規。

🔗 線上免費閱讀第 12 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=12

#太空態勢感知 #SpaceSituationalAwareness #SSA #再入 #Reentry #模型適用域 #模型驗證 #太空安全 #台灣太空

---

## English post

At 06:04 UTC on May 10, 2025, Germany's TIRA radar saw it once more: part of Kosmos 482, a 1972 Soviet Venus mission, about half a tonne, which had circled Earth for 53 years. On its next pass, due at 07:32, the radar searched where it should be and found nothing.

It had reentered, but the exact time and place have never been confirmed by observation. EU SST said 06:04 ±20 minutes; ESA's advance estimate was 06:37 ±197 minutes; The Aerospace Corporation said 06:29 ±120 minutes; the US post-event notice said 05:32 ±12 minutes; Roscosmos said 06:24, over the Indian Ocean.

Five agencies, five answers. With public TLEs alone, how far can a system's safeguards reach?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 12: The Reentry Gate: Knowing When Not to Use the Model

1️⃣ Gating, prediction, and confirmation are three different things
The reentry gate does not predict when a satellite will fall. It asks: given this orbit and these data, is the model still fit for judging maneuvers? Per the final report, using the last 45 days of data, a perigee below 150 km, or below 350 km while dropping more than 2 km a day, is classed as natural reentry and the maneuver count is set to 0. ESA's reentry window for ERS-2 narrowed to ±0.55 hours only on the final day; that is the job of reentry prediction, not of the gate.

2️⃣ Spell out, tier by tier, how far the system can be trusted
Starlink LEO: validated. Reentry: special handling, limited validation. GEO/MEO: a code path only; of 3,422 objects, just 2 have had their tracks checked case by case. Galileo: a separate branch, not integrated. HEO in its normal elliptical phase: known not to apply. Sun-synchronous: preliminary support only. Having a code path is not the same as being validated.

3️⃣ All correct, and still "limited validation"
Among 58 real satellites, all 16 confirmed reentries and all 42 confirmed quiet satellites were classified correctly. But with only 16 positives, the lower bound of the Wilson 95% interval for reentry recall is just 80.6%, and the ground truth is a physical criterion this project defined itself, not independent third-party truth. So the tier stays at "limited validation," and what was tested is the gate decision, not reentry timing.

4️⃣ When the background is noisy, mass maneuvers get drowned out
The mass-maneuver threshold adapts to the background. OneWeb's background is about 1 satellite a day, so injecting 2 at once is flagged; Qianfan's is about 126 a day, so it takes 126 or more to trigger. The final report also records that during Qianfan's orbit-raising in July 2026, daily significant maneuvers rose to 82 and 91, still below the threshold of 113 at the time, and nothing triggered. The two sets of figures differ in date and basis and should not be combined, but they point the same way: dozens of satellites maneuvering at once can still be judged normal.

Once the gate lets a satellite through, what the model flags is still only a departure from normal; when the gate triggers, that is not a confirmed reentry either. Neither is evidence of hostility or a violation.

🔗 Read Chapter 12 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=12

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #Reentry #ModelValidation #SpaceSecurity #Taiwan
