"""福衛七號 leoOrb 的 SP3 代號 / 檔名序號 / NORAD 對照。

驗證方式（來源文件第二節）：拿每個 SP3 代號分別與六顆候選星的 TLE 傳播結果
比對位置差。結果毫無歧義 —— 正確配對約 0.5 km，錯誤配對 7,000-13,000 km。

檔名格式：leoOrb_{YYYY}.{DDD}.{sss}.{aa}_{nnnn}.{nnnn}_sp3
          其中 sss = 衛星序號（001-006）、aa = 弧段序號。
"""

from typing import Dict, Optional

# SP3 代號 -> NORAD
SP3_TO_NORAD: Dict[str, int] = {
    "L76": 44349,   # FORMOSAT7-1
    "L77": 44351,   # FORMOSAT7-2
    "L78": 44343,   # FORMOSAT7-3
    "L79": 44350,   # FORMOSAT7-4
    "L80": 44358,   # FORMOSAT7-5
    "L81": 44353,   # FORMOSAT7-6
}

# 檔名衛星序號 -> SP3 代號
ARC_INDEX_TO_SP3: Dict[str, str] = {
    "001": "L76",
    "002": "L77",
    "003": "L78",
    "004": "L79",
    "005": "L80",
    "006": "L81",
}

SP3_TO_NAME: Dict[str, str] = {
    "L76": "FORMOSAT7-1",
    "L77": "FORMOSAT7-2",
    "L78": "FORMOSAT7-3",
    "L79": "FORMOSAT7-4",
    "L80": "FORMOSAT7-5",
    "L81": "FORMOSAT7-6",
}

NORAD_TO_SP3: Dict[int, str] = {v: k for k, v in SP3_TO_NORAD.items()}

#: 未經位置比對驗證的代號。目前為空 —— 六個對照都已用實資料驗證：
#: L76/77/79/80/81 由來源文件於 2026.223-229 驗證；
#: L78 由本專案於 2024.121-125 驗證（該期間 L78 有資料，2026 年取樣期則無）。
#: 六者皆為正確配對約 0.5 km、錯誤配對 6,550-13,232 km，毫無歧義。
UNCONFIRMED_SP3 = frozenset()

#: 來源文件取樣期（2026.223-2026.229）實際觀測到的代號 —— **不含 L78**。
#: 不可假設六顆星每天都有 leoOrb；可用性隨日期變動（2024.121-140 六顆齊全）。
OBSERVED_SP3_2026 = ("L76", "L77", "L79", "L80", "L81")
OBSERVED_SP3 = OBSERVED_SP3_2026   # 相容別名


def norad_for_sp3(sp3_id: str) -> Optional[int]:
    """SP3 代號 -> NORAD，未知時回傳 None。"""
    return SP3_TO_NORAD.get(sp3_id.strip().upper())


def sp3_for_arc_index(index: str) -> Optional[str]:
    """檔名裡的衛星序號（'001'-'006'）-> SP3 代號。"""
    return ARC_INDEX_TO_SP3.get(str(index).strip())


def is_verified(sp3_id: str) -> bool:
    """該 SP3 代號的 NORAD 對照是否經過位置比對驗證。"""
    sid = sp3_id.strip().upper()
    return sid in SP3_TO_NORAD and sid not in UNCONFIRMED_SP3
