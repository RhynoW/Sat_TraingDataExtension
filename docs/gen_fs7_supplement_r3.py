#!/usr/bin/env python3
"""
gen_fs7_supplement_r3.py — 由 fs7_review7_analysis.json 生成補充材料終審新增 Section S19（Tables S45–S48）
只讀 JSON，不重算。輸出：docs/_supplement_r3_sections.md
用法：python docs/gen_fs7_supplement_r3.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "data/benchmark/fs7_review7_analysis.json").read_text(encoding="utf-8"))
BIN = {"1-50 m": "1–50 m", "50-100 m": "50–100 m", "100-300 m": "100–300 m", "300 m-1 km": "300 m–1 km", "1-3 km": "1–3 km"}


def main():
    L = ["---", "", "## Section S19. Final-round checks: pre-event window covariates, SP3 overlap arcs, rule-S sign "
         "components, √Δt parameters (main §4.3, §5.4, §5.5)", "",
         "Source for every table in this section: `fs7_review7_analysis.json`, produced by `fs7_review7_analysis.py`.", ""]
    cov = R["M2_covariates"]
    L += ["**Table S45 — Covariates of large-candidate-free and contaminated evaluable events** (key `M2_covariates`). "
          "'Large-candidate-free' means that no SP3 candidate ≥ 500 m, of any verdict, lies in the pre-event window; "
          "smaller candidates may be present.", "",
          "| pre-event window | n | median post-event TLEs within 3 d | median TLE gap (d) | median distance to nearest SP3 candidate, any size (d) | median candidates within ±3 d | share with a candidate within 1 d |",
          "|---|--:|--:|--:|--:|--:|--:|"]
    for k in ("large_candidate_free", "contaminated"):
        v = cov[k]
        L.append(f"| {k.replace('_', '-')} | {v['n']} | {v['median_post_tle_3d']:g} | {v['median_gap_day']} | "
                 f"{v['median_nearest_any_candidate_d']} | {v['median_candidates_pm3d']:g} | {v['frac_with_any_candidate_within_1d']:.2f} |")
    L += ["", "Recall at 45 m (rule S) of large-candidate-free events, with Wilson 95% CIs: " + "; ".join(
        f"{BIN[b]} {v['k']}/{v['n']} = {v['recall']:.2f} [{v['wilson95'][0]:.2f}, {v['wilson95'][1]:.2f}]"
        for b, v in R["M2_recall_wilson_lcf"].items()) + ".", ""]
    a = R["M1_overlap_arcs"]
    L += ["**Table S46 — SP3 overlap-arc consistency of the large-candidate-free 50–300 m events by TLE-response class** "
          "(key `M1_overlap_arcs`). This is an internal-consistency check within the same SP3 processing chain, not "
          "independent verification.", "",
          "| class | n | covered by ≥ 2 arcs | median arcs | median arc spread (m) | max arc spread (m) | median persistence ratio | median amplitude (m) |",
          "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for k, nm in (("no_response", "no response"), ("responding", "delayed / other")):
        v = a[k]
        L.append(f"| {nm} | {v['n']} | {v['multi_arc_n']} | {v['median_n_arcs']:g} | {v['median_arc_spread_m']} | "
                 f"{v['max_arc_spread_m']} | {v['median_persist_ratio']} | {v['median_amp_m']} |")
    L += ["", "No-response events covered by two or more arcs: " + "; ".join(
        f"{e['sat']} {e['t_start']} ({e['step_sp3_m']} m, {e['n_arcs_med']:g} arcs, spread {e['arc_spread_m']} m)"
        for e in a["no_response_multi_arc_events"]) + ".", ""]
    L += ["**Table S47 — Wrong-sign events in large-candidate-free windows** (45 m, rule S; key "
          "`m4_uncontaminated_wrong_sign`).", "",
          "| satellite | campaign | t_start (UT) | SP3 step (m) | E1 residual (m) | gap (d) | \\|ȧ\\| (m/d) | verified events in pre-window | candidates within ±3 d | nearest candidate (d) | arcs |",
          "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in R["m4_uncontaminated_wrong_sign"]:
        L.append(f"| {r['sat']} | {r['campaign']} | {r['t_start']} | {r['step_sp3_m']} | {r['step_obs_m']} | {r['gap_day']} | "
                 f"{r['abs_adot_m_day']} | {r['verified_events_in_prewindow']} | {r['candidates_pm3d']} | "
                 f"{r['nearest_any_candidate_d']} | {r['n_arcs_med']:g} |")
    s = R["M4_sign"]
    L += ["", f"**Table S48 — Rule-S components by hypothesized sign** (n = {s['n_pseudo']:,} pseudo-events; p₊ = "
          f"{s['p_positive']}; key `M4_sign`). {s['note']}", "",
          "| threshold | FP / TN, positive hypothesis | FPR (+) [Wilson] | FP / TN, negative hypothesis | FPR (−) [Wilson] | expected FPR [bootstrap 95% CI] | recall, positive-going events | recall, negative-going events |",
          "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for k, nm in (("45m", "45 m"), ("3s", "unified 3σ")):
        v = s[k]; pp, nn = v["positive"], v["negative"]
        L.append(f"| {nm} | {pp['FP']} / {pp['TN']} | {pp['FPR']:.3f} [{pp['FPR_wilson'][0]:.3f}, {pp['FPR_wilson'][1]:.3f}] | "
                 f"{nn['FP']} / {nn['TN']} | {nn['FPR']:.3f} [{nn['FPR_wilson'][0]:.3f}, {nn['FPR_wilson'][1]:.3f}] | "
                 f"{v['expected_FPR']:.3f} [{v['expected_FPR_bootstrap_ci95'][0]:.3f}, {v['expected_FPR_bootstrap_ci95'][1]:.3f}] | "
                 f"{v['recall_positive_events']['recall']:.2f} (n = {v['recall_positive_events']['n']}) | "
                 f"{v['recall_negative_events']['recall']:.2f} (n = {v['recall_negative_events']['n']}) |")
    m5 = R["M5_sqrt_params"]
    L += ["", "**√Δt form, full-data coefficients** (key `M5_sqrt_params`): linear form c = "
          f"{m5['dt_pow_1']['c_hat']}, SNR₅₀ = {m5['dt_pow_1']['snr50']}, β = {m5['dt_pow_1']['beta']}, SNR₉₀ = "
          f"{m5['dt_pow_1']['snr90']}; √Δt form c = {m5['dt_pow_0.5']['c_hat']}, SNR₅₀ = {m5['dt_pow_0.5']['snr50']}, "
          f"β = {m5['dt_pow_0.5']['beta']}, SNR₉₀ = {m5['dt_pow_0.5']['snr90']}. {m5['note']}", ""]
    out = ROOT / "docs/_supplement_r3_sections.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print(f"輸出：{out}")


if __name__ == "__main__":
    main()
