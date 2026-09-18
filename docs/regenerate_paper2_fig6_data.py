"""regenerate_paper2_fig6_data.py — 為圖六蒐集真實訓練曲線與 learning-rate 掃描資料。

回應 round5 review：圖六原本的訓練/驗證損失曲線與學習率敏感度皆為虛構示意資料
（見 generate_paper2_figures.py 舊版程式碼註解自陳「示意」），僅早停棵數 188
是實測值。本腳本用與生產模型完全相同之資料切分（Plan B, 20 特徵, seed=42）
產生兩組真實資料，供 generate_paper2_figures.py 的 fig6 讀取重繪：

(a) 訓練/驗證 binary logloss 逐棵記錄——**不作為生產模型**，另外用相同資料/
    參數/種子跑一次、僅用於畫圖（同時監控 train+val 會改變早停行為，見
    Orbital_Maneuver_V2/train.py 的說明，故與生產模型分開跑）。
(b) learning_rate ∈ {0.01, 0.02, 0.05, 0.1, 0.2} 五組真實獨立訓練（其餘參數
    與生產模型相同、val-only early stopping），記錄各自測試集 Precision
    （F-beta=0.5 最適閾值，與生產模型評估方式一致）。

輸出：docs/paper2_fig6_real_data.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Orbital_Maneuver_V2"))

import lightgbm as lgb
import numpy as np

import dataset as ds
import evaluate

HERE = Path(__file__).parent
PARQUET = HERE.parent / "data" / "maneuvers" / "training_dataset_final.parquet"
OUT_JSON = HERE / "paper2_fig6_real_data.json"

SEED = 42
BASE_PARAMS = dict(
    n_estimators=1000, num_leaves=15, min_child_samples=10,
    reg_lambda=1.0, class_weight="balanced", random_state=SEED, n_jobs=-1,
)


def load_split():
    import pandas as pd
    df = pd.read_parquet(PARQUET, engine="pyarrow")
    df = df[df["plan"] == "B"].copy().reset_index(drop=True)
    df = df.rename(columns={"label_binary": "label"}) if "label" not in df.columns else df
    df["label"] = df["label"].astype(int)
    present = [c for c in ds.PLAN_B_FEATURE_COLS if c in df.columns
               and not df[c].isna().all()]
    df = df.dropna(subset=present).reset_index(drop=True)
    train_df, val_df, test_df = ds.random_split(df, seed=SEED)
    return train_df, val_df, test_df, present


def capture_curve(train_df, val_df, present):
    """(a) 非生產訓練：同時監控 train+val 以取得雙曲線（僅供繪圖）。"""
    X_train, y_train = train_df[present], train_df["label"].values.astype(int)
    X_val, y_val = val_df[present], val_df["label"].values.astype(int)

    model = lgb.LGBMClassifier(learning_rate=0.05, **BASE_PARAMS)
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        eval_names=["train", "val"],
        callbacks=[lgb.log_evaluation(0)],  # 不設 early_stopping：跑滿 n_estimators 供完整曲線觀察
    )
    hist = model.evals_result_
    train_loss = hist["train"]["binary_logloss"]
    val_loss = hist["val"]["binary_logloss"]
    best_iter = int(np.argmin(val_loss)) + 1  # 1-indexed，與 booster best_iteration_ 定義一致
    print(f"[curve] n_trees={len(val_loss)}  best_iter(argmin val_logloss)={best_iter}  "
          f"best_val_logloss={min(val_loss):.5f}")
    return {"train_logloss": train_loss, "val_logloss": val_loss, "best_iter": best_iter}


def capture_lr_sweep(train_df, val_df, test_df, present):
    """(b) 真實 learning-rate 掃描：各自獨立訓練（val-only early stopping，同生產方法）。"""
    X_train, y_train = train_df[present], train_df["label"].values.astype(int)
    X_val, y_val = val_df[present], val_df["label"].values.astype(int)
    X_test, y_test = test_df[present], test_df["label"].values.astype(int)

    lr_grid = [0.01, 0.02, 0.05, 0.1, 0.2]
    results = []
    for lr in lr_grid:
        model = lgb.LGBMClassifier(learning_rate=lr, **BASE_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
        )
        proba_val = model.predict_proba(X_val)[:, 1]
        thr = evaluate.find_optimal_threshold_fbeta(y_val, proba_val, beta=0.5)
        proba_test = model.predict_proba(X_test)[:, 1]
        m = evaluate.compute_metrics(y_test, proba_test, threshold=thr)
        print(f"[lr-sweep] lr={lr:<5}  best_iter={model.best_iteration_:<5}  "
              f"test_precision={m['precision']:.4f}  test_recall={m['recall']:.4f}")
        results.append({"lr": lr, "best_iteration": int(model.best_iteration_ or 0),
                         "test_precision": m["precision"], "test_recall": m["recall"]})
    return results


def main():
    train_df, val_df, test_df, present = load_split()
    print(f"features={len(present)}  train={len(train_df)}  val={len(val_df)}  test={len(test_df)}")

    curve = capture_curve(train_df, val_df, present)
    lr_sweep = capture_lr_sweep(train_df, val_df, test_df, present)

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"curve": curve, "lr_sweep": lr_sweep, "production_lr": 0.05,
                   "seed": SEED, "n_features": len(present)}, fh)
    print(f"saved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
