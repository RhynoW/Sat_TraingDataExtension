# 第 8 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第08章_規則層讓每一個警報都有理由_單章.pdf，14 頁：封面、扉頁、版權頁、第 8 章 10 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 8 章　規則層：讓每一個警報都有理由」／"Chapter 8: The Rule Layer: A Reason for Every Alert"。檔案 21.8 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（圖 8-1 為本專案研究圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=08
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=08

內容依據：全部取自第 8 章 v1.3 正文（已依 TASA 結案報告更新：R7 的 P1–P6、L1 嚴格真值評估），以及本章外部事件來源，未新增事實。案例集舊實驗數字（26.9%、57.6% 等）與 R7 評估屬不同規則版本與評估單元，貼文只引用 R7 數字。

---

## 中文貼文內容

1980 年 6 月 3 日，NORAD 電腦送出的例行訊息裡，記錄飛彈發射數的欄位平時是一排零。那天，部分的「0」被換成了「2」：先是 2 枚，再來 200 枚潛射飛彈來襲。

戰略空軍司令部命令轟炸機組員登機、發動引擎。讓事情停下來的是另一組資料：飛彈預警感測器什麼也沒看到。五角大廈把肇因歸於一顆 46 美分的故障積體電路，以及「訊息設計不良」。

一個欄位從 0 變成 2，就讓轟炸機發動了引擎。一條警報規則，要怎麼替自己的判斷留下可檢查的理由？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 8 章　規則層：讓每一個警報都有理由

1️⃣ 觸發、抑制、品質守門，分開記錄
規則層把「為什麼這筆資料值得看」寫成可檢查的條件。觸發規則問訊號是否超過門檻；抑制規則問有沒有已知原因應降低信心；品質守門問資料夠不夠支持判斷。三者若寫進同一個旗標，日後就分不出系統沒告警，是因為物理條件、資料品質，還是門檻設計。

2️⃣ 門檻不是單一數字
半長軸的判定門檻，是高度門檻（P2：400 公里約 2.0 公里，700 公里以上取 0.4 公里）依序乘上太陽活動倍率（P5，200 sfu 時 ×1.6）與軌道族群倍率（P6）的「有效門檻」。P1 抑制大氣阻力造成的單調小步衰減，P4 把超過門檻的轉換連同其後 2 筆一起標記。「自適應」不等於「自動正確」。

3️⃣ 驗證後沒有作用的規則，就拿掉
P3（高阻力輔助抑制）與升交點赤經殘差標記，經大樣本逐條消融與福衛七號精密真值驗證：P3 對召回與誤報皆無作用，升交點赤經殘差只增加誤報，現行流程都不納入。

4️⃣ 規則層的召回有限，這也是分層的理由
以嚴格真值評估現行規則：Starlink 真值召回 0.322，無推進的火箭箭體上誤報每千星日 0.16 件。比較五種規則組合，召回都在 0.31–0.33 之間，偏低的主因在門檻與小幅機動，與怎麼組合無關。規則層的強項是每個標記都說得出理由；看不到的部分，要靠其他通道與人工複核補上。

ESA 曾表示，一顆典型低軌衛星每週收到數百則交會警報，真正需要分析師細查的約兩則。規則層的價值，也在於讓人只看該看的那幾則。

規則觸發只代表這筆資料偏離常態、值得覆核，不等於機動已確認，更不等於敵意或違規。

🔗 線上免費閱讀第 8 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=08

#太空態勢感知 #SpaceSituationalAwareness #SSA #可解釋AI #ExplainableAI #TLE #異常偵測 #福衛七號 #太空安全 #台灣太空

---

## English post

On June 3, 1980, a routine NORAD computer message carried a field for the number of detected missile launches, normally a row of zeros. That day some of the zeros became twos: first 2, then 200 submarine-launched missiles inbound.

Strategic Air Command ordered bomber crews to their aircraft and engines started. What stopped it was a second set of data: the missile warning sensors saw nothing. The Pentagon blamed a failed 46-cent integrated circuit and "faulty message design."

One field changing from 0 to 2 was enough to start bomber engines. How can an alert rule leave a checkable reason for its own judgment?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 8: The Rule Layer: A Reason for Every Alert

1️⃣ Record triggers, suppressions, and quality gates separately
The rule layer turns "why is this data worth a look" into checkable conditions. A trigger asks whether a signal crosses a threshold; a suppression asks whether a known cause should lower confidence; a quality gate asks whether the data can support a judgment. Fold all three into one flag, and you can no longer tell whether a missing alert came from physics, data quality, or threshold design.

2️⃣ A threshold is not a single number
The semi-major-axis threshold is an "effective threshold": the altitude threshold (P2: about 2.0 km at 400 km, 0.4 km above 700 km) multiplied by a solar-activity factor (P5, ×1.6 at 200 sfu) and an orbit-family factor (P6). P1 suppresses small monotonic drag decay; P4 flags a threshold-crossing transition together with the next 2. "Adaptive" does not mean "automatically right."

3️⃣ If validation shows a rule does nothing, remove it
P3 (an auxiliary high-drag suppression) and a RAAN-residual flag were tested by large-sample rule-by-rule ablation and against FORMOSAT-7 precise-orbit truth: P3 changed neither recall nor false alarms, and the RAAN residual only added false alarms. The current pipeline uses neither.

4️⃣ The rule layer's recall is limited, which is why there are layers
Against strict ground truth, the current rules reach 0.322 recall on Starlink and 0.16 false alarms per 1,000 satellite-days on rocket bodies, which cannot maneuver. Five rule combinations all land between 0.31 and 0.33 recall; the low recall comes from thresholds and small maneuvers, not from how rules are combined. The rule layer's strength is that every flag can state its reason; what it cannot see must be covered by other channels and human review.

ESA has said a typical LEO satellite receives hundreds of conjunction alerts a week, of which about two need an analyst's detailed look. Part of a rule layer's value is letting people look only at the ones that matter.

A rule firing means only that the data departs from normal and deserves review. It is not a confirmed maneuver, let alone evidence of hostility or a violation.

🔗 Read Chapter 8 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=08

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #ExplainableAI #TLE #AnomalyDetection #FORMOSAT7 #SpaceSecurity #Taiwan
