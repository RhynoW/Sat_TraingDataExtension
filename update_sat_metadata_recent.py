#!/usr/bin/env python3
"""
update_sat_metadata_recent.py

從 Space-Track satcat 端點查詢最近 N 天發射的衛星，
更新/新增 sat_metadata.csv（同步更新 data/tle_parquet/sat_metadata.parquet）。

用法:
    python update_sat_metadata_recent.py            # 預設 30 天
    python update_sat_metadata_recent.py --days 60  # 最近 60 天
    python update_sat_metadata_recent.py --dry-run  # 預覽，不寫入
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from spacetrack import SpaceTrackClient
import spacetrack.operators as op

# ──────────────────────────────────────────────────────────────────────────────
# 常數
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

_DIR = Path(__file__).resolve().parent
CSV_PATH     = _DIR / "sat_metadata.csv"
PARQUET_PATH = _DIR / "data" / "tle_parquet" / "sat_metadata.parquet"

# Space-Track OWNER 代碼 → 顯示名稱對照表
# 格式與既有 CSV 一致：「完整名稱 (縮寫)」
OWNER_MAP: dict[str, str] = {
    "AB":   "Arab Satellite Comm. Org. (AB)",
    "ABS":  "Asia Broadcast Satellite (ABS)",
    "AC":   "Orbit/Coface (AC)",
    "AE":   "United Arab Emirates (AE)",
    "AFRI": "Africa (AFRI)",
    "AG":   "Argentina (AG)",
    "ARGN": "Argentina (ARGN)",
    "ALG":  "Algeria (ALG)",
    "AO":   "Angola (AO)",
    "AUS":  "Australia (AUS)",
    "AZER": "Azerbaijan (AZER)",
    "AB":   "Arab League (AB)",
    "BELA": "Belarus (BELA)",
    "BNSC": "United Kingdom (BNSC)",
    "BOL":  "Bolivia (BOL)",
    "BRAZ": "Brazil (BRAZ)",
    "CA":   "Canada (CA)",
    "CIS":  "Commonwealth of Independent States (CIS)",
    "CN":   "China (CN)",
    "COL":  "Colombia (COL)",
    "CZE":  "Czech Republic (CZE)",
    "DEN":  "Denmark (DEN)",
    "ECU":  "Ecuador (ECU)",
    "EGPT": "Egypt (EGPT)",
    "ESA":  "European Space Agency (ESA)",
    "ESRO": "European Space Agency (ESRO)",
    "EST":  "Estonia (EST)",
    "ETH":  "Ethiopia (ETH)",
    "EUME": "EUMETSAT (EUME)",
    "EUTE": "Eutelsat (EUTE)",
    "FGER": "France/Germany (FGER)",
    "FR":   "France (FR)",
    "FRIT": "France/Italy (FRIT)",
    "GER":  "Germany (GER)",
    "GLOB": "Globalstar (GLOB)",
    "GRSA": "Greece (GRSA)",
    "HKNG": "Hong Kong (HKNG)",
    "HUN":  "Hungary (HUN)",
    "IM":   "INMARSAT (IM)",
    "IND":  "India (IND)",
    "INDO": "Indonesia (INDO)",
    "IRAN": "Iran (IRAN)",
    "IRAQ": "Iraq (IRAQ)",
    "IRID": "Iridium (IRID)",
    "ISR":  "Israel (ISR)",
    "ISS":  "International Space Station (ISS)",
    "IT":   "Italy (IT)",
    "ITSO": "INTELSAT (ITSO)",
    "JPN":  "Japan (JPN)",
    "KAZ":  "Kazakhstan (KAZ)",
    "LAOS": "Laos (LAOS)",
    "LKA":  "Sri Lanka (LKA)",
    "LTU":  "Lithuania (LTU)",
    "LUXE": "Luxembourg (LUXE)",
    "MA":   "Morocco (MA)",
    "MALA": "Malaysia (MALA)",
    "MEX":  "Mexico (MEX)",
    "MMR":  "Myanmar (MMR)",
    "MNG":  "Mongolia (MNG)",
    "NATO": "NATO (NATO)",
    "NETH": "Netherlands (NETH)",
    "NICO": "New ICO (NICO)",
    "NIG":  "Nigeria (NIG)",
    "NOR":  "Norway (NOR)",
    "NPK":  "North Korea (NPK)",
    "NZ":   "New Zealand (NZ)",
    "O3B":  "O3b Networks (O3B)",
    "ORB":  "Orbcomm (ORB)",
    "PAKI": "Pakistan (PAKI)",
    "PERU": "Peru (PERU)",
    "POL":  "Poland (POL)",
    "POR":  "Portugal (POR)",
    "PRC":  "China (PRC)",
    "QAT":  "Qatar (QAT)",
    "RASC": "RascomStar-QAF (RASC)",
    "ROM":  "Romania (ROM)",
    "RP":   "Philippines (RP)",
    "RU":   "Russia (RU)",
    "RUSA": "Russia (RUSA)",
    "SAFR": "South Africa (SAFR)",
    "SAUD": "Saudi Arabia (SAUD)",
    "SEA":  "Sea Launch (SEA)",
    "SEAL": "Sea Launch (SEAL)",
    "SES":  "SES (SES)",
    "SING": "Singapore (SING)",
    "STCT": "SingTel (STCT)",
    "SVN":  "Slovenia (SVN)",
    "SWED": "Sweden (SWED)",
    "SWTZ": "Switzerland (SWTZ)",
    "TBD":  "TBD",
    "THAI": "Thailand (THAI)",
    "TMMC": "Turkmenistan (TMMC)",
    "TUR":  "Turkey (TUR)",
    "UAE":  "United Arab Emirates (UAE)",
    "UK":   "United Kingdom (UK)",
    "UKR":  "Ukraine (UKR)",
    "URY":  "Uruguay (URY)",
    "US":   "United States (US)",
    "USBZ": "US/Brazil (USBZ)",
    "VENZ": "Venezuela (VENZ)",
    "VIET": "Vietnam (VIET)",
}

# OBJECT_TYPE → 中文 purpose
OBJECT_TYPE_MAP: dict[str, str] = {
    "PAYLOAD":     "有效載荷",
    "ROCKET BODY": "火箭體",
    "DEBRIS":      "碎片",
    "UNKNOWN":     "未知",
    "TBA":         "有效載荷",  # To Be Assigned — 預設有效載荷
    "OTHER":       "其他",
}


# ──────────────────────────────────────────────────────────────────────────────
# 主邏輯
# ──────────────────────────────────────────────────────────────────────────────

def fetch_recent_satcat(days: int) -> pd.DataFrame:
    """從 Space-Track 下載最近 N 天發射的衛星 satcat 記錄。"""
    identity = os.getenv("SPACE_TRACK_IDENTITY")
    password = os.getenv("SPACE_TRACK_PASSWORD")
    if not identity or not password:
        raise RuntimeError(
            "請在 .env 設定 SPACE_TRACK_IDENTITY 與 SPACE_TRACK_PASSWORD"
        )

    today = date.today()
    cutoff = today - timedelta(days=days)
    date_range = op.inclusive_range(
        cutoff.strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
    )

    print(f"[fetch] 查詢 Space-Track satcat：發射日期 {cutoff} ~ {today} …", flush=True)
    st = SpaceTrackClient(identity=identity, password=password)
    records = st.satcat(
        launch=date_range,
        orderby="NORAD_CAT_ID asc",
        format="json",
    )

    if not records:
        print("[fetch] 查無資料", flush=True)
        return pd.DataFrame()

    # spacetrack 回傳 JSON 字串；parse 後建 DataFrame
    if isinstance(records, str):
        records = json.loads(records)
    if not records:
        print("[fetch] 查無資料", flush=True)
        return pd.DataFrame()

    df = pd.DataFrame(records)
    print(f"[fetch] 取得 {len(df):,} 筆記錄", flush=True)
    return df


def map_satcat_to_metadata(df_raw: pd.DataFrame) -> pd.DataFrame:
    """將 Space-Track satcat DataFrame 轉為 sat_metadata 欄位格式。

    satcat JSON 欄位（小寫）:
      norad_cat_id / object_number → norad_id
      object_name / satname        → name_en
      country                      → source_code
      launch                       → launch_date
      intldes / object_id          → intl_code
      object_type                  → purpose
    """
    # 統一欄位名稱為小寫（API 有時回大寫）
    df_raw = df_raw.rename(columns=lambda c: c.lower())

    rows = []
    for _, r in df_raw.iterrows():
        norad_id = r.get("norad_cat_id") or r.get("object_number")
        if norad_id is None:
            continue
        try:
            norad_id = int(norad_id)
        except (ValueError, TypeError):
            continue

        name_en   = (r.get("object_name") or r.get("satname") or "").strip()
        owner_raw = (r.get("country") or "TBD").strip()
        source_code = OWNER_MAP.get(owner_raw, owner_raw)

        launch_date_raw = r.get("launch") or ""
        if launch_date_raw:
            try:
                launch_date = pd.to_datetime(launch_date_raw).strftime("%Y-%m-%d")
            except Exception:
                launch_date = str(launch_date_raw)
        else:
            launch_date = ""

        intl_code = (r.get("intldes") or r.get("object_id") or "").strip()

        obj_type  = (r.get("object_type") or "TBA").strip().upper()
        purpose   = OBJECT_TYPE_MAP.get(obj_type, "有效載荷")

        rows.append({
            "norad_id":    norad_id,
            "name_en":     name_en,
            "source_code": source_code,
            "launch_date": launch_date,
            "intl_code":   intl_code,
            "purpose":     purpose,
            "constellation": "",
            "notes":       "src:satcat",
        })

    return pd.DataFrame(rows)


def update_metadata(days: int, dry_run: bool) -> None:
    # 1. 讀取現有 CSV
    print(f"[load] 讀取 {CSV_PATH} …", flush=True)
    df_existing = pd.read_csv(CSV_PATH, dtype={"norad_id": int})
    print(f"[load] 現有 {len(df_existing):,} 筆", flush=True)

    # 2. 取得 Space-Track 近期資料
    df_raw = fetch_recent_satcat(days)
    if df_raw.empty:
        print("[done] 無新資料，結束。", flush=True)
        return

    df_new = map_satcat_to_metadata(df_raw)

    # 3. 合併：以 norad_id 為 key
    existing_ids  = set(df_existing["norad_id"])
    new_ids       = set(df_new["norad_id"])

    added_ids     = new_ids - existing_ids
    updated_ids   = new_ids & existing_ids

    df_added   = df_new[df_new["norad_id"].isin(added_ids)]
    df_updated = df_new[df_new["norad_id"].isin(updated_ids)]

    print(f"\n[diff] 新增: {len(df_added):,} 筆 | 可能更新: {len(df_updated):,} 筆")

    if dry_run:
        print("\n=== DRY RUN — 不寫入任何檔案 ===")
        if not df_added.empty:
            print("\n[新增衛星]")
            print(df_added[["norad_id", "name_en", "source_code", "launch_date",
                             "intl_code", "purpose"]].to_string(index=False))
        if not df_updated.empty:
            print("\n[已存在但有更新的衛星（欄位將合併）]")
            _show_diff(df_existing, df_updated, updated_ids)
        return

    # 4. 更新既有列（以 Space-Track 資料補填空值欄位）
    n_updated = 0
    for _, row_new in df_updated.iterrows():
        nid = row_new["norad_id"]
        mask = df_existing["norad_id"] == nid
        row_old = df_existing[mask].iloc[0]

        changed = False
        for col in ["name_en", "source_code", "launch_date", "intl_code", "purpose"]:
            old_val = str(row_old[col]).strip() if pd.notna(row_old[col]) else ""
            new_val = str(row_new[col]).strip() if pd.notna(row_new[col]) else ""
            # 只在舊值為空或為 TBD/TBA 時才用新值覆蓋
            if new_val and (not old_val or old_val.upper() in ("TBD", "TBA", "TBA - TO BE ASSIGNED", "NAN")):
                df_existing.loc[mask, col] = new_val
                changed = True

        if changed:
            # 更新 notes 追加 satcat 標記
            existing_notes = str(row_old.get("notes", "")).strip()
            if "src:satcat" not in existing_notes:
                df_existing.loc[mask, "notes"] = (
                    existing_notes + ";src:satcat" if existing_notes else "src:satcat"
                )
            n_updated += 1

    print(f"[update] 實際更新（有欄位變更）: {n_updated} 筆", flush=True)

    # 5. 新增列
    if not df_added.empty:
        df_existing = pd.concat([df_existing, df_added], ignore_index=True)
        df_existing = df_existing.sort_values("norad_id").reset_index(drop=True)
        print(f"[add] 新增 {len(df_added)} 筆並依 norad_id 排序", flush=True)

    # 6. 寫入 CSV
    df_existing.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print(f"[save] 寫入 {CSV_PATH}（共 {len(df_existing):,} 筆）", flush=True)

    # 7. 同步 parquet
    if PARQUET_PATH.parent.exists():
        df_existing.to_parquet(PARQUET_PATH, index=False)
        print(f"[save] 寫入 {PARQUET_PATH}", flush=True)
    else:
        print(f"[warn] parquet 目錄不存在，略過：{PARQUET_PATH.parent}", flush=True)

    print("\n[done] 完成。", flush=True)


def _show_diff(df_existing: pd.DataFrame, df_updated: pd.DataFrame, ids: set) -> None:
    cols = ["norad_id", "name_en", "source_code", "launch_date", "intl_code", "purpose"]
    for nid in sorted(ids):
        old = df_existing[df_existing["norad_id"] == nid].iloc[0]
        new = df_updated[df_updated["norad_id"] == nid].iloc[0]
        diffs = {}
        for c in cols[1:]:
            ov = str(old.get(c, "")).strip()
            nv = str(new.get(c, "")).strip()
            if ov != nv:
                diffs[c] = (ov, nv)
        if diffs:
            print(f"  NORAD {nid} ({old['name_en']}):")
            for c, (o, n) in diffs.items():
                print(f"    {c}: [{o}] → [{n}]")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="更新最近 N 天發射衛星的基本資料（sat_metadata.csv）"
    )
    parser.add_argument(
        "--days", type=int, default=30, metavar="N",
        help="查詢最近 N 天發射的衛星（預設 30）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只顯示差異，不實際寫入檔案"
    )
    args = parser.parse_args()

    update_metadata(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
