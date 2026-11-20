# -*- coding: utf-8 -*-
"""compare_tasa15_A_vs_R7.py — TASA 指定 15 顆衛星：A 流程（App 附錄 D 統一偵測摘要）與 R7 單星報表對照

A 流程使用 App 附錄 D 之同一程式：
  ① 統一偵測摘要卡：orbit_anomaly_detector.OrbitAnomalyDetector.detect()（該星資料庫內全部 TLE）
  ② 主判結果卡（依路由）：與 maneuver_app_2026November.py 之 compute_nrlmsis_maneuvers、
     compute_model2_detection、compute_ml_detection 相同邏輯（此處去除 Streamlit 快取），
     期間設為 R7 交付期間（r15.json 之 start_date～end_date），使兩者可比。
     Starlink → Model 1（ML 窗口模型）主判；非 Starlink → NRLMSIS 阻力殘差（|殘差| > 0.3 km）主判、Model 2 佐證。
R7：data/benchmark/tasa15_r7_delivery/r15.json（2026-11-15 交付結果）。

比對：A 主判旗標以 48 小時合併為「旗標段」；R7 候選事件 ±24 小時內有 A 主判旗標即算 A 涵蓋。
輸出：data/benchmark/tasa15_A_vs_R7/{summary.csv, summary.json}
用法：python docs/compare_tasa15_A_vs_R7.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import maneuver_report_builder as rb  # noqa: E402
import orbit_anomaly_detector as oad  # noqa: E402

OUT = ROOT / "data" / "benchmark" / "tasa15_A_vs_R7"
OUT.mkdir(parents=True, exist_ok=True)
R15 = json.load(open(ROOT / "data/benchmark/tasa15_r7_delivery/r15.json", encoding="utf-8"))
GAP_H, TOL_H, THR = 48, 24, 0.30


def nrlmsis_flags(norad, d0, d1):
    from atmospheric_drag import drag_residual, load_space_weather, is_reentry_decay
    dd = rb.load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 5:
        return None, False
    cols = ["epoch", "sma_km"] + [c for c in ("eccentricity", "line1", "line2") if c in dd.columns]
    r = drag_residual(dd[cols], load_space_weather())
    if r.empty:
        return None, False
    reentry = bool(is_reentry_decay(dd))
    r = r[["epoch", "drag_resid_da"]].copy()
    r["flag"] = False if reentry else (r["drag_resid_da"].abs() > THR)
    return r, reentry


def model2_flags(norad, d0, d1):
    import joblib
    import ml_model2_anomaly as m2
    from atmospheric_drag import load_space_weather
    mpath = ROOT / "Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl"
    if not mpath.exists():
        return None
    bundle = joblib.load(mpath)
    iso, ch = bundle["model"], bundle["channels"]
    dd = rb.load_tle(norad)
    dd = dd[(dd["epoch"].dt.date >= d0) & (dd["epoch"].dt.date <= d1)].reset_index(drop=True)
    if len(dd) < 8:
        return None
    cols = ["epoch", "sma_km", "inclination_deg", "eccentricity", "raan_deg"] + \
           [c for c in ("line1", "line2") if c in dd.columns]
    r = m2.physical_residuals(dd[cols], load_space_weather())
    if r.empty:
        return None
    X = np.clip(np.nan_to_num(r[ch].to_numpy()), -200, 200)
    return r.assign(flag=(iso.predict(X) == -1))


def episodes(times):
    ts = sorted(pd.to_datetime(pd.Series(times), utc=True))
    out, cur = [], []
    for t in ts:
        if cur and (t - cur[-1]).total_seconds() / 3600 > GAP_H:
            out.append((cur[0], cur[-1])); cur = []
        cur.append(t)
    if cur:
        out.append((cur[0], cur[-1]))
    return out


def covered(ev, flag_times):
    t0 = pd.Timestamp(ev["t_start"]) - pd.Timedelta(hours=TOL_H)
    t1 = pd.Timestamp(ev["t_end"]) + pd.Timedelta(hours=TOL_H)
    return any(t0 <= t <= t1 for t in flag_times)


def main():
    det = oad.OrbitAnomalyDetector(str(ROOT / "space_db.duckdb"))
    rows = []
    for k, v in R15.items():
        nid = int(k)
        d0, d1 = date.fromisoformat(v["start_date"]), date.fromisoformat(v["end_date"])
        name = v["name"]
        is_star = str(name).upper().startswith("STARLINK")
        u = det.detect(nid)
        nm, reentry = nrlmsis_flags(nid, d0, d1)
        m2 = model2_flags(nid, d0, d1)
        if is_star:
            ml = rb.compute_ml_detection(nid, d0, d1)
            prim = ml[0] if ml else None
            prim_times = list(prim.loc[prim["flag"], "epoch"]) if prim is not None else []
            prim_name = "Model 1（ML）"
        else:
            prim_times = list(nm.loc[nm["flag"], "epoch"]) if nm is not None else []
            prim_name = "NRLMSIS 阻力殘差"
        prim_times = [pd.Timestamp(t).tz_convert("UTC") if pd.Timestamp(t).tzinfo else pd.Timestamp(t).tz_localize("UTC")
                      for t in prim_times]
        eps = episodes(prim_times)
        evs = v["events"]
        r7_cov = [covered(e, prim_times) for e in evs]
        e3 = [e for e in evs if e["grade"] == "E3"]
        e3_cov = sum(covered(e, prim_times) for e in e3)

        # A 旗標段中，落在任何 R7 候選事件 ±24h 以外者
        def in_any(ep):
            for e in evs:
                t0 = pd.Timestamp(e["t_start"]) - pd.Timedelta(hours=TOL_H)
                t1 = pd.Timestamp(e["t_end"]) + pd.Timedelta(hours=TOL_H)
                if ep[0] <= t1 and ep[1] >= t0:
                    return True
            return False
        eps_out = sum(not in_any(ep) for ep in eps)
        g = v["counts"]["grades"]
        rows.append({
            "norad": nid, "name": name, "domain": "Starlink" if is_star else "非 Starlink",
            "alt_km": round(v["alt_km_avg"]), "period": f"{v['start_date']}～{v['end_date']}",
            "A_primary": prim_name,
            "A_card_verdict": u.get("verdict"), "A_card_ntle": u.get("n_tle"),
            "A_card_model2": u.get("model2_anomalies"), "A_card_fusion": u.get("fusion_flags"),
            "A_card_l2": u.get("layer2_statistical_events"),
            "A_primary_flags": len(prim_times), "A_primary_episodes": len(eps),
            "A_episodes_outside_R7": eps_out,
            "A_nrlmsis_flags": int(nm["flag"].sum()) if nm is not None else None,
            "A_model2_flags": int(m2["flag"].sum()) if m2 is not None else None,
            "A_reentry": reentry,
            "R7_events": len(evs), "R7_E3": g["E3"], "R7_E2": g["E2"], "R7_E1": g["E1"], "R7_D": g["D"],
            "R7_events_covered_by_A": sum(r7_cov),
            "R7_E3_covered_by_A": e3_cov,
            "R7_E3_list": "; ".join(f"{str(e['t_start'])[:10]} {e['net_da']:+.1f} km{'✓' if covered(e, prim_times) else '✗'}" for e in e3),
            "R7_lowconf": len(v.get("low_conf") or []),
        })
        r = rows[-1]
        print(f"{nid} {name:16s} A[{prim_name}] 旗標 {r['A_primary_flags']:4d} 段 {r['A_primary_episodes']:3d}"
              f"（R7 外 {eps_out:3d}）｜Model2 {r['A_model2_flags']}｜卡片：{r['A_card_verdict']}"
              f"｜R7 事件 {len(evs)}（E3 {g['E3']}），A 涵蓋 {sum(r7_cov)}，E3 涵蓋 {e3_cov}/{len(e3)} {r['R7_E3_list']}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    json.dump(rows, open(OUT / "summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("TOTAL", df[["A_primary_flags", "A_primary_episodes", "A_episodes_outside_R7", "A_model2_flags",
                        "R7_events", "R7_E3", "R7_events_covered_by_A", "R7_E3_covered_by_A"]].sum().to_dict())


if __name__ == "__main__":
    main()
