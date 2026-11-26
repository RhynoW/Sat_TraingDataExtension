/* 觀測資料模型：欄位定義、驗證、CSV 讀寫。線上版（scenario04/web/static/js）與 Rust 單機版（web/ext）共用同一份檔案。
   四種紀錄：pois 地面 POI、observations 觀測紀錄、orbits 軌道解、claims 身分主張；每筆另有複核欄位
   （review 未複核／已接受／有爭議／已否決、review_note、reviewer、reviewed_at）與建立者 by、時間 at。
   伺服器端驗證規則與此相同（Rust src/obs.rs）。 */
(function () {
  'use strict';
  var SRC = { official: '官方（Space-Track 等）', gcat: 'GCAT', amateur: '業餘觀測（SeeSat-L 等）', own: '自行觀測', news: '新聞／公開資訊', other: '其他' };
  var SRC_CONF = { official: 'high', gcat: 'medium', amateur: 'medium', own: 'medium', news: 'low', other: 'low' };
  var CONF = { high: '高', medium: '中', low: '低' };
  var REVIEW = { unreviewed: '未複核', accepted: '已接受', disputed: '有爭議', rejected: '已否決' };
  var POI_KIND = { station: '觀測站', site: '關注地點' };
  var TIME_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?Z?$/;

  function num(k, l, min, max, o) { return Object.assign({ k: k, l: l, type: 'num', min: min, max: max }, o || {}); }
  function txt(k, l, max, o) { return Object.assign({ k: k, l: l, type: 'text', max: max }, o || {}); }
  function sel(k, l, opts, def, o) { return Object.assign({ k: k, l: l, type: 'sel', opts: opts, def: def }, o || {}); }
  var URL_F = txt('source_url', '來源連結', 500, { url: true });
  var NOTE_F = txt('note', '備註', 500);

  var KINDS = {
    pois: {
      label: '地面 POI', unit: '個',
      fields: [txt('name', '名稱', 64, { req: true }), num('lat', '緯度（°）', -90, 90, { req: true }), num('lon', '經度（°）', -180, 360, { req: true }),
        num('alt_m', '高度（m）', -500, 9000, { def: 0 }), sel('kind', '類型', POI_KIND, 'station'), NOTE_F]
    },
    observations: {
      label: '觀測紀錄', unit: '筆',
      fields: [num('norad', 'NORAD', 1, 999999, { int: true }), txt('station', '觀測站（POI 名稱）', 64, { req: true }), txt('time', '時間（UTC）', 40, { req: true, time: true }),
        num('ra_deg', 'RA（°，J2000）', 0, 360), num('dec_deg', 'Dec（°，J2000）', -90, 90), num('az_deg', '方位角（°）', 0, 360), num('el_deg', '仰角（°）', -90, 90),
        num('mag', '星等', -10, 25), txt('observer', '觀測者', 64), sel('source', '來源類型', SRC, 'amateur'), URL_F, NOTE_F]
    },
    orbits: {
      label: '軌道解', unit: '筆',
      fields: [num('norad', 'NORAD（空白＝取自 TLE）', 1, 999999, { int: true }), txt('line1', 'TLE 第 1 行', 80, { req: true, mono: true }), txt('line2', 'TLE 第 2 行', 80, { req: true, mono: true }),
        sel('source', '來源類型', SRC, 'amateur'), txt('source_name', '來源名稱', 64), URL_F, NOTE_F]
    },
    claims: {
      label: '身分主張', unit: '筆',
      fields: [num('norad', 'NORAD', 1, 999999, { int: true, req: true }), txt('name', '主張的名稱', 64, { req: true }), sel('source_type', '來源類型', SRC, 'amateur'),
        URL_F, sel('confidence', '可信度（空白＝依來源類型）', CONF, ''), NOTE_F]
    }
  };
  var META = ['id', 'by', 'at', 'review', 'review_note', 'reviewer', 'reviewed_at'];

  function parseTime(s) {
    var m = TIME_RE.exec(String(s == null ? '' : s).trim());
    if (!m) return null;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)));
    if (d.getUTCFullYear() !== +m[1] || d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3] || +m[4] > 23 || +m[5] > 59 || +(m[6] || 0) > 59) return null;
    return m[1] + '-' + m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5] + ':' + (m[6] || '00') + (m[7] ? '.' + m[7].slice(0, 6) : '');
  }
  var ALPHA5 = 'ABCDEFGHJKLMNPQRSTUVWXYZ';   // TLE Alpha-5：A=10 … Z=33（不用 I、O），例如 A1419＝101419
  function tleNorad(l) {
    var s = String(l || '').slice(2, 7);
    if (s.length === 5 && ALPHA5.indexOf(s[0]) >= 0 && /^\d{4}$/.test(s.slice(1))) return (ALPHA5.indexOf(s[0]) + 10) * 10000 + +s.slice(1);
    s = s.trim(); return /^\d+$/.test(s) && +s > 0 ? +s : null;
  }

  /* 驗證並正規化一筆紀錄；data＝目前全部資料（檢查 POI 名稱重複、觀測站是否存在）；selfId＝修改時本身的 id */
  function validate(kind, rec, data, selfId) {
    var K = KINDS[kind], out = {}, errs = [];
    if (!K) return { rec: null, errors: ['未知的資料種類 ' + kind] };
    K.fields.forEach(function (f) {
      var v = rec[f.k];
      if (v == null) v = '';
      if (typeof v === 'string') v = v.trim();
      if (f.type === 'num') {
        if (v === '') { if (f.req) errs.push(f.l + '必填'); out[f.k] = f.def != null ? f.def : null; return; }
        var x = Number(v);
        if (!isFinite(x)) { errs.push(f.l + '需為數字'); return; }
        if (f.int && Math.floor(x) !== x) { errs.push(f.l + '需為整數'); return; }
        if (x < f.min || x > f.max) { errs.push(f.l + '需介於 ' + f.min + '～' + f.max); return; }
        out[f.k] = x;
      } else if (f.type === 'sel') {
        v = String(v);
        if (v === '') v = f.def;
        if (v !== '' && !Object.prototype.hasOwnProperty.call(f.opts, v)) { errs.push(f.l + '不在選項內：' + v); return; }
        out[f.k] = v;
      } else {
        v = f.mono ? String(v).replace(/\s+$/, '') : String(v);
        if (f.req && !v) { errs.push(f.l + '必填'); return; }
        if (v.length > f.max) { errs.push(f.l + '超過 ' + f.max + ' 字'); return; }
        if (f.url && v && !/^https?:\/\/\S+$/.test(v)) { errs.push(f.l + '需以 http:// 或 https:// 開頭'); return; }
        if (f.time && v) { var t = parseTime(v); if (!t) { errs.push(f.l + '格式需為 YYYY-MM-DD HH:MM:SS（UTC）'); return; } v = t; }
        out[f.k] = v;
      }
    });
    if (!errs.length) {
      if (kind === 'pois') {
        var nm = out.name.toUpperCase();
        if ((data.pois || []).some(function (p) { return p.id !== selfId && String(p.name).toUpperCase() === nm; })) errs.push('已有同名的地面 POI：' + out.name);
      } else if (kind === 'observations') {
        var st = out.station.toUpperCase();
        if (!(data.pois || []).some(function (p) { return String(p.name).toUpperCase() === st; })) errs.push('找不到觀測站「' + out.station + '」，請先新增地面 POI');
        var rd = out.ra_deg != null && out.dec_deg != null, ae = out.az_deg != null && out.el_deg != null;
        if (!rd && !ae) errs.push('需要 RA＋Dec 或 方位角＋仰角');
      } else if (kind === 'orbits') {
        if (!/^1 /.test(out.line1) || !/^2 /.test(out.line2) || out.line1.length < 68 || out.line2.length < 68) errs.push('TLE 兩行格式錯誤（第 1 行以「1 」、第 2 行以「2 」開頭，至少 68 字元）');
        else {
          var a = tleNorad(out.line1), b = tleNorad(out.line2);
          if (a == null || a !== b) errs.push('TLE 兩行的 NORAD 編號不一致或無法辨識');
          else if (out.norad != null && out.norad !== a) errs.push('NORAD ' + out.norad + ' 與 TLE 內的 ' + a + ' 不符');
          else out.norad = a;
        }
      } else if (kind === 'claims') {
        if (!out.confidence) out.confidence = SRC_CONF[out.source_type] || 'low';
      }
    }
    return { rec: errs.length ? null : out, errors: errs };
  }

  // ── CSV ──
  function parseCsv(text) {
    text = String(text || '').replace(/^﻿/, '');
    var rows = [], row = [], f = '', q = false, i, c;
    for (i = 0; i < text.length; i++) {
      c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; }
        else f += c;
      } else if (c === '"') q = true;
      else if (c === ',') { row.push(f); f = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = ''; }
      else f += c;
    }
    if (f !== '' || row.length) { row.push(f); rows.push(row); }
    return rows.filter(function (r) { return r.some(function (x) { return String(x).trim() !== ''; }); });
  }
  function detectKind(head) {
    var h = {}; head.forEach(function (x) { h[String(x).trim().toLowerCase()] = 1; });
    if (h.line1) return 'orbits';
    if (h.station || h.time) return 'observations';
    if (h.lat || h.lon) return 'pois';
    if (h.norad && h.name) return 'claims';
    return null;
  }
  /* CSV 文字 → { kind, records:[{_row, ...}], error } */
  function fromCsv(text, forceKind) {
    var rows = parseCsv(text);
    if (rows.length < 2) return { kind: null, records: [], error: 'CSV 至少需要標題列與一筆資料' };
    var head = rows[0].map(function (x) { return String(x).trim().toLowerCase(); });
    var kind = forceKind || detectKind(head);
    if (!kind) return { kind: null, records: [], error: '無法由標題列判斷資料種類（需含 line1／station／lat／norad+name 等欄位）' };
    var keys = KINDS[kind].fields.map(function (f) { return f.k; }).concat(['review', 'review_note']);
    var recs = rows.slice(1).map(function (r, i) {
      var o = { _row: i + 2 };
      head.forEach(function (k, j) { if (keys.indexOf(k) >= 0) o[k] = r[j] == null ? '' : r[j]; });
      return o;
    });
    return { kind: kind, records: recs, error: null };
  }
  function csvCell(v) { v = v == null ? '' : String(v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function toCsv(kind, recs) {
    var keys = KINDS[kind].fields.map(function (f) { return f.k; }).concat(META);
    return '﻿' + keys.join(',') + '\n' + recs.map(function (r) { return keys.map(function (k) { return csvCell(r[k]); }).join(','); }).join('\n') + '\n';
  }
  function template(kind) {
    var ex = {
      pois: 'name,lat,lon,alt_m,kind,note\n台北觀測站,25.0330,121.5654,10,station,\n',
      observations: 'norad,station,time,ra_deg,dec_deg,az_deg,el_deg,mag,observer,source,source_url,note\n25544,台北觀測站,2026-11-25 11:02:30,215.123,32.456,,,2.5,王小明,own,,\n',
      orbits: 'norad,line1,line2,source,source_name,source_url,note\n,"1 25544U 98067A   26329.50000000  .00016717  00000-0  10270-3 0  9994","2 25544  51.6400 208.9163 0006317  69.9862 290.2104 15.50000000000017",amateur,classfd,,\n',
      claims: 'norad,name,source_type,source_url,confidence,note\n101415,SJ-24,news,https://example.org/news,,\n'
    };
    return '﻿' + ex[kind];
  }

  window.OBSM = { SRC: SRC, SRC_CONF: SRC_CONF, CONF: CONF, REVIEW: REVIEW, POI_KIND: POI_KIND, KINDS: KINDS, META: META,
    validate: validate, parseTime: parseTime, fromCsv: fromCsv, toCsv: toCsv, template: template, parseCsv: parseCsv };
})();
