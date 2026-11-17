//! 衛星分類規則與前端顏色（對應 Python ingestion/metadata.py 與 api/colors.py）。

use chrono::{DateTime, NaiveDate, Utc};
use std::collections::HashSet;
use std::path::Path;

pub const DEFAULT_RULES_YAML: &str = include_str!("../config/classification_rules.yaml");

#[derive(Debug, Clone)]
pub struct Rules {
    /// (關鍵字, 國別標籤)，保留 YAML 順序（先命中者優先）
    pub country_map: Vec<(String, String)>,
    pub known_labels: HashSet<String>,
    /// (星座標籤, 大寫關鍵字)
    pub constellation_rules: Vec<(String, Vec<String>)>,
}

impl Rules {
    pub fn load(override_path: &Path) -> Self {
        if override_path.is_file() {
            match std::fs::read_to_string(override_path)
                .map_err(anyhow::Error::from)
                .and_then(|t| Self::parse(&t))
            {
                Ok(r) => {
                    tracing::info!("分類規則載入自 {}", override_path.display());
                    return r;
                }
                Err(e) => tracing::warn!("{} 載入失敗，改用內建預設：{e}", override_path.display()),
            }
        }
        Self::parse(DEFAULT_RULES_YAML).expect("內建 classification_rules.yaml 格式錯誤")
    }

    fn parse(text: &str) -> anyhow::Result<Self> {
        let v: serde_yaml::Value = serde_yaml::from_str(text)?;
        let mut country_map = Vec::new();
        if let Some(m) = v.get("country_map").and_then(|m| m.as_mapping()) {
            for (k, val) in m {
                if let (Some(k), Some(val)) = (k.as_str(), val.as_str()) {
                    country_map.push((k.to_string(), val.to_string()));
                }
            }
        }
        let mut constellation_rules = Vec::new();
        if let Some(seq) = v.get("constellation_rules").and_then(|s| s.as_sequence()) {
            for item in seq {
                let label = item.get("label").and_then(|l| l.as_str());
                let kws = item.get("keywords").and_then(|k| k.as_sequence());
                if let (Some(label), Some(kws)) = (label, kws) {
                    let kws = kws
                        .iter()
                        .filter_map(|k| match k {
                            serde_yaml::Value::String(s) => Some(s.to_uppercase()),
                            serde_yaml::Value::Number(n) => Some(n.to_string()),
                            _ => None,
                        })
                        .collect();
                    constellation_rules.push((label.to_string(), kws));
                }
            }
        }
        if country_map.is_empty() && constellation_rules.is_empty() {
            anyhow::bail!("country_map 與 constellation_rules 皆為空");
        }
        let known_labels = country_map.iter().map(|(_, v)| v.clone()).collect();
        Ok(Self {
            country_map,
            known_labels,
            constellation_rules,
        })
    }

    pub fn classify_country(&self, source_code: Option<&str>) -> String {
        let sc = match source_code.map(str::trim) {
            Some(s) if !s.is_empty() => s,
            _ => return "不明".into(),
        };
        if self.known_labels.contains(sc) {
            return sc.to_string();
        }
        let low = sc.to_lowercase();
        for (k, label) in &self.country_map {
            if low.contains(&k.to_lowercase()) {
                return label.clone();
            }
        }
        "其他".into()
    }

    pub fn classify_constellation(&self, name: &str) -> Option<String> {
        let n = name.to_uppercase();
        self.constellation_rules
            .iter()
            .find(|(_, kws)| kws.iter().any(|k| n.contains(k.as_str())))
            .map(|(l, _)| l.clone())
    }
}

pub fn classify_purpose(name: &str) -> String {
    let n = name.to_uppercase();
    if n.contains(" DEB") || n.contains("DEBRIS") {
        return "碎片".into();
    }
    if n.contains(" R/B") || n.contains(" RB") || n.contains("ROCKET BODY") {
        return "火箭體".into();
    }
    if n.contains("OBJECT") {
        return "不明物體".into();
    }
    "有效載荷".into()
}

/// 解析 "YYYY-MM-DD..." 前 10 字元為 UTC 日期
pub fn parse_date(s: &str) -> Option<DateTime<Utc>> {
    let s = s.trim();
    let d = NaiveDate::parse_from_str(s.get(..10)?, "%Y-%m-%d").ok()?;
    Some(d.and_hms_opt(0, 0, 0)?.and_utc())
}

pub fn classify_era(launch: Option<DateTime<Utc>>, intl_code: Option<&str>) -> String {
    let launch = launch.or_else(|| {
        let ic = intl_code?.trim();
        let y: i32 = ic.get(..4)?.parse().ok()?;
        Some(NaiveDate::from_ymd_opt(y, 1, 1)?.and_hms_opt(0, 0, 0)?.and_utc())
    });
    let Some(l) = launch else { return "不明".into() };
    let days = (Utc::now() - l).num_days();
    if days < 365 {
        "< 1 年".into()
    } else if days < 365 * 5 {
        "1–5 年".into()
    } else if days < 365 * 10 {
        "5–10 年".into()
    } else {
        "> 10 年".into()
    }
}

pub const ERA_ORDER: [&str; 5] = ["< 1 年", "1–5 年", "5–10 年", "> 10 年", "不明"];

pub fn get_color(ftype: &str, label: &str) -> &'static str {
    let table: &[(&str, &str)] = match ftype {
        "purpose" => &[
            ("有效載荷", "#4CAF50"),
            ("碎片", "#FF9800"),
            ("火箭體", "#9E9E9E"),
            ("不明物體", "#607D8B"),
        ],
        "country" => &[
            ("美國", "#3F51B5"),
            ("俄羅斯/蘇聯", "#F44336"),
            ("中國", "#FF5722"),
            ("英國", "#2196F3"),
            ("法國", "#9C27B0"),
            ("日本", "#E91E63"),
            ("印度", "#FF9800"),
            ("ESA", "#00BCD4"),
            ("其他", "#78909C"),
            ("不明", "#455A64"),
        ],
        "constellation" => &[
            ("Starlink", "#1565C0"),
            ("OneWeb", "#00897B"),
            ("Kuiper", "#FF8F00"),
            ("千帆/Qianfan", "#C62828"),
            ("國網/Guowang", "#D32F2F"),
            ("Starshield", "#455A64"),
            ("Iridium", "#558B2F"),
            ("Globalstar", "#6A1B9A"),
            ("Planet/Flock", "#2E7D32"),
            ("Spire", "#00838F"),
            ("PWSA/SDA", "#5D4037"),
            ("GeeSat/Geespace", "#7B1FA2"),
            ("中國IoT(天啟/行雲)", "#8D6E63"),
            ("吉林/Jilin", "#AD1457"),
            ("Formosat-7", "#00ACC1"),
            ("遙感/Yaogan", "#B71C1C"),
            ("高分", "#E64A19"),
            ("風雲", "#0277BD"),
            ("其他衛星", "#546E7A"),
        ],
        "era" => &[
            ("< 1 年", "#F44336"),
            ("1–5 年", "#FF9800"),
            ("5–10 年", "#4CAF50"),
            ("> 10 年", "#607D8B"),
            ("不明", "#455A64"),
        ],
        _ => &[],
    };
    table
        .iter()
        .find(|(k, _)| *k == label)
        .map(|(_, c)| *c)
        .unwrap_or("#78909C")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn purpose_rules() {
        assert_eq!(classify_purpose("COSMOS 1408 DEB"), "碎片");
        assert_eq!(classify_purpose("CZ-6A R/B"), "火箭體");
        assert_eq!(classify_purpose("OBJECT A"), "不明物體");
        assert_eq!(classify_purpose("STARLINK-1234"), "有效載荷");
    }

    #[test]
    fn default_rules_parse() {
        let r = Rules::parse(DEFAULT_RULES_YAML).unwrap();
        assert_eq!(r.classify_country(Some("United States (US)")), "美國");
        assert_eq!(r.classify_country(None), "不明");
        assert_eq!(
            r.classify_constellation("STARLINK-31000").as_deref(),
            Some("Starlink")
        );
        assert_eq!(r.classify_constellation("ISS (ZARYA)"), None);
    }
}
