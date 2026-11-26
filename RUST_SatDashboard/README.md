# ATRDC SatDashboard — Rust 單機版

`scenario-advanced01`（Flask + CesiumJS）的 Rust 改寫版。產出 **Windows x86_64 / ARM64 單一執行檔**，前端（CesiumJS、底圖）全部內嵌在 exe 裡，離線也能跑，不需要 Python。

右下角 Logo 可自行更換：把 `logo.png` 或 `logo.jpg` 放在執行檔同一個資料夾即可（重新整理頁面就生效）；沒有這個檔案就不顯示 Logo。

## 使用方式

```
dist\SatDashboard.bat            ← 依本機架構自動挑 x64 / arm64 版
dist\SatDashboard-x64.exe        ← Intel / AMD
dist\SatDashboard-arm64.exe      ← Snapdragon 等 ARM64
```

啟動後會自動開啟瀏覽器（預設 `http://127.0.0.1:5013/`，埠被占用時會往後找）。要結束就關閉主控台視窗或按 Ctrl+C。

| 參數 | 說明 |
|---|---|
| `--db <檔案>` | 指定 DuckDB（可以用相對路徑） |
| `--data <目錄>` | 資料根目錄（`user_defined_*`、`geojson\`、`DB\sat_metadata.csv`） |
| `--port <埠號>` | HTTP 埠（預設 5013） |
| `--host 0.0.0.0` | 開放區網存取（預設只綁 127.0.0.1） |
| `--no-browser` | 不自動開瀏覽器 |

### 資料位置

- **客戶端只需要 exe 與資料庫**：衛星名稱／國別／用途（`sat_metadata.csv`）、台灣行政區界、全球機場、海底電纜圖層都內嵌在 exe；
  資料目錄有同名檔案時優先使用檔案（`<資料目錄>\DB\sat_metadata.csv`、`<資料目錄>\geojson\*.geojson`）。`scripts/sync_web.py` 會一併更新內建版。

- **DuckDB**：預設使用相對路徑 `..\scenario-advanced01\DB\space_db_slim.duckdb`，從執行檔所在目錄開始逐層往上找，所以 exe 放在 `dist\`、`target\release\` 或專案根目錄都找得到。`--db` 給相對路徑時也用同樣的規則。
- **使用者資料**：自動尋找 `scenario-advanced01\scenario04\`，沿用 Python 版的 `user_defined_TLE\`、`user_defined_SaTCatalogue\`、`user_defined_tracking_NORAD\`、`geojson\`、`config\classification_rules.yaml`，放檔案即生效（索引每 10 分鐘或 DB 檔更新時自動重建，也可以 `POST /api/admin/reload_cats`）。
- **sat_metadata.csv**：依序找 DB 同目錄 → `<data>\DB\` → `<data>\`。

## 功能範圍

| 頁面 | 說明 |
|---|---|
| `/` | 3D 地球儀主頁（全目錄位置、搜尋、近距離配對篩選、NORAD 監測） |
| `/taipei` | 台北覆蓋分析：即時／指定時刻覆蓋、過頂預報、天球過頂軌跡、衛星凌月預報 |
| `/rpo`、`/rpo/cases` | RPO 相對接近 3D（歷史 TLE 重建、RTN 分量、Chan Pc）與案例總覽 |
| `/cable` | 全球海纜態勢（TeleGeography 圖資＋台灣斷纜事件） |
| `/orbit` | 軌道要素歷史：Spiral Polar、SMA 圓形圖、**雙星軌道要素比較**（`/api/orbit/history`；只用本機資料庫，不向 Space-Track 補抓） |
| `/track` | 單顆衛星 **2D 地面軌跡**與即時資料（Leaflet + 瀏覽器端 SGP4；資料 `/api/sat_tle`；Leaflet、satellite.js 與底圖圖磚需連網） |
| `/mission` | **衛星任務規劃**：地面站下行接收過頂預報（預設中大太遙中心 × Vantor 星系，仰角 15°） |
| `/games` | **太空小遊戲**（v0.1.10 起）：月球模擬、星座壅擠、碎片連鎖、天文夢魘、氣球日食、強弓延伸、太空兵棋 |
| `/starlink` | Starlink 分析（v0.1.6）：可見性／RTT／遮蔽、星系普查、殼層、離軌名單與離軌預測（NRLMSISE-00 完整移植） |
| `/story`、`/story/{sid}` | StoryMap 故事頁（v0.1.6）：群組統計、ISR 解析度、雷達評估、重訪、軌跡 |
| `/orbit-tuner` | Orbit Tuner 介紹頁（v0.1.6） |
| `/manual` | 操作手冊（v0.1.25；原稿 `scenario-advanced01/docs/SatDashboard_操作手冊_v*.md`，`tools/build_manual.py` 產生頁面） |
| `/lab` | **會合與機動實驗室**（v0.1.6，第二階段 Sprint 0–3）：批次會合分析、場景 JSON、避碰決策、RPO 控制模擬；v0.1.7 起主選單「🧪 機動實驗室」可直接進入，見下方說明 |
| 版本與聯絡 | 主控台啟動訊息、`/api/about`、地球儀右下角與任務規劃頁頂列顯示版本、版本日期（台灣時間，重新建置時由 `build.rs` 產生，可用環境變數 `SATDASH_BUILD_DATE` 指定）與聯絡資訊（[Rhyno Wu，LinkedIn](https://www.linkedin.com/in/rhyno-wu-6b766771/)） |
| 底圖 | 所有 3D 頁面預設「地形+海底地形 5.4K」（NASA Blue Marble 地形＋海底地形，內嵌於 exe），地球儀左側的底圖選單已隱藏。同步自 Python 版的頁面用 Viewer 的 `imageryProvider` 選項指定底圖，CesiumJS 1.104 起已移除（內附 1.114，原本會顯示一片藍）；`web/ext/standalone_ext.js` 把 Cesium 的預設底圖換成這張 |
| 啟動視角 | 地球儀與任務規劃頁啟動時（以及 Home 鍵）為台灣上空正上方俯視（`web/ext/standalone_ext.js`） |
| 🗺 網路圖磚面板 | 地球儀、台北、海纜、任務規劃頁左上角：台灣公開 WMTS／WMS 底圖與疊圖、Himawari 氣象衛星全圓盤 |

### API

| 路由 | 說明 |
|---|---|
| `/` | 3D 地球儀主頁（沿用原 `globe.js` / `orbit6_tuner.js`） |
| `/api/stats`、`/api/db_info` | 分類統計、DB 資訊 |
| `/api/positions`、`/coords`、`/active`、`/api/position/<id>` | 平行 SGP4 即時位置 |
| `/api/search`、`/api/sat_orbit`、`/api/sat_tle` | 搜尋、軌道弧、TLE |
| `/api/orbit/history` | 軌道要素逐日歷史（SMA、傾角、RAAN、近地點引數；每日最後一筆；`ORBIT_HISTORY_DB` 可指定完整歷史 DB） |
| `/api/conjunctions` | 全目錄 KD-tree 瞬時鄰近篩選 + Chan (2008) Pc 排序代理 |
| `/api/textures`、`/api/globe_texture/*`、`/api/layers/*` | 底圖、國界（含精細台灣行政界替換）、SSN 站點、自訂 GeoJSON |
| `/api/tracking/*`、`/api/user/*` | NORAD 監測、使用者自訂 TLE / 目錄 |
| `/api/admin/reload_cats`、`/api/health` | 熱重載、健康檢查（含版本日期） |
| `/api/about` | 版本、版本日期、架構、聯絡資訊 |
| `/api/update/status`、`/api/update/check`、`/api/update/db`、`/api/update/app`、`/api/update/restart` | 線上更新：狀態、檢查、更新資料庫、更新程式、重新啟動（POST 只限本機） |
| `/api/taipei_coverage[_at]`、`/api/taipei_passes[_at]`、`/api/taipei_sky`、`/api/taipei_lunar` | 台北覆蓋、過頂、天球、凌月（月球／太陽星曆用內附 astronomy-engine C 版，與 Python 版同一引擎） |
| `/api/rpo/presets`、`/api/rpo/<p>/<s>` | RPO 場景（沿用並寫入 `<data>\DB\rpo_scene_*.json` 快取，與 Python 版共用） |
| `/api/mission/config`、`/api/mission/schedule`、`/api/mission/passes` | 任務規劃：星系總覽、單顆過頂（AOS/LOS 精算至 0.1 s、TCA 1 s、每 30 s 時間標記；`sun_el`／`night`）＋地面軌跡 |
| `/api/mission/weather`、`/api/mission/cloud_track` | 單點雲量預報；星下點序列雲量（`pts=t,lat,lon;…`）（MET Norway，未來 4 天；快取依 Expires） |
| `/api/tiles/xyz/…`、`/api/tiles/wms/…`、`/api/tiles/info` | 網路圖磚代理（補 CORS、磁碟快取 30 天、僅放行圖資目錄內網域） |
| `/api/himawari/latest` | Himawari 各波段最新時刻（NASA GIBS） |
| `/api/himawari/jma_latest`、`/api/himawari/jma_img` | JMA 最新全圓盤影像（約落後 10~20 分鐘）與影像代理／下載 |
| `/api/starlink/*`、`/api/v3_flight14_roster`、`/api/story/*` | Starlink 分析、StoryMap 資料（v0.1.6） |
| `/api/lab/demo`、`/api/lab/scenario` | 示範場景、場景 JSON → 端到端會合報告（v0.1.6） |
| `/api/lab/batch`、`/api/lab/batch.csv`、`/api/lab/csv/parse` | 主星對多顆次星批次會合分析、結果 CSV、次星 CSV 預覽（v0.1.6） |
| `/api/lab/maneuver/demo`、`/api/lab/maneuver` | 避碰決策示範案例與計算（v0.1.6） |
| `/api/lab/rpo/demo`、`/api/lab/rpo` | RPO 控制模擬示範案例與計算（v0.1.6） |

**尚未移植**（點進去會顯示說明頁）：RPO 的 PNG 靜態報告（`report.png`，原版以 matplotlib 繪製）；Space-Track（CDM / Decay / SATCAT 回傳「未配置」，跟 Python 版沒設帳密時一樣）；Flight 14 V3 合成編號的 MEME 補位。

### 會合與機動實驗室（`/lab`，v0.1.6）

第二階段計算引擎（`src/phase2/`）與 Python 線上版同一套演算法，以同一組測試資料逐項比對。四個分頁：

| 分頁 | 內容 |
|---|---|
| 批次分析 | 主星對最多 200 顆次星（NORAD 清單或 CSV），SGP4（WGS-72）→ GCRF，自適應近接極小值搜尋，Foster／Chan 碰撞機率與三態適用性篩選；事件表、距離歷程、交會平面圖，結果下載 CSV／JSON |
| 場景 JSON | `satdash.scenario/v1` 場景（含 schema 驗證與錯誤代碼）→ 端到端報告；協方差可用展示模式或傳播模式（6×6 協方差以變分方程沿數值軌跡傳播） |
| 避碰決策 | 沿跡向單脈衝避碰：可行性預檢、自同一參考軌跡分岔的候選方案、線性 STM 預篩、非線性驗證（重新傳播、重新搜尋 TCA、重算 Pc）、二次篩選；結果分可行／網格內無解／限制衝突 |
| RPO 控制 | V-bar／R-bar 接近、駐留、繞飛：HCW 設計與 GCRF 數值閉迴路重播（J2–J4＋差分阻力），安全區、接近速度、走廊監控，abort_to_hold 撤離脈衝預存與故障注入驗證 |

座標框架：TEME →（GMST82）→ ITRF →（IAU-2006/2000A CIO，含 dX/dY）→ GCRF（`sofars`）。EOP 優先讀 `<資料目錄>\DB\EOP-All.csv`，沒有時使用內嵌快照。

跨語言比對工具：`phase2_cli`（`cargo build --release --bin phase2_cli`），子命令 `e2e`、`schema-cases`、`adaptive-tle`、`covprop`、`csv-parse`、`batch`、`maneuver`、`rpo` 等，由 Python 版 `tools/phase2_xlang_report.py` 呼叫。最新比對（2026-11-18）：

| 層 | Python 與 Rust 差異 |
|---|---|
| SGP4、框架轉換、數值積分 | 位置差 ≤ 0.3 mm（深空 SGP4）、框架 2.7e-9 m、1 天積分 ≤ 1e-6 m |
| 近接搜尋、碰撞機率 | TCA 差 ≤ 1.5e-9 s（低相對速度的對接配對除外，距離差 1e-10 km）、Pc 相對差 ≤ 3e-8 |
| 避碰決策（10 案） | 狀態、候選方案、檢查結果全部相同；機動後距離差 2e-6 m |
| RPO 控制（8 案） | 狀態、脈衝序列、違規、撤離表全部相同；脈衝差 2.2e-10 m/s |

效能（本機）：端到端場景約 0.02 s、避碰基準案例約 0.02 s、RPO 基準案例約 0.13 s（Python 版分別約 1 s、3 s、16 s）。

### 衛星任務規劃（`/mission`）

- 地面站預設為國立中央大學太空及遙測研究中心（中壢，校區近似坐標，可於頁面修改），另有台北參考點。
- 星系：Vantor（原 Maxar Intelligence，2025 年更名）光學衛星 WorldView-1/2/3、GeoEye-1、WorldView Legion 1–6，單選。
- 仰角遮罩預設 15°。時窗以台灣日期選擇：今天（現在到午夜）、明天、後天、大後天，以及之後到第 7 天的日期；TLE 外推越遠誤差越大。
- 3D 先畫出星系各衛星自時窗起點一圈的軌道；**用滑鼠點選軌道（或左側衛星）後才顯示該顆的過頂清單**。
- 雲量預報（未來 3 天）：**被點選軌道正下方（星下點）**的預報雲量。過頂清單「雲量」欄為各次過頂 TCA 時刻的星下點；
  「衛星正下方雲量」色條為選定過頂沿地面軌跡每 60 秒的星下點（滑鼠移上去看低／中／高雲與降水）；
  3D 地面上以半透明方格顯示**地面軌跡左右各 4° 內的網格**雲量（網格密度 2°／1°／0.5° 可選，預設 2°；每格取衛星經過時刻的預報），不畫在衛星軌道上；
  點方格看細節，含該衛星的**地面最佳解析度（GSD）與影像幅寬估算**（天底與該格；依 Vantor 公開規格與過頂高度幾何換算）；雲量預報預設關閉，勾選後才計算；
  後端 `/api/mission/cloud_track` 將星下點取 0.1° 格點、相同格點共用查詢，`grid=1` 時用 compact 端點、最多 400 格、8 個並行；
  資料為 [MET Norway Locationforecast 2.0](https://api.met.no/)（CC BY 4.0，免金鑰、可商用；約前 2.5 天每小時、之後每 6 小時），
  後端 `/api/mission/weather` 依回應 Expires 快取，離線時沿用上次的預報。Open-Meteo 在部分網路（本機實測）TLS 連不上，所以沒有採用。
- 預設不顯示夜間過頂（TCA 時地面站太陽仰角 < 0°，以內附 astronomy-engine 計算）；可取消勾選查看。過頂清單顯示 AOS／LOS（台灣時間）、時長、最大仰角、方位。
- 3D：15° 可接收範圍圈、地面軌跡（清單中過頂的可接收段高亮）、選定過頂之 3D 弧線與**每 30 秒時間點標籤**（含仰角）、衛星動畫（時間軸可拖曳）。
- 天球圖：選定過頂之方位／仰角軌跡，30 秒標點、每 60 秒標註時間、TCA 以 ★ 標示。

### 線上更新（資料庫與程式）

客戶端只需要 exe：第一次啟動沒有資料庫時會**自動下載**（主控台每 10% 顯示進度，完成後頁面自動重新整理）；`--no-update` 時改為在頁面右下角按「檢查更新」→「更新」。

- 來源：HuggingFace dataset [`RhynoWu/Rust_SatDashboard`](https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard) 的 `manifest.json`；
  `--update-manifest <網址或檔案>`（或 `SATDASH_UPDATE_MANIFEST`）可改來源，`--no-update`（或 `SATDASH_NO_UPDATE`）關閉自動檢查。
- 自動檢查：啟動 30 秒後一次、之後每 6 小時；頁面右下角（任務規劃頁在頂列）顯示「資料庫有新版／程式有新版」與更新按鈕。
- 安全：`manifest.json.sig` 為 ed25519 簽章，公鑰內嵌（`src/update_pubkey.hex`）；簽章不符就不提供更新。每個檔案再驗 sha256。
  更新操作（`POST /api/update/*`）只接受本機連線，`--host 0.0.0.0` 時區網使用者無法觸發。
- 資料庫：下載 zstd 壓縮檔（453 MB → 約 237 MB，中斷可續傳）→ 驗 sha256 → 解壓並驗原檔 sha256 → 舊檔改名 `.bak` → 新檔就位 → 重建索引，不必重啟。
- 程式：下載本機架構（x64／ARM64）的 exe → 驗 sha256 → 執行中的 exe 改名 `.old` → 新檔就位 → 按「重新啟動」：
  新版在新的主控台視窗啟動、沿用原埠，頁面自動重新整理；下次啟動時刪除 `.old`。
  比較方式：版本號較新，或版本號相同但版本日期較新。
- manifest 每個檔案都有 `sources` 清單（`{"type": "hf", "url": …}`），客戶端依序嘗試；之後加 GitHub Releases 只要在發布腳本多寫一筆來源。

發布（需要 `huggingface-cli login` 與簽章私鑰）：

```powershell
python scripts\update_keygen.py               # 只需一次：私鑰 %USERPROFILE%\.satdashboard\update_signing_key.pem、公鑰 src\update_pubkey.hex
pwsh -File scripts\build.ps1
python scripts\publish_hf.py --notes "說明"    # 資料庫 + 執行檔；內容沒變的不重傳；同一個 commit 更新 manifest；預設壓縮 dataset 歷史
python scripts\publish_hf.py --skip-exe        # 每日只發布資料庫
python scripts\publish_hf.py --local out\hf    # 只輸出到資料夾，搭配 --update-manifest 做本機測試
```

私鑰遺失時要重新產生並重建 exe，已發出去的舊版 exe 就無法再自動更新（只能手動換）。私鑰請另外備份。

### AIS 船舶追蹤

- 地球儀左側「向量圖層」→「🚢 AIS 船舶」：伺服器端連 [aisstream.io](https://aisstream.io)（`src/ais.rs`，yawc WebSocket＋permessage-deflate），與 Python 版 `scenario04/api/ais.py` 同一套 API，前端共用 `web/static/js/ais.js`。
- 來源：① aisstream.io（預設只訂閱台灣與東亞，`AIS_BBOX` 可改）；② 航港局「[臺灣海域船舶動態資訊系統](https://mpbais.motcmpb.gov.tw/aismpb/)」GeoJSON（台灣周邊約 9,000 艘、每 60 秒輪詢，**單機版預設開啟**，`AIS_MPB=0` 關閉；不需金鑰）。以 MMSI 合併、較新回報為準，圖層面板可勾選只看某一來源，點選船隻顯示資料來源與收到時間。
- 金鑰：環境變數 `AISSTREAM_API_KEY`，或在圖層面板直接輸入（存成資料目錄的 `aisstream_key.txt`，只接受本機設定）。金鑰到 aisstream.io 用 GitHub 登入免費申請。
- 勾選圖層才連線，閒置 10 分鐘（`AIS_IDLE_SEC`）自動斷線；狀態 `/api/ais/status` 含各來源狀態、每段連線長度與重連次數。船位只存在記憶體，1 小時未更新即移除，航跡保留 6 小時。
- AIS 為船舶自主回報，只有岸基接收站約 15～40 浬內有資料；遠洋沒有資料，位置可能遭干擾或偽造。

### 網路圖磚與 Himawari

- 圖資目錄沿用 `Rust_WMTS_Server/static/layers.js`（同步為 `web/static/js/map_layers.js`）：NLSC、中研院百年歷史地圖、臺北市歷史圖資、地調中心液化潛勢、防災／地籍等疊圖。
- Cesium 以 WebGL 貼圖使用圖磚，遠端沒有 CORS 標頭就會被擋，因此一律走本機代理 `/api/tiles/*`；快取在 `%LOCALAPPDATA%\SatDashboard\tile_cache`（可用 `SATDASH_TILE_CACHE` 改位置），看過的區域離線也能顯示。代理只放行圖資目錄出現過的網域與 NASA GIBS。
- Himawari 全圓盤（地球儀疊圖）：NASA GIBS 重投影之 Himawari-9 AHI 紅外 Band 13／可見光 Band 3／氣團 RGB，每 10 分鐘，可回看 24 小時並播放近 2 小時動畫；資料約落後 1 小時。
- JMA 最新全圓盤影像（面板內顯示與下載）：取自 [JMA 氣象衛星中心](https://www.data.jma.go.jp/mscweb/data/himawari/list_fd_.html)，約落後 10~20 分鐘；紅外、可見光、水氣、真彩色、氣團、Sandwich、夜間微物理、沙塵等 10 種。JMA 檔名只有時分、每天覆蓋，`/api/himawari/jma_latest` 以 Last-Modified 找今天最新的一格，`/api/himawari/jma_img` 代理影像（`dl=1` 下載）。影像為地球同步視角且已含海岸線，不疊到地球儀上。
- 需要 `geojson` 檔或金鑰的疊圖（OSM 主題、攝影機、Sentinel、Google 等）不在此面板內。

### 衛星管理與帳號權限（僅單機版）

地球儀頂端「🗂 衛星管理」（`/satadmin`）。資料只存在本機資料目錄 `user_private\`，不上傳：

| 檔案 | 內容 |
|---|---|
| `user_private\accounts.json` | 帳號、角色、Argon2id 密碼雜湊 |
| `user_private\sat_custom.json` | 自訂名稱、群組、操作紀錄（全組織共用；每次寫入保留上一版 `.bak`） |

- **更名**：依 NORAD ID 或名稱／國際編號查詢，輸入自訂名稱與備註；原 Space-Track 名稱保留，可隨時還原。「列出重複名稱」可找出 OBJECT A、TBA - TO BE ASSIGNED 等同名衛星（可排除碎片與火箭殘骸）。更名約 1 秒後重建索引，地球儀、搜尋與報表都會使用新名稱。
- **建議名稱**：「建議名稱」辨識 OBJECT A/B/C：official（Space-Track 已正式命名）＞ inferred（GCAT 逐顆判讀或單一酬載發射）＞ group_inferred（只確認發射群組，命名為「XX 群組衛星（推論）」、不指派 A/B/C 個體）；conflict 標示來源矛盾或類型不一致（例如 Space-Track 已判定為碎片）。每筆附發射群組／候選任務／個體對應分層判讀與來源鏈，勾選後才套用，更名紀錄保存名稱狀態、可信度、證據連結（可加 SeeSat-L 等）與複核狀態；任務類型與用途不自動歸因。GCAT（McDowell, planet4589.org, CC BY 4.0）與 SATCAT 由每日管線寫入 DB。API：`/api/satadmin/suggest`、`POST /api/satadmin/names_batch`。
- **SATCAT 每日異動**：「SATCAT 異動」頁籤列出每日異動：以 Space-Track `satcat_change` 為準（名稱、國際編號、國家、發射日、DECAY 的異動與異動時間，近 90 天），再以每日 SATCAT 快照比對補上物體類型變更；分為正式命名（OBJECT x → 正式名稱）、更名、再入、再入日期修正、新編目、類型變更、其他欄位，可只看已更名或群組內的衛星；已套用推論名稱而 Space-Track 已正式命名者標「可升級」，TLE 目錄仍是 OBJECT x 也會註明；可匯出 CSV。API：`/api/satadmin/changes?days=&kind=&mine=1`。
- **觀測與身分驗證**（`/obs`，衛星管理頁頂端進入）：四種紀錄：地面 POI（觀測站與關注地點）、觀測紀錄（RA/Dec J2000 或方位／仰角）、軌道解（TLE，支援 Alpha-5 編號）、身分主張（名稱＋來源類型＋可信度），每筆附複核狀態（未複核／已接受／有爭議／已否決），內容修改後自動退回未複核；以 CSV 匯入匯出（依標題列自動判斷種類）。交叉驗證：① 觀測殘差——目錄 TLE 與使用者軌道解 SGP4 傳播到觀測時間，比較觀測站看到的方向（IAU 1976 歲差轉 J2000，與 skyfield 差 < 0.004°），≤ 0.5° 符合、≤ 2° 勉強符合，並比對同次發射所有物體找最符合者；② 軌道比對——軌道解與目錄 TLE 在曆元 ±12 小時的最大位置差，≤ 10 km 一致、≤ 50 km 接近，並找同次發射中軌道最接近者（協助判斷 OBJECT A/B/C）；③ 身分主張與 Space-Track 正式名稱、其他主張比對。每顆衛星輸出 identity／orbit／observation 狀態與分層判讀（發射群組→候選任務→個體）；任務類型與能力一律為未知，不自動歸因。業餘觀測屬中等可信度來源，需人工複核。資料存在本機 `user_private\observations.json`（保留上一版 .bak）；檢視者可查看與執行交叉驗證，編輯者可新增／修改／刪除／匯入，管理者可複核。API：`/api/obs/data`、`/api/obs/check`（GET 用已存資料、POST 傳入資料）、`POST /api/obs/{kind}`、`PUT|DELETE /api/obs/{kind}/{id}`、`POST /api/obs/{kind}/{id}/review`。
- **群組**：可多層（例：PRC偵察衛星 → 光學／雷達／電子偵察），逐顆加入或移除 NORAD ID；每個群組可設顏色、感測器類型與預設偵照角度（子群組未設定時沿用上層），供過頂預報使用。
- **CSV**：匯入欄位 `norad_id,name,group,note`（group 以「/」分層，沒有的群組自動建立）；匯出含原名與群組路徑（UTF-8 BOM，Excel 可直接開啟）。
- **帳號**：尚未建立帳號時維持原本行為，不需登入；此時本機視為管理者，區網連線只能查詢。在「帳號管理」由本機建立第一個管理者之後，所有頁面與 API 都需要登入（session 12 小時，閒置會延長；同一帳號連續錯 5 次鎖 60 秒）。

| 角色 | 權限 |
|---|---|
| 檢視者 | 查詢 |
| 編輯者 | 查詢、輸入（CSV 匯入）、新增（群組）、修改（更名、群組成員） |
| 管理者 | 再加帳號管理、重載設定、程式更新 |

- 忘記管理者密碼：關閉程式後刪除 `accounts.json` 即回到「未建立帳號」狀態，群組與更名資料不受影響。

### 星歷資料與衛星失能（僅單機版）

- **最後更新時間**：地球儀 DB 資訊列後面顯示「星歷更新」，取資料庫下載時間與最近重抓時間中較晚的一個，滑鼠移上去可看最新 TLE 曆元。完整狀態在衛星管理的「星歷資料」分頁：資料庫、最近重抓、目錄曆元分布、SATCAT。
- **一鍵重新抓取**（管理者）：
  - CelesTrak（免帳號）：抓 active 群組，群組成員不在其中的另外逐顆補抓，每次上限 30 顆。
  - Space-Track（需帳號）：抓全目錄未再入、30 天內曆元的物體。
  - 抓到的 TLE 存成 `user_private\ephemeris\gp_latest.tle` 覆蓋層，索引只採用比資料庫新的曆元，資料庫檔本身不變。
  - 依兩站使用規範限制頻率：CelesTrak 每 2 小時、Space-Track 每 1 小時、SATCAT 每 12 小時各一次。連線失敗或 5xx 錯誤只冷卻 10 分鐘。
  - Space-Track 帳號可在頁面輸入（明文存在 `user_private\spacetrack.json`），也可設環境變數 `SPACETRACK_USER`／`SPACETRACK_PASS`，環境變數優先。
- **衛星失能（DECAY）**：SATCAT 有 DECAY 日期的衛星標為「已再入」，另標出「TLE 停更」（超過 N 天沒有新曆元，預設 30 天）和「SATCAT 查無」。可依群組（含子群組）列出，附 DECAY 日期、發射日期、在軌天數、最後 TLE 曆元，可匯出 CSV；另有全目錄近 N 天再入清單。群組成員表和查詢結果也會顯示狀態標籤。

### 過頂預報（僅單機版）

地球儀頂端「📅 過頂預報」（`/forecast`），輸出 CSV，不做視覺化：

- **中心點**：可設多個（最多 30 個），每個有經緯度、高度和範圍半徑。半徑 0 只看中心點；半徑大於 0 時，衛星偵照範圍與該圓形區域有交集就算可偵照。常用中心點存在 `user_private\forecast_sites.json`，由編輯者以上儲存。
- **期間**：最長 62 天，預設 31 天。1 個月、7 顆衛星、3 個中心點，debug 版約 1 秒。
- **過頂判定**：以中心點仰角門檻定義過頂時段，預設 10°。
- **偵照角度**：中心點相對衛星的離天底角 ≤ 偵照角度才算可偵照，CSV 會附可偵照起訖時間與偵照地面半徑（500 km 高度時 15° 約 135 km、30° 約 290 km）。角度優先用群組設定（子群組沿用上層），也可以一律套用同一角度。
- **日照**：每筆過頂附 TCA 當下中心點的太陽仰角和當日日出日落（以 −0.833° 計，含大氣折射與日面半徑）。可設「光學衛星只保留日照時段」；另有每日日出日落 CSV。
- **歷史誤差估算**：取資料庫近 N 天（預設 60）同一顆衛星的 TLE 兩兩比對，把舊 TLE 傳播到新 TLE 的曆元後與新 TLE 位置相減，依提前 1、2、3、5、7、10、14、21、30 天統計位置誤差與沿軌時間誤差（中位數、p90）。每筆過頂再依距 TLE 曆元的天數，標上預估時間誤差（p90，取該衛星的曲線，樣本不足時用合併曲線）。
- **CSV**：過頂清單、日出日落、歷史誤差三個檔案，UTF-8 BOM，時間同時列出指定時區與 UTC。
- **交叉驗證**：ISS 過台北 3 天、9 筆過頂，與 Python sgp4 獨立計算（1 秒步長）相比，起訖與 TCA 相差 ≤ 2 秒，最高仰角相差 0.046°。

### 與 Python 版的交叉驗證

| 項目 | 結果 |
|---|---|
| 台北覆蓋（固定時刻） | 各類別顆數、可見數相同，仰角差 0.000°（Rust 另排除 1 顆已再入衛星，同 Python sgp4 錯誤碼 6） |
| 天球過頂（2 h） | 93 筆完全相同 |
| 凌月預報（24 h） | 118 事件逐筆相同，角距一致到小數第 4 位 |
| 過頂預報（時間軸版） | Rust 取「最早 20 筆」；Python 版湊滿 20 筆即提前跳出，結果依 DB 列順序而定。重疊範圍內逐筆相同 |
| RPO 場景 | 3 案例 d_min／TCA／點數相同，距離差 ≤ 0.0001 km |

## 效能（ARM64 筆電實測，33,006 顆）

| 項目 | Rust 版 | Python 版（論文數據） |
|---|---|---|
| 建立衛星索引（DuckDB 225 萬列 → 最新 TLE） | 0.27 s | 數秒 |
| 全目錄 SGP4 + KD-tree 鄰近篩選 | **8 ms**（SGP4 3.8 ms + KD 3.3 ms） | 穩態 52 ms |
| Starlink 全星系位置（約 9 千顆） | 38 ms（含 JSON） | — |
| 台北過頂預報（24 h，1.1 萬顆候選） | 約 0.3 s | 100 s |
| 台北天球過頂（2 h） | 約 0.2 s | 38 s |
| 台北凌月預報（24 h） | 0.13 s | 62 s |
| RPO 場景重算 | 約 0.1 s | — |
| 任務規劃單顆 24 h 過頂 | 7 ms | — |

位置精度：與 Python `sgp4`（`Satrec.twoline2rv`）逐顆比對，LEO / GEO / 深空軌道的差距都落在 JSON 四捨五入精度內（< 50 m）。

## 建置

需要 Rust stable、VS2022 Build Tools（含 ARM64 與 x64 編譯器）。在 ARM64 主機上，`ring`（libduckdb-sys 的建置期相依）另外需要 LLVM clang，腳本會自動把 `C:\Program Files\LLVM\bin` 加進 PATH。

```powershell
python scripts\sync_web.py      # 自 Python 版與 Rust_WMTS_Server 同步前端資產（前端有更新時才需要）
pwsh -File scripts\build.ps1     # 兩種架構都建置，輸出到 dist\
cargo test --release             # 單元測試
```

## 程式結構

```
src/
  main.rs       啟動、埠選擇、開瀏覽器
  config.rs     命令列 / 環境變數 / 資料路徑解析（DB 相對路徑）
  index.rs      DuckDB 讀取、衛星索引、統計、DB 資訊
  classify.rs   國別 / 用途 / 年代 / 星座分類與顏色
  userdata.rs   使用者自訂 TLE（Alpha-5）、目錄、監測清單
  physics.rs    SGP4（WGS72）、TEME→大地座標、KD-tree 篩選、Chan Pc
  coverage.rs   台北覆蓋、過頂預報、天球過頂軌跡
  lunar.rs      衛星凌月預報（astronomy-engine FFI）
  rpo.rs        RPO 相對接近場景
  mission.rs    任務規劃（地面站過頂、30 s 標記）
  tiles.rs      網路圖磚代理、Himawari 最新時刻
  starlink.rs   Starlink 分析（含 NRLMSISE-00 離軌預測）
  story.rs      StoryMap 故事頁
  lab.rs        會合與機動實驗室頁面與 /api/lab/*
  phase2/       第二階段引擎：時間尺度、EOP、框架、力模型、RK4、SGP4 星曆、近接搜尋、Pc、
                適用性篩選、協方差傳播、場景 schema、批次、避碰（maneuver.rs）、RPO（rpo.rs）
  bin/phase2_cli.rs  跨語言比對命令列工具
  state.rs      索引背景重建、歷史索引、快取
  auth.rs       帳號、角色權限、登入 session、權限中介層
  satadmin.rs   衛星更名、群組分類、CSV 匯入匯出、操作紀錄
  suggest.rs    建議名稱：Space-Track／GCAT 證據等級（official／inferred／group_inferred／conflict）
  changes.rs    SATCAT 每日異動（DB 的 satcat_change 表）
  obs.rs        觀測資料模型：地面 POI／觀測／軌道解／身分主張、交叉驗證、複核
  ephemeris.rs  星歷狀態、一鍵重抓（CelesTrak／Space-Track 覆蓋層）、SATCAT 與 DECAY 列表
  forecast.rs   過頂預報：多中心點、偵照角度、日照與日出日落、歷史 TLE 誤差估算、CSV
  api.rs        主頁 HTTP 路由；api_phase2.rs 台北／RPO／海纜路由
  assets.rs     內嵌前端資產
web/templates/  由 sync_web.py 以 Jinja 預先渲染之頁面
web/static/     同步自 Python 版之 JS／CSS／資料；map_layers.js 同步自 Rust_WMTS_Server
web/ext/        Rust 版自有前端：net_tiles.js（網路圖磚面板）、mission.html／mission.js
web/cesium/     CesiumJS 1.114
vendor/astronomy/ astronomy-engine C 原始碼（MIT，Don Cross）
config/         內建預設：classification_rules.yaml、ssn_stations.geojson、overpass_cats.yaml、rpo_presets.json
```

## 版本紀錄

### v0.1.25（2026-11-26）

- 新增「觀測與身分驗證」頁 `/obs`（衛星管理頁頂端進入）：地面 POI、觀測紀錄、軌道解、身分主張四種紀錄與複核（管理者），CSV 匯入匯出；交叉驗證觀測殘差（IAU 1976 歲差轉 J2000，與 skyfield 差 < 0.004°）、軌道比對與同次發射最接近物體、身分主張比對；每顆衛星輸出身分／軌道／觀測狀態與分層判讀。資料存在 `user_private\observations.json`。與線上版逐筆一致，前端 `obs_model.js`、`obs.js` 兩版共用
- TLE Alpha-5 編號（NORAD ≥ 100000，例如 A1419＝101419）解碼
- 地球儀資訊卡新增「名稱查詢」：目錄仍為 OBJECT x 或另有新資訊時，列出 Space-Track 正式名稱、建議名稱（證據等級與可信度）、自訂名稱、發射群組與注意事項
- 操作手冊更新至 v0.1.25（補齊 v0.1.20 起的 AIS、衛星管理、帳號權限、過頂預報、建議名稱、SATCAT 異動、觀測與身分驗證）

### v0.1.24（2026-11-26）

- 衛星管理頁新增「SATCAT 異動」頁籤：以 Space-Track `satcat_change` 為準（名稱、國際編號、國家、發射日、DECAY 的異動與異動時間，近 90 天），再以每日 SATCAT 快照比對補上物體類型變更；分為正式命名（OBJECT x → 正式名稱）、更名、再入、再入日期修正、新編目、類型變更、其他欄位
- 每筆附自訂名稱與所屬群組；可只看已更名或群組內的衛星；已套用推論名稱而 Space-Track 已正式命名者標「可升級」並可跳到建議名稱；TLE 目錄仍是 OBJECT x 也會註明；可匯出 CSV
- 資料由每日管線寫入 DB 的 `satcat_change`／`satcat_change_meta` 表；API `/api/satadmin/changes?days=&kind=&norad=&q=&mine=1`

### v0.1.23（2026-11-26）

- 衛星管理頁新增「建議名稱」：辨識 OBJECT A/B/C 的可能正式名稱。證據等級 official（Space-Track 已命名）＞ inferred（GCAT 逐顆判讀或單一酬載發射）＞ group_inferred（只確認發射群組，命名為「XX 群組衛星（推論）」、不指派 A/B/C 個體）；conflict 標示來源矛盾或類型不一致
- 每筆附發射群組／候選任務／個體對應分層判讀、來源鏈與警示（非酬載、類型不一致）；勾選後以 `POST /api/satadmin/names_batch` 批次套用，更名紀錄保存名稱狀態、可信度、證據連結與複核狀態；任務類型與用途不自動歸因
- GCAT（McDowell, planet4589.org, CC BY 4.0）由每日管線寫入 DB（`gcat_sat`／`gcat_launch`／`gcat_meta`）；API `/api/satadmin/suggest?scope=objects` 或 `?norad=`

### v0.1.22（2026-11-25）

- SATCAT（DECAY 再入日期）改為跟著資料庫發布：每日管線 `scenario-advanced01/tools/update_satcat.py` 以 Space-Track 下載後寫入 DB 的 `satcat`／`satcat_meta` 表；單機版比較本機重抓的檔案與 DB 內的資料，取較新者（「衛星失能」不必再自行連 CelesTrak）

### v0.1.21（2026-11-25）

客戶回饋 8 項（僅單機版；資料只存在本機 `user_private\`）
- 衛星管理頁 `/satadmin`：依 NORAD ID 查詢與更名（保留 Space-Track 原名、可還原）、列出重複名稱（OBJECT A、TBA 等）、多層群組（感測器類型與偵照角度沿用上層）、CSV 匯入匯出、操作紀錄
- 帳號權限：檢視者／編輯者／管理者，Argon2id 雜湊、登入 session、連續錯誤鎖定；尚未建立帳號時維持原行為（本機＝管理者、區網唯讀）
- 星歷資料：地球儀顯示最後更新時間；一鍵重抓 CelesTrak 或 Space-Track（覆蓋層、只採用較新曆元、依兩站規範限制頻率）
- 衛星失能：SATCAT DECAY 再入日期、TLE 停更、近期再入清單，可匯出 CSV
- 過頂預報頁 `/forecast`：多中心點（可設半徑）、最長 62 天、偵照角度判定可偵照時段、太陽仰角與日出日落、光學衛星日照篩選、歷史 TLE 誤差估算，輸出 CSV
- `/api/admin/reload_cats` 改為只限本機或管理者

### v0.1.19（2026-11-21）

碎片連鎖（第三輪審查的 B、C、D 組）
- 驗證強化：新增 `scripts/validate_debris.py`，Cosmos 1408 改用編目等效（L ≥ 10 cm）與 30 個種子（中位數、IQR、bootstrap 區間），另有太陽活動單調性（30 個種子全數通過）與密度 ±15% 敏感度測試
- 大氣：密度表加入 Ap 維度，實測期間以每月等效 Ap（460 km 密度等效）驅動；`gen_solar_tables.py --track` 測試沿軌跡取樣與全球平均的差異（±16% 以內，維持全球平均）
- 解體：碰撞模型的 log₁₀Δv 超過 μ + 1σ 重抽（以 Cosmos 1408 校準的經驗修正；log 誤差 0.577 → 0.179，第 3 年 5.0% → 1.6%、觀測 0.9%）；爆炸模型不變
- 在軌衛星可選「平均 5／10 年後陸續失效」：失效後依 B* 衰減、不再避碰
- 避碰分三級（50%／10%／2%，進階 2 點）
- 任務 3 以 5 個種子、第一代碎片近似風險的中位數判定，門檻 81／79／77%，並顯示各搭配的參考效果；對照組沿用主結果的 `t0`（API 新增 `t0`）
- 後端輸出衰減節點，畫面上的碎片隨阻力下降
- API：`n_frag` 上限放寬到 2,000（介面仍為 1,000）；驗證用欄位 `dv_sigma_max`、`rho_scale`、`ap_fixed`

### v0.1.18（2026-11-21）

碎片連鎖（第三輪審查的快速修正）
- 「解體日期」改稱「太陽活動起算日」，標明只影響太陽活動、軌道目錄仍為現況
- F10.7 走勢圖以灰底標出 2041 年後的週期外推（情境假設，非預報）
- 模擬 5 年以上時標示「有效載荷不衰減」的保守假設
- 清理與移除火箭體的事件顯示候選數
- 快取鍵加入 `model_version`（程式版本＋太陽活動與密度表雜湊），回應也附上；F10.7 表檔頭記錄來源網址與 sha256
- 任務 3 與架構文件措辭改為「初步結果」；文件標明 F10.7／81 天平均同值的近似、「排除高遠地點」只是誤差歸因測試、編目碎片與完整族群的定義差異，並列出待排程的驗證、模型與機制項目

### v0.1.17（2026-11-21）

碎片連鎖：大氣改為隨太陽活動變化（依 Cosmos 1408 驗證報告建議）
- 阻力衰減改用 NRLMSISE-00 全球平均密度表 × 當月 F10.7（81 天平均；1957 年起實測，接 CelesTrak 預報到 2041 年，再往後以 11 年週期外推）
- 兩張表由新腳本 `scripts/gen_solar_tables.py`（numpy＋pymsis）產生並內嵌（`config/f107_monthly.csv`、`config/msis_density.csv`），離線可用
- 新增「大氣」選單（隨太陽活動／固定低中高／舊版靜態）與「解體日期」；歷史情境自動從事件日期起算；結果列出 F10.7，儀表板加 F10.7 走勢圖
- Cosmos 1408 重跑：第 3 年存活 8.2% → 4.9%（觀測 0.9%），剩一半的天數 137 → 170 天（觀測 192）；剩下偏差主要來自高遠地點長尾
- 架構文件：大氣模型說明、驗證重跑結果、文獻補強（Vallado 第 4 版、NRLMSISE-00、IDA 報告完整書目、Johnson DOI 查證紀錄、CelesTrak 資料來源與擷取日期）

### v0.1.16（2026-11-21）

碎片連鎖（依第二輪審查意見改進）
- 「第一代寫實期望碰撞」改稱「第一代碎片近似風險」：未加速情境下第一代碎片對現有目錄的近似風險，誇張模式下註明略偏低
- 任務 3「守護者」改在寫實 ×1 下、以累計期望碰撞比判定（Envisat、1,000 個碎片固定；≤ 85% 一星、≤ 80% 兩星、≤ 75% 三星）。實測發現誇張模式下的比較是混沌的（只移除火箭體 139%、只清理 116%），單次結果不可靠
- 快照取樣時刻改用獨立亂數流（共同隨機數），同種子的決策組與對照組比較雜訊大幅降低
- 決策卡：清理改依累計碰撞風險排序；移除火箭體加入軌道面篩選（傾角差 ≤ 5°、升交點赤經差 ≤ 30°）；三張卡與避碰假設都標明教學簡化
- 429 附 `Retry-After`，前端倒數自動重試；快取鍵加入目錄版本並改為 LRU
- 圖表標出決策生效時間；任務失敗說明原因；「凱斯勒失控」成就改為可解釋的「失控增長」；歷史情境名稱標「教學近似」；簡化軌道提示提前到 30 天
- 爆炸與碰撞兩種解體模型分開標示：選單寫明內部能量／外部撞擊並即時顯示公式與適用情境，情境模板與所選模型不一致時警告，結果摘要列出所用模型
- 納入 Cosmos 1408 衰減驗證：第 1 年吻合、一年以後偏慢；模擬超過 1 年時結果標示長期在軌數與期望碰撞偏高
- 架構文件：補主要論文 DOI、兩種解體模型對照表、6.1 衰減驗證、混沌與共同隨機數的實測結果、未實作項目

### v0.1.15（2026-11-21）

碎片連鎖（依架構審查意見改進）
- 科學正確性與說明
  - 「加速倍率」改名「碰撞誇張倍率」，說明它只放大碰撞截面
  - 新增「第一代寫實期望碰撞」作為主要判讀數字；原寫實等效值改稱「線性反推（偏高）」
  - 再入門檻統一為 120 km；目錄中的火箭體與碎片依 TLE 阻力項 B* 衰減再入（有效載荷假設維持軌道）
  - 結果標示「統計模擬，不是碰撞預報」，附三段說明（看到的、接近真實的、誇張或簡化的）；播放超過 1 年時提示畫面軌道為簡化版
- 資源保護：同時只算一個模擬（其餘回「請稍候」）、相同參數 5 分鐘內直接用快取、主控台記錄每次計算
- 遊戲化
  - 任務模式：自然清除、連鎖觸發者、守護者（1–3 星）
  - 情境模板：Envisat，以及風雲一號 C、Iridium 33 × Cosmos 2251、Cosmos 1408 三個歷史案例（以自訂軌道示意）
  - 緩解決策卡：清理任務、移除廢棄火箭體、避碰機動（預算 3 點），自動跑對照組比較效果
  - 風險儀表板：風險最高的目錄物件、碰撞熱區高度帶、各代碎片比例、累計再入；9 項成就
- 其他：時間軸跨半年以上時刻度顯示年份；架構說明文件更新到 v0.1.15

### v0.1.14（2026-11-21）

文件
- 內建操作手冊（`/manual`）新增第八節「太空小遊戲」：共通操作與 7 個遊戲的玩法、判讀與注意事項
- 新增 [docs/games_debris_architecture.md](docs/games_debris_architecture.md)：碎片連鎖的架構說明（API、模擬管線、前端、限制與擴充指引）

### v0.1.13（2026-11-21）

改進
- 🌙 月球模擬：成功後依 Δv（飛掠依近月點精準度）給 1–3 星並記住最佳成績；挑戰逐關解鎖（可一鍵全部解鎖）；TLI Δv 加滑桿
- 🛰 星座壅擠：倍數改為對數橫條圖（依倍數分色），指標名稱加滑鼠說明
- 💥 碎片連鎖：加速倍率預設改為 ×1 寫實；加速時地球畫面上方顯示「誇張模式」與寫實等效期望值；圖例加大且可點擊開關；圖表顯示目前播放時間
- 🎈 氣球日食：沒有全食時提供「套用剛好全食的直徑並重算」；「從台北看太陽」移到地球畫面右上角
- 🎯 強弓延伸：交會表加顏色說明；播放過後拖動「發射時間誤差」即時重算落點
- 📱 手機與窄螢幕（≤ 820 px）：地球在上且捲動時固定、面板在下；分頁列可橫向捲動
- 時間輸入框在所有分頁都跟著時鐘更新

### v0.1.12（2026-11-21）

改進
- 🔭 天文夢魘
  - CCD 影像點一下可放大
  - 「標出光跡」：以色線（依星座分色）與星等標籤標出每條光跡，不重算影像
  - 「比較：現況 vs 10 萬 Starlink」：同時刻、同指向各拍一張，左右拖曳比較，並列出光跡數與佔去像素的倍數
  - 3D 畫面改為觀測點、望遠鏡視野錐與被拍到的衛星（含名稱與星等），相機順著指向看出去
- ♟ 太空兵棋
  - 教練建議：依局勢（可用率、未修海纜、干擾、升級指數）提示下令重點，可關閉；每個行動按鈕加上效果說明
  - 海纜改用色盲友善配色：藍綠實線＝正常、紅虛線＝中斷、橘虛線＝搶修中；距台灣 1,500 km 外的段落調暗
  - 每回合結束跳出結算：可用率變化、海纜中斷數與本回合事件
  - 終局復盤：自動跑 AI 四種打法各 300 局，與你這一局的平均可用率排名比較

### v0.1.11（2026-11-21）

改進（太空小遊戲共通體驗）
- 每個遊戲開頭新增任務卡：三個步驟加「▶ 示範」按鈕，一鍵帶入參數並執行；原本的開場說明收進「背景說明」
- 「時間」面板可收合，摘要列顯示目前時間與播放速度；月球與氣球分頁預設展開，其他分頁預設收起
- 主要動作按鈕（發射、計算、引爆、拍一張、提交命令…）固定在面板底部，不用捲動就按得到
- 計算中的按鈕顯示轉圈與經過秒數，算完自動把結果捲入畫面
- 播放速度選單在慢動作或自訂倍率時顯示「自訂：…」，不再是空白
- 下方時間軸改用台灣時間（UTC+8），與面板一致
- 從其他分頁切回太空兵棋時，相機回到台灣周邊海纜

### v0.1.10（2026-11-20）

新增
- **太空小遊戲 `/games`**（地球儀工具列「🎮 太空小遊戲」，僅單機版）：
  - 🌙 月球模擬：月相、台北月出月沒、天平動、月食；月面圖（NASA LRO 影像）與 17 個登月點；3D 地月視圖；
    射月球（地—月—日三體積分）：撞月、繞月飛掠、自由返回、LOI 入軌，附自動瞄準
  - 🛰 星座壅擠：依公開申請殼層產生假想 Walker 星座（如 Starlink 10 萬顆），KD-tree 快照估計接近頻率、碰撞期望值、台北可見數與高度密度
  - 💥 碎片連鎖：NASA 標準解體模型（質量與動量守恆）＋J2 與大氣衰減＋KD-tree 碰撞擲骰，可加速看凱斯勒連鎖
  - 🔭 天文夢魘：真實星表（d3-celestial，Hipparcos／Tycho）為背景，以光子數合成望遠鏡 CCD 影像與衛星光跡，含整夜統計
  - 🎈 氣球日食：鍍鋁氣球多大才能讓台北看到日全食（本影幾何、持續時間、質量、阻力壽命、亮度）
  - 🎯 強弓延伸：更強的火箭要多快才到得了衛星交會點（Lambert）、瞄準關鍵與沒打到時的彈頭落點（教育性物理模擬）
  - ♟ 太空兵棋：海纜中斷下的通訊韌性，紅藍對抗＋白方 GM、WEGO、可與 AI 對戰或以連結多人加入，含蒙地卡羅策略比較

改進
- 地球儀分類篩選改為瀏覽器端傳播（`/api/tles`＋Web Worker＋PointPrimitiveCollection）：1.7 萬顆時每幀 25 ms → 8.3 ms，衛星連續移動

### v0.1.9（2026-11-19）

新增
- 任務規劃 `/mission`：點選雲量網格方格時，顯示該衛星的**地面最佳解析度（GSD）與影像幅寬估算**：公開規格（Vantor，PGC 整理：WorldView-1／2／3、GeoEye-1、WorldView Legion）、本次過頂高度下的天底值，以及該格的離天底角、入射角、斜距、全色／多光譜 GSD（沿軌、跨軌與幾何平均）與單一條帶幅寬（由規格反求視場角、投影至球面地表）。公式以公開規格的 20° 離天底值驗算。
- 雲量預報改為勾選後才計算（預設關閉），網格密度 2°／1°／0.5° 可選（預設 2°，地面軌跡左右各 4°），並顯示計算進度。

改進
- 總覽改畫各次過頂「通過可接收圈」的軌道段（以 TCA 為中心前後各 1/4 圈，裁切於時窗內），可直接點選該次過頂；天球圖以灰色虛線同時畫出其他過頂。

### v0.1.8（2026-11-18）

修正
- 任務規劃 `/mission`：選定過頂後另畫出「該次過頂所在的那一圈」軌道（以 TCA 為中心前後各半圈、衛星高度），與 30 秒標點同一時刻、同一高度而完全重合。先前可點選的彩色軌道只是時窗起點後的第一圈，地面軌跡每圈西移約 24°，與之後圈次的過頂標點對不上；該線現改標示為「時窗起點後第一圈」點選入口，選定後淡化。

### v0.1.7（2026-11-18）

新增
- 主選單加入「🧪 機動實驗室」按鈕，點選即在新分頁開啟 `/lab`（繁中／英／日）；先前只能手動輸入網址。
- 操作手冊 `/manual`：主選單「📘 操作手冊」開啟，涵蓋安裝、主畫面、各分析頁、實驗室、任務規劃、更新與常見問題；同一份手冊也放在 HF dataset 的 `MANUAL.md`。

### v0.1.6（2026-11-18）

新增
- **會合與機動實驗室 `/lab`**（第二階段 Sprint 0–3）：批次會合分析、場景 JSON、避碰決策、RPO 控制模擬四個分頁；繁中／英／日介面。
- **第二階段計算引擎 `src/phase2/`**：IAU-2006/2000A 框架轉換與 EOP、GCRF 數值傳播（J2–J4、阻力）、自適應近接極小值搜尋、Foster／Chan 碰撞機率、三態適用性篩選、協方差傳播、場景 schema 驗證、避碰方案搜尋、RPO 控制與 abort_to_hold。
- **`phase2_cli`**：與 Python 線上版逐層比對的命令列工具。
- **`/starlink`、`/story`、`/orbit-tuner`** 由 Python 版移植（先前顯示「尚未移植」說明頁）。

修改
- RPO 相對接近（`/rpo`）：取樣最小值前後逐秒精算 TCA，舊版快取自動重算。
- JSON 浮點數解析改為正確捨入（serde_json `float_roundtrip`），避免讀入的數值末位偏差。
- `sync_web.py` 一併同步 `static/docs`（故事頁引用的 PDF、QR 圖）與 Lab 頁面資產。

### v0.1.5（2026-11-17）

- 可自訂右下角 Logo（exe 同資料夾的 `logo.png`／`logo.jpg`）；接近事件排除對接中的太空站艙段；軌道歷史提示本地資料保留天數。
