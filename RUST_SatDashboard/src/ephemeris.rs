//! 星歷資料狀態與一鍵重抓（客戶回饋第 4 項）、SATCAT 再入（DECAY）列表（第 3 項）。
//!
//! - 重抓的 TLE 存成覆蓋層 <資料目錄>\user_private\ephemeris\gp_latest.tle，索引建立時只採用比 DB 新的曆元
//!   （DB 檔本身不改，下次「檢查更新」下載新 DB 也不衝突）。
//! - 來源：CelesTrak（免帳號，active 群組約 1.2 萬顆＋群組成員逐顆補抓）或 Space-Track（需帳號，全目錄未再入物體）。
//! - SATCAT（含 DECAY 再入日期）存成 user_private\ephemeris\satcat.json；來源同上。
//! - 依兩站使用規範限制頻率：CelesTrak GP 2 小時、Space-Track GP 1 小時、SATCAT 12 小時各一次
//!   （SATDASH_EPHEM_MIN_INTERVAL_S 可覆寫，測試用）。

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use axum::extract::{Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use chrono::{DateTime, NaiveDate, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::auth::{atomic_write, Caller};
use crate::config::Config;
use crate::satadmin::tle_epoch;
use crate::state::AppState;
use crate::userdata::{self, UserTle};

const OVERLAY: &str = "gp_latest.tle";
const SATCAT: &str = "satcat.json";
const META: &str = "meta.json";
const CATNR_MAX: usize = 30;

fn celestrak_base() -> String {
    std::env::var("SATDASH_CELESTRAK_BASE").unwrap_or_else(|_| "https://celestrak.org".into())
}
fn spacetrack_base() -> String {
    std::env::var("SATDASH_SPACETRACK_BASE").unwrap_or_else(|_| "https://www.space-track.org".into())
}
fn min_interval(key: &str) -> u64 {
    if let Some(v) = std::env::var("SATDASH_EPHEM_MIN_INTERVAL_S").ok().and_then(|v| v.parse().ok()) {
        return v;
    }
    match key {
        "gp:celestrak" => 7200,
        "gp:spacetrack" => 3600,
        _ => 43200,
    }
}

pub fn dir(cfg: &Config) -> PathBuf {
    cfg.home.join("user_private").join("ephemeris")
}

fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

// ── 覆蓋層 ───────────────────────────────────────────────────────────────────

pub fn load_overlay(cfg: &Config) -> BTreeMap<u32, UserTle> {
    let p = dir(cfg).join(OVERLAY);
    match std::fs::read_to_string(&p) {
        Ok(t) => userdata::parse_tle_text(&t, OVERLAY),
        Err(_) => BTreeMap::new(),
    }
}

/// 合併：同一顆保留曆元較新者
fn merge_newer(base: &mut BTreeMap<u32, UserTle>, add: BTreeMap<u32, UserTle>) {
    for (n, t) in add {
        let newer = match base.get(&n) {
            None => true,
            Some(old) => tle_epoch(&t.line1) > tle_epoch(&old.line1),
        };
        if newer {
            base.insert(n, t);
        }
    }
}

fn write_overlay(cfg: &Config, m: &BTreeMap<u32, UserTle>) -> anyhow::Result<()> {
    let mut s = String::with_capacity(m.len() * 170);
    s.push_str(&format!("# SatDashboard 重抓星歷覆蓋層（{}，{} 顆）；索引只採用比 DB 新的曆元\n", now_iso(), m.len()));
    for t in m.values() {
        let name = if t.name.is_empty() { "UNKNOWN" } else { t.name.as_str() };
        s.push_str(&format!("0 {name}\n{}\n{}\n", t.line1, t.line2));
    }
    atomic_write(&dir(cfg).join(OVERLAY), s.as_bytes())
}

// ── SATCAT ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SatcatRec {
    pub norad: u32,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub intl: String,
    #[serde(default)]
    pub object_type: String,
    #[serde(default)]
    pub ops_status: String,
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub launch: String,
    #[serde(default)]
    pub decay: String,
    #[serde(default)]
    pub period: Option<f64>,
    #[serde(default)]
    pub incl: Option<f64>,
    #[serde(default)]
    pub apogee: Option<f64>,
    #[serde(default)]
    pub perigee: Option<f64>,
}

pub type Satcat = Arc<HashMap<u32, SatcatRec>>;

type SatcatKey = (PathBuf, Option<SystemTime>, Option<PathBuf>, Option<SystemTime>);
static SATCAT_CACHE: Lazy<Mutex<Option<(SatcatKey, Satcat, Option<FetchRec>)>>> = Lazy::new(|| Mutex::new(None));

/// 資料庫內的 satcat／satcat_meta 表（本機每日管線 tools/update_satcat.py 寫入、跟著 DB 發布）
fn db_satcat(db: &std::path::Path) -> Option<(Vec<SatcatRec>, FetchRec)> {
    let con = crate::index::open_ro(db).ok()?;
    let has = |t: &str| -> bool {
        con.query_row("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [t], |r| r.get::<_, i64>(0))
            .map(|n| n > 0)
            .unwrap_or(false)
    };
    if !has("satcat") || !has("satcat_meta") {
        return None;
    }
    let meta = con
        .query_row("SELECT source, fetched_at, count, decayed FROM satcat_meta LIMIT 1", [], |r| {
            Ok(FetchRec {
                source: format!("資料庫（{}）", r.get::<_, Option<String>>(0)?.unwrap_or_default()),
                fetched_at: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                count: r.get::<_, Option<i64>>(2)?.unwrap_or(0) as usize,
                decayed: r.get::<_, Option<i64>>(3)?.unwrap_or(0) as usize,
                ..Default::default()
            })
        })
        .ok()?;
    let mut st = con
        .prepare("SELECT norad_id, name, intl, object_type, ops_status, owner, launch, decay, period, incl, apogee, perigee FROM satcat")
        .ok()?;
    let s = |v: Option<String>| v.unwrap_or_default().trim().to_string();
    let rows: Vec<SatcatRec> = st
        .query_map([], |r| {
            Ok(SatcatRec {
                norad: r.get::<_, i64>(0)? as u32,
                name: s(r.get(1)?),
                intl: s(r.get(2)?),
                object_type: s(r.get(3)?),
                ops_status: s(r.get(4)?),
                owner: s(r.get(5)?),
                launch: s(r.get(6)?),
                decay: s(r.get(7)?),
                period: r.get(8)?,
                incl: r.get(9)?,
                apogee: r.get(10)?,
                perigee: r.get(11)?,
            })
        })
        .ok()?
        .flatten()
        .collect();
    (!rows.is_empty()).then_some((rows, meta))
}

/// SATCAT：本機重抓的 satcat.json 與資料庫內 satcat 表取較新者（任一檔案更新才重讀）
pub fn satcat(cfg: &Config) -> Satcat {
    satcat_and_meta(cfg).0
}

/// 目前生效之 SATCAT 來源資訊
pub fn satcat_meta(cfg: &Config) -> Option<FetchRec> {
    satcat_and_meta(cfg).1
}

fn satcat_and_meta(cfg: &Config) -> (Satcat, Option<FetchRec>) {
    let p = dir(cfg).join(SATCAT);
    let mt = std::fs::metadata(&p).and_then(|m| m.modified()).ok();
    let db = cfg.resolve_db();
    let dbmt = db.as_ref().and_then(|d| std::fs::metadata(d).ok()).and_then(|m| m.modified().ok());
    let key: SatcatKey = (p.clone(), mt, db.clone(), dbmt);
    let mut c = SATCAT_CACHE.lock();
    if let Some((k, v, m)) = c.as_ref() {
        if *k == key {
            return (v.clone(), m.clone());
        }
    }
    let file: Option<(Vec<SatcatRec>, Option<FetchRec>)> = std::fs::read(&p)
        .ok()
        .and_then(|b| serde_json::from_slice::<Vec<SatcatRec>>(&b).ok())
        .filter(|v| !v.is_empty())
        .map(|v| (v, read_meta(cfg).satcat));
    let from_db = db.as_deref().and_then(db_satcat);
    let file_at = file.as_ref().and_then(|f| f.1.as_ref().map(|m| m.fetched_at.clone())).unwrap_or_default();
    let (rows, meta) = match (file, from_db) {
        (Some(f), Some(d)) => {
            if d.1.fetched_at > file_at { (d.0, Some(d.1)) } else { (f.0, f.1) }
        }
        (Some(f), None) => (f.0, f.1),
        (None, Some(d)) => (d.0, Some(d.1)),
        (None, None) => (Vec::new(), None),
    };
    let v: Satcat = Arc::new(rows.into_iter().map(|r| (r.norad, r)).collect());
    *c = Some((key, v.clone(), meta.clone()));
    (v, meta)
}

fn fnum(s: &str) -> Option<f64> {
    s.trim().parse().ok()
}

/// CelesTrak satcat.csv
pub fn parse_celestrak_satcat(text: &str) -> anyhow::Result<Vec<SatcatRec>> {
    let mut rdr = csv::ReaderBuilder::new().flexible(true).from_reader(text.trim_start_matches('\u{FEFF}').as_bytes());
    let h: Vec<String> = rdr.headers()?.iter().map(|s| s.trim().to_uppercase()).collect();
    let col = |k: &str| h.iter().position(|x| x == k);
    let ci = col("NORAD_CAT_ID").ok_or_else(|| anyhow::anyhow!("satcat.csv 缺 NORAD_CAT_ID 欄"))?;
    let (cn, cid, ct, cs, co, cl, cd, cp, cinc, ca, cpe) = (
        col("OBJECT_NAME"), col("OBJECT_ID"), col("OBJECT_TYPE"), col("OPS_STATUS_CODE"), col("OWNER"),
        col("LAUNCH_DATE"), col("DECAY_DATE"), col("PERIOD"), col("INCLINATION"), col("APOGEE"), col("PERIGEE"),
    );
    let mut out = Vec::new();
    for r in rdr.records() {
        let r = r?;
        let g = |c: Option<usize>| c.and_then(|i| r.get(i)).unwrap_or("").trim().to_string();
        let Ok(n) = g(Some(ci)).parse::<u32>() else { continue };
        out.push(SatcatRec {
            norad: n,
            name: g(cn),
            intl: g(cid),
            object_type: g(ct),
            ops_status: g(cs),
            owner: g(co),
            launch: g(cl),
            decay: g(cd),
            period: fnum(&g(cp)),
            incl: fnum(&g(cinc)),
            apogee: fnum(&g(ca)),
            perigee: fnum(&g(cpe)),
        });
    }
    if out.len() < 1000 {
        anyhow::bail!("satcat.csv 只有 {} 筆，疑似下載不完整", out.len());
    }
    Ok(out)
}

/// Space-Track class/satcat（JSON）
pub fn parse_spacetrack_satcat(text: &str) -> anyhow::Result<Vec<SatcatRec>> {
    let v: Vec<HashMap<String, Value>> = serde_json::from_str(text).map_err(|e| anyhow::anyhow!("SATCAT JSON 解析失敗：{e}"))?;
    let s = |m: &HashMap<String, Value>, k: &str| -> String {
        match m.get(k) {
            Some(Value::String(x)) => x.trim().to_string(),
            Some(Value::Number(x)) => x.to_string(),
            _ => String::new(),
        }
    };
    let out: Vec<SatcatRec> = v
        .iter()
        .filter_map(|m| {
            let n = s(m, "NORAD_CAT_ID").parse::<u32>().ok()?;
            let name = Some(s(m, "SATNAME")).filter(|x| !x.is_empty()).unwrap_or_else(|| s(m, "OBJECT_NAME"));
            Some(SatcatRec {
                norad: n,
                name,
                intl: Some(s(m, "INTLDES")).filter(|x| !x.is_empty()).unwrap_or_else(|| s(m, "OBJECT_ID")),
                object_type: s(m, "OBJECT_TYPE"),
                ops_status: String::new(),
                owner: s(m, "COUNTRY"),
                launch: s(m, "LAUNCH"),
                decay: s(m, "DECAY"),
                period: fnum(&s(m, "PERIOD")),
                incl: fnum(&s(m, "INCLINATION")),
                apogee: fnum(&s(m, "APOGEE")),
                perigee: fnum(&s(m, "PERIGEE")),
            })
        })
        .collect();
    if out.is_empty() {
        anyhow::bail!("Space-Track SATCAT 回傳 0 筆");
    }
    Ok(out)
}

// ── 中繼資料 ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FetchRec {
    pub source: String,
    pub fetched_at: String,
    pub count: usize,
    #[serde(default)]
    pub newer: usize,
    #[serde(default)]
    pub added: usize,
    #[serde(default)]
    pub decayed: usize,
    #[serde(default)]
    pub by: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Meta {
    #[serde(default)]
    pub gp: Option<FetchRec>,
    #[serde(default)]
    pub satcat: Option<FetchRec>,
    /// 每個來源最後嘗試時間（頻率限制用），key：gp:celestrak／gp:spacetrack／satcat:celestrak／satcat:spacetrack
    #[serde(default)]
    pub attempts: BTreeMap<String, String>,
}

fn read_meta(cfg: &Config) -> Meta {
    std::fs::read(dir(cfg).join(META)).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}
fn write_meta(cfg: &Config, m: &Meta) {
    if let Ok(b) = serde_json::to_vec_pretty(m) {
        let _ = atomic_write(&dir(cfg).join(META), &b);
    }
}

/// 頻率限制：回傳尚需等待秒數（0＝可執行）
fn wait_secs(m: &Meta, key: &str) -> u64 {
    let Some(t) = m.attempts.get(key).and_then(|s| DateTime::parse_from_rfc3339(s).ok()) else { return 0 };
    let el = (Utc::now() - t.with_timezone(&Utc)).num_seconds().max(0) as u64;
    min_interval(key).saturating_sub(el)
}

// ── Space-Track 帳密 ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StCred {
    identity: String,
    password: String,
}

fn cred_file(cfg: &Config) -> PathBuf {
    cfg.home.join("user_private").join("spacetrack.json")
}

/// （帳號, 密碼, 來源：env／file）
fn st_cred(cfg: &Config) -> Option<(String, String, &'static str)> {
    let env = |a: &str, b: &str| std::env::var(a).ok().filter(|s| !s.is_empty()).or_else(|| std::env::var(b).ok().filter(|s| !s.is_empty()));
    if let (Some(u), Some(p)) = (env("SPACETRACK_USER", "SPACE_TRACK_IDENTITY"), env("SPACETRACK_PASS", "SPACE_TRACK_PASSWORD")) {
        return Some((u, p, "env"));
    }
    let c: StCred = serde_json::from_slice(&std::fs::read(cred_file(cfg)).ok()?).ok()?;
    (!c.identity.is_empty() && !c.password.is_empty()).then_some((c.identity, c.password, "file"))
}

fn mask(u: &str) -> String {
    let (a, b) = u.split_once('@').unwrap_or((u, ""));
    let keep: String = a.chars().take(2).collect();
    format!("{keep}***{}", if b.is_empty() { String::new() } else { format!("@{b}") })
}

// ── 工作狀態 ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize)]
pub struct Job {
    pub running: bool,
    pub kind: String,
    pub source: String,
    pub by: String,
    pub started_at: String,
    pub finished_at: String,
    pub ok: Option<bool>,
    pub step: String,
    pub log: Vec<String>,
}

static JOB: Lazy<Mutex<Job>> = Lazy::new(|| Mutex::new(Job::default()));

fn step(msg: impl Into<String>) {
    let m = msg.into();
    tracing::info!("星歷重抓：{m}");
    let mut j = JOB.lock();
    j.log.push(format!("{} {m}", chrono::Local::now().format("%H:%M:%S")));
    j.step = m;
}

static CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(300))
        .user_agent(concat!("SatDashboard-Rust/", env!("CARGO_PKG_VERSION"), " (ephemeris refresh)"))
        .build()
        .expect("reqwest client")
});

async fn get_text(url: &str, cookie: Option<&str>) -> anyhow::Result<String> {
    let mut rq = CLIENT.get(url);
    if let Some(c) = cookie {
        rq = rq.header(header::COOKIE, c);
    }
    let r = rq.send().await.map_err(|e| anyhow::anyhow!("連線失敗（{}）：{e}", host_of(url)))?;
    let st = r.status();
    let t = r.text().await?;
    if !st.is_success() {
        anyhow::bail!("{} 回應 HTTP {}：{}", host_of(url), st.as_u16(), t.chars().take(160).collect::<String>());
    }
    Ok(t)
}

fn host_of(url: &str) -> String {
    url.split("//").nth(1).and_then(|s| s.split('/').next()).unwrap_or(url).to_string()
}

struct StSession {
    cookie: String,
}

async fn st_login(id: &str, pw: &str) -> anyhow::Result<StSession> {
    let url = format!("{}/ajaxauth/login", spacetrack_base());
    let r = CLIENT
        .post(&url)
        .form(&[("identity", id), ("password", pw)])
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("連線 Space-Track 失敗：{e}"))?;
    let cookie: Vec<String> = r
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .filter_map(|v| v.split(';').next().map(|s| s.trim().to_string()))
        .filter(|s| s.contains('='))
        .collect();
    let st = r.status();
    let body = r.text().await.unwrap_or_default();
    if !st.is_success() || body.contains("\"Failed\"") || cookie.is_empty() {
        anyhow::bail!("Space-Track 登入失敗（HTTP {}）：請確認帳號密碼", st.as_u16());
    }
    Ok(StSession { cookie: cookie.join("; ") })
}

async fn st_logout(s: &StSession) {
    let _ = get_text(&format!("{}/ajaxauth/logout", spacetrack_base()), Some(&s.cookie)).await;
}

// ── 執行重抓 ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq)]
enum Kind {
    Gp,
    Satcat,
    Both,
}

async fn run_job(st: Arc<AppState>, kind: Kind, source: String) -> anyhow::Result<String> {
    let cfg = st.cfg.clone();
    let mut meta = read_meta(&cfg);
    let mut summary = Vec::new();
    let by = JOB.lock().by.clone();
    let session = if source == "spacetrack" {
        let (id, pw, _) = st_cred(&cfg).ok_or_else(|| anyhow::anyhow!("尚未設定 Space-Track 帳號"))?;
        step("登入 Space-Track…");
        Some(st_login(&id, &pw).await?)
    } else {
        None
    };
    let res: anyhow::Result<()> = async {
        if kind != Kind::Satcat {
            meta.attempts.insert(format!("gp:{source}"), now_iso());
            write_meta(&cfg, &meta);
            let fetched = match &session {
                Some(s) => {
                    step("下載 Space-Track 全目錄 GP（未再入、30 天內曆元）…");
                    let url = format!(
                        "{}/basicspacedata/query/class/gp/decay_date/null-val/epoch/%3Enow-30/orderby/norad_cat_id/format/3le",
                        spacetrack_base()
                    );
                    userdata::parse_tle_text(&get_text(&url, Some(&s.cookie)).await?, "spacetrack")
                }
                None => {
                    step("下載 CelesTrak active 群組…");
                    let url = format!("{}/NORAD/elements/gp.php?GROUP=active&FORMAT=tle", celestrak_base());
                    let mut m = userdata::parse_tle_text(&get_text(&url, None).await?, "celestrak");
                    // 群組成員不在 active（如非現役、碎片）且未再入 → 逐顆補抓（上限 CATNR_MAX）
                    let sc = satcat(&cfg);
                    let d = st.satadmin.snapshot();
                    let mut want: Vec<u32> = d.groups.iter().flat_map(|g| g.members.iter().copied()).collect::<HashSet<_>>().into_iter().collect();
                    want.retain(|n| !m.contains_key(n) && sc.get(n).map_or(true, |r| r.decay.is_empty()));
                    want.sort_unstable();
                    let extra = want.len().min(CATNR_MAX);
                    if extra > 0 {
                        step(format!("逐顆補抓群組成員 {extra} 顆（不在 active 群組）…"));
                    }
                    for n in want.into_iter().take(CATNR_MAX) {
                        let url = format!("{}/NORAD/elements/gp.php?CATNR={n}&FORMAT=tle", celestrak_base());
                        if let Ok(t) = get_text(&url, None).await {
                            m.extend(userdata::parse_tle_text(&t, "celestrak"));
                        }
                        tokio::time::sleep(Duration::from_millis(300)).await;
                    }
                    m
                }
            };
            if fetched.len() < 10 {
                anyhow::bail!("只取得 {} 筆 TLE，疑似來源異常，未寫入", fetched.len());
            }
            let idx = st.index();
            let newer = fetched
                .iter()
                .filter(|(n, t)| idx.sats.get(n).map_or(false, |s| tle_epoch(&t.line1) > tle_epoch(&s.line1)))
                .count();
            let added = fetched.keys().filter(|n| !idx.sats.contains_key(n)).count();
            let count = fetched.len();
            let mut ov = load_overlay(&cfg);
            merge_newer(&mut ov, fetched);
            write_overlay(&cfg, &ov)?;
            step(format!("TLE {count} 筆：比目前新 {newer} 顆、目錄新增 {added} 顆"));
            summary.push(format!("TLE {count} 筆（更新 {newer}、新增 {added}）"));
            meta.gp = Some(FetchRec { source: source.clone(), fetched_at: now_iso(), count, newer, added, decayed: 0, by: by.clone() });
            write_meta(&cfg, &meta);
        }
        if kind != Kind::Gp {
            let key = format!("satcat:{source}");
            let w = wait_secs(&meta, &key);
            if kind == Kind::Both && w > 0 {
                step(format!("SATCAT {} 小時內已更新過，略過", min_interval(&key) / 3600));
            } else {
                meta.attempts.insert(key, now_iso());
                write_meta(&cfg, &meta);
                let recs = match &session {
                    Some(s) => {
                        step("下載 Space-Track SATCAT（含 DECAY）…");
                        let url = format!("{}/basicspacedata/query/class/satcat/orderby/NORAD_CAT_ID%20asc/format/json", spacetrack_base());
                        parse_spacetrack_satcat(&get_text(&url, Some(&s.cookie)).await?)?
                    }
                    None => {
                        step("下載 CelesTrak SATCAT（含 DECAY）…");
                        parse_celestrak_satcat(&get_text(&format!("{}/pub/satcat.csv", celestrak_base()), None).await?)?
                    }
                };
                let decayed = recs.iter().filter(|r| !r.decay.is_empty()).count();
                let count = recs.len();
                atomic_write(&dir(&cfg).join(SATCAT), &serde_json::to_vec(&recs)?)?;
                step(format!("SATCAT {count} 筆（已再入 {decayed} 筆）"));
                summary.push(format!("SATCAT {count} 筆（已再入 {decayed}）"));
                meta.satcat = Some(FetchRec { source: source.clone(), fetched_at: now_iso(), count, newer: 0, added: 0, decayed, by: by.clone() });
                write_meta(&cfg, &meta);
            }
        }
        Ok(())
    }
    .await;
    if let Some(s) = &session {
        st_logout(s).await;
    }
    res?;
    if kind != Kind::Satcat {
        step("重建衛星索引…");
        let st2 = st.clone();
        tokio::task::spawn_blocking(move || {
            st2.rebuild_index_now();
            st2.result_cache.lock().clear();
            *st2.db_info_cache.lock() = None;
        })
        .await?;
    }
    Ok(summary.join("；"))
}

/// 暫時性錯誤（連線失敗、逾時、HTTP 5xx）：不該佔滿整個頻率間隔
fn is_transient(m: &str) -> bool {
    m.contains("連線失敗") || m.contains("HTTP 5") || m.contains("timed out") || m.contains("逾時")
}

const TRANSIENT_COOLDOWN_S: i64 = 600;

/// 本次工作的嘗試時間往前調，使剩餘等待只剩 10 分鐘（403 等封鎖性錯誤仍等完整間隔）
fn shorten_cooldown(cfg: &Config, source: &str) {
    let mut m = read_meta(cfg);
    let now = Utc::now();
    for kind in ["gp", "satcat"] {
        let key = format!("{kind}:{source}");
        let recent = m
            .attempts
            .get(&key)
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .is_some_and(|t| (now - t.with_timezone(&Utc)).num_seconds() < 900);
        if recent {
            let back = min_interval(&key) as i64 - TRANSIENT_COOLDOWN_S;
            if back > 0 {
                let t = now - chrono::Duration::seconds(back);
                m.attempts.insert(key, t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true));
            }
        }
    }
    write_meta(cfg, &m);
}

fn start(st: Arc<AppState>, kind: Kind, source: String, by: String) -> Result<(), (StatusCode, String)> {
    if source != "celestrak" && source != "spacetrack" {
        return Err((StatusCode::BAD_REQUEST, "來源需為 celestrak 或 spacetrack".into()));
    }
    if source == "spacetrack" && st_cred(&st.cfg).is_none() {
        return Err((StatusCode::BAD_REQUEST, "尚未設定 Space-Track 帳號（在下方輸入，或設定環境變數 SPACETRACK_USER／SPACETRACK_PASS）".into()));
    }
    let meta = read_meta(&st.cfg);
    let key = format!("{}:{source}", if kind == Kind::Satcat { "satcat" } else { "gp" });
    let w = wait_secs(&meta, &key);
    if w > 0 {
        return Err((
            StatusCode::TOO_MANY_REQUESTS,
            format!("依 {} 使用規範，同一來源 {} 分鐘內只抓一次；請 {} 分鐘後再試", if source == "spacetrack" { "Space-Track" } else { "CelesTrak" }, min_interval(&key) / 60, w.div_ceil(60)),
        ));
    }
    {
        let mut j = JOB.lock();
        if j.running {
            return Err((StatusCode::CONFLICT, "已有重抓工作進行中".into()));
        }
        *j = Job {
            running: true,
            kind: format!("{kind:?}").to_lowercase(),
            source: source.clone(),
            by: by.clone(),
            started_at: now_iso(),
            ..Default::default()
        };
    }
    tokio::spawn(async move {
        let r = run_job(st.clone(), kind, source.clone()).await;
        let (ok, msg) = match r {
            Ok(s) => (true, format!("完成：{s}")),
            Err(e) => {
                let m = format!("{e:#}");
                if is_transient(&m) {
                    shorten_cooldown(&st.cfg, &source);
                }
                (false, format!("失敗：{m}"))
            }
        };
        step(msg.clone());
        st.satadmin.audit(&by, "重抓星歷", &format!("{source}：{msg}"));
        let mut j = JOB.lock();
        j.running = false;
        j.ok = Some(ok);
        j.finished_at = now_iso();
    });
    Ok(())
}

// ── 狀態計算 ─────────────────────────────────────────────────────────────────

fn index_epoch_stats(st: &Arc<AppState>) -> Value {
    let idx = st.index();
    let now = Utc::now();
    let mut ages: Vec<f64> = idx
        .sats
        .values()
        .filter_map(|s| tle_epoch(&s.line1))
        .map(|t| (now - t).num_seconds() as f64 / 86400.0)
        .collect();
    ages.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let latest = idx.sats.values().filter_map(|s| tle_epoch(&s.line1)).max();
    let med = ages.get(ages.len() / 2).copied();
    json!({
        "count": idx.sats.len(),
        "built_at": idx.built_at.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "epoch_latest": latest.map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)),
        "median_age_days": med.map(|x| (x * 10.0).round() / 10.0),
        "within_1d": ages.iter().filter(|a| **a <= 1.0).count(),
        "within_3d": ages.iter().filter(|a| **a <= 3.0).count(),
        "older_30d": ages.iter().filter(|a| **a > 30.0).count(),
    })
}

fn status_json(st: &Arc<AppState>) -> Value {
    let cfg = &st.cfg;
    let meta = read_meta(cfg);
    let db = cfg.resolve_db();
    let db_mtime: Option<DateTime<Utc>> = db.as_ref().and_then(|p| std::fs::metadata(p).ok()).and_then(|m| m.modified().ok()).map(Into::into);
    let gp_at = meta.gp.as_ref().and_then(|g| DateTime::parse_from_rfc3339(&g.fetched_at).ok()).map(|t| t.with_timezone(&Utc));
    let last = match (db_mtime, gp_at) {
        (Some(a), Some(b)) => Some(a.max(b)),
        (a, b) => a.or(b),
    };
    let cred = st_cred(cfg);
    let wait = |k: &str| wait_secs(&meta, k);
    json!({
        "last_updated": last.map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)),
        "db": {
            "name": db.as_ref().and_then(|p| p.file_name()).map(|s| s.to_string_lossy().into_owned()),
            "updated_at": db_mtime.map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)),
        },
        "index": index_epoch_stats(st),
        "gp": meta.gp,
        "satcat": satcat_meta(cfg),
        "overlay_count": load_overlay(cfg).len(),
        "job": JOB.lock().clone(),
        "spacetrack": {
            "configured": cred.is_some(),
            "identity": cred.as_ref().map(|c| mask(&c.0)),
            "from": cred.as_ref().map(|c| c.2),
        },
        "wait_s": {
            "gp:celestrak": wait("gp:celestrak"), "gp:spacetrack": wait("gp:spacetrack"),
            "satcat:celestrak": wait("satcat:celestrak"), "satcat:spacetrack": wait("satcat:spacetrack"),
        },
    })
}

// ── 再入（DECAY）列表 ────────────────────────────────────────────────────────

fn days_between(a: &str, b: &str) -> Option<i64> {
    let pa = NaiveDate::parse_from_str(a.get(..10)?, "%Y-%m-%d").ok()?;
    let pb = NaiveDate::parse_from_str(b.get(..10)?, "%Y-%m-%d").ok()?;
    Some((pb - pa).num_days())
}

/// 單顆衛星狀態：decayed（SATCAT 有 DECAY）／stale（TLE 超過 stale_days 天未更新）／no_satcat／ok
pub fn sat_status(sc: &HashMap<u32, SatcatRec>, epoch: Option<DateTime<Utc>>, nid: u32, stale_days: f64) -> (&'static str, Value) {
    let r = sc.get(&nid);
    let age = epoch.map(|t| ((Utc::now() - t).num_seconds() as f64 / 86400.0 * 10.0).round() / 10.0);
    let st = match r {
        Some(r) if !r.decay.is_empty() => "decayed",
        _ if age.is_some_and(|a| a > stale_days) => "stale",
        None if !sc.is_empty() => "no_satcat",
        _ => "ok",
    };
    let v = json!({
        "status": st,
        "decay_date": r.map(|r| r.decay.clone()).filter(|s| !s.is_empty()),
        "launch_date": r.map(|r| r.launch.clone()).filter(|s| !s.is_empty()),
        "days_in_orbit": r.and_then(|r| if r.decay.is_empty() || r.launch.is_empty() { None } else { days_between(&r.launch, &r.decay) }),
        "object_type": r.map(|r| r.object_type.clone()),
        "owner": r.map(|r| r.owner.clone()),
        "satcat_name": r.map(|r| r.name.clone()),
        "tle_age_days": age,
    });
    (st, v)
}

async fn api_decay(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Response {
    let cfg = &st.cfg;
    let sc = satcat(cfg);
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let stale_days: f64 = q.get("stale_days").and_then(|s| s.parse().ok()).unwrap_or(30.0);
    let scope = q.get("scope").map(String::as_str).unwrap_or("groups");
    let include_ok = q.get("all").is_some_and(|v| v == "1");
    let mut rows: Vec<Value> = Vec::new();
    if scope == "recent" {
        // 全目錄：近 N 天再入
        let days: i64 = q.get("days").and_then(|s| s.parse().ok()).unwrap_or(30).clamp(1, 3650);
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let mut v: Vec<&SatcatRec> = sc.values().filter(|r| !r.decay.is_empty() && days_between(&r.decay, &today).is_some_and(|x| (0..=days).contains(&x))).collect();
        v.sort_by(|a, b| b.decay.cmp(&a.decay).then(a.norad.cmp(&b.norad)));
        for r in v.into_iter().take(5000) {
            let s = idx.sats.get(&r.norad);
            let (_, mut extra) = sat_status(&sc, s.and_then(|s| tle_epoch(&s.line1)), r.norad, stale_days);
            extra["norad_id"] = json!(r.norad);
            extra["name"] = json!(d.names.get(&r.norad).map(|x| x.name.clone()).unwrap_or_else(|| r.name.clone()));
            extra["intl_code"] = json!(r.intl);
            extra["groups"] = json!([]);
            rows.push(extra);
        }
    } else {
        let gids: Vec<String> = match q.get("group").filter(|s| !s.is_empty()) {
            Some(g) => {
                if !d.groups.iter().any(|x| &x.id == g) {
                    return (StatusCode::NOT_FOUND, Json(json!({"error": format!("找不到群組 {g}")}))).into_response();
                }
                d.descendants(g)
            }
            None => d.groups.iter().map(|g| g.id.clone()).collect(),
        };
        let mut members: BTreeMap<u32, Vec<String>> = BTreeMap::new();
        for gid in &gids {
            if let Some(g) = d.groups.iter().find(|x| &x.id == gid) {
                for &n in &g.members {
                    members.entry(n).or_default().push(d.path(gid));
                }
            }
        }
        for (n, gps) in members {
            let s = idx.sats.get(&n);
            let (stt, mut extra) = sat_status(&sc, s.and_then(|s| tle_epoch(&s.line1)), n, stale_days);
            if stt == "ok" && !include_ok {
                continue;
            }
            let orig = d.names.get(&n).map(|x| x.orig.clone()).filter(|x| !x.is_empty());
            extra["norad_id"] = json!(n);
            extra["name"] = json!(d.names.get(&n).map(|x| x.name.clone()).or_else(|| s.map(|s| s.name.clone())).or_else(|| sc.get(&n).map(|r| r.name.clone())).unwrap_or_default());
            extra["orig_name"] = json!(orig.or_else(|| s.map(|s| s.name.clone())));
            extra["intl_code"] = json!(s.map(|s| crate::satadmin::intl_code(&s.line1)).or_else(|| sc.get(&n).map(|r| r.intl.clone())));
            extra["tle_epoch"] = json!(s.and_then(|s| tle_epoch(&s.line1)).map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)));
            extra["groups"] = json!(gps);
            rows.push(extra);
        }
        let ord = |v: &Value| match v["status"].as_str() {
            Some("decayed") => 0,
            Some("stale") => 1,
            Some("no_satcat") => 2,
            _ => 3,
        };
        rows.sort_by(|a, b| ord(a).cmp(&ord(b)).then_with(|| b["decay_date"].as_str().cmp(&a["decay_date"].as_str())));
    }
    let count = |s: &str| rows.iter().filter(|r| r["status"] == s).count();
    let counts = json!({"decayed": count("decayed"), "stale": count("stale"), "no_satcat": count("no_satcat"), "ok": count("ok")});
    if q.get("format").is_some_and(|f| f == "csv") {
        let mut out = String::from("\u{FEFF}norad_id,name,status,decay_date,launch_date,days_in_orbit,tle_epoch,tle_age_days,intl_code,object_type,owner,groups\n");
        let f = |v: &Value| match v {
            Value::Null => String::new(),
            Value::String(s) => s.clone(),
            Value::Array(a) => a.iter().filter_map(|x| x.as_str()).collect::<Vec<_>>().join(" | "),
            o => o.to_string(),
        };
        let esc = |s: String| if s.contains([',', '"', '\n']) { format!("\"{}\"", s.replace('"', "\"\"")) } else { s };
        for r in &rows {
            let label = match r["status"].as_str() {
                Some("decayed") => "已再入",
                Some("stale") => "TLE 停更",
                Some("no_satcat") => "SATCAT 查無",
                _ => "正常",
            };
            let cols = [
                f(&r["norad_id"]), f(&r["name"]), label.to_string(), f(&r["decay_date"]), f(&r["launch_date"]), f(&r["days_in_orbit"]),
                f(&r["tle_epoch"]), f(&r["tle_age_days"]), f(&r["intl_code"]), f(&r["object_type"]), f(&r["owner"]), f(&r["groups"]),
            ];
            out.push_str(&cols.into_iter().map(esc).collect::<Vec<_>>().join(","));
            out.push('\n');
        }
        let mut resp = Response::new(axum::body::Body::from(out));
        resp.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static("text/csv; charset=utf-8"));
        let fname = format!("decay_{}.csv", chrono::Local::now().format("%Y%m%d_%H%M"));
        resp.headers_mut().insert(header::CONTENT_DISPOSITION, HeaderValue::from_str(&format!("attachment; filename=\"{fname}\"")).unwrap());
        return resp;
    }
    Json(json!({
        "rows": rows, "counts": counts, "stale_days": stale_days, "scope": scope,
        "satcat": satcat_meta(cfg), "satcat_loaded": !sc.is_empty(),
    }))
    .into_response()
}

// ── API ──────────────────────────────────────────────────────────────────────

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/ephemeris/status", get(api_status))
        .route("/api/ephemeris/refresh", post(api_refresh))
        .route("/api/ephemeris/spacetrack", get(api_cred_get).post(api_cred_set).delete(api_cred_del))
        .route("/api/satadmin/decay", get(api_decay))
}

async fn api_status(State(st): State<Arc<AppState>>) -> Json<Value> {
    let st2 = st.clone();
    let v = tokio::task::spawn_blocking(move || status_json(&st2)).await.unwrap_or_else(|e| json!({"error": e.to_string()}));
    Json(v)
}

#[derive(Deserialize)]
struct RefreshReq {
    #[serde(default = "def_src")]
    source: String,
    /// gp（只抓 TLE）／satcat（只抓 SATCAT）／both（預設）
    #[serde(default = "def_kind")]
    what: String,
}
fn def_src() -> String {
    "celestrak".into()
}
fn def_kind() -> String {
    "both".into()
}

async fn api_refresh(State(st): State<Arc<AppState>>, Extension(c): Extension<Caller>, Json(b): Json<RefreshReq>) -> Response {
    let kind = match b.what.as_str() {
        "gp" => Kind::Gp,
        "satcat" => Kind::Satcat,
        _ => Kind::Both,
    };
    match start(st, kind, b.source, c.name()) {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err((s, m)) => (s, Json(json!({"error": m}))).into_response(),
    }
}

async fn api_cred_get(State(st): State<Arc<AppState>>) -> Json<Value> {
    let c = st_cred(&st.cfg);
    Json(json!({"configured": c.is_some(), "identity": c.as_ref().map(|c| mask(&c.0)), "from": c.as_ref().map(|c| c.2)}))
}

async fn api_cred_set(State(st): State<Arc<AppState>>, Extension(c): Extension<Caller>, Json(b): Json<StCred>) -> Response {
    if b.identity.trim().is_empty() || b.password.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "需要帳號與密碼"}))).into_response();
    }
    let data = match serde_json::to_vec_pretty(&StCred { identity: b.identity.trim().into(), password: b.password }) {
        Ok(d) => d,
        Err(e) => return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))).into_response(),
    };
    match atomic_write(&cred_file(&st.cfg), &data) {
        Ok(()) => {
            let _ = std::fs::remove_file(cred_file(&st.cfg).with_extension("bak"));
            st.satadmin.audit(&c.name(), "設定 Space-Track 帳號", &mask(b.identity.trim()));
            Json(json!({"ok": true})).into_response()
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))).into_response(),
    }
}

async fn api_cred_del(State(st): State<Arc<AppState>>, Extension(c): Extension<Caller>) -> Json<Value> {
    let p = cred_file(&st.cfg);
    let _ = std::fs::remove_file(&p);
    let _ = std::fs::remove_file(p.with_extension("bak"));
    st.satadmin.audit(&c.name(), "刪除 Space-Track 帳號", "");
    Json(json!({"ok": true}))
}

#[cfg(test)]
mod tests {
    use super::*;

    const L1A: &str = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005";
    const L2: &str = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537";
    const L1B: &str = "1 25544U 98067A   24002.50000000  .00016717  00000-0  10270-3 0  9006";

    fn tle(l1: &str) -> UserTle {
        UserTle { name: "ISS".into(), line1: l1.into(), line2: L2.into(), source_file: String::new() }
    }

    #[test]
    fn overlay_keeps_newer() {
        let mut a: BTreeMap<u32, UserTle> = [(25544, tle(L1B))].into_iter().collect();
        merge_newer(&mut a, [(25544, tle(L1A))].into_iter().collect());
        assert_eq!(a[&25544].line1, L1B, "較舊的不覆蓋");
        let mut b: BTreeMap<u32, UserTle> = [(25544, tle(L1A))].into_iter().collect();
        merge_newer(&mut b, [(25544, tle(L1B))].into_iter().collect());
        assert_eq!(b[&25544].line1, L1B);
    }

    #[test]
    fn satcat_parsers() {
        let mut csv = String::from("OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,OWNER,LAUNCH_DATE,LAUNCH_SITE,DECAY_DATE,PERIOD,INCLINATION,APOGEE,PERIGEE\n");
        csv.push_str("YAOGAN-30 A,2017-058A,42945,PAY,D,PRC,2017-09-29,XSC,2025-03-01,94.6,35.0,600,590\n");
        for i in 0..1000 {
            csv.push_str(&format!("X {i},2000-001A,{},DEB,,US,2000-01-01,AFETR,,90,10,300,290\n", 50000 + i));
        }
        let v = parse_celestrak_satcat(&csv).unwrap();
        let y = v.iter().find(|r| r.norad == 42945).unwrap();
        assert_eq!(y.decay, "2025-03-01");
        assert_eq!(y.owner, "PRC");
        assert!(parse_celestrak_satcat("NORAD_CAT_ID\n1\n").is_err(), "筆數太少視為不完整");
        let j = r#"[{"NORAD_CAT_ID":"42945","SATNAME":"YAOGAN 30A","INTLDES":"2017-058A","OBJECT_TYPE":"PAYLOAD","COUNTRY":"PRC","LAUNCH":"2017-09-29","DECAY":"2025-03-01","PERIOD":"94.60"},
                   {"NORAD_CAT_ID":"25544","SATNAME":"ISS (ZARYA)","DECAY":null}]"#;
        let v = parse_spacetrack_satcat(j).unwrap();
        assert_eq!(v[0].decay, "2025-03-01");
        assert_eq!(v[0].period, Some(94.6));
        assert_eq!(v[1].decay, "");
    }

    #[test]
    fn status_rules() {
        let mut sc = HashMap::new();
        sc.insert(1, SatcatRec { norad: 1, decay: "2025-03-01".into(), launch: "2017-09-29".into(), ..Default::default() });
        sc.insert(2, SatcatRec { norad: 2, ..Default::default() });
        let fresh = Some(Utc::now());
        let old = Some(Utc::now() - chrono::Duration::days(45));
        let (s, v) = sat_status(&sc, old, 1, 30.0);
        assert_eq!(s, "decayed");
        assert_eq!(v["days_in_orbit"], 2710);
        assert_eq!(sat_status(&sc, old, 2, 30.0).0, "stale");
        assert_eq!(sat_status(&sc, fresh, 2, 30.0).0, "ok");
        assert_eq!(sat_status(&sc, fresh, 3, 30.0).0, "no_satcat");
        assert_eq!(sat_status(&HashMap::new(), fresh, 3, 30.0).0, "ok", "沒有 SATCAT 時不標查無");
        assert_eq!(mask("someone@example.com"), "so***@example.com");
        assert!(is_transient("celestrak.org 回應 HTTP 503：Service Unavailable"));
        assert!(is_transient("連線失敗（celestrak.org）：error sending request"));
        assert!(!is_transient("celestrak.org 回應 HTTP 403：Forbidden"), "403 封鎖不縮短");
    }
}
