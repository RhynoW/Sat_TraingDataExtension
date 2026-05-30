"""
annotate_starlink.py
====================
對 Starlink LEO 衛星做離線標註（零 HTTP 請求）：
  - 從 DuckDB 取 launch_date 判斷版本，套版本質量對照表
  - 再從 UCS Excel 補充（少數 Starlink 有 UCS 記錄）
  - 軌道帶直接從 DuckDB 的 mean_alt_km 計算

版本質量對照（SpaceX 官方數據）：
  v1.0  launch < 2021-09-13  : 260 kg
  v1.5  2021-09-13 ~ 2023-02-26 : 303 kg
  v2mini launch >= 2023-02-27  : 800 kg
"""

import argparse
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

# ── 版本對照表 ──────────────────────────────────────────────────────────────
VERSION_TABLE = [
    # (launch_date_cutoff_exclusive, version_label, mass_kg)
    ("2021-09-13", "v1.0",   260.0),
    ("2023-02-27", "v1.5",   303.0),
    (None,         "v2mini", 800.0),
]

DEFAULT_DB  = r"C:\STK_Python\CCIT_Orbit_Maneuvers\GCP_Version\space_db.duckdb"
DEFAULT_UCS = r"UCS_Satellite_Database\UCS-Satellite-Database 5-1-2023.xlsx"
DEFAULT_IN  = r"input_leo_starlink.csv"
DEFAULT_OUT = r"output\annotations_starlink.csv"

SCHEMA = [
    "norad_id", "cospar_id", "sat_name", "orbit_band",
    "mass_kg", "mass_class", "platform_class", "propulsion_class",
    "propulsion_description", "mission_type",
    "mass_source", "propulsion_source",
    "mass_confidence", "propulsion_confidence",
    "mass_note", "propulsion_note",
]


# ── 分類函式（與主程式一致）───────────────────────────────────────────────
def classify_orbit_band(alt_km):
    if alt_km is None:
        return ""
    if 300 <= alt_km <= 450:
        return "LEO_300_450"
    elif 450 < alt_km <= 800:
        return "LEO_450_800"
    elif 800 < alt_km <= 1000:
        return "LEO_800_1000"
    return "OUT_OF_RANGE"


def classify_mass(mass_kg):
    if mass_kg is None:
        return ""
    if mass_kg < 10:    return "<10kg"
    if mass_kg < 50:    return "10_50kg"
    if mass_kg < 200:   return "50_200kg"
    if mass_kg < 1000:  return "200_1000kg"
    return ">1000kg"


def classify_platform(mass_kg):
    if mass_kg is None: return "Unknown"
    if mass_kg < 50:    return "Cube/Nano"
    if mass_kg < 200:   return "Micro"
    return "Small/Medium"


def map_mission_type(purpose):
    p = (purpose or "").lower()
    if any(x in p for x in ["communication", "telecom", "relay", "iot", "broadband", "connectivity"]):
        return "COMM"
    if any(x in p for x in ["earth observation", "remote sensing", "imaging", "surveillance"]):
        return "EO"
    if any(x in p for x in ["technology", "demo", "experiment", "test", "demonstration"]):
        return "TechDemo"
    if any(x in p for x in ["science", "research", "astronomy"]):
        return "Science"
    if any(x in p for x in ["navigation", "gps", "gnss", "positioning"]):
        return "Nav"
    return "Other"


def starlink_version(launch_date_str: str):
    """回傳 (version_label, mass_kg)"""
    ld = str(launch_date_str or "")[:10]
    for cutoff, label, mass in VERSION_TABLE:
        if cutoff is None or ld < cutoff:
            return label, mass
    return "v2mini", 800.0


# ── UCS 輔助 ────────────────────────────────────────────────────────────────
def load_ucs(xlsx_path: str) -> pd.DataFrame | None:
    p = Path(xlsx_path)
    if not p.exists():
        print(f"[WARN] UCS 檔案不存在：{xlsx_path}，略過 UCS 補充")
        return None
    df = pd.read_excel(xlsx_path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["_norad"] = (
        df.get("NORAD Number", pd.Series(dtype=str))
        .fillna("").str.strip().str.replace(r"\.0$", "", regex=True)
    )
    return df


def ucs_lookup(ucs: pd.DataFrame, norad: str, name: str) -> pd.Series | None:
    m = ucs[ucs["_norad"] == norad]
    if not m.empty:
        return m.iloc[0]
    if name and "Name of Satellite, Alternate Names" in ucs.columns:
        m = ucs[ucs["Name of Satellite, Alternate Names"]
                .str.upper().str.contains(name.upper(), na=False, regex=False)]
        if not m.empty:
            return m.iloc[0]
    return None


def parse_mass(raw) -> float | None:
    s = str(raw or "").strip()
    if s in ("", "nan", "NaN"):
        return None
    m = re.search(r"[\d.]+", s.replace(",", ""))
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


# ── 主流程 ───────────────────────────────────────────────────────────────────
def run(db_path: str, ucs_path: str, input_csv: str, output_csv: str) -> None:
    # 1. 從 DuckDB 取 Starlink 的 launch_date 與軌道資料
    print("從 DuckDB 讀取 Starlink 衛星資料 ...")
    con = duckdb.connect(db_path, read_only=True)
    meta = con.execute("""
        SELECT norad_id,
               name_en,
               intl_code,
               launch_date::DATE AS launch_date,
               ROUND((perigee_km+apogee_km)/2,1) AS mean_alt_km
        FROM sat_n2yo_metadata
        WHERE name_en LIKE 'STARLINK%'
          AND perigee_km IS NOT NULL AND apogee_km IS NOT NULL
          AND (perigee_km+apogee_km)/2 BETWEEN 300 AND 1000
    """).df()
    con.close()
    meta["norad_str"] = meta["norad_id"].astype(str)
    meta = meta.set_index("norad_str")
    print(f"  → {len(meta)} 筆元資料")

    # 2. 讀入輸入 CSV（export_from_duckdb.py 產生）
    inp = pd.read_csv(input_csv, dtype=str)
    inp.columns = [c.strip().upper() for c in inp.columns]
    print(f"  → 輸入 CSV {len(inp)} 筆")

    # 3. 載入 UCS
    ucs = load_ucs(ucs_path)

    # 4. 逐筆標註
    results = []
    v_counter = {"v1.0": 0, "v1.5": 0, "v2mini": 0, "unknown": 0}
    ucs_hit = 0

    for _, row in inp.iterrows():
        norad   = str(row.get("NORAD_ID", "")).strip()
        cospar  = str(row.get("COSPAR_ID", "")).strip()
        name    = str(row.get("NAME", "")).strip()
        alt_km_raw = row.get("MEAN_ALT_KM", "")
        try:
            alt_km = float(alt_km_raw)
        except (ValueError, TypeError):
            alt_km = None

        rec = {f: "" for f in SCHEMA}
        rec["norad_id"]  = norad
        rec["cospar_id"] = cospar
        rec["sat_name"]  = name
        rec["orbit_band"] = classify_orbit_band(alt_km)

        # 版本質量
        m_row = meta.loc[norad] if norad in meta.index else None
        launch_date = str(m_row["launch_date"]) if m_row is not None else ""
        ver_label, ver_mass = starlink_version(launch_date)

        if launch_date:
            rec["mass_kg"]         = ver_mass
            rec["mass_source"]     = f"Starlink_{ver_label}_table"
            rec["mass_confidence"] = "Medium"
            rec["mass_note"]       = (
                f"Starlink {ver_label} version table; launch_date={launch_date}"
            )
            v_counter[ver_label] = v_counter.get(ver_label, 0) + 1
        else:
            v_counter["unknown"] += 1
            rec["mass_note"] = "launch_date not in DuckDB; version unknown"
            rec["mass_confidence"] = "Low"

        # Starlink 推進：氙離子 Hall thruster（v2 mini 以上用 ion thruster）
        if ver_label in ("v1.0", "v1.5"):
            rec["propulsion_class"]       = "Electric_EP"
            rec["propulsion_description"] = "Krypton/Xenon Hall-effect thruster"
            rec["propulsion_source"]      = f"Starlink_{ver_label}_table"
            rec["propulsion_confidence"]  = "High"
            rec["propulsion_note"]        = "SpaceX Starlink v1 uses Hall-effect EP"
        else:
            rec["propulsion_class"]       = "Electric_EP"
            rec["propulsion_description"] = "Argon Hall-effect thruster (v2 mini)"
            rec["propulsion_source"]      = "Starlink_v2mini_table"
            rec["propulsion_confidence"]  = "High"
            rec["propulsion_note"]        = "SpaceX Starlink v2 mini uses Argon Hall thruster"

        # 任務類型：Starlink 全數為通訊
        rec["mission_type"] = "COMM"

        # UCS 補充（優先覆蓋 mass_confidence 至 High）
        if ucs is not None:
            u = ucs_lookup(ucs, norad, name)
            if u is not None:
                lm = parse_mass(u.get("Launch Mass (kg.)"))
                dm = parse_mass(u.get("Dry Mass (kg.)"))
                if lm is not None:
                    rec["mass_kg"]         = lm
                    rec["mass_source"]     = "UCS"
                    rec["mass_confidence"] = "High"
                    note = f"UCS launch mass: {lm} kg"
                    if dm:
                        note += f"; dry mass: {dm} kg"
                    rec["mass_note"] = note
                    ucs_hit += 1

        # 衍生分類
        try:
            mv = float(rec["mass_kg"]) if rec["mass_kg"] not in ("", None) else None
        except (ValueError, TypeError):
            mv = None
        rec["mass_class"]     = classify_mass(mv)
        rec["platform_class"] = classify_platform(mv)

        results.append(rec)

    # 5. 輸出
    out_df = pd.DataFrame(results, columns=SCHEMA)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n[DONE] Starlink 標註完成")
    print(f"  v1.0  (260kg): {v_counter['v1.0']:>5} 顆")
    print(f"  v1.5  (303kg): {v_counter['v1.5']:>5} 顆")
    print(f"  v2mini(800kg): {v_counter['v2mini']:>5} 顆")
    print(f"  版本未知      : {v_counter['unknown']:>5} 顆")
    print(f"  UCS 補充      : {ucs_hit:>5} 顆")
    print(f"  輸出          : {output_csv}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db",     default=DEFAULT_DB)
    p.add_argument("--ucs",    default=DEFAULT_UCS)
    p.add_argument("--input",  default=DEFAULT_IN)
    p.add_argument("--output", default=DEFAULT_OUT)
    args = p.parse_args()
    run(args.db, args.ucs, args.input, args.output)


if __name__ == "__main__":
    main()
