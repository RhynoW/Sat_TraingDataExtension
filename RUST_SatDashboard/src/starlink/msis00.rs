//! NRLMSISE-00 大氣模式（Picone et al. 2002）之 Rust 移植。
//!
//! 逐行對照 pymsis 0.13 內附之 `NRLMSISE-00.FOR`（GTD7 / GTD7D / GTS7 / GLOBE7 / GLOB7S /
//! DENSU / DENSM / SPLINE / SPLINT / SPLINI / DNET / CCOR / CCOR2 / SCALH / GLATF），
//! 係數表由 BLOCK DATA GTD7BK 機械轉換（msis00_data.rs）。開關全為 1（pymsis 預設 options），
//! 單位為公制（METERS(.TRUE.)），輸入介面同 pymsis `pymsiscalc` 包裝（version=0）。
//!
//! 與 Fortran 版的差異：Fortran 以 SAVE / COMMON 快取上一次呼叫的中間量（VTST7），本移植為
//! 純函式、每次全部重算——兩者結果相同（快取只在輸入相同時重用相同數值）。
//! pymsis 以單精度編譯；這裡用倍精度計算，並把輸入先捨入成單精度，與 pymsis 差異約 1e-6 相對量級。

use super::msis00_data::{PARM7, PAVGM, PDM, PTM};

const DGTR: f64 = 1.74533e-2;
const DR: f64 = 1.72142e-2;
const HR: f64 = 0.2618;
const SR: f64 = 7.2722e-5;
const RGAS: f64 = 831.4;

// PARM7 COMMON 內各陣列起點（Fortran 1-based 欄位以 helper 換算）
const O_PT: usize = 0;
const O_PD: usize = 150;
const O_PS: usize = 1500;
const O_PDL: usize = 1650;
const O_PTL: usize = 1700;
const O_PMA: usize = 2100;

// 開關（TSELEC(25*1.)）：SW = SWC = 1
const SW: f64 = 1.0;
const SWC: f64 = 1.0;

#[inline]
fn pt(i: usize) -> f64 {
    PARM7[O_PT + i - 1]
}
#[inline]
fn pd(i: usize, j: usize) -> f64 {
    PARM7[O_PD + (j - 1) * 150 + i - 1]
}
#[inline]
fn ps(i: usize) -> f64 {
    PARM7[O_PS + i - 1]
}
#[inline]
fn pdl(i: usize, j: usize) -> f64 {
    PARM7[O_PDL + (j - 1) * 25 + i - 1]
}
#[inline]
fn ptl(i: usize, j: usize) -> f64 {
    PARM7[O_PTL + (j - 1) * 100 + i - 1]
}
#[inline]
fn pma(i: usize, j: usize) -> f64 {
    PARM7[O_PMA + (j - 1) * 100 + i - 1]
}
#[inline]
fn ptm(i: usize) -> f64 {
    PTM[i - 1]
}
#[inline]
fn pdm(i: usize, j: usize) -> f64 {
    PDM[(j - 1) * 10 + i - 1]
}
#[inline]
fn pavgm(i: usize) -> f64 {
    PAVGM[i - 1]
}
fn pd_col(j: usize) -> &'static [f64] {
    &PARM7[O_PD + (j - 1) * 150..]
}
fn ptl_col(j: usize) -> &'static [f64] {
    &PARM7[O_PTL + (j - 1) * 100..]
}
fn pma_col(j: usize) -> &'static [f64] {
    &PARM7[O_PMA + (j - 1) * 100..]
}

/// 對應 Fortran COMMON 區塊（LPOLY、MESO7、PARMB、DMIX）之單次呼叫狀態
#[derive(Default)]
struct Ctx {
    gsurf: f64,
    re: f64,
    plg: [[f64; 4]; 9],
    ctloc: f64,
    stloc: f64,
    c2tloc: f64,
    s2tloc: f64,
    c3tloc: f64,
    s3tloc: f64,
    day: f64,
    dfa: f64,
    apdf: f64,
    xlong: f64,
    tn1: [f64; 5],
    tn2: [f64; 4],
    tn3: [f64; 5],
    tgn1: [f64; 2],
    tgn2: [f64; 2],
    tgn3: [f64; 2],
    dm28: f64,
}

impl Ctx {
    #[inline]
    fn plg(&self, i: usize, j: usize) -> f64 {
        self.plg[i - 1][j - 1]
    }

    fn glatf(&mut self, lat: f64) {
        let c2 = (2.0 * DGTR * lat).cos();
        self.gsurf = 980.616 * (1.0 - 0.0026373 * c2);
        self.re = 2.0 * self.gsurf / (3.085462e-6 + 2.27e-9 * c2) * 1.0e-5;
    }

    #[allow(clippy::too_many_arguments)]
    fn globe7(&mut self, yrd: f64, sec: f64, lat: f64, long: f64, tloc: f64, f107a: f64, f107: f64, ap: &[f64; 7], p: &[f64]) -> f64 {
        let pp = |i: usize| p[i - 1];
        let mut t = [0.0f64; 15];
        let iyr = (yrd / 1000.0).trunc();
        self.day = yrd - iyr * 1000.0;
        self.xlong = long;
        let c = (lat * DGTR).sin();
        let s = (lat * DGTR).cos();
        let c2 = c * c;
        let c4 = c2 * c2;
        let s2 = s * s;
        let g = &mut self.plg;
        g[1][0] = c;
        g[2][0] = 0.5 * (3.0 * c2 - 1.0);
        g[3][0] = 0.5 * (5.0 * c * c2 - 3.0 * c);
        g[4][0] = (35.0 * c4 - 30.0 * c2 + 3.0) / 8.0;
        g[5][0] = (63.0 * c2 * c2 * c - 70.0 * c2 * c + 15.0 * c) / 8.0;
        g[6][0] = (11.0 * c * g[5][0] - 5.0 * g[4][0]) / 6.0;
        g[1][1] = s;
        g[2][1] = 3.0 * c * s;
        g[3][1] = 1.5 * (5.0 * c2 - 1.0) * s;
        g[4][1] = 2.5 * (7.0 * c2 * c - 3.0 * c) * s;
        g[5][1] = 1.875 * (21.0 * c4 - 14.0 * c2 + 1.0) * s;
        g[6][1] = (11.0 * c * g[5][1] - 6.0 * g[4][1]) / 5.0;
        g[2][2] = 3.0 * s2;
        g[3][2] = 15.0 * s2 * c;
        g[4][2] = 7.5 * (7.0 * c2 - 1.0) * s2;
        g[5][2] = 3.0 * c * g[4][2] - 2.0 * g[3][2];
        g[6][2] = (11.0 * c * g[5][2] - 7.0 * g[4][2]) / 4.0;
        g[7][2] = (13.0 * c * g[6][2] - 8.0 * g[5][2]) / 5.0;
        g[3][3] = 15.0 * s2 * s;
        g[4][3] = 105.0 * s2 * s * c;
        g[5][3] = (9.0 * c * g[4][3] - 7.0 * g[3][3]) / 2.0;
        g[6][3] = (11.0 * c * g[5][3] - 8.0 * g[4][3]) / 3.0;

        self.stloc = (HR * tloc).sin();
        self.ctloc = (HR * tloc).cos();
        self.s2tloc = (2.0 * HR * tloc).sin();
        self.c2tloc = (2.0 * HR * tloc).cos();
        self.s3tloc = (3.0 * HR * tloc).sin();
        self.c3tloc = (3.0 * HR * tloc).cos();

        let day = self.day;
        let cd14 = (DR * (day - pp(14))).cos();
        let cd18 = (2.0 * DR * (day - pp(18))).cos();
        let cd32 = (DR * (day - pp(32))).cos();
        let cd39 = (2.0 * DR * (day - pp(39))).cos();
        let df = f107 - f107a;
        let dfa = f107a - 150.0;
        self.dfa = dfa;
        let plg = |i: usize, j: usize| self.plg[i - 1][j - 1];

        t[0] = pp(20) * df * (1.0 + pp(60) * dfa) + pp(21) * df * df + pp(22) * dfa + pp(30) * dfa * dfa;
        let f1 = 1.0 + (pp(48) * dfa + pp(20) * df + pp(21) * df * df) * SWC;
        let f2 = 1.0 + (pp(50) * dfa + pp(20) * df + pp(21) * df * df) * SWC;
        t[1] = (pp(2) * plg(3, 1) + pp(3) * plg(5, 1) + pp(23) * plg(7, 1))
            + (pp(15) * plg(3, 1)) * dfa * SWC
            + pp(27) * plg(2, 1);
        t[2] = pp(19) * cd32;
        t[3] = (pp(16) + pp(17) * plg(3, 1)) * cd18;
        t[4] = f1 * (pp(10) * plg(2, 1) + pp(11) * plg(4, 1)) * cd14;
        t[5] = pp(38) * plg(2, 1) * cd39;
        let t71 = (pp(12) * plg(3, 2)) * cd14 * SWC;
        let t72 = (pp(13) * plg(3, 2)) * cd14 * SWC;
        t[6] = f2
            * ((pp(4) * plg(2, 2) + pp(5) * plg(4, 2) + pp(28) * plg(6, 2) + t71) * self.ctloc
                + (pp(7) * plg(2, 2) + pp(8) * plg(4, 2) + pp(29) * plg(6, 2) + t72) * self.stloc);
        let t81 = (pp(24) * plg(4, 3) + pp(36) * plg(6, 3)) * cd14 * SWC;
        let t82 = (pp(34) * plg(4, 3) + pp(37) * plg(6, 3)) * cd14 * SWC;
        t[7] = f2
            * ((pp(6) * plg(3, 3) + pp(42) * plg(5, 3) + t81) * self.c2tloc
                + (pp(9) * plg(3, 3) + pp(43) * plg(5, 3) + t82) * self.s2tloc);
        t[13] = f2
            * ((pp(40) * plg(4, 4) + (pp(94) * plg(5, 4) + pp(47) * plg(7, 4)) * cd14 * SWC) * self.s3tloc
                + (pp(41) * plg(4, 4) + (pp(95) * plg(5, 4) + pp(49) * plg(7, 4)) * cd14 * SWC) * self.c3tloc);

        // SW(9)=1：每日 Ap
        let apd = ap[0] - 4.0;
        let mut p44 = pp(44);
        let p45 = pp(45);
        if p44 < 0.0 {
            p44 = 1.0e-5;
        }
        let apdf = apd + (p45 - 1.0) * (apd + ((-p44 * apd).exp() - 1.0) / p44);
        t[8] = apdf
            * (pp(33)
                + pp(46) * plg(3, 1)
                + pp(35) * plg(5, 1)
                + (pp(101) * plg(2, 1) + pp(102) * plg(4, 1) + pp(103) * plg(6, 1)) * cd14 * SWC
                + (pp(122) * plg(2, 2) + pp(123) * plg(4, 2) + pp(124) * plg(6, 2)) * SWC * (HR * (tloc - pp(125))).cos());

        if long > -1000.0 {
            t[10] = (1.0 + pp(81) * dfa * SWC)
                * ((pp(65) * plg(3, 2)
                    + pp(66) * plg(5, 2)
                    + pp(67) * plg(7, 2)
                    + pp(104) * plg(2, 2)
                    + pp(105) * plg(4, 2)
                    + pp(106) * plg(6, 2)
                    + SWC * (pp(110) * plg(2, 2) + pp(111) * plg(4, 2) + pp(112) * plg(6, 2)) * cd14)
                    * (DGTR * long).cos()
                    + (pp(91) * plg(3, 2)
                        + pp(92) * plg(5, 2)
                        + pp(93) * plg(7, 2)
                        + pp(107) * plg(2, 2)
                        + pp(108) * plg(4, 2)
                        + pp(109) * plg(6, 2)
                        + SWC * (pp(113) * plg(2, 2) + pp(114) * plg(4, 2) + pp(115) * plg(6, 2)) * cd14)
                        * (DGTR * long).sin());
            t[11] = (1.0 + pp(96) * plg(2, 1))
                * (1.0 + pp(82) * dfa * SWC)
                * (1.0 + pp(120) * plg(2, 1) * SWC * cd14)
                * ((pp(69) * plg(2, 1) + pp(70) * plg(4, 1) + pp(71) * plg(6, 1)) * (SR * (sec - pp(72))).cos());
            t[11] += SWC
                * (pp(77) * plg(4, 3) + pp(78) * plg(6, 3) + pp(79) * plg(8, 3))
                * (SR * (sec - pp(80)) + 2.0 * DGTR * long).cos()
                * (1.0 + pp(138) * dfa * SWC);
            t[12] = apdf
                * SWC
                * (1.0 + pp(121) * plg(2, 1))
                * ((pp(61) * plg(3, 2) + pp(62) * plg(5, 2) + pp(63) * plg(7, 2)) * (DGTR * (long - pp(64))).cos())
                + apdf
                    * SWC
                    * SWC
                    * (pp(116) * plg(2, 2) + pp(117) * plg(4, 2) + pp(118) * plg(6, 2))
                    * cd14
                    * (DGTR * (long - pp(119))).cos()
                + apdf * SWC * (pp(84) * plg(2, 1) + pp(85) * plg(4, 1) + pp(86) * plg(6, 1)) * (SR * (sec - pp(76))).cos();
        }
        self.apdf = apdf;
        let mut tinf = pp(31);
        for v in t.iter().take(14) {
            tinf += SW.abs() * v;
        }
        tinf
    }

    fn glob7s(&self, p: &[f64]) -> f64 {
        let pp = |i: usize| p[i - 1];
        let plg = |i: usize, j: usize| self.plg(i, j);
        let day = self.day;
        let mut t = [0.0f64; 14];
        let cd32 = (DR * (day - pp(32))).cos();
        let cd18 = (2.0 * DR * (day - pp(18))).cos();
        let cd14 = (DR * (day - pp(14))).cos();
        let cd39 = (2.0 * DR * (day - pp(39))).cos();
        t[0] = pp(22) * self.dfa;
        t[1] = pp(2) * plg(3, 1) + pp(3) * plg(5, 1) + pp(23) * plg(7, 1) + pp(27) * plg(2, 1) + pp(15) * plg(4, 1) + pp(60) * plg(6, 1);
        t[2] = (pp(19) + pp(48) * plg(3, 1) + pp(30) * plg(5, 1)) * cd32;
        t[3] = (pp(16) + pp(17) * plg(3, 1) + pp(31) * plg(5, 1)) * cd18;
        t[4] = (pp(10) * plg(2, 1) + pp(11) * plg(4, 1) + pp(21) * plg(6, 1)) * cd14;
        t[5] = (pp(38) * plg(2, 1)) * cd39;
        let t71 = pp(12) * plg(3, 2) * cd14 * SWC;
        let t72 = pp(13) * plg(3, 2) * cd14 * SWC;
        t[6] = (pp(4) * plg(2, 2) + pp(5) * plg(4, 2) + t71) * self.ctloc + (pp(7) * plg(2, 2) + pp(8) * plg(4, 2) + t72) * self.stloc;
        let t81 = (pp(24) * plg(4, 3) + pp(36) * plg(6, 3)) * cd14 * SWC;
        let t82 = (pp(34) * plg(4, 3) + pp(37) * plg(6, 3)) * cd14 * SWC;
        t[7] = (pp(6) * plg(3, 3) + pp(42) * plg(5, 3) + t81) * self.c2tloc + (pp(9) * plg(3, 3) + pp(43) * plg(5, 3) + t82) * self.s2tloc;
        t[13] = pp(40) * plg(4, 4) * self.s3tloc + pp(41) * plg(4, 4) * self.c3tloc;
        // SW(9)=1
        t[8] = self.apdf * (pp(33) + pp(46) * plg(3, 1) * SWC);
        let long = self.xlong;
        if long > -1000.0 {
            t[10] = (1.0
                + plg(2, 1) * (pp(81) * SWC * (DR * (day - pp(82))).cos() + pp(86) * SWC * (2.0 * DR * (day - pp(87))).cos())
                + pp(84) * SWC * (DR * (day - pp(85))).cos()
                + pp(88) * SWC * (2.0 * DR * (day - pp(89))).cos())
                * ((pp(65) * plg(3, 2) + pp(66) * plg(5, 2) + pp(67) * plg(7, 2) + pp(75) * plg(2, 2) + pp(76) * plg(4, 2) + pp(77) * plg(6, 2))
                    * (DGTR * long).cos()
                    + (pp(91) * plg(3, 2) + pp(92) * plg(5, 2) + pp(93) * plg(7, 2) + pp(78) * plg(2, 2) + pp(79) * plg(4, 2) + pp(80) * plg(6, 2))
                        * (DGTR * long).sin());
        }
        t.iter().map(|v| SW.abs() * v).sum()
    }

    #[allow(clippy::too_many_arguments)]
    fn densu(&mut self, alt: f64, dlb: f64, tinf: f64, tlb: f64, xm: f64, alpha: f64, tz: &mut f64, zlb: f64, s2: f64, zn1: &[f64; 5]) -> f64 {
        let re = self.re;
        let zeta = |zz: f64, zl: f64| (zz - zl) * (re + zl) / (re + zz);
        let za = zn1[0];
        let z = alt.max(za);
        let zg2 = zeta(z, zlb);
        let tt = tinf - (tinf - tlb) * (-s2 * zg2).exp();
        let ta = tt;
        *tz = tt;
        let mut densu = *tz;
        let mut xs = [0.0; 5];
        let mut ys = [0.0; 5];
        let mut y2out = [0.0; 5];
        let (mut x, mut zgdif, mut z1, mut t1) = (0.0, 0.0, 0.0, 0.0);
        if alt < za {
            let dta = (tinf - ta) * s2 * ((re + zlb) / (re + za)).powi(2);
            self.tgn1[0] = dta;
            self.tn1[0] = ta;
            let z = alt.max(zn1[4]);
            z1 = zn1[0];
            let z2 = zn1[4];
            t1 = self.tn1[0];
            let t2 = self.tn1[4];
            let zg = zeta(z, z1);
            zgdif = zeta(z2, z1);
            for k in 0..5 {
                xs[k] = zeta(zn1[k], z1) / zgdif;
                ys[k] = 1.0 / self.tn1[k];
            }
            let yd1 = -self.tgn1[0] / (t1 * t1) * zgdif;
            let yd2 = -self.tgn1[1] / (t2 * t2) * zgdif * ((re + z2) / (re + z1)).powi(2);
            spline(&xs, &ys, yd1, yd2, &mut y2out);
            x = zg / zgdif;
            let y = splint(&xs, &ys, &y2out, x);
            *tz = 1.0 / y;
            densu = *tz;
        }
        if xm == 0.0 {
            return densu;
        }
        let glb = self.gsurf / (1.0 + zlb / re).powi(2);
        let gamma = xm * glb / (s2 * RGAS * tinf);
        let mut expl = (-s2 * gamma * zg2).exp();
        if expl > 50.0 || tt <= 0.0 {
            expl = 50.0;
        }
        let densa = dlb * (tlb / tt).powf(1.0 + alpha + gamma) * expl;
        densu = densa;
        if alt >= za {
            return densu;
        }
        let glb = self.gsurf / (1.0 + z1 / re).powi(2);
        let gamm = xm * glb * zgdif / RGAS;
        let yi = splini(&xs, &ys, &y2out, x);
        let mut expl = gamm * yi;
        if expl > 50.0 || *tz <= 0.0 {
            expl = 50.0;
        }
        densu * (t1 / *tz).powf(1.0 + alpha) * (-expl).exp()
    }

    #[allow(clippy::too_many_arguments)]
    fn densm(&self, alt: f64, d0: f64, xm: f64, tz: &mut f64, zn3: &[f64; 5], zn2: &[f64; 4]) -> f64 {
        let re = self.re;
        let zeta = |zz: f64, zl: f64| (zz - zl) * (re + zl) / (re + zz);
        let mut densm = d0;
        if alt <= zn2[0] {
            let z = alt.max(zn2[3]);
            let z1 = zn2[0];
            let z2 = zn2[3];
            let t1 = self.tn2[0];
            let t2 = self.tn2[3];
            let zg = zeta(z, z1);
            let zgdif = zeta(z2, z1);
            let mut xs = [0.0; 4];
            let mut ys = [0.0; 4];
            let mut y2 = [0.0; 4];
            for k in 0..4 {
                xs[k] = zeta(zn2[k], z1) / zgdif;
                ys[k] = 1.0 / self.tn2[k];
            }
            let yd1 = -self.tgn2[0] / (t1 * t1) * zgdif;
            let yd2 = -self.tgn2[1] / (t2 * t2) * zgdif * ((re + z2) / (re + z1)).powi(2);
            spline(&xs, &ys, yd1, yd2, &mut y2);
            let x = zg / zgdif;
            let y = splint(&xs, &ys, &y2, x);
            *tz = 1.0 / y;
            if xm != 0.0 {
                let glb = self.gsurf / (1.0 + z1 / re).powi(2);
                let gamm = xm * glb * zgdif / RGAS;
                let yi = splini(&xs, &ys, &y2, x);
                let expl = (gamm * yi).min(50.0);
                densm = densm * (t1 / *tz) * (-expl).exp();
            }
            if alt <= zn3[0] {
                let z = alt;
                let z1 = zn3[0];
                let z2 = zn3[4];
                let t1 = self.tn3[0];
                let t2 = self.tn3[4];
                let zg = zeta(z, z1);
                let zgdif = zeta(z2, z1);
                let mut xs = [0.0; 5];
                let mut ys = [0.0; 5];
                let mut y2 = [0.0; 5];
                for k in 0..5 {
                    xs[k] = zeta(zn3[k], z1) / zgdif;
                    ys[k] = 1.0 / self.tn3[k];
                }
                let yd1 = -self.tgn3[0] / (t1 * t1) * zgdif;
                let yd2 = -self.tgn3[1] / (t2 * t2) * zgdif * ((re + z2) / (re + z1)).powi(2);
                spline(&xs, &ys, yd1, yd2, &mut y2);
                let x = zg / zgdif;
                let y = splint(&xs, &ys, &y2, x);
                *tz = 1.0 / y;
                if xm != 0.0 {
                    let glb = self.gsurf / (1.0 + z1 / re).powi(2);
                    let gamm = xm * glb * zgdif / RGAS;
                    let yi = splini(&xs, &ys, &y2, x);
                    let expl = (gamm * yi).min(50.0);
                    densm = densm * (t1 / *tz) * (-expl).exp();
                }
            }
        }
        if xm == 0.0 {
            densm = *tz;
        }
        densm
    }

    fn scalh(&self, alt: f64, xm: f64, temp: f64) -> f64 {
        let g = self.gsurf / (1.0 + alt / self.re).powi(2);
        RGAS * temp / (g * xm)
    }

    /// GTS7（高度 > 72.5 km 之熱氣層），mass ∈ {28, 48}；回傳 (D[9], T[2])，已換成公制
    #[allow(clippy::too_many_arguments)]
    fn gts7(&mut self, iyd: i64, sec: f64, alt: f64, glat: f64, glong: f64, stl: f64, f107a: f64, f107: f64, ap: &[f64; 7], mass: i32) -> ([f64; 9], [f64; 2]) {
        const ALPHA: [f64; 9] = [-0.38, 0.0, 0.0, 0.0, 0.17, 0.0, -0.38, 0.0, 0.0];
        const ALTL: [f64; 8] = [200.0, 300.0, 160.0, 250.0, 240.0, 450.0, 320.0, 450.0];
        let yrd = iyd as f64;
        let za = pdl(16, 2);
        let zn1 = [za, 110.0, 100.0, 90.0, 72.5];
        let mut d = [0.0f64; 9];
        let mut t = [0.0f64; 2];
        let tinf = if alt > zn1[0] {
            ptm(1) * pt(1) * (1.0 + SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, &PARM7[O_PT..]))
        } else {
            ptm(1) * pt(1)
        };
        t[0] = tinf;
        let g0 = if alt > zn1[4] {
            ptm(4) * ps(1) * (1.0 + SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, &PARM7[O_PS..]))
        } else {
            ptm(4) * ps(1)
        };
        let tlb = ptm(2) * (1.0 + SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(4))) * pd(1, 4);
        let s = g0 / (tinf - tlb);
        if alt < 300.0 {
            self.tn1[1] = ptm(7) * ptl(1, 1) / (1.0 - SW * self.glob7s(ptl_col(1)));
            self.tn1[2] = ptm(3) * ptl(1, 2) / (1.0 - SW * self.glob7s(ptl_col(2)));
            self.tn1[3] = ptm(8) * ptl(1, 3) / (1.0 - SW * self.glob7s(ptl_col(3)));
            self.tn1[4] = ptm(5) * ptl(1, 4) / (1.0 - SW * SW * self.glob7s(ptl_col(4)));
            self.tgn1[1] = ptm(9) * pma(1, 9) * (1.0 + SW * SW * self.glob7s(pma_col(9))) * self.tn1[4] * self.tn1[4]
                / (ptm(5) * ptl(1, 4)).powi(2);
        } else {
            self.tn1[1] = ptm(7) * ptl(1, 1);
            self.tn1[2] = ptm(3) * ptl(1, 2);
            self.tn1[3] = ptm(8) * ptl(1, 3);
            self.tn1[4] = ptm(5) * ptl(1, 4);
            self.tgn1[1] = ptm(9) * pma(1, 9) * self.tn1[4] * self.tn1[4] / (ptm(5) * ptl(1, 4)).powi(2);
        }

        let g28 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(3));
        let day = yrd % 1000.0;
        let zhf = pdl(25, 2) * (1.0 + SW * pdl(25, 1) * (DGTR * glat).sin() * (DR * (day - pt(14))).cos());
        let xmm = pdm(5, 3);
        let z = alt;
        let mut tz = 0.0;
        let mut t2 = 0.0;

        // N2（mass 28/48 一律計算）
        let db28 = pdm(1, 3) * g28.exp() * pd(1, 3);
        d[2] = self.densu(z, db28, tinf, tlb, 28.0, ALPHA[2], &mut t[1], ptm(6), s, &zn1);
        let zh28 = pdm(3, 3) * zhf;
        let zhm28 = pdm(4, 3) * pdl(6, 2);
        let xmd = 28.0 - xmm;
        let b28 = self.densu(zh28, db28, tinf, tlb, xmd, ALPHA[2] - 1.0, &mut tz, ptm(6), s, &zn1);
        if z <= ALTL[2] && SW != 0.0 {
            self.dm28 = self.densu(z, b28, tinf, tlb, xmm, ALPHA[2], &mut tz, ptm(6), s, &zn1);
            d[2] = dnet(d[2], self.dm28, zhm28, xmm, 28.0);
        }
        if mass == 48 {
            // He
            let g4 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(1));
            let db04 = pdm(1, 1) * g4.exp() * pd(1, 1);
            d[0] = self.densu(z, db04, tinf, tlb, 4.0, ALPHA[0], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[0] {
                let zh04 = pdm(3, 1);
                let b04 = self.densu(zh04, db04, tinf, tlb, 4.0 - xmm, ALPHA[0] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm04 = self.densu(z, b04, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[0] = dnet(d[0], dm04, zhm28, xmm, 4.0);
                let rl = (b28 * pdm(2, 1) / b04).ln();
                let zc04 = pdm(5, 1) * pdl(1, 2);
                let hc04 = pdm(6, 1) * pdl(2, 2);
                d[0] *= ccor(z, rl, hc04, zc04);
            }
            // O
            let g16 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(2));
            let db16 = pdm(1, 2) * g16.exp() * pd(1, 2);
            d[1] = self.densu(z, db16, tinf, tlb, 16.0, ALPHA[1], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[1] {
                let zh16 = pdm(3, 2);
                let b16 = self.densu(zh16, db16, tinf, tlb, 16.0 - xmm, ALPHA[1] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm16 = self.densu(z, b16, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[1] = dnet(d[1], dm16, zhm28, xmm, 16.0);
                let rl = pdm(2, 2) * pdl(17, 2) * (1.0 + SW * pdl(24, 1) * (f107a - 150.0));
                let hc16 = pdm(6, 2) * pdl(4, 2);
                let zc16 = pdm(5, 2) * pdl(3, 2);
                let hc216 = pdm(6, 2) * pdl(5, 2);
                d[1] *= ccor2(z, rl, hc16, zc16, hc216);
                let hcc16 = pdm(8, 2) * pdl(14, 2);
                let zcc16 = pdm(7, 2) * pdl(13, 2);
                let rc16 = pdm(4, 2) * pdl(15, 2);
                d[1] *= ccor(z, rc16, hcc16, zcc16);
            }
            // O2
            let g32 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(5));
            let db32 = pdm(1, 4) * g32.exp() * pd(1, 5);
            d[3] = self.densu(z, db32, tinf, tlb, 32.0, ALPHA[3], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[3] {
                let zh32 = pdm(3, 4);
                let b32 = self.densu(zh32, db32, tinf, tlb, 32.0 - xmm, ALPHA[3] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm32 = self.densu(z, b32, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[3] = dnet(d[3], dm32, zhm28, xmm, 32.0);
                let rl = (b28 * pdm(2, 4) / b32).ln();
                let hc32 = pdm(6, 4) * pdl(8, 2);
                let zc32 = pdm(5, 4) * pdl(7, 2);
                d[3] *= ccor(z, rl, hc32, zc32);
            }
            let hcc32 = pdm(8, 4) * pdl(23, 2);
            let hcc232 = pdm(8, 4) * pdl(23, 1);
            let zcc32 = pdm(7, 4) * pdl(22, 2);
            let rc32 = pdm(4, 4) * pdl(24, 2) * (1.0 + SW * pdl(24, 1) * (f107a - 150.0));
            d[3] *= ccor2(z, rc32, hcc32, zcc32, hcc232);
            // Ar
            let g40 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(6));
            let db40 = pdm(1, 5) * g40.exp() * pd(1, 6);
            d[4] = self.densu(z, db40, tinf, tlb, 40.0, ALPHA[4], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[4] {
                let zh40 = pdm(3, 5);
                let b40 = self.densu(zh40, db40, tinf, tlb, 40.0 - xmm, ALPHA[4] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm40 = self.densu(z, b40, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[4] = dnet(d[4], dm40, zhm28, xmm, 40.0);
                let rl = (b28 * pdm(2, 5) / b40).ln();
                let hc40 = pdm(6, 5) * pdl(10, 2);
                let zc40 = pdm(5, 5) * pdl(9, 2);
                d[4] *= ccor(z, rl, hc40, zc40);
            }
            // H
            let g1 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(7));
            let db01 = pdm(1, 6) * g1.exp() * pd(1, 7);
            d[6] = self.densu(z, db01, tinf, tlb, 1.0, ALPHA[6], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[6] {
                let zh01 = pdm(3, 6);
                let b01 = self.densu(zh01, db01, tinf, tlb, 1.0 - xmm, ALPHA[6] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm01 = self.densu(z, b01, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[6] = dnet(d[6], dm01, zhm28, xmm, 1.0);
                let rl = (b28 * pdm(2, 6) * pdl(18, 2).abs() / b01).ln();
                let hc01 = pdm(6, 6) * pdl(12, 2);
                let zc01 = pdm(5, 6) * pdl(11, 2);
                d[6] *= ccor(z, rl, hc01, zc01);
                let hcc01 = pdm(8, 6) * pdl(20, 2);
                let zcc01 = pdm(7, 6) * pdl(19, 2);
                let rc01 = pdm(4, 6) * pdl(21, 2);
                d[6] *= ccor(z, rc01, hcc01, zcc01);
            }
            // N
            let g14 = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(8));
            let db14 = pdm(1, 7) * g14.exp() * pd(1, 8);
            d[7] = self.densu(z, db14, tinf, tlb, 14.0, ALPHA[7], &mut t[1], ptm(6), s, &zn1);
            if z <= ALTL[7] {
                let zh14 = pdm(3, 7);
                let b14 = self.densu(zh14, db14, tinf, tlb, 14.0 - xmm, ALPHA[7] - 1.0, &mut t[1], ptm(6), s, &zn1);
                let dm14 = self.densu(z, b14, tinf, tlb, xmm, 0.0, &mut t[1], ptm(6), s, &zn1);
                d[7] = dnet(d[7], dm14, zhm28, xmm, 14.0);
                let rl = (b28 * pdm(2, 7) * pdl(3, 1).abs() / b14).ln();
                let hc14 = pdm(6, 7) * pdl(2, 1);
                let zc14 = pdm(5, 7) * pdl(1, 1);
                d[7] *= ccor(z, rl, hc14, zc14);
                let hcc14 = pdm(8, 7) * pdl(5, 1);
                let zcc14 = pdm(7, 7) * pdl(4, 1);
                let rc14 = pdm(4, 7) * pdl(6, 1);
                d[7] *= ccor(z, rc14, hcc14, zcc14);
            }
            // 異常氧
            let g16h = SW * self.globe7(yrd, sec, glat, glong, stl, f107a, f107, ap, pd_col(9));
            let db16h = pdm(1, 8) * g16h.exp() * pd(1, 9);
            let tho = pdm(10, 8) * pdl(7, 1);
            let dd = self.densu(z, db16h, tho, tho, 16.0, ALPHA[8], &mut t2, ptm(6), s, &zn1);
            let zsht = pdm(6, 8);
            let zmho = pdm(5, 8);
            let zsho = self.scalh(zmho, 16.0, tho);
            d[8] = dd * (-zsht / zsho * ((-(z - zmho) / zsht).exp() - 1.0)).exp();
            d[5] = 1.66e-24 * (4.0 * d[0] + 16.0 * d[1] + 28.0 * d[2] + 32.0 * d[3] + 40.0 * d[4] + d[6] + 14.0 * d[7]);
        }
        let _ = t2;
        for v in d.iter_mut() {
            *v *= 1.0e6;
        }
        d[5] /= 1000.0;
        (d, t)
    }

    /// GTD7（全高度），mass=48；回傳 (D[9], T[2])
    #[allow(clippy::too_many_arguments)]
    fn gtd7(&mut self, iyd: i64, sec: f64, alt: f64, glat: f64, glong: f64, stl: f64, f107a: f64, f107: f64, ap: &[f64; 7]) -> ([f64; 9], [f64; 2]) {
        const MASS: i32 = 48;
        let zn3 = [32.5, 20.0, 15.0, 10.0, 0.0];
        let zn2 = [72.5, 55.0, 45.0, 32.5];
        let zmix = 62.5;
        self.glatf(glat);
        let xmm = pdm(5, 3);
        let altt = alt.max(zn2[0]);
        let mss = if alt < zmix { 28 } else { MASS };
        let (ds, ts) = self.gts7(iyd, sec, altt, glat, glong, stl, f107a, f107, ap, mss);
        let dm28m = self.dm28 * 1.0e6;
        let mut t = ts;
        if alt >= zn2[0] {
            return (ds, t);
        }
        let mut d = [0.0f64; 9];
        self.tgn2[0] = self.tgn1[1];
        self.tn2[0] = self.tn1[4];
        self.tn2[1] = pma(1, 1) * pavgm(1) / (1.0 - SW * self.glob7s(pma_col(1)));
        self.tn2[2] = pma(1, 2) * pavgm(2) / (1.0 - SW * self.glob7s(pma_col(2)));
        self.tn2[3] = pma(1, 3) * pavgm(3) / (1.0 - SW * SW * self.glob7s(pma_col(3)));
        self.tgn2[1] = pavgm(9) * pma(1, 10) * (1.0 + SW * SW * self.glob7s(pma_col(10))) * self.tn2[3] * self.tn2[3]
            / (pma(1, 3) * pavgm(3)).powi(2);
        self.tn3[0] = self.tn2[3];
        if alt < zn3[0] {
            self.tgn3[0] = self.tgn2[1];
            self.tn3[1] = pma(1, 4) * pavgm(4) / (1.0 - SW * self.glob7s(pma_col(4)));
            self.tn3[2] = pma(1, 5) * pavgm(5) / (1.0 - SW * self.glob7s(pma_col(5)));
            self.tn3[3] = pma(1, 6) * pavgm(6) / (1.0 - SW * self.glob7s(pma_col(6)));
            self.tn3[4] = pma(1, 7) * pavgm(7) / (1.0 - SW * self.glob7s(pma_col(7)));
            self.tgn3[1] = pma(1, 8) * pavgm(8) * (1.0 + SW * self.glob7s(pma_col(8))) * self.tn3[4] * self.tn3[4]
                / (pma(1, 7) * pavgm(7)).powi(2);
        }
        let dmc = if alt > zmix { 1.0 - (zn2[0] - alt) / (zn2[0] - zmix) } else { 0.0 };
        let dz28 = ds[2];
        let mut tz = 0.0;
        let dmr = ds[2] / dm28m - 1.0;
        d[2] = self.densm(alt, dm28m, xmm, &mut tz, &zn3, &zn2);
        d[2] *= 1.0 + dmr * dmc;
        let dmr = ds[0] / (dz28 * pdm(2, 1)) - 1.0;
        d[0] = d[2] * pdm(2, 1) * (1.0 + dmr * dmc);
        let dmr = ds[3] / (dz28 * pdm(2, 4)) - 1.0;
        d[3] = d[2] * pdm(2, 4) * (1.0 + dmr * dmc);
        let dmr = ds[4] / (dz28 * pdm(2, 5)) - 1.0;
        d[4] = d[2] * pdm(2, 5) * (1.0 + dmr * dmc);
        d[5] = 1.66e-24 * (4.0 * d[0] + 16.0 * d[1] + 28.0 * d[2] + 32.0 * d[3] + 40.0 * d[4] + d[6] + 14.0 * d[7]) / 1000.0;
        t[1] = tz;
        (d, t)
    }
}

fn spline(x: &[f64], y: &[f64], yp1: f64, ypn: f64, y2: &mut [f64]) {
    let n = x.len();
    let mut u = [0.0f64; 10];
    if yp1 > 0.99e30 {
        y2[0] = 0.0;
        u[0] = 0.0;
    } else {
        y2[0] = -0.5;
        u[0] = (3.0 / (x[1] - x[0])) * ((y[1] - y[0]) / (x[1] - x[0]) - yp1);
    }
    for i in 1..n - 1 {
        let sig = (x[i] - x[i - 1]) / (x[i + 1] - x[i - 1]);
        let p = sig * y2[i - 1] + 2.0;
        y2[i] = (sig - 1.0) / p;
        u[i] = (6.0 * ((y[i + 1] - y[i]) / (x[i + 1] - x[i]) - (y[i] - y[i - 1]) / (x[i] - x[i - 1])) / (x[i + 1] - x[i - 1]) - sig * u[i - 1]) / p;
    }
    let (qn, un) = if ypn > 0.99e30 {
        (0.0, 0.0)
    } else {
        (0.5, (3.0 / (x[n - 1] - x[n - 2])) * (ypn - (y[n - 1] - y[n - 2]) / (x[n - 1] - x[n - 2])))
    };
    y2[n - 1] = (un - qn * u[n - 2]) / (qn * y2[n - 2] + 1.0);
    for k in (0..n - 1).rev() {
        y2[k] = y2[k] * y2[k + 1] + u[k];
    }
}

fn splint(xa: &[f64], ya: &[f64], y2a: &[f64], x: f64) -> f64 {
    let n = xa.len();
    let mut klo = 0usize;
    let mut khi = n - 1;
    while khi - klo > 1 {
        let k = (khi + klo) / 2;
        if xa[k] > x {
            khi = k;
        } else {
            klo = k;
        }
    }
    let h = xa[khi] - xa[klo];
    let a = (xa[khi] - x) / h;
    let b = (x - xa[klo]) / h;
    a * ya[klo] + b * ya[khi] + ((a * a * a - a) * y2a[klo] + (b * b * b - b) * y2a[khi]) * h * h / 6.0
}

fn splini(xa: &[f64], ya: &[f64], y2a: &[f64], x: f64) -> f64 {
    let n = xa.len();
    let mut yi = 0.0;
    let mut klo = 0usize;
    let mut khi = 1usize;
    while x > xa[klo] && khi < n {
        let mut xx = x;
        if khi < n - 1 {
            xx = x.min(xa[khi]);
        }
        let h = xa[khi] - xa[klo];
        let a = (xa[khi] - xx) / h;
        let b = (xx - xa[klo]) / h;
        let a2 = a * a;
        let b2 = b * b;
        yi += ((1.0 - a2) * ya[klo] / 2.0
            + b2 * ya[khi] / 2.0
            + ((-(1.0 + a2 * a2) / 4.0 + a2 / 2.0) * y2a[klo] + (b2 * b2 / 4.0 - b2 / 2.0) * y2a[khi]) * h * h / 6.0)
            * h;
        klo += 1;
        khi += 1;
    }
    yi
}

fn dnet(mut dd: f64, dm: f64, zhm: f64, xmm: f64, xm: f64) -> f64 {
    let a = zhm / (xmm - xm);
    if !(dm > 0.0 && dd > 0.0) {
        if dd == 0.0 && dm == 0.0 {
            dd = 1.0;
        }
        if dm == 0.0 {
            return dd;
        }
        if dd == 0.0 {
            return dm;
        }
    }
    let ylog = a * (dm / dd).ln();
    if ylog < -10.0 {
        return dd;
    }
    if ylog > 10.0 {
        return dm;
    }
    dd * (1.0 + ylog.exp()).powf(1.0 / a)
}

fn ccor(alt: f64, r: f64, h1: f64, zh: f64) -> f64 {
    let e = (alt - zh) / h1;
    let c = if e > 70.0 {
        0.0
    } else if e < -70.0 {
        r
    } else {
        r / (1.0 + e.exp())
    };
    c.exp()
}

fn ccor2(alt: f64, r: f64, h1: f64, zh: f64, h2: f64) -> f64 {
    let e1 = (alt - zh) / h1;
    let e2 = (alt - zh) / h2;
    let c = if e1 > 70.0 || e2 > 70.0 {
        0.0
    } else if e1 < -70.0 && e2 < -70.0 {
        r
    } else {
        r / (1.0 + 0.5 * (e1.exp() + e2.exp()))
    };
    c.exp()
}

#[inline]
fn f32r(x: f64) -> f64 {
    x as f32 as f64
}

/// 總質量密度 [kg/m^3]（等同 `pymsis.calculate(..., version=0)[..., MASS_DENSITY]`，
/// 即 GTD7D 之 D(6)：含異常氧之「有效總質量密度」）。
///
/// - `doy`：年內日序 1–366（整數部分）；`utsec`：當日 UT 秒（pymsis 取整秒）
/// - `lon_deg`：經度（負值自動 +360），`lat_deg`：緯度，`alt_km`：高度
/// - `f107`：前一日 F10.7，`f107a`：81 日平均，`ap`：每日 Ap
#[allow(clippy::too_many_arguments)]
pub fn mass_density(doy: f64, utsec: f64, lon_deg: f64, lat_deg: f64, alt_km: f64, f107: f64, f107a: f64, ap: f64) -> f64 {
    let (doy, utsec) = (f32r(doy), f32r(utsec));
    let (mut lon, lat, alt) = (f32r(lon_deg), f32r(lat_deg), f32r(alt_km));
    let (f107, f107a, ap) = (f32r(f107), f32r(f107a), f32r(ap));
    if lon < 0.0 {
        lon += 360.0;
    }
    let iyd = 10000 + doy.floor() as i64;
    let stl = utsec / 3600.0 + lon / 15.0;
    let aps = [ap, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0];
    let mut ctx = Ctx::default();
    let (d, _t) = ctx.gtd7(iyd, utsec, alt, lat, lon, stl, f107a, f107, &aps);
    // GTD7D：D(6) 加入異常氧
    1.66e-24 * (4.0 * d[0] + 16.0 * d[1] + 28.0 * d[2] + 32.0 * d[3] + 40.0 * d[4] + d[6] + 14.0 * d[7] + 16.0 * d[8]) / 1000.0
}

#[cfg(test)]
mod tests {
    /// pymsis 0.13 `calculate(..., version=0)` 參考值（doy, utsec, lon, lat, alt, f107, f107a, ap, rho）
    const REF: [(f64, f64, f64, f64, f64, f64, f64, f64, f64); 24] = [
        (173.0, 61678.0, 333.2503960160051, -63.3395889359052, 65.0, 240.7569004847039, 116.77471780157282, 63.49896734588635, 9.272653551306576e-05),
        (187.0, 70406.0, 266.95940066303854, -16.162553726289293, 70.0, 168.9268637811507, 74.13386698646025, 113.026966301221, 8.181470184354112e-05),
        (306.0, 71531.0, -1.9448730904902312, 51.34030921025597, 72.0, 124.5750692724961, 138.02468342209772, 20.106254587074712, 4.638003883883357e-05),
        (197.0, 36487.0, 37.681012681449786, -52.78496715964537, 75.0, 117.21640127953292, 182.55470089450787, 42.06131369790599, 2.6790476113092154e-05),
        (182.0, 74255.0, 349.59808789266884, 82.17498047215405, 80.0, 200.46218933923606, 151.18402833211513, 41.533680606805625, 3.473820106592029e-05),
        (178.0, 8182.0, -93.24791526143149, 83.6467235524716, 90.0, 162.89234539861818, 87.37984187061555, 93.52346333062506, 3.9945780372363515e-06),
        (167.0, 25360.0, 151.02178256864184, 74.27899145278067, 100.0, 77.12671779955652, 149.28838948900324, 68.90038243281056, 3.0085035973570484e-07),
        (284.0, 42278.0, -146.33122725906716, 25.156414106808743, 110.0, 223.47391092651822, 158.9411527156426, 39.014617160583484, 8.850587818187705e-08),
        (126.0, 68472.0, 95.12777602161506, 1.938221435042878, 120.0, 205.54543738639202, 92.18830536774348, 122.94400786789154, 2.0672803913157622e-08),
        (307.0, 48103.0, 188.97492924175884, 51.103255596754586, 150.0, 104.49092662362435, 190.3546241701795, 28.698588908580042, 2.3153650108298507e-09),
        (176.0, 1161.0, 281.8225661150179, 64.30846231962498, 200.0, 227.77667735498449, 140.78645790381853, 41.10725829205774, 3.230765377448819e-10),
        (30.0, 66243.0, -176.1704125542902, 25.938319412340714, 250.0, 199.58368903156475, 195.33538247504111, 42.28167410468132, 1.1637344560222473e-10),
        (172.0, 48564.0, 165.23894523595743, 54.29976029981172, 300.0, 243.46075711209477, 92.57872456317662, 72.33185822990048, 2.1497865987374354e-11),
        (79.0, 47920.0, 303.1465655859337, -13.756390563712163, 350.0, 176.11037117512865, 73.67360162400448, 101.01898307294084, 9.149118962437086e-12),
        (166.0, 31428.0, 266.48567796062935, 68.62260747437053, 400.0, 188.8639684936942, 106.83284008647664, 115.27754983443815, 4.052403811821703e-12),
        (336.0, 40378.0, -65.69563899194432, 58.96692057027409, 450.0, 81.28922606273828, 193.82317200903339, 24.676089971115196, 1.2254833649597008e-12),
        (54.0, 15713.0, -8.96139005923928, 34.05799227943795, 500.0, 102.14293807138695, 129.43842433254798, 0.8736892661971418, 1.7090528211388678e-13),
        (137.0, 80235.0, -38.25285511494519, -14.028391067245963, 600.0, 89.0658226073184, 164.97399190548367, 57.06364048297985, 1.7122707331868048e-13),
        (9.0, 81285.0, 173.08764597693295, -12.241638717621699, 700.0, 226.11769101559585, 164.82026762502505, 121.54115281594486, 2.288202179817622e-13),
        (265.0, 63269.0, 4.569150927661026, 7.7731335609851016, 800.0, 105.33343932065561, 219.42117851779417, 36.48231964594907, 4.294453315634335e-14),
        (54.0, 48966.0, -140.47736090887838, -43.111044818580886, 900.0, 207.3631358579296, 174.6840356024622, 19.300981847575414, 8.095752868542312e-15),
        (94.0, 65372.0, 23.168790771170883, -14.0759917580916, 1000.0, 189.69716434515294, 138.38934445656233, 87.97774902382972, 7.373551401889614e-15),
        (167.0, 10625.0, 212.29574956868004, -24.02870709547651, 62.0, 150.71133568200716, 125.154935453501, 16.46019960100451, 0.00023833052546251565),
        (307.0, 41893.0, -70.24956619280584, -38.482444967944666, 30.0, 126.5441012084144, 116.95717882299066, 86.5049574379428, 0.018223153427243233),
    ];

    #[test]
    fn matches_pymsis_version0() {
        let mut worst = 0.0f64;
        for r in REF {
            let rho = super::mass_density(r.0, r.1, r.2, r.3, r.4, r.5, r.6, r.7);
            let rel = (rho / r.8 - 1.0).abs();
            worst = worst.max(rel);
            assert!(rel < 1e-4, "alt {} km: rust {rho:e} vs pymsis {:e}（相對差 {rel:e}）", r.4, r.8);
        }
        eprintln!("NRLMSISE-00 vs pymsis 最大相對差 {worst:e}");
    }
}
