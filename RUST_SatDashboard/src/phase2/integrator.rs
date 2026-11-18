//! 固定步長 RK4（GCRF）與五次 Hermite 內插星曆（與 Python integrator.py 相同）。

use super::forces::ForceModel;
use super::frames::EarthRotationTable;
use super::la::{add, scale};
use super::V3;

pub struct Trajectory {
    pub t0: f64,
    pub h: f64,
    pub r: Vec<V3>,
    pub v: Vec<V3>,
    pub a: Vec<V3>,
}

impl Trajectory {
    pub fn n(&self) -> usize {
        self.r.len()
    }
    pub fn t1(&self) -> f64 {
        self.t0 + (self.n() as f64 - 1.0) * self.h
    }
    pub fn state(&self, tau: f64) -> (V3, V3, V3) {
        let (lo, hi) = if self.h > 0.0 { (self.t0, self.t1()) } else { (self.t1(), self.t0) };
        assert!(tau >= lo - 1e-9 && tau <= hi + 1e-9, "τ={tau} 超出星曆範圍 [{lo}, {hi}]");
        let u = (tau - self.t0) / self.h;
        let k = (u.floor() as i64).clamp(0, self.n() as i64 - 2) as usize;
        hermite5(self.r[k], self.v[k], self.a[k], self.r[k + 1], self.v[k + 1], self.a[k + 1], self.h, u - k as f64)
    }
}

pub fn hermite5(r0: V3, v0: V3, a0: V3, r1: V3, v1: V3, a1: V3, h: f64, s: f64) -> (V3, V3, V3) {
    let (s2, s3, s4, s5) = (s * s, s.powi(3), s.powi(4), s.powi(5));
    let hh = [
        1.0 - 10.0 * s3 + 15.0 * s4 - 6.0 * s5,
        s - 6.0 * s3 + 8.0 * s4 - 3.0 * s5,
        0.5 * (s2 - 3.0 * s3 + 3.0 * s4 - s5),
        10.0 * s3 - 15.0 * s4 + 6.0 * s5,
        -4.0 * s3 + 7.0 * s4 - 3.0 * s5,
        0.5 * (s3 - 2.0 * s4 + s5),
    ];
    let dh = [
        -30.0 * s2 + 60.0 * s3 - 30.0 * s4,
        1.0 - 18.0 * s2 + 32.0 * s3 - 15.0 * s4,
        0.5 * (2.0 * s - 9.0 * s2 + 12.0 * s3 - 5.0 * s4),
        30.0 * s2 - 60.0 * s3 + 30.0 * s4,
        -12.0 * s2 + 28.0 * s3 - 15.0 * s4,
        0.5 * (3.0 * s2 - 8.0 * s3 + 5.0 * s4),
    ];
    let ddh = [
        -60.0 * s + 180.0 * s2 - 120.0 * s3,
        -36.0 * s + 96.0 * s2 - 60.0 * s3,
        0.5 * (2.0 - 18.0 * s + 36.0 * s2 - 20.0 * s3),
        60.0 * s - 180.0 * s2 + 120.0 * s3,
        -24.0 * s + 84.0 * s2 - 60.0 * s3,
        0.5 * (6.0 * s - 24.0 * s2 + 20.0 * s3),
    ];
    let terms = [r0, scale(v0, h), scale(a0, h * h), r1, scale(v1, h), scale(a1, h * h)];
    let comb = |c: &[f64; 6]| {
        let mut out = [0.0; 3];
        for (ck, t) in c.iter().zip(terms.iter()) {
            out = add(out, scale(*t, *ck));
        }
        out
    };
    (comb(&hh), scale(comb(&dh), 1.0 / h), scale(comb(&ddh), 1.0 / (h * h)))
}

pub fn propagate(r0: V3, v0: V3, t0: f64, t1: f64, h: f64, fm: &ForceModel, ert: Option<&EarthRotationTable>) -> Trajectory {
    let n = ((t1 - t0) / h - 1e-9).ceil() as usize + 1;
    let (mut rr, mut vv, mut aa) = (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
    let (mut r, mut v) = (r0, v0);
    let f = |tau: f64, r_: V3, v_: V3| {
        let er = ert.map(|t| t.at(tau));
        fm.accel(r_, v_, er.as_ref())
    };
    for k in 0..n {
        let tau = t0 + k as f64 * h;
        let a = f(tau, r, v);
        rr.push(r);
        vv.push(v);
        aa.push(a);
        if k == n - 1 {
            break;
        }
        let (k1r, k1v) = (v, a);
        let (k2r, k2v) = (add(v, scale(k1v, 0.5 * h)), f(tau + 0.5 * h, add(r, scale(k1r, 0.5 * h)), add(v, scale(k1v, 0.5 * h))));
        let (k3r, k3v) = (add(v, scale(k2v, 0.5 * h)), f(tau + 0.5 * h, add(r, scale(k2r, 0.5 * h)), add(v, scale(k2v, 0.5 * h))));
        let (k4r, k4v) = (add(v, scale(k3v, h)), f(tau + h, add(r, scale(k3r, h)), add(v, scale(k3v, h))));
        let step = |x: V3, a1: V3, a2: V3, a3: V3, a4: V3| {
            add(x, scale(add(add(a1, scale(a2, 2.0)), add(scale(a3, 2.0), a4)), h / 6.0))
        };
        r = step(r, k1r, k2r, k3r, k4r);
        v = step(v, k1v, k2v, k3v, k4v);
    }
    Trajectory { t0, h, r: rr, v: vv, a: aa }
}
