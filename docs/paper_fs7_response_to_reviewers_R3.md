# Response to Reviewers — Final Revision

**Manuscript:** *Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits*

We thank the reviewer for the recommendation to accept with minor revisions and for the careful final reading. All points have been addressed. New checks are produced by `fs7_review7_analysis.py`, which writes `fs7_review7_analysis.json`, and are reported in the main text and in the new Supplementary Section S19 (Tables S45–S48).

---

## Remaining major comments

### M1. "Most isolated sub-300 m real events show no TLE response" must not read as an established TLE-generation conclusion

**Response.** Agreed. All three suggested wording changes have been made.

- **Highlight 4** now reads "Most sub-300 m real events lack a 3-day TLE response, consistent with upstream loss."
- **Abstract** adds "the cause cannot be established with the present data."
- **§5.5(c)** now says the published TLEs "do not show a response consistent with the SP3-derived step within the evaluation window," and it closes by stating that SP3-side truth losses remain a plausible alternative that this study cannot exclude.
- **Conclusion** has the same qualification.

**Partial SP3-side check.** We checked the no-response events against overlapping SP3 arcs, as suggested (Table S46). Of the 17 no-response events, 13 are covered by two or more overlapping, independently processed arcs. Their arc-to-arc spread is a median of 0.3 m (maximum 5.3 m), and the median persistence ratio is 1.18, comparable to 1.33 for the responding events. This makes a failure confined to a single arc solution unlikely. We state explicitly that all arcs share the same processing chain and dynamical models, so this is an internal-consistency check, not independent verification. No independent precise-orbit product, optical or radar tracking, or mission record was available to us for these epochs.

**A further observation bearing on the truth-loss alternative.** Real-event recall at 45 m is 0.60 for positive-going and 0.15 for negative-going SP3 steps (§5.4, Table S48). We report this as consistent with, not as evidence of, truth losses.

### M2. More precise definition of clean and contaminated windows

**Response.**

- **Rename.** "Clean" has been renamed *large-candidate-free* throughout the main text, Tables 6 and 6a, the supplement, and the generating scripts. It is defined as "no SP3 candidate ≥ 500 m, of any verdict, in the pre-event window; it does not mean undisturbed."
- **Covariates (Table S45).** The covariates confirm the reviewer's concern: 91% of large-candidate-free events have another SP3 candidate of some size within 1 day (median separation 0.02 d, median 12 candidates within ±3 d). Large-candidate-free events have a median of 5 post-event TLEs within 3 days and a median TLE gap of 0.93 d, compared with 4 and 1.26 d for contaminated events.
- **Small-bin recall.** Table 6 now gives Wilson CIs wherever n ≥ 5. The small-amplitude large-candidate-free recalls are 0/30 = 0.00 [0.00, 0.11] for 1–50 m and 1/11 = 0.09 [0.02, 0.38] for 50–100 m, and the text calls these samples small.

### M3. The E1-based logistic analysis should not read as a model comparison

**Response.**

- §5 now calls it an "*exploratory E1-based sensitivity check*, not a model comparison or validation."
- **Folds.** There are five folds, each holding out all events of one campaign, so that events sharing TLE coverage and contamination structure never straddle training and test folds.
- **Contamination indicator.** It is computed from the SP3 candidate list alone and uses no test-fold outcome.
- **Caveats.** The text states that the figures are small-sample and unvalidated, and that they are not comparable with the injection-trial AUC. The E1 AUC is not cited in the abstract or conclusion.
- **Fig. 6.** The D1 curve, band and markers are now drawn in grey and dashed, and are labelled "D1-calibrated descriptive probability (not E1)" (see m7).
- The sentence noting that a calibrated E1 model is future work is retained.

### M4. Clearer handling of the pseudo-event sign under rule S

**Response.**

- **Table 5 caption.** It now states that the rule-S pseudo-event FP/TN are sign-mixture expectations, p₊·(positive-hypothesis counts) + (1 − p₊)·(negative-hypothesis counts) with p₊ = 0.521, not the counts of a single draw. Rule-S values are labelled "expected."
- **CIs.** The Wilson interval on a rounded expected count has been replaced by a percentile bootstrap that resamples real events (for p₊) and pseudo-events within satellite. The expected FPR is 0.026 [0.020, 0.033] at 45 m and 0.274 [0.260, 0.288] at 3σ.
- **Separate signs (§5.4; Table S48).** At 45 m, the counts are FP/TN 37/1,108 with FPR 0.032 [0.024, 0.044] under the positive hypothesis, and 22/1,123 with 0.019 [0.013, 0.029] under the negative one. At 3σ they are 313/832 (0.273) and 315/830 (0.275). Recall at 45 m is 0.60 for positive-going and 0.15 for negative-going events.

### M5. More careful integration of the √Δt result

**Response.**

- **Abstract.** It adds that "a post hoc √Δt form reduces this under-prediction but has not been confirmed on independent data."
- **§4.3.** It now explains why the form may matter physically. A √Δt scaling is expected if the inter-TLE ambiguity accumulates like a random walk, for example drag variability that the linear trend does not absorb, rather than as a deterministic rate × interval. This is consistent with the positive lag-1 correlations of Appendix B but not demonstrated.
- **Coefficients.** §4.3 reports them for the √Δt form: SNR₅₀ = 3.55, β = 5.75 and SNR₉₀ = 8.56, compared with 3.77, 5.25 and 9.87 for the linear form. It notes that the √Δt c has different units and is not comparable with the linear-form c.
- **Limitation (iv).** It states that the √Δt form should not replace the pre-specified model until it is confirmed, and that it should be the first form tested in any independent validation.

### M6. Box 2 coefficients must not be over-generalized

**Response.**

- The Box 2 title now reads "for the evaluated FS7/D1 configuration only."
- c ≈ 0.3 is described as "a descriptive-refit scale parameter jointly calibrated with SNR₅₀ and not separately interpretable."
- For conservative operation, Box 2 recommends the empirical interpolated Δa₉₀ of Table 4a, and its upper CI bound at 1× cadence.
- It states that Box 2 does not apply to coordinated burns, low-thrust maneuvers, other altitudes, other tracking densities, or other detectors.

### M7. The 18 m station-keeping figure must not read as an observation

**Response.**

- §7 now calls the value a "*nominal, hypothetical* scale." It states every conversion assumption: a purely along-track ΔV of 0.01 m/s, a = 6,928 km, v = 7,585 m/s, and the Gauss variational equation for a near-circular orbit, which give Δa = 2aΔv/v ≈ 18.3 m.
- "Support" is changed to "two empirical observations are consistent with the statement that a nominal 18 m station-keeping-scale step would not be reliably resolved."
- The 18 m figure does not appear in the abstract or conclusion.

### M8. More conservative wording for "likely real" coordinated burns

**Response.**

- §5.5(b) now reads "is consistent with, but does not establish, that some large rejected candidates are real burns."
- §5.5(b) and limitation (viii) state that the authenticity of the coordinated burns and their contribution to E1 contamination cannot be separated with the present data.
- No public mission record, operator log or telemetry was available to us.

### M9. Verifiable data, code and anonymized review package

**Response.** The anonymized review package `paperB_review_package_R2.zip` (81 files, 1.2 MB) is attached to this resubmission.

- **Manifest.** The SHA-256 of its `MANIFEST_SHA256.txt` is `8ea8f2bea8d223059427f5baf1e0232ebe5ac89f15463ca56241af5b2cf46375`. The manifest lists the SHA-256 of every packaged file.
- **Contents.** The package contains `fs7_review5_analysis.py`, `fs7_review6_analysis.py`, `fs7_review7_analysis.py` and their JSON outputs; `docs/fs7_env_freeze.txt`; and the Supplementary Material (`docs/paper_fs7_supplement_EN.md`), which includes Tables S1b, S44 and S45–S48.
- **Minimal reproduction.** `python fs7_repro_minimal.py` requires only NumPy and pandas, and no Space-Track credentials or database. It reproduces and checks the following values, and every check passes:
  - **Table 3:** calibration-split SNR₅₀ = 3.87 and β = 5.04 (at the grid value c = 0.2818); held-out log loss 0.1237 (drag-aware) and 0.1413 (amplitude-only); held-out AUC 0.9773.
  - **Table 4a:** interpolated Δa₉₀ for all nine conditions, from 40.7 m (1×·low) to 476.3 m (4×·high), within 0.15 m.
  - **Table 4:** recall at 45 m and at unified 3σ for all five bins, and the 96 evaluable events.
  - **Table 5:** recall at 45 m of 0.552 under rule U; FPR 0.052 under rule U and 0.026 under rule S.
- **What needs the raw TLE archive.** The README states this: the injection sweep, the real-event residuals, the pseudo-event draw and the detector-parameter replay. Their outputs are included, so a reviewer without Space-Track credentials can re-derive every main-text number from the derived tables, though not the TLE-level computations.

### M10. Claims must not extend beyond FS7/D1

**Response.**

- **Conclusion.** It now reads "Within the evaluated FS7/D1 conditions (§7; Table S44), public TLEs remain a meaningful screen for kilometre-scale, individually performed orbit changes." This statement is not tied to a specific operating point.
- **Abstract.** It begins its question with "for the evaluated detector and FS7-like conditions."
- **Highlight 2.** It is now prefixed with "FS7/D1."

---

## Minor comments

**m1.** Highlight 2 now reads "FS7/D1 detector-level 90% recall under TLE-equivalent injections: ~40–480 m."

**m2.** The abstract now reads "a 45 m threshold, pre-specified in a prior conference analysis." Box 1 gives the full provenance, and Table 4 labels the threshold "pre-specified, prior conference analysis."

**m3.** The Table 4 column is renamed "D1-calibrated descriptive probability, mean (not an E1 probability)."

**m4.** The five wrong-sign events outside contaminated windows are all 1–50 m steps, and two pairs share a post-event TLE. Their residuals are 229–922 m of opposite sign, 5–40 times the SP3 step. Each has another SP3 candidate within 0.5 d and 5–21 candidates within ±3 d, so their residuals are dominated by neighbouring activity below the 500 m contamination cut (§5.5(b); Table S47).

**m5.** The Table 6 caption now defines the ratio. It is the signed E1 residual (median of the first one or two post-event TLEs) divided by the signed SP3 step. It is not an absolute value, so a negative value means a residual of opposite sign, and the median is taken across events.

**m6.** §5.5(c) states the sensitivity result in the main text: 10–17 no-response events out of 22, zero immediate responses in every variant, and an immediate response for 4 of the 5 large-candidate-free events of ≥ 300 m in every variant. It also points to Table S37 for every variant.

**m7.** Fig. 6 is redrawn. The D1-calibrated curve, its σ_eff band and its bin means are now grey and dashed, with the label "(not E1)." The caption describes them as de-emphasized and states that the panel is not a goodness-of-fit test. The storm-candidate legend now reads "drag-attributed," consistent with §5.1.

**m8.** §1 now reads "abundant maneuver-like events over a wide amplitude range that can be screened against independent precise-orbit solutions."

**m9.** The author, affiliation, corresponding-author, funding, CRediT and AI-use statements will be completed by the authors before formal submission. Placeholders are retained in this anonymized version.

**m10.** Appendix B specifies the σ_TLE estimator completely, and the review package contains its implementing function (`window_stats` in `fs7_injection_sweep.py`). A preprint of reference [11] will be provided. The remaining references will be completed to journal style, with DOIs, volumes and pages, before final submission.
