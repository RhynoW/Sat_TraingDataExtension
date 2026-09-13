#!/usr/bin/env python3
"""
IDS/ILRS maneuver-history parser  ->  normalised burn-level truth table.

Source : https://ids-doris.org/documents/BC/satellites/<sat>man.txt
Format : https://ids-doris.org/documents/BC/satellites/man.readme
Time    : TAI  (NOT UTC -- see TAI_UTC_OFFSET)

Whitespace-token parsing is used rather than the documented fixed columns:
the published column map assumes 232-char burn blocks but the actual stride
is 235 chars (the readme's own k=(i-1)*232 disagrees with its own field map,
which ends at 235). Token parsing is immune to that discrepancy.
"""
import sys, math, datetime as dt
from pathlib import Path

# TAI - UTC = 37 s since 2017-01-01; 36 s for 2015-07-01..2016-12-31.
def tai_utc_offset(year):
    return 36 if year <= 2016 else 37

# ---- component ordering by maneuver parameter type -------------------------
# 005 (SPOTs)            : T,R,L = pitch, roll, yaw   -> ATTITUDE frame, NOT RTN
# 006 (ENVISAT,CRYOSAT2) : radial, along-track, cross-track
# 007 (JASONs)           : Q,S,W = radial, along-track, cross-track
# HY-2A/2C/2D use 006 despite not appearing in the readme's type list.
TYPE_FRAME = {
    "005": ("pitch", "roll", "yaw"),          # not an RTN frame -- handle separately
    "006": ("radial", "along", "cross"),
    "007": ("radial", "along", "cross"),
}

def doy_to_dt(year, doy, hh, mm, ss=0.0):
    base = dt.datetime(year, 1, 1) + dt.timedelta(days=doy - 1, hours=hh, minutes=mm)
    return base + dt.timedelta(seconds=ss)

def parse_file(path):
    """Yield one dict per BURN (not per maneuver record)."""
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        t = line.split()
        if len(t) < 9:
            continue
        sat = t[0]
        # start / end of maneuver window
        y0, d0, h0, m0 = int(t[1]), int(t[2]), int(t[3]), int(t[4])
        y1, d1, h1, m1 = int(t[5]), int(t[6]), int(t[7]), int(t[8])
        win_start = doy_to_dt(y0, d0, h0, m0)
        win_end = doy_to_dt(y1, d1, h1, m1)
        # Window-only records (TOPEX, early SPOT): sat + start(4) + end(4) [+ptype]
        # with no burn/DV block. Yield one WINDOW-level truth (maneuver time known,
        # DV/da unknown) so the event still counts as detectable ground truth.
        if len(t) < 11:
            nan = float("nan")
            yield dict(
                sat=sat, ptype=(t[9] if len(t) > 9 else "win"),
                burn_idx=1, n_burns=0, window_only=True,
                win_start_tai=win_start, win_end_tai=win_end,
                epoch_tai=win_start,
                epoch_utc=win_start - dt.timedelta(seconds=tai_utc_offset(y0)),
                dur_s=nan, dv_radial=nan, dv_along=nan, dv_cross=nan, dv_mag=nan,
                acc_along_ums2=nan,
            )
            continue
        ptype = t[9]
        nburn = int(t[10])
        # nburn==0: record has a maneuver window but zero logged burns (seen in
        # ja2man.txt, e.g. 2019-10-03/04 entries) -- treat as window-only truth
        # (same handling as the <11-token short-record case) instead of silently
        # yielding nothing, which previously dropped 2 genuine Jason-2 maneuvers.
        if nburn == 0:
            nan = float("nan")
            yield dict(
                sat=sat, ptype=ptype,
                burn_idx=1, n_burns=0, window_only=True,
                win_start_tai=win_start, win_end_tai=win_end,
                epoch_tai=win_start,
                epoch_utc=win_start - dt.timedelta(seconds=tai_utc_offset(y0)),
                dur_s=nan, dv_radial=nan, dv_along=nan, dv_cross=nan, dv_mag=nan,
                acc_along_ums2=nan,
            )
            continue
        rest = t[11:]
        # each burn: YYYY DDD HH MM SS.sss dur dv1 dv2 dv3 a1 a2 a3 da1 da2 da3 = 15 tokens
        STRIDE = 15
        for i in range(nburn):
            b = rest[i * STRIDE:(i + 1) * STRIDE]
            if len(b) < STRIDE:
                print(f"  !! short burn block, {sat} {y0}/{d0} burn {i+1}", file=sys.stderr)
                continue
            by, bd, bh, bm = int(b[0]), int(b[1]), int(b[2]), int(b[3])
            bs = float(b[4])
            epoch_tai = doy_to_dt(by, bd, bh, bm, bs)
            epoch_utc = epoch_tai - dt.timedelta(seconds=tai_utc_offset(by))
            dur = float(b[5])
            dv = (float(b[6]), float(b[7]), float(b[8]))
            acc = (float(b[9]), float(b[10]), float(b[11]))
            yield dict(
                sat=sat, ptype=ptype, burn_idx=i + 1, n_burns=nburn,
                window_only=False,
                win_start_tai=win_start, win_end_tai=win_end,
                epoch_tai=epoch_tai, epoch_utc=epoch_utc,
                dur_s=dur,
                dv_radial=dv[0], dv_along=dv[1], dv_cross=dv[2],
                dv_mag=math.sqrt(sum(c * c for c in dv)),
                acc_along_ums2=acc[1],
            )

def selfcheck(recs):
    """acc(2) * duration should reproduce dv(2). Catches column/stride slips."""
    bad = 0
    for r in recs:
        pred = r["acc_along_ums2"] * 1e-6 * r["dur_s"]
        if abs(r["dv_along"]) > 1e-9:
            if abs(pred - r["dv_along"]) / abs(r["dv_along"]) > 0.02:
                bad += 1
    return bad

if __name__ == "__main__":
    for f in sys.argv[1:]:
        recs = list(parse_file(f))
        bad = selfcheck(recs)
        mans = len({(r["sat"], r["win_start_tai"]) for r in recs})
        print(f"{f}: {mans} maneuvers / {len(recs)} burns, "
              f"{recs[0]['epoch_utc'].date()} -> {recs[-1]['epoch_utc'].date()}, "
              f"self-check failures: {bad}")
