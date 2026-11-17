// =====================================================================
// 圖層清單單一來源（single source of truth）。
//
// 以前同一批圖層散在三個地方：static/index.html 的下拉選單 <option>（手寫）、
// 同一支檔案裡各服務各自的 L.tileLayer 物件、以及 ndu60/、ilovemyhome/ 兩個
// 主題頁各自複製一份「歷史影像候選清單」。新增一個圖層要改 2~3 處，漏改任何
// 一處都不會報錯，只會安靜地少一個選項或多一個過時網址。現在全部從這支檔案產生：
//
//   - static/index.html   ：下拉選單、底圖圖層物件、OSM/防災疊圖面板
//   - static/ndu60/       ：歷史影像投影片候選（scope: nationwide + taoyuan）
//   - static/ilovemyhome/ ：同上，再加 newtaipei
//
// 新增/修改圖層：只改這裡。這是純資料 + 兩個小函式，不依賴 Leaflet，
// 各頁自己決定怎麼建圖層物件。載入順序：要在使用它的 <script> 之前載入。
// （純靜態檔案、不需要 build；用 classic <script> 而不是 ES module，
//  是因為各頁都是單檔內嵌 script，維持一致比較不會踩到載入順序問題。）
//
// 欄位說明（layers 每一筆）：
//   id            下拉選單 value，也是分享連結 layer= 參數用的識別碼——改名會讓舊的
//                 分享連結失效，非必要不要改。
//   group         optgroup 的 id（見 groups）；null 表示放在下拉選單最上面、不分組。
//   kind          "tile"   一般 {z}/{x}/{y} 圖磚樣板
//                 "wms"    OGC WMS（沒有固定格網，走 L.tileLayer.wms）
//                 "keyed"  需要使用者自備金鑰，樣板裡的 {key} 由頁面替換
//                 "sentinel" Copernicus Sentinel-2：樣板裡的 {instance}、{time} 由頁面替換
//                 "custom" 由頁面程式碼特別處理（Google／Apple，非圖磚樣板）
//                 "disabled" 只是占位選項，不可選
//   slideshow     有這個欄位才會進主題頁的歷史影像投影片候選：
//                 { year（只用來排序，不是精確測繪年份）, label, scope, rank? }
//                 scope 決定哪個主題頁會納入："nationwide" 全國涵蓋（所有頁面都納入）、
//                 "taoyuan"、"newtaipei"、"hsinchu" 只涵蓋該縣市（只有對應區域的頁面才納入）。
//                 rank（選填，預設 0）：同一年份有多張時的先後，小的先播。慣例：NLSC 歷年像片基本圖是 1，2003 年以後
//                 的專題圖（經建版地形圖、縣市正射影像、最新正射影像）是 2，其餘 0。原本這個順序是靠陣列
//                 手寫順序決定，重構成單一清單後會變成依「圖層在這個檔案裡的位置」，悄悄改掉
//                 投影片的收尾（原本最後一張是最新正射影像）——所以明確寫成欄位，不靠檔案順序。
// =====================================================================
window.MAP_LAYERS = (function () {
  "use strict";

  // ---- 出處標示（HTML 字串，直接給 Leaflet attribution 用）
  const ATTR = {
    osm: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>',
    esri: "Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    sinica:
      '中央研究院人社中心 GIS 專題中心 <a href="https://gis.sinica.edu.tw/tileserver/wmts" target="_blank" rel="noopener">臺灣百年歷史地圖 WMTS 服務</a>',
    nlsc: '中華民國內政部國土測繪中心 <a href="https://wmts.nlsc.gov.tw/wmts" target="_blank" rel="noopener">WMTS 服務</a>',
    taipei:
      '臺北市政府都市發展局 <a href="https://www.historygis.udd.gov.taipei/wmts/" target="_blank" rel="noopener">歷史圖資展示系統</a>',
    taichung: '臺中市政府 <a href="https://giscloud.taichung.gov.tw/" target="_blank" rel="noopener">圖資雲</a>',
    sentinel:
      'Contains modified <a href="https://dataspace.copernicus.eu/" target="_blank" rel="noopener">Copernicus Sentinel</a> data（ESA / 歐盟 Copernicus）',
    taoyuan:
      '中央研究院人社中心 <a href="https://gis.sinica.edu.tw/taoyuan/" target="_blank" rel="noopener">桃園百年歷史地圖</a>',
    newtaipei:
      '中央研究院人社中心 <a href="https://gis.sinica.edu.tw/newtaipei/" target="_blank" rel="noopener">新北百年歷史地圖</a>',
    hsinchu:
      '中央研究院人社中心 <a href="https://gis.sinica.edu.tw/hsinchu/" target="_blank" rel="noopener">新竹百年歷史地圖</a>',
  };

  // ---- 下拉選單分組（順序即顯示順序）
  const groups = [
    { id: "sinica", label: "中央研究院人社中心 GIS 專題中心（公開 WMTS，免金鑰）", attribution: ATTR.sinica },
    { id: "nlsc", label: "內政部國土測繪中心 NLSC（公開 WMTS，免金鑰）", attribution: ATTR.nlsc },
    { id: "nlsc_wms", label: "內政部國土測繪中心 NLSC（公開 WMS，免金鑰）", attribution: ATTR.nlsc },
    { id: "taipei", label: "臺北市政府都市發展局（公開 WMTS，免金鑰）", attribution: ATTR.taipei },
    { id: "taichung", label: "臺中市政府圖資雲（需上方 API Key）", attribution: ATTR.taichung },
    { id: "sentinel", label: "Copernicus Sentinel-2 衛星影像（需上方 Instance ID，縮放 10–14）", attribution: ATTR.sentinel },
    { id: "taoyuan", label: "桃園百年歷史地圖（中研院人社中心，免金鑰）", attribution: ATTR.taoyuan },
    { id: "newtaipei", label: "新北百年歷史地圖（中研院人社中心，免金鑰）", attribution: ATTR.newtaipei },
    { id: "hsinchu", label: "新竹百年歷史地圖（中研院人社中心，免金鑰）", attribution: ATTR.hsinchu },
  ];

  const layers = [];
  const add = (o) => layers.push(o);

  // ---------------------------------------------------------------------
  // 不分組的底圖
  // ---------------------------------------------------------------------
  // OSM 公用圖磚：一般瀏覽器端正常瀏覽用量，屬 Tile Usage Policy 允許的使用，跟
  // ARCHITECTURE.md 第 6 節講的「大量批次下載」完全不同。（早期這裡寫死
  // http://localhost:8081 的本機 osm-tile-server，部署到 HF Space 之後對外部訪客
  // 完全打不通，是一個真實 bug，不是刻意設計。）
  add({ id: "osm", group: null, label: "OpenStreetMap（一般地圖）", kind: "tile",
        template: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: ATTR.osm, maxZoom: 19 });
  // Esri World Imagery：Esri 官方發布的免金鑰公開衛星影像圖磚服務（ArcGIS REST
  // Services，一般網頁用途允許跨域引用，非爬取/逆向工程）。
  add({ id: "esri", group: null, label: "Esri World Imagery（衛星・免金鑰・z≤19）", kind: "tile",
        template: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution: ATTR.esri, maxZoom: 19 });
  // 本專案以台灣 OSM 自製的向量地形圖（Planetiler → OpenMapTiles 結構的 PMTiles，z0–14 全臺，z15 以上放大 z14 的向量）。
  // 暈渲與等高線即時由本站 DEM 圖磚（open-data/terrain-rgb）算出。PMTiles 走靜態路徑（HTTP Range），不扣 API Key 配額。
  // 色調可即時切換，樣式見 basemap/style.js；3D 模式（Cesium）不支援向量底圖，會改用 OSM。
  add({ id: "vector_topo", group: null, label: "向量地形圖（OSM・可切換色調）", kind: "vector",
        pmtiles: "basemap/taiwan.pmtiles", dem: "open-data/terrain-rgb/{z}/{x}/{y}.png", maxZoom: 19,
        attribution: `${ATTR.osm}、<a href="https://openmaptiles.org/" target="_blank" rel="noopener">© OpenMapTiles</a>；地形 Copernicus DEM GLO-30` });
  // Esri Wayback 歷史衛星影像：跟 nlsc_photobase_picker 一樣是「入口」而非實際圖層——
  // 選到它會在地圖右上角展開版本清單（日期／解析度／衛星來源），可用版本是 per-tile
  // 且隨 zoom 而異，所以清單是「目前地圖中心」的，移動地圖後會重查。實作見 wayback.js。
  add({ id: "wayback_picker", group: null,
        label: "🛰️ Esri Wayback 歷史衛星影像（點選展開版本清單）",
        title: "選取後地圖右上角會列出目前位置有哪些期別，含拍攝日期、解析度與衛星來源（2014 起，約 200 期）",
        kind: "wayback-picker" });
  // Google／Apple 不是圖磚樣板：Google 走官方 Maps JavaScript API + GoogleMutant，
  // Apple 走 MapKit JS 右側對照面板，都要使用者自備金鑰/token，程式在 index.html。
  add({ id: "google", group: null, label: "Google 衛星（z≤21・需上方 API Key）", kind: "custom" });
  add({ id: "apple", group: null, label: "Apple 衛星（右側對照面板・需上方 Token）", kind: "custom" });
  // 百度/騰訊/Bing：沒有官方金鑰可用，選項用 disabled 標記，瀏覽器原生就不能選，
  // 不會誤導成「已經可以用」。百度/騰訊不提供公開圖磚服務，官方唯一的公開存取方式
  // 是打對方沒有文件的內部圖磚 CDN，且需要偽造 Referer／輪換 User-Agent 才能繞過
  // 偵測——這是主動規避對方防護機制，不是單純技術限制，所以不接。
  add({ id: "bing", group: null, label: "Bing 衛星（尚未設定・需官方 API Key）", kind: "disabled",
        title: "需要 Bing Maps 官方 API Key，尚未設定" });
  add({ id: "baidu", group: null, label: "百度衛星（尚未設定・需官方 API Key）", kind: "disabled",
        title: "百度不提供公開圖磚服務，需官方 LBS API Key 並改走其官方 JS SDK 介接，尚未設定" });
  add({ id: "tencent", group: null, label: "騰訊衛星（尚未設定・需官方 API Key）", kind: "disabled",
        title: "騰訊不提供公開圖磚服務，需官方 LBS API Key 並改走其官方 JS SDK 介接，尚未設定" });

  // ---------------------------------------------------------------------
  // 中研院人社中心「臺灣百年歷史地圖 WMTS」（gis.sinica.edu.tw/tileserver/wmts，免金鑰）
  // GetCapabilities 確認：TileMatrixSet 是標準全球 GoogleMapsCompatible 格網，所以能
  // 直接疊在同一張地圖上，不需要像 gpkg 那樣另外換算 row/col（見 ARCHITECTURE.md
  // 第 10 節）。imgPrefix 內含各層自己的副檔名（"jpg" 而非 "jpeg"），是照抄該服務
  // GetCapabilities 宣告的 ResourceURL，不是猜的。86 個圖層只挑代表性的放進 demo。
  // ---------------------------------------------------------------------
  const SINICA = "https://gis.sinica.edu.tw/tileserver/file-exists.php?img=";
  [
    ["sinica_jm20k_1904", "JM20K_1904-jpg", "日治臺灣堡圖 1904（明治版・1:20,000）", { year: 1904, label: "日治臺灣堡圖" }],
    ["sinica_jm200k_1944", "JM200K_1944-png", "日治二十萬分一帝國圖 1944（聯勤翻印版）", { year: 1944, label: "日治帝國圖" }],
    ["sinica_ams250k_1944", "AMS250K_1944-png", "美軍二十五萬分一地形圖 1944", { year: 1944, label: "美軍二十五萬分一地形圖" }],
    ["sinica_corona_1966", "Taiwan_Corona_1966-png", "Corona 衛星影像 1966（美國解密偵察衛星）", { year: 1966, label: "Corona 衛星影像" }],
    ["sinica_corona_1969", "Taiwan_Corona_1969-png", "Corona 衛星影像 1969（美國解密偵察衛星）", { year: 1969, label: "Corona 衛星影像" }],
    ["sinica_tm50k_1954", "TM50K_1954-png", "臺灣地形圖 1954", { year: 1954, label: "臺灣地形圖" }],
    ["sinica_tm25k_2003", "TM25K_2003-jpg", "臺灣經建4版地形圖 2003（1:25,000）", { year: 2003, label: "臺灣經建4版地形圖", rank: 2 }],
    ["sinica_abm", "abm-png", "乾隆臺灣番界（柯志明・陳兆勇考證繪製）", null],

    // 以下 16 個是地質調查及礦業管理中心「土壤液化潛勢查詢系統」（liquefaction.gsmma.gov.tw）
    // 網站自己引用的底圖清單（_agMap_DEF.js 的 baseMaps），跟上面是同一個中研院圖磚服務，
    // URL 格式完全相同。標題文字照抄該網站選單。刻意**不**加 slideshow：加了會悄悄改變
    // ndu60／我愛我家兩個主題頁的歷史影像簡報清單與順序。
    // 這個服務對任何縮放級都會即時重採樣（實測 1899 年 1:40 萬的圖在 z20 也回得出圖，
    // 只是很糊），所以不能用「有沒有回圖」判斷原生解析度，也不設 maxNativeZoom；只有下面
    // 兩個實測有真正的邊界：1924 版在 z17 起回固定 197 bytes 空白佔位圖；1942 版只涵蓋
    // 高雄一帶（其他地方回固定 936 bytes 佔位圖，z17 起回 HTTP 500），選了看到空白是正常的。
    ["sinica_am50k_1944", "AM50K_1944-png", "美軍地形圖 1944", null],
    ["sinica_amcity_1945", "AMCityPlan_1945-png", "美軍繪製臺灣城市地圖 1945", null],
    ["sinica_jm400k_1899", "JM400K_1899-png", "日治臺灣全圖 1899", null],
    ["sinica_jm100k_1905", "JM100K_1905-png", "日治臺灣圖 1905", null],
    ["sinica_jm50k_1916", "JM50K_1916-jpg", "日治蕃地地形圖 1916", null],
    ["sinica_jm50k_1920", "JM50K_1920-png", "日治地形圖 1920（總督府土木局）", null],
    ["sinica_jm20k_1921", "JM20K_1921-jpg", "日治臺灣堡圖 1921（大正版）", null],
    ["sinica_jm25k_1921", "JM25K_1921-png", "日治地形圖 1921", null],
    ["sinica_jm50k_1924", "JM50K_1924_new-png", "日治地形圖 1924（陸地測量部）", null, { maxNativeZoom: 16 }],
    ["sinica_jm200k_1932", "JM200K_1932-png", "二十萬分一帝國圖 1932（臺灣部分）", null],
    ["sinica_jm300k_1934", "JM300K_1934-jpg", "日治臺灣全圖 1934（第三版）", null],
    ["sinica_jm300k_1939", "JM300K_1939-png", "日治臺灣全圖 1939（第五版）", null],
    ["sinica_jm25k_1942", "JM25K_1942-png", "日治二萬五千分之一地形圖 1942（昭和修正版・僅高雄一帶有圖）", null, { maxNativeZoom: 16 }],
    ["sinica_tm50k_1956", "TM50K_1956-jpg", "臺灣地形圖 1956", null],
    ["sinica_tm100k_1987", "TM100K_1987-png", "臺灣地形圖 1987", null],
    // 上河文化《台灣地理人文全覽圖》北島第五版（1:50,000；圖層代號的 2017 是中研院的命名）：2026-10 新上架，範圍約北緯 23.37° 以北。
    // 原生到 z15，z16 起回固定 197 bytes 空白佔位圖，所以設 maxNativeZoom: 15 放大 z15 圖磚。
    ["sinica_sunriver_n_2017", "Sunriver_50K_N_2017-png", "上河文化 台灣地理人文全覽圖・北島 第五版（1:50,000）", null,
      { maxNativeZoom: 15, attribution: "上河文化《台灣地理人文全覽圖》北島 第五版；" + ATTR.sinica }],
  ].forEach(([id, prefix, label, show, extra]) =>
    add({ id, group: "sinica", label, kind: "tile", template: `${SINICA}${prefix}-{z}-{x}-{y}`,
          minZoom: 6, maxZoom: 18, ...extra, slideshow: show && { ...show, scope: "nationwide" } })
  );
  // 美軍航照 1945/6/17（臺北）：同一個中研院，但走 /taipei/ 這條獨立路徑，不是 tileserver。
  add({ id: "sinica_taipei_aerial_1945", group: "sinica", label: "美軍航照影像 1945/6/17（臺北）", kind: "tile",
        template: "https://gis.sinica.edu.tw/taipei/file-exists.php?img=Taipei_aerialphoto_1945-jpg-{z}-{x}-{y}",
        minZoom: 6, maxZoom: 18 });

  // ---------------------------------------------------------------------
  // 內政部國土測繪中心 NLSC 公開 WMTS（wmts.nlsc.gov.tw/wmts，免金鑰）
  // GetCapabilities 確認：GoogleMapsCompatible 全球格網，CORS 全開，可直接疊圖。
  // RESTful 路徑順序是 {TileMatrix}/{TileRow}/{TileCol}（z/row/col），對應 Leaflet
  // 樣板要寫成 {z}/{y}/{x}（跟 Esri 那條同順序，不是打錯）。圖層代碼（TOPO50K_113、
  // PHOTO2025）每年會新增當年度版本，這裡先固定選目前最新的。
  // ---------------------------------------------------------------------
  const NLSC = "https://wmts.nlsc.gov.tw/wmts";
  add({ id: "nlsc_emap", group: "nlsc", label: "臺灣通用電子地圖", kind: "tile",
        template: `${NLSC}/EMAP/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 18 });
  add({ id: "nlsc_topo50k", group: "nlsc", label: "1/50000 地形圖 113年版", kind: "tile",
        template: `${NLSC}/TOPO50K_113/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 18 });
  add({ id: "nlsc_photo", group: "nlsc", label: "正射影像圖 114年版（航照）", kind: "tile",
        template: `${NLSC}/PHOTO2025/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 19,
        slideshow: { year: 2025, label: "NLSC 最新正射影像", scope: "nationwide", rank: 2 } });

  // 另外三個國土測繪中心底圖，來自地調中心液化潛勢查詢系統的底圖選單（同一個
  // wmts.nlsc.gov.tw 服務，路徑格式跟上面完全一樣）：EMAP01 是電子地圖的灰階版
  // （疊專題圖時底圖不搶色）、PHOTO2 是通用版正射影像、PHOTO_MIX 是正射影像加註記混合。
  // 跟 PHOTO2025 的關係沒有查證（可能是不同期或不同版本），所以標題沒有寫年度。
  add({ id: "nlsc_emap_gray", group: "nlsc", label: "臺灣通用電子地圖（灰階）", kind: "tile",
        template: `${NLSC}/EMAP01/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 18 });
  add({ id: "nlsc_photo2", group: "nlsc", label: "通用版正射影像圖", kind: "tile",
        template: `${NLSC}/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 19 });
  add({ id: "nlsc_photo_mix", group: "nlsc", label: "通用版正射影像圖（混合）", kind: "tile",
        template: `${NLSC}/PHOTO_MIX/default/GoogleMapsCompatible/{z}/{y}/{x}`, minZoom: 6, maxZoom: 19 });

  // 下拉選單裡放一個「進入年代選擇」的入口，不是真的圖層——選到它會在圖層
  // 面板裡展開一條年代滑桿（見 index.html 的 photobase picker），選定年代後
  // 才真正切換成下面那 47 個實際圖層之一。原本是 47 個個別選項塞滿一個
  // optgroup，改成這樣是使用者明確要求的（下拉選單太長不好選）。
  //
  // 使用者實測發現這一行改版後太不顯眼：以前是 47 個年度直接列在選單裡，
  // 一打開就看得到；現在只剩一行，看起來像個普通圖層，選單裡完全看不出
  // 「選我會展開別的東西」。label 前面加 🎚️ 圖示、文字改成明講「點選展開」，
  // 再加一個滑鼠停留才看得到的 title 提示，兩層線索都給。
  add({ id: "nlsc_photobase_picker", group: "nlsc",
        label: "🎚️ 1/5000像片基本圖（點選展開年代滑桿，歷年版本）",
        title: "選取後請到左側「圖層」面板，會出現一條年代滑桿可以挑選民國65～114年的版本",
        kind: "photobase-picker" });

  // NLSC「1/5000像片基本圖」歷年版本（TOPO05KPHOTO_{民國年}）。GetCapabilities 列出
  // 47 個年度（民國65年起，缺 77/82/85——官方本來就沒有對應圖層，不是漏抓）。每年是全國
  // 單一圖層識別碼，但**同一年度在不同縣市的實際覆蓋範圍差異很大**（真實航測計畫分區域
  // 逐年進行）：實測台南在 65、100 年有真實圖磚，75/95/105/111 年同一點卻是空白。
  // NLSC 的空白圖磚固定回傳 HTTP 200 + 854 bytes 全白 PNG（不是 404），所以選了某年度
  // 卻看到空白，通常代表該年度沒涵蓋這個區域，不是圖層設定錯誤。
  //
  // 這 47 筆刻意不放進任何 `group`（也標 `hiddenFromMenu`），不會出現在下拉選單裡
  // ——但仍然是 MAP_LAYERS.layers 的正常成員，一樣會被建成 SIMPLE_BASE_LAYERS
  // 供上面那個 picker 切換使用，slideshowCandidates() 也照樣抓得到（ndu60/
  // 我愛我家的歷史影像簡報沒有受影響）。分享連結 `layer=nlsc_photobase_100`
  // 這種舊格式還是要能還原，index.html 的分享還原邏輯有特別處理這個前綴。
  ["065", "066", "067", "068", "069", "070", "071", "072", "073", "074",
   "075", "076", "078", "079", "080", "081", "083", "084", "086", "087",
   "088", "089", "090", "091", "092", "093", "094", "095", "096", "097",
   "098", "099", "100", "101", "102", "103", "104", "105", "106", "107",
   "108", "109", "110", "111", "112", "113", "114"].forEach((roc) => {
    const n = parseInt(roc, 10);
    add({ id: `nlsc_photobase_${roc}`, group: null, hiddenFromMenu: true,
          label: `1/5000像片基本圖 民國${n}年（西元${1911 + n}）`,
          kind: "tile", template: `${NLSC}/TOPO05KPHOTO_${roc}/default/GoogleMapsCompatible/{z}/{y}/{x}`,
          minZoom: 6, maxZoom: 18,
          slideshow: { year: 1911 + n, label: `NLSC 1/5000像片基本圖 民國${n}年`, scope: "nationwide", rank: 1 } });
  });

  // 同一個 NLSC 的另一個服務（wms.nlsc.gov.tw/wms，免金鑰、CORS 全開）是傳統 OGC WMS，
  // 沒有固定格網、依請求 bbox 現算圖面，所以走 L.tileLayer.wms()。GetCapabilities 有 67 個
  // 圖層，這裡挑三個跟國土利用/地形分析最相關的（皆最新一期）。
  const wms = (id, label, layer, minZoom) =>
    add({ id, group: "nlsc_wms", label, kind: "wms", template: "https://wms.nlsc.gov.tw/wms",
          wms: { layers: layer, format: "image/png", transparent: true }, minZoom, maxZoom: 18 });
  wms("nlsc_luimap", "國土利用現況調查成果圖", "LUIMAP", 6);
  wms("nlsc_slope", "坡度圖-7級（2010-2015）", "MOI_SLOPEP_LV7_2", 6);
  wms("nlsc_contour", "等高線圖（2010-2015）", "MOI_CONTOUR_2", 10);

  // ---------------------------------------------------------------------
  // 臺北市政府都市發展局「歷史圖資展示系統」（historygis.udd.gov.taipei，免金鑰）
  // 48+ 圖層（民國34年含轟炸前/後對照，到 114 年逐年航測）。挑最新四年 + 1945 對照組。
  // 較新的圖層走 ArcGIS REST 代理路徑（無 CORS header，但 <img> 顯示不需要），較舊的
  // （108 年以前建的）走 /UDDWMTS/tile/ 路徑（有開 CORS）。
  // ---------------------------------------------------------------------
  const UDD = "https://www.historygis.udd.gov.taipei";
  const uddArc = (id, label, year) =>
    add({ id, group: "taipei", label, kind: "tile",
          template: `${UDD}/arcgis/rest/services/Aerial/Ortho_${year}/MapServer/WMTS/tile/1.0.0/Aerial_Ortho_${year}/default/GoogleMapsCompatible/{z}/{y}/{x}`,
          minZoom: 10, maxZoom: 19 });
  uddArc("taipei_udd_aerial2025", "航測影像（114年・2025年）", 2025);
  uddArc("taipei_udd_aerial2024", "航測影像（113年・2024年）", 2024);
  uddArc("taipei_udd_aerial2023", "航測影像（112年・2023年）", 2023);
  uddArc("taipei_udd_aerial2021", "航測影像（110年・2021年）", 2021);
  add({ id: "taipei_udd_1945b", group: "taipei", label: "34年航測影像（民國34年8月・轟炸前）", kind: "tile",
        template: `${UDD}/UDDWMTS/tile/Image_Image_1945_B/{z}/{y}/{x}`, minZoom: 10, maxZoom: 16 });
  add({ id: "taipei_udd_1945a", group: "taipei", label: "34年航測影像（民國34年8月・轟炸後）", kind: "tile",
        template: `${UDD}/UDDWMTS/tile/Image_Image_1945_A/{z}/{y}/{x}`, minZoom: 10, maxZoom: 16 });

  // ---------------------------------------------------------------------
  // 臺中市政府圖資雲（giscloud.taichung.gov.tw）。官方介接：服務網址是
  // .../embedmap/wmtsproxy/{APIKEY}?...，金鑰需以市府 e 化公務帳號或圖資雲會員申請，
  // 嵌在**路徑**裡（不是 query 參數）。金鑰綁定申請人身分，不能寫進這個公開檔案（會外洩
  // 進 git 歷史、也會烘焙進公開的 HF Space），所以樣板用 {key} 占位，由頁面在執行時
  // 用使用者貼在輸入框的值替換（存 localStorage，不進版本庫）。
  // 底層 GeoWebCache、KVP 編碼；TileMatrixSet「GISMAP3857」是標準 Web Mercator，
  // 但 TileMatrix 識別碼要寫成 "MAP3857_{z}"（不是純數字），回應 Content-Type 實際是
  // image/jpeg（跟 FORMAT=image/png 不符，已實測，不是打錯）。CORS 全開。
  // maxZoom 實測校正：GetCapabilities 宣稱到 23 級，但影像資料 z=16 以上就回傳全空白
  // 圖磚（HTTP 200、固定 1588 bytes，真實圖磚動輒 2~3 萬 bytes），台中車站/市政府兩處
  // 都驗證過，故保守設 16。
  // ---------------------------------------------------------------------
  const TAICHUNG = "https://giscloud.taichung.gov.tw/embedmap/wmtsproxy/{key}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=";
  const TAICHUNG_TAIL = "&STYLE=&TILEMATRIXSET=GISMAP3857&TILEMATRIX=MAP3857_{z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png";
  add({ id: "taichung_ortho_new", group: "taichung", label: "航照+福衛影像（新・含7500/1500比例尺）", kind: "keyed",
        template: `${TAICHUNG}TC:GISORTHO${TAICHUNG_TAIL}`, minZoom: 8, maxZoom: 16 });
  add({ id: "taichung_ortho_2017", group: "taichung", label: "航照+福衛影像（2017年版）", kind: "keyed",
        template: `${TAICHUNG}TC:GISORTHO_2017${TAICHUNG_TAIL}`, minZoom: 8, maxZoom: 16 });

  // ---------------------------------------------------------------------
  // Copernicus Data Space 的 Sentinel Hub WMTS（sh.dataspace.copernicus.eu/ogc/wmts/{instance}）。
  // instance ID 等同存取憑證且額度綁在申請人帳號（一般使用者每月 10,000 請求、每分鐘 300），
  // 所以跟臺中金鑰一樣不寫進原始碼，由使用者在頁面輸入（存 localStorage）。不需 OAuth token，
  // CORS 全開（access-control-allow-origin: *），瀏覽器可直連。以下皆實測（台北、2026/8–9）：
  // - 格網用 PopularWebMercator512 的 retina 用法：每張 512 像素圖磚縮成 256 CSS 像素顯示
  //   （Leaflet zoomOffset: 1，請求的 matrix 編號 = 縮放級 + 1；512 版 matrix 編號 N 每軸
  //   2^(N-1) 張）。原因：伺服器蓋在每張圖磚左下角的 Copernicus 浮水印固定約 155 像素寬，
  //   在 256 像素圖磚上佔掉大半個角落；512 像素圖磚縮成 256 CSS 像素後浮水印變一半大、
  //   影像也更銳利。用 image/jpeg：同一張 512 圖磚 PNG 約 670 KB、JPEG 約 110 KB（實測），
  //   影像本身沒有透明需求。PopularWebMercator256 是同服務的標準 256 像素版。
  // - 資料為 10 公尺解析度，z14 約 9.5 m/像素，所以 maxNativeZoom 14，再放大只是拉伸。
  // - TIME 參數是 ISO8601 區間；區間內同一地點取最新一張，雲多時範圍拉長較好。
  // ---------------------------------------------------------------------
  const SENTINEL =
    "https://sh.dataspace.copernicus.eu/ogc/wmts/{instance}?service=WMTS&request=GetTile&version=1.0.0&style=default&format=image/jpeg&tilematrixset=PopularWebMercator512&tilematrix={z}&tilerow={y}&tilecol={x}&time={time}&layer=";
  add({ id: "sentinel_true_color", group: "sentinel", label: "Sentinel-2 真彩色", kind: "sentinel",
        template: `${SENTINEL}TRUE_COLOR`, minZoom: 10, maxNativeZoom: 14, maxZoom: 18, zoomOffset: 1 });
  add({ id: "sentinel_false_color", group: "sentinel", label: "Sentinel-2 假色（植被呈紅色）", kind: "sentinel",
        template: `${SENTINEL}FALSE_COLOR`, minZoom: 10, maxNativeZoom: 14, maxZoom: 18, zoomOffset: 1 });
  add({ id: "sentinel_ndvi", group: "sentinel", label: "Sentinel-2 NDVI（植生指數）", kind: "sentinel",
        template: `${SENTINEL}NDVI`, minZoom: 10, maxNativeZoom: 14, maxZoom: 18, zoomOffset: 1 });

  // ---------------------------------------------------------------------
  // 中研院「桃園/新北百年歷史地圖」（gis.sinica.edu.tw/taoyuan、/newtaipei，免金鑰）
  // 桃園 38、新北 24 個圖層，但每個識別碼是**一張獨立的歷史地圖/航照掃描件**，只涵蓋
  // 掃描原圖那一小塊範圍，不是縣市無縫圖層；這裡各挑涵蓋較大、年代分散的代表。
  // URL 樣板是 file-exists.php?img={圖層}-{格式}-{z}-{x}-{y}；部分圖層（1920、2017）
  // 實際會 302 轉址到 ArcGIS compact cache，<img> 會自動跟隨。
  // maxNativeZoom 是逐一實測（比對真實內容 vs. 固定 196/198 bytes 的空白/404 佔位圖）
  // 校正過的原生解析度上限；maxZoom 刻意設高（19）——如果 maxZoom 剛好卡在實測上限，
  // 使用者在更深的縮放下切過來，Leaflet 會對超過 maxZoom 的圖層完全不繪製；用
  // maxNativeZoom 才能繼續顯示（放大沿用最後一級圖磚）又不會去要不存在的更高解析度圖磚。
  // ---------------------------------------------------------------------
  const TAOYUAN = "https://gis.sinica.edu.tw/taoyuan/file-exists.php?img=";
  const NEWTAIPEI = "https://gis.sinica.edu.tw/newtaipei/file-exists.php?img=";
  const hist = (id, group, base, img, label, minZoom, nativeZoom, show) =>
    add({ id, group, label, kind: "tile", template: `${base}${img}-png-{z}-{x}-{y}`,
          minZoom, maxZoom: 19, maxNativeZoom: nativeZoom, slideshow: show || undefined });
  hist("taoyuan_1920_topomap", "taoyuan", TAOYUAN, "Taoyuan_topomap_2.5K_1920", "桃園水利組合區域地形圖（大正9年・1920）", 9, 17,
       { year: 1920, label: "桃園水利組合區域地形圖", scope: "taoyuan" });
  hist("taoyuan_1973_topomap", "taoyuan", TAOYUAN, "Taoyuan_Taoyuan_1973", "桃園市區地形圖（民國62年・1973）", 9, 17,
       { year: 1973, label: "桃園市區地形圖", scope: "taoyuan" });
  hist("taoyuan_1987_ortho", "taoyuan", TAOYUAN, "Taoyuan_5K_1987", "桃園市區像片基本圖第二版（民國76年・1987）", 11, 17);
  hist("taoyuan_2017_ortho", "taoyuan", TAOYUAN, "Taoyuan_aerialphoto_2017", "桃園水利會正射影像（2017）", 9, 17,
       { year: 2017, label: "桃園水利會正射影像", scope: "taoyuan", rank: 2 });
  hist("newtaipei_1942_topo", "newtaipei", NEWTAIPEI, "NewTaipei_150K_1942", "臺北州管內圖（昭和17年・1942）", 9, 15,
       { year: 1942, label: "臺北州管內圖", scope: "newtaipei" });
  hist("newtaipei_1964_topo", "newtaipei", NEWTAIPEI, "NewTaipei_100K_1964", "台北縣地圖（民國53年・1964）", 9, 15,
       { year: 1964, label: "台北縣地圖", scope: "newtaipei" });
  hist("newtaipei_2007_admin", "newtaipei", NEWTAIPEI, "NewTaipei_65K_2007", "台北縣行政區域圖（民國96年・2007）", 9, 16,
       { year: 2007, label: "台北縣行政區域圖", scope: "newtaipei", rank: 2 });
  hist("newtaipei_1970s_banqiao", "newtaipei", NEWTAIPEI, "Banqiao_3K_1970s_A", "板橋江子翠都市計畫地形測量原圖（民國60年代）", 11, 17);

  // 中研院「新竹百年歷史地圖」（gis.sinica.edu.tw/hsinchu，免金鑰）。同一種服務格式；這裡收 2025 年中研院公告
  // 新增的 6 幅（2025/4/15：1953 都市計畫圖與 4 筆 1970 年代地形測量原圖；2025/7/30：頭前溪河川地形圖 1938）。
  // maxNativeZoom 取自該服務 showwmts 頁的 metadata（maxzoom），並實測過：超過原生級別回固定 198 bytes 佔位圖。
  // 每個圖層只涵蓋一小塊範圍（bounds 見各列註解），範圍外是固定 800 bytes 空白圖磚。
  // 新竹縣市的圖層只放進 "hsinchu" scope，ndu60／我愛我家的候選清單不受影響（它們不納入這個 scope）。
  const HSINCHU = "https://gis.sinica.edu.tw/hsinchu/file-exists.php?img=";
  // bounds: 120.9449–121.0299E, 24.7774–24.8265N
  hist("hsinchu_1953_plan", "hsinchu", HSINCHU, "Hsinchu_6K_1953", "新竹都市計畫圖（1953・1/6,000）", 9, 17,
       { year: 1953, label: "新竹都市計畫圖", scope: "hsinchu" });
  // bounds: 120.9727–121.0212E, 24.7685–24.8039N
  hist("hsinchu_1970_industrial", "hsinchu", HSINCHU, "Hsinchu_3K_1970", "新竹工業區都市計畫地形測量原圖（1970・1/3,000）", 9, 19,
       { year: 1970, label: "新竹工業區地形測量原圖", scope: "hsinchu" });
  // bounds: 120.9493–120.9793E, 24.7840–24.8266N
  hist("hsinchu_1973_detail", "hsinchu", HSINCHU, "Hsinchu_3K_1973", "新竹市細部計畫都市計畫地形測量原圖（1973・1/3,000）", 9, 19,
       { year: 1973, label: "新竹市細部計畫地形測量原圖", scope: "hsinchu" });
  // bounds: 120.9787–121.0394E, 24.7625–24.8028N
  hist("hsinchu_1975_interchange", "hsinchu", HSINCHU, "Hsinchu_3K_1975", "新竹段高速公路交流道都市計畫地形測量原圖（1975・1/3,000）", 9, 19,
       { year: 1975, label: "新竹交流道地形測量原圖", scope: "hsinchu" });
  // bounds: 120.9449–121.0049E, 24.7767–24.8012N
  hist("hsinchu_1977_unplanned", "hsinchu", HSINCHU, "Hsinchu_3K_1977", "新竹市未設定區都市計畫地形測量原圖（1977・1/3,000）", 9, 19,
       { year: 1977, label: "新竹市未設定區地形測量原圖", scope: "hsinchu" });
  // bounds: 120.9082–121.2152E, 24.6884–24.8810N（403 幅拼接，涵蓋新竹市、竹北、新埔、關西、竹東、芎林、橫山局部）
  hist("hsinchu_1938_touchien", "hsinchu", HSINCHU, "Touchien_River_2.5K_1938", "頭前溪河川地形圖（1938・1/2,500）", 9, 18,
       { year: 1938, label: "頭前溪河川地形圖", scope: "hsinchu" });

  // ---------------------------------------------------------------------
  // 疊圖（勾選顯示，不取代底圖）。兩組各自對應左側一個面板；id 在兩組之間不可重名
  // （分享連結的 ov= 參數把兩組的勾選狀態合在同一個逗號清單裡）。
  // ---------------------------------------------------------------------
  const overlayGroups = [
    {
      id: "cameras", panelId: "cameras-layers-box", title: "即時攝影機",
      attribution: "高公局、公路局與各直轄市／縣市交通局公開的路況 CCTV（scripts/make_presale_cameras.py）",
      // 點位來自伺服器 /api/v1/cameras?bbox=（需 client 角色金鑰），由 static/index.html 的
      // 「即時攝影機」區塊依目前畫面查詢；點選點位在彈出視窗播放即時影像（MJPEG／HLS／機關播放頁）。
      overlays: [
        { id: "live_cams", label: "路況即時攝影機", hint: "（放大到 11 級以上顯示，點選看即時影像）", kind: "cameras" },
      ],
    },
    {
      id: "osm", panelId: "osm-layers-box", title: "OSM 圖資疊圖", attribution: "© OpenStreetMap contributors（ODbL）",
      // scripts/extract_osm_layers.py 從 Geofabrik 的 taiwan-latest.osm.pbf 抽出、
      // scripts/gpkg_to_theme_geojson.py 轉成 static/osm-layers/{id}.geojson。向量 GeoJSON，
      // 勾選才抓取。ODbL 衍生資料庫條款要求附出處，見面板固定顯示的 attribution。
      overlays: [
        { id: "railways", label: "鐵路", color: "#a855f7", kind: "geojson", file: "osm-layers/railways.geojson" },
        { id: "highways", label: "主要道路", hint: "（檔案較大，載入較慢）", color: "#f97316", kind: "geojson", file: "osm-layers/highways.geojson" },
        { id: "hospitals", label: "醫院", color: "#ef4444", kind: "geojson", file: "osm-layers/hospitals.geojson" },
        { id: "schools", label: "學校", color: "#3b82f6", kind: "geojson", file: "osm-layers/schools.geojson" },
        { id: "police", label: "警察局", color: "#1e3a8a", kind: "geojson", file: "osm-layers/police.geojson" },
        { id: "fire_stations", label: "消防局", color: "#ea580c", kind: "geojson", file: "osm-layers/fire_stations.geojson" },
        { id: "stations", label: "車站", color: "#10b981", kind: "geojson", file: "osm-layers/stations.geojson" },
        { id: "airports", label: "機場", color: "#8b5cf6", kind: "geojson", file: "osm-layers/airports.geojson" },
      ],
    },
    {
      id: "disaster", panelId: "disaster-layers-box", title: "防災資訊疊圖", attribution: "內政部國土測繪中心 NLSC（WMTS）",
      // 借鏡香港 CSDI 圖庫的「全方位防災地圖」（香港紅十字會）。NLSC 同一個 WMTS 服務裡的
      // 透明點陣疊圖，皆實測過台北車站一帶有真實圖磚。土壤液化潛勢是不透明色塊，疊上去會
      // 蓋住底圖，所以壓成半透明。GeoSensitive2（地質敏感區）在台北回傳 0 bytes，未收錄。
      overlays: [
        { id: "aed", label: "AED", panelLabel: "AED 自動體外電擊器", kind: "nlsc-tile", layer: "AED", opacity: 1 },
        { id: "shelters", label: "避難收容處所", kind: "nlsc-tile", layer: "SHELTERS", opacity: 1 },
        { id: "coolspots", label: "涼適點（避暑）", hint: "（環境部 Cool map，1.2 萬處，點開看開放時間與設施）", color: "#0284c7", kind: "geojson", file: "open-data/homecheck/coolspots.geojson" },
        { id: "fireplug", label: "消防栓", kind: "nlsc-tile", layer: "fireplug", opacity: 1 },
        { id: "liquefaction", label: "土壤液化潛勢", hint: "（半透明）", kind: "nlsc-tile", layer: "SoilLiquefaction2", opacity: 0.5 },
      ],
    },
    {
      id: "cadastre", panelId: "cadastre-layers-box", title: "地籍疊圖", attribution: "內政部國土測繪中心 NLSC（WMTS）",
      // 實測（台北信義區、萬華一帶）：LAND_OPENDATA 是宗地色塊加界線，z19 可見地號（如 547、550）；
      // LANDSECT 只有段界線與段名（z17 才有「信義段」文字，z19 只剩一條線），不是地號圖；
      // LandOffice 兩張測試圖磚皆空白，未收錄。此為開放資料，僅供參考，不能取代地政機關謄本。
      overlays: [
        { id: "landparcel", label: "地籍（含地號）", hint: "（放大到 19 級以上才看得到地號）", kind: "nlsc-tile", layer: "LAND_OPENDATA", opacity: 0.6, maxNativeZoom: 20 },
        { id: "landsect", label: "段界（地段）", kind: "nlsc-tile", layer: "LANDSECT", opacity: 1 },
      ],
    },
    {
      id: "geo", panelId: "geo-layers-box", title: "地質與液化（地質調查及礦業管理中心）",
      // 來源：經濟部地質調查及礦業管理中心「土壤液化潛勢查詢系統」
      // （liquefaction.gsmma.gov.tw），經濟部 2026 年新聞稿宣布更新部分縣市的潛勢圖。
      // 這個系統自己的 agMap_DEF.js 就是圖層定義表，
      // 下面的網址、圖層編號、透明度都是照它抄的，並逐一實測過：
      // - 官方 `liquefaction.gsmma.gov.tw/wmts/` 只回 GetCapabilities，用 KVP/RESTful 取圖磚
      //   都不行；真正圖磚在 Capabilities 公告的 gis.liquid.net.tw（ArcGIS）主機。
      // - 網站 JS 把 2026 圖層寫成 `Soil_cgs_2026/.../P04032_Soil_cgs/...`（圖層名沒有 2026），
      //   跟 Capabilities 的 `P04032_Soil_cgs_2026` 不一致，實測兩種寫法回傳位元組完全相同
      //   的圖磚，所以是命名瑕疵、不影響使用，這裡用 Capabilities 的寫法。
      // - 液化潛勢圖磚不透明（紅/黃/綠色塊），不壓成半透明會整片蓋住底圖。
      // - 各圖層涵蓋範圍不同（來自各服務 GetCapabilities 的範圍宣告，見各 hint）。
      // 以上都是政府開放服務，但**沒有查證各自的使用條款**。
      attribution: "經濟部地質調查及礦業管理中心（liquefaction.gsmma.gov.tw）；圖磚來自 gis.liquid.net.tw",
      overlays: [
        { id: "liq2026", label: "土壤液化潛勢（2026 更新版）", hint: "（紅＝高、黃＝中、綠＝低；z16 以後沒有更細的資料）",
          kind: "tile-overlay", opacity: 0.6, maxNativeZoom: 16,
          template: "https://gis.liquid.net.tw/arcgis/rest/services/P04032/Soil_cgs_2026/MapServer/WMTS/tile/1.0.0/P04032_Soil_cgs_2026/default/GoogleMapsCompatible/{z}/{y}/{x}.png" },
        { id: "liq_old", label: "土壤液化潛勢（更新前舊版）", hint: "（實測宜蘭一帶圖磚近乎空白，可與新版切換比較）",
          kind: "tile-overlay", opacity: 0.6, maxNativeZoom: 16,
          template: "https://gis.liquid.net.tw/arcgis/rest/services/P04032/Soil_cgs/MapServer/WMTS/tile/1.0.0/P04032_Soil_cgs/default/GoogleMapsCompatible/{z}/{y}/{x}.png" },
        { id: "ancient", label: "古地圖判識（舊河道、埤塘、溼地）", hint: "（只涵蓋約 22.9–25.1°N 的西部）",
          kind: "tile-overlay", opacity: 0.8, template: "https://gis.liquid.net.tw/arcgis/services/CGS_ancient/MapServer/WMSServer",
          wms: { layers: "0,1", format: "image/png", transparent: true, version: "1.3.0" } },
        // 軟弱土層：同一個 WMS 服務的 6 個子圖層（黏土/砂土 × 三個深度），做成「一個勾選框＋
        // 一個下拉」而不是 6 個勾選框。REST 子圖層編號跟 WMS 相反（網站註解也提醒以
        // GetCapabilities 的 Name 為準）：0–5 公尺黏土=5、砂土=4；5–10 黏土=3、砂土=2；
        // 10–20 黏土=1、砂土=0。色階是分級（數值定義見官網圖例，這裡沒有查證）。
        { id: "weaksoil", label: "軟弱土層", hint: "（只涵蓋北部約 24.6–25.3°N；色階＝分級，定義見官網圖例）",
          kind: "wms-select", opacity: 0.65, template: "https://gis.liquid.net.tw/arcgis/services/P04032/weaksoil/MapServer/WMSServer",
          wms: { format: "image/png", transparent: true, version: "1.1.1" },
          options: [
            { id: "5", label: "地下 0–5 公尺・軟弱黏土" }, { id: "4", label: "地下 0–5 公尺・疏鬆砂土" },
            { id: "3", label: "地下 5–10 公尺・軟弱黏土" }, { id: "2", label: "地下 5–10 公尺・疏鬆砂土" },
            { id: "1", label: "地下 10–20 公尺・軟弱黏土" }, { id: "0", label: "地下 10–20 公尺・疏鬆砂土" },
          ] },
        { id: "liq_sites", label: "土壤液化監測場址（11 站）", hint: "（點開有各站監測資料查詢連結）",
          color: "#f97316", kind: "geojson", file: "open-data/liquefaction_monitoring_sites.geojson" },
      ],
    },
    {
      id: "miaoli_age", panelId: "miaoli-age-box", title: "苗栗縣建物建築完成年（栗智網，西元）",
      // 來源：苗栗縣政府地政處「栗智網」（ailand.miaoli.gov.tw/gis/）「建物屋齡模擬」所用的公開 ArcGIS 服務
      // .../rest/services/Dynamic/DD16/MapServer/0（約 21 萬個建物點，DD16Y＝建築完成民國年，+1911 換西元）。
      // 服務沒開 CORS，所以由 scripts/make_miaoli_building_age.py 離線抓成快照（5.4 MB，要更新須重跑）。
      // 無完成年（DD16Y=0）的 2 點略過。使用條款未查證。
      attribution: "苗栗縣政府地政處 栗智網（ailand.miaoli.gov.tw）建物建築完成年度，離線快照",
      legend: [
        ["建築完成年（西元）", [["≤1970", "8c2d04"], ["1971–1980", "d94801"], ["1981–1990", "f16913"], ["1991–2000", "fd8d3c"], ["2001–2010", "9ecae1"], ["2011–2020", "4292c6"], [">2020", "08306b"]]],
      ],
      overlays: [
        { id: "ml_building_age", label: "苗栗縣建物建築完成年（20.96 萬點，放大看較清楚）", hint: "（點開看完成年）", color: "#4292c6", kind: "geojson", file: "open-data/miaoli_building_age.json" },
      ],
    },
    {
      id: "tw_house_age", panelId: "tw-house-age-box", title: "全臺住宅屋齡（鄉鎮市區填色，房屋稅籍）",
      // 來源：內政部社會經濟資料服務平台 SEGIS「行政區房屋稅籍住宅類數量依屋齡區分統計_鄉鎮市區」（國土管理署，
      // 每季；本快照為 114 年第 4 季，即 2025 年底），GeoJSON(WGS84) 已含界線與統計值，363 個鄉鎮市區。
      // scripts/make_tw_house_age.py 轉成精簡 GeoJSON；新竹市、嘉義市因資料來源為單一地政事務所，沒有鄉鎮市區別，空白。
      // 屋齡是房屋稅籍「住宅類」登記，與使用執照年份可能有出入。落成年約＝2025 − 屋齡（彈出視窗已換算）。
      attribution: "內政部國土管理署／社會經濟資料服務平台（SEGIS）房屋稅籍住宅類屋齡統計，114Y4S 離線快照",
      overlays: [
        { id: "tw_age_avg", label: "住宅平均屋齡（鄉鎮市區）", hint: "（藍＝新、紅＝老）", color: "#d6604d", kind: "geojson", file: "open-data/tw_house_age.geojson" },
        { id: "tw_age_old", label: "屋齡 40 年以上住宅占比", hint: "（藍＝低、紅＝高）", color: "#d6604d", kind: "geojson", file: "open-data/tw_house_age.geojson" },
      ],
      legend: [
        ["平均屋齡（年）", [["<20", "2166ac"], ["20–25", "67a9cf"], ["25–30", "d1e5f0"], ["30–35", "fddbc7"], ["35–40", "f4a582"], ["40–45", "d6604d"], ["≥45", "b2182b"]]],
        ["40 年以上占比（%）", [["<10", "2166ac"], ["10–20", "67a9cf"], ["20–30", "d1e5f0"], ["30–40", "fddbc7"], ["40–50", "f4a582"], ["50–60", "d6604d"], ["≥60", "b2182b"]]],
      ],
    },
    {
      id: "house_age", panelId: "house-age-box", title: "臺北市建物建築年代（使用執照＋實價登錄，西元）",
      // 兩個臺北市原始來源依門牌合併成一個圖層（scripts/merge_taipei_building_age.py）：
      //  1. 臺北市資料大平臺「歷年使用執照摘要」（發照日期，民國90–114年，即 2001–2025）＋「臺北市門牌位置數值資料」座標，
      //     scripts/make_taipei_house_age.py；同一門牌多張執照取最新一張。
      //  2. 內政部實價登錄 2021/7 起買賣案件的「建築完成年月」（成屋才有），用同一份門牌座標對應，scripts/make_lvr_age.py。
      // 兩邊都有的門牌以使用執照為準（彈出視窗標示來源；6,740 個重疊門牌中 99% 兩者年份差在 1 年內）。
      // 使用執照只有 2001 年以後，實價登錄補上有成交的更早建物，但仍不是全部建物。約 1.5%～12% 的門牌對不到座標，
      // 略過、不做地理編碼推測。門牌座標為戶所人工套圖，有誤差。靜態快照，要更新須重跑腳本。
      // 構想參考 imdataman/taipei-house-age-map，但資料全部取自上述原始來源。
      attribution: "臺北市政府 歷年使用執照摘要＋門牌位置數值資料（data.taipei）、內政部實價登錄，離線快照",
      legend: [
        ["建築年（西元）", [["≤1970", "8c2d04"], ["1971–1980", "d94801"], ["1981–1990", "f16913"], ["1991–2000", "fd8d3c"], ["2001–2010", "9ecae1"], ["2011–2020", "4292c6"], [">2020", "08306b"]]],
      ],
      overlays: [
        { id: "tp_house_age", label: "臺北市建物建築年代（5.3 萬門牌，放大看較清楚）", hint: "（點開看年份與來源）", color: "#4292c6", kind: "geojson", file: "open-data/taipei_building_age.json" },
      ],
    },
    {
      id: "ardswc_ortho", panelId: "ardswc-ortho-box", title: "農村水保署 UAV 正射影像（3 千多組，依視窗自動載入）",
      // 來源：BigGIS 開放資料 gis.ardswc.gov.tw/api/swcb/tiles/ortho（見 data.ardswc.gov.tw/Data/OpenData/Api，
      // 不需申請）。官方目錄是一組一組的小範圍 UAV 影像，不是一張連續圖層，所以做成「一個勾選框」：
      // 放大到 14 級以上後，自動掛上與目前視窗相交的最新 30 組（舊的在下、新的在上，狀態列會顯示
      // 組數與最新一組的日期／案名）。目錄是離線快照（scripts/fetch_ardswc_ortho_catalog.py），
      // 要更新須重跑。圖磚在 storage.geodac.tw，z14–21，.jpg。使用條款未查證。
      attribution: "農業部農村發展及水土保持署 BigGIS UAV 正射影像（gis.ardswc.gov.tw）",
      overlays: [
        { id: "ardswc_ortho", label: "UAV 正射影像（z14 以上）", kind: "ortho-catalog", opacity: 1, catalog: "open-data/ardswc_ortho_catalog.json" },
      ],
    },
    {
      id: "ardswc_hazard", panelId: "ardswc-hazard-box", title: "農村水保署 坡地災害與水保圖資（靜態快照）",
      // 來源：BigGIS 公開向量圖磚（MVT）gis.ardswc.gov.tw/api/ardswc/vectortiles/shp/{圖層}/{z}/{y}/{x}.pbf，
      // 列在 data.ardswc.gov.tw/Data/OpenData/Api 的「不需申請」項目。該伺服器沒開 CORS、前端也沒有向量圖磚
      // 元件，所以由 scripts/make_ardswc_geojson.py 離線抓 z12 圖磚、合併成 GeoJSON（精度約 10 m，已簡化），
      // 勾選才載入。各圖層資料年度不同（2020–2025，見彈出視窗）。未收錄：全臺崩塌地（landslide）、農路
      // （farm_road），資料量太大；需申請的圖層（警告標誌、觀測站、不安定土砂潛勢等）沒有公開網址。
      // 「土石流潛勢溪流」另有地調所山崩雲的圖磚版（山崩・土石流潛勢群組），兩者來源同為水保署。使用條款未查證。
      attribution: "農業部農村發展及水土保持署 BigGIS 開放資料（gis.ardswc.gov.tw），離線快照，非即時",
      overlays: [
        { id: "ar_debris_flow", label: "土石流潛勢溪流（線）", color: "#c53030", kind: "geojson", file: "open-data/ardswc/debris_flow.geojson" },
        { id: "ar_debris_watershed", label: "土石流潛勢溪流集水區", color: "#dd6b20", kind: "geojson", file: "open-data/ardswc/debris_watershed.geojson" },
        { id: "ar_debris_affect", label: "土石流潛勢溪流影響範圍", color: "#e53e3e", kind: "geojson", file: "open-data/ardswc/debris_affect.geojson" },
        { id: "ar_potential_landslide", label: "大規模崩塌潛勢區", color: "#805ad5", kind: "geojson", file: "open-data/ardswc/potential_landslide.geojson" },
        { id: "ar_potential_landslide_affect", label: "大規模崩塌潛勢區影響範圍", color: "#b794f4", kind: "geojson", file: "open-data/ardswc/potential_landslide_affect.geojson" },
        { id: "ar_event_landslide_inventories", label: "事件型崩塌清冊（災後衛星影像判釋）", color: "#975a16", kind: "geojson", file: "open-data/ardswc/event_landslide_inventories.geojson" },
        { id: "ar_soil_water_conservation", label: "水土保持區", color: "#2f855a", kind: "geojson", file: "open-data/ardswc/soil_water_conservation.geojson" },
        { id: "ar_rural_regeneration", label: "農村再生社區", color: "#38a169", kind: "geojson", file: "open-data/ardswc/rural_regeneration.geojson" },
        { id: "ar_subbasin", label: "子集水區", color: "#3182ce", kind: "geojson", file: "open-data/ardswc/subbasin.geojson" },
        { id: "ar_swc_upstream_slope", label: "上游坡地水土保持整體治理區", color: "#2b6cb0", kind: "geojson", file: "open-data/ardswc/swc_upstream_slope.geojson" },
        { id: "ar_mountain_remediation_flood_prevention", label: "治山防災區", color: "#319795", kind: "geojson", file: "open-data/ardswc/mountain_remediation_flood_prevention.geojson" },
        { id: "ar_ecological_inspection", label: "生態檢核區", color: "#68d391", kind: "geojson", file: "open-data/ardswc/ecological_inspection.geojson" },
        { id: "ar_swc_outdoor_eduction_area", label: "水土保持戶外教室（點）", color: "#d69e2e", kind: "geojson", file: "open-data/ardswc/swc_outdoor_eduction_area.geojson" },
        { id: "ar_slopeland", label: "山坡地範圍（六都以外）", color: "#718096", kind: "geojson", file: "open-data/ardswc/slopeland.geojson" },
      ],
    },
    {
      id: "airdefense", panelId: "airdefense-layers-box", title: "防空疏散避難設施（各縣市警察局清冊，僅供參考）",
      // 沒有全國統一資料集：警政署列管的清冊由各縣市分別公開在 data.gov.tw，這裡用
      // scripts/make_airdefense_geojson.py 把 16 個縣市彙整成每縣市一個精簡 GeoJSON 靜態快照
      // （要更新須重跑腳本）。只收有座標的列，不拿地址去地理編碼；縣市分檔、勾選才載入，
      // 因為臺北市就有 2 萬多點。未收錄：雲林縣（下載端擋機器人，未繞過）、宜蘭縣
      // （data.gov.tw 查不到資料集）、金門縣、連江縣（沒找到）。各縣市資料更新日期不同
      // （有的是 111 年版），彈出視窗提醒以現場公告為準。授權：政府資料開放授權條款第 1 版
      // （臺北市資料集頁面標示；其他縣市未逐一查證）。
      attribution: "各縣市警察局防空疏散避難設施清冊（政府資料開放平臺 data.gov.tw）；非全國完整，見面板說明",
      overlays: [
        { id: "ad_taipei", label: "臺北市（22,445 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/taipei.geojson" },
        { id: "ad_newtaipei", label: "新北市（9,550 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/newtaipei.geojson" },
        { id: "ad_taoyuan", label: "桃園市（5,983 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/taoyuan.geojson" },
        { id: "ad_taichung", label: "臺中市（10,347 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/taichung.geojson" },
        { id: "ad_tainan", label: "臺南市（6,905 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/tainan.geojson" },
        { id: "ad_kaohsiung", label: "高雄市（7,544 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/kaohsiung.geojson" },
        { id: "ad_keelung", label: "基隆市（1,198 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/keelung.geojson" },
        { id: "ad_hsinchu_city", label: "新竹市（2,075 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/hsinchu_city.geojson" },
        { id: "ad_hsinchu_county", label: "新竹縣（1,426 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/hsinchu_county.geojson" },
        { id: "ad_changhua", label: "彰化縣（3,066 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/changhua.geojson" },
        { id: "ad_nantou", label: "南投縣（461 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/nantou.geojson" },
        { id: "ad_chiayi_city", label: "嘉義市（2,118 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/chiayi_city.geojson" },
        { id: "ad_pingtung", label: "屏東縣（1,645 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/pingtung.geojson" },
        { id: "ad_taitung", label: "臺東縣（312 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/taitung.geojson" },
        { id: "ad_hualien", label: "花蓮縣（465 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/hualien.geojson" },
        { id: "ad_penghu", label: "澎湖縣（456 處）", color: "#2b6cb0", kind: "geojson", file: "open-data/airdefense/penghu.geojson" },
      ],
    },
    {
      id: "tytree", panelId: "tytree-layers-box", title: "桃園市樹木普查（養護工程處）",
      // 桃園市政府養護工程處「桃園市樹木普查資料庫」（itree.oram.gov.tw）自己地圖頁用的 MapServer WMS
      // （MAP=MapFiles/RoadTree/tree-public.map；圖層 Tree1–Tree5＝健康狀況 良好／枯死／斷頭／不良／危木，
      // 對照該站 api/Common/GetGrowingType）。只即時取圖、不下載資料；網站「政府網站資料開放宣告」
      // 允許免費再利用、須註明出處。為了不讓小比例尺一次請它畫整個桃園，縮放 14 以上才顯示。
      // 樹高、胸徑沒有開放下載（要逐棵查詢），所以這裡只有點位，不能做 3D 樹與陰影。
      attribution: "桃園市政府養護工程處 桃園市樹木普查資料庫",
      overlays: [
        { id: "ty_tree_all", label: "樹木普查（全部）", hint: "（縮放 14 以上才顯示；點位顏色依養工處地圖）",
          kind: "tile-overlay", opacity: 1, minZoom: 14,
          template: "https://itree.oram.gov.tw/mscgi.gms?MAP=MapFiles/RoadTree/tree-public.map",
          wms: { layers: "Tree1,Tree2,Tree3,Tree4,Tree5", format: "image/png", transparent: true, version: "1.1.1" } },
        { id: "ty_tree_risk", label: "需留意的樹（枯死、斷頭、不良、危木）", hint: "（颱風前巡查參考；縮放 14 以上）",
          kind: "tile-overlay", opacity: 1, minZoom: 14,
          template: "https://itree.oram.gov.tw/mscgi.gms?MAP=MapFiles/RoadTree/tree-public.map",
          wms: { layers: "Tree2,Tree3,Tree4,Tree5", format: "image/png", transparent: true, version: "1.1.1" } },
      ],
    },
    {
      id: "landslide", panelId: "landslide-layers-box", title: "山崩・土石流潛勢（地調所山崩雲／水保署）",
      // 在等 BigGIS 受限 API（Landsat／Sentinel 等）申請通過前，先接公開圖資。來源：經濟部地質
      // 調查及礦業管理中心「山崩地質資訊雲端服務平臺」（landslide.geologycloud.tw）自己地圖頁
      // map.js 的圖層表（G.WMTS.list），圖磚為 /jlwmts/jetlink/{圖層}/GoogleMapsCompatible/{z}/{x}/{y}.png
      // （注意是 x 在前；CORS 開放）。土石流潛勢溪流原始資料為水保署（246.swcb.gov.tw/Service/OpenData）。
      // 實測：土石流與順向坡在 z14 以上樣點為空白圖磚，故 maxNativeZoom 設 13；其餘到 z16。
      // 水保署 BigGIS 的「不安定土砂潛勢圖」「地文脆弱度」沒有找到公開圖磚服務，未收錄。
      // 使用條款未查證。
      attribution: "經濟部地質調查及礦業管理中心 山崩地質資訊雲端服務平臺；土石流潛勢溪流：農業部農村發展及水土保持署",
      overlays: [
        { id: "ls_debris", label: "土石流潛勢溪流", kind: "tile-overlay", opacity: 0.9, maxNativeZoom: 13,
          template: "https://landslide.geologycloud.tw/jlwmts/jetlink/swcb_Debris/GoogleMapsCompatible/{z}/{x}/{y}.png" },
        { id: "ls_sens", label: "地質敏感區（含山崩與地滑）", kind: "tile-overlay", opacity: 0.6, maxNativeZoom: 16,
          template: "https://landslide.geologycloud.tw/jlwmts/jetlink/SensitiveArea/GoogleMapsCompatible/{z}/{x}/{y}.png" },
        { id: "ls_dislope", label: "順向坡判釋目錄", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 13,
          template: "https://landslide.geologycloud.tw/jlwmts/jetlink/Dislope/GoogleMapsCompatible/{z}/{x}/{y}.png" },
        { id: "ls_hist", label: "歷史山崩目錄", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 16,
          template: "https://landslide.geologycloud.tw/jlwmts/jetlink/HistoryLS/GoogleMapsCompatible/{z}/{x}/{y}.png" },
        { id: "ls_slope", label: "坡度圖", hint: "（地調所 20 m 坡度分級）", kind: "tile-overlay", opacity: 0.5, maxNativeZoom: 16,
          template: "https://landslide.geologycloud.tw/jlwmts/jetlink/Slp20/GoogleMapsCompatible/{z}/{x}/{y}.png" },
      ],
    },
    {
      id: "hillshade", panelId: "hillshade-layers-box", title: "地形陰影暈渲（Copernicus GLO-30 DEM）",
      // 離線腳本 scripts/make_hillshade_tiles.py 由 Copernicus WorldDEM-30（30 m）算出的**靜態圖磚**：
      // Horn 梯度、四向光源（225/270/315/360°）平均、垂直誇大 1.6 倍；範圍含本島、澎湖、金門、馬祖，z7–z12。
      // 灰階＋透明度編碼：平地全透明、背光坡黑、迎光坡白，所以疊在任何底圖上都不會洗白，
      // 可以再疊「建築完成年」等圖層。z12 以上是放大顯示（來源 30 m，約 z13 的解析度）。
      // 授權：Copernicus DEM Full/Free/Open，需標示出處（見 ARCHITECTURE.md 11.2）。
      attribution: "地形暈渲：Contains modified Copernicus DEM GLO-30 data © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved",
      overlays: [
        { id: "hillshade", label: "陰影暈渲（30 m DEM，臺澎金馬）", hint: "（疊在底圖上；可調不透明度）",
          kind: "tile-overlay", opacity: 0.8, maxNativeZoom: 12, template: "open-data/hillshade/{z}/{x}/{y}.png" },
      ],
    },
    {
      id: "ghlc", panelId: "ghlc-layers-box", title: "全球調和土地覆蓋 GHLC（10 m，2020）",
      // 來源：OpenGeoHub「Global Harmonized Land Cover」(Moreno et al., 2026，CC BY 4.0，
      // 預印本 egusphere-2026-5540)，以規則式整合 ESA WorldCover、GLAD、GLC_FCS30D 等產品，
      // 最多 44 個階層式類別。原始資料是 source.coop 上單一 190 GB 的全球 COG（zstd 壓縮），
      // 沒有現成圖磚服務、瀏覽器端也解不了 zstd，所以這裡是離線腳本
      // scripts/make_ghlc_tiles.py 切出的**臺灣範圍靜態圖磚快照**（不是即時串流，也不含
      // 全球）；只切到 z12（10 m 原生約 z14，更細的縮放級數是放大顯示，看到的是方塊像素）。
      // 10 m 版目前只有 2020 年；30 m 版 2020–2024 年沒有納入。這是模型整合產品，
      // 不是官方土地利用調查，個別像元分類可能有誤。
      attribution: "GHLC 全球調和土地覆蓋 © OpenGeoHub / LandMetric，CC BY 4.0（Moreno et al., 2026, egusphere-2026-5540）",
      // 圖例：第一層 10 大類，每類列出第二層類別的色塊（滑鼠停留看名稱）。色碼抄自 ogh-ghlc10 README，
      // 跟 make_ghlc_tiles.py 的 LEGEND 同一份（10 m 版的 44 類全列）。
      legend: [
        ["建成區", [["建成區", "D73027"]]],
        ["農地", [["大豆", "614d1a"], ["玉米", "F9A41A"], ["水稻", "F9E79F"], ["其他一年生作物", "FFD700"], ["咖啡", "9E7C2D"], ["可可", "6E4B3A"], ["橡膠", "A1887F"], ["油棕", "D4AC0D"]]],
        ["草地", [["栽培草地", "81c784"], ["天然草地", "A5D86A"], ["其他草地", "526140"]]],
        ["森林", [["闊葉常綠疏林", "66d16a"], ["闊葉常綠密林", "1B9E77"], ["闊葉落葉", "388E3C"], ["闊葉落葉密林", "006e00"], ["針葉常綠", "4DB6AC"], ["針葉常綠密林", "00897B"], ["針葉落葉", "80CBC4"], ["針葉落葉密林", "00796B"], ["混合疏林", "8BC34A"], ["混合密林", "558B2F"], ["淹水疏林", "26A69A"], ["淹水密林", "009688"], ["其他淹水林", "00695C"], ["其他林地", "9E9D24"]]],
        ["灌叢", [["灌叢與石南", "E67E22"], ["其他灌叢", "c98804"]]],
        ["稀疏植被／裸地", [["沙漠", "E0CDA9"], ["半乾旱", "C0A46B"], ["半乾旱灌叢", "ac5f3a"], ["岩石與山頂", "d7ccc8"], ["冰雪", "F0F0F0"], ["苔蘚地衣", "c9b1c9"]]],
        ["濕地", [["稀疏植被濕地", "1ed9b4"], ["草本濕地", "1ABC9C"], ["灌叢濕地", "00897B"], ["其他濕地", "2c5747"]]],
        ["水體", [["永久水體", "4169E1"], ["季節性水體", "4189e1"]]],
        ["海岸", [["紅樹林", "6C5CE7"], ["海岸濕地", "9A8CFF"], ["海灘與沙丘", "F5DEB3"]]],
        ["水產養殖", [["水產養殖", "ADD8E6"]]],
      ],
      overlays: [
        { id: "ghlc10", label: "土地覆蓋分類（10 m，2020，臺灣範圍）", hint: "（半透明；點下方圖例對照顏色）",
          kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 12, template: "open-data/ghlc10/{z}/{x}/{y}.png" },
      ],
    },
    {
      id: "ardswc", panelId: "ardswc-layers-box", title: "農村水保署 HOST／CS 地圖（衛星判釋）",
      // 來源：農業部農村發展及水土保持署 BigGIS（gis.ardswc.gov.tw/api-doc）的開放資料 WMTS
      // （gis.ardswc.gov.tw/wmts/，GoogleMapsCompatible、EPSG:3857）。Capabilities 的 6 個圖層
      // 實際圖磚在 storage.geodac.tw（CORS 開放），RESTful 順序 {z}/{y}/{x}.jpg，已實測。
      // 圖磚是不透明 JPG，所以預設半透明疊圖；原生縮放上限依實測：20 m 版 z13、6 m 版 z15、
      // 2010-2015 CS 20 m 版 z14。該署另有 Landsat／Sentinel／UAV 正射等 API，需申請，未加入。
      // 使用條款未查證（頁面標示為開放資料）。
      attribution: "農業部農村發展及水土保持署 BigGIS（gis.ardswc.gov.tw）",
      overlays: [
        { id: "ardswc_host20", label: "2020 HOST 地圖（20 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 13,
          template: "https://storage.geodac.tw/Tile/v2/Map/Host/20M/20200000_121046771_023598277_07_000_Map_Host_20M/{z}/{y}/{x}.jpg" },
        { id: "ardswc_host1015_20", label: "2010–2015 HOST 地圖（20 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 13,
          template: "https://storage.geodac.tw/Tile/v2/Map/Host/20M/00000000_121000000_023000000_14_000_Map_HOST_20M/{z}/{y}/{x}.jpg" },
        { id: "ardswc_host1015_6", label: "2010–2015 HOST 地圖（6 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 15,
          template: "https://storage.geodac.tw/Tile/v2/Map/Host/Taiwan_Rmap_5m_opendata/{z}/{y}/{x}.jpg" },
        { id: "ardswc_cs20", label: "2020 CS 地圖（20 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 13,
          template: "https://storage.geodac.tw/Tile/v2/Map/CSMap/20M/20200000_121046771_023598277_07_000_Map_CSMap_20M/{z}/{y}/{x}.jpg" },
        { id: "ardswc_cs1015_20", label: "2010–2015 CS 地圖（20 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 14,
          template: "https://storage.geodac.tw/Tile/v2/Map/CSMap/csmap_Tile_20m/{z}/{y}/{x}.jpg" },
        { id: "ardswc_cs1015_6", label: "2010–2015 CS 地圖（6 m）", kind: "tile-overlay", opacity: 0.7, maxNativeZoom: 15,
          template: "https://storage.geodac.tw/Tile/v2/Map/CSMap/csmap_Tile_5m/{z}/{y}/{x}.jpg" },
      ],
    },
    {
      id: "traffic", panelId: "traffic-layers-box", title: "最近三個月重大交通事故（A1類，僅供參考）",
      // 資料來源：內政部警政署「即時交通事故資料(A1類)」data.gov.tw/dataset/12818。
      // A1類＝造成當場或 24 小時內死亡的事故（最嚴重分類），使用者明確只要 A1，
      // 不含 A2（僅受傷）。「即時」只是這個資料集的名字：實測抓下來的 CSV
      // 涵蓋 2026 年 1～9 月、不定期整批更新，不是逐秒即時的 API；「最近三個月」
      // 是相對於資料本身最新一筆記錄往前推 90 天，不是相對於今天——資料來源本身
      // 可能已經落後現實世界一到兩週。CSV 端點沒有開 CORS，前端不能直接
      // fetch，這份 GeoJSON 是離線腳本
      // （scripts/fetch_traffic_accidents.py --days 90，預設值）產生的靜態
      // 快照，要更新資料須重跑該腳本，不是即時 API；每個候選點的彈出視窗會
      // 重複標示「資料時間」提醒使用者這不是當下狀態。90 天約 300 起事故，
      // 縮小地圖時點位會疊在一起，前端用 Leaflet.markercluster 做聚合點
      // （縮小合併成數字圓圈，點開/放大才展開個別事故），見 index.html。
      attribution: "內政部警政署 A1類交通事故資料（data.gov.tw，非逐秒即時，見彈出視窗說明）",
      overlays: [
        { id: "a1_accidents", label: "重大交通事故（A1類・最近三個月，依資料本身最新記錄回推）",
          color: "#e53e3e", kind: "geojson", file: "open-data/a1_accidents_recent.geojson" },
      ],
    },
  ];

  // ---- 群組預設出處：layer 沒有自己指定 attribution 時，套用所屬 group 的
  const groupById = Object.fromEntries(groups.map((g) => [g.id, g]));
  layers.forEach((l) => {
    if (!l.attribution && l.group) l.attribution = groupById[l.group].attribution;
  });

  // ---- 主題頁的歷史影像投影片候選：依 (year, rank) 排序，都相同時維持這份清單裡的先後（穩定排序）。
  // scopes 例如 ["nationwide", "taoyuan"]。回傳 { year, label, template }。
  function slideshowCandidates(scopes) {
    return layers
      .filter((l) => l.slideshow && scopes.includes(l.slideshow.scope))
      .sort((a, b) => a.slideshow.year - b.slideshow.year || (a.slideshow.rank || 0) - (b.slideshow.rank || 0))
      .map((l) => ({ year: l.slideshow.year, label: l.slideshow.label, template: l.template }));
  }

  return { ATTR, groups, layers, overlayGroups, slideshowCandidates };
})();
