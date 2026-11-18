//! 第二階段 Sprint 3：RPO 控制模擬（對應 Python tests/test_phase2_sprint3.py：L7 驗收案例、故障注入、基準回歸、
//! HCW STM 性質、受迫解對數值積分、rtn_offset 往返、執行誤差情境、e2e 接受 rtn_offset）。

use std::collections::{BTreeSet, HashMap};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use serde_json::Value;

use super::apply_ops;
use super::constants::GM_KM3_S2;
use super::eop::Eop;
use super::kepler::{state as kstate, Elements};
use super::la::{dot, norm};
use super::rpo::{hcw_forced, hcw_stm, hcw_target, perturbations, run, S6};
use super::rtn::{relative_rtn, rtn_offset_to_gcrf};

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

fn cases() -> Vec<Value> {
    load("rpo_cases.json")["cases"].as_array().unwrap().clone()
}

/// 同一案例只算一次（測試平行執行時共用）
fn report(name: &str) -> Value {
    static CACHE: OnceLock<Mutex<HashMap<String, Value>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(v) = cache.lock().unwrap().get(name) {
        return v.clone();
    }
    let c = cases().into_iter().find(|c| c["name"] == name).unwrap();
    let rep = run(&apply_ops(&load("rpo_vbar.json"), &c["ops"]), &eop()).unwrap();
    cache.lock().unwrap().insert(name.to_string(), rep.clone());
    rep
}

#[test]
fn l7_rpo_cases() {
    let list = cases();
    assert_eq!(list.len(), 8);
    for c in &list {
        let name = c["name"].as_str().unwrap();
        let (rep, exp) = (report(name), &c["expected"]);
        assert_eq!(rep["status"], exp["status"], "{name}：status");
        assert_eq!(rep.get("reasons").cloned().unwrap_or(Value::Null), exp["reasons"], "{name}：reasons");
        assert_eq!(rep.get("reason").cloned().unwrap_or(Value::Null), exp["reason"], "{name}：reason");
        if rep.get("replay").is_some() {
            let types: BTreeSet<String> = rep["replay"]["violations"].as_array().unwrap().iter()
                .map(|v| v["type"].as_str().unwrap().to_string()).collect();
            let et: Vec<String> = exp["violation_types"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
            assert_eq!(types.into_iter().collect::<Vec<_>>(), et, "{name}：violation_types");
            assert_eq!(rep["replay"]["burns"].as_array().unwrap().len() as u64, exp["n_burns"].as_u64().unwrap(), "{name}：n_burns");
            let (a, b) = (f(&rep["replay"]["total_dv_ms"]), f(&exp["total_dv_ms"]));
            assert!((a - b).abs() <= 1e-9 * b.abs(), "{name}：total_dv_ms {a} vs {b}");
            assert_eq!(rep["checks"], exp["checks"], "{name}：checks");
        }
        if rep["status"] == "pass" {
            let ko = f(&rep["limits"]["keep_out_m"]);
            assert!(rep["replay"]["violations"].as_array().unwrap().is_empty());
            assert!(f(&rep["replay"]["min_dist_m"]) >= ko);
            assert!(rep["abort"]["entries"].as_array().unwrap().iter().all(|e| f(&e["nl_worst_m"]) >= ko));
        }
    }
}

#[test]
fn fault_injection_details() {
    let rep = report("fault_comm_loss");
    let fo = &rep["fault"];
    let ko = f(&rep["limits"]["keep_out_m"]);
    assert_eq!(fo["status"], "evaluated");
    assert_eq!(fo["safe"], true);
    assert!((f(&fo["trigger_t_s"]) - (f(&fo["comm_loss_start_s"]) + f(&rep["limits"]["comm_loss"]["trigger_s"]))).abs() < 1e-9);
    assert!(f(&fo["stored_entry_t_s"]) <= f(&fo["comm_loss_start_s"]));
    let mins = fo["nl_min_dist_m"].as_array().unwrap();
    assert_eq!(mins.len(), 5);
    assert!(mins.iter().all(|m| f(m) >= ko));
    assert!(f(&fo["coast_min_dist_m"]) >= ko);
    assert!(!fo["abort_path_rtn_m"].as_array().unwrap().is_empty());
}

#[test]
fn base_regression_and_structure() {
    let (rep, exp) = (report("base_nominal"), load("rpo_vbar.expected.json"));
    let (rb, eb) = (rep["replay"]["burns"].as_array().unwrap(), exp["replay"]["burns"].as_array().unwrap());
    assert_eq!(rb.iter().map(|b| b["kind"].clone()).collect::<Vec<_>>(), eb.iter().map(|b| b["kind"].clone()).collect::<Vec<_>>());
    for (a, b) in rb.iter().zip(eb) {
        assert_eq!(f(&a["t_s"]), f(&b["t_s"]));
        for i in 0..3 {
            let (x, y) = (f(&a["dv_rtn_ms"][i]), f(&b["dv_rtn_ms"][i]));
            // Python 同語言回歸用 rtol 1e-9、atol 1e-12；跨語言（erfa／sofars、BLAS 加總順序）實測最大差 2.2e-10 m/s
            assert!((x - y).abs() <= 1e-9 + 1e-9 * y.abs(), "dv_rtn_ms {x} vs {y}");
        }
    }
    let (re, ee) = (rep["abort"]["entries"].as_array().unwrap(), exp["abort"]["entries"].as_array().unwrap());
    assert_eq!(re.iter().map(|e| f(&e["t_s"])).collect::<Vec<_>>(), ee.iter().map(|e| f(&e["t_s"])).collect::<Vec<_>>());
    for (a, b) in re.iter().zip(ee) {
        for i in 0..3 {
            assert!((f(&a["dv_rtn_ms"][i]) - f(&b["dv_rtn_ms"][i])).abs() <= 1e-12);
        }
        let (x, y) = (f(&a["nl_worst_m"]), f(&b["nl_worst_m"]));
        assert!((x - y).abs() <= 1e-8 * y.abs(), "nl_worst_m {x} vs {y}");
    }
    // 每個控制段起點都有預存撤離脈衝
    let et: Vec<f64> = re.iter().map(|e| f(&e["t_s"])).collect();
    for s in rep["replay"]["segments"].as_array().unwrap() {
        assert!(et.contains(&f(&s["start_s"])));
    }
    // HCW 設計：轉移到達誤差為 0；非線性重播有模型誤差
    for s in rep["design"]["segments"].as_array().unwrap() {
        if s["type"] == "transfer" {
            assert!(f(&s["arrival_error_m"]) < 1e-6);
        }
    }
    let mx = rep["replay"]["segments"].as_array().unwrap().iter()
        .map(|s| s.get("arrival_error_m").map(f).unwrap_or(0.0)).fold(0.0, f64::max);
    assert!(mx > 1.0);
    assert_eq!(rep["applicability"]["hcw_applicable"], true);
}

fn mm6(a: &S6, b: &S6) -> S6 {
    let mut c = [[0.0; 6]; 6];
    for i in 0..6 {
        for j in 0..6 {
            c[i][j] = (0..6).map(|k| a[i][k] * b[k][j]).sum();
        }
    }
    c
}
fn mv6(a: &S6, x: [f64; 6]) -> [f64; 6] {
    let mut y = [0.0; 6];
    for i in 0..6 {
        y[i] = (0..6).map(|k| a[i][k] * x[k]).sum();
    }
    y
}

#[test]
fn hcw_stm_properties() {
    let n = (GM_KM3_S2 / 6778.137f64.powi(3)).sqrt();
    let (p1, p2, p3) = (hcw_stm(n, 700.0), hcw_stm(n, 1300.0), hcw_stm(n, 2000.0));
    let c = mm6(&p2, &p1);
    for i in 0..6 {
        for j in 0..6 {
            assert!((c[i][j] - p3[i][j]).abs() < 1e-9 + 1e-8 * p3[i][j].abs());
        }
    }
    // V-bar 點為平衡點；2:1 自然橢圓一圈後回到原點
    let x = [0.0, -1000.0, 0.0, 0.0, 0.0, 0.0];
    let y = mv6(&hcw_stm(n, 3000.0), x);
    assert!((0..6).all(|i| (y[i] - x[i]).abs() < 1e-8 + 1e-5 * x[i].abs()));
    let y0 = -1000.0;
    let x = [0.0, y0, 0.0, n * y0 / 2.0, 0.0, 0.0];
    let y = mv6(&hcw_stm(n, 2.0 * std::f64::consts::PI / n), x);
    assert!((0..6).all(|i| (y[i] - x[i]).abs() < 1e-6 + 1e-5 * x[i].abs()));
    // 雙脈衝瞄準到達目標點
    let v0 = hcw_target([0.0, -2000.0, 0.0], [0.0, -1000.0, 0.0], n, 2400.0, 0).unwrap();
    let y = mv6(&hcw_stm(n, 2400.0), [0.0, -2000.0, 0.0, v0[0], v0[1], v0[2]]);
    assert!(y[0].abs() < 1e-6 && (y[1] + 1000.0).abs() < 1e-6 && y[2].abs() < 1e-6);
    // 接近整數週期 → transfer_singular
    let e = hcw_target([0.0, -2000.0, 0.0], [0.0, -1000.0, 0.0], n, 2.0 * std::f64::consts::PI / n, 3).unwrap_err();
    assert_eq!((e.code, e.segment), ("transfer_singular", 3));
}

#[test]
fn hcw_forced_matches_numeric() {
    let n = (GM_KM3_S2 / 6778.137f64.powi(3)).sqrt();
    let a = [1e-6, -3e-6, 2e-6];
    let fx = |s: [f64; 6]| -> [f64; 6] {
        [s[3], s[4], s[5], 3.0 * n * n * s[0] + 2.0 * n * s[4] + a[0], -2.0 * n * s[3] + a[1], -n * n * s[2] + a[2]]
    };
    let ax = |x: [f64; 6], k: [f64; 6], c: f64| -> [f64; 6] { std::array::from_fn(|i| x[i] + c * k[i]) };
    let (h, mut x) = (1.0, [0.0; 6]);
    for _ in 0..3000 {
        let k1 = fx(x);
        let k2 = fx(ax(x, k1, 0.5 * h));
        let k3 = fx(ax(x, k2, 0.5 * h));
        let k4 = fx(ax(x, k3, h));
        x = std::array::from_fn(|i| x[i] + h / 6.0 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]));
    }
    let p = hcw_forced(n, 3000.0, a);
    for i in 0..3 {
        assert!((p[i] - x[i]).abs() <= 1e-8 + 1e-8 * x[i].abs(), "{i}: {} vs {}", p[i], x[i]);
    }
}

#[test]
fn rtn_offset_roundtrip() {
    let (r, v, _) = kstate(&Elements { a_km: 6778.137, e: 0.001, i_rad: 51.6f64.to_radians(), raan_rad: 0.3, argp_rad: 0.2, m0_rad: 0.1 }, 0.0);
    let (rc, vc) = rtn_offset_to_gcrf(r, v, [10.0, -500.0, 30.0], [0.1, -0.2, 0.05]);
    let (rho, rhod) = relative_rtn(r, v, rc, vc);
    let (er, ev) = ([10.0, -500.0, 30.0], [0.1, -0.2, 0.05]);
    for i in 0..3 {
        assert!((rho[i] - er[i]).abs() < 1e-9 + 1e-5 * er[i].abs());
        assert!((rhod[i] - ev[i]).abs() < 1e-9 + 1e-5 * ev[i].abs());
    }
}

#[test]
fn abort_perturbations() {
    let cs = perturbations([0.0, 0.1, 0.0], 0.05, 2.0);
    assert_eq!(cs.iter().map(|c| c.0).collect::<Vec<_>>(), ["nominal", "mag_plus", "mag_minus", "point_1", "point_2"]);
    let mags: Vec<f64> = cs.iter().map(|c| norm(c.1)).collect();
    assert!((mags[1] - 0.115).abs() < 1e-12 && (mags[2] - 0.085).abs() < 1e-12);
    assert!((mags[3] - 0.1).abs() < 1e-12 && (mags[4] - 0.1).abs() < 1e-12);
    let ang = (dot(cs[3].1, [0.0, 0.1, 0.0]) / 0.01).acos().to_degrees();
    assert!((ang - 6.0).abs() < 1e-9);
}

#[test]
fn e2e_accepts_rtn_offset() {
    let rep = super::e2e::run(&load("rpo_vbar.json"), &eop()).unwrap();
    assert_eq!(rep["status"], "ok");
    assert!((f(&rep["series"]["d_km"][0]) - 5.0).abs() < 1e-6);
}

#[test]
fn schema_rpo_and_rtn_offset_role() {
    use super::schema::validate;
    let sc = load("rpo_vbar.json");
    assert!(validate(&sc).ok);
    // rtn_offset 用於主星 → E_RTN_OFFSET_ROLE
    let mut bad = sc.clone();
    let tmp = bad["objects"][0]["role"].clone();
    bad["objects"][0]["role"] = bad["objects"][1]["role"].clone();
    bad["objects"][1]["role"] = tmp;
    assert_eq!(validate(&bad).codes, vec!["E_RTN_OFFSET_ROLE"]);
    // 段落型別錯誤、label 過長、rpo_limits 未知欄位 → E_SCHEMA
    for (path, val) in [
        (vec!["rpo", "sequence"], serde_json::json!([{"type": "dock", "duration_s": 10.0}])),
        (vec!["rpo_limits", "nope"], serde_json::json!(1)),
        (vec!["rpo", "sequence"], serde_json::json!([{"type": "hold", "duration_s": 10.0, "label": "x".repeat(41)}])),
        (vec!["rpo", "sequence"], serde_json::json!([])),
    ] {
        let mut d = sc.clone();
        let mut t = &mut d;
        for k in &path[..path.len() - 1] {
            t = t.get_mut(*k).unwrap();
        }
        t[*path.last().unwrap()] = val;
        assert_eq!(validate(&d).codes, vec!["E_SCHEMA"], "{path:?}");
    }
    // 缺 rpo → E_RPO_MISSING
    let mut d = sc.clone();
    d.as_object_mut().unwrap().remove("rpo");
    assert_eq!(run(&d, &eop()).unwrap()["validation"]["codes"], serde_json::json!(["E_RPO_MISSING"]));
}
