/* 一箭多星軌道驗證頁：線上版（scenario04/web/static/js）與 Rust 單機版（web/ext）共用同一份檔案。
   資料：GET /api/launch?tag=YYYY-NNN（或 ?norad=）、GET /api/launch/recent?days= */
(function () {
  'use strict';
  var D = null;
  var GCOL = ['#58a6ff', '#f0883e', '#3fb950', '#d2a8ff', '#ff7b72', '#e3b341', '#56d4dd', '#db61a2', '#a5d6ff', '#7ee787'];
  var EVO = { maneuvering: ['升軌機動', 'ok'], lowering: ['降軌', 'warn'], decaying: ['自然衰減', 'na'], stable: ['穩定', 'na'], insufficient: ['資料不足', 'na'] };
  var SUP = { matched: ['吻合', 'ok'], possible: ['可能', 'warn'], none: ['不吻合', 'na'] };
  var TYPE = { PAYLOAD: '酬載', 'ROCKET BODY': '火箭體', DEBRIS: '碎片', UNKNOWN: '未知', TBA: '未知' };
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function msg(t, ok) { var el = $('msg'); el.textContent = t || ''; el.className = 'msg ' + (ok ? 'ok' : 'bad'); }
  function badge(code, map) { var m = map[code] || [code, 'na']; return '<span class="st st-' + m[1] + '">' + esc(m[0]) + '</span>'; }
  function api(url) {
    return fetch(url).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search); throw new Error('請先登入'); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function gcol(gid) { var i = parseInt(String(gid || 'G1').slice(1), 10) - 1; return GCOL[(i >= 0 ? i : 0) % GCOL.length]; }
  function f(v, d) { return v == null ? '—' : Number(v).toFixed(d); }

  function loadRecent() {
    api('/api/launch/recent?days=' + $('days').value).then(function (j) {
      $('recent').innerHTML = j.results.length ? j.results.map(function (r) {
        return '<span class="chip" data-tag="' + esc(r.tag) + '"><b>' + esc(r.tag) + '</b> ' + esc(r.launch_date || '') + ' ' + esc(r.mission || r.lv || '') + ' <span class="muted">×' + r.count + '</span></span>';
      }).join('') : '<span class="muted">期間內沒有多物體發射</span>';
      $('recent').querySelectorAll('.chip').forEach(function (c) { c.onclick = function () { $('q').value = c.dataset.tag; run(); }; });
      var s = j.supgp;
      $('supmeta').textContent = s ? 'SupGP：' + s.count.toLocaleString() + ' 筆（' + (s.files || '無') + '），取得於 ' + String(s.fetched_at || '').replace('T', ' ').replace('Z', '') + ' UTC' : 'SupGP：資料庫內尚無資料（每日管線更新後才有）';
    }).catch(function (e) { $('recent').textContent = e.message; });
  }

  function run() {
    var q = $('q').value.trim();
    if (!q) return;
    msg('分析中…', true);
    var p = /^\d{4}-\d{3}/.test(q) ? 'tag=' + encodeURIComponent(q) : 'norad=' + encodeURIComponent(q);
    history.replaceState(null, '', '?' + p);
    api('/api/launch?' + p).then(function (j) { D = j; render(); msg('', true); }).catch(function (e) { msg(e.message); });
  }

  function evoCell(e) {
    if (!e) return '—';
    var h = badge(e.status, EVO);
    if (e.raises.length) h += '<div class="muted">升軌 ' + e.raises.length + ' 次，累計 +' + e.raise_total_km + ' km</div>';
    if (e.lowers.length) h += '<div class="muted">降軌 ' + e.lowers.length + ' 次</div>';
    if (e.slope_km_day != null) h += '<div class="muted">近 14 天 ' + (e.slope_km_day > 0 ? '+' : '') + e.slope_km_day + ' km/日</div>';
    h += '<div class="muted">' + e.points + ' 筆 TLE</div>';
    return h;
  }
  function supCell(s, n) {
    if (!s) return '<span class="muted">—</span>';
    if (s.status === 'none') return '<span class="muted" title="SupGP 只收錄自願公布星曆的業者（Starlink、OneWeb、Planet、Kuiper 等）；最近的候選是同批或軌道相近的其他衛星，距離沒有身分意義">無對應 SupGP<br>（最近候選 ' + esc(s.name) + ' 相距 ' + s.dist_km + ' km，非同一顆）</span>';
    var h = badge(s.status, SUP) + ' ' + esc(s.name) + '<div class="muted">' + esc(s.file) + '・距離 ' + s.dist_km + ' km</div>';
    if (s.swap_suspected) h += '<div class="warn" title="同軌道面、相距很近的兩個物體，地面追蹤可能把編號對調（cross-tag）；SupGP 來自業者的星載 GPS，通常較可信，但仍需人工確認">⚠ 疑似目錄編號互換：本物體位置對應 SupGP ' + esc(s.norad) + '，而 SupGP ' + n + ' 的星曆在目錄 ' + esc(s.norad) + ' 的位置（相距 ' + s.swap_dist_km + ' km）</div>';
    else if (s.status !== 'none' && s.norad_consistent === false) h += '<div class="warn">SupGP 編號 ' + esc(s.norad) + ' 與目錄 ' + n + ' 不同' + (s.own_dist_km != null ? '；SupGP ' + n + ' 的星曆相距 ' + s.own_dist_km + ' km' : '') + '</div>';
    return h;
  }

  function render() {
    var j = D, la = j.launch || {};
    $('result').style.display = '';
    var nm = j.members.length, ng = j.groups.length;
    var mv = j.members.filter(function (m) { return m.evolution && m.evolution.status === 'maneuvering'; }).length;
    var sm = j.members.filter(function (m) { return m.supgp && m.supgp.status === 'matched'; }).length;
    var sw = j.members.filter(function (m) { return m.supgp && m.supgp.swap_suspected; }).length;
    $('sum').innerHTML = '<b style="font-size:15px;color:var(--hi)">' + esc(j.tag) + '</b> ' + esc(la.date || '') + ' ' + esc(la.lv || '') + ' ' + esc(la.mission || la.flight || '') +
      '<div class="muted" style="margin-top:4px">目錄中 ' + nm + ' 個物體、' + ng + ' 個軌道群；偵測到升軌 ' + mv + ' 顆；SupGP 吻合 ' + sm + ' 顆' + (sw ? '（<span class="warn">疑似編號互換 ' + sw + ' 顆</span>）' : '') + '；已不在目錄 ' + j.not_in_catalog.length + ' 個' +
      (j.t0 ? '；共同曆元 ' + esc(j.t0) + ' UTC' : '') + '</div>';
    if (!nm) { $('groups').innerHTML = '<div class="muted">目錄中沒有這次發射的物體</div>'; $('chart').innerHTML = ''; renderGone(); return; }
    var byN = {}; j.members.forEach(function (m) { byN[m.norad] = m; });
    $('groups').innerHTML = j.groups.map(function (g) {
      var head = '<tr class="ghead"><td colspan="12"><span class="dot" style="background:' + gcol(g.id) + '"></span><b>' + g.id + '</b>　' + g.count + ' 個物體・傾角 ' + g.incl + '°・升交點 ' + g.raan +
        '°・平均高度 ' + g.alt_min_km + '～' + g.alt_max_km + ' km・類型 ' + g.types.map(function (t) { return TYPE[t] || t; }).join('、') + '<span class="muted">（參考星 ' + g.ref + '）</span></td></tr>';
      return head + g.order.map(function (n) {
        var m = byN[n];
        var nm2 = esc(m.name) + (m.official_name && m.official_name !== m.name ? '<div class="muted">正式名稱 ' + esc(m.official_name) + '</div>' : '');
        return '<tr><td class="num">' + m.order + '</td><td class="num">' + m.norad + '<div class="muted">' + esc(m.intl) + '</div></td><td>' + nm2 + '</td><td>' + esc(TYPE[m.object_type] || m.object_type || '—') +
          '</td><td class="num">' + f(m.perigee_km, 1) + ' / ' + f(m.apogee_km, 1) + '</td><td class="num">' + f(m.incl, 3) + '</td><td class="num">' + (m.du_deg == null ? '—' : (m.du_deg > 0 ? '+' : '') + f(m.du_deg, 3)) +
          '</td><td class="num">' + f(m.dist_ref_km, 1) + '</td><td class="num">' + (m.drift_deg_day > 0 ? '+' : '') + f(m.drift_deg_day, 3) + '</td><td class="num">' + Number(m.bstar).toExponential(2) +
          '</td><td>' + evoCell(m.evolution) + '</td><td>' + supCell(m.supgp, m.norad) + '</td></tr>';
      }).join('');
    }).join('');
    renderChart();
    renderGone();
  }

  function renderGone() {
    var g = D.not_in_catalog;
    $('gone').innerHTML = g.length ? '<h3>已不在目錄（SATCAT 有紀錄）</h3>' + g.map(function (x) {
      return '<span class="chip">' + x.norad + ' ' + esc(x.name) + ' <span class="muted">' + esc(TYPE[x.object_type] || x.object_type) + (x.decay ? '・再入 ' + esc(x.decay) : '') + '</span></span>';
    }).join('') : '';
  }

  /* 高度歷史（平均高度），依軌道群上色 */
  function renderChart() {
    var ser = D.members.filter(function (m) { return m.evolution && m.evolution.series.length; });
    if (!ser.length) { $('chart').innerHTML = '<div class="muted">資料庫中沒有這些物體的歷史 TLE</div>'; return; }
    var W = 1100, H = 320, L = 60, R = 16, T = 14, B = 34;
    var t = function (s) { return Date.parse(s.replace(' ', 'T') + 'Z'); };
    var xs = [], ys = [];
    ser.forEach(function (m) { m.evolution.series.forEach(function (p) { xs.push(t(p[0])); ys.push(p[1]); }); });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (x1 === x0) x1 = x0 + 3600e3;
    var pad = Math.max(2, (y1 - y0) * 0.06); y0 -= pad; y1 += pad;
    var X = function (v) { return L + (v - x0) / (x1 - x0) * (W - L - R); }, Y = function (v) { return T + (1 - (v - y0) / (y1 - y0)) * (H - T - B); };
    var g = '';
    for (var i = 0; i <= 5; i++) {
      var yv = y0 + (y1 - y0) * i / 5;
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(yv) + '" y2="' + Y(yv) + '" stroke="#21262d"/><text x="' + (L - 6) + '" y="' + (Y(yv) + 4) + '" text-anchor="end" fill="#8b949e" font-size="11">' + yv.toFixed(0) + '</text>';
      var xv = x0 + (x1 - x0) * i / 5, d = new Date(xv);
      g += '<text x="' + X(xv) + '" y="' + (H - 12) + '" text-anchor="middle" fill="#8b949e" font-size="11">' + (d.getUTCMonth() + 1) + '/' + d.getUTCDate() + '</text>';
    }
    var lines = ser.map(function (m) {
      var pts = m.evolution.series.map(function (p) { return X(t(p[0])).toFixed(1) + ',' + Y(p[1]).toFixed(1); }).join(' ');
      var last = m.evolution.series[m.evolution.series.length - 1];
      return '<g><title>' + m.norad + ' ' + esc(m.name) + '（' + m.group + '）：' + last[1] + ' km</title><polyline fill="none" stroke="' + gcol(m.group) + '" stroke-width="1.6" stroke-opacity="0.85" points="' + pts + '"/>' +
        m.evolution.series.map(function (p) { return '<circle cx="' + X(t(p[0])).toFixed(1) + '" cy="' + Y(p[1]).toFixed(1) + '" r="1.8" fill="' + gcol(m.group) + '"/>'; }).join('') + '</g>';
    }).join('');
    $('chart').innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto;background:#0d1117;border:1px solid #21262d;border-radius:6px">' + g +
      '<text x="12" y="' + (T + 8) + '" fill="#8b949e" font-size="11">平均高度 km</text>' + lines + '</svg>' +
      '<div class="muted">日期為 UTC；滑鼠停在線上看 NORAD 與最新高度。顏色＝軌道群（' + D.groups.map(function (g) { return '<span style="color:' + gcol(g.id) + '">■</span> ' + g.id; }).join('　') + '）。</div>';
  }

  $('q').addEventListener('keydown', function (e) { if (e.key === 'Enter') run(); });
  $('days').addEventListener('change', loadRecent);
  window.LA = { run: run };
  var u = new URLSearchParams(location.search), q0 = u.get('tag') || u.get('norad');
  loadRecent();
  if (q0) { $('q').value = q0; run(); }
})();
