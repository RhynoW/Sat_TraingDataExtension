//! 近地點掠過分析器（零階再入估算，SGP4）——Python 版 physics/reentry_pass.py 的移植。
//! 時間以整數微秒運算，與 Python datetime/timedelta 的微秒捨入一致。

use chrono::{DateTime, TimeZone, Timelike, Utc};
use serde_json::{json, Value};

use super::common::{eci_to_llh_py, py_round, Sat};

/// timedelta(seconds=x) 的微秒（半數取偶）
fn td_us(sec: f64) -> i64 {
    let us = sec * 1e6;
    let r = us.round();
    if (us - us.trunc()).abs() == 0.5 {
        let t = us.trunc();
        if (t as i64) % 2 == 0 {
            t as i64
        } else {
            r as i64
        }
    } else {
        r as i64
    }
}

fn alt_at(sat: &Sat, us: i64) -> Option<f64> {
    let t = us as f64 / 1e6;
    let (r, _) = sat.pv_unix(t)?;
    Some(eci_to_llh_py(&r, t)[2])
}

fn iso_z_secs(us: i64) -> String {
    let t = DateTime::<Utc>::from_timestamp_micros(us).unwrap_or_default();
    t.format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn iso_z(us: i64) -> String {
    let t = DateTime::<Utc>::from_timestamp_micros(us).unwrap_or_default();
    let sub = t.timestamp_subsec_micros();
    if sub == 0 {
        t.format("%Y-%m-%dT%H:%M:%SZ").to_string()
    } else {
        format!("{}.{sub:06}Z", t.format("%Y-%m-%dT%H:%M:%S"))
    }
}

/// [t_start, t_end] 內每次近地點掠過（大地高局部極小），黃金分割精修至 ~1 s
pub fn perigee_passes(sat: &Sat, t_start: i64, t_end: i64, coarse_s: f64) -> Vec<Value> {
    let total = (t_end - t_start) as f64 / 1e6;
    let n = (total / coarse_s).floor() as i64;
    let step = td_us(coarse_s);
    let ts: Vec<i64> = (0..=n).map(|k| t_start + k * step).collect();
    let alts: Vec<Option<f64>> = ts.iter().map(|t| alt_at(sat, *t)).collect();
    let mut out = Vec::new();
    for i in 1..ts.len().saturating_sub(1) {
        let (Some(a0), Some(a1), Some(a2)) = (alts[i - 1], alts[i], alts[i + 1]) else { continue };
        if !(a1 < a0 && a1 <= a2) {
            continue;
        }
        let (mut lo, mut hi) = (ts[i - 1], ts[i + 1]);
        for _ in 0..40 {
            let d = (hi - lo) as f64 / 1e6;
            if d < 1.0 {
                break;
            }
            let m1 = lo + td_us(0.382 * d);
            let m2 = lo + td_us(0.618 * d);
            let (Some(f1), Some(f2)) = (alt_at(sat, m1), alt_at(sat, m2)) else { break };
            if f1 < f2 {
                hi = m2;
            } else {
                lo = m1;
            }
        }
        // timedelta / 2：微秒半數取偶
        let diff = hi - lo;
        let half = if diff % 2 == 0 {
            diff / 2
        } else {
            let h = diff.div_euclid(2);
            if h % 2 == 0 {
                h
            } else {
                h + 1
            }
        };
        let tp = lo + half;
        let t = tp as f64 / 1e6;
        let Some((r, v)) = sat.pv_unix(t) else { continue };
        let llh = eci_to_llh_py(&r, t);
        let dt = DateTime::<Utc>::from_timestamp_micros(tp).unwrap_or_default();
        let lst = (dt.hour() as f64 + dt.minute() as f64 / 60.0 + llh[1] / 15.0).rem_euclid(24.0);
        let speed = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        out.push(json!({
            "t": iso_z_secs(tp - tp.rem_euclid(1_000_000)),
            "alt_km": py_round(llh[2], 1), "lat": py_round(llh[0], 2), "lon": py_round(llh[1], 2),
            "speed_kms": py_round(speed, 2), "local_solar_time_h": py_round(lst, 1),
        }));
    }
    out
}

/// 由 TLE 外推 days 天：所有近地點掠過與首次 ≤ interface_km 之圈次
pub fn reentry_estimate(line1: &str, line2: &str, days: f64, interface_km: f64) -> Value {
    let yy: i32 = line1.get(18..20).and_then(|s| s.trim().parse().ok()).unwrap_or(0);
    let year = if yy < 57 { 2000 + yy } else { 1900 + yy };
    let doy: f64 = line1.get(20..32).and_then(|s| s.trim().parse().ok()).unwrap_or(1.0);
    let jan1 = Utc.with_ymd_and_hms(year, 1, 1, 0, 0, 0).single().unwrap_or_default();
    let ep_us = jan1.timestamp_micros() + td_us((doy - 1.0) * 86400.0);
    let t0 = ep_us;
    let passes = match Sat::from_tle(line1, line2) {
        Some(sat) => perigee_passes(&sat, t0, t0 + td_us(days * 86400.0), 60.0),
        None => Vec::new(),
    };
    let hit_i = passes.iter().position(|p| p["alt_km"].as_f64().is_some_and(|a| a <= interface_km));
    let hit = hit_i.map(|i| passes[i].clone()).unwrap_or(Value::Null);
    let prev = match hit_i {
        Some(i) if i > 0 => passes[i - 1].clone(),
        _ => Value::Null,
    };
    let a: f64 = line2.get(52..63).and_then(|s| s.trim().parse().ok()).unwrap_or(0.0);
    let period_h = (a > 0.0).then(|| (86400.0 / a) / 3600.0);
    json!({
        "tle_epoch": iso_z(ep_us), "tle_age_days_at_start": py_round(0.0, 1),
        "interface_km": interface_km, "period_h": period_h.map(|p| py_round(p, 2)),
        "lon_per_hour_deg": 15.0, "lon_per_rev_deg": period_h.map(|p| py_round(p.rem_euclid(24.0) * 15.0, 1)),
        "passes": passes, "reentry_pass": hit, "previous_pass": prev,
        "method": "SGP4/SDP4 外推之近地點掠過（大地高局部極小）；首次 ≤ interface_km 者為零階再入圈次；次衛星點為該時刻之 TLE 傳播位置，時間誤差 1 h ≈ 經度 15°",
    })
}
