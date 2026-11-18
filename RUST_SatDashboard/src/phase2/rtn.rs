//! RTN 軸與協方差速度語意（與 Python rtn.py 相同定義）。

use super::la::{cross, dot, inv, mat_t, matmul, norm, scale};
use super::{M3, V3};

pub const CONVENTIONS: [&str; 2] = ["inertial_velocity_components", "rotating_frame_derivative"];

pub fn rtn_matrix(r: V3, v: V3) -> M3 {
    let rr = scale(r, 1.0 / norm(r));
    let h = cross(r, v);
    let n = scale(h, 1.0 / norm(h));
    let t = cross(n, rr);
    [rr, t, n]
}

pub fn jacobian_gcrf_to_rtn(r: V3, v: V3, convention: &str) -> anyhow::Result<Vec<Vec<f64>>> {
    anyhow::ensure!(CONVENTIONS.contains(&convention), "velocity_convention 須為 {CONVENTIONS:?}，收到 {convention}");
    let c = rtn_matrix(r, v);
    let mut j = vec![vec![0.0; 6]; 6];
    for i in 0..3 {
        for k in 0..3 {
            j[i][k] = c[i][k];
            j[i + 3][k + 3] = c[i][k];
        }
    }
    if convention == "rotating_frame_derivative" {
        let w = norm(cross(r, v)) / dot(r, r);
        // −[ω×]·C，ω = (0, 0, w)：[ω×] = [[0,−w,0],[w,0,0],[0,0,0]]
        for k in 0..3 {
            j[3][k] = w * c[1][k];
            j[4][k] = -w * c[0][k];
            j[5][k] = 0.0;
        }
    }
    Ok(j)
}

pub fn cov_gcrf_to_rtn(p: &[Vec<f64>], r: V3, v: V3, convention: &str) -> anyhow::Result<Vec<Vec<f64>>> {
    let j = jacobian_gcrf_to_rtn(r, v, convention)?;
    Ok(matmul(&matmul(&j, p), &mat_t(&j)))
}

pub fn cov_rtn_to_gcrf(p: &[Vec<f64>], r: V3, v: V3, convention: &str) -> anyhow::Result<Vec<Vec<f64>>> {
    let j = inv(&jacobian_gcrf_to_rtn(r, v, convention)?).ok_or_else(|| anyhow::anyhow!("RTN Jacobian 不可逆"))?;
    Ok(matmul(&matmul(&j, p), &mat_t(&j)))
}
