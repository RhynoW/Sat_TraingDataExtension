//! 單一近接事件的輸出組裝（端到端與批次共用，與 Python events.py 欄位相同）：
//! 會合幾何、交會平面、適用性篩選、Pc。

use serde_json::{json, Value};

use super::constants::GM_KM3_S2;
use super::ephemeris::Ephemeris;
use super::la::{add, dot, mv, norm};
use super::pc::{pc_chan, pc_foster, project};
use super::rtn::rtn_matrix;
use super::screening::screen;
use super::tca::Approach;
use super::timescale::UtcTime;
use super::{M3, V3};

pub const ACCURACY_NOTE: &str = "TCA 與距離為數值解（求根容差 1e-6 s），代表求根精度；預報準確度受輸入狀態（TLE 級約公里）與模型不確定性限制";

#[allow(clippy::too_many_arguments)]
pub fn build_event(
    start: &UtcTime,
    ap: &Approach,
    rel: &dyn Fn(f64) -> (V3, V3, V3),
    eph_p: &dyn Ephemeris,
    c3_at: Option<&dyn Fn(f64) -> M3>,
    cov_mode: &str,
    hbr_km: f64,
    other_minima: &[f64],
    span: (f64, f64),
    cov_sources: Option<Value>,
) -> Value {
    let (rp, vp) = eph_p.rv(ap.tau);
    let a_semi = 1.0 / (2.0 / norm(rp) - dot(vp, vp) / GM_KM3_S2);
    let period = 2.0 * std::f64::consts::PI * (a_semi.abs().powi(3) / GM_KM3_S2).sqrt();
    let c = rtn_matrix(rp, vp);
    let vs = add(vp, ap.v_rel);
    let cosang = (dot(vp, vs) / (norm(vp) * norm(vs))).clamp(-1.0, 1.0);
    let mut out = json!({
        "tca_utc": start.plus(ap.tau).iso(), "tca_tau_s": ap.tau, "flag": ap.flag,
        "miss_km": ap.miss_km, "v_rel_kms": norm(ap.v_rel),
        "miss_rtn_km": mv(&c, ap.r_rel),
        "approach_angle_deg": cosang.acos().to_degrees(),
        "accuracy": {"root_precision_s": 1e-6, "note": ACCURACY_NOTE},
    });
    let scr = screen(rel, ap.tau, c3_at, cov_mode, hbr_km, period, other_minima, span);
    let passes = scr["status"] == "passes_initial_screen";
    out["applicability"] = scr;
    if let Some(c3f) = c3_at {
        let c3 = c3f(ap.tau);
        let (miss2, c2, _f) = project(ap.r_rel, ap.v_rel, &c3);
        out["bplane"] = json!({"miss_km": miss2, "cov_km2": c2});
        let (pf, pch) = match (pc_foster(miss2, &c2, hbr_km), pc_chan(miss2, &c2, hbr_km)) {
            (Ok(a), Ok(b)) => (Some(a), Some(b)),
            _ => (None, None),
        };
        out["pc"] = json!({
            "foster": pf, "chan": pch, "hbr_km": hbr_km, "covariance_mode": cov_mode,
            "covariance_source": cov_sources.unwrap_or(Value::Null),
            "interpretation": if passes { "通過目前啟發式篩選；Pc 為所列協方差假設下的值" } else { "未通過或無法判定適用性篩選；二維 Pc 僅供參考" },
        });
    }
    out
}
