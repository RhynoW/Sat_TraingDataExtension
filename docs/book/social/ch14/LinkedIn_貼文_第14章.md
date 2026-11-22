# 第 14 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第14章_機動時刻偵測不只知道有還知道何時_單章.pdf，13 頁：封面、扉頁、版權頁、第 14 章 9 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 14 章　機動時刻偵測：不只知道「有」，還知道「何時」」／"Chapter 14: Maneuver Timing Detection: Knowing Not Just "Whether," but "When""。檔案 22.7 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（章首學習目標頁圖為 NASA S64-03507 反相處理，照片 14-1 為 NASA 公有領域圖片，圖 14-1 為本專案案例集 Case 15 匯出圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=14
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=14

內容依據：全部取自第 14 章 v1.3 正文（已依 TASA 結案報告更新：MEME 比對的時刻中位誤差 2.74 小時與 86.9% 落在 8 小時內、STARLINK-37471 推力弧起點約 1.5 小時、R7 的 TLE 空窗規則與 SJ-26 事件、連續機動段與 STARLINK-4314、R7 流程中候選事件只由 L1 決定）與本章外部事件來源，未新增事實。

---

## 中文貼文內容

2020 年 7 月 16 日，歐洲太空總署的冰層觀測衛星 CryoSat-2 點燃推力器，持續將近 600 秒。這是一場兩週行動的開端：把軌道半長軸提高 887 公尺，讓它和 NASA 的 ICESat-2 週期性重疊，大約每 1.5 天在同一處相遇一次。

887 公尺被拆成 14 次機動，總共只用掉 0.48 公斤燃料。平均下來，每次只抬高幾十公尺。

只有公開 TLE 的旁觀者，能把這 14 次點火一一找出來嗎？還是只會看到一條緩緩上升、分不清起點和終點的曲線？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 14 章　機動時刻偵測：不只知道「有」，還知道「何時」

1️⃣「有機動」和「何時機動」是兩個問題
本書把輸出分成三層：事件存在、事件時間窗、burn epoch（估計的點火時刻）。三者不能互相替代。依結案報告的 R7 規則，事件跨越 7 天以上的 TLE 空窗時，只能測到淨變化、無法定位時間，證據等級最高 E2；較短的空窗也只能說變化落在空窗內，例如 SJ-26 於 2026-11-09 的事件落在 5.3 天的空窗裡。

2️⃣ 時刻能抓多準，要看拿什麼對照
結案報告以逐分鐘 MEME 精密星曆比對：TLE 判定的機動時刻中位誤差 2.74 小時，86.9% 落在 8 小時內。用精密星曆分析 STARLINK-37471 的推力弧，起點可定位到約 1.5 小時。這些數字只適用於 Starlink 與 MEME 真值，不能外推到其他衛星。

3️⃣ 推力向量反演：沿軌幾乎完美
Case 15 以 IDS/DORIS 營運方認證的 ΔV 真值逐筆核對。不受鄰近機動污染的乾淨子集（n=207），沿軌 ΔV 反解與真值相關係數 r=0.942，中位誤差 2.4 mm/s；其中脈衝式化學推進的 CryoSat-2（n=166）達 r=0.975。

4️⃣ 三種失效，各有原因
・垂直軌道面分量：r≈0.00，中位誤差 39.1 mm/s，而真實傾角變化中位數只有 0.2 mm/s，低於 TLE 本身的雜訊。這是物理限制，不是演算法問題。
・鄰近機動污染：SWOT 有 41% 的事件間隔小於 7 天，相關係數掉到 r=0.512。
・電推連續推力：推力攤在數十圈軌道上，沒有單一階躍可反解，套用單步假設會系統性低估。R7 改以「連續機動段」判讀，例如 STARLINK-4314 的 26 天、累計 −83.8 公里降軌列為 E3；但這回答的是「在哪一段」，不是單次點火時刻。

反演結果很好，不代表所有推進方式都適用。時間戳與 ΔV 估計值描述的是一次偏離常態的軌道變化；它不等於機動已確認，更不等於敵意或違規。

🔗 線上免費閱讀第 14 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=14

#太空態勢感知 #SpaceSituationalAwareness #SSA #衛星機動 #軌道力學 #負面結果 #太空安全 #台灣太空

---

## English post

On July 16, 2020, ESA's CryoSat-2 fired its thrusters for nearly 600 seconds, starting a two-week campaign to raise its semi-major axis by 887 m so it would line up with NASA's ICESat-2 about every 1.5 days.

The 887 m was split into 14 maneuvers, using 0.48 kg of fuel. Each raised the orbit by only a few tens of meters.

With only public TLEs, could you pick out those 14 burns? Or would you just see a slowly rising curve with no clear start or end?

📘 National Security from Satellite Orbits: Foundations of Space Situational Awareness
Chapter 14: Maneuver Timing Detection: Knowing Not Just "Whether," but "When"

1️⃣ "Was there a maneuver?" and "When?" are different questions
The book separates event existence, event time window, and burn epoch (the estimated burn time). Under the final report's R7 rule, an event spanning a TLE gap of 7+ days yields a net change but no timing, capped at evidence level E2. SJ-26's 2026-11-09 event can only be placed inside a 5.3-day gap.

2️⃣ Timing precision depends on the reference
Against minute-by-minute MEME precise ephemerides, TLE-derived maneuver times had a median error of 2.74 h, 86.9% within 8 h. For STARLINK-37471, precise ephemerides located the thrust-arc start to about 1.5 h. These apply only to Starlink with MEME truth.

3️⃣ Thrust-vector inversion: near-perfect along-track
Case 15 checks against operator-certified IDS/DORIS ΔV logs. On the clean subset (n=207), TLE-inverted along-track ΔV correlates with truth at r=0.942, median error 2.4 mm/s; CryoSat-2 alone (impulsive chemical propulsion, n=166): r=0.975.

4️⃣ Three failure modes, each with a cause
• Cross-track: r≈0.00, median error 39.1 mm/s, while true inclination changes have a median of 0.2 mm/s, below TLE noise. A physical limit, not an algorithm problem.
• Neighboring burns: 41% of SWOT's events are under 7 days apart; r drops to 0.512.
• Continuous electric thrust: no single step to invert, so a single-impulse assumption underestimates. R7 reads these as "continuous maneuver segments" (e.g. STARLINK-4314's 26-day, −83.8 km descent, rated E3), which answers "which stretch," not "which burn."

Good inversion results do not cover every propulsion type. A timestamp and ΔV estimate describe an orbit change that departed from normal, not a confirmed maneuver, let alone hostility or a violation.

🔗 Read Chapter 14 free online (Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=14

English edition: AI-assisted translation; the Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #SatelliteManeuver #Astrodynamics #NegativeResults #SpaceSecurity #Taiwan
