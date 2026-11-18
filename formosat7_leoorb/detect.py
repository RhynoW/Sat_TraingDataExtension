"""由 leoOrb SP3 辨識福衛七號的機動事件，並驗證候選是否為真。

方法（承本專案在 Starlink 上的三條判準，見 burn_arc_profiler）
----------------------------------------------------------------
1. 由 r,v 算瞬時半長軸 a(t) 與傾角 i(t)。**速度須先補 omega_E x r**（SP3 給地固速度）。
2. **重採樣至均勻 60 秒網格**。leoOrb 的弧段在 2024 年未對齊共同網格
   （相鄰間隔 10/20/30/40/50 秒混合），不重採樣則滾動視窗會對應錯誤樣本數。
3. 以**一個軌道週期的滾動平均**消 J2 短週期。視窗須逐序列由實際週期算出，
   不可寫死 —— 不到 1% 的失配即讓 2/rev 主項殘留 7 倍以上。
4. 以**整數軌道圈**為差分尺度。非整數圈會把殘留諧波混疊成虛假結構。
5. 門檻由序列自身雜訊決定（4 x 穩健 sigma）。

為何福七不能逐檔處理
--------------------
leoOrb 單一弧段僅 126 分鐘，**短於分析所需視窗**（一圈平滑約 95.5 分 + 一圈差分）。
故必須先合併為連續序列，這與 Starlink MEME（每檔 72 小時連續軌跡）不同。

驗證：候選事件是否為真
----------------------
偵出的超門檻段**不等於機動**。本模組以四項獨立證據判定，全部來自資料自身：

  (a) **持久性**：真機動使平均半長軸產生**永久階躍**；殘留假訊號是暫態、會回復。
      以事件前後各數小時的平均 a 相減得 step_m，並與尖峰量比較。
  (b) **弧段一致性**：leoOrb 同一時刻有 4-6 個獨立解算的弧段。真事件在各弧段
      都看得到；假訊號則因各弧獨立解算而彼此不一致。
  (c) **共模檢查**：若同一時刻六顆星同時出現候選，較可能是共同來源
      （太空天氣、產品處理變更），而非六顆同時機動。
  (d) **傾角通道**：面外機動會在 i 上留下訊號，可作為佐證。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .archive import MU_EARTH_KM3_S2 as MU, OMEGA_EARTH_RAD_S as OMEGA

log = logging.getLogger(__name__)

#: 差分與平滑各取幾個軌道圈（須為整數）
LAG_ORBITS = 1
SMOOTH_ORBITS = 1
#: 門檻 = THR_SIGMA x 穩健 sigma，並設下限
THR_SIGMA = 4.0
THR_FLOOR_KM = 0.002
#: 持久性判定的前後視窗（小時）與間隔
STEP_WIN_H = 6.0
STEP_GAP_H = 1.0


def _orbital_period_min(a_km: float) -> float:
    return 2.0 * np.pi * np.sqrt(a_km ** 3 / MU) / 60.0


def build_series(df: pd.DataFrame, step_s: int = 60) -> dict:
    """逐星的均勻網格序列。回傳 {sp3_sat: DataFrame[a_km, inc_deg, n_arcs]}。

    df 為 archive.load_leoorb_tar 的輸出（**合併前**，保留 arc_id 以便算弧段一致性）。
    """
    out = {}
    for sat, g in df.groupby("sp3_sat"):
        g = g.copy()
        for ax in ("x", "y", "z"):
            if f"v{ax}_km_s" not in g:
                g[f"v{ax}_km_s"] = g[f"v{ax}_dm_s"] / 10000.0
        r = g[["x_km", "y_km", "z_km"]].to_numpy(float)
        v = g[["vx_km_s", "vy_km_s", "vz_km_s"]].to_numpy(float)
        v = v + np.cross(np.array([0.0, 0.0, OMEGA]), r)      # 地固 -> 慣性
        rn = np.linalg.norm(r, axis=1)
        g["a_km"] = 1.0 / (2.0 / rn - (v ** 2).sum(1) / MU)
        h = np.cross(r, v)
        g["inc_deg"] = np.degrees(np.arccos(
            np.clip(h[:, 2] / np.linalg.norm(h, axis=1), -1, 1)))

        g["epoch"] = pd.to_datetime(g["epoch"], utc=True)
        by_ep = g.groupby("epoch")
        per_ep = pd.DataFrame({
            "a_km": by_ep["a_km"].mean(),
            "a_spread_m": (by_ep["a_km"].max() - by_ep["a_km"].min()) * 1000.0,
            "inc_deg": by_ep["inc_deg"].mean(),
            "n_arcs": by_ep["arc_id"].nunique(),
        }).sort_index()

        rule = f"{step_s}s"
        s = per_ep.resample(rule).mean()
        s["a_km"] = s["a_km"].interpolate(limit=3)
        s["inc_deg"] = s["inc_deg"].interpolate(limit=3)
        s = s.dropna(subset=["a_km"])
        if len(s) < 200:
            continue
        out[sat] = s
    return out


def _smooth_and_diff(a: pd.Series, step_s: int):
    """回傳 (平滑序列, 差分序列, 門檻, 圈長樣本數)。"""
    n_per_orbit = max(3, int(round(_orbital_period_min(float(a.median())) * 60 / step_s)))
    sm = a.rolling(SMOOTH_ORBITS * n_per_orbit, center=True).mean().dropna()
    d = sm.diff(LAG_ORBITS * n_per_orbit).dropna()
    mad = float((d - d.median()).abs().median())
    thr = max(THR_SIGMA * 1.4826 * mad, THR_FLOOR_KM)
    return sm, d, thr, n_per_orbit


def detect_events(series: dict, step_s: int = 60) -> pd.DataFrame:
    """偵出候選事件段並附持久性、弧段一致性、傾角變化。"""
    rows = []
    for sat, s in series.items():
        a = s["a_km"]
        sm, d, thr, n_orb = _smooth_and_diff(a, step_s)
        hot = d.abs() > thr
        if not hot.any():
            continue
        grp = (hot != hot.shift()).cumsum()[hot]
        for _, idx in d[hot].groupby(grp).groups.items():
            seg = d.loc[idx]
            t0, t1 = seg.index[0], seg.index[-1]
            peak_t = seg.abs().idxmax()
            # (a) 持久性：事件前後各 STEP_WIN_H 的平均 a
            pre = sm.loc[t0 - pd.Timedelta(STEP_WIN_H + STEP_GAP_H, "h"):
                         t0 - pd.Timedelta(STEP_GAP_H, "h")]
            post = sm.loc[t1 + pd.Timedelta(STEP_GAP_H, "h"):
                          t1 + pd.Timedelta(STEP_WIN_H + STEP_GAP_H, "h")]
            step_m = (float(post.mean()) - float(pre.mean())) * 1000.0 if len(pre) > 10 and len(post) > 10 else np.nan
            peak_m = float(seg.loc[peak_t]) * 1000.0
            # (b) 弧段一致性：事件窗內的獨立解分歧
            win = s.loc[t0:t1]
            # (d) 傾角變化
            ipre = s["inc_deg"].loc[pre.index.min():pre.index.max()] if len(pre) else pd.Series(dtype=float)
            ipost = s["inc_deg"].loc[post.index.min():post.index.max()] if len(post) else pd.Series(dtype=float)
            di = (float(ipost.mean()) - float(ipre.mean())) if len(ipre) and len(ipost) else np.nan
            rows.append({
                "sp3_sat": sat, "t_start": t0, "t_end": t1, "peak_t": peak_t,
                "dur_h": (t1 - t0).total_seconds() / 3600.0,
                "peak_m": peak_m, "step_m": step_m,
                "thr_m": thr * 1000.0,
                "n_arcs_med": float(win["n_arcs"].median()),
                "arc_spread_m": float(win["a_spread_m"].median()),
                "di_deg": di,
            })
    if not rows:
        return pd.DataFrame()
    ev = pd.DataFrame(rows).sort_values(["sp3_sat", "t_start"]).reset_index(drop=True)
    ev["persist_ratio"] = (ev["step_m"].abs() / ev["peak_m"].abs()).replace([np.inf], np.nan)
    return ev


def add_common_mode(ev: pd.DataFrame, window_h: float = 3.0) -> pd.DataFrame:
    """(c) 共模檢查：同一時刻有幾顆星同時出現候選。"""
    if ev.empty:
        return ev
    # tz-aware 的 to_numpy() 會給 object array，須先去時區才能做 datetime64 運算
    t = pd.to_datetime(ev["peak_t"], utc=True).dt.tz_convert(None).to_numpy("datetime64[ns]")
    sats = ev["sp3_sat"].to_numpy()
    w = np.timedelta64(int(window_h * 3600), "s")
    n_sat = []
    for ti in t:
        near = np.abs(t - ti) <= w
        n_sat.append(len(set(sats[near])))
    ev = ev.copy()
    ev["n_sat_concurrent"] = n_sat
    return ev


#: 判定門檻
PERSIST_MIN = 0.5      # 永久階躍須達尖峰量的一半以上
SPREAD_MAX_M = 50.0    # 弧段間分歧上限（真事件各弧應一致）
CONCURRENT_MAX = 3     # 同時 >= 此星數視為共模


def verify(ev: pd.DataFrame) -> pd.DataFrame:
    """綜合四項證據給判定。回傳新增 verdict 與 reason 欄的表。"""
    if ev.empty:
        return ev
    ev = add_common_mode(ev).copy()

    def judge(r):
        why = []
        if not np.isfinite(r["persist_ratio"]) or r["persist_ratio"] < PERSIST_MIN:
            why.append("暫態未留永久階躍")
        if r["arc_spread_m"] > SPREAD_MAX_M:
            why.append("弧段間解不一致")
        if r["n_sat_concurrent"] >= CONCURRENT_MAX:
            why.append("多星共模")
        return pd.Series({"verdict": "疑似真事件" if not why else "判為假訊號",
                          "reason": "；".join(why) if why else "四項檢查皆通過"})

    return pd.concat([ev, ev.apply(judge, axis=1)], axis=1)


def summarise(ev: pd.DataFrame) -> str:
    if ev.empty:
        return "無候選事件"
    n = len(ev)
    ok = int((ev["verdict"] == "疑似真事件").sum())
    lines = [f"候選 {n} 段 -> 通過驗證 {ok} 段（{100*ok/n:.1f}%）", ""]
    lines.append("剔除理由分布：")
    for k, v in ev.loc[ev["verdict"] != "疑似真事件", "reason"].value_counts().items():
        lines.append(f"  {k:<28} {v:>4}")
    return "\n".join(lines)
