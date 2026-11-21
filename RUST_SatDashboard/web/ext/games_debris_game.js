/* 太空小遊戲：碎片連鎖的遊戲層（/games 💥 分頁）
 * 情境模板（含已不在目錄中的歷史案例，以自訂軌道示意）、任務模式、緩解決策卡與對照組比較、風險儀表板、成就。
 * 透過 window.SDG_DEBRIS（games_debris.js 提供 baseReq、post）掛上 extend(req) 與 onResult(d, req)。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, fmt = SDG.fmt, HOOK = window.SDG_DEBRIS;
  var YEAR = 365.25 * 86400;

  // ── 情境模板（歷史案例為近似教學設定，不是事件重演）────────────────────
  var TPL = {
    envisat: { norad: 27386, mass: 8211, coll: false, n: 1000, years: 10, acc: 1,
      note: "Envisat 2012 年失聯，至今仍在約 770 km 的軌道上；這裡假想殘餘電池或推進劑爆炸。" },
    fy1c: { orbit: { alt_km: 865, inc_deg: 98.8, name: "風雲一號 C（2007 反衛星試驗，示意）" }, mass: 958, coll: true, n: 1000, years: 20, acc: 1,
      note: "2007 年被直升式反衛星飛彈擊毀，編目碎片超過 3,500 個（> 10 cm）。本模擬初始碎片上限 1,000 個；865 km 的碎片壽命以數十年計。" },
    iridium: { orbit: { alt_km: 789, inc_deg: 86.4, name: "Iridium 33 × Cosmos 2251（2009 碰撞，示意）" }, mass: 1510, coll: true, n: 1000, years: 10, acc: 1,
      note: "史上第一次完整衛星互撞。這裡以兩星合計質量（約 560＋950 kg）做單一碰撞解體近似；實際兩星分屬不同軌道面。" },
    c1408: { orbit: { alt_km: 480, inc_deg: 82.6, name: "Cosmos 1408（2021 反衛星試驗，示意）" }, mass: 2200, coll: true, n: 1000, years: 5, acc: 1,
      note: "2021 年被俄羅斯反衛星飛彈擊毀。480 km 的碎片受大氣拖曳，約 2–3 年內大多再入；可和風雲一號 C 對照。" },
  };
  var cur = null;   // 目前套用的模板
  function applyTpl(k) {
    cur = TPL[k] || null;
    $("d-tpl").value = k || "";
    $("d-tpl-note").textContent = cur ? cur.note : "";
    if (!cur) return;
    if (cur.norad) { $("d-q").value = cur.norad; }
    else { $("d-q").value = ""; }
    $("d-m").value = cur.mass; $("d-kind").value = cur.coll ? "1" : "0";
    $("d-n").value = cur.n; $("d-n").oninput();
    $("d-y").value = String(cur.years); $("d-acc").value = String(cur.acc);
  }
  $("d-tpl").onchange = function () { applyTpl(this.value); };
  // 使用者改選目錄衛星時，自動回到「自訂」
  ["d-q", "d-pick"].forEach(function (id) {
    $(id).addEventListener("change", function () { if (cur && cur.orbit) { cur = null; $("d-tpl").value = ""; $("d-tpl-note").textContent = ""; } });
  });
  $("d-find").addEventListener("click", function () { cur = null; $("d-tpl").value = ""; $("d-tpl-note").textContent = ""; });

  // ── 緩解決策卡（預算 3 點）──────────────────────────────────────────────
  var CARDS = [
    { k: "cleanup", icon: "🧹", name: "清理任務", cost: 2, n: 50, times: [[30, "第 30 天"], [365, "第 1 年"], [1095, "第 3 年"]],
      desc: "主動移除碎片衛星：在指定時間移除當時最重的 50 個碎片（大碎片最容易撞出下一代）。" },
    { k: "derelict", icon: "🚀", name: "移除廢棄火箭體", cost: 1, n: 10, times: [[0, "立即"], [365, "第 1 年"]],
      desc: "預防性移除：母體高度 ±100 km 內最接近的 10 個廢棄火箭體（又大又重，被撞會產生大量碎片）。" },
    { k: "avoid", icon: "🛰", name: "避碰機動", cost: 1, times: [[0, "立即"], [365, "第 1 年"]],
      desc: "在軌運作的衛星（有效載荷）對可追蹤（≥ 10 cm）的物件做避碰機動，碰撞率降為一成；小於 10 cm 的碎片追蹤不到、躲不了。" },
  ];
  var BUDGET = 3;
  $("d-cards").innerHTML = CARDS.map(function (c) {
    return "<label class='chk' title='" + c.desc + "'><input type='checkbox' data-card='" + c.k + "'>" + c.icon + " <b>" + c.name + "</b>（" + c.cost + " 點）" +
      "<select data-cardt='" + c.k + "' style='width:auto;margin-left:auto'>" + c.times.map(function (t) { return "<option value='" + t[0] + "'>" + t[1] + "</option>"; }).join("") + "</select></label>" +
      "<div class='hint' style='margin:-2px 0 4px 22px'>" + c.desc + "</div>";
  }).join("") + "<div class='hint' id='d-budget'></div>";
  function picked() {
    return CARDS.filter(function (c) { return document.querySelector("[data-card=" + c.k + "]").checked; });
  }
  function budget() {
    var used = picked().reduce(function (a, c) { return a + c.cost; }, 0);
    CARDS.forEach(function (c) {
      var cb = document.querySelector("[data-card=" + c.k + "]");
      cb.disabled = !cb.checked && used + c.cost > BUDGET;
    });
    $("d-budget").innerHTML = "已用 <b>" + used + " / " + BUDGET + "</b> 點。" + (used ? "引爆後會自動再跑一次「不採取決策」的對照組（同亂數種子）比較。" : "不選就是「什麼都不做」。");
  }
  $("d-cards").addEventListener("change", budget); budget();

  // ── 任務模式 ─────────────────────────────────────────────────────────────
  var MIS = {
    m1: { name: "任務 1：自然清除", goal: "選一個情境或衛星，在<b>寫實 ×1</b> 下讓第一代碎片 <b>5 年內至少一半再入</b>。提示：軌道越低、大氣越濃，碎片清得越快。",
      setup: function () { $("d-y").value = "5"; $("d-acc").value = "1"; },
      judge: function (d, req) {
        if (req.accel !== 1 || d.years < 4.99) return { ok: false, msg: "需要寫實 ×1、模擬 5 年以上。" };
        var n0 = d.frags.filter(function (f) { return f[2] === 1; }).length;
        var s5 = d.series.filter(function (s) { return s.t >= 5 * YEAR - 1; })[0] || d.series[d.series.length - 1];
        var left = s5.alive[1] / Math.max(1, n0);
        return { ok: left <= 0.5, stars: left <= 0.1 ? 3 : left <= 0.25 ? 2 : 1, msg: "5 年後第一代碎片還剩 <b>" + Math.round(left * 100) + "%</b>（" + fmt(s5.alive[1]) + " / " + fmt(n0) + "）" };
      } },
    m2: { name: "任務 2：連鎖觸發者", goal: "在 <b>×1,000 誇張模式</b>、10 年內觸發<b>第 3 代碎片</b>（碎片撞出的碎片再撞出碎片）。用的初始碎片越少，星數越高。",
      setup: function () { $("d-y").value = "10"; $("d-acc").value = "1000"; },
      judge: function (d, req) {
        if (req.accel < 1000) return { ok: false, msg: "需要 ×1,000 以上的碰撞誇張倍率。" };
        var gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
        return { ok: gens >= 3, stars: req.n_frag <= 100 ? 3 : req.n_frag <= 300 ? 2 : 1, msg: "最多到第 <b>" + gens + "</b> 代；初始碎片 " + req.n_frag + " 個" };
      } },
    m3: { name: "任務 3：守護者", goal: "Envisat 在 <b>×1,000 誇張模式</b>下爆炸。用緩解決策卡（預算 3 點），讓 10 年碰撞次數<b>比不採取決策的對照組少一半以上</b>。",
      setup: function () { applyTpl("envisat"); $("d-acc").value = "1000"; $("d-y").value = "10"; },
      judge: function (d, req, base) {
        if (!req.actions || !req.actions.length) return { ok: false, msg: "至少要選一張決策卡。" };
        if (!base) return { pending: true };
        var r = d.summary.collisions / Math.max(1, base.summary.collisions);
        return { ok: r <= 0.5, stars: r <= 0.15 ? 3 : r <= 0.3 ? 2 : 1, msg: "碰撞 " + d.summary.collisions + " 次，對照組 " + base.summary.collisions + " 次（剩 " + Math.round(r * 100) + "%）" };
      } },
  };
  $("d-mission").onchange = function () {
    var m = MIS[this.value];
    $("d-mission-card").hidden = !m; $("d-mission-res").innerHTML = "";
    if (!m) return;
    m.setup();
    $("d-mission-card").innerHTML = "🎯 <b>" + m.name + "</b><br>" + m.goal;
  };

  // ── 成就（存在瀏覽器；無法存取時只在本頁有效）──────────────────────────
  var ACH = [
    ["gen2", "二次碰撞", "首次看到第 2 代碎片"], ["gen3", "連鎖反應", "觸發第 3 代碎片"], ["capped", "凱斯勒失控", "碎片達 3 萬上限"],
    ["clean", "大氣清道夫", "期末碎片全數再入"], ["guard", "守護者", "決策讓碰撞減半"], ["history", "歷史學家", "試過全部 3 個歷史案例"],
    ["m1", "任務 1", "完成自然清除"], ["m2", "任務 2", "完成連鎖觸發者"], ["m3", "任務 3", "完成守護者"],
  ];
  var got = {};
  try { got = JSON.parse(localStorage.getItem("sdg-debris-ach") || "{}") || {}; } catch (e) { got = {}; }
  function save() { try { localStorage.setItem("sdg-debris-ach", JSON.stringify(got)); } catch (e) { /* 私密模式等 */ } }
  function unlock(k) { if (got[k]) return false; got[k] = Date.now(); save(); return true; }
  function drawAch(fresh) {
    var n = ACH.filter(function (a) { return got[a[0]]; }).length;
    $("d-ach").innerHTML = "<div style='margin-bottom:3px'>已解鎖 <b>" + n + " / " + ACH.length + "</b>" + (fresh.length ? "　<span style='color:#f2cc60'>🎉 新成就：" + fresh.join("、") + "</span>" : "") + "</div>" +
      ACH.map(function (a) {
        return "<span title='" + a[2] + "' style='display:inline-block;margin:2px 4px 2px 0;padding:1px 7px;border-radius:10px;border:1px solid " +
          (got[a[0]] ? "#f2cc60;color:#f2cc60" : "#30363d;color:#6e7681") + "'>" + (got[a[0]] ? "🏅 " : "🔒 ") + a[1] + "</span>";
      }).join("");
  }
  drawAch([]);

  // ── 風險儀表板 ───────────────────────────────────────────────────────────
  var GEN_C = ["#8b949e", "#ffa657", "#ff7b72", "#f778ba", "#bc8cff", "#79c0ff", "#ffffff", "#ffffff"];
  function dash(d) {
    var R = 6378.137, s = d.summary, h = "";
    // 1. 風險最高的目錄物件
    if (d.risk_top && d.risk_top.length) {
      h += "<div style='margin-top:2px'><b>風險最高的目錄物件</b>（被所有碎片撞上的累計期望次數，已除回誇張倍率）</div><table class='kv'>" +
        d.risk_top.map(function (r) { return "<tr><td>" + (r.name || "—") + "</td><td>" + r.kind + "，" + fmt(r.alt_km) + " km，" + (r.expected_real < 0.001 ? r.expected_real.toExponential(1) : r.expected_real.toFixed(3)) + " 次</td></tr>"; }).join("") + "</table>";
    }
    // 2. 碰撞熱區高度帶（50 km 一帶）
    var bands = {};
    d.events.forEach(function (e) {
      if (e.kind !== "collision" || !e.pos) return;
      var alt = Math.hypot(e.pos[0], e.pos[1], e.pos[2]) - R, b = Math.floor(alt / 50) * 50;
      bands[b] = (bands[b] || 0) + 1;
    });
    var bk = Object.keys(bands).map(Number).sort(function (a, b) { return bands[b] - bands[a]; }).slice(0, 5), bmax = bk.length ? bands[bk[0]] : 1;
    h += "<div style='margin-top:6px'><b>碰撞熱區高度帶</b></div>" + (bk.length ? bk.map(function (b) {
      return "<div style='display:flex;gap:6px;align-items:center'><span style='min-width:92px'>" + b + "–" + (b + 50) + " km</span><div style='flex:1;background:#21262d;height:9px;border-radius:3px'><div style='width:" +
        Math.round(bands[b] / bmax * 100) + "%;height:100%;background:#ff7b72;border-radius:3px'></div></div><span style='min-width:40px;text-align:right'>" + bands[b] + " 次</span></div>";
    }).join("") : "<div>沒有碰撞。</div>");
    // 3. 期末各代碎片比例
    var last = d.series[d.series.length - 1].alive, tot = last.reduce(function (a, b) { return a + b; }, 0);
    h += "<div style='margin-top:6px'><b>期末各代碎片比例</b>（在軌 " + fmt(tot) + " 個）</div>";
    if (tot) {
      h += "<div style='display:flex;height:12px;border-radius:3px;overflow:hidden'>" + last.map(function (v, k) {
        return v ? "<div title='第 " + k + " 代：" + fmt(v) + " 個' style='width:" + (v / tot * 100) + "%;background:" + GEN_C[k] + "'></div>" : "";
      }).join("") + "</div><div>" + last.map(function (v, k) { return v ? "<span style='color:" + GEN_C[k] + ";margin-right:8px'>第 " + k + " 代 " + Math.round(v / tot * 100) + "%</span>" : ""; }).join("") + "</div>";
    } else h += "<div>碎片已全數再入或被撞毀。</div>";
    // 4. 累計再入
    h += "<div style='margin-top:6px'><b>累計再入</b>：碎片 " + fmt(s.reentered || 0) + " 個（含被撞毀與清理移除）；目錄物件 " + fmt(s.cat_reentered || 0) + " 個</div>";
    $("d-dash").innerHTML = h;
  }

  // ── 掛上主流程 ───────────────────────────────────────────────────────────
  HOOK.extend = function (req) {
    if (cur && cur.orbit) { req.orbit = cur.orbit; req.norad = 0; }
    var acts = picked().map(function (c) {
      var a = { kind: c.k, t_days: +document.querySelector("[data-cardt=" + c.k + "]").value };
      if (c.n) a.n = c.n;
      return a;
    });
    if (acts.length) req.actions = acts;
    return req;
  };
  var tried = {};
  try { tried = JSON.parse(localStorage.getItem("sdg-debris-tpl") || "{}") || {}; } catch (e) { tried = {}; }
  HOOK.onResult = function (d, req) {
    dash(d);
    $("d-compare").innerHTML = "";
    var fresh = [], gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
    var add = function (k) { if (unlock(k)) fresh.push(ACH.filter(function (a) { return a[0] === k; })[0][1]); };
    if (gens >= 2) add("gen2");
    if (gens >= 3) add("gen3");
    if (d.summary.capped) add("capped");
    if (d.summary.alive_end === 0 && d.summary.fragments_total > 0) add("clean");
    if (cur && cur.orbit) {
      tried[$("d-tpl").value] = 1; try { localStorage.setItem("sdg-debris-tpl", JSON.stringify(tried)); } catch (e) { /* 略 */ }
      if (tried.fy1c && tried.iridium && tried.c1408) add("history");
    }
    var mk = $("d-mission").value, m = MIS[mk];
    var finish = function (base) {
      if (m) {
        var r = m.judge(d, req, base);
        if (r.pending) { $("d-mission-res").innerHTML = "<div class='coach'>🎯 對照組計算中，完成後判定…</div>"; return; }
        if (r.ok && unlock(mk)) fresh.push(m.name.slice(0, 4));
        $("d-mission-res").innerHTML = "<div class='coach' style='border-left-color:" + (r.ok ? "#3fb950" : "#ff7b72") + "'>🎯 <b>" + m.name + "：" +
          (r.ok ? "<span style='color:#3fb950'>成功</span> <span style='color:#f2cc60;font-size:15px'>" + "★★★".slice(0, r.stars) + "☆☆☆".slice(0, 3 - r.stars) + "</span>" : "<span style='color:#ff7b72'>未達成</span>") +
          "</b><br>" + r.msg + "</div>";
      }
      drawAch(fresh);
    };
    if (!req.actions) { finish(null); return; }
    // 有決策卡：自動跑對照組（同參數、同亂數種子、不採取決策）
    if (m && m.judge(d, req, null).pending) finish(null);
    $("d-compare").innerHTML = "對照組（不採取決策）計算中…";
    var base = JSON.parse(JSON.stringify(req)); delete base.actions;
    (function tryPost(n) {
      HOOK.post(base).then(function (b) {
        if (b.error) {
          if (/稍候/.test(b.error) && n < 10) { setTimeout(function () { tryPost(n + 1); }, 1500); return; }
          $("d-compare").textContent = "對照組計算失敗：" + b.error; return;
        }
        var row = function (name, x) {
          var g1 = x.summary.expected_gen1_real;
          return "<tr><td>" + name + "</td><td>" + x.summary.collisions + " 次</td><td>" + fmt(x.summary.fragments_total) + "</td><td>" + fmt(x.summary.alive_end) + "</td><td>" + (g1 < 0.01 ? g1.toExponential(1) : g1.toFixed(2)) + "</td></tr>";
        };
        var r = d.summary.collisions / Math.max(1, b.summary.collisions);
        $("d-compare").innerHTML = "<div style='margin-top:6px'><b>🃏 決策效果（與對照組比較）</b></div><table class='kv'><tr><td></td><td>碰撞</td><td>碎片總數</td><td>期末在軌</td><td>第一代寫實期望</td></tr>" +
          row("採取決策", d) + row("對照組", b) + "</table><div>碰撞次數為對照組的 <b>" + Math.round(r * 100) + "%</b>。兩次用同一個亂數種子，但決策會改變後續擲骰，差距小時可能只是運氣；換幾個種子再比較更可靠。</div>";
        if (r <= 0.5 && b.summary.collisions > 0) { if (unlock("guard")) fresh.push("守護者"); }
        finish(b);
      }).catch(function (e) { $("d-compare").textContent = "對照組計算失敗：" + e; });
    })(0);
  };
})();
