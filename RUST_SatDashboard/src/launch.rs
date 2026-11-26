//! 一箭多星軌道驗證（對應 Python 版 scenario04/api/launch.py；前端 web/ext/launch.js 與線上版共用）。
//!
//! - 分群：目錄 TLE 傾角（差 ≤ 0.5°）、升交點赤經（差 ≤ 2°）、平均高度（差 ≤ 50 km）；共同曆元（成員中最新 TLE 曆元）
//!   SGP4 算緯度幅角 u，群內依相對參考星（最小 NORAD）的 Δu 排序，列出相對漂移（°/日）與距離。
//! - 歷史演化：資料庫歷史 TLE（共同曆元前 120 天）的半長軸與近地／遠地高度；相鄰兩筆間隔 ≤ 5 天且半長軸增加 > 1 km 為升軌，
//!   間隔 ≤ 2 天且減少 > 5 km 為降軌；其餘依近 14 天斜率判斷衰減或穩定。
//! - SupGP：每日管線寫入的 supgp 表（CelesTrak 營運商補充星曆），同發射或軌道相近者傳播到目錄 TLE 曆元比較位置，
//!   ≤ 25 km 吻合、≤ 100 km 可能；吻合到別的編號、且本編號的星曆落在那個編號的目錄位置時，標為疑似目錄編號互換（cross-tag）。

use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;
use std::time::SystemTime;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use chrono::{DateTime, Duration, Utc};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde_json::{json, Value};

use crate::config::{Config, RAW_TABLE};
use crate::obs::{make_prop, rnd, tle_norad};
use crate::physics::Propagator;
use crate::satadmin::{intl_code, tle_epoch};
use crate::state::AppState;

const MU: f64 = 398600.4418;
const RE: f64 = 6378.137;
const G_INCL: f64 = 0.5;
const G_RAAN: f64 = 2.0;
const G_ALT: f64 = 50.0;
const HIST_DAYS: i64 = 120;
const RAISE_KM: f64 = 1.0;
const RAISE_DT: f64 = 5.0;
const LOWER_KM: f64 = 5.0;
const LOWER_DT: f64 = 2.0;
const DECAY_SLOPE: f64 = -0.05;
const SERIES_MAX: usize = 300;
const SUP_INCL: f64 = 0.5;
const SUP_N: f64 = 0.05;
const SUP_RAAN: f64 = 5.0;
const SUP_OK: f64 = 25.0;
const SUP_MAYBE: f64 = 100.0;

#[derive(Debug, Clone, Copy)]
pub struct El {
    pub incl: f64,
    pub raan: f64,
    pub ecc: f64,
    pub n: f64,
    pub bstar: f64,
    pub a: f64,
    pub perigee: f64,
    pub apogee: f64,
    pub alt: f64,
    pub period: f64,
}

fn fnum(s: Option<&str>) -> Option<f64> {
    s?.trim().parse().ok()
}

/// TLE 文字 → 平均根數與衍生量（與 Python 相同切法）
pub fn elements(l1: &str, l2: &str) -> Option<El> {
    let incl = fnum(l2.get(8..16))?;
    let raan = fnum(l2.get(17..25))?;
    let ecc: f64 = format!("0.{}", l2.get(26..33)?.trim()).parse().ok()?;
    fnum(l2.get(34..42))?;
    fnum(l2.get(43..51))?;
    let n = fnum(l2.get(52..63))?;
    if n <= 0.0 {
        return None;
    }
    let bstar = (|| -> Option<f64> {
        let s = l1.get(53..61)?;
        let sign = if s.starts_with('-') { "-" } else { "" };
        let m: f64 = format!("{sign}0.{}", s.get(1..6)?.trim()).parse().ok()?;
        let e: i32 = s.get(6..8)?.trim().parse().ok()?;
        Some(m * 10f64.powi(e))
    })()
    .unwrap_or(0.0);
    let w = n * 2.0 * std::f64::consts::PI / 86400.0;
    let a = (MU / (w * w)).powf(1.0 / 3.0);
    let (per, apo) = (a * (1.0 - ecc) - RE, a * (1.0 + ecc) - RE);
    Some(El { incl, raan, ecc, n, bstar, a, perigee: per, apogee: apo, alt: (per + apo) / 2.0, period: 1440.0 / n })
}

/// "YYYY-MM-DD HH:MM:SS[.mmm]"（與 Python obs.fmt_time 相同）
fn fmt_time(t: &DateTime<Utc>) -> String {
    let us = t.timestamp_subsec_micros();
    format!("{}{}", t.format("%Y-%m-%d %H:%M:%S"), if us > 0 { format!(".{:03}", us / 1000) } else { String::new() })
}

fn wrap(d: f64) -> f64 {
    let d = (d + 180.0).rem_euclid(360.0) - 180.0;
    if d == -180.0 {
        180.0
    } else {
        d
    }
}

/// 緯度幅角 u（°）與位置；速度以 ±0.5 s 差分
fn arg_lat(p: &Propagator, t: &DateTime<Utc>) -> Option<(f64, [f64; 3])> {
    let r = p.position(t)?;
    let a = p.position(&(*t - Duration::milliseconds(500)))?;
    let b = p.position(&(*t + Duration::milliseconds(500)))?;
    let v = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let h = [r[1] * v[2] - r[2] * v[1], r[2] * v[0] - r[0] * v[2], r[0] * v[1] - r[1] * v[0]];
    let (nx, ny) = (-h[1], h[0]);
    let rn = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
    let nn = nx.hypot(ny);
    let u = if nn < 1e-9 {
        r[1].atan2(r[0]).to_degrees().rem_euclid(360.0)
    } else {
        let u = ((nx * r[0] + ny * r[1]) / (nn * rn)).clamp(-1.0, 1.0).acos().to_degrees();
        if r[2] < 0.0 {
            360.0 - u
        } else {
            u
        }
    };
    Some((u, r))
}

fn dist(a: &[f64; 3], b: &[f64; 3]) -> f64 {
    let (dx, dy, dz) = (a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    (dx * dx + dy * dy + dz * dz).sqrt()
}

fn sci5(x: f64) -> f64 {
    format!("{x:.5e}").parse().unwrap_or(x)
}

// ── SupGP ────────────────────────────────────────────────────────────────────

struct Sup {
    file: String,
    name: String,
    line1: String,
    line2: String,
    norad: Option<u32>,
    tag: String,
    el: El,
}

#[derive(Default)]
struct SupData {
    rows: Vec<Sup>,
    meta: Option<Value>,
}

static SUP: Lazy<Mutex<Option<(Option<SystemTime>, Arc<SupData>)>>> = Lazy::new(|| Mutex::new(None));

fn sup_load(cfg: &Config) -> Arc<SupData> {
    let db = cfg.resolve_db();
    let mt = db.as_ref().and_then(|d| std::fs::metadata(d).ok()).and_then(|m| m.modified().ok());
    let mut c = SUP.lock();
    if let Some((m, g)) = c.as_ref() {
        if *m == mt {
            return g.clone();
        }
    }
    let mut d = SupData::default();
    if let Some(db) = db.as_deref() {
        if let Ok(con) = crate::index::open_ro(db) {
            let has = |t: &str| {
                con.query_row("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [t], |r| r.get::<_, i64>(0)).map(|n| n > 0).unwrap_or(false)
            };
            if has("supgp") {
                if let Ok(mut st) = con.prepare("SELECT file, name, line1, line2 FROM supgp ORDER BY file, line1") {
                    if let Ok(rows) = st.query_map([], |r| {
                        Ok((r.get::<_, Option<String>>(0)?, r.get::<_, Option<String>>(1)?, r.get::<_, Option<String>>(2)?, r.get::<_, Option<String>>(3)?))
                    }) {
                        for (f, nm, l1, l2) in rows.flatten() {
                            let (l1, l2) = (l1.unwrap_or_default(), l2.unwrap_or_default());
                            if let Some(el) = elements(&l1, &l2) {
                                d.rows.push(Sup {
                                    file: f.unwrap_or_default(),
                                    name: nm.unwrap_or_default().trim().to_string(),
                                    norad: tle_norad(&l1),
                                    tag: intl_code(&l1).chars().take(8).collect(),
                                    line1: l1,
                                    line2: l2,
                                    el,
                                });
                            }
                        }
                    }
                }
            }
            if has("supgp_meta") {
                d.meta = con
                    .query_row("SELECT fetched_at, files, count FROM supgp_meta LIMIT 1", [], |r| {
                        Ok(json!({"fetched_at": r.get::<_, Option<String>>(0)?, "files": r.get::<_, Option<String>>(1)?, "count": r.get::<_, Option<i64>>(2)?}))
                    })
                    .ok();
            }
        }
    }
    let d = Arc::new(d);
    *c = Some((mt, d.clone()));
    d
}

fn supgp_match(n: u32, el: &El, prop: &Propagator, ep: &DateTime<Utc>, tag: &str, sup: &[Sup], cat: &Cat) -> Value {
    let Some(r0) = prop.position(ep) else { return Value::Null };
    let mut best: Option<(f64, &Sup)> = None;
    for s in sup {
        let e = &s.el;
        let near = (e.incl - el.incl).abs() <= SUP_INCL && (e.n - el.n).abs() <= SUP_N && wrap(e.raan - el.raan).abs() <= SUP_RAAN;
        if s.tag != tag && !near {
            continue;
        }
        let Some(r) = make_prop(&s.line1, &s.line2).and_then(|p| p.position(ep)) else { continue };
        let d = rnd(dist(&r, &r0), 2);
        let better = match best {
            None => true,
            Some((bd, bs)) => (d, s.file.as_str(), s.name.as_str(), s.line1.as_str()) < (bd, bs.file.as_str(), bs.name.as_str(), bs.line1.as_str()),
        };
        if better {
            best = Some((d, s));
        }
    }
    let Some((d, s)) = best else { return Value::Null };
    let status = if d <= SUP_OK { "matched" } else if d <= SUP_MAYBE { "possible" } else { "none" };
    let mut out = json!({"name": s.name, "file": s.file, "norad": s.norad, "epoch": tle_epoch(&s.line1).map(|t| fmt_time(&t)),
           "dist_km": d, "status": status, "norad_consistent": s.norad.map(|x| x == n), "own_dist_km": null, "swap_suspected": false});
    // 本物體編號的 SupGP 星曆在哪裡；若吻合的是別的編號，且本編號的星曆正落在那個編號的目錄位置 → 疑似目錄編號互換（cross-tag）
    if let Some(own) = sup.iter().find(|x| x.norad == Some(n)) {
        if let Some(ro) = make_prop(&own.line1, &own.line2).and_then(|p| p.position(ep)) {
            out["own_dist_km"] = json!(rnd(dist(&ro, &r0), 2));
            if let Some(m) = s.norad.filter(|m| status == "matched" && *m != n) {
                let rq = cat.sats.get(&m).filter(|c| !c.1.is_empty() && !c.2.is_empty()).and_then(|c| make_prop(&c.1, &c.2)).and_then(|p| p.position(ep));
                if let Some(rq) = rq {
                    let sd = rnd(dist(&ro, &rq), 2);
                    out["swap_dist_km"] = json!(sd);
                    out["swap_suspected"] = json!(sd <= SUP_OK);
                }
            }
        }
    }
    out
}

// ── 歷史演化 ─────────────────────────────────────────────────────────────────

fn history(cfg: &Config, ids: &[u32], t0: &DateTime<Utc>) -> HashMap<u32, Vec<(DateTime<Utc>, String, String)>> {
    let mut out: HashMap<u32, Vec<(DateTime<Utc>, String, String)>> = HashMap::new();
    let Some(db) = cfg.resolve_db() else { return out };
    let Ok(con) = crate::index::open_ro(&db) else { return out };
    if ids.is_empty() {
        return out;
    }
    let since = (*t0 - Duration::days(HIST_DAYS)).format("%Y-%m-%d %H:%M:%S").to_string();
    let list = ids.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(",");
    let sql = format!(
        "SELECT norad_id, line1, line2 FROM {RAW_TABLE} WHERE norad_id IN ({list}) AND epoch_utc >= TIMESTAMP '{since}'
         AND line1 IS NOT NULL AND line2 IS NOT NULL ORDER BY norad_id, epoch_utc, line1"
    );
    let Ok(mut st) = con.prepare(&sql) else { return out };
    let Ok(rows) = st.query_map([], |r| Ok((r.get::<_, i64>(0)? as u32, r.get::<_, String>(1)?, r.get::<_, String>(2)?))) else { return out };
    for (n, l1, l2) in rows.flatten() {
        let Some(ep) = tle_epoch(&l1) else { continue };
        let v = out.entry(n).or_default();
        if v.last().is_some_and(|x| x.0 == ep) {
            continue;
        }
        v.push((ep, l1.trim().to_string(), l2.trim().to_string()));
    }
    out
}

fn secs(a: &DateTime<Utc>, b: &DateTime<Utc>) -> f64 {
    (*b - *a).num_microseconds().unwrap_or(0) as f64 / 1e6
}

fn evolution(hist: &[(DateTime<Utc>, String, String)]) -> Value {
    let pts: Vec<(DateTime<Utc>, El)> = hist.iter().filter_map(|(t, l1, l2)| elements(l1, l2).map(|e| (*t, e))).collect();
    let mut out = json!({"points": pts.len(), "status": "insufficient", "raises": [], "lowers": [], "raise_total_km": 0.0,
                         "slope_km_day": null, "a_first": null, "a_last": null, "series": []});
    if pts.is_empty() {
        return out;
    }
    out["a_first"] = json!(rnd(pts[0].1.a, 2));
    out["a_last"] = json!(rnd(pts[pts.len() - 1].1.a, 2));
    out["first_epoch"] = json!(fmt_time(&pts[0].0));
    out["last_epoch"] = json!(fmt_time(&pts[pts.len() - 1].0));
    let (mut raises, mut lowers, mut tot) = (vec![], vec![], 0.0);
    for w in pts.windows(2) {
        let dt = secs(&w[0].0, &w[1].0) / 86400.0;
        let da = w[1].1.a - w[0].1.a;
        if dt <= RAISE_DT && da > RAISE_KM {
            raises.push(json!({"epoch": fmt_time(&w[1].0), "da_km": rnd(da, 2)}));
            tot += da;
        } else if dt <= LOWER_DT && da < -LOWER_KM {
            lowers.push(json!({"epoch": fmt_time(&w[1].0), "da_km": rnd(da, 2)}));
        }
    }
    out["raise_total_km"] = json!(rnd(tot, 2));
    let tl = pts[pts.len() - 1].0;
    let rec: Vec<(DateTime<Utc>, f64)> = pts.iter().filter(|p| secs(&p.0, &tl) <= 14.0 * 86400.0).map(|p| (p.0, p.1.a)).collect();
    let mut slope_r: Option<f64> = None;
    if rec.len() >= 3 && secs(&rec[0].0, &rec[rec.len() - 1].0) >= 2.0 * 86400.0 {
        let xs: Vec<f64> = rec.iter().map(|(t, _)| secs(&rec[0].0, t) / 86400.0).collect();
        let ys: Vec<f64> = rec.iter().map(|(_, a)| *a).collect();
        let (mut sx, mut sy) = (0.0, 0.0);
        for (x, y) in xs.iter().zip(&ys) {
            sx += x;
            sy += y;
        }
        let (mx, my) = (sx / xs.len() as f64, sy / ys.len() as f64);
        let (mut sxx, mut sxy) = (0.0, 0.0);
        for (x, y) in xs.iter().zip(&ys) {
            sxx += (x - mx) * (x - mx);
            sxy += (x - mx) * (y - my);
        }
        let slope = if sxx > 0.0 { sxy / sxx } else { 0.0 };
        slope_r = Some(rnd(slope, 3));
    }
    out["slope_km_day"] = json!(slope_r);
    out["status"] = json!(if !raises.is_empty() {
        "maneuvering"
    } else if !lowers.is_empty() {
        "lowering"
    } else if let Some(s) = slope_r {
        if s < DECAY_SLOPE {
            "decaying"
        } else {
            "stable"
        }
    } else {
        "insufficient"
    });
    out["raises"] = json!(raises);
    out["lowers"] = json!(lowers);
    let k = pts.len().div_ceil(SERIES_MAX).max(1);
    let mut sel: Vec<usize> = (0..pts.len()).step_by(k).collect();
    if *sel.last().unwrap() != pts.len() - 1 {
        sel.push(pts.len() - 1);
    }
    out["series"] = json!(sel.iter().map(|&i| json!([fmt_time(&pts[i].0), rnd(pts[i].1.alt, 2), rnd(pts[i].1.perigee, 2), rnd(pts[i].1.apogee, 2)])).collect::<Vec<_>>());
    out
}

// ── 分析 ─────────────────────────────────────────────────────────────────────

struct Cat {
    sats: BTreeMap<u32, (String, String, String)>, // 目錄原名、line1、line2
}

impl Cat {
    fn new(st: &Arc<AppState>) -> Self {
        let idx = st.index();
        let custom = st.satadmin.snapshot();
        let sats = idx
            .sats
            .iter()
            .map(|(n, s)| {
                let name = custom.names.get(n).map(|r| r.orig.clone()).filter(|o| !o.is_empty()).unwrap_or_else(|| s.name.clone());
                (*n, (name.trim().to_string(), s.line1.clone(), s.line2.clone()))
            })
            .collect();
        Self { sats }
    }
    fn tag(&self, n: u32) -> String {
        self.sats.get(&n).map(|s| intl_code(&s.1).chars().take(8).collect()).unwrap_or_default()
    }
}

fn analyze(st: &Arc<AppState>, tag: &str) -> Value {
    let cat = Cat::new(st);
    let sc = crate::ephemeris::satcat(&st.cfg);
    let g = crate::suggest::gcat(&st.cfg);
    let sup = sup_load(&st.cfg);
    let mem: Vec<u32> = cat.sats.keys().copied().filter(|n| cat.tag(*n) == tag).collect();
    let mut rows: Vec<Value> = vec![];
    let mut props: HashMap<u32, (Propagator, DateTime<Utc>, El)> = HashMap::new();
    for n in &mem {
        let s = &cat.sats[n];
        let (Some(el), Some(p), Some(ep)) = (elements(&s.1, &s.2), make_prop(&s.1, &s.2), tle_epoch(&s.1)) else { continue };
        let scr = sc.get(n);
        rows.push(json!({"norad": n, "name": s.0, "intl": intl_code(&s.1), "object_type": scr.map(|r| r.object_type.clone()).unwrap_or_default(),
            "official_name": scr.map(|r| r.name.clone()).unwrap_or_default(), "epoch": fmt_time(&ep),
            "incl": rnd(el.incl, 4), "raan": rnd(el.raan, 4), "ecc": rnd(el.ecc, 7), "n": rnd(el.n, 8), "bstar": sci5(el.bstar),
            "a_km": rnd(el.a, 2), "perigee_km": rnd(el.perigee, 2), "apogee_km": rnd(el.apogee, 2), "alt_km": rnd(el.alt, 2), "period_min": rnd(el.period, 3)}));
        props.insert(*n, (p, ep, el));
    }
    let mut gone: Vec<(u32, Value)> = sc
        .iter()
        .filter(|(n, r)| r.intl.chars().take(8).collect::<String>() == tag && !props.contains_key(n))
        .map(|(n, r)| (*n, json!({"norad": n, "name": r.name, "object_type": r.object_type, "decay": r.decay})))
        .collect();
    gone.sort_by_key(|x| x.0);
    let la = g.launch.get(tag).map(|l| json!(l)).unwrap_or(Value::Null);
    let mut out = json!({"tag": tag, "launch": la, "members": [], "not_in_catalog": gone.into_iter().map(|x| x.1).collect::<Vec<_>>(), "groups": [], "t0": null,
        "supgp_meta": sup.meta, "params": {"group_incl_deg": G_INCL, "group_raan_deg": G_RAAN, "group_alt_km": G_ALT, "hist_days": HIST_DAYS,
        "raise_km": RAISE_KM, "lower_km": LOWER_KM, "sup_ok_km": SUP_OK, "sup_maybe_km": SUP_MAYBE}});
    if rows.is_empty() {
        out["members"] = json!(rows);
        return out;
    }
    let nid = |r: &Value| r["norad"].as_u64().unwrap() as u32;
    let t0 = rows.iter().map(|r| props[&nid(r)].1).max().unwrap();
    out["t0"] = json!(fmt_time(&t0));
    // 分群
    let mut grp: Vec<Vec<usize>> = vec![];
    for (i, r) in rows.iter().enumerate() {
        let el = props[&nid(r)].2;
        let hit = grp.iter().position(|gl| {
            let e0 = props[&nid(&rows[gl[0]])].2;
            (el.incl - e0.incl).abs() <= G_INCL && wrap(el.raan - e0.raan).abs() <= G_RAAN && (el.alt - e0.alt).abs() <= G_ALT
        });
        match hit {
            Some(k) => grp[k].push(i),
            None => grp.push(vec![i]),
        }
    }
    grp.sort_by(|a, b| b.len().cmp(&a.len()).then(nid(&rows[a[0]]).cmp(&nid(&rows[b[0]]))));
    let mut groups = vec![];
    for (gi, gl) in grp.iter().enumerate() {
        let gid = format!("G{}", gi + 1);
        let refn = nid(&rows[gl[0]]);
        let uref = arg_lat(&props[&refn].0, &t0);
        for &i in gl {
            let n = nid(&rows[i]);
            let ul = arg_lat(&props[&n].0, &t0);
            let r = &mut rows[i];
            r["group"] = json!(gid);
            match (ul, uref) {
                (Some(ul), Some(ur)) => {
                    r["du_deg"] = json!(rnd(wrap(ul.0 - ur.0), 3));
                    r["dist_ref_km"] = json!(rnd(dist(&ul.1, &ur.1), 2));
                }
                _ => {
                    r["du_deg"] = Value::Null;
                    r["dist_ref_km"] = Value::Null;
                }
            }
            r["drift_deg_day"] = json!(rnd((props[&n].2.n - props[&refn].2.n) * 360.0, 4));
        }
        let mut order: Vec<usize> = gl.clone();
        order.sort_by(|&a, &b| {
            let ka = -rows[a]["du_deg"].as_f64().unwrap_or(-1e9);
            let kb = -rows[b]["du_deg"].as_f64().unwrap_or(-1e9);
            ka.total_cmp(&kb).then(nid(&rows[a]).cmp(&nid(&rows[b])))
        });
        for (k, &i) in order.iter().enumerate() {
            rows[i]["order"] = json!(k + 1);
        }
        let alts: Vec<f64> = gl.iter().map(|&i| props[&nid(&rows[i])].2.alt).collect();
        let mut types: Vec<String> = gl
            .iter()
            .map(|&i| rows[i]["object_type"].as_str().filter(|s| !s.is_empty()).unwrap_or("UNKNOWN").to_string())
            .collect();
        types.sort();
        types.dedup();
        let e0 = props[&refn].2;
        groups.push(json!({"id": gid, "count": gl.len(), "ref": refn, "order": order.iter().map(|&i| nid(&rows[i])).collect::<Vec<_>>(),
            "incl": rnd(e0.incl, 3), "raan": rnd(e0.raan, 3), "alt_min_km": rnd(alts.iter().cloned().fold(f64::INFINITY, f64::min), 2),
            "alt_max_km": rnd(alts.iter().cloned().fold(f64::NEG_INFINITY, f64::max), 2), "types": types}));
    }
    let ids: Vec<u32> = rows.iter().map(nid).collect();
    let hist = history(&st.cfg, &ids, &t0);
    for r in rows.iter_mut() {
        let n = nid(r);
        r["evolution"] = evolution(hist.get(&n).map(|v| v.as_slice()).unwrap_or(&[]));
        let (p, ep, el) = &props[&n];
        r["supgp"] = supgp_match(n, el, p, ep, tag, &sup.rows, &cat);
    }
    out["members"] = json!(rows);
    out["groups"] = json!(groups);
    out
}

fn resolve_tag(st: &Arc<AppState>, q: &str) -> Option<String> {
    let q = q.trim().to_uppercase();
    let b = q.as_bytes();
    if b.len() >= 8 && b[..4].iter().all(u8::is_ascii_digit) && b[4] == b'-' && b[5..8].iter().all(u8::is_ascii_digit) {
        return Some(q[..8].to_string());
    }
    let n: u32 = q.parse().ok()?;
    let idx = st.index();
    let t: String = match idx.sats.get(&n) {
        Some(s) => intl_code(&s.line1).chars().take(8).collect(),
        None => crate::ephemeris::satcat(&st.cfg).get(&n).map(|r| r.intl.chars().take(8).collect()).unwrap_or_default(),
    };
    (t.chars().count() == 8).then_some(t)
}

fn recent(st: &Arc<AppState>, days: i64) -> Vec<Value> {
    let cat = Cat::new(st);
    let sc = crate::ephemeris::satcat(&st.cfg);
    let g = crate::suggest::gcat(&st.cfg);
    let now = Utc::now();
    let mut cnt: HashMap<String, usize> = HashMap::new();
    for n in cat.sats.keys() {
        let t = cat.tag(*n);
        if t.chars().count() == 8 {
            *cnt.entry(t).or_default() += 1;
        }
    }
    let y0 = (now - Duration::days(days)).format("%Y").to_string().parse::<i32>().unwrap_or(0);
    let cutoff = (now - Duration::days(days)).format("%Y-%m-%d").to_string();
    let mut ldate: HashMap<String, String> = HashMap::new();
    let mut keys: Vec<&u32> = sc.keys().collect();
    keys.sort();
    for n in keys {
        let r = &sc[n];
        let t: String = r.intl.chars().take(8).collect();
        if cnt.contains_key(&t) && !r.launch.is_empty() && !ldate.contains_key(&t) {
            ldate.insert(t, r.launch.clone());
        }
    }
    let mut out: Vec<(String, String, Value)> = vec![];
    for (t, c) in &cnt {
        let yr: Option<i32> = t.get(..4).and_then(|y| y.parse().ok());
        if *c < 2 || yr.is_none_or(|y| y < y0) {
            continue;
        }
        let ld = ldate.get(t);
        if ld.is_some_and(|d| *d < cutoff) {
            continue;
        }
        let la = g.launch.get(t);
        let mission = la.map(|l| if l.mission.is_empty() { l.flight.clone() } else { l.mission.clone() }).unwrap_or_default();
        out.push((ld.cloned().unwrap_or_default(), t.clone(), json!({"tag": t, "count": c, "launch_date": ld, "lv": la.map(|l| l.lv.clone()).unwrap_or_default(), "mission": mission})));
    }
    out.sort_by(|a, b| (b.0.as_str(), b.1.as_str()).cmp(&(a.0.as_str(), a.1.as_str())));
    out.into_iter().map(|x| x.2).collect()
}

// ── API ──────────────────────────────────────────────────────────────────────

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/launch", get(page)).route("/api/launch", get(api_launch)).route("/api/launch/recent", get(api_recent))
}

async fn page() -> Html<String> {
    let raw = crate::assets::get("ext/launch.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

async fn api_launch(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Response {
    let qs = q.get("tag").or(q.get("norad")).cloned().unwrap_or_default();
    let st2 = st.clone();
    let v = tokio::task::spawn_blocking(move || resolve_tag(&st2, &qs).map(|t| analyze(&st2, &t))).await.ok().flatten();
    match v {
        Some(v) => Json(v).into_response(),
        None => (StatusCode::BAD_REQUEST, Json(json!({"error": "請輸入國際編號（例如 2026-260）或 NORAD 編號"}))).into_response(),
    }
}

async fn api_recent(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> Json<Value> {
    let days = q.get("days").and_then(|s| s.parse::<i64>().ok()).unwrap_or(60).clamp(7, 730);
    let st2 = st.clone();
    let v = tokio::task::spawn_blocking(move || {
        let r = recent(&st2, days);
        json!({"results": r, "days": days, "supgp": sup_load(&st2.cfg).meta})
    })
    .await
    .unwrap_or_else(|e| json!({"error": e.to_string()}));
    Json(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn elements_iss() {
        let l1 = "1 25544U 98067A   26329.50000000  .00016717  00000-0  10270-3 0  9994";
        let l2 = "2 25544  51.6400 208.9163 0006317  69.9862 290.2104 15.50000000000017";
        let e = elements(l1, l2).unwrap();
        assert!((e.incl - 51.64).abs() < 1e-9 && (e.ecc - 0.0006317).abs() < 1e-12);
        assert!((e.bstar - 1.027e-4).abs() < 1e-12);
        assert!((e.a - 6799.0).abs() < 5.0 && e.perigee > 400.0 && e.apogee < 440.0);
        assert!((e.period - 92.903).abs() < 0.01);
    }

    #[test]
    fn wrap_and_fmt() {
        assert_eq!(wrap(190.0), -170.0);
        assert_eq!(wrap(-180.0), 180.0);
        assert_eq!(wrap(359.0), -1.0);
    }
}
