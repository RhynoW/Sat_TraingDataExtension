#!/usr/bin/env python3
"""
Build the second hold-out truth set from IDS/ILRS maneuver histories.

Usage:
    python ids_build_truth.py --fetch          # download all man files
    python ids_build_truth.py --build          # parse -> ids_truth.csv + ids_quiet.csv

Outputs
-------
ids_truth.csv : one row per BURN, with the report's own detectability model applied
                (da_km, da_sigma, severity, tle_visible) so the evaluation can be
                stratified by "physically detectable" vs "physically invisible".
ids_quiet.csv : certified-quiet intervals -- the gaps between operator-logged
                maneuvers. This is the FPR test set (see notes in the .md).

IMPORTANT: IDS timestamps are TAI. Space-Track TLE epochs are UTC.
           TAI - UTC = 37 s (since 2017-01-01). Getting this wrong puts every
           truth epoch 37 s off, which matters at the burn-arc level.
"""
import argparse, csv, math, sys, datetime as dt
from pathlib import Path
from ids_man_parse import parse_file

BASE = "https://ids-doris.org/documents/BC/satellites/"

# ---------------------------------------------------------------------------
# Satellite registry.
#   a_km        : semi-major axis (km)
#   norad       : *** UNVERIFIED -- see notes. Confirm against Space-Track satcat
#                 before joining to the TLE database. ***
#   ptype       : maneuver-parameter type actually observed in the file
# ---------------------------------------------------------------------------
REGISTRY = {
    # file          ids_id    name                 a_km     norad?  status
    "ja1man.txt": ("JASO1", "Jason-1",            7714.4,  26997, "retired 2013"),
    "ja2man.txt": ("JASO2", "Jason-2",            7714.4,  33105, "retired 2019"),
    "ja3man.txt": ("JASO3", "Jason-3",            7714.4,  41240, "active"),
    "s6aman.txt": ("SEN6A", "Sentinel-6A",        7714.4,  46984, "active"),
    "s6bman.txt": ("SEN6B", "Sentinel-6B",        7714.4,  None,  "active"),
    "topman.txt": ("TOPEX", "TOPEX/Poseidon",     7714.4,  22076, "retired 2006"),
    "cs2man.txt": ("CRYO2", "CryoSat-2",          7096.0,  36508, "active"),
    "en1man.txt": ("ENVI1", "Envisat",            7159.5,  27386, "dead 2012, in orbit"),
    "s3aman.txt": ("SEN3A", "Sentinel-3A",        7186.0,  41335, "active"),
    "s3bman.txt": ("SEN3B", "Sentinel-3B",        7186.0,  43437, "active"),
    "srlman.txt": ("SARAL", "SARAL/AltiKa",       7159.5,  39086, "active"),
    "swoman.txt": ("SWOT1", "SWOT",               7268.0,  54754, "active"),   # 驗證: 55160 實為 OneWeb-0619
    "h2aman.txt": ("HY-2A", "HY-2A  (海洋二号A)",  7349.0,  37781, "China"),
    "h2cman.txt": ("HY-2C", "HY-2C  (海洋二号C)",  7335.0,  46469, "China"),
    "h2dman.txt": ("HY-2D", "HY-2D  (海洋二号D)",  7335.0,  48621, "China"),   # 驗證: 49206 實為 OneWeb-0340
    "sp2man.txt": ("SPOT2", "SPOT-2",             7200.0,  20436, "retired; type 005"),
    "sp3man.txt": ("SPOT3", "SPOT-3",             7200.0,  22823, "retired; type 005"),
    "sp4man.txt": ("SPOT4", "SPOT-4",             7200.0,  25260, "retired; type 005"),
    "sp5man.txt": ("SPOT5", "SPOT-5",             7200.0,  27421, "retired; type 005"),
}

MU = 398600.4418

# Report Table 11 -- sma noise sigma by altitude band.
# NOTE: the report's ">700 km" band is open-ended and was calibrated on data
# no higher than ~800 km (FORMOSAT-3 at 789 km). Jason-class targets sit at
# 1336 km, i.e. well outside the calibrated range. sigma there is probably
# SMALLER than 0.05 km. Treat 0.05 as a conservative upper bound and re-fit
# per-satellite from the actual TLE series before drawing conclusions.
def sigma_km(alt_km):
    if alt_km < 450: return 0.15
    if alt_km < 700: return 0.08
    return 0.05

def fetch():
    """Download the IDS maneuver files. Run this yourself -- see .md notes."""
    import urllib.request
    out = Path("ids_raw"); out.mkdir(exist_ok=True)
    for fn in REGISTRY:
        url = BASE + fn
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            (out / fn).write_bytes(data)
            print(f"  ok   {fn}  {len(data):,} bytes")
        except Exception as e:
            print(f"  FAIL {fn}: {e}", file=sys.stderr)

def severity(da):
    da = abs(da)
    if da >= 10: return "large"
    if da >= 5:  return "medium"
    if da >= 1:  return "small"
    return "below-small"

def build(src_dir="ids_raw"):
    src = Path(src_dir)
    truth_rows, quiet_rows = [], []
    for fn, (ids_id, name, a, norad, status) in REGISTRY.items():
        p = src / fn
        if not p.exists():
            p = Path(fn)                       # allow files in cwd
            if not p.exists():
                print(f"  skip {fn} (not found)"); continue
        n = math.sqrt(MU / a**3)
        v = math.sqrt(MU / a)
        alt = a - 6378.137
        sig = sigma_km(alt)
        try:
            burns = list(parse_file(p))
        except Exception as e:
            print(f"  skip {fn} (parse error: {type(e).__name__}: {e})")
            continue
        if not burns:
            continue
        # SPOT (type 005) DV components are attitude angles (pitch/roll/yaw),
        # NOT an RTN frame -- da = 2*dv_along/n is meaningless. Exclude until a
        # coordinate transform is implemented (see .md sec 2).
        if burns[0]["ptype"] == "005":
            print(f"  skip {fn} (type 005 = attitude frame, not RTN)")
            continue
        for b in burns:
            wonly = b.get("window_only", False)
            if wonly:
                # 窗級真值：只有機動時窗，無 ΔV/da（如 TOPEX）
                truth_rows.append(dict(
                    ids_id=ids_id, name=name, norad=norad or "", status=status,
                    ptype=b["ptype"],
                    epoch_utc=b["epoch_utc"].isoformat(timespec="milliseconds"),
                    epoch_tai=b["epoch_tai"].isoformat(timespec="milliseconds"),
                    win_start_tai=b["win_start_tai"].isoformat(),
                    win_end_tai=b["win_end_tai"].isoformat(),
                    burn_idx=b["burn_idx"], n_burns=b["n_burns"],
                    dur_s="", dv_radial="", dv_along="", dv_cross="", dv_mag="",
                    da_km="", di_deg="", da_sigma="", sigma_km=sig,
                    severity="window-only", tle_visible_50="", incl_flag="",
                ))
                continue
            da = 2.0 * (b["dv_along"] / 1000.0) / n
            di = math.degrees((b["dv_cross"] / 1000.0) / v)
            truth_rows.append(dict(
                ids_id=ids_id, name=name, norad=norad or "", status=status,
                ptype=b["ptype"],
                epoch_utc=b["epoch_utc"].isoformat(timespec="milliseconds"),
                epoch_tai=b["epoch_tai"].isoformat(timespec="milliseconds"),
                win_start_tai=b["win_start_tai"].isoformat(),
                win_end_tai=b["win_end_tai"].isoformat(),
                burn_idx=b["burn_idx"], n_burns=b["n_burns"],
                dur_s=f'{b["dur_s"]:.3f}',
                dv_radial=f'{b["dv_radial"]:.6f}', dv_along=f'{b["dv_along"]:.6f}',
                dv_cross=f'{b["dv_cross"]:.6f}',  dv_mag=f'{b["dv_mag"]:.6f}',
                da_km=f"{da:.6f}", di_deg=f"{di:.6f}",
                da_sigma=f"{abs(da)/sig:.2f}", sigma_km=sig,
                severity=severity(da),
                tle_visible_50=int(abs(da) >= 0.2),   # report Table 11, >700 km band
                incl_flag=int(abs(di) >= 0.02),       # report Sec 2.1 threshold
            ))
        # certified-quiet gaps: between end of one maneuver window and start of next
        wins = sorted({(b["win_start_tai"], b["win_end_tai"]) for b in burns})
        for (s0, e0), (s1, e1) in zip(wins, wins[1:]):
            gap_h = (s1 - e0).total_seconds() / 3600.0
            if gap_h > 48:                     # keep only usefully long quiet runs
                quiet_rows.append(dict(
                    ids_id=ids_id, name=name, norad=norad or "",
                    quiet_start_tai=e0.isoformat(), quiet_end_tai=s1.isoformat(),
                    quiet_hours=f"{gap_h:.1f}",
                ))

    for rows, fname in ((truth_rows, "ids_truth.csv"), (quiet_rows, "ids_quiet.csv")):
        if not rows: continue
        with open(fname, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f"wrote {fname}: {len(rows)} rows")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--src", default="ids_raw")
    a = ap.parse_args()
    if a.fetch: fetch()
    if a.build: build(a.src)
    if not (a.fetch or a.build): ap.print_help()
