#!/usr/bin/env python3
"""remote_zip.py — 以 HTTP Range 讀取 Harvard Dataverse 上的大 zip，只抽出需要的成員檔。

STORM-AI 完整資料集 42 GB（private_eval 2021-2024 各 2.7–5.9 GB，絕大部分是 GOES/OMNI2），
我們只需要其中的 sat_density 檔（每檔 ~30 KB）。zipfile 只要能 seek/read 即可讀中央目錄，
故以 Range GET 包成 file-like 物件，下載量從 GB 級降到 MB 級。
"""
from __future__ import annotations

import io
import time
import urllib.request
import zipfile

UA = {"User-Agent": "curl/8.4.0"}
DV = "https://dataverse.harvard.edu/api/access/datafile/{}"


def resolve(fid: int) -> tuple[str, int]:
    """追 303 轉址拿到 S3 presigned URL，並以 Range 0-0 取得總長度。"""
    import requests
    r = requests.get(DV.format(fid), allow_redirects=False, timeout=60, headers=UA)  # 無 UA 會 403
    url = r.headers["Location"]
    r2 = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=60)
    cr = r2.headers.get("Content-Range")  # bytes 0-0/12345
    return url, int(cr.split("/")[1])


class HTTPRangeFile(io.RawIOBase):
    def __init__(self, fid: int, block: int = 1 << 20):
        self.fid = fid
        self.url, self.size = resolve(fid)
        self.pos = 0
        self.block = block
        self.cache: dict[int, bytes] = {}
        self.nbytes = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        if whence == 0:
            self.pos = off
        elif whence == 1:
            self.pos += off
        else:
            self.pos = self.size + off
        return self.pos

    def _get(self, start, end):
        for k in range(5):
            try:
                import requests
                r = requests.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
                if r.status_code != 206:
                    raise IOError(r.status_code)
                b = r.content
                self.nbytes += len(b)
                return b
            except Exception as e:  # presigned URL 4h 過期或暫時錯誤 → 重新解析
                time.sleep(2 * (k + 1))
                try:
                    self.url, _ = resolve(self.fid)
                except Exception:
                    pass
        raise IOError(f"range read failed {start}-{end}")

    def _block(self, i):
        if i not in self.cache:
            if len(self.cache) > 64:
                self.cache.clear()
            s = i * self.block
            self.cache[i] = self._get(s, min(s + self.block, self.size) - 1)
        return self.cache[i]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        out = bytearray()
        while n > 0:
            bi, off = divmod(self.pos, self.block)
            b = self._block(bi)[off:off + n]
            if not b:
                break
            out += b
            self.pos += len(b)
            n -= len(b)
        return bytes(out)

    def readinto(self, buf):
        b = self.read(len(buf))
        buf[:len(b)] = b
        return len(b)


def open_remote_zip(fid: int, block: int = 1 << 18) -> tuple[zipfile.ZipFile, HTTPRangeFile]:
    f = HTTPRangeFile(fid, block=block)
    return zipfile.ZipFile(f), f
