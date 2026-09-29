import sys, importlib.util, numpy as np, pandas as pd, duckdb
sys.path.insert(0, r"F:\GitHub\Sat_TraingDataExtension")
import atmospheric_drag as NEW
spec = importlib.util.spec_from_file_location("OLD", r"E:\Temp\claude\f--GitHub-Sat-TraingDataExtension\666ac0a1-2f05-45ff-8b73-24e11ec1019e\scratchpad\atmospheric_drag.before.py")
OLD = importlib.util.module_from_spec(spec); spec.loader.exec_module(OLD)
sw = NEW.load_space_weather(); OLD._sw_cache = sw
con = duckdb.connect("space_db.duckdb", read_only=True)
cases = [(29052,"FORMOSAT-3A","2024-01-01","2024-12-31"),(25544,"ISS","2024-04-01","2024-06-30"),
         (47122,"STARLINK-1777","2026-06-01","2026-09-28"),(44772,"STARLINK-1068","2026-06-01","2026-09-28"),
         (49176,"STARLINK-3069","2026-06-01","2026-09-28")]
rows=[]
for nid,lbl,a,b in cases:
    df = con.execute("SELECT epoch_utc AS epoch, sma_km, eccentricity, line1, line2 FROM raw_tle_archive "
                     "WHERE norad_id=? AND sma_km IS NOT NULL AND epoch_utc BETWEEN ? AND ? ORDER BY epoch_utc",[nid,a,b]).fetchdf()
    df["epoch"]=pd.to_datetime(df["epoch"],utc=True)
    ro = OLD.drag_residual(df, sw)
    NEW.STORM_AP_MODE=False; rf = NEW.drag_residual(df, sw)
    NEW.STORM_AP_MODE=True;  rn = NEW.drag_residual(df, sw)
    same = np.allclose(ro["drag_resid_da"], rf["drag_resid_da"], rtol=1e-9, atol=1e-12)
    ratio = rf.attrs["B_eff"]/ro.attrs["B_eff"]
    d = (rn["drag_resid_da"]-ro["drag_resid_da"]).abs()
    storm = rn["epoch"].between(pd.Timestamp("2024-05-10",tz="UTC"),pd.Timestamp("2024-05-14",tz="UTC"))
    rows.append(dict(sat=lbl,n=len(rn),old_eq_newoff=same,Beff_ratio=round(ratio,4),
        rms_old_m=round(1000*np.sqrt((ro.drag_resid_da**2).mean()),1),rms_new_m=round(1000*np.sqrt((rn.drag_resid_da**2).mean()),1),
        max_abs_old_km=round(ro.drag_resid_da.abs().max(),3),max_abs_new_km=round(rn.drag_resid_da.abs().max(),3),
        max_change_m=round(1000*d.max(),1),
        n_gt03_old=int((ro.drag_resid_da.abs()>0.3).sum()),n_gt03_new=int((rn.drag_resid_da.abs()>0.3).sum()),
        gannon_rms_old_m=round(1000*np.sqrt((ro.drag_resid_da[storm]**2).mean()),1) if storm.any() else None,
        gannon_rms_new_m=round(1000*np.sqrt((rn.drag_resid_da[storm]**2).mean()),1) if storm.any() else None))
pd.set_option("display.width",250)
print(pd.DataFrame(rows).to_string(index=False))
