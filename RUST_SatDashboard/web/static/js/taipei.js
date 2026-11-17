'use strict';

/* ═══════════════════════════════════════════════════════════════════════════
   三語字典（繁中／英文／日文）— 台北衛星覆蓋時間軸頁
   注意：I18N/t/tpl/setLang 置於 startApp() 之外，讓語言切換按鈕在 Cesium
   尚未載入完成前也能運作；動態面板（分類概況／過頂預報／時間軸徽章等）
   則透過 _refreshUI 掛勾，於 startApp() 初始化後回填。
   ═══════════════════════════════════════════════════════════════════════════ */
const I18N = {
  zh: {
    doc_title: '台北覆蓋分析 — Cesium 2D',
    view_sky: '天球', view_map: '地圖',
    header_title: '台北覆蓋分析 — 台北周邊 2,000 km 內的衛星通過',
    btn_refresh: '更新',
    nav_home: '返回主頁',
    panel_title: '衛星分類覆蓋',
    panel_sub: '台北 25.03°N 121.57°E　·　仰角遮蔽 5°',
    tab_overview: '分類概況',
    tab_passes: '衛星通過預報',
    step_label_prefix: '時間步長：',
    btn_apply_step: '套用',
    step_label_min: '{n} 分',
    step_label_60: '60 分',
    panel_loading: '載入中...',
    map_loading: '初始化地圖...',
    legend_title: '衛星分類',
    cat_us_eo_label: '美國商用光學', cat_us_eo_sub: 'Vantor/Maxar · Planet SkySat · BlackSky',
    cat_cn_comm_label: '中國商用光學', cat_cn_comm_sub: 'SuperView · 高分 · 吉林 · 北京三號',
    cat_cn_mil_label: '中國軍用偵察', cat_cn_mil_sub: '遙感 Yaogan',
    cat_tw_tasa_label: '台灣 TASA', cat_tw_tasa_sub: 'Formosat-2/-3(已退役)/-5/-7/-8',
    cat_starlink_label: 'Starlink 星鏈', cat_starlink_sub: 'SpaceX · Gen1/Gen2/V2 Mini',
    legend_circle_note: '2000 km 覆蓋圈',
    tl_bounds_past: '−30天', tl_bounds_future: '+30天',
    tl_now_btn: '現在',
    tl_badge_now: '現在', tl_badge_hist: '歷史', tl_badge_future: '預測',
    status_total: '衛星', status_visible: '可見', status_plotted: '圖上', status_time: '時刻',
    overview_loading: '資料載入中...',
    unit_count: '顆',
    stat_db: '資料庫', stat_visible: '可見', stat_plotted: '圖上',
    note_filtered: '已被篩選隱藏',
    note_truncated: '大星座僅顯示台北可見的衛星',
    passes_loading: '衛星通過預報載入中（10–30 秒）...',
    passes_none: '24 小時內無衛星通過記錄',
    pass_duration: '持續時間 {m} 分 {s} 秒',
    init_fail: '初始化失敗: {msg}',
  },
  ja: {
    doc_title: '台北カバレッジ分析 — Cesium 2D',
    view_sky: '天球', view_map: '地図',
    header_title: '台北カバレッジ分析 — 台北から半径2,000 km圏内の衛星通過',
    btn_refresh: '更新',
    nav_home: 'ホームへ戻る',
    panel_title: '衛星カテゴリ別カバレッジ',
    panel_sub: '台北 北緯25.03° 東経121.57°　・　仰角マスク 5°',
    tab_overview: 'カテゴリ概況',
    tab_passes: '衛星通過予測',
    step_label_prefix: '時間ステップ：',
    btn_apply_step: '適用',
    step_label_min: '{n}分',
    step_label_60: '60分',
    panel_loading: '読み込み中...',
    map_loading: '地図を初期化中...',
    legend_title: '衛星カテゴリ',
    cat_us_eo_label: '米国商用光学', cat_us_eo_sub: 'Vantor/Maxar・Planet SkySat・BlackSky',
    cat_cn_comm_label: '中国商用光学', cat_cn_comm_sub: 'SuperView・高分・吉林・北京三号',
    cat_cn_mil_label: '中国軍用偵察', cat_cn_mil_sub: '遥感（Yaogan）',
    cat_tw_tasa_label: '台湾 TASA', cat_tw_tasa_sub: 'Formosat-2/-3（退役）/-5/-7/-8',
    cat_starlink_label: 'Starlink', cat_starlink_sub: 'SpaceX・Gen1/Gen2/V2 Mini',
    legend_circle_note: '半径2000kmカバレッジ圏',
    tl_bounds_past: '−30日', tl_bounds_future: '+30日',
    tl_now_btn: '現在',
    tl_badge_now: '現在', tl_badge_hist: '過去', tl_badge_future: '予測',
    status_total: '衛星', status_visible: '可視', status_plotted: '地図上に表示', status_time: '時刻',
    overview_loading: 'データ読み込み中...',
    unit_count: '機',
    stat_db: 'DB', stat_visible: '可視', stat_plotted: '地図表示',
    note_filtered: 'フィルタで非表示',
    note_truncated: '大規模コンステレーションは台北から可視の衛星のみ表示',
    passes_loading: '衛星通過予測を読み込み中（10〜30秒）...',
    passes_none: '24時間以内に衛星の通過はありません',
    pass_duration: '通過時間 {m}分{s}秒',
    init_fail: '初期化に失敗しました: {msg}',
  },
  en: {
    doc_title: 'Taipei Coverage Analysis — Cesium 2D',
    view_sky: 'Sky', view_map: 'Map',
    header_title: 'Taipei Coverage Analysis — Satellite Passes within 2,000 km of Taipei',
    btn_refresh: 'Refresh',
    nav_home: 'Home',
    panel_title: 'Satellite Category Coverage',
    panel_sub: 'Taipei 25.03°N 121.57°E   ·   Elevation Mask Angle: 5°',
    tab_overview: 'Category Overview',
    tab_passes: 'Satellite Pass Forecast',
    step_label_prefix: 'Time Step:',
    btn_apply_step: 'Apply',
    step_label_min: '{n} min',
    step_label_60: '60 min',
    panel_loading: 'Loading...',
    map_loading: 'Initializing map...',
    legend_title: 'Satellite Categories',
    cat_us_eo_label: 'US Commercial Optical', cat_us_eo_sub: 'Vantor/Maxar · Planet SkySat · BlackSky',
    cat_cn_comm_label: 'China Commercial Optical', cat_cn_comm_sub: 'SuperView · Gaofen · Jilin-1 · Beijing-3',
    cat_cn_mil_label: 'China Military Reconnaissance', cat_cn_mil_sub: 'Yaogan (Remote Sensing)',
    cat_tw_tasa_label: 'Taiwan TASA', cat_tw_tasa_sub: 'Formosat-2/-3 (retired)/-5/-7/-8',
    cat_starlink_label: 'Starlink', cat_starlink_sub: 'SpaceX · Gen1/Gen2/V2 Mini',
    legend_circle_note: '2000 km Coverage Radius',
    tl_bounds_past: '−30 days', tl_bounds_future: '+30 days',
    tl_now_btn: 'Now',
    tl_badge_now: 'Now', tl_badge_hist: 'Past', tl_badge_future: 'Forecast',
    status_total: 'Satellites', status_visible: 'Visible', status_plotted: 'Displayed on Map', status_time: 'Time',
    overview_loading: 'Loading data...',
    unit_count: 'sats',
    stat_db: 'DB', stat_visible: 'Visible', stat_plotted: 'Displayed on Map',
    note_filtered: 'Hidden by filter',
    note_truncated: 'Large constellations show only satellites visible from Taipei',
    passes_loading: 'Loading pass forecast (10–30 s)...',
    passes_none: 'No satellite passes in the next 24 hours',
    pass_duration: 'Duration: {m} min {s} sec',
    init_fail: 'Initialization failed: {msg}',
  },
};
const LOCALE_MAP = {zh:'zh-TW', en:'en-US', ja:'ja-JP'};
let LANG = localStorage.getItem('taipei_lang') || 'zh';
if(!I18N[LANG]) LANG = 'zh';
let _refreshUI = null;  // startApp() 掛勾：語言切換時重繪動態內容

function t(key){
  const d = I18N[LANG] || I18N.zh;
  return (key in d) ? d[key] : (I18N.zh[key] !== undefined ? I18N.zh[key] : key);
}
function tpl(key, vars){
  let s = t(key);
  Object.keys(vars || {}).forEach(k => { s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]); });
  return s;
}
function setLang(lang){
  if(!I18N[lang]) return;
  LANG = lang;
  localStorage.setItem('taipei_lang', lang);
  document.documentElement.lang = LOCALE_MAP[lang] || 'zh-TW';
  document.title = t('doc_title');

  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === lang);
  });

  if(_refreshUI) _refreshUI();
  if(window.TaipeiSky) window.TaipeiSky.onLang();
}

function startApp(){

const TAIPEI_LAT=25.0330, TAIPEI_LON=121.5654;
const CATS={
  US_EO:  {labelKey:'cat_us_eo_label',   subKey:'cat_us_eo_sub',   color:'#4488FF'},
  CN_COMM:{labelKey:'cat_cn_comm_label', subKey:'cat_cn_comm_sub', color:'#FF9800'},
  CN_MIL: {labelKey:'cat_cn_mil_label',  subKey:'cat_cn_mil_sub',  color:'#F44336'},
  TW_TASA:{labelKey:'cat_tw_tasa_label', subKey:'cat_tw_tasa_sub', color:'#00E5FF'},
  STARLINK:{labelKey:'cat_starlink_label',subKey:'cat_starlink_sub',color:'#A855F7'},
};

let viewer=null, satDs=null, circleDs=null, bordersDs=null;
let coverageData=null, passesData=null;
let activePanelTab='overview';
let activeCatFilter=null;
let _plotted={};   // 各類別圖上實繪顆數（與分類概況面板同步）

// ── Timeline state ─────────────────────────────────────────────────────────
let _tlMin=0;            // minutes offset from now (0=now, negative=past)
let _tlDebounce=null;
let _autoTimer=null;
let _coverageCtrl=null;   // AbortController for in-flight coverage fetch
let _passesCtrl=null;     // AbortController for in-flight passes fetch
let _loading=false;       // prevents concurrent _loadForTs calls
let _pendingReload=false; // 載入期間的時間軸操作 → 排隊於完成後重載（避免默默丟棄）
let _lastAction=0;        // rate-limit timestamp for buttons
const _TL_MAX=43200;     // 30 days in minutes

// ── Clock ──────────────────────────────────────────────────────────────────
function _cst(d){
  return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19)+' CST';
}
document.getElementById('clock').textContent=_cst(new Date());
setInterval(function(){document.getElementById('clock').textContent=_cst(new Date());},1000);

// ── Cesium init ────────────────────────────────────────────────────────────
async function initCesium(){
  Cesium.Ion.defaultAccessToken=(window.CESIUM_ION_TOKEN||'');

  viewer=new Cesium.Viewer('cesiumContainer',{
    // Initialise directly in 2D — no morph transition, no drift
    sceneMode:           Cesium.SceneMode.SCENE2D,
    animation:           false,
    timeline:            false,
    baseLayerPicker:     false,
    imageryProvider: new Cesium.TileMapServiceImageryProvider({
      url:(window.CESIUM_BASE_URL||'/cesium/')+'Assets/Textures/NaturalEarthII/',
      fileExtension:'jpg',
      credit:'Natural Earth II',
    }),
    terrainProvider:     new Cesium.EllipsoidTerrainProvider(),
    sceneModePicker:     false,
    infoBox:             false,
    geocoder:            false,
    homeButton:          false,
    navigationHelpButton:false,
    selectionIndicator:  false,
    fullscreenButton:    false,
  });

  viewer.cesiumWidget.creditContainer.style.display='none';
  // Freeze clock — prevents time-driven camera updates that cause 2D drift
  viewer.clock.shouldAnimate=false;

  // setView() is synchronous — unlike flyTo() it does NOT start an animation
  // that can drift the camera position after load.
  viewer.camera.setView({
    destination:Cesium.Rectangle.fromDegrees(100.0,9.0,144.0,41.0),
  });

  // Disable rotation and tilt — meaningless in 2D and can cause drift
  viewer.scene.screenSpaceCameraController.enableRotate=false;
  viewer.scene.screenSpaceCameraController.enableTilt=false;

  satDs=new Cesium.CustomDataSource('satellites');
  circleDs=new Cesium.CustomDataSource('circle');
  await viewer.dataSources.add(satDs);
  await viewer.dataSources.add(circleDs);
  _drawCircle();

  // 渲染防護：Cesium 遇幾何錯誤（如 RangeError）會停止渲染，
  // 這裡移除肇事的國界圖層並重啟 render loop，避免整頁死掉。
  viewer.scene.renderError.addEventListener(function(_scene,error){
    console.error('Cesium 渲染錯誤，嘗試自動恢復:',error);
    try{
      if(bordersDs){viewer.dataSources.remove(bordersDs,true);bordersDs=null;}
    }catch(_e){/* noop */}
    setTimeout(function(){
      try{viewer.useDefaultRenderLoop=true;}catch(_e){/* noop */}
    },200);
  });

  document.getElementById('map-loading').style.display='none';
}

function _drawCircle(){
  const R=6371.0, cover=2000.0, ar=cover/R, n=128;
  const lat0=Cesium.Math.toRadians(TAIPEI_LAT);
  const lon0=Cesium.Math.toRadians(TAIPEI_LON);
  const pts=[];
  for(let i=0;i<=n;i++){
    const b=(i/n)*2*Math.PI;
    const la=Math.asin(Math.sin(lat0)*Math.cos(ar)+Math.cos(lat0)*Math.sin(ar)*Math.cos(b));
    const lo=lon0+Math.atan2(Math.sin(b)*Math.sin(ar)*Math.cos(lat0),
                             Math.cos(ar)-Math.sin(lat0)*Math.sin(la));
    pts.push(Cesium.Cartesian3.fromRadians(lo,la));
  }
  circleDs.entities.add({polyline:{positions:pts,width:2,
    material:new Cesium.ColorMaterialProperty(Cesium.Color.fromCssColorString('#FFD600').withAlpha(0.75)),
    arcType:Cesium.ArcType.NONE}});
  circleDs.entities.add({position:Cesium.Cartesian3.fromDegrees(TAIPEI_LON,TAIPEI_LAT),
    point:{pixelSize:9,color:Cesium.Color.fromCssColorString('#FFD600'),
           outlineColor:Cesium.Color.BLACK,outlineWidth:1.5}});
}

// ── Data loading ───────────────────────────────────────────────────────────
async function loadCoverage(ts=null){
  if(_coverageCtrl) _coverageCtrl.abort();
  _coverageCtrl=new AbortController();
  const url=ts?'/api/taipei_coverage_at?ts='+encodeURIComponent(ts):'/api/taipei_coverage';
  try{
    const r=await fetch(url,{signal:_coverageCtrl.signal});
    if(!r.ok) throw new Error('HTTP '+r.status);
    coverageData=await r.json();
    _updateMarkers();
    _updateStatus();
    if(activePanelTab==='overview') renderOverview();
  }catch(e){
    if(e.name==='AbortError') return;
    console.warn('Coverage error',e);
  }
}

let _passesStepSec=900;  // 預設 15 分鐘步長

function updateStepLabel(v){
  document.getElementById('step-label').textContent=v>=60?t('step_label_60'):tpl('step_label_min',{n:v});
}

function applyStepChange(){
  const stepMin=parseInt(document.getElementById('step-slider').value);
  _passesStepSec=stepMin*60;
  loadPasses();
}

async function loadPasses(ts=null){
  if(_passesCtrl) _passesCtrl.abort();
  _passesCtrl=new AbortController();
  let url=ts
    ?'/api/taipei_passes_at?ts='+encodeURIComponent(ts)+'&step_sec='+_passesStepSec
    :'/api/taipei_passes?step_sec='+_passesStepSec;
  try{
    const r=await fetch(url,{signal:_passesCtrl.signal});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(d.status==='computing'){
      // 後端正在計算，2秒後重試
      setTimeout(()=>loadPasses(ts),2000);
      return;
    }
    passesData=d;
    if(activePanelTab==='passes') renderPasses();
  }catch(e){
    if(e.name==='AbortError') return;
    console.warn('Passes error',e);
  }
}

function refreshAll(){
  const now=Date.now();
  if(now-_lastAction<1000) return;
  _lastAction=now;
  clearTimeout(_tlDebounce);
  clearTimeout(_autoTimer);
  _loadForTs();
}

// ── Markers ────────────────────────────────────────────────────────────────
function _updateMarkers(){
  if(!coverageData||!satDs) return;
  satDs.entities.suspendEvents();
  satDs.entities.removeAll();
  _plotted={};
  Object.entries(coverageData.categories).forEach(([catId,cd])=>{
    if(activeCatFilter&&activeCatFilter!==catId){_plotted[catId]=0;return;}
    const col=Cesium.Color.fromCssColorString(cd.color);
    // 超過 300 顆時只畫可見衛星，避免大星座（如 Starlink）拖慢 2D 地圖
    const allSats=cd.satellites||[];
    const satsToPlot=allSats.length>300?allSats.filter(s=>s.visible):allSats;
    _plotted[catId]=satsToPlot.length;
    satsToPlot.forEach(s=>{
      satDs.entities.add({
        id:'sat_'+s.norad_id,
        position:Cesium.Cartesian3.fromDegrees(s.lon,s.lat,0),
        point:{
          pixelSize:s.visible?8:5,
          color:s.visible?col:col.withAlpha(0.4),
          outlineColor:s.visible?Cesium.Color.WHITE.withAlpha(0.85):Cesium.Color.WHITE.withAlpha(0.2),
          outlineWidth:s.visible?1.5:0.5,
        },
        label:{
          text:s.name,
          font:'11px Tahoma,sans-serif',
          fillColor:Cesium.Color.WHITE,
          outlineColor:Cesium.Color.BLACK,
          outlineWidth:2,
          style:Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset:new Cesium.Cartesian2(0,-14),
          horizontalOrigin:Cesium.HorizontalOrigin.CENTER,
          verticalOrigin:Cesium.VerticalOrigin.BOTTOM,
          distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,4.6e6),
          disableDepthTestDistance:Number.POSITIVE_INFINITY,
        },
      });
    });
  });
  satDs.entities.resumeEvents();
  _updateStatus();
  if(activePanelTab==='overview') renderOverview();
}

// ── Category filter ────────────────────────────────────────────────────────
function toggleCatFilter(catId){
  activeCatFilter=(activeCatFilter===catId)?null:catId;
  document.querySelectorAll('.leg-row[data-cat]').forEach(el=>{
    el.classList.toggle('muted',activeCatFilter!==null&&el.dataset.cat!==activeCatFilter);
  });
  _updateMarkers();   // 內部會同步重繪分類概況（含 active 樣式與圖上顆數）
}

// ── Panel tabs ─────────────────────────────────────────────────────────────
function switchPanelTab(tab){
  activePanelTab=tab;
  document.querySelectorAll('.ptab').forEach(el=>{
    el.classList.toggle('active',el.dataset.tab===tab);
  });
  const ctrl=document.getElementById('step-control');
  if(ctrl) ctrl.style.display=tab==='passes'?'flex':'none';
  if(tab==='overview') renderOverview();
  else renderPasses();
}

// ── Overview panel ─────────────────────────────────────────────────────────
function renderOverview(){
  const body=document.getElementById('panel-body');
  body.innerHTML='';
  if(!coverageData){body.innerHTML="<div class='pass-empty'>"+t('overview_loading')+"</div>";return;}
  Object.entries(CATS).forEach(([catId,cfg])=>{
    const cd=coverageData.categories[catId];
    if(!cd) return;
    // 圖上實繪數：與 _updateMarkers 相同邏輯推算，避免面板與地圖不同步
    const nAll=cd.count||0;
    const plotted=(catId in _plotted)?_plotted[catId]
                  :(nAll>300?cd.visible_count:nAll);
    const truncated=nAll>300;
    const filtered=activeCatFilter!==null&&activeCatFilter!==catId;
    const card=document.createElement('div');
    card.className='cat-card'+(activeCatFilter===catId?' active':'');
    card.dataset.cat=catId;
    card.innerHTML=
      "<div class='cat-header'><div class='cat-dot' style='background:"+cfg.color+"'></div>"
      +"<span class='cat-label'>"+t(cfg.labelKey)+"</span>"
      +"<span class='cat-cnt'>"+nAll+" "+t('unit_count')+"</span></div>"
      +"<div class='cat-sublabel'>"+t(cfg.subKey)+"</div>"
      +"<div class='cat-stats'>"
      +"<div class='cstat'><div class='sv' style='color:"+cfg.color+"'>"+nAll+"</div><div class='sl'>"+t('stat_db')+"</div></div>"
      +"<div class='cstat'><div class='sv' style='color:#4CAF50'>"+cd.visible_count+"</div><div class='sl'>"+t('stat_visible')+"</div></div>"
      +"<div class='cstat'><div class='sv' style='color:#FFD600'>"+plotted+"</div><div class='sl'>"+t('stat_plotted')+"</div></div>"
      +"</div>"
      +(filtered?"<div class='cat-note'>"+t('note_filtered')+"</div>"
        :(truncated?"<div class='cat-note'>"+t('note_truncated')+"</div>":""));
    card.addEventListener('click',()=>toggleCatFilter(catId));
    body.appendChild(card);
  });
}

// ── Pass panel ─────────────────────────────────────────────────────────────
function renderPasses(){
  const body=document.getElementById('panel-body');
  body.innerHTML='';
  if(!passesData){
    body.innerHTML="<div class='pass-empty'>"+t('passes_loading')+"</div>";
    return;
  }
  const catIds=activeCatFilter?[activeCatFilter]:Object.keys(CATS);
  catIds.forEach(catId=>{
    const cfg=CATS[catId];
    const cd=passesData.categories[catId];
    if(!cd) return;
    const hdr=document.createElement('div');
    hdr.className='pass-cat-hdr';
    hdr.innerHTML="<span style='width:8px;height:8px;border-radius:50%;background:"+cfg.color+";display:inline-block'></span>"+t(cfg.labelKey);
    body.appendChild(hdr);
    const passes=cd.passes||[];
    if(!passes.length){
      const e=document.createElement('div');
      e.className='pass-empty';
      e.textContent=t('passes_none');
      body.appendChild(e); return;
    }
    passes.slice(0,8).forEach(p=>{
      const item=document.createElement('div');
      item.className='pass-item';
      const rT=new Date(p.t_rise_utc);
      const elCol=p.max_el_deg>=45?'#4CAF50':p.max_el_deg>=20?'#FF9800':'#8b949e';
      const dm=Math.floor(p.duration_s/60), ds_=p.duration_s%60;
      const ts=new Date(rT.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(5,16);
      item.innerHTML=
        "<div class='pass-name'>"+p.name+"</div>"
        +"<div class='pass-row'>"
        +"<span class='pass-time'>&#8599; "+ts+" CST</span>"
        +"<span class='pass-el' style='color:"+elCol+"'>Max "+p.max_el_deg+"&deg;</span>"
        +"</div>"
        +"<div class='pass-dur'>"+tpl('pass_duration',{m:dm,s:ds_})+"</div>";
      body.appendChild(item);
    });
  });
}

// ── Status bar ─────────────────────────────────────────────────────────────
function _updateStatus(){
  if(!coverageData) return;
  let tot=0,vis=0,plot=0;
  Object.entries(coverageData.categories).forEach(([catId,c])=>{
    tot+=c.count||0;vis+=c.visible_count||0;
    plot+=(catId in _plotted)?_plotted[catId]
          :((c.count||0)>300?c.visible_count||0:c.count||0);
  });
  document.getElementById('st-total').textContent=tot;
  document.getElementById('st-visible').textContent=vis;
  const sp=document.getElementById('st-plotted');
  if(sp) sp.textContent=plot;
  const t=new Date(coverageData.timestamp);
  document.getElementById('st-time').textContent=
    new Date(t.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(11,19)+' CST';
}

// ── Timeline ───────────────────────────────────────────────────────────────
function _tlTs(){
  // Returns ISO string for current slider offset, or null if "now"
  if(Math.abs(_tlMin)<5) return null;
  return new Date(Date.now()+_tlMin*60*1000).toISOString();
}

function _tlUpdateDisplay(){
  const ts=new Date(Date.now()+_tlMin*60*1000);
  document.getElementById('tl-time').textContent=_cst(ts);
  const badge=document.getElementById('tl-badge');
  if(Math.abs(_tlMin)<5){
    badge.textContent=t('tl_badge_now'); badge.className='tl-badge now';
  } else if(_tlMin<0){
    badge.textContent=t('tl_badge_hist'); badge.className='tl-badge hist';
  } else {
    badge.textContent=t('tl_badge_future'); badge.className='tl-badge future';
  }
}

function tlSliderInput(v){
  // Live display update while dragging — no API call yet
  _tlMin=parseInt(v);
  _tlUpdateDisplay();
  clearTimeout(_tlDebounce);
}

function tlSliderChange(v){
  // Mouseup / touch end: trigger data load with 500ms debounce
  _tlMin=parseInt(v);
  _tlUpdateDisplay();
  clearTimeout(_tlDebounce);
  clearTimeout(_autoTimer);
  _tlDebounce=setTimeout(()=>_loadForTs(),500);
}

function jumpToNow(){
  const now=Date.now();
  if(now-_lastAction<1000) return;
  _lastAction=now;
  _tlMin=0;
  document.getElementById('tl-slider').value=0;
  _tlUpdateDisplay();
  clearTimeout(_tlDebounce);
  clearTimeout(_autoTimer);
  _loadForTs();
}

async function _loadForTs(){
  if(_loading){_pendingReload=true;return;}
  _loading=true;
  const ts=_tlTs();
  const ldEl=document.getElementById('tl-loading');
  if(ldEl) ldEl.textContent=t('panel_loading');
  try{
    await Promise.all([loadCoverage(ts), loadPasses(ts)]);
  }finally{
    _loading=false;
  }
  if(ldEl) ldEl.textContent='';
  if(_pendingReload){
    // 載入期間使用者又拉動了時間軸 → 立即以最新滑桿位置重載
    _pendingReload=false;
    _loadForTs();
    return;
  }
  // Schedule next auto-refresh only when at "now"
  if(!ts){
    clearTimeout(_autoTimer);
    _autoTimer=setTimeout(()=>_loadForTs(),60000);
  }
}

// ── Borders layer (2D) ─────────────────────────────────────────────────────
async function loadBorders(){
  try{
    const ds=await Cesium.GeoJsonDataSource.load('/api/layers/borders');
    // GeoJSON 多邊形在 Cesium 預設走 RHUMB 弧型細分，超大國界多邊形會觸發
    // 「RangeError: Too many properties to enumerate」並中止渲染。
    // 防護：多邊形一律轉為 GEODESIC 折線外框，並隱藏原多邊形（與 globe.js 同法）。
    const lineColor=Cesium.Color.fromCssColorString('#FFD600').withAlpha(0.7);
    [...ds.entities.values].forEach(ent=>{
      if(ent.polygon){
        const hier=ent.polygon.hierarchy&&ent.polygon.hierarchy.getValue(Cesium.JulianDate.now());
        if(hier&&hier.positions&&hier.positions.length){
          ds.entities.add({polyline:{
            positions:[...hier.positions,hier.positions[0]],
            width:1.5,
            material:new Cesium.ColorMaterialProperty(lineColor),
            arcType:Cesium.ArcType.GEODESIC,
          }});
        }
        ent.polygon.show=new Cesium.ConstantProperty(false);
      }
      if(ent.polyline&&ent.polyline.arcType===undefined){
        ent.polyline.arcType=Cesium.ArcType.GEODESIC;
      }
      if(ent.label) ent.label.show=new Cesium.ConstantProperty(false);
      if(ent.billboard) ent.billboard.show=new Cesium.ConstantProperty(false);
    });
    bordersDs=ds;
    await viewer.dataSources.add(ds);
  }catch(e){
    console.warn('Borders load failed',e);
  }
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init(){
  await initCesium();
  loadBorders();         // fire-and-forget
  _tlUpdateDisplay();    // init timeline display
  await loadCoverage();
  loadPasses();
  // Start 60-second auto-refresh for "now" mode
  _autoTimer=setTimeout(()=>_loadForTs(),60000);
}

window.tlSliderInput=tlSliderInput;
window.tlSliderChange=tlSliderChange;
window.jumpToNow=jumpToNow;

init().catch(e=>{
  document.getElementById('map-loading').textContent=tpl('init_fail',{msg:e.message});
  console.error(e);
});

window.switchPanelTab=switchPanelTab;
window.toggleCatFilter=toggleCatFilter;
window.refreshAll=refreshAll;

// 語言切換時重繪動態內容（分類概況／過頂預報／時間軸徽章／步長標籤）
_refreshUI=function(){
  const stepSlider=document.getElementById('step-slider');
  if(stepSlider) updateStepLabel(stepSlider.value);
  _tlUpdateDisplay();
  if(activePanelTab==='overview') renderOverview();
  else renderPasses();
};

// 天球／地圖檢視切換：地圖隱藏時暫停 Cesium 渲染，顯示時重設尺寸
window.taipeiMapVisible=function(v){
  if(!viewer) return;
  viewer.useDefaultRenderLoop=v;
  if(v) setTimeout(function(){viewer.resize();},0);
};

} // end startApp

// 頁面靜態文字（data-i18n）不需等待 Cesium/startApp() 即可套用已儲存的語言偏好
(function _applyInitialLang(){
  function _apply(){ setLang(LANG); }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',_apply);
  } else {
    _apply();
  }
})();
