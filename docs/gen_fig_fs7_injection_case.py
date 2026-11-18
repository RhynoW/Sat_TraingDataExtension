#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_fs7_injection_case.py — 論文二 Fig. 2：單一注入案例（真實安靜窗上之 MAD/CUSUM 反應）。

內容：一個真實 FS7 TLE 安靜窗（1× 原始更新間隔、中阻力三分位）上注入 Δa = 100 m 階躍，
  (a) 原始與注入後之 TLE 半長軸序列；(b) 去中位數之單步差分與 MAD 門檻；
  (c) CUSUM 統計量（雙側）與決策門檻；各面板標示注入時刻與命中容差 ±2 樣本。
窗、偵測器與常數全部沿用 fs7_injection_sweep.py：WIN = 40 筆、quiet_windows()（單步 > 0.3 km
或間隔 > 5 d 之窗排除）、window_stats()（σ_TLE = MAD×1.4826/√2 之去趨勢單步差分）、
_detect_idx()（statistical_detectors.run_all 之 MAD3σ ∪ CUSUM）、TOL = 2；注入方式同 one_trial()
（x[inj:] += Δa）。唯一差異：注入位置固定取窗中點 inj = WIN // 2（掃描時為 [n/3, 2n/3) 隨機），
以便重現。選窗準則：fs7_injection_trials.csv 中 decim = 1、中阻力三分位、Δa = 0.10 km 之窗，
(σ, |ȧ|, Δt) 最接近該條件中位數（2.6 m、46.9 m/d、0.40 d）者 → NORAD 44350、win_start = 120。

輸入：space_db.duckdb（read_only，raw_tle_archive）——僅預設模式讀取
      data/benchmark/fs7_injection_trials.csv（核對窗統計量與掃描時一致）
輸出：data/benchmark/fs7_injection_case.csv        逐 TLE 序列與偵測器輸出（--pub 之快取）
      data/benchmark/fs7_injection_case_meta.json  窗資訊、σ_TLE、門檻、命中結果
      docs/fig_fs7_injection_case.png（600 dpi）＋ .pdf
用法：python docs/gen_fig_fs7_injection_case.py          （讀 DB → 快取 CSV → docs/ 英文白底圖）
      python docs/gen_fig_fs7_injection_case.py --pub    （只讀快取 CSV，輸出 docs/figures_pub/ 四版本）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DOCS))
import fs7_fig_style as st  # noqa: E402
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402

NORAD, WIN_START, DA_KM, DECIM = 44350, 120, 0.10, 1
SP3_CODE = "L79"
CSV = st.BM / "fs7_injection_case.csv"
META = st.BM / "fs7_injection_case_meta.json"
CUSUM_K, CUSUM_H, MAD_Z = 0.5, 5.0, 3.0      # statistical_detectors 之預設值（run_all 所用）


def build_cache() -> None:
    from fs7_injection_sweep import (CLEAN_STEP_KM, GAP_MAX_DAY, TOL, WIN, _detect_idx,  # noqa: F401
                                     load_series, quiet_windows, window_stats)
    from statistical_detectors import _robust_center_scale, cusum, mad3sigma

    df = load_series(str(ROOT / "space_db.duckdb"))[NORAD]       # read_only 連線
    assert (WIN_START, WIN_START + WIN) in quiet_windows(df), "所選窗已非安靜窗"
    sl = slice(WIN_START, WIN_START + WIN, DECIM)
    ep = pd.to_datetime(df["epoch_utc"].values[sl])
    tday = df["epoch_utc"].values.astype("datetime64[s]").astype(float)[sl] / 86400.0
    a = df["sma_km"].values[sl].astype(float)
    sigma, adot, dtm = window_stats(tday, a)

    # 與掃描時之窗統計量核對（trials CSV 取 4–5 位小數）
    tr = pd.read_csv(st.BM / "fs7_injection_trials.csv")
    row = tr[(tr.norad == NORAD) & (tr.win_start == WIN_START) & (tr.decim == DECIM)
             & (np.isclose(tr.da_km, DA_KM))].iloc[0]
    assert abs(row.sigma_km - round(sigma, 4)) < 1e-9, (row.sigma_km, sigma)
    assert abs(row.adot_kmday - round(adot, 5)) < 1e-9, (row.adot_kmday, adot)
    assert abs(row.dt_day - round(dtm, 3)) < 1e-9, (row.dt_day, dtm)
    band = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    assert band[row.name] == "mid"

    inj = WIN // 2
    x = a.copy()
    x[inj:] += DA_KM
    flags = _detect_idx(x)
    hit = bool(len(flags) and np.abs(flags - inj).min() <= TOL)

    da = np.diff(x, prepend=x[0])                      # 與 run_all 相同
    med, scale = _robust_center_scale(da)
    md = mad3sigma(da, MAD_Z)
    cu = cusum(da, CUSUM_K, CUSUM_H)
    da_raw = np.diff(a, prepend=a[0])
    med_r, _ = _robust_center_scale(da_raw)
    flag_mad = np.zeros(len(x), bool); flag_mad[md["events"]] = True
    flag_cu = np.zeros(len(x), bool); flag_cu[cu["events"]] = True

    out = pd.DataFrame({
        "idx": np.arange(len(x)), "epoch_utc": ep.strftime("%Y-%m-%d %H:%M:%S"),
        "t_day": tday - tday[0], "sma_raw_km": a, "sma_inj_km": x,
        "d_raw_m": (da_raw - med_r) * 1000, "d_inj_m": (da - med) * 1000,
        "z": (da - med) / scale, "cusum_hi": cu["s_hi"], "cusum_lo": cu["s_lo"],
        "flag_mad": flag_mad, "flag_cusum": flag_cu})
    out.loc[0, ["d_raw_m", "d_inj_m", "z"]] = np.nan        # prepend 之第 0 點非差分
    out.to_csv(CSV, index=False, float_format="%.9g")
    meta = {"norad": NORAD, "sp3": SP3_CODE, "win_start_index": WIN_START, "win_len": WIN,
            "decim": DECIM, "drag_tercile": "mid",
            "window_start_utc": str(ep[0]), "window_end_utc": str(ep[-1]),
            "inj_index": inj, "inj_epoch_utc": str(ep[inj]), "da_m": DA_KM * 1000,
            "sigma_tle_m": sigma * 1000, "adot_m_per_day": adot * 1000, "dt_median_day": dtm,
            "mad_scale_of_differences_m": scale * 1000, "mad_threshold_m": MAD_Z * scale * 1000,
            "cusum_k": CUSUM_K, "cusum_h": CUSUM_H, "tolerance_samples": TOL,
            "flags": [int(f) for f in flags], "hit": hit,
            "trials_csv_check": "sigma/adot/dt 與 fs7_injection_trials.csv 一致"}
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"快取：{CSV.name}、{META.name}；flags={meta['flags']} inj={inj} hit={hit}")


def draw():
    import matplotlib.pyplot as plt
    d = pd.read_csv(CSV)
    m = json.loads(META.read_text(encoding="utf-8"))
    inj, tol = m["inj_index"], m["tolerance_samples"]
    td = d["t_day"].values
    t0 = d["sma_raw_km"].iloc[0]
    lo_t, hi_t = td[max(inj - tol, 0)], td[min(inj + tol, len(td) - 1)]

    fig, ax = plt.subplots(3, 1, figsize=(st.SINGLE, 9.6 * st.CM), sharex=True,
                           gridspec_kw={"height_ratios": [1.25, 1.0, 1.0], "hspace": 0.28})
    for a_ in ax:
        a_.axvspan(lo_t, hi_t, color="#f2c94c", alpha=0.28, lw=0, zorder=0)
        a_.axvline(td[inj], color=st.GRAY, lw=0.7, ls="--", zorder=1)
        a_.grid(alpha=0.3)

    # (a) 序列
    ax[0].plot(td, (d["sma_raw_km"] - t0) * 1000, "o-", ms=2.2, lw=0.7, color=st.GRAY,
               label=t("原始 TLE", "Raw TLE"))
    ax[0].plot(td, (d["sma_inj_km"] - t0) * 1000, "o-", ms=2.2, lw=0.8, color=st.BLUE,
               label=t(f"注入後（Δa = +{m['da_m']:.0f} m）", f"Injected (Δa = +{m['da_m']:.0f} m)"))
    ax[0].set_ylabel(t("a − a₀ (m)", "a − a₀ (m)"))
    ax[0].legend(loc="lower left", ncol=1)
    yl = ax[0].get_ylim(); ax[0].set_ylim(yl[0], yl[1] + 0.32 * (yl[1] - yl[0]))
    w0, w1 = m["window_start_utc"][:16], m["window_end_utc"][:16]
    info = (t(f"NORAD {m['norad']}（{m['sp3']}）", f"NORAD {m['norad']} ({m['sp3']})") + "\n"
            + f"{w0} – {w1} UTC\n"
            + t(f"Δa = {m['da_m']:.0f} m；σ_TLE = {m['sigma_tle_m']:.1f} m",
                f"Δa = {m['da_m']:.0f} m; σ_TLE = {m['sigma_tle_m']:.1f} m") + "\n"
            + t(f"|ȧ| = {abs(m['adot_m_per_day']):.1f} m/d；Δt = {m['dt_median_day']:.2f} d（1×，中阻力）",
                f"|ȧ| = {abs(m['adot_m_per_day']):.1f} m/d; Δt = {m['dt_median_day']:.2f} d (1×, mid drag)"))
    ax[0].text(0.985, 0.96, info, transform=ax[0].transAxes, ha="right", va="top", fontsize=5.9,
               linespacing=1.3, color=st.INK,
               bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#9ca3af", lw=0.5))
    st.panel_label(ax[0], "(a)", x=-0.19, y=1.04)

    # (b) 去中位數單步差分 + MAD 門檻
    thr = m["mad_threshold_m"]
    ax[1].plot(td, d["d_raw_m"], "o", ms=2.0, color=st.GRAY, mfc="none", mew=0.5,
               label=t("原始", "Raw"))
    ax[1].plot(td, d["d_inj_m"], "o-", ms=2.2, lw=0.7, color=st.BLUE, label=t("注入後", "Injected"))
    ax[1].axhline(thr, color=st.RED, lw=0.8, ls=":")
    ax[1].axhline(-thr, color=st.RED, lw=0.8, ls=":")
    ax[1].text(td[1], thr, t(f" MAD 門檻 ±{thr:.1f} m（3σ）", f" MAD threshold ±{thr:.1f} m (3σ)"),
               ha="left", va="bottom", fontsize=5.9, color=st.RED)
    fm = d["flag_mad"].values.astype(bool)
    ax[1].plot(td[fm], d["d_inj_m"].values[fm], "s", ms=4.2, mfc="none", mec=st.RED, mew=0.8,
               label=t("MAD 旗標", "MAD flag"))
    ax[1].set_ylabel(t("去趨勢單步差分 (m)", "Detrended step diff. (m)"))
    ax[1].legend(loc="lower left", ncol=3)
    ymax = np.nanmax(d["d_inj_m"]) * 1.12
    ax[1].set_ylim(-max(thr * 2.4, 25), ymax)
    st.panel_label(ax[1], "(b)", x=-0.19, y=1.04)

    # (c) CUSUM
    ax[2].plot(td, d["cusum_hi"], "-", color=st.BLUE, lw=0.9, label=t("S⁺（上升）", "S⁺ (upward)"))
    ax[2].plot(td, d["cusum_lo"], "-", color=st.ORANGE, lw=0.9, label=t("S⁻（下降）", "S⁻ (downward)"))
    ax[2].axhline(m["cusum_h"], color=st.RED, lw=0.8, ls=":")
    ax[2].text(td[-1], m["cusum_h"], t(f"決策門檻 h = {m['cusum_h']:.0f}", f"decision threshold h = {m['cusum_h']:.0f}"),
               ha="right", va="bottom", fontsize=5.9, color=st.RED)
    fc = d["flag_cusum"].values.astype(bool)
    if fc.any():
        yv = np.maximum(d["cusum_hi"].values, d["cusum_lo"].values)
        # 警報後統計量已重置為 0；旗標畫在門檻高度
        ax[2].plot(td[fc], np.full(fc.sum(), m["cusum_h"]), "v", ms=4.0, color=st.RED,
                   label=t("CUSUM 旗標", "CUSUM flag"))
        del yv
    ax[2].set_ylabel(t("CUSUM（σ）", "CUSUM (σ)"))
    ax[2].set_xlabel(t("距窗起點時間（天）", "Time since window start (d)"))
    ax[2].legend(loc="upper left", ncol=1, bbox_to_anchor=(0.0, 1.02))
    ax[2].set_ylim(0, m["cusum_h"] * 1.9)
    ax[2].set_xlim(td[0] - 0.2, td[-1] + 0.2)
    st.panel_label(ax[2], "(c)", x=-0.19, y=1.04)

    # 容差與注入時刻說明（只標一次）
    ax[2].text(hi_t + 0.1, 0.97, t("命中容差 ±2 樣本", "hit tolerance ±2 samples"),
               transform=ax[2].get_xaxis_transform(), ha="left", va="top", fontsize=5.9, color="#8a6d00")
    ax[0].text(td[inj], 1.01, t("注入時刻", "injection epoch"), transform=ax[0].get_xaxis_transform(),
               ha="center", va="bottom", fontsize=5.9, color=st.GRAY)
    fig.align_ylabels(ax)
    return fig


if __name__ == "__main__":
    if not fp.wants_pub():
        build_cache()
    st.run({"fig_fs7_injection_case": draw})
