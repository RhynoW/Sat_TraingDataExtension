"""延伸篇 S2 的推演：呼叫 Rust 單機版「星座壅擠」與「天文夢魘」API，結果存成 JSON。

用法：python docs/book/sim_chapters/s2_data/run_s2.py --server http://127.0.0.1:<埠>
- 星座壅擠以伺服器「現在」為 t0（API 不收 t0），所以每次重跑會有小幅差異。
- 天文夢魘的曝光時刻固定（DUSK）；假想星座的相位以伺服器現在為基準（與星座壅擠一致），重跑也會有小幅差異。
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

PLAN = {"starlink": 34396, "kuiper": 3236, "qianfan": 10800, "guowang": 12992}
MEGA = {"starlink": 100000, "kuiper": 20000, "qianfan": 10000}
SITES = {"lulin": (23.4686, 120.8736, 2.862), "taipei": (25.03, 121.56, 0.01)}
TARGETS = {"M45": (56.75, 24.12)}
# 各地太陽仰角首次 ≤ −13° 的時刻（2026-11-22，以本 API 的 sun_alt 逐分鐘搜尋；同遊戲「跳到今晚天文昏影」）
DUSK = {"lulin": "2026-11-22T10:07:00Z", "taipei": "2026-11-22T10:02:00Z"}


def gmst_deg(t):
    """IAU 1982 GMST（度），與前端 Astronomy.SiderealTime 同一量級精度。"""
    d = (t - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400
    T = d / 36525
    return (280.46061837 + 360.98564736629 * d + 0.000387933 * T * T - T ** 3 / 38710000) % 360


def altaz2radec(alt, az, lat, lon, t):
    """同 games_astro.js 的 altaz2radec：方位（北起算向東）、仰角 → 當日赤經赤緯。"""
    lst = math.radians(gmst_deg(t) + lon)
    a, z, p = map(math.radians, (alt, az, lat))
    dec = math.asin(math.sin(a) * math.sin(p) + math.cos(a) * math.cos(p) * math.cos(z))
    H = math.atan2(-math.sin(z) * math.cos(a), math.sin(a) * math.cos(p) - math.cos(a) * math.sin(p) * math.cos(z))
    return (math.degrees(lst - H) % 360, math.degrees(dec))


def post(server, path, body, timeout=900):
    req = urllib.request.Request(server + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    print(f"  {path} {time.time() - t:.1f} s")
    return d


def groups(kind):
    if kind == "now":
        return []
    src = PLAN if kind == "plan" else MEGA
    return [{"key": k, "synthetic": True, "total": n} for k, n in src.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5093")
    a = ap.parse_args()
    out = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "server": a.server, "crowd": {}, "astro": {}}

    shells = json.load(urllib.request.urlopen(a.server + "/api/games/crowd/shells"))
    out["catalog_groups"] = shells["groups"]

    # 星座壅擠：三種情境 × 配對規則（0 全計、1 同殼層不計、2 同星座不計），取樣 2 小時、每 60 秒
    for kind in ["plan", "mega"]:
        for skip in [0, 1, 2]:
            print(f"crowd {kind} skip={skip}")
            d = post(a.server, "/api/games/crowd", {"groups": groups(kind), "hours": 2, "step_s": 60, "d_km": 20, "skip": skip})
            d.pop("shells", None)
            out["crowd"][f"{kind}_skip{skip}"] = d

    # 天文夢魘：鹿林與台北，Rubin 級（視野 3.5°）30 秒；現況與 10 萬 Starlink
    #  - dusk：昏影（太陽 −13°）時指向方位 250°、仰角 35°（遊戲預設），整夜統計從該時刻起 14 小時
    #  - dusk60：同方位、仰角 60°（避開地球同步軌道帶）
    #  - north：正北、仰角 45°（拱極天區，整夜可觀測，含黎明前）
    #  - m45：同一起點，改指向昴宿星團（傍晚在東方低空）
    for site, (lat, lon, h) in SITES.items():
        t0 = dt.datetime.fromisoformat(DUSK[site].replace("Z", "+00:00"))
        pts = {"dusk": altaz2radec(35, 250, lat, lon, t0), "dusk60": altaz2radec(60, 250, lat, lon, t0),
               "north": altaz2radec(45, 0, lat, lon, t0), "m45": TARGETS["M45"]}
        for pk, (ra, dec) in pts.items():
            for kind in ["now", "mega"]:
                print(f"astro {site} {pk} {kind}")
                d = post(a.server, "/api/games/astro", {"lat": lat, "lon": lon, "h_km": h, "ra_deg": ra, "dec_deg": dec,
                                                       "fov_deg": 3.5, "exp_s": 30, "t": DUSK[site], "groups": groups(kind), "night": True})
                for s in d.get("streaks", []):
                    s.pop("pts", None)
                d["ra_deg"], d["dec_deg"] = ra, dec
                out["astro"][f"{site}_{pk}_{kind}"] = d

    p = HERE / "s2_results.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p)


if __name__ == "__main__":
    main()
