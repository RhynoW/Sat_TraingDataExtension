/* 太空小遊戲：星座壅擠（/games 第二個分頁）
 * - 情境：各星座可改成「假想」N 顆（後端依公開申請殼層產生 Walker 星座），其餘沿用真實目錄
 * - 指標：後端 /api/games/crowd（KD-tree 快照＋氣體動力學接近頻率），前端畫比較表與高度密度剖面
 * - 3D：真實目錄用 satellite.js Web Worker（/static/js/sat_worker.js）；假想星座用內嵌 Worker 解析傳播
 *   （圓軌道＋J2 長期項，與後端同一組公式），每秒更新 4 次，不逐幀內插（十幾萬點時省 CPU） */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, scene = viewer.scene, fmt = SDG.fmt;
  var groups = null, inited = false, last = null;
  var MEGA = { starlink: 100000, kuiper: 20000, qianfan: 10000 };

  // ── 情境表 ──────────────────────────────────────────────────────────────
  function buildTable() {
    $("cr-groups").innerHTML = "<tr><td>星座</td><td>目錄現有</td><td>假想</td><td>顆數</td></tr>" + groups.map(function (g) {
      return "<tr><td><span style='color:" + g.color + "'>●</span> " + g.name + "</td><td>" + fmt(g.real) + "</td>" +
        "<td><input type='checkbox' id='cr-syn-" + g.key + "'></td>" +
        "<td><input type='number' id='cr-n-" + g.key + "' min='0' max='200000' step='100' value='" + g.planned + "' style='width:84px'></td></tr>" +
        "<tr><td colspan='4' class='hint' style='border:0;padding-top:0;white-space:normal'>" + g.note + "（計畫 " + fmt(g.planned) + " 顆）</td></tr>";
    }).join("");
    $("cr-legend").innerHTML = "灰點：其他物件（含碎片、火箭體）；" + groups.map(function (g) {
      return "<span style='color:" + g.color + "'>●</span> " + g.name;
    }).join("、");
  }
  function preset(kind) {
    groups.forEach(function (g) {
      var syn = $("cr-syn-" + g.key), n = $("cr-n-" + g.key);
      if (kind === "now") { syn.checked = false; n.value = g.planned; }
      if (kind === "plan") { syn.checked = true; n.value = g.planned; }
      if (kind === "mega") { syn.checked = !!MEGA[g.key]; n.value = MEGA[g.key] || g.planned; }
    });
  }
  document.querySelectorAll("[data-preset]").forEach(function (b) { b.onclick = function () { preset(b.dataset.preset); }; });

  // ── 計算 ────────────────────────────────────────────────────────────────
  $("cr-run").onclick = function () {
    var btn = this, req = {
      groups: groups.map(function (g) { return { key: g.key, synthetic: $("cr-syn-" + g.key).checked, total: +$("cr-n-" + g.key).value || 0 }; }),
      hours: +$("cr-hours").value, step_s: 60, d_km: 20, skip: +$("cr-skip").value,
    };
    btn.disabled = true; $("cr-res").textContent = "計算中…（快照 " + req.hours * 60 + " 個，十幾萬顆時約需數秒到數十秒）";
    fetch("/api/games/crowd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (d.error) { $("cr-res").textContent = d.error; return; }
        last = d; render(d); chart(d); setSynthetic(d.shells, req.groups);
      })
      .catch(function (e) { btn.disabled = false; $("cr-res").textContent = "計算失敗：" + e; });
  };

  function ratio(a, b) { return b > 0 ? "×" + (a / b).toFixed(a / b >= 10 ? 0 : 1) : "—"; }
  function num(x, n) { return x >= 100 ? fmt(x) : x >= 1 ? fmt(x, 1) : x >= 0.01 ? fmt(x, 3) : x.toExponential(1); }
  function render(d) {
    var b = d.baseline, s = d.scenario;
    // [名稱, 現況, 情境, 現況值, 情境值, 說明]
    var rows = [
      ["物件總數", fmt(b.objects), fmt(s.objects), b.objects, s.objects, "目錄中仍在軌道的衛星、火箭體與碎片，加上情境的假想星座。"],
      ["同時相距 < 20 km 的配對", num(b.pairs_within_d), num(s.pairs_within_d), b.pairs_within_d, s.pairs_within_d, "任一時刻彼此相距不到 20 km 的物件對數（各快照平均）。"],
      ["全系統每天 < 1 km 接近", num(b.enc_day_1km), num(s.enc_day_1km), b.enc_day_1km, s.enc_day_1km, "全部物件每天發生幾次相距不到 1 km 的接近；營運者通常以此量級評估是否避碰。"],
      ["若都不避碰：每年碰撞期望值", num(b.coll_year), num(s.coll_year), b.coll_year, s.coll_year, "假設沒有人做避碰機動、以 10 m 合併半徑估計的年碰撞次數；實際會少很多，用來比較風險倍數。"],
      ["台北天空仰角 > 10° 平均顆數", fmt(b.sky10), fmt(s.sky10), b.sky10, s.sky10, "任一時刻台北上空仰角 10° 以上的物件數（不論是否被照亮）。"],
      ["台北天空仰角 > 30° 平均顆數", fmt(b.sky30), fmt(s.sky30), b.sky30, s.sky30, "同上，仰角 30° 以上。"],
    ];
    // 倍數橫條：對數長度，×1 為 0、×100 以上填滿
    function bar(a, c) {
      if (!(c > 0)) return "—";
      var r = a / c, w = Math.max(2, Math.min(100, Math.log10(Math.max(1, r)) / 2 * 100)), col = r >= 10 ? "#ff7b72" : r >= 3 ? "#f2a73b" : "#58a6ff";
      return "<div style='display:flex;align-items:center;gap:4px'><div style='flex:1;background:#21262d;border-radius:3px;height:9px;min-width:50px'><div style='width:" + w +
        "%;height:100%;background:" + col + ";border-radius:3px'></div></div><b style='color:" + col + ";min-width:36px;text-align:right'>" + ratio(a, c) + "</b></div>";
    }
    var h = "<table class='kv'><tr><td></td><td>現況</td><td>情境</td><td style='width:34%'>倍數</td></tr>" +
      rows.map(function (r) { return "<tr><td title='" + r[5] + "' style='cursor:help;text-decoration:underline dotted'>" + r[0] + "</td><td>" + r[1] + "</td><td><b>" + r[2] + "</b></td><td>" + bar(r[4], r[3]) + "</td></tr>"; }).join("") +
      "</table><div class='hint'>滑鼠移到指標名稱上可看說明；倍數條為對數長度（×100 以上填滿）。</div>";
    h += "<div style='margin-top:6px'>每顆衛星每年 < 1 km 接近次數（約等於需要評估的避碰機動次數）：</div><table class='kv'>" +
      "<tr><td>群組</td><td>現況</td><td>情境</td></tr>";
    var keys = {};
    b.groups.concat(s.groups).forEach(function (g) { keys[g.key] = g.name; });
    Object.keys(keys).forEach(function (k) {
      var gb = b.groups.find(function (g) { return g.key === k; }), gs = s.groups.find(function (g) { return g.key === k; });
      h += "<tr><td>" + keys[k] + "</td><td>" + (gb ? num(gb.per_sat_year_1km) + "（" + fmt(gb.count) + " 顆）" : "—") +
        "</td><td><b>" + (gs ? num(gs.per_sat_year_1km) + "</b>（" + fmt(gs.count) + " 顆）" : "—</b>") + "</td></tr>";
    });
    h += "</table><div class='hint'>取樣 " + d.hours + " 小時、每 " + d.step_s + " 秒一個快照；配對計算：" +
      ["全部都計", "同殼層不計", "同星座不計"][d.skip] + "；計算 " + d.elapsed_s.toFixed(1) + " 秒。</div>";
    $("cr-res").innerHTML = h;
  }

  function chart(d) {
    var cv = $("cr-chart"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 64, R = 12, T = 14, B = 34;
    var alt = d.density.alt_km, A = d.density.baseline, S = d.density.scenario;
    var x0 = 150, x1 = 1400, y0 = -10, y1 = -4;
    var X = function (a) { return L + (a - x0) / (x1 - x0) * (W - L - R); };
    var Y = function (v) { var lv = Math.log10(Math.max(v, 1e-12)); return T + (y1 - Math.max(y0, Math.min(y1, lv))) / (y1 - y0) * (H - T - B); };
    g.clearRect(0, 0, W, H);
    g.font = "12px 'Microsoft JhengHei',sans-serif"; g.fillStyle = "#8b949e"; g.strokeStyle = "#30363d"; g.lineWidth = 1;
    for (var e = y0; e <= y1; e++) {
      g.beginPath(); g.moveTo(L, Y(Math.pow(10, e))); g.lineTo(W - R, Y(Math.pow(10, e))); g.stroke();
      g.textAlign = "right"; g.fillText("1e" + e, L - 6, Y(Math.pow(10, e)) + 4);
    }
    for (var a = 200; a <= x1; a += 200) {
      g.beginPath(); g.moveTo(X(a), T); g.lineTo(X(a), H - B); g.stroke();
      g.textAlign = "center"; g.fillText(a + " km", X(a), H - B + 16);
    }
    function line(arr, color, w) {
      g.strokeStyle = color; g.lineWidth = w; g.beginPath();
      var first = true;
      for (var i = 0; i < alt.length; i++) {
        if (alt[i] > x1) break;
        var px = X(alt[i]), py = Y(arr[i]);
        if (first) { g.moveTo(px, py); first = false; } else g.lineTo(px, py);
      }
      g.stroke();
    }
    line(A, "#8b949e", 1.5); line(S, "#a371f7", 2);
    g.textAlign = "left"; g.fillStyle = "#8b949e"; g.fillText("現況", W - 100, T + 12);
    g.fillStyle = "#a371f7"; g.fillText("情境", W - 56, T + 12);
  }

  // ── 3D 顯示 ─────────────────────────────────────────────────────────────
  var catPC = null, synPC = null, catW = null, synW = null, catGroups = null, catPts = [], synPts = [];
  var busy = { cat: false, syn: false }, replaced = {}, timer = null;
  var WALKER_SRC = [
    "var MU=398600.4418,J2=1.08262668e-3,RE=6378.137,E=[];",
    "function gmst(ms){var d=ms/86400000+2440587.5-2451545,t=d/36525;var g=(280.46061837+360.98564736629*d+0.000387933*t*t-t*t*t/38710000)%360;return g*Math.PI/180;}",
    "onmessage=function(e){var m=e.data;if(m.type==='init'){E=m.els;return;}",
    " var n=E.length/4,out=new Float64Array(n*3),dt=(m.t-m.t0)/1000,g=gmst(m.t),cg=Math.cos(g),sg=Math.sin(g);",
    " for(var i=0;i<n;i++){var a=RE+E[i*4],inc=E[i*4+1],ra0=E[i*4+2],u0=E[i*4+3],nn=Math.sqrt(MU/(a*a*a)),k=1.5*J2*(RE/a)*(RE/a),ci=Math.cos(inc),si=Math.sin(inc);",
    "  var om=ra0-k*nn*ci*dt,u=u0+nn*(1+k*(4*ci*ci-1))*dt,co=Math.cos(om),so=Math.sin(om),cu=Math.cos(u),su=Math.sin(u);",
    "  var x=a*(co*cu-so*su*ci),y=a*(so*cu+co*su*ci),z=a*su*si;",
    "  out[i*3]=(cg*x+sg*y)*1000;out[i*3+1]=(-sg*x+cg*y)*1000;out[i*3+2]=z*1000;}",
    " postMessage({type:'pos',t:m.t,buf:out},[out.buffer]);};",
  ].join("\n");

  function ensureCatalog() {
    if (catPC) return;
    catPC = scene.primitives.add(new Cesium.PointPrimitiveCollection());
    SDG.status("下載全目錄 TLE…");
    fetch("/api/games/crowd/catalog").then(function (r) { return r.json(); }).then(function (d) {
      var col = [Cesium.Color.fromCssColorString("#8b949e").withAlpha(0.55)].concat(groups.map(function (g) { return Cesium.Color.fromCssColorString(g.color); }));
      catGroups = d.sats.map(function (s) { return s[1]; });
      catPts = d.sats.map(function (s) { return catPC.add({ pixelSize: s[1] ? 2.5 : 2, color: col[s[1]], show: false }); });
      catW = new Worker("/static/js/sat_worker.js");
      catW.onmessage = function (e) { busy.cat = false; apply(catPts, e.data.buf, function (i) { var gk = catGroups[i]; return !(gk && replaced[groups[gk - 1].key]); }); };
      catW.postMessage({ type: "init", tles: d.sats.map(function (s) { return [s[2], s[3]]; }) });
      SDG.status("全目錄 " + fmt(d.count) + " 顆（瀏覽器端 SGP4）");
    });
  }
  function apply(pts, buf, visible) {
    var s = new Cesium.Cartesian3(), on = $("cr-show").checked;
    for (var i = 0, k = 0; i < pts.length; i++, k += 3) {
      var x = buf[k];
      if (!on || x !== x || (visible && !visible(i))) { pts[i].show = false; continue; }
      s.x = x; s.y = buf[k + 1]; s.z = buf[k + 2]; pts[i].position = s; pts[i].show = true;
    }
  }
  function setSynthetic(shells, reqGroups) {
    replaced = {};
    reqGroups.forEach(function (g) { if (g.synthetic) replaced[g.key] = true; });
    if (synPC) { scene.primitives.remove(synPC); synPC = null; }
    if (synW) { synW.terminate(); synW = null; }
    synPts = [];
    if (!shells.length) return;
    var els = [], cols = [], cmap = {};
    groups.forEach(function (g) { cmap[g.key] = Cesium.Color.fromCssColorString(g.color); });
    shells.forEach(function (sh) {
      var P = sh.planes, S = sh.per_plane, inc = sh.inc * Math.PI / 180;
      for (var p = 0; p < P; p++) for (var q = 0; q < S; q++) {
        els.push(sh.alt, inc, 2 * Math.PI * p / P, 2 * Math.PI * (q / S + p / (P * S)));
        cols.push(cmap[sh.group]);
      }
    });
    synPC = scene.primitives.add(new Cesium.PointPrimitiveCollection());
    synPts = cols.map(function (c) { return synPC.add({ pixelSize: 2, color: c, show: false }); });
    synW = new Worker(URL.createObjectURL(new Blob([WALKER_SRC], { type: "text/javascript" })));
    synW.t0 = Date.parse(last.t0);
    synW.onmessage = function (e) { busy.syn = false; apply(synPts, e.data.buf); };
    synW.postMessage({ type: "init", els: els });
    busy.syn = false;
  }
  function tick() {
    if (SDG.tab() !== "crowd") return;
    var t = Cesium.JulianDate.toDate(viewer.clock.currentTime).getTime();
    if (catW && !busy.cat) { busy.cat = true; catW.postMessage({ type: "prop", t: t }); }
    if (synW && !busy.syn) { busy.syn = true; synW.postMessage({ type: "prop", t: t, t0: synW.t0 }); }
  }
  $("cr-show").onchange = function () { tick(); };

  document.addEventListener("sdg-tab", function (e) {
    var on = e.detail === "crowd";
    if (catPC) catPC.show = on;
    if (synPC) synPC.show = on;
    if (!on) return;
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 23.7, 3.4e7) });
    viewer.clock.multiplier = 60; $("t-speed").value = "60";   // 低軌一圈約 95 分鐘：1 分鐘／秒看得出運動，不會跳太遠
    if (!inited) {
      inited = true;
      fetch("/api/games/crowd/shells").then(function (r) { return r.json(); }).then(function (d) {
        groups = d.groups; buildTable(); preset("mega"); ensureCatalog();
      });
    }
    if (!timer) timer = setInterval(tick, 250);
  });
})();
