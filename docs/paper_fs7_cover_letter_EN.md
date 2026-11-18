[Date]

The Editor-in-Chief
*Advances in Space Research*

Dear Editor,

We submit the manuscript "An Empirical Sensitivity Model for Maneuver Detection from Public Two-Line Elements: Calibration Against Precise Orbit Determination Truth" for consideration as a research article in *Advances in Space Research*.

Public Two-Line Elements (TLEs) are the main data source for maneuver screening of non-cooperative satellites, yet the smallest maneuver they can reveal has rarely been measured against an independent orbit truth. This manuscript uses the publicly distributed FORMOSAT-7/COSMIC-2 precise orbit product as that truth and reports three results:

1. An event-level baseline against 131 verified maneuvers: recall rises from 0.11 for 1–50 m steps to 0.82 for 1–3 km steps, and a May 2024 storm interval produces 21 drag-driven non-thrust signatures that pass persistence and cross-arc consistency checks.
2. Controlled injections into real TLE series (15,774 trials, cluster-bootstrap inference) show the 90% detection amplitude growing from 50 m to 500 m across update cadence and drag regimes.
3. A drag-aware effective signal-to-noise relation improves temporally held-out predictive performance over an amplitude-only model (log loss 0.124 versus 0.141), with all held-out results computed from parameters fixed on the calibration period.

The results bear directly on the frequent inference that "no maneuver was seen in TLEs, therefore none occurred", and on threshold selection for operational screening. We state the scope explicitly: the relation is detector-level, calibrated on one constellation, and its coefficients are parameterization-dependent.

The manuscript is original, has not been published, and is not under consideration elsewhere. A companion manuscript on TLE semi-major-axis noise floors (reference 11) is in preparation; the two papers do not overlap in data analysis, and the companion work is cited only for the noise estimator and the altitude-dependent noise fit shown as contextual Fig. S3. All authors have approved the submission and declare no competing interests. [To be confirmed.]

Precise-orbit data are public; TLE data are retrieved under the Space-Track user agreement and are not redistributed, but the code release reconstructs the data set from the published NORAD identifiers and epoch lists.

Suggested reviewers (optional): [Name, affiliation, e-mail, expertise] ×3 [To be completed.]

Thank you for your consideration.

Sincerely,

[Corresponding author name]
[Affiliation, address]
[E-mail]
