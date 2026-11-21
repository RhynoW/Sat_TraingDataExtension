"""碎片連鎖的驗證腳本（架構說明 6.1）：Cosmos 1408 衰減、多種子統計、太陽活動單調性、密度敏感度。

需要一個執行中的 SatDashboard（例如 target\\release\\SatDashboard.exe --port 5099 --no-browser --no-update）。

用法（在 RUST_SatDashboard 目錄）：
  py -3.13 scripts/validate_debris.py --url http://127.0.0.1:5099 --seeds 30 --out validate.json
  py -3.13 scripts/validate_debris.py --only mono       # 只跑某一組（cosmos／mono／sens）

方法：
- 存活比例 = 第 t 年仍在軌的第一代碎片 ÷ 第 15 天仍在軌的第一代碎片（扣掉出生後很快再入、來不及編目的碎片），與驗證報告一致。
- 觀測：CelesTrak SATCAT 編目的 1,805 件 2021-11-15 試射碎片（docs/book/sim_validation/cosmos1408/ 的驗證報告）。
- 編目等效：觀測只含可追蹤（約 10 cm 以上）的碎片。碰撞模型 N(>L) = 0.1·M^0.75·L^−1.71，M = 2,200 kg 時
  L ≥ 10 cm 約 1,657 個，因此以 n_frag = 1,657 模擬，再只取 L ≥ 10 cm 的碎片（等於 Lc = 10 cm 的完整族群）。
- 統計：每組 N 個種子，報告中位數、四分位距（IQR）與中位數的 bootstrap 95% 區間（2,000 次重抽）。
- 誤差指標：第 1、2、3、5 年 |log₁₀(模擬 ÷ 觀測)| 的平均（對數尺度，0.2% 與 25% 一樣重要）。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request

import numpy as np

R = 6378.137
OBS = {1: 25.3, 2: 4.8, 3: 0.9, 5: 0.2}
OBS_HALF = 192
YEARS = (1, 2, 3, 5)
N_CAT = round(0.1 * 2200 ** 0.75 * 0.1 ** -1.71)   # 1,657
COSMOS = {"orbit": {"alt_km": 480, "inc_deg": 82.6, "name": "Cosmos 1408"}, "mass_kg": 2200, "collision": True,
          "years": 5, "accel": 1, "solar": "series", "epoch": "2021-11-15"}


def post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    for _ in range(200):
        rq = urllib.request.Request(url + "/api/games/breakup", data, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=900) as f:
                return json.loads(f.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3)
                continue
            raise RuntimeError(f"{e.code} {e.read().decode('utf-8', 'replace')}") from e
    raise RuntimeError("伺服器一直忙碌")


def survival(d: dict, l_min: float = 0.0) -> tuple[dict[int, float], float]:
    """(各年存活百分比, 剩一半的天數)；只取第一代、L ≥ l_min 的碎片。"""
    deaths = [x for i, (f, x) in enumerate(zip(d["frags"], d["deaths"])) if f[2] == 1 and f[3] >= l_min]
    dd = np.array([math.inf if x < 0 else x / 86400 for x in deaths])
    n15 = max((dd > 15).sum(), 1)
    s = {y: 100.0 * (dd > y * 365.25).sum() / n15 for y in YEARS}
    alive = np.sort(dd[dd > 15])
    half = float(alive[len(alive) // 2]) if len(alive) else math.nan   # 第 15 天存活者的中位壽命
    return s, min(half, 5 * 365.25)


def stats(v: list[float], rng: np.random.Generator) -> dict:
    a = np.array(v, dtype=float)
    boot = np.median(rng.choice(a, (2000, len(a))), axis=1)
    return {"median": float(np.median(a)), "q1": float(np.percentile(a, 25)), "q3": float(np.percentile(a, 75)),
            "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)), "n": len(a)}


def log_err(s: dict[int, float]) -> float:
    return float(np.mean([abs(math.log10(max(s[y], 0.01) / OBS[y])) for y in YEARS]))


def run_cosmos(url: str, seeds: int, rng: np.random.Generator) -> dict:
    cases = [
        ("v0.1.18 基準（Ap 固定 15、n = 1,000）", {"n_frag": 1000, "ap_fixed": 15}, 0.0),
        ("Ap 驅動（n = 1,000）", {"n_frag": 1000}, 0.0),
        ("編目等效（L ≥ 10 cm）", {"n_frag": N_CAT}, 0.1),
        ("編目等效＋Δv 截斷 2σ", {"n_frag": N_CAT, "dv_sigma_max": 2.0}, 0.1),
        ("編目等效＋Δv 截斷 1.5σ", {"n_frag": N_CAT, "dv_sigma_max": 1.5}, 0.1),
        ("編目等效＋Δv 截斷 1σ", {"n_frag": N_CAT, "dv_sigma_max": 1.0}, 0.1),
        ("編目等效＋不截斷（明確指定）", {"n_frag": N_CAT, "dv_sigma_max": 10.0}, 0.1),
    ]
    out = {}
    for name, extra, lmin in cases:
        per = {y: [] for y in YEARS}
        half, err = [], []
        for seed in range(1, seeds + 1):
            d = post(url, dict(COSMOS, seed=seed, **extra))
            s, h = survival(d, lmin)
            for y in YEARS:
                per[y].append(s[y])
            half.append(h)
            err.append(log_err(s))
        mean_s = {y: float(np.mean(per[y])) for y in YEARS}
        out[name] = {"params": extra, "l_min": lmin, "years": {y: stats(per[y], rng) for y in YEARS},
                     "half_days": stats(half, rng), "log_err": stats(err, rng), "log_err_of_mean": log_err(mean_s),
                     "model_version": d["model_version"], "per_seed": {str(y): per[y] for y in YEARS}}
        r = out[name]
        print(f"{name}: " + "，".join(f"第{y}年 {r['years'][y]['median']:.1f}%" for y in YEARS)
              + f"，剩一半 {r['half_days']['median']:.0f} 天，log 誤差 {r['log_err']['median']:.3f}", flush=True)
    return out


def run_mono(url: str, seeds: int) -> dict:
    """低／中／高固定太陽活動：同一種子下，F10.7 越高，衰減越快、期望碰撞越少。"""
    res = {m: {"s1": [], "alive_end": [], "gen1": []} for m in ("low", "mid", "high")}
    for seed in range(1, seeds + 1):
        for m in res:
            d = post(url, dict(COSMOS, seed=seed, n_frag=1000, solar=m))
            s, _ = survival(d)
            res[m]["s1"].append(s[1])
            res[m]["alive_end"].append(d["summary"]["alive_end"])
            res[m]["gen1"].append(d["summary"]["expected_gen1_real"])
    viol = {k: sum(1 for i in range(seeds) if not (res["low"][k][i] >= res["mid"][k][i] >= res["high"][k][i])) for k in ("s1", "alive_end", "gen1")}
    for m in res:
        print(f"{m}: 第1年存活中位數 {np.median(res[m]['s1']):.1f}%、期末在軌 {np.median(res[m]['alive_end']):.0f}、第一代風險 {np.median(res[m]['gen1']):.4f}")
    print(f"違反單調（低 ≥ 中 ≥ 高）的種子數：{viol}（共 {seeds} 個）", flush=True)
    return {"by_mode": res, "violations": viol, "seeds": seeds}


def run_sens(url: str, seeds: int, rng: np.random.Generator, extra: dict) -> dict:
    """密度整體 ×0.85／×1.15（涵蓋沿軌跡取樣與全球平均的差異，見 gen_solar_tables.py --track）。"""
    out = {}
    for k in (0.85, 1.0, 1.15):
        per = {y: [] for y in YEARS}
        for seed in range(1, seeds + 1):
            d = post(url, dict(COSMOS, seed=seed, n_frag=N_CAT, rho_scale=k, **extra))
            s, _ = survival(d, 0.1)
            for y in YEARS:
                per[y].append(s[y])
        out[str(k)] = {y: stats(per[y], rng) for y in YEARS}
        print(f"密度 ×{k}: " + "，".join(f"第{y}年 {out[str(k)][y]['median']:.1f}%" for y in YEARS), flush=True)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5099")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--only", choices=["cosmos", "mono", "sens"])
    ap.add_argument("--sens-dv", type=float, help="敏感度測試使用的 Δv 截斷點（預設用後端預設值）")
    ap.add_argument("--out", default="validate.json")
    a = ap.parse_args()
    rng = np.random.default_rng(20211115)
    res: dict = {"observed": OBS, "observed_half_days": OBS_HALF, "seeds": a.seeds, "n_catalog_equiv": N_CAT}
    t0 = time.time()
    if a.only in (None, "cosmos"):
        res["cosmos"] = run_cosmos(a.url, a.seeds, rng)
    if a.only in (None, "mono"):
        res["mono"] = run_mono(a.url, a.seeds)
    if a.only in (None, "sens"):
        res["sens"] = run_sens(a.url, a.seeds, rng, {"dv_sigma_max": a.sens_dv} if a.sens_dv else {})
    res["elapsed_s"] = time.time() - t0
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"完成（{res['elapsed_s'] / 60:.1f} 分鐘）→ {a.out}")


if __name__ == "__main__":
    main()
