#!/usr/bin/env python3
"""
build_meme_labels.py
====================
以 Starlink MEME 精密星曆為 Ground Truth，產生「全時段」機動真值標籤，
供 Layer 3 ML 模型調教（取代舊的 4 天 transitions_2026-05-02.csv）。

設計依據：docs/MEME_truth_ML_tuning_design.md

兩個真值訊號
-----------
1. 主訊號（element jump）：重用 detect_maneuvers.analyze_satellite——
   相鄰 MEME 檔首筆狀態的軌道根數跳變（da / di / draan_res，含 J2 修正），
   已含多級分類（da_severity: none/small/medium/large、maneuver_class:
   raising/lowering/phasing/mixed/stable）。

2. 第二確認（pos_err V 型）：對每顆衛星用「最新可用 TLE」外推到每個 MEME
   首筆時刻，算 TLE-vs-MEME 位置殘差時間序列；殘差先升破門檻再回落（V 型）
   即機動特徵。若某轉換附近 ±window 內出現 V 型峰，標 poserr_confirmed=True。
   TLE 不足時 poserr_confirmed=NaN（不否證，避免流失 recall）。

輸出
----
  data/meme_truth/transitions_full_{date}.csv   逐轉換真值（含兩訊號）
  data/meme_truth/meme_labels_summary_{date}.csv 每顆衛星彙總

用法
----
  python build_meme_labels.py                 # 全 285 顆、含 pos_err 確認
  python build_meme_labels.py --max-sats 20   # 小批測試
  python build_meme_labels.py --no-poserr     # 只主訊號（快）
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

# 主訊號：重用既有、已驗證的 MEME 偵測器（含多級分類）
from detect_maneuvers import analyze_satellite

# 第二確認所需：TLE 批次載入 + 最佳 TLE 外推 + MEME 首筆讀取
from compare_tle_vs_ephemeris import (
    _meme_first_state,
    find_all_ephemeris_files,
    load_registry,
    propagate_with_best_tles,
    query_tles_in_range,
)

log = logging.getLogger("meme_labels")

# ── pos_err V 型偵測門檻（與 labeler.detect_meme_events 一致的物理概念）──────────
_PEAK_KM      = 50.0    # 殘差須升破此值才算候選峰
_RECOVERY_KM  = 20.0    # 峰後須回落至此值以下才確認 V 型
_CONFIRM_H    = 12.0    # 轉換與 V 型峰對齊容差（±小時）


def _poserr_series(sat_name: str, files: list[Path], tle_df: pd.DataFrame, ts) -> pd.DataFrame:
    """回傳 DataFrame(t, pos_err_km)：每個 MEME 首筆時刻的 TLE-vs-MEME 位置殘差。"""
    snaps = []
    for f in sorted(files, key=lambda p: p.name):
        s = _meme_first_state(f)
        if s is not None:
            snaps.append(s)
    if len(snaps) < 3 or tle_df.empty:
        return pd.DataFrame()

    meme = pd.DataFrame(snaps).sort_values("t").reset_index(drop=True)
    prop = propagate_with_best_tles(meme[["t", "r_x", "r_y", "r_z"]], tle_df, sat_name, ts)
    if prop.empty:
        return pd.DataFrame()

    # 對齊時刻（propagate_with_best_tles 依 t 排序，理應一一對應）
    m = meme.merge(prop[["t", "r_x", "r_y", "r_z"]], on="t", suffixes=("_meme", "_tle"))
    if m.empty:
        return pd.DataFrame()
    dr = np.sqrt(
        (m["r_x_tle"] - m["r_x_meme"]) ** 2
        + (m["r_y_tle"] - m["r_y_meme"]) ** 2
        + (m["r_z_tle"] - m["r_z_meme"]) ** 2
    )
    return pd.DataFrame({"t": m["t"].values, "pos_err_km": dr.values})


def _vshape_peak_times(res: pd.DataFrame) -> list[pd.Timestamp]:
    """從殘差序列找 V 型峰（升破 _PEAK_KM → 回落 _RECOVERY_KM），回傳峰值時刻清單。"""
    if res.empty:
        return []
    res = res.sort_values("t").reset_index(drop=True)
    pos = res["pos_err_km"].to_numpy(float)
    t = pd.to_datetime(res["t"], utc=True).to_numpy()
    n = len(pos)
    above = pos > _PEAK_KM
    peaks: list[pd.Timestamp] = []
    i = 0
    while i < n:
        if not above[i]:
            i += 1
            continue
        j = i
        while j < n and above[j]:
            j += 1
        win_end = j - 1
        peak_idx = i + int(np.argmax(pos[i : win_end + 1]))
        # 需在峰後見到回落，才是 V 型（否則是持續發散 Mode A）
        recovered = any(pos[k] < _RECOVERY_KM for k in range(peak_idx + 1, n))
        if recovered:
            peaks.append(pd.Timestamp(t[peak_idx]))
        i = j
    return peaks


def _confirm_transitions(trans: pd.DataFrame, peaks: list[pd.Timestamp],
                         residuals_available: bool) -> pd.Series:
    """對每筆轉換標記 pos_err V 型確認：
      True  — 中點 ±_CONFIRM_H 內有 V 型峰
      False — 殘差序列算得出但該處無 V 型峰（TLE 認為無大機動）
      NA    — 無 TLE / 殘差算不出，無從確認（不否證，保留 recall）
    """
    if not residuals_available:
        return pd.Series([pd.NA] * len(trans), index=trans.index, dtype="object")
    if not peaks:
        return pd.Series([False] * len(trans), index=trans.index, dtype="object")
    peak_ns = np.array([p.value for p in peaks], dtype=np.int64)
    tol_ns = int(_CONFIRM_H * 3600 * 1e9)
    mids = (
        pd.to_datetime(trans["t_from"], utc=True).astype("int64").to_numpy()
        + pd.to_datetime(trans["t_to"], utc=True).astype("int64").to_numpy()
    ) // 2
    out = [bool(np.any(np.abs(peak_ns - m) <= tol_ns)) for m in mids]
    return pd.Series(out, index=trans.index, dtype="object")


def main() -> None:
    ap = argparse.ArgumentParser(description="產生全時段 MEME 真值標籤（含 pos_err V 型第二確認）")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--no-poserr", action="store_true", help="略過 pos_err V 型第二確認（較快）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    data_root = args.data_root
    registry_csv = Path(args.registry) if args.registry else data_root / "url_registry.csv"
    out_dir = Path(args.out_dir) if args.out_dir else data_root / "meme_truth"
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = load_registry(registry_csv)                       # index=norad_id, col sat_name
    name_to_norad = {v: k for k, v in reg["sat_name"].items()}

    raw_dir = data_root / "raw"
    sat_dirs = sorted([p for p in raw_dir.iterdir() if p.is_dir()
                       and not p.name.upper().startswith("STARLINK-DEMO")])
    if args.max_sats:
        sat_dirs = sat_dirs[: args.max_sats]
    log.info("待處理衛星目錄：%d", len(sat_dirs))

    # ── 主訊號：全時段 transitions（多級分類） ──────────────────────────────
    all_trans: list[pd.DataFrame] = []
    for d in sat_dirs:
        tr = analyze_satellite(d.name, d)
        if not tr.empty:
            tr["norad_id"] = name_to_norad.get(d.name, pd.NA)
            all_trans.append(tr)
    if not all_trans:
        log.error("無任何 transitions，結束。")
        return
    trans = pd.concat(all_trans, ignore_index=True)
    log.info("主訊號完成：%d transitions / %d 顆（span %s → %s）",
             len(trans), trans["sat_name"].nunique(),
             trans["t_from"].min(), trans["t_to"].max())

    # ── 第二確認：pos_err V 型 ──────────────────────────────────────────────
    trans["poserr_confirmed"] = pd.Series([pd.NA] * len(trans), dtype="object")
    if not args.no_poserr:
        log.info("計算 pos_err V 型第二確認（批次載入 TLE）…")
        # 每顆衛星的 MEME 觀測窗（供 query_tles_in_range）
        norad_to_window: dict[int, tuple[pd.Timestamp, pd.Timestamp]] = {}
        files_by_sat: dict[str, list[Path]] = {}
        for d in sat_dirs:
            nid = name_to_norad.get(d.name)
            if nid is None:
                continue
            files = find_all_ephemeris_files(d)
            if len(files) < 3:
                continue
            files_by_sat[d.name] = files
            g = trans[trans["sat_name"] == d.name]
            if g.empty:
                continue
            t0 = pd.to_datetime(g["t_from"], utc=True).min()
            t1 = pd.to_datetime(g["t_to"], utc=True).max()
            norad_to_window[int(nid)] = (t0, t1)

        con = duckdb.connect(args.db, read_only=True)
        tle_pool = query_tles_in_range(con, norad_to_window, pre_window_days=3.0)
        con.close()

        from skyfield.api import load as skyfield_load
        ts = skyfield_load.timescale()

        n_conf = 0
        for d in sat_dirs:
            nid = name_to_norad.get(d.name)
            files = files_by_sat.get(d.name)
            if nid is None or files is None:
                continue
            tle_df = tle_pool.get(int(nid))
            if tle_df is None or tle_df.empty:
                continue
            res = _poserr_series(d.name, files, tle_df, ts)
            peaks = _vshape_peak_times(res)
            mask = trans["sat_name"] == d.name
            conf = _confirm_transitions(trans[mask], peaks, residuals_available=not res.empty)
            trans.loc[mask, "poserr_confirmed"] = conf.values
            n_conf += int(sum(1 for c in conf if c is True))
        log.info("pos_err 確認完成：%d 筆轉換獲 V 型確認", n_conf)

    # ── 標籤欄位 ────────────────────────────────────────────────────────────
    # label_meme：主訊號機動真值（da_severity != none）
    trans["label_meme"] = (trans["da_severity"] != "none").astype(int)
    # confirmed_both：主訊號 + pos_err V 型雙訊號皆命中（高信心正樣本）
    trans["confirmed_both"] = (
        (trans["label_meme"] == 1) & (trans["poserr_confirmed"] == True)  # noqa: E712
    )

    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_csv = out_dir / f"transitions_full_{date_tag}.csv"
    trans.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # ── 彙總 ────────────────────────────────────────────────────────────────
    summ = (
        trans.groupby(["sat_name", "inc_family", "maneuver_class"])
        .agg(n_trans=("label_meme", "size"),
             n_maneuver=("label_meme", "sum"),
             n_confirmed=("confirmed_both", "sum"),
             max_abs_da=("da_km", lambda x: float(x.abs().max())))
        .reset_index()
    )
    summ.to_csv(out_dir / f"meme_labels_summary_{date_tag}.csv",
                index=False, encoding="utf-8-sig")

    # ── 摘要 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 66)
    print(f"MEME 真值標籤（全時段）  →  {out_csv}")
    print("=" * 66)
    print(f"  轉換總數        : {len(trans)}  /  {trans['sat_name'].nunique()} 顆")
    print(f"  時間範圍        : {trans['t_from'].min()}  →  {trans['t_to'].max()}")
    print(f"  label_meme=1    : {int(trans['label_meme'].sum())}  "
          f"({100*trans['label_meme'].mean():.1f}%)")
    print(f"  da_severity     : {trans['da_severity'].value_counts().to_dict()}")
    print(f"  maneuver_class  : {trans['maneuver_class'].value_counts().to_dict()}")
    if not args.no_poserr:
        pc = trans["poserr_confirmed"]
        print(f"  poserr V 型確認 : True={int((pc==True).sum())}  "  # noqa: E712
              f"False={int((pc==False).sum())}  NA={int(pc.isna().sum())}")
        print(f"  雙訊號確認正樣本: {int(trans['confirmed_both'].sum())}")


if __name__ == "__main__":
    main()
