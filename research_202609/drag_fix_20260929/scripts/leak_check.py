import os, sys, glob
ROOT = r"F:\GitHub\Sat_TraingDataExtension"; sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
import three_layer_common_eval as T
from satdet import episodes_by_sat, load_drag_map, config
from compare_tle_vs_ephemeris import load_registry
tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
truth = pd.read_csv(tp); truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
eps = episodes_by_sat(truth)
reg = load_registry("data/url_registry.csv"); sats = list({v: k for k, v in reg["sat_name"].items()}.items())
for tag, csv in (("old", "data/drag/drag_resid_20260714.csv"), ("new", "data/drag/drag_resid_20260928.csv")):
    U = T.build_common_units(config.SPACE_DB, sats, load_drag_map(csv), eps)
    y = U["label"].to_numpy(); miss = (U["f_drag_max"] == 0).to_numpy()
    t = pd.to_datetime(U["t_ns"], utc=True)
    print(f"[{tag}] units={len(U)} drag缺值占比 正={miss[y==1].mean():.3f} 負={miss[y==0].mean():.3f} "
          f"AUC(缺值→正)={roc_auc_score(y, miss.astype(float)):.3f} AUC(f_drag_max)={roc_auc_score(y, U['f_drag_max']):.3f}")
    print(f"      單元時間範圍 {t.min().date()}~{t.max().date()}；07-14 後單元占比 正={(t[y==1]>'2026-07-14').mean():.3f} 負={(t[y==0]>'2026-07-14').mean():.3f}")
    U.to_parquet(os.path.join(os.path.dirname(__file__), f"units_{tag}.parquet"))
