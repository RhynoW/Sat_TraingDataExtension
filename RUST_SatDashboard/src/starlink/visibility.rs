//! Starlink 服務能力分析：可見性時間序列、RTT 下限、天空密度、覆蓋空窗、遮蔽模擬
//! （Python 版 physics/starlink_analysis.py 的移植，含 operational_perigee_floor 自動殼層門檻）。

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use rayon::prelude::*;
use serde_json::{json, Value};

use super::census;
use super::common::{self, py_iso_utc, py_round};
use crate::physics::Observer;
use crate::state::AppState;

const CACHE_TTL_S: i64 = 600;
const C_KM_MS: f64 = 299792.458 / 1000.0;
const MAX_STEPS: i64 = 288;
const MAX_JOBS: usize = 2;
const MAX_CACHE: usize = 16;

pub const MIN_OPERATIONAL_PERIGEE_KM: f64 = 330.0;
const SHELL_BIN_KM: f64 = 10.0;
const SHELL_SCAN_KM: (f64, f64) = (150.0, 700.0);
const SHELL_PEAK_MIN_KM: f64 = 250.0;
const SHELL_PEAK_FRAC: f64 = 0.02;
const SHELL_PEAK_MIN_N: f64 = 50.0;
const SHELL_EDGE_FRAC: f64 = 0.05;
const SHELL_FLOOR_CLAMP: (f64, f64) = (250.0, 450.0);
const SHELL_MIN_SAMPLES: usize = 500;

#[derive(Clone, PartialEq, Eq, Hash)]
pub struct Key {
    lat: i64,
    lon: i64,
    mask: i64,
    hours: i64,
    step: i64,
    generation: String,
    dropout: i64,
    excl: bool,
}

#[derive(Clone)]
pub struct Params {
    pub lat: f64,
    pub lon: f64,
    pub mask: f64,
    pub hours: i64,
    pub step: i64,
    pub generation: String,
    pub dropout: f64,
    pub exclude_deorbiting: bool,
}

impl Params {
    fn key(&self) -> Key {
        let r = |x: f64, d: usize| (py_round(x, d) * 10f64.powi(d as i32)).round() as i64;
        Key {
            lat: r(self.lat, 3),
            lon: r(self.lon, 3),
            mask: r(self.mask, 1),
            hours: self.hours,
            step: self.step,
            generation: self.generation.clone(),
            dropout: r(self.dropout, 1),
            excl: self.exclude_deorbiting,
        }
    }
}

/// 讓 hours*60/step ≤ MAX_STEPS
pub fn clamp_step(hours: i64, step: i64) -> i64 {
    step.max((hours * 60 + MAX_STEPS - 1) / MAX_STEPS)
}

struct Occ {
    occ: Vec<i16>, // [az][el][t]
    n_az: usize,
    n_el: usize,
    n_steps: usize,
    el_min: f64,
}

struct Entry {
    result: Arc<Value>,
    occ: Option<Arc<Occ>>,
    at: DateTime<Utc>,
}

static CACHE: Lazy<Mutex<HashMap<Key, Entry>>> = Lazy::new(|| Mutex::new(HashMap::new()));
static COMPUTING: Lazy<Mutex<HashSet<Key>>> = Lazy::new(|| Mutex::new(HashSet::new()));

fn evict_locked(c: &mut HashMap<Key, Entry>) {
    let now = Utc::now();
    c.retain(|_, e| (now - e.at).num_seconds() < CACHE_TTL_S);
    while c.len() > MAX_CACHE {
        let k = c.iter().min_by_key(|(_, e)| e.at).map(|(k, _)| k.clone()).unwrap();
        c.remove(&k);
    }
}

/// 非同步計算並快取；回傳 Some(結果) 或 None（背景計算中 → 202）
pub fn compute_visibility(st: &Arc<AppState>, mut p: Params) -> Option<Arc<Value>> {
    p.step = clamp_step(p.hours, p.step);
    let key = p.key();
    if let Some(e) = CACHE.lock().get(&key) {
        if (Utc::now() - e.at).num_seconds() < CACHE_TTL_S {
            return Some(e.result.clone());
        }
    }
    {
        let mut c = COMPUTING.lock();
        if c.contains(&key) || c.len() >= MAX_JOBS {
            return None;
        }
        c.insert(key.clone());
    }
    let st = st.clone();
    std::thread::spawn(move || {
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| do_compute(&st, &p)));
        let entry = match r {
            Ok((res, occ)) => Entry { result: Arc::new(res), occ: Some(Arc::new(occ)), at: Utc::now() },
            Err(_) => {
                tracing::error!("Starlink 可見性計算失敗");
                Entry { result: Arc::new(json!({"error": "計算失敗", "timeline": [], "stats": {}})), occ: None, at: Utc::now() }
            }
        };
        {
            let mut c = CACHE.lock();
            c.insert(key.clone(), entry);
            evict_locked(&mut c);
        }
        COMPUTING.lock().remove(&key);
    });
    None
}

/// 套用水平線遮蔽（不重跑 SGP4，由佔用矩陣扣除）；None ＝ 基礎資料未就緒（409）
pub fn compute_obstruction(mut p: Params, blocked: &[[f64; 2]]) -> Option<Value> {
    p.step = clamp_step(p.hours, p.step);
    let key = p.key();
    let (main, occ) = {
        let c = CACHE.lock();
        let e = c.get(&key)?;
        if (Utc::now() - e.at).num_seconds() >= CACHE_TTL_S {
            return None;
        }
        (e.result.clone(), e.occ.clone()?)
    };
    let tl = main.get("timeline")?.as_array()?;
    let n_steps = occ.n_steps;
    let mut obstructed = vec![0i32; n_steps];
    for c in blocked {
        let az_i = ((c[0] / 10.0) as i64).rem_euclid(occ.n_az as i64) as usize;
        let el_i = ((c[1] - occ.el_min) / 5.0) as i64;
        if el_i >= 0 && (el_i as usize) < occ.n_el {
            let base = (az_i * occ.n_el + el_i as usize) * n_steps;
            for (t, o) in obstructed.iter_mut().enumerate() {
                *o += occ.occ[base + t] as i32;
            }
        }
    }
    let new_vis: Vec<i64> = (0..n_steps)
        .map(|j| (tl.get(j).and_then(|e| e["visible"].as_i64()).unwrap_or(0) - obstructed[j] as i64).max(0))
        .collect();
    let ts: Vec<Value> = tl.iter().map(|e| e["ts"].clone()).collect();
    let timeline: Vec<Value> = (0..n_steps)
        .map(|j| {
            json!({"ts": ts.get(j).cloned().unwrap_or(Value::Null), "visible": new_vis[j], "available": new_vis[j] >= 1,
                   "rtt_floor_ms": tl.get(j).map(|e| e["rtt_floor_ms"].clone()).unwrap_or(Value::Null)})
        })
        .collect();
    let gaps = detect_gaps(&new_vis.iter().map(|v| *v >= 1).collect::<Vec<_>>(), &ts, p.step);
    let avail = new_vis.iter().filter(|v| **v >= 1).count();
    let new_pct = py_round(100.0 * avail as f64 / n_steps as f64, 2);
    let mean = new_vis.iter().sum::<i64>() as f64 / n_steps as f64;
    let orig_pct = main["stats"]["availability_pct"].as_f64().unwrap_or(0.0);
    Some(json!({
        "timeline": timeline,
        "gaps": gaps,
        "blocked_count": blocked.len(),
        "stats": {
            "mean_visible": py_round(mean, 1),
            "min_visible": new_vis.iter().min().copied().unwrap_or(0),
            "max_visible": new_vis.iter().max().copied().unwrap_or(0),
            "gap_count": gaps.len(),
            "gap_total_min": gaps.iter().map(|g| g["duration_min"].as_i64().unwrap_or(0)).sum::<i64>(),
            "availability_pct": new_pct,
            "delta_pct": py_round(new_pct - orig_pct, 2),
        },
        "original_stats": main["stats"].clone(),
        "mask_deg": p.mask,
        "step_min": p.step,
    }))
}

fn detect_gaps(avail: &[bool], ts: &[Value], step: i64) -> Vec<Value> {
    let n = avail.len();
    let mut gaps = Vec::new();
    let mut start: Option<usize> = None;
    for (j, a) in avail.iter().enumerate() {
        if !a && start.is_none() {
            start = Some(j);
        } else if *a {
            if let Some(s) = start.take() {
                gaps.push(json!({"start": ts[s], "end": ts[j], "duration_min": (j - s) as i64 * step}));
            }
        }
    }
    if let Some(s) = start {
        gaps.push(json!({"start": ts[s], "end": ts[n - 1], "duration_min": (n - 1 - s) as i64 * step}));
    }
    gaps
}

/// TLE 第 2 行平均運動與離心率 → 近地點高度（km）
fn perigee_km(line2: &str) -> Option<f64> {
    let n = line2.get(52..63)?.trim().parse::<f64>().ok()? * 2.0 * std::f64::consts::PI / 86400.0;
    let e = format!("0.{}", line2.get(26..33)?.trim()).parse::<f64>().ok()?;
    if n <= 0.0 {
        return None;
    }
    let a = (common::MU / (n * n)).powf(1.0 / 3.0);
    Some(a * (1.0 - e) - common::RE)
}

/// 依近地點分布自動判定作業殼層下緣（km），回傳 (門檻, "auto"|"fallback")
pub fn operational_perigee_floor(perigees: &[Option<f64>]) -> (f64, &'static str) {
    let pg: Vec<f64> = perigees.iter().flatten().copied().filter(|p| p.is_finite()).collect();
    if pg.len() < SHELL_MIN_SAMPLES {
        return (MIN_OPERATIONAL_PERIGEE_KM, "fallback");
    }
    // np.histogram(pg, bins=arange(150, 710, 10))：55 格、最後一格含右端點
    let edges: Vec<f64> = (0..).map(|i| SHELL_SCAN_KM.0 + i as f64 * SHELL_BIN_KM).take_while(|e| *e < SHELL_SCAN_KM.1 + SHELL_BIN_KM).collect();
    let nb = edges.len() - 1;
    let mut counts = vec![0usize; nb];
    let (first, last) = (edges[0], edges[nb]);
    for &x in &pg {
        if x < first || x > last {
            continue;
        }
        let mut i = ((x - first) / SHELL_BIN_KM) as usize;
        if i >= nb {
            i = nb - 1;
        }
        if x < edges[i] {
            i -= 1;
        } else if i + 1 < nb && x >= edges[i + 1] {
            i += 1;
        }
        counts[i] += 1;
    }
    let need = SHELL_PEAK_MIN_N.max(SHELL_PEAK_FRAC * pg.len() as f64);
    let Some(mut peak) = (0..nb).find(|&i| counts[i] as f64 >= need && edges[i] >= SHELL_PEAK_MIN_KM) else {
        return (MIN_OPERATIONAL_PERIGEE_KM, "fallback");
    };
    while peak + 1 < nb && counts[peak + 1] > counts[peak] {
        peak += 1;
    }
    let cut = SHELL_EDGE_FRAC * counts[peak] as f64;
    let mut i = peak;
    while i >= 1 && counts[i - 1] as f64 >= cut {
        i -= 1;
    }
    let floor = edges[i] - SHELL_BIN_KM;
    (floor.max(SHELL_FLOOR_CLAMP.0).min(SHELL_FLOOR_CLAMP.1), "auto")
}

// ── numpy.random.default_rng(seed).random()（SeedSequence + PCG64 XSL-RR）───────
pub struct Pcg64 {
    state: u128,
    inc: u128,
}

impl Pcg64 {
    const MULT: u128 = (2549297995355413924u128 << 64) | 4865540595714422341u128;

    pub fn from_seed(seed: u32) -> Self {
        // SeedSequence(seed).generate_state(4, uint64)
        const INIT_A: u32 = 0x43b0d7e5;
        const MULT_A: u32 = 0x931e8875;
        const INIT_B: u32 = 0x8b51f9dd;
        const MULT_B: u32 = 0x58f38ded;
        const MIX_L: u32 = 0xca01f9dd;
        const MIX_R: u32 = 0x4973f715;
        let mut hc = INIT_A;
        let hashmix = |v: u32, hc: &mut u32| -> u32 {
            let mut v = v ^ *hc;
            *hc = hc.wrapping_mul(MULT_A);
            v = v.wrapping_mul(*hc);
            v ^ (v >> 16)
        };
        let mix = |x: u32, y: u32| -> u32 {
            let r = MIX_L.wrapping_mul(x).wrapping_sub(MIX_R.wrapping_mul(y));
            r ^ (r >> 16)
        };
        let entropy = [seed];
        let mut pool = [0u32; 4];
        for (i, p) in pool.iter_mut().enumerate() {
            *p = hashmix(entropy.get(i).copied().unwrap_or(0), &mut hc);
        }
        for s in 0..4 {
            for d in 0..4 {
                if s != d {
                    let h = hashmix(pool[s], &mut hc);
                    pool[d] = mix(pool[d], h);
                }
            }
        }
        let mut words = [0u32; 8];
        let mut hb = INIT_B;
        for (i, w) in words.iter_mut().enumerate() {
            let mut v = pool[i % 4] ^ hb;
            hb = hb.wrapping_mul(MULT_B);
            v = v.wrapping_mul(hb);
            *w = v ^ (v >> 16);
        }
        let u = |k: usize| (words[2 * k] as u64) | ((words[2 * k + 1] as u64) << 32);
        let initstate = ((u(0) as u128) << 64) | u(1) as u128;
        let initseq = ((u(2) as u128) << 64) | u(3) as u128;
        let mut r = Self { state: 0, inc: (initseq << 1) | 1 };
        r.step();
        r.state = r.state.wrapping_add(initstate);
        r.step();
        r
    }
    fn step(&mut self) {
        self.state = self.state.wrapping_mul(Self::MULT).wrapping_add(self.inc);
    }
    pub fn next_u64(&mut self) -> u64 {
        self.step();
        let hi = (self.state >> 64) as u64;
        let lo = self.state as u64;
        (hi ^ lo).rotate_right((hi >> 58) as u32)
    }
    pub fn random(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / 9007199254740992.0)
    }
}

fn err_result(msg: &str, mask: f64) -> (Value, Occ) {
    (
        json!({"error": msg, "timeline": [], "stats": {}}),
        Occ { occ: vec![0; 36 * 13], n_az: 36, n_el: 13, n_steps: 1, el_min: mask },
    )
}

fn do_compute(st: &Arc<AppState>, p: &Params) -> (Value, Occ) {
    let idx = st.index();
    let all: Vec<u32> = idx.sats.values().filter(|s| s.name.to_uppercase().contains("STARLINK")).map(|s| s.norad_id).collect();
    let all_set: HashSet<u32> = all.iter().copied().collect();
    let generation = p.generation.as_str();
    let mut cand: Vec<u32> = if generation.is_empty() || generation == "all" {
        all.clone()
    } else {
        let g = census::starlink_ids_by_generation(st, generation);
        let mut v: Vec<u32> = all_set.intersection(&g).copied().collect();
        v.sort_unstable();
        v
    };
    let mut excluded_deorbiting = 0usize;
    if p.exclude_deorbiting {
        let de = census::deorbiting_norad_ids(st);
        let before = cand.len();
        cand.retain(|n| !de.contains(n));
        excluded_deorbiting = before - cand.len();
    }
    let perigee: HashMap<u32, Option<f64>> = all.iter().map(|n| (*n, perigee_km(&idx.sats[n].line2))).collect();
    let pvals: Vec<Option<f64>> = all.iter().map(|n| perigee[n]).collect();
    let (min_perigee, method) = operational_perigee_floor(&pvals);
    let before = cand.len();
    cand.retain(|n| perigee.get(n).copied().flatten().unwrap_or(0.0) >= min_perigee);
    let excluded_low = before - cand.len();

    let dropout = p.dropout.clamp(0.0, 90.0);
    let mut dropped = 0usize;
    if dropout > 0.0 && !cand.is_empty() {
        let mut rng = Pcg64::from_seed(20260909);
        let keep: Vec<bool> = (0..cand.len()).map(|_| rng.random() >= dropout / 100.0).collect();
        dropped = keep.iter().filter(|k| !**k).count();
        cand = cand.iter().zip(&keep).filter(|(_, k)| **k).map(|(n, _)| *n).collect();
    }
    if all.is_empty() {
        return err_result("資料庫中無 STARLINK 衛星", p.mask);
    }
    if cand.is_empty() {
        return err_result("篩選條件（世代／備援情境）後無剩餘衛星，請放寬條件", p.mask);
    }
    tracing::info!(
        "Starlink 計算開始：({:.3},{:.3}) mask={:.1}° {}h@{}min N={}（世代={} 排除離軌={} 備援丟棄={}）",
        p.lat, p.lon, p.mask, p.hours, p.step, cand.len(), generation, excluded_deorbiting, dropped
    );

    let t0 = Utc::now();
    let obs = Observer::new(p.lat, p.lon, 0.01);
    let n_steps = (p.hours * 60 / p.step) as usize + 1;
    let times: Vec<DateTime<Utc>> = (0..n_steps).map(|i| t0 + Duration::minutes(i as i64 * p.step)).collect();
    let gmst: Vec<f64> = times.iter().map(|t| common::gmst_py(common::jd_of_unix(common::unix_of(t)), false)).collect();
    let mask = p.mask;
    let el_min = mask;
    let n_az = 36usize;
    let n_el = (((90.0 - el_min) / 5.0) as usize).max(1);

    // 每顆：各時刻 (可見, el, az, rng)
    let per_sat: Vec<Vec<Option<(f64, f64, f64)>>> = cand
        .par_iter()
        .map(|n| {
            let s = &idx.sats[n];
            let prop = s.prop.as_ref();
            times
                .iter()
                .zip(&gmst)
                .map(|(t, g)| {
                    let r = prop.and_then(|pp| pp.position(t))?;
                    let (el, az, rng) = obs.elaz(&r, *g);
                    (el >= mask).then_some((el, az, rng))
                })
                .collect()
        })
        .collect();

    let mut visible_counts = vec![0i64; n_steps];
    let mut min_rng = vec![f64::INFINITY; n_steps];
    let mut occ = vec![0i16; n_az * n_el * n_steps];
    let az_edges: Vec<f64> = (0..=36).map(|i| i as f64 * 10.0).collect();
    let el_edges: Vec<f64> = (0..).map(|i| el_min + i as f64 * 5.0).take_while(|e| *e < 91.0).collect();
    let n_eb = el_edges.len().saturating_sub(1);
    let mut hist = vec![0u64; 36 * n_eb.max(1)];
    let bin = |edges: &[f64], x: f64| -> Option<usize> {
        let k = edges.partition_point(|e| *e <= x);
        let mut k = k as i64 - 1;
        if x == *edges.last()? {
            k -= 1;
        }
        (k >= 0 && (k as usize) < edges.len() - 1).then_some(k as usize)
    };
    for sat in &per_sat {
        for (t, v) in sat.iter().enumerate() {
            let Some((el, az, rng)) = v else { continue };
            visible_counts[t] += 1;
            if *rng < min_rng[t] {
                min_rng[t] = *rng;
            }
            let ai = ((az / 10.0) as i64).clamp(0, n_az as i64 - 1) as usize;
            let ei = (((el - el_min) / 5.0) as i64).clamp(0, n_el as i64 - 1) as usize;
            occ[(ai * n_el + ei) * n_steps + t] += 1;
            if n_eb >= 1 {
                // np.histogram2d 中 x == 最後一條邊時，numpy 先 searchsorted(side=right) 再減一
                if let (Some(i), Some(j)) = (bin(&az_edges, *az), bin(&el_edges, *el)) {
                    hist[i * n_eb + j] += 1;
                }
            }
        }
    }
    let rtt: Vec<Option<f64>> = min_rng.iter().map(|r| r.is_finite().then(|| 2.0 * r / C_KM_MS)).collect();

    let mut sky = Vec::new();
    if n_eb >= 1 && hist.iter().any(|h| *h > 0) {
        let mx = *hist.iter().max().unwrap() as f64;
        for i in 0..36 {
            for j in 0..n_eb {
                let h = hist[i * n_eb + j];
                if h > 0 {
                    sky.push(json!([
                        py_round((az_edges[i] + az_edges[i + 1]) / 2.0, 1),
                        py_round((el_edges[j] + el_edges[j + 1]) / 2.0, 1),
                        py_round(100.0 * h as f64 / mx, 1),
                    ]));
                }
            }
        }
    }

    let ts: Vec<Value> = times.iter().map(|t| json!(py_iso_utc(t))).collect();
    let timeline: Vec<Value> = (0..n_steps)
        .map(|j| {
            json!({"ts": ts[j], "visible": visible_counts[j], "available": visible_counts[j] >= 1,
                   "rtt_floor_ms": rtt[j].map(|v| py_round(v, 2))})
        })
        .collect();
    let gaps = detect_gaps(&visible_counts.iter().map(|v| *v >= 1).collect::<Vec<_>>(), &ts, p.step);
    let avail = visible_counts.iter().filter(|v| **v >= 1).count();
    let valid: Vec<f64> = rtt.iter().flatten().copied().collect();
    let vmean = visible_counts.iter().sum::<i64>() as f64 / n_steps as f64;
    let stat = |f: fn(&[f64]) -> f64| if valid.is_empty() { Value::Null } else { json!(py_round(f(&valid), 2)) };
    let result = json!({
        "observer": {"lat": p.lat, "lon": p.lon, "mask_deg": p.mask},
        "timeline": timeline,
        "gaps": gaps,
        "sky_density": sky,
        "stats": {
            "total_sats": cand.len(),
            "total_known_starlink": all.len(),
            "generation_filter": generation,
            "excluded_deorbiting_count": excluded_deorbiting,
            "excluded_low_orbit_count": excluded_low,
            "min_operational_perigee_km": min_perigee,
            "min_operational_perigee_method": method,
            "dropout_pct": dropout,
            "dropped_count": dropped,
            "mean_visible": py_round(vmean, 1),
            "min_visible": visible_counts.iter().min().copied().unwrap_or(0),
            "max_visible": visible_counts.iter().max().copied().unwrap_or(0),
            "gap_count": gaps.len(),
            "gap_total_min": gaps.iter().map(|g| g["duration_min"].as_i64().unwrap_or(0)).sum::<i64>(),
            "availability_pct": py_round(100.0 * avail as f64 / n_steps as f64, 2),
            "gap_threshold": 1,
            "mean_rtt_floor_ms": stat(|v| v.iter().sum::<f64>() / v.len() as f64),
            "min_rtt_floor_ms": stat(|v| v.iter().copied().fold(f64::INFINITY, f64::min)),
            "max_rtt_floor_ms": stat(|v| v.iter().copied().fold(f64::NEG_INFINITY, f64::max)),
            "rtt_note": "純幾何傳播延遲；台灣無本地閘道時實際 RTT 估加 30~50ms",
        },
        "computed_at": py_iso_utc(&t0),
        "hours": p.hours,
        "step_min": p.step,
        "mask_deg": p.mask,
    });
    tracing::info!("Starlink 計算完成：{:.2}% 可用，{} 次空窗", 100.0 * avail as f64 / n_steps as f64, gaps.len());
    (result, Occ { occ, n_az, n_el, n_steps, el_min })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pcg64_matches_numpy() {
        // np.random.default_rng(20260909).random(3)
        let mut r = Pcg64::from_seed(20260909);
        let v: Vec<f64> = (0..3).map(|_| r.random()).collect();
        let want = [0.9990195842885582, 0.4649528152763256, 0.10341647129708054];
        for (a, b) in v.iter().zip(want.iter()) {
            assert_eq!(a, b);
        }
    }
}
