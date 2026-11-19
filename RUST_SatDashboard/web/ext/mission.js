/* 衛星任務規劃頁：地面站下行接收過頂預報（預設：中央大學太遙中心 × Vantor 星系，仰角 ≥ 15°）
 * 後端：/api/mission/config、/api/mission/schedule、/api/mission/passes（src/mission.rs） */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var TZ_MS = 8 * 3600000;                 // 台灣時間 UTC+8
  var RE_KM = 6378.137;
  var cfg = null, schedule = null, data = null, selNorad = null, selPass = -1;
  var DAY_MS = 86400000;
  var WEEK = "日一二三四五六";
  var REL = ["今天", "明天", "後天", "大後天"];
  var ORBIT_COLORS = ["#ff9f1a", "#21d4fd", "#ff5ccd", "#b9f227", "#ffd600", "#a78bfa", "#ff6b6b", "#4ade80", "#38bdf8", "#f472b6"];

  // 公開規格之天底（nadir）地面取樣距離 GSD（m）、天底影像幅寬 sw（km）與規格對應之運轉高度 h0（km）。
  // 來源：Vantor（原 Maxar）公開規格，經 Polar Geospatial Center〈Vantor Satellite Constellation〉整理（2026-11-19 查閱）。
  // WorldView-1 只有全色；WorldView-3 另有 SWIR 3.7 m，此處只列全色與多光譜。
  var LEGION = { pan: 0.34, ms: 1.36, sw: 10.0, h0: 518 };
  var SENSOR = {
    40115: { pan: 0.31, ms: 1.24, sw: 13.1, h0: 617 },   // WorldView-3
    35946: { pan: 0.46, ms: 1.84, sw: 16.4, h0: 770 },   // WorldView-2
    32060: { pan: 0.50, ms: null, sw: 17.7, h0: 496 },   // WorldView-1
    33331: { pan: 0.41, ms: 1.65, sw: 15.3, h0: 681 },   // GeoEye-1
    59625: LEGION, 59626: LEGION, 60452: LEGION, 60453: LEGION, 62900: LEGION, 62901: LEGION,
  };
  // 依幾何估算某地面點的 GSD：衛星高度 hKm、該點距地面軌跡之地心角 dDeg。
  // GSD 與斜距成正比；跨軌方向另除以入射角餘弦；合併值取沿軌、跨軌之幾何平均（與公開規格 20° 離天底值相符：
  // WorldView-3 0.31→0.34 m、Legion 0.34→0.37 m）。
  function gsdAt(sp, hKm, dDeg) {
    var R = RE_KM, lam = dDeg * Math.PI / 180, r = R + hKm;
    var rho = Math.sqrt(R * R + r * r - 2 * R * r * Math.cos(lam));            // 斜距（km）
    var eta = Math.asin(Math.min(1, R * Math.sin(lam) / rho));                 // 離天底角
    var inc = eta + lam;                                                       // 地面入射角（自當地天頂起算）
    var k = (hKm / sp.h0) * (rho / hKm), kx = k / Math.cos(inc);               // 沿軌、跨軌倍率（相對規格天底）
    return { rho: rho, eta: eta * 180 / Math.PI, inc: inc * 180 / Math.PI, nadir: hKm / sp.h0, along: k, cross: kx, gm: Math.sqrt(k * kx) };
  }
  // 影像幅寬：由規格（天底幅寬 sw @ h0）反求相機半視場角 α，再把視場兩緣（離天底角 η±α）投影到球面地表，
  // 幅寬＝兩緣之地心角差 × R。離天底時遠側比近側伸長更多，故非對稱；視場緣超過地平時回傳 null。
  function groundAngle(hKm, eta) {                      // 離天底角 eta（rad）→ 地心角（rad）
    var x = (RE_KM + hKm) / RE_KM * Math.sin(eta);
    return x >= 1 ? null : Math.asin(x) - eta;
  }
  function swathAt(sp, hKm, etaDeg) {
    var R = RE_KM, l0 = sp.sw / 2 / R;
    var a = Math.atan(R * Math.sin(l0) / (R + sp.h0 - R * Math.cos(l0)));   // 半視場角
    var e = etaDeg * Math.PI / 180, far = groundAngle(hKm, e + a), near = groundAngle(hKm, Math.abs(e - a));
    if (far == null || near == null) return null;
    return { fov: 2 * a * 180 / Math.PI, nadir: 2 * R * groundAngle(hKm, a),
             here: R * (e >= a ? far - near : far + near) };
  }
  function fmtM(x) { return x.toFixed(2); }
  function gsdHtml(norad, name, hKm, dDeg) {
    var sp = SENSOR[norad];
    if (!sp || !(hKm > 0)) return "";
    var g = gsdAt(sp, hKm, dDeg);
    function band(lbl, v, detail) {
      if (v == null) return "";
      return lbl + " " + fmtM(v * (detail ? g.gm : g.nadir)) + " m" +
        (detail ? "（沿軌 " + fmtM(v * g.along) + "、跨軌 " + fmtM(v * g.cross) + "）" : "");
    }
    var ms = sp.ms != null, w = swathAt(sp, hKm, g.eta);
    return "<br><b>地面最佳解析度（GSD）與影像幅寬估算</b>　" + esc(name) +
      "<br>公開規格：全色 " + sp.pan.toFixed(2) + " m" + (ms ? "、多光譜 " + sp.ms.toFixed(2) + " m" : "（無多光譜）") +
      "、幅寬 " + sp.sw.toFixed(1) + " km（天底，規格高度 " + sp.h0 + " km）" +
      "<br>Nadir（本次過頂高度約 " + Math.round(hKm) + " km）：" + band("全色", sp.pan, false) + (ms ? "、" + band("多光譜", sp.ms, false) : "") +
      (w ? "、幅寬約 " + w.nadir.toFixed(1) + " km" : "") +
      "<br>此格（距地面軌跡約 " + dDeg.toFixed(1) + "°）：離天底角約 " + g.eta.toFixed(1) + "°、入射角約 " + g.inc.toFixed(1) +
      "°、斜距約 " + Math.round(g.rho) + " km<br>　" + band("全色", sp.pan, true) + (ms ? "<br>　" + band("多光譜", sp.ms, true) : "") +
      "<br>　影像幅寬約 " + (w ? w.here.toFixed(1) + " km（跨軌方向單一條帶；視場角約 " + w.fov.toFixed(2) + "°）" : "—（視場緣超出地平）") +
      "<br><span style=\"opacity:.75\">幾何估算：GSD 隨斜距等比放大，跨軌再除以入射角餘弦，合併值取幾何平均；幅寬由規格反求相機視場角，" +
      "將視場兩緣投影至球面地表求得，離天底時遠側伸長較多。未計地形、姿態與大氣，實際影像解析度與幅寬依成像模式與產品處理而定" +
      "（可拼接多條帶擴大涵蓋）。規格來源：Vantor（原 Maxar）公開規格（Polar Geospatial Center 整理）。</span>";
  }

  // 時窗：台灣時間第 k 天（0 = 今天，從現在到午夜；1 = 明天 00:00–24:00 …）
  function dayWindow(k) {
    var now = Date.now();
    var mid = Math.floor((now + TZ_MS) / DAY_MS) * DAY_MS - TZ_MS;    // 今天 00:00（台灣）對應的 UTC 毫秒
    var s0 = mid + k * DAY_MS, e = s0 + DAY_MS, s = Math.max(now, s0);
    return { start: new Date(s).toISOString(), hours: Math.max(1, (e - s) / 3600000) };
  }
  function dayLabel(k) {
    var d = new Date(Math.floor((Date.now() + TZ_MS) / DAY_MS) * DAY_MS + k * DAY_MS);   // 以 UTC 欄位讀台灣日期
    var md = (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + "（" + WEEK[d.getUTCDay()] + "）";
    return (REL[k] ? REL[k] + "　" : "") + md + (k === 0 ? "　現在到午夜" : "");
  }
  // ── 衛星正下方（星下點）雲量預報（/api/mission/cloud_track，MET Norway；只顯示未來 3 天）──
  var WX_DAYS = 3, tcaCloud = {}, trackCloud = null, gridClouds = {}, gridBusy = {}, wxMeta = null, wxErr = null;
  var GRID_HALF = 4;                          // 地面軌跡左右各 4°
  var GRID_MAX = { "2": 200, "1": 600, "0.5": 2000 };   // 各網格密度每次過頂最多格數
  var GRID_REQ = 60;                          // 每次請求格數（後端上限 400；切小批以顯示計算進度）
  var gridProg = { done: 0, total: 0 };       // 雲量網格計算進度（格數）
  function gridStep() { return +$("wx-grid").value; }   // 雲量網格密度（度）：2（預設）、1、0.5
  function gkey(ps) { return ps.aos.t + "@" + gridStep(); }   // 快取鍵：過頂 AOS × 網格密度

  // 過頂的地面軌跡兩側 ±GRID_HALF° 內的網格格點（格點中心為網格間距的整數倍），每格記錄衛星最接近時的時刻
  function bandCells(ps) {
    var t0 = Date.parse(ps.aos.t) / 1000, tr = ps.track, best = {};
    var g = gridStep(), dk = Math.min(0.5, g / 2);
    var snap = function (x) { return Math.round(x / g) * g; };
    for (var i = 0; i < tr.length; i++) {
      var a = tr[i], b = tr[i + 1] || tr[i - 1];
      if (!b) break;
      var lat = a[3], lon = a[4], cl = Math.cos(lat * Math.PI / 180);
      var dlon = ((b[4] - lon + 540) % 360) - 180, de = dlon * cl, dn = b[3] - lat;
      if (!tr[i + 1]) { de = -de; dn = -dn; }
      var n = Math.hypot(de, dn) || 1, pe = dn / n, pn = -de / n;      // 垂直於軌跡的單位向量（東、北）
      for (var k = -GRID_HALF; k <= GRID_HALF + 1e-9; k += dk) {
        var la = snap(lat + k * pn), lo = snap(lon + k * pe / Math.max(cl, 0.05));
        if (la < -89 || la > 89) continue;
        lo = ((lo + 540) % 360) - 180;
        la = +la.toFixed(2); lo = +lo.toFixed(2);
        var key = la + "," + lo, d = Math.abs(k);
        if (!best[key] || d < best[key].d) best[key] = { lat: la, lon: lo, t: Math.round(t0 + a[0]), d: d };
      }
    }
    return Object.keys(best).map(function (k) { return best[k]; })
      .sort(function (x, y) { return x.d - y.d; }).slice(0, GRID_MAX[String(g)] || 600);
  }
  // 時窗內（且在預報範圍內）每一次顯示中的過頂都查詢兩側網格雲量；已查過或查詢中的略過，逐次依序查詢以免同時大量請求
  function loadGridClouds() {
    if (!wxOn()) return;
    var norad = selNorad;
    var todo = shown().filter(function (ps) {
      return inWx(Date.parse(ps.tca.t)) && !gridClouds[gkey(ps)] && !gridBusy[gkey(ps)];
    });
    if (!todo.length) return;
    todo.forEach(function (ps) { gridBusy[gkey(ps)] = true; });
    var todoCells = todo.map(function (ps) { return bandCells(ps); });
    gridProg = { done: 0, total: todoCells.reduce(function (a, c) { return a + c.length; }, 0) };
    showProg();
    renderWx();
    (function next(i) {
      if (i >= todo.length) return;
      if (i >= todo.length) return;
      var ps = todo[i], cells = todoCells[i], key = gkey(ps), step = gridStep();
      // 格數超過後端單次上限時分批查詢，結果依序串接
      var batches = [];
      for (var j = 0; j < cells.length; j += GRID_REQ) batches.push(cells.slice(j, j + GRID_REQ));
      var cl = [], err = null;
      batches.reduce(function (pr, b) {
        return pr.then(function () {
          var q = b.map(function (c) { return c.t + "," + c.lat + "," + c.lon; }).join(";");
          return fetch("/api/mission/cloud_track?grid=1&pts=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
            if (d.error) { err = d.error; cl = cl.concat(b.map(function () { return null; })); }
            else cl = cl.concat(d.points);
            if (norad === selNorad) { gridProg.done += b.length; showProg(); }
          });
        });
      }, Promise.resolve()).then(function () {
        if (norad !== selNorad) return;                 // 期間換了衛星：丟棄
        delete gridBusy[key];
        if (err && !cl.some(Boolean)) { wxErr = err; renderWx(); return next(i + 1); }
        gridClouds[key] = { cells: cells, cl: cl, step: step };
        renderWx(); draw();
        next(i + 1);
      }).catch(function (e) {
        if (norad !== selNorad) return;
        delete gridBusy[key]; wxErr = String(e.message || e); renderWx(); next(i + 1);
      });
    })(0);
  }

  function inWx(ms) { return ms <= Date.now() + WX_DAYS * DAY_MS; }
  // 地圖雲量方格：白色，雲量 0% 全透明 → 100% 接近不透明（貼近白色雲體的直覺）
  function cloudAlpha(p) { return Math.max(0, Math.min(100, p || 0)) / 100 * 0.85; }
  function cloudTip(c) {
    return "星下點 " + c.lat.toFixed(1) + "°N " + c.lon.toFixed(1) + "°E：總雲量 " + Math.round(c.cloud) + "%（低 " + Math.round(c.low) +
      "%、中 " + Math.round(c.mid) + "%、高 " + Math.round(c.high) + "%）" +
      (c.precip != null ? "；" + c.step_h + " 小時降水 " + c.precip + " mm" : "") + (c.step_h > 1 ? "（此時段預報為每 " + c.step_h + " 小時）" : "");
  }
  function cloudQuery(pts) {
    var q = pts.map(function (m) { return Math.round(Date.parse(m.t) / 1000) + "," + m.lat.toFixed(2) + "," + m.lon.toFixed(2); }).join(";");
    return fetch("/api/mission/cloud_track?pts=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) throw new Error(d.error);
      wxMeta = d; wxErr = null;
      return d.points;
    });
  }
  // 過頂清單「雲量」欄：各次過頂 TCA 時刻的星下點
  function loadTcaClouds() {
    tcaCloud = {};
    if (!wxOn()) { renderPasses(); return; }
    var list = data ? data.passes.filter(function (p) { return inWx(Date.parse(p.tca.t)); }) : [];
    if (!list.length) { renderPasses(); return; }
    var want = data;
    cloudQuery(list.map(function (p) { return p.tca; })).then(function (pts) {
      if (want !== data) return;
      list.forEach(function (p, i) { if (pts[i]) tcaCloud[p.tca.t] = pts[i]; });
      renderPasses();
    }).catch(function (e) { wxErr = String(e.message || e); renderPasses(); renderWx(); });
  }
  // 選定過頂：沿地面軌跡每 60 秒的星下點
  function loadTrackClouds() {
    trackCloud = null;
    if (!wxOn()) { renderWx(); return; }
    var ps = shown()[selPass];
    if (!ps || !inWx(Date.parse(ps.tca.t))) { renderWx(); return; }
    var pts = ps.marks.filter(function (m, k) { return k % 2 === 0 || k === ps.marks.length - 1; });
    var key = ps.aos.t;
    renderWx("查詢衛星正下方雲量…");
    cloudQuery(pts).then(function (r) {
      var cur = shown()[selPass];
      if (!cur || cur.aos.t !== key) return;
      trackCloud = { key: key, pts: pts, cl: r };
      renderWx();
    }).catch(function (e) { wxErr = String(e.message || e); renderWx(); });
  }
  function renderWx(msg) {
    var box = $("wx"), ps = shown()[selPass];
    if (!wxOn()) { box.innerHTML = '<div class="hint">勾選上方「計算並顯示雲量預報」後，才查詢衛星正下方色條、地圖上各次過頂兩側網格與過頂清單的雲量欄。</div>'; return; }
    if (!selNorad || !ps) { box.innerHTML = '<div class="hint">點選軌道與過頂後，顯示衛星正下方（星下點）的預報雲量。</div>'; return; }
    if (!inWx(Date.parse(ps.tca.t))) { box.innerHTML = '<div class="hint">雲量預報只提供未來 ' + WX_DAYS + " 天。</div>"; return; }
    if (msg) { box.innerHTML = '<div class="hint">' + msg + "</div>"; return; }
    if (wxErr && !trackCloud) { box.innerHTML = '<div class="hint">' + wxErr + "</div>"; return; }
    if (!trackCloud || trackCloud.key !== ps.aos.t) { box.innerHTML = ""; return; }
    var vals = trackCloud.cl.filter(Boolean).map(function (c) { return c.cloud; });
    var avg = vals.length ? Math.round(vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) : null;
    box.innerHTML = '<div class="hint">' + esc(data.satellite.name) + " 過頂 #" + (selPass + 1) + " 衛星正下方雲量（星下點，每 60 秒）" +
      (avg != null ? "・平均 " + avg + "%" : "") + "・" + wxMeta.source + (wxMeta.stale ? "・離線，顯示上次的預報" : "") +
      (wxMeta.updated_at ? "・更新 " + tw(wxMeta.updated_at, true).slice(0, 11) : "") + "</div>" +
      gridLine(ps) +
      '<div class="hint">地圖上的白色方格為地面軌跡左右各 ' + GRID_HALF +
      '° 內的 ' + gridStep() + '° 網格，每格取衛星經過時刻的預報：雲量越多越白、越不透明，0% 為全透明。光學影像要看這裡的雲；X 波段下行主要受降雨影響。</div>';
  }
  function gridLine(ps) {
    var g = gridClouds[gkey(ps)];
    if (!g && gridBusy[gkey(ps)]) return '<div class="hint" id="wx-prog">' + progText() + '</div>';
    if (!g) return "";
    var v = g.cl.filter(Boolean).map(function (c) { return c.cloud; });
    if (!v.length) return '<div class="hint">地面軌跡兩側網格沒有預報資料</div>';
    var clear = v.filter(function (x) { return x <= 30; }).length;
    var avg = Math.round(v.reduce(function (a, b) { return a + b; }, 0) / v.length);
    return '<div class="hint">地面軌跡左右各 ' + GRID_HALF + "°（" + g.step + "° 網格 " + v.length + " 格）：平均 " + avg + "%，晴（≤ 30%）" +
      clear + " 格（" + Math.round(100 * clear / v.length) + "%）</div>";
  }
  // 雲量計算進度：「雲量計算 45%，請稍待」（雲量區與頂端狀態列同步顯示）
  function progText() {
    var pct = gridProg.total ? Math.floor(100 * gridProg.done / gridProg.total) : 0;
    return "雲量計算 " + pct + "%，請稍待（" + gridStep() + "° 網格 " + gridProg.done + "／" + gridProg.total + " 格）";
  }
  function showProg() {
    var el = $("wx-prog");
    if (el) el.textContent = progText();
    if (gridProg.total && gridProg.done < gridProg.total) status(progText());
    else if (gridProg.total) status("雲量計算完成（" + gridProg.total + " 格）");
  }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function hideNight() { return $("hide-night").checked; }
  function wxOn() { return $("wx-on").checked; }          // 雲量預報預設關閉，勾選才查詢與顯示
  function dayPasses(list) { return list.filter(function (p) { return !(hideNight() && p.night); }); }
  function shown() { return data ? dayPasses(data.passes) : []; }

  function tw(iso, withDate) {
    var d = new Date(Date.parse(iso) + TZ_MS).toISOString();
    return withDate ? d.slice(5, 10) + " " + d.slice(11, 19) : d.slice(11, 19);
  }
  function dur(s) { s = Math.round(s); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  function status(msg) { $("status").textContent = msg; }
  function stationParams() {
    var w = dayWindow(+$("day").value);
    return "lat=" + $("st-lat").value + "&lon=" + $("st-lon").value + "&h_km=" + $("st-h").value +
      "&mask=" + $("mask").value + "&start=" + encodeURIComponent(w.start) + "&hours=" + w.hours.toFixed(4);
  }

  // ── Cesium ────────────────────────────────────────────────────────────────
  Cesium.Ion.defaultAccessToken = "";
  var viewer = new Cesium.Viewer("cesium", {
    baseLayer: new Cesium.ImageryLayer(new Cesium.SingleTileImageryProvider({
      url: "/api/globe_texture/default", rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    })),
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    baseLayerPicker: false, geocoder: false, homeButton: true, sceneModePicker: true,
    navigationHelpButton: false, animation: true, timeline: false, infoBox: true, selectionIndicator: true,
    fullscreenButton: false, sceneMode: Cesium.SceneMode.SCENE2D,      // 預設 2D 地圖（右上角可切換 3D）；不顯示時間軸
  });
  viewer.cesiumWidget.creditContainer.style.display = "none";
  viewer.scene.globe.enableLighting = true;
  var ds = new Cesium.CustomDataSource("mission");
  viewer.dataSources.add(ds);

  // 地面站在 15° 遮罩下對某高度衛星之可接收地面半徑（km）
  function maskRadiusKm(altKm, maskDeg) {
    var e = Cesium.Math.toRadians(maskDeg);
    var lam = Math.acos(RE_KM * Math.cos(e) / (RE_KM + altKm)) - e;
    return RE_KM * lam;
  }

  // 星系各成員只畫「通過地面站可接收圈」的軌道段：每次過頂以 TCA 為中心前後各 1/4 圈（後端 schedule 的 pass.arc），
  // 依時窗與「不顯示夜間過頂」篩選；點選軌道段即選定該衛星與該次過頂。選定的衛星另由 drawPassOrbit() 畫整圈與 30 s 標點。
  function drawOrbits() {
    if (!schedule) return;
    schedule.satellites.forEach(function (s, i) {
      var chosen = s.norad_id === selNorad;
      // 選定的衛星用彩色，其餘灰色
      var col = chosen ? Cesium.Color.fromCssColorString(ORBIT_COLORS[i % ORBIT_COLORS.length]) : Cesium.Color.fromCssColorString("#9aa4b1");
      dayPasses(s.passes || []).forEach(function (ps) {
        if (!ps.arc || ps.arc.length < 2) return;
        var props = { norad: s.norad_id, tca: ps.tca.t };
        var title = s.label + "　" + tw(ps.aos.t, true) + "–" + tw(ps.los.t) + "（台灣）最大仰角 " + ps.max_el.toFixed(1) + "°";
        var seg = [], prev = null;
        function flush() {
          if (seg.length >= 6) ds.entities.add({ name: title + "（點選以選定此次過頂）", properties: props, polyline: {
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(seg), width: chosen ? 3 : 2,
            material: col.withAlpha(chosen ? 0.95 : 0.6) } });
        }
        ps.arc.forEach(function (p) {
          if (prev && Math.abs(p[0] - prev[0]) > 180) { flush(); seg = []; }
          seg.push(p[0], p[1], p[2] * 1000);
          prev = p;
        });
        flush();
        if (chosen) return;
        var tca = ps.tca, a0 = ps.arc[0];
        // TCA 圓點（多顆衛星都集中在地面站附近，不加標籤以免重疊）；名稱與 TCA 時刻標在軌道段起點
        ds.entities.add({ name: title, properties: props, position: Cesium.Cartesian3.fromDegrees(tca.lon, tca.lat, tca.alt_km * 1000),
          point: { pixelSize: 6, color: col, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 } });
        ds.entities.add({ name: title, properties: props, position: Cesium.Cartesian3.fromDegrees(a0[0], a0[1], a0[2] * 1000),
          label: { text: s.label + " " + tw(ps.tca.t).slice(0, 5), font: "12px sans-serif", fillColor: col.withAlpha(0.85),
            showBackground: true, backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6),
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 3.0e7) } });
      });
    });
  }

  // 選定過頂所在的那一圈（以 TCA 為中心前後各半圈，衛星高度）：過頂區間用 5 s 細軌跡、其餘用 30 s 全時窗軌跡，
  // 與 30 s 標點同一時刻、同一高度，兩者完全重合
  function drawPassOrbit(ps, t0ms) {
    var a = RE_KM + (data.satellite.mean_alt_km || 500);
    var half = Math.PI * Math.sqrt(a * a * a / 398600.4418);          // 半個軌道週期（s）
    var aosS = (Date.parse(ps.aos.t) - t0ms) / 1000, losS = (Date.parse(ps.los.t) - t0ms) / 1000;
    var tcaS = (Date.parse(ps.tca.t) - t0ms) / 1000;
    var pts = [];                                                     // [s, lon, lat, alt_km]
    data.ground_track.forEach(function (p) {
      if (p[0] >= tcaS - half && p[0] < aosS) pts.push([p[0], p[1], p[2], p[3]]);
    });
    ps.track.forEach(function (t) { pts.push([aosS + t[0], t[4], t[3], t[5]]); });
    data.ground_track.forEach(function (p) {
      if (p[0] > losS && p[0] <= tcaS + half) pts.push([p[0], p[1], p[2], p[3]]);
    });
    var si = schedule ? schedule.satellites.findIndex(function (s) { return s.norad_id === selNorad; }) : -1;
    var col = Cesium.Color.fromCssColorString(ORBIT_COLORS[(si < 0 ? 0 : si) % ORBIT_COLORS.length]);
    var seg = [], prev = null;
    function flush() {
      if (seg.length >= 6) ds.entities.add({ name: data.satellite.name + "　過頂 #" + (selPass + 1) + " 所在圈次",
        description: "以 TCA " + tw(ps.tca.t, true) + "（台灣）為中心前後各半圈的軌道，與該次過頂的 30 秒標點同一時刻、同一高度。",
        polyline: { positions: Cesium.Cartesian3.fromDegreesArrayHeights(seg), width: 2.5, material: col.withAlpha(0.95) } });
    }
    pts.forEach(function (p) {
      if (prev && Math.abs(p[1] - prev[1]) > 180) { flush(); seg = []; }
      seg.push(p[1], p[2], p[3] * 1000);
      prev = p;
    });
    flush();
  }

  // 地面軌跡兩側 ±GRID_HALF° 的雲量網格（地表，白色、雲越多越不透明）
  function drawCloudGrid(ps) {
    var g = gridClouds[gkey(ps)];
    if (!g) return;
    var h = g.step / 2;
    g.cells.forEach(function (c, i) {
      var v = g.cl[i];
      if (!v) return;
      ds.entities.add({
        name: "雲量 " + Math.round(v.cloud) + "%（" + c.lat + "°, " + c.lon + "°）",
        description: g.step + "° 網格中心 " + c.lat + "°N " + c.lon + "°E<br>衛星經過約 " + tw(new Date(c.t * 1000).toISOString()) +
          "（台灣時間）<br>預報總雲量 " + Math.round(v.cloud) + "%" + (v.step_h > 1 ? "（此時段預報為每 " + v.step_h + " 小時）" : "") +
          "<br>距地面軌跡約 " + c.d.toFixed(1) + "°<br>MET Norway Locationforecast 2.0（CC BY 4.0）" +
          gsdHtml(selNorad, data.satellite.name, ps.tca.alt_km || data.satellite.mean_alt_km, c.d),
        rectangle: { coordinates: Cesium.Rectangle.fromDegrees(c.lon - h, c.lat - h, c.lon + h, c.lat + h),
          material: Cesium.Color.WHITE.withAlpha(cloudAlpha(v.cloud)), height: 0 },
      });
    });
  }

  function stationNow() { return { lat: +$("st-lat").value, lon: +$("st-lon").value, h_km: +$("st-h").value }; }

  function draw() {
    ds.entities.removeAll();
    drawOrbits();
    var st = data ? data.station : stationNow();
    ds.entities.add({
      name: "地面站", position: Cesium.Cartesian3.fromDegrees(st.lon, st.lat, st.h_km * 1000),
      point: { pixelSize: 10, color: Cesium.Color.fromCssColorString("#FFD600"), outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
      label: { text: $("st-preset").selectedOptions[0] ? $("st-preset").selectedOptions[0].text.split("（")[0] : "地面站",
        font: "13px sans-serif", pixelOffset: new Cesium.Cartesian2(0, -18), fillColor: Cesium.Color.YELLOW,
        showBackground: true, backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6) },
    });
    if (!data) {
      var alts = cfg ? cfg.constellations[0].members.map(function (m) { return m.alt_km; }).filter(function (x) { return x > 0; }) : [];
      var altAvg = alts.length ? alts.reduce(function (x, y) { return x + y; }, 0) / alts.length : 550;
      var mk = +$("mask").value, rk = maskRadiusKm(altAvg, mk);
      ds.entities.add({
        name: "仰角 " + mk + "° 可接收範圍（星系平均高度 " + Math.round(altAvg) + " km）",
        position: Cesium.Cartesian3.fromDegrees(st.lon, st.lat),
        ellipse: { semiMajorAxis: rk * 1000, semiMinorAxis: rk * 1000, height: 0,
          material: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.07),
          outline: true, outlineColor: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.8), outlineWidth: 2 },
      });
      setClock(schedule && schedule.start, schedule && schedule.end);
      return;
    }
    var mask = data.mask_deg;
    var start = Cesium.JulianDate.fromIso8601(data.start);
    var stop = Cesium.JulianDate.fromIso8601(data.end);
    var t0ms = Date.parse(data.start);
    var list = shown();

    // 遮罩涵蓋圈
    var rkm = maskRadiusKm(data.satellite.mean_alt_km, mask);
    ds.entities.add({
      name: "仰角 " + mask + "° 可接收範圍（平均高度 " + data.satellite.mean_alt_km + " km）",
      position: Cesium.Cartesian3.fromDegrees(st.lon, st.lat),
      ellipse: { semiMajorAxis: rkm * 1000, semiMinorAxis: rkm * 1000, height: 0,
        material: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.07),
        outline: true, outlineColor: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.8), outlineWidth: 2 },
    });

    // 衛星動態位置（30 s 取樣，Lagrange 內插）
    var pos = new Cesium.SampledPositionProperty();
    pos.setInterpolationOptions({ interpolationDegree: 5, interpolationAlgorithm: Cesium.LagrangePolynomialApproximation });
    data.ground_track.forEach(function (p) {
      pos.addSample(Cesium.JulianDate.addSeconds(start, p[0], new Cesium.JulianDate()),
        Cesium.Cartesian3.fromDegrees(p[1], p[2], p[3] * 1000));
    });
    ds.entities.add({
      name: data.satellite.name, position: pos,
      availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({ start: start, stop: stop })]),
      point: { pixelSize: 11, color: Cesium.Color.fromCssColorString("#58a6ff"), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
      label: { text: data.satellite.name, font: "12px sans-serif", pixelOffset: new Cesium.Cartesian2(0, -16),
        showBackground: true, backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6) },
      path: { leadTime: 0, trailTime: 1800, width: 2, material: Cesium.Color.fromCssColorString("#58a6ff").withAlpha(0.7) },
    });

    // 各次過頂：每 30 s 地面標記點（全部）；選定過頂另畫 3D 弧線、視線與時間標籤
    list.forEach(function (ps, i) {
      var chosen = i === selPass;
      ps.marks.forEach(function (m, k) {
        var last = k === ps.marks.length - 1;
        ds.entities.add({
          name: data.satellite.name + " 過頂 #" + (i + 1) + "　" + tw(m.t, true) + "（台灣）",
          description: "UTC " + m.t + "<br>方位 " + m.az + "°、仰角 " + m.el + "°、斜距 " + m.range_km + " km<br>高度 " + m.alt_km + " km",
          position: Cesium.Cartesian3.fromDegrees(m.lon, m.lat, m.alt_km * 1000),
          point: { pixelSize: chosen ? 8 : 6, color: k === 0 ? Cesium.Color.LIME : last ? Cesium.Color.TOMATO : Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
          label: { text: tw(m.t) + "  " + Math.round(m.el) + "°", font: chosen ? "12px sans-serif" : "11px sans-serif",
            pixelOffset: new Cesium.Cartesian2(10, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
            fillColor: chosen ? Cesium.Color.WHITE : Cesium.Color.fromCssColorString("#c9d1d9"), showBackground: true,
            backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, chosen ? 0.65 : 0.5),
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1.2e7) },
        });
      });
      if (wxOn()) drawCloudGrid(ps);                    // 勾選雲量時：每次過頂都畫兩側雲量網格（已查到者）
      if (chosen) drawPassOrbit(ps, t0ms);
      // 每次過頂都畫可接收弧段（時間線）；選定者較粗
      var arc = [];
      ps.track.forEach(function (t) { arc.push(t[4], t[3], t[5] * 1000); });
      ds.entities.add({ polyline: { positions: Cesium.Cartesian3.fromDegreesArrayHeights(arc), width: chosen ? 4 : 3,
        material: new Cesium.PolylineGlowMaterialProperty({ color: Cesium.Color.fromCssColorString("#3fb950"), glowPower: chosen ? 0.25 : 0.15 }) } });
    });

    setClock(data.start, data.end);
  }

  function setClock(a, b) {
    if (!a || !b) return;
    var start = Cesium.JulianDate.fromIso8601(a), stop = Cesium.JulianDate.fromIso8601(b);
    var c = viewer.clock;
    c.startTime = start.clone(); c.stopTime = stop.clone();
    c.clockRange = Cesium.ClockRange.CLAMPED;
    if (Cesium.JulianDate.lessThan(c.currentTime, start) || Cesium.JulianDate.greaterThan(c.currentTime, stop)) c.currentTime = start.clone();
    c.multiplier = 30; c.shouldAnimate = true;
    if (viewer.timeline) viewer.timeline.zoomTo(start, stop);
  }

  // 滑鼠點選地圖中的軌道段（或 TCA 點）→ 選定該顆衛星與該次過頂
  new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas).setInputAction(function (ev) {
    var hits = viewer.scene.drillPick(ev.position, 5);
    for (var i = 0; i < hits.length; i++) {
      var e = hits[i].id;
      var n = e && e.properties && e.properties.norad && e.properties.norad.getValue();
      if (n) { pickSat(n, e.properties.tca ? e.properties.tca.getValue() : null); return; }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  var wantTca = null;                                   // 點選軌道段時指定的過頂（TCA 時刻），過頂清單載入後選定
  function pickSat(n, tca) {
    if (n === selNorad) {
      if (tca && data) { var k = passIndexByTca(tca); if (k >= 0 && k !== selPass) selectPass(k); }
      return;
    }
    wantTca = tca || null;
    selNorad = n; selPass = -1; data = null; tcaCloud = {}; trackCloud = null; gridClouds = {}; gridBusy = {};
    renderSats(); renderPasses(); renderWx(); loadPasses();
  }
  function passIndexByTca(tca) {
    var t = Date.parse(tca);
    return shown().findIndex(function (p) { return Math.abs(Date.parse(p.tca.t) - t) < 60000; });
  }

  // ── 天球圖（方位／仰角極座標；r = 90° − 仰角）────────────────────────────────
  function sky() {
    var svg = $("sky");
    var mask = +$("mask").value;
    var R = function (el) { return 100 * (90 - el) / 90; };
    var xy = function (az, el) { var a = az * Math.PI / 180, r = R(el); return [r * Math.sin(a), -r * Math.cos(a)]; };
    var h = ['<rect x="-120" y="-120" width="240" height="240" fill="#0d1117"/>'];
    [0, 30, 60].forEach(function (e) { h.push('<circle r="' + R(e) + '" fill="none" stroke="#30363d"/>'); });
    h.push('<circle r="' + R(mask) + '" fill="none" stroke="#f2a73b" stroke-dasharray="4 3"/>');
    h.push('<text x="' + (R(mask) * 0.72 + 2) + '" y="' + (-R(mask) * 0.72) + '" fill="#f2a73b" font-size="8">' + mask + '°</text>');
    h.push('<line x1="-100" y1="0" x2="100" y2="0" stroke="#21262d"/><line x1="0" y1="-100" x2="0" y2="100" stroke="#21262d"/>');
    [["N", 0, -108], ["E", 108, 3], ["S", 0, 114], ["W", -108, 3]].forEach(function (d) {
      h.push('<text x="' + d[1] + '" y="' + d[2] + '" fill="#8b949e" font-size="10" text-anchor="middle">' + d[0] + "</text>");
    });
    // 同一顆衛星的其他過頂：灰色虛線，起點（AOS）與終點（LOS）標時間與序號
    shown().forEach(function (op, j) {
      if (j === selPass) return;
      var opts = op.track.map(function (t) { return xy(t[1], t[2]).map(function (v) { return v.toFixed(1); }).join(","); }).join(" ");
      h.push('<polyline points="' + opts + '" fill="none" stroke="#8b949e" stroke-width="1.6" stroke-dasharray="4 2"/>');
      var a0 = xy(op.aos.az, op.aos.el), a1 = xy(op.los.az, op.los.el);
      h.push('<circle cx="' + a0[0].toFixed(1) + '" cy="' + a0[1].toFixed(1) + '" r="2" fill="#8b949e"/>');
      h.push('<text x="' + (a0[0] + 4).toFixed(1) + '" y="' + (a0[1] - 3).toFixed(1) + '" fill="#8b949e" font-size="6.5">#' + (j + 1) + " " + tw(op.aos.t) + "</text>");
      h.push('<text x="' + (a1[0] + 4).toFixed(1) + '" y="' + (a1[1] + 7).toFixed(1) + '" fill="#8b949e" font-size="6.5">' + tw(op.los.t) + "</text>");
      var tt = xy(op.tca.az, op.tca.el);
      h.push('<text x="' + tt[0].toFixed(1) + '" y="' + (tt[1] + 3).toFixed(1) + '" fill="#8b949e" font-size="8" text-anchor="middle">☆</text>');
    });
    var ps = shown()[selPass];
    if (ps) {
      var pts = ps.track.map(function (t) { return xy(t[1], t[2]).map(function (v) { return v.toFixed(1); }).join(","); }).join(" ");
      h.push('<polyline points="' + pts + '" fill="none" stroke="#3fb950" stroke-width="2"/>');
      ps.marks.forEach(function (m, k) {
        var p = xy(m.az, m.el), last = k === ps.marks.length - 1;
        var col = k === 0 ? "#7ee787" : last ? "#ff7b72" : "#e6edf3";
        h.push('<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="2.4" fill="' + col + '"/>');
        if (k % 2 === 0 || last) {
          h.push('<text x="' + (p[0] + 4).toFixed(1) + '" y="' + (p[1] - 3).toFixed(1) + '" fill="' + col + '" font-size="6.5">' + tw(m.t) + "</text>");
        }
      });
      var t = xy(ps.tca.az, ps.tca.el);
      h.push('<text x="' + t[0].toFixed(1) + '" y="' + (t[1] + 3).toFixed(1) + '" fill="#FFD600" font-size="10" text-anchor="middle">★</text>');
      status("過頂 #" + (selPass + 1) + "：AOS " + tw(ps.aos.t, true) + "，TCA " + tw(ps.tca.t) + "（" + ps.max_el + "°），LOS " + tw(ps.los.t) +
        "；30 秒標點 " + ps.marks.length + " 個（天球圖每 60 秒標註時間，地圖每 30 秒標註）");
    } else {
      h.push('<text x="0" y="4" fill="#8b949e" font-size="9" text-anchor="middle">' + (selNorad ? "點選過頂清單以顯示軌跡" : "先用滑鼠點選軌道") + "</text>");
    }
    svg.innerHTML = h.join("");
  }

  // ── UI ───────────────────────────────────────────────────────────────────
  function renderSats() {
    var con = cfg.constellations[0];
    $("con-title").textContent = con.name + "（單選）";
    $("con-note").textContent = con.note;
    var next = {};
    if (schedule) schedule.satellites.forEach(function (s) { next[s.norad_id] = dayPasses(s.passes); });
    $("sats").innerHTML = con.members.map(function (m) {
      var ps = next[m.norad_id] || [];
      var nx = !m.in_index ? "索引無此衛星" : ps.length ? ps.length + " 次・第一次 " + tw(ps[0].aos.t) + "（" + ps[0].max_el + "°）" : (schedule ? (hideNight() ? "時窗內無白天過頂" : "時窗內無過頂") : "");
      return '<label class="' + (m.in_index ? "" : "off") + '"><input type="radio" name="sat" value="' + m.norad_id + '"' +
        (m.in_index ? "" : " disabled") + (m.norad_id === selNorad ? " checked" : "") + ">" +
        "<span>" + m.label + ' <span class="hint">' + m.norad_id + (m.alt_km ? "・" + Math.round(m.alt_km) + " km" : "") + "</span></span>" +
        '<span class="nx">' + nx + "</span></label>";
    }).join("");
    document.querySelectorAll('input[name="sat"]').forEach(function (r) {
      r.onchange = function () { pickSat(+r.value); };
    });
  }

  function cloudCell(p) {
    var c = tcaCloud[p.tca.t];
    if (!c && !wxOn()) return '<td class="cl" title="勾選「計算並顯示雲量預報」後顯示">—</td>';
    if (!c) return '<td class="cl" title="' + (!inWx(Date.parse(p.tca.t)) ? "超出 " + WX_DAYS + " 天預報範圍" : wxErr || "查詢中或沒有預報") + '">—</td>';
    return '<td class="cl" title="TCA ' + tw(p.tca.t) + " " + cloudTip(c) + '">' + Math.round(c.cloud) + "%</td>";
  }

  function renderPasses() {
    var list = shown(), nNight = data ? data.passes.length - list.length : 0;
    $("sel-name").textContent = data ? data.satellite.name + "（" + list.length + " 次" + (nNight ? "，夜間 " + nNight + " 次未顯示" : "") + "）" : "";
    if (!selNorad || !data) {
      $("passes").innerHTML = '<tr><td colspan="7" class="empty">' + (selNorad ? "計算中…" : "尚未選擇軌道：請用滑鼠點選地圖中的軌道（或上方衛星）。") + "</td></tr>";
      return;
    }
    if (!list.length) {
      $("passes").innerHTML = '<tr><td colspan="7" class="empty">' + dayLabel(+$("day").value).replace("　現在到午夜", "") + " " +
        (nNight ? "沒有白天過頂（夜間 " + nNight + " 次未顯示，取消勾選「不顯示夜間過頂」可查看）。" : "沒有仰角 ≥ " + data.mask_deg + "° 的過頂。") + "</td></tr>";
      return;
    }
    $("passes").innerHTML = list.map(function (p, i) {
      return '<tr class="ps' + (i === selPass ? " sel" : "") + '" data-i="' + i + '"><td>' + (i + 1) + "</td><td title=\"UTC " + p.aos.t + "\">" +
        tw(p.aos.t, true) + (p.clipped_start ? "*" : "") + "</td><td>" + tw(p.los.t) + (p.clipped_end ? "*" : "") + "</td><td>" + dur(p.duration_s) +
        "</td><td>" + p.max_el.toFixed(1) + "°</td><td>" + Math.round(p.aos.az) + "°→" + Math.round(p.los.az) + "°</td>" + cloudCell(p) + "</tr>";
    }).join("");
    document.querySelectorAll("tr.ps").forEach(function (tr) {
      tr.onclick = function () { selectPass(+tr.dataset.i); };
    });
  }

  // 選定第 i 次過頂：重畫、時鐘跳到 AOS 前 1 分鐘、鏡頭飛到地面站
  function selectPass(i) {
    selPass = i; renderPasses(); draw(); sky(); loadTrackClouds(); loadGridClouds();
    var p = shown()[selPass];
    viewer.clock.currentTime = Cesium.JulianDate.addSeconds(Cesium.JulianDate.fromIso8601(p.aos.t), -60, new Cesium.JulianDate());
    viewer.clock.multiplier = 10;
    if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {      // 2D：以地面站為中心俯視
      viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(data.station.lon, data.station.lat, 7.0e6), duration: 1.5 });
    } else {
      viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(data.station.lon, data.station.lat - 14, 2.6e6),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 }, duration: 1.5 });
    }
  }

  function loadPasses() {
    if (!selNorad) { data = null; renderPasses(); draw(); sky(); return; }
    status("計算中…");
    var want = selNorad;
    fetch("/api/mission/passes?norad=" + selNorad + "&" + stationParams()).then(function (r) { return r.json(); }).then(function (d) {
      if (want !== selNorad) return;                     // 期間又點了別條軌道
      if (d.error) { status(d.error); return; }
      data = d;
      selPass = shown().length ? 0 : -1;
      var k = wantTca ? passIndexByTca(wantTca) : -1;
      wantTca = null;
      if (k >= 0) selPass = k;
      renderPasses(); draw(); sky(); loadTcaClouds(); loadTrackClouds(); loadGridClouds();
      var nN = d.passes.filter(function (p) { return p.night; }).length;
      status(d.satellite.name + "：" + dayLabel(+$("day").value) + " 過頂 " + d.passes.length + " 次（仰角 ≥ " + d.mask_deg + "°，其中夜間 " + nN +
        " 次），TLE 曆元 " + d.satellite.tle_epoch.slice(0, 16) + " UTC，計算 " + d.elapsed_sec + " s");
    }).catch(function (e) { status("過頂計算失敗：" + e); });
  }

  function run() {
    $("badge-mask").textContent = "仰角 ≥ " + $("mask").value + "°";
    fetch("/api/mission/schedule?constellation=" + cfg.constellations[0].id + "&" + stationParams())
      .then(function (r) { return r.json(); }).then(function (s) { schedule = s; renderSats(); if (!data) draw(); })
      .catch(function () { /* 總覽失敗不影響單顆 */ });
    loadPasses();
  }

  fetch("/api/mission/config").then(function (r) { return r.json(); }).then(function (c) {
    cfg = c;
    $("st-preset").innerHTML = c.stations.map(function (s) { return '<option value="' + s.id + '">' + s.name + "</option>"; }).join("");
    function applyStation() {
      var s = c.stations.find(function (x) { return x.id === $("st-preset").value; });
      $("st-lat").value = s.lat; $("st-lon").value = s.lon; $("st-h").value = s.h_km; $("st-note").textContent = s.note;
    }
    $("st-preset").onchange = function () { applyStation(); run(); };
    applyStation();
    $("mask").value = c.default_mask_deg;
    selNorad = null;                                     // 不預選：用滑鼠點選軌道後才顯示過頂清單
    $("day").innerHTML = [0, 1, 2, 3, 4, 5, 6, 7].map(function (k) {
      return '<option value="' + k + '"' + (k === 1 ? " selected" : "") + ">" + dayLabel(k) + "</option>";
    }).join("");
    renderSats(); renderPasses(); sky();
    $("btn-run").onclick = run;
    $("day").onchange = function () { data = null; selPass = -1; renderPasses(); renderWx(); run(); };
    renderWx();
    $("wx-grid").onchange = function () { renderWx(); draw(); loadGridClouds(); };
    $("wx-on").onchange = function () { renderWx(); renderPasses(); draw(); loadTcaClouds(); loadTrackClouds(); loadGridClouds(); };
    $("hide-night").onchange = function () { selPass = shown().length ? 0 : -1; renderSats(); renderPasses(); draw(); sky(); loadTrackClouds(); loadGridClouds(); };
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121.0, 20.0, 2.2e7) });   // 2D：以台灣為中心、涵蓋各衛星整圈軌道便於點選
    run();
  });
})();
