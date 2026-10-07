# 交叉驗證：da_monotonic_decay（Orbital_Maneuver_V2）vs 離軌候選啟發式（SatDashboard）

**驗證日期**：2026-09-09
**驗證對象**：`data/url_registry.csv` 284 顆 MEME-truth Starlink 艦隊（同一批衛星，兩套獨立實作）

## 方法

| | da_monotonic_decay（`build_training_dataset.py`） | 離軌候選啟發式（`scenario04/physics/starlink_census.py::deorbiting_norad_ids()`） |
|---|---|---|
| 判定窗 | 近 7 天逐 epoch 滑動窗 | 近 30 天（另要求近 5 天內仍有 TLE） |
| 條件 | frac_neg≥0.85 且無單次跳變>2km 且 bstar_mean>0 且淨 Δa<−2km | 近 30 天 Δa≥40km 且目前高度<480km |
| 設計目的 | 排除「純大氣阻力衰減」以降低機動誤判（FP） | 找出「目前正在離軌」的候選，供即時名單/再入估算用 |

對本艦隊近 10 天原始 TLE（`space_db.duckdb::raw_tle_archive`）分別套用兩套邏輯，取交集/差集比對。

## 結果

- 本艦隊中，`starlink_census` 標記 19 顆離軌候選；`da_monotonic_decay` 標記 8 顆；**兩者交集為 0**。
- **這不是缺陷，是兩套邏輯本就針對不同母體**：
  - **僅 census 標記的 19 顆**：淨 7 天 Δa 達 −19～−76 km（快速下降），但**全數因「單次跳變>2km」被 da_monotonic_decay 排除**——即這批衛星在快速降軌過程中夾雜了離散的推進事件（符合 SpaceX 對除役星實施**主動控制離軌**的已知作法），da_monotonic_decay 判定為「非純阻力衰減」是正確行為，因為這確實不是純被動衰減。
  - **僅 da_monotonic_decay 標記的 8 顆**：淨 7 天 Δa 僅 −2～−21 km（緩降）、frac_neg 0.94–1.00（近乎單調、無跳變），高度已在 338–462 km——符合「無主動控制、純阻力緩慢衰減」的失效衛星特徵，但因 30 天降幅尚未達 40km 門檻，故未被 census heuristic 捕捉（該衛星群後續加速衰減時應會被 census 追上）。
- 本艦隊近 10 天 TLE 之 `bstar` 欄位涵蓋率 100%（Starlink 專屬，非全庫平均的 ~11%），排除了 bstar 缺值造成偽陰性的疑慮。

## 結論（供期末報告引用）

兩套獨立建立的衰減判定邏輯**互補而非重複**：`da_monotonic_decay` 抓「純被動衰減」（適合排除機動誤判），`starlink_census` 離軌啟發式抓「快速降軌」（多半伴隨主動控制離軌事件，適合即時再入預警）。**建議**：若未來需要一個「全面涵蓋所有離軌型態」的判定，應取兩者**聯集**而非任一單獨使用，否則會系統性漏掉其中一種衰減模式（純阻力型 or 主動控制型）。

明細見（分析當次產出、未納入版控）：`_cross_validate_dmd_detail.csv`（284 顆逐星 frac_neg／net7_km／bstar_mean／判定原因）。
