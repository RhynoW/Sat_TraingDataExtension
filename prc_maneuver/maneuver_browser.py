"""
maneuver_browser.py  —  軌道機動事件瀏覽分析工具
================================================
執行方式：
    streamlit run maneuver_browser.py

功能：
  • 載入既有 CSV 或重新執行偵測腳本產生資料
  • 多維度篩選：日期、嚴重度、score 門檻、衛星名稱、發射地點
  • 衛星基本資訊：從 space_db.duckdb 的 sat_n2yo_metadata 自動補充
  • 四個分析頁籤：總覽 / 事件列表 / 衛星詳情 / 散佈分析
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── 路徑 ────────────────────────────────────────────────────────────────────
REPO     = Path(__file__).resolve().parent.parent   # prc_maneuver/../
OUT_DIR  = Path(__file__).resolve().parent / "output"  # prc_maneuver/output/
DEFAULT_FLAGGED     = OUT_DIR / "prc_maneuver_flagged.csv"
DEFAULT_TRANSITIONS = OUT_DIR / "prc_maneuver_transitions.csv"
DB_PATH  = REPO / "space_db.duckdb"

SEV_ORDER  = ["large", "medium", "small", "none"]
SEV_COLORS = {
    "large":  "#d62728",
    "medium": "#ff7f0e",
    "small":  "#1f77b4",
    "none":   "#aec7e8",
}

# ── 頁面設定 ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="軌道機動事件瀏覽器",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🛰️ 軌道機動事件瀏覽器")
st.caption("TLE-based maneuver detection  |  J2-corrected RAAN residual")


# ── 資料載入 ─────────────────────────────────────────────────────────────────

META_PARQUET = REPO / "data" / "tle_parquet" / "sat_metadata.parquet"
META_COLS = [
    "norad_id", "name_en", "launch_date", "launch_site", "intl_code",
    "perigee_km", "apogee_km", "inclination_deg", "period_min",
    "rcs_text", "source_code", "website_desc_en", "website_desc_ch",
]


@st.cache_data(show_spinner="讀取衛星基本資訊…")
def load_sat_metadata(norad_ids: tuple[int, ...]) -> pd.DataFrame:
    """
    讀取衛星基本資訊，優先順序：
      1. data/tle_parquet/sat_metadata.parquet（GitHub/Streamlit 部署用）
      2. space_db.duckdb / space_db_slim.duckdb（本地 DuckDB）
    """
    if not norad_ids:
        return pd.DataFrame()

    # ── 優先：parquet ────────────────────────────────────────────────────────
    if META_PARQUET.exists():
        try:
            df = pd.read_parquet(META_PARQUET)
            # 欄位名稱相容（inclination_deg 可能在 DB 版本被重命名）
            if "inclination_deg" not in df.columns and "meta_inc_deg" in df.columns:
                df = df.rename(columns={"meta_inc_deg": "inclination_deg"})
            df = df[df["norad_id"].isin(set(norad_ids))]
            df["launch_date"] = pd.to_datetime(df["launch_date"], errors="coerce")
            return df.reset_index(drop=True)
        except Exception as exc:
            st.warning(f"parquet metadata 讀取失敗，改用 DuckDB：{exc}")

    # ── 備用：DuckDB（優先 slim，再試原始）────────────────────────────────────
    slim_db = REPO / "space_db_slim.duckdb"
    db_candidates = [p for p in [slim_db, DB_PATH] if p.exists()]
    if not db_candidates:
        return pd.DataFrame()

    id_str = ",".join(map(str, norad_ids))
    for db in db_candidates:
        try:
            con = duckdb.connect(str(db), read_only=True)
            meta = con.execute(f"""
                SELECT norad_id,
                       name_en,
                       launch_date,
                       launch_site,
                       intl_code,
                       perigee_km,
                       apogee_km,
                       inclination_deg,
                       period_min,
                       rcs_text,
                       source_code,
                       website_desc_en,
                       website_desc_ch
                FROM sat_n2yo_metadata
                WHERE norad_id IN ({id_str})
            """).fetchdf()
            con.close()
            meta["launch_date"] = pd.to_datetime(meta["launch_date"], errors="coerce")
            return meta
        except Exception:
            continue

    st.warning("無法讀取衛星基本資訊（parquet 與 DuckDB 皆失敗）")
    return pd.DataFrame()


@st.cache_data(show_spinner="讀取資料中…")
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["t_from", "t_to"])
    df["t_from"] = pd.to_datetime(df["t_from"], utc=True)
    df["t_to"]   = pd.to_datetime(df["t_to"],   utc=True)
    df["date"]   = df["t_from"].dt.date
    df["sat_label"] = df["sat_name"].fillna("") + "  (NORAD " + df["norad_id"].astype(str) + ")"
    if "da_severity" not in df.columns:
        df["da_severity"] = "none"
    df["da_severity"] = pd.Categorical(df["da_severity"], categories=SEV_ORDER, ordered=True)
    return df


def run_detection(download: bool) -> None:
    script = str(Path(__file__).resolve().parent / "detect_prc_maneuvers.py")
    cmd    = [sys.executable, script]
    if download:
        cmd += ["--download"]
    with st.spinner("執行偵測腳本中，請稍候…（可能需要數分鐘）"):
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    if result.returncode == 0:
        st.success("偵測完成！")
        st.cache_data.clear()
    else:
        st.error("偵測失敗，請查看日誌。")
    with st.expander("執行日誌"):
        st.text(result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout)
        if result.stderr:
            st.text(result.stderr[-2000:])


# ─────────────────────────────────────────────────────────────────────────────
# 側邊欄：資料來源 + 篩選
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 資料來源")

    source_mode = st.radio(
        "選擇資料來源",
        ["既有 CSV 檔案", "上傳 CSV", "重新執行偵測"],
        index=0,
    )

    df_raw: pd.DataFrame | None = None

    if source_mode == "既有 CSV 檔案":
        # 列出 output 目錄下的所有 CSV
        csv_files = sorted(OUT_DIR.glob("*.csv"))
        csv_names = [f.name for f in csv_files]
        default_idx = next(
            (i for i, n in enumerate(csv_names) if "flagged" in n), 0
        )
        chosen = st.selectbox("選擇檔案", csv_names, index=default_idx)
        csv_path = OUT_DIR / chosen
        if csv_path.exists():
            df_raw = load_csv(str(csv_path))
            st.caption(f"✅ 已載入  `{chosen}`  —  {len(df_raw):,} 列")
        else:
            st.error("檔案不存在")

    elif source_mode == "上傳 CSV":
        uploaded = st.file_uploader("上傳 CSV 檔案", type=["csv"])
        if uploaded:
            df_raw = load_csv(uploaded)
            st.caption(f"✅ 已載入  —  {len(df_raw):,} 列")

    else:  # 重新執行偵測
        st.warning("將執行 `detect_prc_maneuvers.py`，需要 Space-Track 帳號與網路。")
        dl_missing = st.checkbox("補下載缺失 TLE（2026-01-01~03-30）", value=False)
        if st.button("▶ 開始偵測", type="primary"):
            run_detection(dl_missing)
        # 偵測完後自動載入
        if DEFAULT_FLAGGED.exists():
            df_raw = load_csv(str(DEFAULT_FLAGGED))
            st.caption(f"✅ 已載入  `prc_maneuver_flagged.csv`  —  {len(df_raw):,} 列")

    st.divider()

    if df_raw is not None and not df_raw.empty:
        st.header("🔍 篩選")

        # 日期範圍
        t_min = df_raw["t_from"].dt.date.min()
        t_max = df_raw["t_from"].dt.date.max()
        date_range = st.date_input(
            "t_from 日期範圍",
            value=(t_min, t_max),
            min_value=t_min,
            max_value=t_max,
        )

        # 嚴重度
        avail_sev = [s for s in SEV_ORDER if s in df_raw["da_severity"].unique()]
        sel_sev = st.multiselect("嚴重度", avail_sev, default=avail_sev)

        # Score 門檻
        score_max = float(df_raw["score"].max())
        score_thr = st.slider(
            "最低 score",
            min_value=0.0,
            max_value=min(score_max, 50.0),
            value=1.0,
            step=0.5,
        )

        # 衛星搜尋
        sat_search = st.text_input("衛星名稱關鍵字（留空＝全部）", "").strip().upper()

        st.divider()
        only_flagged = st.checkbox("只顯示 flagged = True", value=True)

# ── 若無資料，停止 ────────────────────────────────────────────────────────────
if df_raw is None or df_raw.empty:
    st.info("請在左側選擇資料來源。")
    st.stop()

# ── 載入衛星基本資訊並 merge ─────────────────────────────────────────────────
_norad_tuple = tuple(sorted(df_raw["norad_id"].dropna().astype(int).unique().tolist()))
sat_meta = load_sat_metadata(_norad_tuple)

if not sat_meta.empty:
    df_raw = df_raw.merge(
        sat_meta[[
            "norad_id", "launch_date", "launch_site", "intl_code",
            "perigee_km", "apogee_km", "period_min", "rcs_text",
            "source_code", "website_desc_en", "website_desc_ch",
        ]],
        on="norad_id", how="left",
    )

# ── 發射地點篩選（sidebar，需在 merge 後才知道可用選項）────────────────────────
with st.sidebar:
    if not sat_meta.empty and "launch_site" in df_raw.columns:
        sites_all = sorted(df_raw["launch_site"].dropna().unique().tolist())
        sel_sites = st.multiselect(
            "發射地點（留空＝全部）",
            options=sites_all,
            default=[],
            placeholder="全部",
        )
    else:
        sel_sites = []

# ─────────────────────────────────────────────────────────────────────────────
# 套用篩選
# ─────────────────────────────────────────────────────────────────────────────

df = df_raw.copy()

# 日期
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    d0, d1 = date_range
    df = df[(df["t_from"].dt.date >= d0) & (df["t_from"].dt.date <= d1)]
elif hasattr(date_range, "__len__") and len(date_range) == 1:
    df = df[df["t_from"].dt.date == date_range[0]]

# 嚴重度
if sel_sev:
    df = df[df["da_severity"].isin(sel_sev)]

# Score
df = df[df["score"] >= score_thr]

# 衛星搜尋
if sat_search:
    df = df[df["sat_name"].fillna("").str.upper().str.contains(sat_search, regex=False)]

# 發射地點
if sel_sites and "launch_site" in df.columns:
    df = df[df["launch_site"].isin(sel_sites)]

# flagged
if only_flagged and "flagged" in df.columns:
    df = df[df["flagged"] == True]

df = df.reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# 頂部 KPI 列
# ─────────────────────────────────────────────────────────────────────────────

n_events = len(df)
n_sats   = df["norad_id"].nunique()
n_large  = (df["da_severity"] == "large").sum()
max_score = df["score"].max() if n_events else 0

k1, k2, k3, k4 = st.columns(4)
k1.metric("機動事件數", f"{n_events:,}")
k2.metric("涉及衛星數", f"{n_sats:,}")
k3.metric("Large 事件", f"{n_large:,}")
k4.metric("最高 Score", f"{max_score:.1f}")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# 四個頁籤
# ─────────────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 總覽",
    "📋 事件列表",
    "🛰️ 衛星詳情",
    "📈 散佈分析",
])

# ════════════════════════════════════════════════════════════════════
# Tab 1 — 總覽
# ════════════════════════════════════════════════════════════════════
with tab1:
    if df.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        col_a, col_b = st.columns([3, 2])

        with col_a:
            st.subheader("時間軸：機動事件分布")
            fig_tl = px.scatter(
                df.sort_values("t_from"),
                x="t_from",
                y="da_km",
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                category_orders={"da_severity": SEV_ORDER},
                hover_data=["sat_name", "norad_id", "score", "flag_reason"],
                labels={"t_from": "時間 (UTC)", "da_km": "Δa (km)"},
                title="Δa over Time（色＝嚴重度）",
                height=380,
            )
            fig_tl.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            for thr in (1, 5, 10, -1, -5, -10):
                fig_tl.add_hline(y=thr, line_dash="dot", line_color="lightgray",
                                 line_width=0.8)
            st.plotly_chart(fig_tl, use_container_width=True)

        with col_b:
            st.subheader("嚴重度分布")
            sev_cnt = df["da_severity"].value_counts().reindex(SEV_ORDER).dropna()
            fig_bar = px.bar(
                sev_cnt.reset_index(),
                x="da_severity",
                y="count",
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                labels={"da_severity": "嚴重度", "count": "事件數"},
                height=200,
            )
            fig_bar.update_layout(showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig_bar, use_container_width=True)

            st.subheader("Score 分布")
            fig_hist = px.histogram(
                df[df["score"] < 50],   # 截斷極端值以便視覺化
                x="score",
                nbins=50,
                color_discrete_sequence=["steelblue"],
                labels={"score": "Score", "count": "次數"},
                height=200,
            )
            fig_hist.update_layout(margin=dict(t=10, b=10))
            st.plotly_chart(fig_hist, use_container_width=True)

        # 熱力圖：每月每週事件數
        st.subheader("每日事件數（熱力圖）")
        df_daily = (
            df.groupby("date")
            .size()
            .reset_index(name="count")
        )
        df_daily["date"] = pd.to_datetime(df_daily["date"])
        df_daily["week"]    = df_daily["date"].dt.isocalendar().week.astype(int)
        df_daily["weekday"] = df_daily["date"].dt.weekday  # 0=Mon
        df_daily["month"]   = df_daily["date"].dt.strftime("%Y-%m")

        fig_heat = px.density_heatmap(
            df_daily,
            x="date",
            y="count",
            nbinsx=60,
            color_continuous_scale="YlOrRd",
            labels={"date": "日期", "count": "事件數"},
            height=200,
        )
        fig_heat.update_layout(margin=dict(t=10, b=10))
        st.plotly_chart(fig_heat, use_container_width=True)

        # Top 衛星排行
        st.subheader("Top 20 活躍衛星（按機動事件數）")
        top_sats = (
            df.groupby(["norad_id", "sat_name"])
            .agg(n_events=("score", "count"),
                 max_score=("score", "max"),
                 max_da_km=("da_km", lambda x: x.abs().max()),
                 n_large=("da_severity", lambda x: (x == "large").sum()))
            .reset_index()
            .sort_values("n_events", ascending=False)
            .head(20)
        )
        fig_top = px.bar(
            top_sats,
            x="n_events",
            y="sat_name",
            orientation="h",
            color="max_score",
            color_continuous_scale="Reds",
            hover_data=["norad_id", "max_da_km", "n_large"],
            labels={"n_events": "事件數", "sat_name": "衛星名稱"},
            height=500,
        )
        fig_top.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=160))
        st.plotly_chart(fig_top, use_container_width=True)


# ════════════════════════════════════════════════════════════════════
# Tab 2 — 事件列表
# ════════════════════════════════════════════════════════════════════
with tab2:
    if df.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        st.subheader(f"事件列表  ({n_events:,} 筆)")

        sort_col = st.selectbox(
            "排序欄位",
            ["score", "t_from", "da_km", "di_deg", "da_severity"],
            index=0,
        )
        sort_asc = st.checkbox("升冪排序", value=False)

        display_cols = [
            "norad_id", "sat_name", "intl_code", "launch_date", "launch_site",
            "t_from", "t_to", "alt_km", "da_km", "di_deg", "draan_res_deg",
            "da_severity", "score", "flag_reason",
        ]
        disp_cols = [c for c in display_cols if c in df.columns]

        df_disp = (
            df[disp_cols]
            .sort_values(sort_col, ascending=sort_asc)
            .reset_index(drop=True)
        )

        # 格式化數值
        for col in ["da_km", "di_deg", "draan_res_deg", "alt_km"]:
            if col in df_disp.columns:
                df_disp[col] = df_disp[col].round(3)
        df_disp["score"] = df_disp["score"].round(2) if "score" in df_disp.columns else df_disp["score"]

        col_cfg: dict = {
            "norad_id":       st.column_config.NumberColumn("NORAD", format="%d"),
            "sat_name":       st.column_config.TextColumn("衛星名稱"),
            "intl_code":      st.column_config.TextColumn("COSPAR ID"),
            "launch_date":    st.column_config.DateColumn("發射日期", format="YYYY-MM-DD"),
            "launch_site":    st.column_config.TextColumn("發射地點", width="medium"),
            "t_from":         st.column_config.DatetimeColumn("t_from (UTC)", format="YYYY-MM-DD HH:mm"),
            "t_to":           st.column_config.DatetimeColumn("t_to (UTC)",   format="YYYY-MM-DD HH:mm"),
            "alt_km":         st.column_config.NumberColumn("高度 km", format="%.1f"),
            "da_km":          st.column_config.NumberColumn("Δa km", format="%.3f"),
            "di_deg":         st.column_config.NumberColumn("Δi °", format="%.4f"),
            "draan_res_deg":  st.column_config.NumberColumn("ΔRAAN_res °", format="%.4f"),
            "da_severity":    st.column_config.TextColumn("嚴重度"),
            "score":          st.column_config.ProgressColumn(
                                  "Score", min_value=0, max_value=min(50, float(df["score"].max()) + 1),
                                  format="%.2f",
                              ),
            "flag_reason":    st.column_config.TextColumn("旗標原因", width="large"),
        }

        st.dataframe(
            df_disp,
            use_container_width=True,
            height=600,
            column_config={k: v for k, v in col_cfg.items() if k in df_disp.columns},
        )

        st.download_button(
            "⬇️ 下載目前篩選結果 CSV",
            data=df_disp.to_csv(index=False).encode("utf-8-sig"),
            file_name="maneuver_filtered.csv",
            mime="text/csv",
        )


# ════════════════════════════════════════════════════════════════════
# Tab 3 — 衛星詳情
# ════════════════════════════════════════════════════════════════════
with tab3:
    if df.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        sat_options = (
            df.groupby(["norad_id", "sat_name"])
            .size()
            .reset_index(name="n")
            .sort_values("n", ascending=False)
        )
        sat_options["label"] = (
            sat_options["sat_name"].fillna("?")
            + "  (NORAD " + sat_options["norad_id"].astype(str) + ")"
            + "  —  " + sat_options["n"].astype(str) + " 事件"
        )

        chosen_label = st.selectbox("選擇衛星", sat_options["label"].tolist())
        chosen_idx   = sat_options["label"].tolist().index(chosen_label)
        chosen_norad = int(sat_options.iloc[chosen_idx]["norad_id"])
        chosen_name  = sat_options.iloc[chosen_idx]["sat_name"]

        df_sat = df[df["norad_id"] == chosen_norad].sort_values("t_from")

        st.markdown(f"### {chosen_name}  —  NORAD {chosen_norad}")

        # ── 衛星基本資料卡 ───────────────────────────────────────────────────
        if not sat_meta.empty:
            m_row = sat_meta[sat_meta["norad_id"] == chosen_norad]
            if not m_row.empty:
                r = m_row.iloc[0]
                with st.container(border=True):
                    st.markdown("#### 🛰️ 衛星基本資訊")
                    info_a, info_b, info_c = st.columns(3)
                    with info_a:
                        st.markdown(f"**COSPAR ID**　{r.get('intl_code','—') or '—'}")
                        ld = r.get("launch_date")
                        st.markdown(f"**發射日期**　{pd.Timestamp(ld).strftime('%Y-%m-%d') if pd.notna(ld) else '—'}")
                        st.markdown(f"**發射地點**　{r.get('launch_site','—') or '—'}")
                    with info_b:
                        st.markdown(f"**RCS**　{r.get('rcs_text','—') or '—'}")
                        pg = r.get("perigee_km")
                        ag = r.get("apogee_km")
                        alt_rng = f"{pg:.0f} × {ag:.0f} km" if pd.notna(pg) and pd.notna(ag) else "—"
                        st.markdown(f"**近/遠地點**　{alt_rng}")
                        pm = r.get("period_min")
                        st.markdown(f"**軌道週期**　{f'{pm:.1f} min' if pd.notna(pm) else '—'}")
                    with info_c:
                        st.markdown(f"**國家/組織**　{r.get('source_code','—') or '—'}")
                    # 英文描述
                    desc_en = r.get("website_desc_en", "")
                    if desc_en and str(desc_en) not in ("nan", "None", ""):
                        with st.expander("英文描述"):
                            st.caption(str(desc_en))
                    # 中文描述
                    desc_ch = r.get("website_desc_ch", "")
                    if desc_ch and str(desc_ch) not in ("nan", "None", ""):
                        with st.expander("中文描述"):
                            st.caption(str(desc_ch))

        # ── 機動事件 KPI ──────────────────────────────────────────────────────
        col1, col2, col3 = st.columns(3)
        col1.metric("機動事件數", len(df_sat))
        col2.metric("最高 Score", f"{df_sat['score'].max():.2f}")
        col3.metric("最大 |Δa| km", f"{df_sat['da_km'].abs().max():.2f}")

        # 高度時間軸
        st.subheader("高度 / Δa 時間軸")
        fig_alt = go.Figure()
        fig_alt.add_trace(go.Scatter(
            x=df_sat["t_from"], y=df_sat["alt_km"],
            mode="lines+markers",
            name="高度 km",
            line=dict(color="royalblue", width=1.5),
            marker=dict(size=6),
        ))
        for sev, color in SEV_COLORS.items():
            sub = df_sat[df_sat["da_severity"] == sev]
            if sub.empty:
                continue
            fig_alt.add_trace(go.Scatter(
                x=sub["t_from"], y=sub["alt_km"],
                mode="markers",
                name=f"da={sev}",
                marker=dict(color=color, size=10, symbol="circle-open", line_width=2),
            ))
        fig_alt.update_layout(
            xaxis_title="時間 (UTC)",
            yaxis_title="高度 km",
            height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_alt, use_container_width=True)

        # Δa / Δi 時間軸
        st.subheader("Δa / Δi / Score 時間軸")
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            x=df_sat["t_from"], y=df_sat["da_km"],
            name="Δa km",
            marker_color=[SEV_COLORS.get(s, "gray") for s in df_sat["da_severity"]],
            yaxis="y1",
        ))
        fig3.add_trace(go.Scatter(
            x=df_sat["t_from"], y=df_sat["di_deg"],
            name="Δi °",
            line=dict(color="green", width=1.5, dash="dot"),
            yaxis="y2",
        ))
        fig3.add_trace(go.Scatter(
            x=df_sat["t_from"], y=df_sat["score"].clip(upper=50),
            name="Score (clip@50)",
            line=dict(color="crimson", width=1.5),
            yaxis="y3",
        ))
        fig3.update_layout(
            xaxis_title="時間 (UTC)",
            yaxis=dict(title="Δa km", side="left"),
            yaxis2=dict(title="Δi °", overlaying="y", side="right", showgrid=False),
            yaxis3=dict(title="Score", overlaying="y", side="right",
                        anchor="free", position=1.0, showgrid=False),
            height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig3, use_container_width=True)

        # 詳細表格
        with st.expander("詳細資料表"):
            st.dataframe(
                df_sat[[c for c in [
                    "t_from", "t_to", "alt_km", "i_deg", "raan_deg",
                    "da_km", "di_deg", "de", "draan_res_deg",
                    "da_severity", "score", "flag_reason",
                ] if c in df_sat.columns]].reset_index(drop=True),
                use_container_width=True,
            )


# ════════════════════════════════════════════════════════════════════
# Tab 4 — 散佈分析
# ════════════════════════════════════════════════════════════════════
with tab4:
    if df.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Δa vs Δi  (色＝嚴重度)")
            fig_sc1 = px.scatter(
                df,
                x="da_km",
                y="di_deg",
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                category_orders={"da_severity": SEV_ORDER},
                hover_data=["sat_name", "norad_id", "score", "t_from"],
                opacity=0.7,
                labels={"da_km": "Δa (km)", "di_deg": "Δi (°)"},
                height=400,
            )
            for thr in (1, 5, 10, -1, -5, -10):
                fig_sc1.add_vline(x=thr, line_dash="dot", line_color="lightgray",
                                  line_width=0.8)
            for thr in (0.02, -0.02):
                fig_sc1.add_hline(y=thr, line_dash="dot", line_color="lightgray",
                                  line_width=0.8)
            st.plotly_chart(fig_sc1, use_container_width=True)

        with col_b:
            st.subheader("高度 vs Score  (色＝嚴重度)")
            fig_sc2 = px.scatter(
                df,
                x="alt_km",
                y=df["score"].clip(upper=50),
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                category_orders={"da_severity": SEV_ORDER},
                hover_data=["sat_name", "norad_id", "da_km", "t_from"],
                opacity=0.7,
                labels={"alt_km": "高度 (km)", "y": "Score (clip@50)"},
                height=400,
            )
            fig_sc2.add_hline(y=1.0, line_dash="dash", line_color="tomato",
                              annotation_text="score=1 (門檻)")
            st.plotly_chart(fig_sc2, use_container_width=True)

        col_c, col_d = st.columns(2)

        with col_c:
            st.subheader("ΔRAAN_res vs Δa  (色＝嚴重度)")
            fig_sc3 = px.scatter(
                df,
                x="da_km",
                y="draan_res_deg",
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                category_orders={"da_severity": SEV_ORDER},
                hover_data=["sat_name", "norad_id", "score"],
                opacity=0.65,
                labels={"da_km": "Δa (km)", "draan_res_deg": "ΔRAAN_res (°)"},
                height=380,
            )
            for thr in (0.1, -0.1):
                fig_sc3.add_hline(y=thr, line_dash="dot", line_color="tomato",
                                  line_width=1)
            st.plotly_chart(fig_sc3, use_container_width=True)

        with col_d:
            st.subheader("傾角 i vs Δi  (色＝嚴重度)")
            fig_sc4 = px.scatter(
                df,
                x="i_deg",
                y="di_deg",
                color="da_severity",
                color_discrete_map=SEV_COLORS,
                category_orders={"da_severity": SEV_ORDER},
                hover_data=["sat_name", "norad_id", "score", "da_km"],
                opacity=0.65,
                labels={"i_deg": "傾角 i (°)", "di_deg": "Δi (°)"},
                height=380,
            )
            for thr in (0.02, -0.02):
                fig_sc4.add_hline(y=thr, line_dash="dot", line_color="tomato",
                                  line_width=1)
            st.plotly_chart(fig_sc4, use_container_width=True)

        # 6 個月熱力圖：月 × 嚴重度
        st.subheader("月份 × 嚴重度 事件數熱力圖")
        df_heat = df.copy()
        df_heat["month"] = df_heat["t_from"].dt.strftime("%Y-%m")
        pivot = (
            df_heat.groupby(["month", "da_severity"], observed=False)
            .size()
            .unstack(fill_value=0)
            .reindex(columns=SEV_ORDER, fill_value=0)
        )
        fig_hm = px.imshow(
            pivot.T,
            color_continuous_scale="YlOrRd",
            labels=dict(x="月份", y="嚴重度", color="事件數"),
            aspect="auto",
            height=280,
        )
        fig_hm.update_layout(margin=dict(t=10, b=10))
        st.plotly_chart(fig_hm, use_container_width=True)
