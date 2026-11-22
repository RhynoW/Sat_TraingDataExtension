"""天文夢魘的光子模型（移植自 RUST_SatDashboard/web/ext/games_astro.js 的 render()），供延伸篇 S2 的影片與計數共用。

與遊戲相同的設定：
- 0 等星每秒每平方公尺光子數 ZP = 8e9（V 波段、含效率的概略值）；滿井每 0.5″ 像素 1e5 電子；視寧度 1.5″；影像 720 × 720。
- 天空亮度 mu（等／平方角秒）依地點；昏影時太陽高於 -18° 每度亮 0.4 等。
- 背景雜訊為泊松（高斯近似）；恆星與光跡以高斯 PSF 加入；顯示為滿井截斷後 asinh 拉伸。
與遊戲不同處：
- 背景星改用 Gaia DR3（G < 15，G 當成 V 使用，差約 0–0.5 等）；15 等以下到極限星等，仍以遊戲的星數統計
  N(<m) ≈ 10^(0.36m − 2.9) 顆／平方度隨機補上（示意，上限 4 萬顆）。
- 「看得見的光跡」：光跡在任一像素的貢獻超過 3 倍天空雜訊（遊戲用同一門檻標記被光跡佔去的像素）。
"""
import csv
import math
from pathlib import Path

import numpy as np

ZP, FULL, SEEING, N = 8e9, 1e5, 1.5, 720
HERE = Path(__file__).resolve().parent


class Camera:
    def __init__(self, fov, D, mu_site, exp=30.0):
        self.fov, self.D, self.mu_site, self.exp = fov, D, mu_site, exp
        self.A = math.pi * D * D / 4
        self.pix = fov * 3600 / N
        self.full = FULL * max(1.0, (self.pix / 0.5) ** 2)
        self.sp = max(0.6, SEEING / 2.355 / self.pix)
        rad = math.ceil(3 * self.sp)
        oy, ox = np.mgrid[-rad:rad + 1, -rad:rad + 1]
        self.off = (ox.ravel(), oy.ravel())

    def sky(self, sun_alt):
        mu = self.mu_site - max(0.0, sun_alt + 18) * 0.4
        s = ZP * self.A * 10 ** (-0.4 * mu) * self.pix ** 2 * self.exp
        return mu, s, math.sqrt(s)

    def limit(self, sig):
        return 8 + 2.5 * math.log10(ZP * self.A * 10 ** -3.2 * self.exp / (5 * sig * 2 * math.pi * self.sp ** 2))

    def to_px(self, x, y):
        return N / 2 + np.asarray(x) / self.fov * N, N / 2 - np.asarray(y) / self.fov * N

    def splat(self, img, px, py, flux):
        """在 (px, py) 加入總通量 flux 的高斯 PSF（向量化）。"""
        px, py, flux = np.atleast_1d(px), np.atleast_1d(py), np.atleast_1d(flux)
        x0, y0 = np.rint(px).astype(int), np.rint(py).astype(int)
        X = x0[:, None] + self.off[0][None, :]
        Y = y0[:, None] + self.off[1][None, :]
        w = np.exp(-((X - px[:, None]) ** 2 + (Y - py[:, None]) ** 2) / (2 * self.sp ** 2)) / (2 * math.pi * self.sp ** 2)
        v = flux[:, None] * w
        ok = (X >= 0) & (Y >= 0) & (X < N) & (Y < N)
        np.add.at(img, (Y[ok], X[ok]), v[ok])

    def stars(self, ra0, dec0, gaia_csv, seed, sig_ref, faint_fill=True):
        """恆星層：Gaia（G < 15）＋15 等以下的星數統計示意星。sig_ref 為決定極限星等的天空雜訊（取最暗的天空）。"""
        img = np.zeros((N, N), np.float32)
        r0, d0 = math.radians(ra0), math.radians(dec0)
        p = np.array([math.cos(d0) * math.cos(r0), math.cos(d0) * math.sin(r0), math.sin(d0)])
        e = np.array([-math.sin(r0), math.cos(r0), 0.0])
        n = np.array([-math.sin(d0) * math.cos(r0), -math.sin(d0) * math.sin(r0), math.cos(d0)])
        rows = list(csv.DictReader(open(gaia_csv, encoding="utf-8")))
        ra = np.radians([float(r["ra"]) for r in rows]); de = np.radians([float(r["dec"]) for r in rows])
        mag = np.array([float(r["phot_g_mean_mag"]) for r in rows])
        u = np.stack([np.cos(de) * np.cos(ra), np.cos(de) * np.sin(ra), np.sin(de)], 1)
        c = u @ p
        x = -np.degrees((u @ e) / c); y = np.degrees((u @ n) / c)
        h = self.fov / 2 * 1.05
        k = (c > 0.9) & (np.abs(x) < h) & (np.abs(y) < h)
        px, py = self.to_px(x[k], y[k])
        self.splat(img, px, py, ZP * self.A * 10 ** (-0.4 * mag[k]) * self.exp)
        n_gaia = int(k.sum())
        lim = min(self.limit(sig_ref), 23)
        rng = np.random.default_rng(seed)
        faint, area = 0, self.fov ** 2
        m = 15.25
        while faint_fill and m < lim:
            cnt = round(area * (10 ** (0.36 * (m + 0.25) - 2.9) - 10 ** (0.36 * (m - 0.25) - 2.9)))
            if faint + cnt > 40000:
                break
            mm = m + (rng.random(cnt) - 0.5) * 0.5
            self.splat(img, rng.random(cnt) * N, rng.random(cnt) * N, ZP * self.A * 10 ** (-0.4 * mm) * self.exp)
            faint += cnt
            m += 0.5
        return img, n_gaia, faint, lim

    def trail(self, pts, mag, frac=1.0):
        """單條光跡的影像層（每段通量 = 每秒光子數 × 段時間，沿線每 0.5 px 分攤）。frac < 1 時只畫前段。"""
        img = np.zeros((N, N), np.float32)
        pts = np.asarray(pts, float)
        if len(pts) < 2:
            return img
        nstep = min(2400, max(8, math.ceil(self.exp / 0.25)))
        dts = self.exp / nstep
        rate = ZP * self.A * 10 ** (-0.4 * mag)
        m = max(2, int(len(pts) * frac))
        ax, ay = self.to_px(pts[:m - 1, 0], pts[:m - 1, 1])
        bx, by = self.to_px(pts[1:m, 0], pts[1:m, 1])
        xs, ys, fs = [], [], []
        for a0, a1, b0, b1 in zip(ax, ay, bx, by):
            steps = max(1, math.ceil(math.hypot(b0 - a0, b1 - a1) / 0.5))
            f = (np.arange(steps) + 0.5) / steps
            xs.append(a0 + (b0 - a0) * f); ys.append(a1 + (b1 - a1) * f); fs.append(np.full(steps, rate * dts / steps))
        self.splat(img, np.concatenate(xs), np.concatenate(ys), np.concatenate(fs))
        return img

    def visible(self, trail_img, sig):
        return float(trail_img.max()) > 3 * sig

    def stretch(self, img, sky, sig):
        hi = math.asinh(min(self.full - sky, 3000 * sig) / (3 * sig))
        v = np.minimum(self.full, img)
        z = np.maximum(0, np.arcsinh(np.maximum(0, v - sky - 2 * sig) / (3 * sig)) / hi)
        return np.clip(255 * np.minimum(1, z * 1.4), 0, 255).astype(np.uint8)


def overlay(now_frame, mega_frame):
    """「疊加」情境：現況目錄的全部光跡＋取代情境中假想星座（名稱以「假想」開頭）的光跡。
    伺服器的假想星座會取代目錄中同一星座的真實衛星；疊加時保留真實衛星，只把假想衛星加上去。"""
    if now_frame.get("dropped") or mega_frame.get("dropped"):
        return {**now_frame, "streaks": [], "dropped": True}
    syn = [s for s in mega_frame["streaks"] if s["name"].startswith("假想")]
    return {**now_frame, "streaks": now_frame["streaks"] + syn}
