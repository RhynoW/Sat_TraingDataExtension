"""satdet.common — 跨模組共用工具（單一事實來源）。

集中曾在多個腳本重複、且各踩過坑的邏輯：
  to_ns()               µs-vs-ns 單位陷阱（raw_tle epoch 會解析成 datetime64[us]）
  latest_file()         「最新時間戳檔案」慣例的唯一實作（含清楚錯誤訊息）
  merge_episodes()      機動轉移 → episode（48h gap 合併、取 max 嚴重度）
  episodes_by_sat()     整張 truth 表 → {衛星: [(times_ns, rank)]}
  fpr_floor_threshold() FPR 預算操作點（floor 保證嚴格 ≤ budget）
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

HOUR_NS = int(3.6e12)
TOL_NS = 24 * HOUR_NS   # episode 配對容差（＝latency 目標）
GAP_NS = 48 * HOUR_NS   # episode 合併間隔
SEV_RANK = {"small": 1, "medium": 2, "large": 3}
RANK_SEV = {v: k for k, v in SEV_RANK.items()}


def to_ns(s) -> np.ndarray:
    """統一轉為 int64 奈秒。

    守住 µs-vs-ns 單位錯誤：pandas 對部分字串格式會解析成 datetime64[us]，
    直接 astype("int64") 會與 [ns] 差 1000×。一律先正規化到 [ns] 再取整數。
    接受字串／datetime Series、list、ndarray。
    """
    ser = s if isinstance(s, pd.Series) else pd.Series(s)
    dt = pd.to_datetime(ser, utc=True, format="ISO8601")
    return (dt.dt.tz_convert(None).astype("datetime64[ns]")
            .astype("int64").to_numpy())


def latest_file(pattern: str) -> str:
    """回傳符合 glob pattern 的最新（字典序最大）檔案路徑。"""
    g = sorted(glob.glob(pattern))
    if not g:
        raise FileNotFoundError(f"找不到符合 {pattern} 的檔案（上游尚未產出？）")
    return g[-1]


def merge_episodes(times_ns, ranks, gap_ns: int = GAP_NS) -> list[tuple[np.ndarray, int]]:
    """單顆衛星：轉移時刻合併為 episode。

    間隔 > gap_ns 斷開；episode 嚴重度＝窗內最大 rank（逐轉移計會低估 recall）。
    輸入自動依時間排序。回傳 [(times_ns_array, rank), ...]。
    """
    times_ns = np.asarray(times_ns)
    ranks = np.asarray(ranks)
    if len(times_ns) == 0:
        return []
    order = np.argsort(times_ns)
    tv, sv = times_ns[order], ranks[order]
    out: list[tuple[np.ndarray, int]] = []
    cur, rk = [tv[0]], sv[0]
    for j in range(1, len(tv)):
        if tv[j] - cur[-1] > gap_ns:
            out.append((np.array(cur), rk))
            cur, rk = [tv[j]], sv[j]
        else:
            cur.append(tv[j])
            rk = max(rk, sv[j])
    out.append((np.array(cur), rk))
    return out


def episodes_by_sat(truth: pd.DataFrame, key: str = "norad_id", t_col: str = "t_to",
                    sev_col: str = "da_severity", gap_ns: int = GAP_NS) -> dict:
    """truth 全表 → {key 值: [(times_ns, rank)]}，僅保留 SEV_RANK 內的嚴重度。"""
    tr = truth[truth[sev_col].isin(SEV_RANK)].copy()
    tr["_ns"] = to_ns(tr[t_col])
    tr["_rk"] = tr[sev_col].map(SEV_RANK)
    return {(int(k) if isinstance(k, (int, np.integer)) else k):
            merge_episodes(g["_ns"].to_numpy(), g["_rk"].to_numpy(), gap_ns)
            for k, g in tr.groupby(key)}


def fpr_floor_threshold(neg_scores, budget: float = 0.05) -> float:
    """FPR 預算操作點：回傳門檻使（以 >= 判定時）FPR 嚴格 ≤ budget。

    只放行 floor(budget·N_neg) 個最高分負樣本；budget·N 不足 1 時門檻取
    max+ε → FPR=0。np.ceil 或四捨五入會讓 FPR 溢出預算（如 0.0501）。
    """
    neg = np.sort(np.asarray(neg_scores, float))
    m = len(neg)
    if m == 0:
        return float("inf")
    kk = int(np.floor(budget * m))
    return float(neg[m - kk]) if kk > 0 else float(neg[-1] + 1e-9)
