# 第 11 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第11章_物理作為第三方證人NRLMSIS與阻力殘差_單章.pdf，15 頁：封面、扉頁、版權頁、第 11 章 11 頁、封底；取自全書排版版 v1.3）可用「文件」上傳，文件標題填「第 11 章　物理作為第三方證人：NRLMSIS 與阻力殘差」／"Chapter 11: Physics as a Third-Party Witness: NRLMSIS and Drag Residuals"。檔案 23.2 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（照片 11-1、11-2 為 NASA 公有領域圖片，圖 11-1 為本專案案例集匯出圖）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=11
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=11

內容依據：全部取自第 11 章 v1.3 正文（已依 TASA 結案報告更新：NRLMSIS 2.1 輸入設定、0.3 km 判定與高度相依誤報、自然衰減驗證、R7 中阻力殘差的角色）與本章外部事件來源，未新增事實。

---

## 中文貼文內容

2022 年 2 月 3 日到 4 日，一場地磁暴掠過地球。約 438 公里高的 Swarm-A 衛星量到，主相期間大氣質量密度增加了 110%；約 505 公里的 GRACE-FO 量到 120%。

事後，研究者把六個大氣模型拿來重跑這場風暴，模擬出的密度增幅彼此相差最多 70%。

從 TLE 看到衛星掉得比預期快，我們習慣說「阻力殘差變大了」。可是如果「預期」本身就可能差到 70%，這個殘差裡，有多少是衛星做了什麼，又有多少是大氣模型算錯了？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 11 章　物理作為第三方證人：NRLMSIS 與阻力殘差

1️⃣ 物理模型是證人，不是裁判
阻力殘差＝觀測到的軌道變化－NRLMSIS 預期阻力造成的變化。|殘差| 超過 0.3 km 判為「阻力無法解釋」，但不直接等同推進燃燒：福衛三號（無推進）全期最大殘差 0.105 km，一顆升軌中的 Starlink 達 1.91 km。模型本身也有偏差：太陽活動高時，NRLMSIS「預期／實測」中位 1.17，福衛七號精密軌道也顯示高峰期模型偏高約 20%。

2️⃣ 預估自然衰減可以，反推大氣密度不行
425 顆衛星的 TLE 實測衰減率與 NRLMSIS 預期，相關係數 0.976；但彈道係數是逐星校準的，量級吻合有一部分是校準的結果。反過來「只用 TLE 反推密度」，Case 10 試了四個版本都未能複現目標研究：151 個阻力弧段中，反推密度與模型密度之比中位 1.00，四分位距卻是 0.39～1.24；換成精密星曆、逐星校準後，仍有約 0.62 dex（上下約 4 倍）的離散。

3️⃣ 三個根因，彼此牽連
樣本偏差：適合反推的衛星幾乎都是壽命末期、姿態失控的翻滾衛星，衰減反映的是有效面積變化，不是密度。B* 循環論證：B* 本身就是從衰減率擬合出來的，再拿它推密度，等於用答案除答案。覆蓋不足：極軌衛星只有約 13 顆，2D 密度場的空間相關只有 r = 0.42。負面結果照實記下，沒有改寫成成功。

4️⃣ 固定門檻，不是每個高度都適用
在正式報表的流程中，阻力殘差是輔助通道，只影響證據等級，不單獨產生候選事件。固定 0.3 km 門檻在 300 km 每千星日誤報 44 件、400 km 3.6 件，600 km 以上則過於保守；依高度調整的方案在樣本外驗證中都未能全面達標，目前只作方向性建議。在 15 顆非 Starlink 衛星上，它補回了 12 次規則層漏偵的點火，但安靜期誤報只有 4 項，信賴區間仍寬。

阻力殘差明顯偏離零，顯示的是偏離物理常態；磁暴期間更不能直接讀成機動。它不等於機動已確認，更不等於敵意或違規。

🔗 線上免費閱讀第 11 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=11

#太空態勢感知 #SpaceSituationalAwareness #SSA #太空天氣 #SpaceWeather #大氣阻力 #負面結果 #太空安全 #台灣太空

---

## English post

On February 3–4, 2022, a geomagnetic storm swept past Earth. At about 438 km, the Swarm-A satellite measured a 110% increase in atmospheric mass density during the main phase; at about 505 km, GRACE-FO measured 120%.

Afterward, researchers re-ran the storm through six atmospheric models. The simulated density increases differed from one another by up to 70%.

When TLEs show a satellite dropping faster than expected, we tend to say "the drag residual went up." But if the "expected" value can itself be off by 70%, how much of that residual is something the satellite did, and how much is the atmospheric model being wrong?

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 11: Physics as a Third-Party Witness: NRLMSIS and Drag Residuals

1️⃣ The physics model is a witness, not a judge
Drag residual = observed orbital change minus the change NRLMSIS predicts from drag. A |residual| above 0.3 km is labeled "not explained by drag," which is not the same as a thruster burn: FORMOSAT-3 (no propulsion) never exceeded 0.105 km, while a Starlink raising its orbit reached 1.91 km. The model has its own bias: at high solar activity the NRLMSIS predicted-to-observed ratio has a median of 1.17, and FORMOSAT-7 precise orbits also show the model running about 20% high near solar maximum.

2️⃣ Predicting natural decay works; inverting density does not
Across 425 satellites, TLE-observed decay rates correlate with NRLMSIS predictions at 0.976, but the ballistic coefficient is calibrated per satellite, so part of the agreement in magnitude comes from the calibration. Going the other way, inferring density from TLEs alone, Case 10 tried four versions and could not reproduce the target study: over 151 drag arcs, the median ratio of inferred to model density was 1.00, yet the interquartile range was 0.39–1.24. Even with precise ephemerides and per-satellite calibration, scatter stayed at about 0.62 dex, roughly a factor of 4 either way.

3️⃣ Three root causes, tangled together
Sample bias: the satellites clean enough to invert are almost all end-of-life tumblers, so their decay tracks changing effective area, not density. B* circularity: B* is itself fitted from the decay rate, so using it to infer density divides the answer by the answer. Sparse coverage: only about 13 polar-orbit satellites, giving a spatial correlation of just r = 0.42 for the 2D density field. The negative result is recorded as it is, not rewritten as a success.

4️⃣ A fixed threshold does not suit every altitude
In the formal report pipeline the drag residual is an auxiliary channel: it only affects the evidence grade and creates no candidate events on its own. The fixed 0.3 km threshold gives 44 false alarms per thousand satellite-days at 300 km and 3.6 at 400 km, and is overly conservative above 600 km. Altitude-dependent alternatives all fell short somewhere in out-of-sample tests, so they remain a directional recommendation. On 15 non-Starlink satellites it recovered 12 burns the rule layer missed, but with only 4 quiet-period false alarms, the confidence interval is still wide.

A drag residual well away from zero marks a departure from physical expectation, and during a geomagnetic storm it cannot be read directly as a maneuver. It is not a confirmed maneuver, let alone evidence of hostility or a violation.

🔗 Read Chapter 11 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=11

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #SpaceWeather #AtmosphericDrag #NegativeResults #SpaceSecurity #Taiwan
