"""延伸篇 S2 影片的資料：14 小時內每 10 分鐘一次 30 秒曝光，鹿林與台北 × 現況與 10 萬 Starlink 情境。

設備：鹿林為 Rubin 級巡天望遠鏡（口徑 6.4 m 等效、視野 3.5°）；台北為業餘 20 cm 望遠鏡（視野 1°）；皆 30 秒曝光。
天空亮度（遊戲地點設定）：鹿林 21.5、台北 18.5 等／平方角秒，供 _photon.py 判斷光跡是否看得見。
指向：各地天文昏影（太陽 -13°）時正北仰角 45°（north）與方位 250° 仰角 60°（dusk60）的赤經赤緯，整夜固定（追蹤恆星）。
每格另存 night=True 的整夜計數（不判斷可見度），供核對。
用法：python docs/book/sim_chapters/s2_data/fetch_astro_frames.py --server http://127.0.0.1:<埠>
輸出：s2_data/astro_frames.json（含每條光跡的切平面座標）
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_s2 import DUSK, SITES, altaz2radec, groups  # noqa: E402

TEL = {"lulin": {"tel": "Rubin 級巡天望遠鏡", "fov_deg": 3.5, "D_m": 6.4, "mu": 21.5},
       "taipei": {"tel": "業餘 20 cm 望遠鏡", "fov_deg": 1.0, "D_m": 0.2, "mu": 18.5}}
POINT = {"north": (45, 0), "dusk60": (60, 250)}


def post(server, body):
    req = urllib.request.Request(server + "/api/games/astro", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5093")
    a = ap.parse_args()
    out = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "exp_s": 30, "sites": {}}
    for site, (lat, lon, h) in SITES.items():
        t0 = dt.datetime.fromisoformat(DUSK[site].replace("Z", "+00:00"))
        tel = TEL[site]
        S = {**tel, "t0": DUSK[site], "pointings": {}}
        for pk, (alt, az) in POINT.items():
          ra, dec = altaz2radec(alt, az, lat, lon, t0)
          base = {"lat": lat, "lon": lon, "h_km": h, "ra_deg": ra, "dec_deg": dec, "fov_deg": tel["fov_deg"], "exp_s": 30}
          P = S["pointings"][pk] = {"ra_deg": ra, "dec_deg": dec, "night": {}, "frames": {}}
          for kind in ["now", "mega"]:
              P["night"][kind] = post(a.server, {**base, "t": DUSK[site], "groups": groups(kind), "night": True})["night"]
              fr = []
              for k in range(84):
                  tk = (t0 + dt.timedelta(minutes=10 * k)).isoformat().replace("+00:00", "Z")
                  d = post(a.server, {**base, "t": tk, "groups": groups(kind), "night": False})
                  fr.append({"t": tk, "sun_alt": d["sun_alt"], "alt": d["point_alt"], "shadowed": d["shadowed"],
                             "streaks": [{"name": s["name"], "group": s["group"], "mag": s["mag"], "range_km": s["range_km"], "pts": s["pts"]}
                                         for s in d["streaks"]]})
              P["frames"][kind] = fr
              print(site, pk, kind, "done")
        out["sites"][site] = S
    for S in out["sites"].values():          # 不計的曝光（天色太亮或指向太低）不保留光跡，檔案較小
        for P in S["pointings"].values():
            for fr in P["frames"].values():
                for f in fr:
                    if f["sun_alt"] > -12 or f["alt"] < 20:
                        f["streaks"], f["dropped"] = [], True
    p = HERE / "astro_frames.json"
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(p, f"{p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
