//! 分段 M/A（等效面積／彈道係數）校準之再入預測——Python 版 physics/segmented_ma.py 的移植
//! （Remis 2026 方法：兩體 + J2/J3/J4 + NRLMSISE-00 阻力、固定步長 RK4）。
//! 演算法、常數、收斂判準與輸出欄位逐項對照 Python 版；密度模式為本模組 msis00（NRLMSISE-00 移植）。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime};

use chrono::{DateTime, Datelike, NaiveDate};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::{json, Map, Value};

use super::common::{py_round, Sat};
use super::msis00;

pub const MU: f64 = 398600.4418;
pub const RE: f64 = 6378.137;
const FLAT: f64 = 1.0 / 298.257223563;
const J2: f64 = 1.08262668e-3;
const J3: f64 = -2.53265649e-6;
const J4: f64 = -1.61962159e-6;
const WE: f64 = 7.2921158553e-5;
const JD_UNIX0: f64 = 2440587.5;

/// Python `round(x)`（半數取偶）→ f64
fn pyr(x: f64) -> f64 {
    super::common::py_round_int(x) as f64
}

// ════════════════════════════ 太空天氣 ════════════════════════════
pub struct SpaceWeather {
    pub path: Option<String>,
    day0: Option<f64>,
    f107: Vec<f64>,
    f81: Vec<f64>,
    ap: Vec<f64>,
    last_obs_day: Option<i64>,
}

impl SpaceWeather {
    fn empty(path: Option<String>) -> Self {
        Self { path, day0: None, f107: vec![], f81: vec![], ap: vec![], last_obs_day: None }
    }

    /// 讀 CelesTrak SW-All.csv（DATE, F10.7_OBS, F10.7_OBS_LAST81|CENTER81, AP_AVG, F10.7_DATA_TYPE）
    fn parse(path: &Path) -> Self {
        let ps = Some(path.display().to_string());
        let Ok(text) = std::fs::read_to_string(path) else { return Self::empty(ps) };
        let mut rdr = csv::ReaderBuilder::new().flexible(true).from_reader(text.trim_start_matches('\u{feff}').as_bytes());
        let Ok(h) = rdr.headers().cloned() else { return Self::empty(ps) };
        let col = |n: &str| h.iter().position(|x| x == n);
        let (Some(c_date), c_f, c_l81, c_c81, c_ap, c_typ) = (
            col("DATE"),
            col("F10.7_OBS"),
            col("F10.7_OBS_LAST81"),
            col("F10.7_OBS_CENTER81"),
            col("AP_AVG"),
            col("F10.7_DATA_TYPE"),
        ) else {
            return Self::empty(ps);
        };
        let get = |rec: &csv::StringRecord, c: Option<usize>| c.and_then(|i| rec.get(i)).unwrap_or("").to_string();
        let mut rows: Vec<(NaiveDate, f64, f64, f64, String)> = Vec::new();
        for rec in rdr.records().flatten() {
            let Ok(d) = NaiveDate::parse_from_str(&get(&rec, Some(c_date)), "%Y-%m-%d") else { continue };
            let num = |s: String| -> Result<f64, ()> {
                if s.is_empty() {
                    Ok(f64::NAN)
                } else {
                    s.trim().parse::<f64>().map_err(|_| ())
                }
            };
            let fl = {
                let l = get(&rec, c_l81);
                if l.is_empty() {
                    get(&rec, c_c81)
                } else {
                    l
                }
            };
            let (Ok(f), Ok(fa), Ok(a)) = (num(get(&rec, c_f)), num(fl), num(get(&rec, c_ap))) else { continue };
            rows.push((d, f, fa, a, get(&rec, c_typ)));
        }
        if rows.is_empty() {
            return Self::empty(ps);
        }
        rows.sort_by_key(|r| r.0);
        let d0 = rows[0].0;
        let n = (rows.last().unwrap().0 - d0).num_days() as usize + 1;
        let mut f107 = vec![f64::NAN; n];
        let mut f81 = vec![f64::NAN; n];
        let mut ap = vec![f64::NAN; n];
        let mut last_obs = None;
        for (d, f, fa, a, typ) in &rows {
            let i = (*d - d0).num_days() as usize;
            f107[i] = *f;
            f81[i] = *fa;
            ap[i] = *a;
            if typ == "OBS" && !a.is_nan() {
                last_obs = Some(i as i64);
            }
        }
        for (arr, dflt) in [(&mut f107, 150.0), (&mut f81, 150.0), (&mut ap, 12.0)] {
            let mut last = dflt;
            for v in arr.iter_mut() {
                if v.is_nan() {
                    *v = last;
                } else {
                    last = *v;
                }
            }
        }
        let day0 = d0.and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp() as f64;
        Self { path: ps, day0: Some(day0), f107, f81, ap, last_obs_day: last_obs }
    }

    fn cap(&self, cutoff: Option<f64>) -> i64 {
        let mut cap = self.ap.len() as i64 - 1;
        if let Some(l) = self.last_obs_day {
            cap = cap.min(l);
        }
        if let (Some(c), Some(d0)) = (cutoff, self.day0) {
            cap = cap.min(((c - d0) / 86400.0).floor() as i64 - 1);
        }
        cap
    }

    /// (F10.7 前一日, F10.7 81 日尾隨平均, 每日 Ap)；截止日之後持平
    fn get(&self, t: f64, cutoff: Option<f64>) -> (f64, f64, f64) {
        let Some(d0) = self.day0 else { return (150.0, 150.0, 12.0) };
        let idx = ((t - d0) / 86400.0).floor() as i64;
        let cap = self.cap(cutoff);
        let clip = |i: i64| -> usize { i.min(cap).max(0) as usize };
        (self.f107[clip(idx - 1)], self.f81[clip(idx)], self.ap[clip(idx)])
    }
}

static SW_CACHE: Lazy<Mutex<Option<(String, Arc<SpaceWeather>)>>> = Lazy::new(|| Mutex::new(None));

/// SW_ALL_PATH 環境變數 → 資料庫目錄／資料目錄 DB\ 之 SW-All.csv（Python 版最後退回 pymsis 內建檔，單機版無此檔）
pub fn sw_default_path(cands: &[PathBuf]) -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("SW_ALL_PATH").map(PathBuf::from).filter(|p| p.exists()) {
        return Some(p);
    }
    cands.iter().find(|p| p.exists()).cloned()
}

pub fn sw_load(path: Option<PathBuf>) -> Arc<SpaceWeather> {
    let mtime = path
        .as_ref()
        .and_then(|p| std::fs::metadata(p).and_then(|m| m.modified()).ok())
        .map(|t| t.duration_since(SystemTime::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0));
    let key = format!("{:?}|{:?}", path, mtime);
    let mut g = SW_CACHE.lock();
    if let Some((k, sw)) = g.as_ref() {
        if *k == key {
            return sw.clone();
        }
    }
    let sw = Arc::new(match &path {
        Some(p) => SpaceWeather::parse(p),
        None => SpaceWeather::empty(None),
    });
    *g = Some((key, sw.clone()));
    sw
}

/// NRLMSISE-00 質量密度 [kg/m^3]（同 Python `_density`：日期取整秒、高度夾 0–1000 km）
fn density(t: f64, lon: f64, lat: f64, alt: f64, sw: &SpaceWeather, cutoff: Option<f64>) -> f64 {
    let (f, fa, ap) = sw.get(t, cutoff);
    let us = (t * 1e6) as i64;
    let secs = us.div_euclid(1_000_000);
    let day = secs.div_euclid(86400);
    let utsec = (secs - day * 86400) as f64;
    let doy = DateTime::from_timestamp(day * 86400, 0).map(|d| d.ordinal() as f64).unwrap_or(1.0);
    let rho = msis00::mass_density(doy, utsec, lon, lat, alt.clamp(0.0, 1000.0), f, fa, ap);
    if rho.is_finite() && rho > 0.0 {
        rho
    } else {
        1e-20
    }
}

// ════════════════════════════ TLE 工具 ════════════════════════════
pub struct Tle {
    pub line1: String,
    pub line2: String,
    pub sat: Sat,
    pub t: f64,
    pub a_kozai: f64,
    pub period: f64,
}

pub fn parse_tles(rows: &[(String, String)]) -> Vec<Tle> {
    let mut out: Vec<Tle> = Vec::new();
    for (l1, l2) in rows {
        let Some(sat) = Sat::from_tle(l1, l2) else { continue };
        let t = sat.epoch_unix();
        let n = sat.mean_motion * 2.0 * std::f64::consts::PI / 1440.0 / 60.0;
        if n <= 0.0 {
            continue;
        }
        let a = (MU / (n * n)).powf(1.0 / 3.0);
        out.push(Tle { line1: l1.clone(), line2: l2.clone(), sat, t, a_kozai: a, period: 2.0 * std::f64::consts::PI / n });
    }
    out.sort_by(|a, b| a.t.total_cmp(&b.t));
    let mut ded: Vec<Tle> = Vec::new();
    for x in out {
        if ded.last().is_some_and(|l| (x.t - l.t).abs() < 60.0) {
            *ded.last_mut().unwrap() = x;
        } else {
            ded.push(x);
        }
    }
    ded
}

fn sgp4_state(tle: &Tle, t: f64) -> Result<[f64; 6], String> {
    let (r, v) = tle.sat.pv_unix(t).ok_or_else(|| "SGP4 error".to_string())?;
    Ok([r[0], r[1], r[2], v[0], v[1], v[2]])
}

fn sgp4_mean_a(tle: &Tle, t0: f64, period: f64) -> Result<f64, String> {
    let dt = 30.0;
    let n = (period / dt).ceil() as usize;
    let mut acc = 0.0;
    let mut ok = 0usize;
    for k in 0..n {
        if let Some((r, v)) = tle.sat.pv_unix(t0 + k as f64 * dt) {
            let rr = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
            let vv = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
            acc += 1.0 / (2.0 / rr - vv / MU);
            ok += 1;
        }
    }
    if (ok as f64) < 0.8 * n as f64 {
        return Err("SGP4 平均半長軸取樣失敗".into());
    }
    Ok(acc / ok as f64)
}

// ════════════════════════════ 數值積分 ════════════════════════════
/// sgp4.propagation.gstime（IAU-82 GMST）
fn gstime(jdut1: f64) -> f64 {
    let tut1 = (jdut1 - 2451545.0) / 36525.0;
    let temp = -6.2e-6 * tut1 * tut1 * tut1 + 0.093104 * tut1 * tut1 + (876600.0 * 3600.0 + 8640184.812866) * tut1 + 67310.54841;
    (temp * std::f64::consts::PI / 180.0 / 240.0).rem_euclid(2.0 * std::f64::consts::PI)
}

struct Traj {
    s: [f64; 6],
    b: f64,
    prof: Option<Vec<f64>>,
    trend: f64,
    active: bool,
    t_cross: Option<f64>,
    wsum: Vec<f64>,
    wcnt: Vec<usize>,
}

struct ChunkRes {
    state: [f64; 6],
    nodes: Vec<[f64; 4]>,
    t_cross: Option<f64>,
}

#[allow(clippy::too_many_arguments)]
fn integrate_chunk(
    s: &[f64; 6],
    b: f64,
    tc: f64,
    l: f64,
    h: f64,
    node_dt: f64,
    prof: Option<&[f64]>,
    stop_alt: Option<f64>,
    windows: &[(f64, f64)],
    wsum: &mut [f64],
    wcnt: &mut [usize],
    record_nodes: bool,
) -> ChunkRes {
    let [mut x, mut y, mut z, mut vx, mut vy, mut vz] = *s;
    let mu = MU;
    let re2 = RE * RE;
    let re3 = re2 * RE;
    let re4 = re2 * re2;
    let c2 = -1.5 * J2 * mu * re2;
    let c3 = -2.5 * J3 * mu * re3;
    let c4 = 1.875 * J4 * mu * re4;
    let half_b = 0.5 * b * 1000.0;
    let prof = prof.unwrap_or(&[]);
    let nnode = prof.len();
    let acc = |tau: f64, x: f64, y: f64, z: f64, vx: f64, vy: f64, vz: f64| -> (f64, f64, f64) {
        let r2 = x * x + y * y + z * z;
        let r = r2.sqrt();
        let ir2 = 1.0 / r2;
        let zr2 = z * z * ir2;
        let ir3 = ir2 / r;
        let ir5 = ir3 * ir2;
        let ir7 = ir5 * ir2;
        let k = -mu * ir3;
        let f2 = c2 * ir5;
        let mut ax = k * x + f2 * x * (1.0 - 5.0 * zr2);
        let mut ay = k * y + f2 * y * (1.0 - 5.0 * zr2);
        let mut az = k * z + f2 * z * (3.0 - 5.0 * zr2);
        let f3 = c3 * ir7;
        let t3 = 3.0 * z - 7.0 * z * zr2;
        ax += f3 * x * t3;
        ay += f3 * y * t3;
        az += f3 * (6.0 * z * z - 7.0 * z * z * zr2 - 0.6 * r2);
        let f4 = c4 * ir7;
        let t4 = 1.0 - 14.0 * zr2 + 21.0 * zr2 * zr2;
        ax += f4 * x * t4;
        ay += f4 * y * t4;
        az += f4 * z * (5.0 - 70.0 / 3.0 * zr2 + 21.0 * zr2 * zr2);
        if nnode > 0 {
            let u = tau / node_dt;
            let mut i = u as i64;
            if i >= nnode as i64 - 1 {
                i = nnode as i64 - 2;
            } else if i < 0 {
                i = 0;
            }
            let i = i as usize;
            let fr = u - i as f64;
            let lr = prof[i] + (prof[i + 1] - prof[i]) * fr;
            let rho = lr.exp();
            let wx = vx + WE * y;
            let wy = vy - WE * x;
            let vr = (wx * wx + wy * wy + vz * vz).sqrt();
            let q = -half_b * rho * vr;
            ax += q * wx;
            ay += q * wy;
            az += q * vz;
        }
        (ax, ay, az)
    };
    let nsteps = pyr(l / h) as i64;
    let per_node = (pyr(node_dt / h) as i64).max(1);
    let mut nodes = Vec::new();
    let mut prev_alt: Option<f64> = None;
    for k in 0..=nsteps {
        let tau = k as f64 * h;
        let t = tc + tau;
        let r2 = x * x + y * y + z * z;
        let r = r2.sqrt();
        let sphi2 = z * z / r2;
        let alt = r - RE * (1.0 - FLAT * sphi2);
        if record_nodes && k % per_node == 0 {
            nodes.push([t, x, y, z]);
        }
        if !windows.is_empty() {
            let v2 = vx * vx + vy * vy + vz * vz;
            let a_osc = 1.0 / (2.0 / r - v2 / mu);
            for (w, win) in windows.iter().enumerate() {
                if win.0 <= t && t < win.1 {
                    wsum[w] += a_osc;
                    wcnt[w] += 1;
                }
            }
        }
        if let Some(sa) = stop_alt {
            if alt < sa {
                let tcr = match prev_alt {
                    Some(p) if p > alt => t - h * (sa - alt) / (p - alt),
                    _ => t,
                };
                return ChunkRes { state: [x, y, z, vx, vy, vz], nodes, t_cross: Some(tcr) };
            }
        }
        if k == nsteps {
            break;
        }
        prev_alt = Some(alt);
        let a1 = acc(tau, x, y, z, vx, vy, vz);
        let hh = 0.5 * h;
        let (x2, y2, z2) = (x + hh * vx, y + hh * vy, z + hh * vz);
        let (u2, v2_, w2) = (vx + hh * a1.0, vy + hh * a1.1, vz + hh * a1.2);
        let a2 = acc(tau + hh, x2, y2, z2, u2, v2_, w2);
        let (x3, y3, z3) = (x + hh * u2, y + hh * v2_, z + hh * w2);
        let (u3, v3, w3) = (vx + hh * a2.0, vy + hh * a2.1, vz + hh * a2.2);
        let a3 = acc(tau + hh, x3, y3, z3, u3, v3, w3);
        let (x4, y4, z4) = (x + h * u3, y + h * v3, z + h * w3);
        let (u4, v4, w4) = (vx + h * a3.0, vy + h * a3.1, vz + h * a3.2);
        let a4 = acc(tau + h, x4, y4, z4, u4, v4, w4);
        let h6 = h / 6.0;
        x += h6 * (vx + 2.0 * u2 + 2.0 * u3 + u4);
        y += h6 * (vy + 2.0 * v2_ + 2.0 * v3 + v4);
        z += h6 * (vz + 2.0 * w2 + 2.0 * w3 + w4);
        vx += h6 * (a1.0 + 2.0 * a2.0 + 2.0 * a3.0 + a4.0);
        vy += h6 * (a1.1 + 2.0 * a2.1 + 2.0 * a3.1 + a4.1);
        vz += h6 * (a1.2 + 2.0 * a2.2 + 2.0 * a3.2 + a4.2);
        let _ = (x2, y2, z2, x3, y3, z3, x4, y4, z4);
    }
    ChunkRes { state: [x, y, z, vx, vy, vz], nodes, t_cross: None }
}

/// 節點 (t,x,y,z) → (t, lon°[0,360), 地心緯度°, 高度 km)
fn nodes_llh(nodes: &[[f64; 4]]) -> Vec<[f64; 4]> {
    if nodes.is_empty() {
        return vec![];
    }
    let t0 = nodes[0][0];
    let th0 = gstime(t0 / 86400.0 + JD_UNIX0);
    nodes
        .iter()
        .map(|n| {
            let (t, x, y, z) = (n[0], n[1], n[2], n[3]);
            let th = th0 + WE * (t - t0);
            let xe = th.cos() * x + th.sin() * y;
            let ye = -th.sin() * x + th.cos() * y;
            let r = (x * x + y * y + z * z).sqrt();
            let lat = (z / r).asin().to_degrees();
            let lon = ye.atan2(xe).to_degrees().rem_euclid(360.0);
            let alt = r - RE * (1.0 - FLAT * (z / r).powi(2));
            [t, lon, lat, alt]
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn propagate(
    states: &[[f64; 6]],
    bs: &[f64],
    t0: f64,
    t_end: f64,
    sw: &SpaceWeather,
    cutoff: Option<f64>,
    stop_alt: Option<f64>,
    windows: &[(f64, f64)],
    h: f64,
    node_dt: f64,
    chunk_s: f64,
) -> (Vec<Traj>, f64) {
    let (tol_mean, tol_max, max_iter) = (0.02, 0.10, 4usize);
    let nw = windows.len();
    let mut trajs: Vec<Traj> = states
        .iter()
        .zip(bs)
        .map(|(s, b)| Traj { s: *s, b: *b, prof: None, trend: 0.0, active: true, t_cross: None, wsum: vec![0.0; nw], wcnt: vec![0; nw] })
        .collect();
    let chunk_s = (node_dt * 4.0).max(pyr(chunk_s / node_dt) * node_dt);
    let mut tc = t0;
    let nnode = pyr(chunk_s / node_dt) as usize + 1;
    while tc < t_end - 1e-6 && trajs.iter().any(|t| t.active) {
        let mut l = chunk_s.min(t_end - tc);
        l = h.max(pyr(l / h) * h);
        let mut nn = (l / node_dt + 1e-9).floor() as usize + 1;
        if (nn - 1) as f64 * node_dt < l - 1e-6 {
            nn += 1;
        }
        let pending: Vec<usize> = (0..trajs.len()).filter(|&i| trajs[i].active).collect();
        // 第一個 chunk：起點密度常數剖面
        let first: Vec<usize> = pending.iter().copied().filter(|&i| trajs[i].b > 0.0 && trajs[i].prof.is_none()).collect();
        for &i in &first {
            let s = trajs[i].s;
            let p = nodes_llh(&[[tc, s[0], s[1], s[2]]])[0];
            let rr = density(p[0], p[1], p[2], p[3], sw, cutoff);
            trajs[i].prof = Some(vec![rr.ln(); nnode]);
        }
        let mut results: HashMap<usize, (ChunkRes, Option<Vec<f64>>, Vec<f64>, Vec<usize>)> = HashMap::new();
        for &i in &pending {
            let tr = &trajs[i];
            let prof = if tr.b > 0.0 {
                let p = tr.prof.as_ref().unwrap();
                let last = *p.last().unwrap();
                Some((0..nn).map(|k| p.get(k).copied().unwrap_or(last) + tr.trend).collect::<Vec<f64>>())
            } else {
                None
            };
            let mut ws = tr.wsum.clone();
            let mut wc = tr.wcnt.clone();
            let res = integrate_chunk(&tr.s, tr.b, tc, l, h, node_dt, prof.as_deref(), stop_alt, windows, &mut ws, &mut wc, tr.b > 0.0);
            results.insert(i, (res, prof, ws, wc));
        }
        // 密度迭代
        let mut pend = pending.clone();
        for it in 0..max_iter {
            let todo: Vec<usize> = pend.iter().copied().filter(|&i| trajs[i].b > 0.0).collect();
            if todo.is_empty() {
                break;
            }
            let mut redo: Vec<(usize, Vec<f64>)> = Vec::new();
            for &i in &todo {
                let llh = nodes_llh(&results[&i].0.nodes);
                let m = llh.len();
                let lr: Vec<f64> = llh.iter().map(|p| density(p[0], p[1], p[2], p[3], sw, cutoff).ln()).collect();
                let used = results[&i].1.as_ref().unwrap();
                let mut new = lr.clone();
                let lastv = *lr.last().unwrap();
                new.resize(nn.max(m), lastv);
                let dif: Vec<f64> = lr.iter().zip(used.iter()).map(|(a, b)| (a - b).abs()).collect();
                let dmean = dif.iter().sum::<f64>() / dif.len() as f64;
                let dmax = dif.iter().copied().fold(f64::MIN, f64::max);
                if (dmean > tol_mean || dmax > tol_max) && it < max_iter - 1 {
                    redo.push((i, new));
                } else {
                    let tr = &mut trajs[i];
                    if let Some(p) = &tr.prof {
                        if p.len() >= m && m == nn {
                            let ml = lr.iter().sum::<f64>() / m as f64;
                            let mp = p[..m].iter().sum::<f64>() / m as f64;
                            tr.trend = (ml - mp).clamp(-0.5, 0.5);
                        }
                    }
                    tr.prof = Some(new);
                }
            }
            if redo.is_empty() {
                break;
            }
            for (i, new) in &redo {
                let tr = &trajs[*i];
                let mut ws = tr.wsum.clone();
                let mut wc = tr.wcnt.clone();
                let res = integrate_chunk(&tr.s, tr.b, tc, l, h, node_dt, Some(new), stop_alt, windows, &mut ws, &mut wc, true);
                results.insert(*i, (res, Some(new.clone()), ws, wc));
            }
            pend = redo.iter().map(|(i, _)| *i).collect();
        }
        for i in 0..trajs.len() {
            if !trajs[i].active {
                continue;
            }
            let (res, _p, ws, wc) = results.remove(&i).unwrap();
            let tr = &mut trajs[i];
            tr.s = res.state;
            tr.wsum = ws;
            tr.wcnt = wc;
            if let Some(tcr) = res.t_cross {
                tr.active = false;
                tr.t_cross = Some(tcr);
            }
        }
        tc += l;
    }
    (trajs, tc)
}

// ════════════════════════════ 分段校準 ════════════════════════════
fn select_anchors(tl: &[Tle], n_segments: usize) -> Vec<usize> {
    let (min_gap_h, da_km, min_gap_da_h) = (12.0, 10.0, 1.0);
    if tl.is_empty() {
        return vec![];
    }
    let mut anchors = vec![tl.len() - 1];
    let mut cur = tl.len() - 1;
    while anchors.len() <= n_segments {
        let (tcur, acur) = (tl[cur].t, tl[cur].a_kozai);
        let (mut j_time, mut j_da): (i64, i64) = (-1, -1);
        for j in (0..cur).rev() {
            let dt = tcur - tl[j].t;
            if j_da < 0 && dt >= min_gap_da_h * 3600.0 && tl[j].a_kozai - acur >= da_km {
                j_da = j as i64;
            }
            if dt >= min_gap_h * 3600.0 {
                j_time = j as i64;
                break;
            }
        }
        let j = j_time.max(j_da);
        if j < 0 {
            break;
        }
        anchors.push(j as usize);
        cur = j as usize;
    }
    anchors.reverse();
    anchors
}

type SegKey = (String, String, String, String, Option<i64>, u64, bool);
static SEG_CACHE: Lazy<Mutex<HashMap<SegKey, Map<String, Value>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

pub fn iso_z(t: f64) -> String {
    DateTime::from_timestamp(t.floor() as i64, 0)
        .unwrap_or_default()
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

/// 校準結果：Map（輸出欄位）＋未捨入之 B
fn calibrate_segment(t1: &Tle, t2: &Tle, sw: &SpaceWeather, b_guess: f64, h: f64, cutoff: Option<f64>, verify: bool) -> (Map<String, Value>, Option<f64>) {
    let mut cap = None;
    if let (Some(c), Some(d0)) = (cutoff, sw.day0) {
        let cp = ((c - d0) / 86400.0).floor() as i64 - 1;
        cap = Some(cp);
        if d0 + (cp + 1) as f64 * 86400.0 > t2.t + t1.period + 86400.0 {
            cap = None;
        }
    }
    let key: SegKey = (t1.line1.clone(), t1.line2.clone(), t2.line1.clone(), t2.line2.clone(), cap, h.to_bits(), verify);
    if let Some(m) = SEG_CACHE.lock().get(&key) {
        let b = m.get("__B").and_then(Value::as_f64);
        let mut m = m.clone();
        m.remove("__B");
        return (m, b);
    }
    let (mut out, b) = calibrate_segment_inner(t1, t2, sw, b_guess, h, cutoff, verify);
    let mut store = out.clone();
    if let Some(b) = b {
        store.insert("__B".into(), json!(b));
    }
    let mut c = SEG_CACHE.lock();
    if c.len() > 20_000 {
        c.clear();
    }
    c.insert(key, store);
    out.remove("__B");
    (out, b)
}

fn calibrate_segment_inner(t1: &Tle, t2: &Tle, sw: &SpaceWeather, b_guess: f64, h: f64, cutoff: Option<f64>, verify: bool) -> (Map<String, Value>, Option<f64>) {
    let p = t1.period;
    let mut out = Map::new();
    let (a1, a2, s0) = match (sgp4_mean_a(t1, t1.t, p), sgp4_mean_a(t2, t2.t, p), sgp4_state(t1, t1.t)) {
        (Ok(a1), Ok(a2), Ok(s0)) => (a1, a2, s0),
        (Err(e), _, _) | (_, Err(e), _) | (_, _, Err(e)) => {
            out.insert("__error".into(), json!(e));
            return (out, None);
        }
    };
    let da_obs = a2 - a1;
    let win = [(t1.t, t1.t + p), (t2.t, t2.t + p)];
    let t_end = t2.t + p + h;
    out.insert("t_start".into(), json!(iso_z(t1.t)));
    out.insert("t_end".into(), json!(iso_z(t2.t)));
    out.insert("dt_h".into(), json!(py_round((t2.t - t1.t) / 3600.0, 2)));
    out.insert("a_start_km".into(), json!(py_round(a1, 3)));
    out.insert("da_obs_km".into(), json!(py_round(da_obs, 4)));
    let run = |bs: &[f64]| -> Vec<Option<f64>> {
        let states = vec![s0; bs.len()];
        let (trajs, _) = propagate(&states, bs, t1.t, t_end, sw, cutoff, Some(60.0), &win, h, 120.0, p);
        trajs
            .iter()
            .map(|tr| {
                if tr.t_cross.is_some() || tr.wcnt.iter().any(|c| *c == 0) {
                    None
                } else {
                    Some(tr.wsum[1] / tr.wcnt[1] as f64 - tr.wsum[0] / tr.wcnt[0] as f64)
                }
            })
            .collect()
    };
    let mut bg = b_guess.max(1e-4);
    let mut found = None;
    for _ in 0..6 {
        let v = run(&[0.0, bg]);
        if let Some(dg) = v[1] {
            found = Some((v[0], dg));
            break;
        }
        bg *= 0.4;
    }
    let Some((d0, dg)) = found else {
        out.insert("B".into(), Value::Null);
        out.insert("status".into(), json!("calib_failed"));
        return (out, None);
    };
    // d0 為 None 時 Python 會在減法丟 TypeError；B=0 無阻力軌跡實務上不會穿越 60 km
    let Some(d0) = d0 else {
        out.insert("__error".into(), json!("unsupported operand type(s) for -: 'float' and 'NoneType'"));
        return (out, None);
    };
    if (dg - d0).abs() < 1e-9 {
        out.insert("B".into(), Value::Null);
        out.insert("status".into(), json!("no_drag_signal"));
        return (out, None);
    }
    let mut b = bg * (da_obs - d0) / (dg - d0);
    let mut resid: Option<f64> = None;
    if b > 0.0 && verify {
        if let Some(dv) = run(&[b])[0] {
            resid = Some(dv - da_obs);
            if (dv - da_obs).abs() * 1000.0 > 10.0 && (dv - dg).abs() > 1e-12 {
                let b2 = b + (da_obs - dv) * (b - bg) / (dv - dg);
                if b2 > 0.0 {
                    if let Some(dv2) = run(&[b2])[0] {
                        if (dv2 - da_obs).abs() < (dv - da_obs).abs() {
                            b = b2;
                            resid = Some(dv2 - da_obs);
                        }
                    }
                }
            }
        }
    }
    out.insert("B".into(), json!(b));
    out.insert("resid_m".into(), resid.map(|r| json!(py_round(r * 1000.0, 1))).unwrap_or(Value::Null));
    out.insert("da_nodrag_km".into(), json!(py_round(d0, 4)));
    out.insert("status".into(), json!("ok"));
    (out, Some(b))
}

#[allow(clippy::too_many_arguments)]
fn calibrate_segments(tl: &[Tle], n_segments: usize, sw: &SpaceWeather, cutoff: Option<f64>, h: f64, mass_kg: f64, cd: f64, verify: bool) -> Result<Vec<Map<String, Value>>, String> {
    let (jump_ratio, raise_km) = (2.0, 0.3);
    let anchors = select_anchors(tl, n_segments);
    let mut segs: Vec<Map<String, Value>> = Vec::new();
    let mut bprev = 0.03;
    for w in anchors.windows(2) {
        let (mut seg, b) = calibrate_segment(&tl[w[0]], &tl[w[1]], sw, bprev, h, cutoff, verify);
        if let Some(e) = seg.remove("__error") {
            return Err(e.as_str().unwrap_or("").to_string());
        }
        seg.insert("A_eff_m2".into(), b.map(|b| json!(py_round(b * mass_kg / cd, 2))).unwrap_or(Value::Null));
        if let Some(b) = b {
            seg.insert("B".into(), json!(py_round(b, 6)));
        }
        let da_obs = seg.get("da_obs_km").and_then(Value::as_f64).unwrap_or(0.0);
        let mut flag: Option<&str> = None;
        if da_obs > raise_km || b.is_some_and(|b| b <= 0.0) {
            flag = Some("raise");
        } else {
            let refs: Vec<f64> = segs
                .iter()
                .filter(|s| s.get("B").and_then(Value::as_f64).is_some_and(|b| b != 0.0) && s.get("thrust_flag").is_none_or(Value::is_null))
                .filter_map(|s| s.get("B").and_then(Value::as_f64))
                .collect();
            let refs = &refs[refs.len().saturating_sub(4)..];
            if let Some(b) = b {
                if !refs.is_empty() && b > jump_ratio * median(refs) {
                    flag = Some("jump");
                }
            }
        }
        seg.insert("thrust_flag".into(), flag.map(|f| json!(f)).unwrap_or(Value::Null));
        if let Some(b) = b {
            if b > 0.0 {
                bprev = b;
            }
        }
        segs.push(seg);
    }
    for k in 0..segs.len() {
        if segs[k].get("thrust_flag").and_then(Value::as_str) == Some("jump") {
            let bk = segs[k].get("B").and_then(Value::as_f64).unwrap_or(f64::NAN);
            let later: Vec<f64> = segs[k + 1..]
                .iter()
                .filter_map(|x| x.get("B").and_then(Value::as_f64))
                .filter(|b| *b != 0.0)
                .collect();
            if later.len() >= 2 && later.iter().all(|b| (b / bk - 1.0).abs() < 0.35) {
                segs[k].insert("thrust_flag".into(), json!("jump_persistent"));
            }
        }
    }
    Ok(segs)
}

fn median(v: &[f64]) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(f64::total_cmp);
    let n = s.len();
    if n % 2 == 1 {
        s[n / 2]
    } else {
        (s[n / 2 - 1] + s[n / 2]) / 2.0
    }
}

fn seg_b(s: &Map<String, Value>) -> Option<f64> {
    s.get("B").and_then(Value::as_f64).filter(|b| *b != 0.0)
}
fn seg_flag(s: &Map<String, Value>) -> bool {
    s.get("thrust_flag").is_some_and(|f| !f.is_null())
}

pub struct PredictOpts {
    pub n_segments: usize,
    pub max_days: f64,
    pub stop_alt_km: f64,
    pub verify: bool,
}

/// 分段 M/A 校準 + 前向數值積分之再入預測（同 Python `predict_reentry`，exact_window=False）
pub fn predict_reentry(rows: &[(String, String)], sw: &SpaceWeather, o: &PredictOpts) -> Value {
    let (h, spread_floor, mass_kg, cd) = (15.0, 0.15, 800.0, 2.2);
    let tstart = Instant::now();
    let tl = parse_tles(rows);
    let cut: Option<f64> = None;
    if tl.len() < 2 {
        return json!({"error": "可用 TLE 少於 2 筆"});
    }
    let segs = match calibrate_segments(&tl, o.n_segments, sw, cut, h, mass_kg, cd, o.verify) {
        Ok(s) => s,
        Err(e) => return json!({"error": e}),
    };
    let t_cal = tstart.elapsed().as_secs_f64();
    let good: Vec<&Map<String, Value>> = segs.iter().filter(|s| seg_b(s).is_some_and(|b| b > 0.0)).collect();
    if good.is_empty() {
        return json!({"error": "無有效校準段", "segments": segs});
    }
    let last = segs.last().unwrap();
    let reliable = !seg_flag(last) && last.get("B").and_then(Value::as_f64).is_some_and(|b| b > 0.0);
    let k_last_flag: i64 = segs.iter().enumerate().filter(|(_, s)| seg_flag(s)).map(|(i, _)| i as i64).max().unwrap_or(-1);
    let stable: Vec<f64> = segs[(k_last_flag + 1) as usize..].iter().filter_map(seg_b).filter(|b| *b > 0.0).collect();
    let (b_nom, rec) = if !stable.is_empty() {
        let bn = *stable.last().unwrap();
        (bn, stable[stable.len().saturating_sub(3)..].to_vec())
    } else {
        let bn = seg_b(good.last().unwrap()).unwrap();
        (bn, vec![bn])
    };
    let rmin = rec.iter().copied().fold(f64::INFINITY, f64::min);
    let rmax = rec.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let b_lo = rmin.min(b_nom * (1.0 - spread_floor));
    let b_hi = rmax.max(b_nom * (1.0 + spread_floor));
    let t0 = tl.last().unwrap();
    let s0 = match sgp4_state(t0, t0.t) {
        Ok(s) => s,
        Err(e) => return json!({"error": e}),
    };
    let (trajs, _) = propagate(&[s0], &[b_nom], t0.t, t0.t + o.max_days * 86400.0, sw, cut, Some(o.stop_alt_km), &[], h, 120.0, t0.period);
    let tn = trajs[0].t_cross;
    let th = tn.map(|tn| t0.t + (tn - t0.t) * b_nom / b_hi);
    let tlo = tn.map(|tn| t0.t + (tn - t0.t) * b_nom / b_lo);
    let elapsed = tstart.elapsed().as_secs_f64();
    let sw_hold = match (sw.day0, sw.last_obs_day) {
        (Some(d0), Some(cap)) => Some(iso_z(d0 + cap as f64 * 86400.0)[..10].to_string()),
        _ => None,
    };
    let flag_any = segs.iter().any(seg_flag);
    let latest_flag = last.get("thrust_flag").cloned().unwrap_or(Value::Null);
    json!({
        "method": "segmented_ma_v1",
        "tle_last_epoch": iso_z(t0.t),
        "cutoff": Value::Null,
        "n_tles_used": tl.len(),
        "segments": segs,
        "B_used": {"nominal": py_round(b_nom, 6), "low": py_round(b_lo, 6), "high": py_round(b_hi, 6)},
        "A_eff_used_m2": py_round(b_nom * mass_kg / cd, 2),
        "reentry_utc": tn.map(iso_z),
        "window_early_utc": th.map(iso_z),
        "window_late_utc": tlo.map(iso_z),
        "beyond_horizon": tn.is_none(),
        "hours_from_last_tle": tn.map(|tn| py_round((tn - t0.t) / 3600.0, 2)),
        "reentry_unix": tn, "early_unix": th, "late_unix": tlo,
        "reliable": reliable,
        "thrust_suspected": flag_any,
        "latest_segment_flag": latest_flag,
        "stop_alt_km": o.stop_alt_km,
        "space_weather": {"source": sw.path, "persisted_from": sw_hold,
                          "note": "截止日之後 F10.7 / Ap 以最後已知日值持平（persistence）"},
        "force_model": "two-body + J2/J3/J4 + NRLMSISE-00 drag (co-rotating atmosphere); RK4 fixed step",
        "timing_s": {"calibration": py_round(t_cal, 2), "total": py_round(elapsed, 2)},
    })
}
