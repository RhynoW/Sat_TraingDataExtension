"""第 2 章 LinkedIn 素材：中英文貼圖（1080×1350，各 5 張）、輪播 PDF，以及單獨第 2 章 PDF。

用法：python docs/book/social/ch02/_build_ch02_social.py [--pdf-only]
來源：docs/book/v1.0_送審版/全書_排版版_v1.3.pdf（單章 PDF 直接取頁，不重新排版；頁界依章首標記判定）；
      照片 data/book/img/nasa/iss064e023038.jpg（NASA ISS064-E-23038，公有領域）。
卡片內容全部取自全書排版版第 2 章正文，不新增事實。
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
PHOTO = ROOT / "data/book/img/nasa/iss064e023038.jpg"
HF = "https://huggingface.co/spaces/RhynoWu/maneuver-detection-i18n"
LINK = {"zh": f"{HF}?mode=book&ch=02", "en": f"{HF}?mode=book&lang=en&ch=02"}

# ---------- 單獨第 2 章 PDF ----------
sys.path.insert(0, str(OUT.parent))
from _book_pages import build_single  # noqa: E402

build_single(2, "第 2 章　看懂衛星軌道：從高度到軌道根數", OUT / "第02章_看懂衛星軌道_從高度到軌道根數_單章.pdf")
if "--pdf-only" in sys.argv:
    raise SystemExit(0)

# ---------- 貼圖 ----------
photo = "data:image/jpeg;base64," + base64.b64encode(PHOTO.read_bytes()).decode()


def qr(url):
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    b = io.BytesIO()
    img.save(b)
    return b.getvalue().decode().split("?>", 1)[-1]


T = {
 "zh": dict(
  font='"Noto Sans TC"', book="從衛星軌道論國家安全", ch="CHAPTER 02", page="第 2 章",
  c1t="看懂衛星軌道：<br>從高度到軌道根數",
  c1q="凌晨三點，一顆 550 公里高的外國衛星，<br>軌道平面 12 小時內向西偏了 2.2 度。<br>該拉警報嗎？",
  credit="照片：NASA ISS064-E-23038，國際太空站 2021-01-14 拍攝台灣西岸夜景",
  c2h="2.2 度，不必燒一滴燃料",
  c2rows=[("地球扁率", "地球赤道略微隆起（J2 攝動），讓傾斜的軌道面像陀螺一樣規律進動"),
          ("每天 4.5°", "以高度 550 公里、傾角 53 度的 Starlink 衛星為例，升交點赤經每天向西漂移約 4.5 度"),
          ("12 小時 2.2°", "直接拿相隔 12 小時的兩筆 TLE 相減，就會看到約 2.2 度的變化")],
  c2f="偵測前先扣除 J2 造成的預期漂移；殘差仍明顯偏離零，才可能是機動、追蹤誤差或其他異常。",
  c3h="TLE：兩行的「證件照」",
  c3rows=[("n → a", "平均運動（每天繞幾圈）以克卜勒第三定律換算半長軸，是主偵測訊號"),
          ("i、e", "傾角與離心率，輔助確認變軌方向與軌道形狀調整"),
          ("Ω", "升交點赤經：扣除 J2 攝動後，檢視殘差"),
          ("B*", "對大氣阻力的敏感度，用來分離自然衰減")],
  c3f="TLE 是 SGP4 平均根數，算出的半長軸只能作前後比對的一致近似量，不是瞬時軌道高度。",
  c4h="差分曲線的四種指紋",
  c4rows=[("平靜期", "差分只在零附近的雜訊帶內抖動"),
          ("自然衰減", "單調、小步、連續下降，通常是稀薄大氣阻力"),
          ("推進機動", "突然跳升或跳降，超出正常雜訊帶，可能是推進器點火"),
          ("資料缺口", "跳動剛好出現在觀測缺口之後，先檢查外推誤差，不能直接當成機動")],
  c4f="TLE 用來找線索，不是驗證真相的標準答案；效能要用精密星曆與點火日誌驗證。",
  c4n="偏離常態不等於已確認的機動；即使確認是機動，也不等於敵意或違規。",
  c5h="線上免費閱讀第 2 章",
  c5s="繁中｜English｜日本語　三語版本",
  c5f="掃描 QR 碼，或點貼文中的連結",
 ),
 "en": dict(
  font='"Inter","Noto Sans TC"', book="National Security from Satellite Orbits", ch="CHAPTER 02", page="Chapter 2",
  c1t="Reading Satellite Orbits:<br>From Altitude to Orbital Elements",
  c1q="3 a.m. A foreign satellite at 550 km<br>has swung its orbital plane 2.2° west in 12 hours.<br>Should anyone sound the alarm?",
  credit="Photo: NASA ISS064-E-23038, Taiwan's west coast at night from the ISS, 2021-01-14",
  c2h="2.2° without a drop of fuel",
  c2rows=[("Earth's bulge", "The slightly bulging equator (J2 perturbation) makes inclined orbital planes precess like a top"),
          ("4.5° a day", "For a Starlink satellite at 550 km and 53° inclination, the ascending node drifts ~4.5° west per day"),
          ("2.2° in 12 h", "Subtract two TLEs 12 hours apart and you see about 2.2° of change")],
  c2f="Remove the expected J2 drift first. Only a residual clearly away from zero may point to a maneuver, tracking error or other anomaly.",
  c3h="A TLE is a two-line ID photo",
  c3rows=[("n → a", "Mean motion (revs per day) converts to semi-major axis via Kepler's third law: the main signal"),
          ("i, e", "Inclination and eccentricity help confirm the direction and shape of an orbit change"),
          ("Ω", "Right ascension of the ascending node: check the residual after removing J2"),
          ("B*", "Sensitivity to atmospheric drag, used to separate natural decay")],
  c3f="TLEs are SGP4 mean elements. The derived semi-major axis is a consistent proxy for comparison, not an instantaneous altitude.",
  c4h="Four fingerprints in the differences",
  c4rows=[("Quiet", "Jitter inside the noise band around zero"),
          ("Natural decay", "Small, steady, monotonic drops, usually from thin-air drag"),
          ("Maneuver", "A sudden jump up or down beyond the noise band, possibly a thruster burn"),
          ("Data gap", "A jump right after a tracking gap: check extrapolation error first")],
  c4f="TLEs find leads, not ground truth. Verify performance against precise ephemerides and burn logs.",
  c4n="Out of the ordinary is not a confirmed maneuver, and a confirmed maneuver is not proof of hostility.",
  c5h="Read Chapter 2 online, free",
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
.en h1{font-size:62px}.en .row span{font-size:30px}.en .row b{flex-basis:220px;font-size:27px}.en h2{font-size:54px}.en .f{font-size:29px}
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
            f = d / f"ch02_{lg}_{i}.png"
            pg.screenshot(path=str(f))
            pngs.append(f)
        car = pymupdf.open()
        for f in pngs:  # LinkedIn「文件」輪播：每張卡一頁
            im = pymupdf.open(f)
            car.insert_pdf(pymupdf.open("pdf", im.convert_to_pdf()))
        car.save(OUT / f"ch02_carousel_{lg}.pdf", garbage=3, deflate=True)
        print(f"{lg}：{len(pngs)} 張貼圖＋輪播 PDF")
    br.close()
