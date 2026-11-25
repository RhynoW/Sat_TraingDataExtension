//! 過頂預報（客戶回饋第 6、7、8 項）：多中心點（可設半徑）、最長 62 天、輸出 CSV；
//! 偵照角度（離天底角）判定可偵照時段；中心點日照（太陽仰角、日出日落）；歷史 TLE 預報誤差估算。
//!
//! 判定方式：
//! - 過頂時段：中心點仰角 ≥ 門檻（半徑 > 0 時改用「星下點與中心的地心角 ≤ 仰角門檻對應地心角＋半徑」）。
//! - 可偵照時段：中心點相對衛星的離天底角 ≤ 偵照角度（半徑 > 0 時用偵照角度對應的地面半徑＋區域半徑）。
//!   偵照角度取衛星所屬群組的設定（子群組沿用上層），群組沒設定時用請求的預設值。
//! - 日照：TCA 當下中心點太陽仰角（astronomy-engine）；日出日落以 −0.833°（含大氣折射與日面半徑）計算。
//! - 歷史誤差：同一顆衛星在資料庫中兩筆 TLE 互相比對——舊 TLE 傳播到新 TLE 的曆元，與新 TLE 位置相減，
//!   依提前天數分組統計位置誤差與沿軌時間誤差（沿軌誤差 ÷ 速度），再依每筆過頂距 TLE 曆元的天數標上預估時間誤差。
//!
//! 地球以球體（6371 km）計算地心角與偵照地面半徑，仰角、離天底角用橢球站心座標精確計算。

use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use chrono::{DateTime, Duration, FixedOffset, NaiveTime, TimeZone, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::auth::{atomic_write, Caller};
use crate::config::{Config, RAW_TABLE};
use crate::physics::{eci_to_llh, gmst_rad, teme_to_ecef, Observer, Propagator};
use crate::satadmin::tle_epoch;
use crate::state::AppState;

const RE: f64 = 6371.0;
const MAX_DAYS: f64 = 62.0;
const MAX_SATS: usize = 1000;
const MAX_TARGETS: usize = 30;
const LEAD_BUCKETS: [f64; 9] = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 14.0, 21.0, 30.0];

// ── 中心點 ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Site {
    pub name: String,
    pub lat: f64,
    pub lon: f64,
    #[serde(default)]
    pub alt_m: f64,
    /// 預報範圍半徑（km）；0＝只看中心點
    #[serde(default)]
    pub radius_km: f64,
    #[serde(default)]
    pub note: String,
}

fn sites_file(cfg: &Config) -> std::path::PathBuf {
    cfg.home.join("user_private").join("forecast_sites.json")
}

fn default_sites() -> Vec<Site> {
    vec![Site { name: "台北".into(), lat: 25.0330, lon: 121.5654, alt_m: 10.0, radius_km: 0.0, note: String::new() }]
}

fn load_sites(cfg: &Config) -> Vec<Site> {
    std::fs::read(sites_file(cfg)).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_else(default_sites)
}

fn check_site(s: &Site) -> Result<(), String> {
    if s.name.trim().is_empty() || s.name.chars().count() > 64 {
        return Err("中心點名稱需 1–64 字元".into());
    }
    if !(-90.0..=90.0).contains(&s.lat) || !(-180.0..=360.0).contains(&s.lon) {
        return Err(format!("「{}」經緯度超出範圍", s.name));
    }
    if !(0.0..=3000.0).contains(&s.radius_km) {
        return Err(format!("「{}」半徑需介於 0–3000 km", s.name));
    }
    if !(-500.0..=9000.0).contains(&s.alt_m) {
        return Err(format!("「{}」高度需介於 −500–9000 m", s.name));
    }
    Ok(())
}

struct Target {
    site: Site,
    obs: Observer,
    unit: [f64; 3],
    r_rad: f64,
}

impl Target {
    fn new(s: Site) -> Self {
        let (la, lo) = (s.lat.to_radians(), s.lon.to_radians());
        Self {
            obs: Observer::new(s.lat, s.lon, s.alt_m / 1000.0),
            unit: [la.cos() * lo.cos(), la.cos() * lo.sin(), la.sin()],
            r_rad: s.radius_km / RE,
            site: s,
        }
    }
}

// ── 幾何 ─────────────────────────────────────────────────────────────────────

/// 仰角門檻 ε 對應之最大地心角（rad）
fn lam_eps(h: f64, eps_deg: f64) -> f64 {
    let e = eps_deg.to_radians();
    ((RE * e.cos() / (RE + h)).clamp(-1.0, 1.0)).acos() - e
}

/// 離天底角 η 對應之地心角（rad）；超過地平則取地平
pub fn lam_eta(h: f64, eta_deg: f64) -> f64 {
    let s = (RE + h) / RE * eta_deg.to_radians().sin();
    if s >= 1.0 {
        lam_eps(h, 0.0)
    } else {
        s.asin() - eta_deg.to_radians()
    }
}

#[derive(Debug, Clone, Copy)]
struct Geo {
    el: f64,
    az: f64,
    rng: f64,
    off_nadir: f64,
    lam: f64,
    sub_lat: f64,
    sub_lon: f64,
    alt: f64,
}

struct SatState {
    r: [f64; 3],
    g: f64,
    llh: [f64; 3],
    u: [f64; 3],
}

fn sat_state(p: &Propagator, t: &DateTime<Utc>) -> Option<SatState> {
    let r = p.position(t)?;
    let g = gmst_rad(t);
    let llh = eci_to_llh(&r, g);
    let (la, lo) = (llh[0].to_radians(), llh[1].to_radians());
    Some(SatState { r, g, llh, u: [la.cos() * lo.cos(), la.cos() * lo.sin(), la.sin()] })
}

fn geo(s: &SatState, tg: &Target) -> Geo {
    let (el, az, rng) = tg.obs.elaz(&s.r, s.g);
    let e = teme_to_ecef(&s.r, s.g);
    let v2 = [tg.obs.x0 - e[0], tg.obs.y0 - e[1], tg.obs.z0 - e[2]];
    let n1 = (e[0] * e[0] + e[1] * e[1] + e[2] * e[2]).sqrt();
    let n2 = (v2[0] * v2[0] + v2[1] * v2[1] + v2[2] * v2[2]).sqrt().max(1e-9);
    let c = (-(e[0] * v2[0] + e[1] * v2[1] + e[2] * v2[2]) / (n1 * n2)).clamp(-1.0, 1.0);
    let d = (s.u[0] * tg.unit[0] + s.u[1] * tg.unit[1] + s.u[2] * tg.unit[2]).clamp(-1.0, 1.0);
    Geo { el, az, rng, off_nadir: c.acos().to_degrees(), lam: d.acos(), sub_lat: s.llh[0], sub_lon: s.llh[1], alt: s.llh[2] }
}

/// 過頂判定值（≥ 0 在時段內；單位：度）
fn g_vis(x: &Geo, tg: &Target, mask: f64) -> f64 {
    if tg.r_rad <= 0.0 {
        x.el - mask
    } else {
        (lam_eps(x.alt, mask) + tg.r_rad - x.lam).to_degrees()
    }
}

/// 可偵照判定值（≥ 0 可偵照；單位：度）
fn g_img(x: &Geo, tg: &Target, eta: f64) -> f64 {
    if tg.r_rad <= 0.0 {
        if x.el < 0.0 {
            return -90.0;
        }
        eta - x.off_nadir
    } else {
        (lam_eta(x.alt, eta) + tg.r_rad - x.lam).to_degrees()
    }
}

fn at(t0: DateTime<Utc>, s: f64) -> DateTime<Utc> {
    t0 + Duration::milliseconds((s * 1000.0).round() as i64)
}

/// 黃金分割求最大值（單峰），回傳 (t, f)
fn gmax(f: &dyn Fn(f64) -> Option<f64>, mut a: f64, mut b: f64) -> Option<(f64, f64)> {
    let r = (5f64.sqrt() - 1.0) / 2.0;
    let mut c = b - r * (b - a);
    let mut d = a + r * (b - a);
    let (mut fc, mut fd) = (f(c)?, f(d)?);
    while b - a > 0.5 {
        if fc > fd {
            b = d;
            d = c;
            fd = fc;
            c = b - r * (b - a);
            fc = f(c)?;
        } else {
            a = c;
            c = d;
            fc = fd;
            d = a + r * (b - a);
            fd = f(d)?;
        }
    }
    let t = (a + b) / 2.0;
    Some((t, f(t)?))
}

/// 二分求 f = 0：f(lo) < 0、f(hi) ≥ 0（lo 可大於 hi）
fn root(f: &dyn Fn(f64) -> Option<f64>, mut lo: f64, mut hi: f64) -> f64 {
    for _ in 0..40 {
        if (hi - lo).abs() <= 0.5 {
            break;
        }
        let m = (lo + hi) / 2.0;
        match f(m) {
            Some(v) if v >= 0.0 => hi = m,
            _ => lo = m,
        }
    }
    hi
}

// ── 太陽 ─────────────────────────────────────────────────────────────────────

const SUN_H0: f64 = -0.833;

/// 當地日期（tz）的日出、日落（UTC）；極晝／極夜回傳 None 並標註
fn sun_events(s: &Site, day0: DateTime<Utc>) -> (Option<DateTime<Utc>>, Option<DateTime<Utc>>, &'static str) {
    let h = s.alt_m / 1000.0;
    let f = |x: f64| crate::lunar::sun_elevation(s.lat, s.lon, h, &at(day0, x)) - SUN_H0;
    let step = 600.0_f64;
    let (mut rise, mut set) = (None, None);
    let mut prev = f(0.0);
    let first = prev;
    let mut x = 0.0;
    while x < 86400.0 {
        let nx = (x + step).min(86400.0);
        let v = f(nx);
        if prev < 0.0 && v >= 0.0 && rise.is_none() {
            let r = root(&|t| Some(f(t)), x, nx);
            rise = Some(at(day0, r));
        } else if prev >= 0.0 && v < 0.0 && set.is_none() {
            let r = root(&|t| Some(f(t)), nx, x);
            set = Some(at(day0, r));
        }
        prev = v;
        x = nx;
    }
    let note = if rise.is_none() && set.is_none() {
        if first >= 0.0 { "極晝" } else { "極夜" }
    } else {
        ""
    };
    (rise, set, note)
}

// ── 歷史誤差 ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize)]
pub struct ErrStat {
    pub lead_days: f64,
    pub n: usize,
    pub pos_med_km: f64,
    pub pos_p90_km: f64,
    pub time_med_s: f64,
    pub time_p90_s: f64,
}

fn pct(v: &mut [f64], p: f64) -> f64 {
    if v.is_empty() {
        return f64::NAN;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let i = ((v.len() - 1) as f64 * p).round() as usize;
    v[i]
}

fn bucket_of(d: f64) -> Option<usize> {
    if d < 0.5 {
        return None;
    }
    LEAD_BUCKETS.iter().position(|b| d <= *b + 0.5)
}

/// 同一顆衛星的 TLE 歷史（每 12 小時取一筆）兩兩比對
fn sat_errors(tles: &[(DateTime<Utc>, Propagator)]) -> Vec<(usize, f64, f64)> {
    let mut out = Vec::new();
    for j in 0..tles.len() {
        let (tj, pj) = &tles[j];
        let (Some(rj), Some(rj2)) = (pj.position(tj), pj.position(&(*tj + Duration::seconds(1)))) else { continue };
        let v = [rj2[0] - rj[0], rj2[1] - rj[1], rj2[2] - rj[2]];
        let sp = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        if sp < 1e-6 {
            continue;
        }
        for (ti, pi) in tles[..j].iter() {
            let d = (*tj - *ti).num_seconds() as f64 / 86400.0;
            let Some(b) = bucket_of(d) else { continue };
            let Some(ri) = pi.position(tj) else { continue };
            let dr = [ri[0] - rj[0], ri[1] - rj[1], ri[2] - rj[2]];
            let pos = (dr[0] * dr[0] + dr[1] * dr[1] + dr[2] * dr[2]).sqrt();
            let along = (dr[0] * v[0] + dr[1] * v[1] + dr[2] * v[2]) / sp;
            out.push((b, pos, (along / sp).abs()));
        }
    }
    out
}

fn summarize(samples: &[(usize, f64, f64)]) -> Vec<ErrStat> {
    let mut out = Vec::new();
    for (bi, b) in LEAD_BUCKETS.iter().enumerate() {
        let mut p: Vec<f64> = samples.iter().filter(|s| s.0 == bi).map(|s| s.1).collect();
        let mut t: Vec<f64> = samples.iter().filter(|s| s.0 == bi).map(|s| s.2).collect();
        if p.is_empty() {
            continue;
        }
        let r = |x: f64, d: f64| (x * d).round() / d;
        out.push(ErrStat {
            lead_days: *b,
            n: p.len(),
            pos_med_km: r(pct(&mut p, 0.5), 100.0),
            pos_p90_km: r(pct(&mut p, 0.9), 100.0),
            time_med_s: r(pct(&mut t, 0.5), 10.0),
            time_p90_s: r(pct(&mut t, 0.9), 10.0),
        });
    }
    out
}

/// 依提前天數內插 p90 時間誤差
fn est_err(curve: &[ErrStat], lead: f64) -> Option<f64> {
    if curve.is_empty() {
        return None;
    }
    if lead <= curve[0].lead_days {
        return Some(curve[0].time_p90_s * (lead / curve[0].lead_days).max(0.0));
    }
    for w in curve.windows(2) {
        if lead <= w[1].lead_days {
            let f = (lead - w[0].lead_days) / (w[1].lead_days - w[0].lead_days);
            return Some(w[0].time_p90_s + f * (w[1].time_p90_s - w[0].time_p90_s));
        }
    }
    let l = curve.last()?;
    Some(l.time_p90_s * lead / l.lead_days)
}

fn load_history(cfg: &Config, ids: &[u32], days: f64) -> anyhow::Result<HashMap<u32, Vec<(DateTime<Utc>, Propagator)>>> {
    let db = cfg.resolve_db().ok_or_else(|| anyhow::anyhow!("找不到資料庫"))?;
    let con = crate::index::open_ro(&db)?;
    let since = (Utc::now() - Duration::seconds((days * 86400.0) as i64)).format("%Y-%m-%d %H:%M:%S").to_string();
    let mut out: HashMap<u32, Vec<(DateTime<Utc>, Propagator)>> = HashMap::new();
    for chunk in ids.chunks(500) {
        let list = chunk.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT norad_id, line1, line2 FROM {RAW_TABLE} WHERE norad_id IN ({list}) AND epoch_utc >= TIMESTAMP '{since}'
             AND line1 IS NOT NULL AND line2 IS NOT NULL ORDER BY norad_id, epoch_utc"
        );
        let mut st = con.prepare(&sql)?;
        let rows = st.query_map([], |r| Ok((r.get::<_, i64>(0)? as u32, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))?;
        for row in rows.flatten() {
            let (n, l1, l2) = row;
            let Some(ep) = tle_epoch(&l1) else { continue };
            let v = out.entry(n).or_default();
            // 每 12 小時取一筆
            if v.last().is_some_and(|(t, _)| (ep - *t).num_seconds() < 43_200) {
                continue;
            }
            if let Some(p) = Propagator::from_tle(&l1, &l2) {
                v.push((ep, p));
            }
        }
    }
    Ok(out)
}

// ── 請求與結果 ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
pub struct Req {
    #[serde(default)]
    pub sites: Vec<Site>,
    #[serde(default)]
    pub groups: Vec<String>,
    #[serde(default)]
    pub norads: Vec<u32>,
    /// 開始時間（UTC ISO）；空白＝現在
    #[serde(default)]
    pub start: Option<String>,
    #[serde(default = "d_days")]
    pub days: f64,
    #[serde(default = "d_mask")]
    pub mask_deg: f64,
    /// 群組未設定偵照角度時的預設值
    #[serde(default = "d_look")]
    pub look_deg: f64,
    /// true：所有衛星一律用 look_deg（忽略群組設定）
    #[serde(default)]
    pub look_override: bool,
    /// true：只輸出可偵照（覆蓋中心點或範圍）的過頂
    #[serde(default = "d_true")]
    pub only_coverable: bool,
    /// 日照篩選：none／optical（光學衛星只留日照時段）／all
    #[serde(default = "d_daylight")]
    pub daylight: String,
    #[serde(default)]
    pub sun_min_deg: f64,
    #[serde(default = "d_tz")]
    pub tz_hours: f64,
    #[serde(default = "d_true")]
    pub error_estimate: bool,
    #[serde(default = "d_hist")]
    pub history_days: f64,
}
fn d_days() -> f64 {
    31.0
}
fn d_mask() -> f64 {
    10.0
}
fn d_look() -> f64 {
    30.0
}
fn d_true() -> bool {
    true
}
fn d_daylight() -> String {
    "optical".into()
}
fn d_tz() -> f64 {
    8.0
}
fn d_hist() -> f64 {
    60.0
}

#[derive(Debug, Clone)]
struct SatJob {
    norad: u32,
    name: String,
    orig: String,
    group: String,
    sensor: String,
    look: f64,
    look_from: &'static str,
    line1: String,
    line2: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct PassRow {
    pub norad_id: u32,
    pub name: String,
    pub orig_name: String,
    pub group: String,
    pub sensor: String,
    pub site: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub duration_s: f64,
    pub tca: DateTime<Utc>,
    pub max_el_deg: f64,
    pub az_tca_deg: f64,
    pub range_km: f64,
    pub min_off_nadir_deg: f64,
    pub ground_dist_km: f64,
    pub sub_lat: f64,
    pub sub_lon: f64,
    pub alt_km: f64,
    pub direction: &'static str,
    pub look_deg: f64,
    pub look_from: &'static str,
    pub swath_radius_km: f64,
    pub coverable: bool,
    pub img_start: Option<DateTime<Utc>>,
    pub img_end: Option<DateTime<Utc>>,
    pub img_duration_s: f64,
    pub sun_el_deg: f64,
    pub sunlit: bool,
    pub tle_epoch: Option<DateTime<Utc>>,
    pub lead_days: f64,
    pub est_err_s: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SunRow {
    pub site: String,
    pub date: String,
    pub sunrise: Option<DateTime<Utc>>,
    pub sunset: Option<DateTime<Utc>>,
    pub daylight_h: f64,
    pub note: &'static str,
}

pub struct Result_ {
    pub passes: Vec<PassRow>,
    pub sun: Vec<SunRow>,
    pub errors: Vec<(u32, String, ErrStat)>,
    pub summary: Value,
    pub tz: FixedOffset,
}

#[derive(Clone)]
pub struct Job {
    pub id: String,
    pub by: String,
    pub created: DateTime<Utc>,
    pub total: usize,
    pub done: Arc<AtomicUsize>,
    pub stage: Arc<Mutex<String>>,
    pub error: Arc<Mutex<Option<String>>>,
    pub result: Arc<Mutex<Option<Arc<Result_>>>>,
    pub params: Value,
}

static JOBS: Lazy<Mutex<Vec<Job>>> = Lazy::new(|| Mutex::new(Vec::new()));

fn select_sats(st: &Arc<AppState>, req: &Req) -> Result<Vec<SatJob>, String> {
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let mut out: BTreeMap<u32, SatJob> = BTreeMap::new();
    let mut add = |n: u32, group: String, sensor: String, look: Option<f64>| {
        if out.contains_key(&n) {
            return;
        }
        let Some(s) = idx.sats.get(&n) else { return };
        let (look, from) = match (req.look_override, look) {
            (false, Some(l)) => (l, "群組"),
            _ => (req.look_deg, "預設"),
        };
        out.insert(n, SatJob {
            norad: n,
            name: s.name.clone(),
            orig: d.names.get(&n).map(|r| r.orig.clone()).unwrap_or_default(),
            group,
            sensor,
            look,
            look_from: from,
            line1: s.line1.clone(),
            line2: s.line2.clone(),
        });
    };
    for gid in &req.groups {
        if !d.groups.iter().any(|g| &g.id == gid) {
            return Err(format!("找不到群組 {gid}"));
        }
        for sub in d.descendants(gid) {
            if let Some(g) = d.groups.iter().find(|x| x.id == sub) {
                for &n in &g.members {
                    add(n, d.path(&sub), d.eff_sensor(&sub), d.eff_look_deg(&sub));
                }
            }
        }
    }
    for &n in &req.norads {
        add(n, String::new(), String::new(), None);
    }
    Ok(out.into_values().collect())
}

fn sensor_label(s: &str) -> &'static str {
    match s {
        "optical" => "光學",
        "radar" => "雷達",
        "sigint" => "電子偵察",
        "other" => "其他",
        _ => "",
    }
}

/// 單顆衛星 × 全部中心點的過頂
fn sat_passes(sj: &SatJob, targets: &[Target], t0: DateTime<Utc>, span: f64, req: &Req) -> Vec<PassRow> {
    let Some(p) = Propagator::from_tle(&sj.line1, &sj.line2) else { return Vec::new() };
    let epoch = tle_epoch(&sj.line1);
    // 週期決定粗掃步長
    let mm: f64 = sj.line2.get(52..63).and_then(|s| s.trim().parse().ok()).unwrap_or(15.0);
    let period_min = 1440.0 / mm.max(0.01);
    let step = if period_min < 200.0 { 20.0 } else if period_min < 800.0 { 60.0 } else { 300.0 };
    let n = (span / step).ceil() as usize;
    let margin = if period_min < 200.0 { 4.0 } else { 1.5 };
    let mut out = Vec::new();
    // 粗掃：每個中心點的候選區段
    let mut segs: Vec<Vec<(f64, f64)>> = vec![Vec::new(); targets.len()];
    let mut open: Vec<Option<f64>> = vec![None; targets.len()];
    for k in 0..=n {
        let x = (k as f64 * step).min(span);
        let st = sat_state(&p, &at(t0, x));
        for (ti, tg) in targets.iter().enumerate() {
            let inside = st.as_ref().map(|s| g_vis(&geo(s, tg), tg, req.mask_deg) > -margin).unwrap_or(false);
            match (inside, open[ti]) {
                (true, None) => open[ti] = Some(x),
                (false, Some(a)) => {
                    segs[ti].push(((a - step).max(0.0), x));
                    open[ti] = None;
                }
                _ => {}
            }
        }
        if st.is_none() && k > 0 && k % 50 == 0 {
            // 已衰退：後續不必再算
            if (0..5).all(|j| sat_state(&p, &at(t0, (x + j as f64 * 3600.0).min(span))).is_none()) {
                break;
            }
        }
    }
    for (ti, o) in open.iter().enumerate() {
        if let Some(a) = o {
            segs[ti].push(((a - step).max(0.0), span));
        }
    }
    for (ti, tg) in targets.iter().enumerate() {
        let gv = |x: f64| sat_state(&p, &at(t0, x)).map(|s| g_vis(&geo(&s, tg), tg, req.mask_deg));
        for &(a, b) in &segs[ti] {
            // 長時段（高軌）在 UTC 午夜切開
            let mut pieces = vec![(a, b)];
            if b - a > 6.0 * 3600.0 {
                pieces.clear();
                let mut s0 = a;
                let mut mid = (at(t0, a).date_naive() + Duration::days(1)).and_time(NaiveTime::MIN).and_utc();
                while (mid - t0).num_seconds() as f64 <= b {
                    let m = (mid - t0).num_seconds() as f64;
                    if m > s0 {
                        pieces.push((s0, m));
                    }
                    s0 = m;
                    mid += Duration::days(1);
                }
                pieces.push((s0, b));
            }
            for (a, b) in pieces {
                let Some((tc, vmax)) = gmax(&gv, a, b) else { continue };
                if vmax < 0.0 {
                    continue;
                }
                let ws = if gv(a).is_some_and(|v| v >= 0.0) { a } else { root(&gv, a, tc) };
                let we = if gv(b).is_some_and(|v| v >= 0.0) { b } else { root(&gv, b, tc) };
                let Some(stc) = sat_state(&p, &at(t0, tc)) else { continue };
                let gt = geo(&stc, tg);
                // 可偵照
                let eta = sj.look;
                let gi = |x: f64| sat_state(&p, &at(t0, x)).map(|s| g_img(&geo(&s, tg), tg, eta));
                let (img_s, img_e, best) = match gmax(&gi, ws, we) {
                    Some((ti_, v)) if v >= 0.0 => {
                        let s = if gi(ws).is_some_and(|x| x >= 0.0) { ws } else { root(&gi, ws, ti_) };
                        let e = if gi(we).is_some_and(|x| x >= 0.0) { we } else { root(&gi, we, ti_) };
                        (Some(s), Some(e), ti_)
                    }
                    Some((ti_, _)) => (None, None, ti_),
                    None => (None, None, tc),
                };
                let coverable = img_s.is_some();
                if req.only_coverable && !coverable {
                    continue;
                }
                let gb = sat_state(&p, &at(t0, best)).map(|s| geo(&s, tg)).unwrap_or(gt);
                let tca = at(t0, tc);
                let sun = crate::lunar::sun_elevation(tg.site.lat, tg.site.lon, tg.site.alt_m / 1000.0, &tca);
                let sunlit = sun >= req.sun_min_deg;
                let drop_dark = match req.daylight.as_str() {
                    "all" => !sunlit,
                    "optical" => sj.sensor == "optical" && !sunlit,
                    _ => false,
                };
                if drop_dark {
                    continue;
                }
                let dir = {
                    let a1 = sat_state(&p, &at(t0, tc - 10.0)).map(|s| s.llh[0]);
                    let a2 = sat_state(&p, &at(t0, tc + 10.0)).map(|s| s.llh[0]);
                    match (a1, a2) {
                        (Some(x), Some(y)) if y > x => "升軌",
                        (Some(_), Some(_)) => "降軌",
                        _ => "",
                    }
                };
                let lead = epoch.map(|e| (tca - e).num_seconds() as f64 / 86400.0).unwrap_or(f64::NAN);
                let r1 = |x: f64| (x * 10.0).round() / 10.0;
                out.push(PassRow {
                    norad_id: sj.norad,
                    name: sj.name.clone(),
                    orig_name: sj.orig.clone(),
                    group: sj.group.clone(),
                    sensor: sensor_label(&sj.sensor).into(),
                    site: tg.site.name.clone(),
                    start: at(t0, ws),
                    end: at(t0, we),
                    duration_s: (we - ws).round(),
                    tca,
                    max_el_deg: r1(gt.el),
                    az_tca_deg: r1(gt.az),
                    range_km: r1(gt.rng),
                    min_off_nadir_deg: r1(gb.off_nadir),
                    ground_dist_km: r1(gt.lam * RE),
                    sub_lat: (gt.sub_lat * 1e4).round() / 1e4,
                    sub_lon: (gt.sub_lon * 1e4).round() / 1e4,
                    alt_km: r1(gt.alt),
                    direction: dir,
                    look_deg: eta,
                    look_from: sj.look_from,
                    swath_radius_km: r1(lam_eta(gt.alt, eta) * RE),
                    coverable,
                    img_start: img_s.map(|x| at(t0, x)),
                    img_end: img_e.map(|x| at(t0, x)),
                    img_duration_s: match (img_s, img_e) {
                        (Some(a), Some(b)) => (b - a).round(),
                        _ => 0.0,
                    },
                    sun_el_deg: r1(sun),
                    sunlit,
                    tle_epoch: epoch,
                    lead_days: (lead * 100.0).round() / 100.0,
                    est_err_s: None,
                });
            }
        }
    }
    out
}

fn run(st: Arc<AppState>, req: Req, job: Job) -> anyhow::Result<Result_> {
    let t0 = match req.start.as_deref().filter(|s| !s.trim().is_empty()) {
        Some(s) => DateTime::parse_from_rfc3339(s.trim()).map_err(|e| anyhow::anyhow!("開始時間格式錯誤：{e}"))?.with_timezone(&Utc),
        None => Utc::now(),
    };
    let span = req.days * 86400.0;
    let tz = FixedOffset::east_opt((req.tz_hours * 3600.0).round() as i32).unwrap_or(FixedOffset::east_opt(8 * 3600).unwrap());
    let sats = select_sats(&st, &req).map_err(|e| anyhow::anyhow!(e))?;
    let targets: Vec<Target> = req.sites.iter().cloned().map(Target::new).collect();
    *job.stage.lock() = format!("計算過頂（{} 顆 × {} 個中心點 × {} 天）", sats.len(), targets.len(), req.days);
    let done = job.done.clone();
    let mut passes: Vec<PassRow> = sats
        .par_iter()
        .flat_map_iter(|sj| {
            let r = sat_passes(sj, &targets, t0, span, &req);
            done.fetch_add(1, Ordering::Relaxed);
            r
        })
        .collect();
    passes.sort_by(|a, b| a.site.cmp(&b.site).then(a.tca.cmp(&b.tca)).then(a.norad_id.cmp(&b.norad_id)));

    // 歷史誤差
    let mut errors: Vec<(u32, String, ErrStat)> = Vec::new();
    let mut fleet_curve = Vec::new();
    let mut curves: HashMap<u32, Vec<ErrStat>> = HashMap::new();
    if req.error_estimate && !sats.is_empty() {
        *job.stage.lock() = format!("歷史誤差估算（近 {} 天 TLE）", req.history_days);
        let ids: Vec<u32> = sats.iter().map(|s| s.norad).collect();
        let hist = load_history(&st.cfg, &ids, req.history_days)?;
        let per: Vec<(u32, Vec<(usize, f64, f64)>)> = ids
            .par_iter()
            .filter_map(|n| hist.get(n).map(|h| (*n, sat_errors(h))))
            .collect();
        let mut all = Vec::new();
        let names: HashMap<u32, String> = sats.iter().map(|s| (s.norad, s.name.clone())).collect();
        for (n, smp) in &per {
            let c = summarize(smp);
            for e in &c {
                errors.push((*n, names.get(n).cloned().unwrap_or_default(), e.clone()));
            }
            if !c.is_empty() {
                curves.insert(*n, c);
            }
            all.extend_from_slice(smp);
        }
        fleet_curve = summarize(&all);
        for e in &fleet_curve {
            errors.push((0, "全部（合併）".into(), e.clone()));
        }
        errors.sort_by(|a, b| (a.0 == 0).cmp(&(b.0 == 0)).then(a.0.cmp(&b.0)).then(a.2.lead_days.partial_cmp(&b.2.lead_days).unwrap()));
        for p in passes.iter_mut() {
            let c = curves.get(&p.norad_id).filter(|c| c.len() >= 2).unwrap_or(&fleet_curve);
            if p.lead_days.is_finite() {
                p.est_err_s = est_err(c, p.lead_days.max(0.0)).map(|x| (x * 10.0).round() / 10.0);
            }
        }
    }

    // 日出日落
    *job.stage.lock() = "計算日出日落".into();
    let first_local = t0.with_timezone(&tz).date_naive();
    let last_local = at(t0, span).with_timezone(&tz).date_naive();
    let mut days = Vec::new();
    let mut dd = first_local;
    while dd <= last_local {
        days.push(dd);
        dd += Duration::days(1);
    }
    let mut sun: Vec<SunRow> = req
        .sites
        .par_iter()
        .flat_map_iter(|s| {
            days.iter()
                .map(|d| {
                    let day0 = tz.from_local_datetime(&d.and_time(NaiveTime::MIN)).single().map(|x| x.with_timezone(&Utc)).unwrap_or(t0);
                    let (r, e, note) = sun_events(s, day0);
                    let dl = match (r, e) {
                        (Some(r), Some(e)) if e > r => (e - r).num_seconds() as f64 / 3600.0,
                        _ => if note == "極晝" { 24.0 } else { 0.0 },
                    };
                    SunRow { site: s.name.clone(), date: d.format("%Y-%m-%d").to_string(), sunrise: r, sunset: e, daylight_h: (dl * 100.0).round() / 100.0, note }
                })
                .collect::<Vec<_>>()
        })
        .collect();
    sun.sort_by(|a, b| a.site.cmp(&b.site).then(a.date.cmp(&b.date)));

    let mut per_site: BTreeMap<String, (usize, usize, usize)> = BTreeMap::new();
    for p in &passes {
        let e = per_site.entry(p.site.clone()).or_default();
        e.0 += 1;
        if p.coverable {
            e.1 += 1;
        }
        if p.sunlit {
            e.2 += 1;
        }
    }
    let skipped: Vec<u32> = req.norads.iter().copied().filter(|n| !sats.iter().any(|s| s.norad == *n)).collect();
    let mut look_values: Vec<f64> = sats.iter().map(|s| s.look).collect();
    look_values.sort_by(|a, b| a.partial_cmp(b).unwrap());
    look_values.dedup();
    let summary = json!({
        "start": t0.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "end": at(t0, span).to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "days": req.days, "sats": sats.len(), "sites": req.sites.len(), "passes": passes.len(),
        "per_site": per_site.iter().map(|(k, v)| json!({"site": k, "passes": v.0, "coverable": v.1, "sunlit": v.2})).collect::<Vec<_>>(),
        "not_in_catalog": skipped,
        "fleet_error": fleet_curve,
        "look_values": look_values,
    });
    Ok(Result_ { passes, sun, errors, summary, tz })
}

// ── CSV ──────────────────────────────────────────────────────────────────────

fn esc(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) { format!("\"{}\"", s.replace('"', "\"\"")) } else { s.to_string() }
}

fn csv_resp(body: String, name: &str) -> Response {
    let mut r = Response::new(axum::body::Body::from(body));
    r.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static("text/csv; charset=utf-8"));
    r.headers_mut().insert(header::CONTENT_DISPOSITION, HeaderValue::from_str(&format!("attachment; filename=\"{name}\"")).unwrap());
    r
}

pub fn passes_csv(res: &Result_) -> String {
    let tz = res.tz;
    let off = tz.local_minus_utc() as f64 / 3600.0;
    let lt = |t: &DateTime<Utc>| t.with_timezone(&tz).format("%Y-%m-%d %H:%M:%S").to_string();
    let ut = |t: &DateTime<Utc>| t.format("%Y-%m-%d %H:%M:%S").to_string();
    let sunmap: HashMap<(String, String), &SunRow> = res.sun.iter().map(|s| ((s.site.clone(), s.date.clone()), s)).collect();
    let hm = |t: &Option<DateTime<Utc>>| t.map(|t| t.with_timezone(&tz).format("%H:%M").to_string()).unwrap_or_default();
    let mut out = String::from("\u{FEFF}");
    out.push_str(&format!(
        "中心點,NORAD,名稱,Space-Track原名,群組,感測器,開始(UTC{off:+}),結束(UTC{off:+}),最高點時間TCA(UTC{off:+}),TCA(UTC),持續秒數,最高仰角,TCA方位角,斜距km,\
最小離天底角,偵照角度,偵照角度來源,偵照地面半徑km,可偵照,可偵照開始(UTC{off:+}),可偵照結束(UTC{off:+}),可偵照秒數,星下點距中心km,星下點緯度,星下點經度,高度km,升降軌,\
太陽仰角,日照,當日日出,當日日落,TLE曆元(UTC),距TLE曆元天數,預估時間誤差秒(p90)\n"
    ));
    for p in &res.passes {
        let date = p.tca.with_timezone(&tz).format("%Y-%m-%d").to_string();
        let s = sunmap.get(&(p.site.clone(), date));
        let cols: Vec<String> = vec![
            esc(&p.site), p.norad_id.to_string(), esc(&p.name), esc(&p.orig_name), esc(&p.group), p.sensor.clone(),
            lt(&p.start), lt(&p.end), lt(&p.tca), ut(&p.tca), p.duration_s.to_string(), p.max_el_deg.to_string(), p.az_tca_deg.to_string(),
            p.range_km.to_string(), p.min_off_nadir_deg.to_string(), p.look_deg.to_string(), p.look_from.into(), p.swath_radius_km.to_string(),
            if p.coverable { "是".into() } else { "否".into() },
            p.img_start.map(|t| lt(&t)).unwrap_or_default(), p.img_end.map(|t| lt(&t)).unwrap_or_default(), p.img_duration_s.to_string(),
            p.ground_dist_km.to_string(), p.sub_lat.to_string(), p.sub_lon.to_string(), p.alt_km.to_string(), p.direction.into(),
            p.sun_el_deg.to_string(), if p.sunlit { "日照".into() } else { "夜間".into() },
            s.map(|s| hm(&s.sunrise)).unwrap_or_default(), s.map(|s| hm(&s.sunset)).unwrap_or_default(),
            p.tle_epoch.map(|t| ut(&t)).unwrap_or_default(),
            if p.lead_days.is_finite() { p.lead_days.to_string() } else { String::new() },
            p.est_err_s.map(|x| x.to_string()).unwrap_or_default(),
        ];
        out.push_str(&cols.join(","));
        out.push('\n');
    }
    out
}

pub fn sun_csv(res: &Result_) -> String {
    let tz = res.tz;
    let off = tz.local_minus_utc() as f64 / 3600.0;
    let mut out = format!("\u{FEFF}中心點,日期(UTC{off:+}),日出,日落,日照時數,備註\n");
    let hm = |t: &Option<DateTime<Utc>>| t.map(|t| t.with_timezone(&tz).format("%H:%M:%S").to_string()).unwrap_or_default();
    for s in &res.sun {
        out.push_str(&format!("{},{},{},{},{},{}\n", esc(&s.site), s.date, hm(&s.sunrise), hm(&s.sunset), s.daylight_h, s.note));
    }
    out
}

pub fn errors_csv(res: &Result_) -> String {
    let mut out = String::from("\u{FEFF}NORAD,名稱,提前天數,樣本數,位置誤差中位數km,位置誤差p90km,時間誤差中位數秒,時間誤差p90秒\n");
    for (n, name, e) in &res.errors {
        out.push_str(&format!(
            "{},{},{},{},{},{},{},{}\n",
            if *n == 0 { "ALL".into() } else { n.to_string() },
            esc(name), e.lead_days, e.n, e.pos_med_km, e.pos_p90_km, e.time_med_s, e.time_p90_s
        ));
    }
    out
}

// ── API ──────────────────────────────────────────────────────────────────────

type St = State<Arc<AppState>>;

fn jerr(s: StatusCode, m: impl Into<String>) -> Response {
    (s, Json(json!({"error": m.into()}))).into_response()
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/forecast", get(page))
        .route("/api/forecast/sites", get(api_sites).put(api_sites_put))
        .route("/api/forecast/run", post(api_run))
        .route("/api/forecast/jobs", get(api_jobs))
        .route("/api/forecast/jobs/{id}", get(api_job))
        .route("/api/forecast/jobs/{id}/{file}", get(api_job_file))
}

async fn page() -> Html<String> {
    let raw = crate::assets::get("ext/forecast.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

async fn api_sites(State(st): St) -> Json<Value> {
    Json(json!({"sites": load_sites(&st.cfg)}))
}

async fn api_sites_put(State(st): St, Extension(c): Extension<Caller>, Json(b): Json<Vec<Site>>) -> Response {
    if !c.can_edit() {
        return jerr(StatusCode::FORBIDDEN, "需要編輯者以上權限");
    }
    if b.len() > 200 {
        return jerr(StatusCode::BAD_REQUEST, "常用中心點最多 200 個");
    }
    for s in &b {
        if let Err(e) = check_site(s) {
            return jerr(StatusCode::BAD_REQUEST, e);
        }
    }
    match serde_json::to_vec_pretty(&b).map_err(|e| e.to_string()).and_then(|d| atomic_write(&sites_file(&st.cfg), &d).map_err(|e| e.to_string())) {
        Ok(()) => {
            st.satadmin.audit(&c.name(), "常用中心點", &format!("儲存 {} 個", b.len()));
            Json(json!({"ok": true})).into_response()
        }
        Err(e) => jerr(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

fn validate(req: &Req) -> Result<(), String> {
    if req.sites.is_empty() || req.sites.len() > MAX_TARGETS {
        return Err(format!("中心點需 1–{MAX_TARGETS} 個"));
    }
    for s in &req.sites {
        check_site(s)?;
    }
    if !(req.days > 0.0 && req.days <= MAX_DAYS) {
        return Err(format!("預報天數需介於 0–{MAX_DAYS} 天"));
    }
    if !(-5.0..=89.0).contains(&req.mask_deg) {
        return Err("仰角門檻需介於 −5–89 度".into());
    }
    if !(req.look_deg > 0.0 && req.look_deg <= 70.0) {
        return Err("偵照角度需介於 0–70 度".into());
    }
    if !(-14.0..=14.0).contains(&req.tz_hours) {
        return Err("時區需介於 −14～+14".into());
    }
    if !(-18.0..=60.0).contains(&req.sun_min_deg) {
        return Err("太陽仰角門檻需介於 −18–60 度".into());
    }
    if !(7.0..=365.0).contains(&req.history_days) {
        return Err("歷史天數需介於 7–365".into());
    }
    if req.groups.is_empty() && req.norads.is_empty() {
        return Err("請選擇群組或輸入 NORAD ID".into());
    }
    Ok(())
}

async fn api_run(State(st): St, Extension(c): Extension<Caller>, Json(req): Json<Req>) -> Response {
    if let Err(e) = validate(&req) {
        return jerr(StatusCode::BAD_REQUEST, e);
    }
    let sats = match select_sats(&st, &req) {
        Ok(s) => s,
        Err(e) => return jerr(StatusCode::BAD_REQUEST, e),
    };
    if sats.is_empty() {
        return jerr(StatusCode::BAD_REQUEST, "選取的衛星都不在目前目錄中");
    }
    if sats.len() > MAX_SATS {
        return jerr(StatusCode::BAD_REQUEST, format!("一次最多 {MAX_SATS} 顆衛星（目前 {} 顆）", sats.len()));
    }
    {
        let jobs = JOBS.lock();
        if jobs.iter().any(|j| j.result.lock().is_none() && j.error.lock().is_none()) {
            return jerr(StatusCode::CONFLICT, "已有預報在計算中，請稍候");
        }
    }
    let id = format!("f{}", Utc::now().format("%Y%m%d%H%M%S%3f"));
    let job = Job {
        id: id.clone(),
        by: c.name(),
        created: Utc::now(),
        total: sats.len(),
        done: Arc::new(AtomicUsize::new(0)),
        stage: Arc::new(Mutex::new("準備中".into())),
        error: Arc::new(Mutex::new(None)),
        result: Arc::new(Mutex::new(None)),
        params: json!({
            "sites": req.sites.iter().map(|s| s.name.clone()).collect::<Vec<_>>(), "days": req.days, "mask_deg": req.mask_deg,
            "look_deg": req.look_deg, "look_override": req.look_override, "only_coverable": req.only_coverable,
            "daylight": req.daylight, "sun_min_deg": req.sun_min_deg, "tz_hours": req.tz_hours, "groups": req.groups.len(), "norads": req.norads.len(),
        }),
    };
    {
        let mut jobs = JOBS.lock();
        jobs.push(job.clone());
        while jobs.len() > 5 {
            jobs.remove(0);
        }
    }
    st.satadmin.audit(&c.name(), "過頂預報", &format!("{} 顆 × {} 個中心點 × {} 天", sats.len(), req.sites.len(), req.days));
    let st2 = st.clone();
    tokio::task::spawn_blocking(move || {
        let t = std::time::Instant::now();
        match run(st2, req, job.clone()) {
            Ok(r) => {
                tracing::info!("過頂預報 {} 完成：{} 筆，{:.1} s", job.id, r.passes.len(), t.elapsed().as_secs_f64());
                *job.result.lock() = Some(Arc::new(r));
            }
            Err(e) => *job.error.lock() = Some(format!("{e:#}")),
        }
    });
    Json(json!({"ok": true, "job_id": id, "sats": sats.len()})).into_response()
}

fn job_json(j: &Job, preview: usize) -> Value {
    let res = j.result.lock().clone();
    let err = j.error.lock().clone();
    let state = if res.is_some() { "done" } else if err.is_some() { "error" } else { "running" };
    let mut v = json!({
        "id": j.id, "by": j.by, "created": j.created.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "state": state, "stage": *j.stage.lock(), "done": j.done.load(Ordering::Relaxed), "total": j.total,
        "error": err, "params": j.params,
    });
    if let Some(r) = res {
        v["summary"] = r.summary.clone();
        if preview > 0 {
            v["preview"] = json!(r.passes.iter().take(preview).collect::<Vec<_>>());
            v["sun_preview"] = json!(r.sun.iter().take(preview.min(62)).collect::<Vec<_>>());
        }
    }
    v
}

async fn api_jobs() -> Json<Value> {
    let jobs = JOBS.lock().clone();
    Json(json!({"jobs": jobs.iter().rev().map(|j| job_json(j, 0)).collect::<Vec<_>>()}))
}

async fn api_job(Path(id): Path<String>) -> Response {
    let j = JOBS.lock().iter().find(|j| j.id == id).cloned();
    match j {
        Some(j) => Json(job_json(&j, 300)).into_response(),
        None => jerr(StatusCode::NOT_FOUND, "找不到此預報（程式重新啟動後會清除，請重新計算）"),
    }
}

async fn api_job_file(Path((id, file)): Path<(String, String)>) -> Response {
    let j = JOBS.lock().iter().find(|j| j.id == id).cloned();
    let Some(j) = j else { return jerr(StatusCode::NOT_FOUND, "找不到此預報") };
    let Some(r) = j.result.lock().clone() else { return jerr(StatusCode::CONFLICT, "預報尚未完成") };
    let stamp = j.created.with_timezone(&r.tz).format("%Y%m%d_%H%M");
    match file.as_str() {
        "passes.csv" => csv_resp(passes_csv(&r), &format!("passes_{stamp}.csv")),
        "sun.csv" => csv_resp(sun_csv(&r), &format!("sun_{stamp}.csv")),
        "errors.csv" => csv_resp(errors_csv(&r), &format!("tle_error_{stamp}.csv")),
        _ => jerr(StatusCode::NOT_FOUND, "檔案需為 passes.csv／sun.csv／errors.csv"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn footprint_geometry() {
        // 500 km 高度：離天底 15° ≈ 地面半徑 135 km；30° ≈ 290 km
        let r15 = lam_eta(500.0, 15.0) * RE;
        let r30 = lam_eta(500.0, 30.0) * RE;
        assert!((r15 - 135.0).abs() < 5.0, "{r15}");
        assert!((r30 - 290.0).abs() < 10.0, "{r30}");
        // 仰角 0° 地心角 ≈ 22°
        assert!((lam_eps(500.0, 0.0).to_degrees() - 22.0).abs() < 0.3);
        assert!(lam_eta(500.0, 80.0) <= lam_eps(500.0, 0.0) + 1e-9, "超過地平取地平");
    }

    #[test]
    fn solver_helpers() {
        let f = |x: f64| Some(-(x - 37.0).powi(2) + 100.0);
        let (t, v) = gmax(&f, 0.0, 100.0).unwrap();
        assert!((t - 37.0).abs() < 1.0 && (v - 100.0).abs() < 1.0);
        let r = root(&f, 0.0, 37.0);
        assert!((r - 27.0).abs() < 1.0, "{r}");
        let r = root(&f, 100.0, 37.0);
        assert!((r - 47.0).abs() < 1.0, "{r}");
    }

    #[test]
    fn error_curve() {
        let c = vec![
            ErrStat { lead_days: 1.0, n: 5, time_p90_s: 2.0, ..Default::default() },
            ErrStat { lead_days: 3.0, n: 5, time_p90_s: 10.0, ..Default::default() },
        ];
        assert_eq!(est_err(&c, 2.0), Some(6.0));
        assert_eq!(est_err(&c, 0.5), Some(1.0));
        assert_eq!(est_err(&c, 6.0), Some(20.0));
        assert_eq!(bucket_of(0.2), None);
        assert_eq!(bucket_of(1.2), Some(0));
        assert_eq!(bucket_of(4.0), Some(3));
        let s = summarize(&[(0, 1.0, 1.0), (0, 3.0, 2.0), (2, 9.0, 4.0)]);
        assert_eq!(s.len(), 2);
        assert_eq!(s[0].pos_med_km, 3.0);
    }

    #[test]
    fn iss_pass_over_taipei() {
        let l1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005";
        let l2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537";
        let sj = SatJob {
            norad: 25544, name: "ISS".into(), orig: String::new(), group: String::new(), sensor: "optical".into(),
            look: 30.0, look_from: "預設", line1: l1.into(), line2: l2.into(),
        };
        let site = Site { name: "台北".into(), lat: 25.033, lon: 121.565, alt_m: 10.0, radius_km: 0.0, note: String::new() };
        let tg = vec![Target::new(site.clone())];
        let req: Req = serde_json::from_value(json!({"sites": [site], "norads": [25544], "only_coverable": false, "daylight": "none"})).unwrap();
        let t0 = Utc.with_ymd_and_hms(2024, 1, 1, 12, 0, 0).unwrap();
        let ps = sat_passes(&sj, &tg, t0, 3.0 * 86400.0, &req);
        assert!(!ps.is_empty(), "3 天內台北應有 ISS 過頂");
        for p in &ps {
            assert!(p.max_el_deg >= 10.0 - 0.2 && p.end > p.start && p.tca >= p.start && p.tca <= p.end, "{p:?}");
            assert!(p.duration_s < 900.0);
            if p.coverable {
                assert!(p.min_off_nadir_deg <= 30.0 + 0.3 && p.img_duration_s > 0.0);
            }
            // 起點仰角 ≈ 門檻
            let pr = Propagator::from_tle(l1, l2).unwrap();
            let s = sat_state(&pr, &p.start).unwrap();
            assert!((geo(&s, &tg[0]).el - 10.0).abs() < 0.3);
        }
        // 半徑 300 km 的區域：可偵照次數 ≥ 單點
        let mut site2 = req.sites[0].clone();
        site2.radius_km = 300.0;
        let tg2 = vec![Target::new(site2)];
        let req2 = Req { only_coverable: true, ..req.clone() };
        let a = sat_passes(&sj, &tg, t0, 3.0 * 86400.0, &req2).len();
        let b = sat_passes(&sj, &tg2, t0, 3.0 * 86400.0, &req2).len();
        assert!(b >= a, "{a} {b}");
        // 日出日落：台北 2024-01-01 約 06:39／17:17（UTC+8）
        let tz = FixedOffset::east_opt(8 * 3600).unwrap();
        let day0 = tz.with_ymd_and_hms(2024, 1, 1, 0, 0, 0).unwrap().with_timezone(&Utc);
        let (r, s, _) = sun_events(&req.sites[0], day0);
        let (r, s) = (r.unwrap().with_timezone(&tz), s.unwrap().with_timezone(&tz));
        assert_eq!(r.format("%H").to_string(), "06");
        assert_eq!(s.format("%H").to_string(), "17");
    }
}
