//! 第二階段 Sprint 2：避碰決策（對應 Python tests/test_phase2_sprint2.py：L6 驗收案例、基準輸出回歸、
//! 線性預篩對非線性驗證、STM 對有限差分、執行誤差協方差、小 HBR 近似 Pc）。

use std::path::PathBuf;
use std::sync::OnceLock;

use serde_json::Value;

use super::constants::MAN_G0_MS2;
use super::eop::Eop;
use super::ephemeris::NumericalEphemeris;
use super::forces::ForceModel;
use super::frames::EarthRotationTable;
use super::integrator::propagate;
use super::la::{add, norm, scale, sub};
use super::maneuver::{exec_error_cov, pc_lin, run, Stm};
use super::timescale::{seconds_between, UtcTime};
use super::apply_ops;

fn testdata() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("config/phase2/testdata")
}
fn load(name: &str) -> Value {
    serde_json::from_str(&std::fs::read_to_string(testdata().join(name)).unwrap()).unwrap()
}
fn eop() -> Eop {
    Eop::load(&testdata().join("eop_snapshot_20261118.csv")).unwrap()
}
fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn base_report() -> &'static Value {
    static R: OnceLock<Value> = OnceLock::new();
    R.get_or_init(|| run(&load("maneuver_leo.json"), &eop()).unwrap())
}

#[test]
fn l6_maneuver_cases() {
    let cases = load("maneuver_cases.json");
    let base = load(cases["base"].as_str().unwrap());
    let e = eop();
    let list = cases["cases"].as_array().unwrap();
    assert_eq!(list.len(), 10);
    for c in list {
        let name = c["name"].as_str().unwrap();
        let rep = if c["ops"].as_array().unwrap().is_empty() { base_report().clone() } else { run(&apply_ops(&base, &c["ops"]), &e).unwrap() };
        let exp = &c["expected"];
        assert_eq!(rep["status"], exp["status"], "{name}：status");
        assert_eq!(rep.get("reason").cloned().unwrap_or(Value::Null), exp["reason"], "{name}：reason");
        if exp["best"].is_null() {
            assert!(rep.get("best").map(Value::is_null).unwrap_or(true), "{name}：best 應為空");
        } else {
            let (b, eb) = (&rep["best"], &exp["best"]);
            assert!((f(&b["burn_tau_s"]) - f(&eb["burn_tau_s"])).abs() < 1e-6, "{name}：burn_tau_s");
            assert_eq!(b["direction"], eb["direction"], "{name}：direction");
            assert!((f(&b["dv_ms"]) - f(&eb["dv_ms"])).abs() < 1e-12, "{name}：dv_ms");
            assert_eq!(b["passed"], eb["passed"], "{name}：passed");
            assert_eq!(rep["searched"]["verified"], exp["verified"], "{name}：verified");
            assert_eq!(rep["searched"]["passed"], exp["passed"], "{name}：passed 數");
        }
        if rep["status"] == "feasible_solution_found" {
            let b = &rep["best"];
            let crit = &rep["criteria"];
            assert!(f(&b["event"]["miss_km"]) >= f(&crit["min_miss_km"]), "{name}");
            if crit["pc_target_used"] == true {
                assert!(f(&b["pc_after"]) <= f(&crit["pc_target"]), "{name}");
            }
            assert!(f(&b["dv_ms"]) <= f(&rep["feasibility"]["dv_search_ms"][1]) + 1e-12, "{name}");
            let w = &rep["feasibility"]["window_utc"];
            let (lo, hi) = (UtcTime::parse(w[0].as_str().unwrap()).unwrap(), UtcTime::parse(w[1].as_str().unwrap()).unwrap());
            let bt = UtcTime::parse(b["burn_utc"].as_str().unwrap()).unwrap();
            assert!(seconds_between(&lo, &bt) >= -1e-6 && seconds_between(&bt, &hi) >= -1e-6, "{name}：機動時刻在窗內");
        }
    }
}

/// 基準輸出回歸（對 Python 產生的 maneuver_leo.expected.json）。跨語言浮點累積差約 1e-9 km（1 μm）、Pc 相對 1e-9，
/// 故容差取 Python 自身回歸（1e-9 km、1e-9 相對）的 10 倍；離散結果（候選、檢查、線性圖）須完全相同。
#[test]
fn base_regression() {
    let exp = load("maneuver_leo.expected.json");
    let rep = base_report();
    assert_eq!(rep["status"], exp["status"]);
    let (ca, cb) = (rep["candidates"].as_array().unwrap(), exp["candidates"].as_array().unwrap());
    assert_eq!(ca.len(), cb.len());
    for (a, b) in ca.iter().zip(cb) {
        assert_eq!(a["burn_utc"], b["burn_utc"]);
        assert_eq!(a["direction"], b["direction"]);
        assert!((f(&a["event"]["miss_km"]) - f(&b["event"]["miss_km"])).abs() < 1e-8);
        assert!((f(&a["event"]["tca_tau_s"]) - f(&b["event"]["tca_tau_s"])).abs() < 1e-6);
        let (pa, pb) = (f(&a["pc_after"]), f(&b["pc_after"]));
        assert!((pa - pb).abs() <= 1e-12 + 1e-8 * pb.abs());
        assert_eq!(a["checks"], b["checks"]);
    }
    assert!((f(&rep["reference"]["event"]["miss_km"]) - f(&exp["reference"]["event"]["miss_km"])).abs() < 1e-8);
    let lm = |r: &Value| r["linear_map"].as_array().unwrap().iter().map(|x| x["min_dv_ms"].clone()).collect::<Vec<_>>();
    assert_eq!(lm(rep), lm(&exp));
    assert_eq!(rep["searched"], exp["searched"]);
    assert_eq!(rep["secondary_screening"], exp["secondary_screening"]);
}

#[test]
fn linear_prediction_matches_nonlinear() {
    for c in base_report()["candidates"].as_array().unwrap() {
        let (lin, act) = (f(&c["linear"]["miss_km"]), f(&c["event"]["miss_km"]));
        assert!((lin - act).abs() / act < 0.02);
    }
}

#[test]
fn reference_model_and_physics() {
    let rep = base_report();
    let (r, t) = (&rep["reference"]["event"], &rep["target"]);
    assert!((f(&r["miss_km"]) - f(&t["miss_km"])).abs() < 1e-5);
    assert!((f(&r["tca_tau_s"]) - f(&t["tca_tau_s"])).abs() < 1e-3);
    for c in rep["candidates"].as_array().unwrap() {
        assert_eq!(f(&c["delta_a_km"]) < 0.0, c["direction"] == "-T");
        assert!(f(&c["burn_rel_tca_s"]) <= -1800.0 + 1e-6);
        let exp = 260.0 * (1.0 - (-f(&c["dv_ms"]) / (220.0 * MAN_G0_MS2)).exp());
        assert!((f(&c["propellant_kg"]) - exp).abs() <= 1e-12 * exp);
        assert_eq!(c["execution_error_included"], true);
    }
    assert_eq!(rep["secondary_screening"]["n_objects"], 4);
    assert!(rep["secondary_screening"]["coverage_note"].as_str().unwrap().contains("未涵蓋完整目錄"));
    assert_eq!(rep["reference"]["model"]["force_model"]["zonal"], "J2-J4");
}

#[test]
fn stm_matches_finite_difference() {
    let e = eop();
    let start = UtcTime::parse("2026-11-20T00:00:00Z").unwrap();
    let ert = EarthRotationTable::new(start, -1.0, 7300.0, &e).unwrap();
    let fm = ForceModel::new(true, false, 0.0);
    let r0 = [215.3357059388151, 4740.941021012885, 4969.580669570353];
    let v0 = [-6.9546790172395765, -2.089713045506579, 2.2894798706190342];
    let eph = NumericalEphemeris::new(propagate(r0, v0, 0.0, 7200.0, 10.0, &fm, Some(&ert)));
    let stm = Stm::new(&eph, 0.0, 20.0, Some(&ert), true);
    let phi = stm.at(7200.0);
    let u = scale(v0, 1.0 / norm(v0));
    let dv = 1e-5;
    let rp = *propagate(r0, add(v0, scale(u, dv)), 0.0, 7200.0, 10.0, &fm, Some(&ert)).r.last().unwrap();
    let rm = *propagate(r0, sub(v0, scale(u, dv)), 0.0, 7200.0, 10.0, &fm, Some(&ert)).r.last().unwrap();
    let fd = scale(sub(rp, rm), 1.0 / (2.0 * dv));
    let lin: Vec<f64> = (0..3).map(|i| phi[i][3] * u[0] + phi[i][4] * u[1] + phi[i][5] * u[2]).collect();
    let d = sub([lin[0], lin[1], lin[2]], fd);
    assert!(norm(d) / norm(fd) < 1e-4, "STM 相對誤差 {}", norm(d) / norm(fd));
}

#[test]
fn execution_error_covariance() {
    let u = [0.0, 1.0, 0.0];
    let err: Value = serde_json::json!({"included": true, "mag_frac_sigma": 0.02, "point_deg_sigma": 1.0});
    let q = exec_error_cov(u, 1e-3, Some(&err));
    let close = |a: f64, b: f64| (a - b).abs() <= 1e-12 * b.abs();
    assert!(close(q[1][1], (0.02f64 * 1e-3).powi(2)));
    assert!(close(q[0][0], (1e-3 * 1.0f64.to_radians()).powi(2)));
    assert!(close(q[2][2], q[0][0]));
    for i in 0..3 {
        for j in 0..3 {
            assert_eq!(q[i][j], q[j][i]);
        }
    }
    let off: Value = serde_json::json!({"included": false});
    assert!(exec_error_cov(u, 1e-3, Some(&off)).iter().flatten().all(|x| *x == 0.0));
    assert!(exec_error_cov(u, 1e-3, None).iter().flatten().all(|x| *x == 0.0));
}

#[test]
fn pc_linear_approximation() {
    let c2 = [[0.04, 0.0], [0.0, 0.01]];
    let p = pc_lin([0.0, 0.0], Some(&c2), 0.01).unwrap();
    let exp = 0.01f64.powi(2) / (2.0 * (0.04f64 * 0.01).sqrt());
    assert!((p - exp).abs() <= 1e-15 * exp);
    assert!(pc_lin([1.0, 0.0], Some(&c2), 0.01).unwrap() < p);
    assert!(pc_lin([0.0, 0.0], None, 0.01).is_none());
}
