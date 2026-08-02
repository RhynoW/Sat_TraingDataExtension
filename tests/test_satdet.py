# -*- coding: utf-8 -*-
"""tests/test_satdet.py — 守住四個實際踩過的坑的最小回歸測試集。

  1. to_ns()：datetime64[us] vs [ns] 的 1000× 單位錯誤
  2. merge_episodes()：48h gap 合併邊界 + max 嚴重度
  3. audit_tles()：quality_flag 三級判則（rejected / suspect / good）+ 重複去除
  4. fpr_floor_threshold()：操作點 FPR 必須嚴格 ≤ 預算（floor 而非 ceil/round）

用法：pytest tests/test_satdet.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satdet.common import (GAP_NS, HOUR_NS, SEV_RANK, fpr_floor_threshold,
                           merge_episodes, to_ns)
from data_quality_audit import audit_tles


# ── 1. µs-vs-ns 回歸 ──────────────────────────────────────────────────────────
def test_to_ns_us_vs_ns_regression():
    """曾踩坑：raw_tle epoch 解析成 datetime64[us]、truth 成 [ns]，直接
    astype("int64") 差 1000×。to_ns 必須對兩種 dtype 給出相同奈秒值。"""
    stamps = ["2026-01-01T00:00:00", "2026-01-02T12:34:56"]
    s_str = pd.Series(stamps)
    s_ns = pd.Series(pd.to_datetime(stamps)).astype("datetime64[ns]")
    s_us = pd.Series(pd.to_datetime(stamps)).astype("datetime64[us]")

    # [us] 直接取整數確實差 1000×（坑本身還在，證明防護有必要）
    assert s_us.astype("int64").iloc[0] * 1000 == s_ns.astype("int64").iloc[0]

    ref = to_ns(s_str)
    np.testing.assert_array_equal(to_ns(s_ns), ref)
    np.testing.assert_array_equal(to_ns(s_us), ref)
    # 一天又 12:34:56 的間隔，奈秒值須精確
    assert ref[1] - ref[0] == (36 * 3600 + 34 * 60 + 56) * 10**9


# ── 2. episode 合併邊界 ───────────────────────────────────────────────────────
def test_merge_episodes_boundary_and_severity():
    """間隔 ≤48h 合併、>48h 斷開；episode 嚴重度＝窗內最大（逐轉移會低估）。"""
    h = HOUR_NS
    t = np.array([0, 47 * h, 47 * h + GAP_NS, 47 * h + 2 * GAP_NS + 1])
    r = np.array([SEV_RANK["small"], SEV_RANK["large"],
                  SEV_RANK["medium"], SEV_RANK["small"]])
    eps = merge_episodes(t, r)
    # t0-t1 間隔 47h 合併；t1→t2 恰 48h（不 >gap）仍合併；t2→t3 為 48h+1ns 斷開
    assert len(eps) == 2
    assert list(eps[0][0]) == [0, 47 * h, 47 * h + GAP_NS]
    assert eps[0][1] == SEV_RANK["large"]      # max 嚴重度
    assert eps[1][1] == SEV_RANK["small"]

    # 未排序輸入須自動排序
    eps2 = merge_episodes(t[::-1], r[::-1])
    assert len(eps2) == 2 and eps2[0][1] == SEV_RANK["large"]
    assert merge_episodes(np.array([]), np.array([])) == []


# ── 3. quality_flag 三級判則 ──────────────────────────────────────────────────
def test_quality_flag_rules():
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    df = pd.DataFrame({
        "epoch": [base,
                  base + pd.Timedelta(seconds=30),    # 與前筆 ≤60s → 去重（n_dup）
                  base + pd.Timedelta(hours=12),      # 正常 → good
                  base + pd.Timedelta(hours=24),      # e=1.2 → rejected
                  base + pd.Timedelta(hours=24 + 72)],  # gap 72h → suspect
        "sma_km": [6900.0, 6900.0, 6900.5, 6900.5, 6901.0],
        "inclination_deg": [53.0, 53.0, 53.0, 53.0, 53.0],
        "eccentricity": [0.001, 0.001, 0.001, 1.2, 0.001],
        "bstar": [1e-4, 1e-4, 1e-4, 1e-4, 5.0],       # 末筆 |B*|>1 亦 suspect
    })
    out = audit_tles(df)
    assert out.attrs["n_dup"] == 1 and len(out) == 4
    flags = out["quality_flag"].tolist()
    assert flags[0] == "good" and flags[1] == "good"
    assert flags[2] == "rejected" and "ecc" in out["quality_reason"].iloc[2]
    assert flags[3] == "suspect"
    assert "gap" in out["quality_reason"].iloc[3] and "bstar" in out["quality_reason"].iloc[3]

    # rejected 優先於 suspect：sma 在地表下 + 大 gap → rejected
    df2 = pd.DataFrame({
        "epoch": [base, base + pd.Timedelta(hours=100)],
        "sma_km": [6900.0, 5000.0],
        "inclination_deg": [53.0, 53.0],
        "eccentricity": [0.001, 0.001],
    })
    assert audit_tles(df2)["quality_flag"].iloc[1] == "rejected"


# ── 4. FPR floor 操作點 ──────────────────────────────────────────────────────
def test_fpr_floor_threshold_strict_budget():
    """曾踩坑：門檻取法不對 → FPR=0.0501 溢出 ≤0.05 預算。
    floor 取法必須在任何 N 下都嚴格 ≤ budget（以 score >= thr 判陽性）。"""
    rng = np.random.default_rng(42)
    for m in (19, 20, 21, 100, 999, 1000, 1234):
        neg = rng.random(m)
        thr = fpr_floor_threshold(neg, 0.05)
        fpr = float((neg >= thr).mean())
        assert fpr <= 0.05 + 1e-12, f"N={m}: FPR={fpr} 溢出預算"

    # 邊界：N=20、budget 5% → 恰放行 1 個（floor(1.0)=1，FPR=0.05 合法）
    neg = np.arange(20, dtype=float)
    thr = fpr_floor_threshold(neg, 0.05)
    assert (neg >= thr).sum() == 1
    # N=19 → floor(0.95)=0 → 一個都不放行
    neg = np.arange(19, dtype=float)
    thr = fpr_floor_threshold(neg, 0.05)
    assert (neg >= thr).sum() == 0
    # 空輸入不炸
    assert fpr_floor_threshold(np.array([]), 0.05) == float("inf")
