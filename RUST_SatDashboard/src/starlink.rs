//! `/starlink` 與 `/api/starlink/*`（Python 版 scenario04/api/starlink.py、starlink_census.py、
//! pages.py 之 /starlink 與轉址、positions.py 之 /api/v3_flight14_roster 的移植）。
//!
//! 子模組：
//! - `visibility`：可見性／RTT／遮蔽模擬（含自動作業殼層門檻 operational_perigee_floor）
//! - `census`：顆數普查、離軌名單、殼層、V3 統計
//! - `reentry_pass`：SGP4 逐圈近地點（零階再入估算）
//! - `segmented` + `msis00`：分段 M/A 校準再入預測（NRLMSISE-00 Rust 移植 + RK4）
//! - `forecast`：離軌預測背景批次（每 6 小時）
//! - `roster`：Starship Flight 14 V3 名單

mod census;
mod common;
mod forecast;
mod msis00;
mod msis00_data;
mod reentry_pass;
mod roster;
mod segmented;
mod visibility;

use std::collections::HashMap;
use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::{Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::{json, Value};

use crate::coverage::{TAIPEI_LAT, TAIPEI_LON};
use crate::state::AppState;

type St = State<Arc<AppState>>;
type Q = Query<HashMap<String, String>>;

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/starlink", get(page))
        .route("/starlink-census", get(|| async { found("/starlink?tab=census") }))
        .route("/starlink-v3", get(|| async { found("/starlink?tab=v3") }))
        .route("/starlink-deorbit", get(|| async { found("/starlink?tab=deorbit") }))
        .route("/api/starlink/visibility", get(api_visibility))
        .route("/api/starlink/obstruction", post(api_obstruction))
        .route("/api/starlink/census", get(api_census))
        .route("/api/starlink/shells", get(api_shells))
        .route("/api/starlink/deorbiting", get(api_deorbiting))
        .route("/api/starlink/deorbit_forecast", get(api_deorbit_forecast))
        .route("/api/starlink/v3_census", get(api_v3_census))
        .route("/api/starlink/reentry_detail", get(api_reentry_detail))
        .route("/api/v3_flight14_roster", get(api_v3_roster))
}

/// Flask `redirect(..., code=302)`
fn found(loc: &'static str) -> Response {
    (StatusCode::FOUND, [(header::LOCATION, loc)]).into_response()
}

fn json_resp(code: StatusCode, v: &Value, max_age: Option<u32>) -> Response {
    let mut r = (code, Json(v)).into_response();
    if let Some(a) = max_age {
        r.headers_mut().insert(header::CACHE_CONTROL, HeaderValue::from_str(&format!("public, max-age={a}")).unwrap());
    }
    r
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Option<T> {
    match tokio::task::spawn_blocking(f).await {
        Ok(v) => Some(v),
        Err(e) => {
            tracing::error!("背景工作失敗：{e}");
            None
        }
    }
}

fn internal() -> Response {
    json_resp(StatusCode::INTERNAL_SERVER_ERROR, &json!({"error": "內部錯誤"}), None)
}

async fn page(State(st): St) -> Response {
    forecast::start(st);
    crate::orbit_history::page("templates/starlink.html").into_response()
}

/// Python `parse_float_arg`：可解析則夾在 [lo, hi]，否則預設值
fn farg(q: &HashMap<String, String>, k: &str, d: f64, lo: f64, hi: f64) -> f64 {
    match q.get(k) {
        Some(v) => v.trim().parse::<f64>().map(|x| x.min(hi).max(lo)).unwrap_or(d),
        None => d,
    }
}

const GENERATIONS: [&str; 5] = ["all", "v1.0", "v1.5", "v2mini", "v3"];

fn norm_generation(g: &str) -> String {
    let g = g.trim();
    if GENERATIONS.contains(&g) {
        g.to_string()
    } else {
        "all".into()
    }
}

async fn api_visibility(State(st): St, Query(q): Q) -> Response {
    let lat = farg(&q, "lat", TAIPEI_LAT, -90.0, 90.0);
    let lon = farg(&q, "lon", TAIPEI_LON, -180.0, 180.0);
    let mask = farg(&q, "mask", 25.0, 0.0, 85.0);
    let hs = q.get("hours").map(|s| s.trim().parse::<i64>()).unwrap_or(Ok(24));
    let ss = q.get("step").map(|s| s.trim().parse::<i64>()).unwrap_or(Ok(15));
    let (hours, step) = match (hs, ss) {
        (Ok(h), Ok(s)) => (h.clamp(1, 72), s.clamp(1, 60)),
        _ => (24, 15),
    };
    let generation = norm_generation(q.get("generation").map(String::as_str).unwrap_or("all"));
    let dropout = farg(&q, "dropout_pct", 0.0, 0.0, 90.0);
    let excl = !matches!(q.get("exclude_deorbiting").map(String::as_str).unwrap_or("1"), "0" | "false" | "False");
    let p = visibility::Params { lat, lon, mask, hours, step, generation, dropout, exclude_deorbiting: excl };
    match visibility::compute_visibility(&st, p) {
        Some(v) => json_resp(StatusCode::OK, &v, None),
        None => json_resp(StatusCode::ACCEPTED, &json!({"status": "computing"}), None),
    }
}

fn jf(v: Option<&Value>, d: f64) -> Result<f64, String> {
    match v {
        None => Ok(d),
        Some(Value::Number(n)) => n.as_f64().ok_or_else(|| "could not convert to float".into()),
        Some(Value::Bool(b)) => Ok(if *b { 1.0 } else { 0.0 }),
        Some(Value::String(s)) => s.trim().parse().map_err(|_| format!("could not convert string to float: '{s}'")),
        Some(o) => Err(format!("float() argument must be a string or a real number, not '{o}'")),
    }
}

fn ji(v: Option<&Value>, d: i64) -> Result<i64, String> {
    match v {
        None => Ok(d),
        Some(Value::Number(n)) => n.as_i64().or_else(|| n.as_f64().map(|f| f.trunc() as i64)).ok_or_else(|| "invalid int".into()),
        Some(Value::Bool(b)) => Ok(*b as i64),
        Some(Value::String(s)) => s.trim().parse().map_err(|_| format!("invalid literal for int() with base 10: '{s}'")),
        Some(o) => Err(format!("int() argument must be a string, a bytes-like object or a real number, not '{o}'")),
    }
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn parse_obstruction(body: &Value) -> Result<(visibility::Params, Vec<[f64; 2]>), String> {
    let g = |k: &str| body.get(k);
    let lat = jf(g("lat"), TAIPEI_LAT)?;
    let lon = jf(g("lon"), TAIPEI_LON)?;
    let mask = jf(g("mask"), 25.0)?;
    let hours = ji(g("hours"), 24)?.clamp(1, 72);
    let step = ji(g("step"), 15)?.clamp(1, 60);
    let gen_raw = match g("generation") {
        None => "all".to_string(),
        Some(Value::String(s)) => s.clone(),
        Some(o) => o.to_string(),
    };
    let generation = if gen_raw.trim().is_empty() { "all".to_string() } else { norm_generation(&gen_raw) };
    let dropout = jf(g("dropout_pct"), 0.0)?.min(90.0).max(0.0);
    let excl = g("exclude_deorbiting").map(truthy).unwrap_or(true);
    let mut cells = Vec::new();
    if let Some(Value::Array(raw)) = g("blocked_cells") {
        for c in raw {
            if let Value::Array(a) = c {
                if a.len() >= 2 {
                    cells.push([jf(Some(&a[0]), 0.0)?, jf(Some(&a[1]), 0.0)?]);
                }
            }
        }
    }
    Ok((visibility::Params { lat, lon, mask, hours, step, generation, dropout, exclude_deorbiting: excl }, cells))
}

async fn api_obstruction(body: Bytes) -> Response {
    let body: Value = serde_json::from_slice(&body).ok().filter(Value::is_object).unwrap_or_else(|| json!({}));
    let (p, cells) = match parse_obstruction(&body) {
        Ok(v) => v,
        Err(e) => return json_resp(StatusCode::BAD_REQUEST, &json!({"error": format!("參數錯誤：{e}")}), None),
    };
    match visibility::compute_obstruction(p, &cells) {
        Some(v) => json_resp(StatusCode::OK, &v, None),
        None => json_resp(StatusCode::CONFLICT, &json!({"error": "基礎資料尚未就緒，請先呼叫 /api/starlink/visibility"}), None),
    }
}

async fn api_census(State(st): St) -> Response {
    let kt = census::keeptrack_starlink_count().await;
    let Some(ours) = blocking(move || census::our_starlink_counts(&st)).await else { return internal() };
    json_resp(StatusCode::OK, &json!({"keeptrack": kt, "ours": ours}), None)
}

async fn api_shells(State(st): St) -> Response {
    match blocking(move || census::starlink_shells(&st)).await {
        Some(v) => json_resp(StatusCode::OK, &v, Some(600)),
        None => internal(),
    }
}

async fn api_deorbiting(State(st): St, Query(q): Q) -> Response {
    forecast::start(st.clone());
    let limit = q.get("limit").map(|s| s.trim().parse::<i64>()).unwrap_or(Ok(60)).map(|v| v.clamp(1, 300)).unwrap_or(60) as usize;
    let Some(mut data) = blocking({
        let st = st.clone();
        move || census::list_deorbiting_starlinks(&st, limit)
    })
    .await
    else {
        return internal();
    };
    if data.get("error").is_none() {
        let fc = forecast::get(&st);
        let fmap = fc.as_ref().and_then(|f| f.get("forecasts")).cloned().unwrap_or(Value::Null);
        if let Some(items) = data["items"].as_array_mut() {
            for it in items {
                let k = it["norad_id"].to_string();
                it["seg"] = fmap.get(&k).cloned().unwrap_or(Value::Null);
            }
        }
        data["forecast"] = match fc.as_ref().filter(|f| f.as_object().is_some_and(|o| !o.is_empty())) {
            Some(f) => json!({"generated_at": f.get("generated_at"), "method": f.get("method"),
                              "window_rule": f.get("window_rule"), "n": f.get("n")}),
            None => Value::Null,
        };
    }
    json_resp(StatusCode::OK, &data, Some(300))
}

async fn api_deorbit_forecast(State(st): St) -> Response {
    forecast::start(st.clone());
    match forecast::get(&st) {
        Some(v) => json_resp(StatusCode::OK, &v, Some(600)),
        None => json_resp(StatusCode::ACCEPTED, &json!({"status": "computing"}), None),
    }
}

async fn api_v3_census(State(st): St) -> Response {
    let Some((mut v, need_prov)) = blocking(move || census::count_v3_candidates_db(&st)).await else { return internal() };
    if need_prov {
        v["provisional"] = census::fetch_v3_provisional_roster().await;
    }
    json_resp(StatusCode::OK, &v, Some(300))
}

async fn api_reentry_detail(State(st): St, Query(q): Q) -> Response {
    let Some(norad) = q.get("norad").and_then(|s| s.trim().parse::<i64>().ok()) else {
        return json_resp(StatusCode::BAD_REQUEST, &json!({"error": "norad 必填且需為整數"}), None);
    };
    let days = q.get("days").map(|s| s.trim().parse::<f64>()).unwrap_or(Ok(10.0)).map(|d| d.min(30.0).max(1.0)).unwrap_or(10.0);
    forecast::start(st.clone());
    forecast::ensure_space_weather(&st).await;
    let Some(v) = blocking(move || {
        let norad = norad as u32;
        let (l1, l2) = match census::latest_tle(&st, norad) {
            Ok(t) => t,
            Err(e) => return e,
        };
        let mut est = reentry_pass::reentry_estimate(&l1, &l2, days, 100.0);
        est["norad_id"] = json!(norad);
        est["name"] = json!(common::starlink_name(&st, norad).unwrap_or_else(|| format!("NORAD-{norad}")));
        let mut seg = forecast::forecast_norad(&st, norad, None);
        if let Some(o) = seg.as_object_mut() {
            for k in ["stats", "reentry_unix", "early_unix", "late_unix"] {
                o.remove(k);
            }
        }
        est["segmented"] = seg;
        est
    })
    .await
    else {
        return internal();
    };
    json_resp(StatusCode::OK, &v, Some(300))
}

async fn api_v3_roster(State(st): St) -> Response {
    json_resp(StatusCode::OK, &roster::roster(st).await, None)
}
