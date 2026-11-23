"""延伸篇 S3 審查（Major Revision）補充推演：前期衝擊指標、GEO 可受攻擊、替代 AI、想定 C 嚇阻與歸因分解、
想定 D 換目標假設、7 天窗口。

需要 2026-11-23 以後的 SatDashboard（games_war.rs 新增 turns、geo_jam、geo_outage_p、red_aggr、red_target、
d_switch_p、d_switch_delay、c_attrib_rep、c_misattrib_p 參數，藍方新增 threshold、utility 打法，逐局輸出每回合可用率）。
預設參數下結果與擴充前逐局相同（已以既有敏感度實驗 72 組比較驗證）。

用法：python docs/book/sim_wargame/review_v2/run_review_v2.py --server http://127.0.0.1:<埠> [--runs 500]
      沒有 --server 時只讀既有 games_v2.csv.gz 重算 summary_v2.json
所有參數值都是示意假設（教學／分析用），不是 DIA 數據。每組 500 局、種子 1000–1499（共同亂數）。
"""
import argparse
import hashlib
import json
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
NEW = ["threshold", "utility"]
BLUE = {"a": ["balanced", "geo", "leo", "repair"] + NEW,
        "b": ["balanced", "geo", "leo", "repair", "hybrid", "sensor"] + NEW,
        "c": ["balanced", "geo", "watch", "evade", "spread"] + NEW,
        "d": ["balanced", "geo", "leo", "repair", "imagery", "avoid"] + NEW}


def experiments():
    """(實驗代號, 想定, 藍方清單, 參數覆寫)"""
    E = []
    # 1 基準（四想定與對照組；新指標與分布、名次機率）
    for code, sc, bl in [("A0", "a", "a"), ("A_pre", "a_pre", "a"), ("B0", "b", "b"), ("C0", "c", "c"), ("C_loiter", "c_loiter", "c"),
                         ("D0", "d", "d"), ("D_noasat", "d_noasat", "d")]:
        E.append((code, sc, BLUE[bl], {}))
    # 2 GEO 可受攻擊（想定 A 與對照組）
    for g in (0.25, 0.5):
        E.append((f"A_geojam{g}", "a", BLUE["a"], {"geo_jam": g}))
        E.append((f"Apre_geojam{g}", "a_pre", BLUE["a"], {"geo_jam": g}))
    for q in (0.1, 0.25):
        E.append((f"A_geoout{q}", "a", BLUE["a"], {"geo_outage_p": q}))
    E.append(("A_geojam0.5_adapt", "a", BLUE["a"], {"geo_jam": 0.5, "red_target": "adaptive"}))
    E.append(("C_geojam0.5", "c", BLUE["c"], {"geo_jam": 0.5}))
    # 3 替代 AI：紅方風險偏好與目標選擇
    for sc, bl in [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")]:
        for ag in (0.5, 1.5):
            E.append((f"{sc.upper()}_aggr{ag}", sc, BLUE[bl], {"red_aggr": ag}))
        for tg in ("random", "adaptive"):
            E.append((f"{sc.upper()}_target_{tg}", sc, BLUE[bl], {"red_target": tg}))
    # 4 想定 C：嚇阻與歸因分解
    for v in (0.05, 0.3):
        E.append((f"C_ptrack{v}", "c", BLUE["c"], {"c_p_strike_tracked": v}))
    for v in (0.0, 1.5):
        E.append((f"C_rep{v}", "c", BLUE["c"], {"c_attrib_rep": v}))
    for v in (0.1, 0.3):
        E.append((f"C_misattr{v}", "c", BLUE["c"], {"c_misattrib_p": v}))
        E.append((f"Cloiter_misattr{v}", "c_loiter", BLUE["c"], {"c_misattrib_p": v}))
    E.append(("C_attrib0.5", "c", BLUE["c"], {"c_attrib_p": 0.5}))
    E.append(("C_nodeter", "c", BLUE["c"], {"c_p_strike_tracked": 0.3}))   # 被監視時不降低出手率：只剩歸因
    E.append(("C_nodeter_rep0", "c", BLUE["c"], {"c_p_strike_tracked": 0.3, "c_attrib_rep": 0.0}))   # 嚇阻與歸因都拿掉
    # 5 想定 D：紅方換目標假設
    for sp in (0.0, 0.5):
        for f in (1.0, 0.7, 0.4):
            E.append((f"D_switch{sp}_img{f}", "d", BLUE["d"], {"d_switch_p": sp, "d_img_factor": f}))
    E.append(("D_delay4", "d", BLUE["d"], {"d_switch_delay": 4}))   # 藍方第 0 回合簽約，紅方第 2–3 回合起才會出手，延遲須 > 3 才有作用
    # 6 7 天窗口（28 回合；需求於第 8 回合後持平）
    for code, sc, bl in [("A0", "a", "a"), ("A_pre", "a_pre", "a"), ("B0", "b", "b"), ("C0", "c", "c"), ("C_loiter", "c_loiter", "c"),
                         ("D0", "d", "d"), ("D_noasat", "d_noasat", "d")]:
        E.append((f"{code}_7d", sc, BLUE[bl], {"turns": 28}))
    return E


def demand(t):
    return 150 + 5 * min(t, 8)


def post(server, body):
    req = urllib.request.Request(server + "/api/games/war/mc", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)


def run(server, runs, only=None):
    rows = []
    for code, sc, blues, params in experiments():
        if only and code not in only:
            continue
        for red in RED:
            d = post(server, {"runs": runs, "blue": blues, "red": red, "scenario": sc, "params": params, "per_game": True})
            for res in d["results"]:
                cols = res["game_cols"]
                for k, g in enumerate(res["games"]):
                    row = dict(zip(cols, g))
                    row["series"] = json.dumps(row["series"])
                    rows.append({"exp": code, "scenario": sc, "red": red, "blue": res["blue"], "seed": 1000 + k, **row})
        print(code, "done", flush=True)
    df = pd.DataFrame(rows)
    if only:   # 只重跑部分實驗：與既有結果合併
        old = pd.read_csv(HERE / "games_v2.csv.gz")
        old = old[~old.exp.isin(only + ["D_delay2"])]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(HERE / "games_v2.csv.gz", index=False, compression="gzip")
    src = (REPO / "RUST_SatDashboard/src/games_war.rs").read_bytes()
    meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "server": server, "runs": runs,
            "games_war_rs_sha256": hashlib.sha256(src).hexdigest(), "experiments": [e[0] for e in experiments()],
            "note": "所有參數為示意假設；預設參數結果與擴充前逐局相同（72 組比較）"}
    (HERE / "run_meta_v2.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return df


def metrics(g):
    s = np.array(json.loads(g))
    dem = np.array([demand(t + 1) for t in range(len(s))])
    unmet = float(((1 - s) * dem).sum())
    below = int((s < 0.85).sum())
    return unmet, below


def summarize(df):
    df = df.copy()
    m = df["series"].map(metrics)
    df["unmet"] = [x[0] for x in m]
    df["below85"] = [x[1] for x in m]
    out = {}
    for (exp, red, blue), g in df.groupby(["exp", "red", "blue"]):
        v = g.sort_values("seed")
        ser = np.array([json.loads(x) for x in v["series"]])
        q = np.percentile(v["mean_avail"], [5, 25, 50, 75, 95])
        out.setdefault(exp, {}).setdefault(red, {})[blue] = {
            "mean": float(v["mean_avail"].mean()), "sd": float(v["mean_avail"].std(ddof=1)),
            "q": [float(x) for x in q], "min": float(v["min_avail"].mean()), "early": float(v["early_avail"].mean()),
            "unmet": float(v["unmet"].mean()), "below85": float(v["below85"].mean()),
            "blue_score": float(v["blue_score"].mean()), "isr_ok": float(v["isr_ok"].mean()), "pnt": float(v["pnt_avail"].mean()),
            "struck": float(v["struck"].mean()), "attributed": float(v["attributed"].mean()), "isr_sat_dead": float(v["isr_sat_dead"].mean()),
            "misattributed": float(v["misattributed"].mean()), "reputation": float(v["reputation"].mean()),
            "series_mean": [float(x) for x in ser.mean(axis=0)], "series_p10": [float(x) for x in np.percentile(ser, 10, axis=0)],
            "series_p90": [float(x) for x in np.percentile(ser, 90, axis=0)],
        }
    # 名次機率（以種子為單位重抽 1,000 次；頻寬平均）
    rng = np.random.default_rng(7)
    ranks = {}
    for (exp, red), g in df.groupby(["exp", "red"]):
        piv = g.pivot(index="seed", columns="blue", values="mean_avail")
        n = len(piv)
        cnt = {b: [0, 0, 0] for b in piv.columns}
        for _ in range(1000):
            idx = rng.integers(0, n, n)
            order = piv.iloc[idx].mean().sort_values(ascending=False).index
            for r, b in enumerate(order[:3]):
                for k in range(r, 3):
                    cnt[b][k] += 1
        ranks.setdefault(exp, {})[red] = {b: [c / 1000 for c in v] for b, v in cnt.items()}
    (HERE / "summary_v2.json").write_text(json.dumps({"stats": out, "ranks": ranks}, ensure_ascii=False), encoding="utf-8")
    return out, ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    ap.add_argument("--runs", type=int, default=500)
    ap.add_argument("--only", help="逗號分隔的實驗代號；只重跑這些並與既有結果合併")
    a = ap.parse_args()
    df = run(a.server, a.runs, a.only.split(",") if a.only else None) if a.server else pd.read_csv(HERE / "games_v2.csv.gz")
    summarize(df)
    print("ok")


if __name__ == "__main__":
    main()
