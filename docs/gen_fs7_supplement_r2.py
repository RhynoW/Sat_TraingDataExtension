#!/usr/bin/env python3
"""
gen_fs7_supplement_r2.py — 由 fs7_review6_analysis.json 生成補充材料 R2 新增 Section S17（Tables S36–S43）
只讀 JSON/CSV，不重算。輸出：docs/_supplement_r2_sections.md
用法：python docs/gen_fs7_supplement_r2.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "data/benchmark"
R = json.loads((BM / "fs7_review6_analysis.json").read_text(encoding="utf-8"))
BIN = {"1-50 m": "1–50 m", "50-100 m": "50–100 m", "100-300 m": "100–300 m", "300 m-1 km": "300 m–1 km", "1-3 km": "1–3 km"}


def ci(x):
    return f"[{x[0]:.2f}, {x[1]:.2f}]"


def main():
    L = ["---", "", "## Section S17. R2 robustness analyses (main §3.3, §4.3–4.5, §5, §5.4–5.5)", "",
         "Source for every table in this section: `fs7_review6_analysis.json`, produced by `fs7_review6_analysis.py`.", ""]
    m1 = R["M1"]
    L += [f"**Table S36 — Outcome classes and TLE-response classes with cluster-bootstrap CIs** "
          f"({m1['n_clusters_sat_campaign']} satellite × campaign clusters, B = 2,000; key `M1`).", "",
          "| population | class | n | proportion [95% CI] |", "|---|---|--:|--:|"]
    for k, v in m1["outcome_classes_131_45m"].items():
        L.append(f"| 131 verified, 45 m, rule S | {k} | {v['n']} | {v['prop']:.2f} {ci(v['ci95'])} |")
    for k, v in m1["clean_50_300m_response_default"].items():
        L.append(f"| large-candidate-free 50–300 m (n = {m1['clean_50_300m_n']}) | {k} | {v['n']} | {v['prop']:.2f} {ci(v['ci95'])} |")
    L += ["", "**Table S37 — Sensitivity of the TLE-response classification** (large-candidate-free events, i.e. no SP3 candidate ≥ 500 m in the pre-event window; ratio cut c means "
          "a response requires a ratio in [c, 1/c], and 'none' requires |ratio| < c at every TLE in the window).", "",
          "| ratio cut | window (d) | 50–300 m: none / delayed / immediate / other | ≥ 300 m: immediate / n |",
          "|--:|--:|---|---|"]
    for r in m1["response_sensitivity"]:
        L.append(f"| {r['ratio_cut']} | {r['window_d']:g} | {r['clean_50_300_none']} / {r['clean_50_300_delayed']} / "
                 f"{r['clean_50_300_immediate']} / {r['clean_50_300_other']} | {r['clean_ge300_immediate']} / {r['clean_ge300_n']} |")
    cv = m1["none_vs_other_covariates"]
    L += ["", "Covariates of no-response (large-candidate-free 50–300 m): " + "; ".join(
        f"{k}: n = {v['n']}, median |ȧ| {v['median_abs_adot_m_day']} m/d, median post-event TLEs within 3 d "
        f"{v['median_n_post_tle_3d']:g}, median gap {v['median_gap_day']} d, median amplitude {v['median_amp_m']} m, "
        f"negative-going {v['frac_negative_step']:.0%}" for k, v in cv.items()) + ". By campaign (none / delayed / other): "
        + "; ".join(f"{c}: {v.get('none', 0)} / {v.get('delayed', 0)} / {v.get('other', 0)}"
                    for c, v in m1["clean_50_300m_by_campaign"].items()) + ". By satellite (none): "
        + ", ".join(f"{s_} {v.get('none', 0)}" for s_, v in m1["clean_50_300m_by_satellite"].items())
        + f". Largest |residual| within 3 d: median {m1['clean_50_300_max_abs_residual_3d_m']['median']} m; "
        f"{m1['clean_50_300_max_abs_residual_3d_m']['n_below_45m']} of {m1['clean_50_300m_n']} never exceed 45 m.", ""]
    m3 = R["M3"]
    L += ["**Table S38 — Pre-event trend contamination by source** (≥ 500 m SP3 candidates in [t_start − 3 d, t_start); "
          "'rejected' means rejected by any check, in practice the common-mode check; key `M3`).", "",
          "| pre-event window | n | recall 45 m (S) | recall 45 m (U) | wrong sign | median \\|residual\\| (m) | median ratio | median \\|ȧ\\| (m/d) | median delay to first post-event TLE (h) | median amplitude (m) |",
          "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in m3["by_source"]:
        L.append(f"| {r['source'].replace('clean', 'large-candidate-free')} | {r['n']} | {r['recall_45_S']:.2f} | {r['recall_45_U']:.2f} | {r['wrong_sign']} | "
                 f"{r['median_abs_residual_m']:,} | {r['median_ratio']} | {r['median_abs_adot_m_day']:,} | "
                 f"{r['median_delay_first_post_tle_h']} | {r['median_amp_m']} |")
    cm = m3["common_mode_contaminated"]
    L += ["", f"Events with a common-mode-rejected ≥ 500 m burn in the pre-event window: "
          f"{m3['n_with_common_mode_rejected_burn_in_prewindow']} (recall {cm['recall_45_S']:.2f}, wrong sign "
          f"{cm['wrong_sign']}; by bin " + ", ".join(f"{BIN[k]} {v}" for k, v in cm["by_bin"].items()) + ").", ""]
    m4 = R["M4"]
    L += ["**Table S39 — 45 m threshold on events never used in the earlier analysis** (key `M4`).", "",
          "| event subset | evaluable n | recall S [Wilson 95% CI] | recall U | discrimination AUC U | discrimination AUC S |",
          "|---|--:|--:|--:|--:|--:|"]
    for tag, nm, n in (("independent_85", "85 events from four campaigns not used earlier", m4["n_events_85_subset_evaluable"]),
                       ("conference_46", "46 events of 2025-07/08 (used earlier)", m4["n_events_46_subset_evaluable"]),
                       ("all_96", "all", m4["n_events_85_subset_evaluable"] + m4["n_events_46_subset_evaluable"])):
        r = m4[tag]
        L.append(f"| {nm} | {n} | {r['recall_S_45m']:.2f} {ci(r['recall_S_45m_wilson'])} | {r['recall_U_45m']:.2f} | "
                 f"{r['AUC_U']:.2f} | {r['AUC_S']:.2f} |")
    L += ["", "Recall by amplitude bin, independent subset (rule S): " + ", ".join(
        f"{BIN[b]} {v['recall']:.2f} (n = {v['n']})" for b, v in m4["independent_85"]["recall_S_by_bin"].items())
        + f". Pseudo-event FPR at 45 m (rule U): {m4['FPR_45m_U']}. Post hoc Youden threshold on the independent subset "
        f"(rule U, reference only): {m4['independent_85_youden_U']['thr_m']:.0f} m.", ""]
    m5 = R["M5"]
    L += ["**Table S40 — Rule-S sensitivity to the hypothesized-sign probability p₊** (key `M5`). Pseudo-event steps: "
          f"{m5['frac_pseudo_positive']:.1%} positive, median {m5['pseudo_step_median_m']} m.", "",
          "| p₊ | FPR (S), 45 m | FPR (S), 3σ | discrimination AUC (S) |", "|--:|--:|--:|--:|"]
    for r in m5["rows"]:
        L.append(f"| {r['p_positive']} | {r['FPR_S_45m']:.3f} | {r['FPR_S_3s']:.3f} | {r['AUC_S']:.3f} |")
    m2 = R["M2"]
    L += ["", "**Table S41 — E1-based logistic models versus the D1-based descriptive probability** "
          "(96 evaluable events; outcome = E1 detection at 45 m, rule S; key `M2`). " + m2["note"], "",
          "| model | log loss | Brier | AUC |", "|---|--:|--:|--:|"]
    for k, nm in (("log_amp", "E1 logistic: log₁₀ amplitude (LOCO)"), ("log_amp_plus_contam", "E1 logistic: + contamination indicator (LOCO)")):
        v = m2[k]; L.append(f"| {nm} | {v['loco_logloss']} | {v['loco_brier']} | {v['loco_auc']} |")
    v = m2["D1_descriptive_probability"]; L.append(f"| D1-based descriptive probability (no refit) | {v['logloss']} | {v['brier']} | {v['auc']} |")
    v = m2["base_rate"]; L.append(f"| base rate | {v['logloss']} | {v['brier']} | — |")
    m7 = R["M7"]
    L += ["", "**Table S42 — Profile likelihood of c on an extended grid (c ≤ 100) with unclipped SNR** (key `M7`). "
          "The c → ∞ limit is the drag-only model Δa/(|ȧ|Δt), in which σ_TLE drops out.", "",
          "| data | ĉ | 95% set | ℓ(ĉ) | ℓ(0.32) | ℓ(drag-only limit) | interior maximum |", "|---|--:|---|--:|--:|--:|---|"]
    for k in ("decim_1", "decim_2", "decim_4", "decim_all"):
        v = m7[k]
        L.append(f"| {k.replace('decim_', '') + ('×' if k != 'decim_all' else ' cadences')} | {v['c_hat']} | "
                 f"[{v['ci95'][0]}, {v['ci95'][1]}] | {v['ll_at_c_hat']} | {v['ll_at_c032']} | {v['ll_drag_only_limit']} | "
                 f"{'yes' if v['interior_max'] else 'no'} |")
    L += ["", "*Numerical floor artifact.* The released analysis scripts bound SNR_eff to [10⁻², 10⁴] before taking "
          "logarithms. This has no effect for c ≤ 10 (at most 0.2% of trials reach the floor). On an extended grid, "
          "however, a growing share of trials is floored, which acts as a spurious low-SNR plateau and inflates the "
          "likelihood. Without the bound, the likelihood decreases monotonically toward the drag-only limit beyond the "
          "interior maximum:", "",
          "| c | share of trials below 10⁻² | ℓ unclipped | ℓ with floor |", "|--:|--:|--:|--:|"]
    for r in m7["clip_artifact_demo"]:
        L.append(f"| {r['c']} | {r['frac_below_1e-2']:.3f} | {r['ll_unclipped']} | {r['ll_clipped_1e-2']} |")
    L += ["", "All published estimates use c ≤ 10 and are unaffected. The R2 analyses of alternative drag proxies use unclipped SNR.", ""]
    L += ["**Table S43a — Alternative drag proxies** (calibration-split fit, test-split evaluation; key `M8`).", "",
          "| ambiguity term | ĉ (calibration) | calibration mean log-likelihood | held-out log loss | held-out AUC |",
          "|---|--:|--:|--:|--:|"]
    for r in R["M8"]:
        L.append(f"| {r['proxy']} | {r.get('c_hat_cal', '—')} | {r.get('cal_mean_ll', '—')} | {r['heldout_logloss']} | {r['heldout_auc']} |")
    L += ["", "**Table S43b — Model-implied Δa₉₀ (full-data fit) under the linear and √Δt forms versus the interpolated empirical "
          "Δa₉₀** (key `M8_da90`).", "", "| condition | linear Δt: model (m) | √Δt: model (m) | interpolated empirical (m) |",
          "|---|--:|--:|--:|"]
    a = {r["cond"]: r for r in R["M8_da90"]["dt_pow_1"]["rows"]}; b = {r["cond"]: r for r in R["M8_da90"]["dt_pow_0.5"]["rows"]}
    for d in (1, 2, 4):
        for band in ("low", "mid", "high"):
            k = f"{d}x_{band}"
            L.append(f"| {d}×·{band} | {a[k]['model_da90_m']} | {b[k]['model_da90_m']} | {a[k]['interp_da90_m']} |")
    L += ["", f"Ratio interpolated / model: linear {R['M8_da90']['dt_pow_1']['ratio_range']}, √Δt "
          f"{R['M8_da90']['dt_pow_0.5']['ratio_range']} (√Δt: ĉ = {R['M8_da90']['dt_pow_0.5']['c_hat']}, SNR₉₀ = "
          f"{R['M8_da90']['dt_pow_0.5']['snr90']}).", ""]
    m9 = R["m9"]
    L += [f"**Table S43c — D1 parameter sensitivity** (all 15,774 injections replayed with identical windows and injection "
          f"indices; baseline agreement with the published hits {m9['baseline_hit_agreement_with_published_trials']:.4f}; "
          "per-condition values in `fs7_review6_detector_sensitivity.csv`; the false-alarm rate is the replay's flags per "
          "satellite per 30 days in control windows, averaged over conditions).", "",
          "| setting | κ | h | MAD multiplier | interpolated Δa₉₀ range (m) | max relative change | Spearman vs baseline | false-alarm rate |",
          "|---|--:|--:|--:|---|--:|--:|--:|"]
    for r in m9["settings"]:
        L.append(f"| {r['setting']} | {r['kappa']} | {r['h']:g} | {r['mad_z']:g} | {r['da90_range_m'][0]:.0f}–{r['da90_range_m'][1]:.0f} | "
                 f"{r['max_rel_change_da90']:.1%} | {r['spearman_da90_vs_baseline']:.3f} | {r['far_pooled_flags_per_30d']} |")
    L.append("")
    out = ROOT / "docs/_supplement_r2_sections.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print(f"輸出：{out}")


if __name__ == "__main__":
    main()
