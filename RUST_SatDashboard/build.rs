// 1. 編譯內附之 astronomy-engine C 原始碼（MIT，Don Cross）供凌月預報之月球／太陽星曆使用
// 2. 版本日期 SATDASH_BUILD_DATE（台灣時間 YYYY-MM-DD）：程式或前端有變更而重新建置時更新；
//    可用環境變數 SATDASH_BUILD_DATE 指定（例如重現某一版）
use std::time::{SystemTime, UNIX_EPOCH};

/// Unix 日數 → (年, 月, 日)（Howard Hinnant civil_from_days）
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (yoe + era * 400 + if m <= 2 { 1 } else { 0 }, m, d)
}

fn main() {
    println!("cargo:rerun-if-changed=vendor/astronomy/astronomy.c");
    println!("cargo:rerun-if-changed=vendor/astronomy/astronomy.h");
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=web/ext");
    println!("cargo:rerun-if-changed=web/templates");
    println!("cargo:rerun-if-changed=Cargo.toml");
    println!("cargo:rerun-if-env-changed=SATDASH_BUILD_DATE");
    let date = std::env::var("SATDASH_BUILD_DATE").unwrap_or_else(|_| {
        let s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
        let (y, m, d) = civil((s + 8 * 3600).div_euclid(86_400));
        format!("{y:04}-{m:02}-{d:02}")
    });
    println!("cargo:rustc-env=SATDASH_BUILD_DATE={date}");

    cc::Build::new()
        .file("vendor/astronomy/astronomy.c")
        .warnings(false)
        .opt_level(2)
        .compile("astronomy");
}
