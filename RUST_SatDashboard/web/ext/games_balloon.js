/* 太空小遊戲：鋁箔氣球日食（/games 分頁）
 * 在指定時刻把氣球放在「太陽—台北」連線上的指定高度，依傾角反推經過該點的圓軌道（二體），
 * 每個時刻：太陽（astronomy-engine）、氣球位置 → 影軸與 WGS84 橢球交點 → 本影／偽本影／半影半徑，
 * 並從台北看日面被遮住的比例（兩圓相交面積）。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, scene = viewer.scene, fmt = SDG.fmt, icrf = SDG.icrf;
  var C3 = Cesium.Cartesian3, M3 = Cesium.Matrix3, JD = Cesium.JulianDate;
  var AU_KM = 149597870.7, RE = 6378.137, MU = 398600.4418, R_SUN = 695700, OMEGA = 7.2921159e-5;
  var SIGMA = 66 / (Math.PI * 30.5 * 30.5);          // Echo 1：66 kg、直徑 30.5 m → 面密度約 22.6 g/m²
  var TP = C3.fromDegrees(121.5654, 25.0330, 10);    // 台北（地固，公尺）
  var D2R = Math.PI / 180, R2D = 180 / Math.PI;
  function norm(a) { return Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]); }
  function unit(a) { var n = norm(a); return [a[0] / n, a[1] / n, a[2] / n]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function v3(c) { return [c.x / 1000, c.y / 1000, c.z / 1000]; }       // Cartesian3（m）→ km 陣列
  function c3(a, res) { var c = res || new C3(); c.x = a[0] * 1000; c.y = a[1] * 1000; c.z = a[2] * 1000; return c; }
  function mul(M, a) { var c = M3.multiplyByVector(M, new C3(a[0], a[1], a[2]), new C3()); return [c.x, c.y, c.z]; }

  // Vallado 指數大氣（h0 km, ρ0 kg/m³, H km）
  var ATM = [[100, 5.297e-7, 5.877], [110, 9.661e-8, 7.263], [120, 2.438e-8, 9.473], [130, 8.484e-9, 12.636], [140, 3.845e-9, 16.149],
    [150, 2.070e-9, 22.523], [180, 5.464e-10, 29.740], [200, 2.789e-10, 37.105], [250, 7.248e-11, 45.546], [300, 2.418e-11, 53.628],
    [350, 9.518e-12, 53.298], [400, 3.725e-12, 58.515], [450, 1.585e-12, 60.828], [500, 6.967e-13, 63.822], [600, 1.454e-13, 71.835],
    [700, 3.614e-14, 88.667], [800, 1.170e-14, 124.64], [900, 5.245e-15, 181.05], [1000, 3.019e-15, 268.00]];
  function rho(h) {
    var row = ATM[0];
    for (var i = 0; i < ATM.length; i++) if (h >= ATM[i][0]) row = ATM[i];
    return row[1] * Math.exp(-(h - row[0]) / row[2]);
  }
  // 圓軌道衰減：da/dt = −ρ·Cd·(A/m)·√(μa)，每降 1 km 累加時間，降到 120 km 為止
  function lifetimeDays(h, am) {
    var t = 0, cd = 2.2;
    for (var x = h; x > 120; x -= 1) {
      var a = (RE + x) * 1000, dadt = rho(x) * cd * am * Math.sqrt(MU * 1e9 * a);
      t += 1000 / dadt;
      if (t > 100 * 365.25 * 86400) return Infinity;
    }
    return t / 86400;
  }
  // 兩圓（半徑 R、r，圓心距 d）相交面積 ÷ 大圓面積
  function overlap(R, r, d) {
    if (d >= R + r) return 0;
    if (d <= Math.abs(R - r)) return Math.min(1, (r * r) / (R * R));
    var a = r * r * Math.acos((d * d + r * r - R * R) / (2 * d * r)), b = R * R * Math.acos((d * d + R * R - r * r) / (2 * d * R));
    var c = 0.5 * Math.sqrt((-d + r + R) * (d + r - R) * (d - r + R) * (d + r + R));
    return (a + b - c) / (Math.PI * R * R);
  }

  var sim = null, ents = [];
  function sunEqj(date) { var s = Astronomy.GeoVector(Astronomy.Body.Sun, date, true); return [s.x * AU_KM, s.y * AU_KM, s.z * AU_KM]; }

  // 時刻 jd 的完整幾何（地固座標，km）
  function geom(jd) {
    var tau = JD.secondsDifference(jd, sim.t0), o = sim.orb;
    var u = o.u0 + o.n * tau, cu = Math.cos(u), su = Math.sin(u);
    var Bi = [o.a * (o.co * cu - o.so * su * o.ci), o.a * (o.so * cu + o.co * su * o.ci), o.a * su * o.si];
    var M = icrf(jd, new M3());
    var Bf = mul(M, Bi), Sf = mul(M, sunEqj(JD.toDate(jd)));
    var Tf = v3(TP), dir = unit(sub(Bf, Sf));
    var alpha = 2 * Math.asin(R_SUN / norm(sub(Sf, Tf)));
    var ray = new Cesium.Ray(c3(Bf), new C3(dir[0], dir[1], dir[2]));
    var hit = Cesium.IntersectionTests.rayEllipsoid(ray, Cesium.Ellipsoid.WGS84), Q = null, s = null, sinE = null;
    if (hit && hit.start > 0) {
      var q = Cesium.Ray.getPoint(ray, hit.start, new C3());
      Q = v3(q); s = hit.start / 1000;
      var up = Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(q, new C3());
      sinE = -(dir[0] * up.x + dir[1] * up.y + dir[2] * up.z);
    }
    var us = unit(sub(Sf, Tf)), ub = unit(sub(Bf, Tf));
    return { Bf: Bf, Sf: Sf, Q: Q, s: s, sinE: sinE, alpha: alpha, us: us, ub: ub, dTB: norm(sub(Bf, Tf)) };
  }

  function clearEnts() { ents.forEach(function (e) { viewer.entities.remove(e); }); ents = []; }

  $("b-dp").onchange = function () { if (this.value) $("b-d").value = this.value; this.value = ""; };
  $("b-hp").onchange = function () { if (this.value) $("b-h").value = this.value; this.value = ""; };

  $("b-run").onclick = function () {
    var D = Math.max(1, +$("b-d").value) / 1000, h = Math.max(160, +$("b-h").value), inc = +$("b-i").value * D2R;
    var t0 = JD.clone(viewer.clock.currentTime), date = JD.toDate(t0);
    var M = icrf(t0, new M3()), Mt = M3.transpose(M, new M3());
    var Ti = mul(Mt, v3(TP)), Si = sunEqj(date), us = unit(sub(Si, Ti));
    var eq = Astronomy.Equator(Astronomy.Body.Sun, date, new Astronomy.Observer(25.033, 121.5654, 10), true, true);
    var elev = Astronomy.Horizon(date, new Astronomy.Observer(25.033, 121.5654, 10), eq.ra, eq.dec, "normal").altitude;
    if (elev < 3) { $("b-res").innerHTML = "<span style='color:#ff7b72'>台北此刻太陽仰角 " + elev.toFixed(1) + "°：請把上方時間調到台北白天（例如中午 12 點）。</span>"; return; }
    // 氣球位置：台北沿太陽方向前進，直到地心距離 = RE + h
    var a = RE + h, tu = dot(Ti, us), x = -tu + Math.sqrt(tu * tu - dot(Ti, Ti) + a * a);
    var B = [Ti[0] + us[0] * x, Ti[1] + us[1] * x, Ti[2] + us[2] * x];
    var dec = Math.asin(B[2] / a), ra = Math.atan2(B[1], B[0]);
    if (Math.sin(inc) < Math.abs(Math.sin(dec))) inc = Math.abs(dec) + 0.01;
    var u0 = Math.asin(Math.max(-1, Math.min(1, Math.sin(dec) / Math.sin(inc))));
    if ($("b-dir").value === "desc") u0 = Math.PI - u0;
    var raan = ra - Math.atan2(Math.cos(inc) * Math.sin(u0), Math.cos(u0));
    var n = Math.sqrt(MU / (a * a * a));
    sim = { t0: t0, D: D, h: h, orb: { a: a, n: n, u0: u0, co: Math.cos(raan), so: Math.sin(raan), ci: Math.cos(inc), si: Math.sin(inc) } };

    // 台北此刻的影子數字
    var g0 = geom(t0), s0 = x, ta = Math.tan(g0.alpha / 2);
    var ru = D / 2 - s0 * ta, rp = D / 2 + s0 * ta, dmin = 2 * s0 * ta;
    var vB = [a * n * (-sim.orb.co * Math.sin(u0) - sim.orb.so * Math.cos(u0) * sim.orb.ci),
      a * n * (-sim.orb.so * Math.sin(u0) + sim.orb.co * Math.cos(u0) * sim.orb.ci), a * n * Math.cos(u0) * sim.orb.si];
    var vT = cross([0, 0, OMEGA], Ti), vr = sub(vB, vT), vperp = norm(sub(vr, [us[0] * dot(vr, us), us[1] * dot(vr, us), us[2] * dot(vr, us)]));
    var thB = 2 * Math.asin(D / 2 / s0), cover = ru > 0 ? 1 : Math.pow(thB / g0.alpha, 2);
    var mass = SIGMA * Math.PI * Math.pow(D * 1000, 2) / 1000;   // 噸
    var life = lifetimeDays(h, 1 / (4 * SIGMA));
    var mag = -26.74 - 2.5 * Math.log10(0.9 * Math.pow((D / 2) / (2 * h), 2));
    var kind = ru > 0 ? "<b style='color:#3fb950'>本影到達地面：台北可見日全食</b>"
      : cover < 0.01 ? "<b style='color:#ff7b72'>日面只被遮住 " + (cover * 100).toPrecision(2) + "%，肉眼察覺不到</b>"
      : "<b style='color:#f2a73b'>本影沒到地面：只有環食（偽本影）與偏食</b>";
    mag = Math.round(mag * 10) / 10 || 0;
    var rows = [
      ["結果", kind],
      ["台北到氣球距離", fmt(s0) + " km（太陽仰角 " + elev.toFixed(1) + "°）"],
      ["太陽視直徑", (g0.alpha * R2D * 60).toFixed(2) + "′"],
      ["全食所需最小直徑", "<b>" + fmt(dmin * 1000) + " m</b>（目前 " + fmt(D * 1000) + " m）"],
      ["本影長度", fmt(D / (2 * ta)) + " km（約直徑的 " + (1 / (2 * ta)).toFixed(0) + " 倍）"],
      [ru > 0 ? "本影直徑（垂直影軸）" : "偽本影直徑", fmt(Math.abs(ru) * 2000) + " m"],
      ["半影直徑", fmt(rp * 2) + " km"],
      ["日面遮住比例（中心線）", (cover * 100).toFixed(cover < 0.01 ? 4 : 1) + "%"],
      ["影子掃過速度", vperp.toFixed(2) + " km/s"],
      [ru > 0 ? "全食持續" : "環食持續", (Math.abs(ru) * 2 / vperp).toFixed(3) + " 秒"],
      ["偏食（變暗）持續", (rp * 2 / vperp).toFixed(1) + " 秒"],
      ["氣球質量（Echo 面密度）", mass < 1 ? fmt(mass * 1000) + " kg" : fmt(mass) + " 噸"],
      ["大氣阻力壽命（粗估）", life === Infinity ? "> 100 年（主要受太陽輻射壓擾動）" : life < 1 ? fmt(life * 24, 1) + " 小時" : fmt(life, life < 30 ? 1 : 0) + " 天"],
      ["夜空亮度（天頂）", mag.toFixed(1) + " 等（滿月約 −12.7、金星約 −4.5）"],
    ];
    $("b-res").innerHTML = "<table class='kv'>" + rows.map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") + "</table>";

    // 3D：影子中心線、影子足跡、氣球、陽光方向
    clearEnts();
    var T = 2 * Math.PI / n, wTrack = Math.min(900, T / 8), track = [];
    for (var k = -100; k <= 100; k++) {
      var g = geom(JD.addSeconds(t0, wTrack * k / 100, new JD()));
      if (g.Q) track.push(c3(g.Q));
    }
    if (track.length > 1) ents.push(viewer.entities.add({ polyline: { positions: track, width: 2, material: Cesium.Color.YELLOW.withAlpha(0.8) } }));
    var cache = { key: null, g: null };
    function G(t) { var kk = t.dayNumber * 86400 + t.secondsOfDay; if (cache.key !== kk) { cache.key = kk; cache.g = geom(t); } return cache.g; }
    function foot(rFn, color, outline) {
      return viewer.entities.add({
        position: new Cesium.CallbackProperty(function (t, res) { var g = G(t); return g.Q ? c3(g.Q, res) : undefined; }, false),
        ellipse: {
          semiMajorAxis: new Cesium.CallbackProperty(function (t) { var g = G(t); return g.Q ? Math.max(1, rFn(g) * 1000 / Math.max(0.05, g.sinE)) : 1; }, false),
          semiMinorAxis: new Cesium.CallbackProperty(function (t) { var g = G(t); return g.Q ? Math.max(1, rFn(g) * 1000) : 1; }, false),
          material: color, outline: !!outline, outlineColor: outline || Cesium.Color.BLACK, height: 0,
        },
      });
    }
    ents.push(foot(function (g) { return D / 2 + g.s * Math.tan(g.alpha / 2); }, Cesium.Color.BLACK.withAlpha(0.25)));
    ents.push(foot(function (g) { return Math.abs(D / 2 - g.s * Math.tan(g.alpha / 2)); },
      ru > 0 ? Cesium.Color.BLACK.withAlpha(0.85) : Cesium.Color.ORANGE.withAlpha(0.6)));
    ents.push(viewer.entities.add({
      position: new Cesium.CallbackProperty(function (t, res) { return c3(G(t).Bf, res); }, false),
      ellipsoid: D > 0.5 ? { radii: new C3(D * 500, D * 500, D * 500), material: Cesium.Color.SILVER } : undefined,
      point: { pixelSize: 7, color: Cesium.Color.SILVER, outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
      label: { text: "🎈 " + fmt(D * 1000) + " m", font: "12px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.WHITE,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2, pixelOffset: new Cesium.Cartesian2(10, -10),
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT },
    }));
    ents.push(viewer.entities.add({
      polyline: { positions: new Cesium.CallbackProperty(function (t) {
        var g = G(t), far = [g.Bf[0] + (g.Bf[0] - (g.Q || g.Bf)[0]), g.Bf[1] + (g.Bf[1] - (g.Q || g.Bf)[1]), g.Bf[2] + (g.Bf[2] - (g.Q || g.Bf)[2])];
        return [c3(g.Q || v3(TP)), c3(far)];
      }, false), width: 1.5, arcType: Cesium.ArcType.NONE, material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.GOLD }) },
    }));
    ents.push(viewer.entities.add({ position: TP, point: { pixelSize: 6, color: Cesium.Color.RED }, label: { text: "台北", font: "12px sans-serif",
      fillColor: Cesium.Color.WHITE, pixelOffset: new Cesium.Cartesian2(8, 8), horizontalOrigin: Cesium.HorizontalOrigin.LEFT } }));

    // 慢動作播放：影子（半影）掃過台北的前後
    var wPlay = Math.max(2, 3 * rp / vperp), clk = viewer.clock;
    clk.startTime = JD.addSeconds(t0, -wPlay, new JD()); clk.stopTime = JD.addSeconds(t0, wPlay, new JD());
    clk.currentTime = JD.clone(clk.startTime); clk.clockRange = Cesium.ClockRange.LOOP_STOP;
    clk.multiplier = 2 * wPlay / 15; clk.shouldAnimate = true;
    $("t-speed").value = ""; $("t-play").textContent = "⏸";
    viewer.timeline.zoomTo(clk.startTime, clk.stopTime);
    var range = Math.max(2.5e6, Math.min(h * 1000 * 3.5, 1.2e8));
    viewer.camera.lookAt(TP, new Cesium.HeadingPitchRange(0.6, -0.55, range));
    viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  };

  // 從台北看太陽：以太陽為中心的切平面，每幀畫日面、氣球剪影與遮蔽比例
  function drawSky() {
    if (SDG.tab() !== "balloon" || !sim) return;
    var g = geomCached(viewer.clock.currentTime), cv = $("b-sky"), c = cv.getContext("2d"), W = cv.width, H = cv.height;
    var us = g.us, e1 = unit(cross([0, 0, 1], us)), e2 = cross(us, e1);
    var ox = Math.atan2(dot(g.ub, e1), dot(g.ub, us)) * R2D, oy = Math.atan2(dot(g.ub, e2), dot(g.ub, us)) * R2D;
    var rs = g.alpha / 2 * R2D, rb = Math.asin(Math.min(1, sim.D / 2 / g.dTB)) * R2D, sc = 120 / 1.2;
    var cover = dot(g.ub, us) > 0 ? overlap(rs, rb, Math.hypot(ox, oy)) : 0;
    var lum = 1 - cover;
    c.fillStyle = "rgb(" + Math.round(20 + 71 * lum) + "," + Math.round(30 + 113 * lum) + "," + Math.round(60 + 154 * lum) + ")";
    c.fillRect(0, 0, W, H);
    c.fillStyle = "#fff6c8"; c.beginPath(); c.arc(W / 2, H / 2, rs * sc, 0, 7); c.fill();
    if (Math.abs(ox) < 2 && Math.abs(oy) < 2) {
      c.fillStyle = "#111"; c.beginPath(); c.arc(W / 2 + ox * sc, H / 2 - oy * sc, Math.max(1, rb * sc), 0, 7); c.fill();
    }
    c.fillStyle = "#fff"; c.font = "12px 'Microsoft JhengHei',sans-serif";
    c.fillText("日面被遮 " + (cover * 100).toFixed(cover < 0.01 ? 3 : 1) + "%", 8, 18);
    c.fillText("氣球距日心 " + (Math.hypot(ox, oy) * 60).toFixed(1) + "′", 8, H - 10);
    var dt = JD.secondsDifference(viewer.clock.currentTime, sim.t0);
    $("b-now").textContent = "時間：" + (dt >= 0 ? "+" : "") + dt.toFixed(2) + " 秒（相對於氣球正好在太陽中心前方）";
  }
  var gc = { key: null, g: null };
  function geomCached(t) { var k = t.dayNumber * 86400 + t.secondsOfDay; if (gc.key !== k) { gc.key = k; gc.g = geom(t); } return gc.g; }
  scene.postRender.addEventListener(drawSky);

  document.addEventListener("sdg-tab", function (e) {
    var on = e.detail === "balloon";
    ents.forEach(function (x) { x.show = on; });
    if (on && !sim) {
      var d = JD.toDate(viewer.clock.currentTime), twh = (d.getUTCHours() + 8) % 24;
      if (twh < 8 || twh > 16) {                          // 預設跳到台北今天中午
        var noon = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 4, 0, 0));
        viewer.clock.currentTime = JD.fromDate(noon);
      }
      viewer.clock.shouldAnimate = false; $("t-play").textContent = "▶";
      viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121.5, 23.5, 6e6) });
    }
  });
})();
