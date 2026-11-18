# Response to Reviewers — Revision R2

**Manuscript:** *Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits*

We thank the reviewer for the second report and for recommending minor revision. We have addressed every point. To keep the main text concise, the alternative-proxy table and the transfer-conditions table (Table 7 in R1) have moved to the Supplementary Material as Tables S43a and S44; their key values remain in §4.3 and §7. The new analyses are produced by `fs7_review6_analysis.py`, which writes `fs7_review6_analysis.json`, and are reported in the main text and in the new Supplementary Section S17 (Tables S36–S43). Two findings from this round are reported openly below:

- an alternative √Δt drag proxy outperforms the pre-specified form (M8);
- a numerical-floor artifact appears in likelihood profiles on extended grids. It does not affect any published estimate (M7).

An anonymized review package with a minimal reproduction script now accompanies the submission (M9).

---

## Major comments

### M1. Precise causal and statistical framing of "most sub-300 m real events leave no TLE response"

**Response.**

- **Definition.** "No TLE response" is a ratio-based classification, independent of the 45 m threshold and of the sign and coverage classes. An event has no response when |TLE residual / SP3 step| < 0.5 at *every* TLE within [t_end + 2 h, t_end + 3 d]. This window is E1's own post-event window, so the classification uses the same TLEs as E1. The definitions of the immediate, delayed and other classes are given in Table 6a.
- **Main-text table with CIs.** New Table 6a lists all outcome classes (coverage, detected, below threshold, wrong sign) for the 131 events. It also lists the TLE-response classes for the 22 clean-window events of 50–300 m. CIs come from a cluster bootstrap over 23 satellite × campaign clusters. The no-response share is 17/22 = 0.77 [0.50, 0.97], and 0 of the 22 respond immediately.
- **Strata.** The 17 no-response events are spread over five satellites (Table S37 note). Twelve of the 17 come from the 2025-07/08 campaign.
- **Window and threshold sensitivity.** Varying the ratio cut over {0.3, 0.5, 0.7} and the window over {3, 5, 7} d gives 10–17 no-response events out of 22. Zero events respond immediately in every variant, and 4 of the 5 clean events of ≥ 300 m respond immediately in every variant (Table S37). Within 3 days, 16 of the 22 events never exceed 45 m at any TLE. The classification does not use the threshold at all.
- **Alternative explanations.** Compared with the responding events, no-response events have fewer post-event TLEs (median 4 versus 7), smaller amplitudes (97 m versus 178 m) and more negative-going steps (65% versus 40%). §5.5(c) lists four open explanations: TLE-generation smoothing or delay, SP3-side truth losses, sparse post-event coverage, and amplitudes near the effective ambiguity.
- **Wording.** We adopted the reviewer's phrasing. The abstract, §5.5 and the Conclusion now say "consistent with a limitation upstream of the detector," and §5.5 calls the decomposition explicitly "descriptive, not causal."

### M2. Earlier and clearer statement of the D1/E1 distinction

**Response.**

- §5 now opens with a highlighted statement that the D1-calibrated model cannot validate E1 detection probabilities.
- The Table 4 column is renamed "D1-based descriptive probability (mean)."
- The Fig. 6 caption states that the panel is not a goodness-of-fit test of E1.
- As the reviewer suggested, we fitted simple E1-based logistic models evaluated by leave-one-campaign-out (Table S41). On log₁₀ amplitude alone, log loss is 0.58 and AUC 0.79. Adding a contamination indicator gives 0.52 and 0.87. The base-rate log loss is 0.67. The D1-based probabilities give log loss 2.06 and AUC 0.55 on the same events. This quantitatively confirms that they must not be read as E1 probabilities. A calibrated E1 model is future work.

### M3. Fuller quantification of the effect of excluding coordinated maneuvers

**Response.** §5.5(b) now contains the requested quantification (Table S38).

- **Prevalence.** In 27 of the 96 evaluable events (28%), the pre-event window contains a ≥ 500 m candidate rejected by the common-mode check. They are spread across all amplitude bins (7, 3, 3, 4 and 10).
- **E1 behavior.** For these events, recall is 0.74 under rule S and 1.00 under rule U, and 7 have wrong-sign residuals. The median |residual| is 2,168 m in the rejected-only group, compared with 6.4 m in clean windows, and the median residual/step ratio is 1.74. The median delay to the first post-event TLE is 16.7 h, compared with 8.2 h.
- **Interpretation.** We state that these burns cannot be independently verified and are not treated as necessarily real. We also note that they appear in the independently produced TLEs as orbit changes of the expected size, which suggests that at least the large rejected candidates are real burns rather than processing artifacts.
- **Scope.** The exclusion of coordinated maneuvers was already stated in the abstract and in contribution 1. It is also reflected in the Conclusion, which now names coordinated burns as a contaminating factor.

### M4. Transparency about the origin of the 45 m threshold

**Response.** Box 1 now gives the full provenance as far as it is documented.

- 45 m was adopted in our earlier conference analysis as about 3 × a TLE noise scale of about 15 m for FS7. It is a noise-based rule and was not chosen by optimizing any detection metric.
- **We state candidly that the data period and estimator behind the ≈ 15 m scale were not recorded**, so we cannot show that its estimation data are disjoint from the present evaluation.
- The conference analysis did apply the threshold to the 46 events of the 2025-07/08 campaign.
- We therefore added a check on the **85 events never used in that analysis** (53 evaluable; §5.4; Table S39). Recall at 45 m is 0.36 [0.24, 0.49] under rule S and 0.55 under rule U, compared with 0.42 [0.28, 0.57] and 0.56 on the conference-campaign events. The discrimination AUC is 0.72 versus 0.73. The full threshold sweep (Fig. S5) shows the robustness to the threshold choice.
- 45 m is now labelled "pre-specified threshold from prior analysis" in Box 1, Table 4 and §5.4, with the explicit statement that it is not a recommended operating point.

### M5. Rigorous definition of the two AUCs

**Response.**

- **Naming.** The two quantities are now named the *injection-trial AUC* and the *real-event/pseudo-event discrimination AUC* (§3.5). For each, §3.5 states the positive class, negative class, unit, pairing and resampling. The discrimination AUC is not quoted in the abstract or conclusion.
- **Hypothesized sign.** It is drawn from the real-event sign mix (p₊ = 0.521) and applied in expectation. Varying p₊ from 0 to 1 changes the rule-S FPR from 0.019 to 0.032 at 45 m and from 0.273 to 0.275 at 3σ, and leaves the rule-S AUC unchanged at 0.588. The pseudo-event steps are nearly sign-symmetric (48.4% positive) (§5.4; Table S40).

### M6. Conditional drag attribution of the storm candidates

**Response.**

- **Wording.** The abstract and conclusion now say "storm-consistent candidates, drag-attributed under the available evidence," and "a distinct false-alarm mode under the evaluated screening rules."
- **Alternatives.** §5.1 lists four alternatives that cannot be excluded: unannounced single-satellite maneuvers; sequential small corrections that evade the ±3 h common-mode rule; changes in TLE or SP3 processing; and correlated residual structure.
- **Records.** No public FS7 maneuver record for the interval was available to this study.

### M7. More prominent treatment of the structural limitation at 1×

**Response.**

- **Prominence.** The limitation now appears in the abstract ("at the densest cadence, however, the model under-predicts the 90% amplitude"), in §4.4 as a bold operational statement, in Box 2, and in limitation (iv). Box 2 states that the formula "must not be used to set a conservative threshold for densely updated objects." It recommends the upper CI bound of the interpolated empirical Δa₉₀ as the conservative alternative. The 22 m value is marked as an extrapolation (dagger in the §4.4 table, and Box 2).
- **Grid upper bound.** The published grid ended at c = 10. We extended it to c = 100 (Table S42). In doing so we found a numerical artifact. The analysis scripts bound SNR_eff to [10⁻², 10⁴], and for very large c a growing share of trials hits the lower bound (12% at c = 100). This acts as a spurious plateau and inflates the likelihood. Without the bound, the likelihood beyond the interior maximum declines monotonically toward the drag-only limit c → ∞.
  - **Published estimates are unaffected:** at most 0.2% of trials are floored for c ≤ 10, and the pooled, 2× and 4× maxima are unchanged (0.32, 0.32, 0.28).
  - At 1×, the unbounded likelihood rises monotonically to the drag-only limit, with 95% set [0.56, ∞). Extending the grid therefore confirms, rather than changes, the non-identification at 1×. At the densest cadence, σ_TLE contributes nothing identifiable within this functional form.

### M8. Physical mechanism of the drag term

**Response.**

- **Interpretation.** §3.3 now states that c·|ȧ|·Δt is an empirical effective ambiguity that does not separate tracking, SGP4-fitting, density-model, solar-lag and update-strategy contributions, and that "drag-related" is not a causal attribution. The form |ȧ|·Δt was specified in advance as the drag-induced change in a between consecutive updates.
- **Alternative proxies.** As requested, we tested c·|ȧ|·Δt^p for p ∈ {0, 0.5, 2} and a drag-only form (§4.3; Table S43a). Every drag-dependent variant beats the amplitude-only model.
- **The √Δt form fits better than the pre-specified linear form,** on both the calibration split (mean log-likelihood −0.2250 versus −0.2317) and the held-out split (log loss 0.1159 versus 0.1238; AUC 0.981 versus 0.977). It also removes most of the 1× under-prediction: the ratio of interpolated to model Δa₉₀ narrows from 0.64–1.85 to 0.67–1.28. It under-predicts 4×·high instead (372 m versus 476 m).
- **Protocol.** By protocol, we keep the pre-specified linear form as the main model and report √Δt as a post hoc finding requiring independent confirmation. It is consistent with a diffusive component of the inter-TLE ambiguity, which also agrees with the positive lag-1 correlations of Appendix B.
- **Role of σ_TLE.** Dropping σ_TLE altogether barely changes held-out performance (0.1243). This is reported as well.

### M9. Verification of the data and code release

**Response.** An anonymized review package (`paperB_review_package_R2.zip`, 81 files, 1.2 MB) accompanies this resubmission. It contains:

- all analysis and figure scripts;
- all derived JSON/CSV tables, including every R1 and R2 product (`fs7_review5_analysis.json`, `fs7_review6_analysis.json`, `docs/gen_fs7_supplement_r1.py`, `docs/gen_fs7_supplement_r2.py`);
- the TLE epoch list (NORAD × epoch), which is metadata permitted by the Space-Track agreement;
- a SHA-256 manifest;
- `README_REVIEW.md`.

`fs7_repro_minimal.py` runs in seconds with NumPy and pandas only, without credentials or a database. It re-derives and checks the main values of Table 3, Table 4a (all nine conditions), Table 4 and Table 5, and exits with code 0 when all checks pass, which they do. The README lists the results that need the raw TLE archive. Table S1b maps every main-text item to its final file, key and script. The repository DOI will be added at acceptance.

### M10. Distinguishing detector level from TLE-product level in the abstract and conclusion

**Response.**

- The first highlight now reads "Detector-level 90% recall under TLE-equivalent injections: ~40 m to ~480 m."
- The abstract asks "how large a TLE-equivalent perturbation a specified detector reveals," and states "upper bounds for the detector, not end-to-end limits of the TLE product."
- The Conclusion states that the values "should not be interpreted as end-to-end maneuver-detection limits of the public TLE product."

---

## Minor comments

**m1. Abstract length.** Shortened from 228 to 183 words. The core messages are retained: independent truth, the injection upper bound, the gain from the drag term, the 1× caveat, real-event recall, the upstream limitation and the storm false-alarm mode.

**m2. "SP3-consistency-verified" at first use.** The term now appears and is defined in the abstract.

**m3. Interpretation of the bounds.** The notes to Table 2b state that the worst and best cases are logical bounds under the stated missing-data scenarios, not statistical confidence intervals.

**m4. Identifiability of the IPW.** The notes to Table 2b state that IPW is identifiable only at the campaign level and cannot correct a satellite or satellite × campaign missingness mechanism.

**m5. Causal language about the 1× residual.** "Indicates" is changed to "is consistent with the possibility that."

**m6. The 22 m extrapolation.** It is marked with a dagger and a footnote in the §4.4 table, and in Box 2. The value appears only in model-implied quantities, not in the empirical Table 4a or Fig. 3.

**m7. Error-rate terminology.** Usage was checked throughout the main text and supplement. A terminology note has been added to the supplement next to Table S1b.

**m8. Denominator and time window of precision.** §4.5 now states that FP counts flags *before* the injected index minus the tolerance, that flags after the injection outside the tolerance are excluded, and that the measure depends on the pre-injection length (13–25 TLEs at 1×) and on the background rate. Event-level precision and false-discovery proportion are given in Table S20, and the event-level false-alarm rate is recommended as the more transferable quantity.

**m9. CUSUM sensitivity.** All 15,774 injections were replayed with identical windows and injection indices; the baseline reproduces every published hit exactly. With h = 4 or 6, or κ = 0.25 or 1.0, Δa₉₀ changes by ≤ 6.7% and the ordering of conditions is preserved (Spearman ≥ 0.98). Raising the MAD multiplier from 3 to 4 changes Δa₉₀ by up to 47% while preserving the ordering (Spearman 0.97). The MAD rule therefore dominates D1's sensitivity (§4.5; Table S43c).

**m10. File versions.** The new Table S1b maps every main-text table, figure and number to its final file, key and script, and lists the superseded files.

**m11. References.** DOIs were added in R1 for refs. [4], [8], [13] and [14]. The remaining entries will be completed to journal style before final submission. Appendix B specifies the σ_TLE estimator completely, so the calculation can be reproduced without ref. [11], and the review package includes the implementing function. A preprint of [11] will be provided.

**m12. Declarations.** The author, affiliation, funding, CRediT and AI-use statements will be completed by the authors before formal submission. The placeholders are retained in this anonymized review version.

---

## Changes not requested by the reviewer

- **Numerical-floor artifact (M7).** It was identified and disclosed; no published value changes.
- **Rounding corrections.** The Wilson upper bound of the 45 m rule-S recall is corrected from 0.49 to 0.48 (0.4848). The cluster-bootstrap CI for the below-threshold class is [0.22, 0.48].
- **Calibration-split c.** It is the grid value 0.2818, printed as 0.28. The minimal reproduction script uses the exact grid value.
