/* rpo3d.js — 泛用型：任一「近距離配對」之相對接近 3D 場景（Cesium）+ Chan Pc（proxy）。
 * 配對清單來自 /api/conjunctions；場景資料來自 /api/rpo/<primary>/<secondary>。
 * 由 rpo3d.html 於 Cesium.js 載入後呼叫 window.startRPO()。
 */
(function () {
  "use strict";

  var C = null, viewer = null;
  var PRIM = "#F2A73B", SEC = "#35C6F4", CRIT = "#FF5C4E";
  var _tick = null;            // 目前 clock.onTick handler（切換時移除）
  var _loadSeq = 0;            // 防止快速切換之過期回應覆寫
  var _curP = null, _curS = null, _curV = "";
  var _eP = null, _eS = null;  // 兩顆衛星 entity（視角追蹤用）
  var _meta = null, _vp = "p"; // 目前視角：'p'=primary / 's'=secondary
  var _pcSpheres = [], _pcSphereOn = true;   // 碰撞機率球 entities（兩顆衛星各一）+ 開關
  // COMSPOC 模式：全期地固座標系（ECEF）長軌跡（GEO 定點保持迴圈／東西換位）+ 外側定鏡頭 + Ranges 讀數
  var _comspocOn = false, _trailEnts = [], _trailData = null, _rangeLabel = null;
  // 雙語 UI 狀態（供 setLang 重新渲染動態內容用）
  var _hasTrail = false, _trailInfo = null;    // COMSPOC 全期軌跡資訊文字
  var _pcDims = null;                          // 碰撞機率球尺寸文字
  var _lastStat = null;                        // { key, vars, err } — #pstat 最後一次狀態訊息
  var _loadingIsDefault = true;                // #loading 是否仍為預設載入文字（尚無錯誤訊息覆蓋）

  // ── 雙語字典（zh / ja）──────────────────────────────────────────────────
  var I18N = {
    zh: {
      doc_title: "RPO 3D — 兩衛星相對接近與衝突機率 Pc",
      nav_cases: "案例總覽",
      nav_globe_home: "地球儀主頁",
      loading_scene: "載入 3D 場景中 …",
      default_title: "RPO 3D 場景",
      picker_label: "近距離配對（選擇即切換該對衛星視角）",
      thr_title: "篩選閾值 km",
      rescan_btn: "重新掃描",
      report_btn: "報告 PNG",
      orbit_btn: "📈 軌道參數",
      orbit_title: "兩顆衛星軌道要素歷史疊圖比較（SMA／傾角／RAAN／ARGP）",
      kpi_range: "目前距離",
      kpi_pc: "Pc（近似值）",
      kpi_alt_suffix: "{name} 高度",
      legend_tca: "最接近 (TCA)",
      vp_toggle_default: "🎥 切換視角",
      vp_label_default: "目前視角：—",
      vp_label: "目前視角：{name}",
      vp_third_person: "第三人稱總覽",
      vp_switch_view: "🎥 切換到 {name} 視角",
      vp_switch_plain: "🎥 切換到 {name}",
      pc_sphere_chk: "🔴 衝突機率橢球（3σ R/T/N 三軸）",
      relwin_chk: "🧭 相對軌跡投影浮動視窗（以對方為中心之 LVLH T–R 平面）",
      comspoc_chk: "🛰 COMSPOC 模式（全期地固座標軌跡迴圈＋外側固定鏡頭＋Ranges）",
      cam_toggle_default: "📷 鏡頭 ⇄",
      cam_toggle: "📷 鏡頭：{mode} ⇄",
      cam_mode_wide: "全景（地球＋軌跡）",
      cam_mode_close: "近景（迴圈）",
      timeline_h2: "事件時間軸",
      note_html: "<b>方法</b>：兩物體以最近 elset SGP4 傳播至共同時鐘；Pc = Chan (2008) 各向同性首階近似"
        + "（σr={sr}、σt={st} km），為<b>排序代理（proxy）</b>、非作業級碰撞機率。<br>"
        + "TLE/SGP4 位置含約 1–5 km 不確定度，次公里距離落於雜訊底——幾何重建、非精密交會判定。",
      comspoc_trail_info: "全期 {from} ~ {to} · {n} 點 @ {step} min · 地固座標系（ECEF）",
      comspoc_no_trail: "此案例未產生全期軌跡（preset 需設 trail_step_min）；模式僅套用鏡頭與 Ranges。",
      pc_sphere_info: "3σ 橢球（三軸）· R {rR} / T {rT} / N {rN} m　（σ R {sr} / T {st} / N {sn} km）"
        + "· 顏色隨 Pc：綠<1e-6 / 琥珀 / 紅>1e-4",
      rel_swap_title: "切換中心物體",
      rel_swap_label: "⇄ 中心",
      rel_close_title: "關閉",
      rel_title: "相對軌跡投影 — 中心：{name}",
      axis_t: "沿軌 T (km) →",
      axis_dh: "Δ高度 (km) ↑=軌道較高",
      rel_foot: "{name}：沿軌 T {t} km、Δ高度 {dh} km（>0=軌道較高） · 粗線=單圈移動平均、細線=逐點 · 拖曳標題移動、⇄ 換中心",
      stat_summary: "TCA {dmin} km · Pc(proxy) {pc} · {n} 點",
      loading_scene_pair: "計算場景中 … ({p} × {s})",
      load_fail: "無法載入：{error}",
      no_valid_orbit: "此配對無有效軌道取樣（TLE 歷史不足或無重疊）",
      fetch_fail: "讀取失敗：{error}",
      scanning_pairs: "掃描近距離配對 …",
      cur_pair: "★ 目前：{p} × {s}",
      preset_case: "◎ 案例：{title}",
      no_pairs: "（無近距離配對）",
      pairs_summary: "{presets} 個精選案例 + {pairs} 個近距離配對（閾值 {thr} km）",
      pair_list_fail: "配對清單載入失敗：{error}",
      cesium_init_fail: "Cesium 初始化失敗：{error}",
    },
    ja: {
      doc_title: "RPO 3D — 2衛星の近接運用と衝突確率（Pc）",
      nav_cases: "事例一覧",
      nav_globe_home: "地球儀ホーム",
      loading_scene: "3D シーンを読み込み中 …",
      default_title: "RPO 3D シーン",
      picker_label: "近接ペア（選択するとそのペアの視点に切替）",
      thr_title: "フィルタ閾値 km",
      rescan_btn: "再スキャン",
      report_btn: "レポート PNG",
      orbit_btn: "📈 軌道要素",
      orbit_title: "2 機の軌道要素履歴を重ねて比較（SMA／傾斜角／RAAN／ARGP）",
      kpi_range: "現在の距離",
      kpi_pc: "Pc（近似値）",
      kpi_alt_suffix: "{name} の高度",
      legend_tca: "最接近時刻 (TCA)",
      vp_toggle_default: "🎥 視点切替",
      vp_label_default: "現在の視点：—",
      vp_label: "現在の視点：{name}",
      vp_third_person: "第三者視点の俯瞰",
      vp_switch_view: "🎥 {name} 視点に切替",
      vp_switch_plain: "🎥 {name} に切替",
      pc_sphere_chk: "🔴 衝突確率楕円体（3σ R/T/Nの3軸）",
      relwin_chk: "🧭 相対軌跡投影（フローティングウィンドウ、相手中心の LVLH T–R 平面）",
      comspoc_chk: "🛰 COMSPOCモード（全期間の地球固定座標系による軌跡ループ＋外側固定視点＋Ranges）",
      cam_toggle_default: "📷 カメラ ⇄",
      cam_toggle: "📷 カメラ：{mode} ⇄",
      cam_mode_wide: "全景（地球＋軌跡）",
      cam_mode_close: "近接視点（ループ）",
      timeline_h2: "イベントタイムライン",
      note_html: "<b>手法</b>：両物体は直近の elset により SGP4 伝播で共通時刻系に揃える。"
        + "Pc = Chan (2008) の等方性一次近似（σr={sr}、σt={st} km）であり、"
        + "<b>順位付けのための代理指標（proxy）</b>であって運用級の衝突確率ではない。<br>"
        + "TLE/SGP4 位置には約 1–5 km の不確かさがあり、サブキロメートルの距離はノイズフロア内"
        + "——幾何学的再構成であり、精密な近接判定ではない。",
      comspoc_trail_info: "全期間 {from} ～ {to} ・ {n} 点 ・ {step}分間隔 ・ 地球固定座標系（ECEF）",
      comspoc_no_trail: "この事例は全期間軌跡が生成されていません（preset に trail_step_min の設定が必要）。モードはカメラと Ranges のみ適用されます。",
      pc_sphere_info: "3σ 楕円体（三軸）・ R {rR} / T {rT} / N {rN} m　（σ R {sr} / T {st} / N {sn} km）"
        + "・ 色は Pc に連動：緑<1e-6 / 琥珀色 / 赤>1e-4",
      rel_swap_title: "中心天体を切替",
      rel_swap_label: "⇄ 中心",
      rel_close_title: "閉じる",
      rel_title: "相対軌跡投影 — 中心：{name}",
      axis_t: "沿軌方向 T (km) →",
      axis_dh: "Δ高度 (km) ↑=軌道がより高い",
      rel_foot: "{name}：沿軌方向 T {t} km、Δ高度 {dh} km（>0＝軌道が高い） ・ 太線＝1周移動平均、細線＝各サンプル ・ タイトルをドラッグで移動、⇄ で中心切替",
      stat_summary: "TCA {dmin} km ・ Pc(proxy) {pc} ・ {n} 点",
      loading_scene_pair: "シーンを計算中 … ({p} × {s})",
      load_fail: "読み込み失敗：{error}",
      no_valid_orbit: "このペアには有効な軌道サンプルがありません（TLE 履歴不足または重複期間なし）",
      fetch_fail: "取得失敗：{error}",
      scanning_pairs: "近接ペアをスキャン中 …",
      cur_pair: "★ 現在：{p} × {s}",
      preset_case: "◎ 事例：{title}",
      no_pairs: "（近接ペアなし）",
      pairs_summary: "{presets} 件の厳選事例 + {pairs} 件の近接ペア（閾値 {thr} km）",
      pair_list_fail: "ペア一覧の読み込み失敗：{error}",
      cesium_init_fail: "Cesiumの初期化に失敗しました：{error}",
    },
    en: {
      doc_title: "RPO 3D — Two-Satellite Proximity and Probability of Collision (Pc)",
      nav_cases: "Case Library",
      nav_globe_home: "Globe Home",
      loading_scene: "Loading 3D scene …",
      default_title: "RPO 3D Scene",
      picker_label: "Close-approach pair (select to switch to that pair's viewpoint)",
      thr_title: "Filter threshold km",
      rescan_btn: "Rescan",
      report_btn: "Report PNG",
      orbit_btn: "📈 Orbit elements",
      orbit_title: "Overlay both satellites' orbital element history (SMA / inclination / RAAN / ARGP)",
      kpi_range: "Current Range",
      kpi_pc: "Pc (approximate)",
      kpi_alt_suffix: "{name} Altitude",
      legend_tca: "Closest Approach (TCA)",
      vp_toggle_default: "🎥 Switch View",
      vp_label_default: "Current view: —",
      vp_label: "Current view: {name}",
      vp_third_person: "Third-person overview",
      vp_switch_view: "🎥 Switch to {name} view",
      vp_switch_plain: "🎥 Switch to {name}",
      pc_sphere_chk: "🔴 Probability-of-collision ellipsoid (3σ R/T/N axes)",
      relwin_chk: "🧭 Relative trajectory projection floating window (LVLH T–R plane, centered on the other object)",
      comspoc_chk: "🛰 COMSPOC mode (full-span Earth-fixed trajectory loop + external fixed camera + Ranges)",
      cam_toggle_default: "📷 Camera ⇄",
      cam_toggle: "📷 Camera: {mode} ⇄",
      cam_mode_wide: "Wide (Earth + trajectory)",
      cam_mode_close: "Close (orbit loop)",
      timeline_h2: "Event Timeline",
      note_html: "<b>Method</b>: both objects are propagated by SGP4 from their nearest elsets to a common clock; "
        + "Pc = Chan (2008) isotropic first-order approximation (σr={sr}, σt={st} km) — a <b>ranking proxy</b>, "
        + "not an operational-grade collision probability.<br>"
        + "TLE/SGP4 positions carry roughly 1–5 km of uncertainty; sub-kilometer ranges sit within the noise floor "
        + "— this is a geometric reconstruction, not a precision conjunction assessment.",
      comspoc_trail_info: "Full span {from} ~ {to} · {n} points @ {step} min · Earth-fixed frame (ECEF)",
      comspoc_no_trail: "No full-span trajectory was generated for this case (preset needs trail_step_min set); this mode applies only the camera and Ranges.",
      pc_sphere_info: "3σ ellipsoid (3 axes) · R {rR} / T {rT} / N {rN} m (σ R {sr} / T {st} / N {sn} km)"
        + " · color is mapped to Pc: green<1e-6 / amber / red>1e-4",
      rel_swap_title: "Swap center object",
      rel_swap_label: "⇄ Center",
      rel_close_title: "Close",
      rel_title: "Relative Trajectory Projection — Center: {name}",
      axis_t: "Along-track T (km) →",
      axis_dh: "Δ Altitude (km) ↑ = higher orbit",
      rel_foot: "{name}: along-track T {t} km, Δaltitude {dh} km (>0 = higher orbit) · thick line = one-orbit moving average, thin line = per-sample · drag title to move, ⇄ to swap center",
      stat_summary: "TCA {dmin} km · Pc(proxy) {pc} · {n} points",
      loading_scene_pair: "Computing scene … ({p} × {s})",
      load_fail: "Failed to load: {error}",
      no_valid_orbit: "No valid orbit samples for this pair (insufficient TLE history or no overlap)",
      fetch_fail: "Fetch failed: {error}",
      scanning_pairs: "Scanning close-approach pairs …",
      cur_pair: "★ Current: {p} × {s}",
      preset_case: "◎ Case: {title}",
      no_pairs: "(No close-approach pairs)",
      pairs_summary: "{presets} curated cases + {pairs} close-approach pairs (threshold {thr} km)",
      pair_list_fail: "Failed to load pair list: {error}",
      cesium_init_fail: "Cesium initialization failed: {error}",
    },
  };
  var LOCALE_MAP = { zh: "zh-Hant", en: "en-US", ja: "ja-JP" };
  var LANG = (function () {
    try { return localStorage.getItem("rpo3d_lang") || "zh"; } catch (e) { return "zh"; }
  })();
  if (!I18N[LANG]) LANG = "zh";

  function t(key) {
    var d = I18N[LANG] || I18N.zh;
    return (key in d) ? d[key] : (I18N.zh[key] !== undefined ? I18N.zh[key] : key);
  }
  function tpl(key, vars) {
    var s = t(key);
    Object.keys(vars || {}).forEach(function (k) {
      s = s.replace(new RegExp("\\{" + k + "\\}", "g"), vars[k]);
    });
    return s;
  }

  // ── 動態內容重新渲染（語言切換時呼叫，避免用字面量寫死中文）──────────────
  function renderNote(meta) {
    var el = document.getElementById("note");
    if (el) el.innerHTML = tpl("note_html", { sr: meta.sigma_r, st: meta.sigma_t });
  }
  function renderAltLabels(meta) {
    var a = document.getElementById("k_pname"), b = document.getElementById("k_sname");
    if (a) a.textContent = tpl("kpi_alt_suffix", { name: meta.primName });
    if (b) b.textContent = tpl("kpi_alt_suffix", { name: meta.secName });
  }
  function renderVpTexts() {
    if (!_meta) return;
    var names = { t: t("vp_third_person"), p: _meta.primName, s: _meta.secName };
    var next = { t: "p", p: "s", s: "t" }[_vp];
    var lab = document.getElementById("vpLabel");
    if (lab) lab.textContent = tpl("vp_label", { name: names[_vp] });
    var btn = document.getElementById("vpToggle");
    if (btn) btn.textContent = (next === "t")
      ? tpl("vp_switch_plain", { name: names[next] })
      : tpl("vp_switch_view", { name: names[next] });
  }
  function renderCamToggleText() {
    var b = document.getElementById("camToggle");
    if (b) b.textContent = tpl("cam_toggle", { mode: _camMode === "wide" ? t("cam_mode_wide") : t("cam_mode_close") });
  }
  function refreshDynamicUI() {
    var titleEl = document.getElementById("title");
    if (titleEl && !_meta) titleEl.textContent = t("default_title");
    if (_loadingIsDefault) {
      var loadEl = document.getElementById("loading");
      if (loadEl) loadEl.textContent = t("loading_scene");
    }
    if (_meta) {
      renderNote(_meta);
      renderAltLabels(_meta);
      renderVpTexts();
      var ci = document.getElementById("comspocInfo");
      if (ci) ci.textContent = _hasTrail ? tpl("comspoc_trail_info", _trailInfo) : t("comspoc_no_trail");
    }
    if (_pcDims) {
      var pi = document.getElementById("pcSphereInfo");
      if (pi) pi.textContent = tpl("pc_sphere_info", _pcDims);
    }
    renderCamToggleText();
    if (_lastStat) stat(_lastStat.key, _lastStat.vars, _lastStat.err);
  }

  // ── 語言切換 ──────────────────────────────────────────────────────────
  function setLang(lang) {
    if (!I18N[lang]) return;
    LANG = lang;
    try { localStorage.setItem("rpo3d_lang", lang); } catch (e) {}
    document.documentElement.lang = LOCALE_MAP[lang] || "zh-Hant";
    document.title = t("doc_title");

    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
    document.querySelectorAll(".lang-btn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.lang === lang);
    });

    refreshDynamicUI();
  }
  window.setLang = setLang;

  function warn(m) {
    _loadingIsDefault = false;
    var w = document.getElementById("warn");
    if (w) { w.textContent = m; w.style.display = "block"; }
    var l = document.getElementById("loading");
    if (l) l.textContent = m;
  }
  function stat(key, vars, err) {
    _lastStat = { key: key, vars: vars, err: !!err };
    var s = document.getElementById("pstat");
    if (s) { s.textContent = key ? tpl(key, vars) : ""; s.className = "stat" + (err ? " err" : ""); }
  }
  function fmtRange(km) {
    if (km == null || isNaN(km)) return "—";
    return km < 10 ? km.toFixed(2) : (km < 1000 ? km.toFixed(1) : Math.round(km).toLocaleString());
  }
  function fmtPc(pc) { return (!pc || pc <= 0) ? "&lt;1e-8" : pc.toExponential(1); }
  // Pc → 風險色（沿用 scenario04 conjunction 門檻：RED>1e-4, AMBER>1e-6, 否則 GREEN）
  function riskColor(pc) {
    if (pc > 1e-4) return C.Color.fromCssColorString(CRIT);
    if (pc > 1e-6) return C.Color.fromCssColorString("#F2A73B");
    return C.Color.fromCssColorString("#4FD08A");
  }

  function initCesium() {
    C = window.Cesium;
    C.Ion.defaultAccessToken = "";
    try { C.IonResource.fromAssetId = function () { return Promise.reject(new Error("Ion disabled")); }; } catch (e) {}
    viewer = new C.Viewer("cesiumContainer", {
      animation: true, timeline: true, baseLayerPicker: false,
      geocoder: false, homeButton: false, navigationHelpButton: false,
      sceneModePicker: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
      imageryProvider: new C.SingleTileImageryProvider({
        url: "/api/globe_texture/default",
        rectangle: C.Rectangle.fromDegrees(-180, -90, 180, 90),
        credit: "NASA Blue Marble",
      }),
      terrainProvider: new C.EllipsoidTerrainProvider(),
    });
    viewer.cesiumWidget.creditContainer.style.display = "none";
    viewer.scene.globe.enableLighting = true;
    viewer.scene.globe.depthTestAgainstTerrain = false;
  }

  function sampledPos(orbit, key) {
    var p = new C.SampledPositionProperty();
    for (var i = 0; i < orbit.length; i++) {
      var a = orbit[i][key];
      p.addSample(C.JulianDate.fromIso8601(orbit[i].t), C.Cartesian3.fromDegrees(a[0], a[1], a[2]));
    }
    try { p.setInterpolationOptions({ interpolationDegree: 5, interpolationAlgorithm: C.LagrangePolynomialApproximation }); } catch (e) {}
    return p;
  }

  function addSat(name, pos, hex, t0, t1, trailS) {
    return viewer.entities.add({
      name: name,
      availability: new C.TimeIntervalCollection([new C.TimeInterval({ start: t0, stop: t1 })]),
      position: pos,
      point: { pixelSize: 11, color: C.Color.fromCssColorString(hex), outlineColor: C.Color.BLACK, outlineWidth: 1 },
      label: { text: name, font: "12px monospace", fillColor: C.Color.fromCssColorString(hex),
        style: C.LabelStyle.FILL, pixelOffset: new C.Cartesian2(0, -18),
        showBackground: true, backgroundColor: C.Color.fromCssColorString("#0A0D13").withAlpha(0.6) },
      // 位置為地固座標系（ECEF）取樣：GEO 物體長拖尾即呈現定點保持迴圈（COMSPOC 式）
      path: { leadTime: 0, trailTime: trailS || 5400, width: 2, resolution: 60,
        material: C.Color.fromCssColorString(hex).withAlpha(0.85) },
    });
  }

  function buildHUD(meta) {
    document.getElementById("title").textContent = meta.title;
    document.getElementById("subtitle").innerHTML = meta.subtitle;
    document.getElementById("lg_p").textContent = meta.primId + " · " + meta.primName;
    document.getElementById("lg_s").textContent = meta.secId + " · " + meta.secName;
    renderAltLabels(meta);
    var tl = meta.timeline || [];
    document.getElementById("timeline").innerHTML = tl.map(function (r) {
      return '<div class="tlrow"><div class="d">' + r.d + '</div><div class="t">' + r.t + "</div></div>";
    }).join("");
    renderNote(meta);
  }

  function clearScene() {
    if (_tick) { try { viewer.clock.onTick.removeEventListener(_tick); } catch (e) {} _tick = null; }
    if (viewer) { try { viewer.trackedEntity = undefined; } catch (e) {} viewer.entities.removeAll(); }
    _eP = _eS = null; _pcSpheres = []; _trailEnts = []; _trailData = null; _rangeLabel = null;
    destroyRelWindow();
  }

  // ── COMSPOC 模式 ──
  // 位置以 fromDegrees 建立即為地固座標系：GEO 物體之傾角／偏心在此系呈每日迴圈、漂移呈螺旋，
  // 長時間累積即 COMSPOC「on-orbit behavior」影片中的兩色迴圈。軌跡隨時鐘漸進繪出（≤ 當前時刻）。
  function buildTrails(trail, meta) {
    if (!trail || !trail.t || !trail.t.length) return;
    var ms = trail.t.map(function (t) { return Date.parse(t); });
    var P = trail.p.map(function (a) { return C.Cartesian3.fromDegrees(a[0], a[1], a[2]); });
    var S = trail.s.map(function (a) { return C.Cartesian3.fromDegrees(a[0], a[1], a[2]); });
    _trailData = { ms: ms, P: P, S: S, d: trail.d };
    function upto(arr) {
      return new C.CallbackProperty(function (time) {
        var now = C.JulianDate.toDate(time).getTime();
        var n = ms.length;                      // 二分搜尋：≤ now 之樣本數
        var lo = 0, hi = n;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (ms[mid] <= now) lo = mid + 1; else hi = mid; }
        return arr.slice(0, Math.max(2, lo));
      }, false);
    }
    _trailEnts = [
      viewer.entities.add({ show: _comspocOn, polyline: { positions: upto(P), width: 1.6,
        material: C.Color.fromCssColorString(PRIM).withAlpha(0.85), arcType: C.ArcType.NONE } }),
      viewer.entities.add({ show: _comspocOn, polyline: { positions: upto(S), width: 1.6,
        material: C.Color.fromCssColorString(SEC).withAlpha(0.85), arcType: C.ArcType.NONE } }),
    ];
    _hasTrail = true;
    _trailInfo = { from: trail.t[0].slice(0, 10), to: trail.t[trail.t.length - 1].slice(0, 10), n: ms.length, step: trail.step_min };
    var info = document.getElementById("comspocInfo");
    if (info) info.textContent = tpl("comspoc_trail_info", _trailInfo);
  }

  // Ranges 讀數：仿 COMSPOC「Ranges ⊗  A (SSN) … B (SSN) = xx km」，掛在連線中點
  function buildRangeLabel(pPos, sPos, meta, sampleAt) {
    _rangeLabel = viewer.entities.add({
      show: _comspocOn,
      position: new C.CallbackProperty(function (time) {
        var a = pPos.getValue(time), b = sPos.getValue(time);
        return (a && b) ? C.Cartesian3.midpoint(a, b, new C.Cartesian3()) : undefined;
      }, false),
      label: {
        text: new C.CallbackProperty(function (time) {
          var s = sampleAt(C.JulianDate.toDate(time).getTime());
          return "Ranges ⊗  " + meta.primName + " (SSN " + meta.primId + ") … "
               + meta.secName + " (SSN " + meta.secId + ") = " + fmtRange(s.d) + " km";
        }, false),
        font: "12px monospace", fillColor: C.Color.WHITE, style: C.LabelStyle.FILL,
        pixelOffset: new C.Cartesian2(0, -26), showBackground: true,
        backgroundColor: C.Color.fromCssColorString("#0A0D13").withAlpha(0.7),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  // COMSPOC 鏡頭（兩段）：
  //  wide  ─ 經度偏西 12°、距地心 60,000 km，視線為地心／物體方向平分線：地球在左、兩物體在右（仿 COMSPOC 構圖）。
  //  close ─ 於兩物體中點沿軌（−T）1,400 km 外、以軌道面法向 N 為上方望向 +T：
  //          地固座標系日迴圈（振幅≈傾角×42,164 km，TJS-10/3 僅 ~250 km）在此距離清楚可見。
  var _camMode = "close";
  function rtnBasis(time) {
    var a = _eP.position.getValue(time), b = _eS.position.getValue(time);
    if (!a || !b) return null;
    var mid = C.Cartesian3.midpoint(a, b, new C.Cartesian3());
    var a2 = _eP.position.getValue(C.JulianDate.addSeconds(time, 60, new C.JulianDate())) || a;
    var v = C.Cartesian3.subtract(a2, a, new C.Cartesian3());
    var R = C.Cartesian3.normalize(mid, new C.Cartesian3());
    var N = C.Cartesian3.cross(mid, v, new C.Cartesian3());
    if (C.Cartesian3.magnitude(N) < 1e-6) N = C.Cartesian3.clone(C.Cartesian3.UNIT_Z);
    N = C.Cartesian3.normalize(N, N);
    var T = C.Cartesian3.normalize(C.Cartesian3.cross(N, R, new C.Cartesian3()), new C.Cartesian3());
    return { mid: mid, R: R, T: T, N: N };
  }
  function comspocCamera(mode) {
    if (!_eP || !_eS || !viewer) return;
    if (mode) _camMode = mode;
    try { viewer.trackedEntity = undefined; } catch (e) {}
    var time = viewer.clock.currentTime;
    var basis = rtnBasis(time);
    if (!basis) return;
    var dest, dir, up;
    if (_camMode === "wide") {
      // 眼點：與兩物體同經度偏西 12°、距地心 60,000 km（GEO）；視線取「地心方向」與「物體方向」
      // 之平分線 → 地球（角徑約 12°）在左、兩物體在右，各離軸約 ±12°，仿 COMSPOC 構圖。
      var c = C.Cartographic.fromCartesian(basis.mid);
      var lon = C.Math.toDegrees(c.longitude), rMid = C.Cartesian3.magnitude(basis.mid);
      var distC = Math.max(2.4e7, rMid * 1.42);   // LEO 遠景下限 24,000 km（地球約佔 31° 視角）
      dest = C.Cartesian3.fromDegrees(lon - 12, 6, distC - 6378137);
      var toC = C.Cartesian3.normalize(C.Cartesian3.negate(dest, new C.Cartesian3()), new C.Cartesian3());
      var toS = C.Cartesian3.normalize(C.Cartesian3.subtract(basis.mid, dest, new C.Cartesian3()), new C.Cartesian3());
      dir = C.Cartesian3.normalize(C.Cartesian3.add(toC, toS, new C.Cartesian3()), new C.Cartesian3());
      up = C.Cartesian3.UNIT_Z;
    } else {
      var back = C.Cartesian3.multiplyByScalar(basis.T, -1.4e6, new C.Cartesian3());
      var out = C.Cartesian3.multiplyByScalar(basis.R, 2.5e5, new C.Cartesian3());
      dest = C.Cartesian3.add(C.Cartesian3.add(basis.mid, back, new C.Cartesian3()), out, new C.Cartesian3());
      dir = C.Cartesian3.normalize(C.Cartesian3.subtract(basis.mid, dest, new C.Cartesian3()), new C.Cartesian3());
      up = basis.N;
    }
    viewer.camera.flyTo({ destination: dest, orientation: { direction: dir, up: up }, duration: 1.0 });
    renderCamToggleText();
  }
  window.__rpoCam = comspocCamera;   // 測試／除錯用

  function setComspoc(on) {
    _comspocOn = on;
    _trailEnts.forEach(function (e) { e.show = on; });
    if (_rangeLabel) _rangeLabel.show = on;
    // 模式下碰撞球與短拖尾會遮住迴圈 → 隱藏；關閉時還原
    _pcSpheres.forEach(function (e) { e.show = on ? false : _pcSphereOn; });
    [_eP, _eS].forEach(function (e) { if (e && e.path) e.path.show = !on; });
    var cb = document.getElementById("camToggle");
    if (cb) cb.style.display = on ? "" : "none";
    if (on) comspocCamera(); else setViewpoint(_vp);
  }

  // 切換至指定衛星視角（相機跟隨該顆），並更新按鈕/標籤
  // 視角三態：t=第三方遠景（預設，綜觀整個事件）→ p=primary → s=secondary → t …
  function setViewpoint(which) {
    if (!_eP || !_eS || !_meta) return;
    _vp = which;
    if (which === "t") {
      try { viewer.trackedEntity = undefined; } catch (e) {}
      comspocCamera("wide");                 // 遠景構圖：地球在側、兩物體與軌道全入鏡
    } else {
      try { viewer.trackedEntity = (which === "p") ? _eP : _eS; } catch (e) {}
    }
    renderVpTexts();
  }

  // Cesium 時間軸醒目色帶：meta.phases = [{from,to,label,color}]（部署/訪G/返回/回收）
  function paintPhases(phases) {
    if (!viewer.timeline || !phases || !phases.length) return;
    try { viewer.timeline._highlightRanges = []; } catch (e) {}   // 換場景時清舊色帶
    phases.forEach(function (ph, i) {
      try {
        var r = viewer.timeline.addHighlightRange(ph.color || "#F2A73B", 4, 1 + i * 5);
        r.setRange(C.JulianDate.fromIso8601(ph.from), C.JulianDate.fromIso8601(ph.to));
      } catch (e) {}
    });
    try { viewer.timeline.resize(); } catch (e) {}
  }

  // ── 浮動視窗：相對軌跡投影（LVLH T–R 平面，與 Cesium 時鐘同步） ──
  // 衛星繞地球「一直繞圈圈」時，慣性/地圖視角看不出軌道升降；在對方 LVLH 座標中，
  // 徑向 R（縱軸，正=軌道較高）與沿軌 T（橫軸）的投影軌跡才能直接呈現接近/抬升/降軌。
  // 資料：orbit[].rtn = secondary−primary 於 primary LVLH；取負向即 primary 相對 secondary
  //（以 secondary 為中心；兩 LVLH 軸向於 km 級間距下近乎平行，投影用途足夠）。
  var _relwin = null, _relOn = true, _relCenterSec = true;   // 預設以 secondary（如 67689 太空飛機）為中心
  function destroyRelWindow() {
    if (_relwin && _relwin.el) { try { _relwin.el.remove(); } catch (e) {} }
    _relwin = null;
  }
  function buildRelWindow(orbit, meta, stepS0) {
    destroyRelWindow();
    if (!orbit.length || !orbit[0].rtn) return;
    var el = document.createElement("div");
    el.id = "relwin";
    el.innerHTML = '<div class="hd">\ud83e\udded <span id="relTitle"></span>'
      + '<span class="x" id="relSwap" data-i18n="rel_swap_label" data-i18n-title="rel_swap_title" title="' + t("rel_swap_title") + '">' + t("rel_swap_label") + '</span>'
      + '<span class="x" id="relClose" data-i18n-title="rel_close_title" title="' + t("rel_close_title") + '">\u2715</span></div>'
      + '<canvas id="relCanvas"></canvas>'
      + '<div class="ft" id="relFoot"></div>';
    document.body.appendChild(el);
    el.style.display = _relOn ? "" : "none";
    var hd = el.querySelector(".hd"), drag = null;
    hd.addEventListener("mousedown", function (e) {
      if (e.target.classList.contains("x")) return;
      drag = { x: e.clientX, y: e.clientY, l: el.offsetLeft, t: el.offsetTop };
      e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      el.style.left = (drag.l + e.clientX - drag.x) + "px";
      el.style.top = (drag.t + e.clientY - drag.y) + "px";
      el.style.right = "auto";
    });
    window.addEventListener("mouseup", function () { drag = null; });
    el.querySelector("#relClose").addEventListener("click", function () {
      _relOn = false; el.style.display = "none";
      var c = document.getElementById("relwinChk"); if (c) c.checked = false;
    });
    el.querySelector("#relSwap").addEventListener("click", function () {
      _relCenterSec = !_relCenterSec;
    });
    var stepS = stepS0 || 600;   // 由 summary.fine_step_s 覆寫（見下）
    var pts = orbit.map(function (o) {
      // 縱軸用「Δ高度」（測地高度差）而非直線 LVLH 的 R：大沿軌間距時 R 被軌道
      // 曲率項（~T²/2r，1,000 km 時約 71 km）淹沒，Δ高度才如實呈現軌道升降。
      return { ms: Date.parse(o.t), T: o.rtn[1], dh: (o.p[2] - o.s[2]) / 1000.0 };
    });
    // 單圈（~96 min）移動平均：把相對偏心造成的每圈擺動平掉，露出升降趨勢
    var per = Math.max(3, Math.round(96 * 60 / stepS)), half = per >> 1;
    var sm = pts.map(function (p, i) {
      var a = Math.max(0, i - half), b = Math.min(pts.length, i + half + 1), T = 0, dh = 0;
      for (var j = a; j < b; j++) { T += pts[j].T; dh += pts[j].dh; }
      return { ms: p.ms, T: T / (b - a), dh: dh / (b - a) };
    });
    _relwin = { el: el, cv: el.querySelector("#relCanvas"), pts: pts, sm: sm, meta: meta };
  }

  function drawRelWindow(nowMs) {
    if (!_relwin || !_relOn) return;
    var w = _relwin, cv = w.cv, meta = w.meta, dpr = window.devicePixelRatio || 1;
    var CW = cv.clientWidth || 460, CH = 330;
    if (cv.width !== CW * dpr || cv.height !== CH * dpr) { cv.width = CW * dpr; cv.height = CH * dpr; }
    var g = cv.getContext("2d");
    var sgn = _relCenterSec ? -1 : 1;   // 沿軌符號
    var hsgn = _relCenterSec ? 1 : -1;  // Δ高度：dh = primary−secondary，中心=secondary 時同號   // 中心=secondary → 畫 primary 相對位置（取負）
    var cName = _relCenterSec ? meta.secName : meta.primName;
    var mName = _relCenterSec ? meta.primName : meta.secName;
    document.getElementById("relTitle").textContent = tpl("rel_title", { name: cName });
    var Ts = w.pts.map(function (p) { return sgn * p.T; });
    var Rs = w.pts.map(function (p) { return hsgn * p.dh; });
    var tmin = Math.min.apply(null, Ts), tmax = Math.max.apply(null, Ts);
    var rmin = Math.min.apply(null, Rs), rmax = Math.max.apply(null, Rs);
    function pad(lo, hi, minSpan) {
      var c = (lo + hi) / 2, sp = Math.max(hi - lo, minSpan) * 1.16 / 2;
      return [c - sp, c + sp];
    }
    var tr = pad(tmin, tmax, 10), rr = pad(rmin, rmax, 4);
    var padL = 58, padR = 14, padT = 12, padB = 36;
    g.save(); g.scale(dpr, dpr);
    g.clearRect(0, 0, CW, CH);
    function X(t) { return padL + (t - tr[0]) / (tr[1] - tr[0]) * (CW - padL - padR); }
    function Y(r) { return CH - padB - (r - rr[0]) / (rr[1] - rr[0]) * (CH - padT - padB); }
    g.strokeStyle = "rgba(255,255,255,.07)"; g.lineWidth = 1; g.beginPath();
    [0.25, 0.5, 0.75].forEach(function (f) {
      var x = padL + f * (CW - padL - padR), y = padT + f * (CH - padT - padB);
      g.moveTo(x, padT); g.lineTo(x, CH - padB); g.moveTo(padL, y); g.lineTo(CW - padR, y);
    }); g.stroke();
    g.strokeStyle = "rgba(255,255,255,.25)"; g.beginPath();
    g.moveTo(X(0), padT); g.lineTo(X(0), CH - padB);
    g.moveTo(padL, Y(0)); g.lineTo(CW - padR, Y(0)); g.stroke();
    g.fillStyle = _relCenterSec ? SEC : PRIM;
    g.beginPath(); g.arc(X(0), Y(0), 4.5, 0, 6.283); g.fill();
    g.fillStyle = "#dfe6f0"; g.font = "13px monospace";
    g.fillText(cName, Math.min(X(0) + 8, CW - 126), Y(0) - 8);
    g.fillStyle = "#8b96a8";
    g.fillText(t("axis_t"), CW - 136, CH - 8);
    g.save(); g.translate(13, 210); g.rotate(-Math.PI / 2);
    g.fillText(t("axis_dh"), 0, 0); g.restore();
    g.fillText(tr[0].toFixed(0), padL, CH - 22);
    g.fillText(tr[1].toFixed(0), CW - padR - 44, CH - 22);
    g.fillText(rr[1].toFixed(1), 18, padT + 12);
    g.fillText(rr[0].toFixed(1), 18, CH - padB - 2);
    var n = w.pts.length, k = 0;
    while (k < n && w.pts[k].ms <= nowMs) k++;
    function path(arr, from, to, style, width) {
      g.strokeStyle = style; g.lineWidth = width; g.beginPath();
      for (var i = from; i < to; i++) {
        var x = X(sgn * arr[i].T), y = Y(hsgn * arr[i].dh);
        if (i === from) g.moveTo(x, y); else g.lineTo(x, y);
      }
      g.stroke();
    }
    var bright = _relCenterSec ? PRIM : SEC;
    if (n > 1) path(w.pts, 0, n, "rgba(139,150,168,.22)", 1);          // 全程逐點（淡細）
    if (k > 1) path(w.pts, 0, k, "rgba(242,167,59,.45)", 1);           // 已播放逐點（半亮細）
    if (k > 1) path(w.sm, 0, k, bright, 2.4);                           // 已播放單圈平均（亮粗＝趨勢）
    if (k > 0) {
      var cur = w.pts[Math.min(k - 1, n - 1)];
      var cx = X(sgn * cur.T), cy = Y(hsgn * cur.dh);
      g.fillStyle = CRIT; g.beginPath(); g.arc(cx, cy, 5, 0, 6.283); g.fill();
      g.strokeStyle = "rgba(255,92,78,.5)"; g.lineWidth = 1;
      g.beginPath(); g.moveTo(X(0), Y(0)); g.lineTo(cx, cy); g.stroke();
      var ft = document.getElementById("relFoot");
      if (ft) ft.textContent = tpl("rel_foot", { name: mName, t: (sgn * cur.T).toFixed(1), dh: (hsgn * cur.dh).toFixed(2) });
    }
    g.restore();
  }


  function buildScene(data) {
    clearScene();
    _hasTrail = false; _trailInfo = null; _pcDims = null;
    var meta = data.meta, orbit = data.orbit, summary = data.summary;
    _meta = meta;
    buildHUD(meta);

    var t0 = C.JulianDate.fromIso8601(orbit[0].t);
    var t1 = C.JulianDate.fromIso8601(orbit[orbit.length - 1].t);
    // 軌道參數連結改用本場景時段（前後各 30 天）：歷史案例（如 2024 年）落在預設「最近 1 年」之外
    var ol = document.getElementById("orbitLink");
    if (ol && _curP != null) {
      var dpad = 30 * 86400000;
      var dStr = function (ms) { return new Date(ms).toISOString().slice(0, 10); };
      ol.href = "/orbit?norad=" + _curP + "," + _curS +
                "&start=" + dStr(Date.parse(orbit[0].t) - dpad) +
                "&end=" + dStr(Date.parse(orbit[orbit.length - 1].t) + dpad);
    }

    var t0ms = C.JulianDate.toDate(t0).getTime();
    var stepMs = (summary.fine_step_s || 60) * 1000;
    function sampleAt(ms) {
      var idx = Math.round((ms - t0ms) / stepMs);
      return orbit[Math.min(orbit.length - 1, Math.max(0, idx))];
    }
    window.__rpoSampleAt = sampleAt;

    var pPos = sampledPos(orbit, "p"), sPos = sampledPos(orbit, "s");
    var trailS = +meta.trail_s || 5400;
    var eP = addSat(meta.primName, pPos, PRIM, t0, t1, trailS);
    var eS = addSat(meta.secName, sPos, SEC, t0, t1, trailS);
    _eP = eP; _eS = eS;

    // ── 碰撞機率球：兩顆衛星各畫一個 3σ 不確定「橢球」，三軸獨立（徑向 R / 沿軌 T / 越軌 N），
    //    各自配向至該衛星之 RTN(LVLH) 座標系；半徑 = 3σ_R / 3σ_T / 3σ_N；顏色隨當下 Pc。
    var sr = +meta.sigma_r || 0.1, st = +meta.sigma_t || 0.5, sn = +meta.sigma_n;
    if (!(sn > 0)) sn = sr;                       // 舊快取缺 σ_n → 退回 σ_r
    var rR = 3 * sr * 1000, rT = 3 * st * 1000, rN = 3 * sn * 1000;   // 半軸（公尺）

    // 由某位置屬性 + 有限差分速度求 RTN 基底，回傳「局部→世界(ECEF)」旋轉四元數之函式。
    // 橢球局部軸 x→R、y→T、z→N（對應 radii 之三軸）。
    function makeRtnQuat(posProp) {
      return function (time) {
        var p = posProp.getValue(time);
        if (!p) return C.Quaternion.IDENTITY;
        var p2 = posProp.getValue(C.JulianDate.addSeconds(time, 1, new C.JulianDate()))
              || posProp.getValue(C.JulianDate.addSeconds(time, -1, new C.JulianDate()));
        if (!p2) return C.Quaternion.IDENTITY;
        var R = C.Cartesian3.normalize(p, new C.Cartesian3());
        var v = C.Cartesian3.subtract(p2, p, new C.Cartesian3());
        if (C.Cartesian3.magnitude(v) < 1e-6) return C.Quaternion.IDENTITY;
        var vh = C.Cartesian3.normalize(v, v);
        var N = C.Cartesian3.cross(R, vh, new C.Cartesian3());
        if (C.Cartesian3.magnitude(N) < 1e-9) return C.Quaternion.IDENTITY;
        N = C.Cartesian3.normalize(N, N);
        var T = C.Cartesian3.normalize(C.Cartesian3.cross(N, R, new C.Cartesian3()), new C.Cartesian3());
        var m = new C.Matrix3(R.x, T.x, N.x, R.y, T.y, N.y, R.z, T.z, N.z);  // 欄=R,T,N
        return C.Quaternion.fromRotationMatrix(m, new C.Quaternion());
      };
    }

    function makePcEllipsoid(posProp) {
      return viewer.entities.add({
        position: posProp,
        orientation: new C.CallbackProperty(makeRtnQuat(posProp), false),
        show: _pcSphereOn,
        ellipsoid: {
          radii: new C.Cartesian3(rR, rT, rN),   // x=R, y=T, z=N（三軸獨立）
          fill: true,
          material: new C.ColorMaterialProperty(new C.CallbackProperty(function (time) {
            var s = sampleAt(C.JulianDate.toDate(time).getTime());
            return riskColor(s.pc).withAlpha(0.22);
          }, false)),
          outline: true,
          outlineWidth: 1.0,
          outlineColor: new C.CallbackProperty(function (time) {
            var s = sampleAt(C.JulianDate.toDate(time).getTime());
            return riskColor(s.pc).withAlpha(0.6);
          }, false),
        },
      });
    }

    _pcSpheres = [makePcEllipsoid(pPos), makePcEllipsoid(sPos)];   // 兩顆衛星各一
    buildTrails(data.trail, meta);
    buildRelWindow(orbit, meta, summary.fine_step_s || 600);
    buildRangeLabel(pPos, sPos, meta, sampleAt);
    if (!data.trail) {
      var ccInfo = document.getElementById("comspocInfo");
      if (ccInfo) ccInfo.textContent = t("comspoc_no_trail");
    }
    _pcDims = { rR: rR.toFixed(0), rT: rT.toFixed(0), rN: rN.toFixed(0), sr: sr, st: st, sn: sn };
    var info = document.getElementById("pcSphereInfo");
    if (info) info.textContent = tpl("pc_sphere_info", _pcDims);

    var dmin = summary.d_min, dmax = orbit.reduce(function (m, o) { return Math.max(m, o.d); }, 0);
    viewer.entities.add({
      polyline: {
        positions: new C.CallbackProperty(function (time) {
          var a = pPos.getValue(time), b = sPos.getValue(time);
          return (a && b) ? [a, b] : [];
        }, false),
        width: 1.6,
        material: new C.ColorMaterialProperty(new C.CallbackProperty(function (time) {
          var s = sampleAt(C.JulianDate.toDate(time).getTime());
          var frac = dmax > dmin ? (s.d - dmin) / (dmax - dmin) : 0;
          return C.Color.fromCssColorString(CRIT).withAlpha(0.9 - 0.55 * Math.min(1, Math.max(0, frac)));
        }, false)),
      },
    });

    var iMin = 0; for (var i = 1; i < orbit.length; i++) if (orbit[i].d < orbit[iMin].d) iMin = i;
    var om = orbit[iMin];
    viewer.entities.add({
      position: C.Cartesian3.fromDegrees(om.s[0], om.s[1], om.s[2]),
      point: { pixelSize: 9, color: C.Color.fromCssColorString(CRIT), outlineColor: C.Color.WHITE, outlineWidth: 1.5 },
      label: { text: "TCA " + fmtRange(om.d) + " km", font: "11px monospace",
        fillColor: C.Color.fromCssColorString(CRIT), pixelOffset: new C.Cartesian2(0, 16),
        showBackground: true, backgroundColor: C.Color.fromCssColorString("#0A0D13").withAlpha(0.6) },
    });

    var spanSec = C.JulianDate.secondsDifference(t1, t0);
    viewer.clock.startTime = t0.clone();
    viewer.clock.stopTime = t1.clone();
    viewer.clock.currentTime = C.JulianDate.addSeconds(t0, spanSec / 2, new C.JulianDate());
    viewer.clock.clockRange = C.ClockRange.LOOP_STOP;
    // 播放速度：全窗約 3 分鐘播完（原 90 s 減半），讓機動段看得清楚
    viewer.clock.multiplier = Math.max(15, spanSec / 180);
    viewer.clock.shouldAnimate = true;
    paintPhases(meta.phases);                       // 需在 zoomTo 前掛上，色帶才會隨刻度繪出
    if (viewer.timeline) viewer.timeline.zoomTo(t0, t1);

    _tick = function (clock) {
      var nowMs = C.JulianDate.toDate(clock.currentTime).getTime();
      drawRelWindow(nowMs);
      var s = sampleAt(nowMs);
      document.getElementById("k_range").textContent = fmtRange(s.d);
      document.getElementById("k_pc").innerHTML = fmtPc(s.pc);
      document.getElementById("k_palt").textContent = (s.p[2] / 1000).toFixed(1);
      document.getElementById("k_salt").textContent = (s.s[2] / 1000).toFixed(1);
    };
    viewer.clock.onTick.addEventListener(_tick);

    document.getElementById("loading").style.display = "none";
    // 預設第三方遠景綜觀事件；操作者可循 遠景→primary→secondary 切換
    setViewpoint("t");
    if (_comspocOn) setComspoc(true);

    // 開場導覽：遠景播放 1 秒 → 自動切到太空飛機（Spacecraft）跟隨視角，
    // 從 TCA 前 10 分鐘開始以 60 倍速播放，相機拉遠到兩星與軌跡同時入鏡。
    // 以 ?intro=0 關閉。
    var introOn = !/[?&]intro=0\b/.test(location.search);
    var mySeq = _loadSeq;
    if (introOn && !_comspocOn) {
      setTimeout(function () {
        if (mySeq !== _loadSeq || !viewer) return;          // 已切換到別的配對
        var which = /SPACECRAFT/i.test(meta.primName) ? "p"
                  : (/SPACECRAFT/i.test(meta.secName) ? "s" : "p");
        // 目標：排除已合體（d<0.2 km，如部署前／回收後）樣本後的最接近點，兩物體才分得開
        var jT = -1;
        for (var q = 0; q < orbit.length; q++) if (orbit[q].d >= 0.2 && (jT < 0 || orbit[q].d < orbit[jT].d)) jT = q;
        var oT = jT >= 0 ? orbit[jT] : om;
        var D = Math.min(4.0e5, Math.max(5.0e3, (oT.d || 0) * 1000 * 20));   // 公尺：5–400 km
        var off = new C.Cartesian3(0, -D, D * 0.45);                         // 南側、偏上俯視
        [_eP, _eS].forEach(function (e) { if (e) e.viewFrom = off; });
        var tca = C.JulianDate.fromIso8601(oT.t);
        var start = C.JulianDate.addSeconds(tca, -600, new C.JulianDate());
        if (C.JulianDate.lessThan(start, viewer.clock.startTime)) start = viewer.clock.startTime.clone();
        viewer.clock.currentTime = start;
        viewer.clock.multiplier = 60;
        viewer.clock.shouldAnimate = true;
        setViewpoint(which);
      }, 1000);
    }

    stat("stat_summary", { dmin: fmtRange(summary.d_min), pc: fmtPc(summary.pc_max).replace("&lt;", "<"), n: summary.n_orbit });
  }

  function loadScene(primary, secondary, onDone, variant) {
    var seq = ++_loadSeq;
    _curP = primary; _curS = secondary; _curV = variant || "";
    var vq = _curV ? "variant=" + encodeURIComponent(_curV) : "";
    stat("loading_scene_pair", { p: primary, s: secondary });
    try { history.replaceState(null, "", "/rpo?primary=" + primary + "&secondary=" + secondary + (vq ? "&" + vq : "")); } catch (e) {}
    // 靜態影像報告連結（五面板 PNG）：中文介面出中文版，其餘出英文版
    var rl = document.getElementById("reportLink");
    if (rl) {
      var lang = "zh"; try { lang = localStorage.getItem("rpo3d_lang") || "zh"; } catch (e) {}
      rl.href = "/api/rpo/" + primary + "/" + secondary + "/report.png?lang=" + (lang === "zh" ? "zh" : "en") +
                (vq ? "&" + vq : "");
    }
    // 雙星軌道要素歷史比較（/orbit 疊圖模式）
    var ol = document.getElementById("orbitLink");
    if (ol) ol.href = "/orbit?norad=" + primary + "," + secondary;
    fetch("/api/rpo/" + primary + "/" + secondary + (vq ? "?" + vq : "")).then(function (r) { return r.json(); }).then(function (data) {
      if (seq !== _loadSeq) return;                       // 已被更新的請求取代
      if (data.error) { stat("load_fail", { error: data.error }, true); return; }
      if (!data.orbit || !data.orbit.length) { stat("no_valid_orbit", null, true); return; }
      buildScene(data);
      var sel = document.getElementById("pairSel");
      if (sel) sel.value = primary + "," + secondary + (_curV ? "," + _curV : "");
      if (onDone) onDone();
    }).catch(function (e) {
      if (seq === _loadSeq) stat("fetch_fail", { error: e.message }, true);
    });
  }

  function optionLabel(p) {
    var mp = fmtRange(p.miss_km);
    return (p.primary_name || p.primary_norad) + " × " + (p.secondary_name || p.secondary_norad)
      + "  ·  " + mp + " km  ·  Pc " + (p.Pc_str || "—");
  }

  function populatePairs(threshold) {
    var sel = document.getElementById("pairSel");
    stat("scanning_pairs");
    // 先取精選案例（歷史 RPO，如神龍系列），再併入即時近距離配對
    fetch("/api/rpo/presets").then(function (r) { return r.json(); }).catch(function () { return { presets: [] }; })
      .then(function (pd) {
        var presets = (pd && pd.presets) || [];
        fetch("/api/conjunctions?threshold_km=" + (threshold || 10)).then(function (r) { return r.json(); }).then(function (d) {
          var pairs = (d && d.pairs) || [];
          var html = "";
          var cur = _curP != null ? (_curP + "," + _curS + (_curV ? "," + _curV : "")) : null;
          // 保留目前（預設/深連結）配對於清單頂端
          if (cur) html += '<option value="' + cur + '">' + tpl("cur_pair", { p: _curP, s: _curS }) + "</option>";
          // 精選案例（置於即時配對之前）
          for (var j = 0; j < presets.length; j++) {
            var pr = presets[j];
            var pv = pr.primary + "," + pr.secondary + (pr.variant ? "," + pr.variant : "");
            if (pv === cur) continue;
            html += '<option value="' + pv + '">' + tpl("preset_case", { title: pr.title }) + "</option>";
          }
          for (var i = 0; i < pairs.length && i < 150; i++) {
            var p = pairs[i];
            var v = p.primary_norad + "," + p.secondary_norad;
            if (v === cur) continue;   // 避免重複
            html += '<option value="' + v + '">' + optionLabel(p) + "</option>";
          }
          sel.innerHTML = html || '<option value="">' + t("no_pairs") + '</option>';
          if (cur) sel.value = cur;
          stat("pairs_summary", { presets: presets.length, pairs: pairs.length, thr: threshold || 10 });
        }).catch(function (e) { stat("pair_list_fail", { error: e.message }, true); });
      });
  }

  window.startRPO = function () {
    try { initCesium(); } catch (e) { warn(tpl("cesium_init_fail", { error: e.message })); return; }
    var initP = window.RPO_PRIMARY || 58573, initS = window.RPO_SECONDARY || 59884;
    _curP = initP; _curS = initS; _curV = window.RPO_VARIANT || "";

    var sel = document.getElementById("pairSel");
    if (sel) sel.addEventListener("change", function () {
      var v = this.value; if (!v) return;
      var a = v.split(","); loadScene(parseInt(a[0], 10), parseInt(a[1], 10), null, a[2] || "");
    });
    var btn = document.getElementById("rescan");
    if (btn) btn.addEventListener("click", function () {
      var thr = parseFloat(document.getElementById("thr").value) || 10;
      populatePairs(thr);
    });
    var vpBtn = document.getElementById("vpToggle");
    if (vpBtn) vpBtn.addEventListener("click", function () {
      setViewpoint({ t: "p", p: "s", s: "t" }[_vp] || "t");   // 遠景→primary→secondary 循環
    });
    var pcChk = document.getElementById("pcSphereChk");
    _pcSphereOn = pcChk ? pcChk.checked : true;   // 預設開啟
    if (pcChk) pcChk.addEventListener("change", function () {
      _pcSphereOn = this.checked;
      _pcSpheres.forEach(function (e) { e.show = _pcSphereOn; });
    });

    var rwChk = document.getElementById("relwinChk");
    if (rwChk) {
      _relOn = rwChk.checked;
      rwChk.addEventListener("change", function () {
        _relOn = this.checked;
        if (_relwin && _relwin.el) _relwin.el.style.display = _relOn ? "" : "none";
      });
    }

    var ccChk = document.getElementById("comspocChk");
    if (ccChk) {
      _comspocOn = ccChk.checked;
      ccChk.addEventListener("change", function () { setComspoc(this.checked); });
    }
    var camBtn = document.getElementById("camToggle");
    if (camBtn) camBtn.addEventListener("click", function () {
      comspocCamera(_camMode === "wide" ? "close" : "wide");
    });

    populatePairs(parseFloat((document.getElementById("thr") || {}).value) || 10);
    loadScene(initP, initS, null, _curV);
  };

  setLang(LANG);
})();
