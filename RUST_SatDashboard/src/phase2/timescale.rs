//! 時間尺度：UTC 日（MJD）＋當日秒；TT = UTC + DAT + 32.184 s；UT1 = UTC + (UT1−UTC)。

use chrono::{DateTime, NaiveDate, Timelike};

use super::constants::{DAY_S, MJD0, TT_MINUS_TAI_S};

const MJD_UNIX0: i64 = 40587;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct UtcTime {
    pub mjd: i64,
    pub sec: f64,
}

impl UtcTime {
    pub fn parse(iso: &str) -> anyhow::Result<Self> {
        let dt = DateTime::parse_from_rfc3339(iso.trim())
            .map_err(|e| anyhow::anyhow!("時刻須為含時區的 ISO 8601（建議以 Z 結尾）：{iso}（{e}）"))?
            .with_timezone(&chrono::Utc);
        let days = (dt.date_naive() - NaiveDate::from_ymd_opt(1970, 1, 1).unwrap()).num_days();
        let sec = dt.hour() as f64 * 3600.0 + dt.minute() as f64 * 60.0 + dt.second() as f64
            + dt.nanosecond() as f64 * 1e-9;
        Ok(UtcTime { mjd: MJD_UNIX0 + days, sec })
    }

    pub fn plus(&self, dt_s: f64) -> Self {
        let total = self.sec + dt_s;
        let dd = (total / DAY_S).floor();
        UtcTime { mjd: self.mjd + dd as i64, sec: total - dd * DAY_S }
    }

    pub fn mjd_float(&self) -> f64 {
        self.mjd as f64 + self.sec / DAY_S
    }

    pub fn iso(&self) -> String {
        let mut whole = self.sec.trunc() as i64;
        let mut us = ((self.sec - whole as f64) * 1e6).round() as i64;
        if us >= 1_000_000 {
            whole += 1;
            us -= 1_000_000;
        }
        let secs = (self.mjd - MJD_UNIX0) * 86400 + whole;
        let dt = DateTime::from_timestamp(secs, (us * 1000) as u32).unwrap();
        dt.format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string()
    }

    pub fn tt_jd(&self, dat_s: f64) -> (f64, f64) {
        (MJD0 + self.mjd as f64, (self.sec + dat_s + TT_MINUS_TAI_S) / DAY_S)
    }

    pub fn ut1_jd(&self, ut1_utc_s: f64) -> (f64, f64) {
        (MJD0 + self.mjd as f64, (self.sec + ut1_utc_s) / DAY_S)
    }
}

pub fn seconds_between(a: &UtcTime, b: &UtcTime) -> f64 {
    (b.mjd - a.mjd) as f64 * DAY_S + (b.sec - a.sec)
}
