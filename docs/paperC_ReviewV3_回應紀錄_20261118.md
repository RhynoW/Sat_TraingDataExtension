# 論文 C 投稿文件審查 Review V3 回應紀錄（2026-11-18）

- 審查文件：paper_C_submission_ReviewV3.md（審查對象為單頁附函 PDF 與 17 頁正文 PDF）
- 修訂檔案：
  - docs/paper_nrlmsis_drag_validation_cover_letter_EN.md
  - docs/paper_nrlmsis_drag_validation_EN.md
  - docs/study_drag_resid_threshold.py、docs/gen_fig_paperC_threshold_oos.py（只改英文圖內用語）→ 以 `--pub` 重畫 docs/figures_pub/ 中的圖 5、圖 6（英文版，白底／黑底；只讀既有 CSV、不重算）
  - output/paper_C_submission/ 之 docx／pdf 重建
- 數值：本輪沒有任何報告數字改變。

## 一、結論

V3 的附函意見 C1–C5 已全數採用 V3 建議文字。正文 M1–M7 已全數處理，其中兩項核對出原稿確實有錯：

- **M4**：Table 5 表注把 TLE 各列寫成週群集 bootstrap，實際是逐星 R_g 中位數加衛星 bootstrap，已更正。
- **M7**：B_eff 估計式少了負號，也漏寫「只取正比值」，已更正。

其餘各項都屬措辭與範圍限定。附函 PDF 為 1 頁，正文 PDF 為 18 頁。

## 二、附函（C1–C6）

| 項目 | 處理 |
|---|---|
| C1 coefficient cancels in both | 改用 V3 建議句：within-satellite Pearson correlations 與 high-to-low flux ratios「invariant to the fitted multiplicative scale for a fixed set of windows; absolute density accuracy is not assessed」 |
| C2 no orbit raising | 改為「no adjacent-TLE semi-major-axis increase exceeding 0.3 km … classified as nominally passive」 |
| C3 混雜限制 | 結果 2 採用 V3 建議文字，句末加「The association remains partly confounded with time and altitude.」 |
| C4 evaluable／benchmark | 結果 3 改為「benchmark flagging rate in every evaluable altitude bin」 |
| C5 90% 與 station-keeping | 結果 3 採用 V3 建議文字（90% residual-level injection detection floor；suggesting possible contamination … by small station-keeping maneuvers） |
| C6 姊妹稿 | 「but not its research question or analyses」改為「but their primary analyses address distinct questions」；內容與投稿狀態仍待作者核對 |

## 三、正文（M1–M7）

| 項目 | 核對結果 | 處理 |
|---|---|---|
| M1 變化「完全來自密度」 | — | §1、§3.3、§4.1 三處改為：固定 B_eff 排除係數逐時調整，預測變化反映沿演化軌道之模型密度與相關軌道因子 |
| M2 rolling recalibration | — | §4.3 改用 V3 建議句（possible mitigation, not evaluated）；補充雙側絕對殘差門檻下影響方向取決於殘差基線與機動正負號；「points to a common origin」改為「is consistent with … although … partly confounded」 |
| M3 false-alarm 用語 | — | §2.9 只保留一句定義（設計上把所有旗標視同誤報），其餘結果、表 6–8 標題與表注、圖 5–6 圖說與圖內標籤一律改為 flag／flag rate；表注統一加「merged flags per 1,000 satellite-days in the nominally passive sample, not validated false-positive rates」；0.43 全文統一稱 benchmark（不再稱 target）；「no scheme meets … in every bin」改為 every evaluable bin。數值不變 |
| M4 Table 5 定義 | paperC_bias_by_f107_20261118.csv 的 ci_method 欄：FS7 為「週群集 bootstrap（逐窗比值中位數）」，TLE 為「衛星 bootstrap（逐星 Σ預期／Σ實測之中位數）」。各組衛星數不同（例：全體 269／266／266）。兩組中位數相除 1.0805／0.9295＝1.162，不等於逐星比中位數 1.171 | **更正表注**（原寫 week-clustered 為錯）；§2.8 補述各高度帶數值之彙總方式；表注說明組中位數相除不會重現 1.17 |
| M5 樣本外範圍 | 跨界轉換：每星每方向至多 1 筆（≤309／877,567） | §4.5 (vi) 補述：時間外測試評估的是回溯選定族群內的門檻轉移，不是即時建構樣本與標籤的前瞻管線；跨界轉換數量如上。未重算剔除跨界轉換的版本（V3 允許以限制說明替代） |
| M6 強措辭 | — | §4.2 → consistent with limited signal-to-noise and do not, by themselves, establish model failure；§1、§3.4、§5 之「represent true decay」→ closely track precise-orbit-derived decay（under the tested conditions），並統一高度為 538–585 km；§5 → do not meet the benchmark in every evaluable bin；§3.5 → not attributable solely to TLE-derived decay；KP3 → 「A fixed residual threshold flags nominally passive satellites most below 450 km; its 90% residual-injection floor is 0.31 km above 600 km.」（138 字元） |
| M7 正負號 | atmospheric_drag.py：ratios＝−Δa/s，B_eff＝median(ratios[ratios>0])，pred＝−B_eff·s，resid＝Δa − pred | **更正 §2.4**：B_eff 為 −Δa_obs/[ρ(μa)^{1/2}Δt]（衰減為正）之中位數，只用比值為正之轉換，B_eff > 0。式 (2) 與程式一致，無須修改 |

## 四、檢核

- 摘要 234 字（≤250）；Key Points 137／136／138 字元（≤140）。
- 正文 docx 結構不變（標題 32、段落 90、表 8、圖 6、公式 3），PDF 18 頁。
- 圖 5、圖 6 重畫後已目視檢查：圖例、軸標與圖說均已改為 flag／benchmark／90% residual-injection detection floor。圖 5 也被期末報告簡報引用，但簡報用中文版，本次未改中文版。
- 附函 PDF 1 頁。docx 後處理步驟：署名區三段段後距設為 0、上下邊界設為 2.0 cm。若重跑 md_to_docx.py 會被覆蓋，需要重做。

## 五、仍待作者處理（同 V3 §六）

1. 作者、機構、通訊資訊與日期。
2. 全體作者同意與利益衝突確認，確認後刪除附函占位。
3. 衍生資料 DOI 與程式碼位置。
4. 經費與生成式 AI 聲明。
5. 兩篇姊妹稿最新狀態，並逐項核對「neither evaluates …」的敘述。
6. 核對 Space-Track 使用者協議中的再散布條款。
7. 最終 PDF 逐頁目視檢查（寬表、分頁、公式）。本輪只檢查了頁數與兩張重畫的圖。
