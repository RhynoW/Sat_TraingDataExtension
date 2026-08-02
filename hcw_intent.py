#!/usr/bin/env python3
"""
hcw_intent.py — HCW 殘差意圖研判：受控 RPO vs 自然漂移
======================================================
思路（與 Model 2「NRLMSIS 扣阻力後看殘差」同構）：
  HCW（Hill–Clohessy–Wiltshire）方程描述**無控制**下兩顆鄰近衛星的相對運動。
  把觀測到的相對軌跡（由 conjunction_viz 從真實 TLE 重建）拿去擬合 HCW：
    擬合得上   → 自然漂移接近（無推力）
    系統性擬合不上 → 有推力介入 = 受控 RPO

作法：滑動視窗最小平方擬合。每個視窗內以 HCW 狀態轉移矩陣的「位置列」建立
設計矩陣 A(3N×6)，解初始相對狀態 x0(6)，殘差 = 觀測 − HCW 預測。
殘差 RMS 隨時間的抬升即為推力事件；相鄰視窗擬合速度之差可反推 ΔV 量級與方向。

座標：吃 conjunction_viz 的 RTN（R=徑向, T=沿跡, N=法向），直接對應 HCW 的 x/y/z。

用法：
  python hcw_intent.py 58573 59884                    # 已知 RPO 案例
  python hcw_intent.py 58573 59884 --control 62841 62842   # 加對照組校準基線

限制（重要，見 README/報告）：
  * HCW 假設目標圓軌道、分離量 << 軌道半徑；偏心率會抬高殘差基線。
  * HCW 不含 J2 差分漂移 —— 兩物體傾角/RAAN 不同時，法向(N)殘差會被 J2 撐大，
    非推力所致。真實 RPO 中追逐者多已匹配目標軌道面，此項影響較小。
  * TLE 位置誤差為 km 級 —— 殘差有觀測雜訊地板，故必須用**對照組**校準門檻，
    不能憑絕對值判定。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

MU = 398600.4418          # km^3/s^2
R_E = 6378.137


def cw_position_rows(n: float, t: float) -> np.ndarray:
    """HCW 狀態轉移矩陣的位置列 (3×6)，狀態序 = [x0,y0,z0,vx0,vy0,vz0]。

    x=徑向, y=沿跡, z=法向；標準 Clohessy-Wiltshire 解：
      x(t) = (4-3c)x0 + (s/n)vx0 + (2/n)(1-c)vy0
      y(t) = 6(s-nt)x0 + y0 - (2/n)(1-c)vx0 + (1/n)(4s-3nt)vy0
      z(t) = c·z0 + (s/n)vz0
    """
    c, s = np.cos(n * t), np.sin(n * t)
    return np.array([
        [4 - 3 * c, 0.0, 0.0, s / n, (2 / n) * (1 - c), 0.0],
        [6 * (s - n * t), 1.0, 0.0, -(2 / n) * (1 - c), (4 * s - 3 * n * t) / n, 0.0],
        [0.0, 0.0, c, 0.0, 0.0, s / n],
    ])


def cw_velocity_rows(n: float, t: float) -> np.ndarray:
    """HCW STM 的速度列 (3×6)，供相鄰視窗反推 ΔV。"""
    c, s = np.cos(n * t), np.sin(n * t)
    return np.array([
        [3 * n * s, 0.0, 0.0, c, 2 * s, 0.0],
        [-6 * n * (1 - c), 0.0, 0.0, -2 * s, 4 * c - 3, 0.0],
        [0.0, 0.0, -n * s, 0.0, 0.0, c],
    ])


def fit_cw_window(t_rel: np.ndarray, pos: np.ndarray, n: float):
    """對單一視窗做 HCW 最小平方擬合。

    t_rel: (N,) 視窗內相對秒數（以視窗起點為 0）
    pos  : (N,3) 觀測 RTN 位置 (km)
    回傳 (x0(6,), resid(N,3), rms_total, rms_axis(3,))
    """
    A = np.vstack([cw_position_rows(n, ti) for ti in t_rel])       # (3N,6)
    b = pos.reshape(-1)                                             # (3N,)
    x0, *_ = np.linalg.lstsq(A, b, rcond=None)
    pred = (A @ x0).reshape(-1, 3)
    resid = pos - pred
    rms_total = float(np.sqrt((resid ** 2).sum(axis=1).mean()))
    rms_axis = np.sqrt((resid ** 2).mean(axis=0))
    return x0, resid, rms_total, rms_axis


def hcw_residual_series(data: dict, window_min: float = 180.0,
                        stride_min: float | None = None) -> pd.DataFrame:
    """對 conjunction_viz.compute_pair_series 的輸出做滑動視窗 HCW 擬合。

    回傳 df[t_mid, rms_km, rms_R, rms_T, rms_N, d_km, n_pts]
    """
    rel = data["rel"]
    t = pd.to_datetime([x["t"] for x in rel], utc=True)
    pos = np.array([[x["R"], x["T"], x["N"]] for x in rel], float)
    dist = np.array([x["d"] for x in rel], float)
    t_sec = (t - t[0]).total_seconds().to_numpy()

    # 平均運動 n 取自 primary 的平均半長軸
    altP = data.get("altP") or []
    a_km = (np.nanmean([x["a"] for x in altP]) + R_E) if altP else np.nan
    if not np.isfinite(a_km):
        raise ValueError("無法取得 primary 半長軸（altP 空）→ 無法定義平均運動 n")
    n = float(np.sqrt(MU / a_km ** 3))

    W = window_min * 60.0
    S = (stride_min if stride_min is not None else window_min / 3.0) * 60.0
    rows = []
    t0 = t_sec[0]
    while t0 + W <= t_sec[-1] + 1e-9:
        m = (t_sec >= t0) & (t_sec <= t0 + W)
        if m.sum() >= 8:                       # 6 未知數 → 至少 8 點才有冗餘
            tw = t_sec[m] - t0
            x0, resid, rms, rms_ax = fit_cw_window(tw, pos[m], n)
            rows.append({
                "t_mid": t[m][len(tw) // 2],
                "rms_km": rms, "rms_R": rms_ax[0], "rms_T": rms_ax[1], "rms_N": rms_ax[2],
                "d_km": float(dist[m].mean()), "n_pts": int(m.sum()),
            })
        t0 += S
    out = pd.DataFrame(rows)
    out.attrs["n_rad_s"] = n
    out.attrs["a_km"] = a_km
    out.attrs["period_min"] = 2 * np.pi / n / 60.0
    return out


def classify(res: pd.DataFrame, baseline_rms: float | None = None,
             k: float = 5.0, valid: dict | None = None) -> dict:
    """以殘差判定是否為受控接近。

    baseline_rms: 對照組（無 RPO）之殘差基線；None 則以自身中位數為基線
                  （自身基線較保守：若整段皆受控會低估）。
    k: 門檻倍數（相對基線）。
    valid: hcw_validity() 的結果。**前提不成立時一律拒絕判定**——線性化破壞後
           殘差反映的是 HCW 模型失效（分離過大），而非推力，此時任何判定都無意義。
           （實測：兩塊 CZ-6A 碎片 Δa=19km、4 天漂離 5683km，前提破壞下會被誤判為
           「受控接近」——碎片不可能機動。故此閘門為必要，不可只警告。）
    """
    if valid is not None and not valid.get("ok", True):
        return {"verdict": f"無法判定（HCW 前提不成立：最大分離 {valid['d_max']:.0f} km "
                           f"／軌道半徑 = {valid['ratio']:.0%} > {HCW_VALID_RATIO:.0%}）",
                "invalid": True, "n_flag": 0, "n_win": len(res),
                "baseline_km": float("nan"), "threshold_km": float("nan"),
                "peak_rms_km": float(res["rms_km"].max()) if len(res) else float("nan"),
                "peak_t": None, "peak_ratio": float("nan"),
                "self_median_km": float(res["rms_km"].median()) if len(res) else float("nan"),
                "peak_axis": {"R": float("nan"), "T": float("nan"), "N": float("nan")}}
    if res.empty:
        return {"verdict": "資料不足（視窗內取樣點不足，請縮小 --step-min 或加大 --window-min）",
                "n_flag": 0, "n_win": 0, "baseline_km": float("nan"),
                "threshold_km": float("nan"), "peak_rms_km": float("nan"),
                "peak_t": None, "peak_ratio": float("nan"), "self_median_km": float("nan"),
                "peak_axis": {"R": float("nan"), "T": float("nan"), "N": float("nan")}}
    self_med = float(res["rms_km"].median())
    base = baseline_rms if baseline_rms is not None else self_med
    thr = k * base
    flag = res["rms_km"] > thr
    peak = res.loc[res["rms_km"].idxmax()]
    ratio = float(res["rms_km"].max() / base) if base > 0 else float("inf")
    if flag.any():
        verdict = "受控接近（HCW 無法解釋的系統性偏離）"
    elif ratio > 2:
        verdict = "疑似受控（偏離未達門檻但高於基線）"
    else:
        verdict = "自然漂移（HCW 可解釋）"
    return {
        "verdict": verdict, "n_flag": int(flag.sum()), "n_win": len(res),
        "baseline_km": base, "threshold_km": thr,
        "peak_rms_km": float(peak["rms_km"]), "peak_t": peak["t_mid"],
        "peak_ratio": ratio, "self_median_km": self_med,
        "peak_axis": {"R": float(peak["rms_R"]), "T": float(peak["rms_T"]),
                      "N": float(peak["rms_N"])},
    }


HCW_VALID_RATIO = 0.05      # 分離量/軌道半徑 之上限（HCW 線性化前提）


def hcw_validity(data: dict) -> dict:
    """檢查 HCW 線性化前提：分離量須 << 軌道半徑。"""
    d = np.array([x["d"] for x in data["rel"]], float)
    altP = data.get("altP") or []
    a_km = (np.nanmean([x["a"] for x in altP]) + R_E) if altP else np.nan
    ratio = float(np.nanmax(d)) / a_km if np.isfinite(a_km) else float("nan")
    # 一律轉 Python 原生型別：np.bool_ 不繼承 bool，直接送進 jsonify 會 TypeError
    return {"a_km": float(a_km), "d_max": float(np.nanmax(d)), "ratio": float(ratio),
            "ok": bool(ratio <= HCW_VALID_RATIO)}


def analyze_pair(db: str, primary: int, secondary: int, step_min: float = 5.0,
                 window_min: float = 180.0, start=None, end=None,
                 around_tca_days: float | None = None):
    """around_tca_days：先粗掃找 TCA，再以 TCA ±N 天重取樣（HCW 僅在近距段有效）。"""
    from conjunction_viz import compute_pair_series
    if around_tca_days is not None and not (start or end):
        scan = compute_pair_series(db, primary, secondary, step_min=30.0)
        tca = pd.Timestamp(scan["summary"]["d_min_t"])
        start = (tca - pd.Timedelta(days=around_tca_days)).strftime("%Y-%m-%d")
        end = (tca + pd.Timedelta(days=around_tca_days)).strftime("%Y-%m-%d")
    data = compute_pair_series(db, primary, secondary, start=start, end=end,
                               step_min=step_min)
    res = hcw_residual_series(data, window_min=window_min)
    return data, res


def main():
    ap = argparse.ArgumentParser(description="HCW 殘差意圖研判（受控 RPO vs 自然漂移）")
    ap.add_argument("primary", type=int)
    ap.add_argument("secondary", type=int)
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--step-min", type=float, default=5.0, help="取樣步長（分）")
    ap.add_argument("--window-min", type=float, default=180.0, help="擬合視窗（分）")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--around-tca", type=float, default=None, metavar="DAYS",
                    help="自動以 TCA ±DAYS 開窗（HCW 僅在近距段有效，長窗必用）")
    ap.add_argument("--control", nargs=2, type=int, metavar=("P", "S"),
                    help="對照組 pair（無 RPO），用以校準殘差基線")
    ap.add_argument("--k", type=float, default=5.0, help="門檻倍數（相對基線）")
    args = ap.parse_args()

    base_rms = None
    if args.control:
        cp, cs = args.control
        print(f"── 對照組 {cp} × {cs}（校準基線）"
              + "─" * 30)
        try:
            _, cres = analyze_pair(args.db, cp, cs, args.step_min, args.window_min,
                                   args.start, args.end, args.around_tca)
            base_rms = float(cres["rms_km"].median())
            print(f"  視窗 {len(cres)}｜殘差 RMS 中位 {base_rms:.4f} km、"
                  f"P95 {cres['rms_km'].quantile(0.95):.4f} km、最大 {cres['rms_km'].max():.4f} km")
        except Exception as e:
            print(f"  對照組失敗（{e}）→ 改用自身中位數為基線")

    print(f"\n── 目標 {args.primary} × {args.secondary} " + "─" * 34)
    data, res = analyze_pair(args.db, args.primary, args.secondary, args.step_min,
                             args.window_min, args.start, args.end, args.around_tca)
    val = hcw_validity(data)
    if not val["ok"]:
        print(f"  ⚠ HCW 適用性不足：最大分離 {val['d_max']:.1f} km / 軌道半徑 "
              f"{val['a_km']:.1f} km = {val['ratio']:.1%} > {HCW_VALID_RATIO:.0%}"
              " → 線性化前提破壞，請用 --around-tca 限縮到近距段")
    m, s = data["meta"], data["summary"]
    print(f"  {m['primName']} × {m['secName']}｜窗 {s['n']} 點 @ {s['step_min']} 分"
          f"｜距離 {s['d_min']}~{s['d_max']} km（TCA {s['d_min_t'][:16]}）")
    print(f"  軌道週期 {res.attrs['period_min']:.1f} 分、擬合視窗 {args.window_min:.0f} 分"
          f"（{args.window_min / res.attrs['period_min']:.1f} 圈）、視窗數 {len(res)}")

    v = classify(res, base_rms, k=args.k, valid=val)
    if v.get("invalid"):
        print("\n  ▶ 判定：" + v["verdict"])
        print("    （殘差反映 HCW 模型失效而非推力，故不輸出判讀。"
              "共軌對才適用——無控制物體只要有 Δa 就會沿跡漂離。）")
        return
    print(f"\n  殘差 RMS：中位 {v['self_median_km']:.4f}、峰值 {v['peak_rms_km']:.4f} km"
          f"（{str(v['peak_t'])[:16]}）")
    print(f"  基線 {v['baseline_km']:.4f} km（{'對照組' if base_rms else '自身中位'}）"
          f"、門檻 {v['threshold_km']:.4f} km（{args.k:g}×）")
    print(f"  峰值/基線 = {v['peak_ratio']:.1f}×｜超門檻視窗 {v['n_flag']}/{v['n_win']}")
    print(f"  峰值分軸殘差：R {v['peak_axis']['R']:.4f}、T {v['peak_axis']['T']:.4f}、"
          f"N {v['peak_axis']['N']:.4f} km")
    print(f"\n  ▶ 判定：{v['verdict']}")

    out = Path("data/benchmark") / f"hcw_resid_{args.primary}_{args.secondary}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n  殘差序列 → {out}")


if __name__ == "__main__":
    main()
