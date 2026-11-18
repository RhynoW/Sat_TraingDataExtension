//! 場景驗證：結構（手寫，對應 scenario_v1.schema.json）＋語意檢查（錯誤代碼與 Python schema.py 相同）。
//! 結構錯誤一律回 E_SCHEMA（訊息內容不列入跨語言比對）；語意代碼以排序後集合比對。

use std::collections::BTreeSet;

use serde_json::{Map, Value};

use super::la::is_pd;
use super::timescale::{seconds_between, UtcTime};

struct Ctx {
    errs: Vec<String>,
}

impl Ctx {
    fn err(&mut self, path: &str, msg: &str) {
        self.errs.push(format!("{path}: {msg}"));
    }
}

fn obj<'a>(c: &mut Ctx, v: &'a Value, path: &str, required: &[&str], allowed: &[&str]) -> Option<&'a Map<String, Value>> {
    let Some(m) = v.as_object() else {
        c.err(path, "須為物件");
        return None;
    };
    for r in required {
        if !m.contains_key(*r) {
            c.err(path, &format!("缺欄位 {r}"));
        }
    }
    for k in m.keys() {
        if !allowed.contains(&k.as_str()) {
            c.err(path, &format!("不允許的欄位 {k}"));
        }
    }
    Some(m)
}

fn is_num(v: &Value) -> bool {
    v.is_number()
}
fn num(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, lo: Option<(f64, bool)>, hi: Option<f64>) {
    if let Some(v) = m.get(k) {
        match v.as_f64() {
            Some(x) if v.is_number() => {
                if let Some((l, excl)) = lo {
                    if (excl && !(x > l)) || (!excl && !(x >= l)) {
                        c.err(&format!("{path}/{k}"), "超出下限");
                    }
                }
                if let Some(h) = hi {
                    if x > h {
                        c.err(&format!("{path}/{k}"), "超出上限");
                    }
                }
            }
            _ => c.err(&format!("{path}/{k}"), "須為數值"),
        }
    }
}
fn int(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, lo: i64) {
    if let Some(v) = m.get(k) {
        let ok = v.as_i64().map(|x| x >= lo).unwrap_or(false)
            || v.as_f64().map(|x| x.fract() == 0.0 && x >= lo as f64).unwrap_or(false);
        if !ok {
            c.err(&format!("{path}/{k}"), "須為整數且不小於下限");
        }
    }
}
fn string(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, min_len: usize) {
    if let Some(v) = m.get(k) {
        match v.as_str() {
            Some(s) if s.chars().count() >= min_len => {}
            _ => c.err(&format!("{path}/{k}"), "須為字串"),
        }
    }
}
fn boolean(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str) {
    if let Some(v) = m.get(k) {
        if !v.is_boolean() {
            c.err(&format!("{path}/{k}"), "須為布林值");
        }
    }
}
fn konst(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, val: &str) {
    if let Some(v) = m.get(k) {
        if v.as_str() != Some(val) {
            c.err(&format!("{path}/{k}"), &format!("須為 {val}"));
        }
    }
}
fn enumv(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, vals: &[&str]) {
    if let Some(v) = m.get(k) {
        if !v.as_str().map(|s| vals.contains(&s)).unwrap_or(false) {
            c.err(&format!("{path}/{k}"), "不在列舉值內");
        }
    }
}
fn num_array(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str, len: usize, nonneg: bool) {
    if let Some(v) = m.get(k) {
        let ok = v.as_array().map(|a| a.len() == len && a.iter().all(|x| is_num(x) && (!nonneg || x.as_f64().unwrap() >= 0.0))).unwrap_or(false);
        if !ok {
            c.err(&format!("{path}/{k}"), &format!("須為 {len} 個數值的陣列"));
        }
    }
}
fn is_obj(c: &mut Ctx, m: &Map<String, Value>, k: &str, path: &str) {
    if let Some(v) = m.get(k) {
        if !v.is_object() {
            c.err(&format!("{path}/{k}"), "須為物件");
        }
    }
}

fn check_covariance(c: &mut Ctx, v: &Value, path: &str) {
    let Some(m) = obj(c, v, path, &["mode", "source", "independent_of_other"],
        &["mode", "epoch", "frame", "rtn_definition", "velocity_convention", "units", "sigma_km", "matrix_6x6",
          "source", "independent_of_other", "propagation", "maneuver_execution_error"]) else { return };
    enumv(c, m, "mode", path, &["demo", "propagated"]);
    string(c, m, "epoch", path, 0);
    enumv(c, m, "frame", path, &["RTN", "GCRF"]);
    string(c, m, "rtn_definition", path, 0);
    enumv(c, m, "velocity_convention", path, &["inertial_velocity_components", "rotating_frame_derivative"]);
    if let Some(u) = m.get("units") {
        if let Some(um) = obj(c, u, &format!("{path}/units"), &[], &["pos", "vel", "cross"]) {
            konst(c, um, "pos", &format!("{path}/units"), "km");
            konst(c, um, "vel", &format!("{path}/units"), "km/s");
            konst(c, um, "cross", &format!("{path}/units"), "km^2/s");
        }
    }
    num_array(c, m, "sigma_km", path, 3, false);
    if let Some(mx) = m.get("matrix_6x6") {
        let ok = mx.as_array().map(|rows| rows.len() == 6 && rows.iter().all(|r|
            r.as_array().map(|a| a.len() == 6 && a.iter().all(is_num)).unwrap_or(false))).unwrap_or(false);
        if !ok {
            c.err(&format!("{path}/matrix_6x6"), "須為 6×6 數值矩陣");
        }
    }
    enumv(c, m, "source", path, &["assumed", "cdm", "od"]);
    boolean(c, m, "independent_of_other", path);
    is_obj(c, m, "propagation", path);
    is_obj(c, m, "maneuver_execution_error", path);
}

fn check_structure(sc: &Value) -> Vec<String> {
    let mut c = Ctx { errs: vec![] };
    let Some(top) = obj(&mut c, sc, "", &["schema", "id", "time", "frames", "objects", "screening", "force_model"],
        &["schema", "id", "description", "time", "frames", "analysis_time", "objects", "screening", "force_model",
          "conjunction", "maneuver_search", "rpo_limits", "monte_carlo"]) else { return c.errs };
    konst(&mut c, top, "schema", "", "satdash.scenario/v1");
    if let Some(id) = top.get("id") {
        let ok = id.as_str().map(|s| !s.is_empty() && s.len() <= 64
            && s.chars().all(|ch| ch.is_ascii_alphanumeric() || "_.-".contains(ch))).unwrap_or(false);
        if !ok {
            c.err("/id", "格式不符");
        }
    }
    string(&mut c, top, "description", "", 0);
    string(&mut c, top, "analysis_time", "", 0);
    if let Some(t) = top.get("time") {
        if let Some(m) = obj(&mut c, t, "/time", &["system"],
            &["system", "eop_source", "eop_version", "leap_seconds_version", "space_weather_version"]) {
            konst(&mut c, m, "system", "/time", "UTC");
            for k in ["eop_source", "eop_version", "leap_seconds_version", "space_weather_version"] {
                string(&mut c, m, k, "/time", 0);
            }
        }
    }
    if let Some(f) = top.get("frames") {
        if let Some(m) = obj(&mut c, f, "/frames", &["propagation"], &["sgp4_output", "propagation"]) {
            konst(&mut c, m, "sgp4_output", "/frames", "TEME");
            konst(&mut c, m, "propagation", "/frames", "GCRF");
        }
    }
    if let Some(objs) = top.get("objects") {
        match objs.as_array() {
            Some(a) if a.len() == 2 => {
                for (i, o) in a.iter().enumerate() {
                    let p = format!("/objects/{i}");
                    let Some(m) = obj(&mut c, o, &p, &["role", "name", "ephemeris", "hbr_m"],
                        &["role", "name", "norad_id", "orbit_regime", "ephemeris", "covariance", "hbr_m", "mass_kg",
                          "area_to_mass_m2kg", "cd", "cr", "propulsion"]) else { continue };
                    enumv(&mut c, m, "role", &p, &["primary", "secondary"]);
                    string(&mut c, m, "name", &p, 1);
                    int(&mut c, m, "norad_id", &p, 0);
                    enumv(&mut c, m, "orbit_regime", &p, &["LEO", "MEO", "GEO", "HEO"]);
                    if let Some(e) = m.get("ephemeris") {
                        let pe = format!("{p}/ephemeris");
                        match e.get("type").and_then(Value::as_str) {
                            Some("TLE") => {
                                if let Some(em) = obj(&mut c, e, &pe, &["type", "line1", "line2"], &["type", "line1", "line2", "source", "retrieved"]) {
                                    for k in ["line1", "line2"] {
                                        if em.get(k).and_then(Value::as_str).map(|s| s.chars().count() != 69).unwrap_or(false) {
                                            c.err(&format!("{pe}/{k}"), "TLE 行長須為 69");
                                        }
                                        string(&mut c, em, k, &pe, 0);
                                    }
                                    string(&mut c, em, "source", &pe, 0);
                                    string(&mut c, em, "retrieved", &pe, 0);
                                }
                            }
                            Some("state") => {
                                if let Some(em) = obj(&mut c, e, &pe, &["type", "epoch", "frame", "r_km", "v_kms"], &["type", "epoch", "frame", "r_km", "v_kms", "source"]) {
                                    string(&mut c, em, "epoch", &pe, 0);
                                    enumv(&mut c, em, "frame", &pe, &["GCRF", "TEME"]);
                                    num_array(&mut c, em, "r_km", &pe, 3, false);
                                    num_array(&mut c, em, "v_kms", &pe, 3, false);
                                    string(&mut c, em, "source", &pe, 0);
                                }
                            }
                            _ => c.err(&pe, "type 須為 TLE 或 state"),
                        }
                    }
                    if let Some(cv) = m.get("covariance") {
                        check_covariance(&mut c, cv, &format!("{p}/covariance"));
                    }
                    num(&mut c, m, "hbr_m", &p, Some((0.0, true)), None);
                    num(&mut c, m, "mass_kg", &p, Some((0.0, true)), None);
                    num(&mut c, m, "area_to_mass_m2kg", &p, Some((0.0, false)), None);
                    num(&mut c, m, "cd", &p, Some((0.0, false)), None);
                    num(&mut c, m, "cr", &p, Some((0.0, false)), None);
                    if let Some(pr) = m.get("propulsion") {
                        let pp = format!("{p}/propulsion");
                        if let Some(pm) = obj(&mut c, pr, &pp, &[], &["isp_s", "dv_budget_ms", "min_notice_s", "thrust_dirs"]) {
                            num(&mut c, pm, "isp_s", &pp, Some((0.0, true)), None);
                            num(&mut c, pm, "dv_budget_ms", &pp, Some((0.0, false)), None);
                            num(&mut c, pm, "min_notice_s", &pp, Some((0.0, false)), None);
                            if let Some(td) = pm.get("thrust_dirs") {
                                let ok = td.as_array().map(|a| a.iter().all(|x| x.as_str().map(|s|
                                    ["R", "T", "N", "-R", "-T", "-N"].contains(&s)).unwrap_or(false))).unwrap_or(false);
                                if !ok {
                                    c.err(&format!("{pp}/thrust_dirs"), "推力方向不在列舉值內");
                                }
                            }
                        }
                    }
                }
            }
            _ => c.err("/objects", "須為 2 個物體的陣列"),
        }
    }
    if let Some(s) = top.get("screening") {
        if let Some(m) = obj(&mut c, s, "/screening", &["start", "duration_s", "threshold_km"], &["start", "duration_s", "step_s", "threshold_km", "propagator", "coarse_step_s", "min_step_s"]) {
            string(&mut c, m, "start", "/screening", 0);
            num(&mut c, m, "duration_s", "/screening", Some((0.0, true)), Some(2592000.0));
            num(&mut c, m, "step_s", "/screening", Some((0.0, true)), Some(600.0));
            num(&mut c, m, "threshold_km", "/screening", Some((0.0, true)), None);
            enumv(&mut c, m, "propagator", "/screening", &["auto", "sgp4", "numerical"]);
            num(&mut c, m, "coarse_step_s", "/screening", Some((0.0, true)), Some(3600.0));
            num(&mut c, m, "min_step_s", "/screening", Some((0.0, true)), Some(60.0));
        }
    }
    if let Some(f) = top.get("force_model") {
        if let Some(m) = obj(&mut c, f, "/force_model", &["zonal", "drag"], &["zonal", "drag", "density_model"]) {
            boolean(&mut c, m, "zonal", "/force_model");
            boolean(&mut c, m, "drag", "/force_model");
            enumv(&mut c, m, "density_model", "/force_model", &["exponential", "nrlmsise00"]);
        }
    }
    if let Some(cj) = top.get("conjunction") {
        if let Some(m) = obj(&mut c, cj, "/conjunction", &[], &["tca", "miss_km", "source"]) {
            string(&mut c, m, "tca", "/conjunction", 0);
            num(&mut c, m, "miss_km", "/conjunction", Some((0.0, false)), None);
            string(&mut c, m, "source", "/conjunction", 0);
        }
    }
    if let Some(ms) = top.get("maneuver_search") {
        let p = "/maneuver_search";
        if let Some(m) = obj(&mut c, ms, p, &["window_rel_tca_s"],
            &["window_rel_tca_s", "dv_ms", "pc_target", "min_miss_km", "feasibility_check", "secondary_screening"]) {
            num_array(&mut c, m, "window_rel_tca_s", p, 2, false);
            num_array(&mut c, m, "dv_ms", p, 2, true);
            num(&mut c, m, "pc_target", p, Some((0.0, true)), Some(1.0));
            num(&mut c, m, "min_miss_km", p, Some((0.0, false)), None);
            boolean(&mut c, m, "feasibility_check", p);
            if let Some(ss) = m.get("secondary_screening") {
                if let Some(sm) = obj(&mut c, ss, &format!("{p}/secondary_screening"), &[], &["catalog", "window_days"]) {
                    enumv(&mut c, sm, "catalog", p, &["active", "full"]);
                    num(&mut c, sm, "window_days", p, Some((0.0, true)), None);
                }
            }
        }
    }
    is_obj(&mut c, top, "rpo_limits", "");
    if let Some(mc) = top.get("monte_carlo") {
        if let Some(m) = obj(&mut c, mc, "/monte_carlo", &[], &["n", "rng", "seed", "samples_file"]) {
            int(&mut c, m, "n", "/monte_carlo", 1);
            enumv(&mut c, m, "rng", "/monte_carlo", &["pcg64"]);
            int(&mut c, m, "seed", "/monte_carlo", 0);
            if let Some(v) = m.get("samples_file") {
                if !(v.is_null() || v.is_string()) {
                    c.err("/monte_carlo/samples_file", "須為字串或 null");
                }
            }
        }
    }
    c.errs
}

pub struct Validation {
    pub ok: bool,
    pub codes: Vec<String>,
    pub messages: Vec<String>,
}

impl Validation {
    pub fn to_json(&self) -> Value {
        serde_json::json!({"ok": self.ok, "codes": self.codes, "messages": self.messages})
    }
}

fn done(codes: BTreeSet<&str>, messages: Vec<String>) -> Validation {
    Validation { ok: codes.is_empty(), codes: codes.into_iter().map(String::from).collect(), messages }
}

pub fn validate(sc: &Value) -> Validation {
    let errs = check_structure(sc);
    let mut codes: BTreeSet<&str> = BTreeSet::new();
    let mut msgs = Vec::new();
    if !errs.is_empty() {
        codes.insert("E_SCHEMA");
        return done(codes, errs.into_iter().take(20).collect());
    }
    let s = |v: &Value| v.as_str().unwrap_or("").to_string();
    let mut times = vec![s(&sc["screening"]["start"])];
    if let Some(a) = sc.get("analysis_time") {
        times.push(s(a));
    }
    if let Some(t) = sc.get("conjunction").and_then(|c| c.get("tca")) {
        times.push(s(t));
    }
    let objs = sc["objects"].as_array().unwrap();
    for o in objs {
        if o["ephemeris"]["type"] == "state" {
            times.push(s(&o["ephemeris"]["epoch"]));
        }
        if let Some(e) = o.get("covariance").and_then(|c| c.get("epoch")) {
            times.push(s(e));
        }
    }
    for t in &times {
        if UtcTime::parse(t).is_err() {
            codes.insert("E_TIME_PARSE");
            msgs.push(format!("無法解析時刻：{t}"));
        }
    }
    if codes.contains("E_TIME_PARSE") {
        return done(codes, msgs);
    }
    if objs[0]["role"] == objs[1]["role"] {
        codes.insert("E_ROLE_DUPLICATE");
    }
    let scr = &sc["screening"];
    if scr.get("propagator").and_then(Value::as_str) == Some("sgp4") && objs.iter().any(|o| o["ephemeris"]["type"] != "TLE") {
        codes.insert("E_PROPAGATOR_SGP4_NEEDS_TLE");
    }
    if let Some(ms) = scr.get("min_step_s").and_then(Value::as_f64) {
        if ms > scr.get("coarse_step_s").and_then(Value::as_f64).unwrap_or(60.0) {
            codes.insert("E_MIN_STEP_GT_COARSE");
        }
    }
    for o in objs {
        let Some(cov) = o.get("covariance") else { continue };
        if cov.get("mode").and_then(Value::as_str) == Some("propagated") {
            if let Some(ep) = cov.get("epoch").and_then(Value::as_str) {
                let rf = if o["ephemeris"]["type"] == "state" { s(&o["ephemeris"]["epoch"]) } else { s(&scr["start"]) };
                let dt = seconds_between(&UtcTime::parse(&rf).unwrap(), &UtcTime::parse(ep).unwrap());
                if dt.abs() > 1e-6 {
                    codes.insert("E_COV_EPOCH_MISMATCH");
                }
            }
        }
    }
    let drag = sc["force_model"]["drag"].as_bool().unwrap_or(false);
    for o in objs {
        if drag && (o.get("area_to_mass_m2kg").is_none() || o.get("cd").is_none()) {
            codes.insert("E_DRAG_PARAMS_MISSING");
        }
        let Some(cov) = o.get("covariance") else { continue };
        if !cov["independent_of_other"].as_bool().unwrap_or(true) {
            codes.insert("E_COV_DEPENDENCE_UNSUPPORTED");
        }
        if cov["mode"] == "demo" {
            match cov.get("sigma_km").and_then(Value::as_array) {
                None => {
                    codes.insert("E_COV_SIGMA_MISSING");
                }
                Some(a) => {
                    if a.iter().any(|x| !(x.as_f64().unwrap_or(0.0) > 0.0)) {
                        codes.insert("E_COV_SIGMA_NONPOSITIVE");
                    }
                }
            }
            continue;
        }
        if cov.get("epoch").is_none() {
            codes.insert("E_COV_EPOCH_MISSING");
        }
        if cov.get("frame").is_none() {
            codes.insert("E_COV_FRAME_MISSING");
        }
        let u = cov.get("units").and_then(Value::as_object);
        if !u.map(|u| ["pos", "vel", "cross"].iter().all(|k| u.contains_key(*k))).unwrap_or(false) {
            codes.insert("E_COV_UNITS_MISSING");
        }
        let Some(mx) = cov.get("matrix_6x6").and_then(Value::as_array) else {
            codes.insert("E_COV_MATRIX_MISSING");
            continue;
        };
        if cov.get("frame").and_then(Value::as_str) == Some("RTN") && cov.get("velocity_convention").is_none() {
            codes.insert("E_COV_VELOCITY_CONVENTION_MISSING");
        }
        let p: Vec<Vec<f64>> = mx.iter().map(|r| r.as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect()).collect();
        let scale = p.iter().flatten().fold(0.0f64, |m, x| m.max(x.abs()));
        let scale = if scale == 0.0 { 1.0 } else { scale };
        let asym = (0..6).flat_map(|i| (0..6).map(move |j| (i, j))).fold(0.0f64, |m, (i, j)| m.max((p[i][j] - p[j][i]).abs()));
        if asym > 1e-12 * scale {
            codes.insert("E_COV_NOT_SYMMETRIC");
        } else if !is_pd(&p) {
            codes.insert("E_COV_NOT_POSITIVE_DEFINITE");
        }
    }
    if let Some(ms) = sc.get("maneuver_search") {
        let w = ms["window_rel_tca_s"].as_array().unwrap();
        let (a, b) = (w[0].as_f64().unwrap(), w[1].as_f64().unwrap());
        if !(a < b && b <= 0.0) {
            codes.insert("E_WINDOW_ORDER");
        }
        if let Some(dv) = ms.get("dv_ms").and_then(Value::as_array) {
            if dv[0].as_f64().unwrap() > dv[1].as_f64().unwrap() {
                codes.insert("E_DV_RANGE_ORDER");
            }
        }
        let tca = sc.get("conjunction").and_then(|c| c.get("tca")).and_then(Value::as_str);
        let at = sc.get("analysis_time").and_then(Value::as_str);
        let notice = objs.iter().find(|o| o["role"] == "primary")
            .and_then(|o| o.get("propulsion")).and_then(|p| p.get("min_notice_s")).and_then(Value::as_f64);
        if let (Some(tca), Some(at), Some(notice)) = (tca, at, notice) {
            if !codes.contains("E_WINDOW_ORDER") {
                let dt = seconds_between(&UtcTime::parse(at).unwrap(), &UtcTime::parse(tca).unwrap());
                if dt + b < notice {
                    codes.insert("E_NOTICE_WINDOW_CONFLICT");
                    msgs.push("最短通知時間與機動窗衝突：沒有合法的機動時刻（infeasible_constraints）".into());
                }
            }
        }
    }
    done(codes, msgs)
}
