//! 太空小遊戲「太空兵棋」：海纜中斷下的太空通訊韌性（紅藍對抗＋白方 GM，WEGO 同時下令）
//!
//! 參考：謝沛學〈從遊戲到實戰：商用兵棋軟體如何協助軍事分析與訓練〉（國防安全雙週報，2020）——
//! 視覺化、軍民通用、多人連線與蒙地卡羅分析。這裡是教育用的抽象模型，數值為示意。
//!
//! - 伺服器權威：狀態只在伺服器，雙方各自提交命令，兩方都交（或由 AI 代下）後一起裁決；可重現（固定種子）
//! - 海纜：取自內嵌的 TeleGeography 圖資中經過台灣周邊的海纜；國際海纜每條 10 單位頻寬，離島海纜 1 單位
//! - 每回合 6 小時、共 8 回合；需求 100 單位
//! - 蒙地卡羅：雙方都由 AI 依策略下令，跑 N 局統計可用率、升級指數與碎片事件
//! - 想定（scenario）：`base` 原始想定；`a` 依 DIA《Challenges to Security in Space 2026》的灰色地帶描述
//!   （商用衛星終端被列為合法目標、Viasat 惡意軟體、Starlink 干擾），細節見 docs/games_war_scenarios.md。
//!   `a_pre`（只預置終端、不受攻擊的對照組）、`a_nojam`、`a_nocyber` 是拆解用變體，只供蒙地卡羅分析。
//!   `b` 依同一報告「致盲並致聾敵人」的描述（偵察、通信、導航衛星；GPS 與 SAR 干擾），`b_typhoon` 為開場颱風變體。
//!   `c` 依同一報告的共軌接近描述（TJS-3 在 GEO 接近他國太空器、Cosmos 2543 跟蹤美國衛星後釋放投射物），
//!   紅方檢查衛星逼近藍方租用的 GEO 通信衛星；`c_loiter` 是紅方只接近、不攻擊的對照組（只供蒙地卡羅分析）。
//!   `d` 依同一報告的直升式反衛星描述（中國 2007 年試射、俄羅斯 Nudol 2021 年試射；碎片威脅所有國家、容易歸因），
//!   紅方可擊毀藍方自有的光學偵察衛星或商用低軌星座的一顆衛星；`d_noasat` 是紅方不用反衛星的對照組（只供蒙地卡羅分析）。

use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::{assets, state::AppState};

/// 國際頻寬需求：危機期間逐回合上升（政府、金融、媒體流量湧入）
/// 第 8 回合（48 小時）後持平：延長窗口（turns > 8）時不再外推危機初期的需求成長（假設）；8 回合內與原本相同
fn demand(t: u32) -> f64 { 150.0 + 5.0 * t.min(8) as f64 }
const MAX_TURNS: u32 = 8;
const AP: i32 = 5;
const LEO_PER_TERM: f64 = 0.02;
/// 想定 A：開戰前已在使用的商用低軌終端（示意）
const A_PRE_TERMS: f64 = 1000.0;
/// 想定 A：開戰前惡意軟體抹除的終端比例；未強化時每次網攻永久損失的比例（示意）
const A_WIPE: f64 = 0.3;
/// 想定 B：GPS 被干擾時的定位授時可用率；有備援定位授時時（示意）
const B_PNT_JAMMED: f64 = 0.3;
const B_PNT_BACKUP: f64 = 0.8;
/// 想定 B：SAR 每次過頂的成功率（不受雲量與雷射致盲影響；被 SAR 干擾時減半）（示意）
const B_SAR_P: f64 = 0.8;
/// 想定 C：近距離攻擊時，藍方 GEO 頻寬放在被盯上那顆衛星的比例；分散租用後（示意）
const C_HOST_SHARE: f64 = 0.5;
const C_HOST_SHARE_SPREAD: f64 = 0.25;
/// 想定 C：GEO 衛星規避機動那一回合的服務比例（示意）
const C_EVADE_DIP: f64 = 0.7;
/// 碎片對低軌容量的影響：每單位碎片 −10%（最多 −50%）；想定 D 業者避碰機動期間減半（示意）
const DEBRIS_HIT: f64 = 0.1;
const DEBRIS_HIT_AVOID: f64 = 0.05;
/// 敏感度分析用的參數覆寫（只供蒙地卡羅 API；預設值等於上面的常數與原本的 AI 規則，省略時結果與修改前完全相同）。
/// 機率參數為 1.0 時不抽亂數，所以預設情況下亂數序列也不變。全部是示意假設，不是 DIA 數據
#[derive(Clone, Deserialize)]
#[serde(default)]
pub struct Params {
    /// 想定 A：開戰前抹除比例與未強化時每次網攻永久抹除的比例
    a_wipe: f64,
    /// 紅方 AI 不得下令的行動（單一手段基準、不干擾對照組）；省下的點數照原優先序用在其他行動
    red_ban: Vec<String>,
    /// 想定 B：GPS 被干擾時的定位授時可用率；SAR 每次過頂成功率
    b_pnt_jammed: f64,
    b_sar_p: f64,
    /// 想定 C：灰色地帶紅方在 10 km 內每回合出手機率（藍方未監視／已監視：後者代表紅方的風險偏好）
    c_p_strike: f64,
    c_p_strike_tracked: f64,
    /// 想定 C：監視資料每回合有效的機率（資料品質與更新率）；有效追蹤下攻擊被歸因的機率；規避成功率；規避次回合的服務比例
    c_track_p: f64,
    c_attrib_p: f64,
    c_evade_p: f64,
    c_evade_dip: f64,
    /// 想定 D：自有光學衛星被毀後，商業影像的偵察效能比例（1.0 = 完全替代）
    d_img_factor: f64,
    /// 想定 D：紅方目標偏好。"adaptive"（預設：藍方有影像備援時灰色地帶紅方不出手、升級紅方改打商用星座）；"isr"（不論備援一律打光學衛星）
    d_red_pref: String,
    /// ── 2026-11-23 擴充（延伸篇 S3 審查）；預設值不抽亂數、不改行動順序，結果與擴充前逐局相同 ──
    /// 每局回合數（每回合 6 小時；28 = 7 天）
    turns: u32,
    /// GEO 可受攻擊：紅方「干擾 GEO 上行鏈路」使 GEO 容量下降的比例（0 = 紅方不使用，與原模型相同），持續 2 回合，抗干擾減半
    geo_jam: f64,
    /// GEO 可受攻擊：每回合租用 GEO 服務中斷（閘道站受攻擊或業者中斷）的機率，中斷當回合 GEO 容量減半
    geo_outage_p: f64,
    /// 紅方風險偏好：切纜、網攻、反衛星與想定 C／D 出手機率的倍數（0.5 保守、1 基準、1.5 激進；上限 1）
    red_aggr: f64,
    /// 紅方目標選擇："base"（原本的固定優先序）、"random"（每回合隨機排列切纜、干擾 GEO、干擾低軌、網攻的順序）、
    /// "adaptive"（第 1 回合起看藍方的 GEO 與低軌容量，先打較大者：簡單適應）
    red_target: String,
    /// 想定 D：藍方有商業影像備援時，紅方改換目標的機率（每局決定一次；1 = 原本的 adaptive）
    d_switch_p: f64,
    /// 想定 D：紅方在藍方簽商業影像後，延遲幾回合才改換目標（期間照打光學衛星）
    d_switch_delay: u32,
    /// 想定 C：歸因成功時藍方的聲望加分（政治後果；原本 3）
    c_attrib_rep: f64,
    /// 想定 C：紅方衛星在 10 km 內但未出手時，藍方每回合誤把異常歸因於紅方的機率（誤歸因：聲望 −2、升級 +2）
    c_misattrib_p: f64,
}

impl Default for Params {
    fn default() -> Self {
        Params { a_wipe: A_WIPE, red_ban: vec![], b_pnt_jammed: B_PNT_JAMMED, b_sar_p: B_SAR_P, c_p_strike: 0.3, c_p_strike_tracked: 0.1,
                 c_track_p: 1.0, c_attrib_p: 1.0, c_evade_p: 1.0, c_evade_dip: C_EVADE_DIP, d_img_factor: 1.0, d_red_pref: "adaptive".into(),
                 turns: MAX_TURNS, geo_jam: 0.0, geo_outage_p: 0.0, red_aggr: 1.0, red_target: "base".into(), d_switch_p: 1.0, d_switch_delay: 0,
                 c_attrib_rep: 3.0, c_misattrib_p: 0.0 }
    }
}

/// 已知的想定代號；其他名稱一律視為 base
fn scen_name(s: &str) -> &str {
    match s { "a" | "a_pre" | "a_nojam" | "a_nocyber" | "b" | "b_typhoon" | "c" | "c_loiter" | "d" | "d_noasat" => s, _ => "base" }
}

struct Rng(u64);
impl Rng {
    fn f(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        ((z ^ (z >> 31)) >> 11) as f64 / (1u64 << 53) as f64
    }
}

#[derive(Clone)]
struct Cable {
    name: String,
    intl: bool,
    cut: bool,
    repair_at: Option<u32>,
    coords: Value,
}

/// 經過台灣周邊（東經 118.0–123.0、北緯 21.5–26.5）的海纜
static CABLES: Lazy<Vec<Cable>> = Lazy::new(|| {
    let raw = assets::get("static/data/cable-geo.json").unwrap_or_default();
    let v: Value = serde_json::from_slice(&raw).unwrap_or(Value::Null);
    let mut out = Vec::new();
    for f in v["features"].as_array().into_iter().flatten() {
        let geo = &f["geometry"]["coordinates"];
        let near = geo.as_array().into_iter().flatten().flat_map(|l| l.as_array().into_iter().flatten()).any(|p| {
            let (x, y) = (p[0].as_f64().unwrap_or(0.0), p[1].as_f64().unwrap_or(0.0));
            (119.2..122.2).contains(&x) && (21.8..25.5).contains(&y)
        });
        if !near {
            continue;
        }
        let name = f["properties"]["name"].as_str().unwrap_or("?").to_string();
        if out.iter().any(|c: &Cable| c.name == name) {
            continue;
        }
        let dom = ["Penghu", "Matsu", "Kinmen", "Taiwan Strait Express"].iter().any(|k| name.contains(k));
        out.push(Cable { name, intl: !dom, cut: false, repair_at: None, coords: geo.clone() });
    }
    out
});

#[derive(Clone, Deserialize)]
pub struct Action {
    kind: String,
    #[serde(default)]
    arg: Option<usize>,
}

fn cost(kind: &str) -> i32 {
    match kind {
        "geo_lease" | "leo_deploy" | "anti_jam" | "patrol" => 2,
        "repair" => 3,
        "harden" | "isr" | "diplomacy" => 1,
        "sar_isr" | "pnt_backup" => 2,
        "jam_gps" | "jam_sar" => 1,
        "sda_track" | "geo_spread" => 1,
        "geo_evade" | "rpo_approach" => 2,
        "rpo_strike" => 3,
        "buy_imagery" | "debris_avoid" => 1,
        "cut_cable" | "jam_leo" | "cyber_gateway" | "jam_geo" => 2,
        "dazzle" | "propaganda" => 1,
        "asat" | "asat_isr" => 4,
        _ => 99,
    }
}
fn is_blue(kind: &str) -> bool {
    matches!(kind, "geo_lease" | "leo_deploy" | "anti_jam" | "patrol" | "repair" | "harden" | "isr" | "diplomacy" | "sar_isr" | "pnt_backup"
        | "sda_track" | "geo_evade" | "geo_spread" | "buy_imagery" | "debris_avoid")
}
/// 只在特定想定可用的行動：'b' 想定 B、'c' 想定 C
fn scen_only(kind: &str) -> Option<char> {
    match kind {
        "sar_isr" | "pnt_backup" | "jam_gps" | "jam_sar" => Some('b'),
        "sda_track" | "geo_evade" | "geo_spread" | "rpo_approach" | "rpo_strike" => Some('c'),
        "buy_imagery" | "debris_avoid" | "asat_isr" => Some('d'),
        _ => None,
    }
}

#[derive(Clone)]
struct War {
    rng: Rng,
    turn: u32,
    cables: Vec<Cable>,
    geo: f64,
    geo_pending: f64,
    leo_terms: f64,
    leo_pending: f64,
    hardened: bool,
    patrol_until: u32,
    jam: f64,
    jam_until: u32,
    gateway_down_until: u32,
    debris: f64,
    asat_used: bool,
    escalation: f64,
    reputation: f64,
    storm_until: u32,
    typhoon_until: u32,
    isr_ok: u32,
    isr_try: u32,
    orders_blue: Option<Vec<Action>>,
    orders_red: Option<Vec<Action>>,
    white_queue: Vec<String>,
    log: Vec<Value>,
    history: Vec<Value>,
    ai_blue: Option<String>,
    ai_red: Option<String>,
    over: bool,
    scenario: String,
    cyber_lost: f64,
    pnt_backup_from: u32,
    pnt: f64,
    sar_seen: bool,
    sar_ok: u32,
    sar_try: u32,
    /// 想定 C：紅方檢查衛星與藍方租用 GEO 衛星的距離階段（0：> 100 km、1：< 100 km、2：< 10 km）
    rpo: u32,
    /// 藍方最後一次看到的距離階段（沒有太空監視時不更新）
    rpo_seen: Option<u32>,
    track_until: u32,
    spread: bool,
    struck: bool,
    attributed: bool,
    evades: u32,
    evade_dip: u32,
    geo_lost: f64,
    /// 可租用的 GEO 頻寬上限；想定 C 被攻擊的那顆衛星失效後跟著下降
    geo_cap: f64,
    /// 想定 D：藍方自有光學偵察衛星是否已被擊毀；是否已簽商業影像合約；業者避碰機動到第幾回合
    isr_sat_dead: bool,
    imagery: bool,
    avoid_until: u32,
    /// GEO 上行鏈路干擾、GEO 服務中斷（2026-11-23 擴充）
    geo_jam_frac: f64,
    geo_jam_until: u32,
    geo_out_until: u32,
    misattributed: u32,
    /// 想定 D：簽商業影像的回合；紅方是否會因備援改換目標（每局決定一次）
    imagery_from: u32,
    d_switch: Option<bool>,
    /// 敏感度分析的參數覆寫（一般對局用預設值）
    p: Params,
}

impl Clone for Rng {
    fn clone(&self) -> Self { Rng(self.0) }
}

impl War {
    fn new_p(seed: u64, ai_blue: Option<String>, ai_red: Option<String>, scenario: &str, p: Params) -> War {
        let scenario = scen_name(scenario).to_string();
        let mut w = War {
            rng: Rng(seed ^ 0xA5A5_1234), turn: 0, cables: CABLES.clone(), geo: 5.0, geo_pending: 0.0, leo_terms: 0.0, leo_pending: 0.0,
            hardened: false, patrol_until: 0, jam: 0.0, jam_until: 0, gateway_down_until: 0, debris: 0.0, asat_used: false,
            escalation: 0.0, reputation: 0.0, storm_until: 0, typhoon_until: 0, isr_ok: 0, isr_try: 0,
            orders_blue: None, orders_red: None, white_queue: vec![], log: vec![], history: vec![], ai_blue, ai_red, over: false,
            scenario, cyber_lost: 0.0, pnt_backup_from: u32::MAX, pnt: 1.0, sar_seen: false, sar_ok: 0, sar_try: 0,
            rpo: 0, rpo_seen: None, track_until: 0, spread: false, struck: false, attributed: false, evades: 0, evade_dip: u32::MAX, geo_lost: 0.0, geo_cap: 60.0, isr_sat_dead: false, imagery: false, avoid_until: 0,
            geo_jam_frac: 0.0, geo_jam_until: 0, geo_out_until: 0, misattributed: 0, imagery_from: u32::MAX, d_switch: None, p,
        };
        // 想定開場：數條國際海纜與馬祖海纜同時中斷（灰色地帶「拖錨」）
        let mut intl: Vec<usize> = (0..w.cables.len()).filter(|&i| w.cables[i].intl).collect();
        let n_cut = (intl.len() as f64 * 0.3).round() as usize;
        for _ in 0..n_cut.min(intl.len()) {
            let k = (w.rng.f() * intl.len() as f64) as usize % intl.len();
            let i = intl.remove(k);
            w.cables[i].cut = true;
        }
        for c in w.cables.iter_mut().filter(|c| c.name.contains("Matsu")) {
            c.cut = true;
        }
        let cut: Vec<String> = w.cables.iter().filter(|c| c.cut).map(|c| c.name.clone()).collect();
        w.say("white", format!("想定開始：{} 條海纜同時中斷（{}）。國際頻寬需求 {} 單位（每回合 +5）。", cut.len(), cut.join("、"), demand(0)));
        if w.is_a() {
            // DIA 2026：商用衛星通信自開戰便支援烏克蘭（p.37）；2022-02-24 入侵前惡意軟體攻擊 Viasat 客戶（p.43）
            w.leo_terms = A_PRE_TERMS;
            w.say("white", format!("想定 A：藍方已有 {} 套商用低軌終端在使用中。紅方宣稱支援藍方的商用終端是合法軍事目標。", A_PRE_TERMS));
            if w.a_cyber() {
                let lost = w.leo_terms * w.p.a_wipe;
                w.leo_terms -= lost;
                w.cyber_lost += lost;
                w.say("red", format!("開戰前惡意軟體抹除 {lost:.0} 套終端的韌體，必須換新才能恢復。"));
            }
            if w.a_jam() {
                w.jam = 0.25;
                w.jam_until = 2;
                w.escalation += 2.0;
                w.say("red", "開場即偵測到針對商用低軌終端的干擾（2 回合）。".into());
            }
        }
        if w.is_b() {
            // DIA 2026 p.18：偵察、通信、導航與預警衛星可能成為「致盲並致聾敵人」的目標
            w.say("white", "想定 B：紅方意圖「致盲並致聾」藍方，偵察、通信與導航衛星都是目標。藍方可用全天候 SAR 偵察與備援定位授時。".into());
            if w.scenario == "b_typhoon" {
                w.typhoon_until = 2;
                w.say("white", "颱風來襲：雲量大增，光學偵察困難，修纜船延後（2 回合）。".into());
            }
        }
        if w.is_c() {
            // DIA 2026 p.33：TJS-3 宣稱為實驗通信衛星，2023 年多次在 GEO 接近他國太空器至 10 km 內；
            // 近距離接近大多與宣稱任務不一致。p.44：Cosmos 2576 被送入與美國衛星相同的軌道
            w.rpo_seen = Some(0);
            w.say("white", "想定 C：紅方一顆宣稱為「通信技術試驗」的衛星進入與藍方租用 GEO 通信衛星相同的軌道（目前距離 > 100 km）。它是檢查衛星還是武器，無從得知。".into());
        }
        w.record();
        w
    }

    fn is_a(&self) -> bool { self.scenario.starts_with('a') }
    fn a_jam(&self) -> bool { self.scenario == "a" || self.scenario == "a_nocyber" }
    fn a_cyber(&self) -> bool { self.scenario == "a" || self.scenario == "a_nojam" }
    fn is_b(&self) -> bool { self.scenario == "b" || self.scenario == "b_typhoon" }
    fn is_c(&self) -> bool { self.scenario == "c" || self.scenario == "c_loiter" }
    fn is_d(&self) -> bool { self.scenario == "d" || self.scenario == "d_noasat" }
    fn allowed(&self, kind: &str) -> bool {
        match scen_only(kind) { None => true, Some('b') => self.is_b(), Some('c') => self.is_c(), Some('d') => self.is_d(), _ => false }
    }

    fn say(&mut self, side: &str, text: String) {
        self.log.push(json!({"turn": self.turn, "side": side, "text": text}));
    }

    fn caps(&self) -> (f64, f64, f64) {
        let t = self.turn;
        let cable: f64 = self.cables.iter().filter(|c| !c.cut).map(|c| if c.intl { 10.0 } else { 1.0 }).sum();
        let storm = t < self.storm_until;
        let geo = self.geo * if storm { 0.7 } else { 1.0 } * if t == self.evade_dip { self.p.c_evade_dip } else { 1.0 }
            * if t < self.geo_jam_until { 1.0 - self.geo_jam_frac } else { 1.0 } * if t < self.geo_out_until { 0.5 } else { 1.0 };
        let jam = if t < self.jam_until { self.jam } else { 0.0 };
        let gw = if t < self.gateway_down_until { 0.5 } else { 1.0 };
        let leo = self.leo_terms * LEO_PER_TERM * (1.0 - jam) * gw * (1.0 - if t < self.avoid_until { DEBRIS_HIT_AVOID } else { DEBRIS_HIT } * self.debris).max(0.5) * if storm { 0.8 } else { 1.0 };
        (cable, geo, leo)
    }

    fn record(&mut self) {
        let (c, g, l) = self.caps();
        let avail = ((c + g + l) / demand(self.turn)).min(1.0);
        let cut = self.cables.iter().filter(|x| x.cut).count();
        self.history.push(json!({"turn": self.turn, "demand": demand(self.turn), "cable": c, "geo": g, "leo": l, "avail": avail, "cut": cut,
            "escalation": self.escalation, "debris": self.debris, "isr_ok": self.isr_ok, "isr_try": self.isr_try, "leo_terms": self.leo_terms, "pnt": self.pnt, "rpo": self.rpo}));
    }

    fn white(&mut self, ev: &str) {
        let t = self.turn;
        match ev {
            "storm" => { self.storm_until = t + 2; self.say("white", "白方事件：強烈太陽風暴，GEO 容量 −30%、低軌 −20%，持續 2 回合。".into()); }
            "typhoon" => { self.typhoon_until = t + 2; for c in self.cables.iter_mut() { if let Some(r) = c.repair_at { c.repair_at = Some(r + 1); } } self.say("white", "白方事件：颱風，雲量大增（光學偵察困難），修纜船延後 1 回合。".into()); }
            "ship" => {
                if let Some(c) = self.cables.iter_mut().find(|c| c.cut && c.repair_at.is_none()) {
                    c.repair_at = Some(t + 1);
                    let n = c.name.clone();
                    self.say("white", format!("白方事件：國際修纜船提前到位，{n} 預計下回合修復。"));
                }
            }
            _ => {}
        }
    }

    fn ai(&mut self, blue: bool) -> Vec<Action> {
        let style = if blue { self.ai_blue.clone() } else { self.ai_red.clone() }.unwrap_or_else(|| "balanced".into());
        let mut ap = AP;
        let mut out = Vec::new();
        let ban: Vec<String> = if blue { vec![] } else { self.p.red_ban.clone() };
        let push = |out: &mut Vec<Action>, ap: &mut i32, k: &str, arg: Option<usize>| {
            if !ban.iter().any(|b| b == k) && cost(k) <= *ap { *ap -= cost(k); out.push(Action { kind: k.into(), arg }); }
        };
        let t = self.turn;
        if blue {
            let cut: Vec<usize> = (0..self.cables.len()).filter(|&i| self.cables[i].cut && self.cables[i].intl && self.cables[i].repair_at.is_none()).collect();
            // 想定 D「避碰」：均衡打法，碎片出現後先協調業者避碰
            if style == "avoid" && self.is_d() && self.debris > 0.0 && t >= self.avoid_until { push(&mut out, &mut ap, "debris_avoid", None); }
            match style.as_str() {
                "geo" => { push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "geo_lease", None); }
                "leo" => { if !self.hardened { push(&mut out, &mut ap, "harden", None); } push(&mut out, &mut ap, "leo_deploy", None); push(&mut out, &mut ap, "leo_deploy", None); }
                "repair" => { for &i in cut.iter().take(1) { push(&mut out, &mut ap, "repair", Some(i)); } push(&mut out, &mut ap, "patrol", None); }
                // 想定 B：先保住偵察與定位授時，剩下的點數才補頻寬
                "sensor" if self.is_b() => {
                    if self.pnt_backup_from == u32::MAX { push(&mut out, &mut ap, "pnt_backup", None); }
                    push(&mut out, &mut ap, "sar_isr", None);
                    if t == 0 { push(&mut out, &mut ap, "harden", None); }
                    else if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); }
                    else { push(&mut out, &mut ap, "geo_lease", None); }
                }
                // 想定 B 折衷：開場建立備援定位授時，之後修纜＋SAR，其餘同均衡
                "hybrid" if self.is_b() => {
                    if t == 0 { push(&mut out, &mut ap, "pnt_backup", None); push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "harden", None); }
                    else {
                        if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); } else { push(&mut out, &mut ap, "leo_deploy", None); }
                        push(&mut out, &mut ap, "sar_isr", None);
                    }
                }
                // 想定 C：以均衡打法為底，只把第 0 回合的閘道站強化換成 C 專屬行動（強化延到第 1 回合）
                // watch：購買商業太空監視資料（被攻擊時可歸因）；evade：另外在看到紅方衛星進到 10 km 內時讓 GEO 衛星規避；
                // spread：把 GEO 頻寬分散到多家業者
                // 想定 D「重 GEO＋商業影像」：第 1 回合用原本的光學偵察那 1 點簽商業影像，之後同重 GEO
                "imagery" if self.is_d() => {
                    if !self.imagery { push(&mut out, &mut ap, "buy_imagery", None); }
                    push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "geo_lease", None);
                }
                "watch" | "evade" | "spread" if self.is_c() => {
                    if t == 0 {
                        push(&mut out, &mut ap, if style == "spread" { "geo_spread" } else { "sda_track" }, None);
                        push(&mut out, &mut ap, "geo_lease", None);
                        push(&mut out, &mut ap, "leo_deploy", None);
                    } else {
                        if style == "evade" && self.rpo_seen == Some(2) && !self.struck { push(&mut out, &mut ap, "geo_evade", None); }
                        if !self.hardened { push(&mut out, &mut ap, "harden", None); }
                        if t < self.jam_until && self.leo_terms > 1000.0 { push(&mut out, &mut ap, "anti_jam", None); }
                        if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); }
                        push(&mut out, &mut ap, "leo_deploy", None);
                    }
                }
                // 閾值規則（2026-11-23）：可用率 ≥ 90% 時只補低軌；低於 90% 時先抗干擾、修纜，再補 GEO 與低軌中較小的一方
                "threshold" => {
                    if t == 0 { push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "leo_deploy", None); push(&mut out, &mut ap, "harden", None); }
                    else {
                        let (c, g, l) = self.caps();
                        if (c + g + l) / demand(t) >= 0.9 { push(&mut out, &mut ap, "leo_deploy", None); }
                        else {
                            if t < self.jam_until && self.leo_terms > 0.0 { push(&mut out, &mut ap, "anti_jam", None); }
                            if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); }
                            push(&mut out, &mut ap, if g < l { "geo_lease" } else { "leo_deploy" }, None);
                        }
                    }
                }
                // 簡單效用（2026-11-23）：每點行動點換到的「剩餘回合容量」最大者優先（貪婪；不預測紅方行動）
                "utility" => {
                    let rem = (self.p.turns.saturating_sub(t)) as f64;
                    loop {
                        let jam = if t < self.jam_until { self.jam } else { 0.0 };
                        let mut cands: Vec<(f64, &str, Option<usize>)> = vec![
                            ((self.geo_cap - self.geo - self.geo_pending).clamp(0.0, 15.0) * (rem - 1.0).max(0.0) / 2.0, "geo_lease", None),
                            (if self.leo_terms + self.leo_pending < 4000.0 { 500.0 * LEO_PER_TERM * (1.0 - jam) * (rem - 1.0).max(0.0) / 2.0 } else { 0.0 }, "leo_deploy", None),
                        ];
                        if let Some(&i) = cut.iter().find(|&&i| !out.iter().any(|a: &Action| a.kind == "repair" && a.arg == Some(i))) {
                            cands.push((10.0 * (rem - 3.0).max(0.0) / 3.0, "repair", Some(i)));
                        }
                        if jam > 0.0 && !out.iter().any(|a| a.kind == "anti_jam") {
                            cands.push((self.leo_terms * LEO_PER_TERM * jam * 0.5 * (self.jam_until - t) as f64 / 2.0, "anti_jam", None));
                        }
                        if !self.hardened && !out.iter().any(|a| a.kind == "harden") {
                            cands.push((self.leo_terms.max(500.0) * LEO_PER_TERM * 0.5 * rem.min(2.0), "harden", None));
                        }
                        cands.retain(|c| c.0 > 0.0 && cost(c.1) <= ap);
                        let Some(best) = cands.into_iter().max_by(|a, b| a.0.partial_cmp(&b.0).unwrap()) else { break };
                        push(&mut out, &mut ap, best.1, best.2);
                        if ap <= 1 { break; }
                    }
                }
                _ => {
                    if t == 0 { push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "leo_deploy", None); push(&mut out, &mut ap, "harden", None); }
                    else {
                        if t < self.jam_until && self.leo_terms > 1000.0 { push(&mut out, &mut ap, "anti_jam", None); }
                        if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); }
                        push(&mut out, &mut ap, "leo_deploy", None);
                    }
                }
            }
            if !self.isr_sat_dead || self.imagery { push(&mut out, &mut ap, "isr", None); }
            push(&mut out, &mut ap, "diplomacy", None);
        } else {
            let aggressive = style == "escalate";
            let intact: Vec<usize> = (0..self.cables.len()).filter(|&i| !self.cables[i].cut && self.cables[i].intl).collect();
            if self.is_d() {
                // 想定 D：升級紅方第 4 回合起每回合 50% 機率試射；藍方已有商業影像備援時，改打商用低軌星座（示範性攻擊）。
                // 灰色地帶紅方只在藍方自有光學衛星正在偵察、且沒有備援時，第 3 回合起每回合 30% 機率擊毀它。
                // 藍方有備援時灰色地帶紅方不出手（阻絕式嚇阻）。出手機率與目標選擇是 AI 行為假設；d_noasat 完全不用反衛星
                if self.scenario == "d" && !self.asat_used {
                    // d_red_pref = "isr"（敏感度分析）：不理會藍方的影像備援，一律打光學衛星
                    let adaptive = self.p.d_red_pref != "isr";
                    // 2026-11-23：d_switch_p < 1 時，每局決定一次紅方是否因備援改換目標；d_switch_delay 為簽約後延遲幾回合才改換
                    let mut adaptive = adaptive;
                    if adaptive && self.imagery {
                        if self.p.d_switch_p < 1.0 && self.d_switch.is_none() { let sw = self.rng.f() < self.p.d_switch_p; self.d_switch = Some(sw); }
                        if self.d_switch == Some(false) || t < self.imagery_from.saturating_add(self.p.d_switch_delay) { adaptive = false; }
                    }
                    let ag = self.p.red_aggr;
                    let fire = if aggressive { t >= 3 && self.rng.f() < (0.5 * ag).min(1.0) }
                        else { t >= 2 && (!self.imagery || !adaptive) && !self.isr_sat_dead && self.isr_try > 0 && self.rng.f() < (0.3 * ag).min(1.0) };
                    if fire { push(&mut out, &mut ap, if self.imagery && adaptive { "asat" } else { "asat_isr" }, None); }
                }
            } else if aggressive && !self.asat_used && t >= 3 && self.rng.f() < (0.5 * self.p.red_aggr).min(1.0) { push(&mut out, &mut ap, "asat", None); }
            if self.is_c() && !self.struck {
                // 想定 C：先逼近到 10 km 內；灰色地帶紅方第 4 回合起每回合 30% 機率出手（知道藍方在追蹤、攻擊會被歸因時降到 10%），
                // 升級紅方一到位就出手。c_loiter 只接近、不攻擊（量測「威脅存在」本身的代價）。出手機率是 AI 行為假設
                let p_strike = (if t < self.track_until { self.p.c_p_strike_tracked } else { self.p.c_p_strike } * self.p.red_aggr).min(1.0);
                let strike = self.rpo == 2 && self.scenario == "c" && (aggressive || (t >= 3 && self.rng.f() < p_strike));
                if strike { push(&mut out, &mut ap, "rpo_strike", None); }
                else if self.rpo < 2 { push(&mut out, &mut ap, "rpo_approach", None); }
            }
            // 2026-11-23：目標順序可由 red_target 改變；預設（base）與原本完全相同：切纜 →（想定 B 專屬）→ 干擾 GEO（geo_jam > 0 才用）→ 干擾低軌 → 網攻
            let mut ops: Vec<&str> = vec!["cut", "b", "jam_geo", "jam_leo", "cyber"];
            match self.p.red_target.as_str() {
                "random" => {
                    let mut pool = vec!["cut", "jam_geo", "jam_leo", "cyber"];
                    let mut order = Vec::new();
                    while !pool.is_empty() { let k = (self.rng.f() * pool.len() as f64) as usize % pool.len(); order.push(pool.remove(k)); }
                    ops = vec!["b"]; ops.extend(order);
                }
                "adaptive" if t >= 1 => {
                    let (_, g, l) = self.caps();
                    ops = if g >= l { vec!["b", "jam_geo", "cut", "jam_leo", "cyber"] } else { vec!["b", "jam_leo", "cut", "jam_geo", "cyber"] };
                }
                _ => {}
            }
            let ag = self.p.red_aggr;
            for op in ops {
                match op {
                    "cut" => {
                        if !intact.is_empty() && self.rng.f() < (0.7 * ag).min(1.0) {
                            let k = (self.rng.f() * intact.len() as f64) as usize % intact.len();
                            push(&mut out, &mut ap, "cut_cable", Some(intact[k]));
                        }
                    }
                    "b" => {
                        if self.is_b() {
                            // 想定 B：致盲並致聾（DIA p.18）——先干擾導航與偵察，剩下的點數才打通信
                            push(&mut out, &mut ap, "jam_gps", None);
                            push(&mut out, &mut ap, "dazzle", None);
                            if self.sar_seen { push(&mut out, &mut ap, "jam_sar", None); }
                        }
                    }
                    "jam_geo" => { if self.p.geo_jam > 0.0 && self.geo >= 10.0 { push(&mut out, &mut ap, "jam_geo", None); } }
                    "jam_leo" => {
                        // 想定 A：商用終端一出現就是目標（DIA p.4、37）；A 系列四組共用門檻 0，避免拆解變體因抹除後低於 800 套而延後被干擾（2026-11-22 修正）
                        let jam_th = if self.is_a() { 0.0 } else { 800.0 };
                        if self.leo_terms + self.leo_pending > jam_th { push(&mut out, &mut ap, "jam_leo", None); }
                    }
                    "cyber" => { if !self.hardened && self.rng.f() < (0.5 * ag).min(1.0) { push(&mut out, &mut ap, "cyber_gateway", None); } }
                    _ => {}
                }
            }
            if !self.is_b() { push(&mut out, &mut ap, "dazzle", None); }
            push(&mut out, &mut ap, "propaganda", None);
        }
        out
    }

    fn resolve(&mut self) {
        let t = self.turn;
        for ev in std::mem::take(&mut self.white_queue) { self.white(&ev); }
        // 隨機事件
        if self.rng.f() < 0.08 { self.white("storm"); }
        let blue: Vec<Action> = self.orders_blue.take().unwrap_or_default().into_iter().filter(|a| self.allowed(&a.kind)).collect();
        let red: Vec<Action> = self.orders_red.take().unwrap_or_default().into_iter().filter(|a| self.allowed(&a.kind)).collect();
        let has = |v: &Vec<Action>, k: &str| v.iter().any(|a| a.kind == k);
        if has(&blue, "patrol") { self.patrol_until = t + 2; self.say("blue", "藍方：海巡與海軍加強海纜區巡邏（2 回合）。".into()); }
        let anti_jam = has(&blue, "anti_jam");
        if has(&blue, "harden") && !self.hardened { self.hardened = true; self.say("blue", "藍方：低軌閘道站完成資安強化。".into()); }
        let dazzled = has(&red, "dazzle");
        let gps_jammed = has(&red, "jam_gps");
        let sar_jammed = has(&red, "jam_sar");
        if has(&blue, "pnt_backup") && self.pnt_backup_from == u32::MAX {
            self.pnt_backup_from = t + 1;
            self.say("blue", "藍方：啟用備援定位授時（多星系接收、慣性與地面備援），下回合起生效。".into());
        }
        // 想定 C：共軌接近（WEGO 同時裁決：分散、監視先生效；攻擊、接近、規避依序結算）
        let evading = has(&blue, "geo_evade");
        let mut tracked = t < self.track_until;
        if has(&blue, "geo_spread") && !self.spread {
            self.spread = true;
            self.say("blue", "藍方：把 GEO 頻寬分散到多家業者的衛星（任何一顆被攻擊只損失約四分之一）。".into());
        }
        if has(&blue, "sda_track") && self.track_until != u32::MAX {
            // DIA p.64：沒有先進太空追蹤感測器的國家，可透過購買商業資料獲得基本 SDA
            self.track_until = u32::MAX;
            tracked = true;
            self.say("blue", "藍方：購買商業太空監視資料，之後持續追蹤紅方衛星。".into());
        }
        // 敏感度分析：監視資料本回合可能中斷或未更新（紅方仍以為自己被監視，所以紅方 AI 的出手率不受影響）
        if tracked && self.is_c() && self.p.c_track_p < 1.0 && self.rng.f() >= self.p.c_track_p {
            tracked = false;
            self.say("blue", "藍方：本回合太空監視資料中斷或未更新。".into());
        }
        let evade_ok = evading && (self.p.c_evade_p >= 1.0 || self.rng.f() < self.p.c_evade_p);
        let struck_before = self.struck;
        if has(&red, "rpo_strike") && !self.struck {
            if self.rpo < 2 {
                self.say("red", "紅方衛星距離不夠，未能採取行動。".into());
            } else if evade_ok {
                self.rpo = 1;
                self.escalation += 1.0;
                self.say("red", "紅方衛星向 GEO 衛星急速逼近，但目標已機動，未造成損害。".into());
            } else {
                // DIA p.44：Cosmos 2543 離開美國衛星後向軌道發射投射物；p.71：天基武器可造成暫時或永久損害
                self.struck = true;
                let share = if self.spread { C_HOST_SHARE_SPREAD } else { C_HOST_SHARE };
                let lost = self.geo * share;
                self.geo -= lost;
                // 那顆衛星上的轉頻器跟著失效：可租用上限同比例下降，不能靠續租補回
                self.geo_cap *= 1.0 - share;
                self.geo_lost = lost;
                self.escalation += 6.0;
                if tracked && (self.p.c_attrib_p >= 1.0 || self.rng.f() < self.p.c_attrib_p) {
                    self.attributed = true;
                    self.escalation += 4.0;
                    self.reputation += self.p.c_attrib_rep;
                    self.say("red", format!("藍方租用的 GEO 通信衛星失效，損失 {lost:.0} 單位頻寬。太空監視資料顯示紅方衛星事前逼近到 10 km 內，國際社會譴責紅方。"));
                } else {
                    self.say("red", format!("藍方租用的 GEO 通信衛星突然失效，損失 {lost:.0} 單位頻寬。{}", if tracked { "追蹤資料不足以證明是人為攻擊。" } else { "沒有追蹤資料，無法證明是人為攻擊。" }));
                }
            }
        }
        if has(&red, "rpo_approach") && !self.struck && self.rpo < 2 {
            self.rpo += 1;
            self.escalation += 0.5;
            if tracked { self.say("red", format!("太空監視：紅方衛星逼近藍方租用的 GEO 衛星（距離 {}）。", if self.rpo >= 2 { "< 10 km" } else { "< 100 km" })); }
        }
        if evading && !struck_before {
            self.evade_dip = t + 1;
            self.evades += 1;
            if evade_ok {
                self.rpo = self.rpo.saturating_sub(1);
                self.say("blue", format!("藍方：GEO 衛星業者執行規避機動，拉開距離；下回合服務暫降 {:.0}%。", (1.0 - self.p.c_evade_dip) * 100.0));
            } else {
                self.say("blue", "藍方：GEO 衛星業者執行規避機動，但未能拉開距離。".into());
            }
        }
        if tracked && self.is_c() { self.rpo_seen = Some(self.rpo); }
        // 2026-11-23：誤歸因（紅方在 10 km 內但本回合未出手，藍方把其他異常歸因於紅方）；預設機率 0 不抽亂數
        if self.is_c() && self.p.c_misattrib_p > 0.0 && tracked && self.rpo == 2 && !has(&red, "rpo_strike") && !self.struck
            && self.rng.f() < self.p.c_misattrib_p {
            self.misattributed += 1;
            self.reputation -= 2.0;
            self.escalation += 2.0;
            self.say("blue", "藍方公開指控紅方衛星干擾，事後證據不足（誤歸因）。".into());
        }
        // 2026-11-23：GEO 租用服務中斷（閘道站或業者），預設機率 0 不抽亂數
        if self.p.geo_outage_p > 0.0 && self.rng.f() < self.p.geo_outage_p {
            // 可用率在回合推進後記錄（turn = t + 1），所以影響持續到 t + 2，才會反映在本回合結算的容量上
            self.geo_out_until = t + 2;
            self.say("white", "租用 GEO 服務中斷（閘道站或業者端），GEO 容量減半 1 回合。".into());
        }
        // 想定 D：商業影像合約（一次有效）、業者避碰機動（2 回合）
        if has(&blue, "buy_imagery") && !self.imagery {
            // DIA p.57：商業衛星影像的可得性提高
            self.imagery = true;
            self.imagery_from = t;
            self.say("blue", "藍方：簽訂商業衛星影像合約，自有光學衛星若被擊毀，仍可取得影像。".into());
        }
        if has(&blue, "debris_avoid") {
            // DIA p.56：碎片越多，衛星越要頻繁避碰，任務成本上升
            self.avoid_until = t + 2;
            self.say("blue", "藍方：協調低軌業者執行避碰機動（2 回合內碎片影響減半）。".into());
        }
        // 紅方
        for a in &red {
            match a.kind.as_str() {
                "cut_cable" => {
                    let i = a.arg.unwrap_or(0).min(self.cables.len().saturating_sub(1));
                    let p = if t < self.patrol_until { 0.3 } else { 0.7 };
                    self.escalation += 4.0;
                    if !self.cables[i].cut && self.rng.f() < p {
                        self.cables[i].cut = true;
                        self.cables[i].repair_at = None;
                        let n = self.cables[i].name.clone();
                        self.say("red", format!("{n} 中斷（疑似船錨拖斷）。"));
                    } else {
                        self.say("red", "可疑船隻在海纜區徘徊，未造成中斷。".into());
                    }
                }
                "jam_leo" => { self.jam = (self.jam + 0.25).min(0.6); self.jam_until = t + 2; self.escalation += 2.0; self.say("red", "偵測到針對低軌使用者終端的干擾。".into()); }
                // 2026-11-23：GEO 可受攻擊的敏感度情境（上行鏈路干擾）；預設 geo_jam = 0 時紅方不會下這個命令
                "jam_geo" => { self.geo_jam_frac = self.p.geo_jam; self.geo_jam_until = t + 2; self.escalation += 2.0; self.say("red", format!("偵測到針對租用 GEO 衛星上行鏈路的干擾（容量 −{:.0}%，2 回合）。", self.p.geo_jam * 100.0)); }
                "cyber_gateway" => {
                    self.escalation += 2.0;
                    if self.hardened { self.say("red", "低軌閘道站遭網攻，已強化，未受影響。".into()); }
                    else if self.a_cyber() {
                        // 想定 A：網攻可造成不可逆效果（DIA p.15–16、68）；AcidRain 抹除數據機（尾註 621）
                        let lost = self.leo_terms * self.p.a_wipe;
                        self.leo_terms -= lost;
                        self.cyber_lost += lost;
                        self.say("red", format!("惡意軟體經閘道站抹除 {lost:.0} 套終端，必須重新部署。"));
                    }
                    else { self.gateway_down_until = t + 2; self.say("red", "低軌閘道站遭網攻，容量減半 2 回合。".into()); }
                }
                "dazzle" => { self.escalation += 1.0; self.say("red", "光學偵察衛星疑遭雷射致盲干擾。".into()); }
                // 想定 B：PLA 演習例行納入上下行鏈路干擾，拒止 GPS 導航（DIA p.31–32）；GPS 干擾常波及民用（p.15）
                "jam_gps" => { self.escalation += 1.0; self.say("red", "藍方周邊 GPS 訊號遭干擾，船舶與航空定位異常（波及民用）。".into()); }
                // 中國商業組織為 PLA 開發 SAR 干擾器（DIA p.32）；Sentinel-1 在克里米亞上空遭干擾（p.43）
                "jam_sar" => { self.escalation += 1.0; self.say("red", "SAR 衛星影像出現干擾條紋。".into()); }
                "propaganda" => { self.reputation -= 1.0; }
                "asat" | "asat_isr" if !self.asat_used => {
                    self.asat_used = true;
                    self.debris += 1.0;
                    self.escalation += 15.0;
                    if !self.is_d() {
                        self.say("red", "紅方進行直升式反衛星試射，低軌碎片大增（所有低軌星系含紅方自己都受影響）。".into());
                    } else {
                        // DIA p.70：地基 ASAT 飛彈的發射可被偵測、會產生碎片，較容易歸因
                        self.reputation += 3.0;
                        if a.kind == "asat_isr" {
                            self.isr_sat_dead = true;
                            self.say("red", "紅方直升式反衛星飛彈擊毀藍方的光學偵察衛星，產生碎片雲。發射被偵測，國際社會譴責紅方。".into());
                        } else {
                            // 擴散星座少一顆衛星，容量影響可忽略；主要效果是碎片
                            self.say("red", "紅方直升式反衛星飛彈擊毀商用低軌星座的一顆衛星（星座仍有數百顆，容量幾乎不變），但碎片雲威脅所有低軌衛星。國際社會譴責紅方。".into());
                        }
                    }
                }
                _ => {}
            }
        }
        // 藍方
        for a in &blue {
            match a.kind.as_str() {
                "geo_lease" => { self.geo_pending += 15.0; self.say("blue", "藍方：租用 GEO 衛星頻寬 +15（下回合生效）。".into()); }
                "leo_deploy" => { self.leo_pending += 500.0; self.say("blue", "藍方：部署 500 套低軌衛星終端（下回合生效）。".into()); }
                "repair" => {
                    let i = a.arg.unwrap_or(0).min(self.cables.len().saturating_sub(1));
                    if self.cables[i].cut && self.cables[i].repair_at.is_none() {
                        let delay = if t < self.typhoon_until { 4 } else { 3 };
                        self.cables[i].repair_at = Some(t + delay);
                        let n = self.cables[i].name.clone();
                        self.say("blue", format!("藍方：派修纜船搶修 {n}（{delay} 回合）。"));
                    }
                }
                "diplomacy" => { self.reputation += 1.0; self.escalation += 0.5; }
                _ => {}
            }
        }
        if anti_jam && t < self.jam_until { self.jam *= 0.5; self.say("blue", "藍方：啟用抗干擾（跳頻、波束調整），干擾效果減半。".into()); }
        if anti_jam && t < self.geo_jam_until { self.geo_jam_frac *= 0.5; }
        // 情監偵：每回合 2 次過頂，成功率受雲量與致盲影響
        let mut n_isr = blue.iter().filter(|a| a.kind == "isr").count() as u32 * 2;
        if n_isr > 0 && self.isr_sat_dead && !self.imagery {
            // 想定 D：自有光學衛星已毀、又沒有商業影像備援
            n_isr = 0;
            self.say("blue", "藍方光學偵察衛星已被擊毀，本回合無法偵察。".into());
        }
        let cloud = if t < self.typhoon_until { 0.85 } else { 0.4 };
        // 想定 D：自有光學衛星已毀、改用商業影像時，效能乘上 d_img_factor（敏感度分析；預設 1.0 = 完全替代）
        let p_ok = (1.0 - cloud) * if dazzled { 0.5 } else { 1.0 } * if self.isr_sat_dead { self.p.d_img_factor } else { 1.0 };
        for _ in 0..n_isr {
            self.isr_try += 1;
            if self.rng.f() < p_ok { self.isr_ok += 1; }
        }
        let n_sar = blue.iter().filter(|a| a.kind == "sar_isr").count() as u32 * 2;
        if n_sar > 0 {
            let p_sar = self.p.b_sar_p * if sar_jammed { 0.5 } else { 1.0 };
            let before = self.sar_ok;
            for _ in 0..n_sar {
                self.isr_try += 1;
                self.sar_try += 1;
                if self.rng.f() < p_sar { self.isr_ok += 1; self.sar_ok += 1; }
            }
            self.sar_seen = true;
            let ok = self.sar_ok - before;
            self.say("blue", format!("藍方：SAR 全天候偵察 {n_sar} 次過頂，成功 {ok} 次{}。", if sar_jammed { "（遭干擾）" } else { "" }));
        }
        self.pnt = if !gps_jammed { 1.0 } else if t >= self.pnt_backup_from { B_PNT_BACKUP } else { self.p.b_pnt_jammed };
        // 推進到下一回合：修復完成、命令生效
        self.turn += 1;
        let nt = self.turn;
        let mut fixed = Vec::new();
        for c in self.cables.iter_mut() {
            if c.repair_at == Some(nt) { c.cut = false; c.repair_at = None; fixed.push(c.name.clone()); }
        }
        if !fixed.is_empty() { self.say("blue", format!("海纜修復：{}。", fixed.join("、"))); }
        self.geo = (self.geo + self.geo_pending).min(self.geo_cap);
        self.leo_terms = (self.leo_terms + self.leo_pending).min(4000.0);
        self.geo_pending = 0.0;
        self.leo_pending = 0.0;
        self.record();
        if self.turn >= self.p.turns { self.over = true; self.say("white", "推演結束。".into()); }
    }

    fn ready(&mut self) {
        if self.over { return; }
        if self.orders_blue.is_none() && self.ai_blue.is_some() { let a = self.ai(true); self.orders_blue = Some(a); }
        if self.orders_red.is_none() && self.ai_red.is_some() { let a = self.ai(false); self.orders_red = Some(a); }
        if self.orders_blue.is_some() && self.orders_red.is_some() { self.resolve(); }
    }

    fn scores(&self) -> Value {
        let av: Vec<f64> = self.history.iter().skip(1).filter_map(|h| h["avail"].as_f64()).collect();
        let mean = if av.is_empty() { 1.0 } else { av.iter().sum::<f64>() / av.len() as f64 };
        let min = av.iter().cloned().fold(1.0, f64::min);
        let early: Vec<f64> = av.iter().take(3).cloned().collect();
        let early = if early.is_empty() { 1.0 } else { early.iter().sum::<f64>() / early.len() as f64 };
        let pv: Vec<f64> = self.history.iter().skip(1).filter_map(|h| h["pnt"].as_f64()).collect();
        let pnt = if pv.is_empty() { 1.0 } else { pv.iter().sum::<f64>() / pv.len() as f64 };
        // 想定 B：定位授時不足扣分（每少 10% 扣 2 分）
        let blue = mean * 100.0 + self.isr_ok as f64 * 3.0 + self.reputation - if self.is_b() { (1.0 - pnt) * 20.0 } else { 0.0 };
        let red = (1.0 - mean) * 100.0 - self.escalation * 0.5 - if self.asat_used { 10.0 } else { 0.0 }
            // 想定 B：致盲致聾的成敗與藍方對稱計分（藍方定位授時不足即紅方得分；藍方偵察成功即紅方失分）
            + if self.is_b() { (1.0 - pnt) * 20.0 - self.isr_ok as f64 * 3.0 } else { 0.0 };
        json!({"mean_avail": mean, "min_avail": min, "early_avail": early, "cyber_lost": self.cyber_lost, "pnt_avail": pnt, "sar_ok": self.sar_ok, "sar_try": self.sar_try, "blue": blue, "red": red, "escalation": self.escalation, "debris": self.debris, "isr_ok": self.isr_ok, "isr_try": self.isr_try,
            "struck": self.struck, "attributed": self.attributed, "geo_lost": self.geo_lost, "evades": self.evades, "isr_sat_dead": self.isr_sat_dead})
    }

    fn view(&self, role: &str) -> Value {
        let (c, g, l) = self.caps();
        let mine = |b: bool| if b { "已提交" } else { "未提交" };
        let blue_visible = role == "blue" || role == "white";
        json!({
            "turn": self.turn, "max_turns": self.p.turns, "over": self.over, "scenario": self.scenario, "demand": demand(self.turn), "ap": AP,
            "pnt": self.pnt, "pnt_backup": blue_visible.then_some(self.pnt_backup_from != u32::MAX),
            // 想定 C：紅方與白方看得到真實距離；藍方只看得到最後一次追蹤到的距離
            "rpo": if role == "blue" { json!(self.rpo_seen) } else { json!(self.rpo) },
            "rpo_tracked": self.turn < self.track_until, "struck": self.struck, "attributed": self.attributed,
            "geo_spread": blue_visible.then_some(self.spread), "geo_cap": blue_visible.then_some(self.geo_cap),
            "isr_sat_dead": self.isr_sat_dead, "imagery": blue_visible.then_some(self.imagery), "avoid": self.turn < self.avoid_until,
            "cables": self.cables.iter().map(|c| json!({"name": c.name, "intl": c.intl, "cut": c.cut, "repair_at": c.repair_at})).collect::<Vec<_>>(),
            "caps": if blue_visible { json!({"cable": c, "geo": g, "leo": l}) } else { json!({"cable": c, "geo": null, "leo": null}) },
            "leo_terms": if blue_visible { json!(self.leo_terms) } else { json!(((self.leo_terms / 1000.0).round() * 1000.0)) },
            "jam": if self.turn < self.jam_until { self.jam } else { 0.0 },
            "hardened": blue_visible.then_some(self.hardened),
            "escalation": self.escalation, "debris": self.debris, "asat_used": self.asat_used,
            "orders": {"blue": mine(self.orders_blue.is_some()), "red": mine(self.orders_red.is_some())},
            "ai": {"blue": self.ai_blue, "red": self.ai_red},
            "log": self.log, "history": self.history, "scores": if self.over || role == "white" { self.scores() } else { Value::Null },
        })
    }
}

struct Session { war: War, tokens: HashMap<String, String> }
static SESS: Lazy<Mutex<HashMap<String, Session>>> = Lazy::new(|| Mutex::new(HashMap::new()));

fn bad(msg: &str) -> Response { (StatusCode::BAD_REQUEST, Json(json!({"error": msg}))).into_response() }
fn token(seed: u64, salt: u64) -> String { format!("{:016x}", Rng(seed ^ salt).f().to_bits()) }

#[derive(Deserialize)]
pub struct NewReq { seed: Option<u64>, ai_blue: Option<String>, ai_red: Option<String>, #[serde(default)] scenario: String, #[serde(default)] params: Params }

pub async fn war_new(State(_st): State<Arc<AppState>>, Json(rq): Json<NewReq>) -> Response {
    let seed = rq.seed.unwrap_or_else(|| std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(1));
    let id = format!("{:06x}", seed % 0xFFFFFF);
    let mut tokens = HashMap::new();
    for (i, r) in ["blue", "red", "white"].iter().enumerate() { tokens.insert(r.to_string(), token(seed, 0x1000 + i as u64)); }
    let mut war = War::new_p(seed, rq.ai_blue.filter(|s| !s.is_empty()), rq.ai_red.filter(|s| !s.is_empty()), &rq.scenario, rq.params);
    war.ready();
    // 雙方都是 AI（白方觀戰）：沒有人會再送命令推進回合，直接跑完全局
    if war.ai_blue.is_some() && war.ai_red.is_some() {
        while !war.over { war.ready(); }
    }
    let geo: Vec<Value> = war.cables.iter().map(|c| json!({"name": c.name, "intl": c.intl, "coords": c.coords})).collect();
    let mut s = SESS.lock();
    if s.len() > 50 { s.clear(); }
    s.insert(id.clone(), Session { war, tokens: tokens.clone() });
    Json(json!({"id": id, "tokens": tokens, "cables_geo": geo})).into_response()
}

pub async fn war_state(Query(q): Query<HashMap<String, String>>) -> Response {
    let s = SESS.lock();
    let Some(ss) = q.get("id").and_then(|id| s.get(id)) else { return bad("找不到這場推演（伺服器重啟後會清除）") };
    let role = q.get("role").map(String::as_str).unwrap_or("white");
    Json(ss.war.view(role)).into_response()
}

pub async fn war_cables(Query(q): Query<HashMap<String, String>>) -> Response {
    let s = SESS.lock();
    let Some(ss) = q.get("id").and_then(|id| s.get(id)) else { return bad("找不到這場推演") };
    Json(json!(ss.war.cables.iter().map(|c| json!({"name": c.name, "intl": c.intl, "coords": c.coords})).collect::<Vec<_>>())).into_response()
}

#[derive(Deserialize)]
pub struct OrdersReq { id: String, role: String, token: String, #[serde(default)] actions: Vec<Action>, white: Option<String> }

pub async fn war_orders(Json(rq): Json<OrdersReq>) -> Response {
    let mut s = SESS.lock();
    let Some(ss) = s.get_mut(&rq.id) else { return bad("找不到這場推演") };
    if ss.tokens.get(&rq.role) != Some(&rq.token) { return bad("角色憑證不符"); }
    let w = &mut ss.war;
    if w.over { return bad("推演已結束"); }
    if rq.role == "white" {
        if let Some(ev) = rq.white { w.white_queue.push(ev); }
        return Json(w.view("white")).into_response();
    }
    let blue = rq.role == "blue";
    let total: i32 = rq.actions.iter().map(|a| cost(&a.kind)).sum();
    if total > AP { return bad("行動點數超過 5"); }
    if rq.actions.iter().any(|a| is_blue(&a.kind) != blue) { return bad("包含不屬於這個陣營的行動"); }
    if rq.actions.iter().any(|a| !w.allowed(&a.kind)) { return bad("這個行動在目前的想定不可用"); }
    if blue { w.orders_blue = Some(rq.actions); } else { w.orders_red = Some(rq.actions); }
    w.ready();
    Json(w.view(&rq.role)).into_response()
}

#[derive(Deserialize)]
pub struct McReq { runs: Option<u32>, blue: Vec<String>, red: String, #[serde(default)] scenario: String,
                   #[serde(default)] params: Params, #[serde(default)] per_game: bool }

/// 蒙地卡羅：每種藍方策略 × N 局（雙方 AI），共同亂數（同一組種子）方便比較。
/// `params` 覆寫示意參數（敏感度分析）；`per_game: true` 時另回傳每局結果（欄位為陣列，第 k 個元素對應種子 1000+k），供配對差值與分位數使用
pub async fn war_mc(Json(rq): Json<McReq>) -> Response {
    let runs = rq.runs.unwrap_or(200).clamp(10, 2000);
    let red = rq.red.clone();
    let scen = rq.scenario.clone();
    let params = rq.params.clone();
    let per_game = rq.per_game;
    let res = tokio::task::spawn_blocking(move || {
        rq.blue.iter().map(|b| {
            let mut means = Vec::new();
            let mut low = 0;
            let mut esc = 0.0;
            let mut asat = 0;
            let (mut early, mut lost, mut isr_ok, mut isr_try) = (0.0, 0.0, 0.0, 0.0);
            let (mut pnt, mut isr_n, mut sar_n, mut sb, mut sr) = (0.0, 0.0, 0.0, 0.0, 0.0);
            let (mut struck, mut attr, mut glost, mut evades) = (0.0, 0.0, 0.0, 0.0);
            let mut isr_dead = 0.0;
            let mut games: Vec<Value> = Vec::new();
            for k in 0..runs {
                let mut w = War::new_p(1000 + k as u64, Some(b.clone()), Some(red.clone()), &scen, params.clone());
                while !w.over { w.ready(); }
                let s = w.scores();
                let m = s["mean_avail"].as_f64().unwrap_or(0.0);
                if per_game {
                    let series: Vec<f64> = w.history.iter().skip(1).filter_map(|h| h["avail"].as_f64()).map(|x| (x * 1e5).round() / 1e5).collect();
                    games.push(json!([m, s["min_avail"], s["early_avail"], s["blue"], s["red"], w.isr_ok, w.sar_ok, s["pnt_avail"], w.reputation,
                                      w.escalation, w.struck as u8, w.attributed as u8, w.isr_sat_dead as u8, w.asat_used as u8, w.cyber_lost, w.geo_lost, w.evades,
                                      w.misattributed, series]));
                }
                means.push(m);
                if s["min_avail"].as_f64().unwrap_or(1.0) < 0.5 { low += 1; }
                esc += w.escalation;
                if w.asat_used { asat += 1; }
                early += s["early_avail"].as_f64().unwrap_or(0.0);
                lost += w.cyber_lost;
                isr_ok += w.isr_ok as f64;
                isr_try += w.isr_try as f64;
                pnt += s["pnt_avail"].as_f64().unwrap_or(1.0);
                isr_n += w.isr_ok as f64;
                sar_n += w.sar_ok as f64;
                sb += s["blue"].as_f64().unwrap_or(0.0);
                sr += s["red"].as_f64().unwrap_or(0.0);
                if w.struck { struck += 1.0; }
                if w.attributed { attr += 1.0; }
                glost += w.geo_lost;
                evades += w.evades as f64;
                if w.isr_sat_dead { isr_dead += 1.0; }
            }
            means.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let n = means.len() as f64;
            let mean = means.iter().sum::<f64>() / n;
            let sd = (means.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0)).sqrt();
            let mut r = json!({"blue": b, "mean_avail": mean, "ci95": 1.96 * sd / n.sqrt(), "p10": means[(n * 0.1) as usize],
                   "p_low": low as f64 / n, "escalation": esc / n, "asat_rate": asat as f64 / n,
                   "early_avail": early / n, "cyber_lost": lost / n, "isr_rate": if isr_try > 0.0 { isr_ok / isr_try } else { 0.0 },
                   "pnt_avail": pnt / n, "isr_ok": isr_n / n, "sar_ok": sar_n / n, "blue_score": sb / n, "red_score": sr / n,
                   "strike_rate": struck / n, "attrib_rate": attr / n, "geo_lost": glost / n, "evades": evades / n, "isr_sat_lost": isr_dead / n});
            if per_game {
                r["game_cols"] = json!(["mean_avail", "min_avail", "early_avail", "blue_score", "red_score", "isr_ok", "sar_ok", "pnt_avail", "reputation",
                                        "escalation", "struck", "attributed", "isr_sat_dead", "asat_used", "cyber_lost", "geo_lost", "evades", "misattributed", "series"]);
                r["games"] = json!(games);
            }
            r
        }).collect::<Vec<_>>()
    }).await.unwrap_or_default();
    let scenario = scen_name(&rq.scenario);
    let p = &rq.params;
    let params = json!({"a_wipe": p.a_wipe, "red_ban": p.red_ban, "b_pnt_jammed": p.b_pnt_jammed, "b_sar_p": p.b_sar_p, "c_p_strike": p.c_p_strike,
        "c_p_strike_tracked": p.c_p_strike_tracked, "c_track_p": p.c_track_p, "c_attrib_p": p.c_attrib_p, "c_evade_p": p.c_evade_p,
        "c_evade_dip": p.c_evade_dip, "d_img_factor": p.d_img_factor, "d_red_pref": p.d_red_pref, "turns": p.turns, "geo_jam": p.geo_jam,
        "geo_outage_p": p.geo_outage_p, "red_aggr": p.red_aggr, "red_target": p.red_target, "d_switch_p": p.d_switch_p, "d_switch_delay": p.d_switch_delay,
        "c_attrib_rep": p.c_attrib_rep, "c_misattrib_p": p.c_misattrib_p});
    Json(json!({"runs": runs, "red": rq.red, "scenario": scenario, "params": params, "results": res})).into_response()
}
