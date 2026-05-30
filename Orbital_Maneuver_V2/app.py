"""app.py — Streamlit dashboard for Orbital_Maneuver_V2 ML maneuver prediction.

啟動方式:
    cd Orbital_Maneuver_V2
    streamlit run app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Orbital Maneuver ML",
    layout="wide",
    page_icon="🛰️",
    initial_sidebar_state="expanded",
)

# ── Default paths ─────────────────────────────────────────────────────────────
_DEFAULT_DB        = str(_HERE.parent / "space_db.duckdb")
_DEFAULT_RESIDUALS = str(_HERE.parent / "data" / "comparison" / "residuals_*.csv")
_DEFAULT_MODEL_DIR = str(_HERE / "models")

# ── Cached loaders ────────────────────────────────────────────────────────────

@st.cache_resource
def _load_model(model_path: str):
    return joblib.load(model_path)


@st.cache_data
def _load_feature_names(model_dir: str) -> list[str]:
    p = Path(model_dir) / "feature_names.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


@st.cache_data
def _load_threshold_info(model_dir: str) -> dict:
    p = Path(model_dir) / "threshold.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"threshold": 0.5, "method": "default"}


@st.cache_data(ttl=300, show_spinner="讀取 TLE 特徵矩陣 …")
def _build_features(norad_id: int, db_path: str) -> pd.DataFrame:
    import data_loader
    return data_loader.build_feature_matrix(norad_id, db_path)


@st.cache_data(ttl=300, show_spinner="載入 MEME 殘差 …")
def _load_residuals(norad_id: int, resid_glob: str) -> pd.DataFrame:
    import labeler
    df = labeler.load_residuals(resid_glob)
    if df.empty:
        return df
    sat = df[df["norad_id"] == norad_id].copy()
    sat["t"] = pd.to_datetime(sat["t"], utc=True, errors="coerce")
    return sat.sort_values("t").reset_index(drop=True)


def _score(model, feat_df: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    """Attach p_maneuver to feat_df; returns copy with new column."""
    present = [c for c in feature_names if c in feat_df.columns]
    X = feat_df[present]
    valid = X.notna().all(axis=1)
    out = feat_df.copy()
    out["p_maneuver"] = float("nan")
    if valid.any():
        out.loc[valid, "p_maneuver"] = model.predict_proba(X[valid])[:, 1]
    return out


# ── Plotting helpers ──────────────────────────────────────────────────────────

_DARK = "plotly_dark"
_MARGIN = dict(l=60, r=40, t=60, b=40)


def _fig_probability(scored: pd.DataFrame, threshold: float, norad_id: int) -> go.Figure:
    """p_maneuver time series with threshold line and alert markers."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.4],
        vertical_spacing=0.06,
        subplot_titles=["機動概率 p_maneuver", "SMA (km)"],
    )

    # ── Row 1: probability ────────────────────────────────────────────────────
    t_col = "epoch_utc"
    fig.add_trace(go.Scatter(
        x=scored[t_col], y=scored["p_maneuver"],
        name="p_maneuver",
        line=dict(color="deepskyblue", width=1.5),
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>p = %{y:.4f}<extra></extra>",
    ), row=1, col=1)

    # Threshold line
    fig.add_hline(
        y=threshold, row=1, col=1,
        line_dash="dash", line_color="red", opacity=0.7,
        annotation_text=f"threshold={threshold:.4f}",
        annotation_position="top right",
        annotation_font_color="red",
    )

    # Alert markers
    alerts = scored[scored["p_maneuver"] >= threshold]
    if not alerts.empty:
        fig.add_trace(go.Scatter(
            x=alerts[t_col], y=alerts["p_maneuver"],
            mode="markers", name="!! MANEUVER",
            marker=dict(color="red", size=9, symbol="triangle-up",
                        line=dict(width=1, color="white")),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>p = %{y:.4f}<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: SMA ────────────────────────────────────────────────────────────
    if "sma_km" in scored.columns:
        fig.add_trace(go.Scatter(
            x=scored[t_col], y=scored["sma_km"],
            name="SMA (km)", line=dict(color="lightgreen", width=1.2),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>SMA = %{y:.3f} km<extra></extra>",
        ), row=2, col=1)
        if not alerts.empty:
            fig.add_trace(go.Scatter(
                x=alerts[t_col], y=alerts["sma_km"],
                mode="markers", name="Alert on SMA",
                marker=dict(color="red", size=7, symbol="triangle-up"),
                showlegend=False,
            ), row=2, col=1)

    fig.update_layout(
        template=_DARK, height=520, margin=_MARGIN,
        legend=dict(orientation="h", y=-0.06),
        yaxis=dict(range=[0, 1.05], title="p_maneuver"),
        yaxis2=dict(title="SMA (km)"),
        title=dict(text=f"NORAD {norad_id} — 機動概率", x=0.02),
    )
    return fig


def _fig_residuals(resid: pd.DataFrame, scored: pd.DataFrame,
                   threshold: float, norad_id: int) -> go.Figure:
    """MEME pos_err_km vs p_maneuver side-by-side."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.5],
        vertical_spacing=0.06,
        subplot_titles=["MEME pos_err_km（殘差距離）", "ML p_maneuver"],
    )

    t_col = "epoch_utc"
    alerts = scored[scored["p_maneuver"] >= threshold]

    # ── Row 1: MEME residuals ─────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=resid["t"], y=resid["pos_err_km"],
        name="pos_err_km", line=dict(color="orange", width=1.2),
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>err = %{y:.2f} km<extra></extra>",
    ), row=1, col=1)

    # Shade MEME maneuver events (pos_err > 50 km) for reference
    fig.add_hline(y=50, row=1, col=1,
                  line_dash="dot", line_color="yellow", opacity=0.5,
                  annotation_text="50 km (MEME 事件門檻)",
                  annotation_position="top left",
                  annotation_font_color="yellow")

    # ── Row 2: ML probability ─────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=scored[t_col], y=scored["p_maneuver"],
        name="p_maneuver", line=dict(color="deepskyblue", width=1.5),
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>p = %{y:.4f}<extra></extra>",
    ), row=2, col=1)
    fig.add_hline(y=threshold, row=2, col=1,
                  line_dash="dash", line_color="red", opacity=0.7)
    if not alerts.empty:
        fig.add_trace(go.Scatter(
            x=alerts[t_col], y=alerts["p_maneuver"],
            mode="markers", name="ML Alert",
            marker=dict(color="red", size=8, symbol="triangle-up"),
        ), row=2, col=1)

    fig.update_layout(
        template=_DARK, height=500, margin=_MARGIN,
        legend=dict(orientation="h", y=-0.06),
        yaxis=dict(title="pos_err (km)"),
        yaxis2=dict(range=[0, 1.05], title="p_maneuver"),
        title=dict(text=f"NORAD {norad_id} — MEME 殘差 vs ML 預測", x=0.02),
    )
    return fig


def _fig_feature_importance(model, feature_names: list[str]) -> go.Figure:
    imp = model.feature_importances_
    pairs = sorted(zip(feature_names, imp), key=lambda x: x[1], reverse=True)
    names, vals = zip(*pairs)
    fig = go.Figure(go.Bar(
        x=list(vals), y=list(names),
        orientation="h",
        marker=dict(
            color=list(vals),
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(title="Importance"),
        ),
        hovertemplate="%{y}: %{x:.1f}<extra></extra>",
    ))
    fig.update_layout(
        template=_DARK, height=420, margin=_MARGIN,
        yaxis=dict(autorange="reversed"),
        xaxis_title="Feature Importance (gain)",
        title="特徵重要性（全模型）",
    )
    return fig


def _fig_key_features(scored: pd.DataFrame, norad_id: int) -> go.Figure:
    """Time series of the most informative TLE features."""
    feat_plot = [
        ("d_sma_km",      "Δ SMA (km)",       "deepskyblue"),
        ("d_sma_per_day", "Δ SMA/day",         "lime"),
        ("sma_slope_km_day", "SMA slope",      "orange"),
        ("tle_gap_hours", "TLE gap (h)",        "violet"),
        ("bstar",         "B* drag",            "coral"),
    ]
    available = [(col, lbl, clr) for col, lbl, clr in feat_plot if col in scored.columns]
    if not available:
        return go.Figure()

    n = len(available)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.04)
    t_col = "epoch_utc"

    for row_i, (col, lbl, clr) in enumerate(available, start=1):
        fig.add_trace(go.Scatter(
            x=scored[t_col], y=scored[col],
            name=lbl, line=dict(color=clr, width=1.2),
            hovertemplate=f"%{{x|%Y-%m-%d}}<br>{lbl} = %{{y:.5f}}<extra></extra>",
        ), row=row_i, col=1)
        fig.update_yaxes(title_text=lbl, row=row_i, col=1)

    fig.update_layout(
        template=_DARK, height=120 * n + 60, margin=_MARGIN,
        showlegend=False,
        title=dict(text=f"NORAD {norad_id} — 關鍵特徵時序", x=0.02),
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🛰️ Maneuver ML")
    st.caption("Orbital_Maneuver_V2 預測介面")
    st.divider()

    raw_norad = st.text_input(
        "NORAD ID（多筆用逗號分隔）",
        value="64479, 68075, 65878",
        help="例: 64479, 68075",
    )
    norad_ids: list[int] = []
    for tok in raw_norad.split(","):
        tok = tok.strip()
        if tok.isdigit():
            norad_ids.append(int(tok))

    st.divider()
    st.subheader("模型設定")

    model_dir = st.text_input("模型目錄", value=_DEFAULT_MODEL_DIR)
    db_path   = st.text_input("DuckDB 路徑", value=_DEFAULT_DB)
    resid_glob = st.text_input("MEME 殘差 Glob", value=_DEFAULT_RESIDUALS,
                                help="用於 MEME 殘差對照頁籤")

    # Load model artifacts
    _model_pkl = Path(model_dir) / "lgbm_maneuver_v1.pkl"
    _artifacts_ok = _model_pkl.exists()

    if not _artifacts_ok:
        st.error(f"找不到模型：{_model_pkl}")
    else:
        _thr_info = _load_threshold_info(model_dir)
        _feat_names = _load_feature_names(model_dir)

        st.caption(
            f"Threshold: **{_thr_info['threshold']:.4f}** "
            f"（{_thr_info.get('method', '?')}）  "
            f"| 特徵數: **{len(_feat_names)}**"
        )

        thr_override = st.checkbox("手動設定 Threshold", value=False)
        if thr_override:
            threshold = st.slider(
                "Threshold", min_value=0.0, max_value=1.0,
                value=float(_thr_info["threshold"]), step=0.01,
            )
        else:
            threshold = float(_thr_info["threshold"])

    st.divider()
    run_btn = st.button("執行預測", type="primary", disabled=not _artifacts_ok)

# ── Main ──────────────────────────────────────────────────────────────────────

st.title("🛰️ 軌道機動 ML 預測系統")
st.markdown(
    "整合 **LightGBM + TLE 特徵工程**，對 Starlink 衛星進行機動概率評分。  "
    "模型以 MEME 星曆殘差為 ground-truth 標籤訓練。"
)

if not _artifacts_ok:
    st.warning("請先執行 `python train.py` 產生模型，或調整側欄的模型目錄路徑。")
    st.stop()

if not run_btn:
    st.info("在側欄輸入 NORAD ID，點擊「執行預測」開始分析。")
    st.stop()

if not norad_ids:
    st.error("請輸入至少一個有效的 NORAD ID。")
    st.stop()

# ── Feature importance (model-level, shown once) ──────────────────────────────
model = _load_model(str(_model_pkl))
feat_names = _load_feature_names(model_dir)

with st.expander("📊 模型特徵重要性（展開查看）", expanded=False):
    st.plotly_chart(
        _fig_feature_importance(model, feat_names),
        use_container_width=True,
        key="feat_imp_global",
    )

st.divider()

# ── Per-satellite analysis ────────────────────────────────────────────────────
for norad_id in norad_ids:
    st.subheader(f"📡 NORAD {norad_id}")

    # 1. Build features
    with st.spinner(f"建構 NORAD {norad_id} 特徵矩陣 …"):
        feat_df = _build_features(norad_id, db_path)

    if feat_df.empty:
        st.warning(f"NORAD {norad_id}：資料庫中無 TLE 資料，跳過。")
        st.divider()
        continue

    # 2. Score
    scored = _score(model, feat_df, feat_names)
    valid_scores = scored["p_maneuver"].dropna()
    n_valid  = int(valid_scores.count())
    n_alerts = int((valid_scores >= threshold).sum())
    p_max    = float(valid_scores.max()) if n_valid > 0 else float("nan")
    n_total  = len(scored)

    # 3. Metrics row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("TLE epochs", n_total)
    c2.metric("評分成功", n_valid,
              delta=f"丟棄 {n_total - n_valid} NaN 行" if n_total > n_valid else None,
              delta_color="off")
    c3.metric("⚠ 警報數", n_alerts,
              delta=f"{n_alerts/n_valid*100:.1f}%" if n_valid > 0 else None,
              delta_color="inverse" if n_alerts > 0 else "off")
    c4.metric("最高 p_maneuver", f"{p_max:.4f}" if not np.isnan(p_max) else "N/A")

    # 4. Tabs
    tab_pred, tab_meme, tab_feat, tab_table = st.tabs(
        ["📈 機動概率", "🛰️ MEME 殘差對照", "🔬 特徵詳情", "📋 預測資料表"]
    )

    with tab_pred:
        st.plotly_chart(
            _fig_probability(scored, threshold, norad_id),
            use_container_width=True,
            key=f"prob_{norad_id}",
        )
        if n_alerts > 0:
            alert_rows = scored[scored["p_maneuver"] >= threshold][
                ["epoch_utc", "p_maneuver", "sma_km", "d_sma_km", "tle_gap_hours"]
            ].copy()
            alert_rows["p_maneuver"] = alert_rows["p_maneuver"].round(4)
            st.caption(f"共 {n_alerts} 個警報 epoch（threshold = {threshold:.4f}）")
            st.dataframe(alert_rows, use_container_width=True, height=200)

    with tab_meme:
        with st.spinner("載入 MEME 殘差 …"):
            resid = _load_residuals(norad_id, resid_glob)

        if resid.empty:
            st.info(
                f"NORAD {norad_id} 無 MEME 殘差資料。  \n"
                "請確認 `data/comparison/residuals_*.csv` 存在且包含此衛星。"
            )
        else:
            st.plotly_chart(
                _fig_residuals(resid, scored, threshold, norad_id),
                use_container_width=True,
                key=f"resid_{norad_id}",
            )

            # Quick stats
            n_meme_events = int((resid["pos_err_km"] > 50).sum())
            peak_err = float(resid["pos_err_km"].max())
            rc1, rc2 = st.columns(2)
            rc1.metric("MEME pos_err > 50 km 筆數", n_meme_events)
            rc2.metric("最大 pos_err (km)", f"{peak_err:.1f}")

    with tab_feat:
        st.plotly_chart(
            _fig_key_features(scored, norad_id),
            use_container_width=True,
            key=f"kfeat_{norad_id}",
        )
        with st.expander("全特徵欄位（數值預覽）"):
            disp_cols = ["epoch_utc", "p_maneuver"] + [c for c in feat_names if c in scored.columns]
            fmt = {c: "{:.5f}" for c in feat_names if c in scored.columns}
            st.dataframe(
                scored[disp_cols].dropna(subset=["p_maneuver"]).style.format(fmt),
                use_container_width=True,
                height=300,
            )

    with tab_table:
        out_cols = (
            ["epoch_utc", "p_maneuver"]
            + [c for c in feat_names if c in scored.columns]
        )
        out_df = scored[out_cols].copy()
        out_df["alert"] = out_df["p_maneuver"] >= threshold

        def _highlight_alert(row):
            return ["background-color: #3d0000" if row["alert"] else "" for _ in row]

        st.dataframe(
            out_df.style
                  .apply(_highlight_alert, axis=1)
                  .format({"p_maneuver": "{:.4f}",
                            **{c: "{:.5f}" for c in feat_names if c in out_df.columns}}),
            use_container_width=True,
            height=400,
        )

        csv_bytes = out_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label=f"📥 下載 NORAD {norad_id} 預測結果 CSV",
            data=csv_bytes,
            file_name=f"predictions_{norad_id}_app.csv",
            mime="text/csv",
            key=f"dl_{norad_id}",
        )

    st.divider()
