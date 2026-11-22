"""延伸篇 S2 影片的背景星：ESA Gaia DR3（gaiadr3.gaia_source）G < 15 等，兩個指向各一錐形區域。

只送出天區座標；以 TAP 同步查詢分小圓查詢後去重（鹿林天區近銀河面，整區一次查詢會逾時）。
資料授權：ESA/Gaia/DPAC，CC BY-SA 3.0 IGO（https://www.cosmos.esa.int/web/gaia-users/license）。
用法：python docs/book/sim_chapters/s2_data/gaia/fetch_gaia.py
輸出：gaia_lulin_G15.csv、gaia_taipei_G15.csv（ra, dec, phot_g_mean_mag）
"""
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
# 指向：各地天文昏影時正北仰角 45° 的赤經赤緯（與 fetch_astro_frames.py 相同）；半徑涵蓋視野對角線
CONES = {"lulin": (334.0353, 68.4686, 2.5), "taipei": (333.4683, 70.03, 0.75)}


SYNC = "https://gea.esac.esa.int/tap-server/tap/sync"


def sync_csv(q):
    body = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
    for attempt in range(4):
        txt = urllib.request.urlopen(urllib.request.Request(SYNC, data=body), timeout=300).read().decode()
        if txt.startswith("source_id"):
            return txt.splitlines()[1:]
        time.sleep(10)
    raise RuntimeError(txt[:300])


def main():
    # 天區較大時同步查詢會逾時、非同步工作會被中止：拆成半徑 0.5° 的小圓（切平面上每 0.65° 一個），以 source_id 去重
    import math
    for site, (ra0, dec0, r) in CONES.items():
        out = HERE / f"gaia_{site}_G15.csv"
        rows, k = {}, int(math.ceil(r / 0.65))
        for iy in range(-k, k + 1):
            for ix in range(-k, k + 1):
                x, y = ix * 0.65, iy * 0.65
                if math.hypot(x, y) > r + 0.5:
                    continue
                dec = dec0 + y
                ra = (ra0 + x / math.cos(math.radians(dec))) % 360
                q = (f"SELECT source_id, ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source "
                     f"WHERE 1=CONTAINS(POINT(ra,dec),CIRCLE({ra:.4f},{dec:.4f},0.5)) AND phot_g_mean_mag<15")
                for line in sync_csv(q):
                    sid, rest = line.split(",", 1)
                    rows[sid] = rest
        out.write_text("ra,dec,phot_g_mean_mag\n" + "\n".join(rows.values()) + "\n", encoding="utf-8")
        print(f"{site}：{len(rows)} 顆（涵蓋半徑 {r}°），{out.name}")


if __name__ == "__main__":
    main()
