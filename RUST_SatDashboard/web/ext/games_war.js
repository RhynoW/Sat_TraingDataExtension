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
  // 行動效果說明（滑鼠移上按鈕時顯示；數值與伺服器裁決一致）
  var DESC = {
    geo_lease: "下回合起 +15 單位頻寬（GEO 上限 60）。不受切纜與低軌干擾影響，是最快的補洞手段。",
    leo_deploy: "下回合起每 500 套終端 +10 單位（上限 4,000 套）。會被紅方干擾與閘道站網攻削弱。",
    repair: "修復下方選定的一條已中斷海纜，3 回合後恢復（颱風時 4 回合）。國際海纜每條 10 單位。",
    patrol: "接下來 2 回合，紅方拖錨切纜的成功率由 70% 降到 30%。",
    anti_jam: "本回合若低軌正被干擾，干擾效果減半。",
    harden: "閘道站完成資安強化後，紅方網攻不再讓低軌容量減半（一次有效到底）。",
    isr: "光學衛星過頂 2 次，每次成功偵察藍方 +3 分；雲量（颱風時更多）與紅方雷射致盲會降低成功率。",
    diplomacy: "公開揭露紅方行為：藍方聲望 +1（計入分數），升級指數 +0.5。",
    cut_cable: "拖錨切斷下方選定的正常海纜：成功率 70%（藍方巡邏時 30%），升級指數 +4。",
    jam_leo: "干擾藍方低軌終端，容量再降 25%（最多 60%），持續 2 回合；升級 +2。",
    cyber_gateway: "網攻低軌閘道站：若藍方未強化，低軌容量減半 2 回合；升級 +2。",
    dazzle: "雷射致盲：本回合藍方光學偵察成功率減半；升級 +1。",
    propaganda: "認知作戰：藍方聲望 −1（影響藍方分數），不增加升級。",
    asat: "直升式反衛星試射（限一次）：低軌碎片大增、所有低軌星系受影響；升級 +15、紅方分數 −10。",
  };
  var S = { id: null, role: "blue", token: null, tokens: null, st: null, orders: [], cables: [], ents: [], poll: null, prevTurn: null, prevCut: 0, noCoach: false };

  function api(path, body) {
    return fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined)
      .then(function (r) { return r.json(); });
  }

  $("w-new").onclick = function () {
    S.role = $("w-role").value;
    api("/api/games/war/new", { ai_blue: $("w-ai-blue").value, ai_red: $("w-ai-red").value }).then(function (d) {
      S.id = d.id; S.tokens = d.tokens; S.token = d.tokens[S.role]; S.orders = []; S.prevTurn = null; S.noCoach = false;
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
    // 距台灣 1,500 km 以外的段落調暗，讓注意力留在台灣周邊
    var near = function (p) {
      var la = p[1] * Math.PI / 180, dl = (p[0] - 121) * Math.PI / 180, l0 = 23.5 * Math.PI / 180;
      return 6371 * Math.acos(Math.min(1, Math.sin(la) * Math.sin(l0) + Math.cos(la) * Math.cos(l0) * Math.cos(dl))) < 1500;
    };
    list.forEach(function (c, i) {
      (c.coords || []).forEach(function (line) {
        var runs = [], cur = null;
        line.forEach(function (p) {
          var nr = near(p);
          if (!cur || cur.near !== nr) { cur = { near: nr, pts: cur ? [cur.pts[cur.pts.length - 1]] : [] }; runs.push(cur); }
          cur.pts.push(p);
        });
        runs.forEach(function (r) {
          if (r.pts.length < 2) return;
          var pos = Cesium.Cartesian3.fromDegreesArray([].concat.apply([], r.pts.map(function (p) { return [p[0], p[1]]; })));
          S.ents.push(viewer.entities.add({ polyline: { positions: pos, width: (c.intl ? 2.5 : 1.5) * (r.near ? 1.2 : 0.8),
            material: new Cesium.PolylineDashMaterialProperty({
              color: new Cesium.CallbackProperty(function () { return color(i, r.near); }, false),
              gapColor: Cesium.Color.TRANSPARENT, dashLength: 14,
              dashPattern: new Cesium.CallbackProperty(function () { var s = S.st && S.st.cables[i]; return s && s.cut ? 0xFF00 : 0xFFFF; }, false),
            }) }, name: c.name, cableIdx: i }));
        });
      });
    });
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 23.5, 4.5e6) });
  }
  // 色盲友善：正常＝藍綠實線、中斷＝紅虛線、搶修中＝橘虛線
  var C_OK = Cesium.Color.fromCssColorString("#39c5cf"), C_CUT = Cesium.Color.fromCssColorString("#ff5c5c"), C_FIX = Cesium.Color.fromCssColorString("#f2a73b");
  function color(i, isNear) {
    var c = S.st && S.st.cables[i], a = isNear ? 1 : 0.3;
    if (!c) return Cesium.Color.GRAY.withAlpha(a);
    return (c.cut ? (c.repair_at != null ? C_FIX : C_CUT) : C_OK).withAlpha((c.cut ? 1 : 0.85) * a);
  }

  function refresh() {
    if (!S.id) return;
    api("/api/games/war/state?id=" + S.id + "&role=" + S.role).then(function (st) {
      if (st.error) { $("w-board").textContent = st.error; return; }
      var prev = S.prevTurn, prevCut = S.prevCut;
      S.st = st; board(); actions(); chart(); log();
      S.prevTurn = st.turn; S.prevCut = st.cables.filter(function (x) { return x.cut; }).length;
      if (prev != null && st.turn > prev && S.role !== "white") summary(prev, prevCut);
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
      ["海纜", fmt(c.cable) + " 單位（" + (st.cables.length - cut) + " / " + st.cables.length + " 條正常；地圖上藍綠實線＝正常、紅虛線＝中斷、橘虛線＝搶修中）"],
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
    if (st.over) {
      box.innerHTML = "<div class='hint'>推演結束。可看下方紀錄與分數，或開新推演。</div>" + (S.role !== "white" ? "<div class='row'><button class='go' id='w-debrief2'>看終局復盤</button></div>" : "");
      if ($("w-debrief2")) $("w-debrief2").onclick = debrief;
      return;
    }
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
      if (!S.noCoach) h += coach(st);
      h += "<div class='views'>" + ACTS[S.role].map(function (a, i) {
        return "<button data-a='" + i + "' title='" + DESC[a[0]] + "'" + (a[2] > left ? " disabled" : "") + ">" + a[1] + "（" + a[2] + "）</button>";
      }).join("") + "</div><div class='hint'>滑鼠移到行動按鈕上可看效果；括號內是行動點數。</div>";
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
    var nc = box.querySelector("[data-nocoach]");
    if (nc) nc.onclick = function (e) { e.preventDefault(); S.noCoach = true; actions(); };
    box.querySelectorAll("[data-x]").forEach(function (x) { x.onclick = function (e) { e.preventDefault(); S.orders.splice(+x.dataset.x, 1); actions(); }; });
    var sb = $("w-submit");
    if (sb) sb.onclick = function () {
      api("/api/games/war/orders", { id: S.id, role: S.role, token: S.token, actions: S.orders.map(function (o) { return { kind: o.kind, arg: o.arg }; }) })
        .then(function (r) { if (r.error) { SDG.status(r.error); return; } S.orders = []; refresh(); });
    };
  }

  // ── 教練提示：依目前局勢挑最多 2 條建議 ──────────────────────────────────
  function coach(st) {
    var tips = [], c = st.caps || {}, tot = (c.cable || 0) + (c.geo || 0) + (c.leo || 0), av = st.demand ? tot / st.demand : 1;
    var unfixed = st.cables.filter(function (x) { return x.cut && x.repair_at == null; }).length;
    var picked = function (k) { return S.orders.some(function (o) { return o.kind === k; }); };
    if (S.role === "blue") {
      if (av < 0.9 && (c.geo || 0) < 60 && !picked("geo_lease")) tips.push("可用率只有 <b>" + Math.round(av * 100) + "%</b>：「租用 GEO 頻寬」下回合就 +15，是最快的補洞方式。");
      if (unfixed > 0 && !picked("repair")) tips.push("有 <b>" + unfixed + " 條海纜中斷且沒人修</b>：在「目標海纜」選一條 ✖ 的，再按「派修纜船」（3 回合後恢復）。");
      if (st.jam > 0 && !picked("anti_jam")) tips.push("低軌正被干擾 <b>" + Math.round(st.jam * 100) + "%</b>：本回合加「抗干擾」可讓干擾減半。");
      if ((st.leo_terms || 0) < 2000 && st.turn <= 4 && !picked("leo_deploy")) tips.push("需求每回合 +5，後期要靠低軌：及早「部署低軌終端」，每 500 套 +10 單位。");
      if (st.turn <= 5 && !picked("patrol")) tips.push("「海纜區巡邏」讓紅方切纜成功率從 70% 降到 30%，持續 2 回合。");
    } else if (S.role === "red") {
      if (st.escalation >= 30) tips.push("升級指數 <b>" + st.escalation.toFixed(1) + "</b>，到 40 就達國際制裁門檻；紅方分數會扣升級指數 × 0.5。");
      if ((st.leo_terms || 0) > 800 && !picked("jam_leo")) tips.push("藍方低軌終端已經不少：「干擾低軌終端」可讓低軌容量再降 25%。");
      if (!picked("cut_cable")) tips.push("切纜最直接壓低藍方可用率，但每次升級 +4；藍方巡邏時成功率只剩 30%。");
      if (!picked("dazzle")) tips.push("「雷射致盲」只花 1 點，可讓藍方本回合偵察成功率減半。");
    }
    if (!tips.length) return "";
    return "<div class='coach'>💡 <b>教練建議</b>（第 " + (st.turn + 1) + " 回合）<a href='#' data-nocoach style='float:right'>不用提示</a><br>" + tips.slice(0, 2).join("<br>") + "</div>";
  }

  // ── 回合結算與終局復盤 ───────────────────────────────────────────────────
  function modal(html) {
    var m = $("w-modal"); m.querySelector(".card").innerHTML = html; m.hidden = false;
    m.onclick = function (e) { if (e.target === m || e.target.dataset.close != null) m.hidden = true; };
  }
  function availAt(t) {
    var h = S.st.history.filter(function (x) { return x.turn === t; })[0];
    if (!h) return null;
    if (h.avail != null) return h.avail;
    return h.demand ? Math.min(1, (h.cable + (h.geo || 0) + (h.leo || 0)) / h.demand) : null;
  }
  function summary(t, prevCut) {
    var st = S.st, C = { blue: "#79c0ff", red: "#ff7b72", white: "#d2a8ff" };
    var logs = st.log.filter(function (l) { return (l.turn === t || l.turn === t + 1) && l.text.indexOf("想定開始") !== 0; });
    var a0 = availAt(t), a1 = availAt(t + 1), cutNow = st.cables.filter(function (x) { return x.cut; }).length;
    var h = "<h2>第 " + (t + 1) + " 回合結算</h2>";
    if (a0 != null && a1 != null && S.role === "blue") {
      var dd = Math.round((a1 - a0) * 100);
      h += "<div class='delta' style='color:" + (dd >= 0 ? "#3fb950" : "#ff7b72") + "'>可用率 " + Math.round(a0 * 100) + "% → " + Math.round(a1 * 100) + "%（" + (dd >= 0 ? "+" : "") + dd + "）</div>";
    }
    h += "<div>海纜中斷 " + prevCut + " → <b>" + cutNow + "</b> 條；升級指數 " + st.escalation.toFixed(1) + "</div>";
    h += "<ul>" + (logs.length ? logs.map(function (l) { return "<li style='color:" + C[l.side] + "'>" + l.text + "</li>"; }).join("") : "<li>這回合沒有特別事件。</li>") + "</ul>";
    if (st.over) {
      h += "<div class='row'><button class='go' id='w-debrief'>看終局復盤</button><button data-close>關閉</button></div>";
      modal(h); $("w-debrief").onclick = debrief;
    } else {
      h += "<div class='row'><button class='go' data-close>繼續第 " + (st.turn + 1) + " 回合</button></div>";
      modal(h);
    }
  }
  function debrief() {
    var st = S.st, sc = st.scores || {};
    var h = "<h2>終局復盤</h2><table class='kv'><tr><td>平均可用率</td><td><b>" + Math.round((sc.mean_avail || 0) * 100) + "%</b>（最低 " + Math.round((sc.min_avail || 0) * 100) + "%）</td></tr>" +
      "<tr><td>偵察成功</td><td>" + (sc.isr_ok || 0) + " / " + (sc.isr_try || 0) + "</td></tr><tr><td>升級指數</td><td>" + st.escalation.toFixed(1) + "</td></tr>" +
      "<tr><td>分數</td><td>藍方 " + (sc.blue || 0).toFixed(0) + "、紅方 " + (sc.red || 0).toFixed(0) + "</td></tr></table>";
    if (S.role !== "blue") {
      modal(h + "<div class='hint' style='margin:6px 0'>紅方的目標是壓低藍方可用率，同時讓升級指數不要過高。</div><div class='row'><button data-close>關閉</button></div>");
      return;
    }
    modal(h + "<div id='w-db-mc' class='hint' style='margin-top:8px'>正在用蒙地卡羅跑 AI 的四種打法（各 300 局）來比較…</div><div class='row'><button data-close>關閉</button></div>");
    var red = st.ai.red || "balanced", N = { balanced: "AI：均衡", geo: "AI：重 GEO", leo: "AI：重低軌", repair: "AI：重修纜" };
    api("/api/games/war/mc", { runs: 300, blue: ["balanced", "geo", "leo", "repair"], red: red }).then(function (d) {
      var rows = d.results.map(function (r) { return { name: N[r.blue], v: r.mean_avail, ci: r.ci95 }; });
      rows.push({ name: "<b>你</b>", v: sc.mean_avail || 0, me: true });
      rows.sort(function (a, b) { return b.v - a.v; });
      var rank = rows.findIndex(function (r) { return r.me; }) + 1;
      var el = $("w-db-mc"); if (!el) return;
      el.innerHTML = "<table class='kv'><tr><td>名次</td><td>打法</td><td>平均可用率</td></tr>" + rows.map(function (r, i) {
        return "<tr" + (r.me ? " style='background:#2a2010'" : "") + "><td>" + (i + 1) + "</td><td>" + r.name + "</td><td>" + (r.v * 100).toFixed(1) + "%" + (r.ci ? " ± " + (r.ci * 100).toFixed(1) : "（這一局）") + "</td></tr>";
      }).join("") + "</table><div style='margin-top:4px'>你在 5 種打法中排第 <b>" + rank + "</b>。AI 數字是對手「" + (red === "escalate" ? "升級" : "灰色地帶") +
        "」下 300 局的平均；你的只有這一局，運氣（切纜成敗、太陽風暴）影響很大，差距在幾個百分點內可視為同一水準。</div>";
    });
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
      [[h.cable, "#39c5cf"], [blueView ? h.geo : 0, "#f2a73b"], [blueView ? h.leo : 0, "#58a6ff"]].forEach(function (s) {
        var hh = s[0] / ymax * (H - T - B); g.fillStyle = s[1]; g.fillRect(x, y - hh, bw, hh); y -= hh;
      });
    });
    g.strokeStyle = "#ff7b72"; g.lineWidth = 2; g.beginPath();
    H0.forEach(function (h, i) { var px = X(h.turn), py = Y(h.demand); if (i) g.lineTo(px, py); else g.moveTo(px, py); }); g.stroke(); g.lineWidth = 1;
    $("w-legend").innerHTML = "<span style='color:#39c5cf'>■ 海纜</span>" + (blueView ? "　<span style='color:#f2a73b'>■ GEO</span>　<span style='color:#58a6ff'>■ 低軌</span>" : "（紅方看不到藍方的衛星容量）") + "　<span style='color:#ff7b72'>━ 需求</span>";
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
