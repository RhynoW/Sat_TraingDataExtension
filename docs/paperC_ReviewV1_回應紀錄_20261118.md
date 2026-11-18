# 論文 C 投稿附函審查 Review V1 回應紀錄（2026-11-18）

- 審查文件：output/paper_C_submission_ReviewV1.md
- 修訂檔案：
  - docs/paper_nrlmsis_drag_validation_cover_letter_EN.md（重寫）
  - docs/paper_nrlmsis_drag_validation_EN.md（同步修訂，使附函與正文一致）
  - output/paper_C_submission/ 之兩份 docx／pdf（以 docs/md_to_docx.py 重建、Word 轉 PDF）
- 數字來源：data/benchmark/paperC_numbers.json、docs/paperC_numbers.py；本次未改任何分析數字。

## 一、結論

審查提出的科學論證問題，多數可由正文既有方法直接回應，不需要補做分析。最關鍵的回應是：每星 B_eff 為全期擬合（樣本內），但兩項驗證指標都不受 B_eff 影響。逐星 Pearson 相關不受常數尺度影響；高／低比為比值之比，B 會相消。附函與正文已補上這段說明。

另外，審查時發現原標題中的「425 Passive」有實質錯誤：425 顆中有 116 顆有升軌紀錄。標題、PLS 與資料集題名已一併更正。

仍待作者處理的是投稿阻擋事項（第三節），這些不能代填。

## 二、逐項回應

| 審查項 | 處理 | 位置 |
|---|---|---|
| P0 研究期間截止日 | 核對 TLE 快取：425 顆最後 epoch 為 2026-11-10～11-14，7 日窗最晚起於 11-12。改寫為「1 January 2024 through 14 November 2026」 | 附函；摘要；§2.3；§5 |
| P0 425／265 母體關係 | 新增巢狀樣本說明：425 → 309 名義被動（116 有升軌）→ 270 自 2024-01 起有 TLE → 265 兩通量組各 ≥5 窗 | 附函；§2.6 |
| P1 B 擬合與驗證界線（3.1） | 明示 B_eff 以全期轉換中位數擬合，屬樣本內；說明相關係數與高／低比不受其影響，只有殘差門檻受影響（已另有訓練期重校準評估，§2.9）；絕對密度偏差被 B_eff 吸收，不在檢驗範圍 | 附函；摘要；§2.4 |
| P1 confirmed independently（3.5） | 改為 corroborate；§3.4 新增說明：精密軌道在觀測上獨立，但 B 校準程序與 NRLMSIS 輸入相同 | 附函；摘要；§3.4；§5 |
| P1 17% 定義（3.4） | §2.8 定義 R_g＝Σ預期／Σ實測（每組 ≥5 窗）、高／低比＝R_>160/R_<120、相對變化＝比值 − 1、CI 為衛星 bootstrap 5,000 次；說明 R_g 的絕對水準取決於 B，不作解讀 | 附函；§2.8；§3.5 |
| 89% 為方向或顯著 | 明示為方向一致比例（R_>160/R_<120 > 1），不是逐星顯著性檢定 | 附函；§2.8；§3.5 |
| 0.92 與 0.962 統計單位（3.3） | 附函標明 0.92＝309 顆逐星相關之中位數；0.962＝五星 616 窗合併相關（正文表 4 已有週群集 CI） | 附函；摘要 |
| reproduces → tracks | 附函、Key Points、結論 1 改為 tracks | 同左 |
| passive 定義（3.2） | 改為 nominally passive；§2.5 明示此為 TLE 推定之標籤，不是推進活動的獨立事實 | 附函；摘要；§2.5；§5 |
| over-alarms／insensitive（3.6） | 改為「flags nominally passive satellites」，以及 0.31 km 注入偵測下限相對 3–19 m 被動殘差的描述；§4.4 說明旗標率是假警報上限，不是已確認的假警報率 | 附函；KP3；摘要；§4.4；§5 |
| primary limitation（3.7） | 改為 possible contamination … an important limitation，並寫出依據（旗標集中於少數具推進衛星：SMOS、KazEOSat-1、GCOM-C 等，§3.6） | 附函；§5 |
| companion manuscripts 零重疊（5.1） | 核對兩稿：Paper B 使用相同的 FS7 leoOrb 精密軌道與 Space-Track TLE；Paper A 共用 Space-Track TLE，且本稿 §4.2 引用其雜訊水準。改寫為「共用資料來源，研究問題與分析不同」，並列出本稿獨有的分析 | 附函 |
| 文獻概括「seldom tested」 | 改為「needs to be evaluated across the range of solar activity」 | 附函 |
| Space-Track 條款措辭（5.2） | 改為「not redistributed, in accordance with its user agreement」，並補充其他資料來源之可得性（指向 Open Research） | 附函 |
| 推薦審稿人（5.3） | 改為選填占位，並註明不提供則刪除；未代填任何人名 | 附函 |
| 標題（四） | 修正事實錯誤（Passive → Perigee-Binned）；審查建議的「Solar-Activity-Dependent Bias …」新標題屬作者決定，未採用，列入第三節 | 標題；參考文獻 2026d |

## 三、仍待作者處理（投稿前）

1. 日期、全體作者、機構、通訊作者資訊（附函與正文）。
2. 全體作者確認投稿與無利益衝突聲明，確認後刪除「[To be confirmed by all authors before submission.]」。
3. 上傳 Zenodo 資料包取得 DOI，填入附函、Open Research 與參考文獻 2026d；程式碼庫 DOI 亦同。
4. 決定是否提供推薦審稿人；不提供則刪除該段。
5. 核對兩篇姊妹稿最新投稿狀態（附函目前寫 submitted）。
6. 決定是否改用審查建議之新標題（以 solar-activity-dependent bias 為主軸）。若改，需同步修改正文、附函、參考文獻 2026d 與資料包 README。
7. 中文稿 docs/paper_nrlmsis_drag_validation.md 的標題仍為「425 Passive」，本次未修改。
8. 經費聲明與生成式 AI 聲明（Acknowledgments 占位）。

## 四、檢核

- 摘要 250 字（AGU 上限 250）；Key Points 為 137／136／128 字元（上限 140）。
- 正文 docx 重建後結構不變（段落 143、表 8、圖與公式 9），PDF 16 頁。
- 附函 PDF 為 2 頁，第 2 頁只有審稿人占位與署名。
