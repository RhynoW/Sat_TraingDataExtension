//! SATCAT 每日異動（對應 Python 版 scenario04/api/changes.py）。
//!
//! 讀 DB 內 satcat_change／satcat_change_meta 表（每日管線 scenario-advanced01/tools/update_satcat.py 寫入、跟著 DB 發布）：
//! Space-Track class/satcat_change 為準（名稱／國際編號／國家／發射日／DECAY 的異動與 CHANGE_MADE 時間），再以前後兩份
//! SATCAT 快照比對補 OBJECT_TYPE 變更。類別（管線端分好）：new 新編目、named OBJECT x → 正式名稱、renamed 更名、
//! decayed 再入、decay_fix 再入日期修正、type 類型變更、other 其他欄位。
//! 單機版另附每筆的自訂名稱與所屬群組（伺服器端保存），並標出「可升級」（已套用推論名稱、Space-Track 已正式命名）。

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::SystemTime;

use axum::extract::{Query, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Duration, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::Serialize;
use serde_json::{json, Value};

use crate::config::Config;
use crate::state::AppState;

pub const KINDS: [&str; 7] = ["new", "named", "renamed", "decayed", "decay_fix", "type", "other"];

#[derive(Debug, Clone, Default, Serialize)]
pub struct Change {
    pub norad_id: u32,
    pub change_made: String,
    pub kind: String,
    pub field: String,
    pub previous: String,
    pub current: String,
    pub name: String,
    pub intl: String,
    pub source: String,
}

#[derive(Default)]
pub struct Changes {
    pub rows: Vec<Change>,
    pub meta: Option<Value>,
}

static CACHE: Lazy<Mutex<Option<(Option<SystemTime>, Arc<Changes>)>>> = Lazy::new(|| Mutex::new(None));

pub fn changes(cfg: &Config) -> Arc<Changes> {
    let db = cfg.resolve_db();
    let mt = db.as_ref().and_then(|d| std::fs::metadata(d).ok()).and_then(|m| m.modified().ok());
    let mut c = CACHE.lock();
    if let Some((m, g)) = c.as_ref() {
        if *m == mt {
            return g.clone();
        }
    }
    let g = Arc::new(db.as_deref().map(load).unwrap_or_default());
    *c = Some((mt, g.clone()));
    g
}

fn load(db: &std::path::Path) -> Changes {
    let mut out = Changes::default();
    let Ok(con) = crate::index::open_ro(db) else { return out };
    let has = |t: &str| {
        con.query_row("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [t], |r| r.get::<_, i64>(0))
            .map(|n| n > 0)
            .unwrap_or(false)
    };
    let s = |v: Option<String>| v.unwrap_or_default();
    if has("satcat_change") {
        if let Ok(mut st) = con.prepare(
            "SELECT norad_id, change_made, kind, field, previous, current, name, intl, source FROM satcat_change ORDER BY change_made DESC, norad_id DESC",
        ) {
            if let Ok(rows) = st.query_map([], |r| {
                Ok(Change {
                    norad_id: r.get::<_, i64>(0)? as u32,
                    change_made: s(r.get(1)?),
                    kind: s(r.get(2)?),
                    field: s(r.get(3)?),
                    previous: s(r.get(4)?),
                    current: s(r.get(5)?),
                    name: s(r.get(6)?),
                    intl: s(r.get(7)?),
                    source: s(r.get(8)?),
                })
            }) {
                out.rows = rows.flatten().collect();
            }
        }
    }
    if has("satcat_change_meta") {
        out.meta = con
            .query_row("SELECT fetched_at, days, count, spacetrack, diff FROM satcat_change_meta LIMIT 1", [], |r| {
                Ok(json!({"fetched_at": r.get::<_, Option<String>>(0)?, "days": r.get::<_, Option<i64>>(1)?, "count": r.get::<_, Option<i64>>(2)?,
                          "spacetrack": r.get::<_, Option<i64>>(3)?, "diff": r.get::<_, Option<i64>>(4)?}))
            })
            .ok();
    }
    out
}

/// 無正式名稱：OBJECT A～ZZZ、TBA…、UNKNOWN、空白（與管線 NONAME_RE 相同）
pub fn is_noname(n: &str) -> bool {
    let t = n.trim().to_uppercase();
    t.is_empty() || t == "UNKNOWN" || t.starts_with("TBA") || crate::suggest::is_object_name(&t)
}

pub struct Filter<'a> {
    pub days: i64,
    pub kinds: Option<HashSet<&'a str>>,
    pub norads: Option<HashSet<u32>>,
    pub q: String,
}

/// 依天數／類別／NORAD／關鍵字篩選；counts 為期間內各類別筆數（不受類別篩選影響）
pub fn select<'a>(rows: &'a [Change], f: &Filter, now: DateTime<Utc>) -> (Vec<&'a Change>, HashMap<&'static str, usize>) {
    let cut = (now - Duration::days(f.days)).format("%Y-%m-%d %H:%M:%S").to_string();
    let mut counts: HashMap<&'static str, usize> = KINDS.iter().map(|k| (*k, 0)).collect();
    let ql = f.q.trim().to_uppercase();
    let mut out = vec![];
    for r in rows.iter().filter(|r| r.change_made >= cut) {
        if let Some(k) = KINDS.iter().find(|k| **k == r.kind) {
            *counts.get_mut(k).unwrap() += 1;
        }
        if f.kinds.as_ref().is_some_and(|ks| !ks.contains(r.kind.as_str())) {
            continue;
        }
        if f.norads.as_ref().is_some_and(|ns| !ns.contains(&r.norad_id)) {
            continue;
        }
        if !ql.is_empty()
            && ql != r.norad_id.to_string()
            && ![&r.name, &r.intl, &r.previous, &r.current].iter().any(|s| s.to_uppercase().contains(&ql))
        {
            continue;
        }
        out.push(r);
    }
    (out, counts)
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/satadmin/changes", get(api_changes))
}

/// ?days=30（1–90）&kind=named,decayed&norad=1,2&q=關鍵字&mine=1（只看已更名或群組內）
async fn api_changes(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> impl IntoResponse {
    let st2 = st.clone();
    let v = tokio::task::spawn_blocking(move || {
        let c = changes(&st2.cfg);
        let idx = st2.index();
        let d = st2.satadmin.snapshot();
        let days = q.get("days").and_then(|s| s.parse::<i64>().ok()).unwrap_or(30).clamp(1, 90);
        let kinds: Option<HashSet<&str>> = q.get("kind").map(|s| s.split(',').filter(|k| KINDS.contains(k)).collect::<HashSet<&str>>()).filter(|s| !s.is_empty());
        let mut groups_of: HashMap<u32, Vec<String>> = HashMap::new();
        for g in &d.groups {
            let p = d.path(&g.id);
            for m in &g.members {
                groups_of.entry(*m).or_default().push(p.clone());
            }
        }
        let mut norads: Option<HashSet<u32>> =
            q.get("norad").filter(|s| !s.trim().is_empty()).map(|s| crate::satadmin::parse_norads(s).into_iter().collect());
        if q.get("mine").is_some_and(|s| s == "1") {
            let mine: HashSet<u32> = d.names.keys().copied().chain(groups_of.keys().copied()).collect();
            norads = Some(match norads {
                Some(n) => n.intersection(&mine).copied().collect(),
                None => mine,
            });
        }
        let f = Filter { days, kinds, norads, q: q.get("q").cloned().unwrap_or_default() };
        let (sel, counts) = select(&c.rows, &f, Utc::now());
        let total = sel.len();
        let limit = 5000;
        let results: Vec<Value> = sel
            .into_iter()
            .take(limit)
            .map(|r| {
                let rec = d.names.get(&r.norad_id);
                // 目錄名稱：已自訂者以原名（Space-Track 目錄名）判斷是否仍是 OBJECT x
                let cat = idx.sats.get(&r.norad_id).map(|s| rec.map(|x| x.orig.clone()).filter(|o| !o.is_empty()).unwrap_or_else(|| s.name.trim().to_string()));
                let stale = r.kind == "named" && cat.as_deref().is_some_and(is_noname);
                let upgrade = r.kind == "named" && rec.is_some_and(|x| ["inferred", "group_inferred", "conflict", "unresolved"].contains(&x.status.as_str()));
                let mut v = json!(r);
                v["catalog_name"] = json!(cat);
                v["catalog_stale"] = json!(stale);
                v["custom"] = json!(rec);
                v["groups"] = json!(groups_of.get(&r.norad_id).cloned().unwrap_or_default());
                v["upgrade"] = json!(upgrade);
                v
            })
            .collect();
        json!({"total": total, "results": results, "truncated": total > limit, "counts": counts, "days": days, "meta": c.meta})
    })
    .await
    .unwrap_or_else(|e| json!({"error": e.to_string()}));
    Json(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ch(n: u32, at: &str, kind: &str, name: &str) -> Change {
        Change { norad_id: n, change_made: at.into(), kind: kind.into(), field: "name".into(), name: name.into(), current: name.into(), ..Default::default() }
    }

    #[test]
    fn select_matches_python() {
        let rows = vec![
            ch(62617, "2026-11-25 18:01:52", "decayed", "SCOT-1 (SCOT)"),
            ch(100928, "2026-11-19 18:13:19", "named", "IRIDE-MS1-EAG2-18"),
            ch(5, "2026-09-01 00:00:00", "new", "OBJECT A"),
        ];
        let now = DateTime::parse_from_rfc3339("2026-11-26T00:00:00Z").unwrap().with_timezone(&Utc);
        let f = |days, kinds: Option<HashSet<&'static str>>, norads: Option<HashSet<u32>>, q: &str| Filter { days, kinds, norads, q: q.into() };
        let (s, c) = select(&rows, &f(30, None, None, ""), now);
        assert_eq!(s.len(), 2);
        assert_eq!((c["named"], c["decayed"], c["new"]), (1, 1, 0));
        assert_eq!(select(&rows, &f(30, Some(["decayed"].into()), None, ""), now).0.len(), 1);
        assert_eq!(select(&rows, &f(30, None, Some([100928].into()), ""), now).0.len(), 1);
        assert_eq!(select(&rows, &f(30, None, None, "iride"), now).0.len(), 1);
        assert_eq!(select(&rows, &f(90, None, None, ""), now).0.len(), 3);
        assert_eq!(select(&rows, &f(3, None, None, ""), now).0.len(), 1);
    }

    #[test]
    fn noname() {
        for n in ["OBJECT A", "object zz", "TBA - TO BE ASSIGNED", "UNKNOWN", ""] {
            assert!(is_noname(n), "{n}");
        }
        for n in ["SJ-24", "OBJECT", "OBJECT ABCD", "STARLINK-1"] {
            assert!(!is_noname(n), "{n}");
        }
    }
}
