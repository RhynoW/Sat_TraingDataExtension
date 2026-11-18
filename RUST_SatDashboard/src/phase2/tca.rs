//! 近接極小值搜尋（與 Python tca.py 相同：節點掃描 g = r·v 由負轉正 → Brent 求根 → dg/dτ > 0 確認）。

use super::constants::BRENT_XTOL_S;
use super::la::{dot, norm};
use super::V3;

/// Brent（1973）zeroin；與 Python brent_root 逐步相同
pub fn brent_root(f: &dyn Fn(f64) -> f64, a0: f64, b0: f64, fa0: f64, fb0: f64, xtol: f64) -> f64 {
    let (mut a, mut b, mut fa, mut fb) = (a0, b0, fa0, fb0);
    if fa == 0.0 {
        return a;
    }
    if fb == 0.0 {
        return b;
    }
    let (mut c, mut fc) = (a, fa);
    let mut d = b - a;
    let mut e = d;
    for _ in 0..200 {
        if (fb > 0.0) == (fc > 0.0) {
            c = a;
            fc = fa;
            d = b - a;
            e = d;
        }
        if fc.abs() < fb.abs() {
            let (ob, oc) = (b, c);
            let (ofb, ofc) = (fb, fc);
            a = ob;
            b = oc;
            c = ob;
            fa = ofb;
            fb = ofc;
            fc = ofb;
        }
        let tol = 2.0 * f64::EPSILON * b.abs() + 0.5 * xtol;
        let m = 0.5 * (c - b);
        if m.abs() <= tol || fb == 0.0 {
            return b;
        }
        if e.abs() >= tol && fa.abs() > fb.abs() {
            let s = fb / fa;
            let (mut p, mut q);
            if a == c {
                p = 2.0 * m * s;
                q = 1.0 - s;
            } else {
                let q_ = fa / fc;
                let r_ = fb / fc;
                p = s * (2.0 * m * q_ * (q_ - r_) - (b - a) * (r_ - 1.0));
                q = (q_ - 1.0) * (r_ - 1.0) * (s - 1.0);
            }
            if p > 0.0 {
                q = -q;
            } else {
                p = -p;
            }
            if 2.0 * p < (3.0 * m * q - (tol * q).abs()).min((e * q).abs()) {
                e = d;
                d = p / q;
            } else {
                d = m;
                e = m;
            }
        } else {
            d = m;
            e = m;
        }
        a = b;
        fa = fb;
        b += if d.abs() > tol { d } else if m > 0.0 { tol } else { -tol };
        fb = f(b);
    }
    b
}

#[derive(Clone, Debug)]
pub struct Approach {
    pub tau: f64,
    pub miss_km: f64,
    pub r_rel: V3,
    pub v_rel: V3,
    pub a_rel: V3,
    pub dgdt: f64,
    pub flag: String,
}

pub struct SearchResult {
    pub events: Vec<Approach>,
    pub all_minima: Vec<Approach>,
    pub step: f64,
    pub threshold_km: Option<f64>,
}

impl SearchResult {
    pub fn global_min(&self) -> Option<&Approach> {
        self.all_minima.iter().min_by(|a, b| a.miss_km.total_cmp(&b.miss_km))
    }
    pub fn resolution(&self) -> serde_json::Value {
        serde_json::json!({"node_step_s": self.step, "threshold_km": self.threshold_km, "root_xtol_s": BRENT_XTOL_S,
                           "note": "節點間距內的多重極小值不保證辨識"})
    }
}

fn approach(rel: &dyn Fn(f64) -> (V3, V3, V3), tau: f64, flag: &str) -> Approach {
    let (r, v, a) = rel(tau);
    Approach { tau, miss_km: norm(r), r_rel: r, v_rel: v, a_rel: a, dgdt: dot(v, v) + dot(r, a), flag: flag.to_string() }
}

pub fn find_minima(rel: &dyn Fn(f64) -> (V3, V3, V3), t0: f64, t1: f64, step: f64, threshold_km: Option<f64>) -> SearchResult {
    let n = ((t1 - t0) / step).round() as usize;
    let mut taus: Vec<f64> = (0..=n).map(|k| t0 + k as f64 * step).collect();
    taus[n] = t1;
    let g = |tau: f64| {
        let (r, v, _) = rel(tau);
        dot(r, v)
    };
    let gn: Vec<f64> = taus.iter().map(|&t| g(t)).collect();
    let mut found = Vec::new();
    if gn[0] > 0.0 {
        found.push(approach(rel, taus[0], "window_edge_start"));
    }
    for k in 0..n {
        if gn[k] < 0.0 && 0.0 <= gn[k + 1] {
            let root = brent_root(&g, taus[k], taus[k + 1], gn[k], gn[k + 1], BRENT_XTOL_S);
            found.push(approach(rel, root, "interior"));
        }
    }
    if gn[n] < 0.0 {
        found.push(approach(rel, taus[n], "window_edge_end"));
    }
    for ap in found.iter_mut() {
        if ap.flag == "interior" && !(ap.dgdt > 0.0) {
            ap.flag = "degenerate".into();
        }
    }
    let events = found.iter().filter(|a| threshold_km.map_or(true, |t| a.miss_km <= t)).cloned().collect();
    SearchResult { events, all_minima: found, step, threshold_km }
}
