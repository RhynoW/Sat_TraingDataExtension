//! 使用者自訂資料：TLE、衛星目錄（CSV）、NORAD 監測清單（CSV）。
//! 對應 Python ingestion/user_defined.py；放檔案即生效（索引重建時重讀）。

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct UserTle {
    pub name: String,
    pub line1: String,
    pub line2: String,
    pub source_file: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct TrackEntry {
    pub norad_id: u32,
    pub alias: String,
    pub priority: String,
    pub priority_label: String,
    pub color: String,
    pub enabled: bool,
    pub notes: String,
    pub source_file: String,
}

const A5: &str = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ";

/// TLE 第 3–7 欄 NORAD ID（Alpha-5 相容，支援 100000–339999）
pub fn tle_norad_id(line: &str) -> Option<u32> {
    let s = line.get(2..7)?.trim().to_uppercase();
    let first = s.chars().next()?;
    if first.is_ascii_digit() {
        return s.parse().ok();
    }
    let tens = A5.find(first)?;
    if tens < 10 || !s[1..].chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(tens as u32 * 10000 + s[1..].parse::<u32>().ok()?)
}

fn read_text(p: &Path) -> std::io::Result<String> {
    let t = std::fs::read_to_string(p)?;
    Ok(t.strip_prefix('\u{feff}').map(str::to_string).unwrap_or(t))
}

fn list_files(dir: &Path, exts: &[&str]) -> Vec<PathBuf> {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return vec![];
    };
    let mut v: Vec<PathBuf> = rd
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.is_file()
                && p.extension()
                    .and_then(|e| e.to_str())
                    .map(|e| exts.iter().any(|x| x.eq_ignore_ascii_case(e)))
                    .unwrap_or(false)
        })
        .collect();
    v.sort();
    v
}

fn file_name(p: &Path) -> String {
    p.file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// 解析單一檔案：2 行 / 3 行 TLE 混用，# 開頭為註解。
pub fn parse_tle_text(text: &str, source: &str) -> BTreeMap<u32, UserTle> {
    let mut out = BTreeMap::new();
    let mut pending_name = String::new();
    let mut pending_l1 = String::new();
    for raw in text.lines() {
        let line = raw.trim_end();
        if line.trim().is_empty() || line.trim_start().starts_with('#') {
            continue;
        }
        if line.starts_with("1 ") && line.len() >= 69 {
            pending_l1 = line.to_string();
            continue;
        }
        if line.starts_with("2 ") && line.len() >= 69 {
            if pending_l1.is_empty() {
                tracing::warn!("user TLE ({source}): line2 前缺 line1，略過");
                continue;
            }
            let (n1, n2) = (tle_norad_id(&pending_l1), tle_norad_id(line));
            match (n1, n2) {
                (Some(a), Some(b)) if a == b => {
                    out.insert(
                        a,
                        UserTle {
                            name: std::mem::take(&mut pending_name),
                            line1: std::mem::take(&mut pending_l1),
                            line2: line.to_string(),
                            source_file: source.to_string(),
                        },
                    );
                }
                _ => {
                    tracing::warn!("user TLE ({source}): line1/line2 NORAD 不一致，略過");
                    pending_l1.clear();
                    pending_name.clear();
                }
            }
            continue;
        }
        let mut name = line.trim();
        if let Some(s) = name.strip_prefix("0 ") {
            name = s.trim();
        }
        pending_name = name.to_string();
        pending_l1.clear();
    }
    out
}

pub fn load_user_tles(dir: &Path) -> BTreeMap<u32, UserTle> {
    let mut out = BTreeMap::new();
    for f in list_files(dir, &["tle", "txt"]) {
        match read_text(&f) {
            Ok(t) => out.extend(parse_tle_text(&t, &file_name(&f))),
            Err(e) => tracing::error!("user TLE 檔讀取失敗 {}: {e}", f.display()),
        }
    }
    if !out.is_empty() {
        tracing::info!("使用者自訂 TLE：{} 顆", out.len());
    }
    out
}

/// 讀 CSV 為 (header→value) 列；容忍欄數不一、BOM。
fn read_csv_rows(p: &Path) -> anyhow::Result<Vec<HashMap<String, String>>> {
    let text = read_text(p)?;
    let mut rdr = csv::ReaderBuilder::new()
        .flexible(true)
        .trim(csv::Trim::All)
        .from_reader(text.as_bytes());
    let headers: Vec<String> = rdr.headers()?.iter().map(|h| h.trim().to_string()).collect();
    let mut rows = Vec::new();
    for rec in rdr.records() {
        let rec = rec?;
        let mut m = HashMap::new();
        for (i, h) in headers.iter().enumerate() {
            if h.is_empty() {
                continue;
            }
            m.insert(h.clone(), rec.get(i).unwrap_or("").trim().to_string());
        }
        rows.push(m);
    }
    Ok(rows)
}

/// 使用者自訂衛星目錄：{norad_id: {欄位: 值}}（含 source_file）
pub fn load_user_catalogue(dir: &Path) -> BTreeMap<u32, HashMap<String, String>> {
    let mut out = BTreeMap::new();
    for f in list_files(dir, &["csv"]) {
        match read_csv_rows(&f) {
            Ok(rows) => {
                for mut row in rows {
                    let Some(nid) = row.get("norad_id").and_then(|v| v.parse::<u32>().ok()) else {
                        continue;
                    };
                    row.remove("norad_id");
                    row.insert("source_file".into(), file_name(&f));
                    out.insert(nid, row);
                }
            }
            Err(e) => tracing::error!("user catalogue 讀取失敗 {}: {e}", f.display()),
        }
    }
    out
}

const TRACK_AUTO_COLORS: [&str; 10] = [
    "#FF4081", "#FFD740", "#00E5FF", "#69F0AE", "#B388FF", "#FF8A65", "#4FC3F7", "#F4FF81", "#FF80AB",
    "#A7FFEB",
];

fn norm_priority(raw: &str) -> &'static str {
    match raw.trim().to_lowercase().as_str() {
        "高" | "high" | "h" => "high",
        "低" | "low" | "l" => "low",
        _ => "medium",
    }
}

fn priority_order(p: &str) -> u8 {
    match p {
        "high" => 0,
        "low" => 2,
        _ => 1,
    }
}

pub fn load_tracking_list(dir: &Path) -> Vec<TrackEntry> {
    let mut by_id: BTreeMap<u32, TrackEntry> = BTreeMap::new();
    for f in list_files(dir, &["csv"]) {
        let rows = match read_csv_rows(&f) {
            Ok(r) => r,
            Err(e) => {
                tracing::error!("tracking 清單讀取失敗 {}: {e}", f.display());
                continue;
            }
        };
        for row in rows {
            let get = |k: &str| row.get(k).cloned().unwrap_or_default();
            let Ok(nid) = get("norad_id").parse::<u32>() else {
                continue;
            };
            let pr_raw = get("priority");
            let enabled_raw = {
                let e = get("enabled").to_uppercase();
                if e.is_empty() {
                    "Y".to_string()
                } else {
                    e
                }
            };
            by_id.insert(
                nid,
                TrackEntry {
                    norad_id: nid,
                    alias: get("alias"),
                    priority: norm_priority(&pr_raw).into(),
                    priority_label: if pr_raw.is_empty() { "中".into() } else { pr_raw },
                    color: get("color"),
                    enabled: !matches!(enabled_raw.as_str(), "N" | "NO" | "0" | "FALSE" | "否"),
                    notes: get("notes"),
                    source_file: file_name(&f),
                },
            );
        }
    }
    let mut items: Vec<TrackEntry> = by_id.into_values().collect();
    items.sort_by_key(|x| (priority_order(&x.priority), x.norad_id));
    for (i, it) in items.iter_mut().enumerate() {
        if it.color.is_empty() {
            it.color = TRACK_AUTO_COLORS[i % TRACK_AUTO_COLORS.len()].into();
        }
    }
    items
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alpha5() {
        assert_eq!(tle_norad_id("1 25544U 98067A"), Some(25544));
        assert_eq!(tle_norad_id("1 A0001U 98067A"), Some(100001));
        assert_eq!(tle_norad_id("1 Z9999U 98067A"), Some(339999));
    }

    #[test]
    fn parse_3le() {
        let t = "# c\n0 ISS (ZARYA)\n1 25544U 98067A   20194.88612269 -.00002218  00000-0 -31515-4 0  9992\n2 25544  51.6461 221.2784 0001413  89.1723 280.4612 15.49507896236008\n";
        let m = parse_tle_text(t, "x.tle");
        assert_eq!(m.len(), 1);
        assert_eq!(m[&25544].name, "ISS (ZARYA)");
    }
}
