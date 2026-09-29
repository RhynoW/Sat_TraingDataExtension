#!/usr/bin/env python3
"""s1_fetch_density.py — 從 STORM-AI（Harvard Dataverse doi:10.7910/DVN/U6K6MJ）抽出密度真值與初始狀態。

只抽 sat_density/*.csv 與 *initial_states*.csv（HTTP Range 讀遠端 zip），不下載 GOES/OMNI2
（佔 42 GB 的 >95%）。太空天氣改用 Celestrak SW-All.csv 與 NASA SPDF OMNI2 年檔（小且連續）。

輸出：
  data/density_all.parquet   sat, t, rho_true（去重、去非物理值）
  data/initial_states_all.parquet  sat, file_id, t0, a, e, i, raan, argp, nu, lat, lon, alt_km
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE))
from remote_zip import open_remote_zip  # noqa: E402

# Dataverse file id → 說明（private_eval 各任務包；phase_1 sat_density 已本地下載）
REMOTE = {
    13456848: "2000-2010 CHAMP", 13456849: "2002-2010 GRACE 1", 13456851: "2002-2010 GRACE 2",
    13457036: "2014-2020 SWARM B", 13457037: "2014-2020 SWARM C", 13457034: "2018-2020 GRACE-FO 1",
    13456847: "2020 SWARM A", 13457035: "2021-2024 GRACE-FO 1", 13456852: "2021-2024 SWARM A",
    13456850: "2021-2024 SWARM B", 13456846: "2021-2024 SWARM C",
}
LOCAL_DENS = DATA / "f_13456842.zip"      # phase_1 sat_density.zip
LOCAL_INIT = [DATA / "f_13456841.zip"]    # phase_1 initial_states.zip
PAT = re.compile(r"([a-z0-9_\-]{6})-(\d+)-(\d{8})_to_(\d{8})\.csv$")
SATNAME = {"swarma": "SWARM-A", "swarmb": "SWARM-B", "swarmc": "SWARM-C", "gr-of1": "GRACE-FO1",
           "grace1": "GRACE-1", "grace2": "GRACE-2", "champ_": "CHAMP"}


def parse_density(name: str, raw: bytes) -> pd.DataFrame | None:
    m = PAT.search(name)
    if not m:
        return None
    d = pd.read_csv(io.BytesIO(raw))
    if d.shape[1] < 2:
        return None
    d.columns = ["t", "rho_true"]
    d["t"] = pd.to_datetime(d["t"], errors="coerce")
    d["rho_true"] = pd.to_numeric(d["rho_true"], errors="coerce")
    d = d[np.isfinite(d["rho_true"]) & (d["rho_true"] > 1e-16) & (d["rho_true"] < 1e-9)]
    d["sat"] = SATNAME.get(m.group(1), m.group(1))
    d["file_id"] = int(m.group(2))
    return d.dropna(subset=["t"])


def parse_init(raw: bytes) -> pd.DataFrame:
    d = pd.read_csv(io.BytesIO(raw))
    d = d.loc[:, [c for c in d.columns if not c.startswith("Unnamed")]]
    return d


def main():
    dens, inits = [], []
    # ── 本地 phase_1
    z = zipfile.ZipFile(LOCAL_DENS)
    for n in z.namelist():
        if n.startswith("sat_density/") and n.endswith(".csv"):
            d = parse_density(n, z.read(n))
            if d is not None:
                dens.append(d)
    for p in LOCAL_INIT:
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if not n.startswith("__") and n.endswith("initial_states.csv"):
                inits.append(parse_init(z.read(n)))
    print(f"phase_1 本地：密度檔 {len(dens)}")
    # ── 遠端 private_eval（只抽密度 + initial states）
    for fid, lbl in REMOTE.items():
        z, f = open_remote_zip(fid)
        names = [n for n in z.namelist() if not n.startswith("__") and "/._" not in n]
        dn = [n for n in names if "sat_density" in n and n.endswith(".csv")]
        inn = [n for n in names if n.endswith("initial_states.csv")]
        k0 = len(dens)
        for n in dn:
            d = parse_density(n, z.read(n))
            if d is not None:
                dens.append(d)
        for n in inn:
            inits.append(parse_init(z.read(n)))
        print(f"  {lbl}: 密度檔 {len(dens)-k0}／初始狀態檔 {len(inn)}；讀取 {f.nbytes/1e6:.1f} MB"
              f"（包大小 {f.size/1e9:.2f} GB）", flush=True)
    D = pd.concat(dens, ignore_index=True)
    D = D.sort_values(["sat", "t"]).drop_duplicates(["sat", "t"]).reset_index(drop=True)
    D.to_parquet(DATA / "density_all.parquet", index=False)
    I = pd.concat(inits, ignore_index=True)
    I.to_parquet(DATA / "initial_states_raw.parquet", index=False)
    print(f"密度：{len(D):,} 點；", D.groupby("sat")["t"].agg(["min", "max", "count"]).to_string())
    print(f"初始狀態：{len(I):,} 列")


if __name__ == "__main__":
    main()
