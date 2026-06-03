from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple
import time
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
import yaml
import duckdb

# local functions
import constellation_planes

# Starlink shell yaml 參數檔案
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "shells_config.yaml")


@st.cache_data(ttl=360)  # 1 小時後自動失效
def load_shell_configs(config_path: str = CONFIG_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def build_plane_config_from_yaml(shell_cfg: dict,
                                 db_path: str,
                                 tle_table: str,
                                 start_dt: datetime,
                                 end_dt: datetime) -> Tuple[Dict[str, List[int]], int]:
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str   = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 這裡假設 get_plane_to_norad_and_name 只回傳 mapping: {pid: {"norad_list":[...], ...}, ...}
    plane_mapping = constellation_planes.get_plane_to_norad_and_name(
        SHELL_NAME       = shell_cfg["shell_name"],
        DB_PATH          = db_path,
        TLE_TABLE        = tle_table,
        start_date       = start_str,
        end_date         = end_str,
        SHELL_ALT_KM     = shell_cfg["shell_alt_km"],
        ALT_TOL_KM       = shell_cfg["alt_tol_km"],
        INC_REF_DEG      = shell_cfg["inc_ref_deg"],
        INC_TOL_DEG      = shell_cfg["inc_tol_deg"],
        NUM_PLANES       = shell_cfg["num_planes"],
        FILTER_STR       = shell_cfg.get("filter_str", "STARLINK-"),
        TARGET_PER_PLANE = shell_cfg.get("target_per_plane", None),
    )

    # 如果你真的在 constellation_planes 裡改成回傳 (mapping, total_sats)，
    # 可以這樣兼容：
    if isinstance(plane_mapping, tuple) and len(plane_mapping) == 2:
        plane_mapping, total_sats_raw = plane_mapping
    else:
        total_sats_raw = None

    plane_config_simple: Dict[str, List[int]] = {}
    total_sats = 0
    for pid, v in plane_mapping.items():
        key = f"plane_{pid:02d}"
        norads = [int(n) for n in v["norad_list"]]
        plane_config_simple[key] = norads
        total_sats += len(norads)

    # 如果上面有 total_sats_raw，就優先用；否則用我們算的 total_sats
    if total_sats_raw is not None:
        total_sats = int(total_sats_raw)

    return plane_config_simple, total_sats

# =================== 字體設定 ===================
plt.rcParams.update({
    'font.family': ['Microsoft JhengHei', 'DejaVu Sans', 'DejaVu Sans Mono'],
    'mathtext.fontset': 'dejavusans',
    'axes.unicode_minus': False,
    'font.size': 11,
})

# DuckDB 檔案
DB_PATH = r'C:/STK_Python/tle_database7.duckdb'
TLE_TABLE = "tle_table"


def compute_daily_mean_sma_all_planes(plane_config: Dict[str, List[int]],
                                      start_dt: datetime,
                                      end_dt: datetime,
                                      chunk_days: int = 7) -> pd.DataFrame:
    """
    對 DuckDB: 使用 date_tag (DATE) + sma_km
    回傳: df[date_tag, plane_id, sma_mean_km, sma_std_km, n_sats]
    """
    t0 = time.time()

    all_norads = sorted({int(nid) for lst in plane_config.values() for nid in lst})
    if not all_norads:
        return pd.DataFrame(columns=[
            "date_tag", "plane_id", "sma_mean_km", "sma_std_km", "n_sats"
        ])

    norad_to_plane: Dict[int, str] = {}
    for plane_id, lst in plane_config.items():
        for nid in lst:
            norad_to_plane.setdefault(int(nid), plane_id)

    conn = duckdb.connect(DB_PATH, read_only=True)
    placeholders = ",".join("?" for _ in all_norads)

    q = f"""
    SELECT
        date_tag,
        norad_id,
        sma_km
    FROM {TLE_TABLE}
    WHERE norad_id IN ({placeholders})
      AND date_tag BETWEEN ? AND ?
    ORDER BY date_tag, norad_id;
    """

    dfs = []
    cur_start = start_dt

    while cur_start <= end_dt:
        cur_end = min(cur_start + timedelta(days=chunk_days - 1), end_dt)

        start_str = cur_start.strftime("%Y-%m-%d")
        end_str   = cur_end.strftime("%Y-%m-%d")

        params = all_norads + [start_str, end_str]
        df_chunk = pd.read_sql_query(q, conn, params=params)

        if not df_chunk.empty:
            df_chunk["date_tag"] = pd.to_datetime(df_chunk["date_tag"]).dt.date
            df_chunk["plane_id"] = df_chunk["norad_id"].map(norad_to_plane)
            df_chunk = df_chunk[df_chunk["plane_id"].notna()].copy()
            dfs.append(df_chunk)

        cur_start = cur_end + timedelta(days=1)

    conn.close()

    if not dfs:
        return pd.DataFrame(columns=[
            "date_tag", "plane_id", "sma_mean_km", "sma_std_km", "n_sats"
        ])

    df = pd.concat(dfs, ignore_index=True)

    g = (
        df.groupby(["date_tag", "plane_id"])
          .agg(
              sma_mean_km=("sma_km", "mean"),
              sma_std_km=("sma_km", "std"),
              n_sats=("norad_id", "nunique"),
          )
          .reset_index()
          .sort_values(["date_tag", "plane_id"])
          .reset_index(drop=True)
    )

    st.write("SMA all planes cost:", time.time() - t0, "secs")
    return g


def compute_daily_mean_raan_all_planes(plane_config: Dict[str, List[int]],
                                       start_dt: datetime,
                                       end_dt: datetime,
                                       chunk_days: int = 7) -> pd.DataFrame:
    """
    對 DuckDB: 使用 date_tag (DATE) + raan_deg
    回傳: df[date_tag, plane_id, raan_deg, n_sats]
    """
    t0 = time.time()

    all_norads = sorted({int(nid) for lst in plane_config.values() for nid in lst})
    if not all_norads:
        return pd.DataFrame(columns=[
            "date_tag", "plane_id", "raan_deg", "n_sats"
        ])

    norad_to_plane: Dict[int, str] = {}
    for plane_id, lst in plane_config.items():
        for nid in lst:
            norad_to_plane.setdefault(int(nid), plane_id)

    conn = duckdb.connect(DB_PATH, read_only=True)
    placeholders = ",".join("?" for _ in all_norads)

    q = f"""
    SELECT
        date_tag,
        norad_id,
        raan_deg
    FROM {TLE_TABLE}
    WHERE norad_id IN ({placeholders})
      AND date_tag BETWEEN ? AND ?
    ORDER BY date_tag, norad_id;
    """

    dfs = []
    cur_start = start_dt

    while cur_start <= end_dt:
        cur_end = min(cur_start + timedelta(days=chunk_days - 1), end_dt)

        start_str = cur_start.strftime("%Y-%m-%d")
        end_str   = cur_end.strftime("%Y-%m-%d")

        params = all_norads + [start_str, end_str]
        df_chunk = pd.read_sql_query(q, conn, params=params)

        if not df_chunk.empty:
            df_chunk["date_tag"] = pd.to_datetime(df_chunk["date_tag"]).dt.floor("D")
            df_chunk["plane_id"] = df_chunk["norad_id"].map(norad_to_plane)
            df_chunk = df_chunk[df_chunk["plane_id"].notna()].copy()
            dfs.append(df_chunk)

        cur_start = cur_end + timedelta(days=1)

    conn.close()

    if not dfs:
        return pd.DataFrame(columns=[
            "date_tag", "plane_id", "raan_deg", "n_sats"
        ])

    df_raw = pd.concat(dfs, ignore_index=True)

    def circular_mean_deg(group: pd.DataFrame) -> pd.Series:
        angles = np.deg2rad(group["raan_deg"].values)
        sin_mean = np.sin(angles).mean()
        cos_mean = np.cos(angles).mean()
        mean_angle = np.arctan2(sin_mean, cos_mean)
        mean_deg = np.rad2deg(mean_angle) % 360.0
        return pd.Series({
            "raan_deg": mean_deg,
            "n_sats": group["norad_id"].nunique()
        })

    df_daily = (
        df_raw[["date_tag", "plane_id", "norad_id", "raan_deg"]]
        .groupby(["date_tag", "plane_id"], group_keys=False)
        .apply(circular_mean_deg, include_groups=False)
        .reset_index()
        .sort_values(["date_tag", "plane_id"])
        .reset_index(drop=True)
    )

    st.write("RAAN all planes cost:", time.time() - t0, "secs")
    return df_daily[["date_tag", "plane_id", "raan_deg", "n_sats"]]


def get_first_norad_per_plane(plane_config: Dict[str, List[int]]) -> Dict[str, int]:
    first_norad = {}
    for plane_id, norad_list in plane_config.items():
        if not norad_list:
            continue
        first_norad[plane_id] = int(sorted(norad_list)[-1])
    return first_norad


def load_representative_raan_from_db(
        first_norad_map: Dict[str, int],
        start_date: str,
        end_date: str,
) -> pd.DataFrame:
    if not first_norad_map:
        return pd.DataFrame()

    plane_ids = list(first_norad_map.keys())
    norad_list = [first_norad_map[p] for p in plane_ids]

    conn = duckdb.connect(DB_PATH, read_only=True)
    placeholders = ",".join("?" for _ in norad_list)

    q = f"""
    SELECT
        date_tag,
        norad_id,
        raan_deg
    FROM {TLE_TABLE}
    WHERE norad_id IN ({placeholders})
      AND date_tag BETWEEN ? AND ?
    ORDER BY date_tag, norad_id;
    """
    params = norad_list + [start_date, end_date]
    df = pd.read_sql_query(q, conn, params=params)
    conn.close()

    if df.empty:
        return df

    df["date_tag"] = pd.to_datetime(df["date_tag"]).dt.date
    norad_to_plane = {nid: pid for pid, nid in first_norad_map.items()}
    df["plane_id"] = df["norad_id"].map(norad_to_plane)

    return df[["date_tag", "plane_id", "norad_id", "raan_deg"]]


def compute_delta_raan_for_adjacent_planes(df_rep: pd.DataFrame,
                                           num_planes: int) -> pd.DataFrame:
    if df_rep.empty:
        return pd.DataFrame()

    df = df_rep.copy()
    df["date_tag"] = pd.to_datetime(df["date_tag"])
    df["plane_idx"] = df["plane_id"].str.extract(r'(\d+)', expand=False).astype(int)

    daily = (
        df.groupby(["date_tag", "plane_idx"], as_index=False)
          .agg({
              "plane_id": "first",
              "norad_id": "first",
              "raan_deg": "mean",
          })
    )

    daily["plane_idx_next"] = (daily["plane_idx"] + 1) % num_planes

    daily_i = daily.rename(columns={
        "plane_idx": "plane_idx_i",
        "plane_id": "plane_i",
        "norad_id": "norad_i",
        "raan_deg": "raan_i_deg",
    })
    daily_j = daily.rename(columns={
        "plane_idx": "plane_idx_j",
        "plane_id": "plane_j",
        "norad_id": "norad_j",
        "raan_deg": "raan_j_deg",
    })

    df_pair = pd.merge(
        daily_i,
        daily_j,
        left_on=["date_tag", "plane_idx_next"],
        right_on=["date_tag", "plane_idx_j"],
        how="inner",
    )

    diff = df_pair["raan_j_deg"] - df_pair["raan_i_deg"]
    df_pair["delta_raan_deg"] = (diff + 180.0) % 360.0 - 180.0

    df_delta = df_pair[[
        "date_tag",
        "plane_i", "plane_j",
        "norad_i", "norad_j",
        "raan_i_deg", "raan_j_deg",
        "delta_raan_deg",
    ]].sort_values(["date_tag", "plane_i"]).reset_index(drop=True)

    return df_delta


def build_delta_raan_adjacent_all_planes(
    plane_config: Dict[str, List[int]],
    start_d: date,
    end_d: date,
    num_planes: int,
) -> pd.DataFrame:
    """
    heavy 計算：從 plane_config + 日期區間 + num_planes 算出整個 ΔRAAN 表。
    只在按下「執行分析」時呼叫一次。
    """
    first_norad_map = get_first_norad_per_plane(plane_config)
    start_str = start_d.strftime("%Y-%m-%d")
    end_str   = end_d.strftime("%Y-%m-%d")

    df_rep = load_representative_raan_from_db(first_norad_map, start_str, end_str)
    df_delta_adj = compute_delta_raan_for_adjacent_planes(df_rep, num_planes=num_planes)
    return df_delta_adj


# =================== Streamlit App ===================
def main():
    st.title("Starlink Shell-1 TLE 分析面板")

    col1, col2 = st.columns(2)
    with col1:
        start_d = st.date_input("開始日期", value=date(2026, 2, 1))
    with col2:
        end_d = st.date_input("結束日期", value=date(2026, 3, 5))

    if start_d > end_d:
        st.error("開始日期必須早於結束日期")
        return

    start_dt = datetime.combine(start_d, datetime.min.time())
    end_dt = datetime.combine(end_d, datetime.max.time())

    cfg_all = load_shell_configs()

    st.sidebar.header("殼層配置")
    phase_names = list(cfg_all.keys())
    phase_sel = st.sidebar.selectbox("選擇 constellation 組態", phase_names, index=0)

    shells_dict = cfg_all[phase_sel]["shells"]
    shell_keys = list(shells_dict.keys())
    shell_sel = st.sidebar.selectbox("選擇殼層", shell_keys, index=0)

    st.sidebar.write("描述：", cfg_all[phase_sel].get("description", ""))
    st.sidebar.write("Shell 設定：", shells_dict[shell_sel])

    run = st.button("執行分析")
    if not run:
        st.info("請設定好日期後按下『執行分析』")
        return

    shell_cfg = shells_dict[shell_sel]
    plane_config, total_sats = build_plane_config_from_yaml(
        shell_cfg=shell_cfg,
        db_path=DB_PATH,
        tle_table=TLE_TABLE,
        start_dt=start_dt,
        end_dt=end_dt,
    )
    plane_ids = sorted(plane_config.keys())
    st.success(f"已載入 {phase_sel} / {shell_sel}，plane 數量：{len(plane_ids)}，納入計算的衛星數量: {total_sats}")
    st.info("")

    # 事先計算好相鄰 plane ΔRAAN，存到 session_state，後面選 plane 只做篩選
    num_planes = int(shell_cfg.get("num_planes", 72))
    df_delta_adj = build_delta_raan_adjacent_all_planes(
        plane_config=plane_config,
        start_d=start_d,
        end_d=end_d,
        num_planes=num_planes,
    )
    st.session_state["df_delta_adj"] = df_delta_adj
    st.session_state["num_planes"] = num_planes
    st.session_state["shell_name"] = shell_cfg.get("shell_name", "Starlink Shell")

    # 從 df_delta_adj 裡抓出實際有資料的 plane（after balancing）
    if not df_delta_adj.empty:
        planes_i = df_delta_adj["plane_i"].unique().tolist()
        planes_j = df_delta_adj["plane_j"].unique().tolist()
        balanced_plane_ids = sorted(set(planes_i) | set(planes_j))
    else:
        balanced_plane_ids = []

    st.session_state["balanced_plane_ids"] = balanced_plane_ids

    tab_sma, tab_raan, tab_heat, tab_delta = st.tabs(
        ["SMA 全殼統計", "單一 plane RAAN", "RAAN 群聚 Heatmap", "相鄰 plane ΔRAAN"]
    )

    # ---------- Tab 1: SMA ----------
    with tab_sma:
        st.sidebar.subheader("資料品質過濾")
        n_min = st.sidebar.slider("每 plane 最少衛星數 (n_sats_min)",
                                  min_value=1, max_value=40, value=10, step=1)
        st.caption(f"目前僅納入 n_sats ≥ {n_min} 的 plane-day 進行 fleet 統計")

        st.subheader("全殼 SMA 重構")

        df_all = compute_daily_mean_sma_all_planes(plane_config, start_dt, end_dt)

        if df_all.empty:
            st.warning("此時間區間沒有 SMA 資料")
        else:
            df_reliable = df_all[df_all["n_sats"] >= n_min].copy()

            sat_count_pivot = df_reliable.pivot_table(
                index="date_tag",
                columns="plane_id",
                values="n_sats",
                aggfunc="sum"
            ).fillna(0).astype(int)

            st.markdown("**Plane sat_count (after balancing)**")
            st.dataframe(sat_count_pivot)

            daily_stats = df_reliable.groupby('date_tag').agg({
                'sma_mean_km': ['mean', 'std'],
                'n_sats': 'sum'
            }).round(3).reset_index()
            daily_stats.columns = ['date_tag', 'fleet_mean_km', 'fleet_std_km', 'total_n_sats']

            earth_radius_km = 6371.0
            shell_alt_km = float(shell_cfg["shell_alt_km"])
            target_sma_km = earth_radius_km + shell_alt_km
            daily_stats['altitude_km'] = (daily_stats['fleet_mean_km'] - earth_radius_km).round(1)

            st.markdown("**Fleet-wide daily SMA stats**")
            st.dataframe(daily_stats.tail(10))

            fig, ax = plt.subplots(figsize=(10, 4))
            t = pd.to_datetime(daily_stats.date_tag)

            ax.plot(t, daily_stats.fleet_mean_km, 'b-o', lw=2, label='Fleet SMA')
            ax.fill_between(
                t,
                daily_stats.fleet_mean_km - daily_stats.fleet_std_km,
                daily_stats.fleet_mean_km + daily_stats.fleet_std_km,
                alpha=0.3, label='±1σ'
            )

            ax.axhline(
                target_sma_km, color='r', ls='--',
                label=f'{shell_alt_km:.0f} km target (r={target_sma_km:.0f} km)'
            )

            ax.set_ylabel('SMA [km]')
            ax.set_title(f"{shell_cfg['shell_name']} Shell 重構軌跡")
            ax.grid(True, alpha=0.3)
            ax.legend()
            st.pyplot(fig)

    # ---------- Tab 2: 單一 plane RAAN ----------
    with tab_raan:
        st.subheader("單一 Plane 每日平均 RAAN 演化")
        plane_sel = st.selectbox("選擇 plane", plane_ids, index=0)

        df_raan_all = compute_daily_mean_raan_all_planes(plane_config, start_dt, end_dt)
        if df_raan_all.empty:
            st.warning("此時間區間沒有 RAAN 資料")
        else:
            df_p = df_raan_all[df_raan_all["plane_id"] == plane_sel].copy()
            if df_p.empty:
                st.warning(f"{plane_sel} 無 RAAN 資料")
            else:
                fig, ax = plt.subplots(figsize=(10, 4))
                dates = pd.to_datetime(df_p["date_tag"])
                raan = df_p["raan_deg"]
                ax.plot(dates, raan, 'bo-', lw=1.5, label=f"{plane_sel} ⟨RAAN⟩")
                ax.set_xlabel("日期 (UTC)")
                ax.set_ylabel("平均 RAAN [deg]")
                ax.set_ylim(0, 360)
                ax.set_title(f"Starlink Shell-1 {plane_sel} 每日平均 RAAN")
                ax.grid(True, linestyle="--", alpha=0.4)
                ax.legend()
                st.pyplot(fig)

    # ---------- Tab 3: RAAN Heatmap ----------
    with tab_heat:
        st.subheader("RAAN 群聚 Heatmap (時間 × Plane)")
        df_raan_all = compute_daily_mean_raan_all_planes(plane_config, start_dt, end_dt)
        if df_raan_all.empty:
            st.warning("此時間區間沒有 RAAN 資料")
        else:
            df_raan_all = df_raan_all.copy()
            df_raan_all['date_tag'] = pd.to_datetime(df_raan_all['date_tag'])
            df_raan_all = df_raan_all.sort_values(['date_tag', 'plane_id'])

            raan_pivot = df_raan_all.pivot_table(
                index='date_tag',
                columns='plane_id',
                values='raan_deg'
            )
            raan_pivot = raan_pivot.reindex(sorted(raan_pivot.columns), axis=1)

            fig, ax = plt.subplots(figsize=(12, 5))
            im = ax.imshow(
                raan_pivot.T,
                aspect='auto',
                origin='lower',
                cmap='twilight',
                vmin=0, vmax=360
            )

            ax.set_xticks(np.arange(len(raan_pivot.index)))
            ax.set_xticklabels(
                [d.strftime('%m-%d') for d in raan_pivot.index],
                rotation=45, ha='right'
            )
            ax.set_yticks(np.arange(len(raan_pivot.columns)))
            ax.set_yticklabels(raan_pivot.columns)

            ax.set_xlabel('日期 (UTC)')
            ax.set_ylabel('Orbit Plane ID')
            ax.set_title('Starlink Shell-1 每日平均 RAAN 群聚圖')

            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label('RAAN [deg]')

            plt.tight_layout()
            st.pyplot(fig)

    # ---------- Tab 4: 相鄰 plane ΔRAAN ----------
    with tab_delta:
        st.subheader("相鄰 Plane 代表衛星 ΔRAAN 日變化")

        df_delta_adj = st.session_state.get("df_delta_adj", pd.DataFrame())
        balanced_plane_ids = st.session_state.get("balanced_plane_ids", [])
        shell_name = st.session_state.get("shell_name", "Starlink Shell")

        if df_delta_adj.empty or not balanced_plane_ids:
            st.warning("相鄰 plane 代表衛星 ΔRAAN 資料為空，或沒有有效的 plane，請先在上方按『執行分析』")
        else:
            # 預設 plane_00 vs plane_01（若它們在 balanced list 裡）
            default_i = "plane_00" if "plane_00" in balanced_plane_ids else balanced_plane_ids[0]
            if "plane_01" in balanced_plane_ids:
                default_j = "plane_01"
            else:
                default_j = balanced_plane_ids[min(1, len(balanced_plane_ids) - 1)]

            plane_i = st.selectbox("Plane i", balanced_plane_ids,
                                   index=balanced_plane_ids.index(default_i))
            plane_j = st.selectbox("Plane j", balanced_plane_ids,
                                   index=balanced_plane_ids.index(default_j))

            mask = (df_delta_adj["plane_i"] == plane_i) & (df_delta_adj["plane_j"] == plane_j)
            df_pair = df_delta_adj[mask].copy()

            if df_pair.empty:
                st.warning(f"{plane_i} vs {plane_j} 無重疊日期")
            else:
                norad_i = int(df_pair["norad_i"].iloc[0])
                norad_j = int(df_pair["norad_j"].iloc[0])

                fig, ax = plt.subplots(figsize=(10, 4))
                ax.plot(df_pair["date_tag"], df_pair["delta_raan_deg"],
                        "o-", lw=1.5,
                        label=f"ΔRAAN ({plane_j} / {norad_j} - {plane_i} / {norad_i})")
                ax.axhline(5.0, color="r", ls="--", lw=1, label="理論 spacing 5°")
                ax.axhline(-5.0, color="r", ls="--", lw=1)
                ax.set_xlabel("日期 (UTC)")
                ax.set_ylabel("ΔRAAN [deg]")

                ax.set_title(
                    f"{shell_name}: {plane_i} (NORAD {norad_i}) vs {plane_j} (NORAD {norad_j})"
                )

                ax.grid(True, alpha=0.3)
                ax.legend(loc="best")
                st.pyplot(fig)

    # 清除 ΔRAAN cache（若你之後改成 cache 版本可以用）
    if st.sidebar.button("清除 ΔRAAN cache"):
        if "df_delta_adj" in st.session_state:
            del st.session_state["df_delta_adj"]
        if "plane_ids" in st.session_state:
            del st.session_state["plane_ids"]
        if "num_planes" in st.session_state:
            del st.session_state["num_planes"]


if __name__ == "__main__":
    main()
