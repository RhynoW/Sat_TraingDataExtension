"""太空兵棋想定 C「共軌接近」的蒙地卡羅推演。

想定依據：DIA《Challenges to Security in Space 2026》繁中譯本（頁碼為譯本頁碼）
- p.33：TJS-3 宣稱為實驗通信衛星，2023 年多次在 GEO 接近他國太空器至不足 10 公里；
  這些近距離接近大多與宣稱任務不一致，顯示中國可能掩飾其真正任務。實踐十七號具機械臂，此類系統可用於抓取其他衛星
- p.44：Cosmos 2543 跟蹤美國國家安全衛星，並以足以造成潛在危險的距離多次接近；2020 年離開後向軌道發射投射物；
  Cosmos 2576 被送入與另一顆美國國家安全衛星相同的軌道
- p.64：沒有先進太空追蹤感測器的國家，可透過購買商業資料獲得基本 SDA
- p.71：天基武器可攻擊其他太空器、造成暫時或永久損害；衛星服務與碎片清除的機器人技術同時具和平用途與 ASAT 應用
效果數值（被攻擊時 GEO 損失 50%、分散後 25%、規避那回合服務降 30%、紅方出手機率）是本遊戲的示意假設，不是 DIA 數據。

用法（repo 根目錄，需另開一個含想定 C 的 SatDashboard 實例）：
  python docs/book/sim_wargame/scenario_c/run_scenario_c.py --server http://127.0.0.1:5091 [--runs 500]
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
BLUE_C = BLUE_BASE + ["watch", "evade", "spread"]
RED = ["balanced", "escalate"]
SCEN = ["base", "c", "c_loiter"]
N_BLUE = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜",
          "watch": "太空監視", "evade": "監視＋規避", "spread": "分散租用"}
N_RED = {"balanced": "紅方：灰色地帶", "escalate": "紅方：升級（含反衛星）"}
N_SCEN = {"base": "原始想定", "c": "想定 C", "c_loiter": "C 對照（只接近不攻擊）"}


def post(server, path, body):
    r = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=600))


def get(server, path):
    return json.load(urllib.request.urlopen(server.rstrip("/") + path, timeout=60))


def run(server, runs):
    rows = []
    for sc in SCEN:
        blue = BLUE_BASE if sc == "base" else BLUE_C   # 監視、規避、分散只在想定 C 有意義
        for red in RED:
            d = post(server, "/api/games/war/mc", {"runs": runs, "blue": blue, "red": red, "scenario": sc})
            assert d["scenario"] == sc, d["scenario"]
            for r in d["results"]:
                rows.append({"scenario": sc, "red": red, "runs": d["runs"], **r})
            print(f"{N_SCEN[sc]}／{N_RED[red]}：完成")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)

    # 敘事範例：同一種子（紅方灰色地帶），藍方均衡、太空監視、監視＋規避各一局；另加紅方升級對均衡一局（必定出手）
    ex = {}
    for b, red in (("balanced", "balanced"), ("watch", "balanced"), ("evade", "balanced"), ("balanced", "escalate")):
        g = post(server, "/api/games/war/new", {"seed": 1001, "ai_blue": b, "ai_red": red, "scenario": "c"})
        st = get(server, f"/api/games/war/state?id={g['id']}&role=white")
        ex[f"c_{b}_vs_{red}"] = {"log": st["log"], "history": st["history"], "scores": st["scores"]}
    (HERE / "example_game_seed1001.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


def summarize(df):
    out = []
    for red in RED:
        out.append(f"\n### {N_RED[red]}\n")
        out.append("| 藍方策略 | 頻寬：原始 | 頻寬：C | 頻寬：C 對照 | GEO 遭攻擊 | 可歸因 | GEO 損失（單位） | 規避次數 | 升級指數（原始→C） |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for b in BLUE_C:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            base = f"{x.loc['base', 'mean_avail']:.1%} ± {x.loc['base', 'ci95']:.1%}" if "base" in x.index else "—"
            esc0 = f"{x.loc['base', 'escalation']:.1f}" if "base" in x.index else "—"
            c, l = x.loc["c"], x.loc["c_loiter"]
            out.append(f"| {N_BLUE[b]} | {base} | {c.mean_avail:.1%} ± {c.ci95:.1%} | {l.mean_avail:.1%} ± {l.ci95:.1%} | "
                       f"{c.strike_rate:.0%} | {c.attrib_rate:.0%} | {c.geo_lost:.1f} | {c.evades:.1f} | {esc0} → {c.escalation:.1f} |")
        # 防護的代價與收益：相對均衡打法，在紅方會出手（C）與只接近（C 對照）時各差多少
        out.append("")
        out.append("| 藍方策略 | 相對均衡：C（百分點） | 相對均衡：C 對照（百分點） | 藍方分數（C） | 藍方分數名次（C） | 紅方分數（C） |")
        out.append("|---|---|---|---|---|---|")
        xc = df[(df.red == red) & (df.scenario == "c")].set_index("blue").loc[BLUE_C]
        xl = df[(df.red == red) & (df.scenario == "c_loiter")].set_index("blue").loc[BLUE_C]
        rk = xc.blue_score.rank(ascending=False).astype(int)
        for b in BLUE_C:
            dc = (xc.loc[b, "mean_avail"] - xc.loc["balanced", "mean_avail"]) * 100
            dl = (xl.loc[b, "mean_avail"] - xl.loc["balanced", "mean_avail"]) * 100
            out.append(f"| {N_BLUE[b]} | {dc:+.1f} | {dl:+.1f} | {xc.loc[b, 'blue_score']:.1f} | {rk[b]} | {xc.loc[b, 'red_score']:.1f} |")
    s = "\n".join(out)
    print(s)
    (HERE / "summary.md").write_text("# 想定 C 推演摘要表（由 run_scenario_c.py 產生）\n" + s + "\n", encoding="utf-8")


def plot(df):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"
    C_BASE, C_C, C_L = "#2a78d6", "#eb6834", "#8d8c86"
    ys = list(range(len(BLUE_C)))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), dpi=200, sharey=True)
    for ax, red in zip(axes, RED):
        g = lambda sc: df[(df.red == red) & (df.scenario == sc)].set_index("blue")
        xb, xc, xl = g("base"), g("c").loc[BLUE_C], g("c_loiter").loc[BLUE_C]
        bv = [(xb.loc[b, "mean_avail"] * 100, y) for b, y in zip(BLUE_C, ys) if b in xb.index]
        ax.scatter([v for v, _ in bv], [y for _, y in bv], s=110, facecolor="none", edgecolor=C_BASE, lw=1.8, zorder=4, label="原始想定（空心圈）")
        ax.scatter(xl.mean_avail * 100, ys, s=22, color=C_L, edgecolor="white", lw=1.0, zorder=6, label="C 對照：紅方只接近不攻擊（小灰點，疊在上層）")
        ax.scatter(xc.mean_avail * 100, ys, s=60, color=C_C, edgecolor="white", lw=1.5, zorder=5, label="想定 C：紅方會出手")
        for b, y in zip(BLUE_C, ys):
            v = xc.loc[b, "mean_avail"] * 100
            ax.text(90.6, y, f"{v:.0f}%｜遭攻擊 {xc.loc[b, 'strike_rate']:.0%}", va="center", fontsize=7.2, color=INK)
        ax.set_xlim(66, 100)
        ax.set_ylim(len(BLUE_C) - 0.5, -0.6)
        ax.set_title(N_RED[red] + "：頻寬可用率（%）", color=INK, fontsize=9.5, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, length=0)
        ax.set_xticks([70, 75, 80, 85, 90])
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([N_BLUE[b] for b in BLUE_C], color=INK)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=8, loc="lower center", ncol=3)
    fig.suptitle("想定 C：重 GEO 最怕近距離攻擊；規避只在紅方真的出手時才划算（各 500 局平均）",
                 color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(HERE / "scenario_c_avail.png")
    print("圖：", HERE / "scenario_c_avail.png")


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
