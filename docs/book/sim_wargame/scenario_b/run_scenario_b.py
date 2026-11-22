"""太空兵棋想定 B「致盲致聾」的蒙地卡羅推演。

想定依據：DIA《Challenges to Security in Space 2026》繁中譯本（頁碼為譯本頁碼）
- p.18：中國國防學界指出，他國的偵察、通信、導航與預警衛星，可能成為「致盲並致聾敵人」的攻擊目標
- p.31–32：PLA 演習例行納入地面衛星上下行鏈路干擾，可能用以拒止天基通信、雷達系統與 GPS 導航；
  中國商業組織為 PLA 開發針對 SAR 的干擾器；地面雷射可干擾、降低或損壞 LEO 衛星，致眩列為雷射用途之一
- p.15：電子攻擊針對 PNT（例如 GPS），常干擾鄰近地區的民用
- p.43：俄方在波羅的海周邊的 GPS 干擾；Sentinel-1 SAR 在克里米亞上空遭干擾
效果數值（GPS 被干擾時 PNT 30%、有備援 80%、SAR 每次過頂 80%）是本遊戲的示意假設，不是 DIA 數據。

用法（repo 根目錄，需另開一個含想定 B 的 SatDashboard 實例）：
  python docs/book/sim_wargame/scenario_b/run_scenario_b.py --server http://127.0.0.1:5091 [--runs 500]
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
BLUE_B = BLUE_BASE + ["hybrid", "sensor"]
RED = ["balanced", "escalate"]
SCEN = ["base", "b", "b_typhoon"]
N_BLUE = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜", "hybrid": "均衡＋備援", "sensor": "重感測"}
N_RED = {"balanced": "紅方：灰色地帶", "escalate": "紅方：升級（含反衛星）"}
N_SCEN = {"base": "原始想定", "b": "想定 B", "b_typhoon": "B＋開場颱風"}


def post(server, path, body):
    r = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=600))


def get(server, path):
    return json.load(urllib.request.urlopen(server.rstrip("/") + path, timeout=60))


def run(server, runs):
    rows = []
    for sc in SCEN:
        blue = BLUE_BASE if sc == "base" else BLUE_B   # 重感測、均衡＋備援只在想定 B 有意義
        for red in RED:
            d = post(server, "/api/games/war/mc", {"runs": runs, "blue": blue, "red": red, "scenario": sc})
            assert d["scenario"] == sc, d["scenario"]
            for r in d["results"]:
                rows.append({"scenario": sc, "red": red, "runs": d["runs"], **r})
            print(f"{N_SCEN[sc]}／{N_RED[red]}：完成")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)

    # 敘事範例：同一種子，藍方均衡與均衡＋備援各一局（紅方灰色地帶）
    ex = {}
    for sc, b in (("base", "balanced"), ("b", "balanced"), ("b", "hybrid")):
        g = post(server, "/api/games/war/new", {"seed": 1001, "ai_blue": b, "ai_red": "balanced", "scenario": sc})
        st = get(server, f"/api/games/war/state?id={g['id']}&role=white")
        ex[f"{sc}_{b}"] = {"log": st["log"], "history": st["history"], "scores": st["scores"]}
    (HERE / "example_game_seed1001.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


def summarize(df):
    out = []
    for red in RED:
        out.append(f"\n### {N_RED[red]}\n")
        out.append("| 藍方策略 | 頻寬：原始 | 頻寬：B | 頻寬：B＋颱風 | 定位授時（B） | 偵察成功次數（B；其中 SAR） | 偵察成功次數（B＋颱風） | 升級指數（原始→B） |")
        out.append("|---|---|---|---|---|---|---|---|")
        for b in BLUE_B:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            base = f"{x.loc['base', 'mean_avail']:.1%} ± {x.loc['base', 'ci95']:.1%}" if "base" in x.index else "—"
            esc0 = f"{x.loc['base', 'escalation']:.1f}" if "base" in x.index else "—"
            bb, bt = x.loc["b"], x.loc["b_typhoon"]
            out.append(f"| {N_BLUE[b]} | {base} | {bb.mean_avail:.1%} ± {bb.ci95:.1%} | {bt.mean_avail:.1%} ± {bt.ci95:.1%} | "
                       f"{bb.pnt_avail:.1%} | {bb.isr_ok:.1f}（{bb.sar_ok:.1f}） | {bt.isr_ok:.1f}（{bt.sar_ok:.1f}） | {esc0} → {bb.escalation:.1f} |")
        out.append("")
        out.append("| 藍方策略 | 前 3 回合頻寬（原始→B） | 最差 10%（原始→B） | 曾低於 50%（原始→B） | 偵察成功率（B） |")
        out.append("|---|---|---|---|---|")
        for b in BLUE_B:
            x = df[(df.red == red) & (df.blue == b)].set_index("scenario")
            bb = x.loc["b"]
            if "base" in x.index:
                o = x.loc["base"]
                out.append(f"| {N_BLUE[b]} | {o.early_avail:.1%} → {bb.early_avail:.1%} | {o.p10:.1%} → {bb.p10:.1%} | "
                           f"{o.p_low:.1%} → {bb.p_low:.1%} | {bb.isr_rate:.1%} |")
            else:
                out.append(f"| {N_BLUE[b]} | — → {bb.early_avail:.1%} | — → {bb.p10:.1%} | — → {bb.p_low:.1%} | {bb.isr_rate:.1%} |")
        # 計分權重：只看頻寬 vs 遊戲計分（頻寬×100 + 偵察成功×3 + 聲望 − 定位授時不足×20）
        x = df[(df.red == red) & (df.scenario == "b")].set_index("blue").loc[BLUE_B]
        r_av = x.mean_avail.rank(ascending=False).astype(int)
        r_sc = x.blue_score.rank(ascending=False).astype(int)
        out.append("")
        out.append("| 藍方策略（想定 B） | 只看頻寬：名次 | 遊戲計分 | 遊戲計分：名次 | 紅方分數 |")
        out.append("|---|---|---|---|---|")
        for b in BLUE_B:
            out.append(f"| {N_BLUE[b]} | {r_av[b]} | {x.loc[b, 'blue_score']:.1f} | {r_sc[b]} | {x.loc[b, 'red_score']:.1f} |")
    s = "\n".join(out)
    print(s)
    (HERE / "summary.md").write_text("# 想定 B 推演摘要表（由 run_scenario_b.py 產生）\n" + s + "\n", encoding="utf-8")


def plot(df):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"
    C_BASE, C_B = "#2a78d6", "#eb6834"
    red = "balanced"
    x = df[(df.red == red) & (df.scenario == "b")].set_index("blue").loc[BLUE_B]
    xb = df[(df.red == red) & (df.scenario == "base")].set_index("blue")
    ys = list(range(len(BLUE_B)))
    fig, axes = plt.subplots(1, 3, figsize=(10, 4.2), dpi=200, sharey=True)
    panels = [("頻寬可用率（%）", x.mean_avail * 100, (60, 100)),
              ("定位授時可用率（%）", x.pnt_avail * 100, (0, 100)),
              ("偵察成功次數（8 回合）", x.isr_ok, (0, max(8, x.isr_ok.max() * 1.15)))]
    for k, (ax, (title, vals, xl)) in enumerate(zip(axes, panels)):
        if k == 0:
            bv = [xb.loc[b, "mean_avail"] * 100 if b in xb.index else None for b in BLUE_B]
            yb = [y for y, v in zip(ys, bv) if v is not None]
            ax.scatter([v for v in bv if v is not None], yb, s=110, facecolor="none", edgecolor=C_BASE, lw=1.8, zorder=4, label="原始想定（空心圈；與想定 B 相同時兩者重疊）")
        ax.scatter(vals, ys, s=46, color=C_B, edgecolor="white", lw=1.5, zorder=3, label="想定 B")
        for v, y in zip(vals, ys):
            ax.text(v + (xl[1] - xl[0]) * 0.035, y, f"{v:.1f}" if k == 2 else f"{v:.0f}", va="center", fontsize=7.5, color=INK)
        ax.set_xlim(xl[0], xl[1] * 1.08 if k else xl[1] + 3)
        ax.set_ylim(len(BLUE_B) - 0.5, -0.6)
        ax.set_title(title, color=INK, fontsize=9.5, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, length=0)
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([N_BLUE[b] for b in BLUE_B], color=INK)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=8, loc="lower center", ncol=2)
    fig.suptitle("想定 B：頻寬、定位授時與偵察三者互相排擠（紅方灰色地帶，各 500 局平均）",
                 color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(HERE / "scenario_b_tradeoff.png")
    print("圖：", HERE / "scenario_b_tradeoff.png")


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
