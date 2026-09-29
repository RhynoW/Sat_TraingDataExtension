#!/usr/bin/env python3
"""s3_ratio_stats.py — 本專案 NRLMSIS 口徑 vs STORM-AI 實測軌道平均密度：比值分布、偏差、RMSE。

輸入 out/msis_hourly.parquet（s2 產出）。
兩種誤差口徑：
  (a) 絕對：R = ρ_true/ρ_model
  (b) 自我校準後：R / median_90d(R)——模擬 drag_residual 的 B_eff 中位數校準（常數倍率會被吸收，
      真正造成誤報的是「相對於平日比值」的偏離）。
分級：當下 3h ap 與當日 Ap 取大（quiet<15、active<48、G1-G2<111、G3<207、G4-G5≥207），
另以 OMNI2 Dst（quiet>−30、moderate −30~−100、intense −100~−250、super<−250）。
輸出：out/ratio_stats_by_class.csv、out/ratio_stats_dst.csv、out/gannon_timeseries.csv、out/lag_scan.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_common import OUT, load_omni2_hourly, storm_class, sw_features  # noqa: E402

KINDS = ["P0", "P1", "P0s", "P1s", "P2d", "P2"]
LABEL = {"P0": "P0 原版(日均Ap,經緯0)", "P1": "P1 現行寫法原樣(星下點;3hAp未生效)",
         "P0s": "P0s 經緯0+3hAp生效(sw9=-1)", "P1s": "P1s 星下點+3hAp生效(sw9=-1)",
         "P2d": "P2d 軌道平均,日均Ap", "P2": "P2 軌道平均,3hAp"}


def add_context(G: pd.DataFrame) -> pd.DataFrame:
    F = sw_features(pd.DatetimeIndex(G["t"]))
    G = G.reset_index(drop=True)
    G["ap3_now"], G["ap_day"] = F["ap3_l0"].to_numpy(), F["ap_day"].to_numpy()
    G["cls"] = storm_class(G["ap3_now"].to_numpy(), G["ap_day"].to_numpy())
    o = load_omni2_hourly()
    G["dst"] = o["dst"].reindex(pd.DatetimeIndex(G["t"]).floor("h")).to_numpy()
    G["dst_cls"] = np.select([G["dst"] > -30, G["dst"] > -100, G["dst"] > -250],
                             ["quiet(>-30)", "moderate(-30~-100)", "intense(-100~-250)"], "super(<-250)")
    G.loc[G["dst"].isna(), "dst_cls"] = "NA"
    return G


def calibrated(G: pd.DataFrame, k: str) -> np.ndarray:
    """R / 90 天滾動中位數（逐衛星），模擬 B_eff 中位數自我校準。"""
    out = np.full(len(G), np.nan)
    for sat, g in G.groupby("sat"):
        R = pd.Series(g["rho_true"].to_numpy() / g[f"rho_{k}"].to_numpy(), index=pd.DatetimeIndex(g["t"]))
        med = R.rolling("90D", center=True, min_periods=200).median()
        out[g.index] = (R / med).to_numpy()
    return out


def stats(r: np.ndarray) -> dict:
    r = r[np.isfinite(r) & (r > 0)]
    if len(r) == 0:
        return {}
    lr = np.log(r)
    rel = 1 / r - 1                                  # (ρ_model − ρ_true)/ρ_true
    return {"n": len(r), "median_ratio": np.median(r), "p05": np.percentile(r, 5),
            "p95": np.percentile(r, 95), "mean_ln": lr.mean(), "std_ln": lr.std(),
            "rmse_ln": np.sqrt((lr ** 2).mean()), "rmse_rel_pct": 100 * np.sqrt((rel ** 2).mean()),
            "frac_true_gt_1p5x": np.mean(r > 1.5)}


def main():
    G = pd.read_parquet(OUT / "msis_hourly.parquet")
    ok = np.isfinite(G["rho_true"]).to_numpy()
    for k in KINDS:                                  # 剔除太空天氣輸入異常（F10.7 閃焰污染等）造成的 NaN/inf
        x = G[f"rho_{k}"].to_numpy()
        ok &= np.isfinite(x) & (x > 1e-16) & (x < 1e-9)
    print(f"有效列 {ok.sum():,}/{len(G):,}（剔除 {(~ok).sum()}）")
    G = G[ok].reset_index(drop=True)
    G = add_context(G)
    for k in KINDS:
        G[f"R_{k}"] = G["rho_true"] / G[f"rho_{k}"]
        G[f"Rc_{k}"] = calibrated(G, k)
    G.to_parquet(OUT / "msis_hourly_ctx.parquet", index=False)

    # ── 時間對齊：真值 orbit-mean 的時間戳慣例（置中/落後）→ 以 lnP2 與 ln真值 之滯後相關檢查
    rows = []
    for sat, g in G.groupby("sat"):
        s_t = pd.Series(np.log(g["rho_true"].to_numpy()), index=pd.DatetimeIndex(g["t"]))
        s_m = pd.Series(np.log(g["rho_P2"].to_numpy()), index=pd.DatetimeIndex(g["t"]))
        dt = (s_t - s_t.rolling("3D", center=True).mean())
        dm = (s_m - s_m.rolling("3D", center=True).mean())
        for lag in range(-3, 13):
            c = dt.corr(dm.shift(lag, freq="h").reindex(dt.index))
            rows.append({"sat": sat, "lag_h": lag, "corr_detrended": c})
    L = pd.DataFrame(rows)
    L.to_csv(OUT / "lag_scan.csv", index=False, encoding="utf-8-sig")
    print("滯後掃描（ρ_model 延後 lag 小時與真值最相關處）：")
    print(L.loc[L.groupby("sat")["corr_detrended"].idxmax()].to_string(index=False))

    order = ["quiet", "active", "G1-G2", "G3", "G4-G5"]
    rows = []
    for k in KINDS:
        for cls in order + ["ALL"]:
            m = np.ones(len(G), bool) if cls == "ALL" else (G["cls"] == cls).to_numpy()
            for mode, col in [("absolute", f"R_{k}"), ("calibrated", f"Rc_{k}")]:
                rows.append({"kind": k, "label": LABEL[k], "class": cls, "mode": mode,
                             **stats(G.loc[m, col].to_numpy())})
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "ratio_stats_by_class.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print("\n=== 比值 ρ_true/ρ_model（全期間、全衛星；absolute / calibrated）===")
    print(S[["kind", "class", "mode", "n", "median_ratio", "p05", "p95", "mean_ln", "std_ln",
             "rmse_ln", "rmse_rel_pct"]].round(3).to_string(index=False))

    rows = []
    for k in KINDS:
        for cls in ["quiet(>-30)", "moderate(-30~-100)", "intense(-100~-250)", "super(<-250)"]:
            m = (G["dst_cls"] == cls).to_numpy()
            for mode, col in [("absolute", f"R_{k}"), ("calibrated", f"Rc_{k}")]:
                rows.append({"kind": k, "dst_class": cls, "mode": mode, **stats(G.loc[m, col].to_numpy())})
    pd.DataFrame(rows).to_csv(OUT / "ratio_stats_dst.csv", index=False, encoding="utf-8-sig")

    # ── 簡化本身的影響（模型對模型，不需真值）
    print("\n=== 簡化造成的 MSIS 內部差（ρ_P2/ρ_Px，中位數 [p05,p95]）===")
    for k in ["P0", "P1", "P0s", "P1s", "P2d"]:
        for cls in order:
            m = (G["cls"] == cls).to_numpy()
            r = (G.loc[m, "rho_P2"] / G.loc[m, f"rho_{k}"]).to_numpy()
            r = r[np.isfinite(r)]
            if len(r):
                print(f"  P2/{k:4s} {cls:6s} n={len(r):7d} med={np.median(r):.3f} "
                      f"[{np.percentile(r,5):.3f},{np.percentile(r,95):.3f}]")

    # ── Gannon 2024-05-08~15 時序
    gm = (G["t"] >= "2024-05-05") & (G["t"] < "2024-05-20")
    GT = G.loc[gm, ["sat", "t", "ap3_now", "ap_day", "dst", "rho_true"] + [f"rho_{k}" for k in KINDS]
               + [f"R_{k}" for k in KINDS] + [f"Rc_{k}" for k in KINDS]]
    GT.to_csv(OUT / "gannon_timeseries.csv", index=False, encoding="utf-8-sig")
    print("\n=== Gannon 期間（2024-05-10 12:00 ~ 05-12 12:00）逐衛星 真值/模型 比值峰值與中位 ===")
    pk = G[(G["t"] >= "2024-05-10 12:00") & (G["t"] < "2024-05-12 12:00")]
    for sat, g in pk.groupby("sat"):
        msg = " ".join(f"{k}:med{g[f'R_{k}'].median():.2f}/max{g[f'R_{k}'].max():.2f}"
                       f"(校準後 med{g[f'Rc_{k}'].median():.2f})" for k in ["P0", "P1", "P2"])
        print(f"  {sat:10s} n={len(g)} {msg}")


if __name__ == "__main__":
    main()
