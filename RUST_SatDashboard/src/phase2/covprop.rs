//! 協方差傳播模式（與 Python covprop.py 相同）：沿名義軌跡（SGP4 或數值星曆）以數值動力學傳播 6×6 GCRF 協方差。
//!
//!     dP/dt = A P + P Aᵀ + Q_c,  A = [[0, I], [G, 0]],  Q_c = diag(0, 0, 0, q, q, q)
//!
//! G = ∂a/∂r：二體項解析式 μ/r³(3 r̂ r̂ᵀ − I)；J2–J4 帶諧項於 ITRF 以中央差分（步長 COV_JAC_DR_KM）
//! 求得後旋回 GCRF。阻力偏導數不納入。RK4 固定步長；節點之間的時刻以前一節點做一次 RK4 子步取得。

use std::cell::RefCell;
use std::collections::HashMap;

use serde_json::{json, Value};

use super::constants::{COV_JAC_DR_KM, GM_KM3_S2};
use super::ephemeris::Ephemeris;
use super::forces::accel_zonal_itrf;
use super::frames::EarthRotationTable;
use super::la::{mm, mv, norm, transpose};
use super::M3;

pub type M6 = [[f64; 6]; 6];

pub fn gravity_gradient(r: [f64; 3], ert: Option<&EarthRotationTable>, tau: f64, zonal: bool) -> M3 {
    let n = norm(r);
    let u = [r[0] / n, r[1] / n, r[2] / n];
    let k = GM_KM3_S2 / n.powi(3);
    let mut g = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            g[i][j] = k * (3.0 * u[i] * u[j] - if i == j { 1.0 } else { 0.0 });
        }
    }
    if let (true, Some(ert)) = (zonal, ert) {
        let m = ert.at(tau).m_gcrf_to_itrf();
        let ri = mv(&m, r);
        let mut gz = [[0.0; 3]; 3];
        for c in 0..3 {
            let (mut p, mut q) = (ri, ri);
            p[c] += COV_JAC_DR_KM;
            q[c] -= COV_JAC_DR_KM;
            let (ap, aq) = (accel_zonal_itrf(p), accel_zonal_itrf(q));
            for i in 0..3 {
                gz[i][c] = (ap[i] - aq[i]) / (2.0 * COV_JAC_DR_KM);
            }
        }
        let rot = mm(&mm(&transpose(&m), &gz), &m);
        for i in 0..3 {
            for j in 0..3 {
                g[i][j] += rot[i][j];
            }
        }
    }
    g
}

pub fn m6_from(p: &[Vec<f64>]) -> M6 {
    let mut o = [[0.0; 6]; 6];
    for i in 0..6 {
        for j in 0..6 {
            o[i][j] = p[i][j];
        }
    }
    o
}

pub fn m6_to_vec(p: &M6) -> Vec<Vec<f64>> {
    p.iter().map(|r| r.to_vec()).collect()
}

fn axpy(p: &M6, s: f64, k: &M6) -> M6 {
    let mut o = *p;
    for i in 0..6 {
        for j in 0..6 {
            o[i][j] = p[i][j] + s * k[i][j];
        }
    }
    o
}

pub struct CovarianceTrack<'a> {
    eph: &'a dyn Ephemeris,
    ert: Option<&'a EarthRotationTable>,
    pub zonal: bool,
    pub q: f64,
    pub h: f64,
    pub t0: f64,
    pub t1: f64,
    p: RefCell<Vec<M6>>,
    gcache: RefCell<HashMap<u64, M3>>,
}

impl<'a> CovarianceTrack<'a> {
    pub fn new(eph: &'a dyn Ephemeris, p0: M6, t0: f64, t1: f64, h: f64, ert: Option<&'a EarthRotationTable>, zonal: bool, q_km2_s3: f64) -> Self {
        CovarianceTrack { eph, ert, zonal, q: q_km2_s3, h, t0, t1, p: RefCell::new(vec![p0]), gcache: RefCell::new(HashMap::new()) }
    }

    fn extend_to(&self, tau: f64) {
        loop {
            let len = self.p.borrow().len();
            if !(self.t0 + (len - 1) as f64 * self.h < tau - 1e-9) {
                break;
            }
            let k = len - 1;
            let pk = self.p.borrow()[k];
            let next = self.step(self.t0 + k as f64 * self.h, &pk, self.h);
            self.p.borrow_mut().push(next);
            self.gcache.borrow_mut().remove(&(self.t0 + (k as f64 - 1.0) * self.h).to_bits());
        }
    }

    fn gradient(&self, tau: f64) -> M3 {
        if let Some(g) = self.gcache.borrow().get(&tau.to_bits()) {
            return *g;
        }
        let (r, _) = self.eph.rv(tau);
        let g = gravity_gradient(r, self.ert, tau, self.zonal);
        self.gcache.borrow_mut().insert(tau.to_bits(), g);
        g
    }

    fn deriv(&self, tau: f64, p: &M6) -> M6 {
        let g = self.gradient(tau);
        let mut a = [[0.0; 6]; 6];
        for i in 0..3 {
            a[i][i + 3] = 1.0;
            for j in 0..3 {
                a[i + 3][j] = g[i][j];
            }
        }
        let mut d = [[0.0; 6]; 6];
        for i in 0..6 {
            for j in 0..6 {
                let mut ap = 0.0;
                let mut pa = 0.0;
                for k in 0..6 {
                    ap += a[i][k] * p[k][j];
                    pa += p[i][k] * a[j][k];
                }
                d[i][j] = ap + pa;
            }
        }
        if self.q != 0.0 {
            for i in 3..6 {
                d[i][i] += self.q;
            }
        }
        d
    }

    fn step(&self, tau: f64, p: &M6, h: f64) -> M6 {
        let k1 = self.deriv(tau, p);
        let k2 = self.deriv(tau + 0.5 * h, &axpy(p, 0.5 * h, &k1));
        let k3 = self.deriv(tau + 0.5 * h, &axpy(p, 0.5 * h, &k2));
        let k4 = self.deriv(tau + h, &axpy(p, h, &k3));
        let mut out = [[0.0; 6]; 6];
        for i in 0..6 {
            for j in 0..6 {
                out[i][j] = p[i][j] + h / 6.0 * (k1[i][j] + 2.0 * k2[i][j] + 2.0 * k3[i][j] + k4[i][j]);
            }
        }
        let mut sym = [[0.0; 6]; 6];
        for i in 0..6 {
            for j in 0..6 {
                sym[i][j] = 0.5 * (out[i][j] + out[j][i]);
            }
        }
        sym
    }

    pub fn at(&self, tau: f64) -> anyhow::Result<M6> {
        anyhow::ensure!(tau <= self.t1 + 1e-6, "τ={tau} 超出協方差傳播範圍 {}", self.t1);
        self.extend_to(tau);
        let len = self.p.borrow().len();
        let u = (tau - self.t0) / self.h;
        let k = (u.floor() as i64).clamp(0, len as i64 - 1) as usize;
        let dt = tau - (self.t0 + k as f64 * self.h);
        let pk = self.p.borrow()[k];
        if dt.abs() < 1e-9 {
            return Ok(pk);
        }
        Ok(self.step(self.t0 + k as f64 * self.h, &pk, dt))
    }

    /// 位置 3×3 區塊（Pc 用）；超出範圍時回傳 NaN（呼叫端事先保證範圍）
    pub fn pos_at(&self, tau: f64) -> M3 {
        match self.at(tau) {
            Ok(p) => [[p[0][0], p[0][1], p[0][2]], [p[1][0], p[1][1], p[1][2]], [p[2][0], p[2][1], p[2][2]]],
            Err(_) => [[f64::NAN; 3]; 3],
        }
    }

    pub fn describe(&self) -> Value {
        json!({"method": "numerical_variational_gcrf", "integrator": "RK4", "step_s": self.h,
               "gravity_partials": if self.zonal { "two-body analytic + J2–J4 central difference" } else { "two-body analytic" },
               "drag_partials": "not included",
               "process_noise": {"model": if self.q != 0.0 { "white_accel" } else { "none" }, "q_km2_s3": self.q}})
    }
}
