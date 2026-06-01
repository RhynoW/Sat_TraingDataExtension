#!/usr/bin/env python3
"""
setup_sat_background.py
========================
初始化 sat_background 資料庫表格，並預先填入從
prc_maneuver_flagged_2025ALL.csv Top-100 事件取出的 66 顆衛星基礎資料。

執行後再由 write_sat_profiles.py 補充研究內容並寫 .md 檔。
"""
from pathlib import Path
import duckdb
import pandas as pd

REPO    = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "space_db.duckdb"
PROF_DIR = Path(__file__).resolve().parent / "sat_profiles"
PROF_DIR.mkdir(exist_ok=True)

FLAGGED_CSV = Path(__file__).resolve().parent / "output" / "prc_maneuver_flagged_2025ALL.csv"

# ── 1. 建立表格 ──────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS sat_background (
    norad_id         INTEGER PRIMARY KEY,
    sat_name         VARCHAR,
    cospar_id        VARCHAR,
    constellation    VARCHAR,
    operator_org     VARCHAR,
    mission_type     VARCHAR,
    launch_date      DATE,
    launch_site      VARCHAR,
    launch_vehicle   VARCHAR,
    orbit_type       VARCHAR,
    mass_kg          DOUBLE,
    maneuver_reason  VARCHAR,
    desc_zh          TEXT,
    desc_en          TEXT,
    md_file          VARCHAR,
    data_quality     VARCHAR  DEFAULT 'stub',
    created_at       TIMESTAMP DEFAULT current_timestamp,
    updated_at       TIMESTAMP DEFAULT current_timestamp
);
"""

con = duckdb.connect(str(DB_PATH), read_only=False)
con.execute(DDL)
print("✅ sat_background 表格已建立")

# ── 2. 從 flagged CSV 取 top 100 → unique sats ───────────────────────────────
df = pd.read_csv(str(FLAGGED_CSV))
top100 = df.nlargest(100, "score")
sats = (
    top100
    .drop_duplicates("norad_id")
    [["norad_id", "sat_name", "score"]]
    .sort_values("score", ascending=False)
    .reset_index(drop=True)
)
print(f"Top-100 事件的唯一衛星：{len(sats)} 顆")

# ── 3. 從 sat_n2yo_metadata 取基礎資料 ──────────────────────────────────────
ids = sats["norad_id"].tolist()
id_str = ",".join(map(str, ids))
meta = con.execute(f"""
    SELECT norad_id, intl_code AS cospar_id, launch_date, launch_site,
           perigee_km, apogee_km, inclination_deg
    FROM sat_n2yo_metadata
    WHERE norad_id IN ({id_str})
""").fetchdf()
merged = sats.merge(meta, on="norad_id", how="left")

# ── 4. 星座/任務類型自動分類 ─────────────────────────────────────────────────
def classify(name: str) -> tuple[str, str, str]:
    """(constellation, operator, mission_type)"""
    n = str(name).upper()
    if "GEESAT" in n:
        return "GEESATCOM", "Geespace (Geely)", "IoT/AIS"
    if "TIANQI" in n:
        return "Tianqi", "Guodian Gaoke", "IoT/M2M"
    if "YAOGAN" in n:
        return "Yaogan", "CASC/PLA", "Reconnaissance/SAR"
    if "TIANZHOU" in n:
        return "CSS", "CASC/CNSA", "Cargo/Resupply"
    if "CSS" in n or "TIANHE" in n or "WENTIAN" in n or "MENGTIAN" in n:
        return "CSS", "CASC/CNSA", "Space Station"
    if "CENTISPACE" in n:
        return "Centispace", "Future Navigation", "PNT"
    if "JILIN" in n:
        return "Jilin-1", "CGSTL", "Commercial EO"
    if "SUPERVIEW" in n:
        return "SuperView", "Space View", "Commercial EO"
    if "QIANFAN" in n:
        return "Qianfan", "Shanghai Spacecom", "Broadband LEO"
    if "SHIYAN" in n or "SY-" in n:
        return "Shiyan", "CASC/CAST", "Experimental"
    if "SHIKONGXING" in n:
        return "Shikongxing", "Unknown", "Space Engineering"
    if "HXMT" in n or "HUIYAN" in n:
        return "HXMT", "IHEP/NSSC", "X-ray Astronomy"
    if "HONGHU" in n:
        return "Honghu", "Commercial", "Commercial EO"
    if "SJ-" in n or n.startswith("SJ"):
        return "Shijian", "CASC", "Experimental"
    if "GJZ" in n:
        return "GJZ", "Unknown/PLA", "Unknown"
    if "DEAR" in n:
        return "DEAR", "Unknown", "Commercial"
    if "ARAB SATELLITE" in n:
        return "Commercial", "Commercial", "Commercial"
    if "OBJECT" in n:
        return "Unknown", "Unknown", "Unknown"
    return "Unknown", "Unknown", "Unknown"

rows = []
for _, r in merged.iterrows():
    const, op, mis = classify(r["sat_name"])
    # 軌道類型估算
    if pd.notna(r.get("inclination_deg")):
        inc = float(r["inclination_deg"])
        orbit = "SSO" if 95 <= inc <= 100 else "LEO"
    else:
        orbit = "LEO"

    md_filename = f"{int(r['norad_id'])}_{str(r['sat_name']).replace('/', '-').replace(' ', '_')}.md"
    rows.append({
        "norad_id":        int(r["norad_id"]),
        "sat_name":        r["sat_name"],
        "cospar_id":       r.get("cospar_id", None),
        "constellation":   const,
        "operator_org":    op,
        "mission_type":    mis,
        "launch_date":     str(r["launch_date"])[:10] if pd.notna(r.get("launch_date")) else None,
        "launch_site":     r.get("launch_site", None),
        "launch_vehicle":  None,
        "orbit_type":      orbit,
        "mass_kg":         None,
        "maneuver_reason": None,
        "desc_zh":         None,
        "desc_en":         None,
        "md_file":         f"sat_profiles/{md_filename}",
        "data_quality":    "stub",
    })

df_rows = pd.DataFrame(rows)

# ── 5. 寫入 DB（upsert by norad_id）────────────────────────────────────────
con.register("_new_sats", df_rows)
con.execute("""
    INSERT OR REPLACE INTO sat_background
        (norad_id, sat_name, cospar_id, constellation, operator_org,
         mission_type, launch_date, launch_site, launch_vehicle,
         orbit_type, mass_kg, maneuver_reason, desc_zh, desc_en,
         md_file, data_quality, created_at, updated_at)
    SELECT
        norad_id, sat_name, cospar_id, constellation, operator_org,
        mission_type, launch_date::DATE, launch_site, launch_vehicle,
        orbit_type, mass_kg, maneuver_reason, desc_zh, desc_en,
        md_file, data_quality,
        current_timestamp, current_timestamp
    FROM _new_sats
""")
print(f"✅ {len(rows)} 顆衛星寫入 sat_background")

# ── 6. 建立 stub .md 檔（尚未有內容的先建立佔位符）────────────────────────
for r in rows:
    md_path = Path(__file__).resolve().parent / r["md_file"]
    if not md_path.exists():
        md_path.write_text(
            f"# {r['sat_name']}  (NORAD {r['norad_id']})\n\n"
            f"> stub — 待補充\n\n"
            f"- **COSPAR ID**: {r['cospar_id'] or 'N/A'}\n"
            f"- **星座**: {r['constellation']}\n"
            f"- **運營商**: {r['operator_org']}\n"
            f"- **任務類型**: {r['mission_type']}\n"
            f"- **發射日期**: {r['launch_date'] or 'N/A'}\n"
            f"- **發射場**: {r['launch_site'] or 'N/A'}\n"
            f"- **軌道**: {r['orbit_type']}\n",
            encoding="utf-8",
        )
print(f"✅ {len(rows)} 個 stub .md 已建立於 {PROF_DIR}")

con.close()
print("\n完成。下一步：執行 write_sat_profiles.py 補充研究內容。")
