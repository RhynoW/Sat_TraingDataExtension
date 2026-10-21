#!/usr/bin/env python3
"""orbit_regime.py — 軌道狀態判別與機動「區段」輸出（案例研究簡報 p.115 步驟 1、2 之初版實作）

動機：融合評分器以 ±24 小時窗口找「短暫跳變」，並以日常站位保持訓練；入軌後持續多日的升軌
（如 Starlink V3）在每個窗口都只像緩慢趨勢，融合評分器只涵蓋 12／61 個升軌段。
本模組改從「狀態」與「區段」兩個角度處理：

步驟 1 狀態判別 classify_regime()
  逐日中位平均高度 → 以 SLOPE_WINDOW_D 天之線性斜率（km／天）判定：
    raising   斜率 > +RATE_KM_D
    lowering  斜率 < −RATE_KM_D
    maintain  其餘（含站位保持、緩慢自然衰減）
  閾值 1 km／天：遠大於 Starlink 級 TLE 高度雜訊之日差，也大於 300 km 以上之自然衰減速率。
  注意：再入前末期之自然衰減可能超過 1 km／天而被標為 lowering；需搭配 atmospheric_drag.is_reentry_decay 判讀。

步驟 2 區段輸出 segments()
  將相同狀態（raising／lowering）之連續日合併（容許 MERGE_GAP_D 天之間隙），每段輸出：
    start／end   以 TLE 逐筆高度定位：段首前 1 天內之最低點、段尾後 1 天內之最高點（升軌；降軌相反）
    delta_km     段內淨高度變化；rate_km_d 平均速率；duration_d 歷時
    dwell_km     段尾後 DWELL_D 天之中位高度（停留高度；資料不足時為 NaN）

輸入：DataFrame(epoch, sma_km)。高度＝sma_km − 6378.137（平均半長軸高度）。
用法：from orbit_regime import classify_regime, segments
"""
from __future__ import annotations

import numpy as np
import pandas as pd

R_E = 6378.137
RATE_KM_D = 1.0
SLOPE_WINDOW_D = 3
MERGE_GAP_D = 0   # 0＝不跨越 maintain 日合併；可分開中途停留 ≥2 天之升軌（停留 1–2 天者仍可能併段，屬 TLE 解析度極限）
DWELL_D = 2.0
MIN_TLE_PER_DAY = 1
EDGE_TOL_KM = 0.3


def _prep(tle: pd.DataFrame) -> pd.DataFrame:
    d = tle[["epoch", "sma_km"]].dropna().copy()
    d["epoch"] = pd.to_datetime(d["epoch"], utc=True)
    d = d.drop_duplicates("epoch").sort_values("epoch").reset_index(drop=True)
    d["alt_km"] = d["sma_km"] - R_E
    return d


def classify_regime(tle: pd.DataFrame, rate_km_d: float = RATE_KM_D,
                    window_d: int = SLOPE_WINDOW_D) -> pd.DataFrame:
    """逐日狀態表：day、alt_km（當日中位）、slope_km_d、regime。"""
    d = _prep(tle)
    if d.empty:
        return pd.DataFrame(columns=["day", "alt_km", "slope_km_d", "regime"])
    daily = d.set_index("epoch")["alt_km"].resample("1D").median()
    daily = daily[d.set_index("epoch")["alt_km"].resample("1D").count() >= MIN_TLE_PER_DAY]
    x = (daily.index - daily.index[0]).days.to_numpy(float)
    y = daily.to_numpy(float)
    slope = np.full(len(y), np.nan)
    half = window_d // 2
    for i in range(len(y)):
        m = np.abs(x - x[i]) <= half
        if m.sum() >= 2:
            slope[i] = np.polyfit(x[m], y[m], 1)[0]
    regime = np.where(slope > rate_km_d, "raising", np.where(slope < -rate_km_d, "lowering", "maintain"))
    regime = np.where(np.isnan(slope), "unknown", regime)
    return pd.DataFrame({"day": daily.index, "alt_km": y, "slope_km_d": slope, "regime": regime})


def segments(tle: pd.DataFrame, kind: str = "raising", rate_km_d: float = RATE_KM_D,
             window_d: int = SLOPE_WINDOW_D) -> pd.DataFrame:
    """把連續的 raising（或 lowering）日合併成區段，並以逐筆 TLE 定位起訖。"""
    cols = ["kind", "start", "end", "duration_d", "alt_start_km", "alt_end_km", "delta_km", "rate_km_d", "dwell_km"]
    reg = classify_regime(tle, rate_km_d, window_d)
    d = _prep(tle)
    days = reg.loc[reg.regime == kind, "day"].tolist()
    if not days:
        return pd.DataFrame(columns=cols)
    groups, cur = [], [days[0]]
    for t in days[1:]:
        if (t - cur[-1]).days <= MERGE_GAP_D + 1:
            cur.append(t)
        else:
            groups.append(cur); cur = [t]
    groups.append(cur)
    one = pd.Timedelta(days=1)
    rows = []
    for g in groups:
        lo, hi = g[0] - one, g[-1] + 2 * one
        w = d[(d.epoch >= lo) & (d.epoch < hi)]
        if len(w) < 2:
            continue
        sgn = 1.0 if kind == "raising" else -1.0
        pre, post = w[w.epoch < g[0] + one], w[w.epoch >= g[-1]]
        if pre.empty or post.empty:
            continue
        i0 = (sgn * pre.alt_km).idxmin()
        i1 = (sgn * post.alt_km).idxmax()
        if i1 <= i0:
            continue
        # 收緊起訖：起點＝仍在起始高度 EDGE_TOL_KM 內的最後一筆；終點＝首次到達終點高度 EDGE_TOL_KM 內的那一筆
        seg = d.loc[i0:i1]
        a_lo, a_hi = float(d.loc[i0, "alt_km"]), float(d.loc[i1, "alt_km"])
        i0 = seg.index[(sgn * (seg.alt_km - a_lo)) <= EDGE_TOL_KM].max()
        seg = d.loc[i0:i1]
        i1 = seg.index[(sgn * (a_hi - seg.alt_km)) <= EDGE_TOL_KM].min()
        if i1 <= i0:
            continue
        t0, t1 = d.loc[i0, "epoch"], d.loc[i1, "epoch"]
        a0, a1 = float(d.loc[i0, "alt_km"]), float(d.loc[i1, "alt_km"])
        dur = (t1 - t0).total_seconds() / 86400
        after = d[(d.epoch > t1) & (d.epoch <= t1 + pd.Timedelta(days=DWELL_D))]
        rows.append(dict(kind=kind, start=t0, end=t1, duration_d=round(dur, 2), alt_start_km=round(a0, 2),
                         alt_end_km=round(a1, 2), delta_km=round(a1 - a0, 2),
                         rate_km_d=round((a1 - a0) / dur, 2) if dur > 0 else np.nan,
                         dwell_km=round(float(after.alt_km.median()), 2) if len(after) >= 2 else np.nan))
    return pd.DataFrame(rows, columns=cols)
