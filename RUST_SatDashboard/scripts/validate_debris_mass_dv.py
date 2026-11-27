"""外部審查 3.1：Cosmos 1408 雙因子敏感度（質量縮放 × Δv 截斷），編目等效 n=1,647、L ≥ 10 cm、30 個種子。
用法：py -3.13 scripts/validate_debris_mass_dv.py（需先以 --port 5099 啟動單機版）"""
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import numpy as np
import validate_debris as V
URL = "http://127.0.0.1:5099"; SEEDS = 30; rng = np.random.default_rng(0)
cases = [("縮放＋不截斷（SBM 原始）", {"dv_sigma_max": 10.0, "mass_rescale": True}),
         ("縮放＋截斷 1σ（v0.1.19 校準）", {"dv_sigma_max": 1.0, "mass_rescale": True}),
         ("不縮放＋不截斷", {"dv_sigma_max": 10.0, "mass_rescale": False}),
         ("不縮放＋截斷 1σ", {"dv_sigma_max": 1.0, "mass_rescale": False})]
out = {}
for name, extra in cases:
    per = {y: [] for y in V.YEARS}; half = []; err = []; am = []
    for seed in range(1, SEEDS + 1):
        d = V.post(URL, dict(V.COSMOS, seed=seed, n_frag=V.N_CAT, **extra))
        s, h = V.survival(d, 0.1)
        for y in V.YEARS: per[y].append(s[y])
        half.append(h); err.append(V.log_err(s))
        am.append(float(np.median([f[4] for f in d["frags"] if f[2] == 1 and f[3] >= 0.1])))
    out[name] = {"params": extra, "years": {y: V.stats(per[y], rng) for y in V.YEARS}, "half_days": V.stats(half, rng),
                 "log_err": V.stats(err, rng), "am_median": V.stats(am, rng), "model_version": d["model_version"]}
    r = out[name]
    print(f"{name}: " + "，".join(f"第{y}年 {r['years'][y]['median']:.1f}%［{r['years'][y]['q1']:.1f}–{r['years'][y]['q3']:.1f}］" for y in V.YEARS)
          + f"，剩一半 {r['half_days']['median']:.0f} 天，log 誤差 {r['log_err']['median']:.3f}，A/M 中位數 {r['am_median']['median']:.4f} m²/kg", flush=True)
json.dump(out, open("validate_debris_mass_dv.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
