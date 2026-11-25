//! 建議名稱：辨識 Space-Track 尚未命名的「OBJECT A/B/C…」（對應 Python 版 scenario04/api/suggest.py）。
//!
//! 證據等級（name_status）：official（Space-Track 已正式命名，high）＞ inferred（GCAT 逐顆判讀或單一酬載發射，medium）
//! ＞ group_inferred（只能確認是某次發射的 N 顆之一：命名到群組，不指派 A/B/C 個體）；另有 conflict（來源矛盾）、unresolved。
//! 推論名稱一律加「（推論）」並附來源鏈，只作為人工複核候選。任務類型與用途一律不自動歸因。
//! 資料：DB 內 satcat、gcat_sat、gcat_launch、gcat_meta 表（每日管線 scenario-advanced01/tools/update_satcat.py 寫入）。

use std::collections::HashMap;
use std::sync::Arc;
use std::time::SystemTime;

use axum::extract::{Query, State};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::Serialize;
use serde_json::{json, Value};

use crate::config::Config;
use crate::ephemeris::{self, SatcatRec};
use crate::index::SatIndex;
use crate::satadmin::intl_code;
use crate::state::AppState;

const ISS_TAG: &str = "1998-067";
const GCAT_URL: &str = "https://planet4589.org/space/gcat/";
const ST_URL: &str = "https://www.space-track.org/#catalog";

#[derive(Debug, Clone, Default, Serialize)]
pub struct GSat {
    pub launch_tag: String,
    pub piece: String,
    #[serde(rename = "type")]
    pub typ: String,
    pub name: String,
    pub plname: String,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct GLaunch {
    pub tag: String,
    pub date: String,
    pub lv: String,
    pub flight: String,
    pub mission: String,
    pub agency: String,
}

#[derive(Default)]
pub struct Gcat {
    pub sat: HashMap<u32, GSat>,
    pub launch: HashMap<String, GLaunch>,
    pub meta: Option<Value>,
}

static CACHE: Lazy<Mutex<Option<(Option<SystemTime>, Arc<Gcat>)>>> = Lazy::new(|| Mutex::new(None));

pub fn gcat(cfg: &Config) -> Arc<Gcat> {
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

fn load(db: &std::path::Path) -> Gcat {
    let mut g = Gcat::default();
    let Ok(con) = crate::index::open_ro(db) else { return g };
    let has = |t: &str| {
        con.query_row("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [t], |r| r.get::<_, i64>(0))
            .map(|n| n > 0)
            .unwrap_or(false)
    };
    let s = |v: Option<String>| v.unwrap_or_default();
    if has("gcat_sat") {
        if let Ok(mut st) = con.prepare("SELECT norad_id, launch_tag, piece, type, name, plname FROM gcat_sat") {
            if let Ok(rows) = st.query_map([], |r| {
                Ok((r.get::<_, i64>(0)? as u32, GSat { launch_tag: s(r.get(1)?), piece: s(r.get(2)?), typ: s(r.get(3)?), name: s(r.get(4)?), plname: s(r.get(5)?) }))
            }) {
                g.sat = rows.flatten().collect();
            }
        }
    }
    if has("gcat_launch") {
        if let Ok(mut st) = con.prepare("SELECT launch_tag, ldate, lv, flight, mission, agency FROM gcat_launch") {
            if let Ok(rows) = st.query_map([], |r| {
                let tag = s(r.get(0)?);
                Ok((tag.clone(), GLaunch { tag, date: s(r.get(1)?), lv: s(r.get(2)?), flight: s(r.get(3)?), mission: s(r.get(4)?), agency: s(r.get(5)?) }))
            }) {
                g.launch = rows.flatten().collect();
            }
        }
    }
    if has("gcat_meta") {
        g.meta = con
            .query_row("SELECT fetched_at, sat_count, launch_count, sat_updated, launch_updated FROM gcat_meta LIMIT 1", [], |r| {
                Ok(json!({"fetched_at": r.get::<_, Option<String>>(0)?, "sat_count": r.get::<_, Option<i64>>(1)?, "launch_count": r.get::<_, Option<i64>>(2)?,
                          "sat_updated": r.get::<_, Option<String>>(3)?, "launch_updated": r.get::<_, Option<String>>(4)?}))
            })
            .ok();
    }
    g
}

// ── 名稱工具 ─────────────────────────────────────────────────────────────────

/// 「OBJECT A」～「OBJECT ZZZ」
pub fn is_object_name(n: &str) -> bool {
    let t = n.trim().to_uppercase();
    t.strip_prefix("OBJECT ").is_some_and(|r| (1..=3).contains(&r.len()) && r.chars().all(|c| c.is_ascii_uppercase()))
}

const ZH: &[(&str, &str)] = &[
    ("Tongxin Jishu Shiyan", "通信技術試驗"), ("Weixing Hulianwang Jishu Shiyan", "衛星互聯網技術試驗"),
    ("Weixing Hulianwang Digui", "衛星互聯網低軌"), ("Weixing Hulianwang", "衛星互聯網"), ("Weili Kongjian", "微厘空間"),
    ("Hai Yang", "海洋"), ("Haiyang", "海洋"), ("Yaogan", "遙感"), ("Shijian", "實踐"), ("Shiyan", "試驗"), ("Gaofen", "高分"),
    ("Jilin-1", "吉林一號"), ("Jilin", "吉林"), ("Tianhui", "天繪"), ("Chuangxin", "創新"), ("Huanjing", "環境"), ("Beidou", "北斗"),
    ("Fengyun", "風雲"), ("Tianlian", "天鏈"), ("Zhongxing", "中星"), ("Qianfan", "千帆"), ("Tanluzhe", "探路者"), ("Ziyuan", "資源"),
    ("Tianqi", "天啟"), ("Xingshidai", "星時代"), ("Guowang", "國網"), ("Tianping", "天平"), ("Tiantong", "天通"), ("Kuaizhou", "快舟"),
    ("Chang Zheng", "長征"), ("Zhuque", "朱雀"), ("Guanlan", "觀瀾"), ("Tiankun", "天鯤"), ("Shenzhou", "神舟"), ("Tianzhou", "天舟"),
    ("Pujiang", "浦江"), ("Taijing", "泰景"), ("Siwei", "四維"), ("Superview", "高景"), ("Zhangheng", "張衡"), ("Huoyan", "火眼"),
];

fn cn_num(n: &str) -> String {
    const D: [&str; 10] = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
    match n.parse::<u32>() {
        Ok(v) if v > 0 && v < 10 => D[v as usize].into(),
        Ok(v) if (10..100).contains(&v) => {
            let (t, u) = (v / 10, v % 10);
            format!("{}十{}", if t == 1 { "" } else { D[t as usize] }, D[u as usize])
        }
        _ => n.to_string(),
    }
}

fn is_alpha(c: Option<char>) -> bool {
    c.is_some_and(|c| c.is_ascii_alphabetic())
}

/// 拼音名稱 → 中文；沒有可轉換部分回傳 None（與 Python to_zh 相同規則）
pub fn to_zh(name: &str) -> Option<String> {
    let s = name.trim();
    if s.is_empty() {
        return None;
    }
    // YG51、YG53/YG56
    if s.split('/').all(|p| p.strip_prefix("YG").is_some_and(|d| !d.is_empty() && d.chars().all(|c| c.is_ascii_digit()))) {
        return Some(s.split('/').map(|p| format!("遙感{}號", cn_num(&p[2..]))).collect::<Vec<_>>().join("／"));
    }
    let mut out = s.to_string();
    for (a, b) in ZH {
        let mut res = String::new();
        let mut rest = out.as_str();
        while let Some(i) = rest.find(a) {
            let before = rest[..i].chars().last();
            let after = rest[i + a.len()..].chars().next();
            if is_alpha(before) || is_alpha(after) {
                res.push_str(&rest[..i + a.len()]);
            } else {
                res.push_str(&rest[..i]);
                res.push_str(b);
                if after == Some(' ') {
                    rest = &rest[i + a.len() + 1..];
                    continue;
                }
            }
            rest = &rest[i + a.len()..];
        }
        res.push_str(rest);
        out = res;
    }
    // 「N hao …」格式（以空白切詞；數字可黏在前一個中文詞後面，如「遙感30 hao」）
    let toks: Vec<&str> = out.split(' ').collect();
    let mut res: Vec<String> = Vec::new();
    let mut i = 0;
    let num = |t: &str| !t.is_empty() && t.chars().all(|c| c.is_ascii_digit());
    let split_num = |t: &str| -> (String, String) {
        let d: String = t.chars().rev().take_while(|c| c.is_ascii_digit()).collect::<Vec<_>>().into_iter().rev().collect();
        (t[..t.len() - d.len()].to_string(), d)
    };
    while i < toks.len() {
        let t = toks[i];
        let at = |k: usize| toks.get(i + k).copied().unwrap_or("");
        let (prefix, d) = split_num(t);
        if !d.is_empty() && at(1) == "hao" {
            let mut piece = format!("{prefix}{}號", cn_num(&d));
            let mut step = 2;
            if at(2).len() == 1 && at(2).chars().all(|c| c.is_ascii_uppercase()) && num(at(3)) && at(4) == "xing" {
                piece.push_str(&format!("{}星{}星", at(2), at(3)));
                step = 5;
            } else if num(at(2)) && at(3) == "zu" && num(at(4)) && at(5) == "xing" {
                piece.push_str(&format!("{}組{}星", at(2), at(4)));
                step = 6;
            } else if num(at(2)) && at(3) == "xing" {
                piece.push_str(&format!("{}星", at(2)));
                step = 4;
            }
            // Python 的 " ?(\d+) hao" 會吃掉前面的空白：接到上一詞
            match res.last_mut() {
                Some(prev) if prefix.is_empty() => prev.push_str(&piece),
                _ => res.push(piece),
            }
            i += step;
        } else if num(t) && at(1) == "xing" && !res.is_empty() {
            res.push(format!("{t}星"));
            i += 2;
        } else {
            res.push(t.to_string());
            i += 1;
        }
    }
    let fin = res.join(" ");
    (fin != s).then_some(fin)
}

fn digits(s: &str) -> Vec<String> {
    let mut v = Vec::new();
    let mut cur = String::new();
    for c in s.chars() {
        if c.is_ascii_digit() {
            cur.push(c);
        } else if !cur.is_empty() {
            v.push(cur.trim_start_matches('0').to_string());
            cur.clear();
        }
    }
    if !cur.is_empty() {
        v.push(cur.trim_start_matches('0').to_string());
    }
    v
}

fn is_payload(t: &str) -> bool {
    t == "PAYLOAD" || t == "PAY"
}

pub fn suggest_one(
    nid: u32,
    idx: &SatIndex,
    sc: &HashMap<u32, SatcatRec>,
    g: &Gcat,
    mates_by_tag: &HashMap<String, Vec<u32>>,
    sc_meta: Option<&ephemeris::FetchRec>,
) -> Value {
    let s = idx.sats.get(&nid);
    let rec = sc.get(&nid);
    let cur = s.map(|s| s.name.clone()).or_else(|| rec.map(|r| r.name.clone())).unwrap_or_default();
    let intl = s.map(|s| intl_code(&s.line1)).filter(|x| !x.is_empty()).or_else(|| rec.map(|r| r.intl.clone())).unwrap_or_default();
    let tag: String = intl.chars().take(8).collect();
    let letter: String = intl.chars().skip(8).collect();
    let gs = g.sat.get(&nid);
    let mut la = g.launch.get(&tag);
    let meta = g.meta.clone().unwrap_or(Value::Null);
    let mates: Vec<Value> = mates_by_tag
        .get(&tag)
        .map(|v| {
            v.iter()
                .take(80)
                .map(|m| {
                    let mr = sc.get(m);
                    json!({"norad_id": m, "intl": mr.map(|r| r.intl.clone()).unwrap_or_default(),
                           "name": idx.sats.get(m).map(|x| x.name.clone()).or_else(|| mr.map(|r| r.name.clone())).unwrap_or_default(),
                           "object_type": mr.map(|r| r.object_type.clone()).unwrap_or_default(),
                           "gcat_name": g.sat.get(m).map(|x| x.name.clone()).unwrap_or_default(), "self": *m == nid})
                })
                .collect()
        })
        .unwrap_or_default();
    let n_pay = mates.iter().filter(|m| is_payload(m["object_type"].as_str().unwrap_or(""))).count().max(if mates.is_empty() { 0 } else { 1 });
    let n_pay = if n_pay == 0 { mates.len() } else { n_pay };
    let mut sources: Vec<Value> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();
    let st_src = json!({"source": "Space-Track SATCAT", "url": ST_URL, "date": sc_meta.map(|m| m.fetched_at.clone()).unwrap_or_default()});
    let g_sat_src = json!({"source": "GCAT satcat（McDowell, CC BY 4.0）", "url": GCAT_URL, "date": meta["sat_updated"].as_str().unwrap_or("")});
    let g_la_src = json!({"source": "GCAT launch log（McDowell, CC BY 4.0）", "url": GCAT_URL, "date": meta["launch_updated"].as_str().unwrap_or("")});
    let official = rec.map(|r| r.name.clone()).unwrap_or_default();
    let sc_type = rec.map(|r| r.object_type.clone()).unwrap_or_default();
    if let Some(gs) = gs {
        if is_payload(&sc_type) && !gs.typ.is_empty() && !gs.typ.to_uppercase().starts_with('P') {
            warnings.push(format!("類型不一致：SATCAT {sc_type}、GCAT {}", gs.typ));
        }
    }
    let (mut status, mut conf, mut name, mut raw): (&str, Option<&str>, Option<String>, Option<String>) = ("unresolved", None, None, None);
    if !official.is_empty() && !is_object_name(&official) && official != cur {
        status = "official";
        conf = Some("high");
        name = Some(official.clone());
        raw = Some(official.clone());
        sources.push(st_src.clone());
        if !sc_type.is_empty() && !is_payload(&sc_type) {
            warnings.push(format!("Space-Track 已判定非酬載（{sc_type}）"));
        }
        if let Some(gs) = gs {
            let (a, b) = (digits(&gs.name), digits(&official));
            if !gs.name.is_empty() && !a.is_empty() && !b.is_empty() && a[0] != b[0] {
                status = "conflict";
                conf = Some("medium");
                warnings.push(format!("Space-Track「{official}」與 GCAT「{}」編號不一致", gs.name));
                sources.push(g_sat_src.clone());
            }
        }
    } else if let Some(gs) = gs.filter(|gs| !gs.name.is_empty() && !is_object_name(&gs.name)) {
        let zh = to_zh(&gs.name);
        name = Some(format!("{}（推論）", zh.unwrap_or_else(|| gs.name.clone())));
        raw = Some(gs.name.clone());
        status = "inferred";
        conf = Some("medium");
        sources.push(g_sat_src.clone());
        if la.is_some() {
            sources.push(g_la_src.clone());
        }
    } else if let Some(l) = la.filter(|_| tag != ISS_TAG) {
        let r = if !l.mission.is_empty() { l.mission.clone() } else { l.flight.clone() };
        sources.push(g_la_src.clone());
        let mut base = to_zh(&r).unwrap_or_else(|| r.clone());
        if base.is_empty() {
            base = format!("{} {} 發射", l.lv, l.date.chars().take(4).collect::<String>());
            conf = Some("low");
        }
        raw = Some(r);
        if n_pay <= 1 {
            status = "inferred";
            conf = conf.or(Some("medium"));
            name = Some(format!("{base}（推論）"));
        } else {
            status = "group_inferred";
            conf = conf.or(Some("medium"));
            name = Some(format!("{base} 群組衛星（推論）"));
            warnings.push(format!("同次發射 {n_pay} 顆酬載，A/B/C 與個別衛星的對應尚未建立"));
        }
    }
    if !warnings.is_empty() && (status == "inferred" || status == "group_inferred") && conf == Some("medium") {
        conf = Some("low");
    }
    if s.is_none() {
        warnings.push("不在目前 TLE 目錄".into());
    }
    let mut mission_raw = la.map(|l| if !l.mission.is_empty() { l.mission.clone() } else { l.flight.clone() }).unwrap_or_default();
    if tag == ISS_TAG {
        mission_raw = "自國際太空站部署".into();
        la = None;
    }
    let srcs: Vec<String> = sources
        .iter()
        .map(|x| format!("{} {}", x["source"].as_str().unwrap_or(""), x["date"].as_str().unwrap_or("")).trim().to_string())
        .collect();
    let note = name.as_ref().map(|n| {
        let mut t = format!("[{status}/{}] 依據：{}", conf.unwrap_or("-"), srcs.join("；"));
        if let Some(r) = raw.as_ref().filter(|r| *r != n) {
            t.push_str(&format!("；原始名稱 {r}"));
        }
        if !intl.is_empty() {
            t.push_str(&format!("；國際編號 {intl}（發射 {tag}、序號 {letter}）"));
        }
        if !warnings.is_empty() {
            t.push_str(&format!("；注意：{}", warnings.join("；")));
        }
        t.chars().take(500).collect::<String>()
    });
    let lg = match la {
        Some(l) => json!({"value": format!("{tag}（{} {}）", l.date.chars().take(11).collect::<String>().trim(), l.lv), "confidence": "high"}),
        None if tag == ISS_TAG => json!({"value": format!("{tag}（國際太空站部署）"), "confidence": "high"}),
        None if !tag.is_empty() => json!({"value": tag, "confidence": "medium"}),
        None => json!({"value": null, "confidence": null}),
    };
    let ind_status = match status {
        "official" => "confirmed",
        "inferred" => "inferred",
        "conflict" => "disputed",
        _ => "unconfirmed",
    };
    let cand = to_zh(&mission_raw).unwrap_or(mission_raw.clone());
    json!({
        "norad_id": nid, "current_name": cur, "intl_code": intl, "launch_tag": tag, "piece": letter, "in_catalog": s.is_some(),
        "layers": {
            "launch_group": lg,
            "candidate_mission": {"value": if cand.is_empty() { Value::Null } else { json!(cand) }, "confidence": if mission_raw.is_empty() { Value::Null } else { json!("medium") }},
            "individual": {"value": if matches!(status, "official" | "inferred" | "conflict") { json!(name) } else { Value::Null }, "status": ind_status},
            "mission_type": "unknown", "capability": "unknown",
        },
        "object_type": sc_type, "official_name": if official.is_empty() { Value::Null } else { json!(official) },
        "gcat": gs, "launch": la, "mates": mates, "payloads_in_launch": n_pay,
        "suggest": name, "raw_name": raw, "name_status": status, "confidence": conf, "sources": sources, "warnings": warnings,
        "note": note.unwrap_or_default(),
    })
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/satadmin/suggest", get(api_suggest))
}

async fn api_suggest(State(st): State<Arc<AppState>>, Query(q): Query<HashMap<String, String>>) -> impl IntoResponse {
    let st2 = st.clone();
    let v = tokio::task::spawn_blocking(move || {
        let idx = st2.index();
        let sc = ephemeris::satcat(&st2.cfg);
        let meta = ephemeris::satcat_meta(&st2.cfg);
        let g = gcat(&st2.cfg);
        let d = st2.satadmin.snapshot();
        let ids: Vec<u32> = if q.get("scope").is_some_and(|s| s == "objects") {
            let lim: usize = q.get("limit").and_then(|s| s.parse().ok()).unwrap_or(1000).min(3000);
            let mut v: Vec<u32> = idx
                .sats
                .values()
                .filter(|s| is_object_name(&d.names.get(&s.norad_id).map(|r| r.orig.clone()).filter(|o| !o.is_empty()).unwrap_or_else(|| s.name.clone())))
                .map(|s| s.norad_id)
                .collect();
            v.sort_unstable_by(|a, b| b.cmp(a));
            v.truncate(lim);
            v
        } else {
            crate::satadmin::parse_norads(q.get("norad").map(String::as_str).unwrap_or("")).into_iter().take(500).collect()
        };
        let mut tags: HashMap<String, Vec<u32>> = HashMap::new();
        for (n, r) in sc.iter() {
            let t: String = r.intl.chars().take(8).collect();
            if !t.is_empty() {
                tags.entry(t).or_default().push(*n);
            }
        }
        for v in tags.values_mut() {
            v.sort_unstable();
        }
        let rows: Vec<Value> = ids
            .iter()
            .map(|&n| {
                let mut v = suggest_one(n, &idx, &sc, &g, &tags, meta.as_ref());
                // 已自訂名稱：附上目前紀錄，供前端判斷「可升級／來源變動」
                if let Some(rec) = d.names.get(&n) {
                    v["custom"] = json!(rec);
                    if is_object_name(&rec.orig) || rec.orig.is_empty() {
                        v["current_name"] = json!(if rec.orig.is_empty() { v["current_name"].clone() } else { json!(rec.orig) });
                    }
                }
                v
            })
            .collect();
        let cnt = |k: &str| rows.iter().filter(|r| r["name_status"] == k).count();
        json!({"results": rows, "count": rows.len(),
               "counts": {"official": cnt("official"), "inferred": cnt("inferred"), "group_inferred": cnt("group_inferred"), "conflict": cnt("conflict"), "unresolved": cnt("unresolved")},
               "satcat_loaded": !sc.is_empty(), "gcat": g.meta,
               "credit": "GCAT: Jonathan C. McDowell, General Catalog of Artificial Space Objects, planet4589.org (CC-BY)"})
    })
    .await
    .unwrap_or_else(|e| json!({"error": e.to_string()}));
    Json(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zh_conversion_matches_python() {
        let cases = [
            ("Yaogan 30 hao 01 zu 01 xing", Some("遙感三十號01組01星")),
            ("YG51", Some("遙感五十一號")),
            ("YG53/YG56", Some("遙感五十三號／遙感五十六號")),
            ("Tanluzhe", Some("探路者")),
            ("Hai Yang 2 hao 05 xing", Some("海洋二號05星")),
            ("Weili Kongjian 05-08", Some("微厘空間05-08")),
            ("Shiyan 28 hao B 01 xing", Some("試驗二十八號B星01星")),
            ("Jilin-1 Gaofen 05B", Some("吉林一號高分05B")),
            ("Jiguang Xingzuo 01 xing", Some("Jiguang Xingzuo 01星")),
            ("Soyuz Rideshare 17", None),
        ];
        for (a, b) in cases {
            assert_eq!(to_zh(a).as_deref(), b, "{a}");
        }
        assert!(is_object_name("OBJECT A") && is_object_name("object zz") && !is_object_name("OBJECT 12") && !is_object_name("OBJECTA"));
        assert_eq!(digits("ET-001C"), vec!["1"]);
    }
}
