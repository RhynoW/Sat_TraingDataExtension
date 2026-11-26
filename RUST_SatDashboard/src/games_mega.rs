//! 百萬顆衛星長期風險與管控：目錄背景族群 API（計算核心在前端 web/ext/games_mega.js，兩版共用）。
//!
//! GET /api/games/mega/background → 各 25 km 高度格（200–2000 km）的運作中衛星、失效衛星與火箭體、碎片顆數。
//! 分類依資料庫 SATCAT（未再入）：高度＝(遠地點＋近地點)/2；DEBRIS→碎片；PAYLOAD 發射 8 年內→運作中、其餘→失效；
//! ROCKET BODY、UNKNOWN→失效。SATCAT 沒有運作狀態欄位，8 年門檻是假設（頁面上有註明）。
//! 與線上版 api/games.py `mega_background()` 同一套規則（測試比對兩版輸出相同）。

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::{json, Value};

use crate::config::Config;
use crate::state::AppState;

pub const H0: f64 = 200.0;
pub const DH: f64 = 25.0;
pub const NB: usize = 72;
/// 酬載發射後幾天內視為運作中（8 年）
pub const ACTIVE_DAYS: i64 = 2922;

/// （高度格, 類別）；類別 0 運作中、1 失效、2 碎片；高度超出 200–2000 km 或資料不足回傳 None
pub fn classify(object_type: &str, launch: &str, apogee: Option<f64>, perigee: Option<f64>, cutoff: &str) -> Option<(usize, usize)> {
    let alt = (apogee? + perigee?) / 2.0;
    if !alt.is_finite() || alt < H0 || alt >= H0 + DH * NB as f64 {
        return None;
    }
    let bin = ((alt - H0) / DH).floor() as usize;
    let kind = match object_type.trim().to_ascii_uppercase().as_str() {
        "DEBRIS" => 2,
        "PAYLOAD" => {
            if !launch.trim().is_empty() && launch.trim() >= cutoff {
                0
            } else {
                1
            }
        }
        _ => 1,
    };
    Some((bin, kind))
}

pub fn background(cfg: &Config, cutoff: &str) -> anyhow::Result<Value> {
    let db = cfg.resolve_db().ok_or_else(|| anyhow::anyhow!("找不到資料庫"))?;
    let con = crate::index::open_ro(&db)?;
    let mut counts = [[0u64; NB]; 3];
    let mut total = 0u64;
    let mut st = con.prepare("SELECT coalesce(object_type, ''), coalesce(launch, ''), apogee, perigee FROM satcat WHERE coalesce(decay, '') = ''")?;
    let rows = st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, Option<f64>>(2)?, r.get::<_, Option<f64>>(3)?)))?;
    for row in rows.flatten() {
        if let Some((b, k)) = classify(&row.0, &row.1, row.2, row.3, cutoff) {
            counts[k][b] += 1;
            total += 1;
        }
    }
    let source = con
        .query_row("SELECT coalesce(source, '') || '，' || coalesce(fetched_at, '') FROM satcat_meta LIMIT 1", [], |r| r.get::<_, String>(0))
        .unwrap_or_else(|_| "SATCAT".into());
    Ok(json!({
        "h0": H0, "dh": DH, "n": NB, "cutoff": cutoff,
        "active": counts[0].to_vec(), "derelict": counts[1].to_vec(), "debris": counts[2].to_vec(),
        "total": total, "source": format!("SATCAT {source}"),
        "rule": "高度＝(遠地點＋近地點)/2；DEBRIS→碎片；PAYLOAD 發射 8 年內→運作中、其餘→失效；ROCKET BODY、UNKNOWN→失效",
    }))
}

pub fn default_cutoff() -> String {
    (chrono::Utc::now().date_naive() - chrono::Duration::days(ACTIVE_DAYS)).format("%Y-%m-%d").to_string()
}

pub async fn background_api(State(st): State<Arc<AppState>>) -> Response {
    let cfg = st.cfg.clone();
    match tokio::task::spawn_blocking(move || background(&cfg, &default_cutoff())).await {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => (StatusCode::SERVICE_UNAVAILABLE, Json(json!({"error": format!("{e:#}")}))).into_response(),
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "計算失敗"}))).into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_rules() {
        let c = "2018-11-26";
        assert_eq!(classify("PAYLOAD", "2024-01-01", Some(560.0), Some(540.0), c), Some((14, 0)), "550 km → 第 14 格、運作中");
        assert_eq!(classify("PAYLOAD", "2010-01-01", Some(560.0), Some(540.0), c), Some((14, 1)), "舊酬載 → 失效");
        assert_eq!(classify("PAYLOAD", "", Some(560.0), Some(540.0), c), Some((14, 1)), "無發射日 → 失效");
        assert_eq!(classify("DEBRIS", "2024-01-01", Some(800.0), Some(800.0), c), Some((24, 2)));
        assert_eq!(classify("ROCKET BODY", "2024-01-01", Some(900.0), Some(880.0), c), Some((27, 1)));
        assert_eq!(classify("UNKNOWN", "", Some(200.0), Some(200.0), c), Some((0, 1)), "下界含 200 km");
        assert_eq!(classify("PAYLOAD", "2024-01-01", Some(36000.0), Some(35000.0), c), None, "GEO 不在範圍");
        assert_eq!(classify("PAYLOAD", "2024-01-01", Some(2000.0), Some(2000.0), c), None, "上界不含 2000 km");
        assert_eq!(classify("PAYLOAD", "2024-01-01", None, Some(500.0), c), None);
    }
}
