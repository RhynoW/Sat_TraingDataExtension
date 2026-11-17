//! 內嵌前端資產（HTML / JS / CSS / CesiumJS / 底圖 / Logo），單一執行檔即可離線運作。

use axum::body::Body;
use axum::http::{header, HeaderValue, Response, StatusCode};
use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "web/"]
pub struct Web;

pub const SSN_STATIONS_DEFAULT: &str = include_str!("../config/ssn_stations.geojson");

pub fn bytes_response(data: Vec<u8>, content_type: &str, max_age: u32) -> Response<Body> {
    let mut r = Response::new(Body::from(data));
    let h = r.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_str(content_type).unwrap());
    h.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_str(&format!("public, max-age={max_age}")).unwrap(),
    );
    r
}

pub fn text(status: StatusCode, msg: impl Into<String>) -> Response<Body> {
    let mut r = Response::new(Body::from(msg.into()));
    *r.status_mut() = status;
    r.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/plain; charset=utf-8"),
    );
    r
}

fn content_type(path: &str) -> String {
    let m = mime_guess::from_path(path).first_or_octet_stream();
    let s = m.essence_str();
    if s.starts_with("text/") || s == "application/javascript" || s == "application/json" {
        format!("{s}; charset=utf-8")
    } else {
        s.to_string()
    }
}

/// 以內嵌路徑回應（不存在回 404）
pub fn serve(path: &str, max_age: u32) -> Response<Body> {
    if path.contains("..") {
        return text(StatusCode::FORBIDDEN, "Forbidden");
    }
    match Web::get(path) {
        Some(f) => bytes_response(f.data.into_owned(), &content_type(path), max_age),
        None => text(StatusCode::NOT_FOUND, format!("找不到資源：{path}")),
    }
}

pub fn get(path: &str) -> Option<Vec<u8>> {
    Web::get(path).map(|f| f.data.into_owned())
}

/// 主頁 HTML（替換快取破壞參數）
pub fn globe_html() -> String {
    let raw = get("templates/globe.html").unwrap_or_default();
    String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION"))
}

/// 尚未移植之頁面
pub fn not_ported_html(page: &str) -> String {
    format!(
        r#"<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>尚未移植 — SatDashboard</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0d1117;color:#c9d1d9;font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif}}
.box{{max-width:520px;padding:32px;border:1px solid #30363d;border-radius:10px;background:#161b22}}
h1{{font-size:20px;margin:0 0 12px}} code{{color:#79c0ff}} a{{color:#58a6ff}}
</style></head><body><div class="box">
<h1>🛰 此頁面尚未移植至 Rust 單機版</h1>
<p>頁面 <code>{page}</code> 屬於後續階段。目前已提供：3D 地球儀（全目錄位置、搜尋、近距離配對篩選）、台北覆蓋分析（含天球與凌月預報）、RPO 相對接近 3D、全球海纜態勢。</p>
<p>完整功能請使用 Python 版（scenario-advanced01）。</p>
<p><a href="/">← 回到 3D 地球儀</a></p>
</div></body></html>"#
    )
}
