//! 場景端到端（與 Python e2e.py Sprint 1 相同流程與報告欄位）：場景 JSON → 驗證 → 星曆（SGP4 或數值，GCRF）
//! → 自適應近接搜尋 → 協方差（展示或傳播模式）→ 適用性篩選 → Foster／Chan Pc → 報告 JSON。
//!
//! screening.propagator：auto（TLE 用 SGP4、狀態向量用數值積分；預設）、sgp4（全部 SGP4，僅限 TLE）、
//! numerical（全部數值積分；TLE 物件先以 SGP4 取 start 時刻狀態）。

use serde_json::{json, Map, Value};

use super::constants::*;
use super::covprop::{m6_from, CovarianceTrack};
use super::eop::{Eop, EopSource};
use super::ephemeris::{Ephemeris, NumericalEphemeris, RelativeState, Sgp4Ephemeris, Sgp4Sat};
use super::events::build_event;
use super::forces::ForceModel;
use super::frames::{earth_rotation, teme_to_gcrf, EarthRotationTable};
use super::integrator::propagate;
use super::la::norm;
use super::rtn::{cov_rtn_to_gcrf, rtn_matrix};
use super::schema::validate;
use super::tca::{find_minima_adaptive, AdaptiveParams};
use super::timescale::{seconds_between, UtcTime};
use super::{M3, V3};

pub const CODE_VERSION: &str = "phase2-sprint1";

fn v3(v: &Value) -> V3 {
    [v[0].as_f64().unwrap(), v[1].as_f64().unwrap(), v[2].as_f64().unwrap()]
}

/// TLE → TEME（SGP4，於 t 時刻）。常數組合與 python-sgp4 預設相同：WGS-72 重力常數、opsmode 'i'
/// （IAU 恆星時、精確 UTC→J2000 曆元）。注意 `Constants::from_elements` 預設為 WGS-84，與官方 SGP4 不同。
pub fn sgp4_teme(line1: &str, line2: &str, t: &UtcTime) -> anyhow::Result<(V3, V3)> {
    Sgp4Sat::from_tle(line1, line2)?.teme(t)
}

/// 回傳 (r, v, τ0)：GCRF 初始狀態與其相對 screening.start 的時刻。TLE 物件在 start 時刻以 SGP4 取狀態。
pub fn initial_state_gcrf(obj: &Value, start: &UtcTime, eop: &dyn EopSource) -> anyhow::Result<(V3, V3, f64)> {
    let eph = &obj["ephemeris"];
    if eph["type"] == "state" {
        let ep = UtcTime::parse(eph["epoch"].as_str().unwrap())?;
        let (mut r, mut v) = (v3(&eph["r_km"]), v3(&eph["v_kms"]));
        if eph["frame"] == "TEME" {
            (r, v) = teme_to_gcrf(r, v, &earth_rotation(&ep, eop)?);
        }
        return Ok((r, v, seconds_between(start, &ep)));
    }
    let (r, v) = sgp4_teme(eph["line1"].as_str().unwrap(), eph["line2"].as_str().unwrap(), start)
        .map_err(|e| anyhow::anyhow!("SGP4 錯誤（{}）：{e}", obj["name"].as_str().unwrap_or("?")))?;
    let (rg, vg) = teme_to_gcrf(r, v, &earth_rotation(start, eop)?);
    Ok((rg, vg, 0.0))
}

/// Python repr(float)：最短可還原表示；指數 < −4 或 ≥ 16 時用科學記號
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let e = format!("{x:e}"); // 例："2.2e-2"、"-1e5"
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    if !(-4..16).contains(&exp) {
        return format!("{mant}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    let s = format!("{x}");
    if s.contains('.') { s } else { format!("{s}.0") }
}

/// Python f"{x:g}"（6 位有效數字）
pub fn py_g(x: f64) -> String {
    if x.is_finite() && x.fract() == 0.0 && x.abs() < 1e6 {
        return format!("{}", x as i64);
    }
    let e = format!("{:.5e}", x);
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let trim = |s: String| -> String {
        if s.contains('.') { s.trim_end_matches('0').trim_end_matches('.').to_string() } else { s }
    };
    if (-4..6).contains(&exp) {
        let prec = (5 - exp).max(0) as usize;
        trim(format!("{x:.prec$}"))
    } else {
        format!("{}e{}{:02}", trim(mant.to_string()), if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// ForceModel.describe() 的 Python dict repr（provenance 字串與 Python 版逐字相同）
fn fm_repr(fm: &ForceModel) -> String {
    let zonal = if fm.zonal { "'J2-J4'".to_string() } else { "None".to_string() };
    let drag = if fm.drag {
        format!("{{'model': 'ExponentialAtmosphere', 'ballistic_m2_kg': {}}}", py_float_repr(fm.ballistic_m2_kg))
    } else {
        "None".into()
    };
    format!("{{'two_body': True, 'zonal': {zonal}, 'drag': {drag}}}")
}

/// 單一物體的協方差模型
enum ObjCov<'a> {
    None,
    Demo { eph: &'a dyn Ephemeris, s2: [f64; 3] },
    Prop(CovarianceTrack<'a>),
}

impl ObjCov<'_> {
    fn at(&self, tau: f64) -> M3 {
        match self {
            ObjCov::None => [[f64::NAN; 3]; 3],
            ObjCov::Demo { eph, s2 } => {
                let (r, v) = eph.rv(tau);
                let c = rtn_matrix(r, v);
                let mut out = [[0.0; 3]; 3];
                for i in 0..3 {
                    for j in 0..3 {
                        out[i][j] = (0..3).map(|k| c[k][i] * s2[k] * c[k][j]).sum();
                    }
                }
                out
            }
            ObjCov::Prop(t) => t.pos_at(tau),
        }
    }
    fn mode(&self) -> Option<&'static str> {
        match self {
            ObjCov::None => None,
            ObjCov::Demo { .. } => Some("demo"),
            ObjCov::Prop(_) => Some("propagated"),
        }
    }
}

fn object_covariance<'a>(
    obj: &Value,
    eph: &'a dyn Ephemeris,
    t0: f64,
    dur: f64,
    ert: &'a EarthRotationTable,
    zonal: bool,
    geo: bool,
) -> anyhow::Result<(ObjCov<'a>, Value, Value)> {
    let Some(cov) = obj.get("covariance").filter(|c| c.as_object().map(|m| !m.is_empty()).unwrap_or(false)) else {
        return Ok((ObjCov::None, Value::Null, Value::Null));
    };
    if cov["mode"] == "demo" {
        let s = v3(&cov["sigma_km"]);
        return Ok((ObjCov::Demo { eph, s2: [s[0] * s[0], s[1] * s[1], s[2] * s[2]] }, cov["source"].clone(),
            json!({"method": "demo", "sigma_km": cov["sigma_km"]})));
    }
    let p: Vec<Vec<f64>> = cov["matrix_6x6"].as_array().unwrap().iter()
        .map(|r| r.as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect()).collect();
    let (r0, v0) = eph.rv(t0);
    let p = if cov["frame"] == "RTN" {
        cov_rtn_to_gcrf(&p, r0, v0, cov["velocity_convention"].as_str().unwrap_or(""))?
    } else {
        p
    };
    let q = cov.get("propagation").and_then(|x| x.get("process_noise")).and_then(|x| x.get("q_km2_s3"))
        .and_then(Value::as_f64).unwrap_or(0.0);
    let step = if geo { COV_STEP_GEO_S } else { COV_STEP_LEO_S };
    let track = CovarianceTrack::new(eph, m6_from(&p), t0, dur, step, Some(ert), zonal, q);
    let desc = track.describe();
    Ok((ObjCov::Prop(track), cov["source"].clone(), desc))
}

pub fn run(sc: &Value, eop: &Eop) -> anyhow::Result<Value> {
    let val = validate(sc);
    if !val.ok {
        return Ok(json!({"status": "invalid_scenario", "validation": val.to_json()}));
    }
    let scr = &sc["screening"];
    let start = UtcTime::parse(scr["start"].as_str().unwrap())?;
    let dur = scr["duration_s"].as_f64().unwrap();
    let objs_list = sc["objects"].as_array().unwrap();
    // Python dict {role: obj}：依出現順序，同角色後者覆蓋前者
    let mut roles: Vec<(String, &Value)> = Vec::new();
    for o in objs_list {
        let role = o["role"].as_str().unwrap().to_string();
        if let Some(slot) = roles.iter_mut().find(|(r, _)| *r == role) {
            slot.1 = o;
        } else {
            roles.push((role, o));
        }
    }
    let get = |role: &str| roles.iter().find(|(r, _)| r == role).map(|(_, o)| *o).unwrap();
    let geo = objs_list.iter().all(|o| o.get("orbit_regime").and_then(Value::as_str).unwrap_or("LEO") == "GEO");
    let fnum = |k: &str| scr.get(k).and_then(Value::as_f64).filter(|x| *x != 0.0);
    let step = fnum("step_s").unwrap_or(if geo { RK4_STEP_GEO_S } else { RK4_STEP_LEO_S });
    let coarse = fnum("coarse_step_s").unwrap_or(SEARCH_COARSE_STEP_S);
    let min_step = fnum("min_step_s").unwrap_or(SEARCH_MIN_STEP_S);
    let mode = scr.get("propagator").and_then(Value::as_str).unwrap_or("auto").to_string();
    let zonal = sc["force_model"]["zonal"].as_bool().unwrap();
    let drag = sc["force_model"]["drag"].as_bool().unwrap();

    let mut t_lo: f64 = 0.0;
    for o in objs_list {
        if o["ephemeris"]["type"] == "state" {
            let dt = seconds_between(&start, &UtcTime::parse(o["ephemeris"]["epoch"].as_str().unwrap())?);
            t_lo = t_lo.min(dt);
            if dt > 0.0 {
                return Ok(json!({"status": "invalid_scenario",
                    "validation": {"ok": false, "codes": ["E_STATE_EPOCH_AFTER_START"], "messages": []}}));
            }
        }
    }
    let ert = EarthRotationTable::new(start, t_lo - 1.0, dur + 1.0, eop)?;

    let mut ephs: Vec<Box<dyn Ephemeris + '_>> = Vec::new();
    let mut t0s: Vec<f64> = Vec::new();
    let mut prov_eph = Map::new();
    for (role, o) in &roles {
        let use_sgp4 = o["ephemeris"]["type"] == "TLE" && (mode == "auto" || mode == "sgp4");
        if use_sgp4 {
            let e = Sgp4Ephemeris::new(o["ephemeris"]["line1"].as_str().unwrap(), o["ephemeris"]["line2"].as_str().unwrap(),
                start, &ert, (0.0, dur))?;
            ephs.push(Box::new(e));
            prov_eph.insert(role.clone(), json!("SGP4 (WGS-72, opsmode i) → GCRF"));
            t0s.push(0.0);
        } else {
            let (r0, v0, t0) = initial_state_gcrf(o, &start, eop)?;
            let b = o.get("cd").and_then(Value::as_f64).unwrap_or(0.0) * o.get("area_to_mass_m2kg").and_then(Value::as_f64).unwrap_or(0.0);
            let fm = ForceModel::new(zonal, drag, b);
            ephs.push(Box::new(NumericalEphemeris::new(propagate(r0, v0, t0, dur, step, &fm, Some(&ert)))));
            prov_eph.insert(role.clone(), json!(format!("numerical RK4 {} s, {}", py_g(step), fm_repr(&fm))));
            t0s.push(t0);
        }
    }
    let mut covs: Vec<(ObjCov, Value, Value)> = Vec::new();
    for (i, (_, o)) in roles.iter().enumerate() {
        covs.push(object_covariance(o, ephs[i].as_ref(), t0s[i], dur, &ert, zonal, geo)?);
    }
    let idx = |role: &str| roles.iter().position(|(r, _)| r == role).unwrap();
    let (ip, is) = (idx("primary"), idx("secondary"));
    let (eph_p, eph_s) = (ephs[ip].as_ref(), ephs[is].as_ref());
    let rel = RelativeState::new(eph_p, eph_s);
    let thr = scr["threshold_km"].as_f64().unwrap();
    let res = find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), 0.0, dur,
        AdaptiveParams { coarse_step: coarse, threshold_km: Some(thr), min_step, ..Default::default() });
    let hbr_km = (get("primary")["hbr_m"].as_f64().unwrap() + get("secondary")["hbr_m"].as_f64().unwrap()) / 1000.0;
    let others: Vec<f64> = res.all_minima.iter().map(|m| m.tau).collect();
    let (cp, cs) = (&covs[ip], &covs[is]);
    let have_cov = cp.0.mode().is_some() && cs.0.mode().is_some();
    let cov_mode: Option<&str> = if have_cov {
        let m = if cp.0.mode() == Some("propagated") || cs.0.mode() == Some("propagated") { "propagated" } else { "demo" };
        Some(if cp.0.mode() != cs.0.mode() { "mixed" } else { m })
    } else {
        None
    };
    let c3 = |tau: f64| -> M3 {
        let (a, b) = (cp.0.at(tau), cs.0.at(tau));
        let mut c = [[0.0; 3]; 3];
        for i in 0..3 {
            for j in 0..3 {
                c[i][j] = a[i][j] + b[i][j];
            }
        }
        c
    };
    let screen_mode = if matches!(cov_mode, Some("propagated") | Some("mixed")) { "propagated" } else { "demo" };
    let mut events = Vec::new();
    for ap in &res.events {
        let mut e = build_event(&start, ap, &|t| rel.rva(t), eph_p, if have_cov { Some(&c3) } else { None }, screen_mode,
            hbr_km, &others, (0.0, dur), if have_cov { Some(json!([cp.1, cs.1])) } else { None });
        if e.get("pc").is_some() {
            e["pc"]["covariance_mode"] = json!(cov_mode);
        }
        events.push(e);
    }
    let gmin = res.global_min().map(|g| json!({"tca_utc": start.plus(g.tau).iso(), "miss_km": g.miss_km, "flag": g.flag}));
    let n_search_evals = rel.n_evals.get();
    let n_series = 600.0f64.min(2.0f64.max(dur / coarse + 1.0)) as usize;
    let s_step = dur / (n_series - 1) as f64;
    let d_km: Vec<f64> = (0..n_series).map(|i| norm(rel.rv(i as f64 * s_step).0)).collect();
    if let Some(e) = rel.take_error() {
        anyhow::bail!(e);
    }
    let mut objects = Map::new();
    for (role, o) in &roles {
        objects.insert(role.clone(), json!({"name": o["name"], "norad_id": o.get("norad_id").cloned().unwrap_or(Value::Null)}));
    }
    let mut search = res.resolution();
    search["n_minima"] = json!(res.all_minima.len());
    search["n_evals"] = json!(n_search_evals);
    search["global_min"] = gmin.unwrap_or(Value::Null);
    Ok(json!({
        "status": "ok",
        "scenario_id": sc["id"],
        "start": start.iso(), "duration_s": dur, "threshold_km": thr,
        "objects": objects,
        "series": {"step_s": s_step, "d_km": d_km},
        "provenance": {
            "code_version": CODE_VERSION, "constants_version": CONSTANTS_VERSION, "eop": eop.version(),
            "frames": {"sgp4_output": "TEME", "propagation": "GCRF", "precession_nutation": "IAU-2006/2000A CIO (xy06+s06), dX/dY applied"},
            "propagator_mode": mode, "ephemeris": prov_eph,
            "covariance": {"primary": cp.2, "secondary": cs.2},
        },
        "search": search,
        "events": events,
    }))
}
