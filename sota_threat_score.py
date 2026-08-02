#!/usr/bin/env python3
"""
sota_threat_score.py — SOTA-lite：威脅／脆弱度量化引擎
======================================================
對標 ComSpOC「SOTA」之輕量版：把既有的機動史、交會分析與行為指紋，疊成
「非合作目標 → 我方資產」之**可達性與威脅評分**。回答：
  「目標 X 是否能在 T 天內、以其殘餘 ΔV 預算抵達我方資產 Y 的軌道鄰域？」

三個計算模組：
  1. ΔV 預算帳本（budget ledger）：由目標之機動史累計已支出 ΔV → 推估支出率與殘餘能力。
  2. 可達性（reachability）        ：物理計算「目標 → 資產」之轉移成本
       - 高度轉移 ΔV（Hohmann 一階）＋ 變平面 ΔV（2V·sin(Δi/2)）
       - RAAN 對齊時間（差分 J2 漂移率 → 需等多久兩軌道面對齊）
  3. 威脅卡（threat card）          ：可達性 × 機動異常近況 × 意圖指標（RAAN 收斂）× 交會幾何
       → 排序輸出，供營運試行之威脅摘要。

真值來源：MEME transitions（目標當前軌態＋機動史）；資產以本土任務軌道定義（可替換）。
用法：python sota_threat_score.py [--horizon-days 30] [--budget-ms 50] [--top 15]
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

MU = 398_600.4418
J2 = 1.082_63e-3
RE = 6378.137

# 我方資產（本土任務軌道；a_km, inc_deg, raan_deg——可替換為實測）
# 含一個「與 Starlink 同傾角族群」之假想 LEO 資產，用以展示引擎之鑑別力（同族群→可達、
# 高威脅；跨傾角族群→變平面 ΔV 數 km/s、天然防護）。
ASSETS = [
    {"name": "FORMOSAT-5",   "a_km": RE + 720.0, "inc_deg": 98.28, "raan_deg": 120.0},
    {"name": "FORMOSAT-7c",  "a_km": RE + 550.0, "inc_deg": 24.0,  "raan_deg": 60.0},
    {"name": "TRITON",       "a_km": RE + 595.0, "inc_deg": 97.4,  "raan_deg": 200.0},
    {"name": "ALLY-LEO-53",  "a_km": RE + 545.0, "inc_deg": 53.15, "raan_deg": 95.0},
]


def circ_v(a):                 # 圓軌速度 m/s
    return np.sqrt(MU / a) * 1000.0


def j2_raan_rate(a, i_deg, e=0.001):     # deg/day
    n = np.sqrt(MU / a ** 3) * 86400.0 / (2 * np.pi)
    p = a * (1 - e ** 2)
    return -1.5 * J2 * (RE / p) ** 2 * n * np.cos(np.deg2rad(i_deg)) * 360.0


def hohmann_dv(a1, a2):        # 高度轉移總 ΔV（m/s）
    v1, v2 = circ_v(a1), circ_v(a2)
    at = 0.5 * (a1 + a2)
    vt1 = np.sqrt(MU * (2 / a1 - 1 / at)) * 1000.0
    vt2 = np.sqrt(MU * (2 / a2 - 1 / at)) * 1000.0
    return abs(vt1 - v1) + abs(v2 - vt2)


def plane_dv(a, di_deg):       # 變平面 ΔV（m/s），於較高處執行更省，取平均高度速度近似
    return 2.0 * circ_v(a) * np.sin(np.deg2rad(abs(di_deg)) / 2.0)


def reach_cost(tgt, ast):
    """目標→資產之轉移 ΔV 與 RAAN 對齊時間。"""
    dv_h = hohmann_dv(tgt["a_km"], ast["a_km"])
    di = ast["inc_deg"] - tgt["inc_deg"]
    dv_p = plane_dv(0.5 * (tgt["a_km"] + ast["a_km"]), di)
    # RAAN 對齊：靠差分 J2 漂移等待（免 ΔV，但花時間）
    dr = j2_raan_rate(ast["a_km"], ast["inc_deg"]) - j2_raan_rate(tgt["a_km"], tgt["inc_deg"])
    draan = ((ast["raan_deg"] - tgt["raan_deg"] + 180) % 360) - 180
    t_align = abs(draan / dr) if abs(dr) > 1e-6 else np.inf     # days
    return dv_h + dv_p, dv_h, dv_p, t_align


def dv_from_da(da, a):
    return abs(da) / 2.0 * np.sqrt(MU / a ** 3) * 1000.0


def build_ledger(trans: pd.DataFrame) -> pd.DataFrame:
    """由 MEME transitions 累計每目標之 ΔV 支出與當前軌態。"""
    trans = trans.copy()
    trans["t_to"] = pd.to_datetime(trans["t_to"], utc=True, format="ISO8601")
    trans["dv_ms"] = trans.apply(lambda r: dv_from_da(r["da_km"], r["a_km"])
                                 if abs(r["da_km"]) > 1.0 else 0.0, axis=1)
    rows = []
    for sat, g in trans.groupby("sat_name"):
        g = g.sort_values("t_to")
        span_d = max(1.0, (g["t_to"].iloc[-1] - g["t_to"].iloc[0]).total_seconds() / 86400)
        spent = float(g["dv_ms"].sum())
        n_man = int((g["dv_ms"] > 0).sum())
        last = g.iloc[-1]
        recent = g[g["t_to"] >= g["t_to"].iloc[-1] - pd.Timedelta(days=30)]
        rows.append({
            "sat_name": sat, "a_km": float(last["a_km"]), "inc_deg": float(last["i_deg"]),
            "raan_deg": float(last["raan_deg"]), "alt_km": float(last["alt_km"]),
            "dv_spent_ms": round(spent, 3), "n_maneuver": n_man,
            "spend_rate_ms_day": round(spent / span_d, 4),
            "recent_dv_ms": round(float(recent["dv_ms"].sum()), 3),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-days", type=float, default=30.0)
    ap.add_argument("--budget-ms", type=float, default=150.0,
                    help="假設殘餘 ΔV 預算上限（m/s；專職 RPO/檢視器級約 150–300）")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    trans = pd.read_csv(tp)
    ledger = build_ledger(trans)
    print(f"SOTA-lite 威脅評分 ← {Path(tp).name}｜{len(ledger)} 目標、{len(ASSETS)} 資產"
          f"｜horizon {args.horizon_days:.0f}d、budget {args.budget_ms:.0f} m/s\n")

    # 候選＝所有有機動能力之目標（recent_dv>0），令威脅排序自行surface可達之同族群配對
    cand = ledger[ledger["recent_dv_ms"] > 0].copy()
    if len(cand) == 0:
        cand = ledger.copy()

    budget = args.budget_ms
    threats = []
    for _, t in cand.iterrows():
        tgt = {"a_km": t["a_km"], "inc_deg": t["inc_deg"], "raan_deg": t["raan_deg"]}
        for ast in ASSETS:
            dv_tot, dv_h, dv_p, t_align = reach_cost(tgt, ast)
            # 可達性（軟性 0–1）：ΔV 成本以預算為尺度指數衰減 × 時間餘裕，
            # 使「同族群低成本」明顯高於「跨傾角數 km/s」，產生鑑別梯度。
            t_margin = np.clip(1 - t_align / args.horizon_days, 0, 1) if np.isfinite(t_align) else 0.0
            reach = float(np.exp(-dv_tot / budget) * t_margin)
            hard_reach = bool(dv_tot <= budget and t_align <= args.horizon_days)
            # 意圖：RAAN 是否朝資產收斂（差分漂移縮小夾角）＋近況機動活躍度
            drift = j2_raan_rate(ast["a_km"], ast["inc_deg"]) - j2_raan_rate(tgt["a_km"], tgt["inc_deg"])
            draan = ((ast["raan_deg"] - tgt["raan_deg"] + 180) % 360) - 180
            converging = 1.0 if (drift * draan < 0) else 0.0
            activity = np.clip(t["recent_dv_ms"] / 20.0, 0, 1)
            # 威脅分數（0–1）：可達性主導，意圖與活躍度加權
            threat = float(np.clip(0.7 * reach + 0.15 * converging + 0.15 * activity, 0, 1))
            threats.append({
                "target": t["sat_name"], "asset": ast["name"],
                "dv_transfer_ms": round(dv_tot, 1), "dv_alt": round(dv_h, 1),
                "dv_plane": round(dv_p, 1), "t_align_d": round(t_align, 1) if np.isfinite(t_align) else 9999,
                "budget_ms": round(budget, 1), "reachable": hard_reach,
                "reach": round(reach, 3), "converging": int(converging),
                "recent_dv": t["recent_dv_ms"], "threat": round(threat, 3),
            })
    T = pd.DataFrame(threats).sort_values("threat", ascending=False)

    print("=" * 96)
    print(f"{'目標':<16}{'資產':<12}{'ΔV轉移':>8}{'(高度':>7}{'/平面)':>7}{'對齊天':>7}"
          f"{'預算':>7}{'可達':>6}{'收斂':>5}{'威脅':>7}")
    print("-" * 96)
    for _, r in T.head(args.top).iterrows():
        print(f"{r.target[:15]:<16}{r.asset:<12}{r.dv_transfer_ms:>8.0f}{r.dv_alt:>7.0f}"
              f"{r.dv_plane:>7.0f}{r.t_align_d:>7.0f}{r.budget_ms:>7.0f}"
              f"{('是' if r.reachable else '否'):>5}{('↗' if r.converging else '·'):>5}{r.threat:>7.3f}")
    print("=" * 96)
    nreach = int(T["reachable"].sum())
    print(f"可達配對：{nreach}/{len(T)}（ΔV 轉移 ≤ 預算 且 RAAN 對齊 ≤ {args.horizon_days:.0f}d）")
    print("判讀：多數 LEO↔LEO 轉移之變平面 ΔV 極高（跨傾角族群數 km/s）＝天然防護；"
          "威脅集中於『同傾角族群、僅需高度轉移＋RAAN 等待』之目標。")

    out = Path("data/benchmark/sota_threat_20260723.csv")
    T.to_csv(out, index=False, encoding="utf-8-sig")
    led = Path("data/benchmark/sota_dv_ledger_20260723.csv")
    ledger.sort_values("dv_spent_ms", ascending=False).to_csv(led, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}\n       {led}")
    print("三模組閉環：ΔV 帳本（機動史）→ 可達性（物理轉移成本）→ 威脅卡（可達×意圖×活躍）。")


if __name__ == "__main__":
    main()
