#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_fs7_model_supplement.py — 論文二補充圖 Fig. S1（兩張）與 Fig. S2。

  fig_fs7_profile_likelihood  Fig. S1(a)：c 之 profile likelihood（SNR50、β 逐點 profile），
                              標 ĉ、95% CI（ℓ(ĉ) − ℓp(c) ≤ 1.92）與 c = 1 之 ΔlogL
  fig_fs7_joint_likelihood    Fig. S1(b)：(c, SNR50) 聯合似然曲面（β 逐點 profile），
                              ΔlogL = 1.92（投影即 c 之 profile CI）與 ΔlogL = 3.00（χ²₂ 聯合 95% 區域）等值線、
                              profile 脊線（各 c 之最大似然 SNR50）、B = 200 叢集自助之 (ĉ_b, SNR50_b) 與其相關係數
  fig_fs7_reliability         Fig. S2：時間切分測試期（≥ 2025-07-01，6,996 筆）reliability diagram，
                              raw 與 Platt 再校準（校準期 OOF 擬合、測試期原樣套用）

輸入（皆為 fs7_review3_analysis.py／fs7_review4_analysis.py 之輸出；本程式不連 DB、不重算擬合）：
  data/benchmark/fs7_review3_profile_grid.csv、fs7_review3_joint_boot.csv
  data/benchmark/fs7_review4_joint_grid.csv、fs7_review4_heldout_predictions.csv
  data/benchmark/fs7_review3_analysis.json、fs7_review4_analysis.json、fs7_final_supplement.json、
  fs7_law_fit_v4.json（核對摘要值）
輸出：docs/fig_fs7_profile_likelihood.png／.pdf、docs/fig_fs7_joint_likelihood.png／.pdf、
      docs/fig_fs7_reliability.png／.pdf（600 dpi＋向量）
用法：python fs7_review3_analysis.py && python fs7_review4_analysis.py   （產生上列 CSV；需 DB，read_only）
      python docs/gen_fig_fs7_model_supplement.py          （docs/ 英文白底）
      python docs/gen_fig_fs7_model_supplement.py --pub    （docs/figures_pub/ 四版本）
Fig. S2 之 raw／Platt 兩組點於橫軸各錯開 ∓0.012 以免重疊（Platt 參數 a ≈ 0.0003、b ≈ 0.998，兩組幾乎重合）；
  分箱為 10 個等寬機率箱，誤差棒為 Wilson 95% CI，下方為各箱試驗數（對數軸）。
校準截距：以 y ~ sigmoid(a + b·logit p) 擬合，a 即截距（與 fs7_final_supplement.py 相同定義，−0.63）；
  fs7_review4_analysis.json 之 calib_intercept（−0.27）換算少乘 ln 10，圖中不採用。
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
from fs7_injection_sweep_v2 import _logit_fit  # noqa: E402
from fs7_tle_recall_unified import wilson  # noqa: E402

DLL1, DLL2 = 1.9208, 2.9957        # χ²₁,0.95 / 2、χ²₂,0.95 / 2


def _j(name):
    return json.loads((st.BM / name).read_text(encoding="utf-8"))


def load():
    prof = pd.read_csv(st.BM / "fs7_review3_profile_grid.csv")
    boot = pd.read_csv(st.BM / "fs7_review3_joint_boot.csv")
    grid = pd.read_csv(st.BM / "fs7_review4_joint_grid.csv")
    pred = pd.read_csv(st.BM / "fs7_review4_heldout_predictions.csv")
    return prof, boot, grid, pred


def calib_line(p, y):
    """y ~ sigmoid(a + b·logit p) → (b, a)。"""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    lg = np.log(p / (1 - p))
    s50, beta, _ = _logit_fit(lg / np.log(10), y)
    b = beta / np.log(10)
    return b, -b * np.log(s50)


def metrics(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    order = np.argsort(p)
    r = np.empty(len(p)); r[order] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    auc = float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return ll, br, auc


def summary():
    """由網格／逐試驗預測重算摘要值，回傳 dict，並與既有 json 及論文數字逐項比對。"""
    prof, boot, grid, pred = load()
    r3, r4, fs, v4 = _j("fs7_review3_analysis.json"), _j("fs7_review4_analysis.json"), \
        _j("fs7_final_supplement.json"), _j("fs7_law_fit_v4.json")
    i = int(prof["rel_ll"].idxmax())
    ok = prof[prof["rel_ll"] >= -1.92]
    s = {"c_hat": round(prof["c"][i], 2), "ci": [round(ok["c"].min(), 2), round(ok["c"].max(), 2)],
         "snr50_at_c_hat": prof["snr50"][i],
         "dll_c1": float(np.interp(0.0, np.log(prof["c"]), prof["rel_ll"])),
         "corr": round(float(np.corrcoef(np.log(boot["c_boot"]), np.log(boot["snr50_boot"]))[0, 1]), 2)}
    g = grid[grid["grid"] == "coarse"]
    k = int(g["ll_total"].idxmax())
    s["joint_max_coarse"] = {"c": round(g["c"][k], 2), "snr50": round(g["snr50"][k], 2)}
    s["joint_max_coarse_exact"] = (float(g["c"][k]), float(g["snr50"][k]), float(g["ll_total"][k]))
    gf = grid[grid["grid"] == "fine"]
    kf = int(gf["ll_total"].idxmax())
    s["joint_max_fine"] = (float(gf["c"][kf]), float(gf["snr50"][kf]), float(gf["ll_total"][kf]))
    s["c_cal"] = float(r4["held_out_metrics"]["c_cal_fixed_for_test"])
    s["prof_max"] = (float(prof["c"][i]), float(prof["snr50"][i]), float(prof["ll_total"][i]))
    s["joint_fine_max_minus_profile_max"] = float(gf["ll_total"].max() - prof["ll_total"].max())
    in1 = gf[gf["ll_total"] - prof["ll_total"].max() >= -DLL1]
    s["joint_dll192_c_range"] = [round(in1["c"].min(), 3), round(in1["c"].max(), 3)]
    y = pred["hit"].values.astype(float)
    for tag, col in (("raw", "p_raw"), ("recal", "p_recal")):
        ll, br, auc = metrics(pred[col].values, y)
        b, a = calib_line(pred[col].values, y)
        s[tag] = {"logloss": round(ll, 4), "brier": round(br, 4), "auc": round(auc, 4),
                  "slope": round(b, 2), "intercept": round(a, 2)}
    s["n_test"] = len(pred)
    s["fs"] = fs["calibration_slope"]
    # fs7_final_supplement.py 以四捨五入後之校準係數（c=0.28、SNR50=3.87、β=5.04）重建 p_raw
    tr = pd.read_csv(st.BM / "fs7_injection_trials.csv")
    mm = pred.merge(tr, on=["norad", "win_start", "decim", "da_km", "hit"], how="left", validate="1:1")
    snr = (mm["da_km"] / np.hypot(mm["sigma_km"], 0.28 * mm["adot_kmday"].abs() * mm["dt_day"])).clip(1e-2, 1e4)
    p_r = 1 / (1 + np.exp(-5.04 * (np.log10(snr) - np.log10(3.87))))
    b_r, a_r = calib_line(p_r.values, mm["hit"].values.astype(float))
    s["raw_rounded"] = {"slope": round(b_r, 2), "intercept": round(a_r, 2)}

    checks = [
        ("ĉ（全資料 profile）", s["c_hat"], r3["identifiability"]["c_hat"], 0.32),
        ("c 之 95% profile CI", s["ci"], r3["identifiability"]["profile_ci95"], [0.28, 0.40]),
        ("c 之 95% CI（v4 json）", s["ci"], v4["c_drag"]["profile_ci95"], [0.28, 0.40]),
        ("corr(log c, log SNR50)，B=200", s["corr"], r3["identifiability"]["joint_boot_corr_logc_logsnr50"], -0.98),
        ("SNR50 於 ĉ（profile）", round(s["snr50_at_c_hat"], 2), v4["law_fit_v4"]["snr50"].__round__(2), 3.77),
        ("聯合網格峰值（26×26）", s["joint_max_coarse"], r4["joint_likelihood"]["ll_max_at"], None),
        ("held-out raw log loss", s["raw"]["logloss"], r4["held_out_metrics"]["raw"]["logloss"], 0.1237),
        ("held-out raw Brier", s["raw"]["brier"], r4["held_out_metrics"]["raw"]["brier"], 0.0393),
        ("held-out raw AUC", s["raw"]["auc"], r4["held_out_metrics"]["raw"]["auc"], 0.9773),
        ("held-out Platt log loss", s["recal"]["logloss"], r4["held_out_metrics"]["recalibrated"]["logloss"], 0.1238),
        ("held-out Platt Brier", s["recal"]["brier"], r4["held_out_metrics"]["recalibrated"]["brier"], 0.0393),
        ("raw 校準斜率", s["raw"]["slope"], fs["calibration_slope"]["slope"], 1.22),
        ("raw 校準斜率（四捨五入係數）", s["raw_rounded"]["slope"], fs["calibration_slope"]["slope"], 1.22),
        ("raw 校準截距（四捨五入係數）", s["raw_rounded"]["intercept"], fs["calibration_slope"]["intercept"], -0.63),
        ("測試期試驗數", s["n_test"], v4["time_split"]["n_test"], 6996),
    ]
    bad = 0
    print("摘要值核對（重算 / 既有 json / 論文）：")
    for name, got, js, paper in checks:
        flag = (got == js) and (paper is None or got == paper)
        bad += not flag
        print(f"  {'一致' if flag else '差異'}  {name}: {got} / {js} / {paper if paper is not None else '—'}")
    print(f"  參考  c = 1 之 ΔlogL = {s['dll_c1']:.2f}（ĉ 處為 0）；ΔlogL ≤ 1.92 區域之 c 投影 "
          f"{s['joint_dll192_c_range']}；細網格峰值 − profile 峰值 = {s['joint_fine_max_minus_profile_max']:.3f}")
    print(f"  參考  以未四捨五入之校準係數（review4 逐試驗 p_raw）重算：斜率 {s['raw']['slope']}、截距 {s['raw']['intercept']}")
    print(f"  參考  Platt 後校準斜率 {s['recal']['slope']}、截距 {s['recal']['intercept']}；"
          f"json 之 calib_intercept {r4['held_out_metrics']['raw']['calib_intercept']}（少乘 ln 10）")
    for tag, v in (("profile 最大（47 點 c）", s["prof_max"]), ("聯合 26×26 網格峰值", s["joint_max_coarse_exact"]),
                   ("聯合 61×61 細網格峰值（圖中標示）", s["joint_max_fine"])):
        print(f"  參考  {tag}: c = {v[0]:.4f}, SNR50 = {v[1]:.4f}, ℓ = {v[2]:.3f}")
    if bad:
        print(f"[注意] {bad} 項與既有 json 或論文不一致（見上）")
    return s


S = None


def draw_profile():
    import matplotlib.pyplot as plt
    prof = load()[0]
    fig, ax = plt.subplots(figsize=(st.SINGLE, 5.6 * st.CM))
    lo, hi = S["ci"]
    ax.axvspan(lo, hi, color=st.BLUE, alpha=0.12, lw=0)
    ax.plot(prof["c"], prof["rel_ll"], "-", color=st.BLUE, lw=1.1)
    ax.plot(prof["c"], prof["rel_ll"], "o", ms=1.8, color=st.BLUE)
    ax.axhline(-DLL1, color=st.GRAY, lw=0.7, ls="--")
    ax.text(9.5, -DLL1 + 0.25, t("ΔlogL = 1.92（χ²₁ 95%）", "ΔlogL = 1.92 (χ²₁, 95%)"),
            ha="right", va="bottom", fontsize=6.0, color=st.GRAY)
    ax.axvline(S["c_hat"], color=st.RED, lw=0.8, ls=":")
    ax.text(S["c_hat"] * 1.08, -25.5, t(f"ĉ = {S['c_hat']:.2f}（全資料 MLE）\n95% CI [{lo:.2f}, {hi:.2f}]",
                                       f"ĉ = {S['c_hat']:.2f} (full-data MLE)\n95% CI [{lo:.2f}, {hi:.2f}]"),
            ha="left", va="center", fontsize=6.2, color=st.RED)
    ax.axvline(S["c_cal"], color=st.GREEN, lw=0.8, ls="-.")
    ax.text(0.053, -8.5, t(f"c = {S['c_cal']:.2f}\n（校準期，\nheld-out 固定值）",
                            f"c = {S['c_cal']:.2f}\n(calibration\nsplit, held-out)"),
            ha="left", va="center", fontsize=6.0, color=st.GREEN)
    ax.axvline(1.0, color=st.ORANGE, lw=0.8, ls=":")
    ax.text(1.08, -11.5, t(f"c = 1（固定值敏感度變體）\nΔlogL = {S['dll_c1']:.1f}",
                           f"c = 1 (fixed-value variant)\nΔlogL = {S['dll_c1']:.1f}").replace("= -", "= \u2212"),
            ha="left", va="center", fontsize=6.2, color=st.ORANGE)
    ax.set_xscale("log")
    if not fp.is_en():
        from matplotlib.ticker import FuncFormatter
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlim(0.05, 10)
    ax.set_ylim(-30, 1.5)
    ax.set_xlabel(t("阻力模糊係數 c", "Drag-ambiguity coefficient c"))
    ax.set_ylabel(t("ℓp(c) − ℓ(ĉ)", "ℓp(c) − ℓ(ĉ)"))
    ax.grid(alpha=0.3)
    return fig


def draw_joint():
    import matplotlib.pyplot as plt
    prof, boot, grid, _ = load()
    gf = grid[grid["grid"] == "fine"]
    cs = np.sort(gf["c"].unique()); ss = np.sort(gf["snr50"].unique())
    # 以 profile 最大值（47 點 c 網格上逐點完整 MLE）為基準：細網格沿窄脊線取樣，其格點最大值略低（約 0.4）
    Z = gf.pivot(index="snr50", columns="c", values="ll_total").loc[ss, cs].values - prof["ll_total"].max()
    fig, ax = plt.subplots(figsize=(st.SINGLE, 7.6 * st.CM))
    levels = [-40, -20, -10, -5, -DLL2, -DLL1, 0]
    cf = ax.contourf(cs, ss, np.maximum(Z, -40), levels=levels, cmap="Blues", extend="neither")
    ax.contour(cs, ss, Z, levels=[-DLL2], colors=[st.RED], linewidths=1.2)
    ax.contour(cs, ss, Z, levels=[-DLL1], colors=[st.INK], linewidths=0.8, linestyles="--")
    pr = prof[(prof["c"] >= cs.min()) & (prof["c"] <= cs.max())]
    ax.plot(pr["c"], pr["snr50"], "-", color="#9ca3af", lw=0.7)
    ax.plot(boot["c_boot"], boot["snr50_boot"], "o", ms=1.6, color=st.ORANGE, alpha=0.8, mew=0)
    cg, sg, _ = S["joint_max_coarse_exact"]
    ax.plot([cg], [sg], "D", ms=3.2, mfc="white", mec=st.INK, mew=0.6, zorder=6)
    ax.plot([S["joint_max_fine"][0]], [S["joint_max_fine"][1]], "*", ms=6.5, color=st.RED, mec="white", mew=0.4, zorder=6)
    ax.set_xscale("log"); ax.set_yscale("log")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator
    ax.xaxis.set_major_locator(FixedLocator([0.2, 0.3, 0.4, 0.5, 0.7]))
    ax.yaxis.set_major_locator(FixedLocator([2.5, 3, 4, 5, 6]))
    for a_ in (ax.xaxis, ax.yaxis):
        a_.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        a_.set_minor_locator(NullLocator()); a_.set_minor_formatter(NullFormatter())
    ax.set_xlim(0.18, 0.75); ax.set_ylim(2.2, 6.5)
    ax.set_xlabel(t("阻力模糊係數 c", "Drag-ambiguity coefficient c"))
    ax.set_ylabel(t("SNR₅₀", "SNR₅₀"))
    cb = fig.colorbar(cf, ax=ax, pad=0.02, fraction=0.05)
    cb.set_label(t("相對對數似然（β 已 profile）", "Relative log-likelihood (β profiled)"))
    cb.ax.tick_params(labelsize=6)
    cb.set_ticks(levels); cb.set_ticklabels([(f"{v:.2f}" if v != int(v) else f"{v:g}").replace("-", "−") for v in levels])
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], color=st.RED, lw=1.0),
          Line2D([], [], color=st.INK, lw=0.8, ls="--"),
          Line2D([], [], color="#9ca3af", lw=0.7),
          Line2D([], [], color=st.ORANGE, marker="o", ms=2.5, lw=0),
          Line2D([], [], color=st.RED, marker="*", ms=6, lw=0, mec="white", mew=0.4),
          Line2D([], [], color=st.INK, marker="D", ms=3, lw=0, mfc="white", mew=0.6)]
    ls = [t("聯合 95% 區域（ΔlogL = 3.00）", "Joint 95% region (ΔlogL = 3.00)"),
          t("ΔlogL = 1.92（投影＝c 之 profile CI）", "ΔlogL = 1.92 (projection = profile CI of c)"),
          t("profile 脊線（各 c 之最大似然 SNR₅₀）", "Profile ridge (ML SNR₅₀ at each c)"),
          t(f"叢集自助估計（B = {len(boot)}，corr = {S['corr']:.2f}）".replace("= -", "= −"),
            f"Cluster-bootstrap estimates (B = {len(boot)}, corr = {S['corr']:.2f})".replace("= -", "= −")),
          t(f"細網格峰值（61×61）：c = {S['joint_max_fine'][0]:.2f}、SNR₅₀ = {S['joint_max_fine'][1]:.2f}",
            f"Fine-grid maximum (61×61): c = {S['joint_max_fine'][0]:.2f}, SNR₅₀ = {S['joint_max_fine'][1]:.2f}"),
          t(f"粗網格峰值（26×26）：c = {cg:.2f}、SNR₅₀ = {sg:.2f}",
            f"Coarse-grid maximum (26×26): c = {cg:.2f}, SNR₅₀ = {sg:.2f}")]
    ax.legend(hs, ls, loc="upper left", fontsize=5.8, bbox_to_anchor=(-0.02, -0.15),
              labelspacing=0.3)
    return fig


def draw_reliability():
    import matplotlib.pyplot as plt
    pred = load()[3]
    y = pred["hit"].values.astype(float)
    edges = np.linspace(0, 1, 11)
    fig, (ax, axh) = plt.subplots(2, 1, figsize=(st.SINGLE, 8.6 * st.CM), sharex=True,
                                  gridspec_kw={"height_ratios": [3.0, 1.0], "hspace": 0.08})
    ax.plot([0, 1], [0, 1], "--", color=st.GRAY, lw=0.7)
    width = 0.1
    for k, (col, lab, mk, mfc, off, colr) in enumerate((
            ("p_raw", t("原始預測機率", "Raw predicted probability"), "o", st.BLUE, -0.012, st.BLUE),
            ("p_recal", t("Platt 再校準", "Platt-recalibrated"), "s", "white", 0.012, st.ORANGE))):
        p = pred[col].values
        b = np.clip(np.digitize(p, edges) - 1, 0, 9)
        xs, ys, los, his, ns = [], [], [], [], []
        for j in range(10):
            m = b == j
            if m.sum() == 0:
                continue
            kk, nn = int(y[m].sum()), int(m.sum())
            lo, hi = wilson(kk, nn)
            xs.append(p[m].mean()); ys.append(kk / nn); los.append(kk / nn - lo); his.append(hi - kk / nn); ns.append(nn)
        xs = np.array(xs)
        ax.errorbar(xs + off, ys, yerr=[los, his], fmt=mk + "-", ms=3.0, lw=0.8, color=colr, mfc=mfc,
                    mew=0.8, elinewidth=0.6, capsize=1.4, capthick=0.6, label=lab)
        cnt = np.histogram(p, bins=edges)[0]
        axh.bar(edges[:-1] + width / 2 + (k - 0.5) * width * 0.42, cnt, width=width * 0.4,
                color=colr if k == 0 else "white", edgecolor=colr, lw=0.6)
    fsl = S["fs"]       # 斜率／截距與 95% CI：fs7_final_supplement.json（論文 §4.6 之值）
    txt = (t(f"時間切分測試期（n = {S['n_test']:,} 次試驗）", f"Temporal hold-out test (n = {S['n_test']:,} trials)") + "\n"
           + t(f"原始：校準斜率 {fsl['slope']:.2f} [{fsl['slope_ci95'][0]:.2f}, {fsl['slope_ci95'][1]:.2f}]",
               f"Raw: calibration slope {fsl['slope']:.2f} [{fsl['slope_ci95'][0]:.2f}, {fsl['slope_ci95'][1]:.2f}]") + "\n"
           + t(f"　　　截距 {fsl['intercept']:.2f} [{fsl['intercept_ci95'][0]:.2f}, {fsl['intercept_ci95'][1]:.2f}]",
               f"        intercept {fsl['intercept']:.2f} [{fsl['intercept_ci95'][0]:.2f}, {fsl['intercept_ci95'][1]:.2f}]") + "\n"
           + t(f"原始：log loss {S['raw']['logloss']:.4f}、Brier {S['raw']['brier']:.4f}",
               f"Raw: log loss {S['raw']['logloss']:.4f}, Brier {S['raw']['brier']:.4f}") + "\n"
           + t(f"Platt：log loss {S['recal']['logloss']:.4f}、Brier {S['recal']['brier']:.4f}",
               f"Platt: log loss {S['recal']['logloss']:.4f}, Brier {S['recal']['brier']:.4f}"))
    ax.text(0.03, 0.82, txt.replace("-0.", "−0."), transform=ax.transAxes, ha="left", va="top",
            fontsize=5.8, linespacing=1.35, color=st.INK)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.02)
    ax.set_ylabel(t("觀測偵測率", "Observed detection rate"))
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    axh.set_yscale("log")
    if not fp.is_en():
        from matplotlib.ticker import FuncFormatter
        axh.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axh.set_ylabel(t("試驗數", "Trials"))
    axh.set_xlabel(t("預測偵測機率", "Predicted detection probability"))
    axh.grid(alpha=0.3, axis="y")
    fig.align_ylabels([ax, axh])
    return fig


if __name__ == "__main__":
    S = summary()
    st.run({"fig_fs7_profile_likelihood": draw_profile,
            "fig_fs7_joint_likelihood": draw_joint,
            "fig_fs7_reliability": draw_reliability})
