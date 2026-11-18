# Response to Reviewers — Revision R1

**Manuscript:** *Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits* (formerly *An Empirical Sensitivity Model for Maneuver Detection from Public Two-Line Elements: Calibration Against Precise Orbit Determination Truth*)

We thank the reviewer for a careful and constructive report. We have addressed every major and minor comment. Several of the requested diagnostics changed our interpretation, and we report those changes openly below.

All new numbers come from one script, `fs7_review5_analysis.py`, which writes `fs7_review5_analysis.json`. New supplementary sections S11–S16 (Tables S28–S35 and Fig. S5) are generated from that file by `docs/gen_fs7_supplement_r1.py`. Section and table numbers refer to the revised manuscript.

## Summary of substantive changes

1. **The title, abstract and contributions are rescoped to detector-level sensitivity** (M1). The paper now distinguishes four meanings of "sensitivity" explicitly (§1).
2. **The empirical 90% injection amplitude is now interpolated and has confidence intervals** (M6). The range across conditions changes from 50–500 m (grid floor) to 41–476 m (interpolated, with 95% CIs) (§4.1, Table 4a).
3. **A rule asymmetry in the real-event threshold comparison was found and removed** (M7). In the original submission, real-event true positives required a sign match, whereas pseudo-event false positives did not. Both samples are now evaluated under a sign-constrained rule and under a sign-free rule (§5.4, Table 5). The conclusion that a σ_TLE-based threshold is operationally unacceptable holds under both rules.
4. **The gap between injection and real-event sensitivity is now decomposed quantitatively** (M5). The decomposition shows that the bin-level agreement between model and real-event recall reported in the original Table 4 arose partly from two opposing biases that cancel. We no longer present that agreement as validation of the model (§5.3, §5.5, Table 6, Conclusion).
5. **The pseudo-event draw tabulated in the original submission is replaced by a reproducible draw** (n = 1,145). The original draw (n = 1,131) depended on the state of the TLE archive at the time and cannot be regenerated from the current archive. The pooled FPRs are essentially unchanged (§5.4; Section S9).

---

## Major comments

### M1. Distinguish "sensitivity" from "detectability"

**Response.** Agreed.

- **Title:** now *Detector-Level Sensitivity of Maneuver Detection from Public Two-Line Elements: An Empirical Model Calibrated Against FORMOSAT-7 Precise Orbits*.
- **Abstract:** states that the 41–476 m range is an injection-recall amplitude for the specified detector, and that these values are "upper bounds for the specified detector, not general TLE detection limits."
- **§1:** the final paragraph now names four distinct quantities and the section in which each appears: the empirical injection amplitude (§4.1), the model-implied amplitude (§4.4), real-event recall conditional on coverage (§5.3), and end-to-end sensitivity, which the paper does not measure.

### M2. Selection bias in the 131-to-96 reduction

**Response.** We added a quantitative analysis (§2.6, Table 2b; Section S11, Table S28).

- **Exclusion reasons and timing.** Of the 35 excluded events, 34 fail the pre-event coverage condition (fewer than three TLEs in the 3 days before the event) and one fails the post-event condition. The median time from the last TLE to the event start is 17.0 h for excluded events and 7.3 h for included events. The time from the event end to the next TLE is similar in both groups (10.4 h versus 10.6 h). Exclusion is therefore driven by sparse TLE updates before the event.
- **Comparison of included and excluded events.** Exclusion depends strongly on campaign (χ² p < 0.001) and satellite (p = 0.001), but not detectably on amplitude (Mann–Whitney p = 0.84). These tests were already in Table S5.
- **Inverse-probability weighting.** Recall weighted by 1/P(included | campaign) differs from the recall over the 96 evaluable events by at most 0.08 in every amplitude bin. A satellite × campaign weighting is not identifiable, because four of its cells contain no included event.
- **Conservative bounds for the full 131-event library (Question 3).** Counting every excluded event as a miss gives a worst-case overall recall of 0.28 at 45 m; counting every excluded event as a detection gives a best case of 0.55. The 96-event estimate is 0.39 and the IPW estimate is 0.37. In the 1–3 km bin, the bounds are 0.54–0.88.
- **Evaluable population.** We now define the "evaluable" population by the pre-specified coverage rule and use that term throughout the paper.

### M3. The common-mode check is structurally biased against coordinated maneuvers

**Response.** Agreed.

- **Scope statement.** The abstract, contribution 1, Table 2, §2.7 (a new paragraph, "Coordinated maneuvers are excluded by design"), Table 7 and limitation (viii) now state that the library contains individually verified, non-coordinated events only.
- **Justification of the check.** The check is intended to remove artifacts that appear on several satellites at once. We state explicitly that it cannot distinguish such artifacts from real coordinated burns.
- **Separate class.** No operator records or telemetry are available to validate a separate coordinated class, so this extension is listed as future work.
- **New consequence identified.** The check also has an indirect effect that we had not recognized. Rejected coordinated burns still change the orbit, so they contaminate the pre-event trend window of neighbouring verified events. Two of the three misses in the 1–3 km bin are caused by such burns (§5.5(b)).

### M4. Interpretation of c

**Response.**

- The identifiability statement now appears directly after Eq. (2), in a paragraph titled "What the coefficients mean, and what they do not." It states that c is neither a physical drag fraction, nor a density-response coefficient, nor a universal property of TLE errors.
- We now report the derived quantity c·|ȧ|·Δt, in metres (Table N; the table in §4.4; Table S29). Its median ranges from 2.0 m to 48 m across conditions and accounts for 76–90% of σ_eff².
- **Alternative parameterizations.** We fitted c separately at each cadence. The estimates are 0.32 [0.25, 0.50] at 2× and 0.28 [0.22, 0.35] at 4×. At 1×, c is *not* identified: the profile likelihood rises to the upper edge of the grid. This result also bears on the dense-cadence residual discussed under M5. Using c′·Δt as a single free scale is algebraically equivalent to the present form at fixed Δt, so it does not remove the trade-off.
- The table of estimated values now notes that individual c values are listed for completeness only.

### M5. Diagnostic treatment of the gap between injection and real-event sensitivity

**Response.** We added four targeted diagnostics (§4.4, §5.5, Table 6; Tables S31, S34 and S35). They answer Question 6 and change the interpretation of the paper.

1. **Lag-1 autocorrelation stratification, within cadence.** The 1× prediction residual is the same in all three r₁ terciles (−0.040, −0.033, −0.038). Adding r₁ as a covariate improves held-out log loss only from 0.1238 to 0.1228. Serial correlation therefore does *not* explain the dense-cadence residual, and we withdraw the earlier suggestion that it does. The more direct signature is that c is not identified at 1× (M4).
2. **Classes of missed real events.** At 45 m, the 131 events divide into 35 excluded for coverage (34 pre-event, 1 post-event), 37 detected, 43 below threshold, and 16 above threshold with the wrong sign.
3. **Multiple burns.** Events that share a TLE interval with another verified event are detected at the same rate as isolated events (0.38 versus 0.39). Pile-up of burns is therefore not a dominant loss.
4. **Pre-event trend contamination.** We flag an event as contaminated when its 3-day pre-event trend window contains an SP3 candidate of ≥ 500 m of any verdict, which happens for 39 of the 96 evaluable events. In these windows, the fitted |ȧ| reflects the campaign staircase (median 711 m/day), not drag. The contamination deflates the model probabilities (mean predicted probability 0.39 against an observed recall of 0.72). It also creates association artifacts for small events: their TLE residual is 23–44 times the SP3 step, because it reflects neighbouring burns. In clean windows, observed recall is 0.16 against a mean predicted probability of 0.59. **The bin-level agreement in Table 4 is therefore partly a cancellation of these two biases.** The −0.17 residual in the 1–3 km bin is fully explained: all three misses are wrong-sign residuals caused by km-scale burns in the pre-event window.
5. **TLE response in clean windows.** None of the 22 clean events of 50–300 m produces an immediate TLE response, 3 produce a delayed one, and 17 produce no response within 3 days. By contrast, 4 of the 5 clean events of ≥ 300 m respond immediately. For small isolated events, the gap therefore arises upstream of the detector. With the present data we cannot determine whether it comes from TLE generation or from SP3-side truth losses; several of these events are negative-going steps during orbit-raising, which makes truth losses plausible. The orbit-state-level injection experiment remains the direct test and is listed as future work, because it requires a new propagation and fitting pipeline.

**Consequences for the paper.** The abstract, a new highlight, §5 (renamed "Real-Event Results within FS7"), §5.3, limitation (ix) and the Conclusion now present the real-event comparison as descriptive and confounded rather than as validation of the model. Validation of the model rests on the temporally held-out injections and on blocked cross-validation.

### M6. Definition of the 90% recall floor

**Response.** The paper now reports two clearly named quantities (§4.1, Table 4a; Table S30).

- The **grid floor** is the smallest tested amplitude with recall ≥ 0.90. It is a descriptive grid quantity.
- The **interpolated Δa₉₀** is computed after monotonizing the recall curve with pool-adjacent-violators and interpolating linearly in log₁₀Δa between grid amplitudes. Its 95% CI comes from a cluster bootstrap (B = 2,000) that repeats the interpolation in every resample.

Recall at every grid amplitude is tabulated with cluster-bootstrap CIs (Table S30), and Table 4a lists the recall one grid step below each floor. The grid floor overstates the interpolated value by up to 1.4×. In five of nine conditions, the grid floor itself changes in at least 26% of bootstrap resamples. The amplitude grid was fixed before any results were examined and was not refined afterwards (Question 2; Box 1, §3.4).

### M7. Framing of the real-event threshold comparison

**Response.**

- **Precise definitions.** Box 1 (estimator E1) defines both thresholds exactly. They are applied to the same residual statistic, with the same windows and the same association rule.
- **Correction of the rule asymmetry.** Checking the sign constraint, as the reviewer asked, revealed that it was applied to real-event true positives but not to pseudo-event false positives. Table 5 now reports a sign-constrained rule S and a sign-free rule U, each applied identically to both samples. At 45 m, rule S gives recall 0.39 at FPR 0.026, and rule U gives recall 0.55 at FPR 0.052. At the unified 3σ threshold, rule S gives 0.47 at FPR 0.274, and rule U gives 0.75 at FPR 0.548. The order-of-magnitude increase in FPR when moving to a σ_TLE-based threshold holds under both rules.
- **Precision and false-discovery proportion.** Sample precision is now reported, with a note that it depends on prevalence.
- **Operating characteristic.** A threshold sweep with ROC curves is reported (Fig. S5, Table S33). The AUC is 0.73 [0.66, 0.80] under rule U and 0.59 [0.51, 0.67] under rule S. A post hoc Youden threshold is reported for reference only and is not used.
- **Threshold provenance (Question 7).** The 45 m threshold was carried over unchanged from our earlier conference analysis. It was not selected using the data evaluated here.

### M8. Qualification of the storm signatures as "drag-driven"

**Response.**

- **Wording.** The candidates are now called "storm-consistent, drag-attributed non-thrust candidates" throughout the paper (abstract, Tables 1 and 2, §5.1, figure captions).
- **Evidence.** §5.1 lists the four lines of evidence: sign, magnitude, timing and campaign records. It states that no thruster telemetry or operator log exists, so the attribution is not definitive (Question 4).
- **Temporal alignment.** We added a per-candidate alignment with the definitive GFZ 3-hourly Kp index and F10.7 flux (new ref. [14]; Table S32). 19 of the 21 candidates follow the main-phase onset (Kp ≥ 7 at 2024-05-10 15 UT). 19 of the 21 have Kp ≥ 5 within the preceding 24 h. The two candidates before the onset coincide with an earlier minor storm (Kp 6.7). We also found and disclosed that the project's earlier daily index file contained fill values for Kp in this period; it is no longer used.

### M9. Detector description sufficient for independent reimplementation

**Response.** A new Box 1 (§3.2) specifies both procedures:

- **Detector D1** (injections): input series, absence of resampling and smoothing, differencing lag, MAD scale formula, MAD rule, CUSUM initialization, κ = 0.5, h = 5, reset rule, union of flags, injection placement, hit tolerance and control false alarms.
- **Estimator E1** (real events): pre-event trend window, post-event test epochs, the S and U decision rules, association of closely spaced events and the definition of detection delay.

Box 1 also lists every quantity fixed in advance. Separating D1 from E1 makes clear that the model is calibrated on D1 only.

### M10. Bounds on external validity

**Response.** §7 adds a paragraph on the population of applicability and a new Table 7. The table maps each evaluated FS7 condition to what a transfer would require, which also answers Question 8 on the required number of events, truth source and calibration protocol. The statement that "public TLEs remain a meaningful screen" is now restricted to kilometre-scale, individually performed orbit changes under the stated conditions (Conclusion). The paper also states explicitly that public TLEs are not a reliable basis for asserting that small maneuvers did not occur.

---

## Minor comments

**m1. Length of the abstract.** The abstract was rewritten (about 230 words). Methodological caveats moved to §1 and §2.

**m2. Meaning of "verified".** At first use in §2.7, the term is now "SP3-consistency-verified maneuver event," and the text states that it does not mean confirmed by operator records or telemetry.

**m3. Role of inclination.** At a 4σ corroboration level, 2 of the 131 verified events and 6 of the rejected candidates show an inclination signature. No classification would change if inclination were included (§2.7; Section S14).

**m4. The one-hit-per-injection rule.** Event-level hit, flag-level hit, fragmentation and duplicate detection are now defined in the main text (§2.7, "Event accounting").

**m5. Confidence intervals for the 90% floors.** The interpolated Δa₉₀ now has cluster-bootstrap 95% CIs (Table 4a). Recall at every grid amplitude also has CIs (Table S30), and we report the bootstrap stability of each grid floor.

**m6. "Natural negative control."** §2.3 is renamed "A quiescent free-decay reference," and the text describes FS7-3 as a "no-maneuver reference under the available campaign records."

**m7. The unavailable reference [11].** A new Appendix B defines the σ_TLE estimator completely: quality-control rules, detrending, robust scale, Δt and the autocorrelation diagnostic. While preparing it we corrected an inference about autocorrelation. Positive lag-1 correlation of the differences cannot arise from AR(1) level errors; it indicates a slowly varying component that the detrending does not absorb. We will also provide a preprint of [11].

**m8. Reference formatting.** Reference [13] is complete in our source and appears to have been truncated in the reviewer's copy. We added DOIs for refs. [4], [8] and [13] and added ref. [14]. The remaining references will be checked against the journal style before resubmission.

**m9. Self-contained main text.** Key material from the supplement now appears in the main text: Table 2b (selection bias), Table 4a (empirical floors with CIs), Table 5 (symmetric threshold rules), Table 6 (decomposition of real-event outcomes) and Table 7 (transfer conditions).

**m10. False-alarm terminology.** §3.5 now defines "false-alarm rate" (flags per satellite per 30 days in control windows), "false-positive rate" (FP/(FP + TN) over pseudo-events) and "false-discovery proportion" (1 − precision). The terms are used consistently.

**m11. Notation.** A notation table (Table N) is added at the beginning of §3.

**m12. Context for the ≈18 m station-keeping figure.** §7 now states that 18 m is a *nominal* amplitude, Δa = 2aΔv/v for an assumed ΔV of 0.01 m/s. It is not an observed event and is not in the 96-event set. The statement that such steps are not reliably resolved is supported by two observations. First, injection recall at 20 m is 0.13–0.58 across conditions. Second, recall at 45 m is 0.00 for the 30 clean-window real events of 1–50 m.

**m13. Computational cost.** The Data and code availability section now reports the environment and the following wall times, all single-threaded on a laptop-class ARM64 machine without parallelization. The injection sweep is estimated at about 1 min, extrapolated from 3.6 ms per trial over 150 timed trials. The identification bootstrap with the profile grid takes 16 s, and the complete R1 analysis takes 5 s, including all of its B = 2,000 bootstraps.

**m14. AUC definitions.** §3.5 now defines the evaluation unit, positive class, treatment of ties and CI method for both uses of AUC. The trial-level held-out AUCs are 0.977 [0.974, 0.981] and 0.967 [0.962, 0.972], and the paired difference is 0.010 [0.007, 0.013], computed over 212 cluster-bootstrap clusters.

**m15. Operational takeaway.** A new Box 2 in §7 gives the decision rule with worked examples. It states that the coefficients are specific to the detector and population, and that the result is an upper bound.

---

## Answers to the reviewer's questions

1. **Distribution of the 35 excluded events.** They are listed by amplitude bin, campaign and satellite in Tables S2–S4. Their timing relative to TLE coverage is reported in §2.6 and Section S11.
2. **Were the grid and thresholds fixed in advance?** Yes. The amplitude grid, decimation factors, D1 parameters and the 45 m threshold were all fixed before any results were examined (Box 1).
3. **Recall for the full 131-event library under a conservative assumption.** The worst-case recall is 0.28 overall at 45 m and 0.54 for 1–3 km (Table 2b).
4. **Independent evidence for the storm classification.** None beyond the campaign records. The attribution is inferential and is stated as such (§5.1).
5. **Sensitivity to estimator and detector parameters.** These parameters were fixed in advance (Box 1). Their sensitivity was not varied systematically in this revision. The robustness checks reported are the ±1.0 d hit tolerance, the ramp variant, the non-overlapping-window subset and the satellite-level bootstrap. A parameter sweep of κ, h and the MAD multiplier is listed as future work.
6. **Relative contributions to the injection–real gap.** See M5, Table 6 and Tables S34–S35.
7. **Was the 45 m threshold chosen independently of the evaluation data?** Yes; it was carried over unchanged from an earlier analysis.
8. **What a transfer to another constellation would require.** See Table 7.

---

## Required revisions: checklist

| # | revision required by the reviewer | where it is addressed |
|---|---|---|
| 1 | detector-level scope | title, abstract, §1, Box 2, Conclusion |
| 2 | selection bias | §2.6, Table 2b, S11 |
| 3 | coordinated maneuvers | §2.7, Table 7, limitation (viii), §5.5(b) |
| 4 | identifiability of the coefficients | §3.3, Table N, S12 |
| 5 | decomposition of the injection–real gap | §4.4, §5.5, Table 6, S13, S16 |
| 6 | definition of the 90% floor and its uncertainty | §4.1, Table 4a, S13 |
| 7 | threshold protocol and operating characteristic | Box 1, §5.4, Table 5, S15, Fig. S5 |
| 8 | reimplementability | Box 1, Appendix B |
| 9 | conditional wording of the storm interpretation | §5.1, S14 |
| 10 | code and data availability | Data and code availability; a repository DOI will be added at acceptance (the archive is not yet public) |
