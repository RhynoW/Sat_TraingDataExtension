//! 星系對單一地面點的重訪 / 覆蓋分析（可設定觀測仰角門檻）。對應 Python physics/revisit.py。
//!
//! * 一次傳播、多門檻：每顆衛星只傳播一次，各仰角門檻以布林運算求得。
//! * 三種「重訪」定義：星系級過頂間隔、單星重訪週期、無覆蓋空窗（coverage gap）。
//! * 時窗頭尾被截斷之空窗不納入統計，另行回報（gap_edge_censored_min）。
//!
//! 與 Python 版差異：Python 一次建 (n_sats, n_steps) 矩陣；此處逐星平行計算過頂區段，
//! 再以區段重建同時可見顆數，結果相同而記憶體用量小得多。記憶體保護（512 MB 上限時
//! 等比縮減衛星數）仍依 Python 公式套用，使 n_sats_propagated 一致。

use chrono::{DateTime, Duration, Utc};
use rayon::prelude::*;
use serde_json::{json, Map, Value};

use super::{gmst_py, iso_py, median, py_round, teme_elaz};
use crate::index::SatIndex;
use crate::physics::Observer;

pub const DEFAULT_MASKS: [f64; 12] = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0];
const TIMELINE_BINS: usize = 360;
const MAX_MATRIX_MB: f64 = 512.0;

/// 布林序列中所有 True 連續區段 (起, 迄)（含端點）
fn runs(b: &[bool]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start: Option<usize> = None;
    for (i, &v) in b.iter().enumerate() {
        match (v, start) {
            (true, None) => start = Some(i),
            (false, Some(s)) => {
                out.push((s, i - 1));
                start = None;
            }
            _ => {}
        }
    }
    if let Some(s) = start {
        out.push((s, b.len() - 1));
    }
    out
}

/// 單顆衛星：各門檻之過頂區段 (起, 迄, 最大仰角)
struct SatRuns {
    clean: bool,
    by_mask: Vec<Vec<(usize, usize, f64)>>,
}

pub fn compute_revisit(
    nids: &[u32],
    idx: &SatIndex,
    lat_deg: f64,
    lon_deg: f64,
    hours: f64,
    step_sec: f64,
) -> Value {
    let h_km = 0.01;
    let masks = DEFAULT_MASKS;
    // Python datetime 精度為微秒
    let now = Utc::now();
    let t0 = now - Duration::nanoseconds(i64::from(now.timestamp_subsec_nanos() % 1000));
    let n_steps = ((hours * 3600.0 / step_sec) as usize).max(2);

    let mut usable: Vec<u32> = nids
        .iter()
        .copied()
        .filter(|n| idx.sats.get(n).is_some_and(|s| !s.line1.is_empty()))
        .collect();
    if usable.is_empty() {
        return json!({"error": "此群組無可用 TLE"});
    }
    let est_mb = usable.len() as f64 * n_steps as f64 * 3.0 * 8.0 / 1024f64.powi(2);
    if est_mb > MAX_MATRIX_MB {
        let keep = ((MAX_MATRIX_MB * 1024f64.powi(2) / (n_steps as f64 * 3.0 * 8.0)) as usize).max(1);
        tracing::warn!(
            "重訪分析矩陣估計 {est_mb:.0} MB > {MAX_MATRIX_MB} MB 上限，衛星數 {} → {keep}",
            usable.len()
        );
        usable.truncate(keep);
    }

    let times: Vec<DateTime<Utc>> = (0..n_steps)
        .map(|i| t0 + Duration::microseconds((i as f64 * step_sec * 1e6).round() as i64))
        .collect();
    let gmst: Vec<f64> = times.iter().map(gmst_py).collect();
    let obs = Observer::new(lat_deg, lon_deg, h_km);

    let per_sat: Vec<SatRuns> = usable
        .par_iter()
        .map(|n| {
            let prop = idx.sats.get(n).and_then(|s| s.prop.as_ref());
            let mut clean = true;
            let el: Vec<f64> = times
                .iter()
                .zip(&gmst)
                .map(|(t, g)| match prop.and_then(|p| p.position(t)) {
                    Some(r) => teme_elaz(&obs, &r, *g).0,
                    None => {
                        clean = false;
                        -90.0
                    }
                })
                .collect();
            let by_mask = masks
                .iter()
                .map(|&m| {
                    let above: Vec<bool> = el.iter().map(|e| *e >= m).collect();
                    runs(&above)
                        .into_iter()
                        .map(|(a, b)| (a, b, el[a..=b].iter().copied().fold(f64::NEG_INFINITY, f64::max)))
                        .collect()
                })
                .collect();
            SatRuns { clean, by_mask }
        })
        .collect();

    let n_ok = per_sat.iter().filter(|s| s.clean).count();
    let bin_edges: Vec<usize> = (0..=TIMELINE_BINS)
        .map(|i| {
            if i == TIMELINE_BINS {
                n_steps
            } else {
                (i as f64 * (n_steps as f64 / TIMELINE_BINS as f64)) as usize
            }
        })
        .collect();
    let win_min = hours * 60.0;
    let to_min = |k: usize| k as f64 * step_sec / 60.0;

    let mut by_mask = Map::new();
    for (mi, &m) in masks.iter().enumerate() {
        // 同時可見顆數（差分陣列由各過頂區段重建）
        let mut diff = vec![0i64; n_steps + 1];
        let mut pass_starts: Vec<usize> = Vec::new();
        let mut pass_durs: Vec<f64> = Vec::new();
        let mut pass_max_el: Vec<f64> = Vec::new();
        let mut sat_revisit: Vec<f64> = Vec::new();
        let mut sat_pass_counts: Vec<f64> = Vec::new();
        let mut sats_seen = 0usize;
        for s in &per_sat {
            let rs = &s.by_mask[mi];
            if rs.is_empty() {
                continue;
            }
            sats_seen += 1;
            sat_pass_counts.push(rs.len() as f64);
            if rs.len() >= 2 {
                let gaps: Vec<f64> = rs.windows(2).map(|w| to_min(w[1].0 - w[0].0)).collect();
                sat_revisit.push(median(&gaps));
            }
            for &(a, b, mx) in rs {
                diff[a] += 1;
                diff[b + 1] -= 1;
                pass_starts.push(a);
                pass_durs.push(to_min(b - a + 1));
                pass_max_el.push(mx);
            }
        }
        let mut n_vis = Vec::with_capacity(n_steps);
        let mut acc = 0i64;
        for d in &diff[..n_steps] {
            acc += d;
            n_vis.push(acc);
        }
        let any_vis: Vec<bool> = n_vis.iter().map(|v| *v > 0).collect();

        pass_starts.sort_unstable();
        let n_passes = pass_starts.len();
        let intervals: Vec<f64> = pass_starts.windows(2).map(|w| to_min(w[1] - w[0])).collect();

        let not_vis: Vec<bool> = any_vis.iter().map(|v| !v).collect();
        let mut gaps_inner: Vec<(usize, f64)> = Vec::new();
        let mut gap_edge_min = 0.0f64;
        for (a, b) in runs(&not_vis) {
            let dur = to_min(b - a + 1);
            if a == 0 || b == n_steps - 1 {
                gap_edge_min = gap_edge_min.max(dur);
                continue;
            }
            gaps_inner.push((a, py_round(dur, 1)));
        }
        let gap_mins: Vec<f64> = gaps_inner.iter().map(|g| g.1).collect();
        let cov_pct = py_round(100.0 * any_vis.iter().filter(|v| **v).count() as f64 / n_steps as f64, 2);
        let timeline: Vec<i64> = (0..TIMELINE_BINS)
            .map(|i| {
                let (a, b) = (bin_edges[i], (bin_edges[i] + 1).max(bin_edges[i + 1]));
                n_vis[a..b.min(n_steps)].iter().copied().max().unwrap_or(0)
            })
            .collect();
        let mut top = gaps_inner.clone();
        top.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
        let top_gaps: Vec<Value> = top
            .iter()
            .take(8)
            .map(|(a, mins)| json!({"start_utc": iso_py(&times[*a]), "minutes": mins}))
            .collect();
        let opt = |v: &[f64], f: &dyn Fn(&[f64]) -> f64, d: usize| {
            if v.is_empty() {
                Value::Null
            } else {
                json!(py_round(f(v), d))
            }
        };
        let vmax = |v: &[f64]| v.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let vmin = |v: &[f64]| v.iter().copied().fold(f64::INFINITY, f64::min);
        by_mask.insert(
            format!("{}", m as i64),
            json!({
                "mask_deg": m,
                "n_passes": n_passes,
                "mean_revisit_min": if n_passes > 0 { json!(py_round(win_min / n_passes as f64, 2)) } else { Value::Null },
                "sat_revisit_median_min": opt(&sat_revisit, &median, 1),
                "sat_revisit_min_min": opt(&sat_revisit, &vmin, 1),
                "sat_passes_median": opt(&sat_pass_counts, &median, 1),
                "sats_multi_pass": sat_revisit.len(),
                "median_interval_min": opt(&intervals, &median, 2),
                "max_interval_min": opt(&intervals, &vmax, 1),
                "coverage_pct": cov_pct,
                "n_gaps": gaps_inner.len(),
                "max_gap_min": if gap_mins.is_empty() { 0.0 } else { py_round(vmax(&gap_mins), 1) },
                "median_gap_min": if gap_mins.is_empty() { 0.0 } else { py_round(median(&gap_mins), 1) },
                "gap_edge_censored_min": py_round(gap_edge_min, 1),
                "top_gaps": top_gaps,
                "sats_seen": sats_seen,
                "max_simultaneous": n_vis.iter().copied().max().unwrap_or(0),
                "mean_simultaneous": py_round(n_vis.iter().sum::<i64>() as f64 / n_steps as f64, 2),
                "median_pass_min": opt(&pass_durs, &median, 1),
                "median_max_el_deg": opt(&pass_max_el, &median, 1),
                "timeline": timeline,
            }),
        );
    }

    json!({
        "station": {"lat": py_round(lat_deg, 4), "lon": py_round(lon_deg, 4), "h_km": h_km},
        "window": {
            "t0_utc": iso_py(&t0),
            "hours": hours,
            "step_sec": step_sec,
            "timeline_bins": TIMELINE_BINS,
        },
        "n_sats_requested": nids.len(),
        "n_sats_propagated": usable.len(),
        "n_sats_clean": n_ok,
        "masks": masks.to_vec(),
        "by_mask": by_mask,
    })
}
