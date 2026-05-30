"""
merge_annotations.py
====================
合併 Starlink 與非 Starlink 標註，產生完整 LEO 訓練資料集。

用法：
  python merge_annotations.py
  python merge_annotations.py --non-starlink output/annotations_non_starlink_ucs.csv
"""

import argparse
from pathlib import Path
import pandas as pd

SCHEMA = [
    "norad_id", "cospar_id", "sat_name", "orbit_band",
    "mass_kg", "mass_class", "platform_class", "propulsion_class",
    "propulsion_description", "mission_type",
    "mass_source", "propulsion_source",
    "mass_confidence", "propulsion_confidence",
    "mass_note", "propulsion_note",
]

DEFAULT_SL     = "output/annotations_starlink.csv"
DEFAULT_NON_SL = "output/annotations_non_starlink_ucs.csv"
DEFAULT_OUT    = "output/annotations_leo_full.csv"


def merge(sl_path: str, non_sl_path: str, out_path: str) -> None:
    sl  = pd.read_csv(sl_path,     encoding="utf-8-sig", dtype=str)
    nsl = pd.read_csv(non_sl_path, encoding="utf-8-sig", dtype=str)

    print(f"Starlink      : {len(sl):>6} 筆  ({sl_path})")
    print(f"非 Starlink   : {len(nsl):>6} 筆  ({non_sl_path})")

    # 統一 schema（允許欄位不完全一致）
    for col in SCHEMA:
        if col not in sl.columns:
            sl[col] = ""
        if col not in nsl.columns:
            nsl[col] = ""

    merged = pd.concat([sl[SCHEMA], nsl[SCHEMA]], ignore_index=True)

    # 去重（理論上不會有，但防呆）
    before = len(merged)
    merged = merged.drop_duplicates(subset=["norad_id"])
    if len(merged) < before:
        print(f"[WARN] 去除重複 {before - len(merged)} 筆")

    # 統計
    has_mass = merged["mass_kg"].notna() & (merged["mass_kg"].astype(str).str.strip() != "")
    has_prop = ~merged["propulsion_class"].isin(["None", ""]) & merged["propulsion_class"].notna()

    merged.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n合計          : {len(merged):>6} 筆")
    print(f"有質量資料    : {has_mass.sum():>6} 筆 ({has_mass.mean()*100:.1f}%)")
    print(f"有推進資料    : {has_prop.sum():>6} 筆 ({has_prop.mean()*100:.1f}%)")
    print()
    print("質量來源分布：")
    print(merged[has_mass]["mass_source"].value_counts().to_string())
    print()
    print("推進類別分布：")
    print(merged[has_prop]["propulsion_class"].value_counts().to_string())
    print(f"\n[DONE] 輸出 -> {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--starlink",     default=DEFAULT_SL)
    p.add_argument("--non-starlink", default=DEFAULT_NON_SL)
    p.add_argument("--output",       default=DEFAULT_OUT)
    args = p.parse_args()
    merge(args.starlink, args.non_starlink, args.output)


if __name__ == "__main__":
    main()
