"""延伸篇 S2 修訂版之光害曝光資料：固定目錄快照與假想星座相位基準（tref），擴充日期、指向、曝光時間與視野。

用法：python docs/book/sim_chapters/s2_data/fetch_astro_v2.py --server http://127.0.0.1:5193 [--part base,dates,scan,inst]
- base ：2026-11-22，鹿林與台北 × 正北仰角 45°、方位 250° 仰角 60° × 現況／取代情境（疊加由 count_visible_v2.py 合成），整夜每 10 分鐘
- dates：鹿林，2026-03-20、06-21、09-22、12-21，同兩個指向，整夜
- scan ：鹿林 2026-11-22，昏影後第一小時（7 次曝光），方位 0／90／180／270° 仰角 45° 與天頂
- inst ：鹿林 2026-11-22 正北仰角 45°，昏影後 2 小時（13 次曝光），曝光 10／60 秒（視野 3.5°）與視野 1°／7°（曝光 30 秒）
天色太亮（太陽 > −12°）或指向低於 20° 的曝光不送出，只記錄時刻（本地以低精度太陽公式判斷，誤差約 0.1°）。
輸出：s2_data/v2/astro_<part>.json
"""
import argparse
import datetime as dt
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_s2 import SITES, altaz2radec, gmst_deg  # noqa: E402

OUT = HERE / "v2"
OUT.mkdir(exist_ok=True)
TREF = "2026-11-23T00:00:00Z"      # 假想星座相位基準（與 run_s2_v2.py 之 T0 相同）
MEGA = {"starlink": 100000, "kuiper": 20000, "qianfan": 10000}
TEL = {"lulin": {"fov_deg": 3.5, "D_m": 6.4, "mu": 21.5}, "taipei": {"fov_deg": 1.0, "D_m": 0.2, "mu": 18.5}}
POINT = {"north": (45, 0), "dusk60": (60, 250)}


def sun_radec(t):
    """低精度太陽赤經赤緯（度），Meeus 簡化式，誤差約 0.01°。"""
    d = (t - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = (280.459 + 0.98564736 * d) % 360
    L = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    e = math.radians(23.439 - 0.00000036 * d)
    return math.degrees(math.atan2(math.cos(e) * math.sin(L), math.cos(L))) % 360, math.degrees(math.asin(math.sin(e) * math.sin(L)))


def alt_of(ra, dec, lat, lon, t):
    H = math.radians((gmst_deg(t) + lon - ra) % 360)
    p, d = math.radians(lat), math.radians(dec)
    return math.degrees(math.asin(math.sin(p) * math.sin(d) + math.cos(p) * math.cos(d) * math.cos(H)))


def dusk(site, day):
    """當地傍晚太陽仰角首次 ≤ −13° 的時刻（逐分鐘，自 UTC 08:00 起搜尋；台灣 UTC+8）"""
    lat, lon, _ = SITES[site]
    t = dt.datetime.fromisoformat(day + "T08:00:00+00:00")
    for _ in range(600):
        if alt_of(*sun_radec(t), lat, lon, t) <= -13:
            return t
        t += dt.timedelta(minutes=1)
    raise RuntimeError("找不到昏影")


def post(server, body):
    req = urllib.request.Request(server + "/api/games/astro", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def frames(server, site, t0, alt, az, n, fov=None, exp=30, kinds=("now", "mega"), radec=None):
    lat, lon, h = SITES[site]
    ra, dec = radec or altaz2radec(alt, az, lat, lon, t0)
    tel = TEL[site]
    fov = fov or tel["fov_deg"]
    base = {"lat": lat, "lon": lon, "h_km": h, "ra_deg": ra, "dec_deg": dec, "fov_deg": fov, "exp_s": exp,
            "night": False, "tref": TREF}
    P = {"site": site, "t0": t0.isoformat().replace("+00:00", "Z"), "alt": alt, "az": az, "ra_deg": ra, "dec_deg": dec,
         "fov_deg": fov, "exp_s": exp, "D_m": tel["D_m"], "mu": tel["mu"], "frames": {}}
    for kind in kinds:
        groups = [] if kind == "now" else [{"key": k, "synthetic": True, "total": v} for k, v in MEGA.items()]
        fr = []
        for k in range(n):
            tk = t0 + dt.timedelta(minutes=10 * k)
            sa = alt_of(*sun_radec(tk), lat, lon, tk)
            pa = alt_of(ra, dec, lat, lon, tk)
            ts = tk.isoformat().replace("+00:00", "Z")
            if sa > -12 or pa < 20:
                fr.append({"t": ts, "sun_alt": sa, "alt": pa, "dropped": True, "streaks": []})
                continue
            d = post(server, {**base, "t": ts, "groups": groups})
            fr.append({"t": ts, "sun_alt": d["sun_alt"], "alt": d["point_alt"], "shadowed": d["shadowed"],
                       "streaks": [{"name": s["name"], "group": s["group"], "kind": s.get("kind"), "mag": s["mag"],
                                    "range_km": s["range_km"], "pts": s["pts"]} for s in d["streaks"]]})
        P["frames"][kind] = fr
    return P


def save(name, obj):
    p = OUT / f"astro_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    print(p.name, f"{p.stat().st_size / 1e6:.1f} MB", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5193")
    ap.add_argument("--part", default="base,dates,scan,inst")
    a = ap.parse_args()
    parts = a.part.split(",")
    meta = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tref": TREF, "snapshot": "space_db_slim_20261123.duckdb"}
    if "base" in parts:
        out = {**meta, "sets": {}}
        for site in ["lulin", "taipei"]:
            t0 = dusk(site, "2026-11-22")
            for pk, (alt, az) in POINT.items():
                out["sets"][f"{site}/{pk}"] = frames(a.server, site, t0, alt, az, 84)
                print(site, pk, t0, flush=True)
            if site == "lulin":   # 昴宿星團（M45），傍晚在東方低空；昏影後第一小時
                out["sets"]["lulin/m45"] = frames(a.server, site, t0, None, None, 7, radec=(56.75, 24.12))
        save("base", out)
    if "dates" in parts:
        out = {**meta, "sets": {}}
        for day in ["2026-03-20", "2026-06-21", "2026-09-22", "2026-12-21"]:
            t0 = dusk("lulin", day)
            for pk, (alt, az) in POINT.items():
                out["sets"][f"{day}/{pk}"] = frames(a.server, "lulin", t0, alt, az, 84)
                print(day, pk, t0, flush=True)
            save("dates", out)
    if "scan" in parts:
        out = {**meta, "sets": {}}
        t0 = dusk("lulin", "2026-11-22")
        for name, (alt, az) in {"az0": (45, 0), "az90": (45, 90), "az180": (45, 180), "az270": (45, 270), "zenith": (89.5, 0)}.items():
            out["sets"][name] = frames(a.server, "lulin", t0, alt, az, 7)
            print("scan", name, flush=True)
        save("scan", out)
    if "inst" in parts:
        out = {**meta, "sets": {}}
        t0 = dusk("lulin", "2026-11-22")
        for name, kw in {"exp10": {"exp": 10}, "exp60": {"exp": 60}, "fov1": {"fov": 1.0}, "fov7": {"fov": 7.0}}.items():
            out["sets"][name] = frames(a.server, "lulin", t0, 45, 0, 13, **kw)
            print("inst", name, flush=True)
        save("inst", out)


if __name__ == "__main__":
    main()
