# 論文 C 投稿文件審查 Review V4 回應紀錄（2026-11-18）

- 審查文件：paper_C_submission_ReviewV4.md（審查對象為 18 頁正文 PDF 與 V3 回應紀錄）
- 修訂檔案：
  - docs/paper_nrlmsis_drag_validation_EN.md（§1、§3.5、§4.1、§4.3、§4.4、§5、PLS；§2.4 行內符號）
  - docs/build_paperC_submission.py（新增：投稿套件一鍵重建與檢核）
  - output/paper_C_submission/ 之正文與附函 docx／pdf（以上述腳本重建）
- 數值：本輪沒有任何報告數字改變；附函 Markdown 本輪未修改內容。

## 一、結論

V4-1 至 V4-6 已全數處理。V4-1 已查出低通量組的實際日期並寫入正文，原文「last 13 weeks of 2026」的歧義已消除。

V4 §5.4 所提的排版可重現性，已改由新腳本 build_paperC_submission.py 處理：一次完成 DOCX 產生、附函署名區與邊界後處理、Word 轉 PDF、頁數回報、摘要字數與 Key Points 字元數檢核，以及占位文字清單。不再依賴手動後處理。

依 V4 §5.1 對 PDF 第 4 頁做了目視檢查：式 (2) 與 §2.4 的文字定義一致。檢查時另外發現 §2.4 行內式有 `^{1/2}` 原始碼直接印出，此問題自初稿即存在，已改為 `ρ√(μa)Δt`。

## 二、逐項回應

| V4 項目 | 處理 |
|---|---|
| V4-1 last 13 weeks of 2026 | 以窗中心之 81 日平均 F10.7 重算分組：<120 sfu 的週為窗起點 2026-08-13 至 11-05，共 13 個連續分析週（11-12 起的不完整窗沒有被動衛星的有效窗）；FS7 的 <120 組也是同樣 13 週。§3.5 改為「the final 13 analysed weeks of the record (windows starting 13 August to 5 November 2026, covering 13 August to 11 November 2026)」，並補註這段期間的後段落在 81 日平均尚屬暫定值的最後約 40 天內（§2.1） |
| V4-2 §4.3 句構 | 採用 V4 建議段落（三種可能成因 → 無法分離 → compatible with a common activity-associated influence, but does not uniquely identify density-model error），後續雙側門檻與 rolling recalibration 文字保留 |
| V4-3 PLS | 補「309 showed no increase in orbit size larger than 300 m between successive records … nominally passive」；17% 改為高／低通量期之預測／觀測比，並加時間與高度混雜；「misses small changes」改為人工注入試驗的描述 |
| V4-4 結論 3 | 採用 V4 建議文字（median within-satellite high-to-low flux ratio 1.17；FS7 1.18–1.32；partly confounded） |
| V4-5 清理參考族群 | §4.4 改用 V4 建議句：獨立支持的靜默族群可強化校準；以殘差篩選須搭配獨立留出評估，以免選出只是與模型一致的族群 |
| V4-6 enforced／any density model | §1 改為「absorbs much of the overall scale difference, so agreement in decay magnitude is not an independent validation of absolute density accuracy」；§4.1 刪除「any density model of reasonable shape could achieve it」，改為同義限定句 |
| §5.1 式 (2) 目視 | PDF 第 4 頁：式 (2) 為 Δa_model = −B_eff ρ √(μa) Δt，與文字 B_eff＝median of −Δa_obs/[ρ√(μa)Δt]（只取正值）一致 |
| §5.2 圖 5、圖 6 | 圖內標籤已於 V3 回合重畫並目視檢查；本輪未再更動 |
| §5.3 新附函交付 | 附函最新版：docs/paper_nrlmsis_drag_validation_cover_letter_EN.md 與 output/paper_C_submission/paper_nrlmsis_drag_validation_cover_letter_EN.pdf（1 頁，本輪重建）。下一輪請與正文 PDF 一併審查 |
| §5.4 排版可重現 | 新增 docs/build_paperC_submission.py（見第三節） |

## 三、建置腳本

```
python docs/build_paperC_submission.py
```

本輪執行結果：

- 正文 PDF 18 頁；附函 PDF 1 頁。
- 摘要 234 字（≤250）；Key Points 137／136／138 字元（≤140）。
- 殘留占位：正文 12 種、附函 5 種（作者、機構、日期、DOI、經費與 AI 聲明、作者確認等）。其中 `[Authors]` 為參考文獻 2026a–d 中自引的匿名作者，投稿前須換成實際作者名。

附函填入真實作者與地址後，若腳本回報超過 1 頁，可調整腳本中的 LETTER_MARGIN_CM，或精簡內文。

## 四、仍待作者處理（同 V4 §六）

1. 作者、機構、通訊作者、電子郵件、附函日期；參考文獻自引的 `[Authors]`。
2. 全體作者核准與利益衝突確認，並刪除附函占位。
3. 衍生資料 DOI 與程式碼位置。
4. 經費與實際 AI 使用聲明。
5. 兩篇姊妹稿的最新狀態，以及 related manuscripts 聲明。
6. Space-Track 等來源的再散布條款。
7. 投稿系統中的標題與數字是否與正文一致。
8. 最終 PDF 逐頁目視檢查。本輪只看了第 4 頁（式 2）與第 12 頁（Table 5），其餘頁面未逐頁檢查。
