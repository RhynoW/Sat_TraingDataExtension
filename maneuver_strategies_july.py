#!/usr/bin/env python3
"""
maneuver_strategies_july.py
===========================
maneuver_app_july.py 專用的緊湊 P1–P6 機動偵測策略模組（乾淨重寫）。

相對舊版的兩項改動（依需求 3、4）：
  P2  高度自適應 Δa 閾值：三階段階梯 → 近似「拋物線左側」平滑曲線。
  P5  F10.7 太陽通量自適應倍率：三階段 → 同型拋物線曲線。

每個策略對「連續 TLE 轉換序列」回傳逐轉換布林旗標，供個別 + 合併顯示。
偵測型（P2/P4/P6）產生旗標；抑制型（P1/P3）移除誤報；P5 調整 P2 閾值。
2026-09-21：抑制型不得擋掉「本身已超過 P2 高度門檻」的步階（避免把向下的降軌機動當成大氣衰減）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

R_E = 6378.137
MU  = 398_600.4418
J2  = 1.082_63e-3

# 非 da 指標的固定閾值（沿用專案）
THR_DI    = 0.02     # deg
THR_DE    = 0.001
THR_DRAAN = 0.10     # deg（J2 修正後 RAAN 殘差）


# ── 軌道分類（緊湊版）────────────────────────────────────────────────────────

def classify_orbit(a_km: float, e: float = 0.0, i_deg: float = 0.0) -> str:
    """回傳 LEO / MEO / GEO / GEO+ / HEO。"""
    GEO_LO, GEO_HI = 41_600.0, 42_650.0
    rp = a_km * (1 - e)
    ra = a_km * (1 + e)
    if e >= 0.25 and (ra - rp) > 20_000:
        return "HEO"
    if a_km < 8_000:
        return "LEO"
    if a_km < GEO_LO:
        return "MEO"
    if a_km <= GEO_HI:
        return "GEO"
    return "GEO+"


# ── 拋物線左側閾值曲線（需求 3、4）───────────────────────────────────────────

@dataclass
class ParabolaParams:
    """y(x) = floor + k·(x − vertex)²，k 由參考點 (ref_x, ref_y) 定；
    只取參考點所在那一側（拋物線的『左側線型』），另一側夾為 floor。"""
    vertex: float
    floor:  float
    ref_x:  float
    ref_y:  float

    def k(self) -> float:
        d = (self.ref_x - self.vertex)
        return (self.ref_y - self.floor) / (d * d) if abs(d) > 1e-9 else 0.0

    def __call__(self, x):
        x = np.asarray(x, float)
        y = self.floor + self.k() * (x - self.vertex) ** 2
        # 只保留參考點那一側；另一側平為 floor（左側線型）
        if self.ref_x < self.vertex:      # 參考點在左 → 只在 x<vertex 有效
            y = np.where(x < self.vertex, y, self.floor)
        else:                             # 參考點在右
            y = np.where(x > self.vertex, y, self.floor)
        return np.maximum(y, self.floor)


# 預設：P2 高度(km) → Δa 閾值(km)；低軌閾值高、隨高度下降至 floor
DEFAULT_P2 = ParabolaParams(vertex=700.0, floor=0.4, ref_x=400.0, ref_y=2.0)
# 預設：P5 F10.7(sfu) → Δa 閾值倍率；高通量(阻力強)倍率上升以抑制誤報
DEFAULT_P5 = ParabolaParams(vertex=70.0, floor=1.0, ref_x=200.0, ref_y=1.6)
# P6 星座感知基準倍率（依傾角族群）
DEFAULT_P6 = {"53deg": 1.0, "SSO": 1.2, "mid-inc": 1.1, "other": 1.0}

# ── P1–P6 說明文字三語樣板（zh/ja/en）─────────────────────────────────────────
# {n}/{total} 為旗標數量、{vertex}/{mult}/{p6mult} 為策略參數、{fam} 為 inc_family()
# 回傳值（"53deg"/"SSO"/"mid-inc"/"other"，語言中立，不需翻譯）。
NOTE_TEMPLATES: dict[str, dict[str, str]] = {
    "P1": {
        "zh": "單調衰減抑制：{n} 筆判為阻力衰減",
        "ja": "単調減衰抑制：{n} 件を大気抵抗による減衰と判定",
        "en": "Monotonic-decay suppression: {n} classified as drag decay",
    },
    "P2": {
        "zh": "高度自適應閾值（拋物線左側，vertex={vertex:.0f}km）：{n} 旗標",
        "ja": "高度適応しきい値（放物線の左枝、vertex={vertex:.0f}km）：{n} 件のフラグ",
        "en": "Altitude-adaptive threshold (left branch of parabola, vertex={vertex:.0f} km): {n} flags",
    },
    "P3": {
        "zh": "B* 輔助抑制：{n} 筆由阻力解釋",
        "ja": "B* 補助抑制：{n} 件を大気抵抗で説明",
        "en": "B*-assisted suppression: {n} explained by drag",
    },
    "P4": {
        "zh": "多窗口補充：{n} 旗標",
        "ja": "マルチウィンドウ補完：{n} 件のフラグ",
        "en": "Multi-window supplement: {n} flags",
    },
    "P5": {
        "zh": "F10.7 倍率（拋物線）：中位倍率 {mult:.2f}，{n} 旗標",
        "ja": "F10.7 倍率（放物線）：中央値倍率 {mult:.2f}、{n} 件のフラグ",
        "en": "F10.7 multiplier (parabola): median multiplier {mult:.2f}, {n} flags",
    },
    "P6": {
        "zh": "星座感知（{fam}，倍率 {p6mult:.2f}）：{n} 旗標",
        "ja": "コンステレーション感知（{fam}、倍率 {p6mult:.2f}）：{n} 件のフラグ",
        "en": "Constellation-aware ({fam}, multiplier {p6mult:.2f}): {n} flags",
    },
    "combined": {
        "zh": "合併偵測：{n} / {total} 轉換",
        "ja": "統合検知：{n} / {total} 遷移",
        "en": "Combined detection: {n} / {total} transitions",
    },
}


def _note(key: str, lang: str, **kwargs) -> str:
    d = NOTE_TEMPLATES.get(key, {})
    tpl = d.get(lang) or d.get("zh") or key
    return tpl.format(**kwargs)


def inc_family(i_deg: float) -> str:
    if 52.0 <= i_deg <= 54.5:
        return "53deg"
    if 96.0 <= i_deg <= 100.0:
        return "SSO"
    if 40.0 <= i_deg <= 90.0:
        return "mid-inc"
    return "other"


# ── 轉換序列計算 ──────────────────────────────────────────────────────────────

def _angle_diff(a1: float, a2: float) -> float:
    d = (a2 - a1) % 360.0
    return d - 360.0 if d > 180.0 else d


def _j2_raan_deg(a, e, i_deg, dt_s):
    i = np.radians(i_deg)
    n = np.sqrt(MU / a ** 3)
    p = a * (1 - e ** 2)
    return np.degrees(-1.5 * n * J2 * (R_E / p) ** 2 * np.cos(i)) * dt_s


def build_transitions(df: pd.DataFrame, f107_lookup: dict | None = None) -> pd.DataFrame:
    """由連續 TLE（欄位 epoch, sma_km, inclination_deg, eccentricity, raan_deg[, bstar]）
    計算逐轉換 da/di/de/draan_res/dt/alt/f107。"""
    d = df.sort_values("epoch").reset_index(drop=True)
    rows = []
    for i in range(1, len(d)):
        p, c = d.iloc[i - 1], d.iloc[i]
        dt_s = (c["epoch"] - p["epoch"]).total_seconds()
        if dt_s <= 0:
            continue
        a0 = float(p["sma_km"])
        da = float(c["sma_km"]) - a0
        di = float(c["inclination_deg"]) - float(p["inclination_deg"])
        de = float(c["eccentricity"]) - float(p["eccentricity"])
        draan_raw = _angle_diff(float(p["raan_deg"]), float(c["raan_deg"]))
        draan_res = draan_raw - _j2_raan_deg(a0, float(p["eccentricity"]),
                                             float(p["inclination_deg"]), dt_s)
        f107 = np.nan
        if f107_lookup:
            f107 = float(f107_lookup.get(pd.Timestamp(c["epoch"]).strftime("%Y-%m-%d"), np.nan))
        rows.append({
            "epoch": c["epoch"], "alt_km": a0 - R_E, "sma_km": float(c["sma_km"]),
            "inc_deg": float(p["inclination_deg"]),
            "da_km": da, "di_deg": di, "de": de, "draan_res_deg": draan_res,
            "dt_h": dt_s / 3600.0,
            "bstar": float(p["bstar"]) if "bstar" in d.columns and pd.notna(p.get("bstar")) else np.nan,
            "f107": f107,
        })
    return pd.DataFrame(rows)


# ── P1–P6 ─────────────────────────────────────────────────────────────────────

def apply_strategies(tr: pd.DataFrame, orbit_class: str,
                     p2: ParabolaParams = DEFAULT_P2,
                     p5: ParabolaParams = DEFAULT_P5,
                     p6: dict | None = None,
                     lang: str = "zh") -> dict:
    """回傳每個策略的逐轉換布林旗標與合併結果。

    Parameters
    ----------
    lang : "zh" | "ja" | "en"，決定 notes 說明文字語言；預設 "zh"（沿用既有呼叫端行為）。
           未知語言或該 key 缺少對應翻譯時，一律退回 "zh"。

    Returns
    -------
    dict:
      per_strategy : {P1..P6: np.ndarray[bool]}  各策略貢獻（偵測或抑制遮罩）
      combined     : np.ndarray[bool]            最終合併旗標
      thr_da       : np.ndarray[float]           每轉換實際採用的 Δa 閾值
      notes        : dict                        每策略一句說明（依 lang 三語）
    """
    p6 = p6 or DEFAULT_P6
    n = len(tr)
    if n == 0:
        return {"per_strategy": {}, "combined": np.array([], bool),
                "thr_da": np.array([]), "notes": {}}

    da = tr["da_km"].to_numpy(float)
    di = tr["di_deg"].to_numpy(float)
    de = tr["de"].to_numpy(float)
    dr = tr["draan_res_deg"].to_numpy(float)
    alt = tr["alt_km"].to_numpy(float)
    bstar = tr["bstar"].to_numpy(float)
    f107 = tr["f107"].to_numpy(float)

    # ── P2：高度自適應 Δa 閾值（拋物線左側）──────────────────────────────────
    thr_p2 = p2(alt)
    flag_p2 = np.abs(da) > thr_p2

    # ── P5：F10.7 倍率（拋物線）調整 P2 閾值 ─────────────────────────────────
    mult = np.where(np.isnan(f107), 1.0, p5(np.nan_to_num(f107, nan=p5.vertex)))
    thr_p5 = thr_p2 * mult
    flag_p5 = np.abs(da) > thr_p5

    # ── P6：星座感知基準倍率（依傾角族群）─────────────────────────────────────
    fam = inc_family(float(np.nanmedian(tr["inc_deg"]))) if n else "other"
    p6_mult = p6.get(fam, 1.0)
    # MEO/GEO 無大氣阻力，Δa 門檻改用極小值（微小 ΔV 也算機動）
    if orbit_class in ("MEO", "GEO", "GEO+", "HEO"):
        thr_p6 = np.full(n, 0.05)
    else:
        thr_p6 = thr_p2 * p6_mult
    flag_p6 = np.abs(da) > thr_p6

    # 其他指標（di/de/draan）於任何策略皆可觸發
    flag_other = (np.abs(di) > THR_DI) | (np.abs(de) > THR_DE) | (np.abs(dr) > THR_DRAAN)

    # ── P1：單調衰減抑制（純大氣阻力，非機動）──────────────────────────────
    # 連續多筆小幅負 da、無大跳變、正 B* → 阻力衰減，抑制誤報。
    suppress_p1 = np.zeros(n, bool)
    win = 5
    for i in range(n):
        lo = max(0, i - win + 1)
        seg = da[lo:i + 1]
        if len(seg) >= 4:
            frac_small_neg = np.mean(seg < 0.1)
            no_jump = np.all(np.abs(seg) < 2.0)
            bs_ok = (not np.isnan(bstar[i])) and bstar[i] > 0
            if frac_small_neg >= 0.85 and no_jump and bs_ok:
                suppress_p1[i] = True

    # ── P3：B* 輔助抑制（da 可由高 B* 阻力解釋）────────────────────────────
    suppress_p3 = np.zeros(n, bool)
    valid_bs = bstar[~np.isnan(bstar)]
    bs_hi = np.nanmedian(valid_bs) + 2 * np.nanstd(valid_bs) if len(valid_bs) else np.inf
    for i in range(n):
        if (not np.isnan(bstar[i])) and bstar[i] > max(bs_hi, 5e-4) and da[i] < 0 and abs(da[i]) < 1.5:
            suppress_p3[i] = True

    # ── 大幅步階護欄（2026-09-21）──────────────────────────────────────────
    # P1／P3 以「小幅負 Δa」判斷阻力衰減，但其容許值（P1 為 2 km、P3 為 1.5 km）遠大於 P2 高度門檻，
    # 會把向下的降軌機動誤當成衰減擋掉（福衛五號 2026-04-14 的 −519 m 即為一例）。
    # 本身已超過 P2 高度門檻的步階，不得被抑制規則擋下。
    suppress_p1 &= ~flag_p2
    suppress_p3 &= ~flag_p2

    # ── P4：多窗口補充偵測（滑動 3 筆內出現超閾值即補旗標）──────────────────
    base_detect = flag_p2 | flag_other
    flag_p4 = np.zeros(n, bool)
    for i in range(n):
        lo = max(0, i - 2)
        if base_detect[lo:i + 1].any():
            flag_p4[i] = True

    # ── 合併：偵測(P2/P5/P6/other/P4) 取聯集，再扣除抑制(P1/P3) ─────────────
    detect = flag_p2 | flag_p5 | flag_p6 | flag_other | flag_p4
    combined = detect & ~(suppress_p1 | suppress_p3)

    return {
        "per_strategy": {
            "P1_suppress": suppress_p1,
            "P2": flag_p2,
            "P3_suppress": suppress_p3,
            "P4": flag_p4,
            "P5": flag_p5,
            "P6": flag_p6,
            "other(di/de/dΩ)": flag_other,
        },
        "combined": combined,
        "thr_da": thr_p5,       # 實務採用（含 F10.7 調整）
        "notes": {
            "P1": _note("P1", lang, n=int(suppress_p1.sum())),
            "P2": _note("P2", lang, vertex=p2.vertex, n=int(flag_p2.sum())),
            "P3": _note("P3", lang, n=int(suppress_p3.sum())),
            "P4": _note("P4", lang, n=int(flag_p4.sum())),
            "P5": _note("P5", lang, mult=float(np.nanmedian(mult)), n=int(flag_p5.sum())),
            "P6": _note("P6", lang, fam=fam, p6mult=p6.get(fam, 1.0), n=int(flag_p6.sum())),
            "combined": _note("combined", lang, n=int(combined.sum()), total=n),
        },
    }
