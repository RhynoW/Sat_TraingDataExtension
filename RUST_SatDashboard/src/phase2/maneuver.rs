//! 避碰決策（v0.3 Sprint 2）：沿跡向單脈衝避碰方案搜尋（與 Python maneuver.py 同流程、同排序鍵與平手規則、
//! 同輸出鍵名與順序）。
//!
//! 流程
//!   1. 基準篩選（e2e::screen_report）→ 目標事件：conjunction.tca 附近（≤ 0.25 週期）的事件；未指定時取 Pc 最大
//!      （無 Pc 時取距離最小）的事件。
//!   2. 可行性預檢（相對 TCA 的機動窗、最短通知時間、Δv 預算、沿跡向推力）→ infeasible_constraints＋原因。
//!   3. 參考軌跡 N0：在可用機動窗起點 τ_h 取主星 GCRF 狀態，以數值積分傳播到篩選窗終點；候選方案自 N0 節點分岔。
//!   4. 線性預篩：沿 N0 積分 STM Φ(t, τ_h)（二體＋J2–J4 重力梯度），Δr_p(TCA) ≈ Φ_rv(TCA, t_b)·T̂·Δv，投影到參考
//!      TCA 的 B-plane；Pc 以小 HBR 近似。網格：n_times 機動時刻 × n_dv 量級 × ±T。
//!   5. 非線性驗證：重新傳播 → 重新搜尋 TCA → 協方差沿候選軌跡傳播（含執行誤差）→ 適用性篩選與 Pc → 二次篩選。
//!   6. 狀態：feasible_solution_found／no_solution_found／infeasible_constraints；預檢另有
//!      no_maneuver_required 與 target_not_found。

use std::cell::RefCell;
use std::cmp::Ordering;
use std::collections::{BTreeSet, HashMap};
use std::time::Instant;

use serde_json::{json, Map, Value};

use super::constants::*;
use super::covprop::{gravity_gradient, CovarianceTrack, M6};
use super::e2e::{self, add3, combined_mode, CovEntry, ObjCov};
use super::eop::Eop;
use super::ephemeris::{Ephemeris, NumericalEphemeris, RelativeState, Sgp4Ephemeris};
use super::events::build_event;
use super::frames::{earth_rotation, teme_to_gcrf, EarthRotationTable};
use super::integrator::propagate;
use super::la::{add, cross, dot, mv, norm, scale, sub};
use super::pc::encounter_frame;
use super::rtn::rtn_matrix;
use super::tca::{find_minima_adaptive, AdaptiveParams, AdaptiveResult};
use super::timescale::{seconds_between, UtcTime};
use super::{M3, V3};

pub const CODE_VERSION: &str = "phase2-sprint2";
pub const STATUSES: [&str; 5] =
    ["feasible_solution_found", "no_solution_found", "infeasible_constraints", "no_maneuver_required", "target_not_found"];

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

/// Python round(x, n)（十進位精確捨入）
fn py_round(x: f64, n: usize) -> f64 {
    format!("{x:.n$}").parse().unwrap()
}

/// Python 的真值判斷（None、False、0、""、[]、{} 為假）
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|x| x != 0.0).unwrap_or(true),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(m)) => !m.is_empty(),
    }
}

fn cmp_f(a: f64, b: f64) -> Ordering {
    a.partial_cmp(&b).unwrap_or(Ordering::Equal)
}

/// τ < t_split 用 before，τ ≥ t_split 用 after（機動後軌跡）
pub struct PiecewiseEphemeris<'a> {
    pub b: &'a dyn Ephemeris,
    pub a: &'a dyn Ephemeris,
    pub ts: f64,
}

impl Ephemeris for PiecewiseEphemeris<'_> {
    fn rv(&self, tau: f64) -> (V3, V3) {
        if tau >= self.ts { self.a.rv(tau) } else { self.b.rv(tau) }
    }
    fn rva(&self, tau: f64) -> (V3, V3, V3) {
        if tau >= self.ts { self.a.rva(tau) } else { self.b.rva(tau) }
    }
    fn span(&self) -> (f64, f64) {
        (self.b.span().0, self.a.span().1)
    }
    fn take_error(&self) -> Option<String> {
        self.b.take_error().or_else(|| self.a.take_error())
    }
}

/// 密切要素（半長軸、偏心率、週期、近地點／遠地點地心距）
#[derive(Clone, Copy, Debug)]
pub struct Osc {
    pub a_km: f64,
    pub e: f64,
    pub period_s: f64,
    pub rp_km: f64,
    pub ra_km: f64,
}

pub fn osc(r: V3, v: V3) -> Osc {
    let (rn, v2) = (norm(r), dot(v, v));
    let a = 1.0 / (2.0 / rn - v2 / GM_KM3_S2);
    let h = cross(r, v);
    let e = (0.0f64.max(1.0 - dot(h, h) / (GM_KM3_S2 * a))).sqrt();
    Osc {
        a_km: a,
        e,
        period_s: 2.0 * std::f64::consts::PI * (a.abs().powf(3.0) / GM_KM3_S2).sqrt(),
        rp_km: a * (1.0 - e),
        ra_km: a * (1.0 + e),
    }
}

/// 小 HBR 近似：HBR²/(2√det C₂)·exp(−½ mᵀC₂⁻¹m)。C2 缺或非正定時 None
pub fn pc_lin(m2: [f64; 2], c2: Option<&[[f64; 2]; 2]>, hbr_km: f64) -> Option<f64> {
    let c2 = c2?;
    let (a, b, c) = (c2[0][0], c2[0][1], c2[1][1]);
    let det = a * c - b * b;
    if !(det > 0.0) {
        return None;
    }
    let q = (c * m2[0] * m2[0] - 2.0 * b * m2[0] * m2[1] + a * m2[1] * m2[1]) / det;
    Some(hbr_km * hbr_km / (2.0 * det.sqrt()) * (-0.5 * q).exp())
}

/// 沿星曆積分 Φ(t, t0)：dΦ/dt = A Φ，A = [[0, I], [G, 0]]；RK4 固定步長 h，節點 t0 + k·h；梯度依 τ 快取
pub struct Stm<'a> {
    eph: &'a dyn Ephemeris,
    pub t0: f64,
    pub h: f64,
    ert: Option<&'a EarthRotationTable>,
    zonal: bool,
    phi: RefCell<Vec<M6>>,
    gcache: RefCell<HashMap<u64, M3>>,
}

fn eye6() -> M6 {
    let mut m = [[0.0; 6]; 6];
    for (i, row) in m.iter_mut().enumerate() {
        row[i] = 1.0;
    }
    m
}

fn axpy6(p: &M6, s: f64, k: &M6) -> M6 {
    let mut o = [[0.0; 6]; 6];
    for i in 0..6 {
        for j in 0..6 {
            o[i][j] = p[i][j] + s * k[i][j];
        }
    }
    o
}

impl<'a> Stm<'a> {
    pub fn new(eph: &'a dyn Ephemeris, t0: f64, h: f64, ert: Option<&'a EarthRotationTable>, zonal: bool) -> Self {
        Stm { eph, t0, h, ert, zonal, phi: RefCell::new(vec![eye6()]), gcache: RefCell::new(HashMap::new()) }
    }

    fn grad(&self, tau: f64) -> M3 {
        if let Some(g) = self.gcache.borrow().get(&tau.to_bits()) {
            return *g;
        }
        let (r, _) = self.eph.rv(tau);
        let g = gravity_gradient(r, self.ert, tau, self.zonal);
        self.gcache.borrow_mut().insert(tau.to_bits(), g);
        g
    }

    fn deriv(&self, tau: f64, p: &M6) -> M6 {
        let g = self.grad(tau);
        let mut out = [[0.0; 6]; 6];
        for i in 0..3 {
            out[i] = p[i + 3];
            for j in 0..6 {
                out[i + 3][j] = g[i][0] * p[0][j] + g[i][1] * p[1][j] + g[i][2] * p[2][j];
            }
        }
        out
    }

    fn step(&self, tau: f64, p: &M6, h: f64) -> M6 {
        let k1 = self.deriv(tau, p);
        let k2 = self.deriv(tau + 0.5 * h, &axpy6(p, 0.5 * h, &k1));
        let k3 = self.deriv(tau + 0.5 * h, &axpy6(p, 0.5 * h, &k2));
        let k4 = self.deriv(tau + h, &axpy6(p, h, &k3));
        let mut out = [[0.0; 6]; 6];
        for i in 0..6 {
            for j in 0..6 {
                out[i][j] = p[i][j] + h / 6.0 * (k1[i][j] + 2.0 * k2[i][j] + 2.0 * k3[i][j] + k4[i][j]);
            }
        }
        out
    }

    pub fn node(&self, k: usize) -> M6 {
        loop {
            let len = self.phi.borrow().len();
            if len > k {
                break;
            }
            let j = len - 1;
            let pj = self.phi.borrow()[j];
            let next = self.step(self.t0 + j as f64 * self.h, &pj, self.h);
            self.phi.borrow_mut().push(next);
        }
        self.phi.borrow()[k]
    }

    pub fn at(&self, tau: f64) -> M6 {
        let k = ((tau - self.t0) / self.h + 1e-9).floor() as i64;
        let k = k.max(0) as usize;
        let p = self.node(k);
        let dt = tau - (self.t0 + k as f64 * self.h);
        if dt.abs() < 1e-9 { p } else { self.step(self.t0 + k as f64 * self.h, &p, dt) }
    }
}

/// 解 A X = B（6×6，部分樞軸 LU；對應 numpy.linalg.solve／LAPACK gesv）
pub fn solve6(a: &M6, b: &M6) -> M6 {
    let mut lu = *a;
    let mut x = *b;
    for c in 0..6 {
        let mut p = c;
        for r in c + 1..6 {
            if lu[r][c].abs() > lu[p][c].abs() {
                p = r;
            }
        }
        lu.swap(c, p);
        x.swap(c, p);
        for r in c + 1..6 {
            let l = lu[r][c] / lu[c][c];
            lu[r][c] = l;
            for j in c + 1..6 {
                lu[r][j] -= l * lu[c][j];
            }
            for j in 0..6 {
                x[r][j] -= l * x[c][j];
            }
        }
    }
    for c in (0..6).rev() {
        for j in 0..6 {
            let mut s = x[c][j];
            for k in c + 1..6 {
                s -= lu[c][k] * x[k][j];
            }
            x[c][j] = s / lu[c][c];
        }
    }
    x
}

fn t6(a: &M6) -> M6 {
    let mut t = [[0.0; 6]; 6];
    for i in 0..6 {
        for j in 0..6 {
            t[i][j] = a[j][i];
        }
    }
    t
}

/// 機動執行誤差（GCRF 速度協方差）：大小誤差沿推力方向 σ = frac·Δv，指向誤差垂直方向 σ = Δv·θ
pub fn exec_error_cov(u: V3, dv_kms: f64, err: Option<&Value>) -> M3 {
    let Some(err) = err.filter(|e| truthy(Some(e))) else { return [[0.0; 3]; 3] };
    if !truthy(err.get("included")) {
        return [[0.0; 3]; 3];
    }
    let sp = err.get("mag_frac_sigma").and_then(Value::as_f64).unwrap_or(0.0) * dv_kms;
    let sq = dv_kms * err.get("point_deg_sigma").and_then(Value::as_f64).unwrap_or(0.0).to_radians();
    let mut q = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            let uu = u[i] * u[j];
            let e = if i == j { 1.0 } else { 0.0 };
            q[i][j] = sp * sp * uu + sq * sq * (e - uu);
        }
    }
    q
}

fn v3(v: &Value) -> V3 {
    [f(&v[0]), f(&v[1]), f(&v[2])]
}

fn catalog_ephemeris<'a>(o: &Value, start: UtcTime, dur: f64, step: f64, zonal: bool, ert: &'a EarthRotationTable,
                         eop: &Eop) -> anyhow::Result<Box<dyn Ephemeris + 'a>> {
    let eph = &o["ephemeris"];
    if eph["type"] == "TLE" {
        return Ok(Box::new(Sgp4Ephemeris::new(eph["line1"].as_str().unwrap(), eph["line2"].as_str().unwrap(), start, ert,
            (0.0, dur))?));
    }
    let ep = UtcTime::parse(eph["epoch"].as_str().unwrap())?;
    let t0 = seconds_between(&start, &ep);
    anyhow::ensure!(t0 <= 0.0, "二次篩選物體 {} 的狀態曆元晚於 screening.start", o["name"].as_str().unwrap_or("?"));
    let (mut r, mut v) = (v3(&eph["r_km"]), v3(&eph["v_kms"]));
    if eph["frame"] == "TEME" {
        (r, v) = teme_to_gcrf(r, v, &earth_rotation(&ep, eop)?);
    }
    let fm = super::forces::ForceModel::new(zonal, false, 0.0);
    Ok(Box::new(NumericalEphemeris::new(propagate(r, v, t0, dur, step, &fm, Some(ert)))))
}

fn search(eph_a: &dyn Ephemeris, eph_b: &dyn Ephemeris, t0: f64, t1: f64, coarse: f64, thr: f64, min_step: f64)
          -> anyhow::Result<AdaptiveResult> {
    let rel = RelativeState::new(eph_a, eph_b);
    let res = find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), t0, t1,
        AdaptiveParams { coarse_step: coarse, threshold_km: Some(thr), min_step, ..Default::default() });
    if let Some(e) = rel.take_error() {
        anyhow::bail!(e);
    }
    Ok(res)
}

fn with(ev: &Value, extra: &[(&str, Value)]) -> Value {
    let mut m = ev.as_object().cloned().unwrap_or_default();
    for (k, v) in extra {
        m.insert((*k).to_string(), v.clone());
    }
    Value::Object(m)
}

/// 機動後事件對照參考事件（同物體、TCA 相差 ≤ match_w）：new（無對應）、worsened（距離變小），其餘 None
fn classify(ev: Value, ref_list: &[(f64, f64)], tb: f64, match_w: f64) -> Option<Value> {
    let tau = f(&ev["tca_tau_s"]);
    let refs: Vec<f64> = ref_list.iter().filter(|(t, _)| *t >= tb - match_w && (tau - t).abs() <= match_w).map(|x| x.1).collect();
    if refs.is_empty() {
        return Some(with(&ev, &[("kind", json!("new")), ("ref_miss_km", Value::Null)]));
    }
    let rm = refs.iter().cloned().fold(f64::INFINITY, |a, b| if b < a { b } else { a });
    if f(&ev["miss_km"]) < rm { Some(with(&ev, &[("kind", json!("worsened")), ("ref_miss_km", json!(rm))])) } else { None }
}

struct CatObj<'a> {
    name: Value,
    norad_id: Value,
    eph: Box<dyn Ephemeris + 'a>,
    ref_events: Vec<(f64, f64)>,
}

#[derive(Clone, Copy)]
struct LinCand {
    burn_tau_s: f64,
    sign: f64,
    dv_ms: f64,
    lin_miss_km: f64,
    lin_pc: Option<f64>,
}

/// 機動前後的目標事件評估（同 Python run 內的 assess）
struct Assessor<'c> {
    start: UtcTime,
    dur: f64,
    coarse: f64,
    thr: f64,
    min_step: f64,
    tca0: f64,
    match_w: f64,
    hbr_km: f64,
    eph_s: &'c dyn Ephemeris,
    cs: &'c CovEntry<'c>,
    p_mode: Option<&'static str>,
    p_source: Value,
    demo_s2: Option<[f64; 3]>,
}

impl Assessor<'_> {
    fn primary_cov<'x>(&self, eph: &'x dyn Ephemeris, track: Option<&'x CovarianceTrack<'x>>) -> ObjCov<'x> {
        match self.p_mode {
            None => ObjCov::None,
            Some("demo") => ObjCov::Demo { eph, s2: self.demo_s2.unwrap() },
            _ => ObjCov::PropRef(track.expect("傳播模式需要協方差軌跡")),
        }
    }

    /// (target_event, other_events_below_threshold)；找不到目標回傳 (None, ...)
    fn assess<'x>(&self, eph_p: &'x dyn Ephemeris, track: Option<&'x CovarianceTrack<'x>>, t_from: f64)
                  -> anyhow::Result<(Option<Value>, Vec<Value>)> {
        let (start, dur, thr, tca0, match_w) = (self.start, self.dur, self.thr, self.tca0, self.match_w);
        let rel = RelativeState::new(eph_p, self.eph_s);
        let res = find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), t_from, dur,
            AdaptiveParams { coarse_step: self.coarse, threshold_km: Some(thr), min_step: self.min_step, ..Default::default() });
        let cp = self.primary_cov(eph_p, track);
        let cov_mode = combined_mode(&cp, &self.cs.0);
        let have_cov = cov_mode.is_some();
        let c3 = |tau: f64| -> M3 { add3(&cp.at(tau), &self.cs.0.at(tau)) };
        let smode = if matches!(cov_mode, Some("propagated") | Some("mixed")) { "propagated" } else { "demo" };
        let others: Vec<f64> = res.all_minima.iter().map(|m| m.tau).collect();
        let srcs = if have_cov { Some(json!([self.p_source, self.cs.1])) } else { None };
        let mut ap_idx: Option<usize> = None;
        for (i, m) in res.all_minima.iter().enumerate() {
            if (m.tau - tca0).abs() <= match_w && ap_idx.map(|j| m.miss_km < res.all_minima[j].miss_km).unwrap_or(true) {
                ap_idx = Some(i);
            }
        }
        let mut tgt = None;
        if let Some(i) = ap_idx {
            let mut e = build_event(&start, &res.all_minima[i], &|t| rel.rva(t), eph_p, if have_cov { Some(&c3) } else { None },
                smode, self.hbr_km, &others, (t_from, dur), srcs);
            if e.get("pc").is_some() {
                e["pc"]["covariance_mode"] = json!(cov_mode);
            }
            tgt = Some(e);
        }
        let rest: Vec<Value> = res.all_minima.iter().enumerate()
            .filter(|(i, m)| m.miss_km <= thr && Some(*i) != ap_idx)
            .map(|(_, m)| json!({"tca_utc": start.plus(m.tau).iso(), "tca_tau_s": m.tau, "miss_km": m.miss_km, "v_rel_kms": norm(m.v_rel)}))
            .collect();
        if let Some(e) = rel.take_error() {
            anyhow::bail!(e);
        }
        Ok((tgt, rest))
    }
}

pub fn run(sc: &Value, eop: &Eop) -> anyhow::Result<Value> {
    let t_wall = Instant::now();
    let ctx = match e2e::build_context(sc, eop)? {
        Ok(c) => c,
        Err(rep) => {
            let v = rep.get("validation").cloned().unwrap_or(Value::Null);
            let codes: BTreeSet<&str> = v.get("codes").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            if codes.len() == 1 && codes.contains("E_NOTICE_WINDOW_CONFLICT") {
                return Ok(json!({"status": "infeasible_constraints", "reason": "notice_window_conflict",
                    "scenario_id": sc.get("id").cloned().unwrap_or(Value::Null), "validation": v,
                    "feasibility": {"note": "最短通知時間與機動窗衝突：沒有合法的機動時刻"}}));
            }
            return Ok(rep);
        }
    };
    let ephs = ctx.ephemerides()?;
    let covs = ctx.covariances(&ephs)?;
    if !truthy(sc.get("maneuver_search")) {
        return Ok(json!({"status": "invalid_scenario",
            "validation": {"ok": false, "codes": ["E_MANEUVER_SEARCH_MISSING"], "messages": ["需要 maneuver_search"]}}));
    }
    let ms = &sc["maneuver_search"];
    let (start, dur, step, coarse, min_step, thr) = (ctx.start, ctx.dur, ctx.step, ctx.coarse, ctx.min_step, ctx.threshold_km);
    let zonal = ctx.zonal;
    let (ip, is) = (ctx.idx("primary"), ctx.idx("secondary"));
    let (prim, secd) = (ctx.obj("primary").clone(), ctx.obj("secondary").clone());
    let eph_p0 = ephs.list[ip].as_ref();
    let eph_s = ephs.list[is].as_ref();
    let (cp0, cs0): (&CovEntry, &CovEntry) = (&covs[ip], &covs[is]);
    let base = e2e::screen_report(&ctx, &ephs, &covs)?;
    let mut info = Map::new();
    info.insert("scenario_id".into(), sc["id"].clone());
    info.insert("start".into(), json!(start.iso()));
    info.insert("duration_s".into(), json!(dur));
    info.insert("threshold_km".into(), json!(thr));
    info.insert("objects".into(), base["objects"].clone());
    let out = |info: &Map<String, Value>, extra: Vec<(&str, Value)>| -> Value {
        let mut m = info.clone();
        for (k, v) in extra {
            m.insert(k.to_string(), v);
        }
        Value::Object(m)
    };

    // 1. 目標事件
    let (r0p, v0p) = eph_p0.rv(0.0);
    let period = osc(r0p, v0p).period_s;
    let match_w = MAN_TARGET_MATCH_FRAC_PERIOD * period;
    let events = base["events"].as_array().cloned().unwrap_or_default();
    let tgt_tca = sc.get("conjunction").and_then(|c| c.get("tca")).filter(|t| truthy(Some(t)));
    let target: Value = if let Some(tt) = tgt_tca {
        let tau_t = seconds_between(&start, &UtcTime::parse(tt.as_str().unwrap())?);
        let near: Vec<&Value> = events.iter().filter(|e| (f(&e["tca_tau_s"]) - tau_t).abs() <= match_w).collect();
        match near.into_iter().min_by(|a, b| cmp_f((f(&a["tca_tau_s"]) - tau_t).abs(), (f(&b["tca_tau_s"]) - tau_t).abs())) {
            Some(t) => t.clone(),
            None => {
                return Ok(out(&info, vec![("status", json!("target_not_found")), ("reason", json!("no_event_near_conjunction_tca")),
                    ("screening", json!({"n_events": events.len()}))]));
            }
        }
    } else {
        if events.is_empty() {
            return Ok(out(&info, vec![("status", json!("target_not_found")), ("reason", json!("no_event_below_threshold")),
                ("screening", json!({"n_events": 0}))]));
        }
        let key = |e: &Value| -> (f64, f64) {
            let p = e.get("pc").and_then(|p| p.get("foster")).and_then(Value::as_f64).filter(|x| *x != 0.0).unwrap_or(-1.0);
            (-p, f(&e["miss_km"]))
        };
        let mut sorted: Vec<&Value> = events.iter().collect();
        sorted.sort_by(|a, b| {
            let (ka, kb) = (key(a), key(b));
            cmp_f(ka.0, kb.0).then(cmp_f(ka.1, kb.1))
        });
        sorted[0].clone()
    };
    let tca0 = f(&target["tca_tau_s"]);

    // 2. 可行性預檢
    let prop = prim.get("propulsion").filter(|p| truthy(Some(p))).cloned().unwrap_or_else(|| json!({}));
    let w = ms["window_rel_tca_s"].as_array().unwrap();
    let (a_rel, b_rel) = (f(&w[0]), f(&w[1]));
    let notice = prop.get("min_notice_s").and_then(Value::as_f64).unwrap_or(0.0);
    let at_tau = match sc.get("analysis_time").filter(|t| truthy(Some(t))) {
        Some(t) => seconds_between(&start, &UtcTime::parse(t.as_str().unwrap())?),
        None => 0.0,
    };
    let earliest = at_tau + notice;
    let mut lo = tca0 + a_rel;
    if earliest > lo {
        lo = earliest;
    }
    if 0.0 > lo {
        lo = 0.0;
    }
    let hi = tca0 + b_rel;
    let dvr = ms.get("dv_ms").filter(|d| truthy(Some(d))).and_then(Value::as_array)
        .map(|a| (f(&a[0]), f(&a[1]))).unwrap_or(MAN_DV_MS_DEFAULT);
    let (dv_lo, dv_hi) = dvr;
    let budget = prop.get("dv_budget_ms").cloned().unwrap_or(Value::Null);
    let dirs = prop.get("thrust_dirs").cloned().unwrap_or(Value::Null);
    let signs: Vec<f64> = [1.0, -1.0].into_iter().filter(|s| {
        let key = if *s > 0.0 { "T" } else { "-T" };
        dirs.is_null() || dirs.as_array().map(|a| a.iter().any(|x| x == key)).unwrap_or(false)
    }).collect();
    let sign_names: Vec<&str> = signs.iter().map(|s| if *s > 0.0 { "+T" } else { "-T" }).collect();
    let mut feas = Map::new();
    feas.insert("target_tca_utc".into(), target["tca_utc"].clone());
    feas.insert("window_rel_tca_s".into(), json!([a_rel, b_rel]));
    feas.insert("earliest_allowed_utc".into(), json!(start.plus(earliest).iso()));
    feas.insert("latest_useful_utc".into(), json!(start.plus(hi).iso()));
    feas.insert("dv_range_ms".into(), json!([dv_lo, dv_hi]));
    feas.insert("dv_budget_ms".into(), budget.clone());
    feas.insert("thrust_dirs".into(), dirs.clone());
    feas.insert("along_track_signs".into(), json!(sign_names));
    info.insert("target".into(), target.clone());
    let infeasible = |info: &Map<String, Value>, reason: &str, feas: &Map<String, Value>| -> Value {
        out(info, vec![("status", json!("infeasible_constraints")), ("reason", json!(reason)), ("feasibility", Value::Object(feas.clone()))])
    };
    if earliest > hi {
        return Ok(infeasible(&info, "notice_window_conflict", &feas));
    }
    if lo > hi {
        return Ok(infeasible(&info, "window_before_data_start", &feas));
    }
    if signs.is_empty() {
        return Ok(infeasible(&info, "no_along_track_thrust", &feas));
    }
    let budget_f = budget.as_f64();
    if let Some(bg) = budget_f {
        if bg < dv_lo {
            return Ok(infeasible(&info, "dv_budget_below_min_dv", &feas));
        }
    }
    let dv_hi_eff = match budget_f {
        Some(bg) => if bg < dv_hi { bg } else { dv_hi },
        None => dv_hi,
    };
    feas.insert("window_utc".into(), json!([start.plus(lo).iso(), start.plus(hi).iso()]));
    feas.insert("dv_search_ms".into(), json!([dv_lo, dv_hi_eff]));

    // 3. 參考軌跡 N0（自 τ_h = lo 起的數值傳播）
    let cov_step = if ctx.geo { COV_STEP_GEO_S } else { COV_STEP_LEO_S };
    let g = step * (cov_step / step - 1e-9).ceil();
    // 地球定向表起點涵蓋二次篩選狀態向量物體的曆元（其數值積分自曆元開始）
    let mut t_lo = ctx.t_lo;
    if let Some(objs) = ms.get("secondary_screening").and_then(|x| x.get("objects")).and_then(Value::as_array) {
        for o in objs {
            if o["ephemeris"]["type"] == "state" {
                if let Some(ep) = o["ephemeris"]["epoch"].as_str() {
                    t_lo = t_lo.min(seconds_between(&start, &UtcTime::parse(ep)?));
                }
            }
        }
    }
    let ert = EarthRotationTable::new(start, t_lo - 1.0, dur + 2.0 * g + 1.0, eop)?;
    let fm_p = e2e::object_force_model(&prim, ctx.zonal, ctx.drag);
    let (r_h, v_h) = eph_p0.rv(lo);
    let n0 = NumericalEphemeris::new(propagate(r_h, v_h, lo, dur, step, &fm_p, Some(&ert)));
    let n0e: &dyn Ephemeris = &n0;

    let pcov = prim.get("covariance").filter(|c| truthy(Some(c))).cloned().unwrap_or_else(|| json!({}));
    let q = e2e::process_noise_q(&prim);
    let n0_track: Option<CovarianceTrack> = match cp0.0.track() {
        Some(t) => Some(CovarianceTrack::new(n0e, t.at(lo)?, lo, dur, g, Some(&ert), zonal, q)),
        None => None,
    };
    let demo_s2: Option<[f64; 3]> = if cp0.0.mode() == Some("demo") {
        let s = v3(&pcov["sigma_km"]);
        Some([s[0] * s[0], s[1] * s[1], s[2] * s[2]])
    } else {
        None
    };
    let cov_mode_ref = combined_mode(&cp0.0, &cs0.0);
    let comparable = cp0.0.mode() == Some("propagated") && cs0.0.mode() == Some("propagated");
    let hbr_km = (f(&prim["hbr_m"]) + f(&secd["hbr_m"])) / 1000.0;
    let pc_target_v = ms.get("pc_target").cloned().unwrap_or(Value::Null);
    let pc_target = pc_target_v.as_f64();
    let min_miss = ms.get("min_miss_km").and_then(Value::as_f64);
    let use_pc = pc_target.is_some() && comparable;
    let min_miss_eff: Option<f64> = match min_miss {
        Some(m) => Some(m),
        None => if use_pc { None } else { Some(MAN_MIN_MISS_DEFAULT_KM) },
    };
    let reject_km = min_miss.unwrap_or(MAN_MIN_MISS_DEFAULT_KM);
    let note = if use_pc {
        "Pc 目標採用：兩物體皆為傳播模式協方差"
    } else if pc_target.is_some() {
        "Pc 目標未採用：協方差非雙方傳播模式，機動前後 Pc 不可直接比較，以距離目標判定"
    } else {
        "以距離目標判定"
    };
    let criteria = json!({"min_miss_km": min_miss_eff, "pc_target": pc_target_v, "pc_target_used": use_pc,
        "pc_comparable": comparable, "covariance_mode": cov_mode_ref, "new_conjunction_reject_km": reject_km, "note": note});

    let asr = Assessor { start, dur, coarse, thr, min_step, tca0, match_w, hbr_km, eph_s, cs: cs0,
        p_mode: cp0.0.mode(), p_source: cp0.1.clone(), demo_s2 };
    let (ref_tgt, ref_rest) = asr.assess(n0e, n0_track.as_ref(), lo)?;
    let Some(ref_tgt) = ref_tgt else {
        return Ok(out(&info, vec![("status", json!("target_not_found")), ("reason", json!("reference_lost")),
            ("feasibility", Value::Object(feas))]));
    };
    let pc_of = |ev: &Value| -> Option<f64> { ev.get("pc").and_then(|p| p.get("foster")).and_then(Value::as_f64) };
    let meets = |ev: &Value| -> bool {
        let ok_miss = min_miss_eff.map(|m| f(&ev["miss_km"]) >= m).unwrap_or(true);
        let ok_pc = !use_pc || pc_of(ev).map(|p| p <= pc_target.unwrap()).unwrap_or(false);
        ok_miss && ok_pc
    };
    let model = json!({"integrator": "RK4", "step_s": step, "force_model": fm_p.describe()});
    let reference = json!({"handover_utc": start.plus(lo).iso(), "handover_tau_s": lo, "model": model,
        "initial_state_source": ephs.prov["primary"], "event": ref_tgt});
    info.insert("feasibility".into(), Value::Object(feas.clone()));
    info.insert("criteria".into(), criteria);
    info.insert("reference".into(), reference);
    if meets(&ref_tgt) {
        return Ok(out(&info, vec![("status", json!("no_maneuver_required")), ("reason", json!("reference_meets_targets")),
            ("timing", json!({"elapsed_s": t_wall.elapsed().as_secs_f64()}))]));
    }

    // 4. 線性預篩
    let k_max = ((hi - lo) / g + 1e-9).floor() as i64;
    let n_times = ms.get("n_times").and_then(Value::as_f64).map(|x| x as i64).unwrap_or(MAN_N_TIMES as i64);
    let idx: Vec<i64> = if n_times <= 1 || k_max == 0 {
        vec![0]
    } else {
        let s: BTreeSet<i64> = (0..n_times).map(|i| ((i * k_max) as f64 / (n_times - 1) as f64).round_ties_even() as i64).collect();
        s.into_iter().collect()
    };
    let burn_taus: Vec<f64> = idx.iter().map(|&k| lo + k as f64 * g).collect();
    let n_dv = ms.get("n_dv").and_then(Value::as_f64).map(|x| x as i64).unwrap_or(MAN_N_DV as i64);
    let dv_levels: Vec<f64> = if n_dv <= 1 {
        vec![dv_hi_eff]
    } else {
        (0..n_dv).map(|i| dv_lo + i as f64 * (dv_hi_eff - dv_lo) / (n_dv - 1) as f64).collect()
    };

    let stm = Stm::new(n0e, lo, g, Some(&ert), zonal);
    let ref_tca = f(&ref_tgt["tca_tau_s"]);
    let phi_t = stm.at(ref_tca);
    let (rp0, vp0) = n0e.rv(ref_tca);
    let (rs0, vs0) = eph_s.rv(ref_tca);
    let r_rel0 = sub(rs0, rp0);
    let v_rel0 = sub(vs0, vp0);
    let fr = encounter_frame(r_rel0, v_rel0);
    let m2_ref = [dot(fr[0], r_rel0), dot(fr[1], r_rel0)];
    let c2_ref: Option<[[f64; 2]; 2]> = ref_tgt.get("bplane").map(|b| {
        let c = &b["cov_km2"];
        [[f(&c[0][0]), f(&c[0][1])], [f(&c[1][0]), f(&c[1][1])]]
    });
    let step_index = |tau: f64| -> usize { ((tau - lo) / step).round_ties_even() as usize };

    let mut lin_map: Vec<Value> = Vec::new();
    let mut fallbacks: Vec<((f64, f64), f64, f64, f64, Option<f64>)> = Vec::new();
    let mut lin_pass: Vec<LinCand> = Vec::new();
    for &tb in &burn_taus {
        let phi_b = stm.at(tb);
        let phi_tb = t6(&solve6(&t6(&phi_b), &t6(&phi_t)));
        let kb = step_index(tb);
        let (rb, vb) = (n0.traj.r[kb], n0.traj.v[kb]);
        let t_hat = rtn_matrix(rb, vb)[1];
        let mut col = [0.0; 3];
        for i in 0..3 {
            col[i] = phi_tb[i][3] * t_hat[0] + phi_tb[i][4] * t_hat[1] + phi_tb[i][5] * t_hat[2];
        }
        let b2 = [dot(fr[0], col), dot(fr[1], col)];
        let mut min_dv = Map::new();
        let mut best: Option<(usize, f64, f64, f64, f64, Option<f64>)> = None;
        for &s in &signs {
            let key = if s > 0.0 { "+T" } else { "-T" };
            min_dv.insert(key.into(), Value::Null);
            for (i, &dv) in dv_levels.iter().enumerate() {
                let k = s * (dv / 1000.0);
                let m2 = [m2_ref[0] - k * b2[0], m2_ref[1] - k * b2[1]];
                let miss_l = m2[0].hypot(m2[1]);
                let pcl = pc_lin(m2, c2_ref.as_ref(), hbr_km);
                let ok = min_miss_eff.map(|m| miss_l >= m).unwrap_or(true)
                    && (!use_pc || pcl.map(|p| p <= pc_target.unwrap()).unwrap_or(false));
                if ok {
                    min_dv.insert(key.into(), json!(dv));
                    let better = match &best {
                        None => true,
                        Some(b) => i < b.0 || (i == b.0 && -miss_l < b.1),
                    };
                    if better {
                        best = Some((i, -miss_l, s, dv, miss_l, pcl));
                    }
                    break;
                }
            }
        }
        // 最大 Δv 下的預測（無解時挑最佳候選用）
        let mut fb: Option<((f64, f64), f64, f64, f64, Option<f64>)> = None;
        for &s in &signs {
            let k = s * (dv_hi_eff / 1000.0);
            let m2 = [m2_ref[0] - k * b2[0], m2_ref[1] - k * b2[1]];
            let miss_l = m2[0].hypot(m2[1]);
            let pcl = pc_lin(m2, c2_ref.as_ref(), hbr_km);
            let score = (if use_pc { pcl.unwrap_or(0.0) } else { 0.0 }, -miss_l);
            let better = match &fb {
                None => true,
                Some(x) => score.0 < x.0 .0 || (score.0 == x.0 .0 && score.1 < x.0 .1),
            };
            if better {
                fb = Some((score, s, dv_hi_eff, miss_l, pcl));
            }
        }
        lin_map.push(json!({"burn_tau_s": tb, "burn_utc": start.plus(tb).iso(), "min_dv_ms": min_dv}));
        fallbacks.push(fb.unwrap());
        if let Some(b) = best {
            lin_pass.push(LinCand { burn_tau_s: tb, sign: b.2, dv_ms: b.3, lin_miss_km: b.4, lin_pc: b.5 });
        }
    }

    let max_verify = ms.get("max_verify").and_then(Value::as_f64).map(|x| x as usize).unwrap_or(MAN_MAX_VERIFY);
    let (order, selection): (Vec<LinCand>, &str) = if !lin_pass.is_empty() {
        let mut v: Vec<&LinCand> = lin_pass.iter().collect();
        v.sort_by(|a, b| cmp_f(a.dv_ms, b.dv_ms).then(cmp_f(-a.lin_miss_km, -b.lin_miss_km)).then(cmp_f(a.burn_tau_s, b.burn_tau_s)));
        (v.into_iter().take(max_verify).copied().collect(), "linear_pass")
    } else {
        let mut ix: Vec<usize> = (0..burn_taus.len()).collect();
        ix.sort_by(|&a, &b| {
            let (fa, fb) = (&fallbacks[a], &fallbacks[b]);
            cmp_f(fa.0 .0, fb.0 .0).then(cmp_f(fa.0 .1, fb.0 .1)).then(cmp_f(burn_taus[a], burn_taus[b]))
        });
        (ix.into_iter().take(3.min(max_verify)).map(|i| {
            let fb = &fallbacks[i];
            LinCand { burn_tau_s: burn_taus[i], sign: fb.1, dv_ms: fb.2, lin_miss_km: fb.3, lin_pc: fb.4 }
        }).collect(), "best_at_max_dv")
    };

    // 二次篩選目錄
    let ss = ms.get("secondary_screening").filter(|x| truthy(Some(x))).cloned().unwrap_or_else(|| json!({}));
    let cat_objs: Vec<Value> = ss.get("objects").and_then(Value::as_array).cloned().unwrap_or_default();
    let end_s = match ss.get("window_days").filter(|x| truthy(Some(x))) {
        None => dur,
        Some(wd) => {
            let x = lo + f(wd) * DAY_S;
            if x < dur { x } else { dur }
        }
    };
    let osc_h = osc(r_h, v_h);
    let da_max = 2.0 * osc_h.a_km.powf(2.0) * norm(v_h) * (dv_hi_eff / 1000.0) / GM_KM3_S2;
    let pad = thr + MAN_PREFILTER_MARGIN_KM + da_max;
    let mut kept: Vec<CatObj> = Vec::new();
    for o in &cat_objs {
        let eph_o = catalog_ephemeris(o, start, dur, step, zonal, &ert, eop)?;
        let (ro, vo) = eph_o.rv(lo);
        if let Some(e) = eph_o.take_error() {
            anyhow::bail!(e);
        }
        let oo = osc(ro, vo);
        let keep = !(oo.rp_km > osc_h.ra_km + pad || oo.ra_km < osc_h.rp_km - pad);
        if keep {
            kept.push(CatObj { name: o["name"].clone(), norad_id: o.get("norad_id").cloned().unwrap_or(Value::Null), eph: eph_o,
                ref_events: vec![] });
        }
    }
    for c in kept.iter_mut() {
        if end_s > lo {
            let res = search(n0e, c.eph.as_ref(), lo, end_s, coarse, thr, min_step)?;
            c.ref_events = res.events.iter().map(|m| (m.tau, m.miss_km)).collect();
        }
    }
    let new_events = |eph_c: &dyn Ephemeris, tb: f64| -> anyhow::Result<Vec<Value>> {
        let mut out = Vec::new();
        if end_s <= tb {
            return Ok(out); // 二次篩選時間窗在機動之前即結束
        }
        for c in &kept {
            let res = search(eph_c, c.eph.as_ref(), tb, end_s, coarse, thr, min_step)?;
            for m in &res.events {
                let ev = json!({"object": c.name, "norad_id": c.norad_id, "tca_utc": start.plus(m.tau).iso(), "tca_tau_s": m.tau,
                    "miss_km": m.miss_km, "v_rel_kms": norm(m.v_rel)});
                if let Some(e) = classify(ev, &c.ref_events, tb, match_w) {
                    out.push(e);
                }
            }
        }
        Ok(out)
    };

    let exec_err = pcov.get("maneuver_execution_error").cloned();
    let exec_included = exec_err.as_ref().map(|e| truthy(Some(e)) && truthy(e.get("included"))).unwrap_or(false);

    // 5. 非線性驗證
    let mut verified: Vec<(Value, usize)> = Vec::new();
    let mut afters: Vec<NumericalEphemeris> = Vec::new();
    let ref_miss = f(&ref_tgt["miss_km"]);
    let ref_sec: Vec<(f64, f64)> = ref_rest.iter().map(|e| (f(&e["tca_tau_s"]), f(&e["miss_km"]))).collect();
    let mass = prim.get("mass_kg").and_then(Value::as_f64).filter(|x| *x != 0.0);
    let isp = prop.get("isp_s").and_then(Value::as_f64).filter(|x| *x != 0.0);
    for c in &order {
        let (tb, s, dv) = (c.burn_tau_s, c.sign, c.dv_ms);
        let kb = step_index(tb);
        let (rb, vb) = (n0.traj.r[kb], n0.traj.v[kb]);
        let u = scale(rtn_matrix(rb, vb)[1], s);
        let vn = add(vb, scale(u, dv / 1000.0));
        let after = NumericalEphemeris::new(propagate(rb, vn, tb, dur, step, &fm_p, Some(&ert)));
        let cand = {
            let eph_c = PiecewiseEphemeris { b: n0e, a: &after, ts: tb };
            let track_c = match &n0_track {
                Some(t0) => {
                    let mut pb = t0.at(tb)?;
                    let qx = exec_error_cov(u, dv / 1000.0, exec_err.as_ref());
                    for i in 0..3 {
                        for j in 0..3 {
                            pb[3 + i][3 + j] += qx[i][j];
                        }
                    }
                    Some(CovarianceTrack::new(&eph_c, pb, tb, dur, g, Some(&ert), zonal, q))
                }
                None => None,
            };
            let (tgt, rest) = asr.assess(&eph_c, track_c.as_ref(), tb)?;
            let (o_b, o_a) = (osc(rb, vb), osc(rb, vn));
            let mut cand = Map::new();
            cand.insert("burn_utc".into(), json!(start.plus(tb).iso()));
            cand.insert("burn_tau_s".into(), json!(tb));
            cand.insert("burn_rel_tca_s".into(), json!(tb - tca0));
            cand.insert("direction".into(), json!(if s > 0.0 { "+T" } else { "-T" }));
            cand.insert("dv_ms".into(), json!(dv));
            cand.insert("linear".into(), json!({"miss_km": c.lin_miss_km, "pc_approx": c.lin_pc}));
            cand.insert("delta_a_km".into(), json!(o_a.a_km - o_b.a_km));
            cand.insert("delta_period_s".into(), json!(o_a.period_s - o_b.period_s));
            cand.insert("propellant_kg".into(), match (mass, isp) {
                (Some(m), Some(i)) => json!(m * (1.0 - (-dv / (i * MAN_G0_MS2)).exp())),
                _ => Value::Null,
            });
            cand.insert("execution_error_included".into(), json!(exec_included && n0_track.is_some()));
            match tgt {
                None => {
                    cand.insert("event".into(), Value::Null);
                    cand.insert("checks".into(), json!({"target_found": false}));
                    cand.insert("passed".into(), json!(false));
                    cand.insert("secondary_screening".into(), json!({"status": "not_run", "reason": "target_not_found"}));
                }
                Some(tgt) => {
                    let mut checks = Map::new();
                    checks.insert("target_found".into(), json!(true));
                    if let Some(m) = min_miss_eff {
                        checks.insert("miss".into(), json!(f(&tgt["miss_km"]) >= m));
                    }
                    if use_pc {
                        checks.insert("pc".into(), json!(pc_of(&tgt).map(|p| p <= pc_target.unwrap()).unwrap_or(false)));
                    }
                    let new_sec: Vec<Value> = rest.iter().filter_map(|e| {
                        let mut m = Map::new();
                        m.insert("object".into(), secd["name"].clone());
                        m.insert("norad_id".into(), secd.get("norad_id").cloned().unwrap_or(Value::Null));
                        for (k, v) in e.as_object().unwrap() {
                            m.insert(k.clone(), v.clone());
                        }
                        classify(Value::Object(m), &ref_sec, tb, match_w)
                    }).collect();
                    let (pa, pr) = (pc_of(&tgt), pc_of(&ref_tgt));
                    let d_miss = f(&tgt["miss_km"]) - ref_miss;
                    cand.insert("event".into(), tgt);
                    cand.insert("d_miss_km".into(), json!(d_miss));
                    cand.insert("pc_before".into(), json!(pr));
                    cand.insert("pc_after".into(), json!(pa));
                    cand.insert("pc_comparable".into(), json!(comparable));
                    let all_ok = checks.values().all(|v| v.as_bool().unwrap());
                    if all_ok {
                        let cat_new = new_events(&eph_c, tb)?;
                        let mut allnew = new_sec;
                        allnew.extend(cat_new);
                        checks.insert("no_new_conjunction".into(), json!(!allnew.iter().any(|e| f(&e["miss_km"]) < reject_km)));
                        let n_new = allnew.len();
                        cand.insert("new_conjunctions".into(), json!(allnew));
                        cand.insert("secondary_screening".into(), json!({"status": "done", "n_new": n_new}));
                    } else {
                        cand.insert("new_conjunctions".into(), json!(new_sec));
                        cand.insert("secondary_screening".into(), json!({"status": "not_run", "reason": "target_not_met"}));
                    }
                    let passed = checks.values().all(|v| v.as_bool().unwrap());
                    cand.insert("checks".into(), Value::Object(checks));
                    cand.insert("passed".into(), json!(passed));
                }
            }
            Value::Object(cand)
        };
        afters.push(after);
        verified.push((cand, afters.len() - 1));
    }

    let n_passed = verified.iter().filter(|(c, _)| c["passed"] == true).count();
    let rank = |c: &Value| -> (bool, f64, f64, f64) {
        let ev_miss = if c["event"].is_null() { -1.0 } else { f(&c["event"]["miss_km"]) };
        (c["passed"] != true, f(&c["dv_ms"]), -ev_miss, f(&c["burn_tau_s"]))
    };
    verified.sort_by(|a, b| {
        let (ka, kb) = (rank(&a.0), rank(&b.0));
        ka.0.cmp(&kb.0).then(cmp_f(ka.1, kb.1)).then(cmp_f(ka.2, kb.2)).then(cmp_f(ka.3, kb.3))
    });
    let best = verified.first().map(|x| x.0.clone());
    let status = if n_passed > 0 { "feasible_solution_found" } else { "no_solution_found" };
    let reason: Value = if n_passed > 0 {
        Value::Null
    } else if selection == "best_at_max_dv" {
        json!("no_linear_candidate_met_targets")
    } else {
        json!("verified_candidates_failed")
    };

    let n_cat = cat_objs.len();
    let coverage = if n_cat > 0 {
        format!("僅完成所提供 {n_cat} 顆物體的二次篩選（近遠地點預篩後 {} 顆逐對搜尋），另含原次星；未涵蓋完整目錄", kept.len())
    } else {
        "未提供二次篩選物體清單：僅檢查與原次星的新增交會".to_string()
    };

    // 6. 繪圖資料
    let best_after: Option<&NumericalEphemeris> = verified.first()
        .filter(|(c, _)| truthy(c.get("event")))
        .map(|(_, i)| &afters[*i]);
    let eph_best_pw = best_after.map(|a| PiecewiseEphemeris { b: n0e, a, ts: f(&best.as_ref().unwrap()["burn_tau_s"]) });
    let plot = plot_data(lo, dur, tca0, period, n0e, eph_s, &ref_tgt, eph_best_pw.as_ref().map(|e| e as &dyn Ephemeris),
        best.as_ref(), hbr_km);

    let n_verified = verified.len();
    let candidates: Vec<Value> = verified.into_iter().map(|x| x.0).collect();
    let mut searched = Map::new();
    searched.insert("times".into(), json!(burn_taus.len()));
    searched.insert("dv_levels".into(), json!(dv_levels.len()));
    searched.insert("signs".into(), json!(sign_names));
    searched.insert("dv_search_ms".into(), json!([dv_lo, dv_hi_eff]));
    searched.insert("grid_cells".into(), json!(burn_taus.len() * dv_levels.len() * signs.len()));
    searched.insert("grid_step_s".into(), json!(g));
    searched.insert("linear_pass_times".into(), json!(lin_pass.len()));
    searched.insert("selection".into(), json!(selection));
    searched.insert("max_verify".into(), json!(max_verify));
    searched.insert("verified".into(), json!(n_verified));
    searched.insert("passed".into(), json!(n_passed));
    let catalog = if ss.as_object().map(|m| m.contains_key("catalog")).unwrap_or(false) { ss["catalog"].clone() } else { json!("provided") };
    Ok(out(&info, vec![
        ("status", json!(status)), ("reason", reason),
        ("searched", Value::Object(searched)),
        ("linear_map", json!(lin_map)),
        ("candidates", json!(candidates)),
        ("best", best.unwrap_or(Value::Null)),
        ("secondary_screening", json!({"catalog": catalog, "n_objects": n_cat, "n_after_prefilter": kept.len(),
            "window_utc": [start.plus(lo).iso(), start.plus(end_s).iso()], "coverage_note": coverage})),
        ("plot", plot),
        ("provenance", json!({"code_version": CODE_VERSION, "constants_version": CONSTANTS_VERSION, "eop": eop.version(),
            "reference_trajectory": model,
            "linear_screening": "STM（二體＋J2–J4 重力梯度，不含阻力偏導數）；Pc 為小 HBR 近似",
            "covariance": base["provenance"]["covariance"]})),
        ("timing", json!({"elapsed_s": t_wall.elapsed().as_secs_f64()})),
    ]))
}

#[allow(clippy::too_many_arguments)]
fn plot_data(lo: f64, dur: f64, tca0: f64, period: f64, n0: &dyn Ephemeris, eph_s: &dyn Ephemeris, ref_tgt: &Value,
             eph_best: Option<&dyn Ephemeris>, best: Option<&Value>, hbr_km: f64) -> Value {
    let n = MAN_PLOT_POINTS;
    let ts: Vec<f64> = (0..n).map(|i| lo + (dur - lo) * i as f64 / (n - 1) as f64).collect();
    let d_ref: Vec<f64> = ts.iter().map(|&t| norm(sub(eph_s.rv(t).0, n0.rv(t).0))).collect();
    let d_best: Option<Vec<f64>> = eph_best.map(|e| ts.iter().map(|&t| norm(sub(eph_s.rv(t).0, e.rv(t).0))).collect());
    // 全域：TCA ± 半週期（限制在 [lo, dur]）
    let mut a = lo;
    if tca0 - 0.5 * period > a {
        a = tca0 - 0.5 * period;
    }
    let mut b = dur;
    if tca0 + 0.5 * period < b {
        b = tca0 + 0.5 * period;
    }
    let tg: Vec<f64> = (0..121).map(|i| a + (b - a) * i as f64 / 120.0).collect();
    let pts = |eph: &dyn Ephemeris| -> Value {
        json!(tg.iter().map(|&t| { let r = eph.rv(t).0; [py_round(r[0], 3), py_round(r[1], 3), py_round(r[2], 3)] }).collect::<Vec<_>>())
    };
    let burn_km = match (eph_best, best) {
        (Some(_), Some(bs)) if a <= f(&bs["burn_tau_s"]) && f(&bs["burn_tau_s"]) <= b => {
            let r = n0.rv(f(&bs["burn_tau_s"])).0;
            json!([py_round(r[0], 3), py_round(r[1], 3), py_round(r[2], 3)])
        }
        _ => Value::Null,
    };
    let glob = json!({"tau_s": tg, "primary_ref": pts(n0), "secondary": pts(eph_s),
        "primary_best": eph_best.map(&pts).unwrap_or(Value::Null), "burn_km": burn_km});
    // 局部：參考 TCA 時主星 RTN 座標（固定），次星相對主星的軌跡
    let tc = f(&ref_tgt["tca_tau_s"]);
    let (rp, vp) = n0.rv(tc);
    let c = rtn_matrix(rp, vp);
    let miss_b = match (eph_best, best) {
        (Some(_), Some(bs)) if truthy(bs.get("event")) => f(&bs["event"]["miss_km"]),
        _ => 0.0,
    };
    let ref_miss = f(&ref_tgt["miss_km"]);
    let mut mx = ref_miss;
    if miss_b > mx {
        mx = miss_b;
    }
    if hbr_km > mx {
        mx = hbr_km;
    }
    let vrel = f(&ref_tgt["v_rel_kms"]);
    let inner = 3.0 * mx / if 1e-6 > vrel { 1e-6 } else { vrel };
    let inner = if inner > 0.5 { inner } else { 0.5 };
    let half = if inner < 120.0 { inner } else { 120.0 };
    let l0 = if tc - half > lo { tc - half } else { lo };
    let l1 = if tc + half < dur { tc + half } else { dur };
    let tl: Vec<f64> = (0..81).map(|i| l0 + (l1 - l0) * i as f64 / 80.0).collect();
    let relpts = |eph: &dyn Ephemeris| -> Value {
        json!(tl.iter().map(|&t| {
            let d = mv(&c, sub(eph_s.rv(t).0, eph.rv(t).0));
            [py_round(d[0], 6), py_round(d[1], 6), py_round(d[2], 6)]
        }).collect::<Vec<_>>())
    };
    let local = json!({"frame": "參考主星於參考 TCA 的 RTN 軸（km）", "tau_s": tl, "rel_ref": relpts(n0),
        "rel_best": eph_best.map(&relpts).unwrap_or(Value::Null)});
    json!({"series": {"tau0_s": lo, "step_s": (dur - lo) / (n - 1) as f64, "d_ref_km": d_ref, "d_best_km": d_best},
           "global": glob, "local": local})
}
