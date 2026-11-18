//! 最小端到端案例（與 Python e2e.py 相同流程與報告欄位）。

use serde_json::{json, Value};

use super::constants::*;
use super::eop::{Eop, EopSource};
use super::forces::ForceModel;
use super::frames::{earth_rotation, teme_to_gcrf, EarthRotationTable};
use super::integrator::{propagate, Trajectory};
use super::la::{add, dot, mv, norm, sub};
use super::pc::{pc_chan, pc_foster, project};
use super::rtn::rtn_matrix;
use super::schema::validate;
use super::screening::screen;
use super::tca::find_minima;
use super::timescale::{seconds_between, UtcTime};
use super::{M3, V3};

pub const CODE_VERSION: &str = "phase2-sprint0";

fn v3(v: &Value) -> V3 {
    [v[0].as_f64().unwrap(), v[1].as_f64().unwrap(), v[2].as_f64().unwrap()]
}

/// TLE → TEME（SGP4，於 t 時刻）。常數組合與 python-sgp4 預設相同：WGS-72 重力常數、opsmode 'i'
/// （IAU 恆星時、精確 UTC→J2000 曆元）。注意 `Constants::from_elements` 預設為 WGS-84，與官方 SGP4 不同。
pub fn sgp4_teme(line1: &str, line2: &str, t: &UtcTime) -> anyhow::Result<(V3, V3)> {
    let el = sgp4::Elements::from_tle(None, line1.as_bytes(), line2.as_bytes())?;
    let d2r = std::f64::consts::PI / 180.0;
    let k = sgp4::Constants::new(
        sgp4::WGS72,
        sgp4::iau_epoch_to_sidereal_time,
        el.epoch(),
        el.drag_term,
        sgp4::Orbit::from_kozai_elements(
            &sgp4::WGS72,
            el.inclination * d2r,
            el.right_ascension * d2r,
            el.eccentricity,
            el.argument_of_perigee * d2r,
            el.mean_anomaly * d2r,
            el.mean_motion * (std::f64::consts::PI / 720.0),
        )?,
    )?;
    let ep = el.datetime;
    let ep_days = (ep.date() - chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap()).num_days();
    let ep_sec = chrono::Timelike::num_seconds_from_midnight(&ep.time()) as f64
        + chrono::Timelike::nanosecond(&ep.time()) as f64 * 1e-9;
    let ep_t = UtcTime { mjd: 40587 + ep_days, sec: ep_sec };
    let minutes = seconds_between(&ep_t, t) / 60.0;
    let p = k.propagate(sgp4::MinutesSinceEpoch(minutes))?;
    Ok((p.position, p.velocity))
}

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
    let (r, v) = sgp4_teme(eph["line1"].as_str().unwrap(), eph["line2"].as_str().unwrap(), start)?;
    let (rg, vg) = teme_to_gcrf(r, v, &earth_rotation(start, eop)?);
    Ok((rg, vg, 0.0))
}

fn demo_cov_gcrf(obj: &Value, r: V3, v: V3) -> Option<M3> {
    let cov = obj.get("covariance")?;
    if cov["mode"] != "demo" {
        return None;
    }
    let s = v3(&cov["sigma_km"]);
    let c = rtn_matrix(r, v);
    let mut out = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            out[i][j] = (0..3).map(|k| c[k][i] * s[k] * s[k] * c[k][j]).sum();
        }
    }
    Some(out)
}

pub fn run(sc: &Value, eop: &Eop) -> anyhow::Result<Value> {
    let val = validate(sc);
    if !val.ok {
        return Ok(json!({"status": "invalid_scenario", "validation": val.to_json()}));
    }
    let start = UtcTime::parse(sc["screening"]["start"].as_str().unwrap())?;
    let dur = sc["screening"]["duration_s"].as_f64().unwrap();
    let objs = sc["objects"].as_array().unwrap();
    let get = |role: &str| objs.iter().find(|o| o["role"] == role).unwrap();
    let (po, so) = (get("primary"), get("secondary"));
    let all_geo = objs.iter().all(|o| o.get("orbit_regime").and_then(Value::as_str) == Some("GEO"));
    let step = sc["screening"].get("step_s").and_then(Value::as_f64)
        .unwrap_or(if all_geo { RK4_STEP_GEO_S } else { RK4_STEP_LEO_S });
    let zonal = sc["force_model"]["zonal"].as_bool().unwrap();
    let drag = sc["force_model"]["drag"].as_bool().unwrap();

    let ip = initial_state_gcrf(po, &start, eop)?;
    let is = initial_state_gcrf(so, &start, eop)?;
    if ip.2 > 0.0 || is.2 > 0.0 {
        return Ok(json!({"status": "invalid_scenario", "validation": {"ok": false, "codes": ["E_STATE_EPOCH_AFTER_START"], "messages": []}}));
    }
    let t_lo = ip.2.min(is.2).min(0.0);
    let ert = if zonal || drag { Some(EarthRotationTable::new(start, t_lo, dur, eop)?) } else { None };
    let prop = |o: &Value, init: (V3, V3, f64)| -> Trajectory {
        let b = o.get("cd").and_then(Value::as_f64).unwrap_or(0.0) * o.get("area_to_mass_m2kg").and_then(Value::as_f64).unwrap_or(0.0);
        propagate(init.0, init.1, init.2, dur, step, &ForceModel::new(zonal, drag, b), ert.as_ref())
    };
    let (p, s) = (prop(po, ip), prop(so, is));
    let rel = |tau: f64| {
        let (rp, vp, ap) = p.state(tau);
        let (rs, vs, as_) = s.state(tau);
        (sub(rs, rp), sub(vs, vp), sub(as_, ap))
    };
    let thr = sc["screening"]["threshold_km"].as_f64().unwrap();
    let res = find_minima(&rel, 0.0, dur, step, Some(thr));
    let hbr_km = (po["hbr_m"].as_f64().unwrap() + so["hbr_m"].as_f64().unwrap()) / 1000.0;
    let other: Vec<f64> = res.all_minima.iter().map(|m| m.tau).collect();
    let c3_opt = |tau: f64| -> Option<M3> {
        let (rp, vp, _) = p.state(tau);
        let (rs, vs, _) = s.state(tau);
        let cp = demo_cov_gcrf(po, rp, vp)?;
        let cs = demo_cov_gcrf(so, rs, vs)?;
        let mut c = [[0.0; 3]; 3];
        for i in 0..3 {
            for j in 0..3 {
                c[i][j] = cp[i][j] + cs[i][j];
            }
        }
        Some(c)
    };
    let have_cov = c3_opt(0.0).is_some();
    let c3 = |tau: f64| c3_opt(tau).unwrap();
    let mut events = Vec::new();
    for ev in &res.events {
        let (rp, vp, _) = p.state(ev.tau);
        let a_semi = 1.0 / (2.0 / norm(rp) - dot(vp, vp) / GM_KM3_S2);
        let period = 2.0 * std::f64::consts::PI * (a_semi.powi(3) / GM_KM3_S2).sqrt();
        let c = rtn_matrix(rp, vp);
        let vs = add(vp, ev.v_rel);
        let cosang = (dot(vp, vs) / (norm(vp) * norm(vs))).clamp(-1.0, 1.0);
        let scr = screen(&rel, ev.tau, if have_cov { Some(&c3) } else { None }, "demo", hbr_km, period, &other, (0.0, dur));
        let mut out = json!({
            "tca_utc": start.plus(ev.tau).iso(), "tca_tau_s": ev.tau, "flag": ev.flag,
            "miss_km": ev.miss_km, "v_rel_kms": norm(ev.v_rel), "miss_rtn_km": mv(&c, ev.r_rel),
            "approach_angle_deg": cosang.acos().to_degrees(),
            "accuracy_note": "TCA 與距離為數值解（求根容差 1e-6 s）；預報準確度受輸入狀態與模型不確定性限制",
        });
        let passes = scr["status"] == "passes_initial_screen";
        out["applicability"] = scr;
        if have_cov {
            let (miss2, c2, _f) = project(ev.r_rel, ev.v_rel, &c3(ev.tau));
            out["bplane"] = json!({"miss_km": miss2, "cov_km2": c2});
            out["pc"] = json!({
                "foster": pc_foster(miss2, &c2, hbr_km)?, "chan": pc_chan(miss2, &c2, hbr_km)?,
                "hbr_km": hbr_km, "covariance_mode": "demo",
                "covariance_source": [po["covariance"]["source"].clone(), so["covariance"]["source"].clone()],
                "interpretation": if passes { "通過目前啟發式篩選；Pc 為展示模式假設下的值" } else { "未通過或無法判定適用性篩選；二維 Pc 僅供參考" },
            });
        }
        events.push(out);
    }
    let gmin = res.global_min().map(|g| json!({"tca_utc": start.plus(g.tau).iso(), "miss_km": g.miss_km, "flag": g.flag}));
    let mut search = res.resolution();
    search["n_minima"] = json!(res.all_minima.len());
    search["global_min"] = gmin.unwrap_or(Value::Null);
    Ok(json!({
        "status": "ok",
        "scenario_id": sc["id"],
        "provenance": {
            "code_version": CODE_VERSION, "constants_version": CONSTANTS_VERSION, "eop": eop.version(),
            "frames": {"sgp4_output": "TEME", "propagation": "GCRF", "precession_nutation": "IAU-2006/2000A CIO (xy06+s06), dX/dY applied"},
            "integrator": {"method": "RK4 fixed-step", "step_s": step, "interpolation": "quintic Hermite (r, v, a)"},
            "force_model": ForceModel::new(zonal, drag, 0.0).describe(),
            "engine": "rust",
        },
        "search": search,
        "events": events,
    }))
}
