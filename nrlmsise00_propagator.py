#!/usr/bin/env python3
"""nrlmsise00_propagator.py — 完整力模式（NRLMSISE-00 大氣密度 + J2 重力 + 數值積分）
軌道傳播架構，供與 SGP4 之簡化解析阻力模型直接對照。

回應審查委員意見：TLE-MEME 殘差跟 F10.7 之相關性檢驗（見案例二十五）僅用 F10.7
作為間接代理指標，未直接量化「SGP4 簡化力模式」相對「完整大氣密度模式」在解釋
殘差上的差異。本模組提供該項直接比較所需之數值傳播器。

設計：
  - 重力：僅 J2（與 SGP4 平均根數理論同一階次，避免因重力模式不同而混淆比較，
    見論文一 2.4 節對 SGP4 平均根數理論之討論）。
  - 阻力：NRLMSISE-00（`pymsis`，version=0）即時大氣密度，取代 SGP4 之靜態 B*
    解析阻力項——此即與 SGP4 之核心方法論差異所在。
  - 初始狀態：直接取 SGP4 在 TLE 曆元本身之狀態向量（與 SGP4 傳播共用同一起點，
    確保比較公平，差異只來自曆元之後的力模式選擇，非初始條件差異）。
  - 彈道係數（BC = Cd·A/m）：**不採用 B* 之教科書換算公式**——B* 本身即為 TLE
    擬合過程中吸收多種誤差來源之代理參數（見論文一 2.2 節之循環論證討論），
    直接換算恐引入未經驗證之比例誤差。改採**本地校準**：以曆元後一段短窗口
    （預設 1 天）之真實觀測（優先用 MEME，否則退回 SGP4 隱含衰減）反推 BC，
    再用校準所得之 BC 搭配隨時間變化之真實大氣密度，向前傳播至評估窗口——
    此設計專門用於檢驗「若阻力係數固定不變、但大氣密度確實隨太陽活動變化，
    數值傳播能否比 SGP4 更貼近真值」，正是委員提出之問題核心。

用法範例見 compare_sgp4_vs_nrlmsise00.py。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar
from skyfield.api import EarthSatellite, load as skyfield_load
from skyfield.positionlib import Geocentric
from skyfield.constants import AU_KM
from skyfield.api import wgs84

import pymsis

MU_KM3_S2 = 398600.4418      # km^3/s^2
R_E_KM = 6378.137            # km (WGS84 equatorial)
J2 = 1.08262668e-3
OMEGA_EARTH = 7.292115e-5    # rad/s，地球自轉角速度（用於相對大氣風速）
MSIS_VERSION = 2.1           # 2026-09-19：改用 NRLMSIS 2.1（pymsis 預設、較新版本，
                              # 較 NRLMSISE-00（version=0，委員原始指定）理論上更準；
                              # 用於檢驗 SGP4 領先是否為 NRLMSISE-00（2002年版）本身
                              # 精度較舊所致。若仍是 SGP4 領先，可排除「換更新版大氣
                              # 模式即可解決」此一解釋。


# ── 座標轉換 ──────────────────────────────────────────────────────────────────

def eci_to_geodetic(t_skyfield, r_km: np.ndarray) -> tuple[float, float, float]:
    """ECI（視為 GCRS，忽略 TEME/GCRS 之角秒級極移差異——對大氣密度查詢而言可忽略，
    密度為 lat/lon/alt 之平滑函數）位置轉大地座標 (lat_deg, lon_deg, alt_km)。"""
    pos = Geocentric(np.asarray(r_km) / AU_KM, t=t_skyfield)
    gp = wgs84.geographic_position_of(pos)
    return gp.latitude.degrees, gp.longitude.degrees, gp.elevation.km


def atmos_density_kgm3(t_skyfield, r_km: np.ndarray) -> float:
    """呼叫 pymsis（NRLMSISE-00）取得該時空點之大氣總質量密度（kg/m^3）。
    未指定 F10.7/Ap 時，pymsis 自動抓取該日期之真實歷史太陽/地磁活動資料。
    僅供單點查驗用；數值積分請改用 `_DensityInterpolator`（批次+內插，見下），
    否則逐步呼叫 pymsis 的開銷會讓積分慢到不可用。"""
    lat, lon, alt = eci_to_geodetic(t_skyfield, r_km)
    if alt < 0 or alt > 1000:  # 超出 NRLMSISE-00 合理適用範圍，回傳極小值避免積分爆走
        return 0.0
    out = pymsis.calculate(
        [t_skyfield.utc_datetime()], [lon], [lat], [alt], version=MSIS_VERSION,
    )
    rho = float(out[0, 0])
    return rho if np.isfinite(rho) and rho > 0 else 0.0


class _DensityInterpolator:
    """效能優化：先用 SGP4 隱含軌跡（與真正的 Cowell 積分路徑差異極小，見下方
    說明）批次取樣 lat/lon/alt，一次性呼叫 pymsis（向量化 fly-through 模式）取得
    整段時間的密度序列，再對時間做線性內插，取代積分過程中逐步呼叫 pymsis。

    合理性：密度為時間/位置之平滑函數，SGP4 與真實（阻力/J2 driven）路徑在數天
    尺度內的位置差異（本研究之殘差量級：數十至數百公尺）相對於密度的空間變化
    尺度（公里至數百公里）可忽略，用 SGP4 路徑取樣密度不會實質影響數值傳播結果，
    卻能把 pymsis 呼叫次數從數千次降為 1 次。
    """

    def __init__(self, line1: str, line2: str, ts, t0_dt, t_end_sec: float, sample_step_s: float = 300.0):
        sat = EarthSatellite(line1, line2, ts=ts)
        n = max(2, int(t_end_sec / sample_step_s) + 2)
        t_secs = np.linspace(0, t_end_sec, n)
        t_dts = [t0_dt + pd.Timedelta(seconds=float(s)) for s in t_secs]
        t_sf = ts.from_datetimes(t_dts)
        geo = sat.at(t_sf)
        r_km = geo.position.km  # shape (3, n)

        lats, lons, alts = [], [], []
        for i in range(n):
            lat, lon, alt = eci_to_geodetic(t_sf[i], r_km[:, i])
            lats.append(lat); lons.append(lon); alts.append(max(alt, 0.0))

        out = pymsis.calculate(t_dts, lons, lats, alts, version=MSIS_VERSION)
        rho = np.asarray(out[:, 0], dtype=float)
        rho = np.where(np.isfinite(rho) & (rho > 0), rho, 1e-16)

        self.t_secs = t_secs
        self.log_rho = np.log(rho)  # 對數空間內插，密度隨高度指數變化，線性內插對數更準確

    def __call__(self, t_sec: float) -> float:
        log_rho = np.interp(t_sec, self.t_secs, self.log_rho)
        return float(np.exp(log_rho))


# ── 動力學 RHS（J2–J5 重力 + NRLMSISE-00 阻力）─────────────────────────────────
# 2026-09-19 補強：原僅用 J2，與 SGP4 內建之 J2–J5 多階項相比精度天生較弱，
# 首輪比較（compare_sgp4_vs_nrlmsise00.py）誤差隨外推天數持續擴大，懷疑係
# 重力模式落差（而非阻力模式）所致，予以補強至 J2–J5，隔離出「僅阻力模式」
# 之乾淨比較。

J3 = -2.53265648e-6
J4 = -1.61962159e-6
J5 = -2.27296082e-7


def _legendre_p(n: int, x) -> np.ndarray:
    """未正規化 Legendre 多項式 P_n(x)，n=0..5（標準公式，供勢能法計算重力用）。"""
    if n == 0:
        return np.ones_like(x)
    if n == 1:
        return x
    if n == 2:
        return 0.5 * (3 * x**2 - 1)
    if n == 3:
        return 0.5 * (5 * x**3 - 3 * x)
    if n == 4:
        return (1.0 / 8.0) * (35 * x**4 - 30 * x**2 + 3)
    if n == 5:
        return (1.0 / 8.0) * (63 * x**5 - 70 * x**3 + 15 * x)
    raise ValueError(f"未支援 n={n}")


def _geopotential_u(r_km: np.ndarray) -> float:
    """帶 J2–J5 之地球重力位能 U(x,y,z)（不含中心項符號慣例已內含負號，
    使得 a = -grad(U) 直接得到含中心引力之總加速度——見下方 _zonal_accel）。
    U = -mu/r * [1 - sum_{n=2}^{5} Jn*(Re/r)^n * Pn(sin(phi))]，sin(phi)=z/r。"""
    r = np.linalg.norm(r_km)
    sinphi = r_km[2] / r
    Jn = {2: J2, 3: J3, 4: J4, 5: J5}
    s = 1.0
    for n, J in Jn.items():
        s -= J * (R_E_KM / r) ** n * _legendre_p(n, sinphi)
    return -MU_KM3_S2 / r * s


def _zonal_accel(r_km: np.ndarray) -> np.ndarray:
    """a = -grad(U)，以中心差分數值微分（避免手動推導 J3–J5 之解析 Cartesian
    公式時引入係數錯誤——勢能法本身只需標準 Legendre 多項式，風險低很多）。
    步長 h=1e-4 km(=0.1 m)：重力位能在軌道尺度（~千公里）下極其平滑，
    此步長遠低於數值穩定性邊界，梯度精度可達 1e-9 相對誤差量級。
    自我檢驗：令 J3=J4=J5=0 時應與原本已驗證過之純 J2 解析公式一致
    （見 compare_sgp4_vs_nrlmsise00.py 執行前之單元測試）。"""
    h = 1e-4
    grad = np.zeros(3)
    for i in range(3):
        rp = r_km.copy(); rp[i] += h
        rm = r_km.copy(); rm[i] -= h
        grad[i] = (_geopotential_u(rp) - _geopotential_u(rm)) / (2 * h)
    return -grad


def _drag_accel_from_rho(rho_kgm3: float, r_km: np.ndarray, v_km_s: np.ndarray, bc_m2_per_kg: float) -> np.ndarray:
    """a_drag = -0.5 * BC * rho * v_rel * |v_rel|（BC = Cd*A/m，km^2/kg 制）。
    v_rel = v - omega_earth × r（相對共轉大氣之速度）。"""
    if rho_kgm3 <= 0:
        return np.zeros(3)
    omega_vec = np.array([0.0, 0.0, OMEGA_EARTH])
    v_atm = np.cross(omega_vec, r_km)               # km/s
    v_rel = v_km_s - v_atm                            # km/s
    v_rel_norm = np.linalg.norm(v_rel)
    # rho: kg/m^3 -> kg/km^3 (x1e9)；BC: km^2/kg；v: km/s -> a: km/s^2
    rho_km3 = rho_kgm3 * 1e9
    return -0.5 * bc_m2_per_kg * rho_km3 * v_rel_norm * v_rel


def _rhs(t_sec: float, state: np.ndarray, density_fn, bc_m2_per_kg: float) -> np.ndarray:
    r, v = state[:3], state[3:]
    rho = density_fn(t_sec)
    a = _zonal_accel(r) + _drag_accel_from_rho(rho, r, v, bc_m2_per_kg)
    return np.concatenate([v, a])


# ── SGP4 初始狀態（起點與 SGP4 完全一致，公平比較）────────────────────────────

def _sgp4_state_at(line1: str, line2: str, t_utc, ts) -> tuple[np.ndarray, np.ndarray]:
    sat = EarthSatellite(line1, line2, ts=ts)
    t_sf = ts.from_datetime(t_utc.to_pydatetime() if hasattr(t_utc, "to_pydatetime") else t_utc)
    geo = sat.at(t_sf)
    return geo.position.km, geo.velocity.km_per_s


def sgp4_sma_km(line1: str, line2: str, t_utc, ts) -> float:
    r, v = _sgp4_state_at(line1, line2, t_utc, ts)
    r_n, v_n = np.linalg.norm(r), np.linalg.norm(v)
    eps = v_n**2 / 2.0 - MU_KM3_S2 / r_n
    return -MU_KM3_S2 / (2.0 * eps)


# ── 校準 BC ───────────────────────────────────────────────────────────────────

def calibrate_bc(
    line1: str, line2: str, ts,
    target_sma_km_at_t1: float, t1_sec: float,
    bc_bounds: tuple[float, float] = (1e-9, 1e-7),
    # 物理合理範圍：Cd*A/m ≈ 0.001–0.1 m^2/kg（一般 LEO 衛星，含 Starlink 級）
    # = 1e-9–1e-7 km^2/kg。原預設 (1e-5, 5e-3) 誤植為 10–5000 m^2/kg，
    # 比物理合理值大 200 倍以上，會導致校準卡在邊界、阻力嚴重失真（已於
    # 煙霧測試中發現並修正，見 compare_sgp4_vs_nrlmsise00.py 之驗證記錄）。
) -> float:
    """在 [0, t1_sec] 短窗口內，找出使數值傳播終點 sma 最貼近 target_sma_km_at_t1
    （建議傳入 MEME 或 SGP4 於 t1 之真實 sma）之 BC。單一標量最佳化，快速。"""
    tle_epoch = _tle_epoch_dt(line1, line2)
    r0, v0 = _sgp4_state_at(line1, line2, tle_epoch, ts)
    state0 = np.concatenate([r0, v0])
    density_fn = _DensityInterpolator(line1, line2, ts, tle_epoch, t1_sec)

    def _residual(bc: float) -> float:
        sol = solve_ivp(_rhs, [0, t1_sec], state0, args=(density_fn, bc),
                        method="RK45", max_step=300.0, rtol=1e-9, atol=1e-6)
        r_end = sol.y[:3, -1]
        v_end = sol.y[3:, -1]
        r_n, v_n = np.linalg.norm(r_end), np.linalg.norm(v_end)
        eps = v_n**2 / 2.0 - MU_KM3_S2 / r_n
        a_end = -MU_KM3_S2 / (2.0 * eps)
        return (a_end - target_sma_km_at_t1) ** 2

    res = minimize_scalar(_residual, bounds=bc_bounds, method="bounded",
                          options={"xatol": 1e-6})
    return float(res.x)


def calibrate_bc_multipoint(
    line1: str, line2: str, ts,
    calib_times_utc: list, target_sma_km: list,
    bc_bounds: tuple[float, float] = (1e-9, 1e-7),
) -> float:
    """改進版校準（2026-09-19 新增）：單點校準（`calibrate_bc`）容易被 MEME
    在校準時刻的局部真實擾動（噪音）帶偏，校準出偏誤的 BC，之後每天複製此
    偏誤——此為單點法之已知缺陷（見 compare_sgp4_vs_nrlmsise00.py 首輪結果，
    Cowell 誤差隨外推天數持續擴大遠快於 SGP4，疑似此因）。改用校準窗口內
    **多筆** MEME 觀測做最小平方擬合，統計上更貼近 SGP4 之 B* 產生方式
    （官方軌道判定亦是對多筆觀測做最小平方擬合，而非單點匹配）。

    效率：對每個候選 BC 僅呼叫一次 solve_ivp（以 t_eval 一次取得所有校準點之
    狀態），而非逐點個別積分。
    """
    tle_epoch = _tle_epoch_dt(line1, line2)
    r0, v0 = _sgp4_state_at(line1, line2, tle_epoch, ts)
    state0 = np.concatenate([r0, v0])

    calib_secs = np.array([
        (pd.Timestamp(t).tz_convert("UTC") if pd.Timestamp(t).tzinfo else pd.Timestamp(t).tz_localize("UTC"))
        .to_pydatetime().timestamp() - pd.Timestamp(tle_epoch).timestamp()
        for t in calib_times_utc
    ])
    order = np.argsort(calib_secs)
    calib_secs = calib_secs[order]
    targets = np.asarray(target_sma_km)[order]
    valid = calib_secs > 0
    calib_secs, targets = calib_secs[valid], targets[valid]
    if len(calib_secs) < 2:
        raise ValueError("多點校準至少需要 2 個有效校準點")

    density_fn = _DensityInterpolator(line1, line2, ts, tle_epoch, float(calib_secs[-1]))

    def _residual(bc: float) -> float:
        sol = solve_ivp(_rhs, [0, calib_secs[-1]], state0, args=(density_fn, bc),
                        method="RK45", t_eval=calib_secs, max_step=300.0, rtol=1e-9, atol=1e-6)
        if sol.y.shape[1] != len(calib_secs):
            return 1e12
        r_n = np.linalg.norm(sol.y[:3, :], axis=0)
        v_n = np.linalg.norm(sol.y[3:, :], axis=0)
        eps = v_n**2 / 2.0 - MU_KM3_S2 / r_n
        a_pred = -MU_KM3_S2 / (2.0 * eps)
        return float(np.sum((a_pred - targets) ** 2))

    res = minimize_scalar(_residual, bounds=bc_bounds, method="bounded",
                          options={"xatol": 1e-6})
    return float(res.x)


def _tle_epoch_dt(line1: str, line2: str):
    sat = EarthSatellite(line1, line2, ts=skyfield_load.timescale())
    return sat.epoch.utc_datetime()


# ── 主要傳播介面 ───────────────────────────────────────────────────────────────

def propagate_cowell(
    line1: str, line2: str, target_times_utc: list, bc_m2_per_kg: float, ts=None,
) -> pd.DataFrame:
    """從 TLE 曆元（初始狀態與 SGP4 一致）以 J2+NRLMSISE-00 數值積分，傳播至每個
    target_times_utc，回傳含 a_km（半長軸）之 DataFrame，供與 MEME/SGP4 比對。"""
    ts = ts or skyfield_load.timescale()
    tle_epoch = _tle_epoch_dt(line1, line2)
    r0, v0 = _sgp4_state_at(line1, line2, tle_epoch, ts)
    state0 = np.concatenate([r0, v0])

    t_targets_sec = sorted(
        (pd.Timestamp(t).tz_localize("UTC") if pd.Timestamp(t).tzinfo is None
         else pd.Timestamp(t)).tz_convert("UTC").to_pydatetime().timestamp()
        - pd.Timestamp(tle_epoch).timestamp()
        for t in target_times_utc
    )
    t_targets_sec = [t for t in t_targets_sec if t > 0]
    if not t_targets_sec:
        return pd.DataFrame()

    density_fn = _DensityInterpolator(line1, line2, ts, tle_epoch, t_targets_sec[-1])
    sol = solve_ivp(_rhs, [0, t_targets_sec[-1]], state0, args=(density_fn, bc_m2_per_kg),
                    method="RK45", t_eval=t_targets_sec, max_step=300.0, rtol=1e-9, atol=1e-6)

    rows = []
    for i, t_sec in enumerate(sol.t):
        r, v = sol.y[:3, i], sol.y[3:, i]
        r_n, v_n = np.linalg.norm(r), np.linalg.norm(v)
        eps = v_n**2 / 2.0 - MU_KM3_S2 / r_n
        a_km = -MU_KM3_S2 / (2.0 * eps)
        rows.append(dict(t=pd.Timestamp(tle_epoch) + pd.Timedelta(seconds=t_sec),
                         a_cowell_km=a_km, r_x=r[0], r_y=r[1], r_z=r[2],
                         v_x=v[0], v_y=v[1], v_z=v[2]))
    return pd.DataFrame(rows)
