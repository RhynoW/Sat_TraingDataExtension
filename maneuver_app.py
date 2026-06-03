from datetime import datetime
import os
import re

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import streamlit as st
from pathlib import Path
from plotly.subplots import make_subplots
from scipy.optimize import curve_fit
from scipy.signal import lombscargle
# ==========================================
# 設定區
# ==========================================

SPACE_DB_PATH = os.getenv(
    "SPACE_DB_PATH",
    r"./space_db.duckdb",
)

DB_PATH = SPACE_DB_PATH
TABLE_NAME = "tle_table"
MU = 398600.4415  # km^3/s^2
R_EARTH = 6371.0  # km

F107_CACHE_FILE = "./f107_cache.csv"
COMPARISON_DIR         = os.getenv("COMPARISON_DIR", "./data/comparison")
GALILEO_COMPARISON_DIR = os.getenv("GALILEO_COMPARISON_DIR", "./data/galileo_comparison")
GEO_MANEUVER_CSV = Path("./data/geo_maneuvers/maneuver_candidates.csv")

# ===== 螺旋圖共用設定 =====
spiral_a = 0.5
spiral_b = 0.02
spiral_cmap = "hsv"

angle_cols = ["inclination_deg", "raan_deg", "argp_deg", "mean_anomaly_deg"]


# ==========================================
# F10.7
# ==========================================

def fetch_f107_data():
    today_str = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(F107_CACHE_FILE):
        df_cache = pd.read_csv(F107_CACHE_FILE)
        if not df_cache.empty and "epoch" in df_cache.columns:
            df_cache["epoch"] = pd.to_datetime(df_cache["epoch"])
            latest_cache_date = df_cache["epoch"].max().strftime("%Y-%m-%d")
            if latest_cache_date == today_str:
                return df_cache

    url = "https://spaceweather.gc.ca/solar_flux_data/daily_flux_values/fluxtable.txt"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        lines = response.text.split("\n")
        data = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 7 and parts[0].isdigit() and len(parts[0]) == 8:
                date_val = pd.to_datetime(parts[0], format="%Y%m%d")
                flux_val = float(parts[5])  # Flux_Adj
                data.append({"epoch": date_val.strftime("%Y-%m-%d"), "f107": flux_val})

        new_df = pd.DataFrame(data)
        if not new_df.empty:
            new_df["epoch"] = pd.to_datetime(new_df["epoch"], errors="coerce").astype("datetime64[ns]")
            new_df.to_csv(F107_CACHE_FILE, index=False)
        return new_df

    except Exception as e:
        st.error(f"F10.7 下載失敗: {e}")
        if os.path.exists(F107_CACHE_FILE):
            df_cache = pd.read_csv(F107_CACHE_FILE)
            if not df_cache.empty and "epoch" in df_cache.columns:
                df_cache["epoch"] = pd.to_datetime(df_cache["epoch"], errors="coerce").astype("datetime64[ns]")
            return df_cache
        return pd.DataFrame()


# ==========================================
# 共用資料處理
# ==========================================

def prepare_spiral_polar_data(df_raw: pd.DataFrame):
    df = df_raw.copy()
    df["date"] = pd.to_datetime(df["date_tag"])
    df = df.sort_values("date").reset_index(drop=True)

    days_since_start = (df["date"] - df["date"].min()).dt.days.values

    if len(days_since_start) == 0:
        return df, np.array([]), np.array([]), np.array([]), np.array([])

    if days_since_start.max() > 0:
        theta_time = 2 * np.pi * days_since_start / days_since_start.max()
    else:
        theta_time = np.zeros_like(days_since_start)

    r_spiral = spiral_a + spiral_b * days_since_start

    if days_since_start.max() > days_since_start.min():
        t_norm = (
            (days_since_start - days_since_start.min())
            / (days_since_start.max() - days_since_start.min())
        )
    else:
        t_norm = np.zeros_like(days_since_start, dtype=float)

    return df, days_since_start, theta_time, r_spiral, t_norm


def angle_diff_deg(a_curr: pd.Series, a_prev: pd.Series) -> pd.Series:
    diff = (a_curr - a_prev + 180.0) % 360.0 - 180.0
    return diff


def compute_delta_table(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df["date"] = pd.to_datetime(df["date_tag"])
    df = (
        df.sort_values(["date", "epoch_jd"])
          .drop_duplicates(subset=["date"], keep="last")
          .reset_index(drop=True)
    )

    for col in angle_cols:
        prev = df[col].shift(1)
        df[f"delta_{col}"] = angle_diff_deg(df[col], prev)

    df["delta_sma_km"] = df["sma_km"] - df["sma_km"].shift(1)

    out_cols = (
        ["date", "norad_id", "sma_km", "delta_sma_km"]
        + angle_cols
        + [f"delta_{c}" for c in angle_cols]
    )
    return df[out_cols]


def calculate_ric_deltas(df):
    df = df.copy()

    if df.empty:
        df["dv_intrack"] = []
        df["dv_crosstrack"] = []
        return df

    sma_smooth = df["sma_km"].rolling(window=3, center=True).mean().fillna(df["sma_km"])
    v_mag = np.sqrt(MU / sma_smooth)

    df["dv_intrack"] = ((v_mag / 2.0) * (sma_smooth.diff() / sma_smooth)) * 1000.0

    di = np.radians(df["inclination_deg"].diff())
    dO = np.radians(df["raan_deg"].diff())
    inc = np.radians(df["inclination_deg"])
    df["dv_crosstrack"] = (v_mag * np.sqrt(di ** 2 + (np.sin(inc) * dO) ** 2)) * 1000.0

    df[["dv_intrack", "dv_crosstrack"]] = df[["dv_intrack", "dv_crosstrack"]].fillna(0)
    return df


# ==========================================
# 機動偵測
# ==========================================

def detect_ric_events(df, column, threshold_mult=5.0, alt_km=None):
    series = df[column].abs()
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0:
        mad = 1e-6
    z_score = (series - median) / mad
    if alt_km is not None and alt_km >= 12_000:
        min_dv = 0.005   # MEO (Galileo ~29,600 km): tiny ΔV, no drag
    elif alt_km is not None and alt_km < 500:
        min_dv = 0.5
    elif alt_km is not None and alt_km >= 700:
        min_dv = 0.01
    else:
        min_dv = 0.05
    is_event = (z_score > threshold_mult) & (series > min_dv)
    return is_event


def detect_maneuvers_refined_adaptive(df):
    df_out = df.copy()
    if df_out.empty:
        return df_out, pd.DataFrame(columns=["idx", "epoch", "sma_delta"]), 4.0

    df_out.columns = df_out.columns.str.strip()
    df_out["epoch"] = pd.to_datetime(df_out["epoch"])

    # 避免 duplicate labels 導致 resample 失敗
    df_out = (
        df_out.sort_values(["epoch", "epoch_jd"])
              .drop_duplicates(subset=["epoch"], keep="last")
              .reset_index(drop=True)
    )

    # 重採樣到日
    df_out = (
        df_out.set_index("epoch")
              .resample("D")
              .ffill()
              .reset_index()
              .sort_values("epoch")
              .reset_index(drop=True)
    )

    if len(df_out) < 2:
        df_out["sma_rate"] = 0.0
        df_out["sma_delta"] = 0.0
        df_out["residual"] = 0.0
        df_out["z_score"] = 0.0
        df_out["is_candidate"] = False
        df_out["is_maneuver"] = False
        return df_out, pd.DataFrame(columns=["idx", "epoch", "sma_delta"]), 4.0

    dt_hours = df_out["epoch"].diff().dt.total_seconds().bfill() / 3600
    dt_hours = dt_hours.replace(0, 24)
    df_out["sma_rate"] = df_out["sma_km"].diff() / dt_hours
    df_out["sma_delta"] = df_out["sma_km"].diff().abs()

    alt_avg = df_out["sma_km"].mean() - R_EARTH
    if 300 <= alt_avg < 500:
        mult = 7.0;  window = 3;  rate_mult = 8.0; rate_floor = 0.10
    elif 500 <= alt_avg < 600:
        mult = 4.0;  window = 7;  rate_mult = 6.0; rate_floor = 0.02
    elif 600 <= alt_avg < 700:
        mult = 3.5;  window = 7;  rate_mult = 6.0; rate_floor = 0.02
    elif 700 <= alt_avg < 1200:
        mult = 3.0;  window = 10; rate_mult = 4.0; rate_floor = 0.005
    elif alt_avg >= 12_000:
        # MEO (e.g. Galileo ~29,600 km): no atmospheric drag, very slow natural SMA drift.
        # Use long reference window and very low floor so small station-keeping burns are flagged.
        mult = 2.5;  window = 21; rate_mult = 3.0; rate_floor = 0.0001
    else:
        mult = 4.0;  window = 7;  rate_mult = 6.0; rate_floor = 0.01

    ref_rate = df_out["sma_rate"].rolling(window, center=True, min_periods=3).median()
    df_out["residual"] = (df_out["sma_rate"] - ref_rate).abs()
    mad_rate = df_out["residual"].rolling(window, center=True, min_periods=3).median()
    mad_rate = mad_rate.fillna(max(mad_rate.median(), 1e-9))
    df_out["z_score"] = df_out["residual"] / mad_rate

    delta = df_out["sma_delta"].dropna()
    d_med = delta.median() if not delta.empty else 0.0
    d_mad = max((delta - d_med).abs().median() if not delta.empty else 0.0, max(d_med * 0.1, 1e-9))
    delta_thr = d_med + mult * d_mad

    rate_abs = df_out["sma_rate"].abs().dropna()
    r_med = rate_abs.median() if not rate_abs.empty else 0.0
    r_mad = max((rate_abs - r_med).abs().median() if not rate_abs.empty else 0.0, max(r_med * 0.1, 1e-9))
    rate_thr = max(r_med + rate_mult * r_mad, rate_floor)

    df_out["is_candidate"] = (df_out["sma_delta"] >= delta_thr) & (df_out["sma_rate"].abs() >= rate_thr)

    clusters, buf = [], []
    for i, flag in enumerate(df_out["is_candidate"]):
        if flag:
            buf.append(i)
        else:
            if buf:
                clusters.append(buf)
                buf = []
    if buf:
        clusters.append(buf)

    df_out["is_maneuver"] = False
    events = []
    for c in clusters:
        peak = df_out.loc[c, "sma_delta"].idxmax()
        if peak in df_out.index:
            df_out.loc[peak, "is_maneuver"] = True
            events.append(
                {
                    "idx": peak,
                    "epoch": df_out.loc[peak, "epoch"],
                    "sma_delta": df_out.loc[peak, "sma_delta"],
                    "sma_direction": "raise" if df_out.loc[peak, "sma_rate"] > 0 else "lower",
                }
            )

    return df_out, pd.DataFrame(events), mult


# ==========================================
# 繪圖
# ==========================================

def plot_dual_axis_sma_f107(df_final):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_final["epoch"], y=df_final["sma_km"], name="SMA (km)", line=dict(color="cyan", width=2)))
    fig.add_trace(
        go.Scatter(
            x=df_final["epoch"],
            y=df_final["f107"],
            name="F10.7 Index",
            line=dict(color="orange", dash="dot"),
            yaxis="y2",
            opacity=0.6,
        )
    )
    manv = df_final[df_final["is_maneuver"]]
    fig.add_trace(
        go.Scatter(
            x=manv["epoch"],
            y=manv["sma_km"],
            mode="markers",
            marker=dict(color="red", size=12, symbol="triangle-up"),
            name="Detected OMM",
        )
    )

    fig.update_layout(
        title="SMA Decay vs Solar Activity (F10.7)",
        yaxis=dict(title="Semi-major Axis (km)", side="left"),
        yaxis2=dict(title="F10.7 (fluxadjflux)", side="right", overlaying="y", showgrid=False),
        template="plotly_dark",
        height=500,
    )
    return fig


def load_data(norad_id, start_date, end_date):
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        query = f"""
        SELECT
            epoch_jd,
            date_tag,
            norad_id,
            sma_km,
            eccentricity,
            inclination_deg,
            raan_deg,
            argp_deg,
            mean_anomaly_deg
        FROM {TABLE_NAME}
        WHERE norad_id = ?
          AND DATE(date_tag) BETWEEN DATE(?) AND DATE(?)
        ORDER BY date_tag
        """
        df = conn.execute(query, [int(norad_id), start_date, end_date]).df()
        conn.close()

        if not df.empty:
            df["epoch"] = pd.to_datetime(df["date_tag"], errors="coerce").astype("datetime64[ns]")
            df = (
                df.sort_values(["epoch", "epoch_jd"])
                  .drop_duplicates(subset=["epoch"], keep="last")
                  .reset_index(drop=True)
            )
            return df

    except Exception as e:
        st.error(f"資料庫讀取失敗: {e}")

    return pd.DataFrame()


def plot_3d_orbit_scene(sma_val, inc_deg, raan_deg, target_id):
    R_earth = 6371.0
    u = np.linspace(0, 2 * np.pi, 50)
    v = np.linspace(0, np.pi, 50)
    x_e = R_earth * np.outer(np.cos(u), np.sin(v))
    y_e = R_earth * np.outer(np.sin(u), np.sin(v))
    z_e = R_earth * np.outer(np.ones(np.size(u)), np.cos(v))

    fig = go.Figure()
    fig.add_trace(go.Surface(
        x=x_e, y=y_e, z=z_e,
        colorscale="Blues", showscale=False, opacity=0.6,
        hoverinfo="skip", name="Earth"
    ))

    inc = np.radians(inc_deg)
    raan = np.radians(raan_deg)
    t = np.linspace(0, 2 * np.pi, 200)
    x_pqw = sma_val * np.cos(t)
    y_pqw = sma_val * np.sin(t)

    x_orbit = (np.cos(raan) * x_pqw) - (np.sin(raan) * np.cos(inc) * y_pqw)
    y_orbit = (np.sin(raan) * x_pqw) + (np.cos(raan) * np.cos(inc) * y_pqw)
    z_orbit = (np.sin(inc) * y_pqw)

    fig.add_trace(go.Scatter3d(
        x=x_orbit, y=y_orbit, z=z_orbit,
        mode="lines",
        line=dict(color="yellow", width=5),
        name=f"Orbit (Inc: {inc_deg:.1f}°)"
    ))
    fig.add_trace(go.Scatter3d(
        x=[x_orbit[0]], y=[y_orbit[0]], z=[z_orbit[0]],
        mode="markers",
        marker=dict(size=10, color="red", symbol="diamond"),
        name="Satellite"
    ))
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (km)", gridcolor="gray", showbackground=False),
            yaxis=dict(title="Y (km)", gridcolor="gray", showbackground=False),
            zaxis=dict(title="Z (km)", gridcolor="gray", showbackground=False),
            aspectmode="data",
            bgcolor="rgb(5, 5, 15)",
        ),
        margin=dict(l=0, r=0, b=0, t=30),
        height=700,
    )
    return fig


def plot_3d_orbit_scene_multi(df_raw, target_id):
    R_earth = 6371.0
    fig = go.Figure()
    u, v = np.linspace(0, 2 * np.pi, 50), np.linspace(0, np.pi, 50)

    fig.add_trace(go.Surface(
        x=R_earth * np.outer(np.cos(u), np.sin(v)),
        y=R_earth * np.outer(np.sin(u), np.sin(v)),
        z=R_earth * np.outer(np.ones(np.size(u)), np.cos(v)),
        colorscale="Blues", showscale=False, opacity=0.5, hoverinfo="skip"
    ))

    n_steps = len(df_raw)
    if n_steps == 0:
        return fig

    colors = px.colors.sample_colorscale(
        "RdBu",
        [i / (n_steps - 1) if n_steps > 1 else 0 for i in range(n_steps)]
    )
    t = np.linspace(0, 2 * np.pi, 100)
    step = max(1, n_steps // 50)

    latest_xyz = None

    for i in range(0, n_steps, step):
        row = df_raw.iloc[i]
        sma = row["sma_km"]
        inc = np.radians(row["inclination_deg"])
        raan = np.radians(row["raan_deg"])

        x_pqw = sma * np.cos(t)
        y_pqw = sma * np.sin(t)
        x_orbit = (np.cos(raan) * x_pqw) - (np.sin(raan) * np.cos(inc) * y_pqw)
        y_orbit = (np.sin(raan) * x_pqw) + (np.cos(raan) * np.cos(inc) * y_pqw)
        z_orbit = (np.sin(inc) * y_pqw)

        latest_xyz = (x_orbit[0], y_orbit[0], z_orbit[0])

        is_last = (i >= n_steps - step)
        is_first = (i == 0)

        fig.add_trace(go.Scatter3d(
            x=x_orbit, y=y_orbit, z=z_orbit,
            mode="lines",
            line=dict(color=colors[i], width=4 if (is_last or is_first) else 2),
            opacity=1.0 if (is_last or is_first) else 0.3,
            name=f"{row['date_tag']}",
            showlegend=True if (is_last or is_first) else False
        ))

    if latest_xyz is not None:
        fig.add_trace(go.Scatter3d(
            x=[latest_xyz[0]], y=[latest_xyz[1]], z=[latest_xyz[2]],
            mode="markers",
            marker=dict(size=8, color="blue", symbol="diamond"),
            name="Latest Position"
        ))

    fig.update_layout(
        scene=dict(aspectmode="data", bgcolor="rgb(5, 5, 15)"),
        margin=dict(l=0, r=0, b=0, t=30),
        height=700,
        title="軌道演變示意: <span style='color:red'>初期</span> → <span style='color:blue'>近期</span>",
    )
    return fig

def ensure_datetime64ns(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df = df.copy()
    df[col] = pd.to_datetime(df[col], errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        df[col] = df[col].astype("datetime64[ns]")
    return df


# ==========================================
# MEME 殘差：載入 + RTN 機動偵測
# ==========================================

_RESID_COLS = [
    "norad_id", "sat_name", "t",
    "dr_r_km", "dr_t_km", "dr_n_km",
    "pos_err_km", "vel_err_kms",
    "tle_epoch", "tle_age_days",
]


def load_meme_residuals(norad_id, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Load MEME vs TLE RTN residuals for one satellite from the latest residuals_*.csv.
    Uses DuckDB to filter efficiently before pulling into pandas (file can be 100M+).
    Returns empty DataFrame if no data found.
    """
    comp_dir = Path(COMPARISON_DIR)
    if not comp_dir.exists():
        return pd.DataFrame()

    csvs = sorted(comp_dir.glob("residuals_*.csv"), reverse=True)
    if not csvs:
        return pd.DataFrame()

    nid = int(norad_id)
    t_start = pd.Timestamp(start_date, tz="UTC")
    t_end   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)

    for csv_path in csvs:
        try:
            con = duckdb.connect(":memory:")
            df = con.execute(f"""
                SELECT *
                FROM read_csv_auto('{csv_path.as_posix()}', ignore_errors=true)
                WHERE CAST(norad_id AS INTEGER) = {nid}
            """).fetchdf()
            con.close()
            if df.empty:
                continue
            df = df[[c for c in _RESID_COLS if c in df.columns]]
            df["t"] = pd.to_datetime(df["t"], utc=True)
            df = df[(df["t"] >= t_start) & (df["t"] < t_end)]
            if not df.empty:
                return df.sort_values("t").reset_index(drop=True)
        except Exception as _e:
            st.warning(f"MEME 殘差 CSV 讀取失敗 ({csv_path.name}): {_e}")
            continue

    return pd.DataFrame()


_GALILEO_RESID_COLS = [
    "norad_id", "sat_name", "t",
    "dr_r_km", "dr_t_km", "dr_n_km",
    "pos_err_km", "vel_err_kms",
    "tle_epoch", "tle_age_days",
]

_GALILEO_PRN_NORAD = {
    "E02": 41549,  "E03": 41860,  "E04": 41861,  "E05": 41862,
    "E06": 59600,  "E07": 41859,  "E08": 41175,  "E09": 41174,
    "E10": 49810,  "E11": 37846,  "E12": 37847,  "E13": 43567,
    "E14": 40129,  "E15": 43564,  "E16": 61182,  "E18": 40128,
    "E19": 38857,  "E21": 43055,  "E23": 61183,  "E25": 43056,
    "E26": 40544,  "E27": 43057,  "E28": 67160,  "E29": 59598,
    "E30": 40890,  "E31": 43058,  "E32": 67162,  "E33": 43565,
    "E34": 49809,  "E36": 43566,
}


def load_galileo_sp3_residuals(
    sat_id,          # NORAD int or PRN string like "E11"
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load Galileo SP3 vs TLE RTN residuals from data/galileo_comparison/residuals_*.csv."""
    gal_dir = Path(GALILEO_COMPARISON_DIR)
    if not gal_dir.exists():
        return pd.DataFrame()

    csvs = sorted(gal_dir.glob("residuals_*.csv"), reverse=True)
    if not csvs:
        return pd.DataFrame()

    # Resolve to NORAD int
    if isinstance(sat_id, str) and sat_id.startswith("E"):
        nid = _GALILEO_PRN_NORAD.get(sat_id.upper())
        if nid is None:
            return pd.DataFrame()
    else:
        try:
            nid = int(sat_id)
        except (ValueError, TypeError):
            return pd.DataFrame()

    t_start = pd.Timestamp(start_date, tz="UTC")
    t_end   = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)

    for csv_path in csvs:
        try:
            con = duckdb.connect(":memory:")
            df = con.execute(f"""
                SELECT *
                FROM read_csv_auto('{csv_path.as_posix()}', ignore_errors=true)
                WHERE CAST(norad_id AS INTEGER) = {nid}
            """).fetchdf()
            con.close()
            if df.empty:
                continue
            df = df[[c for c in _GALILEO_RESID_COLS if c in df.columns]]
            df["t"] = pd.to_datetime(df["t"], utc=True)
            df = df[(df["t"] >= t_start) & (df["t"] < t_end)]
            if not df.empty:
                return df.sort_values("t").reset_index(drop=True)
        except Exception as _e:
            st.warning(f"Galileo SP3 殘差 CSV 讀取失敗 ({csv_path.name}): {_e}")
            continue

    return pd.DataFrame()


def detect_maneuvers_rtn(resid_df: pd.DataFrame, z_thr: float | None = None) -> pd.DataFrame:
    """
    Detect maneuvers from MEME-vs-TLE RTN residuals.

    A maneuver appears as an abrupt step in dr_t_km (in-plane) or dr_n_km (out-of-plane).
    Method: MAD z-score on the per-interval step rate [km/h]; clusters adjacent spikes.
    z_thr is auto-selected from median TLE age when None: ≤3d→4.0, ≤7d→5.0, ≤14d→6.0, >14d→7.0.

    Returns one row per detected event with columns:
        epoch, type, dr_t_km, dr_n_km, dr_r_km, pos_err_km,
        step_km, step_rate_km_h, z_score, tle_age_days
    """
    required = {"t", "dr_t_km", "dr_n_km", "dr_r_km", "pos_err_km"}
    if resid_df.empty or not required.issubset(resid_df.columns):
        return pd.DataFrame()

    df = resid_df.sort_values("t").copy()
    df["t"] = pd.to_datetime(df["t"], utc=True)

    if z_thr is None:
        age = float(df["tle_age_days"].median()) if "tle_age_days" in df.columns else 7.0
        if age <= 3:
            z_thr = 4.0
        elif age <= 7:
            z_thr = 5.0
        elif age <= 14:
            z_thr = 6.0
        else:
            z_thr = 7.0

    # Time step [hours] between consecutive state vectors
    dt_h = df["t"].diff().dt.total_seconds().fillna(600.0) / 3600.0
    dt_h = dt_h.clip(lower=1e-4)

    events = []

    for col, mtype in [("dr_t_km", "in-plane"), ("dr_n_km", "out-of-plane")]:
        step = df[col].diff().abs()          # absolute jump between consecutive rows [km]
        rate = step / dt_h                   # normalised to [km/h]

        med = rate.median()
        mad = (rate - med).abs().median()
        if mad < 1e-9:
            mad = rate.std() if rate.std() > 1e-9 else 1e-9
        z = (rate - med) / mad              # one-sided: large steps flag high

        flagged = df.index[z > z_thr].tolist()
        if not flagged:
            continue

        # Cluster adjacent flagged indices (gap ≤ 3 steps ≈ 30 min at 10-min cadence)
        clusters, buf = [], [flagged[0]]
        for ix in flagged[1:]:
            if ix - buf[-1] <= 3:
                buf.append(ix)
            else:
                clusters.append(buf)
                buf = [ix]
        clusters.append(buf)

        for cluster in clusters:
            peak_ix = z.loc[cluster].idxmax()
            row = df.loc[peak_ix]
            events.append({
                "epoch":           row["t"],
                "type":            mtype,
                "dr_t_km":         row["dr_t_km"],
                "dr_n_km":         row["dr_n_km"],
                "dr_r_km":         row["dr_r_km"],
                "pos_err_km":      row["pos_err_km"],
                "step_km":         round(float(step.loc[peak_ix]), 3),
                "step_rate_km_h":  round(float(rate.loc[peak_ix]), 3),
                "z_score":         round(float(z.loc[peak_ix]), 1),
                "tle_age_days":    round(float(row.get("tle_age_days", np.nan)), 2),
            })

    if not events:
        return pd.DataFrame()

    result = pd.DataFrame(events).sort_values("epoch").reset_index(drop=True)
    # Merge events within the same hour (simultaneous in-plane + out-of-plane)
    result["_epoch_h"] = result["epoch"].dt.floor("h")
    result = (
        result.sort_values("z_score", ascending=False)
              .drop_duplicates("_epoch_h")
              .sort_values("epoch")
              .drop(columns="_epoch_h")
              .reset_index(drop=True)
    )
    return result


# ==========================================
# Streamlit UI
# ==========================================

# ============================================================
# GEO Maneuver Analysis
# ============================================================

def _geo_gmst(jd: np.ndarray) -> np.ndarray:
    T = jd - 2_451_545.0
    return (280.460_618_37 + 360.985_647_366_29 * T) % 360.0


def _geo_mean_lon(raan, argp, ma, jd) -> np.ndarray:
    raw = (raan + argp + ma - _geo_gmst(jd)) % 360.0
    return np.where(raw > 180.0, raw - 360.0, raw)


def load_geo_raw_series(norad_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    """Load TLE time-series for a GEO satellite and compute λ, drift rate."""
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        df = con.execute("""
            SELECT epoch_jd, epoch_utc, raan_deg, argp_deg, mean_anomaly_deg,
                   inclination_deg, eccentricity, sma_km
            FROM raw_tle_archive
            WHERE norad_id = ?
              AND epoch_utc >= ? AND epoch_utc <= ?
            ORDER BY epoch_jd
        """, [norad_id, start_date, end_date]).df()
        con.close()
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # Dedup within 1-hour buckets
    df["_b"] = (df["epoch_jd"] / 0.04).astype(int)
    df = df.drop_duplicates(subset=["_b"]).drop(columns=["_b"]).reset_index(drop=True)

    df["lambda_deg"] = _geo_mean_lon(
        df["raan_deg"].values, df["argp_deg"].values,
        df["mean_anomaly_deg"].values, df["epoch_jd"].values,
    )
    dt = df["epoch_jd"].diff()
    dl = (df["lambda_deg"].diff() + 180.0) % 360.0 - 180.0
    df["drift_deg_day"] = np.where(dt >= 0.05, dl / dt, np.nan)
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True, errors="coerce")
    return df


def load_geo_events(norad_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    """Load pre-computed GEO maneuver events for one satellite."""
    if not GEO_MANEUVER_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GEO_MANEUVER_CSV)
    df = df[df["norad_id"] == norad_id].copy()
    if df.empty:
        return df
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True, errors="coerce")
    t0 = pd.Timestamp(start_date, tz="UTC")
    t1 = pd.Timestamp(end_date,   tz="UTC") + pd.Timedelta(days=1)
    return df[(df["epoch_utc"] >= t0) & (df["epoch_utc"] <= t1)].reset_index(drop=True)


def render_geo_page(norad_id: int, start_date: str, end_date: str) -> None:
    events = load_geo_events(norad_id, start_date, end_date)
    series = load_geo_raw_series(norad_id, start_date, end_date)

    obj_name = (
        events["object_name"].iloc[0]
        if not events.empty and "object_name" in events.columns
        else f"NORAD-{norad_id}"
    )
    st.subheader(f"GEO 機動分析: {obj_name}  (NORAD {norad_id})")
    st.caption(
        f"分析期間: {start_date} – {end_date}  |  "
        "資料來源: space_db → raw_tle_archive + maneuver_candidates.csv"
    )

    if events.empty and series.empty:
        st.warning(
            f"NORAD {norad_id} 無資料。請確認 data/geo_maneuvers/maneuver_candidates.csv 已存在，"
            "且 space_db.duckdb 的 raw_tle_archive 包含此衛星 TLE。"
        )
        return

    def _cnt(t, conf=None):
        if events.empty:
            return 0
        mask = events["type"] == t
        if conf is not None:
            mask = mask & (events["confirmed"] == conf)
        return int(mask.sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("EW 確認", _cnt("EW", True),       help="漂移率符號翻轉 |Δdrift| > 0.02 °/day")
    c2.metric("NS 確認", _cnt("NS", True),       help="傾角步進 Δi < −0.003°，附加 RAAN 殘差確認")
    c3.metric("重定位",  _cnt("REPOSITIONING"),   help="中值漂移 > 0.05 °/day 且最大偏離 > 2°")
    c4.metric("廢棄",    _cnt("DISPOSAL"),         help="SMA 持續超過 42,300 km")
    c5.metric("TLE 空白", _cnt("TLE_GAP"),        help="相鄰 TLE 間距 > 4 天")

    tab_lon, tab_inc, tab_table = st.tabs(["📡 經度 & 漂移率", "↕ 傾角 (NS)", "📋 事件表"])

    # ── Tab 1: Longitude & drift ────────────────────────────────────────────
    with tab_lon:
        if series.empty:
            st.info("無 TLE 時間序列（raw_tle_archive 中未找到此衛星）。")
        else:
            ew_ev  = events[events["type"] == "EW"]      if not events.empty else pd.DataFrame()
            gap_ev = events[events["type"] == "TLE_GAP"] if not events.empty else pd.DataFrame()

            fig_lon = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                subplot_titles=["Sub-Satellite Longitude λ (°)",
                                "Longitude Drift Rate dλ/dt (°/day)"],
                vertical_spacing=0.10,
            )
            fig_lon.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["lambda_deg"],
                name="λ (°)", line=dict(color="deepskyblue", width=1.5),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>λ = %{y:.3f}°<extra></extra>",
            ), row=1, col=1)
            fig_lon.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["drift_deg_day"],
                name="Drift (°/day)", line=dict(color="lightgreen", width=1.2),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>drift = %{y:.4f} °/day<extra></extra>",
            ), row=2, col=1)
            fig_lon.add_hline(y=0.0, row=2, col=1,
                              line_dash="dash", line_color="gray", opacity=0.5)

            # Shade TLE gaps
            if not gap_ev.empty:
                for _, g in gap_ev.iterrows():
                    t_end_g  = g["epoch_utc"]
                    gap_days = float(g["gap_days"]) if pd.notna(g.get("gap_days")) else 4.0
                    t_start_g = t_end_g - pd.Timedelta(days=gap_days)
                    fig_lon.add_vrect(
                        x0=t_start_g, x1=t_end_g,
                        fillcolor="yellow", opacity=0.12, line_width=0,
                        annotation_text="TLE Gap", annotation_position="top left",
                    )

            # EW event markers
            if not ew_ev.empty:
                valid_ser = series[series["lambda_deg"].notna() & series["epoch_utc"].notna()]
                ser_t_ns  = valid_ser["epoch_utc"].astype(np.int64).values if len(valid_ser) > 1 else np.array([0])
                ser_l     = valid_ser["lambda_deg"].values                  if len(valid_ser) > 1 else np.array([0.0])

                conf_ew = ew_ev[ew_ev["confirmed"] == True]
                uncf_ew = ew_ev[ew_ev["confirmed"] == False]

                for subset, color, sym, label in [
                    (conf_ew,  "red",    "triangle-up",      "EW 確認"),
                    (uncf_ew,  "orange", "triangle-up-open", "EW 未確認"),
                ]:
                    if subset.empty:
                        continue
                    ev_t_ns = subset["epoch_utc"].astype(np.int64).values
                    ev_l    = np.interp(ev_t_ns, ser_t_ns, ser_l)
                    ev_d    = subset["drift_after"].values if "drift_after" in subset.columns else np.full(len(subset), np.nan)

                    hover = [
                        f"<b>EW {'✓' if r['confirmed'] else '?'}</b><br>"
                        f"{str(r['epoch_utc'])[:19]} UTC<br>"
                        f"drift: {r.get('drift_before', np.nan):.4f} → "
                        f"{r.get('drift_after', np.nan):.4f} °/day<br>"
                        f"Δdrift: {r.get('delta_drift', np.nan):.4f} °/day"
                        for _, r in subset.iterrows()
                    ]
                    for panel_row, ydata in [(1, ev_l), (2, ev_d)]:
                        fig_lon.add_trace(go.Scatter(
                            x=subset["epoch_utc"], y=ydata,
                            mode="markers", name=label,
                            marker=dict(color=color, size=13, symbol=sym,
                                        line=dict(width=1.5, color="white")),
                            hovertext=hover, hoverinfo="text",
                            showlegend=(panel_row == 1),
                        ), row=panel_row, col=1)

            fig_lon.update_layout(
                template="plotly_dark", height=620,
                legend=dict(orientation="h", y=-0.08),
                margin=dict(l=60, r=30, t=60, b=60),
            )
            st.plotly_chart(fig_lon, use_container_width=True, key=f"geo_lon_{norad_id}")

            if not ew_ev.empty:
                conf_summary = ew_ev[ew_ev["confirmed"] == True]
                if not conf_summary.empty:
                    st.caption(
                        f"共 {len(conf_summary)} 次確認 EW 機動  |  "
                        f"最大 |Δdrift| = "
                        f"{conf_summary['delta_drift'].abs().max():.4f} °/day"
                    )

    # ── Tab 2: Inclination / NS ─────────────────────────────────────────────
    with tab_inc:
        if series.empty:
            st.info("無 TLE 時間序列。")
        else:
            ns_ev = events[events["type"] == "NS"] if not events.empty else pd.DataFrame()

            fig_inc = go.Figure()
            fig_inc.add_trace(go.Scatter(
                x=series["epoch_utc"], y=series["inclination_deg"],
                name="Inclination (°)", line=dict(color="violet", width=1.5),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>i = %{y:.4f}°<extra></extra>",
            ))

            if not ns_ev.empty:
                valid_ser = series[series["inclination_deg"].notna() & series["epoch_utc"].notna()]
                ser_t_ns  = valid_ser["epoch_utc"].astype(np.int64).values if len(valid_ser) > 1 else np.array([0])
                ser_i     = valid_ser["inclination_deg"].values             if len(valid_ser) > 1 else np.array([0.0])

                conf_ns = ns_ev[ns_ev["confirmed"] == True]
                uncf_ns = ns_ev[ns_ev["confirmed"] == False]

                for subset, color, sym, label in [
                    (conf_ns,  "magenta", "star",      "NS 確認"),
                    (uncf_ns,  "pink",    "star-open", "NS 未確認"),
                ]:
                    if subset.empty:
                        continue
                    ev_t_ns = subset["epoch_utc"].astype(np.int64).values
                    ev_i    = np.interp(ev_t_ns, ser_t_ns, ser_i)

                    hover = [
                        f"<b>NS {'✓' if r['confirmed'] else '?'}</b><br>"
                        f"{str(r['epoch_utc'])[:19]} UTC<br>"
                        f"i: {r.get('i_before', np.nan):.4f}° → {r.get('i_after', np.nan):.4f}°<br>"
                        f"Δi = {r.get('delta_i_deg', np.nan):.4f}°<br>"
                        f"ΔRAAN_res = {r.get('delta_raan_residual_deg', np.nan):.3f}°"
                        for _, r in subset.iterrows()
                    ]
                    fig_inc.add_trace(go.Scatter(
                        x=subset["epoch_utc"], y=ev_i,
                        mode="markers", name=label,
                        marker=dict(color=color, size=15, symbol=sym,
                                    line=dict(width=1.5, color="white")),
                        hovertext=hover, hoverinfo="text",
                    ))

            fig_inc.update_layout(
                template="plotly_dark", height=420,
                yaxis_title="Inclination (°)",
                legend=dict(orientation="h"),
                margin=dict(l=60, r=30, t=50, b=40),
            )
            st.plotly_chart(fig_inc, use_container_width=True, key=f"geo_inc_{norad_id}")

            if not ns_ev.empty:
                st.markdown("**NS 事件詳情**")
                ns_cols = [c for c in [
                    "epoch_utc", "confirmed", "i_before", "i_after",
                    "delta_i_deg", "delta_raan_residual_deg",
                ] if c in ns_ev.columns]
                fmt_ns = {k: "{:.4f}" for k in
                          ["i_before", "i_after", "delta_i_deg", "delta_raan_residual_deg"]}
                st.dataframe(ns_ev[ns_cols].style.format(fmt_ns), use_container_width=True)

    # ── Tab 3: Event table ──────────────────────────────────────────────────
    with tab_table:
        if events.empty:
            st.info("此衛星在選定期間無偵測到機動事件。")
        else:
            _ICONS = {
                "EW": "🔴", "NS": "🟣", "REPOSITIONING": "🟡",
                "DISPOSAL": "⚫", "TLE_GAP": "🟤",
            }
            disp = events.copy()
            disp.insert(0, "", disp["type"].map(lambda t: _ICONS.get(t, "⚪")))
            fmt_tbl = {k: "{:.4f}" for k in
                       ["drift_before", "drift_after", "delta_drift",
                        "i_before", "i_after", "delta_i_deg"]}
            fmt_tbl["sma_km"] = "{:.2f}"
            tbl_cols = [c for c in [
                "", "epoch_utc", "type", "confirmed",
                "drift_before", "drift_after", "delta_drift",
                "i_before", "i_after", "delta_i_deg",
                "sma_km", "gap_days",
            ] if c in disp.columns]
            st.dataframe(disp[tbl_cols].style.format(fmt_tbl),
                         use_container_width=True, key=f"geo_tbl_{norad_id}")
            st.download_button(
                "📥 下載事件 CSV",
                data=events.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"geo_events_{norad_id}_{start_date}_{end_date}.csv",
                mime="text/csv",
            )



# ==========================================
# IDS Verification Constants & Helpers
# ==========================================

# NORAD ID → satellite name (IDS / DORIS missions only)
_IDS_NORAD_MAP = {
    22076: "topex-poseidon",   # decommissioned 2006-01-18
    26997: "jason-1",          # decommissioned 2013-07-01
    27386: "envisat",          # contact lost   2012-04-08
    33105: "jason-2",          # decommissioned 2019-10-01
    36508: "cryosat-2",        # active
    37781: "hy-2a",            # decommissioned 2023-01-10
    39086: "saral",            # active (drifting since 2016-07)
    41240: "jason-3",          # active
    41335: "sentinel-3a",      # active
    43437: "sentinel-3b",      # active
    44750: "hy-2c",            # active
    46984: "sentinel-6a",      # active
    48621: "hy-2d",            # active
    54754: "swot",             # active
}

# satellite name → 3-letter IDS/CDDIS directory code
_IDS_SAT_CODES = {
    "topex-poseidon": "top",
    "jason-1": "ja1",
    "envisat": "en1",
    "jason-2": "ja2",
    "cryosat-2": "cs2",
    "hy-2a": "h2a",
    "saral": "srl",
    "jason-3": "ja3",
    "sentinel-3a": "s3a",
    "sentinel-3b": "s3b",
    "hy-2c": "h2c",
    "sentinel-6a": "s6a",
    "hy-2d": "h2d",
    "swot": "swo",
}

# Operational periods and status for UI guidance
# data_start / data_end are ISO date strings; data_end=None means currently active
_IDS_SAT_INFO = {
    "topex-poseidon": {
        "status": "decommissioned",
        "data_start": "1992-09-25",
        "data_end":   "2006-01-18",
        "note": "First altimetry satellite with DORIS. Decommissioned 2006-01-18.",
    },
    "jason-1": {
        "status": "decommissioned",
        "data_start": "2001-12-07",
        "data_end":   "2013-07-01",
        "note": "TOPEX/Poseidon successor. Decommissioned 2013-07-01.",
    },
    "envisat": {
        "status": "decommissioned",
        "data_start": "2002-03-01",
        "data_end":   "2012-04-08",
        "note": "ESA Earth-observation satellite. Contact lost 2012-04-08.",
    },
    "jason-2": {
        "status": "decommissioned",
        "data_start": "2008-06-20",
        "data_end":   "2019-10-01",
        "note": "OSTM/Jason-2. Decommissioned 2019-10-01.",
    },
    "hy-2a": {
        "status": "decommissioned",
        "data_start": "2011-08-16",
        "data_end":   "2023-01-10",
        "note": "Chinese ocean-observation satellite. DORIS operations ended ~2023.",
    },
    "cryosat-2": {
        "status": "active",
        "data_start": "2010-04-08",
        "data_end":   None,
        "note": "ESA ice-monitoring satellite. Still operational.",
    },
    "saral": {
        "status": "active",
        "data_start": "2013-02-25",
        "data_end":   None,
        "note": "CNES/ISRO altimetry. In drifting orbit since 2016-07-21.",
    },
    "jason-3": {
        "status": "active",
        "data_start": "2016-01-17",
        "data_end":   None,
        "note": "Primary ocean-altimetry reference mission.",
    },
    "sentinel-3a": {
        "status": "active",
        "data_start": "2016-02-16",
        "data_end":   None,
        "note": "ESA Copernicus ocean/land surface mission.",
    },
    "sentinel-3b": {
        "status": "active",
        "data_start": "2018-04-25",
        "data_end":   None,
        "note": "ESA Copernicus — companion to Sentinel-3A.",
    },
    "hy-2c": {
        "status": "active",
        "data_start": "2020-09-21",
        "data_end":   None,
        "note": "Chinese ocean-observation satellite.",
    },
    "sentinel-6a": {
        "status": "active",
        "data_start": "2020-11-21",
        "data_end":   None,
        "note": "Sentinel-6 Michael Freilich — Jason-3 successor.",
    },
    "hy-2d": {
        "status": "active",
        "data_start": "2021-05-19",
        "data_end":   None,
        "note": "Chinese ocean-observation satellite.",
    },
    "swot": {
        "status": "active",
        "data_start": "2022-12-16",
        "data_end":   None,
        "note": "Surface Water & Ocean Topography mission (NASA/CNES).",
    },
}

_CDDIS_BASE = "https://cddis.nasa.gov/archive/doris/products/orbits/ssa"
_ILRS_MANEUVER_URL = "https://ilrs.gsfc.nasa.gov/data_and_products/predictions/maneuver.html"
_IDS_EPOCH_REF = pd.Timestamp("1949-12-31 00:00:00", tz="UTC")


def _ids_slugify(name: str) -> str:
    s = name.strip().lower().replace("_", "-")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return {"topexposeidon": "topex-poseidon", "cryosat2": "cryosat-2"}.get(s, s)


@st.cache_data(ttl=3600)
def fetch_ilrs_satellite_list():
    try:
        resp = requests.get(_ILRS_MANEUVER_URL, timeout=15)
        resp.raise_for_status()
        from html.parser import HTMLParser

        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.sats = []
                self._in_li = False
                self._cur = ""

            def handle_starttag(self, tag, attrs):
                if tag == "li":
                    self._in_li = True
                    self._cur = ""

            def handle_endtag(self, tag):
                if tag == "li" and self._in_li:
                    self.sats.append(self._cur.strip())
                    self._in_li = False

            def handle_data(self, data):
                if self._in_li:
                    self._cur += data

        p = _P()
        p.feed(resp.text)
        return sorted({s for s in p.sats if s})
    except Exception:
        return list(_IDS_NORAD_MAP.values())


def _ids_list_cddis_dir(session, url):
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return re.findall(r'href="([^"]+)"', resp.text)
    except Exception:
        return []


def _ids_select_sp3_files(hrefs, sat_code, start_dt, end_dt):
    from datetime import timedelta as _td
    pat = re.compile(
        r"ssa" + re.escape(sat_code.lower()) + r"\d{2}\.b(\d{2})(\d{3})\.e(\d{2})(\d{3})\.\w+\.sp3",
        re.IGNORECASE,
    )
    selected = []
    for href in hrefs:
        fname = href.rstrip("/").split("/")[-1]
        m = pat.match(fname.lower())
        if not m:
            continue
        by, bdoy = int(m.group(1)), int(m.group(2))
        ey, edoy = int(m.group(3)), int(m.group(4))
        by += 2000 if by < 80 else 1900
        ey += 2000 if ey < 80 else 1900
        try:
            b_dt = datetime(by, 1, 1) + _td(days=bdoy - 1)
            e_dt = datetime(ey, 1, 1) + _td(days=edoy - 1)
        except Exception:
            continue
        if e_dt >= start_dt and b_dt <= end_dt:
            selected.append(href)
    return selected


def _ids_decompress_Z(src_path):
    import gzip, subprocess, shutil as _sh
    src_path = Path(src_path)
    dst = Path(str(src_path)[:-2]) if str(src_path).endswith(".Z") else src_path
    if dst.exists():
        return dst
    try:
        subprocess.run(["uncompress", "-f", str(src_path)], check=True, capture_output=True)
        if dst.exists():
            return dst
    except Exception as _e:
        print(f"[ids] uncompress failed for {src_path.name}: {_e}", flush=True)
    try:
        with gzip.open(src_path, "rb") as fin, open(dst, "wb") as fout:
            _sh.copyfileobj(fin, fout)
        return dst
    except Exception as _e:
        print(f"[ids] gzip fallback failed for {src_path.name}: {_e}", flush=True)
    return src_path


def _ids_download_sp3(session, url, dest_path, force=False):
    dest_path = Path(dest_path)
    sp3_path = Path(str(dest_path)[:-2]) if str(dest_path).endswith(".Z") else dest_path
    if not force and sp3_path.exists():
        return sp3_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(65536):
            fh.write(chunk)
    if str(dest_path).endswith(".Z"):
        return _ids_decompress_Z(dest_path)
    return dest_path


def parse_ids_sp3_file(path):
    rows = []
    current_epoch = None
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if line.startswith("*"):
                parts = line[1:].split()
                if len(parts) >= 6:
                    try:
                        current_epoch = pd.Timestamp(
                            int(parts[0]), int(parts[1]), int(parts[2]),
                            int(parts[3]), int(parts[4]), int(float(parts[5])),
                            tz="UTC",
                        )
                    except Exception:
                        current_epoch = None
            elif line.startswith("P") and current_epoch is not None:
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        rows.append({
                            "epoch": current_epoch,
                            "sp3_sat": parts[0][1:].upper(),
                            "x_km": float(parts[1]),
                            "y_km": float(parts[2]),
                            "z_km": float(parts[3]),
                        })
                    except Exception:
                        pass
    return pd.DataFrame(rows)


def _ids_eci_to_ric(r_ref, v_ref):
    r_hat = r_ref / np.linalg.norm(r_ref)
    h = np.cross(r_ref, v_ref)
    c_hat = h / np.linalg.norm(h)
    i_hat = np.cross(c_hat, r_hat)
    return np.column_stack([r_hat, i_hat, c_hat])


def propagate_from_db_elements(con, norad_id, epochs):
    import math
    from sgp4.api import Satrec, WGS84, jday

    df_all = con.execute(
        """SELECT epoch_utc, sma_km, inclination_deg, raan_deg, argp_deg,
                  mean_anomaly_deg, eccentricity
           FROM raw_tle_archive WHERE norad_id = ? ORDER BY epoch_utc ASC""",
        [int(norad_id)],
    ).df()
    if df_all.empty:
        df_all = con.execute(
            """SELECT date_tag AS epoch_utc, sma_km, inclination_deg, raan_deg, argp_deg,
                      mean_anomaly_deg, eccentricity
               FROM tle_table WHERE norad_id = ? ORDER BY date_tag ASC""",
            [int(norad_id)],
        ).df()
    if df_all.empty:
        return pd.DataFrame()

    df_all["epoch_utc"] = pd.to_datetime(df_all["epoch_utc"], utc=True, errors="coerce")
    rows = []
    for t in epochs:
        t_ts = pd.Timestamp(t)
        if t_ts.tzinfo is None:
            t_ts = t_ts.tz_localize("UTC")
        valid = df_all[df_all["epoch_utc"] <= t_ts]
        tle_row = valid.iloc[-1] if not valid.empty else df_all.iloc[0]
        try:
            n_rad_min = math.sqrt(MU / float(tle_row["sma_km"]) ** 3) * 60.0
            _ep = pd.Timestamp(tle_row["epoch_utc"])
            if _ep.tzinfo is None:
                _ep = _ep.tz_localize("UTC")
            tle_epoch_days = (_ep - _IDS_EPOCH_REF).total_seconds() / 86400.0
            sat = Satrec()
            sat.sgp4init(
                WGS84, "i", int(norad_id),
                tle_epoch_days,
                0.0, 0.0, 0.0,
                float(tle_row["eccentricity"]),
                math.radians(float(tle_row["argp_deg"])),
                math.radians(float(tle_row["inclination_deg"])),
                math.radians(float(tle_row["mean_anomaly_deg"])),
                n_rad_min,
                math.radians(float(tle_row["raan_deg"])),
            )
            jd, fr = jday(
                t_ts.year, t_ts.month, t_ts.day,
                t_ts.hour, t_ts.minute,
                t_ts.second + t_ts.microsecond / 1e6,
            )
            err, r, v = sat.sgp4(jd, fr)
            if err != 0:
                continue
            rows.append({
                "epoch": t_ts,
                "sgp4_error": err,
                "x_km": r[0], "y_km": r[1], "z_km": r[2],
                "vx_km_s": v[0], "vy_km_s": v[1], "vz_km_s": v[2],
                "tle_epoch_used": tle_row["epoch_utc"],
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


def compute_ids_ric_residuals(tle_states, ids_states):
    tle = tle_states.copy()
    ids = ids_states.copy()
    tle["epoch"] = pd.to_datetime(tle["epoch"], utc=True)
    ids["epoch"] = pd.to_datetime(ids["epoch"], utc=True)
    merged = pd.merge_asof(
        ids.sort_values("epoch"),
        tle.sort_values("epoch"),
        on="epoch",
        tolerance=pd.Timedelta("120s"),
        direction="nearest",
        suffixes=("_ids", "_tle"),
    )
    rows = []
    for _, r in merged.iterrows():
        if any(pd.isna(r.get(c, float("nan"))) for c in ["x_km_tle", "y_km_tle", "z_km_tle"]):
            continue
        r_tle = np.array([r["x_km_tle"], r["y_km_tle"], r["z_km_tle"]])
        v_tle = np.array([r.get("vx_km_s", 0.0), r.get("vy_km_s", 0.0), r.get("vz_km_s", 0.0)])
        r_ids = np.array([r["x_km_ids"], r["y_km_ids"], r["z_km_ids"]])
        dr = r_ids - r_tle
        if np.linalg.norm(r_tle) < 1e-9 or np.linalg.norm(v_tle) < 1e-9:
            continue
        basis = _ids_eci_to_ric(r_tle, v_tle)
        ric = basis.T @ dr
        rows.append({
            "epoch": r["epoch"],
            "dr_km": float(np.linalg.norm(dr)),
            "radial_km": float(ric[0]),
            "in_track_km": float(ric[1]),
            "cross_track_km": float(ric[2]),
            "tle_epoch_used": r.get("tle_epoch_used"),
            "sgp4_error": int(r.get("sgp4_error", 0)),
        })
    return pd.DataFrame(rows)


def _flush_ids_cluster(candidates, buf_rows, buf_start, buf_end):
    c = pd.DataFrame(buf_rows)
    candidates.append({
        "start_epoch": buf_start,
        "end_epoch": buf_end,
        "peak_dr_km": float(c["dr_km"].max()),
        "peak_abs_in_track_km": float(c["in_track_km"].abs().max()),
        "peak_abs_radial_km": float(c["radial_km"].abs().max()),
        "peak_abs_cross_track_km": float(c["cross_track_km"].abs().max()),
        "n_points": len(c),
    })


def detect_ids_maneuvers(
    resid_df,
    radial_thr=0.3,
    in_track_thr=1.0,
    cross_track_thr=0.3,
    zscore_thr=3.0,
    window=12,
    min_sep_hrs=6,
):
    if resid_df.empty:
        return pd.DataFrame()
    df = resid_df.copy().sort_values("epoch").reset_index(drop=True)

    def _rz(x, w):
        s = pd.Series(x)
        mu_ = s.rolling(w, min_periods=3, center=True).mean()
        sd_ = s.rolling(w, min_periods=3, center=True).std().fillna(1e-9)
        return ((s - mu_) / sd_).fillna(0).values

    z_r = _rz(df["radial_km"].abs().values, window)
    z_i = _rz(df["in_track_km"].abs().values, window)
    z_c = _rz(df["cross_track_km"].abs().values, window)
    df["_flag"] = (
        (df["radial_km"].abs() > radial_thr)
        | (df["in_track_km"].abs() > in_track_thr)
        | (df["cross_track_km"].abs() > cross_track_thr)
        | (z_r > zscore_thr)
        | (z_i > zscore_thr)
        | (z_c > zscore_thr)
    )

    min_sep = pd.Timedelta(hours=min_sep_hrs)
    candidates, buf_rows, buf_start, buf_end = [], [], None, None
    for _, row in df.iterrows():
        if row["_flag"]:
            if buf_start is None:
                buf_start, buf_end, buf_rows = row["epoch"], row["epoch"], [row]
            elif row["epoch"] - buf_end > min_sep:
                _flush_ids_cluster(candidates, buf_rows, buf_start, buf_end)
                buf_start, buf_end, buf_rows = row["epoch"], row["epoch"], [row]
            else:
                buf_rows.append(row)
                buf_end = row["epoch"]
        else:
            if buf_start is not None:
                _flush_ids_cluster(candidates, buf_rows, buf_start, buf_end)
                buf_start = None
    if buf_start is not None:
        _flush_ids_cluster(candidates, buf_rows, buf_start, buf_end)
    return pd.DataFrame(candidates)


def load_ids_precomputed(sat_name):
    path = Path(f"./output_data/residuals/{sat_name}/residuals.csv")
    if path.exists():
        df = pd.read_csv(path)
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        return df
    return pd.DataFrame()

st.set_page_config(page_title="Satellite Maneuver Analytics", layout="wide")

try:
    params = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()

    def _get_param(name, default):
        val = params.get(name, default)
        if isinstance(val, list):
            return val[0] if val else default
        return val

    default_norad = _get_param("norad", "49336, 42738, 42917, 42965, 62876")
    default_start = _get_param("start", "2024-01-01")
    default_end = _get_param("end", "2026-03-30")

except Exception:
    default_norad = "49336, 42738, 42917, 42965, 62876"
    default_start = "2024-01-01"
    default_end = "2026-03-30"

st.title("🛰️ 衛星機動偵測與軌道分析系統")
st.markdown("整合 **F10.7 solar flux**、自適應機動偵測與 **DuckDB / space_db** 歷史數據庫。")

with st.sidebar:
    page = st.radio("分析模式", ["LEO / MEO 分析", "GEO 機動分析"], horizontal=True)
    st.divider()

    if page == "LEO / MEO 分析":
        raw_input = st.text_input("NORAD ID (多筆請用逗號隔開)", value=default_norad)
        target_ids = [id.strip() for id in raw_input.split(",") if id.strip()]
        col_d1, col_d2 = st.columns(2)
        start_d = col_d1.date_input("開始日期", datetime.fromisoformat(default_start))
        end_d = col_d2.date_input("結束日期", datetime.fromisoformat(default_end))
        st.divider()
        st.subheader("繪圖設定")
        ma_val = st.slider("移動平均視窗 (MA)", 1, 14, 1)
        show_sampled = st.checkbox("顯示原始取樣點", value=True)
        run_btn = st.button("執行分析", type="primary")
        # GEO defaults (unused in this page)
        geo_norad_id = 36032
        geo_start_d  = datetime.fromisoformat("2026-03-01").date()
        geo_end_d    = datetime.fromisoformat("2026-05-02").date()
    else:
        geo_norad_id = int(st.number_input(
            "NORAD ID (GEO 衛星)", value=36032, min_value=1, step=1,
            help="預設 36032：Apr 3-4 兩段式 EW 機動 + Apr 21 NS 修正（驗證範例）",
        ))
        col_g1, col_g2 = st.columns(2)
        geo_start_d = col_g1.date_input("開始日期", datetime.fromisoformat("2026-03-01"))
        geo_end_d   = col_g2.date_input("結束日期",  datetime.fromisoformat("2026-05-02"))
        # LEO defaults (unused in this page)
        raw_input = ""; target_ids = []; run_btn = False
        start_d = end_d = datetime.fromisoformat("2026-01-01").date()
        ma_val = 1; show_sampled = False

# GEO page renders here and stops; LEO code below is not reached
if page == "GEO 機動分析":
    render_geo_page(
        geo_norad_id,
        geo_start_d.strftime("%Y-%m-%d"),
        geo_end_d.strftime("%Y-%m-%d"),
    )
    st.stop()

shared_layout = dict(
    margin=dict(l=80, r=80, t=80, b=40),
    hovermode="x unified",
    template="plotly_dark",
    xaxis=dict(showgrid=True, gridcolor="gray", range=[start_d, end_d]),
)

if run_btn:
    if not target_ids:
        st.error("請輸入至少一個 NORAD ID，例如 66666")
    else:
        f107_data = fetch_f107_data()

        for i, satellite_id in enumerate(target_ids):
            with st.container():
                st.subheader(f"📡 衛星分析報告: NORAD {satellite_id}")

                df_raw = load_data(satellite_id, start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d"))
                if df_raw.empty:
                    st.warning(f"⚠️ 找不到 NORAD ID {satellite_id} 的資料，跳過分析。")
                    st.divider()
                    continue

                df_processed, event_df, used_mult = detect_maneuvers_refined_adaptive(df_raw)

                alt_km_avg = float(df_processed["sma_km"].mean() - R_EARTH) if not df_processed.empty else None
                if alt_km_avg is not None and alt_km_avg > 1200:
                    st.warning(
                        f"⚠️ NORAD {satellite_id}：軌道高度 {alt_km_avg:.0f} km 屬 MEO/GEO，"
                        "大氣阻力可忽略，機動偵測靈敏度較低，建議人工確認。"
                    )

                if not f107_data.empty:
                    left_df = ensure_datetime64ns(df_processed, "epoch").sort_values("epoch").reset_index(drop=True)
                    right_df = ensure_datetime64ns(f107_data, "epoch").sort_values("epoch").reset_index(drop=True)

                    df_final = pd.merge_asof(
                        left_df,
                        right_df,
                        on="epoch",
                        direction="nearest"
                    )
                else:
                    df_final = df_processed.copy()

                df_final = calculate_ric_deltas(df_final)
                df_final["sma_visual"] = df_final["sma_km"].rolling(window=ma_val, min_periods=1, center=True).mean()

                tab_analysis, tab_ric, tab_3d, tab_delta, tab_spiral, tab_longaxis, tab_meme, tab_galileo, tab_ids = st.tabs(
                    ["📊 趨勢分析", "🚀 RIC 速度變化", "🌍 3D 軌道", "Δ 計算", "𖦹 Spiral Polar", "⬯ 長軸旋轉週期", "🛰️ MEME 殘差", "🪐 Galileo SP3", "🌍 IDS 驗證"]
                )

                with tab_analysis:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("數據點", len(df_final))
                    m2.metric("機動次數", int(df_final["is_maneuver"].sum()))
                    if not event_df.empty:
                        m3.metric("最大 Δa", f"{event_df['sma_delta'].max():.4f} km")
                    else:
                        m3.metric("最大 Δa", "N/A")

                    fig_2d = go.Figure()
                    fig_2d.add_trace(go.Scatter(
                        x=df_final["epoch"], y=df_final["sma_visual"], name="SMA (km)",
                        line=dict(color="#00CCFF")
                    ))

                    if "f107" in df_final.columns:
                        fig_2d.add_trace(go.Scatter(
                            x=df_final["epoch"], y=df_final["f107"], name="F10.7",
                            yaxis="y2", line=dict(dash="dot", color="orange"), opacity=0.4
                        ))

                    manv_pts = df_final[df_final["is_maneuver"]]
                    fig_2d.add_trace(go.Scatter(
                        x=manv_pts["epoch"], y=manv_pts["sma_km"], mode="markers",
                        marker=dict(color="red", size=10, symbol="star"), name="Maneuver"
                    ))

                    if show_sampled:
                        fig_2d.add_trace(go.Scatter(
                            x=df_raw["epoch"], y=df_raw["sma_km"], mode="markers",
                            marker=dict(color="white", size=4, opacity=0.4),
                            name="Raw Samples"
                        ))

                    fig_2d.update_layout(
                        template="plotly_dark",
                        height=450,
                        yaxis2=dict(overlaying="y", side="right"),
                        legend=dict(orientation="h"),
                    )
                    st.plotly_chart(fig_2d, width="stretch", key=f"fig_2d_{satellite_id}_{i}")

                with tab_ric:
                    df_final["is_dv_v_event"] = detect_ric_events(df_final, "dv_intrack", threshold_mult=6.0, alt_km=alt_km_avg)
                    df_final["is_dv_w_event"] = detect_ric_events(df_final, "dv_crosstrack", threshold_mult=6.0, alt_km=alt_km_avg)

                    fig_ric = go.Figure()
                    fig_ric.add_trace(go.Bar(
                        x=df_final["epoch"], y=df_final["dv_intrack"],
                        name="In-Track (m/s)", marker_color="lime", opacity=0.7
                    ))
                    fig_ric.add_trace(go.Scatter(
                        x=df_final["epoch"], y=df_final["dv_crosstrack"],
                        name="Cross-Tr (m/s)", line=dict(color="magenta", width=1.5)
                    ))

                    v_events = df_final[df_final["is_dv_v_event"]]
                    if not v_events.empty:
                        fig_ric.add_trace(go.Scatter(
                            x=v_events["epoch"], y=v_events["dv_intrack"],
                            mode="markers", name="In-Track Maneuver",
                            marker=dict(color="lime", size=12, symbol="triangle-up", line=dict(width=1, color="white")),
                            hoverinfo="text",
                            text=[f"Time: {t}<br>dv_v: {v:.4f} m/s" for t, v in zip(v_events["epoch"], v_events["dv_intrack"])]
                        ))

                    w_events = df_final[df_final["is_dv_w_event"]]
                    if not w_events.empty:
                        fig_ric.add_trace(go.Scatter(
                            x=w_events["epoch"], y=w_events["dv_crosstrack"],
                            mode="markers", name="Cross-Track Maneuver",
                            marker=dict(color="magenta", size=10, symbol="circle", line=dict(width=1, color="white")),
                            hoverinfo="text",
                            text=[f"Time: {t}<br>dv_w: {w:.4f} m/s" for t, w in zip(w_events["epoch"], w_events["dv_crosstrack"])]
                        ))

                    fig_ric.update_layout(
                        **shared_layout,
                        title=dict(text=f"NORAD {satellite_id} RIC 速度變化分析 (m/s)", y=0.95),
                        yaxis=dict(title=dict(text="Delta-V (m/s)"), zeroline=True, zerolinecolor="white"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        bargap=0.5,
                    )
                    st.plotly_chart(fig_ric, width="stretch", key=f"fig_ric_{satellite_id}_{i}")

                with tab_3d:
                    fig_3d = plot_3d_orbit_scene_multi(df_raw, satellite_id)
                    st.plotly_chart(fig_3d, width="stretch", key=f"fig_3d_{satellite_id}_{i}")


                with tab_delta:
                    st.subheader(f"Δ 計算（SMA 與軌道角度） - NORAD {satellite_id}")
                    df_delta = compute_delta_table(df_raw)

                    st.write("前 10 筆 Δ 資料預覽：")
                    st.dataframe(
                        df_delta.head(10).style.format(
                            {
                                "sma_km": "{:.3f}",
                                "delta_sma_km": "{:.5f}",
                                "inclination_deg": "{:.4f}",
                                "raan_deg": "{:.4f}",
                                "argp_deg": "{:.4f}",
                                "mean_anomaly_deg": "{:.4f}",
                                "delta_inclination_deg": "{:.5f}",
                                "delta_raan_deg": "{:.5f}",
                                "delta_argp_deg": "{:.5f}",
                                "delta_mean_anomaly_deg": "{:.5f}",
                            }
                        ),
                        width="stretch",
                    )

                    csv_name = f"norad_{satellite_id}_angle_sma_deltas_{start_d.strftime('%Y-%m-%d')}_to_{end_d.strftime('%Y-%m-%d')}.csv"
                    csv_bytes = df_delta.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                    st.download_button(
                        label="📥 下載 Δ 資料 (CSV)",
                        data=csv_bytes,
                        file_name=csv_name,
                        mime="text/csv",
                        key=f"delta_csv_{satellite_id}_{i}",
                    )

                    st.markdown("### Δ 時序圖")

                    fig_sma = go.Figure()
                    fig_sma.add_trace(go.Scatter(
                        x=df_delta["date"], y=df_delta["sma_km"],
                        mode="lines+markers", name="sma_km",
                        line=dict(color="#00CCFF"), marker=dict(size=4)
                    ))
                    fig_sma.update_layout(template="plotly_dark", height=300, yaxis_title="sma_km (km)", margin=dict(l=60, r=30, t=50, b=40))
                    st.plotly_chart(fig_sma, width="stretch", key=f"delta_sma_{satellite_id}_{i}")

                    fig_dsma = go.Figure()
                    fig_dsma.add_trace(go.Scatter(
                        x=df_delta["date"], y=df_delta["delta_sma_km"],
                        mode="lines+markers", name="Δsma_km",
                        line=dict(color="#FFA500"), marker=dict(size=4)
                    ))
                    fig_dsma.add_hline(y=0.0, line_dash="dash", line_color="gray", opacity=0.5)
                    fig_dsma.update_layout(template="plotly_dark", height=300, yaxis_title="Δ sma_km (km)", margin=dict(l=60, r=30, t=50, b=40))
                    st.plotly_chart(fig_dsma, width="stretch", key=f"delta_dsma_{satellite_id}_{i}")

                    for col in angle_cols:
                        delta_col = f"delta_{col}"
                        fig_ang = go.Figure()
                        fig_ang.add_trace(go.Scatter(
                            x=df_delta["date"], y=df_delta[delta_col],
                            mode="lines+markers", name=f"Δ {col}",
                            line=dict(color="#ADFF2F"), marker=dict(size=4)
                        ))
                        fig_ang.add_hline(y=0.0, line_dash="dash", line_color="gray", opacity=0.5)
                        fig_ang.update_layout(template="plotly_dark", height=250, yaxis_title=f"Δ {col} (deg)", margin=dict(l=60, r=30, t=50, b=40))
                        st.plotly_chart(fig_ang, width="stretch", key=f"delta_{col}_{satellite_id}_{i}")

                with tab_spiral:
                    st.subheader(f"Spiral Polar 軌道角度分佈 - NORAD {satellite_id}")
                    df_spiral, days_since_start, theta_time, r_spiral, t_norm = prepare_spiral_polar_data(df_raw)

                    fig_spiral = make_subplots(
                        rows=2,
                        cols=2,
                        specs=[[{"type": "polar"}, {"type": "polar"}], [{"type": "polar"}, {"type": "polar"}]],
                        subplot_titles=angle_cols,
                    )

                    for idx, col in enumerate(angle_cols):
                        row_idx = idx // 2 + 1
                        col_idx = idx % 2 + 1
                        theta_angle = np.deg2rad(df_spiral[col].values % 360.0)

                        fig_spiral.add_trace(
                            go.Scatterpolar(
                                theta=np.rad2deg(theta_angle),
                                r=r_spiral,
                                mode="markers",
                                marker=dict(
                                    size=6,
                                    color=t_norm,
                                    colorscale=spiral_cmap,
                                    showscale=True,
                                    colorbar=dict(title="Norm time", ticks="outside"),
                                ),
                                name=col,
                            ),
                            row=row_idx,
                            col=col_idx,
                        )

                        fig_spiral.update_polars(
                            radialaxis=dict(showticklabels=False, showgrid=True),
                            angularaxis=dict(direction="counterclockwise"),
                            row=row_idx,
                            col=col_idx,
                        )

                    fig_spiral.update_layout(
                        template="plotly_dark",
                        showlegend=False,
                        height=700,
                        margin=dict(l=40, r=40, t=90, b=40),
                        title_text=f"NORAD {satellite_id} Angular Elements (Spiral Polar)<br>{start_d} to {end_d}",
                    )
                    st.plotly_chart(fig_spiral, width="stretch", key=f"spiral_{satellite_id}_{i}")

                with tab_longaxis:
                    st.subheader(f"長軸旋轉週期分析 - NORAD {satellite_id}")

                    if not {"epoch_jd", "raan_deg", "argp_deg"}.issubset(df_raw.columns):
                        st.warning("此資料集缺少 epoch_jd / raan_deg / argp_deg，無法做長軸分析。")
                    else:
                        sec_per_sidereal_day = 86164.0905
                        sidereal_days_per_year = 366.24
                        sec_per_sidereal_year = sidereal_days_per_year * sec_per_sidereal_day

                        t_jd = df_raw["epoch_jd"].to_numpy()
                        t_sec = (t_jd - t_jd[0]) * sec_per_sidereal_day
                        t_days = t_sec / sec_per_sidereal_day

                        psi_deg_wrapped = (df_raw["raan_deg"] + df_raw["argp_deg"]).to_numpy()
                        psi_rad_unwrapped = np.unwrap(np.deg2rad(psi_deg_wrapped))
                        psi_deg_unwrapped = np.rad2deg(psi_rad_unwrapped)

                        t_sec_centered = t_sec - t_sec.mean()
                        t_days_centered = t_days - t_days.mean()

                        st.write(f"樣本數: {len(df_raw)}, 覆蓋時間: {(t_sec.max() - t_sec.min())/sec_per_sidereal_day:.2f} 恆星日")

                        T_min = 0.5 * sec_per_sidereal_year
                        T_max = 5.0 * sec_per_sidereal_year
                        w_min = 2.0 * np.pi / T_max
                        w_max = 2.0 * np.pi / T_min
                        n_freq = 5000
                        omega = np.linspace(w_min, w_max, n_freq)

                        y = psi_rad_unwrapped - psi_rad_unwrapped.mean()

                        pgram = lombscargle(
                            t_sec_centered,
                            y,
                            omega,
                            precenter=False,
                            normalize=True
                        )

                        idx_peak = np.argmax(pgram)
                        omega_peak = omega[idx_peak]

                        period_sec = 2.0 * np.pi / omega_peak
                        period_days_sidereal = period_sec / sec_per_sidereal_day
                        period_years_sidereal = period_sec / sec_per_sidereal_year

                        omega_peak_day = omega_peak * sec_per_sidereal_day

                        def model_longaxis(t_day, a, b, A, B):
                            return a * t_day + b + A * np.sin(omega_peak_day * t_day) + B * np.cos(omega_peak_day * t_day)

                        psi_deg_unwrapped_centered = psi_deg_unwrapped - psi_deg_unwrapped.mean()

                        try:
                            p0 = [0.0, 0.0, 1.0, 1.0]
                            params, _ = curve_fit(
                                model_longaxis,
                                t_days_centered,
                                psi_deg_unwrapped_centered,
                                p0=p0
                            )
                            a_fit, b_fit, A_fit, B_fit = params
                            amp_fit = np.sqrt(A_fit**2 + B_fit**2)

                            st.write("擬合參數的物理意義：")
                            st.write("從 TLE 取出：Line of Apsides 長軸方向角 ψ(t)=升交點赤經 Ω(t)+近地點幅角 ω(t)")
                            st.write("a：線性斜率（deg / 恆星日），表示長軸平均旋轉速率。")
                            st.write("b：截距（deg），擬合時的初始偏移。")
                            st.write("A：正弦項係數（deg），主頻週期下的正弦分量。")
                            st.write("B：餘弦項係數（deg），主頻週期下的餘弦分量。")
                            st.write(f"a (deg/恆星日) = {a_fit:.6e}")
                            st.write(f"b (deg)        = {b_fit:.6e}")
                            st.write(f"A (deg)        = {A_fit:.6e}")
                            st.write(f"B (deg)        = {B_fit:.6e}")
                            st.write(f"週期項總振幅 ≈ {amp_fit:.3f} deg")

                            psi_fit_centered = model_longaxis(t_days_centered, *params)
                            psi_fit = psi_fit_centered + psi_deg_unwrapped.mean()
                        except Exception as e:
                            st.error(f"長軸模型擬合失敗: {e}")
                            psi_fit = None

                        fig_wrap = go.Figure()
                        fig_wrap.add_trace(go.Scatter(
                            x=df_raw["date_tag"], y=psi_deg_wrapped,
                            mode="lines+markers", name="ψ (wrapped, deg)",
                            marker=dict(size=3)
                        ))
                        fig_wrap.update_layout(template="plotly_dark", height=300, yaxis_title="ψ (deg, wrapped)", margin=dict(l=60, r=30, t=40, b=40))
                        st.plotly_chart(fig_wrap, use_container_width=True, key=f"longaxis_wrapped_{satellite_id}_{i}")

                        fig_unwrap = go.Figure()
                        fig_unwrap.add_trace(go.Scatter(
                            x=df_raw["date_tag"], y=psi_deg_unwrapped,
                            mode="lines+markers", name="ψ (unwrapped, deg)",
                            marker=dict(size=3)
                        ))
                        if psi_fit is not None:
                            fig_unwrap.add_trace(go.Scatter(
                                x=df_raw["date_tag"], y=psi_fit,
                                mode="lines",
                                name=f"Fit: linear + main low-freq (T≈{period_years_sidereal:.3f} sidereal yr)",
                                line=dict(color="red", width=2)
                            ))
                        fig_unwrap.update_layout(template="plotly_dark", height=320, yaxis_title="ψ (deg, unwrapped)", margin=dict(l=60, r=30, t=40, b=40))
                        st.plotly_chart(fig_unwrap, use_container_width=True, key=f"longaxis_unwrapped_{satellite_id}_{i}")

                        periods_years_sidereal = (2.0 * np.pi / omega) / sec_per_sidereal_year
                        fig_ls = go.Figure()
                        fig_ls.add_trace(go.Scatter(
                            x=periods_years_sidereal, y=pgram,
                            mode="lines", name="LS Power"
                        ))
                        fig_ls.add_vline(
                            x=period_years_sidereal,
                            line_dash="dash",
                            line_color="red",
                            annotation_text=f"Peak ≈ {period_years_sidereal:.3f} yr",
                            annotation_position="top right"
                        )
                        fig_ls.update_layout(
                            template="plotly_dark",
                            height=320,
                            xaxis_title="Period (sidereal years)",
                            yaxis_title="Lomb-Scargle Power",
                            margin=dict(l=60, r=30, t=40, b=40),
                        )
                        st.plotly_chart(fig_ls, use_container_width=True, key=f"longaxis_ls_{satellite_id}_{i}")

                with tab_meme:
                    st.subheader(f"MEME 星曆殘差分析 (NORAD {satellite_id})")
                    st.caption(
                        "資料來源：`compare_tle_vs_ephemeris.py` 產生的 `data/comparison/residuals_*.csv`。"
                        "機動偵測依據 RTN 殘差的逐步突變（MAD z-score），"
                        "精度比 TLE-SMA 差分高 1–2 個量級。"
                    )

                    resid_df = load_meme_residuals(
                        satellite_id,
                        start_d.strftime("%Y-%m-%d"),
                        end_d.strftime("%Y-%m-%d"),
                    )

                    if resid_df.empty:
                        st.info(
                            "此衛星在選定期間無 MEME 殘差資料。\n\n"
                            "請先執行：\n```\npython compare_tle_vs_ephemeris.py\n```"
                        )
                    else:
                        rtn_events = detect_maneuvers_rtn(resid_df)

                        # ── 指標列 ──────────────────────────────────────────
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("殘差點數", f"{len(resid_df):,}")
                        c2.metric("MEME 偵測機動", len(rtn_events))
                        c3.metric("最大 pos_err (km)", f"{resid_df['pos_err_km'].max():.2f}")
                        tle_age_val = resid_df["tle_age_days"].iloc[0] if "tle_age_days" in resid_df.columns else None
                        c4.metric("TLE 年齡 (天)", f"{tle_age_val:.1f}" if tle_age_val is not None else "N/A")

                        # ── RTN 殘差三面板圖 ─────────────────────────────────
                        fig_rtn = make_subplots(
                            rows=3, cols=1,
                            shared_xaxes=True,
                            subplot_titles=[
                                "Along-Track dr_t (km)  ← in-plane 機動指標",
                                "Cross-Track dr_n (km)  ← out-of-plane 機動指標",
                                "3D Pos Error RSS (km)",
                            ],
                            vertical_spacing=0.08,
                        )

                        fig_rtn.add_trace(go.Scatter(
                            x=resid_df["t"], y=resid_df["dr_t_km"],
                            name="dr_t", line=dict(color="deepskyblue", width=1.2),
                        ), row=1, col=1)

                        fig_rtn.add_trace(go.Scatter(
                            x=resid_df["t"], y=resid_df["dr_n_km"],
                            name="dr_n", line=dict(color="mediumseagreen", width=1.2),
                        ), row=2, col=1)

                        fig_rtn.add_trace(go.Scatter(
                            x=resid_df["t"], y=resid_df["pos_err_km"],
                            name="pos_err", line=dict(color="gold", width=1.2),
                        ), row=3, col=1)

                        # 標記機動事件
                        if not rtn_events.empty:
                            inplane  = rtn_events[rtn_events["type"] == "in-plane"]
                            outplane = rtn_events[rtn_events["type"] == "out-of-plane"]

                            for evs, panel_row, val_col, color, label in [
                                (inplane,  1, "dr_t_km", "red",     "順軌道機動"),
                                (outplane, 2, "dr_n_km", "magenta", "交叉軌道機動"),
                            ]:
                                if not evs.empty:
                                    fig_rtn.add_trace(go.Scatter(
                                        x=evs["epoch"],
                                        y=evs[val_col],
                                        mode="markers",
                                        marker=dict(color=color, size=13, symbol="star",
                                                    line=dict(width=1, color="white")),
                                        name=label,
                                        hovertemplate=(
                                            "<b>%{x}</b><br>"
                                            f"{val_col}: %{{y:.2f}} km<br>"
                                            "step: %{customdata[0]:.3f} km<br>"
                                            "z: %{customdata[1]:.1f}"
                                        ),
                                        customdata=evs[["step_km", "z_score"]].values,
                                    ), row=panel_row, col=1)

                        fig_rtn.update_layout(
                            template="plotly_dark",
                            height=680,
                            legend=dict(orientation="h", y=-0.05),
                            margin=dict(l=60, r=30, t=60, b=50),
                        )
                        st.plotly_chart(fig_rtn, use_container_width=True,
                                        key=f"meme_rtn_{satellite_id}_{i}")

                        # ── 事件表 ──────────────────────────────────────────
                        if not rtn_events.empty:
                            st.subheader("偵測到的 MEME 機動事件")
                            fmt = {
                                "dr_t_km":        "{:.2f}",
                                "dr_n_km":        "{:.2f}",
                                "dr_r_km":        "{:.2f}",
                                "pos_err_km":     "{:.2f}",
                                "step_km":        "{:.3f}",
                                "step_rate_km_h": "{:.3f}",
                                "z_score":        "{:.1f}",
                                "tle_age_days":   "{:.2f}",
                            }
                            display_cols = [c for c in [
                                "epoch", "type", "dr_t_km", "dr_n_km", "dr_r_km",
                                "pos_err_km", "step_km", "step_rate_km_h", "z_score", "tle_age_days",
                            ] if c in rtn_events.columns]
                            st.dataframe(
                                rtn_events[display_cols].style.format(fmt),
                                use_container_width=True,
                                key=f"meme_events_{satellite_id}_{i}",
                            )
                        else:
                            st.success("在選定期間未偵測到 RTN 突變事件（z > 5）。")

                        # ── TLE vs MEME 偵測結果比較 ─────────────────────────
                        st.subheader("TLE 偵測 vs MEME 偵測對比")
                        tle_cnt  = int(df_final["is_maneuver"].sum())
                        meme_cnt = len(rtn_events)
                        comp_df  = pd.DataFrame({
                            "方法":   ["TLE-SMA 差分", "MEME RTN 突變"],
                            "偵測機動數": [tle_cnt, meme_cnt],
                            "資料精度": ["~km（TLE 衍生）", "sub-km（精密星曆）"],
                            "時間解析度": ["每日（重採樣）", f"~{(resid_df['t'].diff().dt.total_seconds().median()/60):.0f} 分鐘"],
                        })
                        st.table(comp_df)

                with tab_galileo:
                    st.subheader(f"Galileo SP3 精密星曆殘差分析 (NORAD {satellite_id})")
                    st.caption(
                        "資料來源：`compare_galileo_sp3_vs_tle.py` 產生的 `data/galileo_comparison/residuals_*.csv`。"
                        "精密 SP3 精度 sub-cm；RTN 殘差反映 TLE-SGP4 誤差；"
                        "突變即為機動信號。適用於 MEO 高度 Galileo 星座（~29,600 km）。"
                    )

                    gal_resid_df = load_galileo_sp3_residuals(
                        satellite_id,
                        start_d.strftime("%Y-%m-%d"),
                        end_d.strftime("%Y-%m-%d"),
                    )

                    if gal_resid_df.empty:
                        st.info(
                            "此衛星在選定期間無 Galileo SP3 殘差資料。\n\n"
                            "請先執行：\n```\npython galileo_pipeline.py\n```\n"
                            "或只執行比對步驟：\n```\npython galileo_pipeline.py --skip-download --skip-index --skip-export\n```"
                        )
                        if alt_km_avg is not None and alt_km_avg < 10_000:
                            st.warning(
                                f"注意：NORAD {satellite_id} 軌道高度約 {alt_km_avg:.0f} km，"
                                "非 MEO 高度，此 Galileo SP3 分析頁面僅適用於 Galileo 衛星。"
                            )
                    else:
                        gal_events = detect_maneuvers_rtn(gal_resid_df)

                        # ── 指標列 ──────────────────────────────────────────
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("殘差點數", f"{len(gal_resid_df):,}")
                        c2.metric("SP3 偵測機動", len(gal_events))
                        c3.metric("最大 pos_err (km)", f"{gal_resid_df['pos_err_km'].max():.2f}")
                        median_age = gal_resid_df["tle_age_days"].median() if "tle_age_days" in gal_resid_df.columns else None
                        c4.metric("TLE 中位年齡 (天)", f"{median_age:.1f}" if median_age is not None else "N/A")

                        # ── RTN 三面板圖 ─────────────────────────────────────
                        fig_gal = make_subplots(
                            rows=3, cols=1,
                            shared_xaxes=True,
                            subplot_titles=[
                                "Along-Track dr_t (km)  ← 順軌道誤差（機動主指標）",
                                "Cross-Track dr_n (km)  ← 交叉軌道誤差（面外機動）",
                                "3D Pos Error RSS (km)",
                            ],
                            vertical_spacing=0.08,
                        )

                        fig_gal.add_trace(go.Scatter(
                            x=gal_resid_df["t"], y=gal_resid_df["dr_t_km"],
                            name="dr_t", line=dict(color="deepskyblue", width=1.2),
                        ), row=1, col=1)

                        fig_gal.add_trace(go.Scatter(
                            x=gal_resid_df["t"], y=gal_resid_df["dr_n_km"],
                            name="dr_n", line=dict(color="mediumseagreen", width=1.2),
                        ), row=2, col=1)

                        fig_gal.add_trace(go.Scatter(
                            x=gal_resid_df["t"], y=gal_resid_df["pos_err_km"],
                            name="pos_err", line=dict(color="gold", width=1.2),
                        ), row=3, col=1)

                        if not gal_events.empty:
                            inplane  = gal_events[gal_events["type"] == "in-plane"]
                            outplane = gal_events[gal_events["type"] == "out-of-plane"]

                            for evs, panel_row, val_col, color, label in [
                                (inplane,  1, "dr_t_km", "red",     "順軌道機動"),
                                (outplane, 2, "dr_n_km", "magenta", "交叉軌道機動"),
                            ]:
                                if not evs.empty:
                                    fig_gal.add_trace(go.Scatter(
                                        x=evs["epoch"],
                                        y=evs[val_col],
                                        mode="markers",
                                        marker=dict(color=color, size=13, symbol="star",
                                                    line=dict(width=1, color="white")),
                                        name=label,
                                        hovertemplate=(
                                            "<b>%{x}</b><br>"
                                            f"{val_col}: %{{y:.3f}} km<br>"
                                            "step: %{customdata[0]:.4f} km<br>"
                                            "z: %{customdata[1]:.1f}"
                                        ),
                                        customdata=evs[["step_km", "z_score"]].values,
                                    ), row=panel_row, col=1)

                        fig_gal.update_layout(
                            template="plotly_dark",
                            height=680,
                            legend=dict(orientation="h", y=-0.05),
                            margin=dict(l=60, r=30, t=60, b=50),
                        )
                        st.plotly_chart(fig_gal, use_container_width=True,
                                        key=f"gal_rtn_{satellite_id}_{i}")

                        # ── 事件表 ──────────────────────────────────────────
                        if not gal_events.empty:
                            st.subheader("偵測到的 Galileo SP3 機動事件")
                            fmt = {
                                "dr_t_km":        "{:.3f}",
                                "dr_n_km":        "{:.3f}",
                                "dr_r_km":        "{:.3f}",
                                "pos_err_km":     "{:.3f}",
                                "step_km":        "{:.4f}",
                                "step_rate_km_h": "{:.4f}",
                                "z_score":        "{:.1f}",
                                "tle_age_days":   "{:.2f}",
                            }
                            display_cols = [c for c in [
                                "epoch", "type", "dr_t_km", "dr_n_km", "dr_r_km",
                                "pos_err_km", "step_km", "step_rate_km_h", "z_score", "tle_age_days",
                            ] if c in gal_events.columns]
                            st.dataframe(
                                gal_events[display_cols].style.format(fmt),
                                use_container_width=True,
                                key=f"gal_events_{satellite_id}_{i}",
                            )
                        else:
                            st.success("在選定期間未偵測到 Galileo SP3 RTN 突變事件（z > 5）。")

                        # ── 三方法偵測對比 ───────────────────────────────────
                        st.subheader("三方法偵測對比")
                        tle_cnt   = int(df_final["is_maneuver"].sum())
                        meme_cnt_local = len(
                            load_meme_residuals(satellite_id, start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d"))
                        )
                        gal_cnt   = len(gal_events)
                        tri_df = pd.DataFrame({
                            "方法":       ["TLE-SMA 差分", "MEME RTN 突變", "Galileo SP3 RTN"],
                            "偵測機動數":  [tle_cnt, meme_cnt_local, gal_cnt],
                            "資料精度":   ["~km（TLE 衍生）", "sub-km（SpaceX MEME）", "sub-cm（IGS MGEX SP3）"],
                            "軌道高度":   ["LEO/MEO 通用", "LEO Starlink", "MEO Galileo"],
                        })
                        st.table(tri_df)

                with tab_ids:
                    st.subheader("🌍 IDS 精密軌道驗證")
                    st.caption(
                        "使用 International DORIS Service (IDS) SP3 精密星曆作為 Ground Truth，"
                        "與本地 TLE 資料庫比對，驗證軌道機動偵測。"
                    )
                    sat_name_ids = _IDS_NORAD_MAP.get(int(satellite_id))

                    def _ids_table_rows():
                        rows = []
                        for _k, _n in _IDS_NORAD_MAP.items():
                            _inf = _IDS_SAT_INFO.get(_n, {})
                            _st  = _inf.get("status", "unknown")
                            _ds  = _inf.get("data_start", "")
                            _de  = _inf.get("data_end")
                            rows.append({
                                "NORAD ID":  _k,
                                "衛星名稱":  _n,
                                "IDS 代碼":  _IDS_SAT_CODES.get(_n, ""),
                                "狀態":      "🟢 運作中" if _st == "active" else "🔴 已退役",
                                "資料起始":  _ds,
                                "資料截止":  _de if _de else "至今",
                                "備註":      _inf.get("note", ""),
                            })
                        return rows

                    if sat_name_ids is None:
                        st.info(
                            f"衛星 NORAD {satellite_id} 不在 IDS 支援清單中。"
                            f"支援衛星：{', '.join(sorted(_IDS_NORAD_MAP.values()))}"
                        )
                        with st.expander("📋 IDS 支援衛星"):
                            st.dataframe(
                                pd.DataFrame(_ids_table_rows()),
                                use_container_width=True,
                                hide_index=True,
                            )
                    else:
                        sat_code_ids = _IDS_SAT_CODES.get(sat_name_ids, "")
                        _info = _IDS_SAT_INFO.get(sat_name_ids, {})
                        _status      = _info.get("status", "unknown")
                        _data_start  = _info.get("data_start", "")
                        _data_end    = _info.get("data_end")   # None = still active
                        _note        = _info.get("note", "")

                        _period_str = (
                            f"{_data_start} ～ {_data_end}"
                            if _data_end else
                            f"{_data_start} ～ 至今"
                        )
                        if _status == "decommissioned":
                            st.warning(
                                f"⚠️ NORAD {satellite_id} → **{sat_name_ids}** "
                                f"(IDS 代碼: `{sat_code_ids}`)  |  "
                                f"已退役，資料期間：{_period_str}  |  {_note}"
                            )
                            # Clamp the working date range to the satellite's data window
                            _ids_start = _data_start
                            _ids_end   = _data_end
                            if start_d.strftime("%Y-%m-%d") > _data_end:
                                st.error(
                                    f"您選擇的起始日期 {start_d} 晚於此衛星的最後資料日期 "
                                    f"({_data_end})。請將日期範圍調整至 {_data_start} ～ {_data_end}。"
                                )
                        else:
                            st.success(
                                f"✅ NORAD {satellite_id} → **{sat_name_ids}** "
                                f"(IDS 代碼: `{sat_code_ids}`)  |  "
                                f"資料期間：{_period_str}  |  {_note}"
                            )
                            _ids_start = _data_start
                            _ids_end   = None

                        ids_source = st.radio(
                            "資料來源",
                            [
                                "預計算殘差 (./output_data/residuals/)",
                                "即時從 CDDIS 下載 SP3（需 NASA Earthdata 帳號）",
                            ],
                            horizontal=True,
                            key=f"ids_src_{satellite_id}_{i}",
                        )
                        resid_df_ids = pd.DataFrame()

                        # Clamp UI date range to satellite's actual data window
                        _ui_start = start_d.strftime("%Y-%m-%d")
                        _ui_end   = end_d.strftime("%Y-%m-%d")
                        _eff_start = max(_ui_start, _ids_start) if _ids_start else _ui_start
                        _eff_end   = (
                            min(_ui_end, _ids_end) if _ids_end else _ui_end
                        )

                        if "預計算" in ids_source:
                            resid_df_ids = load_ids_precomputed(sat_name_ids)
                            if resid_df_ids.empty:
                                _local_sp3_dir = Path(f"./output_data/sp3/{sat_name_ids}/")
                                _local_sp3 = (
                                    sorted(_local_sp3_dir.glob("*.sp3"))
                                    if _local_sp3_dir.exists() else []
                                )
                                if _local_sp3:
                                    st.info(
                                        f"找不到預計算殘差，但發現 **{len(_local_sp3)}** 個本地 SP3 檔案"
                                        f"（`{_local_sp3_dir}`）。"
                                        f"點擊按鈕直接從本地 SP3 計算殘差，不需要 Earthdata 帳號。"
                                    )
                                    if st.button(
                                        "⚙️ 從本地 SP3 計算殘差",
                                        key=f"ids_local_{satellite_id}_{i}",
                                    ):
                                        with st.spinner("解析本地 SP3 並計算殘差..."):
                                            try:
                                                _sp3f = []
                                                _pr2 = st.progress(0)
                                                for _n2, _sp3p in enumerate(_local_sp3):
                                                    _df2 = parse_ids_sp3_file(_sp3p)
                                                    if not _df2.empty:
                                                        _sp3f.append(
                                                            _df2[_df2["sp3_sat"] == sat_code_ids.upper()]
                                                        )
                                                    _pr2.progress((_n2 + 1) / len(_local_sp3))
                                                if _sp3f:
                                                    _ids2 = (
                                                        pd.concat(_sp3f)
                                                        .drop_duplicates("epoch")
                                                        .sort_values("epoch")
                                                    )
                                                    _ids2["epoch"] = pd.to_datetime(_ids2["epoch"], utc=True)
                                                    st.info(f"SP3 共 {len(_ids2)} 筆，開始 TLE 傳播...")
                                                    _c2 = duckdb.connect(DB_PATH, read_only=True)
                                                    _tle2 = propagate_from_db_elements(
                                                        _c2, int(satellite_id), _ids2["epoch"].tolist()
                                                    )
                                                    _c2.close()
                                                    if _tle2.empty:
                                                        st.error("TLE 傳播失敗：資料庫無軌道要素。")
                                                    else:
                                                        resid_df_ids = compute_ids_ric_residuals(_tle2, _ids2)
                                                        if not resid_df_ids.empty:
                                                            _od = Path(f"./output_data/residuals/{sat_name_ids}")
                                                            _od.mkdir(parents=True, exist_ok=True)
                                                            resid_df_ids.to_csv(_od / "residuals.csv", index=False)
                                                            st.success(
                                                                f"完成！{len(resid_df_ids)} 筆殘差已儲存至 "
                                                                f"`{_od}/residuals.csv`"
                                                            )
                                                        else:
                                                            st.warning("殘差計算結果為空（SP3 與 TLE 無重疊時間）。")
                                                else:
                                                    st.warning(
                                                        f"本地 SP3 中找不到 `{sat_code_ids.upper()}` 衛星資料。"
                                                    )
                                            except Exception as _e_loc:
                                                st.error(f"從本地 SP3 計算失敗：{_e_loc}")
                                else:
                                    st.warning(
                                        f"找不到預計算殘差：`./output_data/residuals/{sat_name_ids}/residuals.csv`"
                                    )
                                    st.info("請切換至右側「即時從 CDDIS 下載 SP3」，或在終端機執行：")
                                    st.code(
                                        f"cd tle_ids_maneuver_pipeline\n"
                                        f"python run_pipeline.py --config config.yaml --satellite {sat_name_ids} "
                                        f"--start {_eff_start} --end {_eff_end}",
                                        language="bash",
                                    )
                            else:
                                mask = (
                                    (resid_df_ids["epoch"] >= pd.Timestamp(_eff_start, tz="UTC"))
                                    & (resid_df_ids["epoch"] <= pd.Timestamp(_eff_end, tz="UTC"))
                                )
                                resid_df_ids = resid_df_ids[mask].copy()
                                st.info(f"載入 {len(resid_df_ids)} 筆殘差（{_eff_start} ～ {_eff_end}）")
                        else:
                            col_eu, col_ep = st.columns(2)
                            ed_user = col_eu.text_input(
                                "NASA Earthdata 帳號",
                                value=os.getenv("EARTHDATA_USERNAME", ""),
                                key=f"ed_u_{satellite_id}_{i}",
                            )
                            ed_pass = col_ep.text_input(
                                "NASA Earthdata 密碼",
                                type="password",
                                value=os.getenv("EARTHDATA_PASSWORD", ""),
                                key=f"ed_p_{satellite_id}_{i}",
                            )
                            if st.button(
                                "🔄 下載 SP3 並計算殘差",
                                key=f"ids_go_{satellite_id}_{i}",
                            ):
                                if not ed_user or not ed_pass:
                                    st.error("請輸入 NASA Earthdata 帳號與密碼。")
                                else:
                                    with st.spinner("連接 CDDIS 下載 SP3..."):
                                        try:
                                            from requests.adapters import HTTPAdapter
                                            from urllib3.util.retry import Retry as _Retry
                                            _sess = requests.Session()
                                            _sess.mount(
                                                "https://",
                                                HTTPAdapter(max_retries=_Retry(total=3, backoff_factor=1)),
                                            )
                                            _sess.auth = (ed_user, ed_pass)
                                            dir_url = f"{_CDDIS_BASE}/{sat_code_ids}/"
                                            hrefs_all = _ids_list_cddis_dir(_sess, dir_url)
                                            sp3_hrefs = [h for h in hrefs_all if ".sp3" in h.lower()]
                                            s_dt = datetime.strptime(_eff_start, "%Y-%m-%d")
                                            e_dt_dl = datetime.strptime(_eff_end, "%Y-%m-%d")
                                            sel = _ids_select_sp3_files(
                                                sp3_hrefs, sat_code_ids, s_dt, e_dt_dl
                                            )
                                            if not sel:
                                                st.warning("找不到符合日期範圍的 SP3 檔案。")
                                            else:
                                                sp3_frames = []
                                                _prog = st.progress(0)
                                                for _n, href in enumerate(sel):
                                                    fname = href.rstrip("/").split("/")[-1]
                                                    url_sp3 = (
                                                        href
                                                        if href.startswith("http")
                                                        else dir_url + fname
                                                    )
                                                    dest = Path(
                                                        f"./output_data/sp3/{sat_name_ids}/{fname}"
                                                    )
                                                    lp = _ids_download_sp3(_sess, url_sp3, dest)
                                                    _df_sp3 = parse_ids_sp3_file(lp)
                                                    if not _df_sp3.empty:
                                                        sp3_frames.append(
                                                            _df_sp3[
                                                                _df_sp3["sp3_sat"]
                                                                == sat_code_ids.upper()
                                                            ]
                                                        )
                                                    _prog.progress((_n + 1) / len(sel))
                                                if sp3_frames:
                                                    ids_st = (
                                                        pd.concat(sp3_frames)
                                                        .drop_duplicates("epoch")
                                                        .sort_values("epoch")
                                                    )
                                                    ids_st["epoch"] = pd.to_datetime(
                                                        ids_st["epoch"], utc=True
                                                    )
                                                    st.info(f"SP3 共 {len(ids_st)} 筆，開始 TLE 傳播...")
                                                    _con_ids = duckdb.connect(DB_PATH, read_only=True)
                                                    tle_st = propagate_from_db_elements(
                                                        _con_ids, satellite_id,
                                                        ids_st["epoch"].tolist(),
                                                    )
                                                    _con_ids.close()
                                                    if tle_st.empty:
                                                        st.error("TLE 傳播失敗：資料庫無軌道要素。")
                                                    else:
                                                        resid_df_ids = compute_ids_ric_residuals(
                                                            tle_st, ids_st
                                                        )
                                                        if not resid_df_ids.empty:
                                                            _out = Path(
                                                                f"./output_data/residuals/{sat_name_ids}"
                                                            )
                                                            _out.mkdir(parents=True, exist_ok=True)
                                                            resid_df_ids.to_csv(
                                                                _out / "residuals.csv", index=False
                                                            )
                                                            st.success(
                                                                f"完成！{len(resid_df_ids)} 筆殘差已儲存至 "
                                                                f"`{_out}/residuals.csv`"
                                                            )
                                                        else:
                                                            st.warning("殘差計算結果為空。")
                                                else:
                                                    st.warning("SP3 解析後無有效資料。")
                                        except Exception as _e_ids:
                                            st.error(f"CDDIS 錯誤：{_e_ids}")

                        if not resid_df_ids.empty:
                            ids_maneuvers = detect_ids_maneuvers(resid_df_ids)

                            fig_ids = make_subplots(
                                rows=3, cols=1, shared_xaxes=True,
                                subplot_titles=["Radial (km)", "In-Track (km)", "Cross-Track (km)"],
                                vertical_spacing=0.06,
                            )
                            for _rn, _cn, _cl in [
                                (1, "radial_km", "#FF6B6B"),
                                (2, "in_track_km", "#4ECDC4"),
                                (3, "cross_track_km", "#45B7D1"),
                            ]:
                                fig_ids.add_trace(
                                    go.Scatter(
                                        x=resid_df_ids["epoch"],
                                        y=resid_df_ids[_cn],
                                        name=_cn.replace("_km", ""),
                                        line=dict(color=_cl, width=1),
                                    ),
                                    row=_rn, col=1,
                                )
                            if not ids_maneuvers.empty:
                                for _, _cand in ids_maneuvers.iterrows():
                                    for _rn in [1, 2, 3]:
                                        fig_ids.add_vrect(
                                            x0=_cand["start_epoch"],
                                            x1=_cand["end_epoch"],
                                            fillcolor="rgba(255,165,0,0.2)",
                                            line_width=0,
                                            row=_rn, col=1,
                                        )
                            fig_ids.update_layout(
                                template="plotly_dark",
                                height=600,
                                title_text=f"IDS vs TLE  RIC 殘差 — {sat_name_ids}",
                                showlegend=True,
                            )
                            st.plotly_chart(
                                fig_ids, use_container_width=True,
                                key=f"ids_ric_{satellite_id}_{i}",
                            )

                            mc1, mc2, mc3 = st.columns(3)
                            mc1.metric("殘差資料點", len(resid_df_ids))
                            mc2.metric("IDS 偵測機動", len(ids_maneuvers))
                            mc3.metric(
                                "最大 In-Track",
                                f"{resid_df_ids['in_track_km'].abs().max():.3f} km",
                            )

                            if not ids_maneuvers.empty:
                                st.subheader("IDS 機動候選事件")
                                _fmt_ids = {
                                    c: "{:.3f}"
                                    for c in [
                                        "peak_dr_km",
                                        "peak_abs_in_track_km",
                                        "peak_abs_radial_km",
                                        "peak_abs_cross_track_km",
                                    ]
                                }
                                st.dataframe(
                                    ids_maneuvers.style.format(_fmt_ids),
                                    use_container_width=True,
                                    key=f"ids_tbl_{satellite_id}_{i}",
                                )
                                st.download_button(
                                    "⬇ 下載 IDS 機動清單 (CSV)",
                                    data=ids_maneuvers.to_csv(index=False).encode("utf-8-sig"),
                                    file_name=(
                                        f"ids_maneuvers_{sat_name_ids}_"
                                        f"{start_d.strftime('%Y-%m-%d')}_{end_d.strftime('%Y-%m-%d')}.csv"
                                    ),
                                    mime="text/csv",
                                    key=f"dl_ids_{satellite_id}_{i}",
                                )

                            if not event_df.empty:
                                st.subheader("偵測方法比較")
                                st.table(
                                    pd.DataFrame({
                                        "方法": ["TLE-SMA 差分", "IDS SP3 RIC 殘差"],
                                        "偵測機動數": [
                                            int(df_final["is_maneuver"].sum()),
                                            len(ids_maneuvers),
                                        ],
                                        "資料精度": [
                                            "~km（TLE 衍生）",
                                            "sub-cm（IDS DORIS SP3）",
                                        ],
                                        "Ground Truth": ["否", "是（DORIS 精密軌道）"],
                                    })
                                )

                        with st.expander("📋 IDS 支援衛星一覽"):
                            st.dataframe(
                                pd.DataFrame(_ids_table_rows()),
                                use_container_width=True,
                                hide_index=True,
                            )

                st.divider()
else:
    st.info("請於左側面板設定參數並點擊『執行分析』開始。")