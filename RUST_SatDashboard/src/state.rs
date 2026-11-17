//! 全域狀態：衛星索引（TTL / DB mtime 變更自動背景重建）、統計與接近篩選快取。

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Instant, SystemTime};

use parking_lot::{Mutex, RwLock};
use serde_json::Value;

use chrono::{DateTime, Duration, DurationRound, Utc};

use crate::classify::Rules;
use crate::config::Config;
use crate::coverage::{self, Cat};
use crate::index::{self, SatIndex, SharedIndex};
use crate::rpo::SceneCache;

pub struct Cached {
    pub at: Instant,
    pub value: Arc<Value>,
}

pub struct AppState {
    pub cfg: Config,
    pub rules: RwLock<Arc<Rules>>,
    index: RwLock<SharedIndex>,
    index_loaded: Mutex<(Instant, Option<SystemTime>)>,
    rebuilding: AtomicBool,
    pub stats_cache: Mutex<HashMap<bool, Cached>>,
    pub conj_cache: Mutex<HashMap<(u64, usize), Cached>>,
    /// 接近篩選計算鎖：避免並行請求各自重算全目錄
    pub conj_lock: Mutex<()>,
    pub db_info_cache: Mutex<Option<Cached>>,
    pub borders_cache: Mutex<Option<Arc<Vec<u8>>>>,
    pub cats: RwLock<Arc<Vec<Cat>>>,
    /// 歷史索引快取（key：整點小時），最多保留 4 份
    hist_cache: Mutex<Vec<(DateTime<Utc>, SharedIndex)>>,
    /// 天球 / 凌月 / 過頂預報結果快取（key：查詢參數字串）
    pub result_cache: Mutex<HashMap<String, Cached>>,
    pub rpo_cache: Mutex<SceneCache>,
    pub rpo_lock: Mutex<()>,
}

fn load_cats(cfg: &Config) -> Vec<Cat> {
    let a = cfg
        .home
        .parent()
        .map(|p| p.join("overpass_cats.yaml"))
        .unwrap_or_default();
    let b = cfg.override_file("overpass_cats.yaml");
    coverage::load_cats(&[b.as_path(), a.as_path()])
}

fn db_mtime(cfg: &Config) -> Option<SystemTime> {
    cfg.resolve_db()
        .and_then(|p| std::fs::metadata(p).ok())
        .and_then(|m| m.modified().ok())
}

impl AppState {
    pub fn new(cfg: Config) -> Arc<Self> {
        let rules = Rules::load(&cfg.override_file("classification_rules.yaml"));
        let cats = load_cats(&cfg);
        Arc::new(Self {
            cfg,
            rules: RwLock::new(Arc::new(rules)),
            index: RwLock::new(Arc::new(SatIndex::empty())),
            index_loaded: Mutex::new((Instant::now(), None)),
            rebuilding: AtomicBool::new(false),
            stats_cache: Mutex::new(HashMap::new()),
            conj_cache: Mutex::new(HashMap::new()),
            conj_lock: Mutex::new(()),
            db_info_cache: Mutex::new(None),
            borders_cache: Mutex::new(None),
            cats: RwLock::new(Arc::new(cats)),
            hist_cache: Mutex::new(Vec::new()),
            result_cache: Mutex::new(HashMap::new()),
            rpo_cache: Mutex::new(HashMap::new()),
            rpo_lock: Mutex::new(()),
        })
    }

    /// 同步重建索引（啟動時與 admin reload 用）
    pub fn rebuild_index_now(&self) {
        let mtime = db_mtime(&self.cfg);
        let rules = self.rules.read().clone();
        let idx = index::build_index(&self.cfg, &rules);
        *self.index.write() = Arc::new(idx);
        *self.index_loaded.lock() = (Instant::now(), mtime);
        self.stats_cache.lock().clear();
        self.conj_cache.lock().clear();
    }

    /// 取得目前索引；過期（TTL）或 DB 檔更新時於背景重建，期間仍回傳舊索引
    pub fn index(self: &Arc<Self>) -> SharedIndex {
        let (loaded_at, mtime) = *self.index_loaded.lock();
        let stale = loaded_at.elapsed().as_secs() > self.cfg.index_ttl_s || db_mtime(&self.cfg) != mtime;
        if stale && !self.rebuilding.swap(true, Ordering::SeqCst) {
            let me = self.clone();
            std::thread::spawn(move || {
                tracing::info!("索引過期或 DB 已更新，背景重建中…");
                me.rebuild_index_now();
                me.rebuilding.store(false, Ordering::SeqCst);
            });
        }
        self.index.read().clone()
    }

    pub fn reload_all(&self) -> Value {
        *self.cats.write() = Arc::new(load_cats(&self.cfg));
        self.result_cache.lock().clear();
        self.hist_cache.lock().clear();
        let rules = Rules::load(&self.cfg.override_file("classification_rules.yaml"));
        let summary = serde_json::json!({
            "country_map": rules.country_map.len(),
            "constellation_rules": rules.constellation_rules.len(),
        });
        *self.rules.write() = Arc::new(rules);
        *self.borders_cache.lock() = None;
        *self.db_info_cache.lock() = None;
        self.rebuild_index_now();
        summary
    }

    /// 適用於 ts 之索引：ts ≥ now−1h 用現行索引；過去時刻查 epoch ≤ ts（取整點）之最新 TLE
    pub fn index_for_time(self: &Arc<Self>, ts: DateTime<Utc>) -> SharedIndex {
        if ts >= Utc::now() - Duration::hours(1) {
            return self.index();
        }
        let key = ts.duration_trunc(Duration::hours(1)).unwrap_or(ts);
        if let Some((_, idx)) = self.hist_cache.lock().iter().find(|(k, _)| *k == key) {
            return idx.clone();
        }
        let rules = self.rules.read().clone();
        match index::build_index_at(&self.cfg, &rules, key) {
            Ok(idx) => {
                let idx = Arc::new(idx);
                let mut c = self.hist_cache.lock();
                c.push((key, idx.clone()));
                if c.len() > 4 {
                    c.remove(0);
                }
                idx
            }
            Err(e) => {
                tracing::warn!("歷史 TLE 查詢失敗（{key}），退回現行索引：{e:#}");
                self.index()
            }
        }
    }
}
