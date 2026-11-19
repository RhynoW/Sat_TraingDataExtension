# 第 4 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第04章_衛星機動的物理與任務邏輯_單章.pdf，15 頁）可用「文件」上傳，文件標題填「第 4 章　衛星機動的物理與任務邏輯」／"Chapter 4: The Physics and Mission Logic of Satellite Maneuvers"。檔案 23.5 MB，在 LinkedIn 文件 100 MB 上限內。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=04
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=04

內容依據：全部取自第 4 章修訂版正文與本章外部事件來源，未新增事實。主案例 Case 29（孟加拉衛星人工迴避）在本書列為證據等級 C、媒體轉述且未經查證，貼文已註明。

---

## 中文貼文內容

2019 年 9 月 2 日，ESA 的 Aeolus 衛星連續點火三次，把軌道抬高約 350 公尺，避開 Starlink 44。

ESA 前一天做最終決定時，碰撞機率約千分之一，是它門檻的十倍。ESA 事前聯絡過 Starlink 團隊，對方回覆不打算採取行動；SpaceX 事後表示，機率升高後，呼叫系統的程式錯誤讓值班人員沒看到後續郵件。這是 ESA 首次為了避開巨型星座衛星而機動，雙方協調靠的是電郵往來。

問題是：從地面只看得到軌道資料的人，要怎麼知道這三次點火是在躲避，而不是在做別的事？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 4 章　衛星機動的物理與任務邏輯

這一章談三件事：

1️⃣ 軌道變化不等於異常
J2 攝動、大氣阻力、日月引力、太陽輻射壓，都會讓沒有點火的衛星軌道改變。半長軸下降，可能是阻力、主動降軌或離軌；上升，可能是抬軌、批量爬升或位置維持。只看半長軸，判斷不了。

2️⃣ 避碰的決策鏈常被壓縮在一天內
2020 年太空站為一塊 H-2A 整流罩碎片緊急抬軌，從預警到點火不到一天；2022 年 Sentinel-1A 為一塊 Cosmos 1408 碎片改變軌道 140 公尺，預警不到 24 小時，規劃只花數小時。本章主案例是 2026 年孟加拉衛星在沒有 VCM、也沒有商用避碰工具下的人工迴避（這部分只有媒體轉述營運方說法，本書未獨立查證）。沒有協方差，就算不出可信的碰撞機率，人工判斷可能過早、過晚或方向錯誤。

3️⃣ 國安意涵看的是目的與可解釋性
正常維持可預期、可歸因；異常接近可能涉及交會、服務、偵察或非合作行為；停止維持可能是壽命末期，也可能是任務失效的早期徵兆。以福衛七號 FS7-3 為例：最後一次機動在 2025 年 5 月，此後 14 個月沒有軌道維持，高度由 549 公里降到 536.5 公里。公開 TLE 看得到的是「停止軌道維持」這個事實；成因是推進異常、推進劑耗盡或除役規劃，要以營運方遙測核對。

偵測到偏離常態，不等於機動已確認；即使確認是機動，也不等於敵意或違規。

🔗 線上免費閱讀第 4 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=04

#太空態勢感知 #SpaceSituationalAwareness #SSA #碰撞避讓 #太空交通管理 #衛星機動 #福衛七號 #太空安全 #台灣太空

---

## English post

On September 2, 2019, ESA's Aeolus satellite fired its thrusters three times, raising its orbit by about 350 m to avoid Starlink 44.

When ESA made its final decision the day before, the collision probability was about 1 in 1,000, ten times its threshold. Starlink had earlier said it had no plans to act; SpaceX later said a paging-system bug kept its on-call operator from seeing follow-up emails. It was the first time ESA had maneuvered to avoid a mega-constellation satellite, and the two sides coordinated by email.

The question: if all you can see from the ground is orbital data, how do you know those three burns were an avoidance maneuver and not something else?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 4: The Physics and Mission Logic of Satellite Maneuvers

Three takeaways:

1️⃣ An orbital change is not an anomaly
J2, drag, lunisolar gravity and solar radiation pressure all change orbits without any thruster firing. A falling semi-major axis may mean drag, a deliberate lowering or deorbiting; a rising one may mean orbit raising, a batch climb or station-keeping. The semi-major axis alone cannot tell you which.

2️⃣ The avoidance decision chain is often compressed into a day
In 2020, the ISS boosted its orbit to avoid a fragment of an H-2A fairing, with less than a day from warning to burn. In 2022, Sentinel-1A changed its orbit by 140 m to avoid a Cosmos 1408 fragment, with under 24 hours of warning and only hours of planning. The chapter's main case is a 2026 manual avoidance by a Bangladeshi satellite without VCMs or commercial tools (known only from media reports of the operator's statements; not independently verified in the book). Without covariance, no credible collision probability can be computed, and a manual call may come too early, too late, or in the wrong direction.

3️⃣ Security implications depend on purpose and explainability
Routine station-keeping is predictable and attributable. An unusual close approach may involve rendezvous, servicing, reconnaissance or non-cooperative behavior. A halt in station-keeping may mean end of life, or an early sign of mission failure. Take FORMOSAT-7 FS7-3: its last maneuver was in May 2025; for the next 14 months there was no orbit maintenance, and its altitude fell from 549 km to 536.5 km. Public TLEs show the fact that maintenance stopped; whether the cause is a propulsion fault, propellant exhaustion or planned retirement has to be checked against the operator's telemetry.

A departure from normal is not a confirmed maneuver, and a confirmed maneuver is not evidence of hostile intent.

🔗 Read Chapter 4 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=04

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #CollisionAvoidance #SpaceTrafficManagement #SatelliteManeuvers #FORMOSAT7 #SpaceSecurity #Taiwan
