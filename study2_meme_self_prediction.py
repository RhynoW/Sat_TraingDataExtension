#!/usr/bin/env python3
"""
study2_meme_self_prediction.py
==============================
研究 2（黃金版本）：MEME vs MEME 自我預測誤差，外推時程 0–72h。

方法論
------
每個 MEME 檔涵蓋 72h、1 分鐘間隔，且每 ~8h 重新發布、彼此重疊 ~88%。
對同一個目標時刻 t：
  - **真值** = 以 t 為「第一筆」的那個檔（外推齡 0，最新、最接近定軌真值）。
  - **預測** = 較早發布、其涵蓋範圍仍含 t 的檔，對 t 的預測（外推齡 = t − 該檔epoch）。
兩者相減即「MEME 自身在該外推時程的預測誤差」，**完全不需外部傳播器、無 SGP4 誤差混入**，
是最乾淨、樣本量最大的外推誤差量測。外推時程天然落在 ~8h, 16h, …, 72h。

限制與混淆
----------
若 [epoch, t] 期間衛星實際機動，預測誤差會被未建模 ΔV 主導。本腳本沿用
compare_tle_vs_ephemeris.detect_meme_maneuvers 標記「機動污染」的樣本，
同時輸出「全部」與「濾除機動後」兩套統計。

輸出
----
  data/study2/study2_meme_residuals_{date}.csv    逐 (目標時刻 × 外推齡) 殘差
  data/study2/study2_horizon_summary_{date}.csv   外推時程分箱統計
  data/study2/plots/study2_err_vs_horizon_{date}.png

用法
----
  python study2_meme_self_prediction.py --max-sats 5
  python study2_meme_self_prediction.py --no-plot
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from compare_tle_vs_ephemeris import (
    _meme_first_state,
    _rtn_basis,
    detect_meme_maneuvers,
    find_all_ephemeris_files,
)
from starlink_ephemeris.parser import parse_ephemeris_file

log = logging.getLogger("study2")

_STATE_COLS = ["r_x", "r_y", "r_z", "v_x", "v_y", "v_z"]


def build_truth_snapshots(files: list[Path]) -> tuple[pd.DataFrame, dict]:
    """
    Pass 1（快）：只讀每個檔第一筆 → 真值快照序列 + 檔案→epoch 對照。

    回傳 (truth_df[t,r_x..v_z], {file_path: epoch_timestamp})。
    """
    rows: list[dict] = []
    file_epoch: dict[Path, pd.Timestamp] = {}
    for f in sorted(files, key=lambda p: p.name):
        s = _meme_first_state(f)
        if s is not None:
            rows.append(s)
            file_epoch[f] = pd.Timestamp(s["t"])
    if not rows:
        return pd.DataFrame(), {}
    truth = pd.DataFrame(rows)
    truth["t"] = pd.to_datetime(truth["t"], utc=True)
    truth = truth.sort_values("t").drop_duplicates(subset="t").reset_index(drop=True)
    return truth, file_epoch


def collect_predictions(files: list[Path], sat_name: str,
                        truth_times: set, file_epoch: dict) -> pd.DataFrame:
    """
    Pass 2：解析每個檔完整星曆，只保留落在「真值時刻集合」上的列
    （即較早檔對某個目標時刻 t 的外推預測）。加註 epoch 欄以便算外推齡。
    """
    frames: list[pd.DataFrame] = []
    for f in sorted(files, key=lambda p: p.name):
        ep = file_epoch.get(f)
        if ep is None:
            continue
        try:
            _, df = parse_ephemeris_file(f, sat_id=sat_name)
        except Exception as exc:
            log.debug("  [%s] 略過 %s: %s", sat_name, f.name, exc)
            continue
        if df.empty:
            continue
        df["t"] = pd.to_datetime(df["t"], utc=True)
        sub = df[df["t"].isin(truth_times)].copy()
        if sub.empty:
            continue
        sub["epoch"] = ep
        frames.append(sub[["t", "epoch"] + _STATE_COLS])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def process_satellite(sat_name: str, files: list[Path], maneuver_guard: bool,
                      maneuver_min_da: float = 0.3) -> pd.DataFrame:
    truth, file_epoch = build_truth_snapshots(files)
    if truth.empty:
        return pd.DataFrame()
    truth_times = set(truth["t"])
    preds = collect_predictions(files, sat_name, truth_times, file_epoch)
    if preds.empty:
        return pd.DataFrame()

    # 對齊真值：merge on t
    tr = truth.rename(columns={c: f"{c}_tru" for c in _STATE_COLS})
    df = pd.merge(preds, tr, on="t", how="inner", suffixes=("", ""))
    df["horizon_h"] = (df["t"] - df["epoch"]).dt.total_seconds() / 3600.0
    df = df[df["horizon_h"] > 0.05].reset_index(drop=True)   # 丟掉 age≈0 的自身列
    if df.empty:
        return pd.DataFrame()

    # 殘差（預測 − 真值）+ RTN（以真值 r,v 為基底）
    for ax in ("x", "y", "z"):
        df[f"dr_{ax}"] = df[f"r_{ax}"] - df[f"r_{ax}_tru"]
    df["pos_err_km"] = np.sqrt(df["dr_x"]**2 + df["dr_y"]**2 + df["dr_z"]**2)

    R, T, N = _rtn_basis(
        df["r_x_tru"].values, df["r_y_tru"].values, df["r_z_tru"].values,
        df["v_x_tru"].values, df["v_y_tru"].values, df["v_z_tru"].values,
    )
    dr = np.stack([df["dr_x"].values, df["dr_y"].values, df["dr_z"].values], axis=1)
    df["dr_r_km"] = (dr * R).sum(axis=1)
    df["dr_t_km"] = (dr * T).sum(axis=1)
    df["dr_n_km"] = (dr * N).sum(axis=1)

    # 機動污染標記：若 (epoch, t] 期間有真實軌道改變（|Δa| ≥ maneuver_min_da km）
    # 註：不用 detect_meme_maneuvers 的複合 score（其被單筆快照的振盪 RAAN/e 雜訊
    # 主導，會誤標近乎所有樣本）；改以半長軸淨變化這個對雜訊 robust 的實體門檻。
    df["maneuver_contaminated"] = False
    if maneuver_guard:
        mev = detect_meme_maneuvers(sat_name, files)
        if not mev.empty:
            real = mev[mev["da_km"].abs() >= maneuver_min_da]
            burns = pd.to_datetime(real["t_from"], utc=True).values
            if len(burns):
                ep = df["epoch"].values
                tt = df["t"].values
                # 對每筆殘差，檢查是否有 burn 落在 (epoch, t]
                contam = np.zeros(len(df), dtype=bool)
                for b in burns:
                    contam |= (ep < b) & (b <= tt)
                df["maneuver_contaminated"] = contam

    df.insert(0, "sat_name", sat_name)
    keep = ["sat_name", "t", "epoch", "horizon_h",
            "pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km", "maneuver_contaminated"]
    return df[keep]


def horizon_summary(resid: pd.DataFrame) -> pd.DataFrame:
    """依外推時程分箱（最近 8h）彙整位置誤差統計。"""
    r = resid.copy()
    r["horizon_bin_h"] = (np.round(r["horizon_h"] / 8.0) * 8).astype(int)
    rows = []
    for hb, g in r.groupby("horizon_bin_h"):
        rows.append({
            "horizon_bin_h": hb,
            "n":             len(g),
            "pos_med_km":    round(float(g["pos_err_km"].median()), 4),
            "pos_p95_km":    round(float(g["pos_err_km"].quantile(0.95)), 4),
            "rms_t_km":      round(float(np.sqrt((g["dr_t_km"]**2).mean())), 4),
            "rms_r_km":      round(float(np.sqrt((g["dr_r_km"]**2).mean())), 4),
            "rms_n_km":      round(float(np.sqrt((g["dr_n_km"]**2).mean())), 4),
        })
    return pd.DataFrame(rows).sort_values("horizon_bin_h").reset_index(drop=True)


def make_plot(resid: pd.DataFrame, plots_dir: Path, date_tag: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib 不可用，略過繪圖")
        return
    plots_dir.mkdir(parents=True, exist_ok=True)

    clean = resid[~resid["maneuver_contaminated"]]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for label, sub, color in [("全部", resid, "lightsteelblue"),
                              ("濾除機動", clean, "tomato")]:
        s = sub.copy()
        s["hb"] = (np.round(s["horizon_h"] / 8.0) * 8).astype(int)
        med = s.groupby("hb")["pos_err_km"].median()
        ax.plot(med.index, med.values, marker="o", lw=2, label=f"{label}中位數", color=color)
    ax.set_xlabel("外推時程 (小時)")
    ax.set_ylabel("MEME 自我預測位置誤差 (km)")
    ax.set_title(f"研究2：MEME vs MEME 外推誤差 vs 時程 ({date_tag})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / f"study2_err_vs_horizon_{date_tag}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("繪圖完成 → %s", plots_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="研究2：MEME vs MEME 0–72h 外推誤差")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--maneuver-guard", action="store_true",
                    help="標記機動污染樣本（預設關閉：0–72h 短時程、osculating Δa 受"
                         "短週期振盪主導不可靠；嚴謹的機動過濾見 study3）")
    ap.add_argument("--maneuver-min-da", type=float, default=1.0,
                    help="視為真實機動的最小 |Δa|（km），預設 1.0")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    data_root = args.data_root
    out_dir = Path(args.out_dir) if args.out_dir else data_root / "study2"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = data_root / "raw"
    sat_dirs = sorted([p for p in raw_dir.iterdir() if p.is_dir()])
    if args.max_sats:
        sat_dirs = sat_dirs[: args.max_sats]
    log.info("待處理衛星目錄：%d", len(sat_dirs))

    all_res: list[pd.DataFrame] = []
    for d in sat_dirs:
        files = find_all_ephemeris_files(d)
        if len(files) < 2:
            continue
        res = process_satellite(d.name, files, maneuver_guard=args.maneuver_guard,
                                maneuver_min_da=args.maneuver_min_da)
        if not res.empty:
            all_res.append(res)
            log.info("  [%s] n=%d  外推 %.0f–%.0fh  med=%.3f km",
                     d.name, len(res), res["horizon_h"].min(), res["horizon_h"].max(),
                     res["pos_err_km"].median())

    if not all_res:
        log.warning("無任何殘差結果，結束。")
        return

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    resid = pd.concat(all_res, ignore_index=True)
    resid.to_csv(out_dir / f"study2_meme_residuals_{date_tag}.csv",
                 index=False, encoding="utf-8-sig")
    summ = horizon_summary(resid)
    summ.to_csv(out_dir / f"study2_horizon_summary_{date_tag}.csv",
                index=False, encoding="utf-8-sig")

    n_contam = int(resid["maneuver_contaminated"].sum())
    print("\n" + "=" * 64)
    print(f"研究2 MEME 自我預測誤差（{len(resid)} 樣本 / {resid['sat_name'].nunique()} 顆）")
    if args.maneuver_guard:
        print(f"機動污染標記樣本：{n_contam}（{n_contam/len(resid):.1%}）")
    print("下表為全部樣本（外推時程分箱，最近 8h）：")
    print("=" * 64)
    print(f"  {'外推時程':>8}  {'n':>6}  {'P50(km)':>9}  {'P95(km)':>9}  {'T-RMS':>8}")
    for _, r in summ.iterrows():
        print(f"  {r['horizon_bin_h']:>6}h  {r['n']:>6}  {r['pos_med_km']:>9.3f}  "
              f"{r['pos_p95_km']:>9.3f}  {r['rms_t_km']:>8.3f}")

    if not args.no_plot:
        make_plot(resid, out_dir / "plots", date_tag)
    log.info("完成。輸出 → %s", out_dir)


if __name__ == "__main__":
    main()
