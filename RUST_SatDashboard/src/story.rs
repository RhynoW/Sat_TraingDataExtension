//! `/story`、`/story/{sid}` 與 `/api/story/*`（Python 版 scenario04/api/story.py 的移植）。
//!
//! StoryMaps 式敘事頁：故事定義存於 config/stories/*.json（內嵌於執行檔；資料目錄
//! `config\stories\` 有同名檔時優先使用磁碟版，另可放入新故事），前端 story.js 依 JSON 渲染。
//!
//! 與 Python 版的差異（皆屬單機版環境限制）：
//! - provenance.app_commit：單機版無 git 工作目錄，固定為 null（Python 版 git 失敗時亦為 null）。
//! - provenance.propagator：標示實際使用之 Rust sgp4 crate（非 python-sgp4）。
//! - provenance 之「不晚於現在」與「7 天內」以 UTC 判定（Python 版經 DuckDB 工作階段時區轉換，
//!   在 UTC+8 主機上邊界會差 8 小時）。

mod radar;
mod revisit;
mod rx;
mod schema;

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Instant, SystemTime};

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, Response, StatusCode};
use axum::response::Html;
use axum::routing::get;
use axum::Router;
use chrono::{DateTime, Duration, NaiveDateTime, SecondsFormat, Timelike, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use rayon::prelude::*;
use rust_embed::RustEmbed;
use serde_json::{json, Map, Value};

use crate::config::{Config, RAW_TABLE};
use crate::index::SatIndex;
use crate::physics::Observer;
use crate::state::AppState;
use rx::Rx;

type St = State<Arc<AppState>>;
type Q = Query<HashMap<String, String>>;
type Resp = Response<Body>;

#[derive(RustEmbed)]
#[folder = "config/stories/"]
struct StoriesEmbed;

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/story", get(page_index))
        .route("/story/{sid}", get(page_story))
        .route("/api/story/list", get(api_list))
        .route("/api/story/groups", get(api_groups))
        .route("/api/story/group_stats", get(api_group_stats))
        .route("/api/story/maneuvers", get(api_maneuvers))
        .route("/api/story/reentry", get(api_reentry))
        .route("/api/story/isr_resolution", get(api_isr_resolution))
        .route("/api/story/radar_eval", get(api_radar_eval))
        .route("/api/story/revisit", get(api_revisit))
        .route("/api/story/track", get(api_track))
        .route("/api/story/positions", get(api_positions))
        .route("/api/story/provenance", get(api_provenance))
        .route("/api/story/{sid}", get(api_story))
}

// ── 共用工具（Python 相容之數值／時間格式）────────────────────────────────────

/// Python `round(x, d)`（十進位正確捨入、恰為一半時取偶數）
pub(crate) fn py_round(x: f64, d: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.d$}").parse().unwrap_or(x)
}

/// Python `str(float)`：整數值仍帶 `.0`
pub(crate) fn py_float(x: f64) -> String {
    if x.is_finite() && x.fract() == 0.0 && x.abs() < 1e16 {
        format!("{x:.1}")
    } else {
        format!("{x}")
    }
}

/// Python aware datetime `isoformat()`（微秒為 0 時省略）
pub(crate) fn iso_py(t: &DateTime<Utc>) -> String {
    format!("{}+00:00", naive_iso(&t.naive_utc()))
}

fn naive_iso(t: &NaiveDateTime) -> String {
    if t.nanosecond() / 1000 == 0 {
        t.format("%Y-%m-%dT%H:%M:%S").to_string()
    } else {
        t.format("%Y-%m-%dT%H:%M:%S%.6f").to_string()
    }
}

/// `isoformat().replace("+00:00", "Z")`
pub(crate) fn iso_z(t: &DateTime<Utc>) -> String {
    format!("{}Z", naive_iso(&t.naive_utc()))
}

/// 目前 UTC 時刻，秒與次秒歸零
pub(crate) fn now_minute() -> DateTime<Utc> {
    let n = Utc::now();
    n.with_second(0).and_then(|t| t.with_nanosecond(0)).unwrap_or(n)
}

/// GMST（弧度）：同 Python physics/coords.gmst_rad（無 T³ 項，以 UTC 近似 UT1）
pub(crate) fn gmst_py(t: &DateTime<Utc>) -> f64 {
    let d = (t.timestamp() - 946_728_000) as f64 / 86400.0 + f64::from(t.timestamp_subsec_nanos()) / 86400e9;
    let tc = d / 36525.0;
    (280.46061837 + 360.98564736629 * d + 0.000387933 * tc * tc)
        .rem_euclid(360.0)
        .to_radians()
}

/// TEME 位置 → (仰角°, 方位角°, 斜距 km)
pub(crate) fn teme_elaz(o: &Observer, r: &[f64; 3], gmst: f64) -> (f64, f64, f64) {
    o.elaz(r, gmst)
}

/// numpy.median
pub(crate) fn median(v: &[f64]) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = s.len();
    if n == 0 {
        f64::NAN
    } else if n % 2 == 1 {
        s[n / 2]
    } else {
        (s[n / 2 - 1] + s[n / 2]) / 2.0
    }
}

/// 同 Python json_response：UTF-8 JSON，選配 Cache-Control
fn json_resp(status: StatusCode, v: &Value, max_age: Option<u32>) -> Resp {
    let mut r = Response::new(Body::from(serde_json::to_vec(v).unwrap_or_default()));
    *r.status_mut() = status;
    let h = r.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json; charset=utf-8"));
    if let Some(a) = max_age {
        h.insert(
            header::CACHE_CONTROL,
            HeaderValue::from_str(&format!("public, max-age={a}")).unwrap(),
        );
    }
    r
}

fn ok(v: &Value) -> Resp {
    json_resp(StatusCode::OK, v, None)
}

fn err(status: StatusCode, msg: impl Into<String>) -> Resp {
    json_resp(status, &json!({"error": msg.into()}), None)
}

async fn blocking<F>(f: F) -> Resp
where
    F: FnOnce() -> Resp + Send + 'static,
{
    tokio::task::spawn_blocking(f).await.unwrap_or_else(|e| {
        tracing::error!("story 背景工作失敗：{e}");
        err(StatusCode::INTERNAL_SERVER_ERROR, "伺服器內部錯誤")
    })
}

/// 同 Python api.parse_float_arg：解析失敗回傳預設值（不夾限），成功則夾限於 [lo, hi]
fn farg(q: &HashMap<String, String>, k: &str, d: f64, lo: f64, hi: f64) -> f64 {
    match q.get(k) {
        Some(v) => v.trim().parse::<f64>().map(|x| x.max(lo).min(hi)).unwrap_or(d),
        None => d,
    }
}

/// 結果快取（TTL 秒）
struct TtlCache(Mutex<HashMap<String, (Instant, Arc<Value>)>>);

impl TtlCache {
    fn new() -> Self {
        Self(Mutex::new(HashMap::new()))
    }
    fn get(&self, k: &str, ttl: u64) -> Option<Arc<Value>> {
        self.0
            .lock()
            .get(k)
            .filter(|(at, _)| at.elapsed().as_secs() < ttl)
            .map(|(_, v)| v.clone())
    }
    fn put(&self, k: String, v: Arc<Value>) {
        let mut c = self.0.lock();
        if c.len() > 64 {
            c.retain(|_, (at, _)| at.elapsed().as_secs() < 1800);
        }
        c.insert(k, (Instant::now(), v));
    }
}

static RADAR_CACHE: Lazy<TtlCache> = Lazy::new(TtlCache::new);
static REVISIT_CACHE: Lazy<TtlCache> = Lazy::new(TtlCache::new);

// ── 故事檔（內嵌 + 磁碟覆寫）──────────────────────────────────────────────────

fn disk_dir(cfg: &Config) -> PathBuf {
    cfg.override_file("stories")
}

/// 頂層 *.json（不含 schema.json），依檔名排序；磁碟同名檔覆寫內嵌版
fn story_files(cfg: &Config) -> BTreeMap<String, Vec<u8>> {
    let mut out = BTreeMap::new();
    for name in StoriesEmbed::iter() {
        if !name.contains('/') && name.ends_with(".json") {
            if let Some(f) = StoriesEmbed::get(&name) {
                out.insert(name.to_string(), f.data.into_owned());
            }
        }
    }
    if let Ok(rd) = std::fs::read_dir(disk_dir(cfg)) {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            if name.ends_with(".json") && e.path().is_file() {
                match std::fs::read(e.path()) {
                    Ok(b) => {
                        out.insert(name, b);
                    }
                    Err(x) => tracing::warn!("story 檔載入失敗 {name}: {x}"),
                }
            }
        }
    }
    out.remove("schema.json");
    out
}

fn load_all(cfg: &Config) -> Vec<Value> {
    story_files(cfg)
        .into_iter()
        .filter_map(|(name, bytes)| {
            let d: Value = match serde_json::from_slice(&bytes) {
                Ok(d) => d,
                Err(e) => {
                    tracing::warn!("story 檔載入失敗 {name}: {e}");
                    return None;
                }
            };
            let has_id = match d.get("id") {
                Some(Value::String(s)) => !s.is_empty(),
                Some(Value::Null | Value::Bool(false)) | None => false,
                Some(_) => true,
            };
            if !has_id {
                return None;
            }
            if let Err(e) = schema::validate(&d) {
                tracing::warn!("story {name} 不符 schema：{e}");
                return None;
            }
            Some(d)
        })
        .collect()
}

fn find(cfg: &Config, sid: &str) -> Option<Value> {
    if !schema::valid_sid(sid) {
        return None;
    }
    load_all(cfg).into_iter().find(|d| d["id"] == sid)
}

/// config/stories/data/<name>：磁碟優先，否則內嵌
fn data_file(cfg: &Config, name: &str) -> Option<Value> {
    let bytes = std::fs::read(disk_dir(cfg).join("data").join(name))
        .ok()
        .or_else(|| StoriesEmbed::get(&format!("data/{name}")).map(|f| f.data.into_owned()))?;
    match serde_json::from_slice(&bytes) {
        Ok(v) => Some(v),
        Err(e) => {
            tracing::warn!("story 資料檔解析失敗 {name}: {e}");
            None
        }
    }
}

// ── 頁面 ─────────────────────────────────────────────────────────────────────

fn story_page_html(sid: &str) -> Html<String> {
    let Html(h) = crate::orbit_history::page("templates/story.html");
    Html(h.replace("__STORY_ID__", sid))
}

async fn page_index() -> Html<String> {
    story_page_html("")
}

async fn page_story(Path(sid): Path<String>) -> Html<String> {
    story_page_html(if schema::valid_sid(&sid) { &sid } else { "" })
}

async fn api_list(State(st): St) -> Resp {
    let list: Vec<Value> = load_all(&st.cfg)
        .into_iter()
        .map(|d| {
            json!({
                "id": d["id"],
                "title": d.get("title").cloned().unwrap_or_else(|| d["id"].clone()),
                "subtitle": d.get("subtitle").cloned().unwrap_or(json!("")),
                "updated": d.get("updated").cloned().unwrap_or(json!("")),
            })
        })
        .collect();
    ok(&Value::Array(list))
}

async fn api_story(State(st): St, Path(sid): Path<String>) -> Resp {
    match find(&st.cfg, &sid) {
        Some(d) => ok(&d),
        None => err(StatusCode::NOT_FOUND, format!("story '{sid}' 不存在")),
    }
}

// ── 整合展示群組（constellation 標籤 或 名稱正則）─────────────────────────────

struct Group {
    key: &'static str,
    label: &'static str,
    country: Option<&'static str>,
    constellation: Option<&'static str>,
    rx: Option<Rx>,
}

const PRC_ISR_RX: &str = concat!(
    r"^YAOGAN|^GAOFEN|^GF-|JILIN|^JL-?1|^TIANHUI|^TH-|^HAIYANG|^HY-",
    r"|^ZIYUAN|^ZY-|^ZY |^HUANJING|^HJ-|^HJS|^LUDI|^SHIYAN|^SY-|^SHIJIAN|^SJ-|^SJ ",
    r"|^TJS|^YUNHAI|^NINGXIA|^FENGYUN|^FY-|^TIANMU|^YUNYAO",
    r"|ZHUHAI|OVS-|OHS-|^BEIJING|BJ-|TAIJING|SIWEI|SUPERVIEW|GAOJING|^TIANYI|^TY-",
    r"|HEAD-|^HEAD|CHAOHU|HISEA|^CHUANG|^STTW|^GJZ|^KL-|^KL |^CBERS|^PIESAT|^HONGTU",
    r"|^BEIDOU",
);

static GROUPS: Lazy<Vec<Group>> = Lazy::new(|| {
    let rx = |p: &str| Some(Rx::compile(p).expect("內建群組正則語法錯誤"));
    vec![
        Group { key: "gps", label: "GPS", country: None, constellation: None, rx: rx(r"^NAVSTAR") },
        Group { key: "beidou", label: "北斗/BeiDou", country: None, constellation: None, rx: rx(r"^BEIDOU") },
        Group { key: "starlink", label: "Starlink", country: None, constellation: Some("Starlink"), rx: None },
        Group { key: "oneweb", label: "OneWeb", country: None, constellation: Some("OneWeb"), rx: None },
        // 口徑對齊 USSF Space Threat Fact Sheet／UPI：軍用＋民用＋商業遙感衛星＋北斗導航（2026-08 盤點 581）
        Group { key: "prc_isr", label: "大陸 ISR/遙感（含北斗）", country: Some("中國"), constellation: None, rx: rx(PRC_ISR_RX) },
        Group {
            key: "prc_comm",
            label: "大陸通訊星系",
            country: Some("中國"),
            constellation: None,
            rx: rx(r"QIANFAN|SPACESAIL|HULIANWANG|GUOWANG|SATNET|CHINASAT|ZHONGXING|APSTAR|TIANLIAN|TIANTONG"),
        },
    ]
});

fn group(key: &str) -> Option<&'static Group> {
    GROUPS.iter().find(|g| g.key == key)
}

/// Python 版錯誤訊息：`group 需為 ['gps', 'beidou', …]`
fn group_err() -> Resp {
    let keys: Vec<String> = GROUPS.iter().map(|g| format!("'{}'", g.key)).collect();
    err(StatusCode::BAD_REQUEST, format!("group 需為 [{}]", keys.join(", ")))
}

fn group_members(idx: &SatIndex, g: &Group) -> Vec<u32> {
    idx.sats
        .values()
        .filter(|i| i.purpose != "碎片" && i.purpose != "火箭體")
        .filter(|i| g.country.is_none_or(|c| i.country == c))
        .filter(|i| g.constellation.is_none_or(|c| i.constellation.as_deref() == Some(c)))
        .filter(|i| g.rx.as_ref().is_none_or(|r| r.search(&i.name)))
        .map(|i| i.norad_id)
        .collect()
}

/// Python 字串切片 `s[a:b]`（超出長度時截短）
fn py_slice(s: &str, a: usize, b: usize) -> &str {
    let n = s.len();
    s.get(a.min(n)..b.min(n)).unwrap_or("")
}

/// 由 TLE line2 取傾角(°)與平均高度(km)
fn tle_elements(line2: &str) -> Option<(f64, f64)> {
    let inc: f64 = py_slice(line2, 8, 16).trim().parse().ok()?;
    let mm: f64 = py_slice(line2, 52, 63).trim().parse().ok()?;
    if mm <= 0.0 || !inc.is_finite() || !mm.is_finite() {
        return None;
    }
    let n = mm * 2.0 * std::f64::consts::PI / 86400.0;
    let a = (398600.4418 / (n * n)).powf(1.0 / 3.0);
    Some((inc, a - 6378.137))
}

async fn api_groups(State(st): St) -> Resp {
    blocking(move || {
        let idx = st.index();
        let mut out = Map::new();
        for g in GROUPS.iter() {
            out.insert(g.key.into(), json!({"label": g.label, "n": group_members(&idx, g).len()}));
        }
        ok(&Value::Object(out))
    })
    .await
}

/// sat_metadata.csv 之發射日期（launch_date，缺時 launch）；以 (路徑, mtime, 大小) 快取
type LaunchMap = Arc<HashMap<u32, String>>;
static LAUNCH_CACHE: Lazy<Mutex<Option<((PathBuf, Option<SystemTime>, u64), LaunchMap)>>> =
    Lazy::new(|| Mutex::new(None));

fn launch_dates(cfg: &Config) -> LaunchMap {
    let p = cfg.sat_meta_csv();
    let md = std::fs::metadata(&p).ok();
    let key = (
        p.clone(),
        md.as_ref().and_then(|m| m.modified().ok()),
        md.as_ref().map_or(0, |m| m.len()),
    );
    if let Some((k, v)) = &*LAUNCH_CACHE.lock() {
        if *k == key {
            return v.clone();
        }
    }
    let meta = crate::index::load_meta_csv(&p);
    let map: HashMap<u32, String> = meta
        .into_iter()
        .filter_map(|(n, m)| {
            let ld = m
                .get("launch_date")
                .filter(|s| !s.is_empty())
                .or_else(|| m.get("launch").filter(|s| !s.is_empty()))?;
            Some((n, ld.clone()))
        })
        .collect();
    let v = Arc::new(map);
    *LAUNCH_CACHE.lock() = Some((key, v.clone()));
    v
}

/// 依插入順序計數（同 Python Counter）
#[derive(Default)]
struct Counter(Vec<(String, i64)>);

impl Counter {
    fn add(&mut self, k: &str) {
        match self.0.iter_mut().find(|(x, _)| x == k) {
            Some((_, c)) => *c += 1,
            None => self.0.push((k.to_string(), 1)),
        }
    }
    fn get(&self, k: &str) -> i64 {
        self.0.iter().find(|(x, _)| x == k).map_or(0, |(_, c)| *c)
    }
    /// Counter.most_common()：次數遞減，同數依插入順序
    fn most_common(&self) -> Vec<(String, i64)> {
        let mut v = self.0.clone();
        v.sort_by(|a, b| b.1.cmp(&a.1));
        v
    }
    fn to_map(v: Vec<(String, i64)>) -> Value {
        Value::Object(v.into_iter().map(|(k, c)| (k, json!(c))).collect())
    }
}

fn int_hist(m: BTreeMap<i64, i64>) -> Value {
    Value::Object(m.into_iter().map(|(k, c)| (k.to_string(), json!(c))).collect())
}

async fn api_group_stats(State(st): St, Query(q): Q) -> Resp {
    let key = q.get("group").cloned().unwrap_or_default();
    let Some(g) = group(&key) else { return group_err() };
    blocking(move || {
        let idx = st.index();
        let ids = group_members(&idx, g);
        let meta = launch_dates(&st.cfg);
        let mut alt_bins: BTreeMap<i64, i64> = BTreeMap::new();
        let mut inc_bins: BTreeMap<i64, i64> = BTreeMap::new();
        let mut years: BTreeMap<String, i64> = BTreeMap::new();
        let mut regimes = Counter::default();
        let mut alts: Vec<f64> = Vec::new();
        for n in &ids {
            let Some((inc, alt)) = tle_elements(&idx.sats[n].line2) else { continue };
            alts.push(alt);
            let ab = if alt < 2000.0 {
                (alt / 100.0).floor() as i64 * 100
            } else if alt < 30000.0 {
                20000
            } else {
                35000
            };
            *alt_bins.entry(ab).or_default() += 1;
            *inc_bins.entry((inc / 10.0).floor() as i64 * 10).or_default() += 1;
            regimes.add(if alt < 2000.0 {
                "LEO"
            } else if alt < 30000.0 {
                "MEO"
            } else {
                "GEO/IGSO"
            });
            if let Some(ld) = meta.get(n) {
                let y: String = ld.chars().take(4).collect();
                if y.chars().count() == 4 && y.chars().all(|c| c.is_ascii_digit()) {
                    *years.entry(y).or_default() += 1;
                }
            }
        }
        let mut sorted_ids = ids.clone();
        sorted_ids.sort_unstable();
        let sample: Vec<Value> = sorted_ids
            .iter()
            .rev()
            .take(8)
            .map(|n| json!({"norad": n, "name": idx.sats[n].name}))
            .collect();
        alts.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let alt_median = if alts.is_empty() {
            Value::Null
        } else {
            json!(py_round(alts[alts.len() / 2], 1))
        };
        ok(&json!({
            "group": key, "label": g.label, "n": ids.len(),
            "regimes": Counter::to_map(regimes.0),
            "alt_hist": int_hist(alt_bins),
            "inc_hist": int_hist(inc_bins),
            "launch_years": Value::Object(years.into_iter().map(|(k, c)| (k, json!(c))).collect()),
            "alt_median": alt_median,
            "sample": sample,
        }))
    })
    .await
}

async fn api_maneuvers(State(st): St) -> Resp {
    match data_file(&st.cfg, "maneuvers_2026.json") {
        Some(d) => json_resp(StatusCode::OK, &d, Some(3600)),
        None => err(StatusCode::NOT_FOUND, "尚未預算（執行 tools/build_maneuvers_2026.py）"),
    }
}

async fn api_reentry(State(st): St) -> Resp {
    let Some(mut d) = data_file(&st.cfg, "reentry_cluster.json") else {
        return err(StatusCode::NOT_FOUND, "尚未預算（執行 tools/reentry_estimate.py）");
    };
    // 精簡：去掉 MC 逐次 runs
    if let Some(ts) = d.get_mut("targets").and_then(Value::as_object_mut) {
        for t in ts.values_mut() {
            if let Some(mc) = t.get_mut("stage2_mc").and_then(Value::as_object_mut) {
                mc.shift_remove("runs");
            }
        }
    }
    json_resp(StatusCode::OK, &d, Some(600))
}

// ── 偵照衛星感測器／光學解析度分類（型號級別、公開文獻推估；首個符合規則者為準）──

/// (系列, regex, sensor, res_class, 註記)
const ISR_RES_RULES: [(&str, &str, &str, &str, &str); 29] = [
    ("遙感-30/20/25/31/39/40 三星組", r"^YAOGAN[- ]?(30|20|25|31|39|40)\b", "射頻訊號", "—", "海洋目標電子偵察三星組（公開分析）"),
    ("遙感 SAR 型（-1/3/6/10/13/18/23/29/33）", r"^YAOGAN[- ]?(1|3|6|10|13|18|23|29|33)\b", "SAR", "≈1 m（推估）", "公開分析歸類為雷達型"),
    ("遙感-41（GEO 光學）", r"^YAOGAN[- ]?41\b", "光學", "1–5 m", "地球同步高軌光學（2023）"),
    ("遙感 光學型（其餘）", r"^YAOGAN", "光學", "≤0.5 m（推估）", "軍用高解析光學，官方未公開"),
    ("高分-11", r"^GAOFEN[- ]?11\b", "光學", "≤0.5 m", "公開報導約 0.1–0.5 m 級"),
    ("高分-2/7/14（0.5–1 m）", r"^GAOFEN[- ]?(2|7|14)\b", "光學", "0.5–1 m", "GF-2 0.8 m、GF-7 0.65 m 立體"),
    ("高分-3/12（SAR）", r"^GAOFEN[- ]?(3|12)\b", "SAR", "≈1 m", "C 波段 1 m 條帶"),
    ("高分-4（GEO 凝視）", r"^GAOFEN[- ]?4\b", "光學", ">30 m", "GEO 50 m 可見光／400 m 紅外"),
    ("高分-5（高光譜）", r"^GAOFEN[- ]?5\b", "光學", "5–30 m", "高光譜 30 m"),
    ("高分-1/6/13 等", r"^GAOFEN|^GF-", "光學", "1–5 m", "2 m 全色／8 m 多光譜（寬幅 16 m）"),
    ("吉林一號 寬幅/高分 03/04", r"JILIN|^JL-?1", "光學", "0.5–1 m", "GF03 0.75 m、寬幅 01 0.5 m"),
    ("四維／SuperView（高景）", r"SIWEI|SUPERVIEW|GAOJING", "光學", "≤0.5 m", "0.5 m（高景一號）/0.42 m"),
    ("北京三號", r"^BEIJING|BJ-", "光學", "≤0.5 m", "0.5 m 敏捷"),
    ("珠海一號 OVS（視頻）", r"OVS-", "光學", "0.5–1 m", "0.9 m 視頻"),
    ("珠海一號 OHS（高光譜）", r"OHS-|ZHUHAI", "光學", "5–30 m", "10 m 高光譜"),
    ("天繪-1（測繪）", r"^TIANHUI[- ]?1|^TH-1", "光學", "1–5 m", "2 m 全色／5 m 立體"),
    ("天繪-2（SAR 干涉）", r"^TIANHUI[- ]?2|^TH-2", "SAR", "≈3 m", "雙星 InSAR"),
    ("天繪 其他", r"^TIANHUI|^TH-", "光學", "1–5 m", "測繪"),
    ("資源三號／CBERS", r"^ZIYUAN|^ZY-|^ZY |^CBERS", "光學", "1–5 m", "ZY-3 2.1 m 立體"),
    ("環境／陸地探測", r"^HUANJING|^HJ-|^HJS|^LUDI", "光學", "5–30 m", "HJ 16–30 m；陸地探測一號為 L 波段 SAR"),
    ("海絲／巢湖（商業 SAR）", r"HISEA|CHAOHU", "SAR", "≈1 m", "商業 C 波段"),
    ("海洋系列", r"^HAIYANG|^HY-", "光學", ">30 m", "海洋水色 250 m–1 km（HY-2 為微波）"),
    ("風雲／雲海（氣象）", r"^FENGYUN|^FY-|^YUNHAI", "氣象掩星", "—", "氣象成像 250 m–1 km 級"),
    ("天目／雲遙（GNSS 掩星）", r"^TIANMU|^YUNYAO", "氣象掩星", "—", "無成像"),
    ("寧夏一號（射頻）", r"^NINGXIA", "射頻訊號", "—", "商業電子偵察星座（公開分析）"),
    ("TJS 通信技術試驗（GEO）", r"^TJS", "射頻訊號", "—", "疑似 GEO 訊號情報／早期預警"),
    ("實驗／實踐（技術試驗）", r"^SHIYAN|^SY-|^SHIJIAN|^SJ-|^SJ ", "技術試驗", "—", "載荷多未公開"),
    ("其他商業 EO", r"^TIANYI|^TY-|HEAD-|^HEAD|^CHUANG|^STTW|^GJZ|^KL-|^KL |^PIESAT|^HONGTU|TAIJING", "光學", "1–5 m", "型號各異"),
    ("北斗（導航）", r"^BEIDOU", "導航", "—", "無成像感測器"),
];
const RES_ORDER: [&str; 6] = ["≤0.5 m", "≤0.5 m（推估）", "0.5–1 m", "1–5 m", "5–30 m", ">30 m"];
/// 分類規則版本：規則清單／優先順序變更時遞增
const ISR_RES_RULES_VERSION: &str = "1.0";

static ISR_RX: Lazy<Vec<Rx>> = Lazy::new(|| {
    ISR_RES_RULES
        .iter()
        .map(|r| Rx::compile(r.1).expect("內建偵照分類正則語法錯誤"))
        .collect()
});

async fn api_isr_resolution(State(st): St, Query(q): Q) -> Resp {
    let key = q.get("group").cloned().unwrap_or_else(|| "prc_isr".into());
    let Some(g) = group(&key) else { return group_err() };
    blocking(move || {
        let idx = st.index();
        let (mut sensor_c, mut res_c, mut series_c) = (Counter::default(), Counter::default(), Counter::default());
        let mut unknown = 0usize;
        for n in group_members(&idx, g) {
            let nm = &idx.sats[&n].name;
            match ISR_RES_RULES.iter().zip(ISR_RX.iter()).find(|(_, r)| r.search(nm)) {
                Some(((s, _, sensor, res, _), _)) => {
                    sensor_c.add(sensor);
                    series_c.add(s);
                    if *sensor == "光學" {
                        res_c.add(res);
                    } else if *sensor == "SAR" {
                        res_c.add(&format!("SAR {res}"));
                    }
                }
                None => unknown += 1,
            }
        }
        let mut series: Vec<Value> = ISR_RES_RULES
            .iter()
            .filter(|r| series_c.get(r.0) > 0)
            .map(|(s, _, sensor, res, note)| {
                json!({"series": s, "n": series_c.get(s), "sensor": sensor, "res": res, "note": note})
            })
            .collect();
        series.sort_by_key(|x| -x["n"].as_i64().unwrap_or(0));
        let mut res_sorted = res_c.0.clone();
        res_sorted.sort_by_key(|(k, _)| match RES_ORDER.iter().position(|r| r == k) {
            Some(i) => i,
            None => 90 + usize::from(!k.starts_with("SAR")),
        });
        ok(&json!({
            "group": key, "label": g.label,
            "sensor": Counter::to_map(sensor_c.most_common()),
            "resolution": Counter::to_map(res_sorted),
            "series": series, "unknown": unknown,
            "classification_version": ISR_RES_RULES_VERSION,
            "rule_order": ISR_RES_RULES.iter().map(|r| r.0).collect::<Vec<_>>(),
            "note": "分類為型號級別之公開文獻推估（Gunter's Space Page、公開分析），非官方規格；軍用遙感系列之解析度為推估。\
                     單一主分類、NORAD 去重、規則依序先到先得（rule_order）。",
        }))
    })
    .await
}

// ── 雷達效益評估 / 過頂追蹤 ──────────────────────────────────────────────────

fn ssn_geojson(cfg: &Config) -> String {
    std::fs::read_to_string(cfg.override_file("ssn_stations.geojson"))
        .unwrap_or_else(|_| crate::assets::SSN_STATIONS_DEFAULT.to_string())
}

async fn api_radar_eval(State(st): St, Query(q): Q) -> Resp {
    let key = q.get("group").cloned().unwrap_or_else(|| "prc_isr".into());
    let Some(g) = group(&key) else { return group_err() };
    let n = match q.get("n").map(|s| s.trim().parse::<i64>()) {
        None => 40,
        Some(Ok(v)) => v,
        Some(Err(_)) => return err(StatusCode::BAD_REQUEST, "n 需為整數"),
    }
    .clamp(5, 60) as usize;
    let fparse = |k: &str, d: f64| -> Result<f64, Resp> {
        match q.get(k) {
            None => Ok(d),
            Some(s) => s
                .trim()
                .parse::<f64>()
                .map_err(|_| err(StatusCode::BAD_REQUEST, format!("{k} 需為數值"))),
        }
    };
    let hours = match fparse("hours", 24.0) {
        Ok(v) => v.min(48.0).max(6.0),
        Err(r) => return r,
    };
    let mask = match fparse("mask", 5.0) {
        Ok(v) => v.min(30.0).max(0.0),
        Err(r) => return r,
    };
    blocking(move || {
        let ck = format!("{key}|{n}|{hours}|{mask}");
        if let Some(v) = RADAR_CACHE.get(&ck, 1800) {
            return ok(&v);
        }
        let idx = st.index();
        let mut ids = group_members(&idx, g);
        ids.sort_unstable_by(|a, b| b.cmp(a));
        // 只取 LEO（GEO 對地面站幾何恆定）；NORAD 由大到小（較新）之前 n 顆
        let mut sats = Vec::new();
        for nid in ids {
            let s = &idx.sats[&nid];
            if tle_elements(&s.line2).is_some_and(|(_, alt)| alt < 2000.0) && !s.line1.is_empty() {
                sats.push(s);
            }
            if sats.len() >= n {
                break;
            }
        }
        let ssn = radar::ssn_observers(&ssn_geojson(&st.cfg));
        let mut res = radar::evaluate(&sats, &ssn, hours, mask);
        res["group"] = json!(key);
        res["label"] = json!(g.label);
        let res = Arc::new(res);
        RADAR_CACHE.put(ck, res.clone());
        ok(&res)
    })
    .await
}

/// 台灣代表觀測點（故事頁「重訪週期」區塊之選單）
const TW_SITES: [(&str, &str, f64, f64); 6] = [
    ("taipei", "台北", 25.0330, 121.5654),
    ("taichung", "台中", 24.1477, 120.6736),
    ("tropic", "北回歸線（嘉義）", 23.4500, 120.4400),
    ("eluanbi", "鵝鑾鼻", 21.9017, 120.8536),
    ("nangan", "馬祖南竿", 26.1602, 119.9297),
    ("kinmen", "金門", 24.4365, 118.3186),
];

fn tw_sites_json() -> Value {
    Value::Array(
        TW_SITES
            .iter()
            .map(|(k, n, la, lo)| json!({"key": k, "name": n, "lat": la, "lon": lo}))
            .collect(),
    )
}

async fn api_revisit(State(st): St, Query(q): Q) -> Resp {
    let key = q.get("group").map_or("oneweb", |s| s.trim()).to_string();
    let Some(g) = group(&key) else { return group_err() };
    let site_key = q.get("site").map_or("", |s| s.trim());
    let (lat, lon, site_name) = match TW_SITES.iter().find(|s| s.0 == site_key) {
        Some((_, name, la, lo)) => (*la, *lo, name.to_string()),
        None => {
            let lat = farg(&q, "lat", TW_SITES[0].2, -85.0, 85.0);
            let lon = farg(&q, "lon", TW_SITES[0].3, -180.0, 180.0);
            (lat, lon, format!("{lat:.2}°N, {lon:.2}°E"))
        }
    };
    let hours = farg(&q, "hours", 24.0, 6.0, 48.0);
    let step = farg(&q, "step_sec", 30.0, 15.0, 120.0);
    blocking(move || {
        // 快取 30 分鐘：同參數在 TLE 未更新期間結果實質不變
        let ck = format!("{key}|{lat:.3}|{lon:.3}|{hours:.0}|{step:.0}");
        if let Some(v) = REVISIT_CACHE.get(&ck, 1800) {
            let mut v = (*v).clone();
            v["from_cache"] = json!(true);
            return ok(&v);
        }
        let idx = st.index();
        let ids = group_members(&idx, g);
        if ids.is_empty() {
            return err(StatusCode::NOT_FOUND, format!("群組 {key} 無成員"));
        }
        let mut res = revisit::compute_revisit(&ids, &idx, lat, lon, hours, step);
        if res.get("error").is_some() {
            return json_resp(StatusCode::INTERNAL_SERVER_ERROR, &res, None);
        }
        res["group"] = json!(key);
        res["label"] = json!(g.label);
        res["site_name"] = json!(site_name);
        res["sites"] = tw_sites_json();
        let res = Arc::new(res);
        REVISIT_CACHE.put(ck, res.clone());
        json_resp(StatusCode::OK, &res, Some(600))
    })
    .await
}

async fn api_track(State(st): St, Query(q): Q) -> Resp {
    let Ok(nid) = q.get("norad").map_or("", |s| s.trim()).parse::<i64>() else {
        return err(StatusCode::BAD_REQUEST, "norad 必填");
    };
    blocking(move || {
        let idx = st.index();
        let info = u32::try_from(nid).ok().and_then(|n| idx.sats.get(&n));
        let Some(info) = info.filter(|i| !i.line1.is_empty()) else {
            return err(StatusCode::NOT_FOUND, format!("NORAD {nid} 無 TLE"));
        };
        let mut res = radar::track_passes(info.prop.as_ref());
        res["norad"] = json!(nid);
        res["name"] = json!(info.name);
        ok(&res)
    })
    .await
}

// ── 故事頁世界地圖用之衛星即時位置 ───────────────────────────────────────────

async fn api_positions(State(st): St, Query(q): Q) -> Resp {
    let mode = q.get("mode").map_or("all", |s| s.trim()).to_string();
    let val = q.get("val").map_or("", |s| s.trim()).to_string();
    blocking(move || {
        let idx = st.index();
        let sel: Vec<u32> = match mode.as_str() {
            "ids" => val
                .split(',')
                .map(str::trim)
                .filter(|x| !x.is_empty() && x.chars().all(|c| c.is_ascii_digit()))
                .filter_map(|x| x.parse::<u32>().ok())
                .filter(|n| idx.sats.contains_key(n))
                .collect(),
            "group" => match group(&val) {
                Some(g) => group_members(&idx, g),
                None => return group_err(),
            },
            "country" | "constellation" | "purpose" => {
                if val.is_empty() {
                    return err(StatusCode::BAD_REQUEST, "val 不可空白");
                }
                idx.sats
                    .values()
                    .filter(|i| i.field(&mode) == Some(val.as_str()))
                    .map(|i| i.norad_id)
                    .collect()
            }
            "all" => idx.sats.values().filter(|i| !i.line1.is_empty()).map(|i| i.norad_id).collect(),
            _ => return err(StatusCode::BAD_REQUEST, "mode 必須為 all/country/constellation/purpose/ids"),
        };
        let t = Utc::now();
        let pos: Vec<Option<[f64; 3]>> = sel
            .par_iter()
            .map(|n| idx.sats[n].prop.as_ref().and_then(|p| p.llh(&t)))
            .collect();
        let mut sats = Vec::new();
        let mut names = Map::new();
        for (n, p) in sel.iter().zip(&pos) {
            let Some([la, lo, al]) = p else { continue };
            sats.push(json!([n, py_round(*la, 4), py_round(*lo, 4), py_round(*al, 1)]));
            if mode != "all" {
                names.insert(n.to_string(), json!(idx.sats[n].name));
            }
        }
        ok(&json!({
            "mode": mode, "val": val, "count": sats.len(),
            "sats": sats, "names": names,
            "timestamp": iso_py(&t),
        }))
    })
    .await
}

// ── 資料口徑（provenance）────────────────────────────────────────────────────

/// 同 Python ingestion/db.get_db_info 之欄位（時間格式同 Python isoformat），快取 db_info_ttl_s
static DB_INFO: Lazy<TtlCache> = Lazy::new(TtlCache::new);

fn ts_from_us(us: i64) -> Option<NaiveDateTime> {
    DateTime::from_timestamp_micros(us).map(|t| t.naive_utc())
}

fn db_info(cfg: &Config) -> Arc<Value> {
    if let Some(v) = DB_INFO.get("db", cfg.db_info_ttl_s) {
        return v;
    }
    let Some(db) = cfg.resolve_db() else {
        return Arc::new(json!({"error": "資料庫不存在"}));
    };
    let name = db.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let q = || -> anyhow::Result<Value> {
        let md = std::fs::metadata(&db)?;
        let mtime: DateTime<Utc> = md.modified()?.into();
        let con = crate::index::open_ro(&db)?;
        let (total, sats, emin, emax): (Option<i64>, Option<i64>, Option<i64>, Option<i64>) = con.query_row(
            &format!(
                "SELECT COUNT(*), COUNT(DISTINCT norad_id), epoch_us(MIN(epoch_utc)), epoch_us(MAX(epoch_utc))
                 FROM {RAW_TABLE} WHERE line1 IS NOT NULL AND line2 IS NOT NULL"
            ),
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )?;
        let iso = |v: Option<i64>| v.and_then(ts_from_us).map(|t| naive_iso(&t));
        Ok(json!({
            "db_name": name,
            "db_size_mb": py_round(md.len() as f64 / 1024f64.powi(2), 1),
            "db_updated_at": iso_py(&mtime),
            "has_tle_lines": true,
            "total_records": total.unwrap_or(0),
            "valid_sat_count": sats.unwrap_or(0),
            "epoch_min": iso(emin),
            "epoch_max": iso(emax),
        }))
    };
    let v = Arc::new(q().unwrap_or_else(|e| json!({"error": e.to_string(), "db_name": name})));
    DB_INFO.put("db".into(), v.clone());
    v
}

fn provenance(cfg: &Config) -> Value {
    let info = db_info(cfg);
    let now = Utc::now();
    let lit = |t: DateTime<Utc>| format!("TIMESTAMP '{}'", t.format("%Y-%m-%d %H:%M:%S%.6f"));
    // 資料齡以「不晚於現在之最新 epoch」計；有效衛星數以 ≤7 天內有 TLE 者計（皆以 UTC 判定）
    let (latest_past, n_fresh7) = cfg
        .resolve_db()
        .and_then(|db| crate::index::open_ro(&db).ok())
        .map(|con| {
            let lp: Option<i64> = con
                .query_row(
                    &format!("SELECT epoch_us(max(epoch_utc)) FROM {RAW_TABLE} WHERE epoch_utc <= {}", lit(now)),
                    [],
                    |r| r.get(0),
                )
                .unwrap_or_else(|e| {
                    tracing::debug!("provenance latest_past 查詢失敗: {e}");
                    None
                });
            let nf: Option<i64> = con
                .query_row(
                    &format!(
                        "SELECT count(DISTINCT norad_id) FROM {RAW_TABLE} WHERE epoch_utc >= {} AND epoch_utc <= {}",
                        lit(now - Duration::days(7)),
                        lit(now + Duration::days(1))
                    ),
                    [],
                    |r| r.get(0),
                )
                .map_err(|e| tracing::debug!("provenance n_fresh7 查詢失敗: {e}"))
                .ok();
            (lp.and_then(ts_from_us), nf)
        })
        .unwrap_or((None, None));
    let reference = latest_past.or_else(|| {
        info["epoch_max"]
            .as_str()
            .and_then(|s| NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f").ok())
    });
    let (age, latest_past) = match reference {
        Some(em) => {
            let em = em.and_utc();
            let days = (now - em).num_microseconds().unwrap_or(0) as f64 / 1e6 / 86400.0;
            (json!(py_round(days, 1)), json!(em.to_rfc3339_opts(SecondsFormat::Secs, false)))
        }
        None => (Value::Null, Value::Null),
    };
    let sigma_n = std::env::var("SIGMA_N_KM").ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.1);
    json!({
        "source": "Space-Track GP（公開 TLE）；本系統 DuckDB 每日彙整",
        "db_name": info.get("db_name"), "db_updated_at": info.get("db_updated_at"),
        "tle_epoch_min": info.get("epoch_min"), "tle_epoch_max": info.get("epoch_max"),
        "tle_epoch_latest_past": latest_past, "tle_age_days": age,
        "catalog_sat_count": info.get("valid_sat_count"),
        "tle_record_count": info.get("total_records"),
        "fresh_sat_count_7d": n_fresh7,
        "valid_sat_count": info.get("valid_sat_count"),
        "app_commit": null,
        "classification_version": ISR_RES_RULES_VERSION,
        "fresh_criteria": "最新 TLE 年齡 ≤ 7 天（資料齡篩選）；未逐一檢查 SGP4 誤差碼與衰減／再入狀態",
        "propagator": "Rust sgp4 crate 2.4（WGS-72），依軌道週期自動使用 SGP4（近地）或 SDP4（週期 ≥225 min 深空）",
        "frame": "SGP4 輸出 TEME；以 UTC 近似 UT1 計算 GMST 作 TEME→ECEF 旋轉，再依 WGS-84 橢球求地理經緯度與大地高；\
                  未納入極移、章動、UT1−UTC 與完整 ITRF 地球定向參數（地面位置屬態勢展示等級）",
        "screening": "幾何接近篩選為單一傳播時刻（請求當下 UTC）之全目錄 pairwise 距離篩選（KD-tree），\
                      非時間窗 TCA 搜尋；展開 3D 後才於兩星 TLE 重疊期間以 30 分鐘取樣間隔粗掃（區間過長時放大至總點數 ≤1,500）\
                      求全域最小距離，再於最接近時刻 ±12 h 聚焦窗以 60 秒取樣細掃；距離門檻僅用於初始篩選",
        "age_basis": "資料齡以文件／頁面產生時間為基準（非資料庫快照時間）",
        "accuracy": "公開 TLE 級（LEO 沿軌 1–3 km/日量級增長），非精密星曆；不宜作為操作級決策依據",
        "status": "技術展示／非操作級",
        "pc_model": format!(
            "Chan (2008) 2-D 簡化式：以相對 RTN 框架之固定示意標準差 σ_R/σ_T 合成單一相對協方差（σ_R/T/N = \
             {:.0}/{:.0}/{:.0} m；σ_N 僅用於 3D 橢球繪製），等效碰撞半徑 {:.0} m，最接近點 B-plane 假設；\
             非兩星各自 CDM 協方差相加，Pc proxy 僅供事件排序",
            cfg.sigma_r_km * 1000.0, cfg.sigma_t_km * 1000.0, sigma_n * 1000.0, cfg.sat_radius_km * 1000.0
        ),
        "maneuver_method": "相鄰 TLE 半長軸跳變 |Δa| 門檻（LEO 0.5 km、MEO/GEO 2 km，間隔 ≤5 天）之候選事件；\
                            Δv 由 Δa 以 Δv≈n·Δa/2 換算之等效值；替代解釋：TLE 品質波動、阻力模型誤差、資料缺漏",
        "generated_at": now.to_rfc3339_opts(SecondsFormat::Secs, false),
    })
}

async fn api_provenance(State(st): St) -> Resp {
    blocking(move || json_resp(StatusCode::OK, &provenance(&st.cfg), Some(300))).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn py_round_matches_python() {
        assert_eq!(py_round(0.25, 1), 0.2);
        assert_eq!(py_round(2.675, 2), 2.67);
        assert_eq!(py_round(12.25, 1), 12.2);
        assert_eq!(py_round(0.35, 1), 0.3);
        assert_eq!(py_float(5.0), "5.0");
        assert_eq!(py_float(24.395), "24.395");
    }

    #[test]
    fn embedded_stories_valid() {
        let mut n = 0;
        for name in StoriesEmbed::iter() {
            if name.contains('/') || name == "schema.json" || !name.ends_with(".json") {
                continue;
            }
            let d: Value = serde_json::from_slice(&StoriesEmbed::get(&name).unwrap().data).unwrap();
            schema::validate(&d).unwrap_or_else(|e| panic!("{name}: {e}"));
            n += 1;
        }
        assert!(n > 0);
        assert!(StoriesEmbed::get("data/maneuvers_2026.json").is_some());
    }

    #[test]
    fn group_regex_compiles() {
        assert_eq!(GROUPS.len(), 6);
        assert_eq!(ISR_RX.len(), ISR_RES_RULES.len());
        let g = group("prc_isr").unwrap();
        assert!(g.rx.as_ref().unwrap().search("YAOGAN-41"));
        assert!(g.rx.as_ref().unwrap().search("ZY 1-02D"));
        assert!(!g.rx.as_ref().unwrap().search("STARLINK-1"));
    }
}
