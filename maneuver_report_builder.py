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
        for table, col in (("sat_n2yo_metadata", "name"), ("catalog", "name")):
            try:
                r = con.execute(
                    f"SELECT {col} FROM {table} WHERE norad_id=? LIMIT 1", [int(norad_id)]
                ).fetchone()
                if r and r[0]:
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

    idxs = np.arange(1, len(dd))
    if len(idxs) > 220:
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


# ── AI 思維過程說明（SSA-RAG，best-effort；離線／逾時自動退回規則式敘述）──────
RAG_DEFAULT_URL = os.environ.get("SSA_RAG_URL", "http://127.0.0.1:8000")
RAG_TIMEOUT_S = float(os.environ.get("SSA_RAG_TIMEOUT_S", "120"))


def build_tle_maneuver_narrative(satellite_id, alt_km_avg, start_date: str,
                                 end_date: str, event_df: pd.DataFrame) -> str:
    """LEO/MEO TLE 自適應偵測結果 → 自然語言描述（與 app 內同名函式邏輯一致）。"""
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
            "恒為正、不代表方向。")
        lines.append(
            "請根據以上偵測結果解說：這種半長軸跳變模式最可能對應哪種機動類型"
            "（軌道維持、軌道抬升、避碰或離軌）？機動後 TLE 失效對 conjunction "
            "screening 有什麼影響？")
    else:
        lines.append(
            "請解說：此期間未偵測到明顯機動的可能原因有哪些？"
            "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return "\n".join(lines)


_STRATEGY_LABELS = {
    "P2": "P2 高度自適應 Δa 閾值",
    "P5": "P5 F10.7 太陽活動強度調整",
    "P6": "P6 星座／傾角族群基準倍率",
    "P4": "P4 相鄰窗口補充判定",
    "other(di/de/dΩ)": "其他根數（Δi／Δe／ΔRAAN）異常",
    "P1_suppress": "P1 單調衰減抑制（判為大氣阻力自然衰減）",
    "P3_suppress": "P3 高 B* 抑制（判為阻力可解釋、非機動）",
}


def build_pipeline_logic_text(r: dict) -> str:
    """給客戶看的「系統思維邏輯」說明：L1／L2 各自看到什麼徵候、L3 如何從這些徵候
    篩出可信結果——與 render_pdf() 的 AI 思維過程說明頁（LLM 自由文字）互補，
    這裡是決定論、可逐項對照原始數字重現的規則式敘述，不經過 LLM。"""
    l1 = r["l1"]
    sc = l1.get("strategy_counts", {})
    detect_keys = ["P2", "P5", "P6", "P4", "other(di/de/dΩ)"]
    suppress_keys = ["P1_suppress", "P3_suppress"]
    detect_parts = [f"{_STRATEGY_LABELS[k]} {sc.get(k, 0)} 次" for k in detect_keys if k in sc]
    suppress_parts = [f"{_STRATEGY_LABELS[k]} {sc.get(k, 0)} 次" for k in suppress_keys if k in sc]

    lines = [
        "【L1 規則式（P1–P6）看到的徵候】",
        f"本區間共 {l1.get('n_transitions', 0)} 筆相鄰 TLE 轉換。各項判定各自標記候選異常次數："
        + "、".join(detect_parts) + "。",
        "其中會被視為「非機動」而扣除的抑制判定：" + "、".join(suppress_parts)
        + "（連續小幅衰減、無大跳變、且 B* 為正／偏高，較符合大氣阻力自然衰減的特徵）。",
        f"偵測（聯集）扣除抑制後，L1 最終合併標記 {l1['n_flagged']} 次候選機動轉換。",
        "",
        "【L2 統計變點通道看到的徵候】",
        "L2 由四種原理互不相同、且不依賴軌道物理閾值的統計變點演算法各自獨立掃描"
        "半長軸（SMA）時序，純粹從數列本身的統計特徵（均值/變異數突變、貝氏變點機率、"
        "奇異譜分解殘差、3σ 穩健離群值）找出可疑轉折點：",
    ]
    for ch, v in r["l2"].items():
        lines.append(f"  {ch}：{v['n_events']} 次")
    lines.append(
        "這四個通道彼此獨立、對雜訊的敏感方式不同，任一通道單獨觸發都可能只是雜訊"
        "或量測誤差，需要交叉比對才能判斷是否為真實機動。")
    lines += [
        "",
        "【L3 如何從這些徵候中篩出可信結果】",
    ]
    l3 = r["l3"]
    if l3["fusion_available"]:
        lines.append(
            f"融合評分器（L3）把 L2 四通道分數＋大氣阻力殘差，整合成同一組學習到的"
            f"機率模型，逐窗口輸出單一「機動機率」；本報表區間內最高機率為 "
            f"{l3['fusion_max_prob']:.3f}，判定門檻為 {l3['fusion_thr']:.3f}"
            f"（門檻以歷史標註資料訓練/校準得出，非人為拍板）。"
            f"單一通道分數再高，若無法讓融合機率跨過此門檻，仍會被判為不可信、"
            f"不列入最終落點；反之，跨過門檻代表多個徵候在同一時間窗口相互佐證，"
            f"才視為可信的機動候選。")
    else:
        lines.append("融合評分器（L3）本次無可用模型檔，略過此層篩選。")
    if l3["ml_available"]:
        lines.append(
            f"逐窗 ML 模型（L3）另以獨立訓練的門檻，在本區間標記 {l3['ml_n_flagged']} 次候選窗口，"
            "作為與融合評分器互相驗證的第二道判斷。")
    src_txt = {
        "l1_combined": "本報表最終列出的機動偵測落點，以 L1 規則式合併結果為準"
                       "（L1 有標記時優先採用，判定依據最直接對應到單一 TLE 轉換的時間點）。",
        "l3_fusion_fallback": "本區間 L1 規則式未標記任何候選，故改以 L3 融合評分器機率"
                              "跨過門檻的時間窗口為準，列為最終機動偵測落點。",
        "none": "本區間 L1／L3 皆無可用判定結果，故無機動偵測落點。",
    }.get(r.get("landing_source", "none"), "")
    lines.append(src_txt)
    lines.append(f"最終列出機動偵測落點共 {len(r['landing_events'])} 筆（詳見摘要頁清單）。")

    pr = r.get("phase_residual_experimental")
    if pr:
        lines += ["", "【補充觀察指標（實驗性）：相位殘差通道】"]
        if pr["status"] != "ok":
            lines.append("本區間資料不足，無法計算相位殘差補充指標。")
        else:
            lines.append(
                f"針對 L1/L2/L3 皆作用於半長軸、對「相位調整（phasing）機動」"
                f"（軌道週期暫時改變、事後幾乎完全恢復，半長軸幾乎不變但沿軌位置"
                f"累積偏移）structurally 看不見的已知盲區，另計算一項相位殘差訊號"
                f"（緯度幅角實際值 vs. 前一筆外推預測值之差，換算為沿軌弧長 km），"
                f"本區間標記 {pr['n_flags']} 次候選異常"
                + (f"、最大絕對殘差 {pr['max_abs_residual_km']:.2f} km" if pr['max_abs_residual_km'] is not None else "")
                + "。**此指標僅供參考，不併入上述 L1/L2/L3 判定或機動偵測落點清單**："
                  "獨立驗證顯示其準確度（23 星標竿 macro F1≈0.10）遠低於本報表主要"
                  "偵測方法，且完整驗證工作尚未完成，結果應視為候選假說而非已驗證"
                  "結論（詳見 docs/相位殘差通道_新增偵測管道實作與驗證_20260913.md）。")
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
                "source": "rule_based_fallback（SSA-RAG 服務未回應／未啟用）"}
    try:
        from ssa_rag_client import SSARAGClient
    except ImportError:
        return fallback
    try:
        client = SSARAGClient(base_url=RAG_DEFAULT_URL, timeout=RAG_TIMEOUT_S)
        if not client.health():
            return fallback
        result = client.ask(query, topic=topic, client_id="maneuver_report_api")
        return {"answer": result.answer, "confidence": result.confidence, "source": "ssa_rag"}
    except Exception as e:
        logger.warning("SSA-RAG 呼叫失敗，退回規則式敘述：%s", e)
        return fallback


# ── 整合：單一衛星＋日期區間 → 報表資料結構 ──────────────────────────────────
class ReportNotFoundError(ValueError):
    """NORAD 查無資料，或指定區間內 TLE 筆數不足——呼叫端（report_api.py）應回 404，
    與其他非預期例外（程式錯誤）明確區分，後者一律回 500 並記錄完整 traceback。"""


def build_report_data(norad: int, start_date: date, end_date: date, lang: str = "zh") -> dict:
    """回傳給 render_pdf() 用的統一結構。任何一層缺資料只記錄 None／空值，
    不中斷整體報表產製（維持「部分資訊也要能出報表」的可用性優先原則）。"""
    d0, d1 = start_date, end_date
    name = satellite_name(norad)
    df_full = load_tle(norad)
    if df_full.empty:
        raise ReportNotFoundError(f"NORAD {norad} 查無 TLE 資料")
    df = df_full[(df_full["epoch"].dt.date >= d0) & (df_full["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(df) < 3:
        raise ReportNotFoundError(f"NORAD {norad} 在 {d0}~{d1} 區間內 TLE 筆數不足（{len(df)} 筆，需至少 3 筆）")

    f107 = load_f107()
    l1 = compute_l1(df, f107, lang=lang)

    l2_raw = compute_l2(df)
    l2 = {}
    for k, v in l2_raw.items():
        ev = v.get("events")
        l2[k] = {"n_events": 0 if ev is None else len(ev)}

    ml = compute_ml_detection(norad, d0, d1)
    fusion = compute_fusion_detection(norad, d0, d1)
    l3 = {
        "ml_available": ml is not None,
        "ml_n_flagged": int(ml[0]["flag"].sum()) if ml is not None else None,
        "fusion_available": fusion is not None,
        "fusion_max_prob": float(fusion["fusion"].max()) if fusion is not None and len(fusion) else None,
        "fusion_thr": float(fusion.attrs.get("thr")) if fusion is not None else None,
    }

    # 機動落點清單（以 L1 combined flag 對應之 epoch 為主，L1 缺資料時退回 L3 融合門檻以上者）
    if len(l1["combined"]):
        hit_idx = np.where(l1["combined"])[0]
        landing_epochs = df["epoch"].iloc[hit_idx].tolist() if len(hit_idx) else []
        landing_source = "l1_combined"
    elif fusion is not None and l3["fusion_thr"] is not None:
        landing_epochs = fusion.loc[fusion["fusion"] >= l3["fusion_thr"], "epoch"].tolist()
        landing_source = "l3_fusion_fallback"
    else:
        landing_epochs = []
        landing_source = "none"

    # L1 各子策略觸發次數（②系統偵測邏輯頁用）：P2/P5/P6/other 為「偵測」，
    # P1/P3 為「抑制」（判定為大氣阻力自然衰減、非機動而剔除的候選）。
    per_strategy = l1["detail"].get("per_strategy", {})
    l1_strategy_counts = {k: int(np.sum(v)) for k, v in per_strategy.items()}
    l1_n_transitions = len(l1["tr"])

    # 補充觀察指標（實驗性，見案例二十一）：不影響 landing_events／l1/l2/l3 任何判定
    phase_residual = compute_phase_residual_experimental(df)

    alt_km_avg = float(df["sma_km"].mean() - R_E)
    event_df = pd.DataFrame({"epoch": landing_epochs})
    if len(event_df):
        # L1 detail 若有 sma_delta/方向資訊則沿用；否則以相鄰 TLE 差分近似
        sma = df.set_index("epoch")["sma_km"]
        deltas, directions = [], []
        for e in event_df["epoch"]:
            pos = df.index[df["epoch"] == e]
            i = int(pos[0]) if len(pos) else None
            d = float(sma.iloc[i] - sma.iloc[i - 1]) if i and i > 0 else 0.0
            deltas.append(d)
            directions.append("raise" if d >= 0 else "lower")
        event_df["sma_delta"] = deltas
        event_df["sma_direction"] = directions

    narrative_tle = build_tle_maneuver_narrative(
        norad, alt_km_avg, str(d0), str(d1), event_df)
    rag_query = _rag_query_from_narrative(narrative_tle, len(event_df))
    ai_explanation = get_ai_explanation(rag_query, fallback_text=narrative_tle, topic="maneuver")

    return {
        "norad": norad, "name": name, "start_date": str(d0), "end_date": str(d1),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "orbit_class": l1["orbit_class"], "inc_family": l1["inc_family"],
        "alt_km_avg": alt_km_avg, "n_tle": len(df),
        "l1": {"n_flagged": l1["n_flagged"], "n_transitions": l1_n_transitions,
               "strategy_counts": l1_strategy_counts},
        "l2": l2,
        "l3": l3,
        "phase_residual_experimental": phase_residual,
        "landing_events": event_df.to_dict("records"),
        "landing_source": landing_source,
        "narrative": narrative_tle,
        "ai_explanation": ai_explanation,
        "tle_df": df,          # 給 render_pdf 畫時序圖用，不落入 JSON 序列化路徑
        "l2_raw": l2_raw,      # 同上
        "fusion_df": fusion,   # 同上
        "tr_df": l1["tr"],     # 同上：軌道根數逐轉換差值（da/di/de/draan_res），供①根數圖用
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


# ── PDF 產製：F1 簡版（1 頁）／F2 完整版（多頁，含圖表＋AI 說明）──────────────
def render_pdf(report_data: dict, fmt: str = "F1", source_url: str | None = None,
               app_url: str | None = None) -> bytes:
    """source_url：若提供，會在摘要頁左下角印該網址的 QR code
    （掃描可回到產生這份報表的原始 API 呼叫網址）。
    app_url：若提供，會在摘要頁右下角另印一個 QR code（掃描可直接開啟互動式
    儀表板 app，並自動預填這顆衛星與日期區間——見 maneuver_app_2026SOctober.py
    的 ?mode=tool&norad=&d0=&d1= 深連結支援）。"""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    _ensure_cjk_font()

    fmt = (fmt or "F1").upper()
    buf = io.BytesIO()
    r = report_data

    # 頁面容量（行數）以 fontsize=9、預設行距估算：有 QR code 時留白較多，容量較小；
    # 續頁沒有 QR，容量較大。曾在 ISS（NORAD 25544，87 筆機動落點）發現：拿掉 20 筆
    # 截斷後（"請不要省略"），落點多的衛星仍會被 matplotlib 無聲裁到頁面外看不到
    # ——這裡改成「印不下就自動另開續頁」，而非再度截斷或無限縮小字級。
    FIRST_PAGE_CAP = 55 if (source_url or app_url) else 62
    CONT_PAGE_CAP = 62

    def _text_page(fig, lines: list[str], title: str | None = None, draw_qr: bool = False):
        fig.clf()
        if title:
            fig.suptitle(title, fontsize=16)
        text_bottom = 0.18 if draw_qr else 0.06
        top = 0.94 if title else 0.96
        ax = fig.add_axes([0.06, text_bottom, 0.88, top - text_bottom])
        ax.axis("off")
        # 不強制 family="monospace"：該字型不含中文全形標點（全形括號等會變缺字方框），
        # 沿用 rcParams 設定之中文字型即可，犧牲數字欄位等寬對齊換取正確顯示中文標點。
        ax.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=9,
                transform=ax.transAxes)

        if draw_qr and source_url:
            qr_ax = fig.add_axes([0.24, 0.02, 0.16, 0.16])
            qr_ax.imshow(_qr_image(source_url), cmap="gray")
            qr_ax.axis("off")
            qr_ax.set_title("重新產生本報表", fontsize=6.5, pad=2)
            label_ax = fig.add_axes([0.02, 0.005, 0.46, 0.03])
            label_ax.axis("off")
            # clip_on=True：網址長度不固定（不同 NORAD／日期），太長時寧可被裁掉，
            # 也不能讓文字溢出邊框跟右邊那組 QR 的網址文字疊在一起、變成兩行黏一起。
            label_ax.text(0.5, 0.5, source_url, ha="center", va="center", fontsize=5,
                          clip_on=True, transform=label_ax.transAxes)

        if draw_qr and app_url:
            qr_ax2 = fig.add_axes([0.60, 0.02, 0.16, 0.16])
            qr_ax2.imshow(_qr_image(app_url), cmap="gray")
            qr_ax2.axis("off")
            qr_ax2.set_title("互動查詢儀表板", fontsize=6.5, pad=2)
            label_ax2 = fig.add_axes([0.52, 0.005, 0.46, 0.03])
            label_ax2.axis("off")
            label_ax2.text(0.5, 0.5, app_url, ha="center", va="center", fontsize=5,
                           clip_on=True, transform=label_ax2.transAxes)

    def _summary_pages():
        head_lines = [
            f"分析區間：{r['start_date']} ～ {r['end_date']}（TLE 筆數：{r['n_tle']}）",
            f"軌道分類：{r['orbit_class']}（傾角族群：{r['inc_family']}）；"
            f"平均軌道高度：約 {r['alt_km_avg']:.0f} km",
            "",
            "── L1 規則式（P1–P6）──",
            f"旗標命中次數：{r['l1']['n_flagged']}",
            "",
            "── L2 統計變點通道 ──",
        ]
        for ch, v in r["l2"].items():
            head_lines.append(f"  {ch}：事件數 {v['n_events']}")
        head_lines += [
            "",
            "── L3 訓練式融合 ──",
            f"逐窗 ML 模型：{'可用' if r['l3']['ml_available'] else '無模型檔，略過'}"
            + (f"，旗標次數 {r['l3']['ml_n_flagged']}" if r['l3']['ml_n_flagged'] is not None else ""),
            f"融合評分器：{'可用' if r['l3']['fusion_available'] else '無模型檔，略過'}"
            + (f"，最大機率 {r['l3']['fusion_max_prob']:.3f}（門檻 {r['l3']['fusion_thr']:.3f}）"
               if r['l3']['fusion_max_prob'] is not None else ""),
            "",
            f"── 機動偵測落點（共 {len(r['landing_events'])} 筆）──",
        ]
        event_lines = []
        for ev in r["landing_events"]:
            ts = pd.Timestamp(ev["epoch"]).strftime("%Y-%m-%d %H:%M UTC")
            extra = f"　Δa={ev['sma_delta']:+.3f} km（{ev['sma_direction']}）" if "sma_delta" in ev else ""
            event_lines.append(f"  - {ts}{extra}")
        tail_lines = ["", f"報表產生時間：{r['generated_at']}"]

        title = (f"衛星機動偵測報表 — NORAD {r['norad']}"
                 f"{'（' + r['name'] + '）' if r.get('name') else ''}")
        avail1 = FIRST_PAGE_CAP - len(head_lines)
        if len(event_lines) + len(tail_lines) <= avail1:
            return [(head_lines + event_lines + tail_lines, title, True)]

        avail1_events = max(avail1 - 1, 0)
        page1 = (head_lines + event_lines[:avail1_events]
                 + ["", f"（機動偵測落點續下頁，共 {len(event_lines) - avail1_events} 筆）"])
        pages = [(page1, title, True)]
        remaining = event_lines[avail1_events:] + tail_lines
        while remaining:
            avail_cont = CONT_PAGE_CAP - 1
            chunk, remaining = remaining[:avail_cont], remaining[avail_cont:]
            pages.append((["── 機動偵測落點（續）──"] + chunk, None, False))
        return pages

    with PdfPages(buf) as pdf:
        for lines, title, draw_qr in _summary_pages():
            fig = plt.figure(figsize=(8.27, 11.69))  # A4
            _text_page(fig, lines, title=title, draw_qr=draw_qr)
            pdf.savefig(fig)
            plt.close(fig)

        if fmt == "F2":
            # 時序圖頁：SMA + 機動落點標註
            fig2 = plt.figure(figsize=(8.27, 11.69))
            ax1 = fig2.add_subplot(211)
            df = r["tle_df"]
            ax1.plot(df["epoch"], df["sma_km"], lw=0.8)
            for ev in r["landing_events"]:
                ax1.axvline(pd.Timestamp(ev["epoch"]), color="red", alpha=0.4, lw=0.8)
            ax1.set_title("半長軸（SMA）時序與機動落點標註")
            ax1.set_ylabel("SMA (km)")
            ax1.tick_params(axis="x", labelrotation=30)

            ax2 = fig2.add_subplot(212)
            l2raw = r["l2_raw"]
            for ch in ("cusum", "bocpd", "ssa", "mad3sig"):
                if ch in l2raw:
                    ax2.plot(df["epoch"], np.abs(l2raw[ch]["scores"]), lw=0.7, label=ch)
            ax2.set_title("L2 統計通道分數（絕對值）")
            ax2.legend(fontsize=7, ncol=4)
            ax2.tick_params(axis="x", labelrotation=30)
            fig2.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig2)
            plt.close(fig2)

            # ① 軌道根數連續變化與差值頁：a/i/e/RAAN 連續時序（左）＋ Δ 差值（右），
            # 對應 maneuver_app_2026SOctober.py 之 plot_elements_and_deltas()（不含其
            # 第三欄極座標時間視圖──PDF 為靜態列印用途，取核心資訊即可）。
            tr = r["tr_df"]
            fig_elem = plt.figure(figsize=(8.27, 11.69))
            fig_elem.suptitle("① 軌道根數連續變化與差值", fontsize=13)
            rows = [
                ("sma_km", "半長軸 a (km)", "da_km", "Δa (km)"),
                ("inclination_deg", "傾角 i (deg)", "di_deg", "Δi (deg)"),
                ("eccentricity", "離心率 e", "de", "Δe"),
                ("raan_deg", "RAAN (deg)", "draan_res_deg", "ΔRAAN 殘差 (deg)"),
            ]
            for i, (col_l, title_l, col_r, title_r) in enumerate(rows):
                axl = fig_elem.add_subplot(4, 2, 2 * i + 1)
                axl.plot(df["epoch"], df[col_l], lw=0.7, color="#0072B2")
                axl.set_title(title_l, fontsize=9)
                axl.tick_params(axis="x", labelrotation=30, labelsize=7)
                axl.tick_params(axis="y", labelsize=7)

                axr = fig_elem.add_subplot(4, 2, 2 * i + 2)
                if len(tr):
                    axr.plot(tr["epoch"], tr[col_r], lw=0.6, color="#888888")
                axr.set_title(title_r, fontsize=9)
                axr.tick_params(axis="x", labelrotation=30, labelsize=7)
                axr.tick_params(axis="y", labelsize=7)
            fig_elem.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig_elem)
            plt.close(fig_elem)

            # ② 系統偵測邏輯說明頁：L1/L2 各自看到的徵候、L3 如何篩出可信結果
            # ——決定論、可逐項對照原始數字重現的規則式敘述，與下一頁 AI（LLM）
            # 自由文字說明互補、不重複。內容固定幾個段落，不隨事件數量成長，
            # 因此沿用單頁＋手動預先斷行即可，不需要像機動落點清單那樣做續頁。
            fig_logic = plt.figure(figsize=(8.27, 11.69))
            ax_logic = fig_logic.add_axes([0.06, 0.06, 0.88, 0.86])
            ax_logic.axis("off")
            ax_logic.set_title("② 系統偵測邏輯說明", loc="left", fontsize=13)
            logic_text = _wrap_cjk_text(build_pipeline_logic_text(r))
            ax_logic.text(0, 0.97, logic_text, va="top", ha="left", fontsize=8.5,
                          transform=ax_logic.transAxes)
            pdf.savefig(fig_logic)
            plt.close(fig_logic)

            fig3 = plt.figure(figsize=(8.27, 11.69))
            ax3 = fig3.add_axes([0.06, 0.06, 0.88, 0.86])
            ax3.axis("off")
            ax3.set_title("AI 思維過程說明", loc="left", fontsize=13)
            ai = r["ai_explanation"]
            body = (f"（來源：{ai['source']}，信心度：{ai['confidence']}）\n\n"
                    f"{ai['answer']}")
            body = _wrap_cjk_text(body)
            ax3.text(0, 0.95, body, va="top", ha="left", fontsize=9,
                      transform=ax3.transAxes)
            pdf.savefig(fig3)
            plt.close(fig3)

        plt.close(fig)

    return buf.getvalue()
