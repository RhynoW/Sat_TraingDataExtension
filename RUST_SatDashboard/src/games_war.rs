//! 太空小遊戲「太空兵棋」：海纜中斷下的太空通訊韌性（紅藍對抗＋白方 GM，WEGO 同時下令）
//!
//! 參考：謝沛學〈從遊戲到實戰：商用兵棋軟體如何協助軍事分析與訓練〉（國防安全雙週報，2020）——
//! 視覺化、軍民通用、多人連線與蒙地卡羅分析。這裡是教育用的抽象模型，數值為示意。
//!
//! - 伺服器權威：狀態只在伺服器，雙方各自提交命令，兩方都交（或由 AI 代下）後一起裁決；可重現（固定種子）
//! - 海纜：取自內嵌的 TeleGeography 圖資中經過台灣周邊的海纜；國際海纜每條 10 單位頻寬，離島海纜 1 單位
//! - 每回合 6 小時、共 8 回合；需求 100 單位
//! - 蒙地卡羅：雙方都由 AI 依策略下令，跑 N 局統計可用率、升級指數與碎片事件

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
fn demand(t: u32) -> f64 { 150.0 + 5.0 * t as f64 }
const MAX_TURNS: u32 = 8;
const AP: i32 = 5;
const LEO_PER_TERM: f64 = 0.02;

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
        "cut_cable" | "jam_leo" | "cyber_gateway" => 2,
        "dazzle" | "propaganda" => 1,
        "asat" => 4,
        _ => 99,
    }
}
fn is_blue(kind: &str) -> bool {
    matches!(kind, "geo_lease" | "leo_deploy" | "anti_jam" | "patrol" | "repair" | "harden" | "isr" | "diplomacy")
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
}

impl Clone for Rng {
    fn clone(&self) -> Self { Rng(self.0) }
}

impl War {
    fn new(seed: u64, ai_blue: Option<String>, ai_red: Option<String>) -> War {
        let mut w = War {
            rng: Rng(seed ^ 0xA5A5_1234), turn: 0, cables: CABLES.clone(), geo: 5.0, geo_pending: 0.0, leo_terms: 0.0, leo_pending: 0.0,
            hardened: false, patrol_until: 0, jam: 0.0, jam_until: 0, gateway_down_until: 0, debris: 0.0, asat_used: false,
            escalation: 0.0, reputation: 0.0, storm_until: 0, typhoon_until: 0, isr_ok: 0, isr_try: 0,
            orders_blue: None, orders_red: None, white_queue: vec![], log: vec![], history: vec![], ai_blue, ai_red, over: false,
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
        w.record();
        w
    }

    fn say(&mut self, side: &str, text: String) {
        self.log.push(json!({"turn": self.turn, "side": side, "text": text}));
    }

    fn caps(&self) -> (f64, f64, f64) {
        let t = self.turn;
        let cable: f64 = self.cables.iter().filter(|c| !c.cut).map(|c| if c.intl { 10.0 } else { 1.0 }).sum();
        let storm = t < self.storm_until;
        let geo = self.geo * if storm { 0.7 } else { 1.0 };
        let jam = if t < self.jam_until { self.jam } else { 0.0 };
        let gw = if t < self.gateway_down_until { 0.5 } else { 1.0 };
        let leo = self.leo_terms * LEO_PER_TERM * (1.0 - jam) * gw * (1.0 - 0.1 * self.debris).max(0.5) * if storm { 0.8 } else { 1.0 };
        (cable, geo, leo)
    }

    fn record(&mut self) {
        let (c, g, l) = self.caps();
        let avail = ((c + g + l) / demand(self.turn)).min(1.0);
        let cut = self.cables.iter().filter(|x| x.cut).count();
        self.history.push(json!({"turn": self.turn, "demand": demand(self.turn), "cable": c, "geo": g, "leo": l, "avail": avail, "cut": cut,
            "escalation": self.escalation, "debris": self.debris, "isr_ok": self.isr_ok, "isr_try": self.isr_try}));
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
        let push = |out: &mut Vec<Action>, ap: &mut i32, k: &str, arg: Option<usize>| {
            if cost(k) <= *ap { *ap -= cost(k); out.push(Action { kind: k.into(), arg }); }
        };
        let t = self.turn;
        if blue {
            let cut: Vec<usize> = (0..self.cables.len()).filter(|&i| self.cables[i].cut && self.cables[i].intl && self.cables[i].repair_at.is_none()).collect();
            match style.as_str() {
                "geo" => { push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "geo_lease", None); }
                "leo" => { if !self.hardened { push(&mut out, &mut ap, "harden", None); } push(&mut out, &mut ap, "leo_deploy", None); push(&mut out, &mut ap, "leo_deploy", None); }
                "repair" => { for &i in cut.iter().take(1) { push(&mut out, &mut ap, "repair", Some(i)); } push(&mut out, &mut ap, "patrol", None); }
                _ => {
                    if t == 0 { push(&mut out, &mut ap, "geo_lease", None); push(&mut out, &mut ap, "leo_deploy", None); push(&mut out, &mut ap, "harden", None); }
                    else {
                        if t < self.jam_until && self.leo_terms > 1000.0 { push(&mut out, &mut ap, "anti_jam", None); }
                        if let Some(&i) = cut.first() { push(&mut out, &mut ap, "repair", Some(i)); }
                        push(&mut out, &mut ap, "leo_deploy", None);
                    }
                }
            }
            push(&mut out, &mut ap, "isr", None);
            push(&mut out, &mut ap, "diplomacy", None);
        } else {
            let aggressive = style == "escalate";
            let intact: Vec<usize> = (0..self.cables.len()).filter(|&i| !self.cables[i].cut && self.cables[i].intl).collect();
            if aggressive && !self.asat_used && t >= 3 && self.rng.f() < 0.5 { push(&mut out, &mut ap, "asat", None); }
            if !intact.is_empty() && self.rng.f() < 0.7 {
                let k = (self.rng.f() * intact.len() as f64) as usize % intact.len();
                push(&mut out, &mut ap, "cut_cable", Some(intact[k]));
            }
            if self.leo_terms + self.leo_pending > 800.0 { push(&mut out, &mut ap, "jam_leo", None); }
            if !self.hardened && self.rng.f() < 0.5 { push(&mut out, &mut ap, "cyber_gateway", None); }
            push(&mut out, &mut ap, "dazzle", None);
            push(&mut out, &mut ap, "propaganda", None);
        }
        out
    }

    fn resolve(&mut self) {
        let t = self.turn;
        for ev in std::mem::take(&mut self.white_queue) { self.white(&ev); }
        // 隨機事件
        if self.rng.f() < 0.08 { self.white("storm"); }
        let blue = self.orders_blue.take().unwrap_or_default();
        let red = self.orders_red.take().unwrap_or_default();
        let has = |v: &Vec<Action>, k: &str| v.iter().any(|a| a.kind == k);
        if has(&blue, "patrol") { self.patrol_until = t + 2; self.say("blue", "藍方：海巡與海軍加強海纜區巡邏（2 回合）。".into()); }
        let anti_jam = has(&blue, "anti_jam");
        if has(&blue, "harden") && !self.hardened { self.hardened = true; self.say("blue", "藍方：低軌閘道站完成資安強化。".into()); }
        let dazzled = has(&red, "dazzle");
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
                "cyber_gateway" => {
                    self.escalation += 2.0;
                    if self.hardened { self.say("red", "低軌閘道站遭網攻，已強化，未受影響。".into()); }
                    else { self.gateway_down_until = t + 2; self.say("red", "低軌閘道站遭網攻，容量減半 2 回合。".into()); }
                }
                "dazzle" => { self.escalation += 1.0; self.say("red", "光學偵察衛星疑遭雷射致盲干擾。".into()); }
                "propaganda" => { self.reputation -= 1.0; }
                "asat" if !self.asat_used => {
                    self.asat_used = true;
                    self.debris += 1.0;
                    self.escalation += 15.0;
                    self.say("red", "紅方進行直升式反衛星試射，低軌碎片大增（所有低軌星系含紅方自己都受影響）。".into());
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
        // 情監偵：每回合 2 次過頂，成功率受雲量與致盲影響
        let n_isr = blue.iter().filter(|a| a.kind == "isr").count() as u32 * 2;
        let cloud = if t < self.typhoon_until { 0.85 } else { 0.4 };
        let p_ok = (1.0 - cloud) * if dazzled { 0.5 } else { 1.0 };
        for _ in 0..n_isr {
            self.isr_try += 1;
            if self.rng.f() < p_ok { self.isr_ok += 1; }
        }
        // 推進到下一回合：修復完成、命令生效
        self.turn += 1;
        let nt = self.turn;
        let mut fixed = Vec::new();
        for c in self.cables.iter_mut() {
            if c.repair_at == Some(nt) { c.cut = false; c.repair_at = None; fixed.push(c.name.clone()); }
        }
        if !fixed.is_empty() { self.say("blue", format!("海纜修復：{}。", fixed.join("、"))); }
        self.geo = (self.geo + self.geo_pending).min(60.0);
        self.leo_terms = (self.leo_terms + self.leo_pending).min(4000.0);
        self.geo_pending = 0.0;
        self.leo_pending = 0.0;
        self.record();
        if self.turn >= MAX_TURNS { self.over = true; self.say("white", "推演結束。".into()); }
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
        let blue = mean * 100.0 + self.isr_ok as f64 * 3.0 + self.reputation;
        let red = (1.0 - mean) * 100.0 - self.escalation * 0.5 - if self.asat_used { 10.0 } else { 0.0 };
        json!({"mean_avail": mean, "min_avail": min, "blue": blue, "red": red, "escalation": self.escalation, "debris": self.debris, "isr_ok": self.isr_ok, "isr_try": self.isr_try})
    }

    fn view(&self, role: &str) -> Value {
        let (c, g, l) = self.caps();
        let mine = |b: bool| if b { "已提交" } else { "未提交" };
        let blue_visible = role == "blue" || role == "white";
        json!({
            "turn": self.turn, "max_turns": MAX_TURNS, "over": self.over, "demand": demand(self.turn), "ap": AP,
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
pub struct NewReq { seed: Option<u64>, ai_blue: Option<String>, ai_red: Option<String> }

pub async fn war_new(State(_st): State<Arc<AppState>>, Json(rq): Json<NewReq>) -> Response {
    let seed = rq.seed.unwrap_or_else(|| std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(1));
    let id = format!("{:06x}", seed % 0xFFFFFF);
    let mut tokens = HashMap::new();
    for (i, r) in ["blue", "red", "white"].iter().enumerate() { tokens.insert(r.to_string(), token(seed, 0x1000 + i as u64)); }
    let mut war = War::new(seed, rq.ai_blue.filter(|s| !s.is_empty()), rq.ai_red.filter(|s| !s.is_empty()));
    war.ready();
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
    if blue { w.orders_blue = Some(rq.actions); } else { w.orders_red = Some(rq.actions); }
    w.ready();
    Json(w.view(&rq.role)).into_response()
}

#[derive(Deserialize)]
pub struct McReq { runs: Option<u32>, blue: Vec<String>, red: String }

/// 蒙地卡羅：每種藍方策略 × N 局（雙方 AI），共同亂數（同一組種子）方便比較
pub async fn war_mc(Json(rq): Json<McReq>) -> Response {
    let runs = rq.runs.unwrap_or(200).clamp(10, 2000);
    let red = rq.red.clone();
    let res = tokio::task::spawn_blocking(move || {
        rq.blue.iter().map(|b| {
            let mut means = Vec::new();
            let mut low = 0;
            let mut esc = 0.0;
            let mut asat = 0;
            for k in 0..runs {
                let mut w = War::new(1000 + k as u64, Some(b.clone()), Some(red.clone()));
                while !w.over { w.ready(); }
                let s = w.scores();
                let m = s["mean_avail"].as_f64().unwrap_or(0.0);
                means.push(m);
                if s["min_avail"].as_f64().unwrap_or(1.0) < 0.5 { low += 1; }
                esc += w.escalation;
                if w.asat_used { asat += 1; }
            }
            means.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let n = means.len() as f64;
            let mean = means.iter().sum::<f64>() / n;
            let sd = (means.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0)).sqrt();
            json!({"blue": b, "mean_avail": mean, "ci95": 1.96 * sd / n.sqrt(), "p10": means[(n * 0.1) as usize],
                   "p_low": low as f64 / n, "escalation": esc / n, "asat_rate": asat as f64 / n})
        }).collect::<Vec<_>>()
    }).await.unwrap_or_default();
    Json(json!({"runs": runs, "red": rq.red, "results": res})).into_response()
}
