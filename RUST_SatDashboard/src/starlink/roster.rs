//! `/api/v3_flight14_roster`（Python 版 api/positions.py 之 api_v3_flight14_roster 與 physics/v3_meme.py）。
//! 位置優先用 DB 表 v3_meme_teme_samples（SpaceX MEME 72 h 預估，線性內插、不外推），
//! 涵蓋不到才退回索引中的 TLE；另與 CelesTrak 補充檔 SGP4 擬合比對 3D 位置差。

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration as StdDuration, Instant};

use chrono::{DateTime, NaiveDateTime, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::{json, Value};

use super::common::{self, eci_to_llh_py, py_round};
use crate::index::open_ro;
use crate::physics::Propagator;
use crate::state::AppState;
use crate::userdata;

pub const V3_FLIGHT14_NORAD_IDS: std::ops::Range<u32> = 339974..340000;
const V3_FLIGHT14_INTDES: &str = "2026-225";
const MEME_TABLE: &str = "v3_meme_teme_samples";

struct Samples {
    t: Vec<f64>,
    xyz: Vec<[f64; 3]>,
}

type SampleMap = Arc<HashMap<u32, Samples>>;
static MEME_CACHE: Lazy<Mutex<Option<(Instant, SampleMap)>>> = Lazy::new(|| Mutex::new(None));

fn load_samples(st: &AppState) -> SampleMap {
    if let Some((at, m)) = MEME_CACHE.lock().as_ref() {
        if at.elapsed() < StdDuration::from_secs(300) {
            return m.clone();
        }
    }
    let mut by_id: HashMap<u32, Samples> = HashMap::new();
    if let Some(db) = st.cfg.resolve_db() {
        let r = (|| -> anyhow::Result<()> {
            let con = open_ro(&db)?;
            let n: i64 = con.query_row(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [MEME_TABLE],
                |r| r.get(0),
            )?;
            if n == 0 {
                return Ok(());
            }
            let mut stmt = con.prepare(&format!(
                "SELECT norad_id, epoch_ns(CAST(t_utc AS TIMESTAMP)), x_km, y_km, z_km FROM {MEME_TABLE} ORDER BY norad_id, t_utc"
            ))?;
            let rows = stmt.query_map([], |r| {
                Ok((r.get::<_, i64>(0)? as u32, r.get::<_, i64>(1)?, r.get::<_, f64>(2)?, r.get::<_, f64>(3)?, r.get::<_, f64>(4)?))
            })?;
            for row in rows.flatten() {
                let e = by_id.entry(row.0).or_insert(Samples { t: vec![], xyz: vec![] });
                e.t.push(row.1 as f64 / 1e9);
                e.xyz.push([row.2, row.3, row.4]);
            }
            Ok(())
        })();
        if let Err(e) = r {
            tracing::warn!("v3_meme_teme_samples 讀取失敗：{e:#}");
            by_id.clear();
        }
    }
    let m = Arc::new(by_id);
    *MEME_CACHE.lock() = Some((Instant::now(), m.clone()));
    m
}

/// np.interp（xp 遞增；範圍外不外推——呼叫端已先排除）
fn interp(x: f64, xp: &[f64], fp: impl Fn(usize) -> f64) -> f64 {
    let k = xp.partition_point(|v| *v <= x);
    if k == 0 {
        return fp(0);
    }
    if k >= xp.len() {
        return fp(xp.len() - 1);
    }
    let (x0, x1) = (xp[k - 1], xp[k]);
    if x1 == x0 {
        return fp(k);
    }
    fp(k - 1) + (fp(k) - fp(k - 1)) * (x - x0) / (x1 - x0)
}

fn meme_positions(samples: &SampleMap, nids: &[u32], t: f64) -> HashMap<u32, [f64; 3]> {
    let mut out = HashMap::new();
    for nid in nids {
        let Some(s) = samples.get(nid) else { continue };
        if s.t.is_empty() || t < s.t[0] || t > *s.t.last().unwrap() {
            continue;
        }
        out.insert(*nid, [0, 1, 2].map(|c| interp(t, &s.t, |i| s.xyz[i][c])));
    }
    out
}

fn coverage_info(samples: &SampleMap) -> Value {
    if samples.is_empty() {
        return json!({"available": false});
    }
    let mx = samples.values().filter_map(|s| s.t.last().copied()).fold(f64::NEG_INFINITY, f64::max);
    let mn = samples.values().filter_map(|s| s.t.first().copied()).fold(f64::INFINITY, f64::min);
    json!({
        "available": true,
        "satellites": samples.len(),
        "valid_from": common::py_iso_secs(&common::from_unix(mn.floor())),
        "valid_until": common::py_iso_secs(&common::from_unix(mx.floor())),
    })
}

static CT_CACHE: Lazy<Mutex<Option<(Instant, Arc<HashMap<String, Value>>)>>> = Lazy::new(|| Mutex::new(None));

/// CelesTrak 補充檔 Flight 14 元素（依名稱索引；4 小時快取；失敗回空）
async fn fetch_celestrak_v3_elements() -> Arc<HashMap<String, Value>> {
    if let Some((at, m)) = CT_CACHE.lock().as_ref() {
        if at.elapsed() < StdDuration::from_secs(4 * 3600) {
            return m.clone();
        }
    }
    let r = async {
        let text = common::http_client(15)
            .get("https://celestrak.org/NORAD/elements/supplemental/sup-gp.php")
            .query(&[("INTDES", V3_FLIGHT14_INTDES), ("FORMAT", "json")])
            .send()
            .await
            .and_then(|r| r.error_for_status())
            .map_err(|e| e.to_string())?
            .text()
            .await
            .map_err(|e| e.to_string())?;
        serde_json::from_str::<Value>(&text).map_err(|e| e.to_string())
    }
    .await;
    let mut by_name = HashMap::new();
    match r {
        Ok(Value::Array(a)) => {
            for it in a {
                if let Some(n) = it.get("OBJECT_NAME").and_then(Value::as_str).filter(|s| !s.is_empty()) {
                    by_name.insert(n.to_string(), it.clone());
                }
            }
        }
        Ok(_) => {}
        Err(e) => tracing::warn!("CelesTrak V3 supplemental 擬合資料取得失敗：{e}"),
    }
    let m = Arc::new(by_name);
    *CT_CACHE.lock() = Some((Instant::now(), m.clone()));
    m
}

fn num(v: &Value, k: &str) -> Option<f64> {
    let x = v.get(k)?;
    x.as_f64().or_else(|| x.as_str()?.trim().parse().ok())
}

fn celestrak_elem_eci(elem: &Value, t: &DateTime<Utc>) -> Option<[f64; 3]> {
    let ep_s = elem.get("EPOCH")?.as_str()?;
    let ep = NaiveDateTime::parse_from_str(ep_s, "%Y-%m-%dT%H:%M:%S%.f")
        .or_else(|_| DateTime::parse_from_rfc3339(ep_s).map(|d| d.naive_utc()))
        .ok()?;
    let p = Propagator::from_elements(
        ep,
        num(elem, "ECCENTRICITY")?,
        num(elem, "INCLINATION")?,
        num(elem, "RA_OF_ASC_NODE")?,
        num(elem, "ARG_OF_PERICENTER")?,
        num(elem, "MEAN_ANOMALY")?,
        num(elem, "MEAN_MOTION")?,
        num(elem, "BSTAR")?,
    )?;
    p.position(t)
}

pub async fn roster(st: Arc<AppState>) -> Value {
    let st2 = st.clone();
    let local = tokio::task::spawn_blocking(move || {
        let st = st2;
        let idx = st.index();
        let catalogue = userdata::load_user_catalogue(&st.cfg.user_catalogue_dir());
        let t = Utc::now();
        let tu = common::unix_of(&t);
        let valid: Vec<u32> = V3_FLIGHT14_NORAD_IDS.filter(|n| catalogue.contains_key(n)).collect();
        let samples = load_samples(&st);
        let meme = meme_positions(&samples, &valid, tu);
        let tle: HashMap<u32, [f64; 3]> = valid
            .iter()
            .filter_map(|n| {
                let s = idx.sats.get(n)?;
                let r = s.prop.as_ref()?.position(&t)?;
                Some((*n, r))
            })
            .collect();
        let rows: Vec<(u32, String, String, Option<([f64; 3], &'static str)>)> = valid
            .iter()
            .map(|n| {
                let cat = &catalogue[n];
                let name = cat.get("name_en").filter(|s| !s.is_empty()).cloned().unwrap_or_else(|| format!("NORAD {n}"));
                let cons = cat.get("constellation").filter(|s| !s.is_empty()).cloned().unwrap_or_else(|| "—".into());
                let pos = meme.get(n).map(|r| (*r, "meme")).or_else(|| tle.get(n).map(|r| (*r, "tle_estimate")));
                (*n, name, cons, pos)
            })
            .collect();
        (t, rows, coverage_info(&samples))
    })
    .await;
    let Ok((t, rows, meme_cov)) = local else {
        return json!({"error": "內部錯誤"});
    };
    let need_ct = rows.iter().any(|r| r.3.is_some());
    let ct = if need_ct { fetch_celestrak_v3_elements().await } else { Arc::new(HashMap::new()) };
    let tu = common::unix_of(&t);
    let mut results = Vec::new();
    let mut deltas = Vec::new();
    for (nid, name, cons, pos) in rows {
        let mut r = json!({"norad_id": nid, "name": name, "constellation": cons});
        if let Some((eci, src)) = pos {
            r["position_source"] = json!(src);
            let llh = eci_to_llh_py(&eci, tu);
            r["lat"] = json!(py_round(llh[0], 4));
            r["lon"] = json!(py_round(llh[1], 4));
            r["alt_km"] = json!(py_round(llh[2], 1));
            if let Some(el) = ct.get(&name) {
                if let Some(rc) = celestrak_elem_eci(el, &t) {
                    let d = ((eci[0] - rc[0]).powi(2) + (eci[1] - rc[1]).powi(2) + (eci[2] - rc[2]).powi(2)).sqrt();
                    r["celestrak_epoch"] = el.get("EPOCH").cloned().unwrap_or(Value::Null);
                    r["compare_delta_km"] = json!(py_round(d, 1));
                    deltas.push(py_round(d, 1));
                }
            }
        }
        results.push(r);
    }
    json!({
        "results": results,
        "count": results.len(),
        "expected_count": V3_FLIGHT14_NORAD_IDS.len(),
        "compared_count": deltas.len(),
        "compare_delta_km_mean": if deltas.is_empty() { Value::Null } else { json!(py_round(deltas.iter().sum::<f64>() / deltas.len() as f64, 1)) },
        "compare_delta_km_max": if deltas.is_empty() { Value::Null } else { json!(py_round(deltas.iter().copied().fold(f64::MIN, f64::max), 1)) },
        "meme_coverage": meme_cov,
        "source": "position_source=\"meme\"：Starlink 官方 MEME 72 小時預估（SpaceX 自行發布，直接內插，非本系統的軌道模型）。position_source=\"tle_estimate\"：MEME 樣本已過期時的退回路徑，SGP4 fitted from SpaceX MEME precise ephemeris — ESTIMATED，非官方 Space-Track/CelesTrak TLE。NORAD IDs 339974-339999 皆為本專案暫用的合成編號，尚未正式編目。",
        "compare_source": "compare_delta_km：與 CelesTrak 補充檔（sup-gp.php，SpaceX 自行提供之獨立 SGP4 擬合，DATA_SOURCE=SpaceX-E）在同一時刻的 3D 位置差距（km），供交叉驗證；兩者皆非 Space-Track 官方編目 TLE，Space-Track 目前仍為 0 筆（尚未正式編目）。",
    })
}
