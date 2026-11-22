"""延伸篇 S1–S3 的模擬畫面截圖（Rust 單機版 /games）。

用法：python docs/book/sim_chapters/_screens.py --server http://127.0.0.1:<埠>
需要 Playwright 與 Microsoft Edge。畫面依截圖當下的目錄與時間而定，重跑不會逐像素相同。
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
IMG = Path(__file__).resolve().parent / "img"


def shot(page, name, el=None):
    p = IMG / name
    (page.locator(el) if el else page).screenshot(path=str(p))
    print(name)


def tab(page, key):
    page.click(f'button[data-tab="{key}"]')
    page.wait_for_timeout(1500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5093")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True,
                                args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = br.new_page(viewport={"width": 1600, "height": 960}, device_scale_factor=1.5)
        page.goto(a.server + "/games", wait_until="networkidle")
        page.wait_for_timeout(4000)

        if a.only in ("", "s1"):
            # S1：碎片連鎖，Cosmos 1408 情境（碰撞模型、寫實 ×1、5 年）
            tab(page, "debris")
            page.select_option("#d-tpl", "c1408")
            page.wait_for_timeout(500)
            page.click("#d-run")
            page.wait_for_function("document.querySelector('#d-res') && document.querySelector('#d-res').innerText.includes('第一代')", timeout=180000)
            page.get_by_text("看前 90 天").click()   # 碎片散成殼層，全球視角
            page.wait_for_timeout(15000)
            shot(page, "ss_s1_debris.png")

        if a.only in ("", "s2"):
            # S2：星座壅擠，10 萬 Starlink 情境
            tab(page, "crowd")
            page.wait_for_timeout(6000)       # 目錄 TLE 與殼層載入
            page.click('button[data-preset="mega"]')
            page.click("#cr-run")
            page.wait_for_function("document.querySelector('#cr-res').innerText.includes('倍數')", timeout=300000)
            page.wait_for_timeout(5000)
            shot(page, "ss_s2_crowd.png")
            # 天文夢魘：鹿林、Rubin 級、正北仰角 45°、今晚天文昏影，現況 vs 10 萬 Starlink
            tab(page, "astro")
            page.select_option("#s-site", index=0)
            page.select_option("#s-target", "altaz")
            page.fill("#s-az", "0"); page.fill("#s-alt", "45")
            page.click("#s-dusk")
            page.wait_for_timeout(1000)
            page.click("#s-cmp-run")
            page.wait_for_function("!document.querySelector('#s-cmp').hidden && document.querySelector('#s-cmp-res').innerText.length > 0", timeout=180000)
            page.wait_for_timeout(2000)
            shot(page, "ss_s2_astro_compare.png", "#s-cmp-box")

        if a.only in ("", "s3"):
            # S3：太空兵棋，想定 C，藍方 AI 監視＋規避、紅方 AI 升級；雙方 AI，伺服器直接跑完 8 回合
            tab(page, "war")
            page.select_option("#w-scen", "c")
            page.select_option("#w-ai-blue", "evade")
            page.select_option("#w-ai-red", "escalate")
            page.click("#w-new")
            page.wait_for_timeout(6000)
            shot(page, "ss_s3_war.png")
        br.close()


if __name__ == "__main__":
    main()
