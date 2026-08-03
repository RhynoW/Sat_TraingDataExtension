#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ids_sigma_calibrate.py — 用 ILRS/IDS 認證安靜期，實測各高度 TLE 半長軸雜訊 σ_sma。

目的：報告表 11 的 σ（>700 km 帶用 0.05 km）來自合成注入，且從未在 >800 km 校準
      （最高只到 FORMOSAT-3 的 789 km）。IDS 測高衛星提供 717–1325 km 的目標，且其
      安靜期由 operator 點火日誌認證，可實測真實 σ，把表 11 的高度帶真正校準。

方法（trend-immune）：
  在每個安靜區間內取 TLE 的 sma 序列，於區間內做「相鄰差分」——差分消去慢變趨勢
  （大氣阻力衰減），殘差即雜訊。以 MAD 穩健估計：σ ≈ 1.4826·MAD(Δsma)/√2。
  另以「區間內去線性趨勢後殘差 MAD」交叉驗證。兩法一致即可信。

用法：python ids_sigma_calibrate.py
輸出：ids_sigma_calibration.csv（每顆一列）＋ 主控台表。
"""
from __future__ import annotations
import csv, sys, math, datetime as dt
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import duckdb

DB = Path(__file__).resolve().parents[1] / "space_db.duckdb"
QUIET = Path(__file__).parent / "ids_quiet.csv"
RE = 6378.137
TAI_UTC = 37.0  # s（2017 起）；對 σ 無感，仍轉以求一致

# ids_id → (norad, 顯示名)。norad 已對 space_db 確認存在。
TARGETS = [
    (36508, "CryoSat-2"), (27386, "Envisat"),  (37781, "HY-2A"),
    (46469, "HY-2C"),     (48621, "HY-2D"),    (26997, "Jason-1"),
    (33105, "Jason-2"),   (41240, "Jason-3"),  (39086, "SARAL"),
    (41335, "Sentinel-3A"),(43437, "Sentinel-3B"),(46984, "Sentinel-6A"),
    (54754, "SWOT"),
]
# ids_id 對照（quiet csv 用 ids_id 欄）
NORAD2IDS = {36508:"CRYO2",27386:"ENVI1",37781:"HY-2A",46469:"HY-2C",48621:"HY-2D",
             26997:"JASO1",33105:"JASO2",41240:"JASO3",39086:"SARAL",41335:"SEN3A",
             43437:"SEN3B",46984:"SEN6A",54754:"SWOT1"}

BUFFER_D = 0.75   # 安靜區間兩端各留 0.75 天，避開機動暫態
MIN_PTS  = 12     # 每區間最少可用點
MIN_SPAN_D = 3.0  # 每區間最少跨度


MIN_GAP_HR = 3.0   # 去重/稀釋：相鄰點至少間隔 3 小時（消除重複列與近重複 epoch）


def load_tle(nid):
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT epoch_utc, sma_km FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    t = np.array([r[0].timestamp() if hasattr(r[0], "timestamp")
                  else dt.datetime.fromisoformat(str(r[0])).timestamp() for r in rows])
    a = np.array([float(r[1]) for r in rows])
    # 去重＋稀釋：保留每 ≥MIN_GAP_HR 一點（重複 epoch 與近重複會使 MAD 假性偏小）
    keep = [0]
    for i in range(1, len(t)):
        if (t[i] - t[keep[-1]]) >= MIN_GAP_HR * 3600:
            keep.append(i)
    return t[keep], a[keep]


def load_quiet(ids_id):
    out = []
    for r in csv.DictReader(open(QUIET, encoding="utf-8-sig")):
        if r["ids_id"] != ids_id:
            continue
        # TAI → UTC（epoch 秒）
        s = dt.datetime.fromisoformat(r["quiet_start_tai"]).timestamp() - TAI_UTC
        e = dt.datetime.fromisoformat(r["quiet_end_tai"]).timestamp() - TAI_UTC
        out.append((s, e))
    return out


def robust_sigma(nid, ids_id):
    t, a = load_tle(nid)
    if len(t) < MIN_PTS:
        return None
    quiets = load_quiet(ids_id)
    diffs, resids, npts, nint, spans = [], [], 0, 0, []
    for (s, e) in quiets:
        s += BUFFER_D * 86400; e -= BUFFER_D * 86400
        if e <= s:
            continue
        m = (t >= s) & (t <= e)
        if m.sum() < MIN_PTS:
            continue
        tt, aa = t[m], a[m]
        span = (tt[-1] - tt[0]) / 86400.0
        if span < MIN_SPAN_D:
            continue
        nint += 1; npts += len(aa); spans.append(span)
        # 去趨勢殘差（主）：多項式階數依跨度，消阻力慢變曲率後殘差＝雜訊
        deg = 1 if span < 10 else (2 if span < 40 else 3)
        deg = min(deg, len(aa) - 2)
        x = (tt - tt[0]) / 86400.0
        c = np.polyfit(x, aa, max(deg, 1))
        resids.extend((aa - np.polyval(c, x)).tolist())
        # 差分法（交叉驗證）：去重後相鄰差
        diffs.extend(np.diff(aa).tolist())
    if nint == 0:
        return None
    d = np.abs(np.array(diffs)); r = np.abs(np.array(resids))
    sig_res  = 1.4826 * np.median(r)                        # km（主）
    sig_diff = 1.4826 * np.median(d) / math.sqrt(2.0)      # km（交叉驗證）
    alt = float(np.median(a)) - RE
    return dict(norad=nid, alt_km=alt, n_int=nint, n_pts=npts,
                span_med_d=float(np.median(spans)),
                sigma_diff_km=sig_diff, sigma_resid_km=sig_res,
                sma_med=float(np.median(a)))


def table11_sigma(alt):
    if alt < 450: return 0.15
    if alt < 700: return 0.08
    return 0.05


def main():
    print(f"{'衛星':12}{'NORAD':7}{'高度km':>8}{'安靜區':>6}{'點數':>6}"
          f"{'σ_res m':>9}{'σ_diff m':>10}{'表11 m':>8}{'實測/表11':>10}")
    rows = []
    for nid, name in TARGETS:
        r = robust_sigma(nid, NORAD2IDS[nid])
        if not r:
            print(f"{name:12}{nid:<7}  (安靜區間內 TLE 不足，略)"); continue
        t11 = table11_sigma(r["alt_km"])
        ratio = r["sigma_resid_km"] / t11        # σ_res（去趨勢殘差）為主
        rows.append({**r, "name": name, "t11_km": t11, "ratio": ratio})
        print(f"{name:12}{nid:<7}{r['alt_km']:8.0f}{r['n_int']:6}{r['n_pts']:6}"
              f"{r['sigma_resid_km']*1000:9.1f}{r['sigma_diff_km']*1000:10.1f}"
              f"{t11*1000:8.0f}{ratio:10.3f}")
    out = Path(__file__).parent / "ids_sigma_calibration.csv"
    if rows:
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print(f"\n表 → {out}")
        # >800 km 帶小結
        hi = [r for r in rows if r["alt_km"] >= 800]
        if hi:
            import statistics as st
            s = st.median(r["sigma_diff_km"] for r in hi) * 1000
            print(f">800 km 帶（{len(hi)} 顆）實測 σ 中位 = {s:.1f} m"
                  f"（表 11 假設 50 m；比值 {s/50:.2f}）")


if __name__ == "__main__":
    main()
