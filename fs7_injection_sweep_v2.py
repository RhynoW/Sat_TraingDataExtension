#!/usr/bin/env python3
"""
fs7_injection_sweep_v2.py — 注入掃描進階版：定律係數、偏移診斷、平滑化因子
==========================================================================
承 fs7_injection_sweep.py（v1）之三項待辦：

A. 定律係數擬合：logistic( 命中 | log10 SNR_eff )，給出 50% 中點、斜率與
   叢集自助法（按窗重抽）95% CI；並以同資料比較 SNR_amp vs SNR_eff 的
   對數似然（模型選擇證據）。
B. 1× 殘餘偏移診斷：檢驗「密集節奏下相鄰 TLE 共享觀測 → 單步差分序列
   自相關 → 有效 σ 被低估」假說；量測各降頻帶去趨勢差分之 lag-1 自相關。
C. 擬合平滑化因子：以「斜坡注入」（機動被 SGP4 擬合窗攤平的近似）取代
   瞬時階躍，掃描斜坡寬 W ∈ {0, 0.25, 0.5, 1, 2 天}，量測 90% 門檻的
   膨脹倍率；並以定律 + 因子回檢研討會版實測的 ~1 km 分界與磁暴期預測。

輸入：v1 的 data/benchmark/fs7_injection_trials.csv（A/B 用）＋ space_db.duckdb（B/C 用）
輸出：data/benchmark/fs7_injection_smear.csv（C 彙總）
      data/benchmark/fs7_law_fit.json（A/B/C 全部係數與診斷）
      docs/fig_fs7_injection_v2.png（三聯圖：logistic 擬合／自相關／平滑化因子）
用法：python fs7_injection_sweep_v2.py [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

from fs7_injection_sweep import (FS7_NORADS, WIN, _detect_idx, load_series,
                                 quiet_windows, window_stats)

SMEAR_W = [0.0, 0.25, 0.5, 1.0, 2.0]                 # 斜坡寬（天）；0=瞬時階躍
SMEAR_DA = [0.05, 0.10, 0.20, 0.30, 0.50, 1.00]      # km
TOL = 2
N_BOOT = 200


# ── A. logistic 擬合與模型選擇 ────────────────────────────────────────────────

def _logit_fit(x_log: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """回傳 (中點 snr50, 斜率 beta, 平均對數似然)。純 numpy IRLS，避免外部相依。"""
    X = np.column_stack([np.ones_like(x_log), x_log])
    w = np.zeros(2)
    for _ in range(100):
        p = 1.0 / (1.0 + np.exp(-X @ w))
        W = np.clip(p * (1 - p), 1e-6, None)
        try:
            dw = np.linalg.solve((X * W[:, None]).T @ X, X.T @ (y - p))
        except np.linalg.LinAlgError:
            break
        w += dw
        if np.abs(dw).max() < 1e-10:
            break
    p = np.clip(1.0 / (1.0 + np.exp(-X @ w)), 1e-12, 1 - 1e-12)
    ll = float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    snr50 = float(10 ** (-w[0] / w[1])) if w[1] != 0 else float("nan")
    return snr50, float(w[1]), ll


def fit_law(tr: pd.DataFrame, rng) -> dict:
    out = {}
    for col in ("snr_amp", "snr_eff"):
        x = np.log10(tr[col].clip(1e-2, 1e4).values)
        y = tr["hit"].values.astype(float)
        snr50, beta, ll = _logit_fit(x, y)
        # 叢集自助（按窗重抽，保留窗內相關結構）
        keys = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
        uniq = keys.unique()
        groups = {k: np.where(keys.values == k)[0] for k in uniq}
        boots = []
        for _ in range(N_BOOT):
            pick = rng.choice(uniq, size=len(uniq), replace=True)
            idx = np.concatenate([groups[k] for k in pick])
            s50, _, _ = _logit_fit(x[idx], y[idx])
            boots.append(s50)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        out[col] = {"snr50": round(snr50, 2), "beta": round(beta, 2),
                    "mean_loglik": round(ll, 4),
                    "snr50_ci95": [round(float(lo), 2), round(float(hi), 2)]}
    out["delta_loglik_eff_minus_amp"] = round(
        out["snr_eff"]["mean_loglik"] - out["snr_amp"]["mean_loglik"], 4)
    return out


# ── B. 1× 偏移診斷：差分序列自相關 ───────────────────────────────────────────

def diagnose_autocorr(series: dict) -> dict:
    rows = {1: [], 2: [], 4: []}
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            for d in rows:
                t, a = t_all[s:e:d], a_all[s:e:d]
                if len(a) < 10:
                    continue
                slope = np.polyfit(t, a, 1)[0]
                dres = np.diff(a - slope * (t - t[0]))
                dres = dres - np.median(dres)
                if np.std(dres) == 0:
                    continue
                r1 = float(np.corrcoef(dres[:-1], dres[1:])[0, 1])
                rows[d].append(r1)
    return {f"decim_{d}": {"lag1_autocorr_median": round(float(np.median(v)), 3),
                           "n_windows": len(v)}
            for d, v in rows.items()}


# ── C. 斜坡注入（擬合平滑化近似）───────────────────────────────────────────────

def smear_trial(t, a, da_km, w_day, rng) -> bool:
    n = len(a)
    inj = int(rng.integers(n // 3, 2 * n // 3))
    t0 = t[inj]
    x = a.copy()
    if w_day <= 0:
        x[inj:] += da_km
        end_idx = inj
    else:
        ramp = np.clip((t - t0) / w_day, 0.0, 1.0)
        ramp[:inj] = 0.0
        x = x + da_km * ramp
        end_idx = int(np.searchsorted(t, t0 + w_day))
    hits = _detect_idx(x)
    return bool(len(hits) and ((hits >= inj - TOL) & (hits <= end_idx + TOL)).any())


def run_smear(series: dict, rng) -> pd.DataFrame:
    rows = []
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            t, a = t_all[s:e], a_all[s:e]          # 僅 1× 節奏（平滑化因子的基準）
            sigma, adot, dtm = window_stats(t, a)
            if sigma <= 0:
                continue
            for w in SMEAR_W:
                for da in SMEAR_DA:
                    hit = smear_trial(t, a, da, w, rng)
                    rows.append({"norad": nid, "win_start": s, "smear_day": w,
                                 "da_km": da, "hit": int(hit),
                                 "sigma_km": round(sigma, 4),
                                 "adot_kmday": round(adot, 5),
                                 "dt_day": round(dtm, 3)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    tr = pd.read_csv("data/benchmark/fs7_injection_trials.csv")
    series = load_series(args.db)
    result: dict = {}

    # A
    print("A. 定律係數擬合（logistic + 叢集自助 CI）…")
    result["law_fit"] = fit_law(tr, rng)
    for col in ("snr_amp", "snr_eff"):
        f = result["law_fit"][col]
        print(f"   {col}: SNR50={f['snr50']} (95%CI {f['snr50_ci95']}), "
              f"beta={f['beta']}, meanLL={f['mean_loglik']}")
    print(f"   ΔLL(eff−amp) = {result['law_fit']['delta_loglik_eff_minus_amp']} "
          f"{'→ SNR_eff 模型較佳 ✅' if result['law_fit']['delta_loglik_eff_minus_amp'] > 0 else '❌'}")

    # B
    print("\nB. 1× 偏移診斷：去趨勢差分 lag-1 自相關（負值＝擬合共享觀測之特徵）…")
    result["autocorr"] = diagnose_autocorr(series)
    for k, v in result["autocorr"].items():
        print(f"   {k}: median r1 = {v['lag1_autocorr_median']}  (n={v['n_windows']})")

    # C
    print("\nC. 斜坡注入掃描（擬合平滑化因子）…")
    sm = run_smear(series, rng)
    agg = (sm.groupby(["smear_day", "da_km"])
             .agg(n=("hit", "size"), detect_rate=("hit", "mean")).reset_index())
    agg["detect_rate"] = agg["detect_rate"].round(3)
    out = Path("data/benchmark")
    agg.to_csv(out / "fs7_injection_smear.csv", index=False, encoding="utf-8-sig")

    floors = {}
    for w in SMEAR_W:
        sub = agg[agg["smear_day"] == w].sort_values("da_km")
        ok = sub[sub["detect_rate"] >= 0.9]
        floors[w] = float(ok["da_km"].min()) if len(ok) else float("nan")
    base = floors[0.0]
    result["smear_floor90_km"] = {str(k): v for k, v in floors.items()}
    result["smear_factor"] = {str(k): (round(v / base, 2) if np.isfinite(v) and base else None)
                              for k, v in floors.items()}
    print("   90% 門檻 (km) 與膨脹倍率：")
    for w in SMEAR_W:
        fac = result["smear_factor"][str(w)]
        print(f"   W={w:4.2f} d → floor={floors[w]}  factor={fac}")

    # 定律回檢：研討會版情境預測
    snr50_eff = result["law_fit"]["snr_eff"]["snr50"]
    sf_1d = result["smear_factor"].get("1.0") or 1.0
    for name, sigma_m, adot_mday, dt_d in [
            ("2025 campaign（Δt=21.6h, 靜時 ȧ=49 m/day）", 15.0, 49.0, 0.9),
            ("Gannon 磁暴主相（ȧ=182 m/day）",           15.0, 182.0, 0.9)]:
        floor_law = snr50_eff * np.hypot(sigma_m, adot_mday * dt_d)   # 50% 檢出
        result.setdefault("law_backcheck", {})[name] = {
            "floor50_law_m": round(float(floor_law)),
            "floor50_with_smear_1d_m": round(float(floor_law * sf_1d))}
        print(f"   回檢 {name}: 定律 50% 門檻 ≈ {floor_law:.0f} m，"
              f"×平滑化因子(W=1d) ≈ {floor_law * sf_1d:.0f} m")

    with open(out / "fs7_law_fit.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 三聯圖 ────────────────────────────────────────────────────────────────
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(14, 4.2))
    # (1) logistic 擬合
    x = np.log10(tr["snr_eff"].clip(1e-2, 1e4))
    b = tr.copy(); b["bin"] = pd.cut(x, 18)
    g = b.groupby("bin", observed=True).agg(x=("snr_eff", "median"), y=("hit", "mean")).dropna()
    ax[0].plot(g["x"], g["y"], "o", ms=4, color="#1565C0", label="binned data")
    s50, beta = result["law_fit"]["snr_eff"]["snr50"], result["law_fit"]["snr_eff"]["beta"]
    xs = np.logspace(-1, 2.3, 200)
    ax[0].plot(xs, 1 / (1 + np.exp(-beta * (np.log10(xs) - np.log10(s50)))),
               "-", color="#C62828", label=f"logistic fit (SNR50={s50})")
    ax[0].set_xscale("log"); ax[0].set_xlabel("SNR_eff"); ax[0].set_ylabel("Detection rate")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=0.25); ax[0].set_title("(a) Sensitivity-law fit")
    # (2) 自相關
    ds = [1, 2, 4]
    vals = [result["autocorr"][f"decim_{d}"]["lag1_autocorr_median"] for d in ds]
    ax[1].bar([str(d) for d in ds], vals, color=["#1565C0", "#FF8F00", "#C62828"])
    ax[1].axhline(0, c="k", lw=0.8)
    ax[1].set_xlabel("cadence decimation"); ax[1].set_ylabel("median lag-1 autocorr of d(resid)")
    ax[1].set_title("(b) Serial correlation diagnosis"); ax[1].grid(alpha=0.25, axis="y")
    # (3) 平滑化因子
    ws = [w for w in SMEAR_W if np.isfinite(floors[w])]
    ax[2].plot(ws, [floors[w] * 1000 for w in ws], "o-", color="#1565C0")
    ax[2].set_xlabel("injection ramp width W (day)"); ax[2].set_ylabel("90% floor (m)")
    ax[2].set_title("(c) Fit-smearing inflation"); ax[2].grid(alpha=0.25)
    fig.suptitle("FS7 injection sweep v2: law coefficients, offset diagnosis, smearing factor")
    fig.tight_layout()
    fig.savefig("docs/fig_fs7_injection_v2.png", dpi=150)
    print("\n輸出：data/benchmark/fs7_injection_smear.csv, fs7_law_fit.json, "
          "docs/fig_fs7_injection_v2.png")


if __name__ == "__main__":
    main()
