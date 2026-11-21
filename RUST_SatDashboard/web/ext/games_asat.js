/* 太空小遊戲：強弓延伸——更強的火箭打得到衛星嗎？（/games 分頁，教育性物理模擬）
 * - 目標：真實 TLE（/api/sat_tle）＋ satellite.js SGP4；座標 TEME，畫面以 GMST 轉地固
 * - 交會機會：未來 12 小時每 20 秒取樣，衛星高度 < 2,500 km 且星下點距發射點 < 2,500 km 的時刻
 * - 求解：燃燒結束點（發射點上空 40 km）→ 交會點，飛行時間 60–900 秒，Lambert（普適變數、二分法）
 *   取相對地面的燃燒結束速度最小且向上飛的解
 * - 沒打到：以時間誤差 δ 延後到達，彈頭沿二體彈道積分到落地 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, fmt = SDG.fmt, tw = SDG.tw;
  var JD = Cesium.JulianDate, MU = 398600.4418, RE = 6378.137, OMEGA = 7.2921159e-5, BO_ALT = 40;
  var satrec = null, satName = "", norad = 25544, opps = [], sel = null, ents = [];

  function norm(a) { return Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]); }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function add(a, b, k) { return [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k]; }

  function site() { var s = $("a-site").value.split(","); return { lat: +s[0], lon: +s[1] }; }
  // 發射點上空 40 km 的 TEME 位置與時刻
  function siteEci(ms) {
    var s = site(), g = satellite.gstime(new Date(ms));
    var e = satellite.geodeticToEcf({ latitude: s.lat * Math.PI / 180, longitude: s.lon * Math.PI / 180, height: BO_ALT });
    return [Math.cos(g) * e.x - Math.sin(g) * e.y, Math.sin(g) * e.x + Math.cos(g) * e.y, e.z];
  }
  function satRV(ms) {
    var pv = satellite.propagate(satrec, new Date(ms));
    if (!pv || !pv.position) return null;
    return { r: [pv.position.x, pv.position.y, pv.position.z], v: [pv.velocity.x, pv.velocity.y, pv.velocity.z] };
  }
  function toFixed(r, ms, out) {
    var g = satellite.gstime(new Date(ms)), c = Math.cos(g), s = Math.sin(g), o = out || new Cesium.Cartesian3();
    o.x = (c * r[0] + s * r[1]) * 1000; o.y = (-s * r[0] + c * r[1]) * 1000; o.z = r[2] * 1000;
    return o;
  }
  function geod(r, ms) {
    var g = satellite.eciToGeodetic({ x: r[0], y: r[1], z: r[2] }, satellite.gstime(new Date(ms)));
    return { lat: g.latitude * 180 / Math.PI, lon: g.longitude * 180 / Math.PI, h: g.height };
  }
  function gc(lat1, lon1, lat2, lon2) {
    var p = Math.PI / 180, a = Math.sin((lat2 - lat1) * p / 2) ** 2 + Math.cos(lat1 * p) * Math.cos(lat2 * p) * Math.sin((lon2 - lon1) * p / 2) ** 2;
    var d = 2 * RE * Math.asin(Math.sqrt(a));
    var y = Math.sin((lon2 - lon1) * p) * Math.cos(lat2 * p), x = Math.cos(lat1 * p) * Math.sin(lat2 * p) - Math.sin(lat1 * p) * Math.cos(lat2 * p) * Math.cos((lon2 - lon1) * p);
    return { d: d, az: (Math.atan2(y, x) / p + 360) % 360 };
  }

  // Lambert（Curtis 普適變數，單圈），二分法解 z
  function stC(z) { return z > 0 ? (1 - Math.cos(Math.sqrt(z))) / z : z < 0 ? (Math.cosh(Math.sqrt(-z)) - 1) / -z : 0.5; }
  function stS(z) {
    if (z > 0) { var s = Math.sqrt(z); return (s - Math.sin(s)) / (s * s * s); }
    if (z < 0) { var q = Math.sqrt(-z); return (Math.sinh(q) - q) / (q * q * q); }
    return 1 / 6;
  }
  function lambert(R1, R2, t, pro) {
    var r1 = norm(R1), r2 = norm(R2), c = cross(R1, R2), th = Math.acos(Math.max(-1, Math.min(1, dot(R1, R2) / (r1 * r2))));
    if (pro ? c[2] < 0 : c[2] >= 0) th = 2 * Math.PI - th;
    var A = Math.sin(th) * Math.sqrt(r1 * r2 / (1 - Math.cos(th)));
    if (!isFinite(A) || Math.abs(A) < 1e-9) return null;
    var y = function (z) { return r1 + r2 + A * (z * stS(z) - 1) / Math.sqrt(stC(z)); };
    var F = function (z) { var yy = y(z); return Math.pow(yy / stC(z), 1.5) * stS(z) + A * Math.sqrt(yy) - Math.sqrt(MU) * t; };
    var lo = -40, hi = 4 * Math.PI * Math.PI - 1e-6;
    while (y(lo) < 0 && lo < hi) lo += 0.5;
    if (F(lo) > 0 || F(hi) < 0) return null;
    for (var k = 0; k < 80; k++) { var m = (lo + hi) / 2; if (F(m) > 0) hi = m; else lo = m; }
    var z = (lo + hi) / 2, yy = y(z), f = 1 - yy / r1, g = A * Math.sqrt(yy / MU), gd = 1 - yy / r2;
    return { v1: [(R2[0] - f * R1[0]) / g, (R2[1] - f * R1[1]) / g, (R2[2] - f * R1[2]) / g],
      v2: [(gd * R2[0] - R1[0]) / g, (gd * R2[1] - R1[1]) / g, (gd * R2[2] - R1[2]) / g] };
  }

  function vertApogee(v) { var r1 = RE + BO_ALT, ra = 1 / (1 / r1 - v * v / (2 * MU)); return ra > 0 ? ra - RE : Infinity; }
  function showV() {
    var v = +$("a-v").value, h = vertApogee(v);
    $("a-vv").textContent = v.toFixed(2) + " km/s（約 " + (v / 0.295).toFixed(1) + " 馬赫）垂直最高 " + (h === Infinity ? "逃逸" : fmt(h) + " km");
  }
  $("a-v").oninput = function () { showV(); if (opps.length) renderOpps(); };
  $("a-dt").oninput = function () { $("a-dtv").textContent = (+this.value).toFixed(2) + " 秒"; };

  $("a-find").onclick = function () {
    var q = $("a-q").value.trim(); if (q.length < 2) return;
    fetch("/api/search?q=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
      var s = $("a-pick"); s.innerHTML = "";
      d.results.slice(0, 30).forEach(function (x) {
        var o = document.createElement("option"); o.value = x.norad_id;
        o.textContent = x.name + "（" + x.norad_id + "，約 " + Math.round(x.alt_km) + " km）"; s.appendChild(o);
      });
      if (!d.results.length) SDG.status("找不到「" + q + "」");
    });
  };

  $("a-solve").onclick = function () {
    norad = +$("a-pick").value || +$("a-q").value;
    $("a-res").textContent = "計算中…";
    fetch("/api/sat_tle?norad_id=" + norad).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { $("a-res").textContent = d.error; return; }
      satrec = satellite.twoline2satrec(d.line1, d.line2); satName = d.name;
      var t0 = JD.toDate(viewer.clock.currentTime).getTime(), s = site(), cand = [];
      for (var k = 0; k < 12 * 180; k++) {
        var ms = t0 + k * 20000, rv = satRV(ms); if (!rv) continue;
        var g = geod(rv.r, ms); if (g.h > 2500) continue;
        var dd = gc(s.lat, s.lon, g.lat, g.lon).d; if (dd > 2500) continue;
        cand.push({ ms: ms, rv: rv, h: g.h, dist: dd });
      }
      opps = [];
      cand.forEach(function (c) {
        var best = null;
        for (var tau = 60; tau <= 900; tau += 30) {
          var R1 = siteEci(c.ms - tau * 1000);
          [true, false].forEach(function (pro) {
            var L = lambert(R1, c.rv.r, tau, pro); if (!L) return;
            var vr = sub(L.v1, [-OMEGA * R1[1], OMEGA * R1[0], 0]), sp = norm(vr);
            if (dot(vr, R1) <= 0) return;                      // 必須向上飛
            if (!best || sp < best.speed) best = { speed: sp, tau: tau, R1: R1, V1: L.v1, V2: L.v2, pro: pro };
          });
        }
        if (best) { best.ms = c.ms; best.h = c.h; best.dist = c.dist; best.vs = c.rv.v; best.rs = c.rv.r; opps.push(best); }
      });
      // 每個過頂只留最省的一個
      var byPass = [];
      opps.sort(function (a, b) { return a.ms - b.ms; }).forEach(function (o) {
        var last = byPass[byPass.length - 1];
        if (last && o.ms - last.ms < 15 * 60e3) { if (o.speed < last.speed) byPass[byPass.length - 1] = o; } else byPass.push(o);
      });
      opps = byPass;
      sel = opps.slice().sort(function (a, b) { return a.speed - b.speed; })[0] || null;
      renderOpps();
    });
  };

  function renderOpps() {
    var v = +$("a-v").value;
    if (!opps.length) { $("a-res").innerHTML = "未來 12 小時 " + satName + " 沒有經過發射點附近（星下點 2,500 km 內、高度 2,500 km 以下）。換一顆低軌衛星試試。"; return; }
    var h = "<div>" + satName + "：未來 12 小時有 " + opps.length + " 次交會機會（點選一列）</div><table class='kv'><tr><td>交會時刻</td><td>高度</td><td>所需速度</td><td>飛行</td></tr>";
    opps.forEach(function (o, i) {
      var ok = v >= o.speed;
      h += "<tr data-i='" + i + "' style='cursor:pointer" + (o === sel ? ";background:#1f2d3d" : "") + "'><td>" + tw(new Date(o.ms), true).slice(5) +
        "</td><td>" + fmt(o.h) + " km</td><td style='color:" + (ok ? "#3fb950" : "#ff7b72") + "'>" + o.speed.toFixed(2) + " km/s</td><td>" + Math.round(o.tau / 60) + " 分</td></tr>";
    });
    h += "</table><div class='hint'>所需速度：<span style='color:#3fb950'>綠色</span>＝目前燃燒結束速度到得了、<span style='color:#ff7b72'>紅色</span>＝速度不足；點選一列看細節與播放。</div>";
    if (sel) {
      var vclose = norm(sub(sel.V2, sel.vs)), vs = norm(sel.vs);
      var ok = v >= sel.speed;
      h += "<table class='kv' style='margin-top:6px'>" + [
        ["結果", ok ? "<b style='color:#3fb950'>速度足夠：理論上到得了交會點</b>" : "<b style='color:#ff7b72'>速度不足：還差 " + (sel.speed - v).toFixed(2) + " km/s</b>"],
        ["強弓對照", "7–10 馬赫約 2.1–3.0 km/s（高空音速計）；這次需要 <b>" + (sel.speed / 0.295).toFixed(1) + " 馬赫</b>"],
        ["發射時刻", tw(new Date(sel.ms - sel.tau * 1000), true) + "（交會前 " + Math.round(sel.tau) + " 秒就要點火）"],
        ["交會高度", fmt(sel.h) + " km，星下點距發射點 " + fmt(sel.dist) + " km"],
        ["衛星速度", vs.toFixed(2) + " km/s；接近速度 <b>" + vclose.toFixed(2) + " km/s</b>"],
        ["瞄準關鍵 1：時間", "晚 0.1 秒，衛星已移動約 " + fmt(vs * 100) + " m"],
        ["瞄準關鍵 2：速度", "燃燒結束速度差 1 m/s，到達時偏約 " + fmt(sel.tau) + " m"],
        ["瞄準關鍵 3：預測", "TLE 位置誤差約 1 km；若靠末段 30 秒修正，需約 " + fmt(1000 / 30) + " m/s 側向機動能力"],
      ].map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") + "</table>";
    }
    $("a-res").innerHTML = h;
    $("a-res").querySelectorAll("tr[data-i]").forEach(function (tr) { tr.onclick = function () { sel = opps[+tr.dataset.i]; renderOpps(); }; });
  }

  // 二體彈道（TEME，RK4，1 秒）：從燃燒結束到落地或 tEnd
  function ballistic(R, V, t0ms, tMax) {
    var out = [], r = R.slice(), v = V.slice(), dt = 1;
    var acc = function (x) { var n = norm(x), k = -MU / (n * n * n); return [x[0] * k, x[1] * k, x[2] * k]; };
    for (var t = 0; t <= tMax; t += dt) {
      out.push([t0ms + t * 1000, r[0], r[1], r[2]]);
      if (norm(r) < RE && t > 10) break;
      var a1 = acc(r), r2 = add(r, v, dt / 2), v2 = add(v, a1, dt / 2), a2 = acc(r2), r3 = add(r, v2, dt / 2), v3 = add(v, a2, dt / 2), a3 = acc(r3);
      var r4 = add(r, v3, dt), v4 = add(v, a3, dt), a4 = acc(r4);
      for (var k = 0; k < 3; k++) { r[k] += dt / 6 * (v[k] + 2 * v2[k] + 2 * v3[k] + v4[k]); v[k] += dt / 6 * (a1[k] + 2 * a2[k] + 2 * a3[k] + a4[k]); }
    }
    return out;
  }
  function clearEnts() { ents.forEach(function (e) { viewer.entities.remove(e); }); ents = []; }

  function fly(cam) {
    if (!sel) { $("a-miss").textContent = "請先找出交會機會。"; return; }
    var v = +$("a-v").value;
    if (v < sel.speed) { $("a-miss").innerHTML = "<span style='color:#ff7b72'>燃燒結束速度不足，無法到達這個交會點。</span>把滑桿調到 " + sel.speed.toFixed(2) + " km/s 以上，或選所需速度較低的一次。"; return; }
    var delta = +$("a-dt").value, tL = sel.ms - sel.tau * 1000 + delta * 1000;
    // 晚 δ 秒發射：整條彈道延後 δ（地球自轉的微小差異略去），到交會點時衛星已經走開
    var traj = ballistic(sel.R1, sel.V1, tL, delta > 0 ? 3600 : sel.tau);
    var hit = delta === 0, miss = null, impact = null;
    if (!hit) {
      var best = Infinity;
      for (var t = -5; t <= 5; t += 0.01) {
        var ms = sel.ms + delta * 1000 + t * 1000, k = Math.round((ms - tL) / 1000);
        if (k < 0 || k >= traj.length) continue;
        var s = satRV(ms); if (!s) continue;
        var d = norm(sub([traj[k][1], traj[k][2], traj[k][3]], s.r)); if (d < best) best = d;
      }
      miss = best;
      var last = traj[traj.length - 1], g = geod([last[1], last[2], last[3]], last[0]), st = site(), p = gc(st.lat, st.lon, g.lat, g.lon);
      impact = { lat: g.lat, lon: g.lon, d: p.d, az: p.az, t: (last[0] - tL) / 1000, landed: norm([last[1], last[2], last[3]]) < RE + 1 };
    }
    // 3D
    clearEnts();
    var fixedLine = traj.map(function (q) { return toFixed([q[1], q[2], q[3]], q[0]); });
    ents.push(viewer.entities.add({ polyline: { positions: fixedLine, width: 2, arcType: Cesium.ArcType.NONE, material: Cesium.Color.fromCssColorString("#ff7b72") } }));
    var sp = [];
    for (var ts = tL - 120e3; ts <= sel.ms + 300e3; ts += 5000) { var s2 = satRV(ts); if (s2) sp.push(toFixed(s2.r, ts)); }
    ents.push(viewer.entities.add({ polyline: { positions: sp, width: 1.5, arcType: Cesium.ArcType.NONE, material: Cesium.Color.fromCssColorString("#79c0ff").withAlpha(0.8) } }));
    var tEnd = traj[traj.length - 1][0];
    ents.push(viewer.entities.add({
      position: new Cesium.CallbackProperty(function (t, out) {
        var ms = JD.toDate(t).getTime(); if (ms < tL || ms > tEnd) return undefined;
        var k = Math.min(traj.length - 1, Math.floor((ms - tL) / 1000)); return toFixed([traj[k][1], traj[k][2], traj[k][3]], traj[k][0], out);
      }, false),
      point: { pixelSize: 8, color: Cesium.Color.fromCssColorString("#ff7b72") }, label: { text: "🚀", font: "16px sans-serif", pixelOffset: new Cesium.Cartesian2(0, -16) },
    }));
    ents.push(viewer.entities.add({
      position: new Cesium.CallbackProperty(function (t, out) {
        var ms = JD.toDate(t).getTime(); if (hit && ms > sel.ms) return undefined;
        var s3 = satRV(ms); return s3 ? toFixed(s3.r, ms, out) : undefined;
      }, false),
      point: { pixelSize: 8, color: Cesium.Color.fromCssColorString("#79c0ff") },
      label: { text: satName, font: "12px sans-serif", fillColor: Cesium.Color.WHITE, pixelOffset: new Cesium.Cartesian2(10, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT },
    }));
    var ip = toFixed(sel.rs, sel.ms);
    ents.push(viewer.entities.add({
      position: ip,
      point: { pixelSize: new Cesium.CallbackProperty(function (t) {
        var a = (JD.toDate(t).getTime() - sel.ms) / 1000 / (2 * Math.abs(viewer.clock.multiplier));
        return hit && a >= 0 && a < 1 ? 40 * (1 - a) + 4 : 0.01;
      }, false), color: Cesium.Color.YELLOW.withAlpha(0.9) },
      label: { text: "交會點", font: "12px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.YELLOW, pixelOffset: new Cesium.Cartesian2(10, 10), horizontalOrigin: Cesium.HorizontalOrigin.LEFT },
    }));
    var st2 = site();
    ents.push(viewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(st2.lon, st2.lat), point: { pixelSize: 6, color: Cesium.Color.LIME }, label: { text: "發射點", font: "12px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.LIME, pixelOffset: new Cesium.Cartesian2(8, 8), horizontalOrigin: Cesium.HorizontalOrigin.LEFT } }));
    if (impact) ents.push(viewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(impact.lon, impact.lat), point: { pixelSize: 9, color: Cesium.Color.ORANGE }, label: { text: "落點", font: "12px 'Microsoft JhengHei',sans-serif", fillColor: Cesium.Color.ORANGE, pixelOffset: new Cesium.Cartesian2(8, 8), horizontalOrigin: Cesium.HorizontalOrigin.LEFT } }));
    // 說明
    if (hit) {
      $("a-miss").innerHTML = "<b style='color:#3fb950'>命中（理想情況）</b>：接近速度 " + norm(sub(sel.V2, sel.vs)).toFixed(1) +
        " km/s 的撞擊會讓衛星完全解體。<button id='a-to-debris' style='margin-left:6px'>到「碎片連鎖」看碎片</button>";
      $("a-to-debris").onclick = function () {
        $("d-q").value = norad; $("d-kind").value = "1"; $("d-m").value = 1000;
        document.querySelector("#tabs button[data-tab=debris]").click();
        SDG.status("已帶入 NORAD " + norad + "、碰撞模型；按「引爆」");
      };
    } else {
      $("a-miss").innerHTML = "<b style='color:#f2a73b'>沒打到</b>：晚 " + delta.toFixed(2) + " 秒點火，最接近時相距 <b>" + fmt(miss * 1000) + " m</b>。<br>" +
        (impact.landed ? "彈頭沿彈道落下，約 " + Math.round(impact.t / 60) + " 分鐘後落在 <b>北緯 " + impact.lat.toFixed(2) + "°、東經 " + impact.lon.toFixed(2) +
          "°</b>，距發射點 " + fmt(impact.d) + " km、方位 " + Math.round(impact.az) + "°（未計大氣阻力，實際會較近）。"
          : "彈頭在 1 小時內沒有落地（速度接近環繞速度，可能短暫繞行後再入）。");
    }
    var clk = viewer.clock;
    clk.startTime = JD.fromDate(new Date(tL - 20e3)); clk.stopTime = JD.fromDate(new Date(Math.max(tEnd, sel.ms + 30e3)));
    clk.currentTime = JD.clone(clk.startTime); clk.clockRange = Cesium.ClockRange.CLAMPED;
    clk.multiplier = (JD.secondsDifference(clk.stopTime, clk.startTime)) / 25; clk.shouldAnimate = true;
    $("t-speed").value = ""; $("t-play").textContent = "⏸";
    viewer.timeline.zoomTo(clk.startTime, clk.stopTime);
    if (cam) {
      viewer.camera.lookAt(Cesium.Cartesian3.fromDegrees(st2.lon, st2.lat), new Cesium.HeadingPitchRange(0.4, -0.6, 4.5e6));
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    }
  }
  $("a-fly").onclick = function () { fly(true); };
  // 播放過一次後，拖動「發射時間誤差」即時重算落點（不移動相機）
  var dtTimer = null;
  $("a-dt").addEventListener("input", function () {
    if (!ents.length || !sel) return;
    clearTimeout(dtTimer); dtTimer = setTimeout(function () { fly(false); }, 200);
  });

  document.addEventListener("sdg-tab", function (e) {
    var on = e.detail === "asat";
    ents.forEach(function (x) { x.show = on; });
    if (on) { showV(); viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 22, 8e6) }); }
  });
})();
