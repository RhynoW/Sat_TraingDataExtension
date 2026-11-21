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
//! - 目錄物件依 TLE 的 B*（阻力項）換算面積質量比，同樣套用阻力衰減與再入（v0.1.15 起）。
//! - 緩解決策（actions）：清理任務、移除大型廢棄物、避碰機動，於指定時刻生效。
//! - 資源保護：同時只算一個模擬（其餘回 429），相同參數 5 分鐘內直接回快取。

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use chrono::{DateTime, Duration, Utc};
use kiddo::immutable::float::kdtree::ImmutableKdTree;
use kiddo::SquaredEuclidean;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
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
const REENTRY_KM: f64 = 120.0;
const YEAR_S: f64 = 365.25 * 86400.0;
const KNOT_DA_KM: f64 = 5.0;        // 衰減節點：半長軸每下降這麼多記一筆（前端畫阻力衰減用）
const KNOT_PER_FRAG: usize = 12;
const KNOT_MAX: usize = 60_000;
/// Δv 長尾截斷（v0.1.19，只用於碰撞模型）：log₁₀Δv 超過 μ + kσ 重抽。依 Cosmos 1408 驗證選定（單一事件的經驗校準），見架構說明 6.1；
/// 爆炸模型沒有驗證資料，維持原始 SBM
const DV_SIGMA_MAX: f64 = 1.0;      // 近地點低於此高度即移除（出生時與演化中一致）
const CACHE_SECS: i64 = 300;
const CACHE_MAX: usize = 6;

static BUSY: AtomicBool = AtomicBool::new(false);

/// 快取鍵的模型版本：程式版本＋太陽活動與密度表內容的雜湊（更新資料或重新建置後，舊結果不會再命中）
fn model_version() -> &'static str {
    static V: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    V.get_or_init(|| {
        let mut h: u64 = 0xcbf29ce484222325; // FNV-1a
        for b in F107_CSV.bytes().chain(MSIS_CSV.bytes()) {
            h ^= b as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
        format!("{}+{:016x}", env!("CARGO_PKG_VERSION"), h)
    })
}
static CACHE: Mutex<Vec<(String, i64, Value)>> = Mutex::new(Vec::new());

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

// ── 隨太陽活動變化的大氣（v0.1.17）──────────────────────────────────────
// 每月 F10.7（81 天中心平均；實測＋CelesTrak 預報，scripts/gen_solar_tables.py 產生）與 NRLMSISE-00 全球平均密度表
static F107_CSV: &str = include_str!("../config/f107_monthly.csv");
static MSIS_CSV: &str = include_str!("../config/msis_density.csv");
/// 沒有每日 Ap 時的等效 Ap（與 f107_monthly.csv 檔頭的實測中位數一致；固定 F10.7 情境也用這個值）
const AP_DEFAULT: f64 = 10.2;

struct Solar {
    m0: i32,               // 第一個月（年×12＋月−1）
    f107: Vec<f64>,        // 逐月
    obs_until: String,     // 最後一個實測月
    ap: Vec<f64>,          // 逐月等效 Ap（v0.1.19；無每日 Ap 的預報月份為實測中位數）
    alts: Vec<f64>,
    aps: Vec<f64>,
    fs: Vec<f64>,
    ln_rho: Vec<Vec<Vec<f64>>>, // [高度][Ap][F10.7]
}
static SOLAR: std::sync::OnceLock<Solar> = std::sync::OnceLock::new();

fn solar() -> &'static Solar {
    SOLAR.get_or_init(|| {
        let mut m0 = 0;
        let (mut f107, mut ap) = (Vec::new(), Vec::new());
        let mut obs_until = String::new();
        for l in F107_CSV.lines().filter(|l| !l.starts_with('#') && !l.starts_with("month")) {
            let c: Vec<&str> = l.split(',').collect();
            if c.len() < 4 { continue; }
            let (y, m): (i32, i32) = (c[0][..4].parse().unwrap_or(2000), c[0][5..7].parse().unwrap_or(1));
            if f107.is_empty() { m0 = y * 12 + m - 1; }
            f107.push(c[1].parse().unwrap_or(120.0));
            ap.push(c[3].parse().unwrap_or(AP_DEFAULT));
            if c[2] == "OBS" { obs_until = c[0].to_string(); }
        }
        // 密度表：每列「高度,Ap,各 F10.7 的密度」，同一高度的各 Ap 連續排列
        let mut lines = MSIS_CSV.lines().filter(|l| !l.starts_with('#'));
        let fs: Vec<f64> = lines.next().unwrap_or("").split(',').skip(2).filter_map(|x| x.parse().ok()).collect();
        let (mut alts, mut aps, mut ln_rho): (Vec<f64>, Vec<f64>, Vec<Vec<Vec<f64>>>) = (Vec::new(), Vec::new(), Vec::new());
        for l in lines {
            let v: Vec<f64> = l.split(',').filter_map(|x| x.parse().ok()).collect();
            if v.len() != fs.len() + 2 { continue; }
            if alts.last() != Some(&v[0]) {
                alts.push(v[0]);
                ln_rho.push(Vec::new());
            }
            if alts.len() == 1 { aps.push(v[1]); }
            ln_rho.last_mut().unwrap().push(v[2..].iter().map(|r| r.ln()).collect());
        }
        Solar { m0, f107, ap, obs_until, alts, aps, fs, ln_rho }
    })
}

impl Solar {
    /// 時刻的 F10.7 與等效 Ap（逐月線性內插）；早於資料取第一個月，晚於資料（2041 年後）F10.7 以 11 年週期外推
    /// （平均 120、振幅 52，接在最後一個月的極小期），Ap 取實測中位數
    fn at(&self, t: &DateTime<Utc>) -> (f64, f64) {
        use chrono::Datelike;
        let mi = (t.year() * 12 + t.month() as i32 - 1 - self.m0) as f64 + (t.day() as f64 - 1.0) / 30.4;
        let n = self.f107.len();
        if mi <= 0.0 { return (self.f107[0], self.ap[0]); }
        if mi >= (n - 1) as f64 {
            let k = mi - (n - 1) as f64;
            return (120.0 - 52.0 * (TAU * k / 132.0).cos(), AP_DEFAULT);
        }
        let i = mi.floor() as usize;
        let w = mi - i as f64;
        (self.f107[i] * (1.0 - w) + self.f107[i + 1] * w, self.ap[i] * (1.0 - w) + self.ap[i + 1] * w)
    }
    fn data_until(&self) -> String {
        let m = self.m0 + self.f107.len() as i32 - 1;
        format!("{:04}-{:02}", m / 12, m % 12 + 1)
    }
    /// 高度 h（km）、F10.7、日 Ap 的密度（kg/m³）與局部尺度高度（km）：對 ln ρ 三線性內插（F10.7 方向用 ln F、Ap 方向線性）
    fn rho(&self, h: f64, f: f64, ap: f64) -> (f64, f64) {
        let na = self.alts.len();
        let hc = h.clamp(self.alts[0], self.alts[na - 1]);
        let ia = ((hc - self.alts[0]) / (self.alts[1] - self.alts[0])).floor().min((na - 2) as f64) as usize;
        let fc = f.clamp(self.fs[0], self.fs[self.fs.len() - 1]);
        let jf = self.fs.iter().rposition(|&x| x <= fc).unwrap_or(0).min(self.fs.len() - 2);
        let wf = (fc.ln() - self.fs[jf].ln()) / (self.fs[jf + 1].ln() - self.fs[jf].ln());
        let pc = ap.clamp(self.aps[0], self.aps[self.aps.len() - 1]);
        let kp = self.aps.iter().rposition(|&x| x <= pc).unwrap_or(0).min(self.aps.len() - 2);
        let wp = (pc - self.aps[kp]) / (self.aps[kp + 1] - self.aps[kp]);
        let at = |i: usize| {
            let g = |k: usize| self.ln_rho[i][k][jf] * (1.0 - wf) + self.ln_rho[i][k][jf + 1] * wf;
            g(kp) * (1.0 - wp) + g(kp + 1) * wp
        };
        let (l0, l1) = (at(ia), at(ia + 1));
        let dh = self.alts[ia + 1] - self.alts[ia];
        let hs = dh / (l0 - l1).max(1e-6); // 尺度高度
        let wa = (h - self.alts[ia]) / dh;  // 超出表格時沿兩端的尺度高度外推
        ((l0 + (l1 - l0) * wa).exp(), hs)
    }
}

/// 一個時間步的阻力衰減（King-Hele 近似：近圓軌道均勻衰減；偏心軌道近地點不動、遠地點下降）
/// sw = None 用舊版 Vallado 靜態指數大氣；Some((F10.7, Ap)) 用 NRLMSISE-00 全球平均密度表
fn decay(el: &mut El, am: f64, dt: f64, sw: Option<(f64, f64)>) {
    let hp = el.perigee_alt();
    let (rho, h_km) = match sw { Some((f, ap)) => solar().rho(hp.max(100.0), f, ap), None => atm(hp.max(100.0)) };
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
/// dv_k：碰撞模型 log₁₀Δv 常態分布的截斷點（μ + kσ 以上重抽）；INFINITY = 原始 SBM。爆炸模型一律不截斷
fn breakup(rng: &mut Rng, n_target: Option<usize>, collision: bool, m_ref: f64, m_total: f64, l_max: f64, cap: f64, dv_k: f64) -> Vec<Frag> {
    let (k, b) = if collision { (0.1 * m_ref.powf(0.75), 1.71) } else { (6.0, 1.6) };
    let dv_k = if collision { dv_k } else { f64::INFINITY };
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
            let mut z = rng.normal();
            let mut tries = 0;
            while z > dv_k && tries < 50 {
                z = rng.normal();
                tries += 1;
            }
            let dvm = 10f64.powf(mu + 0.4 * z.min(dv_k)) / 1000.0; // km/s
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
    kind: u8, // 目錄物件類別：0 有效載荷、1 火箭體、2 碎片、3 其他；碎片固定 2
    alive: bool,
    death: f64,
    name: Option<String>,
    fail_t: f64,  // 有效載荷失效時刻（秒；INFINITY = 一直維持軌道）：之後依 am_eol 衰減、不再避碰
    am_eol: f64,
}

fn cat_props(s: &SatInfo) -> (f64, f64, u8) {
    // (硬體半徑 km, 質量 kg, 類別)：DB 沒有尺寸與質量，依類別取代表值
    match s.purpose.as_str() {
        "有效載荷" => (0.0015, 500.0, 0),
        "火箭體" => (0.002, 1500.0, 1),
        "碎片" => (0.0002, 5.0, 2),
        _ => (0.0005, 50.0, 3),
    }
}

/// TLE 第 1 行第 54–61 欄的 B*（單位 1/地球半徑，隱含小數點，例如 " 34123-4" = 0.34123e-4）
fn parse_bstar(line1: &str) -> f64 {
    let f = line1.get(53..61).unwrap_or("").trim();
    if f.len() < 3 {
        return 0.0;
    }
    let (body, exp) = f.split_at(f.len() - 2);
    let (sign, digits) = match body.strip_prefix('-') { Some(d) => (-1.0, d), None => (1.0, body.trim_start_matches('+')) };
    let mant: f64 = format!("0.{}", digits.trim()).parse().unwrap_or(0.0);
    let e: i32 = exp.trim().parse().unwrap_or(0);
    sign * mant * 10f64.powi(e)
}

/// B* → 面積質量比（m²/kg）。B* = ρ₀·(Cd·A/m)/2，ρ₀ = 2.461e-8 kg/m³（SGP4 參考密度）、Cd = 2.2（與 decay() 一致）。
/// 負值或雜訊視為 0（不衰減），上限 0.2 m²/kg。
fn bstar_am(bstar: f64) -> f64 {
    let b = 2.0 * (bstar / (R_EARTH_KM * 1000.0)) / 2.461e-8; // Cd·A/m
    (b / 2.2).clamp(0.0, 0.2)
}

#[derive(Deserialize, Serialize, Clone)]
pub struct OrbitReq {
    alt_km: f64,
    inc_deg: f64,
    name: Option<String>,
}

/// 緩解決策：cleanup（移除最重的 n 個碎片）、derelict（移除母體高度 ±100 km 內 n 個火箭體）、
/// avoid（之後有效載荷對 ≥ 10 cm 物件避碰，碰撞率 ×0.1）
#[derive(Deserialize, Serialize, Clone)]
pub struct ActionReq {
    kind: String,
    t_days: f64,
    n: Option<usize>,
    /// 避碰能力：low（碰撞率降至 50%）、std（10%，預設）、high（2%）
    level: Option<String>,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct BreakupReq {
    #[serde(default)]
    norad: u32,
    mass_kg: f64,
    n_frag: usize,
    #[serde(default)]
    collision: bool,
    years: f64,
    accel: f64,
    seed: Option<u64>,
    /// 自訂軌道母體（已不在目錄中的歷史案例用）；有值時忽略 norad
    orbit: Option<OrbitReq>,
    #[serde(default)]
    actions: Vec<ActionReq>,
    /// 大氣：series（預設，隨實測與預報的 F10.7 變化）、low／mid／high（固定 F10.7 = 70／120／200）、static（舊版 Vallado 靜態大氣）
    solar: Option<String>,
    /// 解體日期（YYYY-MM-DD）：只決定太陽活動序列從哪一天開始（歷史情境用）；目錄位置仍是現在
    epoch: Option<String>,
    /// 解體時刻（RFC 3339）：對照組與多種子比較沿用主結果的 t0，確保母體位置與目錄相同（共同隨機數）；未給＝現在，限現在 ±3 天
    t0: Option<String>,
    /// 有效載荷平均剩餘壽命（年）：給值時每顆在 0～2L 年間失效，之後依 B* 衰減且不再避碰；未給為保守假設（一直維持軌道）
    payload_life: Option<f64>,
    /// 驗證用（介面不提供）：Δv 截斷點 k（log₁₀Δv 超過 μ + kσ 重抽）；未給為預設值
    dv_sigma_max: Option<f64>,
    /// 驗證用：密度整體倍率（0.25–4，敏感度測試）
    rho_scale: Option<f64>,
    /// 驗證用：固定 Ap（不隨月份變化；v0.1.18 以前為 15）
    ap_fixed: Option<f64>,
}

fn bad(msg: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response()
}

/// 計算期間持有；結束（含 panic）時釋放忙碌旗標
struct BusyGuard;
impl Drop for BusyGuard {
    fn drop(&mut self) { BUSY.store(false, Ordering::SeqCst); }
}

fn sgp4_rv(s: &SatInfo, t: &DateTime<Utc>) -> Option<(V3, V3)> {
    let p = s.prop.as_ref()?;
    let ns = (t.naive_utc() - p.epoch).num_nanoseconds()?;
    let pr = p.constants.propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9)).ok()?;
    let r = pr.position;
    (r.iter().all(|v| v.is_finite()) && norm(&r) > R_EARTH_KM + 100.0).then_some((r, pr.velocity))
}

pub async fn breakup_api(State(st): State<Arc<AppState>>, Json(rq): Json<BreakupReq>) -> Response {
    if !(2..=2000).contains(&rq.n_frag) {
        return bad("碎片數需介於 2 到 2000");
    }
    if rq.actions.len() > 6 {
        return bad("緩解決策最多 6 項");
    }
    if let Some(o) = &rq.orbit {
        if !(200.0..=2000.0).contains(&o.alt_km) || !(0.0..=180.0).contains(&o.inc_deg) {
            return bad("自訂軌道：高度需介於 200–2000 km、傾角 0–180°");
        }
    }
    let years = rq.years.clamp(0.1, 50.0);
    let accel = rq.accel.clamp(1.0, 1e6);
    let mass = rq.mass_kg.clamp(1.0, 1e6);
    // 快取：同參數、同一份目錄（索引建立時間）5 分鐘內直接回傳；LRU（命中時移到最後）
    let key = format!("{}|{}|{}", model_version(), st.index().built_at.timestamp(), serde_json::to_string(&rq).unwrap_or_default());
    let bucket = Utc::now().timestamp() / CACHE_SECS;
    if let Ok(mut c) = CACHE.lock() {
        if let Some(pos) = c.iter().position(|e| e.0 == key && e.1 == bucket) {
            let e = c.remove(pos);
            let mut v = e.2.clone();
            c.push(e);
            v["cached"] = json!(true);
            return Json(v).into_response();
        }
    }
    // 同時只算一個：區網多人或連點時避免把 CPU 打滿；附 Retry-After 讓前端倒數重試
    if BUSY.swap(true, Ordering::SeqCst) {
        return (StatusCode::TOO_MANY_REQUESTS, [(axum::http::header::RETRY_AFTER, "3")],
            Json(json!({"error": "另一個碎片模擬正在計算", "retry_after": 3}))).into_response();
    }
    let out = tokio::task::spawn_blocking(move || {
        let _g = BusyGuard;
        run(&st, &rq, years, accel, mass)
    })
    .await;
    match out {
        Ok(Ok(v)) => {
            if let Ok(mut c) = CACHE.lock() {
                c.retain(|e| e.1 == bucket && e.0 != key);   // 過期的分桶一併清掉
                if c.len() >= CACHE_MAX { c.remove(0); }
                c.push((key, bucket, v.clone()));
            }
            Json(v).into_response()
        }
        Ok(Err(msg)) => bad(&msg),
        Err(_) => { BUSY.store(false, Ordering::SeqCst); bad("計算失敗") }
    }
}

fn run(st: &Arc<AppState>, rq: &BreakupReq, years: f64, accel: f64, mass: f64) -> Result<Value, String> {
    let t_start = std::time::Instant::now();
    let idx = st.index();
    let now = Utc::now();
    let t0 = match rq.t0.as_deref() {
        Some(s) => {
            let t = DateTime::parse_from_rfc3339(s).map_err(|_| "t0 需為 RFC 3339 時刻")?.with_timezone(&Utc);
            if (t - now).num_seconds().abs() > 3 * 86400 { return Err("t0 需在現在 ±3 天內".into()); }
            t
        }
        None => now,
    };
    // 母體：目錄衛星（SGP4）或自訂圓軌道（升交點赤經 0、從升交點出發）
    let (pr, pv, pname, custom) = if let Some(o) = &rq.orbit {
        let a = R_EARTH_KM + o.alt_km;
        let vc = (MU / a).sqrt();
        let i = o.inc_deg.to_radians();
        ([a, 0.0, 0.0], [0.0, vc * i.cos(), vc * i.sin()], o.name.clone().unwrap_or_else(|| "自訂軌道".into()), true)
    } else {
        let parent = idx.sats.get(&rq.norad).ok_or("目錄中找不到這個 NORAD 編號")?;
        let (r, v) = sgp4_rv(parent, &t0).ok_or("這顆衛星目前無法傳播（TLE 失效或已再入）")?;
        (r, v, parent.name.clone(), false)
    };
    // 太陽活動：模式與起始日期
    let mode = rq.solar.clone().unwrap_or_else(|| "series".into());
    let fixed_f = match mode.as_str() { "low" => Some(70.0), "mid" => Some(120.0), "high" => Some(200.0), _ => None };
    let epoch = rq.epoch.as_deref()
        .and_then(|d| chrono::NaiveDate::parse_from_str(d, "%Y-%m-%d").ok())
        .and_then(|d| d.and_hms_opt(0, 0, 0))
        .map(|d| d.and_utc())
        .unwrap_or(t0);
    let ap_fixed = rq.ap_fixed.map(|a| a.clamp(0.0, 400.0));
    let f_at = |t: f64| -> Option<(f64, f64)> {
        match mode.as_str() {
            "static" => None,
            _ => {
                let (f, ap) = solar().at(&(epoch + Duration::seconds(t as i64)));
                Some((fixed_f.unwrap_or(f), ap_fixed.unwrap_or(if fixed_f.is_some() { AP_DEFAULT } else { ap })))
            }
        }
    };
    let rho_scale = rq.rho_scale.unwrap_or(1.0).clamp(0.25, 4.0);
    let dv_k = rq.dv_sigma_max.map(|k| k.clamp(0.5, 10.0)).unwrap_or(DV_SIGMA_MAX);
    let mut knots: Vec<Value> = Vec::new();
    let mut knot_a: Vec<(f64, usize)> = Vec::new();   // 每個碎片上一筆節點的半長軸與節點數
    let mut payload_failed = 0usize;
    let mut f_hist: Vec<f64> = Vec::new();
    let mut ap_hist: Vec<f64> = Vec::new();
    let mut rng = Rng(rq.seed.unwrap_or(1) ^ 0x5DEECE66D);
    // 快照時刻用獨立亂數流：決策移除物件會改變擲骰次數，但不影響取樣時刻，同種子的對照組與決策組可直接比較（共同隨機數）
    let mut rng_snap = Rng(rq.seed.unwrap_or(1) ^ 0x2545F4914F6CDD1D);

    // 目錄物件（排除母體）轉成 t0 的根數；面積質量比由 TLE 的 B* 換算（阻力衰減用）
    let skip_id = if custom { u32::MAX } else { rq.norad };
    let seed = rq.seed.unwrap_or(1);
    let payload_life = rq.payload_life.map(|l| l.clamp(0.5, 50.0));
    let cats: Vec<&SatInfo> = idx.sats.values().filter(|s| s.prop.is_some() && s.norad_id != skip_id).collect();
    let cat_objs: Vec<Option<Obj>> = cats
        .par_iter()
        .map(|s| {
            let (r, v) = sgp4_rv(s, &t0)?;
            let el = El::from_rv(&r, &v, 0.0)?;
            let (rk, m, kind) = cat_props(s);
            // 有效載荷假設會維持軌道（或由同類補充），不衰減；火箭體、碎片與其他物件依 B* 衰減
            let am = if kind == 0 { 0.0 } else { bstar_am(parse_bstar(&s.line1)) };
            // 可選情境：有效載荷在剩餘壽命（0～2L 年均勻，平均 L 年；依 NORAD 與種子決定，不消耗主亂數流）後失效，改依 B* 衰減
            let (fail_t, am_eol) = match payload_life {
                Some(l) if kind == 0 => {
                    let u = Rng((s.norad_id as u64) << 20 ^ seed ^ 0x9E3779B97F4A7C15).next();
                    let b = bstar_am(parse_bstar(&s.line1));
                    (u * 2.0 * l * YEAR_S, if b > 0.0 { b } else { 0.01 })
                }
                _ => (f64::INFINITY, 0.0),
            };
            Some(Obj { el, r_km: rk, mass: m, am, gen: 0, kind, alive: true, death: -1.0, name: Some(s.name.clone()), fail_t, am_eol })
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
            let reentered = el.perigee_alt() < REENTRY_KM;
            let id = objs.len() - n_cat;
            frag_out.push(json!([id, t, gen, f.l, f.am, el.a, el.e, el.i, el.raan, el.argp, el.m0, el.raan_dot, el.argp_dot, el.m_dot]));
            objs.push(Obj { el, r_km: f.l / 2000.0, mass: f.mass, am: f.am, gen, kind: 2, alive: !reentered, death: if reentered { t } else { -1.0 }, name: None,
                fail_t: f64::INFINITY, am_eol: 0.0 });
            n += 1;
        }
        n
    };

    // 第一次解體
    let l_max = (mass / 100.0).cbrt().clamp(0.5, 10.0);
    let fr = breakup(&mut rng, Some(rq.n_frag), rq.collision, mass, mass, l_max, 2000.0, dv_k);
    let n0 = spawn(&mut objs, &mut frag_out, fr, pr, pv, 0.0, 1, &mut capped);
    events.push(json!({"t": 0.0, "kind": if rq.collision { "collision" } else { "explosion" }, "a": pname, "b": null,
        "n_new": n0, "pos": pr, "catastrophic": true, "gen": 1}));
    let parent_alt = norm(&pr) - R_EARTH_KM;
    let parent_el = El::from_rv(&pr, &pv, 0.0);   // 移除火箭體時比對軌道面用

    // 緩解決策：依時刻排序，於時間步開頭生效
    let mut actions: Vec<ActionReq> = rq.actions.clone();
    actions.sort_by(|a, b| a.t_days.partial_cmp(&b.t_days).unwrap_or(std::cmp::Ordering::Equal));
    let mut next_act = 0usize;
    let mut avoid_from = f64::INFINITY;
    let mut avoid_k = 0.1;

    // 時間步：前 30 天每天、之後依總年數 5／10／30 天；每步 3 個快照（隨機時刻）
    let total_s = years * 365.25 * 86400.0;
    let late_dt: f64 = (if years <= 5.0 { 5.0 } else if years <= 15.0 { 10.0 } else { 30.0 }) * 86400.0;
    let mut t = 0.0;
    let mut series: Vec<Value> = Vec::new();
    let mut expected = 0.0;
    let mut expected_g1 = 0.0; // 只計第一代碎片與目錄物件之間（不含加速產生的後代）
    let mut n_coll = 0usize;
    let mut risk: HashMap<usize, f64> = HashMap::new(); // 目錄物件累計期望碰撞
    let mut frag_risk: HashMap<usize, f64> = HashMap::new(); // 碎片累計期望碰撞（清理任務排序用）
    let d2 = SCREEN_D * SCREEN_D;
    let chord = 4.0 * SCREEN_D / 3.0;
    let alive_counts = |objs: &Vec<Obj>| -> Vec<usize> {
        let mut g = vec![0usize; 8];
        for o in objs.iter().skip(n_cat).filter(|o| o.alive) {
            g[(o.gen as usize).min(7)] += 1;
        }
        g
    };
    let cat_gone = |objs: &Vec<Obj>| objs.iter().take(n_cat).filter(|o| !o.alive).count();
    series.push(json!({"t": 0.0, "alive": alive_counts(&objs), "expected": 0.0, "collisions": 0, "cat_gone": 0}));
    while t < total_s {
        // 緩解決策
        while next_act < actions.len() && actions[next_act].t_days * 86400.0 <= t + 1.0 {
            let a = &actions[next_act];
            next_act += 1;
            match a.kind.as_str() {
                "cleanup" => {
                    let n = a.n.unwrap_or(20).min(200);
                    // 依累計期望碰撞（到目前為止的碰撞風險貢獻）排序，同分再比質量；解體後太早還沒有風險資料時等同依質量
                    let mut idx: Vec<usize> = (n_cat..objs.len()).filter(|&i| objs[i].alive).collect();
                    let rk = |i: &usize| frag_risk.get(i).copied().unwrap_or(0.0);
                    idx.sort_by(|x, y| rk(y).partial_cmp(&rk(x)).unwrap_or(std::cmp::Ordering::Equal)
                        .then(objs[*y].mass.partial_cmp(&objs[*x].mass).unwrap_or(std::cmp::Ordering::Equal)));
                    let cand = idx.len();
                    let took: Vec<usize> = idx.into_iter().take(n).collect();
                    let m: f64 = took.iter().map(|&i| objs[i].mass).sum();
                    for &i in &took { objs[i].alive = false; objs[i].death = t; }
                    events.push(json!({"t": t, "kind": "cleanup", "a": format!("清理任務（教學簡化）：在 {} 個在軌碎片中，移除累計碰撞風險最高的 {} 個（共 {:.0} kg）", cand, took.len(), m), "b": null,
                        "n_new": 0, "removed": took.len(), "candidates": cand, "mass_kg": m, "pos": pr, "catastrophic": false, "gen": 0}));
                }
                "derelict" => {
                    let n = a.n.unwrap_or(10).min(100);
                    // 軌道可及性的粗略篩選：與母體軌道面相近（傾角差 ≤ 5°、升交點赤經差 ≤ 30°，依 J2 漂移推到當下），且高度帶重疊 ±100 km
                    let (pi, praan) = parent_el.as_ref().map(|p| (p.i, p.raan + p.raan_dot * t)).unwrap_or((0.0, 0.0));
                    let mut idx: Vec<(usize, f64)> = (0..n_cat)
                        .filter(|&i| objs[i].alive && objs[i].kind == 1)
                        .filter(|&i| {
                            let e = &objs[i].el;
                            let draan = ((e.raan + e.raan_dot * (t - e.t_ref) - praan).rem_euclid(TAU) + TAU / 2.0).rem_euclid(TAU) - TAU / 2.0;
                            parent_el.is_none() || ((e.i - pi).abs() <= 5f64.to_radians() && draan.abs() <= 30f64.to_radians())
                        })
                        .map(|i| {
                            let e = &objs[i].el;
                            let (hp, ha) = (e.a * (1.0 - e.e) - R_EARTH_KM, e.a * (1.0 + e.e) - R_EARTH_KM);
                            let gap = if parent_alt < hp { hp - parent_alt } else if parent_alt > ha { parent_alt - ha } else { 0.0 };
                            (i, gap)
                        })
                        .filter(|x| x.1 <= 100.0)
                        .collect();
                    idx.sort_by(|x, y| x.1.partial_cmp(&y.1).unwrap_or(std::cmp::Ordering::Equal));
                    let cand = idx.len();
                    let took: Vec<usize> = idx.into_iter().take(n).map(|x| x.0).collect();
                    for &i in &took { objs[i].alive = false; objs[i].death = t; }
                    let msg = if took.len() < n {
                        format!("移除廢棄火箭體（教學簡化）：與母體軌道面相近、高度 ±100 km 內只找到 {} 個候選，全部移除", took.len())
                    } else {
                        format!("移除廢棄火箭體（教學簡化）：在 {} 個符合條件的候選中，移除最接近的 {} 個", cand, took.len())
                    };
                    events.push(json!({"t": t, "kind": "derelict", "a": msg, "b": null, "candidates": cand,
                        "n_new": 0, "removed": took.len(), "pos": pr, "catastrophic": false, "gen": 0}));
                }
                "avoid" => {
                    avoid_from = avoid_from.min(t);
                    let (k, lv) = match a.level.as_deref() {
                        Some("low") => (0.5, "基礎（預警與燃料有限）"),
                        Some("high") => (0.02, "進階（精密定軌、自動化協調）"),
                        _ => (0.1, "標準"),
                    };
                    avoid_k = k;
                    events.push(json!({"t": t, "kind": "avoid", "a": format!("簡化避碰假設・{}：運作中的衛星對 ≥ 10 cm 物件避碰，碰撞機率降至 {:.0}%（實際效果取決於預警、燃料、協調與虛警率）", lv, k * 100.0), "b": null,
                        "n_new": 0, "level": a.level.clone().unwrap_or_else(|| "std".into()), "factor": k, "pos": pr, "catastrophic": false, "gen": 0}));
                }
                _ => {}
            }
        }
        let dt: f64 = (if t < 30.0 * 86400.0 { 86400.0 } else { late_dt }).min(total_s - t);
        let ks = 3;
        let avoid_on = t >= avoid_from;
        let mut cand: Vec<(usize, usize, f64, f64)> = Vec::new(); // (i, j, λ, 相對速度)
        for _ in 0..ks {
            let ts = t + rng_snap.next() * dt;
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
                        let mut lam = vr / chord * (rr * rr) / d2 * dt / ks as f64 * accel;
                        // 避碰：有效載荷（目錄 kind 0）對可追蹤（≥ 10 cm）的物件做機動，碰撞率降為一成
                        if avoid_on && b < n_cat && objs[b].kind == 0 && objs[b].fail_t > ts && objs[a].r_km * 2000.0 >= 0.1 {
                            lam *= avoid_k;
                        }
                        Some((a, b, lam, vr))
                    })
                })
                .collect();
            cand.extend(found);
        }
        cand.sort_by(|x, y| (x.0, x.1).cmp(&(y.0, y.1)));
        for (a, b, lam, vr) in cand {
            expected += lam;
            if objs[a].gen <= 1 && objs[b].gen <= 1 {
                expected_g1 += lam;
            }
            if b < n_cat {
                *risk.entry(b).or_insert(0.0) += lam;
            } else {
                *frag_risk.entry(b).or_insert(0.0) += lam;
            }
            *frag_risk.entry(a).or_insert(0.0) += lam;
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
            let fr = breakup(&mut rng, None, true, m_ref, m_tot, lmax, PER_EVENT_MAX, dv_k);
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
        // 阻力衰減與再入：碎片依 A/M，目錄物件依 TLE 的 B*（am = 0 者不衰減）；密度依時間步中點的 F10.7
        let t_end = t + dt;
        let fstep = f_at(t + dt / 2.0);
        if let Some((fv, av)) = fstep { f_hist.push(fv); ap_hist.push(av); }
        objs.par_iter_mut().filter(|o| o.alive && (o.am > 0.0 || o.fail_t <= t_end)).for_each(|o| {
            if o.am == 0.0 { o.am = o.am_eol; }
            o.el.rebase(t_end);
            decay(&mut o.el, o.am * rho_scale, dt, fstep);
            if o.el.perigee_alt() < REENTRY_KM {
                o.alive = false;
                o.death = t_end;
            }
        });
        // 衰減節點：碎片半長軸比上一筆低 KNOT_DA_KM 以上時記錄（前端在節點間內插 a、e，畫出軌道下降）
        if knots.len() < KNOT_MAX {
            for (k, o) in objs.iter().enumerate().skip(n_cat) {
                let id = k - n_cat;
                if id >= knot_a.len() { knot_a.push((o.el.a, 0)); }
                let (la, nk) = knot_a[id];
                if o.alive && nk < KNOT_PER_FRAG && la - o.el.a >= KNOT_DA_KM && knots.len() < KNOT_MAX {
                    knots.push(json!([id, t_end, (o.el.a * 10.0).round() / 10.0, (o.el.e * 1e5).round() / 1e5]));
                    knot_a[id] = (o.el.a, nk + 1);
                }
            }
        }
        let pl_failed = objs.iter().take(n_cat).filter(|o| o.kind == 0 && o.fail_t <= t_end).count();
        if pl_failed > 0 { payload_failed = pl_failed; }
        t = t_end;
        series.push(json!({"t": t, "alive": alive_counts(&objs), "expected": expected, "collisions": n_coll, "cat_gone": cat_gone(&objs), "f107": fstep.map(|x| x.0), "ap": fstep.map(|x| x.1)}));
        if t_start.elapsed().as_secs() > 90 {
            break;
        }
    }
    events.sort_by(|x, y| x["t"].as_f64().partial_cmp(&y["t"].as_f64()).unwrap_or(std::cmp::Ordering::Equal));
    let deaths: Vec<f64> = objs.iter().skip(n_cat).map(|o| o.death).collect();
    let alive_end = objs.iter().skip(n_cat).filter(|o| o.alive).count();
    let reentered = objs.iter().skip(n_cat).filter(|o| !o.alive && o.death >= 0.0).count();
    // 風險最高的目錄物件（累計期望碰撞，已除回加速倍率）
    let mut rk: Vec<(usize, f64)> = risk.into_iter().collect();
    rk.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
    let kinds = ["有效載荷", "火箭體", "碎片", "其他"];
    let risk_top: Vec<Value> = rk.iter().take(5).map(|&(i, l)| {
        let e = &objs[i].el;
        json!({"name": objs[i].name, "kind": kinds[objs[i].kind as usize % 4], "expected_real": l / accel,
               "alt_km": (e.a - R_EARTH_KM).round()})
    }).collect();
    let elapsed = t_start.elapsed().as_secs_f64();
    tracing::info!(
        "碎片連鎖：母體 {} 碎片 {} {} 年 ×{} 決策 {} → 碎片 {}{} 碰撞 {} 期末 {} 計算 {:.1} 秒",
        pname, rq.n_frag, years, accel, actions.len(), objs.len() - n_cat, if capped { "（達上限）" } else { "" }, n_coll, alive_end, elapsed
    );
    Ok(json!({
        "t0": t0.to_rfc3339(),
        "parent": {"norad": if custom { Value::Null } else { json!(rq.norad) }, "name": pname, "alt_km": parent_alt, "mass_kg": mass, "custom": custom},
        "years": t / (365.25 * 86400.0), "accel": accel, "n_catalog": n_cat,
        "frags": frag_out, "deaths": deaths, "events": events, "series": series, "risk_top": risk_top,
        "summary": {"fragments_total": objs.len() - n_cat, "alive_end": alive_end, "collisions": n_coll, "reentered": reentered,
                    "expected_collisions": expected,
                    // 線性反推：期望值 ÷ 倍率。加速時多出的後代碎片也計入，所以偏高（未補償連鎖偏差）
                    "expected_linear": expected / accel, "expected_real": expected / accel,
                    // 只計第一代碎片與目錄物件：較接近「沒有加速」的寫實期望碰撞
                    "expected_gen1_real": expected_g1 / accel,
                    "cat_reentered": cat_gone(&objs), "capped": capped,
                    "payload_life": payload_life, "payload_failed": payload_failed},
        "knots": knots,
        "solar": {
            "mode": mode, "epoch": epoch.format("%Y-%m-%d").to_string(),
            "f107_mean": if f_hist.is_empty() { Value::Null } else { json!(f_hist.iter().sum::<f64>() / f_hist.len() as f64) },
            "f107_min": f_hist.iter().cloned().fold(f64::INFINITY, f64::min).min(1e9),
            "f107_max": f_hist.iter().cloned().fold(0.0, f64::max),
            "ap_mean": if ap_hist.is_empty() { Value::Null } else { json!(ap_hist.iter().sum::<f64>() / ap_hist.len() as f64) },
            "ap_max": ap_hist.iter().cloned().fold(0.0, f64::max),
            "obs_until": solar().obs_until, "data_until": solar().data_until(),
            "beyond_data": mode == "series" && (epoch + Duration::seconds((t) as i64)).format("%Y-%m").to_string() > solar().data_until(),
        },
        "elapsed_s": elapsed, "cached": false, "model_version": model_version(),
    }))
}
