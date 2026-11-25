/* 衛星管理頁：更名、群組分類、帳號管理、操作紀錄（src/satadmin.rs、src/auth.rs） */
(function () {
  'use strict';
  var ME = null, GROUPS = [], SEL = null, LAST_ROWS = [];
  var SENSOR_LABEL = { '': '（沿用上層）', optical: '光學', radar: '雷達', sigint: '電子偵察', other: '其他' };
  var ROLE_LABEL = { viewer: '檢視者（查詢）', editor: '編輯者（查詢・輸入・新增・修改）', admin: '管理者（含帳號與系統）' };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmtT(s) { return s ? String(s).replace('T', ' ').replace(/(:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$/, '$1').replace('Z', '') : '—'; }
  function msg(el, text, ok) { el = typeof el === 'string' ? $(el) : el; if (!el) return; el.textContent = text || ''; el.className = 'msg ' + (ok ? 'ok' : 'bad'); }
  function canEdit() { return ME && ME.perms && ME.perms.indexOf('modify') >= 0; }
  function isAdmin() { return ME && ME.perms && ME.perms.indexOf('admin') >= 0; }
  var ST_LABEL = { decayed: '已再入', stale: 'TLE 停更', no_satcat: 'SATCAT 查無', ok: '正常' };
  function stBadge(r, showOk) {
    if (!r.status || (r.status === 'ok' && !showOk)) return '';
    var tip = r.status === 'decayed' ? 'DECAY ' + (r.decay_date || '') : (r.tle_age_days != null ? 'TLE ' + r.tle_age_days + ' 天前' : '');
    return ' <span class="st st-' + r.status + '" title="' + esc(tip) + '">' + ST_LABEL[r.status] + (r.status === 'decayed' && r.decay_date ? ' ' + esc(r.decay_date) : '') + '</span>';
  }

  function api(method, url, body, raw) {
    var o = { method: method, headers: {} };
    if (body !== undefined) {
      if (raw) { o.body = body; o.headers['Content-Type'] = 'text/csv; charset=utf-8'; }
      else { o.body = JSON.stringify(body); o.headers['Content-Type'] = 'application/json'; }
    }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); throw new Error('請先登入'); }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      });
    });
  }

  // ── 身分 ──
  function loadMe() {
    return api('GET', '/api/auth/me').then(function (m) {
      ME = m;
      document.body.classList.toggle('ro', !canEdit());
      var who = $('who');
      if (m.auth_enabled) {
        who.innerHTML = '登入身分：<b>' + esc(m.user) + '</b>（' + esc(m.role_label) + '）';
        $('btn-logout').style.display = ''; $('btn-pw').style.display = '';
      } else {
        who.innerHTML = '<span style="color:#d29922">尚未啟用帳號</span>（' + esc(m.role_label) + (m.can_setup ? '・本機' : '・區網唯讀') + '）';
      }
    });
  }

  // ── 分頁 ──
  document.querySelectorAll('#tabs button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('#tabs button').forEach(function (x) { x.classList.toggle('on', x === b); });
      document.querySelectorAll('.tab').forEach(function (x) { x.classList.toggle('on', x.id === 't-' + b.dataset.t); });
      if (b.dataset.t === 'groups') loadGroups();
      if (b.dataset.t === 'users') loadUsers();
      if (b.dataset.t === 'audit') loadAudit();
      if (b.dataset.t === 'decay') decayTab();
      if (b.dataset.t === 'ephem') loadEphem();
    });
  });

  // ── 衛星更名 ──
  function renderRows(rows) {
    LAST_ROWS = rows;
    var tb = document.querySelector('#res tbody');
    if (!rows.length) { tb.innerHTML = '<tr><td colspan="8" class="muted">沒有符合的衛星</td></tr>'; return; }
    tb.innerHTML = rows.map(function (r) {
      var nm = r.custom ? '<span class="cust" title="自訂名稱（' + esc(r.renamed_by || '') + ' ' + esc(fmtT(r.renamed_at)) + '）">✎ ' + esc(r.name) + '</span>' +
        (r.name_status && r.name_status !== 'manual' ? ' <span class="muted">[' + esc(r.name_status) + (r.name_confidence ? '/' + esc(r.name_confidence) : '') + ']</span>' : '') : esc(r.name);
      nm += stBadge(r);
      if (r.note) nm += '<div class="muted">' + esc(r.note) + '</div>';
      var grp = (r.groups || []).map(function (g) { return '<span class="tag">' + esc(g) + '</span>'; }).join('');
      var ops = '<button onclick="SA.rename(' + r.norad_id + ')">更名</button> ' +
        (r.custom ? '<button class="dan" onclick="SA.unrename(' + r.norad_id + ')">還原</button> ' : '') +
        '<button onclick="SA.addToGroup(' + r.norad_id + ')">加入群組</button> <button onclick="SA.loadSuggest([' + r.norad_id + '])">建議名稱</button>';
      return '<tr id="r-' + r.norad_id + '"><td class="num">' + r.norad_id + '</td><td>' + nm + '</td><td>' + esc(r.orig_name || '—') +
        (r.in_catalog ? '' : ' <span class="muted">（不在目前目錄）</span>') + '</td><td>' + esc(r.intl_code || '—') + '</td><td class="num">' +
        esc(fmtT(r.tle_epoch)) + '</td><td>' + esc(r.country || '—') + '／' + esc(r.purpose || '—') + '</td><td>' + grp + '</td><td class="edit-only" style="white-space:nowrap">' + ops + '</td></tr>';
    }).join('');
  }

  function lookup(text) {
    var q = text != null ? text : $('q').value.trim();
    if (text != null) $('q').value = q;
    if (!q) return;
    var isIds = /^[\d\s,，、]+$/.test(q);
    msg('q-msg', '查詢中…', true);
    api('GET', '/api/satadmin/lookup?' + (isIds ? 'norad=' : 'q=') + encodeURIComponent(q)).then(function (j) {
      renderRows(j.results);
      msg('q-msg', '共 ' + j.count + ' 筆' + (j.truncated ? '（僅列前 200 筆，請縮小關鍵字）' : ''), true);
    }).catch(function (e) { msg('q-msg', e.message); });
  }
  function relookup() {
    if (!LAST_ROWS.length) return;
    var ids = LAST_ROWS.map(function (r) { return r.norad_id; }).join(',');
    api('GET', '/api/satadmin/lookup?norad=' + ids).then(function (j) { renderRows(j.results); });
  }

  function rename(nid) {
    var r = LAST_ROWS.find(function (x) { return x.norad_id === nid; }) || {};
    var tr = $('r-' + nid);
    var td = tr.children[1];
    td.innerHTML = '<input id="rn-' + nid + '" style="width:100%" maxlength="64"/><input id="rnn-' + nid + '" style="width:100%;margin-top:4px" placeholder="備註（可空白）"/>' +
      '<div style="margin-top:4px"><button class="pri" id="rns-' + nid + '">儲存</button> <button id="rnc-' + nid + '">取消</button> <span class="msg" id="rnm-' + nid + '"></span></div>';
    $('rn-' + nid).value = r.name || '';
    $('rnn-' + nid).value = r.note || '';
    $('rn-' + nid).focus(); $('rn-' + nid).select();
    $('rnc-' + nid).onclick = function () { renderRows(LAST_ROWS); };
    var save = function () {
      var name = $('rn-' + nid).value.trim();
      if (!name) { msg('rnm-' + nid, '名稱不可空白'); return; }
      api('PUT', '/api/satadmin/names/' + nid, { name: name, note: $('rnn-' + nid).value.trim() })
        .then(function () { msg('q-msg', 'NORAD ' + nid + ' 已更名為「' + name + '」；地球儀約數秒後套用（重新整理頁面）', true); relookup(); })
        .catch(function (e) { msg('rnm-' + nid, e.message); });
    };
    $('rns-' + nid).onclick = save;
    $('rn-' + nid).onkeydown = function (e) { if (e.key === 'Enter') save(); if (e.key === 'Escape') renderRows(LAST_ROWS); };
  }
  function unrename(nid) {
    if (!confirm('還原 NORAD ' + nid + ' 為 Space-Track 原名？')) return;
    api('DELETE', '/api/satadmin/names/' + nid).then(function () { msg('q-msg', '已還原 NORAD ' + nid, true); relookup(); })
      .catch(function (e) { msg('q-msg', e.message); });
  }

  function loadDup() {
    var box = $('dup'); box.style.display = ''; box.innerHTML = '<span class="muted">載入中…</span>';
    api('GET', '/api/satadmin/duplicates?limit=300' + ($('dup-nodeb').checked ? '&no_debris=1' : '')).then(function (j) {
      box.innerHTML = '<h2>重複名稱（共 ' + j.total_names + ' 種名稱重複；點名稱列出全部 NORAD）<button style="float:right" onclick="document.getElementById(\'dup\').style.display=\'none\'">關閉</button></h2>' +
        '<div style="max-height:220px;overflow:auto">' + j.results.map(function (d) {
          return '<span class="dup tag" data-ids="' + d.norad_ids.slice(0, 500).join(',') + '">' + esc(d.name) + ' ×' + d.count + '</span>';
        }).join(' ') + '</div>';
      box.querySelectorAll('.dup').forEach(function (el) { el.onclick = function () { lookup(el.dataset.ids); }; });
    }).catch(function (e) { box.textContent = e.message; });
  }
  function loadNamed() {
    api('GET', '/api/satadmin/names').then(function (j) { renderRows(j.results); msg('q-msg', '已自訂名稱 ' + j.count + ' 筆', true); })
      .catch(function (e) { msg('q-msg', e.message); });
  }

  function importCsv() {
    var f = $('csvfile').files[0];
    if (!f) { msg('csv-msg', '請先選擇 CSV 檔'); return; }
    msg('csv-msg', '匯入中…', true);
    f.text().then(function (t) { return api('POST', '/api/satadmin/import', t, true); }).then(function (j) {
      msg('csv-msg', '完成：更名 ' + j.renamed + ' 筆、加入群組 ' + j.grouped + ' 筆、新建群組 ' + j.created_groups + ' 個' +
        (j.errors.length ? '；錯誤 ' + j.errors.length + ' 筆：' + j.errors.slice(0, 3).join('；') : ''), !j.errors.length);
      GROUPS = [];
    }).catch(function (e) { msg('csv-msg', e.message); });
  }

  // ── 建議名稱 ──
  var SG = [], SG_STATUS = { official: 'official', inferred: 'inferred', group_inferred: 'group_inferred', conflict: 'conflict', unresolved: 'unresolved' };
  var CONF_LABEL = { high: '高', medium: '中', low: '低' };
  var IND_LABEL = { confirmed: '已確認', inferred: '推論', disputed: '有爭議', unconfirmed: '未確認' };
  function sgChanged(r) {
    var c = r.custom;
    if (!c) return '';
    if (r.name_status === 'official' && c.status !== 'official') return '可升級：Space-Track 已正式命名';
    if (c.suggest_raw && r.raw_name && c.suggest_raw !== r.raw_name) return '來源名稱已變動：' + c.suggest_raw + ' → ' + r.raw_name;
    return '';
  }
  function renderSuggest() {
    var f = $('sg-filter').value;
    var rows = SG.filter(function (r) { return !f || (f === 'upgrade' ? sgChanged(r) : r.name_status === f); });
    var stc = { official: 'st-ok', inferred: 'st-stale', group_inferred: 'st-stale', conflict: 'st-decayed', unresolved: 'st-no_satcat' };
    document.querySelector('#sg tbody').innerHTML = rows.map(function (r) {
      var c = r.custom, ch = sgChanged(r), L = r.layers || {};
      var mates = (r.mates || []).map(function (m) { return m.intl + ' ' + (m.name || '') + (m.gcat_name ? '（GCAT：' + m.gcat_name + '）' : '') + (m.self ? ' ←' : ''); }).join('\n');
      var warn = (r.warnings || []).concat(ch ? [ch] : []);
      return '<tr data-n="' + r.norad_id + '"><td>' + (r.suggest && canEdit() ? '<input type="checkbox" class="sg-chk" value="' + r.norad_id + '"/>' : '') + '</td><td class="num">' + r.norad_id +
        '<div class="muted">' + esc(r.intl_code || '') + '</div></td><td>' + esc(r.current_name) + (c ? '<div class="cust">✎ ' + esc(c.name) + '</div>' : '') + '</td><td>' +
        (r.suggest ? '<input class="sg-name" style="width:240px" maxlength="64" value="' + esc(r.suggest) + '"/>' + (r.raw_name && r.raw_name !== r.suggest ? '<div class="muted">原始：' + esc(r.raw_name) + '</div>' : '') : '<span class="muted">（無可靠來源，維持原名）</span>') +
        '</td><td><span class="st ' + (stc[r.name_status] || '') + '">' + esc(r.name_status) + '</span>' + (r.confidence ? ' <span class="muted">可信度' + CONF_LABEL[r.confidence] + '</span>' : '') +
        '</td><td title="' + esc(mates) + '">' + esc((L.launch_group || {}).value || '—') + '<div class="muted">同次發射 ' + (r.mates || []).length + ' 個物體（游標停留看清單）</div></td><td>' +
        esc((L.candidate_mission || {}).value || '—') + '</td><td>' + esc(IND_LABEL[(L.individual || {}).status] || '—') + '</td><td style="white-space:normal;max-width:280px;color:#e3b341">' +
        esc(warn.join('；')) + '</td></tr>';
    }).join('') || '<tr><td colspan="9" class="muted">沒有符合的項目</td></tr>';
    var all = $('sg-all'); if (all) all.onchange = function () { document.querySelectorAll('.sg-chk').forEach(function (x) { x.checked = all.checked; }); };
  }
  function loadSuggest(ids) {
    msg('sg-msg', '分析中…', true);
    var url = ids ? '/api/satadmin/suggest?norad=' + ids.join(',') : '/api/satadmin/suggest?scope=objects&limit=2000';
    api('GET', url).then(function (j) {
      SG = j.results;
      if (!j.gcat) msg('sg-msg', '資料庫內尚無 GCAT 資料（每日管線更新後才有逐顆與發射任務名稱）', false);
      else {
        var c = j.counts;
        msg('sg-msg', '共 ' + j.count + ' 顆：official ' + c.official + '、inferred ' + c.inferred + '、group_inferred ' + c.group_inferred + '、conflict ' + c.conflict + '、unresolved ' + c.unresolved + '（GCAT ' + (j.gcat.sat_updated || '') + '）', true);
      }
      renderSuggest();
      if (ids) $('sg').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }).catch(function (e) { msg('sg-msg', e.message); });
  }
  function sgCheck(mode) {
    document.querySelectorAll('.sg-chk').forEach(function (x) {
      var r = SG.find(function (y) { return y.norad_id === +x.value; });
      x.checked = mode === 'safe' && r && (r.name_status === 'official' || r.name_status === 'inferred') && !(r.warnings || []).length;
    });
  }
  function applySuggest() {
    var ev = ($('sg-evidence').value.match(/https?:\/\/\S+/g) || []), review = $('sg-review').value, items = [];
    document.querySelectorAll('.sg-chk:checked').forEach(function (x) {
      var r = SG.find(function (y) { return y.norad_id === +x.value; }); if (!r) return;
      var name = x.closest('tr').querySelector('.sg-name').value.trim();
      var evid = (r.sources || []).map(function (s) { return s.url; }).concat(ev).filter(function (u, i, a) { return u && a.indexOf(u) === i; });
      items.push({ norad: r.norad_id, name: name, note: r.note + (name !== r.suggest ? '；人工修改建議名稱' : '') + (ev.length ? '；證據：' + ev.join(' ') : ''),
        status: name !== r.suggest ? 'manual' : r.name_status, confidence: r.confidence || '', evidence: evid, review: review, suggest_raw: r.raw_name || '' });
    });
    if (!items.length) { msg('sg-msg', '請先勾選要套用的建議'); return; }
    api('POST', '/api/satadmin/names_batch', items).then(function (j) {
      // 只更新已套用的列（不重載整份清單，避免蓋掉訊息）
      items.forEach(function (it) {
        var r = SG.find(function (y) { return y.norad_id === it.norad; });
        if (r) r.custom = { name: it.name, status: it.status, confidence: it.confidence, suggest_raw: it.suggest_raw };
      });
      renderSuggest();
      msg('sg-msg', '已套用 ' + j.applied + ' 筆；地球儀約數秒後套用新名稱' + (j.errors.length ? '；失敗：' + j.errors.slice(0, 3).join('；') : ''), !j.errors.length);
    }).catch(function (e) { msg('sg-msg', e.message); });
  }

  // ── 群組 ──
  function loadGroups(keepSel) {
    return api('GET', '/api/satadmin/groups').then(function (j) {
      GROUPS = j.groups;
      if (SEL && !GROUPS.some(function (g) { return g.id === SEL; })) SEL = null;
      renderTree();
      renderDetail();
    }).catch(function (e) { $('gtree').textContent = e.message; });
  }
  function kids(pid) { return GROUPS.filter(function (g) { return (g.parent || null) === pid; }).sort(function (a, b) { return a.name.localeCompare(b.name, 'zh-Hant'); }); }
  function renderTree() {
    var out = [];
    (function walk(pid, depth) {
      kids(pid).forEach(function (g) {
        out.push('<div class="g' + (g.id === SEL ? ' on' : '') + '" data-id="' + g.id + '" style="padding-left:' + (8 + depth * 18) + 'px">' +
          '<span class="dot" style="background:' + esc(g.color || 'transparent') + '"></span>' + esc(g.name) +
          (g.eff_sensor ? ' <span class="muted">' + esc(SENSOR_LABEL[g.eff_sensor] || g.eff_sensor) + '</span>' : '') +
          '<span class="cnt">' + g.count_total + '</span></div>');
        walk(g.id, depth + 1);
      });
    })(null, 0);
    $('gtree').innerHTML = out.join('') || '<div class="muted">尚無群組。' + (canEdit() ? '在上方輸入名稱新增，例如「PRC偵察衛星」。' : '') + '</div>';
    $('gtree').querySelectorAll('.g').forEach(function (el) { el.onclick = function () { SEL = el.dataset.id; renderTree(); renderDetail(); }; });
  }
  function newGroup(sub) {
    var name = $('g-new').value.trim();
    if (!name) { msg('g-new-msg', '請輸入群組名稱'); return; }
    if (sub && !SEL) { msg('g-new-msg', '請先在下方選取上層群組'); return; }
    api('POST', '/api/satadmin/groups', { name: name, parent: sub ? SEL : null }).then(function (j) {
      $('g-new').value = ''; msg('g-new-msg', '已新增', true); SEL = j.id; loadGroups();
    }).catch(function (e) { msg('g-new-msg', e.message); });
  }
  function parentOptions(g) {
    var bad = {}; (function mark(id) { bad[id] = 1; kids(id).forEach(function (k) { mark(k.id); }); })(g.id);
    return '<option value="">（最上層）</option>' + GROUPS.filter(function (x) { return !bad[x.id]; })
      .sort(function (a, b) { return a.path.localeCompare(b.path, 'zh-Hant'); })
      .map(function (x) { return '<option value="' + x.id + '"' + (x.id === g.parent ? ' selected' : '') + '>' + esc(x.path) + '</option>'; }).join('');
  }
  function renderDetail() {
    var box = $('gdetail');
    var g = GROUPS.find(function (x) { return x.id === SEL; });
    if (!g) { box.innerHTML = '<div class="muted">選取左側群組以檢視與編輯。</div>'; return; }
    var dis = canEdit() ? '' : ' disabled';
    var sensorOpts = Object.keys(SENSOR_LABEL).map(function (k) { return '<option value="' + k + '"' + (k === (g.sensor || '') ? ' selected' : '') + '>' + SENSOR_LABEL[k] + '</option>'; }).join('');
    var mem = (g.members || []).map(function (r) {
      return '<tr><td class="edit-only"><input type="checkbox" class="mchk" value="' + r.norad_id + '"/></td><td class="num">' + r.norad_id + '</td><td>' +
        (r.custom ? '<span class="cust">✎ ' + esc(r.name) + '</span>' : esc(r.name || '—')) + '</td><td>' + esc(r.orig_name || '—') + '</td><td>' + esc(r.intl_code || '—') +
        '</td><td class="num">' + esc(fmtT(r.tle_epoch)) + '</td><td>' + esc(r.country || '—') + '</td><td>' + stBadge(r) + (r.in_catalog ? '' : ' <span class="muted">不在目前目錄</span>') + '</td></tr>';
    }).join('');
    box.innerHTML =
      '<h2>' + esc(g.path) + ' <span class="muted">（本層 ' + g.count + ' 顆，含子群組 ' + g.count_total + ' 顆）</span></h2>' +
      '<div class="grid2">' +
      '<label>名稱</label><input id="gd-name" maxlength="64"' + dis + '/>' +
      '<label>上層群組</label><select id="gd-parent"' + dis + '>' + parentOptions(g) + '</select>' +
      '<label>顏色</label><div><input type="color" id="gd-color" value="' + esc(g.color || '#F44336') + '"' + dis + '/> <label class="muted"><input type="checkbox" id="gd-nocolor"' + (g.color ? '' : ' checked') + dis + '/> 不指定</label></div>' +
      '<label>感測器類型</label><div><select id="gd-sensor"' + dis + '>' + sensorOpts + '</select> <span class="muted">目前生效：' + esc(SENSOR_LABEL[g.eff_sensor] || '未設定') + '</span></div>' +
      '<label>偵照角度（°）</label><div><input id="gd-look" type="number" min="1" max="70" step="0.5" style="width:90px" placeholder="沿用上層"' + dis + '/> <span class="muted">離天底角，供過頂預報判定可偵照範圍；目前生效：' + (g.eff_look_deg != null ? g.eff_look_deg + '°' : '未設定') + '</span></div>' +
      '<label>備註</label><input id="gd-note"' + dis + '/>' +
      '</div>' +
      '<div class="row edit-only" style="margin-top:10px"><button class="pri" onclick="SA.saveGroup()">儲存群組設定</button>' +
      '<button class="dan" onclick="SA.delGroup()">刪除群組</button><label class="muted"><input type="checkbox" id="gd-cascade"/> 連同子群組刪除</label><span id="gd-msg" class="msg"></span></div>' +
      '<div class="muted" style="margin:4px 0 12px">最後修改：' + esc(g.by || '—') + ' ' + esc(fmtT(g.at)) + '</div>' +
      '<h2>成員</h2>' +
      '<div class="edit-only"><textarea id="gd-add" placeholder="輸入要加入的 NORAD ID，可多個（逗號、空白或換行分隔）"></textarea>' +
      '<div class="row" style="margin-top:6px"><button class="pri" onclick="SA.addMembers()">加入</button><button class="dan" onclick="SA.removeChecked()">移除勾選的衛星</button><span id="gm-msg" class="msg"></span></div></div>' +
      '<div class="tw"><table><thead><tr><th class="edit-only"><input type="checkbox" id="mchk-all"/></th><th>NORAD</th><th>名稱</th><th>Space-Track 原名</th><th>國際編號</th><th>TLE 曆元（UTC）</th><th>國別</th><th>狀態</th></tr></thead><tbody>' +
      (mem || '<tr><td colspan="8" class="muted">本層尚無衛星' + (g.count_total ? '（成員在子群組）' : '') + '</td></tr>') + '</tbody></table></div>';
    $('gd-name').value = g.name; $('gd-note').value = g.note || '';
    $('gd-look').value = g.look_deg != null ? g.look_deg : '';
    var all = $('mchk-all'); if (all) all.onchange = function () { box.querySelectorAll('.mchk').forEach(function (c) { c.checked = all.checked; }); };
  }
  function saveGroup() {
    var look = $('gd-look').value.trim();
    var body = { name: $('gd-name').value.trim(), parent: $('gd-parent').value || null, color: $('gd-nocolor').checked ? '' : $('gd-color').value,
      sensor: $('gd-sensor').value, look_deg: look === '' ? null : parseFloat(look), note: $('gd-note').value };
    api('PUT', '/api/satadmin/groups/' + SEL, body).then(function () { msg('gd-msg', '已儲存', true); loadGroups(); })
      .catch(function (e) { msg('gd-msg', e.message); });
  }
  function delGroup() {
    var g = GROUPS.find(function (x) { return x.id === SEL; });
    var cas = $('gd-cascade').checked;
    if (!confirm('刪除群組「' + g.path + '」' + (cas ? '及其所有子群組' : '') + '？（衛星本身與更名不受影響）')) return;
    api('DELETE', '/api/satadmin/groups/' + SEL + (cas ? '?cascade=1' : '')).then(function () { SEL = g.parent || null; loadGroups(); })
      .catch(function (e) { msg('gd-msg', e.message); });
  }
  function parseIds(s) { return (s.match(/\d+/g) || []).map(Number).filter(function (n) { return n > 0; }); }
  function addMembers(ids, gid) {
    ids = ids || parseIds($('gd-add').value);
    gid = gid || SEL;
    if (!ids.length) { msg('gm-msg', '請輸入 NORAD ID'); return Promise.resolve(); }
    return api('POST', '/api/satadmin/groups/' + gid + '/members', { add: ids }).then(function (j) {
      msg('gm-msg', '加入 ' + j.added + ' 顆' + (j.not_in_catalog.length ? '（其中 ' + j.not_in_catalog.length + ' 顆不在目前目錄：' + j.not_in_catalog.slice(0, 10).join(',') + '）' : ''), true);
      if ($('gd-add')) $('gd-add').value = '';
      return loadGroups();
    }).catch(function (e) { msg('gm-msg', e.message); });
  }
  function removeChecked() {
    var ids = Array.prototype.map.call(document.querySelectorAll('.mchk:checked'), function (c) { return +c.value; });
    if (!ids.length) { msg('gm-msg', '請先勾選要移除的衛星'); return; }
    if (!confirm('從群組移除 ' + ids.length + ' 顆衛星？')) return;
    api('POST', '/api/satadmin/groups/' + SEL + '/members', { remove: ids }).then(function (j) { msg('gm-msg', '已移除 ' + j.removed + ' 顆', true); loadGroups(); })
      .catch(function (e) { msg('gm-msg', e.message); });
  }
  function addToGroup(nid) {
    var p = GROUPS.length ? Promise.resolve() : api('GET', '/api/satadmin/groups?members=0').then(function (j) { GROUPS = j.groups; });
    p.then(function () {
      if (!GROUPS.length) { alert('尚無群組，請先到「群組分類」新增。'); return; }
      var list = GROUPS.slice().sort(function (a, b) { return a.path.localeCompare(b.path, 'zh-Hant'); });
      var td = $('r-' + nid).lastElementChild;
      td.innerHTML = '<select id="ag-' + nid + '">' + list.map(function (g) { return '<option value="' + g.id + '">' + esc(g.path) + '</option>'; }).join('') +
        '</select> <button class="pri" id="agb-' + nid + '">加入</button> <button id="agc-' + nid + '">取消</button>';
      $('agc-' + nid).onclick = function () { renderRows(LAST_ROWS); };
      $('agb-' + nid).onclick = function () {
        api('POST', '/api/satadmin/groups/' + $('ag-' + nid).value + '/members', { add: [nid] })
          .then(function () { GROUPS = []; relookup(); }).catch(function (e) { alert(e.message); });
      };
    });
  }

  // ── 衛星失能（DECAY）──
  function decayTab() {
    var p = GROUPS.length ? Promise.resolve() : api('GET', '/api/satadmin/groups?members=0').then(function (j) { GROUPS = j.groups; });
    p.then(function () {
      var sel = $('dc-group'), cur = sel.value;
      sel.innerHTML = '<option value="">全部群組</option>' + GROUPS.slice().sort(function (a, b) { return a.path.localeCompare(b.path, 'zh-Hant'); })
        .map(function (g) { return '<option value="' + g.id + '">' + esc(g.path) + '（' + g.count_total + '）</option>'; }).join('');
      sel.value = cur || (SEL || '');
      loadDecay();
    });
  }
  function decayQuery() {
    return 'group=' + encodeURIComponent($('dc-group').value) + '&stale_days=' + encodeURIComponent($('dc-stale').value || 30) + ($('dc-all').checked ? '&all=1' : '');
  }
  function loadDecay() {
    $('dc-csv').href = '/api/satadmin/decay?format=csv&' + decayQuery();
    msg('dc-msg', '載入中…', true);
    api('GET', '/api/satadmin/decay?' + decayQuery()).then(function (j) {
      var c = j.counts;
      $('dc-sum').innerHTML = '已再入 <b style="color:#ff8f87">' + c.decayed + '</b> 顆・TLE 停更 <b style="color:#e3b341">' + c.stale + '</b> 顆・SATCAT 查無 ' + c.no_satcat + ' 顆' +
        ($('dc-all').checked ? '・正常 ' + c.ok + ' 顆' : '') + '　|　SATCAT：' + (j.satcat ? esc(j.satcat.source) + ' ' + esc(fmtT(j.satcat.fetched_at)) + '（' + j.satcat.count.toLocaleString() + ' 筆）' :
        '<span style="color:#d29922">尚未下載，DECAY 狀態無法判定；請到「星歷資料」更新 SATCAT</span>');
      document.querySelector('#dc tbody').innerHTML = j.rows.map(function (r) {
        return '<tr><td class="num">' + r.norad_id + '</td><td>' + esc(r.name) + (r.orig_name && r.orig_name !== r.name ? '<div class="muted">' + esc(r.orig_name) + '</div>' : '') + '</td><td>' + stBadge(r, true) +
          '</td><td class="num">' + esc(r.decay_date || '—') + '</td><td class="num">' + esc(r.launch_date || '—') + '</td><td class="num">' + (r.days_in_orbit != null ? r.days_in_orbit.toLocaleString() : '—') +
          '</td><td class="num">' + esc(fmtT(r.tle_epoch)) + '</td><td class="num">' + (r.tle_age_days != null ? r.tle_age_days : '—') + '</td><td>' + esc(r.object_type || '—') + '／' + esc(r.owner || '—') +
          '</td><td>' + (r.groups || []).map(function (g) { return '<span class="tag">' + esc(g) + '</span>'; }).join('') + '</td></tr>';
      }).join('') || '<tr><td colspan="10" class="muted">' + (GROUPS.length ? '群組內沒有已再入或停更的衛星' : '尚無群組') + '</td></tr>';
      msg('dc-msg', '', true);
    }).catch(function (e) { msg('dc-msg', e.message); });
  }
  function loadRecent() {
    msg('dr-msg', '載入中…', true);
    api('GET', '/api/satadmin/decay?scope=recent&days=' + encodeURIComponent($('dc-days').value || 30)).then(function (j) {
      if (!j.satcat_loaded) { msg('dr-msg', '尚未下載 SATCAT，請到「星歷資料」更新'); return; }
      document.querySelector('#dr tbody').innerHTML = j.rows.map(function (r) {
        return '<tr><td class="num">' + r.norad_id + '</td><td>' + esc(r.name) + '</td><td>' + esc(r.intl_code || '—') + '</td><td class="num">' + esc(r.decay_date) + '</td><td class="num">' + esc(r.launch_date || '—') +
          '</td><td class="num">' + (r.days_in_orbit != null ? r.days_in_orbit.toLocaleString() : '—') + '</td><td>' + esc(r.object_type || '—') + '／' + esc(r.owner || '—') + '</td></tr>';
      }).join('') || '<tr><td colspan="7" class="muted">期間內沒有再入物體</td></tr>';
      msg('dr-msg', '共 ' + j.rows.length + ' 筆', true);
    }).catch(function (e) { msg('dr-msg', e.message); });
  }

  // ── 星歷資料 ──
  var EP_TIMER = null;
  function ago(iso) {
    if (!iso) return '';
    var h = (Date.now() - new Date(iso)) / 3600000;
    return h < 1 ? Math.max(1, Math.round(h * 60)) + ' 分鐘前' : h < 48 ? h.toFixed(1) + ' 小時前' : (h / 24).toFixed(1) + ' 天前';
  }
  function loadEphem() {
    return api('GET', '/api/ephemeris/status').then(function (s) {
      var ix = s.index, gp = s.gp, sc = s.satcat;
      $('ep-status').innerHTML =
        '<div class="grid2" style="max-width:900px">' +
        '<label>最後更新</label><div><b style="color:#e6edf3">' + esc(fmtT(s.last_updated)) + ' UTC</b> <span class="muted">（' + ago(s.last_updated) + '）</span></div>' +
        '<label>資料庫</label><div>' + esc(s.db.name || '—') + '，下載於 ' + esc(fmtT(s.db.updated_at)) + '（' + ago(s.db.updated_at) + '）</div>' +
        '<label>最近重抓</label><div>' + (gp ? esc(gp.source) + ' ' + esc(fmtT(gp.fetched_at)) + '（' + ago(gp.fetched_at) + '）：' + gp.count.toLocaleString() + ' 筆，更新 ' + gp.newer.toLocaleString() + ' 顆、新增 ' + gp.added + ' 顆，操作者 ' + esc(gp.by || '—') : '尚未重抓') + '</div>' +
        '<label>目前目錄</label><div>' + ix.count.toLocaleString() + ' 顆；最新曆元 ' + esc(fmtT(ix.epoch_latest)) + '；曆元中位數 ' + ix.median_age_days + ' 天前；1 天內 ' + ix.within_1d.toLocaleString() + ' 顆、3 天內 ' + ix.within_3d.toLocaleString() + ' 顆、超過 30 天 ' + ix.older_30d.toLocaleString() + ' 顆</div>' +
        '<label>SATCAT</label><div>' + (sc ? esc(sc.source) + ' ' + esc(fmtT(sc.fetched_at)) + '：' + sc.count.toLocaleString() + ' 筆（已再入 ' + sc.decayed.toLocaleString() + '）' : '<span style="color:#d29922">尚未下載</span>') + '</div>' +
        '</div>';
      $('ep-cred').textContent = s.spacetrack.configured ? '已設定：' + s.spacetrack.identity + (s.spacetrack.from === 'env' ? '（環境變數）' : '（本機檔案）') : '尚未設定';
      $('ep-btn-st').disabled = !s.spacetrack.configured || !isAdmin();
      $('ep-btn-ct').disabled = !isAdmin();
      $('ep-cred-card').style.display = isAdmin() ? '' : 'none';
      var w = s.wait_s, hint = [];
      if (w['gp:celestrak']) hint.push('CelesTrak 尚需 ' + Math.ceil(w['gp:celestrak'] / 60) + ' 分鐘');
      if (w['gp:spacetrack']) hint.push('Space-Track 尚需 ' + Math.ceil(w['gp:spacetrack'] / 60) + ' 分鐘');
      var jb = s.job;
      if (jb && jb.started_at) {
        $('ep-job').textContent = (jb.running ? '⏳ 進行中（' + jb.source + '）\n' : (jb.ok ? '✅ ' : '❌ ') + '最近一次（' + jb.source + '，' + fmtT(jb.finished_at) + '）\n') + (jb.log || []).join('\n');
      }
      if (!jb.running && hint.length) msg('ep-msg', '頻率限制：' + hint.join('；'), true);
      clearTimeout(EP_TIMER);
      if (jb.running) EP_TIMER = setTimeout(loadEphem, 1500);
      return s;
    }).catch(function (e) { $('ep-status').textContent = e.message; });
  }
  function refresh(source, what) {
    if (!isAdmin()) { msg('ep-msg', '只有管理者可以重抓星歷'); return; }
    msg('ep-msg', '已送出…', true);
    api('POST', '/api/ephemeris/refresh', { source: source, what: what }).then(function () { msg('ep-msg', '', true); loadEphem(); })
      .catch(function (e) { msg('ep-msg', e.message); });
  }
  function saveCred() {
    api('POST', '/api/ephemeris/spacetrack', { identity: $('ep-id').value.trim(), password: $('ep-pw').value })
      .then(function () { $('ep-pw').value = ''; msg('ep-cmsg', '已儲存', true); loadEphem(); }).catch(function (e) { msg('ep-cmsg', e.message); });
  }
  function delCred() {
    if (!confirm('刪除本機儲存的 Space-Track 帳號？')) return;
    api('DELETE', '/api/ephemeris/spacetrack').then(function () { msg('ep-cmsg', '已刪除', true); loadEphem(); }).catch(function (e) { msg('ep-cmsg', e.message); });
  }

  // ── 帳號 ──
  function loadUsers() {
    var box = $('users');
    if (!ME.auth_enabled) {
      if (ME.can_setup) {
        box.innerHTML = '<div class="card"><h2>建立第一個管理者帳號</h2><div class="muted" style="margin-bottom:10px">建立後，所有頁面與 API 都需要登入；之後可新增「檢視者」「編輯者」「管理者」帳號。帳號存在本機 <code>user_private\\accounts.json</code>（密碼以 Argon2 雜湊）。</div>' +
          '<div class="grid2"><label>帳號</label><input id="su-u" autocomplete="username"/><label>顯示名稱</label><input id="su-d" placeholder="可空白"/>' +
          '<label>密碼</label><input id="su-p" type="password" autocomplete="new-password" placeholder="至少 8 字元"/><label>確認密碼</label><input id="su-p2" type="password" autocomplete="new-password"/></div>' +
          '<div class="row" style="margin-top:10px"><button class="pri" onclick="SA.setup()">建立並登入</button><span id="su-msg" class="msg"></span></div></div>';
      } else {
        box.innerHTML = '<div class="card muted">尚未啟用帳號。第一個管理者只能在執行程式的那台電腦上建立。</div>';
      }
      return;
    }
    if (!isAdmin()) { box.innerHTML = '<div class="card muted">帳號管理需要管理者權限。你可以在右上角變更自己的密碼。</div>'; return; }
    api('GET', '/api/auth/users').then(function (j) {
      var roleSel = function (u) { return '<select data-u="' + esc(u.username) + '" class="u-role">' + ['viewer', 'editor', 'admin'].map(function (r) { return '<option value="' + r + '"' + (r === u.role ? ' selected' : '') + '>' + ROLE_LABEL[r] + '</option>'; }).join('') + '</select>'; };
      box.innerHTML = '<div class="card"><h2>帳號清單</h2><div class="tw"><table><thead><tr><th>帳號</th><th>顯示名稱</th><th>角色／權限</th><th>狀態</th><th>建立</th><th>最後登入</th><th>操作</th></tr></thead><tbody>' +
        j.users.map(function (u) {
          var self = u.username === ME.user;
          return '<tr><td>' + esc(u.username) + (self ? ' <span class="muted">（你）</span>' : '') + '</td><td>' + esc(u.display || '') + '</td><td>' + roleSel(u) + '</td><td>' +
            (u.disabled ? '<span style="color:#f85149">停用</span>' : '<span style="color:#3fb950">啟用</span>') + '</td><td>' + esc(fmtT(u.created)) + '</td><td>' + esc(fmtT(u.last_login)) + '</td><td style="white-space:nowrap">' +
            '<button onclick="SA.toggleUser(\'' + esc(u.username) + '\',' + !u.disabled + ')">' + (u.disabled ? '啟用' : '停用') + '</button> ' +
            '<button onclick="SA.resetPw(\'' + esc(u.username) + '\')">重設密碼</button> ' +
            (self ? '' : '<button class="dan" onclick="SA.delUser(\'' + esc(u.username) + '\')">刪除</button>') + '</td></tr>';
        }).join('') + '</tbody></table></div><span id="u-msg" class="msg"></span></div>' +
        '<div class="card"><h2>新增帳號</h2><div class="grid2"><label>帳號</label><input id="nu-u"/><label>顯示名稱</label><input id="nu-d" placeholder="可空白"/>' +
        '<label>密碼</label><input id="nu-p" type="password" autocomplete="new-password" placeholder="至少 8 字元"/><label>角色</label><select id="nu-r"><option value="viewer">' + ROLE_LABEL.viewer + '</option><option value="editor">' + ROLE_LABEL.editor + '</option><option value="admin">' + ROLE_LABEL.admin + '</option></select></div>' +
        '<div class="row" style="margin-top:10px"><button class="pri" onclick="SA.addUser()">新增</button><span id="nu-msg" class="msg"></span></div>' +
        '<div class="muted" style="margin-top:8px">權限對照：檢視者＝查詢；編輯者＝查詢＋輸入（CSV 匯入）＋新增（群組）＋修改（更名、群組成員）；管理者＝再加帳號管理、重抓星歷、重載設定、程式更新。</div></div>';
      box.querySelectorAll('.u-role').forEach(function (s) {
        s.onchange = function () {
          api('PUT', '/api/auth/users/' + encodeURIComponent(s.dataset.u), { role: s.value }).then(function () { msg('u-msg', '已變更 ' + s.dataset.u + ' 的角色（該帳號需重新登入）', true); })
            .catch(function (e) { msg('u-msg', e.message); loadUsers(); });
        };
      });
    }).catch(function (e) { box.textContent = e.message; });
  }
  function setup() {
    var p = $('su-p').value;
    if (p !== $('su-p2').value) { msg('su-msg', '兩次密碼不一致'); return; }
    api('POST', '/api/auth/setup', { username: $('su-u').value.trim(), password: p, display: $('su-d').value })
      .then(function () { location.reload(); }).catch(function (e) { msg('su-msg', e.message); });
  }
  function addUser() {
    api('POST', '/api/auth/users', { username: $('nu-u').value.trim(), password: $('nu-p').value, role: $('nu-r').value, display: $('nu-d').value })
      .then(function () { loadUsers(); }).catch(function (e) { msg('nu-msg', e.message); });
  }
  function toggleUser(u, disable) {
    api('PUT', '/api/auth/users/' + encodeURIComponent(u), { disabled: disable }).then(loadUsers).catch(function (e) { msg('u-msg', e.message); });
  }
  function resetPw(u) {
    var p = prompt('為「' + u + '」設定新密碼（至少 8 字元）：');
    if (!p) return;
    api('PUT', '/api/auth/users/' + encodeURIComponent(u), { password: p }).then(function () { msg('u-msg', '已重設 ' + u + ' 的密碼', true); if (u === ME.user) location.reload(); })
      .catch(function (e) { msg('u-msg', e.message); });
  }
  function delUser(u) {
    if (!confirm('刪除帳號「' + u + '」？')) return;
    api('DELETE', '/api/auth/users/' + encodeURIComponent(u)).then(loadUsers).catch(function (e) { msg('u-msg', e.message); });
  }
  function showPw() {
    var o = prompt('目前密碼：'); if (!o) return;
    var n = prompt('新密碼（至少 8 字元）：'); if (!n) return;
    if (prompt('再輸入一次新密碼：') !== n) { alert('兩次密碼不一致'); return; }
    api('POST', '/api/auth/password', { old: o, new: n }).then(function () { alert('密碼已變更，請重新登入'); location.href = '/login?next=/satadmin'; })
      .catch(function (e) { alert(e.message); });
  }
  function logout() { api('POST', '/api/auth/logout').then(function () { location.href = '/login'; }); }

  // ── 紀錄 ──
  function loadAudit() {
    api('GET', '/api/satadmin/audit?limit=500').then(function (j) {
      document.querySelector('#audit tbody').innerHTML = j.results.map(function (a) {
        return '<tr><td class="num" style="white-space:nowrap">' + esc(fmtT(a.at)) + '</td><td>' + esc(a.by) + '</td><td>' + esc(a.action) + '</td><td>' + esc(a.detail) + '</td></tr>';
      }).join('') || '<tr><td colspan="4" class="muted">尚無紀錄</td></tr>';
    });
  }

  $('q').addEventListener('keydown', function (e) { if (e.key === 'Enter') lookup(); });
  $('sg-filter').addEventListener('change', renderSuggest);
  window.SA = { loadSuggest: loadSuggest, sgCheck: sgCheck, applySuggest: applySuggest, lookup: lookup, rename: rename, unrename: unrename, loadDup: loadDup, loadNamed: loadNamed, importCsv: importCsv, newGroup: newGroup,
    saveGroup: saveGroup, delGroup: delGroup, addMembers: function () { addMembers(); }, removeChecked: removeChecked, addToGroup: addToGroup,
    setup: setup, addUser: addUser, toggleUser: toggleUser, resetPw: resetPw, delUser: delUser, showPw: showPw, logout: logout, loadAudit: loadAudit,
    loadDecay: loadDecay, loadRecent: loadRecent, refresh: refresh, saveCred: saveCred, delCred: delCred };
  loadMe().then(function () {
    var t = new URLSearchParams(location.search).get('tab');
    if (t) { var b = document.querySelector('#tabs button[data-t="' + t + '"]'); if (b) b.click(); }
  });
})();
