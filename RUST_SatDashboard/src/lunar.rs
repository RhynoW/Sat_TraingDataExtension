//! 台北衛星凌月預報（Moon transit），對應 Python physics/lunar_transit.py。
//!
//! 月球／太陽站心位置使用內附的 astronomy-engine C 版（與 Python 版同一套引擎）。
//! TLE 沿軌誤差（低軌約 0.2–0.5°）與月面視半徑（~0.26°）同量級，屬事件預報等級。

use std::collections::HashSet;

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use rayon::prelude::*;
use serde_json::{json, Map, Value};

use crate::coverage::{self, Cat, TAIPEI_H_KM, TAIPEI_LAT, TAIPEI_LON};
use crate::index::{SatIndex, SatInfo};
use crate::physics::{gmst_rad, julian_date, round_to, Observer, Propagator};

// ── astronomy-engine FFI（僅宣告用到的結構與函式）──────────────────────────
mod ffi {
    #![allow(non_camel_case_types, dead_code)]
    pub type astro_status_t = i32;
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_time_t {
        pub ut: f64,
        pub tt: f64,
        pub psi: f64,
        pub eps: f64,
        pub st: f64,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_observer_t {
        pub latitude: f64,
        pub longitude: f64,
        pub height: f64,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_vector_t {
        pub status: astro_status_t,
        pub x: f64,
        pub y: f64,
        pub z: f64,
        pub t: astro_time_t,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_equatorial_t {
        pub status: astro_status_t,
        pub ra: f64,
        pub dec: f64,
        pub dist: f64,
        pub vec: astro_vector_t,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_horizon_t {
        pub azimuth: f64,
        pub altitude: f64,
        pub ra: f64,
        pub dec: f64,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_illum_t {
        pub status: astro_status_t,
        pub time: astro_time_t,
        pub mag: f64,
        pub phase_angle: f64,
        pub phase_fraction: f64,
        pub helio_dist: f64,
        pub ring_tilt: f64,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct astro_angle_result_t {
        pub status: astro_status_t,
        pub angle: f64,
    }
    pub const BODY_SUN: i32 = 9;
    pub const BODY_MOON: i32 = 10;
    pub const EQUATOR_OF_DATE: i32 = 1;
    pub const ABERRATION: i32 = 0;
    pub const REFRACTION_NONE: i32 = 0;

    extern "C" {
        pub fn Astronomy_TimeFromDays(ut: f64) -> astro_time_t;
        pub fn Astronomy_Equator(
            body: i32,
            time: *mut astro_time_t,
            observer: astro_observer_t,
            equdate: i32,
            aberration: i32,
        ) -> astro_equatorial_t;
        pub fn Astronomy_Horizon(
            time: *mut astro_time_t,
            observer: astro_observer_t,
            ra: f64,
            dec: f64,
            refraction: i32,
        ) -> astro_horizon_t;
        pub fn Astronomy_Illumination(body: i32, time: astro_time_t) -> astro_illum_t;
        pub fn Astronomy_MoonPhase(time: astro_time_t) -> astro_angle_result_t;
    }
}

const MOON_RADIUS_KM: f64 = 1737.4;
const AU_KM: f64 = 149_597_870.7;
const COARSE_DEG: f64 = 1.5;

fn astro_observer() -> ffi::astro_observer_t {
    ffi::astro_observer_t {
        latitude: TAIPEI_LAT,
        longitude: TAIPEI_LON,
        height: TAIPEI_H_KM * 1000.0,
    }
}

/// 天體站心（方位°, 仰角°, 距離 km），無大氣折射、含光行差、當日赤道
fn body_horizon(body: i32, ut_days: f64) -> (f64, f64, f64) {
    // SAFETY: 純數值 C 函式，參數皆為值或指向區域變數之指標
    unsafe {
        let mut t = ffi::Astronomy_TimeFromDays(ut_days);
        let obs = astro_observer();
        let eq = ffi::Astronomy_Equator(body, &mut t, obs, ffi::EQUATOR_OF_DATE, ffi::ABERRATION);
        let h = ffi::Astronomy_Horizon(&mut t, obs, eq.ra, eq.dec, ffi::REFRACTION_NONE);
        (h.azimuth, h.altitude, eq.dist * AU_KM)
    }
}

/// 任一地面點的太陽仰角（°，幾何仰角、無折射）；任務規劃頁用來判斷夜間過頂
pub fn sun_elevation(lat: f64, lon: f64, h_km: f64, t: &DateTime<Utc>) -> f64 {
    let ut = julian_date(t) - 2451545.0;
    // SAFETY: 純數值 C 函式，參數皆為值或指向區域變數之指標
    unsafe {
        let mut at = ffi::Astronomy_TimeFromDays(ut);
        let obs = ffi::astro_observer_t { latitude: lat, longitude: lon, height: h_km * 1000.0 };
        let eq = ffi::Astronomy_Equator(ffi::BODY_SUN, &mut at, obs, ffi::EQUATOR_OF_DATE, ffi::ABERRATION);
        ffi::Astronomy_Horizon(&mut at, obs, eq.ra, eq.dec, ffi::REFRACTION_NONE).altitude
    }
}

type V3 = [f64; 3];

fn dot(a: &V3, b: &V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: &V3, b: &V3) -> V3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn norm(a: &V3) -> f64 {
    dot(a, a).sqrt()
}
fn scale(a: &V3, k: f64) -> V3 {
    [a[0] * k, a[1] * k, a[2] * k]
}
fn unit(a: &V3) -> V3 {
    let n = norm(a);
    if n > 1e-12 {
        scale(a, 1.0 / n)
    } else {
        *a
    }
}
fn unit_from_azel(az_deg: f64, el_deg: f64) -> V3 {
    let (az, el) = (az_deg.to_radians(), el_deg.to_radians());
    [el.cos() * az.sin(), el.cos() * az.cos(), el.sin()]
}

/// 月球站心方位／仰角格點（供線性內插）
struct Moon {
    t0: DateTime<Utc>,
    ut0: f64,
    offs: Vec<f64>,
    az: Vec<f64>,
    el: Vec<f64>,
    dist: Vec<f64>,
    u: Vec<V3>,
    uc: [Vec<f64>; 3],
}

fn interp(x: f64, xs: &[f64], ys: &[f64]) -> f64 {
    if x <= xs[0] {
        return ys[0];
    }
    let n = xs.len();
    if x >= xs[n - 1] {
        return ys[n - 1];
    }
    let i = xs.partition_point(|v| *v <= x).max(1);
    let (x0, x1) = (xs[i - 1], xs[i]);
    ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)
}

impl Moon {
    fn new(t0: DateTime<Utc>, offs: Vec<f64>) -> Self {
        let ut0 = julian_date(&t0) - 2451545.0;
        let vals: Vec<(f64, f64, f64)> = offs
            .par_iter()
            .map(|s| body_horizon(ffi::BODY_MOON, ut0 + s / 86400.0))
            .collect();
        let az: Vec<f64> = vals.iter().map(|v| v.0).collect();
        let el: Vec<f64> = vals.iter().map(|v| v.1).collect();
        let dist: Vec<f64> = vals.iter().map(|v| v.2).collect();
        let u: Vec<V3> = az.iter().zip(&el).map(|(a, e)| unit_from_azel(*a, *e)).collect();
        let uc = [0, 1, 2].map(|c| u.iter().map(|v| v[c]).collect::<Vec<f64>>());
        Self {
            t0,
            ut0,
            offs,
            az,
            el,
            dist,
            u,
            uc,
        }
    }

    fn unit_at(&self, s: f64) -> V3 {
        let comp = |c: usize| interp(s, &self.offs, &self.uc[c]);
        unit(&[comp(0), comp(1), comp(2)])
    }

    fn radius_deg(&self, s: f64) -> f64 {
        (MOON_RADIUS_KM / interp(s, &self.offs, &self.dist))
            .asin()
            .to_degrees()
    }

    fn time_at(&self, s: f64) -> DateTime<Utc> {
        self.t0 + Duration::microseconds((s * 1e6).round() as i64)
    }
}

/// 衛星站心單位向量（傳播失敗 → None）與斜距
fn sat_unit(p: &Propagator, t: &DateTime<Utc>, obs: &Observer) -> Option<(V3, f64)> {
    let r = p.position(t)?;
    let enu = obs.enu(&r, gmst_rad(t));
    let rng = norm(&enu);
    Some((scale(&enu, 1.0 / rng.max(1e-3)), rng))
}

fn sep_deg(u: &V3, m: &V3) -> f64 {
    dot(u, m).clamp(-1.0, 1.0).acos().to_degrees()
}

/// 以月球方向為視軸之畫面基底：right＝方位角增加方向，up＝天頂方向
fn tangent_basis(m: &V3) -> (V3, V3) {
    let right = unit(&[m[1], -m[0], 0.0]);
    let up = unit(&[-m[2] * m[0], -m[2] * m[1], 1.0 - m[2] * m[2]]);
    (right, up)
}

fn screen_xy(u: &V3, m: &V3) -> (f64, f64) {
    let (r, up) = tangent_basis(m);
    let d = dot(u, m);
    (
        dot(u, &r).atan2(d).to_degrees(),
        dot(u, &up).atan2(d).to_degrees(),
    )
}

/// 相鄰兩步之大圓弧與月球的最小角距（粗篩）
fn arc_min_dist(a: &V3, b: &V3, m: &V3) -> f64 {
    let n = unit(&cross(a, b));
    let pn = dot(&n, m);
    let c = unit(&[m[0] - pn * n[0], m[1] - pn * n[1], m[2] - pn * n[2]]);
    let inside = dot(&cross(a, &c), &n) >= 0.0 && dot(&cross(&c, b), &n) >= 0.0;
    let d = if inside {
        pn.abs().clamp(0.0, 1.0).asin()
    } else {
        dot(a, m)
            .clamp(-1.0, 1.0)
            .acos()
            .min(dot(b, m).clamp(-1.0, 1.0).acos())
    };
    d.to_degrees()
}

struct Refined {
    s: f64,
    sep: f64,
    omega: f64,
    r: f64,
    track: Vec<Value>,
    sat_az: f64,
    sat_el: f64,
    sat_range_km: f64,
}

fn refine(p: &Propagator, moon: &Moon, s_center: f64, obs: &Observer) -> Option<Refined> {
    let sep_at = |s: f64| -> Option<(f64, V3, f64)> {
        let (u, rng) = sat_unit(p, &moon.time_at(s), obs)?;
        Some((sep_deg(&u, &moon.unit_at(s)), u, rng))
    };
    // 0.5 s 粗掃 ±75 s
    let mut best: Option<(f64, f64)> = None;
    for k in 0..=300 {
        let s = s_center - 75.0 + k as f64 * 0.5;
        if let Some((d, _, _)) = sep_at(s) {
            if best.map_or(true, |b| d < b.1) {
                best = Some((s, d));
            }
        }
    }
    let (s_best, _) = best?;
    // 0.02 s 細掃 ±1 s
    let mut fine: Option<(f64, f64, V3, f64)> = None;
    for k in 0..=100 {
        let s = s_best - 1.0 + k as f64 * 0.02;
        if let Some((d, u, rng)) = sep_at(s) {
            if fine.map_or(true, |f| d < f.1) {
                fine = Some((s, d, u, rng));
            }
        }
    }
    let (s_min, sep_min, u_min, rng_min) = fine?;

    // 相對角速度（度/秒）
    let mut rel = Vec::new();
    for s in [s_min - 0.1, s_min + 0.1] {
        let (u, _) = sat_unit(p, &moon.time_at(s), obs)?;
        rel.push(screen_xy(&u, &moon.unit_at(s)));
    }
    let omega = ((rel[1].0 - rel[0].0).hypot(rel[1].1 - rel[0].1) / 0.2).max(1e-4);
    let r = moon.radius_deg(s_min);
    let half = ((r + 0.65) / omega).clamp(1.0, 90.0);
    let track: Vec<Value> = (0..61)
        .filter_map(|i| {
            let s = s_min - half + 2.0 * half * i as f64 / 60.0;
            let (u, _) = sat_unit(p, &moon.time_at(s), obs)?;
            let (x, y) = screen_xy(&u, &moon.unit_at(s));
            Some(json!([round_to(s - s_min, 2), round_to(x, 4), round_to(y, 4)]))
        })
        .collect();
    Some(Refined {
        s: s_min,
        sep: sep_min,
        omega,
        r,
        track,
        sat_az: u_min[0].atan2(u_min[1]).to_degrees().rem_euclid(360.0),
        sat_el: u_min[2].clamp(-1.0, 1.0).asin().to_degrees(),
        sat_range_km: rng_min,
    })
}

/// (太陽於月球畫面之方位角°, 照亮比例, 月相角°)
fn sun_dir(moon: &Moon, s: f64) -> (f64, f64, f64) {
    let ut = moon.ut0 + s / 86400.0;
    let (az, el, _) = body_horizon(ffi::BODY_SUN, ut);
    let sv = unit_from_azel(az, el);
    let (right, up) = tangent_basis(&moon.unit_at(s));
    let ang = dot(&sv, &up).atan2(dot(&sv, &right)).to_degrees();
    // SAFETY: 純數值 C 函式
    let (frac, phase) = unsafe {
        let t = ffi::Astronomy_TimeFromDays(ut);
        (
            ffi::Astronomy_Illumination(ffi::BODY_MOON, t).phase_fraction,
            ffi::Astronomy_MoonPhase(t).angle,
        )
    };
    (ang, frac, phase)
}

const STATION_CAT: &str = "STATION";
const STATION_GROUPS: [&[u32]; 2] = [&[25544, 25575, 26400, 26700, 49044], &[48274, 53239, 54216]];

#[allow(clippy::too_many_arguments)]
pub fn find_lunar_transits(
    idx: &SatIndex,
    cats: &[Cat],
    ts: DateTime<Utc>,
    hours: f64,
    near_margin: f64,
    want: Option<&HashSet<String>>,
) -> Value {
    let step_s = 60.0;
    let min_el = 5.0;
    let max_events = 300;
    let obs = coverage::taipei();
    let n = (hours * 3600.0 / step_s) as usize + 1;
    let offs: Vec<f64> = (0..n).map(|i| i as f64 * step_s).collect();
    let moon = Moon::new(ts, offs.clone());
    let moon_runs = coverage::runs(moon.el.iter().map(|e| *e >= min_el));

    // 群組：台北過頂類別 + 空間站
    let mut groups: Vec<(String, String, Vec<&SatInfo>)> = coverage::candidates(idx, cats)
        .into_iter()
        .zip(cats)
        .map(|(v, c)| (c.key.clone(), c.color.clone(), v))
        .collect();
    let stations: Vec<&SatInfo> = STATION_GROUPS
        .iter()
        .filter_map(|ids| ids.iter().find_map(|n| idx.sats.get(n)))
        .collect();
    groups.push((STATION_CAT.into(), "#FFFFFF".into(), stations));
    let mut catinfo: Map<String, Value> = cats
        .iter()
        .map(|c| (c.key.clone(), coverage::cat_info(c)))
        .collect();
    catinfo.insert(
        STATION_CAT.into(),
        json!({"label": "空間站 ISS / CSS", "sublabel": "ISS · 中國空間站", "color": "#FFFFFF"}),
    );

    let zmin = (min_el - 1.0).to_radians().sin();
    let mut events: Vec<(DateTime<Utc>, Value)> = Vec::new();
    let mut scanned: HashSet<u32> = HashSet::new();
    for &(a0, b0) in &moon_runs {
        if b0 - a0 < 2 {
            continue;
        }
        let run_times: Vec<DateTime<Utc>> = offs[a0..=b0].iter().map(|s| moon.time_at(*s)).collect();
        let m_run = &moon.u[a0..=b0];
        for (cat, color, list) in &groups {
            if want.map_or(false, |w| !w.contains(cat)) || list.is_empty() {
                continue;
            }
            scanned.extend(list.iter().map(|s| s.norad_id));
            let found: Vec<(DateTime<Utc>, Value)> = list
                .par_iter()
                .filter_map(|s| {
                    let p = s.prop.as_ref()?;
                    let us: Vec<V3> = run_times
                        .iter()
                        .map(|t| sat_unit(p, t, &obs).map(|x| x.0).unwrap_or([0.0, 0.0, -1.0]))
                        .collect();
                    // 粗篩：兩端點皆在地平線上之弧的最小角距
                    let mut best = (f64::INFINITY, 0usize);
                    for k in 0..us.len() - 1 {
                        if us[k][2] < zmin || us[k + 1][2] < zmin {
                            continue;
                        }
                        let mid = unit(&[
                            m_run[k][0] + m_run[k + 1][0],
                            m_run[k][1] + m_run[k + 1][1],
                            m_run[k][2] + m_run[k + 1][2],
                        ]);
                        let d = arc_min_dist(&us[k], &us[k + 1], &mid);
                        if d < best.0 {
                            best = (d, k);
                        }
                    }
                    if best.0 >= COARSE_DEG {
                        return None;
                    }
                    let s_c = offs[a0 + best.1] + step_s / 2.0;
                    let r = refine(p, &moon, s_c, &obs)?;
                    if r.sep > r.r + near_margin || r.sat_el < min_el {
                        return None;
                    }
                    let when = moon.time_at(r.s);
                    let (sun_ang, frac, phase) = sun_dir(&moon, r.s);
                    let transit = r.sep <= r.r;
                    let chord = if transit {
                        2.0 * (r.r * r.r - r.sep * r.sep).max(0.0).sqrt() / r.omega
                    } else {
                        0.0
                    };
                    let mi = offs
                        .iter()
                        .enumerate()
                        .min_by(|x, y| (x.1 - r.s).abs().total_cmp(&(y.1 - r.s).abs()))
                        .map(|x| x.0)
                        .unwrap_or(0);
                    Some((
                        when,
                        json!({
                            "norad_id": s.norad_id, "name": s.name, "cat": cat, "color": color,
                            "t_utc": when.to_rfc3339_opts(SecondsFormat::Millis, false),
                            "kind": if transit { "transit" } else { "near" },
                            "sep_deg": round_to(r.sep, 4), "moon_r_deg": round_to(r.r, 4),
                            "chord_s": round_to(chord, 3), "omega_dps": round_to(r.omega, 3),
                            "sat_az": round_to(r.sat_az, 2), "sat_el": round_to(r.sat_el, 2),
                            "sat_range_km": round_to(r.sat_range_km, 1),
                            "moon_az": round_to(moon.az[mi], 2), "moon_el": round_to(moon.el[mi], 2),
                            "moon_frac": round_to(frac, 4), "moon_phase_deg": round_to(phase, 1),
                            "sun_angle_deg": round_to(sun_ang, 2),
                            "track": r.track,
                        }),
                    ))
                })
                .collect();
            events.extend(found);
        }
    }
    events.sort_by_key(|(t, _)| *t);
    let n_events = events.len();
    events.truncate(max_events);
    json!({
        "timestamp": coverage::iso(&ts), "hours": hours, "step_sec": step_s,
        "near_margin_deg": near_margin, "min_el_deg": min_el,
        "moon_up_runs": moon_runs.iter().map(|&(a, b)| json!([
            coverage::iso(&moon.time_at(offs[a])), coverage::iso(&moon.time_at(offs[b]))
        ])).collect::<Vec<_>>(),
        "n_scanned": scanned.len(),
        "categories": catinfo,
        "events": events.into_iter().map(|(_, v)| v).collect::<Vec<_>>(),
        "n_events": n_events,
        "note": "TLE 沿軌誤差（低軌約 0.2–0.5°）與月面視半徑（~0.26°）同量級，屬事件預報；實際凌月帶寬僅數公里，觀測前請以最新 TLE 重算。",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moon_distance_sane() {
        let (_, el, d) = body_horizon(ffi::BODY_MOON, 9000.0);
        assert!((356_000.0..407_000.0).contains(&d), "{d}");
        assert!((-90.0..=90.0).contains(&el));
    }
}
