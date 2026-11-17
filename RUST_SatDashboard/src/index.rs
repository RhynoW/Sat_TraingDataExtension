//! 衛星索引：DuckDB 最新 TLE + sat_metadata.csv 覆寫 + 使用者自訂資料。
//! 對應 Python ingestion/db.py、index.py。

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use duckdb::{AccessMode, Config as DuckConfig, Connection};
use rayon::prelude::*;
use serde_json::{json, Value};

use crate::classify::{self, Rules, ERA_ORDER};
use crate::config::{Config, META_TABLE, RAW_TABLE};
use crate::physics::Propagator;
use crate::userdata;

pub struct SatInfo {
    pub norad_id: u32,
    pub name: String,
    pub line1: String,
    pub line2: String,
    pub country: String,
    pub purpose: String,
    pub era: String,
    pub constellation: Option<String>,
    pub name_zh: String,
    pub operator: String,
    pub notes: String,
    pub user_defined: bool,
    pub prop: Option<Propagator>,
}

impl SatInfo {
    pub fn constellation_or_dash(&self) -> &str {
        self.constellation.as_deref().unwrap_or("—")
    }
    pub fn field(&self, ftype: &str) -> Option<&str> {
        match ftype {
            "country" => Some(&self.country),
            "purpose" => Some(&self.purpose),
            "era" => Some(&self.era),
            "constellation" => self.constellation.as_deref(),
            _ => None,
        }
    }
}

pub struct SatIndex {
    /// 依 NORAD 排序（BTreeMap），迭代順序固定
    pub sats: BTreeMap<u32, SatInfo>,
    pub built_at: DateTime<Utc>,
}

impl SatIndex {
    pub fn empty() -> Self {
        Self {
            sats: BTreeMap::new(),
            built_at: Utc::now(),
        }
    }
}

pub fn open_ro(db: &Path) -> anyhow::Result<Connection> {
    let cfg = DuckConfig::default().access_mode(AccessMode::ReadOnly)?;
    Ok(Connection::open_with_flags(db, cfg)?)
}

fn table_columns(con: &Connection, table: &str) -> anyhow::Result<Vec<String>> {
    let mut st = con.prepare(&format!("DESCRIBE {table}"))?;
    let cols = st
        .query_map([], |r| r.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(cols)
}

fn table_exists(con: &Connection, table: &str) -> bool {
    con.query_row(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [table],
        |r| r.get::<_, i64>(0),
    )
    .map(|n| n > 0)
    .unwrap_or(false)
}

struct Row {
    norad_id: u32,
    name: String,
    line1: Option<String>,
    line2: Option<String>,
    source_code: Option<String>,
    launch_date: Option<String>,
    intl_code: Option<String>,
}

/// 動態偵測欄位，生成相容 slim/full DB 的「每顆最新一筆 TLE」查詢
fn query_latest_tles(db: &Path, extra_where: Option<&str>) -> anyhow::Result<Vec<Row>> {
    let con = open_ro(db)?;
    let raw_cols = table_columns(&con, RAW_TABLE)?;
    let has = |c: &str| raw_cols.iter().any(|x| x == c);
    let has_lines = has("line1") && has("line2");
    if !has_lines {
        anyhow::bail!("{RAW_TABLE} 無 line1/line2 欄位，Rust 版目前僅支援含 TLE 兩行之 DB");
    }
    let obj_expr = if has("object_name") {
        "COALESCE(r.object_name, 'NORAD-' || CAST(r.norad_id AS VARCHAR))"
    } else {
        "'NORAD-' || CAST(r.norad_id AS VARCHAR)"
    };

    let (join, meta_sel) = if table_exists(&con, META_TABLE) {
        let mc = table_columns(&con, META_TABLE)?;
        let pick = |c: &str, cast: bool| {
            if mc.iter().any(|x| x == c) {
                if cast {
                    format!("CAST(m.{c} AS VARCHAR)")
                } else {
                    format!("m.{c}")
                }
            } else {
                "NULL".to_string()
            }
        };
        (
            format!("LEFT JOIN {META_TABLE} m ON r.norad_id = m.norad_id"),
            format!(
                "{}, {}, {}",
                pick("source_code", false),
                pick("launch_date", true),
                pick("intl_code", false)
            ),
        )
    } else {
        (String::new(), "NULL, NULL, NULL".to_string())
    };

    let extra = extra_where.map(|w| format!(" AND {w}")).unwrap_or_default();
    let sql = format!(
        "SELECT r.norad_id, {obj_expr} AS object_name, r.line1, r.line2, {meta_sel}
         FROM {RAW_TABLE} r {join}
         WHERE r.line1 IS NOT NULL AND r.line2 IS NOT NULL{extra}
         QUALIFY ROW_NUMBER() OVER (PARTITION BY r.norad_id ORDER BY r.epoch_utc DESC) = 1"
    );
    let mut st = con.prepare(&sql)?;
    let rows = st
        .query_map([], |r| {
            Ok(Row {
                norad_id: r.get::<_, i64>(0)? as u32,
                name: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                line1: r.get(2)?,
                line2: r.get(3)?,
                source_code: r.get(4)?,
                launch_date: r.get(5)?,
                intl_code: r.get(6)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// sat_metadata.csv：{norad_id: {欄位: 值}}
fn load_meta_csv(p: &Path) -> HashMap<u32, HashMap<String, String>> {
    let mut out = HashMap::new();
    let Ok(text) = std::fs::read_to_string(p) else {
        return out;
    };
    let text = text.trim_start_matches('\u{feff}');
    let mut rdr = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(text.as_bytes());
    let Ok(headers) = rdr.headers().cloned() else {
        return out;
    };
    for rec in rdr.records().flatten() {
        let mut m = HashMap::new();
        let mut nid = None;
        for (h, v) in headers.iter().zip(rec.iter()) {
            if h == "norad_id" {
                nid = v.trim().parse::<u32>().ok();
            } else {
                m.insert(h.to_string(), v.trim().to_string());
            }
        }
        if let Some(n) = nid {
            out.insert(n, m);
        }
    }
    tracing::info!("sat_metadata.csv：{} 筆", out.len());
    out
}

fn nonempty(m: &HashMap<String, String>, k: &str) -> Option<String> {
    m.get(k).filter(|v| !v.is_empty()).cloned()
}

fn tle_epoch_key(line1: &str) -> Option<f64> {
    let yy: i32 = line1.get(18..20)?.trim().parse().ok()?;
    let doy: f64 = line1.get(20..32)?.trim().parse().ok()?;
    Some((if yy < 57 { 2000 + yy } else { 1900 + yy }) as f64 * 1000.0 + doy)
}

fn rows_to_sats(cfg: &Config, rules: &Rules, rows: Vec<Row>) -> BTreeMap<u32, SatInfo> {
    let mut sats: BTreeMap<u32, SatInfo> = BTreeMap::new();
    let meta = load_meta_csv(&cfg.sat_meta_csv());
    for r in rows {
        let raw = r.name.trim().trim_start_matches(['0', ' ']).to_string();
        let name = if raw.is_empty() {
            format!("OBJECT {}", r.norad_id)
        } else {
            raw
        };
        let empty = HashMap::new();
        let ov = meta.get(&r.norad_id).unwrap_or(&empty);
        let final_name = nonempty(ov, "name_en").unwrap_or(name);
        let src = nonempty(ov, "source_code").or(r.source_code);
        let intl = nonempty(ov, "intl_code").or(r.intl_code);
        let launch = nonempty(ov, "launch_date")
            .and_then(|s| classify::parse_date(&s))
            .or_else(|| r.launch_date.as_deref().and_then(classify::parse_date));
        sats.insert(
            r.norad_id,
            SatInfo {
                norad_id: r.norad_id,
                country: rules.classify_country(src.as_deref()),
                purpose: nonempty(ov, "purpose").unwrap_or_else(|| classify::classify_purpose(&final_name)),
                era: classify::classify_era(launch, intl.as_deref()),
                constellation: nonempty(ov, "constellation")
                    .or_else(|| rules.classify_constellation(&final_name)),
                name: final_name,
                line1: r.line1.unwrap_or_default().trim().to_string(),
                line2: r.line2.unwrap_or_default().trim().to_string(),
                name_zh: String::new(),
                operator: String::new(),
                notes: String::new(),
                user_defined: false,
                prop: None,
            },
        );
    }
    sats
}

fn init_props(sats: &mut BTreeMap<u32, SatInfo>) {
    sats.par_iter_mut().for_each(|(_, s)| {
        s.prop = Propagator::from_tle(&s.line1, &s.line2);
    });
}

/// 指定時刻之歷史索引：每顆取 epoch ≤ ts 之最新 TLE（不併入使用者自訂資料，同 Python 版）
pub fn build_index_at(cfg: &Config, rules: &Rules, ts: DateTime<Utc>) -> anyhow::Result<SatIndex> {
    let db = cfg.resolve_db().ok_or_else(|| anyhow::anyhow!("找不到資料庫"))?;
    let w = format!("r.epoch_utc <= TIMESTAMP '{}'", ts.format("%Y-%m-%d %H:%M:%S"));
    let rows = query_latest_tles(&db, Some(&w))?;
    if rows.is_empty() {
        anyhow::bail!("歷史 TLE 查詢無結果（{ts}）");
    }
    let mut sats = rows_to_sats(cfg, rules, rows);
    init_props(&mut sats);
    tracing::info!("歷史 TLE 索引完成：{} 筆（{ts}）", sats.len());
    Ok(SatIndex {
        sats,
        built_at: Utc::now(),
    })
}

pub fn build_index(cfg: &Config, rules: &Rules) -> SatIndex {
    let t0 = std::time::Instant::now();
    let mut sats: BTreeMap<u32, SatInfo> = BTreeMap::new();

    if let Some(db) = cfg.resolve_db() {
        tracing::info!("建立衛星索引中…（DB：{}）", db.display());
        match query_latest_tles(&db, None) {
            Ok(rows) => sats = rows_to_sats(cfg, rules, rows),
            Err(e) => tracing::error!("建立索引失敗：{e:#}"),
        }
    } else {
        tracing::info!("尚未有衛星資料庫（資料目錄：{}）；目前只有使用者自訂 TLE", cfg.home.display());
    }

    merge_user_defined(cfg, rules, &mut sats);

    // 平行初始化 SGP4 傳播器（3 萬顆約數十毫秒）
    init_props(&mut sats);
    let bad = sats.values().filter(|s| s.prop.is_none()).count();
    tracing::info!(
        "衛星索引完成：{} 筆（TLE 無法解析 {} 筆），耗時 {:.2} s",
        sats.len(),
        bad,
        t0.elapsed().as_secs_f64()
    );
    SatIndex {
        sats,
        built_at: Utc::now(),
    }
}

fn merge_user_defined(cfg: &Config, rules: &Rules, sats: &mut BTreeMap<u32, SatInfo>) {
    for (nid, tle) in userdata::load_user_tles(&cfg.user_tle_dir()) {
        match sats.get_mut(&nid) {
            None => {
                let name = if tle.name.is_empty() {
                    format!("USER-{nid}")
                } else {
                    tle.name.clone()
                };
                sats.insert(
                    nid,
                    SatInfo {
                        norad_id: nid,
                        purpose: classify::classify_purpose(&name),
                        constellation: rules.classify_constellation(&name),
                        name,
                        line1: tle.line1,
                        line2: tle.line2,
                        country: "不明".into(),
                        era: "不明".into(),
                        name_zh: String::new(),
                        operator: String::new(),
                        notes: String::new(),
                        user_defined: true,
                        prop: None,
                    },
                );
            }
            Some(e) => {
                let (ep_db, ep_user) = (tle_epoch_key(&e.line1), tle_epoch_key(&tle.line1));
                if let Some(db) = ep_db {
                    if ep_user.map_or(true, |u| u <= db) {
                        tracing::warn!(
                            "user TLE {} NORAD {nid} 曆元不比 DB 新，保留 DB TLE",
                            tle.source_file
                        );
                        continue;
                    }
                }
                e.line1 = tle.line1;
                e.line2 = tle.line2;
                if !tle.name.is_empty() {
                    e.name = tle.name;
                }
                e.user_defined = true;
            }
        }
    }

    for (nid, row) in userdata::load_user_catalogue(&cfg.user_catalogue_dir()) {
        let Some(e) = sats.get_mut(&nid) else { continue };
        let g = |k: &str| nonempty(&row, k);
        let (zh, en) = (g("name_zh"), g("name_en"));
        if let Some(n) = zh.clone().or(en) {
            e.name = n;
        }
        if let Some(z) = zh {
            e.name_zh = z;
        }
        if let Some(v) = g("country") {
            e.country = v;
        }
        if let Some(v) = g("purpose") {
            e.purpose = v;
        }
        if let Some(v) = g("constellation") {
            e.constellation = Some(v);
        }
        if let Some(v) = g("operator") {
            e.operator = v;
        }
        if let Some(v) = g("notes") {
            e.notes = v;
        }
        let launch = g("launch_date").and_then(|s| classify::parse_date(&s));
        let intl = g("intl_code");
        if launch.is_some() || intl.is_some() {
            e.era = classify::classify_era(launch, intl.as_deref());
        }
    }
}

// ── 統計 ─────────────────────────────────────────────────────────────────────

pub fn build_stats(idx: &SatIndex, payload_only: bool) -> Value {
    let mut country: HashMap<&str, i64> = HashMap::new();
    let mut purpose: HashMap<&str, i64> = HashMap::new();
    let mut era: HashMap<&str, i64> = HashMap::new();
    let mut constel: HashMap<&str, i64> = HashMap::new();
    let mut total = 0usize;
    for s in idx.sats.values() {
        if payload_only && (s.purpose == "碎片" || s.purpose == "火箭體") {
            continue;
        }
        total += 1;
        *country.entry(&s.country).or_default() += 1;
        *purpose.entry(&s.purpose).or_default() += 1;
        *era.entry(&s.era).or_default() += 1;
        *constel
            .entry(s.constellation.as_deref().unwrap_or("其他衛星"))
            .or_default() += 1;
    }
    fn sorted(m: HashMap<&str, i64>) -> Vec<Value> {
        let mut v: Vec<_> = m.into_iter().collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(b.0)));
        v.into_iter()
            .map(|(k, c)| json!({"label": k, "count": c}))
            .collect()
    }
    let mut era_v: Vec<_> = era.into_iter().collect();
    era_v.sort_by_key(|(k, _)| ERA_ORDER.iter().position(|e| e == k).unwrap_or(99));
    // 原版 total 為全索引數（payload_only 亦同）
    let _ = total;
    json!({
        "total": idx.sats.len(),
        "country": sorted(country),
        "purpose": sorted(purpose),
        "era": era_v.into_iter().map(|(k, c)| json!({"label": k, "count": c})).collect::<Vec<_>>(),
        "constellation": sorted(constel),
        "updated_at": Utc::now().to_rfc3339(),
    })
}

// ── DB 資訊 ──────────────────────────────────────────────────────────────────

pub fn db_info(cfg: &Config) -> Value {
    let Some(db) = cfg.resolve_db() else {
        return json!({"error": "資料庫不存在"});
    };
    let name = db
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let meta = match std::fs::metadata(&db) {
        Ok(m) => m,
        Err(e) => return json!({"error": e.to_string(), "db_name": name}),
    };
    let mtime: DateTime<Utc> = meta.modified().map(Into::into).unwrap_or_else(|_| Utc::now());
    let size_mb = (meta.len() as f64 / 1024f64.powi(2) * 10.0).round() / 10.0;
    let q = || -> anyhow::Result<(i64, i64, Option<String>, Option<String>)> {
        let con = open_ro(&db)?;
        Ok(con.query_row(
            &format!(
                "SELECT COUNT(*), COUNT(DISTINCT norad_id),
                        strftime(MIN(epoch_utc), '%Y-%m-%dT%H:%M:%S.%f'),
                        strftime(MAX(epoch_utc), '%Y-%m-%dT%H:%M:%S.%f')
                 FROM {RAW_TABLE} WHERE line1 IS NOT NULL AND line2 IS NOT NULL"
            ),
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )?)
    };
    match q() {
        Ok((total, sats, emin, emax)) => json!({
            "db_name": name,
            "db_size_mb": size_mb,
            "db_updated_at": mtime.to_rfc3339(),
            "has_tle_lines": true,
            "total_records": total,
            "valid_sat_count": sats,
            "epoch_min": emin,
            "epoch_max": emax,
        }),
        Err(e) => json!({"error": e.to_string(), "db_name": name}),
    }
}

pub type SharedIndex = Arc<SatIndex>;
