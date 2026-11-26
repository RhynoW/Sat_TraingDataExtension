/* 太空小遊戲：百萬顆衛星長期風險與管控（單機版「星座壅擠」分頁、線上版 /game；兩版共用同一份檔案）
 *
 * 計算：分殼層統計模型（mean-field），在瀏覽器端計算，兩版結果逐筆一致。
 *  - 高度 200–2000 km 每 25 km 一格；族群：百萬顆星座運作中（Am）、其他運作中（Ab）、百萬顆星座失效（Dm）、
 *    其他失效衛星與火箭體（Db）、碎片 ≥10 cm（F）。月步長、預設模擬 50 年。
 *  - 碰撞：氣體動力學 率＝n₁n₂σv／V（同類 ×½），相對速度 10 km/s；運作中衛星以避碰成功率降低碰撞；
 *    運作中衛星彼此以相位設計與協調不互撞（不計；現有 Starlink 等也是如此）。完整物體互撞為災難性解體；
 *    ≥10 cm 碎片撞完整物體 10% 達災難性解體門檻（撞擊能量／目標質量 > 40 J/g），其餘使運作中衛星失效。碎片數依 NASA 標準解體模型 N(≥10 cm)＝0.1·M^0.75·0.1^−1.71，散布到上下 100 km。
 *  - 大氣阻力：依高度的軌道壽命表（中等太陽活動）把失效衛星與碎片逐格往下移，200 km 以下視為再入；運作中衛星維持軌道。
 *  - 生命週期：運作中衛星依年失效率變成失效衛星；任務結束時依離軌成功率離軌，失敗者留在軌道。
 *    百萬顆星座依部署進度補發，但受「每年發射上限」限制（發射能力有限：損失過快時補不回來）；其他營運者維持起始數量。
 *    營運者停損：某高度格的運作中衛星每年因碰撞損失超過 20% 時，不再往該格補發（殼層被放棄）。
 *  - 主動移除（ADR）：每年移除指定顆數的失效衛星，優先處理碰撞風險最高的高度。
 *  - 部署：FCC 2026-11-25 核准條件的里程碑（2033-11 開始、2035-11 10 萬、2038-11 50 萬、2040-11 100 萬），依規模等比例縮放；
 *    六個殼層的實際高度與傾角未公開，預設平均分布於 500–1,002 km（假設，可調）。
 *  這是供政策討論的量級估計：參數多為假設、平均場模型不含軌道面相位與個別事件的隨機性。 */
(function () {
  "use strict";
  // ── 計算核心（純函式，供測試直接呼叫：window.MEGA_CORE）────────────────────────
  var RE = 6371, H0 = 200, DH = 25, NB = 72, VREL = 10 * 31557600;   // km、km/年
  var SIG_II = Math.PI * 0.004 * 0.004, SIG_IF = Math.PI * 0.0021 * 0.0021, SIG_M = Math.PI * 1 * 1;
  var LC = Math.pow(0.1, -1.71), F_CAT_IF = 0.1, M_BG = 1000, M_DB = 1500, FRAG_LIFE = 0.3;
  var KERNEL = [1, 2, 4, 6, 8, 6, 4, 2, 1];
  // 完整物體的軌道壽命錨點（高度 km, log10 年；中等太陽活動、面質比約 0.01 m²/kg 的近似值）
  var LIFE = [[200, -1.6], [300, -0.7], [400, 0.2], [500, 1.0], [600, 1.6], [700, 2.1], [800, 2.5], [900, 2.8], [1000, 3.1], [1200, 3.5], [1500, 3.9], [2000, 4.3]];
  var MILESTONES = [[2033.875, 0], [2035.875, 100000], [2038.875, 500000], [2040.875, 1000000]];
  var BG = { fail: 0.005, life: 7, pmd: 0.95, avoid: 0.99 };   // 其他營運者的現行水準（假設；現有運作中衛星以 Starlink 為主）
  var ABANDON = 0.2;   // 每顆每年碰撞損失率超過此值即停止補發該高度格   // 其他營運者的現行水準（假設）
  var SHELLS0 = [500, 600, 700, 800, 900, 1002];

  function life(h) {
    if (h <= LIFE[0][0]) return Math.pow(10, LIFE[0][1]);
    for (var i = 1; i < LIFE.length; i++) {
      if (h <= LIFE[i][0]) {
        var a = LIFE[i - 1], b = LIFE[i];
        return Math.pow(10, a[1] + (b[1] - a[1]) * (h - a[0]) / (b[0] - a[0]));
      }
    }
    return Math.pow(10, LIFE[LIFE.length - 1][1]);
  }
  var VOL = [], TBIN = [];
  for (var i0 = 0; i0 < NB; i0++) {
    var hc = H0 + DH * (i0 + 0.5), r = RE + hc;
    VOL.push(4 * Math.PI * r * r * DH);
    TBIN.push(Math.max(life(H0 + DH * (i0 + 1)) - life(H0 + DH * i0), 1e-3));   // 穿越此格的年數
  }
  function binOf(h) { return Math.max(0, Math.min(NB - 1, Math.floor((h - H0) / DH))); }
  function nFrag(m) { return 0.1 * Math.pow(m, 0.75) * LC; }
  function deployed(year, total) {
    var M = MILESTONES;
    if (year <= M[0][0]) return 0;
    for (var i = 1; i < M.length; i++) {
      if (year <= M[i][0]) return total / 1e6 * (M[i - 1][1] + (M[i][1] - M[i - 1][1]) * (year - M[i - 1][0]) / (M[i][0] - M[i - 1][0]));
    }
    return total;
  }
  function shellAlts(cap) {
    if (!(cap < SHELLS0[5])) return SHELLS0.slice();
    var lo = Math.min(500, cap), out = [];
    for (var k = 0; k < 6; k++) out.push(lo + (cap - lo) * k / 5);
    return out;
  }
  function zeros() { var a = new Float64Array(NB); return a; }
  function sum(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; return s; }

  /** bg：{active, derelict, debris} 各 NB 格；p：情境參數 → 逐年序列與期末剖面 */
  function simulate(bg, p) {
    var years = Math.max(1, Math.min(100, Math.round(p.years || 50))), dt = 1 / 12, steps = years * 12;
    var total = Math.max(0, Math.min(1e6, +p.total || 0)), fail = Math.max(0, +p.fail || 0), pmd = Math.max(0, Math.min(1, +p.pmd)),
      avoid = Math.max(0, Math.min(1, +p.avoid)), adr = Math.max(0, +p.adr || 0), mM = Math.max(1, +p.mass || 800),
      lifeM = Math.max(0.5, +p.life || 5), t0 = +p.t0 || 2026.9, lcap = p.launch_cap == null ? 3e5 : Math.max(0, +p.launch_cap);
    var alts = shellAlts(+p.cap || 1002), share = zeros();
    alts.forEach(function (h) { share[binOf(h)] += 1 / 6; });
    var Am = zeros(), Ab = Float64Array.from(bg.active), Dm = zeros(), Db = Float64Array.from(bg.derelict), F = Float64Array.from(bg.debris);
    var Ab0 = Float64Array.from(bg.active);
    var qM = 1 - avoid, qB = 1 - BG.avoid;
    var cum = { coll: 0, cat: 0, launch: 0, pmd: 0, adr: 0, reentry: 0 }, abandoned = new Uint8Array(NB), firstAbandon = null;
    var series = [], start = { act: [], der: [], deb: [] };
    function record(k, rates) {
      var act = sum(Am) + sum(Ab);
      series.push({ year: +(t0 + k * dt).toFixed(3), Am: sum(Am), Ab: sum(Ab), D: sum(Dm) + sum(Db), F: sum(F),
        coll: rates.coll, cat: rates.cat, cum_coll: cum.coll, enc: rates.enc, enc_per_sat: act > 0 ? rates.enc / act : 0,
        launch: cum.launch, adr: cum.adr, abandoned: abandoned.reduce(function (a, v) { return a + v; }, 0) });
    }
    function rates() {
      var out = { coll: 0, cat: 0, enc: 0, bins: [] };
      for (var i = 0; i < NB; i++) {
        var V = VOL[i], k2 = VREL / V, am = Am[i], ab = Ab[i], dm = Dm[i], db = Db[i], f = F[i];
        var D = dm + db, tot = am + ab + D + f;
        // 完整物體互撞（災難性）：運作中衛星彼此（Am–Am、Ab–Ab、Am–Ab）以協調避免，不計
        var c_ab_ab = 0, c_am_ab = 0,
          c_am_d = am * D * SIG_II * k2 * qM, c_ab_d = ab * D * SIG_II * k2 * qB, c_d_d = 0.5 * D * D * SIG_II * k2;
        // 碎片撞完整物體
        var c_am_f = am * f * SIG_IF * k2 * qM, c_ab_f = ab * f * SIG_IF * k2 * qB, c_d_f = D * f * SIG_IF * k2;
        var ii = c_ab_ab + c_am_ab + c_am_d + c_ab_d + c_d_d, iff = c_am_f + c_ab_f + c_d_f;
        // 期望碎片產生率（個／年）
        var mD = D > 0 ? (dm * mM + db * M_DB) / D : M_DB;
        var frag = c_ab_ab * nFrag(2 * M_BG) + c_am_ab * nFrag(mM + M_BG) + c_am_d * nFrag(mM + mD) + c_ab_d * nFrag(M_BG + mD) + c_d_d * nFrag(2 * mD) +
          F_CAT_IF * (c_am_f * nFrag(mM) + c_ab_f * nFrag(M_BG) + c_d_f * nFrag(mD));
        // 1 km 內幾何接近：各運作中衛星自身的接近率加總；除以運作中顆數即每顆平均
        var enc = (am + ab) * (D + f) * SIG_M * k2;   // 與失效衛星、火箭體、碎片的接近（運作中彼此由協調處理）
        out.bins.push({ c_ab_ab: c_ab_ab, c_am_ab: c_am_ab, c_am_d: c_am_d, c_ab_d: c_ab_d, c_d_d: c_d_d, c_am_f: c_am_f, c_ab_f: c_ab_f, c_d_f: c_d_f,
          frag: frag, mD: mD, D: D });
        out.coll += ii + iff; out.cat += ii + F_CAT_IF * iff; out.enc += enc;
      }
      return out;
    }
    for (var i = 0; i < NB; i++) { start.act.push(Ab[i]); start.der.push(Db[i]); start.deb.push(F[i]); }
    var R = rates();
    record(0, R);
    for (var k = 1; k <= steps; k++) {
      var nAm = Float64Array.from(Am), nAb = Float64Array.from(Ab), nDm = Float64Array.from(Dm), nDb = Float64Array.from(Db), nF = Float64Array.from(F);
      for (var i = 0; i < NB; i++) {
        var b = R.bins[i], D = b.D, wm = D > 0 ? Dm[i] / D : 0, wb = 1 - wm;
        // 碰撞造成的移除（期望值，單步不超過族群）
        var lossAm = (b.c_am_ab + b.c_am_d + F_CAT_IF * b.c_am_f) * dt, disAm = (1 - F_CAT_IF) * b.c_am_f * dt;
        var lossAb = (2 * b.c_ab_ab + b.c_am_ab + b.c_ab_d + F_CAT_IF * b.c_ab_f) * dt, disAb = (1 - F_CAT_IF) * b.c_ab_f * dt;
        var lossD = (b.c_am_d + b.c_ab_d + 2 * b.c_d_d + F_CAT_IF * b.c_d_f) * dt;
        var fAm = Math.min(1, (lossAm + disAm) / Math.max(Am[i], 1e-12)), fAb = Math.min(1, (lossAb + disAb) / Math.max(Ab[i], 1e-12)), fD = Math.min(1, lossD / Math.max(D, 1e-12));
        var xAm = Am[i] * fAm, xAb = Ab[i] * fAb, xD = D * fD;
        var dAm = lossAm + disAm > 0 ? xAm * disAm / (lossAm + disAm) : 0, dAb = lossAb + disAb > 0 ? xAb * disAb / (lossAb + disAb) : 0;
        nAm[i] -= xAm; nAb[i] -= xAb; nDm[i] -= xD * wm; nDb[i] -= xD * wb;
        nDm[i] += dAm; nDb[i] += dAb;      // 被碎片打壞但未解體 → 失效
        // 碎片：依實際移除比例縮放產生量，散布到上下 4 格
        var want = (b.c_am_ab + b.c_am_d + b.c_ab_d + 2 * b.c_ab_ab + 2 * b.c_d_d + F_CAT_IF * (b.c_am_f + b.c_ab_f + b.c_d_f)) * dt;
        var got = (xAm - dAm) + (xAb - dAb) + xD;
        var frag = b.frag * dt * (want > 0 ? Math.min(1, got / want) : 0);
        cum.coll += (b.c_ab_ab + b.c_am_ab + b.c_am_d + b.c_ab_d + b.c_d_d + b.c_am_f + b.c_ab_f + b.c_d_f) * dt * (want > 0 ? Math.min(1, got / want) : 1);
        cum.cat += got > 0 ? (want > 0 ? Math.min(1, got / want) : 0) * (b.c_ab_ab + b.c_am_ab + b.c_am_d + b.c_ab_d + b.c_d_d + F_CAT_IF * (b.c_am_f + b.c_ab_f + b.c_d_f)) * dt : 0;
        if (frag > 0) {
          var wsum = 0;
          for (var o = -4; o <= 4; o++) if (i + o >= 0 && i + o < NB) wsum += KERNEL[o + 4];
          for (var o2 = -4; o2 <= 4; o2++) if (i + o2 >= 0 && i + o2 < NB) nF[i + o2] += frag * KERNEL[o2 + 4] / wsum;
        }
        // 生命週期：失效、任務結束（離軌或留軌）
        var failM = Am[i] * fail * dt, retM = Am[i] * dt / lifeM;
        var failB = Ab[i] * BG.fail * dt, retB = Ab[i] * dt / BG.life;
        var outM = Math.min(nAm[i], failM + retM), outB = Math.min(nAb[i], failB + retB);
        var sM = failM + retM > 0 ? outM / (failM + retM) : 0, sB = failB + retB > 0 ? outB / (failB + retB) : 0;
        nAm[i] -= outM; nAb[i] -= outB;
        nDm[i] += sM * (failM + retM * (1 - pmd)); nDb[i] += sB * (failB + retB * (1 - BG.pmd));
        cum.pmd += sM * retM * pmd + sB * retB * BG.pmd;
        // 大氣阻力：失效衛星與碎片往下一格（200 km 以下再入）
        var fdI = Math.min(1, dt / TBIN[i]), fdF = Math.min(1, dt / (TBIN[i] * FRAG_LIFE));
        var mvDm = Dm[i] * fdI, mvDb = Db[i] * fdI, mvF = F[i] * fdF;
        nDm[i] -= mvDm; nDb[i] -= mvDb; nF[i] -= mvF;
        if (i > 0) { nDm[i - 1] += mvDm; nDb[i - 1] += mvDb; nF[i - 1] += mvF; } else cum.reentry += mvDm + mvDb + mvF;
      }
      for (var j = 0; j < NB; j++) { if (nAm[j] < 0) nAm[j] = 0; if (nAb[j] < 0) nAb[j] = 0; if (nDm[j] < 0) nDm[j] = 0; if (nDb[j] < 0) nDb[j] = 0; if (nF[j] < 0) nF[j] = 0; }
      // 主動移除：每步預算 adr·dt，依「失效顆數 × 該格物件密度」由高到低移除
      var budget = adr * dt;
      if (budget > 0) {
        var order = [];
        for (var j2 = 0; j2 < NB; j2++) order.push([j2, (nDm[j2] + nDb[j2]) * (nAm[j2] + nAb[j2] + nDm[j2] + nDb[j2] + nF[j2]) / VOL[j2]]);
        order.sort(function (a, c) { return c[1] - a[1] || a[0] - c[0]; });
        for (var q = 0; q < order.length && budget > 1e-12; q++) {
          var jj = order[q][0], avail = nDm[jj] + nDb[jj];
          if (avail <= 0) continue;
          var take = Math.min(budget, avail), wmj = nDm[jj] / avail;
          nDm[jj] -= take * wmj; nDb[jj] -= take * (1 - wmj); budget -= take; cum.adr += take;
        }
      }
      // 補發：百萬顆依部署進度、其他營運者維持起始數量
      var tgt = deployed(t0 + k * dt, total), needAll = 0;
      for (var j5 = 0; j5 < NB; j5++) {
        if (share[j5] > 0 && !abandoned[j5] && Am[j5] > 1) {
          var bb = R.bins[j5], lossRate = (bb.c_am_d + bb.c_am_f) / Am[j5];   // 每顆每年碰撞損失（含被打壞失效）
          if (lossRate > ABANDON) { abandoned[j5] = 1; if (firstAbandon == null) firstAbandon = +(t0 + k * dt).toFixed(2); }
        }
      }
      for (var j4 = 0; j4 < NB; j4++) if (!abandoned[j4]) needAll += Math.max(0, share[j4] * tgt - nAm[j4]);
      var scaleL = needAll > 0 ? Math.min(1, lcap * dt / needAll) : 0;
      for (var j3 = 0; j3 < NB; j3++) {
        var need = abandoned[j3] ? 0 : share[j3] * tgt - nAm[j3];
        if (need > 0) { nAm[j3] += need * scaleL; cum.launch += need * scaleL; }
        var needB = Ab0[j3] - nAb[j3];
        if (needB > 0) nAb[j3] += needB;
      }
      Am = nAm; Ab = nAb; Dm = nDm; Db = nDb; F = nF;
      R = rates();
      if (k % 12 === 0) record(k, R);
    }
    // 期末：各格碎片產生率 vs. 阻力移除率（>1 表示碎片自行增加的高度）
    var kessler = [];
    for (var i2 = 0; i2 < NB; i2++) {
      var remove = F[i2] / (TBIN[i2] * FRAG_LIFE);
      kessler.push(remove > 0 ? R.bins[i2].frag / remove : (R.bins[i2].frag > 0 ? Infinity : 0));
    }
    return {
      series: series, alts: alts, cum: cum, first_abandon: firstAbandon,
      end: { act: Array.from(Am).map(function (v, i) { return v + Ab[i]; }), der: Array.from(Dm).map(function (v, i) { return v + Db[i]; }), deb: Array.from(F) },
      start: start, kessler: kessler,
    };
  }
  var CORE = { simulate: simulate, NB: NB, H0: H0, DH: DH, deployed: deployed, shellAlts: shellAlts, life: life, nFrag: nFrag, BG: BG, MILESTONES: MILESTONES, ABANDON: ABANDON };
  window.MEGA_CORE = CORE;

  // ── 介面 ─────────────────────────────────────────────────────────────────
  var host = document.getElementById("mega-panel");
  if (!host) return;
  // window.SDG 在線上版是 3D 地球載入後才建立（非同步），用到時再取
  var sdg = function () { return window.SDG; };
  var fmt = function (x, d) { var S = sdg(); return (S && S.fmt) ? S.fmt(x, d) : (+x).toLocaleString("zh-TW", { maximumFractionDigits: d || 0 }); };
  var PRESETS = [
    { key: "base", name: "基準（沒有百萬顆）", color: "#8b949e", p: { total: 0, fail: 0.01, pmd: 0.9, avoid: 0.99, adr: 0, cap: 1002, mass: 800, life: 5, launch_cap: 3e5 } },
    { key: "strict", name: "百萬顆・嚴格管控", color: "#3fb950", p: { total: 1e6, fail: 0.001, pmd: 0.99, avoid: 0.999, adr: 50, cap: 1002, mass: 800, life: 5, launch_cap: 3e5 } },
    { key: "loose", name: "百萬顆・寬鬆管控", color: "#ff7b72", p: { total: 1e6, fail: 0.01, pmd: 0.9, avoid: 0.99, adr: 0, cap: 1002, mass: 800, life: 5, launch_cap: 3e5 } },
    { key: "cap600", name: "百萬顆・限 600 km 以下", color: "#58a6ff", p: { total: 1e6, fail: 0.001, pmd: 0.99, avoid: 0.999, adr: 50, cap: 600, mass: 800, life: 5, launch_cap: 3e5 } },
    { key: "extreme", name: "百萬顆・極嚴格（≤600 km、離軌 99.9%）", color: "#f2cc60", p: { total: 1e6, fail: 0.0005, pmd: 0.999, avoid: 0.9999, adr: 200, cap: 600, mass: 800, life: 5, launch_cap: 3e5 } },
    { key: "custom", name: "自訂", color: "#a371f7", p: null },
  ];
  var METRICS = [
    ["F", "碎片（≥10 cm）總數", true], ["D", "失效衛星與火箭體", true], ["coll", "每年碰撞次數（期望值）", true],
    ["enc_per_sat", "每顆運作中衛星每年 1 km 內接近次數", true], ["Am", "百萬顆星座運作中顆數", false],
  ];
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  host.innerHTML =
    "<div class='q' style='font-weight:600;margin:4px 0'>🌐 百萬顆衛星：長期風險與管控</div>" +
    "<div class='hint' style='white-space:normal'>美國 FCC 於 2026-11-25 有條件核准 SpaceX 部署最多 100 萬顆軌道資料中心衛星（Starmind），里程碑為 2033-11 開始、2035-11 達 10 萬顆、2038-11 達 50 萬顆、2040-11 達 100 萬顆；" +
    "六個殼層位於 500–1,002 km，600 km 以上需另提碎片減緩計畫。這裡用分殼層統計模型估算 50 年內碎片、碰撞與避碰負荷的量級，比較不同管控情境。" +
    " 出處：<a href='https://www.cnbc.com/2026/11/25/spacex-fcc-satellite-approval.html' target='_blank' rel='noopener'>CNBC</a>、" +
    "<a href='https://www.geekwire.com/2026/fcc-clears-spacex-million-satellites-starmind-data-center/' target='_blank' rel='noopener'>GeekWire</a>、" +
    "<a href='https://www.esa.int/Space_Safety/Space_Debris/ESA_Space_Environment_Report_2026' target='_blank' rel='noopener'>ESA 2026 太空環境報告</a>。</div>" +
    "<div style='margin-top:6px'>情境：" + PRESETS.map(function (s) {
      return "<label class='chk' style='display:inline-block;margin-right:8px'><input type='checkbox' class='mg-sc' value='" + s.key + "'" + (s.key !== "custom" ? " checked" : "") +
        "> <span style='color:" + s.color + "'>●</span> " + s.name + "</label>";
    }).join("") + "</div>" +
    "<details id='mg-custom' style='margin-top:4px'><summary class='hint' style='cursor:pointer'>自訂情境參數（勾選「自訂」才會計算）</summary><table class='kv'>" +
    [["mg-total", "部署規模（顆）", 1000000, 0, 1000000, 10000], ["mg-fail", "年失效率（%）", 0.5, 0, 10, 0.1], ["mg-pmd", "任務結束離軌成功率（%）", 95, 0, 100, 0.5],
     ["mg-avoid", "避碰成功率（%）", 99.9, 0, 100, 0.1], ["mg-adr", "每年主動移除失效衛星（顆）", 20, 0, 5000, 10], ["mg-cap", "殼層高度上限（km）", 1002, 500, 1002, 10],
     ["mg-mass", "每顆質量（kg）", 800, 50, 5000, 50], ["mg-life", "任務壽命（年）", 5, 1, 20, 1], ["mg-lcap", "每年最多發射（顆）", 300000, 0, 2000000, 10000]].map(function (r) {
      return "<tr><td>" + r[1] + "</td><td><input type='number' id='" + r[0] + "' value='" + r[2] + "' min='" + r[3] + "' max='" + r[4] + "' step='" + r[5] + "' style='width:96px'></td></tr>";
    }).join("") + "</table></details>" +
    "<div class='row act' style='margin-top:6px'><label>模擬年數</label><select id='mg-years'><option>30</option><option selected>50</option><option>100</option></select>" +
    " <button class='go' id='mg-run'>計算</button></div>" +
    "<div class='row'><label>圖表</label><select id='mg-metric' style='max-width:100%'>" + METRICS.map(function (m) { return "<option value='" + m[0] + "'>" + m[1] + "</option>"; }).join("") + "</select></div>" +
    "<canvas id='mg-chart' width='760' height='300' style='width:100%;background:#0b1622;border:1px solid var(--line);border-radius:6px;margin-top:6px'></canvas>" +
    "<div id='mg-res' class='hint'>按「計算」比較各情境（瀏覽器端計算，約 0.1 秒）。</div>" +
    "<canvas id='mg-prof' width='760' height='240' style='width:100%;background:#0b1622;border:1px solid var(--line);border-radius:6px;margin-top:6px'></canvas>" +
    "<label class='chk'><input type='checkbox' id='mg-3d'> 3D 抽樣顯示百萬顆殼層（3 萬點示意）</label>" +
    "<div class='hint' style='white-space:normal;margin-top:4px'>模型假設：其他營運者維持現有數量（年失效率 0.5%、壽命 7 年、離軌成功率 95%、避碰成功率 99%）；完整物體半徑 2 m、碎片 10 cm；" +
    "運作中衛星彼此以協調避免互撞（不計）；碎片撞上完整物體 10% 解體、其餘使衛星失效；百萬顆星座每年最多發射 30 萬顆（預設，含補發），某高度碰撞損失每年超過 20% 即放棄該高度；目錄背景依 SATCAT（酬載發射 8 年內視為運作中，其餘酬載、火箭體為失效；碎片僅含已編目 ≥10 cm）。" +
    "平均場模型不含軌道面相位、個別事件的隨機性與無法編目的小碎片；數字達到數十萬以上代表模型已進入失控區，實際上該高度在此之前就難以使用，請看各情境的相對差異與出現時間，不是預測。</div>";

  var BGDATA = null, LAST = null, pc = null;
  function $(id) { return document.getElementById(id); }
  function params(key) {
    var s = PRESETS.find(function (x) { return x.key === key; }), p;
    if (s.p) p = Object.assign({}, s.p);
    else p = { total: +$("mg-total").value, fail: +$("mg-fail").value / 100, pmd: +$("mg-pmd").value / 100, avoid: +$("mg-avoid").value / 100,
      adr: +$("mg-adr").value, cap: +$("mg-cap").value, mass: +$("mg-mass").value, life: +$("mg-life").value, launch_cap: +$("mg-lcap").value };
    p.years = +$("mg-years").value;
    var d = new Date(); p.t0 = d.getUTCFullYear() + (d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 31557600000;
    return p;
  }
  function loadBg() {
    if (BGDATA) return Promise.resolve(BGDATA);
    return fetch("/api/games/mega/background").then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) throw new Error(d.error);
      BGDATA = d; return d;
    });
  }
  function run() {
    var btn = $("mg-run"); btn.disabled = true; $("mg-res").textContent = "計算中…";
    loadBg().then(function (bg) {
      var t = performance.now(), keys = Array.prototype.map.call(document.querySelectorAll(".mg-sc:checked"), function (c) { return c.value; });
      if (!keys.length) { $("mg-res").textContent = "請至少勾選一個情境"; btn.disabled = false; return; }
      LAST = keys.map(function (k) { var s = PRESETS.find(function (x) { return x.key === k; }); return { s: s, r: simulate(bg, params(k)) }; });
      chart(); profile(); table(performance.now() - t, bg); btn.disabled = false; show3d();
    }).catch(function (e) { $("mg-res").textContent = "計算失敗：" + e.message; btn.disabled = false; });
  }
  function num(x) { return x >= 1e4 ? fmt(Math.round(x)) : x >= 100 ? fmt(x, 0) : x >= 1 ? fmt(x, 1) : x >= 0.01 ? fmt(x, 3) : x > 0 ? x.toExponential(1) : "0"; }
  function chart() {
    var key = $("mg-metric").value, cv = $("mg-chart"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 70, Rm = 12, T = 16, B = 30;
    var log = METRICS.find(function (m) { return m[0] === key; })[2], xs = LAST[0].r.series, x0 = xs[0].year, x1 = xs[xs.length - 1].year;
    var vmax = 0, vmin = Infinity;
    LAST.forEach(function (o) { o.r.series.forEach(function (s) { var v = s[key]; if (v > vmax) vmax = v; if (v > 0 && v < vmin) vmin = v; }); });
    if (!(vmax > 0)) { vmax = 1; vmin = 0.1; }
    var y0 = log ? Math.floor(Math.log10(Math.max(vmin, vmax * 1e-6))) : 0, y1 = log ? Math.ceil(Math.log10(vmax)) : vmax * 1.08;
    if (log && y1 <= y0) y1 = y0 + 1;
    var X = function (x) { return L + (x - x0) / (x1 - x0) * (W - L - Rm); };
    var Y = function (v) { var t = log ? (Math.log10(Math.max(v, Math.pow(10, y0))) - y0) / (y1 - y0) : v / y1; return H - B - t * (H - T - B); };
    g.clearRect(0, 0, W, H); g.font = "12px 'Microsoft JhengHei',sans-serif"; g.strokeStyle = "#30363d"; g.fillStyle = "#8b949e"; g.lineWidth = 1;
    if (log) for (var e = y0; e <= y1; e++) { g.beginPath(); g.moveTo(L, Y(Math.pow(10, e))); g.lineTo(W - Rm, Y(Math.pow(10, e))); g.stroke(); g.textAlign = "right"; g.fillText("1e" + e, L - 6, Y(Math.pow(10, e)) + 4); }
    else for (var q = 0; q <= 4; q++) { var v = y1 * q / 4; g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - Rm, Y(v)); g.stroke(); g.textAlign = "right"; g.fillText(num(v), L - 6, Y(v) + 4); }
    for (var yr = Math.ceil(x0 / 10) * 10; yr <= x1; yr += 10) { g.beginPath(); g.moveTo(X(yr), T); g.lineTo(X(yr), H - B); g.stroke(); g.textAlign = "center"; g.fillText(yr, X(yr), H - B + 16); }
    LAST.forEach(function (o, n) {
      g.strokeStyle = o.s.color; g.lineWidth = 2; g.beginPath();
      o.r.series.forEach(function (s, i) { var px = X(s.year), py = Y(s[key]); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
      g.stroke(); g.fillStyle = o.s.color; g.textAlign = "left"; g.fillText(o.s.name, L + 8, T + 14 + n * 15);
    });
  }
  function profile() {
    var cv = $("mg-prof"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 70, Rm = 12, T = 16, B = 30, h0 = 200, h1 = 2000;
    var y0 = 0, y1 = 6;
    var X = function (h) { return L + (h - h0) / (h1 - h0) * (W - L - Rm); };
    var Y = function (v) { var t = (Math.log10(Math.max(v, 1)) - y0) / (y1 - y0); return H - B - Math.min(1, t) * (H - T - B); };
    g.clearRect(0, 0, W, H); g.font = "12px 'Microsoft JhengHei',sans-serif"; g.strokeStyle = "#30363d"; g.fillStyle = "#8b949e"; g.lineWidth = 1;
    for (var e = y0; e <= y1; e += 2) { g.beginPath(); g.moveTo(L, Y(Math.pow(10, e))); g.lineTo(W - Rm, Y(Math.pow(10, e))); g.stroke(); g.textAlign = "right"; g.fillText("1e" + e, L - 6, Y(Math.pow(10, e)) + 4); }
    for (var h = 400; h <= h1; h += 200) { g.beginPath(); g.moveTo(X(h), T); g.lineTo(X(h), H - B); g.stroke(); g.textAlign = "center"; g.fillText(h + " km", X(h), H - B + 16); }
    g.textAlign = "left"; g.fillStyle = "#8b949e"; g.fillText("期末各高度碎片數（每 25 km；虛線為現況）", L + 8, T + 2);
    var first = LAST[0].r;
    g.setLineDash([4, 3]); g.strokeStyle = "#6e7681"; g.beginPath();
    first.start.deb.forEach(function (v, i) { var px = X(h0 + 25 * (i + 0.5)); if (i) g.lineTo(px, Y(v)); else g.moveTo(px, Y(v)); }); g.stroke(); g.setLineDash([]);
    LAST.forEach(function (o) {
      g.strokeStyle = o.s.color; g.lineWidth = 1.8; g.beginPath();
      o.r.end.deb.forEach(function (v, i) { var px = X(h0 + 25 * (i + 0.5)); if (i) g.lineTo(px, Y(v)); else g.moveTo(px, Y(v)); }); g.stroke();
    });
  }
  function table(ms, bg) {
    var marks = [10, 25, 50, 100].filter(function (y) { return y <= +$("mg-years").value; });
    var h = "<div style='overflow-x:auto'><table class='kv' style='white-space:nowrap'><tr><td>情境</td><td>年</td><td>碎片 ≥10 cm</td><td>失效衛星</td><td>年碰撞</td><td>累計碰撞</td><td>每顆年接近</td><td>百萬顆運作中</td><td>放棄殼層</td><td>失控高度</td></tr>";
    LAST.forEach(function (o) {
      var r = o.r, bad = r.kessler.filter(function (x) { return x > 1; }).length;
      marks.forEach(function (y, n) {
        var s = r.series[Math.min(y, r.series.length - 1)];
        h += "<tr><td>" + (n ? "" : "<span style='color:" + o.s.color + "'>●</span> " + esc(o.s.name)) + "</td><td>+" + y + "</td><td>" + num(s.F) + "</td><td>" + num(s.D) +
          "</td><td>" + num(s.coll) + "</td><td>" + num(s.cum_coll) + "</td><td>" + num(s.enc_per_sat) + "</td><td>" + num(s.Am) + "</td><td>" + (s.abandoned ? s.abandoned + " 格" : "—") +
          "</td><td>" + (n === marks.length - 1 ? bad + " 格" : "") + "</td></tr>";
      });
    });
    h += "</table></div><div class='hint' style='white-space:normal'>左右捲動可看全部欄位。「每顆年接近」為運作中衛星每年與其他物件相距 1 km 內的幾何接近次數（避碰負荷的代理值）；" +
      "「放棄殼層」為碰撞損失每年超過 20%、營運者停止補發的 25 km 高度格數；「失控高度」為期末碎片產生率超過大氣移除率的高度格數（碎片會自行增加）。" +
      LAST.filter(function (o) { return o.r.first_abandon; }).map(function (o) { return esc(o.s.name) + "：" + Math.floor(o.r.first_abandon) + " 年起開始放棄殼層"; }).join("；") + " 目錄背景：" + fmt(bg.total) + " 個物件（" + esc(bg.source || "SATCAT") +
      "）。計算 " + ms.toFixed(0) + " 毫秒。</div>";
    $("mg-res").innerHTML = h;
  }
  // 3D 抽樣：依情境殼層（取第一個有部署的情境）放 3 萬點，Walker 分布、慣性座標靜態示意
  function show3d() {
    var SDG = sdg();
    if (!SDG || !SDG.viewer || typeof Cesium === "undefined") { if ($("mg-3d").checked) $("mg-res").insertAdjacentHTML("beforeend", "<div class='hint'>3D 地球尚未載入完成，請稍後再勾選。</div>"); return; }
    var on = $("mg-3d").checked;
    if (pc) { SDG.viewer.scene.primitives.remove(pc); pc = null; }
    SDG.viewer.scene.requestRender();   // 線上版使用 requestRenderMode，變更後要主動重繪
    if (!on) return;
    var o = (LAST || []).find(function (x) { return x.r.series.some(function (s) { return s.Am > 0; }); });
    var alts = o ? o.r.alts : SHELLS0, incs = [53, 53, 70, 97.6, 53, 97.6], cols = ["#3fa7ff", "#58d68d", "#f5b041", "#ec7063", "#af7ac5", "#48c9b0"];
    pc = SDG.viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
    var N = 30000, per = N / 6, planes = 60, perPlane = Math.round(per / planes);
    for (var s = 0; s < 6; s++) {
      var a = (6378.137 + alts[s]) * 1000, inc = incs[s] * Math.PI / 180, col = Cesium.Color.fromCssColorString(cols[s]).withAlpha(0.8);
      for (var pI = 0; pI < planes; pI++) for (var q = 0; q < perPlane; q++) {
        var om = 2 * Math.PI * pI / planes + s * 0.37, u = 2 * Math.PI * (q / perPlane + pI / (planes * perPlane)) + s * 0.61;
        var co = Math.cos(om), so = Math.sin(om), cu = Math.cos(u), su = Math.sin(u), ci = Math.cos(inc), si = Math.sin(inc);
        pc.add({ position: new Cesium.Cartesian3(a * (co * cu - so * su * ci), a * (so * cu + co * su * ci), a * su * si), pixelSize: 2, color: col });
      }
    }
    SDG.viewer.scene.requestRender();
    if (SDG.status) SDG.status("百萬顆殼層抽樣 " + fmt(N) + " 點（高度 " + alts.map(function (h) { return Math.round(h); }).join("／") + " km；傾角為示意）");
  }
  $("mg-run").onclick = run;
  $("mg-metric").onchange = function () { if (LAST) chart(); };
  $("mg-3d").onchange = show3d;
  document.addEventListener("sdg-tab", function (e) { if (pc) { pc.show = e.detail === "crowd" || e.detail === "debris"; var S = sdg(); if (S && S.viewer) S.viewer.scene.requestRender(); } });
})();
