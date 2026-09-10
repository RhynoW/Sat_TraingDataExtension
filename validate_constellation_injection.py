#!/usr/bin/env python3
"""
validate_constellation_injection.py — 注入式合成真值測試（進階版）：
非 Starlink 星系的「零異常」，在三個維度上分別有多敏感？

背景：`constellation_anomaly.py` 對 OneWeb／千帆等非 Starlink 星系做批量機動掃描，
目前回報「零異常」，但沒有真值可核對這是「真的安靜」還是「系統對非 Starlink 域本來就不敏感」
（StoryMap 案例十二⑤）。2026-09-10 初版只測了「單顆衛星逐步 |Δa|」一項指標；
本進階版依使用者要求，一次補齊三個方向：

  A. 單顆衛星 Δa 偵測（Monte Carlo 化）：原本每顆衛星只在中段注入一次，
     改成多次隨機注入時刻的重複試驗，用 Wilson 95% CI 取代單一點估計
     （與案例十二②再入驗證同一方法論）。
  B. 軌道面一致性（Δi）注入：`analyze()` 的①用 Δi std 判斷軌道面是否協同異常。
     但軌道面分組（`assign_planes`）本身用 0.5° 傾角間隙分殼層——
     若注入的 Δi 夠大，衛星可能被分群邏輯直接「甩出」原本的軌道面，
     反而完全不會被 Δi std 機制看到（一個違反直覺的陷阱，見下方發現）。
  C. 陣型相位（u=argp+ma）注入：`analyze()` 的③用相位殘差判斷陣型是否跑掉。

  D. 批量機動端到端驗證（最重要的新增）：A/B/C 都只測「單一注入訊號是否夠大」，
     但案例六/②真正的「批量機動」判定是「同一天有多少顆衛星『同時』觸發，
     是否超過 K≈mean+3σ 的『相對』門檻」——這一層完全沒被前一版測過。
     本測試把同一個真實機動量級「同時」注入 N 顆真實衛星（模擬一次真實批量事件），
     重跑完整 `analyze()`，直接檢查那一天會不會被標記為 flag_batch=True，
     並同時報「K 門檻本身有沒有被注入事件自己的量級污染拉高」。

方法論說明（老實話）：所有注入都是「真實 TLE 雜訊背景 + 已知合成機動量級」的疊加，
不是真實發生過的事件；批量測試更是刻意讓多顆衛星「同時」變動，
比真實批量部署（各衛星量級/時間點會有分散度）更理想化，測出的偵測率可能偏樂觀，
用途是刻劃系統的「敏感度地圖」與「盲點」，不是宣稱這就是真實批量事件的偵測率。

用法：
  python validate_constellation_injection.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from constellation_anomaly import (
    CONSTELLATIONS, DA_MANEUVER_KM, SHELL_GAP_DEG, analyze, load_constellation,
)

DB_PATH = "space_db.duckdb"
OUT_CSV_A = "data/benchmark/constellation_injection_persat_20260910.csv"
OUT_CSV_B = "data/benchmark/constellation_injection_plane_20260910.csv"
OUT_CSV_C = "data/benchmark/constellation_injection_formation_20260910.csv"
OUT_CSV_D = "data/benchmark/constellation_injection_batch_20260910.csv"
CONSTELLATIONS_TO_TEST = ["OneWeb", "Qianfan"]
WINDOW_DAYS = 60
RNG_SEED = 42

MAG_DA_KM = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
MAG_DI_DEG = [0.05, 0.1, 0.2, 0.3, 0.5, 1.0]   # 跨越 SHELL_GAP_DEG=0.5 門檻，觀察「甩出殼層」現象
MAG_PHASE_DEG = [1.0, 2.0, 5.0, 10.0, 20.0, 45.0]
N_TRIALS = 30


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z ** 2 / n
    center = p + z ** 2 / (2 * n)
    half = z * (p * (1 - p) / n + z ** 2 / (4 * n ** 2)) ** 0.5
    return (center - half) / denom, (center + half) / denom


def load_window(cname: str) -> pd.DataFrame:
    pat = CONSTELLATIONS[cname]
    d1 = pd.Timestamp("2026-09-10")
    d0 = d1 - pd.Timedelta(days=WINDOW_DAYS)
    return load_constellation(DB_PATH, pat, d0, d1)


# ══ A. 單顆衛星 Δa（Monte Carlo）══════════════════════════════════════════════

def test_persat_da(df: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    counts = df.groupby("norad_id").size()
    eligible = counts[counts >= 15].index.to_numpy()
    rows = []
    for mag in MAG_DA_KM:
        n_detect = 0
        for _ in range(N_TRIALS):
            nid = rng.choice(eligible)
            sub = df[df["norad_id"] == nid][["epoch", "sma_km"]].sort_values("epoch").reset_index(drop=True)
            if len(sub) < 6:
                continue
            idx = int(rng.integers(2, len(sub) - 1))   # 隨機注入時刻，非固定中點
            sma = sub["sma_km"].to_numpy(float).copy()
            sma[idx:] += mag
            da = np.diff(sma)
            if abs(da[idx - 1]) > DA_MANEUVER_KM:
                n_detect += 1
        lo, hi = wilson_ci(n_detect, N_TRIALS)
        rows.append({"inject_mag_km": mag, "n_trials": N_TRIALS, "n_detected": n_detect,
                     "detect_rate": n_detect / N_TRIALS, "ci_lo": lo, "ci_hi": hi})
    return rows


# ══ B. 軌道面 Δi 注入══════════════════════════════════════════════════════════

def test_plane_di(df: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    base = analyze(df)
    snap0 = base["snap"]
    plane_counts = snap0.groupby("plane").size()
    eligible_planes = plane_counts[plane_counts >= 3].index.to_numpy()
    rows = []
    for mag in MAG_DI_DEG:
        n_detect, n_escaped = 0, 0
        n_valid = 0
        for _ in range(N_TRIALS):
            if len(eligible_planes) == 0:
                break
            pid = rng.choice(eligible_planes)
            cand = snap0[snap0["plane"] == pid].index.to_numpy()
            if len(cand) == 0:
                continue
            nid = int(rng.choice(cand))
            d = df.copy()
            m = d["norad_id"] == nid
            last_idx = d[m].index[-1]
            d.loc[last_idx, "inclination_deg"] = d.loc[last_idx, "inclination_deg"] + mag
            R = analyze(d)
            snap1 = R["snap"]
            if nid not in snap1.index:
                continue
            n_valid += 1
            plane_after = snap1.loc[nid, "plane"]
            if plane_after != pid:
                n_escaped += 1   # 被分群邏輯甩出原本的軌道面，逃過偵測
                continue
            pl = R["planes"]
            hit = pl.loc[pl["plane"] == pid, "flag_plane_incoherent"]
            if len(hit) and bool(hit.iloc[0]):
                n_detect += 1
        if n_valid == 0:
            continue
        lo, hi = wilson_ci(n_detect, n_valid)
        rows.append({"inject_mag_deg": mag, "n_trials": n_valid, "n_detected": n_detect,
                     "n_escaped_plane": n_escaped, "detect_rate": n_detect / n_valid,
                     "escape_rate": n_escaped / n_valid, "ci_lo": lo, "ci_hi": hi})
    return rows


# ══ C. 陣型相位注入════════════════════════════════════════════════════════════

def test_formation_phase(df: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    base = analyze(df)
    snap0 = base["snap"]
    form0 = base["formation"].set_index("plane")["n_outliers"]
    plane_counts = snap0.groupby("plane").size()
    eligible_planes = plane_counts[plane_counts >= 4].index.to_numpy()
    rows = []
    for mag in MAG_PHASE_DEG:
        n_detect, n_valid = 0, 0
        for _ in range(N_TRIALS):
            if len(eligible_planes) == 0:
                break
            pid = rng.choice(eligible_planes)
            if pid not in form0.index:
                continue
            cand = snap0[snap0["plane"] == pid].index.to_numpy()
            if len(cand) == 0:
                continue
            nid = int(rng.choice(cand))
            d = df.copy()
            m = d["norad_id"] == nid
            last_idx = d[m].index[-1]
            d.loc[last_idx, "mean_anomaly_deg"] = (d.loc[last_idx, "mean_anomaly_deg"] + mag) % 360.0
            R = analyze(d)
            form1 = R["formation"].set_index("plane")["n_outliers"]
            if pid not in form1.index:
                continue
            n_valid += 1
            if form1.loc[pid] > form0.loc[pid]:
                n_detect += 1
        if n_valid == 0:
            continue
        lo, hi = wilson_ci(n_detect, n_valid)
        rows.append({"inject_mag_deg": mag, "n_trials": n_valid, "n_detected": n_detect,
                     "detect_rate": n_detect / n_valid, "ci_lo": lo, "ci_hi": hi})
    return rows


# ══ D. 批量機動端到端驗證══════════════════════════════════════════════════════

def test_batch_endtoend(df: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    base = analyze(df)
    K_base = base["K"]
    counts = df.groupby("norad_id").size()
    eligible = counts[counts >= 15].index.to_numpy()

    # 選一天：全體衛星中，「當天有 TLE 快照」的衛星數最多的一天，讓注入的衛星盡量真的落在同一天。
    d0 = df.copy()
    d0["day"] = d0["epoch"].dt.date
    day_counts = d0.groupby("day")["norad_id"].nunique().sort_values(ascending=False)
    test_day = day_counts.index[len(day_counts) // 3]   # 避開最邊緣的天，取一個資料密度中段的日子

    mag = 5.0   # 已由 A 測試證實：≥3km 在真實雜訊背景下幾乎必被單顆逐步邏輯抓到
    n_inject_values = sorted(set([2, max(2, int(np.ceil(K_base)) - 1), int(np.ceil(K_base)) + 1,
                                   int(np.ceil(K_base)) + 3, int(np.ceil(K_base)) * 2]))
    rows = []
    for n_inject in n_inject_values:
        n_trials_here = 10
        n_flagged = 0
        n_maneuvering_list, k_incl_list, k_excl_list = [], [], []
        for _ in range(n_trials_here):
            picked = rng.choice(eligible, size=min(n_inject, len(eligible)), replace=False)
            d = df.copy()
            for nid in picked:
                m = d["norad_id"] == nid
                sub_idx = d[m].sort_values("epoch").index
                on_or_after = d.loc[sub_idx, "epoch"].dt.date >= test_day
                if not on_or_after.any():
                    continue
                first_hit = sub_idx[on_or_after][0]
                pos = list(sub_idx).index(first_hit)
                inject_idx = sub_idx[pos:]
                d.loc[inject_idx, "sma_km"] = d.loc[inject_idx, "sma_km"] + mag
            R = analyze(d)
            b = R["batch"]
            row = b[b["day"] == test_day]
            n_man = int(row["n_maneuvering"].iloc[0]) if len(row) else 0
            flagged = bool(row["flag_batch"].iloc[0]) if len(row) else False
            k_incl = R["K"]
            others = b[b["day"] != test_day]["n_maneuvering"]
            k_excl = float(others.mean() + 3 * others.std(ddof=0)) if len(others) > 1 else k_incl
            n_maneuvering_list.append(n_man)
            k_incl_list.append(k_incl)
            k_excl_list.append(k_excl)
            if flagged:
                n_flagged += 1
        rows.append({
            "n_injected": n_inject, "test_day": str(test_day), "inject_mag_km": mag,
            "n_trials": n_trials_here, "n_flagged_batch": n_flagged,
            "flag_rate": n_flagged / n_trials_here,
            "avg_n_maneuvering_that_day": float(np.mean(n_maneuvering_list)),
            "K_baseline_before_injection": K_base,
            "avg_K_including_test_day": float(np.mean(k_incl_list)),
            "avg_K_excluding_test_day": float(np.mean(k_excl_list)),
        })
    return rows


def main() -> None:
    all_a, all_b, all_c, all_d = [], [], [], []
    for cname in CONSTELLATIONS_TO_TEST:
        df = load_window(cname)
        if df.empty or df["norad_id"].nunique() < 10:
            print(f"{cname}: 資料不足，略過")
            continue
        print(f"{cname}: {df['norad_id'].nunique()} 顆衛星、{len(df):,} 筆 TLE，窗 {WINDOW_DAYS} 天")
        rng = np.random.default_rng(RNG_SEED)

        rows_a = test_persat_da(df, rng)
        for r in rows_a:
            r["constellation"] = cname
        all_a += rows_a
        print(f"  A. 單顆Δa完成：{len(rows_a)} 個量級")

        rows_b = test_plane_di(df, rng)
        for r in rows_b:
            r["constellation"] = cname
        all_b += rows_b
        print(f"  B. 軌道面Δi完成：{len(rows_b)} 個量級")

        rows_c = test_formation_phase(df, rng)
        for r in rows_c:
            r["constellation"] = cname
        all_c += rows_c
        print(f"  C. 陣型相位完成：{len(rows_c)} 個量級")

        rows_d = test_batch_endtoend(df, rng)
        for r in rows_d:
            r["constellation"] = cname
        all_d += rows_d
        print(f"  D. 批量端到端完成：{len(rows_d)} 個注入顆數設定")

    pd.DataFrame(all_a).to_csv(OUT_CSV_A, index=False)
    pd.DataFrame(all_b).to_csv(OUT_CSV_B, index=False)
    pd.DataFrame(all_c).to_csv(OUT_CSV_C, index=False)
    pd.DataFrame(all_d).to_csv(OUT_CSV_D, index=False)
    print(f"\n輸出 →\n  {OUT_CSV_A}\n  {OUT_CSV_B}\n  {OUT_CSV_C}\n  {OUT_CSV_D}")


if __name__ == "__main__":
    main()
