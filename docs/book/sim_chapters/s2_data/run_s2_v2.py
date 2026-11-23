"""延伸篇 S2 修訂版（審查意見 Major Revision）之壅擠推演：固定快照與推演時刻，主結果、收斂測試、殼層敏感度與第三方分解。

用法：python docs/book/sim_chapters/s2_data/run_s2_v2.py --server http://127.0.0.1:5193 [--part main,conv,shells]
- 目錄快照：s2_data/snapshot/space_db_slim_20261123.duckdb（伺服器以 --db 指定）；推演起點固定 T0。
- 伺服器另以 --data 指向不含 user_defined_TLE 的空目錄，排除使用者自訂的測試 TLE（NORAD 99001）。
- 需 Rust 單機版 2026-11-23 以後版本（crowd API 接受 t0、watch、自訂 shells，並回傳 third_party）。
輸出：s2_data/v2/crowd_main.json、crowd_conv.json、crowd_shells.json
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
OUT = HERE / "v2"
OUT.mkdir(exist_ok=True)

T0 = "2026-11-23T00:00:00Z"
PLAN = {"starlink": 34396, "kuiper": 3236, "qianfan": 10800, "guowang": 12992}
MEGA = {"starlink": 100000, "kuiper": 20000, "qianfan": 10000}
# 台灣衛星（目錄 country＝Taiwan／TWN 之有效載荷）
TAIWAN = [28254, 29047, 29048, 29049, 29050, 29051, 29052, 42920, 44343, 44349, 44350, 44351, 44353, 44358,
          58017, 62619, 62684, 66666, 68980, 68990]

# Starlink 殼層配置敏感度（顆數皆以 PLAN 34,396 縮放）
GEN1 = [[550, 53, 72, 22], [540, 53.2, 72, 22], [570, 70, 36, 20], [560, 97.6, 6, 58], [560, 97.6, 4, 43]]
STARLINK_ALT = {
    # FCC DA 26-36（2026-01-09）擴大核准之 Gen2 殼層；各殼顆數文件未逐殼列出，此處平均分配（示意）
    "da2636": GEN1 + [[h, i, 72, 23] for h, i in [(340, 53), (345, 48), (350, 38), (355, 43), (360, 96.9), (365, 32)]]
                   + [[h, i, 56, 30] for h, i in [(475, 32), (480, 53), (485, 43)]],
    # DA 26-36 未逐殼列出顆數，只列上限並允許在核准殼層間彈性部署；以兩個極端為界：
    # Gen2 15,000 顆全部放在 400 km 以下六殼（各 72 面 × 35 顆），或全部放在 475–485 km 三殼（各 56 面 × 90 顆）
    "da2636_low": GEN1 + [[h, i, 72, 35] for h, i in [(340, 53), (345, 48), (350, 38), (355, 43), (360, 96.9), (365, 32)]],
    "da2636_high": GEN1 + [[h, i, 56, 90] for h, i in [(475, 32), (480, 53), (485, 43)]],
    # 同總數平均分散於 340–610 km、每 30 km 一殼、傾角 53°（對照：不集中於少數殼層）
    "spread53": [[h, 53, 60, 60] for h in range(340, 611, 30)],
    # 全部集中於 Gen1 兩個 53° 殼層（對照：極端集中）
    "two53": [[550, 53, 72, 22], [540, 53.2, 72, 22]],
}


def post(server, body, timeout=7200):
    req = urllib.request.Request(server + "/api/games/crowd", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    d.pop("shells", None)
    d.pop("density", None) if body.get("_nodens") else None
    print(f"  {time.time() - t:6.1f} s  {json.dumps({k: v for k, v in body.items() if k != 'groups'})}", flush=True)
    return d


def groups(src, starlink_shells=None):
    out = []
    for k, n in src.items():
        g = {"key": k, "synthetic": True, "total": n}
        if k == "starlink" and starlink_shells:
            g["shells"] = starlink_shells
        out.append(g)
    return out


def summ(d):
    """只留章節需要的欄位（第三方網格另存）"""
    return {k: d[k] for k in ("t0", "hours", "step_s", "d_km", "skip", "baseline", "scenario", "elapsed_s")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5193")
    ap.add_argument("--part", default="main,conv,shells,taiwan")
    a = ap.parse_args()
    parts = a.part.split(",")
    base = {"hours": 2, "step_s": 60, "d_km": 20, "t0": T0}

    if "main" in parts:
        out = {"t0": T0, "snapshot": "space_db_slim_20261123.duckdb", "runs": {}}
        for kind, src in [("plan", PLAN), ("mega", MEGA)]:
            for skip in [0, 1, 2]:
                d = post(a.server, {**base, "groups": groups(src), "skip": skip, "watch": TAIWAN})
                out["runs"][f"{kind}_skip{skip}"] = d
        (OUT / "crowd_main.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    if "conv" in parts:
        out = {"t0": T0, "runs": []}
        for kind, src in [("plan", PLAN), ("mega", MEGA)]:
            tests = [("hours", h, {"hours": h}) for h in (2, 6, 12, 24)]
            tests += [("step_s", s, {"step_s": s}) for s in (10, 30, 120)]
            tests += [("d_km", dk, {"d_km": dk}) for dk in (10, 50)]
            tests += [("t0_offset_h", o, {"t0": f"2026-11-23T{o:02d}:00:00Z"}) for o in (3, 6, 9, 12, 15, 18, 21)]
            for axis, val, over in tests:
                d = post(a.server, {**base, **over, "groups": groups(src), "skip": 1})
                out["runs"].append({"kind": kind, "axis": axis, "value": val, **summ(d)})
                (OUT / "crowd_conv.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    if "shells" in parts:
        out = {"t0": T0, "runs": []}
        for name, sh in [("template", None)] + list(STARLINK_ALT.items()):
            for skip in [0, 1, 2]:
                d = post(a.server, {**base, "groups": groups(PLAN, sh), "skip": skip})
                out["runs"].append({"config": name, "shells": sh, **summ(d)})
                (OUT / "crowd_shells.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    if "taiwan" in parts:
        # 單顆衛星在 2 小時取樣中多半 0 次或 1 次（換算為數百次／年），統計上無意義；改以 24 小時取樣並合計
        out = {"t0": T0, "runs": {}}
        for kind, src in [("plan", PLAN), ("mega", MEGA)]:
            d = post(a.server, {**base, "hours": 24, "groups": groups(src), "skip": 1, "watch": TAIWAN})
            out["runs"][kind] = {**summ(d), "third_party": d["third_party"]}
            (OUT / "crowd_taiwan24h.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
