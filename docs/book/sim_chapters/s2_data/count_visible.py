"""延伸篇 S2：依光子模型（../_photon.py）計算每次曝光「看得見」的光跡數。

輸入：astro_frames.json（fetch_astro_frames.py）。輸出：astro_counts.json，以及章節表格用的摘要。
看得見：光跡在任一像素的貢獻超過 3 倍天空雜訊；天空亮度依地點，昏影時隨太陽仰角變亮。
用法：python docs/book/sim_chapters/s2_data/count_visible.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.stdout.reconfigure(encoding="utf-8")
from _photon import Camera, overlay  # noqa: E402


def in_fov(s, half):
    return any(abs(x) <= half and abs(y) <= half for x, y in s["pts"])


def main():
    d = json.loads((HERE / "astro_frames.json").read_text(encoding="utf-8"))
    out = {}
    for site, S in d["sites"].items():
        cam = Camera(S["fov_deg"], S["D_m"], S["mu"], d["exp_s"])
        half = S["fov_deg"] / 2
        for pk, P in S["pointings"].items():
            frames = dict(P["frames"])
            frames["add"] = [overlay(a, b) for a, b in zip(P["frames"]["now"], P["frames"]["mega"])]   # 現況＋假想星座
            for kind, fr in frames.items():
                rows = []
                for f in fr:
                    if f.get("dropped"):
                        rows.append(None)
                        continue
                    _, sky, sig = cam.sky(f["sun_alt"])
                    vis, raw, mags = 0, 0, []
                    for s in f["streaks"]:
                        if not in_fov(s, half):
                            continue
                        raw += 1
                        if cam.visible(cam.trail(s["pts"], s["mag"]), sig):
                            vis += 1
                            mags.append(s["mag"])
                    rows.append({"t": f["t"], "sun_alt": f["sun_alt"], "raw": raw, "visible": vis, "mags": mags})
                out[f"{site}/{pk}/{kind}"] = rows
    (HERE / "astro_counts.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("地點/指向/情境：第一小時（7 次曝光）平均看得見條數｜之後總條數（曝光數）｜全部穿過視野、不論可見")
    for key, rows in out.items():
        first = rows[:7]
        ok = [r for r in rows if r]
        rest = [r for r in rows[7:] if r]
        f_vis = sum(r["visible"] for r in first if r) / 7 if all(first) else None
        print(f"{key}: 第一小時 {f_vis if f_vis is None else round(f_vis, 2)}｜之後 {sum(r['visible'] for r in rest)}（{len(rest)}）｜"
              f"有效 {len(ok)} 次、看得見 {sum(r['visible'] for r in ok)}、穿過 {sum(r['raw'] for r in ok)}")


if __name__ == "__main__":
    main()
