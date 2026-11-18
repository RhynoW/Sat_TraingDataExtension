//! 第二階段 Sprint 1 單元測試（對應 Python tests/test_phase2_sprint1.py；共用 config/phase2/testdata）。

use std::path::PathBuf;

use serde_json::Value;

use super::batch::{prepare_request, run_batch};
use super::covprop::{m6_from, CovarianceTrack};
use super::csvio::{events_to_csv, parse_secondaries};
use super::eop::Eop;
use super::ephemeris::{Ephemeris, NumericalEphemeris, RelativeState, Sgp4Ephemeris};
use super::forces::ForceModel;
use super::frames::EarthRotationTable;
use super::integrator::propagate;
use super::kepler::{state as kstate, Elements};
use super::la::{norm, scale, sub};
use super::tca::{find_minima, find_minima_adaptive, AdaptiveParams, Approach};
use super::timescale::UtcTime;

fn testdata() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("config/phase2/testdata")
}
fn load(name: &str) -> Value {
    serde_json::from_str(&std::fs::read_to_string(testdata().join(name)).unwrap()).unwrap()
}
fn eop() -> Eop {
    Eop::load(&testdata().join("eop_snapshot_20261118.csv")).unwrap()
}
fn start() -> UtcTime {
    UtcTime::parse("2026-11-18T00:00:00Z").unwrap()
}
fn tle(n: &str) -> (String, String) {
    let t = &load("tle_fixture.json")["tles"][n];
    (t["line1"].as_str().unwrap().into(), t["line2"].as_str().unwrap().into())
}
fn interior(v: &[Approach]) -> Vec<Approach> {
    v.iter().filter(|a| a.flag == "interior").cloned().collect()
}
fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[test]
fn adaptive_matches_brute_force_on_real_tles() {
    let eop = eop();
    let dur = 6.0 * 3600.0;
    let ert = EarthRotationTable::new(start(), -1.0, dur + 1.0, &eop).unwrap();
    for (a, b, thr) in [("25544", "48274", 2000.0), ("59103", "68762", 1000.0)] {
        let (pa, pb) = (tle(a), tle(b));
        let p = Sgp4Ephemeris::new(&pa.0, &pa.1, start(), &ert, (0.0, dur)).unwrap();
        let s = Sgp4Ephemeris::new(&pb.0, &pb.1, start(), &ert, (0.0, dur)).unwrap();
        let rel = RelativeState::new(&p, &s);
        let refr = interior(&find_minima(&|t| rel.rva(t), 0.0, dur, 1.0, Some(thr)).events);
        let got = interior(&find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), 0.0, dur,
            AdaptiveParams { coarse_step: 60.0, threshold_km: Some(thr), ..Default::default() }).events);
        assert!(!refr.is_empty() && refr.len() == got.len(), "{a}×{b}: {} vs {}", refr.len(), got.len());
        for (x, y) in refr.iter().zip(&got) {
            assert!((x.tau - y.tau).abs() < 1e-3 && (x.miss_km - y.miss_km).abs() < 1e-6);
        }
    }
}

#[test]
fn adaptive_with_huge_coarse_step_still_complete() {
    let d = std::f64::consts::PI / 180.0;
    let e1 = Elements { a_km: 6878.137, e: 0.0005, i_rad: 51.6 * d, raan_rad: 0.5, argp_rad: 0.0, m0_rad: 0.0 };
    let e2 = Elements { a_km: 6878.537, e: 0.0005, i_rad: 97.4 * d, raan_rad: 0.5, argp_rad: 0.0, m0_rad: 0.001 };
    let rva = |t: f64| {
        let (r1, v1, a1) = kstate(&e1, t);
        let (r2, v2, a2) = kstate(&e2, t);
        (sub(r2, r1), sub(v2, v1), sub(a2, a1))
    };
    let rv = |t: f64| {
        let (r, v, _) = rva(t);
        (r, v)
    };
    let (dur, thr) = (86400.0, 3000.0);
    let refr = interior(&find_minima(&rva, 0.0, dur, 1.0, Some(thr)).events);
    let got = interior(&find_minima_adaptive(&rv, &rva, 0.0, dur,
        AdaptiveParams { coarse_step: 900.0, threshold_km: Some(thr), ..Default::default() }).events);
    let r3 = |v: &[Approach]| v.iter().map(|a| (a.tau * 1000.0).round() as i64).collect::<Vec<_>>();
    assert!(!refr.is_empty());
    assert_eq!(r3(&refr), r3(&got));
}

#[test]
fn low_relative_velocity_flag_on_docked_pair() {
    let eop = eop();
    let dur = 3.0 * 3600.0;
    let ert = EarthRotationTable::new(start(), -1.0, dur + 1.0, &eop).unwrap();
    let (pa, pb) = (tle("69673"), tle("67689"));
    let p = Sgp4Ephemeris::new(&pa.0, &pa.1, start(), &ert, (0.0, dur)).unwrap();
    let s = Sgp4Ephemeris::new(&pb.0, &pb.1, start(), &ert, (0.0, dur)).unwrap();
    let rel = RelativeState::new(&p, &s);
    let res = find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), 0.0, dur,
        AdaptiveParams { coarse_step: 60.0, threshold_km: Some(100.0), ..Default::default() });
    assert!(!res.events.is_empty());
    for a in &res.events {
        assert!(["low_relative_velocity", "window_edge_start", "window_edge_end", "degenerate"].contains(&a.flag.as_str()), "{}", a.flag);
    }
}

#[test]
fn sgp4_ephemeris_acceleration_is_consistent() {
    let eop = eop();
    let dur = 3600.0;
    let ert = EarthRotationTable::new(start(), -1.0, dur + 1.0, &eop).unwrap();
    let t = tle("25544");
    let e = Sgp4Ephemeris::new(&t.0, &t.1, start(), &ert, (0.0, dur)).unwrap();
    let (r, _v, a) = e.rva(1000.0);
    let a2b = scale(r, -398600.4418 / norm(r).powi(3));
    assert!(norm(sub(a, a2b)) / norm(a2b) < 3e-3);
}

#[test]
fn covariance_track_matches_finite_difference_stm() {
    let eop = eop();
    let dur = 3.0 * 3600.0;
    let ert = EarthRotationTable::new(start(), -1.0, dur + 1.0, &eop).unwrap();
    let el = Elements { a_km: 6878.137, e: 0.001, i_rad: 0.9, raan_rad: 0.3, argp_rad: 0.2, m0_rad: 0.1 };
    let (r0, v0, _) = kstate(&el, 0.0);
    let x0 = [r0[0], r0[1], r0[2], v0[0], v0[1], v0[2]];
    let fm = ForceModel::new(true, false, 0.0);
    let nom = NumericalEphemeris::new(propagate(r0, v0, 0.0, dur, 10.0, &fm, Some(&ert)));
    let diag = [0.05f64.powi(2), 0.2f64.powi(2), 0.05f64.powi(2), 1e-8, 1e-8, 1e-8];
    let mut p0 = vec![vec![0.0; 6]; 6];
    for i in 0..6 {
        p0[i][i] = diag[i];
    }
    let trk = CovarianceTrack::new(&nom, m6_from(&p0), 0.0, dur, 20.0, Some(&ert), true, 0.0);
    let deltas = [1e-3, 1e-3, 1e-3, 1e-6, 1e-6, 1e-6];
    let mut phi = vec![vec![0.0; 6]; 6];
    for k in 0..6 {
        let (mut xp, mut xm) = (x0, x0);
        xp[k] += deltas[k];
        xm[k] -= deltas[k];
        let tp = propagate([xp[0], xp[1], xp[2]], [xp[3], xp[4], xp[5]], 0.0, dur, 10.0, &fm, Some(&ert));
        let tm = propagate([xm[0], xm[1], xm[2]], [xm[3], xm[4], xm[5]], 0.0, dur, 10.0, &fm, Some(&ert));
        let n = tp.n() - 1;
        for i in 0..3 {
            phi[i][k] = (tp.r[n][i] - tm.r[n][i]) / (2.0 * deltas[k]);
            phi[i + 3][k] = (tp.v[n][i] - tm.v[n][i]) / (2.0 * deltas[k]);
        }
    }
    let refm = super::la::matmul(&super::la::matmul(&phi, &p0), &super::la::mat_t(&phi));
    let got = trk.at(dur).unwrap();
    let scale_ = (0..3).flat_map(|i| (0..3).map(move |j| (i, j))).map(|(i, j)| refm[i][j].abs()).fold(0.0, f64::max);
    for i in 0..3 {
        for j in 0..3 {
            assert!((got[i][j] - refm[i][j]).abs() < 1e-4 * scale_, "P[{i}][{j}] {} vs {}", got[i][j], refm[i][j]);
        }
    }
    let mid: Vec<Vec<f64>> = trk.at(5000.0).unwrap().iter().map(|r| r.to_vec()).collect();
    assert!(super::la::is_pd(&mid));
}

#[test]
fn csv_parse_matches_expected() {
    let text = std::fs::read_to_string(testdata().join("batch_secondaries.csv")).unwrap();
    let exp = load("batch_secondaries.expected.json");
    let res = parse_secondaries(&text);
    assert_eq!(res["rows"], exp["rows"]);
    let codes: Vec<Value> = res["errors"].as_array().unwrap().iter().map(|e| serde_json::json!([e["line"], e["code"]])).collect();
    assert_eq!(Value::Array(codes), exp["error_codes"]);
    assert_eq!(parse_secondaries("")["errors"][0]["code"], "CSV_EMPTY");
    assert_eq!(parse_secondaries("name\nfoo\n")["errors"][0]["code"], "CSV_NO_ID_COLUMN");
}

#[test]
fn schema_cases_count() {
    assert_eq!(load("schema_cases.json")["cases"].as_array().unwrap().len(), 37);
}

fn check_events(got: &[Value], exp: &[Value], what: &str) {
    assert_eq!(got.len(), exp.len(), "{what}：事件數");
    for (g, e) in got.iter().zip(exp) {
        assert!((f(&g["tca_tau_s"]) - f(&e["tca_tau_s"])).abs() <= 1e-3, "{what}：TCA");
        assert!((f(&g["miss_km"]) - f(&e["miss_km"])).abs() <= 1e-6, "{what}：miss");
        assert_eq!(g["tca_utc"], e["tca_utc"], "{what}：tca_utc");
        assert_eq!(g["applicability"]["status"], e["applicability"]["status"], "{what}：適用性");
        for k in ["foster", "chan"] {
            let (a, b) = (&g["pc"][k], &e["pc"][k]);
            if let (Some(a), Some(b)) = (a.as_f64(), b.as_f64()) {
                let rel = if b == 0.0 { a.abs() } else { (a / b - 1.0).abs() };
                assert!(rel <= 1e-6, "{what}：Pc {k} {a} vs {b}");
            } else {
                assert_eq!(a, b, "{what}：Pc {k}");
            }
        }
    }
}

#[test]
fn e2e_matches_python_expected_all() {
    let eop = eop();
    for name in ["e2e_leo_synthetic", "e2e_leo_propagated", "e2e_tle_iss_css"] {
        let sc = load(&format!("{name}.json"));
        let exp = load(&format!("{name}.expected.json"));
        let rep = super::e2e::run(&sc, &eop).unwrap();
        assert_eq!(rep["status"], "ok", "{name}");
        check_events(rep["events"].as_array().unwrap(), exp["events"].as_array().unwrap(), name);
        assert_eq!(rep["search"]["n_minima"], exp["search"]["n_minima"], "{name}");
        assert_eq!(rep["search"]["n_refined_intervals"], exp["search"]["n_refined_intervals"], "{name}");
        assert_eq!(rep["start"], exp["start"]);
        assert_eq!(rep["provenance"]["ephemeris"], exp["provenance"]["ephemeris"], "{name}");
        assert_eq!(rep["provenance"]["covariance"], exp["provenance"]["covariance"], "{name}");
        let (sg, se) = (rep["series"]["d_km"].as_array().unwrap(), exp["series"]["d_km"].as_array().unwrap());
        assert_eq!(sg.len(), se.len());
        assert!(sg.iter().zip(se).all(|(a, b)| (f(a) - f(b)).abs() < 1e-6));
    }
}

#[test]
fn batch_matches_python_expected() {
    let eop = eop();
    let fx = load("tle_fixture.json");
    let lookup = |n: i64| fx["tles"].get(n.to_string()).map(|t| (
        t["name"].as_str().unwrap().to_string(), t["line1"].as_str().unwrap().to_string(), t["line2"].as_str().unwrap().to_string()));
    let (req, _) = prepare_request(&load("batch_iss.request.json")).unwrap();
    let rep = run_batch(&req, &eop, &lookup).unwrap();
    let exp = load("batch_iss.expected.json");
    assert_eq!(rep["status"], "ok");
    let (gp, ep) = (rep["pairs"].as_array().unwrap(), exp["pairs"].as_array().unwrap());
    assert_eq!(gp.len(), ep.len());
    for (g, e) in gp.iter().zip(ep) {
        for k in ["secondary_norad", "input_line", "secondary_name", "status", "n_events", "n_minima"] {
            assert_eq!(g.get(k), e.get(k), "pair {k}");
        }
        if g["status"] == "ok" {
            check_events(g["events"].as_array().unwrap(), e["events"].as_array().unwrap(), "batch");
            assert!((f(&g["global_min"]["miss_km"]) - f(&e["global_min"]["miss_km"])).abs() < 1e-6);
        }
    }
    check_events(rep["events"].as_array().unwrap(), exp["events"].as_array().unwrap(), "batch flat");
    for k in ["primary", "defaults", "search"] {
        assert_eq!(rep[k], exp[k], "{k}");
    }
    let css = gp.iter().find(|p| p["secondary_norad"] == 48274).unwrap();
    assert!((f(&css["events"][0]["miss_km"]) - 45.91).abs() < 0.05);
    let text = events_to_csv(rep["events"].as_array().unwrap());
    assert!(text.lines().next().unwrap().starts_with("primary_norad,secondary_norad"));
    assert_eq!(text.lines().count(), rep["events"].as_array().unwrap().len() + 1);
    let bad = run_batch(&serde_json::json!({"primary": {"norad_id": 25544}, "secondaries": [], "start": "2026-11-18T00:00:00Z",
        "duration_s": 8.0 * 86400.0, "threshold_km": 10.0}), &eop, &lookup).unwrap();
    assert_eq!(bad["status"], "error");
}
