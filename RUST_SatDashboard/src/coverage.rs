//! 台北覆蓋分析：類別定義、即時 / 指定時刻覆蓋、過頂預報、天球過頂軌跡。
//! 對應 Python physics/coverage.py、skypass.py。

use std::path::Path;

use chrono::{DateTime, Duration, Utc};
use rayon::prelude::*;
use serde_json::{json, Map, Value};

use crate::index::{SatIndex, SatInfo};
use crate::physics::{self, eci_to_llh, gmst_rad, round_to, Observer};

pub const TAIPEI_LAT: f64 = 25.0330;
pub const TAIPEI_LON: f64 = 121.5654;
pub const TAIPEI_H_KM: f64 = 0.01;
pub const MASK_DEG: f64 = 5.0;
pub const TIMELINE_DAYS: i64 = 30;

pub const DEFAULT_CATS_YAML: &str = include_str!("../config/overpass_cats.yaml");

pub fn taipei() -> Observer {
    Observer::new(TAIPEI_LAT, TAIPEI_LON, TAIPEI_H_KM)
}

#[derive(Debug, Clone)]
pub struct Cat {
    pub key: String,
    pub label: String,
    pub sublabel: String,
    pub color: String,
    pub kw: Vec<String>,
}

pub fn load_cats(paths: &[&Path]) -> Vec<Cat> {
    for p in paths {
        if let Ok(t) = std::fs::read_to_string(p) {
            match parse_cats(&t) {
                Ok(c) if !c.is_empty() => {
                    tracing::info!("過頂類別載入自 {}（{} 類）", p.display(), c.len());
                    return c;
                }
                Ok(_) => {}
                Err(e) => tracing::warn!("{} 載入失敗：{e}", p.display()),
            }
        }
    }
    parse_cats(DEFAULT_CATS_YAML).expect("內建 overpass_cats.yaml 格式錯誤")
}

fn parse_cats(text: &str) -> anyhow::Result<Vec<Cat>> {
    let v: serde_yaml::Mapping = serde_yaml::from_str(text)?;
    let s = |m: &serde_yaml::Value, k: &str| m.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    Ok(v.iter()
        .filter_map(|(k, m)| {
            Some(Cat {
                key: k.as_str()?.to_string(),
                label: s(m, "label"),
                sublabel: s(m, "sublabel"),
                color: s(m, "color"),
                kw: m
                    .get("kw")?
                    .as_sequence()?
                    .iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_uppercase()))
                    .collect(),
            })
        })
        .collect())
}

pub fn cat_info(c: &Cat) -> Value {
    json!({"label": c.label, "sublabel": c.sublabel, "color": c.color})
}

/// 各類別候選衛星（碎片 / 火箭體不計；每顆只歸第一個命中類別）
pub fn candidates<'a>(idx: &'a SatIndex, cats: &[Cat]) -> Vec<Vec<&'a SatInfo>> {
    let mut out: Vec<Vec<&SatInfo>> = vec![Vec::new(); cats.len()];
    for s in idx.sats.values() {
        let up = s.name.to_uppercase();
        if up.contains(" DEB") || up.contains(" R/B") {
            continue;
        }
        if let Some(ci) = cats
            .iter()
            .position(|c| c.kw.iter().any(|k| up.contains(k.as_str())))
        {
            out[ci].push(s);
        }
    }
    out
}

pub fn iso(t: &DateTime<Utc>) -> String {
    t.to_rfc3339()
}

pub fn clamp_ts(ts: Option<DateTime<Utc>>) -> DateTime<Utc> {
    let now = Utc::now();
    let t = ts.unwrap_or(now);
    t.max(now - Duration::days(TIMELINE_DAYS))
        .min(now + Duration::days(TIMELINE_DAYS))
}

pub fn is_historical(ts: &DateTime<Utc>) -> bool {
    *ts < Utc::now() - Duration::hours(1)
}

// ── 覆蓋（單一時刻）────────────────────────────────────────────────────────

pub fn coverage(idx: &SatIndex, cats: &[Cat], t: DateTime<Utc>, mask: f64, timeline: bool) -> Value {
    let obs = taipei();
    let g = gmst_rad(&t);
    let cand = candidates(idx, cats);
    let mut result = Map::new();
    for (c, list) in cats.iter().zip(cand) {
        let sats: Vec<Value> = list
            .par_iter()
            .filter_map(|s| {
                let r = s.prop.as_ref()?.position(&t)?;
                let llh = eci_to_llh(&r, g);
                if !(llh[2] > -500.0 && llh[2] < 80_000.0) {
                    return None;
                }
                let (el, az, rng) = obs.elaz(&r, g);
                Some(json!({
                    "norad_id": s.norad_id,
                    "name": s.name,
                    "lat": round_to(llh[0], 4),
                    "lon": round_to(llh[1], 4),
                    "alt_km": round_to(llh[2], 1),
                    "el_deg": round_to(el, 2),
                    "az_deg": round_to(az, 2),
                    "range_km": round_to(rng, 1),
                    "visible": el >= mask,
                    "color": c.color,
                }))
            })
            .collect();
        let visible = sats.iter().filter(|s| s["visible"] == json!(true)).count();
        result.insert(
            c.key.clone(),
            json!({"label": c.label, "sublabel": c.sublabel, "color": c.color,
                   "count": sats.len(), "visible_count": visible, "satellites": sats}),
        );
    }
    let mut out = json!({"categories": result, "timestamp": iso(&t), "mask_deg": mask});
    if timeline {
        out["is_historical"] = json!(is_historical(&t));
        out["is_future"] = json!(t > Utc::now() + Duration::hours(1));
    }
    out
}

// ── 過頂預報 ───────────────────────────────────────────────────────────────

/// 單顆衛星在時間格點上的仰角序列（傳播失敗 = -90°）
fn elevation_series(s: &SatInfo, times: &[DateTime<Utc>], gmsts: &[f64], obs: &Observer) -> Option<Vec<f64>> {
    let p = s.prop.as_ref()?;
    let el: Vec<f64> = times
        .iter()
        .zip(gmsts)
        .map(|(t, g)| p.position(t).map(|r| obs.elaz(&r, *g).0).unwrap_or(-90.0))
        .collect();
    Some(el)
}

/// 連續 ≥ mask 之區段 (首索引, 末索引)（含端點）
pub fn runs(mask: impl Iterator<Item = bool>) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start: Option<usize> = None;
    let mut last = 0;
    for (i, m) in mask.enumerate() {
        last = i;
        match (m, start) {
            (true, None) => start = Some(i),
            (false, Some(a)) => {
                out.push((a, i - 1));
                start = None;
            }
            _ => {}
        }
    }
    if let Some(a) = start {
        out.push((a, last));
    }
    out
}

pub fn passes(
    idx: &SatIndex,
    cats: &[Cat],
    t0: DateTime<Utc>,
    hours: f64,
    step_sec: f64,
    mask: f64,
    timeline: bool,
) -> Value {
    const MAX_PER_CAT: usize = 20;
    let obs = taipei();
    let n = (hours * 3600.0 / step_sec) as usize;
    let times: Vec<DateTime<Utc>> = (0..n)
        .map(|i| t0 + Duration::milliseconds((i as f64 * step_sec * 1000.0) as i64))
        .collect();
    let gmsts: Vec<f64> = times.iter().map(physics::gmst_rad).collect();
    let cand = candidates(idx, cats);
    let mut result = Map::new();
    for (c, list) in cats.iter().zip(cand) {
        let mut cat_passes: Vec<(DateTime<Utc>, Value)> = list
            .par_iter()
            .flat_map_iter(|s| {
                let mut v = Vec::new();
                let Some(el) = elevation_series(s, &times, &gmsts, &obs) else {
                    return v;
                };
                for (a, b) in runs(el.iter().map(|e| *e >= mask)) {
                    // 同 Python：落地點取「首次低於遮罩」之時刻；到窗末仍在上方則取末點
                    let set_i = if b + 1 < n { b + 1 } else { n - 1 };
                    if a >= set_i {
                        continue;
                    }
                    let seg = &el[a..=set_i];
                    let (mx, max_el) =
                        seg.iter().enumerate().fold(
                            (0, f64::MIN),
                            |acc, (i, e)| if *e > acc.1 { (i, *e) } else { acc },
                        );
                    v.push((
                        times[a],
                        json!({
                            "norad_id": s.norad_id,
                            "name": s.name,
                            "t_rise_utc": iso(&times[a]),
                            "t_max_utc": iso(&times[a + mx]),
                            "t_set_utc": iso(&times[set_i]),
                            "max_el_deg": round_to(max_el, 1),
                            "duration_s": (times[set_i] - times[a]).num_seconds(),
                            "color": c.color,
                        }),
                    ));
                }
                v
            })
            .collect();
        cat_passes.sort_by_key(|(t, _)| *t);
        cat_passes.truncate(MAX_PER_CAT);
        result.insert(
            c.key.clone(),
            json!({"label": c.label, "sublabel": c.sublabel, "color": c.color,
                   "passes": cat_passes.into_iter().map(|(_, v)| v).collect::<Vec<_>>()}),
        );
    }
    let mut out = json!({"categories": result, "hours": hours, "mask_deg": mask, "timestamp": iso(&t0)});
    if timeline {
        out["is_historical"] = json!(is_historical(&t0));
        out["is_future"] = json!(t0 > Utc::now() + Duration::hours(1));
    }
    out
}

// ── 天球過頂軌跡 ───────────────────────────────────────────────────────────

/// ECEF(km) → 星下點大地緯度／經度（度，Bowring 3 次疊代）
fn subpoint(e: &[f64; 3]) -> (f64, f64) {
    let a = 6378.137;
    let f = 1.0 / 298.257223563;
    let e2 = f * (2.0 - f);
    let lon = e[1].atan2(e[0]);
    let p = e[0].hypot(e[1]);
    let mut lat = e[2].atan2(p * (1.0 - e2));
    for _ in 0..3 {
        let n = a / (1.0 - e2 * lat.sin().powi(2)).sqrt();
        lat = (e[2] + e2 * n * lat.sin()).atan2(p);
    }
    (lat.to_degrees(), lon.to_degrees())
}

fn ptp(v: impl Iterator<Item = f64>) -> f64 {
    let (lo, hi) = v.fold((f64::MAX, f64::MIN), |(lo, hi), x| (lo.min(x), hi.max(x)));
    hi - lo
}

#[allow(clippy::too_many_arguments)]
pub fn sky_passes(
    idx: &SatIndex,
    cats: &[Cat],
    ts: DateTime<Utc>,
    hours: f64,
    step_sec: f64,
    mask: f64,
    min_el: f64,
    max_per_cat: usize,
) -> Value {
    const MAX_EVALS: f64 = 6_000_000.0;
    const STATIONARY_DEG: f64 = 3.0;
    let obs = taipei();
    let cand = candidates(idx, cats);
    let n_all: usize = cand.iter().map(Vec::len).sum();

    let mut step = step_sec.max(10.0);
    let mut n = (hours * 3600.0 / step) as usize + 1;
    if n_all > 0 && (n_all * n) as f64 > MAX_EVALS {
        step = step.max((hours * 3600.0 * n_all as f64 / MAX_EVALS).ceil());
        n = (hours * 3600.0 / step) as usize + 1;
    }
    let offs: Vec<f64> = (0..n).map(|i| i as f64 * step).collect();
    let times: Vec<DateTime<Utc>> = offs
        .iter()
        .map(|s| ts + Duration::milliseconds((s * 1000.0) as i64))
        .collect();
    let gmsts: Vec<f64> = times.iter().map(gmst_rad).collect();

    let mut all: Vec<(DateTime<Utc>, Value)> = Vec::new();
    for (c, list) in cats.iter().zip(cand) {
        let mut cat_passes: Vec<(f64, DateTime<Utc>, Value)> = list
            .par_iter()
            .flat_map_iter(|s| {
                let mut v = Vec::new();
                let Some(p) = s.prop.as_ref() else { return v };
                // (az, el, sublat, sublon)
                let pts: Vec<(f64, f64, f64, f64)> = times
                    .iter()
                    .zip(&gmsts)
                    .map(|(t, g)| match p.position(t) {
                        Some(r) => {
                            let (el, az, _) = obs.elaz(&r, *g);
                            let (la, lo) = subpoint(&physics::teme_to_ecef(&r, *g));
                            (az, el, la, lo)
                        }
                        None => (0.0, -90.0, 0.0, 0.0),
                    })
                    .collect();
                for (a, b) in runs(pts.iter().map(|x| x.1 >= mask)) {
                    let seg = &pts[a..=b];
                    let (mx, max_el) =
                        seg.iter().enumerate().fold(
                            (0, f64::MIN),
                            |acc, (i, x)| if x.1 > acc.1 { (i, x.1) } else { acc },
                        );
                    if max_el < min_el {
                        continue;
                    }
                    let mut track: Vec<Value> = (a..=b)
                        .map(|i| {
                            let (az, el, la, lo) = pts[i];
                            json!([
                                offs[i] as i64,
                                round_to(az, 1),
                                round_to(el, 1),
                                round_to(la, 2),
                                round_to(lo, 2)
                            ])
                        })
                        .collect();
                    let az_ptp = ptp(seg.iter().map(|x| x.0));
                    let stationary = a == 0
                        && b == n - 1
                        && ptp(seg.iter().map(|x| x.1)) < STATIONARY_DEG
                        && az_ptp.min(360.0 - az_ptp) < STATIONARY_DEG;
                    if stationary {
                        track = vec![track[0].clone(), track[track.len() - 1].clone()];
                    }
                    v.push((
                        max_el,
                        times[a],
                        json!({
                            "norad_id": s.norad_id,
                            "name": s.name,
                            "cat": c.key,
                            "color": c.color,
                            "t_rise_utc": iso(&times[a]),
                            "t_max_utc": iso(&times[a + mx]),
                            "t_set_utc": iso(&times[b]),
                            "max_el_deg": round_to(max_el, 1),
                            "duration_s": (offs[b] - offs[a]) as i64,
                            "clipped_start": a == 0,
                            "clipped_end": b == n - 1,
                            "stationary": stationary,
                            "track": track,
                        }),
                    ));
                }
                v
            })
            .collect();
        cat_passes.sort_by(|x, y| y.0.total_cmp(&x.0));
        cat_passes.truncate(max_per_cat);
        all.extend(cat_passes.into_iter().map(|(_, t, v)| (t, v)));
    }
    all.sort_by_key(|(t, _)| *t);
    let cats_json: Map<String, Value> = cats.iter().map(|c| (c.key.clone(), cat_info(c))).collect();
    json!({
        "timestamp": iso(&ts),
        "hours": hours,
        "step_sec": step,
        "mask_deg": mask,
        "min_el_deg": min_el,
        "observer": {"lat": TAIPEI_LAT, "lon": TAIPEI_LON, "h_km": TAIPEI_H_KM},
        "categories": cats_json,
        "passes": all.into_iter().map(|(_, v)| v).collect::<Vec<_>>(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runs_detect() {
        let v = [false, true, true, false, true];
        assert_eq!(runs(v.iter().copied()), vec![(1, 2), (4, 4)]);
        assert!(runs([false, false].iter().copied()).is_empty());
    }

    #[test]
    fn default_cats() {
        let c = parse_cats(DEFAULT_CATS_YAML).unwrap();
        assert_eq!(c[0].key, "US_EO");
        assert!(c.iter().any(|x| x.key == "STARLINK"));
    }
}
