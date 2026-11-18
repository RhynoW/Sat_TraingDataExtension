# 期末報告 FIN-RPT-01 圖片清單

本資料夾收錄期末報告（`docs/期末報告_20261115.md`，2026-11-18 第九輪版）正文使用之全部圖片，共 23 張，依圖號命名。
內容分兩部分：

- **報告原圖**（本資料夾 `圖NN_*.png`）：報告 DOCX／PDF 實際使用之圖檔複本，原檔在 `docs/`，報告建置仍讀原檔。
- **出版用四版本**（`出版用四版本/圖NN_<stem>/`）：每張圖 8 個檔，中文／英文 × 白底黑字／黑底白字，各有 PNG（600 dpi）與向量 PDF（字型內嵌，文字可選取）。檔名為 `<stem>_<zh|en>_<light|dark>.<png|pdf>`。來源為 `docs/figures_pub/`，產生指令與核對紀錄見 `docs/figures_pub/README.md`。

四版本為依期末審查委員意見③（圖片另存高解析、中／英、白底／黑底版本）製作。圖 4、5、11–17 之原產生程式已不存在，由 `docs/gen_fig_report_r_series.py` 重寫，重繪後之數字已與原圖核對；圖 4、13 之標題與圖例依委員意見④改為直述，圖 13 判定線改依程式公式繪製（說明見 `docs/figures_pub/README.md`）。四版本與報告原圖在版面與用字上可能略有差異，報告內容以報告原圖為準。

| 圖號 | 報告原圖檔名 | 原檔 | 像素（寬×高） | 圖說 |
|---|---|---|---|---|
| 圖 1 | 圖01_fig_sys_architecture.png | `docs/fig_sys_architecture.png` | 2440×1679 | 系統總架構 |
| 圖 2 | 圖02_fig_sys_routing.png | `docs/fig_sys_routing.png` | 2240×1160 | App 統一偵測摘要之路由 |
| 圖 3 | 圖03_fig_sys_r7_flow.png | `docs/fig_sys_r7_flow.png` | 2440×1560 | R7 單星報表判定流程 |
| 圖 4 | 圖04_fig_r5_p2_parabola.png | `docs/fig_r5_p2_parabola.png` | 1170×690 | P2 高度自適應門檻 |
| 圖 5 | 圖05_fig_r1_nrlmsis_density.png | `docs/fig_r1_nrlmsis_density.png` | 1125×690 | NRLMSIS 大氣密度隨高度與太空天氣之變化 |
| 圖 6 | 圖06_fig_paperA_rv1_fig1_zh_light.png | `docs/figures_pub/fig_paperA_rv1_fig1/fig_paperA_rv1_fig1_zh_light.png` | 7407×3025 | DORIS 營運方紀錄之無機動弧段上 TLE 半長軸變異 |
| 圖 7 | 圖07_fig_nrlmsis_decay_expect.png | `docs/fig_nrlmsis_decay_expect.png` | 1920×1312 | NRLMSIS 預期之自然軌道衰減率（2024-01 至 2026-11，300–1000 km） |
| 圖 8 | 圖08_fig_perigee_drag_corr_x30.png | `docs/fig_perigee_drag_corr_x30.png` | 2550×840 | 近地點分檔 425 顆衛星（2024-01 迄今） |
| 圖 9 | 圖09_fig_nrlmsis_solar_tracking_x30.png | `docs/fig_nrlmsis_solar_tracking_x30.png` | 1765×1638 | 衰減率隨太陽活動之起伏 |
| 圖 10 | 圖10_fig_fs7_precise_nrlmsis.png | `docs/fig_fs7_precise_nrlmsis.png` | 1899×1512 | 福衛七號精密軌道衰減率與 NRLMSIS 預期（2024-01 迄今，不含 FORMOSAT7-3） |
| 圖 11 | 圖11_fig_r3_joint_element.png | `docs/fig_r3_joint_element.png` | 1230×810 | STARLINK-37471 於 2026-06-21 之升軌 |
| 圖 12 | 圖12_fig_r9_planupload.png | `docs/fig_r9_planupload.png` | 1425×630 | 相鄰 MEME 發布檔之位置差 |
| 圖 13 | 圖13_fig_r2_starlink_planes.png | `docs/fig_r2_starlink_planes.png` | 1230×660 | Starlink 215 個軌道面之面內傾角變化標準差（由大至小排列） |
| 圖 14 | 圖14_fig_r8_fs_family.png | `docs/fig_r8_fs_family.png` | 1575×630 | 福衛家族高度時序 |
| 圖 15 | 圖15_fig_r7_fs7_fleet.png | `docs/fig_r7_fs7_fleet.png` | 1425×720 | 福衛七號 6 顆高度時序（2024-01 至 2026-07） |
| 圖 16 | 圖16_fig_r4_shenlong_release.png | `docs/fig_r4_shenlong_release.png` | 1290×870 | CSSHQ-1 與物體 G 相對運動重建（TLE／SGP4，非高精度定軌） |
| 圖 17 | 圖17_fig_r6_shenlong_height.png | `docs/fig_r6_shenlong_height.png` | 1575×630 | 平均高度時序（TLE，非高精度定軌） |
| 圖 18 | 圖18_fig_shenlong_2026_rpo.png | `docs/fig_shenlong_2026_rpo.png` | 1540×784 | 神龍太空梭第 4 次任務 |
| 圖 19 | 圖19_fig_tasa15_timeline_r7.png | `docs/fig_tasa15_timeline_r7.png` | 2480×1150 | 15 顆衛星候選事件時間軸（R7）。圓點顏色為證據等級，大小與 \|淨 Δa\| 成正比 |
| 圖 20 | 圖20_fig_starlink_v3_profile.png | `docs/fig_starlink_v3_profile.png` | 2179×1693 | Starlink V3 第一批 26 顆入軌後之軌道行為（TLE，資料至 2026-11-18） |
| 圖 21 | 圖21_fig_sys_app_vs_r7.png | `docs/fig_sys_app_vs_r7.png` | 2440×1039 | App 即時查詢與 R7 單星報表之判定方式對照 |
| 圖 22 | 圖22_fig_tasa15_detect_vs_alt_r7.png | `docs/fig_tasa15_detect_vs_alt_r7.png` | 1680×1173 | 軌道高度與可偵測機動大小（R7 偵測能力估計，資料至 2026-11-14）。上 |
| 圖 23 | 圖23_fig_drag_resid_threshold.png | `docs/fig_drag_resid_threshold.png` | 2535×837 | 阻力殘差門檻研討 |
