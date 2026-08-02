# maneuver_app_2026August.py — 機動偵測儀表板（2026-08 定版，前身 July 緊湊版）

單頁式 Streamlit 儀表板，整合本專案三層偵測架構（規則／統計／ML）與 SSA-RAG 知識庫解說，
對單顆衛星做端到端的機動偵測與判讀。

```bash
streamlit run maneuver_app_2026August.py
```

> 與舊版 `maneuver_app.py`（4,400 行、多頁）的關係：july 版是配合最新模型
> （`models_meme` / `models_meme_forecast` / `models_fusion`）的精簡重寫，改為
> **單頁線性流程**。SSA-RAG 功能於 2026-07-16 自舊版移植進來。

---

## 1. 相依與資料來源

| 類型 | 項目 | 說明 |
|---|---|---|
| 資料庫 | `space_db.duckdb` → `raw_tle_archive` | TLE 主要來源（唯讀連線） |
| 專案模組 | `maneuver_strategies_july` (ms) | P1–P6 規則、`build_transitions`、`classify_orbit` |
| | `statistical_detectors` (sd) | CUSUM／BOCPD／SSA／3σ-MAD |
| | `data_quality_audit` (dqa) | quality_flag 稽核 |
| | `constellation_anomaly` (ca) | 星系級異常 |
| | `atmospheric_drag` | NRLMSIS 阻力殘差、再入判定（可選，失敗則降級） |
| | `build_training_dataset` (btd) | ML 特徵計算 |
| | `ssa_rag_client` / `app_dialogue_client` | SSA-RAG 問答與信箱（可選） |
| 模型 | `Orbital_Maneuver_V2/models_meme/` | **Model 1**：逐窗口偵測（監督式） |
| | `Orbital_Maneuver_V2/models_meme_forecast/` | forecast：未來 1 天機動機率 |
| | `Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl` | **Model 2**：無監督異常 |
| | `models_fusion/fusion_scorer.pkl` | 五通道融合評分器 |
| 檔案 | `f107_cache.csv`、`data/url_registry.csv` | F10.7、衛星名稱對照 |
| | `data/meme_truth/transitions_full_*.csv` | MEME 真值（艦隊統計用） |
| | `data/raw/<sat_name>/` | MEME 精密星曆（⑤ 比較用） |

**設計原則**：所有可選相依都以 `try/except` 包住，缺件時該區塊顯示一行說明並降級，
不會讓整頁崩潰。

---

## 2. 側邊欄控制項

| 控制項 | 預設 | 說明 |
|---|---|---|
| NORAD ID / 名稱 / wildcard | `STARLINK-30273` | 支援 `57681`、`STARLINK-30273`、`STARLINK-30*`、`SL-1?` |
| P2 vertex 高度 (km) | 700 | 拋物線頂點；高於此值取 floor |
| P2 floor 閾值 (km) | 0.4 | 閾值下限 |
| P2 @400km 閾值 (km) | 2.0 | 400 km 處的參考閾值 |
| P5 vertex F10.7 (sfu) | 70 | 太陽活動倍率拋物線頂點 |
| P5 @200sfu 倍率 | 1.6 | 200 sfu 處的參考倍率 |
| SSA-RAG 服務位址 | `http://127.0.0.1:8000` | RAG 服務端點 |
| 執行後自動送 RAG 解說 | 開啟 | 把 ③ 的偵測結果自動送 RAG |
| 💬 App 對話面板 | — | 與 SSA-RAG Server 經信箱互傳訊息 |

查詢命中多顆時（wildcard）會出現「選擇衛星」下拉；日期範圍以該衛星 TLE 的
實際起訖為界，可再縮小。

---

## 3. 頁面區塊

頁面由上而下線性渲染。編號沿用舊版需求編號，**顯示順序非數字順序**：
① ② ③ ⑤ ⑥ ⑦ ⑩ ⑧（④ 預設隱藏）。

### 🎯 統一偵測摘要（頁首）
`orbit_anomaly_detector.OrbitAnomalyDetector` 依軌域自動路由，一眼看出結論：
軌域／域、路由主判、融合旗標、Model 2 異常數。偵測到**自然再入衰減**時直接
判「機動 = 0」並以紅框示警。

### ① 軌道根數連續變化與差值
4×2 子圖：左為 a / i / e / RAAN 時序，右為 Δa / Δi / Δe / ΔRAAN 殘差。
- 🔴 紅叉 = P1–P6 合併偵測
- 🟢 綠星 = NRLMSIS 主判機動（扣大氣阻力後 |Δa 殘差| > 0.30 km），**同時標在 a 曲線與 Δa 圖**，
  使根數圖與主判一致

### ② P1–P6 策略：個別 vs 合併
每個策略的旗標／抑制數、類型（偵測／抑制／最終），右側列出各策略註解。
可展開「P2 / P5 拋物線曲線預覽」即時看滑桿的效果。

### ③ 統計偵測層 ＋ ML 偵測/預測
**本頁核心**。先做**自動路由**：

| 條件 | 主判 | 交叉驗證 |
|---|---|---|
| Starlink（Model 1 分布內） | **Model 1**（監督式） | NRLMSIS 殘差、Model 2 |
| 非 Starlink（OOD） | **NRLMSIS 阻力殘差 + Model 2**（regime-agnostic） | Model 1 僅供參考，可能失準 |

依序呈現：
1. **主判結果卡**（3 個指標，依路由變換）
2. **統計層四圖**：CUSUM／BOCPD／SSA／3σ-MAD 分數與事件
3. **ML forecast**（可展開）：未來 1 天內出現 ≥5 km 機動之機率
4. **Model 1 逐窗口偵測**：模型原始機率曲線 + 門檻線 + 過閘門的旗標
5. **Model 2**：NRLMSIS 阻力殘差（σ）與異常點
6. **融合評分器**：五通道 → 單一連續機率（AUC 0.98／AP 0.96／large recall 0.97）
7. **🤖 SSA-RAG 自動解說**（見 §4）

### ⑤ MEME vs TLE（僅 72h）
以 `data/raw/<sat_name>/` 的精密星曆比對 TLE 外推位置誤差（0–72 h），
輸出中位與 P95。**刻意不做長時程外推**。

### ⑥ 資料品質稽核
`quality_flag`：good／suspect／rejected 統計、主因、依旗標著色的 sma 時序，
非 good 的明細表可下載複核。

### ⑦ 星系級異常分析
偵測到已知星系時才啟用（按鈕觸發，大型星系需 10–20 秒）：
① 軌道面一致性（同 RAAN 面 Δi std）② 批量機動識別（同天顯著機動衛星數 > mean+3σ）
③ 陣型誤差（緯度幅角相位殘差 std）。對應事件分類：批量部署／星系重組／戰術機動。

### ⑩ 合成 TLE 批次生成
以 `synthetic_tle` 依條件（衛星數／天數／間隔／含機動比例／高度／傾角／ΔV／雜訊／種子）
批次生成並下載 `synthetic.tle`。

### ⑧ SSA-RAG 知識問答
互動問答（主題篩選 + 範例問題 + 自訂輸入），回傳答案、信心度與來源文件。

### ④ 艦隊級統計（**預設隱藏**）
```python
_SHOW_FLEET_STATS = False   # 改 True 即復原
```
全 MEME 284 顆的機動 episode 率 + bootstrap 95% CI、各偵測器 vs MEME 真值。
使用者於 2026-07-14 要求先隱藏。

---

## 4. SSA-RAG 整合

### 4.1 元件
| 函式 | 用途 |
|---|---|
| `_rag_health_cached(base_url)` | 健康檢查（快取 60 秒） |
| `_rag_ask_cached(base_url, q, topic)` | 問答（**快取 1 小時**，避免 Streamlit rerun 重複打 RAG） |
| `build_tle_maneuver_narrative(...)` | P1–P6 偵測結果 → 自然語言 |
| `build_ml_maneuver_narrative(...)` | Model 1／融合結果 → 自然語言 |
| `render_rag_auto_explain(narrative, ...)` | 送 RAG 並顯示解說（**health-first**：服務離線只留一行提示） |
| `render_ssa_rag_page(base_url)` | ⑧ 互動問答頁 |
| `render_dialogue_panel()` | 側邊欄 App 對話（**非 RAG**，僅兩 App 間協調） |

`client_id="maneuver_app_july"`，方便 Server 端 `logs/qa_log.jsonl` 辨識來源。

### 4.2 敘述設計：兩個關鍵防呆（皆由實測逼出）

**① 帶正負號的 Δa_net（修「GEO 絕對加總幻覺」）**

敘述除了事件清單，還附「事件方向統計 + **帶號 Δa_net**」，並明示
「累積 |Δa| 恒為正、僅代表活動量級、**不代表方向**；判斷方向務必以 Δa_net 正負號為準」。

> **為何需要**：GEO 站位保持會產生數百筆微小混合事件，淨值近零或負，
> 但「累積 |Δa|」絕對加總恒正。實測 RAG 曾把它讀成淨值而判「軌道抬升」
> （31306 ASTRA 1L 淨 −3.90 km、52904 MEASAT 3D 淨 −0.38 km）。
> 加上帶號 Δa_net 後，兩顆重測皆正確判「軌道維持」。

**② 註明 Δa_net 的來源（避免 Server 自檢誤判）**

敘述加註「Δa_net 由偵測系統就**全部 N 次事件**計算所得，為本題**給定之輸入事實**；
清單僅節錄前 10 筆，Δa_net 不需由清單自行推算」。

> **為何需要**：Server 端自檢會在「答案引用了具體數值、但清單有省略」時
> 判該數值無依據並降級信心。實測 100 顆中觸發 25 筆、且 **25/25 全被壓為 low**。
> 加註後觸發率降至 2–4%，信心分佈由 low 主導翻轉為 high 主導。

### 4.3 相關工具（本目錄）
| 檔案 | 用途 |
|---|---|
| `rag_answer_check.py` | 方向一致性檢查（v4 結構化判定）：`sign_conflict` / `phrasing_warning` |
| `rag_test_july_10sat.py` | 十星批測（`--seed` / `--exclude` / `--norads` / `--geo` / `--tag`） |
| `rag_test_100sat.py` | 大規模批測（`--round` / `--batches` / `--batch-offset`），含節流、續跑、當機重試 |
| `tests/test_rag_answer_check.py` | 檢查器單元回歸（25 案例） |
| `tests/rag_checker_validate.py` | 檢查器語料驗證（243 筆歷史答案） |
| `tests/rag_regression.py` | RAG 服務端 CI 回歸（5 案例，需服務） |

---

## 5. 快取策略

| 裝飾器 | 對象 | 理由 |
|---|---|---|
| `@st.cache_data` | 各 loader、`compute_*_detection` | 純資料，依參數快取 |
| `@st.cache_resource` | `_get_oad()`、`_load_fusion()` | 模型物件，全域共用一份 |
| `@st.cache_data(ttl=60)` | RAG 健康檢查 | 服務狀態會變 |
| `@st.cache_data(ttl=3600)` | RAG 問答 | 同一敘述一小時內不重複查詢 |

`compute_ml_detection` 在 TLE > 220 筆時**等距抽樣至 220 點**以控制計算量。

---

## 6. 重要行為說明

**物理閘門（Model 1 旗標的必要條件）**
```
flag = (模型機率 ≥ 門檻) AND (NRLMSIS 扣阻力後 |殘差 Δa| > 0.30 km)
```
NRLMSIS 不可得時退回高度自適應 |Δa| 閾值。目的：正確扣除大氣阻力（含 F10.7/Ap），
使**純衰減與太陽極大期不誤報**。

**再入守門**：`is_reentry_decay()` 判定自然再入時，NRLMSIS 主判直接令
`is_maneuver = False`。理由：劇烈非線性衰減超出準 secular 阻力模型的適用範圍，
不套用機動模型。

**OOD 警示**：Model 1 僅在 Starlink 上訓練，對非 Starlink 屬分布外。頁面會明確
標示並改用 regime-agnostic 的 Model 2 / NRLMSIS 為主判——這是刻意的設計，
避免使用者誤信 OOD 機率值。

**純衰減偵測**：整段 |Δa| 皆低於高度自適應閾值時，顯示警告說明「模型原始機率偏高
係分布外，已由物理閘門正確濾除為 0」。

---

## 7. 已知限制

- **Model 1 僅適用 Starlink**（監督式訓練域）。非 Starlink 一律走 Model 2 / NRLMSIS。
- **⑤ 僅比較 72 小時**，且需 `data/raw/<sat_name>/` 有該衛星的 MEME 星曆。
- **④ 艦隊統計預設隱藏**（`_SHOW_FLEET_STATS = False`）。
- **SSA-RAG 服務由 Server 端啟動**，本 app 不自行啟動 uvicorn；服務離線時
  自動解說只留一行提示，不影響其他區塊。
- `rag_answer_check` 的**後綴反轉標記**仍是片語表（反向／逆向／之外／以外…），
  非封閉集合，新變體仍需實測補。
