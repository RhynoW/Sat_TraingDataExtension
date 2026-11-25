/* 星歷資料最後更新時間（src/ephemeris.rs）：接在地球儀 DB 資訊列後面，含「重新抓取」連結 */
(function () {
  function fmt(iso) { return iso ? iso.replace('T', ' ').slice(0, 16) + ' UTC' : '—'; }
  function run() {
    var anchor = document.getElementById('dbi-size');
    if (!anchor || !anchor.parentNode) return;
    var bar = anchor.parentNode;
    var box = document.createElement('span');
    box.id = 'ephem-badge';
    bar.appendChild(box);
    function load() {
      fetch('/api/ephemeris/status').then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
        if (!s) return;
        var h = s.last_updated ? (Date.now() - new Date(s.last_updated)) / 3600000 : 1e9;
        var gp = s.gp;
        box.innerHTML = '<span class="dbi-sep">|</span><span class="dbi-k">星歷更新：</span><span class="dbi-v ' + (h < 48 ? 'ok' : 'warn') + '" title="' +
          (gp ? '最近重抓：' + gp.source + ' ' + fmt(gp.fetched_at) + '（' + gp.count + ' 筆，更新 ' + gp.newer + ' 顆）' : '尚未重抓；顯示資料庫下載時間') +
          '&#10;最新 TLE 曆元：' + fmt(s.index && s.index.epoch_latest) + '">' + fmt(s.last_updated) + '</span> ' +
          '<a href="/satadmin?tab=ephem" target="_blank" style="color:#58a6ff;text-decoration:none" title="查看星歷狀態或一鍵重新抓取">' + (s.job && s.job.running ? '⏳ 重抓中' : '↻ 重新抓取') + '</a>';
        if (s.job && s.job.running) setTimeout(load, 5000);
      }).catch(function () {});
    }
    load();
    setInterval(load, 10 * 60 * 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
