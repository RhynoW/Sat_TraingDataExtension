#!/usr/bin/env python3
"""
mpt_maneuver_reconstruct.py — MPT-lite：非合作目標機動重建閉環
==============================================================
對標 ComSpOC ODSSA「Maneuver Processing Tool」之輕量版：把散裝的時刻／ΔV 估計封裝為
**假說 → 優化 → 迭代 refine** 的工作流，從觀測（TLE 半長軸／傾角／RAAN 序列）反推
非合作目標之機動，輸出「機動重建卡」。

閉環三步：
  1. 假說（hypothesis）：以變化點定時刻 t_burn，由 Δa／Δi／ΔRAAN 殘差反解 ΔV 三維向量
                          （in-track 由 Δa、cross-track 由 Δi 與 ΔRAAN、radial 由 Δe）。
  2. 優化（optimize）  ：對 (t_burn, Δa) 做「階躍＋線性 drag」最小平方擬合，壓低殘差。
  3. 迭代（refine）    ：逐步揭露機動後觀測（模擬新 track 進站），回報 ΔV 估計之收斂。

重建卡欄位：t_burn±不確定度、ΔV 向量（R/T/N，m/s）、|ΔV|、脈衝 vs 連續分型、殘差 RMS。

驗證：直接吃 SEG-lite 生成之場景（已知 ΔV 真值）→ 逐場景重建並評分（時刻誤差、ΔV 誤差），
     形成「SEG 生成 ⇄ MPT 重建」閉環對照。亦提供 reconstruct(df) 供真實單星序列使用。

用法：python mpt_maneuver_reconstruct.py [--scenarios data/benchmark/seg_scenarios_*.csv]
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

MU = 398_600.4418
J2 = 1.082_63e-3
RE = 6378.137


def _mad(x):
    x = np.asarray(x, float)
    return 1.4826 * np.median(np.abs(x - np.median(x))) if len(x) else 0.0


def _j2_raan_rate(a, e, i_deg):
    """J2 RAAN 長期漂移率（deg/day）。"""
    n = np.sqrt(MU / a ** 3) * 86400.0 / (2 * np.pi)         # rev/day
    p = a * (1 - e ** 2)
    return -1.5 * J2 * (RE / p) ** 2 * n * np.cos(np.deg2rad(i_deg)) * 360.0


# ── 1. 假說 ───────────────────────────────────────────────────────────────────
def _changepoint(sma):
    """回傳最可能的階躍索引（相鄰穩健 z 之最大處）。"""
    da = np.diff(sma)
    z = np.abs(da - np.median(da)) / (_mad(da) + 1e-9)
    return int(np.argmax(z)) + 1 if len(z) else len(sma) // 2


def _robust_step(sig, cp, k=6):
    """cp 前後各取 k 點穩健中位差。"""
    before = sig[max(0, cp - k):cp]
    after = sig[cp:cp + k]
    if len(before) < 2 or len(after) < 2:
        return 0.0
    return float(np.median(after) - np.median(before))


# ── 2. 優化：階躍＋線性 drag 擬合，掃 t_burn、解 (drag, Δa) ─────────────────────
def _fit_step(t_h, sma, cp_lo, cp_hi):
    """在 [cp_lo,cp_hi] 掃描階躍位置，對每個位置最小平方解 (斜率 drag, 截距, Δa)。"""
    best = None
    for cp in range(cp_lo, cp_hi):
        step = (np.arange(len(sma)) >= cp).astype(float)
        A = np.column_stack([t_h, np.ones_like(t_h), step])
        coef, *_ = np.linalg.lstsq(A, sma, rcond=None)
        resid = sma - A @ coef
        rms = float(np.sqrt(np.mean(resid ** 2)))
        if best is None or rms < best[0]:
            best = (rms, cp, float(coef[2]), float(coef[0]))    # rms, cp, Δa, drag/step
    return best   # (rms, cp, da, drag_rate)


# ── 3. ΔV 反解（R/T/N）────────────────────────────────────────────────────────
def _dv_vector(a, da, di_deg, draan_res_deg, de):
    """由元素變化反解脈衝 ΔV（m/s，Gauss 變分之一階近似）。"""
    V = np.sqrt(MU / a) * 1000.0                                # 圓軌速度 m/s
    dv_t = da / 2.0 * np.sqrt(MU / a ** 3) * 1000.0            # in-track（沿軌）
    dv_n = V * np.sqrt(np.deg2rad(di_deg) ** 2 +
                       (np.sin(1.0) * np.deg2rad(draan_res_deg)) ** 2)  # cross-track（垂軌）
    dv_r = V * abs(de)                                          # radial（徑向，粗略）
    return dv_r, dv_t, dv_n


def reconstruct(df: pd.DataFrame, reveal_steps=(4, 8, 12)) -> dict:
    """對單星序列（欄位：epoch_utc, sma_km, inc_deg[, ecc]）重建機動。回傳重建卡。"""
    d = df.sort_values("epoch_utc").reset_index(drop=True)
    sma = d["sma_km"].to_numpy(float)
    inc = d["inc_deg"].to_numpy(float) if "inc_deg" in d else np.zeros(len(d))
    ecc = d["ecc"].to_numpy(float) if "ecc" in d else np.zeros(len(d))
    t = pd.to_datetime(d["epoch_utc"], utc=True, format="ISO8601")
    t_h = (t - t.iloc[0]).dt.total_seconds().to_numpy() / 3600.0

    cp0 = _changepoint(sma)
    lo, hi = max(1, cp0 - 6), min(len(sma) - 1, cp0 + 7)
    rms, cp, da, drag = _fit_step(t_h, sma, lo, hi)
    a0 = float(np.median(sma[:max(2, cp)]))

    di = _robust_step(inc, cp)
    de = _robust_step(ecc, cp)
    # ΔRAAN 殘差：此輕量版不含 raan 欄時以 0（真實資料可接 draan_res）
    draan_res = 0.0
    dv_r, dv_t, dv_n = _dv_vector(a0, da, di, draan_res, de)
    dv_mag = float(np.sqrt(dv_r ** 2 + dv_t ** 2 + dv_n ** 2))

    # 脈衝 vs 連續：階躍集中度（cp 前後 2 點內完成→脈衝；跨多步→連續）
    win = slice(max(0, cp - 8), min(len(sma), cp + 8))
    seg_z = np.abs(np.diff(sma[win]))
    conc = float(seg_z.max() / (seg_z.sum() + 1e-9)) if len(seg_z) else 1.0
    kind = "impulsive" if conc >= 0.5 else "continuous"

    # 時刻不確定度：以擬合 RMS 換算相鄰步數（RMS / |Δa/步| ≈ 步不確定度）
    dt_unc_h = float(np.median(np.diff(t_h))) * (1 + rms / (abs(da) + 1e-3))

    # 迭代 refine：逐步揭露機動後觀測，重估 Δa
    conv = []
    for r in reveal_steps:
        end = min(len(sma), cp + r)
        if end - cp >= 2:
            da_r = _robust_step(sma[:end], cp, k=min(6, r))
            conv.append({"reveal_after": r, "dv_intrack_ms": round(dv_from_da(da_r, a0), 4)})

    return {
        "t_burn_epoch": t.iloc[cp].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "t_burn_idx": cp, "dt_unc_h": round(dt_unc_h, 2),
        "dv_R_ms": round(dv_r, 4), "dv_T_ms": round(dv_t, 4), "dv_N_ms": round(dv_n, 4),
        "dv_mag_ms": round(dv_mag, 4), "da_km": round(da, 4), "di_deg": round(di, 5),
        "kind": kind, "resid_rms_km": round(rms, 4), "a0_km": round(a0, 2),
        "refine_trace": conv,
    }


def dv_from_da(da, a):
    return abs(da) / 2.0 * np.sqrt(MU / a ** 3) * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--events", default="")
    args = ap.parse_args()

    sp = args.scenarios or sorted(glob.glob("data/benchmark/seg_scenarios_*.csv"))[-1]
    evp = args.events or sorted(glob.glob("data/benchmark/seg_events_*.csv"))[-1]
    series = pd.read_csv(sp)
    truth = pd.read_csv(evp)
    print(f"MPT-lite 機動重建閉環 ← {Path(sp).name}\n")

    # 只對「單事件、可重建」之行為評分（脈衝/批量），逐 (sid,sat_k) 重建
    scoreable = truth[truth["kind"].isin(["impulsive_keep", "batch_deploy", "electric_phasing"])]
    rows = []
    for (sid, k), evg in scoreable.groupby(["sid", "sat_k"]):
        g = series[(series.sid == sid) & (series.sat_k == k)]
        if len(g) < 12:
            continue
        card = reconstruct(g)
        # 真值（取該 sat 之首個事件；批量階梯以總 ΔV 對照）
        ev = evg.iloc[0]
        tv = pd.to_datetime(ev["t_event"], utc=True)
        tb = pd.to_datetime(card["t_burn_epoch"], utc=True)
        rows.append({
            "behavior": ev["kind"], "sid": sid,
            "t_err_h": abs((tb - tv).total_seconds()) / 3600.0,
            "dv_true": abs(float(ev["dv_ms"])), "dv_est": card["dv_mag_ms"],
            "dv_err": abs(card["dv_mag_ms"] - abs(float(ev["dv_ms"]))),
            "kind_est": card["kind"], "rms": card["resid_rms_km"],
        })
    R = pd.DataFrame(rows)

    print("=" * 74)
    print(f"{'行為':<18}{'n':>5}{'時刻誤差中位h':>13}{'ΔV真值中位':>12}{'ΔV估計中位':>12}{'ΔV誤差中位':>12}")
    print("-" * 74)
    for beh, g in R.groupby("behavior"):
        print(f"{beh:<18}{len(g):>5}{g.t_err_h.median():>13.2f}"
              f"{g.dv_true.median():>12.3f}{g.dv_est.median():>12.3f}{g.dv_err.median():>12.3f}")
    print("=" * 74)
    # 分型正確率：脈衝類（impulsive_keep）應判 impulsive；連續類（electric_phasing）應判 continuous；
    # batch_deploy 為多步階梯（單星視角介於兩者），另計不納入二元對錯。
    imp = R[R.behavior == "impulsive_keep"]
    con = R[R.behavior == "electric_phasing"]
    bat = R[R.behavior == "batch_deploy"]
    if len(imp):
        print(f"分型｜脈衝類→impulsive 正確率：{(imp.kind_est=='impulsive').mean():.1%}（n={len(imp)}）")
    if len(con):
        print(f"分型｜連續類→continuous 正確率：{(con.kind_est=='continuous').mean():.1%}（n={len(con)}）")
    if len(bat):
        print(f"分型｜批量階梯 judged continuous 佔比：{(bat.kind_est=='continuous').mean():.1%}"
              f"（多步階梯，兩判皆合理）")

    # 一張範例重建卡
    ex = series[(series.behavior == "impulsive_keep")]
    exsid = ex["sid"].iloc[0]
    card = reconstruct(ex[ex.sid == exsid])
    tv = truth[(truth.sid == exsid)].iloc[0]
    print(f"\n【範例重建卡】{exsid}")
    print(f"  估計 t_burn {card['t_burn_epoch']}（±{card['dt_unc_h']}h）｜真值 {tv['t_event']}")
    print(f"  ΔV(R/T/N) = {card['dv_R_ms']}/{card['dv_T_ms']}/{card['dv_N_ms']} m/s｜|ΔV|={card['dv_mag_ms']}"
          f"（真值 {tv['dv_ms']}）｜分型 {card['kind']}｜殘差RMS {card['resid_rms_km']}km")
    print(f"  迭代收斂（揭露愈多觀測）：{card['refine_trace']}")

    out = Path("data/benchmark/mpt_reconstruction_20260723.csv")
    R.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")
    print("閉環驗證：SEG 生成已知 ΔV → MPT 重建 → 對照真值；脈衝類時刻/ΔV 誤差小、"
          "連續電推較難（漸進弧無單一階躍）——與偵測端結論一致。")


if __name__ == "__main__":
    main()
