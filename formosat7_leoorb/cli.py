"""福衛七號 leoOrb 管線的命令列入口。

用法::

    python -m formosat7_leoorb.cli download --start 2026.223 --end 2026.229
    python -m formosat7_leoorb.cli overlap  --start 2026.223 --end 2026.229
    python -m formosat7_leoorb.cli compare  --start 2026.223 --end 2026.229 \\
        --db space_db.duckdb --out output/formosat7

日期可寫 'YYYY.DDD'（年積日）或 'YYYY-MM-DD'。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger("formosat7_leoorb")


def _as_day_tag(s: str) -> str:
    from .download import day_tag
    if "-" in s:
        y, m, d = (int(x) for x in s.split("-"))
        return day_tag(date(y, m, d))
    return day_tag(s)


def _collect(start: str, end: str, cache_dir: Path | None, force: bool):
    """下載區間並解析成單一長表。"""
    from . import archive, download
    paths = download.download_range(_as_day_tag(start), _as_day_tag(end),
                                    dest_dir=cache_dir, force=force)
    if not paths:
        raise SystemExit("區間內沒有取得任何每日包")
    return pd.concat([archive.load_leoorb_tar(p) for p in paths], ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="formosat7_leoorb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["download", "overlap", "compare"])
    ap.add_argument("--start", required=True, help="起日 YYYY.DDD 或 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="迄日（含）")
    ap.add_argument("--cache-dir", type=Path, default=None, help="每日包快取目錄")
    ap.add_argument("--force", action="store_true", help="忽略快取重新下載")
    ap.add_argument("--db", default="space_db.duckdb", help="TLE 來源 DuckDB（compare 用）")
    ap.add_argument("--step-min", type=int, default=5, help="真值抽稀間隔（分鐘）")
    ap.add_argument("--out", type=Path, default=None, help="輸出目錄（寫 CSV）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    if args.command == "download":
        from .download import day_tags_between, download_range
        paths = download_range(_as_day_tag(args.start), _as_day_tag(args.end),
                               dest_dir=args.cache_dir, force=args.force)
        want = len(list(day_tags_between(_as_day_tag(args.start), _as_day_tag(args.end))))
        print("取得 %d / %d 天" % (len(paths), want))
        return 0

    df = _collect(args.start, args.end, args.cache_dir, args.force)

    if args.command == "overlap":
        from .merge import overlap_summary
        s = overlap_summary(df)
        print(s.to_string())
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            s.to_csv(args.out / "overlap_summary.csv")
        return 0

    # compare
    from .compare import compare, load_tles, summary_by_age, summary_by_satellite
    from .merge import merge_arcs, resample

    truth = resample(merge_arcs(df), args.step_min)
    lo = truth["epoch"].min() - pd.Timedelta(3, "D")   # 關鍵字形式在 numpy 2.5 下已 deprecated
    tles = load_tles(args.db, start=str(lo), end=str(truth["epoch"].max()))
    res = compare(truth, tles)

    by_sat = summary_by_satellite(res)
    by_age = summary_by_age(res)
    print("真值點 %d、殘差點 %d、齡期中位 %.1f h、最長 %.1f h"
          % (len(truth), len(res), res.age_h.median(), res.age_h.max()))
    print()
    print("== 逐星 (km) ==")
    print(by_sat.to_string())
    print()
    print("== 依 TLE 齡期 (km) ==")
    print(by_age.to_string())

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        res.to_csv(args.out / "residuals.csv", index=False)
        by_sat.to_csv(args.out / "summary_by_satellite.csv")
        by_age.to_csv(args.out / "summary_by_age.csv")
        print("已寫入 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
