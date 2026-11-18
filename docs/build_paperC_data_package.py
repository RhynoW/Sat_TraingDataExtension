#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_paperC_data_package.py — 論文 C 之 Zenodo 資料封存包（衍生資料，不含原始 TLE）。

輸出：output/paper_C_submission/data_package/（CSV／CSV.GZ＋README.md＋MANIFEST.csv）
只讀既有結果檔，不重算、不覆寫任何來源檔。
"""
from __future__ import annotations

import gzip
import hashlib
import shutil
import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "data" / "benchmark"
OUT = ROOT / "output" / "paper_C_submission" / "data_package"

# (輸出檔名, 來源, 來源程式, 說明, {欄位: 說明}, 處理)
FILES = [
    ("S01_perigee_bin_selection.csv", "perigee_bin_selection_x30.csv", "docs/select_perigee_bins.py",
     "425 satellites selected in 15 perigee bins (300–1000 km, 50-km step) from the 2026-11 element sets.",
     {"bin": "perigee bin (km)", "norad_id": "NORAD catalogue number", "object_name": "catalogue name",
      "perigee_km/apogee_km": "perigee/apogee altitude at selection (km, rounded 0.1)", "e": "eccentricity", "inc": "inclination (deg)",
      "n_tle": "number of element sets in the last 120 days", "decay_m_per_day": "mean SMA change rate over the last 120 days (m/day, negative = decay)",
      "max_up_km": "largest positive SMA jump in the last 120 days (km)", "tol_km": "bin tolerance used (5/10/20 km)"},
     "drop_bstar_epoch"),
    ("S02_perigee_windows_7day.csv.gz", "perigee_drag_corr_windows_x30.csv.gz", "docs/analyze_perigee_drag_corr.py (TAG=x30)",
     "55,879 seven-day windows of the 425 satellites: TLE-observed and NRLMSIS-expected decay rates.",
     {"w": "window start (UTC, 7-day floor)", "days": "summed transition span in window (days)", "maxdt": "longest transition (days)",
      "maxres": "largest |drag residual| of a transition (km)", "da/pred/res": "summed observed / expected / residual ΔSMA (km)",
      "alt": "mean perigee altitude (km)", "obs_decay/nrl_decay": "observed / NRLMSIS-expected decay rate (m/day, positive = decay)",
      "res_rate": "residual rate (m/day)", "norad_id": "NORAD number", "bin": "selection bin (km)",
      "passive": "True if no adjacent-TLE ΔSMA > +0.3 km in the period", "alt_bin": "window altitude rounded to 50 km"}, "copy"),
    ("S03_perigee_persat.csv", "perigee_drag_corr_persat_x30.csv", "docs/analyze_perigee_drag_corr.py (TAG=x30)",
     "Per-satellite statistics (Table 1, Table 2, Fig. 2).",
     {"r_pearson/rho_spearman": "temporal correlation of observed vs expected 7-day decay", "res_rms": "residual RMS (m/day)",
      "res_rel": "res_rms / median expected decay", "B_eff": "calibrated effective ballistic coefficient (internal units of atmospheric_drag.py)",
      "n_up03_all": "number of adjacent-TLE ΔSMA > +0.3 km", "passive_all": "passive throughout", "first_tle": "first element set used"}, "copy"),
    ("S04_perigee_bins.csv", "perigee_drag_corr_bins_x30.csv", "docs/analyze_perigee_drag_corr.py (TAG=x30)",
     "Per-bin statistics (Table 2). obs_decay_med/nrl_decay_med are medians over all 7-day windows of the bin.", {}, "copy"),
    ("S05_perigee_global.csv", "perigee_drag_corr_global_x30.csv", "docs/analyze_perigee_drag_corr.py (TAG=x30)", "Global correlations (Table 1).", {}, "copy"),
    ("S06_nrlmsis_decay_expect.csv", "nrlmsis_decay_expect.csv", "docs/gen_fig_nrlmsis_decay_expect.py",
     "Daily NRLMSIS 2.1 expected decay rate for B = 0.022 m²/kg at 300–1000 km and F10.7 (Fig. 1).",
     {"<h>km_m_per_day": "expected SMA decay rate at altitude h (m/day)", "f107/f107_81": "F10.7 observed / 81-day centred mean (sfu)"}, "copy"),
    ("S07_solar_tracking_bands.csv", "nrlmsis_solar_tracking_bands_x30.csv", "docs/gen_fig_nrlmsis_solar_tracking.py (TAG=x30)",
     "Altitude-band temporal correlations of the 270 passive satellites (Table 3).", {}, "copy"),
    ("S08_fs7_precise_windows.csv", "fs7_precise_decay_windows.csv", "docs/gen_fig_fs7_precise_nrlmsis.py",
     "616 manoeuvre-free 7-day windows of FORMOSAT-7 FM1/2/4/5/6: precise-orbit, NRLMSIS and TLE decay rates (Table 4, Fig. 4).",
     {"w": "window start", "decay": "precise-orbit decay rate (m/day)", "alt": "mean altitude (km)", "shape": "NRLMSIS shape term ρ√(μa)·86400 per unit B",
      "nrl": "NRLMSIS expected decay (m/day, per-satellite B)", "tle": "TLE decay rate over the same window (m/day)", "sat/name": "SP3 ID / satellite"}, "copy"),
    ("S09_fs7_precise_corr.csv", "fs7_precise_nrlmsis_corr.csv", "docs/gen_fig_fs7_precise_nrlmsis.py", "Per-satellite FORMOSAT-7 statistics (Table 4).", {}, "copy"),
    ("S10_fs7_daily_precise_sma.csv.gz", "fs7_daily_sma_cache", "docs/gen_fig_fs7_precise_nrlmsis.py (day_mean)",
     "Daily median of the one-orbit-smoothed precise SMA (TACC leoOrb), FM1/2/4/5/6.",
     {"date": "UTC date", "sp3_sat": "SP3 ID (L76=FM1, L77=FM2, L79=FM4, L80=FM5, L81=FM6)", "a_km": "SMA (km)", "n_min": "minutes of coverage"},
     "concat_daily"),
    ("S11_threshold_transitions.csv.gz", "perigee_drag_cache_x30", "atmospheric_drag.py via docs/analyze_perigee_drag_corr.py",
     "877,567 adjacent-TLE transitions (≤ 3 days) of the 309 passive satellites used in the threshold study (§2.8, §3.5).",
     {"norad_id": "NORAD number", "epoch": "epoch of the later element set (UTC)", "dt_d": "transition span (days)",
      "alt_km": "perigee altitude (km)", "drag_pred_da": "NRLMSIS-expected ΔSMA (km)", "drag_resid_da": "drag residual = observed − expected ΔSMA (km)"},
     "transitions"),
    ("S12_threshold_by_altitude.csv", "drag_thr_by_alt_x30.csv", "docs/study_drag_resid_threshold.py", "Table 5 (in-sample).", {}, "copy"),
    ("S13_threshold_summary.csv", "drag_thr_summary_x30.csv", "docs/study_drag_resid_threshold.py", "Threshold-study summary and scheme-C coefficients.", {}, "copy"),
    ("S14_threshold_oos_bins.csv", "paperC_thr_oos_bins_20261118.csv", "docs/paperC_numbers.py oos",
     "Out-of-sample false-alarm rate and 90% detection floor by scheme (A–E), evaluation design and altitude bin.",
     {"eval": "sat-5fold / sat-2fold (satellite-grouped CV, 20 repeats) or time split", "scheme": "A fixed 0.30 km; B per-bin lookup; C log-linear; D monotone envelope; E isotonic",
      "hbin": "altitude bin (−1 = all)", "fp_med/fp_p05/fp_p95": "false alarms per 1,000 satellite-days (median, 5th, 95th pct over repeats)",
      "share_meet": "share of repeats with fp ≤ 0.43", "min90_med": "90% detection floor (km)", "sd_train": "training satellite-days",
      "evaluable": "train and test satellite-days ≥ 1000/0.43", "fp_train": "in-training false-alarm rate (time split only)"}, "copy"),
    ("S15_threshold_oos_summary.csv", "paperC_thr_oos_summary_20261118.csv", "docs/paperC_numbers.py oos", "Summary of S14.", {}, "copy"),
    ("S16_threshold_oos_thresholds.csv", "paperC_thr_oos_thresholds_20261118.csv", "docs/paperC_numbers.py oos", "Trained thresholds (median over folds/repeats).", {}, "copy"),
    ("S17_threshold_event_satellites.csv", "paperC_thr_event_sats_20261118.csv", "docs/paperC_numbers.py thr", "In-sample false-alarm events by satellite.", {}, "copy"),
    ("S18_fs7_pooled_corr.csv", "paperC_fs7_pooled_20261118.csv", "docs/paperC_numbers.py fs7pool", "Pooled FORMOSAT-7 correlations with 95% CIs.", {}, "copy"),
    ("S19_bias_by_f107.csv", "paperC_bias_by_f107_20261118.csv", "docs/paperC_numbers.py bias", "NRLMSIS/observed decay ratio by F10.7 81-day group.", {}, "copy"),
    ("S20_f107_lag.csv", "paperC_f107lag_20261118.csv", "docs/paperC_numbers.py f107lag", "F10.7 same-day vs previous-day sensitivity.", {}, "copy"),
    ("S21_fs73.csv", "paperC_fs73_20261118.csv", "docs/paperC_numbers.py fs73", "FORMOSAT7-3 precise-orbit windows and TLE free-decay windows.", {}, "copy"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    man = []
    for name, src, prog, desc, cols, how in FILES:
        dst = OUT / name
        p = BM / src
        if how == "copy":
            if not p.exists():
                print("缺", src)
                continue
            shutil.copyfile(p, dst)
        elif how == "drop_bstar_epoch":
            d = pd.read_csv(p).drop(columns=["bstar", "epoch_utc"], errors="ignore")
            d.to_csv(dst, index=False, encoding="utf-8")
        elif how == "concat_daily":
            d = pd.concat([pd.read_csv(f) for f in sorted(p.glob("*.csv")) if f.stat().st_size > 30])
            d = d.groupby(["sp3_sat", "date"], as_index=False).agg(a_km=("a_km", "median"), n_min=("n_min", "max"))
            d.to_csv(dst, index=False, compression="gzip")
        elif how == "transitions":
            P = pd.read_csv(BM / "perigee_drag_corr_persat_x30.csv")
            parts = []
            for nid in P[P.passive_all].norad_id:
                f = p / f"{nid}.csv.gz"
                if f.exists():
                    r = pd.read_csv(f, usecols=["epoch", "dt_d", "alt_km", "drag_pred_da", "drag_resid_da"])
                    r = r[(r.dt_d > 0) & (r.dt_d <= 3)]
                    r = r[((r.alt_km / 50).round() * 50).between(300, 1000)]
                    r.insert(0, "norad_id", nid)
                    parts.append(r)
            pd.concat(parts).to_csv(dst, index=False, compression="gzip", float_format="%.6g")
        h = hashlib.md5(dst.read_bytes()).hexdigest()
        n = sum(1 for _ in (gzip.open(dst, "rt", encoding="utf-8") if name.endswith(".gz") else open(dst, encoding="utf-8-sig"))) - 1
        man.append({"file": name, "rows": n, "bytes": dst.stat().st_size, "md5": h, "source": f"data/benchmark/{src}", "program": prog})
        print(name, n)
    M = pd.DataFrame(man)
    M.to_csv(OUT / "MANIFEST.csv", index=False, encoding="utf-8")
    lines = ["# Data package: Validating NRLMSIS 2.1 orbital-decay predictions with passive LEO satellites and FORMOSAT-7 precise orbits", "",
             "Derived data needed to reproduce the tables and figures of the manuscript. **Raw Space-Track TLEs are not included** "
             "(the Space-Track user agreement does not permit redistribution); they can be retrieved by registered users with the "
             "NORAD numbers in S01 for 2024-01-01 to 2026-11-15. FORMOSAT-7 leoOrb precise orbits are public from TACC (https://tacc.cwa.gov.tw); "
             "space-weather indices are from CelesTrak (SW-All.csv: F10.7_OBS, F10.7_OBS_CENTER81, AP1–AP8).", "",
             "Software: NRLMSIS 2.1 via pymsis 0.13.0; SGP4 (python-sgp4); analysis scripts listed per file (repository paths). "
             "Units: km, m/day, UTC. Random seeds: threshold study 20261116, out-of-sample validation 20261118.", "",
             "Note for the author: S02, S03, S08 (column `tle`), S11 and S21 contain quantities derived from TLE (SMA changes, decay rates). "
             "These are derived products, but please confirm against the current Space-Track terms before public release.", "",
             "## Files", "", "| File | Rows | Content | Source program |", "|---|--:|---|---|"]
    rows = {m["file"]: m for m in man}
    for name, src, prog, desc, cols, how in FILES:
        if name in rows:
            lines.append(f"| `{name}` | {rows[name]['rows']:,} | {desc} | `{prog}` |")
    lines += ["", "## Column descriptions", ""]
    for name, src, prog, desc, cols, how in FILES:
        if name in rows and cols:
            lines.append(f"### {name}")
            lines += [f"- `{k}`: {v}" for k, v in cols.items()]
            lines.append("")
    lines += ["Files without a column list use the same column names as the corresponding repository output; see MANIFEST.csv for checksums.", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("→", OUT)


if __name__ == "__main__":
    main()
