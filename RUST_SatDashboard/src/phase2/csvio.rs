//! 批次物件 CSV 匯入與結果 CSV 匯出（與 Python csvio.py 相同列、錯誤代碼與行號；
//! 以 testdata/batch_secondaries.csv 共用案例比對）。
//!
//! CSV 解析仿 Python `csv.reader`（預設方言、非 strict）：引號欄位可跨行（跨行時直接接續，不補換行），
//! 行號為 Python `enumerate(reader, start=1)` 的記錄序號。

use serde_json::{json, Map, Value};

pub const COLUMNS: [&str; 8] = ["norad_id", "name", "line1", "line2", "hbr_m", "sigma_r_km", "sigma_t_km", "sigma_n_km"];
pub const MAX_ROWS: usize = 500;

/// Python csv.reader（delimiter ','、quotechar '"'、doublequote、非 strict）逐記錄解析
fn py_csv_records(lines: &[&str]) -> Vec<Vec<String>> {
    #[derive(PartialEq, Clone, Copy)]
    enum St {
        StartField,
        InField,
        InQuoted,
        QuoteInQuoted,
    }
    let mut out = Vec::new();
    let mut rec: Vec<String> = Vec::new();
    let mut field = String::new();
    let mut st = St::StartField;
    let mut pending = false; // 前一行在引號內結束，記錄延續
    for line in lines {
        if !pending {
            rec = Vec::new();
            field = String::new();
            st = St::StartField;
        }
        for ch in line.chars() {
            match st {
                St::StartField => {
                    if ch == '"' {
                        st = St::InQuoted;
                    } else if ch == ',' {
                        rec.push(std::mem::take(&mut field));
                    } else {
                        field.push(ch);
                        st = St::InField;
                    }
                }
                St::InField => {
                    if ch == ',' {
                        rec.push(std::mem::take(&mut field));
                        st = St::StartField;
                    } else {
                        field.push(ch);
                    }
                }
                St::InQuoted => {
                    if ch == '"' {
                        st = St::QuoteInQuoted;
                    } else {
                        field.push(ch);
                    }
                }
                St::QuoteInQuoted => {
                    if ch == '"' {
                        field.push('"');
                        st = St::InQuoted;
                    } else if ch == ',' {
                        rec.push(std::mem::take(&mut field));
                        st = St::StartField;
                    } else {
                        field.push(ch);
                        st = St::InField;
                    }
                }
            }
        }
        if st == St::InQuoted {
            pending = true;
            continue;
        }
        pending = false;
        // 行尾：空行 → []；否則收尾最後一欄
        if !(rec.is_empty() && field.is_empty() && st == St::StartField) {
            rec.push(std::mem::take(&mut field));
        }
        out.push(std::mem::take(&mut rec));
    }
    if pending {
        rec.push(field);
        out.push(rec);
    }
    out
}

/// Python int()（已 strip）：可選正負號、數字間可有單一底線
fn py_int(s: &str) -> Option<i64> {
    let t = s.trim();
    let (sign, body) = match t.strip_prefix('-') {
        Some(b) => (-1, b),
        None => (1, t.strip_prefix('+').unwrap_or(t)),
    };
    if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
        return None;
    }
    let digits: String = body.chars().filter(|c| *c != '_').collect();
    if !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    digits.parse::<i64>().ok().map(|v| sign * v)
}

/// Python float()（已 strip）
fn py_float(s: &str) -> Option<f64> {
    let t = s.trim();
    if t.is_empty() || t.contains("__") || t.starts_with('_') || t.ends_with('_') {
        return None;
    }
    let cleaned: String = if t.contains('_') {
        let cs: Vec<char> = t.chars().collect();
        let mut o = String::new();
        for (i, c) in cs.iter().enumerate() {
            if *c == '_' {
                let ok = i > 0 && i + 1 < cs.len() && cs[i - 1].is_ascii_digit() && cs[i + 1].is_ascii_digit();
                if !ok {
                    return None;
                }
            } else {
                o.push(*c);
            }
        }
        o
    } else {
        t.to_string()
    };
    cleaned.parse::<f64>().ok()
}

fn err(line: usize, code: &str, message: String) -> Value {
    json!({"line": line, "code": code, "message": message})
}

pub fn parse_secondaries(text: &str) -> Value {
    let norm = text.replace("\r\n", "\n").replace('\r', "\n");
    let lines: Vec<&str> = norm.split('\n').collect();
    let mut rows: Vec<Value> = Vec::new();
    let mut errors: Vec<Value> = Vec::new();
    let mut header: Option<Vec<String>> = None;
    let mut seen: Vec<(Option<i64>, Option<String>)> = Vec::new();
    for (idx, rec) in py_csv_records(&lines).into_iter().enumerate() {
        let lineno = idx + 1;
        if rec.is_empty() || rec.iter().all(|c| c.trim().is_empty()) || rec[0].trim_start().starts_with('#') {
            continue;
        }
        let Some(hdr) = &header else {
            let h: Vec<String> = rec.iter().map(|c| c.trim().to_lowercase()).collect();
            for c in h.iter().filter(|c| !COLUMNS.contains(&c.as_str())) {
                errors.push(err(lineno, "CSV_UNKNOWN_COLUMN", format!("未知欄位 {c}（已忽略）")));
            }
            let has = |k: &str| h.iter().any(|c| c == k);
            if !has("norad_id") && !(has("line1") && has("line2")) {
                errors.push(err(lineno, "CSV_NO_ID_COLUMN", "需要 norad_id 欄或 line1＋line2 欄".into()));
                return json!({"rows": [], "errors": errors});
            }
            header = Some(h);
            continue;
        };
        if rows.len() >= MAX_ROWS {
            errors.push(err(lineno, "CSV_TOO_MANY_ROWS", format!("超過 {MAX_ROWS} 列，其後略過")));
            break;
        }
        let mut d: std::collections::HashMap<&str, String> = std::collections::HashMap::new();
        for i in 0..hdr.len().min(rec.len()) {
            if COLUMNS.contains(&hdr[i].as_str()) {
                d.insert(hdr[i].as_str(), rec[i].trim().to_string());
            }
        }
        let get = |k: &str| d.get(k).cloned().unwrap_or_default();
        let mut row = Map::new();
        let mut bad = false;
        let nid = get("norad_id");
        if !nid.is_empty() {
            match py_int(&nid) {
                Some(v) => {
                    row.insert("norad_id".into(), json!(v));
                }
                None => {
                    errors.push(err(lineno, "CSV_BAD_NUMBER", format!("norad_id 非整數：{nid}")));
                    bad = true;
                }
            }
        }
        let (l1, l2) = (get("line1"), get("line2"));
        if !l1.is_empty() || !l2.is_empty() {
            if l1.chars().count() != 69 || l2.chars().count() != 69 || !l1.starts_with("1 ") || !l2.starts_with("2 ") {
                errors.push(err(lineno, "CSV_BAD_TLE", "TLE 兩行須各 69 字元，且以 '1 '、'2 ' 開頭".into()));
                bad = true;
            } else {
                row.insert("line1".into(), json!(l1));
                row.insert("line2".into(), json!(l2));
                if !row.contains_key("norad_id") {
                    let id: String = l1.chars().skip(2).take(5).collect();
                    if let Some(v) = py_int(&id) {
                        row.insert("norad_id".into(), json!(v));
                    }
                }
            }
        }
        if !bad && !row.contains_key("norad_id") && !row.contains_key("line1") {
            errors.push(err(lineno, "CSV_MISSING_ID_OR_TLE", "需要 norad_id 或 TLE".into()));
            bad = true;
        }
        for k in ["hbr_m", "sigma_r_km", "sigma_t_km", "sigma_n_km"] {
            let v = get(k);
            if !v.is_empty() {
                match py_float(&v) {
                    Some(x) if x > 0.0 => {
                        row.insert(k.into(), json!(x));
                    }
                    _ => {
                        errors.push(err(lineno, "CSV_BAD_NUMBER", format!("{k} 須為正數：{v}")));
                        bad = true;
                    }
                }
            }
        }
        let name = get("name");
        if !name.is_empty() {
            row.insert("name".into(), json!(name));
        }
        if bad {
            continue;
        }
        let key = (row.get("norad_id").and_then(Value::as_i64), row.get("line1").and_then(|v| v.as_str().map(String::from)));
        if seen.contains(&key) {
            let shown = row.get("norad_id").map(|v| v.to_string()).unwrap_or_else(|| "None".into());
            errors.push(err(lineno, "CSV_DUPLICATE", format!("重複物件 {shown}（已略過）")));
            continue;
        }
        seen.push(key);
        row.insert("line".into(), json!(lineno));
        rows.push(Value::Object(row));
    }
    if header.is_none() {
        errors.push(err(0, "CSV_EMPTY", "沒有資料".into()));
    }
    json!({"rows": rows, "errors": errors})
}

pub const EVENT_COLUMNS: [&str; 15] = [
    "primary_norad", "secondary_norad", "secondary_name", "tca_utc", "miss_km", "v_rel_kms", "miss_r_km", "miss_t_km",
    "miss_n_km", "approach_angle_deg", "pc_foster", "pc_chan", "applicability", "flag", "covariance_mode",
];

/// Python f"{x:.6e}"：指數至少兩位、帶正負號
pub fn py_exp6(x: f64) -> String {
    if !x.is_finite() {
        return if x.is_nan() { "nan".into() } else if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let s = format!("{x:.6e}");
    let (mant, exp) = s.split_once('e').unwrap();
    let e: i32 = exp.parse().unwrap();
    format!("{mant}e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs())
}

fn py_fixed(x: f64, prec: usize) -> String {
    if !x.is_finite() {
        return if x.is_nan() { "nan".into() } else if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    format!("{x:.prec$}")
}

/// Python str()：None → ''，整數不帶小數點，其餘照 JSON 數值／字串
fn py_str(v: Option<&Value>) -> String {
    match v {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Bool(b)) => if *b { "True".into() } else { "False".into() },
        Some(x) => x.to_string(),
    }
}

fn csv_field(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

pub fn events_to_csv(events: &[Value]) -> String {
    let mut out = EVENT_COLUMNS.join(",");
    out.push('\n');
    let num = |v: &Value| v.as_f64().unwrap_or(f64::NAN);
    for e in events {
        let pc = e.get("pc").filter(|p| p.is_object());
        let rtn = e.get("miss_rtn_km").and_then(Value::as_array);
        let mut f: Vec<String> = vec![
            py_str(e.get("primary_norad")),
            py_str(e.get("secondary_norad")),
            py_str(e.get("secondary_name")),
            py_str(e.get("tca_utc")),
            py_fixed(num(&e["miss_km"]), 6),
            py_fixed(num(&e["v_rel_kms"]), 6),
        ];
        for i in 0..3 {
            f.push(match rtn.and_then(|a| a.get(i)).and_then(Value::as_f64) {
                Some(x) => py_fixed(x, 6),
                None => String::new(),
            });
        }
        f.push(py_fixed(num(&e["approach_angle_deg"]), 3));
        for k in ["foster", "chan"] {
            f.push(match pc.and_then(|p| p.get(k)).and_then(Value::as_f64) {
                Some(x) => py_exp6(x),
                None => String::new(),
            });
        }
        f.push(py_str(e.get("applicability").and_then(|a| a.get("status"))));
        f.push(py_str(e.get("flag")));
        f.push(py_str(pc.and_then(|p| p.get("covariance_mode"))));
        let line: Vec<String> = f.iter().map(|s| csv_field(s)).collect();
        out.push_str(&line.join(","));
        out.push('\n');
    }
    out
}
