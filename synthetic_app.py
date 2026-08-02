"""
synthetic_app.py — Streamlit TLE Synthetic Data Generator
用法: streamlit run synthetic_app.py
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import joblib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from synthetic_tle import (
    ManeuverParams,
    ManeuverType,
    NoiseLevel,
    OrbitalElements,
    RE,
    apply_maneuver,
    batch_generate,
    format_tle,
    generate_sequence,
    generate_training_pair,
    seq_to_tle_text,
)

st.set_page_config(
    page_title="TLE 合成資料生成器",
    page_icon="🛸",
    layout="wide",
)

# ─── Sidebar ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("🛸 TLE 合成資料生成器")
    st.caption("TASA-S-1150268 | A2.2 合成資料模組")

    st.subheader("📡 衛星基本資訊")
    sat_name  = st.text_input("衛星名稱", value="SYNTH-A")
    norad_id  = st.number_input("NORAD ID", value=99001, min_value=1, max_value=99999, step=1)

    st.subheader("🌍 軌道初始條件（Epoch 六元素）")
    alt_km   = st.slider("軌道高度 [km]", 200, 2000, 550, 10)
    sma_km   = RE + alt_km
    ecc      = st.number_input("離心率 e", min_value=0.0, max_value=0.3, value=0.001, step=0.001, format="%.4f")
    inc_deg  = st.slider("傾角 i [°]", 0.0, 180.0, 53.0, 0.5)
    raan_deg = st.slider("升交點赤經 Ω [°]", 0.0, 360.0, 0.0, 1.0)
    argp_deg = st.slider("近地點引數 ω [°]", 0.0, 360.0, 0.0, 1.0)
    ma_deg   = st.slider("平均近點角 M₀ [°]", 0.0, 360.0, 0.0, 1.0)

    epoch_date = st.date_input("Epoch 日期", value=datetime(2026, 5, 1).date())
    epoch_time = st.time_input("Epoch 時間 (UTC)", value=datetime(2026, 5, 1, 0, 0).time())
    epoch = datetime(
        epoch_date.year, epoch_date.month, epoch_date.day,
        epoch_time.hour, epoch_time.minute, epoch_time.second,
        tzinfo=timezone.utc,
    )

    with st.expander("進階：BSTAR 阻力項"):
        bstar = st.number_input(
            "BSTAR", value=1e-4, min_value=1e-6, max_value=1e-2,
            step=1e-5, format="%.2e",
        )

    st.divider()
    st.subheader("🚀 機動設定")

    mtype_label = st.selectbox(
        "機動類型",
        options=[
            "順行 (Prograde) — 升軌",
            "逆行 (Retrograde) — 降軌",
            "法向 (Normal) — 增加傾角",
            "反法向 (Anti-normal) — 降低傾角",
            "Hohmann 轉移 (兩段式升軌)",
            "複合 (Prograde + Normal)",
        ],
    )
    _mtype_map = {
        "順行 (Prograde) — 升軌":       ManeuverType.PROGRADE,
        "逆行 (Retrograde) — 降軌":     ManeuverType.RETROGRADE,
        "法向 (Normal) — 增加傾角":     ManeuverType.NORMAL,
        "反法向 (Anti-normal) — 降低傾角": ManeuverType.ANTINORMAL,
        "Hohmann 轉移 (兩段式升軌)":    ManeuverType.HOHMANN,
        "複合 (Prograde + Normal)":     ManeuverType.COMBINED,
    }
    mtype = _mtype_map[mtype_label]

    col1, col2 = st.columns(2)
    with col1:
        dv_m_s = st.number_input(
            "ΔV [m/s]", min_value=0.001, max_value=500.0, value=5.0, step=0.1, format="%.3f"
        )
    with col2:
        delta_t = st.slider("Delta-T [天]", 1, 90, 30, 1)

    if mtype == ManeuverType.COMBINED:
        pro_frac = st.slider("順行分量佔比", 0.0, 1.0, 0.7, 0.05)
    else:
        pro_frac = 1.0

    st.divider()
    st.subheader("📋 序列設定")
    col3, col4 = st.columns(2)
    with col3:
        n_before = st.slider("機動前 TLE 數", 5, 60, 20)
    with col4:
        n_after  = st.slider("機動後 TLE 數", 5, 60, 20)

    dt_days = st.slider("TLE 間隔 [天]", 1, 7, 3)
    noise_label = st.selectbox("雜訊等級", ["低 (LOW)", "中 (MEDIUM)", "高 (HIGH)"])
    noise_level = {
        "低 (LOW)":    NoiseLevel.LOW,
        "中 (MEDIUM)": NoiseLevel.MEDIUM,
        "高 (HIGH)":   NoiseLevel.HIGH,
    }[noise_label]

    generate_btn = st.button("▶ 生成 TLE 序列", type="primary", use_container_width=True)

# ─── Build initial elements ──────────────────────────────────────────────────

initial = OrbitalElements(
    sma_km   = sma_km,
    ecc      = ecc,
    inc_deg  = inc_deg,
    raan_deg = raan_deg,
    argp_deg = argp_deg,
    ma_deg   = ma_deg,
    epoch    = epoch,
    bstar    = bstar,
    norad_id = int(norad_id),
)

maneuver = ManeuverParams(
    maneuver_type        = mtype,
    dv_m_s               = dv_m_s,
    delta_t_days         = float(delta_t),
    dv_prograde_fraction = pro_frac,
)

post_elements = apply_maneuver(initial.propagate(delta_t), maneuver)

# ─── Detection helpers ───────────────────────────────────────────────────────

_ROOT        = Path(__file__).parent
_LGBM_PKL    = _ROOT / "Orbital_Maneuver_V2" / "models_plan_b" / "lgbm_maneuver_v1.pkl"
_LGBM_THR    = _ROOT / "Orbital_Maneuver_V2" / "models_plan_b" / "threshold.json"
_LGBM_FEAT   = _ROOT / "Orbital_Maneuver_V2" / "models_plan_b" / "feature_names.json"

_MU   = 398600.4418
_J2   = 1.08263e-3
_RE_D = 6378.137      # local alias (RE already imported from synthetic_tle)
_THR_DI    = 0.02     # deg
_THR_DE    = 0.001
_THR_DRAAN = 0.1      # deg

FEAT_NAMES = [
    "alt_km", "inc_deg", "ecc", "inc_family_enc",
    "net_da_km", "max_da_km", "da_std", "da_abs_mean",
    "max_di_deg", "max_draan_res_deg",
    "neg_streak", "total_drop_km", "monotone_decay",
    "n_transitions", "n_tle", "mean_tle_gap_h", "max_tle_gap_h",
    "dv_net_ms", "da_monotonic_decay", "bstar_f107_normalized",
]


def _detect_rule(seq: list, f107: float | None = None) -> pd.DataFrame:
    """P1-P6 rule-based detector (inline, no DuckDB dependency)."""
    rows = []
    for i in range(1, len(seq)):
        prev, curr = seq[i - 1], seq[i]
        dt_s = (curr.epoch - prev.epoch).total_seconds()
        if dt_s <= 0 or dt_s > 86400 * 7:
            continue

        da = curr.sma_km - prev.sma_km
        di = curr.inc_deg - prev.inc_deg
        de = curr.ecc - prev.ecc

        # J2-corrected RAAN residual
        draan_raw = ((curr.raan_deg - prev.raan_deg + 180) % 360) - 180
        n_rad    = np.sqrt(_MU / prev.sma_km ** 3)
        p_km     = prev.sma_km * (1 - prev.ecc ** 2)
        j2_rate  = np.degrees(
            -1.5 * _J2 * (_RE_D / p_km) ** 2 * n_rad * np.cos(np.radians(prev.inc_deg))
        )
        draan_res = draan_raw - j2_rate * dt_s

        # P2 altitude-adaptive Δa threshold
        alt = prev.sma_km - _RE_D
        thr = 2.0 if alt < 400 else (0.5 if alt > 600 else 1.0)
        # P5 F10.7 multiplier
        if f107 is not None and alt < 600:
            if   f107 > 200: thr *= 2.0
            elif f107 > 150: thr *= 1.5
            elif f107 > 100: thr *= 1.2

        rows.append({
            "t_from":       prev.epoch,
            "t_to":         curr.epoch,
            "dt_h":         dt_s / 3600,
            "da_km":        round(da, 4),
            "di_deg":       round(di, 5),
            "de":           round(de, 6),
            "draan_res_deg": round(draan_res, 4),
            "thr_da":       round(thr, 3),
            "flagged": (
                abs(da) > thr or abs(di) > _THR_DI
                or abs(de) > _THR_DE or abs(draan_res) > _THR_DRAAN
            ),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # P1: suppress monotone-decay (atmospheric drag) da flags
    da_v    = df["da_km"].values
    net_da  = float(da_v.sum())
    neg_str = cur = 0
    for v in da_v:
        if v < -0.3:
            cur += 1; neg_str = max(neg_str, cur)
        else:
            cur = 0
    total_drop = -net_da if net_da < 0 else 0.0
    mono = neg_str >= 5 and total_drop > 5.0 and net_da < -3.0

    if mono:
        df["flagged"] = (
            (df["di_deg"].abs() > _THR_DI) |
            (df["de"].abs()     > _THR_DE)  |
            (df["draan_res_deg"].abs() > _THR_DRAAN)
        )
    df["mono_suppressed"] = mono
    return df


def _compute_features(trans: pd.DataFrame, seq: list) -> dict:
    """Compute the 20 LightGBM aggregate features from a transitions DataFrame."""
    smas   = np.array([e.sma_km for e in seq])
    bstars = np.array([e.bstar  for e in seq])
    alt    = float(np.mean(smas)) - _RE_D
    inc    = float(np.mean([e.inc_deg for e in seq]))
    ecc    = float(np.mean([e.ecc    for e in seq]))

    # Inclination family (rough bin encoding matching training data)
    if inc < 20:       ifam = 0
    elif inc < 60:     ifam = 1
    elif inc < 75:     ifam = 2
    elif inc < 85:     ifam = 3
    else:              ifam = 4

    da_v = trans["da_km"].values if len(trans) else np.array([0.0])
    net_da = float(da_v.sum())

    neg_str = cur = 0
    for v in da_v:
        if v < -0.3:
            cur += 1; neg_str = max(neg_str, cur)
        else:
            cur = 0
    total_drop = -net_da if net_da < 0 else 0.0
    mono = int(neg_str >= 5 and total_drop > 5.0 and net_da < -3.0)

    # ΔV estimate from net_da (circular orbit vis-viva)
    a_km   = float(np.mean(smas))
    v_c    = float(np.sqrt(_MU / a_km))   # km/s
    dv_ms  = abs(net_da) * v_c / (2.0 * a_km) * 1000.0   # m/s

    dt_h = trans["dt_h"].values if len(trans) else np.array([0.0])
    di_v = trans["di_deg"].values    if len(trans) else np.array([0.0])
    dr_v = trans["draan_res_deg"].values if len(trans) else np.array([0.0])

    return {
        "alt_km":               alt,
        "inc_deg":              inc,
        "ecc":                  ecc,
        "inc_family_enc":       ifam,
        "net_da_km":            net_da,
        "max_da_km":            float(np.max(np.abs(da_v))),
        "da_std":               float(np.std(da_v)),
        "da_abs_mean":          float(np.mean(np.abs(da_v))),
        "max_di_deg":           float(np.max(np.abs(di_v))),
        "max_draan_res_deg":    float(np.max(np.abs(dr_v))),
        "neg_streak":           neg_str,
        "total_drop_km":        total_drop,
        "monotone_decay":       mono,
        "n_transitions":        len(trans),
        "n_tle":                len(seq),
        "mean_tle_gap_h":       float(np.mean(dt_h)),
        "max_tle_gap_h":        float(np.max(dt_h)),
        "dv_net_ms":            dv_ms,
        "da_monotonic_decay":   mono,
        "bstar_f107_normalized": float(np.mean(bstars)),   # no F10.7 → raw bstar
    }


@st.cache_resource
def _load_lgbm():
    if not _LGBM_PKL.exists():
        return None, None, None
    model     = joblib.load(_LGBM_PKL)
    threshold = json.loads(_LGBM_THR.read_text())["threshold"]
    features  = json.loads(_LGBM_FEAT.read_text())
    return model, threshold, features


# ─── Main Tabs ───────────────────────────────────────────────────────────────

tab_summary, tab_tle, tab_plot, tab_detect, tab_batch = st.tabs([
    "📋 軌道摘要", "📝 TLE 文字", "📈 軌道演化圖", "🔍 偵測分析", "🎲 批量資料集"
])

# ════════════════════════════════════════════════════════════════════════════
# Tab 1: Summary
# ════════════════════════════════════════════════════════════════════════════

with tab_summary:
    st.subheader("機動前後軌道參數比較")

    pre_at_mnvr = initial.propagate(delta_t)

    col_pre, col_post = st.columns(2)

    def _oe_card(el: OrbitalElements, title: str):
        st.markdown(f"**{title}**")
        st.metric("SMA [km]",  f"{el.sma_km:.3f}")
        st.metric("高度 [km]", f"{el.alt_km:.3f}")
        st.metric("離心率",    f"{el.ecc:.6f}")
        st.metric("傾角 [°]",  f"{el.inc_deg:.4f}")
        st.metric("Ω [°]",     f"{el.raan_deg:.4f}")
        st.metric("ω [°]",     f"{el.argp_deg:.4f}")
        st.metric("M [°]",     f"{el.ma_deg:.4f}")
        st.metric("n [rev/day]", f"{el.mean_motion_rev_day:.6f}")

    with col_pre:
        _oe_card(pre_at_mnvr, f"機動前（+{delta_t} 天時刻）")
    with col_post:
        _oe_card(post_elements, "機動後（即刻）")

    st.divider()
    st.subheader("機動效果")

    delta_a = post_elements.sma_km - pre_at_mnvr.sma_km
    delta_i = post_elements.inc_deg - pre_at_mnvr.inc_deg
    delta_e = post_elements.ecc     - pre_at_mnvr.ecc

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Δa [km]", f"{delta_a:+.4f}")
    c2.metric("Δi [°]",  f"{delta_i:+.4f}")
    c3.metric("Δe",      f"{delta_e:+.6f}")
    c4.metric("ΔV [m/s]", f"{dv_m_s:.3f}")

    # Derived metrics
    v_c = initial.circ_velocity_km_s
    st.info(
        f"**圓軌道速度** v_c = {v_c*1000:.1f} m/s  ·  "
        f"**軌道週期** = {initial.orbital_period_s/60:.1f} min  ·  "
        f"**BSTAR** = {bstar:.2e}  ·  "
        f"**平均運動** n = {initial.mean_motion_rev_day:.6f} rev/day"
    )

    # Show sample TLE for initial epoch
    st.subheader("初始 TLE（Epoch 時刻）")
    l0, l1, l2 = format_tle(initial, sat_name=sat_name)
    st.code(f"{l0}\n{l1}\n{l2}", language="text")


# ════════════════════════════════════════════════════════════════════════════
# Tab 2: TLE Text
# ════════════════════════════════════════════════════════════════════════════

with tab_tle:
    if not generate_btn and "pre_seq" not in st.session_state:
        st.info("請點選左側「▶ 生成 TLE 序列」按鈕以產生完整序列。")
    else:
        if generate_btn:
            with st.spinner("生成 TLE 序列中…"):
                pre_seq, post_seq = generate_training_pair(
                    initial, maneuver, n_before, n_after, dt_days, noise_level,
                    rng=np.random.default_rng(42),
                )
            st.session_state["pre_seq"]  = pre_seq
            st.session_state["post_seq"] = post_seq

        pre_seq  = st.session_state["pre_seq"]
        post_seq = st.session_state["post_seq"]

        pre_text  = seq_to_tle_text(pre_seq,  sat_name)
        post_text = seq_to_tle_text(post_seq, sat_name)

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown(f"**機動前 TLE（{len(pre_seq)} 筆）**")
            st.text_area("pre_tle", pre_text, height=400, label_visibility="collapsed")
        with col_r:
            st.markdown(f"**機動後 TLE（{len(post_seq)} 筆）**")
            st.text_area("post_tle", post_text, height=400, label_visibility="collapsed")

        # Download
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"{sat_name}_pre.tle",  pre_text)
            z.writestr(f"{sat_name}_post.tle", post_text)
        buf.seek(0)
        st.download_button(
            "⬇ 下載 TLE 序列 (.zip)",
            data=buf,
            file_name=f"{sat_name}_tle_pair.zip",
            mime="application/zip",
        )


# ════════════════════════════════════════════════════════════════════════════
# Tab 3: Orbital Evolution Plot
# ════════════════════════════════════════════════════════════════════════════

with tab_plot:
    if "pre_seq" not in st.session_state:
        st.info("請先生成 TLE 序列（Tab：TLE 文字）。")
    else:
        pre_seq  = st.session_state["pre_seq"]
        post_seq = st.session_state["post_seq"]

        # Build DataFrame
        def seq_df(seq: list[OrbitalElements], label: str) -> pd.DataFrame:
            return pd.DataFrame([
                {
                    "epoch":   e.epoch,
                    "sma_km":  e.sma_km,
                    "alt_km":  e.alt_km,
                    "ecc":     e.ecc,
                    "inc_deg": e.inc_deg,
                    "raan_deg": e.raan_deg,
                    "label":   label,
                }
                for e in seq
            ])

        df_pre  = seq_df(pre_seq,  "機動前")
        df_post = seq_df(post_seq, "機動後")
        df_all  = pd.concat([df_pre, df_post], ignore_index=True)

        mnvr_time = initial.epoch.__class__(
            *(initial.epoch + __import__("datetime").timedelta(days=delta_t)).timetuple()[:6],
            tzinfo=timezone.utc,
        )

        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=["SMA / 軌道高度 [km]", "傾角 [°]", "離心率"],
            shared_xaxes=True,
            vertical_spacing=0.08,
        )

        for label, grp in df_all.groupby("label"):
            color = "#2E75B6" if label == "機動前" else "#C0504D"
            fig.add_trace(go.Scatter(
                x=grp["epoch"], y=grp["sma_km"] - RE,
                mode="markers+lines", name=label,
                marker=dict(color=color, size=6),
                line=dict(color=color, width=1.5),
                showlegend=True,
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=grp["epoch"], y=grp["inc_deg"],
                mode="markers+lines", name=label, showlegend=False,
                marker=dict(color=color, size=6),
                line=dict(color=color, width=1.5),
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=grp["epoch"], y=grp["ecc"],
                mode="markers+lines", name=label, showlegend=False,
                marker=dict(color=color, size=6),
                line=dict(color=color, width=1.5),
            ), row=3, col=1)

        # Maneuver line
        for r in [1, 2, 3]:
            fig.add_vline(
                x=mnvr_time.isoformat(),
                line_dash="dash", line_color="#FF6600", line_width=2,
                row=r, col=1,
            )

        fig.add_annotation(
            x=mnvr_time.isoformat(), y=1.05,
            xref="x", yref="paper",
            text=f"機動 ΔV={dv_m_s:.2f} m/s",
            showarrow=True, arrowhead=2,
            font=dict(color="#FF6600", size=12),
        )

        fig.update_layout(
            height=700,
            title=f"{sat_name} 機動前後軌道演化",
            legend=dict(orientation="h", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Summary table
        st.subheader("序列統計")
        stats = pd.DataFrame({
            "項目":        ["SMA 均值 [km]", "高度均值 [km]", "傾角均值 [°]", "離心率均值"],
            "機動前":      [
                f"{df_pre['sma_km'].mean():.3f}",
                f"{(df_pre['sma_km'] - RE).mean():.3f}",
                f"{df_pre['inc_deg'].mean():.4f}",
                f"{df_pre['ecc'].mean():.6f}",
            ],
            "機動後":      [
                f"{df_post['sma_km'].mean():.3f}",
                f"{(df_post['sma_km'] - RE).mean():.3f}",
                f"{df_post['inc_deg'].mean():.4f}",
                f"{df_post['ecc'].mean():.6f}",
            ],
            "差值（後-前）": [
                f"{(df_post['sma_km'].mean() - df_pre['sma_km'].mean()):+.4f}",
                f"{((df_post['sma_km'] - RE).mean() - (df_pre['sma_km'] - RE).mean()):+.4f}",
                f"{(df_post['inc_deg'].mean() - df_pre['inc_deg'].mean()):+.4f}",
                f"{(df_post['ecc'].mean() - df_pre['ecc'].mean()):+.6f}",
            ],
        })
        st.dataframe(stats, hide_index=True, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# Tab 4: Detection Analysis
# ════════════════════════════════════════════════════════════════════════════

with tab_detect:
    if "pre_seq" not in st.session_state:
        st.info("請先在「📝 TLE 文字」頁籤點擊「▶ 生成 TLE 序列」。")
    else:
        pre_seq  = st.session_state["pre_seq"]
        post_seq = st.session_state["post_seq"]

        # ── 偵測設定列 ────────────────────────────────────────────────────
        det_col1, det_col2, det_col3 = st.columns([2, 2, 2])
        with det_col1:
            f107_val = st.number_input(
                "F10.7 太陽通量 [sfu]（P5 自適應閾值）",
                min_value=65.0, max_value=300.0, value=128.0, step=1.0,
            )
            use_p5 = st.checkbox("啟用 P5 F10.7 閾值乘數", value=False)
        with det_col2:
            show_only_flagged = st.checkbox("只顯示旗標轉移", value=False)
        with det_col3:
            detect_scope = st.radio(
                "偵測範圍",
                ["全序列（前+後合併）", "僅機動前序列", "僅機動後序列"],
                horizontal=True,
            )

        # ── 選擇序列 ──────────────────────────────────────────────────────
        if detect_scope == "僅機動前序列":
            detect_seq = pre_seq
        elif detect_scope == "僅機動後序列":
            detect_seq = post_seq
        else:
            detect_seq = pre_seq + post_seq
        maneuver_idx = len(pre_seq) - 1   # transition index near the maneuver

        # ── 規則偵測器 (P1–P6) ────────────────────────────────────────────
        f107_in = float(f107_val) if use_p5 else None
        trans_df = _detect_rule(detect_seq, f107=f107_in)

        n_flagged  = int(trans_df["flagged"].sum()) if len(trans_df) else 0
        rule_hit   = n_flagged > 0
        # Check if the maneuver transition itself is flagged (full-seq mode)
        mnvr_flagged = False
        if detect_scope == "全序列（前+後合併）" and len(trans_df) > maneuver_idx:
            mnvr_flagged = bool(trans_df.iloc[maneuver_idx]["flagged"])

        # ── LightGBM 預測 ─────────────────────────────────────────────────
        lgbm_model, lgbm_thr, lgbm_feats = _load_lgbm()
        feats_dict = _compute_features(trans_df, detect_seq)
        feat_row   = pd.DataFrame([feats_dict])[FEAT_NAMES]

        lgbm_prob    = None
        lgbm_hit     = None
        if lgbm_model is not None:
            lgbm_prob = float(lgbm_model.predict_proba(feat_row)[0][1])
            lgbm_hit  = lgbm_prob >= lgbm_thr

        # ── EP 漂移偵測 ───────────────────────────────────────────────────
        pre_smas  = [e.sma_km for e in pre_seq]
        post_smas = [e.sma_km for e in post_seq]
        dt_day    = float(
            (pre_seq[-1].epoch - pre_seq[0].epoch).total_seconds() / 86400
        ) if len(pre_seq) > 1 else float(dt_days)
        pre_rate  = (pre_smas[-1] - pre_smas[0]) / max(dt_day, 0.1)   # km/day
        post_rate = (post_smas[-1] - post_smas[0]) / max(dt_day, 0.1)
        da_jump   = post_seq[0].sma_km - pre_seq[-1].sma_km
        ep_hit    = (post_rate - pre_rate) > 0.02 or abs(da_jump) > 0.3

        # ════ STATUS BANNER ════════════════════════════════════════════════
        any_hit = rule_hit or (lgbm_hit or False) or ep_hit
        true_maneuver = detect_scope != "僅機動前序列"

        if true_maneuver and any_hit:
            st.success(f"✅ 機動偵測成功  |  ΔV={dv_m_s:.3f} m/s  |  Δa={feats_dict['net_da_km']:+.4f} km")
        elif true_maneuver and not any_hit:
            est_thr_dv = (
                initial.circ_velocity_km_s
                * (2.0 if (initial.alt_km < 400) else (0.5 if initial.alt_km > 600 else 1.0))
                / (2.0 * initial.sma_km)
                * 1000
            )
            st.error(
                f"❌ 機動未被偵測  |  ΔV={dv_m_s:.3f} m/s 低於估計門檻 {est_thr_dv:.2f} m/s"
                f"  |  Δa={feats_dict['net_da_km']:+.4f} km"
            )
        else:
            st.info("僅機動前序列 — 正常無機動基準")

        # ════ 方法比較卡片 ═════════════════════════════════════════════════
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "地面真值",
            "機動 ✓" if true_maneuver else "無機動",
            f"ΔV={dv_m_s:.3f} m/s | Δa={feats_dict['net_da_km']:+.3f} km",
        )
        c2.metric(
            "規則偵測器 P1-P6",
            "✅ 偵測" if rule_hit else "❌ 未偵測",
            f"{n_flagged}/{len(trans_df)} 轉移旗標"
            + (" | P1 抑制" if len(trans_df) > 0 and bool(trans_df.iloc[0].get("mono_suppressed", False)) else ""),
        )
        c3.metric(
            "LightGBM (AUC=0.9977)",
            "✅ 偵測" if lgbm_hit else ("❌ 未偵測" if lgbm_hit is not None else "N/A"),
            f"P={lgbm_prob:.4f} | 閾值={lgbm_thr:.4f}" if lgbm_prob is not None else "模型載入失敗",
        )
        c4.metric(
            "EP 漂移偵測",
            "✅ 偵測" if ep_hit else "❌ 未偵測",
            f"Δrate={post_rate - pre_rate:+.4f} km/day | jump={da_jump:+.4f} km",
        )

        # ════ 逐轉移分析表格 ════════════════════════════════════════════
        st.divider()
        st.subheader("逐轉移偵測細節")

        if len(trans_df) == 0:
            st.warning("無有效轉移（序列點數不足或時間間隔過大）")
        else:
            # 標記機動位置
            trans_disp = trans_df.copy()
            trans_disp.index = range(len(trans_disp))

            if detect_scope == "全序列（前+後合併）":
                trans_disp["段落"] = [
                    "機動前" if i < maneuver_idx else ("機動點" if i == maneuver_idx else "機動後")
                    for i in range(len(trans_disp))
                ]
            else:
                trans_disp["段落"] = detect_scope.replace("僅", "")

            trans_disp["時間（from）"] = trans_disp["t_from"].dt.strftime("%m-%d %H:%M")
            trans_disp["Δa [km]"]    = trans_disp["da_km"].map(lambda x: f"{x:+.4f}")
            trans_disp["Δi [°]"]     = trans_disp["di_deg"].map(lambda x: f"{x:+.5f}")
            trans_disp["ΔΩ_res [°]"] = trans_disp["draan_res_deg"].map(lambda x: f"{x:+.4f}")
            trans_disp["Δe"]         = trans_disp["de"].map(lambda x: f"{x:+.6f}")
            trans_disp["閾值 [km]"]  = trans_disp["thr_da"].map(lambda x: f"{x:.3f}")
            trans_disp["旗標"]       = trans_disp["flagged"].map({True: "🚨 YES", False: "—"})

            show_cols = ["段落", "時間（from）", "Δa [km]", "Δi [°]",
                         "ΔΩ_res [°]", "Δe", "閾值 [km]", "旗標"]
            disp = trans_disp[show_cols]
            if show_only_flagged:
                disp = disp[trans_disp["flagged"]]

            def _row_style(row):
                if "YES" in str(row["旗標"]) and row.get("段落") == "機動點":
                    return ["background-color:#d4edda"] * len(row)   # green
                if "YES" in str(row["旗標"]):
                    return ["background-color:#fff3cd"] * len(row)   # yellow
                if str(row.get("段落")) == "機動點":
                    return ["background-color:#cce5ff"] * len(row)   # blue
                return [""] * len(row)

            st.dataframe(
                disp.style.apply(_row_style, axis=1),
                use_container_width=True,
                height=min(50 + 35 * len(disp), 450),
            )

            # 判斷原因
            if rule_hit:
                max_da_row = trans_df.loc[trans_df["da_km"].abs().idxmax()]
                st.caption(
                    f"規則偵測：最大 |Δa| = {abs(max_da_row['da_km']):.4f} km"
                    f"（閾值 {max_da_row['thr_da']:.3f} km），"
                    f"時間：{max_da_row['t_from'].strftime('%Y-%m-%d %H:%M')}"
                )
            else:
                max_da_abs = trans_df["da_km"].abs().max()
                min_thr    = trans_df["thr_da"].min()
                st.caption(
                    f"規則偵測未觸發：最大 |Δa| = {max_da_abs:.4f} km"
                    f"，低於最小閾值 {min_thr:.3f} km"
                )

        # ════ 軌道特徵向量（LightGBM 輸入） ═══════════════════════════
        st.divider()
        col_feat, col_imp = st.columns([1, 1])

        with col_feat:
            st.subheader("特徵向量（20 維）")
            feat_disp = pd.DataFrame({
                "特徵名稱": FEAT_NAMES,
                "數值": [
                    f"{feats_dict[k]:.4f}" if isinstance(feats_dict[k], float) else str(feats_dict[k])
                    for k in FEAT_NAMES
                ],
                "說明": [
                    "軌道高度 km", "傾角 °", "離心率", "傾角族別編碼",
                    "淨 Δa km", "最大 |Δa| km", "Δa 標準差", "Δa 絕對均值",
                    "最大 |Δi|°", "最大 |ΔRAAN_res|°",
                    "連續負向條帶", "總下降量 km", "單調衰減旗標",
                    "轉移數", "TLE 數", "平均間隔 h", "最大間隔 h",
                    "估算 ΔV m/s", "大氣阻力衰減旗標", "BSTAR (无F10.7)",
                ],
            })
            st.dataframe(feat_disp, use_container_width=True, hide_index=True, height=420)

        with col_imp:
            st.subheader("LightGBM 特徵重要度")
            if lgbm_model is not None:
                imp = lgbm_model.feature_importances_
                imp_df = (
                    pd.DataFrame({"feature": FEAT_NAMES, "importance": imp})
                    .sort_values("importance", ascending=True)
                )
                fig_imp = go.Figure(go.Bar(
                    x=imp_df["importance"],
                    y=imp_df["feature"],
                    orientation="h",
                    marker_color=[
                        "#C0504D" if feats_dict.get(f, 0) > np.percentile(list(feats_dict.values()), 75)
                        else "#2E75B6"
                        for f in imp_df["feature"]
                    ],
                    text=imp_df["importance"].map(lambda v: f"{v}"),
                    textposition="outside",
                ))
                fig_imp.update_layout(
                    height=450, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="Gain 重要度",
                )
                st.plotly_chart(fig_imp, use_container_width=True)
            else:
                st.warning("LightGBM 模型未載入")

        # ════ 可偵測性分析：ΔV 門檻掃描 ══════════════════════════════
        st.divider()
        st.subheader("可偵測性分析")
        st.caption(
            "固定當前軌道參數，掃描不同 ΔV 值，預測各方法的偵測狀態（Streamlit 模擬）"
        )

        dv_scan   = np.logspace(-3, np.log10(50), 40)   # 0.001 ~ 50 m/s
        rule_hits = []
        lgbm_hits = []
        da_results= []

        for dv_test in dv_scan:
            test_mnvr = ManeuverParams(
                maneuver_type        = mtype,
                dv_m_s               = float(dv_test),
                delta_t_days         = float(delta_t),
                dv_prograde_fraction = pro_frac,
            )
            rng_s = np.random.default_rng(0)
            try:
                p_seq, q_seq = generate_training_pair(
                    initial, test_mnvr, 10, 10, dt_days,
                    NoiseLevel.MEDIUM, rng=rng_s,
                )
                combo   = p_seq + q_seq
                t_df    = _detect_rule(combo, f107=f107_in)
                r_hit   = bool(t_df["flagged"].any()) if len(t_df) else False
                fd      = _compute_features(t_df, combo)
                da_results.append(fd["net_da_km"])

                l_hit = None
                if lgbm_model is not None:
                    fr = pd.DataFrame([fd])[FEAT_NAMES]
                    prob = float(lgbm_model.predict_proba(fr)[0][1])
                    l_hit = prob >= lgbm_thr
            except Exception:
                r_hit, l_hit = False, None
                da_results.append(0.0)

            rule_hits.append(r_hit)
            lgbm_hits.append(l_hit)

        scan_df = pd.DataFrame({
            "dv_m_s":   dv_scan,
            "net_da_km": da_results,
            "rule":     [1 if h else 0 for h in rule_hits],
            "lgbm":     [1 if h else 0 for h in lgbm_hits],
        })

        # Find detection thresholds
        rule_thr_dv = next((dv_scan[i] for i, h in enumerate(rule_hits) if h), None)
        lgbm_thr_dv = next((dv_scan[i] for i, h in enumerate(lgbm_hits) if h is True), None)

        fig_scan = go.Figure()
        fig_scan.add_trace(go.Scatter(
            x=scan_df["dv_m_s"], y=scan_df["net_da_km"],
            name="淨 Δa [km]", line=dict(color="#888", dash="dot"), yaxis="y2",
        ))
        fig_scan.add_trace(go.Scatter(
            x=scan_df["dv_m_s"], y=scan_df["rule"],
            name="規則偵測器 P1-P6", mode="markers+lines",
            marker=dict(color="#2E75B6", size=7), line=dict(color="#2E75B6"),
        ))
        fig_scan.add_trace(go.Scatter(
            x=scan_df["dv_m_s"], y=scan_df["lgbm"],
            name="LightGBM", mode="markers+lines",
            marker=dict(color="#C0504D", size=7), line=dict(color="#C0504D"),
        ))

        if rule_thr_dv:
            fig_scan.add_vline(
                x=rule_thr_dv, line_dash="dash", line_color="#2E75B6",
                annotation_text=f"規則閾值 {rule_thr_dv:.3f} m/s",
                annotation_position="top right",
            )
        if lgbm_thr_dv:
            fig_scan.add_vline(
                x=lgbm_thr_dv, line_dash="dash", line_color="#C0504D",
                annotation_text=f"LGBM閾值 {lgbm_thr_dv:.3f} m/s",
                annotation_position="bottom right",
            )
        # Current ΔV
        fig_scan.add_vline(
            x=dv_m_s, line_color="#FF6600", line_width=2,
            annotation_text=f"目前 ΔV={dv_m_s:.2f} m/s",
        )

        fig_scan.update_layout(
            title=f"可偵測性曲線 — {mtype_label}（高度 {alt_km:.0f} km）",
            xaxis=dict(title="ΔV [m/s]", type="log"),
            yaxis=dict(title="偵測（1=是，0=否）", range=[-0.1, 1.3]),
            yaxis2=dict(title="淨 Δa [km]", overlaying="y", side="right", showgrid=False),
            height=400,
            legend=dict(orientation="h", y=1.05),
        )
        st.plotly_chart(fig_scan, use_container_width=True)

        thr_col1, thr_col2, thr_col3 = st.columns(3)
        thr_col1.metric(
            "規則偵測 ΔV 門檻",
            f"{rule_thr_dv:.4f} m/s" if rule_thr_dv else ">50 m/s",
            f"Δa 閾值 {feats_dict.get('max_da_km', 0):.3f} km",
        )
        thr_col2.metric(
            "LightGBM ΔV 門檻",
            f"{lgbm_thr_dv:.4f} m/s" if lgbm_thr_dv else ">50 m/s",
            f"P 閾值 {lgbm_thr:.4f}",
        )
        thr_col3.metric(
            "當前 ΔV vs 門檻",
            "可偵測" if any_hit else "低於偵測門檻",
            f"{dv_m_s:.3f} m/s",
        )


# ════════════════════════════════════════════════════════════════════════════
# Tab 5: Batch Dataset Generation
# ════════════════════════════════════════════════════════════════════════════

with tab_batch:
    st.subheader("TASA A2.2 批量標記資料集生成")
    st.info(
        "生成大量帶標記的合成 TLE 序列（maneuver / no-maneuver），"
        "用於 LightGBM / LSTM / Transformer 模型訓練。"
    )

    b1, b2 = st.columns(2)
    with b1:
        n_mnvr    = st.number_input("機動樣本數", 100, 50000, 1000, 100)
        n_nomvr   = st.number_input("無機動樣本數", 100, 50000, 1000, 100)
        dv_min    = st.number_input("ΔV 最小值 [m/s]", 0.001, 10.0, 0.001, 0.001, format="%.3f")
        dv_max    = st.number_input("ΔV 最大值 [m/s]", 1.0, 500.0, 50.0, 1.0)
    with b2:
        b_n_before = st.slider("批量：機動前 TLE 數", 5, 30, 15)
        b_n_after  = st.slider("批量：機動後 TLE 數", 5, 30, 15)
        b_dt_days  = st.slider("批量：TLE 間隔 [天]", 1, 7, 3)
        b_seed     = st.number_input("亂數種子", 0, 99999, 42)

    batch_btn = st.button("🎲 開始批量生成", type="primary")

    if batch_btn:
        total = int(n_mnvr + n_nomvr)
        pbar = st.progress(0, text=f"生成中… 0 / {total}")

        def _progress(pct: float):
            pbar.progress(pct, text=f"生成中… {int(pct * total)} / {total}")

        with st.spinner("正在生成資料集…"):
            df = batch_generate(
                n_maneuver    = int(n_mnvr),
                n_no_maneuver = int(n_nomvr),
                dv_range_m_s  = (float(dv_min), float(dv_max)),
                n_before      = b_n_before,
                n_after       = b_n_after,
                dt_days       = float(b_dt_days),
                noise_level   = noise_level,
                seed          = int(b_seed),
                progress_cb   = _progress,
            )
        pbar.progress(1.0, text="完成！")

        st.success(f"✅ 生成 {len(df)} 筆樣本（{df['label'].sum()} 機動 + {(df['label']==0).sum()} 無機動）")

        # Preview
        st.subheader("資料集預覽（前 10 筆）")
        preview_cols = ["norad_id", "label", "maneuver_type", "dv_m_s",
                        "delta_t_days", "net_da_km", "net_di_deg", "alt_km", "inc_deg"]
        st.dataframe(df[preview_cols].head(10), use_container_width=True)

        # Statistics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("總樣本", len(df))
        c2.metric("機動比例", f"{df['label'].mean():.1%}")
        c3.metric("淨 Δa 均值 [km]", f"{df[df['label']==1]['net_da_km'].mean():.3f}")
        c4.metric("ΔV 範圍 [m/s]", f"{df[df['label']==1]['dv_m_s'].min():.3f} – {df[df['label']==1]['dv_m_s'].max():.1f}")

        # Download
        b_parquet = io.BytesIO()
        df.to_parquet(b_parquet, index=False)
        b_parquet.seek(0)

        b_csv = io.BytesIO()
        # CSV without TLE strings (too large)
        df[preview_cols].to_csv(b_csv, index=False, encoding="utf-8-sig")
        b_csv.seek(0)

        dl1, dl2 = st.columns(2)
        dl1.download_button(
            "⬇ 下載完整資料集 (.parquet，含 TLE)",
            data=b_parquet,
            file_name="synthetic_tle_dataset.parquet",
            mime="application/octet-stream",
        )
        dl2.download_button(
            "⬇ 下載特徵表 (.csv，不含 TLE)",
            data=b_csv,
            file_name="synthetic_tle_features.csv",
            mime="text/csv",
        )
