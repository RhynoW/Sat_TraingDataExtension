"""太空兵棋想定 A「灰色地帶：海纜中斷，商用低軌也被干擾」的蒙地卡羅推演。

想定依據：DIA《Challenges to Security in Space 2026》繁中譯本（頁碼為譯本頁碼）
- p.4、37：俄方以干擾器攻擊商業星座，並將支援烏克蘭的商業終端與衛星列為合法軍事目標
- p.43：2022-02-24 入侵前，惡意軟體攻擊 Viasat 客戶，5 萬名使用者斷線；俄方宣稱以 Tirada 干擾 Starlink
- p.15–16、68：網攻效果可由可逆到不可逆；尾註 621：Viasat 數據機遭 AcidRain 抹除
效果數值（1,000 套預置終端、抹除 30%、干擾 25%）是本遊戲的示意假設，不是 DIA 數據。

用法（repo 根目錄，需另開一個含想定 A 的 SatDashboard 實例）：
  python docs/book/sim_wargame/scenario_a/run_scenario_a.py --server http://127.0.0.1:5091 [--runs 500]
沒有 --server 時只用既有 results.csv 重畫圖與摘要。
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
BLUE = ["balanced", "geo", "leo", "repair"]
RED = ["balanced", "escalate"]
SCEN = ["base", "a_pre", "a", "a_nojam", "a_nocyber"]
N_BLUE = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜"}
N_RED = {"balanced": "紅方：灰色地帶", "escalate": "紅方：升級（含反衛星）"}
N_SCEN = {"base": "原始想定", "a_pre": "對照：只預置終端", "a": "想定 A", "a_nojam": "A 去掉開場干擾", "a_nocyber": "A 去掉網攻抹除"}


def post(server, path, body):
    r = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=600))


def get(server, path):
    return json.load(urllib.request.urlopen(server.rstrip("/") + path, timeout=60))


def run(server, runs):
    rows = []
    for sc in SCEN:
        for red in RED:
            d = post(server, "/api/games/war/mc", {"runs": runs, "blue": BLUE, "red": red, "scenario": sc})
            assert d["scenario"] == sc, d["scenario"]
            for r in d["results"]:
                rows.append({"scenario": sc, "red": red, "runs": d["runs"], **r})
            print(f"{N_SCEN[sc]}／{N_RED[red]}：完成")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)

    # 敘事範例：一局完整紀錄（雙方 AI 均衡／灰色地帶，固定種子）
    ex = {}
    for sc in ("a_pre", "a"):
        g = post(server, "/api/games/war/new", {"seed": 1001, "ai_blue": "balanced", "ai_red": "balanced", "scenario": sc})
        st = get(server, f"/api/games/war/state?id={g['id']}&role=white")
        ex[sc] = {"log": st["log"], "history": st["history"], "scores": st["scores"]}
    (HERE / "example_game_seed1001.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


def summarize(df):
    out = []
    for red in RED:
        out.append(f"\n### {N_RED[red]}\n")
        out.append("| 藍方策略 | " + " | ".join(N_SCEN[s] for s in SCEN) + " | 攻擊代價（A − 對照） |")
        out.append("|---|" + "---|" * (len(SCEN) + 1))
        for b in BLUE:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            cells = [f"{x.loc[s, 'mean_avail']:.1%} ± {x.loc[s, 'ci95']:.1%}" for s in SCEN]
            d = (x.loc["a", "mean_avail"] - x.loc["a_pre", "mean_avail"]) * 100
            out.append(f"| {N_BLUE[b]} | " + " | ".join(cells) + f" | {d:+.1f} 個百分點 |")
        out.append("")
        out.append("| 藍方策略 | 前 3 回合（對照→A） | 最差 10%（對照→A） | 曾低於 50%（對照→A） | 網攻損失終端（A） | 升級指數（對照→A） |")
        out.append("|---|---|---|---|---|---|")
        for b in BLUE:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            o, a = x.loc["a_pre"], x.loc["a"]
            out.append(f"| {N_BLUE[b]} | {o.early_avail:.1%} → {a.early_avail:.1%} | {o.p10:.1%} → {a.p10:.1%} | "
                       f"{o.p_low:.1%} → {a.p_low:.1%} | {a.cyber_lost:,.0f} 套 | {o.escalation:.1f} → {a.escalation:.1f} |")
    s = "\n".join(out)
    print(s)
    (HERE / "summary.md").write_text("# 想定 A 推演摘要表（由 run_scenario_a.py 產生）\n" + s + "\n", encoding="utf-8")


def plot(df):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"
    C = {"a_pre": "#2a78d6", "a": "#eb6834"}
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.2), dpi=200, sharey=True, sharex=True)
    for ax, red in zip(axes, RED):
        for j, sc in enumerate(("a_pre", "a")):
            x = df[(df.red == red) & (df.scenario == sc)].set_index("blue").loc[BLUE]
            ys = range(len(BLUE))
            off = [y + (-0.12 if j == 0 else 0.12) for y in ys]
            ax.errorbar(x.mean_avail * 100, off, xerr=x.ci95 * 100, fmt="o", ms=7, color=C[sc], ecolor=C[sc],
                        elinewidth=2, capsize=0, label=N_SCEN[sc], mec="white", mew=1.5)
            for xv, yv in zip(x.mean_avail * 100, off):
                ax.text(xv + (1.2 if sc == "a_pre" else -1.2), yv, f"{xv:.1f}", va="center",
                        ha="left" if sc == "a_pre" else "right", fontsize=8, color=INK)
        ax.set_yticks(range(len(BLUE)))
        ax.set_yticklabels([N_BLUE[b] for b in BLUE], color=INK)
        ax.invert_yaxis()
        ax.set_title(N_RED[red], color=INK, fontsize=10, loc="left")
        ax.set_xlabel("8 回合平均頻寬可用率（%，點為 500 局平均，線為 95% 信賴區間）", color=MUTED, fontsize=8)
        ax.grid(axis="x", color=GRID, lw=0.8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, length=0)
    lo = (df[df.scenario.isin(["a_pre", "a"])].mean_avail.min() * 100) // 5 * 5 - 5
    axes[0].set_xlim(lo, 100)
    axes[0].legend(frameon=False, fontsize=8.5, loc="lower left")
    fig.suptitle("想定 A：同樣有 1,000 套商用終端，被干擾與抹除後各策略的頻寬可用率", color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(HERE / "scenario_a_avail.png")
    print("圖：", HERE / "scenario_a_avail.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    ap.add_argument("--runs", type=int, default=500)
    a = ap.parse_args()
    df = run(a.server, a.runs) if a.server else pd.read_csv(HERE / "results.csv")
    summarize(df)
    plot(df)


if __name__ == "__main__":
    main()
