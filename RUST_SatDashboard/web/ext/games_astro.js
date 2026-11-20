/* 太空小遊戲：天文觀測夢魘（/games 分頁）
 * 後端 /api/games/astro 給出曝光期間劃過視野且被照亮的衛星（切平面座標、亮度、角速度）與整夜統計；
 * 前端以光子數合成 CCD 影像：天空背景＋泊松（高斯近似）雜訊＋恆星 PSF＋衛星光跡（通量依停留時間分攤）＋滿井飽和，
 * 再以 asinh 拉伸顯示。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, fmt = SDG.fmt, tw = SDG.tw;
  var JD = Cesium.JulianDate, D2R = Math.PI / 180;
  var ZP = 8e9;                 // 0 等星每秒每平方公尺光子數（V 波段，含效率的概略值）
  var FULL = 1e5, SEEING = 1.5, N = 720;
  var stars = null, last = null;
  var MEGA = [{ key: "starlink", synthetic: true, total: 100000 }, { key: "kuiper", synthetic: true, total: 20000 }, { key: "qianfan", synthetic: true, total: 10000 }];

  function site() { var s = $("s-site").value.split(","); return { lat: +s[0], lon: +s[1], h: +s[2], mu: +s[3] }; }
  function tel() { var t = $("s-tel").value.split(","); return { fov: +t[0], D: +t[1] }; }
  function obsr(s) { return new Astronomy.Observer(s.lat, s.lon, s.h * 1000); }
  // 方位仰角 → 赤經赤緯（當日；以恆星時換算）
  function altaz2radec(alt, az, s, date) {
    var lst = (Astronomy.SiderealTime(date) * 15 + s.lon) * D2R, a = alt * D2R, z = az * D2R, p = s.lat * D2R;
    var dec = Math.asin(Math.sin(a) * Math.sin(p) + Math.cos(a) * Math.cos(p) * Math.cos(z));
    var H = Math.atan2(-Math.sin(z) * Math.cos(a), Math.sin(a) * Math.cos(p) - Math.cos(a) * Math.sin(p) * Math.cos(z));
    return { ra: ((lst - H) / D2R % 360 + 360) % 360, dec: dec / D2R };
  }

  function loadStars() {
    if (stars) return Promise.resolve(stars);
    return fetch("/ext/stars8.json").then(function (r) { return r.json(); }).then(function (d) { stars = d.d; return stars; });
  }

  $("s-dusk").onclick = function () {
    var s = site(), d = JD.toDate(viewer.clock.currentTime);
    var start = new Date(d.getTime() - 6 * 3600e3);
    var ev = Astronomy.SearchAltitude(Astronomy.Body.Sun, obsr(s), -1, start, 2, -13);
    if (ev) { viewer.clock.currentTime = JD.fromDate(ev.date); viewer.clock.shouldAnimate = false; $("t-play").textContent = "▶"; SDG.status("時間設為 " + tw(ev.date) + "（太陽 −13°）"); }
  };

  $("s-run").onclick = function () {
    var btn = this, s = site(), T = tel(), exp = +$("s-exp").value, date = JD.toDate(viewer.clock.currentTime);
    var tg = $("s-target").value, rd;
    if (tg === "altaz") rd = altaz2radec(+$("s-alt").value, +$("s-az").value, s, date);
    else { var q = tg.split(","); rd = { ra: +q[0], dec: +q[1] }; }
    var req = { lat: s.lat, lon: s.lon, h_km: s.h, ra_deg: rd.ra, dec_deg: rd.dec, fov_deg: T.fov, exp_s: exp,
      t: date.toISOString(), groups: $("s-scen").value === "mega" ? MEGA : [], night: true };
    btn.disabled = true; $("s-res").textContent = "計算中…";
    Promise.all([loadStars(), fetch("/api/games/astro", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }).then(function (r) { return r.json(); })])
      .then(function (a) {
        btn.disabled = false;
        var d = a[1]; if (d.error) { $("s-res").textContent = d.error; return; }
        last = { d: d, rd: rd, s: s, T: T, exp: exp };
        render(last); nightChart(d);
      })
      .catch(function (e) { btn.disabled = false; $("s-res").textContent = "計算失敗：" + e; });
  };

  // 簡單可重現亂數
  function rng(seed) { var x = seed >>> 0 || 1; return function () { x ^= x << 13; x ^= x >>> 17; x ^= x << 5; return (x >>> 0) / 4294967296; }; }
  function gauss(r) { return Math.sqrt(-2 * Math.log(Math.max(1e-12, r()))) * Math.cos(2 * Math.PI * r()); }

  function render(L) {
    var d = L.d, T = L.T, exp = L.exp, s = L.s, fov = T.fov;
    var A = Math.PI * T.D * T.D / 4, pix = fov * 3600 / N, pixA = pix * pix;
    // 昏影時天空變亮：太陽高於 −18° 時每度約亮 0.4 等
    var mu = s.mu - Math.max(0, d.sun_alt + 18) * 0.4;
    var sky = ZP * A * Math.pow(10, -0.4 * mu) * pixA * exp, sig = Math.sqrt(sky);
    // 顯示像素＝多個實際像素（約 0.5″）合併：滿井依合併面積放大
    var full = FULL * Math.max(1, Math.pow(pix / 0.5, 2));
    var sp = Math.max(0.6, SEEING / 2.355 / pix);
    var img = new Float32Array(N * N), trail = new Uint8Array(N * N), r = rng(Math.round(L.rd.ra * 1000 + L.rd.dec * 7919));
    for (var i = 0; i < img.length; i++) img[i] = sky + sig * gauss(r);
    function splat(x, y, f, mark) {
      var rad = Math.ceil(3 * sp), x0 = Math.round(x), y0 = Math.round(y), norm = 1 / (2 * Math.PI * sp * sp);
      for (var dy = -rad; dy <= rad; dy++) for (var dx = -rad; dx <= rad; dx++) {
        var px = x0 + dx, py = y0 + dy; if (px < 0 || py < 0 || px >= N || py >= N) continue;
        var v = f * norm * Math.exp(-((px - x) * (px - x) + (py - y) * (py - y)) / (2 * sp * sp));
        img[py * N + px] += v; if (mark && v > 3 * sig) trail[py * N + px] = 1;
      }
    }
    var toPx = function (xd, yd) { return [N / 2 + xd / fov * N, N / 2 - yd / fov * N]; };
    // 星表恆星（gnomonic，與後端同一套切平面；東在左）
    var ra0 = L.rd.ra * D2R, de0 = L.rd.dec * D2R, p = [Math.cos(de0) * Math.cos(ra0), Math.cos(de0) * Math.sin(ra0), Math.sin(de0)];
    var e = [-Math.sin(ra0), Math.cos(ra0), 0], n = [-Math.sin(de0) * Math.cos(ra0), -Math.sin(de0) * Math.sin(ra0), Math.cos(de0)];
    var nst = 0, half = fov / 2 * 1.05;
    for (var k = 0; k < stars.length; k += 3) {
      var ra = stars[k] * D2R, de = stars[k + 1] * D2R, u = [Math.cos(de) * Math.cos(ra), Math.cos(de) * Math.sin(ra), Math.sin(de)];
      var c = u[0] * p[0] + u[1] * p[1] + u[2] * p[2]; if (c < 0.9) continue;
      var x = -(u[0] * e[0] + u[1] * e[1]) / c / D2R, y = (u[0] * n[0] + u[1] * n[1] + u[2] * n[2]) / c / D2R;
      if (Math.abs(x) > half || Math.abs(y) > half) continue;
      var q = toPx(x, y); splat(q[0], q[1], ZP * A * Math.pow(10, -0.4 * stars[k + 2]) * exp); nst++;
    }
    // 8 等以下背景星：N(<m) ≈ 10^(0.36m − 2.9) 顆／平方度，畫到極限星等（或 4 萬顆上限）
    var lim = 8 + 2.5 * Math.log10(ZP * A * Math.pow(10, -3.2) * exp / (5 * sig * 2 * Math.PI * sp * sp));
    var area = fov * fov, faint = 0;
    for (var m = 8.25; m < Math.min(lim, 23); m += 0.5) {
      var cnt = Math.round(area * (Math.pow(10, 0.36 * (m + 0.25) - 2.9) - Math.pow(10, 0.36 * (m - 0.25) - 2.9)));
      if (faint + cnt > 40000) break;
      for (var j = 0; j < cnt; j++) splat(r() * N, r() * N, ZP * A * Math.pow(10, -0.4 * (m + (r() - 0.5) * 0.5)) * exp);
      faint += cnt;
    }
    // 衛星光跡：每一小段的通量 = 每秒光子數 × 段時間，沿線段每 0.5 px 分攤
    var nstep = Math.min(2400, Math.max(8, Math.ceil(exp / 0.25))), dts = exp / nstep, brightest = null;
    d.streaks.forEach(function (st) {
      var rate = ZP * A * Math.pow(10, -0.4 * st.mag);
      if (!brightest || st.mag < brightest.mag) brightest = st;
      for (var k2 = 1; k2 < st.pts.length; k2++) {
        var a = toPx(st.pts[k2 - 1][0], st.pts[k2 - 1][1]), b = toPx(st.pts[k2][0], st.pts[k2][1]);
        var len = Math.hypot(b[0] - a[0], b[1] - a[1]), steps = Math.max(1, Math.ceil(len / 0.5));
        for (var t = 0; t < steps; t++) { var f = (t + 0.5) / steps; splat(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, rate * dts / steps, true); }
      }
    });
    // 顯示：滿井截斷後 asinh 拉伸
    var cv = $("s-img"), g = cv.getContext("2d"), out = g.createImageData(N, N), hi = Math.asinh(Math.min(full - sky, 3000 * sig) / (3 * sig)), lost = 0;
    for (var i2 = 0; i2 < img.length; i2++) {
      var v = Math.min(full, img[i2]), z = Math.max(0, Math.asinh(Math.max(0, v - sky - 2 * sig) / (3 * sig)) / hi), c8 = Math.round(255 * Math.min(1, z * 1.4));
      out.data[i2 * 4] = out.data[i2 * 4 + 1] = out.data[i2 * 4 + 2] = c8; out.data[i2 * 4 + 3] = 255;
      lost += trail[i2];
    }
    g.putImageData(out, 0, 0);
    g.fillStyle = "rgba(255,255,255,.75)"; g.font = "14px 'Microsoft JhengHei',sans-serif";
    g.fillText(fov + "° × " + fov + "°　曝光 " + exp + " 秒　光跡 " + d.streaks.length + " 條", 10, 22);
    var rows = [
      ["拍攝時刻", tw(new Date(d.t0), true) + "（太陽仰角 " + d.sun_alt.toFixed(1) + "°，指向仰角 " + d.point_alt.toFixed(1) + "°）"],
      ["劃過視野", "<b>" + d.streaks.length + " 條光跡</b>（另 " + d.shadowed + " 顆在地影中，看不到）；計算 " + fmt(d.objects) + " 個物件"],
      ["最亮的一條", brightest ? brightest.name + "，" + brightest.mag.toFixed(1) + " 等，角速度 " + (brightest.omega * 3600).toFixed(0) + "″/s" : "—"],
      ["被光跡佔去的像素", (lost / img.length * 100).toFixed(3) + "%"],
      ["背景星", fmt(nst) + " 顆星表恆星＋" + fmt(faint) + " 顆示意背景星（極限約 " + Math.min(lim, 23).toFixed(1) + " 等）"],
      ["天空亮度", mu.toFixed(1) + " 等／平方角秒"],
    ];
    $("s-res").innerHTML = "<table class='kv'>" + rows.map(function (x) { return "<tr><td>" + x[0] + "</td><td>" + x[1] + "</td></tr>"; }).join("") + "</table>";
  }

  function nightChart(d) {
    var cv = $("s-night"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 40, R = 10, T = 12, B = 26;
    var ns = d.night, mx = 1; ns.forEach(function (x) { if (x.n != null) mx = Math.max(mx, x.n); });
    var bw = (W - L - R) / ns.length;
    g.clearRect(0, 0, W, H); g.font = "11px 'Microsoft JhengHei',sans-serif";
    ns.forEach(function (x, i) {
      var px = L + i * bw;
      if (x.n == null) { g.fillStyle = "#161b22"; g.fillRect(px, T, bw, H - T - B); return; }
      var h = x.n / mx * (H - T - B); g.fillStyle = x.sun_alt > -18 ? "#f2a73b" : "#a371f7"; g.fillRect(px + 1, H - B - h, Math.max(1, bw - 2), h);
    });
    g.fillStyle = "#8b949e"; g.textAlign = "right"; g.fillText(mx, L - 4, T + 10); g.fillText("0", L - 4, H - B);
    g.textAlign = "center";
    for (var i = 0; i < ns.length; i += 12) g.fillText(tw(new Date(ns[i].t)).slice(11), L + i * bw + bw / 2, H - 8);
    var vals = ns.filter(function (x) { return x.n != null; }).map(function (x) { return x.n; });
    var withAny = vals.filter(function (v) { return v > 0; }).length;
    $("s-res").innerHTML += "<div style='margin-top:4px'>整夜可拍 " + vals.length + " 張（每 10 分鐘），其中 <b>" + withAny + " 張（" +
      (vals.length ? Math.round(100 * withAny / vals.length) : 0) + "%）至少有一條光跡</b>；橘色柱為天文昏影／晨光時段（太陽 −12° 到 −18°）。</div>";
  }

  document.addEventListener("sdg-tab", function (e) {
    if (e.detail === "astro") { loadStars(); viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(120.87, 23.47, 9e6) }); }
  });
})();
