//! HTTP 路由（對應 Python api/positions.py、conjunctions.py、layers.py、user_data.py、pages.py）。

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, Response, StatusCode};
use axum::response::{Html, IntoResponse};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{Duration, Utc};
use rayon::prelude::*;
use serde_json::{json, Map, Value};

use crate::assets;
use crate::classify::get_color;
use crate::index::{SatIndex, SatInfo};
use crate::physics::{self, round_to};
use crate::state::{AppState, Cached};
use crate::userdata;

type St = State<Arc<AppState>>;
type Q = Query<HashMap<String, String>>;
type Resp = Response<Body>;

const UNPORTED_PAGES: [&str; 0] = [];

pub fn router(state: Arc<AppState>) -> Router {
    let mut r = Router::new()
        .route("/", get(page_index))
        .route("/static/{*path}", get(static_file))
        .route("/cesium/{*path}", get(cesium_file))
        .route("/ext/{*path}", get(ext_file))
        .route("/favicon.ico", get(|| async { StatusCode::NO_CONTENT }))
        .route("/api/logo", get(api_logo))
        .route("/api/health", get(api_health))
        .route("/api/about", get(|| async { Json(crate::about::json()) }))
        .route("/api/stats", get(api_stats))
        .route("/api/db_info", get(api_db_info))
        .route("/api/positions", get(api_positions))
        .route("/api/positions/coords", get(api_positions_coords))
        .route("/api/positions/active", post(api_positions_active))
        .route("/api/position/{id}", get(api_position_single))
        .route("/api/sat_orbit", get(api_sat_orbit))
        .route("/api/sat_tle", get(api_sat_tle))
        .route("/api/search", get(api_search))
        .route("/api/conjunctions", get(api_conjunctions))
        .route("/api/cdm/{id}", get(api_spacetrack_cdm))
        .route("/api/decay/{id}", get(api_spacetrack_other))
        .route("/api/satcat/{id}", get(api_spacetrack_other))
        .route("/api/textures", get(api_textures))
        .route("/api/globe_texture", get(api_globe_texture_default))
        .route("/api/globe_texture/{name}", get(api_globe_texture))
        .route("/api/layers/borders", get(api_layer_borders))
        .route("/api/layers/ssn_stations", get(api_layer_ssn))
        .route("/api/layers/user_geojson", get(api_user_geojson_list))
        .route("/api/layers/user_geojson/{name}", get(api_user_geojson_file))
        .route("/api/user/tles", get(api_user_tles))
        .route("/api/user/catalogue", get(api_user_catalogue))
        .route("/api/tracking/list", get(api_tracking_list))
        .route("/api/tracking/positions", get(api_tracking_positions))
        .route("/api/admin/reload_cats", post(api_admin_reload));
    for p in UNPORTED_PAGES {
        r = r.route(p, get(page_not_ported));
    }
    let r = crate::api_phase2::extend(r);
    let r = crate::tiles::extend(r);
    let r = crate::mission::extend(r);
    let r = crate::games::extend(r);
    let r = crate::orbit_history::extend(r);
    let r = crate::lab::extend(r);
    let r = crate::story::extend(r);
    let r = crate::starlink::extend(r);
    let r = crate::update::extend(r);
    r.fallback(fallback).with_state(state)
}

// ── 工具 ─────────────────────────────────────────────────────────────────────

fn json_cached(v: &Value, max_age: u64) -> Resp {
    let mut r = Json(v).into_response();
    r.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_str(&format!("public, max-age={max_age}")).unwrap(),
    );
    r
}

fn err(status: StatusCode, msg: impl Into<String>) -> Resp {
    (status, Json(json!({"error": msg.into()}))).into_response()
}

/// 在阻塞執行緒池執行（SGP4 / DuckDB 等 CPU/IO 工作，不卡住 async runtime）
async fn blocking<F>(f: F) -> Resp
where
    F: FnOnce() -> Resp + Send + 'static,
{
    match tokio::task::spawn_blocking(f).await {
        Ok(r) => r,
        Err(e) => {
            tracing::error!("背景工作失敗：{e}");
            err(StatusCode::INTERNAL_SERVER_ERROR, "伺服器內部錯誤")
        }
    }
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn put_llh(m: &mut Map<String, Value>, llh: [f64; 3]) {
    m.insert("lat".into(), json!(round_to(llh[0], 4)));
    m.insert("lon".into(), json!(round_to(llh[1], 4)));
    m.insert("alt_km".into(), json!(round_to(llh[2], 1)));
}

fn basic_info(s: &SatInfo) -> Map<String, Value> {
    let v = json!({
        "norad_id": s.norad_id,
        "name": s.name,
        "country": s.country,
        "purpose": s.purpose,
        "era": s.era,
        "constellation": s.constellation_or_dash(),
    });
    match v {
        Value::Object(m) => m,
        _ => unreachable!(),
    }
}

/// 平行傳播一批衛星至同一時刻（經緯高）
fn propagate_many(idx: &SatIndex, nids: &[u32]) -> Vec<Option<[f64; 3]>> {
    let t = Utc::now();
    nids.par_iter()
        .map(|n| {
            idx.sats
                .get(n)
                .and_then(|s| s.prop.as_ref())
                .and_then(|p| p.llh(&t))
        })
        .collect()
}

fn filter_params(q: &HashMap<String, String>) -> Result<(String, String, bool), Resp> {
    let ftype = q.get("ftype").map(|s| s.trim().to_string()).unwrap_or_default();
    let fval = q.get("fval").map(|s| s.trim().to_string()).unwrap_or_default();
    let payload_only = q.get("payload_only").map(|s| s == "1").unwrap_or(false);
    if !["country", "purpose", "era", "constellation"].contains(&ftype.as_str()) || fval.is_empty() {
        return Err(err(
            StatusCode::BAD_REQUEST,
            "ftype 必須為 country/purpose/era/constellation，且 fval 不可空白",
        ));
    }
    Ok((ftype, fval, payload_only))
}

fn matched_ids(idx: &SatIndex, ftype: &str, fval: &str, payload_only: bool) -> Vec<u32> {
    idx.sats
        .values()
        .filter(|s| s.field(ftype) == Some(fval))
        .filter(|s| !(payload_only && (s.purpose == "碎片" || s.purpose == "火箭體")))
        .map(|s| s.norad_id)
        .collect()
}

// ── 頁面與靜態檔 ─────────────────────────────────────────────────────────────

async fn page_index() -> Html<String> {
    Html(assets::globe_html())
}

async fn page_not_ported(uri: axum::http::Uri) -> Html<String> {
    Html(assets::not_ported_html(uri.path()))
}

async fn static_file(Path(path): Path<String>) -> Resp {
    assets::serve(&format!("static/{path}"), 3600)
}

async fn ext_file(Path(path): Path<String>) -> Resp {
    assets::serve(&format!("ext/{path}"), 3600)
}

async fn cesium_file(Path(path): Path<String>) -> Resp {
    assets::serve(&format!("cesium/{path}"), 604800)
}

async fn fallback(uri: axum::http::Uri) -> Resp {
    if uri.path().starts_with("/api/") {
        err(
            StatusCode::NOT_FOUND,
            format!("此 API 尚未移植至 Rust 單機版：{}", uri.path()),
        )
    } else {
        assets::text(StatusCode::NOT_FOUND, format!("找不到頁面：{}", uri.path()))
    }
}

/// 右下角 Logo：讀取執行檔同一資料夾的 logo.png 或 logo.jpg（可隨時替換，不快取）；
/// 都沒有就回 404，前端 onerror 隱藏 Logo 區塊。
async fn api_logo() -> Resp {
    let dir = std::env::current_exe().ok().and_then(|e| e.parent().map(|d| d.to_path_buf()));
    if let Some(dir) = dir {
        for (name, ct) in [("logo.png", "image/png"), ("logo.jpg", "image/jpeg"), ("logo.jpeg", "image/jpeg")] {
            if let Ok(b) = std::fs::read(dir.join(name)) {
                return assets::bytes_response(b, ct, 0);
            }
        }
    }
    StatusCode::NOT_FOUND.into_response()
}

async fn api_health(State(st): St) -> Json<Value> {
    let idx = st.index();
    Json(json!({
        "ok": true,
        "version": crate::about::VERSION,
        "build_date": crate::about::BUILD_DATE,
        "arch": std::env::consts::ARCH,
        "satellites": idx.sats.len(),
        "index_built_at": idx.built_at.to_rfc3339(),
        "data_dir": st.cfg.home.display().to_string(),
        "db": st.cfg.resolve_db().map(|p| p.display().to_string()),
    }))
}

// ── 統計 / DB 資訊 ───────────────────────────────────────────────────────────

async fn api_stats(State(st): St, Query(q): Q) -> Resp {
    let payload_only = q.get("payload_only").map(|s| s == "1").unwrap_or(false);
    blocking(move || {
        let idx = st.index();
        let mut c = st.stats_cache.lock();
        if let Some(hit) = c.get(&payload_only) {
            if hit.at.elapsed().as_secs() < 600 {
                return Json(&*hit.value).into_response();
            }
        }
        let v = Arc::new(crate::index::build_stats(&idx, payload_only));
        c.insert(
            payload_only,
            Cached {
                at: Instant::now(),
                value: v.clone(),
            },
        );
        Json(&*v).into_response()
    })
    .await
}

async fn api_db_info(State(st): St) -> Resp {
    blocking(move || {
        let ttl = st.cfg.db_info_ttl_s;
        if let Some(c) = st.db_info_cache.lock().as_ref() {
            if c.at.elapsed().as_secs() < ttl {
                return json_cached(&c.value, ttl);
            }
        }
        let v = Arc::new(crate::index::db_info(&st.cfg));
        *st.db_info_cache.lock() = Some(Cached {
            at: Instant::now(),
            value: v.clone(),
        });
        json_cached(&v, ttl)
    })
    .await
}

// ── 位置 ─────────────────────────────────────────────────────────────────────

async fn api_positions(State(st): St, Query(q): Q) -> Resp {
    let (ftype, fval, payload_only) = match filter_params(&q) {
        Ok(v) => v,
        Err(r) => return r,
    };
    blocking(move || {
        let idx = st.index();
        let matched = matched_ids(&idx, &ftype, &fval, payload_only);
        let t0 = Instant::now();
        let pos = propagate_many(&idx, &matched);
        let elapsed = t0.elapsed().as_secs_f64();
        tracing::info!(
            "平行傳播 {} 顆（{ftype}={fval}）耗時 {:.3} s",
            matched.len(),
            elapsed
        );
        let color = get_color(&ftype, &fval);
        let sats: Vec<Value> = matched
            .iter()
            .zip(pos)
            .filter_map(|(n, p)| {
                let p = p?;
                let mut m = basic_info(&idx.sats[n]);
                m.insert("color".into(), json!(color));
                put_llh(&mut m, p);
                Some(Value::Object(m))
            })
            .collect();
        Json(json!({
            "ftype": ftype,
            "fval": fval,
            "count": sats.len(),
            "total_matched": matched.len(),
            "sampled": false,
            "elapsed_sec": round_to(elapsed, 3),
            "vectorized": true,
            "satellites": sats,
            "timestamp": now_iso(),
        }))
        .into_response()
    })
    .await
}

/// 中頻更新端點。Rust 版平行 SGP4 夠快，直接即時傳播（不需背景快取）。
async fn api_positions_coords(State(st): St, Query(q): Q) -> Resp {
    let (ftype, fval, payload_only) = match filter_params(&q) {
        Ok(v) => v,
        Err(r) => return r,
    };
    blocking(move || {
        let idx = st.index();
        let matched = matched_ids(&idx, &ftype, &fval, payload_only);
        let sats = coords_list(&idx, &matched);
        Json(json!({
            "count": sats.len(),
            "from_cache": false,
            "cache_age": null,
            "timestamp": now_iso(),
            "satellites": sats,
        }))
        .into_response()
    })
    .await
}

fn coords_list(idx: &SatIndex, nids: &[u32]) -> Vec<Value> {
    nids.iter()
        .zip(propagate_many(idx, nids))
        .filter_map(|(n, p)| {
            let p = p?;
            Some(json!({"norad_id": n, "lat": round_to(p[0], 4),
                        "lon": round_to(p[1], 4), "alt_km": round_to(p[2], 1)}))
        })
        .collect()
}

async fn api_positions_active(State(st): St, body: Option<Json<Value>>) -> Resp {
    let ids: Vec<u32> = body
        .and_then(|Json(v)| v.get("norad_ids").and_then(|a| a.as_array()).cloned())
        .unwrap_or_default()
        .iter()
        .take(100)
        .filter_map(|x| match x {
            Value::Number(n) => n.as_u64().map(|v| v as u32),
            Value::String(s) => s.parse().ok(),
            _ => None,
        })
        .collect();
    let idx = st.index();
    let valid: Vec<u32> = ids.into_iter().filter(|n| idx.sats.contains_key(n)).collect();
    if valid.is_empty() {
        return Json(json!({"satellites": [], "count": 0})).into_response();
    }
    let t0 = Instant::now();
    let sats = coords_list(&idx, &valid);
    Json(json!({
        "count": sats.len(),
        "elapsed_sec": round_to(t0.elapsed().as_secs_f64(), 4),
        "timestamp": now_iso(),
        "satellites": sats,
    }))
    .into_response()
}

async fn api_position_single(State(st): St, Path(id): Path<u32>) -> Resp {
    let idx = st.index();
    let Some(s) = idx.sats.get(&id) else {
        return err(StatusCode::NOT_FOUND, format!("NORAD {id} 不在索引中"));
    };
    let mut m = basic_info(s);
    if let Some(p) = s.prop.as_ref().and_then(|p| p.llh(&Utc::now())) {
        put_llh(&mut m, p);
    }
    Json(Value::Object(m)).into_response()
}

fn parse_norad(q: &HashMap<String, String>) -> Result<u32, Resp> {
    q.get("norad_id")
        .map(|s| s.trim())
        .unwrap_or("0")
        .parse::<u32>()
        .map_err(|_| err(StatusCode::BAD_REQUEST, "norad_id 必須為整數"))
}

async fn api_sat_orbit(State(st): St, Query(q): Q) -> Resp {
    let id = match parse_norad(&q) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let hours: f64 = q
        .get("hours")
        .and_then(|s| s.parse().ok())
        .unwrap_or(2.0_f64)
        .clamp(0.01, 240.0);
    let pts: usize = q
        .get("pts")
        .and_then(|s| s.parse().ok())
        .unwrap_or(120)
        .clamp(1, 720);
    let idx = st.index();
    let Some(s) = idx.sats.get(&id) else {
        return err(StatusCode::NOT_FOUND, format!("NORAD {id} 不在索引中"));
    };
    let Some(p) = s.prop.as_ref() else {
        return err(StatusCode::NOT_FOUND, format!("NORAD {id} 無 TLE 資料"));
    };
    let now = Utc::now();
    let step_ms = hours * 3_600_000.0 / pts as f64;
    let positions: Vec<Value> = (0..=pts)
        .filter_map(|i| {
            let t = now + Duration::milliseconds((i as f64 * step_ms) as i64);
            let llh = p.llh(&t)?;
            Some(json!({"lat": round_to(llh[0], 4), "lon": round_to(llh[1], 4),
                        "alt_km": round_to(llh[2], 1)}))
        })
        .collect();
    Json(json!({
        "norad_id": id,
        "name": s.name,
        "hours": hours,
        "pts": positions.len(),
        "positions": positions,
    }))
    .into_response()
}

async fn api_sat_tle(State(st): St, Query(q): Q) -> Resp {
    let id = match parse_norad(&q) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let idx = st.index();
    let Some(s) = idx.sats.get(&id) else {
        return err(StatusCode::NOT_FOUND, format!("NORAD {id} 不在索引中"));
    };
    if s.line1.is_empty() || s.line2.is_empty() {
        return err(StatusCode::NOT_FOUND, format!("NORAD {id} 無 TLE 資料"));
    }
    let mut m = basic_info(s);
    m.insert("line1".into(), json!(s.line1));
    m.insert("line2".into(), json!(s.line2));
    Json(Value::Object(m)).into_response()
}

async fn api_search(State(st): St, Query(q): Q) -> Resp {
    let query = q.get("q").map(|s| s.trim().to_string()).unwrap_or_default();
    if query.chars().count() < 2 {
        return Json(json!({"results": [], "count": 0, "query": query})).into_response();
    }
    let idx = st.index();
    let up = query.to_uppercase();
    let mut matches: Vec<(u8, &SatInfo)> = Vec::new();
    if query.chars().all(|c| c.is_ascii_digit()) {
        if let Some(s) = query.parse::<u32>().ok().and_then(|n| idx.sats.get(&n)) {
            matches.push((0, s));
        }
    }
    for s in idx.sats.values() {
        if s.name.to_uppercase().contains(&up) && !matches.iter().any(|(_, m)| m.norad_id == s.norad_id) {
            matches.push((1, s));
        }
        if matches.len() >= 60 {
            break;
        }
    }
    matches.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.name.cmp(&b.1.name)));
    matches.truncate(20);
    let nids: Vec<u32> = matches.iter().map(|(_, s)| s.norad_id).collect();
    let pos = propagate_many(&idx, &nids);
    let results: Vec<Value> = matches
        .iter()
        .zip(pos)
        .map(|((_, s), p)| {
            let mut m = basic_info(s);
            if let Some(p) = p {
                put_llh(&mut m, p);
            }
            Value::Object(m)
        })
        .collect();
    Json(json!({"results": results, "count": results.len(), "query": query})).into_response()
}

// ── 接近事件 ─────────────────────────────────────────────────────────────────

async fn api_conjunctions(State(st): St, Query(q): Q) -> Resp {
    let threshold = q
        .get("threshold_km")
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(st.cfg.conj_threshold_km)
        .clamp(1.0, 50.0);
    let max_pairs = q
        .get("max_pairs")
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(200)
        .clamp(10, 2000);
    blocking(move || {
        let ttl = st.cfg.conj_ttl_s;
        let key = ((threshold * 10.0).round() as u64, max_pairs);
        let lookup = || {
            st.conj_cache
                .lock()
                .get(&key)
                .filter(|c| c.at.elapsed().as_secs() < ttl)
                .map(|c| c.value.clone())
        };
        if let Some(v) = lookup() {
            return json_cached(&v, ttl);
        }
        let _g = st.conj_lock.lock();
        if let Some(v) = lookup() {
            return json_cached(&v, ttl);
        }
        let v = Arc::new(build_conjunctions(&st, threshold, max_pairs));
        st.conj_cache.lock().insert(
            key,
            Cached {
                at: Instant::now(),
                value: v.clone(),
            },
        );
        json_cached(&v, ttl)
    })
    .await
}

fn build_conjunctions(st: &Arc<AppState>, threshold: f64, max_pairs: usize) -> Value {
    let idx = st.index();
    if idx.sats.len() < 2 {
        return json!({"count": 0, "pairs": [], "threshold_km": threshold, "total_scanned": 0});
    }
    let list: Vec<&SatInfo> = idx.sats.values().collect();
    let props: Vec<_> = list.iter().map(|s| s.prop.as_ref()).collect();
    let t = Utc::now();
    let t0 = Instant::now();
    let anchors: Vec<usize> = list
        .iter()
        .enumerate()
        .filter(|(_, s)| physics::STATION_ANCHORS.contains(&s.norad_id))
        .map(|(i, _)| i)
        .collect();
    let res = physics::scan_pairs(&props, &t, threshold, max_pairs, &anchors);
    tracing::info!(
        "接近事件掃描：{} 有效衛星，閾值 {threshold:.0} km，配對 {}，SGP4 {:.3} s，KD {:.3} s",
        res.total_scanned,
        res.pairs.len(),
        res.t_sgp4,
        res.t_kd
    );
    let c = &st.cfg;
    let pairs: Vec<Value> = res
        .pairs
        .iter()
        .map(|&(i, j, miss)| {
            let (a, b) = (list[i], list[j]);
            let (la, lb) = (res.llh[i], res.llh[j]);
            let pc = physics::compute_pc_chan(miss, c.sigma_r_km, c.sigma_t_km, c.sat_radius_km);
            json!({
                "primary_norad": a.norad_id,
                "primary_name": a.name,
                "primary_purpose": a.purpose,
                "primary_lat": round_to(la[0], 4),
                "primary_lon": round_to(la[1], 4),
                "primary_alt_km": round_to(la[2], 1),
                "secondary_norad": b.norad_id,
                "secondary_name": b.name,
                "secondary_purpose": b.purpose,
                "secondary_lat": round_to(lb[0], 4),
                "secondary_lon": round_to(lb[1], 4),
                "secondary_alt_km": round_to(lb[2], 1),
                "miss_km": round_to(miss, 3),
                "Pc": pc,
                "Pc_str": physics::py_sci(pc),
                "risk_level": physics::risk_level(pc),
            })
        })
        .collect();
    json!({
        "count": pairs.len(),
        "threshold_km": threshold,
        "max_pairs": max_pairs,
        "pairs": pairs,
        "total_scanned": res.total_scanned,
        "docked_excluded": res.docked_excluded,
        "elapsed_sec": round_to(t0.elapsed().as_secs_f64(), 3),
        "sgp4_sec": round_to(res.t_sgp4, 4),
        "kdtree_sec": round_to(res.t_kd, 4),
        "vectorized": true,
        "engine": "rust",
        "timestamp": now_iso(),
    })
}

/// Space-Track 整合尚未移植：與 Python 版未設定帳密時相同回應
async fn api_spacetrack_cdm(Path(id): Path<u32>) -> Json<Value> {
    Json(json!({"norad_id": id, "error": "Space-Track 未配置", "count": 0, "events": []}))
}
async fn api_spacetrack_other(Path(id): Path<u32>) -> Json<Value> {
    Json(json!({"norad_id": id, "error": "Space-Track 未配置"}))
}

// ── 底圖 ─────────────────────────────────────────────────────────────────────

const EMBED_TOPO: &str = "assets/world_topo_bathy_5400.jpg";
const NE2_XML: &str = "cesium/Assets/Textures/NaturalEarthII/tilemapresource.xml";

struct Basemap {
    key: &'static str,
    label: &'static str,
    credit: &'static str,
    disk: &'static [&'static str],
    embedded: Option<&'static str>,
}

const BASEMAPS: [Basemap; 3] = [
    Basemap {
        // 預設底圖固定為「地形+海底地形 5.4K」（內嵌於 exe；地球儀、任務規劃、RPO 頁共用；底圖選單已隱藏）
        key: "default",
        label: "地形+海底地形 5.4K",
        credit: "NASA Visible Earth（Blue Marble 地形＋海底地形）",
        disk: &["textures/world_topo_bathy_5400.jpg"],
        embedded: Some(EMBED_TOPO),
    },
    Basemap {
        key: "2k",
        label: "藍色大理石 2K",
        credit: "NASA Visible Earth",
        disk: &["textures/land_shallow_topo_2048.jpg"],
        embedded: None,
    },
    Basemap {
        key: "topo",
        label: "地形+海底地形 5.4K",
        credit: "NASA Visible Earth",
        disk: &["textures/world_topo_bathy_5400.jpg"],
        embedded: Some(EMBED_TOPO),
    },
];

fn basemap_bytes(st: &AppState, bm: &Basemap) -> Option<Vec<u8>> {
    bm.disk
        .iter()
        .find_map(|rel| std::fs::read(st.cfg.home.join(rel)).ok())
        .or_else(|| bm.embedded.and_then(assets::get))
}

fn basemap_available(st: &AppState, bm: &Basemap) -> bool {
    bm.disk.iter().any(|rel| st.cfg.home.join(rel).is_file())
        || bm
            .embedded
            .map(|e| assets::Web::get(e).is_some())
            .unwrap_or(false)
}

async fn api_textures(State(st): St) -> Json<Value> {
    let mut v: Vec<Value> = BASEMAPS
        .iter()
        .map(|b| {
            json!({"key": b.key, "label": b.label, "credit": b.credit, "type": "single",
                   "available": basemap_available(&st, b)})
        })
        .collect();
    v.push(json!({
        "key": "natural_earth", "label": "Natural Earth II",
        "credit": "Natural Earth / CesiumJS (已內建)", "type": "tms",
        "available": assets::Web::get(NE2_XML).is_some(),
        "tms_url": "/cesium/Assets/Textures/NaturalEarthII/",
    }));
    Json(Value::Array(v))
}

fn image_response(data: Vec<u8>) -> Resp {
    let ct = if data.starts_with(b"\x89PNG") {
        "image/png"
    } else {
        "image/jpeg"
    };
    assets::bytes_response(data, ct, 604800)
}

async fn api_globe_texture_default(st: St) -> Resp {
    api_globe_texture(st, Path("default".into())).await
}

async fn api_globe_texture(State(st): St, Path(name): Path<String>) -> Resp {
    if name == "natural_earth" {
        return assets::text(StatusCode::BAD_REQUEST, "TMS 底圖請直接使用 tms_url");
    }
    let Some(bm) = BASEMAPS.iter().find(|b| b.key == name) else {
        return assets::text(StatusCode::NOT_FOUND, format!("未知底圖: {name}"));
    };
    match basemap_bytes(&st, bm) {
        Some(b) => image_response(b),
        None => assets::text(StatusCode::SERVICE_UNAVAILABLE, "底圖檔案尚未下載"),
    }
}

// ── 向量圖層 ─────────────────────────────────────────────────────────────────

const TAIWAN_PROBE: (f64, f64) = (121.0, 23.7);
const MAX_STRIP_SPAN_DEG: f64 = 15.0;

fn point_in_ring(lon: f64, lat: f64, ring: &[Value]) -> bool {
    let pts: Vec<(f64, f64)> = ring
        .iter()
        .filter_map(|p| Some((p.get(0)?.as_f64()?, p.get(1)?.as_f64()?)))
        .collect();
    let mut inside = false;
    let n = pts.len();
    if n == 0 {
        return false;
    }
    let mut j = n - 1;
    for i in 0..n {
        let (xi, yi) = pts[i];
        let (xj, yj) = pts[j];
        if (yi > lat) != (yj > lat) {
            let x = (xj - xi) * (lat - yi) / (yj - yi) + xi;
            if lon < x {
                inside = !inside;
            }
        }
        j = i;
    }
    inside
}

fn ring_small(ring: &[Value]) -> bool {
    let (mut x0, mut x1, mut y0, mut y1) = (f64::MAX, f64::MIN, f64::MAX, f64::MIN);
    for p in ring {
        if let (Some(x), Some(y)) = (p.get(0).and_then(Value::as_f64), p.get(1).and_then(Value::as_f64)) {
            x0 = x0.min(x);
            x1 = x1.max(x);
            y0 = y0.min(y);
            y1 = y1.max(y);
        }
    }
    x1 - x0 <= MAX_STRIP_SPAN_DEG && y1 - y0 <= MAX_STRIP_SPAN_DEG
}

fn feature_contains_taiwan(f: &Value) -> bool {
    let Some(g) = f.get("geometry") else { return false };
    let coords = g.get("coordinates").and_then(Value::as_array);
    let rings: Vec<&Vec<Value>> = match (g.get("type").and_then(Value::as_str), coords) {
        (Some("Polygon"), Some(c)) => c.first().and_then(Value::as_array).into_iter().collect(),
        (Some("MultiPolygon"), Some(c)) => c
            .iter()
            .filter_map(|poly| poly.as_array()?.first()?.as_array())
            .collect(),
        _ => vec![],
    };
    rings
        .into_iter()
        .any(|r| ring_small(r) && point_in_ring(TAIWAN_PROBE.0, TAIWAN_PROBE.1, r))
}

async fn api_layer_borders(State(st): St) -> Resp {
    let cached = st.borders_cache.lock().clone();
    let bytes = match cached {
        Some(b) => b,
        None => {
            let raw = std::fs::read(st.cfg.home.join("borders.geojson"))
                .ok()
                .or_else(|| assets::get("assets/borders.geojson"))
                .unwrap_or_else(|| br#"{"type":"FeatureCollection","features":[]}"#.to_vec());
            let mut v: Value = serde_json::from_slice(&raw)
                .unwrap_or_else(|_| json!({"type": "FeatureCollection", "features": []}));
            if st.cfg.taiwan_admin_file().is_file() || assets::get(EMBED_TW_ADMIN).is_some() {
                if let Some(feats) = v.get_mut("features").and_then(Value::as_array_mut) {
                    let before = feats.len();
                    feats.retain(|f| !feature_contains_taiwan(f));
                    tracing::info!("全球國界：剔除粗糙台灣輪廓 {} 個 feature", before - feats.len());
                }
            }
            let b = Arc::new(serde_json::to_vec(&v).unwrap_or_default());
            *st.borders_cache.lock() = Some(b.clone());
            b
        }
    };
    assets::bytes_response((*bytes).clone(), "application/json; charset=utf-8", 86400)
}

async fn api_layer_ssn(State(st): St) -> Resp {
    let data = std::fs::read(st.cfg.override_file("ssn_stations.geojson"))
        .unwrap_or_else(|_| assets::SSN_STATIONS_DEFAULT.as_bytes().to_vec());
    assets::bytes_response(data, "application/json; charset=utf-8", 3600)
}

/// 內建向量圖層（資料目錄 geojson\ 沒有同名檔時使用；scripts/sync_web.py 自 Python 版同步）
const EMBED_GEOJSON: [&str; 3] = [
    "Taiwan-admin-ploygon.geojson",
    "openflights-airports.geojson",
    "submarine-cables.geojson",
];
const EMBED_TW_ADMIN: &str = "assets/geojson/Taiwan-admin-ploygon.geojson";

fn geojson_bytes(st: &AppState, name: &str) -> Option<Vec<u8>> {
    std::fs::read(st.cfg.user_geojson_dir().join(name))
        .ok()
        .or_else(|| EMBED_GEOJSON.contains(&name).then(|| assets::get(&format!("assets/geojson/{name}"))).flatten())
}

async fn api_user_geojson_list(State(st): St) -> Json<Value> {
    let dir = st.cfg.user_geojson_dir();
    let mut names: Vec<String> = std::fs::read_dir(&dir)
        .map(|rd| rd.filter_map(|e| e.ok().map(|e| e.file_name().to_string_lossy().into_owned())).collect())
        .unwrap_or_else(|_| Vec::new());
    names.retain(|n| n.ends_with(".geojson"));
    for e in EMBED_GEOJSON {
        if !names.iter().any(|n| n == e) {
            names.push(e.to_string());
        }
    }
    names.sort();
    let items: Vec<Value> = names
        .iter()
        .map(|name| {
            let bytes = geojson_bytes(&st, name);
            let size = bytes.as_ref().map(|b| b.len()).unwrap_or(0);
            let mut m = json!({"name": name, "size_kb": round_to(size as f64 / 1024.0, 1)});
            match bytes.and_then(|b| {
                let b = b.strip_prefix(b"\xef\xbb\xbf").map(<[u8]>::to_vec).unwrap_or(b);
                serde_json::from_slice::<Value>(&b).ok()
            }) {
                Some(v) => {
                    m["features"] = json!(v
                        .get("features")
                        .and_then(Value::as_array)
                        .map(Vec::len)
                        .unwrap_or(0))
                }
                None => m["error"] = json!("解析失敗"),
            }
            m
        })
        .collect();
    Json(Value::Array(items))
}

async fn api_user_geojson_file(State(st): St, Path(name): Path<String>) -> Resp {
    if name.contains(['/', '\\']) || name.contains("..") || !name.ends_with(".geojson") {
        return assets::text(StatusCode::BAD_REQUEST, "無效檔名");
    }
    match geojson_bytes(&st, &name) {
        Some(b) => assets::bytes_response(b, "application/json; charset=utf-8", 300),
        None => assets::text(StatusCode::NOT_FOUND, format!("找不到圖層檔: {name}")),
    }
}

// ── 使用者自訂資料 / NORAD 監測 ──────────────────────────────────────────────

fn sat_info_json(idx: &SatIndex, nid: u32) -> Map<String, Value> {
    let s = idx.sats.get(&nid);
    let v = json!({
        "norad_id": nid,
        "name": s.map(|s| s.name.clone()).unwrap_or_else(|| format!("NORAD-{nid}")),
        "name_zh": s.map(|s| s.name_zh.as_str()).unwrap_or(""),
        "country": s.map(|s| s.country.as_str()).unwrap_or("不明"),
        "purpose": s.map(|s| s.purpose.as_str()).unwrap_or("—"),
        "era": s.map(|s| s.era.as_str()).unwrap_or("不明"),
        "constellation": s.map(|s| s.constellation_or_dash()).unwrap_or("—"),
        "operator": s.map(|s| s.operator.as_str()).unwrap_or(""),
        "notes": s.map(|s| s.notes.as_str()).unwrap_or(""),
        "user_defined": s.map(|s| s.user_defined).unwrap_or(false),
        "in_index": s.is_some(),
    });
    match v {
        Value::Object(m) => m,
        _ => unreachable!(),
    }
}

async fn api_user_tles(State(st): St) -> Json<Value> {
    let tles = userdata::load_user_tles(&st.cfg.user_tle_dir());
    let idx = st.index();
    let nids: Vec<u32> = tles.keys().copied().collect();
    let pos = propagate_many(&idx, &nids);
    let sats: Vec<Value> = tles
        .iter()
        .zip(pos)
        .map(|((nid, t), p)| {
            let mut m = sat_info_json(&idx, *nid);
            m.insert("source_file".into(), json!(t.source_file));
            m.insert("tle_name".into(), json!(t.name));
            if let Some(p) = p {
                put_llh(&mut m, p);
            }
            Value::Object(m)
        })
        .collect();
    Json(json!({"count": sats.len(), "satellites": sats, "timestamp": now_iso()}))
}

async fn api_user_catalogue(State(st): St) -> Json<Value> {
    let rows: Vec<Value> = userdata::load_user_catalogue(&st.cfg.user_catalogue_dir())
        .into_iter()
        .map(|(nid, row)| {
            let mut m: Map<String, Value> = row.into_iter().map(|(k, v)| (k, json!(v))).collect();
            m.insert("norad_id".into(), json!(nid));
            Value::Object(m)
        })
        .collect();
    Json(json!({"count": rows.len(), "rows": rows}))
}

async fn api_tracking_list(State(st): St) -> Json<Value> {
    let idx = st.index();
    let items: Vec<Value> = userdata::load_tracking_list(&st.cfg.user_tracking_dir())
        .into_iter()
        .map(|e| {
            let mut m = match serde_json::to_value(&e) {
                Ok(Value::Object(m)) => m,
                _ => Map::new(),
            };
            m.extend(sat_info_json(&idx, e.norad_id));
            if e.alias.is_empty() {
                m.insert("alias".into(), m["name"].clone());
            } else {
                m.insert("alias".into(), json!(e.alias));
            }
            // CSV notes 優先（sat_info_json 的 notes 來自目錄）
            if !e.notes.is_empty() {
                m.insert("notes".into(), json!(e.notes));
            }
            Value::Object(m)
        })
        .collect();
    let enabled = items.iter().filter(|i| i["enabled"] == json!(true)).count();
    Json(json!({"count": items.len(), "enabled": enabled, "items": items, "timestamp": now_iso()}))
}

async fn api_tracking_positions(State(st): St, Query(q): Q) -> Json<Value> {
    let tracking: HashMap<u32, userdata::TrackEntry> =
        userdata::load_tracking_list(&st.cfg.user_tracking_dir())
            .into_iter()
            .map(|e| (e.norad_id, e))
            .collect();
    let ids_param = q.get("ids").map(|s| s.trim()).unwrap_or("");
    let mut nids: Vec<u32> = if !ids_param.is_empty() {
        let mut v = Vec::new();
        for tok in ids_param.split(',') {
            if let Ok(n) = tok.trim().parse::<u32>() {
                if !v.contains(&n) {
                    v.push(n);
                }
            }
        }
        v
    } else {
        let mut v: Vec<_> = tracking.values().filter(|e| e.enabled).collect();
        v.sort_by_key(|e| e.norad_id);
        v.into_iter().map(|e| e.norad_id).collect()
    };
    nids.truncate(50);
    let idx = st.index();
    let pos = propagate_many(&idx, &nids);
    let results: Vec<Value> = nids
        .iter()
        .zip(pos)
        .map(|(nid, p)| {
            let mut m = sat_info_json(&idx, *nid);
            let meta = tracking.get(nid);
            let alias = meta
                .filter(|e| !e.alias.is_empty())
                .map(|e| json!(e.alias))
                .unwrap_or_else(|| m["name"].clone());
            m.insert("alias".into(), alias);
            m.insert(
                "color".into(),
                json!(meta.map(|e| e.color.as_str()).unwrap_or("")),
            );
            m.insert(
                "priority".into(),
                json!(meta.map(|e| e.priority.as_str()).unwrap_or("medium")),
            );
            m.insert(
                "priority_label".into(),
                json!(meta.map(|e| e.priority_label.as_str()).unwrap_or("中")),
            );
            if let Some(e) = meta.filter(|e| !e.notes.is_empty()) {
                m.insert("notes".into(), json!(e.notes));
            }
            match p {
                Some(p) => {
                    m.insert("ok".into(), json!(true));
                    put_llh(&mut m, p);
                }
                None => {
                    m.insert("ok".into(), json!(false));
                    let why = if idx.sats.contains_key(nid) {
                        "SGP4 傳播失敗"
                    } else {
                        "不在索引中"
                    };
                    m.insert("error".into(), json!(why));
                }
            }
            Value::Object(m)
        })
        .collect();
    let ok = results.iter().filter(|r| r["ok"] == json!(true)).count();
    Json(json!({"count": results.len(), "ok_count": ok, "satellites": results, "timestamp": now_iso()}))
}

async fn api_admin_reload(State(st): St) -> Resp {
    blocking(move || {
        let summary = st.reload_all();
        let n = st.index().sats.len();
        Json(json!({"ok": true, "classification": summary, "satellites": n})).into_response()
    })
    .await
}
