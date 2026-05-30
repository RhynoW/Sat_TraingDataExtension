"""
patch_ucs.py
============
將 UCS Satellite Database 的質量 / 任務類型資料後補進現有 annotations CSV，
只填補尚缺資料的欄位，不覆蓋 NanosatDB / Gunter's 已有的資料。

用法：
  python patch_ucs.py \
      --annotations output/annotations_non_starlink.csv \
      --ucs "UCS_Satellite_Database/UCS-Satellite-Database 5-1-2023.xlsx" \
      --output output/annotations_non_starlink_patched.csv
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


# ── 與 leo_satellite_annotator.py 相同的 mission_type 對應邏輯 ──────────────
def map_mission_type(purpose: str) -> str:
    p = (purpose or "").lower()
    if any(x in p for x in ["communication", "telecom", "relay", "iot", "broadband", "connectivity"]):
        return "COMM"
    if any(x in p for x in ["earth observation", "remote sensing", "imaging", "surveillance"]):
        return "EO"
    if any(x in p for x in ["technology", "demo", "experiment", "test", "demonstration"]):
        return "TechDemo"
    if any(x in p for x in ["science", "research", "astronomy", "space science"]):
        return "Science"
    if any(x in p for x in ["navigation", "gps", "gnss", "positioning", "timing"]):
        return "Nav"
    return "Other"


def classify_mass(mass_kg):
    if mass_kg is None:
        return ""
    if mass_kg < 10:
        return "<10kg"
    elif mass_kg < 50:
        return "10_50kg"
    elif mass_kg < 200:
        return "50_200kg"
    elif mass_kg < 1000:
        return "200_1000kg"
    return ">1000kg"


def classify_platform(mass_kg):
    if mass_kg is None:
        return "Unknown"
    if mass_kg < 50:
        return "Cube/Nano"
    elif mass_kg < 200:
        return "Micro"
    return "Small/Medium"


def _parse_mass(raw: str) -> float | None:
    if not raw or str(raw).strip() in ("", "nan", "NaN"):
        return None
    m = re.search(r"[\d.]+", str(raw).replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def load_ucs(xlsx_path: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx_path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    # 標準化 NORAD 欄位為字串（去除空白、去除小數點）
    if "NORAD Number" in df.columns:
        df["_norad"] = (
            df["NORAD Number"]
            .fillna("")
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )
    else:
        df["_norad"] = ""
    return df


def lookup_ucs_row(ucs: pd.DataFrame, norad_id: str, sat_name: str) -> pd.Series | None:
    # 1. NORAD 精確比對
    match = ucs[ucs["_norad"] == str(norad_id).strip()]
    if not match.empty:
        return match.iloc[0]

    # 2. 衛星名稱子字串比對（大小寫不分）
    if sat_name and "Name of Satellite, Alternate Names" in ucs.columns:
        name_upper = sat_name.strip().upper()
        match = ucs[
            ucs["Name of Satellite, Alternate Names"]
            .str.upper()
            .str.contains(name_upper, na=False, regex=False)
        ]
        if not match.empty:
            return match.iloc[0]
    return None


def patch(annotations_path: str, ucs_path: str, output_path: str) -> None:
    ann = pd.read_csv(annotations_path, encoding="utf-8-sig", dtype=str)
    ucs = load_ucs(ucs_path)

    print(f"annotations : {len(ann)} 筆")
    print(f"UCS         : {len(ucs)} 筆")

    # 缺質量的行索引
    missing_mask = ann["mass_kg"].isna() | (ann["mass_kg"].str.strip() == "")
    print(f"缺質量      : {missing_mask.sum()} 筆 → 嘗試從 UCS 補填")

    matched = 0
    mission_updated = 0

    for idx in ann.index[missing_mask]:
        norad = str(ann.at[idx, "norad_id"]).strip()
        name  = str(ann.at[idx, "sat_name"]).strip()

        row = lookup_ucs_row(ucs, norad, name)
        if row is None:
            continue

        # 解析質量
        launch_mass = _parse_mass(row.get("Launch Mass (kg.)", ""))
        dry_mass    = _parse_mass(row.get("Dry Mass (kg.)", ""))

        if launch_mass is not None:
            ann.at[idx, "mass_kg"]         = launch_mass
            ann.at[idx, "mass_source"]     = "UCS"
            ann.at[idx, "mass_confidence"] = "High"
            note = f"UCS launch mass: {launch_mass} kg"
            if dry_mass is not None:
                note += f"; dry mass: {dry_mass} kg"
            ann.at[idx, "mass_note"] = note
            matched += 1
        elif dry_mass is not None:
            ann.at[idx, "mass_kg"]         = dry_mass
            ann.at[idx, "mass_source"]     = "UCS"
            ann.at[idx, "mass_confidence"] = "Medium"
            ann.at[idx, "mass_note"]       = f"UCS dry mass only: {dry_mass} kg"
            matched += 1

    # mission_type 補填（所有 "Other" 行也重新從 UCS Purpose 推算）
    other_mask = ann["mission_type"].isin(["Other", "", None]) | ann["mission_type"].isna()
    for idx in ann.index[other_mask]:
        norad = str(ann.at[idx, "norad_id"]).strip()
        name  = str(ann.at[idx, "sat_name"]).strip()
        row = lookup_ucs_row(ucs, norad, name)
        if row is None:
            continue
        purpose = str(row.get("Purpose", "")).strip()
        mt = map_mission_type(purpose)
        if mt != "Other":
            ann.at[idx, "mission_type"] = mt
            mission_updated += 1

    # 重新計算 mass_class / platform_class
    for idx in ann.index:
        raw = ann.at[idx, "mass_kg"]
        try:
            mass_val = float(raw) if raw not in (None, "", "nan") else None
        except (ValueError, TypeError):
            mass_val = None
        ann.at[idx, "mass_class"]     = classify_mass(mass_val)
        ann.at[idx, "platform_class"] = classify_platform(mass_val)

    ann.to_csv(output_path, index=False, encoding="utf-8-sig")

    total_with_mass = (ann["mass_kg"].notna() & (ann["mass_kg"].astype(str).str.strip() != "")).sum()
    print(f"\n[DONE] UCS 補填完成")
    print(f"  質量新增    : +{matched} 筆")
    print(f"  任務類型更新: +{mission_updated} 筆")
    print(f"  最終有質量  : {total_with_mass} / {len(ann)} ({total_with_mass/len(ann)*100:.1f}%)")
    print(f"  輸出        : {output_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Patch annotations with UCS mass data")
    p.add_argument("--annotations", "-a",
                   default="output/annotations_non_starlink.csv")
    p.add_argument("--ucs", "-u",
                   default=r"UCS_Satellite_Database/UCS-Satellite-Database 5-1-2023.xlsx")
    p.add_argument("--output", "-o",
                   default="output/annotations_non_starlink_patched.csv")
    args = p.parse_args()
    patch(args.annotations, args.ucs, args.output)


if __name__ == "__main__":
    main()
