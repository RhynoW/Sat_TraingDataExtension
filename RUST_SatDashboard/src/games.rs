//! 太空小遊戲（僅單機版）：/games 頁面與需要大量計算的 API。
//!
//! - 月球模擬：全部在瀏覽器端計算（astronomy-engine JS 版），後端只提供頁面。
//! - 星座壅擠：依各家公開申請的軌道殼層產生假想 Walker 星座（可放大到十萬顆），
//!   與真實目錄（SGP4）一起取多個時刻快照，以 KD-tree 篩出相距 d 以內的配對，
//!   用氣體動力學關係「進入半徑 d 球的頻率 = 球內配對數 × 相對速度 ÷ (4d/3)」估計接近頻率，
//!   再依通量與 d² 成正比換算到 1 km（避碰機動的代理門檻）與 10 m（碰撞）。
//! - 百萬顆：假想星座總數上限 100 萬顆（FCC 2026-11-25 核准 SpaceX 軌道資料中心最多 100 萬顆）；
//!   殼層縮放以 u64 與上限檢查計算（資安檢測 H-6：原本 u32 相乘可溢位繞過上限）。
//!   長期風險與管控的統計模型見 games_mega.rs（背景族群）與 web/ext/games_mega.js（計算核心）。
//! - 重運算並行上限（資安檢測 H-5／H-7）：星座壅擠、天文夢魘、兵推蒙地卡羅與 AI 對 AI 推演
//!   同時最多 HEAVY_MAX 個，超過回 503，避免多個請求占滿 CPU 讓整個服務停擺。

use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Duration, Utc};
use kiddo::immutable::float::kdtree::ImmutableKdTree;
use kiddo::SquaredEuclidean;
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::physics::{eci_to_llh, gmst_rad, Observer, R_EARTH_KM};
use crate::{assets, index::SatInfo, state::AppState};

const MU: f64 = 398600.4418;
const J2: f64 = 1.08262668e-3;

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/games", get(page))
        .route("/api/games/crowd/shells", get(crowd_shells))
        .route("/api/games/crowd/catalog", get(crowd_catalog))
        .route("/api/games/crowd", post(crowd))
        .route("/api/games/mega/background", get(crate::games_mega::background_api))
        .route("/api/games/breakup", post(crate::games_debris::breakup_api))
        .route("/api/games/astro", post(crate::games_astro::astro_api))
        .route("/api/games/war/new", post(crate::games_war::war_new))
        .route("/api/games/war/state", get(crate::games_war::war_state))
        .route("/api/games/war/cables", get(crate::games_war::war_cables))
        .route("/api/games/war/orders", post(crate::games_war::war_orders))
        .route("/api/games/war/mc", post(crate::games_war::war_mc))
}

async fn page() -> Html<String> {
    let raw = assets::get("ext/games.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}

fn bad(msg: &str) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response()
}

// ── 星座殼層樣板 ──────────────────────────────────────────────────────────
// (高度 km, 傾角°, 軌道面數, 每面顆數)；Walker-delta 相位因子 F = 1
type Shell = (f64, f64, u32, u32);

struct Group {
    key: &'static str,
    name: &'static str,
    /// 目錄 constellation 欄位（真實衛星）
    catalog: &'static str,
    color: &'static str,
    shells: &'static [Shell],
    note: &'static str,
}

const GROUPS: &[Group] = &[
    Group {
        key: "starlink",
        name: "Starlink",
        catalog: "Starlink",
        color: "#3fa7ff",
        // Gen1（4,408）＋ Gen2 申請（29,988）
        shells: &[
            (550.0, 53.0, 72, 22), (540.0, 53.2, 72, 22), (570.0, 70.0, 36, 20), (560.0, 97.6, 6, 58), (560.0, 97.6, 4, 43),
            (340.0, 53.0, 48, 110), (345.0, 46.0, 48, 110), (350.0, 38.0, 48, 110), (360.0, 96.9, 30, 120),
            (525.0, 53.0, 28, 120), (530.0, 43.0, 28, 120), (535.0, 33.0, 28, 120), (604.0, 148.0, 12, 12), (614.0, 115.7, 18, 18),
        ],
        note: "Gen1 4,408 顆＋Gen2 申請 29,988 顆的殼層（FCC 申請文件，近似）",
    },
    Group {
        key: "kuiper",
        name: "Amazon Kuiper",
        catalog: "Kuiper",
        color: "#ff9f1c",
        shells: &[(630.0, 51.9, 34, 34), (610.0, 42.0, 36, 36), (590.0, 33.0, 28, 28)],
        note: "FCC 2020 核准的 3,236 顆三殼層",
    },
    Group {
        key: "qianfan",
        name: "千帆（Qianfan）",
        catalog: "千帆/Qianfan",
        color: "#ff5c5c",
        shells: &[(1060.0, 89.0, 36, 36), (1100.0, 50.0, 60, 60), (1150.0, 70.0, 60, 60), (1200.0, 40.0, 48, 48)],
        note: "首期 1,296 顆約 1,060 km、89°（公開報導）；其餘殼層依申報規模估計的示意配置",
    },
    Group {
        key: "guowang",
        name: "國網（Guowang）",
        catalog: "國網/Guowang",
        color: "#c084fc",
        shells: &[
            (590.0, 85.0, 16, 30), (600.0, 50.0, 40, 50), (508.0, 55.0, 60, 60),
            (1145.0, 30.0, 48, 36), (1145.0, 45.0, 48, 36), (1145.0, 60.0, 48, 36), (1145.0, 85.0, 48, 36),
        ],
        note: "ITU 申報 GW-A59（6,080 顆）與 GW-2（6,912 顆），殼層近似",
    },
    Group {
        key: "starmind",
        name: "SpaceX 軌道資料中心（Starmind）",
        catalog: "Starmind",
        color: "#f0f6fc",
        // 六殼層 500–1,002 km（FCC 2026-11-25 核准；各殼層實際高度與傾角未公開，傾角為示意）
        shells: &[
            (500.0, 53.0, 360, 463), (600.0, 53.0, 360, 463), (700.0, 70.0, 360, 463),
            (800.0, 97.6, 360, 463), (900.0, 53.0, 360, 463), (1002.0, 97.6, 360, 463),
        ],
        note: "FCC 2026-11-25 有條件核准最多 100 萬顆（2040-11 全數部署）；六殼層 500–1,002 km，各殼層高度與傾角未公開，此為示意配置",
    },
];

/// 假想衛星總數上限（全部群組合計）
pub(crate) const MAX_SYNTHETIC: u64 = 1_000_000;
/// 自訂殼層的軌道面數、每面顆數與殼層數上限
const MAX_PLANES: u32 = 5000;
const MAX_PER_PLANE: u32 = 5000;
const MAX_SHELLS: usize = 64;

/// 假想群組請求的入口檢查（星座壅擠與天文夢魘共用；資安檢測 H-5）
pub(crate) fn check_groups(groups: &[GroupReq]) -> Result<(), &'static str> {
    let total: u64 = groups.iter().filter(|g| g.synthetic).map(|g| g.total as u64).sum();
    if total > MAX_SYNTHETIC {
        return Err("假想衛星總數上限 100 萬顆");
    }
    if groups.len() > 16 || groups.iter().any(|g| g.shells.as_ref().is_some_and(|v| v.len() > MAX_SHELLS)) {
        return Err("群組或自訂殼層數量過多");
    }
    Ok(())
}

/// 同時進行的重運算上限（各計算內部已用 rayon 平行化，多開只會互搶 CPU）
const HEAVY_MAX: usize = 2;
static HEAVY_RUNNING: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// 重運算許可：離開作用域（含 panic）時自動歸還
pub(crate) struct HeavyPermit(());
impl Drop for HeavyPermit {
    fn drop(&mut self) {
        HEAVY_RUNNING.fetch_sub(1, std::sync::atomic::Ordering::AcqRel);
    }
}

/// 取得重運算許可；已達上限時回傳可直接回應的 503
pub(crate) fn heavy_permit() -> Result<HeavyPermit, Response> {
    use std::sync::atomic::Ordering;
    // 先占位再檢查；超過上限就交由 HeavyPermit 的 drop 歸還
    let permit = HeavyPermit(());
    if HEAVY_RUNNING.fetch_add(1, Ordering::AcqRel) < HEAVY_MAX {
        Ok(permit)
    } else {
        drop(permit);
        Err((StatusCode::SERVICE_UNAVAILABLE, Json(json!({"error": "伺服器正在進行其他大量計算，請稍候再試"}))).into_response())
    }
}

fn group_by_key(k: &str) -> Option<(usize, &'static Group)> {
    GROUPS.iter().enumerate().find(|(_, g)| g.key == k)
}

/// 依目標總數等比例縮放各殼層（保留軌道面數，調整每面顆數）；回傳（樣板中的殼層序號, 殼層）
fn scaled(g: &Group, total: u32) -> Vec<(usize, Shell)> {
    scaled_from(g.shells, total)
}

fn scaled_from(shells: &[Shell], total: u32) -> Vec<(usize, Shell)> {
    // H-6：以 u64 計算、略過不合理的殼層，避免 u32 相乘溢位讓總數失真
    let shells: Vec<Shell> = shells
        .iter()
        .take(MAX_SHELLS)
        .copied()
        .filter(|&(h, i, p, s)| h.is_finite() && i.is_finite() && (100.0..=50000.0).contains(&h) && (1..=MAX_PLANES).contains(&p) && (1..=MAX_PER_PLANE).contains(&s))
        .collect();
    let total = (total as u64).min(MAX_SYNTHETIC);
    let n0: u64 = shells.iter().map(|s| s.2 as u64 * s.3 as u64).sum();
    let k = total as f64 / n0.max(1) as f64;
    shells
        .iter()
        .enumerate()
        .filter_map(|(j, &(h, i, p, s))| {
            let c = ((p as u64 * s as u64) as f64 * k).round().min(MAX_SYNTHETIC as f64) as u32;
            if c == 0 {
                return None;
            }
            let planes = p.min(c);
            let per = ((c as f64 / planes as f64).round() as u32).max(1);
            Some((j, (h, i, planes, per)))
        })
        .collect()
}

/// 殼層的相位偏移（弧度）：升交點赤經偏移不到一個軌道面間隔、緯度幅角偏移不到一個衛星間隔。
/// 各殼層若都從同一相位起點排列，參數相近的殼層（例如 550 km／53° 與 540 km／53.2°）會產生並肩飛行的假想衛星。
/// 偏移只依（群組序號, 樣板殼層序號）決定，與請求順序和縮放無關，同參數結果可重現；
/// 以黃金比例與塑膠數的小數部分做低差異序列，讓各殼層的偏移彼此錯開。
fn shell_phase(gi: usize, j: usize, planes: u32, per: u32) -> (f64, f64) {
    let m = (gi * 32 + j + 1) as f64;
    let fr = (m * 0.618_033_988_749_895).fract();
    let fu = (m * 0.754_877_666_246_693).fract();
    (std::f64::consts::TAU * fr / planes as f64, std::f64::consts::TAU * fu / per as f64)
}

#[derive(Deserialize, Clone)]
pub(crate) struct GroupReq {
    pub(crate) key: String,
    /// None 或 false：沿用真實目錄；true：以 total 顆假想星座取代真實衛星
    #[serde(default)]
    pub(crate) synthetic: bool,
    #[serde(default)]
    pub(crate) total: u32,
    /// 自訂殼層（高度, 傾角, 軌道面數, 每面顆數）取代樣板；供殼層配置敏感度測試
    #[serde(default)]
    pub(crate) shells: Option<Vec<Shell>>,
}

fn group_counts(st: &Arc<AppState>) -> Vec<usize> {
    let idx = st.index();
    GROUPS
        .iter()
        .map(|g| idx.sats.values().filter(|s| s.constellation.as_deref() == Some(g.catalog) && s.prop.is_some()).count())
        .collect()
}

async fn crowd_shells(State(st): State<Arc<AppState>>) -> Response {
    let counts = tokio::task::spawn_blocking(move || group_counts(&st)).await.unwrap_or_default();
    let groups: Vec<Value> = GROUPS
        .iter()
        .enumerate()
        .map(|(i, g)| {
            json!({"key": g.key, "name": g.name, "color": g.color, "note": g.note,
                   "planned": g.shells.iter().map(|s| s.2 * s.3).sum::<u32>(),
                   "real": counts.get(i).copied().unwrap_or(0)})
        })
        .collect();
    Json(json!({"groups": groups})).into_response()
}

/// 全目錄 TLE（前端 Web Worker 傳播顯示用）：[norad, 群組（0 其他、1… 依 GROUPS）, line1, line2]
async fn crowd_catalog(State(st): State<Arc<AppState>>) -> Response {
    tokio::task::spawn_blocking(move || {
        let idx = st.index();
        let rows: Vec<Value> = idx
            .sats
            .values()
            .filter(|s| s.prop.is_some() && !s.line1.is_empty() && !s.line2.is_empty())
            .map(|s| json!([s.norad_id, catalog_group(s), s.line1, s.line2]))
            .collect();
        Json(json!({"count": rows.len(), "sats": rows})).into_response()
    })
    .await
    .unwrap_or_else(|_| bad("目錄讀取失敗"))
}

fn catalog_group(s: &SatInfo) -> u8 {
    match s.constellation.as_deref() {
        Some(c) => GROUPS.iter().position(|g| g.catalog == c).map(|p| (p + 1) as u8).unwrap_or(0),
        None => 0,
    }
}

// ── 物件與傳播 ────────────────────────────────────────────────────────────
pub(crate) struct Walker {
    a: f64,
    inc: f64,
    raan0: f64,
    u0: f64,
    raan_dot: f64,
    u_dot: f64,
}

impl Walker {
    fn new(h: f64, inc_deg: f64, raan0: f64, u0: f64) -> Self {
        let a = R_EARTH_KM + h;
        let n = (MU / (a * a * a)).sqrt();
        let inc = inc_deg.to_radians();
        let k = 1.5 * J2 * (R_EARTH_KM / a).powi(2);
        let ci = inc.cos();
        // J2 長期項：Ω̇ = −k·n·cos i；近地點幅角＋平近點角的漂移合併為 u̇ = n·[1 + k(4cos²i − 1)]
        Self { a, inc, raan0, u0, raan_dot: -k * n * ci, u_dot: n * (1.0 + k * (4.0 * ci * ci - 1.0)) }
    }
    /// 慣性座標（與 TEME 同一組軸）位置、速度
    pub(crate) fn state(&self, dt: f64) -> ([f64; 3], [f64; 3]) {
        let om = self.raan0 + self.raan_dot * dt;
        let u = self.u0 + self.u_dot * dt;
        let (so, co) = om.sin_cos();
        let (su, cu) = u.sin_cos();
        let (si, ci) = self.inc.sin_cos();
        let r = [self.a * (co * cu - so * su * ci), self.a * (so * cu + co * su * ci), self.a * su * si];
        let v0 = self.a * self.u_dot;
        let v = [v0 * (-co * su - so * cu * ci), v0 * (-so * su + co * cu * ci), v0 * cu * si];
        (r, v)
    }
}

pub(crate) enum Obj<'a> {
    Cat(&'a SatInfo),
    Syn(Walker),
}

pub(crate) struct Item<'a> {
    pub(crate) obj: Obj<'a>,
    pub(crate) group: u8,
    /// 假想星座的殼層編號（同殼層由營運者協調，可選擇不計）；目錄物件為 u32::MAX
    pub(crate) shell: u32,
}

pub(crate) fn sgp4_state(s: &SatInfo, t: &DateTime<Utc>) -> Option<([f64; 3], [f64; 3])> {
    let p = s.prop.as_ref()?;
    let ns = (t.naive_utc() - p.epoch).num_nanoseconds()?;
    let pr = p.constants.propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9)).ok()?;
    let r = pr.position;
    let m2 = r[0] * r[0] + r[1] * r[1] + r[2] * r[2];
    (r.iter().all(|v| v.is_finite()) && m2 > 6478.0 * 6478.0 && m2 < 50000.0 * 50000.0).then_some((r, pr.velocity))
}

pub(crate) fn build_items<'a>(sats: &'a [&'a SatInfo], reqs: &[GroupReq]) -> (Vec<Item<'a>>, Vec<Value>) {
    let mut replaced = vec![false; GROUPS.len()];
    let mut items: Vec<Item> = Vec::new();
    let mut shells_out = Vec::new();
    let mut shell_id: u32 = 0;
    let mut syn_count: u64 = 0;
    for rq in reqs {
        let Some((gi, g)) = group_by_key(&rq.key) else { continue };
        if !rq.synthetic {
            continue;
        }
        // 所有群組合計不超過上限（同時保護共用 build_items 的天文夢魘，資安檢測 H-5）
        if syn_count >= MAX_SYNTHETIC {
            break;
        }
        replaced[gi] = true;
        let sh = match &rq.shells {
            Some(v) if !v.is_empty() => scaled_from(v, rq.total),
            _ => scaled(g, rq.total),
        };
        for (j, (h, inc, p, s)) in sh {
            let (raan0, u0) = shell_phase(gi, j, p, s);
            if syn_count + p as u64 * s as u64 > MAX_SYNTHETIC + MAX_SYNTHETIC / 100 {
                break; // 縮放取整的誤差容許 1%，超過就停止加入
            }
            syn_count += p as u64 * s as u64;
            for pi in 0..p {
                for si in 0..s {
                    let raan = raan0 + std::f64::consts::TAU * pi as f64 / p as f64;
                    let u = u0 + std::f64::consts::TAU * (si as f64 / s as f64 + pi as f64 / (p * s) as f64);
                    items.push(Item { obj: Obj::Syn(Walker::new(h, inc, raan, u)), group: (gi + 1) as u8, shell: shell_id });
                }
            }
            shells_out.push(json!({"group": g.key, "alt": h, "inc": inc, "planes": p, "per_plane": s,
                                   "raan0": raan0, "u0": u0}));
            shell_id += 1;
        }
    }
    for s in sats {
        let g = catalog_group(s);
        if g > 0 && replaced[(g - 1) as usize] {
            continue;
        }
        items.push(Item { obj: Obj::Cat(s), group: g, shell: u32::MAX });
    }
    (items, shells_out)
}

const NG: usize = GROUPS.len() + 1;

struct Stats {
    /// 各群組物件數
    count: [usize; NG],
    /// 每秒進入 d 球的配對次數（群組 × 群組，上三角）
    rate: [[f64; NG]; NG],
    pairs_mean: f64,
    sky10: f64,
    sky30: f64,
    snapshots: usize,
    /// 追蹤物件（第三方目錄物件與指定 NORAD）在 items 中的索引
    tracked: Vec<usize>,
    /// 追蹤物件每秒進入 d 球的次數：[與任何物件, 與星座群組（group > 0）]
    trk_rate: Vec<[f64; 2]>,
}

/// skip：0 全部都計；1 同殼層（假想星座）不計；2 同星座（含真實目錄）不計——假設營運者完全協調
fn run(items: &[Item], t0: &DateTime<Utc>, steps: usize, step_s: f64, d_km: f64, skip: u8, watch: &[u32]) -> Stats {
    let obs = Observer::new(25.0330, 121.5654, 0.01);
    // 追蹤：所有第三方目錄物件（group 0）與指定 NORAD
    let tracked: Vec<usize> = items
        .iter()
        .enumerate()
        .filter(|(_, it)| match &it.obj {
            Obj::Cat(s) => it.group == 0 || watch.contains(&s.norad_id),
            Obj::Syn(_) => false,
        })
        .map(|(i, _)| i)
        .collect();
    let mut slot = vec![u32::MAX; items.len()];
    for (k, &i) in tracked.iter().enumerate() {
        slot[i] = k as u32;
    }
    let nt = tracked.len();
    let mut st = Stats { count: [0; NG], rate: [[0.0; NG]; NG], pairs_mean: 0.0, sky10: 0.0, sky30: 0.0, snapshots: 0,
                         trk_rate: vec![[0.0; 2]; nt], tracked };
    for it in items {
        st.count[it.group as usize] += 1;
    }
    let d2 = d_km * d_km;
    let chord = 4.0 * d_km / 3.0;
    for k in 0..steps {
        let dt = k as f64 * step_s;
        let t = *t0 + Duration::milliseconds((dt * 1000.0) as i64);
        let states: Vec<Option<([f64; 3], [f64; 3])>> = items
            .par_iter()
            .map(|it| match &it.obj {
                Obj::Cat(s) => sgp4_state(s, &t),
                Obj::Syn(w) => Some(w.state(dt)),
            })
            .collect();
        let mut pts = Vec::with_capacity(items.len());
        let mut map = Vec::with_capacity(items.len());
        for (i, s) in states.iter().enumerate() {
            if let Some((r, _)) = s {
                pts.push(*r);
                map.push(i);
            }
        }
        if pts.len() < 2 {
            continue;
        }
        let g = gmst_rad(&t);
        let (s10, s30) = pts
            .par_iter()
            .map(|r| {
                let (el, _, _) = obs.elaz(r, g);
                ((el > 10.0) as u32, (el > 30.0) as u32)
            })
            .reduce(|| (0, 0), |a, b| (a.0 + b.0, a.1 + b.1));
        st.sky10 += s10 as f64;
        st.sky30 += s30 as f64;
        let tree: ImmutableKdTree<f64, u64, 3, 32> = ImmutableKdTree::new_from_slice(&pts);
        let (acc, npairs, trk) = (0..pts.len())
            .into_par_iter()
            .fold(
                || ([[0.0f64; NG]; NG], 0usize, vec![[0.0f64; 2]; nt]),
                |(mut acc, mut n, mut trk), a| {
                    for nn in tree.within_unsorted::<SquaredEuclidean>(&pts[a], d2) {
                        let b = nn.item as usize;
                        if b <= a {
                            continue;
                        }
                        let (ia, ib) = (&items[map[a]], &items[map[b]]);
                        if (skip == 1 && ia.shell != u32::MAX && ia.shell == ib.shell)
                            || (skip == 2 && ia.group > 0 && ia.group == ib.group)
                        {
                            continue;
                        }
                        let va = states[map[a]].unwrap().1;
                        let vb = states[map[b]].unwrap().1;
                        let vr = ((va[0] - vb[0]).powi(2) + (va[1] - vb[1]).powi(2) + (va[2] - vb[2]).powi(2)).sqrt();
                        let (x, y) = (ia.group.min(ib.group) as usize, ia.group.max(ib.group) as usize);
                        acc[x][y] += vr / chord;
                        n += 1;
                        let (sa, sb) = (slot[map[a]], slot[map[b]]);
                        if sa != u32::MAX {
                            trk[sa as usize][0] += vr / chord;
                            if ib.group > 0 {
                                trk[sa as usize][1] += vr / chord;
                            }
                        }
                        if sb != u32::MAX {
                            trk[sb as usize][0] += vr / chord;
                            if ia.group > 0 {
                                trk[sb as usize][1] += vr / chord;
                            }
                        }
                    }
                    (acc, n, trk)
                },
            )
            .reduce(
                || ([[0.0f64; NG]; NG], 0usize, vec![[0.0f64; 2]; nt]),
                |(mut a, na, mut ta), (b, nb, tb)| {
                    for i in 0..NG {
                        for j in 0..NG {
                            a[i][j] += b[i][j];
                        }
                    }
                    for (x, y) in ta.iter_mut().zip(tb.iter()) {
                        x[0] += y[0];
                        x[1] += y[1];
                    }
                    (a, na + nb, ta)
                },
            );
        for (x, y) in st.trk_rate.iter_mut().zip(trk.iter()) {
            x[0] += y[0];
            x[1] += y[1];
        }
        for i in 0..NG {
            for j in 0..NG {
                st.rate[i][j] += acc[i][j];
            }
        }
        st.pairs_mean += npairs as f64;
        st.snapshots += 1;
    }
    let n = st.snapshots.max(1) as f64;
    for row in st.rate.iter_mut() {
        for v in row.iter_mut() {
            *v /= n;
        }
    }
    st.pairs_mean /= n;
    st.sky10 /= n;
    st.sky30 /= n;
    for x in st.trk_rate.iter_mut() {
        x[0] /= n;
        x[1] /= n;
    }
    st
}

/// 第三方物件分解：依目錄 purpose（有效載荷／火箭體／碎片／不明）與 t0 時之高度 50 km × 傾角 10° 分格；
/// 另列指定 NORAD 之逐顆結果。數值皆為每顆每年 1 km 內接近次數（與任何物件、與星座群組）。
fn tracked_json(s: &Stats, items: &[Item], t0: &DateTime<Utc>, d_km: f64, watch: &[u32]) -> Value {
    let k = 365.25 * 86400.0 * (1.0 / d_km).powi(2);
    let g = gmst_rad(t0);
    let cls = |p: &str| match p {
        "有效載荷" => "payload",
        "火箭體" => "rocket_body",
        "碎片" => "debris",
        _ => "unknown",
    };
    let mut by_cls: std::collections::BTreeMap<&str, (usize, f64, f64)> = Default::default();
    let mut cells: std::collections::BTreeMap<(i32, i32), (usize, f64, f64)> = Default::default();
    let mut w = Vec::new();
    for (j, &i) in s.tracked.iter().enumerate() {
        let Obj::Cat(sat) = &items[i].obj else { continue };
        let [r_any, r_con] = s.trk_rate[j];
        if items[i].group == 0 {
            let e = by_cls.entry(cls(&sat.purpose)).or_default();
            e.0 += 1;
            e.1 += r_any;
            e.2 += r_con;
            if let Some((r, v)) = sgp4_state(sat, t0) {
                let h = eci_to_llh(&r, g)[2];
                let hv = [r[1] * v[2] - r[2] * v[1], r[2] * v[0] - r[0] * v[2], r[0] * v[1] - r[1] * v[0]];
                let hn = (hv[0] * hv[0] + hv[1] * hv[1] + hv[2] * hv[2]).sqrt();
                let inc = (hv[2] / hn).acos().to_degrees();
                let c = cells.entry(((h / 50.0).floor() as i32 * 50, (inc / 10.0).floor() as i32 * 10)).or_default();
                c.0 += 1;
                c.1 += r_any;
                c.2 += r_con;
            }
        }
        if watch.contains(&sat.norad_id) {
            w.push(json!({"norad": sat.norad_id, "name": sat.name, "group": items[i].group,
                          "per_year_1km": r_any * k, "per_year_1km_constellation": r_con * k}));
        }
    }
    let classes: Vec<Value> = by_cls
        .iter()
        .map(|(c, (n, a, b))| json!({"class": c, "count": n, "per_sat_year_1km": a * k / *n as f64,
                                      "per_sat_year_1km_constellation": b * k / *n as f64, "total_year_1km": a * k}))
        .collect();
    let grid: Vec<Value> = cells
        .iter()
        .map(|((h, i), (n, a, b))| json!({"alt": h, "inc": i, "count": n, "total_year_1km": a * k,
                                          "total_year_1km_constellation": b * k}))
        .collect();
    json!({"classes": classes, "grid": grid, "watch": w})
}

fn stats_json(s: &Stats, d_km: f64) -> Value {
    let year = 365.25 * 86400.0;
    let k1 = (1.0 / d_km).powi(2);
    let kc = (0.01 / d_km).powi(2); // 合併硬體半徑 10 m
    let total: f64 = s.rate.iter().flatten().sum();
    let mut groups = Vec::new();
    for g in 0..NG {
        if s.count[g] == 0 {
            continue;
        }
        let mut r = 0.0;
        for h in 0..NG {
            let (x, y) = (g.min(h), g.max(h));
            r += if g == h { 2.0 * s.rate[x][y] } else { s.rate[x][y] };
        }
        let per_sat_year = r * year / s.count[g] as f64;
        groups.push(json!({
            "key": if g == 0 { "other" } else { GROUPS[g - 1].key },
            "name": if g == 0 { "其他（含碎片、火箭體）" } else { GROUPS[g - 1].name },
            "count": s.count[g],
            "per_sat_year_1km": per_sat_year * k1,
            "per_sat_year_coll": per_sat_year * kc,
        }));
    }
    json!({
        "objects": s.count.iter().sum::<usize>(),
        "groups": groups,
        "enc_day_d": total * 86400.0,
        "enc_day_1km": total * 86400.0 * k1,
        "coll_year": total * year * kc,
        "pairs_within_d": s.pairs_mean,
        "sky10": s.sky10,
        "sky30": s.sky30,
        "snapshots": s.snapshots,
    })
}

/// 高度密度剖面（每 10 km 一格，物件數 ÷ 球殼體積，個／km³）
fn density(items: &[Item], t: &DateTime<Utc>) -> Vec<f64> {
    let g = gmst_rad(t);
    let mut bins = vec![0usize; 186]; // 150–2000 km
    let alts: Vec<Option<f64>> = items
        .par_iter()
        .map(|it| {
            let r = match &it.obj {
                Obj::Cat(s) => sgp4_state(s, t)?.0,
                Obj::Syn(w) => w.state(0.0).0,
            };
            Some(eci_to_llh(&r, g)[2])
        })
        .collect();
    for h in alts.into_iter().flatten() {
        if (150.0..2010.0).contains(&h) {
            bins[((h - 150.0) / 10.0) as usize] += 1;
        }
    }
    bins.iter()
        .enumerate()
        .map(|(i, &c)| {
            let r = R_EARTH_KM + 155.0 + i as f64 * 10.0;
            c as f64 / (4.0 * std::f64::consts::PI * r * r * 10.0)
        })
        .collect()
}

#[derive(Deserialize)]
struct CrowdReq {
    groups: Vec<GroupReq>,
    hours: Option<f64>,
    step_s: Option<f64>,
    d_km: Option<f64>,
    /// 0 全部、1 同殼層不計、2 同星座不計
    skip: Option<u8>,
    /// 推演起點（RFC 3339）；未給時為伺服器現在時刻
    t0: Option<String>,
    /// 另列逐顆結果之 NORAD 編號
    watch: Option<Vec<u32>>,
}

async fn crowd(State(st): State<Arc<AppState>>, Json(rq): Json<CrowdReq>) -> Response {
    let hours = rq.hours.unwrap_or(2.0).clamp(0.25, 24.0);
    let step_s = rq.step_s.unwrap_or(60.0).clamp(10.0, 600.0);
    let d_km = rq.d_km.unwrap_or(20.0).clamp(2.0, 100.0);
    let skip = rq.skip.unwrap_or(1).min(2);
    if let Err(e) = check_groups(&rq.groups) {
        return bad(e);
    }
    if rq.watch.as_ref().is_some_and(|w| w.len() > 1000) {
        return bad("watch 最多 1000 筆");
    }
    let permit = match heavy_permit() {
        Ok(p) => p,
        Err(r) => return r,
    };
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        let t_start = std::time::Instant::now();
        let idx = st.index();
        let sats: Vec<&SatInfo> = idx.sats.values().filter(|s| s.prop.is_some()).collect();
        let t0 = rq.t0.as_deref().and_then(|s| DateTime::parse_from_rfc3339(s).ok()).map(|d| d.with_timezone(&Utc)).unwrap_or_else(Utc::now);
        let watch = rq.watch.clone().unwrap_or_default();
        let steps = ((hours * 3600.0 / step_s).round() as usize).max(1);
        let (base, _) = build_items(&sats, &[]);
        let (scen, shells) = build_items(&sats, &rq.groups);
        let sb = run(&base, &t0, steps, step_s, d_km, skip, &watch);
        let ss = run(&scen, &t0, steps, step_s, d_km, skip, &watch);
        let mut alt = Vec::new();
        for i in 0..186 {
            alt.push(155 + i * 10);
        }
        Json(json!({
            "t0": t0.to_rfc3339(),
            "hours": hours, "step_s": step_s, "d_km": d_km, "skip": skip,
            "baseline": stats_json(&sb, d_km),
            "scenario": stats_json(&ss, d_km),
            "third_party": {"baseline": tracked_json(&sb, &base, &t0, d_km, &watch),
                            "scenario": tracked_json(&ss, &scen, &t0, d_km, &watch)},
            "density": {"alt_km": alt, "baseline": density(&base, &t0), "scenario": density(&scen, &t0)},
            "shells": shells,
            "elapsed_s": t_start.elapsed().as_secs_f64(),
        }))
        .into_response()
    })
    .await
    .unwrap_or_else(|_| bad("計算失敗"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scaled_overflow_and_cap() {
        // H-6：p·s 在 u32 會溢位的殼層（65536×65536）被濾掉，不會讓總數失真
        let v = scaled_from(&[(550.0, 53.0, 65536, 65536), (550.0, 53.0, 10, 10)], 1000);
        let n: u64 = v.iter().map(|(_, s)| s.2 as u64 * s.3 as u64).sum();
        assert_eq!(n, 1000);
        // 上限 100 萬
        let v = scaled_from(&[(550.0, 53.0, 100, 100)], u32::MAX);
        let n: u64 = v.iter().map(|(_, s)| s.2 as u64 * s.3 as u64).sum();
        assert!(n <= MAX_SYNTHETIC + MAX_SYNTHETIC / 100, "{n}");
        // Starmind 樣板約 100 萬顆
        let g = group_by_key("starmind").unwrap().1;
        let n: u64 = g.shells.iter().map(|s| s.2 as u64 * s.3 as u64).sum();
        assert!((990_000..=1_010_000).contains(&n), "{n}");
        // build_items：多群組合計不超過上限
        let reqs: Vec<GroupReq> = ["starlink", "kuiper", "starmind"].iter()
            .map(|k| GroupReq { key: k.to_string(), synthetic: true, total: 1_000_000, shells: None }).collect();
        let (items, _) = build_items(&[], &reqs);
        assert!(items.len() as u64 <= MAX_SYNTHETIC + MAX_SYNTHETIC / 100, "{}", items.len());
    }

    #[test]
    fn group_checks_and_heavy_limit() {
        // H-5：入口檢查（天文夢魘與星座壅擠共用）
        let g = |total: u32, shells: Option<Vec<Shell>>| GroupReq { key: "starlink".into(), synthetic: true, total, shells };
        assert!(check_groups(&[g(u32::MAX, None)]).is_err());
        assert!(check_groups(&[g(600_000, None), g(600_000, None)]).is_err());
        assert!(check_groups(&[g(1000, Some(vec![(550.0, 53.0, 10, 10); 65]))]).is_err());
        assert!(check_groups(&vec![g(1, None); 17]).is_err());
        assert!(check_groups(&[g(1_000_000, None)]).is_ok());
        // 真實目錄（synthetic=false）不計入總數
        assert!(check_groups(&[GroupReq { key: "starlink".into(), synthetic: false, total: u32::MAX, shells: None }]).is_ok());
        // H-5／H-7：重運算並行上限，歸還後可再取得
        let a = heavy_permit().ok().unwrap();
        let b = heavy_permit().ok().unwrap();
        assert!(heavy_permit().is_err());
        drop(a);
        let c = heavy_permit().ok().unwrap();
        assert!(heavy_permit().is_err());
        drop((b, c));
        assert_eq!(HEAVY_RUNNING.load(std::sync::atomic::Ordering::Acquire), 0);
    }
}
