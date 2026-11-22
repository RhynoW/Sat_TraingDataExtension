"""太空兵棋想定 D「直升式反衛星」的蒙地卡羅推演。

想定依據：DIA《Challenges to Security in Space 2026》繁中譯本（頁碼為譯本頁碼）
- p.32：PLA 準則多將 ASAT 飛彈描述為威懾外部介入或管理衝突升高的手段；2007 年中國以 ASAT 飛彈摧毀 800 km 以上的
  退役氣象衛星，產生超過 3,500 塊可追蹤碎片，超過 2,400 塊仍在軌；若在衝突中使用，中國必須應對碎片威脅自身與中立方系統
- p.44：俄羅斯 Nudol 2021 年 11 月在 470 km 摧毀退役衛星，產生超過 1,700 塊可追蹤碎片與數萬塊無法追蹤的碎片
- p.15：ASAT 飛彈的碎片可在軌道上停留數十年甚至數世紀
- p.56：碎片越多，避碰越困難、任務成本越高；碎片壽命取決於尺寸與高度
- p.70：地基 ASAT 飛彈的發射可被偵測、會產生碎片，較其他反太空武器容易歸因
- p.57：商業衛星影像的可得性提高
效果數值（碎片每單位低軌 −10%、避碰時 −5%、聲望 +3、紅方出手機率與目標選擇）是本遊戲的示意假設，不是 DIA 數據。

用法（repo 根目錄，需另開一個含想定 D 的 SatDashboard 實例）：
  python docs/book/sim_wargame/scenario_d/run_scenario_d.py --server http://127.0.0.1:5091 [--runs 500]
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
BLUE_BASE = ["balanced", "geo", "leo", "repair"]
BLUE_D = BLUE_BASE + ["imagery", "avoid"]
RED = ["balanced", "escalate"]
SCEN = ["base", "d", "d_noasat"]
N_BLUE = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜",
          "imagery": "重 GEO＋商業影像", "avoid": "均衡＋避碰"}
N_RED = {"balanced": "紅方：灰色地帶", "escalate": "紅方：升級"}
N_SCEN = {"base": "原始想定", "d": "想定 D", "d_noasat": "D 對照（紅方不用反衛星）"}


def post(server, path, body):
    r = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=600))


def get(server, path):
    return json.load(urllib.request.urlopen(server.rstrip("/") + path, timeout=60))


def run(server, runs):
    rows = []
    for sc in SCEN:
        blue = BLUE_BASE if sc == "base" else BLUE_D   # 商業影像、避碰只在想定 D 有意義
        for red in RED:
            d = post(server, "/api/games/war/mc", {"runs": runs, "blue": blue, "red": red, "scenario": sc})
            assert d["scenario"] == sc, d["scenario"]
            for r in d["results"]:
                rows.append({"scenario": sc, "red": red, "runs": d["runs"], **r})
            print(f"{N_SCEN[sc]}／{N_RED[red]}：完成")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)

    # 敘事範例：同一種子，重 GEO 與重 GEO＋商業影像，對灰色地帶與升級紅方各一局
    ex = {}
    for b in ("geo", "imagery"):
        for red in RED:
            g = post(server, "/api/games/war/new", {"seed": 1001, "ai_blue": b, "ai_red": red, "scenario": "d"})
            st = get(server, f"/api/games/war/state?id={g['id']}&role=white")
            ex[f"d_{b}_vs_{red}"] = {"log": st["log"], "history": st["history"], "scores": st["scores"]}
    (HERE / "example_game_seed1001.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


def summarize(df):
    out = []
    for red in RED:
        out.append(f"\n### {N_RED[red]}\n")
        out.append("| 藍方策略 | 頻寬：D 對照 | 頻寬：D | 反衛星試射 | 光學衛星被毀 | 偵察成功：D 對照 | 偵察成功：D | 升級指數（對照→D） | 藍方分數（對照→D） | 紅方分數（對照→D） |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for b in BLUE_D:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            d, n = x.loc["d"], x.loc["d_noasat"]
            out.append(f"| {N_BLUE[b]} | {n.mean_avail:.1%} | {d.mean_avail:.1%} ± {d.ci95:.1%} | {d.asat_rate:.0%} | {d.isr_sat_lost:.0%} | "
                       f"{n.isr_ok:.2f} | {d.isr_ok:.2f} | {n.escalation:.1f} → {d.escalation:.1f} | {n.blue_score:.1f} → {d.blue_score:.1f} | {n.red_score:.1f} → {d.red_score:.1f} |")
        # 原始想定的升級紅方本來就有反衛星（打低軌、無目標選擇），列出來對照
        if red == "escalate":
            out.append("")
            out.append("| 藍方策略 | 原始想定：頻寬 | 原始想定：反衛星試射 | 原始想定：偵察成功 |")
            out.append("|---|---|---|---|")
            for b in BLUE_BASE:
                o = df[(df.red == red) & (df.blue == b) & (df.scenario == "base")].iloc[0]
                out.append(f"| {N_BLUE[b]} | {o.mean_avail:.1%} | {o.asat_rate:.0%} | {o.isr_ok:.2f} |")
    s = "\n".join(out)
    print(s)
    (HERE / "summary.md").write_text("# 想定 D 推演摘要表（由 run_scenario_d.py 產生）\n" + s + "\n", encoding="utf-8")


def plot(df):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"
    C_D, C_N = "#eb6834", "#8d8c86"
    ys = list(range(len(BLUE_D)))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.0), dpi=200, sharey=True)
    for ax, red in zip(axes, RED):
        g = lambda sc: df[(df.red == red) & (df.scenario == sc)].set_index("blue").loc[BLUE_D]
        xd, xn = g("d"), g("d_noasat")
        for y, b in zip(ys, BLUE_D):
            ax.plot([xn.loc[b, "isr_ok"], xd.loc[b, "isr_ok"]], [y, y], color=GRID, lw=2, zorder=1)
        ax.scatter(xd.isr_ok, ys, s=60, color=C_D, edgecolor="white", lw=1.5, zorder=5, label="想定 D")
        ax.scatter(xn.isr_ok, ys, s=22, color=C_N, edgecolor="white", lw=1.0, zorder=6, label="D 對照：紅方不用反衛星（小灰點，疊在上層）")
        for y, b in zip(ys, BLUE_D):
            ax.text(5.6, y, f"光學衛星被毀 {xd.loc[b, 'isr_sat_lost']:.0%}", va="center", fontsize=7.2, color=INK)
        ax.set_xlim(-0.3, 7.6)
        ax.set_ylim(len(BLUE_D) - 0.5, -0.6)
        ax.set_title(N_RED[red] + "：光學偵察成功次數（8 回合）", color=INK, fontsize=9.5, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, length=0)
        ax.set_xticks([0, 1, 2, 3, 4, 5])
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([N_BLUE[b] for b in BLUE_D], color=INK)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=8, loc="lower center", ncol=2)
    fig.suptitle("想定 D：反衛星打掉的是偵察，商業影像備援讓這一擊落空（各 500 局平均）",
                 color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(HERE / "scenario_d_isr.png")
    print("圖：", HERE / "scenario_d_isr.png")


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
