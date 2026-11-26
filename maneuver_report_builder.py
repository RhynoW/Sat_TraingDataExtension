#!/usr/bin/env python3
"""maneuver_report_builder.py — 機動偵測報表產製核心邏輯（Streamlit 無關）。

供 maneuver_app_2026SOctober.py（互動 UI）與 report_api.py（PDF API 服務）共用。
刻意不 import streamlit：report_api.py 是獨立部署的服務，若直接 import
maneuver_app_2026SOctober.py 來借用函式，會連帶執行該檔頂層的
st.set_page_config()／st.stop() 等只能在 Streamlit runtime 下運作的程式碼。

本檔案的資料後端 bootstrap（HF_DATASET_REPO 等環境變數）與
maneuver_app_2026September.py 完全同源複製，僅把 st.warning/st.error/st.stop
換成例外與 logging，行為（環境變數、優先順序）不變。
"""
from __future__ import annotations

import json
import logging
import os
import textwrap
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms
import statistical_detectors as sd

logger = logging.getLogger(__name__)

R_E = 6378.137
DATA = Path("data")

# ── 資料後端 bootstrap（與 maneuver_app_2026September.py:906-986 同源）──────────
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "").strip()
LOCAL_DB = os.environ.get("LOCAL_DB_PATH", "space_db.duckdb")
STUB_DB = os.environ.get("HF_STUB_PATH", "space_hf.duckdb")

_HF_LAYOUT = {
    "raw_tle_archive":   ("raw_tle_archive/**/*.parquet", True),
    "catalog":           ("catalog.parquet", True),
    "sat_n2yo_metadata": ("sat_n2yo_metadata/**/*.parquet", False),
    "maneuver_labels":   ("maneuver_labels/**/*.parquet", False),
    "conjunction_events": ("conjunction_events/**/*.parquet", False),
    "training_samples":  ("training_samples/**/*.parquet", False),
    "training_samples_plan_b": ("training_samples_plan_b/**/*.parquet", False),
}


def _ensure_httpfs() -> None:
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
                logger.warning("HF secret 建立失敗：%s", e)
        c.close()
    except Exception as e:
        logger.warning("httpfs 安裝失敗（可能已安裝）：%s", e)


def _build_hf_stub(stub_path: str, repo: str) -> str:
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
    con.close()
    return stub_path


def _bootstrap_db() -> tuple[str, str]:
    """回傳 (DB_PATH, backend)。backend ∈ {'local','hf'}。失敗時拋 RuntimeError
    （呼叫端＝report_api.py 應接住並回傳 500，而不是像 Streamlit 版一樣直接停頁）。"""
    if HF_DATASET_REPO:
        _ensure_httpfs()
        _build_hf_stub(STUB_DB, HF_DATASET_REPO)
        return STUB_DB, "hf"
    if Path(LOCAL_DB).exists():
        return LOCAL_DB, "local"
    if Path(STUB_DB).exists():
        _ensure_httpfs()
        return STUB_DB, "hf"
    raise RuntimeError("找不到資料來源：未設 HF_DATASET_REPO，本機亦無 space_db.duckdb")


DB_PATH, DATA_BACKEND = _bootstrap_db()


# ── data loaders（與 app 內同名函式邏輯一致，僅移除 @st.cache_data）────────────
def load_tle(norad_id: int, start=None, end=None) -> pd.DataFrame:
    con = duckdb.connect(DB_PATH, read_only=True)
    q = ("SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
         "raan_deg, argp_deg, mean_anomaly_deg, mean_motion, bstar, line1, line2 FROM raw_tle_archive "
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


def load_f107() -> dict:
    p = Path("f107_cache.csv")
    if not p.exists():
        return {}
    f = pd.read_csv(p)
    f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
    return dict(zip(f["epoch"], f["f107"]))


def satellite_name(norad_id: int) -> str | None:
    """從 catalog／sat_n2yo_metadata 查衛星名稱；查不到回傳 None（呼叫端自行決定顯示方式）。"""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        # sat_n2yo_metadata 之名稱欄為 name_en（2026-11-26 發現：原只查 name 欄，全數回傳 None，
        # 離線執行時 Starlink 被當成非 Starlink，ML／融合通道受限）；舊版 name 欄保留相容
        # 新編目衛星不在 sat_n2yo_metadata：改取 raw_tle_archive 最新一筆之 3LE 名稱（略過「TBA」暫名）
        queries = [f"SELECT {col} FROM {table} WHERE norad_id=? LIMIT 1"
                   for table, col in (("sat_n2yo_metadata", "name_en"), ("sat_n2yo_metadata", "name"), ("catalog", "name"))]
        queries.append("SELECT object_name FROM raw_tle_archive WHERE norad_id=? AND object_name IS NOT NULL "
                       "AND object_name NOT ILIKE '%TBA%' ORDER BY epoch_jd DESC LIMIT 1")
        for q in queries:
            try:
                r = con.execute(q, [int(norad_id)]).fetchone()
                if r and r[0] and str(r[0]).strip():
                    name = str(r[0]).strip()
                    # 部分來源（如新編目衛星）name 欄位直接沿用 3LE 原始格式，
                    # 帶有「0 」line-0 前綴（3LE：第 0 行＝"0 <名稱>"），需去除。
                    if name.startswith("0 "):
                        name = name[2:].strip()
                    return name
            except Exception:
                continue
    finally:
        con.close()
    return None


# ── L1：規則式 P1–P6（沿用 maneuver_strategies_july）─────────────────────────
def compute_l1(df: pd.DataFrame, f107: dict, lang: str = "zh") -> dict:
    """回傳 {"orbit_class", "inc_family", "combined": bool[], "detail": dict}。
    df 須已依所需日期區間過濾、且至少 3 筆（呼叫端負責檢查）。"""
    a0 = float(df["sma_km"].iloc[0])
    i0 = float(df["inclination_deg"].iloc[0])
    orbit_class = ms.classify_orbit(a0, float(df["eccentricity"].iloc[0]), i0)
    fam = ms.inc_family(i0)
    tr = ms.build_transitions(df, f107)
    res = ms.apply_strategies(tr, orbit_class, lang=lang)
    combined = res["combined"] if len(tr) else np.array([], dtype=bool)
    return {"orbit_class": orbit_class, "inc_family": fam, "combined": combined,
            "n_flagged": int(np.sum(combined)), "detail": res, "tr": tr}


# ── L2：CUSUM／BOCPD／SSA／3σ-MAD（沿用 statistical_detectors）───────────────
def compute_l2(df: pd.DataFrame) -> dict:
    """回傳 statistical_detectors.run_all() 之原始結果
    （{"cusum":{"scores","events"}, "bocpd":{...}, "ssa":{...}, "mad3sig":{...}}）。"""
    return sd.run_all(df["sma_km"].to_numpy(float))


# ── 補充觀察指標（實驗性）：相位殘差通道 ────────────────────────────────────
# 對應案例二十一之發現：L1/L2/L3 皆作用於半長軸(sma)，對「相位調整(phasing)
# 機動」——軌道週期暫時改變、事後幾乎完全恢復，sma 幾乎不變但沿軌位置累積
# 偏移——structurally 看不到。原理與參數（k=6 MAD、3 次迭代）沿用
# phase_residual_detector.py，但此處僅重算核心訊號，不依賴該檔案匯入之
# tasa14_compare/tasa23_ext_arena（純屬標竿驗證用，非production相依）。
#
# **明確定位為「補充觀察指標」而非新增判定通道**：23 星標竿獨立表現偏弱
# （macro F1≈0.10，遠低於 L1/L2/L3），且驗證文件本身聲明「應維持候選假說
# 層級，不宜作為已驗證方法引用」（見
# docs/相位殘差通道_新增偵測管道實作與驗證_20260913.md）。因此本函式回傳值
# 僅供報表／App 顯示參考，**不併入 L1/L2/L3 之任何評分、不影響 landing_events
# 判定**，避免此實驗性訊號拉低整體系統可信度。
PHASE_RESIDUAL_MERGE_DAYS = 3.0  # 沿用 phase_residual_detector.py 之 MERGE_D


def compute_phase_residual_experimental(df: pd.DataFrame, k: float = 6.0, n_iter: int = 3) -> dict:
    """實驗性相位殘差補充觀察指標。df 須含 epoch/sma_km/argp_deg/mean_anomaly_deg/
    mean_motion（load_tle 已含全部欄位）。回傳 {"n_flags", "max_abs_residual_km",
    "flagged_epochs", "status"}；資料不足或無法計算時 status="insufficient_data"。"""
    if len(df) < 10 or df["mean_motion"].isna().all():
        return {"status": "insufficient_data", "n_flags": 0,
                "max_abs_residual_km": None, "flagged_epochs": []}

    d = df.dropna(subset=["mean_anomaly_deg", "argp_deg", "mean_motion", "sma_km"]).reset_index(drop=True)
    if len(d) < 10:
        return {"status": "insufficient_data", "n_flags": 0,
                "max_abs_residual_km": None, "flagged_epochs": []}

    t = d["epoch"]
    a = d["sma_km"].to_numpy(float)
    u = (d["argp_deg"].to_numpy(float) + d["mean_anomaly_deg"].to_numpy(float)) % 360.0
    n = d["mean_motion"].to_numpy(float)
    tsec = t.astype("int64").to_numpy() / 1e9

    n_pts = len(a)
    resid = np.full(n_pts, np.nan)
    for i in range(1, n_pts):
        dt_days = (tsec[i] - tsec[i - 1]) / 86400.0
        predicted_orbits = n[i - 1] * dt_days
        predicted_u = (u[i - 1] + predicted_orbits * 360.0) % 360.0
        diff_deg = (u[i] - predicted_u + 180.0) % 360.0 - 180.0
        resid[i] = np.radians(diff_deg) * a[i]

    mask = np.zeros(n_pts, bool)
    for _ in range(n_iter):
        s = resid[np.isfinite(resid) & ~mask]
        if len(s) < 10:
            break
        med = np.median(s)
        mad = 1.4826 * np.median(np.abs(s - med))
        if not np.isfinite(mad) or mad == 0:
            break
        newmask = np.isfinite(resid) & (np.abs(resid - med) > k * mad)
        if newmask.sum() == mask.sum():
            mask = newmask
            break
        mask = newmask

    valid = resid[np.isfinite(resid)]
    if len(valid) < 10:
        return {"status": "insufficient_data", "n_flags": 0,
                "max_abs_residual_km": None, "flagged_epochs": []}
    med = np.median(valid)
    mad = 1.4826 * np.median(np.abs(valid - med))
    max_abs = float(np.nanmax(np.abs(resid - med))) if np.isfinite(resid).any() else None
    if not np.isfinite(mad) or mad == 0:
        return {"status": "ok", "n_flags": 0, "max_abs_residual_km": max_abs, "flagged_epochs": []}

    idx = np.where(np.isfinite(resid) & (np.abs(resid - med) > k * mad))[0]
    flagged_epochs: list = []
    if len(idx):
        grp = [idx[0]]
        for j in idx[1:]:
            if tsec[j] - tsec[grp[-1]] <= PHASE_RESIDUAL_MERGE_DAYS * 86400:
                grp.append(j)
            else:
                best = grp[int(np.argmax(np.abs(resid[grp] - med)))]
                flagged_epochs.append(t.iloc[best])
                grp = [j]
        best = grp[int(np.argmax(np.abs(resid[grp] - med)))]
        flagged_epochs.append(t.iloc[best])

    return {"status": "ok", "n_flags": len(flagged_epochs),
            "max_abs_residual_km": max_abs,
            "flagged_epochs": sorted(flagged_epochs)}


# ── L3：ML 逐窗機率（models_meme）與融合評分器（models_fusion）──────────────
# 與 maneuver_app_2026September.py:1177-1351 邏輯完全一致，僅移除 @st.cache_data／
# @st.cache_resource（改為模組層級延遲載入單例）並改用本檔的 load_tle/load_f107。
_fusion_model_cache: dict | None = None


def _load_fusion():
    global _fusion_model_cache
    if _fusion_model_cache is None:
        import joblib
        p = Path("models_fusion/fusion_scorer.pkl")
        _fusion_model_cache = joblib.load(p) if p.exists() else False
    return _fusion_model_cache or None


def _memo_by_window(fn):
    """依 (NORAD, 起日, 迄日) 快取結果、回傳副本（呼叫端可放心修改）。App 頁面與 PDF 報表
    會對同一區間各算一次 ML／融合評分器（數十秒），共用快取避免重算。最多保留 16 組。"""
    import functools
    cache: dict = {}
    order: list = []
    lock = threading.Lock()

    def _copy(v):
        if isinstance(v, pd.DataFrame):
            out = v.copy()
            out.attrs = dict(v.attrs)
            return out
        if isinstance(v, tuple):
            return tuple(_copy(x) for x in v)
        return v

    @functools.wraps(fn)
    def wrap(norad, d0, d1):
        key = (int(norad), str(d0), str(d1))
        with lock:
            hit = key in cache
            val = cache.get(key)
        if not hit:
            val = fn(norad, d0, d1)
            with lock:
                cache[key] = val
                order.append(key)
                while len(order) > 16:
                    cache.pop(order.pop(0), None)
        return _copy(val)
    return wrap


@_memo_by_window
def compute_ml_detection(norad: int, d0, d1):
    """逐窗口 ML 機動偵測（models_meme，window ≥5km）。回傳 (df[epoch,prob,...], thr) 或 None。"""
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

    dr = dr_am = None
    try:
        from atmospheric_drag import drag_residual, load_space_weather
        _cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
        _dr = drag_residual(dd[_cols], load_space_weather()).set_index("epoch")
        dr = _dr["drag_resid_da"]
        dr_am = dr.abs().rolling("7D").max()
    except Exception:
        pass

    sma = dd["sma_km"].to_numpy(float)
    idxs = np.arange(1, len(dd))
    if len(idxs) > 220:
        # 等距抽樣只為控制耗時，但可能標記的時點一定要評分：旗標需 |殘差| > 門檻（無殘差時需 |Δa| > P2），
        # 只靠抽樣時資料越長漏得越多，同一事件會因查詢範圍不同而少一個通道、等級下降
        # （2026-10-31，NORAD 58651 2026-09-18：SNR 145，範圍 A 為 E3、範圍 B 因 1932 筆抽 220 點降為 E1）
        if dr is not None:
            must = dr[~dr.index.duplicated(keep="last")].reindex(dd["epoch"]).abs().to_numpy() > DRAG_EVENT_KM
        else:
            must = np.r_[False, np.abs(np.diff(sma)) > ms.DEFAULT_P2(sma[1:] - R_E)]
        idxs = np.union1d(np.linspace(1, len(dd) - 1, 220).astype(int), np.flatnonzero(must))
        idxs = idxs[idxs >= 1]

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
    if out["drag_resid_da"].notna().any():
        out["flag"] = (out["prob"] >= float(thr)) & (out["drag_resid_da"].abs() > 0.30)
    else:
        out["flag"] = (out["prob"] >= float(thr)) & (out["da_km"].abs() > out["p2_thr"])
    return out, float(thr)


@_memo_by_window
def compute_fusion_detection(norad: int, d0, d1):
    """連續融合評分器（L3）：5 通道 → ±24h 窗特徵 → HistGBM 機率。回傳 df[epoch,fusion] 或 None。"""
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
        cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
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


def compute_drag_series(df: pd.DataFrame) -> pd.DataFrame | None:
    """NRLMSIS 阻力殘差序列（非 Starlink 的機動偵測時間序列圖用）：df[epoch, drag_resid_da, reentry]。
    與 app 的 compute_nrlmsis_maneuvers 同一計算；自然再入衰減時 reentry=True（圖上不標機動事件）。
    缺 atmospheric_drag／太空天氣資料或筆數不足時回傳 None，不中斷報表產製。"""
    if len(df) < 5:
        return None
    try:
        from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay
        cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in df.columns]
        dr = drag_residual(df[cols], load_space_weather())
        if dr.empty:
            return None
        out = dr[["epoch", "da_km", "drag_resid_da"]].copy()
        out["epoch"] = pd.to_datetime(out["epoch"], utc=True)
        out["reentry"] = bool(is_reentry_decay(df))
        return out.dropna(subset=["drag_resid_da"]).reset_index(drop=True)
    except Exception as e:
        logger.warning("阻力殘差序列計算失敗，略過：%s", e)
        return None


# ── AI 思維過程說明（SSA-RAG，best-effort；離線／逾時自動退回規則式敘述）──────
RAG_DEFAULT_URL = os.environ.get("SSA_RAG_URL", "http://127.0.0.1:8000")
RAG_TIMEOUT_S = float(os.environ.get("SSA_RAG_TIMEOUT_S", "120"))


def build_tle_maneuver_narrative(satellite_id, alt_km_avg, start_date: str,
                                 end_date: str, event_df: pd.DataFrame,
                                 with_questions: bool = True) -> str:
    """LEO/MEO TLE 自適應偵測結果 → 自然語言描述（與 app 內同名函式邏輯一致）。
    with_questions=False：不附結尾那段「請解說…」——那是送給 LLM 的提問，
    SSA-RAG 離線退回時若照印，報表會只有問題沒有答案（2026-10-29 委員提問）。"""
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
                f"半長軸{direction}，|Δa| = {abs(float(ev['sma_delta'])):.4f} km")
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
            "恒為正、不代表方向。")
        if with_questions:
            lines.append(
                "請根據以上偵測結果解說：這種半長軸跳變模式最可能對應哪種機動類型"
                "（軌道維持、軌道抬升、避碰或離軌）？機動後 TLE 失效對 conjunction "
                "screening 有什麼影響？")
    elif with_questions:
        lines.append(
            "請解說：此期間未偵測到明顯機動的可能原因有哪些？"
            "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return "\n".join(lines)


_MU_KM3_S2 = 398600.4418


def _fmt_da(x: float) -> str:
    """Δa 顯示：百公里級跳變不需要到公尺，小量級保留三位小數。"""
    return f"{x:+.1f}" if abs(x) >= 10 else f"{x:+.3f}"


def _ev_list(evs: list[dict]) -> str:
    return "、".join(f"#{e['no']}" for e in evs)


def build_rule_based_explanation(alt_km_avg, events: list[dict],
                                 first_last_da: float | None = None,
                                 max_jump: dict | None = None,
                                 drag_only: list[str] | None = None,
                                 segments: list[dict] | None = None,
                                 prior: dict | None = None) -> str:
    """附錄 F「分析註記」：固定三段（可直接觀察／待驗證解釋／建議複核），決定論、只用本報表
    已算出的數字。待驗證解釋只列可能原因、不排序——沒有證據時不替原因排高低（2026-10-29
    第二輪審閱意見）。輸入是候選事件而非逐筆候選點：逐筆 Δa 加總不等於全期間淨變化
    （第一輪意見：NORAD 58573 曾因此被寫成「淨抬升、排除軌道降低」）。"""
    obs = ["【可直接觀察】"]
    if first_last_da is not None:
        obs.append(f"‧ 全期間首末半長軸差 {first_last_da:+.2f} km。")
    if max_jump:
        obs.append(f"‧ 最大單筆相鄰 TLE Δa：{pd.Timestamp(max_jump['epoch']):%Y-%m-%d} {_fmt_da(max_jump['da'])} km"
                   + (f"（候選事件 #{max_jump['event_no']}）。" if max_jump.get("event_no") else "（未列入候選事件）。"))
    if not events:
        return "\n".join(obs + [
            "‧ 規則式偵測未標記任何候選事件。",
            "",
            "【待驗證解釋（未排序）】",
            "‧ 衛星未執行機動（例如處於任務穩定期，或推進系統已停用）。",
            "‧ 機動量小於 TLE 逐筆擬合雜訊（約數十至數百公尺），無法由本方法偵測。",
            "‧ TLE 更新稀疏或中斷，機動效果與其他攝動混在一起而無法分辨。",
            "",
            "【建議複核】",
            *([f"‧ 阻力殘差有 {len(drag_only)} 次事件（{'、'.join(drag_only)}），規則式未標記，"
               "建議核對該時段 TLE（附錄 B）。"] if drag_only else []),
            "‧ 未偵測到不代表未機動；如需確認，請比對營運者公告或其他軌道資料。"])

    spikes = [e for e in events if e["quality_note"] == STATUS_SPIKE]
    valid = [e for e in events if e["quality_note"] != STATUS_SPIKE]
    obs.append(f"‧ 候選事件 {len(events)} 次"
               + (f"；其中 {len(spikes)} 次呈回跳型態（{_ev_list(spikes)}），以下解釋不納入" if spikes else "")
               + "。")
    if events and "grade" in events[0]:
        obs.append("‧ 證據等級：" + "、".join(
            f"{GRADE_TEXT[g]} {n} 件" for g in ("E3", "E2", "E1", "D")
            if (n := sum(e['grade'] == g for e in events)) or g != "D")
            + (f"（E2 中 {k} 件為非 Starlink 衛星因 ML 輔助由 E3 改列）" if (k := sum(bool(e.get("ml_capped")) for e in events))
               else "") + "。")
    for sg in segments or []:
        obs.append(f"‧ 事件 #{sg['events'][0]}–#{sg['events'][-1]} 為同向連續機動段 C{sg['no']}："
                   f"{pd.Timestamp(sg['t_start']):%Y-%m-%d}～{pd.Timestamp(sg['t_end']):%Y-%m-%d}，"
                   f"累計半長軸 {sg['cum_da']:+.1f} km（含段間漂移），平均約 {sg['rate_km_d']:+.2f} km/天。")
    nets = np.array([e["net_da"] for e in valid], float)
    if len(valid):
        i_up, i_dn = int(np.argmax(nets)), int(np.argmin(nets))
        if nets[i_up] > 0:
            obs.append(f"‧ 事件淨 Δa 最大抬升：#{valid[i_up]['no']}（{pd.Timestamp(valid[i_up]['t_start']):%Y-%m-%d}）"
                       f"{_fmt_da(nets[i_up])} km。")
        if nets[i_dn] < 0:
            obs.append(f"‧ 事件淨 Δa 最大降低：#{valid[i_dn]['no']}（{pd.Timestamp(valid[i_dn]['t_start']):%Y-%m-%d}）"
                       f"{_fmt_da(nets[i_dn])} km。")

    alt = float(alt_km_avg) if alt_km_avg is not None else None
    amax = float(np.abs(nets).max()) if len(nets) else 0.0
    if not len(valid):
        kind = "排除回跳型態後無其他事件；跳變可能來自 TLE 資料問題，也可能是真實軌道變化，需核查原始資料。"
    else:
        n = len(nets)
        n_raise = int((nets > 0).sum()); n_lower = n - n_raise
        up, dn, tot = float(nets.max()), float(nets.min()), float(nets.sum())
        if amax < NOISE_KM:
            kind = "事件幅度均小於 50 m，與 TLE 逐筆擬合雜訊同量級。可能原因包括：雜訊、極小的軌道修正。"
        elif up >= 5 and dn <= -5:
            kind = ("同時存在大幅抬升與大幅降低。可能原因包括：軌道轉移後再降軌、任務性軌道調整、"
                    "資料異常（例如編目交叉標記）。")
        elif n_lower == n and alt is not None and alt < 350 and tot < -5:
            kind = "事件全部為降低，且軌道低於 350 km。可能原因包括：主動降軌或離軌、資料異常。"
        elif tot > 5 or (n_raise >= 0.8 * n and amax > 2):
            kind = "以抬升為主。可能原因包括：" + ((prior or {}).get("raise") or "入軌後爬升至工作軌道、任務性軌道調升、資料異常") + "。"
        elif n_lower == n and (prior or {}).get("lower"):
            kind = "事件全部為降低。可能原因包括：" + prior["lower"] + "。"
        elif n_raise == n and (prior or {}).get("raise"):
            kind = "事件全部為抬升。可能原因包括：" + prior["raise"] + "。"
        elif amax <= 1.0 and n >= 2:
            kind = "多次小幅變化。可能原因包括：補償大氣阻力的軌道維持、TLE 擬合雜訊。"
        elif n == 1:
            kind = "單次跳變。可能原因包括：軌道維持、避碰機動、資料異常。"
        else:
            kind = "抬升與降低交錯。可能原因包括：軌道維持、避碰機動、任務性調整、資料異常。"

    top = sorted(valid or events, key=lambda e: -abs(e["net_da"]))[:3]
    e3 = [e for e in events if e.get("grade") == "E3"]
    rec = ["【建議複核】"]
    if e3:
        rec.append(f"‧ 優先複核 E3 事件（{_ev_list(e3[:10])}{'等' if len(e3) > 10 else ''}）：核對前後原始 TLE 與軌道根數連續性（附錄 E），"
                   "並以更新後軌道資料重算接近事件評估。")
    if {e["no"] for e in top} - {e["no"] for e in e3}:
        rec.append(f"‧ 核對事件淨 Δa 量級最大者（{_ev_list(sorted(top, key=lambda e: e['no']))}）前後的原始 TLE 與軌道根數連續性（附錄 E）。")
    if segments:
        rec.append("‧ 連續機動段應以整段（起訖、累計 Δa、平均速率）而非逐一離散事件解讀；段內 TLE 外推可信度持續偏低，"
                   "建議提高監視頻率。")
    if spikes:
        rec.append(f"‧ 核對回跳型態事件（{_ev_list(spikes)}）：確認是少數 TLE 的資料問題，或真實的軌道變化。")
    if any(abs(e["main_da"]) > BIG_JUMP_KM for e in events):
        rec.append(f"‧ 單筆 |Δa| 超過 {BIG_JUMP_KM:.0f} km 的跳變，建議排除編目交叉標記等資料問題。")
    if drag_only:
        rec.append(f"‧ 阻力殘差另有 {len(drag_only)} 次事件未被規則式標記（{'、'.join(drag_only)}），"
                   "建議一併核對該時段 TLE（附錄 B）。")
    rec.append("‧ 比對營運者公告、其他軌道資料（如精密星曆）或同時段的接近事件紀錄；"
               "僅憑 TLE 無法區分避碰機動與軌道維持。")
    if alt is not None and amax >= NOISE_KM:
        a = R_E + alt
        n_rad = (_MU_KM3_S2 / a ** 3) ** 0.5
        drift = 1.5 * n_rad * amax * 86400        # a·Δn·t，Δn ≈ 1.5·n·Δa/a
        fmt = lambda x: f"{x:,.0f} km" if x >= 1000 else f"{x:.1f} km"
        rec.append(f"‧ 沿軌相位漂移量級估計（僅考慮 Δa）：以最大事件 |淨 Δa| {amax:.3f} km、高度約 {alt:.0f} km，"
                   f"Δn ≈ 1.5·n·Δa／a、沿軌漂移 ≈ a·Δn·t：1 天約 {fmt(drift)}、3 天約 {fmt(3 * drift)}、"
                   f"7 天約 {fmt(7 * drift)}。假設機動後無後續控制，不含 TLE 本身誤差、大氣預報誤差與姿態／面質比變化；"
                   "線性外推僅在數天內有參考價值，超過約一週後其他攝動與後續機動主導。屬量級估計，"
                   "用於判斷是否需要立即更新接近評估，不是碰撞機率或預測誤差保證；不宜僅憑候選旗標自動停止預警。")
    pri = ([f"‧ 營運先驗（{prior['who']}，依公開營運模式的一般知識，非本期資料證據）：{prior['text']}"]
           if prior else [])
    return "\n".join(obs + ["", "【待驗證解釋（未排序）】", *pri, "‧ " + kind,
                            "‧ 以上原因未依可能性排序（營運先驗除外）。本報告未取得營運者機動公告或獨立精密星曆，"
                            "因此未將任何事件判定為已確認推進機動。", ""] + rec)


# ── 候選事件：L1 規則候選點合併成事件，其餘通道作為每個事件的輔助通道欄位 ──────
EVENT_MERGE_H = 48        # 與 detection_timeline.merge_episodes 同一合併規則（相鄰間隔連鎖合併）
EVIDENCE_PAD_H = 24       # 事件起訖前後此時距內有觸發即計一類輔助通道
DRAG_EVENT_KM = 0.30      # 阻力殘差事件門檻（與 detection_timeline 一致）
DRAG_ACCUM_RATIO = 0.5    # 單筆 |實測 Δa| < 此比例 × |殘差|：殘差主要來自阻力預期累積，非實測變化
GAP_LONG_D = 7.0          # 事件內候選轉換跨此天數以上的 TLE 空窗：不列 E3、加註（15 星實測 5.9 與 9.1 天之間無案例）
NOISE_KM = 0.05           # 單筆 |Δa| 小於此值視為 TLE 雜訊量級
BIG_JUMP_KM = 50.0        # 單筆跳變大於此值建議核對原始 TLE
# 複核註記（時間序列型態）與通道觸發程度是兩個獨立維度，分開記錄、分開呈現
STATUS_SPIKE = "回跳型態，資料品質待查"
STATUS_NOISE = "量級近 TLE 雜訊"
STATUS_MULTI = "多通道觸發"
STATUS_SINGLE = "單通道觸發"
STATUS_RULE_ONLY = "僅規則標記"
_EVIDENCE_LABELS = {"drag": ("阻力", "阻力殘差"), "fusion": ("融合", "L3 融合評分器"),
                    "ml": ("ML", "ML 候選窗口"), "l2": ("L2", "L2 ≥2 通道")}


def _merge_groups(times: list, gap_h: float = EVENT_MERGE_H) -> list[list[int]]:
    """依時間排序的 times，與前一點相隔 ≤ gap_h 小時者併入同一組（連鎖合併，
    故單一組的總跨度可超過 gap_h），回傳索引組。"""
    groups: list[list[int]] = []
    for i, t in enumerate(times):
        if groups and (t - times[groups[-1][-1]]).total_seconds() <= gap_h * 3600:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def build_candidate_events(df: pd.DataFrame, tr: pd.DataFrame, combined, l2_raw: dict,
                           drag_df: pd.DataFrame | None, fusion_df: pd.DataFrame | None,
                           ml_df: pd.DataFrame | None) -> list[dict]:
    """統一事件表：事件清單完全由 L1 規則候選點（相鄰 TLE 轉換）48 小時連鎖合併產生；
    阻力殘差／L3 融合／ML 窗口／L2 只當輔助通道欄位，不增刪事件——避免報表同時出現
    41／13／6 三種互不對應的總數（2026-10-29 審閱意見）。"""
    combined = np.asarray(combined, bool)
    if not len(tr) or not combined.any():
        return []
    hit_idx = np.where(combined)[0]
    hit_t = list(tr["epoch"].iloc[hit_idx])
    da = tr["da_km"].to_numpy(float)
    pad = pd.Timedelta(hours=EVIDENCE_PAD_H)

    l2_times = {}
    for ch, v in (l2_raw or {}).items():
        idx = np.asarray(v.get("events", []), int)
        idx = idx[(idx >= 0) & (idx < len(df))]
        l2_times[ch] = df["epoch"].iloc[idx].to_numpy() if len(idx) else np.array([], "datetime64[ns]")
    drag_t = None
    if drag_df is not None and len(drag_df) and not bool(drag_df["reentry"].iloc[0]):
        drag_t = drag_df.loc[drag_df["drag_resid_da"].abs() > DRAG_EVENT_KM, "epoch"]
    fus_t = None
    if fusion_df is not None and len(fusion_df):
        fus_t = fusion_df.loc[fusion_df["fusion"] >= float(fusion_df.attrs.get("thr", 1.1)), "epoch"]
    ml_t = ml_df.loc[ml_df["flag"], "epoch"] if ml_df is not None and len(ml_df) else None

    def _any_in(ts, lo, hi) -> bool:
        if ts is None or not len(ts):
            return False
        ts = pd.to_datetime(pd.Series(ts), utc=True)
        return bool(((ts >= lo) & (ts <= hi)).any())

    events = []
    for no, grp in enumerate(_merge_groups(hit_t), start=1):
        rows = hit_idx[grp]
        t0, t1 = hit_t[grp[0]], hit_t[grp[-1]]
        lo, hi = t0 - pad, t1 + pad
        k_main = rows[int(np.argmax(np.abs(da[rows])))]
        # 事件淨 Δa：事件首個候選轉換之前 → 末個候選轉換之後，中間未被標記的轉換也算進去
        net = float(da[rows[0]:rows[-1] + 1].sum())
        big = np.abs(da[rows]) > 1.0
        spike = (big.sum() >= 2 and (da[rows][big] > 0).any() and (da[rows][big] < 0).any()
                 and abs(net) < 0.2 * float(np.abs(da[rows]).max()))
        ev = []
        if _any_in(drag_t, lo, hi):
            ev.append("drag")
        if _any_in(fus_t, lo, hi):
            ev.append("fusion")
        if _any_in(ml_t, lo, hi):
            ev.append("ml")
        n_l2 = sum(_any_in(t, lo, hi) for t in l2_times.values())
        if n_l2 >= 2:
            ev.append("l2")
        quality = (STATUS_SPIKE if spike else
                   STATUS_NOISE if float(np.abs(da[rows]).max()) < NOISE_KM else "")
        level = STATUS_MULTI if len(ev) >= 2 else (STATUS_SINGLE if ev else STATUS_RULE_ONLY)
        events.append({
            "no": no, "t_start": t0, "t_end": t1, "n_flags": len(rows),
            "main_epoch": tr["epoch"].iloc[k_main], "main_da": float(da[k_main]), "net_da": net,
            "evidence": ev, "n_l2_channels": int(n_l2),
            "channel_level": level, "quality_note": quality,
            "status": quality or level,          # 舊欄位（API 相容）：有複核註記時以註記為準
        })
    return events


def _episode_count(ts: pd.DataFrame | None, kind: str) -> int | None:
    """阻力殘差／融合序列依 detection_timeline 規則（48 小時合併）的事件數；無序列回傳 None。"""
    if ts is None or not len(ts):
        return None
    try:
        import detection_timeline as dtl
        return len(dtl.merge_episodes(ts, kind))
    except Exception as e:
        logger.warning("事件合併計數失敗：%s", e)
        return None


def _drag_episode_is_accum(drag_df: pd.DataFrame, rp: dict) -> bool:
    """殘差事件是否為「阻力預期累積」：事件內每筆超門檻轉換都是實測 Δa 很小、殘差主要來自阻力預期。
    預期值隨轉換時長累積，軌道維持中的衛星遇長 TLE 空窗時，實測不動也會超門檻（NORAD 53056：
    2026-10-18 空窗 36 小時，實測 −0.021 km、預期 −0.518 km，殘差 0.498 km），這不是離散變化。"""
    if "da_km" not in drag_df:
        return False
    day = drag_df["epoch"].dt.date.astype(str)
    sub = drag_df[(day >= rp["d0"]) & (day <= rp["d1"]) & (drag_df["drag_resid_da"].abs() > DRAG_EVENT_KM)]
    return len(sub) > 0 and bool((sub["da_km"].abs() < DRAG_ACCUM_RATIO * sub["drag_resid_da"].abs()).all())


def _drag_only_episodes(drag_df: pd.DataFrame | None, events: list[dict]) -> tuple[list[str], list[str]]:
    """阻力殘差事件中，與任何候選事件（起訖前後 EVIDENCE_PAD_H 小時）都不重疊者的日期，
    分成 (實測有變化, 阻力預期累積) 兩組。主判是 L1，但 L1 的高度自適應門檻會漏掉分成數筆、
    單筆未達門檻的小幅抬升（NORAD 66666：06-24、10-06 單筆約 +0.55 km、門檻約 0.73–0.88 km），
    主頁須明示，不能讓讀者以為候選事件表就是全部值得看的變化（2026-10-29）。"""
    if drag_df is None or not len(drag_df):
        return [], []
    try:
        import detection_timeline as dtl
        reps = dtl.merge_episodes(drag_df, "drag")
    except Exception:
        return [], []
    pad = pd.Timedelta(hours=EVIDENCE_PAD_H)
    alone = [rp for rp in reps if not any(e["t_start"] - pad <= rp["epoch"] <= e["t_end"] + pad for e in events)]
    day = lambda rp: str(pd.Timestamp(rp["epoch"]).date())
    return ([day(rp) for rp in alone if not _drag_episode_is_accum(drag_df, rp)],
            [day(rp) for rp in alone if _drag_episode_is_accum(drag_df, rp)])


# ── R3：事件評估（類型／雜訊基線 SNR／根數同步／證據等級／建議行動）與連續機動段 ──────
# 2026-10-30 第三輪審閱：「8 次候選事件」會被讀成「8 次可能機動」；連續爬升被切成數個離散
# 事件會低估活動強度；Δa 沒有雜訊基線無法跨星比較。以下全部只用本期 TLE 轉換重算，不引入新資料。
SNR_WIN_D = 45            # 雜訊基線：事件前後各 45 天（共約 90 天）未標記轉換
SIGMA_FLOOR_KM = 0.001    # 基線下限 1 m，避免近乎無雜訊的序列 SNR 爆量
SNR_HIGH, SNR_MED = 20.0, 5.0
SEG_MIN_SPAN_D, SEG_MIN_ACTIVE_D, SEG_SAME_SIGN = 2.0, 3, 0.8
JUMP_MAX_SPAN_D = 1.5
CAMPAIGN_GAP_D = 30.0     # 同向連續機動段之間相隔 ≤ 30 天視為同一段機動活動
CAMPAIGN_MIN_KM = 10.0    # 非連續型事件需 |淨 Δa| ≥ 10 km 才併入機動活動
ELEM_K = 6.0              # 根數同步異常：|Δx − 中位數| > 6 × 穩健標準差
E3_BIG_KM = 10.0          # |淨 Δa| ≥ 10 km 且顯著性高即列 E3（不論輔助通道數）
FOCUS_MIN_KM = 1.0        # 主頁「重點複核」：E2／E3，或 |淨 Δa| ≥ 1 km
SYM_PAIR_D, SYM_PAIR_TOL = 30.0, 0.15   # 對稱升降：30 天內反向、|淨 Δa| 相差 ≤ 15%、量級 ≥ 10 km
INC_JUMP_DEG = 0.2        # 單筆 |Δi| 超過此值，疑似他物件根數（編目交叉標記）
TYPE_JUMP, TYPE_SEG, TYPE_MULTI = "單次跳變", "連續機動段", "多筆變化"
# R5（2026-10-30 第五輪審閱）：回跳型態不再與低顯著性同列 E1——可能是資料問題，也可能是真實劇烈變化
# （OBJECT H #2：SNR 522、四通道一致、單筆 −13.6 km），改列 D「資料品質待查」並附資料確認後的等級
GRADE_TEXT = {"D": "D 資料品質待查", "E1": "E1 待觀察", "E2": "E2 人工複核", "E3": "E3 高優先"}
GRADE_RANK = {"D": 0, "E3": 1, "E2": 2, "E1": 3}
ACTION_SPIKE = "核查資料品質（回跳型態）"
_ELEM_COLS = (("di_deg", "Δi"), ("de", "Δe"), ("draan_res_deg", "ΔΩ"))
# 事件狀態（與證據等級分開）：「已排除資料異常」只由人工複核後更新，報表不自動給
STATE_DQ, STATE_LOWSIG, STATE_WEAK, STATE_CAND, STATE_EXCL = (
    "資料品質待查", "低顯著性待觀察", "證據不足待觀察", "候選機動", "已排除資料異常")
P2_MAIN_MAX = 6           # 主表 P2 排程複核最多列 6 項，其餘見完整清單（D／P1 不設上限）
SK_GAP_D, SK_MIN_N = 10.0, 3   # GEO 東西位置保持段：同向、編號相鄰、相隔 ≤ 10 天、至少 3 個事件
NS_GAP_D = 30.0           # GEO 南北位置保持線索：Δi 同步事件相隔 ≤ 30 天合為一組
HIGH_ORBIT_KM = 2000.0    # 平均高度以上，阻力殘差通道改稱「攝動殘差」（大氣阻力可忽略）
LOW_CONF_P1_KM = 1.0      # 低置信複核項：殘差峰值 ≥ 1 km 列 P1，其餘 P2
REVIEW_DUE = "下次接近評估前"


def _robust_sigma(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) >= 5 else float("nan")


def assess_events(events: list[dict], tr: pd.DataFrame, combined, drag_df: pd.DataFrame | None = None,
                  in_domain: bool = True) -> None:
    """就地為每個事件補上 R3 評估欄位。SNR＝|事件淨 Δa| ÷ (σΔa·√k)：σΔa 為事件前後
    SNR_WIN_D 天內「未被標記」相鄰轉換 Δa 的穩健標準差（1.4826·MAD），k 為事件涵蓋的轉換數
    （淨 Δa 是 k 筆轉換的加總，隨機雜訊依 √k 累積）。"""
    if not events:
        return
    combined = np.asarray(combined, bool)
    ep = pd.to_datetime(tr["epoch"])
    da = tr["da_km"].to_numpy(float)
    win = pd.Timedelta(days=SNR_WIN_D)
    dt_d = tr["dt_h"].to_numpy(float) / 24 if "dt_h" in tr else np.zeros(len(tr))
    resid = None
    if drag_df is not None and len(drag_df):
        s = drag_df.drop_duplicates("epoch", keep="last").set_index("epoch")["drag_resid_da"]
        resid = s.reindex(ep).to_numpy(float)
    for e in events:
        t0, t1 = pd.Timestamp(e["t_start"]), pd.Timestamp(e["t_end"])
        inside = ((ep >= t0) & (ep <= t1)).to_numpy()
        near = ((ep >= t0 - win) & (ep <= t1 + win)).to_numpy() & ~combined
        sig = _robust_sigma(da[near])
        if not np.isfinite(sig):
            sig = _robust_sigma(da[~combined])
        sig = max(sig if np.isfinite(sig) else SIGMA_FLOOR_KM, SIGMA_FLOOR_KM)
        k = max(int(inside.sum()), 1)
        snr = abs(e["net_da"]) / (sig * np.sqrt(k))
        flagged = inside & combined
        fl_da = da[flagged]
        same = float(np.mean(np.sign(fl_da) == np.sign(e["net_da"]))) if len(fl_da) else 0.0
        span_d = (t1 - t0).total_seconds() / 86400
        active = len(set(ep[flagged].dt.date))
        if span_d >= SEG_MIN_SPAN_D and active >= SEG_MIN_ACTIVE_D and same >= SEG_SAME_SIGN:
            ev_type = TYPE_SEG
        elif span_d <= JUMP_MAX_SPAN_D:
            ev_type = TYPE_JUMP
        else:
            ev_type = TYPE_MULTI
        elems = []
        for col, lab in _ELEM_COLS:
            if col not in tr:
                continue
            x = tr[col].to_numpy(float)
            s = _robust_sigma(x[near])
            if np.isfinite(s) and s > 0 and (np.abs(x[flagged] - np.nanmedian(x[near])) > ELEM_K * s).any():
                elems.append(lab)
        sigf = "高" if snr >= SNR_HIGH else ("中" if snr >= SNR_MED else "低")
        # 根數同步只作資訊欄、不進等級：平面內推進本來就會連帶改變 e，Δa 也會改變節點進動率
        # 而反映在 ΔΩ 殘差上，五星實測幾乎每個事件都觸發，不構成獨立佐證
        # R4（2026-10-30 第四輪審閱）：量級極大（|淨 Δa| ≥ E3_BIG_KM）但輔助通道少的事件不應低於
        # 1–2 km 的多通道事件（NORAD 67689：+122.7 km 原列 E2、+2.4 km 反列 E3）
        nch = len(e["evidence"])
        model_ch = bool({"fusion", "ml"} & set(e["evidence"]))
        big = abs(e["net_da"]) >= E3_BIG_KM
        # R7：E3 判定依據分開記錄（rule＝連續機動段或 |淨 Δa| ≥ E3_BIG_KM；ml_assisted＝靠 ≥3 類輔助通道且含
        # ML／融合）。ML 窗口模型與融合評分器只以 Starlink 訓練，非 Starlink 衛星（in_domain=False）之
        # ml_assisted E3 改列 E2 並標 ml_capped——審查意見：未經非 Starlink 真值驗證之模型不應決定 E3。
        e3_basis, ml_capped = None, False
        if e["quality_note"] == STATUS_NOISE or sigf == "低":
            base = "E1"
        elif sigf == "高" and (ev_type == TYPE_SEG or big):
            base, e3_basis = "E3", "rule"
        elif sigf == "高" and nch >= 3 and model_ch:
            if in_domain:
                base, e3_basis = "E3", "ml_assisted"
            else:
                base, ml_capped = "E2", True
        elif nch >= 2:
            base = "E2"
        else:
            base = "E1"
        # R6：跨長 TLE 空窗的轉換，SNR 以一般轉換的雜訊為基準、不再適用，時間也無法定位。下降量可由阻力預期
        # 解釋者列 E1，其餘最高 E2（NORAD 58651 2026-09-18：跨 93 天 −1.28 km，阻力預期 −1.5～−1.8 km）
        gap_d, gap_drag = 0.0, False
        if flagged.any():
            k_gap = np.flatnonzero(flagged)[int(np.argmax(dt_d[flagged]))]
            gap_d = float(dt_d[k_gap])
            gap_drag = (gap_d >= GAP_LONG_D and resid is not None and da[k_gap] < 0
                        and abs(resid[k_gap]) < DRAG_ACCUM_RATIO * abs(da[k_gap]))
        if gap_drag:
            base = "E1"
        elif gap_d >= GAP_LONG_D and base == "E3":
            base, e3_basis = "E2", None
        spike = e["quality_note"] == STATUS_SPIKE
        grade = "D" if spike else base
        state = (STATE_DQ if spike else STATE_CAND if base in ("E2", "E3")
                 else STATE_LOWSIG if (sigf == "低" or e["quality_note"]) else STATE_WEAK)
        if spike:
            action = ACTION_SPIKE
        elif abs(e["main_da"]) >= BIG_JUMP_KM:
            action = "先查編目／定軌；確認後再評估碰撞風險"
        elif grade == "E3":
            action = "提高監視頻率；確認後再評估碰撞風險" if ev_type == TYPE_SEG else "立即複核；確認後再評估碰撞風險"
        elif ml_capped:
            action = "優先人工複核（ML 輔助）"
        else:
            action = "人工複核" if grade == "E2" else "觀察"
        e.update(span_d=span_d, active_days=active, rate_km_d=e["net_da"] / span_d if span_d >= 0.5 else None,
                 sigma_km=sig, snr=float(snr), significance=sigf, same_sign=same, elements=elems,
                 ev_type=ev_type, grade=grade, grade_if_ok=base, state=state, action=action,
                 gap_d=gap_d, gap_drag=gap_drag, e3_basis=e3_basis, ml_capped=ml_capped)


def _sma_span(df: pd.DataFrame, t0, t1) -> tuple[float, float, float]:
    """t0 之前最後一筆 TLE 到 t1 之前（含）最後一筆 TLE 的 (半長軸差, 天數, 末筆半長軸)。"""
    ep, sma = df["epoch"], df["sma_km"].to_numpy(float)
    i0 = max(int((ep < t0).sum()) - 1, 0)
    i1 = max(int((ep <= t1).sum()) - 1, 0)
    days = max((pd.Timestamp(t1) - pd.Timestamp(ep.iloc[i0])).total_seconds() / 86400, 1e-6)
    return float(sma[i1] - sma[i0]), days, float(sma[i1])


def build_segments(events: list[dict], df: pd.DataFrame) -> list[dict]:
    """連續機動段（maneuver campaign）：時間相鄰、淨 Δa 同向，且各自為「連續機動段」型或
    |淨 Δa| ≥ CAMPAIGN_MIN_KM 的事件，彼此相隔 ≤ CAMPAIGN_GAP_D 天者合為一段（至少 2 個事件）。
    累計 Δa 取段首事件之前最後一筆 TLE 到段末事件最後一筆 TLE 的半長軸差（含段間漂移）。"""
    ok = [e for e in events if not e["quality_note"]
          and (e.get("ev_type") == TYPE_SEG or abs(e["net_da"]) >= CAMPAIGN_MIN_KM)]
    groups: list[list[dict]] = []
    for e in ok:
        g = groups[-1] if groups else None
        if (g and np.sign(e["net_da"]) == np.sign(g[-1]["net_da"])
                and e["no"] == g[-1]["no"] + 1
                and (pd.Timestamp(e["t_start"]) - pd.Timestamp(g[-1]["t_end"])).days <= CAMPAIGN_GAP_D):
            g.append(e)
        else:
            groups.append([e])
    out = []
    for g in groups:
        if len(g) < 2:
            continue
        t0, t1 = pd.Timestamp(g[0]["t_start"]), pd.Timestamp(g[-1]["t_end"])
        cum, days, sma_end = _sma_span(df, t0, t1)
        grade = min((e.get("grade", "E1") for e in g), key=lambda x: GRADE_RANK[x])
        out.append({"no": len(out) + 1, "events": [e["no"] for e in g], "t_start": t0, "t_end": t1,
                    "cum_da": cum, "sum_net": float(sum(e["net_da"] for e in g)), "days": days,
                    "rate_km_d": cum / days, "sma_end": sma_end, "grade": grade,
                    "high": grade == "E3" or abs(cum) >= E3_BIG_KM})
        for e in g:
            e["segment"] = out[-1]["no"]
    return out


def build_station_keeping(events: list[dict], df: pd.DataFrame, tr: pd.DataFrame, orbit_class: str) -> list[dict]:
    """GEO 位置保持節奏（R5，USA 270：72 個事件幾乎都是單筆小幅 Δa，離散列出看不出營運節奏）。
    東西（EW）：不屬機動段、無複核註記與編目疑點、|淨 Δa| < CAMPAIGN_MIN_KM 的事件，編號相鄰、同向、
    相隔 ≤ SK_GAP_D 天者合為一段（≥ SK_MIN_N 個）。同向小幅 Δa 的累積可能是經度漂移本身、也可能是
    小幅推進序列；方向轉折處才是候選的東西修正時點。南北（NS）：根數一致性註記含 Δi 的事件，
    相隔 ≤ NS_GAP_D 天合為一組，只作線索。非 GEO 回傳空清單。"""
    if orbit_class != "GEO" or not events:
        return []
    ok = lambda e: (not e.get("segment") and not e["quality_note"] and not e.get("catalog_suspect")
                    and abs(e["net_da"]) < CAMPAIGN_MIN_KM)
    runs: list[list[dict]] = []
    for e in events:
        if not ok(e):
            runs.append([])
            continue
        g = runs[-1] if runs else None
        if (g and np.sign(e["net_da"]) == np.sign(g[-1]["net_da"]) and e["no"] == g[-1]["no"] + 1
                and (pd.Timestamp(e["t_start"]) - pd.Timestamp(g[-1]["t_end"])).total_seconds() <= SK_GAP_D * 86400):
            g.append(e)
        else:
            runs.append([e])
    ns_runs: list[list[dict]] = []
    for e in events:
        if "Δi" not in e.get("elements", []) or e["quality_note"] or e.get("catalog_suspect"):
            continue
        if ns_runs and (pd.Timestamp(e["t_start"]) - pd.Timestamp(ns_runs[-1][-1]["t_end"])).days <= NS_GAP_D:
            ns_runs[-1].append(e)
        else:
            ns_runs.append([e])
    ep = pd.to_datetime(tr["epoch"])
    di = tr["di_deg"].to_numpy(float) if "di_deg" in tr else np.zeros(len(tr))
    out = []
    for kind, groups in (("EW", [g for g in runs if len(g) >= SK_MIN_N]), ("NS", ns_runs)):
        for k, g in enumerate(groups, 1):
            t0, t1 = pd.Timestamp(g[0]["t_start"]), pd.Timestamp(g[-1]["t_end"])
            cum, days, _ = _sma_span(df, t0, t1)
            cum_di = float(np.nansum(di[((ep >= t0) & (ep <= t1)).to_numpy()]))
            sk = {"id": f"{kind}{k}", "kind": kind, "events": [e["no"] for e in g], "t_start": t0, "t_end": t1,
                  "cum_da": cum, "cum_di": cum_di, "days": days, "rate_km_d": cum / days,
                  "direction": ("抬升" if cum > 0 else "降低") if kind == "EW" else
                               ("Δi 增" if cum_di > 0 else "Δi 減")}
            out.append(sk)
            for e in g:
                e.setdefault("sk", []).append(sk["id"])
    return out


def catalog_checks(df: pd.DataFrame, tr: pd.DataFrame, combined, events: list[dict]) -> dict:
    """編目一致性與「主要疑點」：大幅跳變應先排除編目交叉標記與定軌更新，再進入機動解釋
    （2026-10-30 第四輪審閱，COSMOS 2612 的 +46.5／−47.9 km 對稱升降）。
    全期檢查：line1／line2 衛星編號不一致筆數、國際編目號種類與改變時點。
    逐事件：e["checks"]＝主要疑點清單；e["catalog_suspect"]＝疑似編目／根數族群跳變（建議行動前置核對）。
    不改證據等級——編目疑點只能由原始資料核對排除，不能由本報表判定。"""
    summ = {"catnum_mismatch": 0, "intl_ids": [], "intl_changes": []}
    mismatch_t: list = []
    if "line1" in df and "line2" in df:
        l1 = df["line1"].fillna("").astype(str)
        l2 = df["line2"].fillna("").astype(str)
        ok = (l1.str.len() >= 17) & (l2.str.len() >= 7)
        mm = (l1.str[2:7].str.strip() != l2.str[2:7].str.strip()) & ok
        summ["catnum_mismatch"] = int(mm.sum())
        mismatch_t = [pd.Timestamp(t) for t in df.loc[mm, "epoch"]]
        intl = l1.str[9:17].str.strip().where(ok)
        summ["intl_ids"] = sorted(set(intl.dropna()) - {""})
        prev = intl.shift()
        chg = intl.notna() & prev.notna() & (intl != prev)
        summ["intl_changes"] = [pd.Timestamp(t) for t in df.loc[chg, "epoch"]]
    combined = np.asarray(combined, bool)
    ep = pd.to_datetime(tr["epoch"])
    di = np.abs(tr["di_deg"].to_numpy(float)) if "di_deg" in tr else np.zeros(len(tr))
    day = pd.Timedelta(days=1)
    for e in events:
        t0, t1 = pd.Timestamp(e["t_start"]), pd.Timestamp(e["t_end"])
        sel = (((ep >= t0) & (ep <= t1)).to_numpy()) & combined
        ck, sus, hard = [], False, []
        if e["quality_note"] == STATUS_SPIKE:
            g_ok = e.get("grade_if_ok")
            ck.append("回跳型態" + (f"（資料確認後 {g_ok}）" if g_ok in ("E2", "E3") else ""))
        if e.get("gap_d", 0) >= GAP_LONG_D:
            ck.append(f"跨 {e['gap_d']:.0f} 天 TLE 空窗" + ("（Δa 與阻力預期相當）" if e.get("gap_drag") else "（時間無法定位）"))
        if abs(e["main_da"]) >= BIG_JUMP_KM:
            ck.append(f"單筆 ≥{BIG_JUMP_KM:.0f} km 大幅跳變")
            sus = True
        dimax = float(np.nanmax(di[sel])) if sel.any() else 0.0
        if dimax > INC_JUMP_DEG:
            ck.append(f"單筆 |Δi| {dimax:.2f}°（疑似他物件根數）")
            hard.append(f"單筆 |Δi| {dimax:.2f}°")
            sus = True
        if any(t0 - day <= t <= t1 + day for t in summ["intl_changes"]):
            ck.append("國際編目號改變")
            hard.append("國際編目號改變")
            sus = True
        if any(t0 - day <= t <= t1 + day for t in mismatch_t):
            ck.append("line1／line2 編號不一致")
            hard.append("line1／line2 編號不一致")
            sus = True
        e["checks"], e["catalog_suspect"], e["catalog_hard"] = ck, sus, hard
    # 對稱升降：兩事件反向、量級相近且時間相近，常見於編目交叉標記（也可能是真實的升軌—降軌相位調整）
    big = [e for e in events if abs(e["net_da"]) >= E3_BIG_KM and not e["quality_note"]]
    for a in big:
        for b in big:
            if (b["no"] > a["no"] and np.sign(a["net_da"]) != np.sign(b["net_da"])
                    and abs(abs(a["net_da"]) - abs(b["net_da"])) <= SYM_PAIR_TOL * max(abs(a["net_da"]), abs(b["net_da"]))
                    and (pd.Timestamp(b["t_start"]) - pd.Timestamp(a["t_end"])).days <= SYM_PAIR_D):
                for x, y in ((a, b), (b, a)):
                    x["checks"].insert(0, f"與 #{y['no']} 對稱升降")
                    x["catalog_suspect"] = True
    for e in events:
        if e.get("ev_type") == TYPE_SEG:
            e["checks"].append("連續同向 Δa")
        if len(e["evidence"]) >= 3:
            e["checks"].append(f"多通道一致（{ev_channels(e, sep='＋')}）")
        if "Δi" in e.get("elements", []) and not any("Δi" in c for c in e["checks"]):
            e["checks"].append("Δi 同步（平面外分量）")
        if e["catalog_suspect"] and not e["action"].startswith(("先", "核查")):
            e["action"] = "先查編目＋" + e["action"]
        # 編目複核紀錄（R5）：狀態由人工複核後更新為「已排除／疑似交叉標記／維持候選」；
        # 自動檢查命中編號類硬證據者暫停機動解釋，僅有大幅跳變／對稱升降者暫列候選機動
        e["catalog_review"] = None
        if e["catalog_suspect"]:
            e["catalog_review"] = {
                "trigger": "、".join(c for c in e["checks"] if "大幅" in c or "對稱" in c or "°" in c
                                    or "編目" in c or "編號" in c),
                "status": "待檢查",
                "result": "、".join(e["catalog_hard"]) or "—",
                "interp": "暫停機動解釋" if e["catalog_hard"] else "暫列候選機動"}
            if e["catalog_hard"]:
                e["state"] = STATE_DQ
    return summ


def _operator_prior(norad: int, name: str | None) -> dict | None:
    """知名目標的營運先驗（公開營運模式的一般知識，非本期資料證據）：只調整「待驗證解釋」
    的列舉內容與順序，不影響事件判定與證據等級。"""
    u = (name or "").upper()
    if int(norad) == 25544 or u.startswith("ISS"):
        return {"who": "ISS",
                "text": "ISS 長期在軌，須定期再升軌（reboost）補償大氣阻力；半長軸抬升事件應優先考慮定期再升軌／"
                        "軌道維持，其次為避碰機動。",
                "short": "ISS 須定期再升軌補償大氣阻力，抬升事件宜優先視為疑似定期再升軌",
                "raise": "定期再升軌（軌道維持）、避碰機動、資料異常"}
    if "STARLINK" in u:
        return {"who": "Starlink",
                "text": "Starlink 衛星入軌後會分段爬升至工作軌道，運行期間另有相位調整、避碰機動，壽終前主動降軌離軌；"
                        "連續同向抬升應優先考慮入軌後爬升或相位調整，連續降低應優先考慮離軌準備。",
                "short": "Starlink 連續同向抬升宜優先考慮入軌後分段爬升或相位調整，連續降低宜優先考慮離軌準備",
                "raise": "入軌後分段爬升至工作軌道、相位調整、資料異常",
                "lower": "離軌準備或主動降軌、避碰機動、資料異常"}
    if "FORMOSAT" in u:
        return {"who": "FORMOSAT",
                "text": "FORMOSAT 系列為任務型衛星，半長軸變化應優先考慮軌道維持（補償阻力）或任務性軌道調整。",
                "short": "FORMOSAT 系列半長軸變化宜優先考慮軌道維持或任務性軌道調整",
                "raise": "軌道維持（補償阻力）、任務性軌道調整、資料異常"}
    return None


def suppression_stats(per_strategy: dict, tr: pd.DataFrame, drag_df: pd.DataFrame | None) -> dict | None:
    """L1 抑制規則（P1 單調衰減／P3 高 B*）的漏檢風險揭露：抑制旗標涵蓋多少轉換、其中有多少
    原本已被偵測規則標記而被扣除、被抑制轉換的 |Δa| 分布，以及被抑制轉換中阻力殘差仍超過門檻者。
    抑制能壓低阻力誤報，但也可能壓掉衰減中夾帶的小幅抬升（2026-10-30 第三輪審閱）。"""
    n = len(tr)
    if not per_strategy or not n:
        return None

    def g(k):
        v = per_strategy.get(k)
        return np.zeros(n, bool) if v is None else np.asarray(v, bool)

    sup = g("P1_suppress") | g("P3_suppress")
    det = g("P2") | g("P5") | g("P6") | g("P4") | g("other(di/de/dΩ)")
    removed = det & sup
    da = np.abs(tr["da_km"].to_numpy(float))
    out = {"n_tr": n, "n_p1": int(g("P1_suppress").sum()), "n_p3": int(g("P3_suppress").sum()),
           "n_sup": int(sup.sum()), "n_removed": int(removed.sum()),
           "sup_absda_p50": float(np.median(da[sup])) if sup.any() else None,
           "sup_absda_p95": float(np.percentile(da[sup], 95)) if sup.any() else None,
           "sup_absda_max": float(da[sup].max()) if sup.any() else None,
           "n_sup_drag_hi": None}
    if drag_df is not None and len(drag_df) and sup.any():
        try:
            left = pd.DataFrame({"epoch": pd.to_datetime(tr["epoch"], utc=True)[sup]}).sort_values("epoch")
            right = drag_df[["epoch", "drag_resid_da"]].copy()
            right["epoch"] = pd.to_datetime(right["epoch"], utc=True)
            left["epoch"] = left["epoch"].astype(right["epoch"].dtype)
            m = pd.merge_asof(left, right.sort_values("epoch"), on="epoch", direction="nearest",
                              tolerance=pd.Timedelta(minutes=1))
            out["n_sup_drag_hi"] = int((m["drag_resid_da"].abs() > DRAG_EVENT_KM).sum())
        except Exception as e:
            logger.warning("抑制點阻力殘差比對失敗：%s", e)
    return out


def low_conf_items(drag_df: pd.DataFrame | None, fus_ts: pd.DataFrame | None, events: list[dict],
                   high_orbit: bool = False, df: pd.DataFrame | None = None,
                   l2_raw: dict | None = None, min_net_km: float | None = None,
                   in_domain: bool = True, suppressed: dict | None = None) -> list[dict]:
    """低置信複核項：阻力殘差事件與 L3 融合超門檻事件中，未與任何候選事件重疊者（主頁無候選事件時
    以表格列出，避免「0 次」被讀成「沒有任何值得看的變化」——2026-10-30 第三輪審閱，NORAD 58214）。
    R5：每項帶優先序（殘差峰值 ≥ LOW_CONF_P1_KM 列 P1）、複核期限與狀態，形成可追蹤的複核清單。
    R7：非 Starlink 衛星（in_domain=False）之 L3 融合超門檻時點不列入——2026-11-15 以 IDS 營運方認證
    安靜期驗證（docs/validate_lowconf_full.py），9 顆非 Starlink 衛星 38 項全數落在安靜期、補回點火 0 次；
    略去之筆數記入 suppressed["fusion_non_starlink"]，供報表交代。"""
    try:
        import detection_timeline as dtl
    except Exception:
        return []
    pad = pd.Timedelta(hours=EVIDENCE_PAD_H)
    out = []
    for ts, kind, src, unit in ((drag_df, "drag", _drag_label(high_orbit), "km"),
                                (fus_ts, "fusion", "L3 融合評分器", "")):
        if ts is None or not len(ts) or (kind == "drag" and bool(ts["reentry"].iloc[0])):
            continue
        for rp in dtl.merge_episodes(ts, kind):
            if any(e["t_start"] - pad <= rp["epoch"] <= e["t_end"] + pad for e in events):
                continue
            if kind == "fusion" and not in_domain:
                if suppressed is not None:
                    suppressed["fusion_non_starlink"] = suppressed.get("fusion_non_starlink", 0) + 1
                continue
            v = float(rp["val"])
            accum = kind == "drag" and _drag_episode_is_accum(ts, rp)
            out.append({"source": src + ("（預期累積）" if accum else ""), "epoch": pd.Timestamp(rp["epoch"]),
                        "value": f"{v:.3f} km" if unit else f"{v:.3f}", "peak": v,
                        "priority": "P1" if unit and abs(v) >= LOW_CONF_P1_KM and not accum else "P2",
                        "due": REVIEW_DUE, "status": "待複核"})
    out += _l2_only_items(df, l2_raw, events, min_net_km=min_net_km)
    return sorted(out, key=lambda x: x["epoch"])


L2_LABEL = {"cusum": "CUSUM", "bocpd": "BOCPD", "ssa": "SSA", "mad3sig": "MAD3σ"}


L2_BG_DAYS = 7.0          # 背景變化率（阻力衰減）：本段前後各 7 天 sma 對時間之線性斜率
L2_MAX_SPAN_D = 3.0       # 單一 L2 觸發段最長 3 天：持續數週的漂移（如高 B* 衛星之快速衰減）會被 48 小時
                          # 連鎖串成長鏈、淨 Δa 虛增（2026-11-15 HAISHAO 1 實例：三週連續下降被列為 −57 km），
                          # 多日漂移交由阻力殘差與連續機動段處理


def _l2_only_items(df: pd.DataFrame | None, l2_raw: dict | None, events: list[dict],
                   min_net_km: float | None = None) -> list[dict]:
    """L2 統計變點補漏（R7）：L1 規則未標記的時段，若 ≥2 種 L2 方法在 48 小時連鎖內同時觸發，
    且扣除背景變化率（主要為阻力衰減，取前後 7 天、不含候選事件之線性斜率）後之淨 Δa，
    達該星高顯著下限（min_net_km，20σ）與 L1 單步門檻（P2）兩者之較大值，
    列為低置信複核項（P2）。L1 以單步變化量判定，對分散在數筆轉換的變化較不敏感；此項讓這類
    「單步不大、累積明顯」的變化進入複核清單，但不併入候選事件、不影響證據等級。
    只要求 ≥2 種方法同時觸發時，15 顆測試衛星共約 500 項，多為雜訊；僅以 20σ 為下限仍有約 100 項，
    多為高阻力衛星衰減率變動。以 L1 單步門檻為下限，對應「每步皆未達 L1 門檻、合計已超過」之漏偵情境。"""
    if df is None or not l2_raw or not len(df) or min_net_km is None or not np.isfinite(min_net_km):
        return []
    hits = []
    for ch, v in l2_raw.items():
        idx = np.asarray(v.get("events", []), int)
        for i in idx[(idx >= 0) & (idx < len(df))]:
            hits.append((pd.Timestamp(df["epoch"].iloc[i]), ch, int(i)))
    if not hits:
        return []
    hits.sort(key=lambda h: h[0])
    pad = pd.Timedelta(hours=EVIDENCE_PAD_H)
    gap = pd.Timedelta(hours=48)
    span = pd.Timedelta(days=L2_MAX_SPAN_D)
    groups, cur = [], [hits[0]]
    for h in hits[1:]:
        if h[0] - cur[-1][0] <= gap and h[0] - cur[0][0] <= span:
            cur.append(h)
        else:
            groups.append(cur)
            cur = [h]
    groups.append(cur)
    sma = df["sma_km"].to_numpy(float)
    tday = (df["epoch"] - df["epoch"].iloc[0]).dt.total_seconds().to_numpy(float) / 86400.0
    ep = df["epoch"]
    in_event = np.zeros(len(df), bool)       # 背景斜率不採候選事件前後之資料，避免機動本身拉偏背景
    for e in events:
        in_event |= ((ep >= e["t_start"] - pad) & (ep <= e["t_end"] + pad)).to_numpy()
    out = []
    for g in groups:
        chans = sorted({h[1] for h in g}, key=list(L2_LABEL).index)
        if len(chans) < 2:
            continue
        t0, t1 = g[0][0], g[-1][0]
        if any(e["t_start"] - pad <= t1 and t0 <= e["t_end"] + pad for e in events):
            continue
        rows = sorted({h[2] for h in g})
        lo, hi = max(rows[0] - 1, 0), rows[-1]
        # 背景變化率（km/天）：本段之前、之後各 L2_BG_DAYS 天分別做 sma 對時間之線性迴歸，取兩斜率平均。
        # 前後分開擬合：若合併成一條直線，本段內的高度跳變會被斜率吸收而抵銷訊號；
        # 兩側皆不跨越候選事件：跨越機動後高度位準不同，斜率失真（2026-11-15 SJ-26 01-22 實例）。
        t_lo, t_hi = tday[lo], tday[hi]
        b_lo = max([tday[ep <= e["t_end"] + pad].max() for e in events
                    if (ep <= e["t_end"] + pad).any() and tday[ep <= e["t_end"] + pad].max() < t_lo],
                   default=-np.inf)
        b_hi = min([tday[ep >= e["t_start"] - pad].min() for e in events
                    if (ep >= e["t_start"] - pad).any() and tday[ep >= e["t_start"] - pad].min() > t_hi],
                   default=np.inf)
        slopes = []
        for sel in (((tday >= max(t_lo - L2_BG_DAYS, b_lo)) & (tday < t_lo) & ~in_event),
                    ((tday > t_hi) & (tday <= min(t_hi + L2_BG_DAYS, b_hi)) & ~in_event)):
            if sel.sum() >= 4:
                slopes.append(float(np.polyfit(tday[sel], sma[sel], 1)[0]))
        bg_rate = float(np.mean(slopes)) if slopes else 0.0
        da = float(sma[hi] - sma[lo])
        floor = max(min_net_km, float(ms.DEFAULT_P2(np.array([sma[lo] - R_E]))[0]))
        net = da - bg_rate * (t_hi - t_lo)       # 扣除背景變化（阻力衰減）後之淨變化
        if abs(net) < floor:
            continue
        steps = np.diff(sma[lo:hi + 1]) if hi > lo else np.array([0.0])
        k = lo + 1 + int(np.argmax(np.abs(steps))) if hi > lo else rows[0]
        out.append({"source": "L2 統計變點（" + "＋".join(L2_LABEL.get(c, c) for c in chans) + "）",
                    "epoch": pd.Timestamp(df["epoch"].iloc[k]),
                    "value": f"{da:+.3f} km（扣除背景 {net:+.3f} km）", "peak": abs(net),
                    "priority": "P2", "due": REVIEW_DUE, "status": "待複核"})
    return out


LC_CASE_GAP_H = 72          # 低置信複核項相隔 ≤ 72 小時者合併為同一複核案件
LC_GAP_D = 2.0              # 項目前一筆 TLE 間隔 ≥ 2 天：標「資料缺口」
LC_BSTAR_HIGH = 5e-4        # 與 P3 之 B* 下限相同：標「高阻力」
LC_F107_HIGH = 150.0        # F10.7 ≥ 150 sfu：標「太陽活躍」


def annotate_low_conf(items: list[dict], df: pd.DataFrame, f107: dict | None) -> list[dict]:
    """R7：低置信複核項加診斷欄位並合併為複核案件（審查意見：以「項」計會高估人工複核量，且應能看出觸發原因）。
    每項加 tle_gap_d（與前一筆 TLE 間隔）、bstar、f107、tags；相隔 ≤ LC_CASE_GAP_H 者同屬一案件（case）。
    案件標「連續段」＝同案件 ≥3 項且跨度 > 3 天，常見於高阻力衛星之持續衰減。"""
    if not items:
        return items
    ep = df["epoch"]
    bst = df["bstar"].to_numpy(float) if "bstar" in df.columns else np.full(len(df), np.nan)
    for x in items:
        k = min(max(int((ep <= x["epoch"]).sum()) - 1, 0), len(df) - 1)     # 項目時點（含）之前最後一筆 TLE
        gap = float((ep.iloc[k] - ep.iloc[k - 1]).total_seconds() / 86400) if k >= 1 else np.nan
        b = float(bst[k]) if np.isfinite(bst[k]) else np.nan
        fv = (f107 or {}).get(pd.Timestamp(x["epoch"]).strftime("%Y-%m-%d"))
        fv = float(fv) if fv is not None and np.isfinite(fv) else np.nan
        tags = [t for t, c in (("資料缺口", np.isfinite(gap) and gap >= LC_GAP_D),
                               ("高阻力", np.isfinite(b) and b >= LC_BSTAR_HIGH),
                               ("太陽活躍", np.isfinite(fv) and fv >= LC_F107_HIGH)) if c]
        x.update(tle_gap_d=gap, bstar=b, f107=fv, tags=tags)
    items = sorted(items, key=lambda x: x["epoch"])
    cid, last = 0, None
    for x in items:
        if last is None or (x["epoch"] - last).total_seconds() / 3600 > LC_CASE_GAP_H:
            cid += 1
        x["case"] = f"K{cid}"
        last = x["epoch"]
    for c in {x["case"] for x in items}:
        mem = [x for x in items if x["case"] == c]
        if len(mem) >= 3 and (mem[-1]["epoch"] - mem[0]["epoch"]).days > 3:
            for x in mem:
                x["tags"] = x["tags"] + ["連續段"]
    return items


def _geodetic_alt_range(line1: str, line2: str, step_min: float = 0.5) -> tuple[float, float] | None:
    """SGP4 傳播一圈，取 WGS84 大地高度的最大／最小值。高度只與 (√(x²+y²), z) 有關，TEME 與地固座標
    只差繞 z 軸旋轉，故不需地球自轉換算。2026-10-30 以 NORAD 69673 09-24 TLE 驗證：612.3／589.1 km，
    與 KeepTrack Altitude History 的 610／587 km 相符（a(1±e) − R⊕ 只得 595.6／588.3 km——中緯度
    傾角下地球扁率使大地高度沿軌起伏約 21·sin²i km，KeepTrack 採的是大地高度極值）。"""
    try:
        from sgp4.api import Satrec
    except ImportError:
        return None
    s = Satrec.twoline2rv(line1, line2)
    t = np.arange(0.0, 2 * np.pi / s.no_kozai + step_min, step_min)
    err, rr, _ = s.sgp4_array(np.full(len(t), s.jdsatepoch), s.jdsatepochF + t / 1440.0)
    rr = rr[err == 0]
    if len(rr) < 10:
        return None
    a, f = 6378.137, 1 / 298.257223563
    e2 = f * (2 - f)
    p, z = np.hypot(rr[:, 0], rr[:, 1]), rr[:, 2]
    lat = np.arctan2(z, p * (1 - e2))
    for _ in range(5):
        n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1 - e2 * n / (n + h)))
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - n
    return float(h.max()), float(h.min())


def altitude_history(df: pd.DataFrame) -> dict | None:
    """遠地點／近地點高度歷史（2026-10-30，參考 KeepTrack Altitude History）：每 UTC 日取最後一筆 TLE。
    主值＝SGP4 傳播一圈的 WGS84 大地高度最大／最小（與 KeepTrack 同口徑）；另存 TLE 平均根數的
    a(1±e) − R⊕（*_mean_km）。缺 sgp4 或 TLE 文字時退回平均根數，definition 欄註明實際採用者。"""
    if df is None or len(df) < 2 or "eccentricity" not in df:
        return None
    cols = ["epoch", "sma_km", "eccentricity"] + [c for c in ("line1", "line2") if c in df]
    d = df[cols].dropna(subset=["sma_km", "eccentricity"]).copy()
    d["day"] = pd.to_datetime(d["epoch"]).dt.floor("D")
    d = d.groupby("day", as_index=False).last()
    if len(d) < 2:
        return None
    d["apogee_mean_km"] = d["sma_km"] * (1 + d["eccentricity"]) - R_E
    d["perigee_mean_km"] = d["sma_km"] * (1 - d["eccentricity"]) - R_E
    geo = None
    if "line1" in d and "line2" in d:
        try:
            geo = [_geodetic_alt_range(l1, l2) for l1, l2 in zip(d["line1"], d["line2"])]
        except Exception as e:
            logger.warning("大地高度計算失敗，改用平均根數：%s", e)
            geo = None
    if geo and all(g is not None for g in geo):
        d["apogee_km"], d["perigee_km"] = [g[0] for g in geo], [g[1] for g in geo]
        definition = "geodetic"
    else:
        d["apogee_km"], d["perigee_km"] = d["apogee_mean_km"], d["perigee_mean_km"]
        definition = "mean"
    return {"daily": d[["day", "epoch", "apogee_km", "perigee_km", "apogee_mean_km", "perigee_mean_km"]]
                     .reset_index(drop=True),
            "definition": definition,
            "d_apogee": float(d["apogee_km"].iloc[-1] - d["apogee_km"].iloc[0]),
            "d_perigee": float(d["perigee_km"].iloc[-1] - d["perigee_km"].iloc[0]),
            "apogee_range": (float(d["apogee_km"].min()), float(d["apogee_km"].max())),
            "perigee_range": (float(d["perigee_km"].min()), float(d["perigee_km"].max())),
            "n_days": len(d), "n_tle": len(df)}


def altitude_summary(r: dict) -> str:
    ah = r.get("alt_history")
    if not ah:
        return "TLE 不足，未計算遠地點／近地點高度歷史。"
    return (f"公開 TLE 推算之遠地點／近地點高度（{r['start_date']}～{r['end_date']}，{ah['n_tle']} 筆 TLE、每日一點共 "
            f"{ah['n_days']} 點）：整個時窗遠地點 {ah['d_apogee']:+.1f} km、近地點 {ah['d_perigee']:+.1f} km；"
            f"遠地點 {ah['apogee_range'][0]:.0f}–{ah['apogee_range'][1]:.0f} km、"
            f"近地點 {ah['perigee_range'][0]:.0f}–{ah['perigee_range'][1]:.0f} km。")


ALT_HISTORY_NOTE = ("高度＝每 UTC 日最後一筆 TLE 以 SGP4 傳播一圈之 WGS84 大地高度最大／最小值（與 KeepTrack "
                    "Altitude History 同口徑；地球扁率使中緯度軌道的大地高度沿軌起伏可達十餘公里）。"
                    "TLE 平均根數 a(1±e) − 6378.137 km 的數值另列於 CSV（apogee_mean_km／perigee_mean_km）。")
ALT_HISTORY_NOTE_MEAN = "高度＝a(1±e) − 6378.137 km（TLE 平均根數，每 UTC 日取最後一筆；本次未能以 SGP4 計算大地高度）。"


def alt_history_note(r: dict) -> str:
    ah = r.get("alt_history") or {}
    return ALT_HISTORY_NOTE if ah.get("definition") == "geodetic" else ALT_HISTORY_NOTE_MEAN


def _drag_label(high_orbit: bool, long: bool = False) -> str:
    """阻力殘差通道名稱：高軌（GEO 等）大氣阻力可忽略，殘差主要反映模型、定軌與 TLE 擬合差異。"""
    if high_orbit:
        return "NRLMSIS 模型殘差（高軌參考用）" if long else "攝動殘差"
    return "阻力殘差"


def detection_capability(tr: pd.DataFrame, combined, events: list[dict]) -> dict | None:
    """偵測能力（R5）：把「0 次候選事件」升級為「在本期雜訊與取樣條件下的偵測界限」。
    σΔa 中位數＝未標記轉換逐月穩健標準差的中位數；近 90 天 P95＝期末 90 天未標記轉換 |Δa| 的 95 百分位；
    單次可辨識量級＝SNR_HIGH × σΔa 中位數（單筆轉換，k＝1）；本期最大未列入事件之單筆 Δa＝不在任何事件
    起訖內的轉換中 |Δa| 最大者。"""
    if tr is None or len(tr) < 5:
        return None
    combined = np.asarray(combined, bool)
    ep = pd.to_datetime(tr["epoch"])
    da = tr["da_km"].to_numpy(float)
    base = pd.DataFrame({"m": ep.dt.strftime("%Y-%m"), "da": da})[~combined]
    sig_m = [s for _, g in base.groupby("m") if np.isfinite(s := _robust_sigma(g["da"].to_numpy(float)))]
    sig = max(float(np.median(sig_m)) if sig_m else _robust_sigma(da[~combined]), SIGMA_FLOOR_KM)
    if not np.isfinite(sig):
        return None
    in90 = (ep >= ep.iloc[-1] - pd.Timedelta(days=90)).to_numpy()
    last90 = in90 & ~combined
    # GEO 等幾乎每筆轉換都被標記的目標，未標記樣本太少：P95 改用近 90 天全部轉換並註明
    p95_all = last90.sum() < 5 and in90.sum() >= 5
    sel90 = in90 if p95_all else last90
    inside = np.zeros(len(tr), bool)
    for e in events:
        inside |= ((ep >= pd.Timestamp(e["t_start"])) & (ep <= pd.Timestamp(e["t_end"]))).to_numpy()
    out = {"sigma_med_m": sig * 1000, "n_months": len(sig_m), "n_unflagged": int((~combined).sum()),
           "p95_90d_m": float(np.percentile(np.abs(da[sel90]), 95)) * 1000 if sel90.sum() >= 5 else None,
           "p95_all": bool(p95_all), "min_detect_m": SNR_HIGH * sig * 1000, "max_unlisted": None}
    if (~inside).any():
        k = int(np.argmax(np.where(~inside, np.abs(da), -1)))
        out["max_unlisted"] = {"da": float(da[k]), "epoch": pd.Timestamp(ep.iloc[k])}
    return out


_STRATEGY_LABELS = {
    "P2": "P2 高度自適應 Δa 閾值",
    "P5": "P5 F10.7 太陽活動強度調整",
    "P6": "P6 星座／傾角族群基準倍率",
    "P4": "P4 相鄰窗口補充判定",
    "other(di/de/dΩ)": "其他根數（Δi／Δe）異常",
    "P1_suppress": "P1 單調衰減抑制（判為大氣阻力自然衰減）",
    "P3_suppress": "P3 高 B* 抑制（2026-11-15 起停用）",
}


def build_method_text(r: dict) -> str:
    """附錄 C「計數口徑與判定流程」：決定論、可逐項對照原始數字重現，不經 LLM。
    判定流程依實際程式寫：L1 主判、其餘通道只作輔助（舊版曾同時寫「L3 未跨門檻
    不列入落點」與「最終以 L1 為準」，兩段互相矛盾）。"""
    l1, l3, c, dq = r["l1"], r["l3"], r["counts"], r["data_quality"]
    sc = l1.get("strategy_counts", {})
    detect = [f"{_STRATEGY_LABELS[k]} {sc.get(k, 0)} 次" for k in ("P2", "P5", "P6", "P4", "other(di/de/dΩ)") if k in sc]
    suppress = [f"{_STRATEGY_LABELS[k]} {sc.get(k, 0)} 次" for k in ("P1_suppress", "P3_suppress") if k in sc]
    lines = [
        "【各項計數的意義：口徑不同，不可相加，也不應直接當作機動次數比較】",
        f"‧ 規則候選點 {c['l1_points']}：L1 規則式（P1–P6）標記的相鄰 TLE 轉換數。",
        f"‧ 候選事件 {c['events']}：上述候選點依時間合併而成；本報表主頁以此為主要事件數。"
        "事件密度＝候選事件數 ÷ TLE 首末筆實際涵蓋天數，次/月以 30 天換算；涵蓋不足 30 天時只列件數與天數。",
    ]
    if c.get("drag_events") is not None:
        lines.append(f"‧ 殘差候選事件 {c['drag_events']}：|阻力模型殘差| > {DRAG_EVENT_KM:.2f} km 的時點，"
                     "以同一規則合併（附錄 B）。殘差異常不等同推進機動。"
                     + (f"其中 {len(c['drag_only'])} 次未與任何候選事件重疊（{'、'.join(c['drag_only'])}）："
                        "L1 的高度自適應門檻會漏掉分成數筆、單筆未達門檻的小幅變化，此類日期列於主頁供複核，"
                        "但不併入候選事件。" if c.get("drag_only") else "")
                     + (f"另有 {len(c['drag_accum'])} 次屬「預期累積」（{'、'.join(c['drag_accum'])}）："
                        f"事件內每筆 |實測 Δa| 都小於殘差的 {DRAG_ACCUM_RATIO:.0%}，殘差主要來自阻力預期值，"
                        "常見於軌道維持中的衛星遇到較長 TLE 空窗，不代表發生離散變化。" if c.get("drag_accum") else ""))
    if l3["ml_available"]:
        lines.append(f"‧ ML 候選窗口 {l3['ml_n_flagged']}：逐窗 ML 模型（7 天窗）分數超過其門檻、"
                     f"且阻力殘差 > {DRAG_EVENT_KM:.2f} km 的窗口數。")
    if l3["fusion_available"] and l3["fusion_max_prob"] is not None:
        lines.append(f"‧ L3 融合評分器：期間最高分數 {l3['fusion_max_prob']:.3f}，操作門檻 {l3['fusion_thr']:.3f}"
                     + (f"，超門檻點合併後 {c['fusion_events']} 次" if c.get("fusion_events") is not None else "")
                     + "。此分數為模型輸出，未針對本衛星所屬族群校準，不可解讀為「機動發生機率」。")
    nt = max(int(dq.get("n_transitions") or 0), 1)
    lines.append("‧ L2 統計變點通道（僅作輔助證據、不作事件計數；逐點觸發、未合併，單一通道對雜訊敏感）。"
                 "觸發密度（每 100 筆相鄰轉換）："
                 + "、".join(f"{ch} {100 * v['n_events'] / nt:.1f}（{v['n_events']} 次）" for ch, v in r["l2"].items())
                 + "。")
    lines += [
        "",
        "【判定流程】",
        "‧ 主判為 L1 規則式：候選事件清單完全由 L1 規則候選點產生。",
        f"‧ 時間合併：候選點依時間排序，與前一點相隔 ≤ {EVENT_MERGE_H} 小時即併入同一事件（連鎖合併），"
        f"因此單一事件的總跨度可以超過 {EVENT_MERGE_H} 小時。",
        f"‧ 輔助通道：阻力殘差、L3 融合、ML 窗口、L2 不增刪事件；事件起訖前後 {EVIDENCE_PAD_H} 小時內有觸發"
        "即記一類，L2 需至少 2 個通道同時觸發才記一類。",
        "‧ 各通道並非獨立觀測：ML 窗口的判定含阻力殘差條件，L3 融合評分器的輸入含 L2 分數與阻力殘差。"
        "多通道一致觸發是值得優先複核的理由，不代表獨立驗證，也不是推進機動的確認。",
        f"‧ 長 TLE 空窗：事件內候選轉換跨 {GAP_LONG_D:.0f} 天以上時不列 E3，且發生時間無法定位；"
        "下降量可由阻力預期解釋者列 E1。",
        f"‧ 複核註記（依時間序列型態，與輔助通道多寡無關）：「{STATUS_SPIKE}」＝事件內有方向相反、"
        "幅度大於 1 km 且淨變化不到最大跳變 20% 的跳變；"
        f"「{STATUS_NOISE}」＝事件內單筆 |Δa| 均小於 {NOISE_KM * 1000:.0f} m。",
        "",
        "【事件評估欄位（R3）】",
        f"‧ 事件類型：「{TYPE_SEG}」＝跨度 ≥ {SEG_MIN_SPAN_D:.0f} 天、有候選點的日期 ≥ {SEG_MIN_ACTIVE_D} 天，"
        f"且 ≥ {SEG_SAME_SIGN:.0%} 候選點與淨 Δa 同向；「{TYPE_JUMP}」＝跨度 ≤ {JUMP_MAX_SPAN_D} 天；其餘為「{TYPE_MULTI}」。",
        f"‧ 雜訊基線與 SNR：σΔa＝事件前後各 {SNR_WIN_D} 天內未被標記之相鄰轉換 Δa 的穩健標準差（1.4826 × MAD，"
        f"下限 {SIGMA_FLOOR_KM * 1000:.0f} m）；SNR＝|事件淨 Δa| ÷（σΔa × √k），k 為事件涵蓋的轉換數。"
        f"顯著性：SNR ≥ {SNR_HIGH:.0f} 為高、{SNR_MED:.0f}–{SNR_HIGH:.0f} 為中、< {SNR_MED:.0f} 為低。"
        "σΔa 衡量的是相鄰 TLE 之間的隨機起伏；SNR 高只表示變化不是相鄰 TLE 的隨機抖動，"
        "不能排除定軌更新造成的系統性跳變。報表中「≥1000」為顯示上限（σΔa 觸及 1 m 下限或量級極大時常見），"
        "不代表無限大或計算錯誤；原始值見 CSV 的 snr 欄。",
        f"‧ 根數一致性註記：事件內任一候選轉換的 Δi、Δe 或 ΔRAAN 殘差偏離鄰近中位數超過 {ELEM_K:.0f} 倍穩健標準差。"
        "Δi★ 獨立意義較高（需平面外分量）；Δe 與切向推進相容、ΔΩ 可能為 Δa 改變節點進動率所致，皆非獨立證據。"
        "僅列為資訊、不計入證據等級，也不能作為機動確認。",
        "‧ 證據等級：E3 高優先複核＝顯著性高，且（至少 3 類輔助通道一致並含 L3 融合或 ML 模型通道、或屬連續機動段、"
        f"或 |淨 Δa| ≥ {E3_BIG_KM:.0f} km）；ML 窗口模型與 L3 融合評分器只以 Starlink 訓練，非 Starlink 衛星僅因"
        "「≥3 類輔助通道含 ML／融合」而達 E3 者改列 E2 並標「ML 輔助」；E2 人工複核＝顯著性中以上且至少 2 類輔助通道一致，但未達 E3；"
        "E1 待觀察＝其餘（含顯著性低、量級近 TLE 雜訊或輔助通道不足者）；"
        f"D 資料品質待查＝呈「{STATUS_SPIKE.split('，')[0]}」者——可能是 TLE 擬合異常、編目交叉標記或定軌更新，"
        "也可能是真實且劇烈的軌道變化，故不與低顯著性事件同列 E1，並附「資料確認後等級」（假設資料無誤時依上列規則重算）。"
        "等級反映的是複核優先順序，不是機動發生機率。",
        f"‧ 事件狀態（與等級分開記錄）：「{STATE_DQ}」＝回跳型態或編目硬證據（國際編目號改變、單筆 |Δi| 異常、"
        f"line1／line2 編號不一致）；「{STATE_LOWSIG}」＝顯著性低或量級近 TLE 雜訊；「{STATE_WEAK}」＝顯著性中以上但輔助"
        f"通道不足；「{STATE_CAND}」＝E2／E3。「{STATE_EXCL}」只在人工複核確認後更新，本報表不自動給出。",
        f"‧ 重點複核項目（主頁）依優先序排列：D＝資料品質優先複核；P1 立即複核＝E3、|淨 Δa| ≥ {E3_BIG_KM:.0f} km、"
        f"有編目疑點，或高優先機動段；P2 排程複核＝其餘 E2、|淨 Δa| ≥ {FOCUS_MIN_KM:.0f} km 的事件或機動段。"
        f"D 與 P1 全數列出，P2 主表最多 {P2_MAIN_MAX} 項（依等級、量級），其餘見完整清單。連續機動段以段為單位列出。",
        "‧ 編目複核紀錄：有編目疑點的事件記錄觸發原因、編目檢查狀態（初始「待檢查」）、自動檢查結果與判讀狀態；"
        "自動檢查命中編號類硬證據者「暫停機動解釋」，僅有大幅跳變或對稱升降者「暫列候選機動」。"
        "人工核對後應將狀態更新為「已排除」「疑似交叉標記」或「維持候選」。",
        f"‧ 低置信複核項：殘差峰值 ≥ {LOW_CONF_P1_KM:.0f} km 列 P1、其餘 P2；複核期限預設「{REVIEW_DUE}」，狀態初始為「待複核」。"
        "相隔 72 小時內者合併為同一複核案件，並標註資料缺口、高阻力、太陽活躍、連續段。"
        "非 Starlink 衛星之 L3 融合評分器超門檻時點不列入（真值驗證於營運方認證安靜期內全為誤報）"
        + (f"，本期略去 {r['low_conf_suppressed']['fusion_non_starlink']} 筆" if (r.get("low_conf_suppressed") or {}).get("fusion_non_starlink") else "")
        + "。",
        "‧ 偵測能力：σΔa 中位數＝未標記轉換逐月穩健標準差的中位數；單次可辨識量級＝"
        f"{SNR_HIGH:.0f} × σΔa（單筆轉換 SNR ≥ {SNR_HIGH:.0f}）；近 90 天 P95＝期末 90 天未標記轉換 |Δa| 的 95 百分位。"
        "量級低於此界限的機動，本方法可能無法與 TLE 雜訊區分。",
        f"‧ 編目一致性與主要疑點：單筆 |Δa| ≥ {BIG_JUMP_KM:.0f} km、單筆 |Δi| > {INC_JUMP_DEG}°、國際編目號在事件前後改變，"
        f"或 {SYM_PAIR_D:.0f} 天內出現量級相近（差 ≤ {SYM_PAIR_TOL:.0%}）的反向大幅事件（對稱升降），均標為「先查編目」："
        "應先核對 NORAD 編號、國際編目號與根數族群連續性，排除編目交叉標記或定軌更新後再進入機動解釋。"
        "此標記不改變證據等級——真實的升軌–降軌相位調整也會呈現對稱升降。",
        f"‧ 連續機動段：相鄰、同向，且各自為「{TYPE_SEG}」或 |淨 Δa| ≥ {CAMPAIGN_MIN_KM:.0f} km 的事件，"
        f"彼此相隔 ≤ {CAMPAIGN_GAP_D:.0f} 天者合為一段；累計 Δa 取段首事件前最後一筆 TLE 至段末事件末筆 TLE "
        "的半長軸差（含段間漂移），平均速率＝累計 Δa ÷ 該時距。",
        *([f"‧ GEO 位置保持段：東西（EW）＝不屬機動段、無複核註記與編目疑點、|淨 Δa| < {CAMPAIGN_MIN_KM:.0f} km 的事件，"
           f"編號相鄰、同向且相隔 ≤ {SK_GAP_D:.0f} 天者合為一段（≥ {SK_MIN_N} 個）；同向小幅 Δa 的累積可能是經度漂移本身，"
           "也可能是小幅推進序列，方向轉折處才是候選的東西修正時點。南北（NS）＝根數一致性註記含 Δi 的事件，"
           f"相隔 ≤ {NS_GAP_D:.0f} 天合為一組，僅作線索（Δi 改變需平面外推力）。",
           "‧ GEO 的「攝動殘差」通道：計算方式與低軌的阻力殘差相同（NRLMSIS），但 GEO 的大氣阻力可忽略，"
           "此殘差主要反映模型、定軌與 TLE 擬合差異，只作參考，不代表顯著大氣阻力。"]
          if r.get("orbit_class") == "GEO" else
          ["‧ 高軌目標的「攝動殘差」通道：計算方式與低軌的阻力殘差相同（NRLMSIS），但大氣阻力可忽略，"
           "殘差主要反映模型與 TLE 擬合差異，只作參考。"] if r.get("high_orbit") else []),
        "‧ 外部複核狀態：本報表未取得營運者機動公告、精密星曆或接近事件資料，所有事件的外部複核狀態均為「無」。",
        "",
        "【L1 規則細項】",
        f"本期 {l1.get('n_transitions', 0)} 筆相鄰 TLE 轉換中，各判定規則各自標記的次數（可重疊）："
        + "、".join(detect) + "。",
        "抑制判定（判為大氣阻力自然衰減而扣除）：" + "、".join(suppress) + "。",
        "判定以 P2 高度門檻依序乘 P5（F10.7，倍率 1.0–1.8）與 P6（傾角族群）倍率之有效門檻為準"
        "（MEO／GEO 為 0.05 km），加上其他根數與 P4 相鄰窗口補標；上列 P2、P5、P6 次數為各門檻單獨計算之參考值。",
        f"扣除抑制後，標記 {l1['n_flagged']} 個規則候選點。",
        *_suppression_lines(r),
        "",
        "【資料處理】",
        f"‧ 編目名稱：{r.get('name') or '（未取得）'}。",
        f"‧ 原始 TLE {dq['n_raw']} 筆"
        + (f"；同一 epoch 重複收錄 {dq['n_dup']} 筆已去除（保留最後一筆）" if dq["n_dup"] else "")
        + f"；有效 TLE {dq['n_tle']} 筆"
        + (f"；TLE 間隔中位數約 {dq['dt_median_h']:.1f} 小時。" if dq["dt_median_h"] is not None else "。"),
        f"‧ 有效相鄰轉換 {dq['n_transitions']} 筆（N 筆 TLE 最多 N−1 筆轉換；時間差 ≤ 0 者略過）。",
        "‧ 首末半長軸差＝期間最後一筆與第一筆 TLE 的半長軸差，描述整段期間的淨變化；"
        "與各事件 Δa 的加總不同，後者只涵蓋被標記的轉換。",
        f"‧ 報表版本 {REPORT_VERSION}；分析流程版本 {_pipeline_version()}（偵測程式與模型檔內容的雜湊，"
        "同一版本的輸入資料應得到相同結果）。",
    ]
    return "\n".join(lines)


def _suppression_lines(r: dict) -> list[str]:
    """附錄 C：抑制規則的漏檢風險與固定殘差門檻的揭露。"""
    out = []
    sp = r.get("suppression")
    if sp and sp["n_sup"]:
        t = (f"‧ 抑制規則漏檢風險：抑制旗標涵蓋 {sp['n_sup']}／{sp['n_tr']} 筆轉換（{sp['n_sup'] / sp['n_tr']:.0%}，"
             "多數本來就未達偵測門檻）；其中原已被偵測規則標記、因抑制而扣除者 "
             f"{sp['n_removed']} 筆。被抑制轉換的 |Δa| 中位數 {sp['sup_absda_p50'] * 1000:.0f} m、"
             f"P95 {sp['sup_absda_p95'] * 1000:.0f} m、最大 {sp['sup_absda_max']:.3f} km")
        if sp.get("n_sup_drag_hi") is not None:
            t += f"；其中阻力殘差仍 > {DRAG_EVENT_KM:.2f} km 者 {sp['n_sup_drag_hi']} 筆（可能被壓掉的小幅變化）"
        out.append(t + "。抑制規則對本星的召回率／誤報率需逐星標註資料，本報表未提供。")
    dp = r.get("drag_pctl")
    if dp:
        out.append(f"‧ 殘差門檻：本星 |阻力殘差| P95 {dp['p95']:.3f} km、P99 {dp['p99']:.3f} km。附錄 B 採跨星固定門檻 "
                   f"{DRAG_EVENT_KM:.2f} km 以維持可比性；固定門檻對低軌、阻力大的目標較易觸發，對高軌目標較易漏檢。"
                   "依各星分位數或高度、B*、F10.7 調整的自適應門檻尚未完成驗證，未採用。")
    return out


def build_report_narrative(norad, alt_km_avg, start_date: str, end_date: str,
                           events: list[dict], first_last_da: float,
                           segments: list[dict] | None = None, prior: dict | None = None) -> str:
    """送 SSA-RAG 的問句（附錄 F 用）。以事件級數字＋首末淨變化描述，要求固定三段、
    不排序原因、不下操作指令（舊版用逐筆候選點 Δa 加總，LLM 據此寫出「淨抬升、
    排除降低」與「暫停自動碰撞預警」，2026-10-29 審閱意見）。"""
    alt_txt = f"平均軌道高度約 {alt_km_avg:.0f} km" if alt_km_avg is not None else "軌道高度未知"
    lines = [f"衛星 NORAD {norad}（{alt_txt}）{start_date} 至 {end_date} 的 TLE 半長軸分析結果"
             f"（候選，非已確認機動）：全期間首末半長軸差 {first_last_da:+.2f} km；"
             f"候選事件 {len(events)} 次。"]
    top = sorted(events, key=lambda e: -abs(e["net_da"]))[:10]
    for e in sorted(top, key=lambda e: e["no"]):
        lines.append(f"- {pd.Timestamp(e['t_start']):%Y-%m-%d}：事件淨 Δa {_fmt_da(e['net_da'])} km"
                     + (f"（{e['ev_type']}，證據等級 {e['grade']}）" if "grade" in e else "")
                     + (f"，{e['quality_note']}" if e["quality_note"] else ""))
    if len(events) > 10:
        lines.append(f"-（另有 {len(events) - 10} 次量級較小的事件未列）")
    for sg in segments or []:
        lines.append(f"- 事件 #{sg['events'][0]}–#{sg['events'][-1]} 為同向連續機動段，累計 {sg['cum_da']:+.1f} km、"
                     f"約 {sg['rate_km_d']:+.2f} km/天")
    if prior:
        lines.append(f"- 營運先驗：{prior['text']}")
    lines.append("請分「可直接觀察」「待驗證解釋」「建議複核」三段、每段 2～3 句說明。"
                 "可直接觀察只重述上列數字；待驗證解釋列出可能原因但不要依可能性排序、不要下結論；"
                 "不要給出操作指令；標準 TLE 不含協變異資訊。")
    return "\n".join(lines)


def build_ml_maneuver_narrative(satellite_id, p_maneuver: float, lgbm_feat: dict,
                                start_date: str, end_date: str,
                                alert: bool | None = None) -> str:
    """LightGBM／融合偵測結果 → 自然語言描述（與 app 內同名函式邏輯一致）。"""
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
        "分析時如何區分大氣阻力衰減與真實機動？")
    return "\n".join(lines)


def _rag_query_from_narrative(narrative: str, n_events: int) -> str:
    """把送給 RAG 檢索的問句與「給人看的完整敘述」分開：0 事件情境下，敘述開頭
    「衛星 NORAD xxx（xxx km）在 xxx 至 xxx 期間...」這段對這顆衛星獨一無二、
    但知識庫文件裡不會出現的具體數字/編號，會稀釋掉後面真正的概念性問題，導致
    向量檢索找不到任何文件（0 篇來源），RAG 因此誠實回答「資料不足」——2026-09-17
    以 NORAD 68196、2025-08-01~2026-09-16 區間實測重現：帶著這段開頭送出 0 篇來源，
    拿掉開頭只問概念性問題則正常檢索到 4 篇文件並得到完整答案。故 0 事件情境改為
    只送純概念性問題；有具體事件時的敘述（含事件清單／方向統計）檢索本來就正常
    （已用 10 顆近期偵測到機動的衛星驗證），不動它。"""
    if n_events == 0:
        return ("此段 TLE 觀測期間，以半長軸（SMA）跳變法未偵測到明顯機動。"
                 "請解說：此類情況下，未偵測到明顯機動的可能原因有哪些？"
                 "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return narrative


def get_ai_explanation(query: str, fallback_text: str | None = None,
                       topic: str = "maneuver") -> dict:
    """呼叫 SSA-RAG 取得說明；離線或逾時一律 fallback 成規則式敘述文字本身，
    絕不讓報表產製因外部服務不穩而失敗或卡住。回傳 {"answer","confidence","source"}。
    query＝實際送去檢索的問句；fallback_text＝服務離線時顯示的文字（預設沿用 query，
    但呼叫端可傳入內容更完整的敘述，例如 0 事件情境時 query 已被簡化，fallback 仍
    想顯示含衛星編號/日期的完整敘述）。"""
    fallback_text = query if fallback_text is None else fallback_text
    fallback = {"answer": fallback_text, "confidence": "n/a",
                "source": "rule_based_fallback"}
    try:
        from ssa_rag_client import SSARAGClient
    except ImportError:
        return fallback
    try:
        client = SSARAGClient(base_url=RAG_DEFAULT_URL, timeout=RAG_TIMEOUT_S)
        if not client.health():
            return fallback
        result = client.ask(query, topic=topic, client_id="maneuver_report_api")
        # 雲端 LLM 偶爾把換行輸出成字面 "\n"（2026-10-29 Space 實測），PDF 會照印成反斜線
        answer = result.answer.replace("\\n", "\n")
        return {"answer": answer, "confidence": result.confidence, "source": "ssa_rag"}
    except Exception as e:
        logger.warning("SSA-RAG 呼叫失敗，退回規則式敘述：%s", e)
        return fallback


# ── 整合：單一衛星＋日期區間 → 報表資料結構 ──────────────────────────────────
class ReportNotFoundError(ValueError):
    """NORAD 查無資料，或指定區間內 TLE 筆數不足——呼叫端（report_api.py）應回 404，
    與其他非預期例外（程式錯誤）明確區分，後者一律回 500 並記錄完整 traceback。"""


def build_report_data(norad: int, start_date: date, end_date: date, lang: str = "zh",
                      with_ai: bool = True, with_external: bool = True) -> dict:
    """回傳給 render_pdf() 用的統一結構。任何一層缺資料只記錄 None／空值，
    不中斷整體報表產製（維持「部分資訊也要能出報表」的可用性優先原則）。
    with_ai=False：不呼叫 SSA-RAG（App 頁面以同一份資料呈現 F2 各節時用，解說另由頁面觸發）。
    with_external=False：不查 N2YO／KeepTrack 基本資料（離線測試用）。"""
    d0, d1 = start_date, end_date
    name = satellite_name(norad)
    # 外部基本資料提前查詢：本地編目查不到名稱時（2026-10-30 TASA 選定 15 星全數如此）以 N2YO 名稱補上，
    # 否則 PDF 顯示「名稱未取得」，且 Starlink／FORMOSAT 營運先驗因名稱缺失而不觸發
    sat_info = None
    if with_external:
        try:
            import sat_info_fetch
            sat_info = sat_info_fetch.get_sat_info(norad)
        except Exception as e:
            logger.warning("衛星基本資料查詢失敗：%s", e)
    if not name and sat_info:
        name = ((sat_info.get("sources", {}).get("N2YO", {}).get("fields") or {}).get("名稱")
                or (sat_info.get("sources", {}).get("KeepTrack", {}).get("fields") or {}).get("名稱"))
    df_full = load_tle(norad)
    if df_full.empty:
        raise ReportNotFoundError(f"NORAD {norad} 查無 TLE 資料")
    df_raw = df_full[(df_full["epoch"].dt.date >= d0) & (df_full["epoch"].dt.date <= d1)]
    # 同一 epoch 重複收錄：保留最後一筆。不能只比對完全相同的 epoch——同一組軌道解經不同來源
    # 入庫時 epoch 會差約 0.864 ms（半長軸完全相同），曾在 NORAD 66666 見 130 對，會產生零時長
    # 轉換、讓候選點清單出現同一分鐘的成對資料（2026-10-29）。相距 < 1 秒即視為同一筆。
    df = df_raw.sort_values("epoch", kind="stable").reset_index(drop=True)
    near_dup = (df["epoch"].shift(-1) - df["epoch"]).dt.total_seconds() < 1.0
    df = df[~near_dup].reset_index(drop=True)
    if len(df) < 3:
        raise ReportNotFoundError(f"NORAD {norad} 在 {d0}~{d1} 區間內 TLE 筆數不足（{len(df)} 筆，需至少 3 筆）")

    f107 = load_f107()
    l1 = compute_l1(df, f107, lang=lang)
    tr = l1["tr"]
    combined = np.asarray(l1["combined"], bool)

    l2_raw = compute_l2(df)
    l2 = {}
    for k, v in l2_raw.items():
        ev = v.get("events")
        l2[k] = {"n_events": 0 if ev is None else len(ev)}

    ml = compute_ml_detection(norad, d0, d1)
    ml_df = ml[0] if ml is not None else None
    fusion = compute_fusion_detection(norad, d0, d1)
    drag_series = compute_drag_series(df)
    l3 = {
        "ml_available": ml is not None,
        "ml_n_flagged": int(ml_df["flag"].sum()) if ml_df is not None else None,
        "fusion_available": fusion is not None,
        "fusion_max_prob": float(fusion["fusion"].max()) if fusion is not None and len(fusion) else None,
        "fusion_thr": float(fusion.attrs.get("thr")) if fusion is not None else None,
    }

    # 規則候選點：combined 與 tr（相鄰轉換）逐列對齊，不可拿去索引 df——第 i 個轉換對應
    # df 第 i+1 筆，且 tr 會略過時間差 ≤0 的轉換。舊版用 df.iloc[hit_idx] 取時間、再以
    # 相鄰 df 列相減求 Δa，整份落點清單時間與 Δa 全部錯位，百公里級跳變因此從清單消失
    # （2026-10-29，NORAD 58573：+123／+140／−260 km 三次跳變皆未列出）。
    events = build_candidate_events(df, tr, combined, l2_raw, drag_series, fusion, ml_df)
    alt_km_avg = float(df["sma_km"].mean() - R_E)
    high_orbit = alt_km_avg > HIGH_ORBIT_KM
    for e in events:
        e["high_orbit"] = high_orbit
    in_domain = bool(name) and str(name).upper().startswith("STARLINK")   # ML／融合之訓練範圍（Starlink）
    assess_events(events, tr, combined, drag_series, in_domain=in_domain)
    catalog = catalog_checks(df, tr, combined, events)
    segments = build_segments(events, df)
    station_keeping = build_station_keeping(events, df, tr, l1["orbit_class"])
    prior = _operator_prior(norad, name)
    landing = []
    if len(tr) and combined.any():
        ev_of = {}
        for e in events:
            for t in tr.loc[combined, "epoch"]:
                if e["t_start"] <= t <= e["t_end"]:
                    ev_of[t] = e["no"]
        for t, d in zip(tr.loc[combined, "epoch"], tr.loc[combined, "da_km"]):
            landing.append({"epoch": t, "sma_delta": float(d),
                            "sma_direction": "raise" if d >= 0 else "lower", "event_no": ev_of.get(t)})

    # 全期間首末差與最大單筆跳變（確認最大跳變是否被規則標記）
    first_last_da = float(df["sma_km"].iloc[-1] - df["sma_km"].iloc[0])
    max_jump = None
    if len(tr):
        k = int(np.argmax(np.abs(tr["da_km"].to_numpy(float))))
        t_k = tr["epoch"].iloc[k]
        max_jump = {"epoch": t_k, "da": float(tr["da_km"].iloc[k]),
                    "event_no": next((e["no"] for e in events if e["t_start"] <= t_k <= e["t_end"]), None)}

    fus_ts = None
    if fusion is not None and len(fusion):
        fus_ts = fusion[["epoch", "fusion"]].copy()
        fus_ts["thr"] = l3["fusion_thr"]
    drag_only, drag_accum = _drag_only_episodes(drag_series, events)
    counts = {
        "l1_points": int(combined.sum()), "events": len(events),
        "events_multi": sum(e["channel_level"] == STATUS_MULTI for e in events),
        "events_spike": sum(e["quality_note"] == STATUS_SPIKE for e in events),
        "drag_events": _episode_count(drag_series, "drag"),
        "drag_only": drag_only, "drag_accum": drag_accum,
        "fusion_events": _episode_count(fus_ts, "fusion"),
        "grades": {g: sum(e["grade"] == g for e in events) for g in ("E3", "E2", "E1", "D")},
    }
    detect_cap = detection_capability(tr, combined, events)
    lc_suppressed: dict = {}
    low_conf = low_conf_items(drag_series, fus_ts, events, high_orbit=high_orbit, df=df, l2_raw=l2_raw,
                              min_net_km=detect_cap["min_detect_m"] / 1000 if detect_cap else None,
                              in_domain=in_domain, suppressed=lc_suppressed)
    low_conf = annotate_low_conf(low_conf, df, f107)
    alt_history = altitude_history(df)
    dt_h = df["epoch"].diff().dt.total_seconds().dropna() / 3600
    data_quality = {"n_raw": len(df_raw), "n_dup": len(df_raw) - len(df), "n_tle": len(df),
                    "n_transitions": len(tr), "dt_median_h": float(dt_h.median()) if len(dt_h) else None}

    # L1 各子策略觸發次數（附錄 C 用）：P2/P5/P6/P4/other 為「偵測」，P1/P3 為「抑制」
    per_strategy = l1["detail"].get("per_strategy", {})
    l1_strategy_counts = {k: int(np.sum(v)) for k, v in per_strategy.items()}
    suppression = suppression_stats(per_strategy, tr, drag_series)
    drag_pctl = None
    if drag_series is not None and len(drag_series):
        a = drag_series["drag_resid_da"].abs().dropna().to_numpy(float)
        if len(a) >= 20:
            drag_pctl = {"p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99))}

    # 補充觀察指標（實驗性，見案例二十一）：僅留在資料結構供 API／研究用，一般報表不印
    phase_residual = compute_phase_residual_experimental(df)

    narrative = build_report_narrative(norad, alt_km_avg, str(d0), str(d1), events, first_last_da,
                                       segments=segments, prior=prior)
    rag_query = _rag_query_from_narrative(narrative, len(events))
    fallback_text = build_rule_based_explanation(alt_km_avg, events, first_last_da, max_jump,
                                                 counts["drag_only"], segments=segments, prior=prior)
    ai_explanation = (get_ai_explanation(rag_query, fallback_text=fallback_text, topic="maneuver") if with_ai
                      else {"answer": fallback_text, "confidence": "n/a", "source": "skipped"})

    return {
        "norad": norad, "name": name, "start_date": str(d0), "end_date": str(d1),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "orbit_class": l1["orbit_class"], "inc_family": l1["inc_family"],
        "alt_km_avg": alt_km_avg, "n_tle": len(df),
        "data_quality": data_quality,
        "l1": {"n_flagged": l1["n_flagged"], "n_transitions": len(tr),
               "strategy_counts": l1_strategy_counts},
        "l2": l2,
        "l3": l3,
        "counts": counts,
        "events": events,
        "segments": segments,
        "station_keeping": station_keeping,
        "high_orbit": high_orbit,
        "detect_cap": detect_cap,
        "alt_history": alt_history,
        "sat_info": sat_info,
        "catalog": catalog,
        "period_days": max((pd.Timestamp(d1) - pd.Timestamp(d0)).days + 1, 1),
        "tle_span_days": max((df["epoch"].iloc[-1] - df["epoch"].iloc[0]).total_seconds() / 86400, 1.0),
        "low_conf": low_conf,
        "low_conf_suppressed": lc_suppressed,
        "operator_prior": prior,
        "suppression": suppression,
        "drag_pctl": drag_pctl,
        "first_last_da": first_last_da,
        "max_jump": max_jump,
        "phase_residual_experimental": phase_residual,
        "landing_events": landing,
        "landing_source": "l1_combined",
        "narrative": narrative,
        "ai_explanation": ai_explanation,
        "analysis_notes": fallback_text,   # 附錄 F 固定式分析註記（不論 SSA-RAG 是否連線）
        "tle_df": df,          # 給 render_pdf 畫時序圖用，不落入 JSON 序列化路徑
        "l2_raw": l2_raw,      # 同上
        "fusion_df": fusion,   # 同上
        "drag_df": drag_series,  # 同上：NRLMSIS 阻力殘差序列，供附錄 B 用
        "tr_df": tr,           # 同上：軌道根數逐轉換差值（da/di/de/draan_res），供附錄 E 根數圖用
    }


_BUNDLED_CJK_FONT = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSansTC-Regular.ttf"


def _ensure_cjk_font() -> None:
    """確保 matplotlib 能正確顯示中文，不靜默 fallback 到無 CJK 字形的 DejaVu Sans
    （曾在 Case14 圖表踩過這個坑：只設 rcParams、從未驗證字型是否真的存在，
    HF Space 的 Linux 容器裡沒有 Windows 字型，結果整張圖中文變亂碼/缺字）。
    優先使用隨repo bundle 的 Noto Sans TC（保證任何部署環境都找得到，不依賴
    host OS 剛好裝了哪些字型），找不到才退回本機系統字型清單。"""
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    # fonttype 3（matplotlib 預設）把中文字嵌成不可靠的點陣/路徑字型子集，
    # PDF 閱讀器無法正確選取/複製文字（曾用 pypdf 與 PyMuPDF 兩種方式驗證，
    # 抽出來的內容都是亂碼 /uniXXXX），改用 42（TrueType 直接嵌入）讓文字
    # 可被選取、複製、搜尋。
    plt.rcParams["pdf.fonttype"] = 42

    if _BUNDLED_CJK_FONT.exists():
        fm.fontManager.addfont(str(_BUNDLED_CJK_FONT))
        family = fm.FontProperties(fname=str(_BUNDLED_CJK_FONT)).get_name()
        plt.rcParams["font.sans-serif"] = [family]
        plt.rcParams["axes.unicode_minus"] = False
        return
    for fname in ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans CJK JP",
                  "Noto Sans CJK SC", "SimHei", "PingFang TC", "PingFang SC",
                  "WenQuanYi Zen Hei", "Source Han Sans TC"]:
        try:
            fm.findfont(fm.FontProperties(family=fname), fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [fname]
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue
    logger.warning("找不到任何可用中文字型（含 bundled Noto Sans TC），"
                   "PDF 內中文可能顯示為缺字方框；請確認 assets/fonts/NotoSansTC-Regular.ttf 存在")


def _qr_image(url: str):
    """把網址轉成 QR code PIL 圖，供 matplotlib imshow 嵌入 PDF。"""
    import qrcode
    return qrcode.make(url)


def _wrap_cjk_text(text: str, width: int = 44) -> str:
    """matplotlib Text 的 wrap=True 對中文長段落不可靠（曾在 F2 報表的 AI 說明頁
    確認：長句直接被裁在頁面右緣，未換行），因此改用 textwrap 依字元數手動預先
    斷行。width 以「字元數」估算（非顯示寬度），44 是以 fontsize=9、ax3 可用寬度
    約 7.3 吋反推的保守值，留有餘裕避免半形字混排時仍溢出。"""
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=width, break_long_words=True,
                                    break_on_hyphens=False) or [""])
    return "\n".join(lines)


def _wrap_display(text: str, width_pt: float, size: float) -> str:
    """依顯示寬度斷行（全形字 1 em、其餘約 0.56 em）。_wrap_cjk_text 以字元數計，
    中英數混排時會提早斷行、右側大片留白（2026-10-29 改版主頁實測）。"""
    import unicodedata

    def cw(ch):
        return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.56

    limit = width_pt / size * 0.97
    out = []
    for para in text.split("\n"):
        line, w = "", 0.0
        for ch in para:
            # 行首禁則：全形標點不放在行首，允許該字略為超出
            if w + cw(ch) > limit and line and ch not in "，。、；：）」』！？":
                k = line.rfind(" ")
                # 英數字串不從中間硬斷：回退到最近的空白（限最後 12 字內）
                if ch.isascii() and ch != " " and line[-1].isascii() and 0 < k > len(line) - 12:
                    out.append(line[:k])
                    line = line[k + 1:]
                else:
                    out.append(line)
                    line = ""
                w = sum(cw(c) for c in line)
            line += ch
            w += cw(ch)
        out.append(line)
    return "\n".join(out)


# ── PDF 產製：F1＝摘要版（一頁）；F2＝技術完整版（摘要＋附錄 A–F）────────────────
# 版面依 2026-10-29 兩輪審閱意見：主頁只回答「分析了什麼／看到什麼變化／哪些需複核／限制」，
# 每個視覺元素只表達一種意義（通道觸發與複核註記分開編碼）；各通道原始計數、根數圖、
# 生成式文字一律在附錄；實驗性相位殘差通道不印（僅留在資料結構）。
# PDF 一律以 72 DPI（＝PDF 點數單位）建圖，並以鎖序列化產製：pyplot 全域狀態非執行緒安全，
# Streamlit 多工作階段同時繪圖時，曾在 HF Space 觀察到整頁座標被放大 100/72 倍、正文跑到
# 頁面外（2026-10-29，同一請求重跑即正常＝偶發競態）。fig.dpi 與 PDF 單位一致即無換算可錯。
REPORT_VERSION = "R7（2026-11-15）"
_PDF_DPI = 72
_RENDER_LOCK = threading.Lock()
_A4_PORTRAIT = (8.27, 11.69)
_HEAD_COLOR = "#1f4e79"
_MUTE_COLOR = "#666666"
_SPIKE_COLOR = "#8e44ad"
_pipeline_version_cache: str | None = None


def _pipeline_version() -> str:
    """分析流程版本：偵測程式與模型檔內容的短雜湊。同一份程式與模型產出的報表版本相同，
    任一項改動即換號——前後兩版都是「41 筆」但清單內容已不同時，可據此分辨。"""
    global _pipeline_version_cache
    if _pipeline_version_cache is None:
        import hashlib
        h = hashlib.sha1()
        base = Path(__file__).resolve().parent
        for rel in ("maneuver_report_builder.py", "maneuver_strategies_july.py", "statistical_detectors.py",
                    "atmospheric_drag.py", "models_fusion/fusion_scorer.pkl",
                    "Orbital_Maneuver_V2/models_meme/lgbm_maneuver_v1.pkl"):
            p = base / rel
            if p.exists():
                h.update(p.read_bytes())
        _pipeline_version_cache = h.hexdigest()[:7]
    return _pipeline_version_cache


def _display_name(name: str | None) -> str:
    """主頁顯示名稱：編目佔位名（TBA - TO BE ASSIGNED）改為「名稱未指派」，原名留在附錄 C。"""
    if not name:
        return "名稱未取得"
    u = name.upper()
    return "名稱未指派" if ("TO BE ASSIGNED" in u or u.startswith("TBA")) else name


def ev_when(e: dict, iso: bool = False) -> str:
    t0, t1 = pd.Timestamp(e["t_start"]), pd.Timestamp(e["t_end"])
    if iso:
        return f"{t0:%Y-%m-%dT%H:%MZ}" + (f"／{t1:%Y-%m-%dT%H:%MZ}" if t1 != t0 else "")
    return f"{t0:%Y-%m-%d %H:%M}" + (f"～{t1:%m-%d %H:%M}" if t1 != t0 else "")


def ev_channels(e: dict, long: bool = False, sep: str = "、") -> str:
    lab = lambda k: (_drag_label(True, long) if k == "drag" and e.get("high_orbit")
                     else _EVIDENCE_LABELS[k][1 if long else 0])
    return sep.join(lab(k) for k in e["evidence"]) or "—"


def _fmt_snr(x: float) -> str:
    """SNR 顯示：整數；≥1000 為顯示上限（原始值見 CSV 的 snr 欄），不代表無限大或計算錯誤。"""
    return f"{x:.0f}" if x < 1000 else "≥1000"


def _fmt_elems(el: list[str]) -> str:
    """根數一致性註記：Δi 標★（需平面外分量，獨立意義較高）；Δe／ΔΩ 與平面內推進相容，非獨立證據。"""
    return "、".join("Δi★" if x == "Δi" else x for x in el) or "—"


def _ev_checks(e: dict) -> str:
    return "、".join(e.get("checks") or ([e["quality_note"]] if e["quality_note"] else [])) or "—"


def _seg_when(g: dict, iso: bool = False) -> str:
    f = "%Y-%m-%dT%H:%MZ" if iso else "%Y-%m-%d"
    return f"{pd.Timestamp(g['t_start']):{f}}{'／' if iso else '～'}{pd.Timestamp(g['t_end']):{f}}"


def is_focus(e: dict) -> bool:
    return (e.get("grade") in ("D", "E2", "E3") or abs(e["net_da"]) >= FOCUS_MIN_KM
            or bool(e.get("catalog_suspect")))


def _review_status(e: dict) -> str:
    if e.get("grade") == "D":
        return "待查資料品質"
    cr = e.get("catalog_review")
    if cr:
        return "暫停機動解釋" if cr["interp"] == "暫停機動解釋" else "待查編目"
    return "待複核"


_TIER_RANK = {"D": 0, "P1": 1, "P2": 2}


def focus_items(r: dict) -> tuple[list[dict], int]:
    """主頁「重點複核項目」，依優先序排列並編號（R5，2026-10-30 第五輪審閱：USA 270 主表 10 項與
    執行摘要建議的 4 項不對齊）。D＝資料品質優先（回跳型態）；P1 立即複核＝E3、|淨 Δa| ≥ E3_BIG_KM、
    有編目疑點或高優先機動段；P2 排程複核＝其餘 E2／|淨 Δa| ≥ 1 km 的事件或機動段。
    回傳 (全部項目, 其餘待觀察事件數)；主表 P2 上限由 focus_split() 處理。"""
    items = []
    for g in r.get("segments") or []:
        items.append({"id": f"C{g['no']}", "t": pd.Timestamp(g["t_start"]), "seg": g, "net": g["cum_da"],
                      "grade": g["grade"], "tier": "P1" if g["high"] else "P2",
                      "checks": f"機動段 #{g['events'][0]}–#{g['events'][-1]}，{g['rate_km_d']:+.2f} km/天",
                      "action": "提高監視頻率；確認後再評估碰撞風險" if g["high"] else "觀察", "status": "待複核"})
    n_rest = 0
    for e in r.get("events", []):
        if e.get("segment"):
            continue
        if not is_focus(e):
            n_rest += 1
            continue
        g = e.get("grade", "E1")
        tier = ("D" if g == "D" else
                "P1" if g == "E3" or abs(e["net_da"]) >= E3_BIG_KM or e.get("catalog_suspect") else "P2")
        items.append({"id": f"#{e['no']}", "t": pd.Timestamp(e["t_start"]), "ev": e, "net": e["net_da"],
                      "grade": g, "tier": tier, "checks": _ev_checks(e), "action": e.get("action", "—"),
                      "status": _review_status(e)})
    items.sort(key=lambda x: (_TIER_RANK[x["tier"]], GRADE_RANK.get(x["grade"], 9), -abs(x["net"])))
    seen: dict = {}
    for x in items:
        seen[x["tier"]] = seen.get(x["tier"], 0) + 1
        x["pid"] = f"D{seen['D']}" if x["tier"] == "D" else f"{x['tier']}-{seen[x['tier']]}"
    return items, n_rest


def focus_split(items: list[dict], p2_max: int = P2_MAIN_MAX) -> tuple[list[dict], list[dict]]:
    """主表與溢出：D、P1 全列，P2 依序取前 p2_max 項。"""
    main = [x for x in items if x["tier"] != "P2"]
    p2 = [x for x in items if x["tier"] == "P2"]
    return main + p2[:p2_max], p2[p2_max:]


def _prioritize(items: list[dict], limit: int) -> list[dict]:
    """版面容量不足時取優先序最前的 limit 項（items 已依優先序排列）。"""
    return items[:limit]


def focus_table(items: list[dict], iso: bool = False, short: int | None = None,
                compact: bool = False) -> tuple[list[str], list[list[str]]]:
    """compact=True（PDF 主頁）：優先序與項目併成一欄，讓出寬度給主要疑點與建議行動。"""
    cut = (lambda t: t if short is None or len(t) <= short else t[:short - 1] + "…")

    def when(x):
        if "seg" in x:
            return _seg_when(x["seg"], iso)
        e = x["ev"]
        if compact and pd.Timestamp(e["t_end"]) != pd.Timestamp(e["t_start"]):
            return f"{pd.Timestamp(e['t_start']):%Y-%m-%d}～{pd.Timestamp(e['t_end']):%m-%d}"
        return ev_when(e, iso)
    tail = lambda x: [when(x), _fmt_da(x["net"]), grade_label(x["ev"]) if "ev" in x else GRADE_TEXT.get(x["grade"], "—"),
                      cut(x["checks"]), x["action"],
                      x["status"]]
    rest = ["時間 (UTC)", "淨 Δa (km)", "證據等級", "主要疑點", "建議行動", "複核狀態"]
    if compact:
        return ["優先序／項目", *rest], [[f"{x['pid']} {x['id']}", *tail(x)] for x in items]
    return ["優先序", "項目", *rest], [[x["pid"], x["id"], *tail(x)] for x in items]


def catalog_review_table(events: list[dict], iso: bool = False) -> tuple[list[str], list[list[str]]]:
    """編目複核紀錄（R5）：下次報表更新時以人工核對結果改寫狀態，形成可追蹤的複核流程。"""
    cols = ["項目", "時間 (UTC)", "觸發原因", "編目檢查狀態", "自動檢查結果", "判讀狀態"]
    rows = [[f"#{e['no']}", ev_when(e, iso), e["catalog_review"]["trigger"] or "—", e["catalog_review"]["status"],
             e["catalog_review"]["result"], e["catalog_review"]["interp"]]
            for e in events if e.get("catalog_review")]
    return cols, rows


def station_keeping_table(sk: list[dict], iso: bool = False) -> tuple[list[str], list[list[str]]]:
    """GEO 位置保持段（R5）：東西段＝同向小幅 Δa 群組；南北組＝Δi 同步線索。"""
    cols = ["段", "類別", "起訖 (UTC)", "涵蓋事件", "事件數", "累計 Δa (km)", "累計 Δi (°)", "時距 (天)",
            "平均速率 (km/天)", "主要方向"]
    rows = [[x["id"], "東西位置保持" if x["kind"] == "EW" else "南北線索（Δi 同步）", _seg_when(x, iso),
             f"#{x['events'][0]}–#{x['events'][-1]}" if len(x["events"]) > 2 else "、".join(f"#{n}" for n in x["events"]),
             str(len(x["events"])), _fmt_da(x["cum_da"]), f"{x['cum_di']:+.3f}", f"{x['days']:.1f}",
             f"{x['rate_km_d']:+.3f}", x["direction"]] for x in sk]
    return cols, rows


def detect_cap_lines(r: dict) -> list[str]:
    """偵測能力四項（Markdown 條列、PDF／App 摘要共用）。"""
    dc = r.get("detect_cap")
    if not dc:
        return []
    few = dc.get("n_months", 0) < 3
    out = [f"σΔa 中位數（未標記轉換、逐月）：{dc['sigma_med_m']:.1f} m"
           + (f"（未標記轉換僅 {dc.get('n_unflagged', 0)} 筆、有效月份 {dc.get('n_months', 0)} 個，僅供參考）" if few else ""),
           ("近 90 天全部轉換 P95 |Δa|（未標記樣本不足，含已標記轉換）：" if dc.get("p95_all") else
            "近 90 天未標記轉換 P95 |Δa|：") + (f"{dc['p95_90d_m']:.0f} m" if dc["p95_90d_m"] is not None else "樣本不足"),
           f"單次事件最低可辨識量級（SNR ≥ {SNR_HIGH:.0f}）：約 {dc['min_detect_m']:.0f} m"]
    mu = dc.get("max_unlisted")
    if mu:
        out.append(f"本期最大未列入事件之單筆 Δa：{_fmt_da(mu['da'])} km（{mu['epoch']:%Y-%m-%d}）")
    return out


def _ev_groups(e: dict) -> str:
    """事件所屬的連續機動段（C）與 GEO 位置保持段（EW／NS）。"""
    g = ([f"C{e['segment']}"] if e.get("segment") else []) + list(e.get("sk") or [])
    return "／".join(g) or "—"


def grade_label(e: dict) -> str:
    """證據等級顯示文字；非 Starlink 因 ML 輔助而由 E3 改列 E2 者加註（R7）。"""
    if e.get("ml_capped"):
        return "E2（ML輔助）"           # 表格欄寬有限：不接「人工複核」
    return GRADE_TEXT.get(e.get("grade"), "—")


def _grade_cell(e: dict) -> str:
    g = e.get("grade")
    t = grade_label(e)
    return t + (f"（確認後 {e['grade_if_ok']}）" if g == "D" and e.get("grade_if_ok") else "")


def event_table(events: list[dict], full: bool = False, iso: bool = False) -> tuple[list[str], list[list[str]]]:
    """候選事件表：full=False＝六欄精簡表；full=True＝附錄 A-1 九欄（含所屬機動段、主要疑點）。"""
    if full:
        cols = ["事件", "偵測時段 (UTC)", "類型", "事件淨 Δa", "最大單筆 Δa", "規則標記", "輔助通道", "所屬段",
                "事件狀態", "主要疑點／複核註記"]
        rows = [[f"#{e['no']}", ev_when(e, iso), e.get("ev_type", "—"), _fmt_da(e["net_da"]), _fmt_da(e["main_da"]),
                 str(e["n_flags"]), ev_channels(e), _ev_groups(e), e.get("state", "—"), _ev_checks(e)]
                for e in events]
    else:
        cols = ["事件", "偵測時段 (UTC)", "類型", "淨 Δa (km)", "證據等級", "建議行動"]
        rows = [[f"#{e['no']}", ev_when(e, iso), e.get("ev_type", "—"), _fmt_da(e["net_da"]),
                 grade_label(e), e.get("action", "—")] for e in events]
    return cols, rows


def assessment_table(events: list[dict]) -> tuple[list[str], list[list[str]]]:
    """附錄 A-2 事件評估表：跨度、活躍日數、速率、雜訊基線、SNR、根數一致性註記、證據等級、建議行動。"""
    cols = ["事件", "跨度 (天)", "活躍日數", "速率 (km/天)", "σΔa (m)", "SNR", "顯著性", "根數一致性註記", "證據等級",
            "建議行動"]
    rows = []
    for e in events:
        if "grade" not in e:
            continue
        rate = e.get("rate_km_d")
        rows.append([f"#{e['no']}", f"{e['span_d']:.1f}", str(e["active_days"]),
                     "—" if rate is None else f"{rate:+.2f}", f"{e['sigma_km'] * 1000:.1f}", _fmt_snr(e["snr"]),
                     e["significance"], _fmt_elems(e["elements"]), _grade_cell(e), e["action"]])
    return cols, rows


def segment_table(segments: list[dict], iso: bool = False) -> tuple[list[str], list[list[str]]]:
    """附錄 A-3 連續機動段。"""
    cols = ["機動段", "起訖 (UTC)", "涵蓋事件", "累計 Δa (km)", "時距 (天)", "平均速率 (km/天)", "證據等級（最高）"]
    rows = [[f"C{g['no']}", _seg_when(g, iso), f"#{g['events'][0]}–#{g['events'][-1]}（{len(g['events'])} 個）",
             _fmt_da(g["cum_da"]), f"{g['days']:.1f}", f"{g['rate_km_d']:+.2f}", GRADE_TEXT.get(g.get("grade"), "—")]
            for g in segments]
    return cols, rows


LOW_CONF_STEP = "比對前後 7 天 TLE 與 F10.7／Ap，確認有無未標記的小幅 Δa"


def low_conf_table(r: dict, iso: bool = False) -> tuple[list[str], list[list[str]]]:
    """低置信複核項（R5）：項目、來源、時間、峰值、優先序、複核期限、狀態；檢查步驟統一為 LOW_CONF_STEP，
    於表下說明（每列重複同一句沒有資訊量）。"""
    f = "%Y-%m-%dT%H:%MZ" if iso else "%Y-%m-%d %H:%M"
    cols = ["項目", "案件", "來源", "時間 (UTC)", "峰值", "優先序", "診斷標記", "狀態"]
    rows = [[f"R{i}", x.get("case", "—"), x["source"], f"{x['epoch']:{f}}", x["value"], x.get("priority", "P2"),
             "、".join(x.get("tags") or []) or "—", x.get("status", "待複核")]
            for i, x in enumerate(r.get("low_conf") or [], 1)]
    return cols, rows


def kpi_tiles(r: dict) -> list[tuple[str, str, str]]:
    """主頁三個重點指標（PDF、App、Markdown 共用）：(標題, 數值, 副標)。"""
    events, c, mj = r.get("events", []), r["counts"], r.get("max_jump")
    g = c.get("grades") or {}
    segs = r.get("segments") or []
    mj_txt = f"{_fmt_da(mj['da'])} km" if mj else "—"
    if segs:
        hi = [f"C{x['no']}" for x in segs if x["high"]]
        t1 = ("主要分析單位：連續機動段", f"{len(segs)} 段",
              f"共 {len(events)} 個候選事件｜高優先 {'、'.join(hi) if hi else '無'}")
    elif events:
        t1 = ("候選事件", f"{len(events)} 次",
              f"E3 高優先 {g.get('E3', 0)}｜E2 {g.get('E2', 0)}｜E1 {g.get('E1', 0)}"
              + (f"｜D {g['D']}" if g.get("D") else ""))
    else:
        n_low = len(r.get("low_conf") or [])
        t1 = ("候選事件", "0 次", f"低置信複核項 {n_low} 筆" if n_low else "L1 規則式未觸發")
    if events:
        top = max(events, key=lambda e: abs(e["net_da"]))
        t2 = ("最大事件淨 Δa", f"{_fmt_da(top['net_da'])} km",
              f"事件 #{top['no']}｜最大單筆相鄰 TLE Δa {mj_txt}")
    else:
        t2 = ("最大單筆相鄰 TLE Δa", mj_txt,
              f"{pd.Timestamp(mj['epoch']):%Y-%m-%d}（未列入事件）" if mj else "")
    return [t1, t2, ("全期間首末差", f"{r['first_last_da']:+.2f} km", "末筆 − 首筆 TLE 半長軸")]


def summary_sentences(r: dict, appendix_ref: str = "附錄 B") -> list[str]:
    """執行摘要（PDF 主頁、App「結果摘要」、Markdown 共用，確保三邊文字同源）：
    要看什麼（數量與分析單位）→ 最大變化 → 判定限制 → 下一步，再附營運先驗與補充觀察。"""
    events, c, mj = r.get("events", []), r["counts"], r.get("max_jump")
    do = c.get("drag_only") or []
    ext = "外部複核狀態：無；未取得營運者公告、精密星曆或接近事件資料。"
    if not events:
        lc = r.get("low_conf") or []
        by = {}
        for x in lc:
            by[x["source"]] = by.get(x["source"], 0) + 1
        s1 = ("L1 規則式未觸發；但存在 " + str(len(lc)) + " 筆低置信複核項（"
              + "、".join(f"{k} {v} 次" for k, v in by.items()) + f"），未列為候選事件，見下表與{appendix_ref}。"
              if lc else "L1 規則式未觸發，本期無候選事件。")
        out = [s1, f"全期間首末半長軸差 {r['first_last_da']:+.2f} km。"]
        dc = r.get("detect_cap")
        if dc:
            mu = dc.get("max_unlisted")
            out.append(f"偵測能力：σΔa 中位數 {dc['sigma_med_m']:.1f} m，單次事件最低可辨識量級（SNR ≥ {SNR_HIGH:.0f}）"
                       f"約 {dc['min_detect_m']:.0f} m" + (f"；本期最大單筆 Δa {_fmt_da(mu['da'])} km，未達規則門檻"
                                                           if mu else "") + "。")
        return out + ["未偵測到不代表未機動：機動量小於上述界限、或 TLE 更新稀疏時，本方法可能無法分辨。", ext]
    g = c.get("grades") or {}
    # R6：事件通常數週到數月一次，次/天 會顯示成 0.00；固定用次/月才能跨範圍、跨星比較。分母用 TLE 實際
    # 涵蓋天數而非查詢天數；涵蓋不足一個月時不外推，只列件數與天數
    days = r.get("tle_span_days") or r.get("period_days") or 365
    out = [f"候選事件 {len(events)} 個（E3 {g.get('E3', 0)}、E2 {g.get('E2', 0)}、E1 {g.get('E1', 0)}"
           + (f"、D 資料品質待查 {g['D']}" if g.get("D") else "")
           + f"；由 {c['l1_points']} 筆規則候選點合併），密度 {len(events)} 件／{days:.0f} 天"
           + (f"（約 {len(events) / days * 30:.2f} 次/月）" if days >= 30 else "") + "。"]
    segs = r.get("segments") or []
    if segs:
        n_in = sum(len(x["events"]) for x in segs)
        hi = [f"C{x['no']}" for x in segs if x["high"]]
        if len(segs) <= 2:
            desc = "；".join(f"C{x['no']} {_seg_when(x)}，累計 {_fmt_da(x['cum_da'])} km、平均約 {x['rate_km_d']:+.2f} km/天"
                            for x in segs)
        else:
            desc = "、".join(f"C{x['no']} {_fmt_da(x['cum_da'])} km" for x in segs) + "；起訖與速率見附錄 A-3"
        out.append(f"主要分析單位：連續機動段 {len(segs)} 段（{desc}），涵蓋 {n_in} 個候選事件"
                   + (f"；高優先機動段：{'、'.join(hi)}" if hi else "")
                   + "。建議以機動段而非離散事件解讀；經人工確認後，再評估是否更新碰撞風險產品。")
    top = max(events, key=lambda e: abs(e["net_da"]))
    out.append(f"最大事件淨 Δa {_fmt_da(top['net_da'])} km（{pd.Timestamp(top['t_start']):%Y-%m-%d}，事件 #{top['no']}）；"
               f"全期間首末半長軸差 {r['first_last_da']:+.2f} km。")
    n_spike = c["events_spike"]
    s = ("所有事件均為候選，非已確認推進機動"
         + (f"；其中 {n_spike} 件呈回跳型態（D），需先排除 TLE 擬合異常、編目交叉標記或定軌更新" if n_spike else "") + "。")
    if mj and not mj.get("event_no") and abs(mj["da"]) >= 5:
        s += "最大單筆跳變未被規則標記，建議複核。"
    out.append(s)
    # 建議複核與主表優先序同源（R5：舊版主表 10 項、摘要只點名 4 項，兩者不對齊）
    items, n_rest = focus_items(r)
    ids = lambda xs: "、".join(x["id"] for x in xs)
    d_it = [x for x in items if x["tier"] == "D"]
    p1 = [x for x in items if x["tier"] == "P1"]
    p2 = [x for x in items if x["tier"] == "P2"]
    rec = []
    if d_it:
        rec.append(f"資料品質優先（D）{ids(d_it)}：先確認資料再重算等級")
    if p1:
        rec.append(f"立即複核（P1）{len(p1)} 項：{ids(p1)}")
    if p2:
        rec.append(f"排程複核（P2）{len(p2)} 項" + (f"（主表列前 {P2_MAIN_MAX} 項）" if len(p2) > P2_MAIN_MAX else ""))
    cr = [e for e in events if e.get("catalog_review")]
    if cr:
        stop = [e for e in cr if e["catalog_review"]["interp"] == "暫停機動解釋"]
        rec.append(f"{'、'.join('#' + str(e['no']) for e in cr[:6])} 先查編目"
                   + (f"（{'、'.join('#' + str(e['no']) for e in stop)} 暫停機動解釋）" if stop else ""))
    out.append(("；".join(rec) + "，優先序見下表" if rec else "無需優先複核之項目")
               + (f"。其餘 {n_rest} 個待觀察事件見附錄 A。" if n_rest else "。"))
    dq = r["data_quality"]
    if r.get("orbit_class") == "GEO":
        sk = r.get("station_keeping") or []
        ew = [x for x in sk if x["kind"] == "EW"]
        ns = [x for x in sk if x["kind"] == "NS"]
        t = ("GEO 定點保持會產生週期性小幅 Δa"
             + (f"（本期 TLE 間隔中位數約 {dq['dt_median_h']:.0f} 小時、更新稀疏）" if dq.get("dt_median_h") else "")
             + "。")
        if ew:
            n_in = sum(len(x["events"]) for x in ew)
            t += (f"位置保持節奏：東西 {len(ew)} 段（涵蓋 {n_in} 個小幅事件）"
                  + (f"、南北線索 {len(ns)} 組（Δi 同步）" if ns else "")
                  + "；段間方向轉折為候選東西修正時點，見附錄 A 位置保持段。")
        else:
            t += "相鄰 TLE 差值易累積大量 E1 事件，宜以機動段與 E2／E3 為主判讀。"
        out.append(t)
    lone = [e for e in events if e.get("ev_type") == TYPE_SEG and not e.get("segment")]
    if lone:
        out.append("事件 " + "、".join(f"#{e['no']}（跨 {e['span_d']:.1f} 天、淨 {_fmt_da(e['net_da'])} km）" for e in lone[:4])
                   + " 為連續機動段，建議以整段解讀。")
    pr = r.get("operator_prior")
    if pr:
        out.append(f"營運先驗（非本期資料證據）：{pr['short']}。")
    if do:
        out.append(f"另有 {len(do)} 次{_drag_label(bool(r.get('high_orbit')))}事件未與候選事件重疊"
                   f"（{'、'.join(do[:6])}{'等' if len(do) > 6 else ''}），"
                   f"可能是規則式門檻未涵蓋的小幅變化，建議一併複核（{appendix_ref}）。")
    ac = c.get("drag_accum") or []
    if ac:   # 日期與判讀見附錄 B、C；主頁只列次數，否則摘要過長會把重點複核表擠出首頁
        out.append(f"另 {len(ac)} 次殘差屬預期累積（實測幾乎不變），非離散變化。")
    out.append(ext)
    return out


def report_csv(r: dict) -> bytes:
    """報表明細 CSV（與 PDF 同一份計算，供下載分析）：長表格式，record_type 區分
    event／segment／low_conf／rule_point；每列帶 NORAD、期間與版本，多份報表可直接串接。
    UTF-8 含 BOM，Excel 直接開啟不亂碼。"""
    base = {"norad": r["norad"], "name": r.get("name") or "", "period_start": r["start_date"],
            "period_end": r["end_date"], "report_version": REPORT_VERSION, "pipeline_version": _pipeline_version()}
    ts = lambda t: "" if t is None else f"{pd.Timestamp(t):%Y-%m-%dT%H:%M:%SZ}"
    items, _ = focus_items(r)
    pid = {x["id"]: x["pid"] for x in items}
    rows = []
    for e in r.get("events", []):
        cr = e.get("catalog_review") or {}
        rows.append({**base, "record_type": "event", "id": f"#{e['no']}", "t_start_utc": ts(e["t_start"]),
                     "t_end_utc": ts(e["t_end"]), "ev_type": e.get("ev_type", ""), "net_da_km": round(e["net_da"], 4),
                     "max_da_km": round(e["main_da"], 4), "n_rule_flags": e["n_flags"],
                     "aux_channels": "|".join(e["evidence"]), "quality_note": e["quality_note"],
                     "span_d": round(e.get("span_d", float("nan")), 3), "active_days": e.get("active_days"),
                     "rate_km_d": None if e.get("rate_km_d") is None else round(e["rate_km_d"], 4),
                     "sigma_da_m": round(e["sigma_km"] * 1000, 2) if "sigma_km" in e else None,
                     "snr": round(e["snr"], 1) if "snr" in e else None, "significance": e.get("significance", ""),
                     "elements_sync": "|".join(e.get("elements", [])), "grade": e.get("grade", ""),
                     "e3_basis": e.get("e3_basis") or "", "ml_capped": bool(e.get("ml_capped")),
                     "action": e.get("action", ""), "segment": f"C{e['segment']}" if e.get("segment") else "",
                     "checks": "|".join(e.get("checks", [])), "catalog_suspect": bool(e.get("catalog_suspect")),
                     "focus": is_focus(e) and not e.get("segment"), "priority": pid.get(f"#{e['no']}", ""),
                     "state": e.get("state", ""), "grade_if_ok": e.get("grade_if_ok", ""),
                     "sk_group": "|".join(e.get("sk") or []), "catalog_check_status": cr.get("status", ""),
                     "catalog_check_result": cr.get("result", ""), "interpretation": cr.get("interp", ""),
                     "review_status": _review_status(e) if pid.get(f"#{e['no']}") else "",
                     "external_review": "none"})
    for g in r.get("segments") or []:
        rows.append({**base, "record_type": "segment", "id": f"C{g['no']}", "t_start_utc": ts(g["t_start"]),
                     "t_end_utc": ts(g["t_end"]), "ev_type": TYPE_SEG, "net_da_km": round(g["cum_da"], 4),
                     "span_d": round(g["days"], 3), "rate_km_d": round(g["rate_km_d"], 4), "grade": g.get("grade", ""),
                     "focus": True, "priority": pid.get(f"C{g['no']}", ""), "review_status": "待複核",
                     "event_ref": ",".join(f"#{n}" for n in g["events"])})
    for x in r.get("station_keeping") or []:
        rows.append({**base, "record_type": "sk_segment", "id": x["id"], "t_start_utc": ts(x["t_start"]),
                     "t_end_utc": ts(x["t_end"]), "ev_type": "東西位置保持" if x["kind"] == "EW" else "南北線索",
                     "net_da_km": round(x["cum_da"], 4), "span_d": round(x["days"], 3),
                     "rate_km_d": round(x["rate_km_d"], 4), "value": f"cum_di_deg={x['cum_di']:+.4f}",
                     "action": x["direction"], "event_ref": ",".join(f"#{n}" for n in x["events"])})
    for i, x in enumerate(r.get("low_conf") or [], 1):
        rows.append({**base, "record_type": "low_conf", "id": f"R{i}", "t_start_utc": ts(x["epoch"]),
                     "aux_channels": x["source"], "value": x["value"], "action": LOW_CONF_STEP,
                     "priority": x.get("priority", "P2"), "review_due": x.get("due", REVIEW_DUE),
                     "review_status": x.get("status", "待複核"), "case": x.get("case", ""),
                     "tags": "|".join(x.get("tags") or []), "tle_gap_d": x.get("tle_gap_d"),
                     "bstar": x.get("bstar"), "f107": x.get("f107")})
    ah = r.get("alt_history")
    if ah:
        for _, a in ah["daily"].iterrows():
            rows.append({**base, "record_type": "alt_daily", "t_start_utc": ts(a["epoch"]),
                         "apogee_km": round(float(a["apogee_km"]), 3), "perigee_km": round(float(a["perigee_km"]), 3),
                         "apogee_mean_km": round(float(a["apogee_mean_km"]), 3),
                         "perigee_mean_km": round(float(a["perigee_mean_km"]), 3),
                         "value": f"definition={ah.get('definition', 'mean')}"})
    try:
        import sat_info_fetch
        for k, v, src in sat_info_fetch.info_rows(r.get("sat_info")):
            rows.append({**base, "record_type": "sat_info", "id": k, "value": v, "aux_channels": src})
    except Exception:
        pass
    dc = r.get("detect_cap")
    if dc:
        mu = dc.get("max_unlisted")
        rows.append({**base, "record_type": "detection_capability", "id": "DC",
                     "sigma_da_m": round(dc["sigma_med_m"], 2),
                     "value": f"min_detect_m={dc['min_detect_m']:.0f}"
                              + (f";p95_90d_m={dc['p95_90d_m']:.0f}" if dc["p95_90d_m"] is not None else "")
                              + (f";max_unlisted_da_km={mu['da']:+.4f}" if mu else ""),
                     "t_start_utc": ts(mu["epoch"]) if mu else ""})
    for p in r.get("landing_events", []):
        rows.append({**base, "record_type": "rule_point", "t_start_utc": ts(p["epoch"]),
                     "max_da_km": round(p["sma_delta"], 4),
                     "event_ref": f"#{p['event_no']}" if p.get("event_no") else ""})
    cols = list(base) + ["record_type", "id", "t_start_utc", "t_end_utc", "ev_type", "net_da_km", "max_da_km",
                         "n_rule_flags", "aux_channels", "quality_note", "span_d", "active_days", "rate_km_d",
                         "sigma_da_m", "snr", "significance", "elements_sync", "grade", "action", "segment",
                         "checks", "catalog_suspect", "focus", "priority", "state", "grade_if_ok", "sk_group",
                         "catalog_check_status", "catalog_check_result", "interpretation", "review_status",
                         "review_due", "event_ref", "value", "apogee_km", "perigee_km", "apogee_mean_km",
                         "perigee_mean_km", "external_review"]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame([{**base, "record_type": "none"}], columns=cols)
    for col in ("n_rule_flags", "active_days"):
        df[col] = df[col].astype("Int64")      # 混有空值時避免輸出成 4.0
    return df.to_csv(index=False).encode("utf-8-sig")


VERSION_NOTES = [
    "R7（2026-11-15）：L1 改以 P2×P5×P6 有效門檻判定（舊版取聯集使 P5、P6 無作用），P5 倍率上限 1.8；"
    "依大樣本消融與福衛七號精密真值驗證，移除 ΔΩ 標記（只增誤報）與 P3 抑制（無作用）；非 Starlink 衛星之 ML 輔助 E3 改列 E2（ML 輔助）；非 Starlink 衛星之 L3 融合評分器不列入低置信複核項；"
    "低置信複核項合併為複核案件並加診斷標記；E3 建議處置改為確認後再評估碰撞風險；低置信複核項新增「L2 統計變點」來源——L1 規則未標記的時段，若 ≥2 種 L2 方法"
    "（CUSUM／BOCPD／SSA／MAD3σ）在 48 小時內同時觸發，且扣除背景衰減後淨 Δa 達該星 20σ 與 L1 單步門檻之較大值，"
    "列為 P2 待複核，不併入候選事件、不影響證據等級。",
    "R6（2026-10-31）：ML 窗口可能標記的時點一律評分（舊版超過 220 筆時僅等距抽樣，長期間會漏掉 ML 通道、等級偏低）；"
    "阻力殘差事件區分「實測有變化」與「預期累積」；事件密度改為件數／TLE 涵蓋天數＋次/月；"
    f"候選轉換跨 {GAP_LONG_D:.0f} 天以上 TLE 空窗的事件不列 E3 並加註，主頁主圖隨摘要長度縮放。",
    "R5（2026-10-30）：重點複核項目改依優先序（D 資料品質／P1 立即／P2 排程）排列並編號，P2 主表上限 "
    f"{P2_MAIN_MAX} 項，執行摘要建議與主表同源；回跳型態改列 D 並附資料確認後等級；新增事件狀態、編目複核紀錄、"
    "GEO 東西／南北位置保持段、偵測能力、低置信項優先序／期限／狀態；多通道一致列出實際通道；"
    "高軌目標阻力通道改稱「攝動殘差」；Markdown 目錄改用固定英文錨點。",
    "R4（2026-10-30）：證據等級納入量級（|淨 Δa| ≥ 10 km 且顯著性高即列 E3）；主頁改為「重點複核項目」"
    "（連續機動段＋E2／E3 或 |淨 Δa| ≥ 1 km），其餘待觀察事件收合；新增事件密度、GEO 位置保持說明、編目一致性檢查與"
    "主要疑點、SNR 顯示上限 ≥1000、根數一致性註記（Δi★）、沿軌相位漂移 1／3／7 天量級。",
    "R3（2026-10-30）：新增證據等級、雜訊基線 SNR、連續機動段、營運先驗、抑制漏檢風險、沿軌漂移假設，以及 CSV／Markdown 匯出。",
    "R2（2026-10-29）：L1 規則候選事件與輔助通道紀錄；主頁一頁摘要＋附錄 A–F。",
]


def report_markdown(r: dict) -> str:
    """報表 Markdown 版（與 PDF 同一份計算、同源文字）。結構依 2026-10-30 第四輪審閱：目錄→版本變更→
    執行摘要→重點指標→重點複核項目→完整候選事件（<details> 收合）→附錄 C／F→資料品質與限制。
    時間一律 ISO 8601 UTC；規則候選點逐筆清單較長，只放在 CSV（record_type=rule_point）。"""
    def md_table(cols, rows, right=()):
        esc = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
        align = "|" + "".join("---:|" if c in right else "---|" for c in cols)
        return "\n".join(["| " + " | ".join(map(esc, cols)) + " |", align]
                         + ["| " + " | ".join(map(esc, row)) + " |" for row in rows])

    def as_md(text: str) -> str:
        # 【小標】轉成粗體段落標題，‧ 條列轉成 Markdown 清單
        lines = []
        for ln in text.split("\n"):
            s = ln.strip()
            if s.startswith("【") and s.endswith("】"):
                lines += ["", f"**{s[1:-1]}**", ""]
            elif s.startswith("‧"):
                lines.append("- " + s[1:].strip())
            else:
                lines.append(s)
        return "\n".join(lines)

    num = ("淨 Δa (km)", "事件淨 Δa", "最大單筆 Δa", "累計 Δa (km)", "時距 (天)", "平均速率 (km/天)", "跨度 (天)",
           "活躍日數", "速率 (km/天)", "σΔa (m)", "SNR", "規則標記", "累計 Δi (°)", "事件數", "峰值")
    dq, events = r["data_quality"], r.get("events", [])
    segs = r.get("segments") or []
    sk = r.get("station_keeping") or []
    cr_cols, cr_rows = catalog_review_table(events, iso=True)
    items, n_rest = focus_items(r)
    main, overflow = focus_split(items)
    # 目錄以固定英文錨點連結（R5）：中文標題、空格與全形符號的自動 anchor 規則在 GitHub／VS Code／Notion 不一致
    sec = [("summary", "執行摘要"), ("metrics", "重點指標"), ("satellite-info", "衛星基本資料"),
           ("altitude-history", "遠地點／近地點高度歷史"), ("detection-capability", "偵測能力"),
           ("focus", "重點複核項目")] + \
          ([("catalog-review", "編目複核紀錄")] if cr_rows else []) + \
          ([("segments", "連續機動段")] if segs else []) + \
          ([("station-keeping", "GEO 位置保持段")] if sk else []) + \
          ([("events", "完整候選事件")] if events else []) + \
          ([("low-confidence", "低置信複核項")] if r.get("low_conf") else []) + \
          [("appendix-c", "附錄 C：計數口徑與判定流程"), ("appendix-f", "附錄 F：分析註記"),
           ("limitations", "資料品質與限制"), ("version-history", "版本變更")]
    title = dict(sec)
    head = lambda k: [f'<a id="{k}"></a>', "", f"## {title[k]}", ""]
    out = [f"# 衛星軌道機動候選事件報告 — NORAD {r['norad']}", "",
           f"**NORAD {r['norad']}｜{_display_name(r.get('name'))}｜{r['orbit_class']}｜{r['start_date']}～{r['end_date']}**  ",
           f"平均高度約 {r['alt_km_avg']:.0f} km｜資料：{dq['n_raw']} 筆原始 TLE → {dq['n_tle']} 筆有效 TLE → "
           f"{dq['n_transitions']} 筆相鄰轉換" + (f"（同一 epoch 重複收錄 {dq['n_dup']} 筆已去除）" if dq["n_dup"] else "")
           + f"｜報表版本 {REPORT_VERSION}", "",
           "## 目錄", "", *[f"- [{h}](#{k})" for k, h in sec], "",
           *head("summary"), *[f"- {s}" for s in summary_sentences(r, appendix_ref="附錄 B")], "",
           *head("metrics"), md_table(["指標", "數值", "說明"], kpi_tiles(r)), "",
           *head("satellite-info")]
    info = r.get("sat_info")
    try:
        import sat_info_fetch
        irows = sat_info_fetch.info_rows(info)
    except Exception:
        irows = []
    out += ([md_table(["欄位", "值", "來源"], irows), ""] if irows else ["未取得外部基本資料。", ""])
    if info:
        out += ["查詢狀態（" + info.get("fetched_at", "") + "）："
                + "；".join(f"[{k}]({v['url']}) {v['status']}" for k, v in info["sources"].items())
                + "。外部資料僅供識別參考，與本報表 TLE 分析結果無關。", ""]
    out += [*head("altitude-history"), altitude_summary(r), ""]
    ah = r.get("alt_history")
    if ah:
        out += [f"*{alt_history_note(r)}逐日數值見下方或 CSV（record_type=alt_daily）。*", "",
                "<details>", f"<summary>逐日遠地點／近地點高度（{ah['n_days']} 點）</summary>", "",
                md_table(["日期 (UTC)", "遠地點 (km)", "近地點 (km)"],
                         [[f"{a['day']:%Y-%m-%d}", f"{a['apogee_km']:.2f}", f"{a['perigee_km']:.2f}"]
                          for _, a in ah["daily"].iterrows()], right=("遠地點 (km)", "近地點 (km)")),
                "", "</details>", ""]
    out += head("detection-capability")
    dcl = detect_cap_lines(r)
    out += ([f"- {x}" for x in dcl] + ["", "量級低於「單次事件最低可辨識量級」的機動，本方法可能無法與 TLE 雜訊區分（定義見附錄 C）。", ""]
            if dcl else ["本期轉換筆數不足，未計算偵測能力。", ""])
    out += head("focus")
    if items:
        out += ["依優先序排列：**D** 資料品質優先複核（先確認資料，再重算證據等級）；**P1** 立即複核（E3、|淨 Δa| ≥ "
                f"{E3_BIG_KM:.0f} km、有編目疑點或高優先機動段）；**P2** 排程複核（E2 或 |淨 Δa| ≥ {FOCUS_MIN_KM:.0f} km）。"
                "連續機動段以段為單位列出。", "",
                md_table(*focus_table(main, iso=True), right=num), ""]
        if overflow:
            out += [f"另有 P2 {len(overflow)} 項（{'、'.join(x['id'] for x in overflow)}）未列入主表，見「完整候選事件」。", ""]
        if n_rest:
            out += [f"其餘 {n_rest} 個待觀察事件（E1、|淨 Δa| < {FOCUS_MIN_KM:.0f} km）列於「完整候選事件」。", ""]
    else:
        out += ["本期無重點複核項目。", ""]
    if cr_rows:
        out += [*head("catalog-review"),
                "編目檢查狀態初始為「待檢查」；人工核對 NORAD 編號、國際編目號與根數族群連續性後，"
                "請於下次報表更新時改為「已排除」「疑似交叉標記」或「維持候選」。", "",
                md_table(cr_cols, cr_rows), ""]
    if segs:
        out += [*head("segments"), "同向、相鄰事件合併；累計 Δa 含段間漂移。", "",
                md_table(*segment_table(segs, iso=True), right=num), ""]
    if sk:
        out += [*head("station-keeping"),
                "東西段＝同向、相鄰的小幅 Δa 事件群組（可能是經度漂移累積或小幅推進序列，段間方向轉折為候選東西修正時點）；"
                "南北線索＝Δi 同步事件。累計 Δa 含段內未標記轉換。", "",
                md_table(*station_keeping_table(sk, iso=True), right=num), ""]
    if events:
        out += [*head("events"), "<details>",
                f"<summary>展開完整候選事件清單與事件評估（{len(events)} 筆）</summary>", "",
                "**A-1 候選事件**（事件淨 Δa＝事件首個候選轉換前至末個候選轉換後的半長軸變化）", "",
                md_table(*event_table(events, full=True, iso=True), right=num), "",
                "**A-2 事件評估**（定義見附錄 C；SNR「≥1000」為顯示上限，原始值見 CSV；Δi★＝獨立意義較高，"
                "Δe 與切向推進相容、ΔΩ 可能由 Δa 改變進動率引起，皆非獨立證據）", "",
                md_table(*assessment_table(events), right=num), "", "</details>", "",
                f"規則候選點逐筆清單（{len(r.get('landing_events', []))} 筆）見同名 CSV（record_type=rule_point）。", ""]
    if r.get("low_conf"):
        out += [*head("low-confidence"), f"未列為候選事件。檢查步驟：{LOW_CONF_STEP}。", "",
                md_table(*low_conf_table(r, iso=True), right=num), ""]
    out += [*head("appendix-c"), as_md(build_method_text(r)), "",
            *head("appendix-f"), "（以下由系統依本報表數字以固定規則產生，不經大型語言模型。）", "",
            as_md(r.get("analysis_notes") or ""), ""]
    ai = r.get("ai_explanation") or {}
    if _ai_passes(ai):
        out += ["**自動摘要（大型語言模型）**", "",
                "（SSA-RAG 知識庫檢索＋大型語言模型產生，僅供參考；與上文或主頁不一致時，以上文與主頁為準。）", "",
                ai["answer"], ""]
    cat = r.get("catalog") or {}
    cat_line = []
    if cat:
        ids = cat.get("intl_ids") or []
        cat_line = [f"- 編目一致性：line1／line2 衛星編號不一致 {cat.get('catnum_mismatch', 0)} 筆；國際編目號 "
                    + ("、".join(ids) if ids else "（未取得）")
                    + (f"，期間改變 {len(cat['intl_changes'])} 次（{'、'.join(f'{t:%Y-%m-%d}' for t in cat['intl_changes'][:5])}）"
                       if cat.get("intl_changes") else "，期間未改變") + "。"]
    out += [*head("limitations"),
            "- 所有事件均為候選，非已確認推進機動；證據等級代表複核優先順序，不代表機動發生機率。",
            "- 各輔助通道可能共享資料與特徵，多通道一致觸發不代表獨立觀測驗證。",
            "- SNR 只衡量相鄰 TLE 間的隨機起伏，不能排除定軌更新造成的系統性跳變；TLE 相對真實軌道的誤差可達數百公尺以上。",
            "- 大幅單筆 Δa 應先排除編目交叉標記、TLE 擬合異常與定軌更新，再進入機動解釋。",
            *cat_line, "",
            *head("version-history"), *[f"- {v}" for v in VERSION_NOTES], "",
            "---", f"報表版本 {REPORT_VERSION}｜分析流程 {_pipeline_version()}｜產生時間 {r['generated_at']}", ""]
    return "\n".join(out)


def _ai_passes(ai: dict) -> bool:
    """生成式摘要是否可對外附上：須確實來自 SSA-RAG，且未被服務端一致性檢查降級
    （服務端重複生成兩次結論不一致時會降信心度並附「結論不一致」提示）。"""
    if ai.get("source") != "ssa_rag":
        return False
    ans = ai.get("answer") or ""
    return str(ai.get("confidence", "")).lower() != "low" and "不一致" not in ans and "信心度降級" not in ans


def render_pdf(report_data: dict, fmt: str = "F1", source_url: str | None = None,
               app_url: str | None = None) -> bytes:
    """執行緒安全外層；參數與說明見 _render_pdf_unlocked()。"""
    with _RENDER_LOCK:
        return _render_pdf_unlocked(report_data, fmt=fmt, source_url=source_url, app_url=app_url)


def _render_pdf_unlocked(report_data: dict, fmt: str = "F1", source_url: str | None = None,
                        app_url: str | None = None) -> bytes:
    """source_url：若提供，會在摘要頁底部印該網址的 QR code（掃描可回到產生這份報表的
    原始 API 呼叫網址）。app_url：保留參數以相容既有呼叫端，但不再印 QR code——2026-10-30 起
    PDF 只留「重新產生本報表」一個（App 的 source_url 已是帶 &report= 的參數網址，掃描即開啟
    互動頁並自動產製，另一個「互動查詢儀表板」QR 重複）。"""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import FancyBboxPatch
    from matplotlib.transforms import blended_transform_factory

    _ensure_cjk_font()

    fmt = (fmt or "F1").upper()
    buf = io.BytesIO()
    r = report_data
    events = r.get("events", [])
    disp_name = _display_name(r.get("name"))
    line_h = 1.32 / 72 / _A4_PORTRAIT[1]          # 每 1 pt 字級的行高（圖面比例）
    page_w_pt = _A4_PORTRAIT[0] * 72
    # 每個段落標題、圖與表都帶衛星識別（2026-10-30）：單頁截出或列印分散時，不必翻回首頁才知道是哪顆衛星
    sat_id = f"NORAD {r['norad']}" + (f"｜{disp_name}" if r.get("name") and disp_name == r.get("name") else "")
    tag = f"［{sat_id}］"

    def _fig_tag(ax):
        """圖內左上角衛星識別：圖被單獨截出時仍可辨識。"""
        ax.text(0.005, 0.99, sat_id, transform=ax.transAxes, ha="left", va="top", fontsize=6.5, color=_MUTE_COLOR,
                zorder=10, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))

    def _date_axis(ax, labels=True):
        loc = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        ax.tick_params(labelsize=7, labelbottom=labels)
        ax.xaxis.get_offset_text().set_fontsize(7)


    _front = {"shown": None}    # 主頁實際列出的重點複核項目數；不足全數時附錄 A 補列 A-0 完整清單

    def _draw_table(fig, rect, cols, rows, widths, size=7.3, color_col=None):
        axt = fig.add_axes(rect)
        axt.axis("off")
        tbl = axt.table(cellText=rows, colLabels=cols, colWidths=widths, cellLoc="center", bbox=[0, 0, 1, 1])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(size)
        for (ri, ci), cell in tbl.get_celld().items():
            cell.set_linewidth(0.3)
            if ri == 0:
                cell.set_facecolor("#e8eef5")
            elif color_col is not None and ci == color_col and "回跳" in str(rows[ri - 1][ci]):
                cell.get_text().set_color(_SPIKE_COLOR)
        return axt

    # ── 主頁（摘要版／技術完整版共用）──────────────────────────────────────
    def _summary_page():
        fig = plt.figure(figsize=_A4_PORTRAIT, dpi=_PDF_DPI)
        fig.text(0.5, 0.972, f"衛星軌道變化分析摘要 — NORAD {r['norad']}", ha="center", va="top", fontsize=14)
        y = 0.938

        def put(text, size=9.0, color="black", width=0.88, x=0.06):
            nonlocal y
            text = _wrap_display(text, width * page_w_pt, size)
            fig.text(x, y, text, va="top", ha="left", fontsize=size, color=color)
            y -= (text.count("\n") + 1) * size * line_h + 0.005

        dq, c = r["data_quality"], r["counts"]
        put(f"NORAD {r['norad']}｜{disp_name}", 10)
        put(f"分析期間：{r['start_date']}～{r['end_date']}｜軌道：{r['orbit_class']}｜"
            f"平均高度：約 {r['alt_km_avg']:.0f} km")
        put(f"資料：{dq['n_raw']} 筆原始 TLE → {dq['n_tle']} 筆有效 TLE → {dq['n_transitions']} 筆相鄰轉換")
        note = []
        if dq["n_dup"]:
            note.append(f"同一 epoch 重複收錄 {dq['n_dup']} 筆已去除")
        if dq["dt_median_h"] is not None:
            note.append(f"TLE 間隔中位數約 {dq['dt_median_h']:.1f} 小時")
        put("（" + "；".join(note + ["細節見附錄 C" if fmt == "F2" else "細節見技術完整版附錄 C"]) + "）",
            7.5, _MUTE_COLOR)
        y -= 0.008

        # 三個重點指標
        tiles = kpi_tiles(r)
        tile_h, tile_w, gap = 0.072, 0.284, 0.014
        for i, (lab, val, sub) in enumerate(tiles):
            x0 = 0.06 + i * (tile_w + gap)
            fig.patches.append(FancyBboxPatch((x0, y - tile_h), tile_w, tile_h, transform=fig.transFigure,
                                              boxstyle="round,pad=0,rounding_size=0.006",
                                              facecolor="#f3f6fa", edgecolor="#c9d6e3", lw=0.6))
            fig.text(x0 + 0.012, y - 0.010, lab, va="top", fontsize=8, color=_MUTE_COLOR)
            fig.text(x0 + 0.012, y - 0.026, val, va="top", fontsize=15, color=_HEAD_COLOR)
            fig.text(x0 + 0.012, y - tile_h + 0.008, sub, va="bottom", fontsize=7, color=_MUTE_COLOR)
        y -= tile_h + 0.014

        for s in summary_sentences(r, appendix_ref="附錄 B" if fmt == "F2" else "技術完整版附錄 B"):
            put("‧ " + s, 9.2)
        y -= 0.006

        # 主圖：半長軸時序＋事件時段（淡色帶）＋事件編號＋主要跳變標註
        put(tag + "半長軸時序與候選事件", 10.5, _HEAD_COLOR)
        if events or c.get("drag_only"):
            put("淡色帶＝事件時段；紫色虛線＝回跳型態（資料品質待查）；上緣數字＝事件編號；"
                "標註為事件淨 Δa 最大的事件（括號內為最大單筆相鄰 TLE Δa）"
                + ("；青色橫條＝連續機動段" if r.get("segments") else "")
                + (f"；底部灰色三角＝未與候選事件重疊的{_drag_label(bool(r.get('high_orbit')))}事件"
                   if c.get("drag_only") else ""),
                7.5, _MUTE_COLOR)
        # 重點複核項目多時壓縮主圖高度，讓 D／P1 盡量都能列在主頁
        n_main = len(focus_split(focus_items(r)[0])[0])
        ch_h = 0.20 if n_main <= 4 else 0.15
        row_h, bottom_reserved = 0.0175, 0.195
        if events:   # 摘要句較多時再縮主圖，替主表（標題＋計數說明＋至多 4 列）留位，否則表會被整個擠出首頁
            ch_h = float(np.clip(y - bottom_reserved - 18 * line_h - 0.042 - row_h * (min(n_main, 4) + 1), 0.13, ch_h))
        ax = fig.add_axes([0.10, y - ch_h, 0.86, ch_h - 0.03])
        tle = r["tle_df"]
        ax.plot(tle["epoch"], tle["sma_km"], lw=1.4, color="#0072B2", zorder=3)
        _fig_tag(ax)
        ax.set_ylabel("半長軸 (km)", fontsize=8)
        ax.ticklabel_format(axis="y", useOffset=False, style="plain")   # 變化僅數十公尺時避免「+6.884e3」偏移記號
        ax.tick_params(axis="y", labelsize=7)
        _date_axis(ax)
        tf = blended_transform_factory(ax.transData, ax.transAxes)
        y -= ch_h + 0.035

        # 事件表：主頁容量不足時依單筆量級列出前 N 次，其餘見附錄 A（不縮小字級）
        title_y = y
        y -= 10.5 * line_h + 0.005 + (7.5 * line_h + 0.002 if events else 0)   # 標題＋一行計數說明
        # 不強制最少列數：摘要句多時硬塞會壓到頁底「限制說明」（SY-12 01 實測），寧可少列、其餘見附錄 A
        max_rows = max(int((y - bottom_reserved) / row_h) - 1, 0)
        # 主頁只列「重點複核項目」（機動段＋E2／E3 或 |淨 Δa| ≥ 1 km 的事件）；容量不足時依證據等級、量級取前 N 項
        items, n_rest = focus_items(r)
        main_items, overflow = focus_split(items)
        shown = main_items if len(main_items) <= max_rows else _prioritize(main_items, max_rows)
        _front["shown"] = len(shown)
        # 圖上編號只標主表列出的事件（GEO 大量 E1 事件全標會疊成一片，USA 270 實測）
        shown_no = {x["ev"]["no"] for x in shown if "ev" in x}

        span = (tle["epoch"].iloc[-1] - tle["epoch"].iloc[0]).total_seconds() or 1.0
        min_band = pd.Timedelta(seconds=span * 0.004)
        lane_last: list = [None, None, None]     # 事件密集時編號分三列交錯，避免疊字
        sma_s = tle.set_index("epoch")["sma_km"]
        for e in events:
            t0, t1, te = pd.Timestamp(e["t_start"]), pd.Timestamp(e["t_end"]), pd.Timestamp(e["main_epoch"])
            spike = e["quality_note"] == STATUS_SPIKE
            ax.axvspan(t0 - min_band / 2, max(t1, t0 + min_band / 2), color="#f5b041", alpha=0.25, lw=0, zorder=1)
            ax.axvline(te, color=_SPIKE_COLOR if spike else "#bbbbbb", lw=0.7 if spike else 0.5,
                       ls="--" if spike else "-", zorder=2)
            if e["no"] in shown_no:
                gaps = [float("inf") if t is None else (te - t).total_seconds() / span for t in lane_last]
                li = next((i for i, g in enumerate(gaps) if g > 0.025), int(np.argmax(gaps)))
                lane_last[li] = te
                ax.text(te, 1.01 + 0.075 * li, str(e["no"]), transform=tf, fontsize=6.5,
                        color=_SPIKE_COLOR if spike else "#333333", ha="center", va="bottom")
        for dstr in c.get("drag_only") or []:
            ax.plot([pd.Timestamp(dstr, tz="UTC") + pd.Timedelta(hours=12)], [0.02], marker="^", ms=5,
                    color="#888888", transform=tf, clip_on=False, zorder=4)
        for sg in r.get("segments") or []:
            ax.plot([pd.Timestamp(sg["t_start"]), pd.Timestamp(sg["t_end"])], [0.97, 0.97], transform=tf,
                    color="#16a085", lw=3, solid_capstyle="butt", zorder=4, clip_on=False)
            ax.text(pd.Timestamp(sg["t_start"]), 0.93, f"C{sg['no']} 累計 {sg['cum_da']:+.1f} km",
                    transform=tf, fontsize=6.5, color="#16a085", ha="left", va="top", zorder=5)
        annotated: list = []
        for e in sorted(events, key=lambda e: -abs(e["net_da"]))[:3]:
            te = pd.Timestamp(e["main_epoch"])
            # 太接近已標註者（< 6% 時間軸）就略過，避免標籤互相蓋住
            if abs(e["net_da"]) < 1.0 or any(abs((te - t).total_seconds()) / span < 0.06 for t in annotated):
                continue
            # 與已標註者相距 < 25% 時間軸時，垂直錯開一階，避免標籤橫向相撞
            tier = sum(abs((te - t).total_seconds()) / span < 0.25 for t in annotated)
            annotated.append(te)
            ya = float(sma_s.loc[sma_s.index <= te].iloc[-1]) if (sma_s.index <= te).any() else float(sma_s.iloc[0])
            right = (te - tle["epoch"].iloc[0]).total_seconds() / span < 0.75
            lab = f"#{e['no']} 淨 {_fmt_da(e['net_da'])} km"
            if abs(e["net_da"] - e["main_da"]) > 0.1 * abs(e["net_da"]):
                lab += f"（單筆 {_fmt_da(e['main_da'])}）"
            ax.annotate(lab, xy=(te, ya),
                        xytext=(6 if right else -6, (-12 - 13 * tier) if e["net_da"] > 0 else (10 + 13 * tier)),
                        textcoords="offset points",
                        ha="left" if right else "right", fontsize=7, color="#333333", zorder=5,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))

        app_a = "附錄 A" if fmt == "F2" else "技術完整版附錄 A"
        notes = [f"候選事件共 {len(events)} 次"]
        if len(shown) < len(items):
            notes.append(f"依優先序列出前 {len(shown)} 項，其餘見{app_a}")
        if n_rest:
            notes.append(f"其餘 {n_rest} 個待觀察事件見{app_a}")
        fig.text(0.06, title_y, tag + (f"重點複核項目（{len(items)} 項）" if events else "候選事件（共 0 次）"),
                 va="top", fontsize=10.5, color=_HEAD_COLOR)
        if events:
            fig.text(0.06, title_y - 10.5 * line_h - 0.004, "；".join(notes) + "。", va="top", fontsize=7.5,
                     color=_MUTE_COLOR)
        if shown:
            tab_h = row_h * (len(shown) + 1)
            _draw_table(fig, [0.06, y - tab_h, 0.88, tab_h], *focus_table(shown, short=15, compact=True),
                        [0.09, 0.15, 0.07, 0.12, 0.22, 0.24, 0.11], color_col=4)
        elif events:
            fig.text(0.06, y, f"本期無重點複核項目；待觀察事件見{app_a}。" if not items
                     else f"主頁版面不足，重點複核項目見{app_a}。", va="top", fontsize=9)
        elif r.get("low_conf"):
            lc_cols, lc_rows = low_conf_table(r)
            fig.text(0.06, y, f"本期間無候選事件。低置信複核項（未列為候選事件，{len(lc_rows)} 筆）：",
                     va="top", fontsize=9)
            y -= 9 * line_h + 0.008
            lc_rows = lc_rows[:max(max_rows - 1, 1)]
            tab_h = row_h * (len(lc_rows) + 1)
            _draw_table(fig, [0.06, y - tab_h, 0.88, tab_h], lc_cols, lc_rows,
                        [0.06, 0.06, 0.20, 0.16, 0.18, 0.07, 0.15, 0.12])
            y -= tab_h + 0.006
            fig.text(0.06, y, f"檢查步驟：{LOW_CONF_STEP}。", va="top", fontsize=7.5, color=_MUTE_COLOR)
        else:
            fig.text(0.06, y, "本期間無候選事件。", va="top", fontsize=9)

        # 限制說明＋QR（固定在頁底）
        y = 0.185
        put(tag + "限制說明", 9.5, _HEAD_COLOR)
        lim = ["‧ 未取得營運者公告或獨立精密星曆，所有事件皆為候選、非已確認推進機動；證據等級僅代表複核優先順序。",
               "‧ 各輔助通道可能共享資料與特徵，多通道一致觸發不代表獨立觀測驗證。",
               "‧ 依公開 TLE 分析，時間解析度受 TLE 更新頻率限制；TLE 相對真實軌道的誤差可達數百公尺以上，"
               "SNR 只衡量相鄰 TLE 間的隨機起伏。"]
        for s in lim:
            put(s, 7.8, width=0.70)
        put(f"報表產生時間：{r['generated_at']}", 7, _MUTE_COLOR)

        if source_url:
            qa = fig.add_axes([0.80, 0.035, 0.14, 0.14])
            qa.imshow(_qr_image(source_url), cmap="gray")
            qa.axis("off")
            qa.set_title("重新產生本報表", fontsize=6.5, pad=2)
        return fig

    # ── 附錄共用 ─────────────────────────────────────────────────────────
    def _new_page(title: str):
        fig = plt.figure(figsize=_A4_PORTRAIT, dpi=_PDF_DPI)
        fig.text(0.06, 0.965, title, va="top", fontsize=13, color=_HEAD_COLOR)
        fig.text(0.94, 0.962, sat_id, va="top", ha="right", fontsize=10, color=_HEAD_COLOR)
        return fig

    def _text_pages(title: str, text: str, size: float = 8.5):
        lines = _wrap_display(text, 0.88 * page_w_pt, size).split("\n")
        cap = int(0.85 / (size * line_h))
        figs = []
        for k in range(0, max(len(lines), 1), cap):
            fig = _new_page(title + ("（續）" if k else ""))
            fig.text(0.06, 0.93, "\n".join(lines[k:k + cap]), va="top", ha="left", fontsize=size)
            figs.append(fig)
        return figs

    def _table_pages(title: str, blocks: list[dict]):
        """表格自動分頁：表頭跨頁重複；split=2 時左右兩欄並排；group 欄相同的列盡量不拆頁。"""
        top, bottom, row_h, sub_h = 0.925, 0.06, 0.0165, 0.03
        figs = [_new_page(title)]
        y = top
        for b in blocks:
            rows, split, k, first = b["rows"], b.get("split", 1), 0, True
            while k < len(rows) or first:
                fit = int((y - sub_h - bottom) / row_h) - 1
                if fit < 3:
                    figs.append(_new_page(title + "（續）"))
                    y = top
                    continue
                cap = fit * split
                cut = min(len(rows), k + cap)
                g = b.get("group")
                if g is not None and cut < len(rows):
                    c2 = cut
                    while c2 > k and rows[c2][g] == rows[c2 - 1][g]:
                        c2 -= 1
                    if c2 - k >= cap // 2:
                        cut = c2
                chunk = rows[k:cut]
                fig = figs[-1]
                sub = _wrap_display(tag + b["subtitle"] + ("" if first else "（續）"), 0.88 * page_w_pt, 9.5)
                fig.text(0.06, y, sub, va="top", fontsize=9.5, color=_HEAD_COLOR)
                y -= sub_h + sub.count("\n") * 9.5 * line_h
                per = -(-len(chunk) // split) if chunk else 0
                col_w = (0.88 - 0.03 * (split - 1)) / split
                for s in range(split):
                    part = chunk[s * per:(s + 1) * per]
                    if not part:
                        continue
                    h = row_h * (len(part) + 1)
                    _draw_table(fig, [0.06 + s * (col_w + 0.03), y - h, col_w, h], b["cols"], part,
                                b["widths"], color_col=b.get("color_col"))
                y -= row_h * (per + 1) + 0.025
                k, first = cut, False
                if not rows:
                    break
        return figs

    def _appendix_a():
        ev_cols, ev_rows = event_table(events, full=True)
        # PDF 表格儲存格不換行：主要疑點過長時截斷，完整文字見 CSV／Markdown
        ev_rows = [row[:-1] + [row[-1] if len(row[-1]) <= 18 else row[-1][:17] + "…"] for row in ev_rows]
        pt_rows = [[f"{pd.Timestamp(p['epoch']):%Y-%m-%d %H:%M}", f"{p['sma_delta']:+.3f}",
                    f"#{p['event_no']}" if p.get("event_no") else "—"] for p in r["landing_events"]]
        as_cols, as_rows = assessment_table(events)
        sg_cols, sg_rows = segment_table(r.get("segments") or [])
        sk_cols, sk_rows = station_keeping_table(r.get("station_keeping") or [])
        cr_cols, cr_rows = catalog_review_table(events)
        extra = []
        if sg_rows:
            extra.append({"subtitle": "連續機動段（同向、相鄰事件合併；累計 Δa 含段間漂移）",
                          "cols": sg_cols, "rows": sg_rows, "widths": [0.08, 0.22, 0.16, 0.13, 0.10, 0.15, 0.16]})
        if sk_rows:
            extra.append({"subtitle": "GEO 位置保持段（東西＝同向小幅 Δa 群組，段間轉折為候選修正時點；南北＝Δi 同步線索）",
                          "cols": sk_cols, "rows": sk_rows,
                          "widths": [0.05, 0.15, 0.17, 0.12, 0.06, 0.09, 0.09, 0.07, 0.11, 0.09]})
        if cr_rows:
            extra.append({"subtitle": "編目複核紀錄（狀態於人工核對後更新為「已排除／疑似交叉標記／維持候選」）",
                          "cols": cr_cols, "rows": cr_rows, "widths": [0.06, 0.24, 0.28, 0.10, 0.17, 0.15]})
        for i, b in enumerate(extra, 3):
            b["subtitle"] = f"A-{i} " + b["subtitle"]
        a0 = []
        f_items, _ = focus_items(r)
        if _front["shown"] is not None and _front["shown"] < len(f_items):
            # 主頁容量不足：A-0 列出全部重點複核項目（含 P2 溢出）
            fc, fr = focus_table(f_items, short=24, compact=True)
            a0 = [{"subtitle": f"A-0 重點複核項目完整清單（{len(f_items)} 項；主頁列出前 {_front['shown']} 項）",
                   "cols": fc, "rows": fr, "widths": [0.09, 0.15, 0.07, 0.12, 0.26, 0.20, 0.11], "color_col": 4}]
        return _table_pages("附錄 A　候選事件、事件評估與規則候選點清單", [
            *a0,
            {"subtitle": f"A-1 候選事件（{len(events)} 次；事件淨 Δa＝事件首個候選轉換前至末個候選轉換後的半長軸變化）",
             "cols": ev_cols, "rows": ev_rows,
             "widths": [0.05, 0.18, 0.07, 0.07, 0.08, 0.05, 0.12, 0.07, 0.11, 0.20], "color_col": 9},
            {"subtitle": "A-2 事件評估（定義見附錄 C；外部複核狀態：均為「無」）",
             "cols": as_cols, "rows": as_rows,
             "widths": [0.05, 0.07, 0.07, 0.09, 0.07, 0.06, 0.06, 0.10, 0.17, 0.26], "color_col": 9},
            *extra,
            {"subtitle": f"A-{3 + len(extra)} 規則候選點（L1 標記之相鄰 TLE 轉換，{len(pt_rows)} 筆；Δa 單位 km）",
             "cols": ["時間 (UTC)", "Δa (km)", "事件"], "rows": pt_rows, "widths": [0.5, 0.3, 0.2],
             "split": 2, "group": 2},
        ])

    # ── 附錄 B：阻力模型殘差（或 Starlink 之融合分數）與候選事件 ────────────────
    def _timeline_page():
        """與案例研究簡報同一繪圖程式（detection_timeline.py）；標題與註腳改為「候選事件」
        口徑，避免把殘差異常直接等同推進機動。"""
        import detection_timeline as dtl

        fig = plt.figure(figsize=(11.69, 8.27), dpi=_PDF_DPI)  # A4 橫向
        fig.patch.set_facecolor(dtl.BG)
        name = r.get("name") or ""
        label = f"NORAD {r['norad']}"
        fusion, drag = r.get("fusion_df"), r.get("drag_df")
        if "STARLINK" in name.upper() and fusion is not None and len(fusion):
            kind = "fusion"
            ts = fusion[["epoch", "fusion"]].copy()
            ts["thr"] = float(fusion.attrs.get("thr", 0.659))
            what = "融合評分器分數"
            src = ("序列：融合評分器（L3）逐 epoch 分數；門檻以上、相隔 48 小時內之點合併為一次候選事件，標示峰值日期。"
                   "分數為模型輸出，未經本族群校準，不代表機動發生機率。")
        elif drag is not None and len(drag):
            kind = "drag"
            ts = drag
            what = "阻力模型殘差"
            src = (f"序列：NRLMSIS 大氣阻力殘差（扣除阻力模型預測後之 Δa 殘差絕對值）；|殘差|＞{DRAG_EVENT_KM:.2f} km、"
                   "相隔 48 小時內合併為一次殘差候選事件。殘差異常不等同推進機動，色階依量級分級。")
        else:
            ax = fig.add_axes([0.06, 0.1, 0.88, 0.8]); ax.axis("off")
            ax.text(0, 0.95, f"附錄 B　{label}\n\n本區間無可用之融合評分器或阻力殘差序列"
                    "（資料筆數不足或太空天氣資料缺漏），略過此圖。",
                    color=dtl.INK, fontsize=12, va="top", transform=ax.transAxes)
            return fig

        reps, n_lanes = dtl.prepare(ts, kind)
        reentry = kind == "drag" and bool(ts["reentry"].iloc[0])
        note = "（偵測到自然再入衰減模式，物理閘門已抑制事件判定）" if reentry else None
        h_in = 6.4
        top, bottom = 1 - 0.95 / 8.27, 1 - (h_in + 0.3) / 8.27
        ax = fig.add_axes([0.08, bottom, 0.89, top - bottom])
        dtl.draw_timeline(ax, ts, kind, label, reps, n_lanes, note=note)
        ax.set_title(f"附錄 B　{label}　{what}與候選事件（共 {len(reps)} 次{'殘差' if kind == 'drag' else '超門檻'}候選事件）",
                     color=dtl.INK, fontsize=14, pad=12, loc="left")
        foot = [src, "本頁事件依上圖序列判定，與主頁「候選事件」（L1 規則式）口徑不同，數量可能不一致。"]
        fig.text(0.08, max(bottom - 0.06, 0.04), _wrap_cjk_text("\n".join(foot), width=140),
                 color=dtl.MUTE, fontsize=8.5, va="top")
        return fig

    # ── 附錄 D：各通道原始輸出（小多圖，各自縱軸）────────────────────────────
    def _scores_page():
        fig = _new_page("附錄 D　L2 統計通道與 L3 融合評分器原始輸出")
        tle = r["tle_df"]
        l2raw = r["l2_raw"]
        fus = r.get("fusion_df")
        panels = [ch for ch in ("cusum", "bocpd", "ssa", "mad3sig") if ch in l2raw]
        n = len(panels) + 1
        top, bottom, gap = 0.90, 0.07, 0.018
        h = (top - bottom - gap * (n - 1)) / n
        axes = []
        for i in range(n):
            ax = fig.add_axes([0.11, top - (i + 1) * h - i * gap, 0.85, h],
                              sharex=axes[0] if axes else None)
            axes.append(ax)
        for ax, ch in zip(axes, panels):
            ax.plot(tle["epoch"], np.abs(l2raw[ch]["scores"]), lw=0.7, color="#555555")
            ax.set_ylabel(ch, fontsize=8)
            ax.tick_params(axis="y", labelsize=6.5)
            _date_axis(ax, labels=False)
            _fig_tag(ax)
        axf = axes[-1]
        if fus is not None and len(fus):
            axf.plot(fus["epoch"], fus["fusion"], lw=0.7, color="#555555")
            axf.axhline(r["l3"]["fusion_thr"], color="#c0392b", ls="--", lw=0.9)
            axf.set_ylim(0, 1.02)
        else:
            axf.text(0.01, 0.5, "本次無可用之融合評分器模型。", fontsize=8, transform=axf.transAxes)
        axf.set_ylabel("L3 融合", fontsize=8)
        _fig_tag(axf)
        axf.tick_params(axis="y", labelsize=6.5)
        _date_axis(axf)
        fig.text(0.06, 0.925, "上四圖為 L2 各通道分數絕對值（各自縱軸，尺度不可互比）；最下圖為 L3 融合評分器分數"
                 + (f"（虛線＝操作門檻 {r['l3']['fusion_thr']:.3f}；未經本族群校準，不代表機動發生機率）"
                    if r["l3"]["fusion_thr"] is not None else ""), va="top", fontsize=7.5, color=_MUTE_COLOR)
        return fig

    # ── 附錄 E：軌道根數連續變化與差值 ───────────────────────────────────────
    def _elements_page():
        tle, tr = r["tle_df"], r["tr_df"]
        fig = plt.figure(figsize=_A4_PORTRAIT, dpi=_PDF_DPI)
        fig.suptitle(f"附錄 E　軌道根數連續變化與差值　{tag}", fontsize=13, color=_HEAD_COLOR)
        rows = [
            ("sma_km", "半長軸 a (km)", "da_km", "Δa (km)"),
            ("inclination_deg", "傾角 i (deg)", "di_deg", "Δi (deg)"),
            ("eccentricity", "離心率 e", "de", "Δe"),
            ("raan_deg", "RAAN (deg)", "draan_res_deg", "ΔRAAN 殘差 (deg)"),
        ]
        for i, (col_l, title_l, col_r, title_r) in enumerate(rows):
            axl = fig.add_subplot(4, 2, 2 * i + 1)
            axl.plot(tle["epoch"], tle[col_l], lw=0.7, color="#0072B2")
            axl.set_title(title_l, fontsize=9)
            _fig_tag(axl)
            _date_axis(axl)
            axr = fig.add_subplot(4, 2, 2 * i + 2)
            if len(tr):
                axr.plot(tr["epoch"], tr[col_r], lw=0.6, color="#888888")
            axr.set_title(title_r, fontsize=9)
            _fig_tag(axr)
            _date_axis(axr)
        fig.tight_layout(rect=[0, 0.03, 1, 0.96])
        return fig

    # ── 附錄 F：分析註記（固定格式；生成式摘要僅在通過一致性檢查時附上）──────────
    def _notes_text() -> str:
        ai = r["ai_explanation"]
        out = ["（以下三段由系統依本報表數字以固定規則產生，不經大型語言模型。）", "",
               r.get("analysis_notes") or ai["answer"], "", "【自動摘要（大型語言模型）】"]
        if _ai_passes(ai):
            out += ["（SSA-RAG 知識庫檢索＋大型語言模型產生，僅供參考；與上文或主頁不一致時，以上文與主頁為準。）",
                    ai["answer"]]
        elif ai.get("source") == "ssa_rag":
            out.append("本次自動摘要未通過一致性檢查，已省略。")
        else:
            out.append("本次 AI 解說服務未連線，未產生自動摘要。")
        return "\n".join(out)

    # ── 第 2 頁：衛星基本資料（N2YO／KeepTrack）與遠地點／近地點高度歷史 ───────────────
    def _alt_info_page():
        fig = _new_page("衛星基本資料與遠地點／近地點高度歷史")
        ah = r.get("alt_history")
        fig.text(0.06, 0.928, _wrap_display(tag + altitude_summary(r), 0.88 * page_w_pt, 9), va="top", fontsize=9)
        if ah:
            d = ah["daily"]
            ax = fig.add_axes([0.10, 0.55, 0.76, 0.32])
            for e in events:   # 候選事件時段淡色帶，對照主頁事件編號
                t0, t1 = pd.Timestamp(e["t_start"]), pd.Timestamp(e["t_end"])
                ax.axvspan(t0, max(t1, t0 + pd.Timedelta(hours=12)), color="#f5b041", alpha=0.18, lw=0, zorder=1)
            for col, color, lab in (("apogee_km", "#2563eb", "遠地點"), ("perigee_km", "#dc2626", "近地點")):
                ax.plot(d["day"], d[col], color=color, lw=1.6, zorder=3)
                ax.text(1.01, d[col].iloc[-1], lab, transform=blended_transform_factory(ax.transAxes, ax.transData),
                        fontsize=8.5, color=color, va="center")
            ax.set_ylabel("高度 (km)", fontsize=8)
            _fig_tag(ax)
            ax.ticklabel_format(axis="y", useOffset=False, style="plain")
            ax.tick_params(axis="y", labelsize=7)
            ax.grid(axis="y", color="#e5e7eb", lw=0.6)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            _date_axis(ax)
            fig.text(0.06, 0.515, _wrap_display(f"藍線＝遠地點、紅線＝近地點、淡色帶＝候選事件時段。{alt_history_note(r)}",
                                                0.88 * page_w_pt, 7.5), va="top", fontsize=7.5, color=_MUTE_COLOR)
        y = 0.465
        fig.text(0.06, y, tag + "衛星基本資料（外部公開來源自動查詢）", va="top", fontsize=10.5, color=_HEAD_COLOR)
        y -= 0.03
        info = r.get("sat_info")
        try:
            import sat_info_fetch
            rows = sat_info_fetch.info_rows(info)
        except Exception:
            rows = []
        rows = [[k, v if len(v) <= 60 else v[:59] + "…", s] for k, v, s in rows][:16]
        if rows:
            h = 0.0175 * (len(rows) + 1)
            _draw_table(fig, [0.06, y - h, 0.88, h], ["欄位", "值", "來源"], rows, [0.20, 0.62, 0.18])
            y -= h + 0.015
        else:
            fig.text(0.06, y, "未取得外部基本資料。", va="top", fontsize=9)
            y -= 0.03
        if info:
            st = "；".join(f"{k}：{v['status']}（{v['url']}）" for k, v in info["sources"].items())
            fig.text(0.06, y, _wrap_display(f"查詢狀態（{info.get('fetched_at', '')}）：{st}。外部資料僅供識別參考，"
                                            "與本報表 TLE 分析結果無關；欄位以來源網站原文呈現。",
                                            0.88 * page_w_pt, 7.5), va="top", fontsize=7.5, color=_MUTE_COLOR)
        return fig

    figs = [_summary_page(), _alt_info_page()]
    if fmt == "F2":
        figs += _appendix_a()
        figs.append(_timeline_page())
        figs += _text_pages("附錄 C　計數口徑與判定流程", build_method_text(r))
        figs.append(_scores_page())
        figs.append(_elements_page())
        figs += _text_pages("附錄 F　分析註記", _notes_text(), size=9)

    footer = (f"NORAD {r['norad']}｜{r['start_date']}～{r['end_date']}｜"
              f"{'摘要版' if fmt != 'F2' else '技術完整版'}｜報表版本 {REPORT_VERSION}｜"
              f"分析流程 {_pipeline_version()}")
    with PdfPages(buf) as pdf:
        for i, f in enumerate(figs, 1):
            f.text(0.5, 0.012, f"{footer}｜第 {i}／{len(figs)} 頁", ha="center", va="bottom",
                   fontsize=6.5, color="#888888")
            pdf.savefig(f)
            plt.close(f)

    return buf.getvalue()
