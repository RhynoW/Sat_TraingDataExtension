//! 版本與聯絡資訊（主控台啟動訊息、`/api/about`、頁面頁尾共用）

use serde_json::{json, Value};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// 版本日期（台灣時間；build.rs 於重新建置時產生）
pub const BUILD_DATE: &str = env!("SATDASH_BUILD_DATE");
pub const CONTACT_NAME: &str = "Rhyno Wu";
pub const CONTACT_URL: &str = "https://www.linkedin.com/in/rhyno-wu-6b766771/";

pub fn json() -> Value {
    json!({
        "app": "ATRDC SatDashboard — Rust 單機版",
        "version": VERSION,
        "build_date": BUILD_DATE,
        "arch": std::env::consts::ARCH,
        "contact": {"name": CONTACT_NAME, "url": CONTACT_URL, "via": "LinkedIn"},
    })
}
