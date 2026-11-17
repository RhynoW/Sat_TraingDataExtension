'use strict';

// ═══════════════════════════════════════════════════════════════════════════════
// 頂欄三語（中/英/日）— 僅涵蓋靜態 UI 文字，國家/用途/星座等動態分類內容維持中文
// ═══════════════════════════════════════════════════════════════════════════════
const GLOBE_I18N = {
  zh: {
    doc_title: '太空態勢儀表板 — 進階版 04-adv01（向量化 SGP4 + 近距離掃描 + 搜尋）',
    app_title: '太空態勢儀表板（進階版）',
    lbl_total: '追蹤物件', lbl_payload: '有效載荷', lbl_debris: '碎片', lbl_rocket: '火箭體',
    lbl_new: '近 1 年', lbl_conj: '近距離配對',
    tip_conj: '點選查看近距離配對清單',
    btn_track: 'NORAD 監測',
    tip_track: 'NORAD 監測（user_defined_tracking_NORAD 清單，可同時追蹤多顆衛星）',
    nav_taipei: '台北覆蓋分析', nav_starlink: 'Starlink 分析', nav_rpo: 'RPO功能測試',
    tip_rpo: '近距離配對相對接近 3D 場景 + Chan Pc（可切換兩顆衛星視角）',
    nav_story: 'StoryMap', tip_story: 'StoryMap 敘事頁：星系・機動・地基追蹤・碰撞預警整合展示',
    dbi_db: 'DB:', dbi_update: '更新：', dbi_valid: '有效衛星：', dbi_epoch: 'TLE 日期：', dbi_size: '大小：',
    search_placeholder: '搜尋 NORAD ID 或衛星名稱...',
    tab_country: '國家', tab_purpose: '用途', tab_era: '年代', tab_constellation: '星座',
    btn_back: '返回',
    loading_text: '正在初始化地球...',
    sec_basemap: '底圖', sec_layers: '向量圖層',
    chk_borders: '全球國界', chk_ssn: 'SSN 地面觀測站',
    btn_orbit6: '軌道六參數', tip_orbit6: '互動調整克卜勒軌道六參數，即時看軌道形狀變化（仿 AGI Orbit Tuner）',
    o6_title: '軌道六參數調整器',
    o6_presets: '預設案例',
    o6_preset_iss: 'ISS 國際太空站', o6_preset_gps: 'GPS 中軌', o6_preset_geo: '地球同步軌道', o6_preset_molniya: 'Molniya 大橢圓',
    o6_show: '顯示於地球', o6_focus: '視角對準',
    o6_stat_apogee: '遠地點高度', o6_stat_perigee: '近地點高度', o6_stat_period: '軌道週期',
    o6_min: '分鐘',
    o6_lbl_a: '半長軸 a', o6_lbl_e: '離心率 e', o6_lbl_i: '傾角 i',
    o6_lbl_raan: '升交點赤經 Ω', o6_lbl_argp: '近地點幅角 ω', o6_lbl_nu: '真近點角 ν',
    o6_help_a: '衛星橢圓軌道最長半徑，決定軌道大小與週期；數值越大，軌道越高、繞地球一圈時間越長。',
    o6_help_e: '軌道偏離正圓的程度，0＝正圓、越接近1＝越扁的橢圓；e 越大，近地點與遠地點高度差越懸殊。',
    o6_help_i: '軌道面與地球赤道面的夾角；0°＝赤道軌道，90°＝極軌，可決定衛星覆蓋的緯度範圍。',
    o6_help_raan: '軌道面與春分點方向的夾角，決定軌道面在慣性空間中朝哪個方向展開（軌道「面朝哪」）。',
    o6_help_argp: '近地點在軌道面內、相對升交點的角度，決定橢圓軌道最近點朝向地球的哪個方位。',
    o6_help_nu: '衛星目前在軌道上的位置角度（相對近地點量測），拖動可模擬衛星沿軌道移動。',
    o6_connect_title: 'STK Connect 指令',
    o6_connect_hint: '對應目前六參數自動產生，可直接貼到 STK Connect 主控台執行',
    o6_connect_sat: '衛星物件名稱',
    o6_connect_copy: '複製指令', o6_connect_copied: '已複製！',
    o6_connect_now: '使用目前 UTC 時間',
    o6_about: 'ℹ️ 關於此功能',
  },
  en: {
    doc_title: 'Space Situational Awareness Dashboard — Advanced 04-adv01 (Vectorized SGP4 + Proximity Scan + Search)',
    app_title: 'Space Situational Awareness Dashboard (Advanced)',
    lbl_total: 'Tracked Objects', lbl_payload: 'Payloads', lbl_debris: 'Debris', lbl_rocket: 'Rocket Bodies',
    lbl_new: '< 1 Year', lbl_conj: 'Close-Approach Pairs',
    tip_conj: 'Click to view the close-approach pair list',
    btn_track: 'NORAD Tracking',
    tip_track: 'NORAD Tracking (user_defined_tracking_NORAD list; multiple satellites can be tracked simultaneously)',
    nav_taipei: 'Taipei Coverage Analysis', nav_starlink: 'Starlink Analysis', nav_rpo: 'RPO Feature Test',
    tip_rpo: '3D relative-approach scene for close-approach pairs + Chan Pc (switchable dual-satellite viewpoint)',
    nav_story: 'StoryMap', tip_story: 'StoryMap narrative pages: constellations, maneuvers, ground tracking and conjunction warning',
    dbi_db: 'DB:', dbi_update: 'Updated:', dbi_valid: 'Valid Satellites:', dbi_epoch: 'TLE Epoch:', dbi_size: 'Size:',
    search_placeholder: 'Search NORAD ID or satellite name...',
    tab_country: 'Country', tab_purpose: 'Purpose', tab_era: 'Era', tab_constellation: 'Constellation',
    btn_back: 'Back',
    loading_text: 'Initializing globe...',
    sec_basemap: 'Basemap', sec_layers: 'Vector Layers',
    chk_borders: 'Global Borders', chk_ssn: 'SSN Ground Stations',
    btn_orbit6: 'Orbit Tuner', tip_orbit6: 'Interactively adjust the six classical Keplerian elements and see the orbit shape change in real time (inspired by AGI Orbit Tuner)',
    o6_title: 'Classical Orbital Elements Tuner',
    o6_presets: 'Presets',
    o6_preset_iss: 'ISS', o6_preset_gps: 'GPS (MEO)', o6_preset_geo: 'Geostationary', o6_preset_molniya: 'Molniya (HEO)',
    o6_show: 'Show on Globe', o6_focus: 'Look At Orbit',
    o6_stat_apogee: 'Apogee Altitude', o6_stat_perigee: 'Perigee Altitude', o6_stat_period: 'Orbital Period',
    o6_min: 'min',
    o6_lbl_a: 'Semi-major Axis a', o6_lbl_e: 'Eccentricity e', o6_lbl_i: 'Inclination i',
    o6_lbl_raan: 'RAAN Ω', o6_lbl_argp: 'Argument of Perigee ω', o6_lbl_nu: 'True Anomaly ν',
    o6_help_a: 'Half of the longest diameter of the elliptical orbit; determines orbit size and period — larger means a higher, slower orbit.',
    o6_help_e: 'How much the orbit deviates from a perfect circle. 0 = circular, closer to 1 = more elongated ellipse; larger e means a bigger gap between perigee and apogee altitude.',
    o6_help_i: 'The angle between the orbital plane and Earth\'s equatorial plane. 0° = equatorial orbit, 90° = polar orbit; determines the latitude range the satellite can cover.',
    o6_help_raan: 'The angle between the orbital plane and the vernal equinox direction; determines which way the orbital plane faces in inertial space.',
    o6_help_argp: 'The angle, measured within the orbital plane, from the ascending node to perigee; determines which side of Earth the closest point of the ellipse faces.',
    o6_help_nu: 'The satellite\'s current position angle along the orbit, measured from perigee; drag it to simulate the satellite moving along its orbit.',
    o6_connect_title: 'STK Connect Command',
    o6_connect_hint: 'Auto-generated from the current six elements — paste directly into the STK Connect console',
    o6_connect_sat: 'Satellite Object Name',
    o6_connect_copy: 'Copy Command', o6_connect_copied: 'Copied!',
    o6_connect_now: 'Use Current UTC Time',
    o6_about: 'ℹ️ About This Feature',
  },
  ja: {
    doc_title: 'スペース・シチュエーショナル・アウェアネス・ダッシュボード — 進化版 04-adv01（ベクトル化SGP4＋近接スキャン＋検索）',
    app_title: 'スペース・シチュエーショナル・アウェアネス・ダッシュボード（進化版）',
    lbl_total: '追跡オブジェクト', lbl_payload: 'ペイロード', lbl_debris: 'デブリ', lbl_rocket: 'ロケット本体',
    lbl_new: '1年未満', lbl_conj: '近接ペア',
    tip_conj: 'クリックして近接ペア一覧を表示',
    btn_track: 'NORAD 監視',
    tip_track: 'NORAD監視（user_defined_tracking_NORADリスト、複数衛星を同時追跡可能）',
    nav_taipei: '台北カバレッジ分析', nav_starlink: 'Starlink 分析', nav_rpo: 'RPO機能テスト',
    tip_rpo: '近接ペアの相対接近3Dシーン＋Chan Pc（2衛星視点切替可能）',
    nav_story: 'StoryMap', tip_story: 'StoryMap ナラティブページ：星系・マヌーバ・地上追跡・衝突警報の統合展示',
    dbi_db: 'DB:', dbi_update: '更新：', dbi_valid: '有効衛星：', dbi_epoch: 'TLE日付：', dbi_size: 'サイズ：',
    search_placeholder: 'NORAD IDまたは衛星名で検索...',
    tab_country: '国', tab_purpose: '用途', tab_era: '年代', tab_constellation: 'コンステレーション',
    btn_back: '戻る',
    loading_text: '地球を初期化中...',
    sec_basemap: 'ベースマップ', sec_layers: 'ベクターレイヤー',
    chk_borders: '世界の国境', chk_ssn: 'SSN地上観測局',
    btn_orbit6: '軌道六要素', tip_orbit6: '古典軌道六要素をインタラクティブに調整し、軌道形状の変化をリアルタイムに確認（AGI Orbit Tuner ライク）',
    o6_title: '軌道六要素チューナー',
    o6_presets: 'プリセット',
    o6_preset_iss: 'ISS 国際宇宙ステーション', o6_preset_gps: 'GPS（中軌道）', o6_preset_geo: '静止軌道', o6_preset_molniya: 'モルニヤ軌道（大楕円）',
    o6_show: '地球儀に表示', o6_focus: '視点を合わせる',
    o6_stat_apogee: '遠地点高度', o6_stat_perigee: '近地点高度', o6_stat_period: '公転周期',
    o6_min: '分',
    o6_lbl_a: '軌道長半径 a', o6_lbl_e: '離心率 e', o6_lbl_i: '軌道傾斜角 i',
    o6_lbl_raan: '昇交点赤経 Ω', o6_lbl_argp: '近地点引数 ω', o6_lbl_nu: '真近点角 ν',
    o6_help_a: '楕円軌道の最長半径。軌道の大きさと周期を決める。値が大きいほど軌道は高く、公転周期は長くなる。',
    o6_help_e: '軌道が正円からどれだけ外れているかを示す指標。0＝正円、1に近いほど扁平な楕円になり、近地点と遠地点の高度差が大きくなる。',
    o6_help_i: '軌道面と地球赤道面のなす角。0°＝赤道軌道、90°＝極軌道。衛星がカバーできる緯度範囲を決める。',
    o6_help_raan: '軌道面と春分点方向のなす角。軌道面が慣性空間内でどちらを向いているかを決める。',
    o6_help_argp: '昇交点から近地点までを軌道面内で測った角度。楕円軌道の最も低い点が地球のどちら側を向くかを決める。',
    o6_help_nu: '衛星が軌道上で現在どこにいるかを示す角度（近地点からの角度）。動かすと軌道上を移動する様子を模擬できる。',
    o6_connect_title: 'STK Connect コマンド',
    o6_connect_hint: '現在の六要素から自動生成。STK Connect コンソールに直接貼り付け可能',
    o6_connect_sat: '衛星オブジェクト名',
    o6_connect_copy: 'コマンドをコピー', o6_connect_copied: 'コピーしました！',
    o6_connect_now: '現在のUTC時刻を使用',
    o6_about: 'ℹ️ この機能について',
  },
};
const GLOBE_LOCALE_MAP = {zh:'zh-TW', en:'en-US', ja:'ja-JP'};
let GLOBE_LANG = localStorage.getItem('starlink_lang') || 'zh';
if(!GLOBE_I18N[GLOBE_LANG]) GLOBE_LANG = 'zh';

function t(key){
  const d = GLOBE_I18N[GLOBE_LANG] || GLOBE_I18N.zh;
  return (key in d) ? d[key] : (GLOBE_I18N.zh[key] !== undefined ? GLOBE_I18N.zh[key] : key);
}
function setLang(lang){
  if(!GLOBE_I18N[lang]) return;
  GLOBE_LANG = lang;
  localStorage.setItem('starlink_lang', lang);
  document.documentElement.lang = GLOBE_LOCALE_MAP[lang] || 'zh-TW';
  document.title = t('doc_title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.getAttribute('data-i18n-title')); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.getAttribute('data-i18n-placeholder')); });
  document.querySelectorAll('.lang-btn').forEach(b => { b.classList.toggle('active', b.dataset.lang === lang); });
}
document.addEventListener('DOMContentLoaded', () => setLang(GLOBE_LANG));
window.setLang = setLang;
window.t = t;
window.getGlobeLang = () => GLOBE_LANG;

function startApp(){

let viewer=null, satDs=null; let orbitEnts=[];
let statsData=null, conjData=null;
let activeTab='country', activeFtype=null, activeFval=null;
let panelMode='tabs';
const entMap=new Map();
let _statsPayload=null;

// 單顆／多顆手動選取（flyToSat／showMultiSats，多為 URL 帶 norad 參數）之週期性位置更新：
// 這兩個路徑先前僅在載入當下取一次靜態位置，此後不會隨時間推移而移動；
// 與大量篩選瀏覽（renderEntities，可能上萬顆）共用同一 entMap 但走各自獨立的更新節奏，
// 避免對大量衛星逐顆呼叫 /api/position/<norad>（那條路徑已有自己的批次自適應更新機制）。
let _selRefreshTimer=null;
let _selNorads=[];
const SEL_REFRESH_MS=10000;
function _stopSelRefresh(){
  if(_selRefreshTimer){ clearInterval(_selRefreshTimer); _selRefreshTimer=null; }
  _selNorads=[];
}
function _startSelRefresh(norads){
  _stopSelRefresh();
  _selNorads=(norads||[]).slice();
  if(!_selNorads.length) return;
  _selRefreshTimer=setInterval(_refreshSelPositions,SEL_REFRESH_MS);
}
async function _refreshSelPositions(){
  if(!_selNorads.length) return;
  await Promise.all(_selNorads.map(async nid=>{
    const ent=entMap.get(nid);
    if(!ent) return;   // 已被其他操作（如切換篩選）清除，略過
    try{
      const r=await fetch('/api/position/'+nid);
      if(!r.ok) return;
      const d=await r.json();
      if(d.error||d.lat==null) return;
      ent.position=Cesium.Cartesian3.fromDegrees(d.lon,d.lat,d.alt_km*1000);
    }catch(e){}
  }));
}
const _payloadOnly={};
const PAYLOAD_TABS=new Set(['country','era','constellation']);
let borderDs=null, ssnDs=null;
let _searchTimer=null;
let _filterRefreshTimer=null;
let _filterTotal=0;       // 篩選群組伺服器端總匹配數（供伺服器負載下限計算）
let _filterRefreshGen=0;  // 每次 _startFilterRefresh 遞增；防止舊迴圈繼續執行
let _currentRefreshMode=null;  // 'fast'|'slow'|null；camera moveEnd 偵測慢→快切換
let _camSettleTimer=null;      // camera.changed debounce 計時器

const SSN_TYPE_COLORS={
  '光學/電光':'#FFC107','雷達':'#00E5FF','飛彈預警/協作':'#FF7043',
  '衛星追控':'#66BB6A','數據中心':'#CE93D8','已除役':'#78909C',
};
const PURPOSE_C  ={有效載荷:'#4CAF50',碎片:'#FF9800',火箭體:'#9E9E9E',不明物體:'#607D8B'};
const COUNTRY_C  ={美國:'#3F51B5','俄羅斯/蘇聯':'#F44336',中國:'#FF5722',英國:'#2196F3',
                   法國:'#9C27B0',日本:'#E91E63',印度:'#FF9800',ESA:'#00BCD4',
                   台灣:'#00ACC1',韓國:'#FF6F00',以色列:'#5C6BC0',澳洲:'#2E7D32',
                   盧森堡:'#F57F17',其他:'#78909C',不明:'#455A64'};
const CONSTEL_C  ={Starlink:'#1565C0',OneWeb:'#00897B',Kuiper:'#FF8F00',
                   '國網/Guowang':'#D32F2F','中國IoT(天啟/行雲)':'#8D6E63',
                   'Planet/Flock':'#2E7D32','千帆/Qianfan':'#C62828',
                   Spire:'#00838F',Iridium:'#558B2F',
                   'PWSA/SDA':'#5D4037',Starshield:'#455A64',
                   'GeeSat/Geespace':'#6A1B9A',Globalstar:'#4527A0',
                   Hawk:'#E65100',Orbcomm:'#37474F',
                   NuSat:'#00695C',Skykraft:'#1565C0',
                   SpaceMobile:'#0277BD',Lynk:'#558B2F',
                   'Telesat LEO':'#4A148C','吉林/Jilin':'#AD1457',
                   'Formosat-7':'#00ACC1',
                   '遙感/Yaogan':'#B71C1C',高分:'#E64A19',風雲:'#0277BD',其他衛星:'#546E7A'};
const ERA_C      ={'< 1 年':'#F44336','1–5 年':'#FF9800','5–10 年':'#4CAF50',
                   '> 10 年':'#607D8B',不明:'#455A64'};

function getColor(ftype,label){
  const m={country:COUNTRY_C,purpose:PURPOSE_C,era:ERA_C,constellation:CONSTEL_C};
  return (m[ftype]||{})[label]||'#78909C';
}

async function initCesium(){
  Cesium.Ion.defaultAccessToken='';
  try{ Cesium.IonResource.fromAssetId=function(){return Promise.reject(new Error('Ion disabled'));}; }catch(e){}
  const opts={
    animation:false, timeline:false, baseLayerPicker:false,
    imageryProvider:new Cesium.SingleTileImageryProvider({
      url:'/api/globe_texture/default',
      rectangle:Cesium.Rectangle.fromDegrees(-180,-90,180,90),
      credit:'NASA Blue Marble © NASA Earth Observatory',
    }),
    terrainProvider:new Cesium.EllipsoidTerrainProvider(),
    sceneModePicker:true, infoBox:true, geocoder:false,
    homeButton:true, navigationHelpButton:false, selectionIndicator:true,
  };
  viewer=new Cesium.Viewer('cesiumContainer',opts);
  window.__cesiumViewer=viewer; // 供 orbit6_tuner.js 等外部模組疊加繪製使用
  viewer.cesiumWidget.creditContainer.style.display='none';
  _bindInfoBoxLinks();
  viewer.scene.globe.enableLighting=true;
  viewer.scene.globe.depthTestAgainstTerrain=false;
  satDs=new Cesium.CustomDataSource('satellites');
  await viewer.dataSources.add(satDs);
  viewer.camera.percentageChanged=0.05;  // 預設 0.5 太鈍，縮放一格常不觸發 changed
  viewer.camera.moveEnd.addEventListener(_onCameraMoveEnd);
  viewer.camera.changed.addEventListener(_onCameraChanged);

  viewer.selectedEntityChanged.addEventListener(ent=>{
    _clearOrbit();
    const _sdp=document.getElementById('sat-detail-panel');
    if(!ent||!ent.id){if(_sdp)_sdp.style.display='none';return;}
    const m=ent.id.match(/^sat_(\d+)$/);
    if(!m){if(_sdp)_sdp.style.display='none';return;}
    const nid=parseInt(m[1]);
    let hexColor='#58a6ff';
    try{
      if(ent.point&&ent.point.color){
        const c=ent.point.color.getValue(Cesium.JulianDate.now());
        if(c) hexColor=colorToHex(c);
      }
    }catch(e){}
    showOrbitArc(nid,hexColor);
    fetchSatDetail(nid);
  });

  document.getElementById('loading').style.display='none';
  initBasemapBar();
}

async function loadBordersLayer(){
  try{
    const ds=await Cesium.GeoJsonDataSource.load('/api/layers/borders');
    const lineColor=Cesium.Color.fromCssColorString('#FFD600').withAlpha(0.85);
    [...ds.entities.values].forEach(ent=>{
      if(ent.polygon){
        const hier=ent.polygon.hierarchy&&ent.polygon.hierarchy.getValue(Cesium.JulianDate.now());
        if(hier&&hier.positions&&hier.positions.length){
          ds.entities.add({polyline:{
            positions:[...hier.positions,hier.positions[0]],
            width:1.5, clampToGround:true,
            material:new Cesium.ColorMaterialProperty(lineColor),
            arcType:Cesium.ArcType.GEODESIC,
          }});
        }
        ent.polygon.show=new Cesium.ConstantProperty(false);
      }
      if(ent.label) ent.label.show=new Cesium.ConstantProperty(false);
    });
    borderDs=ds;
    await viewer.dataSources.add(ds);
  }catch(e){
    console.warn('全球國界載入失敗',e);
    const chk=document.getElementById('chk-borders');
    if(chk) chk.checked=false;
  }
}

// ── 使用者自訂 GeoJSON 圖層（scenario04/geojson/*.geojson，放檔案即載入）────
const userGeoLayers={};   // name -> {ds, color}
const USER_GEO_COLORS=['#FFD600','#FF8A65','#4FC3F7','#69F0AE','#B388FF','#F48FB1','#80DEEA'];

const USER_GEO_LABELS=[
  [/taiwan-admin/i,        '台灣行政區界（精細）'],
  [/submarine|cable/i,     '海底電纜'],
  [/airport|openflights/i, '全球機場'],
];

function _userGeoLabel(name){
  for(const [re,label] of USER_GEO_LABELS){ if(re.test(name)) return label; }
  return name.replace(/\.geojson$/i,'');
}

function _featColor(ent,fallback){
  // feature 自帶 color 屬性（如海底電纜官方配色）優先
  try{
    const p=ent.properties&&ent.properties.color;
    if(p){
      const v=p.getValue(Cesium.JulianDate.now());
      if(typeof v==='string'&&/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v.trim())) return v.trim();
    }
  }catch(e){}
  return fallback;
}

function _styleGeoDs(ds,colorCss){
  // 與全球國界一致：多邊形改畫外框折線（貼地），隱藏填色；線/點配層色或 feature 色
  [...ds.entities.values].forEach(ent=>{
    const col=Cesium.Color.fromCssColorString(_featColor(ent,colorCss)).withAlpha(0.9);
    if(ent.polygon){
      const hier=ent.polygon.hierarchy&&ent.polygon.hierarchy.getValue(Cesium.JulianDate.now());
      if(hier&&hier.positions&&hier.positions.length){
        ds.entities.add({polyline:{
          positions:[...hier.positions,hier.positions[0]],
          width:1.5, clampToGround:true,
          material:new Cesium.ColorMaterialProperty(col),
          arcType:Cesium.ArcType.GEODESIC,
        }});
      }
      ent.polygon.show=new Cesium.ConstantProperty(false);
    }
    if(ent.polyline){
      ent.polyline.material=new Cesium.ColorMaterialProperty(col);
      ent.polyline.width=1.5;
      ent.polyline.clampToGround=true;
    }
    if(ent.billboard){
      ent.billboard=undefined;
      ent.point=new Cesium.PointGraphics({pixelSize:5,color:col,
        outlineColor:Cesium.Color.BLACK,outlineWidth:1,
        scaleByDistance:new Cesium.NearFarScalar(5e5,1.2,2e7,0.5)});
    }
    if(ent.label) ent.label.show=new Cesium.ConstantProperty(false);
  });
}

async function _loadUserGeoDs(name,color){
  const ds=await Cesium.GeoJsonDataSource.load(
    '/api/layers/user_geojson/'+encodeURIComponent(name));
  _styleGeoDs(ds,color);
  await viewer.dataSources.add(ds);
  return ds;
}

function toggleUserGeo(name,cb){
  const layer=userGeoLayers[name];
  if(!layer) return;
  if(layer.ds){ layer.ds.show=cb.checked; return; }
  if(cb.checked){
    _loadUserGeoDs(name,layer.color)
      .then(ds=>{ layer.ds=ds; })
      .catch(e=>{ console.warn('使用者圖層載入失敗 '+name,e); cb.checked=false; });
  }
}

async function loadUserGeojsonLayers(){
  let files=[];
  try{
    const r=await fetch('/api/layers/user_geojson');
    if(!r.ok) return;
    files=await r.json();
  }catch(e){ console.warn('使用者圖層清單載入失敗',e); return; }
  if(!files.length) return;
  const bar=document.getElementById('layer-bar');
  const AUTO_LOAD_MAX_FEATURES=3000, AUTO_LOAD_MAX_KB=4096;
  files.forEach((f,i)=>{
    const color=USER_GEO_COLORS[i%USER_GEO_COLORS.length];
    userGeoLayers[f.name]={ds:null,color:color};
    // 大型圖層（如全球機場 7,698 點）預設不自動載入，勾選時才載
    const heavy=(f.features!=null&&f.features>AUTO_LOAD_MAX_FEATURES)||f.size_kb>AUTO_LOAD_MAX_KB;
    const label=document.createElement('label');
    const cb=document.createElement('input');
    cb.type='checkbox';
    cb.disabled=!!f.error;
    cb.addEventListener('change',()=>toggleUserGeo(f.name,cb));
    const dot=document.createElement('span');
    dot.style.cssText='width:9px;height:9px;border-radius:50%;display:inline-block;flex-shrink:0;background:'+color;
    const txt=document.createElement('span');
    txt.textContent=_userGeoLabel(f.name)+(f.error?'（格式錯誤）':'');
    txt.title=f.name+' · '+f.size_kb+' KB'+(f.features!=null?' · '+f.features+' features':'')
      +(f.error?(' · '+f.error):'')+(heavy?' · 大型圖層，勾選後載入':'');
    label.appendChild(cb); label.appendChild(dot); label.appendChild(txt);
    bar.appendChild(label);
    const skipAuto=/submarine|cable/i.test(f.name);  // 海底電纜預設不自動載入
    if(!f.error&&!heavy&&!skipAuto){ cb.checked=true; toggleUserGeo(f.name,cb); }
  });
}

async function loadStats(){
  try{
    const [r1,r2]=await Promise.all([
      fetch('/api/stats'),
      fetch('/api/stats?payload_only=1'),
    ]);
    if(!r1.ok) throw new Error('HTTP '+r1.status);
    statsData=await r1.json();
    if(r2.ok) _statsPayload=await r2.json();
    renderTopCards();
    renderPanel(activeTab);
    const ts=new Date(statsData.updated_at);
    document.getElementById('ts').textContent=ts.toISOString().replace('T',' ').slice(0,19)+' UTC';
  }catch(e){
    document.getElementById('filter-status').textContent='統計載入失敗: '+e.message;
  }
}

function renderTopCards(){
  if(!statsData) return;
  document.getElementById('c-total').textContent=statsData.total.toLocaleString();
  const pmap={};
  statsData.purpose.forEach(p=>pmap[p.label]=p.count);
  document.getElementById('c-payload').textContent=(pmap['有效載荷']||0).toLocaleString();
  document.getElementById('c-debris') .textContent=(pmap['碎片']    ||0).toLocaleString();
  document.getElementById('c-rocket') .textContent=(pmap['火箭體']  ||0).toLocaleString();
  const emap={};
  statsData.era.forEach(e=>emap[e.label]=e.count);
  document.getElementById('c-new').textContent=(emap['< 1 年']||0).toLocaleString();
}

function setPanelMode(mode){
  panelMode=mode;
  const showTabs=(mode==='tabs');
  document.getElementById('tabs').style.display=showTabs?'flex':'none';
  document.getElementById('panel-back').style.display=showTabs?'none':'block';
  if(showTabs) renderPanel(activeTab);
}

function backToTabs(){
  document.getElementById('conj-card').classList.remove('active-card');
  const tb=document.getElementById('track-btn');
  if(tb) tb.classList.remove('active');
  const ob=document.getElementById('orbit6-btn');
  if(ob) ob.classList.remove('active');
  if(window.OrbitTuner) window.OrbitTuner.clear();
  setPanelMode('tabs');
}

function toggleOrbit6Panel(){
  const btn=document.getElementById('orbit6-btn');
  if(panelMode==='orbit6'){
    btn.classList.remove('active');
    if(window.OrbitTuner) window.OrbitTuner.clear();
    setPanelMode('tabs');
    return;
  }
  document.getElementById('conj-card').classList.remove('active-card');
  const tb=document.getElementById('track-btn');
  if(tb) tb.classList.remove('active');
  btn.classList.add('active');
  clearSearchUI();
  setPanelMode('orbit6');
  if(window.OrbitTuner) window.OrbitTuner.render(document.getElementById('panel-body'));
}

function switchTab(tab){
  const alreadyActive=(activeTab===tab&&panelMode==='tabs');
  if(alreadyActive&&PAYLOAD_TABS.has(tab)){
    _payloadOnly[tab]=!_payloadOnly[tab];
  }else{
    activeTab=tab;
    if(panelMode!=='tabs') setPanelMode('tabs');
  }
  document.querySelectorAll('.tab').forEach(t=>{
    const isThis=t.dataset.tab===tab;
    t.classList.toggle('active',t.dataset.tab===activeTab);
    if(isThis&&PAYLOAD_TABS.has(tab)){
      t.classList.toggle('payload-mode',!!_payloadOnly[tab]);
      t.title=_payloadOnly[tab]?'僅有效載荷（再點切回全部）':'點選再次切換為僅顯示有效載荷';
    }
  });
  renderPanel(tab);
}

function renderPanel(tab){
  if(!statsData||panelMode!=='tabs') return;
  const usePayload=PAYLOAD_TABS.has(tab)&&_payloadOnly[tab]&&_statsPayload;
  const data=usePayload?_statsPayload:statsData;
  const body=document.getElementById('panel-body');
  body.innerHTML='';
  if(usePayload){
    const note=document.createElement('div');
    note.style.cssText='padding:3px 12px 2px;font-size:10px;color:#4CAF50;flex-shrink:0';
    note.textContent='▶ 僅有效載荷（不含碎片／火箭體）';
    body.appendChild(note);
  }
  const rows=data[tab]||[];
  const maxCount=rows.length?rows[0].count:1;
  rows.forEach(row=>{
    const isActive=(activeFtype===tab&&activeFval===row.label);
    const color=getColor(tab,row.label);
    const pct=Math.round(row.count/maxCount*100);
    const btn=document.createElement('button');
    btn.className='stat-row'+(isActive?' active':'');
    btn.innerHTML=
      '<span class="stat-dot" style="background:'+color+'"></span>'+
      '<span class="stat-label" title="'+row.label+'">'+row.label+'</span>'+
      '<span class="stat-cnt">'+row.count.toLocaleString()+'</span>';
    btn.addEventListener('click',()=>filterGlobe(tab,row.label,color));
    const barWrap=document.createElement('div');
    barWrap.style.cssText='padding:0 12px 3px 27px;width:100%';
    barWrap.innerHTML='<div class="stat-bar-wrap"><div class="stat-bar" style="width:'+pct+'%;background:'+color+'"></div></div>';
    const wrap=document.createElement('div');
    wrap.appendChild(btn); wrap.appendChild(barWrap);
    body.appendChild(wrap);
  });
}

// ── 即時位置自動更新 ─────────────────────────────────────────────────────────
// 使用輕量端點 /api/positions/coords（只回傳 lat/lon/alt），就地更新 entity
// 位置，避免清除/重建 entity 造成閃爍。

function _stopFilterRefresh(){
  if(_filterRefreshTimer){ clearTimeout(_filterRefreshTimer); _filterRefreshTimer=null; }
  _currentRefreshMode=null;
}

// 回傳目前 Cesium 可視截錐內的衛星 NORAD ID 陣列
function _getVisibleNorads(){
  if(!viewer||!entMap.size) return[];
  try{
    const cam=viewer.scene.camera;
    const cv=cam.frustum.computeCullingVolume(cam.position,cam.direction,cam.up);
    const occ=new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84,cam.position);
    const nids=[];
    for(const [nid,ent] of entMap){
      const pos=ent.position&&ent.position.getValue(Cesium.JulianDate.now());
      if(pos
        &&cv.computeVisibility(new Cesium.BoundingSphere(pos,1e5))!==Cesium.Intersect.OUTSIDE
        &&occ.isPointVisible(pos)) nids.push(nid);
    }
    return nids;
  }catch(e){ return[]; }
}
// 可視衛星數（快捷包裝，舊介面保持相容）
function _countVisibleSats(){ return _getVisibleNorads().length; }

// 更新間隔：可視衛星數決定 UX 頻率；載入總數設定伺服器保護下限
function _getRefreshMs(total,visible){
  const serverMin=total>3000?10000:total>300?2000:0;
  const ms=visible>3000?60000:visible>100?20000:1000;
  return Math.max(ms,serverMin);
}

// 兩段式自動更新：
//   快速模式（≤100 顆可見）→ POST /api/positions/active → 1 s，直接 SGP4 少量衛星（<5 ms）
//   慢速模式（>100 顆可見）→ GET  /api/positions/coords → 讀背景快取，20～60 s
function _startFilterRefresh(total){
  _stopFilterRefresh();
  if(!activeFtype||!activeFval) return;
  _filterTotal=total;
  const gen=++_filterRefreshGen;
  (function _loop(){
    if(gen!==_filterRefreshGen||!activeFtype||!activeFval) return;
    const visNids=_getVisibleNorads();
    const visible=visNids.length;
    if(visible>0&&visible<=100){
      // ── 快速模式：1 s ──────────────────────────────────────────────────
      _currentRefreshMode='fast';
      _filterRefreshTimer=setTimeout(async()=>{
        const freshNids=_getVisibleNorads();   // timer 期間 camera 可能移動，重新取
        if(freshNids.length>0&&freshNids.length<=100){
          await _refreshActiveSet(freshNids);
        }else{
          await _refreshFilterPositions();     // 模式切換：改走慢速路徑
        }
        _loop();
      },1000);
    }else{
      // ── 慢速模式：從背景快取讀，依可視數決定間隔 ───────────────────────
      _currentRefreshMode='slow';
      const ms=_getRefreshMs(_filterTotal,visible);
      _filterRefreshTimer=setTimeout(async()=>{
        await _refreshFilterPositions();
        _loop();
      },ms);
    }
  })();
}

// 快速模式：只對指定 NORAD ID 列表做即時 SGP4（POST /api/positions/active）
async function _refreshActiveSet(nids){
  if(!activeFtype||!activeFval||!nids.length) return;
  try{
    const payloadParam=(_payloadOnly[activeFtype]&&PAYLOAD_TABS.has(activeFtype))?1:0;
    const r=await fetch('/api/positions/active',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({norad_ids:nids,payload_only:payloadParam}),
    });
    if(!r.ok) return;
    const d=await r.json();
    _updateEntityPositions(d.satellites||[]);
    const timeStr=new Date().toISOString().slice(11,19)+' UTC';
    document.getElementById('filter-status').textContent=
      '顯示 '+entMap.size+' 顆 — '+activeFval
      +' ｜ ↻ '+timeStr+'（畫面 '+nids.length+' 顆 ⚡ 1 s 快速模式）';
  }catch(e){
    console.warn('快速位置更新失敗',e);
  }
}

function _updateEntityPositions(sats){
  sats.forEach(s=>{
    const ent=entMap.get(s.norad_id);
    if(!ent) return;
    ent.position=Cesium.Cartesian3.fromDegrees(s.lon,s.lat,s.alt_km*1000);
  });
}

async function _refreshFilterPositions(){
  if(!activeFtype||!activeFval) return;
  const payloadParam=(_payloadOnly[activeFtype]&&PAYLOAD_TABS.has(activeFtype))?'&payload_only=1':'';
  try{
    const url='/api/positions/coords?ftype='+encodeURIComponent(activeFtype)
      +'&fval='+encodeURIComponent(activeFval)+payloadParam;
    const r=await fetch(url);
    if(!r.ok) return;
    const d=await r.json();
    _updateEntityPositions(d.satellites||[]);
    const visible=_countVisibleSats();
    const nextMs=_getRefreshMs(_filterTotal,visible);
    const timeStr=new Date().toISOString().slice(11,19)+' UTC';
    document.getElementById('filter-status').textContent=
      '顯示 '+entMap.size+' 顆 — '+activeFval
      +' ｜ ↻ '+timeStr+'（畫面 '+visible+' / 每 '+Math.round(nextMs/1000)+' s）';
  }catch(e){
    console.warn('位置自動更新失敗',e);
  }
}

// camera 停止移動後，若處於慢速模式且可視衛星 ≤100 顆，立刻重啟為快速模式
function _onCameraMoveEnd(){
  if(_currentRefreshMode!=='slow'||!activeFtype||!activeFval) return;
  const visible=_countVisibleSats();
  if(visible>0&&visible<=100) _startFilterRefresh(_filterTotal);
}
// camera.changed 在移動過程連續觸發；300ms 無新事件才視為停止，避免高頻觸發 _onCameraMoveEnd
function _onCameraChanged(){
  if(_camSettleTimer) clearTimeout(_camSettleTimer);
  _camSettleTimer=setTimeout(_onCameraMoveEnd,300);
}

async function filterGlobe(ftype,fval,color){
  if(activeFtype===ftype&&activeFval===fval){
    _stopFilterRefresh();
    activeFtype=activeFval=null;
    _clearOrbit();
    satDs.entities.removeAll(); entMap.clear();
    document.getElementById('filter-status').textContent='已清除篩選';
    renderPanel(activeTab);
    return;
  }
  _stopFilterRefresh();
  activeFtype=ftype; activeFval=fval;
  renderPanel(activeTab);
  document.getElementById('filter-status').textContent='載入中：'+fval+' …';
  try{
    const payloadParam=(_payloadOnly[ftype]&&PAYLOAD_TABS.has(ftype))?'&payload_only=1':'';
    const url='/api/positions?ftype='+encodeURIComponent(ftype)+'&fval='+encodeURIComponent(fval)+payloadParam;
    const r=await fetch(url);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    renderEntities(d.satellites,ftype);
    const vflag=d.vectorized?'，向量化':'';
    const elapsed=d.elapsed_sec?'（'+d.elapsed_sec+' s'+vflag+'）':'';
    _startFilterRefresh(d.total_matched);
    const initVisible=_countVisibleSats();
    const initMode=initVisible>0&&initVisible<=100
      ?'⚡ 1 s 快速模式'
      :'每 '+Math.round(_getRefreshMs(d.total_matched,initVisible)/1000)+' s 慢速模式（快取）';
    document.getElementById('filter-status').textContent=
      '顯示 '+d.count+' / '+d.total_matched+' 顆'+elapsed+' — '+fval
      +' ｜ 畫面 '+initVisible+' 顆 / '+initMode;
  }catch(e){
    document.getElementById('filter-status').textContent='載入失敗: '+e.message;
  }
}

function renderEntities(sats,ftype){
  _stopSelRefresh();
  satDs.entities.removeAll(); entMap.clear();
  sats.forEach(s=>{
    const pos=Cesium.Cartesian3.fromDegrees(s.lon,s.lat,s.alt_km*1000);
    const col=Cesium.Color.fromCssColorString(s.color||'#78909C');
    const ent=satDs.entities.add({
      id:'sat_'+s.norad_id, name:s.name, position:pos,
      point:{
        pixelSize:5, color:col,
        outlineColor:Cesium.Color.WHITE.withAlpha(0.25), outlineWidth:1,
        scaleByDistance:new Cesium.NearFarScalar(5e5,1.8,1e7,0.7),
      },
      label:{
        text:s.name, font:'10px Tahoma,sans-serif',
        fillColor:Cesium.Color.WHITE, outlineColor:Cesium.Color.BLACK, outlineWidth:2,
        style:Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset:new Cesium.Cartesian2(0,-14),
        distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,1.5e6),
      },
      description:new Cesium.ConstantProperty(_buildDesc(s)),
    });
    entMap.set(s.norad_id,ent);
  });
}

// 衛星名稱/備註來自外部 TLE 來源與使用者 CSV，插入 HTML 前一律跳脫
function _esc(v){
  return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// 衛星資訊框內的「軌道要素歷史」連結（/orbit；兩顆則為雙星比較）；點擊由主頁代開，見 _bindInfoBoxLinks
function _orbitLink(nids,label){
  return '<a data-newtab href="/orbit?norad='+nids.join(',')+'" target="_blank" rel="noopener"'
    +' style="display:inline-block;margin-top:8px;padding:4px 10px;border-radius:5px;background:#1565c0;color:#fff;'
    +'text-decoration:none;font-size:12px">📈 '+(label||'軌道要素歷史')+'</a>';
}

// InfoBox 是沙盒 iframe（無 allow-popups-to-escape-sandbox），由它開的分頁會繼承沙盒而擋掉腳本，
// /orbit 因此無法執行；改在主頁攔截 a[data-newtab] 點擊，由主頁開正常分頁
// 2D 地面軌跡頁（/track）連結，樣式同 _orbitLink
function _trackLink(nid){
  return '<a data-newtab href="/track?norad='+nid+'" target="_blank" rel="noopener"'
    +' style="display:inline-block;margin:8px 0 0 6px;padding:4px 10px;border-radius:5px;background:#2e7d32;color:#fff;'
    +'text-decoration:none;font-size:12px">🗺 2D 地面軌跡</a>';
}

function _bindInfoBoxLinks(){
  const fr=viewer.infoBox&&viewer.infoBox.frame;
  if(!fr) return;
  const bind=()=>{
    try{
      const d=fr.contentDocument;
      if(!d||d._newtabBound) return;
      d._newtabBound=true;
      d.addEventListener('click',e=>{
        const a=e.target.closest&&e.target.closest('a[data-newtab]');
        if(!a) return;
        const href=a.getAttribute('href')||'';
        if(!/^\/(?!\/)/.test(href)) return;   // 只代開站內相對路徑（擋 javascript:、//外站 等注入連結）
        e.preventDefault();
        // 以主頁上的一般 target=_blank 連結代點：行為同使用者點連結，必定開新分頁（window.open 帶 features 時部分瀏覽器會開彈出視窗或被擋）
        const ln=document.createElement('a');
        ln.href=href; ln.target='_blank'; ln.rel='noopener';
        document.body.appendChild(ln); ln.click(); ln.remove();
      });
    }catch(e){}
  };
  fr.addEventListener('load',bind);
  bind();
}

function _buildDesc(s){
  return '<style>body{background:#fff;color:#212121;margin:0}</style>'
    +'<div style="font-family:Tahoma,sans-serif;font-size:13px;padding:6px">'
    +'<p style="color:#1565c0;font-weight:bold;margin-bottom:6px">'+_esc(s.name)+'</p>'
    +'<table style="border-collapse:collapse;color:#333;font-size:12px">'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">NORAD</td><td><b>'+s.norad_id+'</b></td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">國家</td><td>'+_esc(s.country||'—')+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">用途</td><td>'+_esc(s.purpose||'—')+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">年代</td><td>'+_esc(s.era||'—')+'</td></tr>'
    +(s.constellation&&s.constellation!=='—'?'<tr><td style="padding:2px 10px 2px 0;color:#555">星座</td><td>'+_esc(s.constellation)+'</td></tr>':'')
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">高度</td><td><b>'+(s.alt_km!=null?s.alt_km:'—')+' km</b></td></tr>'
    +'</table>'+_orbitLink([s.norad_id])+_trackLink(s.norad_id)+'</div>';
}

async function loadConjunctions(){
  document.getElementById('c-conj').textContent='...';
  try{
    const r=await fetch('/api/conjunctions');
    if(!r.ok) throw new Error('HTTP '+r.status);
    conjData=await r.json();
    document.getElementById('c-conj').textContent=conjData.count.toLocaleString();
    if(panelMode==='conjunctions') renderConjList();
  }catch(e){
    document.getElementById('c-conj').textContent='err';
    console.warn('接近事件載入失敗',e);
  }
}

function toggleConjPanel(){
  if(panelMode==='conjunctions'){
    document.getElementById('conj-card').classList.remove('active-card');
    setPanelMode('tabs');
    return;
  }
  document.getElementById('conj-card').classList.add('active-card');
  clearSearchUI();
  setPanelMode('conjunctions');
  renderConjList();
}

function renderConjList(){
  const body=document.getElementById('panel-body');
  body.innerHTML='';
  if(!conjData){
    body.innerHTML='<div style="padding:12px;color:#484f58;font-size:11px">接近事件載入中...</div>';
    return;
  }
  if(conjData.error){
    body.innerHTML='<div style="padding:12px;color:#FF5722;font-size:11px">'+conjData.error+'</div>';
    return;
  }
  if(!conjData.pairs||!conjData.pairs.length){
    body.innerHTML='<div style="padding:12px;color:#484f58;font-size:11px">'
      +'目前 '+conjData.threshold_km+' km 閾值內無配對（掃描 '+(conjData.total_scanned||0)+' 顆）</div>';
    return;
  }
  const note=document.createElement('div');
  note.className='conj-note';
  note.textContent='閾值 '+conjData.threshold_km+' km | 掃描 '+conjData.total_scanned
    +' 顆 | 耗時 '+conjData.elapsed_sec+' s'+(conjData.vectorized?' | ⚡向量化':'');
  body.appendChild(note);
  const riskColor={RED:'#FF5252',AMBER:'#FFB86C',GREEN:'#3fb950'};
  conjData.pairs.forEach(p=>{
    const row=document.createElement('div');
    row.className='conj-row';
    const purposeColor={有效載荷:'#4CAF50',碎片:'#FF9800',火箭體:'#9E9E9E'}[p.primary_purpose]||'#78909C';
    const sPurposeColor={有效載荷:'#4CAF50',碎片:'#FF9800',火箭體:'#9E9E9E'}[p.secondary_purpose]||'#78909C';
    const rc=riskColor[p.risk_level]||'#8b949e';
    row.innerHTML=
      '<div style="display:flex;align-items:center;gap:6px">'
      +'<span class="conj-km">'+p.miss_km.toFixed(2)+' km</span>'
      +'<span class="conj-names" title="'+p.primary_name+' + '+p.secondary_name+'">'
      +'<span style="color:'+purposeColor+'">●</span> '+p.primary_name
      +' <span style="color:#484f58">+</span>'
      +' <span style="color:'+sPurposeColor+'">●</span> '+p.secondary_name
      +'</span></div>'
      +'<div style="display:flex;align-items:center;gap:8px;margin-top:3px">'
      +'<span style="font-size:9px;color:#484f58">'+p.primary_alt_km+' km / '+p.secondary_alt_km+' km</span>'
      +'<span style="font-size:9px;font-weight:bold;color:'+rc+'" title="碰撞概率 (Chan 2008)">Pc '+p.Pc_str+'</span>'
      +'<span style="font-size:9px;padding:1px 5px;border-radius:3px;background:'+rc+'22;color:'+rc+'">'+p.risk_level+'</span>'
      +'</div>';
    row.addEventListener('click',()=>flyToPair(p));
    body.appendChild(row);
  });
}

function flyToPair(pair){
  _clearOrbit();
  satDs.entities.removeAll(); entMap.clear();
  const posA=Cesium.Cartesian3.fromDegrees(pair.primary_lon,pair.primary_lat,pair.primary_alt_km*1000);
  const posB=Cesium.Cartesian3.fromDegrees(pair.secondary_lon,pair.secondary_lat,pair.secondary_alt_km*1000);
  const colA=Cesium.Color.fromCssColorString('#FF6B6B');
  const colB=Cesium.Color.fromCssColorString('#FFB86C');
  const riskColor={RED:'#FF5252',AMBER:'#FFD740',GREEN:'#69F0AE'}[pair.risk_level]||'#fff';
  const pcInfo='<table style="border-collapse:collapse;margin-top:6px;font-size:12px;width:100%">'
    +'<tr><td style="color:#888;padding:1px 6px 1px 0">Miss Distance</td><td style="color:#fff">'+pair.miss_km.toFixed(3)+' km</td></tr>'
    +'<tr><td style="color:#888;padding:1px 6px 1px 0">Pc (Chan 2008)</td><td style="color:'+riskColor+'"><b>'+pair.Pc_str+'</b></td></tr>'
    +'<tr><td style="color:#888;padding:1px 6px 1px 0">Risk Level</td>'
    +'<td style="color:'+riskColor+'"><b>'+pair.risk_level+'</b></td></tr>'
    +'</table>';
  satDs.entities.add({id:'ca_a',name:pair.primary_name,position:posA,
    point:{pixelSize:10,color:colA,outlineColor:Cesium.Color.WHITE,outlineWidth:2},
    description:new Cesium.ConstantProperty(
      '<div style="font-family:Tahoma;padding:8px;font-size:13px;background:#1e1e1e;color:#e8e8e8">'
      +'<b style="color:#FF6B6B">'+pair.primary_name+'</b>'
      +'<br>NORAD '+pair.primary_norad
      +'<br>高度 '+pair.primary_alt_km+' km'
      +'<br>位置 '+pair.primary_lat.toFixed(2)+'°, '+pair.primary_lon.toFixed(2)+'°'
      +pcInfo+_orbitLink([pair.primary_norad,pair.secondary_norad],'雙星軌道要素比較')+'</div>')
  });
  satDs.entities.add({id:'ca_b',name:pair.secondary_name,position:posB,
    point:{pixelSize:10,color:colB,outlineColor:Cesium.Color.WHITE,outlineWidth:2},
    description:new Cesium.ConstantProperty(
      '<div style="font-family:Tahoma;padding:8px;font-size:13px;background:#1e1e1e;color:#e8e8e8">'
      +'<b style="color:#FFB86C">'+pair.secondary_name+'</b>'
      +'<br>NORAD '+pair.secondary_norad
      +'<br>高度 '+pair.secondary_alt_km+' km'
      +'<br>位置 '+pair.secondary_lat.toFixed(2)+'°, '+pair.secondary_lon.toFixed(2)+'°'
      +pcInfo+_orbitLink([pair.primary_norad,pair.secondary_norad],'雙星軌道要素比較')+'</div>')
  });
  satDs.entities.add({polyline:{
    positions:[posA,posB], width:2,
    material:new Cesium.ColorMaterialProperty(Cesium.Color.fromCssColorString('#FF6B6B').withAlpha(0.7)),
    arcType:Cesium.ArcType.NONE,
  }});
  const midLat=(pair.primary_lat+pair.secondary_lat)/2;
  const midLon=(pair.primary_lon+pair.secondary_lon)/2;
  const midAlt=(pair.primary_alt_km+pair.secondary_alt_km)/2*1000;
  viewer.camera.flyTo({
    destination:Cesium.Cartesian3.fromDegrees(midLon,midLat,midAlt+800000),
    duration:2,
  });
  document.getElementById('filter-status').textContent=
    pair.primary_name+' + '+pair.secondary_name+' — '+pair.miss_km.toFixed(2)+' km | Pc '+pair.Pc_str+' ('+pair.risk_level+')';
  // 同時繪製兩顆衛星的軌道弧
  showOrbitArc(pair.primary_norad,   '#FF6B6B');
  showOrbitArc(pair.secondary_norad, '#FFB86C');
}

document.getElementById('search-input').addEventListener('input', function(){
  clearTimeout(_searchTimer);
  const q=this.value.trim();
  document.getElementById('search-clear').style.display=q?'':'none';
  if(q.length<2){ clearSearchUI(); return; }
  _searchTimer=setTimeout(()=>doSearch(q),400);
});

async function doSearch(q){
  try{
    const r=await fetch('/api/search?q='+encodeURIComponent(q));
    if(!r.ok) return;
    const d=await r.json();
    showSearchResults(d.results);
  }catch(e){ console.warn('搜尋失敗',e); }
}

function showSearchResults(results){
  document.getElementById('conj-card').classList.remove('active-card');
  setPanelMode('search');
  const body=document.getElementById('panel-body');
  body.innerHTML='';
  if(!results||!results.length){
    body.innerHTML='<div style="padding:12px;color:#484f58;font-size:11px">未找到符合結果</div>';
    return;
  }
  results.forEach(s=>{
    const color=getColor('country',s.country);
    const row=document.createElement('button');
    row.className='stat-row';
    row.innerHTML=
      '<span class="stat-dot" style="background:'+color+'"></span>'
      +'<span class="stat-label" title="'+s.name+'">'+s.name+'</span>'
      +'<span style="font-size:10px;color:#484f58;min-width:54px;text-align:right">'+s.norad_id+'</span>';
    row.addEventListener('click',()=>flyToSat(s));
    body.appendChild(row);
  });
}

function clearSearch(){
  document.getElementById('search-input').value='';
  clearSearchUI();
}

function clearSearchUI(){
  document.getElementById('search-clear').style.display='none';
  clearTimeout(_searchTimer);
  if(panelMode==='search') setPanelMode('tabs');
}

function colorToHex(c){
  const h=v=>Math.round(v*255).toString(16).padStart(2,'0');
  return '#'+h(c.red)+h(c.green)+h(c.blue);
}

function _clearOrbit(){
  orbitEnts.forEach(e=>{ try{ viewer.entities.remove(e); }catch(_){} });
  orbitEnts=[];
}

async function showOrbitArc(nid,colorHex){
  try{
    const r=await fetch('/api/sat_orbit?norad_id='+nid+'&hours=2&pts=120');
    if(!r.ok) return;
    const d=await r.json();
    if(!d.positions||d.positions.length<2) return;
    const coords=d.positions.flatMap(p=>[p.lon,p.lat,p.alt_km*1000]);
    const glowColor=Cesium.Color.fromCssColorString(colorHex||'#58a6ff').withAlpha(0.9);
    orbitEnts.push(viewer.entities.add({
      polyline:{
        positions:Cesium.Cartesian3.fromDegreesArrayHeights(coords),
        width:1.8,
        material:new Cesium.PolylineGlowMaterialProperty({glowPower:0.1,color:glowColor}),
        clampToGround:false,
        arcType:Cesium.ArcType.NONE,
      },
    }));
  }catch(e){ console.warn('軌道弧載入失敗',e); }
}

async function fetchSatDetail(nid){
  const panel=document.getElementById('sat-detail-panel');
  if(!panel) return;
  panel.style.display='block';
  panel.innerHTML='<div style="padding:5px 10px;font-size:11px;color:#484f58">Space-Track 查詢中…</div>';
  const [cdmR,decayR,satcatR]=await Promise.allSettled([
    fetch('/api/cdm/'+nid).then(r=>r.json()),
    fetch('/api/decay/'+nid).then(r=>r.json()),
    fetch('/api/satcat/'+nid).then(r=>r.json()),
  ]);
  let html='';
  // SATCAT
  if(satcatR.status==='fulfilled'&&!satcatR.value.error&&!satcatR.value.message){
    const s=satcatR.value;
    const parts=[];
    if(s.object_type) parts.push('<span style="color:#484f58">類型 </span><b>'+s.object_type+'</b>');
    if(s.apogee_km)   parts.push('<span style="color:#484f58">遠地 </span>'+Math.round(s.apogee_km)+' km');
    if(s.perigee_km)  parts.push('<span style="color:#484f58">近地 </span>'+Math.round(s.perigee_km)+' km');
    if(s.inclination) parts.push('<span style="color:#484f58">傾角 </span>'+parseFloat(s.inclination).toFixed(1)+'°');
    if(parts.length) html+='<div class="st-sec">SATCAT</div>'
      +'<div class="st-row">'+parts.map(p=>'<span>'+p+'</span>').join('')+'</div>';
  }
  // CDM
  if(cdmR.status==='fulfilled'&&!cdmR.value.error){
    const d=cdmR.value;
    if(d.events&&d.events.length){
      html+='<div class="st-sec">CDM ('+d.count+')</div>';
      d.events.slice(0,3).forEach(ev=>{
        const pc=parseFloat(ev.pc||0);
        const hi=pc>1e-4;
        html+='<div class="cdm-ev">'
          +'<div style="font-size:10px;color:#c9d1d9">TCA: '+(ev.tca||'—')+'</div>'
          +'<div style="display:flex;gap:8px;margin-top:2px">'
          +'<span style="color:'+(hi?'#FF5252':'#8b949e');
        html+=hi?';font-weight:bold':'';
        html+='">Pc '+pc.toExponential(2)+(hi?' ⚠':'')+'</span>'
          +'<span style="color:#8b949e">Miss '+parseFloat(ev.min_rng_km||0).toFixed(1)+' km</span>'
          +'</div>'
          +(ev.sat2_name?'<div style="font-size:10px;color:#484f58">vs '+ev.sat2_name+'</div>':'')
          +'</div>';
      });
    } else {
      html+='<div class="st-sec">CDM</div>'
        +'<div style="padding:2px 10px 5px;font-size:11px;color:#484f58">無近期接近事件</div>';
    }
  }
  // Decay
  if(decayR.status==='fulfilled'&&!decayR.value.error&&!decayR.value.message){
    const d=decayR.value;
    if(d.decay_epoch){
      html+='<div class="st-sec">再入預測</div>'
        +'<div class="st-row"><span><span style="color:#484f58">預測再入 </span>'
        +'<b>'+d.decay_epoch+'</b></span>'
        +(d.precedence?'<span><span style="color:#484f58">Precedence </span>'+d.precedence+'</span>':'')
        +'</div>';
    }
  }
  if(!html){
    panel.style.display='none';
  } else {
    panel.innerHTML=html;
  }
}

function flyToSat(s){
  if(s.lat==null) return;
  _stopSelRefresh();
  _clearOrbit();
  satDs.entities.removeAll(); entMap.clear();
  const pos=Cesium.Cartesian3.fromDegrees(s.lon,s.lat,s.alt_km*1000);
  const col=Cesium.Color.fromCssColorString(getColor('country',s.country));
  const ent=satDs.entities.add({
    id:'sat_'+s.norad_id, name:s.name, position:pos,
    point:{pixelSize:10,color:col,outlineColor:Cesium.Color.WHITE,outlineWidth:2},
    description:new Cesium.ConstantProperty(_buildDesc(s)),
  });
  entMap.set(s.norad_id,ent);
  viewer.flyTo(ent,{duration:2});
  viewer.selectedEntity=ent;
  document.getElementById('filter-status').textContent=s.name+' (#'+s.norad_id+')';
  activeFtype=activeFval=null;
  showOrbitArc(s.norad_id, getColor('country',s.country));
  fetchSatDetail(s.norad_id);
  _startSelRefresh([s.norad_id]);
}

async function toggleLayer(type,cb){
  if(type==='borders'){
    if(borderDs){ borderDs.show=cb.checked; return; }
    if(cb.checked) await loadBordersLayer();
    return;
  }
  const ref={ssn:{get:()=>ssnDs,set:v=>{ssnDs=v;},url:'/api/layers/ssn_stations'}}[type];
  if(!ref) return;
  if(cb.checked){
    try{
      const ds=await Cesium.GeoJsonDataSource.load(ref.url);
      [...ds.entities.values].forEach(ent=>{
        const props=ent.properties;
        const stationType=props.type&&props.type.getValue()||'雷達';
        const status=props.status&&props.status.getValue()||'active';
        const hexCol=SSN_TYPE_COLORS[stationType]||'#00E5FF';
        const col=Cesium.Color.fromCssColorString(hexCol);
        const isRetired=(status==='decommissioned');
        ent.billboard=undefined;
        ent.point=new Cesium.PointGraphics({
          pixelSize:isRetired?5:9,
          color:isRetired?col.withAlpha(0.45):col,
          outlineColor:Cesium.Color.BLACK.withAlpha(0.7),outlineWidth:1,
        });
        const nameVal=props.name&&props.name.getValue()||'';
        ent.label=new Cesium.LabelGraphics({
          text:nameVal,font:'10px Tahoma,sans-serif',
          fillColor:isRetired?Cesium.Color.fromCssColorString('#9E9E9E'):Cesium.Color.WHITE,
          outlineColor:Cesium.Color.BLACK,outlineWidth:2,
          style:Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset:new Cesium.Cartesian2(0,-13),
          distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,isRetired?2e6:7e6),
          show:true,
        });
        const locVal=props.location&&props.location.getValue()||'';
        const notesVal=props.notes&&props.notes.getValue()||'';
        ent.description=new Cesium.ConstantProperty(
          '<div style="font-family:Tahoma,sans-serif;font-size:13px;padding:8px;background:#1e1e1e;color:#e8e8e8">'
          +'<p style="color:#8ab4f8;font-weight:bold;font-size:14px;margin:0 0 8px">'+nameVal+'</p>'
          +'<table style="border-collapse:collapse;width:100%;font-size:12px">'
          +'<tr><td style="color:#aaa;padding:2px 10px 2px 0">類型</td><td style="color:#e8e8e8"><b>'+stationType+'</b></td></tr>'
          +'<tr><td style="color:#aaa;padding:2px 10px 2px 0">位置</td><td style="color:#e8e8e8">'+locVal+'</td></tr>'
          +'<tr><td style="color:#aaa;padding:2px 10px 2px 0">狀態</td><td>'
          +(isRetired?'<span style="color:#f44336">已除役</span>':'<span style="color:#4caf50">運作中</span>')
          +'</td></tr>'+(notesVal?'<tr><td style="color:#aaa;padding:2px 10px 2px 0;vertical-align:top">備註</td><td style="color:#ccc">'+notesVal+'</td></tr>':'')
          +'</table></div>'
        );
        const posCart=ent.position.getValue(Cesium.JulianDate.now());
        if(posCart){
          const carto=Cesium.Cartographic.fromCartesian(posCart);
          const lon=Cesium.Math.toDegrees(carto.longitude);
          const lat=Cesium.Math.toDegrees(carto.latitude);
          const h=20000;
          ent.position=new Cesium.ConstantPositionProperty(Cesium.Cartesian3.fromDegrees(lon,lat,h));
          ds.entities.add({polyline:{
            positions:Cesium.Cartesian3.fromDegreesArrayHeights([lon,lat,0,lon,lat,h]),
            width:1,
            material:new Cesium.ColorMaterialProperty(
              (isRetired?Cesium.Color.fromCssColorString('#9E9E9E'):col).withAlpha(isRetired?0.30:0.55)),
            clampToGround:false,arcType:Cesium.ArcType.NONE,
            distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,7e6),
          }});
        }
      });
      await viewer.dataSources.add(ds);
      ref.set(ds);
    }catch(e){
      cb.checked=false;
      console.warn('向量圖層載入失敗: '+type,e);
    }
  }else{
    const ds=ref.get();
    if(ds) viewer.dataSources.remove(ds,true);
    ref.set(null);
  }
}

let _currentBasemap='default';

let _basemapMeta={};  // key → {type,tms_url,...}

async function initBasemapBar(){
  try{
    const r=await fetch('/api/textures');
    if(!r.ok) return;
    const list=await r.json();
    list.forEach(bm=>{ _basemapMeta[bm.key]=bm; });
    const container=document.getElementById('basemap-btns');
    list.forEach(bm=>{
      const btn=document.createElement('button');
      btn.className='bm-btn'+(bm.key===_currentBasemap?' active':'')+(bm.available?'':' unavail');
      btn.dataset.key=bm.key;
      btn.title=bm.available?bm.credit:'尚未下載 — '+bm.credit;
      btn.innerHTML='<span class="bm-dot"></span>'
        +'<span style="flex:1">'+bm.label+'</span>'
        +(bm.available?'':'<span style="font-size:9px;color:#484f58">未下載</span>');
      if(bm.available) btn.addEventListener('click',()=>switchBasemap(bm.key));
      container.appendChild(btn);
    });
  }catch(e){ console.warn('底圖清單載入失敗',e); }
}

function switchBasemap(key){
  if(key===_currentBasemap) return;
  _currentBasemap=key;
  document.querySelectorAll('.bm-btn').forEach(b=>{
    b.classList.toggle('active', b.dataset.key===key);
  });
  const layers=viewer.imageryLayers;
  layers.removeAll();
  const meta=_basemapMeta[key]||{};
  let provider;
  if(meta.type==='tms'){
    provider=new Cesium.TileMapServiceImageryProvider({
      url: meta.tms_url,
      fileExtension:'jpg',
      credit: meta.credit||'Natural Earth II',
    });
  }else{
    provider=new Cesium.SingleTileImageryProvider({
      url:'/api/globe_texture/'+key,
      rectangle:Cesium.Rectangle.fromDegrees(-180,-90,180,90),
      credit: meta.credit||'NASA Blue Marble / Visible Earth',
    });
  }
  layers.addImageryProvider(provider);
}

async function loadDbInfo(){
  try{
    const r=await fetch('/api/db_info');
    if(!r.ok) return;
    const d=await r.json();
    if(d.error) return;
    document.getElementById('dbi-name').textContent=d.db_name||'—';
    if(d.db_updated_at){
      const mt=new Date(d.db_updated_at);
      const diffH=(Date.now()-mt)/3600000;
      const el=document.getElementById('dbi-mtime');
      el.textContent=mt.toISOString().replace('T',' ').slice(0,16)+' UTC';
      el.className='dbi-v '+(diffH<48?'ok':'warn');
    }
    if(d.valid_sat_count!=null)
      document.getElementById('dbi-sats').textContent=d.valid_sat_count.toLocaleString()+' 顆';
    if(d.epoch_min&&d.epoch_max)
      document.getElementById('dbi-epoch').textContent=d.epoch_min.slice(0,10)+' ~ '+d.epoch_max.slice(0,10);
    if(d.db_size_mb!=null)
      document.getElementById('dbi-size').textContent=d.db_size_mb.toLocaleString()+' MB';
  }catch(e){console.warn('DB info 載入失敗',e);}
}

// 多衛星模式配色池（依序循環）
const MULTI_COLORS=[
  '#00E5FF','#FF6B6B','#69FF47','#FFD600','#FF9800',
  '#E040FB','#00BFA5','#FF4081','#40C4FF','#CCFF90',
];

async function _resolveSat(token){
  // token：純數字→NORAD ID，否則→名稱搜尋
  if(/^\d+$/.test(token)){
    try{
      const r=await fetch('/api/position/'+encodeURIComponent(token));
      if(r.ok){ const d=await r.json(); if(!d.error&&d.lat!=null) return d; }
    }catch(e){}
  }
  try{
    const r=await fetch('/api/search?q='+encodeURIComponent(token));
    if(r.ok){
      const d=await r.json();
      const found=(d.results||[]).find(x=>x.lat!=null);
      if(found) return found;
    }
  }catch(e){}
  return null;
}

async function showMultiSats(tokens){
  _stopSelRefresh();
  _clearOrbit();
  satDs.entities.removeAll(); entMap.clear();
  activeFtype=activeFval=null;
  const statusEl=document.getElementById('filter-status');
  statusEl.textContent='載入 '+tokens.length+' 顆衛星…';

  // 依序解析（保留 MULTI_COLORS 順序）
  const results=[];
  for(let i=0;i<tokens.length;i++){
    const sat=await _resolveSat(tokens[i]);
    if(sat) results.push(Object.assign({},sat,{_color:MULTI_COLORS[i%MULTI_COLORS.length]}));
  }

  if(!results.length){
    statusEl.textContent='查無任何衛星位置資料：'+tokens.join(', ');
    return;
  }

  // 建立實體
  results.forEach(s=>{
    const pos=Cesium.Cartesian3.fromDegrees(s.lon,s.lat,s.alt_km*1000);
    const col=Cesium.Color.fromCssColorString(s._color);
    const ent=satDs.entities.add({
      id:'sat_'+s.norad_id, name:s.name, position:pos,
      point:{
        pixelSize:11, color:col,
        outlineColor:Cesium.Color.WHITE, outlineWidth:2,
        scaleByDistance:new Cesium.NearFarScalar(5e5,1.6,8e6,0.8),
      },
      label:{
        text:s.name,
        font:'11px "Segoe UI",sans-serif',
        fillColor:col,
        outlineColor:Cesium.Color.BLACK, outlineWidth:2,
        style:Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset:new Cesium.Cartesian2(0,-18),
        distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,2e7),
      },
      description:new Cesium.ConstantProperty(_buildDesc(s)),
    });
    entMap.set(s.norad_id,ent);
  });

  // 並行載入所有軌道弧
  await Promise.all(results.map(s=>showOrbitArc(s.norad_id,s._color)));

  // 飛至包含所有衛星的視角
  try{ await viewer.flyTo(satDs,{duration:2}); }catch(e){}

  const found=results.length, req=tokens.length;
  statusEl.textContent='顯示 '+found+(found<req?' / '+req:'')
    +' 顆：'+results.map(s=>s.name).join('、');
  _startSelRefresh(results.map(s=>s.norad_id));
}

async function autoSelectFromUrl(){
  // 支援 ?sat=55025,66666,25544  ?sat=STARLINK-36833  ?norad_id=55025
  const params   = new URLSearchParams(window.location.search);

  // ?v3flight14=1 -- 一次顯示 Starship Flight 14 的 26 顆 Starlink V3
  // (合成 NORAD 339974-339999，MEME 精密星曆反算 SGP4 估測軌道，非官方 TLE)
  if(params.get('v3flight14') === '1'){
    const V3_FLIGHT14_IDS = Array.from({length:26}, (_,i)=>String(339974+i));
    await showMultiSats(V3_FLIGHT14_IDS);
    return;
  }

  const satParam = (params.get('sat') || params.get('norad_id') || params.get('norad') || '').trim();
  if(!satParam) return;

  const tokens = satParam.split(',').map(s=>s.trim()).filter(Boolean);

  if(tokens.length > 1){
    await showMultiSats(tokens);
    return;
  }

  // 單顆衛星
  const statusEl = document.getElementById('filter-status');
  statusEl.textContent = '正在查詢「' + satParam + '」…';
  try{
    const result = await _resolveSat(satParam);
    if(result){
      flyToSat(result);
    } else {
      statusEl.textContent = '查無衛星或位置資料：' + satParam;
    }
  }catch(e){
    console.warn('URL 衛星查詢失敗', e);
    statusEl.textContent = '查詢失敗：' + e.message;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// NORAD 監測（user_defined_tracking_NORAD 清單 + 手動加入，多顆同時追蹤）
// ─────────────────────────────────────────────────────────────────────────────
let trackData=null;               // /api/tracking/list 的 items
let trackDs=null;                 // 監測衛星專用 DataSource（與分類篩選 satDs 分離）
let trackTimer=null;
const trackEnabled=new Map();     // nid -> meta（追蹤中，含手動加入）
const trackOrbitEnts=new Map();   // nid -> 軌道弧實體陣列
const trackLastPos={};            // nid -> 最近一次位置回應
const TRACK_REFRESH_MS=15000;

async function _initTrackDs(){
  if(trackDs) return;
  trackDs=new Cesium.CustomDataSource('tracking');
  await viewer.dataSources.add(trackDs);
}

function updateTrackBadge(){
  const el=document.getElementById('track-count');
  if(el) el.textContent=trackEnabled.size?(' ('+trackEnabled.size+')'):'';
}

function _startTrackTimer(){
  if(trackTimer) return;
  trackTimer=setInterval(()=>{ if(trackEnabled.size) refreshTracking(); },TRACK_REFRESH_MS);
}

async function loadTrackingList(){
  try{
    const r=await fetch('/api/tracking/list');
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    trackData=d.items||[];
    trackData.forEach(it=>{ if(it.enabled) trackEnabled.set(it.norad_id,it); });
    updateTrackBadge();
    if(trackEnabled.size){ await refreshTracking(); _startTrackTimer(); }
  }catch(e){ console.warn('NORAD 監測清單載入失敗',e); }
}

function _buildTrackDesc(s,meta){
  const pri=meta&&meta.priority_label?meta.priority_label:'—';
  return '<style>body{background:#fff;color:#212121;margin:0}</style>'
    +'<div style="font-family:Tahoma,sans-serif;font-size:13px;padding:6px">'
    +'<p style="color:#c2185b;font-weight:bold;margin-bottom:6px">🎯 '
    +_esc((meta&&meta.alias)||s.name)+'</p>'
    +'<table style="border-collapse:collapse;color:#333;font-size:12px">'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">NORAD</td><td><b>'+s.norad_id+'</b></td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">名稱</td><td>'+_esc(s.name)+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">國家</td><td>'+_esc(s.country||'—')+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">用途</td><td>'+_esc(s.purpose||'—')+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">優先度</td><td>'+_esc(pri)+'</td></tr>'
    +'<tr><td style="padding:2px 10px 2px 0;color:#555">高度</td><td><b>'+(s.alt_km!=null?s.alt_km:'—')+' km</b></td></tr>'
    +(s.user_defined?'<tr><td style="padding:2px 10px 2px 0;color:#555">來源</td><td style="color:#7b1fa2">使用者自訂 TLE</td></tr>':'')
    +(s.notes?'<tr><td style="padding:2px 10px 2px 0;color:#555">備註</td><td>'+_esc(s.notes)+'</td></tr>':'')
    +'</table>'+_orbitLink([s.norad_id])+_trackLink(s.norad_id)+'</div>';
}

async function _loadTrackOrbit(nid,color){
  try{
    const r=await fetch('/api/sat_orbit?norad_id='+nid+'&hours=2&pts=120');
    if(!r.ok) return;
    const d=await r.json();
    if(!d.positions||d.positions.length<2) return;
    if(!trackEnabled.has(nid)||!trackDs) return;
    const coords=d.positions.flatMap(p=>[p.lon,p.lat,p.alt_km*1000]);
    const ent=trackDs.entities.add({polyline:{
      positions:Cesium.Cartesian3.fromDegreesArrayHeights(coords),
      width:1.5,
      material:new Cesium.PolylineGlowMaterialProperty({
        glowPower:0.12,
        color:Cesium.Color.fromCssColorString(color).withAlpha(0.85)}),
      arcType:Cesium.ArcType.NONE,
    }});
    if(!trackOrbitEnts.has(nid)) trackOrbitEnts.set(nid,[]);
    trackOrbitEnts.get(nid).push(ent);
  }catch(e){ console.warn('監測軌道弧載入失敗 #'+nid,e); }
}

async function refreshTracking(){
  if(!trackEnabled.size) return;
  await _initTrackDs();
  const ids=[...trackEnabled.keys()].join(',');
  try{
    const r=await fetch('/api/tracking/positions?ids='+ids);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    (d.satellites||[]).forEach(s=>{
      trackLastPos[s.norad_id]=s;
      if(!s.ok) return;
      const meta=trackEnabled.get(s.norad_id)||{};
      const color=meta.color||s.color||'#FF4081';
      const pos=Cesium.Cartesian3.fromDegrees(s.lon,s.lat,s.alt_km*1000);
      let ent=trackDs.entities.getById('track_'+s.norad_id);
      if(!ent){
        const col=Cesium.Color.fromCssColorString(color);
        ent=trackDs.entities.add({
          id:'track_'+s.norad_id, name:(meta.alias||s.name), position:pos,
          point:{pixelSize:10,color:col,outlineColor:Cesium.Color.WHITE,outlineWidth:2,
                 scaleByDistance:new Cesium.NearFarScalar(5e5,1.6,2e7,0.8)},
          label:{text:(meta.alias||s.name)+'\n#'+s.norad_id,
                 font:'11px "Segoe UI",Tahoma,sans-serif',
                 fillColor:col, outlineColor:Cesium.Color.BLACK, outlineWidth:2,
                 style:Cesium.LabelStyle.FILL_AND_OUTLINE,
                 pixelOffset:new Cesium.Cartesian2(0,-22),
                 distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,4e7)},
        });
        _loadTrackOrbit(s.norad_id,color);
      }else{
        ent.position=pos;
      }
      ent.description=new Cesium.ConstantProperty(_buildTrackDesc(s,meta));
    });
    if(panelMode==='tracking') renderTrackPanel();
  }catch(e){ console.warn('監測位置更新失敗',e); }
}

async function toggleTrackSat(nid,on){
  if(on){
    const meta=(trackData||[]).find(x=>x.norad_id===nid)
      ||{norad_id:nid,alias:'',color:'',priority:'medium',priority_label:'手動',notes:''};
    trackEnabled.set(nid,meta);
    _startTrackTimer();
    await refreshTracking();
  }else{
    trackEnabled.delete(nid);
    if(trackDs){
      const ent=trackDs.entities.getById('track_'+nid);
      if(ent) trackDs.entities.remove(ent);
      (trackOrbitEnts.get(nid)||[]).forEach(e=>{ try{ trackDs.entities.remove(e); }catch(_){}});
      trackOrbitEnts.delete(nid);
    }
  }
  updateTrackBadge();
  if(panelMode==='tracking') renderTrackPanel();
}

async function addTrackManual(){
  const inp=document.getElementById('track-add-input');
  if(!inp) return;
  const toks=(inp.value||'').split(/[,\s]+/).filter(Boolean);
  const nids=toks.filter(t=>/^\d+$/.test(t)).map(Number);
  if(!nids.length){ inp.value=''; inp.placeholder='請輸入數字 NORAD ID'; return; }
  inp.value='';
  for(const nid of nids){ if(!trackEnabled.has(nid)) await toggleTrackSat(nid,true); }
}

function flyToTracked(nid){
  const ent=trackDs&&trackDs.entities.getById('track_'+nid);
  if(ent){ viewer.flyTo(ent,{duration:1.5}); viewer.selectedEntity=ent; }
}

function toggleTrackPanel(){
  const btn=document.getElementById('track-btn');
  if(panelMode==='tracking'){
    btn.classList.remove('active');
    setPanelMode('tabs');
    return;
  }
  document.getElementById('conj-card').classList.remove('active-card');
  btn.classList.add('active');
  clearSearchUI();
  setPanelMode('tracking');
  renderTrackPanel();
}

function renderTrackPanel(){
  if(panelMode!=='tracking') return;
  const body=document.getElementById('panel-body');
  body.innerHTML='';

  const note=document.createElement('div');
  note.className='conj-note';
  note.textContent='CSV 清單 '+((trackData||[]).length)+' 筆 | 追蹤中 '
    +trackEnabled.size+' 顆 | 每 '+(TRACK_REFRESH_MS/1000)+' 秒自動更新';
  body.appendChild(note);

  const add=document.createElement('div');
  add.className='track-add';
  add.innerHTML='<input id="track-add-input" type="text" placeholder="輸入 NORAD ID（可逗號分隔多顆）"/>'
    +'<button>加入</button>';
  add.querySelector('button').addEventListener('click',addTrackManual);
  add.querySelector('input').addEventListener('keydown',ev=>{ if(ev.key==='Enter') addTrackManual(); });
  body.appendChild(add);

  // CSV 清單 + 手動加入（不在 CSV 中）的合併列表
  const rows=[...(trackData||[])];
  trackEnabled.forEach((meta,nid)=>{
    if(!rows.some(r=>r.norad_id===nid)) rows.push(meta);
  });

  if(!rows.length){
    const empty=document.createElement('div');
    empty.style.cssText='padding:12px;color:#484f58;font-size:11px;line-height:1.6';
    empty.innerHTML='監測清單為空。<br>將 CSV 放入 <code style="color:#8b949e">scenario04/user_defined_tracking_NORAD/</code><br>或於上方輸入 NORAD ID 手動加入。';
    body.appendChild(empty);
    return;
  }

  rows.forEach(item=>{
    const nid=item.norad_id;
    const on=trackEnabled.has(nid);
    const pos=trackLastPos[nid];
    const row=document.createElement('div');
    row.className='track-row';

    const cb=document.createElement('input');
    cb.type='checkbox'; cb.checked=on;
    cb.addEventListener('click',ev=>ev.stopPropagation());
    cb.addEventListener('change',()=>toggleTrackSat(nid,cb.checked));

    const dot=document.createElement('span');
    dot.className='track-dot';
    dot.style.background=item.color||'#FF4081';

    const info=document.createElement('div');
    info.className='track-info';
    const alias=item.alias||item.name||('NORAD-'+nid);
    let sub='#'+nid+(item.name&&item.name!==alias?(' · '+item.name):'');
    let posLine='';
    if(pos&&pos.ok){
      posLine=pos.lat.toFixed(2)+'°, '+pos.lon.toFixed(2)+'° / '+pos.alt_km.toLocaleString()+' km';
    }else if(pos&&!pos.ok){
      posLine='⚠ '+(pos.error||'無位置資料');
    }
    info.innerHTML='<div class="track-alias">'+alias+'</div>'
      +'<div class="track-sub">'+sub+'</div>'
      +(posLine?'<div class="track-pos">'+posLine+'</div>':'');

    row.appendChild(cb); row.appendChild(dot); row.appendChild(info);

    if(pos&&pos.user_defined){
      const uf=document.createElement('span');
      uf.className='track-user-flag'; uf.textContent='自訂'; uf.title='使用者自訂 TLE';
      row.appendChild(uf);
    }
    const pri=document.createElement('span');
    pri.className='track-pri '+(item.priority||'medium');
    pri.textContent=item.priority_label||'中';
    row.appendChild(pri);

    row.addEventListener('click',()=>{ if(trackEnabled.has(nid)) flyToTracked(nid); });
    body.appendChild(row);
  });
}

function _tickUtcClock(){
  const n=new Date();
  const el=document.getElementById('led-time');
  if(el) el.textContent=[n.getUTCHours(),n.getUTCMinutes(),n.getUTCSeconds()]
    .map(v=>String(v).padStart(2,'0')).join(':');
}

document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
    _stopFilterRefresh();
  } else {
    if(activeFtype&&activeFval) _startFilterRefresh(entMap.size);
  }
});

async function init(){
  _tickUtcClock();
  setInterval(_tickUtcClock,1000);
  await initCesium();
  await loadBordersLayer();
  loadUserGeojsonLayers();
  await loadStats();
  loadConjunctions();
  loadDbInfo();
  loadTrackingList();
  await autoSelectFromUrl();
  autoOpenPanelFromUrl();
}

function autoOpenPanelFromUrl(){
  // 支援 /?open=orbit6 從 /orbit-tuner 介紹頁 CTA 連結直接開啟軌道六參數面板
  const params = new URLSearchParams(window.location.search);
  if(params.get('open') === 'orbit6') toggleOrbit6Panel();
}

init().catch(e=>{
  document.getElementById('loading').textContent='初始化失敗: '+e.message;
  console.error(e);
});

window.switchTab=switchTab;
window.toggleLayer=toggleLayer;
window.toggleConjPanel=toggleConjPanel;
window.clearSearch=clearSearch;
window.backToTabs=backToTabs;
window.toggleTrackPanel=toggleTrackPanel;
window.addTrackManual=addTrackManual;
window.toggleOrbit6Panel=toggleOrbit6Panel;

} // end startApp
