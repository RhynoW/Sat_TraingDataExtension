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
| `/starlink` | Starlink 分析（v0.1.6）：可見性／RTT／遮蔽、星系普查、殼層、離軌名單與離軌預測（NRLMSISE-00 完整移植） |
| `/story`、`/story/{sid}` | StoryMap 故事頁（v0.1.6）：群組統計、ISR 解析度、雷達評估、重訪、軌跡 |
| `/orbit-tuner` | Orbit Tuner 介紹頁（v0.1.6） |
| `/manual` | 操作手冊（v0.1.9；原稿 `scenario-advanced01/docs/SatDashboard_操作手冊_v*.md`，`tools/build_manual.py` 產生頁面） |
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

### 網路圖磚與 Himawari

- 圖資目錄沿用 `Rust_WMTS_Server/static/layers.js`（同步為 `web/static/js/map_layers.js`）：NLSC、中研院百年歷史地圖、臺北市歷史圖資、地調中心液化潛勢、防災／地籍等疊圖。
- Cesium 以 WebGL 貼圖使用圖磚，遠端沒有 CORS 標頭就會被擋，因此一律走本機代理 `/api/tiles/*`；快取在 `%LOCALAPPDATA%\SatDashboard\tile_cache`（可用 `SATDASH_TILE_CACHE` 改位置），看過的區域離線也能顯示。代理只放行圖資目錄出現過的網域與 NASA GIBS。
- Himawari 全圓盤（地球儀疊圖）：NASA GIBS 重投影之 Himawari-9 AHI 紅外 Band 13／可見光 Band 3／氣團 RGB，每 10 分鐘，可回看 24 小時並播放近 2 小時動畫；資料約落後 1 小時。
- JMA 最新全圓盤影像（面板內顯示與下載）：取自 [JMA 氣象衛星中心](https://www.data.jma.go.jp/mscweb/data/himawari/list_fd_.html)，約落後 10~20 分鐘；紅外、可見光、水氣、真彩色、氣團、Sandwich、夜間微物理、沙塵等 10 種。JMA 檔名只有時分、每天覆蓋，`/api/himawari/jma_latest` 以 Last-Modified 找今天最新的一格，`/api/himawari/jma_img` 代理影像（`dl=1` 下載）。影像為地球同步視角且已含海岸線，不疊到地球儀上。
- 需要 `geojson` 檔或金鑰的疊圖（OSM 主題、攝影機、Sentinel、Google 等）不在此面板內。

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
