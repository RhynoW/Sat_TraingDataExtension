#!/usr/bin/env python3
"""tle_catnr.py — TLE 5 字元編目欄 ⇄ NORAD 整數（Alpha-5 相容）。

背景
----
傳統 TLE 的編目編號欄只有 5 字元，上限 99999。官方 USSF SATCAT 於 2026 年已用盡
5 位數（Saramago 使 SATCAT 進到 100147），Space-Track/CelesTrak 對 100000–339999
採 **Alpha-5** 編碼塞進原 5 字元欄：首字元改用字母代表「萬位＋千位」的前兩碼
（A=10、B=11…H=17，跳過 I；J=18…N=22，跳過 O；P=23…Z=33），後接 4 位數。

  例：100147 → "A0147"（A=10 → 10*10000 + 0147 = 100147）
      148493 → "E8493"
      339999 → "Z9999"（Alpha-5 上限）

因此舊寫法 ``int(line1[2:7])`` 一遇 6 位數即丟 ValueError。本模組提供相容的
``decode_catnr``（解析）與 ``encode_catnr``（輸出），零外部相依。

註：Alpha-5 僅覆蓋到 339999；逾此範圍官方已宣告改走 GP/OMM（不再提供 TLE 格式），
    屬 C 級來源遷移，非本止血模組職責。
"""
from __future__ import annotations

# 0-9 為數字；A 起為 Alpha-5 字母（排除易與 0/1 混淆的 I、O）
_A5 = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_A5_MAX = 339999  # "Z9999"


def decode_catnr(field: str) -> int:
    """TLE 5 字元編目欄 → NORAD 整數。相容傳統 5 位數與 Alpha-5（100000–339999）。

    傳統數字欄（可含前導空白/零）走 ``int``；首字元為字母則以 Alpha-5 解碼。
    非法輸入丟 ``ValueError``（與原 ``int()`` 行為一致，方便呼叫端沿用既有攔截）。
    """
    s = field.strip().upper()
    if not s:
        raise ValueError("empty catalog-number field")
    if s[0].isdigit():
        return int(s)  # 傳統 ≤99999
    tens = _A5.find(s[0])
    if tens < 10 or not s[1:].isdigit():
        raise ValueError(f"invalid Alpha-5 catalog field: {field!r}")
    return tens * 10000 + int(s[1:])


def encode_catnr(num: int) -> str:
    """NORAD 整數 → TLE 5 字元編目欄。<100000 為零填 5 位；否則 Alpha-5。

    逾 Alpha-5 範圍（>339999）丟 ``ValueError``——該區間須改用 GP/OMM，無合法 TLE 表示。
    """
    if num < 0:
        raise ValueError(f"negative catalog number: {num}")
    if num < 100000:
        return f"{num:05d}"
    if num > _A5_MAX:
        raise ValueError(f"catalog number {num} exceeds Alpha-5 range (>{_A5_MAX}); use GP/OMM")
    return _A5[num // 10000] + f"{num % 10000:04d}"


if __name__ == "__main__":
    # 自測：邊界與已知樣本 round-trip
    cases = {
        "25544": 25544, "00005": 5, "99999": 99999,
        "A0000": 100000, "A0147": 100147, "E8493": 148493, "Z9999": 339999,
    }
    ok = True
    for field, num in cases.items():
        d = decode_catnr(field)
        e = encode_catnr(num)
        rt = decode_catnr(e)
        flag = (d == num) and (rt == num)
        ok &= flag
        print(f"  {'[OK]' if flag else '[FAIL]'} {field!r} -> {d} ; encode({num}) -> {e!r}")
    # 例外案例
    for bad in ("", "  ", "I0000", "A00X0"):
        try:
            decode_catnr(bad)
            print(f"  [FAIL] decode_catnr({bad!r}) 應丟 ValueError 卻沒有")
            ok = False
        except ValueError:
            print(f"  [OK] decode_catnr({bad!r}) 正確丟 ValueError")
    try:
        encode_catnr(340000)
        print("  [FAIL] encode_catnr(340000) 應丟 ValueError 卻沒有")
        ok = False
    except ValueError:
        print("  [OK] encode_catnr(340000) 正確丟 ValueError")
    print("=== ALL PASS ===" if ok else "=== HAS FAILURES ===")
