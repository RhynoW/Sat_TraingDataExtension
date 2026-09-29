"""全量重算阻力殘差（開關 off / on）寫到 scratchpad，不寫 data/drag（避免下游 glob 抓到新檔）。"""
import sys, time
sys.path.insert(0, r"F:\GitHub\Sat_TraingDataExtension")
import duckdb, numpy as np, pandas as pd
import atmospheric_drag as AD
from compare_tle_vs_ephemeris import load_registry
OUT = r"E:\Temp\claude\f--GitHub-Sat-TraingDataExtension\666ac0a1-2f05-45ff-8b73-24e11ec1019e\scratchpad\drag_full_compare.parquet"
sw = AD.load_space_weather()
reg = load_registry("data/url_registry.csv"); sats = [(v, k) for k, v in reg["sat_name"].items()]
con = duckdb.connect("space_db.duckdb", read_only=True)
rows = []; t0 = time.time()
for k, (name, nid) in enumerate(sats):
    df = con.execute("SELECT epoch_utc AS epoch, sma_km, eccentricity, line1, line2 FROM raw_tle_archive "
                     "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
    if len(df) < 5: continue
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    AD.STORM_AP_MODE = False; r0 = AD.drag_residual(df, sw)
    AD.STORM_AP_MODE = True;  r1 = AD.drag_residual(df, sw)
    if r0.empty: continue
    rows.append(pd.DataFrame({"norad_id": int(nid), "sat_name": name, "epoch": r0["epoch"],
                              "resid_off": r0["drag_resid_da"].to_numpy(), "resid_on": r1["drag_resid_da"].to_numpy(),
                              "alt_km": r0["alt_km"].to_numpy()}))
    if (k + 1) % 25 == 0: print(f"{k+1}/{len(sats)} {time.time()-t0:.0f}s", flush=True)
con.close()
out = pd.concat(rows); out.to_parquet(OUT); print("done", len(out), out.sat_name.nunique(), f"{time.time()-t0:.0f}s")
