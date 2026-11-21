//! 太空小遊戲「碎片連鎖」：NASA 標準解體模型（EVOLVE 4.0／Johnson et al. 2001）＋ J2 長期項＋大氣阻力衰減
//! ＋以 KD-tree 快照估計碰撞機率的蒙地卡羅連鎖。
//!
//! - 解體：碎片數 N(>Lc) = 6·S·Lc^−1.6（爆炸）或 0.1·M^0.75·Lc^−1.71（碰撞），由使用者指定的碎片數反推 Lc；
//!   尺寸依冪律抽樣，面積質量比依模型的（雙）常態分布，Δv 依 log10(Δv) ~ N(μ(A/M), 0.4)，方向等向；
//!   質量縮放到總和等於母體質量，Δv 扣掉質量加權平均（動量守恆）。
//! - 傳播：克卜勒根數＋J2 長期漂移；碎片每一步依 A/M 與近地點大氣密度（Vallado 指數模型）降低半長軸，
//!   近地點 < 120 km 視為再入。目錄物件以 t0 的 SGP4 狀態轉成根數後同樣用 J2 長期項（不含阻力）。
//! - 碰撞：每一步取幾個快照，以碎片為查詢點找出 d 以內的物件；配對碰撞率 = 相對速度 ÷ (4d/3) × (R₁+R₂)²/d²，
//!   乘上時間步長與加速倍率得到期望值 λ，以 1−e^−λ 擲骰。撞上時以能量質量比 40 J/g 判斷是否完全解體，
//!   再用碰撞模型產生下一代碎片。
//! - 目錄物件依 TLE 的 B*（阻力項）換算面積質量比，同樣套用阻力衰減與再入（v0.1.15 起）。
//! - 緩解決策（actions）：清理任務、移除大型廢棄物、避碰機動，於指定時刻生效。
//! - 計算核心在 debris_engine.rs（線上版 debris_cli 共用）；本檔只負責 HTTP、快取與忙碌旗標。
//! - 資源保護：同時只算一個模擬（其餘回 429），相同參數 5 分鐘內直接回快取。

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use chrono::{DateTime, Utc};
use rayon::prelude::*;
use serde_json::{json, Value};

use crate::index::SatInfo;
use crate::debris_engine::{self as eng, BreakupReq, CatIn, R_EARTH_KM, V3};
use crate::state::AppState;

const CACHE_SECS: i64 = 300;
const CACHE_MAX: usize = 6;

static BUSY: AtomicBool = AtomicBool::new(false);
static CACHE: Mutex<Vec<(String, i64, Value)>> = Mutex::new(Vec::new());

fn norm(a: &V3) -> f64 { (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]).sqrt() }

fn bad(msg: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response()
}

/// 計算期間持有；結束（含 panic）時釋放忙碌旗標
struct BusyGuard;
impl Drop for BusyGuard {
    fn drop(&mut self) { BUSY.store(false, Ordering::SeqCst); }
}

fn sgp4_rv(s: &SatInfo, t: &DateTime<Utc>) -> Option<(V3, V3)> {
    let p = s.prop.as_ref()?;
    let ns = (t.naive_utc() - p.epoch).num_nanoseconds()?;
    let pr = p.constants.propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9)).ok()?;
    let r = pr.position;
    (r.iter().all(|v| v.is_finite()) && norm(&r) > R_EARTH_KM + 100.0).then_some((r, pr.velocity))
}

pub async fn breakup_api(State(st): State<Arc<AppState>>, Json(rq): Json<BreakupReq>) -> Response {
    let (years, accel, mass) = match eng::check(&rq) {
        Ok(x) => x,
        Err(m) => return bad(&m),
    };
    // 快取：同參數、同一份目錄（索引建立時間）5 分鐘內直接回傳；LRU（命中時移到最後）
    let key = format!("{}|{}|{}", eng::model_version(), st.index().built_at.timestamp(), serde_json::to_string(&rq).unwrap_or_default());
    let bucket = Utc::now().timestamp() / CACHE_SECS;
    if let Ok(mut c) = CACHE.lock() {
        if let Some(pos) = c.iter().position(|e| e.0 == key && e.1 == bucket) {
            let e = c.remove(pos);
            let mut v = e.2.clone();
            c.push(e);
            v["cached"] = json!(true);
            return Json(v).into_response();
        }
    }
    // 同時只算一個：區網多人或連點時避免把 CPU 打滿；附 Retry-After 讓前端倒數重試
    if BUSY.swap(true, Ordering::SeqCst) {
        return (StatusCode::TOO_MANY_REQUESTS, [(axum::http::header::RETRY_AFTER, "3")],
            Json(json!({"error": "另一個碎片模擬正在計算", "retry_after": 3}))).into_response();
    }
    let out = tokio::task::spawn_blocking(move || {
        let _g = BusyGuard;
        run(&st, &rq, years, accel, mass)
    })
    .await;
    match out {
        Ok(Ok(v)) => {
            if let Ok(mut c) = CACHE.lock() {
                c.retain(|e| e.1 == bucket && e.0 != key);   // 過期的分桶一併清掉
                if c.len() >= CACHE_MAX { c.remove(0); }
                c.push((key, bucket, v.clone()));
            }
            Json(v).into_response()
        }
        Ok(Err(msg)) => bad(&msg),
        Err(_) => { BUSY.store(false, Ordering::SeqCst); bad("計算失敗") }
    }
}

fn run(st: &Arc<AppState>, rq: &BreakupReq, years: f64, accel: f64, mass: f64) -> Result<Value, String> {
    let idx = st.index();
    let t0 = eng::resolve_t0(rq, Utc::now())?;
    let parent = if let Some(o) = &rq.orbit {
        eng::custom_parent(o)
    } else {
        let p = idx.sats.get(&rq.norad).ok_or("目錄中找不到這個 NORAD 編號")?;
        let (r, v) = sgp4_rv(p, &t0).ok_or("這顆衛星目前無法傳播（TLE 失效或已再入）")?;
        eng::ParentIn { r, v, name: p.name.clone(), custom: false, norad: rq.norad }
    };
    let sats: Vec<&SatInfo> = idx.sats.values().filter(|s| s.prop.is_some()).collect();
    let cats: Vec<CatIn> = sats
        .par_iter()
        .filter_map(|s| sgp4_rv(s, &t0).map(|rv| CatIn { norad: s.norad_id, name: s.name.clone(), purpose: s.purpose.clone(), line1: s.line1.clone(), rv }))
        .collect();
    let v = eng::run(rq, years, accel, mass, t0, &parent, &cats)?;
    let sm = &v["summary"];
    tracing::info!(
        "碎片連鎖：母體 {} 碎片 {} {} 年 ×{} 決策 {} → 碎片 {}{} 碰撞 {} 期末 {} 計算 {:.1} 秒",
        parent.name, rq.n_frag, years, accel, rq.actions.len(), sm["fragments_total"],
        if sm["capped"].as_bool() == Some(true) { "（達上限）" } else { "" },
        sm["collisions"], sm["alive_end"], v["elapsed_s"].as_f64().unwrap_or(0.0)
    );
    Ok(v)
}
