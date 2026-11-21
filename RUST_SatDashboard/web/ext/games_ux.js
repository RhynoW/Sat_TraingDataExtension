/* 太空小遊戲：共通體驗層（任務卡與示範、時間面板收合、速度選單「自訂」、時間軸台灣時間、計算中提示、結果自動捲入畫面）
 * 只操作 DOM 與 window.SDG，不改各遊戲的邏輯；需在其他 games_*.js 之後載入。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var SDG = window.SDG, viewer = SDG.viewer, clock = viewer.clock, JD = Cesium.JulianDate;

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function until(fn, ms) {
    var t0 = Date.now();
    return new Promise(function (ok, no) {
      (function poll() { if (fn()) ok(); else if (Date.now() - t0 > (ms || 120000)) no(new Error("逾時")); else setTimeout(poll, 200); })();
    });
  }
  function setv(id, v) {
    var e = $(id); e.value = v;
    e.dispatchEvent(new Event("input", { bubbles: true })); e.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function click(sel) { var e = typeof sel === "string" ? (document.getElementById(sel) || document.querySelector(sel)) : sel; if (e) e.click(); }
  function enabled(id) { return function () { return $(id) && !$(id).disabled; }; }
  function show(id) { var e = $(id); if (e && e.offsetParent) e.scrollIntoView({ block: "nearest", behavior: "smooth" }); }

  // ── 任務卡：一句問題、三個步驟、示範按鈕 ─────────────────────────────────
  var MISSIONS = {
    moon: { q: "能把太空船從低地球軌道送到月球嗎？",
      s: ["選一個挑戰（撞月、飛掠、自由返回、繞月）", "按「自動瞄準」找出點火位置", "按「發射」，看三體軌道與結果"],
      demo: function () {
        setv("g-ch", "flyby"); click("g-aim");
        return wait(300).then(function () { return until(enabled("g-aim")); }).then(function () { click("g-run"); return wait(800); }).then(function () { show("res"); });
      } },
    crowd: { q: "如果低軌衛星多到 15 萬顆，太空會有多擠？",
      s: ["點情境按鈕，或勾選「假想」自訂星座顆數", "按「計算壅擠指標」", "看「倍數」欄與高度密度剖面"],
      demo: function () {
        click("[data-preset=mega]"); setv("cr-hours", "1"); click("cr-run");
        return wait(300).then(function () { return until(enabled("cr-run"), 300000); });
      } },
    debris: { q: "一顆大衛星解體，會引發碎片連鎖碰撞嗎？",
      s: ["選任務或情境（含歷史案例），或自選衛星、碎片數與解體方式", "可選緩解決策卡，按「引爆」（預設 ×1 寫實；想看連鎖可改 ×1,000 誇張模式）", "看結果、風險儀表板與成就；點「看全程」播放"],
      demo: function () {
        setv("d-acc", "1000"); click("d-run");
        return wait(300).then(function () { return until(enabled("d-run"), 180000); }).then(function () { click("[data-dplay='3h']"); });
      } },
    astro: { q: "衛星光跡會毀掉一張天文照片嗎？",
      s: ["選觀測地點、指向與望遠鏡", "按「跳到今晚天文昏影」，再按「拍一張」（點影像可放大）", "按「比較」，左右拖曳看 10 萬 Starlink 多了多少光跡"],
      demo: function () {
        click("s-dusk"); setv("s-scen", "now"); click("s-run");
        return wait(300).then(function () { return until(enabled("s-run")); })
          .then(function () { click("s-cmp-run"); return wait(300); }).then(function () { return until(enabled("s-cmp-run")); });
      } },
    balloon: { q: "鋁箔氣球要多大，才能在台北造成日食？",
      s: ["上方時間設在台北白天", "輸入氣球直徑與軌道高度", "按「計算並播放」，看是全食、環食還是偏食"],
      demo: function () {
        var d = new Date(Date.now() + 8 * 3600e3);   // 今天台北中午 12:00
        setv("t-pick", d.toISOString().slice(0, 10) + "T12:00");
        setv("b-d", 8000); setv("b-h", 550); click("b-run");
        return wait(800);
      } },
    asat: { q: "比強弓更強的火箭，打得到國際太空站嗎？",
      s: ["選目標衛星與發射點", "調燃燒結束速度，按「找出交會機會」", "把發射時間誤差調大，按「播放飛行」看落點"],
      demo: function () {
        setv("a-v", 3.0); click("a-solve");
        return until(function () { var t = $("a-res").textContent; return t.length > 30 && t.indexOf("計算中") !== 0; }, 60000)
          .then(function () { setv("a-dt", 1); click("a-fly"); return wait(500); }).then(function () { show("a-miss"); });
      } },
    war: { q: "海纜被切斷時，台灣的國際通訊撐得住嗎？",
      s: ["選雙方由真人或 AI 擔任，以及你扮演的角色", "按「開新推演」", "每回合用 5 個行動點下令，按「提交命令」"],
      demo: function () {
        setv("w-ai-blue", ""); setv("w-role", "blue"); click("w-new");
        return until(function () { return !!$("w-submit"); }, 20000).then(function () {
          click("[data-a='0']"); click("[data-a='1']");
          var b = $("w-submit"); b.classList.add("flash"); b.scrollIntoView({ block: "nearest", behavior: "smooth" });
          setTimeout(function () { b.classList.remove("flash"); }, 4000);
          SDG.status("示範：已選「租用 GEO」與「部署低軌終端」，按「提交命令」進入下一回合。");
        });
      } },
  };
  Object.keys(MISSIONS).forEach(function (t) {
    var box = $("tab-" + t); if (!box) return;
    var h3 = box.querySelector("h3"), m = MISSIONS[t];
    // 原本的開場說明收進「背景說明」，預設收起
    var intro = h3.nextElementSibling;
    if (intro && intro.classList.contains("hint")) {
      var det = document.createElement("details"); det.className = "intro";
      det.innerHTML = "<summary>背景說明</summary>"; intro.parentNode.insertBefore(det, intro); det.appendChild(intro);
    }
    var card = document.createElement("div"); card.className = "mission";
    // 月球分頁：任務卡放最上方並顯示問題，射月球緊接在下（月相與月面圖在地球畫面右上角的收合選單）；其他分頁的標題本身就是問題，卡片接在標題後
    var top = t === "moon";
    card.innerHTML = (top ? "<div class='q'>🎯 " + m.q + "</div>" : "") + "<ol>" + m.s.map(function (x) { return "<li>" + x + "</li>"; }).join("") +
      "</ol><button class='demo'>▶ 示範</button><span class='hint'>自動帶入一組參數並執行</span>";
    if (top) box.insertBefore(card, box.firstChild); else h3.parentNode.insertBefore(card, h3.nextSibling);
    var btn = card.querySelector(".demo");
    btn.onclick = function () {
      btn.disabled = true; btn.textContent = "示範中…";
      Promise.resolve().then(m.demo).catch(function (e) { SDG.status("示範中斷：" + e.message); })
        .then(function () { btn.disabled = false; btn.textContent = "▶ 示範"; });
    };
  });

  // ── 時間面板：可收合；摘要列顯示目前時間與速度；月球說明只在月球分頁 ──────
  var tbox = $("t-box"), sel = $("t-speed");
  var OPEN = { moon: true, balloon: true };          // 需要調時間的分頁預設展開
  tbox.addEventListener("toggle", function () { OPEN[SDG.tab()] = tbox.open; });
  function onTab(t) {
    tbox.open = !!OPEN[t];
    $("t-moonnote").hidden = t !== "moon";
    $("moon-float").hidden = t !== "moon";
    // 兵棋：從其他分頁切回來時，相機回到台灣周邊海纜
    if (t === "war" && $("w-board").textContent) viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(121, 23.5, 4.5e6) });
  }
  document.addEventListener("sdg-tab", function (e) { onTab(e.detail); });
  onTab(SDG.tab());

  function speedText(m) {
    if (m < 1) return "慢動作 ×" + (+m.toPrecision(2));
    if (m === 1) return "即時";
    if (m < 3600) return (+(m / 60).toPrecision(3)) + " 分鐘／秒";
    if (m < 86400) return (+(m / 3600).toPrecision(3)) + " 小時／秒";
    return (+(m / 86400).toPrecision(3)) + " 天／秒";
  }
  function syncClock() {
    var m = clock.multiplier, fixed = null, custom = sel.querySelector("option[data-custom]");
    Array.prototype.forEach.call(sel.options, function (o) { if (!o.dataset.custom && +o.value === m) fixed = o; });
    if (document.activeElement !== sel) {
      if (fixed) { if (custom) custom.remove(); sel.value = fixed.value; }
      else {
        if (!custom) { custom = document.createElement("option"); custom.dataset.custom = "1"; sel.appendChild(custom); }
        custom.value = String(m); custom.textContent = "自訂：" + speedText(m); sel.value = custom.value;
      }
    }
    $("t-play").textContent = clock.shouldAnimate ? "⏸" : "▶";
    // 時間輸入框原本只在月球分頁更新；這裡統一同步（使用者正在編輯時不覆蓋）
    if (document.activeElement !== $("t-pick")) $("t-pick").value = SDG.tw(JD.toDate(clock.currentTime)).replace(" ", "T");
    $("t-sum").textContent = SDG.tw(JD.toDate(clock.currentTime)) + "（台灣）· " + (clock.shouldAnimate ? speedText(m) : "暫停");
  }
  setInterval(syncClock, 250); syncClock();

  // ── 時間軸刻度改用台灣時間（UTC+8），與面板一致 ─────────────────────────
  var tl = viewer.timeline;
  if (tl) {
    var p2 = function (n) { return (n < 10 ? "0" : "") + n; };
    tl.makeLabel = function (t) {
      // 依時間軸跨度取整（Cesium 刻度在長跨度時會有幾十毫秒的浮點偏差）
      var span = tl._timeBarSecondsSpan || 0, q = span > 7200 ? 60000 : span > 60 ? 1000 : 10;
      var d = new Date(Math.round(JD.toDate(t).getTime() / q) * q + 8 * 3600e3);
      if (span > 180 * 86400) return d.getUTCFullYear() + "/" + (d.getUTCMonth() + 1) + "/" + d.getUTCDate();   // 跨年的時間軸要看得到年份
      var s = (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + " " + p2(d.getUTCHours()) + ":" + p2(d.getUTCMinutes());
      var sec = d.getUTCSeconds(), ms = d.getUTCMilliseconds();
      if (sec || ms) s += ":" + p2(sec);
      if (ms) s += "." + String(ms).padStart(3, "0");
      return s;
    };
    tl.zoomTo(tl._startJulian, tl._endJulian);
  }

  // ── 計算中：按鈕轉圈＋經過秒數；結束後把結果捲入畫面 ─────────────────────
  var RESULT = { "g-aim": "res", "g-run": "res", "cr-run": "cr-res", "d-run": "d-res", "s-run": "s-res", "s-cmp-run": "s-cmp","b-run": "b-res", "a-solve": "a-res", "w-mc": "w-mc-res" };
  var timers = {};
  new MutationObserver(function (list) {
    list.forEach(function (r) {
      var b = r.target; if (b.tagName !== "BUTTON" || b.classList.contains("demo")) return;
      if (b.disabled && !timers[b.id]) {
        var t0 = Date.now(); b.classList.add("busy"); b.dataset.el = "";
        timers[b.id] = setInterval(function () { var s = (Date.now() - t0) / 1000; b.dataset.el = s >= 1 ? " " + s.toFixed(0) + " 秒" : ""; }, 250);
      } else if (!b.disabled && timers[b.id]) {
        clearInterval(timers[b.id]); delete timers[b.id]; b.classList.remove("busy"); b.dataset.el = "";
        if (RESULT[b.id]) setTimeout(function () { show(RESULT[b.id]); }, 300);
      }
    });
  }).observe($("side"), { subtree: true, attributes: true, attributeFilter: ["disabled"] });
  // 沒有忙碌狀態的立即計算按鈕：點了之後直接把結果捲入畫面
  ["g-run", "b-run", "a-solve"].forEach(function (id) {
    $(id).addEventListener("click", function () { setTimeout(function () { show(RESULT[id]); }, 600); });
  });
})();
