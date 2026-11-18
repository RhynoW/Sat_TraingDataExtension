//! 離軌 Starlink 再入預測之背景批次——Python 版 services/deorbit_forecast.py 的移植。
//!
//! Python 版於子程序每 6 小時重算清單前 100 顆，寫入 DB_DIR/deorbit_forecast.json；API 只讀快取。
//! 單機版沒有啟動掛勾（不改 main.rs），改為第一次呼叫離軌相關 API 時啟動背景執行緒；
//! 快取檔寫在 <data>\DB\deorbit_forecast.json（不寫進可能與 Python 版共用的資料庫目錄）。

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration as StdDuration, Instant};

use chrono::{DateTime, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::{json, Map, Value};

use super::census;
use super::common::{self, py_iso_secs, py_round};
use super::segmented::{self, PredictOpts};
use crate::config::RAW_TABLE;
use crate::index::open_ro;
use crate::state::AppState;

const INTERVAL_S: i64 = 6 * 3600;
const CHECK_S: u64 = 1800;
const TLE_LOOKBACK_DAYS: i64 = 12;
const LIST_LIMIT: usize = 100;
const WIDEN_FRAC: f64 = 0.25;
pub const METHOD: &str = "segmented_ma_v1（Remis 2026 分段 M/A 校準；兩體+J2–J4+NRLMSISE-00，RK4）";
const SW_ALL_DATASET_URL: &str = "https://huggingface.co/datasets/RhynoWu/satdashboard-db/resolve/main/SW-All.csv";

fn opts() -> PredictOpts {
    PredictOpts { n_segments: 4, max_days: 10.0, stop_alt_km: 80.0, verify: false }
}

fn cache_file(st: &AppState) -> PathBuf {
    st.cfg.home.join("DB").join("deorbit_forecast.json")
}

/// SW-All.csv 候選位置：資料庫目錄 → 資料目錄 DB\
fn sw_candidates(st: &AppState) -> Vec<PathBuf> {
    let mut v = vec![common::db_dir(&st.cfg).join("SW-All.csv"), st.cfg.home.join("DB").join("SW-All.csv")];
    v.dedup();
    v
}

static SW_FAIL_AT: Lazy<Mutex<Option<Instant>>> = Lazy::new(|| Mutex::new(None));

/// 確保 SW-All.csv 存在；缺檔時自 Dataset 下載一次（失敗後 1 小時內不重試）。同 Python ensure_space_weather。
pub async fn ensure_space_weather(st: &AppState) -> Option<PathBuf> {
    if let Some(p) = segmented::sw_default_path(&sw_candidates(st)) {
        return Some(p);
    }
    if SW_FAIL_AT.lock().is_some_and(|t| t.elapsed() < StdDuration::from_secs(3600)) {
        return None;
    }
    let dest = st.cfg.home.join("DB").join("SW-All.csv");
    let r = async {
        let client = reqwest::Client::builder()
            .connect_timeout(StdDuration::from_secs(10))
            .timeout(StdDuration::from_secs(120))
            .build()
            .map_err(|e| e.to_string())?;
        let text = client
            .get(SW_ALL_DATASET_URL)
            .send()
            .await
            .and_then(|r| r.error_for_status())
            .map_err(|e| e.to_string())?
            .text()
            .await
            .map_err(|e| e.to_string())?;
        if !text.starts_with("DATE,") {
            return Err("SW-All.csv 內容格式不符".to_string());
        }
        if let Some(d) = dest.parent() {
            std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        let tmp = dest.with_extension("part");
        std::fs::write(&tmp, text).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, &dest).map_err(|e| e.to_string())?;
        Ok(())
    }
    .await;
    match r {
        Ok(()) => {
            tracing::warn!("太空天氣檔自 Dataset 下載完成：{}", dest.display());
            Some(dest)
        }
        Err(e) => {
            *SW_FAIL_AT.lock() = Some(Instant::now());
            tracing::error!("太空天氣檔下載失敗：{e}");
            None
        }
    }
}

fn iso_min(unix: f64) -> String {
    DateTime::from_timestamp(unix.floor() as i64, 0)
        .unwrap_or_default()
        .format("%Y-%m-%dT%H:%MZ")
        .to_string()
}

/// 區間取「彈道係數範圍」與「±frac × 距最後 TLE 之剩餘時數」兩者較寬者
fn widen_window(mut res: Value) -> Value {
    let (Some(tn), Some(hrs)) = (res["reentry_unix"].as_f64(), res["hours_from_last_tle"].as_f64()) else { return res };
    let pad = WIDEN_FRAC * hrs * 3600.0;
    let te2 = res["early_unix"].as_f64().unwrap_or(tn).min(tn - pad);
    let tl2 = res["late_unix"].as_f64().unwrap_or(tn).max(tn + pad);
    res["window_early_utc"] = json!(iso_min(te2));
    res["window_late_utc"] = json!(iso_min(tl2));
    res["early_unix"] = json!(te2);
    res["late_unix"] = json!(tl2);
    res["window_rule"] = json!(format!("max(B 範圍, ±{}% × 剩餘時數)", (WIDEN_FRAC * 100.0) as i64));
    res
}

fn recent_rows(con: &duckdb::Connection, norad: u32) -> anyhow::Result<Vec<(String, String)>> {
    let now = common::now_sql();
    let mut stmt = con.prepare(&format!(
        "SELECT line1, line2 FROM {RAW_TABLE}
         WHERE norad_id = ? AND line1 IS NOT NULL AND line2 IS NOT NULL
           AND epoch_utc <= {now}
           AND epoch_utc >= (SELECT max(epoch_utc) FROM {RAW_TABLE}
                             WHERE norad_id = ? AND epoch_utc <= {now}) - INTERVAL {TLE_LOOKBACK_DAYS} DAY
         ORDER BY epoch_utc"
    ))?;
    let rows = stmt
        .query_map([norad as i64, norad as i64], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// 單顆即時計算（完整結果，含逐段細節與 stats 以外之全部欄位）
pub fn forecast_norad(st: &AppState, norad: u32, con: Option<&duckdb::Connection>) -> Value {
    let owned;
    let con = match con {
        Some(c) => c,
        None => {
            let Some(db) = st.cfg.resolve_db() else { return json!({"error": "資料庫不存在"}) };
            match open_ro(&db) {
                Ok(c) => {
                    owned = c;
                    &owned
                }
                Err(e) => return json!({"error": format!("{e:#}")}),
            }
        }
    };
    let rows = match recent_rows(con, norad) {
        Ok(r) => r,
        Err(e) => return json!({"error": format!("{e:#}")}),
    };
    if rows.len() < 2 {
        return json!({"error": format!("NORAD {norad} 近 {TLE_LOOKBACK_DAYS} 天可用 TLE 少於 2 筆")});
    }
    let sw = segmented::sw_load(segmented::sw_default_path(&sw_candidates(st)));
    let res = segmented::predict_reentry(&rows, &sw, &opts());
    if res.get("error").is_some() {
        tracing::warn!("分段校準 {norad} 失敗：{}", res["error"]);
        return json!({"error": res["error"].clone()});
    }
    widen_window(res)
}

/// 清單用精簡欄位
fn compact(res: &Value) -> Value {
    if let Some(e) = res.get("error") {
        return json!({"error": e});
    }
    let g = |k: &str| res.get(k).cloned().unwrap_or(Value::Null);
    let segs: Vec<Value> = res["segments"]
        .as_array()
        .map(|a| {
            a.iter()
                .map(|s| {
                    let t = s.get("t_end").filter(|v| v.as_str().is_some_and(|x| !x.is_empty())).or(s.get("t_start"));
                    json!({"t": t.cloned().unwrap_or(Value::Null), "B": s.get("B").cloned().unwrap_or(Value::Null),
                           "flag": s.get("thrust_flag").cloned().unwrap_or(Value::Null)})
                })
                .collect()
        })
        .unwrap_or_default();
    json!({
        "reentry_utc": g("reentry_utc"),
        "window_early_utc": g("window_early_utc"),
        "window_late_utc": g("window_late_utc"),
        "hours_from_last_tle": g("hours_from_last_tle"),
        "beyond_horizon": g("beyond_horizon"),
        "reliable": g("reliable"),
        "thrust_suspected": g("thrust_suspected"),
        "latest_segment_flag": g("latest_segment_flag"),
        "tle_last_epoch": g("tle_last_epoch"),
        "A_eff_used_m2": g("A_eff_used_m2"),
        "segments": segs,
        "space_weather_persisted_from": res.get("space_weather").and_then(|s| s.get("persisted_from")).cloned().unwrap_or(Value::Null),
        "timing_s": res.get("timing_s").and_then(|s| s.get("total")).cloned().unwrap_or(Value::Null),
    })
}

pub fn compute_all(st: &AppState) -> Value {
    let t0 = Instant::now();
    let lst = census::list_deorbiting_starlinks(st, LIST_LIMIT);
    if let Some(e) = lst.get("error") {
        return json!({"error": e, "generated_at": common::py_iso_utc(&Utc::now())});
    }
    let mut out = Map::new();
    let con = st.cfg.resolve_db().and_then(|db| open_ro(&db).ok());
    for it in lst["items"].as_array().cloned().unwrap_or_default() {
        let Some(nid) = it["norad_id"].as_u64() else { continue };
        let r = forecast_norad(st, nid as u32, con.as_ref());
        out.insert(nid.to_string(), compact(&r));
    }
    json!({
        "generated_at": py_iso_secs(&Utc::now()),
        "elapsed_s": py_round(t0.elapsed().as_secs_f64(), 1),
        "n": out.len(),
        "method": METHOD,
        "window_rule": format!("max(B 範圍, ±{}% × 剩餘時數)", (WIDEN_FRAC * 100.0) as i64),
        "forecasts": out,
    })
}

// ── 背景服務 ────────────────────────────────────────────────────────────────
static DATA: Lazy<Mutex<Option<Arc<Value>>>> = Lazy::new(|| Mutex::new(None));
static RUNNING: AtomicBool = AtomicBool::new(false);

/// 目前快取（記憶體 → 快取檔）；尚無則 None
pub fn get(st: &AppState) -> Option<Arc<Value>> {
    if let Some(d) = DATA.lock().clone() {
        return Some(d);
    }
    let text = std::fs::read_to_string(cache_file(st)).ok()?;
    match serde_json::from_str::<Value>(&text) {
        Ok(v) => {
            let v = Arc::new(v);
            *DATA.lock() = Some(v.clone());
            Some(v)
        }
        Err(e) => {
            tracing::warn!("讀取離軌預測快取失敗：{e}");
            None
        }
    }
}

fn age_s(st: &AppState) -> Option<i64> {
    let d = get(st)?;
    let gen = DateTime::parse_from_rfc3339(d.get("generated_at")?.as_str()?).ok()?;
    Some((Utc::now() - gen.with_timezone(&Utc)).num_seconds())
}

fn refresh(st: &AppState) {
    let data = compute_all(st);
    if let Some(e) = data.get("error") {
        tracing::warn!("離軌預測批次失敗：{e}");
        return;
    }
    let path = cache_file(st);
    let write = || -> std::io::Result<()> {
        if let Some(d) = path.parent() {
            std::fs::create_dir_all(d)?;
        }
        let tmp = path.with_extension("part");
        std::fs::write(&tmp, serde_json::to_string(&data).unwrap_or_default())?;
        std::fs::rename(&tmp, &path)
    };
    if let Err(e) = write() {
        tracing::warn!("離軌預測快取寫入失敗（僅保留於記憶體）：{e}");
    }
    tracing::info!("離軌預測批次完成：{} 顆，{} s", data["n"], data["elapsed_s"]);
    *DATA.lock() = Some(Arc::new(data));
}

/// 啟動背景批次（只啟動一次）：快取不存在或超過 6 小時即重算，每 30 分鐘檢查一次
pub fn start(st: Arc<AppState>) {
    if RUNNING.swap(true, Ordering::SeqCst) {
        return;
    }
    let rt = tokio::runtime::Handle::try_current().ok();
    std::thread::Builder::new()
        .name("deorbit_forecast".into())
        .spawn(move || loop {
            if let Some(rt) = &rt {
                let _ = rt.block_on(ensure_space_weather(&st));
            }
            if age_s(&st).is_none_or(|a| a >= INTERVAL_S) {
                refresh(&st);
            }
            std::thread::sleep(StdDuration::from_secs(CHECK_S));
        })
        .ok();
}
