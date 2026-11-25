/* 帳號登入狀態（src/auth.rs）：已啟用帳號時在 #auth-badge 顯示使用者、角色與登出 */
(function () {
  function run() {
    var b = document.getElementById('auth-badge');
    if (!b) return;
    fetch('/api/auth/me').then(function (r) { return r.json(); }).then(function (m) {
      if (!m.auth_enabled || !m.logged_in) return;
      b.style.display = '';
      b.textContent = '👤 ' + m.user + '（' + m.role_label + '） ';
      var a = document.createElement('a');
      a.href = '#'; a.textContent = '登出'; a.style.color = '#58a6ff';
      a.onclick = function (e) { e.preventDefault(); fetch('/api/auth/logout', { method: 'POST' }).then(function () { location.href = '/login'; }); };
      b.appendChild(a);
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
