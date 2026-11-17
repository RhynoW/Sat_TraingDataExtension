'use strict';
/* 軌道要素歷史頁：
   - Spiral Polar ×3（inclination / raan / argp）：角度=要素值、半徑=時間螺旋、顏色=時間
     （仿 maneuver_STEM 之 prepare_spiral_polar_data：r = a + b·days）
   - SMA 圓形時間圖：0°=起始（12 點鐘位置）順時針至 360°=結束，
     r =（當日 SMA − 全期最小值）/（全期最大 − 最小）正規化
   - 時間播放：▶ 撥放時四張圖同步高亮「當日」資料點（未來點淡出、當日白圈＋指引線） */

// ── 三語字典（中／英／日）──────────────────────────────────────────────────
const I18N = {
  zh: {
    doc_title: '軌道要素歷史 — Spiral Polar',
    page_title: '軌道要素歷史',
    subtitle: 'Spiral Polar（傾角／升交點赤經／近地點幅角）＋ SMA 圓形圖',
    nav_home: '返回主頁',
    q_placeholder: '衛星名稱或 NORAD ID（至少 2 字元）',
    lbl_start: '起', lbl_end: '迄', btn_load: '載入',
    status_default: '請先搜尋並選取衛星（預設日期範圍：最近 1 年）',
    status_select_first: '請先搜尋並選取衛星',
    status_loading: '載入中…',
    status_load_fail: '載入失敗：{error}',
    status_loaded: '<b>{name}</b>（NORAD {norad}）　{start} ~ {end}　逐日資料 <b>{n}</b> 天',
    status_compare: '雙星比較　{start} ~ {end}', compare_time: '同一顆衛星：顏色淡→深＝時間早→晚',
    compare_days: '{n} 天', stats_th_sat: '衛星', status_partial: '部分衛星載入失敗：{error}',
    tip_play: '播放/暫停',
    spd_5: '5 天/秒', spd_10: '10 天/秒', spd_20: '20 天/秒', spd_40: '40 天/秒',
    card_sma_title: '半長軸變化（圓形時間圖）',
    card_sma_hint: '0°=起始時間、順時針演進至 360°=結束；半徑 r =（當日 SMA − 全期最小值）正規化',
    card_inc_title: '傾角 inclination（Spiral Polar）',
    card_inc_hint: '角度=傾角值、半徑=時間螺旋（內→外）、顏色=時間',
    card_raan_title: '升交點赤經 RAAN（Spiral Polar）',
    card_raan_hint: '角度=RAAN 值、半徑=時間螺旋（內→外）、顏色=時間',
    card_argp_title: '近地點幅角 ARGP（Spiral Polar）',
    card_argp_hint: '角度=ARGP 值、半徑=時間螺旋（內→外）、顏色=時間',
    info_norad: 'NORAD', info_intl_code: '國際編號', info_country: '國家',
    info_purpose: '用途', info_constellation: '星座', info_operator: '操作單位',
    info_launch_date: '發射日期', info_era: '年代',
    info_alt: '最新高度', info_inc: '最新傾角', info_period: '軌道週期',
    unit_min: '分', label_inc_short: '傾角',
    stats_th_element: '要素', stats_th_min: '最小', stats_th_max: '最大',
    stats_th_range: '變化範圍', stats_th_mean: '平均', stats_th_std: '標準差',
    stats_row_sma: '半長軸 SMA (km)', stats_row_inc: '傾角 inclination (°)',
    stats_row_raan: '升交點赤經 RAAN (°)', stats_row_argp: '近地點幅角 ARGP (°)',
  },
  en: {
    doc_title: 'Orbital Element History — Spiral Polar',
    page_title: 'Orbital Element History',
    subtitle: 'Spiral Polar (Inclination / RAAN / Argument of Perigee) + SMA Circular Chart',
    nav_home: 'Home',
    q_placeholder: 'Satellite name or NORAD ID (2+ characters)',
    lbl_start: 'From', lbl_end: 'To', btn_load: 'Load',
    status_default: 'Please search and select a satellite first (default range: last 1 year)',
    status_select_first: 'Please search and select a satellite first',
    status_loading: 'Loading…',
    status_load_fail: 'Load failed: {error}',
    status_loaded: '<b>{name}</b> (NORAD {norad})   {start} ~ {end}   <b>{n}</b> days of daily data',
    status_compare: 'Two-satellite comparison   {start} ~ {end}', compare_time: 'Per satellite: light → dark = earlier → later',
    compare_days: '{n} days', stats_th_sat: 'Satellite', status_partial: 'Some satellites failed to load: {error}',
    tip_play: 'Play / Pause',
    spd_5: '5 days/s', spd_10: '10 days/s', spd_20: '20 days/s', spd_40: '40 days/s',
    card_sma_title: 'Semi-Major Axis Change (Circular Time Chart)',
    card_sma_hint: '0° = start time, progressing clockwise to 360° = end; radius r = normalized (daily SMA − period minimum)',
    card_inc_title: 'Inclination (Spiral Polar)',
    card_inc_hint: 'Angle = inclination value, radius = time spiral (inner→outer), color = time',
    card_raan_title: 'RAAN (Spiral Polar)',
    card_raan_hint: 'Angle = RAAN value, radius = time spiral (inner→outer), color = time',
    card_argp_title: 'Argument of Perigee ARGP (Spiral Polar)',
    card_argp_hint: 'Angle = ARGP value, radius = time spiral (inner→outer), color = time',
    info_norad: 'NORAD', info_intl_code: 'International Designator', info_country: 'Country',
    info_purpose: 'Purpose', info_constellation: 'Constellation', info_operator: 'Operator',
    info_launch_date: 'Launch Date', info_era: 'Era',
    info_alt: 'Latest Altitude', info_inc: 'Latest Inclination', info_period: 'Orbital Period',
    unit_min: 'min', label_inc_short: 'Inclination',
    stats_th_element: 'Element', stats_th_min: 'Min', stats_th_max: 'Max',
    stats_th_range: 'Range', stats_th_mean: 'Mean', stats_th_std: 'Std Dev',
    stats_row_sma: 'Semi-Major Axis SMA (km)', stats_row_inc: 'Inclination (°)',
    stats_row_raan: 'RAAN (°)', stats_row_argp: 'Argument of Perigee ARGP (°)',
  },
  ja: {
    doc_title: '軌道要素履歴 — Spiral Polar',
    page_title: '軌道要素履歴',
    subtitle: 'Spiral Polar（軌道傾斜角／昇交点赤経／近地点引数）＋ SMA 円形図',
    nav_home: 'ホームに戻る',
    q_placeholder: '衛星名または NORAD ID（2文字以上）',
    lbl_start: '開始', lbl_end: '終了', btn_load: '読み込み',
    status_default: 'まず衛星を検索して選択してください（デフォルト期間：直近1年）',
    status_select_first: 'まず衛星を検索して選択してください',
    status_loading: '読み込み中…',
    status_load_fail: '読み込みに失敗しました：{error}',
    status_loaded: '<b>{name}</b>（NORAD {norad}）　{start} ～ {end}　日次データ <b>{n}</b> 日分',
    status_compare: '2 機比較　{start} ～ {end}', compare_time: '各衛星：色の淡→濃＝時間の早→遅',
    compare_days: '{n} 日分', stats_th_sat: '衛星', status_partial: '一部の衛星の読み込みに失敗しました：{error}',
    tip_play: '再生 / 一時停止',
    spd_5: '5日/秒', spd_10: '10日/秒', spd_20: '20日/秒', spd_40: '40日/秒',
    card_sma_title: '半長軸変化（円形タイムチャート）',
    card_sma_hint: '0°＝開始時刻、時計回りに進み 360°＝終了；半径 r ＝（当日の SMA － 全期間の最小値）で正規化',
    card_inc_title: '軌道傾斜角 inclination（Spiral Polar）',
    card_inc_hint: '角度＝傾斜角の値、半径＝時間スパイラル（内→外）、色＝時間',
    card_raan_title: '昇交点赤経 RAAN（Spiral Polar）',
    card_raan_hint: '角度＝RAAN 値、半径＝時間スパイラル（内→外）、色＝時間',
    card_argp_title: '近地点引数 ARGP（Spiral Polar）',
    card_argp_hint: '角度＝ARGP 値、半径＝時間スパイラル（内→外）、色＝時間',
    info_norad: 'NORAD', info_intl_code: '国際符号', info_country: '国',
    info_purpose: '用途', info_constellation: 'コンステレーション', info_operator: '運用機関',
    info_launch_date: '打上げ日', info_era: '年代',
    info_alt: '最新高度', info_inc: '最新傾斜角', info_period: '軌道周期',
    unit_min: '分', label_inc_short: '傾斜角',
    stats_th_element: '要素', stats_th_min: '最小', stats_th_max: '最大',
    stats_th_range: '変化範囲', stats_th_mean: '平均', stats_th_std: '標準偏差',
    stats_row_sma: '半長軸 SMA (km)', stats_row_inc: '軌道傾斜角 inclination (°)',
    stats_row_raan: '昇交点赤経 RAAN (°)', stats_row_argp: '近地点引数 ARGP (°)',
  },
};
const ORBIT_LOCALE_MAP = {zh: 'zh-TW', en: 'en-US', ja: 'ja-JP'};
let LANG = localStorage.getItem('orbit_lang') || 'zh';
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

/* ── 已載入時的狀態列文字（依目前語言重新組字，資料本身不翻譯）── */
function renderLoadedStatus(){
  let s;
  if(SATS.length === 1){
    const d = SATS[0].data;
    s = tpl('status_loaded', {name: d.name, norad: d.norad, start: d.start, end: d.end, n: d.n_days});
    if(d.note) s += '　<span style="color:#d29922">' + d.note + '</span>';
  }else{
    s = tpl('status_compare', {start: UDATES[0], end: UDATES[UDATES.length - 1]});
    SATS.forEach(o => {
      s += '　<span class="lg"><i style="background:' + o.color + '"></i><b>' + o.data.name +
           '</b>（NORAD ' + o.norad + '，' + tpl('compare_days', {n: o.data.n_days}) + '）</span>';
    });
    s += '　<span style="color:#8b949e">' + t('compare_time') + '</span>';
    SATS.forEach(o => { if(o.data.note) s += '　<span style="color:#d29922">' + satTag(o) + o.data.note + '</span>'; });
  }
  if(LOAD_ERR) s += '　<span style="color:#f85149">' + tpl('status_partial', {error: LOAD_ERR}) + '</span>';
  $('status').innerHTML = s;
}

function setLang(lang){
  if(!I18N[lang]) return;
  LANG = lang;
  localStorage.setItem('orbit_lang', lang);
  document.documentElement.lang = ORBIT_LOCALE_MAP[lang] || 'zh-TW';
  document.title = t('doc_title');

  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.getAttribute('data-i18n-title'));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
  });
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === lang);
  });

  // 若已載入資料，重繪所有用到語系字串的動態內容
  if(SATS.length){
    renderLoadedStatus();
    renderSatInfo();
    renderStats();
    redrawAll(HI);
  }
}

let SELS = [];           // 已選衛星 [{norad, name}]，最多 2 顆（雙星比較）
let SATS = [];           // 已載入 [{norad, data, color, uidx}]；data = /api/orbit/history 回應
let UDATES = [];         // 各星日期聯集（排序），播放軸與時間比例共用
let LOAD_ERR = '';       // 雙星時部分失敗的訊息
let HI = null;           // 目前高亮之聯集日索引（null=無）
let TIMER = null;        // 播放計時器
let AUTOPLAY = false;    // ?autoplay=1：載入後自動播放
const PTS = {};          // canvasId -> [{x,y,label}] 供 hover

const SPIRAL_A = 0.18, SPIRAL_B_FRAC = 0.82;   // r_norm = A + B·(day/maxDay)
const DIM = '#2d333b';                          // 播放時未來點的淡出色
const MAX_SATS = 2;
const CMP_RGB = [[242, 167, 59], [53, 198, 244]];   // 與 /rpo primary（橘）/ secondary（青）一致

function $(id){ return document.getElementById(id); }

/* ── 顏色：單星＝時間 → HSV 色環；雙星＝各星固定色、透明度表時間（淡→深）── */
function timeColor(t){ return 'hsl(' + Math.round(t * 330) + ',85%,55%)'; }
function seriesColor(k, t){
  if(SATS.length === 1) return timeColor(t);
  const c = CMP_RGB[k];
  return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (0.22 + 0.78 * t).toFixed(3) + ')';
}
function satTag(o){ return SATS.length > 1 ? '[' + o.norad + '] ' : ''; }
function uT(u){ return UDATES.length > 1 ? u / (UDATES.length - 1) : 0; }
/* 某星在聯集索引 hi 時「當日或之前最後一筆」之索引（-1=尚無資料）*/
function lastAt(o, hi){
  let r = -1;
  for(let i = 0; i < o.uidx.length && o.uidx[i] <= hi; i++) r = i;
  return r;
}

/* ── canvas 準備（方形、HiDPI）── */
function setupCanvas(cv){
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340;
  cv.width = w * dpr; cv.height = w * dpr;
  cv.style.height = w + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, w);
  return {ctx, w, cx: w / 2, cy: w / 2, R: w / 2 - 34};
}

function polarGrid(g, spokeLabelFn){
  const {ctx, cx, cy, R} = g;
  ctx.strokeStyle = '#21262d'; ctx.fillStyle = '#8b949e';
  ctx.font = '10.5px Segoe UI'; ctx.lineWidth = 1;
  [1/3, 2/3, 1].forEach(f => {
    ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, 2 * Math.PI); ctx.stroke();
  });
  for(let a = 0; a < 360; a += 45){
    const rad = a * Math.PI / 180;
    ctx.beginPath(); ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(rad), cy - R * Math.sin(rad)); ctx.stroke();
    if(a % 90 === 0 && spokeLabelFn){
      ctx.textAlign = 'center';
      ctx.fillText(spokeLabelFn(a),
        cx + (R + 16) * Math.cos(rad), cy - (R + 16) * Math.sin(rad) + 4);
    }
  }
}

/* ── 當日高亮：白圈＋圓心指引線 ── */
function highlightPoint(g, p, color){
  const {ctx, cx, cy} = g;
  ctx.save();
  ctx.strokeStyle = 'rgba(139,148,158,.55)';
  ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p.x, p.y); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, 2 * Math.PI); ctx.fill();
  ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(p.x, p.y, 6.5, 0, 2 * Math.PI); ctx.stroke();
  ctx.restore();
}

/* 各星當日高亮＋說明列（雙星時兩筆以「｜」並列）*/
function highlightAll(g, capId, perSat, hi){
  if(hi == null) return;
  const caps = [];
  SATS.forEach((o, k) => {
    const j = lastAt(o, hi);
    if(j < 0) return;
    highlightPoint(g, perSat[k][j], SATS.length === 1 ? timeColor(uT(hi)) : o.color);
    caps.push(perSat[k][j].label);
  });
  $(capId).textContent = caps.join('　｜　');
}

/* ── Spiral Polar：角度=要素值（數學慣例 0°=右、逆時針）、半徑=時間 ── */
function drawSpiral(cvId, capId, key, hi){
  const cv = $(cvId), g = setupCanvas(cv);
  polarGrid(g, a => a + '°');
  const all = [], perSat = [];
  SATS.forEach((o, k) => {
    const values = o.data[key], dates = o.data.dates, pts = [];
    for(let i = 0; i < values.length; i++){
      const t = uT(o.uidx[i]);
      const rN = SPIRAL_A + SPIRAL_B_FRAC * t;
      const rad = (values[i] % 360) * Math.PI / 180;
      const x = g.cx + g.R * rN * Math.cos(rad);
      const y = g.cy - g.R * rN * Math.sin(rad);
      g.ctx.fillStyle = (hi != null && o.uidx[i] > hi) ? DIM : seriesColor(k, t);
      g.ctx.beginPath(); g.ctx.arc(x, y, 2.6, 0, 2 * Math.PI); g.ctx.fill();
      pts.push({x, y, label: satTag(o) + dates[i] + ' · ' + values[i].toFixed(4) + '°'});
    }
    perSat.push(pts); all.push(...pts);
  });
  highlightAll(g, capId, perSat, hi);
  PTS[cvId] = all;
  attachHover(cv, cvId, capId);
}

/* ── SMA 圓形時間圖：0°=起始（上方）順時針、r=正規化 SMA 變化（雙星共用同一尺度）── */
function drawSmaCircle(cvId, capId, hi){
  const cv = $(cvId), g = setupCanvas(cv);
  const {ctx, cx, cy, R} = g;
  const allSma = [].concat(...SATS.map(o => o.data.sma_km));
  const mn = Math.min(...allSma), mx = Math.max(...allSma), rg = mx - mn;

  ctx.strokeStyle = '#21262d'; ctx.fillStyle = '#8b949e';
  ctx.font = '10.5px Segoe UI'; ctx.lineWidth = 1;
  [1/3, 2/3, 1].forEach(f => {
    ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, 2 * Math.PI); ctx.stroke();
    ctx.textAlign = 'left';
    ctx.fillText((mn + rg * f).toFixed(1), cx + R * f + 3, cy - 3);
  });
  ctx.fillText(mn.toFixed(1) + ' km (min)', cx + 4, cy + 12);

  // 時間刻度：0/90/180/270° → 起始與四分位日期
  const n = UDATES.length;
  [0, 0.25, 0.5, 0.75].forEach(f => {
    const rad = 2 * Math.PI * f;                       // 0=上方、順時針
    const x2 = cx + R * Math.sin(rad), y2 = cy - R * Math.cos(rad);
    ctx.strokeStyle = '#30363d';
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x2, y2); ctx.stroke();
    const di = Math.min(n - 1, Math.round(f * (n - 1)));
    const lb = f === 0 ? UDATES[di] : UDATES[di].slice(5);   // 起始給全日期，餘 MM-DD
    ctx.fillStyle = '#8b949e';
    ctx.textAlign = f === 0.25 ? 'left' : (f === 0.75 ? 'right' : 'center');
    ctx.fillText(lb,
      cx + (R + 8) * Math.sin(rad), cy - (R + 14) * Math.cos(rad) + 4);
  });

  const all = [], perSat = [];
  SATS.forEach((o, k) => {
    const sma = o.data.sma_km, dates = o.data.dates, pts = [];
    ctx.lineWidth = 1.4;
    let prev = null;
    for(let i = 0; i < sma.length; i++){
      const t = uT(o.uidx[i]);
      const rN = rg > 0 ? (sma[i] - mn) / rg : 0.5;
      const rad = 2 * Math.PI * t;
      const x = cx + R * rN * Math.sin(rad);
      const y = cy - R * rN * Math.cos(rad);
      if(prev){
        ctx.strokeStyle = (hi != null && o.uidx[i] > hi) ? DIM : seriesColor(k, t);
        ctx.beginPath(); ctx.moveTo(prev.x, prev.y); ctx.lineTo(x, y); ctx.stroke();
      }
      prev = {x, y};
      pts.push({x, y, label: satTag(o) + dates[i] + ' · SMA ' + sma[i].toFixed(3) +
                ' km（min+' + (sma[i] - mn).toFixed(3) + '）'});
    }
    for(let i = 0; i < sma.length; i++){               // 點在線之上
      ctx.fillStyle = (hi != null && o.uidx[i] > hi) ? DIM : seriesColor(k, uT(o.uidx[i]));
      ctx.beginPath(); ctx.arc(pts[i].x, pts[i].y, 2.4, 0, 2 * Math.PI); ctx.fill();
    }
    perSat.push(pts); all.push(...pts);
  });
  highlightAll(g, capId, perSat, hi);
  PTS[cvId] = all;
  attachHover(cv, cvId, capId);
}

function attachHover(cv, cvId, capId){
  if(cv._hoverBound) return;
  cv._hoverBound = true;
  cv.addEventListener('mousemove', e => {
    const rc = cv.getBoundingClientRect();
    const mx = e.clientX - rc.left, my = e.clientY - rc.top;
    let best = null, bd = 100;
    for(const p of (PTS[cvId] || [])){
      const d = (p.x - mx) ** 2 + (p.y - my) ** 2;
      if(d < bd){ bd = d; best = p; }
    }
    if(best) $(capId).textContent = best.label;
  });
}

/* ── 全部重繪（hi=高亮日索引或 null）── */
function redrawAll(hi){
  if(!SATS.length) return;
  HI = hi;
  drawSmaCircle('cv-sma', 'cap-sma', hi);
  drawSpiral('cv-inc', 'cap-inc', 'inclination_deg', hi);
  drawSpiral('cv-raan', 'cap-raan', 'raan_deg', hi);
  drawSpiral('cv-argp', 'cap-argp', 'argp_deg', hi);
  updateCur(hi);
}

function updateCur(hi){
  if(hi == null || !SATS.length){ $('cur').textContent = ''; return; }
  const parts = [];
  SATS.forEach(o => {
    const d = o.data, j = lastAt(o, hi);
    if(j < 0) return;
    parts.push(satTag(o) + d.dates[j] +
      ' · SMA ' + d.sma_km[j].toFixed(2) + ' km' +
      ' · ' + t('label_inc_short') + ' ' + d.inclination_deg[j].toFixed(3) + '°' +
      ' · RAAN ' + d.raan_deg[j].toFixed(2) + '°' +
      ' · ARGP ' + d.argp_deg[j].toFixed(2) + '°');
  });
  $('cur').textContent = parts.length ? parts.join('　｜　') : UDATES[hi];
}

/* ── 播放控制 ── */
function setPlaying(on){
  if(TIMER){ clearInterval(TIMER); TIMER = null; }
  $('play').innerHTML = on ? '&#10074;&#10074;' : '&#9654;';   // ⏸ / ▶
  if(!on || !SATS.length) return;
  const tl = $('tl');
  if(+tl.value >= +tl.max) tl.value = 0;                       // 播畢重播
  const spd = +$('spd').value;                                  // 天/秒
  TIMER = setInterval(() => {
    const next = +tl.value + 1;
    if(next > +tl.max){ setPlaying(false); return; }
    tl.value = next;
    redrawAll(next);
  }, Math.max(25, Math.round(1000 / spd)));
}

function bindPlayer(){
  $('play').addEventListener('click', () => setPlaying(TIMER === null));
  $('tl').addEventListener('input', () => redrawAll(+$('tl').value));
  $('spd').addEventListener('change', () => { if(TIMER) setPlaying(true); });
}

/* ── 衛星基本資料卡（雙星時並排兩張，標題前加色塊）── */
function satInfoCard(o){
  const d = o.data;
  const inf = d.info || {};
  const last = d.n_days - 1;
  const aKm = d.sma_km[last];
  const period = 2 * Math.PI * Math.sqrt(Math.pow(aKm, 3) / 398600.4418) / 60;
  const rows = [
    [t('info_norad'), d.norad],
    [t('info_intl_code'), inf.intl_code],
    [t('info_country'), inf.country],
    [t('info_purpose'), inf.purpose],
    [t('info_constellation'), inf.constellation],
    [t('info_operator'), inf.operator],
    [t('info_launch_date'), inf.launch_date],
    [t('info_era'), inf.era],
    [t('info_alt'), (aKm - 6378.137).toFixed(0) + ' km'],
    [t('info_inc'), d.inclination_deg[last].toFixed(2) + '°'],
    [t('info_period'), period.toFixed(1) + ' ' + t('unit_min')],
  ].filter(r => r[1] !== '' && r[1] != null);
  const alt = (inf.name_zh && inf.name_en && inf.name_zh !== inf.name_en)
    ? '<span>' + inf.name_en + '</span>' : '';
  const sw = SATS.length > 1 ? '<i class="sw" style="background:' + o.color + '"></i>' : '';
  return '<div class="ttl">' + sw + (inf.name || d.name) + alt + '</div>' +
    '<div class="grid">' +
    rows.map(r => '<div><b>' + r[0] + '</b>' + r[1] + '</div>').join('') +
    '</div>' +
    (inf.notes ? '<div class="notes">' + inf.notes + '</div>' : '');
}

function renderSatInfo(){
  const box = $('satinfo');
  box.classList.toggle('two', SATS.length > 1);
  box.innerHTML = SATS.length > 1
    ? SATS.map(o => '<div class="si">' + satInfoCard(o) + '</div>').join('')
    : satInfoCard(SATS[0]);
  box.style.display = 'block';
}

/* ── 統計表（雙星時每要素兩列，首欄標衛星）── */
function renderStats(){
  const two = SATS.length > 1;
  const keys = [['stats_row_sma', 'sma_km'], ['stats_row_inc', 'inclination_deg'],
                ['stats_row_raan', 'raan_deg'], ['stats_row_argp', 'argp_deg']];
  let h = '<table><tr><th>' + t('stats_th_element') + '</th>' +
          (two ? '<th style="text-align:left">' + t('stats_th_sat') + '</th>' : '') +
          '<th>' + t('stats_th_min') +
          '</th><th>' + t('stats_th_max') + '</th><th>' + t('stats_th_range') + '</th>' +
          '<th>' + t('stats_th_mean') + '</th><th>' + t('stats_th_std') + '</th></tr>';
  keys.forEach(([lb, key]) => {
    SATS.forEach((o, k) => {
      const s = o.data.stats[key];
      h += '<tr><td>' + (k === 0 ? t(lb) : '') + '</td>' +
           (two ? '<td style="text-align:left"><i class="sw" style="background:' + o.color + '"></i>' + o.norad + '</td>' : '') +
           '<td>' + s.min + '</td><td>' + s.max +
           '</td><td>' + s.range + '</td><td>' + s.mean + '</td><td>' + s.std + '</td></tr>';
    });
  });
  h += '</table>';
  $('stats').innerHTML = h;
}

/* ── 載入（雙星時並行抓取；一顆失敗仍顯示另一顆）── */
async function fetchHistory(sel){
  const u = '/api/orbit/history?norad=' + sel.norad +
            '&start=' + $('d0').value + '&end=' + $('d1').value;
  const r = await fetch(u);
  const d = await r.json();
  if(!r.ok) throw new Error(d.error || ('NORAD ' + sel.norad + '：HTTP ' + r.status));
  return d;
}

async function load(){
  if(!SELS.length){ $('status').textContent = t('status_select_first'); return; }
  setPlaying(false);
  $('status').textContent = t('status_loading');
  try{
    const res = await Promise.allSettled(SELS.map(fetchHistory));
    const errs = res.filter(x => x.status === 'rejected').map(x => x.reason && x.reason.message || x.reason);
    const ok = [];
    res.forEach((x, k) => { if(x.status === 'fulfilled') ok.push({norad: SELS[k].norad, data: x.value}); });
    if(!ok.length){ $('status').textContent = errs.join('；'); return; }
    LOAD_ERR = ok.length < SELS.length ? errs.join('；') : '';
    const set = new Set();
    ok.forEach(o => o.data.dates.forEach(d => set.add(d)));
    UDATES = [...set].sort();
    const pos = {};
    UDATES.forEach((d, i) => { pos[d] = i; });
    SATS = ok.map((o, k) => ({
      norad: o.norad, data: o.data, uidx: o.data.dates.map(d => pos[d]),
      color: 'rgb(' + CMP_RGB[k].join(',') + ')',
    }));
    renderLoadedStatus();
    const tl = $('tl');
    tl.max = UDATES.length - 1; tl.value = 0;
    $('player').style.display = 'flex';
    renderSatInfo();
    redrawAll(null);
    renderStats();
    if(AUTOPLAY) setPlaying(true);
  }catch(e){ $('status').textContent = tpl('status_load_fail', {error: e}); }
}

/* 「A,B」或「A」形式的 NORAD 清單 → SELS（最多 2 顆）；格式不符回傳 false */
function setSelsFromList(txt){
  const v = (txt || '').replace(/\s+/g, '');
  if(!/^\d+(,\d+)*$/.test(v)) return false;
  const ids = [...new Set(v.split(',').map(Number))].slice(0, MAX_SATS);
  SELS = ids.map(n => ({norad: n, name: 'NORAD ' + n}));
  $('sel-info').textContent = ids.map(n => 'NORAD ' + n).join(' ＋ ');
  return true;
}

/* ── 搜尋 ── */
let _timer = null;
function bindSearch(){
  const q = $('q'), sug = $('sug');
  q.addEventListener('input', () => {
    clearTimeout(_timer);
    const v = q.value.trim();
    if(v.length < 2 || v.includes(',')){ sug.style.display = 'none'; return; }
    _timer = setTimeout(async () => {
      try{
        const r = await fetch('/api/search?q=' + encodeURIComponent(v));
        const d = await r.json();
        sug.innerHTML = '';
        (d.results || []).forEach(m => {
          const it = document.createElement('div');
          it.className = 'it';
          it.innerHTML = '<b>' + m.name + '</b><span>NORAD ' + m.norad_id +
                         ' · ' + (m.constellation || '—') + '</span>';
          it.onclick = () => {
            SELS = [{norad: m.norad_id, name: m.name}];
            q.value = m.name;
            $('sel-info').textContent = 'NORAD ' + m.norad_id;
            sug.style.display = 'none';
            load();
          };
          sug.appendChild(it);
        });
        sug.style.display = (d.results || []).length ? 'block' : 'none';
      }catch(e){ sug.style.display = 'none'; }
    }, 300);
  });
  document.addEventListener('click', e => {
    if(!sug.contains(e.target) && e.target !== q) sug.style.display = 'none';
  });
}

function init(){
  setLang(LANG);
  const today = new Date();
  const past = new Date(today.getTime() - 365 * 86400 * 1000);
  $('d1').value = today.toISOString().slice(0, 10);
  $('d0').value = past.toISOString().slice(0, 10);
  bindSearch();
  bindPlayer();
  $('go').addEventListener('click', () => {
    // 搜尋框直接輸入「58573,59884」→ 雙星比較
    if($('q').value.includes(',')) setSelsFromList($('q').value);
    load();
  });
  const qs = new URLSearchParams(location.search);
  if(qs.get('embed') === '1'){        // 故事頁內嵌模式：隱藏頁首/搜尋列
    $('hdr').style.display = 'none';
    $('ctrl').style.display = 'none';
  }
  if(qs.get('row') === '1'){          // 四張 Polar 圖排成一列
    document.getElementById('grid').style.gridTemplateColumns = 'repeat(4,1fr)';
  }
  AUTOPLAY = qs.get('autoplay') === '1';
  const D = /^\d{4}-\d{2}-\d{2}$/;
  if(D.test(qs.get('start') || '')) $('d0').value = qs.get('start');
  if(D.test(qs.get('end') || ''))   $('d1').value = qs.get('end');
  // ?norad=58573 單星；?norad=58573,59884 雙星比較
  if(setSelsFromList(qs.get('norad'))){
    if(SELS.length > 1) $('q').value = SELS.map(o => o.norad).join(',');
    load();
  }
  window.addEventListener('resize', () => redrawAll(HI));
}
init();
