"""發布 Rust 單機版的線上更新：衛星資料庫與執行檔 → HuggingFace dataset（預設 RhynoWu/Rust_SatDashboard）。

產出（repo 根目錄）：
  manifest.json            版本、大小、sha256、下載來源（sources 清單，之後可加 GitHub Releases 當第二來源）
  manifest.json.sig        ed25519 簽章（私鑰 %USERPROFILE%\\.satdashboard\\update_signing_key.pem，scripts/update_keygen.py 產生）
  db/space_db_slim.duckdb.zst
  exe/SatDashboard-x64.exe、exe/SatDashboard-arm64.exe
  README.md                dataset 說明
  MANUAL.md                操作手冊（scenario-advanced01/docs/SatDashboard_操作手冊_v*.md 最新一版）

內容沒變的檔案（sha256 與線上 manifest 相同）不重傳，沿用線上那份。預設上傳後壓縮 dataset 歷史（只留最新版）。

  python scripts/publish_hf.py                   # 資料庫 + 執行檔（先跑 scripts/build.ps1）
  python scripts/publish_hf.py --skip-exe        # 只發布資料庫（每日排程用）
  python scripts/publish_hf.py --local out\\hf    # 只輸出到資料夾，不上傳（本機測試：--update-manifest out\\hf\\manifest.json）
  python scripts/publish_hf.py --dry-run         # 只列出會做什麼
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zstandard
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parent / "scenario-advanced01" / "DB" / "space_db_slim.duckdb"
KEY = Path.home() / ".satdashboard" / "update_signing_key.pem"
PUB = ROOT / "src" / "update_pubkey.hex"
EXES = {"x86_64": "SatDashboard-x64.exe", "aarch64": "SatDashboard-arm64.exe"}
DB_NAME = "space_db_slim.duckdb"
MANUAL_DIR = ROOT.parent / "scenario-advanced01" / "docs"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def url_of(repo: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/main/{path}"


def remote_manifest(repo: str) -> dict | None:
    """線上 manifest（沿用沒有變更的 db／app 區塊）。必須通過 ed25519 驗章才採用（資安檢測 H-4）：
    否則取得 HF 寫入權限、但沒有私鑰的攻擊者可以竄改 manifest，再由本腳本以真私鑰重新簽章洗白。
    只有線上確實沒有 manifest（404，第一次發布）才回傳 None；網路錯誤、缺簽章或驗章失敗一律中止。"""
    import urllib.error
    import urllib.request
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    def get(path: str) -> bytes:
        with urllib.request.urlopen(url_of(repo, path), timeout=30) as r:
            return r.read()
    try:
        body = get("manifest.json")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit(f"無法取得線上 manifest（HTTP {e.code}），中止發布")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"無法取得線上 manifest：{e}，中止發布")
    try:
        sig = bytes.fromhex(get("manifest.json.sig").decode("ascii").strip())
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUB.read_text(encoding="ascii").strip())).verify(sig, body)
    except InvalidSignature:
        raise SystemExit("線上 manifest 簽章驗證失敗：可能遭竄改。請先檢查 HF dataset，不可沿用，中止發布")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"線上 manifest 簽章無法驗證（{e}），中止發布")
    return json.loads(body)


def latest_manual() -> Path | None:
    import re
    files = sorted(MANUAL_DIR.glob("SatDashboard_操作手冊_v*.md"),
                   key=lambda f: tuple(int(x) for x in re.findall(r"\d+", f.stem.split("_v")[-1])))
    return files[-1] if files else None


def exe_about(exe: Path) -> dict:
    out = subprocess.run([str(exe), "--version"], capture_output=True, timeout=60, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def native_exe(exe_dir: Path) -> Path:
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    return exe_dir / EXES[arch]


def signer():
    if not KEY.exists():
        raise SystemExit(f"找不到簽章私鑰 {KEY}（先執行 python scripts/update_keygen.py）")
    k = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    if pub != PUB.read_text(encoding="ascii").strip():
        raise SystemExit("私鑰與 src/update_pubkey.hex 不符：exe 會拒絕這份 manifest")
    return k


README = r"""---
license: other
pretty_name: ATRDC SatDashboard Rust 單機版
---

# ATRDC SatDashboard — Rust 單機版（Windows）

太空態勢儀表板的離線單機版：單一執行檔、不需安裝 Python，雙擊即可在瀏覽器開啟。

__LATEST__

📘 **操作手冊**：[MANUAL.md](https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/blob/main/MANUAL.md)（程式內也可從主選單「📘 操作手冊」開啟）

## 下載

- Intel／AMD 電腦：[SatDashboard-x64.exe](https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/resolve/main/exe/SatDashboard-x64.exe)
- ARM64（Snapdragon 等）電腦：[SatDashboard-arm64.exe](https://huggingface.co/datasets/RhynoWu/Rust_SatDashboard/resolve/main/exe/SatDashboard-arm64.exe)

> 如果您對於 EXE 檔案有疑慮，也可以用網頁開啟線上版：**https://rhynowu-atrdc-satdashboard-i18n.hf.space/**
> 不需下載安裝，直接在瀏覽器使用；「衛星任務規劃」（地面站過頂預報、雲量預報）目前只有單機版提供。

## 第一次使用

1. 把 exe 放進一個新資料夾，雙擊執行（Windows 若跳出 SmartScreen：「其他資訊」→「仍要執行」）。
2. 瀏覽器會自動開啟儀表板，程式同時**自動下載衛星資料庫**（約 237 MB）：主控台視窗每 10% 顯示一次進度，完成後頁面自動重新整理、衛星出現。下載期間頁面顯示 0 顆衛星是正常的。
3. 之後程式每 6 小時自動檢查新版資料庫與新版程式，有新版時右下角會出現「更新」按鈕。

下載時間取決於網速：一般家用網路約 1 分鐘內完成（約 237 MB，另加 5～10 秒驗證與解壓）。中斷時再按一次「更新」會從中斷處續傳。

### 資料庫存放位置

資料庫會放在 exe 所在資料夾底下的 `data\DB\space_db_slim.duckdb`，例如 exe 放在 `D:\SatDashboard\`：

```
D:\SatDashboard\
  SatDashboard-x64.exe
  data\
    DB\
      space_db_slim.duckdb        ← 資料庫（約 453 MB）
```

- 下載中會有暫存檔 `space_db_slim.duckdb.download.zst`（續傳用），完成後自動刪除。
- 之後每次更新，舊版改名為 `space_db_slim.duckdb.bak`（只保留上一版），`data\DB\` 最多約 900 MB。
- 不要放在 `C:\Program Files\` 等需要管理員權限的資料夾，否則資料庫寫不進去、程式也無法自我更新；放在桌面、文件或 D 槽的新資料夾即可。
- 搬移時整個資料夾一起搬（exe 啟動時會在自己旁邊找 `data\DB\`）。
- 要指定別的位置：`--db <檔案路徑>` 指定資料庫檔，或 `--data <資料夾>` 指定資料根目錄（資料庫在其下的 `DB\`）。
- 手動放資料庫也可以：放成 exe 旁的 `data\DB\space_db_slim.duckdb` 或 `DB\space_db_slim.duckdb` 都找得到。

### 自訂右下角 Logo（v0.1.5 起）

地球儀首頁右下角可以顯示您自己的單位 Logo：把圖檔命名為 `logo.png` 或 `logo.jpg`，放在 exe 同一個資料夾，重新整理頁面即可，不必重開程式。

```
D:\SatDashboard\
  SatDashboard-x64.exe
  logo.png                      ← 自訂 Logo（或 logo.jpg）
  data\
```

- 沒有這個檔案就不顯示 Logo，右下角只留版本列。
- 兩個都有時優先用 `logo.png`；建議用正方形、透明背景的 PNG（顯示區約 120×120 像素，會等比例縮放）。
- 要換 Logo 就直接覆蓋檔案，要拿掉就刪除檔案；程式自動更新時不會動到它。

## 功能

- 3D 地球儀：全目錄衛星即時位置、搜尋、近距離配對篩選、NORAD 監測
- 衛星任務規劃：地面站下行接收過頂預報（今天到未來 7 天）、夜間過頂過濾、地面軌跡左右各 5° 的 1° 網格雲量預報（MET Norway）
- 軌道要素歷史與雙星比較（/orbit）、2D 地面軌跡（/track）
- 台北覆蓋分析、RPO 相對接近 3D、全球海纜態勢、Himawari 氣象衛星最新全圓盤影像
- Starlink 分析、StoryMap 故事頁（v0.1.6 起）
- 會合與機動實驗室 /lab（v0.1.6 起；v0.1.7 起主選單「🧪 機動實驗室」直接進入）：批次會合分析與碰撞機率、場景 JSON、沿跡向避碰決策、RPO 接近控制模擬（HCW 設計、非線性重播、安全監控、撤離脈衝驗證）

## 檔案

- `manifest.json`：版本、大小、sha256、下載來源；`manifest.json.sig` 是 ed25519 簽章，程式驗證通過才會更新。
- `db/space_db_slim.duckdb.zst`：衛星資料庫（zstd 壓縮）。程式會自動下載；手動安裝時解壓到 exe 所在資料夾的 `data\DB\space_db_slim.duckdb`。
- `exe/`：單機版執行檔。

聯絡：[Rhyno Wu（LinkedIn）](https://www.linkedin.com/in/rhyno-wu-6b766771/)
"""


def render_readme(m: dict) -> str:
    """README 的「最新版」一行取自 manifest（每次發布自動更新）。"""
    app, db = m.get("app") or {}, m.get("db") or {}
    parts = []
    if app:
        parts.append(f"版本 **v{app['version']}**・日期 **{app['build_date']}**")
    if db:
        parts.append(f"衛星資料庫 {db['version'].replace('T', ' ').replace('Z', ' UTC')}")
    line = "**最新版**：" + "；".join(parts) if parts else ""
    return README.replace("__LATEST__", line)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="RhynoWu/Rust_SatDashboard")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--exe-dir", default=str(ROOT / "dist"))
    ap.add_argument("--skip-db", action="store_true")
    ap.add_argument("--skip-exe", action="store_true")
    ap.add_argument("--notes", default="", help="新版說明（顯示在程式的更新提示）")
    ap.add_argument("--local", help="只輸出到此資料夾（manifest 的下載網址改用相對路徑），不上傳")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-squash", action="store_true", help="不壓縮 dataset 歷史")
    ap.add_argument("--expires-days", type=int, default=30,
                    help="manifest 有效天數（1–90，預設 30）。客戶端拒絕過期的 manifest（防凍結攻擊）；每日 DB 排程會重簽延長")
    a = ap.parse_args()

    if not 1 <= a.expires_days <= 90:
        raise SystemExit("--expires-days 需介於 1–90（客戶端拒絕有效期超過 90 天的 manifest）")
    key = signer()
    old = None if a.local else remote_manifest(a.repo)
    now = datetime.now(timezone.utc)
    if old and old.get("generated"):
        # 複測 R-3：客戶端拒絕比上次接受的更舊的 manifest；線上那份若在未來（時鐘錯誤時誤簽），新發布會被所有客戶端拒絕
        prev = datetime.fromisoformat(str(old["generated"]).replace("Z", "+00:00"))
        if prev > now:
            raise SystemExit(f"線上 manifest 時間 {old['generated']} 晚於本機現在 {now:%Y-%m-%dT%H:%M:%SZ}：請先確認本機時鐘，"
                             "新 manifest 若早於它會被所有客戶端拒絕")
    stage = Path(a.local) if a.local else Path(tempfile.mkdtemp(prefix="satdash_hf_"))
    stage.mkdir(parents=True, exist_ok=True)
    src = (lambda p: p) if a.local else (lambda p: url_of(a.repo, p))
    uploads: list[str] = []
    manifest = {"schema": 1, "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "expires": (now + timedelta(days=a.expires_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "db": old.get("db") if old else None, "app": old.get("app") if old else None,
                "contact": "https://www.linkedin.com/in/rhyno-wu-6b766771/"}
    try:
        # ── 資料庫 ──
        if not a.skip_db:
            db = Path(a.db)
            if not db.is_file():
                raise SystemExit(f"找不到資料庫 {db}")
            raw_sha = sha256(db)
            version = datetime.fromtimestamp(db.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            if old and old.get("db") and old["db"]["sha256"] == raw_sha:
                print(f"資料庫沒有變更（{old['db']['version']}），不重傳")
            else:
                packed = stage / "db" / (DB_NAME + ".zst")
                packed.parent.mkdir(parents=True, exist_ok=True)
                print(f"壓縮資料庫 {db.stat().st_size / 1e6:.0f} MB（zstd 19）…")
                if not a.dry_run:
                    with open(db, "rb") as fi, open(packed, "wb") as fo:
                        zstandard.ZstdCompressor(level=19, threads=-1).copy_stream(fi, fo, size=db.stat().st_size)
                psize = packed.stat().st_size if packed.exists() else 0
                manifest["db"] = {"version": version, "file": DB_NAME, "size": db.stat().st_size, "sha256": raw_sha,
                                  "packed": {"format": "zstd", "size": psize, "sha256": sha256(packed) if psize else ""},
                                  "sources": [{"type": "hf", "url": src("db/" + DB_NAME + ".zst")}]}
                uploads.append("db/" + DB_NAME + ".zst")
                print(f"  資料庫版本 {version}：{db.stat().st_size / 1e6:.0f} MB → {psize / 1e6:.0f} MB")

        # ── 執行檔 ──
        if not a.skip_exe:
            exe_dir = Path(a.exe_dir)
            info = exe_about(native_exe(exe_dir))
            assets = {}
            for arch, name in EXES.items():
                p = exe_dir / name
                if not p.is_file():
                    raise SystemExit(f"找不到 {p}（先執行 scripts/build.ps1）")
                h = sha256(p)
                prev = (old or {}).get("app") or {}
                prev_asset = (prev.get("assets") or {}).get(arch)
                if prev_asset and prev_asset["sha256"] == h:
                    assets[arch] = prev_asset
                    print(f"{name} 沒有變更，不重傳")
                    continue
                (stage / "exe").mkdir(parents=True, exist_ok=True)
                if not a.dry_run:
                    shutil.copy2(p, stage / "exe" / name)
                assets[arch] = {"file": name, "size": p.stat().st_size, "sha256": h,
                                "sources": [{"type": "hf", "url": src("exe/" + name)}]}
                uploads.append("exe/" + name)
            manifest["app"] = {"version": info["version"], "build_date": info["build_date"],
                               "notes": a.notes, "assets": assets}
            print(f"程式版本 v{info['version']}（{info['build_date']}）")

        if not manifest["db"] and not manifest["app"]:
            raise SystemExit("沒有任何內容可發布")
        body = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
        (stage / "manifest.json").write_bytes(body)
        (stage / "manifest.json.sig").write_text(key.sign(body).hex() + "\n", encoding="ascii")
        (stage / "README.md").write_text(render_readme(manifest), encoding="utf-8")
        uploads += ["manifest.json", "manifest.json.sig", "README.md"]
        manual = latest_manual()
        if manual:
            shutil.copy2(manual, stage / "MANUAL.md")
            uploads.append("MANUAL.md")
            print(f"操作手冊：{manual.name}")
        print("檔案：", ", ".join(uploads))

        if a.local:
            print(f"已輸出到 {stage}；測試：SatDashboard.exe --update-manifest {stage / 'manifest.json'}")
            return 0
        if a.dry_run:
            print("--dry-run：沒有上傳")
            return 0

        from huggingface_hub import CommitOperationAdd, HfApi
        api = HfApi()
        api.create_repo(a.repo, repo_type="dataset", private=False, exist_ok=True)
        # manifest 放在同一個 commit：客戶端不會看到「manifest 已更新、檔案還沒到」的中間狀態
        ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=str(stage / p)) for p in uploads]
        info = api.create_commit(a.repo, repo_type="dataset", operations=ops,
                                 commit_message=f"update: db {manifest['db'] and manifest['db']['version']}, "
                                                f"app {manifest['app'] and manifest['app']['version']}")
        print("已上傳：", getattr(info, "commit_url", info))
        if not a.no_squash:
            api.super_squash_history(repo_id=a.repo, repo_type="dataset")
            print("已壓縮 dataset 歷史（只留最新版）")
        print("manifest：", url_of(a.repo, "manifest.json"))
        return 0
    finally:
        if not a.local:
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
