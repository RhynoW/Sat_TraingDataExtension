'use strict';
/* 單顆衛星 2D 地面軌跡頁（/track?norad=）：
   - 資料：/api/sat_tle 取 TLE 兩行，其餘全在瀏覽器端以 satellite.js（SGP4）計算
   - 地圖：地面軌跡（過去半圈＋未來一圈半，跨換日線切段）、晝夜區、可視範圍（仰角 0° 圈）、觀測者
   - 側欄：即時狀態（每秒）、基本資料（軌道根數由 TLE 推得）、未來 3 天過境 */

// ── 三語字典（中／英／日）──────────────────────────────────────────────────
const I18N = {
  zh: {
    doc_title: '2D 地面軌跡', page_title: '2D 地面軌跡',
    subtitle: '地面投影、晝夜線、可視範圍與即時資料（瀏覽器端 SGP4）',
    q_placeholder: 'NORAD ID', nav_orbit: '軌道要素歷史', nav_home: '返回主頁',
    opt_track: '地面軌跡', opt_foot: '可視範圍', opt_night: '晝夜', opt_follow: '地圖跟隨衛星',
    opt_hint: '點地圖可設定觀測者位置',
    status_loading: '載入中…', status_need: '請在右上角輸入 NORAD ID', status_fail: '載入失敗：{error}',
    status_decayed: 'SGP4 外推失敗（TLE 過舊或已再入）',
    h_live: '即時狀態', h_basic: '衛星基本資料', h_passes: '未來過境（3 天，仰角 > 10°）', h_observer: '觀測者',
    obs_note: '預設使用瀏覽器定位；未授權時為臺北。點地圖可改變位置。',
    tle_note: '位置以 SGP4 由最新 TLE 外推，精度約數公里，TLE 越舊誤差越大。',
    k_local: '本地時間', k_utc: 'UTC', k_lat: '緯度', k_lon: '經度', k_alt: '高度',
    k_speed: '速度', k_az: '方位角', k_el: '仰角', k_range: '距離', k_ra: '赤經（站心）', k_dec: '赤緯（站心）',
    k_lst: '本地恆星時',
    k_norad: 'NORAD', k_country: '國家', k_purpose: '用途', k_era: '年代', k_const: '星座',
    k_epoch: 'TLE 曆元', k_age: 'TLE 齡', k_period: '軌道週期', k_inc: '傾角', k_ecc: '離心率',
    k_perigee: '近地點高度', k_apogee: '遠地點高度', k_raan: '升交點赤經',
    k_obs_lat: '緯度', k_obs_lon: '經度', k_obs_src: '來源', k_sun_el: '太陽仰角',
    src_geo: '瀏覽器定位', src_default: '預設（臺北）', src_click: '地圖點選',
    lit: '☀ 衛星位於日照區', ecl: '🌑 衛星位於地影中',
    unit_min: '分', unit_day: '天', unit_hr: '小時',
    p_rise: '升起', p_max: '最高', p_set: '落下', p_dur: '時長',
    p_none: '3 天內無仰角 > 10° 的過境', p_geo: '近地球同步軌道：相對觀測者幾乎不動，仰角 {el}°',
    p_vis: '黃字＝可目視（衛星受日照且觀測者處於天黑）',
    pop_obs: '觀測者', pop_now: '目前位置',
  },
  en: {
    doc_title: '2D Ground Track', page_title: '2D Ground Track',
    subtitle: 'Ground track, day/night, visibility footprint and live data (in-browser SGP4)',
    q_placeholder: 'NORAD ID', nav_orbit: 'Orbit history', nav_home: 'Home',
    opt_track: 'Ground track', opt_foot: 'Footprint', opt_night: 'Day/night', opt_follow: 'Follow satellite',
    opt_hint: 'Click the map to set the observer',
    status_loading: 'Loading…', status_need: 'Enter a NORAD ID at the top right', status_fail: 'Load failed: {error}',
    status_decayed: 'SGP4 propagation failed (TLE too old or object re-entered)',
    h_live: 'Live state', h_basic: 'Satellite info', h_passes: 'Upcoming passes (3 days, elevation > 10°)', h_observer: 'Observer',
    obs_note: 'Uses browser geolocation; falls back to Taipei. Click the map to move it.',
    tle_note: 'Position is SGP4-propagated from the latest TLE; accuracy is a few km and degrades with TLE age.',
    k_local: 'Local time', k_utc: 'UTC', k_lat: 'Latitude', k_lon: 'Longitude', k_alt: 'Altitude',
    k_speed: 'Speed', k_az: 'Azimuth', k_el: 'Elevation', k_range: 'Range', k_ra: 'Right ascension (topo)', k_dec: 'Declination (topo)',
    k_lst: 'Local sidereal time',
    k_norad: 'NORAD', k_country: 'Country', k_purpose: 'Purpose', k_era: 'Era', k_const: 'Constellation',
    k_epoch: 'TLE epoch', k_age: 'TLE age', k_period: 'Period', k_inc: 'Inclination', k_ecc: 'Eccentricity',
    k_perigee: 'Perigee altitude', k_apogee: 'Apogee altitude', k_raan: 'RAAN',
    k_obs_lat: 'Latitude', k_obs_lon: 'Longitude', k_obs_src: 'Source', k_sun_el: 'Sun elevation',
    src_geo: 'Browser geolocation', src_default: 'Default (Taipei)', src_click: 'Map click',
    lit: '☀ Satellite is in sunlight', ecl: '🌑 Satellite is in Earth\'s shadow',
    unit_min: 'min', unit_day: 'd', unit_hr: 'h',
    p_rise: 'Rise', p_max: 'Max', p_set: 'Set', p_dur: 'Dur.',
    p_none: 'No passes above 10° in the next 3 days', p_geo: 'Near-geostationary: almost fixed for the observer, elevation {el}°',
    p_vis: 'Yellow = visible to the eye (satellite sunlit, observer in darkness)',
    pop_obs: 'Observer', pop_now: 'Current position',
  },
  ja: {
    doc_title: '2D 地上軌跡', page_title: '2D 地上軌跡',
    subtitle: '地上軌跡・昼夜境界・可視範囲・リアルタイムデータ（ブラウザ内 SGP4）',
    q_placeholder: 'NORAD ID', nav_orbit: '軌道要素履歴', nav_home: 'ホームへ',
    opt_track: '地上軌跡', opt_foot: '可視範囲', opt_night: '昼夜', opt_follow: '衛星を追従',
    opt_hint: '地図をクリックして観測者位置を設定',
    status_loading: '読み込み中…', status_need: '右上に NORAD ID を入力してください', status_fail: '読み込み失敗：{error}',
    status_decayed: 'SGP4 伝播に失敗しました（TLE が古いか再突入済み）',
    h_live: 'リアルタイム状態', h_basic: '衛星基本情報', h_passes: '今後のパス（3 日間、仰角 > 10°）', h_observer: '観測者',
    obs_note: 'ブラウザの位置情報を使用。許可がない場合は台北。地図クリックで変更できます。',
    tle_note: '位置は最新 TLE から SGP4 で外挿。精度は数 km 程度で、TLE が古いほど誤差が増えます。',
    k_local: '現地時刻', k_utc: 'UTC', k_lat: '緯度', k_lon: '経度', k_alt: '高度',
    k_speed: '速度', k_az: '方位角', k_el: '仰角', k_range: '距離', k_ra: '赤経（測心）', k_dec: '赤緯（測心）',
    k_lst: '地方恒星時',
    k_norad: 'NORAD', k_country: '国', k_purpose: '用途', k_era: '年代', k_const: 'コンステレーション',
    k_epoch: 'TLE エポック', k_age: 'TLE 経過', k_period: '軌道周期', k_inc: '軌道傾斜角', k_ecc: '離心率',
    k_perigee: '近地点高度', k_apogee: '遠地点高度', k_raan: '昇交点赤経',
    k_obs_lat: '緯度', k_obs_lon: '経度', k_obs_src: '取得元', k_sun_el: '太陽高度',
    src_geo: 'ブラウザ位置情報', src_default: '既定（台北）', src_click: '地図クリック',
    lit: '☀ 衛星は日照中', ecl: '🌑 衛星は地球の影の中',
    unit_min: '分', unit_day: '日', unit_hr: '時間',
    p_rise: '出', p_max: '最大', p_set: '入', p_dur: '時間',
    p_none: '3 日以内に仰角 10° を超えるパスはありません', p_geo: '静止軌道付近：観測者から見てほぼ固定、仰角 {el}°',
    p_vis: '黄色＝肉眼で見える可能性（衛星が日照中かつ観測地が夜）',
    pop_obs: '観測者', pop_now: '現在位置',
  },
};
const LOCALE = {zh: 'zh-TW', en: 'en-US', ja: 'ja-JP'};
let LANG = 'zh';
try{ LANG = localStorage.getItem('track_lang') || 'zh'; }catch(e){}
if(!I18N[LANG]) LANG = 'zh';
function t(k){ const d = I18N[LANG]; return (k in d) ? d[k] : (I18N.zh[k] !== undefined ? I18N.zh[k] : k); }
function tpl(k, v){ let s = t(k); Object.keys(v || {}).forEach(x => { s = s.replace('{' + x + '}', v[x]); }); return s; }
function $(id){ return document.getElementById(id); }

// ── 常數與小工具 ──
const RE = 6378.137, MU = 398600.4418, AU = 149597870.7;
const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const DEFAULT_OBS = {lat: 25.0330, lon: 121.5654};    // 臺北
const PASS_MIN_EL = 10;                               // 過境表門檻（度）
const wrap180 = x => ((x + 540) % 360) - 180;
const fmtDeg = (x, d) => x.toFixed(d == null ? 2 : d) + '°';
function hms(hours){
  hours = ((hours % 24) + 24) % 24;
  const h = Math.floor(hours), m = Math.floor((hours - h) * 60), s = Math.floor(((hours - h) * 60 - m) * 60);
  return h + 'h ' + String(m).padStart(2, '0') + 'm ' + String(s).padStart(2, '0') + 's';
}
function dms(deg){
  const sg = deg < 0 ? '−' : '', a = Math.abs(deg);
  const d = Math.floor(a), m = Math.floor((a - d) * 60), s = Math.round(((a - d) * 60 - m) * 60);
  return sg + d + '° ' + String(m).padStart(2, '0') + '′ ' + String(s).padStart(2, '0') + '″';
}
function compass(az){ return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(az / 45) % 8]; }
const fmtTime = (d, opt) => d.toLocaleTimeString(LOCALE[LANG], Object.assign({hour12: false}, opt || {}));
const fmtUtc = d => d.toISOString().slice(11, 19);

// ── 狀態 ──
let SAT = null;          // /api/sat_tle 回應
let REC = null;          // satrec
let PERIOD_MIN = 0;
let OBS = Object.assign({src: 'src_default'}, DEFAULT_OBS);
let map, layTrackPast, layTrackFut, layFoot, layNight, satMarker, obsMarker;
let PASSES = null;

// ── 太陽（低精度天文年曆公式，誤差 ~0.01°，足供晝夜/日照判斷）──
function sunEci(date){
  const n = date.getTime() / 86400000 + 2440587.5 - 2451545.0;
  const L = (280.460 + 0.9856474 * n) % 360;
  const g = ((357.528 + 0.9856003 * n) % 360) * D2R;
  const lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * D2R;
  const eps = (23.439 - 0.0000004 * n) * D2R;
  const r = (1.00014 - 0.01671 * Math.cos(g) - 0.00014 * Math.cos(2 * g)) * AU;
  return {x: r * Math.cos(lam), y: r * Math.cos(eps) * Math.sin(lam), z: r * Math.sin(eps) * Math.sin(lam)};
}
// 圓柱地影：衛星在太陽背面且與日地軸距離 < 地球半徑 → 地影中
function isSunlit(p, sun){
  const sr = Math.hypot(sun.x, sun.y, sun.z), sx = sun.x / sr, sy = sun.y / sr, sz = sun.z / sr;
  const proj = p.x * sx + p.y * sy + p.z * sz;
  if(proj > 0) return true;
  return Math.hypot(p.x - proj * sx, p.y - proj * sy, p.z - proj * sz) > RE;
}

function obsGd(){ return {latitude: OBS.lat * D2R, longitude: OBS.lon * D2R, height: 0}; }

/* 某時刻完整狀態：星下點、速度、站心方位/仰角/距離、站心赤經赤緯、日照、太陽仰角 */
function stateAt(date, full){
  const pv = satellite.propagate(REC, date);
  if(!pv || !pv.position || isNaN(pv.position.x)) return null;
  const gmst = satellite.gstime(date);
  const gd = satellite.eciToGeodetic(pv.position, gmst);
  const ecf = satellite.eciToEcf(pv.position, gmst);
  const og = obsGd();
  const la = satellite.ecfToLookAngles(og, ecf);
  const st = {
    date, gmst, pos: pv.position,
    lat: gd.latitude * R2D, lon: wrap180(gd.longitude * R2D), alt: gd.height,
    az: la.azimuth * R2D, el: la.elevation * R2D, range: la.rangeSat,
  };
  if(!full) return st;
  const v = pv.velocity;
  st.speed = Math.hypot(v.x, v.y, v.z);
  const oe = satellite.ecfToEci(satellite.geodeticToEcf(og), gmst);
  const dx = pv.position.x - oe.x, dy = pv.position.y - oe.y, dz = pv.position.z - oe.z;
  st.ra = ((Math.atan2(dy, dx) * R2D) + 360) % 360;
  st.dec = Math.asin(dz / Math.hypot(dx, dy, dz)) * R2D;
  st.lst = ((gmst + og.longitude) * R2D / 15);
  const sun = sunEci(date);
  st.sunlit = isSunlit(pv.position, sun);
  st.sunEl = satellite.ecfToLookAngles(og, satellite.eciToEcf(sun, gmst)).elevation * R2D;
  return st;
}

// ── 地圖圖層 ──
function initMap(){
  map = L.map('map', {worldCopyJump: false, minZoom: 1, zoomSnap: 0.5}).setView([20, 120], 2);
  // 底圖皆免金鑰（CARTO 已改需金鑰會出浮水印，故不用）；預設 Esri 深灰＋地名參考層
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const dark = L.layerGroup([
    L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {maxZoom: 16, attribution: 'Tiles &copy; Esri'}),
    L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {maxZoom: 16}),
  ]).addTo(map);
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
  const img = L.tileLayer(ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom: 17, attribution: 'Imagery &copy; Esri'});
  L.control.layers({'Esri Dark Gray': dark, 'OpenStreetMap': osm, 'Esri Imagery': img}, null, {position: 'topright'}).addTo(map);
  layNight = L.layerGroup().addTo(map);
  layFoot = L.layerGroup().addTo(map);
  layTrackPast = L.layerGroup().addTo(map);
  layTrackFut = L.layerGroup().addTo(map);
  satMarker = L.marker([0, 0], {icon: L.divIcon({className: '', html: '<div class="sat-ico"></div>', iconSize: [18, 18]}), zIndexOffset: 1000});
  obsMarker = L.marker([OBS.lat, OBS.lon], {icon: L.divIcon({className: '', html: '<div class="obs-ico"></div>', iconSize: [12, 12]})}).addTo(map);
  map.on('click', e => setObserver(e.latlng.lat, wrap180(e.latlng.lng), 'src_click'));
  [['optTrack', [layTrackPast, layTrackFut]], ['optFoot', [layFoot]], ['optNight', [layNight]]].forEach(([id, ls]) => {
    $(id).addEventListener('change', function(){ ls.forEach(l => this.checked ? l.addTo(map) : l.remove()); });
  });
}

/* 地圖預設以衛星經度置中，畫面常跨越 ±180°；各圖層於三份世界副本（−360/0/+360）各畫一次 */
const COPIES = [-360, 0, 360];
function addWrapped(layer, ctor, pts, opt){
  COPIES.forEach(k => ctor(pts.map(p => [p[0], p[1] + k]), opt).addTo(layer));
}

/* 依經度跳躍（>180°）切成多段，避免橫跨地圖的長線 */
function splitAntimeridian(pts){
  const segs = [[]];
  pts.forEach((p, i) => {
    if(i && Math.abs(p[1] - pts[i - 1][1]) > 180) segs.push([]);
    segs[segs.length - 1].push(p);
  });
  return segs.filter(s => s.length > 1);
}

function drawTrack(now){
  layTrackPast.clearLayers(); layTrackFut.clearLayers();
  const stepS = Math.max(20, PERIOD_MIN * 60 / 240);
  const past = [], fut = [];
  for(let s = -0.5 * PERIOD_MIN * 60; s <= 1.5 * PERIOD_MIN * 60; s += stepS){
    const st = stateAt(new Date(now.getTime() + s * 1000));
    if(!st) continue;
    (s <= 0 ? past : fut).push([st.lat, st.lon]);
  }
  const cur = stateAt(now);
  if(cur){ past.push([cur.lat, cur.lon]); fut.unshift([cur.lat, cur.lon]); }
  splitAntimeridian(past).forEach(sg => addWrapped(layTrackPast, L.polyline, sg, {color: '#F2A73B', weight: 1.6, opacity: 0.45, dashArray: '4 5', interactive: false}));
  splitAntimeridian(fut).forEach(sg => addWrapped(layTrackFut, L.polyline, sg, {color: '#F2A73B', weight: 2.2, opacity: 0.95, interactive: false}));
}

/* 夜半球：晝夜線緯度 φ(λ) = atan(−cos(λ−λsun) / tan δsun)，往背日極閉合 */
function drawNight(now){
  layNight.clearLayers();
  const sun = sunEci(now), gmst = satellite.gstime(now);
  const dec = Math.atan2(sun.z, Math.hypot(sun.x, sun.y));
  const sunLon = wrap180((Math.atan2(sun.y, sun.x) - gmst) * R2D);
  const td = Math.abs(Math.tan(dec)) < 1e-6 ? 1e-6 * Math.sign(dec || 1) : Math.tan(dec);
  const pts = [];
  for(let lon = -180; lon <= 180; lon += 2){
    const lat = Math.atan(-Math.cos((lon - sunLon) * D2R) / td) * R2D;
    pts.push([Math.max(-85, Math.min(85, lat)), lon]);
  }
  const pole = dec > 0 ? -85 : 85;
  pts.push([pole, 180], [pole, -180]);
  addWrapped(layNight, L.polygon, pts, {stroke: false, fillColor: '#000814', fillOpacity: 0.42, interactive: false});
  COPIES.forEach(k => L.circleMarker([dec * R2D, sunLon + k], {radius: 7, color: '#f2cc60', weight: 2, fillColor: '#f2cc60', fillOpacity: 0.6, interactive: false}).addTo(layNight));
}

/* 可視範圍：地心角 λ = acos(Re/(Re+h)) 之球面小圓；經度展開，含極點時沿極緯閉合 */
function drawFootprint(st){
  layFoot.clearLayers();
  const lam = Math.acos(RE / (RE + Math.max(st.alt, 1)));
  const la1 = st.lat * D2R, lo1 = st.lon * D2R, pts = [];
  let prev = null;
  for(let b = 0; b <= 360; b += 3){
    const br = b * D2R;
    const la2 = Math.asin(Math.sin(la1) * Math.cos(lam) + Math.cos(la1) * Math.sin(lam) * Math.cos(br));
    let lo2 = (lo1 + Math.atan2(Math.sin(br) * Math.sin(lam) * Math.cos(la1), Math.cos(lam) - Math.sin(la1) * Math.sin(la2))) * R2D;
    if(prev != null){ while(lo2 - prev > 180) lo2 -= 360; while(lo2 - prev < -180) lo2 += 360; }
    prev = lo2;
    pts.push([Math.max(-85, Math.min(85, la2 * R2D)), lo2]);
  }
  const span = pts[pts.length - 1][1] - pts[0][1];
  if(Math.abs(span) > 180){                         // 繞極一圈：補極緯兩角閉合
    const pl = st.lat > 0 ? 85 : -85;
    pts.push([pl, pts[pts.length - 1][1]], [pl, pts[0][1]]);
  }
  addWrapped(layFoot, L.polygon, pts, {color: '#35C6F4', weight: 1.2, fillColor: '#35C6F4', fillOpacity: 0.08, interactive: false});
}

/* 取與地圖中心經度最接近的副本經度（標記只畫一個） */
function nearCenter(lon){
  const c = map.getCenter().lng;
  return lon + Math.round((c - lon) / 360) * 360;
}

// ── 側欄 ──
function kv(rows){ return rows.map(r => '<tr><td>' + r[0] + '</td><td' + (r[2] ? ' class="' + r[2] + '"' : '') + '>' + r[1] + '</td></tr>').join(''); }

function renderLive(st){
  $('liveTbl').innerHTML = kv([
    [t('k_local'), fmtTime(st.date)],
    [t('k_utc'), fmtUtc(st.date)],
    [t('k_lat'), fmtDeg(st.lat)],
    [t('k_lon'), fmtDeg(st.lon)],
    [t('k_alt'), st.alt.toFixed(1) + ' km'],
    [t('k_speed'), st.speed.toFixed(2) + ' km/s'],
    [t('k_az'), st.az.toFixed(1) + '° ' + compass(st.az)],
    [t('k_el'), st.el.toFixed(1) + '°', st.el > 0 ? 'el-up' : ''],
    [t('k_range'), Math.round(st.range).toLocaleString() + ' km'],
    [t('k_ra'), hms(st.ra / 15)],
    [t('k_dec'), dms(st.dec)],
    [t('k_lst'), hms(st.lst)],
  ]);
  const el = $('sunlit');
  el.className = st.sunlit ? 'lit' : 'ecl';
  el.textContent = st.sunlit ? t('lit') : t('ecl');
}

function tleEpoch(){
  const yr = REC.epochyr < 57 ? 2000 + REC.epochyr : 1900 + REC.epochyr;
  return new Date(Date.UTC(yr, 0, 1) + (REC.epochdays - 1) * 86400000);
}

function renderBasic(){
  const n = REC.no / 60;                                       // rad/s
  const a = Math.cbrt(MU / (n * n)), e = REC.ecco;
  const ep = tleEpoch(), age = (Date.now() - ep.getTime()) / 86400000;
  $('basicTbl').innerHTML = kv([
    [t('k_norad'), SAT.norad_id],
    [t('k_country'), SAT.country || '—'],
    [t('k_purpose'), SAT.purpose || '—'],
    [t('k_era'), SAT.era || '—'],
    [t('k_const'), SAT.constellation || '—'],
    [t('k_period'), PERIOD_MIN.toFixed(1) + ' ' + t('unit_min')],
    [t('k_inc'), fmtDeg(REC.inclo * R2D, 3)],
    [t('k_ecc'), e.toFixed(6)],
    [t('k_raan'), fmtDeg(REC.nodeo * R2D, 2)],
    [t('k_perigee'), (a * (1 - e) - RE).toFixed(1) + ' km'],
    [t('k_apogee'), (a * (1 + e) - RE).toFixed(1) + ' km'],
    [t('k_epoch'), ep.toISOString().slice(0, 16).replace('T', ' ') + ' UTC'],
    [t('k_age'), age < 2 ? (age * 24).toFixed(1) + ' ' + t('unit_hr') : age.toFixed(1) + ' ' + t('unit_day')],
  ]);
  $('tle').textContent = SAT.line1 + '\n' + SAT.line2;
}

function renderObs(st){
  $('obsTbl').innerHTML = kv([
    [t('k_obs_lat'), fmtDeg(OBS.lat, 4)],
    [t('k_obs_lon'), fmtDeg(OBS.lon, 4)],
    [t('k_obs_src'), t(OBS.src)],
    [t('k_sun_el'), st ? st.sunEl.toFixed(1) + '°' : '—'],
  ]);
}

/* 過境預報：60 s 粗掃仰角 0° 穿越，二分法細化至 1 s；可目視＝最高點時衛星日照且太陽仰角 < −6° */
function computePasses(now){
  const t0 = now.getTime(), end = t0 + 3 * 86400000, step = 60000;
  const elAt = ms => { const s = stateAt(new Date(ms)); return s ? s.el : -90; };
  const refine = (a, b, rising) => {
    for(let k = 0; k < 12; k++){ const m = (a + b) / 2; ((elAt(m) > 0) === rising) ? (b = m) : (a = m); }
    return b;
  };
  const out = [];
  let prevEl = elAt(t0), rise = prevEl > 0 ? t0 : null, maxEl = prevEl, maxT = t0, minEl = prevEl, maxAll = prevEl;
  for(let ms = t0 + step; ms <= end && out.length < 12; ms += step){
    const el = elAt(ms);
    minEl = Math.min(minEl, el); maxAll = Math.max(maxAll, el);
    if(prevEl <= 0 && el > 0){ rise = refine(ms - step, ms, true); maxEl = el; maxT = ms; }
    else if(rise != null && el > maxEl){ maxEl = el; maxT = ms; }
    if(rise != null && prevEl > 0 && el <= 0){
      const set = refine(ms - step, ms, false);
      if(maxEl >= PASS_MIN_EL){
        const sm = stateAt(new Date(maxT), true);
        out.push({rise: new Date(rise), max: new Date(maxT), set: new Date(set), maxEl,
                  vis: sm && sm.sunlit && sm.sunEl < -6});
      }
      rise = null; maxEl = -90;
    }
    prevEl = el;
  }
  // 整段仰角變化 < 2°：近地球同步，改報固定仰角
  PASSES = (maxAll - minEl < 2) ? {geo: true, el: (maxAll + minEl) / 2} : {list: out};
}

function renderPasses(){
  const box = $('passes');
  if(!PASSES){ box.innerHTML = ''; return; }
  if(PASSES.geo){ box.innerHTML = '<div class="note">' + tpl('p_geo', {el: PASSES.el.toFixed(1)}) + '</div>'; return; }
  if(!PASSES.list.length){ box.innerHTML = '<div class="note">' + t('p_none') + '</div>'; return; }
  const dfmt = d => d.toLocaleDateString(LOCALE[LANG], {month: '2-digit', day: '2-digit'}) + ' ' + fmtTime(d, {hour: '2-digit', minute: '2-digit'});
  let h = '<table class="pass"><tr><th>' + t('p_rise') + '</th><th>' + t('p_max') + '</th><th>' + t('p_set') + '</th><th>' + t('p_dur') + '</th></tr>';
  PASSES.list.forEach(p => {
    h += '<tr' + (p.vis ? ' class="vis"' : '') + '><td>' + dfmt(p.rise) + '</td><td>' + p.maxEl.toFixed(0) + '°</td><td>' +
         fmtTime(p.set, {hour: '2-digit', minute: '2-digit'}) + '</td><td>' +
         Math.round((p.set - p.rise) / 60000) + ' ' + t('unit_min') + '</td></tr>';
  });
  box.innerHTML = h + '</table><div class="note">' + t('p_vis') + '</div>';
}

// ── 觀測者 ──
function setObserver(lat, lon, src){
  OBS = {lat, lon, src};
  try{ if(src !== 'src_default') localStorage.setItem('track_obs', JSON.stringify(OBS)); }catch(e){}
  obsMarker.setLatLng([lat, nearCenter(lon)]);
  if(REC){ computePasses(new Date()); renderPasses(); tick(); }
}

function initObserver(){
  try{
    const s = JSON.parse(localStorage.getItem('track_obs') || 'null');
    if(s && isFinite(s.lat) && isFinite(s.lon)){ OBS = s; return; }
  }catch(e){}
  if(navigator.geolocation){
    navigator.geolocation.getCurrentPosition(
      p => setObserver(p.coords.latitude, p.coords.longitude, 'src_geo'),
      () => {}, {timeout: 8000, maximumAge: 3600000});
  }
}

// ── 主迴圈 ──
let _lastSlow = 0;
function tick(){
  if(!REC) return;
  const now = new Date();
  const st = stateAt(now, true);
  if(!st){ $('status').textContent = t('status_decayed'); $('status').style.display = 'block'; return; }
  if(now - _lastSlow > 60000){ drawTrack(now); drawNight(now); _lastSlow = now.getTime(); }
  satMarker.setLatLng([st.lat, nearCenter(st.lon)]);
  obsMarker.setLatLng([OBS.lat, nearCenter(OBS.lon)]);
  if(!map.hasLayer(satMarker)) satMarker.addTo(map);
  if($('optFoot').checked) drawFootprint(st);
  if($('optFollow').checked) map.panTo([st.lat, nearCenter(st.lon)], {animate: false});
  renderLive(st);
  renderObs(st);
}

async function load(norad){
  $('status').style.display = 'block';
  $('status').textContent = t('status_loading');
  $('content').style.display = 'none';
  try{
    const r = await fetch('/api/sat_tle?norad_id=' + norad);
    const d = await r.json();
    if(!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
    SAT = d;
    REC = satellite.twoline2satrec(d.line1, d.line2);
    PERIOD_MIN = 2 * Math.PI / REC.no;
    $('orbitLink').href = '/orbit?norad=' + norad;
    $('q').value = norad;
    renderHead();
    renderBasic();
    _lastSlow = 0;
    const st = stateAt(new Date(), true);
    if(!st){ $('status').textContent = t('status_decayed'); return; }
    $('status').style.display = 'none';
    $('content').style.display = 'block';
    map.setView([st.lat, st.lon], 2);
    tick();
    computePasses(new Date());
    renderPasses();
  }catch(e){ $('status').textContent = tpl('status_fail', {error: e.message || e}); }
}

function renderHead(){
  $('satName').textContent = SAT.name;
  $('satSub').textContent = 'NORAD ' + SAT.norad_id + ' · ' + PERIOD_MIN.toFixed(1) + ' ' + t('unit_min');
  document.title = SAT.name + ' — ' + t('doc_title');
}

function setLang(lang){
  if(!I18N[lang]) return;
  LANG = lang;
  try{ localStorage.setItem('track_lang', lang); }catch(e){}
  document.documentElement.lang = LOCALE[lang];
  document.title = t('doc_title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.getAttribute('data-i18n-placeholder')); });
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.toggle('active', b.dataset.lang === lang));
  if(REC){ renderHead(); renderBasic(); renderPasses(); tick(); }
}
window.setLang = setLang;

function init(){
  setLang(LANG);
  initObserver();
  initMap();
  $('q').addEventListener('keydown', e => {
    if(e.key !== 'Enter') return;
    const v = $('q').value.trim();
    if(!/^\d+$/.test(v)) return;
    try{ history.replaceState(null, '', '/track?norad=' + v); }catch(_){}
    load(v);
  });
  const n = new URLSearchParams(location.search).get('norad');
  if(n && /^\d+$/.test(n)) load(n);
  else $('status').textContent = t('status_need');
  setInterval(tick, 1000);
}
init();
