"""延伸篇 S1 LinkedIn 素材：中文貼圖（1080×1350，5 張）與輪播 PDF。版型沿用 ch01/_build_ch01_social.py。

用法：python docs/book/social/S1/_build_S1_social.py
來源：卡片內容全部取自 docs/book/sim_chapters/S1_碎片連鎖一次解體會引發什麼_初稿.md，不新增事實；
      封面圖 docs/book/sim_chapters/img/op_s1.jpg（本專案模擬畫面）；圖 S1-2 存活曲線 img/s1_cosmos1408_survival.png。
單篇 PDF：docs/book/sim_chapters/pdf/延伸篇S1_碎片連鎖一次解體會引發什麼_單篇.pdf（_build_book.py --with-ext 產生）。
"""
import base64
import sys
from pathlib import Path

import pymupdf
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
IMG = ROOT / "docs/book/sim_chapters/img"


def b64(p, mime):
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


photo = b64(IMG / "op_s1.jpg", "image/jpeg")
surv = b64(IMG / "s1_cosmos1408_survival.png", "image/png")

T = dict(
    book="從衛星軌道論國家安全", ch="延伸篇 S1",
    c1t="碎片連鎖：<br>一次解體會引發什麼",
    c1q="480 公里的大氣，替人類收拾了<br>Cosmos 1408 試射留下的碎片。<br>換一個高度、換一段太陽活動，<br>結果會一樣嗎？",
    credit="碎片連鎖模擬畫面：Cosmos 1408 情境，解體後約 46 天｜本專案 Rust 單機版，2026-11-22",
    c2h="1,805 件碎片的消失紀錄",
    c2rows=[("2021-11-15", "俄羅斯以直升式反衛星飛彈擊毀已失效的 Cosmos 1408"),
            ("第 15 天", "開始有碎片再入"),
            ("第 192 天", "剩下一半"),
            ("1 年", "剩四分之一（25.3%）"),
            ("2026-11-21", "只剩 3 件還在軌道上")],
    c2f="這是碎片連鎖模型唯一有外部觀測可以比對的部分：比的是衰減，不是碰撞率。",
    c2n="資料：CelesTrak SATCAT 國際編號 1982-092 的 1,805 件試射碎片（2026-11-21 下載）",
    c3h="對上了，但要問怎麼對上的",
    c3f="偏差主因是 Δv 分布的長尾。截斷 1σ 後，對數誤差從 0.577 降到 0.179；但這個參數用同一事件校準又評估，0.179 是擬合誤差，不是預測誤差。",
    c3n="藍線：SATCAT 觀測（第 15 天 = 100%）；點：模擬 30 個種子中位數，短線為四分位距",
    c4h="同一次模擬，兩種換算",
    c4a=("0.11", "只計第一代碎片"), c4b=("1.71", "全部期望碰撞 ÷ 倍率"),
    c4f="為了讓連鎖看得見，遊戲把碰撞截面放大 1,000 倍。換算回現實時，線性反推比第一代寫實值高約 15 倍：一張教學圖，就這樣變成嚇人的預報數字。",
    c4n="Envisat 爆成 300 個碎片、碰撞誇張倍率 ×1,000，換算回寫實倍率的 10 年期望碰撞（次）",
    c5h="事後清理有限，<br>太陽活動影響更大",
    c5rows=[("用滿預算", "三張緩解決策卡用滿 3 點，第一代近似風險只降到對照組的 75.8%"),
            ("只移除火箭體", "99.5%，幾乎沒有效果"),
            ("太陽活動", "F10.7 = 70／120／200，第 1 年碎片存活 55.6%／29.2%／7.6%")],
    c5f="教學模型能說明機制與方向，不能取代預報；能對上一條曲線，也不代表對上所有曲線。",
    c5n="決策卡：Envisat、1,000 個碎片、10 年、5 個種子；太陽活動：Cosmos 1408 情境、30 個種子。皆為教學模型示意",
)

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1350px;overflow:hidden;background:#08101C;color:#F5F7FA;font-family:"Noto Sans TC",sans-serif}
.card{position:relative;width:1080px;height:1350px;padding:96px 88px;background:linear-gradient(170deg,#0B1F3A 0%,#08101C 100%)}
.top{display:flex;justify-content:space-between;font:600 24px "IBM Plex Mono","Noto Sans TC",monospace;letter-spacing:.18em;color:#35C6FF}
.foot{position:absolute;left:88px;right:88px;bottom:72px;display:flex;justify-content:space-between;font-size:22px;color:#8A96A6}
h1{font-size:76px;font-weight:900;line-height:1.25;margin-top:40px}
h2{font-size:58px;font-weight:900;line-height:1.3;margin:56px 0 48px}
.bar{width:96px;height:6px;background:#35C6FF;margin-top:40px}
.row{display:flex;gap:36px;padding:28px 0;border-top:1px solid #23344E}
.row b{flex:0 0 250px;font:600 30px "IBM Plex Mono","Noto Sans TC",monospace;color:#FFB020;padding-top:4px}
.row span{font-size:33px;line-height:1.5;color:#E3E9F0}
.f{margin-top:40px;padding:30px 34px;border-left:6px solid #35C6FF;background:#0F2747;font-size:31px;line-height:1.55;font-weight:500}
.note{margin-top:24px;font-size:22px;color:#8A96A6;line-height:1.5}
.photo{position:absolute;inset:0;background:url(%(photo)s) center/cover}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,16,28,.94) 0%%,rgba(8,16,28,.45) 48%%,rgba(8,16,28,.94) 93%%,#08101C 96%%)}
.q{font-size:40px;line-height:1.6;font-weight:500;margin-top:60px}
.credit{position:absolute;left:88px;right:88px;bottom:130px;font-size:20px;color:#C9D3DE}
.fig{background:#fff;border-radius:12px;padding:18px}
.fig img{width:100%%;display:block}
.big{display:flex;gap:40px;margin:10px 0 10px}
.big div{flex:1;padding:36px 32px;border-radius:14px;background:#0F2747}
.big b{display:block;font:700 120px "IBM Plex Mono",monospace;line-height:1.1}
.big span{font-size:30px;color:#C9D3DE}
.x{text-align:center;font:700 44px "Noto Sans TC";color:#FFB020;margin:26px 0 0}
"""


def pages():
    t = T
    top = f'<div class="top"><span>{t["ch"]}</span><span>{{n}} / 5</span></div>'
    foot = f'<div class="foot"><span>{t["book"]}</span><span>©Sat_Dashboard</span></div>'
    rows = lambda rs: "".join(f'<div class="row"><b>{a}</b><span>{b}</span></div>' for a, b in rs)
    return [
        f'<div class="card"><div class="photo"></div><div class="shade"></div><div style="position:relative">{top.format(n=1)}'
        f'<h1>{t["c1t"]}</h1><div class="bar"></div><div class="q">{t["c1q"]}</div></div>'
        f'<div class="credit">{t["credit"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=2)}<h2>{t["c2h"]}</h2>{rows(t["c2rows"])}<div class="f">{t["c2f"]}</div>'
        f'<div class="note">{t["c2n"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=3)}<h2 style="margin-bottom:36px">{t["c3h"]}</h2><div class="fig"><img src="{surv}"></div>'
        f'<div class="note">{t["c3n"]}</div><div class="f">{t["c3f"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=4)}<h2>{t["c4h"]}</h2><div class="big">'
        f'<div><b style="color:#35C6FF">{t["c4a"][0]}</b><span>{t["c4a"][1]}</span></div>'
        f'<div><b style="color:#FF6B4A">{t["c4b"][0]}</b><span>{t["c4b"][1]}</span></div></div>'
        f'<div class="x">相差約 15 倍</div><div class="f">{t["c4f"]}</div><div class="note">{t["c4n"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=5)}<h2>{t["c5h"]}</h2>{rows(t["c5rows"])}<div class="f">{t["c5f"]}</div>'
        f'<div class="note">{t["c5n"]}</div>{foot}</div>',
    ]


HEAD = ('<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?'
        'family=Noto+Sans+TC:wght@400;500;700;900&family=IBM+Plex+Mono:wght@500;600;700&display=swap" rel="stylesheet">'
        '<style>{css}</style></head><body>{body}</body></html>')

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="msedge")
    pg = br.new_page(viewport={"width": 1080, "height": 1350})
    d = OUT / "cards_zh"
    d.mkdir(exist_ok=True)
    css = CSS.replace("%(photo)s", photo).replace("%%", "%")
    pngs = []
    for i, body in enumerate(pages(), 1):
        pg.set_content(HEAD.format(css=css, body=body), wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        f = d / f"S1_zh_{i}.png"
        pg.screenshot(path=str(f))
        pngs.append(f)
    car = pymupdf.open()
    for f in pngs:  # LinkedIn「文件」輪播：每張卡一頁
        car.insert_pdf(pymupdf.open("pdf", pymupdf.open(f).convert_to_pdf()))
    car.save(OUT / "S1_carousel_zh.pdf", garbage=3, deflate=True)
    print(f"{len(pngs)} 張貼圖＋輪播 PDF")
    br.close()
