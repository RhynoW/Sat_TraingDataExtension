//! 碎片連鎖命令列版：stdin 讀一個 JSON 請求，stdout 輸出與單機版 /api/games/breakup 相同的 JSON。
//!
//! 輸入：{"req": <BreakupReq>, "catalog": "<目錄檔路徑>"}
//!   目錄檔每行一個 JSON 陣列 [norad, name, purpose, line1, line2]（線上版 Flask 依自己的衛星索引產生）。
//! 輸出：成功時結果 JSON（結束碼 0）；請求或目錄錯誤時 {"error": "..."}（結束碼 2）。
//!
//! 計算核心與單機版共用 debris_engine.rs（單機版 RUST_SatDashboard/src/ 為唯一來源，
//! 線上版副本由 scenario-advanced01/tools/sync_debris.py 複製）。SGP4 初始化方式與單機版 physics.rs 相同
//! （WGS72、AFSPC 相容模式、修正檢查碼），母體與目錄物件在 t0 的狀態因此與單機版一致。

#[path = "../../src/debris_engine.rs"]
mod debris_engine;

use std::io::Read;

use chrono::{DateTime, NaiveDateTime, Utc};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::json;

use debris_engine::{self as eng, BreakupReq, CatIn, V3};

#[derive(Deserialize)]
struct Input {
    req: BreakupReq,
    catalog: String,
}

struct Sat {
    norad: u32,
    name: String,
    purpose: String,
    line1: String,
    prop: Option<(sgp4::Constants, NaiveDateTime)>,
}

/// 修正 TLE 行末檢查碼（與單機版 physics.rs 相同）
fn fix_checksum(line: &str) -> String {
    let b = line.as_bytes();
    if b.len() < 69 {
        return line.to_string();
    }
    let sum: u32 = b[..68].iter().map(|&c| match c { b'0'..=b'9' => (c - b'0') as u32, b'-' => 1, _ => 0 }).sum();
    let mut s = line[..68].to_string();
    s.push(char::from(b'0' + (sum % 10) as u8));
    s
}

fn prop(l1: &str, l2: &str) -> Option<(sgp4::Constants, NaiveDateTime)> {
    let (a, b) = (fix_checksum(l1.trim_end()), fix_checksum(l2.trim_end()));
    let el = sgp4::Elements::from_tle(None, a.as_bytes(), b.as_bytes()).ok()?;
    let c = sgp4::Constants::from_elements_afspc_compatibility_mode(&el).ok()?;
    Some((c, el.datetime))
}

/// 與單機版 games_debris.rs 的 sgp4_rv 相同：非有限值或半徑 < 地表 + 100 km 視為無法傳播
fn rv(s: &Sat, t: &DateTime<Utc>) -> Option<(V3, V3)> {
    let (c, ep) = s.prop.as_ref()?;
    let ns = (t.naive_utc() - *ep).num_nanoseconds()?;
    let p = c.propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9)).ok()?;
    let r = p.position;
    let n = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
    (r.iter().all(|v| v.is_finite()) && n > eng::R_EARTH_KM + 100.0).then_some((r, p.velocity))
}

fn load_catalog(path: &str) -> Result<Vec<Sat>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("讀不到目錄檔：{e}"))?;
    let rows: Vec<(u32, String, String, String, String)> = text
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).map_err(|e| format!("目錄檔格式錯誤：{e}")))
        .collect::<Result<_, _>>()?;
    Ok(rows
        .into_par_iter()
        .filter(|r| !r.3.is_empty() && !r.4.is_empty())
        .map(|(norad, name, purpose, l1, l2)| {
            let p = prop(&l1, &l2);
            Sat { norad, name, purpose, line1: l1.trim().to_string(), prop: p }
        })
        .collect())
}

fn go(inp: Input) -> Result<serde_json::Value, String> {
    let rq = &inp.req;
    let (years, accel, mass) = eng::check(rq)?;
    let sats = load_catalog(&inp.catalog)?;
    let t0 = eng::resolve_t0(rq, Utc::now())?;
    let parent = if let Some(o) = &rq.orbit {
        eng::custom_parent(o)
    } else {
        let p = sats.iter().find(|s| s.norad == rq.norad).ok_or("目錄中找不到這個 NORAD 編號")?;
        let (r, v) = rv(p, &t0).ok_or("這顆衛星目前無法傳播（TLE 失效或已再入）")?;
        eng::ParentIn { r, v, name: p.name.clone(), custom: false, norad: rq.norad }
    };
    let cats: Vec<CatIn> = sats
        .par_iter()
        .filter_map(|s| rv(s, &t0).map(|x| CatIn { norad: s.norad, name: s.name.clone(), purpose: s.purpose.clone(), line1: s.line1.clone(), rv: x }))
        .collect();
    eng::run(rq, years, accel, mass, t0, &parent, &cats)
}

fn main() {
    let mut buf = String::new();
    let res = std::io::stdin()
        .read_to_string(&mut buf)
        .map_err(|e| format!("讀取輸入失敗：{e}"))
        .and_then(|_| serde_json::from_str::<Input>(&buf).map_err(|e| format!("請求格式錯誤：{e}")))
        .and_then(go);
    match res {
        Ok(v) => println!("{v}"),
        Err(m) => {
            println!("{}", json!({ "error": m }));
            std::process::exit(2);
        }
    }
}
