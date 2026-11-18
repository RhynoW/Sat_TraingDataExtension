//! Starlink 顆數普查、離軌名單、殼層分類、V3 部署統計、單顆再入估算
//! （Python 版 physics/starlink_census.py 的移植）。

use std::collections::{HashMap, HashSet};
use std::time::{Duration as StdDuration, Instant};

use chrono::Utc;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::{json, Map, Value};

use super::common::{self, py_iso_naive, py_iso_secs, py_iso_utc, py_round, ts_from_us};
use crate::config::{META_TABLE, RAW_TABLE};
use crate::index::open_ro;
use crate::state::AppState;

pub const KEEPTRACK_URL: &str = "https://keeptrack.space/starlink-satellite-count";
const KEEPTRACK_TTL_S: u64 = 6 * 3600;

pub const REENTRY_ALT_KM: f64 = 80.0;
pub const DEORBIT_FRESH_DAYS: i64 = 5;
pub const DEORBIT_DA30_KM: f64 = 40.0;
pub const DEORBIT_ALT_MAX_KM: f64 = 480.0;
const DEORBIT_LOOKBACK_DAYS: i64 = 45;
const DEORBIT_CACHE_TTL_S: u64 = 600;

const ERR_NO_DB: &str = "資料庫不存在";
const ERR_NO_IDS: &str = "sat_metadata.csv 內找不到任何 Starlink 衛星（檔案缺失或分類規則異常）";

fn err(msg: impl Into<String>) -> Value {
    json!({"error": msg.into()})
}

// ── keeptrack.space ─────────────────────────────────────────────────────────
static KT_CACHE: Lazy<Mutex<Option<(Instant, Value)>>> = Lazy::new(|| Mutex::new(None));

/// `[\d,]+` 結尾於 `end`（不含）之數字串起點；回傳數值
fn digits_before(s: &str, end: usize) -> Option<i64> {
    let b = s.as_bytes();
    let mut i = end;
    while i > 0 && (b[i - 1].is_ascii_digit() || b[i - 1] == b',') {
        i -= 1;
    }
    if i == end {
        return None;
    }
    s[i..end].replace(',', "").parse().ok()
}

/// `[\d,]+` 由 `start` 起之數字串
fn digits_after(s: &str, start: usize) -> Option<(i64, usize)> {
    let b = s.as_bytes();
    let mut j = start;
    while j < b.len() && (b[j].is_ascii_digit() || b[j] == b',') {
        j += 1;
    }
    if j == start {
        return None;
    }
    s[start..j].replace(',', "").parse().ok().map(|v| (v, j))
}

/// regex `([\d,]+)\s+Starlink satellites (?:are\s+)?in orbit`
fn re_in_orbit(text: &str) -> Option<i64> {
    let pat = "Starlink satellites ";
    let mut from = 0;
    while let Some(k) = text[from..].find(pat) {
        let at = from + k;
        from = at + 1;
        let rest = &text[at + pat.len()..];
        let ok = rest.starts_with("in orbit")
            || rest
                .strip_prefix("are")
                .map(|r| {
                    let t = r.trim_start();
                    t.len() < r.len() && t.starts_with("in orbit")
                })
                .unwrap_or(false);
        if !ok {
            continue;
        }
        // 前面需為 [\d,]+\s+
        let pre = &text[..at];
        let trimmed = pre.trim_end();
        if trimmed.len() == pre.len() {
            continue;
        }
        if let Some(v) = digits_before(text, trimmed.len()) {
            return Some(v);
        }
    }
    None
}

/// regex `<prefix>([\d,]+)<suffix>`（第一個符合者）
fn re_num_between(text: &str, prefix: &str, suffix: &str) -> Option<i64> {
    let mut from = 0;
    while let Some(k) = text[from..].find(prefix) {
        let s = from + k + prefix.len();
        from = from + k + 1;
        if let Some((v, j)) = digits_after(text, s) {
            if text[j..].starts_with(suffix) {
                return Some(v);
            }
        }
    }
    None
}

/// regex `([\d,]+) Starlink satellites are currently working`
fn re_working(text: &str) -> Option<i64> {
    let pat = " Starlink satellites are currently working";
    let mut from = 0;
    while let Some(k) = text[from..].find(pat) {
        let at = from + k;
        from = at + 1;
        if let Some(v) = digits_before(text, at) {
            return Some(v);
        }
    }
    None
}

/// regex `As of ([A-Za-z]+ \d{1,2}, \d{4})`
fn re_as_of(text: &str) -> Option<String> {
    let mut from = 0;
    while let Some(k) = text[from..].find("As of ") {
        let s = from + k + 6;
        from = from + k + 1;
        let b = text.as_bytes();
        let mut i = s;
        while i < b.len() && b[i].is_ascii_alphabetic() {
            i += 1;
        }
        if i == s || i >= b.len() || b[i] != b' ' {
            continue;
        }
        i += 1;
        let d0 = i;
        while i < b.len() && b[i].is_ascii_digit() && i - d0 < 2 {
            i += 1;
        }
        if i == d0 || i + 2 > b.len() || &text[i..i + 2] != ", " {
            continue;
        }
        i += 2;
        let y0 = i;
        while i < b.len() && b[i].is_ascii_digit() && i - y0 < 4 {
            i += 1;
        }
        if i - y0 != 4 {
            continue;
        }
        return Some(text[s..i].to_string());
    }
    None
}

fn parse_keeptrack(html: &str, result: &mut Map<String, Value>) -> Result<(), String> {
    let open = "<script type=\"application/ld+json\">";
    let mut from = 0;
    while let Some(k) = html[from..].find(open) {
        let s = from + k + open.len();
        let Some(e) = html[s..].find("</script>") else { break };
        let block = &html[s..s + e];
        from = s + e;
        if !block.contains("\"FAQPage\"") {
            continue;
        }
        let data: Value = serde_json::from_str(block).map_err(|e| e.to_string())?;
        let mut qa: Vec<(String, String)> = Vec::new();
        for q in data.get("mainEntity").and_then(Value::as_array).cloned().unwrap_or_default() {
            if let Some(name) = q.get("name") {
                let text = q
                    .get("acceptedAnswer")
                    .and_then(|a| a.get("text"))
                    .and_then(Value::as_str)
                    .ok_or_else(|| "'acceptedAnswer'".to_string())?;
                let key = name.as_str().map(str::to_string).unwrap_or_else(|| name.to_string());
                if let Some(slot) = qa.iter_mut().find(|(k, _)| *k == key) {
                    slot.1 = text.to_string();
                } else {
                    qa.push((key, text.to_string()));
                }
            }
        }
        for (_, text) in &qa {
            if let Some(v) = re_in_orbit(text) {
                result.insert("in_orbit".into(), json!(v));
                if let Some(d) = re_as_of(text) {
                    result.insert("as_of".into(), json!(d));
                }
            }
            if let Some(v) = re_num_between(text, "launched ", " Starlink satellites") {
                result.insert("launched_total".into(), json!(v));
            }
            if let Some(v) = re_num_between(text, "About ", " of those have since deorbited") {
                result.insert("deorbited_total".into(), json!(v));
            }
            if let Some(v) = re_working(text) {
                result.insert("working".into(), json!(v));
            }
        }
        break;
    }
    Ok(())
}

/// 抓取並解析 keeptrack.space 的 Starlink 顆數頁面（FAQPage JSON-LD），6 小時快取；失敗回 {"error"}。
pub async fn keeptrack_starlink_count() -> Value {
    if let Some((at, v)) = KT_CACHE.lock().as_ref() {
        if at.elapsed() < StdDuration::from_secs(KEEPTRACK_TTL_S) {
            return v.clone();
        }
    }
    let html = async {
        let r = common::http_client(10).get(KEEPTRACK_URL).send().await?;
        r.error_for_status()?.text().await
    }
    .await;
    let html = match html {
        Ok(h) => h,
        Err(e) => {
            tracing::warn!("keeptrack.space 抓取失敗：{e}");
            return json!({"error": format!("抓取失敗：{e}"), "source_url": KEEPTRACK_URL});
        }
    };
    let mut result = Map::new();
    result.insert("source_url".into(), json!(KEEPTRACK_URL));
    result.insert("fetched_at".into(), json!(py_iso_utc(&Utc::now())));
    match parse_keeptrack(&html, &mut result) {
        Ok(()) => {
            if !result.contains_key("in_orbit") {
                result.insert("error".into(), json!("頁面結構已變更，未能解析出數字（FAQPage JSON-LD 找不到預期欄位）"));
            }
        }
        Err(e) => {
            tracing::warn!("keeptrack.space 解析失敗：{e}");
            result.insert("error".into(), json!(format!("解析失敗：{e}")));
        }
    }
    let v = Value::Object(result);
    *KT_CACHE.lock() = Some((Instant::now(), v.clone()));
    v
}

// ── 本系統口徑 ──────────────────────────────────────────────────────────────
pub fn our_starlink_counts(st: &AppState) -> Value {
    let Some(db) = st.cfg.resolve_db() else { return err(ERR_NO_DB) };
    let ids = common::starlink_ids(st);
    if ids.is_empty() {
        return err(ERR_NO_IDS);
    }
    let r = (|| -> anyhow::Result<Value> {
        let con = open_ro(&db)?;
        let sub = common::ids_subquery(&ids);
        let now = common::now_sql();
        let count = |extra: &str| -> anyhow::Result<i64> {
            let sql = format!(
                "SELECT COUNT(DISTINCT r.norad_id) FROM {RAW_TABLE} r JOIN {sub} s ON s.norad_id = r.norad_id {extra}"
            );
            Ok(con.query_row(&sql, [], |r| r.get::<_, i64>(0))?)
        };
        let latest: Option<i64> = con.query_row(&format!("SELECT epoch_us(max(epoch_utc)) FROM {RAW_TABLE}"), [], |r| r.get(0))?;
        Ok(json!({
            "db_latest_epoch": latest.map(|u| py_iso_naive(&ts_from_us(u))).unwrap_or_else(|| "None".into()),
            "known_starlink_norad_count": ids.len(),
            "cumulative_all_time": count("")?,
            "fresh_30d": count(&format!("WHERE r.epoch_utc >= {now} - INTERVAL 30 DAY"))?,
            "fresh_14d": count(&format!("WHERE r.epoch_utc >= {now} - INTERVAL 14 DAY"))?,
            "fresh_7d": count(&format!("WHERE r.epoch_utc >= {now} - INTERVAL 7 DAY"))?,
        }))
    })();
    r.unwrap_or_else(|e| {
        tracing::warn!("our_starlink_counts 失敗：{e:#}");
        err(format!("{e:#}"))
    })
}

// ── 離軌名單 ────────────────────────────────────────────────────────────────
static DEORBIT_CACHE: Lazy<Mutex<HashMap<usize, (Instant, Value)>>> = Lazy::new(|| Mutex::new(HashMap::new()));

pub fn list_deorbiting_starlinks(st: &AppState, limit: usize) -> Value {
    let Some(db) = st.cfg.resolve_db() else { return err(ERR_NO_DB) };
    let ids = common::starlink_ids(st);
    if ids.is_empty() {
        return err(ERR_NO_IDS);
    }
    if let Some((at, v)) = DEORBIT_CACHE.lock().get(&limit) {
        if at.elapsed() < StdDuration::from_secs(DEORBIT_CACHE_TTL_S) {
            return v.clone();
        }
    }
    struct Row {
        nid: u32,
        epoch_us: i64,
        alt: f64,
        da30: f64,
        da7: f64,
        launch_us: Option<i64>,
    }
    let r = (|| -> anyhow::Result<Vec<Row>> {
        let con = open_ro(&db)?;
        let sub = common::ids_subquery(&ids);
        let now = common::now_sql();
        let sql = format!(
            "WITH base AS (
                SELECT r.norad_id, r.epoch_utc, r.sma_km - 6378.137 AS alt_km
                FROM {RAW_TABLE} r
                JOIN {sub} s ON s.norad_id = r.norad_id
                WHERE r.epoch_utc >= {now} - INTERVAL {DEORBIT_LOOKBACK_DAYS} DAY
            ), cur AS (
                SELECT norad_id, epoch_utc, alt_km FROM base
                QUALIFY ROW_NUMBER() OVER (PARTITION BY norad_id ORDER BY epoch_utc DESC) = 1
            ), past30 AS (
                SELECT norad_id, alt_km AS alt_km_30d_ago FROM base
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY norad_id
                    ORDER BY abs(date_diff('hour', epoch_utc, {now} - INTERVAL 30 DAY))
                ) = 1
            ), past7 AS (
                SELECT norad_id, alt_km AS alt_km_7d_ago FROM base
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY norad_id
                    ORDER BY abs(date_diff('hour', epoch_utc, {now} - INTERVAL 7 DAY))
                ) = 1
            )
            SELECT cur.norad_id, epoch_us(cur.epoch_utc), cur.alt_km,
                   cur.alt_km - past30.alt_km_30d_ago AS da_30d_km,
                   cur.alt_km - past7.alt_km_7d_ago AS da_7d_km,
                   epoch_us(CAST(m.launch_date AS TIMESTAMP))
            FROM cur
            JOIN past30 USING (norad_id)
            JOIN past7 USING (norad_id)
            LEFT JOIN {META_TABLE} m ON m.norad_id = cur.norad_id
            WHERE cur.epoch_utc >= {now} - INTERVAL {DEORBIT_FRESH_DAYS} DAY
              AND (past30.alt_km_30d_ago - cur.alt_km) >= {DEORBIT_DA30_KM}
              AND cur.alt_km < {DEORBIT_ALT_MAX_KM}
            ORDER BY cur.alt_km ASC"
        );
        let mut stmt = con.prepare(&sql)?;
        let rows = stmt
            .query_map([], |r| {
                Ok(Row {
                    nid: r.get::<_, i64>(0)? as u32,
                    epoch_us: r.get(1)?,
                    alt: r.get(2)?,
                    da30: r.get(3)?,
                    da7: r.get(4)?,
                    launch_us: r.get(5)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    })();
    let rows = match r {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("list_deorbiting_starlinks 失敗：{e:#}");
            return err(format!("{e:#}"));
        }
    };
    let total = rows.len();
    let items: Vec<Value> = rows
        .iter()
        .take(limit)
        .map(|r| {
            let daily = r.da7 / 7.0;
            let est = if daily < -0.05 {
                json!(py_round((r.alt - REENTRY_ALT_KM).max(0.0) / daily.abs(), 1))
            } else {
                Value::Null
            };
            json!({
                "norad_id": r.nid,
                "name": common::starlink_name(st, r.nid).unwrap_or_else(|| format!("NORAD-{}", r.nid)),
                // pandas str(Timestamp)；NULL 時 Python 版會輸出字串 "NaT"，這裡回 null
                "launch_date": r.launch_us.map(|u| common::pandas_str(&ts_from_us(u))),
                "epoch_utc": py_iso_naive(&ts_from_us(r.epoch_us)),
                "alt_km": py_round(r.alt, 1),
                "da_30d_km": py_round(r.da30, 1),
                "da_7d_km": py_round(r.da7, 1),
                "est_days_to_reentry_rough": est,
            })
        })
        .collect();
    let result = json!({
        "generated_at": py_iso_utc(&Utc::now()),
        "criteria": {"fresh_days": DEORBIT_FRESH_DAYS, "da30_km_min": DEORBIT_DA30_KM, "alt_km_max": DEORBIT_ALT_MAX_KM},
        "total_matching": total,
        "shown": items.len(),
        "items": items,
        "method": "est_days_to_reentry_rough 為近 7 天平均下降速率線性外推至 80 km 之天數，未計入阻力隨高度指數增強，會高估剩餘天數（實際再入更早），僅供排序參考；較可靠之再入預測見 seg 欄（分段 M/A 校準，背景批次每 6 小時更新）。",
    });
    DEORBIT_CACHE.lock().insert(limit, (Instant::now(), result.clone()));
    result
}

/// 目前正在離軌的 Starlink NORAD 集合（同 list_deorbiting_starlinks 口徑、全歷史；失敗回空集合）
pub fn deorbiting_norad_ids(st: &AppState) -> HashSet<u32> {
    let Some(db) = st.cfg.resolve_db() else { return HashSet::new() };
    let ids = common::starlink_ids(st);
    if ids.is_empty() {
        return HashSet::new();
    }
    let r = (|| -> anyhow::Result<HashSet<u32>> {
        let con = open_ro(&db)?;
        let sub = common::ids_subquery(&ids);
        let now = common::now_sql();
        let sql = format!(
            "WITH base AS (
                SELECT r.norad_id, r.epoch_utc, r.sma_km - 6378.137 AS alt_km
                FROM {RAW_TABLE} r
                JOIN {sub} s ON s.norad_id = r.norad_id
            ), cur AS (
                SELECT norad_id, epoch_utc, alt_km FROM base
                QUALIFY ROW_NUMBER() OVER (PARTITION BY norad_id ORDER BY epoch_utc DESC) = 1
            ), past30 AS (
                SELECT norad_id, alt_km AS alt_km_30d_ago FROM base
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY norad_id
                    ORDER BY abs(date_diff('hour', epoch_utc, {now} - INTERVAL 30 DAY))
                ) = 1
            )
            SELECT cur.norad_id FROM cur JOIN past30 USING (norad_id)
            WHERE cur.epoch_utc >= {now} - INTERVAL {DEORBIT_FRESH_DAYS} DAY
              AND (past30.alt_km_30d_ago - cur.alt_km) >= {DEORBIT_DA30_KM}
              AND cur.alt_km < {DEORBIT_ALT_MAX_KM}"
        );
        let mut stmt = con.prepare(&sql)?;
        let out = stmt
            .query_map([], |r| r.get::<_, i64>(0))?
            .filter_map(Result::ok)
            .map(|v| v as u32)
            .collect();
        Ok(out)
    })();
    r.unwrap_or_else(|e| {
        tracing::warn!("deorbiting_norad_ids 失敗：{e:#}");
        HashSet::new()
    })
}

// ── 世代分類（啟發式，依 launch_date）─────────────────────────────────────────
pub const V3_GENERATION_START: &str = "2026-09-28";

pub fn generation_of(launch: Option<&str>) -> &'static str {
    let Some(d) = launch.filter(|s| !s.is_empty()) else { return "unknown" };
    if d >= V3_GENERATION_START {
        return "v3";
    }
    if d <= "2021-05-31" {
        return "v1.0";
    }
    if d < "2021-06-01" {
        return "unknown";
    }
    if d <= "2022-12-31" {
        return "v1.5";
    }
    if d >= "2023-01-01" {
        return "v2mini";
    }
    "unknown"
}

pub fn starlink_ids_by_generation(st: &AppState, generation: &str) -> HashSet<u32> {
    let all = common::starlink_ids(st);
    if generation.is_empty() || generation == "all" {
        return (*all).clone();
    }
    let meta = common::sat_meta(&st.cfg);
    all.iter()
        .copied()
        .filter(|n| generation_of(meta.get(n).and_then(|r| r.get("launch_date")).map(String::as_str)) == generation)
        .collect()
}

// ── 殼層分類 ────────────────────────────────────────────────────────────────
const SHELL_BANDS: [(&str, f64, f64); 5] =
    [("43°", 42.0, 44.0), ("53.0°", 52.5, 53.1), ("53.2°", 53.1, 53.5), ("70°", 69.0, 71.0), ("97.6°", 96.5, 98.5)];
const SHELL_TOL_KM: f64 = 20.0;
const SHELL_LOW_KM: f64 = 300.0;
const SHELL_FRESH_DAYS: i64 = 30;
static SHELL_CACHE: Lazy<Mutex<Option<(Instant, Value)>>> = Lazy::new(|| Mutex::new(None));

fn median(v: &[f64]) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(f64::total_cmp);
    let n = s.len();
    if n == 0 {
        return f64::NAN;
    }
    if n % 2 == 1 {
        s[n / 2]
    } else {
        (s[n / 2 - 1] + s[n / 2]) / 2.0
    }
}

/// pandas `Series.quantile(q)`（線性內插）
fn quantile(v: &[f64], q: f64) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(f64::total_cmp);
    let n = s.len();
    let pos = q * (n - 1) as f64;
    let lo = pos.floor() as usize;
    let hi = (lo + 1).min(n - 1);
    let f = pos - lo as f64;
    s[lo] + (s[hi] - s[lo]) * f
}

/// 最密集 bin_km 高度帶內的中位數（value_counts().idxmax()：同數時取先出現者）
fn mode_alt(alt: &[f64], bin_km: f64) -> f64 {
    let mut counts: Vec<(f64, usize)> = Vec::new();
    for a in alt {
        let b = (a / bin_km).floor() * bin_km;
        match counts.iter_mut().find(|(k, _)| *k == b) {
            Some(c) => c.1 += 1,
            None => counts.push((b, 1)),
        }
    }
    let mut top = counts[0];
    for c in &counts {
        if c.1 > top.1 {
            top = *c;
        }
    }
    let sel: Vec<f64> = alt.iter().copied().filter(|a| *a >= top.0 - bin_km && *a < top.0 + 2.0 * bin_km).collect();
    median(&sel)
}

pub fn starlink_shells(st: &AppState) -> Value {
    if let Some((at, v)) = SHELL_CACHE.lock().as_ref() {
        if at.elapsed() < StdDuration::from_secs(600) {
            return v.clone();
        }
    }
    let Some(db) = st.cfg.resolve_db() else { return err(ERR_NO_DB) };
    let ids = common::starlink_ids(st);
    let r = (|| -> anyhow::Result<Vec<(f64, f64, i64)>> {
        let con = open_ro(&db)?;
        let sub = common::ids_subquery(&ids);
        let now = common::now_sql();
        let sql = format!(
            "SELECT r.sma_km - 6378.137 AS alt_km, r.inclination_deg AS inc_deg, epoch_us(r.epoch_utc)
             FROM {RAW_TABLE} r JOIN {sub} s ON s.norad_id = r.norad_id
             WHERE r.epoch_utc >= {now} - INTERVAL {SHELL_FRESH_DAYS} DAY AND r.epoch_utc <= {now}
             QUALIFY ROW_NUMBER() OVER (PARTITION BY r.norad_id ORDER BY r.epoch_utc DESC) = 1"
        );
        let mut stmt = con.prepare(&sql)?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, Option<f64>>(0)?.unwrap_or(f64::NAN),
                    r.get::<_, Option<f64>>(1)?.unwrap_or(f64::NAN),
                    r.get::<_, i64>(2)?,
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    })();
    let rows = match r {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("starlink_shells 失敗：{e:#}");
            return err(format!("{e:#}"));
        }
    };
    let mut used = vec![false; rows.len()];
    let mut shells = Vec::new();
    for (name, lo, hi) in SHELL_BANDS {
        let mut alt = Vec::new();
        for (i, (a, inc, _)) in rows.iter().enumerate() {
            if *inc >= lo && *inc < hi {
                used[i] = true;
                alt.push(*a);
            }
        }
        if alt.is_empty() {
            shells.push(json!({"shell": name, "inc_range": [lo, hi], "count": 0}));
            continue;
        }
        let high: Vec<f64> = alt.iter().copied().filter(|a| *a >= SHELL_LOW_KM).collect();
        let work = mode_alt(if high.is_empty() { &alt } else { &high }, 5.0);
        shells.push(json!({
            "shell": name, "inc_range": [lo, hi], "count": alt.len(),
            "work_alt_km": py_round(work, 1),
            "alt_p10_km": py_round(quantile(&alt, 0.1), 1), "alt_p90_km": py_round(quantile(&alt, 0.9), 1),
            "at_shell": alt.iter().filter(|a| (*a - work).abs() <= SHELL_TOL_KM).count(),
            "below": alt.iter().filter(|a| **a < work - SHELL_TOL_KM && **a >= SHELL_LOW_KM).count(),
            "above": alt.iter().filter(|a| **a > work + SHELL_TOL_KM).count(),
            "reentry_imminent": alt.iter().filter(|a| **a < SHELL_LOW_KM).count(),
            "retiring": work < 400.0,
        }));
    }
    let latest = rows.iter().map(|r| r.2).max();
    let out = json!({
        "shells": shells,
        "total": rows.len(),
        "unclassified": used.iter().filter(|u| !**u).count(),
        "tol_km": SHELL_TOL_KM,
        "low_km": SHELL_LOW_KM,
        "generated_at": py_iso_secs(&Utc::now()),
        "fresh_days": SHELL_FRESH_DAYS,
        "db_latest_epoch": latest.map(|u| common::pandas_str(&ts_from_us(u))),
        "method": "傾角分群；工作高度＝該群最密集的 5 km 高度帶（排除 <300 km）；±20 km 內為在工作殼層。單筆 TLE 無法分辨抬軌或離軌，「低於工作殼層」兩者皆含，離軌者見離軌名單。",
    });
    *SHELL_CACHE.lock() = Some((Instant::now(), out.clone()));
    out
}

// ── Starlink V3 ─────────────────────────────────────────────────────────────
pub const V3_INTL_LAUNCHES: [(i32, i32); 1] = [(2026, 225)];
const V3_PROVISIONAL_TTL_S: u64 = 4 * 3600;
static V3_PROV_CACHE: Lazy<Mutex<HashMap<String, (Instant, Value)>>> = Lazy::new(|| Mutex::new(HashMap::new()));

fn v3_intl_sql_filter(col: &str) -> String {
    V3_INTL_LAUNCHES
        .iter()
        .map(|(yr, num)| format!("(substr({col}, 10, 2) = '{:02}' AND substr({col}, 12, 3) = '{num:03}')", yr % 100))
        .collect::<Vec<_>>()
        .join(" OR ")
}

fn intdes_list() -> Vec<String> {
    V3_INTL_LAUNCHES.iter().map(|(y, n)| format!("{y}-{n:03}")).collect()
}

/// CelesTrak 補充檔（sup-gp.php）查詢已知 V3 批次之暫定名單；失敗優雅降級為 {"error"}
pub async fn fetch_v3_provisional_roster() -> Value {
    let key = intdes_list().join(",");
    if let Some((at, v)) = V3_PROV_CACHE.lock().get(&key) {
        if at.elapsed() < StdDuration::from_secs(V3_PROVISIONAL_TTL_S) {
            return v.clone();
        }
    }
    let client = common::http_client(15);
    let mut items: Vec<Value> = Vec::new();
    let mut errors: Vec<String> = Vec::new();
    for intdes in intdes_list() {
        let r = async {
            let resp = client
                .get("https://celestrak.org/NORAD/elements/supplemental/sup-gp.php")
                .query(&[("INTDES", intdes.as_str()), ("FORMAT", "json")])
                .send()
                .await
                .map_err(|e| e.to_string())?;
            let text = resp.error_for_status().map_err(|e| e.to_string())?.text().await.map_err(|e| e.to_string())?;
            serde_json::from_str::<Value>(&text).map_err(|e| e.to_string())
        }
        .await;
        let data = match r {
            Ok(d) => d,
            Err(e) => {
                errors.push(format!("{intdes}：{e}"));
                continue;
            }
        };
        let Some(arr) = data.as_array() else { continue };
        for o in arr {
            let alt = o
                .get("MEAN_MOTION")
                .and_then(|v| v.as_f64().or_else(|| v.as_str().and_then(|s| s.trim().parse().ok())))
                .filter(|mm| *mm != 0.0)
                .map(|mm| {
                    let n = mm * 2.0 * std::f64::consts::PI / 86400.0;
                    py_round((common::MU / (n * n)).powf(1.0 / 3.0) - common::RE, 1)
                });
            let g = |k: &str| o.get(k).cloned().unwrap_or(Value::Null);
            items.push(json!({
                "name": g("OBJECT_NAME"), "object_id": g("OBJECT_ID"),
                "provisional_norad_cat_id": g("NORAD_CAT_ID"), "epoch": g("EPOCH"),
                "alt_km": alt, "inclination_deg": g("INCLINATION"),
                "data_source": g("DATA_SOURCE"),
            }));
        }
    }
    // COSPAR 片段序：依發射段、片段長度、片段字母
    items.sort_by_key(|x| {
        let oid = x.get("object_id").and_then(Value::as_str).unwrap_or("").to_string();
        let (launch, piece) = match oid.rfind('-') {
            Some(i) => (oid[..i].to_string(), oid[i + 1..].to_string()),
            None => (String::new(), oid.clone()),
        };
        (launch, piece.chars().count(), piece)
    });
    let mut result = json!({
        "generated_at": py_iso_secs(&Utc::now()),
        "source": "CelesTrak 補充檔（sup-gp.php；SpaceX 自行提供之軌道根數，非 Space-Track 官方編目）",
        "note": "暫定名單：NORAD 編號為 CelesTrak 暫用碼、非官方 SATCAT 號碼，不會寫入本系統資料庫。一旦 Space-Track 正式編目、TLE 進入每日管線，會自動改列入上方「已編目」清單（並改用真正的 NORAD 編號）。",
        "count": items.len(),
        "items": items,
    });
    if !errors.is_empty() && result["count"] == 0 {
        result["error"] = json!(errors.join("；"));
    }
    V3_PROV_CACHE.lock().insert(key, (Instant::now(), result.clone()));
    result
}

/// 依國際編號比對已編目 V3（DB 部分）；回傳 (結果, 是否需要查暫定名單)
pub fn count_v3_candidates_db(st: &AppState) -> (Value, bool) {
    let Some(db) = st.cfg.resolve_db() else { return (err(ERR_NO_DB), false) };
    let ids = common::starlink_ids(st);
    if ids.is_empty() {
        return (err(ERR_NO_IDS), false);
    }
    let r = (|| -> anyhow::Result<(Vec<(u32, i64, f64)>, Option<i64>)> {
        let con = open_ro(&db)?;
        let sub = common::ids_subquery(&ids);
        let sql = format!(
            "WITH first_seen AS (
                SELECT r.norad_id,
                       min(r.epoch_utc) AS first_epoch,
                       arg_min(r.sma_km, r.epoch_utc) - 6378.137 AS alt_km,
                       arg_min(r.line1, r.epoch_utc) AS first_line1
                FROM {RAW_TABLE} r
                JOIN {sub} s ON s.norad_id = r.norad_id
                WHERE r.line1 IS NOT NULL
                GROUP BY r.norad_id
            )
            SELECT norad_id, epoch_us(first_epoch), alt_km
            FROM first_seen
            WHERE {}
            ORDER BY first_epoch",
            v3_intl_sql_filter("first_line1")
        );
        let mut stmt = con.prepare(&sql)?;
        let rows = stmt
            .query_map([], |r| Ok((r.get::<_, i64>(0)? as u32, r.get::<_, i64>(1)?, r.get::<_, f64>(2)?)))?
            .collect::<Result<Vec<_>, _>>()?;
        let latest: Option<i64> = con.query_row(&format!("SELECT epoch_us(max(epoch_utc)) FROM {RAW_TABLE}"), [], |r| r.get(0))?;
        Ok((rows, latest))
    })();
    let (rows, latest) = match r {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("count_v3_candidates 失敗：{e:#}");
            return (err(format!("{e:#}")), false);
        }
    };
    let items: Vec<Value> = rows
        .iter()
        .map(|(nid, fe, alt)| {
            json!({
                "norad_id": nid,
                "name": common::starlink_name(st, *nid).unwrap_or_else(|| format!("NORAD-{nid}")),
                "first_epoch": py_iso_naive(&ts_from_us(*fe)),
                "alt_km": py_round(*alt, 1),
            })
        })
        .collect();
    let need_prov = items.is_empty();
    let out = json!({
        "generated_at": py_iso_utc(&Utc::now()),
        "intl_launches": intdes_list(),
        "db_latest_epoch": latest.map(|u| py_iso_naive(&ts_from_us(u))).unwrap_or_else(|| "None".into()),
        "candidate_count": items.len(),
        "items": items,
        "provisional": {"skipped_reason": "already_cataloged", "count": 0, "items": []},
        "known_schedule_note": "公開報導（非本系統可獨立驗證）：Starship Flight 14 於 2026-09-28 12:46 UTC 發射，首度進入軌道並部署 26 顆 Starlink V3，SpaceX 確認全數建立聯繫。V3 單顆約 2,000 kg（報導引述之標稱值；V2 Mini 約 800 kg）；26 顆合計約 52 公噸為換算值，非官方實測。",
        "method": "以 TLE 國際編號（發射年＋當年度發射序號）精確比對已知 V3 部署批次清單（見 intl_launches），非入軌高度或發射日期之啟發式猜測；尚未正式編目者見下方 provisional 暫定名單。",
    });
    (out, need_prov)
}

// ── 單顆再入估算 ────────────────────────────────────────────────────────────
/// DB 最新一筆 TLE（line1, line2）；錯誤以 Value 回傳
pub fn latest_tle(st: &AppState, norad: u32) -> Result<(String, String), Value> {
    let Some(db) = st.cfg.resolve_db() else { return Err(err(ERR_NO_DB)) };
    let r = (|| -> anyhow::Result<Result<(String, String), Value>> {
        let con = open_ro(&db)?;
        let mut stmt = con.prepare(&format!("DESCRIBE {RAW_TABLE}"))?;
        let cols: Vec<String> = stmt.query_map([], |r| r.get::<_, String>(0))?.filter_map(Result::ok).collect();
        if !cols.iter().any(|c| c == "line1") || !cols.iter().any(|c| c == "line2") {
            return Ok(Err(err("本資料庫未保留 line1/line2，無法做 SGP4 外推")));
        }
        let row = con
            .query_row(
                &format!(
                    "SELECT line1, line2 FROM {RAW_TABLE}
                     WHERE norad_id = ? AND line1 IS NOT NULL AND line2 IS NOT NULL
                     ORDER BY epoch_utc DESC LIMIT 1"
                ),
                [norad as i64],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
            )
            .ok();
        Ok(row.ok_or_else(|| err(format!("NORAD {norad} 查無可用 TLE"))))
    })();
    match r {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("estimate_reentry_detail({norad}) 失敗：{e:#}");
            Err(err(format!("{e:#}")))
        }
    }
}
