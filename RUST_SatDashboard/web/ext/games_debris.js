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

  // games_debris_game.js 透過 window.SDG_DEBRIS 掛上：extend(req) 加入情境軌道與決策卡、onResult(d, req) 做任務判定與儀表板
  var HOOK = window.SDG_DEBRIS = window.SDG_DEBRIS || {};
  function baseReq() {
    var p = $("d-pick").value.split("|");
    return { norad: +($("d-q").value.trim() || p[0]) || 0, mass_kg: +$("d-m").value, n_frag: +$("d-n").value, collision: $("d-kind").value === "1",
      years: +$("d-y").value, accel: +$("d-acc").value, seed: +$("d-seed").value || 1,
      solar: $("d-solar").value, epoch: $("d-epoch").value || undefined };
  }
  HOOK.baseReq = baseReq;
  HOOK.post = function (req) {
    return fetch("/api/games/breakup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) })
      .then(function (r) { return r.json(); });
  };
  // 伺服器忙碌（429）時依 retry_after 倒數後自動重試，最多 10 次
  HOOK.postRetry = function (req, onWait) {
    return new Promise(function (ok, no) {
      (function go(n) {
        HOOK.post(req).then(function (d) {
          if (d.retry_after && n < 10) {
            var left = d.retry_after;
            (function tick() {
              if (onWait) onWait(left);
              if (left-- <= 0) { go(n + 1); return; }
              setTimeout(tick, 1000);
            })();
            return;
          }
          ok(d);
        }).catch(no);
      })(0);
    });
  };
  $("d-run").onclick = function () {
    var btn = this, req = baseReq();
    if (HOOK.extend) req = HOOK.extend(req);
    if (!req.orbit && !req.norad) { SDG.status("請輸入 NORAD 編號或從清單選擇"); return; }
    btn.disabled = true; $("d-res").textContent = "模擬中…（10 年約需數秒）";
    HOOK.postRetry(req, function (left) { $("d-res").textContent = "另一個碎片模擬正在計算（可能是對照組或其他使用者），" + left + " 秒後自動重試…"; })
      .then(function (d) {
        btn.disabled = false;
        if (d.error) { $("d-res").textContent = d.error; return; }
        res = d; t0 = JD.fromDate(new Date(d.t0));
        summary(d); chart(d); evTable(d); build(d); play("3h"); setBadge();
        if (HOOK.onResult) HOOK.onResult(d, req);
      })
      .catch(function (e) { btn.disabled = false; $("d-res").textContent = "模擬失敗：" + e; });
  };

  function summary(d) {
    var s = d.summary, p = d.parent, first = d.frags.filter(function (f) { return f[2] === 1; });
    var lmin = Math.min.apply(null, first.map(function (f) { return f[3]; }));
    var gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
    var num = function (x) { return x < 0.01 ? x.toExponential(1) : x.toFixed(2); };
    var g1 = s.expected_gen1_real != null ? s.expected_gen1_real : s.expected_real;
    var rows = [
      ["母體", p.name + "（" + (p.custom ? "自訂軌道，示意" : "NORAD " + p.norad) + "，高度 " + fmt(p.alt_km) + " km，" + fmt(p.mass_kg) + " kg）"],
      ["解體模型", d.events[0].kind === "explosion" ? "爆炸模型（內部能量：電池、殘餘推進劑；Δv 較小）" : "碰撞模型（外部撞擊：反衛星、衛星互撞；Δv 較大）"],
      ["第一次解體", fmt(first.length) + " 個碎片（最小約 " + (lmin * 100).toFixed(1) + " cm）；之後的碰撞一律用碰撞模型"],
      ["碎片總數", fmt(s.fragments_total) + (s.capped ? "（達 30,000 上限，之後不再產生）" : "") + "，最多 " + gens + " 代"],
      [fmt(d.years, 1) + " 年後仍在軌道", fmt(s.alive_end) + " 個（已再入 " + fmt(s.reentered || 0) + " 個）"],
      ["碰撞（擲骰）", fmt(s.collisions) + " 次" + (d.accel > 1 ? "（碰撞誇張倍率 ×" + fmt(d.accel) + "）" : "（寫實）")],
      ["第一代碎片近似風險", "<b>" + num(g1) + " 次</b>（未加速情境下，第一代碎片撞上現有目錄物件的近似期望次數" + (d.accel > 1 ? "；誇張模式下第一代碎片也會被撞毀，所以略偏低" : "") + "）"],
    ];
    if (d.accel > 1) rows.push(["線性反推（偏高）", num(s.expected_linear != null ? s.expected_linear : s.expected_real) + " 次（全部期望值 ÷ 倍率；誇張模式多出的後代碎片也算進去，未補償連鎖偏差）"]);
    if (d.solar) {
      var so = d.solar, MODE = { series: "隨太陽活動（實測＋預報）", low: "固定：太陽活動低", mid: "固定：太陽活動中等", high: "固定：太陽活動高", static: "舊版靜態大氣" };
      rows.push(["大氣", MODE[so.mode] + (so.f107_mean != null ? "；F10.7 平均 " + Math.round(so.f107_mean) + (so.mode === "series" ? "（" + Math.round(so.f107_min) + "–" + Math.round(so.f107_max) + "）" : "") : "") +
        (so.mode === "series" ? "；太陽活動從 " + so.epoch + " 起算（軌道目錄仍為現況），實測到 " + so.obs_until + "、預報到 " + so.data_until + (so.beyond_data ? "，之後以 11 年週期外推" : "") : "")]);
    }
    if (s.cat_reentered != null) rows.push(["目錄物件再入", fmt(s.cat_reentered) + " 個（火箭體、碎片依 TLE 阻力項衰減；含被撞毀與決策移除）"]);
    rows.push(["計算", d.elapsed_s.toFixed(1) + " 秒（目錄 " + fmt(d.n_catalog) + " 個物件）" + (d.cached ? "，<b>快取結果</b>（5 分鐘內相同參數）" : "")]);
    var valid = d.years > 1 ? "<div style='color:#d29922;margin:2px 0'>📏 已驗證（Cosmos 1408 試射碎片）：第 1 年的碎片存活比例與觀測吻合；<b>一年以後衰減仍偏慢</b>（第 3 年：隨太陽活動大氣 4.9%、舊版靜態大氣 8.2%、觀測 0.9%），所以一年以上的在軌數與期望碰撞<b>偏高</b>，主因是遠地點很高的碎片活太久。碰撞率尚未驗證。</div>" : "";
    if (d.years >= 5) valid += "<div style='color:#d29922;margin:2px 0'>🛰 保守假設：在軌衛星（有效載荷）一律不衰減（假設會維持軌道或由同類補充）。實際上衛星會在任務結束後失效，所以 " + fmt(d.years, 0) + " 年的長期風險可能偏高。</div>";
    $("d-res").innerHTML = "<div style='color:#f2a73b;margin:2px 0'>⚠ 統計模擬，不是碰撞預報：同樣參數換一個亂數種子，碰撞次數就可能不同。</div>" + valid +
      "<table class='kv'>" + rows.map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") + "</table>" +
      "<details style='margin-top:4px'><summary style='cursor:pointer;color:var(--hi)'>怎麼看這個結果？（看到的、真實的、誇張的）</summary>" +
      "<div style='line-height:1.7;margin-top:4px'><b>你看到的是什麼</b>：碎片雲沿軌道拉成環、幾個月內散成殼層；點的顏色代表第幾代碎片，閃光是碰撞。<br>" +
      "<b>什麼接近真實</b>：初始碎片的數量與尺寸分布（NASA 標準解體模型）、軌道擴散、第一年的碎片衰減（Cosmos 1408 驗證吻合）。<br>" +
      "<b>什麼是誇張或簡化</b>：碰撞誇張倍率（只放大碰撞截面）、每步 3 個快照的統計估計、目錄物件依類別取代表質量、靜態大氣（不含太陽活動）、一年以後衰減偏慢（遠地點很高的碎片活太久）、畫面上的碎片軌道不含阻力。</div></details>";
  }

  // 圖例可點擊開關；圖表畫好後存底圖，播放時只疊上目前時間的游標
  var hidden = {};
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
    for (var k = 1; k <= gmax; k++) (function (k) { if (!hidden["g" + k]) line(function (s) { return s.alive[k]; }, GEN_C[k], 1.5); })(k);
    if (!hidden.tot) line(function (s) { return s.alive.reduce(function (x, y) { return x + y; }, 0); }, "#e6edf3", 2.2);
    if (!hidden.col) line(function (s) { return s.collisions; }, "#f2cc60", 1.8, [5, 4]);
    // 決策生效時間：綠色虛線＋圖示
    var ICON = { cleanup: "🧹", derelict: "🚀", avoid: "🛰" };
    d.events.forEach(function (e) {
      if (!ICON[e.kind]) return;
      var x = X(e.t / 86400);
      g.strokeStyle = "#3fb950"; g.lineWidth = 1.5; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x, T); g.lineTo(x, H - B); g.stroke(); g.setLineDash([]);
      g.font = "13px sans-serif"; g.textAlign = "center"; g.fillText(ICON[e.kind], x, H - B - 6);
    });
    g.font = "12px 'Microsoft JhengHei',sans-serif";
    var item = function (key, col, txt) {
      return "<span data-lg='" + key + "' style='cursor:pointer;white-space:nowrap;margin-right:10px;color:" + col + ";" + (hidden[key] ? "opacity:.35;text-decoration:line-through" : "") + "'>" + txt + "</span>";
    };
    var lg = item("tot", "#e6edf3", "━ 在軌碎片總數") + item("col", "#f2cc60", "┅ 累計碰撞");
    for (k = 1; k <= gmax; k++) lg += item("g" + k, GEN_C[k], "━ 第 " + k + " 代");
    $("d-legend").innerHTML = lg + "<span class='hint'>（點圖例可開關" + (d.events.some(function (e) { return ICON[e.kind]; }) ? "；<span style='color:#3fb950'>綠色虛線</span>＝決策生效時間" : "") + "）</span>";
    $("d-legend").querySelectorAll("[data-lg]").forEach(function (el) { el.onclick = function () { hidden[el.dataset.lg] = !hidden[el.dataset.lg]; chart(res); }; });
    cv._base = g.getImageData(0, 0, W, H); cv._X = X; cv._range = [T, H - B]; cv._last = null;
  }
  function cursor() {
    var cv = $("d-chart"); if (!res || !cv._base) return;
    var t = (JD.toDate(viewer.clock.currentTime).getTime() - Date.parse(res.t0)) / 86400000;
    var tmax = res.series[res.series.length - 1].t / 86400;
    if (t < 0 || t > tmax) t = null;
    var key = t == null ? "x" : Math.round(t * 200);
    if (cv._last === key) return; cv._last = key;
    var g = cv.getContext("2d"); g.putImageData(cv._base, 0, 0);
    if (t == null) return;
    var x = cv._X(t); g.strokeStyle = "#f2a73b"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, cv._range[0]); g.lineTo(x, cv._range[1]); g.stroke();
    g.fillStyle = "#f2a73b"; g.font = "12px 'Microsoft JhengHei',sans-serif"; g.textAlign = x > cv.width - 90 ? "right" : "left";
    g.fillText(t < 1 ? (t * 24).toFixed(1) + " 時" : t < 365 ? t.toFixed(0) + " 天" : (t / 365.25).toFixed(1) + " 年", x + (g.textAlign === "left" ? 4 : -4), cv._range[0] + 12);
  }
  // 加速模式提示：疊在地球畫面上，避免把誇張結果當成真實
  var badge = document.createElement("div");
  badge.style.cssText = "position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:3;background:#3d1f00e6;color:#f2c46b;border:1px solid #f2a73b;border-radius:6px;padding:4px 12px;font-size:13px;pointer-events:none;display:none;max-width:90%;text-align:center";
  $("map").appendChild(badge);
  function setBadge() {
    var on = res && res.accel > 1 && SDG.tab() === "debris";
    badge.style.display = on ? "block" : "none";
    var g1 = res && (res.summary.expected_gen1_real != null ? res.summary.expected_gen1_real : res.summary.expected_real);
    if (on) badge.innerHTML = "⚠ 誇張模式：碰撞截面放大 ×" + fmt(res.accel) + "，連鎖遠快於真實；未加速時第一代碎片近似風險 " +
      (g1 < 0.01 ? g1.toExponential(1) : g1.toFixed(2)) + " 次";
  }

  function evTable(d) {
    var ev = d.events.slice(1);
    if (!ev.length) { $("d-ev").textContent = "沒有發生碰撞。寫實倍率下，單一解體事件很難在幾年內引發連鎖；碎片的危險在於長期累積。"; return; }
    var h = "<table class='kv'><tr><td>時間</td><td>目標 ← 撞擊物</td><td>相對速度</td><td>結果</td></tr>";
    var when = function (t) { return t / 86400 < 1 ? (t / 3600).toFixed(1) + " 時" : t / 86400 < 365 ? (t / 86400).toFixed(1) + " 天" : (t / 86400 / 365.25).toFixed(1) + " 年"; };
    ev.slice(0, 40).forEach(function (e) {
      if (e.kind !== "collision") { h += "<tr><td>" + when(e.t) + "</td><td colspan='3' style='color:#3fb950'>🃏 " + e.a + "</td></tr>"; return; }
      h += "<tr><td>" + when(e.t) + "</td><td>" + e.a + " ← " + e.b +
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
    flashes = d.events.filter(function (e) { return e.kind === "collision" || e.kind === "explosion"; }).slice(0, 3000).map(function (e) {
      var p = toFixed(e.pos, gmst(Date.parse(d.t0) + e.t * 1000), new Cesium.Cartesian3());
      return { t: e.t, big: e.catastrophic || e.kind !== "collision", p: flashPC.add({ position: p, pixelSize: 1, color: Cesium.Color.YELLOW, show: false }) };
    });
  }

  // 長期播放提示：畫面上的碎片軌道不含阻力，播放超過 1 年時提醒以統計為準
  var note = document.createElement("div");
  note.style.cssText = "position:absolute;left:10px;bottom:46px;z-index:3;background:#0d1117d9;color:#8b949e;border:1px solid #30363d;border-radius:6px;padding:3px 9px;font-size:12px;pointer-events:none;display:none";
  note.textContent = "畫面軌道為簡化版（未計阻力，低軌碎片看起來偏高）；碎片數與碰撞統計以後端模擬為準";
  $("map").appendChild(note);
  function update() {
    if (!res || SDG.tab() !== "debris") { note.style.display = "none"; return; }
    var now = JD.toDate(viewer.clock.currentTime).getTime(), t = (now - Date.parse(res.t0)) / 1000, g = gmst(now);
    note.style.display = t > 30 * 86400 ? "block" : "none";
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
    setBadge();
    [fragPC, flashPC].forEach(function (p) { if (p) p.show = on; });
    if (bgPC) bgPC.show = on && $("d-bg").checked;
    if (!on) return;
    if (!timer) timer = setInterval(function () { update(); bgTick(); cursor(); }, 250);
    if (!$("d-q").value) $("d-pick").onchange();
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 20, 2.6e7) });
  });
})();
