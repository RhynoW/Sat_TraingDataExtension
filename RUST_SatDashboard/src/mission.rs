//! 衛星任務規劃：地面站接收衛星下行（Downlink）之過頂預報。
//!
//! 預設情境：國立中央大學太空及遙測研究中心（中壢）接收 Vantor（原 Maxar）光學衛星星系，
//! 仰角遮罩 15°。過頂之 AOS / LOS 以二分法精算至 0.1 s、TCA 精算至 1 s；
//! 過頂軌跡自 AOS 起每 30 s 輸出一個時間標記點（方位／仰角／斜距／星下點）。
//! 每次過頂另附 TCA 時刻地面站的太陽仰角 `sun_el`；`night` = 太陽在地平線下（sun_el < 0°），頁面預設不顯示夜間過頂。

use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use rayon::prelude::*;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::assets;
use crate::index::SatIndex;
use crate::physics::{eci_to_llh, gmst_rad, round_to, Observer, Propagator};
use crate::state::AppState;

pub struct Station {
    pub id: &'static str,
    pub name: &'static str,
    pub lat: f64,
    pub lon: f64,
    pub h_km: f64,
    pub note: &'static str,
}

pub const STATIONS: &[Station] = &[
    Station {
        id: "ncu_csrsr",
        name: "國立中央大學 太空及遙測研究中心（中壢）",
        lat: 24.9683,
        lon: 121.1950,
        h_km: 0.14,
        note: "校區近似坐標；實際天線位置請以中心公告為準，可於頁面修改",
    },
    Station {
        id: "taipei",
        name: "台北（參考點）",
        lat: 25.0330,
        lon: 121.5654,
        h_km: 0.01,
        note: "與台北覆蓋分析同一點",
    },
];

pub struct Constellation {
    pub id: &'static str,
    pub name: &'static str,
    pub note: &'static str,
    pub members: &'static [(u32, &'static str)],
}

pub const CONSTELLATIONS: &[Constellation] = &[Constellation {
    id: "vantor",
    name: "Vantor（原 Maxar Intelligence）光學衛星星系",
    note: "2025 年 Maxar Intelligence 更名 Vantor；WorldView-4 已於 2019 年失效，未列入",
    members: &[
        (40115, "WorldView-3"),
        (35946, "WorldView-2"),
        (32060, "WorldView-1"),
        (33331, "GeoEye-1"),
        (59625, "WorldView Legion 1"),
        (59626, "WorldView Legion 2"),
        (60452, "WorldView Legion 3"),
        (60453, "WorldView Legion 4"),
        (62900, "WorldView Legion 5"),
        (62901, "WorldView Legion 6"),
    ],
}];

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/mission", get(page))
        .route("/api/mission/config", get(config))
        .route("/api/mission/passes", get(passes))
        .route("/api/mission/schedule", get(schedule))
        .route("/api/mission/weather", get(weather))
        .route("/api/mission/cloud_track", get(cloud_track))
}

// ── 地面站雲量預報（MET Norway Locationforecast 2.0，CC BY 4.0）────────────────
// 前約 2.5 天每小時、之後每 6 小時；依回應的 Expires 快取（至少 30 分鐘），上游失敗時回傳上次的結果。
// 條款：https://api.met.no/doc/TermsOfService（需識別用 User-Agent、座標最多 4 位小數、遵守快取）
const MET_URL: &str = "https://api.met.no/weatherapi/locationforecast/2.0/complete";
/// compact 只有總雲量（沒有低／中／高雲），回應約小一半；軌跡兩側 1° 網格用這個
const MET_URL_COMPACT: &str = "https://api.met.no/weatherapi/locationforecast/2.0/compact";

static WX_CLIENT: once_cell::sync::Lazy<reqwest::Client> = once_cell::sync::Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .user_agent(concat!("SatDashboard-Rust/", env!("CARGO_PKG_VERSION"), " (ATRDC standalone ground-station planner)"))
        .build()
        .expect("reqwest client")
});

type WxCache = HashMap<String, (DateTime<Utc>, Value)>; // key → (到期時刻, 回應)
static WX_CACHE: once_cell::sync::Lazy<parking_lot::Mutex<WxCache>> =
    once_cell::sync::Lazy::new(|| parking_lot::Mutex::new(HashMap::new()));

/// 一個地點的預報（快取依 Expires；上游失敗時回傳上次的結果並標 stale）
async fn wx_series(lat: f64, lon: f64, alt_m: i64, compact: bool) -> Result<Value, String> {
    let key = format!("{}{lat:.4},{lon:.4},{alt_m}", if compact { "c:" } else { "" });
    let now = Utc::now();
    let cached = WX_CACHE.lock().get(&key).cloned();
    if let Some((exp, v)) = &cached {
        if *exp > now {
            return Ok(v.clone());
        }
    }
    let base = if compact { MET_URL_COMPACT } else { MET_URL };
    let url = format!("{base}?lat={lat:.4}&lon={lon:.4}&altitude={alt_m}");
    let fetched: anyhow::Result<(Value, DateTime<Utc>)> = async {
        let r = WX_CLIENT.get(&url).send().await?;
        if !r.status().is_success() {
            anyhow::bail!("MET Norway 回應 {}", r.status());
        }
        let exp = r
            .headers()
            .get(axum::http::header::EXPIRES)
            .and_then(|v| v.to_str().ok())
            .and_then(|s| DateTime::parse_from_rfc2822(s.replace("GMT", "+0000").as_str()).ok())
            .map(|t| t.with_timezone(&Utc))
            .unwrap_or(now)
            .max(now + Duration::minutes(30));
        Ok((serde_json::from_slice::<Value>(&r.bytes().await?)?, exp))
    }
    .await;
    match fetched {
        Ok((raw, exp)) => {
            let ts = raw["properties"]["timeseries"].as_array().cloned().unwrap_or_default();
            let mut series = Vec::new();
            for (i, t) in ts.iter().enumerate() {
                let Some(tt) = t["time"].as_str().and_then(|s| DateTime::parse_from_rfc3339(s).ok()) else { continue };
                if tt.with_timezone(&Utc) > now + Duration::days(4) {
                    break;
                }
                let next = ts.get(i + 1).and_then(|n| n["time"].as_str()).and_then(|s| DateTime::parse_from_rfc3339(s).ok());
                let step_h = next.map(|n| (n - tt).num_hours()).unwrap_or(1).max(1);
                let d = &t["data"]["instant"]["details"];
                let pr = t["data"]["next_1_hours"]["details"]["precipitation_amount"]
                    .as_f64()
                    .or_else(|| t["data"]["next_6_hours"]["details"]["precipitation_amount"].as_f64());
                series.push(json!([
                    tt.timestamp(),
                    d["cloud_area_fraction"].as_f64(),
                    d["cloud_area_fraction_low"].as_f64(),
                    d["cloud_area_fraction_medium"].as_f64(),
                    d["cloud_area_fraction_high"].as_f64(),
                    pr,
                    step_h
                ]));
            }
            let v = json!({
                "source": "MET Norway Locationforecast 2.0（CC BY 4.0）",
                "source_url": "https://api.met.no/",
                "updated_at": raw["properties"]["meta"]["updated_at"],
                "point": {"lat": lat, "lon": lon, "alt_m": alt_m},
                "fields": ["t_unix", "cloud_pct", "low_pct", "mid_pct", "high_pct", "precip_mm", "step_h"],
                "series": series,
                "stale": false,
            });
            WX_CACHE.lock().insert(key, (exp, v.clone()));
            Ok(v)
        }
        Err(e) => match cached {
            Some((_, mut v)) => {
                v["stale"] = json!(true);
                Ok(v)
            }
            None => Err(format!("無法取得雲量預報（需連網）：{e:#}")),
        },
    }
}

/// 單點預報（地面站或任一點）
async fn weather(Query(q): Query<HashMap<String, String>>) -> Response {
    let f = |k: &str, d: f64| q.get(k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(d);
    let (lat, lon) = (f("lat", STATIONS[0].lat).clamp(-90.0, 90.0), f("lon", STATIONS[0].lon).clamp(-180.0, 180.0));
    let alt_m = (f("h_km", STATIONS[0].h_km) * 1000.0).round().clamp(-500.0, 9000.0) as i64;
    match wx_series(lat, lon, alt_m, false).await {
        Ok(v) => Json(v).into_response(),
        Err(e) => (StatusCode::BAD_GATEWAY, Json(json!({"error": e}))).into_response(),
    }
}

/// 衛星正下方（星下點）雲量：pts = "t_unix,lat,lon;…"（最多 80 點）。
/// 星下點座標取到 0.1°（約 11 km，與全球預報網格同級），相同格點共用一次查詢；回傳每點在該時刻的預報（超出 4 天為 null）。
/// grid=1：地面軌跡兩側 1° 網格（頁面算好格點中心，最多 400 點），改用 compact 端點、8 個並行。
async fn cloud_track(Query(q): Query<HashMap<String, String>>) -> Response {
    let grid = q.get("grid").is_some_and(|v| v == "1");
    let (max_pts, par) = if grid { (400, 8) } else { (80, 6) };
    let pts: Vec<(i64, f64, f64)> = q
        .get("pts")
        .map(|s| {
            s.split(';')
                .filter_map(|p| {
                    let mut it = p.split(',');
                    let t = it.next()?.trim().parse::<i64>().ok()?;
                    let lat = it.next()?.trim().parse::<f64>().ok()?.clamp(-90.0, 90.0);
                    let lon = it.next()?.trim().parse::<f64>().ok()?.clamp(-180.0, 180.0);
                    Some((t, (lat * 10.0).round() / 10.0, (lon * 10.0).round() / 10.0))
                })
                .take(max_pts)
                .collect()
        })
        .unwrap_or_default();
    let mut cells: Vec<(f64, f64)> = pts.iter().map(|p| (p.1, p.2)).collect();
    cells.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    cells.dedup();
    let mut got: HashMap<String, Value> = HashMap::new();
    let mut err = None;
    for chunk in cells.chunks(par) {
        // 每批最多 6～8 個並行請求（MET Norway 條款：每個用戶端每秒 < 20 次）
        let mut set = tokio::task::JoinSet::new();
        for &(lat, lon) in chunk {
            set.spawn(async move { (lat, lon, wx_series(lat, lon, 0, grid).await) });
        }
        while let Some(Ok((lat, lon, r))) = set.join_next().await {
            match r {
                Ok(v) => {
                    got.insert(format!("{lat:.1},{lon:.1}"), v);
                }
                Err(e) => err = Some(e),
            }
        }
    }
    let mut updated = None;
    let mut stale = false;
    let out: Vec<Value> = pts
        .iter()
        .map(|&(t, lat, lon)| {
            let Some(v) = got.get(&format!("{lat:.1},{lon:.1}")) else { return Value::Null };
            updated = v["updated_at"].as_str().map(str::to_string).or(updated.take());
            stale |= v["stale"].as_bool().unwrap_or(false);
            let row = v["series"].as_array().and_then(|rows| {
                rows.iter().find(|r| {
                    let t0 = r[0].as_i64().unwrap_or(0);
                    let st = r[6].as_i64().unwrap_or(1);
                    t >= t0 && t < t0 + st * 3600
                })
            });
            match row {
                Some(r) => json!({"t": t, "lat": lat, "lon": lon, "cloud": r[1], "low": r[2], "mid": r[3], "high": r[4],
                                  "precip": r[5], "step_h": r[6]}),
                None => Value::Null,
            }
        })
        .collect();
    if out.iter().all(Value::is_null) {
        if let Some(e) = err {
            return (StatusCode::BAD_GATEWAY, Json(json!({"error": e}))).into_response();
        }
    }
    Json(json!({
        "source": "MET Norway Locationforecast 2.0（CC BY 4.0）",
        "updated_at": updated, "stale": stale, "points": out,
    }))
    .into_response()
}

async fn page() -> Html<String> {
    let raw = assets::get("ext/mission.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

fn iso(t: &DateTime<Utc>) -> String {
    t.to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn ms(t: &DateTime<Utc>, s: f64) -> DateTime<Utc> {
    *t + Duration::microseconds((s * 1e6).round() as i64)
}

async fn config(State(st): State<Arc<AppState>>) -> Json<Value> {
    let idx = st.index();
    let t = Utc::now();
    Json(json!({
        "stations": STATIONS.iter().map(|s| json!({
            "id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon, "h_km": s.h_km, "note": s.note,
        })).collect::<Vec<_>>(),
        "constellations": CONSTELLATIONS.iter().map(|c| json!({
            "id": c.id, "name": c.name, "note": c.note,
            "members": c.members.iter().map(|(n, label)| {
                let s = idx.sats.get(n);
                let llh = s.and_then(|s| s.prop.as_ref()).and_then(|p| p.llh(&t));
                json!({
                    "norad_id": n, "label": label,
                    "catalog_name": s.map(|s| s.name.clone()),
                    "in_index": s.is_some(),
                    "alt_km": llh.map(|l| round_to(l[2], 1)),
                    "tle_epoch": s.and_then(|s| s.prop.as_ref()).map(|p| p.epoch.and_utc().to_rfc3339()),
                })
            }).collect::<Vec<_>>(),
        })).collect::<Vec<_>>(),
        "default_mask_deg": 15.0,
        "mark_step_s": 30,
    }))
}

struct Params {
    obs: Observer,
    lat: f64,
    lon: f64,
    h_km: f64,
    mask: f64,
    start: DateTime<Utc>,
    hours: f64,
}

fn params(q: &HashMap<String, String>) -> Params {
    let f = |k: &str, d: f64, lo: f64, hi: f64| {
        q.get(k)
            .and_then(|v| v.parse::<f64>().ok())
            .map(|v| v.clamp(lo, hi))
            .unwrap_or(d)
    };
    let st = &STATIONS[0];
    let lat = f("lat", st.lat, -90.0, 90.0);
    let lon = f("lon", st.lon, -180.0, 180.0);
    let h_km = f("h_km", st.h_km, -0.5, 9.0);
    let now = Utc::now();
    let start = q
        .get("start")
        .and_then(|s| crate::rpo::parse_time(s))
        .map(|t| t.max(now - Duration::days(7)).min(now + Duration::days(14)))
        .unwrap_or(now);
    Params {
        obs: Observer::new(lat, lon, h_km),
        lat,
        lon,
        h_km,
        mask: f("mask", 15.0, 0.0, 85.0),
        start,
        hours: f("hours", 24.0, 1.0, 72.0),
    }
}

/// 單點站心幾何：(仰角, 方位, 斜距, [lat, lon, alt])
fn look(p: &Propagator, obs: &Observer, t: &DateTime<Utc>) -> Option<(f64, f64, f64, [f64; 3])> {
    let r = p.position(t)?;
    let g = gmst_rad(t);
    let (el, az, rng) = obs.elaz(&r, g);
    Some((el, az, rng, eci_to_llh(&r, g)))
}

fn el_at(p: &Propagator, obs: &Observer, t0: &DateTime<Utc>, s: f64) -> f64 {
    look(p, obs, &ms(t0, s)).map(|x| x.0).unwrap_or(-90.0)
}

/// 二分法求仰角穿越遮罩之時刻（a 端與 b 端分處遮罩兩側），精度 0.1 s
fn bisect(p: &Propagator, obs: &Observer, t0: &DateTime<Utc>, mut a: f64, mut b: f64, mask: f64) -> f64 {
    let above_a = el_at(p, obs, t0, a) >= mask;
    while b - a > 0.1 {
        let m = 0.5 * (a + b);
        if (el_at(p, obs, t0, m) >= mask) == above_a {
            a = m;
        } else {
            b = m;
        }
    }
    0.5 * (a + b)
}

struct Pass {
    aos: f64,
    los: f64,
    tca: f64,
    max_el: f64,
    clipped_start: bool,
    clipped_end: bool,
}

fn find_passes(p: &Propagator, prm: &Params) -> Vec<Pass> {
    const STEP: f64 = 10.0;
    let total = prm.hours * 3600.0;
    let n = (total / STEP) as usize;
    let els: Vec<f64> = (0..=n)
        .map(|i| el_at(p, &prm.obs, &prm.start, i as f64 * STEP))
        .collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i <= n {
        if els[i] < prm.mask {
            i += 1;
            continue;
        }
        let a = i;
        while i <= n && els[i] >= prm.mask {
            i += 1;
        }
        let b = i - 1;
        let aos = if a == 0 {
            0.0
        } else {
            bisect(
                p,
                &prm.obs,
                &prm.start,
                (a - 1) as f64 * STEP,
                a as f64 * STEP,
                prm.mask,
            )
        };
        let los = if b == n {
            n as f64 * STEP
        } else {
            bisect(
                p,
                &prm.obs,
                &prm.start,
                b as f64 * STEP,
                (b + 1) as f64 * STEP,
                prm.mask,
            )
        };
        // TCA：AOS–LOS 間每秒取樣取最大仰角
        let mut best = (aos, f64::MIN);
        let mut s = aos.ceil();
        while s <= los {
            let e = el_at(p, &prm.obs, &prm.start, s);
            if e > best.1 {
                best = (s, e);
            }
            s += 1.0;
        }
        if best.1 > f64::MIN {
            out.push(Pass {
                aos,
                los,
                tca: best.0,
                max_el: best.1,
                clipped_start: a == 0,
                clipped_end: b == n,
            });
        }
    }
    out
}

fn pass_json(p: &Propagator, prm: &Params, ps: &Pass, with_marks: bool) -> Value {
    let t0 = &prm.start;
    let pt = |s: f64| {
        let t = ms(t0, s);
        look(p, &prm.obs, &t).map(|(el, az, rng, llh)| {
            json!({
                "t": iso(&t),
                "az": round_to(az, 2), "el": round_to(el, 2), "range_km": round_to(rng, 1),
                "lat": round_to(llh[0], 4), "lon": round_to(llh[1], 4), "alt_km": round_to(llh[2], 2),
            })
        })
    };
    let aos = pt(ps.aos).unwrap_or(Value::Null);
    let los = pt(ps.los).unwrap_or(Value::Null);
    let tca = pt(ps.tca).unwrap_or(Value::Null);
    let sun_el = crate::lunar::sun_elevation(prm.lat, prm.lon, prm.h_km, &ms(t0, ps.tca));
    let mut v = json!({
        "aos": aos, "tca": tca, "los": los,
        "max_el": round_to(ps.max_el, 2),
        "duration_s": round_to(ps.los - ps.aos, 1),
        "sun_el": round_to(sun_el, 1), "night": sun_el < 0.0,
        "clipped_start": ps.clipped_start, "clipped_end": ps.clipped_end,
    });
    if with_marks {
        // 30 s 時間標記：AOS、其後每 30 s、LOS
        let mut marks = Vec::new();
        let mut s = ps.aos;
        while s < ps.los - 1.0 {
            if let Some(x) = pt(s) {
                marks.push(x);
            }
            s += 30.0;
        }
        if let Some(x) = pt(ps.los) {
            marks.push(x);
        }
        // 細軌跡（5 s）供天球圖與 3D 弧線平滑繪製
        let mut fine = Vec::new();
        let mut s = ps.aos;
        while s <= ps.los {
            if let Some((el, az, _, llh)) = look(p, &prm.obs, &ms(t0, s)) {
                fine.push(json!([
                    round_to(s - ps.aos, 1),
                    round_to(az, 2),
                    round_to(el, 2),
                    round_to(llh[0], 4),
                    round_to(llh[1], 4),
                    round_to(llh[2], 2)
                ]));
            }
            s += 5.0;
        }
        v["marks"] = json!(marks);
        v["track"] = json!(fine);
    }
    v
}

fn get_prop<'a>(idx: &'a SatIndex, norad: u32) -> Option<&'a Propagator> {
    idx.sats.get(&norad).and_then(|s| s.prop.as_ref())
}

/// 單顆衛星：過頂清單（含 30 s 標記）＋ 全時窗地面軌跡（30 s，含可接收旗標）
async fn passes(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Response {
    let Some(norad) = q.get("norad").and_then(|v| v.parse::<u32>().ok()) else {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "缺少 norad 參數"}))).into_response();
    };
    let prm = params(&q);
    tokio::task::spawn_blocking(move || {
        let t_calc = std::time::Instant::now();
        let idx = st.index();
        let Some(p) = get_prop(&idx, norad) else {
            return (
                StatusCode::NOT_FOUND,
                Json(json!({"error": format!("NORAD {norad} 不在索引中或無有效 TLE")})),
            )
                .into_response();
        };
        let name = idx.sats.get(&norad).map(|s| s.name.clone()).unwrap_or_default();
        let ps = find_passes(p, &prm);
        let total = prm.hours * 3600.0;
        let track: Vec<Value> = (0..=((total / 30.0) as usize))
            .filter_map(|i| {
                let s = i as f64 * 30.0;
                let (el, _, _, llh) = look(p, &prm.obs, &ms(&prm.start, s))?;
                Some(json!([
                    s as i64,
                    round_to(llh[1], 4),
                    round_to(llh[0], 4),
                    round_to(llh[2], 2),
                    el >= prm.mask
                ]))
            })
            .collect();
        let mean_alt = {
            let alts: Vec<f64> = track.iter().filter_map(|v| v[3].as_f64()).collect();
            if alts.is_empty() {
                500.0
            } else {
                alts.iter().sum::<f64>() / alts.len() as f64
            }
        };
        Json(json!({
            "satellite": {"norad_id": norad, "name": name,
                          "tle_epoch": p.epoch.and_utc().to_rfc3339(), "mean_alt_km": round_to(mean_alt, 1)},
            "station": {"lat": prm.lat, "lon": prm.lon, "h_km": prm.h_km},
            "mask_deg": prm.mask,
            "start": iso(&prm.start),
            "end": iso(&ms(&prm.start, total)),
            "mark_step_s": 30,
            "passes": ps.iter().map(|x| pass_json(p, &prm, x, true)).collect::<Vec<_>>(),
            "ground_track": track,
            "elapsed_sec": round_to(t_calc.elapsed().as_secs_f64(), 3),
        }))
        .into_response()
    })
    .await
    .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "內部錯誤").into_response())
}

/// 單次過頂所在的軌道段：以 TCA 為中心前後各 1/4 圈（裁切於時窗內）的星下點 [lon, lat, alt_km]，60 s 一點（含 AOS、TCA、LOS 三點）；
/// 頁面總覽只畫這些「通過地面站可接收圈」的軌道段，可用滑鼠點選
fn pass_arc(p: &Propagator, prm: &Params, ps: &Pass, line2: &str) -> Vec<Value> {
    let t0 = &prm.start;
    // TLE 第 2 行第 53–63 欄：平均運動（rev/day）；讀不到時當作約 100 分鐘一圈
    let rev_day = line2.get(52..63).and_then(|v| v.trim().parse::<f64>().ok()).filter(|v| *v > 0.5).unwrap_or(14.4);
    let quarter = 86400.0 / rev_day / 4.0;
    // 限制在選定時窗內（不畫到前一天或後一天）
    let (a, b) = ((ps.tca - quarter).max(0.0), (ps.tca + quarter).min(prm.hours * 3600.0));
    let mut ts: Vec<f64> = Vec::new();
    let mut s = a;
    while s < b {
        ts.push(s);
        s += 60.0;
    }
    ts.push(b);
    ts.extend([ps.aos, ps.tca, ps.los]);
    ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
    ts.dedup_by(|x, y| (*x - *y).abs() < 1.0);
    ts.iter()
        .filter_map(|&s| {
            let t = ms(t0, s);
            let r = p.position(&t)?;
            let llh = eci_to_llh(&r, gmst_rad(&t));
            Some(json!([round_to(llh[1], 3), round_to(llh[0], 3), round_to(llh[2], 1)]))
        })
        .collect()
}

/// 星系總覽：各成員過頂摘要（不含軌跡），供排程與衝突檢視
async fn schedule(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Response {
    let cid = q.get("constellation").cloned().unwrap_or_else(|| "vantor".into());
    let Some(c) = CONSTELLATIONS.iter().find(|c| c.id == cid) else {
        return (StatusCode::NOT_FOUND, Json(json!({"error": "未知星系"}))).into_response();
    };
    let prm = Arc::new(params(&q));
    tokio::task::spawn_blocking(move || {
        let idx = st.index();
        let sats: Vec<Value> = c
            .members
            .par_iter()
            .map(|(n, label)| {
                let Some(p) = get_prop(&idx, *n) else {
                    return json!({"norad_id": n, "label": label, "in_index": false, "passes": []});
                };
                let ps = find_passes(p, &prm);
                let line2 = idx.sats.get(n).map(|s| s.line2.as_str()).unwrap_or("");
                let passes: Vec<Value> = ps
                    .iter()
                    .map(|x| {
                        let mut v = pass_json(p, &prm, x, false);
                        v["arc"] = json!(pass_arc(p, &prm, x, line2));
                        v
                    })
                    .collect();
                json!({"norad_id": n, "label": label, "in_index": true, "passes": passes})
            })
            .collect();
        Json(json!({
            "constellation": c.id, "name": c.name,
            "station": {"lat": prm.lat, "lon": prm.lon, "h_km": prm.h_km},
            "mask_deg": prm.mask, "start": iso(&prm.start),
            "end": iso(&ms(&prm.start, prm.hours * 3600.0)),
            "satellites": sats,
        }))
        .into_response()
    })
    .await
    .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "內部錯誤").into_response())
}
