//! 第二階段 Sprint 0 單元測試（對應 Python tests/test_phase2.py；共用 config/phase2/testdata）。

use std::path::PathBuf;

use serde_json::Value;

use super::constants::*;
use super::eop::{Eop, EopSource, EopValues, FixedEop};
use super::forces::{accel_zonal_itrf, zonal_potential, ForceModel};
use super::frames::*;
use super::integrator::{hermite5, propagate};
use super::kepler::{state as kstate, Elements};
use super::la::{norm, sub};
use super::pc::{gauss_legendre, pc_chan, pc_foster};
use super::schema::validate;
use super::tca::{brent_root, find_minima};
use super::timescale::UtcTime;

fn testdata() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("config/phase2/testdata")
}

fn vallado() -> (UtcTime, FixedEop) {
    let a = ARCSEC_TO_RAD;
    (
        UtcTime::parse("2004-04-06T07:51:28.386009Z").unwrap(),
        FixedEop(EopValues { xp_rad: -0.140682 * a, yp_rad: 0.333309 * a, ut1_utc_s: -0.4399619, lod_s: 0.0015563,
            dx_rad: -0.000205 * a, dy_rad: -0.000136 * a, dat_s: 32.0, predicted: false }),
    )
}
const R_TEME: [f64; 3] = [5094.18016210, 6127.64465050, 6380.34453270];
const V_TEME: [f64; 3] = [-4.746131487, 0.785818041, 5.531931288];

fn maxabs(a: [f64; 3], b: [f64; 3]) -> f64 {
    (0..3).map(|i| (a[i] - b[i]).abs()).fold(0.0, f64::max)
}

#[test]
fn eop_dat_matches_sofa() {
    let eop = Eop::load(&testdata().join("eop_snapshot_20261118.csv")).unwrap();
    let t = UtcTime::parse("2026-11-20T00:00:00Z").unwrap();
    assert_eq!(eop.at(t.mjd_float()).unwrap().dat_s, sofars::ts::dat(2026, 11, 20, 0.0).unwrap());
}

#[test]
fn vallado_teme_itrf_gcrf() {
    let (t, eop) = vallado();
    let er = earth_rotation(&t, &eop).unwrap();
    let (ri, vi) = teme_to_itrf(R_TEME, V_TEME, &er);
    assert!(maxabs(ri, [-1033.4793830, 7901.2952754, 6380.3565958]) < 2e-5);
    assert!(maxabs(vi, [-3.225636520, -2.872451450, 5.531924446]) < 1e-8);
    let (rg, vg) = itrf_to_gcrf(ri, vi, &er);
    assert!(maxabs(rg, [5102.508958, 6123.011401, 6378.136928]) < 2e-5);
    assert!(maxabs(vg, [-4.743220157, 0.790536497, 5.533755727]) < 1e-8);
}

#[test]
fn frame_roundtrips() {
    let (t, eop) = vallado();
    let er = earth_rotation(&t, &eop).unwrap();
    let pairs: [(StateFn, StateFn); 3] = [(gcrf_to_itrf, itrf_to_gcrf), (teme_to_gcrf, gcrf_to_teme), (teme_to_itrf, itrf_to_teme)];
    for (f, g) in pairs {
        let (r1, v1) = f(R_TEME, V_TEME, &er);
        let (r2, v2) = g(r1, v1, &er);
        assert!(maxabs(r2, R_TEME) < 1e-9 && maxabs(v2, V_TEME) < 1e-12);
    }
}

#[test]
fn c2t_matches_sofa_c2t06a() {
    let (t, FixedEop(mut ev)) = vallado();
    ev.dx_rad = 0.0;
    ev.dy_rad = 0.0;
    let er = earth_rotation(&t, &FixedEop(ev)).unwrap();
    let (tt1, tt2) = t.tt_jd(32.0);
    let (u1, u2) = t.ut1_jd(ev.ut1_utc_s);
    let m = sofars::pnp::c2t06a(tt1, tt2, u1, u2, ev.xp_rad, ev.yp_rad);
    let mine = er.m_gcrf_to_itrf();
    for i in 0..3 {
        assert!(maxabs(m[i], mine[i]) < 1e-11);
    }
}

#[test]
fn zonal_accel_is_gradient() {
    for r in [[6878.0, 120.0, 900.0], [4000.0, -3000.0, 4500.0]] {
        let h = 1e-3;
        let a = accel_zonal_itrf(r);
        for k in 0..3 {
            let (mut p, mut m) = (r, r);
            p[k] += h;
            m[k] -= h;
            let g = (zonal_potential(p) - zonal_potential(m)) / (2.0 * h);
            assert!((a[k] - g).abs() < 1e-9 * norm(a));
        }
    }
}

#[test]
fn hermite5_exact_on_quintic() {
    let c = [1.0, 0.3, 2.0, -1.0, 0.5, 0.1];
    let p = |t: f64| (0..6).map(|k| c[k] * t.powi(k as i32)).sum::<f64>();
    let dp = |t: f64| (1..6).map(|k| k as f64 * c[k] * t.powi(k as i32 - 1)).sum::<f64>();
    let ddp = |t: f64| (2..6).map(|k| (k * (k - 1)) as f64 * c[k] * t.powi(k as i32 - 2)).sum::<f64>();
    let h = 2.0;
    let s3 = |x: f64| [x, 0.0, 0.0];
    for s in [0.0, 0.3, 0.77, 1.0] {
        let (x, dx, ddx) = hermite5(s3(p(0.0)), s3(dp(0.0)), s3(ddp(0.0)), s3(p(h)), s3(dp(h)), s3(ddp(h)), h, s);
        assert!((x[0] - p(s * h)).abs() < 1e-12 && (dx[0] - dp(s * h)).abs() < 1e-12 && (ddx[0] - ddp(s * h)).abs() < 1e-11);
    }
}

#[test]
fn rk4_two_body_matches_kepler() {
    let el = Elements { a_km: 6878.137, e: 0.001, i_rad: 0.9, raan_rad: 0.3, argp_rad: 0.2, m0_rad: 0.1 };
    let (r0, v0, _) = kstate(&el, 0.0);
    let tr = propagate(r0, v0, 0.0, 86400.0, 10.0, &ForceModel::new(false, false, 0.0), None);
    assert!(norm(sub(tr.r[tr.n() - 1], kstate(&el, 86400.0).0)) < 1e-3);
}

#[test]
fn tca_matches_analytic() {
    let d = std::f64::consts::PI / 180.0;
    let e1 = Elements { a_km: 6878.137, e: 0.0005, i_rad: 51.6 * d, raan_rad: 0.5, argp_rad: 0.0, m0_rad: 0.0 };
    let e2 = Elements { a_km: 6878.537, e: 0.0005, i_rad: 97.4 * d, raan_rad: 0.5, argp_rad: 0.0, m0_rad: 0.001 };
    let g = |t: f64| {
        let (r1, v1, _) = kstate(&e1, t);
        let (r2, v2, _) = kstate(&e2, t);
        super::la::dot(sub(r2, r1), sub(v2, v1))
    };
    let dist = |t: f64| norm(sub(kstate(&e2, t).0, kstate(&e1, t).0));
    let mut roots = vec![];
    let mut t = 0.0;
    while t < 3.0 * 3600.0 {
        let (ga, gb) = (g(t), g(t + 5.0));
        if ga < 0.0 && 0.0 <= gb {
            roots.push(brent_root(&g, t, t + 5.0, ga, gb, 1e-10));
        }
        t += 5.0;
    }
    let exp = roots.iter().cloned().min_by(|a, b| dist(*a).total_cmp(&dist(*b))).unwrap();
    let fm = ForceModel::new(false, false, 0.0);
    let (r1, v1, _) = kstate(&e1, 0.0);
    let (r2, v2, _) = kstate(&e2, 0.0);
    let p = propagate(r1, v1, 0.0, 3.0 * 3600.0, 10.0, &fm, None);
    let s = propagate(r2, v2, 0.0, 3.0 * 3600.0, 10.0, &fm, None);
    let rel = |t: f64| {
        let (a, b, c) = p.state(t);
        let (x, y, z) = s.state(t);
        (sub(x, a), sub(y, b), sub(z, c))
    };
    let res = find_minima(&rel, 0.0, 3.0 * 3600.0, 10.0, None);
    let got = res.global_min().unwrap();
    assert!((got.tau - exp).abs() < 1e-3, "TCA 誤差 {}", got.tau - exp);
    assert!((got.miss_km - dist(exp)).abs() < 1e-3);
}

#[test]
fn pc_consistency() {
    let (x, w) = gauss_legendre(32);
    assert!((w.iter().sum::<f64>() - 2.0).abs() < 1e-14);
    assert!((x.iter().zip(&w).map(|(xi, wi)| wi * xi.powi(10)).sum::<f64>() - 2.0 / 11.0).abs() < 1e-14);
    let c2 = [[0.05, -0.03], [-0.03, 1.0]];
    for d in [0.0, 0.1, 0.3] {
        let f = pc_foster([d, 0.0], &c2, 0.01).unwrap();
        let c = pc_chan([d, 0.0], &c2, 0.01).unwrap();
        assert!((c / f - 1.0).abs() < 1e-3);
    }
}

fn apply_ops(base: &Value, ops: &Value) -> Value {
    let mut d = base.clone();
    for op in ops.as_array().unwrap() {
        let path = op["path"].as_array().unwrap();
        let (head, last) = path.split_at(path.len() - 1);
        let mut tgt = &mut d;
        for k in head {
            tgt = if let Some(s) = k.as_str() { tgt.get_mut(s).unwrap() } else { tgt.get_mut(k.as_u64().unwrap() as usize).unwrap() };
        }
        let set = op["op"] == "set";
        if let Some(s) = last[0].as_str() {
            let m = tgt.as_object_mut().unwrap();
            if set { m.insert(s.into(), op["value"].clone()); } else { m.remove(s); }
        } else {
            let a = tgt.as_array_mut().unwrap();
            let i = last[0].as_u64().unwrap() as usize;
            if set { a[i] = op["value"].clone(); } else { a.remove(i); }
        }
    }
    d
}

#[test]
fn schema_cases_match_expected() {
    let spec: Value = serde_json::from_str(&std::fs::read_to_string(testdata().join("schema_cases.json")).unwrap()).unwrap();
    let base: Value = serde_json::from_str(&std::fs::read_to_string(testdata().join(spec["base"].as_str().unwrap())).unwrap()).unwrap();
    for c in spec["cases"].as_array().unwrap() {
        let got = validate(&apply_ops(&base, &c["ops"])).codes;
        let mut exp: Vec<String> = c["expected_codes"].as_array().unwrap().iter().map(|x| x.as_str().unwrap().to_string()).collect();
        exp.sort();
        assert_eq!(got, exp, "{}", c["name"]);
    }
}

#[test]
fn e2e_matches_python_expected() {
    let sc: Value = serde_json::from_str(&std::fs::read_to_string(testdata().join("e2e_leo_synthetic.json")).unwrap()).unwrap();
    let exp: Value = serde_json::from_str(&std::fs::read_to_string(testdata().join("e2e_leo_synthetic.expected.json")).unwrap()).unwrap();
    let eop = Eop::load(&testdata().join("eop_snapshot_20261118.csv")).unwrap();
    let rep = super::e2e::run(&sc, &eop).unwrap();
    assert_eq!(rep["status"], "ok");
    let best = |r: &Value| r["events"].as_array().unwrap().iter()
        .min_by(|a, b| a["miss_km"].as_f64().unwrap().total_cmp(&b["miss_km"].as_f64().unwrap())).unwrap().clone();
    let (g, e) = (best(&rep), best(&exp));
    assert!((g["tca_tau_s"].as_f64().unwrap() - e["tca_tau_s"].as_f64().unwrap()).abs() < 1e-3);
    assert!((g["miss_km"].as_f64().unwrap() - e["miss_km"].as_f64().unwrap()).abs() < 1e-6);
    assert!((g["pc"]["foster"].as_f64().unwrap() / e["pc"]["foster"].as_f64().unwrap() - 1.0).abs() < 1e-6);
    assert_eq!(g["applicability"]["status"], e["applicability"]["status"]);
    assert_eq!(rep["events"].as_array().unwrap().len(), exp["events"].as_array().unwrap().len());
}
