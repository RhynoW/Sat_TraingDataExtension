#!/usr/bin/env python3
"""rag_test_100sat.py — 100 顆衛星 × SSA-RAG 批次測試（10 批 × 10 顆）
================================================================
復用 rag_test_july_10sat 的偵測管線與 narrative。每批 10 顆換一個種子、
累積排除已測（含前幾輪 30 顆），每批完成後把該批摘要送 SSA-RAG Server 信箱。

輸出：docs/rag_test_100sat_batch{01..10}.csv、docs/rag_test_100sat_all.csv
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import pandas as pd

import rag_test_july_10sat as T
from ssa_rag_client import SSARAGClient
from app_dialogue_client import DialogueClient
from rag_answer_check import sign_conflict, claims_raising_in_conclusion

BASE_SEED = 700000
N_BATCHES = 10
WANT = 10

# 節流（Server/Client 同時運作時避免請求過密而當機）：
# 一次只送 1 筆、每筆間隔 5 秒；累積 10 筆後間隔 10 秒再送該批 Summary。
# （2026-07-16 使用者指示沿革：原 5／10 → 減 2 秒為 3／8 → 再 +2 秒回到 5／10）
GAP_PER_SAT_S = 5.0
GAP_BEFORE_SUMMARY_S = 10.0

# 前幾輪已測（R12/R13/GEO 壓測），避免重複
PREV_TESTED = {
    58986, 48357, 31306, 31307, 56134, 24665, 28472, 68777, 52791, 33436,
    52904, 56226, 57653, 50823, 47630, 69513, 22112, 68704, 66606, 65408,
    18583, 12618, 3623, 28520, 15057, 25546, 39498, 33521, 38245, 42692,
}


def batch_summary_text(b: int, dfb: pd.DataFrame, n_batches: int = 10) -> str:
    n = len(dfb)
    neg = dfb[dfb["net_da_km"] < 0]
    conflicts = dfb[dfb["sign_conflict"].fillna(False)]
    conf = dfb["confidence"].value_counts().to_dict()
    orb = dfb["orbit"].value_counts().to_dict()
    sats = "、".join(f"{r.norad}({r.orbit},{r.net_da_km:+.2f})" for r in dfb.itertuples())
    lines = [
        f"Client 第 {b} 批（10 顆）RAG 測試完成：",
        f"衛星＝{sats}。",
        f"軌域分佈 {orb}；信心分佈 {conf}。",
        f"負向淨Δa 樣本 {len(neg)} 顆，符號檢查器旗標方向矛盾 {len(conflicts)} 顆"
        + ("（" + "、".join(str(int(x)) for x in conflicts["norad"]) + "）"
           if len(conflicts) else "（無）")
        + "。旗標為 Client 端 rag_answer_check v3 結果（已修否定詞與列舉式括號對句兩類誤報）。",
    ]
    return "\n".join(lines)


CRASH_WAIT_S = 180.0        # SSA-RAG 當機後等待 3 分鐘再續測（使用者指示 2026-07-17）
CRASH_POLL_S = 15.0


def ask_with_retry(client, narr: str, tries: int = 3):
    """送一筆查詢；連線失敗（SSA-RAG 當機）時等待 3 分鐘讓服務回來再重試。

    實測第 5 輪曾因服務連續中斷 7 批、產生 61 筆 ERR；重試機制即為此而設。
    等待期間每 15 秒探一次 /health，提早恢復就提早續測（不自行啟動 uvicorn——
    依約定由 Server 端負責）。回傳 (answer, confidence, n_sources)。
    """
    last = ""
    for k in range(tries):
        try:
            r = client.ask(narr, topic="maneuver", client_id="maneuver_app_july_100test")
            return r.answer, r.confidence, len(r.sources)
        except Exception as e:
            last = str(e)
            if k == tries - 1:
                break
            print(f"    ⚠ SSA-RAG 連線失敗（第 {k+1}/{tries} 次），等待 "
                  f"{CRASH_WAIT_S:.0f} 秒讓服務恢復…", flush=True)
            waited = 0.0
            while waited < CRASH_WAIT_S:
                time.sleep(CRASH_POLL_S)
                waited += CRASH_POLL_S
                try:
                    if client.health():
                        print(f"    ✓ 服務已恢復（等待 {waited:.0f} 秒），續測。", flush=True)
                        break
                except Exception:
                    pass
    return f"ERR:{last}", "ERR", 0


def prior_tested_from_csvs(prefix_glob: str) -> set:
    """從既有結果 CSV 收集已測 NORAD（跨輪累積排除）。"""
    out = set()
    for f in sorted(glob.glob(prefix_glob)):
        try:
            d = pd.read_csv(f)
        except Exception:
            continue
        col = "norad" if "norad" in d.columns else None
        if col and len(d):
            out.update(int(x) for x in d[col])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1, help="第幾輪（1=batch01-10）")
    ap.add_argument("--batches", type=int, default=N_BATCHES,
                    help="本輪批數（每批 10 顆；200 顆＝20）")
    ap.add_argument("--batch-offset", type=int, default=None,
                    help="全域批號起始偏移（預設 (round-1)*10）")
    args = ap.parse_args()
    rnd = args.round
    n_batches = args.batches
    offset = args.batch_offset if args.batch_offset is not None else (rnd - 1) * N_BATCHES
    prefix = "" if rnd == 1 else f"r{rnd}_"
    base_seed = BASE_SEED + (rnd - 1) * 100000

    client = SSARAGClient(base_url=T.BASE_URL, timeout=180.0)
    if not client.health():
        print("SSA-RAG 服務未上線，中止。")
        sys.exit(2)

    # 跨輪累積排除：前幾輪 30 顆 + 所有既有 100sat 結果
    tested = set(PREV_TESTED) | prior_tested_from_csvs("docs/rag_test_100sat_*batch*.csv")
    print(f"SSA-RAG 服務正常（{T.BASE_URL}）· 第 {rnd} 輪 {n_batches*WANT} 顆 = "
          f"{n_batches} 批 × {WANT} 顆 · 已排除 {len(tested)} 顆 · "
          f"節流 {GAP_PER_SAT_S:.0f}s/筆、{GAP_BEFORE_SUMMARY_S:.0f}s/批摘要")

    dlg = DialogueClient()
    dlg.send(f"Client 開始第 {rnd} 輪 {n_batches*WANT} 顆衛星 RAG 批次測試"
             f"（{n_batches} 批 × {WANT} 顆，累積排除已測 {len(tested)} 顆；"
             f"節流調整為每筆 {GAP_PER_SAT_S:.0f} 秒、每批摘要前 {GAP_BEFORE_SUMMARY_S:.0f} 秒）；"
             "每批完成即回報該批摘要。")

    all_rows = []

    for b in range(1, n_batches + 1):
        seed = base_seed + b
        gb = b + offset                       # 全域批號（r2＝11..20、r4＝31..50）
        fp = Path("docs") / f"rag_test_100sat_{prefix}batch{gb:02d}.csv"
        # 續跑：已完成且有效的批次直接沿用（曾因服務/工作階段中斷需重跑）
        if fp.exists():
            try:
                prev = pd.read_csv(fp)
            except Exception:
                prev = pd.DataFrame()
            n_err = int((prev["confidence"] == "ERR").sum()) if len(prev) and \
                "confidence" in prev.columns else 0
            if len(prev) and "norad" in prev.columns and n_err == 0:
                tested.update(int(x) for x in prev["norad"])
                all_rows.extend(prev.to_dict("records"))
                print(f"\n===== 第 {gb} 批：沿用既有結果 {len(prev)} 顆（{fp.name}）=====",
                      flush=True)
                continue
            if n_err:
                print(f"\n===== 第 {gb} 批：既有結果含 {n_err} 筆 ERR → 整批重跑 =====",
                      flush=True)
            fp.unlink(missing_ok=True)   # 壞檔／含 ERR → 重跑

        T._TESTED = set(tested)          # pick_candidates 依模組級 _TESTED 排除
        con = duckdb.connect(T.DB_PATH, read_only=True)
        picks = T.pick_candidates(con, want=WANT, seed=seed)
        con.close()
        print(f"\n===== 第 {gb} 批（seed={seed}）挑到 {len(picks)} 顆 =====", flush=True)

        batch_rows = []
        for i, p in enumerate(picks, 1):
            tested.add(p["norad"])
            narr = T.build_tle_narrative(p["norad"], p["alt_km"], p["dmin"], p["dmax"], p["ev"])
            ans, conf, nsrc = ask_with_retry(client, narr)
            cr = claims_raising_in_conclusion(ans) if conf != "ERR" else None
            sc = sign_conflict(ans, p["net_da_km"]) if conf != "ERR" else None
            print(f"  [{gb}.{i}] {p['norad']:>6} {p['name'][:20]:20} {p['orbit']:5} "
                  f"淨{p['net_da_km']:+.2f} · 信心{conf} · 矛盾{sc}", flush=True)
            batch_rows.append({
                "batch": gb, "norad": p["norad"], "name": p["name"], "orbit": p["orbit"],
                "alt_km": round(p["alt_km"], 1), "n_events": p["n_events"],
                "net_da_km": round(p["net_da_km"], 3), "confidence": conf,
                "n_sources": nsrc, "claims_raise": cr, "sign_conflict": sc,
                "answer": ans.replace("\n", " "),
            })
            if i < len(picks):
                time.sleep(GAP_PER_SAT_S)      # 每筆間隔 5 秒

        dfb = pd.DataFrame(batch_rows)
        dfb.to_csv(fp, index=False, encoding="utf-8-sig")
        time.sleep(GAP_BEFORE_SUMMARY_S)       # 累積 10 筆後間隔 10 秒再送 Summary
        dlg.send(batch_summary_text(gb, dfb))
        print(f"  → 批摘要已送 Server；存 {fp}", flush=True)
        all_rows.extend(batch_rows)

    out = pd.DataFrame(all_rows)
    fp_all = Path("docs") / f"rag_test_100sat_{prefix}all.csv"
    out.to_csv(fp_all, index=False, encoding="utf-8-sig")

    n = len(out)
    neg = out[out["net_da_km"] < 0]
    conflicts = out[out["sign_conflict"].fillna(False)]
    print("\n" + "=" * 60)
    print(f"完成 {n} 顆。負向樣本 {len(neg)}，符號矛盾旗標 {len(conflicts)}。")
    print("信心分佈：", out["confidence"].value_counts().to_dict())
    print("軌域分佈：", out["orbit"].value_counts().to_dict())
    dlg.send(
        f"Client 完成第 {rnd} 輪全部 {n} 顆（{n_batches} 批）RAG 測試：負向淨Δa 樣本 {len(neg)} 顆、"
        f"符號矛盾旗標 {len(conflicts)} 顆"
        + ("（NORAD " + "、".join(str(int(x)) for x in conflicts["norad"]) + "）"
           if len(conflicts) else "")
        + f"。信心分佈 {out['confidence'].value_counts().to_dict()}。"
        f"旗標由 rag_answer_check v3 判定（已修否定詞與列舉式括號兩類誤報）。明細存 {fp_all}。")
    dlg.end()
    print(f"輸出 → {fp_all}；彙總與 #Over# 已送 Server。")


if __name__ == "__main__":
    main()
