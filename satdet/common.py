"""satdet.common — 跨模組共用工具（單一事實來源）。

集中曾在多個腳本重複、且各踩過坑的邏輯：
  to_ns()               µs-vs-ns 單位陷阱（raw_tle epoch 會解析成 datetime64[us]）
  latest_file()         「最新時間戳檔案」慣例的唯一實作（含清楚錯誤訊息）
  merge_episodes()      機動轉移 → episode（48h gap 合併、取 max 嚴重度）
  episodes_by_sat()     整張 truth 表 → {衛星: [(times_ns, rank)]}
  fpr_floor_threshold() FPR 預算操作點（floor 保證嚴格 ≤ budget）
  tle_ephemeris_type()  line1 第 63 欄 Ephemeris Type（4 = SGP4-XP，與 SGP4 不互通）
  warn_sgp4xp()         整批 TLE 偵測 Type-4 並發 warning（避免混入後靜默算錯）
"""
from __future__ import annotations

import glob
import warnings

import numpy as np
import pandas as pd

HOUR_NS = int(3.6e12)
TOL_NS = 24 * HOUR_NS   # episode 配對容差（＝latency 目標）
GAP_NS = 48 * HOUR_NS   # episode 合併間隔
SEV_RANK = {"small": 1, "medium": 2, "large": 3}
RANK_SEV = {v: k for k, v in SEV_RANK.items()}

# TLE line1 第 63 欄（0-based index 62）Ephemeris Type。
#   0 = SGP4/SDP4（Space-Track 公開 TLE 一律為 0）
#   4 = SGP4-XP（USSF AstroStds v8+，2020-12 起；EGM-96/J5、Jacchia-70、SRP AGOM）
# Type-4 的平均元素是用 XP 理論擬合的，用傳統 SGP4（python-sgp4/Skyfield）傳播會錯，
# 且 line1 第 45–52 欄（n̈）被 AGOM 取代。本專案下游全部假設 SGP4，故必須標旗。
EPHEMERIS_TYPE_SGP4 = 0
EPHEMERIS_TYPE_SGP4_XP = 4


class SGP4XPWarning(UserWarning):
    """批次中混入 SGP4-XP（Type-4）TLE。"""


def tle_ephemeris_type(line1) -> int | None:
    """回傳 TLE line1 的 Ephemeris Type 整數；line1 缺失／過短／非數字回傳 None。"""
    if not isinstance(line1, str) or len(line1) < 63:
        return None
    ch = line1[62]
    if ch == " ":
        return 0            # 部分來源以空白代表 0
    return int(ch) if ch.isdigit() else None


def warn_sgp4xp(ephemeris_types, context: str = "") -> int:
    """回傳批次中 Type-4 筆數；>0 時發 SGP4XPWarning（不拋例外，讓資料仍入庫但有旗標）。"""
    arr = pd.Series(list(ephemeris_types))
    n_xp = int((arr == EPHEMERIS_TYPE_SGP4_XP).sum())
    if n_xp:
        warnings.warn(
            f"{context} 偵測到 {n_xp}/{len(arr)} 筆 SGP4-XP（Ephemeris Type=4）TLE；"
            "其平均元素與 SGP4 不互通，下游 SGP4/幾何計算應以 ephemeris_type 欄位過濾。",
            SGP4XPWarning, stacklevel=2)
    return n_xp


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
