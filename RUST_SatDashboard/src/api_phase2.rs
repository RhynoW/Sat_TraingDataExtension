//! 第二階段路由：台北覆蓋（/taipei）、RPO 相對接近（/rpo）、全球海纜（/cable）。
//! 對應 Python api/passes.py、api/rpo.py、api/pages.py 之 cable。

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Instant;

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, Response, StatusCode};
use axum::response::{Html, IntoResponse};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Duration, DurationRound, Timelike, Utc};
use serde_json::{json, Value};

use crate::assets;
use crate::coverage::{self, MASK_DEG};
use crate::lunar;
use crate::physics::round_to;
use crate::rpo;
use crate::state::{AppState, Cached};

type St = State<Arc<AppState>>;
type Q = Query<HashMap<String, String>>;
type Resp = Response<Body>;

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/taipei", get(page_taipei))
        .route("/cable", get(page_cable))
        .route("/rpo", get(page_rpo))
        .route("/rpo/", get(page_rpo))
        .route("/rpo/cases", get(page_rpo_cases))
        .route("/api/taipei_coverage", get(api_taipei_coverage))
        .route("/api/taipei_coverage_at", get(api_taipei_coverage_at))
        .route("/api/taipei_passes", get(api_taipei_passes))
        .route("/api/taipei_passes_at", get(api_taipei_passes_at))
        .route("/api/taipei_sky", get(api_taipei_sky))
        .route("/api/taipei_lunar", get(api_taipei_lunar))
        .route("/api/rpo/presets", get(api_rpo_presets))
        .route("/api/rpo/{p}/{s}", get(api_rpo_scene))
        .route("/api/rpo/{p}/{s}/report.png", get(api_rpo_report))
}

// ── 工具 ─────────────────────────────────────────────────────────────────────

fn farg(q: &HashMap<String, String>, k: &str, d: f64, lo: f64, hi: f64) -> f64 {
    match q.get(k) {
        Some(v) => v.trim().parse::<f64>().map(|x| x.clamp(lo, hi)).unwrap_or(d),
        None => d,
    }
}

fn parse_ts(q: &HashMap<String, String>) -> DateTime<Utc> {
    let t = q.get("ts").and_then(|s| rpo::parse_time(&s.replace(' ', "+")));
    coverage::clamp_ts(t)
}

fn json_age(v: &Value, max_age: u64) -> Resp {
    let mut r = Json(v).into_response();
    r.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_str(&format!("public, max-age={max_age}")).unwrap(),
    );
    r
}

fn with_elapsed(mut v: Value, t0: Instant) -> Value {
    v["elapsed_sec"] = json!(round_to(t0.elapsed().as_secs_f64(), 2));
    v
}

async fn blocking<F>(f: F) -> Resp
where
    F: FnOnce() -> Resp + Send + 'static,
{
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|e| {
        tracing::error!("背景工作失敗：{e}");
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "伺服器內部錯誤"})),
        )
            .into_response()
    })
}

/// 依參數字串快取結果（TTL 秒）；快取超過 32 筆時清空
fn cached(st: &AppState, key: String, ttl: u64, f: impl FnOnce() -> Value) -> Arc<Value> {
    if let Some(c) = st.result_cache.lock().get(&key) {
        if c.at.elapsed().as_secs() < ttl {
            return c.value.clone();
        }
    }
    let v = Arc::new(f());
    let mut c = st.result_cache.lock();
    if c.len() > 32 {
        c.clear();
    }
    c.insert(
        key,
        Cached {
            at: Instant::now(),
            value: v.clone(),
        },
    );
    v
}

fn page(path: &str) -> Html<String> {
    let raw = assets::get(path).unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

// ── 頁面 ─────────────────────────────────────────────────────────────────────

async fn page_taipei() -> Html<String> {
    page("templates/taipei.html")
}
async fn page_cable() -> Html<String> {
    page("templates/cable.html")
}
async fn page_rpo_cases() -> Html<String> {
    page("templates/rpo_cases.html")
}

async fn page_rpo(Query(q): Q) -> Html<String> {
    let p = q
        .get("primary")
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(rpo::DEFAULT_PRIMARY);
    let s = q
        .get("secondary")
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(rpo::DEFAULT_SECONDARY);
    let v = rpo::valid_variant(p, s, q.get("variant").map(String::as_str)).unwrap_or_default();
    let Html(h) = page("templates/rpo3d.html");
    Html(
        h.replace("__PRIMARY__", &p.to_string())
            .replace("__SECONDARY__", &s.to_string())
            .replace("__VARIANT__", &v),
    )
}

// ── 台北覆蓋 ─────────────────────────────────────────────────────────────────

async fn api_taipei_coverage(State(st): St, Query(q): Q) -> Resp {
    let mask = farg(&q, "mask_deg", MASK_DEG, 0.0, 85.0);
    blocking(move || {
        let t0 = Instant::now();
        let idx = st.index();
        let cats = st.cats.read().clone();
        json_age(
            &with_elapsed(coverage::coverage(&idx, &cats, Utc::now(), mask, false), t0),
            60,
        )
    })
    .await
}

async fn api_taipei_coverage_at(State(st): St, Query(q): Q) -> Resp {
    let mask = farg(&q, "mask_deg", MASK_DEG, 0.0, 85.0);
    let ts = parse_ts(&q);
    blocking(move || {
        let t0 = Instant::now();
        let idx = st.index_for_time(ts);
        let cats = st.cats.read().clone();
        json_age(
            &with_elapsed(coverage::coverage(&idx, &cats, ts, mask, true), t0),
            60,
        )
    })
    .await
}

fn passes_params(q: &HashMap<String, String>) -> (f64, f64, f64) {
    (
        farg(q, "hours", 24.0, 1.0, 72.0),
        farg(q, "step_sec", 60.0, 10.0, 300.0),
        farg(q, "mask_deg", MASK_DEG, 0.0, 85.0),
    )
}

/// 即時過頂預報：Python 版以背景執行緒 + HTTP 202 輪詢；Rust 版平行運算夠快，直接回傳結果
async fn api_taipei_passes(State(st): St, Query(q): Q) -> Resp {
    let (hours, step, mask) = passes_params(&q);
    blocking(move || {
        // 以分鐘為單位快取 5 分鐘，避免重複整窗運算
        let key = format!("passes:{hours:.1}:{step:.0}:{mask:.1}");
        let v = cached(&st, key, 300, || {
            let t0 = Instant::now();
            let idx = st.index();
            let cats = st.cats.read().clone();
            with_elapsed(
                coverage::passes(&idx, &cats, Utc::now(), hours, step, mask, false),
                t0,
            )
        });
        json_age(&v, 300)
    })
    .await
}

async fn api_taipei_passes_at(State(st): St, Query(q): Q) -> Resp {
    let (hours, step, mask) = passes_params(&q);
    let ts = parse_ts(&q);
    blocking(move || {
        let t0 = Instant::now();
        let idx = st.index_for_time(ts);
        let cats = st.cats.read().clone();
        json_age(
            &with_elapsed(coverage::passes(&idx, &cats, ts, hours, step, mask, true), t0),
            300,
        )
    })
    .await
}

async fn api_taipei_sky(State(st): St, Query(q): Q) -> Resp {
    let ts = parse_ts(&q)
        .with_second(0)
        .and_then(|t| t.with_nanosecond(0))
        .unwrap();
    let hours = farg(&q, "hours", 2.0, 0.5, 6.0);
    let step = farg(&q, "step_sec", 20.0, 10.0, 120.0);
    let mask = farg(&q, "mask_deg", MASK_DEG, 0.0, 85.0);
    let min_el = farg(&q, "min_el", 10.0, 0.0, 85.0);
    let per_cat = farg(&q, "max_per_cat", 25.0, 1.0, 60.0) as usize;
    blocking(move || {
        let key = format!("sky:{}:{hours}:{step}:{mask}:{min_el}:{per_cat}", ts.to_rfc3339());
        let v = cached(&st, key, 300, || {
            let t0 = Instant::now();
            let idx = st.index_for_time(ts);
            let cats = st.cats.read().clone();
            with_elapsed(
                coverage::sky_passes(&idx, &cats, ts, hours, step, mask, min_el, per_cat),
                t0,
            )
        });
        json_age(&v, 120)
    })
    .await
}

async fn api_taipei_lunar(State(st): St, Query(q): Q) -> Resp {
    let ts = parse_ts(&q);
    let ts = ts.duration_trunc(Duration::minutes(10)).unwrap_or(ts);
    let hours = farg(&q, "hours", 24.0, 1.0, 48.0);
    let near = farg(&q, "near", 0.30, 0.0, 1.0);
    let mut cats_q: Vec<String> = q
        .get("cats")
        .map(|c| {
            c.split(',')
                .map(|x| x.trim().to_string())
                .filter(|x| !x.is_empty())
                .collect()
        })
        .unwrap_or_default();
    cats_q.sort();
    blocking(move || {
        let key = format!("lunar:{}:{hours}:{near}:{}", ts.to_rfc3339(), cats_q.join(","));
        let v = cached(&st, key, 900, || {
            let t0 = Instant::now();
            let idx = st.index_for_time(ts);
            let cats = st.cats.read().clone();
            let want: HashSet<String> = cats_q.into_iter().collect();
            let want = (!want.is_empty()).then_some(&want);
            with_elapsed(lunar::find_lunar_transits(&idx, &cats, ts, hours, near, want), t0)
        });
        json_age(&v, 300)
    })
    .await
}

// ── RPO ──────────────────────────────────────────────────────────────────────

async fn api_rpo_presets() -> Json<Value> {
    Json(rpo::presets_list())
}

/// 場景資料：記憶體快取 → 檔案快取（<data>\DB\rpo_scene_*.json，與 Python 版共用）→ 重算後落地
async fn api_rpo_scene(State(st): St, Path((p, s)): Path<(u32, u32)>, Query(q): Q) -> Resp {
    let variant = rpo::valid_variant(p, s, q.get("variant").map(String::as_str));
    blocking(move || {
        let key = (p, s, variant.clone());
        if let Some(v) = st.rpo_cache.lock().get(&key) {
            return Json(&**v).into_response();
        }
        let _g = st.rpo_lock.lock();
        if let Some(v) = st.rpo_cache.lock().get(&key) {
            return Json(&**v).into_response();
        }
        let cf = rpo::cache_file(&st.cfg, p, s, variant.as_deref());
        if let Some(v) = std::fs::read(&cf)
            .ok()
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        {
            let mut v = v;
            rpo::refresh_meta(&mut v, &rpo::preset_for(p, s, variant.as_deref()));
            let v = Arc::new(v);
            st.rpo_cache.lock().insert(key, v.clone());
            return Json(&*v).into_response();
        }
        let idx = st.index();
        let names = |n: u32| idx.sats.get(&n).map(|x| x.name.clone());
        match rpo::compute_scene(&st.cfg, p, s, variant.as_deref(), &names) {
            Ok(v) => {
                if let Err(e) = std::fs::create_dir_all(cf.parent().unwrap())
                    .and_then(|_| std::fs::write(&cf, serde_json::to_vec(&v).unwrap_or_default()))
                {
                    tracing::warn!("RPO 場景快取寫入失敗 {}：{e}", cf.display());
                }
                let v = Arc::new(v);
                st.rpo_cache.lock().insert(key, v.clone());
                Json(&*v).into_response()
            }
            Err(e) => {
                tracing::warn!("RPO 場景計算失敗 {p}×{s}：{e:#}");
                (StatusCode::BAD_REQUEST, Json(json!({"error": format!("{e:#}")}))).into_response()
            }
        }
    })
    .await
}

async fn api_rpo_report() -> Resp {
    (
        StatusCode::NOT_IMPLEMENTED,
        Html(assets::not_ported_html("/api/rpo/…/report.png（靜態影像報告）")),
    )
        .into_response()
}
