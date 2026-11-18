//! 凍結的物理常數與數值設定（與 Python scenario04/phase2/constants.py 逐值相同）。

pub const CONSTANTS_VERSION: &str = "phase2-constants-v1";

pub const GM_KM3_S2: f64 = 398600.4418;
pub const RE_KM: f64 = 6378.137;
pub const J2: f64 = 1.08262668355e-3;
pub const J3: f64 = -2.53265648533e-6;
pub const J4: f64 = -1.61962159137e-6;

pub const OMEGA_E_RAD_S: f64 = 7.292115146706979e-5;
pub const WGS84_N: i32 = 1;

pub const ARCSEC_TO_RAD: f64 = 4.848136811095359935899141e-6;
pub const DAY_S: f64 = 86400.0;
pub const MJD0: f64 = 2400000.5;
pub const TT_MINUS_TAI_S: f64 = 32.184;

pub const RK4_STEP_LEO_S: f64 = 10.0;
pub const RK4_STEP_GEO_S: f64 = 60.0;
pub const PN_NODE_STEP_S: f64 = 3600.0;
pub const BRENT_XTOL_S: f64 = 1.0e-6;
pub const GL_RADIAL_N: usize = 32;
pub const GL_ANGULAR_N: usize = 128;
pub const CHAN_MAX_TERMS: usize = 200;

// 自適應近接搜尋（Sprint 1）
pub const SEARCH_COARSE_STEP_S: f64 = 60.0;
pub const SEARCH_MIN_STEP_S: f64 = 1.0;
pub const SEARCH_SUBDIVIDE: usize = 6;
pub const SEARCH_ACCEL_BOUND_KM_S2: f64 = 0.02;
pub const SEARCH_LOW_VREL_KM_S: f64 = 0.01;
pub const SEARCH_TIDAL_COEF_S2: f64 = 4.7e-6;
pub const SEARCH_PERT_ACCEL_KM_S2: f64 = 3.0e-5;
pub const SEARCH_OMEGA_MAX_RAD_S: f64 = 1.3e-3;

// 協方差傳播（Sprint 1）
pub const COV_STEP_LEO_S: f64 = 20.0;
pub const COV_STEP_GEO_S: f64 = 300.0;
pub const COV_JAC_DR_KM: f64 = 1.0e-3;

pub const SCREEN_K_SIGMA: f64 = 5.0;
pub const SCREEN_TENC_MAX_FRAC_PERIOD: f64 = 0.01;
pub const SCREEN_LIN_MAX_FRAC: f64 = 0.1;
pub const SCREEN_COV_DET_MAX_REL: f64 = 0.10;
pub const SCREEN_COV_AXIS_MAX_REL: f64 = 0.10;
pub const SCREEN_COV_ROT_MAX_DEG: f64 = 5.0;

// 避碰決策（Sprint 2）
pub const MAN_N_TIMES: usize = 48;
pub const MAN_N_DV: usize = 20;
pub const MAN_MAX_VERIFY: usize = 10;
pub const MAN_DV_MS_DEFAULT: (f64, f64) = (0.05, 2.0);
pub const MAN_MIN_MISS_DEFAULT_KM: f64 = 1.0;
pub const MAN_G0_MS2: f64 = 9.80665;
pub const MAN_PREFILTER_MARGIN_KM: f64 = 25.0;
pub const MAN_TARGET_MATCH_FRAC_PERIOD: f64 = 0.25;
pub const MAN_PLOT_POINTS: usize = 241;
