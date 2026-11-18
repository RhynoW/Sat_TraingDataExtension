//! 台灣假想地基雷達站之追蹤效益評估（簡化模型）與過頂追蹤序列。
//! 對應 Python physics/radar_eval.py（evaluate / track_passes）。
//!
//! 評估邏輯（明確為簡化代理，非作業級 OD 誤差分析）：
//!   - 對樣本衛星以 SGP4 傳播 24 h（步長 60 s），計算各站仰角 > mask 的「追蹤弧段」。
//!   - before = 全球已知 SSN 站（config/ssn_stations.geojson）；after = 加入台灣站。
//!   - 精度代理：σ_after/σ_before ≈ √(N_before/N_after)（觀測數均勻假設）。

use chrono::{DateTime, Duration, Utc};
use rayon::prelude::*;
use serde_json::{json, Value};

use super::{gmst_py, iso_z, py_float, py_round, teme_elaz};
use crate::index::SatInfo;
use crate::physics::{Observer, Propagator};

const TW_NAME: &str = "台灣假想地基雷達站（樂山）";
const TW_LAT: f64 = 24.395;
const TW_LON: f64 = 120.905;
const TW_H_KM: f64 = 2.6;

fn tw_station() -> Value {
    json!({"name": TW_NAME, "lat": TW_LAT, "lon": TW_LON})
}

/// SSN 站點（同 Python config/stations.py 之驗證：geometry 須為 Point 且座標恰為 2 個）
pub fn ssn_observers(geojson: &str) -> Vec<Observer> {
    let v: Value = serde_json::from_str(geojson).unwrap_or(Value::Null);
    if v["type"] != "FeatureCollection" {
        return Vec::new();
    }
    v["features"]
        .as_array()
        .map(|fs| {
            fs.iter()
                .filter_map(|f| {
                    let g = &f["geometry"];
                    let c = g["coordinates"].as_array()?;
                    if g["type"] != "Point" || c.len() != 2 {
                        return None;
                    }
                    Some(Observer::new(c[1].as_f64()?, c[0].as_f64()?, 0.0))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// 傳播 n_steps 步；SGP4 錯誤之時刻略過（同 Python：只保留 e == 0）
fn propagate(p: Option<&Propagator>, t0: DateTime<Utc>, n_steps: usize, step_s: f64) -> Vec<(DateTime<Utc>, [f64; 3])> {
    let Some(p) = p else { return Vec::new() };
    (0..n_steps)
        .filter_map(|k| {
            let t = t0 + Duration::milliseconds((k as f64 * step_s * 1000.0).round() as i64);
            p.position(&t).map(|r| (t, r))
        })
        .collect()
}

/// 布林序列 → (弧段數, 最大間隙分, 平均間隙分, 累計可見分)
fn arcs(vis: &[bool], step_s: f64) -> (usize, f64, f64, f64) {
    if vis.is_empty() {
        return (0, 0.0, 0.0, 0.0);
    }
    let n_arcs = vis.windows(2).filter(|w| !w[0] && w[1]).count() + usize::from(vis[0]);
    let mut gaps: Vec<usize> = Vec::new();
    let mut run = 0usize;
    for &v in vis {
        if v {
            if run > 0 {
                gaps.push(run);
            }
            run = 0;
        } else {
            run += 1;
        }
    }
    if run > 0 {
        gaps.push(run);
    }
    let tomin = step_s / 60.0;
    let (gmax, gmean) = if gaps.is_empty() {
        (0.0, 0.0)
    } else {
        (
            *gaps.iter().max().unwrap() as f64 * tomin,
            gaps.iter().sum::<usize>() as f64 / gaps.len() as f64 * tomin,
        )
    };
    (n_arcs, gmax, gmean, vis.iter().filter(|v| **v).count() as f64 * tomin)
}

fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

/// sats：(norad, 衛星)；回傳彙總與逐星指標（鍵順序同 Python）
pub fn evaluate(sats: &[&SatInfo], ssn: &[Observer], hours: f64, mask_deg: f64) -> Value {
    let step_s = 60.0;
    let t0 = super::now_minute();
    let n_steps = (hours * 3600.0 / step_s) as usize;
    let tw = Observer::new(TW_LAT, TW_LON, TW_H_KM);
    let rows: Vec<Value> = sats
        .par_iter()
        .filter_map(|s| {
            let pts = propagate(s.prop.as_ref(), t0, n_steps, step_s);
            if pts.len() < 10 {
                return None;
            }
            let mut vis_b = vec![false; pts.len()];
            let mut vis_tw = vec![false; pts.len()];
            for (k, (t, r)) in pts.iter().enumerate() {
                let g = gmst_py(t);
                vis_b[k] = ssn.iter().any(|o| teme_elaz(o, r, g).0 > mask_deg);
                vis_tw[k] = teme_elaz(&tw, r, g).0 > mask_deg;
            }
            let vis_a: Vec<bool> = vis_b.iter().zip(&vis_tw).map(|(a, b)| *a || *b).collect();
            let (nb, gb_max, gb_mean, mb) = arcs(&vis_b, step_s);
            let (na, ga_max, ga_mean, ma) = arcs(&vis_a, step_s);
            let (n_tw, _, _, _) = arcs(&vis_tw, step_s);
            let only_tw = vis_tw.iter().zip(&vis_b).filter(|(t, b)| **t && !**b).count();
            let only_tw = (only_tw as f64 * step_s / 60.0) as i64;
            let sigma_ratio = if ma > 0.0 && mb > 0.0 {
                (mb / ma).sqrt()
            } else if ma > 0.0 {
                0.0
            } else {
                1.0
            };
            let gain = py_round((1.0 - sigma_ratio) * 100.0, 1);
            Some(json!({
                "norad": s.norad_id, "name": s.name,
                "arcs_before": nb, "arcs_after": na, "arcs_taiwan": n_tw,
                "gap_max_before_min": py_round(gb_max, 1), "gap_max_after_min": py_round(ga_max, 1),
                "gap_mean_before_min": py_round(gb_mean, 1), "gap_mean_after_min": py_round(ga_mean, 1),
                "track_min_before": py_round(mb, 1), "track_min_after": py_round(ma, 1),
                "track_min_taiwan_only": only_tw,
                "sigma_ratio": py_round(sigma_ratio, 3),
                "info_gain_pct": gain,
                "precision_gain_pct": gain,
            }))
        })
        .collect();
    if rows.is_empty() {
        return json!({"error": "無可評估衛星"});
    }
    let avg = |k: &str| {
        let xs: Vec<f64> = rows.iter().map(|r| r[k].as_f64().unwrap_or(0.0)).collect();
        py_round(mean(&xs), 1)
    };
    let summary = json!({
        "n_sats": rows.len(),
        "arcs_before": avg("arcs_before"), "arcs_after": avg("arcs_after"),
        "gap_max_before_min": avg("gap_max_before_min"), "gap_max_after_min": avg("gap_max_after_min"),
        "track_min_before": avg("track_min_before"), "track_min_after": avg("track_min_after"),
        "taiwan_only_min": avg("track_min_taiwan_only"),
        "info_gain_pct": avg("info_gain_pct"),
        "precision_gain_pct": avg("precision_gain_pct"),
        "sats_with_taiwan_arc": rows.iter().filter(|r| r["arcs_taiwan"].as_u64().unwrap_or(0) > 0).count(),
    });
    let mut sorted = rows;
    // Python sorted(key=-info_gain_pct)：穩定排序
    sorted.sort_by(|a, b| {
        let (x, y) = (a["info_gain_pct"].as_f64().unwrap_or(0.0), b["info_gain_pct"].as_f64().unwrap_or(0.0));
        y.partial_cmp(&x).unwrap_or(std::cmp::Ordering::Equal)
    });
    json!({
        "t0": iso_z(&t0), "hours": hours, "mask_deg": mask_deg,
        "n_stations_before": ssn.len(), "taiwan_station": tw_station(),
        "summary": summary,
        "sats": sorted,
        "model_note": "「觀測資訊增益」為 σ∝1/√(累計可見分鐘) 之概念指標（均勻獨立觀測假設），非定軌協方差改善；\
                       弧段以仰角 > mask 之幾何可見性定義，不含偵測判定。",
        "assumptions": {
            "站址": format!("{TW_NAME} {}°N {}°E h={} km（WGS-84）", py_float(TW_LAT), py_float(TW_LON), py_float(TW_H_KM)),
            "最低仰角": format!("{}°", py_float(mask_deg)),
            "可用觀測條件": "elevation ≥ 最低仰角之幾何可見（不含 SNR／雷達方程式／RCS）",
            "傳播": format!("SGP4，步長 {step_s:.0} s，{hours:.0} h，UTC"),
            "座標": "TEME → GMST → ECEF；站心 ENU 求仰角",
            "地形遮蔽": "未納入",
            "大氣折射": "未納入",
            "觀測量": "弧段數、可見分鐘、最大／平均間隙",
            "精度模型": "概念性資訊量指標 σ∝1/√N；不代表 batch LS／EKF 協方差傳播",
            "既有站": format!("SSN 站點圖層 {} 站（同一可見性模型）", ssn.len()),
        },
    })
}

/// 台灣站對單一衛星之未來過頂 az/el 序列（即時追蹤示範用）
pub fn track_passes(p: Option<&Propagator>) -> Value {
    let (hours, step_s, mask_deg, max_passes) = (24.0, 30.0, 5.0, 3usize);
    let t0 = super::now_minute();
    let pts = propagate(p, t0, (hours * 3600.0 / step_s) as usize, step_s);
    let tw = Observer::new(TW_LAT, TW_LON, TW_H_KM);
    let mut passes: Vec<Vec<Value>> = Vec::new();
    let mut cur: Option<Vec<Value>> = None;
    for (t, r) in &pts {
        let (el, az, rng) = teme_elaz(&tw, r, gmst_py(t));
        if el > mask_deg {
            let pt = json!({"t": iso_z(t), "el": py_round(el, 2), "az": py_round(az, 2), "rng": py_round(rng, 1)});
            cur.get_or_insert_with(Vec::new).push(pt);
        } else if let Some(c) = cur.take() {
            passes.push(c);
            if passes.len() >= max_passes {
                break;
            }
        }
    }
    if let Some(c) = cur {
        if passes.len() < max_passes {
            passes.push(c);
        }
    }
    let passes: Vec<Value> = passes
        .into_iter()
        .map(|pts| {
            let max_el = pts
                .iter()
                .filter_map(|x| x["el"].as_f64())
                .fold(f64::NEG_INFINITY, f64::max);
            let (aos, los) = (pts[0]["t"].clone(), pts[pts.len() - 1]["t"].clone());
            let dur = py_round(pts.len() as f64 * step_s / 60.0, 1);
            json!({"points": pts, "aos": aos, "los": los, "max_el": max_el, "duration_min": dur})
        })
        .collect();
    json!({"station": tw_station(), "t0": iso_z(&t0), "mask_deg": mask_deg, "passes": passes})
}
