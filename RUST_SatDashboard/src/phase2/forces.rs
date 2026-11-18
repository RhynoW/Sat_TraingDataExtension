//! 力模型（與 Python forces.py 同公式）：二體＋J2–J4（ITRF 計算）＋阻力（v_rel = v − ω⊕,GCRF × r）。

use sofars::coords::gc2gd;

use super::constants::{GM_KM3_S2, J2, J3, J4, RE_KM, WGS84_N};
use super::frames::EarthRotation;
use super::la::{add, cross, mtv, mv, norm, scale, sub};
use super::V3;

pub fn accel_two_body(r: V3) -> V3 {
    let n = norm(r);
    scale(r, -GM_KM3_S2 / (n * n * n))
}

pub fn accel_zonal_itrf(r: V3) -> V3 {
    let (x, y, z) = (r[0], r[1], r[2]);
    let r2 = x * x + y * y + z * z;
    let rn = r2.sqrt();
    let z2 = z * z / r2;
    let (mu, re) = (GM_KM3_S2, RE_KM);
    let f2 = -1.5 * J2 * mu * re.powi(2) / rn.powi(5);
    let a2 = [f2 * x * (1.0 - 5.0 * z2), f2 * y * (1.0 - 5.0 * z2), f2 * z * (3.0 - 5.0 * z2)];
    let f3 = -2.5 * J3 * mu * re.powi(3) / rn.powi(7);
    let a3 = [
        f3 * x * (3.0 * z - 7.0 * z.powi(3) / r2),
        f3 * y * (3.0 * z - 7.0 * z.powi(3) / r2),
        f3 * (6.0 * z * z - 7.0 * z.powi(4) / r2 - 0.6 * r2),
    ];
    let f4 = 1.875 * J4 * mu * re.powi(4) / rn.powi(7);
    let a4 = [
        f4 * x * (1.0 - 14.0 * z2 + 21.0 * z2 * z2),
        f4 * y * (1.0 - 14.0 * z2 + 21.0 * z2 * z2),
        f4 * z * (5.0 - 70.0 / 3.0 * z2 + 21.0 * z2 * z2),
    ];
    add(add(a2, a3), a4)
}

pub fn zonal_potential(r: V3) -> f64 {
    let rn = norm(r);
    let s = r[2] / rn;
    let p2 = 0.5 * (3.0 * s * s - 1.0);
    let p3 = 0.5 * (5.0 * s.powi(3) - 3.0 * s);
    let p4 = (35.0 * s.powi(4) - 30.0 * s * s + 3.0) / 8.0;
    let q = RE_KM / rn;
    -GM_KM3_S2 / rn * (J2 * q * q * p2 + J3 * q.powi(3) * p3 + J4 * q.powi(4) * p4)
}

#[derive(Clone, Copy, Debug)]
pub struct ExponentialAtmosphere {
    pub h0_km: f64,
    pub rho0: f64,
    pub scale_km: f64,
}

impl Default for ExponentialAtmosphere {
    fn default() -> Self {
        ExponentialAtmosphere { h0_km: 400.0, rho0: 3.725e-12, scale_km: 58.515 }
    }
}

impl ExponentialAtmosphere {
    pub fn density(&self, h_km: f64) -> f64 {
        self.rho0 * (-(h_km - self.h0_km) / self.scale_km).exp()
    }
}

pub fn geodetic_height_km(r_itrf: V3) -> f64 {
    match gc2gd(WGS84_N, scale(r_itrf, 1000.0)) {
        Ok((_e, _p, h)) => h / 1000.0,
        Err(_) => f64::NAN,
    }
}

pub fn accel_drag(r: V3, v: V3, er: &EarthRotation, ballistic_m2_kg: f64, atmos: &ExponentialAtmosphere) -> V3 {
    let v_rel = sub(v, cross(er.omega_gcrf(), r));
    let h = geodetic_height_km(mv(&er.m_gcrf_to_itrf(), r));
    let rho = atmos.density(h);
    scale(v_rel, -0.5 * rho * ballistic_m2_kg * norm(v_rel) * 1000.0)
}

#[derive(Clone, Copy, Debug)]
pub struct ForceModel {
    pub zonal: bool,
    pub drag: bool,
    pub ballistic_m2_kg: f64,
    pub atmos: ExponentialAtmosphere,
}

impl ForceModel {
    pub fn new(zonal: bool, drag: bool, ballistic_m2_kg: f64) -> Self {
        ForceModel { zonal, drag, ballistic_m2_kg, atmos: ExponentialAtmosphere::default() }
    }

    pub fn describe(&self) -> serde_json::Value {
        serde_json::json!({
            "two_body": true,
            "zonal": if self.zonal { Some("J2-J4") } else { None },
            "drag": if self.drag { Some(serde_json::json!({"model": "ExponentialAtmosphere", "ballistic_m2_kg": self.ballistic_m2_kg})) } else { None },
        })
    }

    pub fn accel(&self, r: V3, v: V3, er: Option<&EarthRotation>) -> V3 {
        let mut a = accel_two_body(r);
        if self.zonal {
            let m = er.expect("zonal 需要地球定向").m_gcrf_to_itrf();
            a = add(a, mtv(&m, accel_zonal_itrf(mv(&m, r))));
        }
        if self.drag {
            a = add(a, accel_drag(r, v, er.expect("drag 需要地球定向"), self.ballistic_m2_kg, &self.atmos));
        }
        a
    }
}
