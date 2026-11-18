# 出版用圖檔四版本（高解析 × 中文／英文 × 白底黑字／黑底白字）

每張圖輸出至 `docs/figures_pub/<stem>/`，共 8 個檔：

| 檔名 | 說明 |
|---|---|
| `<stem>_zh_light.png` / `.pdf` | 中文、白底黑字 |
| `<stem>_zh_dark.png` / `.pdf` | 中文、黑底白字 |
| `<stem>_en_light.png` / `.pdf` | 英文、白底黑字 |
| `<stem>_en_dark.png` / `.pdf` | 英文、黑底白字 |

- PNG 為 600 dpi；PDF 為向量，TrueType 內嵌（pdf.fonttype 42，文字可選取）。
- 字型：中文為微軟正黑體，英文為 Arial；缺字依序 fallback 至 DejaVu Sans。
- 所有指令都在 repo 根目錄執行，且只讀快取 CSV：不連 `space_db.duckdb`、不重算，也不覆寫 `docs/fig_*.png` 原檔。
- 一次重產全部：`python docs/gen_all_figures_pub.py`。只跑部分可加關鍵字，例如 `python docs/gen_all_figures_pub.py sigma ids`。

共用模組 `docs/fig_pub.py` 的作法：

- `fp.t(zh, en)` 依語言切換文字。
- `fp.export_variants(draw_fn, stem)` 對 lang × theme 各重繪一次並存檔。
- 黑底版：先照白底配色繪成，再把每個顏色在 HLS 空間做亮度反轉（L → 1 − L），色相與飽和度不變；色圖與色條同樣轉換。半透明填色（alpha < 0.75）改取 max(L, 1 − L)，在黑底上才不會變暗。
- 中文版的對數軸若有負指數，刻度改以一般數字顯示（0.1、1、10），因為微軟正黑體缺數學負號 U+2212。
- 每次輸出都會檢查兩件事：英文版有沒有殘留中文、黑底版有沒有暗色文字。有問題會印出 `[WARN]`。

## 期末報告（docs/期末報告_20261115.md，2026-11-18 第九輪版）圖 1–23

23 張全部完成。四版本另複製一份至 `output/final_word/期末報告_FIN-RPT-01_圖片/`（依圖號命名）。

| 圖號 | 檔名（stem） | 狀態 | 產生指令 | 資料來源 |
|---|---|---|---|---|
| 1 | fig_sys_architecture | 完成 | `python docs/gen_fig_system_flow.py --pub` | 無（流程圖） |
| 2 | fig_sys_routing | 完成 | 同上 | 無 |
| 3 | fig_sys_r7_flow | 完成（內容未改，只加多版本） | 同上 | 無 |
| 4 | fig_r5_p2_parabola | 完成（重寫，2026-11-18） | `python docs/gen_fig_report_r_series.py` p2_parabola | maneuver_strategies_july 常數 |
| 5 | fig_r1_nrlmsis_density | 完成（重寫） | `python docs/gen_fig_report_r_series.py` nrlmsis_density | pymsis 即時計算 |
| 6 | fig_paperA_rv1_fig1 | 完成 | `python docs/gen_fig_paperA_rv1.py` | paperA_reviewV1.json、paperA_rv1_*.csv |
| 7 | fig_nrlmsis_decay_expect | 完成 | `python docs/gen_fig_nrlmsis_decay_expect.py --pub` | data/benchmark/nrlmsis_decay_expect.csv |
| 8 | fig_perigee_drag_corr_x30 | 完成 | `python docs/analyze_perigee_drag_corr.py --pub --tag=x30` | perigee_drag_corr_{windows,persat,bins}_x30 |
| 9 | fig_nrlmsis_solar_tracking_x30 | 完成 | `python docs/gen_fig_nrlmsis_solar_tracking.py --pub --tag=x30` | perigee_drag_corr_*_x30、nrlmsis_decay_expect.csv |
| 10 | fig_fs7_precise_nrlmsis | 完成 | `python docs/gen_fig_fs7_precise_nrlmsis.py --pub` | fs7_precise_decay_windows.csv、fs7_precise_nrlmsis_corr.csv |
| 11 | fig_r3_joint_element | 完成（重寫） | `python docs/gen_fig_report_r_series.py` joint_element | 資料庫 TLE（唯讀） |
| 12 | fig_r9_planupload | 完成（重寫） | `python docs/gen_fig_report_r_series.py` planupload | data/raw/ 之 MEME 發布檔 |
| 13 | fig_r2_starlink_planes | 完成（重寫） | `python docs/gen_fig_report_r_series.py` starlink_planes | 資料庫 TLE（唯讀） |
| 14 | fig_r8_fs_family | 完成（重寫） | `python docs/gen_fig_report_r_series.py` fs_family | 資料庫 TLE（唯讀） |
| 15 | fig_r7_fs7_fleet | 完成（重寫） | `python docs/gen_fig_report_r_series.py` fs7_fleet | 資料庫 TLE（唯讀） |
| 16 | fig_r4_shenlong_release | 完成（重寫） | `python docs/gen_fig_report_r_series.py` shenlong_release | 資料庫 TLE（唯讀）＋SGP4 |
| 17 | fig_r6_shenlong_height | 完成（重寫） | `python docs/gen_fig_report_r_series.py` shenlong_height | 資料庫 TLE（唯讀） |
| 18 | fig_shenlong_2026_rpo | 完成 | `python verify_shenlong_2026_rpo.py --pub` | verify_shenlong_2026_rpo.csv |
| 19 | fig_tasa15_timeline_r7 | 完成 | `python docs/build_tasa15_ppt.py data/benchmark/tasa15_r7_delivery/r15.json --pub-fig-only` | r15.json 以交付當時資料重建（`docs/build_r15_json.py`） |
| 20 | fig_starlink_v3_profile | 完成 | `python docs/analyze_starlink_v3.py --pub` | 資料庫 TLE |
| 21 | fig_sys_app_vs_r7 | 完成 | `python docs/gen_fig_system_flow.py --pub` | 無 |
| 22 | fig_tasa15_detect_vs_alt_r7 | 完成 | `python docs/gen_fig_tasa15_detect_vs_alt.py data/benchmark/tasa15_r7_delivery/r15.json --pub R7` | 同上；重建之中文白底版與報告原圖逐像素相同 |
| 23 | fig_drag_resid_threshold | 完成 | `python docs/study_drag_resid_threshold.py --pub` | drag_thr_by_alt_x30.csv、drag_thr_summary_x30.csv |

### 圖 4、5、11–17 之重寫說明（2026-11-18）

這 9 張報告原圖找不到原產生程式，改由 `docs/gen_fig_report_r_series.py` 依原圖內容重寫。TLE 圖只用下載時間 ≤ 2026-07-15 之資料（圖 16、17 為 2024 年資料，不設下載時間限制），以對應原圖之資料快照。各圖與原圖核對結果：

| 圖 | 核對項目 | 原圖／報告 | 重繪 | 說明 |
|---|---|---|---|---|
| 4 | 參考點、底值、P5 倍率 | 400 km 2.0 km、0.4 km、×1.6 | 相同 | 依委員意見④改直述：標題去「新版程式…實際取值」，刪舊版三段階梯門檻線（報告圖說未提及） |
| 5 | 曲線形狀、倍數關係 | 600 km 極大／極小約數十倍 | 600 km 約 39 倍；磁暴比中等活動高約 1.5–2 倍 | 原圖之日期與經緯度未記錄，重繪取 2024-06-21 12:00 UTC、0°／0°，絕對值與原圖略有差異（400 km 約高 1.4 倍），不影響圖說 |
| 11 | 起點高度、升軌段 | 約 270 km → 465 km | 270.5 → 465.7 km，261 筆 | 一致 |
| 12 | 首值、5846 範圍 | 1,892 m；< 250 m | 1,892 m；最大 256 m | 37471 之 16 點由原始 MEME 檔重算（快取 CSV 只有前 10 點，數值一致）；5846 為 2026-07-04 至 07-08 之 11 對 |
| 13 | 顆數、面數、異常面 | 10,802 顆／215 面／7 面 | 相同；批量事件日 0 | 視窗為 epoch 2026-06-14 至 07-14（30 天）、下載時間 ≤ 2026-07-15（逐一試算反推）。判定線依程式公式（中位數＋3σ）畫在 0.0215°；原圖之線畫在第 7 面之值（約 0.026°），被標記之 7 面相同 |
| 14 | 各星高度 | FS-5 723、TRITON 595、FS-8A 564 km | 相同 | 黑底版福衛三號藍色深淺另行配色，反轉後仍可辨 |
| 15 | FS7-3 末值 | 536 km | 536.3 km | 一致 |
| 16 | 最近距離、06-06 前最大距離 | 約 0.2 km（05-28 05:43Z）；約 1,700 km | 0.18 km（05-28 05:53Z）；1,744 km | 每 1 分鐘、各用 epoch 最接近該時點之 TLE 做 SGP4（改用「epoch ≤ t 之最新 TLE」則為 0.12 km @ 12:58，與原圖不符）。最近時刻差 10 分鐘，報告已註明不宜逐位解讀 |
| 17 | 高度差 | 約 1.00 km | 1.01 km | 原圖為黑底外部工具樣式，重繪改為與其他圖一致之樣式 |

報告原圖 `docs/fig_r*.png` 未覆寫，報告本身未修改。

## 論文一：docs/paper_tle_sma_noise_floor.md

| 圖號 | 檔名（stem） | 狀態 | 產生指令 |
|---|---|---|---|
| 1 | fig_sigma_vs_altitude | 完成（同報告圖 6） | `python docs/gen_fig_sigma_vs_altitude.py --pub` |
| 2 | fig_ids_detection_curve | 完成 | `python ids_truth_set/ids_detection_curve.py --pub`（讀 ids_detection_curve_jason3.csv） |
| 3 | paper2_fig3_shap_importance | **未完成** | 見下方 |
| 4 | paper2_fig5_roc_comparison | **未完成** | 見下方 |
| 5 | fig_ids_dv_vector | 完成 | `python ids_truth_set/ids_dv_vector_validate.py --pub`（讀 ids_dv_vector_validate.csv） |

## 論文二：docs/paper_fs7_sensitivity_model_EN.md

| 圖號 | 檔名（stem） | 狀態 | 產生指令 |
|---|---|---|---|
| Fig. 1（資料與方法流程） | fig_fs7_method_flow | 完成 | `python docs/gen_fig_fs7_method_flow.py --pub`（純繪圖，無資料輸入） |
| Fig. 2（單一注入案例） | fig_fs7_injection_case | 完成 | `python docs/gen_fig_fs7_injection_case.py --pub`（讀 fs7_injection_case.csv／_meta.json；快取由不加 --pub 之預設執行以 DB read_only 產生） |
| Fig. 3 | fig_fs7_injection_recall | 完成 | `python fs7_injection_sweep.py --pub`（讀 fs7_injection_sweep.csv、fs7_injection_trials.csv） |
| Fig. 4 | fig_fs7_injection_collapse | 完成 | 同上（同一指令產生 Fig. 3 與 Fig. 4） |
| Fig. 5 | fig_fs7_injection_metrics | 完成 | `python fs7_injection_sweep_v3.py --pub`（讀 fs7_injection_metrics.csv） |
| Fig. 6（實際事件比較） | fig_fs7_real_event_recall | 完成 | `python docs/gen_fig_fs7_real_event_recall.py --pub`（讀 fs7_tle_recall_unified_20260825.csv、fs7_events_2024.csv；先核對 Table 4） |
| Fig. S1 | fig_fs7_profile_likelihood、fig_fs7_joint_likelihood | 完成 | `python docs/gen_fig_fs7_model_supplement.py --pub`（讀 fs7_review3_profile_grid.csv、fs7_review3_joint_boot.csv、fs7_review4_joint_grid.csv；網格由 `python fs7_review3_analysis.py && python fs7_review4_analysis.py` 產生，需 DB read_only） |
| Fig. S2 | fig_fs7_reliability | 完成 | 同上（讀 fs7_review4_heldout_predictions.csv） |
| Fig. S3 | fig_tle_noise_floor_map_contour | 完成 | `python fs7_noise_floor_map_v2.py --pub`（讀 tle_noise_floor_map.csv） |
| Fig. S4（納入／排除事件分布） | fig_fs7_event_selection | 完成 | `python docs/gen_fig_fs7_event_selection.py --pub`（讀 fs7_tle_recall_unified_20260825.csv） |

論文二新增圖（Fig. 1、2、6、S1、S2、S4）共用 `docs/fs7_fig_style.py`：期刊版面（單欄 8.5 cm／雙欄 17.5 cm、字級 6.5–7.5 pt）；不加 `--pub` 時輸出 `docs/<stem>.png`（600 dpi，英文白底）與 `.pdf`。

## 未完成清單與原因

| 圖 | 原因 |
|---|---|
| 論文一圖 3（paper2_fig3_shap_importance） | 原圖是 `Orbital_Maneuver_V2/analyze_plan_b_model.py` 以 shap 套件輸出的 shap_summary_bar.png，再手動複製而成。要重算 SHAP 並改寫 shap 內建繪圖，不屬於「讀快取重繪」。 |
| 論文一圖 4（paper2_fig5_roc_comparison） | 左半部是直接嵌入的點陣圖（compare_models.py 產生的 roc_comparison.png），無法轉成黑底或英文；要重訓 RF／XGBoost 才能重繪 ROC 曲線。 |

## 已知差異與注意事項

- 四版本由快取 CSV 重繪。部分 CSV 存檔時有四捨五入（perigee persat、drag_thr、shenlong 距離取到 0.01 km），與原圖逐像素比對約有 0.01–0.07% 像素差，肉眼看不出。
- `fig_fs7_injection_metrics` 面板 (a)：由 metrics CSV 依各阻力域試驗數加權重建，等同原本逐試驗平均，差異只來自 CSV 中 recall 取到小數第 3 位。
- `fig_tle_noise_floor_map_contour`：
  - 目前 matplotlib 版本畫出的等高線數值標籤位置，與現有原圖略有不同。
  - 圖中擬合值為 H = 77 km、R² = 0.89，但論文內文寫 H = 79 km、R² = 0.87，需要作者確認。
- 原報告圖 18（fig_shenlong_2026_rpo.png，中文）的「≈」與對數刻度負號，在原檔中是缺字方塊；四版本已用字型 fallback 修正。原檔未動。
- `fig_starlink_v3_profile/` 目錄不是本批程式產生的，不在上述對照表內。
- 論文二新增圖之數字核對（細節見各程式主控台輸出）：
  - Fig. 6：Table 4 各箱 n、兩門檻召回、Wilson CI、平均預測機率全部一致；但 CSV 之 p_pred 是以全資料描述性係數（c = 0.32、SNR₅₀ = 3.77、β = 5.25）計算，Table 4 表註寫「calibration-period coefficients」不符（改用校準期係數 0.28／3.87／5.04 時為 0.31／0.61／0.68／0.71／0.67），需作者確認表註。
  - Fig. S4：campaign 排除率實際為 0.00–0.54（2025-05 為 0/8），與補充材料一致；論文正文 §2.6 寫 0.07–0.54。
  - Fig. S2：校準截距 −0.63 為 fs7_final_supplement.py 以四捨五入係數（0.28／3.87／5.04）重建之值；以未四捨五入係數之逐試驗預測重算為 −0.62。fs7_review4_analysis.json 之 calib_intercept（−0.27）換算少乘 ln 10，不採用。
  - Fig. S1：聯合網格峰值依網格解析度而異（26×26：c = 0.33、SNR₅₀ = 3.70；61×61：0.32、3.77；47 點 profile：0.316、3.77），三者對數似然差 < 0.4，屬窄脊線上之取樣差異。
  - fs7_review3_analysis.py 重跑：模型相關摘要值全部一致；第 6 節 pseudo-event 混淆表因 DB 新增 TLE 而改變（n 1,131 → 1,141），另存 fs7_review3_analysis_rerun.json，原 json 未動。

## r15.json 之重建（報告圖 19、21）

`data/benchmark/tasa15_r7_delivery/r15.json` 以「交付當時之資料」重建：本機資料庫只取 2026-11-15 13:50 UTC（交付 PDF 產生時刻）以前下載之 TLE，期間與交付相同（結束日為 2026-11-14 與該星最後一筆 TLE 日期之較早者，如 SHIYAN 24C 02 為 2026-10-15），分析流程 4778df6。以此重建之圖 19、圖 21 報告版（docs/fig_tasa15_*_r7.png）與原圖逐像素相同。15 顆之候選事件、證據等級與偵測下限皆與交付一致；低置信複核項除 STARLINK-4314 多 1 項（2026-10-18 阻力殘差 0.302 km，門檻邊緣，太空天氣檔已更新）外皆一致，兩張圖不使用低置信複核項。重建步驟：

```
# 1. 建交付當時資料庫（15 顆、downloaded_at_utc <= '2026-11-15 13:50:00'）
# 2. set LOCAL_DB_PATH=<上述資料庫>
python docs/build_r15_json.py data/benchmark/tasa15_r7_delivery/r15.json 2026-11-14
```

圖 19 黑底版之證據等級改用黑底專用配色（`build_tasa15_ppt.GRADE_COLOR_DARK`，經 `fig_pub.theme()` 判斷），使 E1 在黑底上可辨。
