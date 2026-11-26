//! 衛星管理（客戶回饋第 1、2 項）：依 NORAD ID 手動更名、自訂群組分類（可多層，如
//! 「PRC 偵察衛星 → 光學／雷達／電子偵察」）、CSV 匯入匯出、操作紀錄。
//!
//! 資料存在 <資料目錄>\user_private\sat_custom.json（全組織共用、只存本機、不上傳）。
//! 更名於索引建立時套用（地球儀、搜尋、報表都看到新名稱）；原 Space-Track 名稱保留在 orig。

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Extension, Json, Router};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::auth::{atomic_write, Caller};
use crate::config::Config;
use crate::index::{SatIndex, SatInfo};
use crate::state::AppState;

const AUDIT_MAX: usize = 2000;
pub const SENSORS: [&str; 5] = ["", "optical", "radar", "sigint", "other"];

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct NameRec {
    pub name: String,
    #[serde(default)]
    pub orig: String,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub by: String,
    #[serde(default)]
    pub at: String,
    /// 名稱證據等級：official／inferred／group_inferred／conflict／manual（人工輸入）
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub status: String,
    /// high／medium／low
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub confidence: String,
    /// 證據連結（來源網址、SeeSat-L 討論串等）
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence: Vec<String>,
    /// 複核狀態：unreviewed／accepted／disputed／superseded
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub review: String,
    /// 套用時的原始建議名稱（日後來源變動可比對）
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub suggest_raw: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Group {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub parent: Option<String>,
    #[serde(default)]
    pub color: String,
    /// 感測器類型：optical 光學／radar 雷達／sigint 電子偵察／other；空白＝沿用上層
    #[serde(default)]
    pub sensor: String,
    /// 預設偵照角度（離天底角，度）；None＝沿用上層
    #[serde(default)]
    pub look_deg: Option<f64>,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub members: Vec<u32>,
    #[serde(default)]
    pub by: String,
    #[serde(default)]
    pub at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditRec {
    pub at: String,
    pub by: String,
    pub action: String,
    pub detail: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Data {
    #[serde(default)]
    pub next_id: u64,
    #[serde(default)]
    pub names: BTreeMap<u32, NameRec>,
    #[serde(default)]
    pub groups: Vec<Group>,
    #[serde(default)]
    pub audit: Vec<AuditRec>,
    /// 已套用的預設群組版本（空白＝從未套用；套用過就不再自動建立，使用者刪光群組也不會重建）
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub preset: String,
}

/// PRC 衛星預設群組：由 prc_maneuver/build_prc_db.py 依 prc_groups.json 產生（與「PRC衛星基本資料」CHM／PDF 同一套分組）
pub const PRC_PRESET_JSON: &str = include_str!("../config/prc_default_groups.json");

#[derive(Deserialize)]
struct PresetFile {
    version: String,
    #[serde(default)]
    source: String,
    groups: Vec<PresetGroup>,
}
#[derive(Deserialize)]
struct PresetGroup {
    path: Vec<String>,
    #[serde(default)]
    color: String,
    #[serde(default)]
    sensor: String,
    #[serde(default)]
    note: String,
    #[serde(default)]
    members: Vec<u32>,
}

/// 套用預設群組：只新增群組與成員，不改動、不刪除既有群組；新建群組才寫入顏色／感測器／備註。
/// 回傳 (版本, 新建群組數, 新增成員數)
pub fn apply_preset(d: &mut Data, json_text: &str, by: &str) -> Result<(String, usize, usize), String> {
    let p: PresetFile = serde_json::from_str(json_text).map_err(|e| format!("預設群組檔格式錯誤：{e}"))?;
    let (mut created, mut added) = (0usize, 0usize);
    for g in &p.groups {
        let mut parent: Option<String> = None;
        for (i, name) in g.path.iter().enumerate() {
            check_name(name, "群組名稱")?;
            let found = d.groups.iter().find(|x| x.parent == parent && &x.name == name).map(|x| x.id.clone());
            let id = match found {
                Some(id) => id,
                None => {
                    let id = d.new_id();
                    let last = i + 1 == g.path.len();
                    d.groups.push(Group {
                        id: id.clone(),
                        name: name.clone(),
                        parent: parent.clone(),
                        color: if last { norm_color(&g.color) } else { String::new() },
                        sensor: if last && SENSORS.contains(&g.sensor.as_str()) { g.sensor.clone() } else { String::new() },
                        note: if last { g.note.clone() } else { String::new() },
                        by: by.into(),
                        at: now_iso(),
                        ..Default::default()
                    });
                    created += 1;
                    id
                }
            };
            parent = Some(id);
        }
        let gid = parent.ok_or("預設群組路徑空白")?;
        let grp = d.group_mut(&gid).unwrap();
        for &n in &g.members {
            if !grp.members.contains(&n) {
                grp.members.push(n);
                added += 1;
            }
        }
    }
    d.push_audit(by, "套用預設群組", &format!("{}（{}）：新建群組 {created} 個、加入成員 {added} 筆", p.source, p.version));
    Ok((p.version, created, added))
}

impl Data {
    fn group(&self, id: &str) -> Option<&Group> {
        self.groups.iter().find(|g| g.id == id)
    }
    fn group_mut(&mut self, id: &str) -> Option<&mut Group> {
        self.groups.iter_mut().find(|g| g.id == id)
    }
    fn children(&self, id: &str) -> Vec<&Group> {
        self.groups.iter().filter(|g| g.parent.as_deref() == Some(id)).collect()
    }
    /// 自身＋所有下層群組 id
    pub fn descendants(&self, id: &str) -> Vec<String> {
        let mut out = vec![id.to_string()];
        let mut i = 0;
        while i < out.len() {
            let cur = out[i].clone();
            out.extend(self.children(&cur).iter().map(|g| g.id.clone()));
            i += 1;
            if out.len() > 10_000 {
                break;
            }
        }
        out
    }
    /// 祖先鏈（含自身，由近到遠）
    fn ancestors(&self, id: &str) -> Vec<&Group> {
        let mut out = Vec::new();
        let mut cur = self.group(id);
        while let Some(g) = cur {
            if out.iter().any(|x: &&Group| x.id == g.id) || out.len() > 64 {
                break;
            }
            out.push(g);
            cur = g.parent.as_deref().and_then(|p| self.group(p));
        }
        out
    }
    pub fn path(&self, id: &str) -> String {
        let mut v: Vec<&str> = self.ancestors(id).iter().map(|g| g.name.as_str()).collect();
        v.reverse();
        v.join(" / ")
    }
    pub fn eff_sensor(&self, id: &str) -> String {
        self.ancestors(id).iter().find(|g| !g.sensor.is_empty()).map(|g| g.sensor.clone()).unwrap_or_default()
    }
    pub fn eff_look_deg(&self, id: &str) -> Option<f64> {
        self.ancestors(id).iter().find_map(|g| g.look_deg)
    }
    /// 群組（含下層）全部成員，去重
    pub fn all_members(&self, id: &str) -> Vec<u32> {
        let mut seen = HashSet::new();
        let mut out = Vec::new();
        for gid in self.descendants(id) {
            if let Some(g) = self.group(&gid) {
                for &n in &g.members {
                    if seen.insert(n) {
                        out.push(n);
                    }
                }
            }
        }
        out
    }
    fn groups_of(&self) -> HashMap<u32, Vec<String>> {
        let mut m: HashMap<u32, Vec<String>> = HashMap::new();
        for g in &self.groups {
            for &n in &g.members {
                m.entry(n).or_default().push(self.path(&g.id));
            }
        }
        m
    }
    fn new_id(&mut self) -> String {
        self.next_id += 1;
        format!("g{}", self.next_id)
    }
    /// 依路徑（「A / B / C」）找群組，沒有就建立；回傳 (id, 新建數)
    fn ensure_path(&mut self, path: &str, by: &str) -> Result<(String, usize), String> {
        let parts: Vec<String> = path
            .split(['/', '>', '／', '＞'])
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        if parts.is_empty() {
            return Err("群組路徑空白".into());
        }
        let mut parent: Option<String> = None;
        let mut created = 0;
        for p in parts {
            check_name(&p, "群組名稱")?;
            let found = self
                .groups
                .iter()
                .find(|g| g.parent == parent && g.name == p)
                .map(|g| g.id.clone());
            let id = match found {
                Some(id) => id,
                None => {
                    let id = self.new_id();
                    self.groups.push(Group {
                        id: id.clone(),
                        name: p,
                        parent: parent.clone(),
                        by: by.into(),
                        at: now_iso(),
                        ..Default::default()
                    });
                    created += 1;
                    id
                }
            };
            parent = Some(id);
        }
        Ok((parent.unwrap(), created))
    }
    fn push_audit(&mut self, by: &str, action: &str, detail: &str) {
        self.audit.push(AuditRec { at: now_iso(), by: by.into(), action: action.into(), detail: detail.into() });
        if self.audit.len() > AUDIT_MAX {
            let cut = self.audit.len() - AUDIT_MAX;
            self.audit.drain(..cut);
        }
    }
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn check_name(s: &str, what: &str) -> Result<(), String> {
    let n = s.chars().count();
    if n == 0 || n > 64 {
        return Err(format!("{what}需 1–64 字元"));
    }
    if s.chars().any(|c| c.is_control()) {
        return Err(format!("{what}不可含控制字元"));
    }
    Ok(())
}

fn norm_color(s: &str) -> String {
    let t = s.trim();
    let ok = t.len() == 7 && t.starts_with('#') && t[1..].chars().all(|c| c.is_ascii_hexdigit());
    if ok { t.to_uppercase() } else { String::new() }
}

pub fn data_file(cfg: &Config) -> PathBuf {
    cfg.home.join("user_private").join("sat_custom.json")
}

fn read_data(path: &std::path::Path) -> Option<Data> {
    let b = std::fs::read(path).ok()?;
    match serde_json::from_slice::<Data>(&b) {
        Ok(d) => Some(d),
        Err(e) => {
            tracing::error!("衛星管理資料檔格式錯誤（{}）：{e}", path.display());
            None
        }
    }
}

/// 索引建立時套用自訂名稱
pub fn apply_names(cfg: &Config, sats: &mut BTreeMap<u32, SatInfo>) {
    let Some(d) = read_data(&data_file(cfg)) else { return };
    let mut n = 0;
    for (nid, rec) in &d.names {
        if let Some(s) = sats.get_mut(nid) {
            s.name = rec.name.clone();
            n += 1;
        }
    }
    if n > 0 {
        tracing::info!("套用自訂衛星名稱 {n} 筆");
    }
}

pub struct Store {
    path: PathBuf,
    data: Mutex<Data>,
    /// 原始檔存在但解析失敗：拒絕寫入，避免覆蓋使用者資料
    broken: bool,
    rebuild_pending: AtomicBool,
}

impl Store {
    pub fn load(path: PathBuf) -> Self {
        let exists = path.exists();
        let d = read_data(&path);
        let broken = exists && d.is_none();
        let s = Self { path, data: Mutex::new(d.unwrap_or_default()), broken, rebuild_pending: AtomicBool::new(false) };
        s.seed_preset();
        s
    }

    /// 首次啟動（沒有任何群組、也從未套用過預設）時自動建立 PRC 預設群組
    fn seed_preset(&self) {
        if self.broken {
            return;
        }
        {
            let d = self.data.lock();
            if !d.groups.is_empty() || !d.preset.is_empty() {
                return;
            }
        }
        let r = self.edit(|d| {
            let (ver, c, a) = apply_preset(d, PRC_PRESET_JSON, "系統預設")?;
            d.preset = ver;
            Ok((c, a))
        });
        match r {
            Ok((c, a)) => tracing::info!("已建立 PRC 預設群組：{c} 個群組、{a} 個成員"),
            Err(e) => tracing::warn!("建立 PRC 預設群組失敗：{e}"),
        }
    }

    pub fn snapshot(&self) -> Data {
        self.data.lock().clone()
    }

    /// 在副本上修改 → 寫檔成功才替換
    pub fn edit<R>(&self, f: impl FnOnce(&mut Data) -> Result<R, String>) -> Result<R, String> {
        if self.broken {
            return Err(format!("資料檔 {} 格式錯誤，為避免覆蓋已停止寫入；請修復或改名後重新啟動", self.path.display()));
        }
        let mut g = self.data.lock();
        let mut next = g.clone();
        let r = f(&mut next)?;
        let bytes = serde_json::to_vec_pretty(&next).map_err(|e| e.to_string())?;
        atomic_write(&self.path, &bytes).map_err(|e| format!("寫入資料檔失敗：{e}"))?;
        *g = next;
        Ok(r)
    }

    pub fn audit(&self, by: &str, action: &str, detail: &str) {
        let _ = self.edit(|d| {
            d.push_audit(by, action, detail);
            Ok(())
        });
    }

    /// 更名後重建索引（合併 1 秒內的多次變更）
    pub fn schedule_rebuild(&self, st: Arc<AppState>) {
        if self.rebuild_pending.swap(true, Ordering::SeqCst) {
            return;
        }
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(1000));
            st.satadmin.rebuild_pending.store(false, Ordering::SeqCst);
            st.rebuild_index_now();
            st.result_cache.lock().clear();
        });
    }
}

// ── TLE 欄位小工具 ───────────────────────────────────────────────────────────

/// 國際編號：TLE 第 1 行 10–17 欄（98067A → 1998-067A）
pub fn intl_code(line1: &str) -> String {
    let raw = line1.get(9..17).unwrap_or("").trim();
    if raw.len() < 5 || !raw[..2].chars().all(|c| c.is_ascii_digit()) {
        return raw.to_string();
    }
    let yy: u32 = raw[..2].parse().unwrap_or(0);
    let year = if yy < 57 { 2000 + yy } else { 1900 + yy };
    format!("{year}-{}", &raw[2..])
}

/// TLE 曆元（UTC ISO）
pub fn tle_epoch(line1: &str) -> Option<chrono::DateTime<chrono::Utc>> {
    let s = line1.get(18..32)?.trim();
    let yy: i32 = s.get(..2)?.parse().ok()?;
    let doy: f64 = s.get(2..)?.parse().ok()?;
    let year = if yy < 57 { 2000 + yy } else { 1900 + yy };
    let base = chrono::NaiveDate::from_ymd_opt(year, 1, 1)?.and_hms_opt(0, 0, 0)?.and_utc();
    Some(base + chrono::Duration::milliseconds(((doy - 1.0) * 86_400_000.0).round() as i64))
}

fn sat_json(idx: &SatIndex, d: &Data, groups_of: &HashMap<u32, Vec<String>>, sc: &HashMap<u32, crate::ephemeris::SatcatRec>, nid: u32) -> Value {
    let rec = d.names.get(&nid);
    let s = idx.sats.get(&nid);
    let cur = s.map(|s| s.name.clone()).unwrap_or_default();
    let (_, stv) = crate::ephemeris::sat_status(sc, s.and_then(|s| tle_epoch(&s.line1)), nid, 30.0);
    let mut v = json!({
        "norad_id": nid,
        "name": rec.map(|r| r.name.clone()).unwrap_or(cur.clone()),
        "orig_name": rec.map(|r| if r.orig.is_empty() { cur.clone() } else { r.orig.clone() }).unwrap_or(cur),
        "custom": rec.is_some(),
        "note": rec.map(|r| r.note.clone()).unwrap_or_default(),
        "renamed_by": rec.map(|r| r.by.clone()),
        "renamed_at": rec.map(|r| r.at.clone()),
        "name_status": rec.map(|r| r.status.clone()).filter(|s| !s.is_empty()),
        "name_confidence": rec.map(|r| r.confidence.clone()).filter(|s| !s.is_empty()),
        "evidence": rec.map(|r| r.evidence.clone()).unwrap_or_default(),
        "in_catalog": s.is_some(),
        "intl_code": s.map(|s| intl_code(&s.line1)),
        "tle_epoch": s.and_then(|s| tle_epoch(&s.line1)).map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)),
        "country": s.map(|s| s.country.clone()),
        "purpose": s.map(|s| s.purpose.clone()),
        "constellation": s.and_then(|s| s.constellation.clone()),
        "groups": groups_of.get(&nid).cloned().unwrap_or_default(),
    });
    for k in ["status", "decay_date", "launch_date", "tle_age_days"] {
        v[k] = stv[k].clone();
    }
    v
}

/// 解析 NORAD 清單（逗號、空白、換行分隔）
pub fn parse_norads(s: &str) -> Vec<u32> {
    let mut seen = HashSet::new();
    s.split(|c: char| c == ',' || c == '，' || c == '、' || c.is_whitespace())
        .filter_map(|t| t.trim().parse::<u32>().ok())
        .filter(|n| *n > 0 && seen.insert(*n))
        .collect()
}

// ── API ──────────────────────────────────────────────────────────────────────

type St = State<Arc<AppState>>;
type Q = Query<HashMap<String, String>>;

fn json_err(status: StatusCode, msg: impl Into<String>) -> Response {
    (status, Json(json!({"error": msg.into()}))).into_response()
}
fn forbid_edit() -> Response {
    json_err(StatusCode::FORBIDDEN, "需要編輯者以上權限（輸入／新增／修改）")
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/satadmin", get(page))
        .route("/api/satadmin/lookup", get(api_lookup))
        .route("/api/satadmin/duplicates", get(api_duplicates))
        .route("/api/satadmin/names", get(api_names))
        .route("/api/satadmin/names/{nid}", put(api_rename).delete(api_unrename))
        .route("/api/satadmin/names_batch", post(api_rename_batch))
        .route("/api/satadmin/groups", get(api_groups).post(api_group_create))
        .route("/api/satadmin/groups/{id}", put(api_group_update).delete(api_group_delete))
        .route("/api/satadmin/groups/{id}/members", post(api_group_members))
        .route("/api/satadmin/export.csv", get(api_export))
        .route("/api/satadmin/import", post(api_import))
        .route("/api/satadmin/audit", get(api_audit))
}

async fn page() -> Html<String> {
    let raw = crate::assets::get("ext/satadmin.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

/// ?norad=1,2,3 精確查詢；?q=文字 名稱／原名／國際編號模糊查詢（最多 200 筆）
async fn api_lookup(State(st): St, Query(q): Q) -> Json<Value> {
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let gof = d.groups_of();
    let sc = crate::ephemeris::satcat(&st.cfg);
    let mut ids: Vec<u32> = q.get("norad").map(|s| parse_norads(s)).unwrap_or_default();
    let text = q.get("q").map(|s| s.trim().to_uppercase()).unwrap_or_default();
    let mut truncated = false;
    if ids.is_empty() && text.chars().count() >= 2 {
        let lim = 200;
        for s in idx.sats.values() {
            let orig = d.names.get(&s.norad_id).map(|r| r.orig.to_uppercase()).unwrap_or_default();
            if s.name.to_uppercase().contains(&text) || orig.contains(&text) || intl_code(&s.line1).contains(&text) {
                if ids.len() >= lim {
                    truncated = true;
                    break;
                }
                ids.push(s.norad_id);
            }
        }
    }
    ids.truncate(500);
    let rows: Vec<Value> = ids.iter().map(|&n| sat_json(&idx, &d, &gof, &sc, n)).collect();
    Json(json!({"results": rows, "count": rows.len(), "truncated": truncated}))
}

/// 重複名稱（如 OBJECT A、TBA - TO BE ASSIGNED）：同名 ≥ min 顆
async fn api_duplicates(State(st): St, Query(q): Q) -> Json<Value> {
    let idx = st.index();
    let min: usize = q.get("min").and_then(|s| s.parse().ok()).unwrap_or(2).max(2);
    let limit: usize = q.get("limit").and_then(|s| s.parse().ok()).unwrap_or(300).min(2000);
    let no_debris = q.get("no_debris").is_some_and(|v| v == "1");
    let mut m: HashMap<String, Vec<u32>> = HashMap::new();
    for s in idx.sats.values() {
        if no_debris && is_debris_name(&s.name) {
            continue;
        }
        m.entry(s.name.trim().to_string()).or_default().push(s.norad_id);
    }
    let mut v: Vec<(String, Vec<u32>)> = m.into_iter().filter(|(_, ids)| ids.len() >= min).collect();
    v.sort_by(|a, b| b.1.len().cmp(&a.1.len()).then_with(|| a.0.cmp(&b.0)));
    let total = v.len();
    v.truncate(limit);
    let rows: Vec<Value> = v
        .into_iter()
        .map(|(name, mut ids)| {
            ids.sort_unstable();
            json!({"name": name, "count": ids.len(), "norad_ids": ids})
        })
        .collect();
    Json(json!({"results": rows, "total_names": total}))
}

/// 碎片／火箭殘骸名稱（DEB、R/B、COOLANT、AKM、PKM 等）
pub fn is_debris_name(name: &str) -> bool {
    let up = name.to_uppercase();
    up.contains("R/B")
        || up.split(|c: char| !c.is_ascii_alphanumeric()).any(|w| matches!(w, "DEB" | "COOLANT" | "AKM" | "PKM" | "TANK" | "PLATFORM" | "SHROUD"))
}

async fn api_names(State(st): St) -> Json<Value> {
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let gof = d.groups_of();
    let sc = crate::ephemeris::satcat(&st.cfg);
    let rows: Vec<Value> = d.names.keys().map(|&n| sat_json(&idx, &d, &gof, &sc, n)).collect();
    Json(json!({"results": rows, "count": rows.len()}))
}

#[derive(Deserialize)]
struct RenameReq {
    name: String,
    #[serde(default)]
    note: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    confidence: String,
    #[serde(default)]
    evidence: Vec<String>,
    #[serde(default)]
    review: String,
    #[serde(default)]
    suggest_raw: String,
}

const STATUSES: [&str; 6] = ["", "manual", "official", "inferred", "group_inferred", "conflict"];
const REVIEWS: [&str; 5] = ["", "unreviewed", "accepted", "disputed", "superseded"];

/// 驗證並組成更名紀錄
fn make_rec(b: &RenameReq, orig: String, by: &str) -> Result<NameRec, String> {
    let name = b.name.trim().to_string();
    check_name(&name, "名稱")?;
    if !STATUSES.contains(&b.status.as_str()) || !REVIEWS.contains(&b.review.as_str()) || !["", "high", "medium", "low"].contains(&b.confidence.as_str()) {
        return Err("status／confidence／review 值不正確".into());
    }
    let evidence: Vec<String> = b.evidence.iter().map(|e| e.trim().to_string()).filter(|e| e.starts_with("http://") || e.starts_with("https://")).take(10).collect();
    Ok(NameRec {
        name,
        orig,
        note: b.note.trim().chars().take(500).collect(),
        by: by.into(),
        at: now_iso(),
        status: if b.status.is_empty() { "manual".into() } else { b.status.clone() },
        confidence: b.confidence.clone(),
        evidence,
        review: if b.review.is_empty() { "unreviewed".into() } else { b.review.clone() },
        suggest_raw: b.suggest_raw.chars().take(200).collect(),
    })
}

async fn api_rename(State(st): St, Extension(c): Extension<Caller>, Path(nid): Path<u32>, Json(b): Json<RenameReq>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    let idx = st.index();
    let cur = idx.sats.get(&nid).map(|s| s.name.clone());
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        let orig = match d.names.get(&nid) {
            Some(r) if !r.orig.is_empty() => r.orig.clone(),
            _ => cur.clone().unwrap_or_default(),
        };
        let prev = d.names.get(&nid).map(|r| r.name.clone()).unwrap_or(orig.clone());
        let rec = make_rec(&b, orig, &by)?;
        d.push_audit(&by, "更名", &format!("NORAD {nid}：{prev} → {}（{}）", rec.name, rec.status));
        d.names.insert(nid, rec);
        Ok(())
    });
    match res {
        Ok(()) => {
            st.satadmin.schedule_rebuild(st.clone());
            Json(json!({"ok": true, "in_catalog": cur.is_some()})).into_response()
        }
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

#[derive(Deserialize)]
struct BatchItem {
    norad: u32,
    #[serde(flatten)]
    req: RenameReq,
}

/// 批次更名（建議名稱「套用勾選」）：一次寫檔、一筆操作紀錄
async fn api_rename_batch(State(st): St, Extension(c): Extension<Caller>, Json(items): Json<Vec<BatchItem>>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    if items.is_empty() || items.len() > 3000 {
        return json_err(StatusCode::BAD_REQUEST, "一次 1–3000 筆");
    }
    let idx = st.index();
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        let mut errs = Vec::new();
        let mut n = 0;
        let mut stat: HashMap<String, usize> = HashMap::new();
        for it in &items {
            let orig = match d.names.get(&it.norad) {
                Some(r) if !r.orig.is_empty() => r.orig.clone(),
                _ => idx.sats.get(&it.norad).map(|s| s.name.clone()).unwrap_or_default(),
            };
            match make_rec(&it.req, orig, &by) {
                Ok(rec) => {
                    *stat.entry(rec.status.clone()).or_default() += 1;
                    d.names.insert(it.norad, rec);
                    n += 1;
                }
                Err(e) => errs.push(format!("NORAD {}：{e}", it.norad)),
            }
        }
        let mut s: Vec<String> = stat.iter().map(|(k, v)| format!("{k} {v}")).collect();
        s.sort();
        d.push_audit(&by, "批次更名（建議名稱）", &format!("{n} 筆（{}）：{}", s.join("、"), short_list(&items.iter().map(|i| i.norad).collect::<Vec<_>>())));
        errs.truncate(50);
        Ok(json!({"ok": true, "applied": n, "errors": errs}))
    });
    match res {
        Ok(v) => {
            st.satadmin.schedule_rebuild(st.clone());
            Json(v).into_response()
        }
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_unrename(State(st): St, Extension(c): Extension<Caller>, Path(nid): Path<u32>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        let r = d.names.remove(&nid).ok_or_else(|| format!("NORAD {nid} 沒有自訂名稱"))?;
        d.push_audit(&by, "還原名稱", &format!("NORAD {nid}：{} → {}", r.name, r.orig));
        Ok(())
    });
    match res {
        Ok(()) => {
            st.satadmin.schedule_rebuild(st.clone());
            Json(json!({"ok": true})).into_response()
        }
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_groups(State(st): St, Query(q): Q) -> Json<Value> {
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let gof = d.groups_of();
    let sc = crate::ephemeris::satcat(&st.cfg);
    let with_members = q.get("members").map(|s| s != "0").unwrap_or(true);
    let rows: Vec<Value> = d
        .groups
        .iter()
        .map(|g| {
            let mut v = json!({
                "id": g.id, "name": g.name, "parent": g.parent, "path": d.path(&g.id),
                "color": g.color, "sensor": g.sensor, "look_deg": g.look_deg, "note": g.note,
                "eff_sensor": d.eff_sensor(&g.id), "eff_look_deg": d.eff_look_deg(&g.id),
                "count": g.members.len(), "count_total": d.all_members(&g.id).len(),
                "by": g.by, "at": g.at,
            });
            if with_members {
                v["members"] = Value::Array(g.members.iter().map(|&n| sat_json(&idx, &d, &gof, &sc, n)).collect());
            }
            v
        })
        .collect();
    Json(json!({"groups": rows, "sensors": SENSORS}))
}

#[derive(Deserialize)]
struct GroupReq {
    name: Option<String>,
    #[serde(default, with = "double_option")]
    parent: Option<Option<String>>,
    color: Option<String>,
    sensor: Option<String>,
    #[serde(default, with = "double_option")]
    look_deg: Option<Option<f64>>,
    note: Option<String>,
}

/// 區分「沒給」與「給 null」
mod double_option {
    use serde::{Deserialize, Deserializer};
    pub fn deserialize<'de, T: Deserialize<'de>, D: Deserializer<'de>>(d: D) -> Result<Option<Option<T>>, D::Error> {
        Option::<T>::deserialize(d).map(Some)
    }
}

fn check_group_fields(b: &GroupReq) -> Result<(), String> {
    if let Some(n) = &b.name {
        check_name(n.trim(), "群組名稱")?;
    }
    if let Some(s) = &b.sensor {
        if !SENSORS.contains(&s.as_str()) {
            return Err("感測器類型需為 optical／radar／sigint／other 或空白".into());
        }
    }
    if let Some(Some(x)) = b.look_deg {
        if !(x > 0.0 && x <= 70.0) {
            return Err("偵照角度需介於 0–70 度".into());
        }
    }
    Ok(())
}

async fn api_group_create(State(st): St, Extension(c): Extension<Caller>, Json(b): Json<GroupReq>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    if b.name.is_none() {
        return json_err(StatusCode::BAD_REQUEST, "需要群組名稱");
    }
    if let Err(e) = check_group_fields(&b) {
        return json_err(StatusCode::BAD_REQUEST, e);
    }
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        let name = b.name.clone().unwrap().trim().to_string();
        let parent = b.parent.clone().flatten().filter(|p| !p.is_empty());
        if let Some(p) = &parent {
            if d.group(p).is_none() {
                return Err(format!("找不到上層群組 {p}"));
            }
        }
        if d.groups.iter().any(|g| g.parent == parent && g.name == name) {
            return Err(format!("同一層已有群組「{name}」"));
        }
        let id = d.new_id();
        d.groups.push(Group {
            id: id.clone(),
            name,
            parent,
            color: norm_color(b.color.as_deref().unwrap_or("")),
            sensor: b.sensor.clone().unwrap_or_default(),
            look_deg: b.look_deg.flatten(),
            note: b.note.clone().unwrap_or_default().trim().into(),
            members: Vec::new(),
            by: by.clone(),
            at: now_iso(),
        });
        let path = d.path(&id);
        d.push_audit(&by, "新增群組", &path);
        Ok(id)
    });
    match res {
        Ok(id) => Json(json!({"ok": true, "id": id})).into_response(),
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_group_update(State(st): St, Extension(c): Extension<Caller>, Path(id): Path<String>, Json(b): Json<GroupReq>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    if let Err(e) = check_group_fields(&b) {
        return json_err(StatusCode::BAD_REQUEST, e);
    }
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        if d.group(&id).is_none() {
            return Err(format!("找不到群組 {id}"));
        }
        let before = d.path(&id);
        if let Some(p) = b.parent.clone() {
            let p = p.filter(|s| !s.is_empty());
            if let Some(pid) = &p {
                if d.group(pid).is_none() {
                    return Err(format!("找不到上層群組 {pid}"));
                }
                if d.descendants(&id).contains(pid) {
                    return Err("不能移到自己或自己的下層群組底下".into());
                }
            }
            d.group_mut(&id).unwrap().parent = p;
        }
        let g = d.group_mut(&id).unwrap();
        if let Some(n) = &b.name {
            g.name = n.trim().into();
        }
        if let Some(cl) = &b.color {
            g.color = norm_color(cl);
        }
        if let Some(s) = &b.sensor {
            g.sensor = s.clone();
        }
        if let Some(l) = b.look_deg {
            g.look_deg = l;
        }
        if let Some(n) = &b.note {
            g.note = n.trim().into();
        }
        g.by = by.clone();
        g.at = now_iso();
        let (name, parent) = (g.name.clone(), g.parent.clone());
        if d.groups.iter().filter(|x| x.parent == parent && x.name == name).count() > 1 {
            return Err(format!("同一層已有群組「{name}」"));
        }
        let after = d.path(&id);
        d.push_audit(&by, "修改群組", &if before == after { after } else { format!("{before} → {after}") });
        Ok(())
    });
    match res {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_group_delete(State(st): St, Extension(c): Extension<Caller>, Path(id): Path<String>, Query(q): Q) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    let cascade = q.get("cascade").is_some_and(|v| v == "1");
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        if d.group(&id).is_none() {
            return Err(format!("找不到群組 {id}"));
        }
        let ids = d.descendants(&id);
        if ids.len() > 1 && !cascade {
            return Err(format!("此群組底下還有 {} 個子群組；請先刪除子群組，或勾選「連同子群組刪除」", ids.len() - 1));
        }
        let path = d.path(&id);
        let n = d.all_members(&id).len();
        d.groups.retain(|g| !ids.contains(&g.id));
        d.push_audit(&by, "刪除群組", &format!("{path}（{} 個群組、{n} 顆衛星）", ids.len()));
        Ok(())
    });
    match res {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

#[derive(Deserialize)]
struct MembersReq {
    #[serde(default)]
    add: Vec<u32>,
    #[serde(default)]
    remove: Vec<u32>,
}

async fn api_group_members(State(st): St, Extension(c): Extension<Caller>, Path(id): Path<String>, Json(b): Json<MembersReq>) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    if b.add.len() + b.remove.len() > 20_000 {
        return json_err(StatusCode::BAD_REQUEST, "一次最多 20,000 筆");
    }
    let idx = st.index();
    let by = c.name();
    let res = st.satadmin.edit(|d| {
        let path = d.path(&id);
        let g = d.group_mut(&id).ok_or_else(|| format!("找不到群組 {id}"))?;
        let mut have: HashSet<u32> = g.members.iter().copied().collect();
        let mut added = Vec::new();
        for &n in &b.add {
            if n > 0 && have.insert(n) {
                g.members.push(n);
                added.push(n);
            }
        }
        let rm: HashSet<u32> = b.remove.iter().copied().collect();
        let before = g.members.len();
        g.members.retain(|n| !rm.contains(n));
        let removed = before - g.members.len();
        g.at = now_iso();
        g.by = by.clone();
        let missing: Vec<u32> = added.iter().copied().filter(|n| !idx.sats.contains_key(n)).collect();
        let mut parts = Vec::new();
        if !added.is_empty() {
            parts.push(format!("加入 {} 顆（{}）", added.len(), short_list(&added)));
        }
        if removed > 0 {
            parts.push(format!("移除 {removed} 顆（{}）", short_list(&b.remove)));
        }
        if !parts.is_empty() {
            d.push_audit(&by, "群組成員", &format!("{path}：{}", parts.join("；")));
        }
        Ok(json!({"ok": true, "added": added.len(), "removed": removed, "not_in_catalog": missing}))
    });
    match res {
        Ok(v) => Json(v).into_response(),
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

fn short_list(v: &[u32]) -> String {
    let s: Vec<String> = v.iter().take(8).map(|n| n.to_string()).collect();
    if v.len() > 8 { format!("{}…", s.join(",")) } else { s.join(",") }
}

fn csv_field(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

/// 匯出：自訂名稱與群組成員（UTF-8 BOM，Excel 可直接開）
async fn api_export(State(st): St) -> Response {
    let idx = st.index();
    let d = st.satadmin.snapshot();
    let mut out = String::from("\u{FEFF}norad_id,name,orig_name,group,note,in_catalog\n");
    let mut rows: Vec<(u32, String)> = Vec::new();
    for g in &d.groups {
        for &n in &g.members {
            rows.push((n, d.path(&g.id)));
        }
    }
    let grouped: HashSet<u32> = rows.iter().map(|r| r.0).collect();
    for &n in d.names.keys() {
        if !grouped.contains(&n) {
            rows.push((n, String::new()));
        }
    }
    rows.sort();
    for (n, gp) in rows {
        let rec = d.names.get(&n);
        let cur = idx.sats.get(&n).map(|s| s.name.as_str()).unwrap_or("");
        let name = rec.map(|r| r.name.as_str()).unwrap_or("");
        let orig = rec.map(|r| r.orig.as_str()).filter(|s| !s.is_empty()).unwrap_or(cur);
        let note = rec.map(|r| r.note.as_str()).unwrap_or("");
        out.push_str(&format!(
            "{n},{},{},{},{},{}\n",
            csv_field(name),
            csv_field(orig),
            csv_field(&gp),
            csv_field(note),
            if idx.sats.contains_key(&n) { 1 } else { 0 }
        ));
    }
    let mut r = Response::new(axum::body::Body::from(out));
    let h = r.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/csv; charset=utf-8"));
    let fname = format!("sat_custom_{}.csv", chrono::Local::now().format("%Y%m%d_%H%M"));
    h.insert(header::CONTENT_DISPOSITION, HeaderValue::from_str(&format!("attachment; filename=\"{fname}\"")).unwrap());
    r
}

/// 匯入 CSV：欄位 norad_id,name,group,note（有標題列時依欄名；group 以「/」分層，沒有的群組自動建立）
pub fn import_csv(d: &mut Data, text: &str, by: &str, cur_names: &HashMap<u32, String>) -> Result<Value, String> {
    let text = text.trim_start_matches('\u{FEFF}');
    let mut rdr = csv::ReaderBuilder::new().has_headers(false).flexible(true).from_reader(text.as_bytes());
    let mut recs: Vec<Vec<String>> = Vec::new();
    for r in rdr.records() {
        let r = r.map_err(|e| format!("CSV 解析失敗：{e}"))?;
        recs.push(r.iter().map(|s| s.trim().to_string()).collect());
    }
    if recs.is_empty() {
        return Err("CSV 是空的".into());
    }
    let (mut ci, mut cn, mut cg, mut cnote) = (Some(0usize), Some(1usize), Some(2usize), Some(3usize));
    let first_is_header = recs[0].first().map_or(false, |c| c.parse::<u32>().is_err());
    if first_is_header {
        let find = |keys: &[&str]| recs[0].iter().position(|h| keys.iter().any(|k| h.eq_ignore_ascii_case(k)));
        ci = find(&["norad_id", "norad", "norad id", "catnr", "NORAD 編號", "編號"]);
        cn = find(&["name", "new_name", "名稱", "新名稱", "自訂名稱"]);
        cg = find(&["group", "群組", "分類"]);
        cnote = find(&["note", "notes", "備註"]);
        if ci.is_none() {
            return Err("標題列找不到 norad_id 欄".into());
        }
        recs.remove(0);
    }
    let get = |r: &Vec<String>, c: Option<usize>| c.and_then(|i| r.get(i)).cloned().unwrap_or_default();
    let (mut renamed, mut grouped, mut created) = (0, 0, 0);
    let mut errors: Vec<String> = Vec::new();
    for (i, r) in recs.iter().enumerate() {
        let line = i + if first_is_header { 2 } else { 1 };
        let Ok(nid) = get(r, ci).parse::<u32>() else {
            if r.iter().any(|c| !c.is_empty()) {
                errors.push(format!("第 {line} 行：NORAD 編號無效"));
            }
            continue;
        };
        let name = get(r, cn);
        let note = get(r, cnote);
        if !name.is_empty() {
            if let Err(e) = check_name(&name, "名稱") {
                errors.push(format!("第 {line} 行：{e}"));
            } else {
                let orig = match d.names.get(&nid) {
                    Some(x) if !x.orig.is_empty() => x.orig.clone(),
                    _ => cur_names.get(&nid).cloned().unwrap_or_default(),
                };
                let changed = d.names.get(&nid).map_or(true, |x| x.name != name || x.note != note);
                if changed {
                    d.names.insert(nid, NameRec { name: name.clone(), orig, note: note.clone(), by: by.into(), at: now_iso(), status: "manual".into(), review: "unreviewed".into(), ..Default::default() });
                    renamed += 1;
                }
            }
        }
        let gp = get(r, cg);
        if !gp.is_empty() {
            match d.ensure_path(&gp, by) {
                Ok((gid, c)) => {
                    created += c;
                    let g = d.group_mut(&gid).unwrap();
                    if !g.members.contains(&nid) {
                        g.members.push(nid);
                        grouped += 1;
                    }
                }
                Err(e) => errors.push(format!("第 {line} 行：{e}")),
            }
        }
    }
    d.push_audit(by, "CSV 匯入", &format!("更名 {renamed} 筆、加入群組 {grouped} 筆、新建群組 {created} 個、錯誤 {} 筆", errors.len()));
    errors.truncate(100);
    Ok(json!({"ok": true, "renamed": renamed, "grouped": grouped, "created_groups": created, "errors": errors}))
}

async fn api_import(State(st): St, Extension(c): Extension<Caller>, body: Bytes) -> Response {
    if !c.can_edit() {
        return forbid_edit();
    }
    if body.len() > 8 << 20 {
        return json_err(StatusCode::PAYLOAD_TOO_LARGE, "CSV 檔超過 8 MB");
    }
    let text = match String::from_utf8(body.to_vec()) {
        Ok(t) => t,
        Err(_) => return json_err(StatusCode::BAD_REQUEST, "CSV 需為 UTF-8 編碼（Excel 請另存為「CSV UTF-8」）"),
    };
    let idx = st.index();
    let cur: HashMap<u32, String> = idx.sats.iter().map(|(k, s)| (*k, s.name.clone())).collect();
    let by = c.name();
    match st.satadmin.edit(|d| import_csv(d, &text, &by, &cur)) {
        Ok(v) => {
            if v["renamed"].as_u64().unwrap_or(0) > 0 {
                st.satadmin.schedule_rebuild(st.clone());
            }
            Json(v).into_response()
        }
        Err(e) => json_err(StatusCode::BAD_REQUEST, e),
    }
}

async fn api_audit(State(st): St, Query(q): Q) -> Json<Value> {
    let limit: usize = q.get("limit").and_then(|s| s.parse().ok()).unwrap_or(300).min(AUDIT_MAX);
    let d = st.satadmin.snapshot();
    let rows: Vec<&AuditRec> = d.audit.iter().rev().take(limit).collect();
    Json(json!({"results": rows, "total": d.audit.len()}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tle_fields() {
        let l1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005";
        assert_eq!(intl_code(l1), "1998-067A");
        let t = tle_epoch(l1).unwrap();
        assert_eq!(t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true), "2024-01-01T12:00:00Z");
        assert!(is_debris_name("FENGYUN 1C DEB") && is_debris_name("CZ-4C R/B") && !is_debris_name("OBJECT A") && !is_debris_name("DEBUT"));
        assert_eq!(parse_norads("25544, 48274，25544\n 0 abc 57320"), vec![25544, 48274, 57320]);
    }

    #[test]
    fn groups_tree_and_import() {
        let mut d = Data::default();
        let (root, c) = d.ensure_path("PRC偵察衛星", "t").unwrap();
        assert_eq!(c, 1);
        d.group_mut(&root).unwrap().sensor = "optical".into();
        d.group_mut(&root).unwrap().look_deg = Some(30.0);
        let (radar, c) = d.ensure_path("PRC偵察衛星 / 雷達", "t").unwrap();
        assert_eq!(c, 1, "上層已存在只建子群組");
        d.group_mut(&radar).unwrap().sensor = "radar".into();
        assert_eq!(d.path(&radar), "PRC偵察衛星 / 雷達");
        assert_eq!(d.eff_sensor(&radar), "radar");
        assert_eq!(d.eff_look_deg(&radar), Some(30.0), "偵照角度沿用上層");
        let cur: HashMap<u32, String> = [(40001u32, "OBJECT A".to_string())].into_iter().collect();
        let csv = "\u{FEFF}norad_id,名稱,群組,備註\n40001,遙感-30A,PRC偵察衛星/光學,測試\n40002,,PRC偵察衛星/雷達,\nabc,x,y,z\n";
        let v = import_csv(&mut d, csv, "ed", &cur).unwrap();
        assert_eq!(v["renamed"], 1);
        assert_eq!(v["grouped"], 2);
        assert_eq!(v["created_groups"], 1, "只新建「光學」");
        assert_eq!(v["errors"].as_array().unwrap().len(), 1);
        assert_eq!(d.names[&40001].orig, "OBJECT A");
        assert_eq!(d.names[&40001].name, "遙感-30A");
        let mut all = d.all_members(&root);
        all.sort();
        assert_eq!(all, vec![40001, 40002], "上層群組含子群組成員");
        assert_eq!(d.descendants(&root).len(), 3);
        // 無標題列
        let v = import_csv(&mut d, "40003,新名字\n", "ed", &cur).unwrap();
        assert_eq!(v["renamed"], 1);
        assert!(d.audit.len() >= 2);
    }

    #[test]
    fn store_roundtrip_and_broken_file() {
        let dir = std::env::temp_dir().join(format!("sd_satadmin_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let p = dir.join("sat_custom.json");
        let s = Store::load(p.clone());
        s.edit(|d| {
            d.names.insert(1, NameRec { name: "A".into(), ..Default::default() });
            Ok(())
        })
        .unwrap();
        let s2 = Store::load(p.clone());
        assert_eq!(s2.snapshot().names[&1].name, "A");
        // 編輯失敗不寫入
        assert!(s2.edit(|_d| -> Result<(), String> { Err("x".into()) }).is_err());
        std::fs::write(&p, b"{broken").unwrap();
        let s3 = Store::load(p.clone());
        assert!(s3.edit(|_| Ok(())).is_err(), "壞檔拒絕覆寫");
        assert_eq!(std::fs::read(&p).unwrap(), b"{broken");
    }

    #[test]
    fn prc_preset_seed() {
        // 內嵌預設群組可解析、可重複套用（第二次不新增）
        let mut d = Data::default();
        let (ver, c, a) = apply_preset(&mut d, PRC_PRESET_JSON, "t").unwrap();
        assert!(!ver.is_empty() && c > 10 && a > 1000, "群組 {c}、成員 {a}");
        let (_, c2, a2) = apply_preset(&mut d, PRC_PRESET_JSON, "t").unwrap();
        assert_eq!((c2, a2), (0, 0));
        let root = d.groups.iter().find(|g| g.parent.is_none()).unwrap().id.clone();
        assert_eq!(d.all_members(&root).len(), a, "成員不重複");
        assert!(d.groups.iter().all(|g| !g.name.contains(['/', '>', '／', '＞'])), "群組名稱不可含分層符號");
        // 首次啟動自動建立；使用者刪光群組後不重建；已有自訂群組的舊資料檔不套用
        let dir = std::env::temp_dir().join(format!("satadmin_preset_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let p = dir.join("sat_custom.json");
        let s = Store::load(p.clone());
        assert_eq!(s.snapshot().preset, ver);
        assert!(!s.snapshot().groups.is_empty());
        s.edit(|d| { d.groups.clear(); Ok(()) }).unwrap();
        assert!(Store::load(p.clone()).snapshot().groups.is_empty());
        let mut old = Data::default();
        old.ensure_path("我的群組", "u").unwrap();
        std::fs::write(&p, serde_json::to_vec(&old).unwrap()).unwrap();
        let s3 = Store::load(p.clone());
        assert_eq!(s3.snapshot().groups.len(), 1);
        assert!(s3.snapshot().preset.is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
