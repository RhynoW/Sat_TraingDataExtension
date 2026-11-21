/* 太空小遊戲：碎片連鎖的遊戲層（/games 💥 分頁）
 * 情境模板（含已不在目錄中的歷史案例，以自訂軌道示意）、任務模式、緩解決策卡與對照組比較、風險儀表板、成就。
 * 透過 window.SDG_DEBRIS（games_debris.js 提供 baseReq、post）掛上 extend(req) 與 onResult(d, req)。
 * 資料表（情境、決策卡、任務、成就）保留中文，顯示時才經 T() 翻譯；線上版切換語言時呼叫 HOOK.relangGame() 重畫。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, fmt = SDG.fmt, HOOK = window.SDG_DEBRIS, T = HOOK.T, TS = HOOK.TS;
  var YEAR = 365.25 * 86400;

  // ── 情境模板（歷史案例為近似教學設定，不是事件重演）────────────────────
  var TPL = {
    envisat: { norad: 27386, mass: 8211, coll: false, n: 1000, years: 10, acc: 1, epoch: "",
      note: "Envisat 2012 年失聯，至今仍在約 770 km 的軌道上；這裡假想殘餘電池或推進劑爆炸。" },
    fy1c: { orbit: { alt_km: 865, inc_deg: 98.8, name: "風雲一號 C 反衛星試驗情境（教學近似）" }, mass: 958, coll: true, n: 1000, years: 20, acc: 1, epoch: "2007-01-11",
      note: "2007 年被直升式反衛星飛彈擊毀，編目碎片超過 3,500 個（> 10 cm）。本模擬初始碎片上限 1,000 個；865 km 的碎片壽命以數十年計。" },
    iridium: { orbit: { alt_km: 789, inc_deg: 86.4, name: "Iridium–Cosmos 碰撞情境（教學近似）" }, mass: 1510, coll: true, n: 1000, years: 10, acc: 1, epoch: "2009-02-10",
      note: "史上第一次完整衛星互撞。教學近似：以兩星合計質量（約 560＋950 kg）在單一圓軌道上做一次碰撞解體；實際兩星分屬不同軌道面，結果不是事件重演。" },
    c1408: { orbit: { alt_km: 480, inc_deg: 82.6, name: "Cosmos 1408 反衛星試驗情境（教學近似）" }, mass: 2200, coll: true, n: 1000, years: 5, acc: 1, epoch: "2021-11-15",
      note: "2021 年被俄羅斯反衛星飛彈擊毀。480 km 的碎片受大氣拖曳，約 2–3 年內大多再入；可和風雲一號 C 對照。" },
  };
  // ── 解體模型：爆炸（內部能量）與碰撞（外部撞擊）分開說明 ─────────────────
  var KIND = {
    "0": "<b>爆炸模型</b>（NASA 標準解體模型）：衛星自身儲存的能量釋放，例如電池破裂、殘餘推進劑爆炸。碎片數 N = 6·Lc<sup>−1.6</sup>，與母體質量無關；" +
      "Δv 較小（log₁₀Δv 平均 = 0.2χ + 1.85，χ = log₁₀ A/M）。適用：失效衛星、火箭上節的自爆。",
    "1": "<b>碰撞模型</b>（NASA 標準解體模型）：被外部物體高速撞擊，例如反衛星飛彈、衛星互撞。碎片數 N = 0.1·M<sup>0.75</sup>·Lc<sup>−1.71</sup>，隨參考質量增加；" +
      "Δv 較大（log₁₀Δv 平均 = 0.9χ + 2.9），碎片散得較開；超過平均 + 1 個標準差的極端 Δv 重抽（依 Cosmos 1408 驗證的經驗修正）。適用：反衛星試射、Iridium–Cosmos 這類互撞。遊戲中所有後續碰撞都用這個模型。",
  };
  // Cosmos 1408（動能反衛星撞擊）衰減驗證：docs/book/sim_validation/cosmos1408/
  var VALID = "📏 驗證（Cosmos 1408 試射碎片，寫實 ×1）：碰撞模型第 1 年存活 25.3%、第 3 年 1.6%（觀測 25.3%、0.9%；v0.1.19，30 個種子中位數）；爆炸模型 43.9%，第 5 年仍剩 13.8%（觀測 0.2%；v0.1.15 驗證報告）。動能撞擊應選碰撞模型。";
  function kindNote() {
    var k = $("d-kind").value, h = T(KIND[k]) + "<br>" + T(VALID);
    if (cur && String(cur.coll ? 1 : 0) !== k)
      h = "<span style='color:#ff7b72'>" + (cur.coll ? T("⚠ 這個情境實際是外部撞擊，應選「碰撞模型」；目前的選擇會讓碎片的散布與衰減和實際不同。") : T("⚠ 這個情境實際是內部爆炸，應選「爆炸模型」；目前的選擇會讓碎片的散布與衰減和實際不同。")) + "</span><br>" + h;
    $("d-kind-note").innerHTML = h;
  }
  $("d-kind").addEventListener("change", kindNote);

  var cur = null;   // 目前套用的模板
  function applyTpl(k) {
    cur = TPL[k] || null;
    $("d-tpl").value = k || "";
    $("d-tpl-note").textContent = cur ? T(cur.note) + (cur.coll ? T("（碰撞模型：外部撞擊）") : T("（爆炸模型：內部能量）")) : "";
    if (!cur) { kindNote(); return; }
    if (cur.norad) { $("d-q").value = cur.norad; }
    else { $("d-q").value = ""; }
    $("d-m").value = cur.mass; $("d-kind").value = cur.coll ? "1" : "0";
    $("d-n").value = cur.n; $("d-n").oninput();
    $("d-y").value = String(cur.years); $("d-acc").value = String(cur.acc);
    $("d-epoch").value = cur.epoch || ""; $("d-solar").value = "series";   // 歷史情境從事件當天的太陽活動起算
    kindNote();
  }
  $("d-tpl").onchange = function () { applyTpl(this.value); };
  setTimeout(kindNote, 0);
  // 使用者改選目錄衛星時，自動回到「自訂」
  ["d-q", "d-pick"].forEach(function (id) {
    $(id).addEventListener("change", function () { if (cur && cur.orbit) { cur = null; $("d-tpl").value = ""; $("d-tpl-note").textContent = ""; } });
  });
  $("d-find").addEventListener("click", function () { cur = null; $("d-tpl").value = ""; $("d-tpl-note").textContent = ""; });

  // ── 緩解決策卡（預算 3 點）──────────────────────────────────────────────
  var CARDS = [
    { k: "cleanup", icon: "🧹", name: "清理任務", cost: 2, n: 50, times: [[30, "第 30 天"], [365, "第 1 年"], [1095, "第 3 年"]],
      desc: "教學簡化：在指定時間移除當時「累計碰撞風險最高」的 50 個碎片（還沒有風險資料時依質量）。實際清除任務一次只能處理少數目標，且要考慮交會可及性。" },
    { k: "derelict", icon: "🚀", name: "移除廢棄火箭體", cost: 1, n: 10, times: [[0, "立即"], [365, "第 1 年"]],
      desc: "教學簡化：移除與母體軌道面相近（傾角差 ≤ 5°、升交點赤經差 ≤ 30°）、高度 ±100 km 內最接近的 10 個廢棄火箭體（又大又重，被撞會產生大量碎片）。實際還要考慮相位、交會幾何與轉移能量。" },
    { k: "avoid", icon: "🛰", name: "避碰機動", cost: 1, times: [[0, "立即"], [365, "第 1 年"]],
      levels: [["low", "基礎 50%", 1], ["std", "標準 10%", 1], ["high", "進階 2%", 2]],
      desc: "簡化避碰假設：運作中的衛星（有效載荷）對可追蹤（≥ 10 cm）的物件避碰。能力分三級：基礎（預警與燃料有限）碰撞機率降至 50%、標準 10%、進階（精密定軌、自動化協調，2 點）2%。實際效果取決於預警能力、燃料、協調與虛警率；小於 10 cm 的碎片追蹤不到、躲不了；已失效的衛星不能避碰。" },
  ];
  var BUDGET = 3;
  function drawCards() {
    // 重畫時保留勾選、能力等級與時間
    var keep = {};
    CARDS.forEach(function (c) {
      var cb = document.querySelector("[data-card=" + c.k + "]");
      if (cb) keep[c.k] = [cb.checked, lvlSel(c) && lvlSel(c).value, document.querySelector("[data-cardt=" + c.k + "]").value];
    });
    $("d-cards").innerHTML = CARDS.map(function (c) {
      return "<label class='chk' title='" + T(c.desc) + "'><input type='checkbox' data-card='" + c.k + "'>" + c.icon + " <b>" + T(c.name) + "</b>" + T("（{0} 點）", c.levels ? "1–2" : c.cost) +
        (c.levels ? "<select data-cardl='" + c.k + "' style='width:auto;margin-left:auto'>" + c.levels.map(function (l) { return "<option value='" + l[0] + "'" + (l[0] === "std" ? " selected" : "") + ">" + T(l[1]) + "</option>"; }).join("") + "</select>" : "") +
        "<select data-cardt='" + c.k + "' style='width:auto;margin-left:" + (c.levels ? "4px" : "auto") + "'>" + c.times.map(function (t) { return "<option value='" + t[0] + "'>" + T(t[1]) + "</option>"; }).join("") + "</select></label>" +
        "<div class='hint' style='margin:-2px 0 4px 22px'>" + T(c.desc) + "</div>";
    }).join("") + "<div class='hint' id='d-budget'></div>";
    CARDS.forEach(function (c) {
      var k = keep[c.k]; if (!k) return;
      document.querySelector("[data-card=" + c.k + "]").checked = k[0];
      if (k[1]) lvlSel(c).value = k[1];
      document.querySelector("[data-cardt=" + c.k + "]").value = k[2];
    });
  }
  drawCards();
  function picked() {
    return CARDS.filter(function (c) { return document.querySelector("[data-card=" + c.k + "]").checked; });
  }
  function lvlSel(c) { return c.levels ? document.querySelector("[data-cardl=" + c.k + "]") : null; }
  function costOf(c) {
    var s = lvlSel(c);
    return s ? c.levels.filter(function (l) { return l[0] === s.value; })[0][2] : c.cost;
  }
  function budget() {
    var used = picked().reduce(function (a, c) { return a + costOf(c); }, 0);
    CARDS.forEach(function (c) {
      var cb = document.querySelector("[data-card=" + c.k + "]"), sel = lvlSel(c);
      if (sel) {   // 預算不夠的能力等級停用；已選的等級超出預算時退回標準
        var room = BUDGET - used + (cb.checked ? costOf(c) : 0);
        Array.prototype.forEach.call(sel.options, function (o) { o.disabled = c.levels.filter(function (l) { return l[0] === o.value; })[0][2] > room; });
        if (sel.selectedOptions[0].disabled) { sel.value = "std"; used = picked().reduce(function (a, x) { return a + costOf(x); }, 0); }
      }
      cb.disabled = !cb.checked && used + costOf(c) > BUDGET;
    });
    $("d-budget").innerHTML = T("已用 <b>{0} / {1}</b> 點。", used, BUDGET) + (used ? T("引爆後會自動再跑一次「不採取決策」的對照組（同亂數種子）比較。") : T("不選就是「什麼都不做」。"));
  }
  $("d-cards").addEventListener("change", budget); budget();

  // ── 任務模式 ─────────────────────────────────────────────────────────────
  var MIS = {
    m1: { name: "任務 1：自然清除", goal: "選一個情境或衛星，在<b>寫實 ×1</b> 下讓第一代碎片 <b>5 年內至少一半再入</b>。提示：軌道越低、大氣越濃，碎片清得越快。",
      setup: function () { $("d-y").value = "5"; $("d-acc").value = "1"; },
      judge: function (d, req) {
        if (req.accel !== 1 || d.years < 4.99) return { ok: false, msg: T("需要寫實 ×1、模擬 5 年以上。") };
        var n0 = d.frags.filter(function (f) { return f[2] === 1; }).length;
        var s5 = d.series.filter(function (s) { return s.t >= 5 * YEAR - 1; })[0] || d.series[d.series.length - 1];
        var left = s5.alive[1] / Math.max(1, n0);
        var why = left > 0.5 ? "<br>" + T("原因：母體高度 {0} km，這個高度的大氣太稀薄，5 年內拖不下來。試試 500 km 以下的軌道（例如 Cosmos 1408 情境）。", fmt(d.parent.alt_km)) : "";
        return { ok: left <= 0.5, stars: left <= 0.1 ? 3 : left <= 0.25 ? 2 : 1, msg: T("5 年後第一代碎片還剩 <b>{0}%</b>（{1} / {2}）", Math.round(left * 100), fmt(s5.alive[1]), fmt(n0)) + why };
      } },
    m2: { name: "任務 2：連鎖觸發者", goal: "在 <b>×1,000 誇張模式</b>、10 年內觸發<b>第 3 代碎片</b>（碎片撞出的碎片再撞出碎片）。用的初始碎片越少，星數越高。",
      setup: function () { $("d-y").value = "10"; $("d-acc").value = "1000"; },
      judge: function (d, req) {
        if (req.accel < 1000) return { ok: false, msg: T("需要 ×1,000 以上的碰撞誇張倍率。") };
        var gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
        var why = gens < 3 ? "<br>" + T("原因：初始碎片太少或模擬年數太短，碰撞還來不及一代接一代發生。增加碎片數、年數，或改用 ×10,000。") : "";
        return { ok: gens >= 3, stars: req.n_frag <= 100 ? 3 : req.n_frag <= 300 ? 2 : 1, msg: T("最多到第 <b>{0}</b> 代；初始碎片 {1} 個", gens, req.n_frag) + why };
      } },
    m3: { name: "任務 3：守護者", goal: "Envisat 在<b>寫實 ×1</b> 下爆炸。用緩解決策卡（預算 3 點），讓 10 年的<b>第一代碎片近似風險降到不採取決策的對照組 81% 以下</b>（79% 兩星、77% 三星）。寫實模式下幾乎沒有連鎖，決策效果才量得準。以 5 個連續種子的中位數判定（每個種子都跑決策組與對照組，約需 1 分鐘）。",
      setup: function () { applyTpl("envisat"); $("d-acc").value = "1"; $("d-y").value = "10"; },
      judge: function (d, req, base) {
        if (!req.actions || !req.actions.length) return { ok: false, msg: T("至少要選一張決策卡。") };
        if (req.norad !== 27386 || req.orbit || req.n_frag < 1000) return { ok: false, msg: T("任務條件固定為 Envisat、1,000 個碎片（碎片越少，清理的 50 個佔比越大，比較就不公平）。重新選一次任務 3 會自動帶入。") };
        if (req.accel !== 1) return { ok: false, msg: T("需要寫實 ×1：誇張模式下連鎖是混沌的，一次擲骰不同就會讓整條連鎖改變，單次比較不可靠。") };
        if (!base || !base.ratios) return { pending: true };
        // 判定：M3_SEEDS 個連續種子的共同隨機數比較（決策組與對照組同種子、同解體時刻、同取樣時刻），取第一代碎片近似風險比值的中位數
        var rs = base.ratios.slice().sort(function (x, y) { return x - y; }), r = rs[Math.floor(rs.length / 2)];
        var why = "";
        if (r > 0.81) {
          var late = req.actions.every(function (a) { return a.t_days >= 365; });
          var kinds = req.actions.map(function (a) { return a.kind; });
          var av = req.actions.filter(function (a) { return a.kind === "avoid"; })[0];
          why = "<br>" + T("原因：") + T(late ? "決策都在第 1 年以後才生效，碎片已經散開；越早緩解越有效。" :
            !av ? "沒有避碰。清理 50 個碎片只佔 1,000 個中的一小部分，移除火箭體在短期內效果也有限（符合軌道面條件、又剛好在碎片帶裡的目標不多）；保護在軌衛星的避碰效果最大。" :
            av.level === "low" ? "避碰能力只有基礎級（碰撞機率只降到 50%）。改用標準級，或把點數留給進階級。" :
            kinds.indexOf("cleanup") < 0 ? "只有避碰。搭配第 30 天的清理任務，先移除風險最高的碎片，效果會更好。" :
            "只靠一種措施效果有限，可以換個搭配試試。");
        }
        return { ok: r <= 0.81, stars: r <= 0.77 ? 3 : r <= 0.79 ? 2 : 1,
          msg: T("第一代碎片近似風險為對照組的 <b>{0}%</b>（{1} 個種子 {2}–{3} 的中位數，範圍 {4}–{5}%）。", Math.round(r * 100), rs.length, req.seed, req.seed + rs.length - 1,
            Math.round(rs[0] * 100), Math.round(rs[rs.length - 1] * 100)) + "<span class='hint'>" + T("教學判定：種子數仍少，屬初步結果，不是統計結論。") + "</span>" + why + bestTip(req) +
            "<br>" + T("💡 即使三張卡都用上，通常也只能減少兩到三成：碎片一旦產生就很難收回，<b>預防解體（任務後處置、鈍化電池與殘餘推進劑）比事後清除有效得多</b>。") };
      } },  };
  var M3_SEEDS = 5;
  // 機會成本提示：多種子測試中各組合的參考值（scripts/validate_debris.py 同方法；見架構說明 6）
  var M3_REF = { seeds: "7–11", rows: [["清理＋標準避碰", 76], ["進階避碰＋移除火箭體", 80], ["只用進階避碰", 81], ["只用標準避碰", 82], ["清理＋基礎避碰", 83], ["只清理", 91], ["只移除火箭體", 100]] };
  function bestTip(req) {
    if (!M3_REF) return "";
    return "<br>" + T("📊 參考（種子 {0} 的中位數）：", M3_REF.seeds) + M3_REF.rows.map(function (r) { return T(r[0]) + " " + r[1] + "%"; }).join(T("、")) + T("。花同樣的點數，搭配不同，減少的風險可以差好幾倍（例如 3 點的清理＋標準避碰減少約 24%，清理＋移除火箭體只減少約 9%）。");
  }
  $("d-mission").onchange = function () {
    var m = MIS[this.value];
    $("d-mission-card").hidden = !m; $("d-mission-res").innerHTML = "";
    if (!m) return;
    m.setup();
    missionCard();
  };
  function missionCard() {
    var m = MIS[$("d-mission").value];
    if (m) $("d-mission-card").innerHTML = "🎯 <b>" + T(m.name) + "</b><br>" + T(m.goal);
  }

  // ── 成就（存在瀏覽器；無法存取時只在本頁有效）──────────────────────────
  var ACH = [
    ["gen2", "二次碰撞", "首次看到第 2 代碎片"], ["gen3", "連鎖反應", "觸發第 3 代碎片"], ["runaway", "失控增長", "模擬後段碎片仍淨增長：碰撞產生的碎片多於大氣清除"],
    ["clean", "大氣清道夫", "期末碎片全數再入"], ["guard", "守護者", "寫實模式下，決策讓第一代碎片近似風險降到對照組 85% 以下（單一種子）"], ["history", "歷史學家", "試過全部 3 個歷史案例"],
    ["m1", "任務 1", "完成自然清除"], ["m2", "任務 2", "完成連鎖觸發者"], ["m3", "任務 3", "完成守護者"],
  ];
  var got = {};
  try { got = JSON.parse(localStorage.getItem("sdg-debris-ach") || "{}") || {}; } catch (e) { got = {}; }
  function save() { try { localStorage.setItem("sdg-debris-ach", JSON.stringify(got)); } catch (e) { /* 私密模式等 */ } }
  function unlock(k) { if (got[k]) return false; got[k] = Date.now(); save(); return true; }
  var lastFresh = [];
  function drawAch(fresh) {
    var n = ACH.filter(function (a) { return got[a[0]]; }).length;
    lastFresh = fresh;
    $("d-ach").innerHTML = "<div style='margin-bottom:3px'>" + T("已解鎖 <b>{0} / {1}</b>", n, ACH.length) + (fresh.length ? "　<span style='color:#f2cc60'>" + T("🎉 新成就：") + fresh.map(function (x) { return T(x); }).join(T("、")) + "</span>" : "") + "</div>" +
      ACH.map(function (a) {
        return "<span title='" + T(a[2]) + "' style='display:inline-block;margin:2px 4px 2px 0;padding:1px 7px;border-radius:10px;border:1px solid " +
          (got[a[0]] ? "#f2cc60;color:#f2cc60" : "#30363d;color:#6e7681") + "'>" + (got[a[0]] ? "🏅 " : "🔒 ") + T(a[1]) + "</span>";
      }).join("");
  }
  drawAch([]);

  // ── 風險儀表板 ───────────────────────────────────────────────────────────
  var GEN_C = ["#8b949e", "#ffa657", "#ff7b72", "#f778ba", "#bc8cff", "#79c0ff", "#ffffff", "#ffffff"];
  function dash(d) {
    var R = 6378.137, s = d.summary, h = "";
    // 1. 風險最高的目錄物件
    if (d.risk_top && d.risk_top.length) {
      h += "<div style='margin-top:2px'>" + T("<b>風險最高的目錄物件</b>（被所有碎片撞上的累計期望次數，已除回誇張倍率）") + "</div><table class='kv'>" +
        d.risk_top.map(function (r) { return "<tr><td>" + (r.name || "—") + "</td><td>" + T("{0}，{1} km，{2} 次", T(r.kind), fmt(r.alt_km), r.expected_real < 0.001 ? r.expected_real.toExponential(1) : r.expected_real.toFixed(3)) + "</td></tr>"; }).join("") + "</table>";
    }
    // 2. 碰撞熱區高度帶（50 km 一帶）
    var bands = {};
    d.events.forEach(function (e) {
      if (e.kind !== "collision" || !e.pos) return;
      var alt = Math.hypot(e.pos[0], e.pos[1], e.pos[2]) - R, b = Math.floor(alt / 50) * 50;
      bands[b] = (bands[b] || 0) + 1;
    });
    var bk = Object.keys(bands).map(Number).sort(function (a, b) { return bands[b] - bands[a]; }).slice(0, 5), bmax = bk.length ? bands[bk[0]] : 1;
    h += "<div style='margin-top:6px'><b>" + T("碰撞熱區高度帶") + "</b></div>" + (bk.length ? bk.map(function (b) {
      return "<div style='display:flex;gap:6px;align-items:center'><span style='min-width:92px'>" + b + "–" + (b + 50) + " km</span><div style='flex:1;background:#21262d;height:9px;border-radius:3px'><div style='width:" +
        Math.round(bands[b] / bmax * 100) + "%;height:100%;background:#ff7b72;border-radius:3px'></div></div><span style='min-width:40px;text-align:right'>" + T("{0} 次", bands[b]) + "</span></div>";
    }).join("") : "<div>" + T("沒有碰撞。") + "</div>");
    // 3. 期末各代碎片比例
    var last = d.series[d.series.length - 1].alive, tot = last.reduce(function (a, b) { return a + b; }, 0);
    h += "<div style='margin-top:6px'>" + T("<b>期末各代碎片比例</b>（在軌 {0} 個）", fmt(tot)) + "</div>";
    if (tot) {
      h += "<div style='display:flex;height:12px;border-radius:3px;overflow:hidden'>" + last.map(function (v, k) {
        return v ? "<div title='" + T("第 {0} 代：{1} 個", k, fmt(v)) + "' style='width:" + (v / tot * 100) + "%;background:" + GEN_C[k] + "'></div>" : "";
      }).join("") + "</div><div>" + last.map(function (v, k) { return v ? "<span style='color:" + GEN_C[k] + ";margin-right:8px'>" + T("第 {0} 代 {1}%", k, Math.round(v / tot * 100)) + "</span>" : ""; }).join("") + "</div>";
    } else h += "<div>" + T("碎片已全數再入或被撞毀。") + "</div>";
    // 4. 太陽活動走勢（F10.7，隨太陽活動模式才有）
    var fv = d.series.filter(function (x) { return x.f107 != null; });
    if (fv.length > 2 && d.solar && d.solar.mode === "series") {
      var W = 360, H = 46, t1 = fv[fv.length - 1].t, fmin = 60, fmax = Math.max(200, Math.max.apply(null, fv.map(function (x) { return x.f107; })));
      var pts = fv.map(function (x) { return (x.t / t1 * W).toFixed(1) + "," + (H - (x.f107 - fmin) / (fmax - fmin) * H).toFixed(1); }).join(" ");
      // 預報資料之後（2041-10 起）為 11 年週期外推：灰底標出
      var ext = "";
      if (d.solar.beyond_data) {
        var du = d.solar.data_until.split("-"), tb = (Date.UTC(+du[0], +du[1], 1) - Date.parse(d.solar.epoch + "T00:00:00Z")) / 1000, xb = Math.max(0, Math.min(W, tb / t1 * W));
        ext = "<rect x='" + xb.toFixed(1) + "' y='0' width='" + (W - xb).toFixed(1) + "' height='" + H + "' fill='#30363d' opacity='0.6'/>" +
          "<text x='" + (xb + 4).toFixed(1) + "' y='12' fill='#c9d1d9' font-size='10'>" + T("{0} 後：週期外推（情境假設，非預報）", d.solar.data_until.slice(0, 4)) + "</text>";
      }
      h += "<div style='margin-top:6px'>" + T("<b>太陽活動 F10.7</b>（{0} 起；越高大氣越密、碎片衰減越快）", d.solar.epoch) + "</div>" +
        "<svg viewBox='0 0 " + W + " " + H + "' style='width:100%;height:46px;background:#0b1622;border-radius:4px'>" + ext + "<polyline points='" + pts +
        "' fill='none' stroke='#f2a73b' stroke-width='1.5'/><text x='4' y='12' fill='#8b949e' font-size='10'>" + Math.round(fmax) + "</text><text x='4' y='" + (H - 3) + "' fill='#8b949e' font-size='10'>" + fmin + "</text></svg>";
    }
    // 5. 累計再入
    h += "<div style='margin-top:6px'>" + T("<b>累計再入</b>：碎片 {0} 個（含被撞毀與清理移除）；目錄物件 {1} 個", fmt(s.reentered || 0), fmt(s.cat_reentered || 0)) + "</div>";
    $("d-dash").innerHTML = h;
  }

  // ── 掛上主流程 ───────────────────────────────────────────────────────────
  HOOK.extend = function (req) {
    if (cur && cur.orbit) { req.orbit = cur.orbit; req.norad = 0; }
    var acts = picked().map(function (c) {
      var a = { kind: c.k, t_days: +document.querySelector("[data-cardt=" + c.k + "]").value };
      if (c.n) a.n = c.n;
      if (lvlSel(c)) a.level = lvlSel(c).value;
      return a;
    });
    if (acts.length) req.actions = acts;
    return req;
  };
  var tried = {};
  try { tried = JSON.parse(localStorage.getItem("sdg-debris-tpl") || "{}") || {}; } catch (e) { tried = {}; }
  var lastD = null;
  HOOK.onResult = function (d, req) {
    lastD = d;
    dash(d);
    $("d-compare").innerHTML = "";
    var fresh = [], gens = 0; d.frags.forEach(function (f) { gens = Math.max(gens, f[2]); });
    var add = function (k) { if (unlock(k)) fresh.push(ACH.filter(function (a) { return a[0] === k; })[0][1]); };
    if (gens >= 2) add("gen2");
    if (gens >= 3) add("gen3");
    // 失控增長：模擬後 1/3 期間在軌碎片仍淨增加，且期間有碰撞（碰撞產生 > 大氣清除）
    var S = d.series, k0 = Math.floor(S.length * 2 / 3), tot = function (s) { return s.alive.reduce(function (a, b) { return a + b; }, 0); };
    if (S.length > 6 && tot(S[S.length - 1]) > tot(S[k0]) && S[S.length - 1].collisions > S[k0].collisions && !d.summary.capped) add("runaway");
    if (d.summary.alive_end === 0 && d.summary.fragments_total > 0) add("clean");
    if (cur && cur.orbit) {
      tried[$("d-tpl").value] = 1; try { localStorage.setItem("sdg-debris-tpl", JSON.stringify(tried)); } catch (e) { /* 略 */ }
      if (tried.fy1c && tried.iridium && tried.c1408) add("history");
    }
    var mk = $("d-mission").value, m = MIS[mk];
    var finish = function (base) {
      if (m) {
        var r = m.judge(d, req, base);
        if (r.pending) { $("d-mission-res").innerHTML = "<div class='coach'>" + T("🎯 對照組計算中，完成後判定…") + "</div>"; return; }
        if (r.ok && unlock(mk)) fresh.push(m.name.slice(0, 4));
        $("d-mission-res").innerHTML = "<div class='coach' style='border-left-color:" + (r.ok ? "#3fb950" : "#ff7b72") + "'>🎯 <b>" + T(m.name) + T("：") +
          (r.ok ? "<span style='color:#3fb950'>" + T("成功") + "</span> <span style='color:#f2cc60;font-size:15px'>" + "★★★".slice(0, r.stars) + "☆☆☆".slice(0, 3 - r.stars) + "</span>" : "<span style='color:#ff7b72'>" + T("未達成") + "</span>") +
          "</b><br>" + r.msg + "</div>";
      }
      drawAch(fresh);
    };
    if (!req.actions) { finish(null); return; }
    // 有決策卡：自動跑對照組（同參數、同亂數種子、不採取決策）
    if (m && m.judge(d, req, null).pending) finish(null);
    $("d-compare").innerHTML = T("對照組（不採取決策）計算中…");
    // 對照組沿用主結果的解體時刻 t0：母體位置與目錄相同，才是共同隨機數比較
    var base = JSON.parse(JSON.stringify(req)); delete base.actions; base.t0 = req.t0 = d.t0;
    (function tryPost(n) {
      HOOK.postRetry(base, function (left) { $("d-compare").textContent = T("對照組排隊中，{0} 秒後重試…", left); }).then(function (b) {
        if (b.error) { $("d-compare").textContent = T("對照組計算失敗：") + TS(b.error); return; }
        var row = function (name, x) {
          var g1 = x.summary.expected_gen1_real;
          var ex = x.summary.expected_collisions;
          return "<tr><td>" + name + "</td><td>" + (ex < 10 ? ex.toFixed(2) : fmt(ex)) + "</td><td>" + T("{0} 次", x.summary.collisions) + "</td><td>" + fmt(x.summary.fragments_total) + "</td><td>" + fmt(x.summary.alive_end) + "</td><td>" + (g1 < 0.01 ? g1.toExponential(1) : g1.toFixed(2)) + "</td></tr>";
        };
        // 比較指標：第一代碎片近似風險（只計第一代碎片與目錄物件），排除寫實模式偶發擲中產生的後代碎片雜訊
        var r = d.summary.expected_gen1_real / Math.max(1e-12, b.summary.expected_gen1_real);
        var rt = d.summary.expected_collisions / Math.max(1e-12, b.summary.expected_collisions);
        $("d-compare").innerHTML = "<div style='margin-top:6px'><b>" + T("🃏 決策效果（與對照組比較）") + "</b></div><table class='kv'><tr><td></td><td>" + T("累計期望碰撞") + "</td><td>" + T("擲中") + "</td><td>" + T("碎片總數") + "</td><td>" + T("期末在軌") + "</td><td>" + T("第一代近似風險") + "</td></tr>" +
          row(T("採取決策"), d) + row(T("對照組"), b) + "</table><div>" + T("第一代碎片近似風險為對照組的 <b>{0}%</b>（累計期望碰撞為對照組的 {1}%）。", Math.round(r * 100), Math.round(rt * 100)) +
          T("判斷效果用第一代近似風險：它是期望值、對亂數較不敏感，也不受偶發碰撞產生的後代碎片影響；擲中次數受運氣影響，換幾個種子再比較更可靠。") + "</div>";
        if (req.accel === 1 && r <= 0.85 && b.summary.expected_collisions > 0) { if (unlock("guard")) fresh.push("守護者"); }
        if (mk !== "m3") { finish(b); return; }
        // 任務 3：再跑其餘種子（決策組＋對照組），以比值中位數判定
        var ratios = [r];
        (function nextSeed(i) {
          if (i >= M3_SEEDS) { b.ratios = ratios; finish(b); return; }
          $("d-mission-res").innerHTML = "<div class='coach'>" + T("🎯 多種子判定：第 {0} / {1} 個種子計算中（每個種子要跑決策組與對照組，約 10–15 秒）…", i + 1, M3_SEEDS) + "</div>";
          var dq = JSON.parse(JSON.stringify(req)), bq = JSON.parse(JSON.stringify(base));
          dq.seed = bq.seed = req.seed + i;
          HOOK.postRetry(dq).then(function (x) {
            return HOOK.postRetry(bq).then(function (y) {
              if (x.error || y.error) throw new Error(x.error || y.error);
              ratios.push(x.summary.expected_gen1_real / Math.max(1e-12, y.summary.expected_gen1_real));
              nextSeed(i + 1);
            });
          }).catch(function (e) { $("d-mission-res").innerHTML = "<div class='coach'>" + T("🎯 多種子判定失敗：") + TS(String(e.message || e)) + "</div>"; });
        })(1);
      }).catch(function (e) { $("d-compare").textContent = T("對照組計算失敗：") + e; });
    })(0);
  };

  // 切換語言（線上版）：重畫決策卡、說明、任務卡、成就與儀表板（任務判定與對照組文字在下次引爆時更新）
  HOOK.relangGame = function () {
    drawCards(); budget(); kindNote(); missionCard(); drawAch(lastFresh);
    if (cur) $("d-tpl-note").textContent = T(cur.note) + (cur.coll ? T("（碰撞模型：外部撞擊）") : T("（爆炸模型：內部能量）"));
    if (lastD) dash(lastD);
  };
})();
