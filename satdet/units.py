"""satdet.units — unit 級評估的共用切窗（fusion / PatchTST / LSTM-AE 共用）。

unit 級評估是本專案避開「MEME 8h 網格 vs TLE epoch 點級錯位」的關鍵設計：
正 unit＝機動 episode ±tol 窗；負 unit＝安靜 epoch 切成等寬塊（與正 unit
等寬，否則長度不對稱會洩漏、AUC 假高）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import HOUR_NS, TOL_NS, latest_file, to_ns


def load_drag_map(pattern: str = "data/drag/drag_resid_*.csv") -> dict:
    """NRLMSIS 阻力殘差 → {norad_id: {epoch_ns: |drag_resid_da|}}；無檔回空 dict。"""
    try:
        path = latest_file(pattern)
    except FileNotFoundError:
        return {}
    d = pd.read_csv(path)
    d.columns = [c.strip().lstrip("﻿") for c in d.columns]
    d["ep"] = to_ns(d["epoch_utc"])
    return {nid: dict(zip(gg["ep"].to_numpy(), gg["drag_resid_da"].abs().to_numpy()))
            for nid, gg in d.groupby("norad_id")}


def episode_masks(ep_ns: np.ndarray, episodes, tol_ns: int = TOL_NS):
    """對每個 episode 取涵蓋 epoch 遮罩。

    回傳 ([(mask, rank, latency_h), ...], assigned)：
    latency_h＝窗內 epoch 與轉移時刻的最小絕對時差（小時）；
    assigned＝被任一 episode 窗涵蓋的 epoch 布林陣列（餘下為安靜 epoch）。
    """
    assigned = np.zeros(len(ep_ns), bool)
    out = []
    for times, rk in episodes:
        lo, hi = times.min() - tol_ns, times.max() + tol_ns
        mask = (ep_ns >= lo) & (ep_ns <= hi)
        if mask.any():
            lat = float(np.abs(ep_ns[mask][:, None] - times[None, :]).min() / HOUR_NS)
            out.append((mask, rk, lat))
            assigned |= mask
    return out, assigned


def quiet_blocks(ep_ns: np.ndarray, idx: np.ndarray, width_ns: int = 2 * TOL_NS):
    """把安靜 epoch 索引切成等寬（width_ns，預設 ~48h）時間塊，逐塊 yield 索引陣列。"""
    p = 0
    while p < len(idx):
        t0 = ep_ns[idx[p]]
        w = [idx[p]]
        q = p + 1
        while q < len(idx) and ep_ns[idx[q]] - t0 <= width_ns:
            w.append(idx[q])
            q += 1
        yield np.array(w)
        p = q
