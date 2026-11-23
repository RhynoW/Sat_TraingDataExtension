/* AIS 船舶圖層（Python 線上版與 Rust 單機版共用；後端 /api/ais/*）
 * - 勾選「AIS 船舶」才開始輪詢；伺服器端那時才連 aisstream，閒置 10 分鐘自動斷線
 * - 依目前畫面範圍每 10 秒更新一次（鏡頭停止移動也會更新），單次最多 5000 艘
 * - 船隻為指向航向的箭頭（無航向為圓點），依船型上色；點選顯示詳細資料與 6 小時航跡
 * - Rust 單機版：/api/ais/status 回 key_settable=true 時，面板可直接輸入 aisstream 金鑰
 */
(function () {
  'use strict';
  const I18N = {
    zh: {
      layer: 'AIS 船舶', moving: '只顯示航行中', key_ph: '貼上 aisstream.io API 金鑰', key_save: '儲存',
      key_get: '免費申請（GitHub 登入）', key_saved: '金鑰已儲存，連線中…', key_bad: '金鑰格式不正確',
      st_no_key: '未設定 aisstream 金鑰（AISSTREAM_API_KEY）', st_connecting: '連線 aisstream 中…',
      st_retry: '連線中斷，稍後自動重連', st_idle: '待命', st_live: '即時：畫面內 {0} 艘／全部 {1} 艘',
      st_trunc: '（只顯示最新 {0} 艘，請放大地圖）', st_err: '讀取失敗',
      note: 'AIS 為船舶自主回報，僅岸基接收站約 15～40 浬內有資料；位置可能遭干擾或偽造，地圖上沒有船不代表沒有船。',
      t_cargo: '貨輪', t_tanker: '油輪', t_passenger: '客輪', t_fishing: '漁船', t_military: '軍警',
      t_tug: '拖船／工作船', t_leisure: '遊艇／帆船', t_other: '其他', t_unknown: '未知（尚未收到船型）',
      f_mmsi: 'MMSI', f_name: '船名', f_callsign: '呼號', f_imo: 'IMO', f_type: '船型', f_nav: '航行狀態',
      f_sog: '航速', f_cog: '對地航向', f_hdg: '艏向', f_dest: '目的地', f_eta: '預計抵達（UTC）', f_size: '尺寸',
      f_draught: '吃水', f_pos: '位置', f_seen: '最後收到', f_track: '航跡（近 6 小時）', f_cls: 'AIS 等級',
      f_flag: '船籍（MMSI 推估）', sec_ago: '{0} 秒前', min_ago: '{0} 分鐘前', pts: '{0} 點',
      kn: '節', src: '資料：{0}（自主回報，僅供參考）',
      nav: ['動力航行中', '錨泊', '失去操縱', '操縱受限', '受吃水限制', '繫泊', '擱淺', '捕魚作業中', '帆船航行中'],
      s_aisstream: 'aisstream.io', s_mpb: '航港局', f_src: '資料來源', srcs: '來源：',
      ss_live: '即時', ss_connecting: '連線中', ss_retry: '重試中', ss_idle: '待命', ss_no_key: '未設定金鑰',
    },
    en: {
      layer: 'AIS Ships', moving: 'Moving only', key_ph: 'Paste aisstream.io API key', key_save: 'Save',
      key_get: 'Get a free key (GitHub sign-in)', key_saved: 'Key saved, connecting…', key_bad: 'Invalid key format',
      st_no_key: 'aisstream key not set (AISSTREAM_API_KEY)', st_connecting: 'Connecting to aisstream…',
      st_retry: 'Disconnected, retrying automatically', st_idle: 'Standby', st_live: 'Live: {0} in view / {1} total',
      st_trunc: ' (showing newest {0}; zoom in)', st_err: 'Load failed',
      note: 'AIS is self-reported and only received within ~15–40 nmi of shore stations; positions may be jammed or spoofed. A ship missing from the map proves nothing.',
      t_cargo: 'Cargo', t_tanker: 'Tanker', t_passenger: 'Passenger', t_fishing: 'Fishing', t_military: 'Military / law enf.',
      t_tug: 'Tug / service', t_leisure: 'Pleasure / sailing', t_other: 'Other', t_unknown: 'Unknown (type not yet received)',
      f_mmsi: 'MMSI', f_name: 'Name', f_callsign: 'Call sign', f_imo: 'IMO', f_type: 'Type', f_nav: 'Nav status',
      f_sog: 'Speed', f_cog: 'Course', f_hdg: 'Heading', f_dest: 'Destination', f_eta: 'ETA (UTC)', f_size: 'Size',
      f_draught: 'Draught', f_pos: 'Position', f_seen: 'Last heard', f_track: 'Track (last 6 h)', f_cls: 'AIS class',
      f_flag: 'Flag (from MMSI)', sec_ago: '{0} s ago', min_ago: '{0} min ago', pts: '{0} pts',
      kn: 'kn', src: 'Data: {0} (self-reported, for reference only)',
      s_aisstream: 'aisstream.io', s_mpb: 'Taiwan MPB', f_src: 'Sources', srcs: 'Sources: ',
      ss_live: 'live', ss_connecting: 'connecting', ss_retry: 'retrying', ss_idle: 'standby', ss_no_key: 'no key',
      nav: ['Under way (engine)', 'At anchor', 'Not under command', 'Restricted manoeuvrability', 'Constrained by draught',
        'Moored', 'Aground', 'Engaged in fishing', 'Under way (sailing)'],
    },
    ja: {
      layer: 'AIS 船舶', moving: '航行中のみ', key_ph: 'aisstream.io の API キーを貼り付け', key_save: '保存',
      key_get: '無料取得（GitHub ログイン）', key_saved: 'キーを保存しました。接続中…', key_bad: 'キーの形式が正しくありません',
      st_no_key: 'aisstream キー未設定（AISSTREAM_API_KEY）', st_connecting: 'aisstream に接続中…',
      st_retry: '切断されました。自動で再接続します', st_idle: '待機', st_live: 'ライブ：表示範囲 {0} 隻／全体 {1} 隻',
      st_trunc: '（最新 {0} 隻のみ表示。拡大してください）', st_err: '読み込み失敗',
      note: 'AIS は船舶の自己申告で、沿岸受信局から約 15～40 海里以内のみ受信できます。位置は妨害・偽装の可能性があり、地図に船がなくても存在しないとは限りません。',
      t_cargo: '貨物船', t_tanker: 'タンカー', t_passenger: '旅客船', t_fishing: '漁船', t_military: '軍・法執行',
      t_tug: 'タグ／作業船', t_leisure: 'プレジャー／帆船', t_other: 'その他', t_unknown: '不明（船種未受信）',
      f_mmsi: 'MMSI', f_name: '船名', f_callsign: 'コールサイン', f_imo: 'IMO', f_type: '船種', f_nav: '航行状態',
      f_sog: '速力', f_cog: '対地針路', f_hdg: '船首方位', f_dest: '目的地', f_eta: '到着予定（UTC）', f_size: '寸法',
      f_draught: '喫水', f_pos: '位置', f_seen: '最終受信', f_track: '航跡（直近 6 時間）', f_cls: 'AIS クラス',
      f_flag: '船籍（MMSI から推定）', sec_ago: '{0} 秒前', min_ago: '{0} 分前', pts: '{0} 点',
      kn: 'ノット', src: 'データ：{0}（自己申告・参考情報）',
      s_aisstream: 'aisstream.io', s_mpb: '台湾航港局', f_src: 'データ元', srcs: 'データ元：',
      ss_live: 'ライブ', ss_connecting: '接続中', ss_retry: '再試行中', ss_idle: '待機', ss_no_key: 'キー未設定',
      nav: ['機関航行中', '錨泊', '運転不自由', '操縦性能制限', '喫水制限', '係留', '座礁', '漁ろう中', '帆走中'],
    },
  };
  const TYPES = [
    ['cargo', '#4FC3F7'], ['tanker', '#FF7043'], ['passenger', '#66BB6A'], ['fishing', '#FFCA28'],
    ['military', '#EF5350'], ['tug', '#AB47BC'], ['leisure', '#F06292'], ['other', '#B0BEC5'], ['unknown', '#757575'],
  ];
  const COLOR = Object.fromEntries(TYPES);
  // 依 MMSI 前三碼（MID）推估船籍：只列常見者，其餘顯示 MID
  const MID = {
    416: 'TW', 412: 'CN', 413: 'CN', 414: 'CN', 477: 'HK', 453: 'MO', 431: 'JP', 432: 'JP', 440: 'KR', 441: 'KR',
    445: 'KP', 525: 'ID', 533: 'MY', 548: 'PH', 563: 'SG', 564: 'SG', 565: 'SG', 566: 'SG', 574: 'VN', 567: 'TH',
    351: 'PA', 352: 'PA', 353: 'PA', 354: 'PA', 355: 'PA', 356: 'PA', 357: 'PA', 370: 'PA', 371: 'PA', 372: 'PA',
    373: 'PA', 374: 'PA', 636: 'LR', 637: 'LR', 538: 'MH', 229: 'MT', 248: 'MT', 249: 'MT', 256: 'MT', 215: 'MT',
    209: 'CY', 210: 'CY', 212: 'CY', 240: 'GR', 241: 'GR', 237: 'GR', 311: 'BS', 308: 'BS', 309: 'BS',
    338: 'US', 366: 'US', 367: 'US', 368: 'US', 369: 'US', 232: 'GB', 233: 'GB', 234: 'GB', 235: 'GB',
    211: 'DE', 218: 'DE', 226: 'FR', 227: 'FR', 228: 'FR', 244: 'NL', 245: 'NL', 246: 'NL', 257: 'NO', 258: 'NO',
    259: 'NO', 265: 'SE', 266: 'SE', 219: 'DK', 220: 'DK', 273: 'RU', 503: 'AU', 512: 'NZ', 419: 'IN', 403: 'SA',
    470: 'AE', 471: 'AE', 422: 'IR', 271: 'TR', 247: 'IT', 224: 'ES', 225: 'ES', 263: 'PT', 316: 'CA',
  };

  const lang = () => (window.getGlobeLang && window.getGlobeLang()) || 'zh';
  function T(k, ...a) {
    const d = I18N[lang()] || I18N.zh;
    let s = k in d ? d[k] : I18N.zh[k];
    if (typeof s === 'string') a.forEach((v, i) => { s = s.replace('{' + i + '}', v); });
    return s;
  }
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function cat(tp) {
    if (!tp) return 'unknown';
    if (tp >= 70 && tp <= 79) return 'cargo';
    if (tp >= 80 && tp <= 89) return 'tanker';
    if ((tp >= 60 && tp <= 69) || (tp >= 40 && tp <= 49)) return 'passenger';
    if (tp === 30) return 'fishing';
    if (tp === 35 || tp === 55) return 'military';
    if ([31, 32, 33, 34, 50, 51, 52, 53, 54, 56, 57, 58, 59].includes(tp)) return 'tug';
    if (tp === 36 || tp === 37) return 'leisure';
    return 'other';
  }

  let viewer = null, bc = null, ds = null, proxy = null, trackEnt = null;
  let on = false, timer = null, inflight = false, lastStatus = null, lastData = null;
  const icons = {};
  function icon(kind) {               // 白色圖示，billboard 以 color 上色
    if (icons[kind]) return icons[kind];
    const c = document.createElement('canvas'); c.width = c.height = 32;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.strokeStyle = 'rgba(0,0,0,.85)'; g.lineWidth = 2.2;
    g.beginPath();
    if (kind === 'arrow') { g.moveTo(16, 3); g.lineTo(25, 28); g.lineTo(16, 22); g.lineTo(7, 28); g.closePath(); }
    else { g.arc(16, 16, 6.5, 0, Math.PI * 2); }
    g.stroke(); g.fill();
    return (icons[kind] = c);
  }

  function ensure() {
    viewer = viewer || window.__cesiumViewer;
    if (!viewer) return false;
    if (!bc) {
      bc = viewer.scene.primitives.add(new Cesium.BillboardCollection({ scene: viewer.scene }));
      ds = new Cesium.CustomDataSource('ais');
      viewer.dataSources.add(ds);
      const h = viewer.screenSpaceEventHandler, LC = Cesium.ScreenSpaceEventType.LEFT_CLICK;
      const orig = h.getInputAction(LC);
      h.setInputAction((e) => {
        const p = on && viewer.scene.pick(e.position);
        if (p && p.collection === bc && p.id && p.id.aisMmsi) { select(p.id.aisMmsi, p.primitive.position); return; }
        if (orig) orig(e);
      }, LC);
      viewer.selectedEntityChanged.addEventListener((ent) => {
        if (proxy && ent !== proxy) { ds.entities.remove(proxy); proxy = null; clearTrack(); }
      });
      viewer.camera.moveEnd.addEventListener(() => { if (on) refresh(); });
    }
    return true;
  }

  function bbox() {
    const r = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
    if (!r) return { w: -180, s: -90, e: 180, n: 90 };
    const d = Cesium.Math.toDegrees;
    return { w: d(r.west), s: d(r.south), e: d(r.east), n: d(r.north) };
  }

  async function refresh() {
    if (!on || inflight || !ensure()) return;
    inflight = true;
    try {
      const b = bbox(), mv = document.getElementById('ais-moving');
      const off = [...document.querySelectorAll('#ais-srcs input[data-src]')].filter((c) => !c.checked);
      const on_ = [...document.querySelectorAll('#ais-srcs input[data-src]')].filter((c) => c.checked).map((c) => c.dataset.src);
      const q = 'w=' + b.w.toFixed(3) + '&s=' + b.s.toFixed(3) + '&e=' + b.e.toFixed(3) + '&n=' + b.n.toFixed(3) +
        (mv && mv.checked ? '&moving=1' : '') + (off.length ? '&src=' + (on_.join(',') || 'none') : '');
      const r = await fetch('/api/ais/ships?' + q, { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      if (!on) return;
      lastData = d; lastStatus = d;
      draw(d);
      status(d);
    } catch (e) {
      setStatus(T('st_err') + ' (' + e.message + ')', true);
    } finally { inflight = false; }
  }

  function draw(d) {
    bc.removeAll();
    const C = d.cols, ix = Object.fromEntries(C.map((k, i) => [k, i]));
    const cols = {};
    for (const [k, v] of TYPES) cols[k] = Cesium.Color.fromCssColorString(v);
    for (const row of d.rows) {
      const hd = row[ix.hdg] != null ? row[ix.hdg] : (row[ix.sog] >= 0.5 ? row[ix.cog] : null);
      const k = cat(row[ix.type]);
      bc.add({
        position: Cesium.Cartesian3.fromDegrees(row[ix.lon], row[ix.lat], 0),
        image: icon(hd != null ? 'arrow' : 'dot'),
        color: cols[k],
        scale: hd != null ? 0.55 : 0.5,
        rotation: hd != null ? -Cesium.Math.toRadians(hd) : 0,
        alignedAxis: hd != null ? Cesium.Cartesian3.UNIT_Z : Cesium.Cartesian3.ZERO,
        scaleByDistance: new Cesium.NearFarScalar(2e5, 1.4, 2e7, 0.6),
        disableDepthTestDistance: 5e6,
        id: { aisMmsi: row[ix.mmsi] },
      });
    }
    viewer.scene.requestRender && viewer.scene.requestRender();
  }

  function status(d) {
    const st = d.state, srcs = d.sources || {};
    let msg = st === 'live' && d.n != null ? T('st_live', d.n.toLocaleString(), d.total.toLocaleString()) + (d.truncated ? T('st_trunc', d.n) : '')
      : T('st_' + st) || st;
    const a = srcs.aisstream;
    if (st !== 'live' && st !== 'no_key' && d.error) msg += '：' + d.error.slice(0, 80);
    // 各來源狀態（兩個來源時才顯示，例：aisstream.io：即時｜航港局：即時）
    const names = Object.keys(srcs);
    const line2 = names.length > 1 ? names.map((k) => T('s_' + k) + '：' + (T('ss_' + srcs[k].state) || srcs[k].state)).join('｜') : '';
    setStatus(msg + (line2 ? '\n' + line2 : ''), st === 'no_key' || st === 'retry');
    const kb = document.getElementById('ais-keybox');
    if (kb) kb.style.display = (a && a.state === 'no_key' && d.key_settable) ? 'flex' : 'none';
    srcBoxes(names);
  }
  function srcBoxes(names) {           // 來源篩選勾選框（伺服器啟用兩個以上來源才顯示）
    const box = document.getElementById('ais-srcs');
    if (!box) return;
    const have = [...box.querySelectorAll('input[data-src]')].map((c) => c.dataset.src).join(',');
    if (names.length < 2) { box.style.display = 'none'; return; }
    box.style.display = 'flex';
    if (have !== names.join(',')) {
      box.innerHTML = '<span data-ais-i18n="srcs">' + esc(T('srcs')) + '</span>' + names.map((k) =>
        '<label><input type="checkbox" data-src="' + esc(k) + '" checked onchange="AIS.refresh()"/> <span data-ais-i18n="s_' + esc(k) + '">' +
        esc(T('s_' + k)) + '</span></label>').join('');
    }
  }
  function setStatus(s, warn) {
    const el = document.getElementById('ais-status');
    if (el) { el.textContent = s; el.style.whiteSpace = 'pre-line'; el.style.color = warn ? '#FFB74D' : ''; }
  }

  function fmtAgo(t) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - t));
    return s < 120 ? T('sec_ago', s) : T('min_ago', Math.round(s / 60));
  }

  function desc(s) {
    const k = cat(s.type), nav = T('nav');
    const mid = Math.floor(s.mmsi / 1e6);
    const rows = [
      ['f_mmsi', s.mmsi], ['f_name', s.name], ['f_callsign', s.callsign], ['f_imo', s.imo],
      ['f_flag', MID[mid] ? MID[mid] + ' (MID ' + mid + ')' : (mid >= 201 && mid <= 775 ? 'MID ' + mid : '')],
      ['f_type', '<span style="color:' + COLOR[k] + '">■</span> ' + esc(T('t_' + k)) + (s.type ? ' (' + s.type + ')' : '')],
      ['f_nav', s.nav != null && nav[s.nav] ? nav[s.nav] : ''],
      ['f_sog', s.sog != null ? s.sog + ' ' + T('kn') : ''], ['f_cog', s.cog != null ? s.cog + '°' : ''],
      ['f_hdg', s.hdg != null ? s.hdg + '°' : ''], ['f_dest', s.dest], ['f_eta', s.eta],
      ['f_size', s.length ? s.length + ' × ' + (s.width || '?') + ' m' : ''], ['f_draught', s.draught ? s.draught + ' m' : ''],
      ['f_pos', s.lat.toFixed(4) + ', ' + s.lon.toFixed(4)], ['f_seen', fmtAgo(s.t)], ['f_cls', s.cls],
      ['f_track', s.track ? T('pts', s.track.length) : ''],
      ['f_src', Object.keys(s.src || {}).map((k) => T('s_' + k) + ' (' + fmtAgo(s.src[k]) + ')').join(', ')],
    ];
    const tr = rows.filter((r) => r[1] !== undefined && r[1] !== null && r[1] !== '')
      .map((r) => '<tr><th style="text-align:left;padding-right:10px;white-space:nowrap">' + esc(T(r[0])) + '</th><td>' +
        (r[0] === 'f_type' ? r[1] : esc(r[1])) + '</td></tr>').join('');
    const links = s.imo ? ' · <a href="https://www.marinetraffic.com/en/ais/details/ships/imo:' + s.imo + '" target="_blank" rel="noopener">MarineTraffic</a>' : '';
    const SRC_URL = { aisstream: 'https://aisstream.io', mpb: 'https://mpbais.motcmpb.gov.tw/aismpb/' };
    const credit = Object.keys(s.src || {}).map((k) => '<a href="' + SRC_URL[k] + '" target="_blank" rel="noopener">' + esc(T('s_' + k)) + '</a>').join('、');
    return '<table class="cesium-infoBox-defaultTable">' + tr + '</table><p style="font-size:11px;color:#aaa;margin:6px 0 0">' +
      esc(T('src')).replace('{0}', credit || 'aisstream.io') + links + '</p><p style="font-size:11px;color:#aaa;margin:4px 0 0">' + esc(T('note')) + '</p>';
  }

  function clearTrack() { if (trackEnt) { ds.entities.remove(trackEnt); trackEnt = null; } }

  async function select(mmsi, pos) {
    if (proxy) { ds.entities.remove(proxy); proxy = null; }
    clearTrack();
    proxy = ds.entities.add({ id: 'ais_' + mmsi, name: 'MMSI ' + mmsi, position: pos, point: { pixelSize: 1, color: Cesium.Color.TRANSPARENT } });
    viewer.selectedEntity = proxy;
    try {
      const r = await fetch('/api/ais/ship/' + mmsi, { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      const s = await r.json();
      if (!proxy || proxy.id !== 'ais_' + mmsi) return;
      proxy.name = (s.name || 'MMSI ' + mmsi) + ' · AIS';
      proxy.description = new Cesium.ConstantProperty(desc(s));
      if (s.track && s.track.length > 1) {
        trackEnt = ds.entities.add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(s.track.flatMap((p) => [p[2], p[1]])),
            width: 2, material: Cesium.Color.fromCssColorString(COLOR[cat(s.type)]).withAlpha(0.9), clampToGround: false,
          },
        });
      }
    } catch (e) {
      proxy.description = new Cesium.ConstantProperty('<p>' + esc(T('st_err')) + '</p>');
    }
  }

  function legend() {
    const el = document.getElementById('ais-legend');
    if (!el) return;
    el.innerHTML = TYPES.map(([k, c]) => '<span style="white-space:nowrap;margin-right:8px"><span style="color:' + c +
      '">▲</span> ' + esc(T('t_' + k)) + '</span>').join(' ');
  }

  function relang() {
    document.querySelectorAll('[data-ais-i18n]').forEach((el) => { el.textContent = T(el.getAttribute('data-ais-i18n')); });
    const ki = document.getElementById('ais-key'); if (ki) ki.placeholder = T('key_ph');
    legend();
    if (lastStatus) status(lastStatus);
    else setStatus(T('st_idle'));
  }

  function toggle(cb) {
    on = !!cb.checked;
    const box = document.getElementById('ais-ctl');
    if (box) box.style.display = on ? 'block' : 'none';
    if (!ensure()) { setTimeout(() => toggle(cb), 500); return; }
    if (on) {
      relang();
      setStatus(T('st_connecting'));
      refresh();
      timer = setInterval(refresh, 10000);
    } else {
      clearInterval(timer); timer = null;
      bc.removeAll();
      if (proxy) { ds.entities.remove(proxy); proxy = null; }
      clearTrack();
    }
  }

  async function saveKey() {
    const ki = document.getElementById('ais-key');
    const k = (ki && ki.value || '').trim();
    if (!/^[A-Za-z0-9_-]{16,128}$/.test(k)) { setStatus(T('key_bad'), true); return; }
    try {
      const r = await fetch('/api/ais/key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: k }) });
      if (!r.ok) throw new Error(r.status);
      ki.value = '';
      setStatus(T('key_saved'));
      setTimeout(refresh, 1500);
    } catch (e) { setStatus(T('st_err') + ' (' + e.message + ')', true); }
  }

  window.AIS = { toggle, refresh, relang, saveKey, _cat: cat, _T: T };
  document.addEventListener('DOMContentLoaded', relang);
})();
