#!/usr/bin/env python3
"""
orbit_anomaly_detector.py — 統一軌道異常偵測介面（契約 M5 系統整合）
===================================================================
把散落的各層偵測器整合為單一 API，依衛星軌域/星系自動路由，回傳一致結構的結果：

  Layer 1  規則 P1–P6            （maneuver_strategies_july）
  Layer 2  統計 CUSUM/BOCPD/SSA  （statistical_detectors）+ 融合評分器（models_fusion）
  Model 1  監督式 LightGBM       （Starlink LEO 專用，需物理閘門）
  Model 2  無監督 IsolationForest（regime-agnostic，物理殘差）
  物理     NRLMSIS 阻力殘差 + 再入守門（atmospheric_drag）

路由邏輯：
  - 自然再入（is_reentry_decay）→ 直接判「自然衰減，非機動」，紅色警示。
  - Starlink LEO → 主判 Model 1（物理閘門）+ 融合評分器；統計層/Model 2 併陳。
  - 非 Starlink（含 MEO/GEO/HEO/衰減軌）→ 主判 Model 2 + NRLMSIS 殘差（避免 Model 1 OOD 誤報）。

用法：
  from orbit_anomaly_detector import OrbitAnomalyDetector
  det = OrbitAnomalyDetector(); print(det.detect(29052))     # FORMOSAT-3A
  python orbit_anomaly_detector.py 29052 25544 62425
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms
import statistical_detectors as sd
from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay

RE = 6378.137


class OrbitAnomalyDetector:
    def __init__(self, db: str = "space_db.duckdb", registry: str = "data/url_registry.csv"):
        self.db = db
        self.sw = load_space_weather()
        self._fusion = self._load("models_fusion/fusion_scorer.pkl")
        self._model2 = self._load("Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl")
        try:
            from compare_tle_vs_ephemeris import load_registry
            reg = load_registry(registry)
            self._names = reg["sat_name"]
        except Exception:
            self._names = {}

    @staticmethod
    def _load(p):
        try:
            import joblib
            return joblib.load(p) if Path(p).exists() else None
        except Exception:
            return None

    def _tle(self, nid):
        con = duckdb.connect(self.db, read_only=True)
        df = con.execute(
            "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg, "
            "argp_deg, mean_anomaly_deg, bstar, object_name FROM raw_tle_archive "
            "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
        con.close()
        if not df.empty:
            df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="ISO8601")
        return df

    def _fusion_flags(self, df):
        """對單顆算每 epoch ±24h 窗融合機率（與 app 一致）。回傳旗標數。"""
        if self._fusion is None or len(df) < 8:
            return None
        r = sd.run_all(df["sma_km"].to_numpy(float))
        drag = np.zeros(len(df))
        try:
            cols = ["epoch", "sma_km"] + (["eccentricity"] if "eccentricity" in df else [])
            dr = drag_residual(df[cols], self.sw)
            if not dr.empty:
                dmap = dict(zip(pd.to_datetime(dr["epoch"], utc=True), dr["drag_resid_da"].abs()))
                drag = np.array([dmap.get(e, 0.0) for e in df["epoch"]], float)
        except Exception:
            pass
        ch = np.nan_to_num(np.column_stack([
            np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
            np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]), drag / 0.10]))
        t = df["epoch"].reset_index(drop=True)
        feats = []
        for i in range(len(df)):
            m = ((t - t.iloc[i]).abs() <= pd.Timedelta(hours=24)).to_numpy()
            sub = ch[m]; row = []
            for j in range(5):
                col = sub[:, j]; row += [col.max(), col.mean(), float(np.percentile(col, 90))]
            feats.append(row)
        proba = self._fusion["clf"].predict_proba(np.array(feats))[:, 1]
        return int((proba >= self._fusion["thr"]).sum()), float(proba.max())

    def _model2_flags(self, df):
        if self._model2 is None or len(df) < 6:
            return None
        try:
            from ml_model2_anomaly import physical_residuals, _CH
            r = physical_residuals(df.rename(columns={}), self.sw)
            if r.empty:
                return None
            X = np.clip(np.nan_to_num(r[_CH].to_numpy()), -200, 200)
            return int((self._model2["model"].predict(X) == -1).sum())
        except Exception:
            return None

    def detect(self, nid: int) -> dict:
        df = self._tle(nid)
        if df.empty or len(df) < 5:
            return {"norad_id": int(nid), "status": "insufficient_data"}
        name = str(self._names.get(int(nid), df["object_name"].iloc[-1])).strip().lstrip("0 ").strip()
        a = float(df["sma_km"].iloc[-1]); e = float(df["eccentricity"].iloc[-1])
        i = float(df["inclination_deg"].iloc[-1])
        orbit = ms.classify_orbit(a, e, i)
        is_star = name.upper().startswith("STARLINK")
        reentry = bool(is_reentry_decay(df))

        # Layer 2 統計層
        r = sd.run_all(df["sma_km"].to_numpy(float))
        stat_events = {k: len(r[k]["events"]) for k in ("cusum", "bocpd", "ssa", "mad3sig")}
        fus = self._fusion_flags(df)
        m2 = self._model2_flags(df)

        # 路由主判
        if reentry:
            primary, verdict = "NRLMSIS/reentry-guard", "自然再入衰減（非機動）"
        elif is_star and orbit in ("LEO", "MEO"):
            primary = "Model 1 (LightGBM) + 融合評分器"
            verdict = f"融合旗標 {fus[0] if fus else 'NA'} 次"
        else:
            primary = "Model 2 (IsolationForest) + NRLMSIS 殘差"
            verdict = f"Model 2 異常 {m2 if m2 is not None else 'NA'} 次"

        return {
            "norad_id": int(nid), "name": name, "status": "ok",
            "orbit_class": orbit, "domain": "Starlink" if is_star else "non-Starlink",
            "n_tle": len(df), "alt_km": round(a - RE, 1), "ecc": round(e, 4),
            "reentry": reentry, "routed_primary": primary, "verdict": verdict,
            "layer2_statistical_events": stat_events,
            "fusion_flags": None if fus is None else fus[0],
            "fusion_max_prob": None if fus is None else round(fus[1], 3),
            "model2_anomalies": m2,
        }


def main():
    ids = [int(x) for x in sys.argv[1:]] or [29052, 25544, 62425, 38752]
    det = OrbitAnomalyDetector()
    for nid in ids:
        r = det.detect(nid)
        print("=" * 70)
        if r["status"] != "ok":
            print(f"NORAD {nid}: {r['status']}"); continue
        print(f"NORAD {r['norad_id']}  {r['name']}  [{r['orbit_class']} · {r['domain']} · "
              f"alt {r['alt_km']}km]")
        print(f"  再入={r['reentry']}  → 主判：{r['routed_primary']}")
        print(f"  判定：{r['verdict']}")
        print(f"  Layer2 統計事件：{r['layer2_statistical_events']}")
        print(f"  融合旗標={r['fusion_flags']} (max_prob={r['fusion_max_prob']})  "
              f"Model2 異常={r['model2_anomalies']}")


if __name__ == "__main__":
    main()
