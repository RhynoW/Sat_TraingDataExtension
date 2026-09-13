#!/usr/bin/env python3
"""phase_residual_broad_scan.py — 普遍掃描全部 LEO 衛星最近 15 天 TLE 資料，
尋找「相位殘差異常但半長軸(sma)未同步異常」之候選新案例（即結構性看不到 sma
變化的「相位調整」機動候選，比照 STARLINK-5367 案例之發現方式）。

作法（向量化、一次性拉取，避免 27,549 顆衛星逐一連 DB）：
1. 一次 SQL 拉出全部 LEO（sma 6578-8378km，約 200-2000km 高度）近 20 天
   （15 天分析窗＋5 天緩衝供第一筆殘差計算）之 TLE 列。
2. 依衛星分組、3 小時最小間距稀釋（同 tasa14_compare.load_a 慣例）。
3. 逐組計算相位殘差（同 phase_residual_detector.phase_residual_km 邏輯，
   純 numpy 向量化）與局部穩健 z 分數。
4. 同時計算同視窗內 sma 之局部穩健 z 分數。
5. 候選＝相位殘差 |z|>=PHASE_K 且對應時刻 sma |z|<SMA_K（結構性看不到）。

輸出：data/benchmark/phase_residual_broad_scan_candidates_20260913.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DB = "space_db.duckdb"
LEO_SMA_MIN, LEO_SMA_MAX = 6578.0, 8378.0     # ~200-2000km 高度
WINDOW_DAYS = 15
BUFFER_DAYS = 5
MIN_GAP_SEC = 3.0 * 3600
MIN_PTS = 8
PHASE_K = 6.0
SMA_K = 4.0
GAP_MAX_DAYS = 2.0    # 超過此間隔，n外推誤差本身可能已大於真實訊號
PERSIST_K = 6.0       # 下一筆若仍達此門檻，判定為單點TLE雜訊而非真實事件


def fetch_bulk():
    con = duckdb.connect(DB, read_only=True)
    max_t = pd.Timestamp(con.execute("SELECT MAX(epoch_utc) FROM raw_tle_archive").fetchone()[0], tz="UTC")
    since = max_t - pd.Timedelta(days=WINDOW_DAYS + BUFFER_DAYS)
    cutoff = max_t - pd.Timedelta(days=WINDOW_DAYS)
    print(f"資料庫最新 epoch: {max_t}；分析窗: {cutoff} ~ {max_t}", flush=True)
    df = con.execute(
        "SELECT norad_id, object_name, epoch_utc, sma_km, mean_anomaly_deg, argp_deg, mean_motion "
        "FROM raw_tle_archive WHERE epoch_utc >= ? AND sma_km BETWEEN ? AND ? "
        "AND mean_anomaly_deg IS NOT NULL AND argp_deg IS NOT NULL AND mean_motion IS NOT NULL "
        "ORDER BY norad_id, epoch_utc",
        [since, LEO_SMA_MIN, LEO_SMA_MAX]).fetchdf()
    con.close()
    # 緯度幅角 u=argp+M：近圓軌道（e→0，多數 Starlink/Kuiper/OneWeb）下，M 與
    # argp 個別數值退化、易因定軌雜訊劇烈跳動，唯有兩者之和才穩定有物理意義
    # （2026-09-13 廣泛掃描時發現，詳見 phase_residual_detector.py 說明）。
    df["mean_anomaly_deg"] = (df["mean_anomaly_deg"] + df["argp_deg"]) % 360.0
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    return df, cutoff, max_t


def thin_3h(t: np.ndarray) -> np.ndarray:
    keep = [0]
    for i in range(1, len(t)):
        if t[i] - t[keep[-1]] >= MIN_GAP_SEC:
            keep.append(i)
    return np.array(keep)


def to_epoch_sec(s: pd.Series) -> np.ndarray:
    """轉為 UNIX 秒（float）。duckdb fetchdf() 回傳之 datetime 解析度可能是
    us 而非 ns，直接 .astype('int64')/1e9 會因單位錯誤縮小 1000 倍，
    故先正規化為 datetime64[s] 再轉數值。"""
    return s.to_numpy().astype("datetime64[s]").astype("float64")


def robust_z(x: np.ndarray) -> np.ndarray:
    med = np.nanmedian(x)
    mad = 1.4826 * np.nanmedian(np.abs(x - med))
    if not np.isfinite(mad) or mad == 0:
        return np.zeros_like(x)
    return (x - med) / mad


def analyze_one(g: pd.DataFrame, cutoff: pd.Timestamp):
    g = g.sort_values("epoch_utc")
    tsec = to_epoch_sec(g["epoch_utc"])
    idx = thin_3h(tsec)
    if len(idx) < MIN_PTS:
        return []
    g = g.iloc[idx].reset_index(drop=True)
    tsec = to_epoch_sec(g["epoch_utc"])
    a = g["sma_km"].to_numpy(float)
    M = g["mean_anomaly_deg"].to_numpy(float)
    n = g["mean_motion"].to_numpy(float)

    def pred_resid(i, lag):
        """以第 i-lag 筆為基準線外推至第 i 筆之相位殘差（km）。lag=1 為相鄰
        基準；lag=2 為跳過中間一筆的獨立基準——用於偵測「單筆 TLE 本身壞掉」
        （壞的那一筆若被跳過，殘差應消失）。"""
        j = i - lag
        dt_days = (tsec[i] - tsec[j]) / 86400.0
        pred_orbits = n[j] * dt_days
        pred_M = (M[j] + pred_orbits * 360.0) % 360.0
        diff_deg = (M[i] - pred_M + 180.0) % 360.0 - 180.0
        return np.radians(diff_deg) * a[i], dt_days

    n_pts = len(a)
    resid = np.full(n_pts, np.nan)
    resid2 = np.full(n_pts, np.nan)
    gap_days = np.full(n_pts, np.nan)
    gap2_days = np.full(n_pts, np.nan)
    for i in range(1, n_pts):
        resid[i], gap_days[i] = pred_resid(i, 1)
    for i in range(2, n_pts):
        resid2[i], gap2_days[i] = pred_resid(i, 2)

    z_phase = robust_z(resid)
    z_phase2 = robust_z(resid2)
    da = np.diff(a, prepend=a[0])
    z_sma = robust_z(da)

    out = []
    for i in range(n_pts):
        t_i = g["epoch_utc"].iloc[i]
        if t_i < cutoff:
            continue
        if not np.isfinite(z_phase[i]) or not np.isfinite(z_phase2[i]):
            continue
        # 大時間間隔＋衰減/攝動會使外推本身失真，非機動訊號，濾除
        if gap_days[i] > GAP_MAX_DAYS or gap2_days[i] > 2 * GAP_MAX_DAYS:
            continue
        # 持續性檢查：真正的相位調整事後應「固定」（下一筆以此為基準之殘差應
        # 恢復正常）；若下一筆殘差仍同樣異常，多半是單筆 TLE 資料本身有誤，
        # 而非真實機動——過濾掉單點雜訊，不誤報。
        if i + 1 < n_pts and np.isfinite(z_phase[i + 1]) and abs(z_phase[i + 1]) >= PERSIST_K:
            continue
        # 雙基準線一致性檢查：若「跳過上一筆、改用上上筆外推」後異常就消失，
        # 代表問題出在上一筆 TLE 本身壞掉（非真實事件）——要求兩種基準線
        # 皆同號、且皆達顯著門檻，才視為真正候選。
        if abs(z_phase2[i]) < PHASE_K or np.sign(resid[i]) != np.sign(resid2[i]):
            continue
        if abs(z_phase[i]) >= PHASE_K and abs(z_sma[i]) < SMA_K:
            out.append(dict(
                norad_id=int(g["norad_id"].iloc[0]), name=g["object_name"].iloc[0],
                epoch_utc=t_i, phase_resid_km=resid[i], z_phase=z_phase[i],
                da_km=da[i], z_sma=z_sma[i], sma_km=a[i], gap_days=gap_days[i],
            ))
    return out


def main():
    t0 = time.time()
    df, cutoff, max_t = fetch_bulk()
    print(f"共 {len(df):,} 列，{df['norad_id'].nunique():,} 顆衛星（{time.time()-t0:.0f}s）", flush=True)

    candidates = []
    n_done = 0
    n_err = 0
    seen_err_types = set()
    for nid, g in df.groupby("norad_id"):
        n_done += 1
        if n_done % 3000 == 0:
            print(f"  ...已處理 {n_done:,} 顆（{time.time()-t0:.0f}s），目前候選 {len(candidates)} 筆", flush=True)
        try:
            candidates.extend(analyze_one(g, cutoff))
        except Exception as e:
            n_err += 1
            if type(e) not in seen_err_types:
                seen_err_types.add(type(e))
                print(f"  [WARN] {nid} 例外（首次出現此類型，將繼續但不再重複列印）: {type(e).__name__}: {e}", flush=True)
            continue
    if n_err:
        print(f"共 {n_err} 顆衛星計算時發生例外並被跳過（見上方 WARN）", flush=True)

    out = pd.DataFrame(candidates)
    if len(out):
        out = out.sort_values("z_phase", key=lambda s: s.abs(), ascending=False)
    dst = Path("data/benchmark/phase_residual_broad_scan_candidates_20260913.csv")
    out.to_csv(dst, index=False, encoding="utf-8-sig")
    print(f"\n掃描完成：{n_done:,} 顆衛星，耗時 {time.time()-t0:.0f}s", flush=True)
    print(f"候選（相位殘差異常但sma未同步異常）：{len(out)} 筆 → {dst}", flush=True)
    if len(out):
        print(out.head(30).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
