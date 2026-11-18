#!/usr/bin/env python3
"""
gen_fs7_supplement_r1.py — 由 fs7_review5_analysis 之產物生成補充材料 R1 新增章節（S11–S16）之 Markdown
=======================================================================================
只讀 data/benchmark/fs7_review5_analysis.json 與 fs7_review5_recall_grid.csv、
fs7_review5_threshold_sweep.csv；不重算任何數字，避免手抄錯誤。
輸出：docs/_supplement_r1_sections.md（供貼入 paper_fs7_supplement_EN.md）
用法：python docs/gen_fs7_supplement_r1.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "data/benchmark"
R = json.loads((BM / "fs7_review5_analysis.json").read_text(encoding="utf-8"))
BIN_EN = {"1-50 m": "1–50 m", "50-100 m": "50–100 m", "100-300 m": "100–300 m",
          "300 m-1 km": "300 m–1 km", "1-3 km": "1–3 km", "all": "all"}
COND_ORDER = [(d, b) for d in (1, 2, 4) for b in ("low", "mid", "high")]


def f2(x):
    return f"{x:.2f}"


def s11():
    out = ["## Section S11. Selection bias of the evaluable event population (main §2.6, Table 2b)", ""]
    sb = R["selection_bias"]
    ex = sb["exclusion_reason_counts"]
    out += [f"Exclusion reasons (coverage rule of main §2.6): pre-event window with fewer than three TLEs only, "
            f"{ex['pre_window_lt3_only']}; empty post-event window only, {ex['post_window_empty_only']}; both, {ex['both']}. "
            f"Distribution of the number of pre-event TLEs among excluded events: "
            + ", ".join(f"{k} TLE: {v}" for k, v in sb["excluded_pre_n_distribution"].items()) + ".", ""]
    et, it = sb["excluded_timing_h"], sb["included_timing_h"]
    out += [f"Timing of TLE coverage. Excluded events: median time since the last TLE before t_start "
            f"{et['since_last_tle_median']} h (IQR {et['since_last_tle_iqr'][0]}–{et['since_last_tle_iqr'][1]} h), "
            f"median time from t_end to the next TLE {et['to_next_tle_median']} h "
            f"(IQR {et['to_next_tle_iqr'][0]}–{et['to_next_tle_iqr'][1]} h). Included events: "
            f"{it['since_last_tle_median']} h and {it['to_next_tle_median']} h.", ""]
    out += ["**Table S28 — Real-event recall under alternative treatments of excluded events, both thresholds** "
            "(rule S). Source: `fs7_review5_analysis.json` (`selection_bias.recall_bounds_by_bin`).", "",
            "| bin | verified | evaluable | 45 m: evaluable | 45 m: IPW | 45 m: worst | 45 m: best | 3σ: evaluable | 3σ: IPW | 3σ: worst | 3σ: best |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in sb["recall_bounds_by_bin"]:
        out.append(f"| {BIN_EN[r['bin']]} | {r['n_verified']} | {r['n_included']} | "
                   + " | ".join(f2(r[k]) for k in ("recall_incl_45", "ipw_campaign_45", "worst_45", "best_45",
                                                  "recall_incl_3s", "ipw_campaign_3s", "worst_3s", "best_3s")) + " |")
    out += ["", sb["ipw_note"], ""]
    return out


def s12():
    out = ["## Section S12. Coefficient interpretation: per-cadence c and the drag-ambiguity term (main §3.3)", "",
           "**Table S29 — Per-cadence profile-likelihood estimate of c and the derived drag-ambiguity term by condition.** "
           "Source: `fs7_review5_analysis.json` (`per_cadence_c`, `drag_term_by_condition`). Grid `logspace(−1.3, 1.0, 47)`; "
           "95% set ℓ(ĉ) − ℓₚ(c) ≤ 1.9208.", "",
           "| cadence | ĉ | 95% profile set | set reaches grid edge |", "|---|--:|---|---|"]
    for k, v in R["per_cadence_c"].items():
        out.append(f"| {k.split('_')[1]}× | {v['c_hat']} | [{v['profile_ci95'][0]}, {v['profile_ci95'][1]}] | "
                   f"{'yes' if v['ci_touches_grid_edge'] else 'no'} |")
    out += ["", "| condition | σ_TLE (m) | c·\\|ȧ\\|·Δt, c = 0.32 (m) | c·\\|ȧ\\|·Δt, c = 0.28 (m) | σ_eff, c = 0.32 (m) | drag share of σ_eff² |",
            "|---|--:|--:|--:|--:|--:|"]
    dt = {(r["decim"], r["drag"]): r for r in R["drag_term_by_condition"]}
    for d, b in COND_ORDER:
        r = dt[(d, b)]
        out.append(f"| {d}×·{b} | {r['sigma_m']} | {r['drag_term_m_c032']} | {r['drag_term_m_c028']} | "
                   f"{r['sigma_eff_m_c032']} | {r['drag_share_of_var']} |")
    out += ["", "At 1× the profile likelihood increases monotonically to the upper grid edge, so c is not identified "
            "from 1× trials alone; the lower bound of the 95% set (0.56) exceeds the pooled estimate.", ""]
    return out


def s13():
    g = pd.read_csv(BM / "fs7_review5_recall_grid.csv")
    out = ["## Section S13. Injection recall at every grid amplitude and the interpolated Δa₉₀ (main §4.1, Table 4a)", "",
           "**Table S30 — Injection recall by condition and grid amplitude**, with satellite × window cluster-bootstrap "
           "95% CIs (B = 2,000). Source: `fs7_review5_recall_grid.csv`.", ""]
    amps = sorted(g["da_m"].unique())
    out.append("| condition | " + " | ".join(f"{int(a)} m" for a in amps) + " |")
    out.append("|---|" + "--:|" * len(amps))
    for d, b in COND_ORDER:
        sub = g[(g.decim == d) & (g.drag == b)].set_index("da_m")
        out.append(f"| {d}×·{b} | " + " | ".join(
            f"{sub.loc[a, 'recall']:.2f} [{sub.loc[a, 'ci_lo']:.2f}, {sub.loc[a, 'ci_hi']:.2f}]" for a in amps) + " |")
    out += ["", "Interpolation: the recall curve is made monotone non-decreasing by pool-adjacent-violators, and the 0.90 "
            "crossing is interpolated linearly in log₁₀Δa between the bracketing grid amplitudes; the bootstrap repeats "
            "both steps in every resample. Source of Table 4a: `fs7_review5_analysis.json` (`da90_interpolated`).", ""]
    out += ["**Table S31 — Within-cadence stratification by residual lag-1 autocorrelation r₁** (terciles of r₁ within each "
            "cadence; observed minus mean predicted recall under the descriptive-refit coefficients). Source: "
            "`fs7_review5_analysis.json` (`autocorr_stratification`).", "",
            "| cadence | r₁ tercile | median r₁ | windows | interpolated Δa₉₀ [95% CI] | obs − pred (all Δa) | obs − pred (Δa ≤ 200 m) |",
            "|---|---|--:|--:|--:|--:|--:|"]
    order = {"low": 0, "mid": 1, "high": 2}
    rows = sorted(R["autocorr_stratification"]["by_cadence_r1_tercile"], key=lambda r: (r["decim"], order[r["r1_tercile"]]))
    for r in rows:
        out.append(f"| {r['decim']}× | {r['r1_tercile']} | {r['r1_median']} | {r['n_windows']} | "
                   f"{r['interp_da90_m']:.0f} m [{r['interp_ci95_m'][0]:.0f}, {r['interp_ci95_m'][1]:.0f}] | "
                   f"{r['obs_minus_pred_recall']:+.3f} | {r['obs_minus_pred_recall_da_le_200m']:+.3f} |")
    h = R["autocorr_stratification"]["heldout_r1_covariate"]
    out += ["", f"Adding r₁ as a covariate to the calibration-split logistic model (c = 0.28 fixed) changes the held-out "
            f"log loss from {h['snr_eff']['heldout_logloss']} to {h['snr_eff_plus_r1']['heldout_logloss']} "
            f"(r₁ coefficient {h['snr_eff_plus_r1']['coef'][2]}). Correlation of r₁ with log₁₀ SNR_eff: "
            f"{R['autocorr_stratification']['corr_r1_logsnr_eff']}.", ""]
    ha = R["heldout_auc"]
    out += [f"Held-out AUC (trial level, {ha['n_clusters']} clusters, B = 2,000): drag-aware {ha['drag_aware']} "
            f"[{ha['drag_aware_ci'][0]}, {ha['drag_aware_ci'][1]}], amplitude-only {ha['amplitude_only']} "
            f"[{ha['amplitude_only_ci'][0]}, {ha['amplitude_only_ci'][1]}], difference {ha['delta']} "
            f"[{ha['delta_ci'][0]}, {ha['delta_ci'][1]}].", ""]
    return out


def s14():
    st = R["storm_alignment"]
    out = ["## Section S14. Storm-interval candidates and geomagnetic activity (main §5.1)", "",
           f"**Table S32 — The 21 storm-interval candidates aligned with the GFZ 3-hourly Kp index** [main ref. 14]. "
           f"Main-phase onset (first Kp ≥ 7 in the sample): {st['main_onset_kp_ge7']} UT; Kp peak {st['kp_peak']} at "
           f"{st['kp_peak_time']} UT. 'Kp slot' is the 3-h interval containing t_start. Source: `fs7_review5_analysis.json` "
           f"(`storm_alignment`), `data/space_weather/gfz_kp_3h_2024-04_05.csv`.", "",
           "| satellite | t_start (UT) | step (m) | Kp slot | max Kp, preceding 24 h | F10.7 obs (sfu) | hours from main-phase onset |",
           "|---|---|--:|--:|--:|--:|--:|"]
    for c in st["candidates"]:
        out.append(f"| {c['sat']} | {c['t_start']} | {c['step_m']} | {c['kp_slot']:.1f} | {c['kp_max_prev24h']:.1f} | "
                   f"{c['f107_obs']:.0f} | {c['h_from_main_onset']:+.1f} |")
    out += ["", "The project's earlier daily index file carried a constant fill value for Kp in April–May 2024 and is not used.", ""]
    inc = R["inclination"]
    out += ["**Inclination corroboration** (main §2.7). Robust scale of the inclination change across all candidates "
            f"{inc['robust_sigma_di_deg']}°; corroboration level 4σ = {inc['threshold_4sigma_deg']}°. Verified events with "
            f"an inclination signature: {inc['verified_131_with_inc_corroboration']} of {inc['verified_131_n']}; rejected "
            f"candidates: {inc['rejected_with_inc_signature']} of {inc['rejected_n']} (persistence 3, common mode 2, both 1).", ""]
    return out


def s15():
    sr = R["symmetric_rules"]; sw = R["threshold_sweep"]
    out = ["## Section S15. Symmetric decision rules and threshold sweep (main §5.4)", "",
           f"Pseudo-event draw: Draw C (n = {sr['n_pseudo']:,}). Hypothesized sign for rule S: positive with probability "
           f"{sr['p_positive_sign_real_events']} (the real-event sign mix), applied in expectation.", "",
           "**Table S33 — Original asymmetric and symmetric rules.** Source: `fs7_review5_analysis.json` "
           "(`symmetric_rules`, `threshold_sweep`); full sweep in `fs7_review5_threshold_sweep.csv`.", "",
           "| threshold | rule | TP | FP | recall | FPR |", "|---|---|--:|--:|--:|--:|"]
    for thr in ("45 m", "unified 3σ"):
        o = sr[thr]["original_asymmetric"]; u = sr[thr]["U_sign_free_both"]; s = sr[thr]["S_sign_constrained_both"]
        out.append(f"| {thr} | original (TP sign-constrained, FP sign-free) | {o['TP']} | {o['FP']} | {o['recall']:.3f} | {o['FPR']:.3f} |")
        out.append(f"| {thr} | S (both sign-constrained) | {s['TP']} | {s['FP_expected']} | {s['recall']:.3f} | {s['FPR']:.3f} |")
        out.append(f"| {thr} | U (both sign-free) | {u['TP']} | {u['FP']} | {u['recall']:.3f} | {u['FPR']:.3f} |")
    out += ["", f"ROC AUC (real events versus pseudo-events; events and per-satellite pseudo-events resampled separately, "
            f"B = 2,000): rule U {sw['AUC_U']} [{sw['AUC_U_ci'][0]}, {sw['AUC_U_ci'][1]}]; rule S {sw['AUC_S']} "
            f"[{sw['AUC_S_ci'][0]}, {sw['AUC_S_ci'][1]}]. Post hoc Youden threshold (reference only): "
            f"{sw['youden_U']['thr_m']:.0f} m (U: recall {sw['youden_U']['recall_U']}, FPR {sw['youden_U']['FPR_U']}; "
            f"S: recall {sw['youden_S']['recall_S']}, FPR {sw['youden_S']['FPR_S']}). Smallest swept threshold with "
            f"FPR ≤ 0.01: rule S {sw['fpr_le_0.01']['S']['thr_m']:.0f} m (recall {sw['fpr_le_0.01']['S']['recall_S']}); "
            f"rule U {sw['fpr_le_0.01']['U']['thr_m']:.0f} m (recall {sw['fpr_le_0.01']['U']['recall_U']}). "
            f"{sw['precision_note'][0].upper() + sw['precision_note'][1:]}", "",
            "![](fig_fs7_threshold_sweep.png)", "",
            "**Fig. S5** ROC curves (left) and recall/FPR versus threshold (right) for the 96 evaluable real events and the "
            "1,145 pseudo-events under rules S and U; dots and the dotted line mark the pre-specified 45 m threshold. "
            "Data: `fs7_review5_threshold_sweep.csv`; script: `fs7_review5_analysis.py`.", ""]
    return out


def s16():
    md = R["miss_decomposition"]
    out = ["## Section S16. Decomposition of real-event outcomes (main §5.5, Table 6)", "",
           "**Table S34 — Outcome classes of all 131 verified events by amplitude bin** (rule S). Classes: excluded "
           "(pre-event coverage), excluded (post-event coverage), detected, below threshold, sign mismatch (|residual| "
           "above threshold, opposite sign). Source: `fs7_review5_analysis.json` (`miss_decomposition`); per-event "
           "classes in `fs7_review5_event_decomposition.csv`.", "",
           "| bin | 45 m: excl. pre / excl. post / detected / below / wrong sign | 3σ: excl. pre / excl. post / detected / below / wrong sign |",
           "|---|---|---|"]
    keys = ("excl_pre", "excl_post", "detected", "below_threshold", "sign_mismatch")
    for b in list(md["class_by_bin_45"].keys()):
        a = md["class_by_bin_45"][b]; c = md["class_by_bin_3s"][b]
        out.append(f"| {BIN_EN[b]} | " + " / ".join(str(a.get(k, 0)) for k in keys) + " | "
                   + " / ".join(str(c.get(k, 0)) for k in keys) + " |")
    mb = md["multi_burn"]
    out += ["", f"Shared TLE interval (another verified event between the last pre-event and first post-event TLE): "
            f"45 m recall {mb['45']['shared_interval']['recall']} (n = {mb['45']['shared_interval']['n']}) versus "
            f"{mb['45']['single']['recall']} (n = {mb['45']['single']['n']}) for isolated events; 3σ: "
            f"{mb['3s']['shared_interval']['recall']} versus {mb['3s']['single']['recall']}.", ""]
    out += ["**Table S35 — TLE response class by amplitude bin and pre-event trend status** (evaluable events). "
            + md["tle_response_def"] + " Contaminated: an SP3 candidate of any verdict with |step| ≥ 500 m lies in the "
            "pre-event trend window.", "",
            "| bin | clean: immediate / delayed / none / other | contaminated: immediate / delayed / none / other |",
            "|---|---|---|"]
    rk = ("immediate", "delayed", "none", "other")
    bins = list(BIN_EN)[:5]
    for b in bins:
        a = md["tle_response_by_bin_clean"].get(b, {}); c = md["tle_response_by_bin_contaminated"].get(b, {})
        out.append(f"| {BIN_EN[b]} | " + " / ".join(str(a.get(k, 0)) for k in rk) + " | "
                   + " / ".join(str(c.get(k, 0)) for k in rk) + " |")
    out += ["", "**Misses in the 1–3 km bin (45 m).**", "",
            "| satellite | campaign | t_start (UT) | SP3 step (m) | TLE residual (m) | gap (d) | verified events in pre-window | SP3 candidates ≥ 500 m in pre-window (any verdict) |",
            "|---|---|---|--:|--:|--:|--:|--:|"]
    for r in md["bin_1_3km_misses_45"]:
        out.append(f"| {r['sat']} | {r['campaign']} | {r['t_start']} | {r['step_sp3_m']} | {r['step_obs_m']} | "
                   f"{r['gap_day']} | {r['n_events_in_pre_window']} | {r['n_large_steps_pre_window_any_verdict']} |")
    out += ["", f"Of the 16 wrong-sign events at 45 m, {md['sign_mismatch_45_pre_contaminated']} have a contaminated "
            "pre-event window.", ""]
    return out


def main():
    lines = ["---", ""] + s11() + ["---", ""] + s12() + ["---", ""] + s13() + ["---", ""] + s14() \
        + ["---", ""] + s15() + ["---", ""] + s16()
    out = ROOT / "docs/_supplement_r1_sections.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"輸出：{out}")


if __name__ == "__main__":
    main()
