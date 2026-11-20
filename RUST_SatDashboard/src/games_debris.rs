//! 太空小遊戲「碎片連鎖」：NASA 標準解體模型（EVOLVE 4.0／Johnson et al. 2001）＋ J2 長期項＋大氣阻力衰減
//! ＋以 KD-tree 快照估計碰撞機率的蒙地卡羅連鎖。
//!
//! - 解體：碎片數 N(>Lc) = 6·S·Lc^−1.6（爆炸）或 0.1·M^0.75·Lc^−1.71（碰撞），由使用者指定的碎片數反推 Lc；
//!   尺寸依冪律抽樣，面積質量比依模型的（雙）常態分布，Δv 依 log10(Δv) ~ N(μ(A/M), 0.4)，方向等向；
//!   質量縮放到總和等於母體質量，Δv 扣掉質量加權平均（動量守恆）。
//! - 傳播：克卜勒根數＋J2 長期漂移；碎片每一步依 A/M 與近地點大氣密度（Vallado 指數模型）降低半長軸，
//!   近地點 < 120 km 視為再入。目錄物件以 t0 的 SGP4 狀態轉成根數後同樣用 J2 長期項（不含阻力）。
//! - 碰撞：每一步取幾個快照，以碎片為查詢點找出 d 以內的物件；配對碰撞率 = 相對速度 ÷ (4d/3) × (R₁+R₂)²/d²，
//!   乘上時間步長與加速倍率得到期望值 λ，以 1−e^−λ 擲骰。撞上時以能量質量比 40 J/g 判斷是否完全解體，
//!   再用碰撞模型產生下一代碎片。

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use chrono::{DateTime, Utc};
use kiddo::immutable::float::kdtree::ImmutableKdTree;
use kiddo::SquaredEuclidean;
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::index::SatInfo;
use crate::physics::R_EARTH_KM;
use crate::state::AppState;

const MU: f64 = 398600.4418;
const J2: f64 = 1.08262668e-3;
const TAU: f64 = std::f64::consts::TAU;
const MAX_FRAGS: usize = 30_000;
const PER_EVENT_MAX: f64 = 600.0;
const SCREEN_D: f64 = 50.0;

type V3 = [f64; 3];
fn norm(a: &V3) -> f64 { (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]).sqrt() }
fn dot(a: &V3, b: &V3) -> f64 { a[0] * b[0] + a[1] * b[1] + a[2] * b[2] }
fn cross(a: &V3, b: &V3) -> V3 { [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] }
fn sub(a: &V3, b: &V3) -> V3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }

// ── 亂數（SplitMix64，可重現）────────────────────────────────────────────
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        ((z ^ (z >> 31)) >> 11) as f64 / (1u64 << 53) as f64
    }
    fn normal(&mut self) -> f64 {
        let u1 = self.next().max(1e-300);
        let u2 = self.next();
        (-2.0 * u1.ln()).sqrt() * (TAU * u2).cos()
    }
    fn dir(&mut self) -> V3 {
        let z = 2.0 * self.next() - 1.0;
        let t = TAU * self.next();
        let r = (1.0 - z * z).sqrt();
        [r * t.cos(), r * t.sin(), z]
    }
}

// ── 克卜勒根數＋J2 長期項 ────────────────────────────────────────────────
#[derive(Clone)]
struct El {
    a: f64, e: f64, i: f64, raan: f64, argp: f64, m0: f64, t_ref: f64,
    raan_dot: f64, argp_dot: f64, m_dot: f64,
}

impl El {
    fn rates(&mut self) {
        let n = (MU / self.a.powi(3)).sqrt();
        let p = self.a * (1.0 - self.e * self.e);
        let k = 1.5 * J2 * (R_EARTH_KM / p).powi(2) * n;
        let si2 = self.i.sin().powi(2);
        self.raan_dot = -k * self.i.cos();
        self.argp_dot = k * (2.0 - 2.5 * si2);
        self.m_dot = n + k * (1.0 - self.e * self.e).sqrt() * (1.0 - 1.5 * si2);
    }
    fn from_rv(r: &V3, v: &V3, t: f64) -> Option<El> {
        let rn = norm(r);
        let h = cross(r, v);
        let hn = norm(&h);
        let en = dot(v, v) / 2.0 - MU / rn;
        if en >= 0.0 || hn < 1e-6 {
            return None;
        }
        let a = -MU / (2.0 * en);
        let ev = {
            let vxh = cross(v, &h);
            [vxh[0] / MU - r[0] / rn, vxh[1] / MU - r[1] / rn, vxh[2] / MU - r[2] / rn]
        };
        let e = norm(&ev).min(0.999);
        let i = (h[2] / hn).clamp(-1.0, 1.0).acos();
        let nv = [-h[1], h[0], 0.0];
        let nn = norm(&nv);
        let raan = if nn > 1e-9 { nv[1].atan2(nv[0]).rem_euclid(TAU) } else { 0.0 };
        let argp = if nn > 1e-9 && e > 1e-9 {
            let c = (dot(&nv, &ev) / (nn * e)).clamp(-1.0, 1.0).acos();
            if ev[2] < 0.0 { TAU - c } else { c }
        } else {
            0.0
        };
        let nu = if e > 1e-9 {
            let c = (dot(&ev, r) / (e * rn)).clamp(-1.0, 1.0).acos();
            if dot(r, v) < 0.0 { TAU - c } else { c }
        } else {
            // 圓軌道：從升交點量起的緯度幅角
            let c = if nn > 1e-9 { (dot(&nv, r) / (nn * rn)).clamp(-1.0, 1.0).acos() } else { 0.0 };
            if r[2] < 0.0 { TAU - c } else { c }
        };
        let ea = 2.0 * (((1.0 - e) / (1.0 + e)).sqrt() * (nu / 2.0).tan()).atan();
        let m0 = (ea - e * ea.sin()).rem_euclid(TAU);
        let mut el = El { a, e, i, raan, argp, m0, t_ref: t, raan_dot: 0.0, argp_dot: 0.0, m_dot: 0.0 };
        el.rates();
        Some(el)
    }
    /// 時刻 t（秒）的位置、速度（慣性座標，km、km/s）
    fn rv(&self, t: f64) -> (V3, V3) {
        let dt = t - self.t_ref;
        let m = (self.m0 + self.m_dot * dt).rem_euclid(TAU);
        let (raan, argp) = (self.raan + self.raan_dot * dt, self.argp + self.argp_dot * dt);
        let e = self.e;
        let mut ea = if e < 0.8 { m } else { std::f64::consts::PI };
        for _ in 0..8 {
            ea -= (ea - e * ea.sin() - m) / (1.0 - e * ea.cos());
        }
        let (se, ce) = ea.sin_cos();
        let b = (1.0 - e * e).sqrt();
        let (xp, yp) = (self.a * (ce - e), self.a * b * se);
        let rr = self.a * (1.0 - e * ce);
        let nmean = (MU / self.a.powi(3)).sqrt();
        let (vxp, vyp) = (-self.a * nmean * self.a / rr * se, self.a * nmean * self.a / rr * b * ce);
        let (so, co) = raan.sin_cos();
        let (sw, cw) = argp.sin_cos();
        let (si, ci) = self.i.sin_cos();
        let p = [co * cw - so * sw * ci, so * cw + co * sw * ci, sw * si];
        let q = [-co * sw - so * cw * ci, -so * sw + co * cw * ci, cw * si];
        (
            [xp * p[0] + yp * q[0], xp * p[1] + yp * q[1], xp * p[2] + yp * q[2]],
            [vxp * p[0] + vyp * q[0], vxp * p[1] + vyp * q[1], vxp * p[2] + vyp * q[2]],
        )
    }
    /// 在時刻 t 重設參考點（之後改 a、e 時保持位置連續）
    fn rebase(&mut self, t: f64) {
        let dt = t - self.t_ref;
        self.m0 = (self.m0 + self.m_dot * dt).rem_euclid(TAU);
        self.raan += self.raan_dot * dt;
        self.argp += self.argp_dot * dt;
        self.t_ref = t;
    }
    fn perigee_alt(&self) -> f64 { self.a * (1.0 - self.e) - R_EARTH_KM }
}

// ── 大氣（Vallado 指數模型）────────────────────────────────────────────
const ATM: [(f64, f64, f64); 19] = [
    (100.0, 5.297e-7, 5.877), (110.0, 9.661e-8, 7.263), (120.0, 2.438e-8, 9.473), (130.0, 8.484e-9, 12.636), (140.0, 3.845e-9, 16.149),
    (150.0, 2.070e-9, 22.523), (180.0, 5.464e-10, 29.740), (200.0, 2.789e-10, 37.105), (250.0, 7.248e-11, 45.546), (300.0, 2.418e-11, 53.628),
    (350.0, 9.518e-12, 53.298), (400.0, 3.725e-12, 58.515), (450.0, 1.585e-12, 60.828), (500.0, 6.967e-13, 63.822), (600.0, 1.454e-13, 71.835),
    (700.0, 3.614e-14, 88.667), (800.0, 1.170e-14, 124.64), (900.0, 5.245e-15, 181.05), (1000.0, 3.019e-15, 268.00),
];
fn atm(h: f64) -> (f64, f64) {
    let mut row = ATM[0];
    for r in ATM.iter() {
        if h >= r.0 {
            row = *r;
        }
    }
    (row.1 * (-(h - row.0) / row.2).exp(), row.2)
}

/// 一個時間步的阻力衰減（King-Hele 近似：近圓軌道均勻衰減；偏心軌道近地點不動、遠地點下降）
fn decay(el: &mut El, am: f64, dt: f64) {
    let hp = el.perigee_alt();
    let (rho, h_km) = atm(hp.max(100.0));
    let a_m = el.a * 1000.0;
    let mut dadt = -2.2 * am * rho * (MU * 1e9 * a_m).sqrt(); // m/s
    let ae = el.a * el.e;
    if ae > h_km {
        dadt *= (h_km / (TAU * ae)).sqrt();
    }
    let da = (dadt * dt / 1000.0).max(-(el.a - R_EARTH_KM - 80.0)); // km
    let a_new = el.a + da;
    if ae > h_km {
        let rp = el.a * (1.0 - el.e);
        el.e = (1.0 - rp / a_new).clamp(0.0, 0.99);
    }
    el.a = a_new;
    el.rates();
}

// ── NASA 標準解體模型 ──────────────────────────────────────────────────
fn am_dist(rng: &mut Rng, l: f64) -> f64 {
    let x = l.log10();
    if l < 0.11 {
        let mu = if x <= -1.75 { -0.3 } else if x < -1.25 { -0.3 - 1.4 * (x + 1.75) } else { -1.0 };
        let sg = if x <= -3.5 { 0.2 } else { 0.2 + 0.1333 * (x + 3.5) };
        return 10f64.powf(mu + sg * rng.normal());
    }
    let alpha = if x <= -1.95 { 0.0 } else if x < 0.55 { 0.3 + 0.4 * (x + 1.2) } else { 1.0 };
    let mu1 = if x <= -1.1 { -0.6 } else if x < 0.0 { -0.6 - 0.318 * (x + 1.1) } else { -0.95 };
    let s1 = if x <= -1.3 { 0.1 } else if x < -0.3 { 0.1 + 0.2 * (x + 1.3) } else { 0.3 };
    let mu2 = if x <= -0.7 { -1.2 } else if x < -0.1 { -1.2 - 1.333 * (x + 0.7) } else { -2.0 };
    let s2 = if x <= -0.5 { 0.5 } else if x < -0.3 { 0.5 - (x + 0.5) } else { 0.3 };
    let lg = if rng.next() < alpha { mu1 + s1 * rng.normal() } else { mu2 + s2 * rng.normal() };
    10f64.powf(lg)
}
fn area(l: f64) -> f64 {
    if l < 0.00167 { 0.540424 * l * l } else { 0.556945 * l.powf(2.0047077) }
}

struct Frag { l: f64, am: f64, mass: f64, dv: V3 }

/// collision=false：爆炸（N=6·Lc^−1.6）；true：碰撞（N=0.1·M^0.75·Lc^−1.71，M 為參考質量）
fn breakup(rng: &mut Rng, n_target: Option<usize>, collision: bool, m_ref: f64, m_total: f64, l_max: f64, cap: f64) -> Vec<Frag> {
    let (k, b) = if collision { (0.1 * m_ref.powf(0.75), 1.71) } else { (6.0, 1.6) };
    let lc = match n_target {
        Some(n) => (n as f64 / k).powf(-1.0 / b),
        None => (cap / k).powf(-1.0 / b).max(0.1),
    };
    let n = (k * lc.powf(-b)).round().clamp(1.0, cap.max(1.0)) as usize;
    let lmax = l_max.max(lc * 1.01);
    let pmin = (lmax / lc).powf(-b);
    let mut fr: Vec<Frag> = (0..n)
        .map(|_| {
            let u = pmin + (1.0 - pmin) * rng.next();
            let l = lc * u.powf(-1.0 / b);
            let am = am_dist(rng, l);
            let mass = area(l) / am;
            let chi = am.log10();
            let mu = if collision { 0.9 * chi + 2.9 } else { 0.2 * chi + 1.85 };
            let dvm = 10f64.powf(mu + 0.4 * rng.normal()) / 1000.0; // km/s
            let d = rng.dir();
            Frag { l, am, mass, dv: [d[0] * dvm, d[1] * dvm, d[2] * dvm] }
        })
        .collect();
    // 質量守恆：縮放到總和 = 母體質量（A/M 跟著改，保持面積）；動量守恆：扣掉質量加權平均 Δv
    let ms: f64 = fr.iter().map(|f| f.mass).sum();
    let s = m_total / ms.max(1e-9);
    for f in fr.iter_mut() {
        f.mass *= s;
        f.am = area(f.l) / f.mass;
    }
    let mut p = [0.0; 3];
    for f in &fr {
        for k in 0..3 {
            p[k] += f.mass * f.dv[k];
        }
    }
    for f in fr.iter_mut() {
        for k in 0..3 {
            f.dv[k] -= p[k] / m_total;
        }
    }
    fr
}

// ── 物件 ────────────────────────────────────────────────────────────────
struct Obj {
    el: El,
    r_km: f64,
    mass: f64,
    am: f64,
    gen: i32, // 0 = 目錄物件；1 = 第一次爆炸的碎片；之後每撞一次 +1
    alive: bool,
    death: f64,
    name: Option<String>,
}

fn cat_props(s: &SatInfo) -> (f64, f64) {
    // (硬體半徑 km, 質量 kg)：DB 沒有尺寸與質量，依類別取代表值
    match s.purpose.as_str() {
        "有效載荷" => (0.0015, 500.0),
        "火箭體" => (0.002, 1500.0),
        "碎片" => (0.0002, 5.0),
        _ => (0.0005, 50.0),
    }
}

#[derive(Deserialize)]
pub struct BreakupReq {
    norad: u32,
    mass_kg: f64,
    n_frag: usize,
    #[serde(default)]
    collision: bool,
    years: f64,
    accel: f64,
    seed: Option<u64>,
}

fn bad(msg: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response()
}

fn sgp4_rv(s: &SatInfo, t: &DateTime<Utc>) -> Option<(V3, V3)> {
    let p = s.prop.as_ref()?;
    let ns = (t.naive_utc() - p.epoch).num_nanoseconds()?;
    let pr = p.constants.propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9)).ok()?;
    let r = pr.position;
    (r.iter().all(|v| v.is_finite()) && norm(&r) > R_EARTH_KM + 100.0).then_some((r, pr.velocity))
}

pub async fn breakup_api(State(st): State<Arc<AppState>>, Json(rq): Json<BreakupReq>) -> Response {
    if !(2..=1000).contains(&rq.n_frag) {
        return bad("碎片數需介於 2 到 1000");
    }
    let years = rq.years.clamp(0.1, 50.0);
    let accel = rq.accel.clamp(1.0, 1e6);
    let mass = rq.mass_kg.clamp(1.0, 1e6);
    tokio::task::spawn_blocking(move || run(&st, &rq, years, accel, mass)).await.unwrap_or_else(|_| bad("計算失敗"))
}

fn run(st: &Arc<AppState>, rq: &BreakupReq, years: f64, accel: f64, mass: f64) -> Response {
    let t_start = std::time::Instant::now();
    let idx = st.index();
    let Some(parent) = idx.sats.get(&rq.norad) else { return bad("目錄中找不到這個 NORAD 編號") };
    let t0 = Utc::now();
    let Some((pr, pv)) = sgp4_rv(parent, &t0) else { return bad("這顆衛星目前無法傳播（TLE 失效或已再入）") };
    let mut rng = Rng(rq.seed.unwrap_or(1) ^ 0x5DEECE66D);

    // 目錄物件（排除母體）轉成 t0 的根數
    let cats: Vec<&SatInfo> = idx.sats.values().filter(|s| s.prop.is_some() && s.norad_id != rq.norad).collect();
    let cat_objs: Vec<Option<Obj>> = cats
        .par_iter()
        .map(|s| {
            let (r, v) = sgp4_rv(s, &t0)?;
            let el = El::from_rv(&r, &v, 0.0)?;
            let (rk, m) = cat_props(s);
            Some(Obj { el, r_km: rk, mass: m, am: 0.0, gen: 0, alive: true, death: -1.0, name: Some(s.name.clone()) })
        })
        .collect();
    let mut objs: Vec<Obj> = cat_objs.into_iter().flatten().collect();
    let n_cat = objs.len();

    let mut events: Vec<Value> = Vec::new();
    let mut frag_out: Vec<Value> = Vec::new();
    let mut capped = false;

    // 新碎片加入物件表；回傳加入數
    let spawn = |objs: &mut Vec<Obj>, frag_out: &mut Vec<Value>, fr: Vec<Frag>, r: V3, v: V3, t: f64, gen: i32, capped: &mut bool| -> usize {
        let mut n = 0;
        for f in fr {
            if objs.len() - n_cat >= MAX_FRAGS {
                *capped = true;
                break;
            }
            let vv = [v[0] + f.dv[0], v[1] + f.dv[1], v[2] + f.dv[2]];
            let Some(el) = El::from_rv(&r, &vv, t) else { continue };
            let reentered = el.perigee_alt() < 100.0;
            let id = objs.len() - n_cat;
            frag_out.push(json!([id, t, gen, f.l, f.am, el.a, el.e, el.i, el.raan, el.argp, el.m0, el.raan_dot, el.argp_dot, el.m_dot]));
            objs.push(Obj { el, r_km: f.l / 2000.0, mass: f.mass, am: f.am, gen, alive: !reentered, death: if reentered { t } else { -1.0 }, name: None });
            n += 1;
        }
        n
    };

    // 第一次解體
    let l_max = (mass / 100.0).cbrt().clamp(0.5, 10.0);
    let fr = breakup(&mut rng, Some(rq.n_frag), rq.collision, mass, mass, l_max, 1000.0);
    let n0 = spawn(&mut objs, &mut frag_out, fr, pr, pv, 0.0, 1, &mut capped);
    events.push(json!({"t": 0.0, "kind": if rq.collision { "collision" } else { "explosion" }, "a": parent.name, "b": null,
        "n_new": n0, "pos": pr, "catastrophic": true, "gen": 1}));

    // 時間步：前 30 天每天、之後依總年數 5／10／30 天；每步 3 個快照（隨機時刻）
    let total_s = years * 365.25 * 86400.0;
    let late_dt: f64 = (if years <= 5.0 { 5.0 } else if years <= 15.0 { 10.0 } else { 30.0 }) * 86400.0;
    let mut t = 0.0;
    let mut series: Vec<Value> = Vec::new();
    let mut expected = 0.0;
    let mut n_coll = 0usize;
    let d2 = SCREEN_D * SCREEN_D;
    let chord = 4.0 * SCREEN_D / 3.0;
    let alive_counts = |objs: &Vec<Obj>| -> Vec<usize> {
        let mut g = vec![0usize; 8];
        for o in objs.iter().skip(n_cat).filter(|o| o.alive) {
            g[(o.gen as usize).min(7)] += 1;
        }
        g
    };
    series.push(json!({"t": 0.0, "alive": alive_counts(&objs), "expected": 0.0, "collisions": 0}));
    while t < total_s {
        let dt: f64 = (if t < 30.0 * 86400.0 { 86400.0 } else { late_dt }).min(total_s - t);
        let ks = 3;
        let mut cand: Vec<(usize, usize, f64, f64)> = Vec::new(); // (i, j, λ, 相對速度)
        for _ in 0..ks {
            let ts = t + rng.next() * dt;
            let states: Vec<Option<(V3, V3)>> = objs.par_iter().map(|o| o.alive.then(|| o.el.rv(ts))).collect();
            let mut pts = Vec::with_capacity(objs.len());
            let mut map = Vec::with_capacity(objs.len());
            for (i, s) in states.iter().enumerate() {
                if let Some((r, _)) = s {
                    pts.push(*r);
                    map.push(i);
                }
            }
            if pts.len() < 2 {
                continue;
            }
            let tree: ImmutableKdTree<f64, u64, 3, 32> = ImmutableKdTree::new_from_slice(&pts);
            let q: Vec<usize> = (0..pts.len()).filter(|&k| map[k] >= n_cat).collect();
            let found: Vec<(usize, usize, f64, f64)> = q
                .par_iter()
                .flat_map_iter(|&ka| {
                    let a = map[ka];
                    let (_, va) = states[a].unwrap();
                    let objs = &objs;
                    let states = &states;
                    let map = &map;
                    tree.within_unsorted::<SquaredEuclidean>(&pts[ka], d2).into_iter().filter_map(move |nn| {
                        let b = map[nn.item as usize];
                        if b == a || (b >= n_cat && b < a) {
                            return None;
                        }
                        let (_, vb) = states[b].unwrap();
                        let vr = norm(&sub(&va, &vb));
                        let rr = objs[a].r_km + objs[b].r_km;
                        let lam = vr / chord * (rr * rr) / d2 * dt / ks as f64 * accel;
                        Some((a, b, lam, vr))
                    })
                })
                .collect();
            cand.extend(found);
        }
        cand.sort_by(|x, y| (x.0, x.1).cmp(&(y.0, y.1)));
        for (a, b, lam, vr) in cand {
            expected += lam;
            if !objs[a].alive || !objs[b].alive || rng.next() >= 1.0 - (-lam).exp() {
                continue;
            }
            // 碰撞：以較重者為目標，能量質量比 > 40 J/g 為完全解體
            let (big, small) = if objs[a].mass >= objs[b].mass { (a, b) } else { (b, a) };
            let (mb, ms) = (objs[big].mass, objs[small].mass);
            let emr = 0.5 * ms * (vr * 1000.0).powi(2) / mb / 1000.0; // J/g
            let cat = emr > 40.0;
            let tc = t + rng.next() * dt;
            let (rb, vb) = objs[big].el.rv(tc);
            let (_, vs) = objs[small].el.rv(tc);
            let m_ref = if cat { mb + ms } else { ms * vr * vr };
            let m_tot = if cat { mb + ms } else { ms + (m_ref / 100.0).min(mb * 0.5) };
            let vcm = if cat {
                [(mb * vb[0] + ms * vs[0]) / (mb + ms), (mb * vb[1] + ms * vs[1]) / (mb + ms), (mb * vb[2] + ms * vs[2]) / (mb + ms)]
            } else {
                vb
            };
            let gen = objs[a].gen.max(objs[b].gen) + 1;
            let lmax = (m_tot / 100.0).cbrt().clamp(0.1, 10.0);
            let fr = breakup(&mut rng, None, true, m_ref, m_tot, lmax, PER_EVENT_MAX);
            objs[small].alive = false;
            objs[small].death = tc;
            if cat {
                objs[big].alive = false;
                objs[big].death = tc;
            } else {
                objs[big].mass -= m_tot - ms;
            }
            let nm = |o: &Obj| o.name.clone().unwrap_or_else(|| format!("第 {} 代碎片", o.gen));
            let n_new = spawn(&mut objs, &mut frag_out, fr, rb, vcm, tc, gen, &mut capped);
            n_coll += 1;
            events.push(json!({"t": tc, "kind": "collision", "a": nm(&objs[big]), "b": nm(&objs[small]),
                "v_rel": vr, "emr": emr, "catastrophic": cat, "n_new": n_new, "pos": rb, "gen": gen}));
        }
        // 阻力衰減與再入（只算碎片）
        let t_end = t + dt;
        objs.par_iter_mut().skip(n_cat).filter(|o| o.alive).for_each(|o| {
            o.el.rebase(t_end);
            decay(&mut o.el, o.am, dt);
            if o.el.perigee_alt() < 120.0 {
                o.alive = false;
                o.death = t_end;
            }
        });
        t = t_end;
        series.push(json!({"t": t, "alive": alive_counts(&objs), "expected": expected, "collisions": n_coll}));
        if t_start.elapsed().as_secs() > 90 {
            break;
        }
    }
    events.sort_by(|x, y| x["t"].as_f64().partial_cmp(&y["t"].as_f64()).unwrap_or(std::cmp::Ordering::Equal));
    let deaths: Vec<f64> = objs.iter().skip(n_cat).map(|o| o.death).collect();
    let alive_end = objs.iter().skip(n_cat).filter(|o| o.alive).count();
    Json(json!({
        "t0": t0.to_rfc3339(),
        "parent": {"norad": rq.norad, "name": parent.name, "alt_km": norm(&pr) - R_EARTH_KM, "mass_kg": mass},
        "years": t / (365.25 * 86400.0), "accel": accel, "n_catalog": n_cat,
        "frags": frag_out, "deaths": deaths, "events": events, "series": series,
        "summary": {"fragments_total": objs.len() - n_cat, "alive_end": alive_end, "collisions": n_coll,
                    "expected_collisions": expected, "expected_real": expected / accel, "capped": capped},
        "elapsed_s": t_start.elapsed().as_secs_f64(),
    }))
    .into_response()
}
