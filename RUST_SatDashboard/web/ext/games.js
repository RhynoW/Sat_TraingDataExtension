/* 太空小遊戲（Rust 單機版 /games）— 第一個遊戲：月球模擬
 * - 月球星曆、月相、天平動、月出月沒、月相時刻、月食、近遠地點：astronomy-engine JS 版（Don Cross，MIT）
 * - 3D：自繪月球（NASA LRO 月面影像），位置來自 astronomy-engine（不用 Cesium 內建的低精度月球），
 *   姿態以 IAU 月球自轉軸＋光學天平動近似；可切換慣性座標視角（星空不動、看月球軌道）
 * - 射月球：地球、月球、太陽點質量重力，RK4 變步長積分（月球／太陽位置先算每小時表，再以 4 點 Lagrange 內插）
 * 座標：astronomy-engine 的 EQJ（J2000 平赤道）視為 ICRF，畫到 Cesium 時乘上 ICRF→地固旋轉。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var AU_KM = 149597870.7, RE = 6378.137, RM = 1737.4;
  var MU_E = 398600.4418, MU_M = 4902.800066, MU_S = 1.32712440018e11;
  var TW = 8 * 3600e3;
  var OBS = new Astronomy.Observer(25.0330, 121.5654, 10);   // 台北
  var C3 = Cesium.Cartesian3, M3 = Cesium.Matrix3, JD = Cesium.JulianDate;
  var D2R = Math.PI / 180, R2D = 180 / Math.PI;

  function pad(n) { return String(n).padStart(2, "0"); }
  function tw(d, sec) {
    var t = new Date(d.getTime() + TW);
    return t.getUTCFullYear() + "-" + pad(t.getUTCMonth() + 1) + "-" + pad(t.getUTCDate()) + " " +
      pad(t.getUTCHours()) + ":" + pad(t.getUTCMinutes()) + (sec ? ":" + pad(t.getUTCSeconds()) : "");
  }
  function fmt(x, n) { return Number(x).toLocaleString("zh-TW", { maximumFractionDigits: n || 0, minimumFractionDigits: n || 0 }); }
  function norm(a) { return Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]); }
  function unit(a) { var n = norm(a); return [a[0] / n, a[1] / n, a[2] / n]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function sph(latDeg, lonDeg) { var la = latDeg * D2R, lo = lonDeg * D2R; return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)]; }
  function wrap180(x) { x = ((x + 180) % 360 + 360) % 360 - 180; return x; }

  // ── Cesium ──────────────────────────────────────────────────────────────
  var viewer = new Cesium.Viewer("cesium", {
    baseLayer: new Cesium.ImageryLayer(new Cesium.SingleTileImageryProvider({
      url: "/api/globe_texture/default", rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    })),
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
    navigationHelpButton: false, animation: false, timeline: true, infoBox: false, selectionIndicator: false,
    fullscreenButton: false,
  });
  viewer.cesiumWidget.creditContainer.style.display = "none";
  var scene = viewer.scene;
  scene.globe.enableLighting = true;
  if (scene.moon) scene.moon.show = false;            // 改用自繪月球（位置精度較高、可貼高解析影像）
  viewer.camera.frustum.far = 1e11;
  scene.screenSpaceCameraController.maximumZoomDistance = 4e9;
  var clock = viewer.clock;
  clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
  clock.clockRange = Cesium.ClockRange.UNBOUNDED;
  clock.currentTime = JD.now();
  clock.multiplier = 3600;
  clock.shouldAnimate = true;
  function zoomTimeline(center, days) {
    viewer.timeline.zoomTo(JD.addDays(center, -days, new JD()), JD.addDays(center, days, new JD()));
  }
  zoomTimeline(clock.currentTime, 15);

  // ICRF→地固；沒有預載 IAU2006 XYS 資料時退回 TEME 近似（差異約 0.3°，畫面看不出來）
  function icrf(jd, res) {
    return Cesium.Transforms.computeIcrfToFixedMatrix(jd, res) || Cesium.Transforms.computeTemeToPseudoFixedMatrix(jd, res);
  }
  function preload(center) {
    var iv = new Cesium.TimeInterval({ start: JD.addDays(center, -40, new JD()), stop: JD.addDays(center, 40, new JD()) });
    Cesium.Transforms.preloadIcrfFixed(iv).catch(function () {});
  }
  preload(clock.currentTime);
  var _mFix = new M3();
  function toFixed(vKm, M, res) {
    var c = res || new C3();
    c.x = vKm[0] * 1000; c.y = vKm[1] * 1000; c.z = vKm[2] * 1000;
    return M3.multiplyByVector(M, c, c);
  }

  // ── 月球狀態（每個時刻快取）───────────────────────────────────────────────
  var POLE = sph(66.5392, 269.9949);                  // IAU 月球北極（J2000 赤道座標，略去小週期項）
  var mc = { key: NaN };
  function moonAt(jd) {
    var key = jd.dayNumber * 86400 + jd.secondsOfDay;
    if (key === mc.key) return mc;
    var d = JD.toDate(jd);
    var g = Astronomy.GeoMoon(d);
    var r = [g.x * AU_KM, g.y * AU_KM, g.z * AU_KM];
    var lib = Astronomy.Libration(d);
    // 月固座標 → EQJ：z 軸＝月球北極；地球方向在月固座標的經度＝天平動 elon
    var z = POLE, dIn = unit([-r[0], -r[1], -r[2]]);
    var p = unit(sub(dIn, [z[0] * dot(dIn, z), z[1] * dot(dIn, z), z[2] * dot(dIn, z)]));
    var zp = cross(z, p), ce = Math.cos(lib.elon * D2R), se = Math.sin(lib.elon * D2R);
    var x = [ce * p[0] - se * zp[0], ce * p[1] - se * zp[1], ce * p[2] - se * zp[2]];
    var y = cross(z, x);
    var M = icrf(jd, new M3());
    var Rm = new M3(x[0], y[0], z[0], x[1], y[1], z[1], x[2], y[2], z[2]);
    var Rf = M3.multiply(M, Rm, new M3());
    mc = { key: key, r: r, lib: lib, M: M, Rf: Rf, pos: toFixed(r, M), q: Cesium.Quaternion.fromRotationMatrix(Rf) };
    return mc;
  }

  var moonEnt = viewer.entities.add({
    name: "月球",
    viewFrom: new C3(-5.5e6, -5.5e6, 2.5e6),            // 「飛到月球」時相機相對月心的位置（東北天座標，公尺）
    position: new Cesium.CallbackProperty(function (t, res) { return C3.clone(moonAt(t).pos, res); }, false),
    point: { pixelSize: 6, color: Cesium.Color.LIGHTGRAY, distanceDisplayCondition: new Cesium.DistanceDisplayCondition(6e7, 1e12) },
    label: {
      text: "月球", font: "13px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.WHITE,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
      pixelOffset: new Cesium.Cartesian2(0, -16), distanceDisplayCondition: new Cesium.DistanceDisplayCondition(3e7, 1e12),
    },
  });

  // 月球本體用 Primitive（Entity 的位置與姿態每幀變動時會不斷重建幾何，貼圖來不及載入而顯示純白）；
  // 每幀只更新 modelMatrix＝月固→地固旋轉＋月心位置
  var moonPrim = scene.primitives.add(new Cesium.Primitive({
    geometryInstances: new Cesium.GeometryInstance({
      geometry: new Cesium.EllipsoidGeometry({
        radii: new C3(RM * 1000, RM * 1000, RM * 1000), slicePartitions: 128, stackPartitions: 64,
        vertexFormat: Cesium.MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat,
      }),
    }),
    appearance: new Cesium.MaterialAppearance({
      material: Cesium.Material.fromType("Image", { image: "/ext/moon_lroc_2k.jpg" }),
      materialSupport: Cesium.MaterialAppearance.MaterialSupport.TEXTURED,
    }),
    asynchronous: false,
  }));
  scene.preRender.addEventListener(function (sc, time) {
    var m = moonAt(time);
    Cesium.Matrix4.fromRotationTranslation(m.Rf, m.pos, moonPrim.modelMatrix);
  });

  // 月球軌道：前後各 15 天、每 2 小時一點（EQJ），每幀乘上當下的 ICRF→地固
  var orbit = { center: null, pts: [] };
  function rebuildOrbit(jd) {
    orbit.center = JD.clone(jd);
    orbit.pts = [];
    var t0 = JD.toDate(jd).getTime();
    for (var h = -15 * 24; h <= 15 * 24; h += 2) {
      var g = Astronomy.GeoMoon(new Date(t0 + h * 3600e3));
      orbit.pts.push([g.x * AU_KM, g.y * AU_KM, g.z * AU_KM]);
    }
  }
  function inertialLine(ptsFn) {
    return new Cesium.CallbackProperty(function (t) {
      var M = icrf(t, _mFix), pts = ptsFn(t), out = new Array(pts.length);
      for (var i = 0; i < pts.length; i++) out[i] = toFixed(pts[i], M);
      return out;
    }, false);
  }
  var orbitEnt = viewer.entities.add({
    polyline: {
      positions: inertialLine(function (t) {
        if (!orbit.center || Math.abs(JD.daysDifference(t, orbit.center)) > 5) rebuildOrbit(t);
        return orbit.pts;
      }),
      width: 1.5, arcType: Cesium.ArcType.NONE, material: Cesium.Color.fromCssColorString("#9aa4b1").withAlpha(0.7),
    },
  });
  var geoPts = [];
  for (var a = 0; a <= 360; a += 2) geoPts.push(new C3(42164e3 * Math.cos(a * D2R), 42164e3 * Math.sin(a * D2R), 0));
  var geoEnt = viewer.entities.add({
    polyline: { positions: geoPts, width: 1, arcType: Cesium.ArcType.NONE, material: Cesium.Color.fromCssColorString("#f2a73b").withAlpha(0.8) },
    position: new C3(42164e3, 0, 0),
    label: { text: "GEO", font: "11px sans-serif", fillColor: Cesium.Color.fromCssColorString("#f2a73b"), pixelOffset: new Cesium.Cartesian2(14, 0) },
  });

  // 月面登陸點（selenographic 緯度、經度，取至 0.1°）
  var SITES = [
    ["Apollo 11", 0.67, 23.47, 1969, "us"], ["Apollo 12", -3.01, -23.42, 1969, "us"], ["Apollo 14", -3.65, -17.47, 1971, "us"],
    ["Apollo 15", 26.13, 3.63, 1971, "us"], ["Apollo 16", -8.97, 15.50, 1972, "us"], ["Apollo 17", 20.19, 30.77, 1972, "us"],
    ["Luna 2（撞月）", 29.1, 0.0, 1959, "su"], ["Luna 9", 7.08, -64.37, 1966, "su"], ["Surveyor 1", -2.47, -43.34, 1966, "us"],
    ["嫦娥三號", 44.12, -19.51, 2013, "cn"], ["嫦娥四號（背面）", -45.44, 177.60, 2019, "cn"], ["嫦娥五號", 43.06, -51.92, 2020, "cn"],
    ["嫦娥六號（背面）", -41.64, -153.99, 2024, "cn"], ["Chandrayaan-3", -69.37, 32.32, 2023, "in"], ["SLIM", -13.32, 25.25, 2024, "jp"],
    ["IM-1 Odysseus", -80.13, 1.44, 2024, "us"], ["Blue Ghost M1", 18.56, 61.81, 2025, "us"],
  ];
  var SITE_C = { us: "#58a6ff", su: "#ff7b72", cn: "#f2cc60", in: "#3fb950", jp: "#d2a8ff" };
  var siteEnts = SITES.map(function (s) {
    var local = sph(s[1], s[2]).map(function (v) { return v * (RM + 3) * 1000; });
    var lc = new C3(local[0], local[1], local[2]);
    return viewer.entities.add({
      position: new Cesium.CallbackProperty(function (t, res) {
        var m = moonAt(t), c = M3.multiplyByVector(m.Rf, lc, res || new C3());
        return C3.add(c, m.pos, c);
      }, false),
      point: { pixelSize: 6, color: Cesium.Color.fromCssColorString(SITE_C[s[4]]), outlineColor: Cesium.Color.BLACK, outlineWidth: 1,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 3e7) },
      label: { text: s[0] + " " + s[3], font: "11px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.WHITE,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
        pixelOffset: new Cesium.Cartesian2(8, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1.5e7) },
    });
  });

  // ── 慣性座標視角與預設視角 ────────────────────────────────────────────────
  var TAB = "moon";
  scene.postUpdate.addEventListener(function (sc, time) {
    if (TAB !== "moon" || !$("o-inertial").checked || viewer.trackedEntity || sc.mode !== Cesium.SceneMode.SCENE3D) return;
    var off = C3.clone(sc.camera.position);
    sc.camera.lookAtTransform(Cesium.Matrix4.fromRotationTranslation(icrf(time, new M3())), off);
  });
  function setView(kind) {
    var t = clock.currentTime, m = moonAt(t), M = icrf(t, new M3());
    if (kind === "moon") { viewer.trackedEntity = moonEnt; return; }
    if (kind === "ship") { if (ship.ent) viewer.trackedEntity = ship.ent; else status("請先發射太空船"); return; }
    viewer.trackedEntity = undefined;
    var offIn;                                         // 慣性座標下，相機相對地心的位置（公尺）
    if (kind === "earth") {
      var tp = C3.fromDegrees(121, 23.7, 0), Mt = M3.transpose(M, new M3());
      var pin = M3.multiplyByVector(Mt, tp, new C3());
      offIn = C3.multiplyByScalar(C3.normalize(pin, pin), 2.6e7, pin);
    } else {
      var g2 = Astronomy.GeoMoon(new Date(JD.toDate(t).getTime() + 3600e3));
      var h = unit(cross(m.r, sub([g2.x * AU_KM, g2.y * AU_KM, g2.z * AU_KM], m.r)));
      var rm = unit(m.r);
      offIn = new C3((h[0] * 0.95 - rm[0] * 0.3) * 1.15e9, (h[1] * 0.95 - rm[1] * 0.3) * 1.15e9, (h[2] * 0.95 - rm[2] * 0.3) * 1.15e9);
    }
    if ($("o-inertial").checked) {
      scene.camera.lookAtTransform(Cesium.Matrix4.fromRotationTranslation(M), offIn);
    } else {
      var offF = M3.multiplyByVector(M, offIn, new C3());
      scene.camera.lookAtTransform(Cesium.Matrix4.IDENTITY, offF);
      scene.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    }
  }
  document.querySelectorAll("[data-view]").forEach(function (b) { b.onclick = function () { setView(b.dataset.view); }; });
  $("o-inertial").onchange = function () { if (!this.checked) scene.camera.lookAtTransform(Cesium.Matrix4.IDENTITY); };
  $("o-orbit").onchange = function () { orbitEnt.show = this.checked; };
  $("o-geo").onchange = function () { geoEnt.show = this.checked; };
  $("o-sites").onchange = function () { var on = this.checked; siteEnts.forEach(function (e) { e.show = on; }); };

  // ── 時間控制 ─────────────────────────────────────────────────────────────
  function toLocalInput(d) { return tw(d).replace(" ", "T"); }
  $("t-pick").onchange = function () {
    var v = this.value; if (!v) return;
    var d = new Date(v + ":00Z"); d = new Date(d.getTime() - TW);
    clock.currentTime = JD.fromDate(d); preload(clock.currentTime); zoomTimeline(clock.currentTime, 15); refresh(true);
  };
  $("t-now").onclick = function () { clock.currentTime = JD.now(); preload(clock.currentTime); zoomTimeline(clock.currentTime, 15); refresh(true); };
  $("t-speed").onchange = function () { clock.multiplier = +this.value; };
  $("t-play").onclick = function () { clock.shouldAnimate = !clock.shouldAnimate; this.textContent = clock.shouldAnimate ? "⏸" : "▶"; };

  // ── 月相、台北看月亮、事件 ────────────────────────────────────────────────
  var QN = ["新月", "上弦", "滿月", "下弦"];
  function phaseName(a) {
    var near = function (x) { return Math.abs(wrap180(a - x)) < 6; };
    if (near(0)) return "新月"; if (near(90)) return "上弦月"; if (near(180)) return "滿月"; if (near(270)) return "下弦月";
    return a < 90 ? "眉月（漸盈）" : a < 180 ? "盈凸月" : a < 270 ? "虧凸月" : "殘月（漸虧）";
  }
  function subSolar(d, lib) {
    var sun = Astronomy.SunPosition(d);
    return { lat: 0, lon: wrap180(lib.elon + (sun.elon - lib.mlon) + 180) };
  }
  var ev = { at: null, html: "" };
  function events(d) {
    if (ev.at && Math.abs(d - ev.at) < 30 * 60e3 && d < ev.next) return ev.html;
    var rows = [], next = Infinity;
    function addT(label, at) { if (!at) return; var dd = at.date || at; rows.push([label, tw(dd)]); next = Math.min(next, dd.getTime()); }
    addT("下次月出", Astronomy.SearchRiseSet(Astronomy.Body.Moon, OBS, +1, d, 2));
    addT("下次月落", Astronomy.SearchRiseSet(Astronomy.Body.Moon, OBS, -1, d, 2));
    try { addT("下次中天", Astronomy.SearchHourAngle(Astronomy.Body.Moon, OBS, 0, d).time); } catch (e) {}
    var q = Astronomy.SearchMoonQuarter(d), qs = [];
    for (var i = 0; i < 4; i++) { qs.push(QN[q.quarter] + " " + tw(q.time.date).slice(5)); if (!i) next = Math.min(next, q.time.date.getTime()); q = Astronomy.NextMoonQuarter(q); }
    rows.push(["月相時刻", qs.join("<br>")]);
    var ap = Astronomy.SearchLunarApsis(d), aps = [];
    for (var j = 0; j < 2; j++) { aps.push((ap.kind === 0 ? "近地點 " : "遠地點 ") + tw(ap.time.date).slice(5) + "（" + fmt(ap.dist_km) + " km）"); ap = Astronomy.NextLunarApsis(ap); }
    rows.push(["近／遠地點", aps.join("<br>")]);
    var le = Astronomy.SearchLunarEclipse(d);
    var KN = { penumbral: "半影月食", partial: "月偏食", total: "月全食" };
    rows.push(["下次月食", (KN[le.kind] || le.kind) + " " + tw(le.peak.date) + "（食甚）"]);
    ev = { at: d, next: next, html: rows.map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") };
    return ev.html;
  }

  // 月面影像（月相小圖與月面圖共用）
  var tex = null, texW = 1024, texH = 512;
  var img = new Image();
  img.onload = function () {
    var c = document.createElement("canvas"); c.width = texW; c.height = texH;
    var g = c.getContext("2d"); g.drawImage(img, 0, 0, texW, texH);
    tex = g.getImageData(0, 0, texW, texH).data;
    mapBase = null; refresh(true);
  };
  img.src = "/ext/moon_lroc_2k.jpg";
  function texAt(lat, lon) {
    var u = Math.min(texW - 1, Math.max(0, Math.floor((wrap180(lon) + 180) / 360 * texW)));
    var v = Math.min(texH - 1, Math.max(0, Math.floor((90 - lat) / 180 * texH)));
    return (v * texW + u) * 4;
  }
  function smooth(e0, e1, x) { var t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }

  // 月相小圖（北半球視角，簡化：不含亮緣位置角）
  function drawPhase(lib, ss) {
    var cv = $("phase"), g = cv.getContext("2d"), W = cv.width, R = W / 2 - 4;
    var im = g.createImageData(W, W), px = im.data, sv = sph(ss.lat, ss.lon);
    for (var py = 0; py < W; py++) for (var qx = 0; qx < W; qx++) {
      var x = (qx - W / 2) / R, y = (W / 2 - py) / R, rr = x * x + y * y, k = (py * W + qx) * 4;
      if (rr > 1) continue;
      var z = Math.sqrt(1 - rr);
      var lon = lib.elon + Math.atan2(x, z) * R2D, lat = lib.elat + Math.asin(y) * R2D;
      var n = sph(lat, lon), l = 0.07 + 0.93 * smooth(-0.03, 0.08, dot(n, sv));
      var c = tex ? texAt(lat, lon) : -1, base = c >= 0 ? null : 170;
      px[k] = (base || tex[c]) * l; px[k + 1] = (base || tex[c + 1]) * l; px[k + 2] = (base || tex[c + 2]) * l; px[k + 3] = 255;
    }
    g.clearRect(0, 0, W, W); g.putImageData(im, 0, 0);
  }

  // 月面圖：等距圓柱投影，夜區變暗，地球可見半球邊界（虛線）、登陸點
  var mapBase = null, mapKey = "";
  function drawMap(lib, ss) {
    var cv = $("moonmap"), g = cv.getContext("2d"), W = cv.width, H = cv.height;
    var key = ss.lon.toFixed(1) + (tex ? "t" : "");
    if (key !== mapKey || !mapBase) {
      mapKey = key;
      var im = g.createImageData(W, H), px = im.data, sv = sph(ss.lat, ss.lon);
      for (var y = 0; y < H; y++) {
        var lat = 90 - (y + 0.5) / H * 180;
        for (var x = 0; x < W; x++) {
          var lon = (x + 0.5) / W * 360 - 180, k = (y * W + x) * 4;
          var l = 0.22 + 0.78 * smooth(-0.02, 0.05, dot(sph(lat, lon), sv));
          var c = tex ? texAt(lat, lon) : -1;
          px[k] = (c >= 0 ? tex[c] : 150) * l; px[k + 1] = (c >= 0 ? tex[c + 1] : 150) * l; px[k + 2] = (c >= 0 ? tex[c + 2] : 150) * l; px[k + 3] = 255;
        }
      }
      mapBase = im;
    }
    g.putImageData(mapBase, 0, 0);
    var X = function (lon) { return (wrap180(lon) + 180) / 360 * W; }, Y = function (lat) { return (90 - lat) / 180 * H; };
    // 地球可見半球邊界：距地球正下方點 90° 的大圓
    var P = sph(lib.elat, lib.elon), u = unit(cross(P, Math.abs(P[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), v = cross(P, u);
    g.fillStyle = "rgba(255,255,255,.85)";
    for (var f = 0; f < 360; f += 1.2) {
      var cf = Math.cos(f * D2R), sf = Math.sin(f * D2R);
      var q = [cf * u[0] + sf * v[0], cf * u[1] + sf * v[1], cf * u[2] + sf * v[2]];
      g.fillRect(X(Math.atan2(q[1], q[0]) * R2D) - 1, Y(Math.asin(q[2]) * R2D) - 1, 2, 2);
    }
    g.font = "bold 18px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillStyle = "#79c0ff"; g.fillText("＋", X(lib.elon), Y(lib.elat));
    g.fillStyle = "#ffd33d"; g.fillText("☀", X(ss.lon), Y(ss.lat));
    g.font = "11px 'Microsoft JhengHei',sans-serif"; g.textAlign = "left";
    SITES.forEach(function (s) {
      var sx = X(s[2]), sy = Y(s[1]);
      g.fillStyle = SITE_C[s[4]]; g.beginPath(); g.arc(sx, sy, 3.2, 0, 7); g.fill();
      g.strokeStyle = "#000"; g.lineWidth = 1; g.stroke();
    });
  }
  $("moonmap").onmousemove = function (e) {
    var r = this.getBoundingClientRect(), lon = (e.clientX - r.left) / r.width * 360 - 180, lat = 90 - (e.clientY - r.top) / r.height * 180;
    var best = null, bd = 6;
    SITES.forEach(function (s) { var d = Math.hypot(wrap180(s[2] - lon) * Math.cos(lat * D2R), s[1] - lat); if (d < bd) { bd = d; best = s; } });
    this.title = (best ? best[0] + "（" + best[3] + "）\n" : "") + "緯度 " + lat.toFixed(1) + "°、經度 " + lon.toFixed(1) + "°";
  };

  var lastRef = 0;
  function refresh(force) {
    var d = JD.toDate(clock.currentTime);
    if (!force && Math.abs(d - lastRef) < 1000) return;   // 模擬時間不到 1 秒的變化不重算
    lastRef = d;
    if (document.activeElement !== $("t-pick")) $("t-pick").value = toLocalInput(d);
    var lib = Astronomy.Libration(d), ph = Astronomy.MoonPhase(d), il = Astronomy.Illumination(Astronomy.Body.Moon, d);
    var eq = Astronomy.Equator(Astronomy.Body.Moon, d, OBS, true, true), hz = Astronomy.Horizon(d, OBS, eq.ra, eq.dec, "normal");
    var ss = subSolar(d, lib);
    $("moon-kv").innerHTML = [
      ["月相", phaseName(ph) + "（" + ph.toFixed(1) + "°）"],
      ["照亮比例", (il.phase_fraction * 100).toFixed(1) + "%"],
      ["月齡", (ph / 360 * 29.5306).toFixed(1) + " 天"],
      ["地月距離", fmt(lib.dist_km) + " km"],
      ["視直徑", (lib.diam_deg * 60).toFixed(1) + "′"],
      ["天平動", "緯 " + lib.elat.toFixed(2) + "°、經 " + lib.elon.toFixed(2) + "°"],
      ["台北看月亮", hz.altitude > 0 ? "方位 " + hz.azimuth.toFixed(0) + "°、仰角 " + hz.altitude.toFixed(1) + "°" : "在地平線下（" + hz.altitude.toFixed(0) + "°）"],
    ].map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("");
    $("moon-ev").innerHTML = events(d);
    drawPhase(lib, ss);
    drawMap(lib, ss);
  }
  setInterval(function () { if (TAB === "moon") refresh(false); }, 400);

  // ── 射月球 ──────────────────────────────────────────────────────────────
  // 每小時一筆的月球、太陽地心位置表（EQJ，km），4 點 Lagrange 內插（月球內插誤差約數公尺）
  function buildTables(t0ms, days) {
    var step = 3600e3, start = t0ms - 2 * step, n = Math.ceil((days * 24) + 6);
    var moon = new Float64Array(n * 3), sun = new Float64Array(n * 3);
    for (var i = 0; i < n; i++) {
      var d = new Date(start + i * step), m = Astronomy.GeoMoon(d), s = Astronomy.GeoVector(Astronomy.Body.Sun, d, false);
      moon[i * 3] = m.x * AU_KM; moon[i * 3 + 1] = m.y * AU_KM; moon[i * 3 + 2] = m.z * AU_KM;
      sun[i * 3] = s.x * AU_KM; sun[i * 3 + 1] = s.y * AU_KM; sun[i * 3 + 2] = s.z * AU_KM;
    }
    return { t0: t0ms, start: start, step: step, n: n, moon: moon, sun: sun };
  }
  function lag(tb, arr, tSec, out) {
    var u = (tb.t0 + tSec * 1000 - tb.start) / tb.step, i = Math.floor(u);
    if (i < 1) i = 1; if (i > tb.n - 3) i = tb.n - 3;
    var s = u - i, w0 = -s * (s - 1) * (s - 2) / 6, w1 = (s + 1) * (s - 1) * (s - 2) / 2, w2 = -(s + 1) * s * (s - 2) / 2, w3 = (s + 1) * s * (s - 1) / 6;
    for (var k = 0; k < 3; k++) {
      out[k] = w0 * arr[(i - 1) * 3 + k] + w1 * arr[i * 3 + k] + w2 * arr[(i + 1) * 3 + k] + w3 * arr[(i + 2) * 3 + k];
    }
    return out;
  }
  var _m = [0, 0, 0], _s = [0, 0, 0];
  function accel(tb, t, r, out) {
    lag(tb, tb.moon, t, _m); lag(tb, tb.sun, t, _s);
    var r2 = dot(r, r), r3 = r2 * Math.sqrt(r2);
    var dm = sub(_m, r), dm2 = dot(dm, dm), dm3 = dm2 * Math.sqrt(dm2), m2 = dot(_m, _m), m3 = m2 * Math.sqrt(m2);
    var ds = sub(_s, r), ds2 = dot(ds, ds), ds3 = ds2 * Math.sqrt(ds2), s2 = dot(_s, _s), s3 = s2 * Math.sqrt(s2);
    for (var k = 0; k < 3; k++) {
      out[k] = -MU_E * r[k] / r3 + MU_M * (dm[k] / dm3 - _m[k] / m3) + MU_S * (ds[k] / ds3 - _s[k] / s3);
    }
    return out;
  }
  function moonVel(tb, t) {
    var a = lag(tb, tb.moon, t - 30, [0, 0, 0]), b = lag(tb, tb.moon, t + 30, [0, 0, 0]);
    return [(b[0] - a[0]) / 60, (b[1] - a[1]) / 60, (b[2] - a[2]) / 60];
  }

  // 初始狀態：停泊圓軌道與月球軌道共面；點火位置角從「約 3 天後月球方向」量起，切向加速 Δv
  function initState(tb, prm) {
    var R = RE + prm.h;
    var m0 = lag(tb, tb.moon, 0, [0, 0, 0]), v0m = moonVel(tb, 0), mArr = lag(tb, tb.moon, 3 * 86400, [0, 0, 0]);
    var h = unit(cross(m0, v0m)), e1 = unit(mArr), e2 = unit(cross(h, e1));
    var th = prm.theta * D2R, rh = [Math.cos(th) * e1[0] + Math.sin(th) * e2[0], Math.cos(th) * e1[1] + Math.sin(th) * e2[1], Math.cos(th) * e1[2] + Math.sin(th) * e2[2]];
    var vh = unit(cross(h, rh)), v = Math.sqrt(MU_E / R) + prm.dv / 1000;
    return { r: [rh[0] * R, rh[1] * R, rh[2] * R], v: [vh[0] * v, vh[1] * v, vh[2] * v] };
  }

  function simulate(tb, prm, opt) {
    var st = initState(tb, prm), r = st.r, v = st.v, t = 0, tEnd = prm.days * 86400;
    var k1 = [0, 0, 0], k2 = [0, 0, 0], k3 = [0, 0, 0], k4 = [0, 0, 0], rt = [0, 0, 0], mp = [0, 0, 0];
    var rMin = Infinity, tMin = 0, rMinPos = null, prevD = Infinity, falling = false, nearMoon = false;
    var peri1 = null, prevE = Infinity, eFalling = false, pMin = Infinity;   // 第一次近月點；飛掠後的地球近地點
    var out = { samples: opt.scan ? null : [[0, r[0], r[1], r[2]]], events: [{ t: 0, kind: "tli", r: r.slice() }], outcome: null, loi: null };
    var lastS = 0;
    while (t < tEnd) {
      lag(tb, tb.moon, t, mp);
      var rE = norm(r), dM = Math.sqrt((r[0] - mp[0]) * (r[0] - mp[0]) + (r[1] - mp[1]) * (r[1] - mp[1]) + (r[2] - mp[2]) * (r[2] - mp[2]));
      var tau = Math.min(Math.pow(rE, 1.5) / Math.sqrt(MU_E), Math.pow(Math.max(dM, RM * 0.5), 1.5) / Math.sqrt(MU_M));
      var dt = Math.min(900, Math.max(2, 0.03 * tau));
      // RK4
      accel(tb, t, r, k1);
      var va = [v[0] + k1[0] * dt / 2, v[1] + k1[1] * dt / 2, v[2] + k1[2] * dt / 2];
      for (var i = 0; i < 3; i++) rt[i] = r[i] + v[i] * dt / 2;
      accel(tb, t + dt / 2, rt, k2);
      var vb = [v[0] + k2[0] * dt / 2, v[1] + k2[1] * dt / 2, v[2] + k2[2] * dt / 2];
      for (i = 0; i < 3; i++) rt[i] = r[i] + va[i] * dt / 2;
      accel(tb, t + dt / 2, rt, k3);
      var vc = [v[0] + k3[0] * dt, v[1] + k3[1] * dt, v[2] + k3[2] * dt];
      for (i = 0; i < 3; i++) rt[i] = r[i] + vb[i] * dt;
      accel(tb, t + dt, rt, k4);
      for (i = 0; i < 3; i++) {
        r[i] += dt / 6 * (v[i] + 2 * va[i] + 2 * vb[i] + vc[i]);
        v[i] += dt / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]);
      }
      t += dt;
      lag(tb, tb.moon, t, mp);
      var d2 = Math.sqrt((r[0] - mp[0]) * (r[0] - mp[0]) + (r[1] - mp[1]) * (r[1] - mp[1]) + (r[2] - mp[2]) * (r[2] - mp[2]));
      var rE2 = norm(r);
      if (d2 < rMin) { rMin = d2; tMin = t; rMinPos = r.slice(); }
      if (d2 < 30000) nearMoon = true;
      if (falling && d2 > prevD) {                      // 剛通過近月點
        if (!peri1 && prevD < 66000) peri1 = { alt: prevD - RM, t: t, r: r.slice() };
        if (opt.scan === true && prevD < 2e5) break;
        if (prm.loi && !out.loi && prevD < 30000) {
          var vm = moonVel(tb, t), vr = sub(v, vm), u = unit(vr), dv = prm.dvLoi / 1000;
          for (i = 0; i < 3; i++) v[i] -= u[i] * dv;
          out.loi = { t: t, r: r.slice() };
          out.events.push({ t: t, kind: "loi", r: r.slice() });
        }
      }
      falling = d2 < prevD; prevD = d2;
      if (peri1) {                                      // 飛掠後：追蹤回到地球的近地點（自由返回用）
        if (rE2 < pMin) pMin = rE2;
        if (opt.scan === "free" && ((eFalling && rE2 > prevE) || rE2 < RE)) break;
        eFalling = rE2 < prevE; prevE = rE2;
      }
      if (opt.scan === "free" && d2 < RM) break;
      if (!opt.scan) {
        if (d2 < RM) { out.outcome = "impact"; out.events.push({ t: t, kind: "impact", r: r.slice() }); break; }
        if (rE2 < RE + 120 && t > 3600) { out.outcome = nearMoon ? "free" : "reentry"; out.events.push({ t: t, kind: "reentry", r: r.slice() }); break; }
        if (rE2 > 1.5e6) { out.outcome = "escape"; break; }
        var gap = (d2 < 30000 || rE2 < 30000) ? 60 : 300;
        if (t - lastS >= gap) { out.samples.push([t, r[0], r[1], r[2]]); lastS = t; }
      } else if (opt.scan === true && t > 8 * 86400) break;
    }
    if (!opt.scan) out.samples.push([t, r[0], r[1], r[2]]);
    out.tEnd = t; out.rMin = rMin; out.peri1 = peri1;
    out.perigeeAfter = peri1 && pMin < Infinity ? pMin - RE : null;
    // 抵達時的近月點（入軌後繞月的近月點另計）；撞月時取 0
    var pa = peri1 || { alt: rMin - RM, t: tMin, r: rMinPos };
    out.minAlt = out.outcome === "impact" && !peri1 ? 0 : pa.alt; out.tMin = pa.t;
    if (pa.r) out.events.push({ t: pa.t, kind: "peri", r: pa.r });
    if (!opt.scan && !out.outcome) {
      if (out.loi) {
        lag(tb, tb.moon, t, mp);
        var rr = sub(r, mp), vv = sub(v, moonVel(tb, t)), rn = norm(rr), en = dot(vv, vv) / 2 - MU_M / rn;
        if (en < 0) {
          var aa = -MU_M / (2 * en), hh = norm(cross(rr, vv)), ee = Math.sqrt(Math.max(0, 1 + 2 * en * hh * hh / (MU_M * MU_M)));
          out.lunar = { peri: aa * (1 - ee) - RM, apo: aa * (1 + ee) - RM };
          out.outcome = out.lunar.apo < 60000 ? "orbit" : "loose";
        } else out.outcome = "loi_fail";
      } else out.outcome = nearMoon ? "flyby" : "short";
    }
    return out;
  }

  var OUT_TXT = {
    impact: "撞上月球", free: "繞過月球後回到地球大氣（自由返回）", reentry: "沒到月球就落回地球大氣",
    escape: "飛離地月系統", orbit: "進入繞月軌道", loose: "制動不足：仍繞月但遠月點太高，會被拉走",
    loi_fail: "制動不足，沒被月球捕獲", flyby: "飛掠月球後繼續在太空中", short: "Δv 不足，到不了月球附近",
  };
  function challengeOk(ch, r) {
    if (ch === "impact") return r.outcome === "impact";
    if (ch === "flyby") return r.outcome !== "impact" && r.minAlt >= 50 && r.minAlt <= 200;
    if (ch === "free") return r.outcome === "free" && r.minAlt > 0;
    if (ch === "orbit") return r.outcome === "orbit" && r.lunar && r.lunar.peri > 0;
    return false;
  }
  function params() {
    return {
      h: +$("g-h").value, dv: +$("g-dv").value, theta: +$("g-th").value, days: Math.min(30, Math.max(2, +$("g-days").value || 12)),
      loi: $("g-loi").checked, dvLoi: +$("g-dvl").value,
    };
  }
  $("g-th").oninput = function () { $("g-thv").textContent = (+this.value).toFixed(2) + "°"; };
  $("g-ch").onchange = function () {
    var c = this.value;
    $("g-loi").checked = c === "orbit";
    $("g-tgt").value = c === "impact" ? -1000 : c === "free" ? 250 : c === "orbit" ? 110 : 110;
  };

  // 太空船與軌跡（EQJ 取樣，畫面每幀轉到地固）
  var ship = { ent: null, line: null, marks: [], res: null, t0: null };
  function clearShip() {
    if (ship.ent) viewer.entities.remove(ship.ent);
    if (ship.line) viewer.entities.remove(ship.line);
    ship.marks.forEach(function (e) { viewer.entities.remove(e); });
    if (viewer.trackedEntity === ship.ent) viewer.trackedEntity = undefined;
    ship = { ent: null, line: null, marks: [], res: null, t0: null };
  }
  function sampleAt(S, tSec) {
    var lo = 0, hi = S.length - 1;
    if (tSec <= S[0][0]) return [S[0][1], S[0][2], S[0][3]];
    if (tSec >= S[hi][0]) return [S[hi][1], S[hi][2], S[hi][3]];
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (S[mid][0] <= tSec) lo = mid; else hi = mid; }
    var a = S[lo], b = S[hi], f = (tSec - a[0]) / (b[0] - a[0]);
    return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f];
  }
  var MARK = { tli: ["TLI 點火", "#3fb950"], peri: ["近月點", "#d2a8ff"], loi: ["LOI 制動", "#f2a73b"], impact: ["撞月", "#ff7b72"], reentry: ["再入大氣", "#ff7b72"] };
  function drawShip(res, t0ms) {
    clearShip();
    ship.res = res; ship.t0 = JD.fromDate(new Date(t0ms));
    var pts = res.samples.map(function (s) { return [s[1], s[2], s[3]]; });
    ship.line = viewer.entities.add({ polyline: { positions: inertialLine(function () { return pts; }), width: 2, arcType: Cesium.ArcType.NONE,
      material: Cesium.Color.fromCssColorString("#39d0d8") } });
    ship.ent = viewer.entities.add({
      name: "太空船",
      position: new Cesium.CallbackProperty(function (t, out) {
        var s = JD.secondsDifference(t, ship.t0);
        return toFixed(sampleAt(res.samples, s), icrf(t, _mFix), out);
      }, false),
      point: { pixelSize: 8, color: Cesium.Color.WHITE, outlineColor: Cesium.Color.fromCssColorString("#39d0d8"), outlineWidth: 2 },
      label: { text: "🚀", font: "16px sans-serif", pixelOffset: new Cesium.Cartesian2(0, -16) },
    });
    res.events.forEach(function (e) {
      var mk = MARK[e.kind]; if (!mk) return;
      var r = e.r;
      ship.marks.push(viewer.entities.add({
        position: new Cesium.CallbackProperty(function (t, out) { return toFixed(r, icrf(t, _mFix), out); }, false),
        point: { pixelSize: 7, color: Cesium.Color.fromCssColorString(mk[1]) },
        label: { text: mk[0] + " " + tw(new Date(t0ms + e.t * 1000)).slice(5), font: "11px 'Microsoft JhengHei',sans-serif",
          fillColor: Cesium.Color.fromCssColorString(mk[1]), style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2, pixelOffset: new Cesium.Cartesian2(10, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT },
      }));
    });
    var stop = JD.addSeconds(ship.t0, res.tEnd, new JD());
    clock.startTime = JD.clone(ship.t0); clock.stopTime = stop; clock.currentTime = JD.clone(ship.t0);
    clock.clockRange = Cesium.ClockRange.CLAMPED; clock.multiplier = 3600; $("t-speed").value = "3600";
    clock.shouldAnimate = true; $("t-play").textContent = "⏸";
    viewer.timeline.zoomTo(ship.t0, stop);
  }
  function report(res, prm, ch) {
    var ok = challengeOk(ch, res), dvTot = prm.dv + (res.loi ? prm.dvLoi : 0);
    var h = "<span class='" + (ok ? "ok" : "bad") + "'>" + (ok ? "✅ 挑戰成功" : "❌ 挑戰未達成") + "</span>：" + OUT_TXT[res.outcome] + "<br>";
    if (res.outcome === "impact" && !res.peri1) h += "撞月時刻：發射後 <b>" + (res.tEnd / 3600).toFixed(1) + " 小時</b>";
    else h += "抵達時近月點高度 <b>" + fmt(res.minAlt) + " km</b>（發射後 " + (res.tMin / 3600).toFixed(1) + " 小時）";
    if (res.perigeeAfter != null && (ch === "free" || res.outcome === "free"))
      h += "<br>飛掠後回到地球的近地點高度 " + fmt(res.perigeeAfter) + " km（低於 120 km 才會再入大氣）";
    if (res.lunar) h += "<br>繞月軌道：近月點 " + fmt(res.lunar.peri) + " km、遠月點 " + fmt(res.lunar.apo) + " km";
    h += "<br>總 Δv " + fmt(dvTot) + " m/s（TLI " + fmt(prm.dv) + (res.loi ? " ＋ LOI " + fmt(prm.dvLoi) : "") + "）";
    $("res").innerHTML = h;
  }
  function status(s) { $("status").textContent = s || ""; }

  $("g-run").onclick = function () {
    var prm = params(), ch = $("g-ch").value, t0 = JD.toDate(clock.currentTime).getTime();
    if (ship.t0 && clock.clockRange === Cesium.ClockRange.CLAMPED) t0 = JD.toDate(ship.t0).getTime();   // 重新發射沿用同一個發射時刻
    var tb = buildTables(t0, prm.days + 1);
    var t1 = performance.now(), res = simulate(tb, prm, { scan: false });
    status("積分 " + res.samples.length + " 點，" + (performance.now() - t1).toFixed(0) + " ms");
    drawShip(res, t0); report(res, prm, ch); setView("cislunar");
  };
  $("g-clear").onclick = function () {
    clearShip(); clock.clockRange = Cesium.ClockRange.UNBOUNDED; $("res").textContent = "已清除軌跡。"; status("");
  };

  // 自動瞄準：掃描點火位置，找近月點高度最接近目標的解（自由返回另以完整模擬檢查是否真的回到地球）
  $("g-aim").onclick = function () {
    var btn = this, prm = params(), ch = $("g-ch").value, tgt = +$("g-tgt").value;
    var t0 = ship.t0 && clock.clockRange === Cesium.ClockRange.CLAMPED ? JD.toDate(ship.t0).getTime() : JD.toDate(clock.currentTime).getTime();
    var tb = buildTables(t0, Math.max(prm.days, 9) + 1), goal = RM + tgt;
    var rmin = function (th) { return simulate(tb, Object.assign({}, prm, { theta: th, loi: false }), { scan: true }).rMin; };
    var f = function (th) { return Math.abs(rmin(th) - goal); };
    // 自由返回：目標是「飛掠後回到地球的近地點高度」約 50 km（再入走廊），撞月或沒到月球給大罰分
    var gFree = function (th) {
      var r = simulate(tb, Object.assign({}, prm, { theta: th, loi: false }), { scan: "free" });
      if (!r.peri1 || r.peri1.alt < 0 || r.perigeeAfter == null) return 1e9;
      return Math.abs(r.perigeeAfter - 50);
    };
    btn.disabled = true; status("自動瞄準：粗掃 0–360°…");
    var coarse = [], th = 0;
    (function step() {
      var tEnd = performance.now() + 40;
      while (th < 360 && performance.now() < tEnd) { var rr0 = rmin(th); coarse.push([th, Math.abs(rr0 - goal), rr0]); th += 2; }
      if (th < 360) { status("自動瞄準：粗掃 " + Math.round(th / 3.6) + "%"); setTimeout(step, 0); return; }
      var n = coarse.length, mins = [];
      for (var i = 0; i < n; i++) {
        var a = coarse[(i - 1 + n) % n][1], b = coarse[i][1], c = coarse[(i + 1) % n][1];
        if (b <= a && b <= c) mins.push(coarse[i]);
      }
      mins.sort(function (x, y) { return x[1] - y[1]; }); mins = mins.slice(0, 4);
      var cands = mins.map(function (m) {
        var best = m;
        [[0.2, 2], [0.01, 0.2]].forEach(function (g) {
          var c0 = best[0];
          for (var x = c0 - g[1]; x <= c0 + g[1] + 1e-9; x += g[0]) { var v = f(x); if (v < best[1]) best = [x, v]; }
        });
        return [((best[0] % 360) + 360) % 360, best[1]];
      }).sort(function (x, y) { return x[1] - y[1]; });
      var pick = cands[0], unitTxt = "近月點誤差";
      if (ch === "free" && pick && pick[1] < 50000) {
        // 在能接近月球（近月距離 < 2 萬 km）的點火角度區間內細掃回程近地點
        var best = null;
        coarse.forEach(function (c) {
          if (c[2] > RM + 20000) return;
          for (var x = c[0] - 1; x <= c[0] + 1 + 1e-9; x += 0.05) { var v = gFree(x); if (!best || v < best[1]) best = [x, v]; }
        });
        if (best && best[1] < 1e9) {
          for (var x2 = best[0] - 0.05; x2 <= best[0] + 0.05 + 1e-9; x2 += 0.002) { var v2 = gFree(x2); if (v2 < best[1]) best = [x2, v2]; }
          pick = [((best[0] % 360) + 360) % 360, best[1]]; unitTxt = "回程近地點與 50 km 相差";
        } else { pick = null; }
      }
      btn.disabled = false;
      if (!pick || pick[1] > 50000) {
        status(ch === "free" ? "這個 Δv 找不到自由返回軌道：試試 3,100–3,200 m/s 或改變發射時刻"
          : "找不到能接近月球的點火位置：請加大 TLI Δv（一般需 3,100 m/s 以上）");
        return;
      }
      $("g-th").value = pick[0].toFixed(3); $("g-thv").textContent = pick[0].toFixed(2) + "°";
      status("自動瞄準完成：點火位置 " + pick[0].toFixed(3) + "°，" + unitTxt + " " + fmt(pick[1]) + " km；按「發射」看結果");
    })();
  };

  // ── 分頁切換（其他遊戲在各自的檔案，透過 window.SDG 與 sdg-tab 事件取得 viewer 與切換通知）──
  function setTab(t) {
    TAB = t;
    document.querySelectorAll("#tabs button[data-tab]").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === t); });
    document.querySelectorAll("[id^=tab-]").forEach(function (el) { el.hidden = el.id !== "tab-" + t; });
    var on = t === "moon";
    moonPrim.show = on; moonEnt.show = on;
    orbitEnt.show = on && $("o-orbit").checked;
    siteEnts.forEach(function (e) { e.show = on && $("o-sites").checked; });
    [ship.ent, ship.line].concat(ship.marks).forEach(function (e) { if (e) e.show = on; });
    viewer.trackedEntity = undefined;
    scene.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    // 各遊戲會改時鐘範圍（射月球、氣球慢動作）；切換分頁時恢復成不受限的一般播放
    if (clock.clockRange !== Cesium.ClockRange.UNBOUNDED) {
      clock.clockRange = Cesium.ClockRange.UNBOUNDED;
      if (t !== "moon" || !ship.ent) { clock.multiplier = 3600; $("t-speed").value = "3600"; }
    }
    if (on && ship.ent) clock.clockRange = Cesium.ClockRange.CLAMPED;
    if (on) { setView("cislunar"); refresh(true); }
    document.dispatchEvent(new CustomEvent("sdg-tab", { detail: t }));
  }
  document.querySelectorAll("#tabs button[data-tab]").forEach(function (b) { b.onclick = function () { if (!b.disabled) setTab(b.dataset.tab); }; });
  window.SDG = { viewer: viewer, status: status, tw: tw, fmt: fmt, icrf: icrf, tab: function () { return TAB; } };

  setView("cislunar");
  refresh(true);
})();
