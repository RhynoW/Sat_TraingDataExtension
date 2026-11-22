"""四個太空兵棋想定的敏感度分析（第二階段，回應外部審查意見 P1）。

需要一個含參數覆寫（`params`）與每局輸出（`per_game`）的 SatDashboard 實例：
  python docs/book/sim_wargame/sensitivity/run_sensitivity.py --server http://127.0.0.1:<埠> [--runs 500]
沒有 --server 時只讀既有 games.csv.gz 重算表格與圖。

所有參數值都是示意假設（教學／分析用），不是 DIA 數據。每組 500 局，共同亂數（種子 1000–1499），
所以同一想定不同設定之間可以逐局配對相減。
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RED = ["balanced", "escalate"]
N_RED = {"balanced": "灰色地帶", "escalate": "升級"}
BLUE_A = ["balanced", "geo", "leo", "repair"]
BLUE_B = BLUE_A + ["hybrid", "sensor"]
BLUE_C = ["balanced", "geo", "watch", "evade", "spread"]
BLUE_D = BLUE_A + ["imagery", "avoid"]
N_BLUE = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜", "hybrid": "均衡＋備援", "sensor": "感測優先",
          "watch": "太空監視", "evade": "監視＋規避", "spread": "分散租用", "imagery": "重 GEO＋商業影像", "avoid": "均衡＋避碰"}
BAN3 = ["cut_cable", "jam_leo", "cyber_gateway"]


def experiments():
    """(實驗代號, 想定, 紅方清單, 藍方清單, 參數覆寫)"""
    E = []
    both = RED
    # A：抹除比例、單一手段基準
    E.append(("A_pre", "a_pre", both, BLUE_A, {}))
    for w in (0.15, 0.3, 0.6):
        E.append((f"A_wipe{w}", "a", both, BLUE_A, {"a_wipe": w}))
    E.append(("A_none", "a", both, BLUE_A, {"red_ban": BAN3}))
    for k, keep in (("cut", "cut_cable"), ("jam", "jam_leo"), ("cyber", "cyber_gateway")):
        E.append((f"A_only_{k}", "a", both, BLUE_A, {"red_ban": [x for x in BAN3 if x != keep]}))
    # B：預設（權重熱圖、名次穩定度）、不干擾對照、GPS 干擾效果、SAR 成功率
    E.append(("B0", "b", both, BLUE_B, {}))
    E.append(("B_nojam", "b", both, BLUE_B, {"red_ban": ["jam_gps", "jam_sar"]}))
    for v in (0.1, 0.6):
        E.append((f"B_pnt{v}", "b", both, BLUE_B, {"b_pnt_jammed": v}))
    for v in (0.5, 0.95):
        E.append((f"B_sar{v}", "b", both, BLUE_B, {"b_sar_p": v}))
    # C：預設、紅方風險偏好（只有灰色地帶紅方會看監視決定出手）、監視品質、歸因、規避成功率、規避成本、只接近不攻擊、保守組合
    E.append(("C0", "c", both, BLUE_C, {}))
    E.append(("C_loiter", "c_loiter", both, BLUE_C, {}))
    for v in (0.05, 0.3):
        E.append((f"C_risk{v}", "c", ["balanced"], BLUE_C, {"c_p_strike_tracked": v}))
    for v in (0.7, 0.4):
        E.append((f"C_track{v}", "c", both, BLUE_C, {"c_track_p": v}))
    E.append(("C_attrib0.5", "c", both, BLUE_C, {"c_attrib_p": 0.5}))
    for v in (0.8, 0.5):
        E.append((f"C_evade{v}", "c", both, BLUE_C, {"c_evade_p": v}))
    for v in (0.85, 0.5):
        E.append((f"C_dip{v}", "c", both, BLUE_C, {"c_evade_dip": v}))
    E.append(("C_cons", "c", both, BLUE_C, {"c_track_p": 0.7, "c_attrib_p": 0.5, "c_evade_p": 0.8, "c_p_strike_tracked": 0.3}))
    # D：預設、不用反衛星對照、紅方一律打光學衛星 × 商業影像效能
    E.append(("D0", "d", both, BLUE_D, {}))
    E.append(("D_noasat", "d_noasat", both, BLUE_D, {}))
    E.append(("D_adapt_img0.4", "d", both, BLUE_D, {"d_img_factor": 0.4}))
    for v in (1.0, 0.7, 0.4):
        E.append((f"D_isr_img{v}", "d", both, BLUE_D, {"d_red_pref": "isr", "d_img_factor": v}))
    return E


def post(server, body):
    r = urllib.request.Request(server.rstrip("/") + "/api/games/war/mc", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=1800))


def run(server, runs):
    frames = []
    for exp, sc, reds, blues, params in experiments():
        for red in reds:
            d = post(server, {"runs": runs, "blue": blues, "red": red, "scenario": sc, "params": params, "per_game": True})
            assert d["scenario"] == sc and "params" in d, d.get("scenario")
            for r in d["results"]:
                g = pd.DataFrame(r["games"], columns=r["game_cols"])
                g.insert(0, "seed", 1000 + np.arange(len(g)))
                g.insert(0, "blue", r["blue"])
                g.insert(0, "red", red)
                g.insert(0, "scenario", sc)
                g.insert(0, "exp", exp)
                frames.append(g)
            print(f"{exp:16s} {N_RED[red]}：完成")
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(HERE / "games.csv.gz", index=False, float_format="%.6g", compression="gzip")
    meta = {
        "run_at": datetime.now().isoformat(timespec="seconds"), "server": server, "runs": runs, "seeds": f"1000–{999 + runs}",
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
        "games_war_rs_sha256": hashlib.sha256((REPO / "RUST_SatDashboard/src/games_war.rs").read_bytes()).hexdigest(),
        "note": "games_war.rs 為未 commit 的工作版；以檔案雜湊識別版本",
        "experiments": [{"exp": e, "scenario": s, "red": r, "blue": b, "params": p} for e, s, r, b, p in experiments()],
    }
    (HERE / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


# ---------- 統計工具 ----------
def paired(df, exp_x, exp_y, red, blue, col="mean_avail", scale=100.0):
    """x − y 的逐局配對差值：平均、95% 信賴區間半寬；另回傳「當作兩組獨立樣本」的半寬作比較"""
    x = df[(df.exp == exp_x) & (df.red == red) & (df.blue == blue)].sort_values("seed")[col].to_numpy() * scale
    y = df[(df.exp == exp_y) & (df.red == red) & (df.blue == blue)].sort_values("seed")[col].to_numpy() * scale
    d = x - y
    n = len(d)
    hw = 1.96 * d.std(ddof=1) / np.sqrt(n)
    hw_ind = 1.96 * np.sqrt(x.var(ddof=1) / n + y.var(ddof=1) / n)
    return d.mean(), hw, hw_ind


def m(df, exp, red, blue, col="mean_avail"):
    return df[(df.exp == exp) & (df.red == red) & (df.blue == blue)][col].mean()


def fmt_d(t, unit="", nd=1):
    mu, hw, _ = t
    return f"{mu:+.{nd}f} ± {hw:.{nd}f}{unit}"


def rank_stability(df, exp, red, blues, col="mean_avail", B=1000, seed=7):
    """逐局重抽（配對：同一組種子一起抽），各策略排第一的比例"""
    piv = df[(df.exp == exp) & (df.red == red)].pivot(index="seed", columns="blue", values=col)[blues].to_numpy()
    rng = np.random.default_rng(seed)
    n = piv.shape[0]
    wins = np.zeros(len(blues))
    for _ in range(B):
        idx = rng.integers(0, n, n)
        mu = piv[idx].mean(axis=0)
        top = np.flatnonzero(np.isclose(mu, mu.max(), rtol=0, atol=1e-12))
        wins[top] += 1 / len(top)   # 完全相同的打法（例如沒有碎片時的「均衡＋避碰」）平分
    return dict(zip(blues, wins / B))


def dist(df, exp, red, blue):
    x = df[(df.exp == exp) & (df.red == red) & (df.blue == blue)].mean_avail.to_numpy() * 100
    return np.percentile(x, 5), np.percentile(x, 50), np.percentile(x, 95), x.min()


# ---------- 各想定 ----------
def sec_a(df):
    o = ["## 想定 A：灰色地帶", "", "### A-1 抹除比例（攻擊代價 = 想定 A − 對照組，逐局配對差值，百分點）", ""]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "", "| 藍方打法 | 抹除 15% | 抹除 30%（基準） | 抹除 60% | 網攻累計抹除（15%／30%／60%，套） |", "|---|---|---|---|---|"]
        for b in BLUE_A:
            cells = [fmt_d(paired(df, f"A_wipe{w}", "A_pre", red, b), nd=2) for w in (0.15, 0.3, 0.6)]
            lost = "／".join(f"{m(df, f'A_wipe{w}', red, b, 'cyber_lost'):.0f}" for w in (0.15, 0.3, 0.6))
            o.append(f"| {N_BLUE[b]} | {' | '.join(cells)} | {lost} |")
        o.append("")
    o += ["### A-2 單一手段基準（紅方遊戲中只用一種頻寬攻擊手段；開場抹除與開場干擾照常）", "",
          "表中是「只用該手段」減「三種都不用」的逐局配對差值（百分點）；最後一欄是三種都用（想定 A 基準）。", ""]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "", "| 藍方打法 | 三種都不用：可用率 | 只切纜 | 只干擾低軌 | 只網攻閘道站 | 三種都用 | 單項加總 |", "|---|---|---|---|---|---|---|"]
        for b in BLUE_A:
            base = m(df, "A_none", red, b) * 100
            sing = [paired(df, f"A_only_{k}", "A_none", red, b) for k in ("cut", "jam", "cyber")]
            allm = paired(df, "A_wipe0.3", "A_none", red, b)
            o.append(f"| {N_BLUE[b]} | {base:.1f}% | " + " | ".join(fmt_d(s, nd=2) for s in sing) + f" | {fmt_d(allm, nd=2)} | {sum(s[0] for s in sing):+.2f} |")
        o.append("")
    return o


def b_weights(df, red, w_isr, w_pnt):
    g = df[(df.exp == "B0") & (df.red == red)]
    s = g.mean_avail * 100 + g.isr_ok * w_isr + g.reputation - (1 - g.pnt_avail) * w_pnt
    return s.groupby(g.blue).mean()


def sec_b(df):
    o = ["## 想定 B：致盲致聾", ""]
    # 驗證重算的分數等於遊戲分數
    for red in RED:
        g = df[(df.exp == "B0") & (df.red == red)]
        chk = (g.mean_avail * 100 + g.isr_ok * 3 + g.reputation - (1 - g.pnt_avail) * 20 - g.blue_score).abs().max()
        assert chk < 1e-3, chk
    o += ["### B-1 計分權重（見 b_weight_map.png）", "",
          "藍方分數 = 平均可用率 × 100 + 偵察成功次數 × w偵察 + 聲望 − (1 − 定位授時可用率) × w定位授時。權重只影響計分、不影響雙方 AI 的決策，",
          "所以可以用同一批 500 局重算。遊戲預設 w偵察 = 3、w定位授時 = 20；重算結果與遊戲分數逐局相符（誤差 < 0.001）。", ""]
    wi = np.round(np.arange(0, 6.01, 0.25), 2)
    wp = np.arange(0, 41, 1)
    grids = {}
    for red in RED:
        win = np.empty((len(wp), len(wi)), dtype=object)
        for i, a in enumerate(wi):
            for j, p in enumerate(wp):
                s = b_weights(df, red, a, p)
                win[j, i] = s.idxmax()
        grids[red] = (wi, wp, win)
        share = pd.Series(win.ravel()).value_counts(normalize=True)
        o.append(f"紅方{N_RED[red]}：在 w偵察 0–6、w定位授時 0–40 的格點中，各策略分數最高的比例：" +
                 "、".join(f"{N_BLUE[k]} {v:.0%}" for k, v in share.items()) + "。")
        # w定位授時 = 20 時的翻轉點
        col = [win[20, i] for i in range(len(wi))]
        flips = [f"w偵察 {wi[i]:g} 起 {N_BLUE[col[i]]}" for i in range(len(wi)) if i == 0 or col[i] != col[i - 1]]
        o.append(f"  固定 w定位授時 = 20 時：" + "；".join(flips) + "。")
        o.append("")
    o += ["### B-2 紅方不干擾 GPS／SAR 的對照，與效果參數的低／中／高", "",
          "可用率與偵察次數為 500 局平均；「差值」欄是對基準（B0）的逐局配對差值。", ""]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "",
              "| 藍方打法 | 基準：可用率 | 不干擾 GPS／SAR：可用率差 | 基準：定位授時 | 不干擾：定位授時 | GPS 干擾後 10%／30%／60%：定位授時 | 基準：偵察次數 | SAR 50%／80%／95%：偵察次數 |",
              "|---|---|---|---|---|---|---|---|"]
        for b in BLUE_B:
            pn = "／".join(f"{m(df, e, red, b, 'pnt_avail'):.0%}" for e in ("B_pnt0.1", "B0", "B_pnt0.6"))
            sr = "／".join(f"{m(df, e, red, b, 'isr_ok'):.2f}" for e in ("B_sar0.5", "B0", "B_sar0.95"))
            o.append(f"| {N_BLUE[b]} | {m(df, 'B0', red, b) * 100:.1f}% | {fmt_d(paired(df, 'B_nojam', 'B0', red, b))} | "
                     f"{m(df, 'B0', red, b, 'pnt_avail'):.0%} | {m(df, 'B_nojam', red, b, 'pnt_avail'):.0%} | {pn} | {m(df, 'B0', red, b, 'isr_ok'):.2f} | {sr} |")
        o.append("")
    o += ["### B-3 各指標分開排名（基準 B0，不合成總分）", ""]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "", "| 藍方打法 | 可用率 | 定位授時 | 偵察次數 | 升級指數 | 聲望 | 遊戲總分 |", "|---|---|---|---|---|---|---|"]
        for b in BLUE_B:
            o.append(f"| {N_BLUE[b]} | {m(df, 'B0', red, b) * 100:.1f}% | {m(df, 'B0', red, b, 'pnt_avail'):.0%} | {m(df, 'B0', red, b, 'isr_ok'):.2f} | "
                     f"{m(df, 'B0', red, b, 'escalation'):.1f} | {m(df, 'B0', red, b, 'reputation'):.1f} | {m(df, 'B0', red, b, 'blue_score'):.1f} |")
        o.append("")
    return o, grids


def sec_c(df):
    o = ["## 想定 C：共軌接近", "", "表中可用率差值都是對同一紅方、同一參數下「均衡」打法的逐局配對差值（百分點）；負值代表比均衡差。", ""]
    rows = [("C0", "基準（監視永久有效、歸因必成、規避必成）", RED),
            ("C_risk0.05", "紅方低風險偏好：被監視時出手率 5%", ["balanced"]),
            ("C_risk0.3", "紅方高風險偏好：被監視也照樣 30%", ["balanced"]),
            ("C_track0.7", "監視資料每回合有效 70%", RED), ("C_track0.4", "監視資料每回合有效 40%", RED),
            ("C_attrib0.5", "有效追蹤下歸因成功 50%", RED),
            ("C_evade0.8", "規避成功率 80%", RED), ("C_evade0.5", "規避成功率 50%", RED),
            ("C_dip0.85", "規避次回合服務 85%（成本低）", RED), ("C_dip0.5", "規避次回合服務 50%（成本高）", RED),
            ("C_cons", "保守組合：監視 70%、歸因 50%、規避 80%、紅方高風險", RED),
            ("C_loiter", "紅方只接近、不攻擊", RED)]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "",
              "| 設定 | 均衡：可用率 | 重 GEO | 太空監視 | 監視＋規避 | 分散租用 | 監視：遭攻擊／歸因 | 監視＋規避：遭攻擊 | 監視：藍方分數差 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for e, lab, reds in rows:
            if red not in reds:
                continue
            cells = [fmt_d(_pd_vs(df, e, red, b, "balanced")) for b in ("geo", "watch", "evade", "spread")]
            o.append(f"| {lab} | {m(df, e, red, 'balanced') * 100:.1f}% | " + " | ".join(cells) +
                     f" | {m(df, e, red, 'watch', 'struck'):.0%}／{m(df, e, red, 'watch', 'attributed'):.0%} | {m(df, e, red, 'evade', 'struck'):.0%} | "
                     f"{fmt_d(_pd_vs(df, e, red, 'watch', 'balanced', 'blue_score', 1.0))} |")
        o.append("")
    return o


def _pd_vs(df, exp, red, b1, b2, col="mean_avail", scale=100.0):
    x = df[(df.exp == exp) & (df.red == red) & (df.blue == b1)].sort_values("seed")[col].to_numpy() * scale
    y = df[(df.exp == exp) & (df.red == red) & (df.blue == b2)].sort_values("seed")[col].to_numpy() * scale
    d = x - y
    return d.mean(), 1.96 * d.std(ddof=1) / np.sqrt(len(d)), None


def sec_d(df):
    o = ["## 想定 D：直升式反衛星", "",
         "「偵察損失」= 該設定的偵察成功次數 − 紅方不用反衛星（D 對照）的逐局配對差值（次／局）。", ""]
    rows = [("D0", "基準：紅方依藍方備援調整目標，商業影像完全替代"),
            ("D_adapt_img0.4", "紅方調整目標，商業影像效能 40%"),
            ("D_isr_img1.0", "紅方一律打光學衛星，商業影像完全替代"),
            ("D_isr_img0.7", "紅方一律打光學衛星，商業影像效能 70%"),
            ("D_isr_img0.4", "紅方一律打光學衛星，商業影像效能 40%")]
    for red in RED:
        o += [f"**紅方{N_RED[red]}**", "", "| 設定 | 重 GEO：光學衛星被毀 | 重 GEO：偵察損失 | 重 GEO＋商業影像：光學衛星被毀 | 重 GEO＋商業影像：偵察損失 | 重 GEO＋商業影像：可用率差（對重 GEO） |", "|---|---|---|---|---|---|"]
        for e, lab in rows:
            o.append(f"| {lab} | {m(df, e, red, 'geo', 'isr_sat_dead'):.0%} | {fmt_d(_pd_x(df, e, 'D_noasat', red, 'geo', 'isr_ok'), nd=2)} | "
                     f"{m(df, e, red, 'imagery', 'isr_sat_dead'):.0%} | {fmt_d(_pd_x(df, e, 'D_noasat', red, 'imagery', 'isr_ok'), nd=2)} | "
                     f"{fmt_d(_pd_vs(df, e, red, 'imagery', 'geo'))} |")
        o.append("")
    return o


def _pd_x(df, e1, e2, red, b, col):
    return paired(df, e1, e2, red, b, col, 1.0)


def sec_common(df):
    o = ["## 跨想定：配對差值與分布", "",
         "### 配對差值讓比較更精確", "",
         "同一組種子下兩組設定逐局相減，比把兩組當作獨立樣本的信賴區間窄。下表是各想定關鍵比較的 95% 信賴區間半寬（百分點）。", "",
         "| 比較 | 差值 | 配對半寬 | 當作獨立樣本的半寬 |", "|---|---|---|---|"]
    for lab, ex, ey, red, b in [("A：想定 A − 對照（均衡，灰色地帶）", "A_wipe0.3", "A_pre", "balanced", "balanced"),
                                ("A：想定 A − 對照（重 GEO，灰色地帶）", "A_wipe0.3", "A_pre", "balanced", "geo"),
                                ("B：不干擾 − 基準（均衡，灰色地帶）", "B_nojam", "B0", "balanced", "balanced"),
                                ("C：想定 C − 只接近（重 GEO，升級）", "C0", "C_loiter", "escalate", "geo"),
                                ("D：想定 D − 不用反衛星（重 GEO，升級）", "D0", "D_noasat", "escalate", "geo")]:
        mu, hw, hwi = paired(df, ex, ey, red, b)
        o.append(f"| {lab} | {mu:+.2f} | ±{hw:.2f} | ±{hwi:.2f} |")
    o += ["", "### 結果分布與名次穩定度（各想定基準設定）", "",
          "可用率的第 5／50／95 百分位與最差一局；「排第一的比例」是逐局重抽 1,000 次（配對重抽）中該打法平均可用率最高的比例。", ""]
    for exp, blues, lab in (("A_wipe0.3", BLUE_A, "想定 A"), ("B0", BLUE_B, "想定 B"), ("C0", BLUE_C, "想定 C"), ("D0", BLUE_D, "想定 D")):
        for red in RED:
            rs = rank_stability(df, exp, red, blues)
            o += [f"**{lab}，紅方{N_RED[red]}**", "", "| 藍方打法 | 平均 | P5 | P50 | P95 | 最差一局 | 排第一的比例 |", "|---|---|---|---|---|---|---|"]
            for b in blues:
                p5, p50, p95, mn = dist(df, exp, red, b)
                o.append(f"| {N_BLUE[b]} | {m(df, exp, red, b) * 100:.1f}% | {p5:.1f}% | {p50:.1f}% | {p95:.1f}% | {mn:.1f}% | {rs[b]:.0%} |")
            o.append("")
    return o


def plot_b(grids):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    INK, MUTED, SURF = "#1f1f1e", "#6b6a64", "#ffffff"
    # 類別色依策略固定（dataviz 參考色盤第 1–6 槽，順序固定、不隨名次改變）
    COL = dict(zip(BLUE_B, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.0), dpi=200, sharey=True)
    for ax, red in zip(axes, RED):
        wi, wp, win = grids[red]
        idx = np.vectorize(BLUE_B.index)(win)
        ax.imshow(idx, origin="lower", aspect="auto", cmap=ListedColormap([COL[b] for b in BLUE_B]), vmin=-0.5, vmax=len(BLUE_B) - 0.5,
                  extent=(wi[0] - 0.125, wi[-1] + 0.125, wp[0] - 0.5, wp[-1] + 0.5), alpha=0.85, interpolation="nearest")
        from scipy.ndimage import distance_transform_edt
        for k in np.unique(idx):
            mask = idx == k
            # 標籤放在離區域邊界最遠的格點（區域內部最寬處）
            dt = distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1]
            if k == BLUE_B.index("hybrid"):
                dt[np.abs(wp - 20) < 6, :] = 0   # 避開「遊戲預設」標記
            j, i = np.unravel_index(np.argmax(dt), dt.shape)
            name = N_BLUE[BLUE_B[k]]
            if mask.sum() < 25:   # 區域太小放不下文字：引線標註
                ax.annotate(name, (wi[i], wp[j]), xytext=(wi[i] + 1.0, wp[j] + 6), fontsize=8.5, color=INK,
                            arrowprops=dict(arrowstyle="-", color=INK, lw=0.8))
            else:
                ax.text(wi[i], wp[j], name, ha="center", va="center", fontsize=9, color=SURF, fontweight="bold")
        ax.plot([3], [20], marker="o", ms=7, mfc=SURF, mec=INK, mew=1.2)
        ax.annotate("遊戲預設（3, 20）", (3, 20), xytext=(8, -12), textcoords="offset points", fontsize=8, color=INK)
        ax.set_title(f"紅方{N_RED[red]}", fontsize=9.5, color=INK, loc="left")
        ax.set_xlabel("w偵察：每次偵察成功的分數", color=MUTED, fontsize=8.5)
        ax.tick_params(colors=MUTED, length=0, labelsize=8)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].set_ylabel("w定位授時：定位授時全失的扣分", color=MUTED, fontsize=8.5)
    fig.suptitle("想定 B：不同計分權重下，藍方總分最高的打法（同一批 500 局重算）", color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(HERE / "b_weight_map.png")
    print("圖：", HERE / "b_weight_map.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    ap.add_argument("--runs", type=int, default=500)
    a = ap.parse_args()
    df = run(a.server, a.runs) if a.server else pd.read_csv(HERE / "games.csv.gz")
    ob, grids = sec_b(df)
    out = ["# 四想定敏感度分析摘要表（由 run_sensitivity.py 產生）", "",
           "所有參數值為示意假設；每組 500 局，共同亂數（種子 1000–1499）。± 為 95% 信賴區間半寬（逐局配對差值）。", ""]
    out += sec_a(df) + ob + sec_c(df) + sec_d(df) + sec_common(df)
    s = "\n".join(out) + "\n"
    (HERE / "summary.md").write_text(s, encoding="utf-8")
    print(s)
    plot_b(grids)


if __name__ == "__main__":
    main()
