# 第 7 章 LinkedIn 貼文（中文／英文）

使用方式：LinkedIn 不支援 Markdown，請複製「貼文內容」區塊內的純文字。
附件：單章 PDF（第07章_三層偵測架構規則統計與機器學習_單章.pdf，16 頁：封面、扉頁、版權頁、第 7 章 12 頁、封底；取自全書排版版 v1.3，全書已依 TASA 結案報告更新）可用「文件」上傳，文件標題填「第 7 章　三層偵測架構：規則、統計與機器學習」／"Chapter 7: A Three-Layer Detection Architecture: Rules, Statistics, and Machine Learning"。檔案 22.9 MB，在 LinkedIn 文件 100 MB 上限內。本章沒有中央氣象署圖片（照片 7-1 為 NASA 圖片）。

連結：
- 中文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=07
- 英文：https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=07

內容依據：取自第 7 章更新版正文（2026-11-19 依期末報告 2026-11-15 更新：R7 流程、表 13 兩種口徑、契約驗收 FPR），未新增事實。注意：HF 線上版第 7 章尚未同步更新，數字與單章 PDF 不同。

---

## 中文貼文內容

1983 年 9 月 26 日午夜過後，蘇聯中校 Stanislav Petrov 在預警掩體值班。Oko 衛星預警系統報告美國發射了飛彈，最後一共報出五枚。

Petrov 判斷是誤報。他後來說明理由：美國若要開戰，不會只發射五枚；系統剛啟用，他不完全信任；真正的攻擊，應該會有地面雷達一起確認。事後分析指出，是高空雲層反射的陽光被紅外線感測器當成了飛彈尾焰。

機器報了五次「有」，擋下警報的是對合理性的懷疑，以及對第二來源的期待。如果告警系統只有一層，誰來問那一句「這說得通嗎」？

📘《從衛星軌道論國家安全——太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測》
第 7 章　三層偵測架構：規則、統計與機器學習

1️⃣ 分層是責任分工，不是排隊投票
L1 規則層回答「是否符合已知觸發或抑制條件」，留下旗標與理由；L2 統計層（CUSUM、BOCPD、奇異譜分析、穩健 MAD）回答「有多不尋常」；L3 融合層整合多通道，支持事件排序。物理阻力殘差與再入守門是另一組可檢查的假設，不是最終裁判。

2️⃣ 事件只由規則決定，AI 只影響優先順序
正式報表中，候選事件只由 L1 規則產生；統計變點、阻力殘差與兩個機器學習模型只影響證據等級，不新增、不刪除事件。這樣每一件事件都能說明觸發原因。

3️⃣ 融合有價值，但數字要連同口徑一起讀
同一操作點下，驗收口徑的召回：隨機基準 0.044、L1 規則 0.251、L2 最佳單一方法 CUSUM 0.444、融合評分器 0.948。若負樣本只取有真值涵蓋的期間，融合評分器降為 0.472，排序不變。差距同時來自更多證據與不同決策方式，不能全部歸功於「用了 AI」。

4️⃣ 門檻是設定值，實測結果會隨資料浮動
融合告警的門檻設定在誤報率 0.05。契約驗收實測為 0.0498（4,294 個無機動時窗中誤報 214 個），判定達標；因為樣本有限，這個估計值的 95% 信賴區間是 0.044–0.057。換一組未參與訓練的衛星測試，誤報率則為 0.07015。同一個門檻換一批資料，結果就會不同，部署後仍要持續監測。

透明不等於正確：規則能逐條說明觸發理由，但門檻設得不合適，仍會漏報或誤報；物理模型的方程再合理，參數或大氣密度估計有誤差，結果也會偏。方法是否可信，取決於有沒有說清楚適用範圍、有沒有用獨立資料驗證，而不是有沒有標上「非 AI」。

無論哪一層亮燈、融合分數多高，系統指出的都是「偏離常態」，不等於機動已確認，更不等於敵意。

🔗 線上免費閱讀第 7 章（繁中／English／日本語）：
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&ch=07

#太空態勢感知 #SpaceSituationalAwareness #SSA #機器學習 #MachineLearning #異常偵測 #AnomalyDetection #可解釋AI #太空安全 #台灣太空

---

## English post

Just after midnight on September 26, 1983, Soviet Lieutenant Colonel Stanislav Petrov was on duty in an early-warning bunker. The Oko satellite warning system reported a US missile launch, eventually five missiles in all.

Petrov judged it a false alarm. He later explained why: a US first strike would not involve only five missiles; the system was new and he did not fully trust it; and a real attack should be confirmed by ground radar as well. Later analysis found that sunlight reflected off high-altitude clouds had been read by the infrared sensors as rocket plumes.

The machine said "yes" five times. What stopped the alarm was a doubt about plausibility and the expectation of a second source. If an alerting system has only one layer, who asks "does this make sense?"

📘 National Security from Satellite Orbits
Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites
Chapter 7: A Three-Layer Detection Architecture: Rules, Statistics, and Machine Learning

1️⃣ Layers divide responsibility; they are not a voting queue
L1 rules ask whether known trigger or suppression conditions are met and record a flag with its reason. L2 statistics (CUSUM, BOCPD, singular spectrum analysis, robust MAD) ask how unusual the change is. L3 fusion combines the channels to rank events. The physical drag residual and the reentry gate offer another set of checkable hypotheses, not a final verdict.

2️⃣ Rules decide events; AI only sets priority
In the formal report, candidate events come only from the L1 rules. Statistical change points, the drag residual, and the two ML models only affect the evidence grade; they never add or remove events. Every event can therefore state why it was triggered.

3️⃣ Fusion adds value, but read the numbers with their evaluation basis
At the same operating point, acceptance-basis recall was 0.044 for a random baseline, 0.251 for L1 rules, 0.444 for CUSUM (the best single L2 method), and 0.948 for the fusion scorer. With negatives limited to periods covered by ground truth, fusion drops to 0.472 while the ranking holds. The gap comes from more evidence and a different decision method at once, not from "AI" alone.

4️⃣ A threshold is a setting; measured results vary with the data
The fusion alert threshold targets a false-positive rate of 0.05. Contract acceptance measured 0.0498 (214 false alarms in 4,294 no-maneuver windows) and was judged a pass; because the sample is finite, the 95% confidence interval for that estimate is 0.044–0.057. On a separate set of satellites not used in training, the false-positive rate was 0.07015. The same threshold gives different results on different data, so it needs monitoring after deployment.

Transparent is not the same as correct: a rule can explain every trigger, yet a poorly chosen threshold still misses events or raises false alarms; a physical model can rest on sound equations and still drift because of parameter or atmospheric-density errors. Whether a method can be trusted depends on a stated scope and independent validation, not on whether it is labeled "non-AI".

Whichever layer lights up and however high the fusion score, the system is pointing to a departure from normal. That is not a confirmed maneuver, let alone evidence of hostile intent.

🔗 Read Chapter 7 online, free (Traditional Chinese / English / Japanese):
https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n?mode=book&lang=en&ch=07

The English edition is an AI-assisted translation; the Traditional Chinese original prevails.

#SpaceSituationalAwareness #SpaceDomainAwareness #SSA #MachineLearning #AnomalyDetection #ExplainableAI #SpaceSecurity #Taiwan
