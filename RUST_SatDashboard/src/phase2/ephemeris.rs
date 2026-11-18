//! 星曆來源（GCRF）：數值積分（五次 Hermite）或 SGP4（TEME → GCRF），與 Python ephemeris.py 相同。
//!
//! 介面：rv(τ) → (r, v)；rva(τ) → (r, v, a)。τ 為自 screening.start 起算的秒。
//! SGP4 的加速度以 GCRF 速度中央差分（δ = 0.5 s）取得，只在極小值確認時使用。
//! SGP4 常數：WGS-72、opsmode 'i'（與 python-sgp4 預設相同）。
//!
//! 錯誤處理：搜尋演算法以不回傳 Result 的閉包呼叫星曆；SGP4 失敗時回傳 NaN 並記下第一個錯誤，
//! 呼叫端在搜尋結束後以 `take_error()` 檢查（對應 Python 版拋出 ValueError）。

use std::cell::{Cell, RefCell};
use std::collections::HashMap;

use super::frames::{teme_to_gcrf, EarthRotationTable};
use super::integrator::Trajectory;
use super::la::{scale, sub};
use super::timescale::UtcTime;
use super::V3;

pub const SGP4_ACCEL_DT_S: f64 = 0.5;

pub trait Ephemeris {
    fn rv(&self, tau: f64) -> (V3, V3);
    fn rva(&self, tau: f64) -> (V3, V3, V3);
    fn span(&self) -> (f64, f64);
    /// 第一個傳播錯誤（SGP4 錯誤碼等）；無錯誤為 None
    fn take_error(&self) -> Option<String> {
        None
    }
}

pub struct NumericalEphemeris {
    pub traj: Trajectory,
}

impl NumericalEphemeris {
    pub fn new(traj: Trajectory) -> Self {
        NumericalEphemeris { traj }
    }
}

impl Ephemeris for NumericalEphemeris {
    fn rv(&self, tau: f64) -> (V3, V3) {
        let (r, v, _) = self.traj.state(tau);
        (r, v)
    }
    fn rva(&self, tau: f64) -> (V3, V3, V3) {
        self.traj.state(tau)
    }
    fn span(&self) -> (f64, f64) {
        let (a, b) = (self.traj.t0, self.traj.t1());
        (a.min(b), a.max(b))
    }
}

/// 預先建構的 SGP4 衛星（WGS-72、IAU 恆星時 = opsmode 'i'）
pub struct Sgp4Sat {
    k: sgp4::Constants,
    /// 曆元的儒略日整數部（當日 0h，…….5）與日內分數，與 python-sgp4 的 jdsatepoch／jdsatepochF 相同
    jd_epoch: f64,
    jd_epoch_frac: f64,
}

impl Sgp4Sat {
    pub fn from_tle(line1: &str, line2: &str) -> anyhow::Result<Self> {
        let el = sgp4::Elements::from_tle(None, line1.as_bytes(), line2.as_bytes())?;
        let d2r = std::f64::consts::PI / 180.0;
        let k = sgp4::Constants::new(
            sgp4::WGS72,
            sgp4::iau_epoch_to_sidereal_time,
            el.epoch(),
            el.drag_term,
            sgp4::Orbit::from_kozai_elements(
                &sgp4::WGS72,
                el.inclination * d2r,
                el.right_ascension * d2r,
                el.eccentricity,
                el.argument_of_perigee * d2r,
                el.mean_anomaly * d2r,
                el.mean_motion * (std::f64::consts::PI / 720.0),
            )?,
        )?;
        let ep = el.datetime;
        let ep_days = (ep.date() - chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap()).num_days();
        // python-sgp4：jdsatepochF 取 TLE 曆元日的小數部（八位），tsince 以 (jd − jdsatepoch)·1440 + (fr − jdsatepochF)·1440 計算
        let frac = line1.get(20..32).and_then(|f| f.trim().split_once('.')).and_then(|(_, d)| format!("0.{d}").parse::<f64>().ok());
        let jd_epoch_frac = match frac {
            Some(f) => (f * 1e8).round() / 1e8,
            None => {
                (chrono::Timelike::num_seconds_from_midnight(&ep.time()) as f64
                    + chrono::Timelike::nanosecond(&ep.time()) as f64 * 1e-9) / super::constants::DAY_S
            }
        };
        let jd_epoch = super::constants::MJD0 + (40587 + ep_days) as f64;
        Ok(Sgp4Sat { k, jd_epoch, jd_epoch_frac })
    }

    /// TEME 狀態（km、km/s）於 UTC 時刻 t
    pub fn teme(&self, t: &UtcTime) -> anyhow::Result<(V3, V3)> {
        let jd = super::constants::MJD0 + t.mjd as f64;
        let fr = t.sec / super::constants::DAY_S;
        let minutes = (jd - self.jd_epoch) * 1440.0 + (fr - self.jd_epoch_frac) * 1440.0;
        let p = self.k.propagate(sgp4::MinutesSinceEpoch(minutes))?;
        Ok((p.position, p.velocity))
    }
}

pub struct Sgp4Ephemeris<'a> {
    pub sat: Sgp4Sat,
    pub start: UtcTime,
    pub ert: &'a EarthRotationTable,
    pub span: (f64, f64),
    err: RefCell<Option<String>>,
}

impl<'a> Sgp4Ephemeris<'a> {
    pub fn new(line1: &str, line2: &str, start: UtcTime, ert: &'a EarthRotationTable, span: (f64, f64)) -> anyhow::Result<Self> {
        Ok(Sgp4Ephemeris { sat: Sgp4Sat::from_tle(line1, line2)?, start, ert, span, err: RefCell::new(None) })
    }

    fn teme(&self, tau: f64) -> (V3, V3) {
        match self.sat.teme(&self.start.plus(tau)) {
            Ok(x) => x,
            Err(e) => {
                let mut slot = self.err.borrow_mut();
                if slot.is_none() {
                    *slot = Some(format!("SGP4 錯誤（τ={tau:.1} s）：{e}"));
                }
                ([f64::NAN; 3], [f64::NAN; 3])
            }
        }
    }
}

impl Ephemeris for Sgp4Ephemeris<'_> {
    fn rv(&self, tau: f64) -> (V3, V3) {
        let (r, v) = self.teme(tau);
        teme_to_gcrf(r, v, &self.ert.at(tau))
    }
    fn rva(&self, tau: f64) -> (V3, V3, V3) {
        let (r, v) = self.rv(tau);
        let (_, vp) = self.rv(tau + SGP4_ACCEL_DT_S);
        let (_, vm) = self.rv(tau - SGP4_ACCEL_DT_S);
        (r, v, scale(sub(vp, vm), 1.0 / (2.0 * SGP4_ACCEL_DT_S)))
    }
    fn span(&self) -> (f64, f64) {
        self.span
    }
    fn take_error(&self) -> Option<String> {
        self.err.borrow_mut().take()
    }
}

/// 主星在多個配對間重複使用：快取 rv(τ)。鍵與 Python `round(τ, 6)` 相同（十進位六位、精確捨入），
/// 所以鄰近 τ 共用快取值的情形也與 Python 版一致。
pub struct Memo<'e> {
    pub eph: &'e dyn Ephemeris,
    cache: RefCell<HashMap<String, (V3, V3)>>,
}

impl<'e> Memo<'e> {
    pub fn new(eph: &'e dyn Ephemeris) -> Self {
        Memo { eph, cache: RefCell::new(HashMap::new()) }
    }
}

impl Ephemeris for Memo<'_> {
    fn rv(&self, tau: f64) -> (V3, V3) {
        let mut key = format!("{tau:.6}");
        if key == "-0.000000" {
            key = "0.000000".into();
        }
        if let Some(x) = self.cache.borrow().get(&key) {
            return *x;
        }
        let x = self.eph.rv(tau);
        // 傳播失敗（NaN）不快取：Python 版拋出例外時也不會寫入快取
        if !x.0[0].is_nan() {
            self.cache.borrow_mut().insert(key, x);
        }
        x
    }
    fn rva(&self, tau: f64) -> (V3, V3, V3) {
        self.eph.rva(tau)
    }
    fn span(&self) -> (f64, f64) {
        self.eph.span()
    }
    fn take_error(&self) -> Option<String> {
        self.eph.take_error()
    }
}

/// 次星減主星；rv 供掃描（計入 n_evals），rva 供極小值確認
pub struct RelativeState<'a> {
    pub p: &'a dyn Ephemeris,
    pub s: &'a dyn Ephemeris,
    pub n_evals: Cell<usize>,
}

impl<'a> RelativeState<'a> {
    pub fn new(p: &'a dyn Ephemeris, s: &'a dyn Ephemeris) -> Self {
        RelativeState { p, s, n_evals: Cell::new(0) }
    }
    pub fn rv(&self, tau: f64) -> (V3, V3) {
        self.n_evals.set(self.n_evals.get() + 1);
        let (rp, vp) = self.p.rv(tau);
        let (rs, vs) = self.s.rv(tau);
        (sub(rs, rp), sub(vs, vp))
    }
    pub fn rva(&self, tau: f64) -> (V3, V3, V3) {
        let (rp, vp, ap) = self.p.rva(tau);
        let (rs, vs, as_) = self.s.rva(tau);
        (sub(rs, rp), sub(vs, vp), sub(as_, ap))
    }
    pub fn take_error(&self) -> Option<String> {
        self.p.take_error().or_else(|| self.s.take_error())
    }
}
