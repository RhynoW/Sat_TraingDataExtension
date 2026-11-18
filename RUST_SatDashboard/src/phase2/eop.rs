//! 地球定向參數（CelesTrak EOP-All.csv），MJD 線性內插；UT1−UTC 以 UT1−TAI 內插後加回當日 DAT。

use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use super::constants::ARCSEC_TO_RAD;

#[derive(Clone, Copy, Debug)]
pub struct EopValues {
    pub xp_rad: f64,
    pub yp_rad: f64,
    pub ut1_utc_s: f64,
    pub lod_s: f64,
    pub dx_rad: f64,
    pub dy_rad: f64,
    pub dat_s: f64,
    pub predicted: bool,
}

pub trait EopSource {
    fn at(&self, mjd_utc: f64) -> anyhow::Result<EopValues>;
}

pub struct Eop {
    pub path: PathBuf,
    pub sha256: String,
    mjd: Vec<f64>,
    rows: Vec<[f64; 8]>, // x, y, ut1-tai, lod, dx, dy, dat, predicted(0/1)
    pub last_observed: Option<String>,
}

impl Eop {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let raw = std::fs::read(path)?;
        let sha = format!("{:x}", Sha256::digest(&raw));
        let text = String::from_utf8(raw)?;
        let mut lines = text.lines();
        let header: Vec<&str> = lines.next().unwrap_or("").split(',').map(str::trim).collect();
        let col = |n: &str| header.iter().position(|h| *h == n).ok_or_else(|| anyhow::anyhow!("EOP 缺欄位 {n}"));
        let (cd, cm, cx, cy, cu, cl, cdx, cdy, cdat, ct) = (
            col("DATE")?, col("MJD")?, col("X")?, col("Y")?, col("UT1-UTC")?, col("LOD")?, col("DX")?, col("DY")?,
            col("DAT")?, col("DATA_TYPE")?,
        );
        let (mut mjd, mut rows, mut last_obs) = (Vec::new(), Vec::new(), None);
        for ln in lines {
            let f: Vec<&str> = ln.split(',').map(str::trim).collect();
            if f.len() < header.len() {
                continue;
            }
            let p = |i: usize| f[i].parse::<f64>().unwrap_or(f64::NAN);
            let dat = p(cdat);
            let obs = f[ct] == "O";
            mjd.push(p(cm));
            rows.push([p(cx), p(cy), p(cu) - dat, p(cl), p(cdx), p(cdy), dat, if obs { 0.0 } else { 1.0 }]);
            if obs {
                last_obs = Some(f[cd].to_string());
            }
        }
        anyhow::ensure!(mjd.len() >= 2, "EOP 檔資料不足：{}", path.display());
        Ok(Eop { path: path.to_path_buf(), sha256: sha, mjd, rows, last_observed: last_obs })
    }

    pub fn version(&self) -> serde_json::Value {
        serde_json::json!({
            "file": self.path.file_name().map(|s| s.to_string_lossy().to_string()),
            "sha256": &self.sha256[..16],
            "mjd_range": [self.mjd[0], self.mjd[self.mjd.len() - 1]],
            "last_observed": self.last_observed,
        })
    }
}

impl EopSource for Eop {
    fn at(&self, mjd_utc: f64) -> anyhow::Result<EopValues> {
        let (first, last) = (self.mjd[0], self.mjd[self.mjd.len() - 1]);
        anyhow::ensure!(first <= mjd_utc && mjd_utc <= last, "MJD {mjd_utc:.5} 超出 EOP 範圍 {first}–{last}");
        let pp = self.mjd.partition_point(|m| *m <= mjd_utc);
        let i = (pp.max(1) - 1).min(self.mjd.len() - 2);
        let (m0, m1) = (self.mjd[i], self.mjd[i + 1]);
        let f = (mjd_utc - m0) / (m1 - m0);
        let (a, b) = (&self.rows[i], &self.rows[i + 1]);
        let lin = |k: usize| a[k] + f * (b[k] - a[k]);
        let dat = if f < 1.0 { a[6] } else { b[6] };
        Ok(EopValues {
            xp_rad: lin(0) * ARCSEC_TO_RAD,
            yp_rad: lin(1) * ARCSEC_TO_RAD,
            ut1_utc_s: lin(2) + dat,
            lod_s: lin(3),
            dx_rad: lin(4) * ARCSEC_TO_RAD,
            dy_rad: lin(5) * ARCSEC_TO_RAD,
            dat_s: dat,
            predicted: a[7] > 0.0 || b[7] > 0.0,
        })
    }
}

/// 測試用：固定 EOP 值
pub struct FixedEop(pub EopValues);

impl EopSource for FixedEop {
    fn at(&self, _mjd: f64) -> anyhow::Result<EopValues> {
        Ok(self.0)
    }
}
