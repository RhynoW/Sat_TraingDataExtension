//! 二維 Pc 適用性啟發式篩選（與 Python screening.py 相同的三態與指標）。

use serde_json::{json, Map, Value};

use super::constants::*;
use super::la::{add, norm, scale, sub};
use super::pc::{eig2, project};
use super::{M3, V3};

fn is_pd3(c: &M3) -> bool {
    let v: Vec<Vec<f64>> = c.iter().map(|r| r.to_vec()).collect();
    super::la::is_pd(&v)
}

pub fn screen(
    rel: &dyn Fn(f64) -> (V3, V3, V3),
    tca_tau: f64,
    c3_at: Option<&dyn Fn(f64) -> M3>,
    cov_mode: &str,
    hbr_km: f64,
    period_s: f64,
    other_minima_tau: &[f64],
    span: (f64, f64),
) -> Value {
    let thresholds = json!({"k_sigma": SCREEN_K_SIGMA, "tenc_max_frac_period": SCREEN_TENC_MAX_FRAC_PERIOD,
        "lin_max_frac": SCREEN_LIN_MAX_FRAC, "cov_det_max_rel": SCREEN_COV_DET_MAX_REL,
        "cov_axis_max_rel": SCREEN_COV_AXIS_MAX_REL, "cov_rot_max_deg": SCREEN_COV_ROT_MAX_DEG});
    let mut metrics = Map::new();
    let undetermined = |reason: &str, metrics: Map<String, Value>| {
        json!({"status": "undetermined", "reasons": [reason], "metrics": metrics, "thresholds": thresholds,
               "note": "待驗證的啟發式篩選，非二維方法有效性的證明"})
    };
    let Some(c3f) = c3_at else { return undetermined("missing_covariance", metrics) };
    let c3 = c3f(tca_tau);
    if !is_pd3(&c3) {
        return undetermined("covariance_not_positive_definite", metrics);
    }
    let (r0, v0, _) = rel(tca_tau);
    let vn = norm(v0);
    if !(vn > 0.0) {
        return undetermined("zero_relative_velocity", metrics);
    }
    let z = scale(v0, 1.0 / vn);
    let mut zcz = 0.0;
    for a in 0..3 {
        for b in 0..3 {
            zcz += z[a] * c3[a][b] * z[b];
        }
    }
    let sigma_v = zcz.sqrt();
    let t_enc = 2.0 * SCREEN_K_SIGMA * sigma_v / vn;
    let (lo, hi) = (tca_tau - 0.5 * t_enc, tca_tau + 0.5 * t_enc);
    if lo < span.0 || hi > span.1 {
        metrics.insert("t_enc_s".into(), json!(t_enc));
        return undetermined("encounter_window_exceeds_ephemeris", metrics);
    }
    let n = 21;
    let mut dev: f64 = 0.0;
    for i in 0..n {
        let tau = lo + (hi - lo) * i as f64 / (n - 1) as f64;
        let (r, _, _) = rel(tau);
        dev = dev.max(norm(sub(r, add(r0, scale(v0, tau - tca_tau)))));
    }
    let (_m2, c2, _f) = project(r0, v0, &c3);
    let (l1, l2, _th0) = eig2(&c2);
    let lin_ref = hbr_km + l2.max(0.0).sqrt();
    for (k, v) in [("t_enc_s", t_enc), ("period_s", period_s), ("t_enc_frac_period", t_enc / period_s),
                   ("sigma_v_km", sigma_v), ("delta_lin_km", dev), ("delta_lin_ref_km", lin_ref)] {
        metrics.insert(k.into(), json!(v));
    }
    let mut fails: Vec<&str> = Vec::new();
    if t_enc / period_s >= SCREEN_TENC_MAX_FRAC_PERIOD {
        fails.push("encounter_too_long");
    }
    if dev >= SCREEN_LIN_MAX_FRAC * lin_ref {
        fails.push("relative_motion_not_rectilinear");
    }
    if cov_mode == "propagated" {
        let b_cov = |tau: f64| {
            let (r_, v_, _) = rel(tau);
            project(r_, v_, &c3f(tau)).1
        };
        let (ca, cb) = (b_cov(lo), b_cov(hi));
        let (la1, la2, tha) = eig2(&ca);
        let (lb1, lb2, thb) = eig2(&cb);
        let det_rel = (la1 * la2 - lb1 * lb2).abs() / (l1 * l2);
        let ax_rel = ((la1.sqrt() - lb1.sqrt()).abs() / l1.sqrt()).max((la2.sqrt() - lb2.sqrt()).abs() / l2.sqrt());
        let mut rot = (tha - thb).sin().atan2((tha - thb).cos()).to_degrees().abs();
        rot = rot.min(180.0 - rot);
        metrics.insert("cov_det_rel_change".into(), json!(det_rel));
        metrics.insert("cov_axis_rel_change".into(), json!(ax_rel));
        metrics.insert("cov_rot_deg".into(), json!(rot));
        if det_rel >= SCREEN_COV_DET_MAX_REL || ax_rel >= SCREEN_COV_AXIS_MAX_REL || rot >= SCREEN_COV_ROT_MAX_DEG {
            fails.push("covariance_changes_during_encounter");
        }
    } else {
        metrics.insert("covariance_note".into(), json!("展示模式：協方差假設在交會期間不變，未檢查協方差變化"));
    }
    if other_minima_tau.iter().any(|&t| (t - tca_tau).abs() > 1e-9 && lo <= t && t <= hi) {
        fails.push("multiple_approaches_in_window");
    }
    json!({"status": if fails.is_empty() { "passes_initial_screen" } else { "fails_initial_screen" },
           "reasons": fails, "metrics": metrics, "thresholds": thresholds,
           "note": "待驗證的啟發式篩選，非二維方法有效性的證明"})
}
