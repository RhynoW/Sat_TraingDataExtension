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
  var WX_DAYS = 3, tcaCloud = {}, trackCloud = null, gridCloud = null, gridBusy = false, wxMeta = null, wxErr = null;
  var GRID_HALF = 5, GRID_MAX = 400;          // 地面軌跡左右各 5°，1° 網格

  // 選定過頂的地面軌跡兩側 ±5° 內的 1° 網格格點（格點中心為整數度），每格記錄衛星最接近時的時刻
  function bandCells(ps) {
    var t0 = Date.parse(ps.aos.t) / 1000, tr = ps.track, best = {};
    for (var i = 0; i < tr.length; i++) {
      var a = tr[i], b = tr[i + 1] || tr[i - 1];
      if (!b) break;
      var lat = a[3], lon = a[4], cl = Math.cos(lat * Math.PI / 180);
      var dlon = ((b[4] - lon + 540) % 360) - 180, de = dlon * cl, dn = b[3] - lat;
      if (!tr[i + 1]) { de = -de; dn = -dn; }
      var n = Math.hypot(de, dn) || 1, pe = dn / n, pn = -de / n;      // 垂直於軌跡的單位向量（東、北）
      for (var k = -GRID_HALF; k <= GRID_HALF; k += 0.5) {
        var la = Math.round(lat + k * pn), lo = Math.round(lon + k * pe / Math.max(cl, 0.05));
        if (la < -89 || la > 89) continue;
        lo = ((lo + 540) % 360) - 180;
        var key = la + "," + lo, d = Math.abs(k);
        if (!best[key] || d < best[key].d) best[key] = { lat: la, lon: lo, t: Math.round(t0 + a[0]), d: d };
      }
    }
    return Object.keys(best).map(function (k) { return best[k]; })
      .sort(function (x, y) { return x.d - y.d; }).slice(0, GRID_MAX);
  }
  function loadGridClouds() {
    gridCloud = null;
    var ps = shown()[selPass];
    if (!ps || !inWx(Date.parse(ps.tca.t))) return;
    var cells = bandCells(ps), key = ps.aos.t;
    gridBusy = true; renderWx();
    var q = cells.map(function (c) { return c.t + "," + c.lat + "," + c.lon; }).join(";");
    fetch("/api/mission/cloud_track?grid=1&pts=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
      gridBusy = false;
      var cur = shown()[selPass];
      if (!cur || cur.aos.t !== key) return;
      if (d.error) { wxErr = d.error; renderWx(); return; }
      gridCloud = { key: key, cells: cells, cl: d.points };
      renderWx(); draw();
    }).catch(function (e) { gridBusy = false; wxErr = String(e.message || e); renderWx(); });
  }
  function inWx(ms) { return ms <= Date.now() + WX_DAYS * DAY_MS; }
  function cloudColor(p) { return p == null ? "#30363d" : p <= 30 ? "#3fb950" : p <= 70 ? "#d29922" : "#f85149"; }
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
    if (!selNorad || !ps) { box.innerHTML = '<div class="hint">點選軌道與過頂後，顯示衛星正下方（星下點）的預報雲量。</div>'; return; }
    if (!inWx(Date.parse(ps.tca.t))) { box.innerHTML = '<div class="hint">雲量預報只提供未來 ' + WX_DAYS + " 天。</div>"; return; }
    if (msg) { box.innerHTML = '<div class="hint">' + msg + "</div>"; return; }
    if (wxErr && !trackCloud) { box.innerHTML = '<div class="hint">' + wxErr + "</div>"; return; }
    if (!trackCloud || trackCloud.key !== ps.aos.t) { box.innerHTML = ""; return; }
    var cells = trackCloud.pts.map(function (m, i) {
      var c = trackCloud.cl[i];
      return '<i style="background:' + cloudColor(c && c.cloud) + '" title="' + tw(m.t) + "（仰角 " + Math.round(m.el) + "°）" + (c ? cloudTip(c) : "無預報") + '"></i>';
    });
    var vals = trackCloud.cl.filter(Boolean).map(function (c) { return c.cloud; });
    var avg = vals.length ? Math.round(vals.reduce(function (a, b) { return a + b; }, 0) / vals.length) : null;
    var p0 = trackCloud.pts[0], p1 = trackCloud.pts[trackCloud.pts.length - 1];
    box.innerHTML = '<div class="hint">' + esc(data.satellite.name) + " 過頂 #" + (selPass + 1) + " 衛星正下方雲量（星下點，每 60 秒）" +
      (avg != null ? "・平均 " + avg + "%" : "") + "・" + wxMeta.source + (wxMeta.stale ? "・離線，顯示上次的預報" : "") +
      (wxMeta.updated_at ? "・更新 " + tw(wxMeta.updated_at, true).slice(0, 11) : "") + "</div>" +
      '<div class="bar">' + cells.join("") + '</div><div class="ax"><span>' + tw(p0.t) + "（AOS）</span><span>" + tw(p1.t) + "（LOS）</span></div>" +
      gridLine(ps) +
      '<div class="hint">綠 ≤ 30%、黃 ≤ 70%、紅 > 70%。色條為星下點（0.1° 格點）；3D 地面上的方格為地面軌跡左右各 ' + GRID_HALF +
      '° 內的 1° 網格，每格取衛星經過時刻的預報。光學影像要看這裡的雲；X 波段下行主要受降雨影響。</div>';
  }
  function gridLine(ps) {
    if (gridBusy) return '<div class="hint">查詢地面軌跡兩側 1° 網格雲量…（第一次約需 10～20 秒）</div>';
    if (!gridCloud || gridCloud.key !== ps.aos.t) return "";
    var v = gridCloud.cl.filter(Boolean).map(function (c) { return c.cloud; });
    if (!v.length) return '<div class="hint">地面軌跡兩側網格沒有預報資料</div>';
    var clear = v.filter(function (x) { return x <= 30; }).length;
    var avg = Math.round(v.reduce(function (a, b) { return a + b; }, 0) / v.length);
    return '<div class="hint">地面軌跡左右各 ' + GRID_HALF + "°（1° 網格 " + v.length + " 格）：平均 " + avg + "%，晴（≤ 30%）" +
      clear + " 格（" + Math.round(100 * clear / v.length) + "%）</div>";
  }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function hideNight() { return $("hide-night").checked; }
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
    navigationHelpButton: false, animation: true, timeline: true, infoBox: true, selectionIndicator: true,
    fullscreenButton: false,
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

  // 星系各成員自時窗起點一圈的軌道（可用滑鼠點選；選定的那顆另畫完整地面軌跡）
  function drawOrbits() {
    if (!schedule) return;
    schedule.satellites.forEach(function (s, i) {
      if (!s.orbit || s.orbit.length < 2) return;
      var chosen = s.norad_id === selNorad;
      var col = Cesium.Color.fromCssColorString(ORBIT_COLORS[i % ORBIT_COLORS.length]);
      var seg = [], prev = null;
      var props = { norad: s.norad_id };
      function flush() {
        if (seg.length >= 6) ds.entities.add({ name: s.label + "（點選以顯示過頂清單）", properties: props, polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(seg), width: chosen ? 2 : 3,
          material: col.withAlpha(chosen ? 0.35 : 0.85) } });
      }
      s.orbit.forEach(function (p) {
        if (prev && Math.abs(p[0] - prev[0]) > 180) { flush(); seg = []; }
        seg.push(p[0], p[1], p[2] * 1000);
        prev = p;
      });
      flush();
      var p0 = s.orbit[0];
      ds.entities.add({ name: s.label, properties: props, position: Cesium.Cartesian3.fromDegrees(p0[0], p0[1], p0[2] * 1000),
        point: { pixelSize: 7, color: col, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
        label: chosen ? undefined : { text: s.label, font: "12px sans-serif", fillColor: col, pixelOffset: new Cesium.Cartesian2(0, -12),
          showBackground: true, backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.6),
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 3.0e7) } });
    });
  }

  // 地面軌跡兩側 ±5° 的 1° 雲量網格（地表，半透明）
  function drawCloudGrid(ps) {
    if (!gridCloud || gridCloud.key !== ps.aos.t) return;
    gridCloud.cells.forEach(function (c, i) {
      var v = gridCloud.cl[i];
      if (!v) return;
      ds.entities.add({
        name: "雲量 " + Math.round(v.cloud) + "%（" + c.lat + "°, " + c.lon + "°）",
        description: "1° 網格中心 " + c.lat + "°N " + c.lon + "°E<br>衛星經過約 " + tw(new Date(c.t * 1000).toISOString()) +
          "（台灣時間）<br>預報總雲量 " + Math.round(v.cloud) + "%" + (v.step_h > 1 ? "（此時段預報為每 " + v.step_h + " 小時）" : "") +
          "<br>距地面軌跡約 " + c.d.toFixed(1) + "°<br>MET Norway Locationforecast 2.0（CC BY 4.0）",
        rectangle: { coordinates: Cesium.Rectangle.fromDegrees(c.lon - 0.5, c.lat - 0.5, c.lon + 0.5, c.lat + 0.5),
          material: Cesium.Color.fromCssColorString(cloudColor(v.cloud)).withAlpha(0.42), height: 0 },
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
    if (!data) { setClock(schedule && schedule.start, schedule && schedule.end); return; }
    var mask = data.mask_deg;
    var start = Cesium.JulianDate.fromIso8601(data.start);
    var stop = Cesium.JulianDate.fromIso8601(data.end);
    var t0ms = Date.parse(data.start);
    var list = shown();
    var spans = list.map(function (p) { return [(Date.parse(p.aos.t) - t0ms) / 1000 - 15, (Date.parse(p.los.t) - t0ms) / 1000 + 15]; });
    function inShown(t) { return spans.some(function (w) { return t >= w[0] && t <= w[1]; }); }

    // 遮罩涵蓋圈
    var rkm = maskRadiusKm(data.satellite.mean_alt_km, mask);
    ds.entities.add({
      name: "仰角 " + mask + "° 可接收範圍（平均高度 " + data.satellite.mean_alt_km + " km）",
      position: Cesium.Cartesian3.fromDegrees(st.lon, st.lat),
      ellipse: { semiMajorAxis: rkm * 1000, semiMinorAxis: rkm * 1000, height: 0,
        material: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.07),
        outline: true, outlineColor: Cesium.Color.fromCssColorString("#FFD600").withAlpha(0.8), outlineWidth: 2 },
    });

    // 地面軌跡：可接收段（仰角 ≥ 遮罩，且是清單中顯示的過頂；夜間過頂隱藏時不高亮）高亮、其餘灰色；跨換日線處斷開
    var seg = [], segVis = null, prev = null;
    function flush() {
      if (seg.length >= 4) {
        ds.entities.add({ polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(seg), arcType: Cesium.ArcType.GEODESIC,
          width: segVis ? 3.5 : 1.2,
          material: segVis ? Cesium.Color.fromCssColorString("#3fb950") : Cesium.Color.fromCssColorString("#8b949e").withAlpha(0.55),
        } });
      }
    }
    data.ground_track.forEach(function (p) {
      var lon = p[1], lat = p[2], vis = p[4] && inShown(p[0]);
      var jump = prev && Math.abs(lon - prev[0]) > 180;           // 跨換日線：斷開
      if (prev && (jump || vis !== segVis)) {
        flush();
        seg = jump ? [] : [prev[0], prev[1]];                        // 可見性改變：新段由前一點接續
      }
      segVis = vis;
      seg.push(lon, lat);
      prev = [lon, lat];
    });
    flush();

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
          position: Cesium.Cartesian3.fromDegrees(m.lon, m.lat, chosen ? m.alt_km * 1000 : 0),
          point: { pixelSize: chosen ? 8 : 5, color: k === 0 ? Cesium.Color.LIME : last ? Cesium.Color.TOMATO : Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
          label: chosen ? { text: tw(m.t) + "  " + Math.round(m.el) + "°", font: "12px sans-serif",
            pixelOffset: new Cesium.Cartesian2(10, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
            fillColor: Cesium.Color.WHITE, showBackground: true, backgroundColor: Cesium.Color.fromAlpha(Cesium.Color.BLACK, 0.65),
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1.2e7) } : undefined,
        });
      });
      if (chosen) drawCloudGrid(ps);
      if (chosen) {
        var arc = [];
        ps.track.forEach(function (t) { arc.push(t[4], t[3], t[5] * 1000); });
        ds.entities.add({ polyline: { positions: Cesium.Cartesian3.fromDegreesArrayHeights(arc), width: 4,
          material: new Cesium.PolylineGlowMaterialProperty({ color: Cesium.Color.fromCssColorString("#3fb950"), glowPower: 0.25 }) } });
      }
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
    viewer.timeline.zoomTo(start, stop);
  }

  // 滑鼠點選 3D 中的軌道（或軌道起點的衛星）→ 選定該顆衛星
  new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas).setInputAction(function (ev) {
    var hits = viewer.scene.drillPick(ev.position, 5);
    for (var i = 0; i < hits.length; i++) {
      var e = hits[i].id;
      var n = e && e.properties && e.properties.norad && e.properties.norad.getValue();
      if (n) { pickSat(n); return; }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  function pickSat(n) {
    if (n === selNorad) return;
    selNorad = n; selPass = -1; data = null; tcaCloud = {}; trackCloud = null; gridCloud = null;
    renderSats(); renderPasses(); renderWx(); loadPasses();
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
        "；30 秒標點 " + ps.marks.length + " 個（天球圖每 60 秒標註時間，3D 每 30 秒標註）");
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
    if (!c) return '<td class="cl" title="' + (!inWx(Date.parse(p.tca.t)) ? "超出 " + WX_DAYS + " 天預報範圍" : wxErr || "查詢中或沒有預報") + '">—</td>';
    return '<td class="cl" style="color:' + cloudColor(c.cloud) + '" title="TCA ' + tw(p.tca.t) + " " + cloudTip(c) + '">' + Math.round(c.cloud) + "%</td>";
  }

  function renderPasses() {
    var list = shown(), nNight = data ? data.passes.length - list.length : 0;
    $("sel-name").textContent = data ? data.satellite.name + "（" + list.length + " 次" + (nNight ? "，夜間 " + nNight + " 次未顯示" : "") + "）" : "";
    if (!selNorad || !data) {
      $("passes").innerHTML = '<tr><td colspan="7" class="empty">' + (selNorad ? "計算中…" : "尚未選擇軌道：請用滑鼠點選 3D 中的軌道（或上方衛星）。") + "</td></tr>";
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
      tr.onclick = function () {
        selPass = +tr.dataset.i; renderPasses(); draw(); sky(); loadTrackClouds(); loadGridClouds();
        var p = shown()[selPass];
        viewer.clock.currentTime = Cesium.JulianDate.addSeconds(Cesium.JulianDate.fromIso8601(p.aos.t), -60, new Cesium.JulianDate());
        viewer.clock.multiplier = 10;
        viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(data.station.lon, data.station.lat - 14, 2.6e6),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 }, duration: 1.5 });
      };
    });
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
    $("hide-night").onchange = function () { selPass = shown().length ? 0 : -1; renderSats(); renderPasses(); draw(); sky(); loadTrackClouds(); loadGridClouds(); };
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121.0, 23.7, 9.0e6) });   // 台灣正上方俯視
    run();
  });
})();
