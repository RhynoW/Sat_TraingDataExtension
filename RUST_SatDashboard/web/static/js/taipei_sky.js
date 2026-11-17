'use strict';

/* ═══════════════════════════════════════════════════════════════════════════
   台北上空衛星過頂：天球視角 + 地面軌跡（半徑 2000 km）＋日月行星／一等星＋動畫輸出
   相依：taipei.js（LANG/I18N）、vendor/astronomy（Astronomy）、sky_catalog.js（SKY_STARS）、
         taipei_gif.js（GifEncoder）。後端：/api/taipei_sky（方位角/仰角/星下點軌跡）。
   單一 canvas 同時繪製兩個面板；螢幕顯示與動畫輸出共用同一組繪圖函式。
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){

const OBS = {lat: 25.0330, lon: 121.5654, h: 10};
const R_EARTH = 6371.0;
const PRE_MS = 15 * 60e3;              // 時窗起點 = 現在 − 15 分（讓進行中的過頂有完整軌跡）
const UPCOMING_MS = 10 * 60e3;         // 預告即將升起之軌跡（分鐘）
const FONT = 'Tahoma,"Microsoft JhengHei","Noto Sans CJK TC","Hiragino Sans",sans-serif';
const PLANETS = [
  {body: 'Mercury', key: 'mercury', color: '#c9c2b8'},
  {body: 'Venus',   key: 'venus',   color: '#fff3c4'},
  {body: 'Mars',    key: 'mars',    color: '#ff7b59'},
  {body: 'Jupiter', key: 'jupiter', color: '#f5dcae'},
  {body: 'Saturn',  key: 'saturn',  color: '#e8d18f'},
];

/* ── 三語字典（天球視角專用；語言取自 taipei.js 的全域 LANG）──────────────── */
const SKY_I18N = {
  zh: {
    view_sky: '天球', view_map: '地圖',
    title_sky: '天球視角（台北上空）', title_ground: '地面軌跡（台北為中心，半徑 {r} km）',
    sec_show: '顯示', sec_cats: '衛星類別', sec_passes: '過頂清單', sec_export: '動畫輸出',
    layout: '版面', layout_both: '並排', layout_sky: '僅天球', layout_ground: '僅地面軌跡',
    o_stars: '一等星', o_starnames: '星名', o_planets: '行星', o_ecliptic: '黃道',
    o_arrows: '行進方向箭頭', o_names: '衛星名稱', o_all: '顯示時窗內全部軌跡',
    o_eastleft: '東在左（仰望天空）', range: '地面範圍',
    play: '播放', pause: '暫停', loop: '循環', now: '現在', reload: '重新計算',
    hours: '時窗', h_unit: '小時', start_at: '起點(CST)', speed: '速度',
    loading: '計算過頂軌跡中（首次約 10–30 秒）…', load_fail: '載入失敗：{msg}',
    no_passes: '此時窗內沒有符合條件的過頂',
    hud_sun: '太陽', hud_moon: '月', hud_alt: '高度', hud_illum: '照亮', hud_above: '空中衛星',
    tw_day: '白天', tw_civil: '民用曙暮光', tw_nautical: '航海曙暮光', tw_astro: '天文曙暮光', tw_night: '夜間',
    day_note: '白天／曙暮光時一等星肉眼不可見，僅標示位置',
    sun: '太陽', moon: '月球', mercury: '水星', venus: '金星', mars: '火星', jupiter: '木星', saturn: '土星',
    N: '北', E: '東', S: '南', W: '西', taipei: '台北',
    geo: '同步軌道', max_el: '最大仰角', dur: '持續', min: '分', sec: '秒', rise: '升起', peak: '最高', set: '落下',
    sel_hint: '點選圖上衛星或清單項目以查看細節', norad: 'NORAD',
    ex_fmt: '格式', ex_sim: '模擬區間', ex_out: '輸出長度', ex_fps: '幀率', ex_size: '高度',
    ex_go: '輸出動畫', ex_png: '截圖 PNG', ex_run: '輸出中 {i}/{n}…', ex_done: '完成：{name}（{kb} KB）',
    ex_fail: '輸出失敗：{msg}', ex_nomr: '此瀏覽器不支援影片錄製，請改用 GIF',
    ex_from: '自目前時刻起', ex_min: '{n} 分鐘', ex_sec: '{n} 秒',
    credit: '星表 d3-celestial（BSD-3）· 星曆 astronomy-engine（MIT）· TLE/SGP4',
    cat_all: '全部', mask: '仰角遮蔽',
    view_cycle: '切換視角', auto_cycle: '自動輪播', auto_sec: '{n} 秒', tz_label: '台北時間 UTC+8',
    layout_lunar: '衛星凌月', sec_lunar: '凌月事件時間表', lunar_hours: '凌月時窗',
    lunar_loading: '計算凌月事件中（掃描全部類別，約 20–60 秒）…', lunar_none: '此時窗內沒有凌月／擦邊事件',
    lunar_fail: '凌月計算失敗：{msg}', lk_transit: '凌月', lk_near: '擦邊', lunar_kind: '事件', lf_all: '全部', lf_transit: '僅凌月',
    ln_sep: '最小角距', ln_chord: '遮蔽月面', ln_omega: '相對角速度', ln_sat: '衛星仰角／方位', ln_moon: '月球仰角／方位',
    ln_range: '衛星距離', ln_ring: '擦邊範圍 ±{m}°', ln_pic: '月面示意（月相與朝向依實際位置；紋理為示意，未含天平動）',
    ln_note: 'TLE 沿軌誤差（低軌約 0.2–0.5°）與月面視半徑（約 0.26°）同量級，屬事件預報；凌月帶僅數公里寬，觀測前請以最新 TLE 重算。',
    ln_events: '凌月事件：{n}（凌月 {t}）', ln_tl: '事件時間軸（月球在地平線上為亮帶）', ln_replay: '重播選取事件',
    ln_none_sel: '尚無事件', ln_dt_before: '距事件 {t}', ln_dt_now: 'T{s} 秒', ln_transit_word: '凌月', ln_near_word: '擦邊',
    ph_new: '新月', ph_wax_cres: '眉月', ph_fq: '上弦月', ph_wax_gib: '盈凸月', ph_full: '滿月', ph_wan_gib: '虧凸月', ph_lq: '下弦月', ph_wan_cres: '殘月',
  },
  en: {
    view_sky: 'Sky', view_map: 'Map',
    title_sky: 'Sky view (above Taipei)', title_ground: 'Ground track (centered on Taipei, {r} km radius)',
    sec_show: 'Display', sec_cats: 'Satellite categories', sec_passes: 'Pass list', sec_export: 'Export animation',
    layout: 'Layout', layout_both: 'Side by side', layout_sky: 'Sky only', layout_ground: 'Ground only',
    o_stars: '1st-mag stars', o_starnames: 'Star names', o_planets: 'Planets', o_ecliptic: 'Ecliptic',
    o_arrows: 'Direction arrows', o_names: 'Satellite names', o_all: 'Show all tracks in window',
    o_eastleft: 'East on left (looking up)', range: 'Ground range',
    play: 'Play', pause: 'Pause', loop: 'Loop', now: 'Now', reload: 'Recompute',
    hours: 'Window', h_unit: 'h', start_at: 'Start (CST)', speed: 'Speed',
    loading: 'Computing pass tracks (10–30 s on first load)…', load_fail: 'Load failed: {msg}',
    no_passes: 'No qualifying passes in this window',
    hud_sun: 'Sun', hud_moon: 'Moon', hud_alt: 'alt', hud_illum: 'lit', hud_above: 'Satellites up',
    tw_day: 'Daytime', tw_civil: 'Civil twilight', tw_nautical: 'Nautical twilight', tw_astro: 'Astronomical twilight', tw_night: 'Night',
    day_note: 'Stars are not visible to the eye in daylight/twilight; positions shown for reference',
    sun: 'Sun', moon: 'Moon', mercury: 'Mercury', venus: 'Venus', mars: 'Mars', jupiter: 'Jupiter', saturn: 'Saturn',
    N: 'N', E: 'E', S: 'S', W: 'W', taipei: 'Taipei',
    geo: 'GEO', max_el: 'Max elev', dur: 'Duration', min: 'min', sec: 's', rise: 'Rise', peak: 'Peak', set: 'Set',
    sel_hint: 'Click a satellite on the chart or a list item for details', norad: 'NORAD',
    ex_fmt: 'Format', ex_sim: 'Simulated span', ex_out: 'Output length', ex_fps: 'Frame rate', ex_size: 'Height',
    ex_go: 'Export animation', ex_png: 'Snapshot PNG', ex_run: 'Rendering {i}/{n}…', ex_done: 'Done: {name} ({kb} KB)',
    ex_fail: 'Export failed: {msg}', ex_nomr: 'Video recording is not supported in this browser; use GIF',
    ex_from: 'from the current time', ex_min: '{n} min', ex_sec: '{n} s',
    credit: 'Stars: d3-celestial (BSD-3) · Ephemeris: astronomy-engine (MIT) · TLE/SGP4',
    cat_all: 'All', mask: 'Elevation mask',
    view_cycle: 'Cycle view', auto_cycle: 'Auto-rotate', auto_sec: '{n} s', tz_label: 'Taipei time UTC+8',
    layout_lunar: 'Satellite–Moon transit', sec_lunar: 'Lunar transit schedule', lunar_hours: 'Lunar window',
    lunar_loading: 'Scanning lunar transits (all categories, ~20–60 s)…', lunar_none: 'No transit / near-miss events in this window',
    lunar_fail: 'Lunar transit scan failed: {msg}', lk_transit: 'Transit', lk_near: 'Near', lunar_kind: 'Events', lf_all: 'All', lf_transit: 'Transits only',
    ln_sep: 'Min separation', ln_chord: 'Disc crossing', ln_omega: 'Relative rate', ln_sat: 'Sat elev / az', ln_moon: 'Moon elev / az',
    ln_range: 'Satellite range', ln_ring: 'Near-miss range ±{m}°', ln_pic: 'Moon picture (phase and orientation follow the real geometry; surface texture is schematic, no libration)',
    ln_note: 'TLE along-track error (~0.2–0.5° for LEO) is comparable to the Moon\'s 0.26° radius, so this is an event forecast; the transit path is only a few km wide — recompute with fresh TLEs before observing.',
    ln_events: 'Lunar events: {n} ({t} transits)', ln_tl: 'Event timeline (bright band: Moon above horizon)', ln_replay: 'Replay selected event',
    ln_none_sel: 'No event', ln_dt_before: 'Event in {t}', ln_dt_now: 'T{s} s', ln_transit_word: 'Transit', ln_near_word: 'Near miss',
    ph_new: 'New Moon', ph_wax_cres: 'Waxing crescent', ph_fq: 'First quarter', ph_wax_gib: 'Waxing gibbous', ph_full: 'Full Moon', ph_wan_gib: 'Waning gibbous', ph_lq: 'Last quarter', ph_wan_cres: 'Waning crescent',
  },
  ja: {
    view_sky: '天球', view_map: '地図',
    title_sky: '天球ビュー（台北上空）', title_ground: '地上軌跡（台北中心・半径 {r} km）',
    sec_show: '表示', sec_cats: '衛星カテゴリ', sec_passes: '通過リスト', sec_export: 'アニメーション出力',
    layout: 'レイアウト', layout_both: '並べて表示', layout_sky: '天球のみ', layout_ground: '地上軌跡のみ',
    o_stars: '1等星', o_starnames: '星名', o_planets: '惑星', o_ecliptic: '黄道',
    o_arrows: '進行方向の矢印', o_names: '衛星名', o_all: '時間窓内の全軌跡を表示',
    o_eastleft: '東を左（見上げ表示）', range: '地上の範囲',
    play: '再生', pause: '一時停止', loop: 'ループ', now: '現在', reload: '再計算',
    hours: '時間窓', h_unit: '時間', start_at: '開始(CST)', speed: '速度',
    loading: '通過軌跡を計算中（初回は10〜30秒）…', load_fail: '読み込み失敗：{msg}',
    no_passes: 'この時間窓に該当する通過はありません',
    hud_sun: '太陽', hud_moon: '月', hud_alt: '高度', hud_illum: '照明', hud_above: '空の衛星',
    tw_day: '昼間', tw_civil: '市民薄明', tw_nautical: '航海薄明', tw_astro: '天文薄明', tw_night: '夜間',
    day_note: '昼間・薄明中は1等星は肉眼で見えません（位置のみ表示）',
    sun: '太陽', moon: '月', mercury: '水星', venus: '金星', mars: '火星', jupiter: '木星', saturn: '土星',
    N: '北', E: '東', S: '南', W: '西', taipei: '台北',
    geo: '静止軌道', max_el: '最大仰角', dur: '継続', min: '分', sec: '秒', rise: '出現', peak: '最高', set: '消失',
    sel_hint: '図上の衛星またはリスト項目をクリックで詳細表示', norad: 'NORAD',
    ex_fmt: '形式', ex_sim: 'シミュレーション区間', ex_out: '出力の長さ', ex_fps: 'フレームレート', ex_size: '高さ',
    ex_go: 'アニメーション出力', ex_png: 'スナップショット PNG', ex_run: '出力中 {i}/{n}…', ex_done: '完了：{name}（{kb} KB）',
    ex_fail: '出力失敗：{msg}', ex_nomr: 'このブラウザは動画録画に非対応です。GIFをご利用ください',
    ex_from: '現在時刻から', ex_min: '{n} 分', ex_sec: '{n} 秒',
    credit: '星表 d3-celestial（BSD-3）· 天体暦 astronomy-engine（MIT）· TLE/SGP4',
    cat_all: 'すべて', mask: '仰角マスク',
    view_cycle: '表示切替', auto_cycle: '自動切替', auto_sec: '{n} 秒', tz_label: '台北時間 UTC+8',
    layout_lunar: '衛星の月面通過', sec_lunar: '月面通過スケジュール', lunar_hours: '月面通過の時間窓',
    lunar_loading: '月面通過を計算中（全カテゴリ・約20〜60秒）…', lunar_none: 'この時間窓に月面通過／接近イベントはありません',
    lunar_fail: '月面通過の計算に失敗：{msg}', lk_transit: '通過', lk_near: '接近', lunar_kind: 'イベント', lf_all: 'すべて', lf_transit: '通過のみ',
    ln_sep: '最小角距離', ln_chord: '月面を横切る時間', ln_omega: '相対角速度', ln_sat: '衛星 仰角／方位', ln_moon: '月 仰角／方位',
    ln_range: '衛星までの距離', ln_ring: '接近範囲 ±{m}°', ln_pic: '月の図（月相と向きは実際の位置関係に基づく。表面模様は模式図で秤動は含まない）',
    ln_note: 'TLEの軌道方向誤差（低軌道で約0.2〜0.5°）は月の視半径（約0.26°）と同程度のため、イベント予報です。通過帯の幅は数kmのみ。観測前に最新のTLEで再計算してください。',
    ln_events: '月面通過イベント：{n}（通過 {t}）', ln_tl: 'イベントタイムライン（明るい帯＝月が地平線上）', ln_replay: '選択イベントを再生',
    ln_none_sel: 'イベントなし', ln_dt_before: 'イベントまで {t}', ln_dt_now: 'T{s} 秒', ln_transit_word: '通過', ln_near_word: '接近',
    ph_new: '新月', ph_wax_cres: '三日月', ph_fq: '上弦の月', ph_wax_gib: '十三夜月', ph_full: '満月', ph_wan_gib: '十八夜月', ph_lq: '下弦の月', ph_wan_cres: '有明月',
  },
};
function lang(){ return (typeof LANG !== 'undefined' && SKY_I18N[LANG]) ? LANG : 'zh'; }
function st(key, vars){
  let s = (SKY_I18N[lang()][key] !== undefined) ? SKY_I18N[lang()][key] : (SKY_I18N.zh[key] !== undefined ? SKY_I18N.zh[key] : key);
  Object.keys(vars || {}).forEach(k => { s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]); });
  return s;
}
function catLabel(id, fallback){
  const k = 'cat_' + id.toLowerCase() + '_label';
  return (typeof I18N !== 'undefined' && I18N.zh[k] && typeof t === 'function') ? t(k) : (fallback || id);
}

/* ── 狀態 ─────────────────────────────────────────────────────────────────── */
const S = {
  data: null, passes: [], t0: 0, span: 0, maskDeg: 5,
  simMs: Date.now(), playing: true, speed: 60, loop: true,
  layout: 'both', stars: true, starNames: true, planets: true, ecliptic: true,
  arrows: true, names: true, allTracks: false, eastLeft: true, rangeKm: 2000,
  autoCycle: false, autoSec: 8, lastCycle: 0,
  hiddenCats: new Set(), selKey: null, hours: 2, startMs: null,
  borders: null, bordersState: 'idle',
  hit: [], dirty: true, loadCtrl: null, loading: false, exporting: false,
  cel: {ms: null, v: null}, lastListUpd: 0, listPending: false,
};
let ROOT = null, CV = null, CTX = null, VIEW = 'sky', READY = false;
const $ = sel => ROOT.querySelector(sel);

const D2R = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function cst(ms, full){
  const s = new Date(ms + 8 * 3600e3).toISOString();
  return full ? s.replace('T', ' ').slice(0, 19) + ' CST' : s.slice(11, 16);
}
function utcStr(ms){ return new Date(ms).toISOString().replace('T', ' ').slice(11, 19) + ' UTC'; }

/* ── 天體位置（astronomy-engine；J2000 恆星以歲差章動轉至當日）─────────────── */
let OBSV = null;
function celestial(ms){
  if(S.cel.ms === ms) return S.cel.v;
  const A = window.Astronomy;
  if(!OBSV) OBSV = new A.Observer(OBS.lat, OBS.lon, OBS.h);
  const time = A.MakeTime(new Date(ms));
  const hor = (ra, dec) => { const h = A.Horizon(time, OBSV, ra, dec, 'normal'); return {az: h.azimuth, el: h.altitude}; };
  const body = b => { const eq = A.Equator(b, time, OBSV, true, true); return hor(eq.ra, eq.dec); };
  const v = {sun: body('Sun'), moon: body('Moon'), planets: [], stars: [], ecl: []};
  v.moon.frac = A.Illumination('Moon', time).phase_fraction;
  v.moon.waxing = A.MoonPhase(time) < 180;
  PLANETS.forEach(p => v.planets.push(Object.assign({p}, body(p.body))));
  if(S.stars && window.SKY_STARS){
    const rot = A.Rotation_EQJ_EQD(time);
    window.SKY_STARS.forEach(s => {
      const vec = A.RotateVector(rot, A.VectorFromSphere(new A.Spherical(s.dec, s.ra * 15, 1), time));
      const sp = A.SphereFromVector(vec);
      v.stars.push(Object.assign({s}, hor(sp.lon / 15, sp.lat)));
    });
  }
  if(S.ecliptic){
    const T = (ms - 946728000000) / 3.15576e12, eps = (23.4393 - 0.0130 * T) * D2R;
    for(let i = 0; i <= 120; i++){
      const lam = i * 3 * D2R;
      const ra = (Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam)) / D2R + 360) % 360 / 15;
      const dec = Math.asin(Math.sin(eps) * Math.sin(lam)) / D2R;
      v.ecl.push(hor(ra, dec));
    }
  }
  S.cel = {ms, v};
  return v;
}

/* ── 過頂資料前處理與內插（單位向量內插，避免天頂附近方位角突變）───────────── */
function prep(p){
  p.key = p.norad_id + '|' + p.t_rise_utc;
  p.tr0 = Date.parse(p.t_rise_utc); p.tr1 = Date.parse(p.t_set_utc);
  p.u = p.track.map(q => {
    const az = q[1] * D2R, el = q[2] * D2R;
    return [Math.cos(el) * Math.sin(az), Math.cos(el) * Math.cos(az), Math.sin(el)];
  });
  return p;
}
function lerpPt(p, i, f){
  const a = p.track[i], b = p.track[Math.min(i + 1, p.track.length - 1)];
  const ua = p.u[i], ub = p.u[Math.min(i + 1, p.u.length - 1)];
  const e = ua[0] + (ub[0] - ua[0]) * f, n = ua[1] + (ub[1] - ua[1]) * f, u = ua[2] + (ub[2] - ua[2]) * f;
  const m = Math.hypot(e, n, u) || 1;
  let dl = b[4] - a[4]; if(dl > 180) dl -= 360; else if(dl < -180) dl += 360;
  return {az: (Math.atan2(e, n) / D2R + 360) % 360, el: Math.asin(clamp(u / m, -1, 1)) / D2R,
          lat: a[3] + (b[3] - a[3]) * f, lon: a[4] + dl * f};
}
function passAt(p, ms){
  if(p.stationary) return lerpPt(p, 0, 0);
  const sec = (ms - S.t0) / 1000, tr = p.track;
  if(sec < tr[0][0] || sec > tr[tr.length - 1][0]) return null;
  let lo = 0, hi = tr.length - 1;
  while(hi - lo > 1){ const mid = (lo + hi) >> 1; if(tr[mid][0] <= sec) lo = mid; else hi = mid; }
  const span = tr[hi][0] - tr[lo][0];
  return lerpPt(p, lo, span > 0 ? (sec - tr[lo][0]) / span : 0);
}
function isActive(p, ms){ return p.stationary || (ms >= p.tr0 && ms <= p.tr1); }

/* ── 投影 ─────────────────────────────────────────────────────────────────── */
function skyXY(az, el, cx, cy, R){
  const r = R * (90 - el) / 90, a = az * D2R, s = S.eastLeft ? -1 : 1;
  return [cx + s * r * Math.sin(a), cy - r * Math.cos(a)];
}
const P1 = OBS.lat * D2R, SP1 = Math.sin(P1), CP1 = Math.cos(P1);
function kmXY(lat, lon){                     // 以台北為中心的方位等距投影（km；x 向東、y 向北）
  const p2 = lat * D2R, dl = (lon - OBS.lon) * D2R;
  const cd = clamp(SP1 * Math.sin(p2) + CP1 * Math.cos(p2) * Math.cos(dl), -1, 1);
  const d = Math.acos(cd) * R_EARTH;
  const th = Math.atan2(Math.sin(dl) * Math.cos(p2), CP1 * Math.sin(p2) - SP1 * Math.cos(p2) * Math.cos(dl));
  return [d * Math.sin(th), d * Math.cos(th)];
}
function groundXY(lat, lon, cx, cy, R){
  const k = kmXY(lat, lon), sc = R / S.rangeKm;
  return [cx + k[0] * sc, cy - k[1] * sc];
}

/* ── 繪圖：共用小工具 ─────────────────────────────────────────────────────── */
function text(ctx, str, x, y, size, color, align, weight){
  ctx.font = (weight || '') + ' ' + size + 'px ' + FONT;
  ctx.textAlign = align || 'left'; ctx.textBaseline = 'middle';
  ctx.lineWidth = Math.max(2, size / 4); ctx.strokeStyle = 'rgba(6,10,18,.85)'; ctx.lineJoin = 'round';
  ctx.strokeText(str, x, y);
  ctx.fillStyle = color; ctx.fillText(str, x, y);
}
function hexRgb(h){ const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function mixC(a, b, f){ return a.map((v, i) => Math.round(v + (b[i] - v) * f)); }
const SKY_STOPS = [   // [太陽高度, 天頂色, 地平色]
  [6,   '#3f78ad', '#86b4d6'], [0, '#3a5a86', '#d0906a'], [-6, '#1c2e52', '#43507c'],
  [-12, '#0e1832', '#1c2749'], [-18, '#05080f', '#0b1120'],
];
function skyColors(sunAlt){
  const stops = SKY_STOPS;
  if(sunAlt >= stops[0][0]) return [stops[0][1], stops[0][2]];
  for(let i = 0; i < stops.length - 1; i++){
    const a = stops[i], b = stops[i + 1];
    if(sunAlt <= a[0] && sunAlt >= b[0]){
      const f = (a[0] - sunAlt) / (a[0] - b[0]);
      const c1 = mixC(hexRgb(a[1]), hexRgb(b[1]), f), c2 = mixC(hexRgb(a[2]), hexRgb(b[2]), f);
      return ['rgb(' + c1 + ')', 'rgb(' + c2 + ')'];
    }
  }
  return [stops[stops.length - 1][1], stops[stops.length - 1][2]];
}
function starColor(bv){
  if(bv < 0.0) return '#b4cdff'; if(bv < 0.4) return '#f2f6ff'; if(bv < 0.8) return '#fff1d6';
  if(bv < 1.3) return '#ffd7a1'; return '#ffab7a';
}
function drawArrow(ctx, x, y, ang, size, color){
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
  ctx.beginPath(); ctx.moveTo(size, 0); ctx.lineTo(-size * 0.8, size * 0.72); ctx.lineTo(-size * 0.35, 0); ctx.lineTo(-size * 0.8, -size * 0.72); ctx.closePath();
  ctx.fillStyle = color; ctx.strokeStyle = 'rgba(5,8,14,.9)'; ctx.lineWidth = 1.2; ctx.fill(); ctx.stroke();
  ctx.restore();
}
function drawMoon(ctx, x, y, r, frac, waxing, brightAng){
  ctx.save(); ctx.translate(x, y); ctx.rotate(brightAng);
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.fillStyle = '#3a4152'; ctx.fill();
  const a = r * Math.abs(1 - 2 * frac);
  ctx.beginPath(); ctx.arc(0, 0, r, -Math.PI / 2, Math.PI / 2, false);
  if(frac < 0.5) ctx.ellipse(0, 0, Math.max(a, 0.01), r, 0, Math.PI / 2, -Math.PI / 2, true);
  else ctx.ellipse(0, 0, Math.max(a, 0.01), r, 0, Math.PI / 2, 3 * Math.PI / 2, false);
  ctx.closePath(); ctx.fillStyle = '#f4f1e4'; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(255,255,255,.55)';
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.stroke();
  ctx.restore();
}

/* ── 衛星軌跡（兩個面板共用；proj 把 {az,el,lat,lon} 投影為螢幕座標）────────── */
function visiblePasses(ms){
  const out = [];
  S.passes.forEach(p => {
    if(S.hiddenCats.has(p.cat)) return;
    let state;
    if(isActive(p, ms)) state = 'active';
    else if(p.tr0 > ms && p.tr0 - ms <= UPCOMING_MS) state = 'upcoming';
    else if(S.allTracks) state = p.tr1 < ms ? 'done' : 'upcoming';
    else if(p.key === S.selKey) state = p.tr1 < ms ? 'done' : 'upcoming';
    else return;
    out.push({p, state});
  });
  return out;
}
function drawPasses(ctx, ms, proj, u, opt){
  const list = visiblePasses(ms), nActive = list.filter(x => x.state === 'active').length;
  const dense = [];
  list.forEach(({p, state}) => {
    const sel = p.key === S.selKey, col = p.color;
    if(p.stationary){
      const q = passAt(p, ms), xy = proj(q);
      ctx.beginPath(); ctx.rect(xy[0] - 4 * u, xy[1] - 4 * u, 8 * u, 8 * u);
      ctx.fillStyle = col; ctx.strokeStyle = sel ? '#fff' : 'rgba(255,255,255,.6)'; ctx.lineWidth = sel ? 2 : 1;
      ctx.fill(); ctx.stroke();
      if(S.names || sel) text(ctx, p.name, xy[0] + 7 * u, xy[1] - 7 * u, 10 * u, col);
      if(opt.hit) S.hit.push({x: xy[0], y: xy[1], p});
      return;
    }
    const pts = [], past = [];
    for(let i = 0; i < p.track.length - 1; i++){
      for(let k = 0; k < 3; k++){
        const q = lerpPt(p, i, k / 3), xy = proj(q);
        pts.push(xy); past.push(S.t0 + (p.track[i][0] + (p.track[i + 1][0] - p.track[i][0]) * k / 3) * 1000 <= ms);
      }
    }
    { const q = lerpPt(p, p.track.length - 1, 0); pts.push(proj(q)); past.push(S.t0 + p.track[p.track.length - 1][0] * 1000 <= ms); }
    const alpha = state === 'active' ? 1 : (state === 'upcoming' ? 0.4 : 0.22);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    // 已飛行段（實線）與未飛行段（虛線）
    const stroke = (from, to, dashed, w, a) => {
      if(to <= from) return;
      ctx.beginPath(); ctx.moveTo(pts[from][0], pts[from][1]);
      for(let i = from + 1; i <= to; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.setLineDash(dashed ? [5 * u, 4 * u] : []); ctx.lineWidth = w * u; ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.stroke();
    };
    let split = past.lastIndexOf(true);
    if(split < 0) split = 0;
    if(sel){ ctx.globalAlpha = 0.9; ctx.strokeStyle = '#fff'; ctx.lineWidth = 5 * u; ctx.setLineDash([]);
             ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); for(let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]); ctx.stroke(); }
    if(state === 'active'){ stroke(0, split, false, sel ? 3 : 2.4, 1); stroke(split, pts.length - 1, true, sel ? 2.2 : 1.5, 0.7); }
    else stroke(0, pts.length - 1, true, sel ? 2.4 : 1.3, alpha);
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    // 行進方向箭頭：沿螢幕弧長均分，至少一枚
    if(S.arrows && (state === 'active' || sel)){
      const cum = [0];
      for(let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
      const L = cum[cum.length - 1];
      if(L > 24 * u){
        const n = Math.max(1, Math.round(L / (150 * u)));
        for(let j = 0; j < n; j++){
          const target = L * (j + 0.5) / n;
          let i = 1; while(i < cum.length - 1 && cum[i] < target) i++;
          const seg = cum[i] - cum[i - 1] || 1, f = (target - cum[i - 1]) / seg;
          const x = pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, y = pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f;
          ctx.globalAlpha = state === 'active' ? 1 : Math.max(0.45, alpha);
          drawArrow(ctx, x, y, Math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0]), (sel ? 7.5 : 5.5) * u, col);
        }
        ctx.globalAlpha = 1;
      }
    }
    if(sel && state !== 'active'){       // 選取中但未在空中：標示升起／落下時刻
      text(ctx, cst(p.tr0), pts[0][0], pts[0][1] - 9 * u, 10 * u, '#fff', 'center');
      text(ctx, cst(p.tr1), pts[pts.length - 1][0], pts[pts.length - 1][1] - 9 * u, 10 * u, '#fff', 'center');
    }
    if(state === 'active'){
      const q = passAt(p, ms);
      if(q){
        const xy = proj(q);
        ctx.beginPath(); ctx.arc(xy[0], xy[1], (sel ? 6.5 : 4.6) * u, 0, 2 * Math.PI);
        ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = (sel ? 2.4 : 1.6) * u; ctx.strokeStyle = '#fff'; ctx.stroke();
        if(S.names && (sel || nActive <= 14 || q.el >= 30) || sel) text(ctx, p.name, xy[0] + 8 * u, xy[1] - 8 * u, 10.5 * u, sel ? '#fff' : col, 'left', sel ? 'bold' : '');
        if(opt.hit) S.hit.push({x: xy[0], y: xy[1], p});
      }
    }
  });
  ctx.globalAlpha = 1; ctx.setLineDash([]);
}

/* ── 天球面板 ─────────────────────────────────────────────────────────────── */
function drawSky(ctx, cx, cy, R, ms, u, opt){
  const cel = celestial(ms), sunAlt = cel.sun.el;
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.clip();
  const c = skyColors(sunAlt), g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
  g.addColorStop(0, c[0]); g.addColorStop(1, c[1]);
  ctx.fillStyle = g; ctx.fillRect(cx - R, cy - R, 2 * R, 2 * R);

  ctx.lineWidth = 1; ctx.setLineDash([]);
  ctx.strokeStyle = 'rgba(255,255,255,.16)';
  [30, 60].forEach(el => { ctx.beginPath(); ctx.arc(cx, cy, R * (90 - el) / 90, 0, 2 * Math.PI); ctx.stroke(); });
  for(let a = 0; a < 360; a += 30){
    const p = skyXY(a, 0, cx, cy, R);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p[0], p[1]); ctx.stroke();
  }
  ctx.setLineDash([4 * u, 4 * u]); ctx.strokeStyle = 'rgba(255,214,0,.5)';
  ctx.beginPath(); ctx.arc(cx, cy, R * (90 - S.maskDeg) / 90, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
  [30, 60].forEach(el => { const p = skyXY(180, el, cx, cy, R); text(ctx, el + '°', p[0] + 2 * u, p[1] + 9 * u, 9 * u, 'rgba(230,237,243,.7)'); });

  if(S.ecliptic && cel.ecl.length){        // 黃道
    ctx.strokeStyle = 'rgba(255,196,70,.55)'; ctx.setLineDash([2 * u, 5 * u]); ctx.lineWidth = 1.4 * u; ctx.beginPath();
    let pen = false;
    cel.ecl.forEach(q => {
      if(q.el < -1){ pen = false; return; }
      const p = skyXY(q.az, Math.max(q.el, 0), cx, cy, R);
      if(!pen){ ctx.moveTo(p[0], p[1]); pen = true; } else ctx.lineTo(p[0], p[1]);
    });
    ctx.stroke(); ctx.setLineDash([]);
  }
  if(S.stars){
    const dim = sunAlt > -6 ? 0.55 : 1;
    cel.stars.forEach(q => {
      if(q.el < 0) return;
      const p = skyXY(q.az, q.el, cx, cy, R), r = clamp(3.5 - 0.6 * q.s.mag, 1.8, 5.2) * u;
      ctx.globalAlpha = dim; ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 2 * Math.PI); ctx.fillStyle = starColor(q.s.bv); ctx.fill();
      ctx.beginPath(); ctx.arc(p[0], p[1], r * 2.1, 0, 2 * Math.PI); ctx.fillStyle = 'rgba(255,255,255,.10)'; ctx.fill();
      ctx.globalAlpha = 1;
      if(S.starNames) text(ctx, q.s.n[lang()] || q.s.n.en, p[0] + r + 3 * u, p[1] - 1 * u, 9.5 * u, 'rgba(226,232,255,.92)');
    });
  }
  if(S.planets){
    cel.planets.forEach(q => {
      if(q.el < 0) return;
      const p = skyXY(q.az, q.el, cx, cy, R);
      ctx.beginPath(); ctx.arc(p[0], p[1], 4.4 * u, 0, 2 * Math.PI); ctx.fillStyle = q.p.color; ctx.fill();
      ctx.lineWidth = 1.2 * u; ctx.strokeStyle = 'rgba(255,255,255,.75)'; ctx.stroke();
      text(ctx, st(q.p.key), p[0] + 8 * u, p[1] + 1 * u, 10.5 * u, q.p.color, 'left', 'bold');
    });
  }
  const sp = skyXY(cel.sun.az, Math.max(cel.sun.el, -3), cx, cy, R);
  if(cel.moon.el >= 0){
    const mp = skyXY(cel.moon.az, cel.moon.el, cx, cy, R);
    const sunP = skyXY(cel.sun.az, cel.sun.el, cx, cy, R);
    drawMoon(ctx, mp[0], mp[1], 9 * u, cel.moon.frac, cel.moon.waxing, Math.atan2(sunP[1] - mp[1], sunP[0] - mp[0]));
    text(ctx, st('moon'), mp[0] + 13 * u, mp[1] + 1 * u, 10.5 * u, '#f4f1e4', 'left', 'bold');
  }
  if(cel.sun.el >= -1){
    const gr = ctx.createRadialGradient(sp[0], sp[1], 0, sp[0], sp[1], 26 * u);
    gr.addColorStop(0, 'rgba(255,230,120,.95)'); gr.addColorStop(0.35, 'rgba(255,200,60,.35)'); gr.addColorStop(1, 'rgba(255,200,60,0)');
    ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(sp[0], sp[1], 26 * u, 0, 2 * Math.PI); ctx.fill();
    ctx.beginPath(); ctx.arc(sp[0], sp[1], 8.5 * u, 0, 2 * Math.PI); ctx.fillStyle = '#ffd94a'; ctx.fill();
    text(ctx, st('sun'), sp[0] + 12 * u, sp[1] + 1 * u, 10.5 * u, '#ffe27a', 'left', 'bold');
  }
  drawPasses(ctx, ms, q => skyXY(q.az, q.el, cx, cy, R), u, opt);
  ctx.restore();

  ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.lineWidth = 2 * u; ctx.strokeStyle = 'rgba(160,190,230,.85)'; ctx.stroke();
  [['N', 0], ['E', 90], ['S', 180], ['W', 270]].forEach(([k, a]) => {
    const p = skyXY(a, opt.inside ? 7 : -7, cx, cy, R);
    if(opt.inside && k === 'N') p[1] = Math.max(p[1], 94 * u);
    text(ctx, st(k), p[0], p[1], 13 * u, k === 'N' ? '#ff8a80' : '#c9d1d9', 'center', 'bold');
  });
  return cel;
}

/* ── 地面軌跡面板 ─────────────────────────────────────────────────────────── */
function buildBorders(gj){
  const path = new Path2D(); let n = 0;
  const addRing = (ring, close) => {
    const pts = ring.map(c => kmXY(c[1], c[0]));
    if(!pts.some(k => Math.hypot(k[0], k[1]) < 4200)) return;
    pts.forEach((k, i) => { if(i === 0) path.moveTo(k[0], -k[1]); else path.lineTo(k[0], -k[1]); });
    if(close) path.closePath();
    n++;
  };
  (gj.features || []).forEach(f => {
    const g = f.geometry; if(!g) return;
    if(g.type === 'Polygon') g.coordinates.forEach(r => addRing(r, true));
    else if(g.type === 'MultiPolygon') g.coordinates.forEach(p => p.forEach(r => addRing(r, true)));
    else if(g.type === 'LineString') addRing(g.coordinates, false);
    else if(g.type === 'MultiLineString') g.coordinates.forEach(r => addRing(r, false));
  });
  return path;
}
async function ensureBorders(){
  if(S.bordersState !== 'idle') return;
  S.bordersState = 'loading';
  try{
    const r = await fetch('/api/layers/borders');
    if(!r.ok) throw new Error('HTTP ' + r.status);
    S.borders = buildBorders(await r.json()); S.bordersState = 'ready';
  }catch(e){ console.warn('borders', e); S.bordersState = 'failed'; }
  S.dirty = true;
}
function drawGround(ctx, cx, cy, R, ms, u, opt){
  const sc = R / S.rangeKm;
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.clip();
  ctx.fillStyle = '#07111f'; ctx.fillRect(cx - R, cy - R, 2 * R, 2 * R);
  if(S.borders){
    ctx.save(); ctx.translate(cx, cy); ctx.scale(sc, sc);
    ctx.fillStyle = '#132640'; ctx.fill(S.borders, 'evenodd');
    ctx.lineWidth = 1.1 * u / sc; ctx.strokeStyle = '#3f79ad'; ctx.stroke(S.borders);
    ctx.restore();
  }
  ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(255,255,255,.12)';
  ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
  for(let d = 500; d < S.rangeKm; d += 500){
    if(d === 2000) continue;
    ctx.beginPath(); ctx.arc(cx, cy, d * sc, 0, 2 * Math.PI); ctx.setLineDash([3 * u, 5 * u]); ctx.stroke();
  }
  ctx.setLineDash([]);
  for(let d = 500; d <= S.rangeKm; d += 500){
    text(ctx, d + ' km', cx + 3 * u, cy - d * sc - 6 * u, 9 * u, d === 2000 ? '#FFD600' : 'rgba(201,209,217,.7)');
  }
  drawPasses(ctx, ms, q => groundXY(q.lat, q.lon, cx, cy, R), u, opt);
  ctx.restore();

  ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.lineWidth = 2 * u; ctx.strokeStyle = 'rgba(160,190,230,.85)'; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, 2000 * sc, 0, 2 * Math.PI); ctx.lineWidth = 2.2 * u; ctx.strokeStyle = 'rgba(255,214,0,.85)'; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx, cy - 7 * u); ctx.lineTo(cx + 5 * u, cy); ctx.lineTo(cx, cy + 7 * u); ctx.lineTo(cx - 5 * u, cy); ctx.closePath();
  ctx.fillStyle = '#FFD600'; ctx.fill(); ctx.strokeStyle = '#000'; ctx.lineWidth = 1; ctx.stroke();
  text(ctx, st('taipei'), cx + 9 * u, cy + 10 * u, 10.5 * u, '#FFD600', 'left', 'bold');
  [['N', 0, -1], ['E', 1, 0], ['S', 0, 1], ['W', -1, 0]].forEach(([k, dx, dy]) => {
    const rr = opt.inside ? R - 14 * u : R + 11 * u;
    const ly = (opt.inside && k === 'N') ? Math.max(cy + dy * rr, 94 * u) : cy + dy * rr;
    text(ctx, st(k), cx + dx * rr, ly, 13 * u, k === 'N' ? '#ff8a80' : '#c9d1d9', 'center', 'bold');
  });
  if(S.bordersState === 'loading') text(ctx, '…', cx, cy + R * 0.6, 14 * u, '#8b949e', 'center');
}


/* ── 台北本地時間：LED 七段數字 + LED 點陣指針錶盤（畫在 canvas，動畫輸出同步呈現）── */
const SEG = {0: 'abcdef', 1: 'bc', 2: 'abdeg', 3: 'abcdg', 4: 'bcfg', 5: 'acdfg', 6: 'acdefg', 7: 'abc', 8: 'abcdefg', 9: 'abcdfg'};
function segPoly(ctx, x, y, len, t, horiz){
  ctx.beginPath();
  if(horiz){
    ctx.moveTo(x, y); ctx.lineTo(x + t * .6, y - t / 2); ctx.lineTo(x + len - t * .6, y - t / 2);
    ctx.lineTo(x + len, y); ctx.lineTo(x + len - t * .6, y + t / 2); ctx.lineTo(x + t * .6, y + t / 2);
  } else {
    ctx.moveTo(x, y); ctx.lineTo(x + t / 2, y + t * .6); ctx.lineTo(x + t / 2, y + len - t * .6);
    ctx.lineTo(x, y + len); ctx.lineTo(x - t / 2, y + len - t * .6); ctx.lineTo(x - t / 2, y + t * .6);
  }
  ctx.closePath();
}
function ledDigit(ctx, x, y, w, h, t, ch, on, off){
  const g = t * .55, lit = SEG[ch], hh = h / 2;
  const segs = {
    a: [x + g, y, w - 2 * g, 1], g: [x + g, y + hh, w - 2 * g, 1], d: [x + g, y + h, w - 2 * g, 1],
    f: [x, y + g, hh - 2 * g, 0], b: [x + w, y + g, hh - 2 * g, 0],
    e: [x, y + hh + g, hh - 2 * g, 0], c: [x + w, y + hh + g, hh - 2 * g, 0],
  };
  Object.keys(segs).forEach(k => {
    const q = segs[k], isOn = lit.indexOf(k) >= 0;
    segPoly(ctx, q[0], q[1], q[2], t, q[3] === 1);
    ctx.fillStyle = isOn ? on : off;
    ctx.shadowColor = isOn ? on : 'transparent'; ctx.shadowBlur = isOn ? t * 2.2 : 0;
    ctx.fill();
  });
  ctx.shadowBlur = 0;
}
function ledDot(ctx, x, y, r, color, glow){
  ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fillStyle = color; ctx.shadowColor = glow ? color : 'transparent'; ctx.shadowBlur = glow ? r * 3 : 0; ctx.fill();
}
function ledDash(ctx, x, y, w, h, t, on, off){
  segPoly(ctx, x, y + h / 2, w, t, true);
  ctx.fillStyle = on; ctx.shadowColor = on; ctx.shadowBlur = t * 2.2; ctx.fill(); ctx.shadowBlur = 0;
}
// 台北本地時間：上列日期 YYYY-MM-DD、下列時間 HH:MM:SS，兩列皆為同尺寸 LED 七段數字
function drawLedClock(ctx, cx, top, u, ms){
  const d = new Date(ms + 8 * 3600e3), pad2 = v => String(v).padStart(2, '0');
  const dateStr = d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  const timeStr = pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + ':' + pad2(d.getUTCSeconds());
  const AMBER = '#ffb020', DIM = 'rgba(255,176,32,.10)';
  const dw = 15 * u, dh = 28 * u, t = 3.4 * u, gap = 6 * u, sepW = 11 * u, pad = 10 * u, rowGap = 8 * u;
  const rowWidth = str => {
    let w = 0;
    for(const ch of str) w += /\d/.test(ch) ? dw + gap : sepW;
    return w - gap;                                  // 最後一位數字後不留間距
  };
  const wMax = Math.max(rowWidth(dateStr), rowWidth(timeStr));
  const plateW = wMax + 2 * pad, plateH = 2 * dh + rowGap + 2 * pad - 2 * u;
  const px = cx - plateW / 2;
  ctx.save();
  ctx.fillStyle = 'rgba(8,10,16,.92)'; ctx.strokeStyle = 'rgba(255,176,32,.35)'; ctx.lineWidth = 1.2 * u;
  ctx.beginPath(); ctx.roundRect ? ctx.roundRect(px, top, plateW, plateH, 8 * u) : ctx.rect(px, top, plateW, plateH);
  ctx.fill(); ctx.stroke();
  const drawRow = (str, y) => {
    let x = cx - rowWidth(str) / 2;
    for(const ch of str){
      if(/\d/.test(ch)){ ledDigit(ctx, x, y, dw, dh, t, ch, AMBER, DIM); x += dw + gap; }
      else if(ch === ':'){
        ledDot(ctx, x + sepW / 2, y + dh * 0.32, 2 * u, AMBER, true);
        ledDot(ctx, x + sepW / 2, y + dh * 0.68, 2 * u, AMBER, true);
        x += sepW;
      } else { ledDash(ctx, x + 1 * u, y, sepW - 1 * u, dh, t * 0.9, AMBER, DIM); x += sepW; }
    }
  };
  drawRow(dateStr, top + pad - 1 * u);
  drawRow(timeStr, top + pad - 1 * u + dh + rowGap);
  ctx.shadowBlur = 0;
  ctx.restore();
}


/* ═══ 衛星凌月：事件預報（/api/taipei_lunar）＋月面示意圖＋事件時間軸 ═══════════════ */
const LUNAR = {data: null, events: [], t0: 0, span: 0, loading: false, ctrl: null, hours: 24, kind: 'all', selKey: null, replay: true};
function winStart(){ return (S.layout === 'lunar' && LUNAR.data) ? LUNAR.t0 : S.t0; }
function winSpan(){ return (S.layout === 'lunar' && LUNAR.data) ? LUNAR.span : S.span; }
function syncSlider(){
  const sl = $('#sk-slider'); if(!sl) return;
  sl.max = Math.round(winSpan() / 1000); sl.value = Math.round((S.simMs - winStart()) / 1000);
}
function cstDT(ms){ return new Date(ms + 8 * 3600e3).toISOString().slice(5, 19).replace('T', ' '); }
function lunarVisible(){
  return LUNAR.events.filter(e => !S.hiddenCats.has(e.cat) && (LUNAR.kind === 'all' || e.kind === 'transit'));
}
function lunarHalf(e){ const t = e.track; return t.length ? Math.max(Math.abs(t[0][0]), Math.abs(t[t.length - 1][0])) : 2; }
function lunarSel(ms){
  const vis = lunarVisible();
  let e = vis.find(x => x.key === LUNAR.selKey);
  if(!e) e = vis.find(x => x.tms >= ms - 5000) || vis[vis.length - 1] || null;
  return e || null;
}
async function loadLunar(startMs){
  if(LUNAR.ctrl) LUNAR.ctrl.abort();
  const ctrl = LUNAR.ctrl = new AbortController();
  LUNAR.loading = true; setMsg(st('lunar_loading'));
  if(startMs == null){
    const v = $('#sk-start') && $('#sk-start').value;
    startMs = v ? Date.parse(v + ':00+08:00') : Date.now();
  }
  const url = '/api/taipei_lunar?ts=' + encodeURIComponent(new Date(startMs).toISOString()) + '&hours=' + LUNAR.hours;
  try{
    const r = await fetch(url, {signal: ctrl.signal});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    LUNAR.data = d; LUNAR.t0 = Date.parse(d.timestamp); LUNAR.span = d.hours * 3600e3;
    LUNAR.events = d.events.map(e => Object.assign(e, {tms: Date.parse(e.t_utc), key: e.norad_id + '|' + e.t_utc}));
    if(S.layout === 'lunar'){
      if(S.simMs < LUNAR.t0 || S.simMs > LUNAR.t0 + LUNAR.span) S.simMs = clamp(Date.now(), LUNAR.t0, LUNAR.t0 + LUNAR.span);
      setMsg(LUNAR.events.length ? '' : st('lunar_none'));
      buildCats(); refreshList(); syncSlider();
    }
  }catch(e){
    if(e.name === 'AbortError') return;
    LUNAR.data = null; LUNAR.events = [];
    if(S.layout === 'lunar') setMsg(st('lunar_fail', {msg: e.message}));
  }finally{
    if(LUNAR.ctrl === ctrl){ LUNAR.loading = false; LUNAR.ctrl = null; }
    S.dirty = true;
  }
}
function selectLunar(e, jump){
  LUNAR.selKey = e ? e.key : null;
  if(e && jump){
    S.speed = 1; const sp = $('#sk-speed'); if(sp) sp.value = '1';
    S.simMs = clamp(e.tms - (lunarHalf(e) + 6) * 1000, LUNAR.t0, LUNAR.t0 + LUNAR.span);
    S.playing = true; syncPlayBtn();
  }
  S.dirty = true; updateListStates(true); showDetail(); syncSlider();
}
function lunarDetail(){
  const el = $('#sk-detail'); if(!el) return;
  const e = lunarSel(S.simMs);
  if(!LUNAR.data){ el.textContent = st('sel_hint'); return; }
  if(!e){ el.textContent = st('ln_none_sel'); return; }
  el.innerHTML = '<b style="color:' + e.color + '">' + e.name + '</b> · ' + st('norad') + ' ' + e.norad_id +
    ' · <b>' + st(e.kind === 'transit' ? 'lk_transit' : 'lk_near') + '</b><br>' + cstDT(e.tms) + ' CST · ' +
    st('ln_sep') + ' ' + e.sep_deg.toFixed(3) + '°' + (e.kind === 'transit' ? ' · ' + st('ln_chord') + ' ' + e.chord_s.toFixed(2) + ' ' + st('sec') : '');
}
function buildLunarList(){
  const box = $('#sk-list'); box.innerHTML = '';
  LUNAR.events.forEach(e => {
    const d = document.createElement('div'); d.className = 'sk-pass'; d.dataset.key = e.key;
    d.innerHTML = '<span class="sk-dot" style="background:' + e.color + '"></span><span class="sk-pt tm">' + cstDT(e.tms).slice(0, 14) +
      '</span><span class="sk-pn">' + e.name + '</span><span class="sk-bd ' + e.kind + '">' + st(e.kind === 'transit' ? 'lk_transit' : 'lk_near') +
      '</span><span class="sk-pe">' + e.sep_deg.toFixed(2) + '°</span>';
    d.addEventListener('click', () => selectLunar(e, true));
    box.appendChild(d);
  });
  if(LUNAR.data && !LUNAR.events.length){ const n = document.createElement('div'); n.className = 'sk-pass'; n.textContent = st('lunar_none'); box.appendChild(n); }
  showDetail(); updateListStates();
}

/* 月相名稱 */
function phaseName(frac, waxing){
  if(frac < 0.03) return st('ph_new');
  if(frac > 0.97) return st('ph_full');
  if(Math.abs(frac - 0.5) <= 0.06) return st(waxing ? 'ph_fq' : 'ph_lq');
  if(frac < 0.5) return st(waxing ? 'ph_wax_cres' : 'ph_wan_cres');
  return st(waxing ? 'ph_wax_gib' : 'ph_wan_gib');
}
/* 畫面座標基底（與後端一致）：right＝方位角增加方向、up＝天頂方向 */
function tangentBasis(az, el){
  const m = azelVec(az, el);
  const right = norm3([m[1], -m[0], 0]);
  const up = norm3([-m[2] * m[0], -m[2] * m[1], 1 - m[2] * m[2]]);
  return {m, right, up};
}
function azelVec(az, el){ const a = az * D2R, e = el * D2R; return [Math.cos(e) * Math.sin(a), Math.cos(e) * Math.cos(a), Math.sin(e)]; }
function norm3(v){ const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
function dot3(a, b){ return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
/* 月球畫面上：太陽方向角（自 right 逆時針）與天球北極方向角（自 up 順時針）*/
function moonFrame(moonAz, moonEl, sunAz, sunEl){
  const b = tangentBasis(moonAz, moonEl);
  const sv = azelVec(sunAz, sunEl), pl = OBS.lat * D2R, ncp = [0, Math.cos(pl), Math.sin(pl)];
  return {sunAng: Math.atan2(dot3(sv, b.up), dot3(sv, b.right)) / D2R, northAng: Math.atan2(dot3(ncp, b.right), dot3(ncp, b.up)) / D2R};
}

/* 月面程序化貼圖（示意）：主要月海位置取自標準正立月面圖（北上、東左之肉眼視角）*/
const MARIA = [[-0.28, 0.42, 0.30, 0.22, 0.55], [0.08, 0.45, 0.17, 0.15, 0.5], [0.26, 0.20, 0.22, 0.17, 0.5], [0.62, 0.30, 0.11, 0.08, 0.6],
  [0.60, -0.10, 0.13, 0.15, 0.45], [0.36, -0.12, 0.09, 0.08, 0.4], [-0.66, 0.05, 0.28, 0.38, 0.5], [-0.22, -0.30, 0.17, 0.14, 0.42],
  [-0.52, -0.36, 0.11, 0.09, 0.5], [0.0, 0.86, 0.36, 0.06, 0.4]];
function hash2(i, j){ let h = (i * 374761393 + j * 668265263) | 0; h = ((h ^ (h >>> 13)) * 1274126177) | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967295; }
function vnoise(x, y){
  const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
  const a = hash2(xi, yi), b = hash2(xi + 1, yi), c = hash2(xi, yi + 1), d = hash2(xi + 1, yi + 1);
  return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
}
function albedo(u, v){
  let a = 1;
  for(const m of MARIA){ const dx = (u - m[0]) / m[2], dy = (v - m[1]) / m[3], d = dx * dx + dy * dy; if(d < 1.6) a *= 1 - m[4] * Math.exp(-d * 1.8); }
  a *= 0.88 + 0.22 * (0.55 * vnoise(u * 7 + 3, v * 7 + 9) + 0.3 * vnoise(u * 19 + 5, v * 19 + 1) + 0.15 * vnoise(u * 43, v * 43 + 7));
  a += 0.30 * Math.exp(-((u + 0.12) ** 2 + (v + 0.72) ** 2) / 0.004) + 0.22 * Math.exp(-((u + 0.33) ** 2 + (v - 0.10) ** 2) / 0.003)
     + 0.18 * Math.exp(-((u + 0.55) ** 2 + (v - 0.32) ** 2) / 0.003);
  return clamp(a, 0.32, 1.15);
}
const SPRITES = new Map();
function moonSprite(R, frac, sunAng, northAng){
  const key = [Math.round(R), Math.round(frac * 100), Math.round(sunAng / 3), Math.round(northAng / 3)].join('|');
  if(SPRITES.has(key)) return SPRITES.get(key);
  const D = Math.ceil(2 * R) + 2, cv = document.createElement('canvas'); cv.width = cv.height = D;
  const c = cv.getContext('2d'), img = c.createImageData(D, D);
  const inc = Math.acos(clamp(2 * frac - 1, -1, 1)), a = sunAng * D2R;
  const Lx = Math.sin(inc) * Math.cos(a), Ly = Math.sin(inc) * Math.sin(a), Lz = Math.cos(inc);
  const th = northAng * D2R, ct = Math.cos(th), sn = Math.sin(th);
  for(let y = 0; y < D; y++){
    for(let x = 0; x < D; x++){
      const nx = (x + 0.5 - D / 2) / R, ny = -(y + 0.5 - D / 2) / R, r2 = nx * nx + ny * ny, o = (y * D + x) * 4;
      const edge = clamp((1 - Math.sqrt(r2)) * R + 0.5, 0, 1);
      if(edge <= 0){ img.data[o + 3] = 0; continue; }
      const nz = Math.sqrt(Math.max(0, 1 - Math.min(r2, 1)));
      const lam = Math.max(0, nx * Lx + ny * Ly + nz * Lz);
      const u = nx * ct - ny * sn, v = nx * sn + ny * ct;          // 螢幕座標 → 月面正立座標
      const alb = albedo(u, v), lum = alb * (0.96 * lam) + 0.05 * (0.55 + 0.45 * nz);
      img.data[o] = clamp(232 * lum, 0, 255); img.data[o + 1] = clamp(226 * lum, 0, 255); img.data[o + 2] = clamp(212 * lum + 4, 0, 255);
      img.data[o + 3] = 255 * edge;
    }
  }
  c.putImageData(img, 0, 0);
  if(SPRITES.size > 10) SPRITES.delete(SPRITES.keys().next().value);
  SPRITES.set(key, cv);
  return cv;
}
function trackAt(e, tRel){
  const t = e.track; if(!t.length || tRel < t[0][0] || tRel > t[t.length - 1][0]) return null;
  let i = 1; while(i < t.length - 1 && t[i][0] < tRel) i++;
  const f = (tRel - t[i - 1][0]) / ((t[i][0] - t[i - 1][0]) || 1);
  return [t[i - 1][1] + (t[i][1] - t[i - 1][1]) * f, t[i - 1][2] + (t[i][2] - t[i - 1][2]) * f];
}

function drawLunarScene(ctx, W, H, ms, u, opt, top, bot){
  const cel = celestial(ms), e = lunarSel(ms);
  const tlH = 50 * u, availH = H - top - bot - tlH;
  const side = W / availH >= 1.35;
  let V, cx, cy, info;
  if(side){ V = Math.min(availH / 2 - 8 * u, W * 0.30); cx = W * 0.31; cy = top + availH / 2; info = {x: cx + V + 34 * u, y: top + 6 * u, w: W - (cx + V + 34 * u) - 14 * u}; }
  else { V = Math.min(W / 2 - 22 * u, availH * 0.36); cx = W / 2; cy = top + V + 14 * u; info = {x: 14 * u, y: cy + V + 34 * u, w: W - 28 * u}; }

  // 月面參數：事件時取事件當下；否則取目前時刻月球
  let frac, sunAng, northAng, Rdeg, mAz, mEl, waxing;
  if(e){
    frac = e.moon_frac; Rdeg = e.moon_r_deg; mAz = e.moon_az; mEl = e.moon_el; waxing = e.moon_phase_deg < 180;
    if(e._north === undefined){ const sunEv = celestial(e.tms).sun; e._north = moonFrame(mAz, mEl, sunEv.az, sunEv.el).northAng; }
    sunAng = e.sun_angle_deg; northAng = e._north;
  } else {
    frac = cel.moon.frac; Rdeg = 0.259; mAz = cel.moon.az; mEl = cel.moon.el; waxing = cel.moon.waxing;
    const fr = moonFrame(mAz, mEl, cel.sun.az, cel.sun.el); sunAng = fr.sunAng; northAng = fr.northAng;
  }
  const margin = (LUNAR.data && LUNAR.data.near_margin_deg) || 0.3;
  const Hdeg = Rdeg + margin + 0.06, ppd = V / Hdeg, Rpx = Rdeg * ppd;

  // 畫框與刻度
  ctx.save();
  ctx.beginPath(); ctx.rect(cx - V, cy - V, 2 * V, 2 * V); ctx.clip();
  ctx.fillStyle = '#04060b'; ctx.fillRect(cx - V, cy - V, 2 * V, 2 * V);
  ctx.strokeStyle = 'rgba(160,190,230,.14)'; ctx.lineWidth = 1;
  for(let g = -0.6; g <= 0.6001; g += 0.1){
    const px = cx + g * ppd, py = cy - g * ppd;
    ctx.beginPath(); ctx.moveTo(px, cy - V); ctx.lineTo(px, cy + V); ctx.moveTo(cx - V, py); ctx.lineTo(cx + V, py); ctx.stroke();
  }
  // 擦邊範圍環
  ctx.setLineDash([5 * u, 4 * u]); ctx.strokeStyle = 'rgba(255,214,0,.55)'; ctx.lineWidth = 1.3 * u;
  ctx.beginPath(); ctx.arc(cx, cy, (Rdeg + margin) * ppd, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
  text(ctx, st('ln_ring', {m: margin.toFixed(2)}), cx, cy - (Rdeg + margin) * ppd + 9 * u, 9.5 * u, 'rgba(255,214,0,.85)', 'center');
  // 月球
  const spr = moonSprite(Rpx, frac, sunAng, northAng);
  ctx.drawImage(spr, cx - spr.width / 2, cy - spr.height / 2);
  // 衛星軌跡
  if(e && e.track.length){
    const pts = e.track.map(q => [cx + q[1] * ppd, cy - q[2] * ppd, q[0]]);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(5,8,14,.85)'; ctx.lineWidth = 5 * u; ctx.beginPath(); pts.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.stroke();
    ctx.strokeStyle = e.color; ctx.lineWidth = 2.6 * u; ctx.beginPath(); pts.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.stroke();
    for(const f of [0.2, 0.5, 0.8]){
      const i = Math.max(1, Math.min(pts.length - 1, Math.round(f * (pts.length - 1))));
      drawArrow(ctx, pts[i][0], pts[i][1], Math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0]), 7 * u, e.color);
    }
    // 最近距離點
    const p0 = trackAt(e, 0);
    if(p0){ const px = cx + p0[0] * ppd, py = cy - p0[1] * ppd;
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.4 * u; ctx.beginPath(); ctx.moveTo(px - 5 * u, py); ctx.lineTo(px + 5 * u, py); ctx.moveTo(px, py - 5 * u); ctx.lineTo(px, py + 5 * u); ctx.stroke(); }
    // 目前衛星位置
    const tRel = (ms - e.tms) / 1000, pc = trackAt(e, tRel);
    if(pc){
      const px = cx + pc[0] * ppd, py = cy - pc[1] * ppd;
      ctx.beginPath(); ctx.arc(px, py, 5.5 * u, 0, 2 * Math.PI); ctx.fillStyle = e.color; ctx.fill(); ctx.lineWidth = 2 * u; ctx.strokeStyle = '#fff'; ctx.stroke();
    }
  }
  ctx.restore();
  ctx.strokeStyle = 'rgba(160,190,230,.6)'; ctx.lineWidth = 1.5 * u; ctx.strokeRect(cx - V, cy - V, 2 * V, 2 * V);
  // 比例尺（0.25°）
  const sc = 0.25 * ppd; ctx.strokeStyle = '#c9d1d9'; ctx.lineWidth = 1.6 * u; ctx.beginPath();
  ctx.moveTo(cx - V + 10 * u, cy + V - 12 * u); ctx.lineTo(cx - V + 10 * u + sc, cy + V - 12 * u); ctx.stroke();
  text(ctx, '0.25°', cx - V + 10 * u + sc / 2, cy + V - 21 * u, 9.5 * u, '#c9d1d9', 'center');
  // 月相標示
  text(ctx, phaseName(frac, waxing) + '  ' + Math.round(frac * 100) + '%    ' + st('hud_alt') + ' ' + mEl.toFixed(1) + '°  az ' + mAz.toFixed(0) + '°',
       cx + V - 10 * u, cy + V - 14 * u, 11.5 * u, '#e6edf3', 'right', 'bold');
  // 倒數
  if(e){
    const dt = (ms - e.tms) / 1000, adt = Math.abs(dt);
    const label = adt < 60 ? st('ln_dt_now', {s: (dt >= 0 ? '+' : '−') + adt.toFixed(1)}) :
      st('ln_dt_before', {t: (dt < 0 ? '' : '−') + Math.floor(adt / 3600) + ':' + String(Math.floor(adt % 3600 / 60)).padStart(2, '0') + ':' + String(Math.floor(adt % 60)).padStart(2, '0')});
    text(ctx, label, cx + V - 8 * u, cy - V + 16 * u, 14 * u, adt < 8 ? '#ffd24a' : '#c9d1d9', 'right', 'bold');
  }
  // 事件資訊卡
  let ly = info.y + 4 * u; const lh = 19 * u;
  const put = (label, val, col) => { text(ctx, label, info.x, ly, 11 * u, '#8b949e'); text(ctx, val, info.x + 118 * u, ly, 12 * u, col || '#e6edf3', 'left', 'bold'); ly += lh; };
  if(e){
    text(ctx, e.name, info.x, ly, 16 * u, e.color, 'left', 'bold'); ly += lh + 4 * u;
    put(st('norad'), String(e.norad_id));
    put(cstDT(e.tms).slice(0, 5) + ' CST', cstDT(e.tms).slice(6) + '.' + String(Math.floor((e.tms % 1000 + 1000) % 1000 / 100)));
    put('', st(e.kind === 'transit' ? 'ln_transit_word' : 'ln_near_word'), e.kind === 'transit' ? '#ffd24a' : '#9fb3c8');
    put(st('ln_sep'), e.sep_deg.toFixed(3) + '°  (R = ' + e.moon_r_deg.toFixed(3) + '°)');
    if(e.kind === 'transit') put(st('ln_chord'), e.chord_s.toFixed(2) + ' ' + st('sec'));
    put(st('ln_omega'), e.omega_dps.toFixed(3) + ' °/s');
    put(st('ln_sat'), e.sat_el.toFixed(1) + '° / ' + e.sat_az.toFixed(0) + '°');
    put(st('ln_moon'), e.moon_el.toFixed(1) + '° / ' + e.moon_az.toFixed(0) + '°');
    put(st('ln_range'), Math.round(e.sat_range_km).toLocaleString() + ' km');
  } else {
    text(ctx, LUNAR.loading ? st('lunar_loading') : st('ln_none_sel'), info.x, ly + 8 * u, 12 * u, '#8b949e', 'left');
    ly += lh * 2;
  }
  // 誤差說明（自動折行）
  ctx.font = (9.5 * u) + 'px ' + FONT;
  const words = st('ln_note').split(''); let line = '', yy = ly + 8 * u;
  words.forEach(ch => { if(ctx.measureText(line + ch).width > info.w){ text(ctx, line, info.x, yy, 9.5 * u, '#d29922', 'left'); yy += 13 * u; line = ch; } else line += ch; });
  if(line) text(ctx, line, info.x, yy, 9.5 * u, '#d29922', 'left');
  // 月面圖說明（自動折行）
  { let l2 = '', y2 = yy + 22 * u;
    for(const ch of st('ln_pic')){ if(ctx.measureText(l2 + ch).width > info.w){ text(ctx, l2, info.x, y2, 9.5 * u, '#8fb8e8', 'left'); y2 += 13 * u; l2 = ch; } else l2 += ch; }
    if(l2) text(ctx, l2, info.x, y2, 9.5 * u, '#8fb8e8', 'left'); }

  // 事件時間軸
  const ty = H - bot - tlH + 8 * u, tx0 = 14 * u, tx1 = W - 14 * u;
  text(ctx, st('ln_tl'), tx0, ty, 10 * u, '#8fb8e8', 'left', 'bold');
  const by = ty + 24 * u, bh = 16 * u;
  ctx.fillStyle = '#0d1421'; ctx.fillRect(tx0, by - bh / 2, tx1 - tx0, bh);
  if(LUNAR.data){
    const t0 = LUNAR.t0, sp = LUNAR.span, X = t => tx0 + (t - t0) / sp * (tx1 - tx0);
    (LUNAR.data.moon_up_runs || []).forEach(r => {
      const a = X(Date.parse(r[0])), b = X(Date.parse(r[1]));
      ctx.fillStyle = 'rgba(170,190,225,.28)'; ctx.fillRect(a, by - bh / 2, Math.max(1, b - a), bh);
    });
    ctx.strokeStyle = 'rgba(160,190,230,.35)'; ctx.lineWidth = 1;
    const hr0 = Math.ceil((t0 + 8 * 3600e3) / 3600e3) * 3600e3 - 8 * 3600e3;
    for(let t = hr0; t <= t0 + sp; t += 3600e3){
      const hh = new Date(t + 8 * 3600e3).getUTCHours();
      const x = X(t); ctx.beginPath(); ctx.moveTo(x, by + bh / 2); ctx.lineTo(x, by + bh / 2 + (hh % 3 === 0 ? 5 : 2.5) * u); ctx.stroke();
      if(hh % 3 === 0 && sp <= 49 * 3600e3) text(ctx, String(hh).padStart(2, '0'), x, by + bh / 2 + 12 * u, 9 * u, '#8b949e', 'center');
    }
    lunarVisible().forEach(ev => {
      const x = X(ev.tms), h = ev.kind === 'transit' ? bh : bh * 0.55, sel = e && ev.key === e.key;
      ctx.strokeStyle = sel ? '#ffffff' : ev.color; ctx.lineWidth = (sel ? 2.6 : (ev.kind === 'transit' ? 1.6 : 1)) * u;
      ctx.globalAlpha = ev.kind === 'transit' || sel ? 1 : 0.6;
      ctx.beginPath(); ctx.moveTo(x, by - h / 2); ctx.lineTo(x, by + h / 2); ctx.stroke(); ctx.globalAlpha = 1;
    });
    const xm = X(clamp(ms, t0, t0 + sp));
    ctx.strokeStyle = '#ff4d4f'; ctx.lineWidth = 2 * u; ctx.beginPath(); ctx.moveTo(xm, by - bh / 2 - 3 * u); ctx.lineTo(xm, by + bh / 2 + 3 * u); ctx.stroke();
  }
}

/* ── 整體版面／HUD ────────────────────────────────────────────────────────── */
function twilight(alt){
  return alt > 0 ? 'tw_day' : alt > -6 ? 'tw_civil' : alt > -12 ? 'tw_nautical' : alt > -18 ? 'tw_astro' : 'tw_night';
}
function render(ctx, W, H, ms, opt){
  opt = opt || {};
  const u = opt.u || Math.max(0.8, Math.min(W, H) / 760);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = '#0a0e17'; ctx.fillRect(0, 0, W, H);
  if(opt.hit) S.hit = [];
  const top = 92 * u, bot = 30 * u, availH = H - top - bot, lay = opt.layout || S.layout;
  const cel = celestial(ms);
  const panels = [];
  const side = opt.forceSide || W / availH >= 1.45;
  if(lay === 'lunar'){
    /* 由 drawLunarScene 繪製 */
  } else if(lay === 'both'){
    if(side){
      const R = Math.min(W / 4, availH / 2) - 42 * u;
      panels.push({k: 'sky', cx: W / 4, cy: top + availH / 2 + 8 * u, R}, {k: 'ground', cx: 3 * W / 4, cy: top + availH / 2 + 8 * u, R});
    } else {
      const R = Math.min(W / 2, availH / 4) - 40 * u;
      panels.push({k: 'sky', cx: W / 2, cy: top + availH / 4 + 8 * u, R}, {k: 'ground', cx: W / 2, cy: top + 3 * availH / 4 + 8 * u, R});
    }
  } else {
    const R0 = Math.min(W / 2, availH / 2) - 42 * u;
    const cap = Math.min(W / 2 - 34 * u, (H - 30 * u) / 2);
    const R = Math.min(R0 * 1.3, cap);
    panels.push({k: lay, cx: W / 2, cy: H - 20 * u - R, R, single: true});
  }
  panels.forEach(pn => {
    if(pn.R < 20) return;
    const po = Object.assign({}, opt, {inside: !!pn.single});
    if(pn.k === 'sky') drawSky(ctx, pn.cx, pn.cy, pn.R, ms, u, po);
    else drawGround(ctx, pn.cx, pn.cy, pn.R, ms, u, po);
    const ttl = pn.k === 'sky' ? st('title_sky') : st('title_ground', {r: S.rangeKm});
    if(pn.single) text(ctx, ttl, 12 * u, 56 * u, 12 * u, '#8fb8e8', 'left', 'bold');
    else text(ctx, ttl, pn.cx, pn.cy - pn.R - Math.max(31 * u, pn.R * 0.08 + 17 * u), 12 * u, '#8fb8e8', 'center', 'bold');
  });
  if(lay === 'lunar') drawLunarScene(ctx, W, H, ms, u, opt, top, bot);
  // HUD
  const nUp = S.passes.filter(p => !S.hiddenCats.has(p.cat) && isActive(p, ms)).length;
  const hudCount = lay === 'lunar' ? st('ln_events', {n: lunarVisible().length, t: lunarVisible().filter(x => x.kind === 'transit').length}) : st('hud_above') + ': ' + nUp;
  text(ctx, cst(ms, true) + '   (' + utcStr(ms) + ')', 12 * u, 16 * u, 13 * u, '#e6edf3', 'left', 'bold');
  text(ctx, st('taipei') + ' ' + OBS.lat.toFixed(2) + '°N ' + OBS.lon.toFixed(2) + '°E   ' + hudCount,
       12 * u, 33 * u, 10.5 * u, '#8b949e');
  const tw = st(twilight(cel.sun.el));
  text(ctx, st('hud_sun') + ' ' + st('hud_alt') + ' ' + cel.sun.el.toFixed(1) + '° (' + tw + ')   ' +
       st('hud_moon') + ' ' + st('hud_alt') + ' ' + cel.moon.el.toFixed(1) + '° ' + st('hud_illum') + ' ' + Math.round(cel.moon.frac * 100) + '%',
       W - 12 * u, 16 * u, 11 * u, '#c9d1d9', 'right');
  if(S.stars && cel.sun.el > -6) text(ctx, st('day_note'), W - 12 * u, 33 * u, 9.5 * u, '#d29922', 'right');
  drawLedClock(ctx, W / 2, 6 * u, u, ms);
  // 圖例
  let lx = 12 * u;
  const legCats = (lay === 'lunar' && LUNAR.data) ? LUNAR.data.categories : ((S.data && S.data.categories) || {});
  Object.keys(legCats).forEach(id => {
    const c = legCats[id], hidden = S.hiddenCats.has(id);
    ctx.globalAlpha = hidden ? 0.35 : 1;
    ctx.beginPath(); ctx.arc(lx + 4 * u, H - 15 * u, 4.5 * u, 0, 2 * Math.PI); ctx.fillStyle = c.color; ctx.fill();
    const label = catLabel(id, c.label);
    text(ctx, label, lx + 12 * u, H - 15 * u, 10.5 * u, '#c9d1d9');
    ctx.font = 10.5 * u + 'px ' + FONT; lx += 22 * u + ctx.measureText(label).width;
    ctx.globalAlpha = 1;
  });
  text(ctx, st('credit'), W - 12 * u, H - 15 * u, 9 * u, 'rgba(139,148,158,.85)', 'right');
}

/* ── 螢幕迴圈 ─────────────────────────────────────────────────────────────── */
let lastT = 0;
function frame(now){
  requestAnimationFrame(frame);
  if(!READY || VIEW !== 'sky' || document.hidden || S.exporting) { lastT = now; return; }
  const dt = Math.min(0.25, (now - lastT) / 1000); lastT = now;
  if(S.autoCycle && now - S.lastCycle > S.autoSec * 1000) cycleLayout();
  if(S.playing && winSpan()){
    S.simMs += dt * 1000 * S.speed; S.dirty = true;
    const w0 = winStart(), end = w0 + winSpan();
    if(S.layout === 'lunar' && LUNAR.replay && LUNAR.selKey && S.speed <= 5){
      const ev = LUNAR.events.find(x => x.key === LUNAR.selKey);
      if(ev){ const h = lunarHalf(ev) + 6; if(S.simMs > ev.tms + h * 1000 && S.simMs < ev.tms + h * 1000 + 3000) S.simMs = ev.tms - h * 1000; }
    }
    if(S.simMs > end){ if(S.loop) S.simMs = w0; else { S.simMs = end; S.playing = false; syncPlayBtn(); } }
  }
  if(S.dirty){
    S.dirty = false;
    render(CTX, CV.width, CV.height, S.simMs, {hit: true, u: Math.max(0.8, Math.min(CV.width, CV.height) / 760)});
    const sl = $('#sk-slider'); if(sl && winSpan()) sl.value = Math.round((S.simMs - winStart()) / 1000);
    const tl = $('#sk-time'); if(tl) tl.textContent = cst(S.simMs, true);
    S.listPending = true;
  }
  if(S.listPending && now - S.lastListUpd > 400){ S.lastListUpd = now; S.listPending = false; updateListStates(); }
}
function resize(){
  if(!CV) return;
  const wrap = CV.parentElement, dpr = window.devicePixelRatio || 1;
  const w = Math.max(200, wrap.clientWidth), h = Math.max(200, wrap.clientHeight);
  CV.width = Math.round(w * dpr); CV.height = Math.round(h * dpr);
  CV.style.width = w + 'px'; CV.style.height = h + 'px';
  S.dirty = true;
}

/* ── 資料載入 ─────────────────────────────────────────────────────────────── */
async function load(startMs){
  if(S.loadCtrl) S.loadCtrl.abort();
  const ctrl = S.loadCtrl = new AbortController();
  S.loading = true; setMsg(st('loading'));
  const url = '/api/taipei_sky?ts=' + encodeURIComponent(new Date(startMs).toISOString()) +
              '&hours=' + S.hours + '&step_sec=30&min_el=10&max_per_cat=25';
  try{
    const r = await fetch(url, {signal: ctrl.signal});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    S.data = d; S.t0 = Date.parse(d.timestamp); S.span = d.hours * 3600e3; S.maskDeg = d.mask_deg;
    S.passes = d.passes.map(prep).sort((a, b) => (a.stationary - b.stationary) || (a.tr0 - b.tr0));
    if(S.simMs < S.t0 || S.simMs > S.t0 + S.span) S.simMs = clamp(Date.now(), S.t0, S.t0 + S.span);
    syncSlider();
    buildCats(); refreshList();
    if(S.layout !== 'lunar') setMsg(S.passes.length ? '' : st('no_passes'));
  }catch(e){
    if(e.name === 'AbortError') return;
    setMsg(st('load_fail', {msg: e.message}));
  }finally{
    if(S.loadCtrl === ctrl){ S.loading = false; S.loadCtrl = null; }
    S.dirty = true;
  }
}
function reloadNow(){ S.startMs = null; S.simMs = Date.now(); load(Date.now() - PRE_MS); if(S.layout === 'lunar') loadLunar(Date.now()); }
function setMsg(m){ const el = $('#sk-msg'); if(el){ el.textContent = m; el.style.display = m ? 'flex' : 'none'; } }

/* ── 選取／清單 ───────────────────────────────────────────────────────────── */
function select(p, jump){
  S.selKey = p ? p.key : null;
  if(p && jump) S.simMs = clamp(p.tr0 - 30e3, S.t0, S.t0 + S.span);
  S.dirty = true; updateListStates(true); showDetail();
}
function refreshList(){ if(S.layout === 'lunar') buildLunarList(); else buildList(); }
function showDetail(){
  if(S.layout === 'lunar'){ lunarDetail(); return; }
  const el = $('#sk-detail'), p = S.passes.find(x => x.key === S.selKey);
  if(!p){ el.textContent = st('sel_hint'); return; }
  const m = Math.floor(p.duration_s / 60), s = p.duration_s % 60;
  el.innerHTML = '<b style="color:' + p.color + '">' + p.name + '</b> · ' + st('norad') + ' ' + p.norad_id + '<br>' +
    (p.stationary ? st('geo') : st('rise') + ' ' + cst(p.tr0) + ' · ' + st('peak') + ' ' + cst(Date.parse(p.t_max_utc)) + ' · ' + st('set') + ' ' + cst(p.tr1) +
      '<br>' + st('max_el') + ' ' + p.max_el_deg + '° · ' + st('dur') + ' ' + m + ' ' + st('min') + ' ' + s + ' ' + st('sec') +
      (p.clipped_start || p.clipped_end ? ' *' : ''));
}
function buildList(){
  const box = $('#sk-list'); box.innerHTML = '';
  S.passes.forEach(p => {
    const d = document.createElement('div'); d.className = 'sk-pass'; d.dataset.key = p.key;
    d.innerHTML = '<span class="sk-dot" style="background:' + p.color + '"></span><span class="sk-pn">' + p.name +
      '</span><span class="sk-pt">' + (p.stationary ? st('geo') : cst(p.tr0)) + '</span><span class="sk-pe">' + p.max_el_deg + '°</span>';
    d.addEventListener('click', () => select(p, true));
    box.appendChild(d);
  });
  showDetail();
}
function updateListStates(scroll){
  const box = $('#sk-list'); if(!box) return;
  if(S.layout === 'lunar'){
    const cur = lunarSel(S.simMs);
    box.querySelectorAll('.sk-pass[data-key]').forEach(d => {
      const ev = LUNAR.events.find(x => x.key === d.dataset.key); if(!ev) return;
      d.classList.toggle('hidden', S.hiddenCats.has(ev.cat) || (LUNAR.kind === 'transit' && ev.kind !== 'transit'));
      d.classList.toggle('done', ev.tms < S.simMs - 5000);
      d.classList.toggle('active', Math.abs(ev.tms - S.simMs) < 30000);
      const sel = !!cur && ev.key === cur.key; d.classList.toggle('sel', sel);
      if(sel && scroll) d.scrollIntoView({block: 'nearest'});
    });
    return;
  }
  box.querySelectorAll('.sk-pass').forEach(d => {
    const p = S.passes.find(x => x.key === d.dataset.key); if(!p) return;
    d.classList.toggle('hidden', S.hiddenCats.has(p.cat));
    d.classList.toggle('active', isActive(p, S.simMs));
    d.classList.toggle('done', !p.stationary && p.tr1 < S.simMs);
    const sel = p.key === S.selKey; d.classList.toggle('sel', sel);
    if(sel && scroll) d.scrollIntoView({block: 'nearest'});
  });
}
function buildCats(){
  const box = $('#sk-cats'); box.innerHTML = '';
  const lun = S.layout === 'lunar' && LUNAR.data;
  const cats = lun ? LUNAR.data.categories : ((S.data && S.data.categories) || {});
  Object.keys(cats).forEach(id => {
    const n = lun ? LUNAR.events.filter(x => x.cat === id).length : S.passes.filter(p => p.cat === id).length;
    const b = document.createElement('button'); b.type = 'button'; b.className = 'sk-chip' + (S.hiddenCats.has(id) ? ' off' : '');
    b.innerHTML = '<span class="sk-dot" style="background:' + cats[id].color + '"></span>' + catLabel(id, cats[id].label) + ' <i>' + n + '</i>';
    b.addEventListener('click', () => { if(S.hiddenCats.has(id)) S.hiddenCats.delete(id); else S.hiddenCats.add(id); buildCats(); S.dirty = true; updateListStates(); showDetail(); });
    box.appendChild(b);
  });
}

/* ── 動畫輸出（GIF：內建編碼器；MP4/WebM：MediaRecorder）───────────────────── */
function download(blob, name){
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
}
function stamp(){ return new Date(S.simMs + 8 * 3600e3).toISOString().slice(0, 16).replace(/[-:T]/g, ''); }
function exportSize(){
  const H = +$('#sk-ex-size').value, lay = S.layout;
  return {H, W: lay === 'both' ? Math.round(H * 1.9) : (lay === 'lunar' ? Math.round(H * 1.6) : H)};
}
function frameCanvas(W, H){ const c = document.createElement('canvas'); c.width = W; c.height = H; return c; }
async function exportAnim(){
  if(S.exporting || !winSpan()) return;
  const fmt = $('#sk-ex-fmt').value, simMin = +$('#sk-ex-sim').value, outSec = +$('#sk-ex-out').value, fps = +$('#sk-ex-fps').value;
  const {H, W} = exportSize(), info = $('#sk-ex-info'), N = Math.max(2, Math.round(outSec * fps));
  let startMs = S.simMs, spanMs = simMin * 60e3;
  if(S.layout === 'lunar'){                          // 凌月版面：輸出所選事件（前後各數秒）的慢動作
    const ev = lunarSel(S.simMs);
    if(ev){ const h = lunarHalf(ev) + 4; startMs = ev.tms - h * 1000; spanMs = 2 * h * 1000; }
  }
  const wEnd = winStart() + winSpan();
  if(startMs + spanMs > wEnd) startMs = Math.max(winStart(), wEnd - spanMs);
  spanMs = Math.min(spanMs, wEnd - startMs);
  const cv = frameCanvas(W, H), ctx = cv.getContext('2d', {willReadFrequently: fmt === 'gif'});
  const at = i => startMs + spanMs * i / (N - 1);
  const opt = {layout: S.layout, forceSide: true, u: Math.max(0.8, H / 760)};
  S.exporting = true; $('#sk-ex-go').disabled = true;
  if(S.layout !== 'sky' && S.layout !== 'lunar' && S.bordersState === 'idle') await ensureBorders();
  try{
    if(fmt === 'gif'){
      const enc = new GifEncoder(W, H, 100 / fps);
      info.textContent = st('ex_run', {i: 0, n: N});
      enc.buildPalette([0, N >> 2, N >> 1, (3 * N) >> 2, N - 1].map(i => { render(ctx, W, H, at(i), opt); return ctx.getImageData(0, 0, W, H).data; }));
      for(let i = 0; i < N; i++){
        render(ctx, W, H, at(i), opt);
        enc.addFrame(ctx.getImageData(0, 0, W, H).data);
        if(i % 3 === 0){ info.textContent = st('ex_run', {i: i + 1, n: N}); await new Promise(r => setTimeout(r, 0)); }
      }
      const blob = enc.finish(), name = 'taipei_sky_' + stamp() + '.gif';
      download(blob, name); info.textContent = st('ex_done', {name, kb: Math.round(blob.size / 1024)});
    } else {
      const types = fmt === 'mp4' ? ['video/mp4;codecs=avc1.42E01E', 'video/mp4'] : ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
      const mime = window.MediaRecorder && types.find(m => MediaRecorder.isTypeSupported(m));
      if(!mime) throw new Error(st('ex_nomr'));
      const rec = new MediaRecorder(cv.captureStream(fps), {mimeType: mime, videoBitsPerSecond: 6e6}), chunks = [];
      rec.ondataavailable = e => { if(e.data.size) chunks.push(e.data); };
      const done = new Promise(res => { rec.onstop = res; });
      render(ctx, W, H, at(0), opt); rec.start(250);
      await new Promise(res => {
        let i = 0;
        const timer = setInterval(() => {
          render(ctx, W, H, at(Math.min(i, N - 1)), opt);
          info.textContent = st('ex_run', {i: Math.min(i + 1, N), n: N});
          if(++i >= N){ clearInterval(timer); setTimeout(res, 300); }
        }, 1000 / fps);
      });
      rec.stop(); await done;
      const ext = mime.startsWith('video/mp4') ? 'mp4' : 'webm', name = 'taipei_sky_' + stamp() + '.' + ext;
      const blob = new Blob(chunks, {type: mime.split(';')[0]});
      download(blob, name); info.textContent = st('ex_done', {name, kb: Math.round(blob.size / 1024)});
    }
  }catch(e){
    info.textContent = st('ex_fail', {msg: e.message});
  }finally{
    S.exporting = false; $('#sk-ex-go').disabled = false; S.dirty = true;
  }
}
function snapshotPng(){
  const {H, W} = exportSize(), c = frameCanvas(W, H), ctx = c.getContext('2d');
  render(ctx, W, H, S.simMs, {layout: S.layout, forceSide: true, u: Math.max(0.8, H / 760)});
  c.toBlob(b => download(b, 'taipei_sky_' + stamp() + '.png'), 'image/png');
}

/* ── UI ───────────────────────────────────────────────────────────────────── */
const SPEEDS = [0.25, 1, 5, 10, 30, 60, 120, 300, 600];
const LAYOUTS = ['both', 'sky', 'ground'];
function setLayout(l){
  const prev = S.layout;
  S.layout = l;
  const sel = $('#sk-layout'); if(sel) sel.value = l;
  if(l !== 'sky' && l !== 'lunar') ensureBorders();
  const lo = $('#sk-lunar-opts'); if(lo) lo.style.display = l === 'lunar' ? 'block' : 'none';
  const h = $('#sk-sec-title'); if(h){ h.dataset.sk = l === 'lunar' ? 'sec_lunar' : 'sec_passes'; h.textContent = st(h.dataset.sk); }
  if(l === 'lunar'){
    if(!LUNAR.data && !LUNAR.loading) loadLunar();
    else if(LUNAR.data){
      if(S.simMs < LUNAR.t0 || S.simMs > LUNAR.t0 + LUNAR.span) S.simMs = clamp(Date.now(), LUNAR.t0, LUNAR.t0 + LUNAR.span);
      setMsg(LUNAR.events.length ? '' : st('lunar_none'));
    } else setMsg(st('lunar_loading'));
  } else if(prev === 'lunar'){
    if(S.span && (S.simMs < S.t0 || S.simMs > S.t0 + S.span)) S.simMs = clamp(Date.now(), S.t0, S.t0 + S.span);
    setMsg(S.data && !S.passes.length ? st('no_passes') : '');
  }
  buildCats(); refreshList(); syncSlider();
  updateCycleBtn(); S.dirty = true;
}
function cycleLayout(){ setLayout(LAYOUTS[(LAYOUTS.indexOf(S.layout) + 1) % LAYOUTS.length]); S.lastCycle = performance.now(); }
function updateCycleBtn(){
  const b = $('#sk-cycle'); if(b) b.textContent = '⟳ ' + st('view_cycle') + '：' + st('layout_' + S.layout);
}
function syncPlayBtn(){ const b = $('#sk-play'); if(b) b.textContent = S.playing ? '❚❚ ' + st('pause') : '▶ ' + st('play'); }
function buildUI(){
  ROOT.innerHTML =
    '<div id="sk-stage"><div id="sk-cvwrap"><canvas id="sk-canvas"></canvas><div id="sk-msg"></div></div>' +
    '<div id="sk-ctl">' +
      '<button type="button" id="sk-play"></button>' +
      '<input type="range" id="sk-slider" min="0" max="7200" step="1" value="0">' +
      '<span id="sk-time">—</span>' +
      '<label><span data-sk="speed"></span> <select id="sk-speed">' + SPEEDS.map(v => '<option value="' + v + '">' + v + '×</option>').join('') + '</select></label>' +
      '<label><input type="checkbox" id="sk-loop" checked> <span data-sk="loop"></span></label>' +
      '<button type="button" id="sk-cycle" class="sk-btn sk-primary"></button>' +
      '<button type="button" id="sk-now" class="sk-btn"></button>' +
    '</div></div>' +
    '<div id="sk-side">' +
      '<div class="sk-sec"><h3 data-sk="sec_show"></h3>' +
        '<div class="sk-row"><span data-sk="layout"></span> <select id="sk-layout"><option value="both" data-sk="layout_both"></option><option value="sky" data-sk="layout_sky"></option><option value="ground" data-sk="layout_ground"></option><option value="lunar" data-sk="layout_lunar"></option></select></div>' +
        '<div id="sk-lunar-opts" style="display:none"><div class="sk-row"><span data-sk="lunar_hours"></span> <select id="sk-lhours"><option value="12">12</option><option value="24" selected>24</option><option value="48">48</option></select> <span data-sk="h_unit"></span> ' +
        '<span data-sk="lunar_kind"></span> <select id="sk-lkind"><option value="all" data-sk="lf_all"></option><option value="transit" data-sk="lf_transit"></option></select></div>' +
        '<div class="sk-row"><label><input type="checkbox" id="sk-lreplay" checked> <span data-sk="ln_replay"></span></label></div></div>' +
        '<div class="sk-row"><label><input type="checkbox" id="sk-auto"> <span data-sk="auto_cycle"></span></label> <select id="sk-autosec"><option value="5">5</option><option value="8" selected>8</option><option value="15">15</option><option value="30">30</option></select></div>' +
        '<div class="sk-row"><span data-sk="range"></span> <select id="sk-range"><option value="2000">2000 km</option><option value="2500">2500 km</option></select></div>' +
        '<div class="sk-row"><span data-sk="hours"></span> <select id="sk-hours"><option value="1">1</option><option value="2" selected>2</option><option value="3">3</option><option value="6">6</option></select> <span data-sk="h_unit"></span> ' +
        '<button type="button" id="sk-reload" class="sk-btn"></button></div>' +
        '<div class="sk-row"><span data-sk="start_at"></span> <input type="datetime-local" id="sk-start"></div>' +
        '<div class="sk-checks">' +
          [['stars', 'o_stars'], ['starNames', 'o_starnames'], ['planets', 'o_planets'], ['ecliptic', 'o_ecliptic'], ['arrows', 'o_arrows'],
           ['names', 'o_names'], ['allTracks', 'o_all'], ['eastLeft', 'o_eastleft']].map(([k, l]) =>
            '<label><input type="checkbox" data-opt="' + k + '"' + (S[k] ? ' checked' : '') + '> <span data-sk="' + l + '"></span></label>').join('') +
        '</div></div>' +
      '<div class="sk-sec"><h3 data-sk="sec_cats"></h3><div id="sk-cats"></div></div>' +
      '<div class="sk-sec sk-grow"><h3 id="sk-sec-title" data-sk="sec_passes"></h3><div id="sk-detail"></div><div id="sk-list"></div></div>' +
      '<div class="sk-sec"><h3 data-sk="sec_export"></h3>' +
        '<div class="sk-grid">' +
          '<span data-sk="ex_fmt"></span><select id="sk-ex-fmt"><option value="gif">GIF</option><option value="mp4">MP4</option><option value="webm">WebM</option></select>' +
          '<span data-sk="ex_sim"></span><select id="sk-ex-sim"><option value="10">10</option><option value="20">20</option><option value="30" selected>30</option><option value="60">60</option><option value="120">120</option></select>' +
          '<span data-sk="ex_out"></span><select id="sk-ex-out"><option value="8">8</option><option value="12" selected>12</option><option value="20">20</option><option value="30">30</option></select>' +
          '<span data-sk="ex_fps"></span><select id="sk-ex-fps"><option value="10">10</option><option value="15" selected>15</option><option value="24">24</option><option value="30">30</option></select>' +
          '<span data-sk="ex_size"></span><select id="sk-ex-size"><option value="480">480 px</option><option value="640" selected>640 px</option><option value="720">720 px</option><option value="1080">1080 px</option></select>' +
        '</div>' +
        '<div class="sk-row"><button type="button" id="sk-ex-go" class="sk-btn sk-primary"></button> <button type="button" id="sk-ex-png" class="sk-btn"></button></div>' +
        '<div id="sk-ex-info"></div></div>' +
    '</div>';
  CV = $('#sk-canvas'); CTX = CV.getContext('2d');
  $('#sk-speed').value = String(S.speed);
  const mrOk = t => !!(window.MediaRecorder && MediaRecorder.isTypeSupported(t));
  [['mp4', 'video/mp4'], ['webm', 'video/webm']].forEach(([v, m]) => {
    if(!mrOk(m)){ const o = $('#sk-ex-fmt option[value="' + v + '"]'); if(o) o.disabled = true; }
  });
  $('#sk-play').addEventListener('click', () => { S.playing = !S.playing; syncPlayBtn(); });
  $('#sk-slider').addEventListener('input', e => { S.simMs = winStart() + (+e.target.value) * 1000; S.dirty = true; });
  $('#sk-lhours').addEventListener('change', e => { LUNAR.hours = +e.target.value; LUNAR.data = null; LUNAR.events = []; LUNAR.selKey = null; if(S.layout === 'lunar') loadLunar(); });
  $('#sk-lkind').addEventListener('change', e => { LUNAR.kind = e.target.value; buildCats(); updateListStates(); showDetail(); S.dirty = true; });
  $('#sk-lreplay').addEventListener('change', e => { LUNAR.replay = e.target.checked; });
  $('#sk-speed').addEventListener('change', e => { S.speed = +e.target.value; });
  $('#sk-loop').addEventListener('change', e => { S.loop = e.target.checked; });
  $('#sk-now').addEventListener('click', reloadNow);
  $('#sk-reload').addEventListener('click', () => { S.hours = +$('#sk-hours').value; const v = $('#sk-start').value;
    if(v){ const ms = Date.parse(v + ':00+08:00'); S.simMs = ms + PRE_MS; load(ms); if(S.layout === 'lunar') loadLunar(ms); } else reloadNow(); });
  $('#sk-hours').addEventListener('change', () => { S.hours = +$('#sk-hours').value; });
  $('#sk-layout').addEventListener('change', e => setLayout(e.target.value));
  $('#sk-cycle').addEventListener('click', cycleLayout);
  $('#sk-auto').addEventListener('change', e => { S.autoCycle = e.target.checked; S.lastCycle = performance.now(); });
  $('#sk-autosec').addEventListener('change', e => { S.autoSec = +e.target.value; });
  document.addEventListener('keydown', e => {
    if(VIEW === 'sky' && (e.key === 'v' || e.key === 'V') && !/INPUT|SELECT|TEXTAREA/.test((e.target.tagName || ''))) cycleLayout();
  });
  $('#sk-range').addEventListener('change', e => { S.rangeKm = +e.target.value; S.dirty = true; });
  ROOT.querySelectorAll('[data-opt]').forEach(cb => cb.addEventListener('change', () => { S[cb.dataset.opt] = cb.checked; S.cel = {ms: null, v: null}; S.dirty = true; }));
  $('#sk-ex-go').addEventListener('click', exportAnim);
  $('#sk-ex-png').addEventListener('click', snapshotPng);
  CV.addEventListener('click', e => {
    const r = CV.getBoundingClientRect(), dpr = CV.width / r.width, x = (e.clientX - r.left) * dpr, y = (e.clientY - r.top) * dpr;
    let best = null, bd = 16 * dpr;
    S.hit.forEach(h => { const d = Math.hypot(h.x - x, h.y - y); if(d < bd){ bd = d; best = h.p; } });
    select(best, false);
  });
  CV.addEventListener('mousemove', e => {
    const r = CV.getBoundingClientRect(), dpr = CV.width / r.width, x = (e.clientX - r.left) * dpr, y = (e.clientY - r.top) * dpr;
    CV.style.cursor = S.hit.some(h => Math.hypot(h.x - x, h.y - y) < 14 * dpr) ? 'pointer' : 'default';
  });
  if('ResizeObserver' in window) new ResizeObserver(resize).observe(CV.parentElement);
  window.addEventListener('resize', resize);
  applyTexts();
}
function applyTexts(){
  ROOT.querySelectorAll('[data-sk]').forEach(el => { el.textContent = st(el.dataset.sk); });
  $('#sk-now').textContent = '⟳ ' + st('now'); updateCycleBtn();
  [...$('#sk-autosec').options].forEach(o => { o.textContent = st('auto_sec', {n: o.value}); }); $('#sk-reload').textContent = st('reload');
  $('#sk-ex-go').textContent = '⏺ ' + st('ex_go'); $('#sk-ex-png').textContent = st('ex_png');
  const sim = $('#sk-ex-sim'), out = $('#sk-ex-out');
  [...sim.options].forEach(o => { o.textContent = st('ex_min', {n: o.value}); });
  [...out.options].forEach(o => { o.textContent = st('ex_sec', {n: o.value}); });
  syncPlayBtn();
}

/* ── 對外介面 ─────────────────────────────────────────────────────────────── */
function setView(v){
  VIEW = v === 'map' ? 'map' : 'sky';
  document.body.classList.toggle('mode-sky', VIEW === 'sky');
  document.body.classList.toggle('mode-map', VIEW === 'map');
  try{ localStorage.setItem('taipei_view', VIEW); }catch(e){ /* noop */ }
  document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === VIEW));
  if(VIEW === 'map' && window.loadMapOnce) window.loadMapOnce();
  if(window.taipeiMapVisible) window.taipeiMapVisible(VIEW === 'map');
  if(VIEW === 'sky'){ setTimeout(resize, 0); S.dirty = true; }
}
function init(){
  ROOT = document.getElementById('sky-view');
  if(!ROOT) return;
  buildUI();
  READY = true;
  let v = 'sky';
  try{ v = new URLSearchParams(location.search).get('view') || localStorage.getItem('taipei_view') || 'sky'; }catch(e){ /* noop */ }
  setView(v);
  ensureBorders();
  reloadNow();
  requestAnimationFrame(frame);
}
window.TaipeiSky = {
  init, setView,
  onLang(){ if(!READY) return; applyTexts(); buildCats(); refreshList(); updateListStates(); S.dirty = true; },
  _state: S, _render: render,
};
})();
