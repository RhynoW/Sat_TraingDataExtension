#!/usr/bin/env python3
"""
maneuver_app_2026September.py — 機動偵測儀表板（2026-09 HuggingFace 發布版，前身 maneuver_app_2026August.py）
=====================================================
配合最新 ML（models_meme_forecast）與統計偵測（CUSUM/BOCPD/SSA）模型的重寫版。
用法（本機）：  streamlit run maneuver_app_2026September.py

【與 August 版差異 — HuggingFace 發布相容】
  * 資料後端可切換：本機 14GB 全庫（space_db.duckdb），或 HF 遠端 Parquet（不需下載整庫）。
  * 設環境變數 HF_DATASET_REPO=<帳號>/<repo> 即切為遠端模式：
      啟動時自動安裝 httpfs、建立一顆輕量 stub DuckDB，內含指向
      hf://datasets/<repo>/... Parquet 的 VIEW；read_only 連線 + 統計裁剪只抓需要的區塊。
  * 目錄樹佈局須先用 export_to_hf_parquet.py 匯出並上傳（見 README_HF_Space.md）。
  * 未設 HF_DATASET_REPO 且本機存在 space_db.duckdb → 行為與 August 版完全相同。

功能（依需求）
  1. NORAD/名稱查詢（支援 wildcard）；LEO/MEO/GEO/HEO 自動分類套不同規則；
     單頁顯示 a/i/e/RAAN 連續時序 + Δa/Δi/Δe/ΔRAAN 差值。
  2. P1–P6 策略個別結果 + 合併結果。
  3. P2 閾值改「拋物線左側」曲線（UI 滑桿）。
  4. F10.7 自適應倍率改「拋物線」曲線（UI 滑桿）。
  5. 全 284 顆 MEME 艦隊級統計 + bootstrap 95% 信賴區間。
  9. MEME 僅 72h 模型與 TLE 比較（不做長時程外推）。
 10. 合成 TLE 批次生成（重用 synthetic_tle）。
"""
from __future__ import annotations

import colorsys
import glob
import os
from datetime import timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import maneuver_strategies_july as ms
import statistical_detectors as sd
import data_quality_audit as dqa
import constellation_anomaly as ca

DATA = Path("data")
R_E = 6378.137

st.set_page_config(page_title="機動偵測儀表板 2026-09", page_icon="🛰️", layout="wide")

# ── 資料後端 bootstrap（本機全庫 / HuggingFace 遠端 Parquet）─────────────────────
# 環境變數：
#   HF_DATASET_REPO   HF Dataset repo id，例如 "rhynowu/starlink-maneuver-db"（設了即走遠端）
#   LOCAL_DB_PATH     本機全庫路徑（預設 space_db.duckdb）
#   HF_STUB_PATH      遠端模式 stub duckdb 路徑（預設 space_hf.duckdb）
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "").strip()
LOCAL_DB = os.environ.get("LOCAL_DB_PATH", "space_db.duckdb")
STUB_DB = os.environ.get("HF_STUB_PATH", "space_hf.duckdb")

# 遠端 dataset 內的相對佈局（須與 export_to_hf_parquet.py 產出的目錄一致）
_HF_LAYOUT = {
    # view 名稱 : (glob 相對路徑, 是否為必要表)
    "raw_tle_archive":   ("raw_tle_archive/**/*.parquet", True),
    "catalog":           ("catalog.parquet", True),
    "sat_n2yo_metadata": ("sat_n2yo_metadata.parquet", False),
    "maneuver_labels":   ("maneuver_labels.parquet", False),
    "conjunction_events": ("conjunction_events.parquet", False),
    "training_samples":  ("training_samples.parquet", False),
    "training_samples_plan_b": ("training_samples_plan_b.parquet", False),
}


def _ensure_httpfs() -> None:
    """確保 httpfs 已安裝（安裝需可寫連線；之後 read_only 連線即可 autoload）。
    若環境變數 HF_TOKEN 存在，建立「持久化」HF secret，讓 read_only 連線也能讀 private dataset。"""
    try:
        c = duckdb.connect()
        c.execute("INSTALL httpfs")
        c.execute("LOAD httpfs")
        tok = os.environ.get("HF_TOKEN", "").strip()
        if tok:
            try:
                c.execute(
                    "CREATE OR REPLACE PERSISTENT SECRET hf_token "
                    "(TYPE huggingface, TOKEN ?)", [tok])
            except Exception as e:
                st.warning(f"HF secret 建立提示（private repo 才需要）：{e}")
        c.close()
    except Exception as e:  # 安裝失敗時仍嘗試往下（可能已裝好）
        st.warning(f"httpfs 安裝提示：{e}")


def _build_hf_stub(stub_path: str, repo: str) -> str:
    """建立/更新輕量 stub DuckDB：內含指向 hf://datasets/<repo>/... 的 VIEW。
    僅存 view 定義，不落地資料；查詢時 httpfs 依 row-group 統計只抓需要區塊。"""
    base = f"hf://datasets/{repo}"
    con = duckdb.connect(stub_path)
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    for view, (rel, required) in _HF_LAYOUT.items():
        url = f"{base}/{rel}"
        try:
            con.execute(f"CREATE OR REPLACE VIEW {view} AS "
                        f"SELECT * FROM read_parquet('{url}', union_by_name=true)")
        except Exception as e:
            if required:
                con.close()
                raise RuntimeError(f"必要表 {view} 建 VIEW 失敗（{url}）：{e}") from e
            # 可選表缺檔 → 跳過
    con.close()
    return stub_path


@st.cache_resource(show_spinner="初始化資料後端…")
def _bootstrap_db() -> tuple[str, str]:
    """回傳 (DB_PATH, backend)。backend ∈ {'local','hf'}。"""
    if HF_DATASET_REPO:
        _ensure_httpfs()
        _build_hf_stub(STUB_DB, HF_DATASET_REPO)
        return STUB_DB, "hf"
    if Path(LOCAL_DB).exists():
        return LOCAL_DB, "local"
    # 本機無全庫、也未指定 HF repo：若已有預建 stub 就用它
    if Path(STUB_DB).exists():
        _ensure_httpfs()
        return STUB_DB, "hf"
    st.error(
        "找不到資料來源。請擇一：\n"
        "  1) 本機放置 space_db.duckdb（完整庫），或\n"
        "  2) 設環境變數 HF_DATASET_REPO=<帳號>/<repo>（遠端 Parquet 模式）。\n"
        "遠端資料請先用 export_to_hf_parquet.py 匯出並上傳，詳見 README_HF_Space.md。")
    st.stop()


DB_PATH, DATA_BACKEND = _bootstrap_db()


# ── cached loaders ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_catalog() -> pd.DataFrame:
    con = duckdb.connect(DB_PATH, read_only=True)
    # HF 遠端模式：優先讀預先彙整的小 catalog（避免對 19.5M 列做全表 GROUP BY）
    if DATA_BACKEND == "hf":
        try:
            df = con.execute(
                "SELECT norad_id, name, n FROM catalog ORDER BY norad_id").fetchdf()
            con.close()
            return df
        except Exception:
            pass  # 無 catalog 表 → 回退全表彙整
    df = con.execute(
        "SELECT norad_id, ANY_VALUE(object_name) AS name, COUNT(*) n "
        "FROM raw_tle_archive GROUP BY norad_id"
    ).fetchdf()
    con.close()
    return df


@st.cache_data(show_spinner=False)
def load_registry_names() -> dict:
    try:
        from compare_tle_vs_ephemeris import load_registry
        reg = load_registry(DATA / "url_registry.csv")
        return {int(k): v for k, v in reg["sat_name"].items()}
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def load_tle(norad_id: int, start=None, end=None) -> pd.DataFrame:
    con = duckdb.connect(DB_PATH, read_only=True)
    q = ("SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
         "raan_deg, argp_deg, mean_anomaly_deg, bstar FROM raw_tle_archive "
         "WHERE norad_id=? ORDER BY epoch_utc")
    df = con.execute(q, [int(norad_id)]).fetchdf()
    con.close()
    if df.empty:
        return df
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    if start is not None:
        df = df[df["epoch"] >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df["epoch"] <= pd.Timestamp(end, tz="UTC")]
    return df.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_f107() -> dict:
    p = Path("f107_cache.csv")
    if not p.exists():
        return {}
    f = pd.read_csv(p)
    f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
    return dict(zip(f["epoch"], f["f107"]))


@st.cache_data(show_spinner=False)
def load_truth() -> pd.DataFrame:
    g = sorted((DATA / "meme_truth").glob("transitions_full_*.csv"))
    if not g:
        return pd.DataFrame()
    t = pd.read_csv(g[-1])
    t["t_to"] = pd.to_datetime(t["t_to"], utc=True)
    return t


@st.cache_data(show_spinner=False)
def load_stat_metrics() -> pd.DataFrame:
    g = sorted((DATA / "statistical_layer").glob("metrics_*.csv"))
    return pd.read_csv(g[-1]) if g else pd.DataFrame()


@st.cache_data(show_spinner=False)
def compute_ml_detection(norad: int, d0, d1):
    """逐窗口 ML 機動偵測（models_meme，window ≥5km）：對每個 TLE epoch 以
    [t_from−7d, t_from] 特徵窗預測『此窗是否發生機動』的機率。回傳 (df[epoch,prob], thr)。"""
    import json
    import joblib
    import build_training_dataset as btd

    mdir = Path("Orbital_Maneuver_V2/models_meme")
    if not (mdir / "lgbm_maneuver_v1.pkl").exists():
        return None
    model = joblib.load(mdir / "lgbm_maneuver_v1.pkl")
    feats = json.loads((mdir / "feature_names.json").read_text(encoding="utf-8"))
    thr = json.loads((mdir / "threshold.json").read_text(encoding="utf-8")).get("threshold", 0.5)

    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    f107 = load_f107()
    sr = sd.run_all(dd["sma_km"].to_numpy(float))
    win = dd.rename(columns={"epoch": "date_tag"})

    # NRLMSIS 阻力殘差（逐 epoch）＋ 7 天滾動最大 → 供特徵與物理閘門
    dr = dr_am = None
    try:
        from atmospheric_drag import drag_residual, load_space_weather
        _cols = ["epoch", "sma_km"] + (["eccentricity"] if "eccentricity" in dd.columns else [])
        _dr = drag_residual(dd[_cols], load_space_weather()).set_index("epoch")
        dr = _dr["drag_resid_da"]
        dr_am = dr.abs().rolling("7D").max()
    except Exception:
        pass

    idxs = np.arange(1, len(dd))
    if len(idxs) > 220:                                   # 過多時等距抽樣控制計算量
        idxs = np.unique(np.linspace(1, len(dd) - 1, 220).astype(int))

    sma = dd["sma_km"].to_numpy(float)
    epochs, probs, das, thrs, drs = [], [], [], [], []
    for i in idxs:
        t_from = dd["epoch"].iloc[i]
        lo = t_from - pd.Timedelta(days=7)
        window = win[(win["date_tag"] >= lo) & (win["date_tag"] <= t_from)]
        fv = btd.compute_features(window, t_from,
                                  float(f107.get(t_from.strftime("%Y-%m-%d"), np.nan)))
        if not fv:
            continue
        for key, col in [("cusum", "cusum_stat"), ("bocpd", "bocpd_cp_prob"),
                         ("ssa", "ssa_resid_z")]:
            fv[col] = float(sr[key]["scores"][i])
        # 注入 NRLMSIS 阻力殘差特徵
        dr_i = float(dr.loc[dr.index <= t_from].iloc[-1]) if dr is not None and (dr.index <= t_from).any() else np.nan
        dram_i = float(dr_am.loc[dr_am.index <= t_from].iloc[-1]) if dr_am is not None and (dr_am.index <= t_from).any() else np.nan
        fv["drag_resid_da"] = dr_i
        fv["drag_resid_absmax_7d"] = dram_i
        X = pd.DataFrame([{k: fv.get(k, np.nan) for k in feats}])
        epochs.append(t_from)
        probs.append(float(model.predict_proba(X)[:, 1][0]))
        das.append(float(sma[i] - sma[i - 1]))
        thrs.append(float(ms.DEFAULT_P2(np.array([sma[i] - R_E]))[0]))
        drs.append(dr_i)
    if not epochs:
        return None
    out = pd.DataFrame({"epoch": epochs, "prob": probs, "da_km": das,
                        "p2_thr": thrs, "drag_resid_da": drs})
    # 物理閘門（升級版）：ML 判機動須 (模型機率≥門檻) 且 (NRLMSIS 扣阻力後 |殘差Δa| 夠大)。
    # 用物理阻力殘差取代原始 |Δa|：正確扣除大氣阻力(含 F10.7/Ap)，純衰減/太陽極大期不誤報。
    # NRLMSIS 不可得時回退為高度自適應 |Δa| 閾值。
    if out["drag_resid_da"].notna().any():
        out["flag"] = (out["prob"] >= float(thr)) & (out["drag_resid_da"].abs() > 0.30)
    else:
        out["flag"] = (out["prob"] >= float(thr)) & (out["da_km"].abs() > out["p2_thr"])
    return out, float(thr)


@st.cache_data(show_spinner=False)
def compute_model2_detection(norad: int, d0, d1):
    """Model 2（regime-agnostic 無監督）：NRLMSIS 物理殘差 + Isolation Forest 異常偵測。
    通用任何軌道類別、對純衰減零誤報。回傳 df[epoch, z_drag, anomaly]。"""
    import joblib
    mpath = Path("Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl")
    if not mpath.exists():
        return None
    try:
        import ml_model2_anomaly as m2
        from atmospheric_drag import load_space_weather
    except Exception:
        return None
    bundle = joblib.load(mpath)
    iso, ch = bundle["model"], bundle["channels"]
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    r = m2.physical_residuals(
        dd[["epoch", "sma_km", "inclination_deg", "eccentricity", "raan_deg"]],
        load_space_weather())
    if r.empty:
        return None
    X = np.clip(np.nan_to_num(r[ch].to_numpy()), -200, 200)
    r = r.assign(anomaly=(iso.predict(X) == -1))
    return r


@st.cache_data(show_spinner=False)
def compute_nrlmsis_maneuvers(norad: int, d0, d1, thr: float = 0.30):
    """NRLMSIS 阻力殘差機動（regime-agnostic 物理主判）：扣大氣阻力後 |Δa 殘差|>thr。
    回傳 df[epoch, drag_resid_da, is_maneuver]。通用任何軌道、對純衰減零誤報。"""
    try:
        from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay
    except Exception:
        return None
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 5:
        return None
    cols = ["epoch", "sma_km"] + (["eccentricity"] if "eccentricity" in dd.columns else [])
    r = drag_residual(dd[cols], load_space_weather())
    if r.empty:
        return None
    r = r[["epoch", "drag_resid_da"]].copy()
    # 再入守門：自然再入衰減無法用準secular模型消除 → 直接判機動=0
    reentry = is_reentry_decay(dd)
    r["is_maneuver"] = False if reentry else (r["drag_resid_da"].abs() > thr)
    r.attrs["reentry"] = reentry
    return r


@st.cache_resource(show_spinner=False)
def _load_fusion():
    import joblib
    p = Path("models_fusion/fusion_scorer.pkl")
    return joblib.load(p) if p.exists() else None


@st.cache_data(show_spinner=False)
def compute_fusion_detection(norad: int, d0, d1):
    """連續融合評分器：5 通道(CUSUM/BOCPD/SSA/MAD+NRLMSIS drag)→ 每 epoch ±24h 窗
    特徵(max/mean/p90)→ HistGBM 融合機動機率。回傳 df[epoch, fusion] 與屬性 thr。"""
    fs = _load_fusion()
    if fs is None:
        return None
    dd = load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    r = sd.run_all(dd["sma_km"].to_numpy(float))
    drag = np.zeros(len(dd))
    try:
        from atmospheric_drag import drag_residual, load_space_weather
        cols = ["epoch", "sma_km"] + (["eccentricity"] if "eccentricity" in dd.columns else [])
        dr = drag_residual(dd[cols], load_space_weather())
        if not dr.empty:
            dmap = dict(zip(pd.to_datetime(dr["epoch"], utc=True), dr["drag_resid_da"].abs()))
            drag = np.array([dmap.get(e, 0.0) for e in dd["epoch"]], float)
    except Exception:
        pass
    ch = np.nan_to_num(np.column_stack([
        np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
        np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]), drag / 0.10]))
    t = dd["epoch"].reset_index(drop=True)
    feats = []
    for i in range(len(dd)):
        m = ((t - t.iloc[i]).abs() <= pd.Timedelta(hours=24)).to_numpy()
        sub = ch[m]
        row = []
        for j in range(5):
            col = sub[:, j]
            row += [col.max(), col.mean(), float(np.percentile(col, 90))]
        feats.append(row)
    proba = fs["clf"].predict_proba(np.array(feats))[:, 1]
    out = pd.DataFrame({"epoch": dd["epoch"], "fusion": proba})
    out.attrs["thr"] = float(fs["thr"])
    return out


def is_starlink_domain(sat_name: str) -> bool:
    """Model 1（監督式）僅在 Starlink 訓練 → 只有 Starlink 屬其分布內。"""
    return bool(sat_name) and sat_name.upper().startswith("STARLINK")


def resolve_query(q: str, cat: pd.DataFrame, names: dict) -> pd.DataFrame:
    """支援 NORAD、名稱、wildcard（* ?）。回傳符合的 (norad_id, name) 列。"""
    q = q.strip()
    if not q:
        return cat.head(0)
    cat = cat.copy()
    cat["disp"] = cat["norad_id"].map(names).fillna(cat["name"]).fillna("")
    if q.isdigit():
        return cat[cat["norad_id"] == int(q)]
    if any(c in q for c in "*?"):
        import fnmatch
        pat = q.upper()
        mask = cat["disp"].str.upper().apply(lambda s: fnmatch.fnmatch(s, pat))
        return cat[mask]
    return cat[cat["disp"].str.contains(q, case=False, na=False)]


# ── plotting ──────────────────────────────────────────────────────────────────

def _time_colorscale(n: int = 16):
    """時間 → HSL 色環（hue 0→330、S85% L55%），對應參考頁 orbit.js 之 timeColor。"""
    out = []
    for k in range(n):
        p = k / (n - 1)
        r, g, b = colorsys.hls_to_rgb((p * 330) / 360.0, 0.55, 0.85)
        out.append([p, f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"])
    return out


TIME_SCALE = _time_colorscale()


def plot_elements_and_deltas(df: pd.DataFrame, tr: pd.DataFrame, combined: np.ndarray,
                             nrlmsis_mv: pd.DataFrame | None = None,
                             show_altitude: bool = False):
    """① a/i/e/RAAN 連續時序（左）+ Δ 差值（中）+ 極座標時間視圖（右），共 4 列。
    第三欄（仿 orbit.js Spiral Polar）：
      列1 半長軸「圓形時間圖」(0°=起始於上方、順時針至 360°=結束，r=正規化 SMA)；
      列2/3/4 傾角/RAAN/ARGP「Spiral Polar」(角度=要素值、半徑=時間螺旋 r=0.18+0.82·t、色=時間)。
    nrlmsis_mv：NRLMSIS 主判機動（欄 epoch）→ 於 a 曲線與 Δa 圖標記，使根數圖與主判一致。
    show_altitude：左上第一格改顯示「距離地表高度 (km) = a − R⊕」；Δa 為差值、扣常數不變，不受影響。"""
    a_off = R_E if show_altitude else 0.0
    a_title = "距離地表高度 (km)" if show_altitude else "半長軸 a (km)"
    fig = make_subplots(
        rows=4, cols=3, shared_xaxes=True, horizontal_spacing=0.06, vertical_spacing=0.055,
        column_widths=[0.37, 0.37, 0.26],
        specs=[[{"type": "xy"}, {"type": "xy"}, {"type": "polar"}] for _ in range(4)],
        subplot_titles=(
            a_title, "Δa (km)", "SMA 圓形時間圖",
            "傾角 i (deg)", "Δi (deg)", "傾角 Spiral",
            "離心率 e", "Δe", "RAAN Spiral",
            "升交點赤經 RAAN (deg)", "ΔRAAN 殘差 (deg)", "ARGP Spiral"))
    ep, tep = df["epoch"], tr["epoch"]
    left = [("sma_km", 1), ("inclination_deg", 2), ("eccentricity", 3), ("raan_deg", 4)]
    for col, r in left:
        y = df[col] - a_off if col == "sma_km" else df[col]
        fig.add_trace(go.Scatter(x=ep, y=y, mode="lines", line=dict(color="#0072B2", width=1.3),
                                 showlegend=False), row=r, col=1)
    right = [("da_km", 1), ("di_deg", 2), ("de", 3), ("draan_res_deg", 4)]
    for col, r in right:
        fig.add_trace(go.Scatter(x=tep, y=tr[col], mode="lines", line=dict(color="#888", width=1),
                                 showlegend=False), row=r, col=2)
    # 合併偵測（P1–P6）標記於 Δa
    if combined.any():
        cm = tr[combined]
        fig.add_trace(go.Scatter(x=cm["epoch"], y=cm["da_km"], mode="markers",
                                 marker=dict(color="#D55E00", size=7, symbol="x"),
                                 name="P1–P6 合併偵測"), row=1, col=2)
    # NRLMSIS 主判機動：於 a 曲線（上）與 Δa 圖（上）皆標記（綠星），與主判一致
    if nrlmsis_mv is not None and len(nrlmsis_mv):
        mep = pd.to_datetime(nrlmsis_mv["epoch"], utc=True)
        a_src = df.drop_duplicates("epoch").set_index("epoch")["sma_km"].sort_index()
        da_src = tr.drop_duplicates("epoch").set_index("epoch")["da_km"].sort_index()
        a_at = a_src.reindex(mep, method="nearest").to_numpy() - a_off
        da_at = da_src.reindex(mep, method="nearest").to_numpy()
        fig.add_trace(go.Scatter(x=mep, y=a_at, mode="markers",
                                 marker=dict(color="#009E73", size=9, symbol="star",
                                             line=dict(color="white", width=0.5)),
                                 name="NRLMSIS 主判機動"), row=1, col=1)
        fig.add_trace(go.Scatter(x=mep, y=da_at, mode="markers",
                                 marker=dict(color="#009E73", size=9, symbol="star",
                                             line=dict(color="white", width=0.5)),
                                 showlegend=False), row=1, col=2)
    # ── 第三欄：極座標時間視圖 ────────────────────────────────────────────────
    def _spiral(series: str, row: int):
        v = df[series].to_numpy(float)
        e = df["epoch"].to_numpy()
        m = np.isfinite(v)
        v, e = v[m], e[m]
        n = len(v)
        if n == 0:
            return
        t = np.linspace(0, 1, n) if n > 1 else np.array([0.0])
        r_n = 0.18 + 0.82 * t                     # 時間螺旋（內→外）
        theta = np.mod(v, 360.0)                   # 角度 = 要素值
        htxt = [f"{pd.Timestamp(dd).strftime('%Y-%m-%d')} · {vv:.4f}°"
                for dd, vv in zip(e, v)]
        fig.add_trace(go.Scatterpolar(
            r=r_n, theta=theta, mode="markers",
            marker=dict(size=4, color=t, colorscale=TIME_SCALE, cmin=0, cmax=1,
                        showscale=False),
            hovertext=htxt, hoverinfo="text", showlegend=False), row=row, col=3)

    def _sma_circle(row: int):
        s = df["sma_km"].to_numpy(float)
        e = df["epoch"].to_numpy()
        m = np.isfinite(s)
        s, e = s[m], e[m]
        n = len(s)
        if n == 0:
            return
        mn, mx = float(s.min()), float(s.max())
        rg = mx - mn
        t = np.linspace(0, 1, n) if n > 1 else np.array([0.0])
        r_n = (s - mn) / rg if rg > 0 else np.full(n, 0.5)
        theta = t * 360.0                          # 0°=起始（上方）順時針→360°=結束
        htxt = [f"{pd.Timestamp(dd).strftime('%Y-%m-%d')} · SMA {ss:.3f} km"
                f"（min+{ss - mn:.3f}）" for dd, ss in zip(e, s)]
        fig.add_trace(go.Scatterpolar(
            r=r_n, theta=theta, mode="lines+markers",
            line=dict(color="rgba(150,150,150,0.35)", width=1),
            marker=dict(size=4, color=t, colorscale=TIME_SCALE, cmin=0, cmax=1,
                        showscale=False),
            hovertext=htxt, hoverinfo="text", showlegend=False), row=row, col=3)

    _sma_circle(1)
    _spiral("inclination_deg", 2)
    _spiral("raan_deg", 3)
    _spiral("argp_deg", 4)

    _rad = dict(showticklabels=False, gridcolor="#e5e5e5", linecolor="#e5e5e5",
                range=[0, 1.04])
    _ang = dict(gridcolor="#e5e5e5", linecolor="#e5e5e5", tickfont=dict(size=7),
                ticksuffix="°", nticks=8)
    _polar_spiral = dict(radialaxis=_rad, angularaxis=_ang, bgcolor="rgba(0,0,0,0)")
    _polar_sma = dict(
        radialaxis=dict(showticklabels=False, gridcolor="#e5e5e5",
                        linecolor="#e5e5e5", range=[0, 1.06]),
        angularaxis=dict(rotation=90, direction="clockwise", gridcolor="#e5e5e5",
                         linecolor="#e5e5e5", tickfont=dict(size=7), ticksuffix="°",
                         nticks=8),
        bgcolor="rgba(0,0,0,0)")
    # polar(列1)=SMA 圓形；polar2/3/4(列2-4)=Spiral
    fig.update_layout(polar=_polar_sma, polar2=_polar_spiral,
                      polar3=_polar_spiral, polar4=_polar_spiral)
    # 下縮各極座標 domain，讓子圖標題與頂端角度刻度留白、不再交疊
    for _pol in ("polar", "polar2", "polar3", "polar4"):
        _d = fig.layout[_pol].domain
        fig.layout[_pol].domain = dict(x=tuple(_d.x),
                                       y=(_d.y[0], _d.y[1] - 0.028))

    fig.update_layout(height=1020, margin=dict(l=40, r=20, t=52, b=30),
                      legend=dict(orientation="h", y=1.05))
    fig.update_annotations(font_size=12)          # 收斂 12 格 subplot 標題字級
    return fig


def bootstrap_ci(values: np.ndarray, stat=np.mean, n=2000, alpha=0.05, seed=0):
    values = np.asarray(values, float)
    values = values[~np.isnan(values)]
    if len(values) < 2:
        m = float(stat(values)) if len(values) else float("nan")
        return m, m, m
    rng = np.random.default_rng(seed)
    boot = [stat(rng.choice(values, len(values), replace=True)) for _ in range(n)]
    return float(stat(values)), float(np.percentile(boot, 100 * alpha / 2)), \
        float(np.percentile(boot, 100 * (1 - alpha / 2)))


# ── SSA-RAG 整合（自 maneuver_app.py 移植）────────────────────────────────────
RAG_DEFAULT_URL = os.environ.get("SSA_RAG_URL", "http://127.0.0.1:8000")
TLE_GAP_SUPPRESS_H = 48.0


@st.cache_data(ttl=60, show_spinner=False)
def _rag_health_cached(base_url: str) -> bool:
    try:
        from ssa_rag_client import SSARAGClient
    except ImportError:
        return False
    try:
        return SSARAGClient(base_url=base_url).health()
    except Exception:
        return False


@st.cache_data(ttl=3600, show_spinner=False)
def _rag_ask_cached(base_url: str, question: str, topic: str | None) -> dict:
    """同一描述文字只查詢一次（快取 1 小時），避免 Streamlit rerun 重複打 RAG。"""
    from ssa_rag_client import SSARAGClient
    client = SSARAGClient(base_url=base_url, timeout=120.0)
    result = client.ask(question, topic=topic, client_id="maneuver_app_july")
    return {"answer": result.answer, "confidence": result.confidence,
            "sources": result.sources}


def build_tle_maneuver_narrative(satellite_id, alt_km_avg, start_date: str,
                                 end_date: str, event_df: pd.DataFrame) -> str:
    """LEO/MEO TLE 自適應偵測結果 → 自然語言描述（供 SSA-RAG 解說）。"""
    alt_txt = f"平均軌道高度約 {alt_km_avg:.0f} km" if alt_km_avg is not None else "軌道高度未知"
    n_events = 0 if event_df is None or event_df.empty else len(event_df)
    lines = [
        f"衛星 NORAD {satellite_id}（{alt_txt}）在 {start_date} 至 {end_date} 期間，"
        f"以 TLE 半長軸（SMA）跳變法（P1–P6 高度自適應）進行機動偵測，"
        f"共偵測到 {n_events} 次疑似機動事件。"
    ]
    if n_events:
        ev_lines = []
        _is_raise = event_df["sma_direction"].astype(str).to_numpy() == "raise"
        _absd = event_df["sma_delta"].abs().to_numpy(float)
        for _, ev in event_df.head(10).iterrows():
            direction = "抬升" if str(ev.get("sma_direction", "")) == "raise" else "降低"
            ev_lines.append(
                f"- {pd.Timestamp(ev['epoch']).strftime('%Y-%m-%d')}："
                f"半長軸{direction}，|Δa| = {float(ev['sma_delta']):.4f} km")
        if n_events > 10:
            ev_lines.append(f"-（其餘 {n_events - 10} 次事件省略）")
        lines.append("事件清單：\n" + "\n".join(ev_lines))
        n_raise = int(_is_raise.sum())
        n_lower = int((~_is_raise).sum())
        net_signed = float((_absd * np.where(_is_raise, 1.0, -1.0)).sum())
        abs_sum = float(_absd.sum())
        net_dir = "淨抬升" if net_signed > 0 else ("淨降低" if net_signed < 0 else "淨值近零")
        lines.append(
            f"事件方向統計：抬升 {n_raise} 次、降低 {n_lower} 次。"
            f"帶正負號的淨半長軸變化 Δa_net = {net_signed:+.4f} km（{net_dir}）；"
            f"各事件 |Δa| 絕對值加總 = {abs_sum:.3f} km——此值僅代表機動活動量級，"
            "恒為正、不代表方向。"
            f"（註：上列統計與 Δa_net 均由偵測系統就「全部 {n_events} 次事件」計算所得，"
            "為本題給定之輸入事實；上方事件清單僅為可讀性節錄前 10 筆，"
            "故 Δa_net 無法、也不需由清單自行推算，請直接採用。）")
        lines.append(
            "請根據以上偵測結果解說：這種半長軸跳變模式最可能對應哪種機動類型"
            "（軌道維持、軌道抬升、避碰或離軌）？機動後 TLE 失效對 conjunction "
            "screening 有什麼影響？（判斷機動方向請「務必以帶正負號的 Δa_net 為準」——"
            "Δa_net 為正才可能是軌道抬升、為負屬軌道降低／離軌，切勿把絕對值加總當成淨值，"
            "也不要只憑檢索到的文件主題判斷方向。）")
    else:
        lines.append(
            "請解說：此期間未偵測到明顯機動的可能原因有哪些？"
            "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return "\n".join(lines)


def build_ml_maneuver_narrative(satellite_id, p_maneuver: float, lgbm_feat: dict,
                                start_date: str, end_date: str,
                                alert: bool | None = None) -> str:
    """LightGBM／融合偵測結果 → 自然語言描述（供 SSA-RAG 解說）。"""
    if alert is None:
        alert = p_maneuver >= 0.5
    net_da = float(lgbm_feat.get("net_da_km", 0))
    if net_da > 0:
        direction_txt = "半長軸上升（正值，方向上屬於軌道抬升類）"
    elif net_da < 0:
        direction_txt = "半長軸下降（負值，方向上屬於軌道降低／離軌／大氣阻力衰減類，並非軌道抬升）"
    else:
        direction_txt = "半長軸無明顯淨變化"
    lines = [
        f"機動偵測模型對衛星 NORAD {satellite_id}"
        f"（軌道高度約 {float(lgbm_feat.get('alt_km', float('nan'))):.0f} km）"
        f"在 {start_date} 至 {end_date} 的 TLE 資料推論，"
        f"機動機率 p_maneuver = {p_maneuver:.3f}，"
        f"判定為「{'偵測到機動' if alert else '無明顯機動'}」。",
        f"關鍵特徵：累積半長軸變化 {net_da:+.2f} km（{direction_txt}）、"
        f"單筆最大 |Δa| {float(lgbm_feat.get('max_da_km', 0)):.2f} km、"
        f"異常旗標率 {float(lgbm_feat.get('flag_rate', 0)):.0%}、"
        f"估算淨 Δv 約 {float(lgbm_feat.get('dv_net_ms', 0)):.2f} m/s。",
    ]
    if lgbm_feat.get("da_monotonic_decay") or lgbm_feat.get("monotone_decay"):
        lines.append("此觀測窗口帶有單調衰減特徵（半長軸持續小幅下降、無大跳變），"
                     "較可能為大氣阻力自然衰減而非推進機動。")
    lines.append(
        "請解說此偵測結果的物理意義：這樣的半長軸變化與 Δv 量級對應哪種機動行為？"
        "分析時如何區分大氣阻力衰減與真實機動？"
        "（請以上方標註的方向判讀為準，不要單純依照檢索到的文件主題判斷方向。）")
    return "\n".join(lines)


def render_rag_auto_explain(narrative: str, base_url: str = RAG_DEFAULT_URL,
                            topic: str = "maneuver") -> None:
    """將偵測結果的自然語言描述自動送入 SSA-RAG，顯示解說。服務離線只留一行提示。"""
    if not _rag_health_cached(base_url):
        st.caption(f"⚠️ SSA-RAG 服務未上線（{base_url}），略過自動解說。"
                   "啟動方式：於 F:\\GitHub\\SSA-RAG 目錄執行 `uvicorn app.main:app`。")
        return
    st.markdown("#### 🤖 SSA-RAG 自動解說")
    with st.expander("查看送出的偵測結果描述"):
        st.text(narrative)
    with st.spinner("SSA-RAG 解說產生中…（首次呼叫需載入模型，約 10–30 秒）"):
        try:
            res = _rag_ask_cached(base_url, narrative, topic)
        except Exception as e:
            st.warning(f"SSA-RAG 查詢失敗：{e}")
            return
    st.info(res["answer"])
    conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(res["confidence"], "⚪")
    st.caption(f"{conf_color} 信心度：{res['confidence']}")
    if res["sources"]:
        with st.expander(f"📄 參考來源（{len(res['sources'])} 筆）"):
            for s in res["sources"]:
                st.caption(f"**{s.get('file_name', '未知')}**"
                           f"（chunk {s.get('chunk_index', '?')}，"
                           f"score {float(s.get('score', 0)):.3f}）")


def render_ssa_rag_page(base_url: str = RAG_DEFAULT_URL) -> None:
    """SSA-RAG 知識庫互動問答（自訂問題）。"""
    import requests
    try:
        from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS, TOPICS
    except ImportError:
        st.error("找不到 ssa_rag_client.py，請確認檔案已複製到本專案目錄。")
        return
    if not _rag_health_cached(base_url):
        st.caption(f"⚠️ SSA-RAG 服務未上線（{base_url}）。"
                   "啟動：於 F:\\GitHub\\SSA-RAG 執行 `uvicorn app.main:app`。")
        return
    st.success(f"✅ SSA-RAG 服務正常（{base_url}）")
    client = SSARAGClient(base_url=base_url, timeout=120.0)
    col_topic, col_prompt = st.columns([1, 2])
    with col_topic:
        topic = st.selectbox("主題篩選", ["(全部)"] + TOPICS, key="ssa_topic_july")
    with col_prompt:
        prompts = SUGGESTED_PROMPTS.get(topic, [])
        prompt_choice = st.selectbox("範例問題（可略過，直接自訂輸入）",
                                     ["(自訂輸入)"] + prompts, key="ssa_prompt_choice_july")
    default_q = "" if prompt_choice == "(自訂輸入)" else prompt_choice
    question = st.text_input("問題", value=default_q, key="ssa_question_july")
    if st.button("送出", type="primary", key="ssa_submit_july") and question:
        with st.spinner("查詢中… 首次呼叫需載入模型，約 10–30 秒"):
            try:
                result = client.ask(question, topic=None if topic == "(全部)" else topic,
                                    client_id="maneuver_app_july")
            except Exception as e:
                st.error(f"查詢失敗：{e}")
                return
        st.markdown("### 回答")
        st.write(result.answer)
        conf_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")
        st.caption(f"{conf_color} 信心度：{result.confidence}")
        if result.insufficient:
            st.warning("資料不足，無法根據現有文件確認此問題。")
        elif result.sources:
            with st.expander(f"📄 來源文件（{len(result.sources)} 筆）"):
                for s in result.sources:
                    st.caption(f"**{s.get('file_name', '未知')}**"
                               f"（chunk {s.get('chunk_index', '?')}，"
                               f"score {float(s.get('score', 0)):.3f}）")


def _render_dialogue_messages(n_show: int = 12) -> None:
    from app_dialogue_client import DialogueClient, DIALOGUE_END, DIALOGUE_ECHO
    records = DialogueClient().read_all()
    if not records:
        st.caption("（信箱尚無訊息）")
        return
    if len(records) > n_show:
        st.caption(f"（僅顯示最近 {n_show} 則，共 {len(records)} 則）")
    for rec in records[-n_show:]:
        ts = rec.get("timestamp", "")[11:19]
        is_client = rec.get("sender") == "client"
        who = "🛰️ client" if is_client else "🖥️ server"
        msg = str(rec.get("message", ""))
        if msg.strip() == DIALOGUE_ECHO:
            st.markdown(f"<small>{ts} <b>{who}</b>：✓ <code>#Echo#</code>（送達確認）</small>",
                        unsafe_allow_html=True)
        elif msg.strip() == DIALOGUE_END:
            st.markdown(f"<small>{ts} <b>{who}</b>：🔚 <code>#Over#</code>（對話結束）</small>",
                        unsafe_allow_html=True)
        else:
            color = "#8ecae6" if is_client else "#ffb703"
            st.markdown(f"<small><b style='color:{color}'>{who}</b> "
                        f"<span style='opacity:.6'>{ts}</span><br>{msg}</small>",
                        unsafe_allow_html=True)


def render_dialogue_panel() -> None:
    """側邊欄對話面板：與 SSA-RAG Server（scripts/ask.py --chat-listen）互傳訊息。"""
    with st.expander("💬 App 對話（↔ SSA-RAG Server）"):
        try:
            from app_dialogue_client import DialogueClient
        except ImportError:
            st.caption("找不到 app_dialogue_client.py，無法使用對話功能。")
            return
        _render_dialogue_messages()
        st.button("🔄 重新整理", key="dlg_refresh_july")
        with st.form("dlg_form_july", clear_on_submit=True):
            msg = st.text_input("訊息", key="dlg_msg_july",
                                placeholder="例：可以傳送 SSA-RAG 測試了嗎?")
            c_send, c_over = st.columns(2)
            do_send = c_send.form_submit_button("送出", type="primary", use_container_width=True)
            do_over = c_over.form_submit_button("#Over#", use_container_width=True)
        if do_send and msg.strip():
            DialogueClient().send(msg.strip())
            st.rerun()
        if do_over:
            DialogueClient().end()
            st.rerun()


# ── main ──────────────────────────────────────────────────────────────────────

st.title("🛰️ 機動偵測儀表板（September 2026版）")
st.caption("整合 P1–P6 規則、CUSUM/BOCPD/SSA 統計層、MEME-tuned ML forecast 模型")

cat = load_catalog()
names = load_registry_names()

with st.sidebar:
    st.header("查詢")
    query = st.text_input("NORAD ID / 名稱 / wildcard", value="STARLINK-30273",
                          help="例：57681、STARLINK-30273、STARLINK-30* 、SL-1?")
    st.header("P2 高度自適應閾值（拋物線左側）")
    p2_vertex = st.slider("P2 vertex 高度 (km)", 400.0, 1000.0, 700.0, 10.0)
    p2_floor = st.slider("P2 floor 閾值 (km)", 0.1, 1.0, 0.4, 0.05)
    p2_refy = st.slider("P2 @400km 閾值 (km)", 0.5, 4.0, 2.0, 0.1)
    st.header("P5 F10.7 自適應倍率（拋物線）")
    p5_vertex = st.slider("P5 vertex F10.7 (sfu)", 50.0, 120.0, 70.0, 5.0)
    p5_refy = st.slider("P5 @200sfu 倍率", 1.0, 3.0, 1.6, 0.1)

    st.header("🤖 SSA-RAG 知識庫")
    rag_url = st.text_input("SSA-RAG 服務位址", value=RAG_DEFAULT_URL, key="rag_url_july")
    rag_auto = st.checkbox("執行後自動送 RAG 解說（③ 偵測結果）", value=True,
                           key="rag_auto_july",
                           help="將 P1–P6／ML 偵測結果轉自然語言自動送 SSA-RAG；服務離線僅留提示")
    render_dialogue_panel()

p2 = ms.ParabolaParams(vertex=p2_vertex, floor=p2_floor, ref_x=400.0, ref_y=p2_refy)
p5 = ms.ParabolaParams(vertex=p5_vertex, floor=1.0, ref_x=200.0, ref_y=p5_refy)

hits = resolve_query(query, cat, names)
if hits.empty:
    st.warning("查無符合的衛星。")
    st.stop()

hits = hits.copy()
hits["disp"] = hits["norad_id"].map(names).fillna(hits["name"])
if len(hits) > 1:
    st.info(f"符合 {len(hits)} 顆（wildcard）。下方逐顆分析可選擇；艦隊統計見底部。")
    pick = st.selectbox("選擇衛星", hits["disp"] + "  (" + hits["norad_id"].astype(str) + ")")
    norad = int(pick.split("(")[-1].rstrip(")"))
else:
    norad = int(hits["norad_id"].iloc[0])
sat_name = names.get(norad, hits["disp"].iloc[0] if len(hits) else str(norad))

df = load_tle(norad)
if df.empty or len(df) < 3:
    st.error("此衛星 TLE 資料不足。")
    st.stop()

# 日期範圍
dmin, dmax = df["epoch"].min().date(), df["epoch"].max().date()
c1, c2 = st.columns(2)
d0 = c1.date_input("起始", dmin, min_value=dmin, max_value=dmax)
d1 = c2.date_input("結束", dmax, min_value=dmin, max_value=dmax)
df = df[(df["epoch"].dt.date >= d0) & (df["epoch"].dt.date <= d1)].reset_index(drop=True)
if len(df) < 3:
    st.warning("此範圍 TLE 少於 3 筆。")
    st.stop()

a0 = float(df["sma_km"].iloc[0])
i0 = float(df["inclination_deg"].iloc[0])
orbit_class = ms.classify_orbit(a0, float(df["eccentricity"].iloc[0]), i0)
fam = ms.inc_family(i0)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("衛星", sat_name)
m2.metric("NORAD", norad)
m3.metric("軌道類別", orbit_class)
m4.metric("傾角族群", fam)
m5.metric("TLE 筆數", len(df))

f107 = load_f107()
tr = ms.build_transitions(df, f107)
res = ms.apply_strategies(tr, orbit_class, p2=p2, p5=p5)
combined = res["combined"] if len(tr) else np.array([], bool)


# ── 🎯 統一偵測摘要（orbit_anomaly_detector，依軌域自動路由）──────────────────
@st.cache_resource(show_spinner=False)
def _get_oad():
    import orbit_anomaly_detector as _oad
    return _oad.OrbitAnomalyDetector(DB_PATH)


@st.cache_data(show_spinner=False)
def _unified_detect(nid: int):
    try:
        return _get_oad().detect(int(nid))
    except Exception as _e:
        return {"status": "error", "err": str(_e)}


with st.container(border=True):
    st.markdown("#### 🎯 統一偵測摘要（orbit_anomaly_detector · 依軌域自動路由）")
    with st.spinner("統一偵測中…"):
        ur = _unified_detect(norad)
    if ur.get("status") == "ok":
        uc = st.columns(4)
        uc[0].metric("軌域 · 域", f"{ur['orbit_class']} · {ur['domain']}")
        uc[1].metric("路由主判", ur["routed_primary"].split("(")[0].split("+")[0].strip())
        uc[2].metric("融合旗標", ur["fusion_flags"] if ur["fusion_flags"] is not None else "—",
                     f"max_p={ur['fusion_max_prob']}" if ur["fusion_max_prob"] is not None else None)
        uc[3].metric("Model 2 異常", ur["model2_anomalies"] if ur["model2_anomalies"] is not None else "—")
        if ur["reentry"]:
            st.error(f"⚠️ 偵測到**自然再入衰減** → 判定「{ur['verdict']}」（機動=0，不套用機動模型）")
        else:
            st.info(f"路由至 **{ur['routed_primary']}** — {ur['verdict']}")
        st.caption(f"Layer 2 統計事件：{ur['layer2_statistical_events']}。"
                   "Starlink LEO→Model 1+融合；非 Starlink/衰減軌→Model 2+NRLMSIS；再入→守門。")
    else:
        st.caption(f"統一偵測不可得：{ur.get('err', ur.get('status'))}")

# ── ① 根數與差值 ─────────────────────────────────────────────────────────────
st.subheader("① 軌道根數連續變化與差值")
if len(tr):
    _c_ttl, _c_tog = st.columns([3, 1.1])
    with _c_tog:
        _y_mode = st.radio(
            "左上 Y 軸顯示", ["半長軸 a (km)", "距離地表高度 (km)"],
            horizontal=True, key="elem_a_ymode",
            help="切換左上第一格：半長軸 a ↔ 距離地表高度（a − R⊕，R⊕=6378.137 km）。"
                 "註：Streamlit 無法擷取「滑鼠點選 Y 軸」事件，故以此切換鈕達成等效功能；"
                 "Δa 為差值、扣常數不變，不受影響。")
    _show_alt = (_y_mode == "距離地表高度 (km)")
    _nm1 = compute_nrlmsis_maneuvers(norad, d0, d1)
    _mv = _nm1[_nm1["is_maneuver"]] if _nm1 is not None else None
    st.plotly_chart(plot_elements_and_deltas(df, tr, combined, nrlmsis_mv=_mv,
                                             show_altitude=_show_alt),
                    width="stretch")
    if _mv is not None:
        st.caption(f"🟢 綠星 = NRLMSIS 主判機動（扣大氣阻力後 |Δa 殘差|>0.3km），共 {len(_mv)} 次；"
                   "紅叉 = P1–P6 合併偵測。")

# ── ② P1–P6 ─────────────────────────────────────────────────────────────────
st.subheader("② P1–P6 策略：個別 vs 合併")
if len(tr):
    rows = [{"策略": k, "旗標/抑制數": int(v.sum()),
             "類型": "抑制" if "suppress" in k else "偵測"}
            for k, v in res["per_strategy"].items()]
    rows.append({"策略": "★ 合併", "旗標/抑制數": int(combined.sum()), "類型": "最終"})
    cL, cR = st.columns([1, 1.4])
    cL.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with cR:
        for k, note in res["notes"].items():
            st.caption(f"**{k}** — {note}")
    # 閾值曲線預覽
    with st.expander("P2 / P5 拋物線曲線預覽"):
        gx = np.linspace(300, 1000, 100)
        fx = np.linspace(60, 260, 100)
        fig2 = make_subplots(rows=1, cols=2, subplot_titles=("P2：高度→Δa 閾值 (km)",
                                                             "P5：F10.7→倍率"))
        fig2.add_trace(go.Scatter(x=gx, y=p2(gx), line=dict(color="#0072B2")), row=1, col=1)
        fig2.add_trace(go.Scatter(x=fx, y=p5(fx), line=dict(color="#E69F00")), row=1, col=2)
        fig2.update_layout(height=280, showlegend=False, margin=dict(t=30, b=20))
        st.plotly_chart(fig2, width="stretch")

# ── ③ 統計層 + ML ────────────────────────────────────────────────────────────
st.subheader("③ 統計偵測層（CUSUM/BOCPD/SSA）＋ ML 偵測/預測")

# ── 自動路由：Starlink → Model 1 主判；非 Starlink → Model 2 / NRLMSIS 殘差 ──
_in_domain = is_starlink_domain(sat_name)
if _in_domain:
    st.success(f"🛰️ **{sat_name} 屬 Starlink（Model 1 分布內）→ 主判：Model 1（監督式）**，"
               "Model 2 / NRLMSIS 殘差供交叉驗證。")
else:
    st.warning(f"🌐 **{sat_name} 非 Starlink（Model 1 分布外／OOD）→ 主判：Model 2 + NRLMSIS 阻力殘差**"
               "（regime-agnostic，通用任何軌道）。Model 1 機率在此僅供參考，可能失準。")

# 主判結果卡（依路由選擇的偵測器）
with st.container():
    _nm = compute_nrlmsis_maneuvers(norad, d0, d1)
    _m2 = compute_model2_detection(norad, d0, d1)
    if _nm is not None and _nm.attrs.get("reentry"):
        st.error("🔥 **偵測到自然再入/衰減軌道**（深近地點 + 單調快速衰減）→ "
                 "判定為大氣阻力自然衰減，**機動 = 0**。此類劇烈非線性衰減超出準secular阻力模型，"
                 "已由再入守門正確抑制誤報。")
    pc = st.columns(3)
    if _in_domain:
        _det = compute_ml_detection(norad, d0, d1)
        _n1 = int(_det[0]["flag"].sum()) if _det else 0
        pc[0].metric("主判：Model 1 偵測機動", _n1)
        pc[1].metric("NRLMSIS 殘差機動（交叉）", int(_nm["is_maneuver"].sum()) if _nm is not None else 0)
        pc[2].metric("Model 2 異常（交叉）", int(_m2["anomaly"].sum()) if _m2 is not None else 0)
    else:
        _nnm = int(_nm["is_maneuver"].sum()) if _nm is not None else 0
        pc[0].metric("主判：NRLMSIS 殘差機動", _nnm)
        pc[1].metric("Model 2 異常（佐證）", int(_m2["anomaly"].sum()) if _m2 is not None else 0)
        pc[2].metric("Model 1（參考，OOD）", "—")
        if _nm is not None and _nnm:
            mv = _nm[_nm["is_maneuver"]]
            st.caption("NRLMSIS 主判機動時刻： " + "， ".join(
                f"{pd.Timestamp(e).date()} (Δa殘差{v:+.2f}km)"
                for e, v in zip(mv["epoch"], mv["drag_resid_da"])))

if len(df) >= 8:
    sr = sd.run_all(df["sma_km"].to_numpy(float))
    fig3 = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                         subplot_titles=("CUSUM 累積統計", "BOCPD 短 run-length 機率",
                                         "SSA 重構殘差 z", "3σ MAD z"))
    xep = df["epoch"]
    for r_, key, col in [(1, "cusum", "#0072B2"), (2, "bocpd", "#E69F00"),
                         (3, "ssa", "#009E73"), (4, "mad3sig", "#D55E00")]:
        sc = sr[key]["scores"]
        fig3.add_trace(go.Scatter(x=xep, y=sc, line=dict(color=col, width=1.2),
                                  showlegend=False), row=r_, col=1)
        ev = sr[key]["events"]
        if len(ev):
            fig3.add_trace(go.Scatter(x=xep.iloc[ev], y=np.asarray(sc)[ev], mode="markers",
                                      marker=dict(color=col, size=6, symbol="circle-open"),
                                      showlegend=False), row=r_, col=1)
    fig3.update_layout(height=560, margin=dict(l=40, r=20, t=40, b=30))
    st.plotly_chart(fig3, width="stretch")
    cc = st.columns(4)
    for i, key in enumerate(("cusum", "bocpd", "ssa", "mad3sig")):
        cc[i].metric(key.upper() + " 事件數", int(len(sr[key]["events"])))

    # ML forecast（若模型與特徵可得）
    with st.expander("ML forecast（未來 1 天機動機率，models_meme_forecast）"):
        try:
            import joblib, json
            mdir = Path("Orbital_Maneuver_V2/models_meme_forecast")
            model = joblib.load(mdir / "lgbm_maneuver_v1.pkl")
            feats = json.loads((mdir / "feature_names.json").read_text(encoding="utf-8"))
            import build_training_dataset as btd
            t_from = df["epoch"].iloc[-1]
            win = df.rename(columns={"epoch": "date_tag"})
            fv = btd.compute_features(win, t_from,
                                      float(f107.get(t_from.strftime("%Y-%m-%d"), np.nan)))
            if fv:
                # Phase 2：接上統計層三變點統計量（取最新 TLE epoch 的值）
                for key, col in [("cusum", "cusum_stat"), ("bocpd", "bocpd_cp_prob"),
                                 ("ssa", "ssa_resid_z")]:
                    sc = sr[key]["scores"]
                    fv[col] = float(sc[-1]) if len(sc) else np.nan
                X = pd.DataFrame([{k: fv.get(k, np.nan) for k in feats}])
                p = float(model.predict_proba(X)[:, 1][0])
                st.metric("未來 1 天內出現 ≥5km 機動之機率", f"{p:.1%}")
                st.caption(f"模型特徵數 {len(feats)}（含 CUSUM/BOCPD/SSA 統計量）")
            else:
                st.caption("特徵不足，無法評分。")
        except Exception as e:
            st.caption(f"ML 模型/特徵不可得：{e}")

    # ML 機動偵測（每窗口，非預測）
    st.markdown("**ML 機動偵測（每窗口是否發生 ≥5km 機動 · models_meme，非預測）**")
    with st.spinner("ML 逐窗口偵測計算中…"):
        det = compute_ml_detection(norad, d0, d1)
    if det is not None:
        ddf, dthr = det
        prob = ddf["prob"].to_numpy(float)
        flg = ddf[ddf["flag"]]
        # 分布外偵測：整段最大 |Δa| 都低於高度自適應閾值 → 純阻力衰減/無機動
        pure_decay = bool((ddf["da_km"].abs() <= ddf["p2_thr"]).all())
        if pure_decay:
            st.warning("⚠️ 此衛星整段 |Δa| 皆低於高度自適應閾值 → 判定為**純大氣阻力衰減/無機動**。"
                       "模型原始機率偏高係『分布外』(此模型僅在 Starlink 機動衛星上訓練)，"
                       "已由物理閘門正確濾除為 0。")
        figd = go.Figure()
        figd.add_trace(go.Scatter(x=ddf["epoch"], y=prob, mode="lines",
                                  line=dict(color="#CC79A7", width=1.3), name="模型原始機率"))
        figd.add_hline(y=dthr, line=dict(color="#888", dash="dash"),
                       annotation_text=f"模型門檻 {dthr:.2f}")
        if len(flg):
            figd.add_trace(go.Scatter(x=flg["epoch"], y=flg["prob"], mode="markers",
                                      marker=dict(color="#D55E00", size=9, symbol="x"),
                                      name="ML 偵測機動（過物理閘門）"))
        figd.update_layout(height=280, yaxis_title="P(此窗發生機動)",
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.18))
        st.plotly_chart(figd, width="stretch")
        dc = st.columns(3)
        dc[0].metric("ML 偵測到的機動窗口", int(len(flg)))
        dc[1].metric("模型原始 P>門檻 窗口", int((prob >= dthr).sum()))
        dc[2].metric("最大 |Δa| (km)", f"{ddf['da_km'].abs().max():.3f}")
        st.caption("Model 1（監督式，Starlink 專用）。**物理閘門**：ML 旗標須同時 (模型機率≥門檻) 且 "
                   "(NRLMSIS 扣大氣阻力後 |殘差Δa|>0.3km)——正確扣除阻力(含 F10.7/Ap)，"
                   "純衰減/太陽極大期不誤報。")
    else:
        st.caption("ML 偵測不可得（TLE 不足或模型缺失）。")

    # ── Model 2：regime-agnostic 無監督（NRLMSIS 物理殘差 + Isolation Forest）──
    st.markdown("**Model 2：Regime-agnostic 異常偵測（無監督 · 通用任何軌道 · 對純衰減零誤報）**")
    with st.spinner("Model 2 物理殘差計算中…"):
        m2 = compute_model2_detection(norad, d0, d1)
    if m2 is not None:
        anom = m2[m2["anomaly"]]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=m2["epoch"], y=m2["z_drag"], mode="lines",
                                  line=dict(color="#009E73", width=1.2),
                                  name="NRLMSIS 阻力殘差 (σ)"))
        if len(anom):
            fig2.add_trace(go.Scatter(x=anom["epoch"], y=anom["z_drag"], mode="markers",
                                      marker=dict(color="#D55E00", size=8, symbol="diamond"),
                                      name="Model 2 異常(機動)"))
        fig2.update_layout(height=260, yaxis_title="阻力殘差 (物理σ=0.1km)",
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.2))
        st.plotly_chart(fig2, width="stretch")
        e1, e2 = st.columns(2)
        e1.metric("Model 2 偵測異常(機動)", int(len(anom)))
        e2.metric("最大阻力殘差 (σ)", f"{m2['z_drag'].abs().max():.1f}")
        st.caption("Model 2 用大氣密度模型(NRLMSIS)扣除阻力後的物理殘差，"
                   "不靠 alt/inc 族群先驗 → 通用 LEO/MEO/GEO/HEO 且不會把阻力衰減誤判為機動。")
    else:
        st.caption("Model 2 不可得（需 model2.pkl / pymsis / SW 資料）。")

    # ── 連續融合評分器（CUSUM/BOCPD/SSA/MAD + NRLMSIS drag → 單一機率）──────────
    st.markdown("**融合評分器：五通道 → 單一連續機動機率**（Layer 2 統計層融合，"
                "AUC 0.98／AP 0.96／large recall 0.97）")
    with st.spinner("融合評分計算中…"):
        fus = compute_fusion_detection(norad, d0, d1)
    if fus is not None:
        fthr = fus.attrs.get("thr", 0.5)
        fflag = fus[fus["fusion"] >= fthr]
        figf = go.Figure()
        figf.add_trace(go.Scatter(x=fus["epoch"], y=fus["fusion"], mode="lines",
                                  line=dict(color="#CC79A7", width=1.4), name="融合機動機率"))
        figf.add_hline(y=fthr, line_dash="dash", line_color="#999",
                       annotation_text=f"操作門檻 {fthr:.2f} (FPR≤0.05)")
        if len(fflag):
            figf.add_trace(go.Scatter(x=fflag["epoch"], y=fflag["fusion"], mode="markers",
                                      marker=dict(color="#D55E00", size=7), name="融合旗標"))
        figf.update_layout(height=240, yaxis_title="融合機率", yaxis_range=[0, 1],
                           margin=dict(t=20, b=30), legend=dict(orientation="h", y=1.25))
        st.plotly_chart(figf, width="stretch")
        st.caption(f"融合旗標 {len(fflag)} 筆。以衛星分組 CV 訓練(HistGBM)，"
                   "unit 級對齊 MEME 真值，操作點取 FPR≤0.05 下最高 recall。")
    else:
        st.caption("融合評分器不可得（需 models_fusion/fusion_scorer.pkl，執行 `python fusion_scorer.py`）。")

    # ── 🤖 SSA-RAG 自動解說（③ 偵測結果 → 自然語言 → RAG）───────────────────────
    if rag_auto:
        _ev = pd.DataFrame()
        if len(tr) and combined.any():
            _et = tr[combined].copy()
            _ev = pd.DataFrame({
                "epoch": _et["epoch"].to_numpy(),
                "sma_delta": _et["da_km"].abs().to_numpy(),
                "sma_direction": np.where(_et["da_km"].to_numpy() > 0, "raise", "lower"),
            })
        _alt_avg = float(tr["alt_km"].mean()) if len(tr) else None
        _narr = build_tle_maneuver_narrative(norad, _alt_avg, str(d0), str(d1), _ev)
        # Starlink（Model 1 分布內）額外附 ML 偵測敘述
        if _in_domain and det is not None:
            _ddf = det[0]
            _p_ml = float(_ddf.loc[_ddf["flag"], "prob"].max()) if _ddf["flag"].any() \
                else float(_ddf["prob"].max())
            _feat = {
                "alt_km": _alt_avg if _alt_avg is not None else float("nan"),
                "net_da_km": float(_ddf["da_km"].sum()),
                "max_da_km": float(_ddf["da_km"].abs().max()),
                "flag_rate": float(_ddf["flag"].mean()),
                "dv_net_ms": float(_ddf["da_km"].sum()) / 2 * 0.0011 * 1000,
            }
            _narr += "\n\n" + build_ml_maneuver_narrative(
                norad, _p_ml, _feat, str(d0), str(d1), alert=bool(_ddf["flag"].any()))
        render_rag_auto_explain(_narr, base_url=rag_url)

# ── ⑤ MEME vs TLE（72h 模型）────────────────────────────────────────────────
st.subheader("⑤ MEME vs TLE（僅 72h 模型，不做長時程外推）")
try:
    from compare_tle_vs_ephemeris import (find_all_ephemeris_files, propagate_with_best_tles,
                                          _meme_first_state)
    from skyfield.api import load as skyload
    sat_dir = DATA / "raw" / sat_name
    files = find_all_ephemeris_files(sat_dir) if sat_dir.is_dir() else []
    if files:
        snaps = [s for s in (_meme_first_state(f) for f in sorted(files)) if s]
        meme = pd.DataFrame(snaps).sort_values("t").reset_index(drop=True)
        meme = meme[meme["t"] <= meme["t"].iloc[0] + pd.Timedelta(hours=72)]
        ts = skyload.timescale()
        tle_df = df.rename(columns={"epoch": "epoch_utc"})
        prop = propagate_with_best_tles(meme[["t", "r_x", "r_y", "r_z"]], tle_df, sat_name, ts)
        mg = meme.merge(prop[["t", "r_x", "r_y", "r_z"]], on="t", suffixes=("_m", "_t"))
        err = np.sqrt((mg.r_x_t-mg.r_x_m)**2 + (mg.r_y_t-mg.r_y_m)**2 + (mg.r_z_t-mg.r_z_m)**2)
        age_h = (mg["t"] - mg["t"].iloc[0]).dt.total_seconds() / 3600
        figm = go.Figure(go.Scatter(x=age_h, y=err, line=dict(color="#0072B2")))
        figm.update_layout(height=300, xaxis_title="MEME 外推齡 (h, 0–72)",
                           yaxis_title="TLE-vs-MEME 位置誤差 (km)", margin=dict(t=20))
        st.plotly_chart(figm, width="stretch")
        st.caption(f"72h 內位置誤差中位 {np.median(err):.2f} km、P95 {np.percentile(err,95):.2f} km")
    else:
        st.caption(f"無 {sat_name} 的 MEME 星曆（data/raw/）。")
except Exception as e:
    st.caption(f"MEME 比較不可得：{e}")

# ── ⑥ 資料品質稽核 (quality_flag) ─────────────────────────────────────────────
st.subheader("⑥ 資料品質稽核（quality_flag：good / suspect / rejected）")
au = dqa.audit_tles(df)
qs = dqa.summarize(au)
qc = st.columns(5)
qc[0].metric("良好 good", qs["good"], f"{qs['frac_good']*100:.1f}%")
qc[1].metric("存疑 suspect", qs["suspect"])
qc[2].metric("剔除 rejected", qs["rejected"])
qc[3].metric("重複移除 (≤60s)", qs["n_dup"])
qc[4].metric("主因", "、".join(f"{k}:{v}" for k, v in qs["top_reason"].items()) or "—")

_qcmap = {"good": "#2ca02c", "suspect": "#E69F00", "rejected": "#d62728"}
figq = go.Figure()
for _fl in ("good", "suspect", "rejected"):
    _sub = au[au["quality_flag"] == _fl]
    if not _sub.empty:
        figq.add_trace(go.Scatter(
            x=_sub["epoch"], y=_sub["sma_km"], mode="markers",
            marker=dict(size=5, color=_qcmap[_fl]), name=_fl,
            text=_sub["quality_reason"],
            hovertemplate="%{x}<br>sma=%{y:.3f} km<br>%{text}<extra>" + _fl + "</extra>"))
figq.update_layout(title="半長軸時序（依 quality_flag 著色）", height=300,
                   margin=dict(t=40, b=30, l=10, r=10),
                   yaxis_title="sma (km)", legend=dict(orientation="h"))
st.plotly_chart(figq, width="stretch")

_bad = au[au["quality_flag"] != "good"]
if not _bad.empty:
    st.caption(f"非 good 共 {len(_bad)} 筆（可下載複核）：")
    st.dataframe(_bad[["epoch", "sma_km", "inclination_deg", "bstar",
                       "quality_flag", "quality_reason"]],
                 hide_index=True, width="stretch", height=min(300, 52 + 34 * len(_bad)))
else:
    st.caption("此日期範圍內 TLE 全部判定為 good。")
st.caption("規則：**rejected**＝e∉[0,1)／sma≤R⊕／inc∉[0,180]／checksum 錯；"
           "**suspect**＝TLE 缺口>48h（J2 外推誤差，見 NORAD 44349 案例）／單步 Δi>3°／|B\\*|>1；"
           "重複 epoch（≤60s）已移除另計，不影響品質判定。全庫稽核：`python data_quality_audit.py`。")

# ── ⑦ 星系級異常分析（constellation_anomaly）─────────────────────────────────
@st.cache_data(show_spinner=False)
def _cached_constellation(cn: str, days: int):
    from datetime import timedelta as _td
    pat = ca.CONSTELLATIONS[cn]
    con = duckdb.connect(DB_PATH, read_only=True)
    mx = con.execute("SELECT MAX(epoch_utc) FROM raw_tle_archive WHERE UPPER(object_name) LIKE ?",
                     [pat]).fetchone()[0]
    con.close()
    date1 = pd.Timestamp(mx); date0 = date1 - _td(days=days)
    cdf = ca.load_constellation(DB_PATH, pat, date0, date1)
    if cdf.empty or cdf["norad_id"].nunique() < 5:
        return None
    R = ca.analyze(cdf)
    return {"planes": R["planes"], "batch": R["batch"], "formation": R["formation"],
            "K": R["K"], "nsat": int(cdf["norad_id"].nunique()),
            "d0": str(date0.date()), "d1": str(date1.date())}


def _detect_constellation(name: str):
    up = (name or "").upper()
    for cn, pat in ca.CONSTELLATIONS.items():
        if pat.strip("%") in up:
            return cn
    return None


st.subheader("⑦ 星系級異常分析（軌道面 Δi std／批量機動／陣型誤差）")
_cn = _detect_constellation(sat_name)
if _cn is None:
    st.caption(f"「{sat_name}」不屬於已知星系清單，略過。已知：{'、'.join(ca.CONSTELLATIONS)}")
else:
    _cdays = st.slider("分析窗（天）", 7, 60, 30, key="cn_days")
    if st.button(f"▶ 執行 {_cn} 星系級分析（大型星系需 10–20 秒）", key="cn_go"):
        with st.spinner(f"{_cn} 星系級分析中…"):
            CR = _cached_constellation(_cn, _cdays)
        if CR is None:
            st.warning("星系資料不足。")
        else:
            planes, batch, formation = CR["planes"], CR["batch"], CR["formation"]
            st.caption(f"{_cn}：**{CR['nsat']}** 顆，窗 {CR['d0']} ~ {CR['d1']}")
            cc = st.columns(3)
            cc[0].metric("① 異常軌道面", int(planes["flag_plane_incoherent"].sum()),
                         f"{len(planes)} 面")
            cc[1].metric("② 批量事件日", int(batch["flag_batch"].sum()), f"K={CR['K']:.0f}")
            cc[2].metric("③ 相位離群衛星", int(formation["n_outliers"].sum()))
            with st.expander("① 軌道面一致性（同 RAAN 面 Δi 標準差，降冪）"):
                st.dataframe(planes.head(15), hide_index=True, width="stretch")
            with st.expander("② 批量機動識別（同天顯著 |Δa|>2km 機動衛星數）"):
                st.dataframe(batch.head(15), hide_index=True, width="stretch")
            with st.expander("③ 陣型誤差（同面緯度幅角相位殘差 std，降冪）"):
                st.dataframe(formation.head(15), hide_index=True, width="stretch")
            st.caption("① Δi std 過高＝協同傾角機動/星系重組；② 同天機動數 > mean+3σ＝批量"
                       "部署/重組；③ 緯度幅角偏離均勻間隔＝相位保持失效/戰術移相。"
                       "對應事件分類：批量部署／星系重組／戰術機動。")

# ── ④ 艦隊級統計（284 顆）+ bootstrap CI ─────────────────────────────────────
# 先隱藏（使用者要求 2026-07-14）：整段艦隊統計 + 95% CI 暫不顯示；改 True 即復原。
_SHOW_FLEET_STATS = False
if _SHOW_FLEET_STATS:
    st.subheader("④ 艦隊級統計（全 MEME 284 顆）＋ 95% 信賴區間")
    truth = load_truth()
    if not truth.empty:
        # 每顆 medium+ 機動episode率（gap>48h 合併）
        med = truth[truth["da_severity"].isin(["medium", "large"])].copy()
        rates = []
        for s, g in med.groupby("sat_name"):
            tt = np.sort(g["t_to"].astype("int64").to_numpy())
            span_d = max((tt[-1] - tt[0]) / 3.6e12 / 24, 1) if len(tt) > 1 else 1
            n_ep = 1 + int((np.diff(tt) > 48 * 3.6e12).sum()) if len(tt) > 1 else len(tt)
            rates.append(n_ep / span_d * 30)  # 每 30 天episode數
        m, lo, hi = bootstrap_ci(np.array(rates))
        cA, cB = st.columns(2)
        cA.metric("艦隊機動episode率（每30天/顆）", f"{m:.2f}", f"95% CI [{lo:.2f}, {hi:.2f}]")
        cA.caption(f"{len(rates)} 顆有 ≥5km 機動")
        sm = load_stat_metrics()
        if not sm.empty:
            cB.markdown("**各偵測器（TLE 序列）vs MEME 真值**")
            show = sm[sm["input"] == "TLE"][["method", "precision", "recall", "lead_time_h_median"]]
            cB.dataframe(show, hide_index=True, width="stretch")
    else:
        st.caption("找不到 transitions_full 真值檔。")

# ── ⑩ 合成 TLE ───────────────────────────────────────────────────────────────
st.subheader("⑩ 合成 TLE 批次生成")
with st.expander("展開合成資料生成器（依條件批次產生）"):
    try:
        import datetime as _dt
        from synthetic_tle import (ManeuverParams, ManeuverType, NoiseLevel,
                                    OrbitalElements, generate_sequence,
                                    generate_training_pair, seq_to_tle_text)
        cS = st.columns(4)
        n_sat = int(cS[0].number_input("衛星數", 1, 500, 10))
        n_days = int(cS[1].number_input("天數", 3, 120, 26))
        cadence = float(cS[2].number_input("TLE 間隔 (h)", 1, 24, 8))
        man_frac = cS[3].slider("含機動比例", 0.0, 1.0, 0.5, 0.1)
        c6 = st.columns(4)
        alt_lo, alt_hi = c6[0].slider("高度範圍 (km)", 300, 1200, (500, 600), 10)
        inc_lo, inc_hi = c6[1].slider("傾角範圍 (deg)", 0, 100, (52, 55), 1)
        dv_lo, dv_hi = c6[2].slider("ΔV 範圍 (m/s)", 0.1, 50.0, (0.5, 5.0), 0.1)
        noise = c6[3].selectbox("雜訊等級", ["LOW", "MEDIUM", "HIGH"], index=1)
        seed = int(st.number_input("亂數種子", 0, 99999, 42))

        if st.button("生成並下載 synthetic.tle"):
            rng = np.random.default_rng(seed)
            n_tles = max(3, int(round(n_days / (cadence / 24.0))))
            ep0 = _dt.datetime(2026, 5, 1, tzinfo=_dt.timezone.utc)
            nl = getattr(NoiseLevel, noise)
            mtypes = list(ManeuverType)
            texts, n_man = [], 0
            with st.spinner(f"生成 {n_sat} 顆 × {n_tles} TLE…"):
                for k in range(n_sat):
                    start = OrbitalElements(
                        sma_km=R_E + rng.uniform(alt_lo, alt_hi),
                        ecc=rng.uniform(0, 0.002), inc_deg=rng.uniform(inc_lo, inc_hi),
                        raan_deg=rng.uniform(0, 360), argp_deg=rng.uniform(0, 360),
                        ma_deg=rng.uniform(0, 360), epoch=ep0,
                        bstar=rng.uniform(1e-5, 3e-4), norad_id=90000 + k)
                    if rng.random() < man_frac:
                        mp = ManeuverParams(
                            maneuver_type=rng.choice(mtypes),
                            dv_m_s=float(rng.uniform(dv_lo, dv_hi)),
                            delta_t_days=float(rng.uniform(n_days * 0.3, n_days * 0.7)),
                            dv_prograde_fraction=1.0, target_sma_km=None)
                        before, after = generate_training_pair(
                            start, mp, n_before=n_tles // 2, n_after=n_tles - n_tles // 2,
                            dt_days=cadence / 24.0, noise_level=nl, rng=rng)
                        seq = before + after
                        n_man += 1
                    else:
                        seq = generate_sequence(start, n_tles, dt_days=cadence / 24.0,
                                                noise_level=nl, rng=rng)
                    texts.append(seq_to_tle_text(seq, f"SYNTH-{90000 + k}"))
            out = "\n".join(texts)
            st.success(f"完成：{n_sat} 顆（含機動 {n_man} 顆），每顆 ~{n_tles} 筆 TLE。")
            st.download_button("下載 synthetic.tle", out, file_name="synthetic.tle")
    except Exception as e:
        st.caption(f"合成模組不可得：{e}（可改用 synthetic_app.py）")

# ── ⑧ SSA-RAG 知識問答 ────────────────────────────────────────────────────────
st.subheader("⑧ SSA-RAG 知識問答（太空態勢感知知識庫）")
with st.expander("展開互動問答（需 SSA-RAG 服務上線）", expanded=False):
    render_ssa_rag_page(base_url=rag_url)

st.divider()
st.caption("maneuver_app_2026August.py · 模型：P1–P6（拋物線 P2/P5）· CUSUM/BOCPD/SSA · "
           "MEME-tuned 偵測(window≥5km) + forecast(1d) · 真值：MEME 284 顆 · "
           "SSA-RAG 自動解說＋知識問答")
