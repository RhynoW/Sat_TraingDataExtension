# 論文 C 投稿文件審查 Review V2 回應紀錄（2026-11-18）

- 審查文件：paper_C_submission_ReviewV2.md（審查對象為 V1 回應紀錄 docs/paperC_ReviewV1_回應紀錄_20261118.md）
- 修訂檔案：
  - docs/paper_nrlmsis_drag_validation_EN.md（摘要換為作者提供之修訂版，並修訂 §1、§2.4、§2.5、§2.8、§2.9、§3.3–§3.6、§4.3–§4.5、PLS）
  - docs/paper_nrlmsis_drag_validation_cover_letter_EN.md
  - docs/paper_nrlmsis_drag_validation.md（中文早期稿：只改標題並加註版本狀態）
  - output/paper_C_submission/ 之 docx／pdf 重建
- 本輪新增的核對計算以既有資料重算（data/benchmark/perigee_drag_cache_x30、fs7_precise_decay_windows.csv），未改動任何既有報告數字。

## 一、結論

V2 列為「仍待技術確認」的 6 項，都已用程式碼與重算核對，沒有發現需要更改結果的問題：

1. B_eff 對逐星相關的間接影響（只經由 |r_drag| ≤ 1 km 選窗）可以忽略。
2. FS7 pooled r 不受各星 B 差異影響。
3. 17% 的估計量是「先在單星內形成比值、再取跨星中位數」，B 在彙總前已相消。
4. 時間切分以逐筆轉換為單位，沒有 7 日窗重疊問題。
5. 最後一個不完整窗沒有任何被動衛星的有效窗。
6. 89% 的分子與分母為 235／265。

文字已依 V2 收斂：限定 B_eff 不變性的適用範圍、定義旗標率分母並說明它不是已驗證的假陽性率、把注入下限界定為殘差層級的篩檢靈敏度，並將 station-keeping 一律寫為可能解釋。

附函 PDF 已恢復為 1 頁，正文 PDF 為 17 頁。

## 二、技術確認項（V2 §4、§6B）

| V2 項目 | 核對方法與結果 | 稿件處理 |
|---|---|---|
| B_eff 是否只是乘法尺度（4.1、6B-1） | 程式碼確認逐窗預測＝B_eff × 模型形狀項加總。唯一間接路徑是選窗規則 maxres ≤ 1 km。重算 309 顆被動衛星：B 乘 0.8／1.2 時，約 43,000 窗中最多 3 窗改變，逐星 r 中位數不變，單星最大變化 0.022；完全移除該規則多 16 窗，中位數變化 0.0003。被動分類只用實測 Δa，與 B 無關 | §2.4 改寫為限定版（within-satellite r、逐星高／低比），並寫入上述敏感度數字；絕對比值、殘差、門檻與 pooled 統計另行解讀 |
| 多星 pooled r（4.1、4.3、6B-2） | FS7 五星 B＝0.02156–0.02186（差 1.4%）。pooled r：原始 0.962；改用共同 B 為 0.962；先做星內標準化再合併也是 0.962。逐星 0.958–0.967。週群集 bootstrap 以週為群集，同週跨星一併重抽 | §3.4 說明 pooled 與逐星中位數是不同統計量、不可同類比較，並報告上述不變性；附函改為「per-satellite 0.958–0.967; 0.962 pooled over five satellites and 616 windows」 |
| 17% 的跨星彙總（4.2、6B-3） | 程式碼確認：逐星各組 R_g＝Σ預期／Σ實測（≥5 窗）→ 逐星 R_>160/R_<120 → 跨星中位數；bootstrap 以衛星為單位重抽，每次重算中位數（5,000 次）。活動度指標為窗中心（起點＋3 日）之 81 日中心平均 F10.7 觀測值（sfu）；120–160 組不納入高／低比 | §2.8 寫明估計量、bootstrap 程序、指標、單位、中間組處理，以及「B 在跨星彙總前已相消」 |
| 89% 的整數（三） | 0.887 × 265 → 235／265 | §3.5、附函改為 235（89%）of 265 |
| 0.92 的有效窗條件（三） | 逐星相關至少要 10 窗；被動衛星最少 15 窗，沒有未定義值 | §2.5 補述 |
| 旗標率分母（4.4） | 分母＝該檔全部被動衛星逐筆轉換間隔之加總（衛星日），旗標於 48 h 內合併 | §2.9 定義 flag 與分母；§2.9 與 §4.4 採用 V2 建議句（includes both potential false flags and possible genuine maneuvers; not a validated false-positive rate）；刪除 V1 的「upper bound」說法；附函補一句 |
| 注入下限（4.5） | 注入對象為逐筆轉換殘差（半長軸變化，km），隨機正負號，0.02–3.0 km；90% 下限＝90% 注入超過門檻的最小步長；與表 6 殘差 P99（同為逐筆轉換殘差）同單位 | §2.9 界定為 injection-based screening sensitivity，不等同實際推進機動的最小可偵測量，也不換算 Δv；附函改為「residual-level injection floor」 |
| 門檻訓練／測試流程（4.6、6B-4） | 程式碼確認：時間切分以轉換終點 epoch 對 2025-07-01 分界（轉換 ≤ 3 日，跨界最多 3 日）；不使用 7 日窗，因此沒有窗重疊；B_eff（重校準版本）與門檻只用訓練轉換擬合，在測試轉換上固定評估。另發現：選星與被動標籤使用全期資料（含測試期） | §2.9 寫明流程；§4.5 新增限制 (vi) 揭露選星與標籤使用全期資料 |
| station-keeping（4.7、6B-5） | — | §3.6 改為「plausible explanation, no independent maneuver records」；§4.4 改為 suggests … may reflect … possible, not established；§4.5 (iii) inflates → may inflate；PLS 改為 possibly |
| 窗時間戳與最後完整窗（5.1） | 窗為固定曆法 7 日箱（floor 7D，以起點標記），轉換歸入其終點 epoch 所在之箱。11-12 起之最後一箱不完整，被動衛星在其中沒有有效窗 | §2.5 補述；11-14 定義為 TLE 輸入截止日（§2.3 已列各星最後 epoch 為 11-10～11-14） |

## 三、文件與版本（V2 §5、§6A-7）

| 項目 | 處理 |
|---|---|
| 摘要 | 換為作者提供之修訂版（234 字，AGU 上限 250）。逐項對照數字：0.92、0.958–0.967、0.962、1.17［1.16–1.19］、89%、1.18–1.32、2.5／1,000 衛星日、0.31 km 均與正文一致 |
| 正文其他用語 | §3.3 reproduces → tracks；§4.3 will over-alarm → would tend to raise more flags；§1 貢獻 2、4 改為觀測獨立與 flag rate 用語 |
| 中文稿「425 Passive」（6A-7） | 中英標題改為近地點分檔／Perigee-Binned；加註此稿為早期草稿、以英文稿為準 |
| 附函版面（5.3） | 刪除推薦審稿人占位段（AGU 投稿系統另有欄位）、合併開頭兩句、刪除與 Open Research 重複之句，署名區段後距設為 0，PDF 為 1 頁。注意：填入真實作者、地址後可能再溢出，屆時再調整 |
| V2 所稱「未收到修訂版文件」（5.2） | 修訂版位於 docs/*.md 與 output/paper_C_submission/*.docx/pdf，下一輪審查請以這些檔案為準 |

## 四、仍待作者處理

1. 日期、作者、機構、通訊資訊；全體作者核准與利益衝突確認（刪除附函中的 [To be confirmed …]）。
2. 資料與程式碼 DOI（附函、Open Research、參考文獻 2026d）。
3. 兩篇姊妹稿最新狀態（附函寫 submitted）。
4. 經費與生成式 AI 聲明。
5. 實際核對 Space-Track 使用者協議中的再散布條款（附函與 Open Research 措辭仍屬作者主張）。
6. 是否改用以 solar-activity-dependent bias 為主軸的新標題（作者可選）。
7. 推薦審稿人若要提供，請在投稿系統填寫。

## 五、附註

- 本輪重算得到的被動衛星逐星 r 中位數為 0.926，與 persat 檔及正文的 0.923 略有差異（重算時以轉換重新分窗，窗集合有細微不同）。§2.4 只引用相對變化量（B 縮放與移除選窗規則的差值），不引用重算的絕對值。
- 附函 docx 的署名區段後距在 md_to_docx.py 產出後另行設為 0；若重新執行 md_to_docx.py，需要重做這一步。
