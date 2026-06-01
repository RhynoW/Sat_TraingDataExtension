#!/usr/bin/env python3
"""
write_sat_profiles.py
=====================
讀取 prc_maneuver/sat_profiles/ 目錄下已撰寫完成的 .md 檔案，
解析結構化欄位，並 UPDATE 到 DuckDB 的 sat_background 資料表。

用法：
    python prc_maneuver/write_sat_profiles.py [--dry-run]

選項：
    --dry-run   僅顯示將要寫入的欄位，不實際更新資料庫
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime

import duckdb

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
REPO     = Path(__file__).resolve().parent.parent
DB_PATH  = REPO / "space_db.duckdb"
PROF_DIR = Path(__file__).resolve().parent / "sat_profiles"

# ── 從 .md 解析欄位 ──────────────────────────────────────────────────────────

# 從第一行提取 NORAD ID
NORAD_RE = re.compile(r"\(NORAD\s+(\d+)\)", re.IGNORECASE)

# 從表格行提取欄位值：| 欄位名 | 值 |
TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")

# 解析 ## 段落
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def parse_table_value(value: str) -> str | None:
    """清理表格值：N/A → None，去除空白"""
    v = value.strip()
    if v in ("N/A", "N/A（待確認）", "N/A（推測）", "N/A（分類衛星）", ""):
        return None
    return v


def extract_mass_kg(value: str | None) -> float | None:
    """從質量字串中提取數字，如 '~2,800 kg' → 2800.0"""
    if value is None:
        return None
    # 找到第一個數字（含逗號）
    m = re.search(r"[\d,]+", value.replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def parse_md(md_path: Path) -> dict:
    """解析單個 .md 檔案，回傳結構化欄位 dict"""
    text = md_path.read_text(encoding="utf-8")
    result: dict = {"md_file": f"sat_profiles/{md_path.name}"}

    # 1. 提取 NORAD ID（從第一行標題）
    first_line = text.split("\n")[0]
    m = NORAD_RE.search(first_line)
    if m:
        result["norad_id"] = int(m.group(1))
    else:
        # 嘗試從檔名提取
        fname_m = re.match(r"^(\d+)_", md_path.name)
        if fname_m:
            result["norad_id"] = int(fname_m.group(1))
        else:
            return result  # 無法識別，跳過

    # 2. 偵測 data_quality（inferred 旗標）
    if "data_quality: inferred" in text or "推斷（inferred）" in text:
        result["data_quality"] = "inferred"
    elif "> stub — 待補充" in text:
        result["data_quality"] = "stub"
    else:
        result["data_quality"] = "researched"

    # 3. 解析「## 基本資訊」表格
    # 找到基本資訊段落
    info_m = re.search(r"## 基本資訊\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if info_m:
        table_text = info_m.group(1)
        for line in table_text.split("\n"):
            row_m = TABLE_ROW_RE.match(line)
            if not row_m:
                continue
            key = row_m.group(1).strip()
            val = parse_table_value(row_m.group(2))

            key_lower = key.lower()
            if "cospar" in key_lower:
                result["cospar_id"] = val
            elif "星座" in key or "系列" in key:
                result["constellation"] = val
            elif "運營商" in key:
                result["operator_org"] = val
            elif "任務類型" in key:
                result["mission_type"] = val
            elif "發射日期" in key:
                result["launch_date"] = val
            elif "發射場" in key:
                result["launch_site"] = val
            elif "運載火箭" in key:
                result["launch_vehicle"] = val
            elif "軌道" in key:
                result["orbit_type"] = val
            elif "質量" in key:
                result["mass_kg_raw"] = val

    # 4. 提取質量數字
    mass_raw = result.pop("mass_kg_raw", None)
    result["mass_kg"] = extract_mass_kg(mass_raw)

    # 5. 提取 ## 機動行為分析 段落作為 maneuver_reason
    maneuver_m = re.search(r"## 機動行為分析\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if maneuver_m:
        maneuver_text = maneuver_m.group(1).strip()
        # 取第一段（第一個空行前）
        first_para = maneuver_text.split("\n\n")[0].strip()
        # 去除 Markdown 格式（加粗等）
        first_para = re.sub(r"\*\*(.+?)\*\*", r"\1", first_para)
        result["maneuver_reason"] = first_para[:2000] if first_para else None
    else:
        result["maneuver_reason"] = None

    # 6. 提取 ## 任務背景 作為 desc_zh
    bg_m = re.search(r"## 任務背景\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if bg_m:
        desc_zh = bg_m.group(1).strip()
        desc_zh = re.sub(r"\*\*(.+?)\*\*", r"\1", desc_zh)
        result["desc_zh"] = desc_zh[:4000] if desc_zh else None
    else:
        result["desc_zh"] = None

    # 7. desc_en 暫時不填（未來擴充）
    result["desc_en"] = None

    return result


# ── 資料庫 UPDATE ────────────────────────────────────────────────────────────

UPDATE_SQL = """
UPDATE sat_background
SET
    operator_org    = COALESCE($operator_org, operator_org),
    mission_type    = COALESCE($mission_type, mission_type),
    launch_vehicle  = COALESCE($launch_vehicle, launch_vehicle),
    mass_kg         = COALESCE($mass_kg, mass_kg),
    maneuver_reason = COALESCE($maneuver_reason, maneuver_reason),
    desc_zh         = COALESCE($desc_zh, desc_zh),
    desc_en         = COALESCE($desc_en, desc_en),
    data_quality    = $data_quality,
    updated_at      = current_timestamp
WHERE norad_id = $norad_id
"""

INSERT_SQL = """
INSERT OR REPLACE INTO sat_background
    (norad_id, cospar_id, constellation, operator_org, mission_type,
     launch_site, launch_vehicle, orbit_type, mass_kg,
     maneuver_reason, desc_zh, desc_en, md_file, data_quality,
     created_at, updated_at)
VALUES
    ($norad_id, $cospar_id, $constellation, $operator_org, $mission_type,
     $launch_site, $launch_vehicle, $orbit_type, $mass_kg,
     $maneuver_reason, $desc_zh, $desc_en, $md_file, $data_quality,
     current_timestamp, current_timestamp)
"""


def main():
    parser = argparse.ArgumentParser(description="寫入衛星背景資料到 DuckDB sat_background")
    parser.add_argument("--dry-run", action="store_true", help="僅列印解析結果，不寫入資料庫")
    args = parser.parse_args()

    # 找出所有 .md 檔
    md_files = sorted(PROF_DIR.glob("*.md"))
    print(f"找到 {len(md_files)} 個 .md 檔案於 {PROF_DIR}")

    # 解析
    records = []
    skip_count = 0
    for md_path in md_files:
        rec = parse_md(md_path)
        if "norad_id" not in rec:
            print(f"  [WARN] 無法取得 NORAD ID，跳過：{md_path.name}")
            skip_count += 1
            continue
        records.append(rec)

    print(f"成功解析 {len(records)} 筆，跳過 {skip_count} 筆")

    if args.dry_run:
        print("\n=== DRY RUN 結果（前 10 筆）===")
        for r in records[:10]:
            print(f"  NORAD {r['norad_id']:6d} | "
                  f"mission={r.get('mission_type','?')[:30]:30s} | "
                  f"vehicle={str(r.get('launch_vehicle','?'))[:20]:20s} | "
                  f"mass={r.get('mass_kg','?')} | "
                  f"quality={r.get('data_quality','?')}")
        print(f"\n（省略後 {len(records)-10} 筆）")
        return

    # 寫入 DuckDB
    if not DB_PATH.exists():
        print(f"[ERROR] 資料庫不存在：{DB_PATH}")
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH), read_only=False)

    # 確認表格存在
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name='sat_background'"
    ).fetchall()
    if not tables:
        print("[ERROR] sat_background 表格不存在，請先執行 setup_sat_background.py")
        con.close()
        sys.exit(1)

    # 逐筆 upsert（先嘗試 UPDATE，若 norad_id 不存在則 INSERT）
    updated = 0
    inserted = 0
    for rec in records:
        norad_id = rec["norad_id"]

        # 檢查是否已存在
        exists = con.execute(
            "SELECT 1 FROM sat_background WHERE norad_id = ?", [norad_id]
        ).fetchone()

        if exists:
            # UPDATE：僅覆蓋非 None 欄位，保留已有的 cospar_id, launch_date 等
            con.execute(UPDATE_SQL, {
                "norad_id":       norad_id,
                "operator_org":   rec.get("operator_org"),
                "mission_type":   rec.get("mission_type"),
                "launch_vehicle": rec.get("launch_vehicle"),
                "mass_kg":        rec.get("mass_kg"),
                "maneuver_reason":rec.get("maneuver_reason"),
                "desc_zh":        rec.get("desc_zh"),
                "desc_en":        rec.get("desc_en"),
                "data_quality":   rec.get("data_quality", "researched"),
            })
            updated += 1
        else:
            # INSERT（新增不在 setup 裡的衛星）
            con.execute(INSERT_SQL, {
                "norad_id":       norad_id,
                "cospar_id":      rec.get("cospar_id"),
                "constellation":  rec.get("constellation"),
                "operator_org":   rec.get("operator_org"),
                "mission_type":   rec.get("mission_type"),
                "launch_site":    rec.get("launch_site"),
                "launch_vehicle": rec.get("launch_vehicle"),
                "orbit_type":     rec.get("orbit_type"),
                "mass_kg":        rec.get("mass_kg"),
                "maneuver_reason":rec.get("maneuver_reason"),
                "desc_zh":        rec.get("desc_zh"),
                "desc_en":        rec.get("desc_en"),
                "md_file":        rec.get("md_file"),
                "data_quality":   rec.get("data_quality", "researched"),
            })
            inserted += 1

    con.close()

    print(f"\n完成：UPDATE {updated} 筆，INSERT {inserted} 筆")
    print(f"資料庫路徑：{DB_PATH}")
    print("\n下一步：可執行 prc_maneuver/maneuver_browser.py 在瀏覽器中查看結果")


if __name__ == "__main__":
    main()
