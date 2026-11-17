/* Rust 單機版前端補充（不屬於 Python 版同步檔；sync_web.py 把本檔掛進 globe、taipei、cable、rpo3d 頁，mission.html 直接引用）
 * 1. 啟動預設視角：台灣上空（Cesium.Camera.DEFAULT_VIEW_RECTANGLE；Home 鍵也回到這裡）
 * 2. 地球儀頂端工具列「🛰 任務規劃」按鈕：亮黃、高對比
 * 3. 版本日期與聯絡資訊（/api/about）：頁面有 #about-slot 就放進去，否則顯示在右下角 Logo 左側
 * 4. 預設底圖：地形+海底地形 5.4K（後端 /api/globe_texture/default），地球儀的底圖選單隱藏。
 *    Python 版同步來的 globe.js、taipei.js、rpo3d.js、cable.html 以 Viewer 的 imageryProvider 選項指定底圖，
 *    CesiumJS 1.104 起已移除該選項（內附 1.114），而且 Viewer 看到 imageryProvider 會把 baseLayer 設成 false，
 *    結果沒有任何影像圖層（一片藍）。這裡在每個 Scene 第一次繪製時，沒有影像圖層就放上地形+海底地形 5.4K。
 * 5. 線上更新（/api/update/*）：資料庫與程式的新版提示、更新按鈕、進度與重新啟動 */
(function () {
  "use strict";
  // 以台灣（約 121°E、23.7°N）為中心、正上方俯視；範圍約東亞至西太平洋
  var TW = [96.0, 3.5, 146.0, 43.5];

  function applyCamera() {
    if (!window.Cesium || !Cesium.Camera || !Cesium.Rectangle) return false;
    Cesium.Camera.DEFAULT_VIEW_RECTANGLE = Cesium.Rectangle.fromDegrees(TW[0], TW[1], TW[2], TW[3]);
    Cesium.Camera.DEFAULT_VIEW_FACTOR = 0;
    // 每個 Scene 第一次繪製時：沒有任何影像圖層就放上地形+海底地形 5.4K
    var P = Cesium.Scene && Cesium.Scene.prototype;
    if (P && !P.__sdHook) {
      var render = P.render;
      P.render = function () {
        // 前 600 幀內（約 10 秒）只要沒有任何影像圖層就補上一次；頁面自己放了底圖就不動
        if (!this.__sdBase) {
          this.__sdFrames = (this.__sdFrames || 0) + 1;
          try {
            var L = this.imageryLayers;
            if (L && L.length === 0) {
              L.add(Cesium.ImageryLayer.fromProviderAsync(Cesium.SingleTileImageryProvider.fromUrl("/api/globe_texture/default", {
                rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
                credit: "NASA Visible Earth（地形＋海底地形 5.4K）",
              })), 0);
              this.__sdBase = true;
            } else if (this.__sdFrames > 600) {
              this.__sdBase = true;
            }
          } catch (e) { this.__sdBase = true; console.warn("預設底圖載入失敗", e); }
        }
        return render.apply(this, arguments);
      };
      P.__sdHook = true;   // 原型上的旗標名稱不能和每個 Scene 的 __sdBase 相同（會被繼承）
    }
    return true;
  }

  // 各頁以 window.loadCesium 動態載入 Cesium：包住成功回呼，在建立 Viewer 之前設好預設視角與底圖
  if (!applyCamera() && typeof window.loadCesium === "function") {
    var orig = window.loadCesium;
    window.loadCesium = function (ok, fail) {
      return orig.call(this, function () { applyCamera(); if (ok) ok.apply(this, arguments); }, fail);
    };
  }

  var css = "#basemap-bar{display:none!important}" +
    ".sd-about{font:11px/1.4 'Microsoft JhengHei','Noto Sans TC',sans-serif;color:#c9d1d9;white-space:nowrap}" +
    ".sd-about a{color:#58a6ff;text-decoration:none}.sd-about a:hover{text-decoration:underline}" +
    ".sd-about.float{position:fixed;right:170px;bottom:8px;z-index:20;background:rgba(1,4,9,.78);border:1px solid #30363d;" +
    "border-radius:6px;padding:3px 9px}" +
    ".sd-upd{margin-left:8px}.sd-upd b{color:#f2cc60;font-weight:600}.sd-upd .ok{color:#3fb950}.sd-upd .err{color:#ff7b72}" +
    ".sd-upd button{font:inherit;background:#238636;color:#fff;border:0;border-radius:4px;padding:0 6px;margin-left:4px;cursor:pointer}" +
    ".sd-upd button.sec{background:#30363d}" +
    "#mission-link{color:#111!important;background:#ffe600!important;border:1px solid #fff59d!important;" +
    "font-weight:700;box-shadow:0 0 6px rgba(255,230,0,.45)}#mission-link:hover{background:#fff176!important}";
  var st = document.createElement("style");
  st.textContent = css;
  document.head.appendChild(st);

  function about() {
    fetch("/api/about").then(function (r) { return r.json(); }).then(function (a) {
      var slot = document.getElementById("about-slot");
      var el = document.createElement("span");
      el.className = "sd-about" + (slot ? "" : " float");
      el.title = a.app + "（" + a.arch + "）";
      el.innerHTML = "Rust 單機版 v" + a.version + "・版本日期 " + a.build_date + "・聯絡：" +
        '<a href="' + a.contact.url + '" target="_blank" rel="noopener">' + a.contact.name + "（LinkedIn）</a>";
      var upd = document.createElement("span");
      upd.className = "sd-upd";
      el.appendChild(upd);
      (slot || document.body).appendChild(el);
      updater(upd, a);
    }).catch(function () { /* 舊版後端沒有 /api/about */ });
  }

  // ── 線上更新 ──
  function mb(n) { return n ? (n / 1e6).toFixed(0) + " MB" : ""; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function updater(box, about0) {
    var timer = null;
    function post(path) {
      return fetch("/api/update/" + path, { method: "POST" }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.error) alert(d.error);
        return d;
      });
    }
    function schedule(ms) { clearTimeout(timer); timer = setTimeout(load, ms); }
    function render(s) {
      var j = s.job || {}, h = [];
      if (j.running) {
        var pct = j.total ? Math.floor(100 * j.done / j.total) + "%" : "";
        h.push("<b>" + (j.kind === "app" ? "程式" : "資料庫") + "更新：" + esc(j.message) + " " + pct + "</b>");
      } else {
        if (j.phase === "done") h.push('<span class="ok">' + esc(j.message) + "</span>");
        if (j.phase === "error") h.push('<span class="err" title="' + esc(j.message) + '">更新失敗：' + esc(j.message).slice(0, 60) + "</span>");
        if (s.restart_pending) h.push('<button data-act="restart">重新啟動</button>');
        if (s.error) h.push('<span class="err" title="' + esc(s.error) + '">無法檢查更新</span>');
        if (s.db && s.db.update_available) h.push("<b>資料庫有新版 " + esc(s.db.version) + "</b>（" + mb(s.db.download_size) + '）<button data-act="db">更新</button>');
        else if (s.db) h.push('<span class="ok" title="資料庫版本 ' + esc(s.db.version) + '">資料庫為最新</span>');
        if (s.app && s.app.update_available) h.push("<b>程式有新版 v" + esc(s.app.version) + "（" + esc(s.app.build_date) + "）</b>" +
          (s.app.notes ? '<span title="' + esc(s.app.notes) + '"> ⓘ</span>' : "") + "（" + mb(s.app.download_size) + '）<button data-act="app">更新</button>');
        h.push('<button class="sec" data-act="check" title="' + esc(s.checked_at ? "上次檢查 " + s.checked_at : "尚未檢查") + '">' + (s.checking ? "檢查中…" : "檢查更新") + "</button>");
      }
      box.innerHTML = "・" + h.join(" ");
      box.querySelectorAll("button[data-act]").forEach(function (b) {
        b.onclick = function () {
          var act = b.dataset.act;
          if (act === "check") { b.textContent = "檢查中…"; post("check").then(function () { load(); }); return; }
          if (act === "restart") { restart(); return; }
          var what = act === "db" ? "下載並替換衛星資料庫" : "下載新版程式（按「重新啟動」後生效）";
          if (!confirm("確定要" + what + "？")) return;
          post(act).then(function () { schedule(300); });
        };
      });
      schedule(j.running || s.checking ? 1000 : 600000);
    }
    function load() {
      fetch("/api/update/status").then(function (r) { return r.json(); }).then(render).catch(function () { schedule(600000); });
    }
    function restart() {
      box.innerHTML = "・<b>重新啟動中…</b>";
      post("restart").then(function () {
        var tries = 0;
        (function wait() {
          setTimeout(function () {
            fetch("/api/about").then(function (r) { return r.json(); }).then(function (a) {
              if (a.version !== about0.version || a.build_date !== about0.build_date || tries > 20) location.reload(); else { tries++; wait(); }
            }).catch(function () { tries++; wait(); });
          }, 1000);
        })();
      });
    }
    load();
  }
  // 版本列只放在地球儀首頁與有 #about-slot 的頁面（任務規劃）
  var wantAbout = location.pathname === "/" || document.getElementById("about-slot");
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { if (location.pathname === "/" || document.getElementById("about-slot")) about(); });
  } else if (wantAbout) about();
})();
