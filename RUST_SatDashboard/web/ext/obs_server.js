/* 觀測資料（Rust 單機版）：存在伺服器 user_private\observations.json，依帳號權限（編輯者新增修改、管理者複核）。
   介面與線上版 obs_store.js 相同（OBS_BACKEND），由 obs.js 共用。 */
(function () {
  'use strict';
  var DATA = null;
  function api(method, url, body) {
    var o = { method: method, headers: {} };
    if (body !== undefined) { o.body = JSON.stringify(body); o.headers['Content-Type'] = 'application/json'; }
    return fetch(url, o).then(function (r) {
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); throw new Error('請先登入'); }
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function strip(recs) { return recs.map(function (r) { var o = Object.assign({}, r); return o; }); }
  window.OBS_BACKEND = {
    where: '本機 user_private\\observations.json',
    caps: function () {
      return api('GET', '/api/auth/me').then(function (m) {
        var p = m.perms || [];
        return { canEdit: p.indexOf('modify') >= 0, canReview: p.indexOf('admin') >= 0, user: m.user ? m.user + '（' + (m.role_label || '') + '）' : (m.role_label || '') };
      });
    },
    load: function () { return api('GET', '/api/obs/data').then(function (d) { DATA = d; return d; }); },
    add: function (kind, recs) { return api('POST', '/api/obs/' + kind, { records: strip(recs) }); },
    update: function (kind, id, rec) { return api('PUT', '/api/obs/' + kind + '/' + encodeURIComponent(id), rec); },
    remove: function (kind, id) { return api('DELETE', '/api/obs/' + kind + '/' + encodeURIComponent(id)); },
    review: function (kind, id, rv) { return api('POST', '/api/obs/' + kind + '/' + encodeURIComponent(id) + '/review', rv); },
    check: function () { return api('GET', '/api/obs/check'); }
  };
})();
