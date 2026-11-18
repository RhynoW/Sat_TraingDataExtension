# 第 3 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第03章_低軌巨型星座的世界_單章.pdf，16 頁）可用「文件」上傳，文件標題填「第 3 章　低軌巨型星座的世界」／"Chapter 3: The World of LEO Mega-Constellations"。檔案 23.2 MB，在 LinkedIn 文件 100 MB 上限內。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=03
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=03

內容依據：全部取自第 3 章修訂版正文（Case 3 與本章外部事件來源），未新增事實。14 天的數字是固定假設下的模擬，不是實測偵測率，貼文已註明。

---

## 中文貼文內容

同樣是把軌道高度調整 1 公里，1 天完成和 14 天完成，地面看到的訊號差了十多倍。

以新書第 3 章的模擬假設（雜訊底約 19 公尺，偵測器只看相鄰兩筆 TLE 的差），1 天完成時，單步訊噪比約 52σ；拆成 14 天，每天只動數十公尺，單步訊噪比降到約 3.72σ。訊號還在，只是被稀釋了。

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 3 章　低軌巨型星座的世界

這一章以 Starlink 的真實 TLE 為主案例，談三件事：

1️⃣ 抬軌不難，站位保持才難
STARLINK-37457 剛發射後，每天爬升約 8.45 公里，6.9 天累積約 58.1 公里，換算約 440σ，1 到 2 天的資料就足以判定。進入作業高度後的站位保持，每天可能只動數十公尺，兩者在本案例的假設下相差兩到三個數量級。

2️⃣ 沒有萬能的觀測窗
要即時告警，逐點偵測器受限於每一步的訊噪比；要事後回顧，直接比較窗口起點和終點的淨位移，訊噪比可能仍然很高；要可靠抓到小型、漸進的電推機動，則需要 MEME 或精密星曆。模擬中 14 天的近似偵測率 0.929，也不等於實務的告警門檻，還要看誤報率、延遲與連續確認規則。

3️⃣ 從單星到星系
同一批發射、同一殼層的衛星常一起移動。先學會「這個星系平常怎麼動」，才看得出哪一顆偏離同儕。但偏離同儕只是需要查證的訊號，不等於敵意行為。

最近就有一個例子：2026 年 11 月 13 日 Starship 第 15 次試飛，把 26 顆 Starlink V3 送進約 275 公里的低軌道（SpaceX 公布的預定值）。這批衛星進入 TLE 目錄後的爬升階梯，正是本章要找的訊號。

🔗 線上免費閱讀第 3 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=03

#太空態勢感知 #SpaceSituationalAwareness #SSA #低軌衛星 #巨型星座 #Starlink #Starship #電力推進 #太空安全 #台灣太空

---

## English post

Raise a satellite's orbit by 1 km in one day, or spread the same 1 km over 14 days. From the ground, the signal differs by more than a factor of ten.

Under the simulation assumptions in Chapter 3 of my new book (noise floor about 19 m, a detector that only looks at the difference between consecutive TLEs), the one-day version gives a single-step signal-to-noise ratio of about 52σ. Spread over 14 days, moving only tens of meters per day, it drops to about 3.72σ. The signal is still there, just diluted.

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 3: The World of LEO Mega-Constellations

The chapter uses real Starlink TLEs as its main case. Three takeaways:

1️⃣ Orbit raising is easy to see; station-keeping is the hard part
Right after launch, STARLINK-37457 climbed about 8.45 km per day, about 58.1 km over 6.9 days, roughly 440σ. One or two days of data is enough. Station-keeping at operational altitude may move a satellite only tens of meters per day. Under this case's assumptions, the two differ by two to three orders of magnitude.

2️⃣ No observation window fits every purpose
For real-time alerts, a point-by-point detector is limited by the per-step SNR. For after-the-fact review, comparing net displacement between the start and end of the window can still give a high SNR. To reliably catch small, gradual electric-propulsion maneuvers, you need MEME or precise ephemerides. The simulated 14-day detection rate of 0.929 is not an operational alert threshold either; that also depends on false-alarm rate, latency and confirmation rules.

3️⃣ From single satellites to the constellation
Satellites from the same launch or the same shell often move together. Learn how the constellation normally behaves, and the one that departs from its peers stands out. But departing from peers is a signal to verify, not evidence of hostile intent.

A recent example: on November 13, 2026, Starship's 15th test flight placed 26 Starlink V3 satellites into a low orbit of about 275 km (SpaceX's planned value). The staircase climb these satellites will show once they enter the TLE catalog is exactly the signal this chapter looks for.

🔗 Read Chapter 3 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=03

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #LEO #MegaConstellations #Starlink #Starship #ElectricPropulsion #SpaceSecurity #Taiwan
