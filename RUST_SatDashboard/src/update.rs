//! 線上更新：衛星資料庫與執行檔自我更新。
//!
//! 來源：manifest（預設 HuggingFace dataset `RhynoWu/Rust_SatDashboard` 的 `manifest.json`，可用 `--update-manifest`
//! 或 `SATDASH_UPDATE_MANIFEST` 改成其他網址或本機檔案）。manifest 旁的 `manifest.json.sig` 是 ed25519 簽章，
//! 公鑰內嵌（`src/update_pubkey.hex`，`scripts/update_keygen.py` 產生）；簽章不符就不提供任何更新。
//!
//! manifest 每個檔案都有 `sources` 清單（`{"type": "hf"|"github"|…, "url": …}`，相對網址以 manifest 網址為基準），
//! 依序嘗試；之後加 GitHub Releases 當第二來源只要在 manifest 多列一筆，客戶端不必改。
//!
//! 資料庫：下載 `.zst`（中斷可續傳）→ 驗壓縮檔 sha256 → 解壓並驗原檔 sha256 → 舊檔改名 `.bak` → 新檔就位 → 重建索引。
//! 執行檔：下載本機架構的 exe → 驗 sha256 → 執行中的 exe 改名 `.old`（Windows 允許）→ 新檔就位 → 使用者按「重新啟動」。
//!
//! 防凍結（複測 R-2）：manifest 簽章內含 `expires`，過期或缺少 `expires` 的 manifest 一律拒絕——攻擊者重放「最後一份合法
//! manifest」讓客戶端看不到後續安全更新的時間，最多只有一個有效期（發布端預設 30 天，每日 DB 排程會重簽延長）。
//!
//! 防降版／重放（資安檢測 M-2）：資料目錄 `user_private\update_state.json` 記下最後接受的 manifest `generated`，
//! 之後比它舊的 manifest 一律拒絕（即使簽章正確）；執行檔只接受比目前版本新的版本。

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use axum::extract::{ConnectInfo, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::about;
use crate::state::AppState;

pub const DEFAULT_MANIFEST: &str = "https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/resolve/main/manifest.json";
const PUBKEY_HEX: &str = include_str!("update_pubkey.hex");
const CHECK_EVERY: Duration = Duration::from_secs(6 * 3600);

// ── manifest ────────────────────────────────────────────────────────────────

#[derive(Deserialize, Clone, Debug)]
pub struct Source {
    #[serde(rename = "type")]
    pub kind: String,
    pub url: String,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Packed {
    pub format: String,
    pub size: u64,
    pub sha256: String,
}

#[derive(Deserialize, Clone, Debug)]
pub struct DbEntry {
    pub version: String,
    pub file: String,
    pub size: u64,
    pub sha256: String,
    pub packed: Option<Packed>,
    pub sources: Vec<Source>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Asset {
    #[allow(dead_code)] // 發布端檔名，供除錯；下載以 sources 為準
    pub file: String,
    pub size: u64,
    pub sha256: String,
    pub sources: Vec<Source>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct AppEntry {
    pub version: String,
    pub build_date: String,
    #[serde(default)]
    pub notes: String,
    pub assets: HashMap<String, Asset>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Manifest {
    pub schema: u32,
    pub generated: String,
    /// 到期時間（RFC 3339）；在簽章範圍內，過期或缺少就拒絕整份 manifest
    #[serde(default)]
    pub expires: Option<String>,
    pub db: Option<DbEntry>,
    pub app: Option<AppEntry>,
}

// ── 狀態 ────────────────────────────────────────────────────────────────────

#[derive(Default)]
struct Job {
    kind: String,  // "db" | "app"
    phase: String, // download | verify | decompress | install | done | error
    done: u64,
    total: u64,
    message: String,
    running: bool,
}

#[derive(Default)]
struct Status {
    checked_at: Option<String>,
    error: Option<String>,
    manifest: Option<Manifest>,
    manifest_url: String,
    local_db: Option<(PathBuf, u64, SystemTime, String)>, // 路徑、大小、mtime、sha256（依大小 + mtime 快取）
    job: Job,
    restart_pending: bool,
    checking: bool,
}

static STATUS: Lazy<Mutex<Status>> = Lazy::new(|| Mutex::new(Status::default()));

static CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .read_timeout(Duration::from_secs(60))
        .user_agent(concat!("SatDashboard-Rust/", env!("CARGO_PKG_VERSION"), " (updater)"))
        .build()
        .expect("reqwest client")
});

fn manifest_url(st: &AppState) -> String {
    st.cfg.update_manifest.clone().unwrap_or_else(|| DEFAULT_MANIFEST.to_string())
}

/// 相對網址以 manifest 網址（或本機路徑）的目錄為基準
fn resolve_url(base: &str, url: &str) -> String {
    if url.contains("://") || Path::new(url).is_absolute() {
        return url.to_string();
    }
    match base.rfind(['/', '\\']) {
        Some(i) => format!("{}/{}", &base[..i], url),
        None => url.to_string(),
    }
}

fn is_remote(u: &str) -> bool {
    u.starts_with("http://") || u.starts_with("https://")
}

async fn fetch_bytes(url: &str) -> anyhow::Result<Vec<u8>> {
    if !is_remote(url) {
        let p = url.trim_start_matches("file:///").trim_start_matches("file://").to_string();
        return Ok(std::fs::read(p)?);
    }
    let r = CLIENT.get(url).send().await?;
    if !r.status().is_success() {
        anyhow::bail!("{} 回應 {}", url, r.status());
    }
    Ok(r.bytes().await?.to_vec())
}

fn verify_sig(manifest: &[u8], sig_hex: &str) -> anyhow::Result<()> {
    use ed25519_dalek::{Signature, VerifyingKey};
    let pk: [u8; 32] = hex(PUBKEY_HEX.trim())?.try_into().map_err(|_| anyhow::anyhow!("公鑰長度錯誤"))?;
    let sig: [u8; 64] = hex(sig_hex.trim())?.try_into().map_err(|_| anyhow::anyhow!("簽章長度錯誤"))?;
    VerifyingKey::from_bytes(&pk)?
        .verify_strict(manifest, &Signature::from_bytes(&sig))
        .map_err(|_| anyhow::anyhow!("manifest 簽章驗證失敗（不是發布者簽的，或檔案被改過）"))
}

fn hex(s: &str) -> anyhow::Result<Vec<u8>> {
    if !s.is_ascii() || s.len() % 2 != 0 {
        anyhow::bail!("十六進位字串長度錯誤");
    }
    (0..s.len()).step_by(2).map(|i| Ok(u8::from_str_radix(&s[i..i + 2], 16)?)).collect()
}

fn sha256_file(p: &Path) -> std::io::Result<String> {
    let mut f = std::fs::File::open(p)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 20];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}

/// 本機資料庫 sha256（大小與 mtime 沒變就沿用上次的結果）
fn local_db_sha(st: &AppState) -> Option<(PathBuf, String)> {
    let p = st.cfg.resolve_db()?;
    let m = std::fs::metadata(&p).ok()?;
    let (size, mtime) = (m.len(), m.modified().ok()?);
    if let Some((cp, cs, cm, sha)) = STATUS.lock().local_db.clone() {
        if cp == p && cs == size && cm == mtime {
            return Some((p, sha));
        }
    }
    let sha = sha256_file(&p).ok()?;
    STATUS.lock().local_db = Some((p.clone(), size, mtime, sha.clone()));
    Some((p, sha))
}

/// 版本比較：版本號較新，或版本號相同但版本日期較新
fn app_is_newer(a: &AppEntry) -> bool {
    let cur = semver::Version::parse(about::VERSION).ok();
    let new = semver::Version::parse(&a.version).ok();
    match (new, cur) {
        (Some(n), Some(c)) if n != c => n > c,
        _ => a.build_date.as_str() > about::BUILD_DATE,
    }
}

// ── 防降版：最後接受的 manifest 時間 ─────────────────────────────────────────

fn state_file(home: &Path) -> PathBuf {
    home.join("user_private").join("update_state.json")
}

fn last_generated(home: &Path) -> Option<String> {
    let v: Value = serde_json::from_slice(&std::fs::read(state_file(home)).ok()?).ok()?;
    v["last_generated"].as_str().map(str::to_string)
}

/// manifest 的 generated（ISO 8601 UTC，固定格式可直接比字串）不得早於上次接受的；通過就記下來
/// 允許發布端與本機時鐘的誤差；manifest 時間超過「現在＋此值」視為異常（避免誤簽未來時間後鎖死更新）
const FUTURE_SKEW: chrono::Duration = chrono::Duration::days(2);

fn parse_utc(s: &str) -> Option<chrono::DateTime<chrono::Utc>> {
    chrono::DateTime::parse_from_rfc3339(s.trim()).ok().map(|t| t.with_timezone(&chrono::Utc))
}

/// 以解析後的 UTC 時間比較（複測 R-3：RFC 3339 的 +08:00、小數秒等寫法也正確），不早於上次接受的才通過並記下
fn accept_generated(home: &Path, generated: &str) -> anyhow::Result<()> {
    accept_generated_at(home, generated, chrono::Utc::now())
}

fn accept_generated_at(home: &Path, generated: &str, now: chrono::DateTime<chrono::Utc>) -> anyhow::Result<()> {
    let g = parse_utc(generated).ok_or_else(|| anyhow::anyhow!("manifest 時間格式錯誤：{generated}"))?;
    if g > now + FUTURE_SKEW {
        anyhow::bail!("manifest 時間 {generated} 遠在未來（本機時鐘或發布端異常），已拒絕；請確認電腦時間");
    }
    if let Some(last) = last_generated(home) {
        // 舊紀錄無法解析（手動改壞）時視同沒有紀錄
        if let Some(l) = parse_utc(&last) {
            if g < l {
                anyhow::bail!("manifest 時間 {generated} 早於上次接受的 {last}（可能是舊版重放或降版攻擊），已拒絕");
            }
            if g == l {
                return Ok(());
            }
        }
    }
    let norm = g.to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    let data = serde_json::to_vec_pretty(&json!({"last_generated": norm}))?;
    crate::auth::atomic_write(&state_file(home), &data)
}

/// 有效期上限：簽章者也不能簽出超過此長度的 manifest（防誤設成永久有效，讓 R-2 失效）
const MAX_LIFETIME: chrono::Duration = chrono::Duration::days(90);

/// 檢查 manifest 有效期：必須有 expires、晚於 generated、有效期不超過 90 天、且尚未過期
fn check_expiry(generated: &str, expires: Option<&str>, now: chrono::DateTime<chrono::Utc>) -> anyhow::Result<()> {
    let e_raw = expires.ok_or_else(|| anyhow::anyhow!("manifest 沒有到期時間（expires），已拒絕：可能是舊版更新資訊被重放"))?;
    let e = parse_utc(e_raw).ok_or_else(|| anyhow::anyhow!("manifest 到期時間格式錯誤：{e_raw}"))?;
    let g = parse_utc(generated).ok_or_else(|| anyhow::anyhow!("manifest 時間格式錯誤：{generated}"))?;
    if e <= g || e - g > MAX_LIFETIME {
        anyhow::bail!("manifest 有效期異常（{generated} ～ {e_raw}），已拒絕");
    }
    if now > e {
        anyhow::bail!("更新資訊已於 {e_raw} 到期，已拒絕：可能是更新來源遭凍結或發布中斷，也可能是本機時鐘偏快；請確認電腦時間，或聯絡發布者");
    }
    Ok(())
}

fn arch_key() -> &'static str {
    std::env::consts::ARCH
}

// ── 檢查 ────────────────────────────────────────────────────────────────────

pub async fn check(st: Arc<AppState>) -> Value {
    let busy = {
        let mut s = STATUS.lock();
        let busy = s.checking;
        s.checking = true;
        busy
    };
    if busy {
        return status_json(&st).await;
    }
    let url = manifest_url(&st);
    let res: anyhow::Result<Manifest> = async {
        let raw = fetch_bytes(&url).await?;
        let sig = fetch_bytes(&format!("{url}.sig")).await?;
        verify_sig(&raw, &String::from_utf8_lossy(&sig))?;
        let m: Manifest = serde_json::from_slice(&raw)?;
        if m.schema != 1 {
            anyhow::bail!("manifest schema {} 不支援（請更新程式）", m.schema);
        }
        check_expiry(&m.generated, m.expires.as_deref(), chrono::Utc::now())?;
        accept_generated(&st.cfg.home, &m.generated)?;
        Ok(m)
    }
    .await;
    {
        let mut s = STATUS.lock();
        s.manifest_url = url;
        s.checked_at = Some(chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true));
        match res {
            Ok(m) => {
                s.manifest = Some(m);
                s.error = None;
            }
            Err(e) => s.error = Some(format!("{e:#}")),
        }
        s.checking = false;
    }
    status_json(&st).await
}

async fn status_json(st: &Arc<AppState>) -> Value {
    let st2 = st.clone();
    let local = tokio::task::spawn_blocking(move || local_db_sha(&st2)).await.ok().flatten();
    let s = STATUS.lock();
    let m = s.manifest.as_ref();
    let db = m.and_then(|m| m.db.as_ref());
    let app = m.and_then(|m| m.app.as_ref());
    let asset = app.and_then(|a| a.assets.get(arch_key()));
    json!({
        "manifest_url": s.manifest_url,
        "checked_at": s.checked_at,
        "checking": s.checking,
        "manifest_generated": m.map(|m| m.generated.clone()),
        "error": s.error,
        "current": {"version": about::VERSION, "build_date": about::BUILD_DATE, "arch": arch_key(),
                     "db_path": local.as_ref().map(|l| l.0.display().to_string()),
                     "db_sha256": local.as_ref().map(|l| l.1.clone())},
        "db": db.map(|d| json!({
            "version": d.version, "size": d.size,
            "download_size": d.packed.as_ref().map(|p| p.size).unwrap_or(d.size),
            "update_available": local.as_ref().map(|l| l.1 != d.sha256).unwrap_or(true),
        })),
        "app": app.map(|a| json!({
            "version": a.version, "build_date": a.build_date, "notes": a.notes,
            "download_size": asset.map(|x| x.size),
            "update_available": asset.is_some() && app_is_newer(a) && !s.restart_pending,
        })),
        "job": {"kind": s.job.kind, "phase": s.job.phase, "done": s.job.done, "total": s.job.total,
                "message": s.job.message, "running": s.job.running},
        "restart_pending": s.restart_pending,
        "auto_check": st.cfg.update_auto,
    })
}

/// 第一次執行（找不到資料庫）：立即檢查並自動下載資料庫，主控台每 10% 顯示一次進度
pub fn spawn_first_run(st: Arc<AppState>) {
    if !st.cfg.update_auto || st.cfg.resolve_db().is_some() {
        return;
    }
    tokio::spawn(async move {
        let v = check(st.clone()).await;
        if let Some(e) = v["error"].as_str() {
            tracing::warn!("無法取得資料庫下載資訊：{e}（連上網路後在頁面右下角按「檢查更新」→「更新」）");
            return;
        }
        if v["db"].is_null() {
            tracing::warn!("更新來源沒有資料庫可下載");
            return;
        }
        if start_job("db").is_err() {
            return;
        }
        let mb = |b: u64| b as f64 / 1e6;
        let printer = tokio::spawn(async move {
            let mut last = (String::new(), -1i64);
            loop {
                tokio::time::sleep(Duration::from_secs(2)).await;
                let (phase, done, total, running) = {
                    let s = STATUS.lock();
                    (s.job.phase.clone(), s.job.done, s.job.total, s.job.running)
                };
                if !running {
                    break;
                }
                let pct = if total > 0 { (done * 100 / total) as i64 } else { 0 };
                let step = pct / 10;
                if phase != last.0 || step != last.1 {
                    match phase.as_str() {
                        "download" => tracing::info!("下載資料庫 {pct}%（{:.0} / {:.0} MB）", mb(done), mb(total)),
                        "verify" => tracing::info!("驗證下載檔…"),
                        "decompress" => tracing::info!("解壓縮 {pct}%"),
                        "install" => tracing::info!("放置資料庫、建立衛星索引…"),
                        _ => {}
                    }
                    last = (phase, step);
                }
            }
        });
        let r = run_db(st.clone()).await;
        let ok = r.is_ok();
        finish_job(r);
        let _ = printer.await;
        if ok {
            tracing::info!("資料庫已就緒：{} 顆衛星（頁面會自動重新整理）", st.index().sats.len());
        } else {
            tracing::warn!("資料庫下載失敗：{}（在頁面右下角按「更新」會從中斷處續傳）", STATUS.lock().job.message);
        }
    });
}

/// 背景自動檢查：啟動 30 秒後一次，之後每 6 小時
pub fn spawn_auto_check(st: Arc<AppState>) {
    if !st.cfg.update_auto {
        return;
    }
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_secs(30)).await;
        loop {
            let v = check(st.clone()).await;
            if v["db"]["update_available"] == json!(true) {
                tracing::info!("有新版衛星資料庫：{}（可在頁面右下角按「更新」）", v["db"]["version"]);
            }
            if v["app"]["update_available"] == json!(true) {
                tracing::info!("有新版程式：v{}（{}）", v["app"]["version"], v["app"]["build_date"]);
            }
            tokio::time::sleep(CHECK_EVERY).await;
        }
    });
}

// ── 下載 ────────────────────────────────────────────────────────────────────

fn set_job(f: impl FnOnce(&mut Job)) {
    f(&mut STATUS.lock().job);
}

/// 依序嘗試各來源；`.part` 已存在時用 Range 續傳
async fn download(sources: &[Source], base: &str, out: &Path, total: u64) -> anyhow::Result<()> {
    let mut last = anyhow::anyhow!("manifest 沒有下載來源");
    for src in sources {
        let url = resolve_url(base, &src.url);
        set_job(|j| {
            j.phase = "download".into();
            j.total = total;
            j.message = format!("下載中（來源 {}）", src.kind);
        });
        match download_one(&url, out, total).await {
            Ok(()) => return Ok(()),
            Err(e) => {
                tracing::warn!("來源 {} 下載失敗：{e:#}", src.kind);
                last = e;
            }
        }
    }
    Err(last)
}

async fn download_one(url: &str, out: &Path, total: u64) -> anyhow::Result<()> {
    if !is_remote(url) {
        let p = url.trim_start_matches("file:///").trim_start_matches("file://").to_string();
        std::fs::copy(&p, out)?;
        set_job(|j| j.done = total);
        return Ok(());
    }
    let have = std::fs::metadata(out).map(|m| m.len()).unwrap_or(0);
    let have = if have > total { 0 } else { have };
    let mut req = CLIENT.get(url);
    if have > 0 && have < total {
        req = req.header(reqwest::header::RANGE, format!("bytes={have}-"));
    }
    let mut resp = req.send().await?;
    let st = resp.status();
    if have == total && (st.is_success() || st == StatusCode::RANGE_NOT_SATISFIABLE) {
        set_job(|j| j.done = total);
        return Ok(());
    }
    if !st.is_success() {
        anyhow::bail!("{url} 回應 {st}");
    }
    let append = st == StatusCode::PARTIAL_CONTENT;
    let mut f = std::fs::OpenOptions::new().create(true).write(true).append(append).truncate(!append).open(out)?;
    let mut done = if append { have } else { 0 };
    set_job(|j| j.done = done);
    while let Some(chunk) = resp.chunk().await? {
        f.write_all(&chunk)?;
        done += chunk.len() as u64;
        set_job(|j| j.done = done);
    }
    f.flush()?;
    if done != total {
        anyhow::bail!("下載不完整：{done} / {total} bytes（再按一次「更新」會從中斷處續傳）");
    }
    Ok(())
}

fn rename_retry(a: &Path, b: &Path) -> std::io::Result<()> {
    let mut last = None;
    for _ in 0..20 {
        match std::fs::rename(a, b) {
            Ok(()) => return Ok(()),
            Err(e) => last = Some(e),
        }
        std::thread::sleep(Duration::from_millis(250)); // 可能有查詢正開著 DB
    }
    Err(last.unwrap())
}

fn with_suffix(p: &Path, suf: &str) -> PathBuf {
    let mut s = p.as_os_str().to_owned();
    s.push(suf);
    PathBuf::from(s)
}

// ── 資料庫更新 ──────────────────────────────────────────────────────────────

async fn run_db(st: Arc<AppState>) -> anyhow::Result<String> {
    let (m, base) = {
        let s = STATUS.lock();
        (s.manifest.clone(), s.manifest_url.clone())
    };
    let d = m.and_then(|m| m.db).ok_or_else(|| anyhow::anyhow!("尚未取得 manifest，請先「檢查更新」"))?;
    let st2 = st.clone();
    if let Some((_, sha)) = tokio::task::spawn_blocking(move || local_db_sha(&st2)).await? {
        if sha == d.sha256 {
            return Ok(format!("資料庫已是最新（{}）", d.version));
        }
    }
    let target = st.cfg.resolve_db().unwrap_or_else(|| st.cfg.home.join("DB").join(&d.file));
    let had_old = target.exists();
    if let Some(dir) = target.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let (dl_size, dl_sha, packed) = match &d.packed {
        Some(p) if p.format == "zstd" => (p.size, p.sha256.clone(), true),
        Some(p) => anyhow::bail!("不支援的壓縮格式 {}", p.format),
        None => (d.size, d.sha256.clone(), false),
    };
    let part = with_suffix(&target, if packed { ".download.zst" } else { ".download" });
    download(&d.sources, &base, &part, dl_size).await?;

    set_job(|j| {
        j.phase = "verify".into();
        j.message = "驗證下載檔 sha256".into();
    });
    let p2 = part.clone();
    let got = tokio::task::spawn_blocking(move || sha256_file(&p2)).await??;
    if got != dl_sha {
        let _ = std::fs::remove_file(&part);
        anyhow::bail!("下載檔 sha256 不符（已刪除，請重試）");
    }

    let newf = with_suffix(&target, ".new");
    if packed {
        set_job(|j| {
            j.phase = "decompress".into();
            j.done = 0;
            j.total = d.size;
            j.message = "解壓縮".into();
        });
        let (p2, n2, want) = (part.clone(), newf.clone(), d.sha256.clone());
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let src = std::io::BufReader::new(std::fs::File::open(&p2)?);
            let mut dec = ruzstd::decoding::StreamingDecoder::new(src).map_err(|e| anyhow::anyhow!("zstd：{e:?}"))?;
            let mut out = std::io::BufWriter::new(std::fs::File::create(&n2)?);
            let mut h = Sha256::new();
            let mut buf = vec![0u8; 1 << 20];
            let mut done = 0u64;
            loop {
                let n = dec.read(&mut buf)?;
                if n == 0 {
                    break;
                }
                h.update(&buf[..n]);
                out.write_all(&buf[..n])?;
                done += n as u64;
                set_job(|j| j.done = done);
            }
            out.flush()?;
            if format!("{:x}", h.finalize()) != want {
                let _ = std::fs::remove_file(&n2);
                anyhow::bail!("解壓後 sha256 不符");
            }
            Ok(())
        })
        .await??;
        let _ = std::fs::remove_file(&part);
    } else {
        std::fs::rename(&part, &newf)?;
    }

    set_job(|j| {
        j.phase = "install".into();
        j.message = "替換資料庫".into();
    });
    let (t2, n2) = (target.clone(), newf.clone());
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let bak = with_suffix(&t2, ".bak");
        if t2.exists() {
            let _ = std::fs::remove_file(&bak);
            rename_retry(&t2, &bak)?;
        }
        if let Err(e) = rename_retry(&n2, &t2) {
            let _ = std::fs::rename(&bak, &t2); // 復原
            return Err(e.into());
        }
        Ok(())
    })
    .await??;
    let st2 = st.clone();
    tokio::task::spawn_blocking(move || st2.reload_all()).await?;
    Ok(if had_old {
        format!("資料庫已更新為 {}（舊檔保留為 .bak）", d.version)
    } else {
        format!("資料庫已下載（{}）", d.version)
    })
}

// ── 執行檔自我更新 ──────────────────────────────────────────────────────────

async fn run_app() -> anyhow::Result<String> {
    let (m, base) = {
        let s = STATUS.lock();
        (s.manifest.clone(), s.manifest_url.clone())
    };
    let app = m.and_then(|m| m.app).ok_or_else(|| anyhow::anyhow!("尚未取得 manifest，請先「檢查更新」"))?;
    if !app_is_newer(&app) {
        anyhow::bail!("manifest 的程式版本 v{} 不比目前的 v{} 新，不更新", app.version, about::VERSION);
    }
    let asset = app.assets.get(arch_key()).cloned().ok_or_else(|| anyhow::anyhow!("manifest 沒有 {} 版執行檔", arch_key()))?;
    let exe = std::env::current_exe()?;
    let newf = with_suffix(&exe, ".new");
    download(&asset.sources, &base, &newf, asset.size).await?;
    set_job(|j| {
        j.phase = "verify".into();
        j.message = "驗證執行檔 sha256".into();
    });
    let n2 = newf.clone();
    let got = tokio::task::spawn_blocking(move || sha256_file(&n2)).await??;
    if got != asset.sha256 {
        let _ = std::fs::remove_file(&newf);
        anyhow::bail!("執行檔 sha256 不符（已刪除，請重試）");
    }
    set_job(|j| {
        j.phase = "install".into();
        j.message = "替換執行檔".into();
    });
    let old = with_suffix(&exe, ".old");
    let _ = std::fs::remove_file(&old);
    std::fs::rename(&exe, &old).map_err(|e| anyhow::anyhow!("無法改名執行中的程式（資料夾沒有寫入權限？）：{e}"))?;
    if let Err(e) = std::fs::rename(&newf, &exe) {
        let _ = std::fs::rename(&old, &exe);
        anyhow::bail!("無法放置新版執行檔：{e}");
    }
    STATUS.lock().restart_pending = true;
    Ok(format!("已下載 v{}（{}），按「重新啟動」後生效", app.version, app.build_date))
}

/// 啟動時清掉上一版留下的 `.old`
pub fn cleanup_old_exe() {
    if let Ok(exe) = std::env::current_exe() {
        let _ = std::fs::remove_file(with_suffix(&exe, ".old"));
    }
}

/// 以新版重新啟動：新程式在新的主控台視窗執行、等本程式結束後綁同一個埠、不再開瀏覽器
fn restart() -> anyhow::Result<()> {
    let exe = std::env::current_exe()?;
    let mut args: Vec<String> = Vec::new();
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        match a.as_str() {
            "--no-browser" => {}
            "--restart-wait" => {
                it.next();
            }
            _ => args.push(a),
        }
    }
    let mut cmd = std::process::Command::new(exe);
    cmd.args(&args).arg("--no-browser").arg("--restart-wait").arg(std::process::id().to_string());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0000_0010); // CREATE_NEW_CONSOLE
    }
    cmd.spawn()?;
    tokio::spawn(async {
        tokio::time::sleep(Duration::from_millis(600)).await;
        std::process::exit(0);
    });
    Ok(())
}

// ── HTTP ────────────────────────────────────────────────────────────────────

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/api/update/status", get(api_status))
        .route("/api/update/check", post(api_check))
        .route("/api/update/db", post(api_db))
        .route("/api/update/app", post(api_app))
        .route("/api/update/restart", post(api_restart))
}

fn local_only(addr: &std::net::SocketAddr) -> Option<Response> {
    if addr.ip().is_loopback() {
        None
    } else {
        Some((StatusCode::FORBIDDEN, Json(json!({"error": "更新只能在執行程式的那台電腦上操作"}))).into_response())
    }
}

async fn api_status(State(st): State<Arc<AppState>>) -> Json<Value> {
    Json(status_json(&st).await)
}

async fn api_check(State(st): State<Arc<AppState>>, ConnectInfo(a): ConnectInfo<std::net::SocketAddr>) -> Response {
    if let Some(r) = local_only(&a) {
        return r;
    }
    Json(check(st).await).into_response()
}

fn start_job(kind: &str) -> Result<(), Response> {
    let mut s = STATUS.lock();
    if s.job.running {
        return Err((StatusCode::CONFLICT, Json(json!({"error": "已有更新在進行中"}))).into_response());
    }
    s.job = Job { kind: kind.into(), phase: "start".into(), running: true, ..Default::default() };
    Ok(())
}

fn finish_job(r: anyhow::Result<String>) {
    set_job(|j| {
        j.running = false;
        match r {
            Ok(msg) => {
                j.phase = "done".into();
                j.message = msg;
            }
            Err(e) => {
                j.phase = "error".into();
                j.message = format!("{e:#}");
            }
        }
    });
}

async fn api_db(State(st): State<Arc<AppState>>, ConnectInfo(a): ConnectInfo<std::net::SocketAddr>) -> Response {
    if let Some(r) = local_only(&a) {
        return r;
    }
    if let Err(r) = start_job("db") {
        return r;
    }
    tokio::spawn(async move { finish_job(run_db(st).await) });
    Json(json!({"ok": true})).into_response()
}

async fn api_app(ConnectInfo(a): ConnectInfo<std::net::SocketAddr>) -> Response {
    if let Some(r) = local_only(&a) {
        return r;
    }
    if let Err(r) = start_job("app") {
        return r;
    }
    tokio::spawn(async move { finish_job(run_app().await) });
    Json(json!({"ok": true})).into_response()
}

async fn api_restart(ConnectInfo(a): ConnectInfo<std::net::SocketAddr>) -> Response {
    if let Some(r) = local_only(&a) {
        return r;
    }
    if !STATUS.lock().restart_pending {
        return (StatusCode::CONFLICT, Json(json!({"error": "沒有待生效的新版程式"}))).into_response();
    }
    match restart() {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": format!("{e:#}")}))).into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relative_urls() {
        let b = "https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/resolve/main/manifest.json";
        assert_eq!(resolve_url(b, "db/x.zst"), "https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/resolve/main/db/x.zst");
        assert_eq!(resolve_url(b, "https://github.com/a/b"), "https://github.com/a/b");
    }

    #[test]
    fn pubkey_is_32_bytes() {
        assert_eq!(hex(PUBKEY_HEX.trim()).unwrap().len(), 32);
    }

    #[test]
    fn bad_signature_rejected() {
        assert!(verify_sig(b"{}", &"00".repeat(64)).is_err());
        assert!(hex("é0").is_err() && hex("ab\u{4e2d}").is_err(), "多位元組字元不可 panic");
    }

    #[test]
    fn expiry_enforced() {
        let now = parse_utc("2026-11-26T12:00:00Z").unwrap();
        let g = "2026-11-26T04:00:00Z";
        assert!(check_expiry(g, Some("2026-12-26T04:00:00Z"), now).is_ok());
        assert!(check_expiry(g, None, now).is_err(), "缺少 expires 拒絕（舊格式 manifest 重放）");
        assert!(check_expiry(g, Some("2026-11-26T11:59:59Z"), now).is_err(), "已過期拒絕");
        assert!(check_expiry(g, Some("2026-11-26T20:00:00+08:00"), now).is_ok(), "時區寫法以時間比較");
        assert!(check_expiry(g, Some("2026-11-26T03:00:00Z"), now).is_err(), "到期早於 generated");
        assert!(check_expiry(g, Some("2027-06-01T00:00:00Z"), now).is_err(), "有效期超過 90 天");
        assert!(check_expiry(g, Some("not-a-date"), now).is_err());
    }

    #[test]
    fn rollback_rejected() {
        let home = std::env::temp_dir().join(format!("sd_upd_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        accept_generated(&home, "2026-11-26T02:00:00Z").unwrap();
        accept_generated(&home, "2026-11-26T02:00:00Z").unwrap();
        accept_generated(&home, "2026-11-27T00:00:00Z").unwrap();
        assert!(accept_generated(&home, "2026-11-26T02:00:00Z").is_err(), "較舊的 manifest 拒絕");
        assert!(accept_generated(&home, "not-a-date").is_err());
        assert_eq!(last_generated(&home).as_deref(), Some("2026-11-27T00:00:00Z"));
        // R-3：不同寫法以時間比較——同一時刻的 +08:00 寫法視為相同，早一秒的拒絕
        accept_generated(&home, "2026-11-27T08:00:00+08:00").unwrap();
        assert!(accept_generated(&home, "2026-11-27T07:59:59.500+08:00").is_err(), "字串比較會誤判為較新");
        accept_generated(&home, "2026-11-27T00:00:00.250Z").unwrap();
        assert_eq!(last_generated(&home).as_deref(), Some("2026-11-27T00:00:00Z"), "以 UTC 秒精度正規化保存");
        // 遠在未來的 manifest 拒絕，不寫入紀錄
        let now = parse_utc("2026-11-28T00:00:00Z").unwrap();
        assert!(accept_generated_at(&home, "2026-12-31T00:00:00Z", now).is_err());
        assert!(accept_generated_at(&home, "2026-11-29T12:00:00Z", now).is_ok(), "2 天內的時鐘誤差可接受");
    }
}
