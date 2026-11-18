"""從 TACC 下載福衛七號 leoOrb 每日精密定軌包。

資料服務：https://tacc.cwa.gov.tw/data-service/fs7rt_tdpc/daily_tar/
無需帳號。每日包約 1.4-1.6 MB，實測涵蓋 2019.274 起。

TLS 注意事項
------------
tacc.cwa.gov.tw 的憑證鏈中，TAIWAN-CA 中介憑證缺 Subject Key Identifier。
Python 3.12+ 預設開啟 ssl.VERIFY_X509_STRICT，會直接擋下（實測 SSLError）。

本模組放寬的是 RFC 5280 對憑證擴充欄位的**格式嚴格性檢查**，
憑證鏈仍對 certifi 的 CA 信任庫做完整驗證、主機名仍比對。
這**不是** verify=False。
"""

from __future__ import annotations

import logging
import re
import ssl
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional

import certifi
import requests

log = logging.getLogger(__name__)

BASE_URL = "https://tacc.cwa.gov.tw/data-service/fs7rt_tdpc/daily_tar"

#: 預設快取目錄。沿用 repo 的 data/ 慣例（該目錄下各子目錄逐一 gitignore）。
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "formosat7_leoorb"

#: 實測資料起始日（2019-10-01）。更早的日期不必送出請求。
EARLIEST_DAY_TAG = "2019.274"

_DAY_TAG_RE = re.compile(r"^(\d{4})\.(\d{3})$")


class RelaxedStrictAdapter(requests.adapters.HTTPAdapter):
    """憑證鏈仍對 CA 信任庫完整驗證、主機名仍比對；
    僅放寬 RFC 5280 對憑證擴充欄位的嚴格一致性檢查。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_session() -> requests.Session:
    """建立可連上 TACC 的 requests session。"""
    s = requests.Session()
    s.mount("https://", RelaxedStrictAdapter())
    return s


# ── 日期標籤 ──────────────────────────────────────────────────────────────

def day_tag(d: date | datetime | str) -> str:
    """date -> 'YYYY.DDD'（年 + 年積日）。字串則原樣驗證後回傳。"""
    if isinstance(d, str):
        if not _DAY_TAG_RE.match(d):
            raise ValueError("日期標籤格式應為 'YYYY.DDD'，收到 %r" % (d,))
        return d
    if isinstance(d, datetime):
        d = d.date()
    return "%04d.%03d" % (d.year, d.timetuple().tm_yday)


def parse_day_tag(tag: str) -> date:
    """'YYYY.DDD' -> date。"""
    m = _DAY_TAG_RE.match(tag)
    if not m:
        raise ValueError("日期標籤格式應為 'YYYY.DDD'，收到 %r" % (tag,))
    year, doy = int(m.group(1)), int(m.group(2))
    return date(year, 1, 1) + timedelta(days=doy - 1)


def day_tags_between(start: date | str, end: date | str) -> Iterator[str]:
    """產生 [start, end] 閉區間的每日標籤。"""
    d0 = parse_day_tag(start) if isinstance(start, str) else start
    d1 = parse_day_tag(end) if isinstance(end, str) else end
    if d1 < d0:
        raise ValueError("end 早於 start：%s < %s" % (d1, d0))
    d = d0
    while d <= d1:
        yield day_tag(d)
        d += timedelta(days=1)


# ── 下載 ──────────────────────────────────────────────────────────────────

def day_url(tag: str) -> str:
    tag = day_tag(tag)
    return "%s/%s/leoOrb_%s.tar.gz" % (BASE_URL, tag, tag)


def list_available_days(session: Optional[requests.Session] = None,
                        timeout: float = 60.0) -> list[str]:
    """列出伺服器目錄上所有可用的 'YYYY.DDD'（已排序去重）。"""
    s = session or make_session()
    r = s.get(BASE_URL + "/", timeout=timeout)
    r.raise_for_status()
    return sorted(set(_DAY_TAG_RE.match(t).group(0)
                      for t in re.findall(r"\d{4}\.\d{3}", r.text)
                      if _DAY_TAG_RE.match(t)))


def download_day(day: date | str,
                 dest_dir: Optional[Path] = None,
                 session: Optional[requests.Session] = None,
                 force: bool = False,
                 timeout: float = 120.0) -> Path:
    """下載單日包，回傳本地路徑。已存在且非 force 時直接回傳（不重下）。"""
    tag = day_tag(day)
    dest_dir = Path(dest_dir) if dest_dir else DEFAULT_CACHE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / ("leoOrb_%s.tar.gz" % tag)

    if out.exists() and out.stat().st_size > 0 and not force:
        log.debug("快取命中 %s", out.name)
        return out

    s = session or make_session()
    url = day_url(tag)
    log.info("下載 %s", url)
    r = s.get(url, timeout=timeout)
    r.raise_for_status()

    # 先寫暫存再改名，避免中斷留下半截檔被當成快取
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(out)
    log.info("  -> %s (%.1f MB)", out.name, len(r.content) / 1e6)
    return out


def download_range(start: date | str,
                   end: date | str,
                   dest_dir: Optional[Path] = None,
                   session: Optional[requests.Session] = None,
                   force: bool = False,
                   skip_missing: bool = True) -> list[Path]:
    """下載日期區間。skip_missing=True 時，缺日僅記錄警告不中斷。"""
    s = session or make_session()
    paths: list[Path] = []
    for tag in day_tags_between(start, end):
        try:
            paths.append(download_day(tag, dest_dir=dest_dir, session=s, force=force))
        except requests.HTTPError as e:
            if skip_missing:
                log.warning("略過 %s：%s", tag, e)
                continue
            raise
    return paths
