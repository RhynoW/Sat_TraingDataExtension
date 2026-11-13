"""衛星基本資料：自動查詢 N2YO 與 KeepTrack（2026-10-30）。

‧ N2YO（https://www.n2yo.com/satellite/?s=NORAD）：一般 HTTP 請求（瀏覽器標頭）即可取得，
  解析名稱、國際編目號、發射日期、來源國與發射場（TLE 用本系統資料庫，不取 N2YO 的）。
‧ KeepTrack：網頁（keeptrack.space/satellite/NORAD）在 Cloudflare 機器人驗證之後，requests 回 403、
  一般 headless Selenium 也停在「正在執行安全驗證」頁。不使用任何繞過反機器人機制的手法；
  正式來源為官方 v4 API（https://api.keeptrack.space/v4/sat/NORAD，標頭 X-API-Key），
  需由使用者自行申請免費金鑰並設定環境變數 KEEPTRACK_API_KEY（本程式不保存金鑰）。
  未設定金鑰時依序嘗試：一般 requests 取網頁 →（KEEPTRACK_SELENIUM=1 時）一般 Selenium 取網頁，
  被驗證頁擋下即如實回報「需 API 金鑰」。
‧ 結果快取於 data/cache/sat_info/{NORAD}.json（預設 7 天），避免每次產報表都對外查詢。
‧ 任何失敗只記在 sources[*]["status"]，絕不拋例外——報表產製不能因外部網站而中斷。
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("SAT_INFO_CACHE", "data/cache/sat_info"))
CACHE_TTL_S = float(os.environ.get("SAT_INFO_TTL_S", 7 * 86400))
TIMEOUT_S = 15
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
}
N2YO_URL = "https://www.n2yo.com/satellite/?s={norad}"
KT_PAGE_URL = "https://keeptrack.space/satellite/{norad}"
KT_API_URL = "https://api.keeptrack.space/v4/sat/{norad}"

# KeepTrack v4 /sat/{id} 欄位 → 顯示名稱（只取報表用得到的）
_KT_FIELDS = (("NAME", "名稱"), ("ALT_NAME", "別名"), ("OBJECT_ID", "國際編目號"), ("TYPE", "物件類型"),
              ("STATUS", "狀態"), ("COUNTRY", "國家"), ("OWNER", "營運者"), ("MANUFACTURER", "製造商"),
              ("BUS", "衛星平台"), ("MISSION", "任務"), ("PURPOSE", "用途"), ("CONSTELLATION_NAME", "星系"),
              ("LAUNCH_DATE", "發射日期"), ("LAUNCH_SITE", "發射場"), ("LAUNCH_VEHICLE", "運載火箭"),
              ("LAUNCH_MASS", "發射質量 (kg)"), ("DRY_MASS", "乾質量 (kg)"), ("LIFETIME", "設計壽命"),
              ("RCS", "雷達截面積 RCS (m²)"), ("SHAPE", "外形"), ("SPAN", "展開尺寸 (m)"), ("MOTOR", "推進"))
_CHALLENGE = ("Just a moment", "cf_chl_opt", "正在執行安全驗證", "Enable JavaScript and cookies")


def _text(t: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()


def parse_n2yo(page: str) -> dict:
    """N2YO 衛星頁：「欄名 : 值」的區塊＋TLE <pre>。"""
    out: dict = {}
    flat = _text(page)
    m = re.search(r"Track (.{1,60}?) now!", flat)
    if m:
        out["名稱"] = m.group(1).strip()
    for key, lab in (("NORAD ID", "NORAD"), ("Int'l Code", "國際編目號"), ("Launch date", "發射日期"),
                     ("Source", "來源國"), ("Launch site", "發射場"), ("Decay date", "再入日期"),
                     ("Period", "週期"), ("Perigee", "近地點"), ("Apogee", "遠地點"), ("Inclination", "傾角"),
                     ("RCS", "雷達截面積 RCS")):
        m = re.search(re.escape(key) + r"\s*:\s*(.+?)(?=\s+(?:NORAD ID|Int'l Code|Launch date|Source|Launch site|"
                      r"Decay date|Period|Perigee|Apogee|Inclination|RCS|Semi major|Track |Your |\(adsbygoogle|"
                      r"Two Line|Add |Uplink|NASA's|The ))", flat)
        if m and m.group(1).strip() and len(m.group(1)) <= 120:
            out[lab] = m.group(1).strip()
    return out


def fetch_n2yo(norad: int) -> dict:
    import requests
    url = N2YO_URL.format(norad=norad)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
        if r.status_code != 200:
            return {"status": f"HTTP {r.status_code}", "url": url, "fields": {}}
        f = parse_n2yo(r.text)
        if f.get("NORAD") and f["NORAD"] != str(norad):
            return {"status": f"頁面編號不符（{f['NORAD']}）", "url": url, "fields": {}}
        return {"status": "ok" if f else "解析失敗", "url": url, "fields": f}
    except Exception as e:
        return {"status": f"連線失敗：{type(e).__name__}", "url": url, "fields": {}}


def _kt_from_api(norad: int, key: str) -> dict:
    import requests
    url = KT_API_URL.format(norad=norad)
    r = requests.get(url, headers={**HEADERS, "Accept": "application/json", "X-API-Key": key}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        return {"status": f"API HTTP {r.status_code}", "url": KT_PAGE_URL.format(norad=norad), "fields": {}}
    d = r.json()
    d = d.get("data", d) if isinstance(d, dict) else {}
    f = {lab: str(d[k]).strip() for k, lab in _KT_FIELDS if d.get(k) not in (None, "", [], {})}
    return {"status": "ok（v4 API）", "url": KT_PAGE_URL.format(norad=norad), "fields": f}


def parse_keeptrack_page(text: str) -> dict:
    """KeepTrack 網頁可見文字（若可取得）：抓 Altitude History 摘要句與常見欄位。"""
    out = {}
    m = re.search(r"Apogee\s+([+-]?[\d.]+)\s*km,\s*perigee\s+([+-]?[\d.]+)\s*km\s+across the window", text)
    if m:
        out["高度變化摘要"] = f"遠地點 {m.group(1)} km、近地點 {m.group(2)} km（整個時窗）"
    for key, lab in (("Owner", "營運者"), ("Country", "國家"), ("Type", "物件類型"), ("Launch Vehicle", "運載火箭"),
                     ("Launch Site", "發射場"), ("RCS", "雷達截面積 RCS")):
        m = re.search(rf"\b{key}\s*[:\n]\s*([^\n]+)", text)
        if m:
            out[lab] = m.group(1).strip()
    return out


def _kt_from_page(norad: int) -> dict:
    import requests
    url = KT_PAGE_URL.format(norad=norad)
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
    if r.status_code == 200 and not any(c in r.text for c in _CHALLENGE):
        f = parse_keeptrack_page(_text(r.text))
        return {"status": "ok（網頁）" if f else "網頁無可解析欄位", "url": url, "fields": f}
    status = "網頁受 Cloudflare 驗證保護" if any(c in r.text for c in _CHALLENGE) else f"網頁 HTTP {r.status_code}"
    if os.environ.get("KEEPTRACK_SELENIUM") == "1":
        txt = _selenium_text(url)
        if txt and not any(c in txt for c in _CHALLENGE):
            f = parse_keeptrack_page(txt)
            return {"status": "ok（Selenium）" if f else "Selenium 無可解析欄位", "url": url, "fields": f}
        status += "（Selenium 亦停在驗證頁）"
    return {"status": status + "；請設定 KEEPTRACK_API_KEY 使用官方 v4 API", "url": url, "fields": {}}


def _selenium_text(url: str) -> str | None:
    """一般 headless Chrome 取頁面可見文字（不加任何反偵測設定）。舊版 chromedriver 在 PATH 時
    會與新版 Chrome 不相容，先自 PATH 移除含 chromedriver 的目錄，交由 Selenium Manager 配對。"""
    try:
        from selenium import webdriver
        path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(p for p in path.split(os.pathsep)
                                             if not (Path(p) / "chromedriver.exe").exists()
                                             and not (Path(p) / "chromedriver").exists())
        o = webdriver.ChromeOptions()
        o.add_argument("--headless=new")
        o.add_argument(f"--user-agent={HEADERS['User-Agent']}")
        d = webdriver.Chrome(options=o)
        try:
            d.get(url)
            time.sleep(8)
            return d.find_element("tag name", "body").text
        finally:
            d.quit()
            os.environ["PATH"] = path
    except Exception as e:
        logger.info("Selenium 取頁失敗：%s", e)
        return None


def fetch_keeptrack(norad: int) -> dict:
    key = os.environ.get("KEEPTRACK_API_KEY", "").strip()
    try:
        return _kt_from_api(norad, key) if key else _kt_from_page(norad)
    except Exception as e:
        return {"status": f"連線失敗：{type(e).__name__}", "url": KT_PAGE_URL.format(norad=norad), "fields": {}}


def get_sat_info(norad: int, use_cache: bool = True) -> dict:
    """回傳 {"norad", "fetched_at", "sources": {"N2YO": {...}, "KeepTrack": {...}}}；
    sources[*] = {"status", "url", "fields": {顯示名稱: 值}}。"""
    norad = int(norad)
    cp = CACHE_DIR / f"{norad}.json"
    if use_cache and cp.exists() and time.time() - cp.stat().st_mtime < CACHE_TTL_S:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    out = {"norad": norad, "fetched_at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
           "sources": {"N2YO": fetch_n2yo(norad), "KeepTrack": fetch_keeptrack(norad)}}
    if any(s["fields"] for s in out["sources"].values()):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.info("基本資料快取寫入失敗：%s", e)
    return out


def info_rows(info: dict | None) -> list[list[str]]:
    """合併兩來源成 [欄位, 值, 來源] 列：同一欄位兩邊都有且不同時兩列都留。"""
    if not info:
        return []
    order = ["名稱", "別名", "國際編目號", "物件類型", "狀態", "國家", "來源國", "營運者", "製造商", "衛星平台", "任務",
             "用途", "星系", "發射日期", "發射場", "運載火箭", "發射質量 (kg)", "乾質量 (kg)", "設計壽命", "雷達截面積 RCS",
             "雷達截面積 RCS (m²)", "外形", "展開尺寸 (m)", "推進", "再入日期", "高度變化摘要"]
    rows, seen = [], {}
    for src in ("KeepTrack", "N2YO"):
        for k, v in (info.get("sources", {}).get(src, {}).get("fields") or {}).items():
            if k in ("TLE", "NORAD"):
                continue
            if seen.get(k) == v:
                continue
            seen.setdefault(k, v)
            rows.append([k, v, src])
    rank = {k: i for i, k in enumerate(order)}
    return sorted(rows, key=lambda x: (rank.get(x[0], 99), x[2]))
