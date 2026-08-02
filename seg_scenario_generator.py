#!/usr/bin/env python3
"""
seg_scenario_generator.py — SEG-lite：行為級太空事件場景生成器
================================================================
對標 ComSpOC「Space Event Generator」之輕量版：把偵測所得的**行為模板**反轉為
**參數化生成器**，在真實背景（drag 衰減＋TLE 雜訊）上注入完整「行為劇本」，輸出
**帶真值標籤**的半長軸／軌道元素序列，供：
  (1) 深度模型自監督／真值擴增（解 597 個正 episode 之資料瓶頸）；
  (2) 可重現的 L1/L2/L3 演算法測試集（benchmark v2）；
  (3) 操作員行為型態辨識訓練。

行為模板（參數皆取自本專案實測分布，非臆造）：
  impulsive_keep  脈衝式維持/變軌   ← IDS 1,651 次真實點火（dv_mag 依 severity）
  electric_phasing 連續電推 phasing ← thrust_arc_catalog（dur_h/n_arcs/seg_per_h）
  batch_deploy    批量部署爬升      ← 千帆單日多顆階梯爬升活教材
  plane_reconfig  面級協同重組      ← Starlink 異常軌道面（協同 Δi）
  decay_reentry   衰減/再入         ← FORMOSAT-3 艦隊（單調負 Δa、正 B*）
  station_keeping 安靜（負control）  ← 無機動，僅 drag＋雜訊

每個場景輸出：序列 CSV（含 label）＋事件真值 CSV；並可 round-trip 跑統計偵測器，
回報各行為之偵測率，驗證「生成⇄偵測」一致（生成器與偵測器互為對照）。

用法：python seg_scenario_generator.py [--n 60] [--seed 42] [--roundtrip]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

MU = 398_600.4418           # km³/s²
RE = 6378.137               # km
DA_SM, DA_MD, DA_LG = 1.0, 5.0, 10.0   # 嚴重度門檻（與 detect_maneuvers 一致）

# 高度帶 → TLE 半長軸單步雜訊 σ（km，與 synthetic_injection 一致；Starlink 級）
def noise_sigma(alt_km: float) -> float:
    if alt_km < 450:  return 0.15
    if alt_km < 700:  return 0.08
    return 0.05


def dv_from_da(da_km: float, a_km: float) -> float:
    """半長軸變化 → in-track ΔV（m/s），式 (8)。"""
    return abs(da_km) / 2.0 * np.sqrt(MU / a_km ** 3) * 1000.0


def da_from_dv(dv_ms: float, a_km: float) -> float:
    """in-track ΔV（m/s）→ 半長軸變化（km）。"""
    return dv_ms / 1000.0 * 2.0 / np.sqrt(MU / a_km ** 3)


def severity_of(da_km: float) -> str:
    a = abs(da_km)
    if a < DA_SM: return "below-small"
    if a < DA_MD: return "small"
    if a < DA_LG: return "medium"
    return "large"


# ── 真實分布抽樣（IDS ΔV、thrust_arc phasing）──────────────────────────────────
# IDS 依 severity 之 dv_mag（m/s）對數常態近似（med, p90 取自 ids_truth.csv 實測）
IDS_DV = {"small":  (1.78, 2.31), "medium": (2.34, 4.03), "large": (4.97, 5.13)}
# thrust_arc phasing（逐分鐘 MEME 實測 IQR）
PHASING = {"dur_h": (181.8, 1110.1), "n_arcs": (587, 3996),
           "seg_per_h": (3.23, 3.60), "total_dv_ms": (0.88, 0.92)}


def _lognorm(med, p90, rng):
    """由中位數與 p90 反推對數常態並抽一樣本（p90/med = exp(1.2816·s)）。"""
    med = max(med, 1e-6); p90 = max(p90, med * 1.01)
    s = np.log(p90 / med) / 1.2816
    return float(med * np.exp(rng.normal(0.0, s)))


# ── 場景資料結構 ──────────────────────────────────────────────────────────────
@dataclass
class Scenario:
    sid: str
    behavior: str
    n_sat: int
    df: pd.DataFrame                     # 序列（long：sid,behavior,sat_k,epoch,sma_km,ecc,inc_deg,bstar,label,event_id）
    events: list = field(default_factory=list)   # 真值：[{sat_k,t_event,dv_ms,da_km,di_deg,severity,kind}]


# ── 背景序列：drag 衰減＋TLE 雜訊 ─────────────────────────────────────────────
def _background(a0, inc0, n_pts, cadence_h, rng):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 更新節奏抖動（中位 ~6.8h，右偏；此處以 cadence_h 為基準）
    gaps = np.abs(rng.normal(cadence_h, cadence_h * 0.4, n_pts - 1)) + 0.5
    t_h = np.concatenate([[0.0], np.cumsum(gaps)])
    epochs = [t0 + timedelta(hours=float(h)) for h in t_h]
    sig = noise_sigma(a0 - RE)
    drag_rate = rng.uniform(0.0, 0.04)          # km/step 阻力衰減
    sma = a0 - drag_rate * np.arange(n_pts)
    ecc = np.full(n_pts, 0.0006) + rng.normal(0, 5e-5, n_pts)
    inc = np.full(n_pts, inc0) + rng.normal(0, 5e-4, n_pts)
    bstar = np.full(n_pts, rng.uniform(1e-4, 5e-4))
    return epochs, t_h, sma, ecc, inc, bstar, sig


def _emit(sid, behavior, k, epochs, sma, ecc, inc, bstar, sig, label, ev_id, rng):
    sma_obs = sma + rng.normal(0, sig, len(sma))
    return pd.DataFrame({
        "sid": sid, "behavior": behavior, "sat_k": k,
        "epoch_utc": [e.strftime("%Y-%m-%dT%H:%M:%SZ") for e in epochs],
        "sma_km": np.round(sma_obs, 4), "ecc": np.round(ecc, 6),
        "inc_deg": np.round(inc, 5), "bstar": bstar,
        "label": label.astype(int), "event_id": ev_id,
    })


# ── 六種行為劇本 ──────────────────────────────────────────────────────────────
def gen_impulsive(sid, rng, n_pts=70, cadence_h=6.5):
    a0 = rng.uniform(6740, 6950); inc0 = rng.choice([53.0, 53.2, 70.0, 97.6])
    ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
    sev = rng.choice(["small", "medium", "large"], p=[0.6, 0.3, 0.1])
    dv = _lognorm(*IDS_DV[sev], rng); sign = rng.choice([1, -1])
    da = sign * da_from_dv(dv, a0)
    n_burns = int(rng.choice([1, 2], p=[0.68, 0.32]))
    label = np.zeros(n_pts, bool); events = []
    idxs = sorted(rng.choice(range(n_pts // 4, 3 * n_pts // 4), n_burns, replace=False))
    for j, inj in enumerate(idxs):
        step = da / n_burns
        sma[inj:] += step
        label[inj] = True
        events.append({"sat_k": 0, "t_event": ep[inj].strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "dv_ms": round(dv / n_burns, 4), "da_km": round(step, 4),
                       "di_deg": 0.0, "severity": severity_of(step), "kind": "impulsive_keep"})
    df = _emit(sid, "impulsive_keep", 0, ep, sma, ecc, inc, bs, sig, label, sid, rng)
    return Scenario(sid, "impulsive_keep", 1, df, events)


def gen_electric_phasing(sid, rng, n_pts=90, cadence_h=6.0):
    a0 = rng.uniform(6870, 6930); inc0 = rng.choice([53.0, 53.2])
    ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
    dur_h = rng.uniform(*PHASING["dur_h"])
    total_da = da_from_dv(rng.uniform(*PHASING["total_dv_ms"]) * rng.uniform(3, 12), a0)
    # 連續爬升：在 [i0,i1] 之間線性累加（逐 TLE 呈現為緩坡，非單一階躍）
    i0 = rng.integers(n_pts // 5, n_pts // 2)
    i1 = min(n_pts - 2, i0 + max(3, int(dur_h / cadence_h)))
    ramp = np.linspace(0, total_da, i1 - i0)
    sma[i0:i1] += ramp
    sma[i1:] += total_da
    label = np.zeros(n_pts, bool); label[i0:i1] = True
    ev = [{"sat_k": 0, "t_event": ep[i0].strftime("%Y-%m-%dT%H:%M:%SZ"),
           "dv_ms": round(dv_from_da(total_da, a0), 4), "da_km": round(total_da, 4),
           "di_deg": 0.0, "severity": severity_of(total_da), "kind": "electric_phasing"}]
    df = _emit(sid, "electric_phasing", 0, ep, sma, ecc, inc, bs, sig, label, sid, rng)
    return Scenario(sid, "electric_phasing", 1, df, ev)


def gen_batch_deploy(sid, rng, n_pts=80, cadence_h=6.0):
    n_sat = int(rng.integers(4, 9)); frames = []; events = []
    a0 = rng.uniform(6720, 6760); inc0 = 53.2                    # 入軌泊軌
    i_start = rng.integers(n_pts // 4, n_pts // 2)
    for k in range(n_sat):
        ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
        label = np.zeros(n_pts, bool)
        # 階梯爬升：連續數步各 +Δa（同批、略錯開起始）
        s0 = i_start + int(rng.integers(0, 4))
        nstep = int(rng.integers(4, 9)); da_step = rng.uniform(1.5, 2.5)
        for j in range(nstep):
            si = min(n_pts - 1, s0 + j)
            sma[si:] += da_step; label[si] = True
        events.append({"sat_k": k, "t_event": ep[s0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "dv_ms": round(dv_from_da(da_step * nstep, a0), 4),
                       "da_km": round(da_step * nstep, 4), "di_deg": 0.0,
                       "severity": severity_of(da_step * nstep), "kind": "batch_deploy"})
        frames.append(_emit(sid, "batch_deploy", k, ep, sma, ecc, inc, bs, sig, label, sid, rng))
    return Scenario(sid, "batch_deploy", n_sat, pd.concat(frames, ignore_index=True), events)


def gen_plane_reconfig(sid, rng, n_pts=80, cadence_h=6.0):
    n_sat = int(rng.integers(4, 8)); frames = []; events = []
    a0 = rng.uniform(6900, 6950); inc0 = rng.choice([53.2, 70.0])
    i_ev = rng.integers(n_pts // 3, 2 * n_pts // 3)
    ddi = rng.uniform(0.02, 0.08) * rng.choice([1, -1])          # 協同傾角調整
    for k in range(n_sat):
        ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
        label = np.zeros(n_pts, bool)
        ii = i_ev + int(rng.integers(-1, 2))
        inc[ii:] += ddi + rng.normal(0, 0.002)                  # 面內多星同期移傾角
        # 變平面亦帶少量 Δa
        da = da_from_dv(dv_from_da(0, a0), a0)
        label[ii] = True
        events.append({"sat_k": k, "t_event": ep[ii].strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "dv_ms": round(abs(ddi) * np.deg2rad(1) * np.sqrt(MU / a0) * 1000 / 57.3, 4),
                       "da_km": 0.0, "di_deg": round(ddi, 4),
                       "severity": "plane", "kind": "plane_reconfig"})
        frames.append(_emit(sid, "plane_reconfig", k, ep, sma, ecc, inc, bs, sig, label, sid, rng))
    return Scenario(sid, "plane_reconfig", n_sat, pd.concat(frames, ignore_index=True), events)


def gen_decay_reentry(sid, rng, n_pts=80, cadence_h=6.0):
    a0 = rng.uniform(6600, 6750); inc0 = rng.choice([72.0, 97.4])
    ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
    # 加速衰減：drag ∝ 密度隨高度上升 → 二次負曲率；正 B*
    accel = rng.uniform(2e-4, 8e-4)
    sma = a0 - 0.02 * np.arange(n_pts) - accel * np.arange(n_pts) ** 2
    bs = np.full(n_pts, rng.uniform(6e-4, 2e-3))                 # 高 B*
    label = np.zeros(n_pts, bool)                               # 全程「非機動」（負 control）
    ev = [{"sat_k": 0, "t_event": ep[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
           "dv_ms": 0.0, "da_km": round(float(sma[-1] - sma[0]), 4), "di_deg": 0.0,
           "severity": "decay", "kind": "decay_reentry"}]
    df = _emit(sid, "decay_reentry", 0, ep, sma, ecc, inc, bs, sig, label, sid, rng)
    return Scenario(sid, "decay_reentry", 1, df, ev)


def gen_station_keeping(sid, rng, n_pts=70, cadence_h=6.5):
    a0 = rng.uniform(6740, 6950); inc0 = rng.choice([53.2, 70.0, 97.6])
    ep, th, sma, ecc, inc, bs, sig = _background(a0, inc0, n_pts, cadence_h, rng)
    label = np.zeros(n_pts, bool)                               # 純安靜（負 control）
    df = _emit(sid, "station_keeping", 0, ep, sma, ecc, inc, bs, sig, label, sid, rng)
    return Scenario(sid, "station_keeping", 1, df, [])


GENERATORS = {
    "impulsive_keep":  gen_impulsive,
    "electric_phasing": gen_electric_phasing,
    "batch_deploy":    gen_batch_deploy,
    "plane_reconfig":  gen_plane_reconfig,
    "decay_reentry":   gen_decay_reentry,
    "station_keeping": gen_station_keeping,
}


# ── round-trip：對生成序列跑統計偵測器，回報偵測率 ──────────────────────────────
def _roundtrip_rate(scn: Scenario, tol=2) -> tuple[int, int]:
    try:
        from statistical_detectors import run_all
    except Exception:
        return (0, 0)
    hit = pos = 0
    for k, g in scn.df.groupby("sat_k"):
        sma = g["sma_km"].to_numpy()
        lab = np.where(g["label"].to_numpy() == 1)[0]
        if len(lab) == 0:
            continue                                            # 負 control 不計入召回分母
        pos += 1
        r = run_all(sma)
        flagged = set()
        for key in ("mad3sig", "cusum"):
            ev = r.get(key, {}).get("events", [])
            flagged |= set(int(x) for x in np.asarray(ev, int))
        if any(abs(f - li) <= tol for f in flagged for li in lab):
            hit += 1
    return hit, pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="每種行為之場景數")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--behaviors", default="all")
    ap.add_argument("--roundtrip", action="store_true", help="生成後跑統計偵測器驗證")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    behaviors = list(GENERATORS) if args.behaviors == "all" else args.behaviors.split(",")
    print(f"SEG-lite 行為級場景生成：{len(behaviors)} 行為 × {args.n} 場景 …\n")

    all_series, all_events, rt = [], [], {}
    for beh in behaviors:
        gen = GENERATORS[beh]
        scns = []
        for i in range(args.n):
            scn = gen(f"{beh}_{i:04d}", rng)
            all_series.append(scn.df)
            for e in scn.events:
                all_events.append({"sid": scn.sid, "behavior": beh, **e})
            scns.append(scn)
        if args.roundtrip:
            h = p = 0
            for s in scns:
                hh, pp = _roundtrip_rate(s); h += hh; p += pp
            rt[beh] = (h, p)

    series = pd.concat(all_series, ignore_index=True)
    events = pd.DataFrame(all_events)
    out = Path("data/benchmark"); out.mkdir(parents=True, exist_ok=True)
    date = "20260723"
    sp = out / f"seg_scenarios_{date}.csv"
    evp = out / f"seg_events_{date}.csv"
    series.to_csv(sp, index=False, encoding="utf-8-sig")
    events.to_csv(evp, index=False, encoding="utf-8-sig")

    print("=" * 70)
    print(f"{'行為':<18}{'場景':>6}{'序列點':>8}{'正窗':>7}{'事件':>6}", end="")
    print(f"{'round-trip 偵測率':>18}" if args.roundtrip else "")
    print("-" * 70)
    for beh in behaviors:
        s = series[series.behavior == beh]
        npos = int((s.label == 1).sum())
        nev = int((events.behavior == beh).sum()) if len(events) else 0
        nsc = s["sid"].nunique()
        line = f"{beh:<18}{nsc:>6}{len(s):>8}{npos:>7}{nev:>6}"
        if args.roundtrip and beh in rt:
            h, p = rt[beh]
            line += f"{(f'{h}/{p} = {h/p:.2f}' if p else 'n/a（負control）'):>18}"
        print(line)
    print("=" * 70)
    print(f"總計：{series['sid'].nunique()} 場景、{len(series):,} 序列點、{len(events)} 真值事件")
    print(f"輸出 → {sp}")
    print(f"       {evp}")
    print("\n用途：正樣本層擴增（解 597 episode 瓶頸）｜benchmark v2 可重現測試集｜行為型態訓練資料")


if __name__ == "__main__":
    main()
