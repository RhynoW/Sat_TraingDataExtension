//! 觀測資料模型（對應 Python 版 scenario04/api/obs.py；前端 web/ext/obs_model.js、obs.js 與線上版共用）。
//!
//! 四種紀錄存在本機 `user_private\observations.json`：pois 地面 POI、observations 觀測紀錄、orbits 軌道解、claims 身分主張；
//! 每筆附複核欄位（review 未複核／已接受／有爭議／已否決、review_note、reviewer、reviewed_at）。
//! 權限：檢視者可看與執行交叉驗證；編輯者可新增／修改／刪除；管理者可複核。
//!
//! 交叉驗證（與 Python 同一套公式，結果逐筆一致）：
//! - 觀測殘差：目錄 TLE（與使用者軌道解）SGP4 傳播到觀測時間，算觀測站看到的方向與實測方向的角距。RA/Dec 視為 J2000：
//!   TEME 近似當日平赤道（忽略章動，誤差 < 20″），再以 IAU 1976 歲差轉到 J2000；方位／仰角以 WGS84 站心座標計算。
//!   ≤ 0.5° 符合、≤ 2° 勉強符合、其餘不符合；同次發射的其他物體一併比對，找最符合者。
//! - 軌道比對：軌道解與目錄 TLE 在軌道解曆元 ±12 小時（每小時一點）的位置差；≤ 10 km 一致、≤ 50 km 接近。
//!   同次發射的物體全部比對，找軌道最接近者（協助判斷 OBJECT A/B/C 各是誰）。
//! - 身分主張：與 Space-Track 正式名稱、同一顆衛星的其他主張比對。任務類型與能力一律為 unknown，不自動歸因。

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Extension, Json, Router};
use chrono::{DateTime, Duration, NaiveDate, Utc};
use once_cell::sync::OnceCell;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use crate::auth::{atomic_write, Caller};
use crate::config::Config;
use crate::ephemeris;
use crate::physics::{gmst_rad, julian_date, Propagator};
use crate::satadmin::{intl_code, tle_epoch};
use crate::state::AppState;

pub const KINDS: [&str; 4] = ["pois", "observations", "orbits", "claims"];
const REVIEWS: [&str; 4] = ["unreviewed", "accepted", "disputed", "rejected"];
const SRC: [&str; 6] = ["official", "gcat", "amateur", "own", "news", "other"];
const OBS_OK: f64 = 0.5;
const OBS_MARGINAL: f64 = 2.0;
const ORB_OK: f64 = 10.0;
const ORB_CLOSE: f64 = 50.0;
const GRID_H: i64 = 12;
const TOP_N: usize = 5;
const A_WGS84: f64 = 6378.137;
const F_WGS84: f64 = 1.0 / 298.257223563;
const E2: f64 = F_WGS84 * (2.0 - F_WGS84);

fn src_conf(s: &str) -> &'static str {
    match s {
        "official" => "high",
        "gcat" | "amateur" | "own" => "medium",
        _ => "low",
    }
}

/// 四捨五入（遠離零），與 Python obs.rnd 相同
fn rnd(x: f64, d: i32) -> f64 {
    let f = 10f64.powi(d);
    (x.abs() * f + 0.5).floor() / f * x.signum()
}

// ── 欄位定義與驗證（與 obs_model.js 相同規則） ─────────────────────────────────

enum Ft {
    Num { min: f64, max: f64, int: bool, def: Option<f64> },
    Text { max: usize, url: bool, time: bool },
    Sel { opts: &'static [&'static str], def: &'static str },
}

struct F {
    k: &'static str,
    l: &'static str,
    req: bool,
    t: Ft,
}

fn num(k: &'static str, l: &'static str, min: f64, max: f64, req: bool, int: bool, def: Option<f64>) -> F {
    F { k, l, req, t: Ft::Num { min, max, int, def } }
}
fn txt(k: &'static str, l: &'static str, max: usize, req: bool) -> F {
    F { k, l, req, t: Ft::Text { max, url: false, time: false } }
}
fn url_f() -> F {
    F { k: "source_url", l: "來源連結", req: false, t: Ft::Text { max: 500, url: true, time: false } }
}
fn sel(k: &'static str, l: &'static str, opts: &'static [&'static str], def: &'static str) -> F {
    F { k, l, req: false, t: Ft::Sel { opts, def } }
}

fn fields(kind: &str) -> Vec<F> {
    match kind {
        "pois" => vec![
            txt("name", "名稱", 64, true),
            num("lat", "緯度（°）", -90.0, 90.0, true, false, None),
            num("lon", "經度（°）", -180.0, 360.0, true, false, None),
            num("alt_m", "高度（m）", -500.0, 9000.0, false, false, Some(0.0)),
            sel("kind", "類型", &["station", "site"], "station"),
            num("radius_km", "範圍半徑（km，過頂預報用）", 0.0, 3000.0, false, false, Some(0.0)),
            txt("note", "備註", 500, false),
        ],
        "observations" => vec![
            num("norad", "NORAD", 1.0, 999999.0, false, true, None),
            txt("station", "觀測站（POI 名稱）", 64, true),
            F { k: "time", l: "時間（UTC）", req: true, t: Ft::Text { max: 40, url: false, time: true } },
            num("ra_deg", "RA（°，J2000）", 0.0, 360.0, false, false, None),
            num("dec_deg", "Dec（°，J2000）", -90.0, 90.0, false, false, None),
            num("az_deg", "方位角（°）", 0.0, 360.0, false, false, None),
            num("el_deg", "仰角（°）", -90.0, 90.0, false, false, None),
            num("mag", "星等", -10.0, 25.0, false, false, None),
            txt("observer", "觀測者", 64, false),
            sel("source", "來源類型", &SRC, "amateur"),
            url_f(),
            txt("note", "備註", 500, false),
        ],
        "orbits" => vec![
            num("norad", "NORAD（空白＝取自 TLE）", 1.0, 999999.0, false, true, None),
            txt("line1", "TLE 第 1 行", 80, true),
            txt("line2", "TLE 第 2 行", 80, true),
            sel("source", "來源類型", &SRC, "amateur"),
            txt("source_name", "來源名稱", 64, false),
            url_f(),
            txt("note", "備註", 500, false),
        ],
        "claims" => vec![
            num("norad", "NORAD", 1.0, 999999.0, true, true, None),
            txt("name", "主張的名稱", 64, true),
            sel("source_type", "來源類型", &SRC, "amateur"),
            url_f(),
            sel("confidence", "可信度（空白＝依來源類型）", &["high", "medium", "low"], ""),
            txt("note", "備註", 500, false),
        ],
        _ => vec![],
    }
}

fn as_text(v: Option<&Value>) -> String {
    match v {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.trim().to_string(),
        Some(Value::Number(n)) => {
            let f = n.as_f64().unwrap_or(f64::NAN);
            if f.fract() == 0.0 && f.abs() < 1e15 {
                format!("{}", f as i64)
            } else {
                n.to_string()
            }
        }
        Some(Value::Bool(b)) => b.to_string(),
        Some(o) => o.to_string(),
    }
}

/// "YYYY-MM-DD HH:MM[:SS[.ffffff]]"（可用 T、結尾 Z）→ 正規化字串與時間
pub fn parse_time(s: &str) -> Option<(String, DateTime<Utc>)> {
    let s = s.trim();
    let s = s.strip_suffix('Z').unwrap_or(s);
    let b = s.as_bytes();
    if b.len() < 16 || b[4] != b'-' || b[7] != b'-' || !(b[10] == b' ' || b[10] == b'T') || b[13] != b':' {
        return None;
    }
    let dig = |r: std::ops::Range<usize>| -> Option<u32> {
        let t = s.get(r)?;
        (t.bytes().all(|c| c.is_ascii_digit())).then(|| t.parse().ok())?
    };
    let (y, mo, d, h, mi) = (dig(0..4)?, dig(5..7)?, dig(8..10)?, dig(11..13)?, dig(14..16)?);
    let (mut sec, mut frac) = (0u32, String::new());
    if b.len() > 16 {
        if b[16] != b':' || b.len() < 19 {
            return None;
        }
        sec = dig(17..19)?;
        if b.len() > 19 {
            if b[19] != b'.' || b.len() == 20 || !s[20..].bytes().all(|c| c.is_ascii_digit()) {
                return None;
            }
            frac = s[20..].chars().take(6).collect();
        }
    }
    if h > 23 || mi > 59 || sec > 59 {
        return None;
    }
    let us: u32 = format!("{frac:0<6}").parse().ok()?;
    let t = NaiveDate::from_ymd_opt(y as i32, mo, d)?.and_hms_micro_opt(h, mi, sec, us)?.and_utc();
    let norm = format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}{}", y, mo, d, h, mi, sec, if frac.is_empty() { String::new() } else { format!(".{frac}") });
    Some((norm, t))
}

/// TLE 第 3–7 欄的 NORAD 編號（支援 Alpha-5：A=10 … Z=33，不用 I、O；例如 A1419＝101419）
fn tle_norad(l: &str) -> Option<u32> {
    const ALPHA5: &str = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    let s = l.get(2..7)?;
    let first = s.chars().next()?;
    if let Some(i) = ALPHA5.find(first) {
        let rest = &s[1..];
        if rest.len() != 4 || !rest.bytes().all(|c| c.is_ascii_digit()) {
            return None;
        }
        return Some((i as u32 + 10) * 10000 + rest.parse::<u32>().ok()?);
    }
    let s = s.trim();
    if s.is_empty() || !s.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    s.parse::<u32>().ok().filter(|n| *n > 0 && *n < 1_000_000)
}

fn is_url(s: &str) -> bool {
    (s.starts_with("http://") && s.len() > 7 || s.starts_with("https://") && s.len() > 8) && !s.chars().any(char::is_whitespace)
}

pub fn validate(kind: &str, rec: &Value, data: &Data, self_id: Option<&str>) -> Result<Map<String, Value>, Vec<String>> {
    let fs = fields(kind);
    if fs.is_empty() {
        return Err(vec![format!("未知的資料種類 {kind}")]);
    }
    let mut out = Map::new();
    let mut errs = vec![];
    for f in &fs {
        let raw = rec.get(f.k);
        match &f.t {
            Ft::Num { min, max, int, def } => {
                let s = as_text(raw);
                if s.is_empty() {
                    if f.req {
                        errs.push(format!("{}必填", f.l));
                    }
                    out.insert(f.k.into(), def.map(Value::from).unwrap_or(Value::Null));
                    continue;
                }
                let Some(x) = raw.and_then(Value::as_f64).or_else(|| s.parse::<f64>().ok()).filter(|x| x.is_finite()) else {
                    errs.push(format!("{}需為數字", f.l));
                    continue;
                };
                if *int && x.fract() != 0.0 {
                    errs.push(format!("{}需為整數", f.l));
                    continue;
                }
                if x < *min || x > *max {
                    errs.push(format!("{}需介於 {}～{}", f.l, min, max));
                    continue;
                }
                out.insert(f.k.into(), if *int { Value::from(x as i64) } else { Value::from(x) });
            }
            Ft::Sel { opts, def } => {
                let mut v = as_text(raw);
                if v.is_empty() {
                    v = def.to_string();
                }
                if !v.is_empty() && !opts.contains(&v.as_str()) {
                    errs.push(format!("{}不在選項內：{v}", f.l));
                    continue;
                }
                out.insert(f.k.into(), Value::from(v));
            }
            Ft::Text { max, url, time } => {
                let mut v = as_text(raw);
                if f.req && v.is_empty() {
                    errs.push(format!("{}必填", f.l));
                    continue;
                }
                if v.chars().count() > *max {
                    errs.push(format!("{}超過 {} 字", f.l, max));
                    continue;
                }
                if *url && !v.is_empty() && !is_url(&v) {
                    errs.push(format!("{}需以 http:// 或 https:// 開頭", f.l));
                    continue;
                }
                if *time && !v.is_empty() {
                    match parse_time(&v) {
                        Some((n, _)) => v = n,
                        None => {
                            errs.push(format!("{}格式需為 YYYY-MM-DD HH:MM:SS（UTC）", f.l));
                            continue;
                        }
                    }
                }
                out.insert(f.k.into(), Value::from(v));
            }
        }
    }
    if errs.is_empty() {
        let s = |k: &str| out.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        match kind {
            "pois" => {
                let nm = s("name").to_uppercase();
                if data.pois.iter().any(|p| Some(sget(p, "id").as_str()) != self_id && sget(p, "name").to_uppercase() == nm) {
                    errs.push(format!("已有同名的地面 POI：{}", s("name")));
                }
            }
            "observations" => {
                let st = s("station").to_uppercase();
                if !data.pois.iter().any(|p| sget(p, "name").to_uppercase() == st) {
                    errs.push(format!("找不到觀測站「{}」，請先新增地面 POI", s("station")));
                }
                let has = |k: &str| out.get(k).is_some_and(|v| !v.is_null());
                if !(has("ra_deg") && has("dec_deg")) && !(has("az_deg") && has("el_deg")) {
                    errs.push("需要 RA＋Dec 或 方位角＋仰角".into());
                }
            }
            "orbits" => {
                let (l1, l2) = (s("line1"), s("line2"));
                if !l1.starts_with("1 ") || !l2.starts_with("2 ") || l1.chars().count() < 68 || l2.chars().count() < 68 {
                    errs.push("TLE 兩行格式錯誤（第 1 行以「1 」、第 2 行以「2 」開頭，至少 68 字元）".into());
                } else {
                    match (tle_norad(&l1), tle_norad(&l2)) {
                        (Some(a), Some(b)) if a == b => {
                            let given = out.get("norad").and_then(Value::as_i64);
                            if let Some(g) = given.filter(|g| *g != a as i64) {
                                errs.push(format!("NORAD {g} 與 TLE 內的 {a} 不符"));
                            } else {
                                out.insert("norad".into(), Value::from(a));
                            }
                        }
                        _ => errs.push("TLE 兩行的 NORAD 編號不一致或無法辨識".into()),
                    }
                }
            }
            "claims" => {
                if s("confidence").is_empty() {
                    let c = src_conf(&s("source_type"));
                    out.insert("confidence".into(), Value::from(c));
                }
            }
            _ => {}
        }
    }
    if errs.is_empty() {
        Ok(out)
    } else {
        Err(errs)
    }
}

fn sget(m: &Map<String, Value>, k: &str) -> String {
    as_text(m.get(k))
}

// ── 儲存 ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Data {
    #[serde(default)]
    pub next_id: u64,
    #[serde(default)]
    pub pois: Vec<Map<String, Value>>,
    #[serde(default)]
    pub observations: Vec<Map<String, Value>>,
    #[serde(default)]
    pub orbits: Vec<Map<String, Value>>,
    #[serde(default)]
    pub claims: Vec<Map<String, Value>>,
    /// 舊版過頂預報常用中心點（forecast_sites.json）已併入地面 POI
    #[serde(default)]
    pub sites_migrated: bool,
}

impl Data {
    fn list(&mut self, kind: &str) -> Option<&mut Vec<Map<String, Value>>> {
        match kind {
            "pois" => Some(&mut self.pois),
            "observations" => Some(&mut self.observations),
            "orbits" => Some(&mut self.orbits),
            "claims" => Some(&mut self.claims),
            _ => None,
        }
    }
    fn used_by(&self, poi_name: &str) -> usize {
        let n = poi_name.to_uppercase();
        self.observations.iter().filter(|o| sget(o, "station").to_uppercase() == n).count()
    }
}

struct Store {
    path: PathBuf,
    data: Mutex<Data>,
    broken: bool,
}

static STORE: OnceCell<Store> = OnceCell::new();

fn store(cfg: &Config) -> &'static Store {
    STORE.get_or_init(|| {
        let path = cfg.home.join("user_private").join("observations.json");
        let exists = path.exists();
        let d = std::fs::read(&path).ok().and_then(|b| match serde_json::from_slice::<Data>(&b) {
            Ok(d) => Some(d),
            Err(e) => {
                tracing::error!("觀測資料檔格式錯誤（{}）：{e}", path.display());
                None
            }
        });
        let st = Store { broken: exists && d.is_none(), data: Mutex::new(d.unwrap_or_default()), path };
        migrate_sites(cfg, &st);
        st
    })
}

/// 舊版過頂預報常用中心點 → 地面 POI（關注地點；同名略過）。只做一次
fn migrate_sites(cfg: &Config, st: &Store) {
    if st.broken || st.data.lock().sites_migrated {
        return;
    }
    let Some(sites) = crate::forecast::legacy_sites(cfg) else {
        st.data.lock().sites_migrated = true;
        return;
    };
    let r = st.edit(|d| {
        let mut n = 0;
        for s in &sites {
            let rec = json!({"name": s.name, "lat": s.lat, "lon": s.lon, "alt_m": s.alt_m, "radius_km": s.radius_km, "kind": "site", "note": s.note});
            if let Ok(mut m) = validate("pois", &rec, d, None) {
                d.next_id += 1;
                let mut o = Map::new();
                o.insert("id".into(), json!(format!("o{}", d.next_id)));
                o.insert("by".into(), json!("（由過頂預報常用中心點轉入）"));
                o.insert("at".into(), json!(now_iso()));
                o.append(&mut m);
                d.pois.push(o);
                n += 1;
            }
        }
        d.sites_migrated = true;
        Ok(n)
    });
    match r {
        Ok(n) => tracing::info!("過頂預報常用中心點併入地面 POI：{n} 個"),
        Err(e) => tracing::warn!("過頂預報常用中心點併入地面 POI 失敗：{e}"),
    }
}

/// 全部地面 POI（過頂預報中心點選單用）
pub fn pois(cfg: &Config) -> Vec<Map<String, Value>> {
    store(cfg).snapshot().pois
}

/// 過頂預報「儲存為常用中心點」：依名稱寫回地面 POI（同名更新座標／半徑／備註並保留類型，新名稱新增為關注地點）
pub fn upsert_sites(cfg: &Config, by: &str, sites: &[Value]) -> Result<(usize, usize), String> {
    store(cfg).edit(|d| {
        let (mut upd, mut add) = (0, 0);
        for s in sites {
            let name = as_text(s.get("name"));
            let idx = d.pois.iter().position(|p| sget(p, "name").to_uppercase() == name.to_uppercase());
            match idx {
                Some(i) => {
                    let mut rec = Value::Object(d.pois[i].clone());
                    for k in ["lat", "lon", "alt_m", "radius_km", "note"] {
                        rec[k] = s.get(k).cloned().unwrap_or(Value::Null);
                    }
                    rec["name"] = json!(name);
                    let id = sget(&d.pois[i], "id");
                    let m = validate("pois", &rec, d, Some(&id)).map_err(|e| format!("「{name}」：{}", e.join("；")))?;
                    let p = &mut d.pois[i];
                    for (k, v) in m {
                        p.insert(k, v);
                    }
                    p.insert("at".into(), json!(now_iso()));
                    upd += 1;
                }
                None => {
                    let mut rec = s.clone();
                    rec["kind"] = json!("site");
                    let mut m = validate("pois", &rec, d, None).map_err(|e| format!("「{name}」：{}", e.join("；")))?;
                    d.next_id += 1;
                    let mut o = Map::new();
                    o.insert("id".into(), json!(format!("o{}", d.next_id)));
                    o.insert("by".into(), json!(by));
                    o.insert("at".into(), json!(now_iso()));
                    o.append(&mut m);
                    d.pois.push(o);
                    add += 1;
                }
            }
        }
        Ok((upd, add))
    })
}

impl Store {
    fn snapshot(&self) -> Data {
        self.data.lock().clone()
    }
    /// 在副本上修改 → 寫檔成功才替換（保留上一版 .bak）
    fn edit<R>(&self, f: impl FnOnce(&mut Data) -> Result<R, String>) -> Result<R, String> {
        if self.broken {
            return Err(format!("觀測資料檔 {} 格式錯誤，為避免覆蓋已停止寫入；請修復或改名後重新啟動", self.path.display()));
        }
        let mut g = self.data.lock();
        let mut next = g.clone();
        let r = f(&mut next)?;
        let bytes = serde_json::to_vec_pretty(&next).map_err(|e| e.to_string())?;
        if self.path.exists() {
            let _ = std::fs::copy(&self.path, self.path.with_extension("json.bak"));
        }
        atomic_write(&self.path, &bytes).map_err(|e| format!("寫入觀測資料檔失敗：{e}"))?;
        *g = next;
        Ok(r)
    }
}

fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

// ── 幾何 ─────────────────────────────────────────────────────────────────────

fn station_ecef(lat: f64, lon: f64, alt_m: f64) -> [f64; 7] {
    let (sl, cl) = lat.to_radians().sin_cos();
    let (so, co) = lon.to_radians().sin_cos();
    let n = A_WGS84 / (1.0 - E2 * sl * sl).sqrt();
    let h = alt_m / 1000.0;
    [(n + h) * cl * co, (n + h) * cl * so, (n * (1.0 - E2) + h) * sl, sl, cl, so, co]
}

/// 當日平赤道 → J2000（IAU 1976 歲差，Pᵀ·v）
fn precess_to_j2000(v: [f64; 3], t: &DateTime<Utc>) -> [f64; 3] {
    let tt = (julian_date(t) - 2451545.0) / 36525.0;
    let as2r = std::f64::consts::PI / (180.0 * 3600.0);
    let zeta = (2306.2181 * tt + 0.30188 * tt * tt + 0.017998 * tt.powi(3)) * as2r;
    let z = (2306.2181 * tt + 1.09468 * tt * tt + 0.018203 * tt.powi(3)) * as2r;
    let th = (2004.3109 * tt - 0.42665 * tt * tt - 0.041833 * tt.powi(3)) * as2r;
    let (cz, sz, ct, st, cx, sx) = (z.cos(), z.sin(), th.cos(), th.sin(), zeta.cos(), zeta.sin());
    let p = [
        [cz * ct * cx - sz * sx, -cz * ct * sx - sz * cx, -cz * st],
        [sz * ct * cx + cz * sx, -sz * ct * sx + cz * cx, -sz * st],
        [st * cx, -st * sx, ct],
    ];
    [
        p[0][0] * v[0] + p[1][0] * v[1] + p[2][0] * v[2],
        p[0][1] * v[0] + p[1][1] * v[1] + p[2][1] * v[2],
        p[0][2] * v[0] + p[1][2] * v[1] + p[2][2] * v[2],
    ]
}

struct Look {
    ra: f64,
    dec: f64,
    az: f64,
    el: f64,
    rng: f64,
}

fn look(r: &[f64; 3], t: &DateTime<Utc>, stn: &[f64; 7]) -> Look {
    let g = gmst_rad(t);
    let (sg, cg) = g.sin_cos();
    let [x0, y0, z0, sl, cl, so, co] = *stn;
    let (xe, ye, ze) = (cg * r[0] + sg * r[1], -sg * r[0] + cg * r[1], r[2]);
    let (dx, dy, dz) = (xe - x0, ye - y0, ze - z0);
    let e = -so * dx + co * dy;
    let n = -sl * co * dx - sl * so * dy + cl * dz;
    let u = cl * co * dx + cl * so * dy + sl * dz;
    let rng = (e * e + n * n + u * u).sqrt();
    let el = (u / rng.max(1e-3)).clamp(-1.0, 1.0).asin().to_degrees();
    let az = e.atan2(n).to_degrees().rem_euclid(360.0);
    let v = precess_to_j2000([cg * dx - sg * dy, sg * dx + cg * dy, dz], t);
    let ra = v[1].atan2(v[0]).to_degrees().rem_euclid(360.0);
    let dec = (v[2] / (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt()).clamp(-1.0, 1.0).asin().to_degrees();
    Look { ra, dec, az, el, rng }
}

fn unit_radec(ra: f64, dec: f64) -> [f64; 3] {
    let (a, d) = (ra.to_radians(), dec.to_radians());
    [d.cos() * a.cos(), d.cos() * a.sin(), d.sin()]
}
fn unit_azel(az: f64, el: f64) -> [f64; 3] {
    let (a, e) = (az.to_radians(), el.to_radians());
    [e.cos() * a.sin(), e.cos() * a.cos(), e.sin()]
}
fn sep_deg(u: &[f64; 3], v: &[f64; 3]) -> f64 {
    let cx = u[1] * v[2] - u[2] * v[1];
    let cy = u[2] * v[0] - u[0] * v[2];
    let cz = u[0] * v[1] - u[1] * v[0];
    (cx * cx + cy * cy + cz * cz).sqrt().atan2(u[0] * v[0] + u[1] * v[1] + u[2] * v[2]).to_degrees()
}

fn make_prop(l1: &str, l2: &str) -> Option<Propagator> {
    let (a, b) = (l1.trim_end(), l2.trim_end());
    if a.len() < 60 || b.len() < 60 || !a.starts_with("1 ") || !b.starts_with("2 ") {
        return None;
    }
    Propagator::from_tle(a, b)
}

fn fnum(m: &Map<String, Value>, k: &str) -> Option<f64> {
    match m.get(k)? {
        Value::Number(n) => n.as_f64(),
        Value::String(s) if !s.trim().is_empty() => s.trim().parse().ok(),
        _ => None,
    }
    .filter(|x: &f64| x.is_finite())
}

fn norad_of(v: Option<&Value>) -> Option<u32> {
    let n: i64 = match v? {
        Value::Number(n) => {
            let f = n.as_f64()?;
            if f.fract() != 0.0 {
                return None;
            }
            f as i64
        }
        Value::String(s) => s.trim().parse().ok()?,
        _ => return None,
    };
    (n > 0 && n < 1_000_000).then_some(n as u32)
}

fn obs_status(sep: Option<f64>) -> &'static str {
    match sep {
        None => "unknown",
        Some(s) if s <= OBS_OK => "consistent",
        Some(s) if s <= OBS_MARGINAL => "marginal",
        _ => "inconsistent",
    }
}
fn orb_status(d: Option<f64>) -> &'static str {
    match d {
        None => "unknown",
        Some(x) if x <= ORB_OK => "consistent",
        Some(x) if x <= ORB_CLOSE => "close",
        _ => "divergent",
    }
}

/// 目錄（TLE 索引＋SATCAT）與同次發射分組
struct Ctx {
    sats: HashMap<u32, (String, String, String)>, // name（目錄原名）, line1, line2
    sc: ephemeris::Satcat,
    props: Mutex<HashMap<u32, Option<Arc<Propagator>>>>,
    tags: HashMap<String, Vec<u32>>,
}

impl Ctx {
    fn new(st: &Arc<AppState>) -> Self {
        let idx = st.index();
        let custom = st.satadmin.snapshot();
        let mut sats = HashMap::new();
        let mut tags: HashMap<String, Vec<u32>> = HashMap::new();
        for (n, s) in idx.sats.iter() {
            // 自訂名稱前的目錄原名（與線上版的目錄名稱一致）
            let name = custom.names.get(n).map(|r| r.orig.clone()).filter(|o| !o.is_empty()).unwrap_or_else(|| s.name.clone());
            let t: String = intl_code(&s.line1).chars().take(8).collect();
            if t.chars().count() == 8 {
                tags.entry(t).or_default().push(*n);
            }
            sats.insert(*n, (name.trim().to_string(), s.line1.clone(), s.line2.clone()));
        }
        for v in tags.values_mut() {
            v.sort_unstable();
        }
        Self { sats, sc: ephemeris::satcat(&st.cfg), props: Mutex::new(HashMap::new()), tags }
    }
    fn prop(&self, n: u32) -> Option<Arc<Propagator>> {
        if let Some(p) = self.props.lock().get(&n) {
            return p.clone();
        }
        let p = self.sats.get(&n).filter(|s| !s.1.is_empty() && !s.2.is_empty()).and_then(|s| make_prop(&s.1, &s.2)).map(Arc::new);
        self.props.lock().insert(n, p.clone());
        p
    }
    fn tag_of(&self, n: u32) -> String {
        let mut t: String = self.sats.get(&n).map(|s| intl_code(&s.1).chars().take(8).collect()).unwrap_or_default();
        if t.chars().count() < 8 {
            t = self.sc.get(&n).map(|r| r.intl.chars().take(8).collect()).unwrap_or_default();
        }
        t
    }
    fn name(&self, n: u32) -> String {
        match self.sats.get(&n) {
            Some(s) if !s.0.is_empty() => s.0.clone(),
            _ => self.sc.get(&n).map(|r| r.name.clone()).unwrap_or_default(),
        }
    }
    fn official(&self, n: u32) -> String {
        let nm = self.sc.get(&n).map(|r| r.name.trim().to_string()).unwrap_or_default();
        if crate::changes::is_noname(&nm) {
            String::new()
        } else {
            nm
        }
    }
    fn in_catalog(&self, n: u32) -> bool {
        self.sats.contains_key(&n)
    }
    fn line1(&self, n: u32) -> String {
        self.sats.get(&n).map(|s| s.1.clone()).unwrap_or_default()
    }
}

fn obs_dir(o: &Map<String, Value>) -> Option<(&'static str, [f64; 3])> {
    let (ra, dec, az, el) = (fnum(o, "ra_deg"), fnum(o, "dec_deg"), fnum(o, "az_deg"), fnum(o, "el_deg"));
    if let (Some(ra), Some(dec)) = (ra, dec) {
        if (0.0..=360.0).contains(&ra) && (-90.0..=90.0).contains(&dec) {
            return Some(("radec", unit_radec(ra, dec)));
        }
    }
    if let (Some(az), Some(el)) = (az, el) {
        if (0.0..=360.0).contains(&az) && (-90.0..=90.0).contains(&el) {
            return Some(("azel", unit_azel(az, el)));
        }
    }
    None
}

fn predict_sep(p: Option<&Propagator>, t: &DateTime<Utc>, stn: &[f64; 7], frame: &str, u: &[f64; 3]) -> Option<(f64, Look)> {
    let r = p?.position(t)?;
    let lk = look(&r, t, stn);
    let v = if frame == "radec" { unit_radec(lk.ra, lk.dec) } else { unit_azel(lk.az, lk.el) };
    Some((sep_deg(u, &v), lk))
}

fn idv(m: &Map<String, Value>) -> Value {
    m.get("id").cloned().unwrap_or(Value::Null)
}

fn check_observation(o: &Map<String, Value>, ctx: &Ctx, pois: &HashMap<String, &Map<String, Value>>, orbits_by_norad: &BTreeMap<u32, Vec<&Map<String, Value>>>) -> Value {
    let n = norad_of(o.get("norad"));
    let mut out = json!({"id": idv(o), "norad": n, "errors": [], "warnings": [], "status": "unknown", "sep_deg": null, "predicted": null,
                         "by_orbit": [], "candidates": [], "best": null});
    let mut errors: Vec<String> = vec![];
    let mut warnings: Vec<String> = vec![];
    let t = parse_time(&sget(o, "time")).map(|x| x.1);
    let poi = pois.get(&sget(o, "station").to_uppercase()).copied();
    let d = obs_dir(o);
    if t.is_none() {
        errors.push("時間格式錯誤（YYYY-MM-DD HH:MM:SS UTC）".into());
    }
    if poi.is_none() {
        errors.push("找不到觀測站（地面 POI）".into());
    }
    if d.is_none() {
        errors.push("需要 RA/Dec 或方位／仰角".into());
    }
    if !errors.is_empty() {
        out["errors"] = json!(errors);
        return out;
    }
    let (t, poi, (frame, u)) = (t.unwrap(), poi.unwrap(), d.unwrap());
    let (Some(lat), Some(lon)) = (fnum(poi, "lat"), fnum(poi, "lon")) else {
        out["errors"] = json!(["觀測站經緯度錯誤"]);
        return out;
    };
    let alt = fnum(poi, "alt_m").filter(|a| *a != 0.0).unwrap_or(0.0);
    let stn = station_ecef(lat, lon, alt);
    out["frame"] = json!(frame);
    let Some(n) = n else {
        out["warnings"] = json!(["未指定 NORAD，無法比對"]);
        return out;
    };
    let mut sep_r: Option<f64> = None;
    let cat = ctx.prop(n);
    if let Some((s, lk)) = predict_sep(cat.as_deref(), &t, &stn, frame, &u) {
        sep_r = Some(rnd(s, 3));
        out["predicted"] = json!({"ra": rnd(lk.ra, 3), "dec": rnd(lk.dec, 3), "az": rnd(lk.az, 3), "el": rnd(lk.el, 3), "rng_km": rnd(lk.rng, 1)});
        if lk.el < 0.0 {
            warnings.push("預測時衛星在觀測站地平線下".into());
        }
        if let Some(ep) = tle_epoch(&ctx.line1(n)) {
            let dd = ((ep - t).num_microseconds().unwrap_or(0) as f64 / 1e6).abs();
            if dd > 7.0 * 86400.0 {
                warnings.push(format!("目錄 TLE 曆元距觀測 {:.1} 天，預測誤差可能偏大", dd / 86400.0));
            }
        }
    } else if !ctx.in_catalog(n) {
        warnings.push("目錄中沒有此 NORAD 的 TLE".into());
    }
    out["sep_deg"] = json!(sep_r);
    out["status"] = json!(obs_status(sep_r));
    let mut by_orbit = vec![];
    for orb in orbits_by_norad.get(&n).map(|v| v.as_slice()).unwrap_or(&[]) {
        let p = make_prop(&sget(orb, "line1"), &sget(orb, "line2"));
        if let Some((so, _)) = predict_sep(p.as_ref(), &t, &stn, frame, &u) {
            by_orbit.push(json!({"orbit_id": idv(orb), "sep_deg": rnd(so, 3), "status": obs_status(Some(so))}));
        }
    }
    out["by_orbit"] = json!(by_orbit);
    let mut cands: Vec<(f64, u32, f64)> = vec![];
    for &m in ctx.tags.get(&ctx.tag_of(n)).map(|v| v.as_slice()).unwrap_or(&[]) {
        if let Some((sm, lm)) = predict_sep(ctx.prop(m).as_deref(), &t, &stn, frame, &u) {
            cands.push((rnd(sm, 3), m, rnd(lm.el, 1)));
        }
    }
    cands.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)).then(a.2.total_cmp(&b.2)));
    out["candidates"] = json!(cands.iter().take(TOP_N).map(|(s, m, el)| json!({"norad": m, "name": ctx.name(*m), "sep_deg": s, "el_deg": el})).collect::<Vec<_>>());
    if let Some(&(s0, m0, _)) = cands.first() {
        out["best"] = json!(m0);
        if m0 != n && sep_r.is_some_and(|sr| s0 < sr) {
            warnings.push(format!("同次發射中 NORAD {m0}（{}）較符合：{s0:.3}°", ctx.name(m0)));
        }
    }
    out["warnings"] = json!(warnings);
    out
}

fn check_orbit(s: &Map<String, Value>, ctx: &Ctx) -> Value {
    let mut out = json!({"id": idv(s), "norad": null, "errors": [], "warnings": [], "status": "unknown", "epoch": null,
                         "d0_km": null, "dmax_km": null, "catalog_epoch_days": null, "candidates": [], "best": null});
    let (l1, l2) = (sget(s, "line1"), sget(s, "line2"));
    let p = make_prop(&l1, &l2);
    let ep = p.as_ref().and_then(|_| tle_epoch(&l1));
    let (Some(p), Some(ep)) = (p, ep) else {
        out["errors"] = json!(["TLE 格式錯誤或無法傳播"]);
        return out;
    };
    let mut warnings: Vec<String> = vec![];
    let n = tle_norad(&l1).filter(|n| *n > 0 && *n < 1_000_000);
    out["norad"] = json!(n);
    let ms = ep.timestamp_subsec_millis();
    out["epoch"] = json!(format!("{}{}", ep.format("%Y-%m-%d %H:%M:%S"), if ms > 0 { format!(".{ms:03}") } else { String::new() }));
    let times: Vec<DateTime<Utc>> = (-GRID_H..=GRID_H).map(|k| ep + Duration::hours(k)).collect();
    let mine: Vec<Option<[f64; 3]>> = times.iter().map(|t| p.position(t)).collect();
    let diff = |q: Option<&Propagator>| -> (Option<f64>, Option<f64>) {
        let Some(q) = q else { return (None, None) };
        let (mut d0, mut dmax, mut any) = (None, f64::MIN, false);
        for (k, (t, a)) in times.iter().zip(&mine).enumerate() {
            let (Some(a), Some(b)) = (a, q.position(t)) else { continue };
            let d = ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt();
            any = true;
            dmax = dmax.max(d);
            if k as i64 == GRID_H {
                d0 = Some(d);
            }
        }
        if any {
            (d0, Some(dmax))
        } else {
            (None, None)
        }
    };
    let mut dmax_r = None;
    match n.filter(|n| ctx.in_catalog(*n)) {
        Some(n) => {
            let (d0, dm) = diff(ctx.prop(n).as_deref());
            out["d0_km"] = json!(d0.map(|x| rnd(x, 2)));
            dmax_r = dm.map(|x| rnd(x, 2));
            out["dmax_km"] = json!(dmax_r);
            if let Some(ce) = tle_epoch(&ctx.line1(n)) {
                let dd = (ce - ep).num_microseconds().unwrap_or(0) as f64 / 1e6;
                out["catalog_epoch_days"] = json!(rnd(dd / 86400.0, 2));
                if dd.abs() > 7.0 * 86400.0 {
                    warnings.push(format!("目錄 TLE 曆元與軌道解相差 {:.1} 天，位置差含傳播誤差", dd.abs() / 86400.0));
                }
            }
            out["status"] = json!(orb_status(dmax_r));
        }
        None => {
            out["status"] = json!("no_catalog");
            warnings.push("目錄中沒有此 NORAD 的 TLE（獨立軌道解）".into());
        }
    }
    let tag: String = intl_code(&l1).chars().take(8).collect();
    let mut cands: Vec<(f64, u32)> = vec![];
    for &m in ctx.tags.get(&tag).map(|v| v.as_slice()).unwrap_or(&[]) {
        if let (_, Some(dm)) = diff(ctx.prop(m).as_deref()) {
            cands.push((rnd(dm, 2), m));
        }
    }
    cands.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
    out["candidates"] = json!(cands.iter().take(TOP_N).map(|(d, m)| json!({"norad": m, "name": ctx.name(*m), "dmax_km": d})).collect::<Vec<_>>());
    if let Some(&(d0, m0)) = cands.first() {
        out["best"] = json!(m0);
        if Some(m0) != n && dmax_r.is_none_or(|x| d0 < x) {
            warnings.push(format!("軌道最接近 NORAD {m0}（{}，最大差 {d0:.2} km）", ctx.name(m0)));
        }
    }
    out["warnings"] = json!(warnings);
    out
}

fn check_claim(c: &Map<String, Value>, ctx: &Ctx, claims_by_norad: &BTreeMap<u32, Vec<&Map<String, Value>>>) -> Value {
    let n = norad_of(c.get("norad"));
    let mut out = json!({"id": idv(c), "norad": n, "errors": [], "warnings": [], "status": "unknown", "official_name": null});
    let name = sget(c, "name");
    let Some(n) = n.filter(|_| !name.is_empty()) else {
        out["errors"] = json!(["需要 NORAD 與名稱"]);
        return out;
    };
    let off = ctx.official(n);
    out["official_name"] = if off.is_empty() { Value::Null } else { json!(off) };
    let mut others: Vec<String> = claims_by_norad
        .get(&n)
        .map(|v| v.as_slice())
        .unwrap_or(&[])
        .iter()
        .filter(|x| x.get("id") != c.get("id") && sget(x, "review") != "rejected")
        .map(|x| sget(x, "name"))
        .filter(|x| !x.is_empty() && *x != name)
        .collect();
    others.sort();
    others.dedup();
    let mut warnings: Vec<String> = vec![];
    let status = if !off.is_empty() && off.to_uppercase() == name.to_uppercase() {
        "matches_official"
    } else if !off.is_empty() {
        warnings.push(format!("Space-Track 已正式命名為 {off}"));
        "differs_official"
    } else if !others.is_empty() {
        "disputed"
    } else {
        "uncontested"
    };
    if !others.is_empty() {
        warnings.push(format!("另有主張：{}", others.join("、")));
    }
    out["status"] = json!(status);
    out["warnings"] = json!(warnings);
    out
}

struct Per<'a> {
    o: Vec<(String, &'a Value)>,
    b: Vec<(String, &'a Value)>,
    c: Vec<&'a Map<String, Value>>,
}

fn summarize(n: u32, ctx: &Ctx, p: &Per) -> Value {
    let off = ctx.official(n);
    let live: Vec<&&Map<String, Value>> = p.c.iter().filter(|c| sget(c, "review") != "rejected" && !sget(c, "name").is_empty()).collect();
    let mut names: Vec<String> = live.iter().map(|c| sget(c, "name")).collect();
    names.sort();
    names.dedup();
    let conf = |c: &Map<String, Value>| {
        let v = sget(c, "confidence");
        if v.is_empty() {
            src_conf(&sget(c, "source_type")).to_string()
        } else {
            v
        }
    };
    let ident = if !off.is_empty() {
        "confirmed"
    } else if names.len() > 1 {
        "disputed"
    } else if live.iter().any(|c| sget(c, "review") == "accepted" && conf(c) == "high") {
        "confirmed"
    } else if live.iter().any(|c| sget(c, "review") == "accepted") {
        "probable"
    } else if !live.is_empty() {
        "claimed"
    } else {
        "unknown"
    };
    let ok_orbs: Vec<&(String, &Value)> = p.b.iter().filter(|(rv, ch)| rv != "rejected" && ch["errors"].as_array().is_some_and(|e| e.is_empty())).collect();
    let orbit = if ok_orbs.is_empty() {
        if ctx.in_catalog(n) {
            "catalog_only"
        } else {
            "none"
        }
    } else {
        // 取曆元最新者（同曆元取第一筆，與 Python max 相同）
        let mut last = ok_orbs[0];
        for o in &ok_orbs[1..] {
            if o.1["epoch"].as_str().unwrap_or("") > last.1["epoch"].as_str().unwrap_or("") {
                last = o;
            }
        }
        match last.1["status"].as_str().unwrap_or("") {
            "consistent" => "corroborated",
            "close" => "close",
            "divergent" => "divergent",
            "no_catalog" => "independent_only",
            _ => "unknown",
        }
    };
    let st: Vec<&str> = p.o.iter().filter(|(rv, ch)| rv != "rejected" && ch["status"] != "unknown").map(|(_, ch)| ch["status"].as_str().unwrap_or("")).collect();
    let ob = if st.is_empty() {
        "none"
    } else if st.iter().all(|s| *s == "consistent") {
        "consistent"
    } else if st.iter().any(|s| *s == "consistent") {
        "mixed"
    } else if st.iter().all(|s| *s == "inconsistent") {
        "inconsistent"
    } else {
        "marginal"
    };
    let tag = ctx.tag_of(n);
    let best_claim = live.iter().find(|c| sget(c, "review") == "accepted").or(live.first());
    let indiv = if !off.is_empty() { json!(off) } else { best_claim.map(|c| c.get("name").cloned().unwrap_or(Value::Null)).unwrap_or(Value::Null) };
    let opt = |s: &str| if s.is_empty() { Value::Null } else { json!(s) };
    json!({
        "norad": n, "name": ctx.name(n), "official_name": opt(&off), "launch_tag": opt(&tag), "in_catalog": ctx.in_catalog(n),
        "identity_status": ident, "orbit_status": orbit, "observation_status": ob,
        "mission_status": "unknown", "capability_status": "unknown",
        "layers": {
            "launch_group": {"value": opt(&tag), "confidence": if tag.is_empty() { Value::Null } else { json!("high") }},
            "candidate_mission": {"value": if names.is_empty() { Value::Null } else { json!(names) }, "confidence": if names.is_empty() { Value::Null } else { json!("medium") }},
            "individual": {"value": indiv, "status": ident},
        },
        "counts": {"observations": p.o.len(), "orbits": p.b.len(), "claims": p.c.len()},
    })
}

/// 交叉驗證（無狀態）：輸入四種紀錄，輸出每筆結果與每顆衛星摘要
fn check_all(data: &Value, ctx: &Ctx) -> Value {
    let arr = |k: &str| -> Vec<&Map<String, Value>> { data.get(k).and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_object).collect()).unwrap_or_default() };
    let (pois_v, orbits, claims, observations) = (arr("pois"), arr("orbits"), arr("claims"), arr("observations"));
    let mut pois: HashMap<String, &Map<String, Value>> = HashMap::new();
    for p in pois_v {
        pois.insert(sget(p, "name").to_uppercase(), p);
    }
    let mut orbits_by_norad: BTreeMap<u32, Vec<&Map<String, Value>>> = BTreeMap::new();
    for o in &orbits {
        if let Some(n) = tle_norad(&sget(o, "line1")).filter(|n| *n > 0 && *n < 1_000_000) {
            if sget(o, "review") != "rejected" {
                orbits_by_norad.entry(n).or_default().push(o);
            }
        }
    }
    let mut claims_by_norad: BTreeMap<u32, Vec<&Map<String, Value>>> = BTreeMap::new();
    for c in &claims {
        if let Some(n) = norad_of(c.get("norad")) {
            claims_by_norad.entry(n).or_default().push(c);
        }
    }
    let observations: Vec<_> = observations.into_iter().take(2000).collect();
    let orbits: Vec<_> = orbits.into_iter().take(1000).collect();
    let claims: Vec<_> = claims.into_iter().take(5000).collect();
    let r_obs: Vec<Value> = observations.iter().map(|o| check_observation(o, ctx, &pois, &orbits_by_norad)).collect();
    let r_orb: Vec<Value> = orbits.iter().map(|o| check_orbit(o, ctx)).collect();
    let r_clm: Vec<Value> = claims.iter().map(|c| check_claim(c, ctx, &claims_by_norad)).collect();
    let mut per: BTreeMap<u32, Per> = BTreeMap::new();
    let new = || Per { o: vec![], b: vec![], c: vec![] };
    for (rec, ch) in observations.iter().zip(&r_obs) {
        if let Some(n) = ch["norad"].as_u64() {
            per.entry(n as u32).or_insert_with(new).o.push((sget(rec, "review"), ch));
        }
    }
    for (rec, ch) in orbits.iter().zip(&r_orb) {
        if let Some(n) = ch["norad"].as_u64() {
            per.entry(n as u32).or_insert_with(new).b.push((sget(rec, "review"), ch));
        }
    }
    for (rec, ch) in claims.iter().zip(&r_clm) {
        if let Some(n) = ch["norad"].as_u64() {
            per.entry(n as u32).or_insert_with(new).c.push(rec);
        }
    }
    let sats: Vec<Value> = per.iter().rev().map(|(n, p)| summarize(*n, ctx, p)).collect();
    json!({"observations": r_obs, "orbits": r_orb, "claims": r_clm, "sats": sats,
           "thresholds": {"obs_ok_deg": OBS_OK, "obs_marginal_deg": OBS_MARGINAL, "orbit_ok_km": ORB_OK, "orbit_close_km": ORB_CLOSE, "grid_hours": GRID_H}})
}

// ── API ──────────────────────────────────────────────────────────────────────

type St = State<Arc<AppState>>;

fn jerr(s: StatusCode, m: impl Into<String>) -> Response {
    (s, Json(json!({"error": m.into()}))).into_response()
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/obs", get(page))
        .route("/api/obs/data", get(api_data))
        .route("/api/obs/check", get(api_check_stored).post(api_check))
        .route("/api/obs/{kind}", post(api_add))
        .route("/api/obs/{kind}/{id}", put(api_update).delete(api_delete))
        .route("/api/obs/{kind}/{id}/review", post(api_review))
}

async fn page() -> Html<String> {
    let raw = crate::assets::get("ext/obs.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

async fn api_data(State(st): St) -> Json<Value> {
    Json(json!(store(&st.cfg).snapshot()))
}

async fn run_check(st: Arc<AppState>, data: Value) -> Json<Value> {
    let v = tokio::task::spawn_blocking(move || {
        let ctx = Ctx::new(&st);
        check_all(&data, &ctx)
    })
    .await
    .unwrap_or_else(|e| json!({"error": e.to_string()}));
    Json(v)
}

async fn api_check(State(st): St, Json(body): Json<Value>) -> Response {
    if !body.is_object() {
        return jerr(StatusCode::BAD_REQUEST, "需要 JSON 物件");
    }
    run_check(st.clone(), body).await.into_response()
}

async fn api_check_stored(State(st): St) -> Response {
    let d = json!(store(&st.cfg).snapshot());
    run_check(st.clone(), d).await.into_response()
}

#[derive(Deserialize)]
struct AddReq {
    records: Vec<Value>,
}

async fn api_add(State(st): St, Extension(c): Extension<Caller>, Path(kind): Path<String>, Json(b): Json<AddReq>) -> Response {
    if !c.can_edit() {
        return jerr(StatusCode::FORBIDDEN, "需要編輯者以上權限（輸入／新增／修改）");
    }
    if !KINDS.contains(&kind.as_str()) {
        return jerr(StatusCode::NOT_FOUND, "未知的資料種類");
    }
    if b.records.is_empty() || b.records.len() > 5000 {
        return jerr(StatusCode::BAD_REQUEST, "一次 1–5000 筆");
    }
    let (by, admin) = (c.name(), c.is_admin());
    let res = store(&st.cfg).edit(|d| {
        let mut added = 0usize;
        let mut errors = vec![];
        for (i, r) in b.records.iter().enumerate() {
            let row = r.get("_row").and_then(Value::as_u64).unwrap_or(i as u64 + 1);
            match validate(&kind, r, d, None) {
                Ok(mut m) => {
                    d.next_id += 1;
                    let rv = as_text(r.get("review"));
                    let rv = if admin && REVIEWS.contains(&rv.as_str()) { rv } else { "unreviewed".into() };
                    let note: String = if admin { as_text(r.get("review_note")).chars().take(500).collect() } else { String::new() };
                    let mut o = Map::new();
                    o.insert("id".into(), json!(format!("o{}", d.next_id)));
                    o.insert("by".into(), json!(by));
                    o.insert("at".into(), json!(now_iso()));
                    o.insert("reviewer".into(), json!(if rv != "unreviewed" { by.clone() } else { String::new() }));
                    o.insert("reviewed_at".into(), json!(if rv != "unreviewed" { now_iso() } else { String::new() }));
                    o.insert("review".into(), json!(rv));
                    o.insert("review_note".into(), json!(note));
                    o.append(&mut m);
                    d.list(&kind).unwrap().push(o);
                    added += 1;
                }
                Err(e) => errors.push(json!({"row": row, "msg": e.join("；")})),
            }
        }
        Ok(json!({"added": added, "errors": errors}))
    });
    match res {
        Ok(v) => Json(v).into_response(),
        Err(e) => jerr(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_update(State(st): St, Extension(c): Extension<Caller>, Path((kind, id)): Path<(String, String)>, Json(rec): Json<Value>) -> Response {
    if !c.can_edit() {
        return jerr(StatusCode::FORBIDDEN, "需要編輯者以上權限（輸入／新增／修改）");
    }
    let res = store(&st.cfg).edit(|d| {
        let snapshot = d.clone();
        let list = d.list(&kind).ok_or("未知的資料種類")?;
        let i = list.iter().position(|r| sget(r, "id") == id).ok_or_else(|| format!("找不到紀錄 {id}"))?;
        let m = validate(&kind, &rec, &snapshot, Some(&id)).map_err(|e| e.join("；"))?;
        if kind == "pois" {
            let old = sget(&list[i], "name");
            let new = m.get("name").and_then(Value::as_str).unwrap_or("");
            let used = snapshot.used_by(&old);
            if old.to_uppercase() != new.to_uppercase() && used > 0 {
                return Err(format!("有 {used} 筆觀測紀錄使用此觀測站，不能改名"));
            }
        }
        let r = &mut list[i];
        let changed = m.iter().any(|(k, v)| r.get(k) != Some(v));
        for (k, v) in m {
            r.insert(k, v);
        }
        r.insert("at".into(), json!(now_iso()));
        // 內容有變動 → 需重新複核
        if changed && kind != "pois" && sget(r, "review") != "unreviewed" {
            r.insert("review".into(), json!("unreviewed"));
            r.insert("review_note".into(), json!(format!("內容已修改（{}），需重新複核", c.name())));
            r.insert("reviewer".into(), json!(""));
            r.insert("reviewed_at".into(), json!(""));
        }
        Ok(Value::Object(r.clone()))
    });
    match res {
        Ok(v) => Json(v).into_response(),
        Err(e) => jerr(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_delete(State(st): St, Extension(c): Extension<Caller>, Path((kind, id)): Path<(String, String)>) -> Response {
    if !c.can_edit() {
        return jerr(StatusCode::FORBIDDEN, "需要編輯者以上權限（輸入／新增／修改）");
    }
    let res = store(&st.cfg).edit(|d| {
        let snapshot = d.clone();
        let list = d.list(&kind).ok_or("未知的資料種類")?;
        let i = list.iter().position(|r| sget(r, "id") == id).ok_or_else(|| format!("找不到紀錄 {id}"))?;
        if kind == "pois" {
            let used = snapshot.used_by(&sget(&list[i], "name"));
            if used > 0 {
                return Err(format!("有 {used} 筆觀測紀錄使用此觀測站，請先刪除那些紀錄"));
            }
        }
        list.remove(i);
        Ok(())
    });
    match res {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err(e) => jerr(StatusCode::BAD_REQUEST, e),
    }
}

#[derive(Deserialize)]
struct ReviewReq {
    review: String,
    #[serde(default)]
    review_note: String,
}

async fn api_review(State(st): St, Extension(c): Extension<Caller>, Path((kind, id)): Path<(String, String)>, Json(b): Json<ReviewReq>) -> Response {
    if !c.is_admin() {
        return jerr(StatusCode::FORBIDDEN, "複核需要管理者權限");
    }
    if !REVIEWS.contains(&b.review.as_str()) || kind == "pois" {
        return jerr(StatusCode::BAD_REQUEST, "複核狀態錯誤");
    }
    let by = c.name();
    let res = store(&st.cfg).edit(|d| {
        let list = d.list(&kind).ok_or("未知的資料種類")?;
        let r = list.iter_mut().find(|r| sget(r, "id") == id).ok_or_else(|| format!("找不到紀錄 {id}"))?;
        r.insert("review".into(), json!(b.review));
        r.insert("review_note".into(), json!(b.review_note.chars().take(500).collect::<String>()));
        r.insert("reviewer".into(), json!(by));
        r.insert("reviewed_at".into(), json!(now_iso()));
        Ok(Value::Object(r.clone()))
    });
    match res {
        Ok(v) => Json(v).into_response(),
        Err(e) => jerr(StatusCode::BAD_REQUEST, e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn time_parse() {
        assert_eq!(parse_time("2026-11-25 11:02:30").unwrap().0, "2026-11-25 11:02:30");
        assert_eq!(parse_time("2026-11-25T11:02:30.5Z").unwrap().0, "2026-11-25 11:02:30.5");
        assert_eq!(parse_time("2026-11-25 11:02").unwrap().0, "2026-11-25 11:02:00");
        for bad in ["2026-02-30 00:00:00", "2026-11-25 24:00:00", "2026/11/25 11:02:30", "2026-11-25 11:02:30.", ""] {
            assert!(parse_time(bad).is_none(), "{bad}");
        }
    }

    #[test]
    fn validate_rules() {
        let mut d = Data::default();
        let poi = validate("pois", &json!({"name": "台北站", "lat": "25.03", "lon": 121.56}), &d, None).unwrap();
        assert_eq!(poi["alt_m"], json!(0.0));
        assert_eq!(poi["kind"], json!("station"));
        d.pois.push(poi);
        assert!(validate("pois", &json!({"name": "台北站", "lat": 1, "lon": 1}), &d, None).unwrap_err()[0].contains("同名"));
        let e = validate("observations", &json!({"station": "台北站", "time": "2026-11-25 11:02:30"}), &d, None).unwrap_err();
        assert!(e[0].contains("RA"));
        assert!(validate("observations", &json!({"station": "台中站", "time": "2026-11-25 11:02:30", "az_deg": 1, "el_deg": 2}), &d, None).is_err());
        let o = validate("observations", &json!({"station": "台北站", "time": "2026-11-25T11:02:30Z", "az_deg": "10", "el_deg": "20", "norad": "25544"}), &d, None).unwrap();
        assert_eq!(o["norad"], json!(25544));
        assert_eq!(o["time"], json!("2026-11-25 11:02:30"));
        let l1 = "1 25544U 98067A   26329.50000000  .00016717  00000-0  10270-3 0  9994";
        let l2 = "2 25544  51.6400 208.9163 0006317  69.9862 290.2104 15.50000000000017";
        assert_eq!(validate("orbits", &json!({"line1": l1, "line2": l2}), &d, None).unwrap()["norad"], json!(25544));
        assert!(validate("orbits", &json!({"line1": l1, "line2": l2, "norad": 1}), &d, None).unwrap_err()[0].contains("不符"));
        let c = validate("claims", &json!({"norad": 1, "name": "X", "source_type": "official"}), &d, None).unwrap();
        assert_eq!(c["confidence"], json!("high"));
        assert!(validate("claims", &json!({"norad": 1, "name": "X", "source_url": "ftp://x"}), &d, None).is_err());
    }

    #[test]
    fn alpha5() {
        assert_eq!(tle_norad("1 A1419U 26260J   26328.5"), Some(101419));
        assert_eq!(tle_norad("1 Z9999U"), Some(339999));
        assert_eq!(tle_norad("1 25544U"), Some(25544));
        assert_eq!(tle_norad("1  1234U"), Some(1234));
        assert_eq!(tle_norad("1 I1234U"), None);
    }

    #[test]
    fn rounding_matches_python() {
        assert_eq!(rnd(2.3456, 2), 2.35);
        assert_eq!(rnd(-2.5, 0), -3.0);
        assert_eq!(rnd(0.0004, 3), 0.0);
    }
}
