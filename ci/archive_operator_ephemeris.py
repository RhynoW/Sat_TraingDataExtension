#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archive_operator_ephemeris.py — 每日存檔營運方星曆衍生資料（OneWeb、Amazon Kuiper）。

來源：
  1. CelesTrak 補充軌道資料（SupGP，免帳號）：FILE=oneweb、kuiper（JSON／OMM 格式）。
     CelesTrak 以營運方星曆擬合為 SGP4 根數；只提供最新一份，無歷史檔，故須每日存檔才能累積。
     存於 data/operator_ephemeris/supgp/<file>/<file>_<UTC 日期>.json.gz（同日重跑則覆寫）。
  2. Space-Track「Public Files」：Amazon Kuiper 目錄（public-data-files-24206-kuiper-prod）。
     目錄目前常為空；有檔案時下載（已存在則跳過），存於 data/operator_ephemeris/spacetrack_public/<目錄>/。
     帳號沿用 .env 之 SPACE_TRACK_IDENTITY／SPACE_TRACK_PASSWORD（與每日 TLE 下載相同）。

每個來源獨立處理，單一來源失敗不影響其他來源；任一來源失敗時結束碼為 1（批次檔僅發出警告）。
用法：python ci/archive_operator_ephemeris.py [--dry-run]
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "operator_ephemeris"
SUPGP_URL = "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php"
SUPGP_FILES = ("oneweb", "kuiper")
ST = "https://www.space-track.org"
ST_DIRS = ("public-data-files-24206-kuiper-prod",)
UA = {"User-Agent": "orbit-research-client"}


def archive_supgp(name: str, dry: bool) -> str:
    r = requests.get(SUPGP_URL, params={"FILE": name, "FORMAT": "json"}, headers=UA, timeout=120)
    if r.status_code == 403:
        # CelesTrak 對短時間內重複下載同一資料檔回 403（約 2 小時內）；每日排程僅下載一次不會觸發
        raise RuntimeError(f"CelesTrak 回 403（短時間內重複下載被限制），請 2 小時後重跑")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise ValueError(f"SupGP {name}：回應不是非空 JSON 陣列")
    epochs = sorted(d.get("EPOCH", "") for d in data)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = OUT / "supgp" / name / f"{name}_{day}.json.gz"
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return f"SupGP {name}：{len(data)} 筆、{len({d.get('NORAD_CAT_ID') for d in data})} 顆、曆元 {epochs[0]} ～ {epochs[-1]} → {path.relative_to(ROOT)}"


def archive_spacetrack(dry: bool) -> list[str]:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    ident, pw = os.getenv("SPACE_TRACK_IDENTITY"), os.getenv("SPACE_TRACK_PASSWORD")
    if not ident or not pw:
        raise RuntimeError("缺 SPACE_TRACK_IDENTITY／SPACE_TRACK_PASSWORD")
    msgs = []
    with requests.Session() as s:
        s.post(f"{ST}/ajaxauth/login", data={"identity": ident, "password": pw}, timeout=60).raise_for_status()
        try:
            files = s.get(f"{ST}/publicfiles/query/class/files", timeout=120).json()
            for d in ST_DIRS:
                names = files.get(d) or []
                if not names:
                    msgs.append(f"Space-Track {d}：目前無檔案")
                    continue
                n_new = 0
                for name in names:
                    path = OUT / "spacetrack_public" / d / name.replace(":", "")
                    if path.exists() and path.stat().st_size > 0:
                        continue
                    if not dry:
                        r = s.get(f"{ST}/publicfiles/query/class/download", params={"name": name}, timeout=300)
                        r.raise_for_status()
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(r.content)
                    n_new += 1
                msgs.append(f"Space-Track {d}：{len(names)} 個檔案，新下載 {n_new} 個")
        finally:
            s.get(f"{ST}/ajaxauth/logout", timeout=30)
    return msgs


def main() -> int:
    dry = "--dry-run" in sys.argv
    ok = True
    for name in SUPGP_FILES:
        try:
            print("[OK]", archive_supgp(name, dry))
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[FAIL] SupGP {name}：{type(e).__name__}: {e}")
    try:
        for m in archive_spacetrack(dry):
            print("[OK]", m)
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[FAIL] Space-Track Public Files：{type(e).__name__}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
