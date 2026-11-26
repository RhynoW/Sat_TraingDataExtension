//! 網路圖磚疊圖代理（圖資目錄沿用 Rust_WMTS_Server 的 static/layers.js）。
//!
//! Cesium 把圖磚當 WebGL 貼圖，遠端未回 CORS 標頭就無法使用（Leaflet 用 <img> 沒有此限制），
//! 因此由本機後端代理：補 CORS、磁碟快取（看過的區域離線可用）、同時連線數上限。
//! 只放行 map_layers.js 內出現的網域，避免成為開放代理。
//!
//!   GET /api/tiles/xyz/{z}/{x}/{y}?t=<base64url 樣板>                  XYZ / WMTS RESTful 樣板
//!   GET /api/tiles/wms/{z}/{x}/{y}?t=<base64url 服務網址>&layers=…     WMS GetMap（EPSG:3857）

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, Response, StatusCode};
use axum::routing::get;
use axum::Router;
use base64::Engine;
use once_cell::sync::Lazy;
use sha2::{Digest, Sha256};
use tokio::sync::Semaphore;

use crate::state::AppState;

type Resp = Response<Body>;

const CATALOG_JS: &str = include_str!("../web/static/js/map_layers.js");
const CACHE_TTL: Duration = Duration::from_secs(30 * 86400);
const UPSTREAM_CONCURRENCY: usize = 8;
const TRANSPARENT_PNG: [u8; 68] = [
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 31,
    21, 196, 137, 0, 0, 0, 11, 73, 68, 65, 84, 120, 156, 99, 96, 0, 2, 0, 0, 5, 0, 1, 122, 94, 171, 63, 0, 0,
    0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
];

/// 放行網域：map_layers.js 中所有 http(s) 網址的主機（排除 localhost）
static ALLOWED_HOSTS: Lazy<HashSet<String>> = Lazy::new(|| {
    let mut set = HashSet::new();
    for scheme in ["https://", "http://"] {
        for part in CATALOG_JS.split(scheme).skip(1) {
            let host: String = part
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == '.' || *c == '-' || *c == ':')
                .collect();
            let host = host.split(':').next().unwrap_or("").to_ascii_lowercase();
            if host.contains('.') && host != "localhost" && !host.starts_with("127.") {
                set.insert(host);
            }
        }
    }
    for h in EXTRA_HOSTS {
        set.insert((*h).to_string());
    }
    set
});

/// 圖資目錄以外、本程式內建圖層使用之網域（Himawari：NASA GIBS）
const EXTRA_HOSTS: &[&str] = &["gibs.earthdata.nasa.gov"];

/// Himawari AHI 全圓盤（NASA GIBS 重投影為 Web Mercator，每 10 分鐘）
pub const HIMAWARI_LAYERS: &[(&str, &str)] = &[
    (
        "Himawari_AHI_Band13_Clean_Infrared",
        "GoogleMapsCompatible_Level6",
    ),
    (
        "Himawari_AHI_Band3_Red_Visible_1km",
        "GoogleMapsCompatible_Level7",
    ),
    ("Himawari_AHI_Air_Mass", "GoogleMapsCompatible_Level6"),
];
const GIBS: &str = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";

static HIMA_LATEST: Lazy<parking_lot::Mutex<HashMap<String, (std::time::Instant, String)>>> =
    Lazy::new(|| parking_lot::Mutex::new(HashMap::new()));

static CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .user_agent(concat!(
            "SatDashboard-Rust/",
            env!("CARGO_PKG_VERSION"),
            " (standalone tile viewer)"
        ))
        .build()
        .expect("reqwest client")
});

/// 代理使用者提供的圖磚網址專用（資安檢測 M-1）：每一次轉址都重新檢查允許清單，最多 5 次
static TILE_CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::custom(|a| {
            if a.previous().len() >= 5 || !host_allowed(a.url().as_str()) {
                a.stop()
            } else {
                a.follow()
            }
        }))
        .user_agent(concat!(
            "SatDashboard-Rust/",
            env!("CARGO_PKG_VERSION"),
            " (standalone tile viewer)"
        ))
        .build()
        .expect("reqwest client")
});

static LIMIT: Lazy<Semaphore> = Lazy::new(|| Semaphore::new(UPSTREAM_CONCURRENCY));

pub fn cache_dir() -> PathBuf {
    if let Some(d) = std::env::var_os("SATDASH_TILE_CACHE") {
        return PathBuf::from(d);
    }
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir)
        .join("SatDashboard")
        .join("tile_cache")
}

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/tiles/xyz/{z}/{x}/{y}", get(xyz))
        .route("/api/tiles/wms/{z}/{x}/{y}", get(wms))
        .route("/api/tiles/info", get(info))
        .route("/api/himawari/latest", get(himawari_latest))
        .route("/api/himawari/jma_latest", get(jma_latest))
        .route("/api/himawari/jma_img", get(jma_img))
}

// ── JMA 氣象衛星中心（MSC）全圓盤影像：約落後 10~20 分鐘 ───────────────────────────
// https://www.data.jma.go.jp/mscweb/data/himawari/list_fd_.html
// 檔名只有時分（img/fd_/fd__<band>_HHMM.jpg），每天覆蓋；以 Last-Modified 判斷哪一格是今天的最新影像。
// 影像為 601×601 的地球同步視角（已畫海岸線與經緯網），不重投影到地球儀上，只在面板顯示與下載。
const JMA_FD: &str = "https://www.data.jma.go.jp/mscweb/data/himawari/img/fd_";

/// 面板提供的波段（JMA 代碼, 說明）
pub const JMA_BANDS: &[(&str, &str)] = &[
    ("b13", "紅外 B13（10.4 µm，晝夜皆可）"),
    ("b03", "可見光 B03（0.64 µm，僅白天）"),
    ("b08", "水氣 B08（6.2 µm）"),
    ("b07", "短波紅外 B07（3.9 µm）"),
    ("tre", "真彩色 True Color Reproduction（白天）"),
    ("dnc", "日間自然色 Day Natural Color"),
    ("arm", "氣團 RGB（Airmass）"),
    ("snd", "Sandwich（對流雲頂）"),
    ("ngt", "夜間微物理 Night Microphysics"),
    ("dst", "沙塵 RGB（Dust）"),
];

static JMA_LATEST: Lazy<parking_lot::Mutex<HashMap<String, (std::time::Instant, serde_json::Value)>>> =
    Lazy::new(|| parking_lot::Mutex::new(HashMap::new()));

fn jma_band(q: &HashMap<String, String>) -> &'static str {
    let b = q.get("band").map(String::as_str).unwrap_or("b13");
    JMA_BANDS.iter().find(|(k, _)| *k == b).map(|(k, _)| *k).unwrap_or("b13")
}

/// 最新一格：從現在往回逐格（10 分鐘）HEAD，Last-Modified 落在該格時刻之後 0~60 分鐘者即今天的影像（快取 2 分鐘）
async fn jma_latest(Query(q): Query<HashMap<String, String>>) -> axum::Json<serde_json::Value> {
    use chrono::{DateTime, Duration as CDur, Timelike, Utc};
    let band = jma_band(&q);
    if let Some(v) = JMA_LATEST
        .lock()
        .get(band)
        .filter(|(at, _)| at.elapsed() < Duration::from_secs(120))
        .map(|(_, v)| v.clone())
    {
        return axum::Json(v);
    }
    let now = Utc::now();
    let base = now.with_second(0).and_then(|t| t.with_nanosecond(0)).unwrap_or(now)
        - CDur::minutes((now.minute() % 10) as i64);
    let mut found = serde_json::Value::Null;
    for k in 0..12 {
        let slot = base - CDur::minutes(10 * k);
        let hhmm = slot.format("%H%M").to_string();
        let url = format!("{JMA_FD}/fd__{band}_{hhmm}.jpg");
        let Ok(r) = CLIENT.head(&url).send().await else { continue };
        if !r.status().is_success() {
            continue;
        }
        let lm = r
            .headers()
            .get(header::LAST_MODIFIED)
            .and_then(|v| v.to_str().ok())
            .and_then(|s| DateTime::parse_from_rfc2822(s).ok())
            .map(|t| t.with_timezone(&Utc));
        if let Some(lm) = lm {
            let lag = lm - slot;
            if lag >= CDur::zero() && lag < CDur::minutes(60) {
                found = serde_json::json!({
                    "slot": slot.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
                    "hhmm": hhmm,
                    "published": lm.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
                    "age_min": (now - slot).num_minutes(),
                });
                break;
            }
        }
    }
    let v = serde_json::json!({
        "band": band,
        "bands": JMA_BANDS.iter().map(|(k, d)| serde_json::json!({"id": k, "label": d})).collect::<Vec<_>>(),
        "latest": found,
        "source": "JMA 氣象衛星中心 Himawari 全圓盤（https://www.data.jma.go.jp/mscweb/data/himawari/list_fd_.html）",
    });
    if !v["latest"].is_null() {
        JMA_LATEST.lock().insert(band.to_string(), (std::time::Instant::now(), v.clone()));
    }
    axum::Json(v)
}

/// 代理一張 JMA 全圓盤影像；dl=1 時以附件下載（檔名含 UTC 日期與時刻）
async fn jma_img(Query(q): Query<HashMap<String, String>>) -> Resp {
    let band = jma_band(&q);
    let hhmm: String = q.get("hhmm").cloned().unwrap_or_default();
    if hhmm.len() != 4 || !hhmm.bytes().all(|c| c.is_ascii_digit()) {
        return (StatusCode::BAD_REQUEST, "hhmm 需為 4 位數字（UTC 時分）").into_response_compat();
    }
    let url = format!("{JMA_FD}/fd__{band}_{hhmm}.jpg");
    let Ok(r) = CLIENT.get(&url).send().await else {
        return (StatusCode::BAD_GATEWAY, "無法連線 JMA（離線？）").into_response_compat();
    };
    if !r.status().is_success() {
        return (StatusCode::NOT_FOUND, "JMA 沒有這張影像").into_response_compat();
    }
    let day = q.get("date").filter(|d| d.len() == 8 && d.bytes().all(|c| c.is_ascii_digit())).cloned()
        .unwrap_or_else(|| chrono::Utc::now().format("%Y%m%d").to_string());
    let Ok(bytes) = r.bytes().await else {
        return (StatusCode::BAD_GATEWAY, "JMA 影像下載中斷").into_response_compat();
    };
    let mut resp = Response::new(Body::from(bytes));
    let h = resp.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("image/jpeg"));
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("public, max-age=120"));
    if q.get("dl").is_some_and(|v| v == "1") {
        if let Ok(v) = HeaderValue::from_str(&format!("attachment; filename=\"himawari9_{band}_{day}_{hhmm}UTC.jpg\"")) {
            h.insert(header::CONTENT_DISPOSITION, v);
        }
    }
    resp
}

fn decode_template(q: &HashMap<String, String>) -> Option<String> {
    let t = q.get("t")?;
    let raw = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(t.trim_end_matches('='))
        .ok()?;
    String::from_utf8(raw).ok()
}

/// 圖磚網址是否放行（資安檢測 M-1）：用與 reqwest 相同的 WHATWG URL 解析器取主機，避免 `\`、`@` 等解析差異；
/// 只允許 https、預設埠、不帶帳密、主機為網域名稱（不接受 IP 位址）且在圖資目錄允許清單內
fn host_allowed(url: &str) -> bool {
    let Ok(u) = reqwest::Url::parse(url) else { return false };
    if u.scheme() != "https" || u.port().is_some() || !u.username().is_empty() || u.password().is_some() {
        return false;
    }
    let Some(h) = u.host_str() else { return false };
    // IPv4／IPv6 位址（含 127.0.0.1、169.254.169.254、內網；WHATWG 會把 2130706433、0x7f.1 等寫法正規化為 IPv4）一律拒絕
    if h.starts_with('[') || h.parse::<std::net::IpAddr>().is_ok() {
        return false;
    }
    ALLOWED_HOSTS.contains(&h.trim_end_matches('.').to_ascii_lowercase())
}

fn png_blank() -> Resp {
    tile_response(TRANSPARENT_PNG.to_vec(), "image/png", "blank", 3600)
}

fn tile_response(data: Vec<u8>, ct: &str, src: &str, max_age: u32) -> Resp {
    let mut r = Response::new(Body::from(data));
    let h = r.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_str(ct).unwrap_or(HeaderValue::from_static("image/png")),
    );
    h.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_str(&format!("public, max-age={max_age}")).unwrap(),
    );
    h.insert(
        "X-Tile-Source",
        HeaderValue::from_str(src).unwrap_or(HeaderValue::from_static("?")),
    );
    r
}

fn cache_path(url: &str) -> PathBuf {
    let hex: String = Sha256::digest(url.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    cache_dir().join(&hex[..2]).join(&hex[2..])
}

/// 快取檔格式：第一行 content-type，其後為原始位元組
fn read_cache(p: &PathBuf) -> Option<(Vec<u8>, String, bool)> {
    let meta = std::fs::metadata(p).ok()?;
    let fresh = meta
        .modified()
        .ok()
        .and_then(|m| SystemTime::now().duration_since(m).ok())
        .map(|age| age < CACHE_TTL)
        .unwrap_or(false);
    let raw = std::fs::read(p).ok()?;
    let nl = raw.iter().position(|b| *b == b'\n')?;
    let ct = String::from_utf8_lossy(&raw[..nl]).to_string();
    Some((raw[nl + 1..].to_vec(), ct, fresh))
}

fn write_cache(p: &PathBuf, data: &[u8], ct: &str) {
    if let Some(dir) = p.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let mut buf = Vec::with_capacity(data.len() + ct.len() + 1);
    buf.extend_from_slice(ct.as_bytes());
    buf.push(b'\n');
    buf.extend_from_slice(data);
    let tmp = p.with_extension("part");
    if std::fs::write(&tmp, &buf).is_ok() {
        let _ = std::fs::rename(&tmp, p);
    }
}

/// 取圖磚：新鮮快取 → 上游 → 過期快取（離線）→ 透明圖磚
async fn fetch_tile(url: String) -> Resp {
    if !host_allowed(&url) {
        return (StatusCode::FORBIDDEN, "此網域不在圖資目錄（map_layers.js）內").into_response_compat();
    }
    let path = cache_path(&url);
    let cached = {
        let p = path.clone();
        tokio::task::spawn_blocking(move || read_cache(&p))
            .await
            .ok()
            .flatten()
    };
    if let Some((data, ct, true)) = &cached {
        return tile_response(data.clone(), ct, "cache", 86400);
    }
    let upstream = async {
        let _permit = LIMIT.acquire().await.ok()?;
        let resp = TILE_CLIENT.get(&url).send().await.ok()?;
        let status = resp.status();
        let ct = resp
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        let bytes = resp.bytes().await.ok()?;
        Some((status, ct, bytes))
    }
    .await;
    match upstream {
        Some((st, ct, bytes)) if st.is_success() && ct.starts_with("image/") && !bytes.is_empty() => {
            let data = bytes.to_vec();
            let (p, d, c) = (path, data.clone(), ct.clone());
            tokio::task::spawn_blocking(move || write_cache(&p, &d, &c));
            tile_response(data, &ct, "upstream", 86400)
        }
        other => {
            if let Some((data, ct, _)) = cached {
                return tile_response(data, &ct, "stale-cache", 600);
            }
            if let Some((st, ct, _)) = other {
                tracing::debug!("圖磚上游無影像（{st}，{ct}）：{url}");
            } else {
                tracing::debug!("圖磚上游連線失敗：{url}");
            }
            png_blank()
        }
    }
}

trait IntoRespCompat {
    fn into_response_compat(self) -> Resp;
}
impl IntoRespCompat for (StatusCode, &'static str) {
    fn into_response_compat(self) -> Resp {
        let mut r = Response::new(Body::from(self.1));
        *r.status_mut() = self.0;
        r.headers_mut().insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("text/plain; charset=utf-8"),
        );
        r
    }
}

async fn xyz(Path((z, x, y)): Path<(u32, u32, u32)>, Query(q): Query<HashMap<String, String>>) -> Resp {
    let Some(t) = decode_template(&q) else {
        return (StatusCode::BAD_REQUEST, "缺少或無效的 t 參數").into_response_compat();
    };
    let n = 1u64 << z.min(30);
    let url = t
        .replace("{z}", &z.to_string())
        .replace("{x}", &x.to_string())
        .replace("{y}", &y.to_string())
        .replace("{-y}", &(n.saturating_sub(1 + y as u64)).to_string())
        .replace("{TileMatrix}", &z.to_string())
        .replace("{TileCol}", &x.to_string())
        .replace("{TileRow}", &y.to_string());
    fetch_tile(url).await
}

const ORIGIN_SHIFT: f64 = 20_037_508.342_789_244;

/// 圖磚 (z, x, y) 之 EPSG:3857 範圍 (minx, miny, maxx, maxy)
fn tile_bbox(z: u32, x: u32, y: u32) -> (f64, f64, f64, f64) {
    let size = 2.0 * ORIGIN_SHIFT / (1u64 << z.min(30)) as f64;
    let minx = -ORIGIN_SHIFT + x as f64 * size;
    let maxy = ORIGIN_SHIFT - y as f64 * size;
    (minx, maxy - size, minx + size, maxy)
}

fn enc(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' | b',' | b':' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

async fn wms(Path((z, x, y)): Path<(u32, u32, u32)>, Query(q): Query<HashMap<String, String>>) -> Resp {
    let Some(base) = decode_template(&q) else {
        return (StatusCode::BAD_REQUEST, "缺少或無效的 t 參數").into_response_compat();
    };
    let g = |k: &str, d: &str| q.get(k).cloned().unwrap_or_else(|| d.to_string());
    let version = g("version", "1.1.1");
    let (minx, miny, maxx, maxy) = tile_bbox(z, x, y);
    let crs_key = if version.starts_with("1.3") { "CRS" } else { "SRS" };
    let sep = if base.contains('?') { '&' } else { '?' };
    let url = format!(
        "{base}{sep}SERVICE=WMS&REQUEST=GetMap&VERSION={}&LAYERS={}&STYLES={}&FORMAT={}&TRANSPARENT={}&{crs_key}=EPSG:3857&BBOX={minx:.6},{miny:.6},{maxx:.6},{maxy:.6}&WIDTH=256&HEIGHT=256",
        enc(&version),
        enc(&g("layers", "")),
        enc(&g("styles", "")),
        enc(&g("format", "image/png")),
        if g("transparent", "true") == "false" { "FALSE" } else { "TRUE" },
    );
    fetch_tile(url).await
}

/// 各 Himawari 圖層最新可用時刻：以 Time=default 取一張圖磚，讀回應標頭 layer-time-actual（快取 5 分鐘）
async fn himawari_latest(Query(q): Query<HashMap<String, String>>) -> axum::Json<serde_json::Value> {
    let want = q.get("layer").cloned();
    let mut out = Vec::new();
    for (layer, tms) in HIMAWARI_LAYERS {
        if want.as_deref().is_some_and(|w| w != *layer) {
            continue;
        }
        let hit = HIMA_LATEST
            .lock()
            .get(*layer)
            .filter(|(at, _)| at.elapsed() < Duration::from_secs(300))
            .map(|(_, t)| t.clone());
        let time = match hit {
            Some(t) => Some(t),
            None => {
                let url = format!("{GIBS}/{layer}/default/default/{tms}/0/0/0.png");
                let t = CLIENT.get(&url).send().await.ok().and_then(|r| {
                    r.headers()
                        .get("layer-time-actual")
                        .and_then(|v| v.to_str().ok())
                        .map(str::to_string)
                });
                if let Some(t) = &t {
                    HIMA_LATEST
                        .lock()
                        .insert(layer.to_string(), (std::time::Instant::now(), t.clone()));
                }
                t
            }
        };
        let max_level: u32 = tms
            .trim_start_matches("GoogleMapsCompatible_Level")
            .parse()
            .unwrap_or(6);
        out.push(serde_json::json!({
            "layer": layer,
            "tms": tms,
            "max_level": max_level,
            "latest": time,
            "template": format!("{GIBS}/{layer}/default/{{time}}/{tms}/{{z}}/{{y}}/{{x}}.png"),
        }));
    }
    axum::Json(serde_json::json!({
        "source": "NASA GIBS（Himawari-9 AHI，JMA；GIBS 圖層名沿用 Himawari_AHI）",
        "cadence_min": 10,
        "layers": out,
    }))
}

async fn info(State(_st): State<Arc<AppState>>) -> axum::Json<serde_json::Value> {
    let dir = cache_dir();
    let mut hosts: Vec<&String> = ALLOWED_HOSTS.iter().collect();
    hosts.sort();
    axum::Json(serde_json::json!({
        "cache_dir": dir.display().to_string(),
        "cache_ttl_days": CACHE_TTL.as_secs() / 86400,
        "upstream_concurrency": UPSTREAM_CONCURRENCY,
        "allowed_hosts": hosts,
        "catalog": "Rust_WMTS_Server/static/layers.js → web/static/js/map_layers.js",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hosts_from_catalog() {
        assert!(ALLOWED_HOSTS.contains("wmts.nlsc.gov.tw"));
        assert!(ALLOWED_HOSTS.contains("gis.sinica.edu.tw"));
        assert!(!ALLOWED_HOSTS.contains("localhost"));
        assert!(host_allowed(
            "https://wmts.nlsc.gov.tw/wmts/EMAP/default/GoogleMapsCompatible/1/1/1"
        ));
        assert!(!host_allowed("https://evil.example.com/x.png"));
        assert!(!host_allowed("https://wmts.nlsc.gov.tw.evil.com/x"));
        assert!(!host_allowed("file:///c:/windows"));
        // M-1：解析差異與內網
        assert!(!host_allowed("http://127.0.0.1:8080\\@wmts.nlsc.gov.tw/x"), "反斜線繞過");
        assert!(!host_allowed("https://127.0.0.1:8080\\@wmts.nlsc.gov.tw/x"), "反斜線繞過（https）");
        assert!(!host_allowed("https://wmts.nlsc.gov.tw@127.0.0.1/x"), "帳密欄偽裝");
        assert!(!host_allowed("https://user:pw@wmts.nlsc.gov.tw/x"), "不接受帶帳密");
        assert!(!host_allowed("http://wmts.nlsc.gov.tw/x"), "只允許 https");
        assert!(!host_allowed("https://wmts.nlsc.gov.tw:8443/x"), "只允許預設埠");
        assert!(!host_allowed("https://169.254.169.254/latest/meta-data"), "雲端中繼資料位址");
        assert!(!host_allowed("https://[::1]/x") && !host_allowed("https://10.0.0.1/x"), "IP 位址");
        assert!(host_allowed("https://WMTS.NLSC.GOV.TW./wmts/x"), "大小寫與結尾點正規化");
        assert!(host_allowed("https://wmts.nlsc.gov.tw:443/wmts/x"), "明寫 443 等同預設埠");
        assert!(!host_allowed("https://2130706433/x") && !host_allowed("https://0x7f.1/x"), "十進位／十六進位 IPv4 寫法");
    }

    #[test]
    fn bbox_world() {
        let (a, b, c, d) = tile_bbox(0, 0, 0);
        assert!((a + ORIGIN_SHIFT).abs() < 1e-6 && (d - ORIGIN_SHIFT).abs() < 1e-6);
        assert!((c - ORIGIN_SHIFT).abs() < 1e-6 && (b + ORIGIN_SHIFT).abs() < 1e-6);
    }
}
