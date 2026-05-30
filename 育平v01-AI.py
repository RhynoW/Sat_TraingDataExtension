import requests
import matplotlib.pyplot as plt
from datetime import datetime
import pytz


SRS_URL = "https://services.swpc.noaa.gov/text/srs.txt"


def fetch_srs_text(url=SRS_URL):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.text


def parse_lat(lat_str):
    """
    解析 Section II 的緯度欄位，例如:
    N17, S18
    """
    lat_str = lat_str.strip()
    if len(lat_str) != 3:
        raise ValueError(f"Invalid latitude format: {lat_str}")

    hemi = lat_str[0].upper()
    deg = int(lat_str[1:])

    if hemi == "N":
        return deg
    elif hemi == "S":
        return -deg
    else:
        raise ValueError(f"Invalid latitude hemisphere: {lat_str}")


def parse_location(location):
    """
    解析 Section I / IA 的位置欄位，例如:
    N17W62, S16E38
    緯度: 北正南負
    經度: 西正東負
    """
    location = location.strip()
    if len(location) != 6:
        raise ValueError(f"Invalid location format: {location}")

    lat_str = location[:3]   # N17 / S16
    lon_str = location[3:]   # W62 / E38

    lat = int(lat_str[1:]) * (1 if lat_str[0].upper() == "N" else -1)
    lon = int(lon_str[1:]) * (1 if lon_str[0].upper() == "W" else -1)

    return lat, lon


def score_region(region, tw_hour=None):
    """
    僅對 Section I 的 sunspot regions 做風險評分
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
    elif "alpha" in mag:
        score += 0

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


def parse_srs_full(text):
    """
    完整解析 NOAA SWPC srs.txt 三段:
      I.  Regions with Sunspots.
      IA. H-alpha Plages without Spots.
      II. Regions Due to Return

    回傳結構:
    {
        "meta": {...},
        "sections": {
            "regions_with_sunspots": [...],
            "plages_without_spots": [...],
            "regions_due_to_return": [...]
        }
    }
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

    regions_with_sunspots = []
    plages_without_spots = []
    regions_due_to_return = []

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            continue

        # --------
        # Metadata
        # --------
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

        # -----------------------
        # Section start detection
        # -----------------------
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

        # --------------
        # Section I parse
        # --------------
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

            regions_with_sunspots.append({
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
            })
            continue

        # ---------------
        # Section IA parse
        # ---------------
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

            plages_without_spots.append({
                "id": ar_id,
                "location": location,
                "lat": lat,
                "lon": lon,
                "lo": lo,
            })
            continue

        # --------------
        # Section II parse
        # --------------
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
            lat_str = parts[1]
            lo = int(parts[2])

            try:
                lat = parse_lat(lat_str)
            except ValueError:
                continue

            regions_due_to_return.append({
                "id": ar_id,
                "lat": lat,
                "lo": lo,
            })
            continue

    return {
        "meta": meta,
        "sections": {
            "regions_with_sunspots": regions_with_sunspots,
            "plages_without_spots": plages_without_spots,
            "regions_due_to_return": regions_due_to_return,
        }
    }


def plot_solar_risk_map_from_srs(parsed):
    """
    只繪製 Section I: Regions with Sunspots
    """
    ar_list = parsed["sections"]["regions_with_sunspots"]
    tw_hour = datetime.now(pytz.timezone("Asia/Taipei")).hour

    if not ar_list:
        print("警告：Section I 找不到任何活動區資料")
        return

    for region in ar_list:
        region["score"] = score_region(region, tw_hour=tw_hour)

    fig, ax = plt.subplots(figsize=(8, 8))

    sun_circle = plt.Circle((0, 0), 90, color="yellow", alpha=0.2)
    ax.add_artist(sun_circle)

    ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
    ax.axvline(0, color="red", linestyle="-", alpha=0.7, label="Central Meridian (CM)")
    ax.axvline(-30, color="orange", linestyle="--", alpha=0.5)
    ax.axvline(30, color="orange", linestyle="--", alpha=0.5)

    for ar in ar_list:
        color = "red" if ar["score"] >= 70 else ("orange" if ar["score"] >= 40 else "royalblue")

        ax.scatter(
            ar["lon"], ar["lat"],
            s=250, c=color, edgecolors="black", zorder=3, alpha=0.85
        )

        ax.text(
            ar["lon"] + 3,
            ar["lat"] + 3,
            f"AR{ar['id']}\n{ar['mag_type']}",
            fontsize=8.5,
            fontweight="bold",
            color="black"
        )

    ax.set_xlim(-100, 100)
    ax.set_ylim(-100, 100)
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude (East < 0 > West)")
    ax.set_ylabel("Latitude (South < 0 > North)")
    ax.set_title(
        "Solar Active Regions Risk Map\n"
        f"{parsed['meta']['issued_utc']} | Taiwan Time: {tw_hour:02d}:00",
        pad=20
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    plt.show()


def print_srs_summary(parsed):
    """
    簡單列印三段解析結果摘要
    """
    meta = parsed["meta"]
    sec = parsed["sections"]

    print("=== SRS META ===")
    for k, v in meta.items():
        print(f"{k}: {v}")

    print("\n=== Section I: Regions with Sunspots ===")
    print(f"Count: {len(sec['regions_with_sunspots'])}")
    for r in sec["regions_with_sunspots"]:
        print(r)

    print("\n=== Section IA: H-alpha Plages without Spots ===")
    print(f"Count: {len(sec['plages_without_spots'])}")
    for r in sec["plages_without_spots"]:
        print(r)

    print("\n=== Section II: Regions Due to Return ===")
    print(f"Count: {len(sec['regions_due_to_return'])}")
    for r in sec["regions_due_to_return"]:
        print(r)


def main():
    text = fetch_srs_text()
    parsed = parse_srs_full(text)

    print_srs_summary(parsed)
    plot_solar_risk_map_from_srs(parsed)


if __name__ == "__main__":
    main()