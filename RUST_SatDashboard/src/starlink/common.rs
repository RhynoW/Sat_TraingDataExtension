//! Starlink 模組共用工具：Python 相容的捨入／ISO 字串、sat_metadata.csv 快取、
//! Starlink NORAD 集合（同 Python `_starlink_norad_ids()`）、DuckDB 輔助、HTTP client。

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration as StdDuration, Instant, SystemTime};

use chrono::{DateTime, NaiveDateTime, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;

use crate::config::Config;
use crate::state::AppState;

pub const MU: f64 = 398600.4418;
pub const RE: f64 = 6378.137;
const F_EARTH: f64 = 1.0 / 298.257223563;
const E2: f64 = F_EARTH * (2.0 - F_EARTH);

/// Python `round(x, nd)`（正確捨入、半數取偶；Rust `{:.N}` 格式化語意相同）
pub fn py_round(x: f64, nd: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.nd$}").parse().unwrap_or(x)
}

/// Python `round(x)`（回傳整數、半數取偶）
pub fn py_round_int(x: f64) -> i64 {
    format!("{x:.0}").parse::<f64>().unwrap_or(x) as i64
}

/// Python `datetime.isoformat()`（UTC aware：`…+00:00`；微秒為 0 時省略）
pub fn py_iso_utc(t: &DateTime<Utc>) -> String {
    format!("{}+00:00", py_iso_naive(&t.naive_utc()))
}

/// Python naive `datetime.isoformat()` / pandas `Timestamp.isoformat()`（微秒為 0 時省略）
pub fn py_iso_naive(t: &NaiveDateTime) -> String {
    let us = t.and_utc().timestamp_subsec_micros();
    if us == 0 {
        t.format("%Y-%m-%dT%H:%M:%S").to_string()
    } else {
        format!("{}.{us:06}", t.format("%Y-%m-%dT%H:%M:%S"))
    }
}

/// Python `isoformat(timespec="seconds")`（UTC aware）
pub fn py_iso_secs(t: &DateTime<Utc>) -> String {
    t.format("%Y-%m-%dT%H:%M:%S+00:00").to_string()
}

/// 由 unix 秒（含小數）建 UTC 時刻（微秒精度，同 Python datetime）
pub fn from_unix(t: f64) -> DateTime<Utc> {
    let us = (t * 1e6).round() as i64;
    DateTime::from_timestamp_micros(us).unwrap_or_default()
}

pub fn unix_of(t: &DateTime<Utc>) -> f64 {
    t.timestamp() as f64 + t.timestamp_subsec_nanos() as f64 * 1e-9
}

/// DuckDB 查詢用「現在」字面值（UTC naive TIMESTAMP）。
/// Python 版用 `now()`（TIMESTAMPTZ）與 naive 的 epoch_utc 比較，結果隨伺服器時區偏移；
/// 這裡固定以 UTC 解讀（epoch_utc 本身即 UTC），與部署在 UTC 主機上的 Python 版一致。
pub fn now_sql() -> String {
    format!("TIMESTAMP '{}'", Utc::now().naive_utc().format("%Y-%m-%d %H:%M:%S%.6f"))
}

/// Python 版 settings.DB_DIR 之對應：資料庫所在目錄（找不到 DB 時用 <data>\DB）
pub fn db_dir(cfg: &Config) -> PathBuf {
    cfg.resolve_db()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| cfg.home.join("DB"))
}

// ── sat_metadata.csv（以 mtime 快取；檔案不存在時用索引模組內建版）──────────────
type Meta = Arc<HashMap<u32, HashMap<String, String>>>;
static META: Lazy<Mutex<Option<(Option<SystemTime>, PathBuf, Meta)>>> = Lazy::new(|| Mutex::new(None));

pub fn sat_meta(cfg: &Config) -> Meta {
    let p = cfg.sat_meta_csv();
    let mtime = std::fs::metadata(&p).and_then(|m| m.modified()).ok();
    let mut g = META.lock();
    if let Some((mt, path, m)) = g.as_ref() {
        if *mt == mtime && *path == p {
            return m.clone();
        }
    }
    let m: Meta = Arc::new(crate::index::load_meta_csv(&p));
    *g = Some((mtime, p, m.clone()));
    m
}

/// 由 sat_metadata.csv 名稱（classification_rules 之星座規則）判定的 Starlink NORAD 集合（1 小時快取）
static IDS: Lazy<Mutex<Option<(Instant, Arc<HashSet<u32>>)>>> = Lazy::new(|| Mutex::new(None));

pub fn starlink_ids(st: &AppState) -> Arc<HashSet<u32>> {
    if let Some((at, ids)) = IDS.lock().as_ref() {
        if at.elapsed() < StdDuration::from_secs(3600) {
            return ids.clone();
        }
    }
    let meta = sat_meta(&st.cfg);
    let rules = st.rules.read().clone();
    let ids: HashSet<u32> = meta
        .iter()
        .filter(|(_, row)| {
            rules.classify_constellation(row.get("name_en").map(String::as_str).unwrap_or("")).as_deref() == Some("Starlink")
        })
        .map(|(n, _)| *n)
        .collect();
    tracing::info!("starlink_ids(): {} 顆（sat_metadata.csv 分類）", ids.len());
    let ids = Arc::new(ids);
    *IDS.lock() = Some((Instant::now(), ids.clone()));
    ids
}

pub fn starlink_name(st: &AppState, nid: u32) -> Option<String> {
    sat_meta(&st.cfg).get(&nid).and_then(|r| r.get("name_en").cloned())
}

/// `JOIN starlink_ids s` 用的子查詢（Python 以 con.register(DataFrame) 註冊；唯讀連線改用 unnest 清單字面值）
pub fn ids_subquery(ids: &HashSet<u32>) -> String {
    let mut v: Vec<u32> = ids.iter().copied().collect();
    v.sort_unstable();
    let list = v.iter().map(u32::to_string).collect::<Vec<_>>().join(",");
    format!("(SELECT CAST(unnest([{list}]) AS INTEGER) AS norad_id)")
}

/// DuckDB `epoch_us(ts)` → NaiveDateTime（微秒）
pub fn ts_from_us(us: i64) -> NaiveDateTime {
    DateTime::from_timestamp_micros(us).unwrap_or_default().naive_utc()
}

/// pandas `str(Timestamp)`：`YYYY-MM-DD HH:MM:SS[.ffffff]`
pub fn pandas_str(t: &NaiveDateTime) -> String {
    py_iso_naive(t).replacen('T', " ", 1)
}

/// 對外 HTTP client（通用瀏覽器 User-Agent；與 Python 版相同的逾時）
pub fn http_client(timeout_s: u64) -> reqwest::Client {
    reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        .timeout(StdDuration::from_secs(timeout_s))
        .build()
        .unwrap_or_default()
}

// ── 座標（同 Python physics/coords.py）───────────────────────────────────────

/// Python `jday()` 後 jd+fr 之等值（unix 秒 → 儒略日）
pub fn jd_of_unix(t: f64) -> f64 {
    t / 86400.0 + 2440587.5
}

/// coords.py 之 GMST（無 T³ 項；GEO 時 eci_to_llh_batch 改用 IAU2006）
pub fn gmst_py(jd: f64, iau2006: bool) -> f64 {
    let d = jd - 2451545.0;
    let tc = d / 36525.0;
    let mut deg = 280.46061837 + 360.98564736629 * d + 0.000387933 * tc * tc;
    if iau2006 {
        deg -= tc * tc * tc / 38710000.0;
    }
    deg.rem_euclid(360.0).to_radians()
}

/// Python `eci_to_llh_batch(r[None,:], t)[0]` → [lat°, lon°, alt km]
pub fn eci_to_llh_py(r: &[f64; 3], unix_t: f64) -> [f64; 3] {
    let rmag = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
    let g = gmst_py(jd_of_unix(unix_t), rmag > RE + 10_000.0);
    let (sg, cg) = g.sin_cos();
    let xe = cg * r[0] + sg * r[1];
    let ye = -sg * r[0] + cg * r[1];
    let ze = r[2];
    let lon = ye.atan2(xe);
    let rr = (xe * xe + ye * ye).sqrt();
    let mut lat = ze.atan2(rr * (1.0 - E2));
    let mut alt = 0.0;
    for _ in 0..5 {
        let sl = lat.sin();
        let n = RE / (1.0 - E2 * sl * sl).sqrt();
        let cl = lat.cos();
        alt = if cl.abs() > 1e-9 { rr / cl - n } else { ze.abs() / (1.0 - E2) - n };
        lat = ze.atan2(rr * (1.0 - E2 * (n / (n + alt))));
    }
    [lat.to_degrees(), lon.to_degrees(), alt]
}

// ── SGP4（同 Python Satrec.twoline2rv；檢查碼自動修正）──────────────────────────
pub struct Sat {
    pub constants: sgp4::Constants,
    pub epoch: NaiveDateTime,
    /// TLE 平均運動（rev/day）
    pub mean_motion: f64,
}

fn fix_checksum(line: &str) -> String {
    let b = line.as_bytes();
    if b.len() < 69 {
        return line.to_string();
    }
    let sum: u32 = b[..68]
        .iter()
        .map(|&c| match c {
            b'0'..=b'9' => (c - b'0') as u32,
            b'-' => 1,
            _ => 0,
        })
        .sum();
    let mut s = line[..68].to_string();
    s.push(char::from(b'0' + (sum % 10) as u8));
    s
}

impl Sat {
    pub fn from_tle(l1: &str, l2: &str) -> Option<Self> {
        let a = fix_checksum(l1.trim_end());
        let b = fix_checksum(l2.trim_end());
        let el = sgp4::Elements::from_tle(None, a.as_bytes(), b.as_bytes()).ok()?;
        let constants = sgp4::Constants::from_elements_afspc_compatibility_mode(&el).ok()?;
        Some(Self {
            constants,
            epoch: el.datetime,
            mean_motion: el.mean_motion,
        })
    }
    pub fn epoch_unix(&self) -> f64 {
        let u = self.epoch.and_utc();
        u.timestamp() as f64 + u.timestamp_subsec_nanos() as f64 * 1e-9
    }
    /// TEME 位置／速度；錯誤（含 r < 地球半徑之衰退）回傳 None（同 Python e != 0）
    pub fn pv_unix(&self, t: f64) -> Option<([f64; 3], [f64; 3])> {
        let min = (t - self.epoch_unix()) / 60.0;
        let p = self.constants.propagate(sgp4::MinutesSinceEpoch(min)).ok()?;
        let r = p.position;
        let mag2 = r[0] * r[0] + r[1] * r[1] + r[2] * r[2];
        (r.iter().chain(p.velocity.iter()).all(|v| v.is_finite()) && mag2 >= 6378.135 * 6378.135).then_some((r, p.velocity))
    }
}
