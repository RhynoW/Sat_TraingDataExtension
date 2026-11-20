/* 太空小遊戲：碎片連鎖（/games 分頁）
 * 後端 /api/games/breakup 回傳每個碎片的出生時刻與根數（含 J2 漂移率）、再入時刻、碰撞事件與時間序列；
 * 前端每秒 4 次以克卜勒方程解出位置（不含阻力衰減，僅以再入時刻移除）、閃光標出解體與碰撞。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, scene = viewer.scene, fmt = SDG.fmt;
  var JD = Cesium.JulianDate, TAU = 2 * Math.PI, MU = 398600.4418;
  var GEN_C = ["#8b949e", "#ffa657", "#ff7b72", "#f778ba", "#bc8cff", "#79c0ff", "#ffffff", "#ffffff"];
  var res = null, t0 = null, fragPC = null, flashPC = null, pts = [], flashes = [], timer = null;

  function gmst(ms) {
    var d = ms / 86400000 + 2440587.5 - 2451545, t = d / 36525;
    return ((280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - t * t * t / 38710000) % 360) * Math.PI / 180;
  }
  function toFixed(r, g, out) {
    var c = Math.cos(g), s = Math.sin(g);
    out.x = (c * r[0] + s * r[1]) * 1000; out.y = (-s * r[0] + c * r[1]) * 1000; out.z = r[2] * 1000;
    return out;
  }
  // 根數 → 慣性位置（km）；f = [id, birth, gen, L, A/M, a, e, i, Ω, ω, M0, Ωdot, ωdot, Mdot]
  function pos(f, t) {
    var dt = t - f[1], a = f[5], e = f[6], inc = f[7];
    var M = ((f[10] + f[13] * dt) % TAU + TAU) % TAU, om = f[8] + f[11] * dt, w = f[9] + f[12] * dt;
    var E = e < 0.8 ? M : Math.PI;
    for (var k = 0; k < 8; k++) E -= (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
    var xp = a * (Math.cos(E) - e), yp = a * Math.sqrt(1 - e * e) * Math.sin(E);
    var co = Math.cos(om), so = Math.sin(om), cw = Math.cos(w), sw = Math.sin(w), ci = Math.cos(inc), si = Math.sin(inc);
    return [xp * (co * cw - so * sw * ci) + yp * (-co * sw - so * cw * ci),
      xp * (so * cw + co * sw * ci) + yp * (-so * sw + co * cw * ci), xp * sw * si + yp * cw * si];
  }

  $("d-n").oninput = function () { $("d-nv").textContent = this.value; };
  $("d-pick").onchange = function () { var p = this.value.split("|"); $("d-q").value = p[0]; $("d-m").value = p[1]; };
  $("d-find").onclick = function () {
    var q = $("d-q").value.trim(); if (q.length < 2) return;
    fetch("/api/search?q=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
      var sel = $("d-pick");
      if (!d.results.length) { SDG.status("找不到「" + q + "」"); return; }
      d.results.slice(0, 20).forEach(function (s, i) {
        var o = document.createElement("option");
        o.value = s.norad_id + "|" + (s.purpose === "火箭體" ? 1500 : s.purpose === "有效載荷" ? 1000 : 10) + "|" + s.name;
        o.textContent = s.name + "（" + s.norad_id + "，約 " + Math.round(s.alt_km) + " km）";
        sel.insertBefore(o, sel.firstChild);
        if (i === 0) { sel.value = o.value; sel.onchange(); }
      });
      SDG.status("找到 " + d.results.length + " 筆；質量依類別預設，請依實際規格修改");
    });
  };

  $("d-run").onclick = function () {
    var btn = this, p = $("d-pick").value.split("|");
    var norad = +($("d-q").value.trim() || p[0]);
    if (!norad) { SDG.status("請輸入 NORAD 編號或從清單選擇"); return; }
    var req = { norad: norad, mass_kg: +$("d-m").value, n_frag: +$("d-n").value, collision: $("d-kind").value === "1",
      years: +$("d-y").value, accel: +$("d-acc").value, seed: +$("d-seed").value || 1 };
    btn.disabled = true; $("d-res").textContent = "模擬中…（10 年約需數秒）";
    fetch("/api/games/breakup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (d.error) { $("d-res").textContent = d.error; return; }
        res = d; t0 = JD.fromDate(new Date(d.t0));
        summary(d); chart(d); evTable(d); build(d); play("3h");
      })
      .catch(function (e) { btn.disabled = false; $("d-res").textContent = "模擬失敗：" + e; });
  };

  function summary(d) {
    var s = d.summary, p = d.parent, first = d.frags.filter(function (f) { return f[2] === 1; });
    var lmin = Math.min.apply(null, first.map(function (f) { return f[3]; }));
    var gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
    var rows = [
      ["母體", p.name + "（NORAD " + p.norad + "，高度 " + fmt(p.alt_km) + " km，" + fmt(p.mass_kg) + " kg）"],
      ["第一次解體", fmt(first.length) + " 個碎片（最小約 " + (lmin * 100).toFixed(1) + " cm）"],
      ["碎片總數", fmt(s.fragments_total) + (s.capped ? "（達 30,000 上限，之後不再產生）" : "") + "，最多 " + gens + " 代"],
      [fmt(d.years, 1) + " 年後仍在軌道", fmt(s.alive_end) + " 個"],
      ["碰撞（擲骰）", fmt(s.collisions) + " 次（加速 ×" + fmt(d.accel) + "）"],
      ["寫實等效期望碰撞", "<b>" + (s.expected_real < 0.01 ? s.expected_real.toExponential(1) : s.expected_real.toFixed(2)) + " 次</b>（期望值 ÷ 加速倍率，未計連鎖放大）"],
      ["計算", d.elapsed_s.toFixed(1) + " 秒（目錄 " + fmt(d.n_catalog) + " 個物件）"],
    ];
    $("d-res").innerHTML = "<table class='kv'>" + rows.map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") + "</table>";
  }

  function chart(d) {
    var cv = $("d-chart"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 56, R = 12, T = 12, B = 30;
    var S = d.series, tmax = S[S.length - 1].t / 86400;
    var ymax = 1; S.forEach(function (s) { var a = s.alive.reduce(function (x, y) { return x + y; }, 0); ymax = Math.max(ymax, a, s.collisions); });
    var lmax = Math.ceil(Math.log10(ymax + 1));
    var X = function (days) { return L + days / tmax * (W - L - R); };
    var Y = function (v) { return T + (1 - Math.log10(Math.max(v, 1)) / lmax) * (H - T - B); };
    g.clearRect(0, 0, W, H); g.font = "12px 'Microsoft JhengHei',sans-serif"; g.strokeStyle = "#30363d"; g.fillStyle = "#8b949e"; g.lineWidth = 1;
    for (var e = 0; e <= lmax; e++) { g.beginPath(); g.moveTo(L, Y(Math.pow(10, e))); g.lineTo(W - R, Y(Math.pow(10, e))); g.stroke(); g.textAlign = "right"; g.fillText(fmt(Math.pow(10, e)), L - 6, Y(Math.pow(10, e)) + 4); }
    var yrs = tmax / 365.25, step = yrs > 20 ? 10 : yrs > 5 ? 2 : yrs > 1.5 ? 1 : 0.25;
    for (var y = 0; y <= yrs + 1e-9; y += step) { g.beginPath(); g.moveTo(X(y * 365.25), T); g.lineTo(X(y * 365.25), H - B); g.stroke(); g.textAlign = "center"; g.fillText(y + " 年", X(y * 365.25), H - B + 16); }
    function line(fn, color, w, dash) {
      g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash || []); g.beginPath();
      S.forEach(function (s, i) { var px = X(s.t / 86400), py = Y(fn(s)); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
      g.stroke(); g.setLineDash([]);
    }
    var gmax = 0; S.forEach(function (s) { s.alive.forEach(function (v, k) { if (v) gmax = Math.max(gmax, k); }); });
    for (var k = 1; k <= gmax; k++) (function (k) { line(function (s) { return s.alive[k]; }, GEN_C[k], 1.5); })(k);
    line(function (s) { return s.alive.reduce(function (x, y) { return x + y; }, 0); }, "#e6edf3", 2.2);
    line(function (s) { return s.collisions; }, "#f2cc60", 1.8, [5, 4]);
    var lg = "<span style='color:#e6edf3'>━ 在軌碎片總數</span>　<span style='color:#f2cc60'>┅ 累計碰撞</span>";
    for (k = 1; k <= gmax; k++) lg += "　<span style='color:" + GEN_C[k] + "'>━ 第 " + k + " 代</span>";
    $("d-legend").innerHTML = lg;
  }

  function evTable(d) {
    var ev = d.events.slice(1);
    if (!ev.length) { $("d-ev").textContent = "沒有發生碰撞。寫實倍率下，單一解體事件很難在幾年內引發連鎖；碎片的危險在於長期累積。"; return; }
    var h = "<table class='kv'><tr><td>時間</td><td>目標 ← 撞擊物</td><td>相對速度</td><td>結果</td></tr>";
    ev.slice(0, 40).forEach(function (e) {
      h += "<tr><td>" + (e.t / 86400 < 1 ? (e.t / 3600).toFixed(1) + " 時" : (e.t / 86400).toFixed(1) + " 天") + "</td><td>" + e.a + " ← " + e.b +
        "</td><td>" + e.v_rel.toFixed(1) + " km/s</td><td>" + (e.catastrophic ? "<b style='color:#ff7b72'>完全解體</b>" : "撞出坑洞") + "，新碎片 " + e.n_new + "</td></tr>";
    });
    if (ev.length > 40) h += "<tr><td colspan='4'>…共 " + fmt(ev.length) + " 次</td></tr>";
    $("d-ev").innerHTML = h + "</table>";
  }

  function build(d) {
    if (fragPC) scene.primitives.remove(fragPC);
    if (flashPC) scene.primitives.remove(flashPC);
    fragPC = scene.primitives.add(new Cesium.PointPrimitiveCollection());
    flashPC = scene.primitives.add(new Cesium.PointPrimitiveCollection());
    pts = d.frags.map(function (f) { return fragPC.add({ pixelSize: 2.5, color: Cesium.Color.fromCssColorString(GEN_C[Math.min(7, f[2])]), show: false }); });
    flashes = d.events.slice(0, 3000).map(function (e) {
      var p = toFixed(e.pos, gmst(Date.parse(d.t0) + e.t * 1000), new Cesium.Cartesian3());
      return { t: e.t, big: e.catastrophic || e.kind !== "collision", p: flashPC.add({ position: p, pixelSize: 1, color: Cesium.Color.YELLOW, show: false }) };
    });
  }

  function update() {
    if (!res || SDG.tab() !== "debris") return;
    var now = JD.toDate(viewer.clock.currentTime).getTime(), t = (now - Date.parse(res.t0)) / 1000, g = gmst(now);
    var c = new Cesium.Cartesian3(), D = res.deaths;
    for (var i = 0; i < pts.length; i++) {
      var f = res.frags[i];
      if (t < f[1] || (D[i] >= 0 && t >= D[i]) || f[5] > 60000) { pts[i].show = false; continue; }
      pts[i].position = toFixed(pos(f, t), g, c); pts[i].show = true;
    }
    var dur = 1.5 * Math.abs(viewer.clock.multiplier);
    flashes.forEach(function (fl) {
      var a = (t - fl.t) / dur;
      if (a < 0 || a > 1) { fl.p.show = false; return; }
      fl.p.show = true; fl.p.pixelSize = (fl.big ? 40 : 18) * (1 - a) + 3;
      fl.p.color = Cesium.Color.fromCssColorString(fl.big ? "#ffdd55" : "#ff9944").withAlpha(1 - a);
    });
  }

  function play(kind) {
    if (!res) return;
    var clk = viewer.clock, secs = { "3h": 3 * 3600, "90d": 90 * 86400, all: res.series[res.series.length - 1].t }[kind];
    clk.startTime = JD.clone(t0); clk.stopTime = JD.addSeconds(t0, secs, new JD()); clk.currentTime = JD.clone(t0);
    clk.clockRange = Cesium.ClockRange.CLAMPED; clk.multiplier = secs / 30; clk.shouldAnimate = true;
    $("t-speed").value = ""; $("t-play").textContent = "⏸";
    viewer.timeline.zoomTo(clk.startTime, clk.stopTime);
    var alt = res.parent.alt_km;
    if (kind === "3h") {                                 // 貼近爆炸點，看碎片雲沿軌道拉長
      var e0 = res.events[0], p0 = toFixed(e0.pos, gmst(Date.parse(res.t0)), new Cesium.Cartesian3());
      viewer.camera.lookAt(p0, new Cesium.HeadingPitchRange(0, -0.9, 9e6));
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    } else viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 20, Math.max(2.2e7, alt * 3.2e4)) });
  }
  document.querySelectorAll("[data-dplay]").forEach(function (b) { b.onclick = function () { play(b.dataset.dplay); }; });

  // 目錄背景（與星座壅擠相同的資料來源）
  var bgPC = null, bgW = null, bgPts = [], bgBusy = false;
  $("d-bg").onchange = function () {
    if (!this.checked) { if (bgPC) bgPC.show = false; return; }
    if (bgPC) { bgPC.show = true; return; }
    bgPC = scene.primitives.add(new Cesium.PointPrimitiveCollection());
    fetch("/api/games/crowd/catalog").then(function (r) { return r.json(); }).then(function (d) {
      var col = Cesium.Color.fromCssColorString("#8b949e").withAlpha(0.35);
      bgPts = d.sats.map(function () { return bgPC.add({ pixelSize: 1.5, color: col, show: false }); });
      bgW = new Worker("/static/js/sat_worker.js");
      bgW.onmessage = function (e) {
        bgBusy = false; var b = e.data.buf, s = new Cesium.Cartesian3();
        for (var i = 0, k = 0; i < bgPts.length; i++, k += 3) {
          if (b[k] !== b[k]) { bgPts[i].show = false; continue; }
          s.x = b[k]; s.y = b[k + 1]; s.z = b[k + 2]; bgPts[i].position = s; bgPts[i].show = true;
        }
      };
      bgW.postMessage({ type: "init", tles: d.sats.map(function (s) { return [s[2], s[3]]; }) });
    });
  };
  function bgTick() {
    if (!bgW || bgBusy || !$("d-bg").checked || SDG.tab() !== "debris") return;
    bgBusy = true; bgW.postMessage({ type: "prop", t: JD.toDate(viewer.clock.currentTime).getTime() });
  }

  document.addEventListener("sdg-tab", function (e) {
    var on = e.detail === "debris";
    [fragPC, flashPC].forEach(function (p) { if (p) p.show = on; });
    if (bgPC) bgPC.show = on && $("d-bg").checked;
    if (!on) return;
    if (!timer) timer = setInterval(function () { update(); bgTick(); }, 250);
    if (!$("d-q").value) $("d-pick").onchange();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 20, 2.6e7) });
  });
})();
