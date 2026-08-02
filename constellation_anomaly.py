#!/usr/bin/env python3
"""
constellation_anomaly.py — 星系級軌道機動異常分析（契約表 8 情境②三項）
=====================================================================
對整個星系（Starlink/OneWeb/Kuiper/Qianfan/Yaogan…）做多星協同偏差偵測，對應事件分類：
  批量部署 / 星系重組 / 戰術機動。三項分析：

  ① 軌道面一致性檢測：同一 RAAN 面內衛星的 Δi（傾角變化）標準差。
     一個平面理應共面演化；某些衛星 Δi 偏離 → 協同/異常傾角機動（星系重組跡象）。
  ② 批量機動識別：同一日內機動的衛星數 > K → 批量事件（部署升軌/整體重定相）。
  ③ 陣型誤差分析：同一 RAAN 面內衛星的緯度幅角 u=(ω+M) 相對「均勻間隔」的偏離。
     偏離過大 → 相位保持失效或戰術性移相。

用法：
  python constellation_anomaly.py --constellation Starlink --days 30
  python constellation_anomaly.py --list
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

# 已知星系（僅有效載荷）→ object_name 比對樣式（大寫、含 '0 ' 前綴故用 %…%）
CONSTELLATIONS = {
    "Starlink": "%STARLINK-%", "OneWeb": "%ONEWEB%", "Kuiper": "%KUIPER%",
    "Qianfan": "%QIANFAN%", "Yaogan": "%YAOGAN%", "Flock": "%FLOCK%",
    "Iridium": "%IRIDIUM%", "Globalstar": "%GLOBALSTAR%", "Spire": "%LEMUR%",
    "Orbcomm": "%ORBCOMM%", "Gaofen": "%GAOFEN%", "Hawk": "%HAWK%",
    "Fengyun": "%FENGYUN%", "Tianqi": "%TIANQI%", "Jilin": "%JILIN%",
    "Tianhui": "%TIANHUI%", "SpaceMobile": "%SPACEMOBILE%", "NuSat": "%NUSAT%",
    # Planet Labs 四子星系（Flock 保留為代表；SkySat/Pelican/RapidEye 分列）
    "SkySat": "%SKYSAT%", "Pelican": "%PELICAN%", "RapidEye": "%RAPIDEYE%",
}
DA_MANEUVER_KM = 2.0    # ② 單步 |Δa| 判「顯著」機動門檻（濾例行 station-keeping 抖動）
SHELL_GAP_DEG = 0.5     # 傾角殼層分群間隙
RAAN_BIN_DEG = 5.0      # 殼層內 RAAN 平面分箱寬（~72 面，貼合 Starlink）


def _gap_cluster(x: np.ndarray, gap: float) -> np.ndarray:
    """1D 間隙分群（用於傾角殼層；殼層間有明顯間隙）。回傳等長標籤。"""
    order = np.argsort(x); xs = x[order]
    lab = np.zeros(len(x), int); cur = 0
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] > gap:
            cur += 1
        lab[i] = cur
    out = np.empty(len(x), int); out[order] = lab
    return out


def assign_planes(inc: np.ndarray, raan: np.ndarray) -> np.ndarray:
    """軌道面 = (傾角殼層, RAAN 固定分箱)。大型密集星系無法用間隙分 RAAN，
    故殼層用間隙、殼層內 RAAN 用固定 5° 分箱（≈72 面）為務實代理。回傳字串 plane id。"""
    shell = _gap_cluster(inc, SHELL_GAP_DEG)
    rbin = (np.floor((raan % 360.0) / RAAN_BIN_DEG)).astype(int)
    return np.array([f"S{s}-R{b}" for s, b in zip(shell, rbin)])


def load_constellation(db: str, pattern: str, date0, date1) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    df = con.execute(
        "SELECT norad_id, object_name, epoch_utc, sma_km, inclination_deg, raan_deg, "
        "argp_deg, mean_anomaly_deg FROM raw_tle_archive "
        "WHERE UPPER(object_name) LIKE ? AND sma_km IS NOT NULL "
        "AND epoch_utc BETWEEN ? AND ? ORDER BY norad_id, epoch_utc",
        [pattern, str(date0), str(date1)]).fetchdf()
    con.close()
    if not df.empty:
        df["epoch"] = pd.to_datetime(df["epoch_utc"], utc=True, format="ISO8601")
    return df


def analyze(df: pd.DataFrame, K: int | None = None) -> dict:
    # 每顆首/末快照
    first = df.groupby("norad_id").first()
    last = df.groupby("norad_id").last()
    snap = pd.DataFrame({
        "inc0": first["inclination_deg"], "inc1": last["inclination_deg"],
        "raan": last["raan_deg"], "argp": last["argp_deg"], "ma": last["mean_anomaly_deg"],
        "sma1": last["sma_km"]})
    snap["di"] = snap["inc1"] - snap["inc0"]
    snap["u"] = (snap["argp"] + snap["ma"]) % 360.0
    snap = snap.dropna(subset=["raan", "inc1", "u"])
    snap["plane"] = assign_planes(snap["inc1"].to_numpy(), snap["raan"].to_numpy())

    # ── ① 軌道面一致性（Δi std）──────────────────────────────────────────────
    plane_rows = []
    for pid, g in snap.groupby("plane"):
        if len(g) < 3:
            continue
        plane_rows.append({"plane": pid, "n": len(g),
                           "raan_mean": round(float(g["raan"].mean()), 2),
                           "inc_mean": round(float(g["inc1"].mean()), 3),
                           "di_std_deg": round(float(g["di"].std(ddof=0)), 4),
                           "di_absmax_deg": round(float(g["di"].abs().max()), 4)})
    planes = pd.DataFrame(plane_rows).sort_values("di_std_deg", ascending=False)
    di_thr = float(planes["di_std_deg"].median() + 3 * planes["di_std_deg"].std(ddof=0)) if len(planes) else 0
    planes["flag_plane_incoherent"] = planes["di_std_deg"] > max(di_thr, 0.01)

    # ── ② 批量機動識別（同天機動衛星數 > K）─────────────────────────────────
    d = df.copy()
    d["da"] = d.groupby("norad_id")["sma_km"].diff()
    d["day"] = d["epoch"].dt.date
    man = d[d["da"].abs() > DA_MANEUVER_KM]
    batch = (man.groupby("day")["norad_id"].nunique()
             .rename("n_maneuvering").reset_index().sort_values("n_maneuvering", ascending=False))
    # 批量事件＝同天顯著機動衛星數異常偏高：相對門檻 = mean + 3σ（非固定 K，避開例行機動基線）
    if K is None and len(batch):
        K = float(batch["n_maneuvering"].mean() + 3 * batch["n_maneuvering"].std(ddof=0))
    K = K or 5
    batch["flag_batch"] = batch["n_maneuvering"] > K

    # ── ③ 陣型誤差（同面緯度幅角 u 偏離均勻間隔）──────────────────────────────
    form_rows = []
    for pid, g in snap.groupby("plane"):
        if len(g) < 4:
            continue
        u = np.sort(g["u"].to_numpy())
        N = len(u)
        # 以「觀測到的中位間隔」為期望槽距，計每星到最近均勻槽的相位殘差
        gaps = np.diff(np.r_[u, u[0] + 360.0])
        exp = np.median(gaps)
        # 相對於均勻鋪排的殘差：每顆與其理想位置差（用相位排序後累積偏移）
        ideal = u[0] + exp * np.arange(N)
        resid = ((u - ideal + 180) % 360) - 180
        rstd = float(np.std(resid, ddof=0))
        outliers = int((np.abs(resid) > max(3 * rstd, 2.0)).sum())
        form_rows.append({"plane": pid, "n": N, "slot_deg": round(float(exp), 2),
                          "phase_resid_std_deg": round(rstd, 3), "n_outliers": outliers})
    formation = pd.DataFrame(form_rows).sort_values("phase_resid_std_deg", ascending=False)

    return {"snap": snap, "planes": planes, "batch": batch, "formation": formation, "K": K}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--constellation", default="Starlink")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--K", type=int, default=None, help="批量機動門檻（預設 max(5,1%%星數)）")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("已知星系：", "、".join(CONSTELLATIONS)); return
    pat = CONSTELLATIONS.get(args.constellation)
    if not pat:
        print(f"未知星系 {args.constellation}；--list 看清單"); return

    con = duckdb.connect(args.db, read_only=True)
    mx = con.execute("SELECT MAX(epoch_utc) FROM raw_tle_archive WHERE UPPER(object_name) LIKE ?",
                     [pat]).fetchone()[0]
    con.close()
    date1 = pd.Timestamp(mx); date0 = date1 - timedelta(days=args.days)
    print(f"{'='*66}\n星系級異常分析 — {args.constellation}  窗 {date0.date()}~{date1.date()}\n{'='*66}")
    df = load_constellation(args.db, pat, date0, date1)
    if df.empty or df["norad_id"].nunique() < 5:
        print("資料不足。"); return
    print(f"衛星 {df['norad_id'].nunique()} 顆、TLE {len(df)} 筆")

    R = analyze(df, K=args.K)
    planes, batch, formation = R["planes"], R["batch"], R["formation"]

    print(f"\n① 軌道面一致性（{len(planes)} 個平面，依 Δi std 降冪）")
    print(planes.head(8).to_string(index=False))
    nflag = int(planes["flag_plane_incoherent"].sum())
    print(f"  → 異常平面（Δi std 過高，疑協同傾角機動/重組）：{nflag} 個")

    print(f"\n② 批量機動識別（|Δa|>{DA_MANEUVER_KM}km；相對門檻 K={R['K']:.0f}=mean+3σ）")
    print(batch.head(8).to_string(index=False))
    bd = batch[batch["flag_batch"]]
    print(f"  → 批量事件日（>{R['K']:.0f} 顆同天顯著機動，疑批量部署/重組）：{len(bd)} 天"
          + (f"：{', '.join(str(x) for x in bd['day'].head(6))}" if len(bd) else ""))

    print(f"\n③ 陣型誤差（{len(formation)} 個平面，依相位殘差 std 降冪）")
    print(formation.head(8).to_string(index=False))
    print(f"  → 相位離群衛星總數（疑相位保持失效/移相）：{int(formation['n_outliers'].sum())} 顆")

    out_dir = Path("data/constellation"); out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.constellation}_{date1.date()}"
    planes.to_csv(out_dir / f"planes_{tag}.csv", index=False, encoding="utf-8-sig")
    batch.to_csv(out_dir / f"batch_{tag}.csv", index=False, encoding="utf-8-sig")
    formation.to_csv(out_dir / f"formation_{tag}.csv", index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out_dir}/(planes|batch|formation)_{tag}.csv")


if __name__ == "__main__":
    main()
