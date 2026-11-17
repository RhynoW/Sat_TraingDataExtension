'use strict';
/* StoryMaps 式敘事渲染器：
   /story        → 故事清單卡片
   /story/<id>   → 依 /api/story/<id> 之 JSON 渲染章節：
     text      {title, body}
     table     {title, columns, rows, row_anchors?, note?}
     sat       {title, norads[], body, anchor, start?, row?, autoplay?, height?}
     positions {title, body, mode, val?, ids?, sequence?, height?}   世界地圖位置分布
     embed     {title, body, url, height}                            任意頁面內嵌
   ?autoplay=<總秒數> → 自動導覽：依各節 dur 權重分配時間、平滑捲動走完全篇。

   雙語（繁中／日文）：I18N 字典 + t()/tpl()/setLang()，模式參照 starlink.js。
   只翻譯本檔案自產生的介面控制項文字（按鈕、標籤、表頭、圖說、提示訊息）；
   故事 JSON（title/body/columns/rows/note 等）與其他 API 動態回傳內容（PROV.*、
   d.note、d.method.* 等後端組字串）維持原樣不翻譯。 */

// ── 雙語字典（zh / ja）──────────────────────────────────────────────────────
const I18N = {
  zh: {
    doc_title_list: 'Story — 太空態勢敘事',
    hdr_title_default: '太空態勢敘事',
    nav_prev: '上一步', nav_prev_title: '上一步（↑ / PageUp）',
    nav_next: '下一步', nav_next_title: '下一步（↓ / PageDown）',
    lnk_list: '故事清單', nav_home: '返回主頁', loading_text: '載入中…',

    list_title: '太空態勢敘事',
    list_sub: 'StoryMaps 式互動故事 — 以軌道資料說故事',
    list_updated: '更新：{d}',
    list_empty: '尚無故事。',

    err_story_not_found: '故事不存在。', err_story_back: '回清單',
    err_load_fail: '載入失敗：{err}',
    ph_scroll_load: '捲動至此載入…',
    ph_scroll_load_orbit: '捲動至此載入軌道視圖…',
    ph_scroll_load_pos: '捲動至此載入位置分布…',
    open_full_page: '開啟完整頁面 ↗',

    prov_title: '資料口徑',
    prov_stale_prefix: '⚠ TLE 資料齡 {age}',
    prov_ok_prefix: 'TLE 最新 epoch {date}・資料齡 {age}',
    prov_age_day: '{n} 天',
    prov_row_source: '資料來源',
    prov_row_catalog: '目錄／有效',
    prov_row_catalog_val: '{cat} 顆去重 NORAD（{rec} 筆 TLE）；≤7 天有 TLE 可傳播 {fresh} 顆',
    prov_row_history: '歷史範圍',
    prov_future_flag: '（含未來 epoch）',
    prov_row_version: '版本／狀態',
    prov_commit_prefix: 'commit {c}・',
    prov_status_default: '技術展示／非操作級',
    prov_row_db_update: '資料庫更新',
    prov_row_propagator: '傳播模型',
    prov_row_frame: '座標系',
    prov_row_accuracy: '精度等級',
    prov_row_pc: '接近篩選參數',
    prov_row_maneuver: '軌道變化候選',
    prov_row_snapshot: '口徑快照',
    prov_row_snapshot_val: '{t} UTC（頁面產生時間；未來 epoch 之 TLE 為 GEO 平根數常態，傳播一律以「不晚於現在之最新 epoch」為準）',

    pos_load_fail: '位置資料載入失敗',
    pos_cap: '衛星數：{n}｜TLE 傳播位置，計算時刻 {t} UTC{epoch}',
    pos_cap_epoch: '｜TLE 最新 epoch {d}（資料齡 {age} 天）',

    regime_heo_other: 'HEO/其他',
    globe_label_cap: '標籤：正面且不重疊者，上限 {n}（隨旋轉輪替）',

    gs_kpi_objects: '在軌物體（不含碎片／火箭體）', gs_kpi_regime: '軌道域',
    gs_kpi_alt_median: '高度中位數', gs_kpi_launch_range: '發射年份範圍',
    gs_bars_launch: '歷年發射數（依目錄發射日期）',
    gs_bars_alt: '高度分佈（km；LEO 每 100 km 一格，MEO／GEO 各一格）',
    gs_note: '點選衛星開啟逐日軌道歷史（SMA 圓形圖＋Spiral Polar，近一年）。',

    isr_bars_sensor: '感測器類型（顆）', isr_bars_res: '成像解析度級別（光學＋SAR，顆）', isr_unclassified: '未分類',
    th_isr_series: '系列', th_isr_count: '顆', th_isr_sensor: '感測器',
    th_isr_res: '解析度級別', th_isr_note: '註記',
    isr_note_suffix: '（圖中 * 為推估級別；單位 m）',
    sensor_光學: '光學', sensor_SAR: 'SAR', sensor_射頻訊號: '射頻訊號',
    sensor_氣象掩星: '氣象掩星', sensor_技術試驗: '技術試驗', sensor_導航: '導航',

    legend_before: '建立前', legend_after: '建立後（＋台灣站）',

    man_connector: '；大陸群組另含：',
    man_kpi_sats: '星系衛星數', man_kpi_events: '2026 機動候選事件',
    man_kpi_sats_with_event: '有事件之衛星', man_kpi_sats_with_event_val: '{n}（{pct}%）',
    man_kpi_rate100: '每 100 顆衛星事件數', man_kpi_rate1000: '每千次 TLE 轉移事件數',
    man_kpi_median_da: '中位 |Δa|', man_kpi_prc_flag: 'PRC 管線旗標事件（1–5 月）',
    man_bars_month: '月分佈', man_note_top: '最活躍衛星（事件數）',
    man_details_summary: '最大 |Δa| 事件（前 {n}）：前後 TLE epoch、間隔、等效 Δv',
    th_man_sat: '衛星', th_man_tle_before: 'TLE 前', th_man_tle_after: 'TLE 後',
    th_man_gap_h: '間隔 (h)', th_man_da: 'Δa (km)', th_man_dv: '等效 Δv (m/s)', th_man_regime: '軌道域',
    man_final_note: '候選 ≠ 已確認：Δv 是由 Δa 依 Δv≈n·Δa/2 換算的等效值（假設切向脈衝）。其他可能解釋包括 TLE 品質雜訊／軌道決定更新、LEO 大氣阻力模型誤差，以及資料缺漏造成的跳變。確認機動需要精密星曆或多來源交叉驗證。',

    radar_kpi_arcs: '每日追蹤弧段（平均／顆）', radar_kpi_gap: '最大無觀測間隙',
    radar_kpi_track_min: '累計追蹤時間／24 h', radar_kpi_taiwan_only: '僅台灣站可見（全球站皆不可見）',
    radar_kpi_gain: '相對觀測資訊增益（σ∝1/√N 概念指標）', radar_kpi_taiwan_arc_sats: '台灣站有弧段之衛星',
    radar_bars_pb: '建立前 vs 建立後（樣本平均）',
    radar_bars_map: '地面站佈局：全球已知 SSN 站（{n}）＋台灣假想站',
    th_radar_sat: '衛星', th_radar_arcs: '弧段 前→後', th_radar_taiwan_arc: '台灣弧段',
    th_radar_gap: '最大間隙 前→後（分）', th_radar_precision: '精度提升',
    radar_note: '{model} 樣本：{label} 低軌 {n} 顆，評估起點 {t0}，仰角遮蔽 {mask}°。',
    radar_details_summary: '模型假設表',
    radar_legend_1: '追蹤弧段／日', radar_legend_2: '最大間隙（分）', radar_legend_3: '累計追蹤（分）',

    rv_loading: '傳播星系軌道並計算各仰角門檻的覆蓋率…',
    rv_label_site: '觀測點', rv_label_mask: '地面觀測仰角門檻',
    rv_recalc: '重新計算中…',
    rv_kpi_coverage: '覆蓋率（{h} h 內至少 1 顆在門檻之上）', rv_no_outage: '無中斷',
    rv_kpi_max_gap: '最長無覆蓋空窗', rv_kpi_sat_revisit: '單星重訪週期（中位數）',
    rv_kpi_mean_revisit: '星系級平均通過間隔', rv_kpi_max_simul: '同時可見顆數峰值',
    rv_cap_cov: '覆蓋率 vs 仰角門檻（%）', rv_cap_gap: '最長無覆蓋空窗 vs 仰角門檻（分）',
    rv_cap_timeline: '未來 {h} h 可見顆數時間帶（門檻 {m}°；紅色＝完全無覆蓋）',
    rv_cap_top_gaps: '最長的無覆蓋空窗（門檻 {m}°）',
    th_rv_idx: '#', th_rv_start: '空窗起始（UTC）', th_rv_len: '長度',
    rv_note: '觀測點 {site}；{label} {n} 顆（TLE 可傳播）；時窗 {h} h、取樣 {step} s。「單星重訪週期」為同一顆衛星再次通過的間隔中位數（傳統 revisit period 定義）；「星系級平均通過間隔」為任一顆衛星通過的平均間隔，星系規模愈大此值愈小，兩者不可混用。{censored}中位通過長度 {pmed}，中位最大仰角 {emed}。',
    rv_censored: '時窗頭尾另有被截斷之空窗（至少 {n} 分），未計入統計。',
    site_taipei: '台北', site_taichung: '台中', site_tropic: '北回歸線（嘉義）',
    site_eluanbi: '鵝鑾鼻', site_nangan: '馬祖南竿', site_kinmen: '金門',

    tl_peak: '峰值 {n} 顆',

    sky_no_sat: '無可示範衛星', sky_kpi_sat: '衛星',
    sky_kpi_passes: '未來 24 h 通過次數', sky_kpi_max_el: '最高仰角',
    th_sky_idx: '#', th_sky_aos: 'AOS（UTC）', th_sky_los: 'LOS',
    th_sky_maxel: '最大仰角', th_sky_dur: '時長',
    sky_note: '站點：{name}（{lat}°N, {lon}°E）；仰角遮蔽 {mask}°。',
    sky_no_pass_24h: '24 h 內無衛星通過',
    sky_tracking: '追蹤中（第 {n} 次通過）{t} UTC · Az {az}° · El {el}° · 距離 {rng} km',

    hero_site_role: '{label} 備援觀測點', hero_site_hint: '可於第五部切換站點',
    hero_next_window: '下一個候選備援窗口（門檻 {m}°）', hero_geo_only: '幾何層，非通聯保證',
    hero_now_covered: '現在即有幾何覆蓋', hero_no_window: '{h} h 內無窗口',
    hero_window_in: '約 {m} 分鐘後', hero_tle_age: 'TLE 資料齡 {n} 天',
    hero_max_gap: '最長無覆蓋空窗（{h} h 內）',
    hero_conjunction: '空間接近關注事件（<{thr} km）', hero_candidate_note: '候選，需人工複核',
    hero_pairs: '{n} 對',
    slh_inorbit: '近 30 天在軌（本系統）', slh_inorbit_sub: 'Space-Track TLE 30 天內有更新',
    slh_kt: 'keeptrack.space 公開在軌', slh_kt_sub: '外部對照 · 累計發射 {n}',
    slh_deorbit: '正在離軌', slh_deorbit_sub: '30 天降逾 40 km 且低於 480 km',
    slh_v3: '疑似 V3（Starship 部署）', slh_v3_sub: '新衛星待 Space-Track 編目後計入',
    slh_shells: '軌道殼層', slh_shells_sub: '依傾角分群',
    sh_kpi_total: '近 {d} 天有 TLE 的 Starlink', sh_kpi_at: '位於工作殼層', sh_kpi_low: '低於 300 km（即將再入）',
    sh_th_shell: '殼層（傾角）', sh_th_count: '顆數', sh_th_work: '目前工作高度', sh_th_range: '高度 P10–P90',
    sh_th_at: '在工作殼層', sh_th_below: '低於（抬軌／降軌中）', sh_th_above: '高於', sh_th_low: '< 300 km',
    sh_retiring: '退役中殼層', sh_note: '工作高度為該殼層最密集的 5 km 高度帶，每次開啟即時計算；±{tol} km 內算作在工作殼層。單筆 TLE 無法分辨抬軌或離軌，「低於」兩者皆含。',

    cdm_kpi_pairs: '<{thr} km 幾何接近配對（TLE 傳播）', cdm_kpi_scanned: '掃描物體數',
    cdm_kpi_elapsed: '{s} s', cdm_kpi_elapsed_label: '向量化 SGP4 掃描耗時',
    cdm_kpi_red_amber: 'RED / AMBER（前 10）',
    th_cdm_primary: '主體', th_cdm_secondary: '次體', th_cdm_miss: '最接近距離',
    th_cdm_pc: '接近篩選參數', th_cdm_level: '等級',
    cdm_expand_btn: '3D 展開',
    cdm_note: '「接近篩選參數」（Pc proxy）僅用於排序供人工複核的事件，並非碰撞判定或正式碰撞機率。幾何篩選（<{thr} km）≠ 碰撞風險；此值為 Chan (2008) 二維近似，σ R/T/N 為固定假設值（{sigma}），不是 CDM 協方差，僅供排序使用；距離約為 0 的對接／共位配對已排除。',

    re_kpi_mc_median: '{name}：數值 MC 中位再入時刻 [TLE-derived]',
    re_kpi_mc_pos: '{name}：MC 中位落點（5–95% 跨度 {h} h）',
    re_kpi_vs_esa: '{name}：本系統 − ESA 預報',
    th_re_sat: '衛星', th_re_last_tle: '最後 TLE', th_re_s1: '階段一 SGP4 近地點掠過',
    th_re_s2: '階段二 數值 MC 中位', th_re_esa: 'ESA 預報 [ESA-reported]', th_re_delta: 'Δ（S1／S2）',
    re_reentered: '（{n}/{total} 次再入）',
    re_hindcast_summary: 'Salsa 2024-09-08 18:47Z 回測（誤差＝本系統 − ESA 實際）與密度尺度校準',
    th_re_hc_lead: '前置', th_re_hc_tle: 'TLE', th_re_hc_s1err: 'S1 誤差',
    th_re_hc_s2err: 'S2 誤差', th_re_hc_mcerr: 'MC 中位誤差', th_re_hc_mcspread: 'MC 跨度',
    re_lead_days: '{n} 天',
    re_calib_note: 'NRLMSIS 密度尺度校準值 ×{scale}（掃描 {scales}，平均誤差 h：{err}）',
    re_spacetrack_note: 'Space-Track 18 SDS 衰減預報（日級）：{s}',
    re_generated: '｜產生 {t}',
    re_msg_suffix: '（{src}，訊息 {msg}）',
    hero_loading: '載入即時狀態…',
  },
  ja: {
    doc_title_list: 'Story — 宇宙状況把握ストーリー',
    hdr_title_default: '宇宙状況把握ストーリー',
    nav_prev: '前へ', nav_prev_title: '前へ（↑ / PageUp）',
    nav_next: '次へ', nav_next_title: '次へ（↓ / PageDown）',
    lnk_list: 'ストーリー一覧', nav_home: 'ホームに戻る', loading_text: '読み込み中…',

    list_title: '宇宙状況把握ストーリー',
    list_sub: 'StoryMaps 形式のインタラクティブストーリー — 軌道データで語る',
    list_updated: '更新日：{d}',
    list_empty: 'ストーリーはまだありません。',

    err_story_not_found: 'ストーリーが見つかりません。', err_story_back: '一覧に戻る',
    err_load_fail: '読み込み失敗：{err}',
    ph_scroll_load: 'スクロールすると読み込まれます…',
    ph_scroll_load_orbit: 'スクロールすると軌道ビューが読み込まれます…',
    ph_scroll_load_pos: 'スクロールすると位置分布が読み込まれます…',
    open_full_page: '全画面で開く ↗',

    prov_title: 'データの出典・品質',
    prov_stale_prefix: '⚠ TLEデータの経過日数：{age}',
    prov_ok_prefix: 'TLE最新エポック {date}・データ齢 {age}',
    prov_age_day: '{n} 日',
    prov_row_source: 'データソース',
    prov_row_catalog: 'カタログ／有効',
    prov_row_catalog_val: '{cat} 機（重複を除いたNORADオブジェクト）（TLE {rec} 件）；直近7日以内のTLEで伝播可能 {fresh} 機',
    prov_row_history: '収録期間',
    prov_future_flag: '（未来エポックを含む）',
    prov_row_version: 'バージョン／状態',
    prov_commit_prefix: 'commit {c}・',
    prov_status_default: '技術デモ／非運用レベル',
    prov_row_db_update: 'データベース更新',
    prov_row_propagator: '伝播モデル',
    prov_row_frame: '座標系',
    prov_row_accuracy: '精度レベル',
    prov_row_pc: '近接スクリーニングパラメータ',
    prov_row_maneuver: '軌道変化候補',
    prov_row_snapshot: '出典スナップショット',
    prov_row_snapshot_val: '{t} UTC（ページ生成時刻。未来エポックのTLEはGEOの平均軌道要素として一般的であり、伝播は常に「現在時刻以前で最新のエポック」を基準とする）',

    pos_load_fail: '位置データの読み込みに失敗しました',
    pos_cap: '衛星数：{n}｜TLE伝播位置、計算時刻 {t} UTC{epoch}',
    pos_cap_epoch: '｜TLE最新エポック {d}（データ齢 {age} 日）',

    regime_heo_other: 'HEO/その他',
    globe_label_cap: 'ラベル：正面かつ重ならないもののみ、上限 {n}（回転に伴い入れ替わり）',

    gs_kpi_objects: '軌道上物体（デブリ・ロケット体を除く）', gs_kpi_regime: '軌道域',
    gs_kpi_alt_median: '高度中央値', gs_kpi_launch_range: '打上げ年範囲',
    gs_bars_launch: '年別打上げ数（カタログの打上げ日ベース）',
    gs_bars_alt: '高度分布（km；LEOは100kmごと、MEO／GEOはそれぞれ1区分）',
    gs_note: '衛星をクリックすると日次の軌道履歴（SMA円形図＋スパイラル極座標図、直近1年）が開きます。',

    isr_bars_sensor: 'センサー種別（機）', isr_bars_res: '撮像分解能クラス（光学＋SAR、機）', isr_unclassified: '未分類',
    th_isr_series: '系列', th_isr_count: '機', th_isr_sensor: 'センサー',
    th_isr_res: '分解能クラス', th_isr_note: '備考',
    isr_note_suffix: '（図中の * は推定クラス；単位 m）',
    sensor_光學: '光学', sensor_SAR: 'SAR', sensor_射頻訊號: '電波信号',
    sensor_氣象掩星: '気象掩蔽', sensor_技術試驗: '技術試験', sensor_導航: '航法',

    legend_before: '設置前', legend_after: '設置後（＋台湾局）',

    man_connector: '；中国大陸グループはさらに次を含む：',
    man_kpi_sats: 'コンステレーションの衛星数', man_kpi_events: '2026年の候補機動イベント',
    man_kpi_sats_with_event: 'イベントのある衛星', man_kpi_sats_with_event_val: '{n}（{pct}%）',
    man_kpi_rate100: '衛星100機あたりのイベント数', man_kpi_rate1000: 'TLE遷移1,000回あたりのイベント数',
    man_kpi_median_da: '中央値 |Δa|', man_kpi_prc_flag: 'PRCパイプライン旗標イベント（1〜5月）',
    man_bars_month: '月別分布', man_note_top: '最も活発な衛星（イベント数）',
    man_details_summary: '最大 |Δa| イベント（上位 {n} 件）：前後のTLEエポック、間隔、等価Δv',
    th_man_sat: '衛星', th_man_tle_before: 'TLE前', th_man_tle_after: 'TLE後',
    th_man_gap_h: '間隔 (h)', th_man_da: 'Δa (km)', th_man_dv: '等価Δv (m/s)', th_man_regime: '軌道域',
    man_final_note: '候補 ≠ 確定：Δvは、Δv≈n·Δa/2（接線方向のインパルスを仮定）によりΔaから換算した等価値です。その他の可能性として、TLE品質のばらつき／軌道決定の更新、LEOにおける大気抵抗モデル誤差、データ欠落による不連続な変化が考えられます。機動の確認には、精密暦または複数情報源による相互検証が必要です。',

    radar_kpi_arcs: '1日あたりの追跡アーク（平均／機）', radar_kpi_gap: '最大無観測ギャップ',
    radar_kpi_track_min: '累積追跡時間／24時間', radar_kpi_taiwan_only: '台湾局のみ可視（他の全世界局では不可視）',
    radar_kpi_gain: '相対観測情報利得（σ∝1/√N の概念指標）', radar_kpi_taiwan_arc_sats: '台湾局でアークのある衛星',
    radar_bars_pb: '設置前 vs 設置後（サンプル平均）',
    radar_bars_map: '地上局配置：既知の全世界SSN局（{n}）＋台湾仮想局',
    th_radar_sat: '衛星', th_radar_arcs: 'アーク 前→後', th_radar_taiwan_arc: '台湾アーク',
    th_radar_gap: '最大ギャップ 前→後（分）', th_radar_precision: '精度向上',
    radar_note: '{model} サンプル：{label} 低軌道 {n} 機、評価起点 {t0}、仰角マスク {mask}°。',
    radar_details_summary: 'モデル前提条件',
    radar_legend_1: '追跡アーク／日', radar_legend_2: '最大ギャップ（分）', radar_legend_3: '累積追跡（分）',

    rv_loading: 'コンステレーション軌道を伝播し、各仰角しきい値でのカバレッジ率を計算中…',
    rv_label_site: '観測地点', rv_label_mask: '地上観測の仰角しきい値',
    rv_recalc: '再計算中…',
    rv_kpi_coverage: 'カバレッジ率（{h}時間以内に1機以上がしきい値を超える）', rv_no_outage: '中断なし',
    rv_kpi_max_gap: '最長のカバレッジ空白時間', rv_kpi_sat_revisit: '単一衛星の再訪周期（中央値）',
    rv_kpi_mean_revisit: 'コンステレーションレベルの平均通過間隔', rv_kpi_max_simul: '同時可視機数のピーク',
    rv_cap_cov: 'カバレッジ率 vs 仰角しきい値（%）', rv_cap_gap: '最長のカバレッジ空白時間 vs 仰角しきい値（分）',
    rv_cap_timeline: '今後 {h} 時間の可視衛星数の推移（しきい値 {m}°；赤＝カバレッジなし）',
    rv_cap_top_gaps: '最長のカバレッジ空白時間（しきい値 {m}°）',
    th_rv_idx: '#', th_rv_start: 'ギャップ開始（UTC）', th_rv_len: '長さ',
    rv_note: '観測地点 {site}；{label} {n} 機（TLE伝播可能）；時間窓 {h} 時間、サンプリング間隔 {step} 秒。「単一衛星の再訪周期」は同一衛星が再び通過するまでの間隔の中央値（従来のrevisit period定義）であり、「コンステレーションレベルの平均通過間隔」はいずれかの衛星が通過する平均間隔で、コンステレーション規模が大きいほど値は小さくなる — 両者を混同しないこと。{censored}通過時間の中央値 {pmed}、最大仰角の中央値 {emed}。',
    rv_censored: '時間窓の前後には打ち切られたギャップ（少なくとも {n} 分）が別途存在し、統計には含まれていない。',
    site_taipei: '台北', site_taichung: '台中', site_tropic: '北回帰線（嘉義）',
    site_eluanbi: '鵝鑾鼻（ガランビ）', site_nangan: '馬祖南竿（ナンカン）', site_kinmen: '金門（キンモン）',

    tl_peak: 'ピーク {n} 機',

    sky_no_sat: 'デモ可能な衛星がありません', sky_kpi_sat: '衛星',
    sky_kpi_passes: '今後24時間の通過回数', sky_kpi_max_el: '最大仰角',
    th_sky_idx: '#', th_sky_aos: 'AOS（UTC）', th_sky_los: 'LOS',
    th_sky_maxel: '最大仰角', th_sky_dur: '継続時間',
    sky_note: '観測局：{name}（{lat}°N, {lon}°E）；仰角マスク角 {mask}°。',
    sky_no_pass_24h: '24時間以内に衛星の通過はありません',
    sky_tracking: '追跡中（{n}回目の通過）{t} UTC · 方位角 {az}° · 仰角 {el}° · 距離 {rng} km',

    hero_site_role: '{label} バックアップ観測地点', hero_site_hint: '第5部で観測地点を切り替え可能',
    hero_next_window: '次の候補バックアップ時間帯（しきい値 {m}°）', hero_geo_only: '幾何レベルであり、通信保証ではない',
    hero_now_covered: '現在すでに幾何学的カバレッジあり', hero_no_window: '{h} 時間以内にウィンドウなし',
    hero_window_in: '約 {m} 分後', hero_tle_age: 'TLEデータ齢 {n} 日',
    hero_max_gap: '最長のカバレッジ空白時間（{h}時間以内）',
    hero_conjunction: '近接監視イベント（<{thr} km）', hero_candidate_note: '候補であり、目視確認が必要',
    hero_pairs: '{n} 組',
    slh_inorbit: '直近30日の在軌数（本システム）', slh_inorbit_sub: 'Space-Track TLE が30日以内に更新',
    slh_kt: 'keeptrack.space 公開在軌数', slh_kt_sub: '外部比較 · 累計打ち上げ {n}',
    slh_deorbit: '離軌中', slh_deorbit_sub: '30日で40 km超低下かつ480 km未満',
    slh_v3: 'V3 と推定（Starship 展開）', slh_v3_sub: '新衛星は Space-Track 登録後に計上',
    slh_shells: '軌道シェル', slh_shells_sub: '軌道傾斜角でグループ化',
    sh_kpi_total: '直近{d}日にTLEがあるStarlink', sh_kpi_at: '運用シェル内', sh_kpi_low: '300 km未満（再突入間近）',
    sh_th_shell: 'シェル（傾斜角）', sh_th_count: '機数', sh_th_work: '現在の運用高度', sh_th_range: '高度 P10–P90',
    sh_th_at: '運用シェル内', sh_th_below: '下（軌道上昇／降下中）', sh_th_above: '上', sh_th_low: '< 300 km',
    sh_retiring: '退役中のシェル', sh_note: '運用高度は各シェルで最も衛星が密集する5 km帯で、開くたびにリアルタイム計算します。±{tol} km 以内を運用シェル内とします。単一のTLEでは軌道上昇と離軌を区別できないため、「下」には両方が含まれます。',

    cdm_kpi_pairs: '<{thr} km 幾何接近ペア（TLE伝播）', cdm_kpi_scanned: 'スキャン物体数',
    cdm_kpi_elapsed: '{s} 秒', cdm_kpi_elapsed_label: 'ベクトル化SGP4スキャン所要時間',
    cdm_kpi_red_amber: 'RED / AMBER（上位10件）',
    th_cdm_primary: '主天体', th_cdm_secondary: '副天体', th_cdm_miss: '最接近距離',
    th_cdm_pc: '近接スクリーニングパラメータ', th_cdm_level: 'レベル',
    cdm_expand_btn: '3D展開',
    cdm_note: '「近接スクリーニングパラメータ」（Pc proxy）は、目視確認が必要なイベントの順位付けにのみ使用し、衝突判定でも正式な衝突確率でもありません。幾何学的スクリーニング（<{thr} km）≠衝突リスクです。この値はChan (2008)の2次元近似で、σ R/T/Nは固定の仮定値（{sigma}）であり、CDM共分散ではありません。順位付け専用で、距離が約0のドッキング／共位置ペアは除外済みです。',

    re_kpi_mc_median: '{name}：数値MC中央値再突入時刻 [TLE-derived]',
    re_kpi_mc_pos: '{name}：MC中央値の落下地点（5–95%レンジ {h} 時間）',
    re_kpi_vs_esa: '{name}：本システム − ESA予報',
    th_re_sat: '衛星', th_re_last_tle: '最終TLE', th_re_s1: '段階1 SGP4近地点通過',
    th_re_s2: '段階2 数値MC中央値', th_re_esa: 'ESA予報 [ESA-reported]', th_re_delta: 'Δ（S1／S2）',
    re_reentered: '（{n}/{total} 回再突入）',
    re_hindcast_summary: 'Salsa 2024-09-08 18:47Z の事後再現計算（hindcast）（誤差＝本システム − ESA実測）と密度スケール較正',
    th_re_hc_lead: 'リード', th_re_hc_tle: 'TLE', th_re_hc_s1err: 'S1誤差',
    th_re_hc_s2err: 'S2誤差', th_re_hc_mcerr: 'MC中央値誤差', th_re_hc_mcspread: 'MCレンジ',
    re_lead_days: '{n} 日',
    re_calib_note: 'NRLMSIS密度スケール較正値 ×{scale}（走査 {scales}、平均誤差 h：{err}）',
    re_spacetrack_note: 'Space-Track 18 SDS 再突入・軌道減衰予測（日次）：{s}',
    re_generated: '｜生成 {t}',
    re_msg_suffix: '（{src}、メッセージ {msg}）',
    hero_loading: 'リアルタイム状態を読み込み中…',
  },
  en: {
    doc_title_list: 'Story — Space Situational Awareness (SSA) Narratives',
    hdr_title_default: 'Space Situational Awareness (SSA) Narratives',
    nav_prev: 'Previous', nav_prev_title: 'Previous (↑ / PageUp)',
    nav_next: 'Next', nav_next_title: 'Next (↓ / PageDown)',
    lnk_list: 'Story List', nav_home: 'Back to Home', loading_text: 'Loading…',

    list_title: 'Space Situational Awareness (SSA) Narratives',
    list_sub: 'StoryMaps-style interactive stories — telling stories with orbital data',
    list_updated: 'Updated: {d}',
    list_empty: 'No stories yet.',

    err_story_not_found: 'Story not found.', err_story_back: 'Back to list',
    err_load_fail: 'Failed to load: {err}',
    ph_scroll_load: 'Scroll here to load…',
    ph_scroll_load_orbit: 'Scroll here to load the orbit view…',
    ph_scroll_load_pos: 'Scroll here to load the position distribution…',
    open_full_page: 'Open full page ↗',

    prov_title: 'Data Provenance',
    prov_stale_prefix: '⚠ TLE data age: {age}',
    prov_ok_prefix: 'Latest TLE epoch {date} · Data age {age}',
    prov_age_day: '{n} days',
    prov_row_source: 'Data Source',
    prov_row_catalog: 'Catalog / Valid',
    prov_row_catalog_val: '{cat} de-duplicated NORAD objects ({rec} TLE records); {fresh} propagable using TLE data no more than 7 days old',
    prov_row_history: 'Historical Range',
    prov_future_flag: ' (includes future epochs)',
    prov_row_version: 'Version / Status',
    prov_commit_prefix: 'commit {c} · ',
    prov_status_default: 'Technical Demonstration / Not for Operations',
    prov_row_db_update: 'Database Updated',
    prov_row_propagator: 'Propagator',
    prov_row_frame: 'Reference Frame',
    prov_row_accuracy: 'Accuracy Level',
    prov_row_pc: 'Close-Approach Screening Parameter',
    prov_row_maneuver: 'Orbital Change Candidate',
    prov_row_snapshot: 'Data Provenance Snapshot',
    prov_row_snapshot_val: '{t} UTC (page generation time; future-epoch TLEs are typical for GEO mean elements — propagation always uses the "latest epoch not later than now")',

    pos_load_fail: 'Failed to load position data',
    pos_cap: 'Satellites: {n} | TLE-propagated positions, computed at {t} UTC{epoch}',
    pos_cap_epoch: ' | Latest TLE epoch {d} (data age {age} days)',

    regime_heo_other: 'HEO/Other',
    globe_label_cap: 'Labels: near-side and non-overlapping only, capped at {n} (rotates with the view)',

    gs_kpi_objects: 'Objects in Orbit (excl. debris/rocket bodies)', gs_kpi_regime: 'Orbital regime',
    gs_kpi_alt_median: 'Median altitude', gs_kpi_launch_range: 'Launch year range',
    gs_bars_launch: 'Launches by year (catalog launch date)',
    gs_bars_alt: 'Altitude distribution (km; LEO in 100 km bins, MEO/GEO each one bin)',
    gs_note: 'Click a satellite to open its daily orbit history (SMA circular plot + spiral polar plot, past year).',

    isr_bars_sensor: 'Sensor type (satellites)', isr_bars_res: 'Imaging resolution class (optical + SAR, satellites)', isr_unclassified: 'Unclassified',
    th_isr_series: 'Series', th_isr_count: 'Sats', th_isr_sensor: 'Sensor',
    th_isr_res: 'Resolution class', th_isr_note: 'Note',
    isr_note_suffix: ' (* denotes an estimated class; units in m)',
    sensor_光學: 'Optical', sensor_SAR: 'SAR', sensor_射頻訊號: 'RF signals',
    sensor_氣象掩星: 'Meteorological Radio Occultation', sensor_技術試驗: 'Technology demonstration', sensor_導航: 'Navigation',

    legend_before: 'Before', legend_after: 'After (+ Taiwan station)',

    man_connector: '; the PRC group additionally includes: ',
    man_kpi_sats: 'Constellation satellites', man_kpi_events: '2026 candidate maneuver events',
    man_kpi_sats_with_event: 'Satellites with events', man_kpi_sats_with_event_val: '{n} ({pct}%)',
    man_kpi_rate100: 'Events per 100 satellites', man_kpi_rate1000: 'Events per 1,000 TLE-to-TLE transitions',
    man_kpi_median_da: 'Median |Δa|', man_kpi_prc_flag: 'PRC pipeline-flagged events (Jan–May)',
    man_bars_month: 'Monthly distribution', man_note_top: 'Most active satellites (event count)',
    man_details_summary: 'Largest |Δa| events (top {n}): before/after TLE epoch, interval, equivalent Δv',
    th_man_sat: 'Satellite', th_man_tle_before: 'TLE before', th_man_tle_after: 'TLE after',
    th_man_gap_h: 'Interval (h)', th_man_da: 'Δa (km)', th_man_dv: 'Equivalent Δv (m/s)', th_man_regime: 'Regime',
    man_final_note: 'Candidate ≠ confirmed: Δv is an equivalent value derived from Δa using Δv≈n·Δa/2, assuming a tangential impulse. Alternative explanations include TLE-quality noise or orbit-determination updates, atmospheric-drag model errors in LEO, and discontinuities caused by missing data. Confirming a maneuver requires precise ephemerides or cross-validation from multiple sources.',

    radar_kpi_arcs: 'Mean daily tracking arcs per satellite', radar_kpi_gap: 'Largest unobserved interval',
    radar_kpi_track_min: 'Cumulative tracking time per 24 h', radar_kpi_taiwan_only: 'Visible only from the Taiwan station (not visible from any other global station)',
    radar_kpi_gain: 'Relative observation information gain (σ∝1/√N concept metric)', radar_kpi_taiwan_arc_sats: 'Satellites with an arc at the Taiwan station',
    radar_bars_pb: 'Before vs. after (sample average)',
    radar_bars_map: 'Ground station layout: known global SSN stations ({n}) + hypothetical Taiwan ground station',
    th_radar_sat: 'Satellite', th_radar_arcs: 'Arcs before→after', th_radar_taiwan_arc: 'Taiwan arcs',
    th_radar_gap: 'Max gap before→after (min)', th_radar_precision: 'Precision gain',
    radar_note: '{model} Sample: {label} LEO, {n} satellites; evaluation start time {t0}; elevation mask {mask}°.',
    radar_details_summary: 'Model assumptions',
    radar_legend_1: 'Tracking arcs/day', radar_legend_2: 'Max gap (min)', radar_legend_3: 'Cumulative tracking (min)',

    rv_loading: 'Propagating constellation orbits and computing the coverage rate for each elevation threshold…',
    rv_label_site: 'Observation site', rv_label_mask: 'Ground-observation elevation mask angle',
    rv_recalc: 'Recomputing…',
    rv_kpi_coverage: 'Coverage rate (at least one satellite above threshold within {h} h)', rv_no_outage: 'No outage',
    rv_kpi_max_gap: 'Longest coverage gap', rv_kpi_sat_revisit: 'Single-satellite revisit period (median)',
    rv_kpi_mean_revisit: 'Constellation-level mean pass interval', rv_kpi_max_simul: 'Peak simultaneous visible count',
    rv_cap_cov: 'Coverage rate vs. elevation threshold (%)', rv_cap_gap: 'Longest coverage gap vs. elevation threshold (min)',
    rv_cap_timeline: 'Visible-count time band for the next {h} h (threshold {m}°; red = zero coverage)',
    rv_cap_top_gaps: 'Longest coverage gaps (threshold {m}°)',
    th_rv_idx: '#', th_rv_start: 'Gap start (UTC)', th_rv_len: 'Duration',
    rv_note: 'Observation site {site}; {label}, {n} satellites (TLE-propagable); window {h} h, sampled every {step} s. "Single-satellite revisit period" is the median interval between successive passes of the same satellite (the conventional revisit-period definition); "constellation-level mean pass interval" is the mean interval between passes of any satellite, which shrinks as the constellation grows — the two must not be conflated. {censored}Median pass duration {pmed}; median max elevation {emed}.',
    rv_censored: 'Gaps truncated at the edges of the time window (at least {n} min) exist separately and are not included in the statistics.',
    site_taipei: 'Taipei', site_taichung: 'Taichung', site_tropic: 'Tropic of Cancer (Chiayi)',
    site_eluanbi: 'Eluanbi', site_nangan: 'Nangan, Matsu', site_kinmen: 'Kinmen',

    tl_peak: 'Peak {n} satellites',

    sky_no_sat: 'No satellite available for demonstration', sky_kpi_sat: 'Satellite',
    sky_kpi_passes: 'Passes in the next 24 h', sky_kpi_max_el: 'Max elevation',
    th_sky_idx: '#', th_sky_aos: 'AOS (UTC)', th_sky_los: 'LOS',
    th_sky_maxel: 'Max elevation', th_sky_dur: 'Duration',
    sky_note: 'Station: {name} ({lat}°N, {lon}°E); elevation mask angle: {mask}°.',
    sky_no_pass_24h: 'No satellite passes within 24 h',
    sky_tracking: 'Tracking (pass {n}) {t} UTC · Az {az}° · El {el}° · Range {rng} km',

    hero_site_role: '{label} backup observation site', hero_site_hint: 'Switch sites in Part 5',
    hero_next_window: 'Next candidate backup window (threshold {m}°)', hero_geo_only: 'Geometric layer only — not a communications guarantee',
    hero_now_covered: 'Geometric coverage available now', hero_no_window: 'No window within {h} h',
    hero_window_in: 'In about {m} min', hero_tle_age: 'TLE data age {n} days',
    hero_max_gap: 'Longest coverage gap (within {h} h)',
    hero_conjunction: 'Conjunction watch events (<{thr} km)', hero_candidate_note: 'Candidate — requires manual review',
    hero_pairs: '{n} pairs',
    slh_inorbit: 'In orbit, last 30 days (this system)', slh_inorbit_sub: 'Space-Track TLE updated within 30 days',
    slh_kt: 'keeptrack.space public in-orbit', slh_kt_sub: 'External reference · {n} launched',
    slh_deorbit: 'Deorbiting now', slh_deorbit_sub: '>40 km drop in 30 days and below 480 km',
    slh_v3: 'Suspected V3 (Starship-deployed)', slh_v3_sub: 'Counted once Space-Track catalogs them',
    slh_shells: 'Orbital shells', slh_shells_sub: 'Grouped by inclination',
    sh_kpi_total: 'Starlinks with a TLE in the last {d} days', sh_kpi_at: 'At working shell', sh_kpi_low: 'Below 300 km (reentry imminent)',
    sh_th_shell: 'Shell (inclination)', sh_th_count: 'Count', sh_th_work: 'Current working altitude', sh_th_range: 'Altitude P10–P90',
    sh_th_at: 'At shell', sh_th_below: 'Below (raising / lowering)', sh_th_above: 'Above', sh_th_low: '< 300 km',
    sh_retiring: 'Retiring shell', sh_note: 'The working altitude is the densest 5 km altitude band of each shell, computed live on every visit; satellites within ±{tol} km count as at the shell. A single TLE cannot tell orbit-raising from deorbiting, so "Below" includes both.',

    cdm_kpi_pairs: 'Geometric close-approach pairs <{thr} km (TLE propagation)', cdm_kpi_scanned: 'Objects scanned',
    cdm_kpi_elapsed: '{s} s', cdm_kpi_elapsed_label: 'Vectorized SGP4 scan time',
    cdm_kpi_red_amber: 'RED / AMBER (top 10)',
    th_cdm_primary: 'Primary', th_cdm_secondary: 'Secondary', th_cdm_miss: 'Miss distance',
    th_cdm_pc: 'Close-Approach Screening Parameter', th_cdm_level: 'Level',
    cdm_expand_btn: 'Expand 3D',
    cdm_note: 'The "close-approach screening parameter" (Pc proxy) is used only to rank events for manual review; it is not a collision determination or a formal probability of collision. Geometric screening (<{thr} km) ≠ collision risk. The value is a Chan (2008) 2-D approximation using fixed assumed σ R/T/N values ({sigma}), not a CDM covariance, and is for ranking only. Docking/co-located pairs at approximately zero distance are excluded.',

    re_kpi_mc_median: '{name}: numerical MC median reentry time [TLE-derived]',
    re_kpi_mc_pos: '{name}: MC median reentry location (5–95% spread {h} h)',
    re_kpi_vs_esa: '{name}: this system − ESA forecast',
    th_re_sat: 'Satellite', th_re_last_tle: 'Last TLE', th_re_s1: 'Stage 1 SGP4 perigee pass',
    th_re_s2: 'Stage 2 numerical MC median', th_re_esa: 'ESA forecast [ESA-reported]', th_re_delta: 'Δ (S1/S2)',
    re_reentered: ' ({n}/{total} reentered)',
    re_hindcast_summary: 'Salsa 2024-09-08 18:47Z hindcast (error = this system − ESA actual) and density-scale calibration',
    th_re_hc_lead: 'Lead time', th_re_hc_tle: 'TLE', th_re_hc_s1err: 'S1 error',
    th_re_hc_s2err: 'S2 error', th_re_hc_mcerr: 'MC median error', th_re_hc_mcspread: 'MC spread',
    re_lead_days: '{n} days',
    re_calib_note: 'NRLMSIS density-scale calibration ×{scale} (scan {scales}; mean error h: {err})',
    re_spacetrack_note: 'Space-Track 18 SDS decay forecast (daily): {s}',
    re_generated: ' | generated {t}',
    re_msg_suffix: ' ({src}, message {msg})',
    hero_loading: 'Loading live status…',
  },
};
const LOCALE_MAP = {zh: 'zh-Hant', ja: 'ja-JP', en: 'en-US'};
let LANG = localStorage.getItem('story_lang') || 'zh';
if(!I18N[LANG]) LANG = 'zh';
let CUR_SID = window.STORY_ID || '';

function t(key){
  const d = I18N[LANG] || I18N.zh;
  return (key in d) ? d[key] : (I18N.zh[key] !== undefined ? I18N.zh[key] : key);
}
function tpl(key, vars){
  let s = t(key);
  Object.keys(vars || {}).forEach(k => { s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]); });
  return s;
}
function sensorLabel(zhName){ return t('sensor_' + zhName) !== ('sensor_' + zhName) ? t('sensor_' + zhName) : zhName; }
const SITE_KEY_MAP = {taipei: 'site_taipei', taichung: 'site_taichung', tropic: 'site_tropic',
                      eluanbi: 'site_eluanbi', nangan: 'site_nangan', kinmen: 'site_kinmen'};
function siteLabel(site){
  const k = SITE_KEY_MAP[site.key];
  return k ? t(k) : site.name;
}

// ── 靜態介面文字（story.html 內固定殼層元素）──────────────────────────────────
function applyStaticI18n(){
  document.documentElement.lang = LOCALE_MAP[LANG] || 'zh-Hant';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.getAttribute('data-i18n-title')); });
  document.querySelectorAll('.lang-btn').forEach(b => { b.classList.toggle('active', b.dataset.lang === LANG); });
}

// ── 故事清單快取（供日文版故事自動切換判斷 {id}-ja 是否存在）──────────────────
let STORY_LIST_CACHE = null;
async function getStoryList(){
  if(STORY_LIST_CACHE) return STORY_LIST_CACHE;
  try{ STORY_LIST_CACHE = await (await fetch('/api/story/list')).json(); }
  catch(e){ STORY_LIST_CACHE = []; }
  return STORY_LIST_CACHE;
}
async function findLangVariant(sid, targetLang){
  if(!sid) return null;
  const list = await getStoryList();
  const ids = new Set(list.map(s => s.id));
  if(targetLang === 'ja'){
    if(sid.endsWith('-ja')) return null;
    const cand = sid + '-ja';
    return ids.has(cand) ? cand : null;
  }
  if(sid.endsWith('-ja')){
    const cand = sid.slice(0, -3);
    return ids.has(cand) ? cand : null;
  }
  return null;
}

// ── 語言切換：更新殼層文字，並在有對應 {id}-ja／去 -ja 版本時自動改載入 ──────
async function setLang(lang){
  if(!I18N[lang]) return;
  LANG = lang;
  localStorage.setItem('story_lang', lang);
  applyStaticI18n();
  if(CUR_SID){
    const variant = await findLangVariant(CUR_SID, lang);
    if(variant){
      CUR_SID = variant;
      history.pushState({}, '', '/story/' + variant);
    }
    await renderStory(CUR_SID);
  } else {
    await renderList();
  }
}

function esc(s){
  return String(s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* 表格儲存格：先 esc，再把 markdown 連結 [文字](https://… 或 /站內路徑) 轉為 <a>（僅限表格用） */
function mdCell(s){
  return esc(s).replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function $id(i){ return document.getElementById(i); }

/* ── 資料口徑（provenance）：頁面載入時抓一次，供口徑列／各區塊註記 ── */
let PROV = null;
async function loadProv(){
  try{ PROV = await (await fetch('/api/story/provenance')).json(); }catch(e){ PROV = null; }
  return PROV;
}
function provHtml(){
  if(!PROV) return '';
  const age = PROV.tle_age_days == null ? '—' : tpl('prov_age_day', {n: PROV.tle_age_days});
  const stale = PROV.tle_age_days != null && PROV.tle_age_days > 3;
  const row = (k, v) => '<div class="pv"><span class="k">' + k + '</span><span class="v">' + esc(v || '—') + '</span></div>';
  return '<details class="prov"' + (stale ? ' open' : '') + '><summary>' + t('prov_title') +
    (stale ? '<b class="stale">' + tpl('prov_stale_prefix', {age}) + '</b>' : '<span class="ok">' + tpl('prov_ok_prefix', {date: (PROV.tle_epoch_latest_past || PROV.tle_epoch_max || '').slice(0, 10), age}) + '</span>') +
    '</summary><div class="pgrid">' +
    row(t('prov_row_source'), PROV.source) +
    row(t('prov_row_catalog'), tpl('prov_row_catalog_val', {cat: fmtN(PROV.catalog_sat_count || PROV.valid_sat_count), rec: fmtN(PROV.tle_record_count), fresh: fmtN(PROV.fresh_sat_count_7d)})) +
    row(t('prov_row_history'), (PROV.tle_epoch_min || '').slice(0, 10) + ' ～ ' + (PROV.tle_epoch_max || '').slice(0, 10) + (PROV.tle_epoch_max > (PROV.tle_epoch_latest_past || '') ? t('prov_future_flag') : '')) +
    row(t('prov_row_version'), (PROV.app_commit ? tpl('prov_commit_prefix', {c: PROV.app_commit}) : '') + (PROV.status || t('prov_status_default'))) +
    row(t('prov_row_db_update'), (PROV.db_updated_at || '').slice(0, 16).replace('T', ' ') + ' UTC') + row(t('prov_row_propagator'), PROV.propagator) +
    row(t('prov_row_frame'), PROV.frame) + row(t('prov_row_accuracy'), PROV.accuracy) + row(t('prov_row_pc'), PROV.pc_model) + row(t('prov_row_maneuver'), PROV.maneuver_method) +
    row(t('prov_row_snapshot'), tpl('prov_row_snapshot_val', {t: (PROV.generated_at || '').slice(0, 16).replace('T', ' ')})) +
    '</div></details>';
}

/* ── 故事清單 ── */
async function renderList(){
  const wrap = $id('wrap');
  const r = await fetch('/api/story/list');
  const list = await r.json();
  // 清單頁不用滿頁吸附（否則 hero 100vh + mandatory snap 會把頁面吸回頂端、卡片永遠捲不到）
  document.documentElement.classList.add('nosnap');
  document.title = t('doc_title_list');
  CUR_SID = '';
  let h = '<div class="hero list"><h2>' + esc(t('list_title')) + '</h2>' +
          '<div class="sub">' + esc(t('list_sub')) + '</div></div>' +
          '<div class="cards">';
  list.forEach(s => {
    h += '<a class="card" href="/story/' + esc(s.id) + '"><h4>' + esc(s.title) +
         '</h4><p>' + esc(s.subtitle) + '</p>' +
         (s.updated ? '<div class="up">' + esc(tpl('list_updated', {d: s.updated})) + '</div>' : '') + '</a>';
  });
  h += '</div>';
  if(!list.length) h += '<div style="color:#8b949e;padding:30px 0">' + esc(t('list_empty')) + '</div>';
  wrap.innerHTML = h;
  applyStaticI18n();
}

/* ── orbit 內嵌網址 ── */
function orbitUrl(norad, sec){
  let u = '/orbit?norad=' + norad + '&embed=1';
  if(sec.start) u += '&start=' + sec.start;
  if(sec.row) u += '&row=1';
  if(sec.autoplay) u += '&autoplay=1';
  return u;
}

function satFrame(sec, idx){
  const ns = sec.norads || [];
  const hgt = sec.height || (sec.row ? 760 : 1250);
  let btns = '';
  if(ns.length > 1){
    btns = ns.map((n, i) =>
      '<button class="nbtn' + (i === 0 ? ' on' : '') + '" data-fr="fr' + idx +
      '" data-norad="' + n + '" data-cfg="' + idx + '">NORAD ' + n + '</button>').join('');
  }else if(ns.length === 1){
    btns = '<span style="font-size:12.5px;color:#8b949e">NORAD ' + ns[0] + '</span>';
  }
  return '<div class="sat-head">' + btns +
    '<a class="open" href="/orbit?norad=' + ns[0] + '" target="_blank">' + esc(t('open_full_page')) + '</a></div>' +
    '<div class="frame" id="fr' + idx + '" data-src="' + orbitUrl(ns[0], sec) +
    '" data-h="' + hgt + '"><div class="ph">' + esc(t('ph_scroll_load_orbit')) + '</div></div>';
}

/* 上一步／下一步：以視窗高度為一步（每節恰為 100vh；封面已併入第一節） */
function stepTargets(){ return [...document.querySelectorAll('.sec')]; }
function currentStep(){
  const ts = stepTargets(), y = window.scrollY + window.innerHeight * 0.3;
  let cur = 0;
  ts.forEach((t, i) => { if(t.offsetTop <= y) cur = i; });
  return cur;
}
function goStep(delta){
  const ts = stepTargets();
  const i = Math.max(0, Math.min(ts.length - 1, currentStep() + delta));
  ts[i].scrollIntoView({behavior: 'smooth', block: 'start'});
}
function setupStepNav(){
  const nav = $id('stepnav'); if(!nav) return;
  nav.style.display = '';
  $id('nav-prev').onclick = () => goStep(-1);
  $id('nav-next').onclick = () => goStep(1);
  const upd = () => {
    const i = currentStep(), n = stepTargets().length;
    $id('nav-prev').disabled = i <= 0; $id('nav-next').disabled = i >= n - 1;
  };
  window.addEventListener('scroll', upd, {passive: true}); upd();
  document.addEventListener('keydown', e => {
    if(e.target.matches('input,select,textarea,button')) return;
    if(e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' '){ e.preventDefault(); goStep(1); }
    if(e.key === 'ArrowUp' || e.key === 'PageUp'){ e.preventDefault(); goStep(-1); }
  });
}

function frameHeight(px){ return Math.min(px || 1250, window.innerHeight - 150) + 'px'; }

function loadFrame(fr){
  if(fr.querySelector('iframe')) return;
  const ifr = document.createElement('iframe');
  ifr.src = fr.dataset.src;
  ifr.style.height = frameHeight(+fr.dataset.h);
  fr.appendChild(ifr);
  const ph = fr.querySelector('.ph'); if(ph) ph.remove();
}

/* ── positions 世界地圖／3D 球體 ── */
const PM = {};   // pmId -> {sats, names, focus, cv, seqTimer, …3D: units, rot}
const RE_KM = 6378.137;

async function initPosMap(box){
  if(box.classList.contains('inited')) return;
  box.classList.add('inited');
  const pmId = box.id;
  let url = '/api/story/positions?mode=' + box.dataset.mode;
  if(box.dataset.val) url += '&val=' + encodeURIComponent(box.dataset.val);
  if(box.dataset.ids) url += '&val=' + box.dataset.ids + '&mode=ids';
  let d;
  try{
    const r = await fetch(url);
    d = await r.json();
  }catch(e){ box.innerHTML = '<div class="ph">' + esc(t('pos_load_fail')) + '</div>'; return; }
  const st = PM[pmId] = {sats: d.sats || [], names: d.names || {}, focus: -1};
  box.innerHTML = '<canvas></canvas>';
  st.cv = box.querySelector('canvas');
  const capEl = box.parentElement.querySelector('.pm-cap');
  if(capEl) capEl.textContent = tpl('pos_cap', {
    n: d.count,
    t: new Date(d.timestamp).toISOString().slice(0, 16).replace('T', ' '),
    epoch: (PROV && PROV.tle_epoch_max ? tpl('pos_cap_epoch', {d: (PROV.tle_epoch_latest_past || PROV.tle_epoch_max).slice(0, 10), age: PROV.tle_age_days}) : ''),
  });

  if(box.dataset.globe === '1'){ initGlobe3D(pmId); return; }

  // 依序聚焦模式：按鈕 + 自動輪播
  if(box.dataset.seq === '1' && st.sats.length){
    const bar = box.parentElement.querySelector('.pm-seq');
    bar.innerHTML = st.sats.map((s, i) =>
      '<button class="nbtn" data-i="' + i + '">' +
      esc(st.names[String(s[0])] || ('NORAD ' + s[0])) + '</button>').join('');
    bar.querySelectorAll('button').forEach(b =>
      b.addEventListener('click', () => {
        clearInterval(st.seqTimer);
        focusPos(pmId, +b.dataset.i);
      }));
    focusPos(pmId, 0);
    st.seqTimer = setInterval(() => {
      focusPos(pmId, (st.focus + 1) % st.sats.length);
    }, 3500);
  }
  const bg = new Image();
  bg.onload = () => { st.bg = bg; drawPosMap(pmId); };
  bg.onerror = () => drawPosMap(pmId);
  bg.src = '/api/globe_texture';
  drawPosMap(pmId);
}

/* ── 3D 球體（單純深色底、無貼圖、自動旋轉）── */
function initGlobe3D(pmId){
  const st = PM[pmId];
  // 預計算單位向量與徑向距離（地球半徑=1）
  st.units = st.sats.map(s => {
    const la = s[1] * Math.PI / 180, lo = s[2] * Math.PI / 180;
    return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo),
            Math.sin(la), 1 + s[3] / RE_KM];
  });
  st.rMax = Math.max(1.25, ...st.units.map(u => u[3]));
  // 經緯網格點（30° 間隔，每條 90 取樣）
  st.grid = [];
  for(let lo = 0; lo < 360; lo += 30)
    for(let j = 0; j < 90; j++){
      const la = (-90 + j * 2) * Math.PI / 180, lor = lo * Math.PI / 180;
      st.grid.push([Math.cos(la) * Math.cos(lor), Math.cos(la) * Math.sin(lor), Math.sin(la)]);
    }
  for(let la = -60; la <= 60; la += 30)
    for(let j = 0; j < 120; j++){
      const lar = la * Math.PI / 180, lor = j * 3 * Math.PI / 180;
      st.grid.push([Math.cos(lar) * Math.cos(lor), Math.cos(lar) * Math.sin(lor), Math.sin(lar)]);
    }
  st.rot = 0;
  let tick = 0;
  const loop = () => {
    if(!st.cv.isConnected) return;          // 節點移除即停
    if(tick++ % 2 === 0){ st.rot += 0.005 / 3; drawGlobe3D(pmId); }  // ~30fps，旋轉速度為原本 1/3
    requestAnimationFrame(loop);
  };
  loop();
}

function drawGlobe3D(pmId){
  const st = PM[pmId];
  const cv = st.cv, box = cv.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const w = box.clientWidth || 1100;
  const h = Math.max(240, Math.round(box.clientHeight > 60 ? box.clientHeight : Math.min(w * 0.52, 600)));
  if(cv.width !== w * dpr || cv.height !== h * dpr){ cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px'; }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // 單純深色底
  ctx.fillStyle = '#05080f'; ctx.fillRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2;
  const Rpx = (h / 2 - 16) / st.rMax;       // 最遠衛星恰好入框
  const cosR = Math.cos(st.rot), sinR = Math.sin(st.rot);
  const T = 20 * Math.PI / 180, cosT = Math.cos(T), sinT = Math.sin(T);
  const proj = (u) => {                      // 繞 Z 旋轉 → 繞水平軸傾角 → 正交投影
    const x1 = u[0] * cosR - u[1] * sinR, y1 = u[0] * sinR + u[1] * cosR, z1 = u[2];
    return [y1, -(z1 * cosT - x1 * sinT), x1 * cosT + z1 * sinT];  // [sx, sy, depth]
  };
  // 地球圓盤（微弱放射漸層）＋輪廓
  const g = ctx.createRadialGradient(cx - Rpx * .3, cy - Rpx * .3, Rpx * .1, cx, cy, Rpx);
  g.addColorStop(0, '#182234'); g.addColorStop(1, '#0b111d');
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(cx, cy, Rpx, 0, 2 * Math.PI); ctx.fill();
  ctx.strokeStyle = '#2b3a52'; ctx.lineWidth = 1;
  ctx.stroke();
  // 經緯網（正面）
  ctx.fillStyle = 'rgba(80,100,135,.5)';
  st.grid.forEach(u => {
    const p = proj(u);
    if(p[2] > 0) ctx.fillRect(cx + p[0] * Rpx - .5, cy + p[1] * Rpx - .5, 1, 1);
  });
  // 參考環：MEO（GPS 高度 ≈4.16 R⊕）與 GEO（≈6.61 R⊕），赤道面投影為橢圓
  const drawRing = (rr, color, label) => {
    if(rr > st.rMax + 0.3) return;
    ctx.strokeStyle = color; ctx.setLineDash([4, 5]); ctx.lineWidth = 1; ctx.beginPath();
    for(let k = 0; k <= 120; k++){
      const a = k / 120 * 2 * Math.PI, p = proj([Math.cos(a), Math.sin(a), 0]);
      const X = cx + p[0] * rr * Rpx, Y = cy + p[1] * rr * Rpx;
      k ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
    }
    ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = color; ctx.font = '10px Segoe UI'; ctx.textAlign = 'left';
    const p0 = proj([1, 0, 0]);
    ctx.fillText(label, cx + p0[0] * rr * Rpx + 4, cy + p0[1] * rr * Rpx - 4);
  };
  drawRing(4.164, 'rgba(63,185,80,.45)', 'MEO 20,200 km');
  drawRing(6.611, 'rgba(255,215,71,.45)', 'GEO 35,786 km');
  // 衛星（依軌道域配色）
  const big = st.sats.length > 200;
  const hasNames = Object.keys(st.names).length > 0;
  const REG = [['LEO', 2000, '#58d0ff'], ['MEO', 30000, '#3fb950'], ['GEO/IGSO', 40000, '#ffd747'], [t('regime_heo_other'), 1e9, '#f778ba']];
  const regOf = alt => REG.find(r => alt < r[1]);
  const regCount = {};
  const MAX_LABELS = big ? 150 : 100000;           // 大星系：正面不重疊標籤上限
  const cellW = 74, cellH = 13, occ = new Set();   // 標籤佔位格（避免重疊）
  let nLabels = 0;
  const labels = [];
  for(let i = 0; i < st.units.length; i++){
    const u = st.units[i], p = proj(u), r = u[3];
    const X = cx + p[0] * r * Rpx, Y = cy + p[1] * r * Rpx;
    const inFront = p[2] > 0;
    const reg = regOf(st.sats[i][3]);
    regCount[reg[0]] = (regCount[reg[0]] || 0) + 1;
    const scrDist = Math.hypot(X - cx, Y - cy);
    if(!inFront && scrDist < Rpx) continue;          // 被地球遮蔽
    ctx.globalAlpha = inFront ? .92 : .35;
    ctx.fillStyle = reg[2];
    if(big) ctx.fillRect(X - 1, Y - 1, 2, 2);
    else{ ctx.beginPath(); ctx.arc(X, Y, 4, 0, 2 * Math.PI); ctx.fill(); }
    if(hasNames && inFront && nLabels < MAX_LABELS){
      const nm = st.names[String(st.sats[i][0])];
      if(!nm) continue;
      const gx = Math.floor((X + 7) / cellW), gy = Math.floor(Y / cellH);
      if(X + 7 > w - 4 || Y < 8 || Y > h - 4) continue;
      let clash = false;                              // 八方向鄰接格皆須空
      for(let dx = -1; dx <= 1 && !clash; dx++)
        for(let dy = -1; dy <= 1; dy++) if(occ.has((gx + dx) + ':' + (gy + dy))){ clash = true; break; }
      if(clash) continue;
      occ.add(gx + ':' + gy); nLabels++;
      labels.push([nm, X + 7, Y + 4]);
    }
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = big ? 'rgba(201,209,217,.85)' : '#e6edf3';
  ctx.font = (big ? '9.5px' : '11px') + ' Segoe UI'; ctx.textAlign = 'left';
  labels.forEach(([nm, x, y]) => ctx.fillText(nm, x, y));
  if(big && hasNames){
    ctx.fillStyle = '#6e7681'; ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'right';
    ctx.fillText(tpl('globe_label_cap', {n: MAX_LABELS}), w - 8, h - 8);
  }
  // 圖例：軌道域顆數
  let ly = 14;
  ctx.font = '11px Segoe UI'; ctx.textAlign = 'left';
  REG.forEach(r => {
    const c = regCount[r[0]]; if(!c) return;
    ctx.fillStyle = r[2]; ctx.beginPath(); ctx.arc(14, ly, 4, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = '#c9d1d9'; ctx.fillText(r[0] + '  ' + fmtN(c), 24, ly + 4); ly += 17;
  });
}

function focusPos(pmId, i){
  const st = PM[pmId];
  st.focus = i;
  const bar = st.cv.closest('.pm-wrap').querySelector('.pm-seq');
  if(bar) bar.querySelectorAll('button').forEach((b, bi) =>
    b.classList.toggle('on', bi === i));
  drawPosMap(pmId);
}

function drawPosMap(pmId){
  const st = PM[pmId];
  const cv = st.cv, box = cv.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const w = box.clientWidth || 1100, h = Math.round(w / 2);
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.height = h + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // 底圖（equirectangular）或深色底＋經緯網
  if(st.bg){ ctx.globalAlpha = .85; ctx.drawImage(st.bg, 0, 0, w, h); ctx.globalAlpha = 1; }
  else{
    ctx.fillStyle = '#0a0f1a'; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#1c2635'; ctx.lineWidth = 1;
    for(let lo = -150; lo <= 150; lo += 30){
      const x = (lo + 180) / 360 * w;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for(let la = -60; la <= 60; la += 30){
      const y = (90 - la) / 180 * h;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
  }
  ctx.fillStyle = 'rgba(0,0,0,.25)'; ctx.fillRect(0, 0, w, h);
  const big = st.sats.length > 200;
  const seq = st.focus >= 0;
  st.sats.forEach((s, i) => {
    const x = (s[2] + 180) / 360 * w, y = (90 - s[1]) / 180 * h;
    if(seq && i !== st.focus){ ctx.fillStyle = 'rgba(139,148,158,.55)'; }
    else ctx.fillStyle = big ? 'rgba(88,208,255,.75)' : '#ffd747';
    ctx.beginPath(); ctx.arc(x, y, big ? 1.1 : 4, 0, 2 * Math.PI); ctx.fill();
    if(!big && !seq && st.names[String(s[0])]){
      ctx.fillStyle = '#e6edf3'; ctx.font = '11px Segoe UI'; ctx.textAlign = 'left';
      ctx.fillText(st.names[String(s[0])], x + 7, y + 4);
    }
  });
  if(seq){
    const s = st.sats[st.focus];
    const x = (s[2] + 180) / 360 * w, y = (90 - s[1]) / 180 * h;
    ctx.strokeStyle = '#ffd747'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, 2 * Math.PI); ctx.stroke();
    ctx.fillStyle = '#ffd747';
    ctx.beginPath(); ctx.arc(x, y, 4.5, 0, 2 * Math.PI); ctx.fill();
    const nm = st.names[String(s[0])] || ('NORAD ' + s[0]);
    ctx.font = 'bold 13px Segoe UI'; ctx.textAlign = 'left'; ctx.fillStyle = '#fff';
    const lx = Math.min(x + 12, w - 220);
    ctx.fillText(nm, lx, Math.max(16, y - 12));
    ctx.font = '11.5px Segoe UI'; ctx.fillStyle = '#ffd747';
    ctx.fillText(s[1].toFixed(1) + '°, ' + s[2].toFixed(1) + '° · ' +
                 Math.round(s[3]).toLocaleString() + ' km', lx, Math.max(30, y + 4));
  }
}

/* ═══════════ 整合展示節型（懶載入：.lazy[data-kind]） ═══════════ */
function kpi(v, l, cls){
  return '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="v">' + v + '</div><div class="l">' + esc(l) + '</div></div>';
}
function fmtN(n){ return Number(n).toLocaleString(LOCALE_MAP[LANG] || 'zh-Hant'); }

/* 細長條圖（color 可為單色或逐根顏色陣列；值標籤：≤14 根全標，否則只標最大） */
function drawBars(cv, labels, values, color, unit){
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 500, h = 170;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const n = values.length; if(!n) return;
  const mx = Math.max(...values, 1);
  const padL = 8, padR = 8, padT = 18, padB = 26;
  const bw = (w - padL - padR) / n;
  ctx.strokeStyle = '#21262d'; ctx.beginPath(); ctx.moveTo(padL, h - padB); ctx.lineTo(w - padR, h - padB); ctx.stroke();
  ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'center';
  const imax = values.indexOf(mx);
  values.forEach((v, i) => {
    const bh = (h - padT - padB) * v / mx;
    const x = padL + i * bw + bw * 0.15, y = h - padB - bh;
    ctx.fillStyle = Array.isArray(color) ? color[i] : color;
    ctx.beginPath(); ctx.roundRect(x, y, bw * 0.7, bh, [3, 3, 0, 0]); ctx.fill();
    if(n <= 14 || i === imax){
      ctx.fillStyle = '#c9d1d9';
      ctx.fillText(fmtN(v) + (unit || ''), x + bw * 0.35, Math.max(10, y - 4));
    }
    if(n <= 14 || i % Math.ceil(n / 12) === 0){
      ctx.fillStyle = '#8b949e';
      ctx.fillText(String(labels[i]), x + bw * 0.35, h - padB + 14);
    }
  });
}

async function initGroupStats(el){
  const r = await fetch('/api/story/group_stats?group=' + el.dataset.group);
  const d = await r.json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  const reg = Object.entries(d.regimes).map(([k, v]) => k + ' ' + v).join(' · ');
  const years = Object.keys(d.launch_years), yv = Object.values(d.launch_years);
  const altK = Object.keys(d.alt_hist), altV = Object.values(d.alt_hist);
  el.innerHTML =
    '<div class="kpis">' + kpi(fmtN(d.n), t('gs_kpi_objects')) +
    kpi(esc(reg), t('gs_kpi_regime')) + kpi(d.alt_median != null ? fmtN(Math.round(d.alt_median)) + ' km' : '—', t('gs_kpi_alt_median')) +
    kpi(years.length ? years[0] + '–' + years[years.length - 1] : '—', t('gs_kpi_launch_range')) + '</div>' +
    '<div class="two"><div class="bars"><h5>' + esc(t('gs_bars_launch')) + '</h5><canvas id="' + el.id + '-y"></canvas></div>' +
    '<div class="bars"><h5>' + esc(t('gs_bars_alt')) + '</h5><canvas id="' + el.id + '-a"></canvas></div></div>' +
    '<div class="chips">' + d.sample.map(s => '<a class="chip" href="/orbit?norad=' + s.norad + '" target="_blank">' +
      esc(s.name) + ' ↗</a>').join('') + '</div>' +
    '<div class="note">' + esc(t('gs_note')) + '</div>';
  drawBars($id(el.id + '-y'), years, yv, '#58a6ff');
  drawBars($id(el.id + '-a'), altK.map(k => k >= 20000 ? (k == 20000 ? 'MEO' : 'GEO') : k), altV,
           altK.map(k => k >= 30000 ? '#ffd747' : (k >= 20000 ? '#3fb950' : '#58d0ff')));
}

/* 章節總覽磚 */
function tocHtml(sec){
  return '<div class="toc">' + (sec.items || []).map(it =>
    '<a class="tile" href="#' + esc(it.anchor) + '"><div class="ic">' + (it.icon || '') + '</div>' +
    '<div class="t">' + esc(it.label) + '</div><div class="s">' + esc(it.sub || '') + '</div></a>').join('') + '</div>';
}

/* 偵照衛星感測器／光學解析度分類 */
const SENSOR_COLOR = {'光學': '#58a6ff', 'SAR': '#bc8cff', '射頻訊號': '#f0883e', '氣象掩星': '#39c5cf',
                      '技術試驗': '#8b949e', '導航': '#3fb950'};
async function initIsrRes(el){
  const d = await (await fetch('/api/story/isr_resolution?group=' + (el.dataset.group || 'prc_isr'))).json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  const sk = Object.keys(d.sensor), sv = Object.values(d.sensor);
  const rk = Object.keys(d.resolution), rv = Object.values(d.resolution);
  el.innerHTML =
    '<div class="kpis">' + sk.map(k => '<div class="kpi"><div class="v" style="color:' + (SENSOR_COLOR[k] || '#e6edf3') + '">' +
      fmtN(d.sensor[k]) + '</div><div class="l">' + esc(sensorLabel(k)) + '</div></div>').join('') +
    (d.unknown ? kpi(fmtN(d.unknown), t('isr_unclassified')) : '') + '</div>' +
    '<div class="two"><div class="bars"><h5>' + esc(t('isr_bars_sensor')) + '</h5><canvas id="' + el.id + '-s"></canvas></div>' +
    '<div class="bars"><h5>' + esc(t('isr_bars_res')) + '</h5><canvas id="' + el.id + '-r"></canvas></div></div>' +
    '<table class="data"><tr><th>' + esc(t('th_isr_series')) + '</th><th>' + esc(t('th_isr_count')) + '</th><th>' + esc(t('th_isr_sensor')) + '</th><th>' + esc(t('th_isr_res')) + '</th><th>' + esc(t('th_isr_note')) + '</th></tr>' +
    d.series.map(s => '<tr><td>' + esc(s.series) + '</td><td>' + s.n + '</td><td style="color:' + (SENSOR_COLOR[s.sensor] || '#c9d1d9') + '">' +
      esc(sensorLabel(s.sensor)) + '</td><td>' + esc(s.res) + '</td><td style="text-align:left;color:#8b949e">' + esc(s.note) + '</td></tr>').join('') +
    '</table><div class="note">' + esc(d.note) + '</div>';
  drawBars($id(el.id + '-s'), sk.map(sensorLabel), sv, sk.map(k => SENSOR_COLOR[k] || '#8b949e'));
  const seq = ['#1f6feb', '#388bfd', '#58a6ff', '#79c0ff', '#a5d6ff', '#cae8ff'];
  const shortLbl = k => k.replace('（推估）', '*').replace('SAR ≈', 'SAR ').replace(/ m$/, '').replace(' m*', '*');
  drawBars($id(el.id + '-r'), rk.map(shortLbl), rv,
           rk.map((k, i) => k.startsWith('SAR') ? '#bc8cff' : seq[Math.min(i, seq.length - 1)]));
  el.querySelector('.note').textContent += t('isr_note_suffix');
}

/* 前／後配對長條（雷達效益） */
function drawPaired(cv, labels, before, after, units){
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 500, h = 180;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const n = labels.length, padL = 8, padT = 20, padB = 30, gw = (w - padL - 8) / n;
  ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'center';
  labels.forEach((lb, i) => {
    const mx = Math.max(before[i], after[i], 1e-9);
    [[before[i], '#6e7681', -1], [after[i], '#3fb950', 1]].forEach(([v, col, side]) => {
      const bh = (h - padT - padB) * v / mx, bw = gw * 0.28;
      const x = padL + i * gw + gw / 2 + (side < 0 ? -bw - 3 : 3), y = h - padB - bh;
      ctx.fillStyle = col; ctx.beginPath(); ctx.roundRect(x, y, bw, bh, [3, 3, 0, 0]); ctx.fill();
      ctx.fillStyle = '#c9d1d9'; ctx.fillText(v + (units[i] || ''), x + bw / 2, Math.max(10, y - 4));
    });
    ctx.fillStyle = '#8b949e'; ctx.fillText(lb, padL + i * gw + gw / 2, h - padB + 14);
  });
  ctx.textAlign = 'left'; ctx.fillStyle = '#6e7681'; ctx.fillRect(padL, h - 10, 10, 8); ctx.fillStyle = '#8b949e'; ctx.fillText(t('legend_before'), padL + 14, h - 2);
  ctx.fillStyle = '#3fb950'; ctx.fillRect(padL + 60, h - 10, 10, 8); ctx.fillStyle = '#8b949e'; ctx.fillText(t('legend_after'), padL + 74, h - 2);
}

async function initManeuvers(el){
  const r = await fetch('/api/story/maneuvers');
  const d = await r.json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  const keys = (el.dataset.groups || '').split(',').filter(k => d.groups[k]);
  let h = '<div class="note">' + esc(d.method.stat) + t('man_connector') + esc(d.method.prc) + '</div>';
  keys.forEach((k, i) => {
    const g = d.groups[k];
    const months = Object.keys(g.monthly), mv = Object.values(g.monthly);
    const pct = g.n_sats ? Math.round(100 * g.n_sats_with_event / g.n_sats) : 0;
    h += '<h4 style="margin:16px 0 4px;font-size:14px;color:#e6edf3">' + esc(g.label) + '</h4>' +
      '<div class="kpis">' + kpi(fmtN(g.n_sats), t('man_kpi_sats')) + kpi(fmtN(g.n_events), t('man_kpi_events')) +
      kpi(tpl('man_kpi_sats_with_event_val', {n: fmtN(g.n_sats_with_event), pct}), t('man_kpi_sats_with_event')) +
      (g.rate_per_100_sats != null ? kpi(g.rate_per_100_sats, t('man_kpi_rate100')) : '') +
      (g.rate_per_1000_transitions != null ? kpi(g.rate_per_1000_transitions, t('man_kpi_rate1000')) : '') +
      (g.median_abs_da_km != null ? kpi(g.median_abs_da_km + ' km', t('man_kpi_median_da')) : '') +
      (g.prc_pipeline ? kpi(fmtN(g.prc_pipeline.n_events), t('man_kpi_prc_flag')) : '') + '</div>' +
      '<div class="two"><div class="bars"><h5>' + esc(t('man_bars_month')) + '</h5><canvas id="' + el.id + '-m' + i + '"></canvas></div>' +
      '<div><div class="note" style="margin:0 0 4px">' + esc(t('man_note_top')) + '</div><div class="chips">' +
      g.top.slice(0, 8).map(tp => '<a class="chip" href="/orbit?norad=' + tp.norad + '" target="_blank">' +
        esc(tp.name) + ' · ' + tp.events + '</a>').join('') + '</div></div></div>';
    if(g.events && g.events.length){
      h += '<details class="evd"><summary>' + esc(tpl('man_details_summary', {n: g.events.length})) + '</summary>' +
        '<table class="data"><tr><th>' + esc(t('th_man_sat')) + '</th><th>' + esc(t('th_man_tle_before')) + '</th><th>' + esc(t('th_man_tle_after')) + '</th><th>' + esc(t('th_man_gap_h')) + '</th><th>' + esc(t('th_man_da')) + '</th><th>' + esc(t('th_man_dv')) + '</th><th>' + esc(t('th_man_regime')) + '</th></tr>' +
        g.events.map(e => '<tr><td><a href="/orbit?norad=' + e.norad + '&start=' + e.epoch_before.slice(0, 10) + '" target="_blank">' + esc(e.name) + '</a><br><span style="color:#6e7681">' + e.norad + '</span></td>' +
          '<td>' + e.epoch_before.slice(0, 16).replace('T', ' ') + '</td><td>' + e.epoch_after.slice(0, 16).replace('T', ' ') + '</td>' +
          '<td>' + e.gap_h + '</td><td>' + (e.da_km > 0 ? '+' : '') + e.da_km + '</td><td>' + e.dv_ms + '</td><td>' + e.regime + '</td></tr>').join('') +
        '</table></details>';
    }
  });
  h += '<div class="note">' + esc(t('man_final_note')) + '</div>';
  el.innerHTML = h;
  keys.forEach((k, i) => {
    const g = d.groups[k];
    drawBars($id(el.id + '-m' + i), Object.keys(g.monthly).map(m => m.slice(5)), Object.values(g.monthly), '#d29922');
  });
}

let RADAR = null;   // 快取 radar_eval 結果供 skyplot 選星
async function initRadar(el){
  const r = await fetch('/api/story/radar_eval?group=' + el.dataset.group + '&n=' + (el.dataset.n || 30));
  const d = await r.json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  RADAR = d;
  const s = d.summary;
  const arrow = (a, b, unit, better) => a + unit + ' → <b style="color:' + (better ? '#3fb950' : '#e6edf3') + '">' + b + unit + '</b>';
  el.innerHTML =
    '<div class="kpis">' +
    kpi(arrow(s.arcs_before, s.arcs_after, '', s.arcs_after > s.arcs_before), t('radar_kpi_arcs')) +
    kpi(arrow(s.gap_max_before_min, s.gap_max_after_min, ' 分', s.gap_max_after_min < s.gap_max_before_min), t('radar_kpi_gap')) +
    kpi(arrow(s.track_min_before, s.track_min_after, ' 分', s.track_min_after > s.track_min_before), t('radar_kpi_track_min')) +
    kpi(s.taiwan_only_min + ' 分', t('radar_kpi_taiwan_only')) +
    kpi('+' + (s.info_gain_pct != null ? s.info_gain_pct : s.precision_gain_pct) + '%', t('radar_kpi_gain'), 'gain') +
    kpi(s.sats_with_taiwan_arc + '/' + s.n_sats, t('radar_kpi_taiwan_arc_sats')) + '</div>' +
    '<div class="bars"><h5>' + esc(t('radar_bars_pb')) + '</h5><canvas id="' + el.id + '-pb"></canvas></div>' +
    '<div class="two"><div><div class="bars"><h5>' + esc(tpl('radar_bars_map', {n: d.n_stations_before})) + '</h5>' +
    '<canvas id="' + el.id + '-map"></canvas></div></div>' +
    '<div><table class="data"><tr><th>' + esc(t('th_radar_sat')) + '</th><th>' + esc(t('th_radar_arcs')) + '</th><th>' + esc(t('th_radar_taiwan_arc')) + '</th><th>' + esc(t('th_radar_gap')) + '</th><th>' + esc(t('th_radar_precision')) + '</th></tr>' +
    d.sats.slice(0, 8).map(x => '<tr><td><a href="/orbit?norad=' + x.norad + '" target="_blank">' + esc(x.name) + '</a></td>' +
      '<td>' + x.arcs_before + ' → ' + x.arcs_after + '</td><td>' + x.arcs_taiwan + '</td>' +
      '<td>' + x.gap_max_before_min + ' → ' + x.gap_max_after_min + '</td><td>+' + (x.info_gain_pct != null ? x.info_gain_pct : x.precision_gain_pct) + '%</td></tr>').join('') +
    '</table></div></div>' +
    '<div class="note">' + tpl('radar_note', {model: esc(d.model_note), label: esc(d.label), n: s.n_sats, t0: d.t0, mask: d.mask_deg}) + '</div>' +
    (d.assumptions ? '<details class="evd"><summary>' + esc(t('radar_details_summary')) + '</summary><table class="data">' +
      Object.entries(d.assumptions).map(([k, v]) => '<tr><td style="text-align:left">' + esc(k) + '</td><td style="text-align:left">' + esc(String(v)) + '</td></tr>').join('') +
      '</table></details>' : '');
  drawPaired($id(el.id + '-pb'), [t('radar_legend_1'), t('radar_legend_2'), t('radar_legend_3')],
             [s.arcs_before, s.gap_max_before_min, s.track_min_before],
             [s.arcs_after, s.gap_max_after_min, s.track_min_after], ['', '', '']);
  // 站點地圖
  const st = await (await fetch('/api/layers/ssn_stations')).json();
  const cv = $id(el.id + '-map'), dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 500, h = Math.round(w / 2);
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#0a0f1a'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#1c2635';
  for(let lo = -150; lo <= 150; lo += 30){ const x = (lo + 180) / 360 * w; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for(let la = -60; la <= 60; la += 30){ const y = (90 - la) / 180 * h; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  (st.features || []).forEach(f => {
    const [lon, lat] = f.geometry.coordinates;
    const x = (lon + 180) / 360 * w, y = (90 - lat) / 180 * h;
    ctx.fillStyle = '#58a6ff'; ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill();
  });
  const tw = d.taiwan_station, tx = (tw.lon + 180) / 360 * w, ty = (90 - tw.lat) / 180 * h;
  ctx.fillStyle = '#ffd747'; ctx.beginPath(); ctx.arc(tx, ty, 6, 0, 2 * Math.PI); ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(tx, ty, 9, 0, 2 * Math.PI); ctx.stroke();
  ctx.fillStyle = '#ffd747'; ctx.font = 'bold 11px Segoe UI';
  const right = tx > w - 170;                     // 近右緣時標籤置左，避免裁切
  ctx.textAlign = right ? 'right' : 'left';
  ctx.fillText(tw.name, tx + (right ? -12 : 12), ty + 4);
}

/* -- 重訪 / 覆蓋分析（可調地面觀測仰角門檻）--------------------------------
   後端一次傳播、回傳多個仰角門檻的結果，故滑桿切換門檻不需重新請求。 */
const RV = {};   // el.id -> {data, mi}

async function initRevisit(el){
  const group = el.dataset.group || 'oneweb';
  const site  = el.dataset.site  || 'taipei';
  el.innerHTML = '<div class="ph">' + esc(t('rv_loading')) + '</div>';
  const d = await (await fetch('/api/story/revisit?group=' + encodeURIComponent(group) +
                               '&site=' + encodeURIComponent(site))).json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }

  // 預設門檻：取最接近 25 度（一般使用者終端常見遮蔽角）者
  let mi = 0, best = 1e9;
  d.masks.forEach((m, i) => { const dd = Math.abs(m - 25); if(dd < best){ best = dd; mi = i; } });
  RV[el.id] = {data: d, mi: mi};

  const sites = d.sites || [];
  el.innerHTML =
    '<div class="rvctl">' +
      '<label>' + esc(t('rv_label_site')) + ' <select id="' + el.id + '-site">' +
        sites.map(s => '<option value="' + esc(s.key) + '"' + (s.key === site ? ' selected' : '') + '>' +
          esc(siteLabel(s)) + '（' + s.lat.toFixed(2) + '°N）</option>').join('') +
      '</select></label>' +
      '<label class="rng">' + esc(t('rv_label_mask')) + ' ' +
        '<input type="range" id="' + el.id + '-mask" min="0" max="' + (d.masks.length - 1) + '" step="1" value="' + mi + '">' +
        '<b id="' + el.id + '-maskv"></b></label>' +
    '</div>' +
    '<div id="' + el.id + '-out"></div>';

  $id(el.id + '-mask').oninput = e => { RV[el.id].mi = +e.target.value; drawRevisit(el.id); };
  $id(el.id + '-site').onchange = async e => {
    const out = $id(el.id + '-out'); out.innerHTML = '<div class="ph">' + esc(t('rv_recalc')) + '</div>';
    const nd = await (await fetch('/api/story/revisit?group=' + encodeURIComponent(group) +
                                  '&site=' + encodeURIComponent(e.target.value))).json();
    if(nd.error){ out.innerHTML = '<div class="ph">' + esc(nd.error) + '</div>'; return; }
    RV[el.id].data = nd; drawRevisit(el.id);
  };
  drawRevisit(el.id);
}

function drawRevisit(id){
  const st = RV[id]; if(!st) return;
  const d = st.data, masks = d.masks, m = masks[st.mi], k = String(Math.round(m)), b = d.by_mask[k];
  $id(id + '-maskv').textContent = m.toFixed(0) + '°';

  const hrs = d.window.hours;
  const noOutage = b.coverage_pct >= 99.999;
  const satRv = b.sat_revisit_median_min;
  const covCls = b.coverage_pct >= 99.9 ? ' gain' : '';
  const selSite = (d.sites || []).find(s => s.name === d.site_name);
  const siteName = selSite ? siteLabel(selSite) : d.site_name;

  $id(id + '-out').innerHTML =
    '<div class="kpis">' +
      kpi(b.coverage_pct.toFixed(2) + '%', tpl('rv_kpi_coverage', {h: hrs}), covCls) +
      kpi(noOutage ? t('rv_no_outage') : b.max_gap_min.toFixed(1) + ' 分', t('rv_kpi_max_gap')) +
      kpi(satRv == null ? '—' : (satRv / 60).toFixed(1) + ' h', t('rv_kpi_sat_revisit')) +
      kpi(b.mean_revisit_min == null ? '—' : b.mean_revisit_min.toFixed(2) + ' 分', t('rv_kpi_mean_revisit')) +
      kpi(b.max_simultaneous, t('rv_kpi_max_simul')) +
    '</div>' +
    '<div class="rvgrid">' +
      '<div><div class="cap">' + esc(t('rv_cap_cov')) + '</div><canvas id="' + id + '-cov"></canvas></div>' +
      '<div><div class="cap">' + esc(t('rv_cap_gap')) + '</div><canvas id="' + id + '-gap"></canvas></div>' +
    '</div>' +
    '<div class="cap">' + esc(tpl('rv_cap_timeline', {h: hrs, m: m.toFixed(0)})) + '</div>' +
    '<canvas id="' + id + '-tl"></canvas>' +
    (b.top_gaps.length
      ? '<div class="cap">' + esc(tpl('rv_cap_top_gaps', {m: m.toFixed(0)})) + '</div><table class="data"><tr><th>' + esc(t('th_rv_idx')) + '</th><th>' + esc(t('th_rv_start')) + '</th><th>' + esc(t('th_rv_len')) + '</th></tr>' +
        b.top_gaps.map((g, i) => '<tr><td>' + (i + 1) + '</td><td>' +
          g.start_utc.slice(5, 16).replace('T', ' ') + '</td><td>' + g.minutes.toFixed(1) + ' 分</td></tr>').join('') +
        '</table>'
      : '') +
    '<div class="note">' + tpl('rv_note', {
      site: esc(siteName), label: esc(d.label), n: fmtN(d.n_sats_propagated), h: hrs, step: d.window.step_sec,
      censored: (b.gap_edge_censored_min > 0 ? tpl('rv_censored', {n: b.gap_edge_censored_min.toFixed(1)}) : ''),
      pmed: (b.median_pass_min == null ? '—' : b.median_pass_min.toFixed(1) + ' 分'),
      emed: (b.median_max_el_deg == null ? '—' : b.median_max_el_deg.toFixed(1) + '°'),
    }) + '</div>';

  drawBars($id(id + '-cov'), masks.map(x => x.toFixed(0) + '°'),
           masks.map(x => d.by_mask[String(Math.round(x))].coverage_pct),
           masks.map((x, i) => i === st.mi ? '#ffd747' : '#1f6feb'), '');
  drawBars($id(id + '-gap'), masks.map(x => x.toFixed(0) + '°'),
           masks.map(x => d.by_mask[String(Math.round(x))].max_gap_min),
           masks.map((x, i) => i === st.mi ? '#ffd747' : '#f85149'), '');
  drawTimeline($id(id + '-tl'), b.timeline, hrs);
}

/* 可見顆數時間帶：0 顆的時段以紅色標出（服務中斷） */
function drawTimeline(cv, arr, hours){
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 600, h = 96;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#0d1117'; ctx.fillRect(0, 0, w, h);
  const padB = 20, padT = 8, n = arr.length, mx = Math.max(...arr, 1);
  const bw = w / n;
  arr.forEach((v, i) => {
    const bh = (h - padT - padB) * v / mx;
    ctx.fillStyle = v === 0 ? '#f85149' : '#238636';
    ctx.fillRect(i * bw, v === 0 ? h - padB - 6 : h - padB - bh, Math.max(bw, 1), v === 0 ? 6 : bh);
  });
  ctx.strokeStyle = '#21262d'; ctx.beginPath(); ctx.moveTo(0, h - padB); ctx.lineTo(w, h - padB); ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'center';
  const stepH = Math.max(1, Math.round(hours / 8));
  for(let t = 0; t <= hours; t += stepH){
    const x = w * t / hours;
    ctx.fillText('+' + t + ' h', Math.min(w - 14, Math.max(14, x)), h - 6);
  }
  ctx.textAlign = 'left'; ctx.fillStyle = '#6e7681';
  ctx.fillText(tpl('tl_peak', {n: mx}), 4, 12);
}

async function initSkyplot(el){
  let sats = [];
  if(el.dataset.norads) sats = el.dataset.norads.split(',').map(x => ({norad: +x, name: 'NORAD ' + x}));
  else{
    if(!RADAR){ const r = await fetch('/api/story/radar_eval?group=' + el.dataset.group + '&n=30'); RADAR = await r.json(); }
    sats = (RADAR.sats || []).filter(x => x.arcs_taiwan > 0).slice(0, 4);
  }
  if(!sats.length){ el.innerHTML = '<div class="ph">' + esc(t('sky_no_sat')) + '</div>'; return; }
  el.innerHTML = '<div class="pm-seq" id="' + el.id + '-btn"></div>' +
    '<div class="skywrap"><canvas id="' + el.id + '-sky"></canvas><div id="' + el.id + '-info"></div></div>';
  const bar = $id(el.id + '-btn');
  sats.forEach((s, i) => {
    const b = document.createElement('button'); b.className = 'nbtn' + (i === 0 ? ' on' : '');
    b.textContent = s.name; b.onclick = () => { bar.querySelectorAll('.nbtn').forEach(x => x.classList.toggle('on', x === b)); loadTrack(el, s.norad); };
    bar.appendChild(b);
  });
  loadTrack(el, sats[0].norad);
}

let SKY_TIMER = null;
async function loadTrack(el, norad){
  clearInterval(SKY_TIMER);
  const d = await (await fetch('/api/story/track?norad=' + norad)).json();
  const info = $id(el.id + '-info');
  if(d.error || !d.passes.length){ info.innerHTML = '<div class="ph">' + esc(d.error || t('sky_no_pass_24h')) + '</div>'; return; }
  info.innerHTML = '<div class="kpis">' + kpi(esc(d.name), t('sky_kpi_sat')) + kpi(d.passes.length, t('sky_kpi_passes')) +
    kpi(Math.max(...d.passes.map(p => p.max_el)).toFixed(1) + '°', t('sky_kpi_max_el')) + '</div>' +
    '<table class="data"><tr><th>' + esc(t('th_sky_idx')) + '</th><th>' + esc(t('th_sky_aos')) + '</th><th>' + esc(t('th_sky_los')) + '</th><th>' + esc(t('th_sky_maxel')) + '</th><th>' + esc(t('th_sky_dur')) + '</th></tr>' +
    d.passes.map((p, i) => '<tr><td>' + (i + 1) + '</td><td>' + p.aos.slice(5, 16).replace('T', ' ') + '</td><td>' +
      p.los.slice(11, 16) + '</td><td>' + p.max_el.toFixed(1) + '°</td><td>' + p.duration_min + ' 分</td></tr>').join('') + '</table>' +
    '<div class="note" id="' + el.id + '-cur">' + esc(tpl('sky_note', {name: d.station.name, lat: d.station.lat, lon: d.station.lon, mask: d.mask_deg})) + '</div>';
  const cv = $id(el.id + '-sky'), dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 380;
  cv.width = w * dpr; cv.height = w * dpr; cv.style.height = w + 'px';
  const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const cx = w / 2, cy = w / 2, R = w / 2 - 26;
  const xy = (az, elv) => { const rr = R * (90 - elv) / 90, a = az * Math.PI / 180; return [cx + rr * Math.sin(a), cy - rr * Math.cos(a)]; };
  const allPts = d.passes.flatMap((p, pi) => p.points.map(q => ({...q, pi})));
  let k = 0;
  const draw = () => {
    ctx.fillStyle = '#0a0f1a'; ctx.fillRect(0, 0, w, w);
    ctx.strokeStyle = '#21262d'; ctx.fillStyle = '#8b949e'; ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'center';
    [0, 30, 60].forEach(e => { ctx.beginPath(); ctx.arc(cx, cy, R * (90 - e) / 90, 0, 2 * Math.PI); ctx.stroke(); ctx.fillText(e + '°', cx + 3, cy - R * (90 - e) / 90 + 11); });
    ['N', 'E', 'S', 'W'].forEach((t, i) => { const [x, y] = xy(i * 90, -8); ctx.fillText(t, x, y + 4); });
    ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
    d.passes.forEach((p, pi) => {
      ctx.strokeStyle = pi === 0 ? '#58a6ff' : '#3b4a5e'; ctx.lineWidth = pi === 0 ? 2 : 1.2; ctx.beginPath();
      p.points.forEach((q, i) => { const [x, y] = xy(q.az, q.el); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
    });
    const q = allPts[k % allPts.length];
    const [x, y] = xy(q.az, q.el);
    ctx.fillStyle = '#ffd747'; ctx.beginPath(); ctx.arc(x, y, 5.5, 0, 2 * Math.PI); ctx.fill();
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 8, 0, 2 * Math.PI); ctx.stroke();
    ctx.strokeStyle = 'rgba(255,215,71,.5)'; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke(); ctx.setLineDash([]);
    const cur = $id(el.id + '-cur');
    if(cur) cur.textContent = tpl('sky_tracking', {n: q.pi + 1, t: q.t.slice(11, 19), az: q.az.toFixed(1), el: q.el.toFixed(1), rng: fmtN(Math.round(q.rng))});
  };
  draw();
  SKY_TIMER = setInterval(() => { k++; draw(); }, 120);
}

/* ── 首屏狀態卡：離島備援窗口／覆蓋空窗／接近關注事件（幾何層、候選需人工複核） ── */
async function initHeroCards(cfg){
  const box = $id('hcards'); if(!box) return;
  if(cfg.kind === 'starlink') return initStarlinkHero(box);
  const group = cfg.group || 'oneweb', site = cfg.site || 'nangan', thr = cfg.threshold_km || 10;
  const card = (v, l, s) => '<div class="hcard"><b>' + v + '</b><span>' + l + '</span>' +
                            (s ? '<i>' + s + '</i>' : '') + '</div>';
  try{
    const [rv, cj] = await Promise.all([
      fetch('/api/story/revisit?group=' + group + '&site=' + site).then(r => r.json()),
      fetch('/api/conjunctions?threshold_km=' + thr + '&max_pairs=400').then(r => r.json()).catch(() => null),
    ]);
    if(rv.error){ box.innerHTML = '<div class="ph">' + esc(rv.error) + '</div>'; return; }
    // 取最接近 25° 的仰角門檻（一般使用者終端常見遮蔽角）
    let mi = 0, best = 1e9;
    rv.masks.forEach((m, i) => { const d = Math.abs(m - 25); if(d < best){ best = d; mi = i; } });
    const b = rv.by_mask[String(Math.round(rv.masks[mi]))];
    // 下一個候選窗口：由可見顆數時間帶找目前／下一個 >0 的時槽
    const tl = b.timeline || [], binMin = rv.window.hours * 60 / tl.length;
    let nextTxt = '—';
    if(tl.length){
      if(tl[0] > 0){ nextTxt = t('hero_now_covered'); }
      else{
        const k = tl.findIndex(x => x > 0);
        nextTxt = k < 0 ? tpl('hero_no_window', {h: rv.window.hours}) : tpl('hero_window_in', {m: Math.round(k * binMin)});
      }
    }
    const age = (PROV && PROV.tle_age_days != null) ? tpl('hero_tle_age', {n: PROV.tle_age_days}) : '';
    const selSite = (rv.sites || []).find(s => s.name === rv.site_name);
    box.innerHTML =
      card(esc(selSite ? siteLabel(selSite) : rv.site_name), esc(tpl('hero_site_role', {label: rv.label})), t('hero_site_hint')) +
      card(nextTxt, tpl('hero_next_window', {m: rv.masks[mi].toFixed(0)}), t('hero_geo_only')) +
      card(b.coverage_pct >= 99.999 ? t('rv_no_outage') : b.max_gap_min.toFixed(0) + ' 分', tpl('hero_max_gap', {h: rv.window.hours}), age) +
      card(cj && cj.count != null ? tpl('hero_pairs', {n: fmtN(cj.count)}) : '—', tpl('hero_conjunction', {thr}), t('hero_candidate_note'));
  }catch(e){ box.innerHTML = ''; }
}

/* Starlink 頁首即時計數（hero_cards.kind = "starlink"） */
async function initStarlinkHero(box){
  // 五張卡先畫外框，各 API 回來就各自填入（census 需即時抓外部網站，冷啟動可能數秒，不拖累其他卡）
  const num = v => (v === null || v === undefined || isNaN(v)) ? '—' : fmtN(v);
  const ids = ['inorbit', 'kt', 'deorbit', 'v3', 'shells'];
  box.innerHTML = ids.map(k => '<div class="hcard" id="slh-' + k + '"><b>…</b><span>' + esc(t('slh_' + k)) +
                                '</span><i>' + esc(t('slh_' + k + '_sub').replace(/ · .*\{n\}.*$/, '')) + '</i></div>').join('');
  const fill = (k, v, sub) => {
    const c = $id('slh-' + k); if(!c) return;
    c.querySelector('b').textContent = v;
    if(sub !== undefined) c.querySelector('i').textContent = sub;
  };
  const get = u => fetch(u).then(r => r.json()).catch(() => ({error: 'fetch'}));
  get('/api/starlink/census').then(cs => {
    const ours = (cs && cs.ours) || {}, kt = (cs && cs.keeptrack) || {};
    fill('inorbit', num(ours.fresh_30d));
    fill('kt', num(kt.in_orbit), kt.launched_total ? tpl('slh_kt_sub', {n: fmtN(kt.launched_total)}) : t('slh_kt_sub').replace(/ · .*$/, ''));
  });
  get('/api/starlink/deorbiting?limit=100').then(d => fill('deorbit', num(d.total_matching)));
  get('/api/starlink/v3_census').then(d => fill('v3', num(d.candidate_count)));
  get('/api/starlink/shells').then(d => fill('shells', d.shells ? d.shells.filter(x => x.count > 0).length : '—',
                                            d.shells ? d.shells.map(x => x.shell).join(' · ') : undefined));
}

/* 軌道殼層分類（/api/starlink/shells） */
async function initShells(el){
  const d = await (await fetch('/api/starlink/shells')).json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  const sum = k => d.shells.reduce((a, x) => a + (x[k] || 0), 0);
  const cols = ['sh_th_shell', 'sh_th_count', 'sh_th_work', 'sh_th_range', 'sh_th_at', 'sh_th_below', 'sh_th_above', 'sh_th_low'];
  el.innerHTML = '<div class="kpis">' + kpi(fmtN(d.total), tpl('sh_kpi_total', {d: d.fresh_days})) +
    kpi(fmtN(sum('at_shell')), t('sh_kpi_at')) + kpi(fmtN(sum('reentry_imminent')), t('sh_kpi_low')) + '</div>' +
    '<table class="data"><tr>' + cols.map(k => '<th>' + esc(t(k)) + '</th>').join('') + '</tr>' +
    d.shells.map(x => '<tr><td><b>' + esc(x.shell) + '</b>' +
      (x.retiring ? ' <span style="color:#d29922">' + esc(t('sh_retiring')) + '</span>' : '') + '</td>' +
      '<td>' + fmtN(x.count) + '</td><td>' + (x.work_alt_km != null ? fmtN(Math.round(x.work_alt_km)) + ' km' : '—') + '</td>' +
      '<td>' + (x.alt_p10_km != null ? Math.round(x.alt_p10_km) + '–' + Math.round(x.alt_p90_km) + ' km' : '—') + '</td>' +
      '<td>' + fmtN(x.at_shell || 0) + '</td><td>' + fmtN(x.below || 0) + '</td><td>' + fmtN(x.above || 0) + '</td>' +
      '<td>' + fmtN(x.reentry_imminent || 0) + '</td></tr>').join('') + '</table>' +
    '<div class="tbl-note">' + esc(tpl('sh_note', {tol: d.tol_km})) + '</div>';
}

/* FAQ 摺疊問答（sec.qa = [{q, a}]） */
function faqHtml(sec){
  return '<div class="faq">' + (sec.qa || []).map(x =>
    '<details><summary>' + esc(x.q) + '</summary><div class="faq-a">' + esc(x.a) + '</div></details>').join('') + '</div>';
}

async function initCdm(el){
  const thr = el.dataset.thr || 10;
  const d = await (await fetch('/api/conjunctions?threshold_km=' + thr + '&max_pairs=400')).json();
  const pairs = (d.pairs || []).filter(p => p.miss_km > 0.05)   // 排除對接／共位（距離≈0）
    .sort((a, b) => (b.Pc || 0) - (a.Pc || 0) || a.miss_km - b.miss_km).slice(0, 10);
  const lv = l => l === 'RED' ? '#f85149' : (l === 'AMBER' ? '#d29922' : '#3fb950');
  el.innerHTML = '<div class="kpis">' + kpi(fmtN(d.count), tpl('cdm_kpi_pairs', {thr})) +
    kpi(fmtN(d.total_scanned), t('cdm_kpi_scanned')) + kpi(tpl('cdm_kpi_elapsed', {s: d.elapsed_sec || 0}), t('cdm_kpi_elapsed_label')) +
    kpi(pairs.filter(p => p.risk_level === 'RED').length + ' / ' + pairs.filter(p => p.risk_level === 'AMBER').length, t('cdm_kpi_red_amber')) + '</div>' +
    '<table class="data"><tr><th>' + esc(t('th_cdm_primary')) + '</th><th>' + esc(t('th_cdm_secondary')) + '</th><th>' + esc(t('th_cdm_miss')) + '</th><th>' + esc(t('th_cdm_pc')) + '</th><th>' + esc(t('th_cdm_level')) + '</th><th></th></tr>' +
    pairs.map(p => '<tr><td>' + esc(p.primary_name) + '<br><span style="color:#6e7681">' + p.primary_norad + ' · ' + p.primary_alt_km + ' km</span></td>' +
      '<td>' + esc(p.secondary_name) + '<br><span style="color:#6e7681">' + p.secondary_norad + '</span></td>' +
      '<td>' + p.miss_km.toFixed(2) + ' km</td><td>' + p.Pc_str + '</td>' +
      '<td><b style="color:' + lv(p.risk_level) + '">' + p.risk_level + '</b></td>' +
      '<td><button class="nbtn" data-p="' + p.primary_norad + '" data-s="' + p.secondary_norad + '">' + esc(t('cdm_expand_btn')) + '</button></td></tr>').join('') +
    '</table><div class="note">' + esc(tpl('cdm_note', {thr, sigma: (PROV ? PROV.pc_model.replace(/^.*σ/, 'σ') : '100/500/100 m')})) + '</div>' +
    '<div class="frame" id="' + el.id + '-fr" style="display:none" data-h="820"></div>';
  el.querySelectorAll('button[data-p]').forEach(b => b.addEventListener('click', () => {
    const fr = $id(el.id + '-fr'); fr.style.display = ''; fr.querySelectorAll('iframe').forEach(f => f.remove());
    const ifr = document.createElement('iframe'); ifr.src = '/rpo?primary=' + b.dataset.p + '&secondary=' + b.dataset.s;
    ifr.style.height = frameHeight(820); fr.appendChild(ifr); fr.scrollIntoView({behavior: 'smooth', block: 'start'});
    el.querySelectorAll('button[data-p]').forEach(x => x.classList.toggle('on', x === b));
  }));
  if(pairs.length && new URLSearchParams(location.search).get('autoplay')) el.querySelector('button[data-p]').click();
}

async function initReentry(el){
  const d = await (await fetch('/api/story/reentry')).json();
  if(d.error){ el.innerHTML = '<div class="ph">' + esc(d.error) + '</div>'; return; }
  const f = t => (t || '—').replace('T', ' ').replace('Z', 'Z');
  const T = Object.values(d.targets || {});
  let h = '<div class="kpis">' + T.map(tg => {
    const mc = tg.stage2_mc || {}, s1 = (tg.stage1 || {}).reentry_pass || {};
    return kpi(f(mc.t_median).slice(5, 16), tpl('re_kpi_mc_median', {name: tg.name})) +
           kpi((mc.lat_median != null ? mc.lat_median + '°, ' + mc.lon_median + '°' : '—'), tpl('re_kpi_mc_pos', {name: tg.name, h: mc.spread_hours ?? '—'})) +
           kpi(((tg.stage2_vs_esa || {}).dt_hours_vs_esa ?? '—') + ' h', tpl('re_kpi_vs_esa', {name: tg.name}));
  }).join('') + '</div>';
  h += '<table class="data"><tr><th>' + esc(t('th_re_sat')) + '</th><th>' + esc(t('th_re_last_tle')) + '</th><th>' + esc(t('th_re_s1')) + '</th><th>' + esc(t('th_re_s2')) + '</th><th>' + esc(t('th_re_esa')) + '</th><th>' + esc(t('th_re_delta')) + '</th></tr>' +
    T.map(tg => { const s1 = (tg.stage1 || {}).reentry_pass || {}, mc = tg.stage2_mc || {};
      return '<tr><td style="text-align:left">' + esc(tg.name) + '<br><span style="color:#6e7681">' + tg.norad + '</span></td><td>' + (tg.tle_epoch || '').slice(0, 10) + '</td>' +
        '<td style="text-align:left">' + f(s1.t) + '<br>' + (s1.lat ?? '') + '°, ' + (s1.lon ?? '') + '°（' + (s1.alt_km ?? '') + ' km）</td>' +
        '<td style="text-align:left">' + f(mc.t_median) + '<br>' + (mc.lat_median ?? '') + '°, ' + (mc.lon_median ?? '') + '°' + tpl('re_reentered', {n: mc.n_reentered ?? 0, total: mc.n ?? 0}) + '</td>' +
        '<td style="text-align:left">' + f(tg.esa_t) + ' ±' + tg.esa_unc_min + ' min<br>' + esc(tg.esa_region || '') + '</td>' +
        '<td>' + ((tg.stage1_vs_esa || {}).dt_hours_vs_esa ?? '—') + ' h／' + ((tg.stage2_vs_esa || {}).dt_hours_vs_esa ?? '—') + ' h</td></tr>'; }).join('') + '</table>';
  const hc = d.hindcast || {};
  if(hc.cases && hc.cases.length){
    h += '<details class="evd" open><summary>' + esc(t('re_hindcast_summary')) + '</summary><table class="data"><tr><th>' + esc(t('th_re_hc_lead')) + '</th><th>' + esc(t('th_re_hc_tle')) + '</th><th>' + esc(t('th_re_hc_s1err')) + '</th><th>' + esc(t('th_re_hc_s2err')) + '</th><th>' + esc(t('th_re_hc_mcerr')) + '</th><th>' + esc(t('th_re_hc_mcspread')) + '</th></tr>' +
      hc.cases.map(c => '<tr><td>' + esc(tpl('re_lead_days', {n: c.lead_days})) + '</td><td>' + (c.tle_epoch || '').slice(0, 10) + '</td><td>' + (c.stage1_err_h ?? '—') + ' h</td><td>' + (c.stage2_err_h ?? '—') + ' h</td><td>' + (c.mc_err_h ?? '—') + ' h</td><td>' + (c.mc_spread_h ?? '—') + ' h</td></tr>').join('') + '</table>' +
      (d.calibration ? '<div class="note">' + esc(tpl('re_calib_note', {scale: d.calibration.best_scale, scales: (d.calibration.scales || []).join('/'), err: JSON.stringify(d.calibration.mean_err_h_by_scale || {})})) + '</div>' : '') + '</details>';
  }
  const stf = d.spacetrack_forecast || {};
  const stl = Object.entries(stf).filter(([k, v]) => Array.isArray(v) && v.length).map(([k, v]) => k + '：' + v[0]._class + ' ' + (v[0].DECAY_EPOCH || '') + tpl('re_msg_suffix', {src: v[0].SOURCE, msg: v[0].MSG_EPOCH}));
  if(stl.length) h += '<div class="note">' + esc(tpl('re_spacetrack_note', {s: stl.join('；')})) + '</div>';
  h += '<div class="note">' + esc((d.method || {}).stage1 || '') + '｜' + esc((d.method || {}).stage2 || '') + '｜' + esc((d.method || {}).caveat || '') + esc(tpl('re_generated', {t: f(d.generated_at)})) + '</div>';
  el.innerHTML = h;
}

const LAZY_INIT = {groupstats: initGroupStats, maneuvers: initManeuvers, radar: initRadar,
                   skyplot: initSkyplot, cdm: initCdm, isrres: initIsrRes, reentry: initReentry,
                   revisit: initRevisit, shells: initShells};
function initLazy(el){
  if(el.classList.contains('inited')) return;
  el.classList.add('inited');
  const fn = LAZY_INIT[el.dataset.kind];
  if(fn) fn(el).catch(e => { el.innerHTML = '<div class="ph">' + esc(tpl('err_load_fail', {err: String(e)})) + '</div>'; });
}

/* ── 單一故事 ── */
async function renderStory(sid){
  CUR_SID = sid;
  const wrap = $id('wrap');
  const r = await fetch('/api/story/' + encodeURIComponent(sid));
  if(!r.ok){ wrap.innerHTML = '<div style="padding:60px 0">' + esc(t('err_story_not_found')) + '<a href="/story">' + esc(t('err_story_back')) + '</a></div>'; return; }
  const st = await r.json();
  await loadProv();
  applyStaticI18n();
  document.title = st.title + ' — Story';
  $id('hdr-title').textContent = st.title;
  $id('lnk-list').style.display = '';

  // 封面（標題／副標／說明）併入第一節上方，不再獨立佔一整頁（滿頁吸附下獨立封面會卡在第一頁）
  const heroHtml = '<div class="hero-in"><h2>' + esc(st.title) + '</h2>' +
          '<div class="sub">' + esc(st.subtitle || '') + '</div>' +
          (st.hero_cards ? '<div class="hcards" id="hcards"><div class="ph">' + esc(t('hero_loading')) + '</div></div>' : '') +
          (st.hero_note ? '<div class="note">' + esc(st.hero_note) + '</div>' : '') + provHtml() + '</div>';
  if(st.hero_cards) setTimeout(() => initHeroCards(st.hero_cards), 0);
  let h = '';

  const SECS = st.sections || [];
  const dotIds = [];
  SECS.forEach((sec, i) => {
    const aid = sec.anchor || ('sec' + i);
    dotIds.push({id: aid, title: sec.title || ''});
    h += '<div class="sec' + (i === 0 ? ' first vis' : '') + '" id="' + esc(aid) + '" data-dur="' + (sec.dur || 1) + '" data-type="' + esc(sec.type || 'text') + '">' +
         (i === 0 ? heroHtml : '') +
         '<h3>' + esc(sec.title || '') + '</h3>';
    if(sec.body) h += '<div class="body">' + esc(sec.body) + '</div>';
    h += '<div class="sec-body">';
    if(sec.type === 'toc'){
      h += tocHtml(sec);
    }else if(sec.type === 'faq'){
      h += faqHtml(sec);
    }else if(sec.type === 'table'){
      h += '<table class="launch"><tr>' +
           sec.columns.map(c => '<th>' + esc(c) + '</th>').join('') + '</tr>';
      sec.rows.forEach((row, ri) => {
        const anchor = (sec.row_anchors || [])[ri] || '';
        h += '<tr class="rw"' + (anchor ? ' data-go="' + esc(anchor) + '"' : '') + '>' +
             row.map(c => '<td>' + mdCell(c) + '</td>').join('') + '</tr>';
      });
      h += '</table>';
      if(sec.note) h += '<div class="tbl-note">' + esc(sec.note) + '</div>';
    }else if(sec.type === 'image'){
      h += '<figure class="img-sec">' +
           '<img src="' + esc(sec.src || '') + '" alt="' + esc(sec.alt || sec.title || '') + '" loading="lazy">' +
           (sec.caption ? '<figcaption>' + mdCell(sec.caption) + '</figcaption>' : '') +
           '</figure>';
    }else if(sec.type === 'sat'){
      h += satFrame(sec, i);
    }else if(sec.type === 'positions'){
      h += '<div class="pm-wrap"><div class="pm-seq"></div>' +
           '<div class="posmap" id="pm' + i + '" data-mode="' + esc(sec.mode || 'all') + '"' +
           (sec.val ? ' data-val="' + esc(sec.val) + '"' : '') +
           (sec.ids ? ' data-ids="' + sec.ids.join(',') + '"' : '') +
           (sec.sequence ? ' data-seq="1"' : '') +
           (sec.globe ? ' data-globe="1"' : '') +
           '><div class="ph">' + esc(t('ph_scroll_load_pos')) + '</div></div>' +
           '<div class="pm-cap"></div></div>';
    }else if(sec.type === 'embed'){
      h += '<div class="frame" data-src="' + esc(sec.url) + '" data-h="' +
           (sec.height || 860) + '"><div class="ph">' + esc(t('ph_scroll_load')) + '</div></div>';
    }else if(LAZY_INIT[sec.type]){
      h += '<div class="lazy" id="lz' + i + '" data-kind="' + sec.type + '"' +
           (sec.group ? ' data-group="' + esc(sec.group) + '"' : '') +
           (sec.groups ? ' data-groups="' + sec.groups.join(',') + '"' : '') +
           (sec.n ? ' data-n="' + sec.n + '"' : '') +
           (sec.norads ? ' data-norads="' + sec.norads.join(',') + '"' : '') +
           (sec.threshold_km ? ' data-thr="' + sec.threshold_km + '"' : '') +
           (sec.site ? ' data-site="' + esc(sec.site) + '"' : '') +
           '><div class="ph">' + esc(t('ph_scroll_load')) + '</div></div>';
    }
    h += '</div></div>';
  });
  wrap.innerHTML = h;
  setupStepNav();

  // NORAD 對應設定保存（sat 多星切換用）
  const cfgMap = {}; SECS.forEach((sec, i) => cfgMap[i] = sec);

  const dots = $id('dots');
  dots.innerHTML = dotIds.map(d =>
    '<a href="#' + esc(d.id) + '" title="' + esc(d.title) + '" data-for="' + esc(d.id) + '"></a>').join('');

  wrap.querySelectorAll('tr.rw[data-go]').forEach(tr =>
    tr.addEventListener('click', () => {
      const el = document.getElementById(tr.dataset.go);
      if(el) el.scrollIntoView({behavior: 'smooth'});
    }));

  wrap.querySelectorAll('.nbtn[data-fr]').forEach(b =>
    b.addEventListener('click', () => {
      const fr = document.getElementById(b.dataset.fr);
      fr.querySelectorAll('iframe').forEach(f => f.remove());
      const ifr = document.createElement('iframe');
      ifr.src = orbitUrl(b.dataset.norad, cfgMap[b.dataset.cfg] || {});
      ifr.style.height = frameHeight(+fr.dataset.h);
      fr.appendChild(ifr);
      const ph = fr.querySelector('.ph'); if(ph) ph.remove();
      fr.parentElement.querySelectorAll('.nbtn').forEach(x => x.classList.toggle('on', x === b));
    }));

  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if(en.isIntersecting){
        en.target.classList.add('vis');
        const fr = en.target.querySelector('.frame');
        if(fr) loadFrame(fr);
        const pm = en.target.querySelector('.posmap');
        if(pm) initPosMap(pm);
        const lz = en.target.querySelector('.lazy');
        if(lz) initLazy(lz);
        dots.querySelectorAll('a').forEach(a =>
          a.classList.toggle('on', a.dataset.for === en.target.id));
      }
    });
  }, {rootMargin: '300px 0px -30% 0px', threshold: 0.02});
  wrap.querySelectorAll('.sec').forEach(s => io.observe(s));

  // ── 自動導覽（?autoplay=<總秒數>）──
  const total = parseFloat(new URLSearchParams(location.search).get('autoplay') || '0');
  if(total > 0) startTour(total);
}

function startTour(totalSec){
  const secs = [...document.querySelectorAll('.sec')];
  if(!secs.length) return;
  const heroDur = 0;   // 封面已併入第一節
  const weights = secs.map(s => parseFloat(s.dataset.dur) || 1);
  const wsum = weights.reduce((a, b) => a + b, 0);
  const durs = weights.map(w => (totalSec - heroDur) * w / wsum);
  let i = -1;
  function next(){
    i += 1;
    if(i >= secs.length) return;
    secs[i].scrollIntoView({behavior: 'smooth', block: 'start'});
    setTimeout(next, durs[i] * 1000);
  }
  window.scrollTo(0, 0);
  setTimeout(next, heroDur * 1000);
}

applyStaticI18n();
if(window.STORY_ID) renderStory(window.STORY_ID);
else renderList();
