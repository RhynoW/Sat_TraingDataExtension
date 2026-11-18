//! `/orbit`（軌道要素歷史：Spiral Polar、SMA 圓形圖、雙星比較）與 `/track`（單顆衛星 2D 地面軌跡）頁，
//! 以及 `/api/orbit/history`（Python 版 scenario04/api/orbit_history.py 的移植）。
//!
//! 與 Python 版的差異：只讀本機資料庫的 raw_tle_archive（每日取最後一筆）。
//! Python 版在覆蓋不足時會用 Space-Track 帳密向 gp_history 補抓並寫入 orbit_cache.duckdb；
//! 單機版會發給使用者，不內含帳密，所以不補抓，覆蓋率低時在 note 說明。
//! 環境變數 `ORBIT_HISTORY_DB` 可指定另一個（例如完整歷史的）DuckDB。

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{Duration, NaiveDate, Utc};
use serde_json::{json, Value};

use crate::assets;
use crate::index::open_ro;
use crate::state::AppState;
use crate::userdata;

const ELEMS: [&str; 4] = ["sma_km", "inclination_deg", "raan_deg", "argp_deg"];

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/orbit", get(|| async { page("templates/orbit.html") }))
        .route("/track", get(|| async { page("templates/track.html") }))
        .route("/orbit-tuner", get(|| async { page("templates/orbit_tuner.html") }))
        .route("/manual", get(|| async { page("templates/manual.html") }))
        .route("/api/orbit/history", get(history))
        .route("/api/orbit/limits", get(limits))
}

/// 本地資料保留範圍（多數衛星的保留天數中位數）；單機版不向 Space-Track 補抓。
/// /orbit 頁據此把預設區間改成本地範圍並提示使用者。
async fn limits(State(st): State<Arc<AppState>>) -> Json<Value> {
    let r = tokio::task::spawn_blocking(move || -> anyhow::Result<Option<(i64, String)>> {
        let Some(db) = history_db(&st) else { return Ok(None) };
        let con = open_ro(&db)?;
        let row = con.query_row(
            "SELECT CAST(median(d) AS BIGINT), (SELECT CAST(CAST(max(epoch_utc) AS DATE) AS VARCHAR)
                 FROM raw_tle_archive WHERE epoch_utc <= now())
             FROM (SELECT datediff('day', min(epoch_utc), max(epoch_utc)) + 1 AS d
                   FROM raw_tle_archive GROUP BY norad_id)",
            [],
            |r| Ok((r.get::<_, Option<i64>>(0)?, r.get::<_, Option<String>>(1)?)),
        )?;
        Ok(match row {
            (Some(d), Some(hi)) => Some((d, hi)),
            _ => None,
        })
    })
    .await;
    let mut out = json!({"spacetrack": false, "local_start": null, "local_end": null, "local_days": null});
    if let Ok(Ok(Some((days, hi)))) = r {
        if let Ok(end) = NaiveDate::parse_from_str(&hi, "%Y-%m-%d") {
            let start = end - Duration::days(days.max(1) - 1);
            out["local_start"] = json!(start.format("%Y-%m-%d").to_string());
            out["local_end"] = json!(hi);
            out["local_days"] = json!(days);
        }
    }
    Json(out)
}

pub fn page(path: &str) -> Html<String> {
    let raw = assets::get(path).unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

fn bad(code: StatusCode, msg: String) -> Response {
    (code, Json(json!({"error": msg}))).into_response()
}

fn history_db(st: &AppState) -> Option<PathBuf> {
    std::env::var_os("ORBIT_HISTORY_DB")
        .map(PathBuf::from)
        .filter(|p| p.is_file())
        .or_else(|| st.cfg.resolve_db())
}

type Daily = Vec<(String, [f64; 4])>;

fn daily_from_archive(st: &AppState, norad: u32, start: NaiveDate, end: NaiveDate) -> anyhow::Result<Daily> {
    let Some(db) = history_db(st) else { return Ok(Vec::new()) };
    let con = open_ro(&db)?;
    let sql = format!(
        "SELECT CAST(d AS VARCHAR), {cols} FROM (
            SELECT CAST(epoch_utc AS DATE) AS d, {cols}, row_number() OVER (
                PARTITION BY CAST(epoch_utc AS DATE) ORDER BY epoch_utc DESC) AS rn
            FROM raw_tle_archive
            WHERE norad_id = ? AND epoch_utc >= CAST(? AS TIMESTAMP) AND epoch_utc < CAST(? AS TIMESTAMP)
        ) WHERE rn = 1 ORDER BY d",
        cols = ELEMS.join(", ")
    );
    let mut stmt = con.prepare(&sql)?;
    let end1 = end + Duration::days(1);
    let rows = stmt.query_map(duckdb::params![norad as i64, start.to_string(), end1.to_string()], |r| {
        Ok((
            r.get::<_, String>(0)?,
            [
                r.get::<_, Option<f64>>(1)?.unwrap_or(f64::NAN),
                r.get::<_, Option<f64>>(2)?.unwrap_or(f64::NAN),
                r.get::<_, Option<f64>>(3)?.unwrap_or(f64::NAN),
                r.get::<_, Option<f64>>(4)?.unwrap_or(f64::NAN),
            ],
        ))
    })?;
    Ok(rows.filter_map(Result::ok).filter(|(_, v)| v.iter().all(|x| x.is_finite())).collect())
}

fn r(x: f64, d: i32) -> f64 {
    let p = 10f64.powi(d);
    (x * p).round() / p
}

async fn history(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(norad) = q.get("norad").and_then(|v| v.trim().parse::<u32>().ok()) else {
        return bad(StatusCode::BAD_REQUEST, "norad 參數必填且需為整數".into());
    };
    let pd = |k: &str| q.get(k).filter(|s| !s.is_empty()).map(|s| NaiveDate::parse_from_str(s, "%Y-%m-%d"));
    let end = match pd("end") {
        Some(Ok(d)) => d,
        Some(Err(_)) => return bad(StatusCode::BAD_REQUEST, "start/end 需為 YYYY-MM-DD".into()),
        None => Utc::now().date_naive(),
    };
    let start = match pd("start") {
        Some(Ok(d)) => d,
        Some(Err(_)) => return bad(StatusCode::BAD_REQUEST, "start/end 需為 YYYY-MM-DD".into()),
        None => end - Duration::days(365),
    };
    if start >= end {
        return bad(StatusCode::BAD_REQUEST, "start 需早於 end".into());
    }
    let st2 = st.clone();
    let daily = match tokio::task::spawn_blocking(move || daily_from_archive(&st2, norad, start, end)).await {
        Ok(Ok(d)) => d,
        Ok(Err(e)) => return bad(StatusCode::INTERNAL_SERVER_ERROR, format!("讀取資料庫失敗：{e:#}")),
        Err(_) => return bad(StatusCode::INTERNAL_SERVER_ERROR, "內部錯誤".into()),
    };
    let span = (end - start).num_days() + 1;
    let coverage = daily.len() as f64 / span as f64;
    let max_gap = daily
        .windows(2)
        .filter_map(|w| {
            let a = NaiveDate::parse_from_str(&w[0].0, "%Y-%m-%d").ok()?;
            let b = NaiveDate::parse_from_str(&w[1].0, "%Y-%m-%d").ok()?;
            Some((b - a).num_days())
        })
        .max()
        .unwrap_or(0);
    let note = (coverage < 0.5 || max_gap >= 7).then(|| {
        "Rust 單機版只用本機資料庫（多數衛星只有近期 TLE，白名單衛星才有完整歷史），不向 Space-Track 補抓".to_string()
    });
    if daily.is_empty() {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({"error": format!("NORAD {norad} 於 {start} ~ {end} 無 TLE 資料；{}", note.unwrap_or_default()),
                        "norad": norad})),
        )
            .into_response();
    }
    let dates: Vec<&str> = daily.iter().map(|d| d.0.as_str()).collect();
    let mut out = serde_json::Map::new();
    let mut stats = serde_json::Map::new();
    for (i, e) in ELEMS.iter().enumerate() {
        let v: Vec<f64> = daily.iter().map(|d| d.1[i]).collect();
        let n = v.len() as f64;
        let mean = v.iter().sum::<f64>() / n;
        let std = if v.len() > 1 { (v.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n).sqrt() } else { 0.0 };
        let (mn, mx) = v.iter().fold((f64::MAX, f64::MIN), |(a, b), &x| (a.min(x), b.max(x)));
        stats.insert((*e).into(), json!({"min": r(mn, 4), "max": r(mx, 4), "range": r(mx - mn, 4),
                                         "mean": r(mean, 4), "std": r(std, 5)}));
        out.insert((*e).into(), json!(v.iter().map(|x| r(*x, 6)).collect::<Vec<_>>()));
    }

    let idx = st.index();
    let info = idx.sats.get(&norad);
    let cat = userdata::load_user_catalogue(&st.cfg.user_catalogue_dir()).remove(&norad).unwrap_or_default();
    let name = info.map(|s| s.name.clone()).unwrap_or_else(|| format!("NORAD {norad}"));
    let intl_raw = info.and_then(|s| s.line1.get(9..17)).map(|s| s.trim().to_string()).unwrap_or_default();
    let intl = if intl_raw.len() >= 5 && intl_raw[..2].chars().all(|c| c.is_ascii_digit()) {
        let yy: u32 = intl_raw[..2].parse().unwrap_or(0);
        format!("{}{}-{}", if yy >= 57 { "19" } else { "20" }, &intl_raw[..2], &intl_raw[2..])
    } else {
        intl_raw
    };
    let g = |k: &str| cat.get(k).cloned().unwrap_or_default();
    let sat_info = json!({
        "name": name,
        "name_zh": info.map(|s| s.name_zh.clone()).unwrap_or_default(),
        "name_en": "",
        "country": info.map(|s| s.country.clone()).unwrap_or_default(),
        "purpose": info.map(|s| s.purpose.clone()).unwrap_or_default(),
        "constellation": info.and_then(|s| s.constellation.clone()).unwrap_or_default(),
        "era": info.map(|s| s.era.clone()).unwrap_or_default(),
        "operator": info.map(|s| s.operator.clone()).unwrap_or_default(),
        "launch_date": g("launch_date"),
        "intl_code": if g("intl_code").is_empty() { intl } else { g("intl_code") },
        "notes": info.map(|s| s.notes.clone()).unwrap_or_default(),
    });
    let mut v = json!({
        "norad": norad, "name": name, "info": sat_info,
        "start": start.to_string(), "end": end.to_string(),
        "n_days": dates.len(), "coverage": r(coverage, 3), "note": note,
        "dates": dates, "stats": Value::Object(stats),
    });
    for (k, val) in out {
        v[k] = val;
    }
    Json(v).into_response()
}
