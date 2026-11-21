//! 太空小遊戲「天文觀測夢魘」：望遠鏡一次曝光期間，有哪些衛星劃過視野、多亮、多快；
//! 以及整夜每次曝光平均被劃幾條。
//!
//! - 物件：真實目錄（SGP4）＋可選的假想星座（與「星座壅擠」相同的 Walker 殼層）
//! - 指向：赤經赤緯（TEME 視為當日赤道，與星表 J2000 差約 0.3°，畫面上看不出來）
//! - 可見條件：衛星被太陽照到（圓柱形地影）、測站太陽仰角 < −12°（天文昏影以後）
//! - 亮度：m = m₁₀₀₀ + 5·log10(距離/1000 km) − 2.5·log10(F(φ)/F(90°))，F 為朗伯球相位函數；
//!   m₁₀₀₀ 依類型取代表值（Starlink 約 5.8 等等，見 std_mag）

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use chrono::{DateTime, Duration, Utc};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::json;

use crate::games::{build_items, sgp4_state, GroupReq, Item, Obj};
use crate::index::SatInfo;
use crate::physics::{gmst_rad, julian_date, Observer, R_EARTH_KM};
use crate::state::AppState;

type V3 = [f64; 3];
fn dot(a: &V3, b: &V3) -> f64 { a[0] * b[0] + a[1] * b[1] + a[2] * b[2] }
fn norm(a: &V3) -> f64 { dot(a, a).sqrt() }
fn unit(a: &V3) -> V3 { let n = norm(a); [a[0] / n, a[1] / n, a[2] / n] }
fn cross(a: &V3, b: &V3) -> V3 { [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] }
fn sub(a: &V3, b: &V3) -> V3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }

/// 低精度太陽方向（Vallado，約 0.01°），當日赤道座標
fn sun_dir(t: &DateTime<Utc>) -> V3 {
    let tc = (julian_date(t) - 2451545.0) / 36525.0;
    let l = 280.460 + 36000.771 * tc;
    let m = (357.5291092 + 35999.05034 * tc).to_radians();
    let lam = (l + 1.914666471 * m.sin() + 0.019994643 * (2.0 * m).sin()).to_radians();
    let eps = (23.439291 - 0.0130042 * tc).to_radians();
    [lam.cos(), eps.cos() * lam.sin(), eps.sin() * lam.sin()]
}

fn obs_teme(o: &Observer, t: &DateTime<Utc>) -> V3 {
    let (sg, cg) = gmst_rad(t).sin_cos();
    [cg * o.x0 - sg * o.y0, sg * o.x0 + cg * o.y0, o.z0]
}

fn std_mag_cat(s: &SatInfo) -> f64 {
    let n = s.name.to_uppercase();
    if n.contains("ISS (ZARYA)") { return -1.5; }
    if n.starts_with("CSS (") || n.contains("TIANHE") { return 0.0; }
    if n.contains("STARLINK") { return 5.8; }
    if n.contains("ONEWAB") || n.contains("ONEWEB") { return 7.5; }
    if n.contains("KUIPER") { return 6.5; }
    match s.purpose.as_str() {
        "火箭體" => 4.5,
        "碎片" => 8.5,
        "有效載荷" => 5.5,
        _ => 7.0,
    }
}
fn std_mag(it: &Item) -> f64 {
    match &it.obj {
        Obj::Cat(s) => std_mag_cat(s),
        Obj::Syn(_) => [5.8, 5.8, 6.5, 6.0, 6.0][(it.group as usize).min(4)],
    }
}
fn name_of(it: &Item) -> String {
    match &it.obj {
        Obj::Cat(s) => s.name.clone(),
        Obj::Syn(_) => ["假想", "假想 Starlink", "假想 Kuiper", "假想千帆", "假想國網"][(it.group as usize).min(4)].to_string(),
    }
}

fn state(it: &Item, t: &DateTime<Utc>, dt: f64) -> Option<V3> {
    match &it.obj {
        Obj::Cat(s) => sgp4_state(s, t).map(|x| x.0),
        Obj::Syn(w) => Some(w.state(dt).0),
    }
}

struct View { p: V3, e: V3, n: V3, half: f64 }
impl View {
    /// 方向 u → 切平面（度，x 向東為負以符合天空影像東左西右）；在指向背面回傳 None
    fn proj(&self, u: &V3) -> Option<(f64, f64)> {
        let c = dot(u, &self.p);
        if c <= 0.05 { return None; }
        Some((-(dot(u, &self.e) / c).to_degrees(), (dot(u, &self.n) / c).to_degrees()))
    }
}

/// 線段是否穿過（放大 m 倍的）正方形視野
fn seg_hits(a: (f64, f64), b: (f64, f64), half: f64) -> bool {
    let (x0, y0, x1, y1) = (-half, -half, half, half);
    let inside = |p: (f64, f64)| p.0 >= x0 && p.0 <= x1 && p.1 >= y0 && p.1 <= y1;
    if inside(a) || inside(b) { return true; }
    // Liang–Barsky
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (p, q) in [(-dx, a.0 - x0), (dx, x1 - a.0), (-dy, a.1 - y0), (dy, y1 - a.1)] {
        if p == 0.0 { if q < 0.0 { return false; } continue; }
        let r = q / p;
        if p < 0.0 { if r > t1 { return false; } if r > t0 { t0 = r; } } else { if r < t0 { return false; } if r < t1 { t1 = r; } }
    }
    t0 <= t1
}

fn sunlit(r: &V3, s: &V3) -> bool {
    let d = dot(r, s);
    d > 0.0 || norm(&[r[0] - d * s[0], r[1] - d * s[1], r[2] - d * s[2]]) > R_EARTH_KM
}

fn mag_at(r: &V3, o: &V3, s: &V3, m0: f64) -> f64 {
    let to_obs = sub(o, r);
    let rng = norm(&to_obs);
    let phi = dot(&unit(&to_obs), s).clamp(-1.0, 1.0).acos(); // 相位角：衛星看太陽與看觀測者的夾角
    let f = (phi.sin() + (std::f64::consts::PI - phi) * phi.cos()) / std::f64::consts::PI;
    m0 + 5.0 * (rng / 1000.0).log10() - 2.5 * (f.max(1e-4) / (1.0 / std::f64::consts::PI)).log10()
}

fn alt_of(o: &Observer, u: &V3, t: &DateTime<Utc>) -> f64 {
    let up = unit(&obs_teme(o, t));
    dot(u, &up).asin().to_degrees()
}

#[derive(Deserialize)]
pub struct AstroReq {
    lat: f64,
    lon: f64,
    h_km: f64,
    ra_deg: f64,
    dec_deg: f64,
    fov_deg: f64,
    exp_s: f64,
    t: Option<String>,
    groups: Option<Vec<GroupReq>>,
    night: Option<bool>,
}

fn bad(msg: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response()
}

pub async fn astro_api(State(st): State<Arc<AppState>>, Json(rq): Json<AstroReq>) -> Response {
    tokio::task::spawn_blocking(move || run(&st, &rq)).await.unwrap_or_else(|_| bad("計算失敗"))
}

fn run(st: &Arc<AppState>, rq: &AstroReq) -> Response {
    let t_start = std::time::Instant::now();
    let t0 = rq.t.as_deref().and_then(|s| DateTime::parse_from_rfc3339(s).ok()).map(|d| d.with_timezone(&Utc)).unwrap_or_else(Utc::now);
    let exp = rq.exp_s.clamp(1.0, 600.0);
    let fov = rq.fov_deg.clamp(0.05, 20.0);
    let obs = Observer::new(rq.lat, rq.lon, rq.h_km);
    let (ra, dec) = (rq.ra_deg.to_radians(), rq.dec_deg.to_radians());
    let p = [dec.cos() * ra.cos(), dec.cos() * ra.sin(), dec.sin()];
    let e = unit(&cross(&[0.0, 0.0, 1.0], &p));
    let view = View { p, e, n: cross(&p, &e), half: fov / 2.0 };

    let idx = st.index();
    let sats: Vec<&SatInfo> = idx.sats.values().filter(|s| s.prop.is_some()).collect();
    let reqs = rq.groups.clone().unwrap_or_default();
    let (items, _) = build_items(&sats, &reqs);
    let tref = Utc::now(); // 假想星座以「現在」為相位基準（與星座壅擠一致）
    let dt_of = |t: &DateTime<Utc>| (*t - tref).num_milliseconds() as f64 / 1000.0;
    let at = |s: f64| t0 + Duration::milliseconds((s * 1000.0) as i64);

    let sun0 = sun_dir(&t0);
    let sun_alt = alt_of(&obs, &sun0, &t0);
    let point_alt = alt_of(&obs, &p, &t0);

    // 一次曝光：粗篩（每 15 秒一段的線段）→ 細取樣（約 0.25 秒）
    let seg = 15.0f64.min(exp);
    let nseg = (exp / seg).ceil() as usize;
    let times: Vec<f64> = (0..=nseg).map(|k| (k as f64 * seg).min(exp)).collect();
    let cand: Vec<usize> = (0..items.len())
        .into_par_iter()
        .filter(|&i| {
            let mut prev: Option<(f64, f64)> = None;
            for &s in &times {
                let t = at(s);
                let Some(r) = state(&items[i], &t, dt_of(&t)) else { return false };
                let u = unit(&sub(&r, &obs_teme(&obs, &t)));
                let Some(q) = view.proj(&u) else { prev = None; continue };
                if let Some(a) = prev {
                    if seg_hits(a, q, view.half * 1.3) { return true; }
                }
                prev = Some(q);
            }
            false
        })
        .collect();
    let mut streaks = Vec::new();
    let mut shadowed = 0;
    for i in cand {
        let it = &items[i];
        let n = ((exp / 0.25).ceil() as usize).clamp(8, 2400);
        let mut pts = Vec::new();
        let mut mid: Option<(V3, V3, f64)> = None;
        for k in 0..=n {
            let s = exp * k as f64 / n as f64;
            let t = at(s);
            let Some(r) = state(it, &t, dt_of(&t)) else { continue };
            let o = obs_teme(&obs, &t);
            let u = unit(&sub(&r, &o));
            if let Some(q) = view.proj(&u) {
                if q.0.abs() < view.half * 1.3 && q.1.abs() < view.half * 1.3 {
                    pts.push([(q.0 * 1e5).round() / 1e5, (q.1 * 1e5).round() / 1e5]);
                    if mid.is_none() { mid = Some((r, o, s)); }
                }
            }
        }
        let Some((r, o, s_mid)) = mid else { continue };
        if !sunlit(&r, &sun0) { shadowed += 1; continue; }
        if pts.len() < 2 { continue; }
        let m = mag_at(&r, &o, &sun0, std_mag(it));
        let (a, b) = (pts[0], pts[pts.len() - 1]);
        let span_s = exp * (pts.len() - 1) as f64 / ((exp / 0.25).ceil().clamp(8.0, 2400.0));
        let omega = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt() / span_s.max(1e-3);
        streaks.push(json!({"name": name_of(it), "group": it.group, "mag": (m * 10.0).round() / 10.0,
            "omega": omega, "range_km": norm(&sub(&r, &o)).round(), "pts": pts,
            // 3D 顯示用：第一次進入視野時的 TEME 位置（km）與距曝光開始的秒數
            "r_teme": [r[0].round(), r[1].round(), r[2].round()], "t_s": (s_mid * 100.0).round() / 100.0}));
    }

    // 整夜統計：14 小時內每 10 分鐘一次曝光，天文昏影後、指向仰角 > 20° 才算
    let mut night = Vec::new();
    if rq.night.unwrap_or(true) {
        for k in 0..84 {
            let tk = t0 + Duration::minutes(10 * k);
            let s = sun_dir(&tk);
            let sa = alt_of(&obs, &s, &tk);
            let pa = alt_of(&obs, &p, &tk);
            if sa > -12.0 || pa < 20.0 {
                night.push(json!({"t": tk.to_rfc3339(), "sun_alt": sa, "alt": pa, "n": null}));
                continue;
            }
            let ts: Vec<DateTime<Utc>> = times.iter().map(|&x| tk + Duration::milliseconds((x * 1000.0) as i64)).collect();
            let cnt = (0..items.len())
                .into_par_iter()
                .filter(|&i| {
                    let mut prev: Option<(f64, f64)> = None;
                    for t in &ts {
                        let Some(r) = state(&items[i], t, dt_of(t)) else { return false };
                        let u = unit(&sub(&r, &obs_teme(&obs, t)));
                        let Some(q) = view.proj(&u) else { prev = None; continue };
                        if let Some(a) = prev {
                            if seg_hits(a, q, view.half) { return sunlit(&r, &s); }
                        }
                        prev = Some(q);
                    }
                    false
                })
                .count();
            night.push(json!({"t": tk.to_rfc3339(), "sun_alt": sa, "alt": pa, "n": cnt}));
        }
    }
    Json(json!({
        "t0": t0.to_rfc3339(), "exp_s": exp, "fov_deg": fov, "sun_alt": sun_alt, "point_alt": point_alt,
        "objects": items.len(), "streaks": streaks, "shadowed": shadowed, "night": night,
        "elapsed_s": t_start.elapsed().as_secs_f64(),
    }))
    .into_response()
}
