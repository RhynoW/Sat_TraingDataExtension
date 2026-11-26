/* 過頂預報頁（src/forecast.rs） */
(function () {
  'use strict';
  var ME = null, JOB = null, TIMER = null;
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function msg(id, t, ok) { var el = $(id); el.textContent = t || ''; el.className = 'msg ' + (ok ? 'ok' : 'bad'); }
  function api(method, url, body) {
    var o = { method: method, headers: {} };
    if (body !== undefined) { o.body = JSON.stringify(body); o.headers['Content-Type'] = 'application/json'; }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=/forecast'; throw new Error('請先登入'); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function tzh() { return parseFloat($('tz').value); }
  function fmt(iso) {
    if (!iso) return '';
    var d = new Date(new Date(iso).getTime() + tzh() * 3600000);
    return d.toISOString().replace('T', ' ').slice(5, 19);
  }

  // ── 中心點 ──
  function siteRow(s) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><input class="s-name" style="width:130px"/></td><td><input class="s-lat" type="number" step="0.0001" style="width:100px"/></td>' +
      '<td><input class="s-lon" type="number" step="0.0001" style="width:100px"/></td><td><input class="s-alt" type="number" step="1" style="width:80px"/></td>' +
      '<td><input class="s-r" type="number" min="0" max="3000" step="1" style="width:80px"/></td><td><input class="s-note" style="width:160px"/></td>' +
      '<td><button class="dan">刪除</button></td>';
    tr.querySelector('.s-name').value = s.name || '';
    tr.querySelector('.s-lat').value = s.lat != null ? s.lat : '';
    tr.querySelector('.s-lon').value = s.lon != null ? s.lon : '';
    tr.querySelector('.s-alt').value = s.alt_m || 0;
    tr.querySelector('.s-r').value = s.radius_km || 0;
    tr.querySelector('.s-note').value = s.note || '';
    tr.querySelector('button').onclick = function () { tr.remove(); };
    document.querySelector('#sites tbody').appendChild(tr);
  }
  function sites() {
    return Array.prototype.map.call(document.querySelectorAll('#sites tbody tr'), function (tr) {
      var g = function (c) { return tr.querySelector(c).value; };
      return { name: g('.s-name').trim(), lat: parseFloat(g('.s-lat')), lon: parseFloat(g('.s-lon')), alt_m: parseFloat(g('.s-alt')) || 0, radius_km: parseFloat(g('.s-r')) || 0, note: g('.s-note') };
    });
  }
  function addSite() { siteRow({ name: '', lat: '', lon: '', alt_m: 0, radius_km: 0 }); }
  function saveSites() {
    var s = sites();
    if (s.some(function (x) { return !x.name || isNaN(x.lat) || isNaN(x.lon); })) { msg('site-msg', '每個中心點都需要名稱與經緯度'); return; }
    api('PUT', '/api/forecast/sites', s).then(function (j) {
      msg('site-msg', '已寫入地面 POI：更新 ' + j.updated + ' 個、新增 ' + j.added + ' 個（觀測與身分驗證頁同步可見）', true);
      return api('GET', '/api/forecast/sites').then(function (k) { POIS = k.pois || []; fillPoiSel(); });
    }).catch(function (e) { msg('site-msg', e.message); });
  }

  // ── 從地面 POI 加入（與「觀測與身分驗證」共用同一份 POI 清單）──
  var POIS = [];
  function fillPoiSel() {
    var sel = $('poi-sel'); if (!sel) return;
    sel.innerHTML = POIS.length ? POIS.map(function (p, i) { return '<option value="' + i + '">' + esc(p.name) + '（' + (p.kind === 'site' ? '關注地點' : '觀測站') + (p.radius_km ? '・' + p.radius_km + ' km' : '') + '）</option>'; }).join('')
      : '<option value="">（尚無地面 POI）</option>';
  }
  function addPoi() {
    var p = POIS[+$('poi-sel').value]; if (!p) return;
    var dup = sites().some(function (s) { return s.name.toUpperCase() === String(p.name).toUpperCase(); });
    if (dup) { msg('site-msg', '「' + p.name + '」已在中心點清單中'); return; }
    siteRow({ name: p.name, lat: p.lat, lon: p.lon, alt_m: p.alt_m || 0, radius_km: p.radius_km || 0, note: p.note || '' });
  }


  // ── 群組 ──
  var SENS = { optical: '光學', radar: '雷達', sigint: '電子偵察', other: '其他' };
  function loadGroups() {
    return api('GET', '/api/satadmin/groups?members=0').then(function (j) {
      var gs = j.groups.slice().sort(function (a, b) { return a.path.localeCompare(b.path, 'zh-Hant'); });
      $('groups').innerHTML = gs.length ? gs.map(function (g) {
        var depth = (g.path.match(/ \/ /g) || []).length;
        return '<label style="padding-left:' + (depth * 18) + 'px"><input type="checkbox" class="g-chk" value="' + g.id + '"/> ' + esc(g.name) +
          ' <span class="muted">（' + g.count_total + ' 顆' + (g.eff_sensor ? '・' + (SENS[g.eff_sensor] || g.eff_sensor) : '') + (g.eff_look_deg != null ? '・偵照 ' + g.eff_look_deg + '°' : '') + '）</span></label>';
      }).join('') + '<div class="muted" style="margin-top:4px">勾選上層群組即包含所有子群組。</div>' :
        '尚無群組，可到「衛星管理」建立，或直接在下方輸入 NORAD ID。';
    }).catch(function (e) { $('groups').textContent = e.message; });
  }


  // 衛星屬性存在本機資料目錄 user_private\sat_attrs.json（伺服器端讀取，不上傳）
  var ATTRB = {
    load: function () { return api('GET', '/api/forecast/attrs').then(function (j) { return j.attrs || []; }); },
    save: function (rows) { return api('PUT', '/api/forecast/attrs', rows).then(function (j) { return j.count; }); }
  };

  // ── 衛星屬性（簡要版輸出用：衛星隸屬、解析度；兩版共用，儲存方式見 ATTRB）──
  function attrRow(a) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><input class="a-norad" type="number" min="1" style="width:90px"/></td><td class="a-name muted"></td>' +
      '<td><input class="a-own" style="width:100px"/></td><td><input class="a-res" style="width:140px"/></td><td><input class="a-note" style="width:200px"/></td>' +
      '<td><button class="dan">刪除</button></td>';
    tr.querySelector('.a-norad').value = a.norad || '';
    tr.querySelector('.a-name').textContent = a.name || '';
    tr.querySelector('.a-own').value = a.owner || '';
    tr.querySelector('.a-own').placeholder = a.default_owner || '依 SATCAT';
    tr.querySelector('.a-res').value = a.resolution || '';
    tr.querySelector('.a-note').value = a.note || '';
    tr.querySelector('button').onclick = function () { tr.remove(); };
    document.querySelector('#attrs tbody').appendChild(tr);
  }
  function attrsFromTable() {
    return Array.prototype.map.call(document.querySelectorAll('#attrs tbody tr'), function (tr) {
      var g = function (c) { return tr.querySelector(c).value.trim(); };
      return { norad: parseInt(g('.a-norad'), 10) || 0, owner: g('.a-own'), resolution: g('.a-res'), note: g('.a-note'), name: tr.querySelector('.a-name').textContent };
    }).filter(function (a) { return a.norad > 0 && (a.owner || a.resolution || a.note); });
  }
  var ATTRS = [];
  function loadAttrs() {
    return ATTRB.load().then(function (rows) {
      ATTRS = rows || [];
      document.querySelector('#attrs tbody').innerHTML = '';
      ATTRS.forEach(attrRow);
      $('attr-count').textContent = ATTRS.length ? '（' + ATTRS.length + ' 筆）' : '';
    }).catch(function (e) { msg('attr-msg', e.message); });
  }
  function saveAttrs() {
    var rows = attrsFromTable(), seen = {}, dup = [];
    rows.forEach(function (a) { if (seen[a.norad]) dup.push(a.norad); seen[a.norad] = 1; });
    if (dup.length) { msg('attr-msg', 'NORAD 重複：' + dup.join(', ')); return; }
    ATTRB.save(rows.map(function (a) { return { norad: a.norad, owner: a.owner, resolution: a.resolution, note: a.note }; }))
      .then(function (n) { msg('attr-msg', '已儲存 ' + n + ' 筆', true); return loadAttrs(); })
      .catch(function (e) { msg('attr-msg', e.message); });
  }
  function addAttr() { attrRow({}); }
  function parseCsv(text) {
    var rows = [], row = [], f = '', q = false, i, c;
    text = text.replace(/^\uFEFF/, '');
    for (i = 0; i < text.length; i++) {
      c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ',') { row.push(f); f = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = ''; }
      else f += c;
    }
    if (f || row.length) { row.push(f); rows.push(row); }
    return rows.filter(function (r) { return r.some(function (x) { return x.trim(); }); });
  }
  function importAttrs(inp) {
    var file = inp.files && inp.files[0]; if (!file) return;
    file.text().then(function (text) {
      var rows = parseCsv(text); inp.value = '';
      if (!rows.length) { msg('attr-msg', '檔案是空的'); return; }
      var h = rows[0].map(function (x) { return x.trim().toUpperCase(); });
      var col = function (keys) { return h.findIndex(function (x) { return keys.some(function (k) { return x.indexOf(k) >= 0; }); }); };
      var cn = col(['NORAD']), co = col(['隸屬']), cr = col(['解析度', 'RESOLUTION']), ce = col(['備註', 'NOTE']);
      if (cn < 0) { msg('attr-msg', '找不到 NORAD 欄（第一列需為欄名：NORAD,名稱,衛星隸屬,解析度,備註）'); return; }
      var cur = {}, upd = 0, add = 0, bad = 0;
      document.querySelectorAll('#attrs tbody tr').forEach(function (tr) { var n = parseInt(tr.querySelector('.a-norad').value, 10); if (n) cur[n] = tr; });
      rows.slice(1).forEach(function (r) {
        var n = parseInt(String(r[cn] || '').trim(), 10);
        if (!(n > 0)) { bad++; return; }
        var v = { owner: co >= 0 ? (r[co] || '').trim() : null, resolution: cr >= 0 ? (r[cr] || '').trim() : null, note: ce >= 0 ? (r[ce] || '').trim() : null };
        var tr = cur[n];
        if (tr) {
          if (v.owner !== null) tr.querySelector('.a-own').value = v.owner;
          if (v.resolution !== null) tr.querySelector('.a-res').value = v.resolution;
          if (v.note !== null) tr.querySelector('.a-note').value = v.note;
          upd++;
        } else {
          attrRow({ norad: n, owner: v.owner || '', resolution: v.resolution || '', note: v.note || '' });
          cur[n] = document.querySelector('#attrs tbody tr:last-child'); add++;
        }
      });
      $('attr-card').open = true;
      msg('attr-msg', '已匯入：更新 ' + upd + ' 筆、新增 ' + add + ' 筆' + (bad ? '、略過 ' + bad + ' 列（NORAD 不正確）' : '') + '；請按「儲存屬性表」', true);
    });
  }
  function exportAttrs() {
    var q = function (s) { s = String(s == null ? '' : s); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    var lines = ['NORAD,名稱,衛星隸屬,解析度,備註'].concat(attrsFromTable().map(function (a) { return [a.norad, a.name, a.owner, a.resolution, a.note].map(q).join(','); }));
    var url = URL.createObjectURL(new Blob(['\uFEFF' + lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' }));
    var el = document.createElement('a'); el.href = url; el.download = 'sat_attrs.csv'; document.body.appendChild(el); el.click(); el.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function attrsBody() {
    var o = {}; ATTRS.forEach(function (a) { o[a.norad] = { owner: a.owner || '', resolution: a.resolution || '' }; }); return o;
  }

  // ── 執行 ──
  function setLook(v) { $('look').value = v; }
  function run() {
    var s = sites();
    if (!s.length) { msg('run-msg', '請至少設定一個中心點'); return; }
    if (s.some(function (x) { return !x.name || isNaN(x.lat) || isNaN(x.lon); })) { msg('run-msg', '每個中心點都需要名稱與經緯度'); return; }
    var groups = Array.prototype.map.call(document.querySelectorAll('.g-chk:checked'), function (c) { return c.value; });
    var norads = ($('norads').value.match(/\d+/g) || []).map(Number);
    var start = null;
    if ($('start').value) {
      var local = new Date($('start').value + 'Z').getTime() - tzh() * 3600000;
      start = new Date(local).toISOString().replace('.000Z', 'Z');
    }
    var body = { sites: s, groups: groups, norads: norads, start: start, days: parseFloat($('days').value), mask_deg: parseFloat($('mask').value),
      look_deg: parseFloat($('look').value), look_override: $('look-ov').checked, only_coverable: $('only-cov').checked, daylight: $('daylight').value,
      sun_min_deg: parseFloat($('sunmin').value) || 0, tz_hours: tzh(), error_estimate: $('err').checked, history_days: parseFloat($('hist').value) || 60 , attrs: attrsBody() };
    $('run').disabled = true; msg('run-msg', '已送出…', true); $('prog').style.width = '0';
    api('POST', '/api/forecast/run', body).then(function (j) { JOB = j.job_id; poll(); })
      .catch(function (e) { msg('run-msg', e.message); $('run').disabled = false; });
  }
  function poll() {
    clearTimeout(TIMER);
    api('GET', '/api/forecast/jobs/' + JOB).then(function (j) {
      $('prog').style.width = (j.total ? Math.round(100 * j.done / j.total) : 0) + '%';
      $('stage').textContent = j.stage + '（' + j.done + ' / ' + j.total + ' 顆）';
      if (j.state === 'running') { TIMER = setTimeout(poll, 800); return; }
      $('run').disabled = false;
      if (j.state === 'error') { msg('run-msg', j.error); return; }
      msg('run-msg', '完成', true); $('stage').textContent = '';
      show(j);
    }).catch(function (e) { msg('run-msg', e.message); $('run').disabled = false; });
  }
  function show(j) {
    var s = j.summary;
    $('result').style.display = '';
    var base = '/api/forecast/jobs/' + j.id + '/';
    $('dl-passes').href = base + 'passes.csv'; $('dl-sun').href = base + 'sun.csv'; $('dl-err').href = base + 'errors.csv';
    $('dl-brief-a').href = base + 'brief_a.csv'; $('dl-brief-b').href = base + 'brief_b.csv';
    $('sum').innerHTML = '期間 ' + esc(fmt(s.start)) + ' ～ ' + esc(fmt(s.end)) + '（' + s.days + ' 天）・' + s.sats + ' 顆衛星・' + s.sites + ' 個中心點・共 <b>' + s.passes.toLocaleString() + '</b> 筆過頂' +
      (s.not_in_catalog.length ? '<div class="muted">不在目前目錄、未計算：' + s.not_in_catalog.join(', ') + '</div>' : '') +
      '<table style="width:auto;margin-top:8px"><thead><tr><th>中心點</th><th>過頂</th><th>可偵照</th><th>日照</th></tr></thead><tbody>' +
      s.per_site.map(function (p) { return '<tr><td>' + esc(p.site) + '</td><td class="num">' + p.passes + '</td><td class="num">' + p.coverable + '</td><td class="num">' + p.sunlit + '</td></tr>'; }).join('') + '</tbody></table>';
    var fe = s.fleet_error || [];
    $('errbox').innerHTML = fe.length ? '<div class="muted" style="margin:8px 0 4px">歷史 TLE 預報誤差（所選衛星合併）：</div><table style="width:auto;margin-bottom:10px"><thead><tr><th>提前天數</th><th>樣本</th><th>位置誤差中位數 km</th><th>位置 p90 km</th><th>時間誤差中位數 s</th><th>時間 p90 s</th></tr></thead><tbody>' +
      fe.map(function (e) { return '<tr><td class="num">' + e.lead_days + '</td><td class="num">' + e.n + '</td><td class="num">' + e.pos_med_km + '</td><td class="num">' + e.pos_p90_km + '</td><td class="num">' + e.time_med_s + '</td><td class="num">' + e.time_p90_s + '</td></tr>'; }).join('') +
      '</tbody></table>' : '';
    document.querySelector('#pv tbody').innerHTML = (j.preview || []).map(function (p) {
      var img = p.coverable ? fmt(p.img_start).slice(6) + '–' + fmt(p.img_end).slice(6) + '（' + p.img_duration_s + ' s）' : '<span class="no">—</span>';
      return '<tr><td>' + esc(p.site) + '</td><td class="num">' + p.norad_id + '</td><td>' + esc(p.name) + '</td><td>' + esc(p.group) + '</td><td>' + fmt(p.start) + '</td><td>' + fmt(p.tca) +
        '</td><td>' + fmt(p.end).slice(6) + '</td><td class="num">' + p.max_el_deg + '°</td><td class="num">' + p.min_off_nadir_deg + '°</td><td class="num">' + p.look_deg + '°</td><td>' + img +
        '</td><td class="' + (p.sunlit ? 'yes' : 'no') + '">' + (p.sunlit ? '日照' : '夜間') + '</td><td class="num">' + p.sun_el_deg + '°</td><td class="num">' + (p.est_err_s != null ? '±' + p.est_err_s : '') + '</td></tr>';
    }).join('') || '<tr><td colspan="14" class="muted">期間內沒有符合條件的過頂</td></tr>';
  }

  window.FC = { addPoi: addPoi, addSite: addSite, saveSites: saveSites, run: run, setLook: setLook,
    addAttr: addAttr, saveAttrs: saveAttrs, importAttrs: importAttrs, exportAttrs: exportAttrs };
  loadAttrs();
  api('GET', '/api/auth/me').then(function (m) {
    ME = m;
    if (!(m.perms || []).includes('modify')) { $('btn-save-sites').style.display = 'none'; $('btn-save-attrs').style.display = 'none'; }
  });
  api('GET', '/api/forecast/sites').then(function (j) { j.sites.forEach(siteRow); POIS = j.pois || []; fillPoiSel(); });
  loadGroups();
})();
