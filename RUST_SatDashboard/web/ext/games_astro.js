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

  // 依目前畫面設定組出請求；groups 為 null 時依「情境」選單
  function shot(groups, night) {
    var s = site(), T = tel(), exp = +$("s-exp").value, date = JD.toDate(viewer.clock.currentTime);
    var tg = $("s-target").value, rd;
    if (tg === "altaz") rd = altaz2radec(+$("s-alt").value, +$("s-az").value, s, date);
    else { var q = tg.split(","); rd = { ra: +q[0], dec: +q[1] }; }
    var req = { lat: s.lat, lon: s.lon, h_km: s.h, ra_deg: rd.ra, dec_deg: rd.dec, fov_deg: T.fov, exp_s: exp,
      t: date.toISOString(), groups: groups || ($("s-scen").value === "mega" ? MEGA : []), night: night };
    return fetch("/api/games/astro", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.error) throw new Error(d.error); return { d: d, rd: rd, s: s, T: T, exp: exp }; });
  }

  $("s-run").onclick = function () {
    var btn = this;
    btn.disabled = true; $("s-res").textContent = "計算中…";
    Promise.all([loadStars(), shot(null, true)])
      .then(function (a) {
        btn.disabled = false;
        last = a[1];
        render(last, $("s-img"), true); nightChart(last.d); draw3D(last);
      })
      .catch(function (e) { btn.disabled = false; $("s-res").textContent = "計算失敗：" + e.message; });
  };

  // 現況與 10 萬 Starlink 情境同時刻、同指向各拍一張，左右拖曳比較（背景星用同一組亂數，只差在光跡）
  $("s-cmp-run").onclick = function () {
    var btn = this;
    btn.disabled = true; $("s-cmp-res").textContent = "計算中…";
    Promise.all([loadStars(), shot([], false), shot(MEGA, false)])
      .then(function (a) {
        btn.disabled = false; $("s-cmp").hidden = false;
        var ra = render(a[1], $("s-cmp-a"), false), rb = render(a[2], $("s-cmp-b"), false);
        setCmp(+$("s-cmp-x").value);
        var row = function (n, r) { return "<tr><td>" + n + "</td><td>" + r.n + " 條</td><td>" + (r.lost * 100).toFixed(3) + "%</td><td>" + (r.brightest ? r.brightest.mag.toFixed(1) + " 等" : "—") + "</td></tr>"; };
        $("s-cmp-res").innerHTML = "<table class='kv'><tr><td>情境</td><td>光跡</td><td>佔去像素</td><td>最亮</td></tr>" + row("現況", ra) + row("10 萬 Starlink", rb) + "</table>" +
          "<div>光跡變成 <b>" + (ra.n ? (rb.n / ra.n).toFixed(1) + " 倍" : rb.n + " 條（現況 0 條）") + "</b>，佔去的像素變成 <b>" +
          (ra.lost > 0 ? (rb.lost / ra.lost).toFixed(1) + " 倍" : "—") + "</b>。拖曳影像或下方滑桿比較。</div>";
        $("s-cmp").scrollIntoView({ block: "nearest", behavior: "smooth" });
      })
      .catch(function (e) { btn.disabled = false; $("s-cmp-res").textContent = "計算失敗：" + e.message; });
  };
  function setCmp(x) {
    $("s-cmp-b").style.clipPath = "inset(0 0 0 " + x + "%)"; $("s-cmp-line").style.left = x + "%"; $("s-cmp-x").value = x;
  }
  $("s-cmp-x").oninput = function () { setCmp(+this.value); };
  (function () {
    var box = $("s-cmp-box"), drag = false;
    function at(e) { var r = box.getBoundingClientRect(); setCmp(Math.max(0, Math.min(100, (e.clientX - r.left) / r.width * 100))); }
    box.addEventListener("pointerdown", function (e) { drag = true; box.setPointerCapture(e.pointerId); at(e); });
    box.addEventListener("pointermove", function (e) { if (drag) at(e); });
    box.addEventListener("pointerup", function () { drag = false; });
  })();

  // 放大檢視
  $("s-img").onclick = function () {
    if (!this._base) return;
    var lb = $("lightbox"); lb.querySelector("img").src = this.toDataURL(); lb.hidden = false;
  };
  $("lightbox").onclick = function () { this.hidden = true; };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") $("lightbox").hidden = true; });

  // 標出光跡：在原始影像上疊色線與星等標籤（不重算影像）
  var GC = ["#3fb950", "#58a6ff", "#f2a73b", "#ff7b72", "#d2a8ff"];   // 其他、Starlink、Kuiper、千帆、國網
  function mark(cv) {
    if (!cv._base) return;
    var g = cv.getContext("2d"), L = cv._L, fov = L.T.fov;
    g.putImageData(cv._base, 0, 0);
    if (!$("s-mark").checked) return;
    var toPx = function (q) { return [N / 2 + q[0] / fov * N, N / 2 - q[1] / fov * N]; };
    g.save(); g.font = "bold 13px 'Microsoft JhengHei',sans-serif"; g.lineCap = "round";
    L.d.streaks.forEach(function (st) {
      var col = GC[st.group] || GC[0], ps = st.pts.map(toPx);
      g.globalAlpha = 0.5; g.strokeStyle = col; g.lineWidth = 7; g.beginPath();
      ps.forEach(function (p, i) { if (i) g.lineTo(p[0], p[1]); else g.moveTo(p[0], p[1]); }); g.stroke();
      var inside = ps.filter(function (p) { return p[0] > 8 && p[0] < N - 8 && p[1] > 34 && p[1] < N - 8; });
      if (!inside.length) return;
      var p = inside[Math.floor(inside.length / 2)], txt = st.mag.toFixed(1) + " 等 " + st.name.slice(0, 16);
      var tw2 = g.measureText(txt).width, x = Math.max(4, Math.min(N - tw2 - 4, p[0] + 8)), y = Math.max(46, Math.min(N - 6, p[1] - 8));
      g.globalAlpha = 0.75; g.fillStyle = "#000"; g.fillRect(x - 3, y - 13, tw2 + 6, 17);
      g.globalAlpha = 1; g.fillStyle = col; g.fillText(txt, x, y);
    });
    g.restore();
  }
  $("s-mark").onchange = function () { ["s-img", "s-cmp-a", "s-cmp-b"].forEach(function (id) { mark($(id)); }); };

  // 3D：觀測點、望遠鏡視野錐（延伸到最遠一條光跡之外）與被拍到的衛星（第一次進入視野時的位置）
  var ents3 = [];
  function clear3() { ents3.forEach(function (e) { viewer.entities.remove(e); }); ents3 = []; }
  function draw3D(L) {
    clear3();
    var d = L.d, s = L.s, C3 = Cesium.Cartesian3, jd0 = JD.fromDate(new Date(d.t0));
    var M0 = Cesium.Transforms.computeTemeToPseudoFixedMatrix(jd0);
    var ra = L.rd.ra * D2R, de = L.rd.dec * D2R, p = [Math.cos(de) * Math.cos(ra), Math.cos(de) * Math.sin(ra), Math.sin(de)];
    var ne = Math.hypot(p[0], p[1]) || 1, e = [-p[1] / ne, p[0] / ne, 0], n = [p[1] * e[2] - p[2] * e[1], p[2] * e[0] - p[0] * e[2], p[0] * e[1] - p[1] * e[0]];
    var fx = function (v, M) { return C3.normalize(Cesium.Matrix3.multiplyByVector(M || M0, new C3(v[0], v[1], v[2]), new C3()), new C3()); };
    var O = C3.fromDegrees(s.lon, s.lat, s.h * 1000);
    var maxR = d.streaks.reduce(function (m, st) { return Math.max(m, st.range_km); }, 0);
    var R = Math.max(1500, Math.min(40000, maxR * 1.15)) * 1000, t = Math.tan(L.T.fov / 2 * D2R);
    var far = [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(function (c) {
      var v = [p[0] + (e[0] * c[0] + n[0] * c[1]) * t, p[1] + (e[1] * c[0] + n[1] * c[1]) * t, p[2] + (e[2] * c[0] + n[2] * c[1]) * t];
      return C3.add(O, C3.multiplyByScalar(fx(v), R, new C3()), new C3());
    });
    var vio = Cesium.Color.fromCssColorString("#a371f7");
    far.forEach(function (q) { ents3.push(viewer.entities.add({ polyline: { positions: [O, q], width: 1.5, material: vio.withAlpha(0.8), arcType: Cesium.ArcType.NONE } })); });
    ents3.push(viewer.entities.add({ polyline: { positions: far.concat([far[0]]), width: 2, material: vio, arcType: Cesium.ArcType.NONE } }));
    var siteName = $("s-site").selectedOptions[0].textContent.replace(/（.*$/, "");
    ents3.push(viewer.entities.add({ position: O, point: { pixelSize: 9, color: Cesium.Color.YELLOW, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
      label: { text: siteName, font: "13px 'Microsoft JhengHei'", fillColor: Cesium.Color.YELLOW, pixelOffset: new Cesium.Cartesian2(0, 16), style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 2 } }));
    var order = d.streaks.slice().sort(function (a, b) { return a.mag - b.mag; });
    order.forEach(function (st, i) {
      if (!st.r_teme) return;
      var M = Cesium.Transforms.computeTemeToPseudoFixedMatrix(JD.addSeconds(jd0, st.t_s || 0, new JD()));
      var pos = Cesium.Matrix3.multiplyByVector(M, new C3(st.r_teme[0] * 1000, st.r_teme[1] * 1000, st.r_teme[2] * 1000), new C3());
      var col = Cesium.Color.fromCssColorString(GC[st.group] || GC[0]);
      ents3.push(viewer.entities.add({ position: pos, point: { pixelSize: 7, color: col, outlineColor: Cesium.Color.BLACK, outlineWidth: 1 },
        label: i < 8 ? { text: st.name.slice(0, 18) + " " + st.mag.toFixed(1) + "等", font: "12px 'Microsoft JhengHei'", fillColor: col, pixelOffset: new Cesium.Cartesian2(10, -10),
          horizontalOrigin: Cesium.HorizontalOrigin.LEFT, style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 2 } : undefined }));
    });
    // 相機站在觀測點後上方，順著望遠鏡指向看出去
    var dir = fx(p), enu = Cesium.Transforms.eastNorthUpToFixedFrame(O), inv = Cesium.Matrix4.inverseTransformation(enu, new Cesium.Matrix4());
    var loc = Cesium.Matrix4.multiplyByPointAsVector(inv, dir, new C3());
    viewer.camera.lookAt(O, new Cesium.HeadingPitchRange(Math.atan2(loc.x, loc.y), -0.45, R * 1.1));
    viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  }

  // 簡單可重現亂數
  function rng(seed) { var x = seed >>> 0 || 1; return function () { x ^= x << 13; x ^= x >>> 17; x ^= x << 5; return (x >>> 0) / 4294967296; }; }
  function gauss(r) { return Math.sqrt(-2 * Math.log(Math.max(1e-12, r()))) * Math.cos(2 * Math.PI * r()); }

  function render(L, cv, withRes) {
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
    var g = cv.getContext("2d"), out = g.createImageData(N, N), hi = Math.asinh(Math.min(full - sky, 3000 * sig) / (3 * sig)), lost = 0;
    for (var i2 = 0; i2 < img.length; i2++) {
      var v = Math.min(full, img[i2]), z = Math.max(0, Math.asinh(Math.max(0, v - sky - 2 * sig) / (3 * sig)) / hi), c8 = Math.round(255 * Math.min(1, z * 1.4));
      out.data[i2 * 4] = out.data[i2 * 4 + 1] = out.data[i2 * 4 + 2] = c8; out.data[i2 * 4 + 3] = 255;
      lost += trail[i2];
    }
    g.putImageData(out, 0, 0);
    g.fillStyle = "rgba(255,255,255,.75)"; g.font = "14px 'Microsoft JhengHei',sans-serif";
    g.fillText(fov + "° × " + fov + "°　曝光 " + exp + " 秒　光跡 " + d.streaks.length + " 條", 10, 22);
    cv._base = g.getImageData(0, 0, N, N); cv._L = L; mark(cv);
    var rows = [
      ["拍攝時刻", tw(new Date(d.t0), true) + "（太陽仰角 " + d.sun_alt.toFixed(1) + "°，指向仰角 " + d.point_alt.toFixed(1) + "°）"],
      ["劃過視野", "<b>" + d.streaks.length + " 條光跡</b>（另 " + d.shadowed + " 顆在地影中，看不到）；計算 " + fmt(d.objects) + " 個物件"],
      ["最亮的一條", brightest ? brightest.name + "，" + brightest.mag.toFixed(1) + " 等，角速度 " + (brightest.omega * 3600).toFixed(0) + "″/s" : "—"],
      ["被光跡佔去的像素", (lost / img.length * 100).toFixed(3) + "%"],
      ["背景星", fmt(nst) + " 顆星表恆星＋" + fmt(faint) + " 顆示意背景星（極限約 " + Math.min(lim, 23).toFixed(1) + " 等）"],
      ["天空亮度", mu.toFixed(1) + " 等／平方角秒"],
    ];
    if (withRes) $("s-res").innerHTML = "<table class='kv'>" + rows.map(function (x) { return "<tr><td>" + x[0] + "</td><td>" + x[1] + "</td></tr>"; }).join("") + "</table>";
    return { n: d.streaks.length, lost: lost / img.length, brightest: brightest };
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
    var on = e.detail === "astro";
    ents3.forEach(function (x) { x.show = on; });
    if (on) { loadStars(); if (!ents3.length) viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(120.87, 23.47, 9e6) }); }
  });
})();
