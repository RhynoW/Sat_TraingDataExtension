#!/usr/bin/env python3
"""s4_ratio_model.py — LightGBM 學 ln(ρ_true/ρ_NRLMSIS)，時間切分，2024（含 Gannon）為測試集。

仿 STORM-AI 冠軍（BiMA：在 NRLMSIS 2.1 上學比值/對數比值）的精神，但目的不同：本專案要的是
「hindcast 阻力殘差」，故為 nowcast（只用 ≤t 的指標），不做 3 天預報。

兩個基底（各訓一個模型）：
  M1  y = ln(ρ_true/ρ_P1)  → 可直接乘回 atmospheric_drag 現行 density() 的單點值（drop-in）
  M2  y = ln(ρ_true/ρ_P2)  → 乘回軌道平均 MSIS（建議的物理改良版）
特徵（皆可由 Celestrak SW + TLE 取得，=可部署）：3h ap 滯後 0–24h、24–72h 均值、24h max/sum、
  F10.7(當日/前日)、F81、日 Ap(當日/前日)、年週期、UTC 時、高度、星下點緯度/地方時、升降段、
  LTAN、ln ρ_base。另訓 M2+OMNI（加 Dst/AE/Bz/Vsw，研究用、非必要）比較上限。
切分：train < 2023-01-01；valid = 2023（early stopping）；test = 2024。
輸出：out/model_M1.txt、out/model_M2.txt、out/model_M2omni.txt、out/model_test_metrics.csv、
      out/model_test_pred.parquet、out/feature_importance.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_common import OUT, sw_features  # noqa: E402

GEOM = ["alt_proj", "lat0", "lst0_s", "lst0_c", "asc0", "ltan_s", "ltan_c", "ln_rho_base"]


def geom_features(G: pd.DataFrame, base: str) -> pd.DataFrame:
    X = pd.DataFrame(index=G.index)
    X["alt_proj"] = G["alt_proj"].to_numpy()
    X["lat0"] = G["lat0"].to_numpy()
    X["lst0_s"], X["lst0_c"] = np.sin(2 * np.pi * G["lst0"] / 24), np.cos(2 * np.pi * G["lst0"] / 24)
    X["asc0"] = G["asc0"].astype(float).to_numpy()
    X["ltan_s"], X["ltan_c"] = np.sin(2 * np.pi * G["ltan"] / 24), np.cos(2 * np.pi * G["ltan"] / 24)
    X["ln_rho_base"] = np.log(G[f"rho_{base}"].to_numpy())
    return X


def build_X(G: pd.DataFrame, base: str, with_omni=False) -> pd.DataFrame:
    F = sw_features(pd.DatetimeIndex(G["t"]), with_omni=with_omni)
    F.index = G.index
    return pd.concat([F, geom_features(G, base)], axis=1)


PARAMS = dict(objective="regression", learning_rate=0.03, num_leaves=63, min_data_in_leaf=300,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
              verbose=-1, seed=42)


def fit(X, y, tr, va):
    dtr = lgb.Dataset(X[tr], y[tr])
    dva = lgb.Dataset(X[va], y[va])
    return lgb.train(PARAMS, dtr, 4000, valid_sets=[dva],
                     callbacks=[lgb.early_stopping(200, verbose=False)])


def rm(lr):
    lr = lr[np.isfinite(lr)]
    return np.sqrt(np.mean(lr ** 2)), 100 * np.sqrt(np.mean((np.exp(-lr) - 1) ** 2))


def cal(G, ratio):
    """比值 / 逐衛星 90 天滾動中位數（模擬 B_eff 校準）。"""
    out = np.full(len(G), np.nan)
    for sat, g in G.groupby("sat"):
        R = pd.Series(ratio[g.index], index=pd.DatetimeIndex(g["t"]))
        out[g.index] = (R / R.rolling("90D", center=True, min_periods=200).median()).to_numpy()
    return out


def main():
    G = pd.read_parquet(OUT / "msis_hourly_ctx.parquet")
    G = G[np.isfinite(G["rho_true"]) & np.isfinite(G["ltan"])].sort_values(["sat", "t"]).reset_index(drop=True)
    t = pd.DatetimeIndex(G["t"])
    tr = (t < "2023-01-01"); va = (t >= "2023-01-01") & (t < "2024-01-01"); te = t >= "2024-01-01"
    print(f"樣本：train {tr.sum():,}（{t[tr].min():%Y-%m}~{t[tr].max():%Y-%m}）、valid {va.sum():,}、"
          f"test {te.sum():,}（{t[te].min():%Y-%m-%d}~{t[te].max():%Y-%m-%d}）")
    print("test 衛星：", G.loc[te, "sat"].value_counts().to_dict())

    preds, rows, imps = {}, [], []
    for name, base, omni in [("M1", "P1", False), ("M2", "P2", False), ("M2omni", "P2", True)]:
        X = build_X(G, base, with_omni=omni)
        y = np.log(G["rho_true"] / G[f"rho_{base}"]).to_numpy()
        ok = np.isfinite(y)
        m = fit(X, y, tr & ok, va & ok)
        m.save_model(str(OUT / f"model_{name}.txt"))
        p = m.predict(X, num_iteration=m.best_iteration)
        preds[name] = (base, p)
        imp = pd.Series(m.feature_importance("gain"), index=X.columns).sort_values(ascending=False)
        imps.append(imp.rename(name))
        print(f"{name}: best_iter={m.best_iteration}, 前 8 重要特徵：{list(imp.index[:8])}")

    # ── 測試集評估（逐分級 + Gannon 窗）
    Gt = G.copy()
    for name, (base, p) in preds.items():
        Gt[f"lr_base_{name}"] = np.log(G["rho_true"] / G[f"rho_{base}"])
        Gt[f"lr_corr_{name}"] = Gt[f"lr_base_{name}"] - p
        Gt[f"rho_corr_{name}"] = G[f"rho_{base}"] * np.exp(p)
    Gt["Rc_corr_M1"] = cal(Gt, (Gt["rho_true"] / Gt["rho_corr_M1"]).to_numpy())
    Gt["Rc_corr_M2"] = cal(Gt, (Gt["rho_true"] / Gt["rho_corr_M2"]).to_numpy())
    gannon = (t >= "2024-05-10 12:00") & (t < "2024-05-13 00:00")
    oct24 = (t >= "2024-10-10 12:00") & (t < "2024-10-12 00:00")
    segs = {"test_ALL": te, "test_quiet": te & (G["cls"] == "quiet"), "test_active": te & (G["cls"] == "active"),
            "test_G1-G2": te & (G["cls"] == "G1-G2"), "test_G3": te & (G["cls"] == "G3"),
            "test_G4-G5": te & (G["cls"] == "G4-G5"), "Gannon_2024-05-10~12": gannon,
            "Oct2024_storm_10~11": oct24}
    for seg, m in segs.items():
        m = np.asarray(m)
        r = {"segment": seg, "n": int(m.sum())}
        for name in preds:
            rb, pb = rm(Gt.loc[m, f"lr_base_{name}"].to_numpy())
            rc, pc = rm(Gt.loc[m, f"lr_corr_{name}"].to_numpy())
            r[f"{name}_base_rmse_ln"], r[f"{name}_corr_rmse_ln"] = rb, rc
            r[f"{name}_base_rmse_rel%"], r[f"{name}_corr_rmse_rel%"] = pb, pc
            r[f"{name}_improve_rel%"] = 100 * (1 - pc / pb) if pb else np.nan
            r[f"{name}_median_ratio_after"] = float(np.exp(np.nanmedian(Gt.loc[m, f"lr_corr_{name}"])))
            r[f"{name}_median_ratio_before"] = float(np.exp(np.nanmedian(Gt.loc[m, f"lr_base_{name}"])))
        for name in ["M1", "M2"]:
            base = preds[name][0]
            rc_b = Gt.loc[m, f"Rc_{base}"].to_numpy(); rc_c = Gt.loc[m, f"Rc_corr_{name}"].to_numpy()
            r[f"{name}_calib_median_before"] = float(np.nanmedian(rc_b))
            r[f"{name}_calib_median_after"] = float(np.nanmedian(rc_c))
        rows.append(r)
    M = pd.DataFrame(rows)
    M.to_csv(OUT / "model_test_metrics.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    cols = ["segment", "n"] + [c for c in M.columns if ("rmse_rel%" in c or "improve" in c or "median_ratio" in c or "calib" in c)]
    print(M[cols].round(3).T.to_string())
    pd.concat(imps, axis=1).to_csv(OUT / "feature_importance.csv", encoding="utf-8-sig")
    keep = ["sat", "t", "cls", "ap3_now", "ap_day", "dst", "rho_true", "rho_P0", "rho_P1", "rho_P2",
            "rho_corr_M1", "rho_corr_M2", "rho_corr_M2omni"]
    Gt.loc[te, keep].to_parquet(OUT / "model_test_pred.parquet", index=False)


if __name__ == "__main__":
    main()
