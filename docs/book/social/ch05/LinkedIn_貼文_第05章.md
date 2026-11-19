# 第 5 章 LinkedIn 貼文（中文／英文）：負的大氣阻力？

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第05章_大氣阻力太空天氣與假機動_單章.pdf，19 頁）可用「文件」上傳，文件標題填「第 5 章　大氣阻力、太空天氣與假機動」／"Chapter 5: Atmospheric Drag, Space Weather, and False Maneuvers"。檔案 24.8 MB，在 LinkedIn 文件 100 MB 上限內。

注意：本章 PDF 含中央氣象署的電離層圖（圖 5-1 至 5-3）。網站規定非經授權禁止轉載，本書已註明「送印前須取得中央氣象署授權」。公開發布單章 PDF 也屬轉載，建議取得授權後再上傳 PDF；貼文本身未使用這些圖。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=05
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=05

內容依據：重點放在主案例二 Case 30（負 B*），全部取自第 5 章修訂版正文，未新增事實。OneWeb 與 Kuiper 沒有真值、美方定軌程序未公開，貼文已註明。

---

## 中文貼文內容

負的大氣阻力？

TLE 裡有一個參數叫 B*，描述衛星受大氣阻力的程度。照物理，它應該是正的：阻力只會讓衛星減速。但翻開公開 TLE，會看到不少衛星的 B* 是負的。

大氣不會推衛星往前。問題出在模型：SGP4 沒有推力項。衛星持續用推力抵銷阻力時，多出來的沿軌加速度沒地方放，就被擬合進 B*，變成一個物理上不可能的負值。

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 5 章　大氣阻力、太空天氣與假機動

本章的 Case 30 做了三件事：

1️⃣ 普查
2026 年 8 月以後、高度 1,300 公里以下的近圓軌道物件，共 22,748 個，依星系與高度帶比較負 B* 的比例與 B* 的跳動幅度。

2️⃣ 用真值驗證
以 283 顆 Starlink、6,461 筆 TLE 對照 SpaceX 公開的 MEME 精密星曆。只看單筆 TLE 的 B*，判斷降軌的 AUC 為 0.913，判斷升軌只有 0.743。B* 確實藏著推力的線索，但不是一個乾淨的訊號。

3️⃣ 劃出不能用的地方
800 公里以上的碎片也有可觀的負 B*，碎片不會點火，所以高軌的負 B* 不能單獨當作推力證據，必須和同高度碎片比較。OneWeb 與 Kuiper 沒有公開精密星曆，它們的負 B* 只能間接推論；美方的定軌程序也未公開，這個機制是從結果反推的。

這對兩種人都有影響：
・做機動偵測的：把負 B* 直接當異常，會產生大量誤報；完全忽略，又會漏掉推力線索。
・用 TLE 反推熱層密度的：推進中的衛星要先排除，否則它們的 B* 量到的不是大氣。

B* 不是衛星固定不變的屬性。1979 年 Skylab 的控制團隊就曾切換低阻力與高阻力姿態，來調整再入時間。

TLE 的參數會吸收推力、姿態與擬合誤差。太空態勢感知不能只依賴單一參數。

🔗 線上免費閱讀第 5 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=05

#太空態勢感知 #SpaceSituationalAwareness #SSA #TLE #SGP4 #大氣阻力 #Starlink #電力推進 #低軌衛星 #太空安全

---

## English post

Negative atmospheric drag?

Every TLE carries a parameter called B*, which describes how strongly drag acts on a satellite. Physically it should be positive: drag only slows a satellite down. Yet plenty of public TLEs show a negative B*.

The atmosphere does not push satellites forward. The issue is the model: SGP4 has no thrust term. When a satellite uses continuous thrust to offset drag, the extra along-track acceleration has nowhere to go, so it gets fitted into B* and shows up as a physically impossible negative value.

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 5: Atmospheric Drag, Space Weather, and False Maneuvers

Case 30 in this chapter does three things:

1️⃣ A census
22,748 near-circular objects below 1,300 km since August 2026, comparing the share of negative B* and the size of B* swings by constellation and altitude band.

2️⃣ Validation against ground truth
283 Starlink satellites and 6,461 TLEs, checked against SpaceX's public MEME precise ephemerides. Using B* from a single TLE, orbit lowering is detected with an AUC of 0.913, orbit raising with only 0.743. B* does carry a thrust signal, but not a clean one.

3️⃣ Where it does not work
Debris above 800 km also shows substantial negative B*, and debris never fires a thruster. So a negative B* at high altitude is not evidence of thrust on its own; compare against debris at the same altitude. OneWeb and Kuiper publish no precise ephemerides, so their negative B* can only be inferred indirectly, and since the US orbit determination process is not public, the mechanism is inferred from the results.

Why it matters:
• For maneuver detection: treat negative B* as an anomaly and you drown in false alarms; ignore it and you miss thrust clues.
• For thermospheric density from TLEs: exclude satellites under thrust first, or their B* is not measuring the atmosphere.

B* is not a fixed property of a satellite either. In 1979, Skylab's controllers switched between low-drag and high-drag attitudes to adjust its reentry time.

TLE parameters absorb thrust, attitude and fitting error. Space situational awareness cannot rely on a single parameter.

🔗 Read Chapter 5 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=05

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #TLE #SGP4 #AtmosphericDrag #Starlink #ElectricPropulsion #LEO #SpaceSecurity
