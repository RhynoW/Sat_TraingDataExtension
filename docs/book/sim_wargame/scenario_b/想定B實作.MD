# 想定 B 實作紀錄：致盲致聾

> 日期：2026-11-21｜對象：Rust 單機版「太空兵棋」（`RUST_SatDashboard/`，v0.1.17 工作版）
> 狀態：已實作、已建置、已推演、介面已實測；**尚未 commit**，正式版執行檔尚未更新
> 行號：已更新為第二階段（參數覆寫）實作後的 `games_war.rs`
> 相關文件：[想定設計說明](../../../../RUST_SatDashboard/docs/games_war_scenarios.md)｜[推演報告](推演報告_想定B致盲致聾.md)｜[想定 A 實作紀錄](../scenario_a/想定A實作.MD)

## 1. 摘要

依美國國防情報局（DIA）《Challenges to Security in Space 2026》繁中譯本「致盲並致聾敵人」的描述，在兵棋中加入想定 B。紅方除了切纜與干擾通信，還會干擾導航（GPS）與偵察（SAR、雷射致盲）；藍方多了全天候 SAR 偵察與備援定位授時兩種行動。

推演結果：頻寬、定位授時、偵察三者互相排擠，哪種打法最好取決於計分權重。在紅方灰色地帶策略下，只看頻寬時「均衡」排第 1（92.5%）；用遊戲計分時「均衡＋備援」排第 1（84.3 分），均衡掉到第 5。每組 500 局。

## 2. 想定依據

頁碼為繁中譯本頁碼，均已逐條核對譯本原文。

| DIA 描述 | 頁碼 | 對應機制 |
|---|---|---|
| 偵察、通信、導航與預警衛星可能成為「致盲並致聾敵人」的攻擊目標 | p.18 | 紅方 AI 優先干擾導航與偵察 |
| PLA 演習例行納入上下行鏈路干擾，可能用以拒止 GPS 導航 | p.31–32 | 紅方 `jam_gps` |
| 中國商業組織為 PLA 開發針對 SAR 的干擾器 | p.32 | 紅方 `jam_sar` |
| 地面雷射可干擾 LEO 衛星；致眩列為雷射用途 | p.32、69 | 沿用原有 `dazzle` |
| 電子攻擊針對 PNT，常干擾鄰近地區民用 | p.15 | GPS 干擾紀錄註明「波及民用」 |
| 俄方 GPS 干擾；Sentinel-1 SAR 遭干擾 | p.43 | 佐證兩種干擾都有實例 |
| SAR 提供全天候、晝夜覆蓋 | p.28 | 藍方 `sar_isr` 不受雲量影響 |

**不是來自 DIA 的部分**

- 把「致盲並致聾」寫成紅方 AI 的行動優先順序，是推演假設。
- 備援定位授時的做法和效果，DIA 沒有討論。
- 所有效果數值與計分權重都是示意值。

## 3. 規則變更

### 新行動

| 行動 | 陣營 | 點數 | 效果 | 示意參數 |
|---|---|---|---|---|
| `jam_gps` 干擾 GPS | 紅 | 1 | 當回合藍方定位授時降到 30%；藍方有備援時 80%。升級 +1 | `B_PNT_JAMMED = 0.3`、`B_PNT_BACKUP = 0.8` |
| `jam_sar` 干擾 SAR | 紅 | 1 | 當回合藍方 SAR 成功率減半。升級 +1 | 減半 |
| `sar_isr` SAR 全天候偵察 | 藍 | 2 | 2 次過頂，每次 80%，不受雲量與雷射致盲影響；每次成功 +3 分 | `B_SAR_P = 0.8` |
| `pnt_backup` 備援定位授時 | 藍 | 2 | 下回合起永久生效 | — |

這 4 個行動只在想定 B 可用。其他想定下，伺服器會拒絕人類玩家的命令，並在裁決時過濾掉 AI 送出的命令。

### AI

| 陣營 | 變更 |
|---|---|
| 紅方（想定 B） | 優先順序：切纜（70% 機率）→ 干擾 GPS → 雷射致盲 → 藍方用過 SAR 後干擾 SAR → 剩餘點數干擾低軌、網攻、認知作戰。雷射致盲只下一次，避免重複 |
| 藍方 `sensor` 重感測 | 先建備援，每回合 SAR，第 0 回合強化閘道站，之後剩餘點數修纜或租 GEO |
| 藍方 `hybrid` 均衡＋備援 | 第 0 回合建備援、租 GEO、強化閘道站；之後每回合修纜（沒有可修的就部署低軌）加 SAR |

`sensor`、`hybrid` 在其他想定會退回均衡打法。

### 計分（只限想定 B）

| 陣營 | 公式 |
|---|---|
| 藍方 | 頻寬 × 100 + 偵察成功 × 3 + 聲望 − （1 − 定位授時平均）× 20 |
| 紅方 | 原公式 + （1 − 定位授時平均）× 20 − 偵察成功 × 3 |

紅方的對稱項是推演時發現缺口後補上的（見第 6 節）。原始想定與想定 A 的計分不變。

### 變體

| 代號 | 內容 |
|---|---|
| `b_typhoon` | 想定 B，另外第 0 到 1 回合颱風：雲量 85%，修纜延後 1 回合 |

## 4. 程式變更

`git diff --numstat`（相對 HEAD，含想定 A 的變更）：`games_war.rs` +161／−17、`games_war.js` +44／−13、`games.html` +8／−5，合計 +213／−35 行。

### 4.1 後端 `src/games_war.rs`

| 位置 | 變更 |
|---|---|
| [L42–46](../../../../RUST_SatDashboard/src/games_war.rs#L42-L46)、[L89–91](../../../../RUST_SatDashboard/src/games_war.rs#L89-L91) | 常數 `B_PNT_JAMMED`、`B_PNT_BACKUP`、`B_SAR_P`；`scen_name()` 統一判斷合法想定代號（取代原本散在兩處的 `match`） |
| [L149–150](../../../../RUST_SatDashboard/src/games_war.rs#L149-L150) | `cost()`：`sar_isr`、`pnt_backup` 2 點；`jam_gps`、`jam_sar` 1 點 |
| [L161–173](../../../../RUST_SatDashboard/src/games_war.rs#L161-L173) | `is_blue()` 加入藍方新行動；新增 `b_only()`（想定 C 實作時改為 `scen_only()`，由 `allowed()` 統一判斷） |
| [L207–211](../../../../RUST_SatDashboard/src/games_war.rs#L207-L211) | `War` 新增 `pnt_backup_from`、`pnt`、`sar_seen`、`sar_ok`、`sar_try` |
| [L278–285](../../../../RUST_SatDashboard/src/games_war.rs#L278-L285) | 想定 B 開場紀錄；`b_typhoon` 設定開場颱風 |
| [L299](../../../../RUST_SatDashboard/src/games_war.rs#L299) | `is_b()`：精確比對 `b`、`b_typhoon` |
| [L363–377](../../../../RUST_SatDashboard/src/games_war.rs#L363-L377) | 藍方 AI `sensor`、`hybrid` |
| [L437–447](../../../../RUST_SatDashboard/src/games_war.rs#L437-L447) | 紅方 AI 想定 B 的優先順序；原本的雷射致盲在想定 B 不再重複下令 |
| [L458–470](../../../../RUST_SatDashboard/src/games_war.rs#L458-L470) | 裁決：非想定 B 時過濾 B 專屬行動；讀取 GPS、SAR 干擾；建立備援 |
| [L576–578](../../../../RUST_SatDashboard/src/games_war.rs#L576-L578) | 紅方 `jam_gps`、`jam_sar` 的效果與紀錄文字 |
| [L634–647](../../../../RUST_SatDashboard/src/games_war.rs#L634-L647) | SAR 偵察判定（使用後 `sar_seen = true`）；當回合定位授時 |
| [L677–683](../../../../RUST_SatDashboard/src/games_war.rs#L677-L683) | `scores()`：定位授時平均；想定 B 的藍方扣分與紅方對稱計分 |
| [L694](../../../../RUST_SatDashboard/src/games_war.rs#L694) | `view()` 回傳 `pnt`、`pnt_backup`（`pnt_backup` 只給藍方與白方） |
| [L770](../../../../RUST_SatDashboard/src/games_war.rs#L770) | `war_orders`：非想定 B 時拒絕 B 專屬行動 |
| [L834](../../../../RUST_SatDashboard/src/games_war.rs#L834) | `war_mc` 新增回傳 `pnt_avail`、`isr_ok`、`sar_ok`、`blue_score`、`red_score` |
| `record()` | `history` 每回合新增 `pnt` |

定位授時的判定：

```rust
// 當回合：沒被干擾 100%；被干擾時看備援是否已生效（建立後下回合起）
self.pnt = if !gps_jammed { 1.0 } else if t >= self.pnt_backup_from { B_PNT_BACKUP } else { B_PNT_JAMMED };
```

### 4.2 前端

| 檔案 | 變更 |
|---|---|
| `web/ext/games.html` | 兩個想定選單加入「想定 B」「想定 B＋開場颱風」；藍方 AI 選單加入「重感測」「均衡＋備援」（標註僅想定 B）；頁尾 DIA 出處加入想定 B 頁碼 |
| `web/ext/games_war.js` | `ACTS` 加入 4 個新行動，非想定 B 時不顯示；`DESC` 新行動說明；`SCEN` 想定說明；`isB()`、`SCEN_NAME`；狀態表加「定位授時」列；教練提示加 2 條；終局復盤與蒙地卡羅在想定 B 時加入 `sensor`、`hybrid`；蒙地卡羅表加「定位授時」「偵察成功（SAR）」「藍方分數」3 欄，結論同時列出頻寬最高和藍方分數最高的打法 |

### 4.3 文件

- `RUST_SatDashboard/docs/games_war_scenarios.md`：新增「想定 B」一節（依據、機制對照、AI、範圍限制、變體），並更新想定一覽和 API。
- `docs/book/sim_wargame/scenario_a/想定A實作.MD`：行號連結依本次變更更新。

## 5. API

| 端點 | 新參數 | 新回傳 |
|---|---|---|
| `POST /api/games/war/new` | `scenario`：加入 `b`、`b_typhoon` | — |
| `GET /api/games/war/state` | — | `pnt`、`pnt_backup`；`history[].pnt` |
| `POST /api/games/war/orders` | 行動：`sar_isr`、`pnt_backup`（藍）；`jam_gps`、`jam_sar`（紅） | 非想定 B 時回傳錯誤「這個行動只在想定 B 可用」 |
| `POST /api/games/war/mc` | `scenario`：加入 `b`、`b_typhoon`；`blue` 可用 `sensor`、`hybrid` | `results[].pnt_avail`、`isr_ok`、`sar_ok`、`blue_score`、`red_score` |

範例：

```json
POST /api/games/war/mc
{"runs": 500, "blue": ["balanced", "geo", "leo", "repair", "hybrid", "sensor"], "red": "balanced", "scenario": "b"}
```

## 6. 實作過程中發現並修正的問題

| 問題 | 發現方式 | 修正 |
|---|---|---|
| `is_b()` 用「開頭是 b」判斷，`base` 也被當成想定 B | 冒煙測試：原始想定的定位授時變成 30% | 後端 `is_b()` 與前端 `isB()` 都改為精確比對 |
| 紅方 AI 在想定 B 會下兩次雷射致盲 | 檢查 AI 程式 | 想定 B 只在 B 區塊下一次 |
| 「重感測」太極端（頻寬 65%） | 冒煙測試 | 另加折衷打法「均衡＋備援」 |
| 紅方分數不反映致盲致聾的成敗：藍方越重視感測，紅方分數越高（對重感測 +11.8） | 推演結果的紅方分數 | 想定 B 的紅方計分加入對稱項 |
| 蒙地卡羅結論寫「目前最佳：均衡」，但均衡的定位授時只有 30%、偵察 0 次 | 介面實測 | 想定 B 時加「藍方分數」欄，結論同時列出頻寬最高與分數最高的打法，並註明取決於權重 |
| 圖：數值標籤撞到面板標題，原始想定與想定 B 相同時點被蓋住 | 檢視輸出圖 | 標籤移到點右側；原始想定改用空心大圈；圖例移到圖下方 |

## 7. 建置與測試

### 建置

建置時，[games_war.rs](../../../../RUST_SatDashboard/src/games_war.rs) 以外的 [games_debris.rs](../../../../RUST_SatDashboard/src/games_debris.rs) 正在被其他工作改動（17:13 修改，有 `f107_at` 未定義的編譯錯誤）。我沒有動那個檔案，改用以下方式建置：

1. 把 crate 複製到 scratchpad。
2. `games_debris.rs` 換成 HEAD 版本。
3. 用獨立的 `CARGO_TARGET_DIR` 建置。

建置結果無警告、無錯誤。**注意：這表示正式目錄目前無法建置，要等碎片連鎖那邊的修改完成。**

### 測試

測試時另開一個實例（`--port 5091`），測完只停止自己啟動的 PID。

| 測試 | 結果 |
|---|---|
| 回歸：原始想定 | 修正 `is_b()` 後，均衡 85.8%、重 GEO 84.4%，與想定 A 推演時的原始想定數字相同 |
| 回歸：想定 A | 均衡 83.7%、重 GEO 86.7%，與想定 A 報告相同 |
| 全部組合 | 3 個想定 × 2 種紅方 × 4 或 6 種藍方 × 500 局 |
| 手算核對 | 均衡＋備援的 SAR 成功次數 2 × 0.8 + 12 × 0.4 = 6.4；重感測 1.6 + 14 × 0.4 = 7.2；定位授時 (0.3 + 7 × 0.8) ÷ 8 = 73.8%，都與模擬值相同 |
| Playwright（msedge） | 原始想定不顯示 B 專屬按鈕；想定 B 顯示 SAR 與備援按鈕；下令後狀態表出現「定位授時 30%（GPS 遭干擾）；備援已建立」，紀錄出現 SAR 與 GPS 干擾；蒙地卡羅表出現新欄位與雙結論；**無 JS 錯誤** |

## 8. 推演結果摘要

紅方灰色地帶策略。完整表格、判讀與限制見[推演報告](推演報告_想定B致盲致聾.md)。

| 藍方打法 | 頻寬：原始 | 頻寬：B | 定位授時（B） | 偵察成功（B） | 遊戲計分（B） | 計分名次 |
|---|---|---|---|---|---|---|
| 均衡 | 85.8% | 92.5% | 30.0% | 0.0 | 70.7 | 5 |
| 重 GEO | 84.4% | 84.4% | 30.0% | 4.7 | 76.6 | 4 |
| 重低軌 | 72.4% | 86.8% | 30.0% | 4.2 | 77.4 | 3 |
| 重修纜 | 76.7% | 76.7% | 30.0% | 0.9 | 59.2 | 6 |
| 均衡＋備援 | — | 74.2% | 73.8% | 6.4 | 84.3 | 1 |
| 重感測 | — | 65.4% | 73.8% | 7.2 | 78.7 | 2 |

判讀時要注意的模型現象：

- 紅方致盲致聾後，藍方頻寬反而上升，是因為紅方每回合固定 5 點，用在導航與偵察就排擠掉低軌干擾與網攻。
- 原有 4 種藍方打法的定位授時都是 30%，是因為這些 AI 不會使用新行動。
- 計分名次取決於權重；偵察每次成功的價值低於約 0.9 分時，均衡打法會重新領先。

## 9. 已知限制

1. 30%、80%（定位授時）、80%（SAR）與計分權重都是示意值。
2. 定位授時是單一數字，沒有區分使用者；GPS 干擾波及民用只寫在紀錄文字中。
3. 預警衛星沒有納入。
4. 紅方看到 SAR 一次就每回合干擾，是簡化。
5. 沒有做計分權重與紅方行動點數的敏感度分析。

## 10. 檔案清單

| 檔案 | 狀態 |
|---|---|
| `RUST_SatDashboard/src/games_war.rs` | 修改 |
| `RUST_SatDashboard/web/ext/games_war.js` | 修改 |
| `RUST_SatDashboard/web/ext/games.html` | 修改 |
| `RUST_SatDashboard/docs/games_war_scenarios.md` | 修改 |
| `docs/book/sim_wargame/scenario_a/想定A實作.MD` | 修改（行號） |
| `docs/book/sim_wargame/scenario_b/run_scenario_b.py` | 新增：推演腳本 |
| `docs/book/sim_wargame/scenario_b/results.csv`、`summary.md`、`example_game_seed1001.json`、`scenario_b_tradeoff.png` | 新增：推演輸出 |
| `docs/book/sim_wargame/scenario_b/推演報告_想定B致盲致聾.md` | 新增 |
| `docs/book/sim_wargame/scenario_b/想定B實作.MD` | 本文件 |

## 11. 待辦

| 項目 | 說明 |
|---|---|
| commit | 等作者決定（想定 A、B 與 Cosmos 1408 驗證都還沒 commit） |
| 正式目錄建置 | 要等 `games_debris.rs` 的修改完成才能建置 |
| 敏感度分析 | 計分權重（偵察 0 到 5 分、定位授時 0 到 40）；紅方行動點數 5 對 7 |
| 想定 C、D | 共軌接近、直升式反衛星 |
