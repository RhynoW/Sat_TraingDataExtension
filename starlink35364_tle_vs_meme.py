#!/usr/bin/env python3
"""
MEME ephemeris vs TLE (SGP4) residual analysis for a single Starlink satellite.

功能：
1. 讀 MEME 文字檔，抽出 UTC, r, v -> CSV
2. 用多組 TLE 做 SGP4 propagation（Skyfield，GCRS ≈ EME2000）-> MEME epoch
3. 計算 Cartesian 殘差與 RTN 分量
4. 產生：
   - meme_states.csv
   - tle_vs_meme_all.csv
   - tle_vs_meme_segmented.csv  (nearest-TLE 分段)
   - tle_vs_meme_summary.csv
   - tle_vs_meme_rss.html
   - tle_vs_meme_rtn.html

座標系說明
----------
MEME 檔使用 UVW = EME2000（J2000 ECI）。
Skyfield `EarthSatellite.at()` 回傳 GCRS，與 J2000/EME2000 在 sub-km
精度下可互通，不需要額外旋轉矩陣。
請勿直接使用 sgp4.api.Satrec.sgp4() —— 其輸出為 TEME 座標，
與 MEME EME2000 相差 0.2–0.5 km（主要在 Cross-track 方向）。
"""

from __future__ import annotations

import math
import re
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from skyfield.api import EarthSatellite
from skyfield.api import load as skyfield_load


# ========= 使用者設定 =========

# MEME 原始文字檔路徑
MEME_TXT_PATH = "2026-05-02T09-56-42Z.txt"

# 輸出資料夾
OUT_DIR = Path("output_starlink35364")
OUT_DIR.mkdir(exist_ok=True)

# 多組 TLE：這邊放你手上的 Starlink TLE（可放任意數量）
TLES = [
    (
        "1 65840U 25221T   26121.92913175  .00012783  00000-0  44311-3 0  9991",
        "2 65840  53.1610 201.1149 0001546  84.2224 275.8953 15.30189473 32888",
    ),
    (
        "1 65840U 25221T   26122.38633737  .00019760  00000-0  67753-3 0  9992",
        "2 65840  53.1593 198.9925 0001801  82.9392 277.1813 15.30198268 32958",
    ),
    (
        "1 65840U 25221T   26122.51696622  .00015058  00000-0  51962-3 0  9990",
        "2 65840  53.1580 198.3860 0001193  85.0282 275.0855 15.30192271 32975",
    ),
]


# ========= MEME 解析 =========

# 時間戳格式：YYYYDDDHHMMSS.sss（共 13 位數字 + 小數點 + 3 位小數）
_TS_RE = re.compile(r"^(\d{4})(\d{3})(\d{2})(\d{2})(\d{2}\.\d+)$")


def parse_meme_to_states(path: str | Path) -> pd.DataFrame:
    """
    從 MEME 文字檔抽出 state 行：
      YYYYDDDHHMMSS.sss  x  y  z  vx  vy  vz

    - 時間戳：完整保留小數秒（微秒精度）
    - 跳過協方差行（長度 ≠ 7 且首欄不符時間戳格式）
    - 回傳含 utc（tz-aware）與 hours_from_start 的 DataFrame
    """
    rows: list[list] = []

    for line in Path(path).open("r", encoding="utf-8"):
        parts = line.split()
        if len(parts) != 7:
            continue

        m = _TS_RE.match(parts[0])
        if not m:
            continue

        year = int(m.group(1))
        doy  = int(m.group(2))
        hh   = int(m.group(3))
        mm   = int(m.group(4))
        ss_f = float(m.group(5))           # e.g. 42.000 or 42.536
        ss_i = int(ss_f)
        us   = round((ss_f - ss_i) * 1_000_000)

        dt = (
            pd.Timestamp(year=year, month=1, day=1, tz="UTC")
            + pd.Timedelta(days=doy - 1, hours=hh, minutes=mm,
                           seconds=ss_i, microseconds=us)
        )
        rows.append([dt] + list(map(float, parts[1:])))

    df = pd.DataFrame(
        rows,
        columns=["utc", "x_km", "y_km", "z_km", "vx_kms", "vy_kms", "vz_kms"],
    )
    if not df.empty:
        df["hours_from_start"] = (
            (df["utc"] - df["utc"].iloc[0]).dt.total_seconds() / 3600.0
        )
    return df


# ========= TLE / Skyfield 工具 =========

def tle_epoch_utc(line1: str) -> pd.Timestamp:
    """TLE line-1 的 epoch（year + day-of-year）轉成 UTC Timestamp。"""
    yr = int(line1[18:20])
    yr += 2000 if yr < 57 else 1900
    doyf = float(line1[20:32])
    day  = int(math.floor(doyf))
    frac = doyf - day
    return (
        pd.Timestamp(year=yr, month=1, day=1, tz="UTC")
        + pd.Timedelta(days=day - 1 + frac)
    )


def propagate_skyfield(
    sat: EarthSatellite,
    times_utc: pd.Series,
    ts,
) -> tuple[np.ndarray, np.ndarray]:
    """
    用 Skyfield propagate 到一組 UTC 時間。

    回傳：
      pos  shape (3, N)  km      GCRS ≈ EME2000
      vel  shape (3, N)  km/s    GCRS ≈ EME2000
    """
    t_arr = ts.from_datetimes([
        dt.to_pydatetime() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).to_pydatetime()
        for dt in times_utc
    ])
    geo = sat.at(t_arr)
    return geo.position.km, geo.velocity.km_per_s   # GCRS ≈ J2000/EME2000


# ========= RTN 投影 =========

def rtn_from_cartesian(
    r_ref: np.ndarray,
    v_ref: np.ndarray,
    dr: np.ndarray,
) -> np.ndarray:
    """
    把位置殘差 dr 投影到 RTN（Radial / Along-track / Cross-track）。

    定義：
      R = r̂  （徑向向外）
      N = (r × v) / |r × v|  （法向量，軌道平面法線）
      T = N × R               （沿軌方向，近似速度方向）

    r_ref, v_ref 單位 km / km/s；dr 單位 km。
    回傳 [dr_R, dr_T, dr_N]（km）。
    """
    rhat = r_ref / np.linalg.norm(r_ref)
    nhat = np.cross(r_ref, v_ref)
    nhat = nhat / np.linalg.norm(nhat)
    that = np.cross(nhat, rhat)
    return np.array(
        [np.dot(dr, rhat), np.dot(dr, that), np.dot(dr, nhat)],
        dtype=float,
    )


# ========= 主流程：TLE vs MEME =========

def tle_vs_meme_analysis(
    meme_df: pd.DataFrame,
    tles: list[tuple[str, str]],
    ts,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    給定 MEME 狀態表與多組 TLE，回傳：
      res_all       — 每個 TLE × 每個 MEME epoch 的殘差
      res_segmented — 依「最近 TLE epoch」分段後的最佳殘差
    """
    # 建構 Skyfield EarthSatellite + epoch
    tle_objs: list[dict] = []
    for i, (l1, l2) in enumerate(tles, start=1):
        sat = EarthSatellite(l1, l2, ts=ts)
        tle_objs.append({
            "tle_id":    f"TLE-{i}",
            "epoch_utc": tle_epoch_utc(l1),
            "sat":       sat,
            "line1":     l1,
            "line2":     l2,
        })

    # 所有 TLE × 所有 MEME epoch 的殘差
    records: list[dict] = []
    for tle in tle_objs:
        pos, vel = propagate_skyfield(tle["sat"], meme_df["utc"], ts)
        for j, row in enumerate(meme_df.itertuples(index=False)):
            r_ref = np.array([row.x_km,   row.y_km,   row.z_km],   dtype=float)
            v_ref = np.array([row.vx_kms, row.vy_kms, row.vz_kms], dtype=float)
            r_tle = pos[:, j]
            v_tle = vel[:, j]

            dr = r_tle - r_ref          # TLE − MEME（正值＝TLE 超前）
            dv = v_tle - v_ref
            dr_r, dr_t, dr_n = rtn_from_cartesian(r_ref, v_ref, dr)

            records.append({
                "utc":             row.utc,
                "hours_from_start": row.hours_from_start,
                "tle_id":          tle["tle_id"],
                "tle_epoch_utc":   tle["epoch_utc"],
                "tle_age_hours":   (row.utc - tle["epoch_utc"]).total_seconds() / 3600.0,
                "dx_km":           float(dr[0]),
                "dy_km":           float(dr[1]),
                "dz_km":           float(dr[2]),
                "rss_pos_km":      float(np.linalg.norm(dr)),
                "rss_vel_kms":     float(np.linalg.norm(dv)),
                "dr_r_km":         float(dr_r),
                "dr_t_km":         float(dr_t),
                "dr_n_km":         float(dr_n),
            })

    res_all = pd.DataFrame.from_records(records)

    # 依「距 TLE epoch 絕對時間最近」分段
    m2 = meme_df[["utc"]].copy()
    for tle in tle_objs:
        col = tle["tle_id"] + "_abs_age_h"
        m2[col] = (m2["utc"] - tle["epoch_utc"]).abs().dt.total_seconds() / 3600.0

    age_cols = [c for c in m2.columns if c.endswith("_abs_age_h")]
    m2["segment_tle_id"] = (
        m2[age_cols].idxmin(axis=1).str.replace("_abs_age_h", "", regex=False)
    )

    res_segmented = res_all.merge(m2[["utc", "segment_tle_id"]], on="utc")
    res_segmented = res_segmented[
        res_segmented["tle_id"] == res_segmented["segment_tle_id"]
    ].copy()

    return res_all, res_segmented


# ========= 繪圖 =========

def plot_rss(
    res_all: pd.DataFrame,
    res_segmented: pd.DataFrame,
    out_html: Path,
) -> None:
    """位置 3D RSS (km) vs UTC：每組 TLE + nearest-TLE segmented 曲線。"""
    fig = go.Figure()

    for tle_id, g in res_all.groupby("tle_id"):
        epoch = g["tle_epoch_utc"].iloc[0]
        label = f"{tle_id}  (epoch {pd.Timestamp(epoch).strftime('%Y-%m-%dT%H:%M')})"
        fig.add_trace(go.Scatter(
            x=g["utc"], y=g["rss_pos_km"],
            mode="lines", name=label,
        ))

    fig.add_trace(go.Scatter(
        x=res_segmented["utc"],
        y=res_segmented["rss_pos_km"],
        mode="lines",
        name="Nearest-TLE segmented",
        line=dict(color="black", dash="dash", width=3),
    ))

    fig.update_layout(
        title="TLE (SGP4/GCRS) vs MEME (EME2000) — Position RSS",
        xaxis_title="UTC",
        yaxis_title="Position error (km)",
        template="plotly_white",
    )
    fig.write_html(out_html, include_plotlyjs="cdn")


def plot_rtn(
    res_segmented: pd.DataFrame,
    out_html: Path,
) -> None:
    """Segmented 解的 RTN 分量 vs UTC：R / Along-track(T) / Cross-track(N)。"""
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=["Radial (R)", "Along-track (T)", "Cross-track (N)"],
    )

    colors = ["royalblue", "tomato", "seagreen"]
    for row_idx, (col, label, color) in enumerate(
        [("dr_r_km", "R", colors[0]),
         ("dr_t_km", "T", colors[1]),
         ("dr_n_km", "N", colors[2])], start=1
    ):
        # Add zero reference line
        fig.add_hline(y=0, line_dash="dot", line_color="gray",
                      line_width=1, row=row_idx, col=1)
        fig.add_trace(
            go.Scatter(
                x=res_segmented["utc"],
                y=res_segmented[col],
                mode="lines",
                name=label,
                line=dict(color=color),
            ),
            row=row_idx, col=1,
        )

    fig.update_layout(
        title="TLE vs MEME — RTN Position Error (Nearest-TLE segmented)",
        template="plotly_white",
        height=900,
    )
    fig.update_xaxes(title_text="UTC", row=3, col=1)
    for r, label in [(1, "R (km)"), (2, "T (km)"), (3, "N (km)")]:
        fig.update_yaxes(title_text=label, row=r, col=1)

    fig.write_html(out_html, include_plotlyjs="cdn")


# ========= main =========

def main() -> None:
    ts = skyfield_load.timescale()

    # 1) 解析 MEME -> CSV
    print(f"Parsing MEME: {MEME_TXT_PATH}")
    meme_df = parse_meme_to_states(MEME_TXT_PATH)
    if meme_df.empty:
        raise SystemExit(f"No state vectors parsed from {MEME_TXT_PATH}")
    meme_csv = OUT_DIR / "meme_states.csv"
    meme_df.to_csv(meme_csv, index=False)
    print(f"  {len(meme_df)} state vectors  →  {meme_csv}")

    # 2) TLE vs MEME 殘差
    print(f"Propagating {len(TLES)} TLE(s) over {len(meme_df)} MEME epochs …")
    res_all, res_segmented = tle_vs_meme_analysis(meme_df, TLES, ts)

    # 3) 輸出 CSV
    res_all.to_csv(OUT_DIR / "tle_vs_meme_all.csv", index=False)
    res_segmented.to_csv(OUT_DIR / "tle_vs_meme_segmented.csv", index=False)

    summary = (
        res_all.groupby("tle_id")
        .agg(
            tle_epoch_utc    = ("tle_epoch_utc",  "first"),
            samples          = ("utc",            "count"),
            min_rss_km       = ("rss_pos_km",     "min"),
            mean_rss_km      = ("rss_pos_km",     "mean"),
            max_rss_km       = ("rss_pos_km",     "max"),
            final_rss_km     = ("rss_pos_km",     "last"),
            mean_rss_vel_kms = ("rss_vel_kms",    "mean"),
            min_abs_age_h    = ("tle_age_hours",  lambda s: float(np.min(np.abs(s)))),
            max_abs_age_h    = ("tle_age_hours",  lambda s: float(np.max(np.abs(s)))),
        )
        .reset_index()
    )
    summary.to_csv(OUT_DIR / "tle_vs_meme_summary.csv", index=False)

    print("\n=== Summary ===")
    print(summary.to_string(index=False))

    # 4) 繪圖
    rss_html = OUT_DIR / "tle_vs_meme_rss.html"
    rtn_html = OUT_DIR / "tle_vs_meme_rtn.html"
    plot_rss(res_all, res_segmented, rss_html)
    plot_rtn(res_segmented, rtn_html)

    print(f"\nOutputs in {OUT_DIR}/")
    for p in [meme_csv,
              OUT_DIR / "tle_vs_meme_all.csv",
              OUT_DIR / "tle_vs_meme_segmented.csv",
              OUT_DIR / "tle_vs_meme_summary.csv",
              rss_html, rtn_html]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
