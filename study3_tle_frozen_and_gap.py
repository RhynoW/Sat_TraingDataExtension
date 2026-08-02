#!/usr/bin/env python3
"""
study3_tle_frozen_and_gap.py
============================
研究 3：TLE 凍結外推曲線（1–7 天）＋ 下載斷點 ~7 天 spot-check，含機動過濾。

兩部分
------
Part A — TLE 凍結外推曲線：
    取一筆 TLE，**凍結**不更新，SGP4 外推 1、2、…、7 天，與 MEME 首筆近真值比對，
    得到「單筆 TLE 隨齡退化」曲線。這與研究1（每時刻選最新 TLE、最小化誤差）相反，
    刻意讓 TLE 老化，量測公開 TLE 的預測退化速率。

Part B — 斷點 spot-check：
    自動偵測每顆衛星 MEME 檔的最大時間斷點（出國暫停下載造成，約 6/14→6/21 一週）。
    取斷點前最後一筆 TLE，外推越過斷點到斷點後第一筆 MEME 真值，量測 ~7 天長時程誤差。

機動過濾（robust）
------------------
MEME 首筆為 osculating 元素，其半長軸受 J2 短週期振盪主導（±數 km），無法可靠判斷機動。
本腳本改用 **檔案平均半長軸**（對整個 72h 檔的 osculating a 取平均 → 消去短週期振盪，
逼近平均半長軸）。相鄰檔平均 a 的階躍 ≥ 門檻即判定期間發生真實機動。斷點兩側平均 a
差 ≥ 門檻 → 該衛星在斷點期間機動，spot-check 予以標記/排除。

輸出
----
  data/study3/study3_frozen_curve_{date}.csv       Part A 逐 (TLE×horizon) 殘差
  data/study3/study3_frozen_summary_{date}.csv     Part A 依整數天分箱統計
  data/study3/study3_gap_spotcheck_{date}.csv      Part B 逐衛星 ~7 天誤差
  data/study3/plots/study3_frozen_curve_{date}.png

用法
----
  python study3_tle_frozen_and_gap.py --max-sats 5
  python study3_tle_frozen_and_gap.py --part A --tle-stride 4
  python study3_tle_frozen_and_gap.py --part B
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

from datetime import timezone

from compare_tle_vs_ephemeris import (
    _MU_M,
    _MEME_LINE_RE,
    _meme_first_state,
    _rtn_basis,
    find_all_ephemeris_files,
    load_registry,
    propagate_tle,
    query_tles_in_range,
)

log = logging.getLogger("study3")

_DAY = pd.Timedelta(days=1)
# 平均半長軸需對「整數個軌道週期」平均才能消去 J2 短週期振盪；只取 ~1.6 個軌道
# （150 行）會殘留 ~0.3–0.5km 振盪雜訊，污染 8h 階躍判斷。改取 ~10 個軌道
# （~960 行 ≈ 16h @ 1-min），殘留降至 <0.1km；仍只讀檔案開頭、不建 DataFrame，遠快於完整解析。
_MEAN_A_LINES = 960


def file_epoch_mean_a_first(path: Path, sat_name: str, max_lines: int = _MEAN_A_LINES) -> dict | None:
    """
    輕量解析：只讀前 max_lines 筆狀態向量，回傳：
      epoch    — 第一筆時刻（外推齡 0）
      mean_a   — 首個軌道週期內 osculating 半長軸平均（消去短週期振盪 ≈ 平均半長軸）
      first    — 第一筆狀態 dict（r_x..v_z）供作近真值

    只讀檔案開頭數十行、不建 DataFrame，比完整解析快約一個數量級。
    """
    rs: list[tuple] = []
    vs: list[tuple] = []
    epoch = None
    first = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _MEME_LINE_RE.match(line.strip())
                if not m:
                    continue
                vals = tuple(float(m.group(i)) for i in range(6, 12))
                rs.append(vals[:3])
                vs.append(vals[3:])
                if first is None:
                    yr, doy = int(m.group(1)), int(m.group(2))
                    hh, mm  = int(m.group(3)), int(m.group(4))
                    ss_f = float(m.group(5)); ss_i = int(ss_f)
                    us = round((ss_f - ss_i) * 1_000_000)
                    epoch = (pd.Timestamp(yr, 1, 1, tzinfo=timezone.utc)
                             + pd.Timedelta(days=doy - 1)
                             + pd.Timedelta(hours=hh, minutes=mm, seconds=ss_i, microseconds=us))
                    first = {"r_x": vals[0], "r_y": vals[1], "r_z": vals[2],
                             "v_x": vals[3], "v_y": vals[4], "v_z": vals[5]}
                if len(rs) >= max_lines:
                    break
    except Exception:
        return None
    if first is None:
        return None
    r = np.asarray(rs, float); v = np.asarray(vs, float)
    rn = np.linalg.norm(r, axis=1); vn = np.linalg.norm(v, axis=1)
    a  = 1.0 / (2.0 / rn - vn**2 / _MU_M)          # vis-viva，向量化
    return {"epoch": epoch, "mean_a": float(np.mean(a)), "first": first}


def build_file_table(files: list[Path], sat_name: str) -> pd.DataFrame:
    """回傳依 epoch 排序的 DataFrame：epoch, mean_a, r_x..v_z（首筆近真值）。"""
    rows = []
    for f in sorted(files, key=lambda p: p.name):
        d = file_epoch_mean_a_first(f, sat_name)
        if d is not None:
            rows.append({"epoch": d["epoch"], "mean_a": d["mean_a"], **d["first"]})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("epoch").drop_duplicates("epoch").reset_index(drop=True)


def _epoch_ns(file_tbl: pd.DataFrame) -> np.ndarray:
    """檔案 epoch 轉為 UTC int64 奈秒（避免 tz-aware/naive 比較問題）。"""
    return file_tbl["epoch"].dt.tz_convert("UTC").astype("int64").to_numpy()


def maneuver_burn_times(file_tbl: pd.DataFrame, thr_km: float) -> np.ndarray:
    """相鄰檔平均 a 階躍 ≥ thr_km → 判定機動，回傳 burn 近似時刻（int64 奈秒）。"""
    if len(file_tbl) < 2:
        return np.array([], dtype=np.int64)
    da = np.abs(np.diff(file_tbl["mean_a"].to_numpy()))
    idx = np.where(da >= thr_km)[0]
    e_ns = _epoch_ns(file_tbl)
    return np.array([(e_ns[i] + e_ns[i+1]) // 2 for i in idx], dtype=np.int64)


# ── Part A：TLE 凍結外推曲線 ──────────────────────────────────────────────────

def frozen_curve_for_sat(sat_name, tle_df, file_tbl, ts,
                         horizons_d, tol_h, burns) -> pd.DataFrame:
    """對每筆 TLE 凍結外推至 epoch+N 天，與最近 MEME 近真值比對。"""
    if tle_df.empty or file_tbl.empty:
        return pd.DataFrame()

    truth_ns = _epoch_ns(file_tbl)                              # 近真值時刻（int64 ns）
    truth_state = file_tbl[["r_x","r_y","r_z","v_x","v_y","v_z"]].to_numpy(float)
    tol_ns = int(tol_h * 3600 * 1e9)
    day_ns = 86400 * 10**9

    out = []
    for _, tle in tle_df.iterrows():
        e = pd.Timestamp(tle["epoch_utc"])
        e = e.tz_localize("UTC") if e.tzinfo is None else e.tz_convert("UTC")
        e_ns = e.value

        # 對每個整數天 horizon 找最近的近真值快照
        targets, matched_state, matched_h = [], [], []
        for N in horizons_d:
            t_tgt_ns = e_ns + N * day_ns
            j = int(np.searchsorted(truth_ns, t_tgt_ns))
            cands = [k for k in (j-1, j) if 0 <= k < len(truth_ns)]
            if not cands:
                continue
            k = min(cands, key=lambda k: abs(int(truth_ns[k]) - t_tgt_ns))
            if abs(int(truth_ns[k]) - t_tgt_ns) > tol_ns:
                continue
            targets.append(pd.Timestamp(int(truth_ns[k]), tz="UTC"))
            matched_state.append(truth_state[k])
            matched_h.append(N)
        if not targets:
            continue

        # 一次把該 TLE 外推到所有匹配時刻
        try:
            prop = propagate_tle(tle["line1"], tle["line2"], sat_name,
                                 pd.Series(targets), ts)
        except Exception:
            continue

        for i, t_tgt in enumerate(targets):
            tru = matched_state[i]
            row = prop.iloc[i]
            dr = np.array([row["r_x"]-tru[0], row["r_y"]-tru[1], row["r_z"]-tru[2]])
            pos_err = float(np.linalg.norm(dr))
            R, T, N_ = _rtn_basis(*[np.array([x]) for x in
                                   [tru[0],tru[1],tru[2],tru[3],tru[4],tru[5]]])
            t_tgt_ns = t_tgt.value
            contaminated = bool(np.any((e_ns < burns) & (burns <= t_tgt_ns))) \
                           if burns.size else False
            out.append({
                "sat_name":     sat_name,
                "tle_epoch":    e,
                "t_target":     t_tgt,
                "horizon_days": matched_h[i],
                "age_days":     round((t_tgt - e).total_seconds()/86400.0, 3),
                "pos_err_km":   round(pos_err, 4),
                "dr_r_km":      round(float((dr*R[0]).sum()), 4),
                "dr_t_km":      round(float((dr*T[0]).sum()), 4),
                "dr_n_km":      round(float((dr*N_[0]).sum()), 4),
                "maneuver_contaminated": contaminated,
            })
    return pd.DataFrame(out)


def frozen_summary(resid: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for h, g in resid.groupby("horizon_days"):
        rows.append({
            "subset":       label,
            "horizon_days": int(h),
            "n":            len(g),
            "pos_med_km":   round(float(g["pos_err_km"].median()), 3),
            "pos_p95_km":   round(float(g["pos_err_km"].quantile(0.95)), 3),
            "rms_t_km":     round(float(np.sqrt((g["dr_t_km"]**2).mean())), 3),
        })
    return pd.DataFrame(rows).sort_values("horizon_days").reset_index(drop=True)


# ── Part B：斷點 spot-check ──────────────────────────────────────────────────

def gap_spotcheck_for_sat(sat_name, tle_df, file_tbl, ts,
                          gap_min_d, gap_max_d, maneuver_thr, net_thr) -> dict | None:
    """偵測最大斷點，外推斷點前 TLE 至斷點後首筆真值，量 ~7 天誤差 + 機動標記。"""
    if len(file_tbl) < 2 or tle_df.empty:
        return None
    e = file_tbl["epoch"].to_numpy()
    gaps = np.diff(e).astype("timedelta64[s]").astype(np.int64) / 86400.0
    gi = int(np.argmax(gaps))
    gap_d = float(gaps[gi])
    if not (gap_min_d <= gap_d <= gap_max_d):
        return None                                   # 無符合條件的斷點

    before = file_tbl.iloc[gi]                        # 斷點前最後一筆
    after  = file_tbl.iloc[gi + 1]                    # 斷點後第一筆（近真值）
    t_after = pd.Timestamp(after["epoch"])

    # 斷點兩側各自「檔內 8h 間距」的平均半長軸階躍，捕捉「來回機動 / 小機動」
    # ——這類衛星淨 Δmean_a 可能接近 0，但斷點前後仍在活躍機動，極可能斷點期間也機動。
    # 關鍵：**不可**跨斷點算階躍（跨斷點含 ~7 天自然阻力衰減，會誤判所有衛星）；
    # 只在斷點前側 (gi-3..gi) 與後側 (gi+1..gi+4) 各自算相鄰檔差（8h 間距、阻力可忽略）。
    pre_a  = file_tbl.iloc[max(0, gi - 3):gi + 1]["mean_a"].to_numpy()
    post_a = file_tbl.iloc[gi + 1:min(len(file_tbl), gi + 5)]["mean_a"].to_numpy()
    step_pre  = float(np.abs(np.diff(pre_a)).max())  if len(pre_a)  >= 2 else 0.0
    step_post = float(np.abs(np.diff(post_a)).max()) if len(post_a) >= 2 else 0.0
    local_step = max(step_pre, step_post)

    # 斷點前最新 TLE（epoch ≤ before.epoch）
    ep = pd.to_datetime(tle_df["epoch_utc"], utc=True)
    pre = tle_df[ep <= pd.Timestamp(before["epoch"])]
    if pre.empty:
        return None
    tle = pre.iloc[-1]
    e_tle = pd.Timestamp(tle["epoch_utc"])
    e_tle = e_tle.tz_localize("UTC") if e_tle.tzinfo is None else e_tle.tz_convert("UTC")

    try:
        prop = propagate_tle(tle["line1"], tle["line2"], sat_name,
                             pd.Series([t_after]), ts)
    except Exception:
        return None
    row = prop.iloc[0]
    tru = after[["r_x","r_y","r_z","v_x","v_y","v_z"]].to_numpy(float)
    dr = np.array([row["r_x"]-tru[0], row["r_y"]-tru[1], row["r_z"]-tru[2]])
    pos_err = float(np.linalg.norm(dr))

    d_mean_a = float(after["mean_a"] - before["mean_a"])
    # 判機動：跨斷點淨階躍超「阻力感知門檻」net_thr（含 ~7 天阻力衰減，門檻須較大）
    #        或 斷點兩側 8h 局部階躍超 maneuver_thr（阻力可忽略，門檻可較小）
    maneuvered = (abs(d_mean_a) >= net_thr) or (local_step >= maneuver_thr)

    return {
        "sat_name":       sat_name,
        "gap_days":       round(gap_d, 2),
        "gap_start":      pd.Timestamp(before["epoch"]),
        "gap_end":        t_after,
        "tle_epoch":      e_tle,
        "horizon_days":   round((t_after - e_tle).total_seconds()/86400.0, 2),
        "pos_err_km":     round(pos_err, 3),
        "delta_mean_a_km": round(d_mean_a, 4),
        "local_step_km":  round(local_step, 4),
        "maneuvered":     maneuvered,
    }


# ── 共用：載入 TLE ────────────────────────────────────────────────────────────

def load_tle_pool(db, data_root, sat_entries):
    norad_to_window = {}
    for norad_id, _, file_tbl in sat_entries:
        norad_to_window[norad_id] = (file_tbl["epoch"].min() - pd.Timedelta(days=3),
                                     file_tbl["epoch"].max())
    con = duckdb.connect(db, read_only=True)
    pool = query_tles_in_range(con, norad_to_window, pre_window_days=3.0)
    con.close()
    return pool


def main() -> None:
    ap = argparse.ArgumentParser(description="研究3：TLE 凍結曲線 + 斷點 spot-check")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--sat-list", default=None,
                    help="檔案路徑，每行一個 MEME 衛星名，只處理清單內衛星")
    ap.add_argument("--part", choices=["A", "B", "both"], default="both")
    ap.add_argument("--tle-stride", type=int, default=3,
                    help="Part A 每隔幾筆 TLE 取一筆（控制計算量），預設 3")
    ap.add_argument("--tol-h", type=float, default=6.0, help="近真值匹配容差（小時）")
    ap.add_argument("--maneuver-thr", type=float, default=0.2,
                    help="8h 相鄰檔平均半長軸階躍判定機動的門檻（km；阻力可忽略）")
    ap.add_argument("--gap-net-thr", type=float, default=0.6,
                    help="跨斷點淨 Δmean_a 判定機動的門檻（km；須大於 ~7 天阻力衰減量）")
    ap.add_argument("--gap-min-d", type=float, default=4.0)
    ap.add_argument("--gap-max-d", type=float, default=8.0)
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    data_root = args.data_root
    registry_csv = Path(args.registry) if args.registry else data_root / "url_registry.csv"
    out_dir = Path(args.out_dir) if args.out_dir else data_root / "study3"
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = load_registry(registry_csv)
    name_to_norad = {v: k for k, v in reg["sat_name"].items()}

    raw_dir = data_root / "raw"
    sat_dirs = sorted([p for p in raw_dir.iterdir() if p.is_dir()])
    if args.sat_list:
        wanted = {ln.strip() for ln in Path(args.sat_list).read_text().splitlines() if ln.strip()}
        sat_dirs = [p for p in sat_dirs if p.name in wanted]
        log.info("依清單 %s 過濾 → %d 顆", args.sat_list, len(sat_dirs))
    if args.max_sats:
        sat_dirs = sat_dirs[: args.max_sats]
    log.info("待處理衛星目錄：%d（解析檔案平均半長軸中…）", len(sat_dirs))

    ts = skyfield_load.timescale()
    sat_entries = []
    for d in sat_dirs:
        norad_id = name_to_norad.get(d.name)
        if norad_id is None:
            continue
        files = find_all_ephemeris_files(d)
        tbl = build_file_table(files, d.name)
        if tbl.empty:
            continue
        sat_entries.append((int(norad_id), d.name, tbl))
    log.info("有效衛星：%d，批次查詢 TLE…", len(sat_entries))

    tle_pool = load_tle_pool(args.db, data_root, sat_entries)
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    horizons_d = [1, 2, 3, 4, 5, 6, 7]

    # ── Part A ────────────────────────────────────────────────────────────────
    if args.part in ("A", "both"):
        all_frozen = []
        for norad_id, sat_name, tbl in sat_entries:
            tle_df = tle_pool.get(norad_id)
            if tle_df is None or tle_df.empty:
                continue
            tle_df = tle_df.iloc[::args.tle_stride].reset_index(drop=True)
            burns = maneuver_burn_times(tbl, args.maneuver_thr)
            r = frozen_curve_for_sat(sat_name, tle_df, tbl, ts,
                                     horizons_d, args.tol_h, burns)
            if not r.empty:
                all_frozen.append(r)
                log.info("  [A][%s] n=%d  clean=%d",
                         sat_name, len(r), int((~r["maneuver_contaminated"]).sum()))
        if all_frozen:
            fro = pd.concat(all_frozen, ignore_index=True)
            fro.to_csv(out_dir / f"study3_frozen_curve_{date_tag}.csv",
                       index=False, encoding="utf-8-sig")
            clean = fro[~fro["maneuver_contaminated"]]
            summ = pd.concat([frozen_summary(fro, "all"),
                              frozen_summary(clean, "clean")], ignore_index=True)
            summ.to_csv(out_dir / f"study3_frozen_summary_{date_tag}.csv",
                        index=False, encoding="utf-8-sig")
            print("\n" + "=" * 66)
            print(f"研究3 Part A：TLE 凍結外推曲線（{len(fro)} 樣本 / "
                  f"{fro['sat_name'].nunique()} 顆；下表為濾除機動後）")
            print("=" * 66)
            print(f"  {'horizon':>7}  {'n':>6}  {'P50(km)':>9}  {'P95(km)':>9}  {'T-RMS':>8}")
            for _, r in frozen_summary(clean, "clean").iterrows():
                print(f"  {r['horizon_days']:>5} 天  {r['n']:>6}  {r['pos_med_km']:>9.2f}  "
                      f"{r['pos_p95_km']:>9.2f}  {r['rms_t_km']:>8.2f}")
            if not args.no_plot:
                _plot_frozen(fro, out_dir / "plots", date_tag)
        else:
            log.warning("Part A 無結果")

    # ── Part B ────────────────────────────────────────────────────────────────
    if args.part in ("B", "both"):
        rows = []
        for norad_id, sat_name, tbl in sat_entries:
            tle_df = tle_pool.get(norad_id)
            if tle_df is None or tle_df.empty:
                continue
            r = gap_spotcheck_for_sat(sat_name, tle_df, tbl, ts,
                                      args.gap_min_d, args.gap_max_d,
                                      args.maneuver_thr, args.gap_net_thr)
            if r is not None:
                rows.append(r)
        if rows:
            gap = pd.DataFrame(rows)
            gap.to_csv(out_dir / f"study3_gap_spotcheck_{date_tag}.csv",
                       index=False, encoding="utf-8-sig")
            clean = gap[~gap["maneuvered"]]
            print("\n" + "=" * 66)
            print(f"研究3 Part B：斷點 spot-check（{len(gap)} 顆有符合斷點；"
                  f"平均斷點 {gap['gap_days'].mean():.1f} 天）")
            print(f"  斷點期間機動衛星：{int(gap['maneuvered'].sum())} / {len(gap)}")
            print("=" * 66)
            print(f"  {'子集':<14} {'n':>5}  {'horizon天':>8}  {'P50誤差km':>10}  {'P95誤差km':>10}")
            for label, sub in [("全部", gap), ("非機動(純外推)", clean),
                               ("機動衛星", gap[gap["maneuvered"]])]:
                if len(sub):
                    print(f"  {label:<14} {len(sub):>5}  {sub['horizon_days'].mean():>8.2f}  "
                          f"{sub['pos_err_km'].median():>10.2f}  "
                          f"{sub['pos_err_km'].quantile(0.95):>10.2f}")
        else:
            log.warning("Part B 無符合斷點的衛星（可調 --gap-min-d/--gap-max-d）")

    log.info("完成。輸出 → %s", out_dir)


def _plot_frozen(fro, plots_dir, date_tag):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plots_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for label, sub, color in [("全部", fro, "lightsteelblue"),
                              ("濾除機動", fro[~fro["maneuver_contaminated"]], "tomato")]:
        med = sub.groupby("horizon_days")["pos_err_km"].median()
        ax.plot(med.index, med.values, marker="o", lw=2, label=f"{label}中位數", color=color)
    ax.set_xlabel("TLE 凍結外推時程 (天)")
    ax.set_ylabel("TLE 位置誤差 (km)  [vs MEME 近真值]")
    ax.set_title(f"研究3A：TLE 凍結外推退化曲線 ({date_tag})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / f"study3_frozen_curve_{date_tag}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
