//! AIS 船舶追蹤：伺服器端合併兩個來源的船位，提供給地球儀（前端 web/static/js/ais.js，與 Python 版共用）。
//!
//! 與 Python 版 scenario04/api/ais.py 同一套行為與 API：
//! - aisstream.io（WebSocket）：預設只訂閱台灣與東亞（AIS_BBOX 可覆寫）；yawc permessage-deflate；
//!   握手逾時 45 秒（實測 101 升級回應約 13 秒）；不主動 ping，改用 NO_DATA_SEC 看門狗；
//!   斷線指數退避＋抖動重連；每段連線長度記在 sessions，用來看斷線頻率。
//! - 航港局「臺灣海域船舶動態資訊系統」GeoJSON（tools/geojsonais.ashx，台灣周邊約 8,000～9,000 艘），每 60 秒輪詢。
//!   單機版預設開啟（AIS_MPB=0 關閉）；線上版（Python）預設關閉，因為不是正式開放資料、頁面沒有使用條款。
//! - 有人開 AIS 圖層才連線／輪詢，閒置 AIS_IDLE_SEC（預設 600 秒）停止。
//! - 以 MMSI 合併：位置以較新的回報為準（航港局用 Record_Time，台灣時間）；靜態欄位 aisstream 優先、
//!   航港局只補缺；每艘記錄各來源最後收到時間。船位只存在記憶體，1 小時未更新移除，航跡保留 6 小時。
//!
//! 金鑰：環境變數 AISSTREAM_API_KEY，或資料目錄的 aisstream_key.txt（可在圖層面板輸入，POST /api/ais/key）。

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures::SinkExt;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::state::AppState;

const WS_URL: &str = "wss://stream.aisstream.io/v0/stream";
const MSG_TYPES: [&str; 5] = [
    "PositionReport",
    "StandardClassBPositionReport",
    "ExtendedClassBPositionReport",
    "ShipStaticData",
    "StaticDataReport",
];
const MPB_URL: &str = "https://mpbais.motcmpb.gov.tw/aismpb/tools/geojsonais.ashx";
const MPB_REFERER: &str = "https://mpbais.motcmpb.gov.tw/aismpb/";
const MPB_INTERVAL: f64 = 60.0;
const STALE_SEC: f64 = 3600.0;
const TRACK_SEC: f64 = 6.0 * 3600.0;
const TRACK_STEP: f64 = 60.0;
const MAX_SHIPS: usize = 5000;
/// 連線中超過此秒數沒收到任何資料 → 視為失聯重連（保活由伺服器端 ping，本端不主動 ping）
const NO_DATA_SEC: f64 = 120.0;
/// 航港局沒有艏向；較新的航港局位置沿用 5 分鐘內 aisstream 的艏向
const HDG_KEEP_SEC: f64 = 300.0;
const SRC_A: &str = "aisstream";
const SRC_M: &str = "mpb";

fn now_s() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

#[derive(Default, Clone)]
struct Ship {
    mmsi: u32,
    lat: f64,
    lon: f64,
    t: f64,
    sog: Option<f64>,
    cog: Option<f64>,
    hdg: Option<i64>,
    hdg_t: f64,
    nav: Option<i64>,
    cls: &'static str,
    name: String,
    typ: Option<i64>,
    callsign: String,
    dest: String,
    imo: Option<i64>,
    length: Option<f64>,
    width: Option<f64>,
    draught: Option<f64>,
    eta: String,
    src: BTreeMap<&'static str, f64>,
}

impl Ship {
    fn moving(&self) -> bool {
        if matches!(self.nav, Some(1) | Some(5) | Some(6)) {
            return false;
        }
        self.sog.map(|s| s >= 0.5).unwrap_or(false)
    }
    fn src_code(&self) -> String {
        let mut s = String::new();
        if self.src.contains_key(SRC_A) {
            s.push('A');
        }
        if self.src.contains_key(SRC_M) {
            s.push('M');
        }
        s
    }
    fn detail(&self) -> Map<String, Value> {
        let mut m = Map::new();
        m.insert("mmsi".into(), json!(self.mmsi));
        m.insert("lat".into(), json!(self.lat));
        m.insert("lon".into(), json!(self.lon));
        m.insert("t".into(), json!(self.t));
        m.insert("sog".into(), json!(self.sog));
        m.insert("cog".into(), json!(self.cog));
        m.insert("hdg".into(), json!(self.hdg));
        if !self.cls.is_empty() {
            m.insert("cls".into(), json!(self.cls));
        }
        if self.nav.is_some() {
            m.insert("nav".into(), json!(self.nav));
        }
        for (k, v) in [("name", &self.name), ("callsign", &self.callsign), ("dest", &self.dest), ("eta", &self.eta)] {
            if !v.is_empty() {
                m.insert(k.into(), json!(v));
            }
        }
        for (k, v) in [("type", self.typ), ("imo", self.imo)] {
            if let Some(v) = v {
                m.insert(k.into(), json!(v));
            }
        }
        for (k, v) in [("length", self.length), ("width", self.width), ("draught", self.draught)] {
            if let Some(v) = v {
                m.insert(k.into(), json!(v));
            }
        }
        m.insert("src".into(), json!(self.src));
        m
    }
}

#[derive(Default)]
struct SrcStat {
    state: &'static str,
    error: String,
    msgs: u64,
    last_msg: f64,
    since: f64,
    reconnects: u64,
    sessions: VecDeque<f64>,
}

impl SrcStat {
    fn json(&self, state: &str) -> Value {
        let ses: Vec<i64> = self.sessions.iter().map(|x| x.round() as i64).collect();
        let avg = if ses.is_empty() { Value::Null } else { json!((self.sessions.iter().sum::<f64>() / ses.len() as f64).round()) };
        json!({"state": state, "error": self.error, "msgs": self.msgs,
               "last_msg": if self.last_msg > 0.0 { json!(self.last_msg) } else { Value::Null },
               "since": if self.since > 0.0 { json!(self.since) } else { Value::Null },
               "reconnects": self.reconnects, "sessions": ses, "avg_session": avg})
    }
}

#[derive(Default)]
struct Inner {
    ships: HashMap<u32, Ship>,
    tracks: HashMap<u32, VecDeque<(i64, f64, f64)>>,
    a: SrcStat,
    m: SrcStat,
    last_prune: f64,
}

/// 位置更新的欄位
struct Pos {
    lat: f64,
    lon: f64,
    t: f64,
    sog: Option<f64>,
    cog: Option<f64>,
    hdg: Option<i64>,
    nav: Option<Option<i64>>,
    cls: &'static str,
}

impl Inner {
    /// 寫入位置：較舊的回報不蓋掉較新的位置（仍記錄來源時間）
    fn put_pos(&mut self, mmsi: u32, src: &'static str, p: Pos) -> &mut Ship {
        let sh = self.ships.entry(mmsi).or_insert_with(|| Ship { mmsi, ..Default::default() });
        let e = sh.src.entry(src).or_insert(0.0);
        *e = e.max(p.t);
        if p.t >= sh.t {
            let keep_hdg = src == SRC_M && sh.hdg_t > 0.0 && p.t - sh.hdg_t <= HDG_KEEP_SEC;
            sh.lat = p.lat;
            sh.lon = p.lon;
            sh.t = p.t;
            sh.sog = p.sog;
            sh.cog = p.cog;
            if src == SRC_A {
                sh.hdg = p.hdg;
                sh.hdg_t = p.t;
            } else if !keep_hdg {
                sh.hdg = None;
            }
            if let Some(n) = p.nav {
                sh.nav = n;
            }
            if !p.cls.is_empty() {
                sh.cls = p.cls;
            }
            let tr = self.tracks.entry(mmsi).or_default();
            if tr.back().map(|q| p.t - q.0 as f64 >= TRACK_STEP).unwrap_or(true) {
                tr.push_back((p.t.round() as i64, r5(p.lat), r5(p.lon)));
                let cap = (TRACK_SEC / TRACK_STEP) as usize + 1;
                while tr.len() > cap {
                    tr.pop_front();
                }
            }
        }
        self.ships.get_mut(&mmsi).unwrap()
    }
}

pub struct Hub {
    inner: Mutex<Inner>,
    key: Mutex<String>,
    key_file: Mutex<Option<PathBuf>>,
    run_a: AtomicBool,
    run_m: AtomicBool,
    last_access: AtomicU64, // 毫秒
    idle_sec: f64,
    bbox: Value,
    mpb_on: bool,
}

static HUB: Lazy<Arc<Hub>> = Lazy::new(|| Arc::new(Hub::new()));

fn num(v: Option<&Value>) -> Option<f64> {
    match v {
        Some(Value::Number(n)) => n.as_f64(),
        _ => None,
    }
}

fn clean(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.replace('@', " ").split_whitespace().collect::<Vec<_>>().join(" "),
        _ => String::new(),
    }
}

fn r5(x: f64) -> f64 {
    (x * 1e5).round() / 1e5
}

fn r1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}

/// 航港局 Record_Time（台灣時間 "YYYY/MM/DD HH:MM:SS"）→ epoch 秒
fn mpb_time(v: Option<&Value>) -> Option<f64> {
    let s = v?.as_str()?.trim();
    let dt = chrono::NaiveDateTime::parse_from_str(s, "%Y/%m/%d %H:%M:%S").ok()?;
    Some(dt.and_utc().timestamp() as f64 - 8.0 * 3600.0)
}

fn bbox_env() -> Value {
    let def = json!([[[0.0, 100.0], [50.0, 150.0]]]); // 台灣與東亞（緯 0～50°N、經 100～150°E）
    match std::env::var("AIS_BBOX") {
        Ok(s) if !s.trim().is_empty() => match serde_json::from_str::<Value>(&s) {
            Ok(v) if v.as_array().map(|a| !a.is_empty()).unwrap_or(false) => v,
            _ => {
                tracing::warn!("AIS_BBOX 格式錯誤，改用預設（台灣與東亞）");
                def
            }
        },
        _ => def,
    }
}

impl Hub {
    fn new() -> Self {
        Hub {
            inner: Mutex::new(Inner {
                a: SrcStat { state: "idle", ..Default::default() },
                m: SrcStat { state: "idle", ..Default::default() },
                ..Default::default()
            }),
            key: Mutex::new(std::env::var("AISSTREAM_API_KEY").unwrap_or_default().trim().to_string()),
            key_file: Mutex::new(None),
            run_a: AtomicBool::new(false),
            run_m: AtomicBool::new(false),
            last_access: AtomicU64::new(0),
            idle_sec: std::env::var("AIS_IDLE_SEC").ok().and_then(|v| v.parse().ok()).unwrap_or(600.0),
            bbox: bbox_env(),
            mpb_on: std::env::var("AIS_MPB").map(|v| v.trim() != "0").unwrap_or(true),
        }
    }

    fn init_key_file(&self, home: &std::path::Path) {
        let mut kf = self.key_file.lock();
        if kf.is_some() {
            return;
        }
        let p = home.join("aisstream_key.txt");
        if self.key.lock().is_empty() {
            if let Ok(s) = std::fs::read_to_string(&p) {
                let s = s.trim().to_string();
                if !s.is_empty() {
                    *self.key.lock() = s;
                }
            }
        }
        *kf = Some(p);
    }

    fn has_key(&self) -> bool {
        !self.key.lock().is_empty()
    }

    fn idle(&self) -> bool {
        let last = self.last_access.load(Ordering::Relaxed) as f64 / 1000.0;
        now_s() - last > self.idle_sec
    }

    fn touch(self: &Arc<Self>) {
        self.last_access.store((now_s() * 1000.0) as u64, Ordering::Relaxed);
        if self.has_key() && !self.run_a.swap(true, Ordering::SeqCst) {
            self.inner.lock().a.state = "connecting";
            let hub = self.clone();
            tokio::spawn(async move { hub.run_ws().await });
        }
        if self.mpb_on && !self.run_m.swap(true, Ordering::SeqCst) {
            self.inner.lock().m.state = "connecting";
            let hub = self.clone();
            tokio::spawn(async move { hub.run_mpb().await });
        }
    }

    fn status(&self) -> Map<String, Value> {
        let g = self.inner.lock();
        let has = self.has_key();
        let a_state = if has { g.a.state } else { "no_key" };
        let mut srcs = Map::new();
        srcs.insert(SRC_A.into(), g.a.json(a_state));
        let mut states = vec![a_state];
        if self.mpb_on {
            srcs.insert(SRC_M.into(), g.m.json(g.m.state));
            states.push(g.m.state);
        }
        let overall = ["live", "connecting", "retry", "idle"].into_iter().find(|s| states.contains(s)).unwrap_or("no_key");
        let mut m = Map::new();
        m.insert("state".into(), json!(overall));
        m.insert("has_key".into(), json!(has));
        m.insert("key_settable".into(), json!(true));
        m.insert("ships".into(), json!(g.ships.len()));
        m.insert("msgs".into(), json!(g.a.msgs));
        m.insert("last_msg".into(), if g.a.last_msg > 0.0 { json!(g.a.last_msg) } else { Value::Null });
        m.insert("since".into(), if g.a.since > 0.0 { json!(g.a.since) } else { Value::Null });
        m.insert("error".into(), json!(g.a.error));
        m.insert("idle_sec".into(), json!(self.idle_sec));
        m.insert("bbox".into(), self.bbox.clone());
        m.insert("source".into(), json!(srcs.keys().cloned().collect::<Vec<_>>().join("+")));
        m.insert("sources".into(), Value::Object(srcs));
        m
    }

    fn query(&self, w: f64, s: f64, e: f64, n: f64, moving: bool, limit: usize, srcs: Option<&[String]>) -> Value {
        let now = now_s();
        self.prune(now);
        let mut st = self.status();
        let g = self.inner.lock();
        let total = g.ships.len();
        let mut out: Vec<&Ship> = g
            .ships
            .values()
            .filter(|x| x.lat >= s && x.lat <= n)
            .filter(|x| if w <= e { x.lon >= w && x.lon <= e } else { x.lon >= w || x.lon <= e })
            .filter(|x| !moving || x.moving())
            .filter(|x| srcs.map(|ss| ss.iter().any(|k| x.src.contains_key(k.as_str()))).unwrap_or(true))
            .collect();
        out.sort_by(|a, b| b.t.partial_cmp(&a.t).unwrap_or(std::cmp::Ordering::Equal));
        let trunc = out.len() > limit;
        let rows: Vec<Value> = out
            .iter()
            .take(limit)
            .map(|x| json!([x.mmsi, r5(x.lat), r5(x.lon), x.cog, x.hdg, x.sog, x.typ, x.name, x.nav, x.src_code()]))
            .collect();
        st.insert("total".into(), json!(total));
        st.insert("n".into(), json!(rows.len()));
        st.insert("truncated".into(), json!(trunc));
        st.insert("cols".into(), json!(["mmsi", "lat", "lon", "cog", "hdg", "sog", "type", "name", "nav", "src"]));
        st.insert("rows".into(), Value::Array(rows));
        Value::Object(st)
    }

    fn ship(&self, mmsi: u32) -> Option<Value> {
        let g = self.inner.lock();
        let sh = g.ships.get(&mmsi)?;
        let mut m = sh.detail();
        let tr: Vec<Value> = g.tracks.get(&mmsi).map(|t| t.iter().map(|p| json!([p.0, p.1, p.2])).collect()).unwrap_or_default();
        m.insert("track".into(), Value::Array(tr));
        Some(Value::Object(m))
    }

    /// aisstream 單則訊息（與 Python AisHub.handle 相同規則）
    fn handle(&self, msg: &Value, now: f64) {
        let mt = msg.get("MessageType").and_then(Value::as_str).unwrap_or("");
        let empty = Value::Object(Map::new());
        let body = msg.get("Message").and_then(|m| m.get(mt)).unwrap_or(&empty);
        let meta: Map<String, Value> = msg
            .get("MetaData")
            .and_then(Value::as_object)
            .map(|m| m.iter().map(|(k, v)| (k.to_lowercase(), v.clone())).collect())
            .unwrap_or_default();
        let mmsi = num(meta.get("mmsi")).or_else(|| num(body.get("UserID"))).unwrap_or(0.0);
        if !(1.0..4.3e9).contains(&mmsi) {
            return;
        }
        let mmsi = mmsi as u32;
        let mut g = self.inner.lock();
        g.a.msgs += 1;
        g.a.last_msg = now;
        let is_pos = matches!(mt, "PositionReport" | "StandardClassBPositionReport" | "ExtendedClassBPositionReport");
        if is_pos {
            let (mut lat, mut lon) = (num(body.get("Latitude")), num(body.get("Longitude")));
            if lat.is_none() || lon.is_none() {
                lat = num(meta.get("latitude"));
                lon = num(meta.get("longitude"));
            }
            let (Some(lat), Some(lon)) = (lat, lon) else { return };
            if lat.abs() > 90.0 || lon.abs() > 180.0 || (lat == 0.0 && lon == 0.0) {
                return;
            }
            if body.get("Valid") == Some(&Value::Bool(false)) {
                return;
            }
            let pr = mt == "PositionReport";
            let p = Pos {
                lat,
                lon,
                t: now,
                sog: num(body.get("Sog")).filter(|v| *v < 102.3).map(r1),
                cog: num(body.get("Cog")).filter(|v| *v < 360.0).map(r1),
                hdg: num(body.get("TrueHeading")).filter(|v| *v < 360.0).map(|v| v as i64),
                nav: if pr { Some(num(body.get("NavigationalStatus")).filter(|v| *v != 15.0).map(|v| v as i64)) } else { None },
                cls: if pr { "A" } else { "B" },
            };
            let sh = g.put_pos(mmsi, SRC_A, p);
            if mt == "ExtendedClassBPositionReport" {
                apply_static(sh, body);
            }
            if sh.name.is_empty() {
                sh.name = clean(meta.get("shipname"));
            }
        } else if matches!(mt, "ShipStaticData" | "StaticDataReport") {
            let Some(sh) = g.ships.get_mut(&mmsi) else { return }; // 沒位置的靜態資料不留
            if mt == "StaticDataReport" {
                let a = body.get("ReportA").unwrap_or(&empty);
                let b = body.get("ReportB").unwrap_or(&empty);
                if a.get("Valid") == Some(&Value::Bool(true)) {
                    apply_static(sh, &json!({"Name": a.get("Name")}));
                }
                if b.get("Valid") == Some(&Value::Bool(true)) {
                    apply_static(
                        sh,
                        &json!({"Type": b.get("ShipType"), "CallSign": b.get("CallSign"), "Dimension": b.get("Dimension")}),
                    );
                }
            } else {
                apply_static(sh, body);
            }
            if sh.name.is_empty() {
                sh.name = clean(meta.get("shipname"));
            }
        }
    }

    /// 航港局 GeoJSON（與 Python AisHub.handle_mpb 相同規則），回傳有效筆數
    fn handle_mpb(&self, data: &Value) -> usize {
        let Some(feats) = data.get("features").and_then(Value::as_array) else { return 0 };
        let mut g = self.inner.lock();
        let mut n = 0;
        for f in feats {
            let Some(p) = f.get("properties") else { continue };
            let s = |k: &str| p.get(k).and_then(Value::as_str).map(str::trim).unwrap_or("");
            let Ok(mmsi) = s("MMSI").parse::<u32>() else { continue };
            let (Some(lat), Some(lon), Some(t)) = (num(p.get("Latitude")), num(p.get("Longitude")), mpb_time(p.get("Record_Time")))
            else {
                continue;
            };
            if mmsi == 0 || lat.abs() > 90.0 || lon.abs() > 180.0 || (lat == 0.0 && lon == 0.0) {
                continue;
            }
            let nav = s("Navigational_Status").parse::<i64>().ok().filter(|v| *v != 15);
            let pos = Pos {
                lat,
                lon,
                t,
                sog: num(p.get("SOG")).filter(|v| *v < 102.3).map(r1),
                cog: num(p.get("COG")).filter(|v| *v < 360.0).map(r1),
                hdg: None,
                nav: Some(nav),
                cls: "",
            };
            let sh = g.put_pos(mmsi, SRC_M, pos);
            // 靜態欄位只補缺；剔除常見佔位值
            if sh.name.is_empty() {
                let nm = clean(p.get("ShipName"));
                if !nm.is_empty() && nm != "1" {
                    sh.name = nm;
                }
            }
            if sh.typ.is_none() {
                sh.typ = num(p.get("Ship_and_Cargo_Type")).filter(|v| *v > 0.0).map(|v| v as i64);
            }
            if sh.callsign.is_empty() {
                let cs = clean(p.get("Call_Sign"));
                if !cs.trim_matches('0').is_empty() && cs != "1234567" {
                    sh.callsign = cs;
                }
            }
            if sh.imo.is_none() {
                sh.imo = s("IMO_Number").parse::<i64>().ok().filter(|v| (1_000_000..=9_999_999).contains(v));
            }
            n += 1;
        }
        n
    }

    fn prune(&self, now: f64) {
        let mut g = self.inner.lock();
        if now - g.last_prune < 30.0 {
            return;
        }
        g.last_prune = now;
        let stale: Vec<u32> = g.ships.iter().filter(|(_, s)| now - s.t > STALE_SEC).map(|(m, _)| *m).collect();
        for m in stale {
            g.ships.remove(&m);
            g.tracks.remove(&m);
        }
        for tr in g.tracks.values_mut() {
            while tr.front().map(|p| now - p.0 as f64 > TRACK_SEC).unwrap_or(false) {
                tr.pop_front();
            }
        }
    }

    async fn sleep_unless_idle(&self, sec: f64) {
        let end = now_s() + sec;
        while now_s() < end && !self.idle() {
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    }

    async fn run_ws(self: Arc<Self>) {
        let mut backoff = 2.0_f64;
        while !self.idle() {
            self.inner.lock().a.state = "connecting";
            let mut t_live = 0.0;
            let r = self.session(&mut t_live).await;
            if let Err(e) = r {
                let msg: String = format!("{e:#}").chars().take(300).collect();
                let dur = if t_live > 0.0 { now_s() - t_live } else { 0.0 };
                tracing::warn!("aisstream 連線中斷（本段 {dur:.0} 秒）：{msg}（{backoff:.0} 秒後重連）");
                {
                    let mut g = self.inner.lock();
                    if t_live > 0.0 {
                        g.a.sessions.push_back(dur);
                        while g.a.sessions.len() > 20 {
                            g.a.sessions.pop_front();
                        }
                        g.a.reconnects += 1;
                    }
                    g.a.error = msg;
                    g.a.state = "retry";
                }
                let jitter = 0.7 + 0.6 * ((now_s().fract() * 1e6) as u64 % 1000) as f64 / 1000.0;
                self.sleep_unless_idle(backoff * jitter).await;
                backoff = (backoff * 2.0).min(120.0);
            }
            if t_live > 0.0 {
                backoff = backoff.min(4.0);
            }
        }
        self.inner.lock().a.state = "idle";
        self.run_a.store(false, Ordering::SeqCst);
        tracing::info!("aisstream 閒置 {:.0} 秒，已斷線", self.idle_sec);
    }

    async fn session(&self, t_live: &mut f64) -> anyhow::Result<()> {
        use yawc::{OpCode, Options, WebSocket};
        let key = self.key.lock().clone();
        let opts = Options::default().with_low_latency_compression().with_max_payload_read(4 << 20);
        let mut ws = tokio::time::timeout(Duration::from_secs(45), WebSocket::connect(WS_URL.parse()?).with_options(opts))
            .await
            .map_err(|_| anyhow::anyhow!("連線逾時"))??;
        let sub = json!({"APIKey": key, "BoundingBoxes": self.bbox, "FilterMessageTypes": MSG_TYPES});
        ws.send(yawc::Frame::text(sub.to_string())).await?;
        tracing::info!("aisstream 已連線，訂閱範圍 {}", self.bbox);
        let mut last_rx = now_s();
        loop {
            if self.idle() {
                return Ok(());
            }
            let f = match tokio::time::timeout(Duration::from_secs(20), ws.next_frame()).await {
                Err(_) => {
                    if now_s() - last_rx > NO_DATA_SEC {
                        anyhow::bail!("{NO_DATA_SEC:.0} 秒沒有收到資料，重新連線");
                    }
                    continue;
                }
                Ok(r) => r?,
            };
            last_rx = now_s();
            match f.opcode() {
                OpCode::Text | OpCode::Binary => {
                    let Ok(m) = serde_json::from_slice::<Value>(f.payload()) else { continue };
                    if let Some(e) = m.get("error") {
                        anyhow::bail!("{}", e.to_string().chars().take(200).collect::<String>());
                    }
                    if m.get("MessageType").and_then(Value::as_str) == Some("SubscriptionConfirmation") {
                        tracing::info!("aisstream 訂閱確認：{}", m.get("Message").unwrap_or(&serde_json::Value::Null));
                        continue;
                    }
                    {
                        let mut g = self.inner.lock();
                        if g.a.state != "live" {
                            g.a.state = "live";
                            g.a.since = now_s();
                            g.a.error.clear();
                            *t_live = now_s();
                        }
                    }
                    let now = now_s();
                    self.handle(&m, now);
                    self.prune(now);
                }
                OpCode::Close => anyhow::bail!("伺服器關閉連線{}", f.close_code().map(|c| format!("（{c:?}）")).unwrap_or_default()),
                _ => {}
            }
        }
    }

    async fn fetch_mpb() -> anyhow::Result<Value> {
        static CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
            reqwest::Client::builder()
                .user_agent("Mozilla/5.0 (ATRDC SatDashboard AIS layer)")
                .timeout(Duration::from_secs(45))
                .build()
                .expect("reqwest client")
        });
        let r = CLIENT.get(MPB_URL).header("Referer", MPB_REFERER).send().await?.error_for_status()?;
        let b = r.bytes().await?;
        Ok(serde_json::from_slice(&b)?)
    }

    async fn run_mpb(self: Arc<Self>) {
        let mut fails = 0u32;
        while !self.idle() {
            let t0 = now_s();
            let wait = match Self::fetch_mpb().await {
                Ok(v) => {
                    let n = self.handle_mpb(&v);
                    {
                        let mut g = self.inner.lock();
                        g.m.msgs += n as u64;
                        g.m.last_msg = now_s();
                        if g.m.state != "live" {
                            g.m.since = now_s();
                        }
                        g.m.state = "live";
                        g.m.error.clear();
                    }
                    fails = 0;
                    self.prune(now_s());
                    MPB_INTERVAL - (now_s() - t0)
                }
                Err(e) => {
                    fails += 1;
                    let msg: String = format!("{e:#}").chars().take(300).collect();
                    tracing::warn!("航港局 AIS 讀取失敗：{msg}");
                    let mut g = self.inner.lock();
                    g.m.error = msg;
                    g.m.state = "retry";
                    (MPB_INTERVAL * fails as f64).min(600.0)
                }
            };
            self.sleep_unless_idle(wait.max(5.0)).await;
        }
        self.inner.lock().m.state = "idle";
        self.run_m.store(false, Ordering::SeqCst);
    }
}

fn apply_static(sh: &mut Ship, b: &Value) {
    let nm = clean(b.get("Name"));
    if !nm.is_empty() {
        sh.name = nm;
    }
    if let Some(t) = num(b.get("Type")).filter(|v| *v > 0.0) {
        sh.typ = Some(t as i64);
    }
    let cs = clean(b.get("CallSign"));
    if !cs.is_empty() {
        sh.callsign = cs;
    }
    let ds = clean(b.get("Destination"));
    if !ds.is_empty() {
        sh.dest = ds;
    }
    if let Some(i) = num(b.get("ImoNumber")).filter(|v| *v > 0.0) {
        sh.imo = Some(i as i64);
    }
    if let Some(d) = b.get("Dimension").filter(|d| d.is_object()) {
        let g = |k| num(d.get(k)).unwrap_or(0.0);
        let (l, w) = (g("A") + g("B"), g("C") + g("D"));
        if l > 0.0 {
            sh.length = Some(l);
        }
        if w > 0.0 {
            sh.width = Some(w);
        }
    }
    if let Some(dr) = num(b.get("MaximumStaticDraught")).filter(|v| *v > 0.0) {
        sh.draught = Some(dr);
    }
    if let Some(e) = b.get("Eta").filter(|e| num(e.get("Month")).unwrap_or(0.0) > 0.0) {
        let g = |k| num(e.get(k)).unwrap_or(0.0) as i64;
        sh.eta = format!("{:02}-{:02} {:02}:{:02}", g("Month"), g("Day"), g("Hour"), g("Minute"));
    }
}

// ── HTTP ─────────────────────────────────────────────────────────────────────

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/ais/status", get(api_status))
        .route("/api/ais/ships", get(api_ships))
        .route("/api/ais/ship/{mmsi}", get(api_ship))
        .route("/api/ais/key", post(api_key))
}

fn hub(st: &AppState) -> Arc<Hub> {
    HUB.init_key_file(&st.cfg.home);
    HUB.clone()
}

async fn api_status(State(st): State<Arc<AppState>>) -> Json<Value> {
    Json(Value::Object(hub(&st).status()))
}

#[derive(Deserialize)]
struct ShipsQ {
    w: Option<f64>,
    s: Option<f64>,
    e: Option<f64>,
    n: Option<f64>,
    moving: Option<String>,
    limit: Option<usize>,
    src: Option<String>,
}

async fn api_ships(State(st): State<Arc<AppState>>, Query(q): Query<ShipsQ>) -> Json<Value> {
    let h = hub(&st);
    h.touch();
    let c = |v: Option<f64>, d: f64, lo: f64, hi: f64| v.filter(|x| x.is_finite()).unwrap_or(d).clamp(lo, hi);
    let lim = q.limit.unwrap_or(MAX_SHIPS).clamp(1, MAX_SHIPS);
    let srcs: Option<Vec<String>> = q
        .src
        .as_deref()
        .filter(|s| !s.is_empty())
        .map(|s| s.split(',').filter(|k| *k == SRC_A || *k == SRC_M).map(String::from).collect());
    Json(h.query(
        c(q.w, -180.0, -180.0, 180.0),
        c(q.s, -90.0, -90.0, 90.0),
        c(q.e, 180.0, -180.0, 180.0),
        c(q.n, 90.0, -90.0, 90.0),
        q.moving.as_deref() == Some("1"),
        lim,
        srcs.as_deref(),
    ))
}

async fn api_ship(State(st): State<Arc<AppState>>, Path(mmsi): Path<u32>) -> Response {
    let h = hub(&st);
    h.touch();
    match h.ship(mmsi) {
        Some(v) => Json(v).into_response(),
        None => (StatusCode::NOT_FOUND, Json(json!({"error": "not found"}))).into_response(),
    }
}

#[derive(Deserialize)]
struct KeyBody {
    key: String,
}

/// 單機版：在圖層面板輸入金鑰，存到資料目錄 aisstream_key.txt（只接受本機連線）
async fn api_key(
    State(st): State<Arc<AppState>>,
    axum::extract::ConnectInfo(addr): axum::extract::ConnectInfo<std::net::SocketAddr>,
    Json(b): Json<KeyBody>,
) -> Response {
    if !addr.ip().is_loopback() {
        return (StatusCode::FORBIDDEN, "只接受本機設定金鑰").into_response();
    }
    let k = b.key.trim().to_string();
    if k.len() < 16 || k.len() > 128 || !k.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return (StatusCode::BAD_REQUEST, "金鑰格式不正確").into_response();
    }
    let h = hub(&st);
    let path = h.key_file.lock().clone();
    if let Some(p) = path {
        if let Some(d) = p.parent() {
            let _ = std::fs::create_dir_all(d);
        }
        if let Err(e) = std::fs::write(&p, &k) {
            return (StatusCode::INTERNAL_SERVER_ERROR, format!("寫入失敗：{e}")).into_response();
        }
    }
    *h.key.lock() = k;
    h.inner.lock().a.error.clear();
    h.touch();
    Json(json!({"ok": true})).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pos(mmsi: u32, lat: f64, lon: f64, sog: f64, nav: i64) -> Value {
        json!({"MessageType": "PositionReport", "MetaData": {"MMSI": mmsi, "ShipName": format!("TEST {mmsi}  "), "latitude": lat, "longitude": lon},
               "Message": {"PositionReport": {"UserID": mmsi, "Valid": true, "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": 90.0, "TrueHeading": 91, "NavigationalStatus": nav}}})
    }

    fn rt(ts: f64) -> String {
        chrono::DateTime::from_timestamp(ts as i64 + 8 * 3600, 0).unwrap().naive_utc().format("%Y/%m/%d %H:%M:%S").to_string()
    }

    fn feat(mmsi: u32, lat: f64, lon: f64, ts: f64, name: &str, imo: &str, cs: &str) -> Value {
        json!({"type": "Feature", "properties": {"MMSI": mmsi.to_string(), "ShipName": name, "IMO_Number": imo, "Call_Sign": cs,
               "Navigational_Status": "15", "SOG": 5.0, "COG": 90.0, "Ship_and_Cargo_Type": 30, "Longitude": lon, "Latitude": lat,
               "Record_Time": rt(ts)}})
    }

    #[test]
    fn merge_filter_prune() {
        let h = Hub::new();
        let t0 = 1_800_000_000.0;
        let st = json!({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 1},
            "Message": {"ShipStaticData": {"UserID": 1, "Valid": true, "Name": "EVER GIVEN@@@", "Type": 70, "CallSign": "H3RC ",
              "ImoNumber": 9811000, "Destination": "KAOHSIUNG@@", "MaximumStaticDraught": 14.5,
              "Dimension": {"A": 300, "B": 100, "C": 30, "D": 29}, "Eta": {"Month": 11, "Day": 25, "Hour": 8, "Minute": 30}}}});
        h.handle(&st, t0);
        assert!(h.inner.lock().ships.is_empty(), "無位置的靜態資料不建檔");
        h.handle(&pos(1, 22.6, 120.3, 10.0, 0), t0);
        h.handle(&st, t0 + 1.0);
        {
            let g = h.inner.lock();
            let s = &g.ships[&1];
            assert_eq!((s.name.as_str(), s.typ, s.length, s.width), ("EVER GIVEN", Some(70), Some(400.0), Some(59.0)));
            assert_eq!((s.dest.as_str(), s.imo, s.eta.as_str()), ("KAOHSIUNG", Some(9811000), "11-25 08:30"));
        }
        h.handle(&pos(2, 25.1, 121.7, 0.1, 1), t0);
        h.handle(&pos(3, 0.0, 0.0, 1.0, 0), t0);
        h.handle(&pos(5, 24.0, 119.0, 102.3, 0), t0);
        h.handle(&pos(7, 35.0, -179.5, 5.0, 0), t0);
        let q = |w, s, e, n, mv| {
            let v = h.query(w, s, e, n, mv, 5000, None);
            let mut ids: Vec<u64> = v["rows"].as_array().unwrap().iter().map(|r| r[0].as_u64().unwrap()).collect();
            ids.sort();
            ids
        };
        assert_eq!(q(118.0, 21.0, 123.0, 26.0, false), vec![1, 2, 5]);
        assert_eq!(q(118.0, 21.0, 123.0, 26.0, true), vec![1]);
        assert_eq!(q(170.0, 30.0, -170.0, 40.0, false), vec![7]);
        assert_eq!(h.inner.lock().ships[&5].sog, None);
        assert_eq!(h.inner.lock().ships[&2].name, "TEST 2");
        for k in 1..400 {
            h.handle(&pos(1, 22.6 + k as f64 * 0.001, 120.3, 10.0, 0), t0 + k as f64 * 30.0);
        }
        let n = h.ship(1).unwrap()["track"].as_array().unwrap().len();
        assert!((195..=201).contains(&n), "航跡點數 {n}");
        h.inner.lock().last_prune = 0.0;
        h.prune(t0 + 400.0 * 30.0 + STALE_SEC + 1.0);
        assert!(h.inner.lock().ships.is_empty());
    }

    #[test]
    fn mpb_merge() {
        let h = Hub::new();
        let now = 1_800_000_000.0;
        assert_eq!(mpb_time(Some(&json!(rt(now)))), Some(now));
        let n = h.handle_mpb(&json!({"features": [
            feat(1, 23.0, 120.0, now - 60.0, "MINGDONGYU 1   ", "", "       "),
            feat(2, 24.0, 121.0, now - 30.0, "1", "123456789", "0000000"),
            feat(3, 0.0, 0.0, now, "X", "", ""),
            {"properties": {"MMSI": "x"}},
            feat(4, 22.5, 119.5, now - 10.0, "B", "9811000", "BX12 ")]}));
        assert_eq!(n, 3);
        {
            let g = h.inner.lock();
            let s1 = &g.ships[&1];
            assert_eq!((s1.name.as_str(), s1.typ, s1.nav, s1.hdg, s1.t), ("MINGDONGYU 1", Some(30), None, None, now - 60.0));
            let s2 = &g.ships[&2];
            assert!(s2.name.is_empty() && s2.imo.is_none() && s2.callsign.is_empty(), "剔除佔位值");
            assert_eq!((g.ships[&4].imo, g.ships[&4].callsign.as_str()), (Some(9811000), "BX12"));
        }
        // aisstream 較新：取代位置、帶艏向、靜態覆蓋
        let mut p = pos(1, 23.01, 120.01, 12.0, 0);
        p["Message"]["PositionReport"]["TrueHeading"] = json!(45);
        h.handle(&p, now);
        h.handle(&json!({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 1},
            "Message": {"ShipStaticData": {"UserID": 1, "Name": "REAL NAME", "Type": 70}}}), now);
        // 較舊的航港局回報不蓋位置、不改靜態
        h.handle_mpb(&json!({"features": [feat(1, 23.5, 120.5, now - 120.0, "OTHER", "", "")]}));
        {
            let g = h.inner.lock();
            let s1 = &g.ships[&1];
            assert_eq!((s1.lat, s1.hdg, s1.name.as_str(), s1.typ), (23.01, Some(45), "REAL NAME", Some(70)));
        }
        h.handle_mpb(&json!({"features": [feat(1, 23.05, 120.05, now + 120.0, "", "", "")]}));
        {
            let g = h.inner.lock(); // parking_lot 不可重入：同一敘述內只能鎖一次
            assert_eq!((g.ships[&1].lat, g.ships[&1].hdg), (23.05, Some(45)));
        }
        h.handle_mpb(&json!({"features": [feat(1, 23.1, 120.1, now + 600.0, "", "", "")]}));
        assert_eq!(h.inner.lock().ships[&1].hdg, None);
        let v = h.query(118.0, 21.0, 123.0, 26.0, false, 5000, None);
        let mut codes: Vec<(u64, String)> =
            v["rows"].as_array().unwrap().iter().map(|r| (r[0].as_u64().unwrap(), r[9].as_str().unwrap().to_string())).collect();
        codes.sort();
        assert_eq!(codes, vec![(1, "AM".into()), (2, "M".into()), (4, "M".into())]);
        let only_a = h.query(118.0, 21.0, 123.0, 26.0, false, 5000, Some(&["aisstream".to_string()]));
        assert_eq!(only_a["n"], json!(1));
        assert_eq!(v["bbox"], json!([[[0.0, 100.0], [50.0, 150.0]]]));
    }
}
