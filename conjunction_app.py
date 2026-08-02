#!/usr/bin/env python3
"""
conjunction_app.py
==================
衛星合相（Conjunction）分析 Streamlit App — backend_duckdb.py 的 Streamlit 改寫版

部署模式自動偵測：
  Cloud 模式：讀 data/tle_parquet/latest30day_tle.parquet，顯示預計算 Conjunction 事件 + SGP4 軌道可視化
  Local 模式：連接本地 space_db.duckdb，額外支援即時 Conjunction 計算（run_ca_pipeline）

使用前置作業：
  python prc_maneuver/build_slim_db.py --latest30day
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sgp4.api import Satrec, jday
from sgp4.conveniences import sat_epoch_datetime

# ── 路徑 ─────────────────────────────────────────────────────────────────────
REPO        = Path(__file__).resolve().parent
PARQUET_DIR = REPO / "data" / "tle_parquet"
LATEST30    = PARQUET_DIR / "latest30day_tle.parquet"
META_P      = PARQUET_DIR / "sat_metadata.parquet"
SATBG_P     = PARQUET_DIR / "sat_background.parquet"
CONJ_P      = PARQUET_DIR / "conjunction_events.parquet"
SPACE_DB    = REPO / "space_db.duckdb"

IS_CLOUD = not SPACE_DB.exists()

# ── 地球幾何常數 ──────────────────────────────────────────────────────────────
R_EARTH_KM = 6378.137
F_EARTH    = 1 / 298.257223563
E2         = F_EARTH * (2 - F_EARTH)
MU_KM3_S2  = 398600.4418

# ── 觀測地點預設 ──────────────────────────────────────────────────────────────
OBSERVER_LOCATIONS: dict[str, dict[str, float] | None] = {
    "台北市（25.03°N, 121.57°E）": {"lat": 25.0330, "lon": 121.5654, "alt_km": 0.01},
    "高雄市（22.63°N, 120.30°E）": {"lat": 22.6273, "lon": 120.3014, "alt_km": 0.01},
    "花蓮市（23.97°N, 121.60°E）": {"lat": 23.9712, "lon": 121.6075, "alt_km": 0.01},
    "馬公市（23.57°N, 119.57°E）": {"lat": 23.5703, "lon": 119.5683, "alt_km": 0.01},
    "自定義": None,
}

PASS_COLORS = ["#00e5ff", "#ff9800", "#4caf50", "#e91e63", "#9c27b0", "#ff5722"]
PASS_FILL  = [
    "rgba(0,229,255,0.13)", "rgba(255,152,0,0.13)", "rgba(76,175,80,0.13)",
    "rgba(233,30,99,0.13)", "rgba(156,39,176,0.13)", "rgba(255,87,34,0.13)",
]

# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="衛星 Conjunction 分析", page_icon="🛰", layout="wide")


# ── 資料載入 ──────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_latest30() -> pd.DataFrame:
    if LATEST30.exists():
        try:
            return pd.read_parquet(LATEST30)
        except Exception:
            pass
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_metadata() -> pd.DataFrame:
    if META_P.exists():
        try:
            return pd.read_parquet(META_P)
        except Exception:
            pass
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_satbg() -> pd.DataFrame:
    if SATBG_P.exists():
        try:
            return pd.read_parquet(SATBG_P)
        except Exception:
            pass
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_conj_events() -> pd.DataFrame:
    if CONJ_P.exists():
        try:
            return pd.read_parquet(CONJ_P)
        except Exception:
            pass
    if not IS_CLOUD:
        for db in [SPACE_DB, REPO / "space_db_slim.duckdb"]:
            if db.exists():
                try:
                    con = duckdb.connect(str(db), read_only=True)
                    df = con.execute(
                        "SELECT * FROM conjunction_events ORDER BY tca_utc DESC LIMIT 5000"
                    ).fetchdf()
                    con.close()
                    return df
                except Exception:
                    pass
    return pd.DataFrame()


# ── 座標轉換 ──────────────────────────────────────────────────────────────────

def _gmst_rad(jd: float, fr: float) -> float:
    T = ((jd - 2451545.0) + fr) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr) + 0.000387933 * T ** 2
    return float(np.deg2rad(gmst % 360.0))


def eci_to_llh(r_eci_km: np.ndarray, t_utc: datetime) -> tuple[float, float, float]:
    x, y, z = r_eci_km
    jd, fr = jday(t_utc.year, t_utc.month, t_utc.day,
                  t_utc.hour, t_utc.minute,
                  t_utc.second + t_utc.microsecond * 1e-6)
    gmst = _gmst_rad(jd, fr)
    x_e =  np.cos(gmst) * x + np.sin(gmst) * y
    y_e = -np.sin(gmst) * x + np.cos(gmst) * y
    z_e = z
    lon = np.arctan2(y_e, x_e)
    r   = np.sqrt(x_e ** 2 + y_e ** 2)
    lat = np.arctan2(z_e, r * (1 - E2))
    alt = 0.0
    for _ in range(5):
        sl = np.sin(lat)
        N  = R_EARTH_KM / np.sqrt(1 - E2 * sl ** 2)
        cl = np.cos(lat)
        alt = r / cl - N if abs(cl) > 1e-9 else abs(z_e) / (1.0 - E2) - N
        lat = np.arctan2(z_e, r * (1 - E2 * (N / (N + alt))))
    return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)


def eci_to_ecef(r_eci: np.ndarray, jd: float, fr: float) -> np.ndarray:
    g = _gmst_rad(jd, fr)
    return np.array([
         np.cos(g) * r_eci[0] + np.sin(g) * r_eci[1],
        -np.sin(g) * r_eci[0] + np.cos(g) * r_eci[1],
        r_eci[2],
    ])


def observer_ecef(lat_deg: float, lon_deg: float, alt_km: float = 0.0) -> np.ndarray:
    lat = np.deg2rad(lat_deg)
    lon = np.deg2rad(lon_deg)
    sl, cl = np.sin(lat), np.cos(lat)
    N = R_EARTH_KM / np.sqrt(1 - E2 * sl ** 2)
    return np.array([
        (N + alt_km) * cl * np.cos(lon),
        (N + alt_km) * cl * np.sin(lon),
        (N * (1 - E2) + alt_km) * sl,
    ])


def mean_alt_km(mean_motion_rev_d: float | Any) -> float | None:
    if not mean_motion_rev_d or pd.isna(mean_motion_rev_d):
        return None
    n = float(mean_motion_rev_d) * 2.0 * np.pi / 86400.0
    return (MU_KM3_S2 / n ** 2) ** (1.0 / 3.0) - R_EARTH_KM


# ── SGP4 傳播 ─────────────────────────────────────────────────────────────────

def propagate_orbit(
    line1: str,
    line2: str,
    num_pts: int = 360,
    span_hours: int = 6,
    start_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    SGP4 傳播。start_time 指定傳播起點；若 None 則從 TLE epoch 開始。
    傳回 dict 列表，每項包含 lat/lon/alt_km/ecef/time。
    """
    sat = Satrec.twoline2rv(line1, line2)
    if start_time is not None:
        ref = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
    else:
        ref = sat_epoch_datetime(sat).replace(tzinfo=timezone.utc)

    jd0, fr0 = jday(ref.year, ref.month, ref.day,
                    ref.hour, ref.minute,
                    ref.second + ref.microsecond * 1e-6)
    times_min = np.linspace(0.0, span_hours * 60.0, num_pts)
    jds = np.full(num_pts, jd0)
    frs = fr0 + times_min / 1440.0
    # 處理 fr >= 1 的溢位
    overflow = frs >= 1.0
    jds[overflow] += np.floor(frs[overflow]).astype(int)
    frs[overflow] %= 1.0

    errs, r_ecis, _ = sat.sgp4_array(jds, frs)

    positions: list[dict[str, Any]] = []
    for i, (err, r_eci) in enumerate(zip(errs, r_ecis)):
        if err != 0:
            continue
        t = ref + timedelta(minutes=float(times_min[i]))
        lat, lon, alt_km = eci_to_llh(r_eci, t)
        ecef = eci_to_ecef(r_eci, jds[i], frs[i])
        positions.append({
            "time":    t.isoformat(),
            "_ts":     t.timestamp(),
            "lat":     lat,
            "lon":     lon,
            "alt_km":  alt_km,
            "ecef":    ecef.tolist(),
        })
    return positions


# ── 2D 軌道圖 ─────────────────────────────────────────────────────────────────

def orbit_figure_2d(
    positions: list[dict],
    sat_name: str,
    span_hours: int,
    current_idx: int,
) -> go.Figure:
    lats = [p["lat"] for p in positions]
    lons = [p["lon"] for p in positions]

    # 分段（跨越 ±180° 截斷）
    segs_lat: list[list[float]] = [[]]
    segs_lon: list[list[float]] = [[]]
    for i in range(len(lons)):
        if i > 0 and abs(lons[i] - lons[i - 1]) > 180:
            segs_lat.append([])
            segs_lon.append([])
        segs_lat[-1].append(lats[i])
        segs_lon[-1].append(lons[i])

    fig = go.Figure()
    for idx, (slat, slon) in enumerate(zip(segs_lat, segs_lon)):
        fig.add_trace(go.Scattergeo(
            lat=slat, lon=slon,
            mode="lines",
            line=dict(width=1.8, color="#00e5ff"),
            showlegend=(idx == 0),
            name=sat_name,
        ))

    # 目前位置（紅色標記）
    cp = positions[current_idx]
    fig.add_trace(go.Scattergeo(
        lat=[cp["lat"]], lon=[cp["lon"]],
        mode="markers+text",
        marker=dict(size=14, color="#ff3333", symbol="circle",
                    line=dict(width=2, color="#ffffff")),
        text=["▲ 現在位置"],
        textposition="top right",
        textfont=dict(size=12, color="#ff9999"),
        showlegend=False,
        name="現在位置",
    ))

    fig.update_layout(
        geo=dict(
            showland=True,      landcolor="rgb(45,50,55)",
            showocean=True,     oceancolor="rgb(20,25,40)",
            showcountries=True, countrycolor="rgb(80,80,80)",
            showcoastlines=True, coastlinecolor="rgb(100,100,110)",
            bgcolor="rgb(15,18,28)",
            projection_type="natural earth",
        ),
        margin=dict(l=0, r=0, t=32, b=0),
        paper_bgcolor="rgb(15,18,28)",
        font_color="white",
        height=520,
        title=dict(
            text=f"SGP4 軌道（{span_hours} 小時）— {sat_name}",
            x=0.5,
        ),
    )
    return fig


# ── 3D 軌道圖 ─────────────────────────────────────────────────────────────────

def _earth_sphere() -> go.Surface:
    n = 48
    phi   = np.linspace(0, 2 * np.pi, n)
    theta = np.linspace(0, np.pi, n)
    xe = R_EARTH_KM * np.outer(np.cos(phi), np.sin(theta))
    ye = R_EARTH_KM * np.outer(np.sin(phi), np.sin(theta))
    ze = R_EARTH_KM * np.outer(np.ones(n),  np.cos(theta))
    return go.Surface(
        x=xe, y=ye, z=ze,
        colorscale=[[0, "rgb(10,40,100)"], [0.5, "rgb(15,70,50)"], [1, "rgb(10,40,100)"]],
        showscale=False,
        opacity=0.75,
        name="地球",
        hoverinfo="skip",
    )


def orbit_figure_3d(
    positions: list[dict],
    sat_name: str,
    current_idx: int,
    obs_lat: float | None = None,
    obs_lon: float | None = None,
    obs_label: str = "",
) -> go.Figure:
    xs = [p["ecef"][0] for p in positions]
    ys = [p["ecef"][1] for p in positions]
    zs = [p["ecef"][2] for p in positions]

    fig = go.Figure()

    # 地球球體
    fig.add_trace(_earth_sphere())

    # 軌道軌跡
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(width=3, color="#00e5ff"),
        name=sat_name,
    ))

    # 目前位置
    fig.add_trace(go.Scatter3d(
        x=[xs[current_idx]], y=[ys[current_idx]], z=[zs[current_idx]],
        mode="markers+text",
        marker=dict(size=9, color="#ff3333",
                    line=dict(width=2, color="#ffffff")),
        text=["▲ 現在"],
        textposition="top center",
        textfont=dict(size=11, color="#ff9999"),
        name="現在位置",
    ))

    # 觀測站（可選）
    if obs_lat is not None and obs_lon is not None:
        obs_pos = observer_ecef(obs_lat, obs_lon)
        fig.add_trace(go.Scatter3d(
            x=[obs_pos[0]], y=[obs_pos[1]], z=[obs_pos[2]],
            mode="markers+text",
            marker=dict(size=7, color="#ffcc00",
                        symbol="diamond",
                        line=dict(width=1, color="#ffffff")),
            text=[obs_label or "觀測站"],
            textposition="top center",
            textfont=dict(size=10, color="#ffcc00"),
            name=obs_label or "觀測站",
        ))

    max_r = max(np.sqrt(xs[i]**2 + ys[i]**2 + zs[i]**2) for i in range(len(xs)))
    axis_range = [-max_r * 1.05, max_r * 1.05]
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (km)", range=axis_range,
                       backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)", showgrid=True),
            yaxis=dict(title="Y (km)", range=axis_range,
                       backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)", showgrid=True),
            zaxis=dict(title="Z (km)", range=axis_range,
                       backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)", showgrid=True),
            bgcolor="rgb(8,10,20)",
            aspectmode="cube",
            camera=dict(eye=dict(x=1.4, y=1.4, z=0.8)),
        ),
        paper_bgcolor="rgb(8,10,20)",
        font_color="white",
        height=560,
        margin=dict(l=0, r=0, t=32, b=0),
        title=dict(text=f"3D 軌道（ECEF）— {sat_name}", x=0.5),
        legend=dict(bgcolor="rgba(0,0,0,0.45)", bordercolor="gray", borderwidth=1),
    )
    return fig


# ── 過頂時間計算 ──────────────────────────────────────────────────────────────

def az_to_compass(az_deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(az_deg / 22.5) % 16]


def find_passes(
    line1: str,
    line2: str,
    obs_lat: float,
    obs_lon: float,
    obs_alt_km: float,
    start_utc: datetime,
    duration_hours: float = 72.0,
    min_elev_deg: float = 10.0,
    dt_sec: int = 10,
) -> list[dict]:
    """
    找出衛星在觀測站上方仰角 >= min_elev_deg 的所有過頂事件。
    dt_sec=10 對 25,920 步（72h）使用向量化 SGP4，速度快。
    """
    sat = Satrec.twoline2rv(line1, line2)
    t0  = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
    n   = max(2, int(duration_hours * 3600 / dt_sec))

    # 批次 jd/fr（避免逐步 jday 呼叫）
    jd0, fr0 = jday(t0.year, t0.month, t0.day,
                    t0.hour, t0.minute,
                    t0.second + t0.microsecond * 1e-6)
    steps_frac = np.arange(n) * dt_sec / 86400.0
    frs = fr0 + steps_frac
    jds = np.full(n, jd0) + np.floor(frs).astype(int)
    frs = frs % 1.0

    errs, r_ecis, _ = sat.sgp4_array(jds, frs)
    valid = errs == 0

    # 向量化 ECI→ECEF→仰角
    obs_ecef = observer_ecef(obs_lat, obs_lon, obs_alt_km)
    T_arr    = ((jds - 2451545.0) + frs) / 36525.0
    gmst_arr = np.deg2rad((280.46061837 + 360.98564736629 * (jds - 2451545.0 + frs)
                           + 0.000387933 * T_arr ** 2) % 360.0)

    elevs = np.full(n, -90.0)
    if np.any(valid):
        rv = r_ecis[valid]
        gv = gmst_arr[valid]
        xe = np.cos(gv) * rv[:, 0] + np.sin(gv) * rv[:, 1]
        ye = -np.sin(gv) * rv[:, 0] + np.cos(gv) * rv[:, 1]
        ze = rv[:, 2]
        sat_ecef = np.stack([xe, ye, ze], axis=1) - obs_ecef
        rn = np.linalg.norm(sat_ecef, axis=1, keepdims=True)
        lat_r, lon_r = np.deg2rad(obs_lat), np.deg2rad(obs_lon)
        zenith = np.array([
            np.cos(lat_r) * np.cos(lon_r),
            np.cos(lat_r) * np.sin(lon_r),
            np.sin(lat_r),
        ])
        rho_hat = sat_ecef / np.maximum(rn, 1e-9)
        el_sin  = np.clip(rho_hat @ zenith, -1.0, 1.0)
        elevs[valid] = np.rad2deg(np.arcsin(el_sin))

    # 找連續 above-horizon 區間
    above  = elevs >= min_elev_deg
    passes = []
    i = 0
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            seg_el = elevs[i:j]
            j_max  = int(np.argmax(seg_el))
            t_aos  = t0 + timedelta(seconds=int(i * dt_sec))
            t_tca  = t0 + timedelta(seconds=int((i + j_max) * dt_sec))
            t_los  = t0 + timedelta(seconds=int((j - 1) * dt_sec))

            # 方位角（在 TCA 時刻計算）
            az_tca = 0.0
            idx_tca = i + j_max
            if valid[idx_tca]:
                r_e = r_ecis[idx_tca]
                g   = gmst_arr[idx_tca]
                s_ecef = np.array([
                     np.cos(g) * r_e[0] + np.sin(g) * r_e[1],
                    -np.sin(g) * r_e[0] + np.cos(g) * r_e[1],
                    r_e[2],
                ])
                rho = s_ecef - obs_ecef
                rn_s = np.linalg.norm(rho)
                if rn_s > 0.1:
                    rho_h = rho / rn_s
                    south = np.array([ np.sin(lat_r)*np.cos(lon_r),
                                       np.sin(lat_r)*np.sin(lon_r),
                                      -np.cos(lat_r)])
                    east  = np.array([-np.sin(lon_r), np.cos(lon_r), 0.0])
                    az_tca = float(np.rad2deg(
                        np.arctan2(np.dot(rho_h, east), -np.dot(rho_h, south))
                    )) % 360.0

            passes.append({
                "AOS (UTC)":     t_aos.strftime("%Y-%m-%d %H:%M:%S"),
                "TCA (UTC)":     t_tca.strftime("%Y-%m-%d %H:%M:%S"),
                "LOS (UTC)":     t_los.strftime("%Y-%m-%d %H:%M:%S"),
                "最大仰角 (°)":   round(float(seg_el[j_max]), 1),
                "方位角":         f"{az_tca:.1f}° ({az_to_compass(az_tca)})",
                "持續時間 (s)":   int((j - 1 - i) * dt_sec),
                "_times":        [t0 + timedelta(seconds=int((i + k) * dt_sec))
                                  for k in range(j - i)],
                "_elevs":        seg_el.tolist(),
            })
            i = j
        else:
            i += 1

    return passes


def elevation_timeline_figure(passes: list[dict], sat_name: str) -> go.Figure:
    fig = go.Figure()
    for idx, p in enumerate(passes[:6]):  # 最多顯示 6 條
        color = PASS_COLORS[idx % len(PASS_COLORS)]
        fill  = PASS_FILL[idx % len(PASS_FILL)]
        xs    = [t.strftime("%Y-%m-%d %H:%M") for t in p["_times"]]
        ys    = p["_elevs"]
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="lines",
            name=f"Pass {idx+1}　{p['AOS (UTC)'][11:16]}Z  {p['最大仰角 (°)']:.0f}°",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=fill,
        ))
    fig.update_layout(
        title=dict(text=f"{sat_name} — 仰角時間線", x=0.5),
        xaxis_title="時間（UTC）",
        yaxis_title="仰角（°）",
        yaxis=dict(range=[0, None]),
        height=300,
        margin=dict(t=40, b=36, l=40, r=10),
        paper_bgcolor="rgb(15,18,28)",
        plot_bgcolor="rgb(20,24,36)",
        font_color="white",
        legend=dict(bgcolor="rgba(0,0,0,0)", font_size=11),
    )
    return fig


# ── 側邊欄 ────────────────────────────────────────────────────────────────────

def render_sidebar(df_tle: pd.DataFrame, df_meta: pd.DataFrame) -> int | None:
    with st.sidebar:
        mode_label = "☁️ Cloud 模式（parquet）" if IS_CLOUD else "💾 Local 模式（DuckDB）"
        st.markdown(f"**{mode_label}**")

        norads_available: list[int] = []
        if not df_tle.empty:
            norads_available = sorted(df_tle["norad_id"].dropna().astype(int).unique().tolist())

        st.divider()
        st.subheader("衛星選擇")
        search = st.text_input("搜尋（NORAD ID 或衛星名稱）", placeholder="例：52750 或 TIANHE")

        chosen: int | None = None

        if search.strip().isdigit():
            chosen = int(search.strip())
        elif search.strip() and not df_meta.empty:
            hits = df_meta[df_meta["name_en"].str.contains(search.strip(), case=False, na=False)]
            if not hits.empty:
                chosen = int(hits.iloc[0]["norad_id"])
            else:
                st.caption("找不到匹配衛星名稱。")

        if chosen is None:
            if norads_available:
                chosen = st.selectbox(
                    "或從清單選擇",
                    norads_available,
                    format_func=lambda n: f"NORAD {n}",
                )
            else:
                st.info("無 TLE 資料。請先執行：\n```\npython prc_maneuver/build_slim_db.py --latest30day\n```")

        st.divider()
        st.markdown(f"TLE 資料：**{len(norads_available):,}** 顆衛星")
        if not df_tle.empty and "epoch_utc" in df_tle.columns:
            max_ep = pd.to_datetime(df_tle["epoch_utc"]).max()
            st.caption(f"最新 epoch：{max_ep.strftime('%Y-%m-%d')}")

    return chosen


# ── Tab 1: 衛星資訊 ────────────────────────────────────────────────────────────

def tab_sat_info(norad: int, df_tle: pd.DataFrame, df_meta: pd.DataFrame, df_bg: pd.DataFrame) -> None:
    if df_tle.empty:
        st.info("尚無 TLE 資料。請先執行 `build_slim_db.py --latest30day`。")
        return

    tle_row = df_tle[df_tle["norad_id"] == norad]
    if tle_row.empty:
        st.warning(f"NORAD {norad} 不在 latest30day_tle.parquet 中（可能已離軌或超過 30 天無更新）。")
        return

    r = tle_row.iloc[0]
    sat_name  = str(r.get("object_name") or f"NORAD {norad}")
    epoch_dt  = pd.to_datetime(r["epoch_utc"])
    mm        = r.get("mean_motion")
    inc       = r.get("inclination_deg")
    ecc       = r.get("eccentricity")
    alt       = mean_alt_km(mm)
    period    = 1440.0 / float(mm) if pd.notna(mm) and float(mm) > 0 else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("衛星名稱", sat_name)
    c2.metric("NORAD ID", norad)
    c3.metric("TLE Epoch", epoch_dt.strftime("%Y-%m-%d %H:%M UTC"))
    c4.metric("傾角 i", f"{inc:.3f}°" if pd.notna(inc) else "—")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("平均高度", f"{alt:.0f} km"         if alt is not None else "—")
    c6.metric("軌道週期", f"{period:.1f} min"     if period else "—")
    c7.metric("離心率 e", f"{ecc:.6f}"            if pd.notna(ecc) else "—")
    c8.metric("平均運動", f"{mm:.6f} rev/d"       if pd.notna(mm) else "—")

    if not df_meta.empty:
        meta_row = df_meta[df_meta["norad_id"] == norad]
        if not meta_row.empty:
            m = meta_row.iloc[0]
            with st.expander("N2YO 元資料", expanded=False):
                mc1, mc2 = st.columns(2)
                with mc1:
                    st.markdown(f"**國際代號**　{m.get('intl_code') or '—'}")
                    st.markdown(f"**發射日期**　{m.get('launch_date') or '—'}")
                    st.markdown(f"**發射場**　{m.get('launch_site') or '—'}")
                with mc2:
                    st.markdown(f"**近地點**　{m.get('perigee_km') or '—'} km")
                    st.markdown(f"**遠地點**　{m.get('apogee_km') or '—'} km")
                    st.markdown(f"**RCS**　{m.get('rcs_text') or '—'}")
                desc = m.get("website_desc_en")
                if desc and str(desc) not in ("nan", "None", ""):
                    st.caption(str(desc)[:500])

    if not df_bg.empty:
        bg_row = df_bg[df_bg["norad_id"] == norad]
        if not bg_row.empty:
            b = bg_row.iloc[0]
            quality = b.get("data_quality", "stub")
            badge = {"researched": "✅ researched", "inferred": "⚠️ inferred"}.get(quality, f"🔲 {quality}")
            with st.container(border=True):
                st.markdown(f"#### 📚 任務背景　{badge}")
                bc1, bc2 = st.columns(2)
                with bc1:
                    st.markdown(f"**星座**　{b.get('constellation') or '—'}")
                    st.markdown(f"**任務類型**　{b.get('mission_type') or '—'}")
                    lv = b.get("launch_vehicle")
                    st.markdown(f"**運載火箭**　{lv if lv and str(lv) not in ('nan','None') else '—'}")
                with bc2:
                    mass = b.get("mass_kg")
                    st.markdown(f"**質量**　{f'{float(mass):.0f} kg' if pd.notna(mass) else '—'}")
                    st.markdown(f"**運營商**　{b.get('operator_org') or '—'}")
                reason = b.get("maneuver_reason")
                if reason and str(reason) not in ("nan", "None", ""):
                    st.markdown(f"**機動原因**：{reason}")
                desc_zh = b.get("desc_zh")
                if desc_zh and str(desc_zh) not in ("nan", "None", ""):
                    with st.expander("任務背景詳情（中文）"):
                        st.write(str(desc_zh))

    with st.expander("TLE 原始字串"):
        l1 = str(r.get("line1", ""))
        l2 = str(r.get("line2", ""))
        st.code(f"{sat_name}\n{l1}\n{l2}", language=None)


# ── Tab 2: 軌道可視化（含 2D / 3D 子頁面）───────────────────────────────────

def tab_orbit(norad: int, df_tle: pd.DataFrame) -> None:
    if df_tle.empty:
        st.info("無 TLE 資料。請先執行 `build_slim_db.py --latest30day`。")
        return

    tle_row = df_tle[df_tle["norad_id"] == norad]
    if tle_row.empty:
        st.warning(f"找不到 NORAD {norad} 的 TLE。")
        return

    r        = tle_row.iloc[0]
    line1    = str(r["line1"])
    line2    = str(r["line2"])
    sat_name = str(r.get("object_name") or f"NORAD {norad}")

    span_h = st.select_slider(
        "軌跡時間（小時，以目前時刻為中心）",
        options=[1, 3, 6, 12, 24],
        value=6,
    )
    num_pts = max(180, span_h * 60)  # 每分鐘一個點

    # 以目前時刻為中心（前半 + 後半）
    now       = datetime.now(timezone.utc)
    start_t   = now - timedelta(hours=span_h / 2)

    with st.spinner("SGP4 傳播中…"):
        positions = propagate_orbit(line1, line2, num_pts=num_pts,
                                    span_hours=span_h, start_time=start_t)

    if not positions:
        st.error("SGP4 傳播失敗，TLE 可能已過期或格式有誤。")
        return

    # 找最接近目前時刻的點作為「現在位置」
    now_ts = now.timestamp()
    current_idx = min(range(len(positions)),
                      key=lambda i: abs(positions[i]["_ts"] - now_ts))

    # ── 2D / 3D 子頁面 ────────────────────────────────────────────────────────
    sub = st.tabs(["🗺 2D 地圖", "🌐 3D 地球"])

    with sub[0]:
        fig2d = orbit_figure_2d(positions, sat_name, span_h, current_idx)
        st.plotly_chart(fig2d, use_container_width=True)

    with sub[1]:
        fig3d = orbit_figure_3d(positions, sat_name, current_idx)
        st.plotly_chart(fig3d, use_container_width=True)

    # 軌道參數摘要
    inc  = r.get("inclination_deg")
    ecc  = r.get("eccentricity")
    raan = r.get("raan_deg")
    mm   = r.get("mean_motion")
    alt  = mean_alt_km(mm)

    kc = st.columns(5)
    kc[0].metric("傾角 i",       f"{inc:.3f}°"         if pd.notna(inc)  else "—")
    kc[1].metric("離心率 e",     f"{ecc:.6f}"           if pd.notna(ecc)  else "—")
    kc[2].metric("升交點赤經 Ω", f"{raan:.3f}°"         if pd.notna(raan) else "—")
    kc[3].metric("平均運動",     f"{mm:.6f} rev/d"      if pd.notna(mm)   else "—")
    kc[4].metric("平均高度",     f"{alt:.0f} km"        if alt is not None else "—")

    epoch = pd.to_datetime(r["epoch_utc"])
    cp    = positions[current_idx]
    st.caption(
        f"TLE Epoch：{epoch.strftime('%Y-%m-%d %H:%M UTC')}　"
        f"｜　目前位置：{cp['lat']:.3f}°N, {cp['lon']:.3f}°E, "
        f"高度 {cp['alt_km']:.1f} km"
    )


# ── Tab 3: Conjunction 事件 ────────────────────────────────────────────────────

def tab_conjunction(norad: int | None, df_conj: pd.DataFrame) -> None:
    if IS_CLOUD:
        st.info("☁️ Cloud 模式：顯示預計算 Conjunction 事件（由 `build_slim_db.py --latest30day` 匯出）。")
    else:
        st.info("💾 Local 模式：顯示資料庫中已儲存的 Conjunction 事件。即時計算請至「⚡ 即時合相」分頁。")

    if df_conj.empty:
        st.warning(
            "尚無 Conjunction 事件資料。\n\n"
            "請先執行合相管線，或執行：\n"
            "```\npython prc_maneuver/build_slim_db.py --latest30day\n```"
        )
        return

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        filter_norad = st.checkbox("只顯示目前衛星", value=(norad is not None), disabled=(norad is None))
    with fc2:
        risk_opts = ["全部"]
        if "risk_label" in df_conj.columns:
            risk_opts += sorted(df_conj["risk_label"].dropna().unique().tolist())
        risk_filter = st.selectbox("風險等級", risk_opts)
    with fc3:
        max_dist = st.slider("最大接近距離 (km)", 0.1, 100.0, 50.0, step=0.1)

    filtered = df_conj.copy()
    if filter_norad and norad is not None and "primary_norad" in filtered.columns:
        filtered = filtered[filtered["primary_norad"] == norad]
    if risk_filter != "全部" and "risk_label" in filtered.columns:
        filtered = filtered[filtered["risk_label"] == risk_filter]
    if "miss_distance_km" in filtered.columns:
        filtered = filtered[filtered["miss_distance_km"] <= max_dist]

    st.markdown(f"顯示 **{len(filtered):,}** 筆（共 {len(df_conj):,} 筆）Conjunction 事件")

    with st.expander("📖 CDM 操作門檻說明", expanded=False):
        st.markdown("""
**Pc（碰撞機率）操作門檻（參照 CCSDS CDM 標準）**

| 風險等級 | Pc 範圍 | 典型處置 |
|---------|--------|---------|
| 🔴 HIGH | Pc ≥ 1×10⁻³ | 多數任務規程要求執行 COLA 避碰機動 |
| 🟠 ELEVATED | 1×10⁻⁴ ≤ Pc < 1×10⁻³ | 機動評估，視情況執行避碰 |
| 🟡 MEDIUM | 1×10⁻⁵ ≤ Pc < 1×10⁻⁴ | 分析員複核，評估事件趨勢 |
| 🟢 LOW | Pc < 1×10⁻⁵ | 持續監控，無需立即行動 |

> **miss_distance ≠ 碰撞風險全貌**：miss distance 反映幾何接近程度，Pc 整合了幾何距離**與**位置不確定性。
> 單獨看 miss distance 不足以完整反映風險——miss distance 大但 covariance 大時，Pc 仍可能不可忽視。
>
> **covariance_method = DEFAULT**：本系統使用 TLE 統計 pseudo-covariance（固定 σR=1 km, σT=5 km, σN=3 km），
> 非實際軌道決定估算。Pc 可能被高估或低估，決策時應結合 miss distance 互補判斷。
""")

    if filtered.empty:
        st.info("無符合條件的事件。")
        return

    display_cols = [c for c in
                    ["primary_norad", "secondary_norad", "tca_utc",
                     "miss_distance_km", "relative_speed_km_s",
                     "pc", "pc_method", "covariance_method",
                     "screen_volume_frame", "risk_label"]
                    if c in filtered.columns]
    sort_col = "tca_utc" if "tca_utc" in display_cols else display_cols[0]
    st.dataframe(
        filtered[display_cols].sort_values(sort_col, ascending=False),
        use_container_width=True,
        height=420,
    )

    if "pc" in filtered.columns and len(filtered) > 1:
        valid_pc = filtered["pc"].replace(0, np.nan).dropna()
        if len(valid_pc) > 0:
            fig_pc = go.Figure(go.Histogram(
                x=np.log10(valid_pc),
                nbinsx=30,
                marker_color="#00e5ff",
                name="log₁₀(Pc)",
            ))
            # CDM 操作門檻垂直標線
            for log_thr, label, color in [
                (-3, "HIGH ≥1e-3", "#ff4444"),
                (-4, "ELEVATED ≥1e-4", "#ff9800"),
                (-5, "MEDIUM ≥1e-5", "#ffcc00"),
            ]:
                fig_pc.add_vline(
                    x=log_thr,
                    line_dash="dash",
                    line_color=color,
                    annotation_text=label,
                    annotation_position="top right",
                    annotation_font_color=color,
                    annotation_font_size=11,
                )
            fig_pc.update_layout(
                title="Pc 分布（log₁₀ 尺度）— 垂直線為 CDM 操作門檻",
                xaxis_title="log₁₀(Pc)",
                yaxis_title="事件數",
                height=280,
                margin=dict(t=44, b=24, l=0, r=0),
                paper_bgcolor="rgb(15,18,28)",
                plot_bgcolor="rgb(20,24,36)",
                font_color="white",
            )
            st.plotly_chart(fig_pc, use_container_width=True)


# ── Tab 4: 過頂時間 ────────────────────────────────────────────────────────────

def tab_pass_time(norad: int | None, df_tle: pd.DataFrame) -> None:
    if norad is None:
        st.info("請在左側選擇衛星。")
        return
    if df_tle.empty:
        st.info("無 TLE 資料。請先執行 `build_slim_db.py --latest30day`。")
        return

    tle_row = df_tle[df_tle["norad_id"] == norad]
    if tle_row.empty:
        st.warning(f"找不到 NORAD {norad} 的 TLE。")
        return

    r        = tle_row.iloc[0]
    line1    = str(r["line1"])
    line2    = str(r["line2"])
    sat_name = str(r.get("object_name") or f"NORAD {norad}")

    st.subheader(f"🔭 {sat_name}（NORAD {norad}）過頂時間預測")

    col1, col2 = st.columns(2)
    with col1:
        obs_choice = st.selectbox("觀測地點", list(OBSERVER_LOCATIONS.keys()))
        if obs_choice == "自定義":
            obs_lat = st.number_input("緯度（°N）", value=25.0330,
                                      min_value=-90.0, max_value=90.0, step=0.0001, format="%.4f")
            obs_lon = st.number_input("經度（°E）", value=121.5654,
                                      min_value=-180.0, max_value=180.0, step=0.0001, format="%.4f")
            obs_label = "自定義觀測站"
        else:
            loc = OBSERVER_LOCATIONS[obs_choice]
            assert loc is not None
            obs_lat   = loc["lat"]
            obs_lon   = loc["lon"]
            obs_label = obs_choice.split("（")[0]

        obs_alt_km: float = 0.01

    with col2:
        duration_h = st.select_slider("預測時間跨度（小時）",
                                      options=[24, 48, 72, 120, 168], value=72)
        min_elev   = st.slider("最小仰角（°）", 0, 45, 10)
        start_now  = st.checkbox("從現在開始", value=True)
        if start_now:
            start_utc = datetime.now(timezone.utc)
        else:
            sd = st.date_input("起始日期（UTC）", value=datetime.now(timezone.utc).date())
            start_utc = datetime(sd.year, sd.month, sd.day, tzinfo=timezone.utc)

    st.markdown(
        f"觀測地點：**{obs_label}**　（{obs_lat:.4f}°N, {obs_lon:.4f}°E）　"
        f"｜　分析：接下來 **{duration_h}** 小時　｜　最小仰角 **{min_elev}°**"
    )

    with st.spinner(f"計算過頂事件（{duration_h}h × 10s 解析度）…"):
        passes = find_passes(
            line1, line2,
            obs_lat=obs_lat, obs_lon=obs_lon, obs_alt_km=obs_alt_km,
            start_utc=start_utc,
            duration_hours=float(duration_h),
            min_elev_deg=float(min_elev),
            dt_sec=10,
        )

    if not passes:
        st.info(f"在未來 {duration_h} 小時內，仰角 ≥ {min_elev}° 的過頂事件為零。")
        return

    st.success(f"找到 **{len(passes)}** 次過頂（仰角 ≥ {min_elev}°）")

    display_cols = ["AOS (UTC)", "TCA (UTC)", "LOS (UTC)", "最大仰角 (°)", "方位角", "持續時間 (s)"]
    df_passes = pd.DataFrame([{k: v for k, v in p.items() if not k.startswith("_")}
                               for p in passes])
    st.dataframe(df_passes[display_cols], use_container_width=True,
                 height=min(420, 52 + 36 * len(df_passes)))

    # 仰角時間線圖（最多前 6 次）
    if passes:
        fig_el = elevation_timeline_figure(passes, sat_name)
        st.plotly_chart(fig_el, use_container_width=True)

    # 3D 地球（標示衛星目前位置 + 觀測站）
    with st.expander("3D 地球視角（衛星目前位置 + 觀測站）", expanded=False):
        now      = datetime.now(timezone.utc)
        start_3d = now - timedelta(hours=3)
        with st.spinner("SGP4 傳播中…"):
            pos3d = propagate_orbit(line1, line2, num_pts=180, span_hours=6, start_time=start_3d)
        if pos3d:
            idx3d = min(range(len(pos3d)),
                        key=lambda i: abs(pos3d[i]["_ts"] - now.timestamp()))
            fig3d = orbit_figure_3d(pos3d, sat_name, idx3d,
                                    obs_lat=obs_lat, obs_lon=obs_lon,
                                    obs_label=obs_label)
            st.plotly_chart(fig3d, use_container_width=True)


# ── Tab 5: 即時合相（本地限定）────────────────────────────────────────────────

def tab_realtime_conjunction(norad: int | None) -> None:
    if IS_CLOUD:
        st.warning(
            "即時 Conjunction 計算需要本地 `space_db.duckdb`，Streamlit Cloud 上不支援。\n\n"
            "本地執行：`streamlit run conjunction_app.py`"
        )
        return

    if norad is None:
        st.info("請先在左側選擇衛星。")
        return

    st.subheader(f"NORAD {norad} — 即時 Conjunction 分析（v2 kdtree）")

    col1, col2 = st.columns(2)
    with col1:
        time_start_date = st.date_input("分析起始日期（UTC）",
                                         value=datetime.now(timezone.utc).date())
        time_span_h  = st.slider("分析時間跨度（小時）", 6, 72, 24)
        miss_thr     = st.slider("接近距離門檻（km）", 1.0, 200.0, 50.0)
    with col2:
        max_inc_deg  = st.slider("最大傾角差 Δi（°）", 1.0, 15.0, 5.0)
        prefilter_km = st.slider("軌道高度預篩範圍（km）", 50.0, 500.0, 200.0)
        n_mc         = st.select_slider("Monte Carlo 樣本數",
                                        options=[1000, 5000, 10000, 20000], value=5000)

    if not st.button("▶ 開始計算", type="primary"):
        return

    try:
        from ca_pipeline_kdtree_v2_fixed import run_ca_pipeline
    except ImportError:
        st.error("找不到 `ca_pipeline_kdtree_v2_fixed.py`，請確認檔案位於 repo 根目錄。")
        return

    time_start = datetime(
        time_start_date.year, time_start_date.month, time_start_date.day,
        tzinfo=timezone.utc,
    )
    with st.spinner("計算中（可能需要 30-60 秒）…"):
        try:
            result = run_ca_pipeline(
                db_path=str(SPACE_DB),
                target_norad_id=norad,
                time_start=time_start,
                time_span_hours=time_span_h,
                miss_threshold_km=miss_thr,
                prefilter_padding_km=prefilter_km,
                max_delta_inc_deg=max_inc_deg,
                n_mc=n_mc,
                Rc_km=0.01,
            )
        except Exception as e:
            st.error(f"計算失敗：{e}")
            return

    if result.get("status") != "ok":
        st.error(f"管線錯誤：{result}")
        return

    events  = result.get("events", [])
    summary = result.get("summary", {})
    timing  = result.get("timing", {})

    kc = st.columns(4)
    kc[0].metric("候選衛星（預篩後）", summary.get("prefilter_candidate_count", "—"))
    kc[1].metric("粗命中",             summary.get("coarse_hit_count", "—"))
    kc[2].metric("Conjunction 事件",   summary.get("event_count", "—"))
    kc[3].metric("耗時",               f"{timing.get('elapsed_sec', 0):.1f} s")

    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True)
    else:
        st.success(f"NORAD {norad}：分析時段內無 Conjunction 事件。")

    if result.get("debug"):
        with st.expander("Debug log"):
            st.text("\n".join(result["debug"]))


# ── Tab 6: RPO / Rendezvous 相對運動（本地限定）──────────────────────────────

@st.cache_data(show_spinner=False)
def _cached_pair(db: str, primary: int, secondary: int,
                 start, end, step_min: float) -> dict:
    from conjunction_viz import compute_pair_series
    return compute_pair_series(db, primary, secondary,
                               start=start, end=end, step_min=step_min)


def _rpo_fig3d(rel: list, comp: tuple, obs_name: str, other_name: str,
               color_by: str = "time") -> go.Figure:
    """從 obs 物體的 LVLH 座標系看 other 物體的 3D 相對軌跡（時序或距離著色）。"""
    x = [p[comp[0]] for p in rel]; y = [p[comp[1]] for p in rel]; z = [p[comp[2]] for p in rel]
    if color_by == "range":
        cvals = [p["d"] for p in rel]; cbar = "range (km)"; cscale = "Turbo_r"
    else:
        cvals = list(range(len(rel))); cbar = "時序"; cscale = "Turbo"
    txt = [f"{p['t'][5:16]}Z<br>R={p[comp[0]]} T={p[comp[1]]} N={p[comp[2]]} km<br>range={p['d']} km"
           for p in rel]
    fig = go.Figure()
    fig.add_trace(go.Scatter3d(
        x=x, y=y, z=z, mode="markers+lines",
        marker=dict(size=2.6, color=cvals, colorscale=cscale, showscale=True,
                    colorbar=dict(title=cbar, thickness=10, len=.7)),
        line=dict(color="rgba(150,155,170,0.35)", width=2),
        text=txt, hoverinfo="text", name=other_name))
    fig.add_trace(go.Scatter3d(
        x=[0], y=[0], z=[0], mode="markers+text",
        marker=dict(size=6, color="#ff5c4e", symbol="diamond"),
        text=[f"▲ {obs_name}"], textposition="top center",
        textfont=dict(color="#ff9a90", size=11), name=obs_name, hoverinfo="name"))
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="R 徑向 (km)", backgroundcolor="rgb(8,10,20)", gridcolor="rgb(40,44,60)"),
            yaxis=dict(title="T 順行 (km)", backgroundcolor="rgb(8,10,20)", gridcolor="rgb(40,44,60)"),
            zaxis=dict(title="N 法向 (km)", backgroundcolor="rgb(8,10,20)", gridcolor="rgb(40,44,60)"),
            bgcolor="rgb(8,10,20)", camera=dict(eye=dict(x=1.5, y=1.5, z=.9))),
        paper_bgcolor="rgb(8,10,20)", font_color="white", height=460,
        margin=dict(l=0, r=0, t=34, b=0),
        title=dict(text=f"從 {obs_name} 視角看 {other_name}（LVLH）", x=0.5),
        showlegend=False)
    return fig


def _pair_inputs(prefix: str, default_primary: int):
    """共用的 primary/secondary/窗 輸入元件（不同分頁用不同 key 前綴避免衝突）。"""
    c1, c2, c3 = st.columns(3)
    primary = int(c1.number_input("Primary NORAD", value=default_primary, step=1,
                                  format="%d", key=prefix + "p"))
    secondary = int(c2.number_input("Secondary NORAD", value=59884, step=1,
                                    format="%d", key=prefix + "s"))
    step_min = float(c3.select_slider("取樣間隔（分）", options=[10, 15, 30, 60, 120],
                                      value=30, key=prefix + "step"))
    c4, c5 = st.columns(2)
    start = c4.text_input("起始日期 UTC（YYYY-MM-DD，空=自動重疊窗）", value="",
                          key=prefix + "start").strip()
    end = c5.text_input("結束日期 UTC（空=自動）", value="", key=prefix + "end").strip()
    return primary, secondary, step_min, start, end


def tab_rpo(norad: int | None, df_tle: pd.DataFrame) -> None:
    if IS_CLOUD:
        st.warning("RPO / Rendezvous 分析需本地 `space_db.duckdb`（即時 SGP4 傳播），Cloud 不支援。\n\n"
                   "本地執行：`streamlit run conjunction_app.py`")
        return
    st.subheader("🔗 RPO / Rendezvous 相對運動分析")
    st.caption("任兩顆衛星：相對距離、LVLH 相對運動、接近率、雙高度。"
               "3D 立體視角請見「🧊 3D 相對視角」分頁。")

    primary, secondary, step_min, start, end = _pair_inputs("rpo_", int(norad) if norad else 58573)

    if not st.button("▶ 計算相對運動", type="primary"):
        return
    try:
        with st.spinner("SGP4 逐時刻傳播中…"):
            data = _cached_pair(str(SPACE_DB), primary, secondary,
                                start or None, end or None, step_min)
    except Exception as e:
        st.error(f"計算失敗：{e}")
        return

    rel = data["rel"]; s = data["summary"]; m = data["meta"]
    tx = [pd.to_datetime(p["t"]) for p in rel]

    k = st.columns(5)
    k[0].metric("最接近", f"{s['d_min']:.2f} km" if s['d_min'] < 10 else f"{s['d_min']:.0f} km")
    k[1].metric("結束間距", f"{s['d_last']:.0f} km")
    k[2].metric("取樣點", f"{s['n']} @ {s['step_min']:.0f}m")
    k[3].metric(f"{m['primName'][:12]} Δalt", f"{s['altP_span']:.0f} km")
    k[4].metric(f"{m['secName'][:12]} Δalt", f"{s['altS_span']:.0f} km")

    # ① 相對距離
    logy = st.radio("距離軸", ["log", "linear"], horizontal=True, index=0) == "log"
    f1 = go.Figure(go.Scatter(x=tx, y=[p["d"] for p in rel], mode="lines+markers",
                              line=dict(color="#f2a73b", width=1.6), marker=dict(size=3),
                              name="range"))
    for e in m.get("events", []):
        f1.add_vline(x=pd.to_datetime(e["t"]).timestamp() * 1000, line_dash="dash",
                     line_color="#ff5c4e", annotation_text=e["label"])
    f1.update_layout(title="① 相對距離 vs 時間", yaxis_title="range (km)",
                     yaxis_type="log" if logy else "linear", height=320,
                     paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)",
                     font_color="white", margin=dict(t=40, b=30, l=10, r=10))
    st.plotly_chart(f1, use_container_width=True)

    cc = st.columns(2)
    # ② LVLH 2D（primary 視角，時間著色）
    f2 = go.Figure(go.Scatter(x=[p["T"] for p in rel], y=[p["R"] for p in rel],
                              mode="markers", marker=dict(size=4, color=list(range(len(rel))),
                              colorscale="Turbo", showscale=False),
                              text=[p["t"][5:16] for p in rel], name="secondary"))
    f2.add_trace(go.Scatter(x=[0], y=[0], mode="markers", marker=dict(size=9, color="#ff5c4e"),
                            name="ref"))
    f2.update_layout(title="② LVLH 相對運動（T–R，時間著色）", xaxis_title="along-track T (km)",
                     yaxis_title="radial R (km)", height=340, showlegend=False,
                     paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)",
                     font_color="white", margin=dict(t=40, b=30, l=10, r=10))
    cc[0].plotly_chart(f2, use_container_width=True)
    # ③ range-rate
    f3 = go.Figure(go.Scatter(x=tx, y=[p["rr"] for p in rel], mode="lines",
                              line=dict(color="#35c6f4", width=1.5), name="ṙ"))
    f3.add_hline(y=0, line_color="rgba(255,255,255,0.25)")
    f3.update_layout(title="③ 接近率 vs 時間（− 接近 / + 遠離）", yaxis_title="range-rate (km/s)",
                     height=340, paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)",
                     font_color="white", margin=dict(t=40, b=30, l=10, r=10))
    cc[1].plotly_chart(f3, use_container_width=True)

    # ④ 雙高度
    f4 = go.Figure()
    f4.add_trace(go.Scatter(x=[pd.to_datetime(p["t"]) for p in data["altP"]],
                            y=[p["a"] for p in data["altP"]], mode="lines+markers",
                            line=dict(color="#f2a73b", width=1.4), marker=dict(size=2),
                            name=f"{m['primId']} {m['primName']}"))
    f4.add_trace(go.Scatter(x=[pd.to_datetime(p["t"]) for p in data["altS"]],
                            y=[p["a"] for p in data["altS"]], mode="lines+markers",
                            line=dict(color="#35c6f4", width=1.4), marker=dict(size=2),
                            name=f"{m['secId']} {m['secName']}"))
    f4.update_layout(title="④ 平均高度（a−R⊕）— 兩物體", yaxis_title="altitude (km)", height=320,
                     paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)", font_color="white",
                     margin=dict(t=40, b=30, l=10, r=10),
                     legend=dict(bgcolor="rgba(0,0,0,0.3)", font_size=11))
    st.plotly_chart(f4, use_container_width=True)

    st.info("🧊 三維立體視角（可旋轉、從各物體自身角度看對方）請切換至「🧊 3D 相對視角」分頁。")


# ── Tab 7: 3D 相對視角（本地限定）────────────────────────────────────────────

def tab_rpo_3d(norad: int | None) -> None:
    if IS_CLOUD:
        st.warning("3D 相對視角需本地 `space_db.duckdb`（即時 SGP4 傳播），Cloud 不支援。")
        return
    st.subheader("🧊 3D 相對視角 — 從各物體角度看對方")
    st.caption("每張圖以**觀測物體自身**為原點（紅鑽），顯示對方在其 LVLH（R 徑向／T 順行／N 法向）"
               "座標系的三維相對軌跡；可拖曳旋轉。沿軌 T 主導＝沿軌分離；R/N 小＝近共面。")

    primary, secondary, step_min, start, end = _pair_inputs("r3d_", int(norad) if norad else 58573)
    cby = st.radio("著色", ["時序", "距離"], horizontal=True, index=0)
    color_by = "range" if cby == "距離" else "time"

    if not st.button("▶ 計算 3D 視角", type="primary", key="r3d_go"):
        return
    try:
        with st.spinner("SGP4 逐時刻傳播中…"):
            data = _cached_pair(str(SPACE_DB), primary, secondary,
                                start or None, end or None, step_min)
    except Exception as e:
        st.error(f"計算失敗：{e}")
        return

    rel = data["rel"]; s = data["summary"]; m = data["meta"]
    k = st.columns(4)
    k[0].metric("Pair", f"{m['primId']} × {m['secId']}")
    k[1].metric("最接近", f"{s['d_min']:.2f} km" if s['d_min'] < 10 else f"{s['d_min']:.0f} km")
    k[2].metric("結束間距", f"{s['d_last']:.0f} km")
    k[3].metric("取樣點", f"{s['n']} @ {s['step_min']:.0f}m")

    d3 = st.columns(2)
    d3[0].plotly_chart(_rpo_fig3d(rel, ("R", "T", "N"), m["primName"], m["secName"], color_by),
                       use_container_width=True)
    d3[1].plotly_chart(_rpo_fig3d(rel, ("R2", "T2", "N2"), m["secName"], m["primName"], color_by),
                       use_container_width=True)


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main() -> None:
    df_tle  = load_latest30()
    df_meta = load_metadata()
    df_bg   = load_satbg()
    df_conj = load_conj_events()

    chosen = render_sidebar(df_tle, df_meta)

    tabs = st.tabs([
        "🛰 衛星資訊",
        "🌍 軌道可視化",
        "⚠️ Conjunction",
        "🔭 過頂時間",
        "⚡ 即時合相",
        "🔗 RPO/Rendezvous",
        "🧊 3D 相對視角",
    ])

    with tabs[0]:
        if chosen is not None:
            tab_sat_info(chosen, df_tle, df_meta, df_bg)
        else:
            st.info("請在左側選擇或搜尋衛星。")

    with tabs[1]:
        if chosen is not None:
            tab_orbit(chosen, df_tle)
        else:
            st.info("請在左側選擇或搜尋衛星。")

    with tabs[2]:
        tab_conjunction(chosen, df_conj)

    with tabs[3]:
        tab_pass_time(chosen, df_tle)

    with tabs[4]:
        tab_realtime_conjunction(chosen)

    with tabs[5]:
        tab_rpo(chosen, df_tle)

    with tabs[6]:
        tab_rpo_3d(chosen)


if __name__ == "__main__":
    main()
