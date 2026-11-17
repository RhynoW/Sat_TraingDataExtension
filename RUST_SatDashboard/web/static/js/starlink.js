"use strict";
/* ═══════════════════════════════════════════════════════════════════════════
   Starlink 台灣服務能力分析前端
   功能：可見性時間軸、RTT 傳播延遲、極座標天空密度、遮蔽模擬、三語（中/英/日）
   ═══════════════════════════════════════════════════════════════════════════ */

// ── 全域狀態 ──────────────────────────────────────────────────────────────────
let _polling   = false;
let _data      = null;     // 主要可見性計算結果
let _obstData  = null;     // 遮蔽模擬結果
let _polarMode = 'density';
let _blocked   = new Set();  // "az_c,el_c" 字串集合
let _maskDeg   = 25;
let _lastPreset    = null;   // {lat,lon,cityKey}
let _obstBtnBusy   = false;

// ── 三語字典 ──────────────────────────────────────────────────────────────────
const I18N = {
  zh: {
    doc_title: 'Starlink 台灣服務能力分析',
    app_title: 'Starlink 台灣服務能力分析',
    app_subtitle: '幾何可用性 · 延遲估算 · 天空覆蓋 · 遮蔽模擬',
    nav_taipei: '台北覆蓋', nav_story: 'StoryMap', nav_home: '主頁',
    lbl_lat: '緯度', lbl_lon: '經度', lbl_mask: '遮蔽仰角',
    lbl_mask_deg_suffix: '°　　城市預設：',
    preset_btn: '選擇',
    city_taipei: '台北', city_taichung: '台中', city_tainan: '台南',
    city_kaohsiung: '高雄', city_hualien: '花蓮', city_kinmen: '金門', city_penghu: '澎湖',
    compute_btn: '計算',
    settings_note_default: '預報時距 24 小時，步長 15 分鐘，Starlink 終端建議遮蔽仰角 25°',
    settings_note_preset: '已選擇：{name}（{lat}N, {lon}E），遮蔽仰角建議 25°',
    loading_msg_default: '正在向量化計算 6000+ 顆 Starlink 可見性，請稍候...',
    loading_msg_compute: '正在向量化計算 Starlink 可見性（{lat}N, {lon}E，仰角 ≥ {mask}°）...',
    error_prefix: '錯誤：{error}',
    stat_total: '資料庫衛星數', stat_mean: '平均可見顆數', stat_min: '最低可見顆數',
    stat_avail: '幾何可用率', stat_rtt_mean: '平均 RTT 下限', stat_rtt_range: 'RTT 下限範圍',
    stat_gaps: '覆蓋空窗次數',
    stat_excluded: '已排除離軌中衛星', stat_excluded_link: '查看即時離軌名單 →',
    lbl_generation: '世代篩選', lbl_dropout: '備援折損模擬', gen_all: '全部',
    timeline_title: '可見衛星數量時間軸（24 小時）',
    rtt_title: '傳播延遲下限（RTT floor，ms）',
    rtt_note: '純幾何傳播延遲（光速 × 斜距 × 2）；不含地面基礎設施，台灣無本地閘道時估計額外加 30~50 ms',
    timeline_note: '計算時刻：{ts}　步長：{step} 分',
    tab_density: '密度圖', tab_obstruct: '遮蔽模擬',
    polar_density_note: '中心 = 天頂 ・ 外環 = 遮蔽仰角 ・ 顏色越深衛星密度越高',
    obstruct_hint: '點擊天空格子標記遮蔽區域（紅色）',
    btn_clear_all: '清除全部', btn_apply_obst: '計算遮蔽影響', btn_computing: '計算中...',
    block_count: '已選 {n} 格',
    obst_result_title: '遮蔽模擬結果', btn_close: '關閉', obst_chart_title: '遮蔽前後對比',
    gaps_box_title: '幾何覆蓋空窗（可見衛星數 < 1）',
    gap_ok: '覆蓋連續，24 小時內無幾何空窗',
    gap_dur: '{n} 分鐘',
    gap_total: '合計空窗：{min} 分鐘（{hr} 小時）',
    obst_before: '遮蔽前', obst_after: '遮蔽後（{n} 格封鎖）',
    obst_sub: '平均可見 {mean} 顆　空窗 {gaps} 次',
    obst_new_gaps_title: '遮蔽後新增空窗', obst_still_ok: '遮蔽後仍無空窗',
    alert_no_cells: '請先在遮蔽模擬模式下點選要封鎖的天空格子',
    alert_obst_fail: '遮蔽計算失敗：{error}',
    axis_visible: '可見顆數', axis_rtt: 'RTT ms',
    label_now: '現在', rtt_no_data: 'RTT 資料不可用', label_zenith: '天頂',
    roadmap_title: '功能藍圖 — Starlink 台灣分析工具',
    badge_done: '已實作', badge_plan: '規劃中',
    layer1_title: '第一層 — 連線品質預測（對一般用戶最直接）',
    card1_1_title: '可見衛星數量時間軸',
    card1_1_desc: '以用戶座標 + 仰角遮蔽計算 24 小時可見衛星數時間序列，是服務幾何可用性的最佳代理指標。',
    card1_2_title: '覆蓋空窗偵測',
    card1_2_desc: '標出可見數低於門檻的時段。台灣緯度覆蓋極佳，斷線多為遮蔽或雨衰，而非幾何因素。',
    card1_3_title: '天空密度覆蓋圖',
    card1_3_desc: '極座標天空密度圖告訴用戶天線朝哪個方向淨空優先，取代「北半球朝北」的一般經驗法則。',
    card1_4_title: '遮蔽模擬',
    card1_4_desc: '點選天空格子描繪地形 / 建物遮蔽，即時計算扣除遮蔽後的幾何可用率與空窗變化。',
    card1_5_title: '傳播延遲下限估計',
    card1_5_desc: '由最近可見衛星斜距計算光速往返時間（RTT floor）。Starlink 在台灣典型約 4–9 ms，加上閘道路由後實際約 25–45 ms。',
    layer2_title: '第二層 — 進階網路品質分析（重度用戶 / 企業 / 研究者）',
    card2_1_title: '換手頻率估計',
    card2_1_desc: '追蹤「最高仰角衛星」隨時間的切換次數，換手密集時段對應較高的 jitter。',
    card2_2_title: '閘道站可及性分析',
    card2_2_desc: '判斷每顆衛星是否同時可見日本、菲律賓等鄰近閘道（bent-pipe），或標記具 ISL 星間鏈路的 Gen2 衛星。',
    card2_3_title: '雨衰風險指標',
    card2_3_desc: 'Ku/Ka 頻段在台灣強降雨衰減顯著，低仰角鏈路穿越更長雨層路徑，結合即時天氣提供精確服務品質預警。',
    layer3_title: '第三層 — 台灣情境韌性分析（SSA / 通訊韌性）',
    card3_1_title: '備援情境模擬',
    card3_1_desc: '隨機折損 0～90% 衛星，觀察台灣可見數與可用率的退化程度（呼應 2024 東部強震海纜受損、單一路徑失效的韌性議題；可與海纜頁 /cable 對照）。',
    card3_2_title: '世代 / 機型篩選',
    card3_2_desc: '依發射日期啟發式區分 v1.0／v1.5／v2 Mini／V3 世代子集合分析可用性；並自動排除近期偵測為離軌中的衛星（詳見「離軌名單」分頁）。',
    status_note_label: '現況說明',
    status_note_body: '《電信管理法》第 36 條修正案已於 2026 年 7 月 21 日三讀通過，取消外資持股上限，改由主管機關依國家安全等 7 項標準逐案審核核准；惟截至目前 Starlink 尚未取得正式核准、也還未在台灣商轉。本工具基於公開 TLE 資料計算純幾何可用性，供技術評估與政策討論參考。',
  },
  en: {
    doc_title: 'Starlink Taiwan Service Availability Analysis',
    app_title: 'Starlink Taiwan Service Availability Analysis',
    app_subtitle: 'Geometric Availability · Latency Estimate · Sky Coverage · Obstruction Simulation',
    nav_taipei: 'Taipei Coverage', nav_story: 'StoryMap', nav_home: 'Home',
    lbl_lat: 'Latitude', lbl_lon: 'Longitude', lbl_mask: 'Mask Elevation',
    lbl_mask_deg_suffix: '°   City Preset:',
    preset_btn: 'Select',
    city_taipei: 'Taipei', city_taichung: 'Taichung', city_tainan: 'Tainan',
    city_kaohsiung: 'Kaohsiung', city_hualien: 'Hualien', city_kinmen: 'Kinmen', city_penghu: 'Penghu',
    compute_btn: 'Compute',
    settings_note_default: 'Forecast window 24h, step 15min. Recommended mask elevation for Starlink terminals: 25°',
    settings_note_preset: 'Selected: {name} ({lat}N, {lon}E), recommended mask elevation 25°',
    loading_msg_default: 'Vectorized computation of 6000+ Starlink satellites\' visibility in progress...',
    loading_msg_compute: 'Computing vectorized Starlink visibility ({lat}N, {lon}E, elevation ≥ {mask}°)...',
    error_prefix: 'Error: {error}',
    stat_total: 'Satellites in Database', stat_mean: 'Mean Visible Count', stat_min: 'Min Visible Count',
    stat_avail: 'Geometric Availability', stat_rtt_mean: 'Mean RTT Floor', stat_rtt_range: 'RTT Floor Range',
    stat_gaps: 'Coverage Gap Count',
    stat_excluded: 'Deorbiting Excluded', stat_excluded_link: 'View live deorbit list →',
    lbl_generation: 'Generation', lbl_dropout: 'Redundancy Loss Sim', gen_all: 'All',
    timeline_title: 'Visible Satellite Count Timeline (24h)',
    rtt_title: 'Propagation Latency Floor (RTT floor, ms)',
    rtt_note: 'Pure geometric propagation delay (speed of light × slant range × 2); excludes ground infrastructure — without a local gateway in Taiwan, add an estimated 30–50 ms',
    timeline_note: 'Computed at: {ts}   Step: {step} min',
    tab_density: 'Density Map', tab_obstruct: 'Obstruction Sim',
    polar_density_note: 'Center = Zenith ・ Outer ring = Mask elevation ・ Darker = higher satellite density',
    obstruct_hint: 'Click sky cells to mark obstructed areas (red)',
    btn_clear_all: 'Clear All', btn_apply_obst: 'Compute Obstruction Impact', btn_computing: 'Computing...',
    block_count: '{n} cells selected',
    obst_result_title: 'Obstruction Simulation Result', btn_close: 'Close', obst_chart_title: 'Before / After Comparison',
    gaps_box_title: 'Geometric Coverage Gaps (visible count < 1)',
    gap_ok: 'Continuous coverage — no geometric gaps in 24h',
    gap_dur: '{n} min',
    gap_total: 'Total gap time: {min} min ({hr} h)',
    obst_before: 'Before', obst_after: 'After ({n} cells blocked)',
    obst_sub: 'Mean visible {mean}   Gaps {gaps}',
    obst_new_gaps_title: 'New Gaps After Obstruction', obst_still_ok: 'Still no gaps after obstruction',
    alert_no_cells: 'Please select sky cells to block in obstruction simulation mode first',
    alert_obst_fail: 'Obstruction computation failed: {error}',
    axis_visible: 'Visible Count', axis_rtt: 'RTT ms',
    label_now: 'Now', rtt_no_data: 'RTT data unavailable', label_zenith: 'Zenith',
    roadmap_title: 'Feature Roadmap — Starlink Taiwan Analysis Tool',
    badge_done: 'Implemented', badge_plan: 'Planned',
    layer1_title: 'Layer 1 — Connection Quality Prediction (Most direct for general users)',
    card1_1_title: 'Visible Satellite Count Timeline',
    card1_1_desc: 'Computes a 24-hour time series of visible satellite count from user coordinates and elevation mask — the best proxy for geometric service availability.',
    card1_2_title: 'Coverage Gap Detection',
    card1_2_desc: "Flags periods where visible count falls below threshold. Taiwan's latitude has excellent geometric coverage — disconnections are usually caused by obstruction or rain fade, not geometry.",
    card1_3_title: 'Sky Density Coverage Map',
    card1_3_desc: "A polar sky density map shows users which direction to prioritize keeping clear, replacing the generic 'point north in the northern hemisphere' rule of thumb.",
    card1_4_title: 'Obstruction Simulation',
    card1_4_desc: 'Click sky cells to sketch terrain / building obstruction and instantly compute the resulting change in geometric availability and gaps.',
    card1_5_title: 'Propagation Latency Floor Estimate',
    card1_5_desc: "Computes speed-of-light round-trip time (RTT floor) from the nearest visible satellite's slant range. Starlink in Taiwan is typically ~4–9 ms geometrically, with actual RTT around 25–45 ms once gateway routing is included.",
    layer2_title: 'Layer 2 — Advanced Network Quality Analysis (Power users / Enterprise / Researchers)',
    card2_1_title: 'Handover Frequency Estimate',
    card2_1_desc: "Tracks how often the 'highest-elevation satellite' switches over time; periods of frequent handover correspond to higher jitter.",
    card2_2_title: 'Gateway Reachability Analysis',
    card2_2_desc: 'Determines whether each satellite can simultaneously see a nearby gateway in Japan, the Philippines, etc. (bent-pipe), or flags Gen2 satellites with inter-satellite links (ISL).',
    card2_3_title: 'Rain Fade Risk Indicator',
    card2_3_desc: "Ku/Ka band signals attenuate significantly in Taiwan's heavy rainfall; low-elevation links traverse a longer path through the rain layer. Combined with real-time weather data, this provides precise service-quality warnings.",
    layer3_title: 'Layer 3 — Taiwan Scenario Resilience Analysis (SSA / Communication Resilience)',
    card3_1_title: 'Redundancy Scenario Simulation',
    card3_1_desc: 'Randomly drops 0–90% of satellites to show how visible count and availability over Taiwan degrade (echoing the resilience lessons of the 2024 eastern Taiwan earthquake submarine cable damage — see also the /cable page).',
    card3_2_title: 'Generation / Model Filtering',
    card3_2_desc: 'Splits the constellation into v1.0 / v1.5 / v2 Mini / V3 subsets by a launch-date heuristic, and automatically excludes satellites currently detected as deorbiting (see the "Deorbiting" tab).',
    status_note_label: 'Current Status',
    status_note_body: "An amendment to Article 36 of the Telecommunications Management Act passed its third reading on July 21, 2026, removing the foreign-ownership cap and replacing it with a case-by-case review against 7 criteria (including national security) by the competent authority; however, as of now Starlink has not yet obtained formal approval or launched commercial service in Taiwan. This tool computes pure geometric availability from public TLE data, for technical evaluation and policy discussion reference only.",
  },
  ja: {
    doc_title: 'Starlink 台湾サービス可用性分析',
    app_title: 'Starlink 台湾サービス可用性分析',
    app_subtitle: '幾何学的可用性 ・ 遅延推定 ・ 天空カバレッジ ・ 遮蔽シミュレーション',
    nav_taipei: '台北カバレッジ', nav_story: 'StoryMap', nav_home: 'ホーム',
    lbl_lat: '緯度', lbl_lon: '経度', lbl_mask: '遮蔽仰角',
    lbl_mask_deg_suffix: '°　　都市プリセット：',
    preset_btn: '選択',
    city_taipei: '台北', city_taichung: '台中', city_tainan: '台南',
    city_kaohsiung: '高雄', city_hualien: '花蓮', city_kinmen: '金門', city_penghu: '澎湖',
    compute_btn: '計算',
    settings_note_default: '予報期間24時間、ステップ15分。Starlink端末の推奨遮蔽仰角は25°',
    settings_note_preset: '選択済み：{name}（{lat}N, {lon}E）、推奨遮蔽仰角 25°',
    loading_msg_default: '6000機以上のStarlink可視性をベクトル計算中、しばらくお待ちください...',
    loading_msg_compute: 'Starlink可視性をベクトル計算中（{lat}N, {lon}E、仰角 ≥ {mask}°）...',
    error_prefix: 'エラー：{error}',
    stat_total: 'データベース衛星数', stat_mean: '平均可視衛星数', stat_min: '最小可視衛星数',
    stat_avail: '幾何学的可用率', stat_rtt_mean: '平均RTT下限', stat_rtt_range: 'RTT下限範囲',
    stat_gaps: 'カバレッジギャップ回数',
    stat_excluded: '離軌中除外数', stat_excluded_link: 'リアルタイム離軌リストを見る →',
    lbl_generation: '世代フィルタ', lbl_dropout: '冗長性損失シミュレーション', gen_all: 'すべて',
    timeline_title: '可視衛星数タイムライン（24時間）',
    rtt_title: '伝搬遅延下限（RTT floor、ms）',
    rtt_note: '純粋な幾何学的伝搬遅延（光速 × スラントレンジ × 2）。地上インフラを含まず、台湾にローカルゲートウェイがない場合は推定30〜50ms追加',
    timeline_note: '計算時刻：{ts}　ステップ：{step}分',
    tab_density: '密度マップ', tab_obstruct: '遮蔽シミュレーション',
    polar_density_note: '中心＝天頂 ・ 外環＝遮蔽仰角 ・ 色が濃いほど衛星密度が高い',
    obstruct_hint: '天空セルをクリックして遮蔽エリア（赤）をマーク',
    btn_clear_all: 'すべて消去', btn_apply_obst: '遮蔽影響を計算', btn_computing: '計算中...',
    block_count: '{n} セル選択済み',
    obst_result_title: '遮蔽シミュレーション結果', btn_close: '閉じる', obst_chart_title: '遮蔽前後の比較',
    gaps_box_title: '幾何学的カバレッジギャップ（可視衛星数 < 1）',
    gap_ok: '連続カバレッジ、24時間以内に幾何学的ギャップなし',
    gap_dur: '{n} 分',
    gap_total: '合計ギャップ時間：{min}分（{hr}時間）',
    obst_before: '遮蔽前', obst_after: '遮蔽後（{n}セル遮断）',
    obst_sub: '平均可視 {mean}　ギャップ {gaps}回',
    obst_new_gaps_title: '遮蔽後の新規ギャップ', obst_still_ok: '遮蔽後もギャップなし',
    alert_no_cells: '先に遮蔽シミュレーションモードで遮断するセルを選択してください',
    alert_obst_fail: '遮蔽計算に失敗：{error}',
    axis_visible: '可視数', axis_rtt: 'RTT ms',
    label_now: '現在', rtt_no_data: 'RTTデータなし', label_zenith: '天頂',
    roadmap_title: '機能ロードマップ — Starlink台湾分析ツール',
    badge_done: '実装済み', badge_plan: '計画中',
    layer1_title: 'レイヤー1 — 接続品質予測（一般ユーザーに最も直接的）',
    card1_1_title: '可視衛星数タイムライン',
    card1_1_desc: 'ユーザー座標と仰角マスクから24時間の可視衛星数時系列を計算。サービスの幾何学的可用性を示す最良の代理指標。',
    card1_2_title: 'カバレッジギャップ検出',
    card1_2_desc: '可視数が閾値を下回る時間帯をフラグ表示。台湾の緯度は幾何学的カバレッジが非常に良好で、切断の多くは遮蔽や雨減衰によるもので幾何学的要因ではない。',
    card1_3_title: '天空密度カバレッジマップ',
    card1_3_desc: '極座標の天空密度マップは、アンテナをどの方向に向けて開けておくべきかを示し、「北半球では北向き」という一般的な経験則に代わるものとなる。',
    card1_4_title: '遮蔽シミュレーション',
    card1_4_desc: '天空セルをクリックして地形・建物の遮蔽を描画し、遮蔽後の幾何学的可用率とギャップの変化をリアルタイムで計算。',
    card1_5_title: '伝搬遅延下限推定',
    card1_5_desc: '最も近い可視衛星のスラントレンジから光速往復時間（RTT floor）を計算。台湾でのStarlinkは幾何学的には約4〜9msだが、ゲートウェイ経由の実際のRTTは約25〜45ms。',
    layer2_title: 'レイヤー2 — 高度なネットワーク品質分析（ヘビーユーザー・企業・研究者向け）',
    card2_1_title: 'ハンドオーバー頻度推定',
    card2_1_desc: '「最高仰角衛星」の時間経過による切替回数を追跡。ハンドオーバーが頻繁な時間帯はジッターが高くなる傾向。',
    card2_2_title: 'ゲートウェイ到達可能性分析',
    card2_2_desc: '各衛星が日本やフィリピンなど近隣のゲートウェイ（ベントパイプ）を同時に可視できるか判定、またはISL（衛星間リンク）を持つGen2衛星をフラグ表示。',
    card2_3_title: '雨減衰リスク指標',
    card2_3_desc: 'Ku/Ka帯は台湾の豪雨で減衰が顕著。低仰角リンクは雨層をより長く通過する。リアルタイム気象データと組み合わせて精密なサービス品質警告を提供。',
    layer3_title: 'レイヤー3 — 台湾シナリオ・レジリエンス分析（SSA・通信レジリエンス）',
    card3_1_title: '冗長性シナリオシミュレーション',
    card3_1_desc: '衛星を0～90%ランダムに損失させ、台湾上空の可視数と可用率の劣化度をシミュレート（2024年台湾東部地震での海底ケーブル損傷問題を踏まえたレジリエンス検討。/cableページも参照）。',
    card3_2_title: '世代・機種フィルタリング',
    card3_2_desc: '打ち上げ日による推定でv1.0／v1.5／v2 Mini／V3世代のサブセットに分けて可用性を分析し、直近で離軌中と判定された衛星を自動的に除外（「離軌リスト」タブを参照）。',
    status_note_label: '現状説明',
    status_note_body: '電信管理法第36条の改正案は2026年7月21日に第三読会を通過し、外資持株比率の上限が撤廃され、国家安全保障など7つの基準に基づく主務官庁による個別審査・承認制に変更された。ただし現時点でStarlinkはまだ正式な認可を取得しておらず、台湾での商用サービスも開始していない。本ツールは公開TLEデータに基づく純粋な幾何学的可用性を計算するものであり、技術評価および政策議論の参考情報として提供する。',
  },
};
const LOCALE_MAP = {zh:'zh-TW', en:'en-US', ja:'ja-JP'};
let LANG = localStorage.getItem('starlink_lang') || 'zh';
if(!I18N[LANG]) LANG = 'zh';

function t(key){
  const d = I18N[LANG] || I18N.zh;
  return (key in d) ? d[key] : (I18N.zh[key] !== undefined ? I18N.zh[key] : key);
}
function tpl(key, vars){
  let s = t(key);
  Object.keys(vars || {}).forEach(k => { s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]); });
  return s;
}

// ── 語言切換 ──────────────────────────────────────────────────────────────────
function setLang(lang){
  if(!I18N[lang]) return;
  LANG = lang;
  localStorage.setItem('starlink_lang', lang);
  document.documentElement.lang = LOCALE_MAP[lang] || 'zh-TW';
  document.title = t('doc_title');

  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === lang);
  });

  updateSettingsNote();
  updateBlockCount();
  if(_obstBtnBusy){
    const btn = document.getElementById('apply-obst-btn');
    if(btn) btn.textContent = t('btn_computing');
  }

  if(_data){
    renderStats(_data.stats);
    renderLineChart(_data.timeline, _data.stats, _obstData ? _obstData.timeline : undefined);
    renderRttChart(_data.timeline, _data.stats);
    _redrawPolar();
    renderGaps(_data.gaps, _data.stats);
    updateTimelineNote(_data);
    if(_obstData) renderObstructionResult(_obstData);
  }
}

// ── 時鐘 ──────────────────────────────────────────────────────────────────────
function _tick(){
  const el=document.getElementById('clock');
  if(el) el.textContent=new Date().toUTCString().replace('GMT','UTC');
}

// ── 城市預設下拉 ──────────────────────────────────────────────────────────────
function togglePreset(){
  document.getElementById('preset-menu').classList.toggle('open');
}
function applyPreset(lat,lon,cityKey){
  document.getElementById('sf-lat').value=lat;
  document.getElementById('sf-lon').value=lon;
  _lastPreset = {lat, lon, cityKey};
  updateSettingsNote();
  document.getElementById('preset-menu').classList.remove('open');
}
function updateSettingsNote(){
  const el = document.getElementById('settings-note');
  if(!el) return;
  if(_lastPreset){
    el.textContent = tpl('settings_note_preset',
      {name: t('city_' + _lastPreset.cityKey), lat: _lastPreset.lat, lon: _lastPreset.lon});
  } else {
    el.textContent = t('settings_note_default');
  }
}
function updateBlockCount(){
  const el = document.getElementById('block-count');
  if(el) el.textContent = tpl('block_count', {n: _blocked.size});
}
document.addEventListener('click',e=>{
  if(!e.target.closest('#preset-wrap'))
    document.getElementById('preset-menu').classList.remove('open');
});

// ── 取得輸入參數 ──────────────────────────────────────────────────────────────
function getParams(){
  const lat        = parseFloat(document.getElementById('sf-lat').value)  || 25.033;
  const lon        = parseFloat(document.getElementById('sf-lon').value)  || 121.565;
  const mask       = parseFloat(document.getElementById('sf-mask').value) || 25;
  const genEl      = document.getElementById('sf-generation');
  const generation = genEl ? genEl.value : 'all';
  const dropoutEl  = document.getElementById('sf-dropout');
  let dropout_pct  = dropoutEl ? parseFloat(dropoutEl.value) : 0;
  if(!Number.isFinite(dropout_pct)) dropout_pct = 0;
  dropout_pct = Math.max(0, Math.min(dropout_pct, 90));
  return {lat, lon, mask, generation, dropout_pct};
}

// ── Loading 狀態 ──────────────────────────────────────────────────────────────
function setLoading(on, msg){
  document.getElementById('loading-bar').classList.toggle('active', on);
  if(msg) document.getElementById('loading-msg').textContent = msg;
  document.getElementById('compute-btn').disabled = on;
}

function showResultPanels(show){
  ['stats-row','charts-row','gaps-box'].forEach(id=>{
    document.getElementById(id).style.display = show ? '' : 'none';
  });
}

// ── 觸發計算 ──────────────────────────────────────────────────────────────────
function triggerCompute(){
  if(_polling) return;
  _data = null; _obstData = null;
  _blocked.clear();
  updateBlockCount();
  document.getElementById('obst-result').style.display = 'none';
  showResultPanels(false);
  const {lat, lon, mask, generation, dropout_pct} = getParams();
  _maskDeg = mask;
  setLoading(true, tpl('loading_msg_compute', {lat: lat.toFixed(3), lon: lon.toFixed(3), mask}));
  const url = `/api/starlink/visibility?lat=${lat}&lon=${lon}&mask=${mask}&hours=24&step=15`
            + `&generation=${encodeURIComponent(generation)}&dropout_pct=${dropout_pct}`;
  _poll(url);
}

function _poll(url){
  _polling = true;
  fetch(url)
    .then(r => r.status === 202 ? null : r.json())
    .then(data => {
      if(data === null){ setTimeout(() => _poll(url), 1800); return; }
      _polling = false;
      setLoading(false);
      if(data.error){
        document.getElementById('loading-msg').textContent = tpl('error_prefix', {error: data.error});
        document.getElementById('loading-bar').classList.add('active');
        return;
      }
      _data = data;
      renderAll(data);
    })
    .catch(err => { _polling = false; setLoading(false); console.error(err); });
}

// ═══════════════════════════════════════════════════════════════════════════════
// 主渲染函數
// ═══════════════════════════════════════════════════════════════════════════════
function renderAll(data){
  showResultPanels(true);
  renderStats(data.stats);
  renderLineChart(data.timeline, data.stats);
  renderRttChart(data.timeline, data.stats);
  renderPolarDensity(data.sky_density, data.mask_deg);
  renderGaps(data.gaps, data.stats);
  updateTimelineNote(data);
}
function updateTimelineNote(data){
  const note = document.getElementById('timeline-note');
  if(note){
    const ts = new Date(data.computed_at).toUTCString().replace('GMT','UTC');
    note.textContent = tpl('timeline_note', {ts, step: data.step_min});
  }
}

// ── 統計卡片 ──────────────────────────────────────────────────────────────────
function renderStats(s){
  const set = (id, val, cls='') => {
    const el = document.getElementById(id);
    if(!el) return;
    el.textContent = val;
    el.className = 'sc-val' + (cls ? ' ' + cls : '');
  };
  set('st-total',    s.total_sats.toLocaleString());
  set('st-mean',     s.mean_visible.toFixed(1));
  set('st-min',      s.min_visible,   s.min_visible >= 1 ? 'good' : 'warn');
  set('st-avail',    s.availability_pct.toFixed(2) + '%',
                     s.availability_pct >= 99 ? 'good' : s.availability_pct >= 95 ? '' : 'warn');
  set('st-gaps',     s.gap_count,      s.gap_count === 0 ? 'good' : 'warn');
  set('st-rtt-mean', s.mean_rtt_floor_ms != null ? s.mean_rtt_floor_ms.toFixed(1) + ' ms' : '—');
  set('st-rtt-range',
      s.min_rtt_floor_ms != null
        ? `${s.min_rtt_floor_ms.toFixed(1)}–${s.max_rtt_floor_ms.toFixed(1)} ms`
        : '—');
  const excludedEl = document.getElementById('st-excluded');
  if(excludedEl){
    const excluded = s.excluded_deorbiting_count || 0;
    const dropped  = s.dropped_count || 0;
    excludedEl.textContent = dropped > 0 ? `${excluded} (+${dropped})` : String(excluded);
  }
}

// ── 空窗列表 ──────────────────────────────────────────────────────────────────
function renderGaps(gaps, stats){
  const box = document.getElementById('gaps-content');
  if(!gaps || gaps.length === 0){
    box.innerHTML = `<div class="gap-ok">&#10003; ${t('gap_ok')}</div>`;
    return;
  }
  let html = '';
  gaps.forEach(g => {
    const t1 = fmtTime(g.start), t2 = fmtTime(g.end);
    html += `<div class="gap-item">
      <span class="gap-time">${t1} – ${t2}</span>
      <span class="gap-dur">&#9673; ${tpl('gap_dur', {n: g.duration_min})}</span>
    </div>`;
  });
  if(stats.gap_total_min > 0)
    html += `<div style="font-size:11px;color:#8b949e;margin-top:6px">
      ${tpl('gap_total', {min: stats.gap_total_min, hr: (stats.gap_total_min/60).toFixed(2)})}</div>`;
  box.innerHTML = html;
}
function fmtTime(iso){ return new Date(iso).toLocaleTimeString(LOCALE_MAP[LANG] || 'zh-TW',{hour:'2-digit',minute:'2-digit'}); }

// ═══════════════════════════════════════════════════════════════════════════════
// 可見衛星數量時間軸折線圖
// ═══════════════════════════════════════════════════════════════════════════════
function renderLineChart(timeline, stats, obstrTimeline){
  const cvs = document.getElementById('timeline-canvas');
  const W   = (cvs.parentElement.clientWidth - 20) || 680;
  const H   = 160;
  _setupCanvas(cvs, W, H);
  const ctx = cvs.getContext('2d');
  _drawLineChart(ctx, W, H, timeline, stats, obstrTimeline);
}

function _drawLineChart(ctx, W, H, timeline, stats, obstrTimeline){
  const pL=46, pR=12, pT=14, pB=36;
  const cW = W-pL-pR, cH = H-pT-pB, n = timeline.length;
  const maxY = Math.max(stats.max_visible||0, 10) + Math.ceil((stats.max_visible||10)*0.12 + 2);

  ctx.clearRect(0,0,W,H);
  ctx.fillStyle = '#0d1117'; ctx.fillRect(0,0,W,H);

  const xP = i => pL + i/(n-1)*cW;
  const yP = v => pT + cH - (v/maxY)*cH;

  // Y 網格
  const yStep = Math.max(1, Math.ceil(maxY/6/5)*5);
  ctx.font = '9px monospace'; ctx.textAlign = 'right';
  for(let v=0; v<=maxY; v+=yStep){
    const y = yP(v);
    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
    _line(ctx, pL, y, pL+cW, y);
    ctx.fillStyle = '#6e7681'; ctx.fillText(v, pL-4, y+3);
  }

  // X 網格（每 3 小時）
  const stepMin = n>1 ? (24*60/(n-1)) : 15;
  ctx.textAlign = 'center';
  for(let h=0; h<=24; h+=3){
    const i = Math.round(h*60/stepMin);
    if(i>=n) break;
    const x = xP(i);
    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1; _line(ctx, x, pT, x, pT+cH);
    ctx.fillStyle = '#6e7681'; ctx.fillText(h===0?t('label_now'):`+${h}h`, x, pT+cH+14);
  }

  // 空窗區
  timeline.forEach((e,i) => {
    if(!e.available){
      ctx.fillStyle = 'rgba(244,67,54,.12)';
      const x1 = i>0?xP(i-0.5):xP(0), x2 = i<n-1?xP(i+0.5):xP(n-1);
      ctx.fillRect(x1, pT, x2-x1, cH);
    }
  });

  // 門檻虛線
  ctx.setLineDash([4,4]); ctx.strokeStyle='#F44336'; ctx.lineWidth=1;
  _line(ctx, pL, yP(1), pL+cW, yP(1));
  ctx.setLineDash([]);

  // 原始折線填色
  _fillArea(ctx, timeline, xP, yP, pL, pT, cH, 'rgba(168,85,247,.1)');

  // 遮蔽後折線（若有）
  if(obstrTimeline){
    _fillArea(ctx, obstrTimeline, xP, yP, pL, pT, cH, 'rgba(244,67,54,.08)');
    ctx.strokeStyle = '#F44336'; ctx.lineWidth = 1.5; ctx.setLineDash([5,3]);
    _drawLine(ctx, obstrTimeline, xP, yP);
    ctx.setLineDash([]);
  }

  // 原始折線
  ctx.strokeStyle = '#A855F7'; ctx.lineWidth = 2;
  _drawLine(ctx, timeline, xP, yP);

  // 軸線
  ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(pL,pT); ctx.lineTo(pL,pT+cH); ctx.lineTo(pL+cW,pT+cH); ctx.stroke();

  // Y 軸標題
  ctx.save(); ctx.translate(11, pT+cH/2); ctx.rotate(-Math.PI/2);
  ctx.font='10px sans-serif'; ctx.fillStyle='#8b949e'; ctx.textAlign='center';
  ctx.fillText(t('axis_visible'),0,0); ctx.restore();
}
function _fillArea(ctx, tl, xP, yP, pL, pT, cH, color){
  const n = tl.length;
  ctx.fillStyle = color;
  ctx.beginPath();
  tl.forEach((e,i)=>{ const x=xP(i),y=yP(e.visible); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); });
  ctx.lineTo(xP(n-1),yP(0)); ctx.lineTo(xP(0),yP(0)); ctx.closePath();
  ctx.fill();
}
function _drawLine(ctx, tl, xP, yP){
  ctx.lineJoin='round'; ctx.beginPath();
  tl.forEach((e,i)=>{ const x=xP(i),y=yP(e.visible); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); });
  ctx.stroke();
}

// ═══════════════════════════════════════════════════════════════════════════════
// RTT 傳播延遲折線圖
// ═══════════════════════════════════════════════════════════════════════════════
function renderRttChart(timeline, stats){
  const cvs = document.getElementById('rtt-canvas');
  if(!cvs) return;
  const W = (cvs.parentElement.clientWidth - 20) || 680;
  const H = 90;
  _setupCanvas(cvs, W, H);
  const ctx = cvs.getContext('2d');

  const pL=46, pR=12, pT=10, pB=28;
  const cW=W-pL-pR, cH=H-pT-pB, n=timeline.length;

  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#0d1117'; ctx.fillRect(0,0,W,H);

  const rttValues = timeline.map(e=>e.rtt_floor_ms).filter(v=>v!=null);
  if(rttValues.length === 0){
    ctx.fillStyle='#6e7681'; ctx.font='11px sans-serif'; ctx.textAlign='center';
    ctx.fillText(t('rtt_no_data'),W/2,H/2); return;
  }
  const maxRtt = Math.ceil((stats.max_rtt_floor_ms||10) * 1.15 / 2) * 2;
  const minRtt = Math.max(0, Math.floor((stats.min_rtt_floor_ms||0) * 0.85 / 2) * 2);

  const xP = i => pL + i/(n-1)*cW;
  const yP = v => pT + cH - ((v-minRtt)/(maxRtt-minRtt||1))*cH;

  // 網格
  ctx.font='9px monospace'; ctx.textAlign='right';
  const steps=[minRtt, (minRtt+maxRtt)/2, maxRtt];
  steps.forEach(v=>{
    const y = yP(v);
    ctx.strokeStyle='#21262d'; ctx.lineWidth=1; _line(ctx,pL,y,pL+cW,y);
    ctx.fillStyle='#6e7681'; ctx.fillText(v.toFixed(1),pL-3,y+3);
  });

  // 參考線：LEO 天頂 RTT（550km）
  const rtt550 = 2*550/299.792;
  if(rtt550 >= minRtt && rtt550 <= maxRtt){
    const y = yP(rtt550);
    ctx.strokeStyle='rgba(88,166,255,.3)'; ctx.lineWidth=1; ctx.setLineDash([3,3]);
    _line(ctx,pL,y,pL+cW,y); ctx.setLineDash([]);
    ctx.fillStyle='#58a6ff'; ctx.font='8px monospace'; ctx.textAlign='left';
    ctx.fillText(t('label_zenith'),pL+2,y-2);
  }

  // 折線
  ctx.strokeStyle='#58a6ff'; ctx.lineWidth=1.5; ctx.lineJoin='round';
  ctx.beginPath();
  timeline.forEach((e,i)=>{
    const v=e.rtt_floor_ms; if(v==null) return;
    const x=xP(i),y=yP(v); i===0||timeline[i-1].rtt_floor_ms==null?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  ctx.stroke();

  // X 標籤（只標 0h 和 24h）
  ctx.fillStyle='#6e7681'; ctx.font='9px monospace'; ctx.textAlign='center';
  ctx.fillText(t('label_now'),xP(0),H-2);
  ctx.fillText('+24h',xP(n-1),H-2);

  // 軸
  ctx.strokeStyle='#30363d'; ctx.lineWidth=1.5;
  ctx.beginPath(); ctx.moveTo(pL,pT); ctx.lineTo(pL,pT+cH); ctx.lineTo(pL+cW,pT+cH); ctx.stroke();

  // Y 標題
  ctx.save(); ctx.translate(11,pT+cH/2); ctx.rotate(-Math.PI/2);
  ctx.font='9px sans-serif'; ctx.fillStyle='#8b949e'; ctx.textAlign='center';
  ctx.fillText(t('axis_rtt'),0,0); ctx.restore();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 極座標天空圖
// ═══════════════════════════════════════════════════════════════════════════════
function setPolarMode(mode){
  _polarMode = mode;
  document.getElementById('tab-density').classList.toggle('active', mode==='density');
  document.getElementById('tab-obstruct').classList.toggle('active', mode==='obstruct');
  document.getElementById('polar-density-note').style.display = mode==='density' ? '' : 'none';
  document.getElementById('obstruct-controls').style.display  = mode==='obstruct' ? '' : 'none';
  if(_data) _redrawPolar();

  const cvs = document.getElementById('polar-canvas');
  if(mode === 'obstruct'){
    cvs.style.cursor = 'crosshair';
    cvs.onclick = onPolarClick;
  } else {
    cvs.style.cursor = '';
    cvs.onclick = null;
  }
}

function _redrawPolar(){
  if(_polarMode === 'density')
    renderPolarDensity(_data.sky_density, _data.mask_deg);
  else
    renderPolarObstruct(_data.sky_density, _data.mask_deg);
}

function renderPolarDensity(skyDensity, maskDeg){
  const {ctx, cx, cy, maxR} = _polarSetup();
  _drawPolarGrid(ctx, cx, cy, maxR, maskDeg);
  if(skyDensity) skyDensity.forEach(([azC,elC,pct])=>
    _drawPolarCell(ctx,cx,cy,maxR,maskDeg,azC,elC,10,5,pct/100,'168,85,247'));
  _polarZenith(ctx,cx,cy);
}

function renderPolarObstruct(skyDensity, maskDeg){
  const {ctx, cx, cy, maxR} = _polarSetup();
  // 底層密度（半透明）
  if(skyDensity) skyDensity.forEach(([azC,elC,pct])=>
    _drawPolarCell(ctx,cx,cy,maxR,maskDeg,azC,elC,10,5,pct/100*0.3,'168,85,247'));
  // 網格
  const azSteps=Array.from({length:36},(_,i)=>i*10+5);
  const el_min=maskDeg;
  const elSteps=[];
  for(let e=el_min+2.5; e<90; e+=5) elSteps.push(e);
  azSteps.forEach(azC=>elSteps.forEach(elC=>{
    const key=`${azC},${elC}`;
    const blocked=_blocked.has(key);
    _drawPolarCellOutline(ctx,cx,cy,maxR,maskDeg,azC,elC,10,5,blocked?'rgba(244,67,54,.55)':'rgba(255,255,255,.04)');
    if(blocked)
      _drawPolarCell(ctx,cx,cy,maxR,maskDeg,azC,elC,10,5,0.7,'244,67,54');
  }));
  _drawPolarGrid(ctx,cx,cy,maxR,maskDeg);
  _polarZenith(ctx,cx,cy);
}

function onPolarClick(e){
  if(_polarMode !== 'obstruct' || !_data) return;
  const cvs = document.getElementById('polar-canvas');
  const rect = cvs.getBoundingClientRect();
  const dpr  = window.devicePixelRatio || 1;
  const mx   = (e.clientX - rect.left) / rect.width  * (cvs.width  / dpr);
  const my   = (e.clientY - rect.top)  / rect.height * (cvs.height / dpr);
  const SIZE = 240, cx=SIZE/2, cy=SIZE/2, maxR=SIZE/2-10;
  const dx=mx-cx, dy=my-cy;
  const r=Math.sqrt(dx*dx+dy*dy);
  if(r > maxR || r < 1) return;
  const maskDeg = _data.mask_deg;
  const el = 90 - (r/maxR)*(90-maskDeg);
  if(el < maskDeg) return;
  const az = ((Math.atan2(dx,-dy)*180/Math.PI)+360)%360;
  // Snap to cell center
  const azC = Math.floor(az/10)*10+5;
  const elC = Math.floor((el-maskDeg)/5)*5+maskDeg+2.5;
  const key = `${azC},${elC}`;
  if(_blocked.has(key)) _blocked.delete(key); else _blocked.add(key);
  updateBlockCount();
  renderPolarObstruct(_data.sky_density, maskDeg);
}

function clearObstruction(){
  _blocked.clear();
  _obstData = null;
  updateBlockCount();
  document.getElementById('obst-result').style.display = 'none';
  if(_data) renderPolarObstruct(_data.sky_density, _data.mask_deg);
  if(_data) renderLineChart(_data.timeline, _data.stats);
}

function clearObstructionResult(){
  _obstData = null;
  document.getElementById('obst-result').style.display = 'none';
  if(_data) renderLineChart(_data.timeline, _data.stats);
}

function applyObstruction(){
  if(!_data || _blocked.size === 0){
    alert(t('alert_no_cells')); return;
  }
  const {lat, lon, mask, generation, dropout_pct} = getParams();
  const blocked_cells = [..._blocked].map(k=>{ const [a,e]=k.split(','); return [parseFloat(a),parseFloat(e)]; });
  const btn = document.getElementById('apply-obst-btn');
  _obstBtnBusy = true;
  btn.disabled = true; btn.textContent = t('btn_computing');

  fetch('/api/starlink/obstruction',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,mask,hours:24,step:15,blocked_cells,generation,dropout_pct}),
  })
  .then(r=>r.json())
  .then(data=>{
    _obstBtnBusy = false;
    btn.disabled=false; btn.textContent = t('btn_apply_obst');
    if(data.error){ alert(tpl('alert_obst_fail', {error: data.error})); return; }
    _obstData = data;
    renderObstructionResult(data);
    renderLineChart(_data.timeline, _data.stats, data.timeline);
  })
  .catch(err=>{ _obstBtnBusy = false; btn.disabled=false; btn.textContent = t('btn_apply_obst'); console.error(err); });
}

function renderObstructionResult(data){
  const box = document.getElementById('obst-result');
  box.style.display = '';
  const s = data.stats, o = data.original_stats;
  const delta = s.delta_pct;
  const dColor = delta < 0 ? '#F44336' : '#2ea043';
  document.getElementById('obst-compare').innerHTML = `
    <div class="obst-compare-grid">
      <div class="occ before">
        <div class="occ-title">${t('obst_before')}</div>
        <div class="occ-val">${o.availability_pct.toFixed(2)}%</div>
        <div class="occ-sub">${tpl('obst_sub', {mean: o.mean_visible, gaps: o.gap_count})}</div>
      </div>
      <div class="occ arrow">&#8594;</div>
      <div class="occ after">
        <div class="occ-title">${tpl('obst_after', {n: data.blocked_count})}</div>
        <div class="occ-val">${s.availability_pct.toFixed(2)}%</div>
        <div class="occ-sub">${tpl('obst_sub', {mean: s.mean_visible, gaps: s.gap_count})}</div>
      </div>
      <div class="occ delta" style="color:${dColor}">
        &#916; ${delta >= 0?'+':''}${delta.toFixed(2)}%
      </div>
    </div>`;

  // 遮蔽後空窗
  let gHtml = '';
  if(data.gaps && data.gaps.length > 0){
    gHtml = `<div style="margin-top:8px;font-size:11px;color:#e6edf3;font-weight:600">${t('obst_new_gaps_title')}</div>`;
    data.gaps.forEach(g=>{
      gHtml += `<div class="gap-item"><span class="gap-time">${fmtTime(g.start)} – ${fmtTime(g.end)}</span>
        <span class="gap-dur">&#9673; ${tpl('gap_dur', {n: g.duration_min})}</span></div>`;
    });
  } else {
    gHtml = `<div class="gap-ok" style="margin-top:6px">&#10003; ${t('obst_still_ok')}</div>`;
  }
  document.getElementById('obst-gaps').innerHTML = gHtml;

  // 遮蔽後 RTT 比較圖（用 obst-canvas）
  const cvs = document.getElementById('obst-canvas');
  if(cvs && _data){
    const W=(cvs.parentElement.clientWidth-20)||680, H=120;
    _setupCanvas(cvs,W,H);
    _drawLineChart(cvs.getContext('2d'),W,H,_data.timeline,_data.stats,data.timeline);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 極座標輔助函數
// ═══════════════════════════════════════════════════════════════════════════════
function _polarSetup(){
  const cvs = document.getElementById('polar-canvas');
  const SIZE = 240;
  const dpr  = window.devicePixelRatio || 1;
  cvs.width  = SIZE*dpr; cvs.height = SIZE*dpr;
  cvs.style.width = SIZE+'px'; cvs.style.height = SIZE+'px';
  const ctx = cvs.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.fillStyle='#0d1117'; ctx.fillRect(0,0,SIZE,SIZE);
  return {ctx, cx:SIZE/2, cy:SIZE/2, maxR:SIZE/2-10};
}

function _drawPolarGrid(ctx, cx, cy, maxR, maskDeg){
  const DIRS=['N','NE','E','SE','S','SW','W','NW'];
  ctx.strokeStyle='#21262d'; ctx.lineWidth=1;
  [30,45,60,75,90].forEach(el=>{
    if(el<maskDeg) return;
    const r=_el2r(el,maskDeg,maxR);
    ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.stroke();
    ctx.fillStyle='#6e7681'; ctx.font='8px monospace'; ctx.textAlign='center';
    ctx.fillText(el+'°',cx,cy-r+9);
  });
  DIRS.forEach((d,i)=>{
    const a=(i*45-90)*Math.PI/180;
    const rInner=_el2r(maskDeg,maskDeg,maxR);
    _line(ctx,cx+rInner*Math.cos(a),cy+rInner*Math.sin(a),cx+maxR*Math.cos(a),cy+maxR*Math.sin(a));
    const lr=maxR+14;
    ctx.fillStyle=d==='N'?'#e6edf3':'#8b949e'; ctx.font='9px sans-serif'; ctx.textAlign='center';
    ctx.fillText(d,cx+lr*Math.cos(a),cy+lr*Math.sin(a)+3);
  });
  ctx.strokeStyle='#F44336'; ctx.lineWidth=1.5; ctx.setLineDash([3,3]);
  ctx.beginPath(); ctx.arc(cx,cy,maxR,0,Math.PI*2); ctx.stroke();
  ctx.setLineDash([]);
}

function _polarZenith(ctx,cx,cy){
  ctx.fillStyle='#A855F7'; ctx.beginPath(); ctx.arc(cx,cy,3,0,Math.PI*2); ctx.fill();
}

function _el2r(el, maskDeg, maxR){ return Math.max(0,(90-el)/(90-maskDeg)*maxR); }

function _drawPolarCell(ctx,cx,cy,maxR,maskDeg,azC,elC,azStep,elStep,alpha,rgb){
  if(alpha<=0) return;
  const rInner=_el2r(Math.min(elC+elStep/2,90),maskDeg,maxR);
  const rOuter=_el2r(Math.max(elC-elStep/2,maskDeg),maskDeg,maxR);
  if(rOuter<=0) return;
  const a1=(azC-azStep/2-90)*Math.PI/180, a2=(azC+azStep/2-90)*Math.PI/180;
  ctx.fillStyle=`rgba(${rgb},${Math.min(alpha*0.9+0.05,0.92).toFixed(3)})`;
  ctx.beginPath();
  if(rInner<1){ ctx.moveTo(cx,cy); ctx.arc(cx,cy,rOuter,a1,a2,false); ctx.closePath(); }
  else { ctx.arc(cx,cy,rOuter,a1,a2,false); ctx.arc(cx,cy,rInner,a2,a1,true); ctx.closePath(); }
  ctx.fill();
}

function _drawPolarCellOutline(ctx,cx,cy,maxR,maskDeg,azC,elC,azStep,elStep,strokeOrFill){
  const rInner=_el2r(Math.min(elC+elStep/2,90),maskDeg,maxR);
  const rOuter=_el2r(Math.max(elC-elStep/2,maskDeg),maskDeg,maxR);
  if(rOuter<=0) return;
  const a1=(azC-azStep/2-90)*Math.PI/180, a2=(azC+azStep/2-90)*Math.PI/180;
  ctx.fillStyle=strokeOrFill;
  ctx.beginPath();
  if(rInner<1){ ctx.moveTo(cx,cy); ctx.arc(cx,cy,rOuter,a1,a2,false); ctx.closePath(); }
  else { ctx.arc(cx,cy,rOuter,a1,a2,false); ctx.arc(cx,cy,rInner,a2,a1,true); ctx.closePath(); }
  ctx.fill();
}

// ── 通用工具 ──────────────────────────────────────────────────────────────────
function _setupCanvas(cvs, w, h){
  const dpr = window.devicePixelRatio || 1;
  cvs.width=w*dpr; cvs.height=h*dpr;
  cvs.style.width=w+'px'; cvs.style.height=h+'px';
  cvs.getContext('2d').scale(dpr,dpr);
}
function _line(ctx,x1,y1,x2,y2){ ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); }

// ── 初始化 ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded',()=>{
  _tick(); setInterval(_tick,1000);
  setLang(LANG);
  // 分頁：直接開啟其他分頁時，延後到切回「台灣服務分析」才計算（starlink_tabs.js）
  if (!window.SL_TAB || window.SL_TAB === 'analysis') triggerCompute();
  else window._slPendingCompute = true;
});
