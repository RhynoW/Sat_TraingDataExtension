//! RTN 軸與協方差速度語意（與 Python rtn.py 相同定義）。

use super::la::{add, cross, dot, inv, mat_t, matmul, mtv, mv, norm, scale, sub};
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

/// RTN 軸相對慣性系的角速度（RTN 分量，二體近似）：(0, 0, |r×v|/|r|²)
pub fn omega_rtn(r: V3, v: V3) -> V3 {
    [0.0, 0.0, norm(cross(r, v)) / dot(r, r)]
}

/// 追蹤星相對目標星的 RTN 狀態（m、m/s）；速度為旋轉 RTN 座標中的時間導數（HCW 的 ẋ, ẏ, ż）
pub fn relative_rtn(rt: V3, vt: V3, rc: V3, vc: V3) -> (V3, V3) {
    let c = rtn_matrix(rt, vt);
    let rho = scale(mv(&c, sub(rc, rt)), 1000.0);
    let rhod = sub(scale(mv(&c, sub(vc, vt)), 1000.0), cross(omega_rtn(rt, vt), rho));
    (rho, rhod)
}

/// relative_rtn 的反函數：目標星 GCRF 狀態＋RTN 相對狀態（m、m/s，旋轉座標導數）→ 追蹤星 GCRF（km、km/s）
pub fn rtn_offset_to_gcrf(rt: V3, vt: V3, r_m: V3, v_ms: V3) -> (V3, V3) {
    let c = rtn_matrix(rt, vt);
    let rc = add(rt, div(mtv(&c, r_m), 1000.0));
    let vc = add(vt, div(mtv(&c, add(v_ms, cross(omega_rtn(rt, vt), r_m))), 1000.0));
    (rc, vc)
}

fn div(a: V3, s: f64) -> V3 {
    [a[0] / s, a[1] / s, a[2] / s]
}
