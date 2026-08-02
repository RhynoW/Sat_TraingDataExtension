# maneuver_app.py 進度說明（期中報告用，2026-07-20 簡報）

**計畫案號**：TASA-S-1150268《智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究》
**執行期限**：2026-04-24 ～ 2026-11-30｜**契約期中截止**：2026-07-31
**本文件資料基準日**：2026-07-05｜**用途**：2026-07-20 期中簡報之 `maneuver_app.py`（Streamlit 儀表板）進度補充說明

---

## 〇、與既有期中預擬版報告的關係

計畫團隊完成期中預擬版報告
（`docs/CCITOrbitalManeuver_Midterm_Prelease_Report_20260624.doc`），內含 Layer 1–3 之正式驗證指標
（Recall/FAR/ROC-AUC 等，量測自 `leo_annotator/`、`Orbital_Maneuver_V2/` 等離線訓練與評估腳本）。
**本文件不重複、不覆蓋該報告的效能數字**，範疇限定在該報告所列「主要尚待事項」之一——
**Streamlit 視覺化儀表板（`maneuver_app.py`）**——說明其自 6/24 以來的實際進度。

> 6/24 版報告將「Streamlit 視覺化儀表板」列在「主要尚待事項」，但截至本文件撰寫時，
> `maneuver_app.py` 已是一個涵蓋 10+ 分析頁籤、整合三種偵測管線（TLE-SMA／MEME RTN／LightGBM ML）
> 與 SSA-RAG 問答系統的完整儀表板。**此項目的實際進度顯著領先 6/24 報告的描述**，建議正式期中報告
> （7/31 前交付）更新此條目狀態。

---

## 一、契約需求 vs. `maneuver_app.py` 現況對照

以下對照契約研究計畫書（`TASA_智慧化低軌通訊衛星軌道異常及太空事件偵測演算法研究_0510._v2.pdf`）
所定義的三層偵測架構，說明 **maneuver_app.py 這支程式本身** 涵蓋到哪些部分（不含 `leo_annotator/`
等獨立訓練/評估腳本——那些已在 6/24 報告中另行報告）。

| 契約項目 | 狀態 | maneuver_app.py 內證據 |
|---|---|---|
| Layer 1 閾值基準層（TLE-SMA 差分） | ✅ 完成 | `detect_maneuvers_refined_adaptive()`：5 個高度帶（300–500/500–600/600–700/700–1200/其他）自適應 mult/window/rate_mult/rate_floor |
| Layer 1（GEO 專屬） | ✅ 完成 | `render_geo_page()`：EW/NS/重定位/廢棄/TLE 空白五類事件，獨立分頁 |
| Layer 2 統計偵測層 CUSUM / BOCPD / SSA | 以其他演算法實作 | 僅有 `from scipy.signal import lombscargle`，用於「⬯ 長軸旋轉週期」頁籤估算拱點/節點週期，非變化點偵測，與契約要求用途不同 |
| Layer 3 XGBoost | ✅ 完成，已整合 | `load_ml_models()` 載入 `models/orbital_phase_v1.ubj`＋`activity_level_v1.ubj`，283 衛星訓練，CV Acc 96.1% |
| Layer 3 LightGBM（Plan B） | ✅ 完成，已整合 | `compute_lgbm_plan_b_features()`：20 特徵、26 天聚合窗口，模型檔 `Orbital_Maneuver_V2/models_plan_b/lgbm_maneuver_v1.pkl` |
| Layer 3 LSTM Autoencoder／Transformer | 以其他演算法實作 | 未在 `maneuver_app.py` 或全 repo 中找到對應程式碼 |
| RIC（徑向/沿跡/法向）ΔV 偵測 | ✅ 完成 | `calculate_ric_deltas()`、`detect_ric_events()`，高度自適應 min_dv（0.5/0.05/0.01 m/s） |
| 環境解耦（SMA 衰減 vs F10.7） | ✅ 完成 | `fetch_f107_data()`、`da_monotonic_decay` 旗標 |
| 軌道分類（LEO/MEO/GEO/GEO+/HEO 等四層分類） | ✅ 完成 | `classify_orbit()`：高度類別／偏心率形狀／幾何約束／任務狀態，含信心分數與判斷理由 |
| SSA-RAG 知識庫問答整合 | ✅ 完成 | `render_rag_auto_explain()`、`ssa_rag_client.py`，各分析頁自動將偵測結果轉自然語言送 RAG 解說 |
| DuckDB 結構化資料庫查詢 | ✅ 完成 | `load_data()` 查詢 `space_db.duckdb` / `tle_table` |

---

## 二、三層架構在 maneuver_app.py 中的落地情形

### Layer 1：閾值基準層 — 已完成並持續強化

`maneuver_app.py` 內建兩條 Layer 1 管線：

1. **TLE-SMA 差分管線**（LEO/MEO 分析頁）：`detect_maneuvers_refined_adaptive()` 依軌道高度分五個帶
   套用不同的跳變門檻與速率門檻，避免單一固定閾值在不同高度衛星上表現不一致。
2. **GEO 專屬管線**（GEO 機動分析頁）：以漂移率符號翻轉、傾角步進、SMA 持續超標等規則分別判定
   EW／NS／重定位／廢棄／TLE 空白五類事件。

兩條管線於本次 session 前已存在；本次新增的是**軌域自動路由**（見下節）。

### Layer 2：統計偵測層 — 尚未實作（如實揭露）

契約要求的 CUSUM、BOCPD、SSA（奇異譜分析）三種 7–30 天窗口統計變化點偵測方法，
在 `maneuver_app.py` 中**均未實作**。現有的 `scipy.signal.lombscargle` 匯入僅用於估算
軌道拱點/節點的長期旋轉週期（「⬯ 長軸旋轉週期」頁籤），是週期性特徵分析工具，
不是契約所指的變化點偵測器。

依 6/24 報告，此項目（連同 EP 漂移偵測器等替代方法）已在 `leo_annotator/` 中有其他進展
（`anomaly_detector.py` 3σ MAD、`ep_slope_detector.py` 同儕比較法），但這些**未整合進
`maneuver_app.py` 的 Streamlit 介面**，使用者目前無法在儀表板上直接看到這些方法的結果。

### Layer 3：AI 偵測層 — 傳統 ML 已完成，深度學習尚未開始

XGBoost（軌道相位 4 類 + 活動強度二元）與 LightGBM Plan B（26 天聚合機動分類器）
均已載入並整合進「🤖 ML 模型偵測」頁，可對任一 NORAD ID 即時推論並顯示機率、
特徵重要度、SSA-RAG 自動解說。LSTM Autoencoder 與 Transformer 依契約排程屬第三～
第五個月工作，目前尚未開始，不算落後於契約期程。

---

## 三、本次 session 完成的具體改進

以下四項改動今日完成，直接呼應契約「專案背景」第 3 點痛點
（「偵測靈敏度與誤報率(False Alarm)難以兼顧」），並已逐一以實際 NORAD 資料驗證：

1. **LEO/MEO／GEO 軌域自動判斷路由**：使用者在「LEO / MEO 分析」頁輸入 NORAD ID 執行分析時，
   程式先以 `classify_orbit()` 依中位數軌道要素判斷軌域，若歸類為 GEO／GEO+，
   自動改渲染 GEO 機動分析視圖，不再需要使用者自行判斷、手動切換分析模式。
   （驗證：NORAD 36032 正確自動切換；NORAD 66666 正確維持 LEO/MEO 視圖。）

2. **ML 模型偵測頁軌域守門警告**：套用同一軌域判斷，當偵測到 GEO/GEO+ 衛星時，
   於畫面顯示「此模型僅在 LEO 衛星（193–985 km）訓練，結果僅供參考」，避免模型被套用在
   訓練分布之外（out-of-distribution）的資料上而誤導判讀。
   （根因：訓練集 `training_samples_plan_b.csv` 14,023 筆樣本高度全部落在 193–985 km，
   完全不含 MEO/GEO 衛星。驗證：NORAD 49336（a≈42,164 km）正確觸發警告。）

3. **半長軸／高度並列顯示格式標準化**：LEO/MEO 與 ML 頁所有半長軸相關的表格欄位與圖表座標軸，
   統一改為「SMA(高度)」並列格式（例如 `6,942.2km(高度571.2km)`），圖表 Y 軸刻度同步標示對應高度。

4. **LightGBM 機動判定新增 TLE 資料缺口守門（降低誤報率的具體實證案例）**：
   - **問題發現**：NORAD 44349 半長軸在觀測期間平緩、連續下降（典型大氣阻力衰減特徵），
     但 ML 模型仍判定出 2 次高機率「機動」事件（p_maneuver ≈ 0.99）。
   - **根因分析**：比對觸發前後窗口的完整特徵向量，發現關鍵差異並非半長軸跳變，
     而是 `max_tle_gap_h`（視窗內最長 TLE 追蹤間隔）從正常的 24 小時暴增至 134–163 小時；
     長間隔導致 RAAN 殘差的 J2 長期進動率線性外推誤差被放大，單筆轉移的 Δraan_residual
     超過 0.1° 判定閾值而被標記，進而讓整個 26 天視窗被誤判為高機率機動。
   - **修正方式**：新增 `TLE_GAP_SUPPRESS_H = 48.0` 小時門檻，當視窗內最長 TLE 缺口超過門檻時，
     不論原始機率多高，直接壓制判定為非機動；同時套用於「單次推論」與「滾動趨勢圖」兩處，
     並在 UI 上以橘色標記／橘色區塊區隔「原本會誤報但已被壓制」的視窗，供使用者辨識。
   - **驗證結果**：NORAD 44349 原始 16 個高機率視窗（全期間）經此修正後全數正確壓制為非機動；
     擴大到完整資料期間測試，298 個滾動視窗中有 50 個因資料缺口被正確壓制、
     20 個維持為真實高機率警示。

---

## 四、已知落差與風險

| 項目 | 現況 | 風險/建議 |
|---|---|---|
| Layer 2 統計偵測層未整合進儀表板 | `leo_annotator/anomaly_detector.py`、`ep_slope_detector.py` 已有初步方法，但使用者無法在 `maneuver_app.py` 介面上查看 | 建議期中後優先評估：是否將這些既有腳本的輸出接入 Streamlit，而非從零開發 CUSUM/BOCPD/SSA |
| CUSUM／BOCPD／SSA 三種契約明列方法 | 全 repo 零實作 | 6/24 報告已列為優先待辦（預估 3–4 天工時），與本文件結論一致 |
| LSTM Autoencoder／Transformer | 未開始 | 依契約排程屬第三～五個月，暫不算落後 |
| 星系級異常分析（Δi 標準差／批量機動／陣型誤差） | `constellation_planes.py` 有 RAAN 分面與艦隊級統計，但三項契約指定指標均未實作 | 依契約排程屬第四個月，暫不算落後 |
| 資料清洗 quality_flag（good/suspect/rejected） | 未實作 | 6/24 報告已列為待辦，`maneuver_app.py` 目前以 P1 單調衰減抑制等規則替代 |

---

## 五、下一階段規劃

依 6/24 報告的優先順序建議，`maneuver_app.py` 端接續工作為：

1. 將 `leo_annotator/anomaly_detector.py`（3σ MAD 統計異常）與 `ep_slope_detector.py`
   （EP 同儕比較）的輸出接入 Streamlit 介面，作為 Layer 2 的過渡方案。
2. 視 Layer 2 CUSUM/BOCPD 開發進度，於「📊 趨勢分析」或「🔍 LightGBM 機動偵測」頁新增對應視覺化。
3. 持續以真實 NORAD 案例驗證各偵測管線在誤報率上的表現（比照本次 NORAD 44349 TLE 缺口案例的
   問題發現→根因分析→修正→驗證流程），作為期末報告效能評估的佐證素材。

---

## 附錄：本文件引用之關鍵檔案

- `maneuver_app.py`：`classify_orbit()`、`detect_maneuvers_refined_adaptive()`、
  `compute_lgbm_plan_b_features()`、`compute_lgbm_rolling_predictions()`、`render_geo_page()`、
  `render_ml_page()`、`format_sma_with_alt()`、`sma_axis_ticks()`、`TLE_GAP_SUPPRESS_H`
- `Orbital_Maneuver_V2/train.py`、`Orbital_Maneuver_V2/models_plan_b/`：LightGBM Plan B 訓練與模型檔
- `models/orbital_phase_v1.ubj`、`models/activity_level_v1.ubj`、`models/model_meta_v1.json`：XGBoost 模型
- `ssa_rag_client.py`：SSA-RAG 問答整合客戶端
- `docs/CCITOrbitalManeuver_Midterm_Prelease_Report_20260624.doc`：全計畫層級期中預擬版報告（本文件之對照基準）
