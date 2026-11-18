"""第 1 章 LinkedIn 素材：中英文貼圖（1080×1350，各 5 張）、輪播 PDF，以及單獨第 1 章 PDF。

用法：python docs/book/social/ch01/_build_ch01_social.py
來源：docs/book/v1.0_送審版/全書_排版版_v1.2.pdf（單章 PDF 直接取頁，不重新排版）；
      照片 data/book/img/nasa/iss073e0688699.jpg（NASA，公有領域）。
卡片內容全部取自第 1 章修訂版正文，不新增事實。
"""
import base64
import io
import sys
from pathlib import Path

import pymupdf
import qrcode
import qrcode.image.svg
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BOOK_PDF = ROOT / "docs/book/v1.0_送審版/全書_排版版_v1.2.pdf"
PHOTO = ROOT / "data/book/img/nasa/iss073e0688699.jpg"
HF = "https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n"
LINK = {"zh": f"{HF}?mode=book&ch=01", "en": f"{HF}?mode=book&lang=en&ch=01"}

# ---------- 單獨第 1 章 PDF ----------
# 全書頁碼（1 起算）：1 封面、2 扉頁（四個 QR 碼）、3 版權頁、7–17 第 1 章（18 為空白頁）、最後一頁封底
src = pymupdf.open(BOOK_PDF)
assert src.page_count == 250 and not src[17].get_text().strip(), "全書頁數或第 1 章頁界已變，請重新確認"
assert "01" in src[6].get_text() and "02" in src[18].get_text()
pdf = pymupdf.open()
for a, b in [(0, 2), (6, 16), (src.page_count - 1, src.page_count - 1)]:
    pdf.insert_pdf(src, from_page=a, to_page=b)
pdf.set_metadata({"title": "從衛星軌道論國家安全｜第 1 章　太空已成為國家安全疆域（單章試閱）",
                  "author": "Sat_Dashboard", "subject": "太空態勢感知"})
pdf.set_toc([[1, "封面", 1], [1, "扉頁", 2], [1, "版權頁", 3], [1, "第 1 章　太空已成為國家安全疆域", 4], [1, "封底", pdf.page_count]])
ch_pdf = OUT / "第01章_太空已成為國家安全疆域_單章.pdf"
pdf.save(ch_pdf, garbage=3, deflate=True)
print(f"單章 PDF：{ch_pdf.name}，{pdf.page_count} 頁")

# ---------- 貼圖 ----------
photo = "data:image/jpeg;base64," + base64.b64encode(PHOTO.read_bytes()).decode()


def qr(url):
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    b = io.BytesIO()
    img.save(b)
    return b.getvalue().decode().split("?>", 1)[-1]


T = {
 "zh": dict(
  font='"Noto Sans TC"', book="從衛星軌道論國家安全", ch="CHAPTER 01", page="第 1 章",
  c1t="太空已成為<br>國家安全疆域",
  c1q="同一組軌道，兩種說法。<br>危險出現時，誰手上有什麼資料，<br>又能多快讓對方知道？",
  credit="照片：NASA ISS073-E-688699，國際太空站 2025-08-26 拍攝台灣海峽與東海夜景",
  c2h="同一組軌道，兩種說法",
  c2rows=[("2021-07-01", "中國太空站執行「預防碰撞控制」，中方稱 Starlink-1095 逼近"),
          ("2021-10-21", "再一次，這次是 Starlink-2305"),
          ("2021-12", "中國向聯合國秘書長提交照會，指危及航天員生命與健康"),
          ("2022-01", "美國回覆照會：美國太空司令部未評估出顯著碰撞機率")],
  c2f="本章先不問誰對，而是問：資料在誰手上？能透過什麼管道，及時讓另一方知道？",
  c3h="衛星出事，影響落在地面",
  c3rows=[("2022", "Viasat KA-SAT 遭網路攻擊，德國 Enercon 約 5,800 座風機的遠端監控中斷"),
          ("2024", "Finnair 兩班飛往塔爾圖的班機受 GPS 干擾折返，航線暫停一個月"),
          ("2026", "美國 DIA 報告：中國 ISR 衛星超過 510 個系統，2018 年以來增加三倍以上")],
  c3f="前兩起事件中，衛星軌道都沒有改變，受影響的是地面。太空態勢感知不能只看軌道位置。",
  c4h="資訊共享是分層的",
  c4rows=[("公開／非機密", "NOTSO 通知、JCO 商業資料整合、Orbital Watch 第一階段"),
          ("會員制", "Space ISAC：會員回報、網安監測、24/7 營運中心"),
          ("可含機密", "CIC：邀請制，需安全許可，與 CSpOC 協同")],
  c4f="公開 TLE 適合當第一層篩選與早期警示，不能取代精密定軌或機密情資。",
  c4n="表格依 Elara Nova Podcast 第 30 集整理（證據等級 C，本專案未獨立查證）",
  c5h="線上免費閱讀第 1 章",
  c5s="繁中｜English｜日本語　三語版本",
  c5f="掃描 QR 碼，或點貼文中的連結",
 ),
 "en": dict(
  font='"Inter","Noto Sans TC"', book="National Security from Satellite Orbits", ch="CHAPTER 01", page="Chapter 1",
  c1t="Space Has Become a<br>National Security Domain",
  c1q="One set of orbits, two stories.<br>When danger appears, who holds which data,<br>and how fast can they tell the other side?",
  credit="Photo: NASA ISS073-E-688699, Taiwan Strait and East China Sea at night from the ISS, 2025-08-26",
  c2h="One set of orbits, two stories",
  c2rows=[("2021-07-01", "China's space station maneuvers to avoid Starlink-1095, China says"),
          ("2021-10-21", "It happens again, this time with Starlink-2305"),
          ("2021-12", "China tells the UN Secretary-General the astronauts were endangered"),
          ("2022-01", "US reply: US Space Command assessed no significant collision probability")],
  c2f="The chapter asks not who was right, but who held the data, and how it could reach the other side in time.",
  c3h="When satellites fail, the ground feels it",
  c3rows=[("2022", "Cyberattack on Viasat KA-SAT cuts remote monitoring of ~5,800 Enercon wind turbines in Germany"),
          ("2024", "Two Finnair flights to Tartu turn back after GPS interference; route suspended for a month"),
          ("2026", "US DIA report: China fields 510+ ISR satellite systems, more than triple since 2018")],
  c3f="In the first two events, no orbit changed; the damage was on the ground. Space situational awareness cannot stop at orbital positions.",
  c4h="Information sharing comes in layers",
  c4rows=[("Public / unclassified", "NOTSO notices, JCO commercial data fusion, Orbital Watch phase 1"),
          ("Members only", "Space ISAC: member reports, cyber monitoring, 24/7 watch center"),
          ("May be classified", "CIC: invitation only, security clearance, works with CSpOC")],
  c4f="Public TLEs are a first-layer screen and early warning. They do not replace precise orbit determination or classified intelligence.",
  c4n="Table based on Elara Nova Podcast ep. 30 (evidence grade C; not independently verified)",
  c5h="Read Chapter 1 online, free",
  c5s="Traditional Chinese | English | Japanese",
  c5f="Scan the QR code or use the link in the post",
 ),
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1350px;overflow:hidden;background:#08101C;color:#F5F7FA;font-family:%(font)s,sans-serif}
.card{position:relative;width:1080px;height:1350px;padding:96px 88px;background:linear-gradient(170deg,#0B1F3A 0%%,#08101C 100%%)}
.top{display:flex;justify-content:space-between;font:600 24px "IBM Plex Mono",monospace;letter-spacing:.18em;color:#35C6FF}
.foot{position:absolute;left:88px;right:88px;bottom:72px;display:flex;justify-content:space-between;font-size:22px;color:#8A96A6}
h1{font-size:76px;font-weight:900;line-height:1.25;margin-top:40px}
h2{font-size:58px;font-weight:900;line-height:1.3;margin:56px 0 52px}
.bar{width:96px;height:6px;background:#35C6FF;margin-top:40px}
.row{display:flex;gap:36px;padding:30px 0;border-top:1px solid #23344E}
.row b{flex:0 0 250px;font:600 30px "IBM Plex Mono",%(font)s,monospace;color:#FFB020;padding-top:4px}
.row span{font-size:33px;line-height:1.5;color:#E3E9F0}
.f{margin-top:44px;padding:30px 34px;border-left:6px solid #35C6FF;background:#0F2747;font-size:32px;line-height:1.55;font-weight:500}
.note{margin-top:26px;font-size:22px;color:#8A96A6;line-height:1.5}
.photo{position:absolute;inset:0;background:url(%(photo)s) center/cover}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,16,28,.92) 0%%,rgba(8,16,28,.35) 45%%,rgba(8,16,28,.92) 100%%)}
.q{font-size:40px;line-height:1.6;font-weight:500;margin-top:60px;color:#F5F7FA}
.credit{position:absolute;left:88px;right:88px;bottom:130px;font-size:20px;color:#C9D3DE}
.qr{width:420px;height:420px;background:#fff;padding:22px;margin:30px 0 40px;border-radius:12px}
.qr svg{width:100%%;height:100%%}
.en .row span{font-size:30px}.en .row b{flex-basis:220px;font-size:27px}.en h2{font-size:54px}.en .f{font-size:29px}
.url{font:500 24px "IBM Plex Mono",monospace;color:#7FD8FF;word-break:break-all;line-height:1.5}
"""


def pages(lg):
    t = T[lg]
    top = f'<div class="top"><span>{t["ch"]}</span><span>{{n}} / 5</span></div>'
    foot = f'<div class="foot"><span>{t["book"]}</span><span>©Sat_Dashboard</span></div>'
    rows = lambda rs: "".join(f'<div class="row"><b>{a}</b><span>{b}</span></div>' for a, b in rs)
    return [
        f'<div class="card"><div class="photo"></div><div class="shade"></div><div style="position:relative">{top.format(n=1)}'
        f'<h1>{t["c1t"]}</h1><div class="bar"></div><div class="q">{t["c1q"]}</div></div>'
        f'<div class="credit">{t["credit"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=2)}<h2>{t["c2h"]}</h2>{rows(t["c2rows"])}<div class="f">{t["c2f"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=3)}<h2>{t["c3h"]}</h2>{rows(t["c3rows"])}<div class="f">{t["c3f"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=4)}<h2>{t["c4h"]}</h2>{rows(t["c4rows"])}<div class="f">{t["c4f"]}</div>'
        f'<div class="note">{t["c4n"]}</div>{foot}</div>',
        f'<div class="card">{top.format(n=5)}<h2 style="margin-bottom:12px">{t["c5h"]}</h2>'
        f'<div style="font-size:32px;color:#C9D3DE">{t["c5s"]}</div><div class="qr">{qr(LINK[lg])}</div>'
        f'<div class="url">{LINK[lg]}</div><div class="note" style="font-size:26px">{t["c5f"]}</div>{foot}</div>',
    ]


HEAD = ('<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?'
        'family=Noto+Sans+TC:wght@400;500;700;900&family=Inter:wght@400;500;700;900&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">'
        '<style>{css}</style></head><body class="{lg}">{body}</body></html>')

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="msedge")
    pg = br.new_page(viewport={"width": 1080, "height": 1350})
    for lg in ("zh", "en"):
        d = OUT / f"cards_{lg}"
        d.mkdir(exist_ok=True)
        css = CSS % {"font": T[lg]["font"], "photo": photo}
        pngs = []
        for i, body in enumerate(pages(lg), 1):
            pg.set_content(HEAD.format(css=css, body=body, lg=lg), wait_until="networkidle")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(300)
            f = d / f"ch01_{lg}_{i}.png"
            pg.screenshot(path=str(f))
            pngs.append(f)
        car = pymupdf.open()
        for f in pngs:  # LinkedIn「文件」輪播：每張卡一頁
            im = pymupdf.open(f)
            car.insert_pdf(pymupdf.open("pdf", im.convert_to_pdf()))
        car.save(OUT / f"ch01_carousel_{lg}.pdf", garbage=3, deflate=True)
        print(f"{lg}：{len(pngs)} 張貼圖＋輪播 PDF")
    br.close()
