/* 觀測與身分驗證頁：線上版與 Rust 單機版共用。資料存取透過 window.OBS_BACKEND
   （線上版 obs_store.js＝瀏覽器 localStorage；單機版 obs_server.js＝伺服器 user_private，含帳號權限）。 */
(function () {
  'use strict';
  var M = window.OBSM, B = window.OBS_BACKEND, D = { pois: [], observations: [], orbits: [], claims: [] }, CK = null, CAPS = {}, EDIT = {};
  var IDENT = { confirmed: '已確認', probable: '可能', claimed: '有主張（未複核）', disputed: '有爭議', unknown: '未知' };
  var ORBIT = { corroborated: '與目錄一致', close: '與目錄接近', divergent: '與目錄不一致', independent_only: '只有獨立軌道解', catalog_only: '只有目錄 TLE', none: '無軌道資料', unknown: '—' };
  var OBSV = { consistent: '符合', mixed: '部分符合', marginal: '勉強符合', inconsistent: '不符合', none: '無觀測' };
  var C_OBS = { consistent: '符合', marginal: '勉強符合', inconsistent: '不符合', unknown: '無法比對' };
  var C_ORB = { consistent: '一致', close: '接近', divergent: '不一致', no_catalog: '無目錄 TLE', unknown: '無法比對' };
  var C_CLM = { matches_official: '與正式名稱相同', differs_official: '與正式名稱不同', disputed: '有其他主張', uncontested: '無其他主張', unknown: '—' };
  var GOOD = { confirmed: 'ok', corroborated: 'ok', consistent: 'ok', matches_official: 'ok', probable: 'warn', claimed: 'warn', close: 'warn', marginal: 'warn', mixed: 'warn', uncontested: 'warn',
    disputed: 'bad', divergent: 'bad', inconsistent: 'bad', differs_official: 'bad' };
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function msg(id, t, ok) { var el = $(id); if (!el) return; el.textContent = t || ''; el.className = 'msg ' + (ok ? 'ok' : 'bad'); }
  function badge(code, label) { return '<span class="st st-' + (GOOD[code] || 'na') + '">' + esc(label || code) + '</span>'; }
  function link(u) { return u ? ' <a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">🔗</a>' : ''; }
  function stamp() { var d = new Date(); return d.getFullYear() + ('0' + (d.getMonth() + 1)).slice(-2) + ('0' + d.getDate()).slice(-2) + '_' + ('0' + d.getHours()).slice(-2) + ('0' + d.getMinutes()).slice(-2); }
  function download(name, text, type) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: type || 'text/csv;charset=utf-8' }));
    a.download = name; document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  function chk(kind, id) { if (!CK) return null; return (CK[kind] || []).find(function (c) { return c.id === id; }) || null; }

  // ── 分頁 ──
  document.querySelectorAll('#tabs button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('#tabs button').forEach(function (x) { x.classList.toggle('on', x === b); });
      document.querySelectorAll('.tab').forEach(function (x) { x.classList.toggle('on', x.id === 't-' + b.dataset.t); });
    });
  });

  // ── 各種紀錄的表格 ──
  var COLS = {
    pois: [['名稱', function (r) { return esc(r.name); }], ['緯度', function (r) { return r.lat; }], ['經度', function (r) { return r.lon; }], ['高度 m', function (r) { return r.alt_m; }],
      ['類型', function (r) { return esc(M.POI_KIND[r.kind] || r.kind); }], ['使用中', function (r) { var n = D.observations.filter(function (o) { return String(o.station).toUpperCase() === String(r.name).toUpperCase(); }).length; return n ? n + ' 筆觀測' : '—'; }],
      ['備註', function (r) { return esc(r.note); }]],
    observations: [['NORAD', function (r) { return r.norad == null ? '—' : r.norad; }], ['觀測站', function (r) { return esc(r.station); }], ['時間（UTC）', function (r) { return esc(r.time); }],
      ['方向', function (r) { return r.ra_deg != null && r.dec_deg != null ? 'RA ' + r.ra_deg + '° / Dec ' + r.dec_deg + '°' : 'Az ' + r.az_deg + '° / El ' + r.el_deg + '°'; }],
      ['星等', function (r) { return r.mag == null ? '—' : r.mag; }], ['觀測者／來源', function (r) { return esc(r.observer || '—') + '<div class="muted">' + esc(M.SRC[r.source] || r.source) + link(r.source_url) + '</div>'; }],
      ['交叉驗證', function (r) { return obsChk(chk('observations', r.id)); }]],
    orbits: [['NORAD', function (r) { return r.norad; }], ['TLE', function (r) { return '<div class="mono">' + esc(r.line1) + '<br>' + esc(r.line2) + '</div>'; }],
      ['來源', function (r) { return esc(M.SRC[r.source] || r.source) + (r.source_name ? '<div class="muted">' + esc(r.source_name) + '</div>' : '') + link(r.source_url); }],
      ['交叉驗證', function (r) { return orbChk(chk('orbits', r.id)); }]],
    claims: [['NORAD', function (r) { return r.norad; }], ['主張的名稱', function (r) { return esc(r.name); }], ['來源類型', function (r) { return esc(M.SRC[r.source_type] || r.source_type) + link(r.source_url); }],
      ['可信度', function (r) { return esc(M.CONF[r.confidence] || r.confidence); }], ['備註', function (r) { return esc(r.note); }], ['交叉驗證', function (r) { return clmChk(chk('claims', r.id)); }]]
  };
  function warnHtml(c) {
    return (c.errors || []).map(function (e) { return '<div class="bad">✖ ' + esc(e) + '</div>'; }).join('') + (c.warnings || []).map(function (w) { return '<div class="warn">⚠ ' + esc(w) + '</div>'; }).join('');
  }
  function obsChk(c) {
    if (!c) return '<span class="muted">尚未驗證</span>';
    var h = badge(c.status, C_OBS[c.status]) + (c.sep_deg != null ? ' 殘差 <b>' + c.sep_deg + '°</b>' : '');
    if (c.predicted) h += '<div class="muted">預測 ' + (c.frame === 'radec' ? 'RA ' + c.predicted.ra + '° Dec ' + c.predicted.dec + '°' : 'Az ' + c.predicted.az + '° El ' + c.predicted.el + '°') + '（仰角 ' + c.predicted.el + '°、距離 ' + c.predicted.rng_km + ' km）</div>';
    if ((c.by_orbit || []).length) h += '<div class="muted">以軌道解：' + c.by_orbit.map(function (b) { return b.orbit_id + ' ' + b.sep_deg + '°'; }).join('、') + '</div>';
    if ((c.candidates || []).length > 1) h += '<div class="muted" title="' + esc(c.candidates.map(function (x) { return x.norad + ' ' + x.name + '：' + x.sep_deg + '°'; }).join('\n')) + '">同次發射比對：' + esc(c.candidates.slice(0, 3).map(function (x) { return x.norad + ' ' + x.sep_deg + '°'; }).join('、')) + '</div>';
    return h + warnHtml(c);
  }
  function orbChk(c) {
    if (!c) return '<span class="muted">尚未驗證</span>';
    var h = badge(c.status, C_ORB[c.status]) + (c.dmax_km != null ? ' 最大差 <b>' + c.dmax_km + ' km</b>（曆元 ' + c.d0_km + ' km）' : '');
    if (c.epoch) h += '<div class="muted">曆元 ' + esc(c.epoch) + ' UTC' + (c.catalog_epoch_days != null ? '；目錄 TLE 相差 ' + c.catalog_epoch_days + ' 天' : '') + '</div>';
    if ((c.candidates || []).length) h += '<div class="muted" title="' + esc(c.candidates.map(function (x) { return x.norad + ' ' + x.name + '：' + x.dmax_km + ' km'; }).join('\n')) + '">同次發射最接近：' + esc(c.candidates.slice(0, 3).map(function (x) { return x.norad + ' ' + x.name + ' ' + x.dmax_km + ' km'; }).join('、')) + '</div>';
    return h + warnHtml(c);
  }
  function clmChk(c) {
    if (!c) return '<span class="muted">尚未驗證</span>';
    return badge(c.status, C_CLM[c.status]) + warnHtml(c);
  }
  function reviewCell(kind, r) {
    var h = badge(r.review === 'accepted' ? 'confirmed' : r.review === 'rejected' || r.review === 'disputed' ? 'disputed' : 'claimed', M.REVIEW[r.review] || '未複核');
    if (r.reviewer || r.reviewed_at) h += '<div class="muted">' + esc(r.reviewer || '') + ' ' + esc(String(r.reviewed_at || '').replace('T', ' ').replace('Z', '')) + '</div>';
    if (r.review_note) h += '<div class="muted">' + esc(r.review_note) + '</div>';
    return h;
  }
  function renderKind(kind) {
    var K = M.KINDS[kind], rows = D[kind].slice().reverse(), cols = COLS[kind];
    var f = ($('f-' + kind) || {}).value || '';
    if (f) rows = rows.filter(function (r) { return JSON.stringify(r).toUpperCase().indexOf(f.toUpperCase()) >= 0; });
    $('n-' + kind).textContent = D[kind].length;
    var head = '<tr>' + cols.map(function (c) { return '<th>' + c[0] + '</th>'; }).join('') + (kind === 'pois' ? '' : '<th>複核</th>') + '<th>操作</th></tr>';
    var body = rows.map(function (r) {
      var ops = (CAPS.canEdit ? '<button onclick="OBS.edit(\'' + kind + '\',\'' + r.id + '\')">編輯</button> <button class="dan" onclick="OBS.del(\'' + kind + '\',\'' + r.id + '\')">刪除</button> ' : '') +
        (CAPS.canReview && kind !== 'pois' ? '<button onclick="OBS.review(\'' + kind + '\',\'' + r.id + '\')">複核</button>' : '');
      return '<tr id="row-' + r.id + '">' + cols.map(function (c) { return '<td>' + c[1](r) + '</td>'; }).join('') + (kind === 'pois' ? '' : '<td>' + reviewCell(kind, r) + '</td>') +
        '<td style="white-space:nowrap">' + (ops || '<span class="muted">唯讀</span>') + '<div class="muted">' + esc(r.id) + (r.by ? '・' + esc(r.by) : '') + '</div></td></tr>';
    }).join('') || '<tr><td colspan="' + (cols.length + 2) + '" class="muted">尚無' + K.label + (CAPS.canEdit ? '，可用上方「新增」或到「匯入匯出」貼上 CSV' : '') + '</td></tr>';
    $('tb-' + kind).innerHTML = '<thead>' + head + '</thead><tbody>' + body + '</tbody>';
  }
  function renderAll() { ['observations', 'orbits', 'claims', 'pois'].forEach(renderKind); renderSummary(); }

  // ── 新增／編輯表單 ──
  function formHtml(kind, r) {
    return M.KINDS[kind].fields.map(function (f) {
      var v = r && r[f.k] != null ? r[f.k] : (f.def != null && !r ? f.def : ''), id = 'in-' + kind + '-' + f.k, inp;
      if (f.type === 'sel') inp = '<select id="' + id + '">' + (f.def === '' ? '<option value="">（依來源類型）</option>' : '') + Object.keys(f.opts).map(function (k) { return '<option value="' + k + '"' + (String(v) === k ? ' selected' : '') + '>' + esc(f.opts[k]) + '</option>'; }).join('') + '</select>';
      else if (kind === 'observations' && f.k === 'station') inp = '<select id="' + id + '">' + D.pois.map(function (p) { return '<option' + (String(v).toUpperCase() === String(p.name).toUpperCase() ? ' selected' : '') + '>' + esc(p.name) + '</option>'; }).join('') + '</select>' + (D.pois.length ? '' : ' <span class="bad">請先新增地面 POI</span>');
      else inp = '<input id="' + id + '" value="' + esc(v) + '"' + (f.mono ? ' class="mono" style="width:100%;max-width:640px"' : f.type === 'num' ? ' style="width:140px"' : ' style="width:100%;max-width:420px"') + (f.time ? ' placeholder="2026-11-25 11:02:30"' : '') + '/>';
      return '<label>' + esc(f.l) + (f.req ? ' *' : '') + '</label><div>' + inp + '</div>';
    }).join('');
  }
  function openForm(kind, id) {
    var r = id ? D[kind].find(function (x) { return x.id === id; }) : null;
    EDIT[kind] = id || null;
    var box = $('form-' + kind);
    box.style.display = '';
    box.innerHTML = '<h2>' + (id ? '編輯 ' + esc(id) : '新增' + M.KINDS[kind].label) + '</h2><div class="grid2">' + formHtml(kind, r) + '</div>' +
      (kind === 'observations' ? '<div class="muted" style="margin:6px 0">RA/Dec 請填 J2000；或改填方位角＋仰角（站心、未修正大氣折射）。時間一律 UTC。</div>' : '') +
      '<div class="row" style="margin-top:8px"><button class="pri" onclick="OBS.save(\'' + kind + '\')">儲存</button><button onclick="OBS.cancel(\'' + kind + '\')">取消</button><span id="fm-' + kind + '" class="msg"></span></div>';
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function readForm(kind) { var o = {}; M.KINDS[kind].fields.forEach(function (f) { var el = $('in-' + kind + '-' + f.k); o[f.k] = el ? el.value : ''; }); return o; }
  function save(kind) {
    var rec = readForm(kind), id = EDIT[kind];
    var p = id ? B.update(kind, id, rec) : B.add(kind, [rec]).then(function (r) { if (r.errors.length) throw new Error(r.errors.map(function (e) { return e.msg; }).join('；')); return r; });
    p.then(function () { cancel(kind); return reload(); }).then(function () { msg('m-' + kind, id ? '已更新 ' + id : '已新增', true); })
      .catch(function (e) { msg('fm-' + kind, e.message); });
  }
  function cancel(kind) { EDIT[kind] = null; var b = $('form-' + kind); b.style.display = 'none'; b.innerHTML = ''; }
  function del(kind, id) {
    if (!confirm('刪除 ' + id + '？')) return;
    B.remove(kind, id).then(reload).then(function () { msg('m-' + kind, '已刪除 ' + id, true); }).catch(function (e) { msg('m-' + kind, e.message); });
  }
  function review(kind, id) {
    var r = D[kind].find(function (x) { return x.id === id; }), tr = $('row-' + id), td = tr.children[tr.children.length - 2];
    td.innerHTML = '<select id="rv-' + id + '">' + Object.keys(M.REVIEW).map(function (k) { return '<option value="' + k + '"' + ((r.review || 'unreviewed') === k ? ' selected' : '') + '>' + M.REVIEW[k] + '</option>'; }).join('') +
      '</select><input id="rvn-' + id + '" placeholder="複核說明（選填）" style="width:100%;margin-top:4px" value="' + esc(r.review_note || '') + '"/><div style="margin-top:4px"><button class="pri" id="rvs-' + id + '">儲存</button> <button id="rvc-' + id + '">取消</button></div>';
    $('rvc-' + id).onclick = function () { renderKind(kind); };
    $('rvs-' + id).onclick = function () {
      B.review(kind, id, { review: $('rv-' + id).value, review_note: $('rvn-' + id).value }).then(reload).then(function () { msg('m-' + kind, id + ' 已複核', true); }).catch(function (e) { msg('m-' + kind, e.message); });
    };
  }

  // ── 交叉驗證與衛星摘要 ──
  function runCheck() {
    msg('ck-msg', '計算中…', true);
    return B.check().then(function (j) { CK = j; renderAll(); msg('ck-msg', '完成：' + j.sats.length + ' 顆衛星、' + j.observations.length + ' 筆觀測、' + j.orbits.length + ' 筆軌道解、' + j.claims.length + ' 筆身分主張', true); })
      .catch(function (e) { msg('ck-msg', e.message); });
  }
  function renderSummary() {
    var tb = $('tb-sum');
    if (!CK) { tb.innerHTML = '<tbody><tr><td class="muted">按「執行交叉驗證」計算。資料有變動時請重新執行。</td></tr></tbody>'; return; }
    var t = CK.thresholds;
    $('ck-th').textContent = '門檻：觀測殘差 ≤ ' + t.obs_ok_deg + '° 符合、≤ ' + t.obs_marginal_deg + '° 勉強符合；軌道解與目錄 TLE 在曆元 ±' + t.grid_hours + ' 小時內最大位置差 ≤ ' + t.orbit_ok_km + ' km 一致、≤ ' + t.orbit_close_km + ' km 接近。';
    tb.innerHTML = '<thead><tr><th>NORAD</th><th>名稱</th><th>發射群組</th><th>身分</th><th>軌道</th><th>觀測</th><th>任務／能力</th><th>紀錄</th></tr></thead><tbody>' + CK.sats.map(function (s) {
      var L = s.layers;
      return '<tr class="sum-row" data-n="' + s.norad + '" style="cursor:pointer"><td class="num">' + s.norad + (s.in_catalog ? '' : '<div class="muted">不在目錄</div>') + '</td><td>' + esc(s.name || '—') +
        (s.official_name ? '<div class="muted">正式名稱 ' + esc(s.official_name) + '</div>' : '') + (L.candidate_mission.value ? '<div class="muted">主張：' + esc(L.candidate_mission.value.join('、')) + '</div>' : '') +
        '</td><td>' + esc(s.launch_tag || '—') + '</td><td>' + badge(s.identity_status, IDENT[s.identity_status]) + (L.individual.value ? '<div class="muted">' + esc(L.individual.value) + '</div>' : '') +
        '</td><td>' + badge(s.orbit_status, ORBIT[s.orbit_status]) + '</td><td>' + badge(s.observation_status, OBSV[s.observation_status]) +
        '</td><td class="muted">未知（不自動歸因）</td><td class="muted">觀測 ' + s.counts.observations + '・軌道 ' + s.counts.orbits + '・主張 ' + s.counts.claims + '</td></tr>';
    }).join('') + (CK.sats.length ? '' : '<tr><td colspan="8" class="muted">沒有任何紀錄指定 NORAD</td></tr>') + '</tbody>';
    tb.querySelectorAll('.sum-row').forEach(function (tr) { tr.onclick = function () { detail(+tr.dataset.n); }; });
  }
  function detail(n) {
    var parts = [['observations', obsChk], ['orbits', orbChk], ['claims', clmChk]].map(function (x) {
      var rs = D[x[0]].filter(function (r) { var c = chk(x[0], r.id); return (c && c.norad === n) || r.norad === n; });
      if (!rs.length) return '';
      return '<h3>' + M.KINDS[x[0]].label + '（' + rs.length + '）</h3><table><tbody>' + rs.map(function (r) {
        var desc = x[0] === 'observations' ? esc(r.time) + '・' + esc(r.station) + '・' + esc(r.observer || '') : x[0] === 'orbits' ? '<span class="mono">' + esc(r.line1) + '</span>' : esc(r.name) + '・' + esc(M.SRC[r.source_type] || '');
        return '<tr><td style="width:70px">' + esc(r.id) + '</td><td>' + desc + '</td><td>' + reviewCell(x[0], r) + '</td><td>' + x[1](chk(x[0], r.id)) + '</td></tr>';
      }).join('') + '</tbody></table>';
    }).join('');
    $('sum-detail').innerHTML = '<h2>NORAD ' + n + ' 明細 <button style="float:right" onclick="document.getElementById(\'sum-detail\').innerHTML=\'\'">關閉</button></h2>' + parts;
    $('sum-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ── 匯入匯出 ──
  function importCsv() {
    var f = $('io-file').files[0], txt = $('io-text').value.trim(), kind = $('io-kind').value || null;
    (f ? f.text() : Promise.resolve(txt)).then(function (t) {
      if (!t) throw new Error('請選擇檔案或貼上 CSV');
      var p = M.fromCsv(t, kind);
      if (p.error) throw new Error(p.error);
      return B.add(p.kind, p.records).then(function (r) {
        msg('io-msg', M.KINDS[p.kind].label + '：匯入 ' + r.added + ' 筆' + (r.errors.length ? '；失敗 ' + r.errors.length + ' 筆' : ''), !r.errors.length);
        $('io-err').innerHTML = r.errors.slice(0, 50).map(function (e) { return '<div>第 ' + e.row + ' 列：' + esc(e.msg) + '</div>'; }).join('');
        return reload();
      });
    }).catch(function (e) { msg('io-msg', e.message); });
  }
  function exportCsv(kind) { download('obs_' + kind + '_' + stamp() + '.csv', M.toCsv(kind, D[kind])); }
  function templateCsv(kind) { download('obs_' + kind + '_範本.csv', M.template(kind)); }
  function exportJson() { download('obs_backup_' + stamp() + '.json', B.exportJson(), 'application/json'); }
  function importJson() {
    var f = $('io-json').files[0];
    if (!f) { msg('bk-msg', '請先選擇備份檔'); return; }
    f.text().then(function (t) { if (!confirm('以備份取代目前的觀測資料？')) return; B.importJson(t); return reload().then(function () { msg('bk-msg', '已還原', true); }); }).catch(function (e) { msg('bk-msg', e.message); });
  }
  function clearAll() { if (confirm('清除這個瀏覽器中所有觀測資料？（建議先下載備份）')) { B.clear(); reload(); } }

  function reload() { return B.load().then(function (d) { D = d; renderAll(); }); }
  ['observations', 'orbits', 'claims', 'pois'].forEach(function (k) { var el = $('f-' + k); if (el) el.addEventListener('input', function () { renderKind(k); }); });
  window.OBS = { add: function (k) { openForm(k, null); }, edit: openForm, save: save, cancel: cancel, del: del, review: review, runCheck: runCheck,
    importCsv: importCsv, exportCsv: exportCsv, templateCsv: templateCsv, exportJson: exportJson, importJson: importJson, clearAll: clearAll };
  B.caps().then(function (c) {
    CAPS = c;
    document.body.classList.toggle('ro', !c.canEdit);
    if (!B.exportJson) document.querySelectorAll('.local-only').forEach(function (x) { x.style.display = 'none'; });
    $('where').textContent = '資料存放：' + B.where + (c.user ? '・' + c.user : '') + (c.canEdit ? '' : '・唯讀') + (c.canReview ? '・可複核' : '');
    return reload();
  }).then(function () { if (D.observations.length || D.orbits.length || D.claims.length) runCheck(); })
    .catch(function (e) { $('where').textContent = e.message; });
})();
