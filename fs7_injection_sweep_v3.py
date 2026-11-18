#!/usr/bin/env python3
"""
fs7_injection_sweep_v3.py — 審查必做三項：完整叢集自助、指標套組、平臺檢定
==========================================================================
承 v1/v2，落實期刊審查之三項「必做」：

A. 完整叢集自助（單位＝衛星×安靜窗，即獨立叢集）：
   SNR50、斜率 β、ΔLL(eff−amp) 三者之 95% CI；報告有效叢集數。
B. 指標套組（逐條件）：recall（±2 步容差 vs 固定 ±1.0 天容差兩種口徑）、
   precision、FAR（每星每 30 天誤旗標數）、偵測延遲（中位天）、事件碎裂率
   （一次注入引出 >1 個鄰近旗標之比例）。
C. 低幅平臺檢定：注入端最小幅度之命中率 vs 匹配對照窗（未注入、同分布
   偽注入位置、同容差）之巧合命中率——叢集自助差值 CI 判定是否統計相容。

輸出：
  data/benchmark/fs7_injection_metrics.csv   指標套組（條件 × 指標）
  data/benchmark/fs7_law_fit_v3.json         A/C 之係數、CI、檢定
  docs/fig_fs7_injection_metrics.png         雙聯圖（容差對照 / FAR–recall 操作點）
用法：python fs7_injection_sweep_v3.py [--seed 42]
      python fs7_injection_sweep_v3.py --pub   （只重繪：由 fs7_injection_metrics.csv 重建，不連 DB；
                                                輸出 docs/figures_pub/fig_fs7_injection_metrics/ 四版本）
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

import numpy as np
import pandas as pd

from fs7_injection_sweep import (DA_GRID, DECIM, MIN_PTS, _detect_idx,
                                 load_series, quiet_windows, window_stats)
from fs7_injection_sweep_v2 import _logit_fit

sys.path.insert(0, str(Path(__file__).resolve().parent / "docs"))
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402

TOL_STEP = 2          # 步數容差（v1 同）
TOL_DAY = 1.0         # 固定時間容差（天）——審查要求之對照口徑
FRAG_SPAN = 5         # 注入後歸因旗標的樣本跨距
N_BOOT = 500
PLATEAU_DA = 0.05     # 平臺檢定的低幅端（km，≤此值）


def run_trials(series: dict, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    """回傳 (注入試驗表, 對照窗表)。"""
    tr_rows, ctl_rows = [], []
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            for d in DECIM:
                t, a = t_all[s:e:d], a_all[s:e:d]
                n = len(a)
                if n < MIN_PTS:
                    continue
                sigma, adot, dtm = window_stats(t, a)
                if sigma <= 0:
                    continue
                key = dict(norad=nid, win_start=s, decim=d,
                           sigma_km=round(sigma, 4), adot_kmday=round(adot, 5),
                           dt_day=round(dtm, 3), span_day=round(float(t[-1] - t[0]), 2))

                # ── 對照窗：未注入之旗標行為 + 偽注入巧合命中 ────────────────
                flags0 = _detect_idx(a)
                pinj = int(rng.integers(n // 3, 2 * n // 3))
                ctl_rows.append({**key,
                    "n_flags": len(flags0),
                    "far_per30d": round(len(flags0) / max(t[-1] - t[0], 1e-6) * 30.0, 3),
                    "coinc_step": int(bool(len(flags0) and np.abs(flags0 - pinj).min() <= TOL_STEP)),
                    "coinc_time": int(bool(len(flags0) and np.abs(t[np.clip(flags0, 0, n - 1)] - t[pinj]).min() <= TOL_DAY)),
                })

                # ── 注入試驗 ────────────────────────────────────────────────
                for da_km in DA_GRID:
                    inj = int(rng.integers(n // 3, 2 * n // 3))
                    x = a.copy(); x[inj:] += da_km
                    flags = _detect_idx(x)
                    near = flags[np.abs(flags - inj) <= TOL_STEP]
                    near_t = flags[np.abs(t[np.clip(flags, 0, n - 1)] - t[inj]) <= TOL_DAY]
                    attrib = flags[(flags >= inj - TOL_STEP) & (flags <= inj + FRAG_SPAN)]
                    fp = flags[flags < inj - TOL_STEP]           # 注入前之旗標＝誤報
                    after = flags[flags >= inj]
                    delay_d = float(t[int(after.min())] - t[inj]) if len(after) else np.nan
                    tr_rows.append({**key, "da_km": da_km,
                        "hit_step": int(len(near) > 0),
                        "hit_time": int(len(near_t) > 0),
                        "n_attrib": int(len(attrib)),
                        "n_fp": int(len(fp)),
                        "delay_day": round(delay_d, 3) if np.isfinite(delay_d) else np.nan,
                        "snr_eff": round(da_km / np.hypot(sigma, adot * dtm), 2),
                    })
    return pd.DataFrame(tr_rows), pd.DataFrame(ctl_rows)


def cluster_boot(tr: pd.DataFrame, rng, n_boot=N_BOOT) -> dict:
    """A：SNR50/β/ΔLL 之衛星×窗叢集自助。"""
    keys = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
    uniq = keys.unique()
    groups = {k: np.where(keys.values == k)[0] for k in uniq}
    y = tr["hit_step"].values.astype(float)
    x_eff = np.log10(tr["snr_eff"].clip(1e-2, 1e4).values)
    sig = tr["sigma_km"].values
    x_amp = np.log10((tr["da_km"] / sig).clip(1e-2, 1e4).values)

    def fit_all(idx):
        s50e, be, lle = _logit_fit(x_eff[idx], y[idx])
        s50a, ba, lla = _logit_fit(x_amp[idx], y[idx])
        return s50e, be, lle - lla
    s50, beta, dll = fit_all(np.arange(len(y)))
    boots = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([groups[k] for k in pick])
        boots.append(fit_all(idx))
    b = np.array(boots)
    ci = lambda col: [round(float(np.percentile(b[:, col], q)), 3) for q in (2.5, 97.5)]
    return {"n_trials": int(len(y)), "n_clusters_effective": int(len(uniq)),
            "snr50": round(s50, 2), "snr50_ci95": ci(0),
            "beta": round(beta, 2), "beta_ci95": ci(1),
            "delta_ll_per_sample": round(dll, 4), "delta_ll_ci95": ci(2),
            "n_boot": n_boot}


def plateau_test(tr: pd.DataFrame, ctl: pd.DataFrame, rng, n_boot=N_BOOT) -> dict:
    """C：低幅平臺 vs 匹配對照之巧合命中率，叢集自助差值 CI。"""
    out = {}
    lo = tr[tr["da_km"] <= PLATEAU_DA]
    for d in DECIM + ["pooled"]:
        li = lo if d == "pooled" else lo[lo["decim"] == d]
        ci_ = ctl if d == "pooled" else ctl[ctl["decim"] == d]
        if not len(li) or not len(ci_):
            continue
        k1 = (li["norad"].astype(str) + "_" + li["win_start"].astype(str)).values
        k2 = (ci_["norad"].astype(str) + "_" + ci_["win_start"].astype(str)).values
        u1, u2 = np.unique(k1), np.unique(k2)
        g1 = {k: np.where(k1 == k)[0] for k in u1}
        g2 = {k: np.where(k2 == k)[0] for k in u2}
        y1, y2 = li["hit_step"].values.astype(float), ci_["coinc_step"].values.astype(float)
        diff = float(y1.mean() - y2.mean())
        boots = []
        for _ in range(n_boot):
            i1 = np.concatenate([g1[k] for k in rng.choice(u1, len(u1), replace=True)])
            i2 = np.concatenate([g2[k] for k in rng.choice(u2, len(u2), replace=True)])
            boots.append(float(y1[i1].mean() - y2[i2].mean()))
        lo_ci, hi_ci = np.percentile(boots, [2.5, 97.5])
        out[str(d)] = {"plateau_rate": round(float(y1.mean()), 3),
                       "control_coinc_rate": round(float(y2.mean()), 3),
                       "diff": round(diff, 3),
                       "diff_ci95": [round(float(lo_ci), 3), round(float(hi_ci), 3)],
                       "consistent": bool(lo_ci <= 0 <= hi_ci)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    series = load_series(args.db)
    print("重跑注入試驗（含延遲/碎裂/FP/雙容差）…")
    tr, ctl = run_trials(series, rng)
    print(f"注入試驗 {len(tr)} 筆、對照窗 {len(ctl)} 筆")

    # B：指標套組彙總
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    agg = (tr.groupby(["da_km", "decim", "drag_band"], observed=True)
             .agg(n=("hit_step", "size"),
                  recall_step=("hit_step", "mean"),
                  recall_time=("hit_time", "mean"),
                  tp=("hit_step", "sum"), fp=("n_fp", "sum"),
                  delay_med_day=("delay_day", "median"),
                  frag_rate=("n_attrib", lambda x: float((x > 1).mean())))
             .reset_index())
    agg["precision"] = (agg["tp"] / (agg["tp"] + agg["fp"]).clip(lower=1)).round(3)
    for c in ("recall_step", "recall_time", "frag_rate"):
        agg[c] = agg[c].round(3)
    ctl["drag_band"] = pd.qcut(ctl["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    far = (ctl.groupby(["decim", "drag_band"], observed=True)["far_per30d"]
              .median().reset_index().rename(columns={"far_per30d": "far_per30d_med"}))
    agg = agg.merge(far, on=["decim", "drag_band"], how="left")
    out = Path("data/benchmark")
    agg.to_csv(out / "fs7_injection_metrics.csv", index=False, encoding="utf-8-sig")

    print("\nA. 完整叢集自助（衛星×窗）…")
    law = cluster_boot(tr, rng)
    print(f"   有效叢集數={law['n_clusters_effective']}（試驗 {law['n_trials']} 筆非獨立）")
    print(f"   SNR50={law['snr50']} CI{law['snr50_ci95']}  beta={law['beta']} CI{law['beta_ci95']}")
    print(f"   ΔLL/樣本={law['delta_ll_per_sample']} CI{law['delta_ll_ci95']} "
          f"{'（CI 全正 → SNR_eff 顯著較佳）' if law['delta_ll_ci95'][0] > 0 else '（未達顯著）'}")

    print("\nC. 低幅平臺 vs 匹配對照窗（Δa ≤ %g km）…" % PLATEAU_DA)
    plat = plateau_test(tr, ctl, rng)
    for k, v in plat.items():
        print(f"   decim={k}: 平臺 {v['plateau_rate']} vs 對照 {v['control_coinc_rate']} "
              f"差 {v['diff']} CI{v['diff_ci95']} → {'統計相容 ✅' if v['consistent'] else '不相容'}")

    print("\nB. 指標套組（節錄：decim=1, drag=mid）：")
    sub = agg[(agg["decim"] == 1) & (agg["drag_band"] == "mid")]
    print(sub[["da_km", "recall_step", "recall_time", "precision",
               "far_per30d_med", "delay_med_day", "frag_rate"]].to_string(index=False))

    result = {"law_fit_full_boot": law, "plateau_test": plat,
              "tolerance_note": f"step tol=±{TOL_STEP}, time tol=±{TOL_DAY} day",
              "far_unit": "median flags per satellite per 30 days (control windows)"}
    with open(out / "fs7_law_fit_v3.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 圖：容差對照 + FAR–recall 操作點（原圖為英文版；預設輸出維持英文）──────
    import matplotlib
    matplotlib.use("Agg")
    s1 = {d: tr[tr["decim"] == d].groupby("da_km")[["hit_step", "hit_time"]].mean() for d in DECIM}
    prev = fp.lang()
    fp.set_lang("en")
    try:
        draw_metrics(s1, agg).savefig("docs/fig_fs7_injection_metrics.png", dpi=150)
    finally:
        fp.set_lang(prev)
    print("\n輸出：fs7_injection_metrics.csv, fs7_law_fit_v3.json, fig_fs7_injection_metrics.png")


def draw_metrics(s1: dict, agg: pd.DataFrame):
    """(a) 容差定義對照、(b) 各條件 FAR–recall 操作點；s1[decim] 為 index=da_km、欄 hit_step／hit_time 之召回。"""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for d, c in zip(DECIM, ["#1565C0", "#FF8F00", "#C62828"]):
        s1d = s1[d]
        ax[0].plot(s1d.index * 1000, s1d["hit_step"], "o-", color=c,
                   label=t(f"×{d} ±2 步", f"x{d} ±2 steps"))
        ax[0].plot(s1d.index * 1000, s1d["hit_time"], "s--", color=c, alpha=0.55,
                   label=t(f"×{d} ±1.0 天", f"x{d} ±1.0 day"))
    ax[0].set_xscale("log"); ax[0].set_xlabel(t("注入 |Δa| (m)", "Injected |Δa| (m)"))
    ax[0].set_ylabel(t("召回率", "Recall")); ax[0].legend(fontsize=7); ax[0].grid(alpha=0.25)
    ax[0].set_title(t("(a) 命中容差定義對照", "(a) Tolerance definition comparison"))
    for d, c in zip(DECIM, ["#1565C0", "#FF8F00", "#C62828"]):
        s2 = agg[agg["decim"] == d]
        ax[1].scatter(s2["far_per30d_med"], s2["recall_step"], s=22, color=c, label=t(f"×{d}", f"x{d}"))
    ax[1].set_xlabel(t("誤報率（對照窗；每星每 30 天旗標數中位）", "FAR (median flags / sat / 30 d, control)"))
    ax[1].set_ylabel(t("召回率", "Recall")); ax[1].legend(fontsize=8); ax[1].grid(alpha=0.25)
    ax[1].set_title(t("(b) 各條件之操作點", "(b) Operating points by condition"))
    fig.suptitle(t("福衛七號注入實驗 v3：指標套組", "FS7 injection v3: metrics suite"))
    fig.tight_layout()
    return fig


def pub():
    """只重繪（不連 DB）：由 fs7_injection_metrics.csv 重建。
    panel (a) 之每 da_km × decim 召回＝各阻力域 recall 以試驗數 n 加權平均，
    等同原逐試驗平均（差異僅來自 CSV 中 recall 取 3 位小數之捨入）。"""
    agg = pd.read_csv(Path(__file__).resolve().parent / "data/benchmark/fs7_injection_metrics.csv")
    s1 = {}
    for d in DECIM:
        g = agg[agg["decim"] == d]
        w = g.groupby("da_km")["n"].sum()
        s1[d] = pd.DataFrame({
            "hit_step": (g["recall_step"] * g["n"]).groupby(g["da_km"]).sum() / w,
            "hit_time": (g["recall_time"] * g["n"]).groupby(g["da_km"]).sum() / w})
    fp.export_variants(lambda: draw_metrics(s1, agg), "fig_fs7_injection_metrics")


if __name__ == "__main__":
    if fp.wants_pub():
        pub()
    else:
        main()
