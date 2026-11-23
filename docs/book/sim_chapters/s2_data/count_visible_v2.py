"""延伸篇 S2 修訂版：由 fetch_astro_v2.py 的曝光資料計算「看得見」的光跡數、來源分解與敏感度。

看得見：光跡在任一像素的貢獻超過 k 倍天空雜訊（預設 k = 3），光子模型見 ../_photon.py。
疊加情境 = 現況目錄全部光跡＋取代情境中的假想衛星光跡（_photon.overlay）。
敏感度（只改計數，不重抓光跡）：Starlink m₁₀₀₀（4.5／5.0／5.8／6.5；目錄與假想 Starlink 光跡之星等同步平移）、
可見門檻 k（2／3／5）、天空亮度 ±0.5 等／平方角秒。曝光時間與視野之敏感度另以 astro_inst.json 重抓之光跡計算。
用法：python docs/book/sim_chapters/s2_data/count_visible_v2.py
輸出：s2_data/v2/astro_summary.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.stdout.reconfigure(encoding="utf-8")
from _photon import Camera, overlay  # noqa: E402

V2 = HERE / "v2"
M1000_BASE = 5.8


def source(s):
    if s["range_km"] > 30000:
        return "高軌（GEO 等）"
    if (s.get("kind") or "") == "假想" or s["name"].startswith("假想"):
        return "假想星座"
    k = s.get("kind") or ""
    if k == "火箭體":
        return "火箭體"
    if k == "碎片":
        return "碎片"
    if s["group"] > 0:
        return "目錄中的星座衛星"
    return "其他衛星"


def in_fov(s, half):
    return any(abs(x) <= half and abs(y) <= half for x, y in s["pts"])


def count(P, kind, k=3.0, dmu=0.0, m1000=M1000_BASE, fov=None, exp=None):
    fov = fov or P["fov_deg"]
    exp = exp or P["exp_s"]
    cam = Camera(fov, P["D_m"], P["mu"] + dmu, exp)
    half = fov / 2
    fr_now, fr_mega = P["frames"]["now"], P["frames"]["mega"]
    frs = fr_now if kind == "now" else [overlay(a, b) for a, b in zip(fr_now, fr_mega)]
    rows = []
    for f in frs:
        if f.get("dropped"):
            rows.append(None)
            continue
        _, _, sig = cam.sky(f["sun_alt"])
        vis = raw = 0
        src = {}
        for s in f["streaks"]:
            if not in_fov(s, half):
                continue
            raw += 1
            mag = s["mag"] + ((m1000 - M1000_BASE) if s["group"] == 1 else 0.0)
            if float(cam.trail(s["pts"], mag).max()) > k * sig:
                vis += 1
                src[source(s)] = src.get(source(s), 0) + 1
        rows.append({"t": f["t"], "raw": raw, "visible": vis, "src": src})
    return rows


def summarize(rows, first_n=7):
    first = rows[:first_n]
    ok_first = [r for r in first if r]
    rest = [r for r in rows[first_n:] if r]
    src = {}
    for r in rows:
        if r:
            for a, b in r["src"].items():
                src[a] = src.get(a, 0) + b
    return {"first_n": len(ok_first),
            "first_mean": (sum(r["visible"] for r in ok_first) / len(ok_first)) if ok_first else None,
            "rest_total": sum(r["visible"] for r in rest), "rest_n": len(rest),
            "night_visible": sum(r["visible"] for r in rows if r), "night_raw": sum(r["raw"] for r in rows if r),
            "n_frames": len([r for r in rows if r]), "src": src}


def main():
    out = {}
    base = json.loads((V2 / "astro_base.json").read_text(encoding="utf-8"))
    out["base"] = {}
    for key, P in base["sets"].items():
        out["base"][key] = {kind: summarize(count(P, kind)) for kind in ("now", "add")}
        out["base"][key]["per_frame"] = {kind: count(P, kind) for kind in ("now", "add")}
    # 敏感度：鹿林兩個指向與台北兩個指向
    sens = {}
    for key in ["lulin/north", "lulin/dusk60", "taipei/north", "taipei/dusk60"]:
        P = base["sets"][key]
        S = sens[key] = {}
        for m in (4.5, 5.0, 5.8, 6.5):
            S[f"m1000={m}"] = {kd: summarize(count(P, kd, m1000=m)) for kd in ("now", "add")}
        for k in (2.0, 5.0):
            S[f"k={k:g}"] = {kd: summarize(count(P, kd, k=k)) for kd in ("now", "add")}
        for dmu in (-0.5, 0.5):
            S[f"mu{dmu:+g}"] = {kd: summarize(count(P, kd, dmu=dmu)) for kd in ("now", "add")}
    out["sens"] = sens
    for name in ("dates", "scan", "inst"):
        p = V2 / f"astro_{name}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        out[name] = {key: {kind: summarize(count(P, kind)) for kind in ("now", "add")} | {"t0": P["t0"], "fov": P["fov_deg"], "exp": P["exp_s"]}
                     for key, P in d["sets"].items()}
    (V2 / "astro_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for sec in ("base", "dates", "scan", "inst"):
        for key, v in out.get(sec, {}).items():
            a, b = v["now"], v["add"]
            f = lambda x: "—" if x is None else f"{x:.1f}"
            print(f"{sec:5s} {key:22s} 第一小時 {f(a['first_mean'])} → {f(b['first_mean'])}（{a['first_n']}）｜之後 {a['rest_total']} → {b['rest_total']}（{a['rest_n']}）"
                  f"｜整夜可見 {a['night_visible']} → {b['night_visible']}、穿過 {a['night_raw']} → {b['night_raw']}｜來源(疊加) {b['src']}")
    for key, S in sens.items():
        for lab, v in S.items():
            print(f"sens {key:14s} {lab:10s} 第一小時 {v['now']['first_mean']:.1f} → {v['add']['first_mean']:.1f}｜整夜 {v['now']['night_visible']} → {v['add']['night_visible']}")


if __name__ == "__main__":
    main()
