//! 故事 JSON 驗證：手寫對應 config/stories/schema.json 之規則（Python 版以 jsonschema 驗證，
//! 不合者記 WARNING 並略過）。schema.json 變更時需同步此檔。
//! `format: uri` 與 Python jsonschema 預設行為相同，不檢查。

use serde_json::{Map, Value};

const SECTION_TYPES: [&str; 17] = [
    "text", "toc", "table", "sat", "positions", "embed", "groupstats", "isrres", "maneuvers",
    "radar", "skyplot", "cdm", "reentry", "revisit", "shells", "faq", "image",
];
const MODES: [&str; 6] = ["all", "country", "constellation", "purpose", "group", "ids"];
const GROUP_KEYS: [&str; 6] = ["gps", "beidou", "starlink", "oneweb", "prc_isr", "prc_comm"];

type R = Result<(), String>;

fn is_int(v: &Value) -> bool {
    match v {
        Value::Number(n) => n.is_i64() || n.is_u64() || n.as_f64().is_some_and(|f| f.fract() == 0.0),
        _ => false,
    }
}

/// `^[a-z0-9][a-z0-9-]{0,63}$`
pub fn valid_sid(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty()
        && b.len() <= 64
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b[1..]
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
}

/// `^\d{4}-\d{2}-\d{2}$`（Python `$` 亦接受結尾換行）
fn valid_date(s: &str) -> bool {
    let s = s.strip_suffix('\n').unwrap_or(s);
    let b = s.as_bytes();
    b.len() == 10
        && b.iter().enumerate().all(|(i, c)| {
            if i == 4 || i == 7 {
                *c == b'-'
            } else {
                c.is_ascii_digit()
            }
        })
}

/// `^[A-Za-z][A-Za-z0-9_-]*$`
fn valid_anchor(s: &str) -> bool {
    let s = s.strip_suffix('\n').unwrap_or(s);
    let b = s.as_bytes();
    !b.is_empty()
        && b[0].is_ascii_alphabetic()
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_' || *c == b'-')
}

/// `^[a-z][a-z0-9_-]{0,31}$`
fn valid_site(s: &str) -> bool {
    let s = s.strip_suffix('\n').unwrap_or(s);
    let b = s.as_bytes();
    !b.is_empty()
        && b.len() <= 32
        && b[0].is_ascii_lowercase()
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
}

fn string(v: &Value, path: &str, min_len: usize) -> R {
    match v.as_str() {
        Some(s) if s.chars().count() >= min_len => Ok(()),
        Some(_) => Err(format!("{path} 長度不足")),
        None => Err(format!("{path} 需為字串")),
    }
}

fn str_pat(v: &Value, path: &str, f: fn(&str) -> bool) -> R {
    match v.as_str() {
        Some(s) if f(s) => Ok(()),
        Some(s) => Err(format!("{path}={s:?} 不符格式")),
        None => Err(format!("{path} 需為字串")),
    }
}

fn number(v: &Value, path: &str, int: bool, lo: Option<f64>, hi: Option<f64>) -> R {
    let Some(x) = v.as_f64().filter(|_| v.is_number()) else {
        return Err(format!("{path} 需為數值"));
    };
    if int && !is_int(v) {
        return Err(format!("{path} 需為整數"));
    }
    if lo.is_some_and(|lo| x < lo) || hi.is_some_and(|hi| x > hi) {
        return Err(format!("{path} 超出範圍"));
    }
    Ok(())
}

fn array<'a>(v: &'a Value, path: &str, min_items: usize) -> Result<&'a Vec<Value>, String> {
    match v.as_array() {
        Some(a) if a.len() >= min_items => Ok(a),
        Some(_) => Err(format!("{path} 項目不足")),
        None => Err(format!("{path} 需為陣列")),
    }
}

fn enum_of(v: &Value, path: &str, opts: &[&str]) -> R {
    match v.as_str() {
        Some(s) if opts.contains(&s) => Ok(()),
        _ => Err(format!("{path} 不在允許值內")),
    }
}

fn require(o: &Map<String, Value>, keys: &[&str], path: &str) -> R {
    for k in keys {
        if !o.contains_key(*k) {
            return Err(format!("{path} 缺少必要欄位 '{k}'"));
        }
    }
    Ok(())
}

fn norad_list(v: &Value, path: &str, min_items: usize) -> R {
    for (i, x) in array(v, path, min_items)?.iter().enumerate() {
        number(x, &format!("{path}[{i}]"), true, Some(1.0), Some(999999.0))?;
    }
    Ok(())
}

fn section(v: &Value, path: &str) -> R {
    let Some(o) = v.as_object() else {
        return Err(format!("{path} 需為物件"));
    };
    require(o, &["type", "title"], path)?;
    for (k, x) in o {
        let p = format!("{path}.{k}");
        match k.as_str() {
            "type" => enum_of(x, &p, &SECTION_TYPES)?,
            "title" => string(x, &p, 1)?,
            "anchor" => str_pat(x, &p, valid_anchor)?,
            "dur" => number(x, &p, false, Some(0.0), None)?,
            "body" | "val" | "note" | "src" | "alt" | "caption" => string(x, &p, 0)?,
            "mode" => enum_of(x, &p, &MODES)?,
            "ids" => norad_list(x, &p, 0)?,
            "norads" => norad_list(x, &p, 1)?,
            "start" => str_pat(x, &p, valid_date)?,
            "group" => enum_of(x, &p, &GROUP_KEYS)?,
            "groups" => {
                for (i, g) in array(x, &p, 0)?.iter().enumerate() {
                    enum_of(g, &format!("{p}[{i}]"), &GROUP_KEYS)?;
                }
            }
            "n" => number(x, &p, true, Some(1.0), Some(60.0))?,
            "threshold_km" => number(x, &p, false, Some(1.0), Some(500.0))?,
            "url" => str_pat(x, &p, |s| s.starts_with('/'))?,
            "height" => number(x, &p, true, Some(200.0), None)?,
            "columns" | "row_anchors" => {
                for (i, c) in array(x, &p, 0)?.iter().enumerate() {
                    string(c, &format!("{p}[{i}]"), 0)?;
                }
            }
            "rows" => {
                for (i, r) in array(x, &p, 0)?.iter().enumerate() {
                    array(r, &format!("{p}[{i}]"), 0)?;
                }
            }
            "items" => {
                for (i, it) in array(x, &p, 0)?.iter().enumerate() {
                    let ip = format!("{p}[{i}]");
                    let io = it.as_object().ok_or_else(|| format!("{ip} 需為物件"))?;
                    require(io, &["label", "anchor"], &ip)?;
                }
            }
            "site" => str_pat(x, &p, valid_site)?,
            "qa" => {
                for (i, it) in array(x, &p, 1)?.iter().enumerate() {
                    let ip = format!("{p}[{i}]");
                    let io = it.as_object().ok_or_else(|| format!("{ip} 需為物件"))?;
                    require(io, &["q", "a"], &ip)?;
                    string(&io["q"], &format!("{ip}.q"), 1)?;
                    string(&io["a"], &format!("{ip}.a"), 1)?;
                }
            }
            _ => {}
        }
    }
    // allOf：依節型別要求的欄位（type 必為字串，前面已驗證）
    let ty = o["type"].as_str().unwrap_or_default();
    let need: &[&str] = match ty {
        "table" => &["columns", "rows"],
        "sat" => &["norads"],
        "embed" => &["url"],
        "toc" => &["items"],
        "positions" if o.get("mode").and_then(Value::as_str) == Some("ids") => &["ids"],
        "groupstats" | "isrres" | "radar" | "skyplot" => &["group"],
        "faq" => &["qa"],
        "image" => &["src"],
        _ => &[],
    };
    require(o, need, path)
}

/// 驗證整份故事；錯誤訊息供記錄
pub fn validate(d: &Value) -> R {
    let Some(o) = d.as_object() else {
        return Err("故事需為 JSON 物件".into());
    };
    require(o, &["id", "title", "sections"], "$")?;
    for (k, x) in o {
        match k.as_str() {
            "id" => str_pat(x, "$.id", valid_sid)?,
            "title" => string(x, "$.title", 1)?,
            "subtitle" | "hero_note" => string(x, &format!("$.{k}"), 0)?,
            "updated" => str_pat(x, "$.updated", valid_date)?,
            "sections" => {
                for (i, s) in array(x, "$.sections", 1)?.iter().enumerate() {
                    section(s, &format!("$.sections[{i}]"))?;
                }
            }
            _ => {}
        }
    }
    Ok(())
}
