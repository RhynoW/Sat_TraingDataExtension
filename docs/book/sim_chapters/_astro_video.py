"""延伸篇 S2：天文夢魘整夜錄影（鹿林、台北 × 現況、現況＋假想星座疊加），每 10 分鐘一次 30 秒曝光。
只放兩地都能觀測的曝光：太陽仰角 ≤ -12° 且天區仰角 ≥ 20°（天區隨恆星西沉，約 6 小時後低於 20°），不能觀測的時段不模擬。

資料：s2_data/v2/astro_base.json（fetch_astro_v2.py，快照 S2-20261123）；背景星：s2_data/gaia/（Gaia DR3，G < 15；不補統計示意星）。
影像：_photon.py（移植自遊戲 games_astro.js）合成：天空背景依地點與昏影亮度、光子雜訊、Gaia 恆星與示意暗星、
光跡依星等換算光子數；每次曝光內光跡依取樣順序逐步畫出。只畫被太陽照到、且超過 3 倍天空雜訊的光跡；顯示拉伸比遊戲緩（避免暗星填滿畫面）。
設備：鹿林巡天望遠鏡等效教學設定（口徑 6.4 m 等效、視野 3.5°）；台北業餘 20 cm（視野 1°）。指向：天文昏影時正北仰角 45° 的天區（追蹤恆星）。
用法：python docs/book/sim_chapters/_astro_video.py   輸出：docs/book/sim_chapters/video/s2_astro_night.mp4
"""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _photon import Camera, N, overlay  # noqa: E402

_V2 = json.loads((HERE / "s2_data/v2/astro_base.json").read_text(encoding="utf-8"))
PK = "north"
DATA = {"exp_s": 30, "sites": {}}          # 轉成原 astro_frames.json 的結構
for _site in ("lulin", "taipei"):
    _P = _V2["sets"][f"{_site}/{PK}"]
    DATA["sites"][_site] = {"fov_deg": _P["fov_deg"], "D_m": _P["D_m"], "mu": _P["mu"], "t0": _P["t0"],
                            "pointings": {PK: {"ra_deg": _P["ra_deg"], "dec_deg": _P["dec_deg"], "frames": dict(_P["frames"])}}}
for _S in DATA["sites"].values():          # 疊加情境：現況目錄＋假想 10 萬 Starlink、2 萬 Kuiper、1 萬千帆
    _F = _S["pointings"][PK]["frames"]
    _F["add"] = [overlay(a, b) for a, b in zip(_F["now"], _F["mega"])]
OUT = HERE / "video"
FR = OUT / "_frames"
FFMPEG = shutil.which("ffmpeg") or r"C:\Users\USER\AppData\Local\Programs\ffmpeg-arm64\bin\ffmpeg.exe"

W, H, P = 1920, 1080, 430
GROW, HOLD, FPS = 6, 3, 15
FONT = "C:/Windows/Fonts/msjh.ttc"
f_big, f_mid, f_sm, f_xs = (ImageFont.truetype(FONT, s) for s in (34, 22, 17, 14))
BG, INK, INK2, LINE = (11, 16, 26), (236, 240, 245), (150, 160, 175), (55, 63, 78)
BLUE, ORANGE = (58, 135, 229), (235, 104, 52)
SITE_NAME = {"lulin": "鹿林天文台（巡天望遠鏡等效，視野 3.5°）", "taipei": "台北（業餘 20 cm，視野 1°）"}
KIND_NAME = {"now": "現況目錄", "add": "現況＋13 萬顆假想衛星"}
GROUP_NAME = {0: "", 1: "Starlink", 2: "Kuiper", 3: "千帆", 4: "國網"}
LAYOUT = {("lulin", "now"): (40, 105), ("lulin", "add"): (40 + P + 40, 105),
          ("taipei", "now"): (40, 105 + P + 75), ("taipei", "add"): (40 + P + 40, 105 + P + 75)}

CAM, STAR, NOISE, META = {}, {}, {}, {}
for site, S in DATA["sites"].items():
    cam = CAM[site] = Camera(S["fov_deg"], S["D_m"], S["mu"], DATA["exp_s"])
    Pt = S["pointings"][PK]
    _, _, sig_dark = cam.sky(-30)
    STAR[site], ng, nf, lim = cam.stars(Pt["ra_deg"], Pt["dec_deg"], HERE / f"s2_data/gaia/gaia_{site}_G15.csv", 7, sig_dark, faint_fill=False)
    NOISE[site] = np.random.default_rng(11).standard_normal((N, N)).astype(np.float32)
    META[site] = (ng, nf, lim)
    print(site, f"Gaia {ng} 顆、示意暗星 {nf} 顆、極限約 {lim:.1f} 等")


def in_fov(s, half):
    return any(abs(x) <= half and abs(y) <= half for x, y in s["pts"])


TRAILS, CNT = {}, {}      # (site, kind, k) → 看得見的光跡
for site, S in DATA["sites"].items():
    cam, half = CAM[site], S["fov_deg"] / 2
    for kind in ("now", "add"):
        c = []
        for k, f in enumerate(S["pointings"][PK]["frames"][kind]):
            if f.get("dropped"):
                c.append(None); continue
            _, _, sig = cam.sky(f["sun_alt"])
            lst = [s for s in f["streaks"] if in_fov(s, half) and cam.visible(cam.trail(s["pts"], s["mag"]), sig)]
            TRAILS[(site, kind, k)] = lst
            c.append(len(lst))
        CNT[(site, kind)] = c
KS = [k for k in range(84) if all(CNT[key][k] is not None for key in CNT)]   # 兩地都能觀測的曝光
NK = len(KS)


def panel(img, d, site, kind, k, frac):
    ox, oy = LAYOUT[(site, kind)]
    S = DATA["sites"][site]
    f = S["pointings"][PK]["frames"][kind][k]
    cam, half = CAM[site], S["fov_deg"] / 2
    mu, sky, sig = cam.sky(f["sun_alt"])
    d.text((ox, oy - 30), f"{SITE_NAME[site]}｜{KIND_NAME[kind]}", font=f_sm, fill=INK)
    lst = TRAILS.get((site, kind, k), [])
    if f.get("dropped"):
        pim = Image.new("RGB", (P, P), (60, 66, 76))
    else:
        raw = sky + sig * NOISE[site] + STAR[site]
        for s in lst:
            raw = raw + cam.trail(s["pts"], s["mag"], frac)
        b = raw.reshape(N // 2, 2, N // 2, 2).mean(axis=(1, 3))      # 2×2 合併：雜訊降為一半，減少單像素閃爍
        # 顯示拉伸：比遊戲緩（參考值 40σ），避免近銀河面的大量暗星把畫面填滿；光跡與亮星仍清楚
        s2 = sig / 2
        v = np.minimum(cam.full, b) - sky - 2 * s2
        z = 255 * np.clip(np.arcsinh(np.maximum(0, v) / (40 * s2)) / np.arcsinh(min(cam.full - sky, 3e5 * s2) / (40 * s2)) * 1.6, 0, 1)
        ped = float(np.clip((22.0 - mu) * 13, 0, 110))               # 天空背景亮度示意（台北光害、昏影變亮）
        z = ped + z * (255 - ped) / 255
        pim = Image.fromarray(z.astype(np.uint8)).resize((P, P), Image.BICUBIC).convert("RGB")
    pd = ImageDraw.Draw(pim)
    if frac >= 1:
        used = []
        for s in lst:
            pts = [(x, y) for x, y in s["pts"] if abs(x) <= half and abs(y) <= half]
            x, y = pts[len(pts) // 2]
            px, py = cam.to_px(x, y)
            lx = min(max(float(px) * P / N + 6, 4), P - 170); ly = min(max(float(py) * P / N + 4, 26), P - 44)
            while any(abs(ly - u) < 18 and abs(lx - v) < 170 for v, u in used):
                ly += 18
            used.append((lx, ly))
            nm = (("假想 " + GROUP_NAME[s["group"]]) if s["name"].startswith("假想") else s["name"])[:20]
            txt = f"{s['mag']:.1f} 等 {nm}"
            tw = pd.textlength(txt, font=f_xs)
            pd.rectangle([lx - 3, ly - 1, lx + tw + 3, ly + 17], fill=(0, 0, 0))
            pd.text((lx, ly), txt, font=f_xs, fill=(250, 200, 120) if s["group"] else (150, 190, 250))
    local = dt.datetime.fromisoformat(f["t"].replace("Z", "+00:00")) + dt.timedelta(hours=8)
    pd.rectangle([0, 0, P, 24], fill=(0, 0, 0))
    pd.text((6, 4), f"{local:%H:%M}　太陽 {f['sun_alt']:.0f}°　天空 {mu:.1f} 等/平方角秒", font=f_xs, fill=INK2)
    bar = P / S["fov_deg"] * (1.0 if S["fov_deg"] > 2 else 0.25)
    pd.line([P - 20 - bar, P - 12, P - 20, P - 12], fill=(230, 230, 230), width=2)
    pd.text((P - 20 - bar, P - 32), "1°" if S["fov_deg"] > 2 else "15′", font=f_xs, fill=(230, 230, 230))
    img.paste(pim, (ox, oy))
    d.rectangle([ox, oy, ox + P, oy + P], outline=LINE)
    if f.get("dropped"):
        d.text((ox + 4, oy + P + 6), "不計：太陽仰角 > -12°" if f["sun_alt"] > -12 else "不計：指向仰角 < 20°", font=f_sm, fill=INK2)
    else:
        d.text((ox + 4, oy + P + 6), f"看得見的光跡 {len(lst)} 條", font=f_sm, fill=ORANGE if kind == "add" else BLUE)


def chart(d, k):
    x0, y0, w, h = 1050, 560, 830, 420
    d.text((x0, y0 - 40), "每次 30 秒曝光看得見的光跡條數", font=f_mid, fill=INK)
    mx = max(max((v for v in c if v is not None), default=1) for c in CNT.values())
    hh = (h - 40) / 2
    for r, (site, nm) in enumerate([("lulin", "鹿林"), ("taipei", "台北")]):
        top = y0 + r * (hh + 40)
        d.text((x0, top), nm, font=f_sm, fill=INK2)
        base = top + hh
        d.line([x0 + 50, base, x0 + w, base], fill=LINE)
        bw = (w - 60) / NK
        for i, kk in enumerate(KS):
            if kk > k:
                break
            for j, (kind, col) in enumerate([("now", BLUE), ("add", ORANGE)]):
                v = CNT[(site, kind)][kk]
                if v:
                    bx = x0 + 52 + i * bw + j * bw / 2
                    d.rectangle([bx, base - v / mx * (hh - 24), bx + bw / 2 - 1, base], fill=col)
        t0 = dt.datetime.fromisoformat(DATA["sites"][site]["t0"].replace("Z", "+00:00"))
        for i in range(0, NK + 1, 6):
            d.text((x0 + 52 + i * bw - 16, base + 4), f"{t0 + dt.timedelta(minutes=10 * (KS[0] + i), hours=8):%H:%M}", font=f_xs, fill=INK2)
        tot = [sum(CNT[(site, kd)][kk] for kk in KS if kk <= k) for kd in ("now", "add")]
        d.text((x0 + w - 330, top), f"累計　現況 {tot[0]}　現況＋假想 {tot[1]}", font=f_xs, fill=INK)
    d.rectangle([x0 + 50, y0 + h + 30, x0 + 64, y0 + h + 44], fill=BLUE); d.text((x0 + 70, y0 + h + 26), "現況目錄", font=f_xs, fill=INK2)
    d.rectangle([x0 + 170, y0 + h + 30, x0 + 184, y0 + h + 44], fill=ORANGE)
    d.text((x0 + 190, y0 + h + 26), "現況＋假想 10 萬 Starlink、2 萬 Kuiper、1 萬千帆", font=f_xs, fill=INK2)


def frame(k, frac):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 24), "天文夢魘：一整夜，望遠鏡每 10 分鐘拍一張 30 秒曝光", font=f_big, fill=INK)
    info = ["鹿林：巡天望遠鏡等效設定、視野 3.5°；台北：業餘 20 cm、視野 1°",
            "天空亮度：鹿林 21.5、台北 18.5 等／平方角秒；昏影時隨太陽變亮",
            f"指向：天文昏影時正北仰角 45° 的天區（追蹤恆星）；共 {NK} 次曝光",
            "只畫被太陽照到、且超過 3 倍天空雜訊的光跡（遊戲的光子模型）",
            "背景星：只畫 Gaia DR3 真實恆星（G<15）；灰底亮度示意天空背景",
            "情境為「疊加」：現況目錄全部保留，再加上 13 萬顆假想衛星",
            "只放能觀測的時段：天區約 6 小時後低於仰角 20°，之後不模擬",
            "教學模型示意｜2026-11-22 晚，快照 S2-20261123｜Gaia 資料：ESA/Gaia/DPAC"]
    for i, s in enumerate(info):
        d.text((1050, 92 + i * 27), s, font=f_sm if i < 7 else f_xs, fill=INK2 if i < 7 else (120, 130, 145))
    t = dt.datetime.fromisoformat(DATA["sites"]["lulin"]["pointings"][PK]["frames"]["now"][k]["t"].replace("Z", "+00:00")) + dt.timedelta(hours=8)
    d.text((1050, 370), f"第 {KS.index(k) + 1:02d} / {NK} 次曝光　鹿林 {t:%m-%d %H:%M}（台北早 4 分鐘）", font=f_mid, fill=INK)
    d.line([1050, 420, 1880, 420], fill=LINE)
    for site in ("lulin", "taipei"):
        for kind in ("now", "add"):
            panel(img, d, site, kind, k, frac)
    chart(d, k)
    return img


def main():
    if FR.exists():
        shutil.rmtree(FR)
    FR.mkdir(parents=True)
    i = 0
    for k in KS:
        for g in range(GROW + HOLD):
            frame(k, min(1.0, (g + 1) / GROW)).save(FR / f"{i:05d}.png"); i += 1
    for _ in range(FPS * 3):
        frame(KS[-1], 1.0).save(FR / f"{i:05d}.png"); i += 1
    frame(3, 1.0).save(OUT / "s2_astro_night_sample.png")
    mp4 = OUT / "s2_astro_night.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FR / "%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(FR)
    print(mp4, f"{i} 格、{i / FPS:.0f} 秒、{mp4.stat().st_size / 1e6:.1f} MB")
    for key, c in CNT.items():
        print(key, "曝光", NK, "看得見總條數", sum(c[k] for k in KS))


if __name__ == "__main__":
    main()
