//! RPO 控制模擬（v0.3 Sprint 3）：HCW 設計、閉迴路非線性重播、安全監控、abort_to_hold（與 Python rpo.py
//! 同流程、同步數規則、同控制律與平手規則、同輸出鍵名與順序）。
//!
//! 座標：目標星（primary）RTN 軸，x = R、y = T、z = N；相對狀態單位 m、m/s，速度為旋轉 RTN 座標中的時間導數。
//! 追蹤星為 secondary。
//!
//! 段落（rpo.sequence）
//!   transfer    雙脈衝 HCW 瞄準：起點依實際相對狀態解 Φ_rv v₀ = r_f − Φ_rr r₀；到達時把相對速度歸零
//!   hold        脈衝式死區保持：偏離駐留點超過 deadband 時，以 HCW 瞄準在 retarget_s 內回到駐留點，到達時歸零
//!   fly_around  HCW 自然 2:1 橢圓：v = (n·y₀/2, −2n·x₀, 0)，經 revolutions 圈後歸零
//! 同一控制律分別在 HCW 線性模型（設計）與 GCRF 數值傳播（二體＋J2–J4＋阻力，閉迴路重播）中執行。
//! 安全監控、abort_to_hold 撤離表與故障注入同 Python 說明。

use std::collections::{BTreeSet, HashMap, HashSet};
use std::time::Instant;

use serde_json::{json, Map, Value};

use super::constants::*;
use super::e2e::{initial_state_gcrf, object_force_model};
use super::eop::Eop;
use super::ephemeris::{Ephemeris, NumericalEphemeris};
use super::forces::{accel_drag, ForceModel};
use super::frames::{EarthRotation, EarthRotationTable};
use super::integrator::{propagate, Trajectory};
use super::la::{add, cross, dot, mtv, mv, norm, scale, sub};
use super::maneuver::py_round;
use super::rtn::{relative_rtn, rtn_matrix, rtn_offset_to_gcrf};
use super::schema::validate;
use super::timescale::{seconds_between, UtcTime};
use super::V3;

pub const CODE_VERSION: &str = "phase2-sprint3";

pub type S6 = [[f64; 6]; 6];

/// AXES（corridor_axis）
pub fn axis(name: &str) -> V3 {
    match name {
        "+R" => [1.0, 0.0, 0.0],
        "-R" => [-1.0, 0.0, 0.0],
        "+T" => [0.0, 1.0, 0.0],
        "-T" => [0.0, -1.0, 0.0],
        "+N" => [0.0, 0.0, 1.0],
        _ => [0.0, 0.0, -1.0],
    }
}

/// itertools.product((-1, 0, 1), repeat=3) 去掉 (0,0,0) 後正規化（順序同 Python）
pub fn abort_dirs() -> Vec<V3> {
    let mut out = Vec::with_capacity(26);
    for a in [-1i32, 0, 1] {
        for b in [-1i32, 0, 1] {
            for c in [-1i32, 0, 1] {
                if (a, b, c) == (0, 0, 0) {
                    continue;
                }
                let s = ((a * a + b * b + c * c) as f64).sqrt();
                out.push([a as f64 / s, b as f64 / s, c as f64 / s]);
            }
        }
    }
    out
}

#[derive(Debug)]
pub struct DesignError {
    pub code: &'static str,
    pub segment: usize,
    pub detail: Value,
}

pub fn hcw_stm(n: f64, t: f64) -> S6 {
    let (s, c) = ((n * t).sin(), (n * t).cos());
    [
        [4.0 - 3.0 * c, 0.0, 0.0, s / n, 2.0 * (1.0 - c) / n, 0.0],
        [6.0 * (s - n * t), 1.0, 0.0, -2.0 * (1.0 - c) / n, (4.0 * s - 3.0 * n * t) / n, 0.0],
        [0.0, 0.0, c, 0.0, 0.0, s / n],
        [3.0 * n * s, 0.0, 0.0, c, 2.0 * s, 0.0],
        [-6.0 * n * (1.0 - c), 0.0, 0.0, -2.0 * s, 4.0 * c - 3.0, 0.0],
        [0.0, 0.0, -n * s, 0.0, 0.0, c],
    ]
}

/// 6×6 STM 的 3×3 子塊 (列 r0.., 行 c0..)
fn block(p: &S6, r0: usize, c0: usize) -> [[f64; 3]; 3] {
    let mut b = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            b[i][j] = p[r0 + i][c0 + j];
        }
    }
    b
}

/// 3×3 LU（部分選主元，乘數以倒數相乘，同 LAPACK getf2）
fn lu3(a: &[[f64; 3]; 3]) -> ([[f64; 3]; 3], [usize; 3], f64) {
    let mut m = *a;
    let mut piv = [0usize, 1, 2];
    let mut sign = 1.0;
    for k in 0..3 {
        let mut p = k;
        for i in k + 1..3 {
            if m[i][k].abs() > m[p][k].abs() {
                p = i;
            }
        }
        if p != k {
            m.swap(p, k);
            piv.swap(p, k);
            sign = -sign;
        }
        if m[k][k] != 0.0 {
            let rcp = 1.0 / m[k][k];
            for i in k + 1..3 {
                m[i][k] *= rcp;
            }
        }
        for i in k + 1..3 {
            for j in k + 1..3 {
                m[i][j] -= m[i][k] * m[k][j];
            }
        }
    }
    let det = sign * m[0][0] * m[1][1] * m[2][2];
    (m, piv, det)
}

fn det3(a: &[[f64; 3]; 3]) -> f64 {
    lu3(a).2
}

fn solve3(a: &[[f64; 3]; 3], b: V3) -> V3 {
    let (m, piv, _) = lu3(a);
    let mut y = [b[piv[0]], b[piv[1]], b[piv[2]]];
    for i in 1..3 {
        for j in 0..i {
            y[i] -= m[i][j] * y[j];
        }
    }
    for i in (0..3).rev() {
        for j in i + 1..3 {
            y[i] -= m[i][j] * y[j];
        }
        y[i] /= m[i][i];
    }
    y
}

/// 起點所需相對速度 v₀（m/s）。Φ_rv 近奇異時回傳 DesignError("transfer_singular")
pub fn hcw_target(r0: V3, rf: V3, n: f64, t: f64, segment: usize) -> Result<V3, DesignError> {
    let p = hcw_stm(n, t);
    let a = block(&p, 0, 3);
    let mut an = a;
    for row in an.iter_mut() {
        for x in row.iter_mut() {
            *x *= n;
        }
    }
    if det3(&an).abs() < 1e-9 {
        return Err(DesignError { code: "transfer_singular", segment, detail: json!({"duration_s": t}) });
    }
    Ok(solve3(&a, sub(rf, mv(&block(&p, 0, 0), r0))))
}

/// HCW 在常數加速度 a（m/s²，RTN）下的特解位置（自 t = 0 起，零初始狀態）
pub fn hcw_forced(n: f64, t: f64, a: V3) -> V3 {
    let (s, c) = ((n * t).sin(), (n * t).cos());
    let (ax, ay, az) = (a[0], a[1], a[2]);
    let n2 = n * n;
    [
        ax / n2 * (1.0 - c) + 2.0 * ay / n2 * (n * t - s),
        -2.0 * ax / n2 * (n * t - s) + ay / n2 * (4.0 * (1.0 - c) - 1.5 * n2 * t * t),
        az / n2 * (1.0 - c),
    ]
}

/// 差分阻力加速度（追蹤星減目標星），目標星 RTN 分量，m/s²
pub fn drag_rel_rtn(fm_t: &ForceModel, fm_c: &ForceModel, rt: V3, vt: V3, rc: V3, vc: V3, er: &EarthRotation) -> V3 {
    let mut a = [0.0; 3];
    if fm_c.drag {
        a = add(a, accel_drag(rc, vc, er, fm_c.ballistic_m2_kg, &fm_c.atmos));
    }
    if fm_t.drag {
        a = sub(a, accel_drag(rt, vt, er, fm_t.ballistic_m2_kg, &fm_t.atmos));
    }
    scale(mv(&rtn_matrix(rt, vt), a), 1000.0)
}

pub fn mean_motion(r: V3, v: V3) -> f64 {
    let a = 1.0 / (2.0 / norm(r) - dot(v, v) / GM_KM3_S2);
    (GM_KM3_S2 / a.powf(3.0)).sqrt()
}

fn ecc(r: V3, v: V3) -> f64 {
    let (rn, v2) = (norm(r), dot(v, v));
    let a = 1.0 / (2.0 / rn - v2 / GM_KM3_S2);
    let h = cross(r, v);
    (1.0 - dot(h, h) / (GM_KM3_S2 * a)).max(0.0).sqrt()
}

/// 與 Python _rk4（integrator.propagate 的單步）相同運算式與加總順序
pub fn rk4(r: V3, v: V3, tau: f64, h: f64, fm: &ForceModel, ert: &EarthRotationTable) -> (V3, V3) {
    let f = |t: f64, r_: V3, v_: V3| {
        if fm.zonal || fm.drag {
            fm.accel(r_, v_, Some(&ert.at(t)))
        } else {
            fm.accel(r_, v_, None)
        }
    };
    let a = f(tau, r, v);
    let (k1r, k1v) = (v, a);
    let (k2r, k2v) = (add(v, scale(k1v, 0.5 * h)), f(tau + 0.5 * h, add(r, scale(k1r, 0.5 * h)), add(v, scale(k1v, 0.5 * h))));
    let (k3r, k3v) = (add(v, scale(k2v, 0.5 * h)), f(tau + 0.5 * h, add(r, scale(k2r, 0.5 * h)), add(v, scale(k2v, 0.5 * h))));
    let (k4r, k4v) = (add(v, scale(k3v, h)), f(tau + h, add(r, scale(k3r, h)), add(v, scale(k3v, h))));
    // Python：x + h/6·(k1 + 2·k2 + 2·k3 + k4)，加總由左至右
    let comb = |x: V3, a1: V3, a2: V3, a3: V3, a4: V3| {
        let mut out = [0.0; 3];
        for i in 0..3 {
            out[i] = x[i] + h / 6.0 * (a1[i] + 2.0 * a2[i] + 2.0 * a3[i] + a4[i]);
        }
        out
    };
    (comb(r, k1r, k2r, k3r, k4r), comb(v, k1v, k2v, k3v, k4v))
}

pub fn steps(x: f64, h: f64) -> usize {
    ((x / h + 0.5).floor() as i64).max(1) as usize
}

/// Python float // float
pub fn py_floordiv(vx: f64, wx: f64) -> f64 {
    let m = vx % wx;
    let mut div = (vx - m) / wx;
    if m != 0.0 && ((wx < 0.0) != (m < 0.0)) {
        div -= 1.0;
    }
    if div != 0.0 {
        let mut fd = div.floor();
        if div - fd > 0.5 {
            fd += 1.0;
        }
        fd
    } else {
        (0.0f64).copysign(vx / wx)
    }
}

trait Plant {
    fn k(&self) -> usize;
    fn rel(&self) -> (V3, V3);
    fn mean_motion(&self) -> f64;
    fn apply(&mut self, dv: V3);
    fn step(&mut self);
    fn state(&self) -> (V3, V3);
}

struct HcwPlant {
    x: [f64; 6],
    n: f64,
    phi: S6,
    k: usize,
}

impl HcwPlant {
    fn new(rho: V3, rhod: V3, n: f64, h: f64) -> Self {
        HcwPlant { x: [rho[0], rho[1], rho[2], rhod[0], rhod[1], rhod[2]], n, phi: hcw_stm(n, h), k: 0 }
    }
}

impl Plant for HcwPlant {
    fn k(&self) -> usize {
        self.k
    }
    fn rel(&self) -> (V3, V3) {
        ([self.x[0], self.x[1], self.x[2]], [self.x[3], self.x[4], self.x[5]])
    }
    fn mean_motion(&self) -> f64 {
        self.n
    }
    fn apply(&mut self, dv: V3) {
        for i in 0..3 {
            self.x[3 + i] += dv[i];
        }
    }
    fn step(&mut self) {
        let mut y = [0.0; 6];
        for (i, row) in self.phi.iter().enumerate() {
            let mut s = 0.0;
            for j in 0..6 {
                s += row[j] * self.x[j];
            }
            y[i] = s;
        }
        self.x = y;
        self.k += 1;
    }
    fn state(&self) -> (V3, V3) {
        self.rel()
    }
}

struct NlPlant<'a> {
    tr: &'a Trajectory,
    rc: V3,
    vc: V3,
    h: f64,
    fm: &'a ForceModel,
    ert: &'a EarthRotationTable,
    k: usize,
}

impl Plant for NlPlant<'_> {
    fn k(&self) -> usize {
        self.k
    }
    fn rel(&self) -> (V3, V3) {
        relative_rtn(self.tr.r[self.k], self.tr.v[self.k], self.rc, self.vc)
    }
    fn mean_motion(&self) -> f64 {
        mean_motion(self.tr.r[self.k], self.tr.v[self.k])
    }
    fn apply(&mut self, dv: V3) {
        let c = rtn_matrix(self.tr.r[self.k], self.tr.v[self.k]);
        let d = mtv(&c, dv);
        self.vc = add(self.vc, [d[0] / 1000.0, d[1] / 1000.0, d[2] / 1000.0]);
    }
    fn step(&mut self) {
        let (r, v) = rk4(self.rc, self.vc, self.k as f64 * self.h, self.h, self.fm, self.ert);
        self.rc = r;
        self.vc = v;
        self.k += 1;
    }
    fn state(&self) -> (V3, V3) {
        (self.rc, self.vc)
    }
}

/// 每節點樣本 (k, 段落, ρ, ρ̇)（脈衝後）
pub type Sample = (usize, usize, V3, V3);

pub struct Ctl {
    pub retarget_s: f64,
    pub deadband_m: Value,
    pub max_burn_ms: Value,
}

pub struct SimOut {
    pub burns: Vec<Value>,
    pub segments: Vec<Value>,
    pub samples: Vec<Sample>,
    pub rec: HashMap<usize, (V3, V3)>,
}

fn f64v(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn v3(v: &Value) -> V3 {
    [f64v(&v[0]), f64v(&v[1]), f64v(&v[2])]
}

fn simulate(plant: &mut dyn Plant, segs: &[Value], nsteps: &[usize], h: f64, ctl: &Ctl, record_nodes: &HashSet<usize>)
    -> Result<SimOut, DesignError> {
    let mut burns: Vec<Value> = Vec::new();
    let mut dvs: Vec<f64> = Vec::new();
    let mut seg_out = Vec::new();
    let mut samples: Vec<Sample> = Vec::new();
    let mut rec = HashMap::new();
    let max_burn = f64v(&ctl.max_burn_ms);
    let db_default = f64v(&ctl.deadband_m);

    let burn = |plant: &mut dyn Plant, burns: &mut Vec<Value>, dvs: &mut Vec<f64>, dv: V3, kind: &str, si: usize| {
        plant.apply(dv);
        let m = norm(dv);
        burns.push(json!({"t_s": plant.k() as f64 * h, "segment": si, "kind": kind, "dv_rtn_ms": dv, "dv_ms": m}));
        dvs.push(m);
    };
    let sample_and_step = |plant: &mut dyn Plant, samples: &mut Vec<Sample>, rec: &mut HashMap<usize, (V3, V3)>, si: usize| {
        let (rho, rhod) = plant.rel();
        samples.push((plant.k(), si, rho, rhod));
        if record_nodes.contains(&plant.k()) {
            rec.insert(plant.k(), plant.state());
        }
        plant.step();
    };

    let mut hold_pt: Option<V3> = None;
    for (si, (seg, &ns)) in segs.iter().zip(nsteps.iter()).enumerate() {
        let (k0, nb0) = (plant.k(), burns.len());
        let typ = seg["type"].as_str().unwrap();
        let mut info = Map::new();
        info.insert("index".into(), json!(si));
        info.insert("type".into(), seg["type"].clone());
        info.insert("label".into(), seg.get("label").cloned().unwrap_or(json!("")));
        info.insert("start_s".into(), json!(k0 as f64 * h));
        info.insert("end_s".into(), json!((k0 + ns) as f64 * h));
        match typ {
            "transfer" => {
                let tgt = v3(&seg["to_rtn_m"]);
                let (rho, rhod) = plant.rel();
                let v0 = hcw_target(rho, tgt, plant.mean_motion(), ns as f64 * h, si)?;
                let dv = sub(v0, rhod);
                if norm(dv) > max_burn {
                    return Err(DesignError { code: "transfer_dv_exceeds", segment: si,
                        detail: json!({"dv_ms": norm(dv), "max_burn_ms": ctl.max_burn_ms}) });
                }
                burn(plant, &mut burns, &mut dvs, dv, "transfer_start", si);
                for _ in 0..ns {
                    sample_and_step(plant, &mut samples, &mut rec, si);
                }
                let (rho, rhod) = plant.rel();
                info.insert("target_rtn_m".into(), json!(tgt));
                info.insert("arrival_error_m".into(), json!(norm(sub(rho, tgt))));
                burn(plant, &mut burns, &mut dvs, scale(rhod, -1.0), "transfer_arrival", si);
                hold_pt = Some(tgt);
            }
            "hold" => {
                let p = if seg.get("at_rtn_m").is_some() {
                    v3(&seg["at_rtn_m"])
                } else {
                    hold_pt.unwrap_or_else(|| plant.rel().0)
                };
                let db = seg.get("deadband_m").map(f64v).unwrap_or(db_default);
                let rsteps = steps(ctl.retarget_s, h);
                let mut corr_end: Option<usize> = None;
                for j in 0..ns {
                    let (rho, rhod) = plant.rel();
                    if corr_end.is_some() && Some(plant.k()) == corr_end {
                        burn(plant, &mut burns, &mut dvs, neg(rhod), "deadband_null", si);
                        corr_end = None;
                    } else if corr_end.is_none() && norm(sub(rho, p)) > db {
                        let nr = rsteps.min(ns - j);
                        if nr >= 2 {
                            let dv = sub(hcw_target(rho, p, plant.mean_motion(), nr as f64 * h, si)?, rhod);
                            if norm(dv) <= max_burn {
                                burn(plant, &mut burns, &mut dvs, dv, "deadband_start", si);
                                corr_end = Some(plant.k() + nr);
                            }
                        }
                    }
                    sample_and_step(plant, &mut samples, &mut rec, si);
                }
                if corr_end.is_some() && Some(plant.k()) == corr_end {
                    let rhod = plant.rel().1;
                    burn(plant, &mut burns, &mut dvs, neg(rhod), "deadband_null", si);
                }
                info.insert("hold_rtn_m".into(), json!(p));
                info.insert("deadband_m".into(), json!(db));
                hold_pt = Some(p);
            }
            _ => {
                let (rho, rhod) = plant.rel();
                let n = plant.mean_motion();
                let start_rho = rho;
                burn(plant, &mut burns, &mut dvs, sub([n * rho[1] / 2.0, -2.0 * n * rho[0], 0.0], rhod), "fly_around_start", si);
                for _ in 0..ns {
                    sample_and_step(plant, &mut samples, &mut rec, si);
                }
                let (rho, rhod) = plant.rel();
                info.insert("target_rtn_m".into(), json!(start_rho));
                info.insert("arrival_error_m".into(), json!(norm(sub(rho, start_rho))));
                burn(plant, &mut burns, &mut dvs, neg(rhod), "fly_around_end", si);
                hold_pt = Some(start_rho);
            }
        }
        info.insert("n_burns".into(), json!(burns.len() - nb0));
        let mut s = 0.0;
        for d in &dvs[nb0..] {
            s += d;
        }
        info.insert("dv_ms".into(), json!(s));
        seg_out.push(Value::Object(info));
    }
    let (rho, rhod) = plant.rel();
    samples.push((plant.k(), segs.len() - 1, rho, rhod));
    if record_nodes.contains(&plant.k()) {
        rec.insert(plant.k(), plant.state());
    }
    Ok(SimOut { burns, segments: seg_out, samples, rec })
}

fn neg(a: V3) -> V3 {
    [-a[0], -a[1], -a[2]]
}

/// 違規以 (type, segment) 聚合；回傳 (violations, min_d, max_c)
fn monitor(samples: &[Sample], segs: &[Value], lim: &Map<String, Value>, h: f64) -> (Vec<Value>, f64, f64) {
    struct Viol {
        kind: &'static str,
        si: usize,
        first: f64,
        last: f64,
        count: usize,
        worst: f64,
        limit: Value,
    }
    let ax = axis(lim["corridor_axis"].as_str().unwrap());
    let mut viol: Vec<Viol> = Vec::new();
    let (mut min_d, mut max_c) = (f64::INFINITY, f64::NEG_INFINITY);
    let (ko, mc, cr, rr) = (f64v(&lim["keep_out_m"]), f64v(&lim["max_closing_ms"]), f64v(&lim["corridor_range_m"]),
        f64v(&lim["closing_range_m"]));
    let half = f64v(&lim["corridor_half_angle_deg"]);
    let mut add_v = |kind: &'static str, si: usize, k: usize, val: f64, limit: &Value, lower_worse: bool| {
        if let Some(v) = viol.iter_mut().find(|v| v.kind == kind && v.si == si) {
            v.last = k as f64 * h;
            v.count += 1;
            if (lower_worse && val < v.worst) || (!lower_worse && val > v.worst) {
                v.worst = val;
            }
        } else {
            viol.push(Viol { kind, si, first: k as f64 * h, last: k as f64 * h, count: 1, worst: val, limit: limit.clone() });
        }
    };
    for &(k, si, rho, rhod) in samples {
        let d = norm(rho);
        let c = if d > 0.0 { -dot(rho, rhod) / d } else { 0.0 };
        min_d = min_d.min(d);
        max_c = max_c.max(c);
        if d < ko {
            add_v("keep_out", si, k, d, &lim["keep_out_m"], true);
        }
        if d < rr && c > mc {
            add_v("closing_speed", si, k, c, &lim["max_closing_ms"], false);
        }
        let seg = &segs[si];
        let corr = seg.get("corridor").and_then(Value::as_bool).unwrap_or(seg["type"] != "fly_around");
        if corr && d < cr && d > 0.0 {
            let ang = (dot(rho, ax) / d).clamp(-1.0, 1.0).acos() * (180.0 / std::f64::consts::PI);
            if ang > half {
                add_v("corridor", si, k, ang, &lim["corridor_half_angle_deg"], false);
            }
        }
    }
    viol.sort_by(|a, b| a.first.partial_cmp(&b.first).unwrap().then_with(|| a.kind.cmp(b.kind)));
    let out = viol.into_iter().map(|v| json!({"type": v.kind, "segment": v.si, "first_t_s": v.first, "last_t_s": v.last,
        "count": v.count, "worst": v.worst, "limit": v.limit})).collect();
    (out, min_d, max_c)
}

fn timeline(samples: &[Sample], h: f64) -> Value {
    let n = samples.len();
    let stride = ((n as f64 / RPO_TIMELINE_MAX as f64).ceil() as usize).max(1);
    let mut idx: Vec<usize> = (0..n).filter(|i| i % stride == 0).collect();
    if *idx.last().unwrap() != n - 1 {
        idx.push(n - 1);
    }
    let (mut t, mut rtn, mut dist, mut clo, mut sg) = (vec![], vec![], vec![], vec![], vec![]);
    for i in idx {
        let (k, si, rho, rhod) = samples[i];
        let d = norm(rho);
        t.push(json!(k as f64 * h));
        rtn.push(json!([py_round(rho[0], 3), py_round(rho[1], 3), py_round(rho[2], 3)]));
        dist.push(json!(py_round(d, 3)));
        clo.push(json!(py_round(if d > 0.0 { -dot(rho, rhod) / d } else { 0.0 }, 5)));
        sg.push(json!(si));
    }
    json!({"t_s": t, "rtn_m": rtn, "dist_m": dist, "closing_ms": clo, "segment": sg})
}

/// 5 種執行誤差情境（3σ）：nominal、mag_plus、mag_minus、point_1、point_2
pub fn perturbations(dv: V3, mag_frac: f64, point_deg: f64) -> [(&'static str, V3); 5] {
    let m = norm(dv);
    let u = [dv[0] / m, dv[1] / m, dv[2] / m];
    let mut e1 = cross(u, [1.0, 0.0, 0.0]);
    if norm(e1) < 1e-6 {
        e1 = cross(u, [0.0, 0.0, 1.0]);
    }
    let ne = norm(e1);
    let e1 = [e1[0] / ne, e1[1] / ne, e1[2] / ne];
    let e2 = cross(u, e1);
    let (sm, th) = (3.0 * mag_frac, 3.0 * point_deg * (std::f64::consts::PI / 180.0));
    let (ct, st) = (th.cos(), th.sin());
    let pt = |e: V3| [m * (ct * u[0] + st * e[0]), m * (ct * u[1] + st * e[1]), m * (ct * u[2] + st * e[2])];
    [("nominal", dv), ("mag_plus", scale(dv, 1.0 + sm)), ("mag_minus", scale(dv, 1.0 - sm)), ("point_1", pt(e1)), ("point_2", pt(e2))]
}

/// HCW（含常數差分加速度 a_rel 的受迫解）下單一撤離脈衝的最小 Δv 搜尋；5 種執行誤差情境都須達標
#[allow(clippy::too_many_arguments)]
pub fn abort_search(rho: V3, rhod: V3, n: f64, keep_out: f64, horizon_s: f64, margin: f64, dv_max: f64, a_rel: V3,
                    mag_frac: f64, point_deg: f64) -> Map<String, Value> {
    let m_samp = py_floordiv(horizon_s, RPO_ABORT_SAMPLE_S) as usize + 1;
    let mut base: Vec<V3> = Vec::with_capacity(m_samp);
    let mut g: Vec<[[f64; 3]; 3]> = Vec::with_capacity(m_samp);
    for j in 0..m_samp {
        let t = j as f64 * RPO_ABORT_SAMPLE_S;
        let p = hcw_stm(n, t);
        base.push(add(add(mv(&block(&p, 0, 0), rho), mv(&block(&p, 0, 3), rhod)), hcw_forced(n, t, a_rel)));
        g.push(block(&p, 0, 3));
    }
    let d0 = norm(rho);
    let req = keep_out.max((margin * keep_out).min(0.95 * d0));
    let esc = (2.0 * margin * keep_out).max(RPO_ABORT_ESCAPE_FACTOR * d0);
    let (lo, nn) = (RPO_ABORT_MIN_DV_MS, RPO_ABORT_N_DV);
    let mags: Vec<f64> = (0..nn).map(|i| lo * (dv_max / lo).powf(i as f64 / (nn - 1) as f64)).collect();
    let dirs = abort_dirs();
    let mut best: Option<(f64, V3, f64, f64, f64)> = None;
    let out = |dv: V3, m: f64, md: f64, de: f64, safe: bool| -> Map<String, Value> {
        let Value::Object(o) = json!({"dv_rtn_ms": dv, "dv_ms": m, "hcw_min_dist_m": md, "hcw_end_dist_m": de,
            "required_m": req, "escape_m": esc, "hcw_safe": safe}) else { unreachable!() };
        o
    };
    for &m in &mags {
        for u in &dirs {
            let dv = scale(*u, m);
            let (mut md, mut de) = (f64::INFINITY, f64::INFINITY);
            for (_label, dvp) in perturbations(dv, mag_frac, point_deg) {
                let mut mn = f64::INFINITY;
                let mut last = 0.0;
                for (b, gj) in base.iter().zip(g.iter()) {
                    let d = norm(add(*b, mv(gj, dvp)));
                    mn = mn.min(d);
                    last = d;
                }
                md = md.min(mn);
                de = de.min(last);
            }
            if md >= req && de >= esc {
                return out(dv, m, md, de, true);
            }
            let score = (md / req).min(de / esc);
            if best.as_ref().map(|b| score > b.0).unwrap_or(true) {
                best = Some((score, dv, m, md, de));
            }
        }
    }
    let b = best.unwrap();
    out(b.1, b.2, b.3, b.4, false)
}

fn invalid(codes: &[&str], msgs: &[&str]) -> Value {
    json!({"status": "invalid_scenario", "validation": {"ok": false, "codes": codes, "messages": msgs}})
}

fn obj_map(v: Option<&Value>) -> Map<String, Value> {
    v.and_then(Value::as_object).cloned().unwrap_or_default()
}

/// Python 的真值判斷
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|x| x != 0.0).unwrap_or(true),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(m)) => !m.is_empty(),
    }
}

pub fn run(sc: &Value, eop: &Eop) -> anyhow::Result<Value> {
    let t_wall = Instant::now();
    let val = validate(sc);
    if !val.ok {
        return Ok(json!({"status": "invalid_scenario", "validation": val.to_json()}));
    }
    let rpo = sc.get("rpo");
    if !truthy(rpo) {
        return Ok(invalid(&["E_RPO_MISSING"], &["需要 rpo"]));
    }
    let rpo = rpo.unwrap();
    let start = UtcTime::parse(sc["screening"]["start"].as_str().unwrap())?;
    let h = sc["screening"].get("step_s").and_then(Value::as_f64).filter(|x| *x != 0.0).unwrap_or(RK4_STEP_LEO_S);
    let zonal = sc["force_model"]["zonal"].as_bool().unwrap();
    let drag = sc["force_model"]["drag"].as_bool().unwrap();
    let objs = sc["objects"].as_array().unwrap();
    let find = |role: &str| objs.iter().rev().find(|o| o["role"] == role).unwrap();
    let (tgt_o, ch_o) = (find("primary"), find("secondary"));
    let rl = obj_map(sc.get("rpo_limits"));
    let mut lim = rpo_limits_default();
    for (k, v) in &rl {
        if k != "comm_loss" {
            lim.insert(k.clone(), v.clone());
        }
    }
    let mut comm = rpo_comm_loss_default();
    for (k, v) in obj_map(rl.get("comm_loss")) {
        comm.insert(k, v);
    }
    let control = obj_map(rpo.get("control"));
    let ctl = Ctl {
        retarget_s: control.get("retarget_s").map(f64v).unwrap_or(RPO_RETARGET_S),
        deadband_m: control.get("deadband_m").cloned().unwrap_or(json!(RPO_DEADBAND_M)),
        max_burn_ms: control.get("max_burn_ms").cloned().unwrap_or(json!(RPO_MAX_BURN_MS)),
    };
    let ab = obj_map(rpo.get("abort"));
    let ee = obj_map(ab.get("execution_error"));
    let gf = |m: &Map<String, Value>, k: &str, d: f64| m.get(k).map(f64v).unwrap_or(d);
    let ab_update = gf(&ab, "update_s", RPO_ABORT_UPDATE_S);
    let ab_max_dv = gf(&ab, "max_dv_ms", RPO_ABORT_MAX_DV_MS);
    let ab_margin = gf(&ab, "margin", RPO_ABORT_MARGIN);
    let mag_frac = gf(&ee, "mag_frac_sigma", RPO_EXEC_MAG_FRAC);
    let point_deg = gf(&ee, "point_deg_sigma", RPO_EXEC_POINT_DEG);

    // 初始狀態（τ = 0）
    let mut t_lo: f64 = 0.0;
    for o in objs {
        if o["ephemeris"]["type"] == "state" {
            let te = seconds_between(&start, &UtcTime::parse(o["ephemeris"]["epoch"].as_str().unwrap())?);
            if te > 0.0 {
                return Ok(invalid(&["E_STATE_EPOCH_AFTER_START"], &[]));
            }
            t_lo = t_lo.min(te);
        }
    }
    let fm_t = object_force_model(tgt_o, zonal, drag);
    let fm_c = object_force_model(ch_o, zonal, drag);
    let segs: Vec<Value> = rpo["sequence"].as_array().unwrap().clone();
    let ert0 = EarthRotationTable::new(start, t_lo - 1.0, 1.0, eop)?;
    let state_at0 = |o: &Value, fm: &ForceModel| -> anyhow::Result<(V3, V3)> {
        let (r, v, t0) = initial_state_gcrf(o, &start, eop)?;
        if t0 < 0.0 {
            return Ok(NumericalEphemeris::new(propagate(r, v, t0, 0.0, h, fm, Some(&ert0))).rv(0.0));
        }
        Ok((r, v))
    };
    let (rt0, vt0) = state_at0(tgt_o, &fm_t)?;
    let (rc0, vc0) = if ch_o["ephemeris"]["type"] == "rtn_offset" {
        rtn_offset_to_gcrf(rt0, vt0, v3(&ch_o["ephemeris"]["r_m"]), v3(&ch_o["ephemeris"]["v_ms"]))
    } else {
        state_at0(ch_o, &fm_c)?
    };
    let n0 = mean_motion(rt0, vt0);
    let period0 = 2.0 * std::f64::consts::PI / n0;
    let nsteps: Vec<usize> = segs.iter().map(|s| {
        if s["type"] != "fly_around" { steps(f64v(&s["duration_s"]), h) } else { steps(f64v(&s["revolutions"]) * period0, h) }
    }).collect();
    let n_seq: usize = nsteps.iter().sum();
    let safe_orbits = f64v(&comm["safe_orbits"]);
    let trigger_s = f64v(&comm["trigger_s"]);
    let h_steps = (safe_orbits * period0 / h - 1e-9).ceil() as usize;
    let trig_steps = (trigger_s / h + 0.5).floor() as usize;
    let fault = rpo.get("fault").filter(|f| truthy(Some(f)));
    let k_f = fault.map(|f| (f64v(&f["comm_loss_start_s"]) / h + 0.5).floor() as usize);
    let n_tot = (n_seq + h_steps).max(k_f.map(|k| k + trig_steps + h_steps).unwrap_or(0)) + 1;
    let ert = EarthRotationTable::new(start, t_lo - 1.0, n_tot as f64 * h + 2.0 * h + 1.0, eop)?;
    let tr = propagate(rt0, vt0, 0.0, n_tot as f64 * h, h, &fm_t, Some(&ert));

    let mut lim_out = lim.clone();
    lim_out.insert("comm_loss".into(), Value::Object(comm.clone()));
    let mut info = Map::new();
    info.insert("scenario_id".into(), sc["id"].clone());
    info.insert("start".into(), json!(start.iso()));
    info.insert("step_s".into(), json!(h));
    info.insert("objects".into(), json!({
        "target": {"name": tgt_o["name"], "norad_id": tgt_o.get("norad_id").cloned().unwrap_or(Value::Null)},
        "chaser": {"name": ch_o["name"], "norad_id": ch_o.get("norad_id").cloned().unwrap_or(Value::Null)}}));
    info.insert("limits".into(), Value::Object(lim_out));
    let design_err = |ex: DesignError, stage: &str| -> Value {
        let mut o = info.clone();
        o.insert("status".into(), json!("invalid_design"));
        o.insert("reason".into(), json!(ex.code));
        o.insert("segment".into(), json!(ex.segment));
        o.insert("detail".into(), ex.detail);
        o.insert("stage".into(), json!(stage));
        Value::Object(o)
    };

    // HCW 設計
    let (rho0, rhod0) = relative_rtn(rt0, vt0, rc0, vc0);
    let mut hp = HcwPlant::new(rho0, rhod0, n0, h);
    let design = match simulate(&mut hp, &segs, &nsteps, h, &ctl, &HashSet::new()) {
        Ok(d) => d,
        Err(ex) => return Ok(design_err(ex, "hcw_design")),
    };
    let (d_viol, d_min, _) = monitor(&design.samples, &segs, &lim, h);

    // 非線性閉迴路重播
    let upd = steps(ab_update, h);
    let seg_starts: Vec<usize> = (0..nsteps.len()).map(|i| nsteps[..i].iter().sum()).collect();
    let mut an: BTreeSet<usize> = (0..=n_seq).step_by(upd).collect();
    an.extend(seg_starts.iter().copied());
    let abort_nodes: Vec<usize> = an.into_iter().collect();
    let mut rec_nodes: HashSet<usize> = abort_nodes.iter().copied().collect();
    if let Some(k) = k_f.filter(|k| *k <= n_seq) {
        rec_nodes.insert(k);
    }
    let mut np = NlPlant { tr: &tr, rc: rc0, vc: vc0, h, fm: &fm_c, ert: &ert, k: 0 };
    let replay = match simulate(&mut np, &segs, &nsteps, h, &ctl, &rec_nodes) {
        Ok(d) => d,
        Err(ex) => return Ok(design_err(ex, "nonlinear_replay")),
    };
    let (viol, min_d, max_c) = monitor(&replay.samples, &segs, &lim, h);
    let ko = f64v(&lim["keep_out_m"]);

    let verify = |k: usize, rc: V3, vc: V3, dv: V3, record: bool| -> (Vec<f64>, Option<Vec<Value>>) {
        let (rt, vt) = (tr.r[k], tr.v[k]);
        let c = rtn_matrix(rt, vt);
        let mut mins = Vec::with_capacity(5);
        let mut path = None;
        for (label, dvp) in perturbations(dv, mag_frac, point_deg) {
            let d = mtv(&c, dvp);
            let (mut r, mut v) = (rc, add(vc, [d[0] / 1000.0, d[1] / 1000.0, d[2] / 1000.0]));
            let mut md = norm(sub(r, rt)) * 1000.0;
            let mut pts: Option<Vec<Value>> = if record && label == "nominal" { Some(vec![]) } else { None };
            let stride = (h_steps / 300).max(1);
            for j in 1..=h_steps {
                (r, v) = rk4(r, v, (k + j - 1) as f64 * h, h, &fm_c, &ert);
                md = md.min(norm(sub(r, tr.r[k + j])) * 1000.0);
                if let Some(p) = pts.as_mut() {
                    if j % stride == 0 {
                        let q = relative_rtn(tr.r[k + j], tr.v[k + j], r, v).0;
                        p.push(json!([py_round(q[0], 3), py_round(q[1], 3), py_round(q[2], 3)]));
                    }
                }
            }
            mins.push(md);
            if pts.is_some() {
                path = pts;
            }
        }
        (mins, path)
    };
    let fmin = |a: &[f64]| a.iter().copied().fold(f64::INFINITY, f64::min);

    let mut entries: Vec<Value> = Vec::new();
    let mut entry_dv: Vec<(f64, V3, Value)> = Vec::new();
    for &k in &abort_nodes {
        let (rc, vc) = replay.rec[&k];
        let (rho, rhod) = relative_rtn(tr.r[k], tr.v[k], rc, vc);
        let a_rel = drag_rel_rtn(&fm_t, &fm_c, tr.r[k], tr.v[k], rc, vc, &ert.at(k as f64 * h));
        let mut s = abort_search(rho, rhod, mean_motion(tr.r[k], tr.v[k]), ko, safe_orbits * period0, ab_margin, ab_max_dv,
            a_rel, mag_frac, point_deg);
        s.insert("a_rel_rtn_ms2".into(), json!(a_rel));
        let dv = v3(&s["dv_rtn_ms"]);
        let (mins, _) = verify(k, rc, vc, dv, false);
        let worst = fmin(&mins);
        let safe = s["hcw_safe"].as_bool().unwrap() && worst >= ko;
        let mut e = Map::new();
        e.insert("t_s".into(), json!(k as f64 * h));
        e.insert("range_m".into(), json!(norm(rho)));
        entry_dv.push((k as f64 * h, dv, s["dv_ms"].clone()));
        e.extend(s);
        e.insert("nl_min_dist_m".into(), json!(mins));
        e.insert("nl_worst_m".into(), json!(worst));
        e.insert("safe".into(), json!(safe));
        entries.push(Value::Object(e));
    }
    let all_safe = entries.iter().all(|e| e["safe"] == true);

    let mut fault_out = Value::Null;
    if let (Some(f), Some(k_f)) = (fault, k_f) {
        if k_f > n_seq {
            fault_out = json!({"status": "not_applicable", "comm_loss_start_s": f["comm_loss_start_s"],
                "note": "通訊中斷時刻晚於控制序列結束"});
        } else {
            let ent = entry_dv.iter().filter(|e| e.0 <= k_f as f64 * h + 1e-9).last().unwrap();
            let (mut rc, mut vc) = replay.rec[&k_f];
            let mut coast_min = norm(sub(rc, tr.r[k_f])) * 1000.0;
            let mut coast_path = Vec::new();
            for j in 1..=trig_steps {
                (rc, vc) = rk4(rc, vc, (k_f + j - 1) as f64 * h, h, &fm_c, &ert);
                coast_min = coast_min.min(norm(sub(rc, tr.r[k_f + j])) * 1000.0);
                if j % (trig_steps / 60).max(1) == 0 {
                    let q = relative_rtn(tr.r[k_f + j], tr.v[k_f + j], rc, vc).0;
                    coast_path.push(json!([py_round(q[0], 3), py_round(q[1], 3), py_round(q[2], 3)]));
                }
            }
            let k_tr = k_f + trig_steps;
            let (mins, path) = verify(k_tr, rc, vc, ent.1, true);
            let worst = fmin(&mins);
            fault_out = json!({"status": "evaluated", "comm_loss_start_s": k_f as f64 * h, "trigger_t_s": k_tr as f64 * h,
                "stored_entry_t_s": ent.0, "dv_rtn_ms": ent.1, "dv_ms": ent.2,
                "coast_min_dist_m": coast_min, "nl_min_dist_m": mins, "nl_worst_m": worst,
                "safe": coast_min >= ko && worst >= ko,
                "coast_path_rtn_m": coast_path, "abort_path_rtn_m": path});
        }
    }

    // HCW 適用前提
    let max_range = replay.samples.iter().map(|s| norm(s.2)).fold(f64::NEG_INFINITY, f64::max);
    let e0 = ecc(rt0, vt0);
    let frac = max_range / 1000.0 / norm(rt0);
    let applicable = e0 < RPO_HCW_ECC_MAX && frac < RPO_HCW_RANGE_FRAC_MAX;
    let appl = json!({"target_eccentricity": e0, "max_range_m": max_range, "range_frac": frac, "hcw_applicable": applicable,
        "thresholds": {"eccentricity": RPO_HCW_ECC_MAX, "range_frac": RPO_HCW_RANGE_FRAC_MAX}});

    let fault_eval = fault_out.get("status").map(|s| s == "evaluated").unwrap_or(false);
    let mut reasons: Vec<&str> = Vec::new();
    if !viol.is_empty() {
        reasons.push("nominal_violations");
    }
    if !all_safe {
        reasons.push("abort_unsafe");
    }
    if fault_eval && fault_out["safe"] == false {
        reasons.push("fault_abort_unsafe");
    }
    let sum = |b: &[Value]| {
        let mut s = 0.0;
        for x in b {
            s += f64v(&x["dv_ms"]);
        }
        s
    };
    let total_dv = sum(&replay.burns);
    let mass = ch_o.get("mass_kg");
    let isp = ch_o.get("propulsion").and_then(|p| p.get("isp_s"));
    let propellant = if truthy(mass) && truthy(isp) {
        json!(f64v(mass.unwrap()) * (1.0 - (-total_dv / (f64v(isp.unwrap()) * MAN_G0_MS2)).exp()))
    } else {
        Value::Null
    };
    let mut notes = vec!["執行模型：理想脈衝（有限推力未模擬）", "導航：完美導航（控制律讀取真實相對狀態）",
        "非線性重播為模型間交叉驗證，不等同實際軌道真值"];
    if lim.contains_key("fov_deg") {
        notes.push("fov_deg 未模擬（v1 假設感測器持續指向目標）");
    }
    if !applicable {
        notes.push("超出 HCW 適用前提（目標星偏心率或相對距離過大），設計脈衝誤差可能偏大");
    }
    let n_entries = entries.len();
    let n_safe = entries.iter().filter(|e| e["safe"] == true).count();
    let fault_safe = if fault_eval { fault_out["safe"].clone() } else { Value::Null };
    let n_viol = viol.len();

    let mut o = info;
    o.insert("status".into(), json!(if reasons.is_empty() { "pass" } else { "fail" }));
    o.insert("reasons".into(), json!(reasons));
    o.insert("applicability".into(), appl);
    o.insert("design".into(), json!({"model": "HCW", "n_rad_s": n0, "burns": design.burns, "segments": design.segments,
        "total_dv_ms": sum(&design.burns), "min_dist_m": d_min, "violations": d_viol,
        "timeline": timeline(&design.samples, h)}));
    o.insert("replay".into(), json!({
        "model": {"integrator": "RK4", "step_s": h, "target_force_model": fm_t.describe(), "chaser_force_model": fm_c.describe()},
        "burns": replay.burns, "segments": replay.segments, "total_dv_ms": total_dv, "propellant_kg": propellant,
        "min_dist_m": min_d, "max_closing_ms": max_c, "violations": viol, "timeline": timeline(&replay.samples, h)}));
    o.insert("abort".into(), json!({"strategy": comm["strategy"], "trigger_s": comm["trigger_s"], "safe_orbits": comm["safe_orbits"],
        "update_s": upd as f64 * h, "margin": ab_margin, "max_dv_ms": ab_max_dv,
        "execution_error": {"mag_frac_sigma": mag_frac, "point_deg_sigma": point_deg, "cases": "nominal, ±3σ 大小, 兩方向 3σ 指向"},
        "entries": entries, "all_safe": all_safe}));
    o.insert("fault".into(), fault_out);
    o.insert("checks".into(), json!({"nominal_violations": n_viol, "abort_entries": n_entries, "abort_entries_safe": n_safe,
        "fault_abort_safe": fault_safe}));
    o.insert("notes".into(), json!(notes));
    o.insert("provenance".into(), json!({"code_version": CODE_VERSION, "constants_version": CONSTANTS_VERSION, "eop": eop.version(),
        "frames": {"propagation": "GCRF", "relative": "target RTN (x=R, y=T, z=N), rotating-frame velocity"}}));
    o.insert("timing".into(), json!({"elapsed_s": t_wall.elapsed().as_secs_f64()}));
    Ok(Value::Object(o))
}
