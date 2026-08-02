#!/usr/bin/env python3
"""
run_statistical_layer.py
========================
Layer 2 契約具名統計方法（CUSUM / BOCPD / SSA）之執行與 MEME 真值驗證。

對每顆衛星建立兩種軌道半長軸時間序列：
  TLE sma     — 由 raw_tle_archive.sma_km（推論時可得、可部署）
  MEME mean-a — 由 study3.build_file_table 的檔案平均半長軸（乾淨、消 J2 振盪）

在兩序列上各跑三種偵測器，將偵測事件與 MEME 真值機動（transitions_full 中
da_severity ∈ {medium,large}）以 ±容差匹配，計算 precision / recall / lead-time，
並與簡易 TLE 差分門檻基準同表對比。

輸出
----
  data/statistical_layer/events_{date}.csv          逐事件（method×input×sat）
  data/statistical_layer/metrics_{date}.csv         每 (method,input) 的 P/R/lead
  data/statistical_layer/per_epoch_stats_{date}.csv 逐 (sat,tle_epoch) 三統計量（供 ML 特徵）

用法
----
  python run_statistical_layer.py --max-sats 30
  python run_statistical_layer.py                 # 全 283 顆
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import statistical_detectors as sd
from compare_tle_vs_ephemeris import find_all_ephemeris_files, load_registry
from study3_tle_frozen_and_gap import build_file_table

log = logging.getLogger("stat_layer")

_TOL_H = 24.0          # 事件↔真值episode匹配容差（小時）
_MIN_LEN = 8           # 序列最短長度（點）
_EPISODE_GAP_H = 48.0  # 相鄰 medium+ 機動間隔 > 此值 → 視為不同機動episode
_SEV_TRUTH = {"medium", "large"}   # 真值機動門檻（≥5km，與 forecast 主模型一致）


def _to_ns(s) -> np.ndarray:
    """統一轉為 int64 UTC 奈秒；跨 DB(µs)/CSV(ns) 來源單位一致（避免 1000× 錯位）。"""
    dt = pd.to_datetime(s, utc=True)
    arr = dt.to_numpy() if hasattr(dt, "to_numpy") else np.asarray(dt)
    return arr.astype("datetime64[ns]").astype("int64")


def _collapse_episodes(times_ns: np.ndarray, gap_ns: int) -> list[tuple[int, int]]:
    """把密集的 per-8h 機動時刻合併為機動episode『區間』[起, 迄]。
    相鄰時刻間隔 > gap_ns 視為不同episode。回傳 (start_ns, end_ns) 清單。"""
    if len(times_ns) == 0:
        return []
    t = np.sort(times_ns)
    episodes: list[tuple[int, int]] = []
    start = prev = t[0]
    for i in range(1, len(t)):
        if t[i] - prev > gap_ns:
            episodes.append((int(start), int(prev)))
            start = t[i]
        prev = t[i]
    episodes.append((int(start), int(prev)))
    return episodes


def _tle_sma_series(con, norad_id: int) -> pd.DataFrame:
    df = con.execute(
        "SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
        "AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(norad_id)]
    ).fetchdf()
    if df.empty:
        return df
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    df = df.drop_duplicates("epoch_utc").reset_index(drop=True)
    return df


def _match(detect_ns: np.ndarray, episodes: list[tuple[int, int]], tol_ns: int) -> dict:
    """區間式匹配：機動episode [起,迄] 擴張 ±tol。
      recall    — episode 內（含容差）至少有一次偵測即算命中
      precision — 偵測落在任一 episode 區間（含容差）內即算命中
      lead_time — episode『起始』− 該episode首次偵測（正=在機動開始前預警）
    """
    nd, nt = len(detect_ns), len(episodes)
    if nd == 0 and nt == 0:
        return {}
    det = np.sort(detect_ns.astype(np.int64))
    matched_truth = 0
    leads = []
    for (s, e) in episodes:
        lo, hi = s - tol_ns, e + tol_ns
        inside = det[(det >= lo) & (det <= hi)]
        if len(inside):
            matched_truth += 1
            leads.append((s - int(inside[0])) / 3.6e12)   # ns→h，正=機動起始前偵測
    matched_det = 0
    for dt in det:
        if any((s - tol_ns) <= dt <= (e + tol_ns) for (s, e) in episodes):
            matched_det += 1
    return {
        "n_detect": nd, "n_truth": nt,
        "precision": (matched_det / nd) if nd else float("nan"),
        "recall": (matched_truth / nt) if nt else float("nan"),
        "lead_time_h_median": float(np.median(leads)) if leads else float("nan"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Layer 2 CUSUM/BOCPD/SSA + MEME 真值驗證")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--truth", default=None, help="transitions_full CSV（預設取最新）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-sats", type=int, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    data_root = args.data_root
    reg_csv = Path(args.registry) if args.registry else data_root / "url_registry.csv"
    out_dir = Path(args.out_dir) if args.out_dir else data_root / "statistical_layer"
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = load_registry(reg_csv)
    name_to_norad = {v: k for k, v in reg["sat_name"].items()}

    # ── 真值：medium+ 機動時刻（per sat）─────────────────────────────────────
    truth_glob = sorted((data_root / "meme_truth").glob("transitions_full_*.csv"))
    truth_path = Path(args.truth) if args.truth else (truth_glob[-1] if truth_glob else None)
    if truth_path is None:
        log.error("找不到 transitions_full 真值檔"); return
    truth = pd.read_csv(truth_path)
    truth = truth[truth["da_severity"].isin(_SEV_TRUTH)].copy()
    gap_ns = int(_EPISODE_GAP_H * 3.6e12)
    truth_ns_by_sat: dict[str, np.ndarray] = {}
    for s, g in truth.groupby("sat_name"):
        per8h = _to_ns(g["t_to"])
        truth_ns_by_sat[s] = _collapse_episodes(per8h, gap_ns)   # 合併為機動episode
    n_ep = sum(len(v) for v in truth_ns_by_sat.values())
    log.info("真值載入 ← %s（%d 顆，合併後 %d 個機動episode，gap>%.0fh）",
             truth_path.name, len(truth_ns_by_sat), n_ep, _EPISODE_GAP_H)

    raw_dir = data_root / "raw"
    sat_dirs = sorted([p for p in raw_dir.iterdir() if p.is_dir()
                       and not p.name.upper().startswith("STARLINK-DEMO")])
    if args.max_sats:
        sat_dirs = sat_dirs[: args.max_sats]

    con = duckdb.connect(args.db, read_only=True)
    tol_ns = int(_TOL_H * 3.6e12)

    event_rows: list[dict] = []
    epoch_rows: list[dict] = []
    # 契約具名三法 + 現行 3σ MAD 替代方案（同表對照）
    METHODS = ("cusum", "bocpd", "ssa", "mad3sig")

    for d in sat_dirs:
        sat = d.name
        norad = name_to_norad.get(sat)
        if norad is None:
            continue
        truth_ns = truth_ns_by_sat.get(sat, [])

        series = {}
        # TLE sma
        tle = _tle_sma_series(con, int(norad))
        if len(tle) >= _MIN_LEN:
            series["TLE"] = (_to_ns(tle["epoch_utc"]),
                             tle["sma_km"].to_numpy(float), tle["epoch_utc"])
        # MEME mean-a
        try:
            ftb = build_file_table(find_all_ephemeris_files(d), sat)
        except Exception:
            ftb = pd.DataFrame()
        if len(ftb) >= _MIN_LEN:
            series["MEME"] = (_to_ns(ftb["epoch"]),
                              ftb["mean_a"].to_numpy(float) / 1000.0, ftb["epoch"])  # m→km

        for inp, (t_ns, y, epoch_ser) in series.items():
            res = sd.run_all(y)
            for m in METHODS:
                ev_idx = res[m]["events"]
                det_ns = t_ns[ev_idx] if len(ev_idx) else np.array([], dtype=np.int64)
                mm = _match(det_ns.astype(np.int64), truth_ns, tol_ns)
                if mm:
                    event_rows.append({"sat_name": sat, "method": m, "input": inp, **mm})
            # 逐 epoch 三統計量（僅 TLE 序列，供 ML 特徵；推論可得）
            if inp == "TLE":
                for i, ep in enumerate(epoch_ser):
                    epoch_rows.append({
                        "norad_id": int(norad), "sat_name": sat,
                        "epoch_utc": pd.Timestamp(ep).isoformat(),
                        "cusum_stat":   round(float(res["cusum"]["scores"][i]), 5),
                        "bocpd_cp_prob": round(float(res["bocpd"]["scores"][i]), 5),
                        "ssa_resid_z":  round(float(res["ssa"]["scores"][i]), 5),
                    })
        log.info("  [%s] TLE=%d MEME=%d truth=%d",
                 sat, len(series.get("TLE", (np.array([]),))[0]) if "TLE" in series else 0,
                 len(series.get("MEME", (np.array([]),))[0]) if "MEME" in series else 0,
                 len(truth_ns))
    con.close()

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")

    # ── 逐事件明細 + 彙總指標 ────────────────────────────────────────────────
    ev_df = pd.DataFrame(event_rows)
    ev_df.to_csv(out_dir / f"events_{date_tag}.csv", index=False, encoding="utf-8-sig")

    # 彙總：micro 平均（跨衛星加總 TP/偵測/真值）
    rows = []
    for (m, inp), g in ev_df.groupby(["method", "input"]):
        nd = g["n_detect"].sum(); nt = g["n_truth"].sum()
        tp_r = (g["recall"] * g["n_truth"]).sum()       # 匹配到的真值數
        tp_p = (g["precision"] * g["n_detect"]).sum()   # 匹配到的偵測數
        rows.append({
            "method": m, "input": inp,
            "n_sat": g["sat_name"].nunique(),
            "n_detect": int(nd), "n_truth": int(nt),
            "precision": round(tp_p / nd, 3) if nd else float("nan"),
            "recall": round(tp_r / nt, 3) if nt else float("nan"),
            "lead_time_h_median": round(float(np.nanmedian(g["lead_time_h_median"]))
                                        if g["lead_time_h_median"].notna().any() else float("nan"), 2),
        })
    met_df = pd.DataFrame(rows).sort_values(["input", "method"]).reset_index(drop=True)
    met_df.to_csv(out_dir / f"metrics_{date_tag}.csv", index=False, encoding="utf-8-sig")

    if epoch_rows:
        pd.DataFrame(epoch_rows).to_csv(
            out_dir / f"per_epoch_stats_{date_tag}.csv", index=False, encoding="utf-8-sig")

    # ── 摘要 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"Layer 2 契約具名統計方法 — MEME 真值驗證（容差 ±{_TOL_H:.0f}h，真值=medium+）")
    print("=" * 78)
    print(f"  {'method':<8} {'input':<6} {'n_sat':>6} {'n_detect':>9} {'n_truth':>8} "
          f"{'Prec':>7} {'Recall':>7} {'lead_h':>8}")
    for _, r in met_df.iterrows():
        print(f"  {r['method']:<8} {r['input']:<6} {r['n_sat']:>6} {r['n_detect']:>9} "
              f"{r['n_truth']:>8} {r['precision']:>7.3f} {r['recall']:>7.3f} "
              f"{r['lead_time_h_median']:>8.2f}")
    print("=" * 78)
    log.info("輸出 → %s", out_dir)

    from satdet import record
    record("statistical_layer",
           params={"tol_h": _TOL_H},
           outputs={"events": out_dir / f"events_{date_tag}.csv",
                    "metrics": out_dir / f"metrics_{date_tag}.csv",
                    "per_epoch_stats": out_dir / f"per_epoch_stats_{date_tag}.csv"})


if __name__ == "__main__":
    main()
