#!/usr/bin/env python3
"""rag_test_july_10sat.py — maneuver_app_july × SSA-RAG 十星批次測試
================================================================
用 july 版的偵測管線（build_transitions + P1–P6 apply_strategies）對隨機挑選的
10 顆酬載衛星產生「機動偵測敘述」，送入 SSA-RAG 自動解說，並以 rag_answer_check
檢查 Δa 方向紀律（負淨變化卻宣稱「軌道抬升」＝矛盾）。

輸出：docs/rag_test_july_10sat_<stamp>.csv
規則：服務健康檢查通過才跑；不自行啟動 uvicorn（由 Server 端）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms
from ssa_rag_client import SSARAGClient
from rag_answer_check import sign_conflict, claims_raising_in_conclusion

DB_PATH = "space_db.duckdb"
R_E = 6378.137
BASE_URL = "http://127.0.0.1:8000"
SEED = 20260716

# 排除非酬載（殘骸／火箭體）
_EXCLUDE = ("DEB", "R/B", "ROCKET BODY", "COOLANT", "WESTFORD NEEDLES")

# 前一輪已測，避免重複
_TESTED = set()


def load_f107() -> dict:
    p = Path("f107_cache.csv")
    if not p.exists():
        return {}
    f = pd.read_csv(p)
    f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
    return dict(zip(f["epoch"], f["f107"]))


def load_tle(con, norad: int) -> pd.DataFrame:
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, "
        "raan_deg, argp_deg, mean_anomaly_deg, bstar FROM raw_tle_archive "
        "WHERE norad_id=? ORDER BY epoch_utc", [int(norad)]).fetchdf()
    if df.empty:
        return df
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    return df.reset_index(drop=True)


def build_tle_narrative(norad, alt_avg, d0, d1, ev: pd.DataFrame) -> str:
    """與 maneuver_app_july.build_tle_maneuver_narrative 一致（供離線批次用）。"""
    alt_txt = f"平均軌道高度約 {alt_avg:.0f} km" if alt_avg is not None else "軌道高度未知"
    n = 0 if ev is None or ev.empty else len(ev)
    lines = [f"衛星 NORAD {norad}（{alt_txt}）在 {d0} 至 {d1} 期間，以 TLE 半長軸（SMA）"
             f"跳變法（P1–P6 高度自適應）進行機動偵測，共偵測到 {n} 次疑似機動事件。"]
    if n:
        el = []
        _is_raise = ev["sma_direction"].astype(str).to_numpy() == "raise"
        _absd = ev["sma_delta"].abs().to_numpy(float)
        for _, e in ev.head(10).iterrows():
            direc = "抬升" if str(e["sma_direction"]) == "raise" else "降低"
            el.append(f"- {pd.Timestamp(e['epoch']).strftime('%Y-%m-%d')}："
                      f"半長軸{direc}，|Δa| = {float(e['sma_delta']):.4f} km")
        if n > 10:
            el.append(f"-（其餘 {n - 10} 次事件省略）")
        lines.append("事件清單：\n" + "\n".join(el))
        n_raise = int(_is_raise.sum())
        n_lower = int((~_is_raise).sum())
        net_signed = float((_absd * np.where(_is_raise, 1.0, -1.0)).sum())
        abs_sum = float(_absd.sum())
        net_dir = "淨抬升" if net_signed > 0 else ("淨降低" if net_signed < 0 else "淨值近零")
        lines.append(f"事件方向統計：抬升 {n_raise} 次、降低 {n_lower} 次。"
                     f"帶正負號的淨半長軸變化 Δa_net = {net_signed:+.4f} km（{net_dir}）；"
                     f"各事件 |Δa| 絕對值加總 = {abs_sum:.3f} km——此值僅代表機動活動量級，"
                     "恒為正、不代表方向。"
                     f"（註：上列統計與 Δa_net 均由偵測系統就「全部 {n} 次事件」計算所得，"
                     "為本題給定之輸入事實；上方事件清單僅為可讀性節錄前 10 筆，"
                     "故 Δa_net 無法、也不需由清單自行推算，請直接採用。）")
        lines.append("請根據以上偵測結果解說：這種半長軸跳變模式最可能對應哪種機動類型"
                     "（軌道維持、軌道抬升、避碰或離軌）？機動後 TLE 失效對 conjunction "
                     "screening 有什麼影響？（判斷機動方向請「務必以帶正負號的 Δa_net 為準」——"
                     "Δa_net 為正才可能是軌道抬升、為負屬軌道降低／離軌，切勿把絕對值加總當成淨值，"
                     "也不要只憑檢索到的文件主題判斷方向。）")
    else:
        lines.append("請解說：此期間未偵測到明顯機動的可能原因有哪些？"
                     "大氣阻力造成的自然衰減與推進機動在 TLE 半長軸變化上如何區分？")
    return "\n".join(lines)


def detect(con, f107, norad):
    """回傳 (event_df, alt_avg, orbit_class, net_da) 或 None。"""
    df = load_tle(con, norad)
    if df.empty or len(df) < 8:
        return None
    tr = ms.build_transitions(df, f107)
    if not len(tr):
        return None
    a0, e0, i0 = float(df["sma_km"].iloc[0]), float(df["eccentricity"].iloc[0]), \
        float(df["inclination_deg"].iloc[0])
    oc = ms.classify_orbit(a0, e0, i0)
    res = ms.apply_strategies(tr, oc)
    comb = res["combined"]
    if comb is None or not len(comb) or not comb.any():
        return None
    et = tr[comb].copy()
    ev = pd.DataFrame({
        "epoch": et["epoch"].to_numpy(),
        "sma_delta": et["da_km"].abs().to_numpy(),
        "sma_direction": np.where(et["da_km"].to_numpy() > 0, "raise", "lower"),
    })
    return ev, float(tr["alt_km"].mean()), oc, float(et["da_km"].sum()), \
        str(df["epoch"].min().date()), str(df["epoch"].max().date())


def pick_candidates(con, want=10, seed=SEED):
    """挑酬載衛星（排除殘骸/RB），優先有偵測事件、且兼顧抬升/降低方向多樣。"""
    cat = con.execute(
        "SELECT norad_id, ANY_VALUE(object_name) AS name, COUNT(*) n "
        "FROM raw_tle_archive GROUP BY norad_id HAVING n>=20").fetchdf()
    cat = cat[~cat["name"].fillna("").str.upper().str.contains("|".join(_EXCLUDE))]
    cat = cat[~cat["norad_id"].isin(_TESTED)]
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(cat))
    f107 = load_f107()
    half = want // 2
    raise_dom, lower_dom = [], []
    scanned = 0
    for idx in order:
        if scanned >= 600:
            break
        scanned += 1
        row = cat.iloc[int(idx)]
        nid = int(row["norad_id"])
        try:
            r = detect(con, f107, nid)
        except Exception:
            continue
        if r is None:
            continue
        ev, alt, oc, net_da, dmin, dmax = r
        rec = {"norad": nid, "name": str(row["name"]), "orbit": oc, "alt_km": alt,
               "n_events": len(ev), "net_da_km": net_da, "dmin": dmin, "dmax": dmax,
               "ev": ev}
        (raise_dom if net_da >= 0 else lower_dom).append(rec)
        if len(lower_dom) >= half and len(raise_dom) >= (want - half):
            break
    # 平衡取樣：一半抬升主導、一半降低主導（降低事件用來壓測方向紀律）
    half = want // 2
    picks = lower_dom[:half] + raise_dom[:want - half]
    if len(picks) < want:  # 補足
        extra = (raise_dom[want - half:] + lower_dom[half:])
        picks += extra[:want - len(picks)]
    return picks[:want]


def pick_geo(con, want=10, seed=SEED, min_events=15):
    """專挑 GEO/GEO+ 站位保持衛星：多筆微小混合事件、淨值近零/負——正是
    『GEO 絕對加總幻覺』的壓測案例。優先 |淨Δa| 小且事件數多者。"""
    cat = con.execute(
        "SELECT norad_id, ANY_VALUE(object_name) AS name, COUNT(*) n "
        "FROM raw_tle_archive GROUP BY norad_id HAVING n>=20").fetchdf()
    cat = cat[~cat["name"].fillna("").str.upper().str.contains("|".join(_EXCLUDE))]
    cat = cat[~cat["norad_id"].isin(_TESTED)]
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(cat))
    f107 = load_f107()
    geo = []
    scanned = 0
    for idx in order:
        if scanned >= 1500 or len(geo) >= want * 4:
            break
        scanned += 1
        row = cat.iloc[int(idx)]
        nid = int(row["norad_id"])
        try:
            r = detect(con, f107, nid)
        except Exception:
            continue
        if r is None:
            continue
        ev, alt, oc, net_da, dmin, dmax = r
        if not oc.startswith("GEO") or len(ev) < min_events:
            continue
        geo.append({"norad": nid, "name": str(row["name"]), "orbit": oc, "alt_km": alt,
                    "n_events": len(ev), "net_da_km": net_da, "dmin": dmin,
                    "dmax": dmax, "ev": ev})
    # 排序：|淨Δa| 小（方向最難判）且事件多者優先
    geo.sort(key=lambda p: (abs(p["net_da_km"]), -p["n_events"]))
    return geo[:want]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--exclude", default="", help="逗號分隔 NORAD，排除已測")
    ap.add_argument("--norads", default="", help="逗號分隔 NORAD，指定重跑（略過隨機挑選）")
    ap.add_argument("--geo", action="store_true", help="專挑 GEO 站位保持衛星壓測")
    ap.add_argument("--tag", default="", help="輸出檔名後綴")
    args = ap.parse_args()
    if args.exclude.strip():
        _TESTED.update(int(x) for x in args.exclude.split(",") if x.strip())

    client = SSARAGClient(base_url=BASE_URL, timeout=180.0)
    if not client.health():
        print("SSA-RAG 服務未上線，中止。")
        sys.exit(2)

    con = duckdb.connect(DB_PATH, read_only=True)
    if args.norads.strip():
        f107 = load_f107()
        nlist = [int(x) for x in args.norads.split(",") if x.strip()]
        catn = con.execute(
            "SELECT norad_id, ANY_VALUE(object_name) AS name FROM raw_tle_archive "
            "GROUP BY norad_id").fetchdf().set_index("norad_id")["name"].to_dict()
        picks = []
        for nid in nlist:
            r = detect(con, f107, nid)
            if r is None:
                print(f"  {nid}: 無偵測事件，略過")
                continue
            ev, alt, oc, net_da, dmin, dmax = r
            picks.append({"norad": nid, "name": str(catn.get(nid, nid)), "orbit": oc,
                          "alt_km": alt, "n_events": len(ev), "net_da_km": net_da,
                          "dmin": dmin, "dmax": dmax, "ev": ev})
        print(f"指定重跑 {len(picks)} 顆")
    elif args.geo:
        print(f"SSA-RAG 服務正常（{BASE_URL}）· GEO 壓測 · seed={args.seed} · 已排除 {len(_TESTED)} 顆")
        picks = pick_geo(con, want=10, seed=args.seed)
    else:
        print(f"SSA-RAG 服務正常（{BASE_URL}）· seed={args.seed} · 已排除 {len(_TESTED)} 顆")
        picks = pick_candidates(con, want=10, seed=args.seed)
    con.close()
    print(f"挑選 {len(picks)} 顆酬載衛星（有 P1–P6 偵測事件）：")
    for p in picks:
        print(f"  {p['norad']:>6}  {p['name'][:24]:24}  {p['orbit']:5}  "
              f"alt~{p['alt_km']:.0f}km  事件{p['n_events']:>2}  淨Δa {p['net_da_km']:+.2f}km")

    rows = []
    for i, p in enumerate(picks, 1):
        narr = build_tle_narrative(p["norad"], p["alt_km"], p["dmin"], p["dmax"], p["ev"])
        print(f"\n[{i}/{len(picks)}] NORAD {p['norad']} ({p['name'][:20]}) 送 RAG…")
        try:
            res = client.ask(narr, topic="maneuver", client_id="maneuver_app_july_test")
        except Exception as e:
            print(f"   查詢失敗：{e}")
            rows.append({**{k: p[k] for k in ("norad", "name", "orbit", "alt_km",
                        "n_events", "net_da_km")}, "confidence": "ERR",
                        "answer": f"ERR:{e}", "n_sources": 0,
                        "claims_raise": None, "sign_conflict": None})
            continue
        ans = res.answer
        cr = claims_raising_in_conclusion(ans)
        sc = sign_conflict(ans, p["net_da_km"])
        print(f"   信心 {res.confidence} · 來源 {len(res.sources)} · "
              f"結論宣稱抬升={cr} · 方向矛盾={sc}")
        print(f"   答：{ans[:120].replace(chr(10), ' ')}…")
        rows.append({
            "norad": p["norad"], "name": p["name"], "orbit": p["orbit"],
            "alt_km": round(p["alt_km"], 1), "n_events": p["n_events"],
            "net_da_km": round(p["net_da_km"], 3), "confidence": res.confidence,
            "n_sources": len(res.sources), "claims_raise": cr, "sign_conflict": sc,
            "answer": ans.replace("\n", " "),
        })

    out = pd.DataFrame(rows)
    _suffix = args.tag or ("norads" if args.norads.strip() else
                           ("geo" if args.geo else f"seed{args.seed}"))
    fp = Path("docs") / f"rag_test_july_10sat_{_suffix}.csv"
    out.to_csv(fp, index=False, encoding="utf-8-sig")

    n = len(out)
    conflicts = int(out["sign_conflict"].fillna(False).sum())
    neg = out[out["net_da_km"] < 0]
    print("\n" + "=" * 60)
    print(f"完成 {n} 顆。方向矛盾（負淨Δa卻判抬升）：{conflicts} / {len(neg)} 負向樣本")
    print("信心分佈：", out["confidence"].value_counts().to_dict())
    print(f"輸出 → {fp}")


if __name__ == "__main__":
    main()
