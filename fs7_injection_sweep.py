#!/usr/bin/env python3
"""
fs7_injection_sweep.py — 福衛七號真實 TLE 序列上的合成機動注入掃描
===================================================================
期刊版核心實驗：在 6 顆 FORMOSAT-7 的真實 TLE 半長軸序列（真實更新節奏、
真實雜訊、真實阻力）上注入已知階躍 Δa，量測偵測率隨三維條件的變化：

    Δa（機動量級） × 降頻 d（模擬更新間隔 1×/2×/4×） × 阻力域（|ȧ| 三分位）

並驗證「時間感知有效訊噪比」的塌縮假說：

    SNR_eff = Δa / sqrt(σ² + (ȧ·Δt)²)

若偵測率對 SNR_eff 的曲線在所有條件下重合（對 raw Δa 則發散），
即證明偵測極限由 (σ, Δt, ȧ) 三參數共同決定——期刊版的靈敏度定律。

偵測器沿用契約 M3 之 statistical_detectors.run_all（MAD3σ ∪ CUSUM），
與 synthetic_injection_test.py 方法學連續。

輸出：
  data/benchmark/fs7_injection_sweep.csv    彙總（條件 × 偵測率）
  data/benchmark/fs7_injection_trials.csv   逐試驗（供塌縮圖）
  docs/fig_fs7_injection_recall.png         召回 vs Δa（按降頻/阻力域分層）
  docs/fig_fs7_injection_collapse.png       塌縮驗證（SNR_amp vs SNR_eff）

用法：python fs7_injection_sweep.py [--db space_db.duckdb] [--seed 42]
      python fs7_injection_sweep.py --pub   （只重繪：讀 data/benchmark/fs7_injection_sweep.csv／trials.csv，不連 DB；
                                             輸出 docs/figures_pub/ 兩圖之中英×白底／黑底四版本）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

from statistical_detectors import run_all

sys.path.insert(0, str(Path(__file__).resolve().parent / "docs"))
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402

FS7_NORADS = [44343, 44349, 44350, 44351, 44353, 44358]
DA_GRID = [0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00]  # km
DECIM = [1, 2, 4]          # 降頻倍率（模擬更新間隔拉長）
WIN = 40                   # 每窗 TLE 筆數
STRIDE = 20                # 滑動步幅
MIN_PTS = 10               # 降頻後最少點數
TOL = 2                    # 命中容差（樣本步）
GAP_MAX_DAY = 5.0          # 窗內最大允許間隔（天）
CLEAN_STEP_KM = 0.30       # 基底預清洗：疑似真實事件的單步門檻


def _detect_idx(sma: np.ndarray) -> np.ndarray:
    """MAD3σ ∪ CUSUM 旗標索引（沿用 M3 偵測器組合）。"""
    r = run_all(sma)
    flag = np.zeros(len(sma), bool)
    for k in ("mad3sig", "cusum"):
        ev = r[k]["events"]
        if len(ev):
            flag[np.clip(np.asarray(ev), 0, len(sma) - 1)] = True
    return np.where(flag)[0]


def load_series(db: str) -> dict[int, pd.DataFrame]:
    con = duckdb.connect(db, read_only=True)
    out = {}
    for nid in FS7_NORADS:
        df = con.execute(
            "SELECT epoch_utc, sma_km FROM raw_tle_archive "
            "WHERE norad_id=? AND sma_km IS NOT NULL "
            "ORDER BY epoch_utc", [nid]).df()
        df = df.drop_duplicates("epoch_utc").reset_index(drop=True)
        out[nid] = df
    con.close()
    return out


def quiet_windows(df: pd.DataFrame) -> list[tuple[int, int]]:
    """切出無疑似真實事件、無大間隔的滑動窗（回傳 [start,end) 索引）。"""
    t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
    a = df["sma_km"].values
    da = np.abs(np.diff(a, prepend=a[0]))
    dt = np.diff(t, prepend=t[0])
    bad = (da > CLEAN_STEP_KM) | (dt > GAP_MAX_DAY)
    wins = []
    for s in range(0, len(a) - WIN, STRIDE):
        e = s + WIN
        if not bad[s + 1:e].any():
            wins.append((s, e))
    return wins


def window_stats(t: np.ndarray, a: np.ndarray) -> tuple[float, float, float]:
    """回傳 (σ_km, adot_km_per_day, dt_med_day)。σ 取去趨勢後單步差分之 MAD 穩健標準差。"""
    slope = np.polyfit(t, a, 1)[0]                      # km/day（含阻力趨勢）
    resid = a - slope * (t - t[0])
    d = np.diff(resid)
    sigma = 1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0)
    return float(sigma), float(slope), float(np.median(np.diff(t)))


def one_trial(t, a, da_km, rng) -> tuple[bool, float]:
    """注入 + 偵測。回傳 (命中, 對照窗是否誤報)。"""
    n = len(a)
    inj = int(rng.integers(n // 3, 2 * n // 3))
    x = a.copy()
    x[inj:] += da_km
    hits = _detect_idx(x)
    hit = bool(len(hits) and np.abs(hits - inj).min() <= TOL)
    ctrl_fp = bool(len(_detect_idx(a)))                 # 未注入之誤報（整窗任一旗標）
    return hit, ctrl_fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    series = load_series(args.db)
    trials = []
    for nid, df in series.items():
        wins = quiet_windows(df)
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        print(f"NORAD {nid}: {len(df)} 筆 TLE，安靜窗 {len(wins)} 個")
        for (s, e) in wins:
            for d in DECIM:
                t = t_all[s:e:d]
                a = a_all[s:e:d]
                if len(a) < MIN_PTS:
                    continue
                sigma, adot, dtm = window_stats(t, a)
                if sigma <= 0:
                    continue
                for da_km in DA_GRID:
                    hit, ctrl_fp = one_trial(t, a, da_km, rng)
                    trials.append({
                        "norad": nid, "win_start": s, "decim": d,
                        "da_km": da_km, "hit": int(hit), "ctrl_fp": int(ctrl_fp),
                        "sigma_km": round(sigma, 4), "adot_kmday": round(adot, 5),
                        "dt_day": round(dtm, 3),
                        "snr_amp": round(da_km / sigma, 2),
                        "snr_eff": round(da_km / np.hypot(sigma, adot * dtm), 2),
                    })
    tr = pd.DataFrame(trials)
    print(f"\n總試驗數：{len(tr)}")

    # 阻力域三分位（以 |ȧ| 分層；跨所有窗）
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])

    agg = (tr.groupby(["da_km", "decim", "drag_band"], observed=True)
             .agg(n=("hit", "size"), detect_rate=("hit", "mean"),
                  fp_rate=("ctrl_fp", "mean"),
                  sigma_med=("sigma_km", "median"), dt_med=("dt_day", "median"),
                  adot_med=("adot_kmday", lambda x: float(np.median(np.abs(x)))))
             .reset_index())
    agg["detect_rate"] = agg["detect_rate"].round(3)
    agg["fp_rate"] = agg["fp_rate"].round(3)

    out = Path("data/benchmark")
    out.mkdir(parents=True, exist_ok=True)
    agg.to_csv(out / "fs7_injection_sweep.csv", index=False, encoding="utf-8-sig")
    tr.to_csv(out / "fs7_injection_trials.csv", index=False, encoding="utf-8-sig")

    # ── 偵測下限表 ─────────────────────────────────────────────────────────
    print("\n【50% / 90% 召回所需 Δa (km)，按 降頻 × 阻力域】")
    for d in DECIM:
        for band in ["low", "mid", "high"]:
            sub = agg[(agg["decim"] == d) & (agg["drag_band"] == band)].sort_values("da_km")
            def _floor(p):
                ok = sub[sub["detect_rate"] >= p]
                return float(ok["da_km"].min()) if len(ok) else float("nan")
            print(f"  d={d}  drag={band:4s}  Δt~{sub['dt_med'].median():.2f}d  "
                  f"σ~{sub['sigma_med'].median()*1000:.0f}m  "
                  f"50%:{_floor(0.5)}  90%:{_floor(0.9)}")

    # ── 塌縮檢定：raw SNR vs SNR_eff 的分箱曲線離散度 ───────────────────────
    def _binned(col):
        b = tr.copy()
        b["bin"] = pd.cut(np.log10(b[col].clip(0.05, 200)), 20)
        g = b.groupby(["bin", "decim"], observed=True)["hit"].mean().unstack()
        return g.std(axis=1, skipna=True).mean()   # 各條件曲線間的平均離散
    disp_amp, disp_eff = _binned("snr_amp"), _binned("snr_eff")
    print(f"\n【塌縮檢定】分箱偵測率曲線之條件間離散度："
          f"SNR_amp={disp_amp:.3f} → SNR_eff={disp_eff:.3f} "
          f"（{'塌縮成立 ✅' if disp_eff < disp_amp else '塌縮不成立 ❌'}）")

    # ── 圖（原圖為英文版；預設輸出維持英文）─────────────────────────────────
    import matplotlib
    matplotlib.use("Agg")
    prev = fp.lang()
    fp.set_lang("en")
    try:
        draw_recall(agg).savefig("docs/fig_fs7_injection_recall.png", dpi=150)
        draw_collapse(tr).savefig("docs/fig_fs7_injection_collapse.png", dpi=150)
    finally:
        fp.set_lang(prev)

    print("\n輸出：data/benchmark/fs7_injection_sweep.csv, fs7_injection_trials.csv")
    print("　　　docs/fig_fs7_injection_recall.png, fig_fs7_injection_collapse.png")


_BAND_ZH = {"low": "低", "mid": "中", "high": "高"}


def draw_recall(agg: pd.DataFrame):
    """召回 vs Δa（按降頻/阻力域分層）；回傳 Figure。"""
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharey=True)
    for ax, band in zip(axes, ["low", "mid", "high"]):
        for d, c in zip(DECIM, ["#1565C0", "#FF8F00", "#C62828"]):
            sub = agg[(agg["decim"] == d) & (agg["drag_band"] == band)].sort_values("da_km")
            dtm = sub["dt_med"].median()
            ax.plot(sub["da_km"] * 1000, sub["detect_rate"], "o-", color=c,
                    label=t(f"更新間隔 ×{d}（約 {dtm:.1f} 天）", f"cadence x{d} (~{dtm:.1f} d)"))
        ax.set_xscale("log")
        ax.set_xlabel(t("注入階躍 |Δa| (m)", "Injected step |Δa| (m)"))
        ax.set_title(t(f"阻力{_BAND_ZH[band]}（|da/dt| 三分位）", f"drag {band} (|da/dt| tercile)"))
        ax.axhline(0.9, ls=":", c="gray", lw=0.8)
        ax.axhline(0.5, ls=":", c="gray", lw=0.8)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel(t("偵測率", "Detection rate"))
    axes[0].legend(fontsize=8)
    fig.suptitle(t("福衛七號真實 TLE 合成注入：召回率 vs Δa（依更新間隔與阻力域分層）",
                   "FS7 real-TLE synthetic injection: recall vs Δa by cadence & drag regime"))
    fig.tight_layout()
    return fig


def draw_collapse(tr: pd.DataFrame):
    """塌縮檢定（SNR_amp vs SNR_eff）；回傳 Figure。"""
    import matplotlib.pyplot as plt
    fig2, ax2 = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True)
    for ax, col, ttl in [(ax2[0], "snr_amp", t("僅幅度 SNR = Δa/σ", "amplitude-only SNR = Δa/σ")),
                         (ax2[1], "snr_eff", t("有效 SNR = Δa/√(σ²+(ȧΔt)²)", "effective SNR = Δa/√(σ²+(ȧΔt)²)"))]:
        for d, c in zip(DECIM, ["#1565C0", "#FF8F00", "#C62828"]):
            b = tr[tr["decim"] == d].copy()
            b["bin"] = pd.cut(np.log10(b[col].clip(0.05, 200)), 18)
            g = b.groupby("bin", observed=True).agg(x=(col, "median"), y=("hit", "mean"))
            g = g.dropna()
            ax.plot(g["x"], g["y"], "o-", ms=3.5, color=c, label=t(f"更新間隔 ×{d}", f"cadence x{d}"))
        ax.set_xscale("log")
        if not fp.is_en():   # 微軟正黑體缺 U+2212，10^{-1} 之負號會成缺字方塊 → 中文版改用一般數字刻度
            from matplotlib.ticker import FuncFormatter
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.set_xlabel(ttl)
        ax.axvline(4, ls="--", c="gray", lw=0.8)
        ax.grid(alpha=0.25)
    ax2[0].set_ylabel(t("偵測率", "Detection rate"))
    ax2[0].legend(fontsize=8)
    fig2.suptitle(t("塌縮檢定：以 Δa/σ 為橫軸時曲線分離，以 SNR_eff 為橫軸時重合",
                    "Collapse test: curves separate under Δa/σ but coincide under SNR_eff"))
    fig2.tight_layout()
    return fig2


def pub():
    bm = Path(__file__).resolve().parent / "data/benchmark"
    agg = pd.read_csv(bm / "fs7_injection_sweep.csv")
    tr = pd.read_csv(bm / "fs7_injection_trials.csv")
    fp.export_variants(lambda: draw_recall(agg), "fig_fs7_injection_recall")
    fp.export_variants(lambda: draw_collapse(tr), "fig_fs7_injection_collapse")


if __name__ == "__main__":
    if fp.wants_pub():
        pub()
    else:
        main()
