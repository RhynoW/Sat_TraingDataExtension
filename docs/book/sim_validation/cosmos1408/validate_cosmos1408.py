"""碎片連鎖遊戲的衰減驗證：Cosmos 1408 反衛星試射碎片（2021-11-15）。

比對對象
- 觀測：CelesTrak SATCAT，國際編號 1982-092 的碎片（NORAD ≥ 49000，即 2021 年試射產生者），用再入日期算存活曲線。
- 模擬：Rust 單機版「碎片連鎖」後端 POST /api/games/breakup，自訂圓軌道 480 km／82.6°、2,200 kg、
  1,000 個碎片、寫實倍率 ×1、5 年；碰撞與爆炸模型各跑 5 個種子。

用法（repo 根目錄）：
  python docs/book/sim_validation/cosmos1408/validate_cosmos1408.py [--server http://127.0.0.1:5091]
  有 --server 時重跑模擬並更新 sim_deaths.csv；沒有時沿用既有 sim_deaths.csv。
  satcat_1982-092.csv 取自 https://celestrak.org/satcat/records.php?INTDES=1982-092&FORMAT=CSV
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
T0 = pd.Timestamp("2021-11-15")
R_E = 6378.137
ANCHOR_D = 15          # 觀測第一筆再入在第 15 天；兩邊都以第 15 天仍在軌者為 100%
HORIZON_D = 5 * 365    # 比對到第 5 年
SEEDS = [1, 2, 3, 4, 5]
APO_CAP = 1200       # 敏感度檢驗的遠地點上限（km）


def run_sims(server: str) -> pd.DataFrame:
    rows = []
    for model in (True, False):
        for seed in SEEDS:
            req = {"norad": 0, "orbit": {"alt_km": 480, "inc_deg": 82.6, "name": "Cosmos 1408"},
                   "mass_kg": 2200, "n_frag": 1000, "collision": model, "years": 5, "accel": 1,
                   "seed": seed, "actions": []}
            r = urllib.request.Request(server.rstrip("/") + "/api/games/breakup",
                                       data=json.dumps(req).encode(), headers={"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(r, timeout=300))
            fr, de = np.array(d["frags"]), np.array(d["deaths"])
            for k in range(len(fr)):
                if fr[k, 2] > 1:      # 只取第一次解體的碎片（本情境寫實倍率下沒有後代）
                    continue
                a, e = fr[k, 5], fr[k, 6]
                rows.append({"model": "collision" if model else "explosion", "seed": seed, "frag": int(fr[k, 0]),
                             "perigee_km": round(a * (1 - e) - R_E, 1), "apogee_km": round(a * (1 + e) - R_E, 1),
                             "am_m2kg": fr[k, 4],
                             "death_day": -1.0 if de[k] < 0 else round((de[k] - fr[k, 1]) / 86400, 3)})
            print(f"模擬 {'碰撞' if model else '爆炸'} 種子 {seed}：{d['summary']['fragments_total']} 個碎片，"
                  f"期末在軌 {d['summary']['alive_end']}，{d['elapsed_s']:.1f} 秒")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "sim_deaths.csv", index=False)
    return df


def survival(death_day: np.ndarray, days: np.ndarray) -> np.ndarray:
    """death_day = -1 表示期末仍在軌。回傳以第 ANCHOR_D 天在軌數為分母的存活比例。"""
    dd = np.where(death_day < 0, np.inf, death_day)
    base = (dd > ANCHOR_D).sum()
    return np.array([(dd > t).sum() for t in days]) / base, base


def t_at(frac_curve: np.ndarray, days: np.ndarray, level: float) -> float:
    idx = np.argmax(frac_curve <= level)
    return float(days[idx]) if frac_curve[idx] <= level else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    args = ap.parse_args()
    sim = run_sims(args.server) if args.server else pd.read_csv(HERE / "sim_deaths.csv")

    sc = pd.read_csv(HERE / "satcat_1982-092.csv")
    deb = sc[(sc.OBJECT_TYPE == "DEB") & (sc.NORAD_CAT_ID >= 49000)]
    obs_dd = ((pd.to_datetime(deb.DECAY_DATE) - T0).dt.days).fillna(-1).to_numpy(float)
    days = np.arange(ANCHOR_D, HORIZON_D + 1)
    obs_s, obs_n = survival(obs_dd, days)

    curves = {"observed": obs_s}
    meta = {"observed": {"n": int(obs_n), "dead_at_birth": 0}}
    for model in ("collision", "explosion"):
        ss = []
        for seed in SEEDS:
            x = sim[(sim.model == model) & (sim.seed == seed)]
            s, n = survival(x.death_day.to_numpy(float), days)
            ss.append(s)
        ss = np.array(ss)
        curves[model] = ss.mean(0)
        curves[model + "_min"], curves[model + "_max"] = ss.min(0), ss.max(0)
        # 敏感度：排除出生遠地點 > APO_CAP 的碎片（真實長壽碎片的遠地點見報告）
        sa = []
        for seed in SEEDS:
            x = sim[(sim.model == model) & (sim.seed == seed) & (sim.apogee_km <= APO_CAP)]
            sa.append(survival(x.death_day.to_numpy(float), days)[0])
        curves[model + "_apocap"] = np.array(sa).mean(0)
        x = sim[sim.model == model]
        meta[model + "_apocap_share_removed"] = float((x.apogee_km > APO_CAP).mean())
        meta[model] = {"n": int(round(len(x) / len(SEEDS))),
                       "dead_by_anchor": float(((x.death_day >= 0) & (x.death_day <= ANCHOR_D)).mean())}

    # 阻力尺度因子 k：只有阻力時 da/dt ∝ ρ·(A/M)，ρ·(A/M) 全體乘 k 等同時間軸除以 k。
    # 以模擬碰撞曲線 S_sim(t·k) 擬合觀測 S_obs(t)，最小化存活比例的均方根差。
    def scaled(curve, k):
        return np.interp(ANCHOR_D + (days - ANCHOR_D) * k, days, curve, right=curve[-1])
    ks = np.round(np.arange(0.5, 6.01, 0.01), 2)
    fit = {}
    for model in ("collision", "explosion"):
        rms = [np.sqrt(np.mean((scaled(curves[model], k) - obs_s) ** 2)) for k in ks]
        kb = float(ks[int(np.argmin(rms))])
        fit[model] = {"k": kb, "rms": float(min(rms)), "rms_k1": float(rms[list(ks).index(1.0)])}
        curves[model + "_fit"] = scaled(curves[model], kb)

    out = pd.DataFrame({"day": days, **{k: np.round(v, 4) for k, v in curves.items()}})
    out.to_csv(HERE / "survival_curves.csv", index=False)

    # 摘要表
    lines = []
    lines.append("| 指標 | 觀測（SATCAT） | 模擬：碰撞模型 | 模擬：爆炸模型 |")
    lines.append("|---|---|---|---|")
    for lv in (0.5, 0.25, 0.10, 0.05):
        lines.append(f"| 剩 {int(lv*100)}% 的天數 | {t_at(obs_s, days, lv):.0f} | "
                     f"{t_at(curves['collision'], days, lv):.0f} | {t_at(curves['explosion'], days, lv):.0f} |")
    for yr in (1, 2, 3, 5):
        i = min(yr * 365, HORIZON_D) - ANCHOR_D
        lines.append(f"| 第 {yr} 年存活比例 | {obs_s[i]:.1%} | {curves['collision'][i]:.1%}"
                     f"（{curves['collision_min'][i]:.1%}–{curves['collision_max'][i]:.1%}） | "
                     f"{curves['explosion'][i]:.1%}（{curves['explosion_min'][i]:.1%}–{curves['explosion_max'][i]:.1%}） |")
    for yr in (1, 2, 3):
        i = yr * 365 - ANCHOR_D
        lines.append(f"| 第 {yr} 年存活比例，排除遠地點 > {APO_CAP} km | {obs_s[i]:.1%} | "
                     f"{curves['collision_apocap'][i]:.1%} | {curves['explosion_apocap'][i]:.1%} |")
    lines.append(f"| 均方根差（k = 1，原模型） | — | {fit['collision']['rms_k1']:.3f} | {fit['explosion']['rms_k1']:.3f} |")
    lines.append(f"| 最佳阻力尺度因子 k | — | {fit['collision']['k']:.2f}（均方根差 {fit['collision']['rms']:.3f}） | "
                 f"{fit['explosion']['k']:.2f}（均方根差 {fit['explosion']['rms']:.3f}） |")
    summary = "\n".join(lines)
    print(summary)
    print(json.dumps({"meta": meta, "fit": fit}, ensure_ascii=False, indent=1))
    (HERE / "summary.json").write_text(json.dumps({"meta": meta, "fit": fit, "table_md": summary},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    plot(out, fit, meta)


def plot(out: pd.DataFrame, fit: dict, meta: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"
    C_OBS, C_COL, C_EXP = "#1f1f1e", "#2a78d6", "#eb6834"
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=200)
    yr = out.day / 365.25
    ax.fill_between(yr, out.collision_min * 100, out.collision_max * 100, color=C_COL, alpha=0.15, lw=0)
    ax.fill_between(yr, out.explosion_min * 100, out.explosion_max * 100, color=C_EXP, alpha=0.15, lw=0)
    ax.plot(yr, out.observed * 100, color=C_OBS, lw=2.2, label=f"觀測：SATCAT 編目碎片（{meta['observed']['n']:,} 件）")
    ax.plot(yr, out.collision * 100, color=C_COL, lw=2, label="模擬：碰撞模型（5 種子平均與範圍）")
    ax.plot(yr, out.explosion * 100, color=C_EXP, lw=2, label="模擬：爆炸模型（5 種子平均與範圍）")
    ax.plot(yr, out.collision_apocap * 100, color=C_COL, lw=1.6, ls=(0, (4, 3)),
            label=f"碰撞模型，排除遠地點 > {APO_CAP:,} km 的碎片（敏感度）")
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 100)
    ax.set_xlabel("試射後年數（2021-11-15 起）", color=MUTED)
    ax.set_ylabel("仍在軌比例（%，以第 15 天為 100%）", color=MUTED)
    ax.grid(axis="y", color=GRID, lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED)
    leg = ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK)
    ax.set_title("Cosmos 1408 碎片的衰減：觀測與碎片連鎖模擬", color=INK, fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(HERE / "cosmos1408_survival.png")
    print("圖：", HERE / "cosmos1408_survival.png")


if __name__ == "__main__":
    main()
