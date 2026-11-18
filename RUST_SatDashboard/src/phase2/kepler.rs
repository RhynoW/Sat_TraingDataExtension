//! 二體解析解（與 Python kepler.py 相同）。

use super::constants::GM_KM3_S2;
use super::la::{add, norm, scale};
use super::V3;

#[derive(Clone, Copy, Debug)]
pub struct Elements {
    pub a_km: f64,
    pub e: f64,
    pub i_rad: f64,
    pub raan_rad: f64,
    pub argp_rad: f64,
    pub m0_rad: f64,
}

pub fn solve_kepler(m: f64, e: f64) -> f64 {
    let mut ea = if e < 0.8 { m } else { std::f64::consts::PI };
    for _ in 0..50 {
        let d = (ea - e * ea.sin() - m) / (1.0 - e * ea.cos());
        ea -= d;
        if d.abs() < 1e-15 {
            break;
        }
    }
    ea
}

pub fn state(el: &Elements, tau: f64) -> (V3, V3, V3) {
    let mu = GM_KM3_S2;
    let n = (mu / el.a_km.powi(3)).sqrt();
    let m = (el.m0_rad + n * tau) % (2.0 * std::f64::consts::PI);
    let ea = solve_kepler(m, el.e);
    let (se, ce) = ea.sin_cos();
    let b = el.a_km * (1.0 - el.e * el.e).sqrt();
    let (xp, yp) = (el.a_km * (ce - el.e), b * se);
    let rr = el.a_km * (1.0 - el.e * ce);
    let (xd, yd) = (-el.a_km * n * se * el.a_km / rr, b * n * ce * el.a_km / rr);
    let (so, co) = el.raan_rad.sin_cos();
    let (sw, cw) = el.argp_rad.sin_cos();
    let (si, ci) = el.i_rad.sin_cos();
    let p = [co * cw - so * sw * ci, so * cw + co * sw * ci, sw * si];
    let q = [-co * sw - so * cw * ci, -so * sw + co * cw * ci, cw * si];
    let r = add(scale(p, xp), scale(q, yp));
    let v = add(scale(p, xd), scale(q, yd));
    let nr = norm(r);
    (r, v, scale(r, -mu / (nr * nr * nr)))
}
