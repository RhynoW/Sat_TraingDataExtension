//! 批次會合分析（與 Python batch.py 相同輸出）：一顆主星對多顆次星，SGP4 星曆（GCRF）＋自適應近接搜尋＋展示模式 Pc。
//!
//! 輸入（JSON）：primary {norad_id | line1+line2, name?, hbr_m?, sigma_km?[3]}、secondaries（csvio rows）、
//! start、duration_s ≤ 604800、threshold_km、coarse_step_s?、defaults?。
//! tle_lookup(norad_id) → (name, line1, line2)。

use std::time::Instant;

use serde_json::{json, Map, Value};

use super::constants::*;
use super::eop::Eop;
use super::ephemeris::{Ephemeris, Memo, RelativeState, Sgp4Ephemeris};
use super::events::build_event;
use super::frames::EarthRotationTable;
use super::la::norm;
use super::rtn::rtn_matrix;
use super::tca::{find_minima_adaptive, AdaptiveParams};
use super::timescale::UtcTime;
use super::M3;

pub const MAX_DURATION_S: f64 = 7.0 * 86400.0;
pub const SERIES_MAX_POINTS: f64 = 600.0;

pub type TleLookup<'a> = &'a dyn Fn(i64) -> Option<(String, String, String)>;

fn defaults() -> Map<String, Value> {
    let mut m = Map::new();
    m.insert("hbr_m".into(), json!(5.0));
    m.insert("sigma_km_primary".into(), json!([0.1, 0.5, 0.1]));
    m.insert("sigma_km_secondary".into(), json!([0.2, 1.0, 0.2]));
    m
}

/// Python 真值判斷（None、0、空字串、空陣列為假）
pub fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|x| x != 0.0).unwrap_or(true),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python float(x)：數值或數值字串
pub fn py_float_val(v: &Value) -> anyhow::Result<f64> {
    match v {
        Value::Number(n) => Ok(n.as_f64().unwrap()),
        Value::String(s) => s.trim().parse::<f64>().map_err(|_| anyhow::anyhow!("could not convert string to float: '{s}'")),
        Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        _ => anyhow::bail!("float() argument must be a string or a real number, not '{v}'"),
    }
}

fn py_int_val(v: &Value) -> anyhow::Result<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|x| x.trunc() as i64)).ok_or_else(|| anyhow::anyhow!("bad int")),
        Value::String(s) => s.trim().parse::<i64>().map_err(|_| anyhow::anyhow!("invalid literal for int() with base 10: '{s}'")),
        Value::Bool(b) => Ok(*b as i64),
        _ => anyhow::bail!("int() argument must be a string or a number, not '{v}'"),
    }
}

/// Python f-string / str() 呈現 JSON 值（錯誤訊息用）
fn py_show(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        x => x.to_string(),
    }
}

/// Python 等號：數值以數值比較
fn py_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => x.as_f64() == y.as_f64(),
        _ => a == b,
    }
}

fn tle_norad(line1: &str) -> Value {
    let id: String = line1.chars().skip(2).take(5).collect();
    id.trim().parse::<i64>().map(|v| json!(v)).unwrap_or(Value::Null)
}

fn resolve(spec: &Value, lookup: TleLookup) -> anyhow::Result<Option<(String, String, String)>> {
    let s = |k: &str| spec.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    if truthy(spec.get("line1")) && truthy(spec.get("line2")) {
        let name = if truthy(spec.get("name")) {
            py_show(&spec["name"])
        } else {
            format!("NORAD {}", spec.get("norad_id").map(py_show).unwrap_or_else(|| "?".into()))
        };
        return Ok(Some((name, s("line1"), s("line2"))));
    }
    if let Some(n) = spec.get("norad_id").filter(|v| !v.is_null()) {
        if let Some(hit) = lookup(py_int_val(n)?) {
            let name = if truthy(spec.get("name")) { py_show(&spec["name"]) } else { hit.0 };
            return Ok(Some((name, hit.1, hit.2)));
        }
    }
    Ok(None)
}

fn demo_cov(eph: &dyn Ephemeris, s2: [f64; 3], tau: f64) -> M3 {
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

fn sigma3(v: &Value) -> anyhow::Result<[f64; 3]> {
    let a = v.as_array().ok_or_else(|| anyhow::anyhow!("sigma_km 須為 3 個數值"))?;
    anyhow::ensure!(a.len() == 3, "sigma_km 須為 3 個數值");
    Ok([py_float_val(&a[0])?, py_float_val(&a[1])?, py_float_val(&a[2])?])
}

/// 回傳批次報告；輸入錯誤（解析失敗等）以 Err 回傳（對應 Python ValueError）
pub fn run_batch(req: &Value, eop: &Eop, lookup: TleLookup) -> anyhow::Result<Value> {
    let t_start = Instant::now();
    let start = UtcTime::parse(req["start"].as_str().ok_or_else(|| anyhow::anyhow!("start 須為 ISO 字串"))?)?;
    let dur = py_float_val(&req["duration_s"])?;
    if !(0.0 < dur && dur <= MAX_DURATION_S) {
        return Ok(json!({"status": "error", "error": format!("duration_s 須在 (0, {MAX_DURATION_S:.0}] 秒")}));
    }
    let thr = py_float_val(&req["threshold_km"])?;
    let coarse = if truthy(req.get("coarse_step_s")) { py_float_val(&req["coarse_step_s"])? } else { SEARCH_COARSE_STEP_S };
    let mut d = defaults();
    if let Some(Value::Object(extra)) = req.get("defaults") {
        for (k, v) in extra {
            d.insert(k.clone(), v.clone());
        }
    }
    let ert = EarthRotationTable::new(start, -1.0, dur + 1.0, eop)?;
    let span = (0.0, dur);

    let prim = &req["primary"];
    let Some(pr) = resolve(prim, lookup)? else {
        return Ok(json!({"status": "error", "error": format!("找不到主星 TLE：{}", prim)}));
    };
    let p_sgp4 = Sgp4Ephemeris::new(&pr.1, &pr.2, start, &ert, span)?;
    let p_eph = Memo::new(&p_sgp4);
    let p_sigma = if truthy(prim.get("sigma_km")) { prim["sigma_km"].clone() } else { d["sigma_km_primary"].clone() };
    let p_hbr = py_float_val(if truthy(prim.get("hbr_m")) { &prim["hbr_m"] } else { &d["hbr_m"] })?;
    let p_norad = if truthy(prim.get("norad_id")) { prim["norad_id"].clone() } else { tle_norad(&pr.1) };
    let ps = sigma3(&p_sigma)?;
    let p_s2 = [ps[0] * ps[0], ps[1] * ps[1], ps[2] * ps[2]];
    let n_series = SERIES_MAX_POINTS.min(2.0f64.max(dur / coarse + 1.0)) as usize;
    let s_step = dur / (n_series - 1) as f64;

    let mut pairs: Vec<Value> = Vec::new();
    let mut flat: Vec<Value> = Vec::new();
    let empty = vec![];
    for row in req["secondaries"].as_array().unwrap_or(&empty) {
        let mut base = Map::new();
        base.insert("secondary_norad".into(), row.get("norad_id").cloned().unwrap_or(Value::Null));
        base.insert("input_line".into(), row.get("line").cloned().unwrap_or(Value::Null));
        let pair_err = |mut base: Map<String, Value>, msg: String| {
            base.insert("status".into(), json!("error"));
            base.insert("error".into(), json!(msg));
            Value::Object(base)
        };
        let sr = match resolve(row, lookup) {
            Ok(Some(x)) => x,
            Ok(None) => {
                pairs.push(pair_err(base, "找不到 TLE".into()));
                continue;
            }
            Err(e) => return Err(e),
        };
        base.insert("secondary_name".into(), json!(sr.0));
        let row_norad = row.get("norad_id").cloned().unwrap_or(Value::Null);
        if py_eq(&row_norad, &p_norad) && !truthy(row.get("line1")) {
            pairs.push(pair_err(base, "與主星相同".into()));
            continue;
        }
        let res: anyhow::Result<Value> = (|| {
            let s_eph = Sgp4Ephemeris::new(&sr.1, &sr.2, start, &ert, span)?;
            let rel = RelativeState::new(&p_eph, &s_eph);
            let res = find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), 0.0, dur,
                AdaptiveParams { coarse_step: coarse, threshold_km: Some(thr), ..Default::default() });
            let keys = ["sigma_r_km", "sigma_t_km", "sigma_n_km"];
            let ss = if keys.iter().all(|k| truthy(row.get(*k))) {
                [py_float_val(&row["sigma_r_km"])?, py_float_val(&row["sigma_t_km"])?, py_float_val(&row["sigma_n_km"])?]
            } else {
                sigma3(&d["sigma_km_secondary"])?
            };
            let s_s2 = [ss[0] * ss[0], ss[1] * ss[1], ss[2] * ss[2]];
            let hbr_km = (p_hbr + py_float_val(if truthy(row.get("hbr_m")) { &row["hbr_m"] } else { &d["hbr_m"] })?) / 1000.0;
            let c3 = |tau: f64| {
                let (a, b) = (demo_cov(&p_eph, p_s2, tau), demo_cov(&s_eph, s_s2, tau));
                let mut c = [[0.0; 3]; 3];
                for i in 0..3 {
                    for j in 0..3 {
                        c[i][j] = a[i][j] + b[i][j];
                    }
                }
                c
            };
            let others: Vec<f64> = res.all_minima.iter().map(|m| m.tau).collect();
            let sec_norad = if truthy(base.get("secondary_norad")) { base["secondary_norad"].clone() } else { tle_norad(&sr.1) };
            let mut evs = Vec::new();
            for ap in &res.events {
                let mut e = build_event(&start, ap, &|t| rel.rva(t), &p_eph, Some(&c3), "demo", hbr_km, &others, span,
                    Some(json!(["assumed", "assumed"])));
                e["primary_norad"] = p_norad.clone();
                e["secondary_norad"] = sec_norad.clone();
                e["secondary_name"] = json!(sr.0);
                evs.push(e);
            }
            let n_search_evals = rel.n_evals.get();
            let series: Vec<f64> = (0..n_series).map(|i| norm(rel.rv(i as f64 * s_step).0)).collect();
            if let Some(e) = rel.take_error() {
                anyhow::bail!(e);
            }
            let gmin = res.global_min().map(|g| json!({"tca_utc": start.plus(g.tau).iso(), "miss_km": g.miss_km}));
            let mut out = base.clone();
            for (k, v) in [
                ("status", json!("ok")), ("n_events", json!(evs.len())), ("events", json!(evs)),
                ("n_minima", json!(res.all_minima.len())), ("n_evals", json!(n_search_evals)),
                ("global_min", gmin.unwrap_or(Value::Null)), ("series", json!({"step_s": s_step, "d_km": series})),
            ] {
                out.insert(k.into(), v);
            }
            flat.extend(evs);
            Ok(Value::Object(out))
        })();
        match res {
            Ok(v) => pairs.push(v),
            Err(e) => pairs.push(pair_err(base, e.to_string())),
        }
    }
    let foster = |e: &Value| e.get("pc").and_then(|p| p.get("foster")).and_then(Value::as_f64).filter(|x| *x != 0.0).unwrap_or(0.0);
    flat.sort_by(|a, b| {
        (-foster(a)).partial_cmp(&-foster(b)).unwrap_or(std::cmp::Ordering::Equal)
            .then(a["miss_km"].as_f64().unwrap_or(0.0).partial_cmp(&b["miss_km"].as_f64().unwrap_or(0.0)).unwrap_or(std::cmp::Ordering::Equal))
    });
    Ok(json!({
        "status": "ok", "start": start.iso(), "duration_s": dur, "threshold_km": thr,
        "primary": {"norad_id": p_norad, "name": pr.0, "hbr_m": p_hbr, "sigma_km": p_sigma},
        "defaults": d, "pairs": pairs, "events": flat,
        "search": {"method": "adaptive", "coarse_step_s": coarse, "min_step_s": SEARCH_MIN_STEP_S,
                   "accel_bound_km_s2": SEARCH_ACCEL_BOUND_KM_S2},
        "provenance": {"propagator": "SGP4 (WGS-72, opsmode i) → GCRF", "eop": eop.version(),
                       "covariance": "展示模式：RTN 三軸 σ、忽略相關項與時間演化",
                       "constants_version": CONSTANTS_VERSION},
        "elapsed_s": (t_start.elapsed().as_secs_f64() * 1000.0).round() / 1000.0,
    }))
}

pub const MAX_SECONDARIES: usize = 200;

/// Lab API 的請求整理（與 Python api/lab.py lab_batch 相同）：secondaries_csv 或 secondaries 陣列 →
/// run_batch 的輸入。成功回傳 (req, csv 解析結果)；失敗回傳 400 用的錯誤 JSON。
pub fn prepare_request(body: &Value) -> Result<(Value, Option<Value>), Value> {
    let mut parsed = None;
    let secs: Vec<Value> = if truthy(body.get("secondaries_csv")) {
        let text = match &body["secondaries_csv"] {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
        let p = super::csvio::parse_secondaries(&text);
        let rows = p["rows"].as_array().cloned().unwrap_or_default();
        parsed = Some(p);
        rows
    } else {
        body.get("secondaries").and_then(Value::as_array).map(|a| a.iter().filter(|s| s.is_object()).cloned().collect()).unwrap_or_default()
    };
    if secs.is_empty() {
        return Err(json!({"status": "error", "error": "沒有可分析的次星", "csv": parsed}));
    }
    if secs.len() > MAX_SECONDARIES {
        return Err(json!({"status": "error", "error": format!("次星最多 {MAX_SECONDARIES} 顆")}));
    }
    let mut req = Map::new();
    for k in ["primary", "start", "duration_s", "threshold_km", "coarse_step_s", "defaults"] {
        req.insert(k.into(), body.get(k).cloned().unwrap_or(Value::Null));
    }
    if !req["primary"].is_object() || !truthy(req.get("start")) || req["duration_s"].is_null() || req["threshold_km"].is_null() {
        return Err(json!({"status": "error", "error": "需要 primary、start、duration_s、threshold_km"}));
    }
    req.insert("secondaries".into(), Value::Array(secs));
    Ok((Value::Object(req), parsed))
}
