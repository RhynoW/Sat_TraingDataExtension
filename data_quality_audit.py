#!/usr/bin/env python3
"""
data_quality_audit.py — TLE 資料品質稽核，逐筆賦予 quality_flag（good / suspect / rejected）
=============================================================================================
契約 M1 交付物「資料清洗 quality_flag」。動機：偵測前先分級資料可信度，避免壞資料
（TLE 缺口外推誤差、根數跳變、非物理值、極端 B*）在下游被誤判為機動（見期中報告 C.4
NORAD 44349 案例：TLE 缺口 134–163h → J2 外推放大 → 假機動）。

分級規則（逐 TLE，相對於前一筆）：
  rejected（不可用／corrupt，物理不可能）：
    - eccentricity∉[0,1)、sma_km≤R⊕（軌道在地表下）、inc∉[0,180]、關鍵欄位 NaN
    - TLE 行檢查碼錯誤（若提供 line1/line2）
  suspect（可用但存疑，需人工複核）：
    - 與前筆時間間隔 > GAP_SUSPECT_H（缺口 → J2/阻力外推誤差放大）
    - 單步 |Δi| > DI_STEP_SUSPECT 度（多為 TLE 誤差，真實變軌少如此劇烈）
    - |B*| > BSTAR_ABS_SUSPECT（極端阻力係數）
    - 與前筆 epoch 重複（redundant）
  good：以上皆未觸發。

用法：
  python data_quality_audit.py                 # 全庫稽核 → data/quality/tle_quality_*.csv + DuckDB 表
  python data_quality_audit.py --norad 44349   # 單顆列印
  from data_quality_audit import audit_tles     # 供 app 分頁呼叫
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

RE = 6378.137
# ── 門檻（可調）────────────────────────────────────────────────────────────────
GAP_SUSPECT_H = 48.0          # TLE 間隔 > 此 → suspect（對齊 app TLE_GAP_SUPPRESS_H）
DI_STEP_SUSPECT = 3.0         # 單步傾角變化（度）> 此 → suspect
BSTAR_ABS_SUSPECT = 1.0       # |B*| > 此 → suspect
SMA_MAX = 500_000.0           # sma 上限（km）合理性
FLAGS = ("good", "suspect", "rejected")


def _tle_checksum_ok(line: str) -> bool:
    """TLE 行檢查碼：各字元數字加總（'-'=1，其餘非數字=0）mod 10 == 末位。"""
    if not isinstance(line, str) or len(line) < 69:
        return True  # 無行資料 → 不判（視為通過）
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    try:
        return (s % 10) == int(line[68])
    except (ValueError, IndexError):
        return False


def audit_tles(df: pd.DataFrame) -> pd.DataFrame:
    """對單顆衛星的 TLE 序列逐筆稽核。

    df 需含 epoch, sma_km, inclination_deg, eccentricity；選用 raan_deg, bstar, line1, line2。
    回傳原 df + 欄位 quality_flag, quality_reason（分號分隔），依 epoch 排序。
    """
    d = df.sort_values("epoch").reset_index(drop=True).copy()
    # 先去除重複/近重複 epoch（≤60s，儲存冗餘非資料品質問題）；另計 n_dup。
    _dts = pd.to_datetime(d["epoch"], utc=True).diff().dt.total_seconds()
    _keep = _dts.isna() | (_dts >= 60.0)
    n_dup = int((~_keep).sum())
    d = d[_keep.to_numpy()].reset_index(drop=True)
    n = len(d)
    a = d["sma_km"].to_numpy(float)
    e = d["eccentricity"].to_numpy(float)
    inc = d["inclination_deg"].to_numpy(float)
    bstar = d["bstar"].to_numpy(float) if "bstar" in d.columns else np.full(n, np.nan)
    t = pd.to_datetime(d["epoch"], utc=True)
    dt_h = t.diff().dt.total_seconds().to_numpy() / 3600.0
    di = np.abs(np.diff(inc, prepend=inc[0]))
    has_lines = "line1" in d.columns and "line2" in d.columns

    flags, reasons = [], []
    for k in range(n):
        rs = []
        # ── rejected（物理不可能／corrupt）──
        if not np.isfinite(a[k]) or not np.isfinite(e[k]) or not np.isfinite(inc[k]):
            rs.append(("rejected", "nan_field"))
        if np.isfinite(e[k]) and (e[k] < 0 or e[k] >= 1.0):
            rs.append(("rejected", f"ecc={e[k]:.4f}"))
        if np.isfinite(a[k]) and (a[k] <= RE or a[k] > SMA_MAX):
            rs.append(("rejected", f"sma={a[k]:.0f}"))
        if np.isfinite(inc[k]) and (inc[k] < 0 or inc[k] > 180):
            rs.append(("rejected", f"inc={inc[k]:.2f}"))
        if has_lines and (not _tle_checksum_ok(d["line1"].iloc[k])
                          or not _tle_checksum_ok(d["line2"].iloc[k])):
            rs.append(("rejected", "checksum"))
        # ── suspect（存疑）──
        if k > 0 and np.isfinite(dt_h[k]) and dt_h[k] > GAP_SUSPECT_H:
            rs.append(("suspect", f"gap={dt_h[k]:.0f}h"))
        if k > 0 and di[k] > DI_STEP_SUSPECT:
            rs.append(("suspect", f"di={di[k]:.2f}deg"))
        if np.isfinite(bstar[k]) and abs(bstar[k]) > BSTAR_ABS_SUSPECT:
            rs.append(("suspect", f"bstar={bstar[k]:.2g}"))

        if any(f == "rejected" for f, _ in rs):
            flags.append("rejected")
        elif any(f == "suspect" for f, _ in rs):
            flags.append("suspect")
        else:
            flags.append("good")
        reasons.append(";".join(r for _, r in rs))
    d["quality_flag"] = flags
    d["quality_reason"] = reasons
    d.attrs["n_dup"] = n_dup
    return d


def summarize(audited: pd.DataFrame) -> dict:
    """回傳 {n, good, suspect, rejected, frac_good, top_reason}。"""
    vc = audited["quality_flag"].value_counts().to_dict()
    n = len(audited)
    reasons = [r.split("=")[0] for rr in audited["quality_reason"] for r in rr.split(";") if r]
    top = pd.Series(reasons).value_counts().head(3).to_dict() if reasons else {}
    return {"n": n, "good": vc.get("good", 0), "suspect": vc.get("suspect", 0),
            "rejected": vc.get("rejected", 0), "n_dup": int(audited.attrs.get("n_dup", 0)),
            "frac_good": round(vc.get("good", 0) / n, 4) if n else 0.0,
            "top_reason": top}


# ── 全庫稽核 ──────────────────────────────────────────────────────────────────
def audit_catalog(db: str, max_sats: int | None = None, min_tle: int = 3,
                  write_db: bool = True) -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(db, read_only=True)
    nids = [r[0] for r in con.execute(
        "SELECT norad_id FROM raw_tle_archive GROUP BY norad_id HAVING COUNT(*)>=? "
        "ORDER BY norad_id", [min_tle]).fetchall()]
    if max_sats:
        nids = nids[:max_sats]
    rows = []
    for k, nid in enumerate(nids):
        df = con.execute(
            "SELECT epoch_utc AS epoch, object_name, sma_km, inclination_deg, eccentricity, "
            "raan_deg, bstar FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc",
            [int(nid)]).fetchdf()
        if len(df) < min_tle:
            continue
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        s = summarize(audit_tles(df))
        rows.append({"norad_id": int(nid),
                     "object_name": str(df["object_name"].iloc[-1]).strip(),
                     "n_tle": s["n"], "good": s["good"], "suspect": s["suspect"],
                     "rejected": s["rejected"], "frac_good": s["frac_good"],
                     "top_reason": ";".join(f"{k2}:{v2}" for k2, v2 in s["top_reason"].items())})
        if (k + 1) % 500 == 0:
            print(f"  ...{k+1}/{len(nids)}", flush=True)
    con.close()
    out = pd.DataFrame(rows)

    out_dir = Path("data/quality"); out_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = out_dir / f"tle_quality_{tag}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"完成 → {path}  ({len(out)} 顆)")
    if write_db and not out.empty:
        try:
            con = duckdb.connect(db)
            con.execute("CREATE OR REPLACE TABLE tle_quality_flag AS SELECT * FROM out")
            con.close()
            print("  已寫入 DuckDB 表 tle_quality_flag")
        except Exception as ex:
            print(f"  DuckDB 寫入略過（可能被佔用）：{ex}")
    # 概況
    tot = out[["good", "suspect", "rejected"]].sum()
    g = int(tot.sum())
    if g:
        print(f"  全庫 TLE：good {tot['good']/g:.1%}  suspect {tot['suspect']/g:.1%}  "
              f"rejected {tot['rejected']/g:.1%}")
    return out


def main():
    ap = argparse.ArgumentParser(description="TLE 資料品質稽核 quality_flag")
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--norad", type=int, default=None, help="單顆列印（否則全庫）")
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--no-db", action="store_true", help="不寫入 DuckDB 表")
    args = ap.parse_args()

    if args.norad:
        import duckdb
        con = duckdb.connect(args.db, read_only=True)
        df = con.execute(
            "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg, bstar "
            "FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc", [args.norad]).fetchdf()
        con.close()
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        au = audit_tles(df)
        s = summarize(au)
        print(f"NORAD {args.norad}: {s}")
        bad = au[au["quality_flag"] != "good"]
        if not bad.empty:
            print(bad[["epoch", "sma_km", "inclination_deg", "quality_flag", "quality_reason"]]
                  .head(30).to_string(index=False))
    else:
        audit_catalog(args.db, max_sats=args.max_sats, write_db=not args.no_db)


if __name__ == "__main__":
    main()
