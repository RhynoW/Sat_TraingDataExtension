/* 太空小遊戲：太空兵棋（/games 分頁）——海纜中斷下的通訊韌性，紅藍對抗＋白方 GM
 * 伺服器權威（/api/games/war/*），本頁只送命令與顯示；網址帶 ?war=ID&role=…&token=… 可加入同一場。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, fmt = SDG.fmt;
  var ACTS = {
    blue: [["geo_lease", "租用 GEO 頻寬 +15", 2], ["leo_deploy", "部署低軌終端 500 套（+10）", 2], ["repair", "派修纜船（3 回合）", 3, "cut"],
      ["patrol", "海纜區巡邏（切纜成功率 70%→30%，2 回合）", 2], ["anti_jam", "抗干擾（本回合干擾減半）", 2], ["harden", "閘道站資安強化", 1],
      ["isr", "光學偵察（2 次過頂）", 1], ["diplomacy", "公開揭露、外交施壓", 1]],
    red: [["cut_cable", "拖錨切斷海纜（升級 +4）", 2, "intact"], ["jam_leo", "干擾低軌終端（+25%，升級 +2）", 2], ["cyber_gateway", "網攻閘道站（升級 +2）", 2],
      ["dazzle", "雷射致盲光學衛星（升級 +1）", 1], ["propaganda", "認知作戰", 1], ["asat", "反衛星試射（升級 +15，限一次）", 4]],
  };
  var S = { id: null, role: "blue", token: null, tokens: null, st: null, orders: [], cables: [], ents: [], poll: null };

  function api(path, body) {
    return fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined)
      .then(function (r) { return r.json(); });
  }

  $("w-new").onclick = function () {
    S.role = $("w-role").value;
    api("/api/games/war/new", { ai_blue: $("w-ai-blue").value, ai_red: $("w-ai-red").value }).then(function (d) {
      S.id = d.id; S.tokens = d.tokens; S.token = d.tokens[S.role]; S.orders = [];
      drawCables(d.cables_geo);
      var base = location.origin + "/games?war=" + d.id;
      $("w-links").innerHTML = "推演編號 <b>" + d.id + "</b>。加入連結（給對手或 GM，另開分頁）：" +
        ["blue", "red", "white"].map(function (r) { return "<a href='" + base + "&role=" + r + "&token=" + d.tokens[r] + "' target='_blank'>" + { blue: "藍方", red: "紅方", white: "白方" }[r] + "</a>"; }).join("、");
      refresh();
    });
  };

  function drawCables(list) {
    S.ents.forEach(function (e) { viewer.entities.remove(e); }); S.ents = [];
    S.cables = list;
    list.forEach(function (c, i) {
      (c.coords || []).forEach(function (line) {
        var pos = Cesium.Cartesian3.fromDegreesArray([].concat.apply([], line.map(function (p) { return [p[0], p[1]]; })));
        S.ents.push(viewer.entities.add({ polyline: { positions: pos, width: c.intl ? 2.5 : 1.5,
          material: new Cesium.ColorMaterialProperty(new Cesium.CallbackProperty(function () { return color(i); }, false)) }, name: c.name, cableIdx: i }));
      });
    });
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 23.5, 4.5e6) });
  }
  function color(i) {
    var c = S.st && S.st.cables[i];
    if (!c) return Cesium.Color.GRAY;
    return c.cut ? (c.repair_at != null ? Cesium.Color.ORANGE : Cesium.Color.RED) : Cesium.Color.LIME.withAlpha(0.8);
  }

  function refresh() {
    if (!S.id) return;
    api("/api/games/war/state?id=" + S.id + "&role=" + S.role).then(function (st) {
      if (st.error) { $("w-board").textContent = st.error; return; }
      S.st = st; board(); actions(); chart(); log();
      var waiting = !st.over && st.orders[S.role] === "已提交";
      clearInterval(S.poll); S.poll = null;
      if (waiting || (S.role === "white" && !st.over)) S.poll = setInterval(refresh, 2000);
    });
  }

  function board() {
    var st = S.st, c = st.caps, tot = (c.cable || 0) + (c.geo || 0) + (c.leo || 0), cut = st.cables.filter(function (x) { return x.cut; }).length;
    var rows = [
      ["回合", (st.over ? "結束" : (st.turn + 1) + " / " + st.max_turns) + "（每回合 6 小時）"],
      ["國際頻寬需求", fmt(st.demand) + " 單位"],
      ["海纜", fmt(c.cable) + " 單位（" + (st.cables.length - cut) + " / " + st.cables.length + " 條正常；紅＝中斷、橘＝搶修中）"],
    ];
    if (c.geo != null) rows.push(["GEO／低軌", fmt(c.geo, 1) + "／" + fmt(c.leo, 1) + " 單位（終端 " + fmt(st.leo_terms) + " 套，干擾 " + Math.round(st.jam * 100) + "%）"],
      ["可用率", "<b>" + Math.round(Math.min(1, tot / st.demand) * 100) + "%</b>"]);
    else rows.push(["藍方低軌終端（估計）", "約 " + fmt(st.leo_terms) + " 套"]);
    rows.push(["升級指數", st.escalation.toFixed(1) + (st.escalation >= 40 ? "（<b style='color:#ff7b72'>已達國際制裁門檻</b>）" : "")],
      ["低軌碎片", st.debris > 0 ? "<b style='color:#ff7b72'>反衛星碎片已產生</b>（所有低軌星系受影響）" : "無"],
      ["命令", "藍方 " + st.orders.blue + (st.ai.blue ? "（AI）" : "") + "；紅方 " + st.orders.red + (st.ai.red ? "（AI）" : "")]);
    if (st.scores) rows.push(["分數", "平均可用率 " + Math.round(st.scores.mean_avail * 100) + "%、偵察成功 " + st.scores.isr_ok + "/" + st.scores.isr_try +
      "；藍方 " + st.scores.blue.toFixed(0) + "、紅方 " + st.scores.red.toFixed(0)]);
    $("w-board").innerHTML = "<table class='kv'>" + rows.map(function (r) { return "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>"; }).join("") + "</table>";
  }

  function actions() {
    var st = S.st, box = $("w-act");
    if (st.over) { box.innerHTML = "<div class='hint'>推演結束。可看下方紀錄與分數，或開新推演。</div>"; return; }
    if (S.role === "white") {
      box.innerHTML = "<h3>白方事件注入</h3><div class='views'><button data-w='storm'>太陽風暴</button><button data-w='typhoon'>颱風</button><button data-w='ship'>修纜船提前到位</button></div>";
      box.querySelectorAll("[data-w]").forEach(function (b) { b.onclick = function () { api("/api/games/war/orders", { id: S.id, role: "white", token: S.token, white: b.dataset.w }).then(function () { SDG.status("已排入下回合：" + b.textContent); }); }; });
      return;
    }
    var mine = st.orders[S.role] === "已提交";
    var used = S.orders.reduce(function (a, o) { return a + o.cost; }, 0), left = st.ap - used;
    var h = "<h3>" + (S.role === "blue" ? "藍方" : "紅方") + "行動（剩 " + left + " / " + st.ap + " 點）</h3>";
    if (mine) h += "<div class='hint'>已提交，等待對手…</div>";
    else {
      h += "<div class='views'>" + ACTS[S.role].map(function (a, i) {
        return "<button data-a='" + i + "'" + (a[2] > left ? " disabled" : "") + ">" + a[1] + "（" + a[2] + "）</button>";
      }).join("") + "</div>";
      h += "<div class='row'><label>目標海纜</label><select id='w-target'>" + st.cables.map(function (c, i) {
        return "<option value='" + i + "'>" + (c.cut ? "✖ " : "✔ ") + c.name + "</option>";
      }).join("") + "</select></div>";
      h += "<div class='hint'>本回合命令：" + (S.orders.length ? S.orders.map(function (o, i) { return o.label + " <a href='#' data-x='" + i + "'>✕</a>"; }).join("、") : "（無）") + "</div>";
      h += "<div class='row'><button class='go' id='w-submit'>提交命令</button></div>";
    }
    box.innerHTML = h;
    box.querySelectorAll("[data-a]").forEach(function (b) {
      b.onclick = function () {
        var a = ACTS[S.role][+b.dataset.a], o = { kind: a[0], cost: a[2], label: a[1].replace(/（.*$/, "") };
        if (a[3]) {
          var i = +$("w-target").value, c = st.cables[i];
          if (a[3] === "cut" && !c.cut) { SDG.status("修纜要選已中斷的海纜"); return; }
          if (a[3] === "intact" && c.cut) { SDG.status("要選仍正常的海纜"); return; }
          o.arg = i; o.label += "：" + c.name;
        }
        S.orders.push(o); actions();
      };
    });
    box.querySelectorAll("[data-x]").forEach(function (x) { x.onclick = function (e) { e.preventDefault(); S.orders.splice(+x.dataset.x, 1); actions(); }; });
    var sb = $("w-submit");
    if (sb) sb.onclick = function () {
      api("/api/games/war/orders", { id: S.id, role: S.role, token: S.token, actions: S.orders.map(function (o) { return { kind: o.kind, arg: o.arg }; }) })
        .then(function (r) { if (r.error) { SDG.status(r.error); return; } S.orders = []; refresh(); });
    };
  }

  function chart() {
    var H0 = S.st.history, cv = $("w-chart"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 44, R = 44, T = 12, B = 26;
    var ymax = 0; H0.forEach(function (h) { ymax = Math.max(ymax, h.demand || 0, h.cable + h.geo + h.leo); }); ymax = Math.ceil(ymax / 50) * 50;
    var X = function (t) { return L + t / S.st.max_turns * (W - L - R); }, Y = function (v) { return T + (1 - v / ymax) * (H - T - B); };
    g.clearRect(0, 0, W, H); g.font = "11px 'Microsoft JhengHei',sans-serif"; g.fillStyle = "#8b949e"; g.strokeStyle = "#30363d";
    for (var v = 0; v <= ymax; v += 50) { g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - R, Y(v)); g.stroke(); g.textAlign = "right"; g.fillText(v, L - 4, Y(v) + 4); }
    for (var t = 0; t <= S.st.max_turns; t++) { g.textAlign = "center"; g.fillText(t, X(t), H - 8); }
    var blueView = S.role !== "red", bw = (W - L - R) / S.st.max_turns * 0.6;
    H0.forEach(function (h) {
      var x = X(h.turn) - bw / 2, y = H - B;
      [[h.cable, "#3fb950"], [blueView ? h.geo : 0, "#f2a73b"], [blueView ? h.leo : 0, "#58a6ff"]].forEach(function (s) {
        var hh = s[0] / ymax * (H - T - B); g.fillStyle = s[1]; g.fillRect(x, y - hh, bw, hh); y -= hh;
      });
    });
    g.strokeStyle = "#ff7b72"; g.lineWidth = 2; g.beginPath();
    H0.forEach(function (h, i) { var px = X(h.turn), py = Y(h.demand); if (i) g.lineTo(px, py); else g.moveTo(px, py); }); g.stroke(); g.lineWidth = 1;
    $("w-legend").innerHTML = "<span style='color:#3fb950'>■ 海纜</span>" + (blueView ? "　<span style='color:#f2a73b'>■ GEO</span>　<span style='color:#58a6ff'>■ 低軌</span>" : "（紅方看不到藍方的衛星容量）") + "　<span style='color:#ff7b72'>━ 需求</span>";
  }

  function log() {
    var C = { blue: "#79c0ff", red: "#ff7b72", white: "#d2a8ff" };
    $("w-log").innerHTML = S.st.log.slice().reverse().map(function (l) {
      return "<div><span style='color:#8b949e'>第 " + (l.turn + 1) + " 回合</span> <span style='color:" + C[l.side] + "'>" + l.text + "</span></div>";
    }).join("");
  }

  $("w-mc").onclick = function () {
    var btn = this; btn.disabled = true; $("w-mc-res").textContent = "計算中…";
    api("/api/games/war/mc", { runs: +$("w-runs").value, blue: ["balanced", "geo", "leo", "repair"], red: $("w-mc-red").value }).then(function (d) {
      btn.disabled = false;
      var N = { balanced: "均衡", geo: "重 GEO", leo: "重低軌", repair: "重修纜" };
      var best = d.results.slice().sort(function (a, b) { return b.mean_avail - a.mean_avail; })[0];
      $("w-mc-res").innerHTML = "<table class='kv'><tr><td>藍方策略</td><td>平均可用率（95% CI）</td><td>最差 10%</td><td>曾低於 50%</td><td>紅方升級</td></tr>" +
        d.results.map(function (r) {
          return "<tr><td>" + N[r.blue] + "</td><td>" + (r.mean_avail * 100).toFixed(1) + "% ± " + (r.ci95 * 100).toFixed(1) + "</td><td>" + Math.round(r.p10 * 100) +
            "%</td><td>" + Math.round(r.p_low * 100) + "%</td><td>" + r.escalation.toFixed(1) + (r.asat_rate > 0 ? "（反衛星 " + Math.round(r.asat_rate * 100) + "%）" : "") + "</td></tr>";
        }).join("") + "</table><div>各 " + fmt(d.runs) + " 局、同一組亂數種子（共同亂數）比較；目前最佳：<b>" + N[best.blue] + "</b>。差距小於信賴區間時視為平手。</div>";
    });
  };

  // 由加入連結開啟
  var q = new URLSearchParams(location.search);
  if (q.get("war")) {
    S.id = q.get("war"); S.role = q.get("role") || "white"; S.token = q.get("token");
    setTimeout(function () {
      document.querySelector("#tabs button[data-tab=war]").click();
      $("w-role").value = S.role;
      api("/api/games/war/cables?id=" + S.id).then(function (c) { if (!c.error) drawCables(c); refresh(); });
    }, 300);
  }

  document.addEventListener("sdg-tab", function (e) {
    var on = e.detail === "war";
    S.ents.forEach(function (x) { x.show = on; });
    if (on && !S.id) viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 23.5, 4.5e6) });
  });
})();
