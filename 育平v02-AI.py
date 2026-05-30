"""
Solar risk map generator
========================

這支程式會完成以下工作：
1. 從 NOAA SWPC 下載最新的 Solar Region Summary (SRS) 純文字資料。
2. 解析 SRS 中的活動區資訊，包括有黑子的活動區、僅有 H-alpha plage 的區域、以及即將回歸的活動區。
3. 從中央氣象署（CWA）太陽黑子頁面擷取最新 JPEG 太陽影像網址。
4. 下載該影像並以原始色階呈現，不額外套用 colormap。
5. 根據磁場型態、面積、經度位置與台灣時間，對每個活動區給出簡單風險分數。
6. 繪製左右並排圖：左圖為 CWA Sunspot Image，右圖為 Solar Active Regions Risk Map。
7. 將最終圖檔輸出成 PNG。

注意：
- 本程式使用 requests 並關閉 SSL verify，主要是為了避免某些環境中的憑證驗證問題。
- 風險分數屬於經驗式 heuristic，並非 NOAA 官方 flare probability。
"""

import re
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Tuple, Any
from urllib.parse import urlparse

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.lines import Line2D
import requests
from bs4 import BeautifulSoup
import pytz
import urllib3

# 關閉 requests 在 verify=False 下的 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =============================
# 資料來源設定
# =============================
# NOAA SWPC 的 Solar Region Summary (SRS) 純文字資料
SRS_URL = "https://services.swpc.noaa.gov/text/srs.txt"

# 中央氣象署的太陽黑子觀測頁面
CWA_SUNSPOT_URL = "https://swoo.cwa.gov.tw/V2/page/Observation/Sunspot.html"

# 輸出圖檔位置
OUTPUT_IMAGE = "solar_risk_map_side_by_side_fixed.png"


# =============================
# SRS 下載與解析
# =============================
def fetch_srs_text(url: str = SRS_URL) -> str:
    """
    下載 NOAA SWPC 的 SRS 純文字資料。

    Parameters
    ----------
    url : str
        SRS 資料來源網址。

    Returns
    -------
    str
        SRS 純文字內容。
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=20, verify=False)
    response.raise_for_status()
    return response.text


def parse_lat(lat_str: str) -> int:
    """
    將 SRS Section II 使用的緯度字串轉為整數。

    範例：
    - N15 -> 15
    - S08 -> -8

    Parameters
    ----------
    lat_str : str
        緯度字串，格式應為 [N/S][兩位數]

    Returns
    -------
    int
        北緯為正、南緯為負。
    """
    lat_str = lat_str.strip()
    if len(lat_str) != 3:
        raise ValueError(f"Invalid latitude format: {lat_str}")

    hemisphere = lat_str[0].upper()
    degree = int(lat_str[1:])

    if hemisphere == "N":
        return degree
    if hemisphere == "S":
        return -degree
    raise ValueError(f"Invalid latitude hemisphere: {lat_str}")


def parse_location(location: str) -> Tuple[int, int]:
    """
    將 SRS 中的六碼位置字串轉為緯度與經度。

    SRS 格式例如：
    - N08W22 -> lat=8, lon=22
    - S14E35 -> lat=-14, lon=-35

    在本程式中經度定義為：
    - West 為正值
    - East 為負值

    這與右圖 x 軸標示「East < 0 > West」一致。

    Parameters
    ----------
    location : str
        六碼位置字串。

    Returns
    -------
    tuple[int, int]
        (latitude, longitude)
    """
    location = location.strip()
    if len(location) != 6:
        raise ValueError(f"Invalid location format: {location}")

    lat_str = location[:3]
    lon_str = location[3:]

    lat = int(lat_str[1:]) * (1 if lat_str[0].upper() == "N" else -1)
    lon = int(lon_str[1:]) * (1 if lon_str[0].upper() == "W" else -1)
    return lat, lon


def parse_srs_full(text: str) -> Dict[str, Any]:
    """
    完整解析 SRS 內容。

    解析結果分成三大區塊：
    - Section I: Regions with Sunspots
    - Section IA: H-alpha Plages without Spots
    - Section II: Regions Due to Return

    Returns
    -------
    dict
        包含 meta 與 sections 的巢狀字典。
    """
    lines = text.splitlines()

    meta = {
        "product": None,
        "issued_utc": None,
        "srs_number": None,
        "report_compiled_from": None,
        "section_i_valid_at": None,
        "section_ia_valid_at": None,
        "section_ii_window": None,
    }

    section = None
    passed_header = False

    regions_with_sunspots: List[Dict[str, Any]] = []
    plages_without_spots: List[Dict[str, Any]] = []
    regions_due_to_return: List[Dict[str, Any]] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue

        # 解析檔頭資訊
        if stripped.startswith(":Product:"):
            meta["product"] = stripped.split(":", 2)[-1].strip()
            continue

        if stripped.startswith(":Issued:"):
            meta["issued_utc"] = stripped.split(":", 2)[-1].strip()
            continue

        if stripped.startswith("SRS Number"):
            meta["srs_number"] = stripped
            continue

        if stripped.startswith("Report compiled from data received at SWO on"):
            meta["report_compiled_from"] = stripped.replace(
                "Report compiled from data received at SWO on", ""
            ).strip()
            continue

        # 偵測各 section 起點
        if stripped.startswith("I.  Regions with Sunspots."):
            section = "I"
            passed_header = False
            meta["section_i_valid_at"] = stripped
            continue

        if stripped.startswith("IA. H-alpha Plages without Spots."):
            section = "IA"
            passed_header = False
            meta["section_ia_valid_at"] = stripped
            continue

        if stripped.startswith("II. Regions Due to Return"):
            section = "II"
            passed_header = False
            meta["section_ii_window"] = stripped
            continue

        # -----------------------------
        # Section I: Regions with Sunspots
        # -----------------------------
        if section == "I":
            if stripped.startswith("Nmbr Location"):
                passed_header = True
                continue

            if not passed_header:
                continue

            parts = stripped.split()
            if len(parts) < 8 or not parts[0].isdigit():
                continue

            ar_id = int(parts[0])
            location = parts[1]
            lo = int(parts[2])
            area = int(parts[3])
            zurich = parts[4]
            ll = int(parts[5])
            nn = int(parts[6])
            mag_type = " ".join(parts[7:])

            try:
                lat, lon = parse_location(location)
            except ValueError:
                continue

            regions_with_sunspots.append(
                {
                    "id": ar_id,
                    "location": location,
                    "lat": lat,
                    "lon": lon,
                    "lo": lo,
                    "area": area,
                    "zurich": zurich,
                    "ll": ll,
                    "nn": nn,
                    "mag_type": mag_type,
                }
            )
            continue

        # -----------------------------
        # Section IA: H-alpha Plages without Spots
        # -----------------------------
        if section == "IA":
            if stripped.startswith("Nmbr") and "Location" in stripped and "Lo" in stripped:
                passed_header = True
                continue

            if not passed_header:
                continue

            parts = stripped.split()
            if len(parts) < 3 or not parts[0].isdigit():
                continue

            ar_id = int(parts[0])
            location = parts[1]
            lo = int(parts[2])

            try:
                lat, lon = parse_location(location)
            except ValueError:
                continue

            plages_without_spots.append(
                {
                    "id": ar_id,
                    "location": location,
                    "lat": lat,
                    "lon": lon,
                    "lo": lo,
                }
            )
            continue

        # -----------------------------
        # Section II: Regions Due to Return
        # -----------------------------
        if section == "II":
            if stripped.startswith("Nmbr") and "Lat" in stripped and "Lo" in stripped:
                passed_header = True
                continue

            if not passed_header:
                continue

            parts = stripped.split()
            if len(parts) < 3 or not parts[0].isdigit():
                continue

            ar_id = int(parts[0])
            lat = parse_lat(parts[1])
            lo = int(parts[2])

            regions_due_to_return.append(
                {
                    "id": ar_id,
                    "lat": lat,
                    "lo": lo,
                }
            )
            continue

    return {
        "meta": meta,
        "sections": {
            "regions_with_sunspots": regions_with_sunspots,
            "plages_without_spots": plages_without_spots,
            "regions_due_to_return": regions_due_to_return,
        },
    }


# =============================
# 風險分數 heuristic
# =============================
def score_region(region: Dict[str, Any], tw_hour: int = None) -> int:
    """
    對單一活動區做簡易風險評分。

    評分規則：
    1. 磁場型態
       - 含 delta: +45
       - 含 gamma: +25
       - 含 beta : +10
    2. 面積
       - >= 300: +25
       - >= 150: +15
       - >= 50 : +8
    3. 經度位置（越接近中央子午線越加分）
       - |lon| <= 30: +25
       - |lon| <= 60: +10
    4. 台灣時間夜間觀測時段
       - 19:00~02:59: +20

    最終分數上限為 100。

    Parameters
    ----------
    region : dict
        單一活動區資訊。
    tw_hour : int, optional
        台灣時間小時，若未提供則使用當下 Asia/Taipei 時間。

    Returns
    -------
    int
        0~100 的風險分數。
    """
    if tw_hour is None:
        tw_hour = datetime.now(pytz.timezone("Asia/Taipei")).hour

    mag = region["mag_type"].lower()
    area = region["area"]
    lon = region["lon"]

    score = 0

    if "delta" in mag:
        score += 45
    if "gamma" in mag:
        score += 25
    elif "beta" in mag:
        score += 10

    if area >= 300:
        score += 25
    elif area >= 150:
        score += 15
    elif area >= 50:
        score += 8

    if abs(lon) <= 30:
        score += 25
    elif abs(lon) <= 60:
        score += 10

    if 19 <= tw_hour or tw_hour <= 2:
        score += 20

    return min(score, 100)


# =============================
# CWA 影像網址擷取
# =============================
def absolute_url(base: str, src: str) -> str:
    """
    將相對路徑轉成完整 URL。

    Parameters
    ----------
    base : str
        基準頁面 URL。
    src : str
        可能是絕對或相對路徑的資源位置。

    Returns
    -------
    str
        完整網址。
    """
    if src.startswith("http://") or src.startswith("https://"):
        return src

    if src.startswith("//"):
        return "https:" + src

    if src.startswith("/"):
        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{src}"

    return base.rsplit("/", 1)[0] + "/" + src


def fetch_cwa_sunspot_jpeg_url(page_url: str = CWA_SUNSPOT_URL) -> str:
    """
    從 CWA 太陽黑子頁面中找出最新 JPEG 影像網址。

    搜尋優先順序：
    1. displaybox 區塊內的 img
    2. 全頁 img
    3. HTML/script 文字中的 jpg/jpeg
    4. data-src / data-original / srcset 等 lazy-load 屬性

    Parameters
    ----------
    page_url : str
        CWA 太陽黑子頁面。

    Returns
    -------
    str
        JPEG 圖檔完整網址。
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(page_url, headers=headers, timeout=20, verify=False)
    response.raise_for_status()
    html = response.text

    soup = BeautifulSoup(html, "html.parser")

    # 1) 優先找 displaybox 中的 JPEG
    for box in soup.select("div.displaybox"):
        for img in box.find_all("img"):
            src = img.get("src", "")
            if src.lower().endswith((".jpg", ".jpeg")):
                return absolute_url(page_url, src)

    # 2) 次優先：全頁 img
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.lower().endswith((".jpg", ".jpeg")):
            return absolute_url(page_url, src)

    # 3) fallback：從 HTML / script 文字中抓 jpg/jpeg
    candidates = re.findall(r"""['"]([^'"]+\.(?:jpg|jpeg))['"]""", html, flags=re.IGNORECASE)
    if candidates:
        return absolute_url(page_url, candidates[0])

    # 4) fallback：lazy-load 常見屬性
    for tag in soup.find_all(True):
        for attr in ["data-src", "data-original", "srcset"]:
            value = tag.get(attr)
            if not value:
                continue
            match = re.search(r"([^,\s]+\.(?:jpg|jpeg))", value, flags=re.IGNORECASE)
            if match:
                return absolute_url(page_url, match.group(1))

    raise RuntimeError("找不到 CWA Sunspot 頁面中的 JPEG 影像網址")


def fetch_image_array(img_url: str):
    """
    下載 JPEG 影像並轉為 matplotlib 可用的影像陣列。

    Parameters
    ----------
    img_url : str
        影像網址。

    Returns
    -------
    numpy.ndarray
        影像像素陣列。
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(img_url, headers=headers, timeout=30, verify=False)
    response.raise_for_status()
    return mpimg.imread(BytesIO(response.content), format="jpg")


# =============================
# 繪圖
# =============================
def classify_risk_color(score: int) -> str:
    """
    依風險分數決定點位顏色。

    Parameters
    ----------
    score : int
        活動區分數。

    Returns
    -------
    str
        matplotlib 顏色字串。
    """
    if score >= 70:
        return "red"
    if score >= 40:
        return "orange"
    return "deepskyblue"


def label_offset(lon: int, lat: int) -> Tuple[int, int]:
    """
    根據點位象限給 AR 標籤一個簡單偏移，降低文字重疊機率。

    Parameters
    ----------
    lon : int
        經度。
    lat : int
        緯度。

    Returns
    -------
    tuple[int, int]
        (x_offset, y_offset)
    """
    dx = 3 if lon <= 0 else -18
    dy = 3 if lat <= 0 else -10
    return dx, dy


def plot_solar_risk_map_side_by_side(output_path: str = OUTPUT_IMAGE) -> Dict[str, Any]:
    """
    產生左右並排圖。

    左圖：
    - CWA Sunspot Image
    - 以原始色階顯示，不額外加上 colormap

    右圖：
    - Solar Active Regions Risk Map
    - 顯示中央子午線與 ±30 度可視區參考線
    - 用顏色區分低、中、高風險
    - 標註 AR 編號、磁場型態與分數

    Parameters
    ----------
    output_path : str
        輸出 PNG 檔案路徑。

    Returns
    -------
    dict
        回傳一些執行摘要，方便外部檢查。
    """
    # 下載與解析 SRS
    srs_text = fetch_srs_text()
    parsed = parse_srs_full(srs_text)
    active_regions = parsed["sections"]["regions_with_sunspots"]

    if not active_regions:
        raise RuntimeError("Section I 找不到任何活動區資料")

    # 以台灣時間作為其中一個 heuristic 輸入
    tw_timezone = pytz.timezone("Asia/Taipei")
    tw_now = datetime.now(tw_timezone)
    tw_hour = tw_now.hour

    # 為各活動區計分
    for region in active_regions:
        region["score"] = score_region(region, tw_hour=tw_hour)
        region["color"] = classify_risk_color(region["score"])

    # 下載 CWA 太陽影像
    cwa_jpeg_url = fetch_cwa_sunspot_jpeg_url()
    bg_img = fetch_image_array(cwa_jpeg_url)

    # 建立左右子圖
    fig, (ax_img, ax_map) = plt.subplots(
        1,
        2,
        figsize=(16, 8),
        gridspec_kw={"width_ratios": [1, 1], "wspace": 0.08},
    )

    # -----------------------------
    # 左圖：CWA Sunspot Image
    # -----------------------------
    # 直接使用原始影像陣列，不指定 cmap，因此保留原始色階/色彩。
    ax_img.imshow(bg_img, origin="upper")
    ax_img.set_title("CWA Sunspot Image (Original Scale)", pad=12)
    ax_img.axis("off")

    ax_img.text(
        0.5,
        -0.05,
        "Source: CWA latest sunspot image",
        transform=ax_img.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color="dimgray",
    )

    # -----------------------------
    # 右圖：Solar Risk Map
    # -----------------------------
    ax_map.set_facecolor("black")

    ax_map.axhline(
        0,
        color="white",
        linestyle="--",
        alpha=0.35,
        linewidth=1,
        label="Solar equator",
    )

    ax_map.axvline(
        0,
        color="red",
        linestyle="-",
        alpha=0.7,
        linewidth=1.2,
        label="Central Meridian (CM)",
    )

    ax_map.axvline(
        -30,
        color="orange",
        linestyle="--",
        alpha=0.55,
        linewidth=1,
        label="CM ±30° zone",
    )
    ax_map.axvline(
        30,
        color="orange",
        linestyle="--",
        alpha=0.55,
        linewidth=1,
    )

    # 繪製活動區
    for ar in active_regions:
        ax_map.scatter(
            ar["lon"],
            ar["lat"],
            s=240,
            c=ar["color"],
            edgecolors="black",
            linewidths=1.0,
            zorder=4,
            alpha=0.92,
        )

        dx, dy = label_offset(ar["lon"], ar["lat"])
        ax_map.text(
            ar["lon"] + dx,
            ar["lat"] + dy,
            f"AR{ar['id']}\n{ar['mag_type']}\nS={ar['score']}",
            fontsize=8.3,
            fontweight="bold",
            color="white",
            zorder=5,
            bbox=dict(
                boxstyle="round,pad=0.22",
                fc="black",
                ec="white",
                lw=0.2,
                alpha=0.52,
            ),
        )

    # 自訂風險圖例
    risk_handles = [
        Line2D([0], [0], marker="o", color="none", label="High risk (>=70)",
               markerfacecolor="red", markeredgecolor="black", markersize=10),
        Line2D([0], [0], marker="o", color="none", label="Medium risk (40-69)",
               markerfacecolor="orange", markeredgecolor="black", markersize=10),
        Line2D([0], [0], marker="o", color="none", label="Low risk (<40)",
               markerfacecolor="deepskyblue", markeredgecolor="black", markersize=10),
    ]

    line_handles, line_labels = ax_map.get_legend_handles_labels()
    ax_map.legend(
        handles=line_handles + risk_handles,
        loc="upper right",
        fontsize=8.5,
        framealpha=0.85,
    )

    ax_map.set_xlim(-100, 100)
    ax_map.set_ylim(-100, 100)
    ax_map.set_aspect("equal")
    ax_map.set_xlabel("Longitude (East < 0 > West)")
    ax_map.set_ylabel("Latitude (South < 0 > North)")
    ax_map.set_title("Solar Active Regions Risk Map", pad=12)

    fig.suptitle(
        f"SRS: {parsed['meta']['issued_utc']} | TW: {tw_hour:02d}:00",
        fontsize=14,
        y=0.965,
    )

    # 使用 subplots_adjust 取代 tight_layout，避免版面警告
    fig.subplots_adjust(left=0.04, right=0.98, top=0.90, bottom=0.08, wspace=0.08)

    plt.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    return {
        "issued_utc": parsed["meta"]["issued_utc"],
        "tw_hour": tw_hour,
        "region_count": len(active_regions),
        "cwa_image_url": cwa_jpeg_url,
        "output_path": output_path,
        "regions": active_regions,
    }


# =============================
# 主程式進入點
# =============================
def main() -> None:
    """
    主程式：產生圖檔並列印摘要資訊。
    """
    result = plot_solar_risk_map_side_by_side()

    print("Solar risk map generated successfully.")
    print(f"SRS issued UTC : {result['issued_utc']}")
    print(f"TW hour        : {result['tw_hour']:02d}")
    print(f"Region count   : {result['region_count']}")
    print(f"CWA image URL  : {result['cwa_image_url']}")
    print(f"Output image   : {result['output_path']}")

    print("\nActive Regions:")
    for region in result["regions"]:
        print(
            f"AR{region['id']}: loc={region['location']}, lat={region['lat']}, lon={region['lon']}, "
            f"area={region['area']}, mag={region['mag_type']}, score={region['score']}"
        )


if __name__ == "__main__":
    main()