#!/usr/bin/env python3
"""
conjunction_app/app.py
======================
衛星 Conjunction 分析 Streamlit App

目錄結構：
  conjunction_app/
  ├── app.py          ← 本檔
  ├── requirements.txt
  └── .streamlit/config.toml

資料來源（相對於 repo 根目錄）：
  data/tle_parquet/latest30day_tle.parquet   ← build_slim_db.py --latest30day 產生
  data/tle_parquet/sat_metadata.parquet
  data/tle_parquet/sat_background.parquet
  data/tle_parquet/conjunction_events.parquet
  space_db.duckdb                            ← 本地模式（即時合相計算）

啟動：
  streamlit run conjunction_app/app.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── 路徑設定（本檔在 conjunction_app/ 子目錄）─────────────────────────────────
_HERE = Path(__file__).resolve().parent       # .../conjunction_app/
REPO  = _HERE.parent                          # repo 根目錄

# 讓 repo 根目錄下的模組（ca_pipeline_kdtree_v2_fixed 等）可被 import
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sgp4.api import Satrec, jday
from sgp4.conveniences import sat_epoch_datetime

# ── Parquet / DB 路徑 ─────────────────────────────────────────────────────────
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
PASS_FILL   = [
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
                    df  = con.execute(
                        "SELECT * FROM conjunction_events ORDER BY tca_utc DESC LIMIT 5000"
                    ).fetchdf()
                    con.close()
                    return df
                except Exception:
                    pass
    return pd.DataFrame()


# ── 座標轉換 ──────────────────────────────────────────────────────────────────

def _gmst_rad(jd: float, fr: float) -> float:
    T    = ((jd - 2451545.0) + fr) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr) + 0.000387933 * T**2
    return float(np.deg2rad(gmst % 360.0))


def eci_to_llh(r_eci: np.ndarray, t_utc: datetime) -> tuple[float, float, float]:
    x, y, z = r_eci
    jd, fr  = jday(t_utc.year, t_utc.month, t_utc.day,
                   t_utc.hour, t_utc.minute,
                   t_utc.second + t_utc.microsecond * 1e-6)
    g  = _gmst_rad(jd, fr)
    xe =  np.cos(g) * x + np.sin(g) * y
    ye = -np.sin(g) * x + np.cos(g) * y
    ze = z
    lon = np.arctan2(ye, xe)
    r   = np.sqrt(xe**2 + ye**2)
    lat = np.arctan2(ze, r * (1 - E2))
    alt = 0.0
    for _ in range(5):
        sl  = np.sin(lat)
        N   = R_EARTH_KM / np.sqrt(1 - E2 * sl**2)
        cl  = np.cos(lat)
        alt = r / cl - N if abs(cl) > 1e-9 else abs(ze) / (1.0 - E2) - N
        lat = np.arctan2(ze, r * (1 - E2 * (N / (N + alt))))
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
    N = R_EARTH_KM / np.sqrt(1 - E2 * sl**2)
    return np.array([
        (N + alt_km) * cl * np.cos(lon),
        (N + alt_km) * cl * np.sin(lon),
        (N * (1 - E2) + alt_km) * sl,
    ])


def mean_alt_km(mm: Any) -> float | None:
    if not mm or pd.isna(mm):
        return None
    n = float(mm) * 2.0 * np.pi / 86400.0
    return (MU_KM3_S2 / n**2) ** (1.0 / 3.0) - R_EARTH_KM


# ── SGP4 傳播 ─────────────────────────────────────────────────────────────────

def propagate_orbit(
    line1: str, line2: str,
    num_pts: int = 360, span_hours: int = 6,
    start_time: datetime | None = None,
) -> list[dict[str, Any]]:
    sat = Satrec.twoline2rv(line1, line2)
    ref = start_time if start_time and start_time.tzinfo else (
        start_time.replace(tzinfo=timezone.utc) if start_time
        else sat_epoch_datetime(sat).replace(tzinfo=timezone.utc)
    )
    jd0, fr0  = jday(ref.year, ref.month, ref.day,
                     ref.hour, ref.minute,
                     ref.second + ref.microsecond * 1e-6)
    times_min = np.linspace(0.0, span_hours * 60.0, num_pts)
    jds = np.full(num_pts, jd0)
    frs = fr0 + times_min / 1440.0
    ov  = frs >= 1.0
    jds[ov] += np.floor(frs[ov]).astype(int)
    frs[ov] %= 1.0

    errs, r_ecis, _ = sat.sgp4_array(jds, frs)
    positions: list[dict[str, Any]] = []
    for i, (err, r_eci) in enumerate(zip(errs, r_ecis)):
        if err:
            continue
        t   = ref + timedelta(minutes=float(times_min[i]))
        lat, lon, alt = eci_to_llh(r_eci, t)
        ecef = eci_to_ecef(r_eci, jds[i], frs[i])
        positions.append({
            "time": t.isoformat(), "_ts": t.timestamp(),
            "lat": lat, "lon": lon, "alt_km": alt,
            "ecef": ecef.tolist(),
        })
    return positions


# ── 2D 軌道圖 ─────────────────────────────────────────────────────────────────

def orbit_figure_2d(positions: list[dict], sat_name: str, span_hours: int, current_idx: int) -> go.Figure:
    lats, lons = [p["lat"] for p in positions], [p["lon"] for p in positions]
    segs_lat: list[list[float]] = [[]]
    segs_lon: list[list[float]] = [[]]
    for i in range(len(lons)):
        if i > 0 and abs(lons[i] - lons[i - 1]) > 180:
            segs_lat.append([]); segs_lon.append([])
        segs_lat[-1].append(lats[i]); segs_lon[-1].append(lons[i])

    fig = go.Figure()
    for k, (slat, slon) in enumerate(zip(segs_lat, segs_lon)):
        fig.add_trace(go.Scattergeo(
            lat=slat, lon=slon, mode="lines",
            line=dict(width=1.8, color="#00e5ff"),
            showlegend=(k == 0), name=sat_name,
        ))
    cp = positions[current_idx]
    fig.add_trace(go.Scattergeo(
        lat=[cp["lat"]], lon=[cp["lon"]],
        mode="markers+text",
        marker=dict(size=14, color="#ff3333", symbol="circle",
                    line=dict(width=2, color="#ffffff")),
        text=["▲ 現在位置"], textposition="top right",
        textfont=dict(size=12, color="#ff9999"),
        showlegend=False, name="現在位置",
    ))
    fig.update_layout(
        geo=dict(
            showland=True,      landcolor="rgb(45,50,55)",
            showocean=True,     oceancolor="rgb(20,25,40)",
            showcountries=True, countrycolor="rgb(80,80,80)",
            showcoastlines=True, coastlinecolor="rgb(100,100,110)",
            bgcolor="rgb(15,18,28)", projection_type="natural earth",
        ),
        margin=dict(l=0, r=0, t=32, b=0),
        paper_bgcolor="rgb(15,18,28)", font_color="white", height=520,
        title=dict(text=f"SGP4 軌道（{span_hours}h）— {sat_name}", x=0.5),
    )
    return fig


# ── 3D 軌道圖 ─────────────────────────────────────────────────────────────────

def _earth_sphere() -> go.Surface:
    n   = 48
    phi = np.linspace(0, 2 * np.pi, n)
    th  = np.linspace(0, np.pi, n)
    xe  = R_EARTH_KM * np.outer(np.cos(phi), np.sin(th))
    ye  = R_EARTH_KM * np.outer(np.sin(phi), np.sin(th))
    ze  = R_EARTH_KM * np.outer(np.ones(n),  np.cos(th))
    return go.Surface(
        x=xe, y=ye, z=ze,
        colorscale=[[0, "rgb(10,40,100)"], [0.5, "rgb(15,70,50)"], [1, "rgb(10,40,100)"]],
        showscale=False, opacity=0.75, name="地球", hoverinfo="skip",
    )


def orbit_figure_3d(
    positions: list[dict], sat_name: str, current_idx: int,
    obs_lat: float | None = None, obs_lon: float | None = None,
    obs_label: str = "",
) -> go.Figure:
    xs = [p["ecef"][0] for p in positions]
    ys = [p["ecef"][1] for p in positions]
    zs = [p["ecef"][2] for p in positions]

    fig = go.Figure()
    fig.add_trace(_earth_sphere())
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs, mode="lines",
        line=dict(width=3, color="#00e5ff"), name=sat_name,
    ))
    fig.add_trace(go.Scatter3d(
        x=[xs[current_idx]], y=[ys[current_idx]], z=[zs[current_idx]],
        mode="markers+text",
        marker=dict(size=9, color="#ff3333", line=dict(width=2, color="#ffffff")),
        text=["▲ 現在"], textposition="top center",
        textfont=dict(size=11, color="#ff9999"), name="現在位置",
    ))
    if obs_lat is not None and obs_lon is not None:
        op = observer_ecef(obs_lat, obs_lon)
        fig.add_trace(go.Scatter3d(
            x=[op[0]], y=[op[1]], z=[op[2]],
            mode="markers+text",
            marker=dict(size=7, color="#ffcc00", symbol="diamond",
                        line=dict(width=1, color="#ffffff")),
            text=[obs_label or "觀測站"], textposition="top center",
            textfont=dict(size=10, color="#ffcc00"), name=obs_label or "觀測站",
        ))
    max_r = max(np.sqrt(xs[i]**2 + ys[i]**2 + zs[i]**2) for i in range(len(xs)))
    ax_r  = [-max_r * 1.05, max_r * 1.05]
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X km", range=ax_r, backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)"),
            yaxis=dict(title="Y km", range=ax_r, backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)"),
            zaxis=dict(title="Z km", range=ax_r, backgroundcolor="rgb(8,10,20)",
                       gridcolor="rgb(40,40,60)"),
            bgcolor="rgb(8,10,20)", aspectmode="cube",
            camera=dict(eye=dict(x=1.4, y=1.4, z=0.8)),
        ),
        paper_bgcolor="rgb(8,10,20)", font_color="white",
        height=560, margin=dict(l=0, r=0, t=32, b=0),
        title=dict(text=f"3D 軌道（ECEF）— {sat_name}", x=0.5),
        legend=dict(bgcolor="rgba(0,0,0,0.45)", bordercolor="gray", borderwidth=1),
    )
    return fig


# ── 過頂時間計算 ──────────────────────────────────────────────────────────────

def az_to_compass(az: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(az / 22.5) % 16]


def find_passes(
    line1: str, line2: str,
    obs_lat: float, obs_lon: float, obs_alt_km: float,
    start_utc: datetime, duration_hours: float = 72.0,
    min_elev_deg: float = 10.0, dt_sec: int = 10,
) -> list[dict]:
    sat = Satrec.twoline2rv(line1, line2)
    t0  = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
    n   = max(2, int(duration_hours * 3600 / dt_sec))

    jd0, fr0    = jday(t0.year, t0.month, t0.day, t0.hour, t0.minute,
                       t0.second + t0.microsecond * 1e-6)
    steps_frac  = np.arange(n) * dt_sec / 86400.0
    frs = fr0 + steps_frac
    jds = np.full(n, jd0) + np.floor(frs).astype(int)
    frs = frs % 1.0

    errs, r_ecis, _ = sat.sgp4_array(jds, frs)
    valid = errs == 0

    obs_ecef = observer_ecef(obs_lat, obs_lon, obs_alt_km)
    T_arr    = ((jds - 2451545.0) + frs) / 36525.0
    gmst_arr = np.deg2rad(
        (280.46061837 + 360.98564736629 * (jds - 2451545.0 + frs)
         + 0.000387933 * T_arr**2) % 360.0
    )
    elevs = np.full(n, -90.0)
    if np.any(valid):
        rv  = r_ecis[valid];  gv = gmst_arr[valid]
        xe  = np.cos(gv) * rv[:,0] + np.sin(gv) * rv[:,1]
        ye  = -np.sin(gv) * rv[:,0] + np.cos(gv) * rv[:,1]
        sat_ecef = np.stack([xe, ye, rv[:,2]], axis=1) - obs_ecef
        rn  = np.linalg.norm(sat_ecef, axis=1, keepdims=True)
        lr, lo = np.deg2rad(obs_lat), np.deg2rad(obs_lon)
        zenith  = np.array([np.cos(lr)*np.cos(lo), np.cos(lr)*np.sin(lo), np.sin(lr)])
        rho_hat = sat_ecef / np.maximum(rn, 1e-9)
        elevs[valid] = np.rad2deg(np.arcsin(np.clip(rho_hat @ zenith, -1.0, 1.0)))

    above, passes = elevs >= min_elev_deg, []
    i = 0
    while i < n:
        if above[i]:
            j      = i
            while j < n and above[j]: j += 1
            seg_el = elevs[i:j]; j_max = int(np.argmax(seg_el))
            t_aos  = t0 + timedelta(seconds=int(i * dt_sec))
            t_tca  = t0 + timedelta(seconds=int((i + j_max) * dt_sec))
            t_los  = t0 + timedelta(seconds=int((j - 1) * dt_sec))

            az_tca = 0.0
            idx_t  = i + j_max
            if valid[idx_t]:
                r_e  = r_ecis[idx_t]; g = gmst_arr[idx_t]
                s_ec = np.array([np.cos(g)*r_e[0]+np.sin(g)*r_e[1],
                                  -np.sin(g)*r_e[0]+np.cos(g)*r_e[1], r_e[2]])
                rho  = s_ec - obs_ecef; rn_s = np.linalg.norm(rho)
                if rn_s > 0.1:
                    rh    = rho / rn_s
                    lr, lo = np.deg2rad(obs_lat), np.deg2rad(obs_lon)
                    south = np.array([ np.sin(lr)*np.cos(lo), np.sin(lr)*np.sin(lo), -np.cos(lr)])
                    east  = np.array([-np.sin(lo), np.cos(lo), 0.0])
                    az_tca = float(np.rad2deg(np.arctan2(np.dot(rh, east), -np.dot(rh, south)))) % 360.0

            passes.append({
                "AOS (UTC)":   t_aos.strftime("%Y-%m-%d %H:%M:%S"),
                "TCA (UTC)":   t_tca.strftime("%Y-%m-%d %H:%M:%S"),
                "LOS (UTC)":   t_los.strftime("%Y-%m-%d %H:%M:%S"),
                "最大仰角 (°)": round(float(seg_el[j_max]), 1),
                "方位角":       f"{az_tca:.1f}° ({az_to_compass(az_tca)})",
                "持續時間 (s)": int((j - 1 - i) * dt_sec),
                "_times": [t0 + timedelta(seconds=int((i+k)*dt_sec)) for k in range(j-i)],
                "_elevs": seg_el.tolist(),
            })
            i = j
        else:
            i += 1
    return passes


def elevation_timeline_figure(passes: list[dict], sat_name: str) -> go.Figure:
    fig = go.Figure()
    for idx, p in enumerate(passes[:6]):
        color, fill = PASS_COLORS[idx % 6], PASS_FILL[idx % 6]
        fig.add_trace(go.Scatter(
            x=[t.strftime("%Y-%m-%d %H:%M") for t in p["_times"]],
            y=p["_elevs"], mode="lines",
            name=f"Pass {idx+1}  {p['AOS (UTC)'][11:16]}Z  {p['最大仰角 (°)']:.0f}°",
            line=dict(color=color, width=2),
            fill="tozeroy", fillcolor=fill,
        ))
    fig.update_layout(
        title=dict(text=f"{sat_name} — 仰角時間線", x=0.5),
        xaxis_title="時間（UTC）", yaxis_title="仰角（°）",
        yaxis=dict(range=[0, None]), height=300,
        margin=dict(t=40, b=36, l=40, r=10),
        paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)",
        font_color="white", legend=dict(bgcolor="rgba(0,0,0,0)", font_size=11),
    )
    return fig


# ── 側邊欄（含中國 LEO 下拉 + NORAD 搜尋）────────────────────────────────────

def render_sidebar(
    df_tle: pd.DataFrame,
    df_meta: pd.DataFrame,
    df_bg: pd.DataFrame,
) -> int | None:
    with st.sidebar:
        mode_label = "☁️ Cloud 模式（parquet）" if IS_CLOUD else "💾 Local 模式（DuckDB）"
        st.markdown(f"**{mode_label}**")
        st.divider()

        # 選擇模式切換
        st.subheader("衛星選擇")
        select_mode = st.radio(
            "選擇方式",
            ["🇨🇳 中國 LEO 衛星", "🔍 NORAD ID / 搜尋"],
            horizontal=True,
            label_visibility="collapsed",
        )

        chosen: int | None = None

        # ── 模式 A：中國 LEO 下拉 ────────────────────────────────────────────
        if select_mode == "🇨🇳 中國 LEO 衛星":
            if df_bg.empty:
                st.warning("sat_background.parquet 不存在。\n請先執行：\n```\npython prc_maneuver/build_slim_db.py --latest30day\n```")
            else:
                df_bg_s = df_bg.sort_values(["constellation", "sat_name"]).reset_index(drop=True)

                # 建立選項字串：「星座  ▸  衛星名稱  (NORAD xxxxx)」
                opt_labels = [
                    f"{row['constellation']}  ▸  {row['sat_name']}  "
                    f"(NORAD {int(row['norad_id'])})"
                    for _, row in df_bg_s.iterrows()
                ]
                # norad_id 對照表
                opt_norads = df_bg_s["norad_id"].astype(int).tolist()

                # 品質標記
                quality_icon = {
                    "researched": "✅",
                    "inferred":   "⚠️",
                }.get

                # 顯示統計
                n_researched = (df_bg_s["data_quality"] == "researched").sum()
                n_inferred   = (df_bg_s["data_quality"] == "inferred").sum()
                st.caption(f"{len(df_bg_s)} 顆  ✅ {n_researched} 已研究  ⚠️ {n_inferred} 推斷")

                sel_idx = st.selectbox(
                    "星座 ▸ 衛星名稱",
                    range(len(opt_labels)),
                    format_func=lambda i: opt_labels[i],
                )
                chosen = opt_norads[sel_idx]

                # 顯示品質徽章
                sel_row = df_bg_s.iloc[sel_idx]
                q = sel_row.get("data_quality", "stub")
                badge = {"researched": "✅ researched", "inferred": "⚠️ inferred"}.get(q, f"🔲 {q}")
                constellation = sel_row.get("constellation", "—")
                mission       = sel_row.get("mission_type", "—")
                st.caption(f"{badge}　{constellation}　{mission}")

        # ── 模式 B：NORAD ID / 名稱搜尋 ─────────────────────────────────────
        else:
            search = st.text_input(
                "NORAD ID 或衛星名稱",
                placeholder="例：52750 或 TIANHE",
            )
            if search.strip().isdigit():
                chosen = int(search.strip())
            elif search.strip() and not df_meta.empty:
                hits = df_meta[
                    df_meta["name_en"].str.contains(search.strip(), case=False, na=False)
                ]
                if not hits.empty:
                    chosen = int(hits.iloc[0]["norad_id"])
                else:
                    st.caption("找不到匹配衛星名稱。")

            # 全衛星清單（fallback，只在搜尋框為空時顯示）
            if chosen is None:
                norads = (
                    sorted(df_tle["norad_id"].dropna().astype(int).unique().tolist())
                    if not df_tle.empty else []
                )
                if norads:
                    chosen = st.selectbox(
                        "或從全衛星清單選擇",
                        norads,
                        format_func=lambda n: f"NORAD {n}",
                    )
                else:
                    st.info("無 TLE 資料。請先執行：\n```\npython prc_maneuver/build_slim_db.py --latest30day\n```")

        # ── 統計摘要 ─────────────────────────────────────────────────────────
        st.divider()
        n_tle = len(df_tle["norad_id"].unique()) if not df_tle.empty else 0
        st.markdown(f"TLE 資料：**{n_tle:,}** 顆衛星")
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

    r        = tle_row.iloc[0]
    sat_name = str(r.get("object_name") or f"NORAD {norad}")
    epoch_dt = pd.to_datetime(r["epoch_utc"])
    mm, inc, ecc = r.get("mean_motion"), r.get("inclination_deg"), r.get("eccentricity")
    alt    = mean_alt_km(mm)
    period = 1440.0 / float(mm) if pd.notna(mm) and float(mm) > 0 else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("衛星名稱", sat_name)
    c2.metric("NORAD ID",  norad)
    c3.metric("TLE Epoch", epoch_dt.strftime("%Y-%m-%d %H:%M UTC"))
    c4.metric("傾角 i",    f"{inc:.3f}°" if pd.notna(inc) else "—")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("平均高度", f"{alt:.0f} km"      if alt is not None else "—")
    c6.metric("軌道週期", f"{period:.1f} min"  if period else "—")
    c7.metric("離心率 e", f"{ecc:.6f}"          if pd.notna(ecc) else "—")
    c8.metric("平均運動", f"{mm:.6f} rev/d"     if pd.notna(mm)  else "—")

    if not df_meta.empty:
        mrow = df_meta[df_meta["norad_id"] == norad]
        if not mrow.empty:
            m = mrow.iloc[0]
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
        brow = df_bg[df_bg["norad_id"] == norad]
        if not brow.empty:
            b = brow.iloc[0]
            q = b.get("data_quality", "stub")
            badge = {"researched": "✅ researched", "inferred": "⚠️ inferred"}.get(q, f"🔲 {q}")
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
        st.code(f"{sat_name}\n{r.get('line1','')}\n{r.get('line2','')}", language=None)


# ── Tab 2: 軌道可視化（2D / 3D 子頁面）──────────────────────────────────────

def tab_orbit(norad: int, df_tle: pd.DataFrame) -> None:
    if df_tle.empty:
        st.info("無 TLE 資料。請先執行 `build_slim_db.py --latest30day`。")
        return
    row = df_tle[df_tle["norad_id"] == norad]
    if row.empty:
        st.warning(f"找不到 NORAD {norad} 的 TLE。")
        return

    r        = row.iloc[0]
    sat_name = str(r.get("object_name") or f"NORAD {norad}")
    line1, line2 = str(r["line1"]), str(r["line2"])

    span_h  = st.select_slider(
        "軌跡時間（小時，以目前時刻為中心）",
        options=[1, 3, 6, 12, 24], value=6,
    )
    num_pts = max(180, span_h * 60)
    now     = datetime.now(timezone.utc)
    start_t = now - timedelta(hours=span_h / 2)

    with st.spinner("SGP4 傳播中…"):
        positions = propagate_orbit(line1, line2, num_pts=num_pts,
                                    span_hours=span_h, start_time=start_t)

    if not positions:
        st.error("SGP4 傳播失敗，TLE 可能已過期或格式有誤。")
        return

    now_ts      = now.timestamp()
    current_idx = min(range(len(positions)), key=lambda i: abs(positions[i]["_ts"] - now_ts))

    sub = st.tabs(["🗺 2D 地圖", "🌐 3D 地球"])
    with sub[0]:
        st.plotly_chart(orbit_figure_2d(positions, sat_name, span_h, current_idx),
                        use_container_width=True)
    with sub[1]:
        st.plotly_chart(orbit_figure_3d(positions, sat_name, current_idx),
                        use_container_width=True)

    inc  = r.get("inclination_deg"); ecc = r.get("eccentricity")
    raan = r.get("raan_deg");        mm  = r.get("mean_motion")
    alt  = mean_alt_km(mm)
    kc   = st.columns(5)
    kc[0].metric("傾角 i",       f"{inc:.3f}°"        if pd.notna(inc)  else "—")
    kc[1].metric("離心率 e",     f"{ecc:.6f}"          if pd.notna(ecc)  else "—")
    kc[2].metric("升交點赤經 Ω", f"{raan:.3f}°"        if pd.notna(raan) else "—")
    kc[3].metric("平均運動",     f"{mm:.6f} rev/d"     if pd.notna(mm)   else "—")
    kc[4].metric("平均高度",     f"{alt:.0f} km"       if alt is not None else "—")

    cp = positions[current_idx]
    st.caption(
        f"TLE Epoch：{pd.to_datetime(r['epoch_utc']).strftime('%Y-%m-%d %H:%M UTC')}　"
        f"｜　目前位置：{cp['lat']:.3f}°N, {cp['lon']:.3f}°E, 高度 {cp['alt_km']:.1f} km"
    )


# ── Tab 3: Conjunction 事件 ────────────────────────────────────────────────────

def tab_conjunction(norad: int | None, df_conj: pd.DataFrame) -> None:
    if IS_CLOUD:
        st.info("☁️ Cloud 模式：顯示預計算 Conjunction 事件（由 `build_slim_db.py --latest30day` 匯出）。")
    else:
        st.info("💾 Local 模式：資料庫中已儲存的 Conjunction 事件。即時計算請至「⚡ 即時合相」分頁。")

    if df_conj.empty:
        st.warning("尚無 Conjunction 資料。請先執行合相管線或 `build_slim_db.py --latest30day`。")
        return

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        filter_norad = st.checkbox("只顯示目前衛星", value=(norad is not None), disabled=(norad is None))
    with fc2:
        risk_opts = ["全部"] + (sorted(df_conj["risk_label"].dropna().unique().tolist())
                                if "risk_label" in df_conj.columns else [])
        risk_filter = st.selectbox("風險等級", risk_opts)
    with fc3:
        max_dist = st.slider("最大接近距離 (km)", 0.1, 100.0, 50.0, step=0.1)

    f = df_conj.copy()
    if filter_norad and norad is not None and "primary_norad" in f.columns:
        f = f[f["primary_norad"] == norad]
    if risk_filter != "全部" and "risk_label" in f.columns:
        f = f[f["risk_label"] == risk_filter]
    if "miss_distance_km" in f.columns:
        f = f[f["miss_distance_km"] <= max_dist]

    st.markdown(f"顯示 **{len(f):,}** 筆（共 {len(df_conj):,} 筆）Conjunction 事件")
    if f.empty:
        st.info("無符合條件的事件。")
        return

    disp = [c for c in ["primary_norad","secondary_norad","tca_utc",
                         "miss_distance_km","pc","risk_label"] if c in f.columns]
    sc   = "tca_utc" if "tca_utc" in disp else disp[0]
    st.dataframe(f[disp].sort_values(sc, ascending=False), use_container_width=True, height=420)

    if "pc" in f.columns and len(f) > 1:
        vp = f["pc"].replace(0, np.nan).dropna()
        if len(vp) > 0:
            fig_pc = go.Figure(go.Histogram(
                x=np.log10(vp), nbinsx=30, marker_color="#00e5ff",
            ))
            fig_pc.update_layout(
                title="Pc 分布（log₁₀）", xaxis_title="log₁₀(Pc)", yaxis_title="事件數",
                height=260, margin=dict(t=36,b=24,l=0,r=0),
                paper_bgcolor="rgb(15,18,28)", plot_bgcolor="rgb(20,24,36)", font_color="white",
            )
            st.plotly_chart(fig_pc, use_container_width=True)


# ── Tab 4: 過頂時間 ────────────────────────────────────────────────────────────

def tab_pass_time(norad: int | None, df_tle: pd.DataFrame) -> None:
    if norad is None:
        st.info("請在左側選擇衛星。"); return
    if df_tle.empty:
        st.info("無 TLE 資料。"); return

    row = df_tle[df_tle["norad_id"] == norad]
    if row.empty:
        st.warning(f"找不到 NORAD {norad} 的 TLE。"); return

    r        = row.iloc[0]
    sat_name = str(r.get("object_name") or f"NORAD {norad}")
    line1, line2 = str(r["line1"]), str(r["line2"])

    st.subheader(f"🔭 {sat_name}（NORAD {norad}）過頂時間預測")
    col1, col2 = st.columns(2)

    with col1:
        obs_choice = st.selectbox("觀測地點", list(OBSERVER_LOCATIONS.keys()))
        if obs_choice == "自定義":
            obs_lat   = st.number_input("緯度（°N）", value=25.0330,
                                        min_value=-90.0, max_value=90.0, format="%.4f")
            obs_lon   = st.number_input("經度（°E）", value=121.5654,
                                        min_value=-180.0, max_value=180.0, format="%.4f")
            obs_label = "自定義觀測站"
        else:
            loc       = OBSERVER_LOCATIONS[obs_choice]
            assert loc is not None
            obs_lat, obs_lon = loc["lat"], loc["lon"]
            obs_label = obs_choice.split("（")[0]

    with col2:
        duration_h = st.select_slider("預測時間（小時）",
                                      options=[24, 48, 72, 120, 168], value=72)
        min_elev   = st.slider("最小仰角（°）", 0, 45, 10)
        start_now  = st.checkbox("從現在開始", value=True)
        if start_now:
            start_utc = datetime.now(timezone.utc)
        else:
            sd = st.date_input("起始日期（UTC）", value=datetime.now(timezone.utc).date())
            start_utc = datetime(sd.year, sd.month, sd.day, tzinfo=timezone.utc)

    st.markdown(
        f"觀測地點：**{obs_label}**（{obs_lat:.4f}°N, {obs_lon:.4f}°E）　"
        f"｜　**{duration_h}h**　｜　最小仰角 **{min_elev}°**"
    )

    with st.spinner(f"計算中（{duration_h}h × 10s 解析度）…"):
        passes = find_passes(
            line1, line2,
            obs_lat=obs_lat, obs_lon=obs_lon, obs_alt_km=0.01,
            start_utc=start_utc,
            duration_hours=float(duration_h),
            min_elev_deg=float(min_elev),
            dt_sec=10,
        )

    if not passes:
        st.info(f"未來 {duration_h}h 內仰角 ≥ {min_elev}° 的過頂事件為零。")
        return

    st.success(f"找到 **{len(passes)}** 次過頂（仰角 ≥ {min_elev}°）")

    disp_cols = ["AOS (UTC)", "TCA (UTC)", "LOS (UTC)", "最大仰角 (°)", "方位角", "持續時間 (s)"]
    df_p = pd.DataFrame([{k: v for k, v in p.items() if not k.startswith("_")} for p in passes])
    st.dataframe(df_p[disp_cols], use_container_width=True,
                 height=min(420, 52 + 36 * len(df_p)))

    st.plotly_chart(elevation_timeline_figure(passes, sat_name), use_container_width=True)

    with st.expander("3D 地球（衛星位置 + 觀測站）", expanded=False):
        now      = datetime.now(timezone.utc)
        with st.spinner("SGP4 傳播中…"):
            pos3d = propagate_orbit(line1, line2, num_pts=180, span_hours=6,
                                    start_time=now - timedelta(hours=3))
        if pos3d:
            idx3d = min(range(len(pos3d)), key=lambda i: abs(pos3d[i]["_ts"] - now.timestamp()))
            st.plotly_chart(
                orbit_figure_3d(pos3d, sat_name, idx3d,
                                obs_lat=obs_lat, obs_lon=obs_lon, obs_label=obs_label),
                use_container_width=True,
            )


# ── Tab 5: 即時 Conjunction（本地限定）───────────────────────────────────────

def tab_realtime_conjunction(norad: int | None) -> None:
    if IS_CLOUD:
        st.warning(
            "即時 Conjunction 計算需要本地 `space_db.duckdb`，Streamlit Cloud 上不支援。\n\n"
            "本地執行：`streamlit run conjunction_app/app.py`"
        )
        return
    if norad is None:
        st.info("請先在左側選擇衛星。"); return

    st.subheader(f"NORAD {norad} — 即時 Conjunction 分析（v2 kdtree）")
    col1, col2 = st.columns(2)
    with col1:
        time_start_date = st.date_input("起始日期（UTC）", value=datetime.now(timezone.utc).date())
        time_span_h     = st.slider("時間跨度（小時）", 6, 72, 24)
        miss_thr        = st.slider("接近距離門檻（km）", 1.0, 200.0, 50.0)
    with col2:
        max_inc_deg  = st.slider("最大傾角差 Δi（°）", 1.0, 15.0, 5.0)
        prefilter_km = st.slider("高度預篩範圍（km）", 50.0, 500.0, 200.0)
        n_mc         = st.select_slider("Monte Carlo 樣本數",
                                        options=[1000, 5000, 10000, 20000], value=5000)

    if not st.button("▶ 開始計算", type="primary"):
        return

    try:
        from ca_pipeline_kdtree_v2_fixed import run_ca_pipeline
    except ImportError:
        st.error("找不到 `ca_pipeline_kdtree_v2_fixed.py`，請確認位於 repo 根目錄。")
        return

    time_start = datetime(time_start_date.year, time_start_date.month,
                          time_start_date.day, tzinfo=timezone.utc)
    with st.spinner("計算中（可能需要 30-60 秒）…"):
        try:
            result = run_ca_pipeline(
                db_path=str(SPACE_DB), target_norad_id=norad,
                time_start=time_start, time_span_hours=time_span_h,
                miss_threshold_km=miss_thr, prefilter_padding_km=prefilter_km,
                max_delta_inc_deg=max_inc_deg, n_mc=n_mc, Rc_km=0.01,
            )
        except Exception as e:
            st.error(f"計算失敗：{e}"); return

    if result.get("status") != "ok":
        st.error(f"管線錯誤：{result}"); return

    events, summary, timing = result.get("events",[]), result.get("summary",{}), result.get("timing",{})
    kc = st.columns(4)
    kc[0].metric("候選衛星（預篩後）", summary.get("prefilter_candidate_count","—"))
    kc[1].metric("粗命中",             summary.get("coarse_hit_count","—"))
    kc[2].metric("Conjunction 事件",   summary.get("event_count","—"))
    kc[3].metric("耗時",               f"{timing.get('elapsed_sec',0):.1f} s")

    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True)
    else:
        st.success(f"NORAD {norad}：分析時段內無 Conjunction 事件。")
    if result.get("debug"):
        with st.expander("Debug log"):
            st.text("\n".join(result["debug"]))


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main() -> None:
    df_tle  = load_latest30()
    df_meta = load_metadata()
    df_bg   = load_satbg()
    df_conj = load_conj_events()

    chosen = render_sidebar(df_tle, df_meta, df_bg)

    tabs = st.tabs([
        "🛰 衛星資訊",
        "🌍 軌道可視化",
        "⚠️ Conjunction",
        "🔭 過頂時間",
        "⚡ 即時合相",
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


if __name__ == "__main__":
    main()
