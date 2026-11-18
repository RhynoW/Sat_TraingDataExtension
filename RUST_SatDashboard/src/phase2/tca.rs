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

// ── 自適應近接極小值搜尋（Sprint 1；與 Python find_minima_adaptive 逐步相同） ──────────────

use super::constants::{
    SEARCH_ACCEL_BOUND_KM_S2, SEARCH_COARSE_STEP_S, SEARCH_LOW_VREL_KM_S, SEARCH_MIN_STEP_S, SEARCH_OMEGA_MAX_RAD_S,
    SEARCH_PERT_ACCEL_KM_S2, SEARCH_SUBDIVIDE, SEARCH_TIDAL_COEF_S2,
};

/// 距離的一維黃金分割極小化（低相對速度時與 g 求根互相確認）
pub fn golden_min(f: &dyn Fn(f64) -> f64, a0: f64, b0: f64, tol: f64, maxiter: usize) -> f64 {
    let gr = (5.0f64.sqrt() - 1.0) / 2.0;
    let (mut a, mut b) = (a0, b0);
    let (mut c, mut d) = (b - gr * (b - a), a + gr * (b - a));
    let (mut fc, mut fd) = (f(c), f(d));
    for _ in 0..maxiter {
        if (b - a).abs() <= tol {
            break;
        }
        if fc < fd {
            b = d;
            d = c;
            fd = fc;
            c = b - gr * (b - a);
            fc = f(c);
        } else {
            a = c;
            c = d;
            fc = fd;
            d = a + gr * (b - a);
            fd = f(d);
        }
    }
    0.5 * (a + b)
}

pub struct AdaptiveParams {
    pub coarse_step: f64,
    pub threshold_km: Option<f64>,
    pub min_step: f64,
    pub accel_bound: f64,
}

impl Default for AdaptiveParams {
    fn default() -> Self {
        AdaptiveParams { coarse_step: SEARCH_COARSE_STEP_S, threshold_km: None, min_step: SEARCH_MIN_STEP_S, accel_bound: SEARCH_ACCEL_BOUND_KM_S2 }
    }
}

pub struct AdaptiveResult {
    pub events: Vec<Approach>,
    pub all_minima: Vec<Approach>,
    pub params: AdaptiveParams,
    pub finest: f64,
    pub n_refined: usize,
}

impl AdaptiveResult {
    pub fn global_min(&self) -> Option<&Approach> {
        self.all_minima.iter().min_by(|a, b| a.miss_km.total_cmp(&b.miss_km))
    }
    pub fn resolution(&self) -> serde_json::Value {
        serde_json::json!({"method": "adaptive", "coarse_step_s": self.params.coarse_step, "min_step_s": self.params.min_step,
            "finest_step_used_s": self.finest, "threshold_km": self.params.threshold_km,
            "accel_bound_km_s2": self.params.accel_bound, "root_xtol_s": BRENT_XTOL_S,
            "n_refined_intervals": self.n_refined,
            "guarantee": "門檻以下、且與相鄰極小值相隔超過最小步長的近接必被辨識",
            "note": "TCA 與距離為數值解精度，不代表預報準確度"})
    }
}

/// 節點值：(距離, g = r·v, |v|)
type Node = (f64, f64, f64);

/// 自適應近接極小值搜尋（演算法說明見 Python tca.find_minima_adaptive）
pub fn find_minima_adaptive(
    rel_rv: &dyn Fn(f64) -> (V3, V3),
    rel_rva: &dyn Fn(f64) -> (V3, V3, V3),
    t0: f64,
    t1: f64,
    params: AdaptiveParams,
) -> AdaptiveResult {
    let (coarse_step, threshold_km, min_step, accel_bound) = (params.coarse_step, params.threshold_km, params.min_step, params.accel_bound);
    let n = (((t1 - t0) / coarse_step - 1e-9).ceil() as i64).max(1) as usize;
    let mut taus: Vec<f64> = (0..n).map(|k| t0 + k as f64 * coarse_step).collect();
    taus.push(t1);
    let ev = |tau: f64| -> Node {
        let (r, v) = rel_rv(tau);
        (norm(r), dot(r, v), norm(v))
    };
    let g = |tau: f64| {
        let (r, v) = rel_rv(tau);
        dot(r, v)
    };
    let nodes: Vec<Node> = taus.iter().map(|&t| ev(t)).collect();
    let mut found: Vec<Approach> = Vec::new();
    let mut n_refined = 0usize;
    let mut finest = coarse_step;

    let leaf = |a: f64, b: f64, sa: Node, sb: Node, found: &mut Vec<Approach>| {
        if sa.1 < 0.0 && 0.0 <= sb.1 {
            let root = brent_root(&g, a, b, sa.1, sb.1, BRENT_XTOL_S);
            let mut ap = approach(rel_rva, root, "interior");
            if norm(ap.v_rel) < SEARCH_LOW_VREL_KM_S {
                let tg = golden_min(&|t: f64| norm(rel_rv(t).0), a, b, 1e-6, 200);
                let alt = approach(rel_rva, tg, "interior");
                if alt.miss_km < ap.miss_km {
                    ap = alt;
                }
                ap.flag = "low_relative_velocity".into();
            }
            found.push(ap);
        }
    };

    let mut stack: Vec<(f64, f64, Node, Node)> = (0..n).map(|k| (taus[k], taus[k + 1], nodes[k], nodes[k + 1])).rev().collect();
    while let Some((a, b, sa, sb)) = stack.pop() {
        let h = b - a;
        if let Some(thr) = threshold_km {
            if h > min_step * (1.0 + 1e-9) && sa.2.max(sb.2) >= SEARCH_LOW_VREL_KM_S {
                let d_up = sa.0.max(sb.0) + (sa.2.max(sb.2) + accel_bound * h) * h / 2.0;
                let amax = accel_bound.min(SEARCH_TIDAL_COEF_S2 * d_up + SEARCH_PERT_ACCEL_KM_S2);
                let vmax = sa.2.max(sb.2) + amax * h;
                let lb = sa.0.min(sb.0) - vmax * h / 2.0;
                let jmax = SEARCH_TIDAL_COEF_S2 * vmax + amax * SEARCH_OMEGA_MAX_RAD_S;
                let dev = (3.0 * vmax * amax + d_up * jmax) * h * h / 8.0;
                let (ga, gb) = (sa.1, sb.1);
                let hidden_root_possible = if ga < 0.0 && gb < 0.0 {
                    ga.max(gb) + dev >= 0.0
                } else if ga > 0.0 && gb > 0.0 {
                    ga.min(gb) - dev <= 0.0
                } else {
                    dev >= ga.abs().min(gb.abs())
                };
                if lb < thr && hidden_root_possible {
                    let m = (SEARCH_SUBDIVIDE as f64).min((h / min_step - 1e-9).ceil()) as usize;
                    let mut sub: Vec<f64> = (0..=m).map(|i| a + h * i as f64 / m as f64).collect();
                    sub[m] = b;
                    let mut sv = Vec::with_capacity(m + 1);
                    sv.push(sa);
                    for &t in &sub[1..m] {
                        sv.push(ev(t));
                    }
                    sv.push(sb);
                    n_refined += 1;
                    finest = finest.min(h / m as f64);
                    for i in (0..m).rev() {
                        stack.push((sub[i], sub[i + 1], sv[i], sv[i + 1]));
                    }
                    continue;
                }
            }
        }
        leaf(a, b, sa, sb, &mut found);
    }

    if nodes[0].1 > 0.0 {
        found.insert(0, approach(rel_rva, taus[0], "window_edge_start"));
    }
    if nodes[n].1 < 0.0 {
        found.push(approach(rel_rva, taus[n], "window_edge_end"));
    }
    for ap in found.iter_mut() {
        if (ap.flag == "interior" || ap.flag == "low_relative_velocity") && !(ap.dgdt > 0.0) {
            ap.flag = "degenerate".into();
        }
    }
    found.sort_by(|x, y| x.tau.total_cmp(&y.tau));
    let events = found.iter().filter(|a| threshold_km.map_or(true, |t| a.miss_km <= t)).cloned().collect();
    AdaptiveResult { events, all_minima: found, params, finest, n_refined }
}
