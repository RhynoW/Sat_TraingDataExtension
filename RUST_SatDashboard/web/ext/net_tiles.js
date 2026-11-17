/* 網路圖磚疊圖（Cesium 版）
 * 圖資目錄：window.MAP_LAYERS（沿用 Rust_WMTS_Server/static/layers.js，由 scripts/sync_web.py 同步）。
 * 圖磚一律走本機代理 /api/tiles/*：補 CORS（Cesium 以 WebGL 貼圖使用圖磚，遠端沒有 CORS 標頭就會被擋）、
 * 磁碟快取（看過的區域離線也能用）。
 * 掛載方式：包裝 Cesium.Scene.prototype.render，每個場景第一次渲染時自動加上「🗺 網路圖磚」面板，
 * 不需修改各頁程式（地球儀、台北覆蓋、海纜…）。 */
(function () {
  "use strict";
  var ML = window.MAP_LAYERS;
  if (!ML) return;

  var TW_RECT = [117.5, 20.5, 123.5, 27.0];          // 台灣圖資之請求範圍（減少無涵蓋處之請求）
  var GLOBAL_IDS = { osm: 1, esri: 1 };
  var OK_TOKENS = /\{(z|x|y|-y|TileMatrix|TileCol|TileRow)\}/g;

  function b64url(s) {
    return btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function usableTemplate(t) {
    return typeof t === "string" && /^https?:\/\//.test(t) && t.replace(OK_TOKENS, "").indexOf("{") < 0;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // 依圖層定義產生代理網址與縮放上限
  function source(def, opt) {
    if (def.kind === "nlsc-tile") {
      return {
        url: "/api/tiles/xyz/{z}/{x}/{y}?t=" +
          b64url("https://wmts.nlsc.gov.tw/wmts/" + def.layer + "/default/GoogleMapsCompatible/{z}/{y}/{x}"),
        max: def.maxNativeZoom || 18,
      };
    }
    if (def.wms || def.kind === "wms" || def.kind === "wms-select") {
      var p = {};
      Object.keys(def.wms || {}).forEach(function (k) { p[k.toLowerCase()] = def.wms[k]; });
      if (opt) p.layers = opt;
      var qs = Object.keys(p).map(function (k) { return "&" + encodeURIComponent(k) + "=" + encodeURIComponent(p[k]); }).join("");
      return { url: "/api/tiles/wms/{z}/{x}/{y}?t=" + b64url(def.template) + qs, max: 20 };
    }
    return { url: "/api/tiles/xyz/{z}/{x}/{y}?t=" + b64url(def.template), max: def.maxNativeZoom || def.maxZoom || 19 };
  }

  // ── 目錄整理 ──────────────────────────────────────────────────────────────
  var groupLabel = {};
  (ML.groups || []).forEach(function (g) { groupLabel[g.id] = g.label; });
  var BASES = (ML.layers || []).filter(function (l) {
    return (l.kind === "tile" || l.kind === "wms") && usableTemplate(l.template);
  });
  var OVERLAY_GROUPS = (ML.overlayGroups || []).map(function (g) {
    var items = g.overlays.filter(function (o) {
      if (o.kind === "nlsc-tile") return !!o.layer;
      if (o.kind === "tile-overlay") return usableTemplate(o.template) || (o.wms && /^https?:/.test(o.template));
      if (o.kind === "wms-select") return /^https?:/.test(o.template) && o.options && o.options.length;
      return false;
    });
    return { id: g.id, title: g.title, attribution: g.attribution, items: items };
  }).filter(function (g) { return g.items.length; });
  var OVERLAY_BY_ID = {};
  OVERLAY_GROUPS.forEach(function (g) {
    g.items.forEach(function (o) { OVERLAY_BY_ID[o.id] = { def: o, group: g }; });
  });
  var BASE_BY_ID = {};
  BASES.forEach(function (b) { BASE_BY_ID[b.id] = b; });

  // ── 樣式 ──────────────────────────────────────────────────────────────────
  function injectCss() {
    if (document.getElementById("nt-css")) return;
    var css = document.createElement("style");
    css.id = "nt-css";
    css.textContent = [
      ".nt-btn{position:absolute;left:10px;top:10px;z-index:20;background:rgba(22,27,34,.92);color:#e6edf3;",
      "border:1px solid #30363d;border-radius:18px;padding:6px 12px;font:13px 'Microsoft JhengHei','Noto Sans TC',sans-serif;cursor:pointer}",
      ".nt-btn:hover,.nt-btn.on{border-color:#58a6ff;color:#79c0ff}",
      ".nt-panel{position:absolute;left:10px;top:48px;z-index:20;width:320px;max-width:calc(100% - 20px);max-height:calc(100% - 140px);",
      "overflow:auto;background:rgba(13,17,23,.95);color:#c9d1d9;border:1px solid #30363d;border-radius:10px;",
      "padding:10px 12px;font:12px 'Microsoft JhengHei','Noto Sans TC',sans-serif;display:none;box-shadow:0 6px 24px rgba(0,0,0,.5)}",
      ".nt-panel.open{display:block}",
      ".nt-panel h4{margin:6px 0 6px;font-size:13px;color:#e6edf3}",
      ".nt-panel select{width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px}",
      ".nt-row{display:flex;align-items:center;gap:6px;margin:4px 0}",
      ".nt-row input[type=range]{flex:1}",
      ".nt-panel details{border-top:1px solid #21262d;padding:4px 0}",
      ".nt-panel summary{cursor:pointer;color:#e6edf3;padding:2px 0}",
      ".nt-panel label{display:flex;gap:6px;align-items:flex-start;margin:3px 0 3px 4px;cursor:pointer}",
      ".nt-hint{color:#8b949e}",
      ".nt-op{width:64px}",
      ".nt-attr{margin-top:8px;color:#8b949e;font-size:11px;line-height:1.5}",
      ".nt-attr a{color:#58a6ff}",
      ".nt-note{color:#8b949e;font-size:11px;margin:2px 0 6px}",
    ].join("");
    document.head.appendChild(css);
  }

  // ── 每個 Cesium 場景一份控制器 ─────────────────────────────────────────────
  function attach(scene) {
    var container = scene.canvas.closest(".cesium-viewer") || scene.canvas.parentElement;
    if (!container || scene.canvas.clientWidth < 320) return false;   // 容器尚未顯示：下次渲染再試
    injectCss();
    var layers = scene.imageryLayers;
    var storeKey = "netTiles:" + location.pathname;
    var state = { base: "", baseAlpha: 1, overlays: {}, hima: null };   // overlays: id → {alpha, opt}；hima: {band, back, alpha}
    try { Object.assign(state, JSON.parse(localStorage.getItem(storeKey) || "{}")); } catch (e) { /* 無痕或停用儲存 */ }
    var live = { base: null, overlays: {}, hima: null };     // 實際 ImageryLayer
    var himaInfo = {};                                        // layer → {latest, template, max_level}
    var busy = false;

    function save() {
      try { localStorage.setItem(storeKey, JSON.stringify(state)); } catch (e) { /* 忽略 */ }
    }
    function rect(def) {
      return GLOBAL_IDS[def.id] ? undefined : Cesium.Rectangle.fromDegrees(TW_RECT[0], TW_RECT[1], TW_RECT[2], TW_RECT[3]);
    }
    function makeLayer(def, opt, alpha) {
      var s = source(def, opt);
      var provider = new Cesium.UrlTemplateImageryProvider({
        url: s.url, maximumLevel: s.max, rectangle: rect(def),
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
      });
      var l = new Cesium.ImageryLayer(provider, { alpha: alpha });
      l.__nt = true;
      return l;
    }
    function alive(l) { return l && !l.isDestroyed() && layers.contains(l); }

    // Himawari：最新時刻往前 back×10 分鐘之 ISO 時刻
    function himaTime() {
      var info = state.hima && himaInfo[state.hima.band];
      if (!info || !info.latest) return null;
      var t = new Date(Date.parse(info.latest) - (state.hima.back || 0) * 600000);
      return t.toISOString().replace(/\.\d{3}Z$/, "Z");
    }
    function makeHimaLayer(band, time, alpha) {
      var info = himaInfo[band];
      var provider = new Cesium.UrlTemplateImageryProvider({
        url: "/api/tiles/xyz/{z}/{x}/{y}?t=" + b64url(info.template.replace("{time}", time)),
        maximumLevel: info.max_level, tilingScheme: new Cesium.WebMercatorTilingScheme(),
      });
      var l = new Cesium.ImageryLayer(provider, { alpha: alpha });
      l.__nt = true; l.__key = band + "@" + time;
      return l;
    }

    // 讓本模組圖層維持在正確位置：底圖在原底圖之上、疊圖在最上層；被頁面 removeAll 銷毀時自動重建
    function reconcile() {
      if (busy) return;
      busy = true;
      try {
        if (alive(live.base) && live.base.__id !== state.base) { layers.remove(live.base, true); live.base = null; }
        if (state.base && BASE_BY_ID[state.base]) {
          if (!alive(live.base)) {
            live.base = makeLayer(BASE_BY_ID[state.base], null, state.baseAlpha);
            live.base.__id = state.base;
            layers.add(live.base);
          }
          live.base.alpha = state.baseAlpha;
          layers.lowerToBottom(live.base);
          if (layers.length > 1) layers.raise(live.base);
        } else if (alive(live.base)) {
          layers.remove(live.base, true); live.base = null;
        }
        // Himawari 全圓盤：疊在底圖之上、台灣疊圖之下
        var ht = himaTime();
        var hkey = ht ? state.hima.band + "@" + ht : "";
        if (alive(live.hima) && live.hima.__key !== hkey) { layers.remove(live.hima, true); live.hima = null; }
        if (hkey) {
          if (!alive(live.hima)) { live.hima = makeHimaLayer(state.hima.band, ht, state.hima.alpha); layers.add(live.hima); }
          live.hima.alpha = state.hima.alpha;
          layers.raiseToTop(live.hima);
        }
        Object.keys(live.overlays).forEach(function (id) {
          var o = live.overlays[id];
          var want = state.overlays[id];
          if (!want || (want.opt || "") !== (o.__opt || "")) { if (alive(o)) layers.remove(o, true); delete live.overlays[id]; }
        });
        Object.keys(state.overlays).forEach(function (id) {
          var info = OVERLAY_BY_ID[id];
          if (!info) return;
          var want = state.overlays[id];
          var l = live.overlays[id];
          if (!alive(l)) {
            l = makeLayer(info.def, want.opt, want.alpha);
            l.__opt = want.opt || "";
            layers.add(l);
            live.overlays[id] = l;
          }
          l.alpha = want.alpha;
          layers.raiseToTop(l);
        });
      } finally {
        busy = false;
      }
      renderAttr();
      scene.requestRender();
    }
    layers.layerAdded.addEventListener(function (l) { if (!l.__nt) setTimeout(reconcile, 0); });
    layers.layerRemoved.addEventListener(function (l) { if (!busy) setTimeout(reconcile, 0); });

    // ── UI ──
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nt-btn";
    btn.textContent = "🗺 網路圖磚";
    btn.title = "疊加台灣公開 WMTS／WMS 圖資（國土測繪中心、中研院、地調中心…）";
    var panel = document.createElement("div");
    panel.className = "nt-panel";
    btn.onclick = function () { panel.classList.toggle("open"); btn.classList.toggle("on"); };

    var html = ['<h4>底圖</h4><select class="nt-base"><option value="">（頁面原底圖）</option>'];
    var byGroup = {};
    BASES.forEach(function (b) { (byGroup[b.group || ""] = byGroup[b.group || ""] || []).push(b); });
    Object.keys(byGroup).forEach(function (g) {
      html.push('<optgroup label="' + esc(g ? (groupLabel[g] || g) : "一般底圖") + '">');
      byGroup[g].forEach(function (b) { html.push('<option value="' + esc(b.id) + '">' + esc(b.label) + "</option>"); });
      html.push("</optgroup>");
    });
    html.push('</select><div class="nt-row">透明度<input type="range" class="nt-base-alpha" min="0" max="1" step="0.05"></div>');
    html.push('<h4>☁ Himawari 氣象衛星全圓盤</h4>' +
      '<label><input type="checkbox" class="nt-hima-on"><span style="flex:1">顯示（每 10 分鐘，NASA GIBS 重投影）</span></label>' +
      '<select class="nt-hima-band">' +
      '<option value="Himawari_AHI_Band13_Clean_Infrared">紅外 Band 13（10.4 µm，晝夜皆可）</option>' +
      '<option value="Himawari_AHI_Band3_Red_Visible_1km">可見光 Band 3（0.64 µm，1 km，僅白天）</option>' +
      '<option value="Himawari_AHI_Air_Mass">氣團 RGB（Air Mass）</option></select>' +
      '<div class="nt-row">時間<input type="range" class="nt-hima-back" min="0" max="144" step="1" style="direction:rtl"></div>' +
      '<div class="nt-row"><span class="nt-hima-time nt-hint" style="flex:1">—</span>' +
      '<button type="button" class="nt-hima-play" style="background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:2px 8px;cursor:pointer">▶ 近 2 小時動畫</button></div>' +
      '<div class="nt-row">透明度<input type="range" class="nt-hima-alpha" min="0" max="1" step="0.05"></div>' +
      '<div class="nt-note">地球儀疊圖為 NASA GIBS 重投影，約落後 1 小時；最新影像見下方 JMA 全圓盤。</div>' +
      '<h4>🛰 JMA 最新全圓盤影像（約落後 10~20 分鐘）</h4>' +
      '<select class="nt-jma-band"></select>' +
      '<div class="nt-row"><span class="nt-jma-time nt-hint" style="flex:1">—</span>' +
      '<a class="nt-jma-dl" href="#" style="color:#58a6ff;text-decoration:none;white-space:nowrap">⬇ 下載</a></div>' +
      '<a class="nt-jma-open" href="#" target="_blank" rel="noopener" title="另開分頁看原尺寸">' +
      '<img class="nt-jma-img" alt="Himawari-9 全圓盤" style="display:none;width:100%;border-radius:6px;margin-top:4px;background:#fff"></a>' +
      '<div class="nt-note">來源：<a href="https://www.data.jma.go.jp/mscweb/data/himawari/list_fd_.html" target="_blank" rel="noopener" style="color:#58a6ff">JMA 氣象衛星中心</a>' +
      '（601×601 地球同步視角，已含海岸線與經緯網；不疊到地球儀上）。檔名時刻為觀測起始，影像上的標註時刻約晚 10 分鐘。</div>');
    html.push('<h4>疊圖</h4><div class="nt-note">台灣公開圖資，請放大至台灣區域查看；首次載入需連網，之後自動快取。</div>');
    OVERLAY_GROUPS.forEach(function (g) {
      var open = g.items.some(function (o) { return state.overlays[o.id]; });
      html.push("<details" + (open ? " open" : "") + "><summary>" + esc(g.title) + " <span class=\"nt-hint\">(" + g.items.length + ")</span></summary>");
      g.items.forEach(function (o) {
        html.push('<label><input type="checkbox" data-ov="' + esc(o.id) + '"><span style="flex:1">' + esc(o.panelLabel || o.label) +
          (o.hint ? ' <span class="nt-hint">' + esc(o.hint) + "</span>" : "") + "</span>" +
          '<input type="range" class="nt-op" data-op="' + esc(o.id) + '" min="0" max="1" step="0.05" title="透明度"></label>');
        if (o.kind === "wms-select") {
          html.push('<select data-opt="' + esc(o.id) + '" style="margin:0 0 4px 24px;width:calc(100% - 24px)">' +
            o.options.map(function (x) { return '<option value="' + esc(x.id) + '">' + esc(x.label) + "</option>"; }).join("") + "</select>");
        }
      });
      html.push("</details>");
    });
    html.push('<div class="nt-attr"></div>');
    panel.innerHTML = html.join("");
    container.appendChild(btn);
    container.appendChild(panel);

    var baseSel = panel.querySelector(".nt-base");
    var baseAlpha = panel.querySelector(".nt-base-alpha");
    baseSel.value = BASE_BY_ID[state.base] ? state.base : "";
    baseAlpha.value = state.baseAlpha;
    baseSel.onchange = function () { state.base = baseSel.value; save(); reconcile(); };
    baseAlpha.oninput = function () { state.baseAlpha = +baseAlpha.value; save(); reconcile(); };

    panel.querySelectorAll("input[data-ov]").forEach(function (cb) {
      var id = cb.dataset.ov;
      var def = OVERLAY_BY_ID[id].def;
      var op = panel.querySelector('input[data-op="' + id + '"]');
      var sel = panel.querySelector('select[data-opt="' + id + '"]');
      var cur = state.overlays[id];
      cb.checked = !!cur;
      op.value = cur ? cur.alpha : (def.opacity != null ? def.opacity : 1);
      if (sel && cur && cur.opt) sel.value = cur.opt;
      function apply() {
        if (cb.checked) state.overlays[id] = { alpha: +op.value, opt: sel ? sel.value : "" };
        else delete state.overlays[id];
        save(); reconcile();
      }
      cb.onchange = apply;
      op.oninput = function () { if (cb.checked) apply(); };
      if (sel) sel.onchange = function () { if (cb.checked) apply(); };
    });

    var hOn = panel.querySelector(".nt-hima-on");
    var hBand = panel.querySelector(".nt-hima-band");
    var hBack = panel.querySelector(".nt-hima-back");
    var hAlpha = panel.querySelector(".nt-hima-alpha");
    var hTime = panel.querySelector(".nt-hima-time");
    var hPlay = panel.querySelector(".nt-hima-play");
    var hs = state.hima || { band: "Himawari_AHI_Band13_Clean_Infrared", back: 0, alpha: 0.75 };
    hOn.checked = !!state.hima;
    hBand.value = hs.band; hBack.value = hs.back || 0; hAlpha.value = hs.alpha;
    function himaApply() {
      state.hima = hOn.checked ? { band: hBand.value, back: +hBack.value, alpha: +hAlpha.value } : null;
      save(); reconcile(); himaLabel();
    }
    function himaLabel() {
      var t = himaTime() || (function () {
        var info = himaInfo[hBand.value];
        return info && info.latest ? new Date(Date.parse(info.latest) - hBack.value * 600000).toISOString() : null;
      })();
      if (!t) { hTime.textContent = "最新時刻查詢中…（需連網）"; return; }
      var d = new Date(t);
      var tw = new Date(d.getTime() + 8 * 3600000).toISOString().slice(5, 16).replace("T", " ");
      hTime.textContent = d.toISOString().slice(5, 16).replace("T", " ") + " UTC（台灣 " + tw + "）" + (+hBack.value ? "" : "・最新");
    }
    hOn.onchange = himaApply; hBand.onchange = himaApply; hAlpha.oninput = himaApply;
    hBack.oninput = function () { himaLabel(); };
    hBack.onchange = himaApply;
    var playTimer = null;
    hPlay.onclick = function () {
      if (playTimer) { clearInterval(playTimer); playTimer = null; hPlay.textContent = "▶ 近 2 小時動畫"; return; }
      hOn.checked = true;
      var k = 12;
      hPlay.textContent = "■ 停止";
      playTimer = setInterval(function () {
        hBack.value = k; himaApply();
        k = k > 0 ? k - 1 : 12;
      }, 1500);
    };
    // JMA 最新全圓盤：面板展開時查詢最新一格，每 5 分鐘更新
    var jBand = panel.querySelector(".nt-jma-band"), jTime = panel.querySelector(".nt-jma-time");
    var jImg = panel.querySelector(".nt-jma-img"), jDl = panel.querySelector(".nt-jma-dl"), jOpen = panel.querySelector(".nt-jma-open");
    var jmaTimer = null;
    function jmaLoad() {
      jTime.textContent = "查詢最新影像中…（需連網）";
      fetch("/api/himawari/jma_latest?band=" + encodeURIComponent(jBand.value || "b13")).then(function (r) { return r.json(); }).then(function (d) {
        if (!jBand.options.length) {
          jBand.innerHTML = d.bands.map(function (b) { return '<option value="' + esc(b.id) + '">' + esc(b.label) + "</option>"; }).join("");
          jBand.value = d.band;
        }
        var L = d.latest;
        if (!L) { jTime.textContent = "JMA 目前沒有今天的影像（或離線）"; jImg.style.display = "none"; return; }
        var t = new Date(L.slot), tw = new Date(t.getTime() + 8 * 3600000).toISOString();
        var day = L.slot.slice(0, 10).replace(/-/g, "");
        var src = "/api/himawari/jma_img?band=" + d.band + "&hhmm=" + L.hhmm + "&date=" + day;
        jTime.textContent = L.slot.slice(5, 16).replace("T", " ") + " UTC（台灣 " + tw.slice(5, 16).replace("T", " ") + "）・" + L.age_min + " 分鐘前";
        jImg.src = src; jImg.style.display = "block";
        jOpen.href = src; jDl.href = src + "&dl=1";
      }).catch(function () { jTime.textContent = "無法連線 JMA（離線？）"; });
    }
    jBand.onchange = jmaLoad;
    btn.addEventListener("click", function () {
      if (!panel.classList.contains("open")) { clearInterval(jmaTimer); jmaTimer = null; return; }
      jmaLoad();
      if (!jmaTimer) jmaTimer = setInterval(jmaLoad, 300000);
    });

    fetch("/api/himawari/latest").then(function (r) { return r.json(); }).then(function (d) {
      (d.layers || []).forEach(function (l) { himaInfo[l.layer] = l; });
      himaLabel(); reconcile();
    }).catch(function () { hTime.textContent = "無法取得 Himawari 最新時刻（離線？）"; });

    function renderAttr() {
      var parts = [];
      if (state.base && BASE_BY_ID[state.base] && BASE_BY_ID[state.base].attribution) parts.push(BASE_BY_ID[state.base].attribution);
      if (state.hima) parts.push('Himawari-9 AHI（JMA）經 <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA GIBS</a>');
      Object.keys(state.overlays).forEach(function (id) {
        var g = OVERLAY_BY_ID[id] && OVERLAY_BY_ID[id].group;
        if (g && g.attribution && parts.indexOf(g.attribution) < 0) parts.push(g.attribution);
      });
      var box = panel.querySelector(".nt-attr");
      // 出處字串來自圖資目錄（含連結 HTML），非使用者輸入
      box.innerHTML = parts.length ? "出處：" + parts.join("；") : "圖資目錄：Rust_WMTS_Server layers.js";
      var n = (state.base ? 1 : 0) + (state.hima ? 1 : 0) + Object.keys(state.overlays).length;
      btn.textContent = "🗺 網路圖磚" + (n ? "（" + n + "）" : "");
    }
    reconcile();
    return true;
  }

  // ── 掛載：等 Cesium 載入後包裝 Scene.render ─────────────────────────────────
  function hook() {
    if (!window.Cesium || !Cesium.Scene || !Cesium.Scene.prototype) return false;
    var proto = Cesium.Scene.prototype;
    if (proto.__ntHooked) return true;
    var orig = proto.render;
    proto.render = function () {
      if (!this.__ntDone) {
        try { this.__ntDone = attach(this) !== false; } catch (e) { this.__ntDone = true; console.warn("網路圖磚面板初始化失敗", e); }
      }
      return orig.apply(this, arguments);
    };
    proto.__ntHooked = true;
    return true;
  }
  if (!hook()) {
    var timer = setInterval(function () { if (hook()) clearInterval(timer); }, 100);
  }
})();
