#!/usr/bin/env python3
"""
burn_arc_profiler.py — MEME 檔內推力弧剖面器 + 相鄰檔「新機動計畫上傳」偵測器
==============================================================================
背景（期中報告 §11 先導實驗）：SpaceX 把計畫機動預先編入精密星曆，故「相鄰檔比對」
只量得定軌/計畫更新雜訊（~100–250 m）；正確作法是「檔內比對」——由每檔逐分鐘 r,v
以活力積分算瞬時半長軸 a(t)，推力弧以 a 的爬升直接顯現，可達分鐘級時刻定位。

功能：
  1) 推力弧剖面（per file）：a(t) 以一個軌道週期之滾動中位消 J2 短週期 → 30 分鐘
     跨距差分超過門檻之連續段合併為 arc，輸出起訖時刻、Δa、換算 ΔV（(Δa/2)·n）。
  2) 計畫上傳偵測（adjacent files）：相鄰發布檔重疊首 10 分鐘的位置差中位數，
     跳出正常帶（NORMAL_BAND_M）即旗標「新機動計畫上傳」。

用法：python burn_arc_profiler.py --sat STARLINK-5846 [--start 2026-07-01 --end 2026-07-10]
輸出：data/benchmark/burn_arcs_<sat>.csv、plan_uploads_<sat>.csv + manifest
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from starlink_ephemeris.parser import parse_ephemeris_file
from satdet import record
from satdet.common import HOUR_NS

MU = 398600.4418
RAW_DIR = Path("data/raw")
ARC_LAG_MIN = 30          # 差分跨距（分鐘）
ARC_THR_KM = 0.15         # 30 分鐘 Δa 門檻（>3×平滑後殘餘抖動）
NORMAL_BAND_M = 400.0     # 相鄰檔首段位置差正常帶上限（實測 100–250 m）


def osculating_sma(df: pd.DataFrame) -> pd.Series:
    """由 r,v 逐點算瞬時半長軸（vis-viva）。index=UTC 時間。"""
    r = df[["r_x", "r_y", "r_z"]].to_numpy()
    v = df[["v_x", "v_y", "v_z"]].to_numpy()
    rn = np.linalg.norm(r, axis=1)
    a = 1.0 / (2.0 / rn - (v ** 2).sum(1) / MU)
    return pd.Series(a, index=pd.to_datetime(df["t"]))


def profile_arcs(a: pd.Series) -> pd.DataFrame:
    """平滑 a(t) → 30 分鐘差分 → 連續超門檻段合併為推力弧。"""
    med = a.rolling(97, center=True).median().dropna()   # ~1 軌道週期，消 J2 短週期
    da = med.diff(ARC_LAG_MIN)
    hot = da.abs() > ARC_THR_KM
    arcs = []
    start = None
    for t, h in hot.items():
        if h and start is None:
            start = t
        elif not h and start is not None:
            seg = med.loc[start:t]
            arcs.append({"t_start": start, "t_end": t,
                         "dur_h": round((t - start).total_seconds() / 3600, 2),
                         "da_km": round(float(seg.iloc[-1] - seg.iloc[0]), 3)})
            start = None
    if start is not None:
        seg = med.loc[start:]
        arcs.append({"t_start": start, "t_end": med.index[-1],
                     "dur_h": round((med.index[-1] - start).total_seconds() / 3600, 2),
                     "da_km": round(float(seg.iloc[-1] - seg.iloc[0]), 3)})
    out = pd.DataFrame(arcs)
    if not out.empty:
        a_mid = float(med.median())
        n = np.sqrt(MU / a_mid ** 3)
        out["dv_ms"] = (out["da_km"].abs() / 2 * n * 1000).round(4)   # 式(8)
    return out


def merge_file_arcs(per_file: dict[str, pd.DataFrame], gap_h: float = 6.0) -> pd.DataFrame:
    """聚合為「推力機動作業」：電推進以每軌分段點火，微結構過瑣；將相隔 < gap_h 的
    micro-arc 併為一個 campaign，輸出起訖、淨 Δa、峰值單步時刻（最強推力弧中心）。"""
    rows = []
    for fname, arcs in per_file.items():
        for _, r in arcs.iterrows():
            rows.append({**r, "src_file": fname})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates("t_start").sort_values("t_start").reset_index(drop=True)
    camps = []
    cur = None
    for _, r in df.iterrows():
        if cur is None:
            cur = {"t_start": r["t_start"], "t_end": r["t_end"],
                   "peak_da": r["da_km"], "peak_t": r["t_start"], "n_arcs": 1}
        elif (r["t_start"] - cur["t_end"]).total_seconds() / 3600 < gap_h:
            cur["t_end"] = r["t_end"]; cur["n_arcs"] += 1
            if abs(r["da_km"]) > abs(cur["peak_da"]):
                cur["peak_da"] = r["da_km"]; cur["peak_t"] = r["t_start"]
        else:
            camps.append(cur)
            cur = {"t_start": r["t_start"], "t_end": r["t_end"],
                   "peak_da": r["da_km"], "peak_t": r["t_start"], "n_arcs": 1}
    if cur:
        camps.append(cur)
    return pd.DataFrame(camps)


def plan_upload_scan(files: list[Path], sat: str) -> pd.DataFrame:
    """相鄰檔重疊首 10 分鐘位置差中位數；> NORMAL_BAND_M 旗標計畫上傳。"""
    dfs = []
    for f in files:
        _, df = parse_ephemeris_file(f, sat)
        dfs.append((f.name, df.set_index(pd.to_datetime(df["t"]))))
    rows = []
    for (na, A), (nb, B) in zip(dfs[:-1], dfs[1:]):
        common = A.index.intersection(B.index)[:10]
        if len(common) == 0:
            continue
        d = np.linalg.norm(A.loc[common, ["r_x", "r_y", "r_z"]].to_numpy()
                           - B.loc[common, ["r_x", "r_y", "r_z"]].to_numpy(), axis=1)
        dm = float(np.median(d)) * 1000.0   # m
        rows.append({"file_prev": na, "file_next": nb, "first10min_diff_m": round(dm, 1),
                     "flag_new_plan": dm > NORMAL_BAND_M})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sat", required=True, help="衛星名（data/raw/ 目錄名），如 STARLINK-5846")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    d = RAW_DIR / args.sat
    files = sorted(d.glob("*.txt"))
    if args.start:
        files = [f for f in files if f.stem >= args.start]
    if args.end:
        files = [f for f in files if f.stem <= args.end + "T99"]
    if not files:
        print(f"{d} 無檔案"); sys.exit(1)
    print(f"{args.sat}: {len(files)} 個 MEME 發布檔（{files[0].stem} ~ {files[-1].stem}）")

    # 1) 推力弧剖面
    per_file = {}
    for f in files:
        _, df = parse_ephemeris_file(f, args.sat)
        arcs = profile_arcs(osculating_sma(df))
        if not arcs.empty:
            per_file[f.name] = arcs
    arcs = merge_file_arcs(per_file)
    print(f"\n=== 推力機動作業剖面（聚合後 {len(arcs)} 個 campaign；電推每軌分段點火已併）===")
    if not arcs.empty:
        show = arcs.copy()
        show["起"] = show["t_start"].dt.strftime("%m-%d %H:%M")
        show["訖"] = show["t_end"].dt.strftime("%m-%d %H:%M")
        show["峰值單步時刻"] = show["peak_t"].dt.strftime("%m-%d %H:%M")
        show["含弧數"] = show["n_arcs"]; show["峰值Δa_km"] = show["peak_da"]
        print(show[["起", "訖", "峰值單步時刻", "峰值Δa_km", "含弧數"]].to_string(index=False))

    # 2) 計畫上傳偵測
    up = plan_upload_scan(files, args.sat)
    n_flag = int(up["flag_new_plan"].sum()) if not up.empty else 0
    if not up.empty:
        print(f"\n=== 計畫上傳偵測（{len(up)} 對相鄰檔）===")
        print(f"  首 10 分鐘位置差：中位 {up['first10min_diff_m'].median():.0f} m、"
              f"P95 {up['first10min_diff_m'].quantile(0.95):.0f} m、最大 {up['first10min_diff_m'].max():.0f} m")
        print(f"  超過正常帶（>{NORMAL_BAND_M:.0f} m）旗標：{n_flag} 次")
        for _, r in up[up["flag_new_plan"]].iterrows():
            print(f"    {r['file_prev'][:16]} → {r['file_next'][:16]}  差 {r['first10min_diff_m']:.0f} m")

    out_dir = Path("data/benchmark")
    fa = out_dir / f"burn_arcs_{args.sat}.csv"
    fu = out_dir / f"plan_uploads_{args.sat}.csv"
    arcs.to_csv(fa, index=False, encoding="utf-8-sig")
    up.to_csv(fu, index=False, encoding="utf-8-sig")
    record("burn_arc_profiler",
           inputs={"raw_dir": d, "n_files": len(files)},
           params={"arc_lag_min": ARC_LAG_MIN, "arc_thr_km": ARC_THR_KM,
                   "normal_band_m": NORMAL_BAND_M, "sat": args.sat},
           outputs={"burn_arcs": fa, "plan_uploads": fu})
    print(f"\n輸出 → {fa}\n     → {fu}")


if __name__ == "__main__":
    main()
