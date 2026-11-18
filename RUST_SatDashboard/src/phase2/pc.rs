//! 二維碰撞機率 Foster／Chan（與 Python pc.py 同算法、同節點數）。

use std::f64::consts::PI;

use super::constants::{CHAN_MAX_TERMS, GL_ANGULAR_N, GL_RADIAL_N};
use super::la::{cross, dot, norm, scale, sub};
use super::{M3, V3};

pub fn gauss_legendre(n: usize) -> (Vec<f64>, Vec<f64>) {
    let (mut x, mut w) = (vec![0.0; n], vec![0.0; n]);
    let legendre = |z: f64| {
        let (mut p0, mut p1) = (1.0, z);
        for k in 2..=n {
            let p2 = ((2 * k - 1) as f64 * z * p1 - (k - 1) as f64 * p0) / k as f64;
            p0 = p1;
            p1 = p2;
        }
        let dp = n as f64 * (z * p1 - p0) / (z * z - 1.0);
        (p1, dp)
    };
    for i in 0..n {
        let mut z = (PI * (i as f64 + 0.75) / (n as f64 + 0.5)).cos();
        for _ in 0..100 {
            let (p1, dp) = legendre(z);
            let dz = p1 / dp;
            z -= dz;
            if dz.abs() < 1e-15 {
                break;
            }
        }
        let (_p1, dp) = legendre(z);
        x[i] = z;
        w[i] = 2.0 / ((1.0 - z * z) * dp * dp);
    }
    (x, w)
}

pub fn encounter_frame(r_rel: V3, v_rel: V3) -> M3 {
    let z = scale(v_rel, 1.0 / norm(v_rel));
    let mut rp = sub(r_rel, scale(z, dot(r_rel, z)));
    let mut nrp = norm(rp);
    if nrp < 1e-12 {
        let tmp = if z[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
        rp = sub(tmp, scale(z, dot(tmp, z)));
        nrp = norm(rp);
    }
    let x = scale(rp, 1.0 / nrp);
    let y = cross(z, x);
    [x, y, z]
}

/// 回傳 (miss2, C2, F)：交會平面 miss 向量、2×2 協方差、交會座標軸
pub fn project(r_rel: V3, v_rel: V3, c3: &M3) -> ([f64; 2], [[f64; 2]; 2], M3) {
    let f = encounter_frame(r_rel, v_rel);
    let mut c2 = [[0.0; 2]; 2];
    for i in 0..2 {
        for j in 0..2 {
            let mut s = 0.0;
            for a in 0..3 {
                for b in 0..3 {
                    s += f[i][a] * c3[a][b] * f[j][b];
                }
            }
            c2[i][j] = s;
        }
    }
    let off = 0.5 * (c2[0][1] + c2[1][0]);
    c2[0][1] = off;
    c2[1][0] = off;
    ([dot(f[0], r_rel), dot(f[1], r_rel)], c2, f)
}

pub fn pc_foster(miss: [f64; 2], c2: &[[f64; 2]; 2], hbr_km: f64) -> anyhow::Result<f64> {
    let (a, b, c) = (c2[0][0], c2[0][1], c2[1][1]);
    let det = a * c - b * b;
    anyhow::ensure!(det > 0.0, "C2 非正定");
    let (ia, ib, ic) = (c / det, -b / det, a / det);
    let nrm = 1.0 / (2.0 * PI * det.sqrt());
    let (xg, wg) = gauss_legendre(GL_RADIAL_N);
    let nt = GL_ANGULAR_N;
    let mut total = 0.0;
    for (xi, wi) in xg.iter().zip(wg.iter()) {
        let rho = 0.5 * hbr_km * (xi + 1.0);
        let mut acc = 0.0;
        for j in 0..nt {
            let th = 2.0 * PI * j as f64 / nt as f64;
            let x = miss[0] + rho * th.cos();
            let y = miss[1] + rho * th.sin();
            acc += (-0.5 * (ia * x * x + 2.0 * ib * x * y + ic * y * y)).exp();
        }
        total += wi * rho * acc * (2.0 * PI / nt as f64);
    }
    Ok(nrm * total * 0.5 * hbr_km)
}

pub fn eig2(c2: &[[f64; 2]; 2]) -> (f64, f64, f64) {
    let (a, b, c) = (c2[0][0], c2[0][1], c2[1][1]);
    let m = 0.5 * (a + c);
    let d = (0.25 * (a - c).powi(2) + b * b).sqrt();
    (m + d, m - d, 0.5 * (2.0 * b).atan2(a - c))
}

pub fn pc_chan(miss: [f64; 2], c2: &[[f64; 2]; 2], hbr_km: f64) -> anyhow::Result<f64> {
    let (l1, l2, th) = eig2(c2);
    anyhow::ensure!(l2 > 0.0, "C2 非正定");
    let (sx, sy) = (l1.sqrt(), l2.sqrt());
    let (st, ct) = th.sin_cos();
    let xm = ct * miss[0] + st * miss[1];
    let ym = -st * miss[0] + ct * miss[1];
    let u = hbr_km * hbr_km / (sx * sy);
    let v = xm * xm / l1 + ym * ym / l2;
    // Pc = Σ_m w_m · tail_m，w_m = e^{−v/2}(v/2)^m/m!（遞迴，不溢位）；tail_m 為 Poisson 尾項（由大 k 往小 k 累加）
    if 0.5 * v > 700.0 {
        return Ok(0.0);
    }
    let max_terms = CHAN_MAX_TERMS + (0.5 * v).ceil() as usize;
    let kmax = max_terms + 60;
    let mut pk = vec![0.0; kmax + 1];
    pk[0] = (-0.5 * u).exp();
    for k in 1..=kmax {
        pk[k] = pk[k - 1] * 0.5 * u / k as f64;
    }
    let mut tail = vec![0.0; kmax + 1];
    let mut acc = 0.0;
    for k in (1..=kmax).rev() {
        acc += pk[k];
        tail[k - 1] = acc;
    }
    let (mut w, mut total) = ((-0.5 * v).exp(), 0.0);
    for m in 0..max_terms {
        if m > 0 {
            w *= 0.5 * v / m as f64;
        }
        let term = w * tail[m];
        total += term;
        if m as f64 > 0.5 * v + 2.0 && term < 1e-18 * total.max(1e-300) {
            break;
        }
    }
    Ok(total)
}
