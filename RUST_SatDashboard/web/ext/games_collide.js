/* 太空小遊戲：兩顆衛星以不同接近角相撞——碎片的軌道分布（單機版「碎片連鎖」分頁、線上版 /game；兩版共用同一份檔案）
 *
 * 計算全部在瀏覽器端，結果只由參數與亂數種子決定。
 *  - 幾何：兩顆衛星都在同一高度的圓軌道，碰撞點在指定緯度。衛星 A 的速度方向由傾角與緯度決定（升軌段），
 *    衛星 B 的速度是把 A 的速度繞當地鉛垂線轉「接近角 θ」。兩者速率相同，相對速度 = 2v·sin(θ/2)。
 *  - 解體：NASA 標準解體模型（Johnson et al. 2001），與碎片連鎖引擎（src/debris_engine.rs）相同的公式：
 *    能量質量比 EMR = ½·m小·v相對²／m大 > 40 J/g 為完全解體；碎片數 N(≥Lc) = 0.1·M^0.75·Lc^−1.71，
 *    完全解體時 M = 兩顆質量和，否則 M = m小·v相對²（kg、km/s）；面積質量比依尺寸的雙峰分布、
 *    Δv 對數常態（μ = 0.9·log₁₀(A/M) + 2.9、σ = 0.4；預設不截斷＝SBM 原始，可選與引擎相同的 Cosmos 1408 校準：μ+1σ 以上重抽）；
 *    各母體的碎片質量與動量守恆。非完全解體的拋出質量可選教學假設、固定比例或不產生碎片（都不是 SBM 標準）。
 *  - 多種子：每個接近角跑 N 個種子，比較表列中位數與 5–95% 區間；圖表與 3D 為第一個種子的樣本。
 *  - 碎片的速度基準（可切換）：
 *    「各自母體」——每顆衛星的碎片沿用該衛星的速度再加 Δv（預設）。2009 年 Iridium 33–Cosmos 2251 碰撞後
 *    觀測到兩團碎片分別沿兩顆母體原本的軌道面散開，這個假設與觀測相符。
 *    「共同質心」——所有碎片沿用兩顆衛星的質量加權平均速度（碎片連鎖引擎的連鎖碰撞目前用這個）。
 *    迎頭相撞時質心速度很小，碎片會大量落入大氣，可對照看假設的影響。
 *  - 軌道：碎片速度 → 克卜勒根數（近地點、遠地點、週期、傾角）；近地點低於 120 km 視為立即再入。
 *    3D 用克卜勒＋J2 長期項傳播，慣性座標示意。
 *  - 壽命粗估：等效高度 = 近地點 + ¼(遠地點 − 近地點)，查中等太陽活動、面積質量比 0.01 m²/kg 的軌道壽命表，
 *    再依碎片的面積質量比反比縮放。只是量級，精確的長期演化請用上方的「引爆」模擬。 */
(function () {
  "use strict";
  // ── 計算核心（純函式，供測試直接呼叫：window.COLLIDE_CORE）──────────────────
  var MU = 398600.4418, RE = 6378.137, J2 = 1.08262668e-3, TAU = 2 * Math.PI, D2R = Math.PI / 180;
  var REENTRY_KM = 120, NMAX = 20000;
  var LIFE = [[200, -1.6], [300, -0.7], [400, 0.2], [500, 1.0], [600, 1.6], [700, 2.1], [800, 2.5], [900, 2.8], [1000, 3.1], [1200, 3.5], [1500, 3.9], [2000, 4.3]];

  function Rng(seed) { this.s = BigInt.asUintN(64, BigInt(Math.max(1, Math.floor(seed)))); }
  Rng.prototype.next = function () {   // splitmix64（與引擎同一個產生器）
    this.s = BigInt.asUintN(64, this.s + 0x9E3779B97F4A7C15n);
    var z = this.s;
    z = BigInt.asUintN(64, (z ^ (z >> 30n)) * 0xBF58476D1CE4E5B9n);
    z = BigInt.asUintN(64, (z ^ (z >> 27n)) * 0x94D049BB133111EBn);
    return Number((z ^ (z >> 31n)) >> 11n) / 9007199254740992;
  };
  Rng.prototype.normal = function () { var u1 = Math.max(this.next(), 1e-300), u2 = this.next(); return Math.sqrt(-2 * Math.log(u1)) * Math.cos(TAU * u2); };
  Rng.prototype.dir = function () { var z = 2 * this.next() - 1, t = TAU * this.next(), r = Math.sqrt(1 - z * z); return [r * Math.cos(t), r * Math.sin(t), z]; };

  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function norm(a) { return Math.sqrt(dot(a, a)); }
  function add(a, b, k) { k = k == null ? 1 : k; return [a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2]]; }
  function scale(a, k) { return [a[0] * k, a[1] * k, a[2] * k]; }

  // 面積質量比分布（NASA SBM，尺寸 L 公尺 → A/M m²/kg），與引擎 am_dist 相同
  function amDist(rng, l) {
    var x = Math.log10(l);
    if (l < 0.11) {
      var mu = x <= -1.75 ? -0.3 : x < -1.25 ? -0.3 - 1.4 * (x + 1.75) : -1.0;
      var sg = x <= -3.5 ? 0.2 : 0.2 + 0.1333 * (x + 3.5);
      return Math.pow(10, mu + sg * rng.normal());
    }
    var alpha = x <= -1.95 ? 0 : x < 0.55 ? 0.3 + 0.4 * (x + 1.2) : 1;
    var mu1 = x <= -1.1 ? -0.6 : x < 0 ? -0.6 - 0.318 * (x + 1.1) : -0.95;
    var s1 = x <= -1.3 ? 0.1 : x < -0.3 ? 0.1 + 0.2 * (x + 1.3) : 0.3;
    var mu2 = x <= -0.7 ? -1.2 : x < -0.1 ? -1.2 - 1.333 * (x + 0.7) : -2.0;
    var s2 = x <= -0.5 ? 0.5 : x < -0.3 ? 0.5 - (x + 0.5) : 0.3;
    var lg = rng.next() < alpha ? mu1 + s1 * rng.normal() : mu2 + s2 * rng.normal();
    return Math.pow(10, lg);
  }
  function area(l) { return l < 0.00167 ? 0.540424 * l * l : 0.556945 * Math.pow(l, 2.0047077); }

  // 一個母體的碎片：n 個、尺寸 ≥ lc 依冪律（指數 1.71）抽樣，質量縮放到 mTotal、扣掉質量加權平均 Δv（動量守恆）
  function fragments(rng, n, lc, mTotal, dvk) {
    var b = 1.71, lmax = Math.min(10, Math.max(0.1, Math.cbrt(mTotal / 100), lc * 1.01)), pmin = Math.pow(lmax / lc, -b), fr = [], i, k;
    for (i = 0; i < n; i++) {
      var u = pmin + (1 - pmin) * rng.next(), l = lc * Math.pow(u, -1 / b), am = amDist(rng, l), chi = Math.log10(am);
      var z = rng.normal(), tries = 0;
      while (z > dvk && tries < 50) { z = rng.normal(); tries++; }
      var dvm = Math.pow(10, 0.9 * chi + 2.9 + 0.4 * Math.min(z, dvk)) / 1000;   // km/s
      fr.push({ l: l, am: am, mass: area(l) / am, dv: scale(rng.dir(), dvm) });
    }
    var ms = fr.reduce(function (s, f) { return s + f.mass; }, 0), s = mTotal / Math.max(ms, 1e-9), p = [0, 0, 0];
    fr.forEach(function (f) { f.mass *= s; f.am = area(f.l) / f.mass; for (k = 0; k < 3; k++) p[k] += f.mass * f.dv[k]; });
    fr.forEach(function (f) { for (k = 0; k < 3; k++) f.dv[k] -= p[k] / mTotal; f.dvm = norm(f.dv); });
    return fr;
  }

  // 位置、速度 → 根數（a km、e、i、Ω、ω、M0 弧度）
  function elements(r, v) {
    var rn = norm(r), h = cross(r, v), hn = norm(h), en = dot(v, v) / 2 - MU / rn;
    if (en >= 0 || hn < 1e-6) return null;
    var a = -MU / (2 * en), vxh = cross(v, h), ev = [vxh[0] / MU - r[0] / rn, vxh[1] / MU - r[1] / rn, vxh[2] / MU - r[2] / rn];
    var e = Math.min(norm(ev), 0.999), i = Math.acos(Math.max(-1, Math.min(1, h[2] / hn)));
    var nv = [-h[1], h[0], 0], nn = norm(nv);
    var raan = nn > 1e-9 ? (Math.atan2(nv[1], nv[0]) + TAU) % TAU : 0;
    var argp = 0, nu;
    if (nn > 1e-9 && e > 1e-9) { argp = Math.acos(Math.max(-1, Math.min(1, dot(nv, ev) / (nn * e)))); if (ev[2] < 0) argp = TAU - argp; }
    if (e > 1e-9) { nu = Math.acos(Math.max(-1, Math.min(1, dot(ev, r) / (e * rn)))); if (dot(r, v) < 0) nu = TAU - nu; }
    else { nu = nn > 1e-9 ? Math.acos(Math.max(-1, Math.min(1, dot(nv, r) / (nn * rn)))) : 0; if (r[2] < 0) nu = TAU - nu; }
    var ea = 2 * Math.atan(Math.sqrt((1 - e) / (1 + e)) * Math.tan(nu / 2)), m0 = ((ea - e * Math.sin(ea)) % TAU + TAU) % TAU;
    var n = Math.sqrt(MU / (a * a * a)), p = a * (1 - e * e), kk = 1.5 * J2 * Math.pow(RE / p, 2) * n, si2 = Math.pow(Math.sin(i), 2);
    return { a: a, e: e, i: i, raan: raan, argp: argp, m0: m0, hp: a * (1 - e) - RE, ha: a * (1 + e) - RE, period: TAU / n / 60,
      rd: -kk * Math.cos(i), wd: kk * (2 - 2.5 * si2), md: n + kk * Math.sqrt(1 - e * e) * (1 - 1.5 * si2) };
  }
  // 根數在 t 秒後的位置（km，慣性座標）
  function position(el, t) {
    var m = el.m0 + el.md * t, raan = el.raan + el.rd * t, w = el.argp + el.wd * t, e = el.e, ea = e < 0.8 ? m : Math.PI;
    for (var k = 0; k < 8; k++) ea -= (ea - e * Math.sin(ea) - m) / (1 - e * Math.cos(ea));
    var xp = el.a * (Math.cos(ea) - e), yp = el.a * Math.sqrt(1 - e * e) * Math.sin(ea);
    var co = Math.cos(raan), so = Math.sin(raan), cw = Math.cos(w), sw = Math.sin(w), ci = Math.cos(el.i), si = Math.sin(el.i);
    var P = [co * cw - so * sw * ci, so * cw + co * sw * ci, sw * si], Q = [-co * sw - so * cw * ci, -so * sw + co * cw * ci, cw * si];
    return [xp * P[0] + yp * Q[0], xp * P[1] + yp * Q[1], xp * P[2] + yp * Q[2]];
  }
  function life(h) {
    if (h <= LIFE[0][0]) return Math.pow(10, LIFE[0][1]);
    for (var i = 1; i < LIFE.length; i++) if (h <= LIFE[i][0]) {
      var a = LIFE[i - 1], b = LIFE[i];
      return Math.pow(10, a[1] + (b[1] - a[1]) * (h - a[0]) / (b[0] - a[0]));
    }
    return Math.pow(10, LIFE[LIFE.length - 1][1]);
  }
  function lifeOf(f) { var he = f.hp + 0.25 * Math.max(0, f.ha - f.hp); return life(he) * 0.01 / f.am; }

  // 碰撞幾何：A 在緯度 lat 的升軌段，B 的速度為 A 繞當地鉛垂線轉 θ
  function geometry(h, incA, lat, theta) {
    var r = RE + h, v = Math.sqrt(MU / r), i = incA * D2R, lim = Math.min(incA, 180 - incA);
    var phi = Math.max(-lim, Math.min(lim, lat)) * D2R;
    var R = [Math.cos(phi), 0, Math.sin(phi)], east = [0, 1, 0], north = [-Math.sin(phi), 0, Math.cos(phi)];
    var sb = Math.max(-1, Math.min(1, Math.cos(i) / Math.cos(phi))), cb = Math.sqrt(1 - sb * sb);
    var uA = add(scale(north, cb), east, sb), th = theta * D2R;
    var uB = add(scale(uA, Math.cos(th)), cross(R, uA), Math.sin(th));
    var rv = scale(R, r), vA = scale(uA, v), vB = scale(uB, v), hB = cross(rv, vB);
    return { r: rv, vA: vA, vB: vB, v: v, lat: phi / D2R, incB: Math.acos(hB[2] / norm(hB)) / D2R };
  }

  function pct(arr, q) { if (!arr.length) return NaN; var s = arr.slice().sort(function (a, b) { return a - b; }); return s[Math.min(s.length - 1, Math.floor(q * s.length))]; }

  /** p: { h, incA, lat, mA, mB, theta, lc（公尺）, frame: "parent" | "cm", seed, dvk（Δv 截斷點，預設 Infinity＝SBM 原始）,
   *       ejecta: "edu" | "fraction" | "none"（非完全解體拋出質量）, ejecta_frac } */
  function simulate(p) {
    var g = geometry(p.h, p.incA, p.lat, p.theta), rng = new Rng((p.seed || 7) * 1000 + Math.round(p.theta * 10));
    var mA = p.mA, mB = p.mB, lc = p.lc || 0.1, aBig = mA >= mB, mb = Math.max(mA, mB), ms = Math.min(mA, mB);
    var dvk = p.dvk == null ? Infinity : p.dvk, ejm = p.ejecta || "edu";
    var vrel = norm(add(g.vA, g.vB, -1)), emr = 0.5 * ms * Math.pow(vrel * 1000, 2) / mb / 1000, cat = emr > 40;
    var vBig = aBig ? g.vA : g.vB, vSmall = aBig ? g.vB : g.vA, vcm = scale(add(scale(g.vA, mA), g.vB, mB), 1 / (mA + mB));
    var parts, M;
    if (cat) {
      M = mA + mB;
      parts = [{ who: "A", m: mA, v: g.vA }, { who: "B", m: mB, v: g.vB }];
    } else {
      M = ms * vrel * vrel;
      // 撞出的質量（與引擎的 ejecta 設定相同；都不是 SBM 標準）；小的一顆全毀，大的一顆受損但存活
      var ej = ejm === "none" ? 0 : ejm === "fraction" ? mb * Math.min(0.5, Math.max(0, p.ejecta_frac == null ? 0.01 : p.ejecta_frac)) : Math.min(M / 100, mb * 0.5);
      parts = ejm === "none" ? [] : [{ who: aBig ? "B" : "A", m: ms, v: vSmall }, { who: aBig ? "A" : "B", m: ej, v: vBig }].filter(function (x) { return x.m > 0; });
    }
    var mPart = parts.reduce(function (s, x) { return s + x.m; }, 0);
    var nAll = parts.length ? 0.1 * Math.pow(M, 0.75) * Math.pow(lc, -1.71) : 0, w = Math.max(1, nAll / NMAX), frs = [];
    parts.forEach(function (pt) {
      var n = Math.round(nAll * pt.m / mPart / w), base = p.frame === "cm" ? (cat ? vcm : vBig) : pt.v;
      if (n < 1) return;
      fragments(rng, n, lc, pt.m, dvk).forEach(function (f) {
        var el = elements(g.r, add(base, f.dv));
        if (!el) { frs.push({ who: pt.who, escape: true, am: f.am, dvm: f.dvm }); return; }
        el.who = pt.who; el.am = f.am; el.l = f.l; el.dvm = f.dvm; el.reentry = el.hp < REENTRY_KM;
        el.life = el.reentry ? 0 : lifeOf(el);
        frs.push(el);
      });
    });
    var ok = frs.filter(function (f) { return !f.escape && !f.reentry; });
    var frac = function (fn) { return ok.length ? frs.filter(function (f) { return !f.escape && !f.reentry && fn(f); }).length / frs.length : 0; };
    var incs = function (who) { return ok.filter(function (f) { return !who || f.who === who; }).map(function (f) { return f.i / D2R; }); };
    var iA = incs("A"), iB = incs("B");
    return {
      p: p, geom: g, vrel: vrel, emr: emr, catastrophic: cat, n_total: nAll, weight: w, frags: frs,
      survivor: cat ? null : (aBig ? "A" : "B"),
      stats: {
        n_sim: frs.length, n_A: frs.filter(function (f) { return f.who === "A"; }).length, n_B: frs.filter(function (f) { return f.who === "B"; }).length,
        reentry_now: frs.filter(function (f) { return f.reentry || f.escape; }).length / Math.max(1, frs.length),
        inc_A: [pct(iA, 0.05), pct(iA, 0.5), pct(iA, 0.95)], inc_B: [pct(iB, 0.05), pct(iB, 0.5), pct(iB, 0.95)],
        hp: [pct(ok.map(function (f) { return f.hp; }), 0.05), pct(ok.map(function (f) { return f.hp; }), 0.5)],
        ha: [pct(ok.map(function (f) { return f.ha; }), 0.5), pct(ok.map(function (f) { return f.ha; }), 0.95)],
        dv_med: pct(frs.map(function (f) { return f.dvm * 1000; }), 0.5),
        life_lt1: frac(function (f) { return f.life < 1; }), life_gt25: frac(function (f) { return f.life > 25; }), life_gt100: frac(function (f) { return f.life > 100; }),
        cross_iss: frac(function (f) { return f.hp <= 420 && f.ha >= 420; }), cross_550: frac(function (f) { return f.hp <= 550 && f.ha >= 550; }),
      },
    };
  }
  // 多種子：同參數跑 n 個種子（seed, seed+1, …），回傳第一個種子的完整結果與各比例指標的中位數、5–95% 區間
  var ENS_KEYS = ["reentry_now", "life_lt1", "life_gt25", "life_gt100", "cross_iss", "cross_550", "dv_med"];
  function ensemble(p, n) {
    var runs = [], k;
    for (k = 0; k < Math.max(1, n); k++) runs.push(simulate(Object.assign({}, p, { seed: (p.seed || 7) + k })));
    var r0 = runs[0], ens = { n: runs.length };
    ENS_KEYS.concat(["hp_med", "ha_95"]).forEach(function (key) {
      var v = runs.map(function (r) { return key === "hp_med" ? r.stats.hp[1] : key === "ha_95" ? r.stats.ha[1] : r.stats[key]; }).filter(Number.isFinite);
      ens[key] = [pct(v, 0.05), pct(v, 0.5), pct(v, 0.95)];
    });
    r0.ens = ens;
    return r0;
  }
  var CORE = { simulate: simulate, ensemble: ensemble, geometry: geometry, elements: elements, position: position, life: life, Rng: Rng };
  window.COLLIDE_CORE = CORE;

  // ── 介面 ─────────────────────────────────────────────────────────────────
  var host = document.getElementById("collide-panel");
  if (!host) return;
  var sdg = function () { return window.SDG; };
  var fmt = function (x, d) { var S = sdg(); return (S && S.fmt) ? S.fmt(x, d) : (+x).toLocaleString("zh-TW", { maximumFractionDigits: d || 0 }); };
  var pctS = function (x) { return (x * 100 >= 10 || x === 0 ? Math.round(x * 100) : (x * 100).toFixed(1)) + "%"; };
  var COL = { A: "#58a6ff", B: "#f0883e" };
  var PRESETS = {
    iridium: { name: "Iridium 33–Cosmos 2251（2009，教學近似）", h: 789, incA: 86.4, lat: 72.5, mA: 560, mB: 900, angles: "10, 45, 90, 103, 135, 180",
      note: "2009-02-10 於西伯利亞上空約 789 km 相撞，相對速度約 11.7 km/s（接近角約 103°）。Iridium 33 約 560 kg、Cosmos 2251 約 900 kg。" +
        "量級檢查（不是模型驗證）：模型 ≥10 cm 約 1,200 件；SATCAT（Space-Track，2026-11-26 擷取）中國際編號 1993-036（Cosmos 2251）的碎片 1,716 件、" +
        "1997-051（Iridium 33 所屬發射，可能含同次發射的其他碎片）656 件，含已再入者。口徑不同：編目門檻約 10 cm 但不精確、編目隨時間增加、國際編號歸屬不一定等於碰撞產生；尚未以已發表文獻作第二來源。" },
    leo550: { name: "兩顆 1,000 kg 衛星在 550 km（Starlink 殼層高度）", h: 550, incA: 53, lat: 30, mA: 1000, mB: 1000, angles: "10, 45, 90, 135, 180", note: "低軌壅擠高度；比較碎片多快被大氣拖下來。" },
    small: { name: "1 kg 碎片撞 1,000 kg 衛星（非完全解體）", h: 800, incA: 98, lat: 40, mA: 1000, mB: 1, angles: "1, 5, 30, 90, 180", note: "小碎片撞大衛星：接近角很小時能量不足以完全解體，只撞出部分碎片。" },
  };
  function $(id) { return document.getElementById(id); }
  var inp = function (id, v, min, max, step, w) { return "<input type='number' id='" + id + "' value='" + v + "' min='" + min + "' max='" + max + "' step='" + step + "' style='width:" + (w || 76) + "px'>"; };
  host.innerHTML =
    "<div class='q' style='font-weight:600;margin:4px 0'>💫 兩顆衛星以不同角度相撞：碎片會散到哪些軌道？</div>" +
    "<div class='hint' style='white-space:normal'>兩顆衛星在同一高度、同一點相撞，只改變兩者速度方向的夾角（接近角）。夾角越大，相對速度越高：10° 約 1.3 km/s，180°（迎頭相撞）約 15 km/s。" +
    "碎片數依 NASA 標準解體模型；每塊碎片的速度＝母體速度＋解體 Δv，再換算成軌道。瀏覽器端計算。" +
    "<br>判讀重點：完全解體時，標準解體模型的碎片數只看兩顆質量和、Δv 只看碎片的面積質量比，<b>都不隨相對速度改變</b>；" +
    "接近角改變的是（1）能量是否達到完全解體門檻（小碎片撞大衛星、或接近角很小時才會差很多）、（2）B 的碎片雲落在哪個軌道面（傾角），" +
    "也就是碎片會覆蓋多少種傾角與升交點、日後散成殼層的範圍、（3）若改用「共同質心」假設，迎頭相撞的碎片會大量落入大氣。" +
    "再入比例等數字在各角度之間的差異多半落在多種子的區間內，屬於抽樣雜訊，不是接近角的效應。本示範為教學與情境探索用，不是碰撞或碎片環境的預測。</div>" +
    "<div class='row'><label>情境</label><select id='cl-preset' style='flex:1'>" + Object.keys(PRESETS).map(function (k) { return "<option value='" + k + "'>" + PRESETS[k].name + "</option>"; }).join("") + "</select></div>" +
    "<div id='cl-note' class='hint'></div>" +
    "<div class='row'><label>碰撞高度</label>" + inp("cl-h", 789, 200, 2000, 10) + "<span class='hint'>km</span><label>A 傾角</label>" + inp("cl-i", 86.4, 0, 180, 0.1) + "<span class='hint'>°</span>" +
    "<label>碰撞緯度</label>" + inp("cl-lat", 72.5, -90, 90, 0.5) + "<span class='hint'>°</span></div>" +
    "<div class='row'><label>A 質量</label>" + inp("cl-ma", 560, 0.1, 100000, 10, 84) + "<span class='hint'>kg</span><label>B 質量</label>" + inp("cl-mb", 900, 0.1, 100000, 10, 84) + "<span class='hint'>kg</span></div>" +
    "<div class='row'><label>接近角</label><input id='cl-ang' type='text' value='10, 45, 90, 103, 135, 180' style='flex:1;background:var(--bg);color:var(--hi);border:1px solid var(--line);border-radius:6px;padding:3px 6px'><span class='hint'>°，逗號分隔，最多 8 個</span></div>" +
    "<div class='row'><label>最小碎片</label><select id='cl-lc'><option value='0.1' selected>10 cm（可編目）</option><option value='0.05'>5 cm</option><option value='0.01'>1 cm（數量多，抽樣）</option></select>" +
    "<label title='每塊碎片的速度以哪個速度為基準'>速度基準</label><select id='cl-frame'><option value='parent' selected>各自母體（符合 Iridium–Cosmos 觀測）</option><option value='cm'>共同質心（理想化）</option></select></div>" +
    "<div class='row'><label>Δv 分布</label><select id='cl-dvm'><option value='inf' selected>SBM 原始（不截斷）</option><option value='1'>Cosmos 1408 校準（截斷 μ+1σ）</option></select>" +
    "<label title='能量質量比 ≤ 40 J/g 時目標被打掉的質量（都不是 SBM 標準）'>非完全解體</label><select id='cl-ej'><option value='edu' selected>教學假設</option><option value='fraction'>目標質量 1%</option><option value='none'>不產生碎片</option></select>" +
    "<label>種子數</label><select id='cl-ns'><option>1</option><option>10</option><option selected>30</option><option>100</option></select></div>" +
    "<div class='row act'><label>亂數種子</label>" + inp("cl-seed", 7, 1, 1e9, 1) + "<button class='go' id='cl-run'>計算</button><button id='cl-demo'>▶ 示範</button></div>" +
    "<div id='cl-res' class='hint'>按「計算」比較各接近角。</div>" +
    "<div class='row'><label>圖表角度</label><select id='cl-sel'></select></div>" +
    "<canvas id='cl-gab' width='760' height='300' style='width:100%;background:#0b1622;border:1px solid var(--line);border-radius:6px;margin-top:6px'></canvas>" +
    "<canvas id='cl-inc' width='760' height='220' style='width:100%;background:#0b1622;border:1px solid var(--line);border-radius:6px;margin-top:6px'></canvas>" +
    "<div class='row'><label class='chk'><input type='checkbox' id='cl-3d'> 3D 顯示碎片雲</label>" +
    "<span class='views'><button data-clt='600'>10 分鐘</button><button data-clt='orbit'>1 圈</button><button data-clt='86400'>1 天</button><button data-clt='2592000'>30 天</button><button data-clt='31557600'>1 年</button></span></div>" +
    "<div class='hint' style='white-space:normal;margin-top:4px'>模型：NASA 標準解體模型（與上方碎片連鎖相同的公式；能量質量比 > 40 J/g 為完全解體）。" +
    "「各自母體」：每顆衛星的碎片沿用自己的速度，2009 年 Iridium–Cosmos 碰撞後確實觀測到兩團碎片分別沿兩個母體的軌道面散開；「共同質心」：所有碎片沿用兩顆的質量加權平均速度，迎頭相撞時會高估落入大氣的比例。" +
    "壽命為粗估（等效高度＝近地點＋¼(遠地點−近地點)，中等太陽活動，依面積質量比縮放），精確的長期演化與連鎖碰撞請用上方的「引爆」。3D 為慣性座標示意（克卜勒＋J2 長期項），不含大氣衰減。</div>";

  var LAST = null, pc = null, T3D = 600;
  function setPreset(k) {
    var s = PRESETS[k];
    $("cl-h").value = s.h; $("cl-i").value = s.incA; $("cl-lat").value = s.lat; $("cl-ma").value = s.mA; $("cl-mb").value = s.mB; $("cl-ang").value = s.angles;
    $("cl-note").textContent = s.note;
  }
  function angles() {
    return $("cl-ang").value.split(/[,，\s]+/).map(Number).filter(function (x) { return isFinite(x) && x > 0 && x <= 180; })
      .filter(function (x, i, a) { return a.indexOf(x) === i; }).slice(0, 8);
  }
  function run() {
    var ang = angles();
    if (!ang.length) { $("cl-res").textContent = "請輸入 0–180° 的接近角"; return; }
    var t = performance.now(), base = { h: Math.min(2000, Math.max(200, +$("cl-h").value)), incA: Math.min(180, Math.max(0, +$("cl-i").value)), lat: +$("cl-lat").value,
      mA: Math.max(0.1, +$("cl-ma").value), mB: Math.max(0.1, +$("cl-mb").value), lc: +$("cl-lc").value, frame: $("cl-frame").value, seed: +$("cl-seed").value || 7,
      dvk: $("cl-dvm").value === "inf" ? Infinity : +$("cl-dvm").value, ejecta: $("cl-ej").value };
    var ns = Math.min(100, Math.max(1, +$("cl-ns").value || 1));
    LAST = ang.map(function (a) { return ensemble(Object.assign({}, base, { theta: a }), ns); });
    table(performance.now() - t);
    var sel = $("cl-sel"), prev = sel.value;
    sel.innerHTML = LAST.map(function (r, i) { return "<option value='" + i + "'>" + r.p.theta + "°</option>"; }).join("");
    var keep = LAST.findIndex(function (r) { return String(r.p.theta) === (sel.dataset.theta || prev); });
    sel.value = keep >= 0 ? keep : Math.min(LAST.length - 1, LAST.findIndex(function (r) { return r.p.theta >= 90; }) < 0 ? 0 : LAST.findIndex(function (r) { return r.p.theta >= 90; }));
    plots(); show3d();
  }
  // 比例指標：多種子時顯示「中位數［5–95%］」
  function E(r, key) {
    var e = r.ens;
    if (!e || e.n < 2) return pctS(r.stats[key]);
    return pctS(e[key][1]) + "<span style='color:#8b949e'>［" + pctS(e[key][0]) + "–" + pctS(e[key][2]) + "］</span>";
  }
  function table(ms) {
    var g0 = LAST[0].geom, ns = LAST[0].ens ? LAST[0].ens.n : 1;
    var h = "<div style='overflow-x:auto'><table class='kv' style='white-space:nowrap'><tr><td>接近角</td><td>相對速度</td><td>能量質量比</td><td>結果</td><td>碎片 ≥" + (+$("cl-lc").value * 100) + " cm</td>" +
      "<td>B 傾角</td><td>A 碎片傾角 5–95%</td><td>B 碎片傾角 5–95%</td><td>近地點中位數</td><td>遠地點 95%</td><td>立即再入</td><td>1 年內再入</td><td>壽命 &gt;25 年</td><td>穿越 ISS 420 km</td><td>穿越 550 km</td></tr>";
    LAST.forEach(function (r, i) {
      var s = r.stats, rng = function (a) { return isFinite(a[0]) ? a[0].toFixed(1) + "–" + a[2].toFixed(1) + "°" : "—"; };
      h += "<tr data-cli='" + i + "' style='cursor:pointer'><td>" + r.p.theta + "°</td><td>" + r.vrel.toFixed(1) + " km/s</td><td>" + fmt(r.emr) + " J/g</td><td>" +
        (r.catastrophic ? "<b style='color:#ff7b72'>完全解體</b>" : "部分解體（" + r.survivor + " 受損存活）") + "</td><td>" + fmt(r.n_total) + "</td><td>" + r.geom.incB.toFixed(1) + "°</td><td>" +
        rng(s.inc_A) + "</td><td>" + rng(s.inc_B) + "</td><td>" + (isFinite(s.hp[1]) ? fmt(s.hp[1]) + " km" : "—") + "</td><td>" + (isFinite(s.ha[1]) ? fmt(s.ha[1]) + " km" : "—") + "</td><td>" +
        E(r, "reentry_now") + "</td><td>" + E(r, "life_lt1") + "</td><td>" + E(r, "life_gt25") + "</td><td>" + E(r, "cross_iss") + "</td><td>" + E(r, "cross_550") + "</td></tr>";
    });
    var w = LAST.some(function (r) { return r.weight > 1; });
    h += "</table></div><div class='hint' style='white-space:normal'>點表格列可切換下方圖表。碰撞點緯度 " + g0.lat.toFixed(1) + "°（不能超過 A 的傾角）、軌道速度 " + g0.v.toFixed(2) + " km/s。" +
      "百分比以全部碎片為分母；「穿越」指近地點低於、遠地點高於該高度，這些碎片會反覆穿過該高度的衛星群。" +
      (w ? "碎片數超過 " + fmt(NMAX) + " 時抽樣計算，比例不受影響。" : "") +
      (ns > 1 ? "比例欄為 " + ns + " 個種子的中位數，括號內為 5–95% 區間；近地點、遠地點與傾角欄、下方圖表與 3D 為第一個種子的樣本。" : "<b>單一種子樣本</b>：各角度之間的小差異可能只是抽樣雜訊，建議用 30 個種子比較。") +
      "Δv：" + ($("cl-dvm").value === "inf" ? "SBM 原始" : "Cosmos 1408 校準（經驗修正）") + "；速度基準：" + ($("cl-frame").value === "cm" ? "共同質心（理想化）" : "各自母體") + "。計算 " + ms.toFixed(0) + " 毫秒。</div>";
    $("cl-res").innerHTML = h;
    $("cl-res").querySelectorAll("tr[data-cli]").forEach(function (tr) { tr.onclick = function () { $("cl-sel").value = tr.dataset.cli; $("cl-sel").dataset.theta = LAST[+tr.dataset.cli].p.theta; plots(); show3d(); }; });
  }
  function cur() { return LAST && LAST[+$("cl-sel").value || 0]; }
  function plots() {
    var r = cur(); if (!r) return;
    // Gabbard 圖：週期 vs 遠地點（點）與近地點（圈）
    var cv = $("cl-gab"), g = cv.getContext("2d"), W = cv.width, H = cv.height, L = 56, R = 12, T = 22, B = 30;
    var ok = r.frags.filter(function (f) { return !f.escape && !f.reentry; });
    if (!ok.length) {
      [cv, $("cl-inc")].forEach(function (c) { var x = c.getContext("2d"); x.clearRect(0, 0, c.width, c.height); x.fillStyle = "#8b949e"; x.font = "13px sans-serif";
        x.fillText("接近角 " + r.p.theta + "°：沒有留在軌道上的 ≥" + (r.p.lc * 100) + " cm 碎片（能量太低或全部立即再入）", 20, 40); });
      return;
    }
    var per =ok.map(function (f) { return f.period; }), alt = ok.map(function (f) { return f.ha; });
    var x0 = Math.min(85, pct(per, 0.01)), x1 = Math.max(x0 + 10, pct(per, 0.99)), y1 = Math.max(r.p.h + 200, pct(alt, 0.99)) * 1.05;
    var X = function (v) { return L + (v - x0) / (x1 - x0) * (W - L - R); }, Y = function (v) { return T + (1 - v / y1) * (H - T - B); };
    g.clearRect(0, 0, W, H); g.font = "11px sans-serif"; g.strokeStyle = "#21262d"; g.fillStyle = "#8b949e";
    for (var a = 0; a <= y1; a += y1 > 3000 ? 1000 : 500) { g.beginPath(); g.moveTo(L, Y(a)); g.lineTo(W - R, Y(a)); g.stroke(); g.textAlign = "right"; g.fillText(a + " km", L - 4, Y(a) + 4); }
    var stp = (x1 - x0) > 60 ? 20 : (x1 - x0) > 25 ? 10 : 5;
    for (var p = Math.ceil(x0 / stp) * stp; p <= x1; p += stp) { g.textAlign = "center"; g.fillText(p + " 分", X(p), H - 10); }
    g.setLineDash([4, 3]); g.strokeStyle = "#6e7681"; g.beginPath(); g.moveTo(L, Y(r.p.h)); g.lineTo(W - R, Y(r.p.h)); g.stroke(); g.setLineDash([]);
    ok.forEach(function (f) {
      if (f.period < x0 || f.period > x1) return;
      g.fillStyle = COL[f.who]; g.fillRect(X(f.period) - 1, Y(Math.min(f.ha, y1)) - 1, 2, 2);
      g.strokeStyle = COL[f.who]; g.globalAlpha = 0.5; g.beginPath(); g.arc(X(f.period), Y(Math.max(0, f.hp)), 1.6, 0, TAU); g.stroke(); g.globalAlpha = 1;
    });
    g.textAlign = "left"; g.fillStyle = "#c9d1d9";
    g.fillText("Gabbard 圖（接近角 " + r.p.theta + "°）：點＝遠地點、圈＝近地點；虛線＝碰撞高度", L + 6, T - 6);
    g.fillStyle = COL.A; g.fillText("● 衛星 A 的碎片", W - 230, T - 6); g.fillStyle = COL.B; g.fillText("● 衛星 B 的碎片", W - 120, T - 6);
    // 傾角分布
    cv = $("cl-inc"); g = cv.getContext("2d"); W = cv.width; H = cv.height; T = 22; B = 26;
    var bins = 90, ha = new Array(bins).fill(0), hb = new Array(bins).fill(0);
    ok.forEach(function (f) { var k = Math.min(bins - 1, Math.floor(f.i / D2R / 2)); (f.who === "A" ? ha : hb)[k]++; });
    var mx = Math.max.apply(null, ha.map(function (v, i) { return v + hb[i]; })) || 1, bw = (W - L - R) / bins;
    g.clearRect(0, 0, W, H); g.font = "11px sans-serif";
    for (var k = 0; k < bins; k++) {
      var ya = (H - T - B) * ha[k] / mx, yb = (H - T - B) * hb[k] / mx;
      g.fillStyle = COL.A; g.fillRect(L + k * bw, H - B - ya, bw - 1, ya);
      g.fillStyle = COL.B; g.fillRect(L + k * bw, H - B - ya - yb, bw - 1, yb);
    }
    g.fillStyle = "#8b949e"; g.textAlign = "center";
    for (var d = 0; d <= 180; d += 30) g.fillText(d + "°", L + d / 2 * bw, H - 8);
    g.textAlign = "left"; g.fillStyle = "#c9d1d9";
    g.fillText("碎片傾角分布（每 2°）：A 母體 " + r.p.incA + "°、B 母體 " + r.geom.incB.toFixed(1) + "°", L + 6, T - 6);
  }
  // 3D：選定角度的碎片在碰撞後 T3D 秒的位置（慣性座標示意），加上兩顆母體的原軌道
  function show3d() {
    var SDG = sdg();
    if (!$("cl-3d").checked) { if (pc && SDG && SDG.viewer) { SDG.viewer.scene.primitives.remove(pc); pc = null; SDG.viewer.scene.requestRender(); } return; }
    if (!SDG || !SDG.viewer || typeof Cesium === "undefined") { $("cl-res").insertAdjacentHTML("beforeend", "<div class='hint'>3D 地球尚未載入完成，請稍後再勾選。</div>"); return; }
    var r = cur(); if (!r) return;
    if (pc) SDG.viewer.scene.primitives.remove(pc);
    pc = SDG.viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
    var cA = Cesium.Color.fromCssColorString(COL.A), cB = Cesium.Color.fromCssColorString(COL.B), t = T3D, n = 0;
    var tt = t === "orbit" ? TAU * Math.sqrt(Math.pow(RE + r.p.h, 3) / MU) : t;   // 1 圈＝母體軌道週期
    [["A", r.geom.vA], ["B", r.geom.vB]].forEach(function (x) {
      var el = elements(r.geom.r, x[1]), c = (x[0] === "A" ? cA : cB).withAlpha(0.35);
      for (var k = 0; k < 360; k++) { var q = position(el, k / 360 * el.period * 60); pc.add({ position: new Cesium.Cartesian3(q[0] * 1000, q[1] * 1000, q[2] * 1000), pixelSize: 1.5, color: c }); }
    });
    r.frags.forEach(function (f) {
      if (f.escape || f.reentry) return;
      var q = position(f, tt);
      pc.add({ position: new Cesium.Cartesian3(q[0] * 1000, q[1] * 1000, q[2] * 1000), pixelSize: 3, color: f.who === "A" ? cA : cB });
      n++;
    });
    SDG.viewer.scene.requestRender();
    var lbl = { 600: "10 分鐘", orbit: "1 圈", 86400: "1 天", 2592000: "30 天", 31557600: "1 年" }[t];
    if (SDG.status) SDG.status("接近角 " + r.p.theta + "° 碰撞後 " + lbl + "：" + fmt(n) + " 塊碎片（藍＝A、橘＝B；淡色環為母體原軌道；慣性座標示意、不含大氣衰減）");
  }
  function demo() {
    var wrap = host.closest("details"); if (wrap) wrap.open = true;
    $("cl-preset").value = "iridium"; setPreset("iridium"); $("cl-frame").value = "parent"; $("cl-dvm").value = "inf"; $("cl-ns").value = "30"; $("cl-3d").checked = true; T3D = 86400;
    $("cl-sel").dataset.theta = "103"; run();
    host.scrollIntoView({ block: "start", behavior: "smooth" });
    return Promise.resolve();
  }
  window.COLLIDE_DEMO = demo;
  $("cl-preset").onchange = function () { setPreset(this.value); };
  $("cl-run").onclick = run;
  $("cl-demo").onclick = demo;
  $("cl-sel").onchange = function () { this.dataset.theta = LAST[+this.value].p.theta; plots(); show3d(); };
  $("cl-3d").onchange = show3d;
  host.querySelectorAll("[data-clt]").forEach(function (b) { b.onclick = function () { T3D = b.dataset.clt === "orbit" ? "orbit" : +b.dataset.clt; $("cl-3d").checked = true; show3d(); }; });
  document.addEventListener("sdg-tab", function (e) { if (pc) { pc.show = e.detail === "debris"; var S = sdg(); if (S && S.viewer) S.viewer.scene.requestRender(); } });
  setPreset("iridium");
  // 單機版：在碎片連鎖的任務卡加「示範 2」（任務卡由 games_ux.js 產生）
  var tries = 0, iv = setInterval(function () {
    var card = document.querySelector("#tab-debris .mission");
    if (card || ++tries > 50) {
      clearInterval(iv);
      if (!card || card.querySelector(".demo2")) return;
      var b = document.createElement("button"); b.className = "demo2"; b.textContent = "▶ 示範 2：兩顆衛星以不同角度相撞";
      b.style.marginLeft = "6px"; b.onclick = demo;
      var d1 = card.querySelector(".demo"); if (d1 && d1.nextSibling) card.insertBefore(b, d1.nextSibling); else card.appendChild(b);
    }
  }, 200);
})();
