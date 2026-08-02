#!/usr/bin/env python3
"""
study1_tle_error_distribution.py
================================
研究 1：以「每個 MEME 檔的第一筆狀態向量」為近似 Ground Truth，
量化公開 TLE（SGP4 傳播）的位置誤差分布。

方法論
------
每個 MEME 檔涵蓋 72h、1 分鐘間隔，**第一筆**是外推量最小、最接近 SpaceX
定軌真值的一筆（越往後的列越是預測外推）。因此我們對每個 MEME 檔只取第一筆
（沿用 compare_tle_vs_ephemeris._meme_first_state），組成一條「近真值快照序列」
（~8h 間隔）。對每個快照時刻，選取最近的先行 TLE 以 SGP4 傳播，計算 TLE − MEME
的 ECI 與 RTN 殘差，並記錄該筆 TLE 的年齡（epoch → 快照時刻）。

彙整後即得：
  - TLE 位置誤差的分布（中位數 / P95 / P99 / 最大）
  - 誤差隨 TLE 年齡增長的關係（預期：沿軌 T 分量主導、近似線性）
  - RTN 三分量分解（佐證 TLE 對微小面外/切向機動不敏感）

重要前提：MEME「首筆」仍是估計值，只是比公開 TLE 精確 1~2 個數量級，
故稱「近似 GT / 高精度參考」，不宜逕稱 ground truth。

輸出
----
  data/study1/study1_tle_residuals_{date}.csv   逐快照殘差
  data/study1/study1_summary_{date}.csv         逐衛星 + 艦隊摘要
  data/study1/plots/study1_ecdf_{date}.png      位置誤差 ECDF
  data/study1/plots/study1_err_vs_age_{date}.png 誤差 vs TLE 年齡

用法
----
  python study1_tle_error_distribution.py --max-sats 5     # 先小批驗證
  python study1_tle_error_distribution.py                  # 全部衛星
  python study1_tle_error_distribution.py --no-plot
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
from skyfield.api import load as skyfield_load

# 重用既有地基（不修改原檔）
from compare_tle_vs_ephemeris import (
    _meme_first_state,
    _rtn_basis,
    find_all_ephemeris_files,
    load_registry,
    propagate_tle,
    query_tles_in_range,
)

log = logging.getLogger("study1")


# ── 近真值快照序列 ────────────────────────────────────────────────────────────

def collect_first_state_snapshots(sat_name: str, ephem_files: list[Path]) -> pd.DataFrame:
    """
    對每個 MEME 檔取第一筆狀態向量，組成近真值快照序列。

    回傳 DataFrame（欄位 t, r_x, r_y, r_z, v_x, v_y, v_z，UTC-aware，依 t 排序）。
    這與 compare_tle_vs_ephemeris 的殘差流程共用相同欄位格式，可直接餵給
    compute_residuals 風格的計算。
    """
    rows: list[dict] = []
    for f in sorted(ephem_files, key=lambda p: p.name):
        s = _meme_first_state(f)
        if s is not None:
            rows.append(s)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    return df.sort_values("t").drop_duplicates(subset="t").reset_index(drop=True)


def propagate_best_tle_with_age(
    snap_df: pd.DataFrame,
    tle_df: pd.DataFrame,
    sat_name: str,
    ts,
) -> pd.DataFrame:
    """
    對每個快照時刻選最近先行 TLE（epoch ≤ t）並 SGP4 傳播，同時記錄 TLE 年齡。

    與 compare_tle_vs_ephemeris.propagate_with_best_tles 邏輯相同（searchsorted +
    分組批次傳播），但額外輸出 tle_epoch / tle_age_days 逐列欄位，供誤差-年齡分析。

    回傳 DataFrame：t, r_x..v_z（TLE 傳播態）, tle_epoch, tle_age_days。
    """
    if tle_df.empty or snap_df.empty:
        return pd.DataFrame()

    times  = pd.to_datetime(snap_df["t"], utc=True)
    epochs = pd.to_datetime(tle_df["epoch_utc"], utc=True).values

    idx = np.searchsorted(epochs, times.values, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)

    work = snap_df[["t"]].copy()
    work["_tle_idx"] = idx

    frames: list[pd.DataFrame] = []
    for tle_idx, group in work.groupby("_tle_idx", sort=True):
        row = tle_df.iloc[int(tle_idx)]
        try:
            chunk = propagate_tle(
                row["line1"], row["line2"], sat_name,
                group["t"].reset_index(drop=True), ts,
            )
        except Exception as exc:
            log.debug("  [%s] SGP4 error TLE %s: %s", sat_name, row["epoch_utc"], exc)
            continue
        ep = pd.Timestamp(row["epoch_utc"])
        ep = ep.tz_localize("UTC") if ep.tzinfo is None else ep.tz_convert("UTC")
        chunk["tle_epoch"]     = ep
        chunk["tle_age_days"]  = (chunk["t"] - ep).dt.total_seconds() / 86400.0
        frames.append(chunk)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("t").reset_index(drop=True)


def compute_residuals_rtn(truth: pd.DataFrame, tle: pd.DataFrame) -> pd.DataFrame:
    """
    在時間戳 t 上 inner join，計算 (TLE − MEME近真值) 的 ECI + RTN 殘差。

    RTN 基底以近真值（MEME 首筆快照）的位置/速度為參考。
    回傳含 pos_err_km / vel_err_kms / dr_r/t/n_km / tle_age_days 的 DataFrame。
    """
    m = truth.rename(columns={c: f"{c}_m" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]})
    t = tle.rename(columns={c: f"{c}_t" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]})
    df = pd.merge(m, t, on="t", how="inner")
    if df.empty:
        return df

    for ax in ("x", "y", "z"):
        df[f"dr_{ax}"] = df[f"r_{ax}_t"] - df[f"r_{ax}_m"]
        df[f"dv_{ax}"] = df[f"v_{ax}_t"] - df[f"v_{ax}_m"]
    df["pos_err_km"]  = np.sqrt(df["dr_x"]**2 + df["dr_y"]**2 + df["dr_z"]**2)
    df["vel_err_kms"] = np.sqrt(df["dv_x"]**2 + df["dv_y"]**2 + df["dv_z"]**2)

    R, T, N = _rtn_basis(
        df["r_x_m"].values, df["r_y_m"].values, df["r_z_m"].values,
        df["v_x_m"].values, df["v_y_m"].values, df["v_z_m"].values,
    )
    dr = np.stack([df["dr_x"].values, df["dr_y"].values, df["dr_z"].values], axis=1)
    df["dr_r_km"] = (dr * R).sum(axis=1)
    df["dr_t_km"] = (dr * T).sum(axis=1)
    df["dr_n_km"] = (dr * N).sum(axis=1)
    return df


# ── 主流程 ────────────────────────────────────────────────────────────────────

def process_satellite(norad_id, sat_name, ephem_files, tle_df, ts) -> tuple[dict, pd.DataFrame | None]:
    snap = collect_first_state_snapshots(sat_name, ephem_files)
    if snap.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_snapshots"}, None
    if tle_df is None or tle_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_tle"}, None

    tle_prop = propagate_best_tle_with_age(snap, tle_df, sat_name, ts)
    if tle_prop.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_propagation"}, None

    res = compute_residuals_rtn(snap, tle_prop)
    if res.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_match"}, None

    res.insert(0, "sat_name", sat_name)
    res.insert(0, "norad_id", norad_id)
    keep = ["norad_id", "sat_name", "t", "tle_epoch", "tle_age_days",
            "pos_err_km", "vel_err_kms", "dr_r_km", "dr_t_km", "dr_n_km"]
    res = res[keep]

    summary = {
        "norad_id":          norad_id,
        "sat_name":          sat_name,
        "status":            "ok",
        "n_snapshots":       len(snap),
        "n_points":          len(res),
        "tle_age_mean_days": round(float(res["tle_age_days"].mean()), 3),
        "pos_err_med_km":    round(float(res["pos_err_km"].median()), 4),
        "pos_err_p95_km":    round(float(res["pos_err_km"].quantile(0.95)), 4),
        "pos_err_max_km":    round(float(res["pos_err_km"].max()), 4),
        "rms_r_km":          round(float(np.sqrt((res["dr_r_km"]**2).mean())), 4),
        "rms_t_km":          round(float(np.sqrt((res["dr_t_km"]**2).mean())), 4),
        "rms_n_km":          round(float(np.sqrt((res["dr_n_km"]**2).mean())), 4),
    }
    return summary, res


def make_plots(resid: pd.DataFrame, plots_dir: Path, date_tag: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib 不可用，略過繪圖")
        return

    plots_dir.mkdir(parents=True, exist_ok=True)

    # (1) 位置誤差 ECDF
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.sort(resid["pos_err_km"].dropna().values)
    y = np.arange(1, len(x) + 1) / len(x)
    ax.plot(x, y, color="steelblue", lw=1.5)
    for pct in (50, 95, 99):
        v = float(np.percentile(x, pct))
        ax.axvline(v, ls="--", lw=0.9, label=f"P{pct}: {v:.2f} km")
    ax.set_xlabel("TLE 位置誤差 (km)  [vs MEME 首筆近真值]")
    ax.set_ylabel("CDF")
    ax.set_title(f"研究1：TLE 位置誤差分布 ECDF ({date_tag})")
    ax.set_ylim(0, 1.02)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / f"study1_ecdf_{date_tag}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # (2) 誤差 vs TLE 年齡（散點 + 年齡分箱中位數）
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(resid["tle_age_days"], resid["pos_err_km"], s=6, alpha=0.25,
               color="teal", linewidths=0, label="逐快照")
    bins = np.arange(0, resid["tle_age_days"].max() + 0.5, 0.5)
    resid = resid.copy()
    resid["_agebin"] = pd.cut(resid["tle_age_days"], bins)
    med = resid.groupby("_agebin", observed=True)["pos_err_km"].median()
    centers = [iv.mid for iv in med.index]
    ax.plot(centers, med.values, color="tomato", lw=2, marker="o", label="每 0.5 天中位數")
    ax.set_xlabel("TLE 年齡 (天)")
    ax.set_ylabel("TLE 位置誤差 (km)")
    ax.set_title(f"研究1：TLE 位置誤差 vs TLE 年齡 ({date_tag})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / f"study1_err_vs_age_{date_tag}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("繪圖完成 → %s", plots_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="研究1：TLE 誤差分布（以 MEME 首筆為近真值）")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--sat-list", default=None,
                    help="檔案路徑，每行一個 MEME 衛星名，只處理清單內衛星")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    data_root = args.data_root
    registry_csv = Path(args.registry) if args.registry else data_root / "url_registry.csv"
    out_dir = Path(args.out_dir) if args.out_dir else data_root / "study1"
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = load_registry(registry_csv)                      # index=norad_id, col sat_name
    name_to_norad = {v: k for k, v in reg["sat_name"].items()}

    raw_dir = data_root / "raw"
    sat_dirs = sorted([p for p in raw_dir.iterdir() if p.is_dir()])
    if args.sat_list:
        wanted = {ln.strip() for ln in Path(args.sat_list).read_text().splitlines() if ln.strip()}
        sat_dirs = [p for p in sat_dirs if p.name in wanted]
    if args.max_sats:
        sat_dirs = sat_dirs[: args.max_sats]
    log.info("待處理衛星目錄：%d", len(sat_dirs))

    # 蒐集每顆衛星的觀測窗（首尾快照時刻）以批次查 TLE
    ts = skyfield_load.timescale()
    sat_entries: list[tuple] = []
    norad_to_window: dict[int, tuple] = {}
    for d in sat_dirs:
        sat_name = d.name
        norad_id = name_to_norad.get(sat_name)
        if norad_id is None:
            log.debug("  [%s] registry 無對應 norad_id，略過", sat_name)
            continue
        files = find_all_ephemeris_files(d)
        if not files:
            continue
        snap = collect_first_state_snapshots(sat_name, files)
        if snap.empty:
            continue
        norad_to_window[int(norad_id)] = (snap["t"].min(), snap["t"].max())
        sat_entries.append((int(norad_id), sat_name, files))

    log.info("有效衛星（含快照）：%d，批次查詢 TLE…", len(sat_entries))
    con = duckdb.connect(args.db, read_only=True)
    tle_pool = query_tles_in_range(con, norad_to_window, pre_window_days=3.0)
    con.close()

    summaries: list[dict] = []
    all_res: list[pd.DataFrame] = []
    for norad_id, sat_name, files in sat_entries:
        s, res = process_satellite(norad_id, sat_name, files, tle_pool.get(norad_id), ts)
        summaries.append(s)
        if res is not None:
            all_res.append(res)
        log.info("  [%s] %s  n=%s  med=%s km",
                 sat_name, s["status"], s.get("n_points", "-"), s.get("pos_err_med_km", "-"))

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    pd.DataFrame(summaries).to_csv(out_dir / f"study1_summary_{date_tag}.csv",
                                   index=False, encoding="utf-8-sig")

    if not all_res:
        log.warning("無任何殘差結果，結束。")
        return
    resid = pd.concat(all_res, ignore_index=True)
    resid.to_csv(out_dir / f"study1_tle_residuals_{date_tag}.csv",
                 index=False, encoding="utf-8-sig")

    # 艦隊級分布摘要（列印）
    pe = resid["pos_err_km"]
    print("\n" + "=" * 64)
    print(f"研究1 艦隊級 TLE 位置誤差分布（{len(resid)} 快照 / {resid['norad_id'].nunique()} 顆）")
    print("=" * 64)
    print(f"  中位數 P50 : {pe.median():.3f} km")
    print(f"  P95        : {pe.quantile(0.95):.3f} km")
    print(f"  P99        : {pe.quantile(0.99):.3f} km")
    print(f"  最大       : {pe.max():.3f} km")
    print(f"  RTN RMS    : R={np.sqrt((resid['dr_r_km']**2).mean()):.3f}  "
          f"T={np.sqrt((resid['dr_t_km']**2).mean()):.3f}  "
          f"N={np.sqrt((resid['dr_n_km']**2).mean()):.3f} km  "
          f"(T 沿軌通常主導)")
    print("\n  誤差 vs TLE 年齡（每 0.5 天分箱中位數）：")
    tmp = resid.copy()
    tmp["_b"] = (tmp["tle_age_days"] // 0.5) * 0.5
    for b, g in tmp.groupby("_b"):
        print(f"    {b:>4.1f}–{b+0.5:.1f} 天 : 中位 {g['pos_err_km'].median():7.3f} km  (n={len(g)})")

    if not args.no_plot:
        make_plots(resid, out_dir / "plots", date_tag)

    log.info("完成。輸出 → %s", out_dir)


if __name__ == "__main__":
    main()
