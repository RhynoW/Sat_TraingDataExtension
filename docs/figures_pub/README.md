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

## 期末報告（docs/期末報告_20261115.md）圖 1–22

| 圖號 | 檔名（stem） | 狀態 | 產生指令 | 資料來源（快取） |
|---|---|---|---|---|
| 1 | fig_sys_architecture | 完成 | `python docs/gen_fig_system_flow.py --pub` | 無（流程圖） |
| 2 | fig_sys_routing | 完成 | 同上 | 無 |
| 3 | fig_sys_r7_flow | 完成（內容未改，只加多版本） | 同上 | 無 |
| 4 | fig_r5_p2_parabola | **未完成** | — | 見下方「未完成清單」 |
| 5 | fig_r1_nrlmsis_density | **未完成** | — | 同上 |
| 6 | fig_sigma_vs_altitude | 完成 | `python docs/gen_fig_sigma_vs_altitude.py --pub` | ids_truth_set/ids_sigma_calibration.csv |
| 7 | fig_nrlmsis_decay_expect | 完成 | `python docs/gen_fig_nrlmsis_decay_expect.py --pub` | data/benchmark/nrlmsis_decay_expect.csv |
| 8 | fig_perigee_drag_corr_x30 | 完成 | `python docs/analyze_perigee_drag_corr.py --pub --tag=x30` | perigee_drag_corr_{windows,persat,bins}_x30 |
| 9 | fig_nrlmsis_solar_tracking_x30 | 完成 | `python docs/gen_fig_nrlmsis_solar_tracking.py --pub --tag=x30` | perigee_drag_corr_*_x30、nrlmsis_decay_expect.csv |
| 10 | fig_fs7_precise_nrlmsis | 完成 | `python docs/gen_fig_fs7_precise_nrlmsis.py --pub` | fs7_precise_decay_windows.csv、fs7_precise_nrlmsis_corr.csv |
| 11 | fig_r3_joint_element | **未完成** | — | 見下方 |
| 12 | fig_r9_planupload | **未完成** | — | 見下方 |
| 13 | fig_r2_starlink_planes | **未完成** | — | 見下方 |
| 14 | fig_r8_fs_family | **未完成** | — | 見下方 |
| 15 | fig_r7_fs7_fleet | **未完成** | — | 見下方 |
| 16 | fig_r4_shenlong_release | **未完成** | — | 見下方 |
| 17 | fig_r6_shenlong_height | **未完成** | — | 見下方 |
| 18 | fig_shenlong_2026_rpo | 完成 | `python verify_shenlong_2026_rpo.py --pub` | verify_shenlong_2026_rpo.csv |
| 19 | fig_tasa15_timeline_r7 | **程式已備妥，未輸出** | `python docs/build_tasa15_ppt.py <r15.json> --pub-fig-only` | r15.json（已不在專案內） |
| 20 | fig_sys_app_vs_r7 | 完成 | `python docs/gen_fig_system_flow.py --pub` | 無 |
| 21 | fig_tasa15_detect_vs_alt_r7 | **程式已備妥，未輸出** | `python docs/gen_fig_tasa15_detect_vs_alt.py <r15.json> --pub R7` | r15.json（已不在專案內） |
| 22 | fig_drag_resid_threshold | 完成 | `python docs/study_drag_resid_threshold.py --pub` | drag_thr_by_alt_x30.csv、drag_thr_summary_x30.csv |

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
| Fig. 1（資料與方法流程） | — | **無圖檔** | 專案內沒有此圖，也沒有產生程式 |
| Fig. 2（單一注入案例） | — | **無圖檔** | 同上 |
| Fig. 3 | fig_fs7_injection_recall | 完成 | `python fs7_injection_sweep.py --pub`（讀 fs7_injection_sweep.csv、fs7_injection_trials.csv） |
| Fig. 4 | fig_fs7_injection_collapse | 完成 | 同上（同一指令產生 Fig. 3 與 Fig. 4） |
| Fig. 5 | fig_fs7_injection_metrics | 完成 | `python fs7_injection_sweep_v3.py --pub`（讀 fs7_injection_metrics.csv） |
| Fig. 6（實際事件比較） | — | **無圖檔** | 專案內沒有此圖，也沒有產生程式 |
| Fig. S1／S2 | fig_fs7_profile_likelihood、fig_fs7_joint_likelihood | **未完成** | 見下方 |
| Fig. S3 | fig_tle_noise_floor_map_contour | 完成 | `python fs7_noise_floor_map_v2.py --pub`（讀 tle_noise_floor_map.csv） |
| Fig. S4（納入／排除事件分布） | — | **無圖檔** | 專案內沒有此圖，也沒有產生程式 |

## 未完成清單與原因

| 圖 | 原因 |
|---|---|
| 報告圖 4、5、11–17（fig_r5_p2_parabola、fig_r1_nrlmsis_density、fig_r3_joint_element、fig_r9_planupload、fig_r2_starlink_planes、fig_r8_fs_family、fig_r7_fs7_fleet、fig_r4_shenlong_release、fig_r6_shenlong_height） | 專案內只有 PNG，找不到產生程式。檔名只出現在 build_*_ppt*.py 的插圖引用，git 歷史中也沒有。重繪等於從頭重寫程式，而且多數要重查 DB（MEME 檔、Starlink 軌道面、福衛家族、神龍相對運動），無法保證與報告原圖一致。 |
| 報告圖 19、21（fig_tasa15_timeline_r7、fig_tasa15_detect_vs_alt_r7） | 程式已改好，支援四版本輸出，並以小樣本測試過。所需的 `r15.json`（maneuver_report_builder 對 15 顆衛星之 R7 輸出，資料至 2026-11-14）已不在專案內。若重跑 DB，現在的 TLE 已比 11-14 新，結果會與報告不一致。取得原 r15.json 後執行上表指令即可。另外，黑底版的 E1 淺藍在反轉後偏暗，產出前需再調整。 |
| 論文一圖 3（paper2_fig3_shap_importance） | 原圖是 `Orbital_Maneuver_V2/analyze_plan_b_model.py` 以 shap 套件輸出的 shap_summary_bar.png，再手動複製而成。要重算 SHAP 並改寫 shap 內建繪圖，不屬於「讀快取重繪」。 |
| 論文一圖 4（paper2_fig5_roc_comparison） | 左半部是直接嵌入的點陣圖（compare_models.py 產生的 roc_comparison.png），無法轉成黑底或英文；要重訓 RF／XGBoost 才能重繪 ROC 曲線。 |
| 論文二 Fig. S1／S2（fig_fs7_profile_likelihood、fig_fs7_joint_likelihood） | 圖中的 profile likelihood 曲線、聯合似然網格與 reliability 曲線沒有存檔（json 只存摘要值）。要重跑 fs7_review3／review4，包含 200 次 cluster bootstrap 擬合及讀 DB 取窗起點時間。 |
| 論文二 Fig. 1、2、6、S4 | 專案內沒有這些圖檔或產生程式（論文只寫了 caption）。 |

## 已知差異與注意事項

- 四版本由快取 CSV 重繪。部分 CSV 存檔時有四捨五入（perigee persat、drag_thr、shenlong 距離取到 0.01 km），與原圖逐像素比對約有 0.01–0.07% 像素差，肉眼看不出。
- `fig_fs7_injection_metrics` 面板 (a)：由 metrics CSV 依各阻力域試驗數加權重建，等同原本逐試驗平均，差異只來自 CSV 中 recall 取到小數第 3 位。
- `fig_tle_noise_floor_map_contour`：
  - 目前 matplotlib 版本畫出的等高線數值標籤位置，與現有原圖略有不同。
  - 圖中擬合值為 H = 77 km、R² = 0.89，但論文內文寫 H = 79 km、R² = 0.87，需要作者確認。
- 原報告圖 18（fig_shenlong_2026_rpo.png，中文）的「≈」與對數刻度負號，在原檔中是缺字方塊；四版本已用字型 fallback 修正。原檔未動。
- `fig_starlink_v3_profile/` 目錄不是本批程式產生的，不在上述對照表內。
