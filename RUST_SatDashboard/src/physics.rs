//! 純數學運算：SGP4 傳播、TEME→大地座標、KD-tree 接近篩選、Chan (2008) Pc。
//! 對應 Python physics/coords.py、propagate.py、conjunction.py。

use chrono::{DateTime, NaiveDateTime, Utc};
use kiddo::immutable::float::kdtree::ImmutableKdTree;
use kiddo::SquaredEuclidean;
use rayon::prelude::*;

use crate::config::MAX_ALT_KM;

pub const R_EARTH_KM: f64 = 6378.137;
const F_EARTH: f64 = 1.0 / 298.257223563;
const E2: f64 = F_EARTH * (2.0 - F_EARTH);

/// 預先初始化好的 SGP4 傳播器（每顆衛星一個，索引建立時平行建好）
pub struct Propagator {
    pub constants: sgp4::Constants,
    pub epoch: NaiveDateTime,
}

/// 修正 TLE 行末檢查碼（Python sgp4 不驗證檢查碼，Rust crate 會；DB 內有少數合成 TLE 檢查碼不符）
fn fix_checksum(line: &str) -> String {
    let b = line.as_bytes();
    if b.len() < 69 {
        return line.to_string();
    }
    let sum: u32 = b[..68]
        .iter()
        .map(|&c| match c {
            b'0'..=b'9' => (c - b'0') as u32,
            b'-' => 1,
            _ => 0,
        })
        .sum();
    let mut s = line[..68].to_string();
    s.push(char::from(b'0' + (sum % 10) as u8));
    s
}

impl Propagator {
    /// 等同 Python `Satrec.twoline2rv`（WGS72 + improved 模式）
    pub fn from_tle(line1: &str, line2: &str) -> Option<Self> {
        let l1 = fix_checksum(line1.trim_end());
        let l2 = fix_checksum(line2.trim_end());
        let el = sgp4::Elements::from_tle(None, l1.as_bytes(), l2.as_bytes()).ok()?;
        let constants = sgp4::Constants::from_elements_afspc_compatibility_mode(&el).ok()?;
        Some(Self {
            constants,
            epoch: el.datetime,
        })
    }

    /// TEME 位置（km）；SGP4 錯誤（衰退、離心率越界…）回傳 None
    pub fn position(&self, t: &DateTime<Utc>) -> Option<[f64; 3]> {
        let ns = (t.naive_utc() - self.epoch).num_nanoseconds()?;
        let p = self
            .constants
            .propagate(sgp4::MinutesSinceEpoch(ns as f64 / 60e9))
            .ok()?;
        let r = p.position;
        // 同 Python sgp4 錯誤碼 6：軌道半徑 < 地球半徑（WGS72 6378.135 km）視為已衰退
        let mag2 = r[0] * r[0] + r[1] * r[1] + r[2] * r[2];
        if r.iter().all(|v| v.is_finite()) && mag2 >= 6378.135 * 6378.135 {
            Some(r)
        } else {
            None
        }
    }

    /// 經緯高（含高度合理性過濾）
    pub fn llh(&self, t: &DateTime<Utc>) -> Option<[f64; 3]> {
        let r = self.position(t)?;
        let g = gmst_rad(t);
        let llh = eci_to_llh(&r, g);
        (llh[2] > -500.0 && llh[2] < MAX_ALT_KM).then_some(llh)
    }
}

impl Propagator {
    /// 由平均根數建傳播器（精簡 DB 無 TLE 兩行時；等同 Python sgp4init WGS72 'i'）
    #[allow(clippy::too_many_arguments)]
    pub fn from_elements(
        epoch: NaiveDateTime,
        ecc: f64,
        incl_deg: f64,
        raan_deg: f64,
        argp_deg: f64,
        ma_deg: f64,
        mm_revday: f64,
        bstar: f64,
    ) -> Option<Self> {
        let d2r = std::f64::consts::PI / 180.0;
        let orbit = sgp4::Orbit::from_kozai_elements(
            &sgp4::WGS72,
            incl_deg * d2r,
            raan_deg * d2r,
            ecc,
            argp_deg * d2r,
            ma_deg * d2r,
            mm_revday * std::f64::consts::PI / 720.0,
        )
        .ok()?;
        let constants = sgp4::Constants::new(
            sgp4::WGS72,
            sgp4::afspc_epoch_to_sidereal_time,
            sgp4::julian_years_since_j2000_afspc_compatibility_mode(&epoch),
            bstar,
            orbit,
        )
        .ok()?;
        Some(Self { constants, epoch })
    }
}

/// 地面觀測站（ECEF 與 ENU 旋轉所需三角函數）
#[derive(Clone, Copy)]
pub struct Observer {
    pub x0: f64,
    pub y0: f64,
    pub z0: f64,
    sl: f64,
    cl: f64,
    so: f64,
    co: f64,
}

impl Observer {
    pub fn new(lat_deg: f64, lon_deg: f64, h_km: f64) -> Self {
        let (sl, cl) = lat_deg.to_radians().sin_cos();
        let (so, co) = lon_deg.to_radians().sin_cos();
        let n = R_EARTH_KM / (1.0 - E2 * sl * sl).sqrt();
        Self {
            x0: (n + h_km) * cl * co,
            y0: (n + h_km) * cl * so,
            z0: (n * (1.0 - E2) + h_km) * sl,
            sl,
            cl,
            so,
            co,
        }
    }

    /// TEME → 站心 ENU（km）
    pub fn enu(&self, r: &[f64; 3], gmst: f64) -> [f64; 3] {
        let e = teme_to_ecef(r, gmst);
        let (dx, dy, dz) = (e[0] - self.x0, e[1] - self.y0, e[2] - self.z0);
        [
            -self.so * dx + self.co * dy,
            -self.sl * self.co * dx - self.sl * self.so * dy + self.cl * dz,
            self.cl * self.co * dx + self.cl * self.so * dy + self.sl * dz,
        ]
    }

    /// (仰角°, 方位角°, 斜距 km)
    pub fn elaz(&self, r: &[f64; 3], gmst: f64) -> (f64, f64, f64) {
        let [e, n, u] = self.enu(r, gmst);
        let rng = (e * e + n * n + u * u).sqrt();
        let el = (u / rng.max(0.001)).clamp(-1.0, 1.0).asin().to_degrees();
        let az = e.atan2(n).to_degrees().rem_euclid(360.0);
        (el, az, rng)
    }
}

pub fn teme_to_ecef(r: &[f64; 3], gmst: f64) -> [f64; 3] {
    let (sg, cg) = gmst.sin_cos();
    [cg * r[0] + sg * r[1], -sg * r[0] + cg * r[1], r[2]]
}

pub fn julian_date(t: &DateTime<Utc>) -> f64 {
    t.timestamp() as f64 / 86400.0 + t.timestamp_subsec_nanos() as f64 / 86400e9 + 2440587.5
}

/// IAU 2006 GMST（弧度）
pub fn gmst_rad(t: &DateTime<Utc>) -> f64 {
    let d = julian_date(t) - 2451545.0;
    let tc = d / 36525.0;
    let deg = (280.46061837 + 360.98564736629 * d + 0.000387933 * tc * tc - tc * tc * tc / 38710000.0)
        .rem_euclid(360.0);
    deg.to_radians()
}

/// ECI(TEME) km → [lat_deg, lon_deg, alt_km]（5 次疊代大地緯度）
pub fn eci_to_llh(r: &[f64; 3], gmst: f64) -> [f64; 3] {
    let (sg, cg) = gmst.sin_cos();
    let xe = cg * r[0] + sg * r[1];
    let ye = -sg * r[0] + cg * r[1];
    let ze = r[2];
    let lon = ye.atan2(xe);
    let rr = (xe * xe + ye * ye).sqrt();
    let mut lat = ze.atan2(rr * (1.0 - E2));
    let mut alt = 0.0;
    for _ in 0..5 {
        let sl = lat.sin();
        let n = R_EARTH_KM / (1.0 - E2 * sl * sl).sqrt();
        let cl = lat.cos();
        alt = if cl.abs() > 1e-9 {
            rr / cl - n
        } else {
            ze.abs() / (1.0 - E2) - n
        };
        lat = ze.atan2(rr * (1.0 - E2 * (n / (n + alt))));
    }
    [lat.to_degrees(), lon.to_degrees(), alt]
}

pub fn round_to(x: f64, d: i32) -> f64 {
    let m = 10f64.powi(d);
    (x * m).round() / m
}

/// Python 風格科學記號 "1.23e-05"
pub fn py_sci(x: f64) -> String {
    let s = format!("{x:.2e}");
    match s.split_once('e') {
        Some((m, e)) => {
            let (sign, digits) = match e.strip_prefix('-') {
                Some(d) => ('-', d),
                None => ('+', e),
            };
            format!("{m}e{sign}{digits:0>2}")
        }
        None => s,
    }
}

/// Chan (2008) 2-D 碰撞機率各向同性首階近似（排序代理，非作業級 Pc）
pub fn compute_pc_chan(miss_km: f64, sigma_r: f64, sigma_t: f64, r_sat: f64) -> f64 {
    let s2 = sigma_r * sigma_r + sigma_t * sigma_t;
    if s2 <= 0.0 {
        return 0.0;
    }
    let x = r_sat * r_sat / (2.0 * s2);
    let base = if x < 50.0 { 1.0 - (-x).exp() } else { 1.0 };
    let miss = (-0.5 * miss_km * miss_km / s2).exp();
    round_to(base * miss, 8)
}

pub fn risk_level(pc: f64) -> &'static str {
    if pc > 1e-4 {
        "RED"
    } else if pc > 1e-6 {
        "AMBER"
    } else {
        "GREEN"
    }
}

pub struct ScanResult {
    /// (i, j, miss_km)，i/j 為輸入切片索引，已依 miss 遞增排序並截斷
    pub pairs: Vec<(usize, usize, f64)>,
    pub llh: Vec<[f64; 3]>,
    pub total_scanned: usize,
    /// 兩端屬同一座太空站（艙段／對接中太空船）而排除的配對數
    pub docked_excluded: usize,
    pub t_sgp4: f64,
    pub t_kd: f64,
}

/// 太空站核心艙 NORAD（ISS ZARYA、天宮 天和）：其 STATION_RADIUS_KM 內的物件視為同一座太空站
pub const STATION_ANCHORS: [u32; 2] = [25544, 48274];
pub const STATION_RADIUS_KM: f64 = 1.0;

/// 全目錄瞬時鄰近篩選：平行 SGP4 → 高度過濾 → 不可變 KD-tree → 平行半徑查詢
/// `anchors`：太空站核心艙在 `props` 中的索引；位於其 STATION_RADIUS_KM 內的物件歸為同一群組，
/// 兩端同群組的配對（常共用同一組 TLE、距離 0 km）不是接近事件，不列入。
pub fn scan_pairs(
    props: &[Option<&Propagator>],
    t: &DateTime<Utc>,
    threshold_km: f64,
    max_pairs: usize,
    anchors: &[usize],
) -> ScanResult {
    let t0 = std::time::Instant::now();
    let g = gmst_rad(t);
    let states: Vec<Option<([f64; 3], [f64; 3])>> = props
        .par_iter()
        .map(|p| {
            let r = p.as_ref()?.position(t)?;
            let llh = eci_to_llh(&r, g);
            (llh[2] > -500.0 && llh[2] < 80_000.0).then_some((r, llh))
        })
        .collect();
    let t_sgp4 = t0.elapsed().as_secs_f64();

    let mut llh = vec![[f64::NAN; 3]; props.len()];
    let mut pts: Vec<[f64; 3]> = Vec::with_capacity(props.len());
    let mut map: Vec<usize> = Vec::with_capacity(props.len());
    for (i, s) in states.iter().enumerate() {
        if let Some((r, l)) = s {
            llh[i] = *l;
            pts.push(*r);
            map.push(i);
        }
    }
    let total = pts.len();
    if total < 2 {
        return ScanResult {
            pairs: vec![],
            llh,
            total_scanned: total,
            docked_excluded: 0,
            t_sgp4,
            t_kd: 0.0,
        };
    }

    let t1 = std::time::Instant::now();
    let tree: ImmutableKdTree<f64, u64, 3, 32> = ImmutableKdTree::new_from_slice(&pts);
    let r2 = threshold_km * threshold_km;
    let mut pairs: Vec<(usize, usize, f64)> = pts
        .par_iter()
        .enumerate()
        .flat_map_iter(|(a, p)| {
            tree.within_unsorted::<SquaredEuclidean>(p, r2)
                .into_iter()
                .filter_map(move |nn| {
                    let b = nn.item as usize;
                    (b > a).then(|| (a, b, nn.distance.sqrt()))
                })
        })
        .collect();
    let t_kd = t1.elapsed().as_secs_f64();

    // 太空站群組（pts 索引 → 群組編號）
    let mut group: std::collections::HashMap<usize, usize> = std::collections::HashMap::new();
    for (g, &ai) in anchors.iter().enumerate() {
        let Some(a) = map.iter().position(|&m| m == ai) else { continue };
        let pa = pts[a];
        for (k, p) in pts.iter().enumerate() {
            let d2 = (p[0] - pa[0]).powi(2) + (p[1] - pa[1]).powi(2) + (p[2] - pa[2]).powi(2);
            if d2 <= STATION_RADIUS_KM * STATION_RADIUS_KM {
                group.insert(k, g);
            }
        }
    }
    let before = pairs.len();
    pairs.retain(|&(a, b, _)| !matches!((group.get(&a), group.get(&b)), (Some(x), Some(y)) if x == y));
    let docked_excluded = before - pairs.len();

    pairs.sort_by(|x, y| x.2.total_cmp(&y.2));
    pairs.truncate(max_pairs);
    let pairs = pairs.into_iter().map(|(a, b, d)| (map[a], map[b], d)).collect();
    ScanResult {
        pairs,
        llh,
        total_scanned: total,
        docked_excluded,
        t_sgp4,
        t_kd,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const L1: &str = "1 25544U 98067A   20194.88612269 -.00002218  00000-0 -31515-4 0  9992";
    const L2: &str = "2 25544  51.6461 221.2784 0001413  89.1723 280.4612 15.49507896236008";

    #[test]
    fn iss_altitude_sane() {
        let p = Propagator::from_tle(L1, L2).unwrap();
        let t = p.epoch.and_utc() + chrono::Duration::minutes(30);
        let llh = p.llh(&t).unwrap();
        assert!(llh[2] > 380.0 && llh[2] < 440.0, "{llh:?}");
        assert!(llh[0].abs() <= 51.7);
    }

    #[test]
    fn bad_checksum_tolerated() {
        let bad = format!("{}0", &L1[..68]);
        assert!(Propagator::from_tle(&bad, L2).is_some());
    }

    #[test]
    fn sci_format() {
        assert_eq!(py_sci(1.2345e-5), "1.23e-05");
        assert_eq!(py_sci(0.0), "0.00e+00");
    }

    #[test]
    fn pc_monotonic() {
        let a = compute_pc_chan(0.1, 0.1, 0.5, 0.005);
        let b = compute_pc_chan(5.0, 0.1, 0.5, 0.005);
        assert!(a > b);
    }
}
