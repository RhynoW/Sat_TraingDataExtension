//! TEME / GCRF / ITRF 狀態與協方差轉換（與 Python frames.py 同一轉換鏈）。
//! GCRF→ITRF：IAU-2006/2000A CIO 法（xy06＋dX/dY、s06、c2ixys、era00、pom00）；
//! TEME→ITRF：Vallado（2006），PEF = R3(GMST82)·TEME。地球自轉項只在 TIRS／PEF 層出現一次。

use sofars::{erst, pnp};

use super::constants::{DAY_S, OMEGA_E_RAD_S, PN_NODE_STEP_S};
use super::eop::EopSource;
use super::la::{cross, mm, mtv, mv, sub, add, transpose};
use super::timescale::UtcTime;
use super::{M3, V3};

pub fn rz(theta: f64) -> M3 {
    let (s, c) = theta.sin_cos();
    [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]
}

#[derive(Clone, Copy, Debug)]
pub struct EarthRotation {
    pub rc2i: M3,
    pub era: f64,
    pub rpom: M3,
    pub omega: f64,
    pub gmst82: f64,
}

impl EarthRotation {
    pub fn m_gcrf_to_tirs(&self) -> M3 {
        mm(&rz(self.era), &self.rc2i)
    }
    pub fn m_gcrf_to_itrf(&self) -> M3 {
        mm(&self.rpom, &self.m_gcrf_to_tirs())
    }
    pub fn omega_gcrf(&self) -> V3 {
        mtv(&self.m_gcrf_to_tirs(), [0.0, 0.0, self.omega])
    }
}

fn pn_quantities(t: &UtcTime, eop: &dyn EopSource) -> anyhow::Result<(f64, f64, f64, f64, super::eop::EopValues)> {
    let ev = eop.at(t.mjd_float())?;
    let (tt1, tt2) = t.tt_jd(ev.dat_s);
    let (x, y) = pnp::xy06(tt1, tt2);
    let (x, y) = (x + ev.dx_rad, y + ev.dy_rad);
    let s = pnp::s06(tt1, tt2, x, y);
    let sp = pnp::sp00(tt1, tt2);
    Ok((x, y, s, sp, ev))
}

fn build(t: &UtcTime, x: f64, y: f64, s: f64, xp: f64, yp: f64, sp: f64, dut1: f64, lod: f64) -> EarthRotation {
    let (u1, u2) = t.ut1_jd(dut1);
    EarthRotation {
        rc2i: pnp::c2ixys(x, y, s),
        era: erst::era00(u1, u2),
        rpom: pnp::pom00(xp, yp, sp),
        omega: OMEGA_E_RAD_S * (1.0 - lod / DAY_S),
        gmst82: erst::gmst82(u1, u2),
    }
}

/// 單一時刻直接計算（不內插）
pub fn earth_rotation(t: &UtcTime, eop: &dyn EopSource) -> anyhow::Result<EarthRotation> {
    let (x, y, s, sp, ev) = pn_quantities(t, eop)?;
    Ok(build(t, x, y, s, ev.xp_rad, ev.yp_rad, sp, ev.ut1_utc_s, ev.lod_s))
}

/// 傳播區間的地球定向表：X、Y、s、xp、yp、s'、UT1−UTC、LOD 於節點線性內插
pub struct EarthRotationTable {
    pub epoch: UtcTime,
    step: f64,
    n0: i64,
    vals: Vec<[f64; 8]>,
    pub dat: f64,
}

impl EarthRotationTable {
    pub fn new(epoch: UtcTime, t0_s: f64, t1_s: f64, eop: &dyn EopSource) -> anyhow::Result<Self> {
        let step = PN_NODE_STEP_S;
        let n0 = (t0_s / step).floor() as i64 - 1;
        let n1 = (t1_s / step).ceil() as i64 + 1;
        let mut vals = Vec::new();
        for k in n0..=n1 {
            let (x, y, s, sp, ev) = pn_quantities(&epoch.plus(k as f64 * step), eop)?;
            vals.push([x, y, s, ev.xp_rad, ev.yp_rad, sp, ev.ut1_utc_s, ev.lod_s]);
        }
        let dat = eop.at(epoch.plus(t0_s).mjd_float())?.dat_s;
        anyhow::ensure!(eop.at(epoch.plus(t1_s).mjd_float())?.dat_s == dat, "傳播區間跨越閏秒，Sprint 0 不支援");
        Ok(EarthRotationTable { epoch, step, n0, vals, dat })
    }

    pub fn at(&self, tau_s: f64) -> EarthRotation {
        let u = tau_s / self.step - self.n0 as f64;
        let i = (u.floor() as i64).clamp(0, self.vals.len() as i64 - 2) as usize;
        let f = u - i as f64;
        let (a, b) = (&self.vals[i], &self.vals[i + 1]);
        let v: Vec<f64> = (0..8).map(|k| a[k] + f * (b[k] - a[k])).collect();
        let t = self.epoch.plus(tau_s);
        build(&t, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7])
    }
}

pub fn gcrf_to_itrf(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let m = er.m_gcrf_to_tirs();
    let rt = mv(&m, r);
    let vt = sub(mv(&m, v), cross([0.0, 0.0, er.omega], rt));
    (mv(&er.rpom, rt), mv(&er.rpom, vt))
}

pub fn itrf_to_gcrf(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let rt = mtv(&er.rpom, r);
    let vt = mtv(&er.rpom, v);
    let m = er.m_gcrf_to_tirs();
    (mtv(&m, rt), mtv(&m, add(vt, cross([0.0, 0.0, er.omega], rt))))
}

pub fn teme_to_itrf(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let m = rz(er.gmst82);
    let rp = mv(&m, r);
    let vp = sub(mv(&m, v), cross([0.0, 0.0, er.omega], rp));
    (mv(&er.rpom, rp), mv(&er.rpom, vp))
}

pub fn itrf_to_teme(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let rp = mtv(&er.rpom, r);
    let vp = mtv(&er.rpom, v);
    let m = rz(er.gmst82);
    (mtv(&m, rp), mtv(&m, add(vp, cross([0.0, 0.0, er.omega], rp))))
}

pub fn teme_to_gcrf(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let (ri, vi) = teme_to_itrf(r, v, er);
    itrf_to_gcrf(ri, vi, er)
}

pub fn gcrf_to_teme(r: V3, v: V3, er: &EarthRotation) -> (V3, V3) {
    let (ri, vi) = gcrf_to_itrf(r, v, er);
    itrf_to_teme(ri, vi, er)
}

pub type StateFn = fn(V3, V3, &EarthRotation) -> (V3, V3);

/// 線性狀態轉換的 6×6 Jacobian：J[:, k] = fn(e_k)
pub fn state_jacobian(f: StateFn, er: &EarthRotation) -> Vec<Vec<f64>> {
    let mut j = vec![vec![0.0; 6]; 6];
    for k in 0..6 {
        let mut e = [0.0; 6];
        e[k] = 1.0;
        let (r, v) = f([e[0], e[1], e[2]], [e[3], e[4], e[5]], er);
        for i in 0..3 {
            j[i][k] = r[i];
            j[i + 3][k] = v[i];
        }
    }
    j
}

pub fn transform_covariance(p: &[Vec<f64>], f: StateFn, er: &EarthRotation) -> Vec<Vec<f64>> {
    use super::la::{mat_t, matmul};
    let j = state_jacobian(f, er);
    matmul(&matmul(&j, p), &mat_t(&j))
}

#[allow(unused)]
fn _t(m: &M3) -> M3 {
    transpose(m)
}
