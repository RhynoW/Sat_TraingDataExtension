# 阻力殘差修正與下游重跑（2026-09-29）

## 結論

1. `atmospheric_drag.py` 兩項修正本身影響很小：全量 284 星 125,721 轉換中，僅 103 筆跨越 0.3 km 閘門（0.08%，全在 ≤550 km）。
2. **重大發現：舊阻力殘差檔造成缺值洩漏。** 舊檔 `data/drag/drag_resid_20260714.csv` 只到 07-14；三層擂台單元中 79.6% 正樣本、49.7% 負樣本落在 07-14 之後，缺值補 0，「阻力缺值」成為時間代理訊號（單獨 AUC 0.647）。L3 融合學到它。
3. 同一資料庫（2026-09-28）、只換阻力檔的對照：

| 指標 | 舊檔 | 新檔 |
|---|---|---|
| 擂台 L3 融合 OOF AUC | 0.891 | 0.812 |
| 擂台 L3 不含阻力通道 | 0.798 | 0.797 |
| 擂台「僅阻力」基線 AUC | 0.381 | 0.627 |
| 融合評分器 ROC-AUC | 0.891 | 0.811 |
| 融合評分器 TPR_large | 0.686 | 0.638 |

   舊檔帶來的 +0.092 幾乎全是洩漏；真實物理阻力貢獻約 +0.013。
   **09-21 勘誤文件的擂台 L3 AUC 0.902 受此洩漏灌水。** 候選確認式 L3（`three_layer_candidate_eval.py`）不用阻力，不受影響。

4. MEME LightGBM（併入新阻力特徵後重訓，指令已重現原模型門檻值）：

| 模型 | 原訓練指令 | 測試 AUC 舊 | 測試 AUC 新 |
|---|---|---|---|
| models_meme | `train.py --parquet ... --plan A --min-severity medium --task window` | 0.6166 | 0.6171 |
| models_meme_forecast | `train.py --parquet ... --plan A --min-severity medium --task forecast --horizon-days 1` | 0.6609 | 0.6614 |

5. Model 2（IsolationForest）：開關 off/on 召回 0.204/0.205、精確 0.416/0.420、FORMOSAT-3A 誤報 0/0。
   IDS 域外逐窗 FPR：重訓 off 0.040、重訓 on 0.038、**原部署 model2.pkl＋新程式 0.032**（與 08-02 發表值一致）→ 建議保留原 model2.pkl。

## 狀態

- 已寫入正式位置：`data/drag/drag_resid_20260928.csv`（下游 glob 會自動採用）、`data/benchmark/*_20260928.csv`（擂台新檔版）。
- **未安裝**（自動模式權限擋下覆寫正式模型）：本資料夾的 `lgbm_meme_window/`、`lgbm_meme_forecast/`、`training_dataset_final_newdrag.parquet`、`fusion_new/models_fusion__fusion_scorer.pkl`。安裝前請先備份原檔。
- 舊檔版對照結果：`arena_old/`、`fusion_old/`。

## 重現

- `scripts/run_sandboxed.py`：以 `DRAG_CSV`、`STORM_AP`、`OUT_DIR` 執行任一下游腳本，模型與 CSV 全導向 OUT_DIR。
- `scripts/leak_check.py`：缺值洩漏檢驗。
- `scripts/drag_full_compare.py`、`scripts/drag_impact.py`：開關 off/on 殘差比對。
