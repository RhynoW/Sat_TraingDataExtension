//! 設定：命令列參數 / 環境變數 / 資料目錄解析（對應 Python 版 config/settings.py）。

use std::env;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Config {
    /// 資料根目錄（版面同 Python 版 scenario04/：DB/、user_defined_*、geojson/ …）
    pub home: PathBuf,
    /// 明確指定的 DuckDB 檔（--db / DB_PATH）
    pub db_override: Option<PathBuf>,
    pub host: String,
    pub port: u16,
    pub open_browser: bool,

    pub conj_threshold_km: f64,
    pub conj_ttl_s: u64,
    pub sigma_r_km: f64,
    pub sigma_t_km: f64,
    pub sat_radius_km: f64,
    pub index_ttl_s: u64,
    pub db_info_ttl_s: u64,

    /// 線上更新 manifest 網址或本機檔（None = 內建 HuggingFace 網址）
    pub update_manifest: Option<String>,
    /// 啟動後與每 6 小時自動檢查更新（--no-update 關閉；仍可在頁面手動檢查）
    pub update_auto: bool,
    /// 重新啟動時由舊程式傳入：等舊程式（PID）結束、釋出原埠再綁定
    pub restart_wait: Option<u32>,
    /// 額外允許的 Host 名稱（小寫，不含埠）；localhost 與 IP 位址一律允許（防 DNS rebinding，見 auth::host_ok）
    pub allowed_hosts: Vec<String>,
}

pub const RAW_TABLE: &str = "raw_tle_archive";
pub const META_TABLE: &str = "sat_n2yo_metadata";
/// 傳播結果高度合理範圍上限（km）：需涵蓋 Cluster 等高橢圓軌道遠地點（~131,000 km）
pub const MAX_ALT_KM: f64 = 140_000.0;

fn env_f64(k: &str, d: f64) -> f64 {
    env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d)
}
fn env_u64(k: &str, d: u64) -> u64 {
    env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d)
}

const USAGE: &str = "\
SatDashboard（Rust 單機版）

用法：SatDashboard.exe [選項]
  --data <目錄>     資料根目錄（含 DB\\、user_defined_TLE\\ 等；預設自動尋找）
  --db <檔案>       指定 DuckDB 檔（預設 <data>\\DB\\space_db_slim.duckdb）
  --port <埠號>     HTTP 埠（預設 5013，被占用時自動往後找）
  --host <位址>     綁定位址（預設 127.0.0.1；區網分享用 0.0.0.0）
  --no-browser      啟動後不自動開啟瀏覽器
  --no-update       不自動檢查新版資料庫與程式（頁面上仍可手動檢查）
  --update-manifest <網址或檔案>  更新來源 manifest（預設 HuggingFace RhynoWu/Rust_SatDashboard）
  --allow-host <名稱>  區網以電腦名稱連線時加入允許的主機名稱（例：my-pc；可重複；寫了埠號會自動去掉；
                       localhost 與 IP 位址一律允許）
  --version         顯示版本（JSON）後結束
  -h, --help        顯示說明

環境變數：SATDASH_DATA、DB_PATH、PORT、SATDASH_UPDATE_MANIFEST、SATDASH_NO_UPDATE、SATDASH_ALLOWED_HOSTS（逗號分隔）、CONJ_THRESHOLD_KM、CONJ_TTL、SIGMA_R_KM、SIGMA_T_KM、
          AISSTREAM_API_KEY（AIS 船舶圖層；也可在地球儀圖層面板輸入）、AIS_BBOX、AIS_MPB（0＝關閉航港局來源）、AIS_IDLE_SEC
";

impl Config {
    pub fn from_args() -> anyhow::Result<Self> {
        let mut data: Option<PathBuf> = env::var_os("SATDASH_DATA").map(PathBuf::from);
        let mut db: Option<PathBuf> = env::var_os("DB_PATH").map(PathBuf::from);
        let mut port: u16 = env::var("PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(5013);
        let mut host = env::var("HOST").unwrap_or_else(|_| "127.0.0.1".into());
        let mut open_browser = true;
        let mut update_manifest: Option<String> = env::var("SATDASH_UPDATE_MANIFEST").ok().filter(|s| !s.is_empty());
        let mut update_auto = env::var_os("SATDASH_NO_UPDATE").is_none();
        let mut restart_wait: Option<u32> = None;
        let mut allowed_hosts: Vec<String> = env::var("SATDASH_ALLOWED_HOSTS")
            .map(|v| v.split(',').map(crate::auth::host_name).filter(|x| !x.is_empty()).collect())
            .unwrap_or_default();

        let mut args = env::args().skip(1);
        while let Some(a) = args.next() {
            match a.as_str() {
                "--data" => data = args.next().map(PathBuf::from),
                "--db" => db = args.next().map(PathBuf::from),
                "--port" => {
                    port = args
                        .next()
                        .and_then(|v| v.parse().ok())
                        .ok_or_else(|| anyhow::anyhow!("--port 需要整數"))?
                }
                "--host" => host = args.next().unwrap_or(host),
                "--no-browser" => open_browser = false,
                "--no-update" => update_auto = false,
                "--update-manifest" => update_manifest = args.next(),
                "--restart-wait" => restart_wait = args.next().and_then(|v| v.parse().ok()),
                "--allow-host" => {
                    let h = args.next().ok_or_else(|| anyhow::anyhow!("--allow-host 需要主機名稱"))?;
                    // 去掉埠號、方括號與結尾的點（複測 R-4）
                    let h = crate::auth::host_name(&h);
                    if h.is_empty() {
                        anyhow::bail!("--allow-host 主機名稱不正確");
                    }
                    allowed_hosts.push(h);
                }
                "--version" => {
                    println!("{}", crate::about::json());
                    std::process::exit(0);
                }
                "-h" | "--help" => {
                    println!("{USAGE}");
                    std::process::exit(0);
                }
                other => anyhow::bail!("未知參數：{other}\n\n{USAGE}"),
            }
        }

        let home = match data {
            Some(d) => d,
            None => discover_home(),
        };

        Ok(Self {
            home,
            db_override: db,
            host,
            port,
            open_browser,
            conj_threshold_km: env_f64("CONJ_THRESHOLD_KM", 10.0),
            conj_ttl_s: env_u64("CONJ_TTL", 120),
            sigma_r_km: env_f64("SIGMA_R_KM", 0.1),
            sigma_t_km: env_f64("SIGMA_T_KM", 0.5),
            sat_radius_km: 0.005,
            index_ttl_s: 600,
            db_info_ttl_s: 300,
            update_manifest,
            update_auto,
            restart_wait,
            allowed_hosts,
        })
    }

    /// 依序解析資料庫位置（同 Python resolve_db 精神，但不自動下載）：
    /// 1. --db / DB_PATH（相對路徑以執行檔目錄及其上層逐層解析）
    /// 2. 預設相對路徑 ..\scenario-advanced01\DB\space_db_slim.duckdb（同上逐層解析）
    /// 3. 資料目錄內 DB\ 或根目錄的 slim / full DB
    pub fn resolve_db(&self) -> Option<PathBuf> {
        let mut cands: Vec<PathBuf> = Vec::new();
        if let Some(p) = &self.db_override {
            cands.extend(resolve_relative(p));
        }
        cands.extend(resolve_relative(Path::new(DEFAULT_DB_REL)));
        cands.push(self.home.join("DB").join("space_db_slim.duckdb"));
        cands.push(self.home.join("DB").join("space_db.duckdb"));
        cands.push(self.home.join("space_db_slim.duckdb"));
        cands.push(self.home.join("space_db.duckdb"));
        cands.into_iter().find(|p| p.is_file())
    }

    /// sat_metadata.csv：DB 同目錄 → 資料目錄 DB\ → 資料目錄根
    pub fn sat_meta_csv(&self) -> PathBuf {
        let mut cands = Vec::new();
        if let Some(dir) = self.resolve_db().and_then(|d| d.parent().map(Path::to_path_buf)) {
            cands.push(dir.join("sat_metadata.csv"));
        }
        cands.push(self.home.join("DB").join("sat_metadata.csv"));
        cands.push(self.home.join("sat_metadata.csv"));
        cands
            .iter()
            .find(|p| p.is_file())
            .cloned()
            .unwrap_or_else(|| cands.pop().unwrap())
    }
    pub fn user_tle_dir(&self) -> PathBuf {
        self.home.join("user_defined_TLE")
    }
    pub fn user_catalogue_dir(&self) -> PathBuf {
        self.home.join("user_defined_SaTCatalogue")
    }
    pub fn user_tracking_dir(&self) -> PathBuf {
        self.home.join("user_defined_tracking_NORAD")
    }
    pub fn user_geojson_dir(&self) -> PathBuf {
        self.home.join("geojson")
    }
    pub fn taiwan_admin_file(&self) -> PathBuf {
        self.user_geojson_dir().join("Taiwan-admin-ploygon.geojson")
    }
    /// 可覆寫的設定檔：資料目錄有檔就用，否則用內嵌預設
    pub fn override_file(&self, name: &str) -> PathBuf {
        self.home.join("config").join(name)
    }
}

/// 預設 DB 相對路徑（相對於 RUST_SatDashboard 專案根目錄）
pub const DEFAULT_DB_REL: &str = r"..\scenario-advanced01\DB\space_db_slim.duckdb";

/// 相對路徑候選：目前工作目錄、執行檔目錄及其每一層上層目錄
/// （exe 位於 target\release\ 或 dist\ 時也能找回專案根目錄）
fn resolve_relative(p: &Path) -> Vec<PathBuf> {
    if p.is_absolute() {
        return vec![p.to_path_buf()];
    }
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        bases.push(cwd);
    }
    if let Some(exe_dir) = env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(Path::to_path_buf))
    {
        let mut cur: Option<&Path> = Some(exe_dir.as_path());
        while let Some(d) = cur {
            bases.push(d.to_path_buf());
            cur = d.parent();
        }
    }
    bases.into_iter().map(|b| b.join(p)).collect()
}

fn looks_like_home(p: &Path) -> bool {
    p.join("DB").is_dir() || p.join("user_defined_TLE").is_dir()
}

/// 自動尋找資料根目錄：
/// 1. 執行檔旁的 data\
/// 2. 執行檔所在目錄
/// 3. 往上層找 scenario-advanced01\scenario04（開發時直接沿用 Python 版資料）
/// 4. 目前工作目錄
fn discover_home() -> PathBuf {
    let exe_dir = env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    let mut cands = vec![exe_dir.join("data"), exe_dir.clone()];
    let mut cur: Option<&Path> = Some(exe_dir.as_path());
    while let Some(d) = cur {
        cands.push(d.join("scenario-advanced01").join("scenario04"));
        cands.push(d.join("data"));
        cur = d.parent();
    }
    if let Ok(cwd) = env::current_dir() {
        cands.push(cwd.join("data"));
        cands.push(cwd);
    }
    cands
        .into_iter()
        .find(|p| looks_like_home(p))
        .unwrap_or_else(|| exe_dir.join("data"))
}
