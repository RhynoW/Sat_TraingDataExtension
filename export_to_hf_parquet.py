#!/usr/bin/env python3
"""
export_to_hf_parquet.py — 將 space_db.duckdb 匯出為分割 Parquet，供上傳 HuggingFace Dataset。
=====================================================
用途（配合 maneuver_app_2026September.py 的遠端模式）：
  * 把 14GB 的 space_db.duckdb 各表匯出成 zstd 壓縮 Parquet（大表全域排序，利於遠端點查裁剪）。
  * 產生小的 catalog.parquet（norad_id / name / n / first / last），讓 App 免全表 GROUP BY。
  * （可選）建立輕量 stub DuckDB（space_hf.duckdb）內含指向 hf://datasets/<repo>/... 的 VIEW。
  * 印出各檔壓縮大小與 `hf upload` 指令。

範例：
  # 只匯出 App 需要的核心表（raw_tle_archive + catalog + 小型 metadata）
  python export_to_hf_parquet.py --out hf_export --core-only

  # 匯出整庫所有非空表，並順便建立指向 <repo> 的 stub 供本機測試
  python export_to_hf_parquet.py --out hf_export --repo rhynowu/starlink-maneuver-db

之後上傳（需先 `pip install -U "huggingface_hub[hf_transfer]"` 並 `hf auth login`）：
  export HF_HUB_ENABLE_HF_TRANSFER=1
  hf upload-large-folder <帳號>/<repo> hf_export --repo-type=dataset
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import duckdb

# App 遠端模式實際會用到的表（--core-only 時只匯這些）
CORE_TABLES = ["raw_tle_archive", "sat_n2yo_metadata", "maneuver_labels",
               "conjunction_events", "training_samples", "training_samples_plan_b"]

# 依序偵測可用的「時間欄」，用於排序與（大表）年份分割
EPOCH_CANDIDATES = ["epoch_utc", "tle_epoch", "date_tag", "center_epoch",
                    "epoch", "tca_utc", "coarse_hit_time_utc", "load_time"]

# 超過此列數且有時間欄 → 依 year 分割成多檔（避免單檔過大）
PARTITION_ROW_THRESHOLD = 25_000_000


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def list_tables(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name").fetchall()]


def table_cols(con, t: str) -> list[str]:
    return [r[0] for r in con.execute(f'DESCRIBE "{t}"').fetchall()]


def pick_epoch(cols: list[str]) -> str | None:
    for c in EPOCH_CANDIDATES:
        if c in cols:
            return c
    return None


def export_table(con, t: str, out: Path, zstd_level: int, row_group: int) -> Path:
    """匯出單表為 Parquet。大表依 year 分割並全域排序；否則單檔排序。回傳輸出路徑。"""
    cols = table_cols(con, t)
    n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    if n == 0:
        print(f"  [skip] {t}: 0 列")
        return None

    epoch = pick_epoch(cols)
    has_norad = "norad_id" in cols
    order_parts = ([f'"norad_id"'] if has_norad else []) + ([f'"{epoch}"'] if epoch else [])
    order_by = f"ORDER BY {', '.join(order_parts)}" if order_parts else ""

    tdir = out / t
    tdir.mkdir(parents=True, exist_ok=True)
    copts = (f"FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {zstd_level}, "
             f"ROW_GROUP_SIZE {row_group}")

    big = n > PARTITION_ROW_THRESHOLD and epoch is not None
    if big:
        # 依 year 分割：加一個 year 分割欄（App 以具名欄查詢，忽略多出來的 year）
        sql = (f'COPY (SELECT *, CAST(year("{epoch}") AS INT) AS year '
               f'FROM "{t}" {order_by}) '
               f"TO '{tdir.as_posix()}' ({copts}, PARTITION_BY (year), OVERWRITE_OR_IGNORE)")
        con.execute(sql)
        print(f"  [ok]  {t}: {n:,} 列 → 依 year 分割（{human(dir_size(tdir))}）")
        return tdir
    else:
        fpath = tdir / "data.parquet"
        sql = f'COPY (SELECT * FROM "{t}" {order_by}) TO \'{fpath.as_posix()}\' ({copts})'
        con.execute(sql)
        print(f"  [ok]  {t}: {n:,} 列 → 單檔（{human(dir_size(fpath))}）")
        return fpath


def export_catalog(con, out: Path, zstd_level: int) -> Path:
    """由 raw_tle_archive 彙整小型 catalog（App load_catalog 直接讀，免全表 GROUP BY）。"""
    fpath = out / "catalog.parquet"
    con.execute(f"""
        COPY (
          SELECT norad_id,
                 ANY_VALUE(object_name)      AS name,
                 COUNT(*)                     AS n,
                 MIN(epoch_utc)               AS first_epoch,
                 MAX(epoch_utc)               AS last_epoch
          FROM raw_tle_archive
          GROUP BY norad_id
          ORDER BY norad_id
        ) TO '{fpath.as_posix()}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {zstd_level})
    """)
    print(f"  [ok]  catalog.parquet（{human(fpath.stat().st_size)}）")
    return fpath


def build_stub(stub_path: Path, repo: str, tables: list[str]) -> None:
    """建立指向 hf://datasets/<repo> 的 stub DuckDB（本機測試遠端模式用）。"""
    base = f"hf://datasets/{repo}"
    con = duckdb.connect(str(stub_path))
    con.execute("INSTALL httpfs"); con.execute("LOAD httpfs")
    views = {t: f"{t}/**/*.parquet" for t in tables}
    views["catalog"] = "catalog.parquet"
    for v, rel in views.items():
        con.execute(f"CREATE OR REPLACE VIEW {v} AS "
                    f"SELECT * FROM read_parquet('{base}/{rel}', union_by_name=true)")
    con.close()
    print(f"  [ok]  stub DuckDB → {stub_path}（views: {', '.join(views)}）")


def write_dataset_readme(out: Path, tables: list[str]) -> None:
    (out / "README.md").write_text(textwrap.dedent(f"""\
        ---
        license: cc-by-4.0
        tags:
          - space-situational-awareness
          - satellite
          - tle
          - orbital-maneuver
        ---

        # Starlink / LEO 機動偵測資料集（由 space_db.duckdb 匯出）

        Parquet（zstd 壓縮）。大表依 `year` Hive 分割並全域排序（`norad_id`, epoch），
        方便以 DuckDB httpfs 遠端點查（`WHERE norad_id=?` 靠 row-group 統計裁剪）。

        ## 內容
        {chr(10).join(f'- `{t}/`' for t in tables)}
        - `catalog.parquet` — 每顆衛星彙整（norad_id / name / n / first_epoch / last_epoch）

        ## DuckDB 遠端直查範例
        ```python
        import duckdb
        duckdb.sql("INSTALL httpfs; LOAD httpfs;")
        duckdb.sql(\"\"\"
          SELECT * FROM 'hf://datasets/<repo>/raw_tle_archive/**/*.parquet'
          WHERE norad_id = 44713 ORDER BY epoch_utc
        \"\"\")
        ```

        > 注意：原始 TLE 來源條款（Space-Track / CelesTrak 等）請自行確認再散布範圍。
        """), encoding="utf-8")
    print("  [ok]  README.md（dataset card）")


def main() -> None:
    ap = argparse.ArgumentParser(description="匯出 DuckDB → 分割 Parquet（供 HuggingFace Dataset）")
    ap.add_argument("--db", default="space_db.duckdb", help="來源 DuckDB（預設 space_db.duckdb）")
    ap.add_argument("--out", default="hf_export", help="輸出目錄（預設 hf_export）")
    ap.add_argument("--tables", default="", help="逗號分隔的表清單（預設：全部非空表）")
    ap.add_argument("--core-only", action="store_true",
                    help="只匯出 App 遠端模式需要的核心表")
    ap.add_argument("--zstd-level", type=int, default=9, help="zstd 壓縮等級（預設 9）")
    ap.add_argument("--row-group", type=int, default=122880, help="ROW_GROUP_SIZE（預設 122880）")
    ap.add_argument("--repo", default="", help="（可選）HF repo id → 一併建立 stub DuckDB")
    ap.add_argument("--stub", default="space_hf.duckdb", help="stub DuckDB 輸出路徑")
    args = ap.parse_args()

    dbp = Path(args.db)
    if not dbp.exists():
        raise SystemExit(f"找不到 DuckDB：{dbp}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(dbp), read_only=True)
    con.execute(f"PRAGMA threads={max(1, (__import__('os').cpu_count() or 4))}")
    all_tables = list_tables(con)

    if args.tables:
        want = [t.strip() for t in args.tables.split(",") if t.strip()]
    elif args.core_only:
        want = [t for t in CORE_TABLES if t in all_tables]
    else:
        want = all_tables
    missing = [t for t in want if t not in all_tables]
    if missing:
        raise SystemExit(f"下列表不存在：{missing}")

    print(f"來源：{dbp}（{human(dbp.stat().st_size)}）")
    print(f"輸出：{out.resolve()}")
    print(f"匯出表（{len(want)}）：{', '.join(want)}\n")

    exported: list[str] = []
    for t in want:
        p = export_table(con, t, out, args.zstd_level, args.row_group)
        if p is not None:
            exported.append(t)

    print("\n產生 catalog（由 raw_tle_archive 彙整）…")
    if "raw_tle_archive" in all_tables:
        export_catalog(con, out, args.zstd_level)
    else:
        print("  [warn] 無 raw_tle_archive → 略過 catalog")

    write_dataset_readme(out, exported)
    con.close()

    if args.repo:
        print("\n建立 stub DuckDB…")
        build_stub(Path(args.stub), args.repo, exported)

    total = dir_size(out)
    print("\n" + "=" * 60)
    print(f"完成。輸出總大小：{human(total)}（原庫 {human(dbp.stat().st_size)}）")
    repo_disp = args.repo or "<帳號>/<repo>"
    print(textwrap.dedent(f"""\
        ─ 上傳步驟 ─────────────────────────────────────────────
          pip install -U "huggingface_hub[hf_transfer]"
          hf auth login
          export HF_HUB_ENABLE_HF_TRANSFER=1        # (PowerShell: $env:HF_HUB_ENABLE_HF_TRANSFER=1)
          hf upload-large-folder {repo_disp} {out.as_posix()} --repo-type=dataset --private
        ─ 啟動 App（遠端模式）─────────────────────────────────
          set  HF_DATASET_REPO={repo_disp}          # (PowerShell: $env:HF_DATASET_REPO='{repo_disp}')
          streamlit run maneuver_app_2026September.py
        ────────────────────────────────────────────────────────"""))


if __name__ == "__main__":
    main()
